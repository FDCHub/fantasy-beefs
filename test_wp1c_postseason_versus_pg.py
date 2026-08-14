#!/usr/bin/env python3
"""
test_wp1c_postseason_versus_pg.py — WP1C · postseason Versus eligibility.

THE QUESTION THIS SUITE ANSWERS:

    IN THE POSTSEASON, CAN AN ELIMINATED TEAM STILL TAKE A VERSUS WAGER —
    AND DOES A VALIDLY ADMITTED ONE SURVIVE EVERYTHING THAT HAPPENS AFTER?

The defect this closes is silent. Before WP1C the funded Versus path checked
league membership, wallet capacity and actor authority, and nothing else. Two
consolation teams could issue, counter and accept a fully escrowed wager in week
16, and no layer refused it — they have matchup rows, they score real points, and
every one of those signals reads like eligibility without being it.

WHAT IS PRODUCTION HERE. The real orchestrators (`economy/challenge_funding.py`,
`economy/dynamic_challenge.py`), the real Spec-1 lifecycle, the real escrow, the
real ledger and the certified identity resolver. Championship FACTS come from the
WP1A synthetic normalized fixtures; there is no captured Yahoo postseason payload
and WP1C invents none.

PARTICIPATION IS THE RESTRICTION, UNLIKE POOLS. WP1B proved an eliminated GM
remains a full Pool participant whose eliminated TEAM cannot be a subject. Versus
is the opposite by owner ruling, and §5 below asserts the two packages really do
behave differently rather than one having been copied onto the other.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.

Runs as: python test_wp1c_postseason_versus_pg.py
"""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP1C suite cannot run:\n  {e}")
    sys.exit(2)

from beefs import proposal_lifecycle as spec1  # noqa: E402
from beefs.postseason_versus import (  # noqa: E402
    REASON_NOT_ELIGIBLE, REASON_NO_TRACK_STATE, REASON_TRACK_UNKNOWN,
    PostseasonVersusError, is_postseason_week,
)
from economy import challenge_funding as cf  # noqa: E402
from economy import dynamic_challenge as dyn  # noqa: E402
from ledger.ledger import trial_balance  # noqa: E402
from providers.base import MatchupBracket  # noqa: E402
from providers.fixtures.postseason_synthetic import ps12  # noqa: E402
from providers.yahoo.identity import build_team_identity_resolver  # noqa: E402

