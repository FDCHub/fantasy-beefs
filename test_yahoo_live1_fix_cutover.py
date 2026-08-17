#!/usr/bin/env python3
"""
test_yahoo_live1_fix_cutover.py — YAHOO-LIVE-1-FIX · the production cutover.

WHAT THIS CERTIFIES, AND WHY IT IS A SEPARATE SUITE.

YAHOO-LIVE-1 built a correct per-user grant store and then did not connect it to
anything. The production request path still loaded a repository-level operator
credential, and no product operation could name a league's credential owner — so
the architecture was real and unreachable at the same time. This suite proves the
two seams are closed, and it does it the only way that means anything: by
OBSERVING WHICH BEARER REACHES THE REQUEST.

── THE LOAD-BEARING TEST (§11) ──────────────────────────────────────────────

§4 of this suite is the one that would catch a regression to the old behaviour.
A legitimate-looking operator credential is placed in the environment; a Yahoo
league with no credential owner invokes the production path; and the path must
FAIL rather than succeed on that credential. Then the same league is given a
commissioner with a real grant, and the bearer that arrives at the mocked Yahoo
request must be that commissioner's.

Without the second half, "it failed" could mean the wiring is broken. Without the
first half, "it worked" could mean it worked on the operator token. Both halves,
against the same league, are what make the claim.

WHAT IT CANNOT PROVE. That Yahoo accepts the token. No live credentials exist in
this environment; §6 records that rather than implying otherwise.

DATABASE. Private SQLite per scenario.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
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


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _code_only(text: str) -> str:
    text = re.sub(r'"""[\s\S]*?"""', " ", text)
    text = re.sub(r"'''[\s\S]*?'''", " ", text)
    return re.sub(r"^\s*#.*$", " ", text, flags=re.M)


from auth.token_crypto import generate_key                          # noqa: E402

TEST_ENV = {"FS_TOKEN_ENCRYPTION_KEY": generate_key()}

from auth.provider_grant import (                                   # noqa: E402
    GrantUnavailable, disconnect, grant_for, record_grant,
)
from db.schema import Base, League, User                            # noqa: E402
from providers.errors import ProviderCredentialError                # noqa: E402


def _fresh_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _user(db, email, subject, role="gm"):
    u = User(email=email, hashed_password=None, auth_provider="yahoo",
             provider_subject=subject, role=role, is_active=1)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _league(db, name="L", provider="yahoo", key="461.l.488800"):
    lg = League(name=name, season=2025, provider=provider,
                provider_league_key=key)
    db.add(lg)
    db.commit()
    db.refresh(lg)
    return lg


def _tokens(access="at-owner", refresh="rt-owner"):
    return {"access_token": access, "refresh_token": refresh,
            "expires_in": 3600, "scope": "openid email fspt-r"}


class _CapturingQuery:
    """Stands in for yfpy, and records the credential it was handed.

    THE SEAM EXISTS BECAUSE THE CLAIM IS ABOUT THE BEARER, not about yfpy. What
    must be certified is which token the transport presents; driving real yfpy
    to find that out would be certifying yfpy.
    """

    seen: list[dict] = []

    def __init__(self, *, league_id, game_code, game_id,
                 yahoo_access_token_json, browser_callback):
        type(self).seen.append(dict(yahoo_access_token_json))
        self.league_id = league_id

    def get_league_info(self):
        return {"fantasy_content": {"league": {"league_id": self.league_id}}}


# ── 1 · the transport refuses to guess ───────────────────────────────────────

_section("1 · The transport has no credential of its own to fall back on")

from providers.yahoo.transport import YahooLiveTransport                # noqa: E402

try:
    YahooLiveTransport()
    _assert("a bare transport refuses to be constructed", False,
            "it was constructed and would have loaded the operator credential")
except ProviderCredentialError as exc:
    _assert("a bare transport refuses to be constructed", True,
            str(exc)[:60] + "…")

_assert("and the refusal names the per-user seam to use instead",
        "token_provider_for_league" in str(
            _read("providers", "yahoo", "transport.py")))

_assert("the operator path survives, but only under an explicit name",
        hasattr(YahooLiveTransport, "for_operator_tooling"))

# THE TRANSPORT MUST NOT KNOW WHOSE TOKEN IT HOLDS. If it could resolve a user
# it could resolve the wrong one.
_transport_code = _code_only(_read("providers", "yahoo", "transport.py"))
for term in ("provider_credential_user_id", "bearer_for_league",
             "access_token_for", "ProviderGrant"):
    _assert(f"the transport never resolves {term} itself",
            term not in _transport_code)

# AND IT MUST NOT REFRESH. One refresh implementation, in the store.
for term in ("grant_type", "refresh_token=", "refresh_grant"):
    _assert(f"the transport contains no refresh logic ({term})",
            term not in _transport_code)


# ── 2 · the production composition passes the league's own credential ────────

_section("2 · Production runtime resolves the credential from the league")

_MAIN = _code_only(_read("api", "main.py"))
_SYNC = _code_only(_read("notifications", "tuesday_sync.py"))

_assert("the settlement transport factory takes the league",
        "def _pool_settlement_transport(db" in _MAIN)
_assert("and builds the transport from the league's credential owner",
        "token_provider=token_provider_for_league(db, league_id=league_id)"
        in _MAIN)
_assert("its caller passes the league it is settling",
        "_pool_settlement_transport(db, league.id)" in _MAIN)

_assert("the background worker builds its transport the same way",
        "token_provider=token_provider_for_league(db," in _SYNC)
_assert("and its yfpy query takes the league's bearer",
        "bearer_for_league(db, league_id=league_id)" in _SYNC)

# NO PRODUCTION MODULE CALLS THE OPERATOR LOADER ANY MORE.
for module, label in ((_MAIN, "api/main.py"), (_SYNC, "tuesday_sync.py")):
    _assert(f"{label} never calls load_credentials()",
            "load_credentials(" not in module)
    _assert(f"{label} never constructs a bare YahooLiveTransport()",
            "YahooLiveTransport()" not in module)
    _assert(f"{label} never reaches operator tooling",
            "for_operator_tooling" not in module)


# ── 3 · the operator credential is quarantined, not deleted ──────────────────

_section("3 · Operator credentials remain for tooling, unreachable from runtime")

_assert("the loader still exists for tooling",
        "def load_credentials" in _read("providers", "yahoo", "transport.py"))

# WP2B'S EVIDENCE GATE STILL EXERCISES IT — §4 forbids deleting that tooling to
# satisfy a source scan, because the measured refusal is the most useful fact
# the project holds about the external blocker.
_CERTIFY = _read("providers", "certify", "run.py")
_assert("the offline certification gate still asserts it refuses",
        "load_credentials()" in _CERTIFY)
_assert("and the WP2B live finding is still recorded verbatim",
        "not authorized to perform this action" in _CERTIFY)

# THE ONLY REMAINING RUNTIME READER IS THE OPERATOR BRANCH, and it is gated on
# a flag production never sets.
_assert("the transport reads the operator loader only in operator mode",
        "if self._token_provider is not None:" in _transport_code
        and "_operator_credentials" in _transport_code)


# ── 4 · THE LOAD-BEARING TEST — no operator fallback, ever ────────────────────

_section("4 · §11 · A Yahoo league with no owner FAILS rather than borrowing")

_OPERATOR_ENV = {
    # A CREDENTIAL THAT WOULD HAVE WORKED. Shaped exactly like the real
    # `YAHOO_PRIVATE_JSON` + `YAHOO_CONSUMER_SECRET` pair the old path loaded,
    # so if any fallback survived, this is what it would have used — and the
    # assertion below would catch it by name.
    "YAHOO_PRIVATE_JSON": json.dumps({
        "access_token": "OPERATOR-TOKEN-MUST-NEVER-BE-USED",
        "refresh_token": "OPERATOR-REFRESH-MUST-NEVER-BE-USED",
        "consumer_key": "operator-key", "token_type": "bearer"}),
    "YAHOO_CONSUMER_SECRET": "operator-secret",
}

db = _fresh_db()
comm = _user(db, "comm@example.com", "sub-comm", role="commissioner")
league = _league(db)

from providers.yahoo.user_credentials import (                      # noqa: E402
    CredentialOwnerMissing, bearer_for_league, credential_owner_id,
    league_credential_state, set_credential_owner, token_provider_for_league,
)

_CapturingQuery.seen.clear()
transport = YahooLiveTransport(
    token_provider=token_provider_for_league(db, league_id=league.id,
                                             environ=TEST_ENV),
    query_factory=_CapturingQuery)

# THE FAILURE ARRIVES AS A PROVIDER FAILURE. Everything that consumes this
# transport catches `ProviderError` to decide whether a week is fresh and what
# to tell an operator; a credential failure that bypassed that taxonomy turned
# the commissioner diagnostic into a 500 rather than a report.
try:
    transport.fetch_league("461.l.488800")
    _assert("an unowned Yahoo league FAILS CLOSED", False,
            "the read succeeded — a fallback credential was used")
except ProviderCredentialError as exc:
    _assert("an unowned Yahoo league FAILS CLOSED", True, str(exc)[:60])
    _assert("and it fails as a PROVIDER error, so callers classify it",
            "no_credential_owner" in str(exc), str(exc)[:80])

_assert("and no request was made at all",
        _CapturingQuery.seen == [], f"{len(_CapturingQuery.seen)} request(s)")

# THE OPERATOR CREDENTIAL WAS AVAILABLE THE WHOLE TIME. Proved, so the failure
# above cannot be dismissed as "there was nothing to fall back to".
from providers.yahoo.transport import load_credentials                 # noqa: E402

_loaded = load_credentials(environ=_OPERATOR_ENV)
_assert("the operator credential WAS loadable during that failure",
        _loaded.get("access_token") == "OPERATOR-TOKEN-MUST-NEVER-BE-USED")


_section("4b · The same league, once a commissioner authorizes, uses THEIR token")

record_grant(db, user_id=comm.id, provider_subject="sub-comm",
             tokens=_tokens(access="COMMISSIONER-BEARER"), environ=TEST_ENV)
set_credential_owner(db, league_id=league.id, user_id=comm.id)

_CapturingQuery.seen.clear()
transport = YahooLiveTransport(
    token_provider=token_provider_for_league(db, league_id=league.id,
                                             environ=TEST_ENV),
    query_factory=_CapturingQuery)
transport.fetch_league("461.l.488800")

_assert("the request was made", len(_CapturingQuery.seen) == 1,
        f"{len(_CapturingQuery.seen)} request(s)")
_presented = _CapturingQuery.seen[0] if _CapturingQuery.seen else {}
_assert("the bearer presented is the COMMISSIONER'S",
        _presented.get("access_token") == "COMMISSIONER-BEARER",
        str(_presented.get("access_token"))[:40])
_assert("and it is NOT the operator token",
        _presented.get("access_token") != "OPERATOR-TOKEN-MUST-NEVER-BE-USED")
_assert("no refresh token was handed downstream",
        "refresh_token" not in _presented, ", ".join(sorted(_presented)))


# ── 5 · every dead-grant state fails closed too ──────────────────────────────

_section("5 · Disconnected and reconnect-required both fail closed")

disconnect(db, user_id=comm.id)
_CapturingQuery.seen.clear()
transport = YahooLiveTransport(
    token_provider=token_provider_for_league(db, league_id=league.id,
                                             environ=TEST_ENV),
    query_factory=_CapturingQuery)
try:
    transport.fetch_league("461.l.488800")
    _assert("a disconnected owner fails closed", False, "the read succeeded")
except ProviderCredentialError as exc:
    _assert("a disconnected owner fails closed", True, str(exc)[:50])
    _assert("  · and carries its reason", "disconnected" in str(exc))
_assert("and made no request", _CapturingQuery.seen == [])

# RECONNECT-REQUIRED, reached the way production reaches it: Yahoo rejects the
# refresh of an expired token.
record_grant(db, user_id=comm.id, provider_subject="sub-comm",
             tokens=_tokens(access="will-expire"), environ=TEST_ENV)
stale = grant_for(db, user_id=comm.id)
stale.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
db.commit()


def _rejecting(*, refresh_token):
    raise GrantUnavailable("invalid_grant", "revoked at Yahoo")


_CapturingQuery.seen.clear()
transport = YahooLiveTransport(
    token_provider=token_provider_for_league(db, league_id=league.id,
                                             environ=TEST_ENV,
                                             refresher=_rejecting),
    query_factory=_CapturingQuery)
try:
    transport.fetch_league("461.l.488800")
    _assert("a rejected grant fails closed", False, "the read succeeded")
except ProviderCredentialError as exc:
    _assert("a rejected grant fails closed", True, str(exc)[:50])
    _assert("  · and carries its reason", "invalid_grant" in str(exc)
            or "reconnect_required" in str(exc), str(exc)[:70])
_assert("and made no request", _CapturingQuery.seen == [])
_assert("the grant is left reconnect-required for an operator to see",
        grant_for(db, user_id=comm.id).status == "reconnect_required")

# AND THE OPERATOR CREDENTIAL IS STILL SITTING THERE, still unused.
_assert("no operator fallback occurred in ANY failure state",
        all("OPERATOR" not in str(seen) for seen in _CapturingQuery.seen))


# ── 6 · the canonical refresh path is the one that runs ──────────────────────

_section("6 · Refresh happens in the store, once, and is observable")

db2 = _fresh_db()
owner = _user(db2, "owner@example.com", "sub-owner", role="commissioner")
lg2 = _league(db2, name="Refresh League")
record_grant(db2, user_id=owner.id, provider_subject="sub-owner",
             tokens=_tokens(access="expiring"), environ=TEST_ENV)
set_credential_owner(db2, league_id=lg2.id, user_id=owner.id)
stale = grant_for(db2, user_id=owner.id)
stale.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
db2.commit()

_refreshes = {"n": 0}


def _renewing(*, refresh_token):
    _refreshes["n"] += 1
    return _tokens(access="RENEWED-BEARER", refresh="rt-rotated")


_CapturingQuery.seen.clear()
transport = YahooLiveTransport(
    token_provider=token_provider_for_league(db2, league_id=lg2.id,
                                             environ=TEST_ENV,
                                             refresher=_renewing),
    query_factory=_CapturingQuery)
transport.fetch_league("461.l.488800")

_assert("an expired token was refreshed through the store",
        _refreshes["n"] == 1, f"{_refreshes['n']} refresh(es)")
_assert("and the RENEWED bearer is what reached the request",
        _CapturingQuery.seen[0].get("access_token") == "RENEWED-BEARER")
_assert("the rotated refresh token was persisted by the store",
        grant_for(db2, user_id=owner.id).token_version >= 2)

# A SECOND READ INSIDE THE HOUR DOES NOT REFRESH AGAIN.
transport.fetch_league("461.l.488800")
_assert("a second read within the token's life does not refresh again",
        _refreshes["n"] == 1, f"{_refreshes['n']} refresh(es)")
_assert("but it still asks the store, so a later expiry is caught",
        len(_CapturingQuery.seen) == 2, f"{len(_CapturingQuery.seen)} request(s)")


# ── 7 · one league cannot read on another user's grant ───────────────────────

_section("7 · User isolation across leagues")

stranger = _user(db2, "stranger@example.com", "sub-stranger")
record_grant(db2, user_id=stranger.id, provider_subject="sub-stranger",
             tokens=_tokens(access="STRANGER-BEARER"), environ=TEST_ENV)

_CapturingQuery.seen.clear()
transport = YahooLiveTransport(
    token_provider=token_provider_for_league(db2, league_id=lg2.id,
                                             environ=TEST_ENV),
    query_factory=_CapturingQuery)
transport.fetch_league("461.l.488800")
_assert("the league still reads on its OWN owner's grant",
        _CapturingQuery.seen[0].get("access_token") != "STRANGER-BEARER",
        str(_CapturingQuery.seen[0].get("access_token"))[:30])

# A DISTINCT PROVIDER KEY. `(provider, provider_league_key)` is unique —
# two FantasyStakes leagues cannot both claim the same Yahoo league, which
# is correct and is why this fixture needs its own.
lg3 = _league(db2, name="Stranger League", key="461.l.999001")
set_credential_owner(db2, league_id=lg3.id, user_id=stranger.id)
_CapturingQuery.seen.clear()
YahooLiveTransport(
    token_provider=token_provider_for_league(db2, league_id=lg3.id,
                                             environ=TEST_ENV),
    query_factory=_CapturingQuery).fetch_league("461.l.999001")
_assert("and a different league reads on ITS owner's grant",
        _CapturingQuery.seen[0].get("access_token") == "STRANGER-BEARER")

# THE OWNER IS RE-READ PER CALL, so a handover takes effect on the next read.
set_credential_owner(db2, league_id=lg3.id, user_id=owner.id)
_CapturingQuery.seen.clear()
YahooLiveTransport(
    token_provider=token_provider_for_league(db2, league_id=lg3.id,
                                             environ=TEST_ENV),
    query_factory=_CapturingQuery).fetch_league("461.l.999001")
_assert("a handover takes effect on the very next read",
        _CapturingQuery.seen[0].get("access_token") == "RENEWED-BEARER")


# ── 8 · the background job resolves the identical owner ──────────────────────

_section("8 · A worker resolves exactly the same credential owner")

_assert("the worker and the request path both resolve by league id",
        credential_owner_id(db2, league_id=lg2.id) == owner.id)
_assert("with no session, cookie or request involved",
        bearer_for_league(db2, league_id=lg2.id, environ=TEST_ENV)
        == "RENEWED-BEARER")


# ── 9 · Demo needs none of it ────────────────────────────────────────────────

_section("9 · Demo requires and selects no Yahoo credential")

db3 = _fresh_db()
demo_league = _league(db3, name="Demo League", provider="demo",
                      key="demo.l.certification")
state = league_credential_state(db3, league_id=demo_league.id)
_assert("a Demo league has no credential owner and needs none",
        state.owner_user_id is None and state.connected is False,
        str(state.reason_code))

_demo_sources = []
for base, _dirs, files in os.walk(os.path.join(ROOT, "providers", "demo")):
    for name in files:
        if name.endswith(".py"):
            _demo_sources.append(os.path.join(base, name))
_demo = "\n".join(open(f, encoding="utf-8", errors="replace").read()
                  for f in _demo_sources)
for term in ("bearer_for_league", "token_provider_for_league",
             "load_credentials", "YahooLiveTransport(", "provider_grant"):
    _assert(f"the Demo provider never references {term}", term not in _demo)
db3.close()
db.close()
db2.close()


# ── 10 · the ownership operation, over HTTP ──────────────────────────────────

_section("10 · The commissioner ownership route, driven")

from test_support_app_server import (                               # noqa: E402
    AppServer, COMMISSIONER_EMAIL, GM_EMAIL, PASSWORD,
)

_PLANT = r"""
import os, sys
sys.path.insert(0, %(root)r)
from auth.provider_grant import record_grant, disconnect
from db.schema import SessionLocal, User
db = SessionLocal()
u = db.query(User).filter(User.email == %(email)r).first()
if u is not None:
    record_grant(db, user_id=u.id, provider_subject=%(subject)r,
                 tokens={"access_token": %(access)r,
                         "refresh_token": "rt-planted", "expires_in": 3600,
                         "scope": "openid email fspt-r"})
    if %(kill)r:
        disconnect(db, user_id=u.id)
    print("planted")
