#!/usr/bin/env python3
"""
test_prod_harden1_release.py — PROD-HARDEN-1 · deployment and release controls.

WHAT THIS CERTIFIES. That a production deployment can be identified, validated,
gated, upgraded and released deterministically — and that each of those is a
mechanism rather than a paragraph in a runbook.

The distinction matters because everything here is the kind of thing that reads
as done when it is only described. "Startup validates configuration" is a
sentence; whether a production process with no `DATABASE_URL` actually refuses
to start is a test. Each section below drives the real mechanism.

DATABASE. SQLite for the route and manifest tiers — none of these claims are
dialect-dependent. PostgreSQL certification of the migrations themselves is
PG-CERT-1's, and is not repeated here.
"""

from __future__ import annotations

import json
import os
import re
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


# ── 1 · release identity ─────────────────────────────────────────────────────

_section("1 · §10 · The running build can be identified")

from ops.release import (                                          # noqa: E402
    SOURCE_ENV, SOURCE_GIT, SOURCE_PLATFORM, SOURCE_UNKNOWN, release_identity,
)

_assert("an explicit release wins over everything",
        release_identity({"FS_RELEASE": "v1.2.3"}, use_cache=False).source
        == SOURCE_ENV)
_assert("the platform's commit is used when no explicit release is set",
        release_identity({"RAILWAY_GIT_COMMIT_SHA": "abc123def456"},
                         use_cache=False).release == "abc123def456")
_assert("  · and is reported as coming from the platform",
        release_identity({"RAILWAY_GIT_COMMIT_SHA": "abc123def456"},
                         use_cache=False).source == SOURCE_PLATFORM)
_assert("a checkout falls back to git HEAD",
        release_identity({}, use_cache=False).source
        in (SOURCE_GIT, SOURCE_UNKNOWN))
_assert("the identity is short enough to log",
        len(release_identity({"FS_RELEASE": "a" * 40},
                             use_cache=False).short) == 12)

_identity = release_identity({"FS_RELEASE": "rel", "FS_ENV": "production"},
                             use_cache=False)
_assert("it carries the environment", _identity.environment == "production")
_assert("and an application version", bool(_identity.version))

# NOTHING SECRET IS IN IT. A commit identifies a build; a config value does not
# belong in a response an operator can curl.
_payload = json.dumps(_identity.as_dict())
for secret in ("SECRET", "PASSWORD", "KEY", "TOKEN", "postgres://"):
    _assert(f"the identity carries no {secret.lower()}",
            secret.lower() not in _payload.lower())


# ── 2 · configuration validation ─────────────────────────────────────────────

_section("2 · §12 · Production configuration is graded and fails closed")

from ops.config import (                                           # noqa: E402
    ProductionConfigError, evaluate_config, startup_guard,
)
from auth.token_crypto import generate_key                         # noqa: E402

_KEY = generate_key()
_COMPLETE = {
    "FS_ENV": "production", "DATABASE_URL": "postgresql://h/x",
    "FS_TOKEN_ENCRYPTION_KEY": _KEY, "JWT_SECRET_KEY": "s" * 32,
    "FS_YAHOO_CLIENT_ID": "id", "FS_YAHOO_CLIENT_SECRET": "sec",
    "FS_YAHOO_REDIRECT_URI": "https://x/cb",
    "FS_PUBLIC_BASE_URL": "https://x", "FS_RELEASE": "rel",
}

_full = evaluate_config(_COMPLETE)
_assert("a fully configured production process is serviceable",
        _full.serviceable is True and not _full.missing_critical,
        ", ".join(_full.missing_critical) or "nothing missing")
_assert("  · it can store provider tokens", _full.can_store_provider_tokens)
_assert("  · and it can sign in with Yahoo", _full.can_sign_in_with_yahoo)

# THE TWO THAT MUST STOP A DEPLOY.
for name, why in (("DATABASE_URL",
                   "would silently write the season into a container file"),
                  ("FS_TOKEN_ENCRYPTION_KEY",
                   "would accept Yahoo sign-ins and drop every grant")):
    env = dict(_COMPLETE)
    env.pop(name)
    report = evaluate_config(env)
    _assert(f"without {name} a production process is NOT serviceable",
            not report.serviceable and name in report.missing_critical, why)
    try:
        startup_guard(env)
        _assert(f"  · and startup refuses", False, "it started anyway")
    except ProductionConfigError as exc:
        _assert(f"  · and startup refuses", True, "ProductionConfigError")
        # THE VALUE THAT WAS REMOVED, not `env.get` of a key that is gone —
        # which returns "" and is a substring of every string, so the first cut
        # could never pass.
        removed = _COMPLETE[name]
        _assert("  · naming the variable and no value",
                name in str(exc) and removed not in str(exc)
                and _KEY not in str(exc))

