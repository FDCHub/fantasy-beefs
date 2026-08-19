"""D2.5.1 — public demo entry under concurrent visitors.

THE BLOCKER THIS OWNS. D2.5 fired four simultaneous `POST /demo/enter` at a
mutated showcase and got:

    [500, 500, 500, 200]
    StaleDataError: UPDATE statement on table 'beef_challenges'
                    expected to update 1 row(s); 0 were matched.

Three of four visitors raced inside `restore_in_place`: each read the same
surplus challenges and whichever committed first deleted the rows the others
still held. The demo's only entry point failed for most simultaneous visitors.

WHAT IS ASSERTED. Not merely "no 500" — that could be bought by swallowing the
error and serving a broken league. The whole canonical state has to survive the
race: one league id, the same pool slate, the same standings, the fingerprint
restored, the visitor seated as Pain Sanders, and a balanced ledger.

NEIGHBOURS ARE PRESENT THROUGHOUT. A Yahoo league, an unrelated demo league and
a retired showcase sit in the same database, and the global `nfl_schedule` is
fingerprinted, so the lock cannot be shown "safe" by being broad.

REPEATED, because a race that only sometimes loses is still a race. Requires
PostgreSQL: the serialization is a `pg_advisory_lock`, and the lifecycle needs
`SELECT ... FOR UPDATE` regardless.
"""
from __future__ import annotations

import sys
import threading
import uuid

_FAILURES: list[str] = []
_PASSES = 0

ROUNDS = 3
CONCURRENCY = 6


def check(label: str, condition: bool, detail: str = "") -> None:
    global _PASSES
    if condition:
        _PASSES += 1
        print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))
    else:
        _FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


from fastapi.testclient import TestClient
from sqlalchemy import text

import api.main as entry
from db.schema import (
    Base, BeefChallenge, League, PoolInstance, SessionLocal, Team, User,
    Wallet, engine,
)
from demo import reset, showcase
from demo.seed import DEMO_SEAT_ORDINAL, DEMO_USER_EMAIL, find_showcase, seed
from ledger.ledger import trial_balance
from reports.standings_read_model import league_standings

DIALECT = engine.dialect.name
print("=" * 78)
print(f"D2.5.1 — CONCURRENT PUBLIC ENTRY  ({DIALECT})")
print("=" * 78)
if DIALECT != "postgresql":
    print("\nSKIPPED — the serialization is a PostgreSQL advisory lock and the "
          "lifecycle requires PostgreSQL.")
    raise SystemExit(0)

Base.metadata.create_all(engine)
seed(force=True)


# ── neighbours that must be untouched ────────────────────────────────────────

with SessionLocal() as db:
    tag = uuid.uuid4().hex[:6]
    yahoo = League(season=showcase.SEASON, name="Real Yahoo League",
                   projection_source="fantasypros", provider="yahoo",
                   provider_league_key=f"461.l.{tag}", start_week=1)
    other = League(season=showcase.SEASON, name="Other Demo",
                   projection_source="demo", provider="demo",
                   provider_league_key=f"demo.l.other.{tag}", start_week=1)
    retired = League(season=showcase.SEASON, name="Old Showcase (retired)",
                     projection_source="demo", provider="demo",
                     provider_league_key=f"demo.l.retired.{tag}.9", start_week=1)
    db.add_all([yahoo, other, retired])
    db.flush()
    for lg in (yahoo, other, retired):
        t = Team(league_id=lg.id, team_name=f"{lg.name} T1", owner="GM",
                 email=f"{lg.id}.{tag}@example.invalid", provider=lg.provider,
                 provider_team_key=f"{lg.provider_league_key}.t.1",
                 provider_team_id="1")
        db.add(t)
        db.flush()
        db.add(Wallet(team_id=t.id, balance=0))
    db.add(__import__("db.schema", fromlist=["NflSchedule"]).NflSchedule(
        season=2099, week=1, home_team="AAA", away_team="BBB",
        kickoff_utc=showcase.OBSERVED_AT))
    db.commit()
    NEIGHBOUR_IDS = [yahoo.id, other.id, retired.id]


def neighbour_fingerprint(db):
    rows = db.execute(text(
        "SELECT id, name, provider, provider_league_key, season_closed_at "
        "FROM leagues WHERE id = ANY(:ids) ORDER BY id"),
        {"ids": NEIGHBOUR_IDS}).fetchall()
    sched = db.execute(text(
        "SELECT count(*), COALESCE(SUM(week),0) FROM nfl_schedule")).fetchone()
    ledger = db.execute(text(
        "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries le "
        "JOIN teams t ON ('wallet:' || t.id) = le.account "
        "WHERE t.league_id = ANY(:ids)"), {"ids": NEIGHBOUR_IDS}).scalar()
    return {"leagues": [tuple(map(str, r)) for r in rows],
            "nfl_schedule": tuple(sched), "neighbour_ledger": int(ledger or 0)}


