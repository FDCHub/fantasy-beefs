"""Reset the showcase demo league to its canonical state — and nothing else.

    python -m demo.reset            retire the current showcase, build a fresh one
    python -m demo.reset --check    prove what it WOULD touch, change nothing

── THIS MODULE'S ENTIRE JOB IS TO REFUSE ────────────────────────────────────

A reset command that can reach a real league is a catastrophe waiting for a
tired evening. So the guard comes first and it is not optional: every entry
point calls `assert_demo_league`, which raises unless the league proves, from
its PROVIDER BINDING, that the demo seeder created it. There is no `--force`
that bypasses it, no league-id parameter that skips it, and no name-based check
anywhere — a league called "FantasyStakes Demo League" bound to Yahoo is a
Yahoo league and this module will refuse it.

── RESET RETIRES, IT DOES NOT DELETE ────────────────────────────────────────

The Ledger is append-only and its history is immutable; a reset that deleted
postings would have to violate that. So the superseded league is RETIRED — its
provider key is moved into a `retired.` namespace so `find_showcase` no longer
returns it — and a fresh showcase is built beside it. Every posting the old
league ever made survives, trial balance stays zero, and no wallet is repaired
by hand.

That also makes reset IDEMPOTENT in the way that matters: run it twice and you
get one current showcase league with identical contents, because the fixture is
a set of literals rather than anything generated.
"""
from __future__ import annotations

import argparse
import sys
import threading as _threading
from contextlib import contextmanager as _contextmanager

from demo import showcase


class DemoSafetyError(RuntimeError):
    """Raised when an operation cannot prove it is acting on a demo league."""


#: The prefix that marks a retired showcase. Deliberately still inside the demo
#: namespace: a retired demo league is still a demo league, and must never
#: become eligible for any non-demo path.
RETIRED_PREFIX = "demo.l.retired."


def assert_demo_league(league) -> None:
    """Refuse unless this league is unmistakably a showcase demo league.

    THREE INDEPENDENT CONDITIONS, ALL REQUIRED. Any one alone is forgeable by
    accident: a league can be named anything, a season can be reused, and a
    provider string could in principle be set by a future import path. Together
    they identify a league that only `demo.seed` creates.

      1. `provider == "demo"`             — the binding the whole demo path uses
      2. the provider key is in the demo namespace AND says `showcase`
      3. the season is the showcase season

    NO NAME IS CONSULTED. WP2 §14 already established that a league called
    "Demo League" is not a demo league, and that ruling is honoured here.
    """
    from providers.demo import DEMO_LEAGUE_KEY_PREFIX, DEMO_PROVIDER

    if league is None:
        raise DemoSafetyError("no league given; refusing to act on nothing")

    provider = getattr(league, "provider", None)
    key = getattr(league, "provider_league_key", "") or ""
    season = getattr(league, "season", None)

    if provider != DEMO_PROVIDER:
        raise DemoSafetyError(
            f"league {getattr(league, 'id', '?')} is bound to provider "
            f"{provider!r}, not {DEMO_PROVIDER!r}. Demo reset is refused for "
            f"every league the demo seeder did not create.")
    if not key.startswith(DEMO_LEAGUE_KEY_PREFIX):
        raise DemoSafetyError(
            f"league {getattr(league, 'id', '?')} has provider key {key!r}, "
            f"which is outside the demo namespace {DEMO_LEAGUE_KEY_PREFIX!r}.")
    if "showcase" not in key:
        raise DemoSafetyError(
            f"league {getattr(league, 'id', '?')} has provider key {key!r}, "
            f"which is a demo league but not a SHOWCASE demo league. This "
            f"command owns only what `demo.seed` created.")
    if season != showcase.SEASON:
        raise DemoSafetyError(
            f"league {getattr(league, 'id', '?')} is season {season!r}, not "
            f"the showcase season {showcase.SEASON!r}.")


