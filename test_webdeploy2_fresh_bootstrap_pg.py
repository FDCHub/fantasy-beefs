#!/usr/bin/env python3
"""WEBDEPLOY-2 - the pre-deploy migration command against a FRESH database.

    TEST_DATABASE_URL=postgresql://.../fantasy_test python test_webdeploy2_fresh_bootstrap_pg.py

WHY THIS SUITE EXISTS. `railway.toml` runs `python -m migrations.run` as the
platform's `preDeployCommand`: once, before any instance starts, with a non-zero
exit blocking the release. Against an EMPTY database that was fatal, and it was
found by actually deploying rather than by reasoning:

    MIGRATION FAILED: NoSuchTableError - the release must not proceed.

Every ACTIVE migration is pending on an empty database, the first one ALTERs
`leagues`, and no table exists yet. The application's own startup hook would
have bootstrapped the schema - but the pre-deploy command fails before any
instance is permitted to start, so nothing ever did. A first deploy onto a
freshly provisioned PostgreSQL could never succeed.

WHAT THE FIX HAS TO PRESERVE, AND WHY EACH IS CHECKED HERE

  1. A fresh database ends up with the COMPLETE schema, including the six RC2
     championship tables and `ledger_entries`. Both are easy to miss: the
     championship models are only registered by an explicit import, and the
     ledger lives on its own declarative base. A bootstrap that stamped
     0003-0006 while creating none of those tables would report itself migrated
     and fail on the first Credit posted - which is the precise failure
     `railway.toml` warns about for the entrypoint.

  2. `pending()` and `verify()` are both empty afterwards, so `/ready` answers
     200 rather than withholding traffic from a healthy process forever.

  3. FRESH MEANS ENTIRELY EMPTY. A database with ANY table takes the ordinary
     migration path untouched. This is the guard that stops the bootstrap from
     ever being a silent `create_all` over a database that already holds data.

  4. It is idempotent, and `--dry-run` still writes nothing.

REQUIRES POSTGRESQL. `preDeployCommand` runs against the production target and
DDL transactionality is exactly what is being relied on.
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_FAILURES: list = []
_PASSES = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _PASSES
    if condition:
        _PASSES += 1
        print(f"  [PASS] {label}" + (f" - {detail}" if detail else ""))
    else:
        _FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{title}")


from sqlalchemy import create_engine, inspect, make_url, text  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))

print("=" * 78)
print("WEBDEPLOY-2 - PRE-DEPLOY MIGRATION AGAINST A FRESH DATABASE")
print("=" * 78)

_ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if not _ADMIN_URL:
    print("\n  [FAIL] TEST_DATABASE_URL is not set - this suite needs PostgreSQL.")
    print("  It does NOT fall back to SQLite: the pre-deploy command runs")
    print("  against PostgreSQL and that is what must be certified.")
    raise SystemExit(2)

_url = make_url(_ADMIN_URL)
if _url.get_backend_name() != "postgresql":
    print(f"\n  [FAIL] TEST_DATABASE_URL is not PostgreSQL ({_url.drivername})")
    raise SystemExit(2)
if "_test" not in (_url.database or ""):
    print(f"\n  [FAIL] the database name must contain '_test'; this suite "
          f"CREATEs and DROPs databases.")
    raise SystemExit(2)

# `str(URL)` MASKS THE PASSWORD as *** in SQLAlchemy 2.0, which produces a
# connection failure that looks exactly like a bad credential and is not one.
_BASE = _url.set(database="postgres").render_as_string(hide_password=False)
_admin = create_engine(_BASE, isolation_level="AUTOCOMMIT")


def make_db(suffix: str) -> str:
    name = f"{_url.database}_{suffix}"[:60]
    with _admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    return _url.set(database=name).render_as_string(hide_password=False)


def drop_db(url: str) -> None:
    name = make_url(url).database
    with _admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))


def run_module(url: str, *args) -> subprocess.CompletedProcess:
    """Run `python -m migrations.run` exactly as the platform does."""
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    env["PYTHONIOENCODING"] = "utf-8"
    env["JWT_SECRET_KEY"] = env.get("JWT_SECRET_KEY", "webdeploy2-suite")
    env.pop("TEST_DATABASE_URL", None)
    return subprocess.run([sys.executable, "-m", "migrations.run", *args],
                          cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)


def tables(url: str) -> set:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


# -- 1 . the empty database the first deploy actually lands on ---------------

section("1 - An empty database is bootstrapped, not migrated")

fresh_url = make_db("fresh")
check("the database starts genuinely empty", tables(fresh_url) == set(),
      f"{len(tables(fresh_url))} tables")

proc = run_module(fresh_url)
check("`python -m migrations.run` EXITS 0 on an empty database",
      proc.returncode == 0,
      (proc.stderr or proc.stdout).strip().splitlines()[-1][:90]
      if proc.returncode else "exit 0")
check("  - and says it bootstrapped rather than migrated",
      "fresh database" in proc.stdout, proc.stdout.strip()[:90])
check("  - NoSuchTableError is gone",
      "NoSuchTableError" not in (proc.stdout + proc.stderr),
      "clean")

built = tables(fresh_url)
check("the application schema exists", "leagues" in built, f"{len(built)} tables")
check("the LEDGER table exists - its own declarative base is not forgotten",
      "ledger_entries" in built)
check("the migration record table exists", "schema_migrations" in built)

RC2_TABLES = ("fantasystakes_championship_config",)
missing_rc2 = [t for t in RC2_TABLES if t not in built]
check("the RC2 championship tables exist - the models were registered",
      not missing_rc2, str(missing_rc2 or "present"))


# -- 2 . the record matches the schema --------------------------------------

section("2 - The manifest is stamped, and the schema corroborates it")

env = dict(os.environ)
env["DATABASE_URL"] = fresh_url
env.pop("TEST_DATABASE_URL", None)
probe = subprocess.run(
    [sys.executable, "-c",
     "import json\n"
     "from db.schema import engine\n"
     "from migrations.run import pending, verify, applied_identifiers\n"
     "print(json.dumps({'pending': [m.identifier for m in pending(engine)],\n"
     "                  'unverified': verify(engine),\n"
     "                  'applied': sorted(applied_identifiers(engine))}))"],
    cwd=ROOT, env=env, capture_output=True, text=True,
    encoding="utf-8", errors="replace", timeout=600)

state = {}
try:
    import json as _json
    state = _json.loads(probe.stdout.strip().splitlines()[-1])
except Exception:
    pass

check("nothing is pending after the bootstrap", state.get("pending") == [],
      str(state.get("pending"))[:80])
check("every applied migration is corroborated by the live schema",
      state.get("unverified") == [], str(state.get("unverified"))[:100])
check("the manifest is stamped", len(state.get("applied") or []) >= 6,
      f"{len(state.get('applied') or [])} recorded")


# -- 3 . readiness, which is what the platform gates on ---------------------

section("3 - /ready answers 200 against the bootstrapped database")

ready = subprocess.run(
    [sys.executable, "-c",
     "from fastapi.testclient import TestClient\n"
     "import api.main_rc2 as m, json\n"
     "with TestClient(m.app) as c:\n"
     "    r = c.get('/ready')\n"
     "    print(json.dumps({'status': r.status_code, 'body': r.json()}))"],
    cwd=ROOT, env={**env, "JWT_SECRET_KEY": "webdeploy2-suite"},
    capture_output=True, text=True, encoding="utf-8", errors="replace",
    timeout=600)
body = {}
try:
    import json as _json
    body = _json.loads(ready.stdout.strip().splitlines()[-1])
except Exception:
    pass
check("/ready returns 200", body.get("status") == 200, str(body.get("status")))
checks = (body.get("body") or {}).get("checks") or {}
check("  - migrations ok", checks.get("migrations") == "ok", str(checks.get("migrations")))
check("  - schema ok", checks.get("schema") == "ok", str(checks.get("schema")))
check("  - database ok", checks.get("database") == "ok", str(checks.get("database")))


# -- 4 . idempotence and dry-run --------------------------------------------

section("4 - Repeating it changes nothing")

again = run_module(fresh_url)
check("a second run exits 0", again.returncode == 0, str(again.returncode))
check("  - and reports nothing pending", "nothing pending" in again.stdout,
      again.stdout.strip()[:80])
check("  - the schema is unchanged", tables(fresh_url) == built,
      f"{len(built)} tables")

dry_url = make_db("dry")
dry = run_module(dry_url, "--dry-run")
check("--dry-run on an empty database exits 0", dry.returncode == 0)
check("  - says it WOULD bootstrap", "WOULD BOOTSTRAP" in dry.stdout,
      dry.stdout.strip()[:80])
check("  - and creates NOTHING", tables(dry_url) == set(),
      f"{len(tables(dry_url))} tables")


# -- 5 . the guard: fresh means ENTIRELY empty ------------------------------

section("5 - A database that is not empty is never bootstrapped")

# THE CASE THAT MATTERS. A database holding ANY table is not a fresh
# deployment, and a bootstrap over it would be a silent `create_all` across
# somebody's data. It must take the ordinary migration path - which, on a
# database with no application schema, correctly FAILS rather than inventing one.
partial_url = make_db("partial")
eng = create_engine(partial_url)
with eng.begin() as conn:
    conn.execute(text("CREATE TABLE unrelated_marker (id integer primary key)"))
eng.dispose()

partial = run_module(partial_url)
after = tables(partial_url)
check("a non-empty database is REFUSED, not bootstrapped",
      partial.returncode != 0,
      f"exit {partial.returncode}")
check("  - it failed as a migration, naming the missing table",
      "MIGRATION FAILED" in (partial.stderr + partial.stdout),
      (partial.stderr or partial.stdout).strip().splitlines()[-1][:90]
      if (partial.stderr or partial.stdout).strip() else "")
check("  - and NO application schema was created over it",
      "leagues" not in after and "ledger_entries" not in after,
      f"tables now: {sorted(after)[:4]}")
check("  - the pre-existing table is untouched", "unrelated_marker" in after)

for _u in (fresh_url, dry_url, partial_url):
    drop_db(_u)

print("\n" + "=" * 78)
if _FAILURES:
    print(f"WEBDEPLOY-2 FRESH BOOTSTRAP: {len(_FAILURES)} FAILED")
    for item in _FAILURES:
        print(f"  - {item}")
    raise SystemExit(1)
print(f"WEBDEPLOY-2 FRESH BOOTSTRAP: all {_PASSES} assertions PASSED")
