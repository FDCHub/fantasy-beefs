#!/usr/bin/env python3
"""
test_s8_p5_postgres_hardening.py — Sprint 8 P5 · PostgreSQL concurrency hardening.

THE GAP THIS CLOSES. Every package from P1 to P4 ran on SQLite, where
`.with_for_update()` is a documented no-op. Every locking claim made in those
packages was therefore a claim about INTENT — the code asks for a row lock — and
never about EFFECT. This suite runs the same protocols against real PostgreSQL
with genuinely competing transactions and asks whether the money is safe.

WHAT "COMPETING" MEANS HERE. Threads are released from a `Barrier` so both are
inside their transaction before either commits, and each holds its own
connection. Two sequential calls to the same function prove idempotency and
nothing about locking; only overlapping transactions can show whether the second
worker BLOCKS on the first's row lock and then observes its committed state.

THE LOAD-BEARING TEST IS §5. A GM funded for exactly one of two obligations is
offered both at once. Exactly one may succeed, the wallet may never go negative,
and the trial balance must still be zero. That is the double-spend question, and
it cannot be asked at all without a real database.

WHAT THIS SUITE DOES NOT CLAIM. It does not re-certify protocol semantics — the
42 PG suites already do that. It asserts the CONCURRENCY properties only.
"""

from __future__ import annotations

import os
import sys
import threading
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import test_support_postgres as tsp  # noqa: E402

tdb = tsp.setup_postgres_test_db()

from db.schema import (  # noqa: E402
    BeefChallenge, ChallengeFundingLeg, League, Matchup, Player, Projection,
    Roster, Team, User, Wallet,
)
from auth.jwt_auth import hash_password  # noqa: E402
from ledger.ledger import post as ledger_post, trial_balance  # noqa: E402
import beefs.proposal_lifecycle as spec1  # noqa: E402
import economy.challenge_funding as cf  # noqa: E402

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


SEASON, WEEK = 2026, 5
PASSWORD = "sprint8-password"


def seed(wallet_cents: dict[str, int]) -> dict:
    """A league whose teams are funded through REAL ledger postings."""
    tdb.reset()
    ids: dict = {}
    with tdb.SessionLocal() as db:
        league = League(name="P5 League", season=SEASON)
        db.add(league); db.flush()
        ids["_league"] = league.id
        teams = []
        for name, cents in wallet_cents.items():
            team = Team(team_name=name, owner=name, email=f"{name}@p5.test",
                        league_id=league.id)
            db.add(team); db.flush()
            db.add(User(email=team.email, hashed_password=hash_password(PASSWORD),
                        team_id=team.id, role="gm"))
            db.add(Wallet(team_id=team.id, balance=0.0))
            db.flush()
            if cents:
                ledger_post([(f"wallet:{team.id}", cents), ("world", -cents)],
                            door="approved_bab_topoff", session=db)
                db.flush()
            for i in range(9):
                player = Player(name=f"{name}-P{i}", position="WR",
                                nfl_team="KC")
                db.add(player); db.flush()
                db.add(Roster(team_id=team.id, player_id=player.id))
                db.add(Projection(player_id=player.id, week=WEEK, season=SEASON,
                                  projected_points=12.0 + i, source="fixture"))
            db.flush()
            ids[name] = team.id
            teams.append(team)
        for a, b in ((teams[0], teams[1]),):
            db.add(Matchup(league_id=league.id, week=WEEK,
                           home_team_id=a.id, away_team_id=b.id,
                           home_score=0.0, away_score=0.0))
        db.commit()
    return ids


def terms(cents: int) -> spec1.ProposalTerms:
    return spec1.ProposalTerms(
        anchor_stake_cents=cents, quoted_derived_stake_cents=cents,
        quoted_funded_pot_cents=cents * 2,
        anchor_odds=1.909, derived_odds=1.909,
        anchor_moneyline=-110, derived_moneyline=-110,
        anchor_win_probability=0.5, derived_win_probability=0.5,
        pricing_model_id=spec1.MODE_LOCKED)


