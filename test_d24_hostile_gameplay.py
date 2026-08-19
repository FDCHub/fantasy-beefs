"""D2.4 — hostile gameplay: what the seated public GM still cannot do.

D2 and D2.3 proved the demo cannot REACH a league it did not create. That was a
suite about a read-only demo. The demo is now genuinely mutable — the public
seat can strike a real wager and enter a real pool — so the question changes
from "can it see anything else" to "can it ACT on anything else".

Every attack below is run as the seated public GM (Pain Sanders) against real
production entry points, with a real Yahoo league and a second demo league
sitting in the same database.

REQUIRES POSTGRESQL, for the same reason the lifecycle suite does.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone

_FAILURES: list[str] = []
_PASSES = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _PASSES
    if condition:
        _PASSES += 1
        print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))
    else:
        _FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def section(t):
    print(f"\n{t}")


from sqlalchemy import text

from db.schema import (
    Base, BeefChallenge, League, LeagueCommissioner, SessionLocal, Team, User,
    Wallet, engine,
)
from demo import gameplay, reset, showcase, states
from demo.seed import DEMO_SEAT_ORDINAL, DEMO_USER_EMAIL, find_showcase, seed
from ledger.ledger import trial_balance

DIALECT = engine.dialect.name
NOW = datetime(2026, 12, 30, 12, 0, 0, tzinfo=timezone.utc)

print("=" * 78)
print(f"D2.4 — HOSTILE GAMEPLAY  ({DIALECT})")
print("=" * 78)
if DIALECT != "postgresql":
    print("\nSKIPPED — requires PostgreSQL.")
    raise SystemExit(0)

Base.metadata.create_all(engine)
seed(force=True)

# ── the neighbours the demo must not touch ───────────────────────────────────
with SessionLocal() as db:
    tag = uuid.uuid4().hex[:6]
    yahoo_league = League(season=showcase.SEASON, name="Real Yahoo League",
                          projection_source="fantasypros", provider="yahoo",
                          provider_league_key=f"461.l.{tag}", start_week=1)
    other_demo = League(season=showcase.SEASON, name="Other Demo",
                        projection_source="demo", provider="demo",
                        provider_league_key=f"demo.l.other.{tag}", start_week=1)
    db.add_all([yahoo_league, other_demo])
    db.flush()
    yahoo_team = Team(league_id=yahoo_league.id, team_name="Real Yahoo Team",
                      owner="Real GM", email=f"real.{tag}@example.invalid",
                      provider="yahoo", provider_team_key=f"461.l.{tag}.t.1",
                      provider_team_id="1")
    other_team = Team(league_id=other_demo.id, team_name="Other Demo Team",
                      owner="Other GM", email=f"other.{tag}@example.invalid",
                      provider="demo",
                      provider_team_key=f"demo.l.other.{tag}.t.1",
                      provider_team_id="1")
    db.add_all([yahoo_team, other_team])
    db.flush()
    db.add_all([Wallet(team_id=yahoo_team.id, balance=0),
                Wallet(team_id=other_team.id, balance=0)])
    db.commit()
    YAHOO_LEAGUE_ID, YAHOO_TEAM_ID = yahoo_league.id, yahoo_team.id
    OTHER_LEAGUE_ID, OTHER_TEAM_ID = other_demo.id, other_team.id

with SessionLocal() as db:
    league = find_showcase(db)
    LEAGUE_ID = league.id
    by_name = {t.team_name: t for t in db.query(Team)
               .filter(Team.league_id == LEAGUE_ID).all()}
    ords = {t.ordinal: by_name[t.team_name] for t in showcase.TEAMS}
    PAIN_ID = ords[DEMO_SEAT_ORDINAL].id
    OTHER_SHOWCASE_ID = ords[1].id
    visitor = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
    VISITOR_ID = visitor.id


def refuses(label, fn, *, allow=(Exception,)):
    """Run an attack and assert the product refused it."""
    with SessionLocal() as db:
        try:
            fn(db)
            db.rollback()
            check(label, False, "the action was ACCEPTED")
        except allow as exc:
            db.rollback()
            check(label, True, f"{type(exc).__name__}: {str(exc)[:80]}")


# ══════════════════════════════════════════════════════════════════════════════
section("1 · The seated GM cannot play outside its own league")
# ══════════════════════════════════════════════════════════════════════════════

from beefs.beef_engine import issue_challenge, respond_to_challenge

refuses("cannot challenge a YAHOO league's GM",
        lambda db: issue_challenge(PAIN_ID, YAHOO_TEAM_ID,
                                   week=showcase.CURRENT_WEEK,
                                   bet_type="straight", amount=5.0, db=db))

refuses("cannot challenge ANOTHER demo league's GM",
        lambda db: issue_challenge(PAIN_ID, OTHER_TEAM_ID,
                                   week=showcase.CURRENT_WEEK,
                                   bet_type="straight", amount=5.0, db=db))

refuses("cannot be challenged INTO another league (reversed direction)",
        lambda db: issue_challenge(YAHOO_TEAM_ID, PAIN_ID,
                                   week=showcase.CURRENT_WEEK,
                                   bet_type="straight", amount=5.0, db=db))

# NOTE a FantasyStakes matchup is between any two GMs who are both PLAYING that
# week — not only the two facing each other on the Yahoo card. Challenging a GM
# in a different week-11 fixture is therefore legitimate, and an earlier draft
# of this suite wrongly asserted it was refused. What must be refused is a week
# the teams are not scheduled in at all.
refuses("cannot challenge in a week with no scheduled fixture (postseason)",
        lambda db: issue_challenge(PAIN_ID, OTHER_SHOWCASE_ID,
                                   week=showcase.PLAYOFF_START_WEEK,
                                   bet_type="straight", amount=5.0, db=db))

refuses("cannot stake below the product minimum",
        lambda db: issue_challenge(
            PAIN_ID,
            ords[next(a if h == DEMO_SEAT_ORDINAL else h
                      for h, a, _x, _y
                      in showcase.REGULAR_SCHEDULE[showcase.CURRENT_WEEK]
                      if DEMO_SEAT_ORDINAL in (h, a))].id,
            week=showcase.CURRENT_WEEK, bet_type="straight", amount=0.5,
            db=db))


# ══════════════════════════════════════════════════════════════════════════════
section("2 · The seated GM cannot enter another league's pool")
# ══════════════════════════════════════════════════════════════════════════════

from betting.pool_claims import submit_claim
from db.schema import PoolInstance

with SessionLocal() as db:
    inst = (db.query(PoolInstance)
            .filter(PoolInstance.league_id == LEAGUE_ID,
                    PoolInstance.week == showcase.CURRENT_WEEK,
                    PoolInstance.settled.is_(False))
            .order_by(PoolInstance.slot).first())
    OPEN_INSTANCE_ID = inst.id

refuses("cannot claim a subject from a YAHOO league",
        lambda db: submit_claim(db, pool_instance_id=OPEN_INSTANCE_ID,
                                team_id=PAIN_ID, subject_id=YAHOO_TEAM_ID,
                                replace=True, now=NOW))

refuses("cannot enter a pool ON BEHALF of a Yahoo GM",
        lambda db: submit_claim(db, pool_instance_id=OPEN_INSTANCE_ID,
                                team_id=YAHOO_TEAM_ID, subject_id=PAIN_ID,
                                replace=True, now=NOW))

refuses("cannot enter a pool on behalf of ANOTHER demo league's GM",
        lambda db: submit_claim(db, pool_instance_id=OPEN_INSTANCE_ID,
                                team_id=OTHER_TEAM_ID, subject_id=PAIN_ID,
                                replace=True, now=NOW))


# ══════════════════════════════════════════════════════════════════════════════
section("3 · The public seat holds no authority it was not given")
# ══════════════════════════════════════════════════════════════════════════════

with SessionLocal() as db:
    visitor = db.query(User).filter(User.id == VISITOR_ID).first()
    commissions = {c.league_id for c in db.query(LeagueCommissioner)
                   .filter(LeagueCommissioner.user_id == VISITOR_ID).all()}
    check("the visitor commissions NOTHING — not even the showcase",
          not commissions, str(sorted(commissions)))
    check("  · and specifically not the Yahoo league",
          YAHOO_LEAGUE_ID not in commissions)
    check("  · and specifically not the other demo league",
          OTHER_LEAGUE_ID not in commissions)
    check("the visitor is a plain GM", visitor.role == "gm", str(visitor.role))
    check("the visitor is seated on the showcase team only",
          visitor.team_id == PAIN_ID, str(visitor.team_id))
    grants = db.execute(text(
        "SELECT count(*) FROM provider_grants WHERE user_id = :u"),
        {"u": VISITOR_ID}).scalar()
    check("the visitor holds NO provider grant — demo entry mints none",
          grants == 0, str(grants))
    oauth_states = db.execute(text(
        "SELECT count(*) FROM oauth_states")).scalar() if db.execute(text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'oauth_states'")).scalar() else 0
    check("demo entry created no Yahoo OAuth state", oauth_states == 0,
          str(oauth_states))


# ══════════════════════════════════════════════════════════════════════════════
section("4 · Public entry takes no parameters, so nothing can be chosen")
# ══════════════════════════════════════════════════════════════════════════════

import inspect

from api.demo_routes import enter_showcase_demo

params = set(inspect.signature(enter_showcase_demo).parameters) - {"response",
                                                                   "db"}
check("the entry handler accepts NO caller-supplied parameter — no league, "
      "team, week or state can be named",
      not params, str(sorted(params)))
check("`ensure_canonical` takes no parameters either",
      not inspect.signature(reset.ensure_canonical).parameters)

from fastapi.testclient import TestClient

import api.main as entry

anon = TestClient(entry.app)
for payload in ({"league_id": YAHOO_LEAGUE_ID}, {"team_id": YAHOO_TEAM_ID},
                {"week": 1}, {"state": "final"},
                {"provider_league_key": f"461.l.{tag}"}):
    r = anon.post("/demo/enter", json=payload)
    body = r.json() if r.status_code == 200 else {}
    check(f"POST /demo/enter ignores {list(payload)[0]!r}",
          r.status_code == 200 and body.get("league_id") == LEAGUE_ID,
          f"{r.status_code} -> league {body.get('league_id')}")


# ══════════════════════════════════════════════════════════════════════════════
section("5 · Reset and the FINAL transition cannot touch the neighbours")
# ══════════════════════════════════════════════════════════════════════════════

def neighbour_state(db):
    return {
        "yahoo_league": (db.query(League)
                         .filter(League.id == YAHOO_LEAGUE_ID).first()
                         .provider_league_key),
        "yahoo_closed": (db.query(League)
                         .filter(League.id == YAHOO_LEAGUE_ID).first()
                         .season_closed_at),
        "other_league": (db.query(League)
                         .filter(League.id == OTHER_LEAGUE_ID).first()
                         .provider_league_key),
        "yahoo_ledger": db.execute(text(
            "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
            "WHERE account LIKE :a"), {"a": f"wallet:{YAHOO_TEAM_ID}"}).scalar(),
        "other_ledger": db.execute(text(
            "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
            "WHERE account LIKE :a"), {"a": f"wallet:{OTHER_TEAM_ID}"}).scalar(),
        "schedule_rows": db.execute(text(
            "SELECT count(*) FROM nfl_schedule")).scalar(),
        "commissioners": db.execute(text(
            "SELECT count(*) FROM league_commissioners WHERE league_id IN "
            "(:a, :b)"), {"a": YAHOO_LEAGUE_ID, "b": OTHER_LEAGUE_ID}).scalar(),
    }


with SessionLocal() as db:
    BEFORE = neighbour_state(db)

# a visitor plays, entry restores, then the season is advanced and closed
with SessionLocal() as db:
    opp = next(a if h == DEMO_SEAT_ORDINAL else h
               for h, a, _x, _y in showcase.REGULAR_SCHEDULE[showcase.CURRENT_WEEK]
               if DEMO_SEAT_ORDINAL in (h, a))
    o = issue_challenge(PAIN_ID, ords[opp].id, week=showcase.CURRENT_WEEK,
                        bet_type="straight", amount=5.0, db=db)
    db.flush()
    respond_to_challenge(o.challenge_id, accept=True, db=db)
    db.commit()
reset.ensure_canonical()
states.advance_to_final()

with SessionLocal() as db:
    AFTER = neighbour_state(db)

for key in sorted(BEFORE):
    check(f"unchanged through play, restore and season close: {key}",
          BEFORE[key] == AFTER[key], f"{BEFORE[key]!r} -> {AFTER[key]!r}")

with SessionLocal() as db:
    check("the Yahoo league is still NOT closed",
          db.query(League).filter(League.id == YAHOO_LEAGUE_ID)
          .first().season_closed_at is None)
    check("the showcase IS closed — the close reached only its own league",
          find_showcase(db).season_closed_at is not None)
check("the ledger balances after every attack", trial_balance() == 0,
      str(trial_balance()))


print("\n" + "=" * 78)
if _FAILURES:
    print(f"D2.4 HOSTILE GAMEPLAY: {_PASSES} passed, {len(_FAILURES)} FAILED")
    for f in _FAILURES:
        print(f"   FAILED: {f}")
    sys.exit(1)
print(f"D2.4 HOSTILE GAMEPLAY: all {_PASSES} attacks refused")