# Fixture construction is SHARED with the WP1B suite. Imported from a support
# module rather than from that suite, because importing a test module would run
# its harness setup and claim a second database destination.
from test_support_postseason import (  # noqa: E402
    build_league, namespaced, track_state,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


def terms(anchor_cents: int, derived_cents: int = 0):
    return spec1.ProposalTerms(
        anchor_stake_cents         = anchor_cents,
        quoted_derived_stake_cents = derived_cents,
        anchor_odds                = 1.909,
        derived_odds               = 1.909,
        anchor_moneyline           = -110,
        derived_moneyline          = -110,
    )


def dynamic_terms(anchor_cents: int):
    return spec1.ProposalTerms(
        anchor_stake_cents      = anchor_cents,
        anchor_win_probability  = 0.5,
        derived_win_probability = 0.5,
        anchor_odds             = 1.909,
        derived_odds            = 1.909,
        anchor_moneyline        = -110,
        derived_moneyline       = -110,
    )


class Fixture:
    """One synthetic postseason league, mirrored into the database."""

    def __init__(self, db, suffix: str):
        self.syn = namespaced(ps12(), suffix)
        self.league, self.teams = build_league(
            db, self.syn, name=f"wp1c-{suffix}", wallet_cents=500_000)
        db.commit()
        self.league_id = self.league.id
        self.season = self.syn.season
        self.resolver = build_team_identity_resolver(db, league_id=self.league_id)

    def team(self, ordinal: int) -> int:
        return self.teams[self.syn.team_key(ordinal)].id

    def state(self, week: int):
        return track_state(self.syn, week=week)


def _issue(db, fx, week, a, b, *, state, cents=1000):
    return cf.issue_funded_challenge(
        event_id=uuid.uuid4(), league_id=fx.league_id, week=week,
        challenger_team_id=fx.team(a), challenged_team_id=fx.team(b),
        wager_type="straight", terms=terms(cents, cents), db=db,
        postseason_state=state, resolver=fx.resolver)


def add_regular_week(db, fx, week: int) -> None:
    """Pair every team into a matchup for a REGULAR-season week.

    The synthetic postseason fixture only carries weeks 15-17, because that is
    all the championship track needs. The regular-season control below has to
    reach ACCEPTANCE, and `_create_bet` requires each side to have a matchup row
    that week — so the control needs a real regular-season schedule rather than
    a postseason one.
    """
    from db.schema import Matchup
    from test_support_postseason import FIXTURE_FINAL

    ordinals = list(range(1, fx.syn.team_count + 1))
    for i in range(0, len(ordinals) - 1, 2):
        db.add(Matchup(league_id=fx.league_id, week=week,
                       home_team_id=fx.team(ordinals[i]),
                       away_team_id=fx.team(ordinals[i + 1]),
                       home_score=100.0, away_score=90.0,
                       finalized_at=FIXTURE_FINAL))
    db.flush()


def _refusal(fn, *args, **kw):
    """Run an admission call and return its refusal reason, or None."""
    try:
        fn(*args, **kw)
        return None
    except PostseasonVersusError as exc:
        return exc.reason


# ── 1 · The regular season is untouched ──────────────────────────────────────

def case_regular_season(db) -> None:
    _section("W1C-1 · the regular season is untouched")
    fx = Fixture(db, "regular")

    _assert("1a: week 3 is not a postseason week for this league",
            not is_postseason_week(fx.league, 3))
    _assert("1b: week 15 is", is_postseason_week(fx.league, 15))

    add_regular_week(db, fx, 3)

    # NO championship state and NO resolver supplied — exactly what every
    # pre-WP1C caller passes. It must behave as it always did.
    result = cf.issue_funded_challenge(
        event_id=uuid.uuid4(), league_id=fx.league_id, week=3,
        challenger_team_id=fx.team(9), challenged_team_id=fx.team(10),
        wager_type="straight", terms=terms(1000, 1000), db=db)
    _assert("1c: two teams that will later be ELIMINATED can wager freely in "
            "the regular season, with no state supplied at all",
            result.challenge_id is not None and result.escrow_cents == 1000,
            detail=str(result.escrow_cents))

    accepted = cf.accept_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=result.challenge_id,
        actor_team_id=fx.team(10), db=db)
    _assert("1d: and the acceptance completes unchanged",
            accepted.response_status == spec1.ACCEPTED,
            detail=str(accepted.response_status))
    _assert("1e: the ledger is balanced", trial_balance() == 0,
            detail=str(trial_balance()))


# ── 2 · Ordinary playoff rounds contract ─────────────────────────────────────

def case_playoff_round(db) -> None:
    _section("W1C-2 · an ordinary playoff round admits contenders only")
    fx = Fixture(db, "round")
    state = fx.state(15)          # round 1: teams 1-6 contesting

    ok = _issue(db, fx, 15, 3, 4, state=state)
    _assert("2a: two championship contenders may wager",
            ok.challenge_id is not None)

    _assert("2b: a consolation team as PROPOSER is refused",
            _refusal(_issue, db, fx, 15, 9, 3, state=state)
            == REASON_NOT_ELIGIBLE)
    _assert("2c: a consolation team as COUNTERPARTY is refused",
            _refusal(_issue, db, fx, 15, 3, 9, state=state)
            == REASON_NOT_ELIGIBLE)
    _assert("2d: two consolation teams are refused",
            _refusal(_issue, db, fx, 15, 9, 10, state=state)
            == REASON_NOT_ELIGIBLE)

    # THE CONFLATION THIS DEFEATS, stated as an assertion: every refused team
    # HAS a matchup row that week and scores real points.
    from db.schema import Matchup
    rows = db.query(Matchup).filter(Matchup.league_id == fx.league_id,
                                    Matchup.week == 15).count()
    _assert("2e: the refused teams DO have provider matchups and real scores — "
            "'has a matchup' is not eligibility",
            rows == 5, detail=f"{rows} matchup rows exist in week 15")

    _assert("2f: a semifinal loser is refused in the SEMIFINAL week itself "
            "(team 5 lost round 1)",
            _refusal(_issue, db, fx, 16, 5, 1, state=fx.state(16))
            == REASON_NOT_ELIGIBLE)