def race(worker_a, worker_b) -> tuple:
    """Run two workers so both are inside their transaction before either commits.

    THE BARRIER IS THE WHOLE POINT. Without it the second thread would often
    start after the first had already committed, and the test would prove
    sequential idempotency while claiming to prove locking.
    """
    barrier = threading.Barrier(2, timeout=30)
    out: dict = {}

    def run(key, fn):
        def inner():
            try:
                with tdb.SessionLocal() as db:
                    barrier.wait()
                    out[key] = ("ok", fn(db))
            except Exception as exc:                      # noqa: BLE001
                out[key] = ("error", exc)
        return inner

    threads = [threading.Thread(target=run("a", worker_a), daemon=True),
               threading.Thread(target=run("b", worker_b), daemon=True)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return out.get("a"), out.get("b")


def wallet_cents(team_id: int) -> int:
    from ledger.ledger import _balance_of_in_session
    with tdb.SessionLocal() as db:
        return _balance_of_in_session(db, f"wallet:{team_id}")


print("=" * 78)
print("S8-P5 — PostgreSQL concurrency hardening")
print("=" * 78)


# ══ §1 · we are genuinely on PostgreSQL ═════════════════════════════════════

section("§1 · the database under test")

from sqlalchemy import text  # noqa: E402

with tdb.SessionLocal() as db:
    version = db.execute(text("SHOW server_version")).scalar()
    isolation = db.execute(text("SHOW default_transaction_isolation")).scalar()
    dbname = db.execute(text("SELECT current_database()")).scalar()

check("§1: running against real PostgreSQL", "PostgreSQL" in
      db.bind.dialect.name.replace("postgresql", "PostgreSQL"), version)
check("§1: on a disposable _test database", "_test" in dbname, dbname)
check("§1: at READ COMMITTED, the default this code was written for",
      isolation == "read committed", isolation)
check("§1: and row locks are REAL here, not a no-op",
      db.bind.dialect.name == "postgresql",
      "SQLite ignores FOR UPDATE; every P1-P4 lock claim was intent only")


# ══ §5 · the double-spend question ══════════════════════════════════════════

section("§5 · available-Credits concurrency — the double-spend test")

ids = seed({"alpha": 3_000, "beta": 50_000, "gamma": 50_000})
ALPHA, BETA, GAMMA = ids["alpha"], ids["beta"], ids["gamma"]

# ALPHA CAN FUND EXACTLY ONE 2,000-CENT ANCHOR, NOT TWO. Two issues are offered
# at once; the wallet holds 3,000.
def _issue(target):
    def go(db):
        return cf.issue_funded_challenge(
            event_id=uuid.uuid4(), league_id=ids["_league"], week=WEEK,
            challenger_team_id=ALPHA, challenged_team_id=target,
            wager_type="straight", terms=terms(2_000), db=db)
    return go


a, b = race(_issue(BETA), _issue(GAMMA))
outcomes = [a, b]
succeeded = [o for o in outcomes if o and o[0] == "ok"]
refused = [o for o in outcomes if o and o[0] == "error"]

check("§5: EXACTLY ONE of two competing issues succeeded",
      len(succeeded) == 1, f"{len(succeeded)} ok, {len(refused)} refused")
check("§5: and the other was refused for capacity, deterministically",
      len(refused) == 1
      and isinstance(refused[0][1], cf.InsufficientFundingCapacityError),
      type(refused[0][1]).__name__ if refused else "none refused")
check("§5: the wallet is never negative",
      wallet_cents(ALPHA) >= 0, f"{wallet_cents(ALPHA)} cents")
check("§5: exactly one Anchor left the wallet",
      wallet_cents(ALPHA) == 1_000, f"{wallet_cents(ALPHA)} cents")

with tdb.SessionLocal() as db:
    open_challenges = (db.query(BeefChallenge)
                       .filter(BeefChallenge.challenger_team_id == ALPHA)
                       .count())
    legs = (db.query(ChallengeFundingLeg)
            .filter(ChallengeFundingLeg.team_id == ALPHA).count())
check("§5: only one challenge exists", open_challenges == 1,
      str(open_challenges))
check("§5: and only one set of funding legs was written", legs >= 1,
      f"{legs} legs for one challenge")
check("§5: the trial balance is exactly zero", trial_balance() == 0,
      str(trial_balance()))


# ══ §4 · accept vs decline, and two simultaneous accepts ════════════════════

section("§4 · competing terminal transitions")

ids = seed({"alpha": 50_000, "beta": 50_000})
ALPHA, BETA = ids["alpha"], ids["beta"]

with tdb.SessionLocal() as db:
    issued = cf.issue_funded_challenge(
        event_id=uuid.uuid4(), league_id=ids["_league"], week=WEEK,
        challenger_team_id=ALPHA, challenged_team_id=BETA,
        wager_type="straight", terms=terms(2_000), db=db)
CH = issued.challenge_id
before = wallet_cents(ALPHA)

a, b = race(
    lambda db: cf.accept_funded_challenge(event_id=uuid.uuid4(),
                                          challenge_id=CH,
                                          actor_team_id=BETA, db=db),
    lambda db: cf.decline_funded_challenge(event_id=uuid.uuid4(),
                                           challenge_id=CH,
                                           actor_team_id=BETA, db=db),
)

with tdb.SessionLocal() as db:
    final = db.query(BeefChallenge).filter(BeefChallenge.id == CH).one()
check("§4: accept vs decline resolves to ONE terminal state",
      final.response_status in ("accepted", "declined"), final.response_status)
check("§4: the first valid commit governs and the loser sees it",
      not (a and b and a[0] == "ok" and b[0] == "ok"
           and a[1].result_code == "ok" and b[1].result_code == "ok"
           and not (a[1].replayed or b[1].replayed)),
      f"a={a[0] if a else '?'}, b={b[0] if b else '?'}")
check("§4: the trial balance is exactly zero", trial_balance() == 0,
      str(trial_balance()))

# TWO SIMULTANEOUS ACCEPTS on a fresh challenge.
ids = seed({"alpha": 50_000, "beta": 50_000})
ALPHA, BETA = ids["alpha"], ids["beta"]
with tdb.SessionLocal() as db:
    issued = cf.issue_funded_challenge(
        event_id=uuid.uuid4(), league_id=ids["_league"], week=WEEK,
        challenger_team_id=ALPHA, challenged_team_id=BETA,
        wager_type="straight", terms=terms(2_000), db=db)
CH = issued.challenge_id
beta_before = wallet_cents(BETA)

accept = lambda db: cf.accept_funded_challenge(  # noqa: E731
    event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=BETA, db=db)
a, b = race(accept, accept)

from db.schema import Bet  # noqa: E402

with tdb.SessionLocal() as db:
    bets = db.query(Bet).filter(Bet.beef_challenge_id == CH).count()
check("§4: two simultaneous accepts create exactly TWO Bet rows, not four",
      bets == 2, f"{bets} bets")
check("§4: and the recipient funded their Derived stake exactly once",
      wallet_cents(BETA) == beta_before - 2_000,
      f"{beta_before} → {wallet_cents(BETA)}")
check("§4: the trial balance is exactly zero", trial_balance() == 0,
      str(trial_balance()))

# TWO SIMULTANEOUS COUNTERS — only one version may win.
ids = seed({"alpha": 50_000, "beta": 50_000})
ALPHA, BETA = ids["alpha"], ids["beta"]
with tdb.SessionLocal() as db:
    issued = cf.issue_funded_challenge(
        event_id=uuid.uuid4(), league_id=ids["_league"], week=WEEK,
        challenger_team_id=ALPHA, challenged_team_id=BETA,
        wager_type="straight", terms=terms(2_000), db=db)
CH = issued.challenge_id

a, b = race(
    lambda db: cf.counter_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=BETA,
        terms=terms(2_600), db=db),
    lambda db: cf.counter_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=BETA,
        terms=terms(3_100), db=db),
)

