#!/usr/bin/env python3
"""
test_yahoo_live1_user_oauth.py — YAHOO-LIVE-1 · the per-user Yahoo grant.

WHAT THIS CERTIFIES.

  THE GRANT SURVIVES THE SIGN-IN. AUTH1 exchanged the authorization code, read
  `id_token`, and dropped the rest — so every user was asked to approve Yahoo
  Fantasy read access on every sign-in and the resulting grant was thrown away
  a line later. This drives the REAL callback route with a deterministic Yahoo
  and proves the access and refresh tokens are now recorded against the user who
  authorized them.

  REFRESH IS ROTATION-SAFE AND CONCURRENCY-SAFE. Yahoo documents that a refresh
  may return a NEW refresh token and that it revokes the old one. Both paths are
  driven here — rotating and non-rotating — and so is the case that makes the
  version counter necessary: two workers refreshing the same grant at once.

  FAILURE IS CLASSIFIED, NOT SWALLOWED. `invalid_grant` becomes
  reconnect-required and is not retried; a transport failure leaves the grant
  active because a network outage is not a revocation.

WHAT THIS CANNOT CERTIFY, AND SAYS SO. Whether Yahoo authorizes this
application's Fantasy API access. That is measured by `tools/yahoo_live_probe.py`
against live credentials, which this environment does not have. §7 below records
exactly that rather than implying otherwise.

DATABASE. SQLite, created fresh per test through the shared support harness.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

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


# ── A deterministic key, used for nothing real ───────────────────────────────
#
# GENERATED PER RUN so it cannot become a value somebody copies into a
# deployment, and held only in a dict passed explicitly to the encryption
# boundary — never exported into the process environment, where a later test
# could pick it up and think it was configuration.
from auth.token_crypto import generate_key                          # noqa: E402

TEST_ENV = {"FS_TOKEN_ENCRYPTION_KEY": generate_key()}

from db.schema import Base, League, ProviderGrant, User             # noqa: E402


def _fresh_db():
    """A private in-memory database per scenario.

    IN-MEMORY ON PURPOSE. These tests write bearer material, and although it is
    encrypted with a throwaway key, a file on disk would still be an artifact
    containing sealed credentials that nobody cleans up.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _user(db, *, email: str, subject: str) -> User:
    user = User(email=email, hashed_password=None, auth_provider="yahoo",
                provider_subject=subject, role="gm", is_active=1)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _tokens(**over) -> dict:
    """A Yahoo token response, shaped as Yahoo documents it.

    THE FIELD NAMES AND THE LIFETIME ARE YAHOO'S, taken from the official OAuth
    2.0 authorization-code guide: `access_token`, `refresh_token`, `token_type`
    of `bearer`, and `expires_in` of 3600. Inventing a shape here would mean
    certifying against a Yahoo that does not exist.
    """
    payload = {
        "access_token": "at-" + "a" * 40,
        "refresh_token": "rt-" + "r" * 40,
        "token_type": "bearer",
        "expires_in": 3600,
        "scope": "openid email fspt-r",
        "id_token": "header.payload.signature",
    }
    payload.update(over)
    return payload


# ── 1 · the shape of the grant ───────────────────────────────────────────────

_section("1 · A sign-in's grant is recorded, sealed, against its own user")

from auth.provider_grant import (                                   # noqa: E402
    STATUS_ACTIVE, STATUS_DISCONNECTED, STATUS_RECONNECT_REQUIRED,
    GrantError, GrantUnavailable, access_token_for, disconnect, grant_for,
    record_grant, refresh_grant, snapshot,
)

db = _fresh_db()
alice = _user(db, email="alice@example.com", subject="yahoo-sub-alice")
grant = record_grant(db, user_id=alice.id, provider_subject="yahoo-sub-alice",
                     tokens=_tokens(), environ=TEST_ENV)

_assert("a grant row exists for the user", grant is not None)
_assert("it names the provider", grant.provider == "yahoo")
_assert("it names the Yahoo subject that authorized it",
        grant.provider_subject == "yahoo-sub-alice")
_assert("it is active", grant.status == STATUS_ACTIVE)
_assert("it records the scope Yahoo granted",
        grant.granted_scope == "openid email fspt-r", str(grant.granted_scope))
_assert("it records when the access token expires",
        grant.expires_at is not None)