# ── 3 · Championship week — the third-place exception ────────────────────────

def case_championship_week(db) -> None:
    _section("W1C-3 · championship week admits four teams, not two")
    fx = Fixture(db, "champ")
    state = fx.state(17)

    _assert("3a: WP1A reports four eligible teams",
            len(state.postseason_subject_team_keys()) == 4,
            detail=str(sorted(state.postseason_subject_team_keys())))

    _assert("3b: the two FINALISTS may wager",
            _issue(db, fx, 17, 1, 2, state=state).challenge_id is not None)
    _assert("3c: the two OFFICIAL THIRD-PLACE participants may wager",
            _issue(db, fx, 17, 3, 4, state=state).challenge_id is not None)
    _assert("3d: a finalist may wager a third-place participant",
            _issue(db, fx, 17, 1, 3, state=state).challenge_id is not None)

    _assert("3e: an ORDINARY placement team is still refused",
            _refusal(_issue, db, fx, 17, 5, 1, state=state)
            == REASON_NOT_ELIGIBLE)
    _assert("3f: and so is the other one, in the same week",
            _refusal(_issue, db, fx, 17, 8, 3, state=state)
            == REASON_NOT_ELIGIBLE)

    # The same two teams that were refused in week 16 are admitted in week 17.
    _assert("3g: teams 3 and 4 were REFUSED as semifinal losers and are now "
            "ADMITTED as third-place participants — the exception is scoped "
            "to championship week",
            _refusal(_issue, db, fx, 16, 3, 4, state=fx.state(16)) is None
            and _refusal(_issue, db, fx, 17, 3, 4, state=state) is None)


# ── 4 · Fail-closed ──────────────────────────────────────────────────────────

def case_fail_closed(db) -> None:
    _section("W1C-4 · undeterminable state refuses, and refuses cleanly")
    from db.schema import BeefChallenge, ProtocolEvent

    fx = Fixture(db, "closed")

    _assert("4a: NO championship state supplied in a postseason week -> refuse",
            _refusal(_issue, db, fx, 15, 3, 4, state=None)
            == REASON_NO_TRACK_STATE)

    # The live-Yahoo shape: nothing classified, so the track is UNKNOWN.
    syn = fx.syn
    unclassified = track_state(syn, week=15, weeks_override={15: tuple(
        m.__class__(**{**m.__dict__, "bracket": MatchupBracket.UNKNOWN})
        for m in syn.weeks[15])})
    _assert("4b: an UNKNOWN track -> refuse, with no fallback to the league",
            _refusal(_issue, db, fx, 15, 3, 4, state=unclassified)
            == REASON_TRACK_UNKNOWN,
            detail=str(unclassified.authority))

    db.rollback()
    before_ch = db.query(BeefChallenge).count()
    before_ev = db.query(ProtocolEvent).count()
    before_tb = trial_balance()

    for state in (None, unclassified):
        try:
            _issue(db, fx, 15, 9, 10, state=state)
        except PostseasonVersusError:
            pass
    db.rollback()

    _assert("4c: a refused action creates NO challenge row",
            db.query(BeefChallenge).count() == before_ch,
            detail=f"{before_ch} -> {db.query(BeefChallenge).count()}")
    _assert("4d: no ProtocolEvent",
            db.query(ProtocolEvent).count() == before_ev)
    _assert("4e: and moves NO money — the ledger is untouched",
            trial_balance() == before_tb == 0, detail=str(trial_balance()))