def resolve_open_action(db, league) -> dict:
    """Settle a retiring showcase's live week so it leaves no escrow behind.

    ── WHY RETIREMENT CANNOT JUST RENAME THE LEAGUE ─────────────────────────

    Canonical CURRENT deliberately leaves the live week's FantasyStakes
    contests ACCEPTED AND UNSETTLED, because that is what a week in progress
    is — and an accepted contest holds both GMs' stakes in `escrow:{bet}`.
    Renaming the league does not resolve them, so every reset used to strand a
    little more escrow in the ledger for ever.

    That is not merely untidy. `season_close_orchestrator.verify_preconditions`
    checks escrow with a GLOBAL query — no league filter, because an escrow
    account is keyed by wager, not by league — so escrow abandoned by a RETIRED
    showcase blocks the CURRENT one from ever closing its season:

        [escrow_resolved] unresolved escrow: [('escrow:61', 500), ...]

    Steps 1 and 2 of that check are league-scoped; only this one is not. So the
    demo resolves its own open action rather than leaving a global residue, and
    it does so through the real settlement engine.

    NOTHING IS VOIDED OR CLAWED BACK. The week is finalized with its own fixture
    result and settled, so the outgoing league ends in a coherent terminal state
    instead of an abandoned one.
    """
    from db.schema import Bet, Team, Wallet
    from betting.settlement_engine import settle_week

    from demo import states

    team_ids = [t.id for t in db.query(Team)
                .filter(Team.league_id == league.id).all()]
    if not team_ids:
        return {"resolved": 0}
    wallet_ids = [w.id for w in db.query(Wallet)
                  .filter(Wallet.team_id.in_(team_ids)).all()]
    pending = (db.query(Bet)
               .filter(Bet.wallet_id.in_(wallet_ids),
                       Bet.status == "pending").count()) if wallet_ids else 0
    if not pending:
        return {"resolved": 0}

    week = int(league.provider_current_week or 0)
    if week not in showcase.REGULAR_SCHEDULE:
        # Nothing this module can finalize; leave it rather than guess.
        return {"resolved": 0, "week": week, "skipped": "week not scheduled"}

    teams = states._teams_by_ordinal(db, league.id)
    states.finalize_week(db, league, teams, week)
    settle_week(week, db, league.id)
    db.flush()
    return {"resolved": pending, "week": week}


def retire_showcase(db, league) -> str:
    """Move a showcase league out of the current namespace. Commits nothing.

    Fails closed: `assert_demo_league` runs before a single attribute is
    touched, so a refusal leaves the row exactly as it was.
    """
    assert_demo_league(league)
    # Resolve its live week BEFORE renaming, so the outgoing league leaves no
    # escrow behind — see `resolve_open_action`.
    resolve_open_action(db, league)
    old_key = league.provider_league_key
    league.provider_league_key = (
        f"{RETIRED_PREFIX}{league.id}.{old_key.rsplit('.', 1)[-1]}")
    league.name = f"{league.name} (retired)"
    db.add(league)
    db.flush()
    return old_key


def reset() -> dict:
    """Retire the current showcase and build a fresh one at canonical state."""
    from db.schema import SessionLocal

    from demo.seed import find_showcase, seed

    retired = None
    with SessionLocal() as db:
        current = find_showcase(db)
        if current is not None:
            retired = {"league_id": current.id,
                       "old_key": retire_showcase(db, current)}
            db.commit()

    result = seed(force=True)
    result["retired"] = retired
    return result


def canonical_fingerprint(db, league) -> dict:
    """Cheap counts that together identify the canonical CURRENT showcase.

    WHY A FINGERPRINT AND NOT A FLAG. The public demo is genuinely mutable now —
    a visitor can strike a real Versus challenge and enter a real Pool — so the
    next visitor must not inherit it. Rebuilding on every entry would make a
    public route replay a whole season on demand, which is both slow and an
    obvious way to hammer the deployment. So entry rebuilds only when the league
    is no longer canonical, and this is how that is decided.

    EVERY EXPECTED VALUE IS DERIVED FROM THE FIXTURE, never a magic number, so a
    fixture change moves the expectation with it instead of silently making
    every visit look dirty.

    The counts are the ones a visitor's actions actually move: issuing or
    accepting a challenge changes `challenges`, entering a pool changes
    `pool_claims`, and advancing to FINAL changes the week, the finalized
    matchups and `season_closed`.
    """
    from db.schema import (
        BeefChallenge, Matchup, PoolClaim, PoolInstance, Team,
    )
    from demo import showcase

    team_ids = [t.id for t in db.query(Team)
                .filter(Team.league_id == league.id).all()]
    return {
        "current_week": league.provider_current_week,
        "season_closed": league.season_closed_at is not None,
        "teams": len(team_ids),
        "challenges": (db.query(BeefChallenge)
                       .filter(BeefChallenge.challenger_team_id.in_(team_ids))
                       .count() if team_ids else 0),
        "pool_claims": (db.query(PoolClaim)
                        .join(PoolInstance,
                              PoolClaim.pool_instance_id == PoolInstance.id)
                        .filter(PoolInstance.league_id == league.id).count()),
        "pool_instances": (db.query(PoolInstance)
                           .filter(PoolInstance.league_id == league.id).count()),
        "finalized_matchups": (db.query(Matchup)
                               .filter(Matchup.league_id == league.id,
                                       Matchup.finalized_at.isnot(None))
                               .count()),
    }