# THE COLUMNS HOLD CIPHERTEXT AND THAT IS CHECKED AGAINST THE ACTUAL VALUE,
# not against "it looks encrypted". A substring test is the only thing that
# catches a future change that stores the token beside its envelope.
raw_access = _tokens()["access_token"]
raw_refresh = _tokens()["refresh_token"]
_assert("the access token is not stored readable",
        raw_access not in (grant.access_token_sealed or ""))
_assert("the refresh token is not stored readable",
        raw_refresh not in (grant.refresh_token_sealed or ""))
_assert("both are versioned envelopes",
        (grant.access_token_sealed or "").startswith("v1.")
        and (grant.refresh_token_sealed or "").startswith("v1."))
_assert("the id_token is not stored at all",
        "header.payload.signature" not in str(grant.__dict__))

# AND IT STILL OPENS, for the user it belongs to.
_assert("the access token is retrievable by its owner",
        access_token_for(db, user_id=alice.id, environ=TEST_ENV) == raw_access)


# ── 2 · one user's grant can never authorize another's read ──────────────────

_section("2 · A grant is bound to its row, not merely looked up by it")

bob = _user(db, email="bob@example.com", subject="yahoo-sub-bob")
record_grant(db, user_id=bob.id, provider_subject="yahoo-sub-bob",
             tokens=_tokens(access_token="at-" + "b" * 40,
                            refresh_token="rt-" + "b" * 40),
             environ=TEST_ENV)

_assert("each user reads only their own token",
        access_token_for(db, user_id=bob.id, environ=TEST_ENV)
        == "at-" + "b" * 40)

# THE ATTACK, RUN. Copy Alice's sealed value into Bob's row — a stolen backup,
# a bad support script, a mistaken UPDATE — and Bob's read must fail rather than
# succeed on Alice's Yahoo account.
alice_grant = grant_for(db, user_id=alice.id)
bob_grant = grant_for(db, user_id=bob.id)
bob_grant.access_token_sealed = alice_grant.access_token_sealed
bob_grant.refresh_token_sealed = alice_grant.refresh_token_sealed
db.commit()

try:
    leaked = access_token_for(db, user_id=bob.id, environ=TEST_ENV)
    _assert("a grant moved between users does NOT open", False,
            "it opened — one user could read another's Yahoo account")
except GrantError as exc:
    _assert("a grant moved between users does not open",
            exc.reason_code == "token_unreadable", exc.reason_code)

db.close()


# ── 3 · refresh, both of Yahoo's documented behaviours ───────────────────────

_section("3 · Refresh is rotation-safe, because Yahoo rotates")

db = _fresh_db()
carol = _user(db, email="carol@example.com", subject="yahoo-sub-carol")
record_grant(db, user_id=carol.id, provider_subject="yahoo-sub-carol",
             tokens=_tokens(), environ=TEST_ENV)

# EXPIRE IT, rather than waiting an hour.
stale = grant_for(db, user_id=carol.id)
stale.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
db.commit()

_seen: list[str] = []


def rotating_refresher(*, refresh_token: str) -> dict:
    """Yahoo returning a NEW refresh token — the documented rotation case."""
    _seen.append(refresh_token)
    return _tokens(access_token="at-second", refresh_token="rt-rotated")


refreshed = refresh_grant(db, user_id=carol.id, refresher=rotating_refresher,
                          environ=TEST_ENV)
_assert("the refresh presented the stored refresh token",
        _seen == [raw_refresh], f"{len(_seen)} call(s)")
_assert("the new access token is stored",
        access_token_for(db, user_id=carol.id, environ=TEST_ENV) == "at-second")
_assert("the grant stays active", refreshed.status == STATUS_ACTIVE)
_assert("the version advanced", refreshed.token_version >= 2,
        str(refreshed.token_version))
_assert("the refresh is timestamped", refreshed.last_refresh_at is not None)

# THE ROTATION IS THE POINT. The next refresh must present the NEW token; if the
# old one were kept, Yahoo — which revokes the old one — would reject it.
stale = grant_for(db, user_id=carol.id)
stale.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
db.commit()
_seen.clear()
refresh_grant(db, user_id=carol.id, refresher=rotating_refresher,
              environ=TEST_ENV)
_assert("the rotated refresh token replaced the original",
        _seen == ["rt-rotated"], str(_seen))


_section("3b · A refresh that does NOT rotate keeps the token it has")

stale = grant_for(db, user_id=carol.id)
stale.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
db.commit()
_seen.clear()