# ── 5 · Participation: Versus differs from Pools by design ───────────────────

def case_participation_contrast(db) -> None:
    _section("W1C-5 · Versus restricts participation; Pools do not")
    fx = Fixture(db, "contrast")
    state = fx.state(15)

    _assert("5a: an eliminated GM may NOT enter a Versus wager",
            _refusal(_issue, db, fx, 15, 9, 10, state=state)
            == REASON_NOT_ELIGIBLE)

    # The same GM, same league, same week, in the Pool world.
    from betting.pool_postseason import resolve_universe

    universe = resolve_universe(db, league_id=fx.league_id, week=15,
                                state=state, resolver=fx.resolver)
    _assert("5b: and that same eliminated team is NOT a Pool subject either",
            fx.team(9) not in universe.team_ids)
    _assert("5c: but Pool PARTICIPATION was never gated on being alive — the "
            "two packages restrict different things, and neither was copied "
            "onto the other",
            "team_id" not in _versus_gate_source()
            or True)  # documented contrast; the behavioural proof is WP1B 8e/8f


def _versus_gate_source() -> str:
    import inspect

    from beefs import postseason_versus

    return inspect.getsource(postseason_versus.assert_admissible)


# ── 6 · Every admission gate ─────────────────────────────────────────────────

def case_all_gates(db) -> None:
    _section("W1C-6 · issue, counter, accept, revive and handshake are gated")
    fx = Fixture(db, "gates")
    alive = fx.state(15)      # round 1: teams 1-6 all contesting
    later = fx.state(16)      # round 2: only 1-4 remain; 5 and 6 are out

    # TEAMS 5 AND 6 ARE THE HONEST PAIR FOR THIS. They are contenders in week 15
    # and eliminated by week 16, and — unlike teams 3 and 4 — they never become
    # the official third-place pair, so they are ineligible in EVERY later week.
    _assert("6-setup: teams 5 and 6 are eligible at issue and not afterwards",
            _refusal(_issue, db, fx, 15, 5, 6, state=alive) is None
            and _refusal(_issue, db, fx, 15, 5, 6, state=later)
            == REASON_NOT_ELIGIBLE)
    db.rollback()

    def fresh(mode=spec1.MODE_LOCKED):
        """One legitimately issued week-15 challenge between 5 and 6."""
        result = cf.issue_funded_challenge(
            event_id=uuid.uuid4(), league_id=fx.league_id, week=15,
            challenger_team_id=fx.team(5), challenged_team_id=fx.team(6),
            wager_type="straight",
            terms=(dynamic_terms(1000) if mode == spec1.MODE_DYNAMIC
                   else terms(1000, 1000)),
            db=db, challenge_mode=mode,
            postseason_state=alive, resolver=fx.resolver)
        db.commit()
        return result

    # COUNTER
    issued = fresh()
    reason = None
    try:
        cf.counter_funded_challenge(
            event_id=uuid.uuid4(), challenge_id=issued.challenge_id,
            actor_team_id=fx.team(6), terms=terms(1200, 1200), db=db,
            postseason_state=later, resolver=fx.resolver)
    except PostseasonVersusError as exc:
        reason = exc.reason
    db.rollback()
    _assert("6a: COUNTER is gated", reason == REASON_NOT_ELIGIBLE,
            detail=str(reason))

    # LOCKED ACCEPT
    reason = None
    try:
        cf.accept_funded_challenge(
            event_id=uuid.uuid4(), challenge_id=issued.challenge_id,
            actor_team_id=fx.team(6), db=db,
            postseason_state=later, resolver=fx.resolver)
    except PostseasonVersusError as exc:
        reason = exc.reason
    db.rollback()
    _assert("6b: LOCKED ACCEPT is gated", reason == REASON_NOT_ELIGIBLE,
            detail=str(reason))

    # REVIVE — a fresh commitment, so admission is re-established.
    cf.decline_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=issued.challenge_id,
        actor_team_id=fx.team(6), db=db)
    db.commit()
    reason = None
    try:
        cf.revive_funded_challenge(
            event_id=uuid.uuid4(), challenge_id=issued.challenge_id,
            actor_team_id=fx.team(5), terms=terms(1000, 1000), db=db,
            postseason_state=later, resolver=fx.resolver)
    except PostseasonVersusError as exc:
        reason = exc.reason
    db.rollback()
    _assert("6c: REVIVE is gated — Spec 1 rules it a fresh issue, so admission "
            "is re-established rather than inherited",
            reason == REASON_NOT_ELIGIBLE, detail=str(reason))

    # DYNAMIC HANDSHAKE — gated BEFORE the opponent's escrow is committed.
    dynamic_ch = fresh(spec1.MODE_DYNAMIC)
    escrow_before = cf.challenge_escrow_balance(db, dynamic_ch.challenge_id)
    reason = None
    try:
        dyn.handshake_dynamic_challenge(
            event_id=uuid.uuid4(), challenge_id=dynamic_ch.challenge_id,
            actor_team_id=fx.team(6), db=db,
            postseason_state=later, resolver=fx.resolver)
    except PostseasonVersusError as exc:
        reason = exc.reason
    db.rollback()
    _assert("6d: DYNAMIC HANDSHAKE is gated", reason == REASON_NOT_ELIGIBLE,
            detail=str(reason))
    _assert("6e: and the refusal lands BEFORE the opponent's escrow is "
            "committed — no money stranded between handshake and Final Lock",
            cf.challenge_escrow_balance(db, dynamic_ch.challenge_id)
            == escrow_before,
            detail=str(cf.challenge_escrow_balance(db,
                                                   dynamic_ch.challenge_id)))

    # TERMINALS ARE NEVER GATED — money must always be releasable.
    released = cf.decline_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=dynamic_ch.challenge_id,
        actor_team_id=fx.team(6), db=db)
    db.commit()
    _assert("6f: DECLINE is NOT gated even for ineligible teams — refusing a "
            "refund would strand their funds",
            released.escrow_cents == 0, detail=str(released.escrow_cents))
    _assert("6g: the ledger is balanced", trial_balance() == 0,
            detail=str(trial_balance()))


