#!/usr/bin/env python3
"""SPRINT C1 — the self-service Yahoo connection surface, driven.

    python test_c1_provider_connection.py
    DATABASE_URL=postgresql://…/fs_c1_conn_test python test_c1_provider_connection.py

WHAT THIS CERTIFIES. `auth.provider_grant.disconnect` was implemented, certified
and completely unreachable before C1 — no route, no control. A product that asks
for access to somebody's Yahoo account and offers no way to withdraw it should
not ship, so C1 wired `POST /provider/disconnect` and `GET /provider/connection`.

THE THREE CLAIMS THAT MATTER, and each is driven rather than read:

  1. a user can disconnect their OWN grant, and the bearer material is gone
  2. a user CANNOT disconnect anybody else's — the route takes no user id
  3. disconnecting destroys no economic record: not a wager, not a ledger row,
     not a wallet, not league membership

Claim 3 is the one worth being adversarial about. A disconnect that quietly
cascaded into settled economics would be catastrophic and completely invisible
in a status field, so this suite posts a real ledger entry, disconnects, and
asserts trial balance and every economic row are untouched.

NO NETWORK. No Yahoo endpoint is contacted; grants are sealed locally with a
test key.
"""
from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="c1-conn-")
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = (
        "sqlite:///" + os.path.join(_TMP, "conn.db").replace(os.sep, "/"))
os.environ.setdefault("JWT_SECRET_KEY", "c1-provider-connection-suite")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth.token_crypto import generate_key  # noqa: E402

os.environ.setdefault("FS_TOKEN_ENCRYPTION_KEY", generate_key())

FAIL: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


def section(title: str) -> None:
    print(f"\n{title}")


from fastapi.testclient import TestClient  # noqa: E402

import api.main_rc2 as entry  # noqa: E402

with TestClient(entry.app):
    pass

from sqlalchemy import text  # noqa: E402

from auth.provider_grant import (  # noqa: E402
    PROVIDER_YAHOO, grant_for, record_grant, snapshot,
)
from db.schema import League, SessionLocal, Team, User, Wallet, engine  # noqa: E402
from ledger.ledger import balance_of, create_ledger_table, post, trial_balance  # noqa: E402

create_ledger_table()

print("=" * 74)
print(f"C1 — PROVIDER CONNECTION SURFACE  ({engine.dialect.name})")
print("=" * 74)


# ── fixture: two users, each with their own grant ────────────────────────────

def make_user(email: str) -> int:
    with SessionLocal() as db:
        user = User(email=email, hashed_password="x", role="gm",
                    auth_provider="yahoo", provider_subject=f"sub-{email}")
        db.add(user)
        db.commit()
        return int(user.id)


TOKENS = {"access_token": "at-secret-value", "refresh_token": "rt-secret-value",
          "expires_in": 3600}

MINE = make_user("c1-mine@cert.test")
THEIRS = make_user("c1-theirs@cert.test")

with SessionLocal() as db:
    record_grant(db, user_id=MINE, provider_subject="sub-mine", tokens=TOKENS)
    record_grant(db, user_id=THEIRS, provider_subject="sub-theirs", tokens=TOKENS)
    db.commit()


def auth_client(user_id: int) -> TestClient:
    """A client carrying a real session for one user."""
    from auth.jwt_auth import create_access_token
    from auth.session import (
        CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, new_csrf_token,
    )

    csrf = new_csrf_token()
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        token = create_access_token(user, csrf=csrf)

    client = TestClient(entry.app)
    client.cookies.set(SESSION_COOKIE, token)
    # THE DOUBLE-SUBMIT HALF. A state-changing request needs the CSRF value in
    # BOTH the readable cookie and the header, matching the `csrf` claim sealed
    # inside the session JWT. The first draft of this suite sent neither and the
    # disconnect answered 403 — the protection working, not a defect.
    client.cookies.set(CSRF_COOKIE, csrf)
    client.headers.update({CSRF_HEADER: csrf})
    return client


# ── 1 · the connection read ──────────────────────────────────────────────────

section("1 · An account can see whether it holds a Yahoo authorization")

mine = auth_client(MINE)
r = mine.get("/provider/connection")
check("GET /provider/connection answers", r.status_code == 200, str(r.status_code))
body = r.json() if r.status_code == 200 else {}
check("  · it reports a grant on file", body.get("had_grant") is True, str(body))
check("  · and reports it connected", body.get("connected") is True, str(body))
check("  · it carries NO token material",
      not any(k in str(body) for k in ("at-secret-value", "rt-secret-value",
                                       "sealed", "token")),
      str(body))

check("the route requires a session",
      TestClient(entry.app).get("/provider/connection").status_code in (401, 403),
      str(TestClient(entry.app).get("/provider/connection").status_code))


