"""
economy/external_mapping.py — optional external-stakes reconciliation (WP-15, §22).

WHAT THIS IS FOR. Some leagues settle up outside FantasyStakes — cash, an app,
an honour system. Such a league wants one number per GM at season end: "what do
I owe, or what am I owed?" That number is not the ledger's, because the ledger
correctly says a MINTED championship pot is nobody's debt. This module answers
the external question without changing the internal answer.

── WHAT IT IS EMPHATICALLY NOT ─────────────────────────────────────────────

    NOT a ledger posting.       Nothing here writes. No account moves.
    NOT a deposit.              No real money is described, received or held.
    NOT payment processing.     No processor, no instrument, no transfer.
    NOT the FantasyStakes Score. Competitive standing is untouched and unread.

It is a MAPPING LAYER, and it is optional. A league that does not reconcile
externally never calls it, and nothing else in the economy depends on it.

── THE ATTRIBUTION RULE, AND WHY IT IS NOTIONAL ────────────────────────────

WP-5 made championship pots LEAGUE-LEVEL MINTED allocations: no GM was debited
to create one and no GM owes anything because one exists. That is the internal
truth and it does not change here.

But a league reconciling externally has to decide who stood behind the money the
league played for. §22's rule: minted championship allocations are attributed
NOTIONALLY across the frozen season participant field as EQUAL-SHARE DUES.

    dues(GM) = total minted championship VC / |frozen participant field|

Equal share, because the pot was allocated by the league rather than bought by
anyone — there is no per-GM contribution to reproduce, and weighting by
anything else would invent a subscription nobody agreed to.

THE FIELD IS THE FROZEN ONE, not today's roster. A GM who left in Week 9 was
part of the league the pot was allocated for; excluding them would silently
raise everybody else's share, and including a GM who joined in Week 12 would
charge them for a season they did not play. The field comes from
`SeasonAllocation` — the GMs who were actually issued an opening allocation for
this season — which is the same "funded field" the championship machinery
already uses.

── AWARDS ARE NOT COUNTED TWICE, AND THAT IS THE WHOLE ARITHMETIC ──────────

A championship award reaches the GM as a WALLET CREDIT. Current Settle already
counts it, once, through the Wallet term. So the mapping adds the notional dues
as an obligation and adds NOTHING for the award — the award is already inside
the settle figure it starts from.

    owed(GM) = dues(GM) − current_settle(GM)

    positive  the GM owes the league
    negative  the league owes the GM

`SUM(owed) == SUM(receivable)` falls out by construction and is asserted rather
than assumed: the dues sum to exactly the minted total (remainder included), and
the settle figures sum to whatever the ledger says, so the two sides balance
because both are derived from the same posted state.

── EXACT CENTS, CANONICAL REMAINDER ───────────────────────────────────────

Integer cents; no float participates. A minted total that does not divide by the
field size leaves a remainder, assigned ONE CENT AT A TIME BY ASCENDING
PARTICIPANT ID — the same convention `economy.skunk.split_by_canonical_id` and
`economy.championship_distribution` already use. It is arithmetic determinism
only: it decides who holds an extra cent, never who owes more in any meaningful
sense.
"""

from __future__ import annotations

from dataclasses import dataclass

from economy.economy_events import CHAMPIONSHIP_PILLARS
from ruleset import is_final_por


class ExternalMappingError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_WRONG_ERA = "MAPPING_WRONG_ERA"
REASON_NO_FIELD = "MAPPING_NO_PARTICIPANT_FIELD"
REASON_LEAGUE_NOT_FOUND = "MAPPING_LEAGUE_NOT_FOUND"


@dataclass(frozen=True)
class ParticipantMapping:
    team_id: int
    #: Notional equal-share dues for the minted championship allocations.
    #: NOT a debt in the ledger and not posted anywhere.
    notional_dues_cents: int
    #: This GM's Current Settle, unchanged and unmodified by the mapping.
    current_settle_cents: int

    @property
    def owed_cents(self) -> int:
        """Positive: the GM owes the league. Negative: the league owes them."""
        return self.notional_dues_cents - self.current_settle_cents


@dataclass(frozen=True)
class ExternalReconciliation:
    league_id: int
    season: int
    #: Every Credit minted into a championship pot this league-season.
    minted_championship_cents: int
    #: The frozen participant field, ascending.
    participant_team_ids: tuple[int, ...]
    rows: tuple[ParticipantMapping, ...]

    @property
    def total_dues_cents(self) -> int:
        return sum(r.notional_dues_cents for r in self.rows)

    @property
    def total_owed_cents(self) -> int:
        return sum(r.owed_cents for r in self.rows)

    @property
    def total_receivable_cents(self) -> int:
        """The other side of the same statement.

        A GM's `owed` is positive when they owe the league; the league's
        RECEIVABLE from the field is that same sum. Reported separately so a
        caller can assert the identity rather than being told it holds."""
        return sum(r.owed_cents for r in self.rows)

    @property
    def balances(self) -> bool:
        return self.total_owed_cents == self.total_receivable_cents

    def as_dict(self) -> dict:
        return {
            "league_id": self.league_id,
            "season": self.season,
            "minted_championship_cents": self.minted_championship_cents,
            "participant_team_ids": list(self.participant_team_ids),
            "total_dues_cents": self.total_dues_cents,
            "total_owed_cents": self.total_owed_cents,
            "balances": self.balances,
            "rows": [{"team_id": r.team_id,
                      "notional_dues_cents": r.notional_dues_cents,
                      "current_settle_cents": r.current_settle_cents,
                      "owed_cents": r.owed_cents} for r in self.rows],
        }


