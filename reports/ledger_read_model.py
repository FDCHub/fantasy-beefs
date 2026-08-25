"""
reports/ledger_read_model.py — authoritative accounting read models (S8-P3).

READ-ONLY, AND NOT AN ACCOUNTING SYSTEM. Nothing here posts, locks, commits or
derives a settlement figure of its own. Every monetary answer in this module
ultimately comes from ONE call to `economy.current_settle.current_settle()`,
which derives a GM's position from posted `ledger_entries` and is the sole
authority on what Current Settle means.

WHY THAT MATTERS MORE THAN IT LOOKS. Sprint 8 needs the same accounting in three
places: a GM reading their own Ledger, a commissioner reading twelve GM cards,
and a league reconciliation totalling them. The tempting shape is three
functions, each querying what its own response needs. That produces three
formulas that agree today and drift the first time one is corrected — and a
commissioner whose view of a GM disagrees with that GM's own view is worse than
no commissioner view at all.

So the dependency is a chain, not a fan:

    current_settle()            ← the authority, in economy/, untouched by P3
        └── gm_ledger()         ← the ONLY caller of it in this layer
              └── league_positions()   ← calls gm_ledger per team
                    └── league_reconciliation()  ← sums league_positions

`current_settle` is called in exactly one place in this module. The P3 suite
asserts that structurally, so a later "just add a quick query here" cannot pass
review by accident.

EXACT INTEGER CENTS, EVERYWHERE. Every monetary field is an int. No float, no
formatted string, no rounding. Whole-dollar presentation is the frontend's job
and happens once, at the moment of drawing (S7 `credits.js`); a read model that
returned "$65" would have made that decision for it and lost the cents.

WHAT THIS MODULE ADDS BEYOND `CurrentSettle`, AND ON WHAT AUTHORITY.

  held_open_challenges_cents
      `economy/challenge_escrow_view.team_open_challenge_escrow_cents()` — real
      escrow funded against challenges still in an OPEN response state. This is
      a genuine backend read, not a UI invention, and it is a SUBSET of
      `in_play_cents` rather than an addition to it: the money is already
      counted once as an asset, and reporting it separately says which part of
      In Play is not yet committed to an accepted wager. It is therefore
      reported beside the position and never added to a total.

  available_cents, total_virtual_stakes_cents
      GROUPINGS of authoritative terms, not new formulas — each is a sum of
      fields `CurrentSettle` already publishes, and each is documented at its
      definition. They exist so the frontend does not have to know which terms
      group together, which is exactly the knowledge that would become a second
      formula if it lived in JavaScript.

WHAT IT DELIBERATELY DOES NOT ADD. Several figures the Sprint 7 illustrative
Ledger showed have no authoritative source and are NOT manufactured here —
season winnings, per-award splits, and the Versus/Pool activity nets. They are
listed in `UNSOURCED_UI_FIELDS` as bounded seams for P4 rather than being
invented, because a number with no source behind it is worse in a ledger than a
number that is honestly absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from db.schema import FaabTransaction, League, Team
from economy.challenge_escrow_view import team_open_challenge_escrow_cents
from economy.current_settle import current_settle
from economy.top_off import TOPUP_BET


class LedgerReadModelError(ValueError):
    """A read model could not be produced from posted state."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_LEAGUE_NOT_FOUND = "LEAGUE_NOT_FOUND"
REASON_TEAM_NOT_IN_LEAGUE = "TEAM_NOT_IN_LEAGUE"


#: Illustrative Rev 4.2 Ledger fields with NO authoritative backend source.
#:
#: Named here so P4 binds what exists and leaves the rest honestly unresolved,
#: which is the presentation the accepted UI already uses for an unknown figure.
#: This is a seam register, not a to-do list: some of these may never have a
#: source, and inventing one to fill the cell is the failure mode it prevents.
UNSOURCED_UI_FIELDS = (
    "season_winnings — settled award credits are inside `wallet` and are not "
    "separately attributed by any posted door; reporting a figure would mean "
    "reconstructing it from bet history, which is a new derivation, not a read",
    "season_award_split — the POR fixes a total, not a per-award breakdown",
    "versus_activity_net / pool_activity_net — explanatory activity totals; the "
    "S7 model states these feed no total, and no posted door groups them",
    "bet_record — a win/loss record, not an amount; not accounting state",
)