# AND THE ONE THAT GATES TRAFFIC WITHOUT BLOCKING STARTUP.
#
# `FS_COOKIE_INSECURE` in production is a real misconfiguration and must stop
# traffic — but the process still functions, and a process that cannot start
# cannot be inspected either. It belongs in `missing_critical` (so `/ready`
# refuses) and NOT in `fatal_at_startup`.
_insecure = dict(_COMPLETE)
_insecure["FS_COOKIE_INSECURE"] = "1"
_report = evaluate_config(_insecure)
_assert("insecure cookies make a production process NOT serviceable",
        not _report.serviceable,
        ", ".join(_report.missing_critical))
_assert("  · but do NOT prevent it from starting",
        not _report.fatal_at_startup,
        "the process stays up and inspectable")
startup_guard(_insecure)
_assert("  · so startup_guard does not raise for it", True)

# THE ONES THAT MUST NOT.
_no_yahoo = dict(_COMPLETE)
for var in ("FS_YAHOO_CLIENT_ID", "FS_YAHOO_CLIENT_SECRET",
            "FS_YAHOO_REDIRECT_URI"):
    _no_yahoo.pop(var)
_degraded = evaluate_config(_no_yahoo)
_assert("a production process WITHOUT Yahoo still serves",
        _degraded.serviceable is True,
        "Demo, reads and every non-provider surface still work")
_assert("  · and says so as a degraded capability",
        any("YAHOO" in m for m in _degraded.missing_degraded),
        ", ".join(_degraded.missing_degraded))
_assert("  · and reports Yahoo sign-in unavailable",
        _degraded.can_sign_in_with_yahoo is False)
try:
    startup_guard(_no_yahoo)
    _assert("  · and startup does NOT refuse", True, "it started")
except ProductionConfigError:
    _assert("  · and startup does NOT refuse", False, "it refused")

# DEVELOPMENT IS NEVER BLOCKED.
_dev = evaluate_config({"FS_ENV": "development"})
_assert("a development process with nothing configured is serviceable",
        _dev.serviceable is True)
startup_guard({"FS_ENV": "development"})
_assert("  · and startup does not raise for it", True)

# NO DEVELOPMENT FALLBACK IS EVER SUBSTITUTED IN PRODUCTION.
_CONFIG_CODE = re.sub(r'"""[\s\S]*?"""', " ", _read("ops", "config.py"))
_CONFIG_CODE = re.sub(r"^\s*#.*$", " ", _CONFIG_CODE, flags=re.M)
_assert("the config module substitutes no default secret",
        not re.search(r"(setdefault|or\s+[\"'])\s*[\"'][A-Za-z0-9+/=]{16,}",
                      _CONFIG_CODE))
_assert("and it reports names, never values",
        "missing_critical" in _CONFIG_CODE
        and not re.search(r"env\.get\([^)]*\)\s*\)?\s*$", _CONFIG_CODE, re.M))


# ── 3 · the migration manifest ───────────────────────────────────────────────

_section("3 · §8 · One deterministic production upgrade sequence")

from migrations.manifest import ACTIVE, HISTORICAL                 # noqa: E402
from migrations import run as migration_runner                     # noqa: E402

_assert("an ordered manifest exists", len(ACTIVE) >= 2, f"{len(ACTIVE)} active")
_assert("every entry has a stable identifier",
        all(re.match(r"^\d{4}_[a-z_]+$", m.identifier) for m in ACTIVE),
        ", ".join(m.identifier for m in ACTIVE))
_assert("identifiers are unique",
        len({m.identifier for m in ACTIVE}) == len(ACTIVE))
_assert("the order is deterministic — identity before the grant that "
        "references it",
        [m.identifier for m in ACTIVE][:2]
        == ["0001_yahoo_identity", "0002_provider_grants"])
_assert("every active module is importable and exposes upgrade()",
        all(hasattr(__import__(m.module, fromlist=["upgrade"]), "upgrade")
            for m in ACTIVE))

_assert("historical scripts are recorded rather than run",
        len(HISTORICAL) >= 25, f"{len(HISTORICAL)} recorded")
