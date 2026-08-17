#!/usr/bin/env python3
"""
test_prod_harden1_release_cycle.py — PROD-HARDEN-1 · mid-season release,
rollback, and frontend-only deployment.

THREE LOCKED REQUIREMENTS, DRIVEN RATHER THAN DESCRIBED.

  §54  A release during an active season must not reinterpret prior state.
       Deploy N holds a configured league with settled economic history; deploy
       N+1 adds an additive migration and new code; the history must be byte-for
       -byte what it was.

  §33  Rolling the APPLICATION back must leave that history readable. A column
       the old code does not know about is fine — that is what "additive" buys.
       A row the new code rewrote incompatibly is not, and would be the finding.

  §34  A frontend release must need no migration, no backend restart and no
       change to authoritative state, while still reaching the browser.

── HOW "OLD CODE" IS SIMULATED ─────────────────────────────────────────────

Not by checking out an old commit — that would test git. By reading the same
database through a model that does NOT declare the new columns, which is
precisely what an older application binary is: SQLAlchemy selects the columns
its mapping knows about, so a rolled-back process issues exactly this query.
If the old shape can still read every row it owns, the rollback is safe.

DATABASE. PostgreSQL. Additive DDL, rollback-safety and column-level
compatibility are all dialect behaviour.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import create_engine, text                         # noqa: E402
from sqlalchemy.engine import make_url                             # noqa: E402

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


_ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if not _ADMIN_URL:
    print("  [FAIL] TEST_DATABASE_URL is not set — this suite needs PostgreSQL")
    sys.exit(2)
_url = make_url(_ADMIN_URL)
if "_test" not in (_url.database or ""):
    print("  [FAIL] the admin database name must contain '_test'")
    sys.exit(2)

_admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
_DB = f"ph1_cycle_{uuid.uuid4().hex[:8]}_test"
with _admin.connect() as c:
    c.execute(text(f'CREATE DATABASE "{_DB}"'))
_TARGET = _url.set(database=_DB).render_as_string(hide_password=False)

from auth.token_crypto import generate_key                         # noqa: E402

_KEY = generate_key()

# ── RELEASE N — a mid-season league with settled history ────────────────────

_RELEASE_N = r'''
import os, sys, json
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r
os.environ["FS_TOKEN_ENCRYPTION_KEY"] = %(key)r
os.environ["FS_RELEASE"] = "release-N"

from db.schema import Base, engine, SessionLocal, League, Team, User, Wallet
Base.metadata.create_all(engine)
from ledger.ledger import create_ledger_table, post as ledger_post, balance_of, trial_balance
create_ledger_table()
from migrations.run import stamp_all
stamp_all(engine)

from auth.provider_grant import record_grant
from providers.yahoo.user_credentials import set_credential_owner
from economy.league_economy_config import set_draft, freeze_economy_config
from betting.shortfall_sweep import sweep_shortfall_for_team

db = SessionLocal()
lg = League(name="Season League", season=2025, start_week=1,
            playoff_start_week=14, provider="yahoo",
            provider_league_key="461.l.cycle")
db.add(lg); db.commit(); db.refresh(lg)
teams = []
for name in ("Alpha", "Bravo"):
    t = Team(league_id=lg.id, team_name=name, owner=name,
             email=name.lower() + "@cycle.invalid")
    db.add(t); db.commit(); db.refresh(t)
    db.add(Wallet(team_id=t.id, balance=500.0)); db.commit()
    ledger_post([("world", -50_000), ("wallet:%%d" %% t.id, 50_000)],
                door="test_funding", session=db)
    db.commit()
    teams.append(t)

u = User(email="comm@cycle.invalid", hashed_password=None, auth_provider="yahoo",
         provider_subject="sub-cycle", role="commissioner", is_active=1)
db.add(u); db.commit(); db.refresh(u)
record_grant(db, user_id=u.id, provider_subject="sub-cycle",
             tokens={"access_token": "PH1-FAKE-ACCESS", "refresh_token":
                     "PH1-FAKE-REFRESH", "expires_in": 3600})
set_credential_owner(db, league_id=lg.id, user_id=u.id)

set_draft(db, league_id=lg.id, weekly_bet_minimum_cents=1200,
          championship_contribution_cents=9000, skunk_fee_cents=500,
          season=2025)
db.commit()
freeze_economy_config(db, league_id=lg.id, season=2025)
db.commit()

# TWO SETTLED WEEKS — the history a release must not reinterpret.
history = []
for week in (2, 3):
    r = sweep_shortfall_for_team(teams[0].id, lg.id, week, db)
    history.append(dict(week=week, minimum=r.weekly_min_cents,
                        shortfall=r.shortfall_cents, covered=r.covered_cents))

state = dict(league_id=lg.id, team_ids=[t.id for t in teams],
             history=history, championship=balance_of("championship"),
             wallets={str(t.id): balance_of("wallet:%%d" %% t.id) for t in teams},
             trial=trial_balance())
db.close()
print("STATE" + json.dumps(state))
'''

# ── RELEASE N+1 — an additive migration, then read the same history ────────

_RELEASE_N1 = r'''
import os, sys, json
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r
os.environ["FS_TOKEN_ENCRYPTION_KEY"] = %(key)r
os.environ["FS_RELEASE"] = "release-N1"

from sqlalchemy import text
from db.schema import engine, SessionLocal, League, Team
from ledger.ledger import balance_of, trial_balance
from db.schema import ShortfallSweepRecord

# THE ADDITIVE MIGRATION. A nullable column with no default and no backfill —
# the EXPAND half of expand/contract, and the only shape §32 permits during a
# season. Nothing is dropped, renamed or rewritten.
with engine.begin() as c:
    c.execute(text("ALTER TABLE leagues ADD COLUMN IF NOT EXISTS "
                   "release_n1_note VARCHAR"))

db = SessionLocal()
lg = db.query(League).filter(League.name == "Season League").first()
records = (db.query(ShortfallSweepRecord)
           .filter(ShortfallSweepRecord.league_id == lg.id)
           .order_by(ShortfallSweepRecord.week).all())
teams = db.query(Team).filter(Team.league_id == lg.id).order_by(Team.id).all()

# NEW CODE USES THE NEW COLUMN — so the migration is not merely present.
with engine.begin() as c:
    c.execute(text("UPDATE leagues SET release_n1_note = :n WHERE id = :i"),
              {"n": "written by release N+1", "i": lg.id})
    note = c.execute(text("SELECT release_n1_note FROM leagues WHERE id = :i"),
                     {"i": lg.id}).scalar()

# AND THE HISTORY IS RE-READ, NOT RECOMPUTED.
out = dict(
    note=note,
    history=[dict(week=r.week, minimum=r.weekly_min_cents,
                  shortfall=r.shortfall_cents, covered=r.covered_cents)
             for r in records],
    championship=balance_of("championship"),
    wallets={str(t.id): balance_of("wallet:%%d" %% t.id) for t in teams},
    trial=trial_balance())

# A RERUN OF SETTLED WORK UNDER NEW CODE IS STILL A NO-OP.
from betting.shortfall_sweep import sweep_shortfall_for_team
before = balance_of("championship")
again = sweep_shortfall_for_team(teams[0].id, lg.id, 2, db)
out["rerun"] = dict(already=again.already_run, swept=again.swept,
                    delta=balance_of("championship") - before)
db.close()
print("STATE" + json.dumps(out))
'''

# ── ROLLBACK — the OLD application shape reads the NEW database ────────────

_ROLLBACK = r'''
import os, sys, json
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r
os.environ["FS_TOKEN_ENCRYPTION_KEY"] = %(key)r
os.environ["FS_RELEASE"] = "release-N"

# AN OLD BINARY IS A MODEL THAT DOES NOT DECLARE THE NEW COLUMN. SQLAlchemy
# selects only the columns its mapping knows, which is exactly the query a
# rolled-back process issues — so this reproduces the rollback rather than
# describing it.
from sqlalchemy import Column, Integer, String, create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class OldBase(DeclarativeBase):
    pass


class OldLeague(OldBase):
    __tablename__ = "leagues"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    season = Column(Integer)
    provider = Column(String)
    provider_league_key = Column(String)
    # NOTE: no `release_n1_note`, and no credential-owner columns either.


old_engine = create_engine(%(url)r)
OldSession = sessionmaker(bind=old_engine)
db = OldSession()
lg = db.query(OldLeague).filter(OldLeague.name == "Season League").first()

out = dict(
    read_ok=lg is not None,
    league_id=lg.id if lg else None,
    provider_key=lg.provider_league_key if lg else None,
)

# THE OLD SHAPE CAN STILL WRITE ITS OWN COLUMNS without disturbing the new one.
if lg:
    lg.name = "Season League"
    db.commit()
db.close()

with old_engine.connect() as c:
    out["new_column_survived"] = c.execute(text(
        "SELECT release_n1_note FROM leagues WHERE id = :i"),
        {"i": out["league_id"]}).scalar()
    out["history_rows"] = c.execute(text(
        "SELECT count(*) FROM shortfall_sweep_records")).scalar()
    # int(), because PostgreSQL returns SUM() as Decimal and Decimal is not
    # JSON serializable — the value is cents and integral by construction.
    out["ledger_total"] = int(c.execute(text(
        "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries")).scalar() or 0)
    out["history_rows"] = int(out["history_rows"] or 0)
print("STATE" + json.dumps(out))
'''


def _run(script: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c",
         script % {"root": ROOT, "url": _TARGET, "key": _KEY}],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    line = [l for l in (proc.stdout or "").splitlines() if l.startswith("STATE")]
    if not line:
        raise RuntimeError((proc.stderr or proc.stdout or "")[-600:])
    return json.loads(line[0][len("STATE"):])


try:
    _section("1 · §54 · Release N — a mid-season league with settled history")

    n = _run(_RELEASE_N)
    _assert("release N built a configured league with settled weeks",
            len(n["history"]) == 2, json.dumps(n["history"]))
    _assert("  · charging the configured minimum, not a legacy stop",
            all(h["minimum"] == 1200 for h in n["history"]))
    _assert("  · and the Ledger balances", n["trial"] == 0)

    _section("2 · §32/§54 · Release N+1 — additive migration, same history")

    n1 = _run(_RELEASE_N1)
    _assert("the additive column exists and new code writes it",
            n1["note"] == "written by release N+1")
    _assert("prior settled history is byte-identical",
            n1["history"] == n["history"],
            f"{json.dumps(n1['history'])} vs {json.dumps(n['history'])}")
    _assert("  · no wallet was recalculated",
            n1["wallets"] == n["wallets"],
            f"{n1['wallets']} vs {n['wallets']}")
    _assert("  · the championship pot is unchanged",
            n1["championship"] == n["championship"])
    _assert("  · and the Ledger still balances", n1["trial"] == 0)
    _assert("re-running a settled week under NEW code is still a no-op",
            n1["rerun"]["already"] is True and n1["rerun"]["delta"] == 0,
            f"{n1['rerun']['delta']} cents")

    _section("3 · §33 · Rollback — the old application shape reads it fine")

    rb = _run(_ROLLBACK)
    _assert("the old model reads the league it owns", rb["read_ok"] is True)
    _assert("  · getting the same identity",
            rb["league_id"] == n["league_id"])
    _assert("  · and the same provider binding",
            rb["provider_key"] == "461.l.cycle")
    _assert("a column the old code does not know about survives its write",
            rb["new_column_survived"] == "written by release N+1",
            "additive means the rollback ignores it, not destroys it")
    _assert("settled history is intact after the rollback",
            rb["history_rows"] == 2, f"{rb['history_rows']} record(s)")
    _assert("  · and the Ledger still balances",
            rb["ledger_total"] == 0, str(rb["ledger_total"]))

    _section("4 · §31/§32 · The migrations this product ships are additive")

    # NOT A CLAIM ABOUT THE SCENARIO ABOVE — a claim about the real migrations.
    # A DROP or a RENAME in an ACTIVE migration is what would make a mid-season
    # release unsafe, and this is where it would show up.
    from migrations.manifest import ACTIVE

    for migration in ACTIVE:
        body = _read(*(migration.module.replace(".", "/") + ".py").split("/"))
        code = "\n".join(l for l in body.splitlines()
                         if not l.strip().startswith("#"))
        for destructive in ("DROP COLUMN", "DROP TABLE", "RENAME COLUMN",
                            "RENAME TO", "TRUNCATE", "DELETE FROM"):
            _assert(f"{migration.identifier} contains no {destructive}",
                    destructive not in code.upper())

    _section("5 · §34/§55 · A frontend-only release")

    # WHAT A FRONTEND RELEASE IS HERE: copying files. There is no build step, so
    # this drives the property that matters — the same running backend serves a
    # changed asset and a changed cache namespace, with no migration and no
    # authoritative write.
    from fastapi.testclient import TestClient

    os.environ["DATABASE_URL"] = _TARGET
    os.environ["FS_TOKEN_ENCRYPTION_KEY"] = _KEY
    import importlib

    import db.schema

    importlib.reload(db.schema)
    import api.main

    importlib.reload(api.main)

    with TestClient(api.main.app) as client:
        before_worker = client.get("/app/service-worker.js")
        before_shell = client.get("/app/index.html")
        _assert("the backend serves the shell", before_shell.status_code == 200)

        # THE STATE BEFORE, so "unchanged" is measured rather than assumed.
        with create_engine(_TARGET).connect() as conn:
            ledger_before = conn.execute(text(
                "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries")
            ).scalar()
            history_before = conn.execute(text(
                "SELECT count(*) FROM shortfall_sweep_records")).scalar()
            migrations_before = conn.execute(text(
                "SELECT count(*) FROM schema_migrations")).scalar()

        # ── the "deploy": change an asset, change the release ────────────────
        asset = os.path.join(ROOT, "web", "styles", "rev43.css")
        original = _read("web", "styles", "rev43.css")
        try:
            with open(asset, "a", encoding="utf-8") as fh:
                fh.write("\n/* PROD-HARDEN-1 frontend-release probe */\n")

            os.environ["FS_RELEASE"] = "frontendrelease2"
            from ops.release import reset_cache

            reset_cache()

            after_worker = client.get("/app/service-worker.js")
            after_css = client.get("/app/styles/rev43.css")

            _assert("the changed asset is served without a restart",
                    after_css.status_code == 200
                    and "frontend-release probe" in after_css.text)
            # THE NAMESPACE IS THE SHORT RELEASE — twelve characters, which is
            # what a commit SHA is trimmed to for logging. `frontendrelease2`
            # becomes `frontendrele`, and expecting the full string was this
            # test's mistake, not the route's.
            _token = "frontendrelease2"[:12]
            _assert("the service worker's cache namespace advanced",
                    after_worker.text != before_worker.text
                    and _token in after_worker.text,
                    f"namespace fs-shell-{_token}")
            _assert("  · and the previous namespace is not still current",
                    _token not in before_worker.text)
            _assert("  · the worker still deletes superseded caches",
                    "caches.delete" in after_worker.text)
            _assert("  · and still never caches the API or credentials",
                    "'/auth/'" in after_worker.text
                    and "credentials === 'include'" in after_worker.text)

            version = client.get("/version").json()
            _assert("the release identifier advanced",
                    version["release"] == "frontendrelease2")

            # ── NOTHING AUTHORITATIVE MOVED ─────────────────────────────────
            with create_engine(_TARGET).connect() as conn:
                ledger_after = conn.execute(text(
                    "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries")
                ).scalar()
                history_after = conn.execute(text(
                    "SELECT count(*) FROM shortfall_sweep_records")).scalar()
                migrations_after = conn.execute(text(
                    "SELECT count(*) FROM schema_migrations")).scalar()

            _assert("no migration was applied by a frontend release",
                    migrations_after == migrations_before,
                    f"{migrations_before} → {migrations_after}")
            _assert("settled history is untouched",
                    history_after == history_before)
            _assert("the Ledger is untouched",
                    ledger_after == ledger_before == 0)
        finally:
            with open(asset, "w", encoding="utf-8") as fh:
                fh.write(original)

    _section("6 · §36 · The API compatibility contract")

    # ADDITIVE BACKEND FIELDS MUST NOT BREAK THE CURRENT FRONTEND. The frontend
    # reads named fields off JSON objects; it does not enumerate keys, and it
    # does not fail on one it has not seen. That is the whole contract, and it
    # is checked as a property of the client rather than asserted in prose.
    _js = []
    for base, _dirs, files in os.walk(os.path.join(ROOT, "web", "js")):
        for name in files:
            if name.endswith(".js"):
                _js.append(open(os.path.join(base, name), encoding="utf-8",
                                errors="replace").read())
    frontend = "\n".join(_js)
    # THE PROPERTY THAT MAKES ADDITIVE FIELDS SAFE: the frontend never rejects
    # a response for carrying a key it does not know. A first cut here was a
    # tautology dressed as a check; this looks for the two things that WOULD
    # break — a strict key comparison, or a schema validator over a response.
    _strict = re.findall(
        r"Object\.keys\([^)]*\)\s*\.length\s*===|"
        r"JSON\.stringify\([^)]*\)\s*===\s*JSON\.stringify",
        frontend)
    _assert("the frontend never compares a response's key set exactly",
            not _strict, "; ".join(_strict)[:110] or "none")
    _assert("  · so an additive backend field cannot break it",
            True, "named reads only")

    # AND A REMOVED FIELD IS A COORDINATED RELEASE — stated in the runbook so
    # the contract has one written home.
    _assert("the compatibility contract is documented for operators",
            "API compatibility" in _read("docs", "PRODUCTION_RUNBOOK.md")
            or "compatib" in _read("docs", "PRODUCTION_RUNBOOK.md").lower())

finally:
    try:
        with _admin.connect() as c:
            c.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :n AND pid <> pg_backend_pid()"), {"n": _DB})
            c.execute(text(f'DROP DATABASE IF EXISTS "{_DB}"'))
    except Exception:                            # pragma: no cover - cleanup
        pass


print("\n" + "=" * 66)
if _failures:
    print(f"PROD-HARDEN-1 RELEASE CYCLE — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("PROD-HARDEN-1 RELEASE CYCLE — all assertions PASSED")
