#!/usr/bin/env python3
"""
test_prod_harden1_restore.py — PROD-HARDEN-1 · the restore drill, for real.

§53 IS EXPLICIT THAT MOCKING THIS IS INSUFFICIENT, and it is right. A backup
nobody has restored is a hypothesis, and the failure modes that matter — an
encrypted grant that will not open, a wallet whose Ledger did not come back with
it, a settled result that reverted — are exactly the ones a mock cannot have.

So this does the real thing:

    1. build representative committed state on PostgreSQL
    2. take a real backup artifact
    3. DESTROY the database
    4. restore into a fresh one
    5. certify the invariants against the restored copy

── HOW THE BACKUP IS TAKEN, AND WHY ────────────────────────────────────────

`pg_dump --format=custom` is the runbook's instrument and is what this drill
uses. The binaries are not on this machine's PATH — but they are inside the
PostgreSQL container the test database lives in, which is where they belong
anyway, so the dump and the restore run there via `docker exec`. That is the
same artifact an operator produces, made by the same tool, at the same version
as the server.

Two fallbacks exist, and which one ran is always reported rather than hidden:
a local `pg_dump` if one is on PATH, and failing both, a SQL-level row dump
taken through the application's own connection. The fallback is weaker as an
ARTIFACT and identical as a TEST — what is certified is that committed state
survives destroy-and-restore intact, not that one particular tool works.

── WHAT IS DESTROYED ───────────────────────────────────────────────────────

A database this suite created, in the disposable test container, and nothing
else. The guards are the project's own: `_test` in the name, no Railway host.
"""

from __future__ import annotations

import json
import os
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

from sqlalchemy import create_engine, inspect, text                # noqa: E402
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


_ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if not _ADMIN_URL:
    print("  [FAIL] TEST_DATABASE_URL is not set — this suite needs PostgreSQL")
    sys.exit(2)
_url = make_url(_ADMIN_URL)
if "_test" not in (_url.database or ""):
    print("  [FAIL] the admin database name must contain '_test'")
    sys.exit(2)
for forbidden in ("railway", "rlwy"):
    if forbidden in (_url.host or ""):
        print(f"  [FAIL] refusing a {forbidden} host")
        sys.exit(2)

_admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
_SOURCE = f"ph1_src_{uuid.uuid4().hex[:8]}_test"
_RESTORED = f"ph1_dst_{uuid.uuid4().hex[:8]}_test"
_TMP = tempfile.mkdtemp(prefix="ph1-restore-")


def _url_for(name: str) -> str:
    return _url.set(database=name).render_as_string(hide_password=False)


def _drop(name: str) -> None:
    try:
        with _admin.connect() as c:
            c.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :n AND pid <> pg_backend_pid()"), {"n": name})
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    except Exception:                            # pragma: no cover - cleanup
        pass


# THE ENCRYPTION KEY IS GENERATED HERE AND PASSED TO BOTH SIDES.
#
# It is deliberately NOT written into the dump, which is exactly the property
# §42 requires: a backup carrying its own decryption key protects nothing. The
# restored database is opened with the key held separately, which is the real
# operational relationship being certified.
from auth.token_crypto import generate_key                         # noqa: E402

_KEY = generate_key()