_assert("  · and the one-shot data conversion is among them",
        any("migrate_tx_type_pool_values" in h for h in HISTORICAL))

# NO SCRIPT IS SILENTLY UNACCOUNTED FOR. Every migration file on disk is either
# ACTIVE or HISTORICAL — the inventory is the point of the manifest.
import pathlib                                                     # noqa: E402

_on_disk = {str(p).replace(os.sep, "/")
            for d in ("migrations", "db/migrations")
            for p in pathlib.Path(d).glob("*.py")
            if p.name not in ("__init__.py", "manifest.py", "run.py")}
_accounted = set(HISTORICAL) | {m.module.replace(".", "/") + ".py"
                                for m in ACTIVE}
_unaccounted = sorted(_on_disk - _accounted)
_assert("every migration file on disk is accounted for in the manifest",
        not _unaccounted, ", ".join(_unaccounted) or "all accounted")


# ── 4 · the migration ledger, driven ─────────────────────────────────────────

_section("4 · §9 · Applied migrations are recorded in the database")

_tmp = tempfile.mkdtemp(prefix="ph1-mig-")
_DRIVER = r'''
import os, sys, json
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r
os.environ["FS_RELEASE"] = "test-release-sha"

from sqlalchemy import create_engine, text
engine = create_engine(%(url)r)
with engine.begin() as c:
    c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR "
                   "NOT NULL UNIQUE, hashed_password VARCHAR, team_id INTEGER, "
                   "role VARCHAR NOT NULL DEFAULT 'gm', is_active INTEGER "
                   "DEFAULT 1, buy_in_paid INTEGER DEFAULT 0, "
                   "stripe_account_id VARCHAR, created_at TIMESTAMP, "
                   "last_login_at TIMESTAMP)"))
    c.execute(text("CREATE TABLE leagues (id INTEGER PRIMARY KEY, name VARCHAR "
                   "NOT NULL, season INTEGER NOT NULL, provider VARCHAR, "
                   "provider_league_key VARCHAR, provider_current_week INTEGER)"))

from migrations.run import applied_identifiers, pending, status, upgrade

before = sorted(applied_identifiers(engine))
pending_before = [m.identifier for m in pending(engine)]
first = upgrade(engine)
after = sorted(applied_identifiers(engine))
second = upgrade(engine)
after_second = sorted(applied_identifiers(engine))

with engine.connect() as c:
    rows = c.execute(text("SELECT identifier, release, application_version "
                          "FROM schema_migrations ORDER BY identifier")).fetchall()

print("RESULT" + json.dumps({
    "before": before, "pending_before": pending_before,
    "first": first, "after": after,
    "second": second, "after_second": after_second,
    "rows": [list(r) for r in rows],
    "status": status(engine),
}))
'''
try:
    url = "sqlite:///" + os.path.join(_tmp, "m.db").replace(os.sep, "/")
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER % {"root": ROOT, "url": url}],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    line = [l for l in (proc.stdout or "").splitlines() if l.startswith("RESULT")]
    _assert("the runner applied migrations to a pre-change database", bool(line),
            (proc.stderr or "")[-300:])
    if line:
        out = json.loads(line[0][len("RESULT"):])
        _assert("nothing was recorded before it ran", out["before"] == [])
        _assert("both migrations were pending",
                out["pending_before"] == ["0001_yahoo_identity",
                                          "0002_provider_grants"])
        _assert("both are recorded after", out["after"]
                == ["0001_yahoo_identity", "0002_provider_grants"])
        _assert("a second run applies nothing",
                any("nothing pending" in s for s in out["second"]),
                "; ".join(out["second"]))
        _assert("  · and records nothing further",
                out["after_second"] == out["after"])
        _assert("each row carries the release that applied it",
                all(r[1] == "test-release-sha" and r[2] for r in out["rows"]),
                str(out["rows"][0]) if out["rows"] else "no rows")
        _assert("status reports a clean head",
                out["status"]["pending"] == []
                and out["status"]["manifest_head"] == "0002_provider_grants")
finally:
    import shutil

    shutil.rmtree(_tmp, ignore_errors=True)

# A FAILED MIGRATION IS NOT RECORDED. Asserted from the runner's shape: the row
# is written only after `upgrade()` returns.
_RUN_CODE = re.sub(r'"""[\s\S]*?"""', " ", _read("migrations", "run.py"))
# SCOPED TO `upgrade()`. `_record` is DEFINED above it, so comparing first
# occurrences in the whole file compared against the definition rather than the
# call — which is always earlier and says nothing.
_UPGRADE_FN = _RUN_CODE.split("def upgrade(")[1].split(chr(10) + "def ")[0]
_assert("the record is written only after the migration returns",
        _UPGRADE_FN.index("module.upgrade()") < _UPGRADE_FN.index("_record("))
