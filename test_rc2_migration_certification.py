#!/usr/bin/env python3
"""RC2 migration certification — both lifecycles, proved separately.

WHY THIS EXISTS. RC2 CI ran `python -m migrations.run` against a DATABASE_URL
pointing at a SQLite path that did not exist. SQLite creates an empty file on
connect, `ensure_table` added `schema_migrations`, and `0001_yahoo_identity` then
reflected `users` — a table no migration builds — and raised NoSuchTableError.
That was the harness asserting a lifecycle the product does not have, not a
defect in the migrations. There are exactly TWO supported lifecycles and this
suite drives both:

  A. FRESH DATABASE — the application startup hook builds the whole schema from
     the registered SQLAlchemy models, creates the ledger table (which lives on a
     separate declarative base), then STAMPS the ACTIVE manifest, because
     `create_all` produced everything those migrations add. No migration runs.

  B. EXISTING DATABASE — `python -m migrations.run`, once, explicitly, before the
     release. Migrations carry an existing database forward; they never
     construct one.

Running B's command against a database that has had neither lifecycle applied is
the one thing that cannot work, and it is what CI was doing.

THE RC1 BASELINE IS REAL, NOT SIMULATED. Part B builds its "before" database by
checking out the immutable RC1 baseline commit into a temporary git worktree and
running RC1'S OWN models and RC1's own bootstrap against it. An empty file, or a
current-tree schema with the RC2 tables omitted by hand, would be this suite
asserting its own assumption about what RC1 looked like.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _REPO)

RC1_COMMIT = "c46915979cb9239c362079bff27112393d144cf7"

#: Tables RC2 adds. Every one is created by migrations 0003-0005 on an existing
#: database, and by `create_all` from the registered models on a fresh one.
RC2_SNAPSHOT_TABLES = ("fantasystakes_championship_freeze",
                       "fantasystakes_championship_score")
RC2_ECONOMY_TABLES = ("fantasystakes_championship_config",
                      "fantasystakes_championship_allocation")
RC2_DISTRIBUTION_TABLES = ("fantasystakes_championship_distribution_run",)
RC2_TABLES = RC2_SNAPSHOT_TABLES + RC2_ECONOMY_TABLES + RC2_DISTRIBUTION_TABLES

FAIL: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


def run_python(code: str, *, cwd: str, db_url: str, extra_env: dict | None = None):
    """Run a snippet in a SEPARATE interpreter rooted at `cwd`.

    Part B needs RC1's modules and RC2's modules in the same test run. They share
    module names, so they cannot share an interpreter — the first import wins and
    the second silently gets the wrong code. A subprocess per tree is what makes
    the two halves genuinely different code.
    """
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    env["PYTHONPATH"] = cwd
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("TEST_DATABASE_URL", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, "-c", code], cwd=cwd, env=env,
                          capture_output=True, text=True)


def sqlite_url(path: str) -> str:
    return "sqlite:///" + path.replace("\\", "/")


def inspect_db(db_url: str) -> dict:
    """Tables and migration records, read with the CURRENT tree's SQLAlchemy."""
    code = r"""
import json, os
from sqlalchemy import create_engine, inspect, text
eng = create_engine(os.environ["DATABASE_URL"])
insp = inspect(eng)
tables = sorted(insp.get_table_names())
records = []
if "schema_migrations" in tables:
    with eng.connect() as c:
        records = sorted(r[0] for r in c.execute(text(
            "SELECT identifier FROM schema_migrations")).fetchall())
print("@@" + json.dumps({"tables": tables, "records": records}))
"""
    proc = run_python(code, cwd=_REPO, db_url=db_url)
    line = [l for l in proc.stdout.splitlines() if l.startswith("@@")]
    if not line:
        raise AssertionError(f"inspect failed: {proc.stdout}\n{proc.stderr}")
    return json.loads(line[0][2:])


def migrations_run(db_url: str, *args: str):
    code = ("import sys\n"
            "from migrations.run import main\n"
            f"sys.exit(main({list(args)!r}))\n")
    return run_python(code, cwd=_REPO, db_url=db_url)


# ═════════════════════════════════════════════════════════════════════════════
# A · FRESH DATABASE — the real application startup hook
# ═════════════════════════════════════════════════════════════════════════════
print("\nRC2-MIG-A · fresh database bootstrap via the real RC2 startup hook")

_tmp_a = tempfile.mkdtemp()
db_a = os.path.join(_tmp_a, "fresh.db")
url_a = sqlite_url(db_a)

