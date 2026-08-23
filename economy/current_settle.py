"""
Current Settle — DERIVED from posted Ledger state (S5-P2 §7).

    Current Settle = settlement-relevant GM assets − GM obligations

    positive  the league owes the GM
    negative  the GM owes

NEVER STORED, NEVER INCREMENTED, NEVER READ FROM Wallet.balance. There is no
Current Settle column and no cached total anywhere in this module — every call
recomputes from `ledger_entries`. A stored figure would be one more thing that
can disagree with the money, and the whole point of the ledger is that it
cannot.

THE MODEL IS UI/UX POR Rev 2.1's Model B, whose reconciled sample this module
reproduces exactly:

    assets       Wallet 152 + Weekly min left 10 + Weekly Min Reserve 120
                 + In Play 89 + Out of circulation 20 + awards 0   = 391
    obligations  advance 260 + skunk 20                            = 280
    Current Settle                                                 = +111

ASSETS (`wallet:`, `min:`, `min_reserve:`, `expired_min:`, GM-funded unresolved
escrow) and OBLIGATIONS (season advance, approved Top-Off, `receivable:`).

── WHAT THE FINAL POR RESHAPES (WP-15, §21) ────────────────────────────────

The identity is unchanged. Three of its inputs are, and each for a reason that
belongs to a package that already landed:

  · `expired_min:` LEAVES THE ASSET SET. WP-4 forfeits an unspent Weekly Minimum
    to the FantasyStakes Championship Pot at week close, so under the Final POR
    the account is never written and counting it would be counting a state the
    era cannot produce. It is excluded rather than deleted: a legacy season's
    balance is real and is still counted for that season.

  · THE PER-GM CHAMPIONSHIP OBLIGATION IS GONE, and it went structurally rather
    than by a subtraction here. `season_advance_cents` sums the GM's own credit
    legs under the allocation door; WP-5 stopped posting the `reserve:{team}`
    leg, so there is nothing to sum. The 8000 asymmetry the sample above
    describes simply does not arise for a Final POR season — its opening
    allocation moves Current Settle by exactly zero.

  · SKUNK IS DERIVED THROUGH EVENT PROVENANCE, not from the `receivable:`
    balance. That balance is neither Skunk-only (`betting/shortfall_sweep.py`
    also posts to it) nor season-scoped, and WP-12 made it correctable — a
    reversal and a restatement must net. `economy.skunk.cumulative_skunk_fees_
    cents` answers exactly "what did THIS league-season's Skunk machinery post
    against this GM", which is the obligation, and nets a correction for free.

THE SIX CONCEPTS STAY SEPARATE, and the dataclass keeps them in separate fields
on purpose (§21): Wallet, FantasyStakes Score, Current Settle, Championship
Pots, Top-Off principal and Skunk assessment are six different questions.
FantasyStakes Score is not here AT ALL — it is competitive and this is
accounting, and mixing them is the single most common way a surface ends up
telling a GM their standing depends on their balance. A Championship POT is a
league account and is not any GM's asset; a championship AWARD reaches the GM as
a Wallet credit and is counted there ONCE, by the Wallet term, with nothing
added on top.

DELIBERATELY EXCLUDED, each for a stated reason:

    reserve:{team}          GM-keyed for provenance only. Economically committed
                            to the Championship pot from activation — never
                            spendable, never releasable — so counting it as a GM
                            asset would overstate every GM by 80 Credits all
                            season. Model B's sample omits it, and 391 only
                            reconciles because it does.
    championship:{league}   league pot, not any GM's.
    skunk:{league}          league pot; the GM's side of Skunk is the
                            `receivable:` obligation, already counted.
    pool:{league}           NOT a generic GM asset. A collected weekly Pool
                            contribution has LEFT the GM: it funds four
                            occurrences whose outcome is not yet theirs. Pool
                            funding therefore genuinely reduces Current Settle,
                            and asserting a zero delta there would be forcing
                            the number rather than measuring it.

IN PLAY IS ATTRIBUTED, NOT ASSUMED. A shared escrow account is never counted
gross. Ownership comes from the provenance the funding path already recorded —
`ChallengeFundingLeg` for challenge and challenge-derived escrow, `Bet.wallet`
for a plain single-GM wager. An escrow account whose balance cannot be
attributed raises rather than being split by a guess; §11 is explicit that an
approximation here is a blocker, not a rounding choice.
"""

