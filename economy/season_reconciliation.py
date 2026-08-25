"""
Season-end economic postings (S5-P3 §3-§6).

Four operations, each exactly-once, each its own callable so the close
orchestrator sequences them rather than hiding them:

    sweep_championship_reserves    reserve:{team}    -> championship:{league}
                                   LEGACY-ERA ONLY; retired by WP-5
    consolidate_legacy_championship  "championship"  -> championship:{league}
                                   LEGACY-ERA ONLY; retired by WP-5
    distribute_championship        championship:{league} -> winner Wallets
    reconcile_expired_minimum      expired_min:{team}  -> wallet:{team}
                                   LEGACY-ERA ONLY; retired by WP-4 for
                                   RULESET_FINAL_POR seasons

WHY THE RESERVE SWEEP CHANGES NO GM'S CURRENT SETTLE. `reserve:{team}` is
GM-keyed for provenance but was economically committed to the Championship pot
at activation, and S5-P2 therefore excludes it from the settlement-relevant
asset set. Moving it to `championship:{league_id}` is account consolidation, not
a refund, not a GM asset transfer, and emphatically NOT a reduction of the
opening Season Allocation obligation — the 22000 was advanced regardless of
where the 8000 later sits. A close that quietly netted the sweep against the
advance would forgive a real obligation.

WHY THE EXPIRED-MINIMUM RETURN ALSO CHANGES NOTHING, AND WHY IT NO LONGER RUNS.
`expired_min:{team}` and `wallet:{team}` are both settlement-relevant assets of
the SAME GM, so the return is a reclassification: Current Settle moves by
exactly zero, the same reason expiry itself did in S5-P1. That is the LEGACY
era. WP-4 replaced it — under `RULESET_FINAL_POR` an unspent Weekly Minimum is
forfeited to the FantasyStakes Championship Pot at WEEK close, so there is no
`expired_min:` balance at season end and no return to make. This step is
therefore RETIRED for Final POR seasons rather than left to run as a harmless
no-op: a retired path that still executes is a path that can be re-armed by a
future edit, and running it would also record a season-close event asserting a
return that the Final POR does not make.

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

from economy.championship_distribution import (
    distribute_championship as calculate_championship_distribution,
    podium_standings,
)
from economy.championship_podium import resolve_podium
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
    #: WP-5 — True when the era retired this step. A Final POR season never
    #: advanced a `reserve:{team}` at all, so a zero total here means two very
    #: different things across the two eras and the flag is what separates them.
    retired: bool = False


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
    #: True when the era retired this step (WP-4, `RULESET_FINAL_POR`). A caller
    #: can then tell "no GM had an expired balance" apart from "this era does
    #: not have expired balances", which the totals alone cannot distinguish.
    retired: bool = False
    #: (team_id, cents) that a retired run found and deliberately did not move.
    stranded: tuple[tuple[int, int], ...] = ()


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

    from ruleset import is_final_por

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    season = league.season
    db.flush()

    if is_final_por(db, league_id=league_id, season=season):
        # RETIRED FOR THIS ERA (WP-5). Model B never advanced a per-GM
        # Championship Reserve, so there is nothing to consolidate — and the
        # account it would consolidate INTO, `championship:{league}`, is itself
        # retired for Final POR writes. Returning empty rather than recording a
        # zero RESERVE_SWEEP event keeps the season's event log free of a claim
        # that a sweep happened, which is the same rule WP-4 applied to the
        # expired-Minimum return.
        return SweepResult(league_id=league_id, season=season, swept=(),
                           total_cents=0, retired=True)

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

    from ruleset import is_final_por

    now = now or datetime.now(timezone.utc)
    db.flush()

    league_row = db.query(League).filter(League.id == league_id).first()
    if league_row is not None and is_final_por(db, league_id=league_id,
                                               season=league_row.season):
        # RETIRED FOR THIS ERA (WP-5). This step's only effect is to WRITE to
        # `championship:{league}`, which is a retired namespace for a Final POR
        # season. Consolidating into it would create exactly the posting §11
        # retires, and would do so in the name of tidying up.
        #
        # THE LEGACY BALANCE IS LEFT WHERE IT IS, DELIBERATELY. It is a legacy
        # season's money; nothing here has the authority to re-home it into a
        # different era's pot, and in practice it is zero — the bare account was
        # written only by the shortfall sweep, which WP-5 also retires.
        return 0

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

# `default_standings_order` WAS HERE AND IS DELETED (WP1D).
#
# It ranked a league's teams by regular-season Points For and was the DEFAULT
# recipient order for the Championship Pot. That was a live money defect, not a
# style problem: a league whose highest regular-season scorers all lost in the
# first playoff round paid 60/30/10 to three eliminated teams while the actual
# champion received nothing.
#
# DELETED RATHER THAN KEPT AS A READ MODEL, because after this package it had no
# caller at all. The Skunk Pot — the one payout for which season-long scoring IS
# the right authority — ranks through `economy.skunk.season_points_for` and
# always did; `reports/standings.py::_compute_standings_order` serves the
# reporting surfaces. Leaving a third, uncalled function that computes a payout
# order is how a defect gets re-wired by someone reaching for the obvious name.
#
# Points For is still correct for the Skunk Pot. It is no longer correct for
# anything the Championship Pot consults.

def distribute_championship(db, *, league_id: int,
                            standings_order: list[int] | None = None,
                            split: list[int] | None = None,
                            now: datetime | None = None,
                            podium_source=None) -> ChampionshipResult:
    """Pay the Championship pot out by the accepted 60/30/10 rule.

    THE ARITHMETIC IS NOT REIMPLEMENTED. WP-10's
    `economy/championship_distribution.py` is the ONE canonical split for all
    three championship pillars and is called unchanged, including its remainder
    rule: every ordinary place floors, and the ENTIRE indivisible remainder goes
    to first place. It also carries the Final POR §17 dead-heat rule, which the
    arithmetic this path used before carried no equivalent of.

    ── WP1D — WHO RECEIVES IT ──────────────────────────────────────────────

        1st  the actual league champion
        2nd  the championship-game runner-up
        3rd  the winner of the official third-place game

    derived by `economy/championship_podium.py` from the authoritative
    postseason state and resolved through the certified league-scoped identity
    seam. `podium_source` is INJECTED because `economy/` imports nothing from
    `providers/`: the season-close route passes a zero-argument callable that
    returns `(championship_state, team_identity_resolver)`.

    IT IS A CALLABLE AND NOT TWO VALUES, FOR AN ORDERING REASON. Building the
    resolver eagerly makes an unbound roster refuse the close BEFORE the
    orchestrator's nine preconditions have run, so a league with a pending Versus
    wager and unbound teams would be told about its teams instead of its wager.
    Calling it here — after the pot check, at the one moment the podium is
    actually needed — keeps every earlier refusal reachable and costs an
    already-closed replay nothing, because that path returns before this.

    THERE IS NO FALLBACK. If the podium cannot be established — unknown track,
    incomplete championship, undecided third-place game — this raises and the
    whole close rolls back. It does NOT fall back to regular-season Points For;
    that was the defect.

    `standings_order` REMAINS FOR EXISTING TESTS AND IS NOT REACHABLE FROM
    PRODUCTION. The season-close route never passes it and accepts no such
    input from a client, so no commissioner can name a podium (WP1D-R2). It is
    honoured only when a caller supplies it explicitly, which the certified
    Sprint-5 suites do to pin an exact payout against fixed teams; production
    passes the podium instead.
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

    if standings_order is not None:
        # EXPLICIT CALLER-SUPPLIED ORDER — tests only; see the docstring.
        order = list(standings_order)
    else:
        # THE PRODUCTION PATH. Refuses rather than ordering by anything else.
        state, resolver = podium_source() if podium_source else (None, None)
        podium = resolve_podium(state, resolver)
        order = list(podium.team_ids)

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

    # ── WP-10 · THE ONE CANONICAL SPLIT ──────────────────────────────────────
    #
    # Final POR §17 fixes 60/30/10 AND its dead-heat rule as product rules, and
    # requires one implementation across all three championship pillars. This
    # path used `economy/championship.py::championship_distribution`, which had
    # no tie rule at all: it paid an ordered list 60/30/10 in whatever order the
    # caller built, so a genuine dead heat was resolved by list construction
    # rather than by the rule.
    #
    # `podium_standings` gives each podium finisher a DISTINCT descending rank
    # value, so a bracket — which cannot tie, by `derive_podium_keys`' own
    # three-distinct-ids contract — reports no tie and is paid exactly as
    # before. The dead-heat machinery is present and simply never fires here,
    # which is the correct relationship between a knockout result and a rule
    # that exists for scored ones.
    #
    # The `(place, team_id, pct, cents)` tuple shape is preserved for
    # `ChampionshipResult.placements` and every certified caller of it.
    ranked = calculate_championship_distribution(
        pot, podium_standings(order), split=tuple(split))
    by_place = {p.place: p for p in ranked}
    placements = tuple(
        (p.place, p.team_id, split[p.place - 1] if p.place <= len(split) else 0,
         p.amount_cents)
        for p in (by_place[k] for k in sorted(by_place)))
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
    """Credit each GM's `expired_min:` back to their own Wallet. LEGACY ERA ONLY.

    RETIRED UNDER `RULESET_FINAL_POR` (WP-4) — see the module docstring. A Final
    POR season returns immediately with `retired=True`, having posted nothing
    and recorded no event.

    PER-GM EVENT KEYS, not one league key. A GM added mid-close, or a partially
    completed run, must be able to converge without re-crediting the GMs already
    reconciled — and a per-GM key is what makes each one independently
    exactly-once.

    Same GM before and after, so Current Settle moves by exactly zero. No
    issuance, no championship sweep, no obligation reduction and no
    commissioner-selectable destination.
    """
    from db.schema import League
    from ruleset import is_final_por

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    season = league.season
    db.flush()

    if is_final_por(db, league_id=league_id, season=season):
        # RETIRED FOR THIS ERA (WP-4). Nothing was ever written to
        # `expired_min:` this season, so there is nothing to return; the whole
        # unspent Weekly Minimum already left the GM at week close. Returning an
        # empty result rather than raising keeps the close orchestrator's step
        # sequence intact and lets it report the retirement, and writing no
        # event keeps the season's economy_event log free of a claim that a
        # return happened.
        #
        # A STRANDED BALANCE IS SURFACED, NOT SILENTLY SWEPT. The one way a
        # Final POR season can hold `expired_min:` cents is a season whose
        # weeks closed while unstamped and which was stamped afterwards. Those
        # cents are the GM's under the era that posted them, and this retired
        # path is not the authority to move them, so they are reported and left
        # in place for the close's own conservation assertion to catch.
        stranded = tuple(
            (team.id, bal) for team, bal in
            ((t, _balance_of_in_session(db, expired_min_account(t.id)))
             for t in _teams(db, league_id))
            if bal != 0)
        return ExpiredMinResult(league_id=league_id, season=season,
                                returned=(), total_cents=0,
                                retired=True, stranded=stranded)

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