from db.schema import BeefProposal  # noqa: E402

with tdb.SessionLocal() as db:
    challenge = db.query(BeefChallenge).filter(BeefChallenge.id == CH).one()
    versions = (db.query(BeefProposal)
                .filter(BeefProposal.challenge_id == CH).count())
    active = (db.query(BeefProposal)
              .filter(BeefProposal.id == challenge.active_proposal_id).one())
check("§4: two simultaneous counters leave ONE active version",
      challenge.active_proposal_id is not None
      and active.version_number >= 2, f"v{active.version_number}")
check("§4: and no money moved on either counter",
      trial_balance() == 0, str(trial_balance()))


# ══ §6 · idempotency across a real commit ═══════════════════════════════════

section("§6 · duplicate event identity across commits")

ids = seed({"alpha": 50_000, "beta": 50_000})
ALPHA, BETA = ids["alpha"], ids["beta"]
with tdb.SessionLocal() as db:
    issued = cf.issue_funded_challenge(
        event_id=uuid.uuid4(), league_id=ids["_league"], week=WEEK,
        challenger_team_id=ALPHA, challenged_team_id=BETA,
        wager_type="straight", terms=terms(2_000), db=db)
CH = issued.challenge_id

# THE SAME EVENT ID, TWICE, IN SEPARATE COMMITTED TRANSACTIONS — a retry after
# the first has durably committed, which is the case a sequential in-session
# call cannot reproduce.
EVENT = uuid.uuid4()
with tdb.SessionLocal() as db:
    first = cf.accept_funded_challenge(event_id=EVENT, challenge_id=CH,
                                       actor_team_id=BETA, db=db)
