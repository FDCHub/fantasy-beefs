"""
Season-end economic postings (S5-P3 §3-§6).

Four operations, each exactly-once, each its own callable so the close
orchestrator sequences them rather than hiding them:

    sweep_championship_reserves    reserve:{team}    -> championship:{league}
    consolidate_legacy_championship  "championship"  -> championship:{league}
    distribute_championship        championship:{league} -> winner Wallets
    reconcile_expired_minimum      expired_min:{team}  -> wallet:{team}

WHY THE RESERVE SWEEP CHANGES NO GM'S CURRENT SETTLE. `reserve:{team}` is
GM-keyed for provenance but was economically committed to the Championship pot
at activation, and S5-P2 therefore excludes it from the settlement-relevant
asset set. Moving it to `championship:{league_id}` is account consolidation, not
a refund, not a GM asset transfer, and emphatically NOT a reduction of the
opening Season Allocation obligation — the 22000 was advanced regardless of
where the 8000 later sits. A close that quietly netted the sweep against the
advance would forgive a real obligation.

WHY THE EXPIRED-MINIMUM RETURN ALSO CHANGES NOTHING. `expired_min:{team}` and
`wallet:{team}` are both settlement-relevant assets of the SAME GM, so the
return is a reclassification. Current Settle moves by exactly zero, which is the
same reason expiry itself did in S5-P1.

RECEIVABLES ARE NOT COLLECTED HERE, DELIBERATELY. Skunk is ledger-only by owner
ruling S5-R1, and no controlling non-superseded authority requires an automatic
Wallet debit or award seizure against `receivable:{team}` — searched across the
merged Ledger, BAB Economy and Additional Protocol sections for any collection,
seizure, netting, withholding or offset rule and found none. So the receivable
stays posted and Current Settle nets it arithmetically. Inventing a collection
posting here would move real Credits on an authority that does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from economy.championship import championship_distribution
from economy.economy_events import (
    DOOR_CHAMPIONSHIP_DISTRIBUTION,
    DuplicateEconomyEvent,
    DOOR_EXPIRED_MINIMUM_RECONCILIATION,
    DOOR_LEGACY_CHAMPIONSHIP_CONSOLIDATION,
    DOOR_RESERVE_SWEEP,
    EVENT_CHAMPIONSHIP_DISTRIBUTION,
    EVENT_EXPIRED_MINIMUM_RECONCILIATION,
    EVENT_LEGACY_CHAMPIONSHIP_CONSOLIDATION,
    EVENT_RESERVE_SWEEP,
    LEGACY_CHAMPIONSHIP_ACCOUNT,
    championship_account,
    expired_min_account,
    gm_season_key,
    league_season_key,
    record_event,
    reserve_account,
    wallet_account,
)
from ledger.ledger import _balance_of_in_session, post as ledger_post

#: The accepted default split. Reused, never recomputed.
DEFAULT_CHAMPIONSHIP_SPLIT = [60, 30, 10]


class SeasonReconciliationError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_AMBIGUOUS_LEGACY_POT = "AMBIGUOUS_LEGACY_POT"
REASON_EMPTY_POT = "EMPTY_POT"
REASON_NO_STANDINGS = "NO_STANDINGS"
REASON_NO_WALLET = "NO_WALLET"


@dataclass(frozen=True)
class SweepResult:
    league_id: int
    season: int
    swept: tuple[tuple[int, int], ...]
    total_cents: int


@dataclass(frozen=True)
class ChampionshipResult:
    league_id: int
    season: int
    pot_cents: int
    placements: tuple[tuple[int, int, int, int], ...]   # place, team, pct, cents


@dataclass(frozen=True)
class ExpiredMinResult:
    league_id: int
    season: int
    returned: tuple[tuple[int, int], ...]
    total_cents: int


def _teams(db, league_id: int):
    """Ascending team id — the deterministic lock and posting order every
    multi-GM writer in Sprint 5 uses, so concurrent whole-league jobs queue
    rather than deadlock."""
    from db.schema import Team

    return (db.query(Team).filter(Team.league_id == league_id)
            .order_by(Team.id).all())


# ── §3 Championship Reserve sweep ─────────────────────────────────────────────

def sweep_championship_reserves(db, *, league_id: int,
                                now: datetime | None = None) -> SweepResult:
    """Consolidate every `reserve:{team}` into `championship:{league_id}`.

    ONE posting for the whole league, not one per GM: the sweep is a single
    economic event and a partial sweep is not a state the close may observe. A
    GM whose reserve is already zero contributes no leg.
    """
    from db.schema import League

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    season = league.season
    db.flush()

    legs: list[tuple[str, int]] = []
    swept: list[tuple[int, int]] = []
    total = 0
    for team in _teams(db, league_id):
        balance = _balance_of_in_session(db, reserve_account(team.id))
        if balance <= 0:
            continue
        legs.append((reserve_account(team.id), -balance))
        swept.append((team.id, balance))
        total += balance

    posting_id = None
    if total > 0:
        legs.append((championship_account(league_id), total))
        posting_id = ledger_post(legs, door=DOOR_RESERVE_SWEEP, session=db)

    # The event row is written even for a zero sweep, so a league whose reserves
    # were already consolidated records the step as done and a retry is a no-op
    # rather than a re-examination of balances that may since have changed.
    record_event(db, event_key=league_season_key(EVENT_RESERVE_SWEEP,
                                                 league_id, season),
                 league_id=league_id, season=season,
                 event_type=EVENT_RESERVE_SWEEP, amount_cents=total,
                 posting_id=posting_id, now=now)

    return SweepResult(league_id=league_id, season=season,
                       swept=tuple(swept), total_cents=total)


# ── §4 legacy bare-championship consolidation ─────────────────────────────────

def consolidate_legacy_championship(db, *, league_id: int,
                                    now: datetime | None = None) -> int:
    """Move any bare `championship` balance into the league-scoped account.

    ATTRIBUTION MUST BE DETERMINISTIC OR THIS REFUSES. The bare account is
    global and predates league scoping, so with more than one league in the
    database there is no way to know whose money it is — and splitting it, or
    assigning it to the league being closed, would be inventing provenance.
    With exactly one league the attribution is unambiguous.

    Returns the consolidated amount, which is 0 in the expected case: the S5-P3
    preflight found no reachable data carrying a nonzero legacy balance, and
    this function manufactures no movement when there is nothing to move.
    """
    from db.schema import League

    now = now or datetime.now(timezone.utc)
    db.flush()
    legacy = _balance_of_in_session(db, LEGACY_CHAMPIONSHIP_ACCOUNT)
    if legacy == 0:
        return 0

    league_count = db.query(League).count()
    if league_count != 1:
        raise SeasonReconciliationError(
            REASON_AMBIGUOUS_LEGACY_POT,
            f'the bare "championship" account holds {legacy} cents but the '
            f"database carries {league_count} leagues. That account is global "
            f"and predates league scoping, so its attribution is ambiguous; "
            f"refusing to guess which league it belongs to.")

    league = db.query(League).filter(League.id == league_id).first()
    season = league.season
    posting_id = ledger_post(
        [(LEGACY_CHAMPIONSHIP_ACCOUNT, -legacy),
         (championship_account(league_id), legacy)],
        door=DOOR_LEGACY_CHAMPIONSHIP_CONSOLIDATION, session=db)
    record_event(db,
                 event_key=league_season_key(
                     EVENT_LEGACY_CHAMPIONSHIP_CONSOLIDATION, league_id, season),
                 league_id=league_id, season=season,
                 event_type=EVENT_LEGACY_CHAMPIONSHIP_CONSOLIDATION,
                 amount_cents=legacy, posting_id=posting_id, now=now)
    return legacy


# ── §5 Championship distribution ──────────────────────────────────────────────

def default_standings_order(db, *, league_id: int, league) -> list[int]:
    """Final rank order by regular-season Points For, best first.

    Ties break on ascending canonical team id — the same tie-break convention
    used everywhere else in this codebase, so a reader who has learned it once
    can predict it here. Tests may pass an explicit recorded order instead;
    §5 permits recorded/synthetic authoritative final standings for Sprint 5,
    and Sprint 6 will supply live Yahoo-derived standings."""
    from economy.skunk import season_points_for

    totals = season_points_for(db, league_id=league_id, league=league)
    return [team_id for team_id, _ in
            sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))]


def distribute_championship(db, *, league_id: int,
                            standings_order: list[int] | None = None,
                            split: list[int] | None = None,
                            now: datetime | None = None) -> ChampionshipResult:
    """Pay the Championship pot out by the accepted 60/30/10 rule.

    THE ARITHMETIC IS NOT REIMPLEMENTED. `championship_distribution()` is the
    accepted pure function and is called unchanged, including its remainder
    rule: every ordinary place floors, and the ENTIRE indivisible remainder goes
    to first place. That rule is deliberately different from the Pool's §6.3
    canonical-id spread, and collapsing the two would silently change payouts.
    """
    from db.schema import League, Wallet

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    season = league.season
    split = split or DEFAULT_CHAMPIONSHIP_SPLIT

    db.flush()
    pot = _balance_of_in_session(db, championship_account(league_id))
    if pot <= 0:
        raise SeasonReconciliationError(
            REASON_EMPTY_POT,
            f"championship:{league_id} holds {pot} cents; nothing to distribute.")

    order = standings_order or default_standings_order(db, league_id=league_id,
                                                       league=league)
    if len(order) < len(split):
        raise SeasonReconciliationError(
            REASON_NO_STANDINGS,
            f"league {league_id} has {len(order)} ranked teams but the split "
            f"names {len(split)} places; refusing to distribute against an "
            f"incomplete ranking.")
    order = order[:len(split)]

    for team_id in order:
        if db.query(Wallet).filter(Wallet.team_id == team_id).first() is None:
            raise SeasonReconciliationError(
                REASON_NO_WALLET,
                f"placed team {team_id} has no wallet; refusing to pay a "
                f"subset of the placements.")

    placements = championship_distribution(pot, list(split), list(order))
    paid = sum(amount for _, _, _, amount in placements)
    if paid != pot:
        raise SeasonReconciliationError(
            "CONSERVATION_VIOLATION",
            f"placements total {paid} for a pot of {pot}.")

    legs = [(championship_account(league_id), -pot)]
    legs.extend((wallet_account(team_id), amount)
                for _, team_id, _, amount in placements if amount > 0)
    posting_id = ledger_post(legs, door=DOOR_CHAMPIONSHIP_DISTRIBUTION,
                             session=db)
    record_event(db, event_key=league_season_key(
                     EVENT_CHAMPIONSHIP_DISTRIBUTION, league_id, season),
                 league_id=league_id, season=season,
                 event_type=EVENT_CHAMPIONSHIP_DISTRIBUTION,
                 amount_cents=pot, posting_id=posting_id, now=now)

    return ChampionshipResult(league_id=league_id, season=season, pot_cents=pot,
                              placements=tuple(placements))


# ── §6 expired Weekly Minimum reconciliation ──────────────────────────────────

def reconcile_expired_minimum(db, *, league_id: int,
                              now: datetime | None = None) -> ExpiredMinResult:
    """Credit each GM's `expired_min:` back to their own Wallet.

    PER-GM EVENT KEYS, not one league key. A GM added mid-close, or a partially
    completed run, must be able to converge without re-crediting the GMs already
    reconciled — and a per-GM key is what makes each one independently
    exactly-once.

    Same GM before and after, so Current Settle moves by exactly zero. No
    issuance, no championship sweep, no obligation reduction and no
    commissioner-selectable destination.
    """
    from db.schema import League

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    season = league.season
    db.flush()

    returned: list[tuple[int, int]] = []
    total = 0
    for team in _teams(db, league_id):
        key = gm_season_key(EVENT_EXPIRED_MINIMUM_RECONCILIATION, league_id,
                            season, team.id)
        savepoint = db.begin_nested()
        try:
            balance = _balance_of_in_session(db, expired_min_account(team.id))
            posting_id = None
            if balance > 0:
                posting_id = ledger_post(
                    [(expired_min_account(team.id), -balance),
                     (wallet_account(team.id), balance)],
                    door=DOOR_EXPIRED_MINIMUM_RECONCILIATION, session=db)
            record_event(db, event_key=key, league_id=league_id, season=season,
                         team_id=team.id,
                         event_type=EVENT_EXPIRED_MINIMUM_RECONCILIATION,
                         amount_cents=balance, posting_id=posting_id, now=now)
            savepoint.commit()
            if balance > 0:
                returned.append((team.id, balance))
                total += balance
        except DuplicateEconomyEvent:
            # This GM was already reconciled — by a partially completed earlier
            # run or a concurrent worker. Roll back only their savepoint and
            # continue; aborting would un-reconcile the GMs already done.
            savepoint.rollback()
        except Exception:
            savepoint.rollback()
            raise

    db.flush()
    return ExpiredMinResult(league_id=league_id, season=season,
                            returned=tuple(returned), total_cents=total)