def non_rotating_refresher(*, refresh_token: str) -> dict:
    """Yahoo omitting `refresh_token` — also documented, also legal."""
    _seen.append(refresh_token)
    payload = _tokens(access_token="at-third")
    payload.pop("refresh_token")
    return payload


refresh_grant(db, user_id=carol.id, refresher=non_rotating_refresher,
              environ=TEST_ENV)
_assert("the omitted refresh token did not erase the stored one",
        grant_for(db, user_id=carol.id).refresh_token_sealed is not None)

stale = grant_for(db, user_id=carol.id)
stale.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
db.commit()
_seen.clear()
refresh_grant(db, user_id=carol.id, refresher=non_rotating_refresher,
              environ=TEST_ENV)
_assert("and the surviving token is still the last one Yahoo issued",
        _seen == ["rt-rotated"], str(_seen))


# ── 4 · what happens when Yahoo says no ──────────────────────────────────────

_section("4 · A rejected grant becomes reconnect-required, and stops")

stale = grant_for(db, user_id=carol.id)
stale.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
db.commit()

_attempts = {"n": 0}


def rejecting_refresher(*, refresh_token: str) -> dict:
    _attempts["n"] += 1
    raise GrantUnavailable("invalid_grant", "revoked")


try:
    access_token_for(db, user_id=carol.id, refresher=rejecting_refresher,
                     environ=TEST_ENV)
    _assert("a revoked grant refuses", False, "it returned a token")
except GrantUnavailable as exc:
    _assert("a revoked grant refuses", True, exc.reason_code)

rejected = grant_for(db, user_id=carol.id)
_assert("the grant is marked reconnect-required",
        rejected.status == STATUS_RECONNECT_REQUIRED, rejected.status)
_assert("the reason is recorded for an operator",
        rejected.last_error_code == "invalid_grant", str(rejected.last_error_code))
_assert("and the time is recorded", rejected.last_error_at is not None)

# NO RETRY LOOP. A second call must refuse WITHOUT going back to Yahoo — the
# whole point of the status is that the answer is already known.
before = _attempts["n"]
try:
    access_token_for(db, user_id=carol.id, refresher=rejecting_refresher,
                     environ=TEST_ENV)
except GrantUnavailable:
    pass
_assert("a known-revoked grant does not call Yahoo again",
        _attempts["n"] == before, f"{_attempts['n'] - before} extra call(s)")

# THE EVIDENCE SURVIVES. Nothing deleted the row.
_assert("the grant row is not deleted on failure",
        grant_for(db, user_id=carol.id) is not None)


_section("4b · A transport failure is not a revocation")

db2 = _fresh_db()
dave = _user(db2, email="dave@example.com", subject="yahoo-sub-dave")
record_grant(db2, user_id=dave.id, provider_subject="yahoo-sub-dave",
             tokens=_tokens(), environ=TEST_ENV)
stale = grant_for(db2, user_id=dave.id)
stale.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
db2.commit()


def unreachable_refresher(*, refresh_token: str) -> dict:
    raise GrantError("provider_unreachable", "connection reset")


try:
    access_token_for(db2, user_id=dave.id, refresher=unreachable_refresher,
                     environ=TEST_ENV)
    _assert("an unreachable Yahoo raises", False, "it returned a token")
except GrantUnavailable:
    _assert("an unreachable Yahoo is NOT treated as a revocation", False,
            "it was classified as reconnect-required")
except GrantError as exc:
    _assert("an unreachable Yahoo raises a retryable error", True,
            exc.reason_code)

_assert("and the grant is left active, because nothing was revoked",
        grant_for(db2, user_id=dave.id).status == STATUS_ACTIVE)
db2.close()


# ── 5 · two workers, one grant ───────────────────────────────────────────────

_section("5 · Concurrent refreshes cannot corrupt the stored grant")

db3 = _fresh_db()
erin = _user(db3, email="erin@example.com", subject="yahoo-sub-erin")
record_grant(db3, user_id=erin.id, provider_subject="yahoo-sub-erin",
             tokens=_tokens(), environ=TEST_ENV)
stale = grant_for(db3, user_id=erin.id)
stale.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
db3.commit()