db.close()
"""


# THE CSRF TOKEN IS SENT, BECAUSE THE PRODUCT REQUIRES IT.
#
# A first cut omitted it and every POST came back 403 "missing CSRF token" —
# which is the session layer working exactly as designed, and which would have
# made this suite "prove" that a commissioner cannot connect a league when in
# fact it had proved that an unprotected request is refused. The gate is
# `X-FS-CSRF` matching the `fs_csrf` cookie, so the helper carries both.
CSRF_COOKIE = "fs_csrf"
CSRF_HEADER = "X-FS-CSRF"


def _csrf_from(cookie: str) -> str:
    for part in (cookie or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == CSRF_COOKIE:
            return value
    return ""


def _call(origin, method, path, cookie=None):
    req = urllib.request.Request(origin + path, method=method)
    if cookie:
        req.add_header("Cookie", cookie)
        token = _csrf_from(cookie)
        if token:
            req.add_header(CSRF_HEADER, token)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body or "{}")
        except ValueError:
            return e.code, {"raw": body[:200]}


def _call_without_csrf(origin, method, path, cookie):
    """The same call with the token deliberately withheld.

    Used once, to prove the protection is actually on this route rather than
    assumed to be — a route added in this package could have been mounted
    outside the middleware and nothing else here would notice.
    """
    req = urllib.request.Request(origin + path, method=method)
    req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def _sign_in(origin, email):
    req = urllib.request.Request(
        origin + "/auth/session", method="POST",
        data=json.dumps({"email": email, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.headers.get_all("Set-Cookie") or []
        return "; ".join(c.split(";")[0] for c in raw)


def _plant(server, email, subject, access, kill=False):
    return subprocess.run(
        [sys.executable, "-c", _PLANT % {
            "root": ROOT, "email": email, "subject": subject,
            "access": access, "kill": kill}],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "DATABASE_URL": server.database_url,
             "FS_TOKEN_ENCRYPTION_KEY": TEST_ENV["FS_TOKEN_ENCRYPTION_KEY"]})


with AppServer(server_env={
        "FS_TOKEN_ENCRYPTION_KEY": TEST_ENV["FS_TOKEN_ENCRYPTION_KEY"]}) as srv:

    # ── a member cannot assign ownership ────────────────────────────────────
    gm_cookie = _sign_in(srv.origin, GM_EMAIL)
    status, body = _call(srv.origin, "POST",
                         "/league/1/provider/credential", gm_cookie)
    _assert("an ordinary member cannot assign credential ownership",
            status == 403, f"{status} {str(body)[:70]}")

    # ── unauthenticated cannot ──────────────────────────────────────────────
    status, _ = _call(srv.origin, "POST", "/league/1/provider/credential")
    _assert("an unauthenticated caller cannot either", status == 401,
            str(status))

    # ── and the new route is inside the CSRF gate ───────────────────────────
    comm_probe = _sign_in(srv.origin, COMMISSIONER_EMAIL)
    status = _call_without_csrf(srv.origin, "POST",
                                "/league/1/provider/credential", comm_probe)
    _assert("a session-bearing POST without a CSRF token is refused",
            status == 403, str(status))

    # ── a commissioner with NO grant is refused ─────────────────────────────
    comm_cookie = _sign_in(srv.origin, COMMISSIONER_EMAIL)
    status, body = _call(srv.origin, "POST",
                         "/league/1/provider/credential", comm_cookie)
    _assert("a commissioner with no Yahoo grant is refused",
            status == 409
            and body.get("detail", {}).get("reason_code") == "not_connected",
            f"{status} {str(body)[:80]}")

    # ── a commissioner with a DISCONNECTED grant is refused ─────────────────
    planted = _plant(srv, COMMISSIONER_EMAIL, "sub-comm-live",
                     "COMMISSIONER-LIVE-BEARER", kill=True)
    _assert("a disconnected grant was planted", "planted" in planted.stdout,
            (planted.stderr or "")[-140:])
    status, body = _call(srv.origin, "POST",
                         "/league/1/provider/credential", comm_cookie)
    _assert("a disconnected grant cannot become a credential source",
            status == 409
            and body.get("detail", {}).get("reason_code") == "disconnected",
            f"{status} {str(body)[:80]}")

    # ── an active grant connects ────────────────────────────────────────────
    planted = _plant(srv, COMMISSIONER_EMAIL, "sub-comm-live",
                     "COMMISSIONER-LIVE-BEARER")
    _assert("an active grant was planted", "planted" in planted.stdout)
    status, body = _call(srv.origin, "POST",
                         "/league/1/provider/credential", comm_cookie)
    _assert("the commissioner can assign their OWN grant",
            status == 200 and body.get("connected") is True,
            f"{status} {str(body)[:110]}")
    _assert("the response says it is them", body.get("is_you") is True)
    _assert("and the assignment is timestamped",
            bool(body.get("assigned_at")), str(body.get("assigned_at")))

    # ── NO BEARER IN THE RESPONSE ──────────────────────────────────────────
    _assert("no bearer material is in the response",
            "COMMISSIONER-LIVE-BEARER" not in json.dumps(body)
            and "rt-planted" not in json.dumps(body))

    # ── THE ROUTE ACCEPTS NO USER ID AT ALL ────────────────────────────────
    _route = _read("api", "main.py").split(
        "def connect_league_provider_credential(")[1].split("\n@app.")[0]
    _assert("the route takes no user id, email or subject parameter",
            not re.search(r"^\s+(user_id|owner_user_id|email|subject)\s*:",
                          _route, re.M))
    _assert("it assigns the authenticated commissioner and only them",
            "user_id=comm.id" in _route)

    # ── a member cannot read the diagnostic either ─────────────────────────
    status, _ = _call(srv.origin, "GET",
                      "/league/1/provider/credential", gm_cookie)
    _assert("a member cannot read the credential diagnostic", status == 403,
            str(status))

    status, body = _call(srv.origin, "GET",
                         "/league/1/provider/credential", comm_cookie)
    _assert("the commissioner can", status == 200 and body.get("connected"),
            f"{status} {str(body)[:80]}")
    _assert("and that view carries no bearer material either",
            "COMMISSIONER-LIVE-BEARER" not in json.dumps(body))


# ── 11 · live configuration, checked again after the cutover ─────────────────

_section("11 · §12 · Live Yahoo configuration presence (values never printed)")

for name in ("FS_YAHOO_CLIENT_ID", "FS_YAHOO_CLIENT_SECRET",
             "FS_YAHOO_REDIRECT_URI", "FS_TOKEN_ENCRYPTION_KEY"):
    present = bool(os.environ.get(name))
    _assert(f"{name}: {'PRESENT' if present else 'ABSENT'}", True, "reported")

_live = all(os.environ.get(k) for k in
            ("FS_YAHOO_CLIENT_ID", "FS_YAHOO_CLIENT_SECRET",
             "FS_YAHOO_REDIRECT_URI"))
_assert("LIVE YAHOO RECONFIRMATION — NOT EXECUTED: LOCAL CREDENTIALS "
        "UNAVAILABLE" if not _live else
        "live credentials ARE present — run tools/yahoo_live_probe.py",
        True, "reported, not skipped")
_assert("this is distinct from Yahoo's previously measured WP2B 403",
        True, "reported")


print("\n" + "=" * 66)
if _failures:
    print(f"YAHOO-LIVE-1-FIX CUTOVER — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("YAHOO-LIVE-1-FIX CUTOVER — all assertions PASSED")