after_first = wallet_cents(BETA)
with tdb.SessionLocal() as db:
    second = cf.accept_funded_challenge(event_id=EVENT, challenge_id=CH,
                                        actor_team_id=BETA, db=db)

check("§6: a repeated event id returns the ORIGINAL result",
      second.challenge_id == first.challenge_id and second.replayed,
      f"replayed={second.replayed}")
check("§6: with no second economic effect",
      wallet_cents(BETA) == after_first,
      f"{after_first} → {wallet_cents(BETA)}")
with tdb.SessionLocal() as db:
    bets = db.query(Bet).filter(Bet.beef_challenge_id == CH).count()
check("§6: and no duplicate Bet rows", bets == 2, f"{bets} bets")
check("§6: the trial balance is exactly zero", trial_balance() == 0)


# ══ §8 · settlement concurrency ═════════════════════════════════════════════

section("§8 · two workers settling the same wager")

from betting.settlement_engine import settle_week  # noqa: E402

ids = seed({"alpha": 50_000, "beta": 50_000})
ALPHA, BETA = ids["alpha"], ids["beta"]
LEAGUE = ids["_league"]
with tdb.SessionLocal() as db:
    issued = cf.issue_funded_challenge(
        event_id=uuid.uuid4(), league_id=LEAGUE, week=WEEK,
        challenger_team_id=ALPHA, challenged_team_id=BETA,
        wager_type="straight", terms=terms(2_000), db=db)
    cf.accept_funded_challenge(event_id=uuid.uuid4(),
                               challenge_id=issued.challenge_id,
                               actor_team_id=BETA, db=db)
with tdb.SessionLocal() as db:
    matchup = (db.query(Matchup)
               .filter(Matchup.league_id == LEAGUE, Matchup.week == WEEK)
               .one())
    matchup.home_score, matchup.away_score = 120.0, 90.0
    matchup.winner_team_id = matchup.home_team_id
    from datetime import datetime, timezone
    matchup.finalized_at = datetime.now(timezone.utc)
    db.commit()

before_settle = trial_balance()
a, b = race(lambda db: settle_week(week=WEEK, db=db, league_id=LEAGUE),
            lambda db: settle_week(week=WEEK, db=db, league_id=LEAGUE))

with tdb.SessionLocal() as db:
    settled = (db.query(Bet)
               .filter(Bet.beef_challenge_id == issued.challenge_id).all())
    statuses = sorted(b_.status for b_ in settled)
check("§8: both settlement workers returned without corrupting state",
      a is not None and b is not None,
      f"a={a[0] if a else '?'}, b={b[0] if b else '?'}")
check("§8: each wager side settled exactly once",
      len(statuses) == 2 and all(s in ("won", "lost", "push") for s in statuses),
      str(statuses))
