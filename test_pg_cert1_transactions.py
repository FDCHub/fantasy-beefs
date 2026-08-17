#!/usr/bin/env python3
"""
test_pg_cert1_transactions.py — PG-CERT-1 · atomicity and concurrency on PostgreSQL.

WHAT THIS CERTIFIES. That the transaction and concurrency behaviour the product
was DESIGNED around is actually delivered by PostgreSQL — not by SQLite, which
cannot express half of it, and not by inspection, which cannot express any of
it.

Three questions, each of which has a wrong answer that looks fine until it
happens in production:

  §11  AUTH CALLBACK — a sign-in creates a user and then records that user's
       Yahoo grant. If the second half fails, does a broken half-state commit?
       And does signing in twice make two grants?

  §24  ROLLBACK — when a write group fails partway, is anything from it left
       behind? Asked of the grant insert, the duplicate identity, the credential
       assignment and a Ledger posting group.

  §25  CONCURRENCY — the grant's `token_version` exists so two workers
       refreshing the same grant cannot both write. That was proved against
       SQLite with a staged interleave; here it is proved against PostgreSQL
       with two real connections in two real transactions.

WHAT IT IS NOT. Crash and recovery certification — that is the next phase, and
§24 says so explicitly. Nothing here kills a process or corrupts a data file; it
exercises transaction boundaries, which is a different and smaller claim.

DATABASE. PostgreSQL, one disposable database, created and dropped here.
"""

from __future__ import annotations

import os
import subprocess
import sys
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


_ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if not _ADMIN_URL:
    print("  [FAIL] TEST_DATABASE_URL is not set")
    sys.exit(2)
_url = make_url(_ADMIN_URL)
if "_test" not in (_url.database or ""):
    print("  [FAIL] the admin database name must contain '_test'")
    sys.exit(2)

_admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
_DB = f"pgcert1_tx_{uuid.uuid4().hex[:8]}_test"
with _admin.connect() as c:
    c.execute(text(f'CREATE DATABASE "{_DB}"'))
_TARGET = _url.set(database=_DB).render_as_string(hide_password=False)