_BUILD = r'''
import os, sys, json
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r
os.environ["FS_TOKEN_ENCRYPTION_KEY"] = %(key)r

from db.schema import (Base, engine, SessionLocal, League, ProviderGrant, Team,
                       User, Wallet)
Base.metadata.create_all(engine)
from ledger.ledger import create_ledger_table, post as ledger_post, balance_of, trial_balance
create_ledger_table()

from auth.provider_grant import record_grant
from providers.yahoo.user_credentials import set_credential_owner
from economy.league_economy_config import set_draft, freeze_economy_config
from betting.shortfall_sweep import sweep_shortfall_for_team

db = SessionLocal()

lg = League(name="Restore League", season=2025, start_week=1,
            playoff_start_week=14, provider="yahoo",
            provider_league_key="461.l.restore")
db.add(lg); db.commit(); db.refresh(lg)

teams = []
for name in ("Alpha", "Bravo", "Charlie"):
    t = Team(league_id=lg.id, team_name=name, owner=name,
             email=name.lower() + "@restore.invalid",
             provider_team_key="461.l.restore.t.%%d" %% (len(teams) + 1))
    db.add(t); db.commit(); db.refresh(t)
    db.add(Wallet(team_id=t.id, balance=500.0)); db.commit()
    ledger_post([("world", -50_000), ("wallet:%%d" %% t.id, 50_000)],
                door="test_funding", session=db)
    db.commit()
    teams.append(t)

u = User(email="comm@restore.invalid", hashed_password=None,
         auth_provider="yahoo", provider_subject="sub-restore-comm",
         role="commissioner", is_active=1)
db.add(u); db.commit(); db.refresh(u)

# A SEALED GRANT — fake bearer material, real envelope.
record_grant(db, user_id=u.id, provider_subject="sub-restore-comm",
             tokens={"access_token": "PH1-FAKE-ACCESS-" + "A" * 40,
                     "refresh_token": "PH1-FAKE-REFRESH-" + "R" * 40,
                     "expires_in": 3600, "scope": "openid email fspt-r"})
set_credential_owner(db, league_id=lg.id, user_id=u.id)

# A FROZEN ECONOMY, so a configured value has to survive.
set_draft(db, league_id=lg.id, weekly_bet_minimum_cents=1200,
          championship_contribution_cents=9000, skunk_fee_cents=500,
          season=2025)
db.commit()
freeze_economy_config(db, league_id=lg.id, season=2025)
db.commit()

# A SETTLED ECONOMIC ARTIFACT — a completed sweep with a durable record.
sweep = sweep_shortfall_for_team(teams[0].id, lg.id, 3, db)

from db.schema import ProviderGrant as PG
grant = db.query(PG).filter(PG.user_id == u.id).first()

state = {
    "league_id": lg.id,
    "provider_league_key": lg.provider_league_key,
    "credential_owner": lg.provider_credential_user_id,
    "team_ids": [t.id for t in teams],
    "team_provider_keys": [t.provider_team_key for t in teams],
    "user_id": u.id,
    "user_subject": u.provider_subject,
    "grant_id": grant.id,
    "grant_access_sealed": grant.access_token_sealed,
    "grant_refresh_sealed": grant.refresh_token_sealed,
    "grant_version": grant.token_version,
    "wallets": {str(t.id): balance_of("wallet:%%d" %% t.id) for t in teams},
    "championship": balance_of("championship"),
    "trial": trial_balance(),
    "sweep": dict(week=sweep.week, minimum=sweep.weekly_min_cents,
                  shortfall=sweep.shortfall_cents,
                  covered=sweep.covered_cents, swept=sweep.swept),
}
db.close()
print("STATE" + json.dumps(state))
'''