# ── 2 · economics recorded BEFORE the disconnect ─────────────────────────────

section("2 · A real economic record exists before we touch anything")

with SessionLocal() as db:
    league = League(season=2032, name="C1 Conn", projection_source="fantasypros",
                    start_week=1, playoff_start_week=15, season_final_week=17)
    db.add(league)
    db.flush()
    team = Team(league_id=league.id, team_name="C1", owner="o",
                email="c1-team@cert.test")
    db.add(team)
    db.flush()
    db.add(Wallet(team_id=team.id, balance=0.0))
    db.commit()
    LEAGUE_ID, TEAM_ID = int(league.id), int(team.id)

# THE GOVERNED ISSUANCE DOOR AND ITS EXEMPT ACCOUNT PREFIX. An ordinary account
# may not be debited below zero; issuance is the certified exception, and the
# door and prefix must match one row of `_ISSUANCE_EXEMPTIONS` or the posting is
# refused — which is the ledger behaving exactly as it should.
from ledger.ledger import SEASON_ALLOCATION_DOOR  # noqa: E402

post(entries=[(f"wallet:{TEAM_ID}", 5000),
              (f"season_issuance:{LEAGUE_ID}", -5000)],
     door=SEASON_ALLOCATION_DOOR)

BEFORE = {
    "trial_balance": trial_balance(),
    "wallet": balance_of(f"wallet:{TEAM_ID}"),
}
with SessionLocal() as db:
    BEFORE["ledger_rows"] = db.execute(
        text("SELECT count(*) FROM ledger_entries")).scalar()
    BEFORE["teams"] = db.query(Team).count()
    BEFORE["wallets"] = db.query(Wallet).count()
    BEFORE["leagues"] = db.query(League).count()

check("the fixture posted real Credits", BEFORE["wallet"] == 5000,
      str(BEFORE["wallet"]))
check("the ledger balances", BEFORE["trial_balance"] == 0,
      str(BEFORE["trial_balance"]))


# ── 3 · disconnecting your own grant ─────────────────────────────────────────

section("3 · A user can disconnect their own authorization")

r = mine.post("/provider/disconnect")
check("POST /provider/disconnect succeeds", r.status_code == 200, str(r.status_code))
out = r.json() if r.status_code == 200 else {}
check("  · it reports not connected", out.get("connected") is False, str(out))
check("  · it reports a grant HAD existed", out.get("had_grant") is True)
check("  · and says plainly that revocation at Yahoo is a separate act",
      "Yahoo account" in str(out.get("detail", "")), str(out.get("detail"))[:110])
check("  · the response carries no token material",
      "at-secret-value" not in str(out) and "rt-secret-value" not in str(out))

with SessionLocal() as db:
    grant = grant_for(db, user_id=MINE, provider=PROVIDER_YAHOO)
    check("the sealed access token is destroyed", grant.access_token_sealed is None)
    check("the sealed refresh token is destroyed", grant.refresh_token_sealed is None)
    check("the grant is marked disconnected", grant.status == "disconnected",
          str(grant.status))
    check("  · and its token version advanced, so a stale copy is not reusable",
          int(grant.token_version or 0) >= 1, str(grant.token_version))

check("a second disconnect is idempotent, not an error",
      mine.post("/provider/disconnect").status_code == 200)


# ── 4 · you cannot disconnect anybody else ───────────────────────────────────

section("4 · One account cannot revoke another's authorization")

with SessionLocal() as db:
    other = grant_for(db, user_id=THEIRS, provider=PROVIDER_YAHOO)
    check("the other user's grant is untouched",
          other.access_token_sealed is not None
          and other.refresh_token_sealed is not None
          and other.status == "active",
          str(other.status))

# THE ROUTE TAKES NO USER ID. That is the mechanism, so it is asserted directly:
# there is no parameter through which another account could be named.
import inspect as _inspect  # noqa: E402

sig = _inspect.signature(entry.app.__dict__ and
                         [r.endpoint for r in entry.app.routes
                          if getattr(r, "path", "") == "/provider/disconnect"][0])
check("the disconnect endpoint accepts no user identifier",
      not any(p in sig.parameters for p in ("user_id", "target_user_id",
                                            "league_id", "subject")),
      str(list(sig.parameters)))

# And the other account can still use its own connection.
theirs = auth_client(THEIRS)
r = theirs.get("/provider/connection")
check("the other account still reports connected",
      r.status_code == 200 and r.json().get("connected") is True,
      str(r.json() if r.status_code == 200 else r.status_code))


# ── 5 · nothing economic moved ───────────────────────────────────────────────

section("5 · Disconnecting destroys no economic record")