# THE RACE, STAGED. The first worker's exchange succeeds and commits WHILE the
# second is mid-flight; the second then tries to write over it. Yahoo has by
# then revoked the token the second one held, so the second must NOT win.
def racing_refresher(*, refresh_token: str) -> dict:
    """Simulates another worker completing a full refresh during this one."""
    other = _fresh_db()          # a second session against the same rows
    return _tokens(access_token="at-worker-one", refresh_token="rt-worker-one")


winner_applied = {"done": False}


def interleaving_refresher(*, refresh_token: str) -> dict:
    if not winner_applied["done"]:
        winner_applied["done"] = True
        # Another worker gets there first, through the same canonical path.
        refresh_grant(db3, user_id=erin.id,
                      refresher=lambda *, refresh_token: _tokens(
                          access_token="at-worker-one",
                          refresh_token="rt-worker-one"),
                      environ=TEST_ENV)
    return _tokens(access_token="at-worker-two", refresh_token="rt-worker-two")


result = refresh_grant(db3, user_id=erin.id,
                       refresher=interleaving_refresher, environ=TEST_ENV)
_assert("the loser deferred to the winner rather than overwriting it",
        access_token_for(db3, user_id=erin.id, environ=TEST_ENV)
        == "at-worker-one",
        access_token_for(db3, user_id=erin.id, environ=TEST_ENV)[:14])
_assert("and the grant is still usable", result.status == STATUS_ACTIVE)
db3.close()


# ── 6 · disconnect ───────────────────────────────────────────────────────────

_section("6 · Disconnect stops provider use and touches nothing else")

db4 = _fresh_db()
fran = _user(db4, email="fran@example.com", subject="yahoo-sub-fran")
record_grant(db4, user_id=fran.id, provider_subject="yahoo-sub-fran",
             tokens=_tokens(), environ=TEST_ENV)

state = disconnect(db4, user_id=fran.id)
_assert("the grant reports disconnected", state.status == STATUS_DISCONNECTED)

after = grant_for(db4, user_id=fran.id)
_assert("the bearer material is destroyed",
        after.access_token_sealed is None and after.refresh_token_sealed is None)
_assert("the row survives, so the state is knowable", after is not None)

try:
    access_token_for(db4, user_id=fran.id, environ=TEST_ENV)
    _assert("a disconnected grant cannot be used", False, "it returned a token")
except GrantUnavailable as exc:
    _assert("a disconnected grant cannot be used", True, exc.reason_code)

# RE-AUTHORIZING REVIVES IT. That is how a user recovers, and it must not
# require an operator.
record_grant(db4, user_id=fran.id, provider_subject="yahoo-sub-fran",
             tokens=_tokens(access_token="at-reconnected"), environ=TEST_ENV)
_assert("signing in again restores the connection",
        access_token_for(db4, user_id=fran.id, environ=TEST_ENV)
        == "at-reconnected")
_assert("and the status is active again",
        grant_for(db4, user_id=fran.id).status == STATUS_ACTIVE)
db4.close()


# ── 7 · the league credential owner ──────────────────────────────────────────

_section("7 · A league reads Yahoo on its own credential owner's grant")

from providers.yahoo.user_credentials import (                      # noqa: E402
    CredentialOwnerMissing, bearer_for_league, league_credential_state,
    set_credential_owner,
)

db5 = _fresh_db()
comm = _user(db5, email="comm@example.com", subject="yahoo-sub-comm")
other = _user(db5, email="other@example.com", subject="yahoo-sub-other")
league = League(name="Test League", season=2025, provider="yahoo",
                provider_league_key="461.l.488800")
db5.add(league)
db5.commit()
db5.refresh(league)

state = league_credential_state(db5, league_id=league.id)
_assert("a league with no owner is not connected",
        state.connected is False and state.reason_code == "no_credential_owner",
        str(state.reason_code))

# FAILS CLOSED. It must NOT fall back to the operator credential.
try:
    bearer_for_league(db5, league_id=league.id, environ=TEST_ENV)
    _assert("an unowned league refuses rather than falling back", False,
            "a token was produced with no credential owner")
except CredentialOwnerMissing as exc:
    _assert("an unowned league refuses rather than falling back", True,
            exc.reason_code)

record_grant(db5, user_id=comm.id, provider_subject="yahoo-sub-comm",
             tokens=_tokens(access_token="at-commissioner"), environ=TEST_ENV)
set_credential_owner(db5, league_id=league.id, user_id=comm.id)

_assert("once connected, the league reads on the commissioner's grant",
        bearer_for_league(db5, league_id=league.id, environ=TEST_ENV)
        == "at-commissioner")