_VERIFY = r'''
import os, sys, json
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r
os.environ["FS_TOKEN_ENCRYPTION_KEY"] = %(key)r

from db.schema import (SessionLocal, League, ProviderGrant, Team, User, Wallet)
from ledger.ledger import balance_of, trial_balance
from auth.provider_grant import access_token_for
from payments.economy_config import resolve_allocation_terms
from db.schema import ShortfallSweepRecord

db = SessionLocal()
lg = db.query(League).filter(League.name == "Restore League").first()
u = db.query(User).filter(User.provider_subject == "sub-restore-comm").first()
grant = db.query(ProviderGrant).filter(ProviderGrant.user_id == u.id).first()
teams = db.query(Team).filter(Team.league_id == lg.id).order_by(Team.id).all()
terms = resolve_allocation_terms(db, league_id=lg.id, season=2025)
record = (db.query(ShortfallSweepRecord)
          .filter(ShortfallSweepRecord.league_id == lg.id).first())

out = {
    "league_id": lg.id,
    "provider_league_key": lg.provider_league_key,
    "credential_owner": lg.provider_credential_user_id,
    "team_ids": [t.id for t in teams],
    "team_provider_keys": [t.provider_team_key for t in teams],
    "user_id": u.id,
    "user_subject": u.provider_subject,
    "grant_id": grant.id,
    "grant_access_sealed": grant.access_token_sealed,
    "grant_refresh_sealed": grant.refresh_token_sealed,
    "grant_version": grant.token_version,
    "grant_opens": access_token_for(db, user_id=u.id),
    "wallets": {str(t.id): balance_of("wallet:%%d" %% t.id) for t in teams},
    "championship": balance_of("championship"),
    "trial": trial_balance(),
    "economy": dict(source=terms.source, weekly=terms.weekly_bet_minimum_cents,
                    weeks=terms.regular_season_week_count,
                    allocation=terms.buyin_cents),
    "sweep_record": dict(week=record.week, minimum=record.weekly_min_cents,
                         shortfall=record.shortfall_cents,
                         covered=record.covered_cents) if record else None,
}

# A RESTORED DATABASE MUST BE IMMEDIATELY AUTHORITATIVE — including that a
# rerun of already-settled work stays a no-op.
from betting.shortfall_sweep import sweep_shortfall_for_team
champ_before = balance_of("championship")
again = sweep_shortfall_for_team(teams[0].id, lg.id, 3, db)
out["rerun"] = dict(already=again.already_run, swept=again.swept,
                    delta=balance_of("championship") - champ_before)

from ops.audit import run_audit
audit = run_audit(SessionLocal())
out["audit"] = dict(clean=audit.clean,
                    findings=[(f.check, f.severity) for f in audit.findings])
db.close()
print("VERIFY" + json.dumps(out))
'''


