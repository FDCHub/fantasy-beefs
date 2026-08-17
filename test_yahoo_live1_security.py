#!/usr/bin/env python3
"""
test_yahoo_live1_security.py — YAHOO-LIVE-1 · the security boundary.

WHAT THIS CERTIFIES. That a Yahoo bearer credential, now that the product stores
one, cannot get anywhere it should not: not into an API response, not into the
rendered page, not into browser storage, not into a log, and not into another
user's provider read.

WHY IT IS SEPARATE FROM THE ARCHITECTURE SUITE. `test_yahoo_live1_user_oauth.py`
proves the grant behaves correctly. This proves the grant stays PUT — a
different question, and one that has to be asked against the real running
server and the real rendered application rather than against the store in
isolation. A token that never leaks in a unit test can still be serialised by a
route that returns a model with one column too many.

EVERY CREDENTIAL HERE IS FAKE AND OBVIOUSLY SO. The markers are long, unique,
and could not be mistaken for a real Yahoo value; the encryption key is
generated per run. No real secret is required to run this suite and none is
produced by it.

DATABASE. SQLite through the shared app-server harness, plus private in-memory
databases for the store-level checks.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_app_server import (                              # noqa: E402
    AppServer, COMMISSIONER_EMAIL, GM_EMAIL, PASSWORD,
)

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


# THE MARKERS. Distinctive enough that finding one anywhere is unambiguous, and
# shaped nothing like a real Yahoo token so no reader can mistake them.
FAKE_ACCESS = "FSFAKEACCESS-" + "A" * 48
FAKE_REFRESH = "FSFAKEREFRESH-" + "R" * 48
FAKE_ID_TOKEN = "FSFAKEIDTOKEN-" + "I" * 48

from auth.token_crypto import generate_key                          # noqa: E402

TEST_ENV = {"FS_TOKEN_ENCRYPTION_KEY": generate_key()}


# ── 1 · the source itself never logs bearer material ─────────────────────────

_section("1 · No credential term is printed, logged or formatted anywhere")

# CODE ONLY. Every module in this package documents at length WHICH credentials
# must never be logged, naming each of them. Scanning the raw text would fail on
# the documentation that exists to prevent the very thing being scanned for.
def _code_only(text: str) -> str:
    text = re.sub(r'"""[\s\S]*?"""', " ", text)
    text = re.sub(r"'''[\s\S]*?'''", " ", text)
    return re.sub(r"^\s*#.*$", " ", text, flags=re.M)


_TOKEN_MODULES = [
    ("auth/token_crypto.py", _read("auth", "token_crypto.py")),
    ("auth/provider_grant.py", _read("auth", "provider_grant.py")),
    ("providers/yahoo/user_credentials.py",
     _read("providers", "yahoo", "user_credentials.py")),
    ("auth/yahoo_oidc.py", _read("auth", "yahoo_oidc.py")),
    ("tools/yahoo_live_probe.py", _read("tools", "yahoo_live_probe.py")),
]

for name, source in _TOKEN_MODULES:
    code = _code_only(source)
    # A `print` or a logging call whose ARGUMENTS mention a credential is the
    # defect. Printing a status, a reason code or a count is not.
    # THE WHOLE CALL, NOT THE FIRST LINE OF IT. A first cut stopped at the
    # newline and so read `print("  bearer token   obtained from the stored "` —
    # flagging a line whose very next fragment is "(value not shown)". A call
    # that spans lines has to be matched across them or the scan reports on
    # where the author happened to wrap.
    emitters = re.findall(
        r"(?:print|log(?:ger)?\.\w+|logging\.\w+)\s*\((.*?)\)\s*$",
        code, re.S | re.M)
    leaky = [call for call in emitters
             if re.search(r"\b(?:access_token|refresh_token|id_token|"
                          r"code_verifier|client_secret)\b", call)
             and "redacted" not in call.lower()
             and "not shown" not in call.lower()]
    _assert(f"{name} logs no credential", not leaky,
            "; ".join(leaky)[:120] or "none")

# AND NO CREDENTIAL IS INTERPOLATED INTO AN ERROR MESSAGE.
#
# NOT INTO ANY STRING — INTO A MESSAGE. A first cut flagged
# `f"{config.client_id}:{config.client_secret}"`, which is the HTTP Basic
# credential the OAuth spec requires and is not output at all; it goes into an
# Authorization header. What must never happen is a credential reaching an
# EXCEPTION, because exceptions are logged and rendered. So that is what is
# scanned: the argument of every raise.
for name, source in _TOKEN_MODULES:
    code = _code_only(source)
    raised = re.findall(r"raise\s+\w+\((.*?)\)\s*(?:from\s+\w+)?\s*$",
                        code, re.S | re.M)
    # THE VALUE, NOT THE WORD. A first cut flagged
    # `raise GrantError("no_access_token", "token response carried no
    # access_token")` — an English sentence naming the field that was missing,
    # which is exactly the diagnostic an operator needs and contains no
    # credential at all. What leaks a credential is INTERPOLATING one, so the
    # scan looks for a substitution rather than for the noun.
    leaky = [r for r in raised
             if re.search(r"\{[^{}]*\b(?:access_token|refresh_token|id_token|"
                          r"code_verifier|client_secret|plaintext|token)\b"
                          r"[^{}]*\}", r)]
    _assert(f"{name} puts no credential in an exception message",
            not leaky, "; ".join(leaky)[:120] or "none")

# THE DEFAULT REPRS ARE OVERRIDDEN. A dataclass or a model in a traceback prints
# every field it has, and a traceback reaches a log.
_assert("the grant model overrides __repr__ so a traceback cannot print it",
        "tokens=<sealed>" in _read("db", "schema.py"))
_assert("the keyring overrides __repr__ for the same reason",
        "material=<hidden>" in _read("auth", "token_crypto.py"))
_assert("the OIDC config still hides its client secret",
        "client_secret=<hidden>" in _read("auth", "yahoo_oidc.py"))


# ── 2 · the encryption boundary refuses rather than degrading ────────────────

_section("2 · No key means no storage — never plaintext storage")

from auth.token_crypto import (                                     # noqa: E402
    TokenCryptoError, TokenCryptoUnavailable, available, decrypt, encrypt,
)

_assert("with no key configured, the boundary reports unavailable",
        available({}) is False)
try:
    encrypt("anything", context="grant:1:access", environ={})
    _assert("and refuses to seal", False, "it produced a value with no key")
except TokenCryptoUnavailable:
    _assert("and refuses to seal", True, "TokenCryptoUnavailable")

for bad, why in ((("x" * 8), "too short"), ("not-base64!!", "not base64")):
    try:
        encrypt("v", context="c", environ={"FS_TOKEN_ENCRYPTION_KEY": bad})
        _assert(f"  · a key that is {why} is refused", False, "it was accepted")
    except TokenCryptoError:
        _assert(f"  · a key that is {why} is refused", True, "refused")

# THE ENVELOPE IS AUTHENTICATED. One flipped bit must fail, not decrypt to
# something else.
sealed = encrypt(FAKE_REFRESH, context="grant:1:refresh", environ=TEST_ENV)
_assert("the sealed value does not contain the token",
        FAKE_REFRESH not in sealed)
tampered = sealed[:-6] + ("A" if sealed[-6] != "A" else "B") + sealed[-5:]
try:
    decrypt(tampered, context="grant:1:refresh", environ=TEST_ENV)
    _assert("a tampered envelope is refused", False, "it opened")
except TokenCryptoError:
    _assert("a tampered envelope is refused", True, "authentication failed")


# ── 3 · one user's grant is unreachable from another's session ───────────────

_section("3 · User A's grant cannot authorize user B's provider read")

from sqlalchemy import create_engine                                # noqa: E402
from sqlalchemy.orm import sessionmaker                             # noqa: E402

from auth.provider_grant import (                                   # noqa: E402
    GrantError, access_token_for, grant_for, record_grant,
)
from db.schema import Base, League, User                            # noqa: E402

engine = create_engine("sqlite://")
Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()


def _mk(email: str, subject: str, role: str = "gm") -> User:
    u = User(email=email, hashed_password=None, auth_provider="yahoo",
             provider_subject=subject, role=role, is_active=1)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


victim = _mk("victim@example.com", "sub-victim")
attacker = _mk("attacker@example.com", "sub-attacker")
boss = _mk("boss@example.com", "sub-boss", role="commissioner")

record_grant(db, user_id=victim.id, provider_subject="sub-victim",
             tokens={"access_token": FAKE_ACCESS,
                     "refresh_token": FAKE_REFRESH, "expires_in": 3600},
             environ=TEST_ENV)

_assert("the victim can read their own token",
        access_token_for(db, user_id=victim.id, environ=TEST_ENV) == FAKE_ACCESS)

# THE ATTACKER HAS NO GRANT, and asking for one produces nothing rather than a
# fallback to anybody else's.
try:
    access_token_for(db, user_id=attacker.id, environ=TEST_ENV)
    _assert("a user with no grant gets no token", False, "a token appeared")
except GrantError as exc:
    _assert("a user with no grant gets no token", True, exc.reason_code)

# A COMMISSIONER IS NOT AN EXCEPTION. Administering a league is not holding a
# member's Yahoo credential, and there is no parameter that would conflate them.
try:
    access_token_for(db, user_id=boss.id, environ=TEST_ENV)
    _assert("a commissioner gets no token merely for being one", False,
            "a token appeared")
except GrantError as exc:
    _assert("a commissioner gets no token merely for being one", True,
            exc.reason_code)

# AND THE STORE OFFERS NO WIDER LOOKUP. If a function existed that returned a
# grant without a user_id, a future caller would eventually use it.
import inspect as _inspect                                          # noqa: E402
import auth.provider_grant as _grant_module                         # noqa: E402

_public = [n for n in dir(_grant_module)
           if not n.startswith("_") and callable(getattr(_grant_module, n))]
_wide = []
for name in _public:
    fn = getattr(_grant_module, name)
    try:
        params = _inspect.signature(fn).parameters
    except (TypeError, ValueError):
        continue
    if "db" in params and "user_id" not in params and name not in (
            "GrantError", "GrantUnavailable", "GrantSnapshot"):
        _wide.append(name)
_assert("no store function returns a grant without naming its user",
        not _wide, ", ".join(_wide) or "none")

# THE SAFE VIEW CARRIES NO CIPHERTEXT EITHER. A commissioner diagnostic renders
# this, and a ciphertext on screen is a ciphertext in a screenshot.
from auth.provider_grant import snapshot                            # noqa: E402

view = snapshot(db, user_id=victim.id)
_serialised = json.dumps(view.__dict__, default=str)
for marker, what in ((FAKE_ACCESS, "access token"),
                     (FAKE_REFRESH, "refresh token")):
    _assert(f"the safe view carries no {what}", marker not in _serialised)
_assert("nor any ciphertext", "v1." not in _serialised, _serialised[:120])
_assert("but it does report whether a refresh token exists",
        view.has_refresh_token is True)


# ── 4 · the league's credential owner is the only source ─────────────────────

_section("4 · A league cannot borrow a credential it was not given")

league = League(name="Victim League", season=2025, provider="yahoo",
                provider_league_key="461.l.488800")
db.add(league)
db.commit()
db.refresh(league)

from providers.yahoo.user_credentials import (                      # noqa: E402
    CredentialOwnerMissing, bearer_for_league,
)

try:
    bearer_for_league(db, league_id=league.id, environ=TEST_ENV)
    _assert("an unowned league gets no token", False, "a token appeared")
except CredentialOwnerMissing:
    _assert("an unowned league gets no token", True, "no_credential_owner")

# CODE ONLY. This module's docstring names `transport.load_credentials()` at
# length while explaining what it replaces, so scanning the raw text would fail
# on the documentation recording the removal.
_assert("and it does not fall back to the operator credential",
        "load_credentials" not in _code_only(
            _read("providers", "yahoo", "user_credentials.py")))
db.close()


# ── 5 · nothing reaches the browser ──────────────────────────────────────────

_section("5 · No bearer material reaches any client surface")

# THE STORED GRANT IS PLANTED IN THE RUNNING SERVER'S OWN DATABASE, so the
# assertions below are about a deployment that genuinely holds one. Asserting
# "no token in the response" against a server that has no token would be
# asserting nothing at all.
_PLANT = r"""
import os, sys
sys.path.insert(0, %(root)r)
os.environ.setdefault("FS_TOKEN_ENCRYPTION_KEY", %(key)r)
from auth.provider_grant import record_grant
from db.schema import SessionLocal, User
db = SessionLocal()
user = db.query(User).filter(User.email == %(email)r).first()
if user is not None:
    record_grant(db, user_id=user.id, provider_subject="sub-live",
                 tokens={"access_token": %(access)r,
                         "refresh_token": %(refresh)r,
                         "id_token": %(idt)r, "expires_in": 3600,
                         "scope": "openid email fspt-r"})
    print("planted")