AFTER = {
    "trial_balance": trial_balance(),
    "wallet": balance_of(f"wallet:{TEAM_ID}"),
}
with SessionLocal() as db:
    AFTER["ledger_rows"] = db.execute(
        text("SELECT count(*) FROM ledger_entries")).scalar()
    AFTER["teams"] = db.query(Team).count()
    AFTER["wallets"] = db.query(Wallet).count()
    AFTER["leagues"] = db.query(League).count()

for key in ("trial_balance", "wallet", "ledger_rows", "teams", "wallets",
            "leagues"):
    check(f"  {key} unchanged", BEFORE[key] == AFTER[key],
          f"{BEFORE[key]} -> {AFTER[key]}")

check("the wallet still holds its Credits", AFTER["wallet"] == 5000)
check("the ledger still balances", AFTER["trial_balance"] == 0)

# League membership and the credential OWNER assignment are different things;
# a self-service disconnect must not silently unassign a league.
with SessionLocal() as db:
    still = db.query(League).filter(League.id == LEAGUE_ID).first()
    check("league membership and identity survive a disconnect",
          still is not None and still.name == "C1 Conn")


# ── 6 · OAuth callback failure paths ─────────────────────────────────────────

section("6 · The callback fails closed on every hostile or broken input")

# NO NETWORK IS REACHED IN ANY OF THESE. Each is refused before a code would be
# exchanged, which is the property being asserted: a forged or cancelled
# callback must cost nothing — no token exchange, no identity lookup, no write.

anon = TestClient(entry.app, follow_redirects=False)

CASES = (
    ("the user denied consent",
     "/auth/yahoo/callback?error=access_denied", "cancelled"),
    ("a callback with no transaction cookie",
     "/auth/yahoo/callback?code=x&state=y", "sign_in_expired"),
    ("a callback with neither code nor state",
     "/auth/yahoo/callback", "sign_in_expired"),
)
for label, url, expected in CASES:
    r = anon.get(url)
    check(f"{label} redirects rather than erroring",
          r.status_code in (302, 303, 307), str(r.status_code))
    location = r.headers.get("location", "")
    check(f"  · and reports {expected!r}", f"auth={expected}" in location,
          location[:110])
    check("  · carrying no code, token or subject in the URL",
          not any(k in location for k in ("code=", "token", "id_token",
                                          "subject", "access")),
          location[:110])

# WITH YAHOO UNCONFIGURED the callback refuses at the configuration guard,
# which is also closed and also exchanges nothing.
_unconf = anon.get("/auth/yahoo/callback?code=x&state=y")
check("an unconfigured deployment refuses the callback rather than erroring",
      _unconf.status_code in (302, 303, 307)
      and "auth=" in _unconf.headers.get("location", ""),
      _unconf.headers.get("location", "")[:110])

# A FORGED STATE, WITH A REAL TRANSACTION COOKIE. This is the attack the state
# check exists for: the cookie is genuine, the state in the query is not.
from auth.jwt_auth import SECRET_KEY  # noqa: E402
from auth.yahoo_oidc import new_transaction, seal_transaction  # noqa: E402

# CONFIGURE YAHOO FIRST, so the STATE CHECK is the guard actually exercised.
# With Yahoo unconfigured the callback fails earlier, at `load_config`, and
# answers `sign_in_unavailable` — still closed, still no exchange, but it proves
# the config guard rather than the state guard. Production has Yahoo configured,
# so the state check is the one that runs there, and it is the one worth
# asserting.
os.environ["FS_YAHOO_CLIENT_ID"] = "c1-test-client-id"
os.environ["FS_YAHOO_CLIENT_SECRET"] = "c1-test-client-secret"
os.environ["FS_YAHOO_REDIRECT_URI"] = "https://example.test/auth/yahoo/callback"

txn = new_transaction()
forged = TestClient(entry.app, follow_redirects=False)
forged.cookies.set("fs_yahoo_txn", seal_transaction(txn, secret=SECRET_KEY),
                   path="/auth")
r = forged.get("/auth/yahoo/callback?code=stolen-code&state=not-the-state")
check("a forged state is refused even with a valid transaction cookie",
      "auth=state_invalid" in r.headers.get("location", ""),
      r.headers.get("location", "")[:110])
check("  · and the stolen code never appears in the redirect",
      "stolen-code" not in r.headers.get("location", ""))

# NO GRANT WAS CREATED BY ANY OF THE ABOVE.
with SessionLocal() as db:
    total = db.execute(text("SELECT count(*) FROM provider_grants")).scalar()
check("no failed callback created a provider grant", total == 2, str(total))


print("\n" + "=" * 74)
if FAIL:
    print(f"C1 PROVIDER CONNECTION — {len(FAIL)} FAILED")
    for f in FAIL:
        print(f"  · {f}")
    sys.exit(1)
print(f"PASS: provider connection surface certified on {engine.dialect.name}")