# TestClient's context manager fires FastAPI's startup events, so this drives
# `api.main._create_tables` exactly as `uvicorn api.main_rc2:app` does — the
# entrypoint the Procfile actually runs. Nothing here reimplements bootstrap.
BOOT = r"""
from fastapi.testclient import TestClient
import api.main_rc2 as rc2
with TestClient(rc2.app):
    pass
print("BOOTED")
"""

check("a fresh deployment starts from no database at all",
      not os.path.exists(db_a), db_a)

boot1 = run_python(BOOT, cwd=_REPO, db_url=url_a)
check("RC2 application startup completes on an empty database",
      boot1.returncode == 0 and "BOOTED" in boot1.stdout,
      (boot1.stderr or boot1.stdout)[-400:])

state_a = inspect_db(url_a)
check("startup created the ledger table (separate declarative base)",
      "ledger_entries" in state_a["tables"])
check("startup created the RC2 championship snapshot tables",
      all(t in state_a["tables"] for t in RC2_SNAPSHOT_TABLES),
      str([t for t in RC2_SNAPSHOT_TABLES if t not in state_a["tables"]]))
check("startup created the RC2 championship economy tables",
      all(t in state_a["tables"] for t in RC2_ECONOMY_TABLES),
      str([t for t in RC2_ECONOMY_TABLES if t not in state_a["tables"]]))
check("startup created the RC2 championship distribution table",
      all(t in state_a["tables"] for t in RC2_DISTRIBUTION_TABLES),
      str([t for t in RC2_DISTRIBUTION_TABLES if t not in state_a["tables"]]))

from migrations.manifest import ACTIVE  # noqa: E402

ACTIVE_IDS = [m.identifier for m in ACTIVE]
check("a fresh database is stamped with the whole ACTIVE manifest",
      state_a["records"] == sorted(ACTIVE_IDS), str(state_a["records"]))

status_a = migrations_run(url_a, "--status")
check("status reports zero pending on a fresh database",
      status_a.returncode == 0 and "pending       : none" in status_a.stdout,
      status_a.stdout.strip().replace("\n", " | "))

# A fresh database must not need `migrations.run` at all — but running it must be
# a safe no-op, because an operator or a deploy pipeline may run it anyway.
noop_a = migrations_run(url_a)
check("migrations.run is a clean no-op on a freshly bootstrapped database",
      noop_a.returncode == 0 and "nothing pending" in noop_a.stdout,
      (noop_a.stdout + noop_a.stderr).strip()[-200:])

boot2 = run_python(BOOT, cwd=_REPO, db_url=url_a)
state_a2 = inspect_db(url_a)
check("a second startup succeeds", boot2.returncode == 0,
      (boot2.stderr or "")[-300:])
check("a second startup changes no schema",
      state_a2["tables"] == state_a["tables"],
      str(set(state_a2["tables"]) ^ set(state_a["tables"])))
check("a second startup creates no duplicate migration records",
      state_a2["records"] == state_a["records"], str(state_a2["records"]))


# ═════════════════════════════════════════════════════════════════════════════
# B · EXISTING RC1 DATABASE → RC2
# ═════════════════════════════════════════════════════════════════════════════
print("\nRC2-MIG-B · existing RC1 database upgraded to RC2")

_tmp_b = tempfile.mkdtemp()
rc1_tree = os.path.join(_tmp_b, "rc1")


def _cleanup() -> None:
    """Always give the worktree back, including on a crash.

    Registered with atexit rather than written at the end of the script: an
    assertion that raises partway through Part B would otherwise leave a
    registered worktree behind for every run.
    """
    subprocess.run(["git", "worktree", "remove", "--force", rc1_tree],
                   cwd=_REPO, capture_output=True, text=True)
    subprocess.run(["git", "worktree", "prune"], cwd=_REPO,
                   capture_output=True, text=True)
    for directory in (_tmp_a, _tmp_b):
        shutil.rmtree(directory, ignore_errors=True)


atexit.register(_cleanup)

have = subprocess.run(["git", "cat-file", "-e", RC1_COMMIT + "^{commit}"],
                      cwd=_REPO, capture_output=True, text=True)
if have.returncode != 0:
    print(f"  [FAIL] RC1 baseline {RC1_COMMIT[:12]} is not present in this clone.")
    print("         The RC1->RC2 upgrade path cannot be certified against a "
          "simulated baseline.")
    print("         CI must check out with `fetch-depth: 0`.")
    FAIL.append("RC1 baseline commit unavailable")
    rc1_available = False