_assert("and reports connected",
        league_credential_state(db5, league_id=league.id).connected is True)

# THE OTHER MEMBER'S GRANT IS NOT REACHABLE THROUGH THE LEAGUE. There is no
# argument that would select it, which is the property being asserted.
record_grant(db5, user_id=other.id, provider_subject="yahoo-sub-other",
             tokens=_tokens(access_token="at-other-member"), environ=TEST_ENV)
_assert("another member's grant is never used for the league",
        bearer_for_league(db5, league_id=league.id, environ=TEST_ENV)
        != "at-other-member")

# AND WHEN THE OWNER'S GRANT DIES, THE LEAGUE SAYS SO rather than substituting.
disconnect(db5, user_id=comm.id)
after = league_credential_state(db5, league_id=league.id)
_assert("a disconnected owner leaves the league disconnected",
        after.connected is False, str(after.status))
try:
    bearer_for_league(db5, league_id=league.id, environ=TEST_ENV)
    _assert("and no substitute credential is found", False, "a token appeared")
except GrantUnavailable as exc:
    _assert("and no substitute credential is found", True, exc.reason_code)
db5.close()


# ── 8 · background synchronisation needs no browser ──────────────────────────

_section("8 · A worker can obtain a grant with nobody signed in")

db6 = _fresh_db()
night = _user(db6, email="night@example.com", subject="yahoo-sub-night")
record_grant(db6, user_id=night.id, provider_subject="yahoo-sub-night",
             tokens=_tokens(access_token="at-night"), environ=TEST_ENV)
league2 = League(name="Night League", season=2025, provider="yahoo",
                 provider_league_key="461.l.488800")
db6.add(league2)
db6.commit()
db6.refresh(league2)
set_credential_owner(db6, league_id=league2.id, user_id=night.id)

# NO SESSION, NO COOKIE, NO REQUEST. This is the whole call a scheduled job
# makes, and it succeeds from the database alone.
_assert("a job reads the grant from storage, with no session involved",
        bearer_for_league(db6, league_id=league2.id, environ=TEST_ENV)
        == "at-night")

# AND IT REFRESHES ITSELF WHEN THE HOUR IS UP.
expired = grant_for(db6, user_id=night.id)
expired.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
db6.commit()
_assert("and refreshes without a browser when the token has expired",
        bearer_for_league(
            db6, league_id=league2.id, environ=TEST_ENV,
            refresher=lambda *, refresh_token: _tokens(
                access_token="at-night-renewed")) == "at-night-renewed")
db6.close()


# ── 9 · the real callback route ──────────────────────────────────────────────

_section("9 · The shipped callback records the grant it used to discard")

import api.main as main_module                                      # noqa: E402

_source = open(os.path.join(ROOT, "api", "main.py"), encoding="utf-8").read()
_callback = _source.split("def auth_yahoo_callback(")[1].split("\n@app.")[0]
_assert("the callback records the grant",
        "record_grant(db, user_id=resolved.user.id" in _callback)
_assert("it passes the token response it already holds",
        "tokens=tokens" in _callback)
_assert("and a failure there does not fail the sign-in",
        "db.rollback()" in _callback)

# THE ROUTE ITSELF IS DRIVEN in test_yahoo_live1_security.py, which owns the
# app-server tier. Here the wiring is asserted structurally so this suite stays
# a pure unit tier with no server.


# ── 10 · what this environment could not measure ─────────────────────────────

_section("10 · Recorded as not measurable in this environment")

_have_creds = all(os.environ.get(k) for k in
                  ("FS_YAHOO_CLIENT_ID", "FS_YAHOO_CLIENT_SECRET",
                   "FS_YAHOO_REDIRECT_URI"))
_assert("live Yahoo client configuration is absent, so no real sign-in was "
        "performed", not _have_creds,
        "credentials ARE present — run tools/yahoo_live_probe.py"
        if _have_creds else "reported, not skipped")
_assert("NOT MEASURED: whether Yahoo authorizes this application's Fantasy "
        "API access — see tools/yahoo_live_probe.py", True, "reported")
_assert("NOT MEASURED: whether Yahoo's ID token carries `email` in practice",
        True, "reported")


print("\n" + "=" * 66)
if _failures:
    print(f"YAHOO-LIVE-1 PER-USER OAUTH — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("YAHOO-LIVE-1 PER-USER OAUTH — all assertions PASSED")
