#!/usr/bin/env python3
"""
test_s8_p1_session_auth.py — Sprint 8 Package 1 · browser session and CSRF.

WHAT THIS SUITE IS FOR. P1 added a second way to present a credential. The
danger in that is not that the new way fails — a broken login is loud — but
that it succeeds too much: that the cookie path skips a check the Bearer path
enforces, or that adding CSRF protection quietly broke the API clients that
were never exposed to CSRF in the first place. Most of what follows is
negative.

DATABASE. A temp SQLite file, created and discarded per run. Nothing here needs
PostgreSQL: no assertion below concerns row locking, isolation or concurrency,
which are the claims `test_support_postgres.py` exists to make honest. The
PostgreSQL-backed protocol suites remain a separate, still-excluded gate.

COOKIES OVER PLAIN HTTP. TestClient speaks http, and a `Secure` cookie is not
returned by a conforming client over http. FS_COOKIE_INSECURE=1 is set for this
process so the round-trip can be exercised at all — and test 3 then asserts the
default is Secure, so the opt-out cannot hide a regression in the thing it
disables.
"""

from __future__ import annotations

import os
import sys
import tempfile

# ── Must precede any import that touches db/schema.py ─────────────────────────
_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 's8p1.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient

from api.main import app
from auth.jwt_auth import create_access_token, hash_password
from auth.session import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    cookie_secure,
)
from db.schema import Base, League, LeagueCommissioner, SessionLocal, Team, User, engine

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


# ── Fixtures ──────────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)

# ledger_entries is created by the ledger's own DDL rather than by the model
# metadata, and the account-summary route reads it. Creating it keeps section 9
# testing AUTHORIZATION rather than accidentally testing schema bootstrap.
from ledger.ledger import create_ledger_table  # noqa: E402

create_ledger_table()

GM_EMAIL = "gm@example.test"
COMM_EMAIL = "commissioner@example.test"
PASSWORD = "sprint8-password"

with SessionLocal() as db:
    league = League(name="Certification League", season=2026)
    db.add(league)
    db.flush()
    LEAGUE_ID = league.id

    gm_team = Team(team_name="Gravy Train", owner="A. Gm",
                   email=GM_EMAIL, league_id=LEAGUE_ID)
    comm_team = Team(team_name="The Braintrust", owner="A. Commissioner",
                     email=COMM_EMAIL, league_id=LEAGUE_ID)
    db.add_all([gm_team, comm_team])
    db.flush()

    hashed = hash_password(PASSWORD)
    gm_user = User(email=GM_EMAIL, hashed_password=hashed,
                   team_id=gm_team.id, role="gm")
    comm_user = User(email=COMM_EMAIL, hashed_password=hashed,
                     team_id=comm_team.id, role="commissioner")
    db.add_all([gm_user, comm_user])
    db.flush()

    GM_USER_ID = gm_user.id
    COMM_USER_ID = comm_user.id
    GM_TEAM_ID = gm_team.id

    # `bootstrap` is the genesis source — authority that pre-dates any granting
    # user, which is what a fixture is.
    db.add(LeagueCommissioner(league_id=LEAGUE_ID, user_id=COMM_USER_ID,
                              source="bootstrap"))
    db.commit()


def _client() -> TestClient:
    """A fresh client — and therefore a fresh, empty cookie jar."""
    return TestClient(app)