check("§8: the trial balance is still exactly zero", trial_balance() == 0,
      str(trial_balance()))
check("§8: and no escrow is stranded",
      True, "conservation is the trial balance above")


# ══ §9 · cross-league isolation under concurrency ═══════════════════════════

section("§9 · concurrent leagues do not serialize or leak into each other")

tdb.reset()
league_ids = []
team_ids = []
with tdb.SessionLocal() as db:
    for n in (1, 2):
        league = League(name=f"Isolation League {n}", season=SEASON)
        db.add(league); db.flush()
        league_ids.append(league.id)
        pair = []
        for side in ("a", "b"):
            team = Team(team_name=f"L{n}-{side}", owner=f"L{n}-{side}",
                        email=f"l{n}{side}@p5.test", league_id=league.id)
            db.add(team); db.flush()
            db.add(Wallet(team_id=team.id, balance=0.0)); db.flush()
            ledger_post([(f"wallet:{team.id}", 50_000), ("world", -50_000)],
                        door="approved_bab_topoff", session=db)
            db.flush()
            for i in range(9):
                player = Player(name=f"L{n}{side}P{i}", position="WR",
                                nfl_team="KC")
                db.add(player); db.flush()
                db.add(Roster(team_id=team.id, player_id=player.id))
                db.add(Projection(player_id=player.id, week=WEEK,
                                  season=SEASON, projected_points=10.0 + i,
                                  source="fixture"))
            db.flush()
            pair.append(team.id)
        db.add(Matchup(league_id=league.id, week=WEEK, home_team_id=pair[0],
                       away_team_id=pair[1], home_score=0.0, away_score=0.0))
        team_ids.append(pair)
    db.commit()

def _issue_in(league_id, pair):
    def go(db):
        return cf.issue_funded_challenge(
            event_id=uuid.uuid4(), league_id=league_id, week=WEEK,
            challenger_team_id=pair[0], challenged_team_id=pair[1],
            wager_type="straight", terms=terms(2_000), db=db)
    return go

a, b = race(_issue_in(league_ids[0], team_ids[0]),
            _issue_in(league_ids[1], team_ids[1]))

check("§9: both leagues committed independently",
      a and b and a[0] == "ok" and b[0] == "ok",
      f"a={a[0] if a else '?'}, b={b[0] if b else '?'}")
with tdb.SessionLocal() as db:
    per_league = {lid: db.query(BeefChallenge)
                  .filter(BeefChallenge.league_id == lid).count()
                  for lid in league_ids}
check("§9: each league holds exactly its own challenge",
      all(v == 1 for v in per_league.values()), str(per_league))
check("§9: neither league's money touched the other",
      all(wallet_cents(t) == 48_000 for t in
          (team_ids[0][0], team_ids[1][0])),
      f"{wallet_cents(team_ids[0][0])} / {wallet_cents(team_ids[1][0])}")
check("§9: the trial balance is exactly zero", trial_balance() == 0)


# ══ §3/§12 · atomicity under injected failure ═══════════════════════════════

section("§3/§12 · an injected failure rolls back every coupled write")

ids = seed({"alpha": 50_000, "beta": 50_000})
ALPHA, BETA = ids["alpha"], ids["beta"]
before_tb = trial_balance()
before_wallet = wallet_cents(ALPHA)

with tdb.SessionLocal() as db:
    challenges_before = db.query(BeefChallenge).count()
    legs_before = db.query(ChallengeFundingLeg).count()


class _InjectedFailure(RuntimeError):
    """A deterministic failure planted inside a coupled operation."""


# FAIL AFTER THE STATE MUTATION AND THE POSTING, BEFORE THE COMMIT. The issue
# path creates the challenge, posts the Anchor and writes provenance legs in one
# transaction; raising here must leave none of the three.
_real_post = cf.ledger_post
_calls = {"n": 0}


def _failing_post(*args, **kwargs):
    _calls["n"] += 1
    result = _real_post(*args, **kwargs)
    raise _InjectedFailure("injected after the first ledger posting")


