#!/usr/bin/env python3
"""
test_pg_cert1_migrations.py — PG-CERT-1 · the PostgreSQL launch schema.

WHAT THIS CERTIFIES, AND WHY IT COULD NOT BE CERTIFIED BEFORE.

Every package since WP3D.1 has carried the same disclosure: a migration was
written, its PostgreSQL branch was asserted to EXIST, and nobody had run it,
because no PostgreSQL was reachable. SQLite creating a table proves nothing
about PostgreSQL's ALTER, its foreign keys, its CHECK constraints or its
transaction semantics — and the three migrations this product's launch depends
on all turn on exactly those.

A real PostgreSQL engine runs everything below. Nothing here is inferred from
source, and nothing is satisfied by SQLite.

── THE TWO PATHS, AND WHY BOTH ────────────────────────────────────────────

    PATH A — FRESH       `Base.metadata.create_all`, which is what
                         `api/main.py` runs at startup. This is how a new
                         deployment gets its schema.

    PATH B — UPGRADE     a pre-change baseline, then the migrations. This is
                         how an EXISTING database reaches the same place.

Both are real production paths and they must converge, or a deployment's schema
depends on how old it is. §9 below compares them column by column and constraint
by constraint.

── SAFETY ─────────────────────────────────────────────────────────────────

Every database this suite touches is created by it, named with the `_test`
marker the harnesses require, and dropped afterwards. It refuses to run against
anything it did not create. No production data, no real credential, and no
token value is printed — the encryption fixtures are generated per run and the
"tokens" are obvious fakes.

    TEST_DATABASE_URL=postgresql://.../fantasy_test python test_pg_cert1_migrations.py
"""

from __future__ import annotations

import os
import re
import sys
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


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


# ── 0 · the target, guarded ──────────────────────────────────────────────────

_section("0 · PostgreSQL target")

_ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if not _ADMIN_URL:
    print("  [FAIL] TEST_DATABASE_URL is not set")
    print("\nPG-CERT-1 MIGRATIONS — cannot run without a PostgreSQL target")
    sys.exit(2)

_url = make_url(_ADMIN_URL)
if not _url.drivername.startswith("postgresql"):
    print(f"  [FAIL] TEST_DATABASE_URL is not PostgreSQL ({_url.drivername})")
    sys.exit(2)
# THE SAME MARKER EVERY OTHER HARNESS REQUIRES. A database without `_test` in
# its name is not one this suite will create tables in or drop.
if "_test" not in (_url.database or ""):
    print("  [FAIL] the admin database name must contain '_test'")
    sys.exit(2)
for forbidden in ("railway", "rlwy"):
    if forbidden in (_url.host or ""):
        print(f"  [FAIL] refusing a {forbidden} host")
        sys.exit(2)

# REDACTED FOR THE REPORT. The host class and the driver are the facts worth
# recording; the password is not, and is never rendered.
_admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
with _admin.connect() as c:
    _version = c.execute(text("show server_version")).scalar()
print(f"  server            PostgreSQL {_version}")
print(f"  driver            {_url.drivername}")
print(f"  host class        {'localhost' if _url.host in ('127.0.0.1', 'localhost') else 'explicit test URL'}")
print(f"  admin database    …{(_url.database or '')[-12:]}")
_assert("a real PostgreSQL engine is in use", True, f"{_version}")

_CREATED: list[str] = []


def _new_db(tag: str) -> str:
    """A private, disposable database for one scenario."""
    name = f"pgcert1_{tag}_{uuid.uuid4().hex[:8]}_test"
    with _admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    _CREATED.append(name)
    # `str(URL)` MASKS THE PASSWORD as `***` — a SQLAlchemy safety default that
    # is exactly right for logging and exactly wrong for handing a child
    # process something to connect with. Rendered unmasked here, used only as a
    # subprocess argument, and never printed: the report shows the host class
    # and the database suffix, never this string.
    return _url.set(database=name).render_as_string(hide_password=False)


def _drop_all() -> None:
    for name in _CREATED:
        try:
            with _admin.connect() as c:
                c.execute(text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"),
                    {"n": name})
                c.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        except Exception:                       # pragma: no cover - cleanup
            pass