# ── One GM's position ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GmLedger:
    """One GM's authoritative accounting position, in exact integer cents.

    The `CurrentSettle` components are carried through UNCHANGED and under
    their own names, so a reader can line this up against
    `economy/current_settle.py` term by term. Nothing is renamed for
    presentation — a rename is where a mapping error hides.
    """

    team_id: int
    team_name: str
    owner: str

    # ── Assets, verbatim from CurrentSettle ──────────────────────────────────
    wallet_cents: int
    weekly_min_live_cents: int
    min_reserve_cents: int
    expired_min_cents: int
    in_play_cents: int
    assets_cents: int

    # ── Obligations, verbatim from CurrentSettle ─────────────────────────────
    season_advance_cents: int
    topoff_issued_cents: int
    receivable_cents: int

    #: WP-15 — THE SKUNK OBLIGATION, WHICHEVER ERA STATED IT.
    #:
    #: These two were on `CurrentSettle` and stopped here, and the omission was
    #: not cosmetic. Under the Final POR a GM's Skunk is derived through event
    #: provenance and is NOT a `receivable:` balance, so a surface itemising the
    #: obligation as `-receivable_cents` drew ZERO for a GM who had really been
    #: assessed -- while `obligations_cents`, which the same row carries,
    #: included the fee. The total was right and the line item was blank, so the
    #: parts stopped summing to the whole for exactly the seasons the Final POR
    #: governs.
    #:
    #: `is_final_por` travels with it because a consumer cannot pick the right
    #: source without knowing the era, and inferring the era from which figure
    #: happens to be non-zero is how the next mapping error hides.
    skunk_cents: int
    is_final_por: bool

    obligations_cents: int

    # ── The result, verbatim from CurrentSettle ──────────────────────────────
    current_settle_cents: int

    # ── Reported beside the position, never added to it ──────────────────────
    held_open_challenges_cents: int

    @property
    def available_cents(self) -> int:
        """Spendable now: wallet plus released weekly minimum not yet spent.

        A GROUPING of two authoritative terms, not a new quantity. It is already
        net of anything held against an open challenge, because that money has
        left `wallet:` for `escrow:challenge:` — which is also why `held` is
        reported separately rather than subtracted again here.
        """
        return self.wallet_cents + self.weekly_min_live_cents

    @property
    def total_virtual_stakes_cents(self) -> int:
        """Season opening allocation plus approved Top-Offs.

        A GROUPING of two authoritative obligation terms. `receivable` is
        deliberately excluded: a Skunk receivable is an obligation but it is not
        virtual stakes issued to the GM, and folding it in here would make Total
        Virtual Stakes grow every time a fee was assessed.
        """
        return self.season_advance_cents + self.topoff_issued_cents

    def as_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "team_name": self.team_name,
            "owner": self.owner,
            "wallet_cents": self.wallet_cents,
            "weekly_min_live_cents": self.weekly_min_live_cents,
            "min_reserve_cents": self.min_reserve_cents,
            "expired_min_cents": self.expired_min_cents,
            "in_play_cents": self.in_play_cents,
            "assets_cents": self.assets_cents,
            "season_advance_cents": self.season_advance_cents,
            "topoff_issued_cents": self.topoff_issued_cents,
            "receivable_cents": self.receivable_cents,
            # WP-15 -- BOTH, or a Final POR GM's Skunk line reads zero while
            # the total beside it includes the fee.
            "skunk_cents": self.skunk_cents,
            "is_final_por": self.is_final_por,
            "obligations_cents": self.obligations_cents,
            "current_settle_cents": self.current_settle_cents,
            "held_open_challenges_cents": self.held_open_challenges_cents,
            "available_cents": self.available_cents,
            "total_virtual_stakes_cents": self.total_virtual_stakes_cents,
        }


