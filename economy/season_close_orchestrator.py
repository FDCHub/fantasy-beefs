"""
Canonical season-close orchestrator (S5-P3 §9-§11).

ONE deterministic order, wrapped around the EXISTING irreversible
`economy.season_close.close_season()`, which is called LAST and never earlier:

     1  every governed Versus wager is terminal
     2  every governed Pool occurrence is settled
     3  every governed escrow account is resolved to zero
     4  final applicable Weekly Minimum release is complete
     5  final Week Close expiry is complete
     6  every required Skunk week is assessed or recorded NO_LOSER
     7  no required week is still RESULTS_NOT_READY
     8  terminal Pool rollover handling is complete OR the governed season
        boundary has been reached, in which case step 9c performs it (WP6F)
     9  pool:{league_id} holds nothing beyond those live carries
    9b  no unresolved ProviderConflict (S6 §11, additive)
    9c  terminal Pool rollover sweep -> championship:{league_id} (WP6F)
    10  sweep every reserve:{team} -> championship:{league_id}
    11  distribute Skunk
    12  distribute Championship
    13  reconcile every expired_min:{team} -> Wallet  (LEGACY ERA ONLY;
        RETIRED for RULESET_FINAL_POR seasons, which forfeit the unspent
        Weekly Minimum to the FantasyStakes Championship Pot at week close)
    14  derive final Current Settle per GM from posted state
    15  account-level conservation assertions
    16  global trial balance, then close_season()

A COMPLETION MARKER MUST NEVER SUPPRESS UNFINISHED ECONOMICS. `close_season()`
stamps an irreversible timestamp that no path returns to NULL, so it is the last
thing that happens and only after every preceding check passed. The orchestrator
refuses LOUDLY and names the FIRST unmet prerequisite rather than skipping it —
a close that silently stepped over unsettled money would make that money
permanently unreachable.

WHY THE PRECONDITIONS ARE CHECKED BEFORE ANY POSTING. Steps 1-9b are pure reads.
If any fails, nothing has been written and the league is exactly as it was, so a
refused close is always safely retryable once the underlying work completes.
Step 9c is the first thing that posts, and it is placed after every read for
exactly that reason.

WP6F — WHY A SWEEP LIVES INSIDE THE CLOSE AT ALL. The owner ruling makes
terminal rollover expiry a season-boundary settlement rule: at
`season_final_week` a carry with no later eligible occurrence transfers to the
Championship Pot, and no PoolInstance is required to host that transfer. The
close is the only place that knows the boundary has been reached, so it is the
narrowest correct home for the disposal. The RULE itself is not restated here —
`betting.pool_settlement.expire_terminal_rollovers` owns it, reusing the same
event type, ledger door and posting shape the occurrence-hosted final-week
sweep already uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from economy.current_settle import current_settle
from economy.economy_events import (
    DuplicateEconomyEvent,
    EVENT_SKUNK_ASSESSMENT,
    championship_account,
    expired_min_account,
    league_week_key,
    reserve_account,
    skunk_account,
)
from economy.season_reconciliation import (
    SeasonReconciliationError,
    consolidate_legacy_championship,
    distribute_championship,
    reconcile_expired_minimum,
    sweep_championship_reserves,
)
from economy.skunk import SkunkError, distribute_season_skunk
from ledger.ledger import _balance_of_in_session, trial_balance


class SeasonClosePreconditionError(ValueError):
    """A required prerequisite is unmet. NOTHING has been posted.

    `step` names the first failing check, so an operator is told what to finish
    rather than being handed a generic refusal."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"[{step}] {message}")
        self.step = step


@dataclass
class SeasonCloseReport:
    league_id: int
    season: int
    closed_now: bool = False
    replayed: bool = False
    #: WP6F — cents this call's terminal rollover sweep MOVED (0 on a replay).
    terminal_rollover_swept_cents: int = 0
    #: WP6F — cents no longer carried, replays included. Distinct from the
    #: above so a retry cannot be mistaken for a second sweep.
    terminal_rollover_disposed_cents: int = 0
    terminal_rollover_sweeps: tuple = ()
    reserve_swept_cents: int = 0
    legacy_consolidated_cents: int = 0
    skunk_distributed_cents: int = 0
    championship_pot_cents: int = 0
    championship_placements: tuple = ()
    expired_min_returned_cents: int = 0
    #: WP-4. True when step 13 was retired by the season's era rather than
    #: having simply found nothing to return. `expired_min_returned_cents` is 0
    #: in both cases and cannot tell them apart.
    expired_min_step_retired: bool = False
    current_settle: dict = field(default_factory=dict)
    zero_assertions: dict = field(default_factory=dict)