def _describe(engine) -> dict:
    """The structural facts two schemas must agree on.

    DELIBERATELY NOT A BYTE COMPARISON. Index names, constraint names and
    column order legitimately differ between a `create_all` and a hand-written
    ALTER; what must NOT differ is which tables exist, which columns they have,
    what type and nullability those columns are, and which keys and checks
    constrain them.
    """
    insp = inspect(engine)
    out: dict = {"tables": sorted(insp.get_table_names()), "columns": {},
                 "pk": {}, "fk": {}, "unique": {}, "check": {}}
    for table in out["tables"]:
        out["columns"][table] = {
            c["name"]: (str(c["type"]).upper().split("(")[0], bool(c["nullable"]))
            for c in insp.get_columns(table)}
        out["pk"][table] = sorted(
            insp.get_pk_constraint(table).get("constrained_columns") or [])
        out["fk"][table] = sorted(
            (tuple(sorted(f["constrained_columns"])), f["referred_table"])
            for f in insp.get_foreign_keys(table))
        out["unique"][table] = sorted(
            tuple(sorted(u["column_names"] or []))
            for u in insp.get_unique_constraints(table))
        try:
            out["check"][table] = sorted(
                (c.get("name") or "") for c in insp.get_check_constraints(table))
        except Exception:                        # pragma: no cover - dialect
            out["check"][table] = []
    return out


