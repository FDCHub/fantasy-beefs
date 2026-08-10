"""
Browser session custody — S8-P1.

WHY THIS MODULE EXISTS. `auth/jwt_auth.py` issues a Bearer token, which is the
right credential for an API client and the wrong one for a browser: a token the
page can read is a token a script can exfiltrate. Sprint 8's ruling is that the
browser authenticates with a Secure, HttpOnly, SameSite=Lax cookie and that no
JWT ever reaches JavaScript. This module owns that cookie — its attributes, its
lifetime, and the CSRF defence that a cookie credential makes necessary.

TWO CREDENTIALS, ONE AUTHORITY. The Bearer path is unchanged and still
supported for non-browser clients. Both paths resolve through the SAME
`get_current_user` and therefore through the same role and ownership guards;
this module adds a way to present a credential, never a way to hold authority.

WHY A COOKIE NEEDS CSRF AT ALL. HttpOnly stops a script reading the credential.
It does nothing about a cross-site form or image tag causing the BROWSER to
attach it to a state-changing request. SameSite=Lax blocks the common
cross-site POST, but it is one browser-side control with known edge cases
(top-level navigations, older clients that ignore the attribute), and the
ruling is explicit that HttpOnly alone is not CSRF protection. So the cookie is
paired with a token check.

THE CSRF DESIGN — SIGNED DOUBLE-SUBMIT, NOT PLAIN DOUBLE-SUBMIT. At login the
server mints a random CSRF token and does two things with it: it embeds the
token as a `csrf` claim INSIDE the signed session JWT (which the page cannot
read), and it sets the same raw value in a second, script-readable cookie
(which the page can read but cannot forge a matching JWT for). An unsafe
request must echo the readable value in the `X-FS-CSRF` header, and the server
accepts it only if it equals the claim inside the signed token.

Plain double-submit — comparing header to cookie — is defeated by anything that
can write a cookie for the site, including a compromised sibling subdomain,
because the attacker controls both halves. Binding one half to the JWT
signature closes that: forging a match requires the signing key.

A SESSION COOKIE MUST CARRY THAT CLAIM. A token minted for the API path has no
`csrf` claim, so `read_session_claims()` refuses it when it arrives in the
cookie. Without that rule an attacker holding any valid API token could plant
it as a session cookie and transact with no CSRF token at all — CSRF protection
would be opt-out by choice of credential.

ORIGIN IS CHECKED TOO, as defence in depth. It is not the primary control: a
same-origin fetch always carries a correct `Origin`, so a mismatch means
something is wrong regardless of what the token check says.

SECURE IS THE DEFAULT AND THE OPT-OUT IS NARROW. `Secure` is on unless
FS_COOKIE_INSECURE=1 is set explicitly, which exists so a plain-HTTP local
harness can run. It is never inferred from DEBUG, from the absence of TLS, or
from the request scheme — a misconfigured proxy must not be able to silently
downgrade a production cookie.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Request, Response

# ── Names ─────────────────────────────────────────────────────────────────────

#: HttpOnly. Holds the signed session JWT. JavaScript can never read this.
SESSION_COOKIE = "fs_session"

#: NOT HttpOnly, deliberately — the page must read it to echo it back. It is
#: not a credential: on its own it authenticates nothing.
CSRF_COOKIE = "fs_csrf"

#: The header an unsafe cookie-authenticated request must carry.
CSRF_HEADER = "X-FS-CSRF"

#: Claim carrying the CSRF token inside the signed session token.
CSRF_CLAIM = "csrf"

#: Claim distinguishing a browser session token from an API Bearer token.
CONTEXT_CLAIM = "ctx"
CONTEXT_BROWSER = "browser"

#: Methods that may change state and therefore require a CSRF token when the
#: caller presents the ambient cookie credential.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: GET routes that change state despite their verb. EMPTY, AND MEANT TO STAY SO.
#:
#: P1 found one — `GET /settle/{week}` called `settle_week()` — and listed it
#: here so the CSRF gate would cover a mutation spelled as a read. S8-P2 fixed
#: the contract instead: the route is now `POST /settle/{week}`, the method
#: gate covers it for the ordinary reason, and there is no compatibility GET.
#:
#: The mechanism is kept rather than deleted, at zero cost, because it is the
#: honest way to record the rule: a GET that writes is a defect, and if one is
#: ever introduced this is where it must be declared and where the control in
#: test_s8_p2_authorization.py will find it. An empty tuple asserts the claim
#: "there are no state-changing GETs" in a form that can be checked, which a
#: deleted constant cannot.
STATE_CHANGING_GET_PREFIXES: tuple[str, ...] = ()

_SESSION_MAX_AGE_SECONDS = 8 * 60 * 60   # matches TOKEN_EXPIRE_HOURS


def cookie_secure() -> bool:
    """True unless a local harness has explicitly opted out.

    Read at call time rather than import time so a test can set the variable
    around a single app instance without leaking the setting into the process
    for every later import.
    """
    return os.getenv("FS_COOKIE_INSECURE", "") != "1"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


# ── Issuing and clearing ──────────────────────────────────────────────────────

def issue_browser_session(response: Response, token: str, csrf_token: str) -> None:
    """Attach the session pair to `response`.

    `token` must already carry the `csrf` and `ctx` claims — minting is
    `jwt_auth.create_access_token`'s job, so there is exactly one place a token
    is signed.
    """
    secure = cookie_secure()

    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=_SESSION_MAX_AGE_SECONDS,
        httponly=True,          # the whole point: unreadable from script
        secure=secure,
        samesite="lax",
        path="/",
    )
    # Readable by design. Same lifetime, so the page never holds a CSRF token
    # for a session that has already expired.
    response.set_cookie(
        CSRF_COOKIE, csrf_token,
        max_age=_SESSION_MAX_AGE_SECONDS,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_browser_session(response: Response) -> None:
    """Expire both cookies.

    Deletion must repeat path and the security attributes: a cookie is
    identified by name/domain/path, and a delete that omits them can leave the
    original in place while appearing to succeed.
    """
    secure = cookie_secure()
    for name, http_only in ((SESSION_COOKIE, True), (CSRF_COOKIE, False)):
        response.set_cookie(
            name, "",
            max_age=0,
            expires=0,
            httponly=http_only,
            secure=secure,
            samesite="lax",
            path="/",
        )


# ── Reading ───────────────────────────────────────────────────────────────────

def read_session_claims(request: Request) -> dict | None:
    """Decoded claims of a VALID browser session cookie, or None.

    None covers every failure equally — absent, malformed, expired, wrong
    signature, or a token that is not a browser session token — because a
    caller has nothing useful to do with the distinction and reporting it would
    tell an attacker which half of a forgery attempt was wrong.
    """
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None

    # Imported here rather than at module scope: jwt_auth imports db.schema,
    # and this module is imported by the middleware layer that must stay
    # cheap and free of model imports at startup.
    from auth.jwt_auth import decode_token_quietly

    claims = decode_token_quietly(raw)
    if not claims:
        return None

    # A token minted for the API path is not a session token. Refusing it here
    # is what stops CSRF protection from being bypassable by presenting an API
    # token as a cookie.
    if claims.get(CONTEXT_CLAIM) != CONTEXT_BROWSER:
        return None
    if not claims.get(CSRF_CLAIM):
        return None
    return claims


def has_session_cookie(request: Request) -> bool:
    """Whether a session cookie was PRESENTED — not whether it is valid.

    The CSRF gate keys off presentation, not validity: an expired cookie
    carries no authority and must not be able to force a 403 on a request that
    would otherwise be a legitimate anonymous POST.
    """
    return bool(request.cookies.get(SESSION_COOKIE))


# ── CSRF verification ─────────────────────────────────────────────────────────

def _origin_is_same_site(request: Request) -> bool:
    """Defence in depth. Absent Origin and Referer pass.

    A missing `Origin` is normal for a same-origin non-CORS request in some
    clients, so absence cannot be treated as hostile without breaking
    legitimate callers. The token check is what actually carries this gate.
    """
    origin = request.headers.get("origin")
    if origin is None:
        referer = request.headers.get("referer")
        if not referer:
            return True
        origin = referer

    host = request.headers.get("host")
    if not host:
        return True

    # Compare host[:port] only. Scheme is not compared: a TLS-terminating proxy
    # forwards http internally, and comparing it would fail every deployment
    # that has one.
    try:
        without_scheme = origin.split("://", 1)[1]
    except IndexError:
        return False
    origin_host = without_scheme.split("/", 1)[0]
    return origin_host == host


def _is_state_changing_get(request: Request) -> bool:
    """A GET that writes, and therefore needs the same protection as a POST."""
    if request.method != "GET":
        return False
    path = request.url.path
    return any(path.startswith(prefix) for prefix in STATE_CHANGING_GET_PREFIXES)


def csrf_failure_reason(request: Request) -> str | None:
    """None if this request may proceed; a short reason if it must be refused.

    THE GATE IS PRESENTATION-BASED AND FAILS CLOSED. Any unsafe request that
    presents a session cookie must carry a matching CSRF token — including one
    that also carries a Bearer header. That is deliberately stricter than
    necessary: an ambient credential is attached by the browser whether or not
    the caller intended it, and deciding per-request which credential "wins"
    would make the protection depend on resolution order.

    A request with NO session cookie is not CSRF-exposed: a Bearer header is
    not ambient, and an anonymous request has nothing to abuse.
    """
    if request.method not in UNSAFE_METHODS and not _is_state_changing_get(request):
        return None
    if not has_session_cookie(request):
        return None

    claims = read_session_claims(request)
    if claims is None:
        # Presented but unusable. It confers no authority, so the request may
        # proceed to routing, where the auth dependency will refuse it if the
        # route needs a user.
        return None

    if not _origin_is_same_site(request):
        return "cross-origin request rejected"

    sent = request.headers.get(CSRF_HEADER)
    if not sent:
        return "missing CSRF token"

    # secrets.compare_digest: constant-time, so a wrong token cannot be
    # recovered a character at a time from response timing.
    if not secrets.compare_digest(sent, str(claims.get(CSRF_CLAIM, ""))):
        return "invalid CSRF token"

    return None