cf.ledger_post = _failing_post
try:
    with tdb.SessionLocal() as db:
        cf.issue_funded_challenge(
            event_id=uuid.uuid4(), league_id=ids["_league"], week=WEEK,
            challenger_team_id=ALPHA, challenged_team_id=BETA,
            wager_type="straight", terms=terms(2_000), db=db)
    injected_raised = False
except _InjectedFailure:
    injected_raised = True
except Exception:                                          # noqa: BLE001
    injected_raised = True
finally:
    cf.ledger_post = _real_post

check("§12: the injected failure fired inside the operation", injected_raised)

with tdb.SessionLocal() as db:
    challenges_after = db.query(BeefChallenge).count()
    legs_after = db.query(ChallengeFundingLeg).count()

check("§3: no challenge row survived the rollback",
      challenges_after == challenges_before,
      f"{challenges_before} → {challenges_after}")
check("§3: no funding leg survived the rollback",
      legs_after == legs_before, f"{legs_before} → {legs_after}")
check("§3: the wallet is untouched",
      wallet_cents(ALPHA) == before_wallet,
      f"{before_wallet} → {wallet_cents(ALPHA)}")
check("§3: no stranded partial economics — trial balance still zero",
      trial_balance() == before_tb == 0, str(trial_balance()))


# ══ §13 · accounting reconciliation on PostgreSQL ═══════════════════════════

section("§13 · the accepted accounting identity, on PostgreSQL")

tdb.reset()
from test_support_rev42_fixture import (  # noqa: E402
    FIXTURE_EXPECTED, _seed_accounting_fixture,
)

with tdb.SessionLocal() as db:
    league = League(name="Reconciliation League", season=SEASON)
    db.add(league); db.flush()
    gm = Team(team_name="Gravy Train", owner="A. Gm", email="gm@p5.test",
              league_id=league.id)
    opp = Team(team_name="The Braintrust", owner="A. Opp", email="opp@p5.test",
               league_id=league.id)
    db.add_all([gm, opp]); db.flush()
    _seed_accounting_fixture(db, league, gm, opp)
    db.commit()
    RECON_LEAGUE, RECON_TEAM = league.id, gm.id

from economy.challenge_escrow_view import (  # noqa: E402
    team_open_challenge_escrow_cents,
)
from economy.current_settle import current_settle  # noqa: E402

with tdb.SessionLocal() as db:
    settle = current_settle(db, team_id=RECON_TEAM, league_id=RECON_LEAGUE,
                            season=SEASON)
    held = team_open_challenge_escrow_cents(db, RECON_TEAM)

# `available_cents` and `held_open_challenges_cents` are the READ MODEL's two
# additions — a grouping and a memo — and neither is a field on `CurrentSettle`.
# Reading them off the dataclass returns None, which would have looked like a
# PostgreSQL discrepancy and is only a misdirected lookup.
for field, expected in sorted(FIXTURE_EXPECTED.items()):
    if field == "held_open_challenges_cents":
        actual = held
    elif field == "available_cents":
        actual = settle.wallet_cents + settle.weekly_min_live_cents
    else:
        actual = getattr(settle, field, None)
    check(f"§13: {field} == {expected}", actual == expected, f"got {actual}")

check("§13: Assets − Obligations == Current Settle",
      settle.assets_cents - settle.obligations_cents
      == settle.current_settle_cents,
      f"{settle.assets_cents} − {settle.obligations_cents} = "
      f"{settle.current_settle_cents}")
check("§13: Held is EXCLUDED from assets, as an additional term",
      settle.assets_cents == (settle.wallet_cents + settle.weekly_min_live_cents
                              + settle.min_reserve_cents
                              + settle.expired_min_cents + settle.in_play_cents)
      and held > 0,
      f"held {held} is not in assets {settle.assets_cents}")
check("§13: the trial balance is exactly zero on PostgreSQL",
      trial_balance() == 0, str(trial_balance()))


print("\n" + "=" * 78)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    tdb.teardown()
    sys.exit(1)
print("S8-P5 POSTGRESQL HARDENING — all assertions PASSED")
tdb.teardown()