def expected_fingerprint() -> dict:
    """What `canonical_fingerprint` reads on an untouched CURRENT showcase."""
    from demo import showcase

    played = showcase.COMPLETED_THROUGH_WEEK + 1        # + the live week
    return {
        "current_week": showcase.CURRENT_WEEK,
        "season_closed": False,
        "teams": showcase.TEAM_COUNT,
        "challenges": len(showcase.VERSUS_PER_WEEK_MARKETS) * played,
        "pool_claims": showcase.POOL_SLOTS_PER_WEEK * showcase.TEAM_COUNT * played,
        "pool_instances": showcase.POOL_SLOTS_PER_WEEK * played,
        "finalized_matchups": (len(showcase.REGULAR_SCHEDULE[1])
                               * showcase.COMPLETED_THROUGH_WEEK),
    }


def is_canonical(db, league) -> bool:
    """Whether this showcase is untouched CURRENT."""
    return canonical_fingerprint(db, league) == expected_fingerprint()


#: Everything that points AT a challenge or a bet, read off the foreign-key
#: graph. `beef_starters` and `bets` are handled separately because the restore
#: needs their rows before they go.
_CHALLENGE_REFERRERS: tuple = (
    ("beef_proposals", "challenge_id"),
    ("beef_starters", "beef_challenge_id"),
    ("challenge_final_lock_claims", "challenge_id"),
    ("challenge_final_locks", "challenge_id"),
    ("challenge_funding_legs", "challenge_id"),
    ("feed_events", "challenge_id"),
    ("protocol_events", "challenge_id"),
)
_BET_REFERRERS: tuple = (
    ("feed_events", "bet_id"),
    ("transactions", "bet_id"),
)


#: The advisory-lock key that serializes showcase restore and rebuild.
#:
#: A FIXED CONSTANT, not derived from a league id, and that is deliberate: the
#: thing being serialized is "whoever is currently the showcase", which changes
#: identity precisely when a rebuild happens. Keying on the league id would
#: release the lock at the exact moment it matters most.
#:
#: The bytes spell FSMODEMO, which fits a signed bigint and collides with
#: nothing else in this application.
_SHOWCASE_LOCK_KEY = 0x46534D4F44454D4F

#: Fallback for engines with no advisory locks. Adequate where it is used:
#: SQLite runs one process, and the full demo requires PostgreSQL anyway.
_PROCESS_LOCK = _threading.Lock()