_DRIVER = r'''
import os, sys, json
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r

from db.schema import Base, engine, SessionLocal, League, ProviderGrant, User
Base.metadata.create_all(engine)
from ledger.ledger import create_ledger_table, post as ledger_post, balance_of
create_ledger_table()

from auth.token_crypto import generate_key
from auth.provider_grant import (grant_for, record_grant, refresh_grant,
                                 GrantUnavailable)
from providers.yahoo.user_credentials import set_credential_owner

ENV = {"FS_TOKEN_ENCRYPTION_KEY": generate_key()}
OUT = {}
db = SessionLocal()


def tokens(access="at-1", refresh="rt-1"):
    return {"access_token": access, "refresh_token": refresh,
            "expires_in": 3600, "scope": "openid email fspt-r"}


# ══ §11 · the auth callback's transaction boundary ══════════════════════════

# A GRANT CANNOT REFERENCE A USER THAT DOES NOT EXIST — the FK, on PostgreSQL.
try:
    db.add(ProviderGrant(user_id=999999, provider="yahoo",
                         provider_subject="ghost", status="active",
                         token_version=1))
    db.commit()
    OUT["orphan_grant"] = "COMMITTED"
except Exception:
    db.rollback()
    OUT["orphan_grant"] = "REFUSED"
OUT["orphan_rows"] = db.query(ProviderGrant).filter(
    ProviderGrant.provider_subject == "ghost").count()

u = User(email="cb@example.com", hashed_password=None, auth_provider="yahoo",
         provider_subject="sub-cb", role="gm", is_active=1)
db.add(u); db.commit(); db.refresh(u)

# THE USER EXISTS BEFORE THE GRANT REFERENCES IT — the ordering the callback
# relies on, asserted rather than assumed.
g = record_grant(db, user_id=u.id, provider_subject="sub-cb",
                 tokens=tokens(), environ=ENV)
OUT["grant_after_user"] = dict(exists=g is not None, user=g.user_id == u.id)

# SIGNING IN TWICE UPDATES ONE GRANT — it does not accumulate.
record_grant(db, user_id=u.id, provider_subject="sub-cb",
             tokens=tokens(access="at-2"), environ=ENV)
OUT["repeat_signin"] = db.query(ProviderGrant).filter(
    ProviderGrant.user_id == u.id).count()

# A FAILURE PART-WAY THROUGH THE CALLBACK LEAVES NOTHING. Simulated the way it
# would really happen: the grant write raises after the user is committed, and
# the session is rolled back — the user survives (they are authenticated) and no
# half-built grant exists.
u2 = User(email="half@example.com", hashed_password=None, auth_provider="yahoo",
          provider_subject="sub-half", role="gm", is_active=1)
db.add(u2); db.commit(); db.refresh(u2)
try:
    db.add(ProviderGrant(user_id=u2.id, provider="yahoo",
                         provider_subject="sub-half", status="not_a_status",
                         token_version=1))
    db.commit()
except Exception:
    db.rollback()
OUT["half_state"] = dict(
    user_survived=db.query(User).filter(User.id == u2.id).count() == 1,
    grant_rows=db.query(ProviderGrant).filter(
        ProviderGrant.user_id == u2.id).count())

# ══ §24 · duplicate identity, and the credential assignment ════════════════

try:
    db.add(User(email="dup@example.com", hashed_password=None,
                auth_provider="yahoo", provider_subject="sub-cb", role="gm",
                is_active=1))
    db.commit()
    OUT["dup_identity"] = "COMMITTED"
except Exception:
    db.rollback()
    OUT["dup_identity"] = "REFUSED"
OUT["dup_rows"] = db.query(User).filter(
    User.provider_subject == "sub-cb").count()

lg = League(name="TX League", season=2025, provider="yahoo",
            provider_league_key="461.l.tx")
db.add(lg); db.commit(); db.refresh(lg)
try:
    lg.provider_credential_user_id = 999999
    db.commit()
    OUT["bad_owner"] = "COMMITTED"
except Exception:
    db.rollback()
    OUT["bad_owner"] = "REFUSED"
db.refresh(lg)
OUT["owner_after_failure"] = lg.provider_credential_user_id

set_credential_owner(db, league_id=lg.id, user_id=u.id)
db.refresh(lg)
OUT["owner_assigned"] = lg.provider_credential_user_id == u.id

# A LEDGER WRITE GROUP THAT FAILS ITS GUARD LEAVES NOTHING. The funded-balance
# guard refuses a debit a protected account cannot cover, and the whole posting
# — both legs — must be absent afterwards, not just the offending one.
before = balance_of("championship")
try:
    ledger_post([("wallet:9999", -5000), ("championship", 5000)],
                door="pgcert1_probe", session=db)
    OUT["ledger_group"] = "COMMITTED"
except Exception:
    db.rollback()
    OUT["ledger_group"] = "REFUSED"
OUT["ledger_unchanged"] = balance_of("championship") == before

# THE ID, NOT THE OBJECT. `db.close()` detaches every instance it loaded, and
# reading `u.id` afterwards raises DetachedInstanceError — the concurrency
# section below needs the value, not the ORM row.
USER_ID = u.id
db.close()

# ══ §25 · two real connections racing one grant ════════════════════════════
#
# A GENUINE RACE, NOT TWO CALLS IN A ROW. A first cut simply called
# `refresh_grant` twice on two sessions and asserted the version advanced once.
# It advanced twice — correctly, because `refresh_grant` re-reads the version
# when it starts, so sequential calls are two legitimate refreshes and not a
# conflict at all. The conflict only exists when both are IN FLIGHT: both have
# read version N and both are about to write N+1.
#
# So both run on threads, and neither is allowed to leave its refresher until
# the other has arrived — which puts both inside the critical section with the
# same observed version, on two real PostgreSQL connections.
import threading

both_inside = threading.Barrier(2, timeout=30)
results = {}


def worker(tag):
    session = SessionLocal()

    def refresher(*, refresh_token):
        # Both threads have now read the same token_version and are past the
        # point of no return; whichever writes second must lose.
        both_inside.wait()
        return tokens(access="at-%%s" %% tag, refresh="rt-%%s" %% tag)

    try:
        grant = refresh_grant(session, user_id=USER_ID, refresher=refresher,
                              environ=ENV)
        results[tag] = dict(ok=True, version=grant.token_version,
                            status=grant.status)
    except Exception as exc:
        results[tag] = dict(ok=False, error=type(exc).__name__)
    finally:
        session.close()


# Expire the access token so both threads genuinely need to refresh.
setup = SessionLocal()
from datetime import datetime, timedelta, timezone
g = grant_for(setup, user_id=USER_ID)
baseline = g.token_version
g.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
setup.commit()
setup.close()

threads = [threading.Thread(target=worker, args=(t,)) for t in ("one", "two")]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=60)

check = SessionLocal()
final = grant_for(check, user_id=USER_ID)
OUT["race"] = dict(
    rows=check.query(ProviderGrant).filter(
        ProviderGrant.user_id == USER_ID).count(),
    status=final.status,
    baseline=baseline,
    version=final.token_version,
    both_returned=all(r.get("ok") for r in results.values()),
    workers=results,
)
check.close()

print("RESULT" + json.dumps(OUT))
'''

