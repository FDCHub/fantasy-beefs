"""
workers/final_lock.py — WP6B: the production caller for Dynamic Final Lock.

WHAT THIS MODULE IS, AND WHAT IT DELIBERATELY IS NOT. It is the scheduled system
process that SIMULATION_ENGINE_MODULE_SPEC_Rev9 §5 names as the Final-Lock
trigger, and nothing more. Every economic decision — the guards, the one official
simulation, the Adjustment, the Derived refund, the escrow migration, the Bet
rows, the frozen result, the claim mutex — already lives in
`economy.dynamic_challenge` and is certified by
`test_p3_d2_dynamic_final_lock_pg.py`. This file adds no economics, re-derives no
price, and owns no invariant. It answers exactly three operational questions:

    WHICH challenges are awaiting Final Lock?
    IS one of them due yet?
    WITH WHAT live lineup data does the certified engine run?

and then calls `run_final_lock`. WP6 found that engine certified with no caller;
this is the caller, and the only thing it may correctly be.

THE ACTOR CLASS IS FIXED BY THE SPEC, and it is why this is a `workers/` module
rather than a route (Rev 9 §5.5): "the same scheduled system worker/process class
that acquires fresh claims. Not an end user, not a GM, not a commissioner, not
reachable from any HTTP route. Final Lock is machine-triggered at kickoff; a
human 'retry' button would be a second admission path into the money path and
there is no product requirement for one." No HTTP surface is added anywhere for
this capability, deliberately. WP6 refused to manufacture a pass by adding one,
and adding one here would be the same defect arriving one package later.

THE TIMING RULE IS NOT REIMPLEMENTED HERE. Rev 9 §5 fixes the trigger at "the
challenge's earliest covered kickoff (`_nfl_lock_time` / per-challenge kickoff
already computed in `beef_engine`)", and §13 records that helper becoming
load-bearing at P3-D2. `_nfl_lock_time(LOCK_SEASON, week)` is therefore imported
and called, not paraphrased: a second kickoff calculation would be a second
answer to a question that already has exactly one, and the two would drift.

THE LINEUP IS LIVE, AND THAT IS THE MODE. Locked freezes lineups at acceptance
and reads the `BeefStarter` snapshot; Dynamic "leaves lineups and odds live until
Final Lock re-prices exactly once" (Rev 9 §0). So the starters handed to the
engine come from `beef_engine._fetch_starters_for_odds` — live `Roster` joined to
live `Projection` — which is the same reader the product already prices with, and
the only one. (The `BeefStarter` snapshot is not an alternative here even in
principle: `_capture_beef_starters` runs on the retired legacy accept path, so a
challenge issued through `POST /beef/challenge` has no snapshot to read.)

WHAT THE WORKER MAY DECIDE, AND WHAT IT MUST NOT. It decides eligibility,
dueness, and whether the governed simulation has inputs at all. It does NOT
decide lateness: the certified engine has no late-lock branch, so a worker that
arrives after kickoff — a restart, a paused host, a backlog — locks exactly as
one that arrives at kickoff would. Inventing a "too late to lock" rule here would
strand escrow the engine was perfectly willing to resolve, which is the very
failure WP6 reported.

ONE SESSION PER CHALLENGE, ALWAYS. `acquire_final_lock_claim` commits Phase 1 by
itself and `_fail_claim` rolls back before committing a release, so the engine
owns transaction boundaries on the session it is handed. Sharing one session
across challenges would let one challenge's rollback discard another's work.
Discovery reads on its own session and closes it before any execution begins.

PRODUCTION INVOCATION (see RUNBOOK §5):

    python -m workers.final_lock --loop        # resident worker, 60s cadence
    python -m workers.final_lock               # one sweep, then exit
    python -m workers.final_lock --dry-run     # report dueness, claim nothing

`Procfile` declares it as the `final_lock` process type and
`railway.final_lock.toml` as its own Railway service, so a deployed
FantasyStakes runs Final Lock with no GM or commissioner doing anything.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, Sequence

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.orm import Session

from beefs import proposal_lifecycle as spec1
from betting.exceptions import ScheduleNotReadyError
# THE governed kickoff helper, imported from its single definition site. This is
# the same function object `beefs.beef_engine` imports and prices every other
# kickoff-lock decision with; Rev 9 §5 names it by that name.
from betting.pool_engine import _nfl_lock_time
from config import LOCK_SEASON
from db.schema import BeefChallenge, ChallengeFinalLock, SessionLocal
from economy import dynamic_challenge as dyn
from odds.dynamic_pricing import DynamicPricingError

#: Default sweep cadence for `--loop`, in seconds. Final Lock fires AT the
#: earliest covered kickoff, so the worker's latency budget is the gap between
#: sweeps; sixty seconds keeps that gap an order of magnitude below the
#: fifteen-minute claim TTL and far below any settlement deadline. It is a
#: cadence, never a timing rule: `_nfl_lock_time` alone decides dueness, and a
#: slower cadence delays a lock without ever authorizing an early one.
DEFAULT_INTERVAL_SECONDS = 60

# ── Outcome vocabulary ────────────────────────────────────────────────────────
#
# Named constants rather than bare strings, for the same reason the engine gives
# its refusals distinct exception TYPES: operators and tests branch on these, and
# a typo in a literal would silently read as "some other outcome".
LOCKED             = "locked"        # this sweep executed Final Lock
REPLAYED           = "replayed"      # already complete; the committed result was returned
NOT_DUE            = "not_due"       # earliest covered kickoff has not arrived
DUE                = "due"           # --dry-run only: would lock, claimed nothing
SCHEDULE_NOT_READY = "schedule_not_ready"   # no governed kickoff exists to compare against
NO_SIM_INPUTS      = "no_sim_inputs"        # the official simulation has no lineups to run on
NOT_OWNED          = "not_owned"     # another worker holds a live, non-stale claim
FAILED             = "failed"        # deterministic refusal; the engine released the claim
ERROR              = "error"         # unexpected fault; Phase 2 rolled back, claim recovers on TTL


def default_worker_id() -> str:
    """A worker identity that is stable for the life of the PROCESS and distinct
    between processes.

    BOTH HALVES ARE LOAD-BEARING. `_final_lock_phase_2` re-reads the claim and
    refuses when `claim.claimed_by != worker_id`, so an identity that changed
    between the acquisition and the execution would make a worker unable to
    execute its own claim. And two workers must never collide on one identity, or
    the second would satisfy that same equality check against a claim it does not
    hold — which is exactly the mutex the `UNIQUE(challenge_id)` row exists to
    provide. Host plus PID plus a per-process nonce covers restarts that reuse a
    PID and containers that share a hostname.
    """
    return f"final-lock@{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


#: Computed once, at import, for the reason `default_worker_id` documents.
WORKER_ID = default_worker_id()


# ── Results ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChallengeOutcome:
    """What the worker did about ONE challenge, and why."""
    challenge_id:  int
    league_id:     Optional[int]
    week:          Optional[int]
    status:        str
    detail:        str = ""
    due_at:        Optional[datetime] = None
    final_lock_id: Optional[int] = None
    anchor_bet_id: Optional[int] = None
    derived_bet_id: Optional[int] = None


@dataclass(frozen=True)
class SweepResult:
    worker_id:  str
    started_at: datetime
    outcomes:   tuple[ChallengeOutcome, ...] = field(default_factory=tuple)

    def count(self, status: str) -> int:
        return sum(1 for o in self.outcomes if o.status == status)

    @property
    def examined(self) -> int:
        return len(self.outcomes)

    @property
    def locked(self) -> int:
        return self.count(LOCKED)

    @property
    def failed(self) -> int:
        return self.count(FAILED) + self.count(ERROR)

    def summary(self) -> str:
        seen: dict[str, int] = {}
        for o in self.outcomes:
            seen[o.status] = seen.get(o.status, 0) + 1
        parts = ", ".join(f"{k}={v}" for k, v in sorted(seen.items()))
        return f"examined={self.examined}" + (f" ({parts})" if parts else "")


# ── Discovery ─────────────────────────────────────────────────────────────────

def eligible_challenges(db: Session, *,
                        league_id: Optional[int] = None) -> list[BeefChallenge]:
    """Every Dynamic challenge that has Handshaken and has not yet Final-Locked.

    THE FOUR PREDICATES ARE THE ENGINE'S OWN ENTRY CONDITIONS, asked in advance
    so the worker does not claim a challenge Phase 2 would only refuse:

      mode is Dynamic          — Locked never reaches this module at all
                                 (`_require_dynamic`).
      response_status accepted — "only an accepted Dynamic challenge may
                                 Final-Lock" (§2 entry guard 4).
      dynamic_handshake_at set — a challenge with no Handshake record has no
                                 frozen model, no ceilings and no funded escrow.
      no ChallengeFinalLock    — the frozen result is `UNIQUE(challenge_id)`, so
                                 its absence is exactly "not yet locked".

    COMPLETION IS READ FROM THE RESULT, NOT FROM THE CLAIM, and the two agree by
    construction: the claim's biconditional CHECKs make `completed` imply
    `final_lock_id IS NOT NULL`. Filtering on the result rather than the claim
    also keeps a `claimed` or `failed` row eligible, which is what lets a crashed
    attempt be recovered by the next sweep instead of being filtered out of
    existence. The claim table decides WHO executes; this decides WHAT is left.

    Ordered by week then id so two workers walk the same list in the same order,
    and so an operator reading a log can predict it.
    """
    locked_ids = select(ChallengeFinalLock.challenge_id)
    q = (db.query(BeefChallenge)
         .filter(BeefChallenge.challenge_mode == spec1.MODE_DYNAMIC,
                 BeefChallenge.response_status == spec1.ACCEPTED,
                 BeefChallenge.dynamic_handshake_at.isnot(None),
                 ~BeefChallenge.id.in_(locked_ids)))
    if league_id is not None:
        q = q.filter(BeefChallenge.league_id == league_id)
    return q.order_by(BeefChallenge.week, BeefChallenge.id).all()


def final_lock_due_at(challenge: BeefChallenge) -> datetime:
    """The governed Final-Lock moment: the challenge's earliest covered kickoff.

    Rev 9 §5: the trigger is "a single scheduled event, fired at the challenge's
    earliest covered kickoff (`_nfl_lock_time` / per-challenge kickoff already
    computed in `beef_engine`)". A straight/spread/over-under Dynamic wager
    covers both GMs' entire lineups for the week, so every game that week is a
    covered game and the earliest covered kickoff IS the week's earliest
    kickoff — which is precisely what `_nfl_lock_time` returns.

    `LOCK_SEASON`, NOT `CURRENT_SEASON`, and not `League.season`. `config` states
    the distinction outright: LOCK_SEASON is "NFL schedule season for
    kickoff-lock checks; independent of CURRENT_SEASON (projection data year)".
    Every kickoff-lock decision in the challenge domain — issue, respond, counter,
    expiry — passes LOCK_SEASON to this helper, and a Final Lock computed against
    a different season would fire at a different instant than the lock rule the
    same challenge was issued under.

    Raises `ScheduleNotReadyError` when the week has no real announced kickoff.
    That is a refusal to answer, not an answer of "now": see `sweep_challenge`.
    """
    return _nfl_lock_time(LOCK_SEASON, challenge.week)


def build_final_lock_inputs(db: Session,
                            challenge: BeefChallenge) -> dyn.FinalLockInputs:
    """The LIVE lineup and projection data the one official simulation runs on.

    STARTERS ARE BOUND BY CHALLENGE ROLE, which is the only vocabulary
    `FinalLockInputs` has since B-3/B-4 removed team ids, matchup id and week
    from it. The engine maps role to side from the persisted `Matchup` itself, so
    there is no home/away decision for this function to get wrong or to game — it
    supplies two lists and nothing else.

    PROVENANCE IS RECORDED AS WHAT WAS ACTUALLY READ. `_fetch_starters_for_odds`
    reads `Projection` rows keyed `(player_id, week, season=CURRENT_SEASON,
    source=SOURCE)`, so those are the coordinates written to the frozen record.
    `projections` carries no version column, so the dataset's identity is the key
    that selected it; claiming a finer version than the table can express would
    record an assertion rather than an observation.
    """
    from beefs.beef_engine import (
        SEASON as PROJECTION_SEASON,
        SOURCE as PROJECTION_SOURCE,
        _fetch_starters_for_odds,
    )

    inputs = _fetch_starters_for_odds(
        challenge.wager_type,
        challenge.challenger_team_id,
        challenge.challenged_team_id,
        challenge.player_id,
        challenge.week,
        db,
    )
    return dyn.FinalLockInputs(
        challenger_starters = tuple(inputs.ch_starters or ()),
        challenged_starters = tuple(inputs.cd_starters or ()),
        projection_source_id       = PROJECTION_SOURCE,
        projection_dataset_version = f"{PROJECTION_SEASON}-w{challenge.week}",
    )


# ── Execution ─────────────────────────────────────────────────────────────────

def sweep_challenge(
    challenge_id: int,
    *,
    worker_id: str,
    now: Optional[datetime] = None,
    dry_run: bool = False,
    session_factory: Callable[[], Session] = SessionLocal,
) -> ChallengeOutcome:
    """Decide about, and if due execute, Final Lock for ONE challenge.

    ITS OWN SESSION, ALWAYS — see the module docstring. The engine commits and
    rolls back the session it is handed, so each challenge gets a fresh one and a
    refusal on one challenge cannot discard another's committed lock. That is
    also what makes "continue safely to other eligible challenges" true rather
    than hoped for.

    NOTHING IS CLAIMED BEFORE THE DUE CHECK. `run_final_lock` acquires the claim
    itself as its first act, so calling it early would take the execution right
    for a challenge that must not execute yet — and hold it for the full TTL
    against the worker that arrives when it genuinely is due.
    """
    moment = now or datetime.now(timezone.utc)
    with session_factory() as db:
        challenge = (db.query(BeefChallenge)
                     .filter(BeefChallenge.id == challenge_id).first())
        if challenge is None:
            return ChallengeOutcome(challenge_id, None, None, ERROR,
                                    "challenge not found")
        league_id, week = challenge.league_id, challenge.week

        # ── is it due? ───────────────────────────────────────────────────────
        try:
            due_at = final_lock_due_at(challenge)
        except ScheduleNotReadyError as exc:
            # NO GOVERNED KICKOFF, NO LOCK. The week is unloaded or carries only
            # placeholder timestamps, so there is no earliest covered kickoff to
            # be at or past. Treating that absence as "due now" would fire the
            # trigger at an ungoverned instant; treating it as "never" would
            # strand the challenge. It is reported and retried next sweep, which
            # is what happens the moment the schedule lands.
            return ChallengeOutcome(challenge_id, league_id, week,
                                    SCHEDULE_NOT_READY, str(exc))
        if moment < due_at:
            return ChallengeOutcome(challenge_id, league_id, week, NOT_DUE,
                                    f"due at {due_at.isoformat()}", due_at)

        # ── does the official simulation have inputs? ────────────────────────
        #
        # Asked BEFORE the claim, because a challenge with no lineups cannot be
        # priced by any attempt, and claiming it would only park the execution
        # right on a challenge no worker can finish. `simulate_scores` refuses an
        # empty starter list outright, so this is the engine's own requirement
        # asked one step earlier and reported instead of raised.
        final_inputs = build_final_lock_inputs(db, challenge)
        if not final_inputs.challenger_starters or not final_inputs.challenged_starters:
            return ChallengeOutcome(
                challenge_id, league_id, week, NO_SIM_INPUTS,
                f"wager_type={challenge.wager_type!r} yields "
                f"{len(final_inputs.challenger_starters)}/"
                f"{len(final_inputs.challenged_starters)} starters; the official "
                f"simulation has nothing to run on", due_at)

        if dry_run:
            # Everything above this line is a read. The dueness answer and the
            # simulation-input answer are both already known, and reporting them
            # without acquiring the claim is the whole point of the mode: an
            # operator can ask "what would you do" without taking an execution
            # right away from the worker that will genuinely do it.
            return ChallengeOutcome(challenge_id, league_id, week, DUE,
                                    "dry run — nothing claimed, nothing posted",
                                    due_at)

        # ── the certified engine, unaltered ──────────────────────────────────
        try:
            result = dyn.run_final_lock(
                event_id     = uuid.uuid4(),
                challenge_id = challenge_id,
                worker_id    = worker_id,
                final_inputs = final_inputs,
                db           = db,
                now          = moment,
            )
        except dyn.FinalLockNotOwnedError as exc:
            # A live, non-stale claim is held elsewhere. Rev 9 §5.8: "do not
            # execute, do not report success." Back off; the owner is working,
            # and if it dies its claim expires and the next sweep reclaims it.
            return ChallengeOutcome(challenge_id, league_id, week, NOT_OWNED,
                                    str(exc), due_at)
        except (dyn.DynamicChallengeError, DynamicPricingError) as exc:
            # DETERMINISTIC REFUSAL. `run_final_lock` has already rolled Phase 2
            # back and committed the claim to `failed`, releasing ownership at
            # once (§5.3) — so there is nothing to undo here and no reason to
            # make every other worker wait out the staleness window. Recorded and
            # stepped over; the sweep continues.
            return ChallengeOutcome(challenge_id, league_id, week, FAILED,
                                    f"{type(exc).__name__}: {exc}", due_at)
        except Exception as exc:                      # noqa: BLE001
            # UNEXPECTED FAULT. The engine's own `except Exception` already rolled
            # Phase 2 back, so no partial economic write survives and the claim
            # stays `claimed` — recoverable on TTL by design (§5.7, "crash during
            # Phase 2"). Escrow is exactly as the Handshake left it, which is what
            # keeps guard 3's strict equality true for the recovering worker.
            db.rollback()
            return ChallengeOutcome(challenge_id, league_id, week, ERROR,
                                    f"{type(exc).__name__}: {exc}", due_at)

        return ChallengeOutcome(
            challenge_id, league_id, week,
            REPLAYED if result.replayed else LOCKED,
            result.detail, due_at,
            final_lock_id  = result.final_lock_id,
            anchor_bet_id  = result.anchor_bet_id,
            derived_bet_id = result.derived_bet_id,
        )


def run_once(
    *,
    worker_id: Optional[str] = None,
    now: Optional[datetime] = None,
    league_id: Optional[int] = None,
    dry_run: bool = False,
    session_factory: Callable[[], Session] = SessionLocal,
) -> SweepResult:
    """One sweep: discover every challenge awaiting Final Lock, act on each.

    DISCOVERY CLOSES BEFORE EXECUTION OPENS. The ids are collected on a read-only
    session which is then released, so no execution runs while a discovery
    transaction sits open holding a snapshot — and so a challenge that another
    worker locks mid-sweep is simply found complete when this worker reaches it,
    rather than double-executed.
    """
    wid = worker_id or WORKER_ID
    started = now or datetime.now(timezone.utc)

    with session_factory() as db:
        pending = [c.id for c in eligible_challenges(db, league_id=league_id)]
        db.rollback()

    outcomes = [
        sweep_challenge(cid, worker_id=wid, now=now, dry_run=dry_run,
                        session_factory=session_factory)
        for cid in pending
    ]
    return SweepResult(worker_id=wid, started_at=started,
                       outcomes=tuple(outcomes))


# ── Resident process ──────────────────────────────────────────────────────────

class _Stopper:
    """SIGTERM/SIGINT -> stop after the current sweep, never mid-challenge.

    Railway (and every other supervisor) stops a process with SIGTERM. Dying
    inside Phase 2 is survivable — the claim expires and the next worker recovers
    it — but taking a fifteen-minute TTL on every ordinary redeploy is a cost
    with no reason to pay it, so the flag is checked between sweeps.
    """

    def __init__(self) -> None:
        self.stop = False
        for sig in (signal.SIGINT, getattr(signal, "SIGTERM", signal.SIGINT)):
            try:
                signal.signal(sig, self._handle)
            except (ValueError, OSError):
                # Not the main thread, or the platform lacks the signal. The loop
                # still terminates on KeyboardInterrupt.
                pass

    def _handle(self, signum, frame) -> None:      # noqa: ANN001, ARG002
        print(f"[final-lock] signal {signum} received — stopping after this sweep",
              flush=True)
        self.stop = True


def run_forever(
    *,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    league_id: Optional[int] = None,
    worker_id: Optional[str] = None,
    max_sweeps: Optional[int] = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> int:
    """Sweep on a fixed cadence until told to stop.

    A RESIDENT PROCESS RATHER THAN A PLATFORM CRON, and the reason is the timing
    rule. Final Lock fires AT the earliest covered kickoff; a platform whose
    smallest schedulable unit is an hour would put up to an hour of drift between
    the governed instant and the execution. Owning the cadence in-process makes
    the latency bound `interval_seconds` — sixty by default — on any host that
    can keep a process alive, which is the same thing the `web` process already
    requires of the deployment. `--interval` tunes the cadence only; it can never
    authorize a lock before `_nfl_lock_time` says so.
    """
    stopper = _Stopper()
    wid = worker_id or WORKER_ID
    print(f"[final-lock] worker {wid} starting — sweeping every "
          f"{interval_seconds}s"
          f"{f' (league {league_id})' if league_id is not None else ''}",
          flush=True)
    sweeps = 0
    while not stopper.stop:
        try:
            result = run_once(worker_id=wid, league_id=league_id,
                              session_factory=session_factory)
            _report(result, verbose=False)
        except Exception as exc:                      # noqa: BLE001
            # A SWEEP FAILURE IS NOT A PROCESS FAILURE. A dropped connection or a
            # transient database fault must not take the worker down and leave
            # every subsequent kickoff unserved; the next sweep re-discovers
            # everything from durable state, so there is nothing to carry across.
            print(f"[final-lock] sweep error: {type(exc).__name__}: {exc}",
                  flush=True)
        sweeps += 1
        if max_sweeps is not None and sweeps >= max_sweeps:
            break
        if stopper.stop:
            break
        # Sliced sleep, so a stop signal is honoured promptly rather than after a
        # full interval.
        for _ in range(interval_seconds):
            if stopper.stop:
                break
            time.sleep(1)
    print(f"[final-lock] worker {wid} stopped after {sweeps} sweep(s)", flush=True)
    return 0


# ── Reporting / CLI ───────────────────────────────────────────────────────────

def _report(result: SweepResult, *, verbose: bool) -> None:
    interesting = [o for o in result.outcomes
                   if verbose or o.status not in (NOT_DUE, SCHEDULE_NOT_READY)]
    if interesting or verbose:
        print(f"[final-lock] {result.summary()}", flush=True)
    for o in interesting:
        print(f"  challenge {o.challenge_id} (league {o.league_id}, "
              f"week {o.week}): {o.status}"
              f"{f' — {o.detail}' if o.detail else ''}", flush=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workers.final_lock",
        description="FantasyStakes Dynamic Final Lock worker "
                    "(SIMULATION_ENGINE_MODULE_SPEC_Rev9 §5). System actor only.")
    parser.add_argument("--loop", action="store_true",
                        help="stay resident and sweep on a fixed cadence")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS,
                        help=f"seconds between sweeps in --loop mode "
                             f"(default {DEFAULT_INTERVAL_SECONDS})")
    parser.add_argument("--league", type=int, default=None,
                        help="restrict the sweep to one league id")
    parser.add_argument("--dry-run", action="store_true",
                        help="report dueness only; acquire no claim and post "
                             "nothing")
    parser.add_argument("--verbose", action="store_true",
                        help="report every examined challenge, not just the "
                             "ones acted on")
    args = parser.parse_args(argv)

    if args.interval < 1:
        parser.error("--interval must be at least 1 second")
    if args.loop and args.dry_run:
        parser.error("--dry-run is a one-shot report; it does not take --loop")

    if args.loop:
        return run_forever(interval_seconds=args.interval,
                           league_id=args.league)

    result = run_once(league_id=args.league, dry_run=args.dry_run)
    _report(result, verbose=True)
    # A one-shot invocation reports failure to whatever ran it. In `--loop` mode
    # a failed challenge is an event, not a reason to exit — see `run_forever`.
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())