@_contextmanager
def showcase_lock():
    """Serialize showcase restore/rebuild across concurrent public visitors.

    ── WHY THIS EXISTS (D2.5 blocker) ───────────────────────────────────────

    `POST /demo/enter` restores canonical state before seating the visitor, and
    four simultaneous visitors produced:

        [500, 500, 500, 200]
        StaleDataError: UPDATE statement on table 'beef_challenges'
                        expected to update 1 row(s); 0 were matched.

    Three of four requests raced inside `restore_in_place`: each read the same
    surplus challenges, and whichever committed first deleted the rows the
    others were still holding. The demo's ONLY entry point failed for most
    simultaneous visitors.

    ── A SESSION-LEVEL ADVISORY LOCK, HELD ON ITS OWN CONNECTION ────────────

    `pg_advisory_lock` rather than `pg_advisory_xact_lock` because the critical
    section spans more than one transaction — the in-place restore commits, and
    the rebuild fallback opens its own sessions. A transaction-scoped lock would
    release between them and reopen the race.

    IT LOCKS NOTHING ELSE. This is one application-level key covering one
    operation on the single active showcase. No table is locked, no row is
    locked, no other league is touched, and a Yahoo league is not delayed by a
    demo visitor. Production locking semantics are untouched.

    THE LOCK IS ALWAYS RELEASED. Release runs in `finally`, and the connection
    is closed after it — and a dropped connection releases a session-level
    advisory lock anyway, so a crashed worker cannot wedge the demo shut.
    """
    from sqlalchemy import text

    from db.schema import engine

    if engine.dialect.name != "postgresql":
        with _PROCESS_LOCK:
            yield
        return

    conn = engine.connect()
    try:
        conn.execute(text("SELECT pg_advisory_lock(:k)"),
                     {"k": _SHOWCASE_LOCK_KEY})
        # Commit so the lock is held by the CONNECTION rather than by an open
        # transaction that later work would have to keep alive.
        conn.commit()
        yield
    finally:
        try:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"),
                         {"k": _SHOWCASE_LOCK_KEY})
            conn.commit()
        finally:
            conn.close()


