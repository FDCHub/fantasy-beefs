"""
auth/yahoo_oidc.py — Sign in with Yahoo, on OpenID Connect over OAuth 2.0.

WHAT THIS OWNS. Building the authorization URL, exchanging the code for tokens,
and validating the identity token that comes back. It owns no user, no session,
no cookie and no route; `api/main.py` composes those around it.

WHAT FANTASYSTAKES NEVER SEES. The Yahoo password. Yahoo authenticates the Yahoo
account by whatever method that account uses — password, Account Key, a
verification prompt — and tells us only that it succeeded and who it was. There
is no field anywhere in this product that could hold a Yahoo credential, and the
browser never touches the exchange: the client secret lives in server
configuration and the code is redeemed server-side, once.

── THE FLOW, AND WHERE EACH GUARD SITS ──────────────────────────────────────

    start     mint `state` and `nonce`, stash them in a short-lived signed
              cookie, redirect to Yahoo
    Yahoo     authenticates the account and asks the user to approve
    callback   1. the `state` in the query must equal the one we stashed
               2. exchange the code, server-side, with client authentication
               3. the ID token must be signed by Yahoo, issued by Yahoo,
                  audienced to US, unexpired, and carry OUR nonce
               4. `sub` is the identity; nothing else is

    `state` defeats CSRF on the callback: a forged redirect carries a value we
    never minted. `nonce` defeats replay of a captured ID token into a new
    sign-in: the token names the exact request it was issued for. They are
    different attacks and both guards are required.

PKCE IS DELIBERATELY NOT SENT. PKCE protects a PUBLIC client that cannot keep a
secret — a mobile or SPA client where the code could be intercepted before the
exchange. FantasyStakes is a CONFIDENTIAL client: the exchange happens on the
server, authenticated with the client secret, so an intercepted code is useless
without it. Yahoo does not document PKCE support for this flow, and §7 of the
package is explicit that a mechanism the provider does not support must not be
invented. State plus nonce plus a confidential exchange is the correct posture
here, and this paragraph is the record of that decision.

THE NETWORK IS A SEAM. `TokenExchange` and `KeyResolver` are the only two things
that touch Yahoo, and both are injectable. That is what lets the certification
suite drive the REAL callback, the REAL validation and the REAL identity
resolution against a deterministic boundary — one code path, exercised by tests,
rather than a second "test mode" that could diverge from what ships.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from jose import jwt
from jose.exceptions import JWTError

__all__ = [
    "AUTHORIZE_URL",
    "ISSUERS",
    "JWKS_URL",
    "SCOPES",
    "TOKEN_URL",
    "OidcConfig",
    "OidcError",
    "YahooIdentity",
    "authorization_url",
    "exchange_code",
    "load_config",
    "new_transaction",
    "validate_id_token",
]

# ── Yahoo's own endpoints ─────────────────────────────────────────────────────
#
# Constants, not configuration. These are Yahoo's, they are the same for every
# deployment, and making them settable would mean a misconfigured environment
# could point the sign-in at somebody else's authorization server.

AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
JWKS_URL = "https://api.login.yahoo.com/openid/v1/certs"

#: Accepted `iss` values. Yahoo has used both spellings across its OIDC
#: documentation; both are Yahoo, and neither is anybody else.
ISSUERS = ("https://api.login.yahoo.com", "https://login.yahoo.com")

#: ONE AUTHORIZATION, TWO PURPOSES — the §6 preference, made concrete.
#:
#: `openid` is what turns the grant into an identity assertion and makes Yahoo
#: return an ID token. `fspt-r` is Yahoo's Fantasy Sports READ scope, so the
#: same grant that identifies the GM also authorizes reading the Fantasy
#: leagues the product exists to read. Asking twice — once to know who someone
#: is and again to read their league — would be two consent screens for one
#: relationship.
#:
#: NO WRITE SCOPE. FantasyStakes reads Yahoo and writes nothing to it.
SCOPES = ("openid", "fspt-r")

#: How long an in-flight sign-in may take before its state is stale. Long
#: enough for a real person to complete a Yahoo verification prompt, short
#: enough that a captured state is not useful later.
TRANSACTION_TTL_SECONDS = 10 * 60

#: Clock skew tolerated when checking `exp`.
LEEWAY_SECONDS = 60


class OidcError(Exception):
    """A sign-in could not be completed.

    CARRIES A REASON CODE, NOT A MESSAGE FOR THE USER. The route maps the code
    to product language; the detail stays server-side. Nothing in `detail` is
    ever rendered, logged to a user-visible surface, or put in a URL.
    """

    def __init__(self, reason_code: str, detail: str = ""):
        super().__init__(detail or reason_code)
        self.reason_code = reason_code
        self.detail = detail


@dataclass(frozen=True)
class OidcConfig:
    """The three values a deployment supplies. The secret never leaves here."""

    client_id: str
    client_secret: str
    redirect_uri: str

    def __repr__(self) -> str:            # pragma: no cover - defensive
        # NEVER REPR THE SECRET. A dataclass would print it, and a dataclass in
        # an exception traceback would print it into a log.
        return (f"OidcConfig(client_id={self.client_id!r}, "
                f"redirect_uri={self.redirect_uri!r}, client_secret=<hidden>)")


def load_config(environ: dict | None = None) -> OidcConfig:
    """Read the deployment's Yahoo configuration, or refuse.

    THE REDIRECT URI IS THE SERVER'S, ALWAYS. It is configuration, never
    anything the browser supplies — a callback target a caller could choose is
    an open redirector with an authorization code attached to it.
    """
    env = os.environ if environ is None else environ
    client_id = (env.get("FS_YAHOO_CLIENT_ID", "") or "").strip()
    client_secret = (env.get("FS_YAHOO_CLIENT_SECRET", "") or "").strip()
    redirect_uri = (env.get("FS_YAHOO_REDIRECT_URI", "") or "").strip()
    if not (client_id and client_secret and redirect_uri):
        raise OidcError("sign_in_unavailable",
                        "Yahoo sign-in configuration is incomplete")
    if not redirect_uri.lower().startswith(("https://", "http://localhost",
                                            "http://127.0.0.1")):
        # A production callback must be TLS. Localhost is allowed unencrypted
        # because Yahoo permits it for development and there is no network.
        raise OidcError("sign_in_unavailable",
                        "FS_YAHOO_REDIRECT_URI must be https, or localhost")
    return OidcConfig(client_id=client_id, client_secret=client_secret,
                      redirect_uri=redirect_uri)


@dataclass(frozen=True)
class Transaction:
    """The two secrets that bind one sign-in attempt to one callback."""

    state: str
    nonce: str
    issued_at: int

    def as_claims(self) -> dict:
        return {"state": self.state, "nonce": self.nonce, "iat": self.issued_at}


def new_transaction() -> Transaction:
    """Mint a fresh state and nonce.

    BOTH FROM `secrets`, both 256 bits of entropy. `state` is what makes a
    forged callback detectable; `nonce` is what makes a replayed ID token
    detectable. Neither is derived from the other, because an attacker who
    learned one must not learn the other.
    """
    return Transaction(state=secrets.token_urlsafe(32),
                       nonce=secrets.token_urlsafe(32),
                       issued_at=int(time.time()))


def authorization_url(config: OidcConfig, transaction: Transaction) -> str:
    """Where to send the browser to have Yahoo authenticate the account."""
    query = urllib.parse.urlencode({
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": transaction.state,
        "nonce": transaction.nonce,
    })
    return f"{AUTHORIZE_URL}?{query}"


# ── The two network seams ─────────────────────────────────────────────────────

class TokenExchange(Protocol):
    """Redeem an authorization code. The only outbound call in the flow."""

    def __call__(self, *, config: OidcConfig, code: str) -> dict: ...


class KeyResolver(Protocol):
    """Yahoo's signing key for a given ID token header."""

    def __call__(self, *, kid: str | None, alg: str) -> Any: ...