from __future__ import annotations

from dataclasses import dataclass

from economy.economy_events import (
    expired_min_account,
    min_reserve_account,
    receivable_account,
    wallet_account,
)
from ledger.ledger import _balance_of_in_session

DOOR_SEASON_ALLOCATION = "season_allocation"
DOOR_APPROVED_TOPOFF = "approved_bab_topoff"


class CurrentSettleError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_UNATTRIBUTABLE_ESCROW = "UNATTRIBUTABLE_ESCROW"


@dataclass(frozen=True)
class CurrentSettle:
    """One GM's position, with every component exposed.

    The components are returned, not just the total, because a bare number is
    untestable against Model B: the sample reconciles term by term, and a wrong
    component can cancel another wrong component in the total."""

    team_id: int
    wallet_cents: int
    weekly_min_live_cents: int
    min_reserve_cents: int
    expired_min_cents: int
    in_play_cents: int
    season_advance_cents: int
    topoff_issued_cents: int
    receivable_cents: int

    #: WP-15. Which era's asset set and Skunk derivation govern. Carried on the
    #: object so a reader can tell WHY a figure is shaped as it is without
    #: re-resolving the ruleset, and so the two properties below have one input
    #: rather than a hidden global.
    is_final_por: bool = False

    #: WP-15 — Skunk assessed against this GM THIS LEAGUE-SEASON, as a positive
    #: magnitude, derived through economy-event provenance. Populated only under
    #: the Final POR; a legacy season's obligation is `receivable_cents`, which
    #: is what it has always been.
    skunk_cents: int = 0

    @property
    def assets_cents(self) -> int:
        # `expired_min:` IS A LEGACY-ERA ASSET ONLY (WP-4/WP-15). A Final POR
        # season never writes the account, so this exclusion changes no figure
        # for a correctly-behaved season — it is what makes the OMISSION
        # deliberate and testable rather than an accident of the data.
        expired = 0 if self.is_final_por else self.expired_min_cents
        return (self.wallet_cents + self.weekly_min_live_cents
                + self.min_reserve_cents + expired
                + self.in_play_cents)

    @property
    def obligations_cents(self) -> int:
        # THE SKUNK OBLIGATION HAS ONE SOURCE PER ERA, NEVER BOTH. Adding the
        # provenance figure to the raw `receivable:` balance would count every
        # Skunk twice, because the provenance figure is derived FROM those same
        # postings. See the module docstring for why the Final POR reads the
        # provenance rather than the balance.
        skunk = self.skunk_cents if self.is_final_por else self.receivable_cents
        return (self.season_advance_cents + self.topoff_issued_cents + skunk)

    @property
    def current_settle_cents(self) -> int:
        return self.assets_cents - self.obligations_cents

    def as_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "wallet": self.wallet_cents,
            "weekly_min_live": self.weekly_min_live_cents,
            "min_reserve": self.min_reserve_cents,
            "expired_min": self.expired_min_cents,
            "in_play": self.in_play_cents,
            "assets": self.assets_cents,
            "season_advance": self.season_advance_cents,
            "topoff_issued": self.topoff_issued_cents,
            "receivable": self.receivable_cents,
            "skunk": self.skunk_cents,
            "is_final_por": self.is_final_por,
            "obligations": self.obligations_cents,
            "current_settle": self.current_settle_cents,
        }


# ── Components ────────────────────────────────────────────────────────────────

def live_weekly_minimum_cents(db, team_id: int) -> int:
    """Every live `min:{team}:{week}` balance, summed across weeks.

    Summed from the ledger by account pattern rather than from a week list: a
    caller that had to supply the weeks could omit one, and the omission would
    silently understate the GM."""
    from sqlalchemy import text

    db.flush()
    total = db.execute(text(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
        "WHERE account LIKE :pattern"), {"pattern": f"min:{team_id}:%"}).scalar()
    return int(total or 0)