# ── Preconditions (steps 1-9) — pure reads ────────────────────────────────────

def _team_ids(db, league_id: int) -> list[int]:
    from db.schema import Team

    return [t.id for t in db.query(Team).filter(Team.league_id == league_id)
            .order_by(Team.id).all()]


def verify_preconditions(db, *, league_id: int, final_week: int) -> None:
    """Steps 1-9. Raises on the FIRST unmet prerequisite; writes nothing."""
    from db.schema import (
        Bet, EconomyEvent, League, Matchup, PoolInstance, ProviderConflict,
        Wallet,
    )
    from betting.pool_season_boundary import playoff_start_week, season_final_week

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise SeasonClosePreconditionError("league", f"league {league_id} not found")
    season = league.season
    team_ids = _team_ids(db, league_id)
    db.flush()

    # 1 — Versus terminal.
    wallet_ids = [w.id for w in db.query(Wallet)
                  .filter(Wallet.team_id.in_(team_ids)).all()]
    if wallet_ids:
        pending = (db.query(Bet)
                   .filter(Bet.wallet_id.in_(wallet_ids),
                           Bet.status == "pending").count())
        if pending:
            raise SeasonClosePreconditionError(
                "versus_terminal",
                f"{pending} Versus wager(s) are still pending for league "
                f"{league_id}. Closing now would strand their escrow.")

    # 2 — Pool occurrences settled.
    unsettled = (db.query(PoolInstance)
                 .filter(PoolInstance.league_id == league_id,
                         PoolInstance.settled.is_(False)).count())
    if unsettled:
        raise SeasonClosePreconditionError(
            "pool_settled",
            f"{unsettled} Pool occurrence(s) are unsettled for league "
            f"{league_id}.")

    # 3 — escrow resolved. Any nonzero escrow account is refused: the close
    # cannot tell whose it is without the S5-P2 attribution, and an unresolved
    # wager is precisely what step 1 was supposed to have eliminated.
    from sqlalchemy import text
    open_escrow = db.execute(text(
        "SELECT account, SUM(amount_cents) FROM ledger_entries "
        "WHERE account LIKE 'escrow:%' GROUP BY account "
        "HAVING SUM(amount_cents) <> 0")).fetchall()
    if open_escrow:
        raise SeasonClosePreconditionError(
            "escrow_resolved",
            f"unresolved escrow: {[(a, int(v)) for a, v in open_escrow]}")

    # 4/5 — Weekly Minimum release and expiry complete for every governed week.
    cutoff = min(final_week, playoff_start_week(league) - 1)
    played_weeks = sorted({
        m.week for m in db.query(Matchup)
        .filter(Matchup.league_id == league_id, Matchup.week <= cutoff).all()})
    for week in played_weeks:
        for team_id in team_ids:
            live = _balance_of_in_session(db, f"min:{team_id}:{week}")
            if live != 0:
                raise SeasonClosePreconditionError(
                    "weekly_minimum_expiry",
                    f"min:{team_id}:{week} still holds {live} cents; Week Close "
                    f"expiry is incomplete for week {week}.")

    # 6/7 — every required Skunk week assessed, or explicitly not ready.
    for week in played_weeks:
        finalized = all(
            m.finalized_at is not None for m in db.query(Matchup)
            .filter(Matchup.league_id == league_id, Matchup.week == week).all())
        if not finalized:
            raise SeasonClosePreconditionError(
                "results_not_ready",
                f"week {week} has matchups with finalized_at IS NULL; its "
                f"Skunk assessment cannot be completed and the season cannot "
                f"close.")
        assessed = (db.query(EconomyEvent)
                    .filter(EconomyEvent.event_key
                            == league_week_key(EVENT_SKUNK_ASSESSMENT,
                                               league_id, season, week))
                    .count())
        if not assessed:
            raise SeasonClosePreconditionError(
                "skunk_assessed",
                f"week {week} has no Skunk assessment event. Every required "
                f"week must be assessed or have recorded its NO_LOSER zero "
                f"outcome.")

    # 8 — terminal Pool rollover handling.
    #
    # WP6F OWNER RULING. Terminal rollover expiry is a SEASON-BOUNDARY
    # SETTLEMENT RULE (BAB-805, BAB-901, AP-166): at `season_final_week` a carry
    # with no later eligible occurrence transfers to the Championship Pot. So at
    # the boundary a live carry is WORK THIS CLOSE PERFORMS (step 9c below), not
    # a reason to refuse — and refusing would make it permanently undischargeable
    # for any league whose final week falls inside the postseason, which under
    # POR §9's own default boundaries is every league.
    #
    # BEFORE THE BOUNDARY IT STILL REFUSES, AND THAT IS THE POINT OF THE GATE.
    # The ruling disposes of a rollover that has NO LATER ELIGIBLE OCCURRENCE;
    # below the final week a later occurrence is precisely what still exists, so
    # a close taken early must not be able to vacuum a live carry into
    # Championship. The refusal is therefore narrowed by the ruling, not removed.
    carried_rows = (db.query(PoolInstance)
                    .filter(PoolInstance.league_id == league_id,
                            PoolInstance.rollover_cents > 0).all())
    carried_cents = sum(int(r.rollover_cents or 0) for r in carried_rows)
    boundary = season_final_week(league)
    boundary_reached = int(final_week) >= int(boundary)

    if carried_rows and not boundary_reached:
        raise SeasonClosePreconditionError(
            "pool_rollover",
            f"{len(carried_rows)} Pool occurrence(s) still carry a live "
            f"rollover, and this close is being taken at week {final_week}, "
            f"before the governed season boundary (season_final_week "
            f"{boundary}). A carry may only be disposed once no later eligible "
            f"occurrence exists.")

    # 9 — the Pool account is drained.
    #
    # AT THE BOUNDARY THE EXPECTED RESIDUAL IS EXACTLY THE LIVE CARRIES, because
    # a carry never left `pool:{league_id}` — a rollover is a column transfer,
    # not a posting. Step 9c drains it. Anything ABOVE that residual is money no
    # instance accounts for and still refuses, which is what keeps this check a
    # real conservation gate rather than one the ruling quietly disabled.
    expected_pool = carried_cents if boundary_reached else 0
    pool_balance = _balance_of_in_session(db, f"pool:{league_id}")
    if pool_balance != expected_pool:
        detail = (f"pool:{league_id} holds {pool_balance} cents."
                  if not expected_pool else
                  f"pool:{league_id} holds {pool_balance} cents but live "
                  f"rollover carries total only {expected_pool}; "
                  f"{pool_balance - expected_pool} cents are unaccounted for.")
        raise SeasonClosePreconditionError("pool_zero", detail)

    # 9b — S6 §11: no UNRESOLVED provider conflict.
    #
    # ADDITIVE AND LAST AMONG THE PRECONDITIONS. The eight accepted Sprint 5
    # checks above are untouched and still run in their accepted order; this one
    # is appended, so a league that would have closed under Sprint 5 and carries
    # no conflict closes identically. close_season() remains step 16.
    #
    # WHY THE CLOSE IS THE RIGHT PLACE TO BLOCK. S6-R3 forbids Sprint 6 from
    # building automatic economic reversal, so a post-final contradiction cannot
    # be corrected by code — it can only be recorded and escalated. Season close
    # is irreversible and stamps a timestamp no path returns to NULL, which
    # makes it the LAST moment a human can still act on a contradiction about a
    # result that money has already been paid on. Closing over one would make
    # the disagreement permanently unactionable.
    #
    # ACKNOWLEDGED CONFLICTS DO NOT BLOCK. An operator who acknowledged a
    # conflict has recorded that they looked at it and accepted the stored
    # value; that is the only resolution S6-R3 permits Sprint 6 to offer, and
    # honouring it is what keeps the gate from being permanently unclearable.
    # Acknowledgement moves no money — providers/yahoo/persist.py has no path
    # that could.
    open_conflicts = (db.query(ProviderConflict)
                      .filter(ProviderConflict.league_id == league_id,
                              ProviderConflict.resolved_at.is_(None))
                      .order_by(ProviderConflict.id)
                      .all())
    if open_conflicts:
        summary = [
            f"{c.conflict_type}:{c.contradicted_field} on "
            f"{c.external_identity} (stored {c.existing_value!r}, provider "
            f"claimed {c.provider_value!r}, seen {c.occurrence_count}x)"
            for c in open_conflicts[:5]
        ]
        more = ("" if len(open_conflicts) <= 5
                else f" ... and {len(open_conflicts) - 5} more")
        raise SeasonClosePreconditionError(
            "provider_conflict",
            f"{len(open_conflicts)} unresolved provider conflict(s) for league "
            f"{league_id}: {'; '.join(summary)}{more}. Sprint 6 builds no "
            f"automatic economic reversal (S6-R3) — each must be reviewed and "
            f"acknowledged by an operator before the season may close.")