def _live_exchange(*, config: OidcConfig, code: str) -> dict:
    """Redeem the code against Yahoo, with HTTP Basic client authentication.

    THE SECRET GOES IN THE HEADER, NOT THE BODY, and never into a query string:
    a query string is logged by proxies and by Yahoo, and a body is not. It
    never appears in this module's return value either.
    """
    import requests

    basic = base64.b64encode(
        f"{config.client_id}:{config.client_secret}".encode()).decode()
    try:
        response = requests.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {basic}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "authorization_code",
                  "redirect_uri": config.redirect_uri,
                  "code": code},
            timeout=15,
        )
    except Exception as exc:                       # pragma: no cover - network
        raise OidcError("provider_unreachable", f"token endpoint: {exc!r}")

    if response.status_code != 200:
        # THE BODY IS NOT PROPAGATED. Yahoo's error bodies are diagnostics and
        # can echo request parameters; the status is enough to classify.
        raise OidcError("exchange_failed",
                        f"token endpoint returned {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:                      # pragma: no cover - network
        raise OidcError("exchange_failed", f"token endpoint gave non-JSON: {exc!r}")


def _live_key(*, kid: str | None, alg: str) -> Any:  # pragma: no cover - network
    """Fetch Yahoo's JWKS and return the key the token names."""
    import requests

    try:
        jwks = requests.get(JWKS_URL, timeout=15).json()
    except Exception as exc:
        raise OidcError("provider_unreachable", f"jwks: {exc!r}")
    for key in jwks.get("keys", []):
        if kid is None or key.get("kid") == kid:
            return key
    raise OidcError("identity_token_invalid", "no matching signing key")


def exchange_code(code: str, *, config: OidcConfig,
                  exchange: TokenExchange | None = None) -> dict:
    """Trade the authorization code for Yahoo's token response.

    VALIDATES THE SHAPE BEFORE ANYTHING TRUSTS IT. A token response with no
    `id_token` is not an identity assertion — it is an access grant, and
    treating it as a sign-in would authenticate nobody while appearing to
    succeed.
    """
    payload = (exchange or _live_exchange)(config=config, code=code)
    if not isinstance(payload, dict):
        raise OidcError("exchange_failed", "token response was not an object")
    if not payload.get("id_token"):
        raise OidcError("identity_unavailable",
                        "token response carried no id_token")
    if not payload.get("access_token"):
        raise OidcError("exchange_failed",
                        "token response carried no access_token")
    return payload


@dataclass(frozen=True)
class YahooIdentity:
    """Who Yahoo says this is.

    `subject` IS THE IDENTITY AND THE OTHERS ARE NOT. Yahoo's `sub` is stable
    for the life of the account; the email and the display name are properties
    of it that a user may change this afternoon. Keying on either would give the
    same person a second FantasyStakes account the day they change it, and would
    hand one person's league to another if an address were ever reassigned.
    """

    subject: str
    email: str | None
    display_name: str | None

    def __repr__(self) -> str:            # pragma: no cover - defensive
        return f"YahooIdentity(subject={self.subject!r})"


def validate_id_token(id_token: str, *, config: OidcConfig, nonce: str,
                      key_resolver: KeyResolver | None = None,
                      now: int | None = None) -> YahooIdentity:
    """Verify Yahoo's identity token and return the identity it asserts.

    EVERY CHECK HERE IS LOAD-BEARING, and skipping any one of them is a
    different real attack:

      signature   without it the token is a JSON object anybody can author
      issuer      without it another OIDC provider's token would be accepted
      audience    without it a token minted for a DIFFERENT Yahoo application
                  would sign its user into this one
      expiry      without it a token stays a credential forever
      nonce       without it a token captured from one sign-in replays into
                  another
      subject     without it there is no identity to resolve

    `python-jose` performs the first four when told what to expect, so they are
    passed explicitly rather than disabled; the nonce and the subject are
    checked here because they are this application's business.
    """
    header = _unverified_header(id_token)
    alg = header.get("alg", "")
    if alg not in ("RS256", "RS384", "RS512"):
        # `none` is the classic forgery, and a symmetric algorithm would let
        # anyone holding the client secret mint an identity for anyone.
        raise OidcError("identity_token_invalid", f"unacceptable alg {alg!r}")

    key = (key_resolver or _live_key)(kid=header.get("kid"), alg=alg)

    try:
        claims = jwt.decode(
            id_token, key, algorithms=[alg],
            audience=config.client_id,
            options={"verify_aud": True, "verify_exp": True,
                     "verify_signature": True, "leeway": LEEWAY_SECONDS},
        )
    except JWTError as exc:
        raise OidcError("identity_token_invalid", f"decode failed: {exc!r}")

    issuer = claims.get("iss")
    if issuer not in ISSUERS:
        raise OidcError("identity_token_invalid", f"unexpected issuer {issuer!r}")

    # AUDIENCE, CHECKED AGAIN AND ON PURPOSE. `verify_aud` above accepts a list
    # containing our id; a token audienced to us AND to somebody else is not a
    # token minted for this application alone, and Yahoo does not issue one.
    audience = claims.get("aud")
    if audience != config.client_id and audience != [config.client_id]:
        raise OidcError("identity_token_invalid", "audience is not this client")

    if not claims.get("nonce"):
        raise OidcError("identity_token_invalid", "token carries no nonce")
    if not secrets.compare_digest(str(claims["nonce"]), str(nonce)):
        raise OidcError("replay_detected", "nonce does not match this sign-in")

    expires = claims.get("exp")
    moment = int(time.time()) if now is None else now
    if not isinstance(expires, (int, float)) or moment - LEEWAY_SECONDS > expires:
        raise OidcError("identity_token_invalid", "token is expired")

    subject = claims.get("sub")
    if not subject or not str(subject).strip():
        raise OidcError("identity_unavailable", "token carries no subject")

    return YahooIdentity(
        subject=str(subject).strip(),
        email=_clean(claims.get("email")),
        display_name=_clean(claims.get("name") or claims.get("nickname")),
    )


def _unverified_header(token: str) -> dict:
    try:
        return jwt.get_unverified_header(token)
    except Exception as exc:
        raise OidcError("identity_token_invalid", f"unreadable header: {exc!r}")


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


# ── The transaction cookie ────────────────────────────────────────────────────
#
# STATE AND NONCE LIVE IN A SIGNED, HttpOnly, SHORT-LIVED COOKIE rather than in
# a server-side table. They are single-use, they expire in minutes, and a table
# would need a reaper. Signing them with the application's own key is what makes
# the cookie unforgeable; `HttpOnly` is what keeps script from reading the nonce
# and mounting the replay the nonce exists to prevent.

def seal_transaction(transaction: Transaction, *, secret: str) -> str:
    return jwt.encode(transaction.as_claims(), secret, algorithm="HS256")


def open_transaction(sealed: str, *, secret: str,
                     now: int | None = None) -> Transaction:
    try:
        claims = jwt.decode(sealed, secret, algorithms=["HS256"],
                            options={"verify_aud": False})
    except JWTError as exc:
        raise OidcError("sign_in_expired", f"transaction unreadable: {exc!r}")
    issued = int(claims.get("iat", 0))
    moment = int(time.time()) if now is None else now
    if moment - issued > TRANSACTION_TTL_SECONDS:
        raise OidcError("sign_in_expired", "sign-in took too long")
    return Transaction(state=str(claims.get("state", "")),
                       nonce=str(claims.get("nonce", "")),
                       issued_at=issued)


def json_safe(payload: dict) -> str:      # pragma: no cover - diagnostics only
    """A token response with every credential removed. For tests, never logs."""
    redacted = {k: ("<redacted>" if "token" in k or "secret" in k else v)
                for k, v in payload.items()}
    return json.dumps(redacted, sort_keys=True)