def frozen_participant_field(db, *, league_id: int,
                             season: int) -> tuple[int, ...]:
    """The GMs this season was actually allocated for, ascending.

    FROM `SeasonAllocation`, NOT FROM `teams`. A GM who left mid-season was part
    of the league the pot was allocated for and stays in the field; a GM who
    joined afterwards was not and does not. Reading today's roster would move
    every other GM's share whenever the roster moved.
    """
    from db.schema import SeasonAllocation

    db.flush()
    rows = (db.query(SeasonAllocation.team_id)
            .filter(SeasonAllocation.league_id == league_id,
                    SeasonAllocation.season == season)
            .distinct().all())
    return tuple(sorted(int(r[0]) for r in rows))


def minted_championship_cents(db, *, league_id: int, season: int) -> int:
    """Every Credit MINTED into a championship pot this league-season.

    MINTED, NOT FUNDED. The distinction is the whole basis of §22's rule: a
    minted allocation is the league's, stands behind nobody, and is what the
    external field is notionally being asked to have stood behind. Credits that
    reached a pot by any other route are NOT included — an unspent Weekly
    Minimum swept in by WP-4 was already the GM's own money and was already
    counted against them when it left their asset position, and a Top-Off's pot
    leg (WP-6) rides on an obligation the GM already carries.

    Read from the issuance tally, which is exactly the minted total and nothing
    else. Its debit balance is negated once to give a positive magnitude.
    """
    from economy.economy_events import championship_issuance_account
    from ledger.ledger import _balance_of_in_session

    db.flush()
    return -_balance_of_in_session(
        db, championship_issuance_account(league_id, season))


def split_equally(total_cents: int, team_ids) -> dict[int, int]:
    """Equal shares in exact cents, remainder by ASCENDING participant id.

    The same convention `split_by_canonical_id` and the canonical championship
    split already use. Arithmetic determinism only: it decides who holds an
    extra cent, never anything competitive.
    """
    ordered = sorted(int(t) for t in team_ids)
    if not ordered:
        return {}
    base, remainder = divmod(int(total_cents), len(ordered))
    return {team_id: base + (1 if index < remainder else 0)
            for index, team_id in enumerate(ordered)}


def reconcile(db, *, league_id: int,
              season: int | None = None) -> ExternalReconciliation:
    """The optional external statement. READS ONLY — writes nothing at all."""
    from db.schema import League
    from economy.current_settle import current_settle

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise ExternalMappingError(REASON_LEAGUE_NOT_FOUND,
                                   f"league {league_id} not found")
    season = league.season if season is None else season

    if not is_final_por(db, league_id=league_id, season=season):
        raise ExternalMappingError(
            REASON_WRONG_ERA,
            f"league {league_id} season {season} is governed by the legacy "
            f"ruleset, whose championship pots were funded by real per-GM "
            f"contributions already carried as obligations. Attributing "
            f"notional dues on top would charge every GM twice.")

    field = frozen_participant_field(db, league_id=league_id, season=season)
    if not field:
        raise ExternalMappingError(
            REASON_NO_FIELD,
            f"league {league_id} season {season} has no SeasonAllocation rows, "
            f"so the frozen participant field cannot be stated. Refusing to "
            f"attribute dues across a field derived from today's roster.")

    minted = minted_championship_cents(db, league_id=league_id, season=season)
    dues = split_equally(minted, field)

    rows = tuple(
        ParticipantMapping(
            team_id=team_id,
            notional_dues_cents=dues[team_id],
            # NOTHING IS ADDED FOR A CHAMPIONSHIP AWARD. It reached the GM as a
            # Wallet credit and Current Settle already counts it there, once.
            current_settle_cents=current_settle(
                db, team_id=team_id, league_id=league_id,
                season=season).current_settle_cents)
        for team_id in field)

    return ExternalReconciliation(
        league_id=league_id, season=season,
        minted_championship_cents=minted,
        participant_team_ids=field, rows=rows)


#: Named for the certification and for any reader checking §22's claim: the
#: pillars whose pots may be minted at all. The Points pot is never minted, so
#: it contributes nothing to notional dues — its money is Skunk the GMs were
#: really assessed, and that is already an obligation each of them carries.
MINTABLE_PILLARS_FOR_DUES: tuple[str, ...] = tuple(
    p for p in CHAMPIONSHIP_PILLARS if p != "points")