def in_play_cents(db, team_id: int) -> int:
    """The GM's own funded interest in unresolved escrow — Model B's In Play.

    ATTRIBUTED FROM RECORDED PROVENANCE, in two layers:

      1. `ChallengeFundingLeg` — every challenge and challenge-derived escrow
         records (team_id, destination_account, amount, leg_kind). `fund` legs
         are positive and `reverse` legs negative by schema CHECK, so a plain
         SUM is the net unreversed interest.
      2. `escrow:{bet_id}` for a plain wager, owned by that bet's wallet.

    An escrow account holding money that neither layer explains raises
    UNATTRIBUTABLE_ESCROW. Splitting it evenly, or attributing it to the league,
    would put a number on a fact nobody recorded.
    """
    from sqlalchemy import text

    from db.schema import Bet, ChallengeFundingLeg, Wallet

    db.flush()

    # Every escrow account still holding money.
    open_escrows = {
        row[0]: int(row[1]) for row in db.execute(text(
            "SELECT account, SUM(amount_cents) FROM ledger_entries "
            "WHERE account LIKE 'escrow:%' GROUP BY account "
            "HAVING SUM(amount_cents) <> 0")).fetchall()
    }
    if not open_escrows:
        return 0

    total = 0
    for account, balance in open_escrows.items():
        legs = (db.query(ChallengeFundingLeg)
                .filter(ChallengeFundingLeg.destination_account == account)
                .all())
        if legs:
            by_team: dict[int, int] = {}
            for leg in legs:
                by_team[leg.team_id] = by_team.get(leg.team_id, 0) + int(
                    leg.amount_cents)
            funded = sum(by_team.values())
            if funded != balance:
                # A partially-settled escrow: the recorded provenance no longer
                # explains the balance. Refuse rather than scale a guess.
                raise CurrentSettleError(
                    REASON_UNATTRIBUTABLE_ESCROW,
                    f"{account} holds {balance} cents but its funding legs net "
                    f"to {funded}. Ownership is not deterministically "
                    f"attributable; refusing to approximate.")
            total += by_team.get(team_id, 0)
            continue

        # Layer 1b — S8-P4C-2: the Dynamic per-side ANCHOR escrow.
        #
        # WHY IT NEEDS ITS OWN LAYER. At the Handshake the pooled challenge
        # escrow migrates to `escrow:challenge:{id}:anchor`, and
        # `economy/dynamic_challenge.py` deliberately writes NO funding leg for
        # that move: a `reverse` leg means money went back to its funding
        # source, and this money went onward. That is correct for reversibility
        # accounting and it leaves this account with no leg naming it — so
        # Layer 1 cannot see it and, before this layer existed, the whole read
        # failed with UNATTRIBUTABLE_ESCROW the moment any Dynamic wager was
        # handshaken.
        #
        # It was invisible until P4C-2 because Dynamic had no HTTP path; nothing
        # about the money moved changed, only whether it could be reached.
        #
        # OWNERSHIP IS READ FROM THE GOVERNED HELPER, not inferred. The Anchor
        # is the ORIGINAL ISSUER by protocol (A4/§12) regardless of who authored
        # the accepted version, and `anchor_team_id` is where that rule lives.
        # The Derived side needs nothing here: the opponent funds it through the
        # normal `_fund` path, so it carries real legs and Layer 1 attributes it.
        if account.startswith("escrow:challenge:") and account.endswith(":anchor"):
            from db.schema import BeefChallenge, BeefProposal
            from economy.challenge_funding import anchor_team_id

            try:
                challenge_id = int(account.split(":")[2])
            except (IndexError, ValueError):
                challenge_id = None
            if challenge_id is not None:
                challenge = (db.query(BeefChallenge)
                             .filter(BeefChallenge.id == challenge_id).first())
                if challenge is not None:
                    proposal = (db.query(BeefProposal).filter(
                        BeefProposal.id == (challenge.accepted_proposal_id
                                            or challenge.active_proposal_id))
                        .first())
                    if proposal is not None:
                        if anchor_team_id(challenge, proposal) == team_id:
                            total += balance
                        continue

        # Layer 2 — a plain wager's escrow, owned by the betting wallet.
        if account.startswith("escrow:") and account.count(":") == 1:
            suffix = account.split(":", 1)[1]
            if suffix.isdigit():
                bet = db.query(Bet).filter(Bet.id == int(suffix)).first()
                if bet is not None:
                    wallet = (db.query(Wallet)
                              .filter(Wallet.id == bet.wallet_id).first())
                    if wallet is not None:
                        if wallet.team_id == team_id:
                            total += balance
                        continue
        raise CurrentSettleError(
            REASON_UNATTRIBUTABLE_ESCROW,
            f"{account} holds {balance} cents with no ChallengeFundingLeg "
            f"provenance and no resolvable owning Bet. Ownership cannot be "
            f"determined from posted state.")
    return total