def _league(db: Session, league_id: int) -> League:
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise LedgerReadModelError(REASON_LEAGUE_NOT_FOUND,
                                   f"League {league_id} not found")
    return league


def gm_ledger(db: Session, *, team_id: int, league_id: int) -> GmLedger:
    """One GM's position — THE single call site of `current_settle()` here.

    The season comes from the league row rather than from the caller. A caller
    that supplied it could ask for a season the league is not in and receive a
    confidently wrong allocation figure, and there would be nothing in the
    answer to show that had happened.
    """
    league = _league(db, league_id)

    team = db.query(Team).filter(Team.id == team_id).first()
    if team is None or team.league_id != league_id:
        raise LedgerReadModelError(
            REASON_TEAM_NOT_IN_LEAGUE,
            f"Team {team_id} is not a member of league {league_id}")

    # THE authority. Every monetary figure below is this call's output.
    settle = current_settle(db, team_id=team_id, league_id=league_id,
                            season=league.season)

    return GmLedger(
        team_id=settle.team_id,
        team_name=team.team_name,
        owner=team.owner,
        wallet_cents=settle.wallet_cents,
        weekly_min_live_cents=settle.weekly_min_live_cents,
        min_reserve_cents=settle.min_reserve_cents,
        expired_min_cents=settle.expired_min_cents,
        in_play_cents=settle.in_play_cents,
        assets_cents=settle.assets_cents,
        season_advance_cents=settle.season_advance_cents,
        topoff_issued_cents=settle.topoff_issued_cents,
        receivable_cents=settle.receivable_cents,
        skunk_cents=settle.skunk_cents,
        is_final_por=settle.is_final_por,
        obligations_cents=settle.obligations_cents,
        current_settle_cents=settle.current_settle_cents,
        held_open_challenges_cents=team_open_challenge_escrow_cents(db, team_id),
    )


# ── Every GM in one league ───────────────────────────────────────────────────

def league_positions(db: Session, *, league_id: int) -> list[GmLedger]:
    """Every GM's position in one league, ordered deterministically.

    MEMBERSHIP IS READ, NOT ASSUMED. The Rev 4.2 illustrative league has twelve
    GM cards; nothing here assumes twelve, or any other number. The roster is
    whatever `teams.league_id` says it is, so a league of eight or fourteen
    produces eight or fourteen positions.

    Ordered by team_id. That is implementation determinism so a commissioner
    gets a stable list between refreshes, not a product rule about card order —
    Rev 4.2 owns the presentation order.

    Calls `gm_ledger` per team rather than reimplementing it, so the figure a
    commissioner reads for a GM is produced by the arithmetic that GM's own
    Ledger tab reads. A second query shaped for this response is exactly how
    the two views come to disagree.
    """
    _league(db, league_id)      # 404 for an absent league, before any position

    teams = (db.query(Team)
             .filter(Team.league_id == league_id)
             .order_by(Team.id)
             .all())
    return [gm_ledger(db, team_id=t.id, league_id=league_id) for t in teams]


# ── League reconciliation ────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExceptionRow:
    """Something a commissioner must SEE without it entering a total."""
    count: int
    cents: int
    settlement_liability: bool
    note: str

    def as_dict(self) -> dict:
        return {"count": self.count, "cents": self.cents,
                "settlement_liability": self.settlement_liability,
                "note": self.note}