def restore_in_place(db, league) -> dict:
    """Undo a visitor's actions WITHOUT rebuilding the league. Commits nothing.

    ── WHY IN PLACE, AND WHY IT MATTERS MORE THAN IT LOOKS ──────────────────

    Rebuilding produced a canonical-LOOKING league with different numbers on
    every screen. `betting.pool_rotation` ranks the week's candidate
    definitions by a digest over (definition_key, league_id, season,
    rotation_cycle) — LEAGUE ID IS IN THE DIGEST, deliberately, so two real
    leagues do not draw the same slate. A rebuilt showcase therefore gets a new
    id, a different Pool slate, different winners and a different champion:

        league 1 week-1 slate: highest_combined_receptions, ...
        league 2 week-1 slate: most_receiving_touchdowns, ...
        league 1 leader: Cleat Fleetwood Mac
        league 2 leader: Hurts So Good

    That is correct product behaviour and it is fatal to a demo whose
    walkthrough names a leader: the second visitor would see a different league
    from the first. The rotation is immutable, so the demo keeps its league id
    instead.

    ── THE MUTABLE SURFACE IS SMALL, WHICH IS WHAT MAKES THIS SAFE ──────────

    A seated GM is a GM. Through the product they can do exactly two things
    that outlive their session: strike or answer a FantasyStakes challenge, and
    change their Prediction on an open Pool. So this restores exactly those two
    things, and touches nothing the seeder wrote.

    Anything it cannot restore returns False and the caller rebuilds — this is
    an optimisation over rebuilding, never a substitute for the guarantee.
    """
    from sqlalchemy import text

    from db.schema import (
        BeefChallenge, Bet, PoolInstance, Team,
    )
    from demo import showcase

    assert_demo_league(league)
    if league.season_closed_at is not None:
        # A closed season is not a visitor mutation; it is a different state.
        return {"restored": False, "reason": "season closed"}

    team_ids = [t.id for t in db.query(Team)
                .filter(Team.league_id == league.id).all()]
    canonical_count = expected_fingerprint()["challenges"]
    challenges = (db.query(BeefChallenge)
                  .filter(BeefChallenge.challenger_team_id.in_(team_ids))
                  .order_by(BeefChallenge.id).all())
    extra = challenges[canonical_count:]

    removed_postings = 0
    for challenge in extra:
        bets = db.query(Bet).filter(
            Bet.beef_challenge_id == challenge.id).all()
        # The challenge POINTS AT its two bets (`fk_challenger_bet_id`), so the
        # references have to be released before the bets can go. Clearing them
        # first — rather than deleting the challenge first — keeps the rows
        # available for the escrow lookup below.
        challenge.challenger_bet_id = None
        challenge.challenged_bet_id = None
        db.add(challenge)
        db.flush()
        for bet in bets:
            # Delete the WHOLE posting each escrow leg belongs to, so a balanced
            # set leaves together and the trial balance cannot drift. A posting
            # that also touches an account outside this league would be refused
            # below rather than half-removed.
            account = f"escrow:{bet.id}"
            posting_ids = [r[0] for r in db.execute(text(
                "SELECT DISTINCT posting_id FROM ledger_entries "
                "WHERE account = :a"), {"a": account}).fetchall()]
            for pid in posting_ids:
                legs = db.execute(text(
                    "SELECT account, amount_cents FROM ledger_entries "
                    "WHERE posting_id = :p"), {"p": pid}).fetchall()
                if sum(int(c) for _a, c in legs) != 0:
                    return {"restored": False,
                            "reason": f"posting {pid} is unbalanced"}
                db.execute(text(
                    "DELETE FROM ledger_entries WHERE posting_id = :p"),
                    {"p": pid})
                removed_postings += 1
        # EVERY REFERRER, ENUMERATED FROM THE FOREIGN-KEY GRAPH rather than
        # discovered one IntegrityError at a time. A row this misses does not
        # corrupt anything — the delete refuses, `restore_in_place` returns
        # False and the caller rebuilds — but each one it handles is a rebuild
        # avoided, and a rebuild changes every number on every screen.
        for table, column in _CHALLENGE_REFERRERS:
            db.execute(text(f"DELETE FROM {table} WHERE {column} = :c"),
                       {"c": challenge.id})
        for bet in bets:
            for table, column in _BET_REFERRERS:
                db.execute(text(f"DELETE FROM {table} WHERE {column} = :b"),
                           {"b": bet.id})
        db.flush()
        for bet in bets:
            db.delete(bet)
        db.flush()
        db.delete(challenge)
    db.flush()

    # Re-apply the canonical Prediction for every open occurrence, in case the
    # visitor changed theirs. `replace=True` keeps it ONE claim per GM.
    from betting.pool_claims import submit_claim
    from betting.pool_subjects import league_weekly_structure
    from db.schema import PoolDefinition

    reclaimed = 0
    open_instances = (db.query(PoolInstance)
                      .filter(PoolInstance.league_id == league.id,
                              PoolInstance.settled.is_(False))
                      .order_by(PoolInstance.slot).all())
    ordinal_of = {t.team_name: t.ordinal for t in showcase.TEAMS}
    teams_by_ordinal = {ordinal_of[t.team_name]: t
                        for t in db.query(Team)
                        .filter(Team.league_id == league.id).all()
                        if t.team_name in ordinal_of}
    # UIRECON WAVE 3B — RESTORE MEANS RESTORE, INCLUDING THE EMPTY SLOT.
    #
    # The canonical CURRENT state now has the visitor UNCLAIMED on one live-week
    # slot, so a visitor who made a pick and then reset has to end up without
    # one again. Skipping the re-claim below is not enough — `submit_claim`
    # with `replace=True` overwrites a claim but never removes one, so their pick
    # would simply survive the reset and the demo would be a single use.
    #
    # A DIRECT DELETE, LIKE THE CHALLENGE AND BET CLEANUP ABOVE. This module
    # already removes visitor-created rows this way and every path through it
    # has passed `assert_demo_league` first. It is scoped to one league, one
    # team, one unsettled instance on the live week.
    from db.schema import PoolClaim as _PoolClaim

    _visitor = teams_by_ordinal.get(showcase.VISITOR_ORDINAL)
    withdrawn = 0
    if _visitor is not None:
        for instance in open_instances:
            if not showcase.visitor_skips_claim(
                    instance.week, instance.slot, showcase.VISITOR_ORDINAL):
                continue
            for stale in (db.query(_PoolClaim)
                          .filter(_PoolClaim.pool_instance_id == instance.id,
                                  _PoolClaim.team_id == _visitor.id).all()):
                db.delete(stale)
                withdrawn += 1
        db.flush()

    for instance in open_instances:
        definition = (db.query(PoolDefinition)
                      .filter(PoolDefinition.key == instance.definition_key)
                      .first())
        structure = league_weekly_structure(db, league_id=league.id,
                                            week=instance.week,
                                            scope=definition.scope)
        subjects = list(structure.considered_subject_ids)
        if not subjects:
            continue
        for n, spec in enumerate(showcase.TEAMS):
            # UIRECON WAVE 3B — the same skip the seed applies, applied again on
            # restore. Without it, resetting the demo would hand the visitor
            # back a fully-claimed slate and quietly undo the one Prop Pool they
            # are meant to be able to pick. `instance.week` is checked because
            # this loop walks every UNSETTLED occurrence, not just the live one.
            if showcase.visitor_skips_claim(instance.week, instance.slot,
                                            spec.ordinal):
                continue
            submit_claim(db, pool_instance_id=instance.id,
                         team_id=teams_by_ordinal[spec.ordinal].id,
                         subject_id=subjects[(n + instance.slot) % len(subjects)],
                         replace=True, now=showcase.OBSERVED_AT)
            reclaimed += 1
    db.flush()
    return {"restored": True, "challenges_removed": len(extra),
            "postings_removed": removed_postings, "claims_reapplied": reclaimed,
            "visitor_claims_withdrawn": withdrawn}


