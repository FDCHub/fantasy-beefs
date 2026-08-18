#!/usr/bin/env python3
"""SPRINT B1 — the database-state invariant, driven on whatever dialect is set.

    python test_b1_schema_readiness.py
    DATABASE_URL="postgresql://.../fantasy_b1" python test_b1_schema_readiness.py

THE INVARIANT UNDER TEST
------------------------

    The application must not report ready against an unstamped, outdated or
    unverifiable database schema.

WHY THIS SUITE EXISTS. Before B1 the readiness check asked exactly one question
— "does `schema_migrations` list anything as pending?" — and treated the answer
as the whole truth about the database. A record is a CLAIM. Measured on this
branch before the fix:

    a database stamped 0001-0006 with all six championship tables ABSENT
    answered  GET /ready -> 200, {"ready": true, "migrations": "ok"}

That is the worst possible direction to be wrong in: the platform sends live
traffic to a process that cannot serve a championship, and every signal the
operator has says the deployment is healthy.

Four database states are built and driven here, and each one is built by real
code paths rather than described:

    HEALTHY     bootstrapped through the certified production entrypoint
    CORRUPT     stamped at head, schema missing what the stamp claims
    OUTDATED    schema at head, a migration record removed
    UNSTAMPED   schema present, no migration record at all

Only the first may answer ready. This suite is dialect-agnostic on purpose: the
production target is PostgreSQL and the invariant is not allowed to be a SQLite
accident, so CI runs it against both.

NO ECONOMICS. Nothing here posts a Credit, settles anything or touches a
championship figure. It builds schemas and reads two endpoints.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

FAIL: list = []
_TMP = tempfile.mkdtemp(prefix="b1-schema-")


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


def section(title: str) -> None:
    print(f"\n{title}")


# ── the dialect under test ───────────────────────────────────────────────────
#
# A caller-supplied DATABASE_URL is used as a TEMPLATE: each scenario gets its
# own database so the four states cannot contaminate one another. On SQLite that
# is a separate file; on PostgreSQL a separate database, created and dropped
# here.

_TEMPLATE = os.environ.get("B1_DATABASE_URL", "").strip()
IS_POSTGRES = _TEMPLATE.startswith("postgres")
_pg_created: list = []


def _pg_admin_url() -> str:
    head, _, _ = _TEMPLATE.rpartition("/")
    return f"{head}/postgres"


def scenario_url(name: str) -> str:
    """A private, empty database for one scenario."""
    if not IS_POSTGRES:
        return "sqlite:///" + os.path.join(_TMP, f"{name}.db").replace(os.sep, "/")

    from sqlalchemy import create_engine, text

    dbname = f"fs_b1_{name}"
    admin = create_engine(_pg_admin_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{dbname}"'))
        c.execute(text(f'CREATE DATABASE "{dbname}"'))
    admin.dispose()
    _pg_created.append(dbname)
    head, _, _ = _TEMPLATE.rpartition("/")
    return f"{head}/{dbname}"


def drop_scenarios() -> None:
    if not IS_POSTGRES or not _pg_created:
        return
    from sqlalchemy import create_engine, text

    admin = create_engine(_pg_admin_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        for dbname in _pg_created:
            c.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :d AND pid <> pg_backend_pid()"), {"d": dbname})
            c.execute(text(f'DROP DATABASE IF EXISTS "{dbname}"'))
    admin.dispose()


# ── the driver ───────────────────────────────────────────────────────────────
#
# Every scenario runs in a SUBPROCESS. `db.schema` binds its engine at import,
# and readiness reads that engine — reloading modules in-process to repoint a
# database is exactly how a suite ends up certifying a stale binding. A fresh
# interpreter per scenario is the only way this measures what it claims to.

_DRIVER = r'''
import json, os, sys
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r
os.environ.setdefault("JWT_SECRET_KEY", "b1-schema-readiness-suite")

MUTATE = %(mutate)r

from fastapi.testclient import TestClient
import api.main_rc2 as entry          # the certified production entrypoint

# Bootstrap through the real startup hook, then apply the scenario's damage.
with TestClient(entry.app) as client:
    pass

from sqlalchemy import inspect, text
from db.schema import engine

if MUTATE == "corrupt":
    # Stamped at head, but the objects the stamp claims are gone. Built by
    # DROPPING them, so the record is genuinely ahead of the schema.
    from migrations.manifest import ACTIVE
    drop = [t for m in ACTIVE for t in m.tables if "fantasystakes" in t]
    # CASCADE on PostgreSQL: the championship tables reference one another
    # (score and correction both carry an FK to freeze) and PostgreSQL refuses
    # to drop a table other objects depend on. SQLite does not enforce it, which
    # is precisely why this suite must run on both.
    suffix = " CASCADE" if engine.dialect.name == "postgresql" else ""
    with engine.begin() as c:
        for t in drop:
            c.execute(text("DROP TABLE IF EXISTS " + t + suffix))
elif MUTATE == "outdated":
    with engine.begin() as c:
        c.execute(text("DELETE FROM schema_migrations WHERE identifier = :i"),
                  {"i": "0006_rc2_championship_correction"})
elif MUTATE == "unstamped":
    with engine.begin() as c:
        c.execute(text("DROP TABLE schema_migrations"))

from migrations.run import pending, verify
problems = verify(engine)
outstanding = [m.identifier for m in pending(engine)]

# READ READINESS WITHOUT RE-RUNNING STARTUP, because that is what production
# does. `TestClient` fires startup handlers on context entry; entering a second
# time would re-run the bootstrap, and OUTSIDE production the bootstrap calls
# `create_all`, which would silently rebuild the very tables this scenario
# dropped. A production process skips the bootstrap entirely once the database
# has tables, so it never heals a schema out from under itself — which is the
# whole reason readiness has to detect the damage rather than repair it.
# No context manager, no startup, one honest measurement.
client = TestClient(entry.app)
r = client.get("/ready")
body = r.json()
if True:
    print("RESULT" + json.dumps({
        "status": r.status_code,
        "ready": body.get("ready"),
        "process": body.get("process"),
        "database": body.get("database"),
        "checks": body.get("checks", {}),
        "verify": problems,
        "pending": outstanding,
        "tables": sorted(inspect(engine).get_table_names()),
    }))
'''


def run_scenario(name: str, mutate: str = "") -> dict:
    url = scenario_url(name)
    env = dict(os.environ)
    env.pop("TEST_DATABASE_URL", None)      # never let the PG harness bind here
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-c",
         _DRIVER % {"root": ROOT, "url": url, "mutate": mutate}],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env)
    lines = [l for l in (proc.stdout or "").splitlines() if l.startswith("RESULT")]
    if not lines:
        raise AssertionError(
            f"scenario {name!r} produced no result\n"
            f"STDOUT:\n{(proc.stdout or '')[-1500:]}\n"
            f"STDERR:\n{(proc.stderr or '')[-1500:]}")
    return json.loads(lines[0][len("RESULT"):])


DIALECT = "PostgreSQL" if IS_POSTGRES else "SQLite"
print("=" * 70)
print(f"B1 SCHEMA READINESS — driven on {DIALECT}")
print("=" * 70)


try:
    # ── 1 · the healthy database ─────────────────────────────────────────────

    section("1 · A correctly bootstrapped database is ready")

    healthy = run_scenario("healthy")
    check("the production entrypoint bootstraps a complete schema",
          all(t in healthy["tables"] for t in (
              "fantasystakes_championship_freeze",
              "fantasystakes_championship_score",
              "fantasystakes_championship_config",
              "fantasystakes_championship_allocation",
              "fantasystakes_championship_distribution_run",
              "fantasystakes_championship_correction",
              "schema_migrations", "ledger_entries")),
          f'{len(healthy["tables"])} tables')
    check("nothing is pending", healthy["pending"] == [], str(healthy["pending"]))
    check("the record is corroborated by the schema",
          healthy["verify"] == [], str(healthy["verify"]))
    check("/ready answers 200", healthy["status"] == 200, str(healthy["status"]))
    check("  · ready", healthy["ready"] is True)
    check("  · the process is reported healthy", healthy["process"] is True)
    check("  · the database is reported usable", healthy["database"] is True)
    check("  · and the schema check is explicit, not implied",
          healthy["checks"].get("schema") == "ok",
          str(healthy["checks"].get("schema")))

    # ── 2 · the corrupt record — the defect this sprint closes ───────────────

    section("2 · A stamp the schema cannot corroborate FAILS CLOSED")

    corrupt = run_scenario("corrupt", "corrupt")
    check("the championship tables really are absent",
          not any(t.startswith("fantasystakes_championship")
                  for t in corrupt["tables"]),
          str([t for t in corrupt["tables"] if t.startswith("fantasystakes")]))
    check("the migration record still claims them — nothing is pending",
          corrupt["pending"] == [], str(corrupt["pending"]))
    check("  · so `pending` alone could never have caught this",
          corrupt["pending"] == [])
    check("verification reports every unbacked claim",
          len(corrupt["verify"]) == 6, str(len(corrupt["verify"])))
    check("/ready answers 503", corrupt["status"] == 503, str(corrupt["status"]))
    check("  · not ready", corrupt["ready"] is False)
    check("  · the schema check names the problem",
          str(corrupt["checks"].get("schema", "")).startswith("unverified:"),
          str(corrupt["checks"].get("schema"))[:120])
    # THE OPERATIONAL DISTINCTION. The code is fine; the schema is not.
    check("  · the PROCESS is still reported healthy",
          corrupt["process"] is True)
    check("  · while the DATABASE is reported unusable",
          corrupt["database"] is False)

    # ── 3 · an outdated database ─────────────────────────────────────────────

    section("3 · A database behind the manifest FAILS CLOSED")

    outdated = run_scenario("outdated", "outdated")
    check("the missing migration is pending",
          outdated["pending"] == ["0006_rc2_championship_correction"],
          str(outdated["pending"]))
    check("/ready answers 503", outdated["status"] == 503, str(outdated["status"]))
    check("  · not ready", outdated["ready"] is False)
    check("  · and it names what is pending",
          "0006_rc2_championship_correction"
          in str(outdated["checks"].get("migrations", "")),
          str(outdated["checks"].get("migrations")))
    check("  · the database is reported unusable", outdated["database"] is False)

    # ── 4 · an unstamped database ────────────────────────────────────────────

    section("4 · A database with no migration record FAILS CLOSED")

    unstamped = run_scenario("unstamped", "unstamped")
    check("every manifest migration reads as pending",
          len(unstamped["pending"]) == 6, str(len(unstamped["pending"])))
    check("/ready answers 503", unstamped["status"] == 503,
          str(unstamped["status"]))
    check("  · not ready", unstamped["ready"] is False)
    check("  · the database is reported unusable", unstamped["database"] is False)
    # An empty record claims nothing, so it can contradict nothing. `pending` is
    # what refuses this state, and that separation is deliberate.
    check("  · verification stays silent — an empty record makes no claim",
          unstamped["verify"] == [], str(unstamped["verify"]))

    # ── 5 · the manifest describes itself completely ─────────────────────────

    section("5 · The manifest can actually be verified")

    from migrations.manifest import ACTIVE

    check("every active migration is verifiable by table or column",
          all(m.tables or m.columns for m in ACTIVE),
          ", ".join(m.identifier for m in ACTIVE if not (m.tables or m.columns)))

    claimed = {t for m in ACTIVE for t in m.tables}
    check("every RC2 championship table is claimed by some migration",
          {t for t in healthy["tables"] if t.startswith("fantasystakes_championship")}
          <= claimed,
          str({t for t in healthy["tables"]
               if t.startswith("fantasystakes_championship")} - claimed))

    # A migration claiming an object nobody builds would fail readiness on a
    # healthy database — which section 1 already proves cannot happen.
    check("no migration claims an object the healthy schema lacks",
          healthy["verify"] == [])

    # ── 6 · readiness cannot pass by failing to look ─────────────────────────

    section("6 · An unanswerable schema question is not a pass")

    import inspect as _inspect

    import api.main as _main

    src = _inspect.getsource(_main.ready)
    body = src.split("except Exception:")[-1]
    check("the schema check's exception path sets ready False",
          "ready_ = False" in body,
          "a readiness check that cannot determine the schema must fail closed")
    check("  · and reports the state as unknown rather than ok",
          '"unknown"' in body)

finally:
    drop_scenarios()
    import shutil

    shutil.rmtree(_TMP, ignore_errors=True)


print("\n" + "=" * 70)
if FAIL:
    print(f"B1 SCHEMA READINESS ({DIALECT}) — {len(FAIL)} FAILED")
    for f in FAIL:
        print(f"  · {f}")
    sys.exit(1)
print(f"PASS: B1 schema readiness certified on {DIALECT}")