# ── The orchestrator ──────────────────────────────────────────────────────────

def close_season_economy(db, *, league_id: int, final_week: int,
                         operator: str = "s5-close",
                         now: datetime | None = None,
                         podium_source=None) -> SeasonCloseReport:
    """Run the full close sequence. Does NOT commit — the caller owns the
    transaction, which is what keeps every posting and every event row atomic
    with the checks that authorized them.

    `close_season()` is called last and commits internally; by then every
    economic step has already been written into this same transaction.

    ── WP1D — THIS FUNCTION NO LONGER ACCEPTS A RECIPIENT ORDER ─────────────

    `standings_order` USED TO BE A PARAMETER HERE AND HAS BEEN REMOVED, not
    defaulted and not deprecated. Any caller able to pass it could name the three
    teams who receive 60/30/10 of the Championship Pot, and a parameter that can
    do that on the production close path is a bypass of the podium regardless of
    whether today's routes happen to pass it. `distribute_championship` keeps it
    for the certified arithmetic suites, which call that function directly and
    pin an exact payout against fixed teams; the close does not offer the door.

    `podium_source` REPLACES IT AND CANNOT DO THE SAME JOB. It is a zero-argument
    callable returning `(championship_state, team_identity_resolver)`, and the
    order is DERIVED from that state by `economy/championship_podium.py` rather
    than stated by the caller. The worst a caller can do with it is supply a
    state the podium refuses, which refuses the close — it cannot select a
    recipient.
    """
    from db.schema import League, PoolInstance
    from economy.season_close import close_season, is_season_closed

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise SeasonClosePreconditionError("league",
                                           f"league {league_id} not found")
    report = SeasonCloseReport(league_id=league_id, season=league.season)

    if is_season_closed(league):
        # A completed close replays harmlessly: nothing is re-posted, and the
        # per-GM position is re-derived from posted state rather than cached.
        report.replayed = True
        report.current_settle = {
            team_id: current_settle(db, team_id=team_id, league_id=league_id,
                                    season=league.season).as_dict()
            for team_id in _team_ids(db, league_id)}
        return report

    # Steps 1-9 — pure reads, before any posting.
    verify_preconditions(db, league_id=league_id, final_week=final_week)

    # Step 9c — TERMINAL POOL ROLLOVER SWEEP (WP6F owner ruling).
    #
    # FIRST POSTING OF THE CLOSE, AND DELIBERATELY BEFORE THE RESERVE SWEEP AND
    # CHAMPIONSHIP DISTRIBUTION. BAB-901 requires Season Close to resolve Pool
    # rollovers and season-end sweeps BEFORE Championship distribution, and the
    # order is economically load-bearing rather than cosmetic: step 12 reads the
    # whole `championship:{league_id}` balance as its pot, so a carry that
    # arrived after it would sit in the account unpaid and step 15's
    # conservation assertion would refuse the close it was supposed to complete.
    #
    # STILL AFTER EVERY PRECONDITION. Steps 1-9 remain pure reads, so a refused
    # close has written nothing and stays safely retryable — the property the
    # module docstring states, preserved rather than traded away for the sweep.
    from betting.pool_settlement import expire_terminal_rollovers

    terminal = expire_terminal_rollovers(db, league_id=league_id,
                                         final_week=final_week, now=now)
    report.terminal_rollover_swept_cents = terminal.total_cents
    report.terminal_rollover_disposed_cents = terminal.disposed_cents
    report.terminal_rollover_sweeps = tuple(
        {"pool_instance_id": s.pool_instance_id,
         "definition_key": s.definition_key, "week": s.week, "slot": s.slot,
         "classification": s.classification, "amount_cents": s.amount_cents,
         "replayed": s.replayed}
        for s in terminal.swept)

    # POST-SWEEP CONSERVATION. Steps 8 and 9 were evaluated against the residual
    # the sweep was expected to dispose of; these two assert it actually did.
    # Without them a sweep that silently disposed of nothing would fall straight
    # through into Championship distribution with the carry still live.
    still_carried = (db.query(PoolInstance)
                     .filter(PoolInstance.league_id == league_id,
                             PoolInstance.rollover_cents > 0).count())
    if still_carried:
        raise SeasonClosePreconditionError(
            "pool_rollover",
            f"{still_carried} Pool occurrence(s) still carry a live rollover "
            f"after the terminal sweep at season_final_week "
            f"{terminal.season_final_week}.")
    pool_after = _balance_of_in_session(db, f"pool:{league_id}")
    if pool_after != 0:
        raise SeasonClosePreconditionError(
            "pool_zero",
            f"pool:{league_id} holds {pool_after} cents after the terminal "
            f"rollover sweep.")

    # Step 10 — reserve sweep (and any legacy pot consolidation first, so the
    # distribution below sees one canonical pot).
    try:
        report.legacy_consolidated_cents = consolidate_legacy_championship(
            db, league_id=league_id, now=now)
    except DuplicateEconomyEvent:
        pass
    try:
        sweep = sweep_championship_reserves(db, league_id=league_id, now=now)
        report.reserve_swept_cents = sweep.total_cents
    except DuplicateEconomyEvent:
        report.reserve_swept_cents = 0

    # Step 11 — Skunk. An empty pot is not an error at close: a season with no
    # assessed Skunk legitimately has nothing to distribute.
    try:
        skunk = distribute_season_skunk(db, league_id=league_id, now=now)
        report.skunk_distributed_cents = skunk.pot_cents
    except SkunkError as exc:
        if exc.reason != "EMPTY_POT":
            raise
    except DuplicateEconomyEvent:
        pass

    # Step 12 — Championship.
    try:
        # WP1D — THE PODIUM IS THE AUTHORITY, AND A REFUSAL ABORTS THE CLOSE.
        # `distribute_championship` raises rather than falling back, and the
        # only reason swallowed below is EMPTY_POT. Steps 9c-11 have already
        # written into THIS transaction, so the caller's rollback discards the
        # terminal rollover sweep, the reserve sweep and the Skunk distribution
        # along with it — the season stays exactly as it was, retryable once the
        # postseason result becomes authoritative.
        #
        # `podium_source` IS CALLED INSIDE distribute_championship, not here, so
        # that an empty pot still closes a season whose bracket was never
        # classified and so that every step 1-11 refusal stays reachable first.
        champ = distribute_championship(db, league_id=league_id, now=now,
                                        podium_source=podium_source)
        report.championship_pot_cents = champ.pot_cents
        report.championship_placements = champ.placements
    except SeasonReconciliationError as exc:
        if exc.reason != "EMPTY_POT":
            raise
    except DuplicateEconomyEvent:
        pass

    # Step 13 — expired Weekly Minimum back to each GM's own Wallet.
    # RETIRED under RULESET_FINAL_POR (WP-4): the call returns retired=True
    # having posted nothing. The step is still SEQUENCED here so the numbered
    # order below it — final Current Settle, conservation, trial balance — is
    # identical in both eras and steps 14-16 keep the same meaning.
    expired = reconcile_expired_minimum(db, league_id=league_id, now=now)
    report.expired_min_returned_cents = expired.total_cents
    report.expired_min_step_retired = expired.retired

    # Step 14 — final Current Settle, derived.
    db.flush()
    report.current_settle = {
        team_id: current_settle(db, team_id=team_id, league_id=league_id,
                                season=league.season).as_dict()
        for team_id in _team_ids(db, league_id)}

    # Step 15 — account-level conservation.
    zeros = {}
    for team_id in _team_ids(db, league_id):
        zeros[f"reserve:{team_id}"] = _balance_of_in_session(
            db, reserve_account(team_id))
        zeros[f"expired_min:{team_id}"] = _balance_of_in_session(
            db, expired_min_account(team_id))
    zeros[f"pool:{league_id}"] = _balance_of_in_session(db, f"pool:{league_id}")
    zeros[f"skunk:{league_id}"] = _balance_of_in_session(
        db, skunk_account(league_id))
    zeros[f"championship:{league_id}"] = _balance_of_in_session(
        db, championship_account(league_id))
    report.zero_assertions = zeros
    nonzero = {k: v for k, v in zeros.items() if v != 0}
    if nonzero:
        raise SeasonClosePreconditionError(
            "conservation",
            f"accounts that must be zero at close still hold money: {nonzero}")

    # Step 16 — global trial balance, then the irreversible close LAST.
    db.flush()
    if trial_balance() != 0:
        raise SeasonClosePreconditionError(
            "trial_balance",
            f"global trial balance is {trial_balance()}, not zero.")

    result = close_season(league_id, operator, db)
    report.closed_now = result.closed_now
    return report