_assert("and the CLI exits non-zero on failure so a release stops",
        "return 2" in _RUN_CODE and "MIGRATION FAILED" in _read(
            "migrations", "run.py"))


# ── 5 · startup does not race migrations ─────────────────────────────────────

_section("5 · §7 · Web processes do not run DDL against an existing database")

_MAIN = _read("api", "main.py")
_startup = _MAIN.split("def _create_tables()")[1].split(chr(10) + "@app.")[0]
_assert("the bootstrap is skipped on a production database that has tables",
        "is_production()" in _startup and "existing" in _startup
        and "return" in _startup)
_assert("  · and says so rather than doing it silently",
        "bootstrap skipped" in _startup)
_assert("a fresh database still bootstraps",
        "Base.metadata.create_all(engine)" in _startup)
_assert("  · and stamps the manifest so readiness is correct",
        "stamp_all" in _startup)


# ── 6 · health, readiness and version, driven ────────────────────────────────

_section("6 · §11 · Liveness and readiness are distinct and real")

from fastapi.testclient import TestClient                          # noqa: E402

_tmp2 = tempfile.mkdtemp(prefix="ph1-app-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    _tmp2, "app.db").replace(os.sep, "/")

import importlib                                                   # noqa: E402

import db.schema                                                   # noqa: E402

importlib.reload(db.schema)
import api.main                                                    # noqa: E402

importlib.reload(api.main)

with TestClient(api.main.app) as client:
    version = client.get("/version")
    _assert("/version responds", version.status_code == 200)
    _assert("  · with a release and its source",
            bool(version.json().get("release"))
            and bool(version.json().get("release_source")))

    ready = client.get("/ready")
    _assert("/ready responds ready on a bootstrapped database",
            ready.status_code == 200 and ready.json()["ready"] is True,
            json.dumps(ready.json().get("checks", {})))
    checks = ready.json()["checks"]
    _assert("  · it checks the database", checks.get("database") == "ok")
    _assert("  · it checks the migration head",
            checks.get("migrations") == "ok")
    _assert("  · it reports Yahoo WITHOUT gating on it",
            checks.get("yahoo_sign_in") == "not_configured"
            and ready.json()["ready"] is True,
            "an unconfigured provider must not take the product offline")
    _assert("  · and it reports whether writes are enabled",
            checks.get("writes") == "enabled")

    health = client.get("/health")
    _assert("/health still responds — liveness is a separate question",
            health.status_code == 200)

    # NO CONFIGURATION VALUE LEAKS THROUGH EITHER SURFACE.
    _bodies = version.text + ready.text + health.text
    for marker in ("SECRET", "sqlite:///", "postgres", "FS_TOKEN"):
        _assert(f"no {marker!r} in the health/readiness surfaces",
                marker not in _bodies)

    # ── the service worker carries the release ───────────────────────────────
    _section("7 · §35 · The service worker's cache namespace is the release")

    worker = client.get("/app/service-worker.js")
    _assert("the worker is served", worker.status_code == 200)
    _assert("  · with the placeholder substituted",
            "__FS_RELEASE__" not in worker.text)
    _assert("  · producing a release-derived cache namespace",
            re.search(r"const VERSION = 'fs-shell-' \+ RELEASE", worker.text)
            is not None)
    _release_token = version.json()["release"][:12]
    _safe = "".join(c for c in _release_token if c.isalnum())
    _assert("  · naming THIS release", f"'{_safe}'" in worker.text,
            f"expected {_safe}")
    _assert("  · and it is never cached itself, or a new release is invisible",
            "no-store" in worker.headers.get("cache-control", ""),
            worker.headers.get("cache-control", ""))

    # THE PWA RULES WP3E CERTIFIED ARE UNCHANGED.
    for rule in ("'/auth/'", "credentials === 'include'", "clients.claim",
                 "caches.delete"):
        _assert(f"  · WP3E's rule survives: {rule}", rule in worker.text)


print("\n" + "=" * 66)
if _failures:
    print(f"PROD-HARDEN-1 RELEASE — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("PROD-HARDEN-1 RELEASE — all assertions PASSED")