@dataclass(frozen=True)
class LeagueReconciliation:
    """The league's position, aggregated from the individual GM positions.

    NOT A SECOND ACCOUNTING PATH. Every aggregate below is the sum of the
    `league_positions()` outputs — the same objects the commissioner's GM cards
    are drawn from. Nothing here re-queries the ledger, so the roll-up cannot
    disagree with the rows that explain it, and `reconciles` is a real check of
    that rather than a restatement of it.
    """

    league_id: int
    season: int
    position_count: int

    aggregate_assets_cents: int
    aggregate_obligations_cents: int
    aggregate_current_settle_cents: int
    aggregate_total_virtual_stakes_cents: int

    #: Sum of each GM's own `current_settle_cents`, computed independently of
    #: the assets/obligations aggregates so the two can be COMPARED.
    sum_of_gm_settles_cents: int

    exceptions: dict[str, ExceptionRow] = field(default_factory=dict)

    @property
    def reconciles(self) -> bool:
        """Whether the league arithmetic closes.

        Two independent routes to the same number: aggregate assets minus
        aggregate obligations, and the sum of the GMs' own Current Settle
        figures. They are equal iff every position was included exactly once
        and no term was dropped in aggregation. Comparing a number with itself
        would prove nothing, which is why both are carried.
        """
        return (self.aggregate_assets_cents - self.aggregate_obligations_cents
                == self.sum_of_gm_settles_cents
                == self.aggregate_current_settle_cents)

    def as_dict(self) -> dict:
        return {
            "league_id": self.league_id,
            "season": self.season,
            "position_count": self.position_count,
            "aggregate_assets_cents": self.aggregate_assets_cents,
            "aggregate_obligations_cents": self.aggregate_obligations_cents,
            "aggregate_current_settle_cents": self.aggregate_current_settle_cents,
            "aggregate_total_virtual_stakes_cents":
                self.aggregate_total_virtual_stakes_cents,
            "sum_of_gm_settles_cents": self.sum_of_gm_settles_cents,
            "reconciles": self.reconciles,
            "exceptions": {k: v.as_dict() for k, v in self.exceptions.items()},
        }


def _open_top_off_exception(db: Session, league_id: int) -> ExceptionRow:
    """Requested but undecided Top-Offs.

    NOT A LIABILITY, and the reason is structural rather than a policy choice:
    `topoff_issued_cents` reads the approved-issuance DOOR in the ledger, so a
    pending request has posted nothing and contributes nothing to any position
    above. Reporting it here tells a commissioner what is waiting on them
    without any total moving.
    """
    rows = (db.query(FaabTransaction)
            .filter(FaabTransaction.league_id == league_id,
                    FaabTransaction.type == TOPUP_BET,
                    FaabTransaction.decision == "pending")
            .all())
    return ExceptionRow(
        count=len(rows),
        cents=sum(int(r.amount_cents or 0) for r in rows),
        settlement_liability=False,
        note=("Requested, not decided. Nothing is issued until a commissioner "
              "approves, and nothing is counted until it is issued."),
    )


def _pending_hold_exception(positions: list[GmLedger]) -> ExceptionRow:
    """Credits committed to challenges still open.

    NOT A SETTLEMENT LIABILITY. The money is already inside each GM's `in_play`
    assets — it left the wallet when the challenge was issued — so adding it
    again as a liability would double-count it against the GM. It is reported so
    a commissioner can see how much of the league's In Play is not yet committed
    to an accepted wager.
    """
    holding = [p for p in positions if p.held_open_challenges_cents != 0]
    return ExceptionRow(
        count=len(holding),
        cents=sum(p.held_open_challenges_cents for p in holding),
        settlement_liability=False,
        note=("Held against open challenges. Already inside In Play as an "
              "asset; reported here, never added to a total."),
    )


def league_reconciliation(db: Session, *, league_id: int) -> LeagueReconciliation:
    """Aggregate the league's GM positions.

    Derived entirely from `league_positions()` — one pass over the same objects
    the GM cards are built from.
    """
    league = _league(db, league_id)
    positions = league_positions(db, league_id=league_id)

    return LeagueReconciliation(
        league_id=league_id,
        season=league.season,
        position_count=len(positions),
        aggregate_assets_cents=sum(p.assets_cents for p in positions),
        aggregate_obligations_cents=sum(p.obligations_cents for p in positions),
        aggregate_current_settle_cents=sum(
            p.assets_cents - p.obligations_cents for p in positions),
        aggregate_total_virtual_stakes_cents=sum(
            p.total_virtual_stakes_cents for p in positions),
        sum_of_gm_settles_cents=sum(p.current_settle_cents for p in positions),
        exceptions={
            "open_top_offs": _open_top_off_exception(db, league_id),
            "pending_challenge_holds": _pending_hold_exception(positions),
        },
    )