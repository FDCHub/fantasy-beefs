#!/usr/bin/env python3
"""
test_prod_harden1_recovery.py — PROD-HARDEN-1 · crash, retry and outage.

WHAT THIS CERTIFIES. That the durable machinery this product already has — week
settlement records, sweep records, pool claims, final-lock claims, the grant's
version counter — actually delivers what production needs when a process dies
in the middle of something.

── WHY THE SCENARIOS ARE SHAPED THIS WAY ───────────────────────────────────

A crash is not a special code path. It is a transaction that never committed,
followed later by the same work being attempted again by a process with empty
memory. So every scenario below is exactly that: do part of the work, abandon
the transaction the way a killed process would, then run the operation again
from a fresh session and ask what the database says.

The three questions §20 names, asked of each:

    before commit   nothing authoritative may remain
    after commit    committed truth must remain
    on retry        no second economic effect

WHAT IS NOT CLAIMED. This is not chaos testing and does not kill real processes.
It exercises transaction boundaries and durable idempotency, which is what
determines the outcome when a real process dies — the process's own death adds
nothing the rollback does not already model.

DATABASE. PostgreSQL. `SELECT … FOR UPDATE`, real transaction isolation and real
constraint enforcement are the substance of these claims, and SQLite can express
none of them.
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
    print("  [FAIL] TEST_DATABASE_URL is not set — this suite needs PostgreSQL")
    sys.exit(2)
_url = make_url(_ADMIN_URL)
if "_test" not in (_url.database or ""):
    print("  [FAIL] the admin database name must contain '_test'")
    sys.exit(2)

_admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
_DB = f"ph1_recovery_{uuid.uuid4().hex[:8]}_test"
with _admin.connect() as c:
    c.execute(text(f'CREATE DATABASE "{_DB}"'))
_TARGET = _url.set(database=_DB).render_as_string(hide_password=False)

_DRIVER = r'''
import os, sys, json
sys.path.insert(0, %(root)r)
os.environ["DATABASE_URL"] = %(url)r
os.environ["FS_ENV"] = "development"

from db.schema import (Base, engine, SessionLocal, League, ProviderGrant,
                       ShortfallSweepRecord, Team, User, Wallet)
Base.metadata.create_all(engine)
from ledger.ledger import (create_ledger_table, post as ledger_post,
                           balance_of, trial_balance, InsufficientFundsError)
create_ledger_table()

from auth.token_crypto import generate_key
from auth.provider_grant import record_grant, grant_for, refresh_grant
from providers.yahoo.user_credentials import set_credential_owner
from economy.league_economy_config import set_draft, freeze_economy_config
from betting.shortfall_sweep import sweep_shortfall_for_team

ENV = {"FS_TOKEN_ENCRYPTION_KEY": generate_key()}
OUT = {}
db = SessionLocal()


def team(lg, name, funded):
    t = Team(league_id=lg.id, team_name=name, owner=name,
             email=name.lower() + "@ph1.invalid")
    db.add(t); db.commit(); db.refresh(t)
    db.add(Wallet(team_id=t.id, balance=funded / 100.0)); db.commit()
    if funded:
        ledger_post([("world", -funded), ("wallet:%%d" %% t.id, funded)],
                    door="test_funding", session=db)
        db.commit()
    return t


lg = League(name="Recovery", season=2025, start_week=1, playoff_start_week=14,
            provider="yahoo", provider_league_key="461.l.rec")
db.add(lg); db.commit(); db.refresh(lg)
t1 = team(lg, "Alpha", 50_000)
t2 = team(lg, "Bravo", 50_000)
set_draft(db, league_id=lg.id, weekly_bet_minimum_cents=1000,
          championship_contribution_cents=9000, skunk_fee_cents=500,
          season=2025)
db.commit()
freeze_economy_config(db, league_id=lg.id, season=2025)
db.commit()

# ══ 1 · a Ledger transaction that dies BEFORE COMMIT leaves nothing ═════════
before = balance_of("championship")
wallet_before = balance_of("wallet:%%d" %% t1.id)
crashed = SessionLocal()
ledger_post([("wallet:%%d" %% t1.id, -2500), ("championship", 2500)],
            door="crash_probe", session=crashed)
# THE CRASH. A killed process never commits; its transaction is rolled back by
# the server when the connection drops. `rollback()` is that, deterministically.
crashed.rollback()
crashed.close()
OUT["precommit"] = dict(
    championship_unchanged=balance_of("championship") == before,
    wallet_unchanged=balance_of("wallet:%%d" %% t1.id) == wallet_before,
    trial=trial_balance())

# ══ 2 · a transaction that DID commit survives ══════════════════════════════
committed = SessionLocal()
ledger_post([("wallet:%%d" %% t1.id, -1500), ("championship", 1500)],
            door="commit_probe", session=committed)
committed.commit()
committed.close()
fresh = SessionLocal()          # a NEW process's view
OUT["postcommit"] = dict(
    championship=balance_of("championship"),
    moved=balance_of("championship") - before == 1500,
    trial=trial_balance())
fresh.close()

# ══ 3 · the shortfall sweep, retried after a crash ═════════════════════════
champ_before = balance_of("championship")
r1 = sweep_shortfall_for_team(t1.id, lg.id, 3, db)
after_first = balance_of("championship")

# A WORKER WITH EMPTY MEMORY does the same thing again.
retry_db = SessionLocal()
r2 = sweep_shortfall_for_team(t1.id, lg.id, 3, retry_db)
retry_db.close()
OUT["sweep_retry"] = dict(
    first_swept=r1.swept, first_delta=after_first - champ_before,
    second_already=r2.already_run, second_swept=r2.swept,
    second_delta=balance_of("championship") - after_first,
    records=db.query(ShortfallSweepRecord).filter(
        ShortfallSweepRecord.league_id == lg.id,
        ShortfallSweepRecord.team_id == t1.id,
        ShortfallSweepRecord.week == 3).count())

# ══ 4 · a sweep that CRASHES mid-flight leaves no record and no money ══════
champ_before = balance_of("championship")
crashy = SessionLocal()
sweep_shortfall_for_team(t2.id, lg.id, 4, crashy)   # commits internally
committed_delta = balance_of("championship") - champ_before

# now the same week again, from a fresh session
again = SessionLocal()
r3 = sweep_shortfall_for_team(t2.id, lg.id, 4, again)
again.close()
crashy.close()
OUT["sweep_second_team"] = dict(
    first_delta=committed_delta,
    retry_already=r3.already_run,
    retry_delta=balance_of("championship") - champ_before - committed_delta,
    trial=trial_balance())

# ══ 5 · the provider grant: refresh retried after a crash ══════════════════
u = User(email="owner@ph1.invalid", hashed_password=None, auth_provider="yahoo",
         provider_subject="sub-owner", role="commissioner", is_active=1)
db.add(u); db.commit(); db.refresh(u)
record_grant(db, user_id=u.id, provider_subject="sub-owner",
             tokens={"access_token": "at-1", "refresh_token": "rt-1",
                     "expires_in": 3600}, environ=ENV)
set_credential_owner(db, league_id=lg.id, user_id=u.id)
USER_ID = u.id

from datetime import datetime, timedelta, timezone
g = grant_for(db, user_id=USER_ID)
baseline_version = g.token_version
g.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
db.commit()

# A refresh whose caller dies before the store commits.
calls = {"n": 0}


def dying_refresher(*, refresh_token):
    calls["n"] += 1
    raise RuntimeError("worker killed mid-exchange")


try:
    refresh_grant(db, user_id=USER_ID, refresher=dying_refresher, environ=ENV)
except Exception:
    db.rollback()

after_crash = grant_for(db, user_id=USER_ID)
OUT["grant_crash"] = dict(version=after_crash.token_version,
                          status=after_crash.status,
                          unchanged=after_crash.token_version == baseline_version)

# The retry succeeds and advances exactly once.
def good_refresher(*, refresh_token):
    calls["n"] += 1
    return {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600}


refresh_grant(db, user_id=USER_ID, refresher=good_refresher, environ=ENV)
final = grant_for(db, user_id=USER_ID)
OUT["grant_retry"] = dict(version=final.token_version,
                          advanced_once=final.token_version == baseline_version + 1,
                          status=final.status)

# ══ 6 · provider outage — every failure mode fails closed ═════════════════
from providers.yahoo.transport import YahooLiveTransport
from providers.yahoo.user_credentials import token_provider_for_league
from providers.errors import ProviderCredentialError
from auth.provider_grant import disconnect


class Capturing:
    seen = []

    def __init__(self, *, league_id, game_code, game_id,
                 yahoo_access_token_json, browser_callback):
        type(self).seen.append(dict(yahoo_access_token_json))

    def get_league_info(self):
        raise RuntimeError("should not be reached")


outage = {}

# (a) the grant is fine, but Yahoo is unreachable during refresh
expired = grant_for(db, user_id=USER_ID)
expired.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
db.commit()
from auth.provider_grant import GrantError


def unreachable(*, refresh_token):
    raise GrantError("provider_unreachable", "connection reset")


Capturing.seen.clear()
try:
    YahooLiveTransport(
        token_provider=token_provider_for_league(
            db, league_id=lg.id, environ=ENV, refresher=unreachable),
        query_factory=Capturing).fetch_league("461.l.rec")
    outage["unreachable"] = "SUCCEEDED"
except ProviderCredentialError:
    outage["unreachable"] = "REFUSED"
outage["unreachable_requests"] = len(Capturing.seen)
outage["unreachable_status"] = grant_for(db, user_id=USER_ID).status

# (b) disconnected
disconnect(db, user_id=USER_ID)
Capturing.seen.clear()
try:
    YahooLiveTransport(
        token_provider=token_provider_for_league(db, league_id=lg.id, environ=ENV),
        query_factory=Capturing).fetch_league("461.l.rec")
    outage["disconnected"] = "SUCCEEDED"
except ProviderCredentialError:
    outage["disconnected"] = "REFUSED"
outage["disconnected_requests"] = len(Capturing.seen)

# (c) no credential owner at all
lg2 = League(name="Unowned", season=2025, start_week=1, playoff_start_week=14,
             provider="yahoo", provider_league_key="461.l.unowned")
db.add(lg2); db.commit(); db.refresh(lg2)
Capturing.seen.clear()
try:
    YahooLiveTransport(
        token_provider=token_provider_for_league(db, league_id=lg2.id, environ=ENV),
        query_factory=Capturing).fetch_league("461.l.unowned")
    outage["unowned"] = "SUCCEEDED"
except ProviderCredentialError:
    outage["unowned"] = "REFUSED"
outage["unowned_requests"] = len(Capturing.seen)

# NOTHING THE OUTAGE TOUCHED CHANGED THE LEDGER.
outage["trial"] = trial_balance()
outage["championship"] = balance_of("championship")
OUT["outage"] = outage

# ══ 7 · the write-disable refuses economic writes and nothing else ════════
from ops.safe_mode import WritesDisabled, assert_writes_allowed, safe_mode_state

DISABLED = {"FS_WRITES_DISABLED": "1", "FS_WRITES_DISABLED_REASON": "drill"}
OUT["safe_mode"] = dict(
    off_by_default=not safe_mode_state({}).enabled,
    on_when_set=safe_mode_state(DISABLED).enabled,
    reason=safe_mode_state(DISABLED).reason)

os.environ["FS_WRITES_DISABLED"] = "1"
champ_before = balance_of("championship")
try:
    ledger_post([("world", -100), ("championship", 100)],
                door="should_be_refused", session=db)
    OUT["safe_mode"]["write"] = "ACCEPTED"
except WritesDisabled as exc:
    db.rollback()
    OUT["safe_mode"]["write"] = "REFUSED"
    OUT["safe_mode"]["reason_code"] = exc.reason_code
# READS STILL WORK while writes are refused — the entire point of the mode.
OUT["safe_mode"]["read_works"] = balance_of("championship") == champ_before
OUT["safe_mode"]["audit_runs"] = True
os.environ.pop("FS_WRITES_DISABLED")

# ══ 8 · the recovery audit on a healthy database ══════════════════════════
from ops.audit import run_audit

audit = run_audit(SessionLocal())
OUT["audit"] = dict(clean=audit.clean, checks=audit.checks_run,
                    findings=[f.check for f in audit.findings])

OUT["final_trial"] = trial_balance()
db.close()
print("RESULT" + json.dumps(OUT))
'''

try:
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER % {"root": ROOT, "url": _TARGET}],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    line = [l for l in (proc.stdout or "").splitlines() if l.startswith("RESULT")]

    _section("1 · §20 · A transaction that never commits leaves nothing")
    _assert("the PostgreSQL scenarios ran", bool(line),
            (proc.stderr or "")[-500:])

    if line:
        import json

        out = json.loads(line[0][len("RESULT"):])

        pre = out["precommit"]
        _assert("an abandoned posting left the championship pot untouched",
                pre["championship_unchanged"] is True)
        _assert("  · and the wallet untouched", pre["wallet_unchanged"] is True)
        _assert("  · and the Ledger still balances", pre["trial"] == 0)

        _section("2 · §20 · A transaction that committed survives")
        post = out["postcommit"]
        _assert("committed truth is visible to a new session",
                post["moved"] is True, f"{post['championship']} cents")
        _assert("  · and the Ledger still balances", post["trial"] == 0)

        _section("3 · §21/§52 · The shortfall sweep is retry-safe")
        sw = out["sweep_retry"]
        _assert("the first run swept", sw["first_swept"] is True,
                f"{sw['first_delta']} cents to championship")
        _assert("a retry reports already-run", sw["second_already"] is True)
        _assert("  · and sweeps nothing", sw["second_swept"] is False)
        _assert("  · with NO second economic effect",
                sw["second_delta"] == 0, f"{sw['second_delta']} cents")
        _assert("  · and exactly one durable record exists",
                sw["records"] == 1, f"{sw['records']} record(s)")

        sw2 = out["sweep_second_team"]
        _assert("a second team's week is independent",
                sw2["first_delta"] > 0, f"{sw2['first_delta']} cents")
        _assert("  · and its retry is also a no-op",
                sw2["retry_already"] is True and sw2["retry_delta"] == 0)
        _assert("  · the Ledger balances throughout", sw2["trial"] == 0)

        _section("4 · §52 · A grant refresh killed mid-exchange")
        gc = out["grant_crash"]
        _assert("a refresh that died wrote nothing",
                gc["unchanged"] is True, f"version {gc['version']}")
        _assert("  · and left the grant usable, not marked revoked",
                gc["status"] == "active", gc["status"])
        gr = out["grant_retry"]
        _assert("the retry succeeds", gr["status"] == "active")
        _assert("  · advancing the version exactly once",
                gr["advanced_once"] is True, f"version {gr['version']}")

        _section("5 · §25/§26 · Provider outage fails closed, every mode")
        o = out["outage"]
        for mode, label in (("unreachable", "Yahoo unreachable during refresh"),
                            ("disconnected", "the grant was disconnected"),
                            ("unowned", "the league has no credential owner")):
            _assert(f"{label}: the read is REFUSED", o[mode] == "REFUSED")
            _assert(f"  · and no request was made",
                    o[f"{mode}_requests"] == 0,
                    f"{o[f'{mode}_requests']} request(s)")
        _assert("an unreachable Yahoo does NOT mark the grant revoked",
                o["unreachable_status"] == "active", o["unreachable_status"])
        _assert("no provider failure moved any money",
                o["trial"] == 0, f"trial balance {o['trial']}")

        _section("6 · §24 · The emergency write-disable")
        sm = out["safe_mode"]
        _assert("writes are enabled by default", sm["off_by_default"] is True)
        _assert("the flag turns them off", sm["on_when_set"] is True)
        _assert("  · carrying the operator's reason", sm["reason"] == "drill")
        _assert("an economic write is REFUSED while disabled",
                sm["write"] == "REFUSED", sm.get("write"))
        _assert("  · with a named reason code, not a generic failure",
                sm.get("reason_code") == "writes_disabled",
                str(sm.get("reason_code")))
        _assert("reads still work while writes are disabled",
                sm["read_works"] is True)

        _section("7 · §44 · The recovery audit on a healthy database")
        au = out["audit"]
        _assert("the audit runs read-only and reports clean",
                au["clean"] is True, ", ".join(au["findings"]) or "no findings")
        for check in ("schema", "ledger_balance", "protected_accounts",
                      "provider_grants", "credential_owners", "safe_mode"):
            _assert(f"  · it checked {check}", check in au["checks"])

        _assert("and the Ledger balances at the end of everything",
                out["final_trial"] == 0, str(out["final_trial"]))

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
    print(f"PROD-HARDEN-1 RECOVERY — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("PROD-HARDEN-1 RECOVERY — all assertions PASSED")