else:
    rc1_available = True
    subprocess.run(["git", "worktree", "add", "--detach", rc1_tree, RC1_COMMIT],
                   cwd=_REPO, capture_output=True, text=True, check=True)

# Seed a realistic RC1 production database using RC1'S OWN models: users with the
# Yahoo identity columns, a league, teams, wallets, a frozen economy config, the
# base Season-Opening Allocation rows AND their real three-leg ledger postings.
RC1_SEED = r"""
from datetime import datetime, timezone
from db.schema import (Base, League, LeagueSeasonEconomyConfig, SeasonAllocation,
                       SessionLocal, Team, User, Wallet, engine)
from ledger.ledger import create_ledger_table, post as ledger_post, trial_balance
from ledger.ledger import SEASON_ALLOCATION_DOOR

# This is the RC1 fresh-deployment bootstrap, run with RC1's models.
Base.metadata.create_all(engine)
create_ledger_table()

SEASON = 2026
with SessionLocal() as db:
    lg = League(season=SEASON, name="RC1 Production League",
                projection_source="fantasypros", start_week=1,
                playoff_start_week=15, season_final_week=17,
                provider_current_week=9)
    db.add(lg); db.flush()
    for i in range(4):
        t = Team(league_id=lg.id, team_name=f"RC1 Team {i+1}",
                 owner=f"Owner {i+1}", email=f"rc1-{i+1}@example.test")
        db.add(t); db.flush()
        db.add(Wallet(team_id=t.id, balance=0.0))
        db.add(User(email=f"gm-{i+1}@example.test", hashed_password=None,
                    auth_provider="yahoo", provider_subject=f"yahoo-subject-{i+1}",
                    team_id=t.id, role="gm", is_active=1))
        db.add(SeasonAllocation(league_id=lg.id, team_id=t.id, season=SEASON,
                                buyin_cents=22000, min_reserve_cents=14000,
                                reserve_cents=8000))
        ledger_post([(f"season_issuance:{lg.id}:{SEASON}", -22000),
                     (f"min_reserve:{t.id}", 14000),
                     (f"reserve:{t.id}", 8000)],
                    door=SEASON_ALLOCATION_DOOR, session=db)
    db.add(LeagueSeasonEconomyConfig(
        league_id=lg.id, season=SEASON, weekly_bet_minimum_cents=1000,
        championship_contribution_cents=8000, skunk_fee_cents=1000,
        regular_season_week_count=14, active_team_count=4, start_week_used=1,
        playoff_start_week_used=15, frozen_at=datetime.now(timezone.utc)))
    db.commit()
assert trial_balance() == 0, "RC1 seed did not balance"
print("RC1_SEEDED")
"""

RC1_STAMP = r"""
from db.schema import engine
from migrations.run import stamp_all
print("RC1_STAMPED:" + ",".join(stamp_all(engine)))
"""

# The two shapes an RC1 database can genuinely be in:
#   stamped — bootstrapped by RC1 startup, which stamps RC1's ACTIVE manifest
#   legacy  — predates the manifest entirely, so it has no schema_migrations
VARIANTS = (
    ("stamped RC1 production database", True),
    ("legacy RC1 database with no migration history", False),
)

