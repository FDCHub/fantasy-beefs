#!/usr/bin/env python3
"""
test_yahoo_live1_provider_tokens.py — YAHOO-LIVE-1 · the provider credential.

WHAT THIS CERTIFIES. The migration that creates the grant table, and the seam
that decides which Yahoo authorization a league's reads run on — including the
part that matters most, which is what happens when there isn't one.

WHERE THE OPERATOR CREDENTIAL ENDED UP.

This suite once recorded an interim position: the per-user seam existed and the
production composition still constructed the operator transport. YAHOO-LIVE-1-FIX
closed that — production now resolves the league's own credential owner, and a
bare transport refuses to be constructed at all.

`load_credentials` itself survives, deliberately, behind the explicitly-named
`YahooLiveTransport.for_operator_tooling()`. WP2B's live evidence gate and the
offline certification both exercise it, and the measured finding that the
operator credential REFRESHES while the Fantasy API refuses is the most useful
fact this project holds about the external blocker. Deleting the code that
produced it to satisfy a source scan would have thrown that away.

The cutover's own certification is `test_yahoo_live1_fix_cutover.py`.

DATABASE. A private SQLite file per migration scenario, so the migration is run
against a database that starts WITHOUT the new table — which an in-memory
schema created from `db.schema` would not.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

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


# ── 1 · the migration, run for real against a database without the table ─────

_section("1 · The migration is additive, idempotent and non-destructive")

_MIGRATION_DRIVER = r"""
import os, sys
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r

# A PRE-MIGRATION DATABASE. Built from the schema as it was BEFORE this package,
# so the migration is applied to a database that genuinely lacks the table — the
# only way to prove an ALTER rather than a CREATE-from-model.
from sqlalchemy import create_engine, text
engine = create_engine(%(url)r)
with engine.begin() as c:
    c.execute(text('''CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, email VARCHAR NOT NULL UNIQUE,
        hashed_password VARCHAR, auth_provider VARCHAR, provider_subject VARCHAR,
        team_id INTEGER, role VARCHAR NOT NULL DEFAULT 'gm',
        is_active INTEGER NOT NULL DEFAULT 1,
        buy_in_paid INTEGER NOT NULL DEFAULT 0, stripe_account_id VARCHAR,
        created_at TIMESTAMP, last_login_at TIMESTAMP)'''))
    c.execute(text('''CREATE TABLE leagues (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR NOT NULL,
        season INTEGER NOT NULL, provider VARCHAR, provider_league_key VARCHAR,
        provider_current_week INTEGER)'''))
    c.execute(text("INSERT INTO users (email, role) VALUES ('before@x.com','gm')"))
    c.execute(text("INSERT INTO leagues (name, season) VALUES ('Before', 2025)"))

import importlib
migration = importlib.import_module("migrations.add_provider_grants")
first = migration.upgrade()
second = migration.upgrade()

from sqlalchemy import inspect
with engine.connect() as c:
    inspector = inspect(c)
    tables = inspector.get_table_names()
    grant_cols = {x["name"] for x in inspector.get_columns("provider_grants")}
    league_cols = {x["name"] for x in inspector.get_columns("leagues")}
    user_cols = {x["name"] for x in inspector.get_columns("users")}
    users_kept = c.execute(text("SELECT email FROM users")).fetchall()
    leagues_kept = c.execute(text("SELECT name FROM leagues")).fetchall()
    owner = c.execute(text(
        "SELECT provider_credential_user_id FROM leagues")).scalar()