db.close()
"""


def _get(origin: str, path: str, cookie: str | None = None):
    req = urllib.request.Request(origin + path)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


with AppServer(server_env={"FS_TOKEN_ENCRYPTION_KEY":
                           TEST_ENV["FS_TOKEN_ENCRYPTION_KEY"]}) as server:
    # IN A SUBPROCESS, AGAINST THE SERVER'S OWN DATABASE. `db.schema` binds its
    # engine from DATABASE_URL at import time, so planting in-process would hold
    # a second engine against the same SQLite file the server has open.
    planted = subprocess.run(
        [sys.executable, "-c", _PLANT % {
            "root": ROOT, "key": TEST_ENV["FS_TOKEN_ENCRYPTION_KEY"],
            "email": GM_EMAIL, "access": FAKE_ACCESS,
            "refresh": FAKE_REFRESH, "idt": FAKE_ID_TOKEN}],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ,
             "DATABASE_URL": server.database_url,
             "FS_TOKEN_ENCRYPTION_KEY": TEST_ENV["FS_TOKEN_ENCRYPTION_KEY"]})
    _planted = "planted" in (planted.stdout or "")
    _assert("a real grant was planted in the running deployment", _planted,
            (planted.stderr or "")[-160:] or planted.stdout.strip())

    # SIGN IN and sweep every surface a client can reach.
    session = urllib.request.Request(
        server.origin + "/auth/session", method="POST",
        data=json.dumps({"email": GM_EMAIL, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"})
    cookie = None
    try:
        with urllib.request.urlopen(session, timeout=15) as response:
            raw = response.headers.get_all("Set-Cookie") or []
            cookie = "; ".join(c.split(";")[0] for c in raw)
    except urllib.error.HTTPError as exc:
        _assert("the harness could sign in", False, str(exc.code))

    # THE ROUTES A SIGNED-IN GM ACTUALLY READS, named from the mounted paths
    # rather than guessed. A first cut listed `/league/1/context` and
    # `/league/1/action`, both of which 404 — and a 404 body proves nothing
    # about whether a real response would have carried a token.
    SURFACES = [
        "/app/index.html", "/auth/me", "/auth/methods", "/health",
        "/league/1/context/me", "/league/1/action/me", "/league/1/ledger/me",
        "/league/1/standings", "/league/1/versus/board",
        "/league/1/provider/status",
    ]
    for path in SURFACES:
        status, body = _get(server.origin, path, cookie)
        leaked = [name for name, marker in
                  (("access token", FAKE_ACCESS),
                   ("refresh token", FAKE_REFRESH),
                   ("id token", FAKE_ID_TOKEN))
                  if marker in body]
        # A 404 IS REPORTED AS ONE. A route that is not there has not been
        # swept, and saying "clean" about it would overstate the sweep.
        _assert(f"{path} ({status}) carries no bearer material",
                not leaked,
                ", ".join(leaked)
                or ("clean" if status < 400 else f"clean, but {status}"))

    # THE SHIPPED FRONTEND, SWEPT AS SOURCE. A token cannot be rendered by code
    # that never names the field it would come from.
    _web = []
    for base, _dirs, files in os.walk(os.path.join(ROOT, "web")):
        if "tests" in base.split(os.sep):
            continue
        for name in files:
            if name.endswith((".js", ".html", ".css")):
                _web.append(os.path.join(base, name))
    _js = "\n".join(open(p, encoding="utf-8", errors="replace").read()
                    for p in _web)
    for term in ("access_token", "refresh_token", "refresh_token_sealed",
                 "access_token_sealed", "Bearer "):
        _assert(f"the frontend never references {term!r}", term not in _js)
    # CODE ONLY, AGAIN. `web/js/session.js` documents, in a comment, that the
    # application uses "no localStorage, no sessionStorage, and no cookie WRITE
    # anywhere" — so a raw scan finds the sentence promising the property and
    # calls it a violation of the property.
    _js_code = re.sub(r"/\*[\s\S]*?\*/", " ",
                      re.sub(r"^\s*//.*$", " ", _js, flags=re.M))
    for store in ("localStorage", "sessionStorage", "indexedDB"):
        _assert(f"the frontend uses no {store} at all",
                store not in _js_code,
                "absent" if store not in _js_code
                else "FOUND — a token could be persisted there")

    # THE SERVICE WORKER MUST NOT CACHE THE AUTH SURFACE. WP3E certified this;
    # it is re-asserted here because this package is the one that made the auth
    # surface hold a credential.
    _sw = _read("web", "service-worker.js")
    _assert("the service worker still never caches /auth/", "'/auth/'" in _sw)
    _assert("and never caches credentialed requests",
            "credentials === 'include'" in _sw)


# ── 6 · the OIDC guards are untouched ────────────────────────────────────────

_section("6 · AUTH1 / AUTH1-FIX guards are not weakened by this package")

_OIDC = _read("auth", "yahoo_oidc.py")
_assert("PKCE is still required at exchange",
        "no usable PKCE verifier" in _OIDC and "len(code_verifier) < 43" in _OIDC)
_assert("S256 only — `plain` is still never offered",
        'CHALLENGE_METHOD = "S256"' in _OIDC and '"plain"' not in _OIDC)
_assert("the nonce is still compared in constant time",
        "compare_digest(str(claims[\"nonce\"])" in _OIDC)
_assert("the scopes still include openid, email and fspt-r",
        'SCOPES = ("openid", "email", "fspt-r")' in _OIDC)

_MAIN = _read("api", "main.py")
_callback = _MAIN.split("def auth_yahoo_callback(")[1].split("\n@app.")[0]
# THE CALL, NOT THE IMPORT. `exchange_code` is imported at the top of the
# function, so comparing against its first occurrence compared against the
# import statement and always failed. The guard's claim is about the CALL.
_assert("state is still checked before the code is exchanged",
        "state_invalid" in _callback
        and _callback.index("state_invalid")
        < _callback.index("exchange_code(code"))
_assert("the verifier still comes from the sealed transaction",
        "code_verifier=transaction.code_verifier" in _callback)
_assert("the identity is still the Yahoo subject",
        "subject=identity.subject" in _callback)
_assert("production still refuses password authentication",
        "There is no " in _MAIN and "Sign in with Yahoo" in _MAIN)

# THE GRANT IS RECORDED AFTER THE IDENTITY IS PROVED, never before.
_assert("the grant is recorded only after validation and resolution",
        _callback.index("resolve_user(db") < _callback.index("record_grant("))


# ── 7 · Demo needs no Yahoo credential ───────────────────────────────────────

_section("7 · Demo remains entirely independent of Yahoo authorization")

_demo_sources = []
for base, _dirs, files in os.walk(os.path.join(ROOT, "providers", "demo")):
    for name in files:
        if name.endswith(".py"):
            _demo_sources.append(os.path.join(base, name))
_demo = "\n".join(open(p, encoding="utf-8", errors="replace").read()
                  for p in _demo_sources)
for term in ("provider_grant", "access_token_for", "bearer_for_league",
             "load_credentials", "token_crypto"):
    _assert(f"the Demo provider never imports {term}", term not in _demo)
_assert("Demo sources were actually found to check",
        len(_demo_sources) > 0, f"{len(_demo_sources)} file(s)")


# ── 8 · no Yahoo Fantasy Information is persisted ────────────────────────────

_section("8 · The storage boundary — credentials yes, Fantasy data no")

from db.schema import ProviderGrant                                 # noqa: E402

_columns = {c.name for c in ProviderGrant.__table__.columns}
_assert("the grant table holds only credential and status fields",
        _columns == {
            "id", "user_id", "provider", "provider_subject",
            "access_token_sealed", "refresh_token_sealed", "expires_at",
            "granted_scope", "status", "token_version", "created_at",
            "updated_at", "last_refresh_at", "last_error_code",
            "last_error_at"},
        ", ".join(sorted(_columns)))
# WHOLE WORDS. A first cut looked for the substring "stat" and flagged
# `status` — the column that records whether the grant works. The forbidden
# thing is a Fantasy-data column, and `status` is not one.
for forbidden in ("roster", "player", "stat", "matchup", "standing",
                  "scoreboard", "settings", "points", "payload", "team"):
    _assert(f"  · no {forbidden} column",
            not any(re.search(rf"(^|_){forbidden}s?(_|$)", c)
                    for c in _columns),
            ", ".join(c for c in sorted(_columns)
                      if re.search(rf"(^|_){forbidden}s?(_|$)", c)) or "none")

_assert("the probe describes structure and keeps no payload",
        "_describe" in _read("tools", "yahoo_live_probe.py")
        and "never returns a leaf value" in _read("tools", "yahoo_live_probe.py"))
_assert("and it writes no fixture, file or table",
        not re.search(r"open\([^)]*['\"]w['\"]",
                      _read("tools", "yahoo_live_probe.py")))


print("\n" + "=" * 66)
if _failures:
    print(f"YAHOO-LIVE-1 SECURITY — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("YAHOO-LIVE-1 SECURITY — all assertions PASSED")