for variant_name, stamped in VARIANTS if rc1_available else ():
    print("")
    print(f"  -- {variant_name} --")
    db_b = os.path.join(_tmp_b, f"rc1-{'stamped' if stamped else 'legacy'}.db")
    url_b = sqlite_url(db_b)

    seed = run_python(RC1_SEED, cwd=rc1_tree, db_url=url_b)
    check("RC1 baseline schema and data build from RC1's own models",
          seed.returncode == 0 and "RC1_SEEDED" in seed.stdout,
          (seed.stderr or seed.stdout)[-400:])
    if stamped:
        st = run_python(RC1_STAMP, cwd=rc1_tree, db_url=url_b)
        check("RC1 startup stamped RC1's own ACTIVE manifest",
              st.returncode == 0 and "RC1_STAMPED:" in st.stdout,
              (st.stderr or st.stdout)[-300:])

    before = inspect_db(url_b)
    check("the RC1 baseline genuinely lacks every RC2 table",
          not any(t in before["tables"] for t in RC2_TABLES),
          str([t for t in RC2_TABLES if t in before["tables"]]))
    check("the RC1 baseline is a real schema, not an empty file",
          "users" in before["tables"] and "leagues" in before["tables"]
          and "ledger_entries" in before["tables"]
          and len(before["tables"]) > 20, str(len(before["tables"])))
    check("RC1 migration history matches the variant under test",
          before["records"] == (["0001_yahoo_identity", "0002_provider_grants"]
                                if stamped else []), str(before["records"]))

    # THE UPGRADE — RC2's code, RC2's manifest, one explicit command.
    dry = migrations_run(url_b, "--dry-run")
    check("dry-run reports the pending work and applies nothing",
          dry.returncode == 0 and "WOULD APPLY" in dry.stdout
          and inspect_db(url_b)["records"] == before["records"],
          dry.stdout.strip().replace("\n", " | ")[-220:])

    up = migrations_run(url_b)
    check("RC1 -> RC2 upgrade succeeds",
          up.returncode == 0 and "migrations complete." in up.stdout,
          (up.stdout + up.stderr).strip()[-400:])

    after = inspect_db(url_b)
    check("RC2 championship snapshot tables exist after upgrade",
          all(t in after["tables"] for t in RC2_SNAPSHOT_TABLES),
          str([t for t in RC2_SNAPSHOT_TABLES if t not in after["tables"]]))
    check("RC2 championship economy tables exist after upgrade",
          all(t in after["tables"] for t in RC2_ECONOMY_TABLES),
          str([t for t in RC2_ECONOMY_TABLES if t not in after["tables"]]))
    check("RC2 championship distribution table exists after upgrade",
          all(t in after["tables"] for t in RC2_DISTRIBUTION_TABLES),
          str([t for t in RC2_DISTRIBUTION_TABLES if t not in after["tables"]]))
    check("the upgrade dropped no RC1 table",
          set(before["tables"]) <= set(after["tables"]),
          str(sorted(set(before["tables"]) - set(after["tables"]))))
    check("migration records are complete after upgrade",
          after["records"] == sorted(ACTIVE_IDS), str(after["records"]))

    # RC1 data and money must survive untouched.
    VERIFY = r"""
from db.schema import SessionLocal, SeasonAllocation, Team, User, League
from ledger.ledger import balance_of, trial_balance
with SessionLocal() as db:
    allocs = db.query(SeasonAllocation).order_by(SeasonAllocation.team_id).all()
    teams = db.query(Team).count()
    users = db.query(User).count()
    leagues = db.query(League).count()
    lg = db.query(League).first()
print("@@" + repr({
    "allocs": [(a.team_id, a.buyin_cents, a.min_reserve_cents, a.reserve_cents)
               for a in allocs],
    "teams": teams, "users": users, "leagues": leagues,
    "issuance": balance_of(f"season_issuance:{lg.id}:2026"),
    "reserves": [balance_of(f"reserve:{a.team_id}") for a in allocs],
    "trial": trial_balance(),
}))
"""
    ver = run_python(VERIFY, cwd=_REPO, db_url=url_b)
    payload = [l for l in ver.stdout.splitlines() if l.startswith("@@")]
    data = eval(payload[0][2:]) if payload else {}  # noqa: S307 - our own repr
    check("RC1 rows are readable by RC2 code and unchanged",
          data.get("teams") == 4 and data.get("users") == 4
          and data.get("leagues") == 1
          and data.get("allocs") == [(i, 22000, 14000, 8000) for i in
                                     sorted(t for t, *_ in data.get("allocs", []))],
          str(data.get("allocs")) + (ver.stderr[-200:] if ver.stderr else ""))
    check("RC1 posted money is untouched by the upgrade",
          data.get("issuance") == -88000
          and data.get("reserves") == [8000, 8000, 8000, 8000],
          f"issuance={data.get('issuance')} reserves={data.get('reserves')}")
    check("trial balance remains exactly zero after upgrade",
          data.get("trial") == 0, str(data.get("trial")))

    # Replay.
    again = migrations_run(url_b)
    replay = inspect_db(url_b)
    check("a second migration run is idempotent",
          again.returncode == 0 and "nothing pending" in again.stdout,
          (again.stdout + again.stderr).strip()[-200:])
    check("replay creates no duplicate migration records and no schema drift",
          replay["records"] == after["records"]
          and replay["tables"] == after["tables"],
          str(replay["records"]))

    status_b = migrations_run(url_b, "--status")
    check("status reports zero pending after upgrade",
          status_b.returncode == 0 and "pending       : none" in status_b.stdout,
          status_b.stdout.strip().replace("\n", " | "))

print(f"\n{'=' * 64}")
if FAIL:
    print(f"FAILED: {len(FAIL)} assertion(s)")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("PASS: RC2 migration certification — fresh bootstrap and RC1->RC2 upgrade")
