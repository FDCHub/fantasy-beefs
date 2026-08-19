"""D2.4 — the showcase demo repeats, run after run and database after database.

WHAT DETERMINISM HAS TO MEAN HERE. The walkthrough names a leader, a podium and
a Grand Champion. If those move between demonstrations the document is wrong for
everyone after the first viewer, so "deterministic" cannot just mean "no RNG" —
it has to mean the same NUMBERS, from a cold database, every time.

THE RUN, TWICE, ON TWO SEPARATE DATABASES:

    Try Demo  ->  canonical CURRENT  ->  Pain Sanders plays  ->  entry restores
              ->  canonical CURRENT  ->  CURRENT -> FINAL     ->  season close

Both runs are fingerprinted at three points and the fingerprints compared field
by field. Team assignment, rosters, projections, markets, Versus records, pool
wins, standings, Top-Off activity, Championship Scores, podium, Grand Champion
and final balances are all in the digest.

Usage:  python test_d24_determinism.py           (creates its own databases)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))

CAPTURE = r'''
import json, sys
from db.schema import Base, SessionLocal, Team, engine
from demo import reset, showcase, states
from demo.seed import DEMO_USER_EMAIL, find_showcase, seed
from db.schema import PoolInstance, Projection, Roster, User
from ledger.ledger import trial_balance
from reports.standings_read_model import league_standings


def digest(tag):
    from beefs.beef_engine import compute_market_board
    with SessionLocal() as db:
        lg = find_showcase(db)
        teams = sorted(db.query(Team).filter(Team.league_id == lg.id).all(),
                       key=lambda t: t.id)
        ordn = {t.team_name: t.ordinal for t in showcase.TEAMS}
        rows = league_standings(db, league_id=lg.id).overall
        out = {
            "tag": tag,
            "league_id": lg.id,
            "current_week": lg.provider_current_week,
            "season_closed": lg.season_closed_at is not None,
            "team_assignment": [(t.team_name, ordn.get(t.team_name)) for t in teams],
            "rosters": db.query(Roster).count(),
            "projections": db.query(Projection).count(),
            "standings": [(r.team_name, r.versus_wins, r.versus_losses,
                           r.pool_wins, r.versus_net_cents, r.pool_net_cents,
                           r.net_cents) for r in rows],
            "week1_slate": [i.definition_key for i in db.query(PoolInstance)
                            .filter(PoolInstance.league_id == lg.id,
                                    PoolInstance.week == 1)
                            .order_by(PoolInstance.slot).all()],
            "trial_balance": trial_balance(),
        }
        seat = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
        seated = db.query(Team).filter(Team.id == seat.team_id).first()
        out["seat"] = seated.team_name if seated else None

        # Markets are recomputed from the projections, so they belong in the
        # digest: a projection change that moved a line would surface here.
        by_ord = {ordn[t.team_name]: t for t in teams if t.team_name in ordn}
        markets = []
        for home, away, _h, _a in showcase.REGULAR_SCHEDULE[showcase.CURRENT_WEEK]:
            b = compute_market_board(by_ord[home], by_ord[away],
                                     showcase.CURRENT_WEEK, db)
            markets.append((b.anchor_moneyline, float(b.spread_line),
                            float(getattr(b, "total_line", 0) or 0)))
        out["markets_week11"] = markets

        topoff = db.execute(__import__("sqlalchemy").text(
            "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
            "WHERE door LIKE '%topoff%' AND amount_cents > 0")).scalar()
        out["topoff_cents"] = int(topoff)

        from reports.championship_read_model import get_fantasystakes_championship
        snap = get_fantasystakes_championship(db, league_id=lg.id,
                                              season=lg.season)
        if snap is not None:
            names = {t.id: t.team_name for t in teams}
            out["championship"] = [(names[r.team_id], r.place,
                                    r.championship_score_cents)
                                   for r in sorted(snap.rows,
                                                   key=lambda r: (r.place,
                                                                  names[r.team_id]))]
            from reports.grand_champion import (ChampionshipFinish,
                                                calculate_grand_champion)
            ids = {t.team_name: t.id for t in teams}
            ord_name = {t.ordinal: t.team_name for t in showcase.TEAMS}
            yahoo = tuple(ChampionshipFinish(team_id=ids[ord_name[o]], place=i + 1)
                          for i, o in enumerate(showcase.YAHOO_PODIUM_ORDINALS))
            fs = tuple(ChampionshipFinish(team_id=r.team_id, place=r.place)
                       for r in snap.rows)
            gc = calculate_grand_champion(
                yahoo_finishes=yahoo, fantasystakes_finishes=fs,
                fantasystakes_scores={r.team_id: r.championship_score_cents
                                      for r in snap.rows})
            out["grand_champion"] = sorted(names[t] for t in gc.champion_team_ids)
            out["final_balances"] = sorted(
                (names[t.id], int(db.execute(__import__("sqlalchemy").text(
                    "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
                    "WHERE account = :a"), {"a": f"wallet:{t.id}"}).scalar()))
                for t in teams)
        return out


Base.metadata.create_all(engine)
frames = []

seed(force=True)
frames.append(digest("CURRENT"))

# A visitor plays, then entry restores canonical state.
with SessionLocal() as db:
    from beefs.beef_engine import issue_challenge, respond_to_challenge
    lg = find_showcase(db)
    by = {t.team_name: t for t in db.query(Team).filter(Team.league_id == lg.id).all()}
    tm = {t.ordinal: by[t.team_name] for t in showcase.TEAMS}
    opp = next(a if h == 7 else h
               for h, a, _x, _y in showcase.REGULAR_SCHEDULE[showcase.CURRENT_WEEK]
               if 7 in (h, a))
    o = issue_challenge(tm[7].id, tm[opp].id, week=showcase.CURRENT_WEEK,
                        bet_type="straight", amount=5.0, db=db)
    db.flush()
    respond_to_challenge(o.challenge_id, accept=True, db=db)
    db.commit()
reset.ensure_canonical()
frames.append(digest("RESTORED"))

states.advance_to_final()
frames.append(digest("FINAL"))

print("@@DIGEST@@" + json.dumps(frames, sort_keys=True, default=str))
'''


def run(dbname: str):
    import psycopg2

    c = psycopg2.connect(host="127.0.0.1", port=5433, user="postgres",
                         password="postgres", dbname="postgres")
    c.autocommit = True
    cur = c.cursor()
    cur.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
    cur.execute(f'CREATE DATABASE "{dbname}"')
    c.close()

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["DATABASE_URL"] = (
        f"postgresql+psycopg2://postgres:postgres@127.0.0.1:5433/{dbname}")
    # BASE SCHEMA FIRST. The migrations are incremental — they alter and extend
    # tables `Base.metadata` declares — so running them against an empty
    # database fails, and the capture's own create_all would then be missing
    # every migration-only table (`fantasystakes_championship_freeze` among
    # them).
    subprocess.run([sys.executable, "-c",
                    "from db.schema import Base, engine;"
                    " Base.metadata.create_all(engine)"],
                   cwd=REPO, env=env, capture_output=True, timeout=600)
    subprocess.run([sys.executable, "-m", "migrations.run"], cwd=REPO, env=env,
                   capture_output=True, timeout=600)
    p = subprocess.run([sys.executable, "-c", CAPTURE], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=3600,
                       errors="replace")
    for line in (p.stdout or "").splitlines():
        if line.startswith("@@DIGEST@@"):
            return json.loads(line[len("@@DIGEST@@"):])
    print((p.stdout or "")[-3000:])
    print((p.stderr or "")[-3000:])
    raise SystemExit(f"run {dbname} produced no digest")


print("=" * 78)
print("D2.4 — DETERMINISM: the same demo, twice, on two databases")
print("=" * 78)

print("\nrun A ...")
a = run("d24det_a")
print("run B ...")
b = run("d24det_b")

failures = []
for fa, fb in zip(a, b):
    tag = fa["tag"]
    print(f"\n{tag}")
    for key in sorted(set(fa) | set(fb)):
        if key == "tag":
            continue
        va, vb = fa.get(key), fb.get(key)
        if va == vb:
            shown = str(va)
            print(f"  [SAME] {key:<18} {shown[:92]}")
        else:
            failures.append(f"{tag}.{key}")
            print(f"  [DIFF] {key:<18}\n      A={str(va)[:180]}\n      B={str(vb)[:180]}")

print("\n" + "=" * 78)
if failures:
    print(f"D2.4 DETERMINISM: {len(failures)} field(s) DIFFERED")
    for f in failures:
        print(f"   DIFFERED: {f}")
    sys.exit(1)
print("D2.4 DETERMINISM: every canonical output repeated exactly")