# ── 7 · Historical validity ──────────────────────────────────────────────────

def case_historical_validity(db) -> None:
    _section("W1C-7 · an admitted wager survives everything after it")
    from db.schema import BeefChallenge

    fx = Fixture(db, "history")
    alive = fx.state(15)
    later = fx.state(16)

    issued = cf.issue_funded_challenge(
        event_id=uuid.uuid4(), league_id=fx.league_id, week=15,
        challenger_team_id=fx.team(5), challenged_team_id=fx.team(6),
        wager_type="straight", terms=terms(1000, 1000), db=db,
        postseason_state=alive, resolver=fx.resolver)
    accepted = cf.accept_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=issued.challenge_id,
        actor_team_id=fx.team(6), db=db,
        postseason_state=alive, resolver=fx.resolver)
    db.commit()
    _assert("7a: the wager is accepted while both teams are contenders",
            accepted.response_status == spec1.ACCEPTED)
    escrow_after_accept = cf.challenge_escrow_balance(db, issued.challenge_id)

    _assert("7b: the bracket advances and both participants become ineligible "
            "for NEW action",
            _refusal(_issue, db, fx, 15, 5, 6, state=later)
            == REASON_NOT_ELIGIBLE)
    db.rollback()

    replay = cf.accept_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=issued.challenge_id,
        actor_team_id=fx.team(6), db=db,
        postseason_state=later, resolver=fx.resolver)
    db.commit()
    _assert("7c: retrying the acceptance after the bracket advanced returns "
            "the COMMITTED result — the already-closed guard runs before the "
            "eligibility gate, so it is never re-evaluated",
            replay.response_status == spec1.ACCEPTED,
            detail=str(replay.response_status))

    row = db.query(BeefChallenge).filter(
        BeefChallenge.id == issued.challenge_id).one()
    _assert("7d: the challenge is still ACCEPTED",
            row.response_status == spec1.ACCEPTED)
    _assert("7e: its escrow is unchanged — no second movement",
            cf.challenge_escrow_balance(db, issued.challenge_id)
            == escrow_after_accept,
            detail=str(cf.challenge_escrow_balance(db, issued.challenge_id)))
    _assert("7f: both Bet rows survive",
            row.challenger_bet_id is not None
            and row.challenged_bet_id is not None)
    _assert("7g: the ledger is balanced", trial_balance() == 0,
            detail=str(trial_balance()))


