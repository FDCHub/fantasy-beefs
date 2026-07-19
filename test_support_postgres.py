"""
test_support_postgres.py — disposable Postgres test-DB harness (FR-8.7 §6a).

INFRASTRUCTURE, NOT A TEST. This module has no assertions; the Postgres
lifecycle tests import it. It provides a SAFELY-GUARDED setup for a disposable
Postgres test database, because the settlement lifecycle code issues
`SELECT ... FOR UPDATE`, which SQLite cannot parse — those scenarios can only run
on real Postgres.

No pytest, no testcontainers. Plain standalone-script convention, using the
already-installed psycopg2 driver implicitly via SQLAlchemy's `postgresql://`
URL (create_engine routes to psycopg2-binary; no direct psycopg2 import needed).

TEST_DATABASE_URL must point at an EMPTY, disposable database. Setup REFUSES a
non-empty DB: ownership of every table must be unambiguous, so teardown can
safely drop the full schema it created. The harness creates all tables on setup
and drops them on teardown — it will not co-exist with pre-existing tables.

USAGE (from a lifecycle test — call setup FIRST, before importing db.schema):

    from test_support_postgres import setup_postgres_test_db

    tdb = setup_postgres_test_db()          # guards, binds engine, creates tables
    # ... only now import models / engines that read db.schema ...
    from db.schema import Bet, League, Matchup, Wallet
    from betting.settlement_engine import settle_week, recover_week

    tdb.reset()                              # clean slate before each scenario
    with tdb.SessionLocal() as db:
        ...
    tdb.teardown()                           # drop the schema this harness created

The operator must export TEST_DATABASE_URL pointing at a DEDICATED, DISPOSABLE,
EMPTY Postgres database whose name contains "_test", e.g.:

    export TEST_DATABASE_URL="postgresql://localhost:5432/fantasy_test"
    python test_recover_week_lifecycle.py

SAFETY: every guard RAISES (never silently skips). A missing TEST_DATABASE_URL
is a loud failure. TEST_DATABASE_URL is NEVER inferred from DATABASE_URL, and is
refused if it resolves to the same host+port+database as the live DATABASE_URL.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

# NOTE: db.schema / ledger are imported INSIDE setup_postgres_test_db(), AFTER
# DATABASE_URL is set — never at module top. db.schema builds its engine from
# DATABASE_URL at import time, so importing it here would bind to the wrong DB.

# Host substrings that unmistakably indicate Railway (prod/dev) — refused.
_FORBIDDEN_HOST_PATTERNS = ("railway", "rlwy", "proxy.rlwy")

# The test database name must contain this substring, or setup refuses to run.
_REQUIRED_DBNAME_MARKER = "_test"

# Postgres default port, used when a URL omits an explicit port.
_DEFAULT_PG_PORT = 5432


def _destination(url_str: str) -> tuple[str, int, str]:
    """Normalize a DB URL to a destination tuple (host, port, database),
    ignoring scheme spelling, credentials, and query string. postgres:// is
    rewritten to postgresql:// first so the driver-prefix difference doesn't
    matter; host is lowercased; a missing port defaults to 5432."""
    normalized = url_str.replace("postgres://", "postgresql://", 1)
    u = make_url(normalized)
    host = (u.host or "").lower()
    port = u.port or _DEFAULT_PG_PORT
    database = u.database or ""
    return (host, port, database)


class PostgresTestDB:
    """Handle returned by setup_postgres_test_db(). Carries the bound engine and
    SessionLocal, plus reset()/teardown() over the tables this harness created
    (the db.schema models + the ledger_entries table). teardown()'s safety rests
    on setup having proven the test DB EMPTY before creating anything."""

    def __init__(self, engine, SessionLocal, model_base, ledger_base):
        self.engine = engine
        self.SessionLocal = SessionLocal
        self._model_base = model_base
        self._ledger_base = ledger_base

    def _created_table_names(self) -> list[str]:
        """Names of the tables this harness created — model tables from
        db.schema's Base plus ledger_entries from the ledger's own Base."""
        names = [t.name for t in self._model_base.metadata.sorted_tables]
        names += [t.name for t in self._ledger_base.metadata.sorted_tables]
        return names

    def reset(self) -> None:
        """Between-scenario clean slate: TRUNCATE every harness-created table and
        RESTART IDENTITY (so SERIAL ids start fresh each scenario). CASCADE lets
        the truncate ignore FK ordering. Keeps the schema intact — far faster
        than drop+recreate, and touches only the tables we made."""
        names = self._created_table_names()
        if not names:
            return
        joined = ", ".join(names)
        with self.engine.begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE"))

    def teardown(self) -> None:
        """Drop the full schema this harness created (ledger first, then models).
        This is safe to run as a full drop_all ONLY because setup_postgres_test_db()
        proved the test database EMPTY before creating anything — so every table
        present is harness-created. The safety comes from that empty-DB
        precondition, not from drop_all being selective. metadata's drop_all
        resolves intra-metadata FK ordering; the two metadatas are independent
        (no cross-FKs), so their relative order is irrelevant."""
        self._ledger_base.metadata.drop_all(self.engine)
        self._model_base.metadata.drop_all(self.engine)


def setup_postgres_test_db() -> PostgresTestDB:
    """Apply all safety guards, bind db.schema's engine to TEST_DATABASE_URL,
    verify the DB is EMPTY, create every table (models + ledger), and return a
    PostgresTestDB handle.

    Guards (all raise RuntimeError, never skip):
      1. TEST_DATABASE_URL must be set and non-empty. Never falls back to
         DATABASE_URL.
      2. The URL must be a Postgres URL (postgresql:// after normalization).
      3. The database name must contain "_test".
      4. The host must not look like Railway (railway / rlwy / proxy.rlwy).
      5. TEST_DATABASE_URL must not resolve to the same destination
         (host+port+database) as the live DATABASE_URL.
      6. After binding, the test database must be EMPTY (no pre-existing tables).
    Only after every guard passes does it set DATABASE_URL and import db.schema.
    """
    test_url = os.environ.get("TEST_DATABASE_URL", "").strip()

    # Guard 1 — TEST_DATABASE_URL required, no DATABASE_URL fallback.
    if not test_url:
        raise RuntimeError(
            "The Postgres test suite requires TEST_DATABASE_URL to be set to a "
            "dedicated, disposable, EMPTY Postgres database (name containing "
            "'_test'). It is unset/empty. This harness will NOT fall back to "
            "DATABASE_URL — set TEST_DATABASE_URL explicitly, e.g. "
            "postgresql://localhost:5432/fantasy_test"
        )

    # Normalize the legacy postgres:// prefix exactly as db.schema does, so the
    # scheme check and parsing below see the same form the engine will bind to.
    normalized = test_url.replace("postgres://", "postgresql://", 1)
    parsed = urlparse(normalized)
    dbname = (parsed.path or "").lstrip("/")
    host = (parsed.hostname or "").lower()

    # Guard 2 — must be a Postgres URL. The lifecycle tests need FOR UPDATE /
    # real transactions; a sqlite:// (or anything else) is refused.
    if not normalized.startswith("postgresql://"):
        raise RuntimeError(
            f"TEST_DATABASE_URL must be a Postgres URL (postgresql://…); got scheme "
            f"{parsed.scheme!r}. The lifecycle tests cannot run on any other backend."
        )

    # Guard 3 — the database name must contain "_test". This is the primary
    # can't-be-prod safety rule: a real database (e.g. 'railway', 'fantasy')
    # will not match, so the harness refuses to create/drop/truncate in it.
    if _REQUIRED_DBNAME_MARKER not in dbname:
        raise RuntimeError(
            f"Refusing to use database {dbname!r}: its name must contain "
            f"'{_REQUIRED_DBNAME_MARKER}' to be accepted as a disposable test "
            f"database (e.g. 'fantasy_test'). This harness TRUNCATEs and DROPs "
            f"tables — it will only ever do so against a '_test'-named database."
        )

    # Guard 4 — refuse Railway (prod/dev) hosts outright.
    if any(pattern in host for pattern in _FORBIDDEN_HOST_PATTERNS):
        raise RuntimeError(
            f"Refusing to use host {host!r}: it matches a forbidden Railway host "
            f"pattern ({', '.join(_FORBIDDEN_HOST_PATTERNS)}). The Postgres test "
            f"harness must never point at a Railway (production/dev) database."
        )

    # Guard 5 — refuse if TEST_DATABASE_URL resolves to the SAME destination
    # (host+port+database) as the currently-live DATABASE_URL, regardless of how
    # each is spelled (scheme prefix, credentials, casing, default vs explicit
    # port, query string). Destination-only comparison.
    current_database_url = os.environ.get("DATABASE_URL", "").strip()
    if current_database_url:
        test_dest = _destination(test_url)
        # Fail closed — a set-but-unparseable live URL means separation from the
        # test DB cannot be established, so a table-dropping harness must HALT
        # rather than proceed.
        try:
            current_dest = _destination(current_database_url)
        except Exception as exc:
            raise RuntimeError(
                "Refusing to run: the existing DATABASE_URL could not be parsed, so the "
                "harness cannot prove TEST_DATABASE_URL targets a database separate from "
                "the live one. A table-dropping harness must refuse when separation cannot "
                "be established."
            ) from exc
        if test_dest == current_dest:
            raise RuntimeError(
                "Refusing to run: TEST_DATABASE_URL resolves to the same database "
                f"destination as the live DATABASE_URL {test_dest!r} (host+port+database "
                "match, ignoring credentials/spelling). The test harness must target a "
                "SEPARATE disposable database."
            )

    # Guards passed — bind db.schema's engine to the test DB, THEN import it.
    os.environ["DATABASE_URL"] = test_url

    from db.schema import Base, engine, SessionLocal
    from ledger.ledger import create_ledger_table, _LedgerBase

    # Loud ordering check: if db.schema was already imported earlier in this
    # process (before setup ran), its engine is bound to the wrong DB and this
    # is the last chance to catch it. engine.url.database is the bound dbname.
    bound_dbname = engine.url.database or ""
    if _REQUIRED_DBNAME_MARKER not in bound_dbname:
        raise RuntimeError(
            f"db.schema.engine is bound to database {bound_dbname!r}, not a "
            f"'_test' database. db.schema was almost certainly imported before "
            f"setup_postgres_test_db() ran. Import test_support_postgres and call "
            f"setup_postgres_test_db() FIRST, before importing anything from "
            f"db.schema or any module that imports it."
        )

    # Guard 6 — the test database must be EMPTY before we create anything, so
    # that every table present afterwards is unambiguously harness-created and
    # teardown's full drop_all is safe. Inspect the NOW-BOUND test engine.
    preexisting = set(inspect(engine).get_table_names())
    if preexisting:
        raise RuntimeError(
            "Refusing to run: the TEST_DATABASE_URL database is NOT empty — it "
            f"already contains {len(preexisting)} table(s): "
            f"{sorted(preexisting)}. This harness requires an EMPTY disposable "
            "database so that ownership of every table is unambiguous and "
            "teardown can safely drop the full schema it created. Point "
            "TEST_DATABASE_URL at a fresh, empty database."
        )

    # Empty DB confirmed — create the full schema: db.schema models + ledger.
    Base.metadata.create_all(engine)
    create_ledger_table()

    return PostgresTestDB(engine, SessionLocal, Base, _LedgerBase)


# ── Manual smoke check (operator convenience — NOT part of any test run) ──────
# Running this file directly exercises the guards + setup/reset/teardown against
# whatever TEST_DATABASE_URL points at, so an operator can validate their test
# database wiring. It does nothing during import or py_compile.
if __name__ == "__main__":
    print("test_support_postgres.py — manual smoke check")
    tdb = setup_postgres_test_db()
    print(f"  bound engine     : {tdb.engine.url}")
    print(f"  created tables   : {len(tdb._created_table_names())}")
    tdb.reset()
    print("  reset()          : OK (TRUNCATE … RESTART IDENTITY CASCADE)")
    tdb.teardown()
    print("  teardown()       : OK (dropped the harness-created schema)")
    print("  SMOKE CHECK PASSED")
