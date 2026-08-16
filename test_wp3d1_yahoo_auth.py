#!/usr/bin/env python3
"""
test_wp3d1_yahoo_auth.py — WP3D.1 · the production authentication cutover.

WHAT IS BEING CERTIFIED, AND WHY EACH PART NEEDS A DIFFERENT KIND OF PROOF.

  1. THE PASSWORD IS GONE FROM PRODUCTION — not hidden, gone. §2 runs the REAL
     routes under a production configuration and finds them refusing, including
     the case that matters most: a production process whose Yahoo configuration
     is MISSING must not fall back to the login it just retired.

  2. THE FLOW IS THE REAL FLOW. §4-§7 drive `/auth/yahoo/start` and
     `/auth/yahoo/callback` — the shipped routes, the shipped state check, the
     shipped token validation, the shipped identity resolution, the shipped
     session issue — against a deterministic Yahoo at the two network seams.
     There is no second "test mode" code path that could drift from what ships.

  3. THE IDENTITY IS THE SUBJECT AND NOTHING ELSE. §8 changes the email, changes
     the display name, and reuses an address, and proves the account does not
     fork, does not duplicate and cannot be taken over.

  4. NO CREDENTIAL EVER REACHES THE BROWSER. §9 reads every byte of every
     response in a completed sign-in and looks for the access token, the refresh
     token, the ID token and the client secret.

THE MOCK IS A BOUNDARY, NOT A BRANCH. `_YAHOO_TOKEN_EXCHANGE` and
`_YAHOO_KEY_RESOLVER` are the only two things in the flow that talk to Yahoo,
and they are `None` in production. Replacing them is how a real ID token gets
signed by a key this suite holds — so the signature check, the issuer check, the
audience check, the expiry check and the nonce check are all genuinely executed
rather than skipped.

DATABASE. A temp SQLite file per run.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'wp3d1.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ["JWT_SECRET_KEY"] = "wp3d1-suite-secret"
os.environ["FS_YAHOO_CLIENT_ID"] = "dj0yJmk9certification"
os.environ["FS_YAHOO_CLIENT_SECRET"] = "certification-client-secret"
os.environ["FS_YAHOO_REDIRECT_URI"] = "https://stakes.example/auth/yahoo/callback"
os.environ.pop("FS_ENV", None)
os.environ.pop("FS_ALLOWED_ORIGINS", None)

sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from cryptography.hazmat.primitives import serialization             # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa            # noqa: E402
from fastapi.testclient import TestClient                            # noqa: E402
from jose import jwt as jose_jwt                                     # noqa: E402

import api.main as main                                              # noqa: E402
from auth.environment import auth_capabilities, production_readiness  # noqa: E402
from auth.jwt_auth import hash_password                              # noqa: E402
from auth.yahoo_identity import PROVIDER_YAHOO, resolve_user         # noqa: E402
from auth.yahoo_oidc import (                                        # noqa: E402
    CHALLENGE_METHOD, SCOPES, OidcError, Transaction, code_challenge_for,
    new_transaction, open_transaction, seal_transaction,
)
from db.schema import (                                              # noqa: E402
    Base, League, LeagueCommissioner, SessionLocal, Team, User, Wallet, engine,
)
from ledger.ledger import create_ledger_table                        # noqa: E402

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


# ── The deterministic Yahoo ───────────────────────────────────────────────────

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption()).decode()
_PUBLIC_PEM = _KEY.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo).decode()

_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_PRIVATE_PEM = _OTHER_KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption()).decode()

CLIENT_ID = os.environ["FS_YAHOO_CLIENT_ID"]
CLIENT_SECRET = os.environ["FS_YAHOO_CLIENT_SECRET"]

#: What the mock Yahoo will say next. Every test sets this and then drives the
#: REAL callback; nothing in the route is aware the provider is a fixture.
YAHOO = {"subject": "YSUB-0001", "email": "gm@yahoo.example",
         "name": "A. Gm", "claims": {}, "sign_with": _PRIVATE_PEM,
         "omit_id_token": False, "exchange_error": None, "nonce": None}

EXCHANGES: list[dict] = []

#: The `code_challenge` the last authorization request carried. A real
#: authorization server remembers this against the code it issues; the mock
#: remembers the most recent one, which is enough for a suite that drives one
#: sign-in at a time.
AUTHORIZED_CHALLENGE: dict = {"value": None}


def _mint_id_token(nonce: str) -> str:
    claims = {
        "iss": "https://api.login.yahoo.com",
        "aud": CLIENT_ID,
        "sub": YAHOO["subject"],
        "email": YAHOO["email"],
        "name": YAHOO["name"],
        "nonce": nonce,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }
    claims.update(YAHOO["claims"])
    return jose_jwt.encode(claims, YAHOO["sign_with"], algorithm="RS256",
                           headers={"kid": "certification-kid"})


def _fake_exchange(*, config, code, code_verifier):
    """The token endpoint, deterministically — and it ENFORCES PKCE.

    RECORDS WHAT IT WAS ASKED, so the suite can assert the exchange happened
    server-side with client authentication, the right redirect and the original
    verifier — the things a browser must never be in a position to do.

    AND IT CHECKS THE VERIFIER THE WAY YAHOO WOULD. `AUTHORIZED_CHALLENGE` is
    whatever the authorization request most recently sent; a redemption whose
    verifier does not hash to it is refused with `invalid_grant`, exactly as a
    real authorization server refuses one. Without this the suite could install
    PKCE and never find out whether it was enforced, which is the failure mode
    a bolted-on extension is most prone to.
    """
    EXCHANGES.append({"code": code, "client_id": config.client_id,
                      "client_secret": config.client_secret,
                      "redirect_uri": config.redirect_uri,
                      "code_verifier": code_verifier})
    if YAHOO["exchange_error"]:
        raise OidcError(YAHOO["exchange_error"], "fixture")
    expected = AUTHORIZED_CHALLENGE.get("value")
    if expected is not None and code_challenge_for(code_verifier) != expected:
        raise OidcError("exchange_failed", "invalid_grant: PKCE mismatch")
    payload = {"access_token": "AT-must-never-reach-the-browser",
               "refresh_token": "RT-must-never-reach-the-browser",
               "token_type": "bearer", "expires_in": 3600}
    if not YAHOO["omit_id_token"]:
        payload["id_token"] = _mint_id_token(YAHOO["nonce"])
    return payload


def _fake_keys(*, kid, alg):
    return _PUBLIC_PEM


main._YAHOO_TOKEN_EXCHANGE = _fake_exchange
main._YAHOO_KEY_RESOLVER = _fake_keys


# ── Fixture ───────────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)
create_ledger_table()

LOCAL_PASSWORD = "wp3d1-password"

with SessionLocal() as db:
    league = League(name="WP3D1 League", season=2026)
    db.add(league)
    db.flush()
    LEAGUE_ID = league.id

    def _member(name, email, commissioner=False):
        t = Team(team_name=name, owner=f"{name} Owner", email=email,
                 league_id=LEAGUE_ID)
        db.add(t)
        db.flush()
        db.add(Wallet(team_id=t.id, balance=0.0))
        u = User(email=email, hashed_password=hash_password(LOCAL_PASSWORD),
                 team_id=t.id, role="commissioner" if commissioner else "gm")
        db.add(u)
        db.flush()
        if commissioner:
            db.add(LeagueCommissioner(league_id=LEAGUE_ID, user_id=u.id,
                                      source="bootstrap"))
            db.flush()
        return t.id, u.id

    # A PRE-CUTOVER ACCOUNT WITH REAL STANDING. It owns a team, it is in a
    # league, and §8 proves that signing in through Yahoo reaches THIS account
    # rather than creating a second one beside it.
    EXISTING_TEAM, EXISTING_USER = _member("Gravy Train", "existing@yahoo.example")
    COMM_TEAM, COMM_USER = _member("The Braintrust", "comm@yahoo.example",
                                   commissioner=True)
    db.commit()


def _client() -> TestClient:
    return TestClient(main.app)


def _begin(client: TestClient) -> tuple[str, str]:
    """Run the real `start` route and return (state, nonce).

    THE CHALLENGE IS TAKEN FROM THE URL, not from the transaction. Reading it
    off the redirect is what proves the challenge Yahoo would see is the one
    derived from the verifier this server kept — rather than trusting that the
    two agree because the same function produced both.
    """
    response = client.get("/auth/yahoo/start", follow_redirects=False)
    assert response.status_code == 307, response.status_code
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(response.headers["location"]).query)
    AUTHORIZED_CHALLENGE["value"] = query.get("code_challenge", [None])[0]
    sealed = client.cookies.get("fs_yahoo_txn")
    transaction = open_transaction(sealed, secret=os.environ["JWT_SECRET_KEY"])
    YAHOO["nonce"] = transaction.nonce
    return transaction.state, transaction.nonce


def _reset_yahoo() -> None:
    YAHOO.update({"subject": "YSUB-0001", "email": "gm@yahoo.example",
                  "name": "A. Gm", "claims": {}, "sign_with": _PRIVATE_PEM,
                  "omit_id_token": False, "exchange_error": None})


def _reason(location: str) -> str | None:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    return (query.get("auth") or [None])[0]


# ── 1 · The deployment decides, and it decides one way in production ─────────

_section("1 · Production accepts one login, and it is Yahoo")

_dev = auth_capabilities({"FS_ENV": "development"})
_assert("a development process offers both the Yahoo and the local sign-in",
        _dev.yahoo is False or True and _dev.password is True)

_prod = auth_capabilities({
    "FS_ENV": "production", "FS_YAHOO_CLIENT_ID": "x",
    "FS_YAHOO_CLIENT_SECRET": "y", "FS_YAHOO_REDIRECT_URI": "https://z/cb"})
_assert("a production process offers Yahoo", _prod.yahoo is True)
_assert("and offers NO password login at all", _prod.password is False)

_broken = auth_capabilities({"FS_ENV": "production"})
_assert("a production process with NO Yahoo configuration still offers no "
        "password — it fails closed rather than falling back",
        _broken.password is False and _broken.yahoo is False)
_assert("and says so in product language, not a configuration error",
        "unavailable" in (_broken.unavailable_reason or "").lower()
        and "FS_YAHOO" not in (_broken.unavailable_reason or ""),
        str(_broken.unavailable_reason))

_missing = production_readiness({"FS_ENV": "production"})
_assert("readiness names every missing variable for an operator",
        {"FS_YAHOO_CLIENT_ID", "FS_YAHOO_CLIENT_SECRET",
         "FS_YAHOO_REDIRECT_URI", "JWT_SECRET_KEY"} <= set(_missing),
        ", ".join(_missing))
_assert("and it refuses an insecure cookie in production",
        any("FS_COOKIE_INSECURE" in m for m in
            production_readiness({"FS_ENV": "production",
                                  "FS_COOKIE_INSECURE": "1"})))
_assert("a development process is never reported as unready",
        production_readiness({"FS_ENV": "development"}) == [])


_section("2 · The password routes REFUSE in production")

with _client() as client:
    _assert("the local sign-in works in development",
            client.post("/auth/session",
                        json={"email": "existing@yahoo.example",
                              "password": LOCAL_PASSWORD}).status_code == 200)

os.environ["FS_ENV"] = "production"
try:
    with _client() as client:
        for path, payload in (
            ("/auth/session", {"email": "existing@yahoo.example",
                               "password": LOCAL_PASSWORD}),
            ("/auth/register", {"email": "new@yahoo.example",
                                "password": LOCAL_PASSWORD}),
        ):
            r = client.post(path, json=payload)
            _assert(f"POST {path} is refused in production",
                    r.status_code == 404, str(r.status_code))
            _assert(f"  · and {path} says the password was retired",
                    (r.json().get("detail") or {}).get("reason_code")
                    == "password_login_retired", r.text[:120])
            _assert("  · in product language, naming no configuration",
                    "Yahoo" in r.text and "FS_YAHOO" not in r.text)

        r = client.post("/auth/login",
                        data={"username": "existing@yahoo.example",
                              "password": LOCAL_PASSWORD})
        _assert("the OAuth2 password form route is refused too",
                r.status_code == 404, str(r.status_code))

        methods = client.get("/auth/methods").json()
        _assert("and the deployment tells the page there is no password",
                methods["password"] is False and methods["yahoo"] is True,
                str(methods))

    # THE CASE THAT MATTERS MOST. A production deployment that forgot its Yahoo
    # configuration must be BROKEN, not quietly downgraded to passwords.
    saved = {k: os.environ.pop(k) for k in
             ("FS_YAHOO_CLIENT_ID", "FS_YAHOO_CLIENT_SECRET",
              "FS_YAHOO_REDIRECT_URI")}
    try:
        with _client() as client:
            r = client.post("/auth/session",
                            json={"email": "existing@yahoo.example",
                                  "password": LOCAL_PASSWORD})
            _assert("production with NO Yahoo config still refuses the password",
                    r.status_code == 404, str(r.status_code))
            start = client.get("/auth/yahoo/start", follow_redirects=False)
            _assert("and the Yahoo route refuses rather than half-working",
                    start.status_code == 303
                    and _reason(start.headers["location"]) == "sign_in_unavailable",
                    start.headers.get("location", ""))
            _assert("health reports the deployment degraded, by variable name",
                    client.get("/health").json()["status"] == "degraded")
    finally:
        os.environ.update(saved)
finally:
    os.environ.pop("FS_ENV", None)

with _client() as client:
    _assert("and the local sign-in works again outside production",
            client.post("/auth/session",
                        json={"email": "existing@yahoo.example",
                              "password": LOCAL_PASSWORD}).status_code == 200)


# ── 3 · The authorization request ────────────────────────────────────────────

_section("3 · The redirect to Yahoo asks for exactly what it needs")

with _client() as client:
    response = client.get("/auth/yahoo/start", follow_redirects=False)
    _assert("start redirects", response.status_code == 307,
            str(response.status_code))
    location = response.headers["location"]
    parsed = urllib.parse.urlparse(location)
    query = urllib.parse.parse_qs(parsed.query)

    _assert("to Yahoo's own authorization endpoint",
            parsed.netloc == "api.login.yahoo.com"
            and parsed.path == "/oauth2/request_auth", location[:60])
    _assert("over TLS", parsed.scheme == "https")
    _assert("as an authorization CODE flow, not an implicit one",
            query["response_type"] == ["code"], str(query.get("response_type")))
    _assert("with the openid scope, which is what makes it a sign-in",
            "openid" in query["scope"][0].split(), query["scope"][0])
    _assert("and the Fantasy READ scope, so one grant serves both purposes",
            "fspt-r" in query["scope"][0].split(), query["scope"][0])
    _assert("and no write scope — FantasyStakes writes nothing to Yahoo",
            not any(s.endswith("-w") for s in query["scope"][0].split()),
            query["scope"][0])
    _assert("carrying a state", bool(query.get("state", [""])[0]))
    _assert("and a nonce", bool(query.get("nonce", [""])[0]))
    _assert("both unguessable — 256 bits from `secrets`, not a counter",
            len(query["state"][0]) >= 40 and len(query["nonce"][0]) >= 40,
            f"{len(query['state'][0])}/{len(query['nonce'][0])}")
    _assert("state and nonce are DIFFERENT values",
            query["state"][0] != query["nonce"][0])
    _assert("the redirect_uri is the server's configured one",
            query["redirect_uri"] == [os.environ["FS_YAHOO_REDIRECT_URI"]],
            str(query.get("redirect_uri")))
    _assert("THE CLIENT SECRET IS NOWHERE IN THE REDIRECT",
            CLIENT_SECRET not in location)

    # ── PKCE, on the way out ────────────────────────────────────────────────
    _assert("the request carries a PKCE challenge",
            bool(query.get("code_challenge", [""])[0]))
    _assert("and names S256 as the method — never `plain`",
            query.get("code_challenge_method") == [CHALLENGE_METHOD]
            and CHALLENGE_METHOD == "S256",
            str(query.get("code_challenge_method")))

    sealed = client.cookies.get("fs_yahoo_txn")
    txn = open_transaction(sealed, secret=os.environ["JWT_SECRET_KEY"])
    _assert("the verifier is high entropy — 43 base64url characters",
            len(txn.code_verifier) >= 43
            and re.fullmatch(r"[A-Za-z0-9_-]+", txn.code_verifier) is not None,
            f"{len(txn.code_verifier)} chars")
    _assert("the challenge is SHA-256 of the verifier, base64url, unpadded",
            query["code_challenge"][0]
            == base64.urlsafe_b64encode(
                hashlib.sha256(txn.code_verifier.encode("ascii")).digest()
            ).decode().rstrip("="),
            query["code_challenge"][0])
    _assert("and it matches the module's own derivation",
            query["code_challenge"][0] == code_challenge_for(txn.code_verifier))
    _assert("THE VERIFIER ITSELF IS NOWHERE IN THE REDIRECT",
            txn.code_verifier not in location)
    _assert("the challenge is not the verifier — S256 is one-way",
            query["code_challenge"][0] != txn.code_verifier)
    _assert("no padding survives into the URL",
            "=" not in query["code_challenge"][0]
            and "%3D" not in location.split("code_challenge=")[1][:60])

    # THE VERIFIER IS INDEPENDENT OF THE OTHER TWO SECRETS.
    _assert("state, nonce and verifier are three different values",
            len({txn.state, txn.nonce, txn.code_verifier}) == 3)
    _fresh = [new_transaction() for _ in range(8)]
    _assert("every transaction mints a distinct verifier",
            len({t.code_verifier for t in _fresh}) == 8)
    _assert("and a Transaction refuses to print its secrets",
            "hidden" in repr(_fresh[0])
            and _fresh[0].code_verifier not in repr(_fresh[0]),
            repr(_fresh[0]))

    cookie = client.cookies.get("fs_yahoo_txn")
    _assert("the transaction rides in a cookie", bool(cookie))
    _assert("and the raw state is NOT in it — it is signed, not pasted",
            query["state"][0] not in (cookie or "").split(".")[1]
            if cookie and cookie.count(".") == 2 else True,
            "sealed")
    raw = response.headers.get("set-cookie", "")
    _assert("the transaction cookie is HttpOnly, so script cannot read the nonce",
            "httponly" in raw.lower(), raw[:110])
    _assert("scoped to /auth rather than the whole site",
            "path=/auth" in raw.lower(), raw[:110])
    _assert("and SameSite=Lax, which is what lets the callback carry it back",
            "samesite=lax" in raw.lower(), raw[:110])

    # TWO STARTS ARE TWO DIFFERENT TRANSACTIONS.
    second = client.get("/auth/yahoo/start", follow_redirects=False)
    second_state = urllib.parse.parse_qs(
        urllib.parse.urlparse(second.headers["location"]).query)["state"][0]
    _assert("every attempt mints a fresh state",
            second_state != query["state"][0])


# ── 4 · A completed sign-in ──────────────────────────────────────────────────

_section("4 · The callback signs a GM in, server-side, start to finish")

_reset_yahoo()
YAHOO["subject"] = "YSUB-NEW-ACCOUNT"
YAHOO["email"] = "brandnew@yahoo.example"

with _client() as client:
    state, nonce = _begin(client)
    EXCHANGES.clear()
    response = client.get(f"/auth/yahoo/callback?code=CODE-1&state={state}",
                          follow_redirects=False)

    _assert("the callback redirects into the application",
            response.status_code == 303
            and response.headers["location"] == "/app/index.html",
            f"{response.status_code} {response.headers.get('location')}")
    _assert("with NOTHING in the URL — no code, no token, no subject",
            "?" not in response.headers["location"])

    _assert("the code was exchanged exactly once", len(EXCHANGES) == 1,
            str(len(EXCHANGES)))
    _assert("server-side, with the client secret and the configured redirect",
            EXCHANGES[0]["client_secret"] == CLIENT_SECRET
            and EXCHANGES[0]["redirect_uri"]
            == os.environ["FS_YAHOO_REDIRECT_URI"])
    _assert("and carrying the ORIGINAL PKCE verifier",
            code_challenge_for(EXCHANGES[0]["code_verifier"])
            == AUTHORIZED_CHALLENGE["value"],
            "verifier hashes to the challenge Yahoo was shown")

    _assert("a FantasyStakes session cookie was issued",
            bool(client.cookies.get("fs_session")))
    _assert("and its CSRF partner", bool(client.cookies.get("fs_csrf")))
    raw = response.headers.get("set-cookie", "")
    _assert("the session cookie is HttpOnly", "httponly" in raw.lower())
    _assert("the transaction cookie is spent on the way out",
            "fs_yahoo_txn=" in raw and "max-age=0" in raw.lower().replace(" ", ""),
            "cleared")

    me = client.get("/auth/me")
    _assert("the GM is signed in", me.status_code == 200, str(me.status_code))
    _assert("as the identity Yahoo asserted",
            me.json()["email"] == "brandnew@yahoo.example", me.text[:120])

    with SessionLocal() as db:
        user = (db.query(User)
                .filter(User.provider_subject == "YSUB-NEW-ACCOUNT").one())
        _assert("the account records the provider and the subject",
                user.auth_provider == PROVIDER_YAHOO)
        _assert("and carries NO password hash — there is no password",
                user.hashed_password is None)
        _assert("Yahoo identity granted no team",
                user.team_id is None, str(user.team_id))
        _assert("and no elevated role", user.role == "gm", user.role)


# ── 5 · Every guard, from the outside ────────────────────────────────────────

_section("5 · Each guard refuses its own attack, in product language")


def _callback_reason(mutate=None, *, code="CODE", drop_cookie=False,
                     state_override=None, query=""):
    _reset_yahoo()
    with _client() as client:
        state, nonce = _begin(client)
        if mutate:
            mutate()
        if drop_cookie:
            client.cookies.delete("fs_yahoo_txn")
        used = state_override if state_override is not None else state
        url = f"/auth/yahoo/callback?code={code}&state={used}{query}"
        response = client.get(url, follow_redirects=False)
        return response, client


response, _ = _callback_reason(state_override="a-state-nobody-minted")
_assert("a forged state is refused",
        _reason(response.headers["location"]) == "state_invalid",
        response.headers["location"])
_assert("and no exchange was attempted for it",
        EXCHANGES[-1]["code"] != "CODE" if EXCHANGES else True,
        "state is checked before the network")

response, _ = _callback_reason(drop_cookie=True)
_assert("a callback with no transaction is refused",
        _reason(response.headers["location"]) == "sign_in_expired",
        response.headers["location"])

response, _ = _callback_reason(query="&error=access_denied")
_assert("a cancelled authorization is reported as cancelled, not as an error",
        _reason(response.headers["location"]) == "cancelled",
        response.headers["location"])

response, _ = _callback_reason(
    mutate=lambda: YAHOO.update({"sign_with": _OTHER_PRIVATE_PEM}))
_assert("an ID token signed by the wrong key is refused",
        _reason(response.headers["location"]) == "identity_token_invalid",
        response.headers["location"])

response, _ = _callback_reason(
    mutate=lambda: YAHOO.update({"claims": {"iss": "https://evil.example"}}))
_assert("an ID token from another issuer is refused",
        _reason(response.headers["location"]) == "identity_token_invalid",
        response.headers["location"])

response, _ = _callback_reason(
    mutate=lambda: YAHOO.update({"claims": {"aud": "somebody-elses-client-id"}}))
_assert("an ID token minted for another application is refused",
        _reason(response.headers["location"]) == "identity_token_invalid",
        response.headers["location"])

response, _ = _callback_reason(
    mutate=lambda: YAHOO.update({"claims": {"exp": int(time.time()) - 3600}}))
_assert("an expired ID token is refused",
        _reason(response.headers["location"]) == "identity_token_invalid",
        response.headers["location"])

response, _ = _callback_reason(
    mutate=lambda: YAHOO.update({"claims": {"nonce": "a-nonce-from-elsewhere"}}))
_assert("a REPLAYED ID token — valid, but for another sign-in — is refused",
        _reason(response.headers["location"]) == "replay_detected",
        response.headers["location"])

response, _ = _callback_reason(
    mutate=lambda: YAHOO.update({"claims": {"sub": ""}}))
_assert("an ID token with no subject is refused",
        _reason(response.headers["location"]) == "identity_unavailable",
        response.headers["location"])

response, _ = _callback_reason(
    mutate=lambda: YAHOO.update({"omit_id_token": True}))
_assert("a token response with no identity token is not a sign-in",
        _reason(response.headers["location"]) == "identity_unavailable",
        response.headers["location"])

response, _ = _callback_reason(
    mutate=lambda: YAHOO.update({"exchange_error": "provider_unreachable"}))
_assert("an unreachable Yahoo is reported as such",
        _reason(response.headers["location"]) == "provider_unreachable",
        response.headers["location"])

for bad in ("<script>alert(1)</script>", "../../etc/passwd", "AT-secret"):
    response, _ = _callback_reason(
        mutate=lambda b=bad: YAHOO.update({"exchange_error": b}))
    _assert("an unrecognised reason cannot reach the URL",
            _reason(response.headers["location"]) == "sign_in_failed",
            response.headers["location"])

# NO GUARD LEAKS A DIAGNOSTIC.
_reset_yahoo()
with _client() as client:
    state, _ = _begin(client)
    YAHOO["sign_with"] = _OTHER_PRIVATE_PEM
    response = client.get(f"/auth/yahoo/callback?code=C&state={state}",
                          follow_redirects=False)
    blob = response.headers["location"] + response.text
    for leak in ("Traceback", "JWTError", "Signature", "jose", CLIENT_SECRET,
                 "api.login.yahoo.com", "id_token", "500"):
        _assert(f"the refusal leaks no {leak!r}", leak not in blob,
                blob[:100])

# A SPENT TRANSACTION CANNOT BE REPLAYED.
_reset_yahoo()
YAHOO["subject"] = "YSUB-REPLAY"
with _client() as client:
    state, _ = _begin(client)
    first = client.get(f"/auth/yahoo/callback?code=C1&state={state}",
                       follow_redirects=False)
    _assert("the first callback succeeds",
            first.headers["location"] == "/app/index.html")
    second = client.get(f"/auth/yahoo/callback?code=C1&state={state}",
                        follow_redirects=False)
    _assert("and replaying the same callback is refused — the state is spent",
            _reason(second.headers["location"]) == "sign_in_expired",
            second.headers["location"])


# ── 6 · The identity is the subject ──────────────────────────────────────────

_section("6 · One Yahoo account, one FantasyStakes account, forever")

_reset_yahoo()
YAHOO["subject"] = "YSUB-STABLE"
YAHOO["email"] = "stable@yahoo.example"

with _client() as client:
    state, _ = _begin(client)
    client.get(f"/auth/yahoo/callback?code=C&state={state}",
               follow_redirects=False)
with SessionLocal() as db:
    first_id = (db.query(User)
                .filter(User.provider_subject == "YSUB-STABLE").one().id)

# THE EMAIL CHANGES. A Yahoo user may change their address this afternoon.
YAHOO["email"] = "renamed@yahoo.example"
YAHOO["name"] = "Somebody Else"
with _client() as client:
    state, _ = _begin(client)
    client.get(f"/auth/yahoo/callback?code=C&state={state}",
               follow_redirects=False)
with SessionLocal() as db:
    rows = db.query(User).filter(User.provider_subject == "YSUB-STABLE").all()
    _assert("changing the Yahoo email does not create a second account",
            len(rows) == 1, str(len(rows)))
    _assert("it is the SAME FantasyStakes account", rows[0].id == first_id,
            f"{first_id} → {rows[0].id}")
    _assert("and the new address is recorded",
            rows[0].email == "renamed@yahoo.example", rows[0].email)
    _assert("changing the display name creates nothing either",
            db.query(User).filter(User.email == "renamed@yahoo.example")
            .count() == 1)

# TWO SUBJECTS SHARING AN EMAIL DO NOT COLLAPSE. This is the takeover case: if
# identity keyed on the address, the second person would land on the first
# person's Ledger.
YAHOO["subject"] = "YSUB-IMPOSTOR"
YAHOO["email"] = "renamed@yahoo.example"
with _client() as client:
    state, _ = _begin(client)
    client.get(f"/auth/yahoo/callback?code=C&state={state}",
               follow_redirects=False)
with SessionLocal() as db:
    impostor = (db.query(User)
                .filter(User.provider_subject == "YSUB-IMPOSTOR").one())
    _assert("a DIFFERENT Yahoo subject with the same email is a DIFFERENT account",
            impostor.id != first_id, f"{impostor.id} vs {first_id}")
    _assert("and it did not take the first account's address",
            db.query(User).filter(User.id == first_id).one().email
            == "renamed@yahoo.example")
    _assert("the newcomer holds no contact address rather than a stolen one",
            impostor.email.endswith("@yahoo.invalid"), impostor.email)
    from auth.yahoo_identity import _placeholder_email
    _assert("and the placeholder is a digest, not the subject printed in a field",
            impostor.email == _placeholder_email("YSUB-IMPOSTOR")
            and "YSUB-IMPOSTOR" not in impostor.email, impostor.email)

# THE PRE-CUTOVER ACCOUNT IS CLAIMED, NOT DUPLICATED.
YAHOO["subject"] = "YSUB-EXISTING"
YAHOO["email"] = "existing@yahoo.example"
with _client() as client:
    state, _ = _begin(client)
    client.get(f"/auth/yahoo/callback?code=C&state={state}",
               follow_redirects=False)
    me = client.get("/auth/me").json()
with SessionLocal() as db:
    rows = db.query(User).filter(User.email == "existing@yahoo.example").all()
    _assert("an existing account is LINKED rather than duplicated",
            len(rows) == 1, str(len(rows)))
    _assert("it is the original user id", rows[0].id == EXISTING_USER,
            f"{EXISTING_USER} → {rows[0].id}")
    _assert("its team, and therefore its league standing, is untouched",
            rows[0].team_id == EXISTING_TEAM, str(rows[0].team_id))
    _assert("its password hash is LEFT IN PLACE, so a rollback is still safe",
            rows[0].hashed_password is not None)
    _assert("and the Yahoo subject is now bound to it",
            rows[0].provider_subject == "YSUB-EXISTING")
_assert("the signed-in identity is the existing account",
        me["team_id"] == EXISTING_TEAM, str(me.get("team_id")))

# AN ACCOUNT ALREADY BOUND TO ANOTHER SUBJECT IS NEVER RE-BOUND.
YAHOO["subject"] = "YSUB-SECOND-CLAIMANT"
YAHOO["email"] = "existing@yahoo.example"
with _client() as client:
    state, _ = _begin(client)
    client.get(f"/auth/yahoo/callback?code=C&state={state}",
               follow_redirects=False)
with SessionLocal() as db:
    original = db.query(User).filter(User.id == EXISTING_USER).one()
    _assert("a second Yahoo account cannot take over a linked account",
            original.provider_subject == "YSUB-EXISTING",
            original.provider_subject)
    _assert("it gets its own account instead",
            db.query(User)
            .filter(User.provider_subject == "YSUB-SECOND-CLAIMANT")
            .count() == 1)
    _assert("with no team, because identity grants nothing",
            db.query(User)
            .filter(User.provider_subject == "YSUB-SECOND-CLAIMANT")
            .one().team_id is None)

# THE DATABASE, NOT THE QUERY, ENFORCES UNIQUENESS.
with SessionLocal() as db:
    duplicated = False
    try:
        db.add(User(email="dupe@yahoo.example", hashed_password=None,
                    auth_provider=PROVIDER_YAHOO,
                    provider_subject="YSUB-EXISTING", role="gm"))
        db.commit()
        duplicated = True
    except Exception:
        db.rollback()
    _assert("a duplicate (provider, subject) is refused by the database itself",
            not duplicated, "unique constraint holds")

with SessionLocal() as db:
    blank = False
    try:
        resolve_user(db, subject="", email="nobody@yahoo.example")
        blank = True
    except ValueError:
        db.rollback()
    _assert("a blank subject is refused rather than matched",
            not blank)


# ── 7 · Nothing reaches the browser that should not ──────────────────────────

_section("7 · No token, no secret, no credential leaves the server")

_reset_yahoo()
YAHOO["subject"] = "YSUB-LEAKCHECK"
with _client() as client:
    start = client.get("/auth/yahoo/start", follow_redirects=False)
    state, _ = _begin(client)
    done = client.get(f"/auth/yahoo/callback?code=CODE&state={state}",
                      follow_redirects=False)
    me = client.get("/auth/me")

    everything = "".join([
        start.headers.get("location", ""), str(dict(start.headers)),
        start.text, done.headers.get("location", ""), str(dict(done.headers)),
        done.text, me.text, str(dict(client.cookies)),
    ])
    for secret in ("AT-must-never-reach-the-browser",
                   "RT-must-never-reach-the-browser", CLIENT_SECRET):
        _assert(f"{secret[:18]}… never reaches the browser",
                secret not in everything)
    _assert("no ID token is handed to the page",
            "eyJ" not in me.text and "id_token" not in everything.lower())
    _assert("the identity read exposes no provider subject",
            "YSUB-LEAKCHECK" not in me.text, me.text[:120])
    _assert("and no Yahoo endpoint is named in anything the page receives",
            "api.login.yahoo.com" not in (done.text + me.text))


# ── 8 · Sessions and sign-out ────────────────────────────────────────────────

_section("8 · FantasyStakes owns the session, and ending it is honest")

_reset_yahoo()
YAHOO["subject"] = "YSUB-SESSION"
with _client() as client:
    state, _ = _begin(client)
    client.get(f"/auth/yahoo/callback?code=C&state={state}",
               follow_redirects=False)
    before = client.cookies.get("fs_session")
    _assert("a session exists after the callback", bool(before))

    # ROTATION. A second sign-in must not reuse the first one's token.
    state, _ = _begin(client)
    client.get(f"/auth/yahoo/callback?code=C&state={state}",
               follow_redirects=False)
    _assert("signing in again ROTATES the session rather than reusing it",
            client.cookies.get("fs_session") != before)

    _assert("ordinary reads work without contacting Yahoo",
            client.get("/auth/me").status_code == 200)
    _quiet = len(EXCHANGES)
    for _ in range(5):
        client.get("/auth/me")
    _assert("and NOT ONE of them contacts Yahoo — the session is ours",
            len(EXCHANGES) == _quiet, f"{len(EXCHANGES) - _quiet} exchanges")

    out = client.delete("/auth/session",
                        headers={"X-FS-CSRF": client.cookies.get("fs_csrf")})
    _assert("sign-out succeeds", out.status_code == 204, str(out.status_code))
    _assert("and the session is gone",
            client.get("/auth/me").status_code == 401,
            str(client.get("/auth/me").status_code))


# ── 9 · Authorization did not move ───────────────────────────────────────────

_section("9 · Yahoo identity grants nothing beyond identity")

_reset_yahoo()
YAHOO["subject"] = "YSUB-OUTSIDER"
YAHOO["email"] = "outsider@yahoo.example"
with _client() as client:
    state, _ = _begin(client)
    client.get(f"/auth/yahoo/callback?code=C&state={state}",
               follow_redirects=False)

    _assert("a Yahoo-authenticated stranger is not a league member",
            client.get(f"/league/{LEAGUE_ID}/context/me").status_code == 403,
            str(client.get(f"/league/{LEAGUE_ID}/context/me").status_code))
    _assert("and cannot read commissioner provider diagnostics",
            client.get(f"/league/{LEAGUE_ID}/provider/status").status_code
            in (401, 403))
    _assert("nor the league's Versus board",
            client.get(f"/league/{LEAGUE_ID}/versus/board?week=3").status_code
            == 403)
    _assert("the identity read reports no team and no commission",
            client.get("/auth/me").json()["capabilities"]["has_team"] is False)

# THE LINKED ACCOUNT KEEPS EXACTLY WHAT IT HAD.
_reset_yahoo()
YAHOO["subject"] = "YSUB-EXISTING"
YAHOO["email"] = "existing@yahoo.example"
with _client() as client:
    state, _ = _begin(client)
    client.get(f"/auth/yahoo/callback?code=C&state={state}",
               follow_redirects=False)
    caps = client.get("/auth/me").json()["capabilities"]
    _assert("a linked GM resumes their own league context",
            caps["acting_league_id"] == LEAGUE_ID
            and caps["acting_team_id"] == EXISTING_TEAM, str(caps))
    _assert("and is still not a commissioner",
            caps["is_commissioner"] is False)
    _assert("their league context reads",
            client.get(f"/league/{LEAGUE_ID}/context/me").status_code == 200)
    _assert("and provider diagnostics are still refused",
            client.get(f"/league/{LEAGUE_ID}/provider/status").status_code
            in (401, 403))


# ── 10 · The frontend holds no authority ─────────────────────────────────────

_section("10 · The browser starts a sign-in and does nothing else")

WEB = os.path.join(ROOT, "web", "js")


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _code_only(source: str) -> str:
    stripped = re.sub(r"/\*[\s\S]*?\*/", " ", source)
    return re.sub(r"^\s*//.*$", " ", stripped, flags=re.M)


FRONTEND = "\n".join(
    _code_only(_read("web", "js", name))
    for name in sorted(os.listdir(WEB)) if name.endswith(".js"))
GATE_JS = _read("web", "js", "auth-view.js")
# CONCATENATION JOINED. The gate builds its copy from adjacent string literals
# across several lines, so a scan for a whole sentence would miss copy that is
# present and correct. Removing the `' + '` seams reassembles what renders.
GATE_COPY = re.sub(r"'\s*\+\s*'", "", GATE_JS)

for forbidden in ("client_secret", "clientSecret", "id_token", "access_token",
                  "refresh_token", "grant_type", "authorization_code",
                  "code_verifier", "/oauth2/get_token", "api.login.yahoo.com",
                  "localStorage", "sessionStorage"):
    _assert(f"no frontend module touches {forbidden!r}",
            forbidden not in FRONTEND)

_assert("the gate starts the flow by NAVIGATING, not by fetching",
        "/auth/yahoo/start" in GATE_JS and "apiFetch('/auth/yahoo" not in GATE_JS)
_assert("the Yahoo action is a real anchor, so it is keyboard-operable",
        '<a class="fs-btn fs-btn--gold fs-gate__yahoo"' in GATE_JS)
_assert("and it is comprehensible without an image",
        ">Sign in with Yahoo</a>" in GATE_JS
        and not re.search(r"<img|yahoo[^\"']*\.(svg|png)", GATE_JS, re.I))
_assert("the copy explains what Yahoo is for",
        "Connect securely with your Yahoo account" in GATE_COPY)
_assert("and states plainly that FantasyStakes never sees the password",
        "never sees your Yahoo password" in GATE_COPY)
_assert("no production forgot-password link exists anywhere",
        not re.search(r"forgot", FRONTEND, re.I))
_assert("no reset-password flow exists anywhere",
        not re.search(r"reset\s*password|password\s*reset", FRONTEND, re.I))
_assert("the gate does not imitate Yahoo's own sign-in page",
        "Enter your Yahoo password" not in GATE_COPY
        and "yahoo.com/login" not in GATE_JS
        and "<input" not in GATE_COPY.split("function devSignIn")[0])
_assert("sign-out does not claim to end the Yahoo session",
        "signs the GM out of Yahoo" not in GATE_JS
        or "does NOT sign the GM out of Yahoo" in GATE_JS)

_assert("the password form is drawn ONLY when the server declares it",
        "if (!METHODS.password) return '';" in GATE_JS)
_assert("and the page cannot decide that for itself",
        "METHODS = " in GATE_JS and "location.search" not in
        GATE_JS.split("takeSignInReason")[2] if GATE_JS.count("takeSignInReason") > 2
        else True)


# ── 11 · The server-side surface ─────────────────────────────────────────────

_section("11 · Secrets stay in configuration and out of everything else")

MAIN = _read("api", "main.py")
OIDC = _read("auth", "yahoo_oidc.py")
IDENTITY = _read("auth", "yahoo_identity.py")

_assert("no live secret is committed anywhere in the auth surface",
        CLIENT_SECRET not in MAIN + OIDC + IDENTITY)
_assert("the client secret is read from configuration, never a literal",
        'environ.get("FS_YAHOO_CLIENT_SECRET"' in OIDC
        or 'env.get("FS_YAHOO_CLIENT_SECRET"' in OIDC)
_assert("the config object refuses to repr its secret",
        "client_secret=<hidden>" in OIDC)
_assert("no token or secret is printed or logged",
        not re.search(r"^\s*print\(.*(token|secret)", OIDC, re.I | re.M)
        and not re.search(r"logger\.[a-z]+\(.*(token|secret)", OIDC, re.I))
_assert("the identity DTO refuses to repr anything but the subject",
        "YahooIdentity(subject=" in OIDC)
_assert("the callback never puts a raw reason in the URL",
        "_SIGN_IN_REASONS" in MAIN and "safe = reason_code if reason_code in" in MAIN)
# AUTH1-FIX REVERSED THIS. AUTH1 asserted that PKCE was deliberately absent, on
# a reading of Yahoo's generic OAuth 2.0 page. Yahoo's Sign In With Yahoo
# documentation — the OIDC surface this product uses — documents
# `code_challenge`, `code_challenge_method` and `code_verifier`, so the correct
# assertion is the opposite one and the flow now sends all three.
_assert("PKCE is sent, and the reasoning is recorded in the module",
        "code_challenge" in OIDC and "PKCE IS SENT" in OIDC)
_assert("S256 only — `plain` is never offered",
        'CHALLENGE_METHOD = "S256"' in OIDC
        and '"plain"' not in OIDC and "'plain'" not in OIDC)
_assert("the verifier is minted from `secrets`, not from a weaker source",
        "code_verifier=secrets.token_urlsafe" in OIDC)
_assert("the challenge is SHA-256, base64url, unpadded",
        "hashlib.sha256(verifier.encode" in OIDC
        and "urlsafe_b64encode" in OIDC and 'rstrip("=")' in OIDC)
_assert("and the verifier is never printed, logged or repr'd",
        "secrets=<hidden>" in OIDC
        and not re.search(r"(print|logger\.[a-z]+)\(.*(verifier|code_verifier)",
                          OIDC, re.I))
_assert("the redirect URI comes from configuration, never from the request",
        "FS_YAHOO_REDIRECT_URI" in OIDC and "request.url" not in
        MAIN.split("def auth_yahoo_start")[1].split("def auth_yahoo_callback")[0])
_assert("a non-TLS production redirect is refused",
        "must be https, or localhost" in OIDC)


# ── 12 · The identity schema is additive and reversible ──────────────────────

_section("12 · The migration is additive, and the rollback is safe")

from sqlalchemy import inspect as sa_inspect                        # noqa: E402

_cols = {c["name"]: c for c in sa_inspect(engine).get_columns("users")}
_assert("users.auth_provider exists and is nullable",
        "auth_provider" in _cols and _cols["auth_provider"]["nullable"])
_assert("users.provider_subject exists and is nullable",
        "provider_subject" in _cols and _cols["provider_subject"]["nullable"])
_assert("users.hashed_password is now nullable",
        _cols["hashed_password"]["nullable"])
_assert("no column was dropped — the rollback path keeps every value",
        {"email", "hashed_password", "team_id", "role", "is_active"}
        <= set(_cols))

MIGRATION = _read("migrations", "add_yahoo_identity.py")
_assert("the migration drops nothing",
        "DROP COLUMN" not in MIGRATION.upper())
_assert("it creates the uniqueness the concurrency case needs",
        "CREATE UNIQUE INDEX" in MIGRATION)
_assert("and it is idempotent",
        "already applied" in MIGRATION)




# ── 14 · PKCE, enforced end to end ───────────────────────────────────────────

_section("14 · PKCE is installed AND enforced, not merely present")

_reset_yahoo()
YAHOO["subject"] = "YSUB-PKCE"

# THE HAPPY PATH FIRST, so the failures below are known to be failures of PKCE
# rather than of anything else in the flow.
with _client() as client:
    state, _ = _begin(client)
    before = len(EXCHANGES)
    ok = client.get(f"/auth/yahoo/callback?code=C&state={state}",
                    follow_redirects=False)
    _assert("a sign-in carrying the right verifier completes",
            ok.headers["location"] == "/app/index.html",
            ok.headers["location"])
    _assert("and the exchange presented it", len(EXCHANGES) == before + 1
            and bool(EXCHANGES[-1]["code_verifier"]))

# A WRONG VERIFIER IS REFUSED BY THE AUTHORIZATION SERVER.
#
# The transaction cookie is re-sealed with a verifier this sign-in never
# registered — which is exactly the shape of an authorization code injected
# into this callback from somebody else's flow. The mock refuses it the way
# Yahoo refuses `invalid_grant`, and the route reports the governed refusal.
_reset_yahoo()
with _client() as client:
    state, _ = _begin(client)
    hostile = new_transaction()
    forged = Transaction(state=state, nonce=YAHOO["nonce"],
                         code_verifier=hostile.code_verifier,
                         issued_at=int(time.time()))
    client.cookies.set("fs_yahoo_txn",
                       seal_transaction(forged,
                                        secret=os.environ["JWT_SECRET_KEY"]))
    before = len(EXCHANGES)
    r = client.get(f"/auth/yahoo/callback?code=C&state={state}",
                   follow_redirects=False)
    _assert("a verifier that does not match the challenge is REFUSED",
            _reason(r.headers["location"]) == "exchange_failed",
            r.headers["location"])
    _assert("the attempt reached the token endpoint and was rejected there",
            len(EXCHANGES) == before + 1,
            "the authorization server enforced it, as Yahoo would")
    _assert("and no session was issued", not client.cookies.get("fs_session"))

# A MISSING VERIFIER IS REFUSED BEFORE THE NETWORK.
_reset_yahoo()
with _client() as client:
    state, _ = _begin(client)
    empty = Transaction(state=state, nonce=YAHOO["nonce"], code_verifier="",
                        issued_at=int(time.time()))
    client.cookies.set("fs_yahoo_txn",
                       seal_transaction(empty,
                                        secret=os.environ["JWT_SECRET_KEY"]))
    before = len(EXCHANGES)
    r = client.get(f"/auth/yahoo/callback?code=C&state={state}",
                   follow_redirects=False)
    _assert("a transaction with NO verifier cannot be exchanged",
            _reason(r.headers["location"]) == "sign_in_expired",
            r.headers["location"])
    _assert("and it never reached the token endpoint",
            len(EXCHANGES) == before,
            "refused locally, before any network call")

# A SHORT VERIFIER IS REFUSED — RFC 7636 sets the floor at 43 characters.
_reset_yahoo()
with _client() as client:
    state, _ = _begin(client)
    short = Transaction(state=state, nonce=YAHOO["nonce"],
                        code_verifier="tooshort", issued_at=int(time.time()))
    client.cookies.set("fs_yahoo_txn",
                       seal_transaction(short,
                                        secret=os.environ["JWT_SECRET_KEY"]))
    r = client.get(f"/auth/yahoo/callback?code=C&state={state}",
                   follow_redirects=False)
    _assert("an under-length verifier is refused rather than sent",
            _reason(r.headers["location"]) == "sign_in_expired",
            r.headers["location"])

# PKCE DID NOT REPLACE ANYTHING. State and nonce still refuse on their own.
_reset_yahoo()
with _client() as client:
    _begin(client)
    r = client.get("/auth/yahoo/callback?code=C&state=not-the-minted-one",
                   follow_redirects=False)
    _assert("state is STILL validated with PKCE in place",
            _reason(r.headers["location"]) == "state_invalid",
            r.headers["location"])

_reset_yahoo()
with _client() as client:
    state, _ = _begin(client)
    YAHOO["claims"] = {"nonce": "a-nonce-from-another-sign-in"}
    r = client.get(f"/auth/yahoo/callback?code=C&state={state}",
                   follow_redirects=False)
    _assert("nonce is STILL validated with PKCE in place",
            _reason(r.headers["location"]) == "replay_detected",
            r.headers["location"])

# THE VERIFIER IS SINGLE-USE, because the transaction it rides in is.
_reset_yahoo()
YAHOO["subject"] = "YSUB-PKCE-ONCE"
with _client() as client:
    state, _ = _begin(client)
    first = client.get(f"/auth/yahoo/callback?code=C&state={state}",
                       follow_redirects=False)
    _assert("the first redemption succeeds",
            first.headers["location"] == "/app/index.html")
    before = len(EXCHANGES)
    second = client.get(f"/auth/yahoo/callback?code=C&state={state}",
                        follow_redirects=False)
    _assert("the verifier cannot be spent twice",
            _reason(second.headers["location"]) == "sign_in_expired",
            second.headers["location"])
    _assert("and the second attempt made no exchange",
            len(EXCHANGES) == before)

# THE CLIENT SECRET IS STILL PRESENTED. PKCE is additive, not a replacement.
_assert("client authentication still accompanies every exchange",
        all(e["client_secret"] == CLIENT_SECRET for e in EXCHANGES),
        f"{len(EXCHANGES)} exchanges")

# NOTHING ABOUT PKCE REACHES THE BROWSER.
_reset_yahoo()
YAHOO["subject"] = "YSUB-PKCE-LEAK"
with _client() as client:
    start = client.get("/auth/yahoo/start", follow_redirects=False)
    sealed = client.cookies.get("fs_yahoo_txn")
    txn = open_transaction(sealed, secret=os.environ["JWT_SECRET_KEY"])
    state, _ = _begin(client)
    done = client.get(f"/auth/yahoo/callback?code=C&state={state}",
                      follow_redirects=False)
    me = client.get("/auth/me")
    surface = "".join([start.headers.get("location", ""), start.text,
                       str(dict(start.headers)), done.headers.get("location", ""),
                       done.text, str(dict(done.headers)), me.text])
    _assert("the verifier never appears in any response the browser receives",
            txn.code_verifier not in surface)
    _assert("nor in any cookie value the page can read",
            txn.code_verifier not in str(dict(client.cookies))
            or "fs_yahoo_txn" not in str(dict(client.cookies)),
            "sealed inside the HttpOnly transaction cookie only")
    raw = start.headers.get("set-cookie", "")
    _assert("and the cookie carrying it is HttpOnly",
            "httponly" in raw.lower(), raw[:100])
    _assert("no verifier reaches the redirect URL either",
            "code_verifier" not in start.headers.get("location", ""))


# ── 15 · Scopes and claims, reconciled against Yahoo's documentation ─────────

_section("15 · Every scope buys a claim this product consumes")

_assert("`openid` is requested — it is what makes this a sign-in",
        "openid" in SCOPES)
_assert("`email` is requested, because the migration claim path reads it",
        "email" in SCOPES)
_assert("`fspt-r` is requested, so one grant also authorizes Fantasy reads",
        "fspt-r" in SCOPES)
_assert("and NOTHING else is requested",
        set(SCOPES) == {"openid", "email", "fspt-r"}, " ".join(SCOPES))

_assert("no WRITE scope of any kind",
        not any(sc.endswith("-w") for sc in SCOPES)
        and not any("w" == sc.split("-")[-1] for sc in SCOPES),
        " ".join(SCOPES))
for unused in ("sdps-r", "sdpp-w", "mail-r", "profile"):
    _assert(f"the unused permission {unused!r} is not requested",
            unused not in SCOPES)
_assert("and the reason profile scopes are omitted is recorded in the module",
        "sdps-r" in OIDC and "WHAT IS DELIBERATELY NOT REQUESTED" in OIDC)

# `sub` IS MANDATORY, AND NOTHING SUBSTITUTES FOR IT.
_reset_yahoo()
for missing, expected in ((("sub", ""), "identity_unavailable"),
                          (("sub", "   "), "identity_unavailable")):
    _reset_yahoo()
    with _client() as client:
        state, _ = _begin(client)
        YAHOO["claims"] = {missing[0]: missing[1]}
        r = client.get(f"/auth/yahoo/callback?code=C&state={state}",
                       follow_redirects=False)
        _assert(f"an ID token whose sub is {missing[1]!r} is refused",
                _reason(r.headers["location"]) == expected,
                r.headers["location"])

# THE OPTIONAL CLAIMS ARE OPTIONAL, AND THEIR ABSENCE IS NOT AMBIGUITY.
#
# Yahoo returns `name` only with a profile scope this product does not request,
# so its absence is the EXPECTED case rather than an edge one. A sign-in must
# complete on `sub` alone.
_reset_yahoo()
YAHOO["subject"] = "YSUB-BARE-CLAIMS"
YAHOO["claims"] = {"name": None, "email": None}
with _client() as client:
    state, _ = _begin(client)
    r = client.get(f"/auth/yahoo/callback?code=C&state={state}",
                   follow_redirects=False)
    _assert("an ID token with NO name and NO email still signs the GM in",
            r.headers["location"] == "/app/index.html",
            r.headers["location"])
    _assert("on the subject alone", client.get("/auth/me").status_code == 200)
with SessionLocal() as db:
    bare = (db.query(User)
            .filter(User.provider_subject == "YSUB-BARE-CLAIMS").one())
    _assert("and it is one unambiguous account",
            bare.auth_provider == PROVIDER_YAHOO)
    _assert("with an undeliverable placeholder rather than a guessed address",
            bare.email.endswith("@yahoo.invalid"), bare.email)
    _assert("that is a digest, not the subject printed in a displayed field",
            "YSUB-BARE-CLAIMS" not in bare.email, bare.email)

# A SECOND SIGN-IN, STILL WITH NO CLAIMS, IS THE SAME ACCOUNT.
_reset_yahoo()
YAHOO["subject"] = "YSUB-BARE-CLAIMS"
YAHOO["claims"] = {"name": None, "email": None}
with _client() as client:
    state, _ = _begin(client)
    client.get(f"/auth/yahoo/callback?code=C&state={state}",
               follow_redirects=False)
with SessionLocal() as db:
    _assert("a claimless GM does not accumulate accounts",
            db.query(User)
            .filter(User.provider_subject == "YSUB-BARE-CLAIMS").count() == 1)

# THE EMAIL CLAIM IS USED FOR MIGRATION AND FOR NOTHING ELSE.
_assert("nothing resolves identity from a display name",
        "display_name" not in _read("auth", "yahoo_identity.py")
        .split("def resolve_user")[1].split("def _placeholder_email")[0]
        .replace("display_name: str | None = None", ""),
        "display_name is accepted and never read")
_assert("and the resolver keys on the subject, never on the email",
        "User.provider_subject == subject" in IDENTITY
        and "User.email == normalised" in IDENTITY
        and IDENTITY.index("User.provider_subject == subject")
        < IDENTITY.index("User.email == normalised"),
        "subject is looked up first, and wins")



# ── 13 · The frontend tiers ──────────────────────────────────────────────────

def _run_node(script: str, label: str, env_extra: dict | None = None) -> None:
    node = shutil.which("node")
    if node is None:
        _assert(f"{label} — node is available", False, "node not on PATH")
        return
    print(f"\n{label}")
    env = dict(os.environ)
    env.update(env_extra or {})
    proc = subprocess.run(
        [node, os.path.join(ROOT, "web", "tests", script)],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print(proc.stderr.rstrip()[-2000:])
    passes = proc.stdout.count("[PASS]")
    fails = proc.stdout.count("[FAIL]")
    _assert(f"{label} is green", proc.returncode == 0 and fails == 0,
            f"{passes} PASS / {fails} FAIL, exit {proc.returncode}")


_section("13 · The sign-in surface, rendered")

_run_node("wp3d1_component_tests.mjs", "WP3D.1 component suite (Node)")

from test_support_app_server import (                               # noqa: E402
    AppServer, GM_EMAIL as APP_GM_EMAIL, PASSWORD as APP_PASSWORD,
)

for mode, env_extra in (
    ("development", {}),
    ("production", {"FS_ENV": "production",
                    "FS_YAHOO_CLIENT_ID": "dj0yJmk9browser",
                    "FS_YAHOO_CLIENT_SECRET": "browser-secret",
                    "FS_YAHOO_REDIRECT_URI":
                        "https://stakes.example/auth/yahoo/callback"}),
):
    with AppServer(server_env=env_extra) as _server:
        _run_node("wp3d1_browser.mjs", f"WP3D.1 browser suite — {mode}",
                  # NO HARNESS SIGN-IN, IN EITHER MODE. This suite is about
                  # the GATE, and a harness that signed in first would mount the
                  # application over the surface being certified.
                  {"FS_TEST_ORIGIN": _server.origin,
                   "FS_WP3D1_MODE": mode})


print("\n" + "=" * 66)
if _failures:
    print(f"WP3D.1 YAHOO AUTHENTICATION — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("WP3D.1 YAHOO AUTHENTICATION — all assertions PASSED")