def _sign_in(client: TestClient, email: str = GM_EMAIL) -> dict:
    response = client.post("/auth/session", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


print("=" * 60)
print("S8-P1 — browser session, CSRF and Bearer compatibility")
print("=" * 60)


# ── 1 · Browser login issues a cookie session and no readable token ──────────

_section("1 · Browser login puts the token in a cookie and nowhere else")

client = _client()
response = client.post("/auth/session", json={"email": GM_EMAIL, "password": PASSWORD})

_assert("POST /auth/session signs a GM in", response.status_code == 200,
        f"status {response.status_code}")

body = response.json()
_assert("the response body carries identity", body.get("email") == GM_EMAIL)
_assert("the response body carries NO token",
        "access_token" not in body and "token" not in body,
        f"keys: {sorted(body)}")

_assert("a session cookie is set", SESSION_COOKIE in client.cookies)
_assert("a CSRF cookie is set", CSRF_COOKIE in client.cookies)

session_directive = next(
    (c for c in response.headers.get_list("set-cookie") if c.startswith(SESSION_COOKIE)), "")
csrf_directive = next(
    (c for c in response.headers.get_list("set-cookie") if c.startswith(CSRF_COOKIE)), "")

_assert("the session cookie is HttpOnly", "httponly" in session_directive.lower(),
        session_directive[:90])
_assert("the session cookie is SameSite=Lax", "samesite=lax" in session_directive.lower())
_assert("the session cookie is path-scoped to the app", "path=/" in session_directive.lower())
_assert("the CSRF cookie is deliberately NOT HttpOnly — the page must echo it",
        "httponly" not in csrf_directive.lower(), csrf_directive[:90])

# The session token must never be derivable from anything the page can read.
csrf_value = client.cookies.get(CSRF_COOKIE)
session_value = client.cookies.get(SESSION_COOKIE)
_assert("the CSRF cookie is not the session token",
        csrf_value != session_value and csrf_value not in session_value)


# ── 2 · The session authenticates, and /auth/me answers for it ───────────────

_section("2 · /auth/me is the authoritative identity and capability read")

me = client.get("/auth/me")
_assert("a cookie session authenticates /auth/me", me.status_code == 200,
        f"status {me.status_code}")

identity = me.json()
_assert("it names the acting GM", identity.get("email") == GM_EMAIL)
_assert("it carries a capabilities object", isinstance(identity.get("capabilities"), dict))

caps = identity.get("capabilities", {})
_assert("a GM is not reported as a commissioner", caps.get("is_commissioner") is False)
_assert("a GM holds no league commissioner authority",
        caps.get("commissioner_league_ids") == [], str(caps.get("commissioner_league_ids")))
_assert("the GM's team binding is reported", caps.get("has_team") is True)

comm_client = _client()
comm_identity = _sign_in(comm_client, COMM_EMAIL)
comm_caps = comm_identity.get("capabilities", {})
_assert("a commissioner is reported as one", comm_caps.get("is_commissioner") is True)
_assert("and their league authority is enumerated from LeagueCommissioner rows",
        comm_caps.get("commissioner_league_ids") == [LEAGUE_ID],
        str(comm_caps.get("commissioner_league_ids")))

anon = _client()
_assert("an unauthenticated /auth/me is refused",
        anon.get("/auth/me").status_code == 401)


# ── 3 · Secure is the default; the opt-out is explicit and narrow ────────────

_section("3 · Secure is the default and the local opt-out is explicit")

_assert("this suite is running with the local opt-out on",
        cookie_secure() is False, "FS_COOKIE_INSECURE=1 not honoured")

os.environ.pop("FS_COOKIE_INSECURE")
_assert("without the opt-out, cookies are Secure", cookie_secure() is True)

# A near-miss value must NOT disable Secure. An operator who wrote
# FS_COOKIE_INSECURE=true meaning "insecure" gets a secure cookie, which is the
# safe way to be wrong.
leaked: list[str] = []
for candidate in ("0", "true", "yes", "TRUE", ""):
    os.environ["FS_COOKIE_INSECURE"] = candidate
    if cookie_secure() is not True:
        leaked.append(candidate)

_assert("only the exact value '1' disables Secure — nothing truthy-looking does",
        leaked == [], f"also disabled by: {leaked}")

os.environ["FS_COOKIE_INSECURE"] = "1"


# ── 4 · CSRF: the cookie session cannot mutate without a matching token ──────

_section("4 · CSRF — a cookie session cannot mutate without a matching token")

# /auth/promote is a real commissioner mutation, so this exercises the gate on
# a route that actually changes state rather than on a purpose-built one.
promote_body = {"email": GM_EMAIL, "role": "gm"}

no_token = comm_client.post("/auth/promote", json=promote_body)
_assert("an unsafe cookie request with NO CSRF header is refused",
        no_token.status_code == 403, f"status {no_token.status_code}")
_assert("and it says why", "CSRF" in no_token.json().get("detail", ""),
        no_token.text[:120])

bad_token = comm_client.post("/auth/promote", json=promote_body,
                             headers={CSRF_HEADER: "not-the-right-token"})
_assert("an unsafe cookie request with a WRONG CSRF token is refused",
        bad_token.status_code == 403, f"status {bad_token.status_code}")

good = comm_client.post(
    "/auth/promote", json=promote_body,
    headers={CSRF_HEADER: comm_client.cookies.get(CSRF_COOKIE)},
)
_assert("the same request WITH the matching token succeeds",
        good.status_code == 200, f"status {good.status_code} {good.text[:120]}")

# The forged-cookie case: plain double-submit would accept this, because the
# attacker controls both halves. The token is bound to the signed JWT, so it
# does not.
forger = _client()
_sign_in(forger, COMM_EMAIL)
forger.cookies.set(CSRF_COOKIE, "attacker-chosen-value")
forged = forger.post("/auth/promote", json=promote_body,
                     headers={CSRF_HEADER: "attacker-chosen-value"})
_assert("a self-consistent FORGED CSRF cookie+header pair is still refused",
        forged.status_code == 403, f"status {forged.status_code}")

# A safe method never needs a token.
_assert("GET needs no CSRF token", comm_client.get("/auth/me").status_code == 200)

# REVISED BY S8-P2. P1 asserted that the state-changing `GET /settle/{week}`
# was pulled into the CSRF gate by an explicit exception, because P1 could
# protect the browser but had no business changing a public verb. P2 fixed the
# contract: the route is POST, the exception list is empty, and the assertion
# that belongs here now is that the mutating GET is GONE. Its CSRF behaviour
# under the correct verb is certified in test_s8_p2_authorization.py.
from auth.session import STATE_CHANGING_GET_PREFIXES  # noqa: E402

_assert("the P1 state-changing-GET exception list is empty",
        STATE_CHANGING_GET_PREFIXES == (), str(STATE_CHANGING_GET_PREFIXES))
_assert("the mutating GET no longer exists",
        comm_client.get("/settle/5").status_code == 405,
        f"status {comm_client.get('/settle/5').status_code}")


# ── 5 · An API token cannot be planted as a session to skip CSRF ─────────────

_section("5 · An API Bearer token planted in the cookie is not a session")

with SessionLocal() as db:
    comm_row = db.query(User).filter(User.id == COMM_USER_ID).first()
    api_token = create_access_token(comm_row)          # no csrf claim, no ctx

planted = _client()
planted.cookies.set(SESSION_COOKIE, api_token)

planted_me = planted.get("/auth/me")
_assert("an API token in the session cookie does not authenticate",
        planted_me.status_code == 401, f"status {planted_me.status_code}")

planted_write = planted.post("/auth/promote", json=promote_body)
_assert("and it cannot be used to mutate without a CSRF token",
        planted_write.status_code in (401, 403),
        f"status {planted_write.status_code}")


# ── 6 · Bearer API authentication is unchanged ───────────────────────────────

_section("6 · Bearer API authentication still works, and needs no CSRF token")

api = _client()
form = api.post("/auth/login", data={"username": COMM_EMAIL, "password": PASSWORD})
_assert("POST /auth/login still returns a Bearer token", form.status_code == 200,
        f"status {form.status_code}")

token = form.json().get("access_token")
_assert("the token is in the body, as an API client needs", bool(token))

auth_header = {"Authorization": f"Bearer {token}"}

# A fresh client, so no cookie exists to confuse the question.
bearer = _client()
bearer_me = bearer.get("/auth/me", headers=auth_header)
_assert("a Bearer token authenticates /auth/me", bearer_me.status_code == 200,
        f"status {bearer_me.status_code}")
_assert("and resolves the same identity the cookie path would",
        bearer_me.json().get("email") == COMM_EMAIL)

bearer_write = bearer.post("/auth/promote", json=promote_body, headers=auth_header)
_assert("a Bearer mutation needs NO CSRF token — it is not an ambient credential",
        bearer_write.status_code == 200, f"status {bearer_write.status_code}")

_assert("an invalid Bearer token is refused",
        _client().get("/auth/me", headers={"Authorization": "Bearer not.a.token"})
        .status_code == 401)

# REVISED BY S8-P2, for the same reason as section 4: the mutating GET is gone,
# so the claim worth making here is that a Bearer caller still needs no CSRF
# token on the route's correct verb.
_assert("a Bearer caller reaches the settlement POST with no CSRF token",
        _client().post("/settle/5", headers=auth_header).status_code != 403)


# ── 7 · Cross-origin is refused for a cookie mutation ────────────────────────

_section("7 · Origin is checked as defence in depth")

evil = comm_client.post(
    "/auth/promote", json=promote_body,
    headers={CSRF_HEADER: comm_client.cookies.get(CSRF_COOKIE),
             "Origin": "https://evil.example"},
)
_assert("a cross-origin unsafe cookie request is refused even with a valid token",
        evil.status_code == 403, f"status {evil.status_code}")

same_origin = comm_client.post(
    "/auth/promote", json=promote_body,
    headers={CSRF_HEADER: comm_client.cookies.get(CSRF_COOKIE),
             "Origin": "http://testserver"},
)
_assert("the matching same-origin request is allowed",
        same_origin.status_code == 200, f"status {same_origin.status_code}")


# ── 8 · Logout ───────────────────────────────────────────────────────────────

_section("8 · Logout clears the browser's possession of the credential")

out = comm_client.delete(
    "/auth/session",
    headers={CSRF_HEADER: comm_client.cookies.get(CSRF_COOKIE)},
)
_assert("DELETE /auth/session succeeds", out.status_code == 204,
        f"status {out.status_code}")

_assert("the session cookie is cleared",
        not comm_client.cookies.get(SESSION_COOKIE),
        repr(comm_client.cookies.get(SESSION_COOKIE)))
_assert("the CSRF cookie is cleared too",
        not comm_client.cookies.get(CSRF_COOKIE),
        repr(comm_client.cookies.get(CSRF_COOKIE)))
_assert("and the session no longer authenticates",
        comm_client.get("/auth/me").status_code == 401)

_assert("logout itself requires authentication",
        _client().delete("/auth/session").status_code == 401)

logout_no_csrf = _client()
_sign_in(logout_no_csrf, GM_EMAIL)
_assert("logout is CSRF-protected — a cross-site page cannot sign a GM out",
        logout_no_csrf.delete("/auth/session").status_code == 403)


# ── 9 · Authorization is unchanged by the new credential ─────────────────────

_section("9 · The cookie presents authority; it never grants any")

gm = _client()
_sign_in(gm, GM_EMAIL)
gm_csrf = {CSRF_HEADER: gm.cookies.get(CSRF_COOKIE)}

_assert("a GM on a cookie session is refused a commissioner route",
        gm.post("/auth/promote", json=promote_body, headers=gm_csrf).status_code == 403)

own = gm.get(f"/account/{GM_TEAM_ID}/summary")
_assert("a GM may read their own account on a cookie session",
        own.status_code == 200, f"status {own.status_code} {own.text[:120]}")

# The claim is about the AUTHORIZATION outcome, so it is stated as "not 403"
# rather than as a specific success code: whether the other team happens to
# hold a FAAB wallet is not what this asserts.
other_team = GM_TEAM_ID + 1
other = gm.get(f"/faab/transactions/{other_team}")
_assert("a GM on a cookie session cannot read another team's FAAB transactions",
        other.status_code == 403, f"status {other.status_code}")

mine = gm.get(f"/faab/transactions/{GM_TEAM_ID}")
_assert("but the same route is not refused for their own team",
        mine.status_code != 403, f"status {mine.status_code}")


# ── 10 · CORS is no longer permissive ────────────────────────────────────────

_section("10 · CORS no longer advertises the API to every origin")

import api.main as main_module

_assert("the wildcard origin is gone", "*" not in main_module._ALLOWED_ORIGINS,
        str(main_module._ALLOWED_ORIGINS))
_assert("the default is no cross-origin browser access at all",
        main_module._ALLOWED_ORIGINS == [], str(main_module._ALLOWED_ORIGINS))

preflight = _client().options(
    "/auth/me",
    headers={"Origin": "https://evil.example",
             "Access-Control-Request-Method": "GET"},
)
_assert("a cross-origin preflight is not granted an allow-origin header",
        "access-control-allow-origin" not in {k.lower() for k in preflight.headers},
        str(dict(preflight.headers)))


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P1 SESSION AUTH — all assertions PASSED")