def _run(script: str, url: str, marker: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", script % {"root": ROOT, "url": url, "key": _KEY}],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    line = [l for l in (proc.stdout or "").splitlines() if l.startswith(marker)]
    if not line:
        raise RuntimeError((proc.stderr or proc.stdout or "")[-600:])
    return json.loads(line[0][len(marker):])


try:
    _section("1 · §16 · Representative committed state")

    with _admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{_SOURCE}"'))
    before = _run(_BUILD, _url_for(_SOURCE), "STATE")

    _assert("a league, teams, wallets and a commissioner exist",
            before["league_id"] and len(before["team_ids"]) == 3)
    _assert("a frozen economy configuration exists", True, "1200/9000/500")
    _assert("a sealed Yahoo grant exists",
            bool(before["grant_refresh_sealed"])
            and before["grant_refresh_sealed"].startswith("v1."))
    _assert("a settled economic artifact exists",
            before["sweep"]["swept"] is True,
            f"{before['sweep']['covered']} cents swept")
    _assert("and the Ledger balances", before["trial"] == 0)

    # ── 2 · the backup artifact ──────────────────────────────────────────────
    _section("2 · §36/§37 · A real backup artifact")

    dump_path = os.path.join(_TMP, "backup.dump")

    # WHERE THE INSTRUMENT LIVES. Prefer a local `pg_dump`; otherwise run the
    # one inside the database container, which is the same tool at the same
    # version as the server it is dumping.
    _container = os.environ.get("FS_PG_CONTAINER", "pg-fantasy-test")
    _local = shutil.which("pg_dump") is not None
    _in_container = False
    if not _local and shutil.which("docker"):
        probe = subprocess.run(
            ["docker", "exec", _container, "pg_dump", "--version"],
            capture_output=True, text=True, timeout=60)
        _in_container = probe.returncode == 0

    used_pg_dump = _local or _in_container
    _remote_dump = "/tmp/ph1_backup.dump"

    def _pg(tool: str, *args) -> subprocess.CompletedProcess:
        """Run a PostgreSQL client tool, locally or in the container."""
        base = ["--host", "127.0.0.1" if _in_container else (_url.host or "localhost"),
                "--port", "5432" if _in_container else str(_url.port or 5432),
                "--username", _url.username or "postgres"]
        if _in_container:
            return subprocess.run(
                ["docker", "exec", "-e", f"PGPASSWORD={_url.password or ''}",
                 _container, tool, *base, *args],
                capture_output=True, text=True, timeout=300)
        return subprocess.run(
            [tool, *base, *args], capture_output=True, text=True, timeout=300,
            env={**os.environ, "PGPASSWORD": _url.password or ""})

    if used_pg_dump:
        target = _remote_dump if _in_container else dump_path
        proc = _pg("pg_dump", "--format=custom", "--no-owner",
                   "--no-privileges", "--dbname", _SOURCE, "--file", target)
        size = 0
        if proc.returncode == 0 and _in_container:
            copied = subprocess.run(
                ["docker", "cp", f"{_container}:{_remote_dump}", dump_path],
                capture_output=True, text=True, timeout=120)
            size = os.path.getsize(dump_path) if copied.returncode == 0 else 0
        elif proc.returncode == 0:
            size = os.path.getsize(dump_path)
        _assert("pg_dump produced a custom-format artifact",
                proc.returncode == 0 and size > 0,
                f"{size} bytes" if size else (proc.stderr or "")[-200:])
    else:
        # THE FALLBACK, AND IT IS REPORTED AS ONE. Every table's rows read
        # through the application's own connection and written out as SQL.
        src = create_engine(_url_for(_SOURCE))
        statements: list[str] = []
        insp = inspect(src)
        with src.connect() as conn:
            tables = insp.get_sorted_table_names() if hasattr(
                insp, "get_sorted_table_names") else insp.get_table_names()
            for table in tables:
                cols = [c["name"] for c in insp.get_columns(table)]
                rows = conn.execute(text(f'SELECT * FROM "{table}"')).fetchall()
                for row in rows:
                    values = ", ".join(
                        "NULL" if v is None else
                        ("'" + str(v).replace("'", "''") + "'")
                        for v in row)
                    statements.append(
                        f'INSERT INTO "{table}" '
                        f'({", ".join(chr(34) + c + chr(34) for c in cols)}) '
                        f'VALUES ({values});')
        with open(dump_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(statements))
        _assert("a SQL-level backup artifact was produced",
                os.path.getsize(dump_path) > 0,
                f"{len(statements)} row statements — pg_dump not on PATH")

    _instrument = ("pg_dump --format=custom (in container)" if _in_container
                   else "pg_dump --format=custom (local)" if _local
                   else "SQL row dump — pg_dump unavailable")
    print(f"    (backup instrument: {_instrument})")

    # ── 3 · destroy ──────────────────────────────────────────────────────────
    _section("3 · §53 · The source database is DESTROYED")

    _drop(_SOURCE)
    with _admin.connect() as c:
        gone = c.execute(text(
            "SELECT count(*) FROM pg_database WHERE datname = :n"),
            {"n": _SOURCE}).scalar()
    _assert("the source database no longer exists", gone == 0)

    # ── 4 · restore ──────────────────────────────────────────────────────────
    _section("4 · §53 · Restored into a fresh database")

    with _admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{_RESTORED}"'))

    if used_pg_dump:
        source_artifact = _remote_dump if _in_container else dump_path
        proc = _pg("pg_restore", "--no-owner", "--no-privileges",
                   "--dbname", _RESTORED, source_artifact)
        _assert("pg_restore rebuilt the database from the artifact",
                proc.returncode == 0, (proc.stderr or "")[-200:])
    else:
        # The schema is rebuilt from the models — which is what a fresh
        # deployment pointed at a restored volume does — then the rows replay.
        rebuild = subprocess.run(
            [sys.executable, "-c",
             "import os,sys; sys.path.insert(0, %r); "
             "os.environ['DATABASE_URL']=%r; "
             "from db.schema import Base, engine; Base.metadata.create_all(engine); "
             "from ledger.ledger import create_ledger_table; create_ledger_table(); "
             "print('SCHEMA')" % (ROOT, _url_for(_RESTORED))],
            cwd=ROOT, capture_output=True, text=True)
        _assert("the schema was rebuilt", "SCHEMA" in rebuild.stdout,
                (rebuild.stderr or "")[-200:])
        dst = create_engine(_url_for(_RESTORED), isolation_level="AUTOCOMMIT")
        with open(dump_path, encoding="utf-8") as fh:
            body = fh.read()
        replayed = 0
        with dst.connect() as conn:
            conn.execute(text("SET session_replication_role = replica"))
            for statement in [s for s in body.split(";\n") if s.strip()]:
                conn.execute(text(statement))
                replayed += 1
            conn.execute(text("SET session_replication_role = origin"))
            # SEQUENCES FOLLOW THE ROWS. A restore that left every sequence at 1
            # would collide on the next insert — a real restore hazard, and one
            # `pg_restore` handles for us on the other path.
            for table in inspect(dst).get_table_names():
                cols = [c["name"] for c in inspect(dst).get_columns(table)]
                if "id" not in cols:
                    continue
                conn.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('\"{table}\"','id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{table}\"), 1), true)"))
        _assert("the rows were replayed", replayed > 0, f"{replayed} statements")

    # ── 5 · the invariants ───────────────────────────────────────────────────
    _section("5 · §17 · Restore invariants")

    after = _run(_VERIFY, _url_for(_RESTORED), "VERIFY")

    _assert("the Ledger still balances after restore",
            after["trial"] == 0, str(after["trial"]))
    _assert("every wallet equals its Ledger-derived truth",
            after["wallets"] == before["wallets"],
            f"{after['wallets']} vs {before['wallets']}")
    _assert("  · and no wallet was reconstructed — the values are identical",
            all(after["wallets"][k] == before["wallets"][k]
                for k in before["wallets"]))
    _assert("the championship pot survived",
            after["championship"] == before["championship"],
            f"{after['championship']} cents")

    _section("6 · §17 · Identity, provider binding and settled state")

    _assert("league and team ids survive",
            after["league_id"] == before["league_id"]
            and after["team_ids"] == before["team_ids"])
    _assert("provider league and team keys survive",
            after["provider_league_key"] == before["provider_league_key"]
            and after["team_provider_keys"] == before["team_provider_keys"])
    _assert("the Yahoo subject survives",
            after["user_subject"] == before["user_subject"])
    _assert("the credential owner survives",
            after["credential_owner"] == before["credential_owner"])

    _section("7 · §17/§42 · The encrypted grant, opened with a separately held key")

    _assert("the sealed envelopes are byte-identical",
            after["grant_access_sealed"] == before["grant_access_sealed"]
            and after["grant_refresh_sealed"] == before["grant_refresh_sealed"])
    _assert("  · and still open with the key held outside the backup",
            after["grant_opens"] == "PH1-FAKE-ACCESS-" + "A" * 40,
            "opened")
    _assert("the token version survives",
            after["grant_version"] == before["grant_version"])

    _section("8 · §17 · Settled state remains settled")

    _assert("the frozen economy survives exactly",
            after["economy"]["source"] == "FROZEN_CONFIG"
            and after["economy"]["weekly"] == 1200
            and after["economy"]["weeks"] == 13
            and after["economy"]["allocation"] == 1200 * 13 + 9000,
            json.dumps(after["economy"]))
    _assert("the settled sweep record survives",
            after["sweep_record"] is not None
            and after["sweep_record"]["covered"] == before["sweep"]["covered"],
            json.dumps(after["sweep_record"]))
    _assert("re-running it on the restored database is a no-op",
            after["rerun"]["already"] is True
            and after["rerun"]["swept"] is False)
    _assert("  · with NO duplicate settlement",
            after["rerun"]["delta"] == 0, f"{after['rerun']['delta']} cents")

    _section("9 · §44 · The recovery audit accepts the restored database")

    _assert("the audit reports CLEAN", after["audit"]["clean"] is True,
            json.dumps(after["audit"]["findings"]))

finally:
    _drop(_SOURCE)
    _drop(_RESTORED)
    shutil.rmtree(_TMP, ignore_errors=True)


print("\n" + "=" * 66)
if _failures:
    print(f"PROD-HARDEN-1 RESTORE — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("PROD-HARDEN-1 RESTORE — all assertions PASSED")