def season_advance_cents(db, team_id: int, league_id: int, season: int) -> int:
    """The opening allocation issued to this GM, from posted state.

    Read as the sum of that GM's own credit legs under the `season_allocation`
    door — min_reserve plus reserve — rather than from the SeasonAllocation row.
    POSTED ECONOMICS ARE AUTHORITATIVE (§9): a row without a posting represents
    no advance, and this way the obligation can never disagree with the money
    that created it.

    The whole 22000 is the obligation even though only 14000 is a GM asset. The
    8000 Championship Reserve is advanced to the GM and immediately committed to
    the pot — that asymmetry is exactly why opening allocation moves Current
    Settle by −8000 rather than by zero.
    """
    from sqlalchemy import text

    db.flush()
    total = db.execute(text(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
        "WHERE door = :door AND account IN (:min_reserve, :reserve)"),
        {"door": DOOR_SEASON_ALLOCATION,
         "min_reserve": min_reserve_account(team_id),
         "reserve": f"reserve:{team_id}"}).scalar()
    return int(total or 0)


def topoff_issued_cents(db, team_id: int) -> int:
    """Approved Top-Off issued to this GM, from posted state.

    Only the canonical approved Top-Off door counts. A rejected or expired
    request posts nothing, so it contributes nothing here — §9's "do not infer
    obligations from request records when no issuance posting exists" is
    satisfied structurally rather than by filtering request statuses."""
    from sqlalchemy import text

    db.flush()
    total = db.execute(text(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
        "WHERE door = :door AND account = :wallet"),
        {"door": DOOR_APPROVED_TOPOFF,
         "wallet": wallet_account(team_id)}).scalar()
    return int(total or 0)


# ── Derivation ────────────────────────────────────────────────────────────────

def current_settle(db, *, team_id: int, league_id: int,
                   season: int) -> CurrentSettle:
    """Derive one GM's Current Settle from posted Ledger state."""
    from economy.skunk import cumulative_skunk_fees_cents
    from ruleset import is_final_por as _is_final_por

    db.flush()
    receivable = _balance_of_in_session(db, receivable_account(team_id))
    final_por = _is_final_por(db, league_id=league_id, season=season)
    # DERIVED ONLY FOR THE ERA THAT USES IT. The provenance query joins two
    # tables; running it for a legacy season would cost a join to produce a
    # number `obligations_cents` would then ignore.
    skunk = (cumulative_skunk_fees_cents(db, league_id=league_id,
                                         season=season, team_id=team_id)
             if final_por else 0)
    return CurrentSettle(
        team_id=team_id,
        is_final_por=final_por,
        skunk_cents=skunk,
        wallet_cents=_balance_of_in_session(db, wallet_account(team_id)),
        weekly_min_live_cents=live_weekly_minimum_cents(db, team_id),
        min_reserve_cents=_balance_of_in_session(
            db, min_reserve_account(team_id)),
        expired_min_cents=_balance_of_in_session(
            db, expired_min_account(team_id)),
        in_play_cents=in_play_cents(db, team_id),
        season_advance_cents=season_advance_cents(db, team_id, league_id,
                                                  season),
        topoff_issued_cents=topoff_issued_cents(db, team_id),
        # `receivable:` runs negative as an obligation grows, so the obligation
        # magnitude is its negation. Reading the raw balance would flip the sign
        # of every Skunk in the total.
        receivable_cents=-receivable,
    )