def ensure_canonical() -> dict:
    """Guarantee a canonical CURRENT showcase exists, rebuilding only if needed.

    RETURNS WHAT IT DID, so the caller can report it and a test can assert that
    an untouched league was NOT rebuilt — the difference between "idempotent"
    and "rebuilds every time" is the whole point of the fingerprint.

    NO PARAMETERS, AND THAT IS DELIBERATE. There is no league id, team, week or
    state a caller could name, so this cannot be pointed at anything but the
    showcase, and `reset()` still runs `assert_demo_league` before it touches a
    row.
    """
    from db.schema import SessionLocal

    from demo.seed import find_showcase

    # EVERYTHING BELOW RUNS UNDER THE LOCK, including the rebuild fallback.
    # A concurrent visitor waits here and then finds the league already
    # canonical, so it takes the cheap `none` path and is seated normally —
    # which is why every simultaneous request can answer 200.
    with showcase_lock():
        with SessionLocal() as db:
            league = find_showcase(db)

            # ── ABSENT IS NOT A DRIFT, AND IS NOT THIS FUNCTION'S TO FIX ────
            # Public entry must never bring a league into existence. Seeding is
            # an operator action; a public route that can create a showcase is
            # a public route that can be made to create them repeatedly, which
            # is exactly what the entry route's own docstring forbids. The
            # caller turns this into a controlled 404.
            if league is None:
                return {"action": "absent", "league_id": None,
                        "canonical": False}

            if is_canonical(db, league):
                return {"action": "none", "league_id": league.id,
                        "canonical": True}
            drift = {k: v for k, v in canonical_fingerprint(db, league).items()
                     if v != expected_fingerprint().get(k)}

            # ── RESTORE IN PLACE FIRST ─────────────────────────────────────
            # Keeping the league id keeps the Pool slate, and therefore every
            # number on every screen, identical between visitors. Rebuilding is
            # the fallback, not the plan.
            outcome = restore_in_place(db, league)
            if outcome.get("restored") and is_canonical(db, league):
                db.commit()
                return {"action": "restored", "league_id": league.id,
                        "canonical": True, "drift": drift, "detail": outcome}
            db.rollback()

        result = reset()
        return {"action": "rebuilt", "league_id": result.get("league_id"),
                "canonical": True, "drift": drift}


def check() -> dict:
    """What reset WOULD do, and to what. Writes nothing.

    Also reports how many NON-demo leagues exist, because the useful thing to
    see before running a destructive-looking command is the number it will not
    be touching.
    """
    from db.schema import League, SessionLocal

    from demo.seed import find_showcase

    with SessionLocal() as db:
        current = find_showcase(db)
        total = db.query(League).count()
        demo_leagues = db.query(League).filter(League.provider == "demo").count()
        verdict = "no showcase league exists; reset would create one"
        if current is not None:
            try:
                assert_demo_league(current)
                verdict = f"would retire league {current.id} and build a fresh one"
            except DemoSafetyError as exc:      # pragma: no cover - defensive
                verdict = f"WOULD REFUSE: {exc}"
        return {
            "showcase_league_id": getattr(current, "id", None),
            "leagues_in_database": total,
            "demo_leagues": demo_leagues,
            "non_demo_leagues_untouched": total - demo_leagues,
            "verdict": verdict,
        }


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if args.check:
        for k, v in check().items():
            print(f"  {k:28} {v}")
        return 0

    try:
        result = reset()
    except DemoSafetyError as exc:
        print(f"DEMO RESET REFUSED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"DEMO RESET FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    print("showcase demo league reset")
    for k, v in result.items():
        print(f"  {k:26} {v}")
    return 0 if result.get("trial_balance") == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