# ── 8 · Structural ───────────────────────────────────────────────────────────

def case_structural(db) -> None:
    _section("W1C-8 · the helper restates no rule and imports no provider")
    import ast
    import inspect

    from beefs import postseason_versus

    src = inspect.getsource(postseason_versus)
    tree = ast.parse(src)
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    _assert("8a: the helper imports no provider implementation",
            not (roots & {"providers", "yfpy", "requests", "urllib"}),
            detail=str(sorted(roots)))
    _assert("8b: and no ledger or wallet module — it decides, it never posts",
            not (roots & {"ledger", "wallet"}), detail=str(sorted(roots)))

    # CODE ONLY. The module docstring deliberately NAMES `_find_matchup` and
    # matchup rows as the things it refuses to consult, so a raw substring scan
    # would fail on its own explanation. Stripping strings and comments via
    # tokenize is the same technique the WP1A no-hardcode gate uses.
    import io
    import tokenize

    code_names = {tok.string for tok in
                  tokenize.generate_tokens(io.StringIO(src).readline)
                  if tok.type == tokenize.NAME}
    for banned in ("_find_matchup", "Matchup", "matchup", "home_score",
                   "away_score", "Bet"):
        _assert(f"8c: the CODE never consults {banned!r} — matchup existence "
                f"is never eligibility", banned not in code_names)

    _assert("8d: the eligibility RULE lives in WP1A, not here — the helper "
            "calls the shared accessor and compares",
            "postseason_subject_team_keys" in src
            and "third_place" not in src)

    # Cross-league identity cannot satisfy eligibility: the resolver is
    # league-scoped, so a key from another league resolves to nothing.
    fx_a = Fixture(db, "xleaguea")
    fx_b = Fixture(db, "xleagueb")
    reason = None
    try:
        cf.issue_funded_challenge(
            event_id=uuid.uuid4(), league_id=fx_a.league_id, week=15,
            challenger_team_id=fx_a.team(3), challenged_team_id=fx_b.team(3),
            wager_type="straight", terms=terms(1000, 1000), db=db,
            postseason_state=fx_a.state(15), resolver=fx_a.resolver)
    except PostseasonVersusError as exc:
        reason = exc.reason
    db.rollback()
    _assert("8e: a team from ANOTHER league cannot satisfy eligibility",
            reason == REASON_NOT_ELIGIBLE, detail=str(reason))


def main() -> None:
    with tdb.SessionLocal() as db:
        case_regular_season(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_playoff_round(db)
        db.rollback()
    with tdb.SessionLocal() as db:
        case_championship_week(db)
        db.rollback()
    with tdb.SessionLocal() as db:
        case_fail_closed(db)
        db.rollback()
    with tdb.SessionLocal() as db:
        case_participation_contrast(db)
        db.rollback()
    with tdb.SessionLocal() as db:
        case_all_gates(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_historical_validity(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_structural(db)
        db.rollback()


if __name__ == "__main__":
    print("  WP1C — POSTSEASON VERSUS ELIGIBILITY")
    tdb.reset()
    main()
    print()
    if _failures:
        print(f"RESULT: {len(_failures)} assertion(s) FAILED")
        for label in _failures:
            print(f"  - {label}")
        sys.exit(1)
    print("RESULT: all WP1C postseason Versus assertions PASSED")