try:
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER % {"root": ROOT, "url": _TARGET}],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    line = [l for l in (proc.stdout or "").splitlines() if l.startswith("RESULT")]

    _section("1 · §11 · The auth callback's transaction boundary")
    _assert("the PostgreSQL scenarios ran", bool(line),
            (proc.stderr or "")[-400:])

    if line:
        import json

        out = json.loads(line[0][len("RESULT"):])

        _assert("a grant cannot reference a nonexistent user",
                out["orphan_grant"] == "REFUSED")
        _assert("  · and nothing was written by the attempt",
                out["orphan_rows"] == 0, f"{out['orphan_rows']} row(s)")
        _assert("the user exists before the grant references it",
                out["grant_after_user"]["exists"] is True
                and out["grant_after_user"]["user"] is True)
        _assert("signing in twice updates ONE grant rather than duplicating",
                out["repeat_signin"] == 1, f"{out['repeat_signin']} row(s)")
        _assert("a callback failing after the user is committed leaves the "
                "user signed-in-able", out["half_state"]["user_survived"] is True)
        _assert("  · and leaves NO half-built grant behind",
                out["half_state"]["grant_rows"] == 0,
                f"{out['half_state']['grant_rows']} row(s)")

        _section("2 · §24 · Rollback leaves no partial authoritative state")

        _assert("a duplicate Yahoo identity is refused",
                out["dup_identity"] == "REFUSED")
        _assert("  · and exactly one row still holds that subject",
                out["dup_rows"] == 1, f"{out['dup_rows']} row(s)")
        _assert("a credential owner that does not exist is refused",
                out["bad_owner"] == "REFUSED")
        _assert("  · and the league's owner is unchanged by the attempt",
                out["owner_after_failure"] is None,
                str(out["owner_after_failure"]))
        _assert("a valid assignment then commits", out["owner_assigned"] is True)
        _assert("a Ledger posting that fails its guard is refused whole",
                out["ledger_group"] == "REFUSED")
        _assert("  · with NEITHER leg written",
                out["ledger_unchanged"] is True)

        _section("3 · §25 · Two PostgreSQL transactions racing one grant")

        race = out["race"]
        _assert("the grant is still a single row afterwards",
                race["rows"] == 1, f"{race['rows']} row(s)")
        _assert("it is still usable — no worker corrupted it",
                race["status"] == "active", race["status"])
        _assert("both callers got a grant back rather than an exception",
                race["both_returned"] is True, str(race["workers"]))
        # THE VERSION ADVANCED EXACTLY ONCE FOR THE ONE WRITE THAT WON.
        #
        # Two threads entered `refresh_grant` having read the same version and
        # were held there until both had arrived. Only one may claim it. A
        # second advance would mean the loser wrote as well — over a refresh
        # token Yahoo revokes the moment the winner's exchange succeeds — and
        # the grant would be dead despite a refresh having just worked.
        _assert("exactly one of the two racing writes won",
                race["version"] == race["baseline"] + 1,
                f"baseline {race['baseline']} → {race['version']}")

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
    print(f"PG-CERT-1 TRANSACTIONS — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("PG-CERT-1 TRANSACTIONS — all assertions PASSED")