try:
    # ── 1 · migration inventory ──────────────────────────────────────────────

    _section("1 · Migration inventory and ordering")

    import pathlib

    _migrations = sorted(
        [str(p) for p in pathlib.Path("migrations").glob("*.py")]
        + [str(p) for p in pathlib.Path("db/migrations").glob("*.py")])
    _with_upgrade = [m for m in _migrations
                     if re.search(r"^def upgrade\(", _read(m), re.M)]
    _assert("the migration set was enumerated", len(_migrations) > 20,
            f"{len(_migrations)} scripts across migrations/ and db/migrations/")

    # THE ORDERING FINDING, RECORDED RATHER THAN PAPERED OVER.
    #
    # There is no manifest and no runner: 28 scripts in two directories, of
    # which only a minority expose a callable `upgrade()` and the rest are
    # standalone `__main__` scripts. Writing a manifest that CLAIMED to sequence
    # all of them would assert an order this package has not verified for
    # nineteen of them, which is worse than recording that none exists.
    #
    # WHAT MAKES THAT SAFE FOR LAUNCH is the fact certified in §2 and §3: a
    # FRESH deployment does not run migrations at all. `api/main.py` calls
    # `Base.metadata.create_all`, which produces the complete schema in one
    # step. The migrations exist to carry an EXISTING database forward, and the
    # three this workstream owns are certified individually below.
    # THE FINDING THIS ASSERTION RECORDED IS NOW CLOSED.
    #
    # PG-CERT-1 found no manifest and deliberately did not invent one, because
    # asserting an order for nineteen unverified scripts would have been worse
    # than recording that none existed. PROD-HARDEN-1 closed it properly: an
    # ordered ACTIVE registry, a HISTORICAL list of what must NOT run, and a
    # runner that records what it applied. So this now pins the resolution
    # rather than the gap.
    _assert("an ordered migration manifest now exists",
            pathlib.Path("migrations/manifest.py").exists()
            and pathlib.Path("migrations/run.py").exists(),
            "closed by PROD-HARDEN-1")
    _assert(f"{len(_with_upgrade)} of {len(_migrations)} expose a callable "
            f"upgrade()", True, "reported")
    _assert("the launch-critical three all do",
            {"migrations\\add_yahoo_identity.py".replace("\\", os.sep),
             "migrations\\add_provider_grants.py".replace("\\", os.sep)}
            <= set(_with_upgrade),
            ", ".join(m for m in _with_upgrade if "add_" in m))

    # ── 2 · PATH A — fresh ───────────────────────────────────────────────────

    _section("2 · PATH A — a fresh database through the shipped bootstrap")

    _assert("the shipped startup delegates fresh schema ownership to the "
            "migration bootstrap",
            "bootstrap_fresh(engine)" in _read("api", "main.py"))

    # THE DEFECT THIS PACKAGE FOUND, PINNED SO IT CANNOT RETURN.
    #
    # `ledger_entries` lives on the Ledger's own declarative base, so
    # `db.schema.Base.metadata.create_all` does not create it. Measured on
    # PostgreSQL: a fresh database built by the startup hook came up with every
    # application table and NO ledger table — a deployment that would start,
    # serve, and fail on the first Credit posted. Existing deployments were
    # never exposed because a migration created it years ago; only a brand-new
    # one is, which is precisely what a launch is.
    # THE WHOLE FUNCTION, not a fixed slice of it. PROD-HARDEN-1 added the
    # production-skip branch ahead of the bootstrap, which pushed
    # `create_ledger_table()` past a 1600-character window and made this read
    # as a regression when nothing had regressed.
    _startup = (_read("api", "main.py").split("def _create_tables()")[1]
                .split(chr(10) + "@app.")[0])
    _assert("and the startup hook ALSO creates the Ledger's own table",
            "create_ledger_table()" in _startup,
            "ledger_entries is on a separate declarative base")

    fresh_url = _new_db("fresh")
    _FRESH_DRIVER = r"""
import os, sys
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r
from api.main import _create_tables
_create_tables()
print("CREATED")
"""
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-c", _FRESH_DRIVER % {"root": ROOT, "url": fresh_url}],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    _assert("the fresh schema builds on PostgreSQL", "CREATED" in proc.stdout,
            (proc.stderr or "")[-260:])

    _READY_DRIVER = r"""
import os, sys
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r
from fastapi.testclient import TestClient
from api.main import app
with TestClient(app) as client:
    response = client.get("/ready")
    print("READY_STATUS=" + str(response.status_code))
    print("READY_BODY=" + response.text)
"""
    ready_proc = subprocess.run(
        [sys.executable, "-c",
         _READY_DRIVER % {"root": ROOT, "url": fresh_url}],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    _assert("the real application reports the fresh schema ready",
            ready_proc.returncode == 0
            and "READY_STATUS=200" in ready_proc.stdout
            and '"schema":"ok"' in ready_proc.stdout,
            ((ready_proc.stderr or "") + (ready_proc.stdout or ""))[-600:])

    fresh_engine = create_engine(fresh_url)
    fresh = _describe(fresh_engine)
    _assert("it produced the full table set", len(fresh["tables"]) > 40,
            f"{len(fresh['tables'])} tables")
    championship_tables = (
        "fantasystakes_championship_freeze",
        "fantasystakes_championship_score",
        "fantasystakes_championship_config",
        "fantasystakes_championship_allocation",
        "fantasystakes_championship_distribution_run",
        "fantasystakes_championship_correction",
    )
    for required in ("users", "leagues", "provider_grants", "ledger_entries",
                     *championship_tables):
        _assert(f"  · {required} exists", required in fresh["tables"])

    # ── 3 · PATH B — upgrade ─────────────────────────────────────────────────

    _section("3 · PATH B — a pre-change baseline carried forward by migrations")

    from migrations.run import (applied_identifiers, repair_false_stamps,
                                verify)
    from migrations.manifest import ACTIVE

    applied = applied_identifiers(fresh_engine)
    _assert("fresh bootstrap records the current migration head only after "
            "building its physical schema",
            applied == {m.identifier for m in ACTIVE}, str(sorted(applied)))
    _assert("fresh bootstrap schema corroborates every applied migration",
            verify(fresh_engine) == [], str(verify(fresh_engine)))

    indexes = {i["name"] for table in championship_tables
               for i in inspect(fresh_engine).get_indexes(table)}
    _assert("fresh championship snapshot index exists",
            "ix_fs_champ_score_league_season" in indexes, str(sorted(indexes)))
    _assert("fresh championship correction index exists",
            "ix_fs_champ_correction_league_season" in indexes,
            str(sorted(indexes)))

    with fresh_engine.begin() as connection:
        connection.execute(text(
            "DROP TABLE fantasystakes_championship_distribution_run"))
    false_stamp = verify(fresh_engine)
    _assert("a false stamp is detected from physical schema, not pending count",
            false_stamp == [
                "0005_rc2_championship_distribution: table "
                "fantasystakes_championship_distribution_run missing"],
            str(false_stamp))
    repaired = repair_false_stamps(fresh_engine)
    _assert("the explicit false-stamp repair reruns only the affected migration",
            len(repaired) == 1
            and "0005_rc2_championship_distribution" in repaired[0],
            str(repaired))
    _assert("false-stamp repair restores a verifiable physical schema",
            verify(fresh_engine) == []
            and "fantasystakes_championship_distribution_run"
            in inspect(fresh_engine).get_table_names())

    upgrade_url = _new_db("upgrade")

    # A GENUINE PRE-CHANGE BASELINE. `users` without the Yahoo columns and with
    # `hashed_password` NOT NULL, `leagues` without the credential owner, and
    # rows in both — so the migrations are applied to a database that actually
    # has something to lose.
    _BASELINE = """
    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        email VARCHAR NOT NULL UNIQUE,
        hashed_password VARCHAR NOT NULL,
        team_id INTEGER,
        role VARCHAR NOT NULL DEFAULT 'gm',
        is_active INTEGER NOT NULL DEFAULT 1,
        buy_in_paid INTEGER NOT NULL DEFAULT 0,
        stripe_account_id VARCHAR,
        created_at TIMESTAMP,
        last_login_at TIMESTAMP);
    CREATE TABLE leagues (
        id SERIAL PRIMARY KEY,
        name VARCHAR NOT NULL,
        season INTEGER NOT NULL,
        provider VARCHAR,
        provider_league_key VARCHAR,
        provider_current_week INTEGER);
    INSERT INTO users (email, hashed_password, role)
        VALUES ('legacy@example.com', 'bcrypt$legacyhash', 'commissioner');
    INSERT INTO leagues (name, season) VALUES ('Legacy League', 2025);
    """
    up_engine = create_engine(upgrade_url, isolation_level="AUTOCOMMIT")
    with up_engine.connect() as c:
        for stmt in [s for s in _BASELINE.split(";") if s.strip()]:
            c.execute(text(stmt))
    _assert("a pre-change PostgreSQL baseline was built", True,
            "users NOT NULL password, leagues without credential owner, rows in both")

    _MIGRATE_DRIVER = r"""
import os, sys, json
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r
import importlib
out = {}
for name in ("migrations.add_yahoo_identity", "migrations.add_provider_grants"):
    m = importlib.import_module(name)
    out[name] = {"first": m.upgrade(), "second": m.upgrade()}
print("RESULT" + json.dumps(out))
"""
    proc = subprocess.run(
        [sys.executable, "-c",
         _MIGRATE_DRIVER % {"root": ROOT, "url": upgrade_url}],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    line = [l for l in (proc.stdout or "").splitlines() if l.startswith("RESULT")]
    _assert("both launch migrations ran on PostgreSQL", bool(line),
            (proc.stderr or "")[-300:])

    import json

    ran = json.loads(line[0][len("RESULT"):]) if line else {}

    # ── 4 · Yahoo identity migration on PostgreSQL ───────────────────────────

    _section("4 · §8 · Yahoo identity migration — PostgreSQL")

    upgraded = _describe(create_engine(upgrade_url))
    ucols = upgraded["columns"].get("users", {})
    _assert("auth_provider was added", "auth_provider" in ucols)
    _assert("provider_subject was added", "provider_subject" in ucols)
    _assert("both are NULLABLE, so existing rows stay valid",
            ucols.get("auth_provider", ("", False))[1] is True
            and ucols.get("provider_subject", ("", False))[1] is True)
    _assert("hashed_password was RELAXED to nullable on PostgreSQL",
            ucols.get("hashed_password", ("", False))[1] is True,
            "this is the ALTER SQLite could never prove")
    _assert("the legacy password column still exists",
            "hashed_password" in ucols)

    with create_engine(upgrade_url).connect() as c:
        survivor = c.execute(text(
            "SELECT email, hashed_password, role FROM users")).fetchone()
    _assert("the existing user survived the migration untouched",
            survivor is not None and survivor[0] == "legacy@example.com"
            and survivor[1] == "bcrypt$legacyhash"
            and survivor[2] == "commissioner",
            str(survivor[0]) if survivor else "gone")

    # THE UNIQUENESS RULE, EXERCISED AGAINST REAL POSTGRESQL rather than read
    # off a CREATE INDEX statement.
    ins = create_engine(upgrade_url, isolation_level="AUTOCOMMIT")
    with ins.connect() as c:
        c.execute(text("INSERT INTO users (email, hashed_password, "
                       "auth_provider, provider_subject, role) VALUES "
                       "('a@example.com', NULL, 'yahoo', 'sub-A', 'gm')"))
        c.execute(text("INSERT INTO users (email, hashed_password, "
                       "auth_provider, provider_subject, role) VALUES "
                       "('b@example.com', NULL, 'yahoo', 'sub-B', 'gm')"))
    _assert("a Yahoo-created account may have a NULL password", True,
            "inserted with hashed_password NULL")

    duplicate_refused = False
    try:
        with ins.connect() as c:
            c.execute(text("INSERT INTO users (email, hashed_password, "
                           "auth_provider, provider_subject, role) VALUES "
                           "('c@example.com', NULL, 'yahoo', 'sub-A', 'gm')"))
    except Exception:
        duplicate_refused = True
    _assert("a DUPLICATE Yahoo subject is refused by the database",
            duplicate_refused, "unique (auth_provider, provider_subject)")

    # SAME EMAIL, DIFFERENT SUBJECT stays distinguishable — the property the
    # AUTH1 placeholder-address logic exists to preserve.
    with ins.connect() as c:
        rows = c.execute(text(
            "SELECT provider_subject FROM users WHERE auth_provider='yahoo' "
            "ORDER BY provider_subject")).fetchall()
    _assert("two distinct subjects coexist",
            [r[0] for r in rows] == ["sub-A", "sub-B"], str([r[0] for r in rows]))

    # NULLs DO NOT COLLIDE — the legacy row and any future one.
    nulls_ok = True
    try:
        with ins.connect() as c:
            c.execute(text("INSERT INTO users (email, hashed_password, role) "
                           "VALUES ('n1@example.com', 'h', 'gm')"))
            c.execute(text("INSERT INTO users (email, hashed_password, role) "
                           "VALUES ('n2@example.com', 'h', 'gm')"))
    except Exception:
        nulls_ok = False
    _assert("two NULL-subject rows do not collide", nulls_ok)

    _assert("the identity migration is idempotent on PostgreSQL",
            any("nothing to do" in s or "already" in s
                for s in ran.get("migrations.add_yahoo_identity", {})
                            .get("second", [])),
            "; ".join(ran.get("migrations.add_yahoo_identity", {})
                      .get("second", []))[:110])

    # ── 5 · provider-grant migration on PostgreSQL ───────────────────────────

    _section("5 · §9 · Provider-grant migration — PostgreSQL")

    _assert("provider_grants exists", "provider_grants" in upgraded["tables"])
    gcols = upgraded["columns"].get("provider_grants", {})
    for col in ("user_id", "provider", "provider_subject",
                "access_token_sealed", "refresh_token_sealed", "expires_at",
                "granted_scope", "status", "token_version", "created_at",
                "updated_at", "last_refresh_at", "last_error_code",
                "last_error_at"):
        _assert(f"  · {col}", col in gcols)
    _assert("expires_at is a real TIMESTAMP type",
            "TIMESTAMP" in gcols.get("expires_at", ("", True))[0],
            gcols.get("expires_at", ("?",))[0])
    _assert("the sealed columns are TEXT, not a bounded VARCHAR",
            gcols.get("access_token_sealed", ("", True))[0] == "TEXT"
            and gcols.get("refresh_token_sealed", ("", True))[0] == "TEXT")
    _assert("unique (user_id, provider) exists",
            ("provider", "user_id") in upgraded["unique"]["provider_grants"]
            or ("user_id", "provider") in upgraded["unique"]["provider_grants"],
            str(upgraded["unique"]["provider_grants"]))
    _assert("a foreign key to users exists",
            any(ref == "users" for _cols, ref
                in upgraded["fk"]["provider_grants"]),
            str(upgraded["fk"]["provider_grants"]))

    lcols = upgraded["columns"].get("leagues", {})
    _assert("leagues.provider_credential_user_id was added",
            "provider_credential_user_id" in lcols)
    _assert("  · and is nullable", lcols.get(
        "provider_credential_user_id", ("", False))[1] is True)
    _assert("  · with a foreign key to users on PostgreSQL",
            any(cols == ("provider_credential_user_id",) and ref == "users"
                for cols, ref in upgraded["fk"]["leagues"]),
            str(upgraded["fk"]["leagues"]))
    _assert("leagues.provider_credential_assigned_at was added",
            "provider_credential_assigned_at" in lcols)
    _assert("  · as a TIMESTAMP",
            "TIMESTAMP" in lcols.get(
                "provider_credential_assigned_at", ("", True))[0])

    _assert("the grant migration is idempotent on PostgreSQL",
            any("already exists" in s or "nothing to do" in s
                for s in ran.get("migrations.add_provider_grants", {})
                            .get("second", [])),
            "; ".join(ran.get("migrations.add_provider_grants", {})
                      .get("second", []))[:110])

    # ── 6 · the constraints, exercised ───────────────────────────────────────

    _section("6 · §9 · Grant constraints and foreign keys, enforced by PostgreSQL")

    with ins.connect() as c:
        uid = c.execute(text(
            "SELECT id FROM users WHERE email='a@example.com'")).scalar()
        c.execute(text(
            "INSERT INTO provider_grants (user_id, provider, provider_subject,"
            " access_token_sealed, status, token_version) VALUES "
            "(:u,'yahoo','sub-A','v1.active.NONCE.CIPHERTEXT','active',1)"),
            {"u": uid})
    _assert("a valid grant row inserts", True)

    def _refused(sql: str, params: dict | None = None) -> bool:
        try:
            with ins.connect() as c:
                c.execute(text(sql), params or {})
            return False
        except Exception:
            return True

    _assert("a DUPLICATE grant for the same (user, provider) is refused",
            _refused("INSERT INTO provider_grants (user_id, provider, "
                     "provider_subject, status, token_version) VALUES "
                     "(:u,'yahoo','sub-A','active',1)", {"u": uid}))
    _assert("an ORPHAN user_id is refused by the foreign key",
            _refused("INSERT INTO provider_grants (user_id, provider, "
                     "provider_subject, status, token_version) VALUES "
                     "(999999,'yahoo','sub-Z','active',1)"))
    _assert("an INVALID status is refused by the CHECK constraint",
            _refused("INSERT INTO provider_grants (user_id, provider, "
                     "provider_subject, status, token_version) VALUES "
                     "(:u,'espn','sub-A','banana',1)", {"u": uid}))
    _assert("a valid non-active status is accepted",
            not _refused("INSERT INTO provider_grants (user_id, provider, "
                         "provider_subject, status, token_version) VALUES "
                         "(:u,'espn','sub-A','reconnect_required',1)",
                         {"u": uid}))

    _assert("a NULL credential owner is allowed on a league",
            not _refused("UPDATE leagues SET provider_credential_user_id=NULL"))
    _assert("a NONEXISTENT credential owner is refused",
            _refused("UPDATE leagues SET provider_credential_user_id=999999"))
    with ins.connect() as c:
        c.execute(text("UPDATE leagues SET provider_credential_user_id=:u, "
                       "provider_credential_assigned_at=NOW()"), {"u": uid})
        owner, when = c.execute(text(
            "SELECT provider_credential_user_id, "
            "provider_credential_assigned_at FROM leagues")).fetchone()
    _assert("an assignment persists with its timestamp",
            owner == uid and when is not None, f"owner={owner}")

    # REASSIGNMENT, and the previous owner's grant is untouched by it.
    with ins.connect() as c:
        other = c.execute(text(
            "SELECT id FROM users WHERE email='b@example.com'")).scalar()
        c.execute(text("UPDATE leagues SET provider_credential_user_id=:u"),
                  {"u": other})
        now_owner = c.execute(text(
            "SELECT provider_credential_user_id FROM leagues")).scalar()
        grants_intact = c.execute(text(
            "SELECT count(*) FROM provider_grants WHERE user_id=:u"),
            {"u": uid}).scalar()
    _assert("reassignment persists", now_owner == other)
    _assert("and the previous owner's grant is not deleted by it",
            grants_intact >= 1, f"{grants_intact} grant(s) still held")

    # ── 7 · encryption round-trip through PostgreSQL ─────────────────────────

    _section("7 · §10 · The AES-GCM envelope survives PostgreSQL unchanged")

    from auth.token_crypto import (                                # noqa: E402
        TokenCryptoError, decrypt, encrypt, generate_key,
    )

    KEY_ENV = {"FS_TOKEN_ENCRYPTION_KEY": generate_key()}
    FAKE = "PGCERT1-FAKE-REFRESH-" + "R" * 64      # obviously not a real token

    sealed = encrypt(FAKE, context="grant:7:refresh", environ=KEY_ENV)
    with ins.connect() as c:
        c.execute(text("UPDATE provider_grants SET refresh_token_sealed=:s "
                       "WHERE provider='yahoo'"), {"s": sealed})
        stored = c.execute(text(
            "SELECT refresh_token_sealed FROM provider_grants "
            "WHERE provider='yahoo'")).scalar()
    _assert("the envelope round-trips through PostgreSQL byte-identically",
            stored == sealed, f"{len(stored or '')} of {len(sealed)} chars")
    _assert("  · nothing was truncated", len(stored or "") == len(sealed))
    _assert("  · and it still opens",
            decrypt(stored, context="grant:7:refresh", environ=KEY_ENV) == FAKE)
    _assert("  · the plaintext is NOT what the column holds", FAKE not in stored)

    # THE ROW BINDING SURVIVES STORAGE. A ciphertext copied to another row must
    # still fail to open, after a real database round-trip.
    moved = False
    try:
        decrypt(stored, context="grant:99:refresh", environ=KEY_ENV)
        moved = True
    except TokenCryptoError:
        pass
    _assert("a ciphertext copied to another grant does not open", not moved)

    # NO PLAINTEXT TOKEN COLUMN EXISTS ANYWHERE IN THE SCHEMA.
    _plain = [f"{t}.{c}" for t, cols in fresh["columns"].items()
              for c in cols
              if re.search(r"(^|_)(access|refresh|id)_token$", c)]
    _assert("no plaintext token column exists in the whole schema",
            not _plain, ", ".join(_plain) or "none")

    # ── 8 · fresh vs upgraded ────────────────────────────────────────────────

    _section("8 · §23 · Fresh and upgraded schemas agree on the launch tables")

    # SCOPED TO WHAT PATH B BUILT. The upgrade baseline deliberately contains
    # only `users` and `leagues` plus what the migrations add — comparing whole
    # table lists would compare a two-table baseline against a fifty-table
    # application and report a difference that is an artifact of the fixture.
    # WHAT THE COMPARISON CAN AND CANNOT CLAIM.
    #
    # The upgrade baseline is a MINIMAL pre-change database — the columns
    # `users` and `leagues` had before this workstream, plus whatever these two
    # migrations add. It deliberately does not contain the columns other
    # migrations add (the economy columns, the playoff columns, the projection
    # source), because those belong to migrations this package did not run.
    #
    # So the comparison is scoped to WHAT THESE MIGRATIONS OWN. Comparing the
    # full column lists would report a difference that is an artifact of the
    # fixture and would say nothing about whether the two paths converge on the
    # thing being certified. A first cut did exactly that and reported eight
    # `leagues` columns as drift; they are not drift, they are other packages'
    # migrations.
    OWNED = {
        "users": {"auth_provider", "provider_subject", "hashed_password",
                  "email", "id", "role", "is_active"},
        "leagues": {"provider_credential_user_id",
                    "provider_credential_assigned_at", "provider",
                    "provider_league_key", "id", "name", "season"},
        "provider_grants": None,        # wholly owned — compare everything
    }

    for table, owned in OWNED.items():
        f_cols = fresh["columns"].get(table, {})
        u_cols = upgraded["columns"].get(table, {})
        keys = set(f_cols) if owned is None else (owned & set(f_cols))

        missing = sorted(k for k in keys if k not in u_cols)
        _assert(f"{table}: the upgrade path has every owned column",
                not missing, ", ".join(missing) or "none missing")

        differing = sorted(
            f"{c}: fresh={f_cols[c]} upgraded={u_cols[c]}"
            for c in keys & set(u_cols) if f_cols[c] != u_cols[c])
        _assert(f"{table}: types and nullability agree on those columns",
                not differing, "; ".join(differing)[:200] or "identical")

    # UNIQUENESS IS COMPARED AS ENFORCEMENT, not as constraint objects.
    #
    # PostgreSQL enforces a unique rule through a constraint OR a bare unique
    # index, and `get_unique_constraints` reports only the former. The identity
    # migration originally created an index while `create_all` creates a
    # constraint — the same rule, two shapes, and two deployments of the same
    # product differing by age. PG-CERT-1 changed the migration to emit a real
    # constraint on PostgreSQL so the paths converge; this checks the union, so
    # it stays true for a database migrated by either version of that file.
    def _enforced_unique(desc, table):
        insp_unique = {tuple(sorted(u)) for u in desc["unique"].get(table, [])}
        return insp_unique

    def _unique_via_index(url, table):
        with create_engine(url).connect() as conn:
            return {tuple(sorted(i["column_names"] or []))
                    for i in inspect(conn).get_indexes(table)
                    if i.get("unique")}

    for table in ("users", "provider_grants"):
        f_rule = _enforced_unique(fresh, table) | _unique_via_index(fresh_url, table)
        u_rule = (_enforced_unique(upgraded, table)
                  | _unique_via_index(upgrade_url, table))
        # Scoped to the rules these migrations own, for the same fixture reason
        # as the columns above: `users.team_id` is unique in the real schema and
        # absent from the minimal baseline.
        owned_rules = {("auth_provider", "provider_subject")} if table == "users" \
            else {("provider", "user_id")}
        _assert(f"{table}: the owned uniqueness rule is enforced on both paths",
                owned_rules <= (f_rule & u_rule),
                f"fresh={sorted(f_rule)} upgraded={sorted(u_rule)}")

    _assert("provider_grants: the same foreign keys on both paths",
            set(fresh["fk"].get("provider_grants", []))
            == set(upgraded["fk"].get("provider_grants", [])),
            f"fresh={fresh['fk'].get('provider_grants')} "
            f"upgraded={upgraded['fk'].get('provider_grants')}")
    _assert("leagues: the credential-owner foreign key exists on both paths",
            all(any(cols == ("provider_credential_user_id",) and ref == "users"
                    for cols, ref in d["fk"].get("leagues", []))
                for d in (fresh, upgraded)),
            f"fresh={fresh['fk'].get('leagues')} "
            f"upgraded={upgraded['fk'].get('leagues')}")

    # ── 9 · schema drift: metadata vs the real database ──────────────────────

    _section("9 · §22 · SQLAlchemy metadata against the real PostgreSQL schema")

    _DRIFT_DRIVER = r"""
import os, sys, json
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r
from sqlalchemy import inspect
from db.schema import Base, engine
from migrations.run import _register_rc2_models
_register_rc2_models()
insp = inspect(engine)
actual = set(insp.get_table_names())
declared = set(Base.metadata.tables)
cols = {}
for t in sorted(declared & actual):
    cols[t] = sorted(set(c.name for c in Base.metadata.tables[t].columns)
                     ^ set(c["name"] for c in insp.get_columns(t)))
print("RESULT" + json.dumps({
    "declared_not_in_db": sorted(declared - actual),
    "in_db_not_declared": sorted(actual - declared),
    "column_drift": {t: v for t, v in cols.items() if v},
}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", _DRIFT_DRIVER % {"root": ROOT, "url": fresh_url}],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    line = [l for l in (proc.stdout or "").splitlines() if l.startswith("RESULT")]
    _assert("the drift comparison ran", bool(line), (proc.stderr or "")[-200:])
    if line:
        drift = json.loads(line[0][len("RESULT"):])
        _assert("every declared table exists in PostgreSQL",
                not drift["declared_not_in_db"],
                ", ".join(drift["declared_not_in_db"]) or "none")
        # `ledger_entries` IS DECLARED — on the Ledger's own base, which the
        # comparison above reads `db.schema.Base` for. Its absence from that
        # metadata is the deliberate separation described in `ledger/ledger.py`
        # ("no accidental relationship or cascade between an accounting row and
        # an application row"), not drift, so it is named rather than flagged.
        _undeclared = [t for t in drift["in_db_not_declared"]
                       if t not in {"ledger_entries", "schema_migrations"}]
        _assert("no undeclared table was created",
                not _undeclared, ", ".join(_undeclared) or "none")
        _assert("  · ledger_entries is declared on the Ledger's own base",
                "ledger_entries" in drift["in_db_not_declared"],
                "separate declarative base, by design")
        _assert("  · schema_migrations is owned by the migration runner",
                "schema_migrations" in drift["in_db_not_declared"],
                "runner-owned operational table, by design")
        _assert("no column drift between metadata and the database",
                not drift["column_drift"],
                str(drift["column_drift"])[:200] or "none")

finally:
    _drop_all()
    print(f"\n  (dropped {len(_CREATED)} disposable database(s))")


print("\n" + "=" * 66)
if _failures:
    print(f"PG-CERT-1 MIGRATIONS — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("PG-CERT-1 MIGRATIONS — all assertions PASSED")