def canonical_snapshot(db):
    lg = find_showcase(db)
    return {
        "league_id": lg.id,
        "fingerprint": reset.canonical_fingerprint(db, lg),
        "slate": [i.definition_key for i in db.query(PoolInstance)
                  .filter(PoolInstance.league_id == lg.id,
                          PoolInstance.week == 1)
                  .order_by(PoolInstance.slot).all()],
        "standings": [(r.team_name, r.net_cents, r.pool_wins, r.versus_wins,
                       r.versus_losses) for r in
                      league_standings(db, league_id=lg.id).overall],
    }


with SessionLocal() as db:
    BASE = canonical_snapshot(db)
    NEIGHBOURS = neighbour_fingerprint(db)
    check("baseline showcase is canonical CURRENT",
          reset.is_canonical(db, find_showcase(db)),
          f"league {BASE['league_id']}")

client = TestClient(entry.app, raise_server_exceptions=False)


def mutate():
    """A real visitor action: strike and accept a live-week challenge."""
    from beefs.beef_engine import issue_challenge, respond_to_challenge

    with SessionLocal() as db:
        lg = find_showcase(db)
        by = {t.team_name: t for t in db.query(Team)
              .filter(Team.league_id == lg.id).all()}
        tm = {t.ordinal: by[t.team_name] for t in showcase.TEAMS}
        opp = next(a if h == DEMO_SEAT_ORDINAL else h
                   for h, a, _x, _y
                   in showcase.REGULAR_SCHEDULE[showcase.CURRENT_WEEK]
                   if DEMO_SEAT_ORDINAL in (h, a))
        o = issue_challenge(tm[DEMO_SEAT_ORDINAL].id, tm[opp].id,
                            week=showcase.CURRENT_WEEK, bet_type="straight",
                            amount=5.0, db=db)
        db.flush()
        respond_to_challenge(o.challenge_id, accept=True, db=db)
        db.commit()


for rnd in range(1, ROUNDS + 1):
    print(f"\nRound {rnd} · {CONCURRENCY} simultaneous visitors on a mutated "
          f"showcase")

    mutate()
    with SessionLocal() as db:
        check(f"  round {rnd}: the mutation really made it non-canonical",
              not reset.is_canonical(db, find_showcase(db)))

    barrier = threading.Barrier(CONCURRENCY)
    results: list = []

    def hit():
        # Release every thread at the same instant — a staggered start would
        # not exercise the race the blocker described.
        barrier.wait()
        try:
            r = client.post("/demo/enter")
            results.append((r.status_code, r.json()))
        except Exception as exc:                      # pragma: no cover
            results.append((f"EXC {type(exc).__name__}", {}))

    threads = [threading.Thread(target=hit) for _ in range(CONCURRENCY)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    codes = [c for c, _ in results]
    check(f"  round {rnd}: NO request returned 500",
          not [c for c in codes if c == 500], str(codes))
    check(f"  round {rnd}: every request returned 200",
          all(c == 200 for c in codes), str(codes))
    league_ids = {b.get("league_id") for _, b in results if isinstance(b, dict)}
    check(f"  round {rnd}: every visitor got the SAME league",
          league_ids == {BASE["league_id"]}, str(league_ids))

    with SessionLocal() as db:
        after = canonical_snapshot(db)
        check(f"  round {rnd}: canonical fingerprint restored",
              after["fingerprint"] == BASE["fingerprint"],
              str({k: v for k, v in after["fingerprint"].items()
                   if BASE["fingerprint"].get(k) != v}))
        check(f"  round {rnd}: the league id is unchanged",
              after["league_id"] == BASE["league_id"],
              f"{BASE['league_id']} -> {after['league_id']}")
        check(f"  round {rnd}: the pool slate is unchanged",
              after["slate"] == BASE["slate"])
        check(f"  round {rnd}: the standings are unchanged",
              after["standings"] == BASE["standings"])
        check(f"  round {rnd}: exactly ONE active showcase exists",
              db.query(League).filter(
                  League.provider_league_key.like("demo.l.showcase.%")).count()
              == 1)
        visitor = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
        seat = db.query(Team).filter(Team.id == visitor.team_id).first()
        check(f"  round {rnd}: the seat is Pain Sanders, in this league",
              seat.team_name == "Pain Sanders"
              and seat.league_id == after["league_id"], seat.team_name)
        check(f"  round {rnd}: trial balance is zero", trial_balance() == 0,
              str(trial_balance()))
        check(f"  round {rnd}: neighbours and nfl_schedule unchanged",
              neighbour_fingerprint(db) == NEIGHBOURS)


print("\nAfter the rounds")
with SessionLocal() as db:
    check("an untouched league is still left alone",
          reset.ensure_canonical()["action"] == "none")
    check("the showcase is canonical", reset.is_canonical(db, find_showcase(db)))
    check("neighbours survived every round",
          neighbour_fingerprint(db) == NEIGHBOURS)
    check("final trial balance is zero", trial_balance() == 0)

print("\n" + "=" * 78)
if _FAILURES:
    print(f"D2.5.1 CONCURRENT ENTRY: {_PASSES} passed, {len(_FAILURES)} FAILED")
    for f in _FAILURES:
        print(f"   FAILED: {f}")
    sys.exit(1)
print(f"D2.5.1 CONCURRENT ENTRY: all {_PASSES} assertions PASSED "
      f"({ROUNDS} rounds x {CONCURRENCY} simultaneous visitors)")