import json
print("RESULT" + json.dumps({
    "first": first, "second": second,
    "has_table": "provider_grants" in tables,
    "grant_cols": sorted(grant_cols), "league_cols": sorted(league_cols),
    "user_cols": sorted(user_cols),
    "users_kept": [r[0] for r in users_kept],
    "leagues_kept": [r[0] for r in leagues_kept],
    "owner_default_null": owner is None,
}))
"""

_tmp = tempfile.mkdtemp(prefix="fs-yl1-migration-")
try:
    db_file = os.path.join(_tmp, "pre.db")
    url = "sqlite:///" + db_file.replace(os.sep, "/")
    proc = subprocess.run(
        [sys.executable, "-c", _MIGRATION_DRIVER % {"root": ROOT, "url": url}],
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    line = [ln for ln in (proc.stdout or "").splitlines()
            if ln.startswith("RESULT")]
    _assert("the migration ran against a pre-migration database", bool(line),
            (proc.stderr or "")[-300:])
    if line:
        import json

        out = json.loads(line[0][len("RESULT"):])
        _assert("it created the grant table", out["has_table"] is True)
        _assert("with every column the model declares",
                set(out["grant_cols"]) == {
                    "id", "user_id", "provider", "provider_subject",
                    "access_token_sealed", "refresh_token_sealed",
                    "expires_at", "granted_scope", "status", "token_version",
                    "created_at", "updated_at", "last_refresh_at",
                    "last_error_code", "last_error_at"},
                ", ".join(out["grant_cols"]))
        _assert("it added the league's credential owner",
                "provider_credential_user_id" in out["league_cols"])
        _assert("and that column defaults to NULL on existing rows",
                out["owner_default_null"] is True)

        # NON-DESTRUCTIVE, PROVED BY THE ROWS THAT WERE ALREADY THERE.
        _assert("the existing user row survives untouched",
                out["users_kept"] == ["before@x.com"], str(out["users_kept"]))
        _assert("the existing league row survives untouched",
                out["leagues_kept"] == ["Before"], str(out["leagues_kept"]))
        _assert("no user column was dropped or renamed",
                {"email", "hashed_password", "auth_provider",
                 "provider_subject"} <= set(out["user_cols"]))
        _assert("no league column was dropped or renamed",
                {"provider", "provider_league_key", "provider_current_week"}
                <= set(out["league_cols"]))

        # IDEMPOTENT. A migration that is not safe to re-run is a migration
        # somebody will eventually break a deployment with.
        _assert("running it twice is safe",
                any("already exists" in s or "nothing to do" in s
                    for s in out["second"]),
                "; ".join(out["second"]))
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


# ── 2 · PostgreSQL ───────────────────────────────────────────────────────────

_section("2 · PostgreSQL execution")

_PG = os.environ.get("TEST_DATABASE_URL", "").strip()
if not _PG:
    # STATED, NOT SKIPPED. SQLite creating a table proves nothing about
    # PostgreSQL's ALTER, and a suite that quietly omitted this would read as
    # broader coverage than it has.
    _assert("POSTGRESQL TOKEN-GRANT MIGRATION — UNVERIFIED: TEST_DATABASE_URL "
            "is not set in this environment", True, "reported, not skipped")
    _assert("the migration carries a PostgreSQL branch to be verified",
            "CREATE TABLE provider_grants" in _read(
                "migrations", "add_provider_grants.py")
            and "SERIAL PRIMARY KEY" in _read(
                "migrations", "add_provider_grants.py"))
    _assert("and the league column uses a real foreign key on PostgreSQL",
            "REFERENCES users (id)" in _read("migrations",
                                             "add_provider_grants.py"))
else:
    # THE CERTIFICATION MOVED, AND THIS BRANCH WAS WRONG WHERE IT STOOD.
    #
    # It ran the migration directly against `TEST_DATABASE_URL`. Under the
    # project's own PostgreSQL convention that URL names the ADMIN database —
    # the one `run_pg_suites.py` creates and drops per-suite databases FROM, and
    # which therefore has no `users` and no `leagues` for the migration to alter.
    # It could only ever have failed, and it went unnoticed because no
    # PostgreSQL was reachable until PG-CERT-1.
    #
    # PG-CERT-1 certifies this properly, on a disposable database, against both
    # a fresh schema and a genuine pre-change baseline, including idempotency
    # and constraint enforcement. Duplicating a weaker version of that here
    # would be two implementations of one claim, so this defers to it by name.
    _assert("PostgreSQL execution is certified by PG-CERT-1, not duplicated "
            "here", os.path.isfile(os.path.join(
                ROOT, "test_pg_cert1_migrations.py")),
            "see test_pg_cert1_migrations.py §3-§6")


# ── 3 · the provider credential seam ─────────────────────────────────────────

_section("3 · A league's Yahoo reads run on a named user's authorization")

_CRED = _read("providers", "yahoo", "user_credentials.py")


def _code_only(text: str) -> str:
    text = re.sub(r'"""[\s\S]*?"""', " ", text)
    return re.sub(r"^\s*#.*$", " ", text, flags=re.M)


_code = _code_only(_CRED)
_assert("the seam resolves the credential from the league's owner",
        "credential_owner_id" in _code and "bearer_for_league" in _code)
_assert("it reads the owner from the league row, not from a session",
        "League.provider_credential_user_id" in _code
        or "league.provider_credential_user_id" in _code)
_assert("it never loads the repository-level operator credential",
        "load_credentials" not in _code)
_assert("it fails closed when no owner is set",
        "CredentialOwnerMissing" in _code)
_assert("and there is no parameter that names another user's grant",
        not re.search(r"def bearer_for_league\([^)]*user_id", _code))


# ── 4 · the operator credential, stated as outstanding ───────────────────────

_section("4 · The operator credential path is named, not silently left")

_TRANSPORT = _read("providers", "yahoo", "transport.py")
_assert("the legacy operator loader still exists for tooling",
        "def load_credentials" in _TRANSPORT)

# YAHOO-LIVE-1-FIX COMPLETED THE SWAP THIS SUITE ONCE RECORDED AS OUTSTANDING.
#
# The assertions here used to state the honest interim position: the per-user
# seam was built and the production composition still constructed the operator
# transport. The owner ruled that interim position incomplete, and it is — so
# the cutover happened and these now pin the finished state instead. The
# detailed certification lives in test_yahoo_live1_fix_cutover.py; what is kept
# here is the fact that the old shape cannot come back.
_MAIN = _read("api", "main.py")
_assert("the settlement factory no longer builds a credential-less transport",
        "return YahooLiveTransport()" not in _MAIN)
_assert("it resolves the league's own credential owner instead",
        "token_provider=token_provider_for_league" in _MAIN)
_assert("and the operator loader is reachable only by an explicit name",
        "def for_operator_tooling" in _TRANSPORT)
_assert("which production never calls",
        "for_operator_tooling" not in _MAIN)


# ── 5 · nothing else moved ───────────────────────────────────────────────────

_section("5 · Scope")

# ANCHORED TO THIS PACKAGE'S OWN COMMIT RANGE, not to a moving HEAD.
#
# Diffing against a parent commit was right exactly once: while YAHOO-LIVE-1 was
# the uncommitted work. Every package landing afterwards then appeared inside
# this scan as a violation of YAHOO-LIVE-1's scope — PG-CERT-1's shortfall-sweep
# hygiene being the one that tripped it. A scope claim is about a fixed set of
# changes, so it is measured against a fixed range.
YL1_PARENT, YL1_COMMIT = "3d01f1f", "64d5ec1"
_touched = set(subprocess.run(
    ["git", "diff", "--name-only", YL1_PARENT, YL1_COMMIT],
    cwd=ROOT, capture_output=True, text=True).stdout.split())

for forbidden in ("economy/", "ledger/", "betting/", "odds/", "beefs/",
                  "reports/", "spec/", "docs/", "web/manifest.webmanifest",
                  "web/service-worker.js"):
    hits = sorted(f for f in _touched if f.startswith(forbidden))
    _assert(f"{forbidden} is untouched", not hits, ", ".join(hits))

_assert("no Yahoo attribution copy changed",
        "attribution" not in " ".join(
            f for f in _touched if f.startswith("web/js/")))

# THE DEMO RUNTIME IS UNCHANGED AND UNCOUPLED.
_assert("no Demo provider source changed",
        not any(f.startswith("providers/demo/") for f in _touched),
        ", ".join(f for f in _touched if f.startswith("providers/demo/")))

# AND NO YAHOO PAYLOAD CACHE WAS INTRODUCED.
_schema = _read("db", "schema.py")
_new_tables = re.findall(r'__tablename__ = "([a-z_]+)"', _schema)
_assert("exactly one table was added, and it holds credentials",
        _new_tables.count("provider_grants") == 1)
for banned in ("yahoo_payload", "provider_cache", "fantasy_cache",
               "roster_cache", "provider_snapshot_cache"):
    _assert(f"  · no {banned} table", banned not in _new_tables)


print("\n" + "=" * 66)
if _failures:
    print(f"YAHOO-LIVE-1 PROVIDER TOKENS — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("YAHOO-LIVE-1 PROVIDER TOKENS — all assertions PASSED")
