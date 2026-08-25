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

    ── TWO SHAPES OF OPEN ACTION, AND BOTH LEAVE ESCROW (UIRECON Wave 5) ────

    An ACCEPTED contest holds both GMs' stakes in `escrow:{bet}`, which the
    settlement below resolves. An OFFERED one — which canonical CURRENT now also
    leaves behind, so Status has an ACTION REQUIRED and a WAITING rail — holds
    only the issuer's Anchor, in `escrow:challenge:{id}`, and has no Bet at all.
    The pending-Bet count below is therefore blind to it: a showcase whose only
    open action was two unanswered offers would report nothing to resolve and
    strand their escrow globally, which is the exact failure this function was
    written to stop, arriving by a second door.
    """
    from db.schema import Bet, Team, Wallet
    from betting.settlement_engine import settle_week

    from demo import gameplay, states

    team_ids = [t.id for t in db.query(Team)
                .filter(Team.league_id == league.id).all()]
    if not team_ids:
        return {"resolved": 0}

    # THE UNANSWERED OFFERS RUN OUT FIRST, through the system-owned expiry that
    # returns the Anchor by exact reverse legs. Before the pending-Bet gate,
    # because they are invisible to it.
    expired = gameplay.expire_live_negotiations(
        db, league=league, week=int(league.provider_current_week or 0))

    wallet_ids = [w.id for w in db.query(Wallet)
                  .filter(Wallet.team_id.in_(team_ids)).all()]
    pending = (db.query(Bet)
               .filter(Bet.wallet_id.in_(wallet_ids),
                       Bet.status == "pending").count()) if wallet_ids else 0
    if not pending:
        return {"resolved": 0, "expired": expired["expired"]}

    week = int(league.provider_current_week or 0)
    if week not in showcase.REGULAR_SCHEDULE:
        # Nothing this module can finalize; leave it rather than guess.
        return {"resolved": 0, "week": week, "expired": expired["expired"],
                "skipped": "week not scheduled"}

    teams = states._teams_by_ordinal(db, league.id)
    states.finalize_week(db, league, teams, week)
    settle_week(week, db, league.id)
    db.flush()
    return {"resolved": pending, "week": week,
            "expired": expired["expired"]}


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
    from beefs.proposal_lifecycle import OFFERED
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
        # UIRECON WAVE 5 — COUNTING CHALLENGES IS NOT ENOUGH ANY MORE.
        #
        # The showcase now leaves two live-week challenges UNANSWERED, and a
        # visitor answering one does not change how many challenges exist — it
        # changes what state one of them is in. Without this term the two open
        # rails would empty permanently on the first Accept and the fingerprint
        # would go on reporting the league as pristine, which is the exact shape
        # of the Wave 3 defect this file already carries a scar from.
        #
        # OFFERED, NOT MERELY OPEN. A COUNTER is still an open negotiation, so a
        # count over `OPEN_STATES` does not move when a visitor counters — and
        # the demo would keep a countered version, on the wrong rail, for every
        # visitor after them. The canonical state is the one the seeder wrote:
        # offered, at version one.
        "offered_challenges": (db.query(BeefChallenge)
                               .filter(BeefChallenge.challenger_team_id.in_(team_ids),
                                       BeefChallenge.response_status == OFFERED)
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

    # ── THE CLAIMS THE SHOWCASE DELIBERATELY DOES NOT MAKE ───────────────────
    #
    # `claim_week_pools` and the re-claim loop in `_restore` both skip the
    # visitor on one live-week slot, so a PRISTINE showcase holds one claim
    # fewer than a full grid. Counting the full grid here made an untouched
    # league fail `is_canonical`, which made `ensure_canonical` treat every
    # single visit as dirty — and when restore-in-place could not reconcile a
    # difference that was never drift, it fell through to a full REBUILD. A new
    # league id draws a different Pool rotation, so the slate, the pool winners
    # and the standings all moved between visitors, and `/demo/enter` replayed
    # an entire season on every request.
    #
    # THE SKIPS ARE COUNTED, NOT ASSUMED. `visitor_skips_claim` is the single
    # predicate both claim loops consult, so asking it here is asking the same
    # question the seeder answered rather than restating its answer as a
    # constant. Change the slot, the seat, or the number of skipped claims and
    # this expectation follows without being edited — which is the rule the
    # docstring above states and the rule the original line broke.
    #
    # THE RANGES ARE THE FIXTURE'S OWN. Weeks are the `played` window this
    # function already reasons in; slots are 1..POOL_SLOTS_PER_WEEK, matching
    # `pool_instance.slot`'s CHECK constraint; ordinals come off `showcase.TEAMS`
    # itself, which is what both claim loops iterate. No number is invented here.
    skipped = sum(
        1
        for week in range(showcase.START_WEEK, showcase.START_WEEK + played)
        for slot in range(1, showcase.POOL_SLOTS_PER_WEEK + 1)
        for spec in showcase.TEAMS
        if showcase.visitor_skips_claim(week, slot, spec.ordinal)
    )

    return {
        "current_week": showcase.CURRENT_WEEK,
        "season_closed": False,
        "teams": showcase.TEAM_COUNT,
        # UIRECON WAVE 5 — the accepted contests PLUS the live week's open
        # negotiations. Every term is read off the fixture tuple that produces
        # it, so adding or removing a contest moves this expectation with it.
        # Wave 3's scar is directly above: a hand-written count here made every
        # untouched visit look dirty and replayed a whole season per request.
        #
        # FINAL POR §6 ADDED A FOURTH TERM, AND OMITTING IT REOPENED THAT SCAR.
        # `VISITOR_WRAPUP_MATCHUPS` seeds the visitor one settled contest in the
        # week Wrap Up opens on, so `versus_card()` issues it and the league
        # holds 39 challenges while this sum still expected 38. One short is
        # enough: `is_canonical` was false on a pristine showcase, so
        # `ensure_canonical` rebuilt on EVERY `/demo/enter` — a new league id, a
        # new Pool rotation and a full season replayed per request. The term is
        # read off the tuple for the same reason the other three are.
        "challenges": (len(showcase.VERSUS_PER_WEEK_MARKETS) * played
                       + len(showcase.VISITOR_LIVE_EXTRA_MATCHUPS)
                       + len(showcase.VISITOR_WRAPUP_MATCHUPS)
                       + len(showcase.VISITOR_OPEN_NEGOTIATIONS)),
        "offered_challenges": len(showcase.VISITOR_OPEN_NEGOTIATIONS),
        "pool_claims": (showcase.POOL_SLOTS_PER_WEEK * showcase.TEAM_COUNT
                        * played) - skipped,
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
#: Everything that points AT a PROPOSAL. A challenge written by the funded
#: lifecycle owns proposals, and those own rows of their own — so the graph is
#: two levels deep and clearing only the first level leaves the second holding a
#: foreign key. `beef_challenges.active_proposal_id` and `accepted_proposal_id`
#: point back UP at a proposal too, which is why the challenge's own pointers
#: are released before any of this runs.
_PROPOSAL_REFERRERS: tuple = (
    ("beef_proposal_starters", "proposal_id"),
    ("protocol_events", "proposal_id"),
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


def _remove_challenge(db, challenge) -> dict:
    """Delete one challenge and everything that belongs to it. Commits nothing.

    THE POSTINGS GO WHOLE OR NOT AT ALL. Each escrow leg is deleted with the
    entire posting it belongs to, so a balanced set leaves together and the
    trial balance cannot drift. A posting that reaches an account outside this
    challenge is refused rather than half-removed, and the caller rebuilds.

    BOTH ESCROW SHAPES ARE COVERED. An accepted challenge holds its money in
    `escrow:{bet_id}`, one account per side; an offered one — which has no Bets
    at all — holds the issuer's Anchor in `escrow:challenge:{id}`. Handling only
    the first would leave an unanswered challenge's escrow stranded on the
    ledger after its row was gone.
    """
    from sqlalchemy import text
    from db.schema import Bet

    bets = db.query(Bet).filter(
        Bet.beef_challenge_id == challenge.id).all()
    # The challenge POINTS AT its two bets (`fk_challenger_bet_id`), so the
    # references have to be released before the bets can go. Clearing them
    # first — rather than deleting the challenge first — keeps the rows
    # available for the escrow lookup below.
    challenge.challenger_bet_id = None
    challenge.challenged_bet_id = None
    # THE PROPOSAL POINTERS COME OFF FOR THE SAME REASON THE BET ONES DO. A
    # funded-lifecycle challenge points AT the version in force, so the
    # proposals cannot be deleted while the container still names them.
    challenge.active_proposal_id = None
    challenge.accepted_proposal_id = None
    db.add(challenge)
    db.flush()

    accounts = [f"escrow:{bet.id}" for bet in bets]
    accounts.append(f"escrow:challenge:{challenge.id}")

    postings = 0
    for account in accounts:
        posting_ids = [r[0] for r in db.execute(text(
            "SELECT DISTINCT posting_id FROM ledger_entries "
            "WHERE account = :a"), {"a": account}).fetchall()]
        for pid in posting_ids:
            legs = db.execute(text(
                "SELECT account, amount_cents FROM ledger_entries "
                "WHERE posting_id = :p"), {"p": pid}).fetchall()
            if sum(int(c) for _a, c in legs) != 0:
                return {"ok": False, "postings": postings,
                        "reason": f"posting {pid} is unbalanced"}
            db.execute(text(
                "DELETE FROM ledger_entries WHERE posting_id = :p"),
                {"p": pid})
            postings += 1

    # ── THE FOREIGN-KEY GRAPH UNDER A CHALLENGE, DELETED LEAF-FIRST ───────
    #
    # EVERY REFERRER, ENUMERATED FROM THE GRAPH rather than discovered one
    # IntegrityError at a time. A row this misses does not corrupt anything —
    # the delete refuses, `restore_in_place` returns False and the caller
    # rebuilds — but each one it handles is a rebuild avoided, and a rebuild
    # changes every number on every screen.
    #
    # THREE LEVELS DEEP once a challenge carries proposals and funding:
    #
    #   beef_challenges
    #     ├─ beef_proposals ──┬─ beef_proposal_starters
    #     │                   └─ protocol_events (proposal_id)
    #     ├─ protocol_events ─┬─ ledger_posting_batches ─┐
    #     │                   ├─ challenge_funding_legs ─┘
    #     │                   └─ challenge_final_lock(_claim)s
    #     └─ beef_starters · feed_events · bets
    #
    # ORDER IS THE WHOLE OF THE CORRECTNESS, so it is spelled out here rather
    # than left to the order of a tuple that reads as an unordered set. The
    # tuples above stay as the DECLARATION of the graph; this is the traversal.
    proposal_ids = [r[0] for r in db.execute(text(
        "SELECT id FROM beef_proposals WHERE challenge_id = :c"),
        {"c": challenge.id}).fetchall()]

    def _sql(statement: str, **params) -> None:
        db.execute(text(statement), params)

    # 1 — funding legs first: they point at a posting batch, at a protocol
    #     event, and at each other (a reversal names the leg it reverses).
    _sql("DELETE FROM challenge_funding_legs WHERE challenge_id = :c",
         c=challenge.id)
    # 2 — the Final-Lock records, which also name a protocol event.
    _sql("DELETE FROM challenge_final_lock_claims WHERE challenge_id = :c",
         c=challenge.id)
    _sql("DELETE FROM challenge_final_locks WHERE challenge_id = :c",
         c=challenge.id)
    # 3 — the posting batches those legs referred to, found through the events
    #     that caused them. Their ledger entries have already gone above.
    _sql("DELETE FROM ledger_posting_batches WHERE protocol_event_id IN "
         "(SELECT id FROM protocol_events WHERE challenge_id = :c)",
         c=challenge.id)
    # 4 — proposal-level leaves, before the proposals themselves.
    for proposal_id in proposal_ids:
        _sql("DELETE FROM ledger_posting_batches WHERE protocol_event_id IN "
             "(SELECT id FROM protocol_events WHERE proposal_id = :p)",
             p=proposal_id)
        _sql("DELETE FROM beef_proposal_starters WHERE proposal_id = :p",
             p=proposal_id)
        _sql("DELETE FROM protocol_events WHERE proposal_id = :p",
             p=proposal_id)
    db.flush()
    # 5 — the events themselves, now unreferenced.
    _sql("DELETE FROM protocol_events WHERE challenge_id = :c", c=challenge.id)
    # 6 — and the challenge's own direct children.
    _sql("DELETE FROM beef_proposals WHERE challenge_id = :c", c=challenge.id)
    _sql("DELETE FROM beef_starters WHERE beef_challenge_id = :c",
         c=challenge.id)
    _sql("DELETE FROM feed_events WHERE challenge_id = :c", c=challenge.id)
    db.flush()

    for bet in bets:
        for table, column in _BET_REFERRERS:
            db.execute(text(f"DELETE FROM {table} WHERE {column} = :b"),
                       {"b": bet.id})
    db.flush()
    for bet in bets:
        db.delete(bet)
    db.flush()
    db.delete(challenge)
    return {"ok": True, "postings": postings, "reason": None}


def _seeded_negotiation_rows(db, league, teams_by_ordinal) -> list:
    """Every challenge occupying one of the fixture's open-negotiation slots.

    BY SHAPE — week, issuer, recipient — because a re-issued negotiation carries
    a new id and nothing may depend on the old one.
    """
    from db.schema import BeefChallenge
    from demo import showcase

    ordinal_by_team_id = {t.id: o for o, t in teams_by_ordinal.items()}
    rows = (db.query(BeefChallenge)
            .filter(BeefChallenge.week == league.provider_current_week)
            .order_by(BeefChallenge.id).all())
    return [c for c in rows
            if showcase.is_open_negotiation(
                c.week,
                ordinal_by_team_id.get(c.challenger_team_id),
                ordinal_by_team_id.get(c.challenged_team_id))]


def _open_negotiations_need_restoring(db, league, teams_by_ordinal) -> bool:
    """Whether the fixture's unanswered challenges are still unanswered.

    CANONICAL MEANS OFFERED AND UNCOUNTERED. An accepted, declined or expired
    negotiation is obviously answered; a COUNTERED one is subtler — it is still
    open, but its terms are a version the seeder never wrote and the decision
    has changed hands. Both are drift, and both are reconciled the same way.
    """
    from db.schema import BeefProposal
    from beefs.proposal_lifecycle import OFFERED
    from demo import showcase

    rows = _seeded_negotiation_rows(db, league, teams_by_ordinal)
    if len(rows) != len(showcase.VISITOR_OPEN_NEGOTIATIONS):
        return True
    for challenge in rows:
        if challenge.response_status != OFFERED:
            return True
        versions = (db.query(BeefProposal)
                    .filter(BeefProposal.challenge_id == challenge.id).count())
        if versions != 1:
            return True
    return False


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
    # RESOLVED ONCE, USED BY BOTH HALVES. The negotiation reconciliation below
    # and the Pool re-claim further down both need the fixture's ordinal map.
    _ordinal_of = {t.team_name: t.ordinal for t in showcase.TEAMS}
    teams_by_ordinal = {_ordinal_of[t.team_name]: t
                        for t in db.query(Team)
                        .filter(Team.league_id == league.id).all()
                        if t.team_name in _ordinal_of}
    canonical_count = expected_fingerprint()["challenges"]
    challenges = (db.query(BeefChallenge)
                  .filter(BeefChallenge.challenger_team_id.in_(team_ids))
                  .order_by(BeefChallenge.id).all())
    extra = challenges[canonical_count:]

    removed_postings = 0
    for challenge in extra:
        removed = _remove_challenge(db, challenge)
        if not removed["ok"]:
            return {"restored": False, "reason": removed["reason"]}
        removed_postings += removed["postings"]
    db.flush()

    # ── UIRECON WAVE 5 · THE OPEN NEGOTIATIONS, PUT BACK AS THEY WERE ───────
    #
    # The showcase leaves two live-week challenges unanswered so Status has an
    # ACTION REQUIRED and a WAITING rail to show. A visitor can genuinely answer
    # the incoming one — that is the whole point of seeding it — and answering
    # it does not create an EXTRA challenge, it changes the state of a canonical
    # one. The loop above would therefore not have touched it, and the demo
    # would have lost a rail permanently on the first Accept.
    #
    # RECONCILED BY SHAPE, NOT BY ID. A re-issued negotiation gets a new
    # challenge id, so nothing may identify these by position or number. The
    # fixture states the pairing and `showcase.is_open_negotiation` is the one
    # predicate both the seeder and this reconciliation ask.
    #
    # REMOVED AND RE-ISSUED RATHER THAN REWOUND. Rewinding an acceptance would
    # mean un-placing two Bets and reversing an escrow migration by hand — a
    # second settlement engine living in a reset path. Removing the row and
    # asking the seeder for a fresh one uses the same governed command the
    # original came from, which is the only way the replacement is guaranteed
    # to be the same kind of object.
    negotiations_restored = 0
    if _open_negotiations_need_restoring(db, league, teams_by_ordinal):
        for challenge in _seeded_negotiation_rows(db, league, teams_by_ordinal):
            removed = _remove_challenge(db, challenge)
            if not removed["ok"]:
                return {"restored": False, "reason": removed["reason"]}
            removed_postings += removed["postings"]
        db.flush()
        from demo.gameplay import open_live_negotiations
        reissued = open_live_negotiations(
            db, league=league, teams=teams_by_ordinal,
            week=league.provider_current_week)
        negotiations_restored = len(reissued["issued"])
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
            "visitor_claims_withdrawn": withdrawn,
            "negotiations_restored": negotiations_restored}


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
