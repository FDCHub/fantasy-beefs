"""
JWT authentication for Fantasy Beefs.

TWO WAYS TO PRESENT A CREDENTIAL, ONE PLACE THAT RESOLVES IT (S8-P1).

  API client   POST /auth/login    → JWT in the response body
                                   → Authorization: Bearer <token>
  Browser      POST /auth/session  → JWT in a Secure HttpOnly cookie
                                   → cookie attached automatically; the page
                                     never sees the token

Both arrive at the SAME get_current_user(), so every downstream guard —
require_commissioner, assert_own_team, assert_own_wallet — is enforced
identically whichever credential was used. Adding the cookie added a way to
PRESENT authority, not a way to hold it.

Bearer takes precedence when both are present, because an Authorization header
is always deliberate while a cookie is ambient. Note that precedence does not
weaken CSRF: auth/session.py refuses any unsafe request that merely PRESENTS a
session cookie without a matching token, whatever else it carries.

Cookie custody, cookie attributes and the CSRF token live in auth/session.py.

Flow
  1. verify bcrypt password → sign HS256 JWT
                          claims: sub (user_id), team_id, role, exp
                          browser sessions additionally carry csrf and ctx
  2. get_current_user() dependency decodes + validates → User row
  3. require_commissioner() wraps get_current_user and enforces role

User ↔ Team coupling
  • One User per team (team_id unique).
  • Registration: email must match an existing team.email (or leave unlinked).
  • Commissioner: team_id=1 owner by default; promotable via /auth/promote.

Secret key
  • Set JWT_SECRET_KEY env-var in production. Falls back to dev-only default.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Team, User
from db.deps import get_db

# ── Config ────────────────────────────────────────────────────────────────────

SECRET_KEY          = os.getenv("JWT_SECRET_KEY", "fantasy-beefs-dev-secret-CHANGE-IN-PROD")
ALGORITHM           = "HS256"
TOKEN_EXPIRE_HOURS  = 8
SEED_PASSWORD       = "beefs2024"   # printed at seed time; change before real deployment

pwd_context   = CryptContext(schemes=["bcrypt"], deprecated="auto")

# auto_error=False so an absent Authorization header falls through to the
# cookie path instead of 401-ing inside the security scheme. The scheme stays
# registered, so /docs still offers the Bearer flow. Absence is no longer an
# error here; it is an error only once BOTH credentials have been tried.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── Token helpers ─────────────────────────────────────────────────────────────

def create_access_token(user: User, *, csrf: str | None = None) -> str:
    """Sign a token for `user`.

    Passing `csrf` mints a BROWSER SESSION token: it carries the CSRF token as
    a claim and marks its context, which is what lets auth/session.py tell a
    session cookie apart from an API token that has been planted in one. Every
    token in the system is signed here, so there is one place to audit what a
    credential can claim.
    """
    payload = {
        "sub":     str(user.id),
        "email":   user.email,
        "team_id": user.team_id,
        "role":    user.role,
        "exp":     datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    if csrf is not None:
        from auth.session import CONTEXT_BROWSER, CONTEXT_CLAIM, CSRF_CLAIM
        payload[CSRF_CLAIM] = csrf
        payload[CONTEXT_CLAIM] = CONTEXT_BROWSER
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token_quietly(token: str) -> dict | None:
    """Claims, or None for any invalid token.

    The non-raising twin of `_decode_token`, for callers that must inspect a
    credential without committing to refusing the request — the CSRF gate needs
    to read a cookie's claims while leaving the 401 decision to the route's own
    dependency.
    """
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def _decode_token(token: str) -> dict:
    claims = decode_token_quietly(token)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


# ── FastAPI dependencies ──────────────────────────────────────────────────────

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    request: Request,
    token:   str | None = Depends(oauth2_scheme),
    db:      Session = Depends(get_db),
) -> User:
    """Resolve the acting user from either supported credential.

    Bearer first — an Authorization header is deliberate, a cookie is ambient.
    A cookie is accepted only if `read_session_claims` vouches for it, which
    means it must be a genuine browser-session token rather than any valid JWT
    that happens to be sitting in the cookie jar.
    """
    from auth.session import read_session_claims

    payload: dict | None = None
    if token:
        payload = _decode_token(token)      # raises 401 on a bad Bearer token
    else:
        payload = read_session_claims(request)

    if payload is None:
        raise _UNAUTHENTICATED

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed token")

    user = db.query(User).filter(User.id == user_id, User.is_active == 1).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def get_current_gm(user: User = Depends(get_current_user)) -> User:
    """Any authenticated user (GM or commissioner)."""
    return user


def require_commissioner(user: User = Depends(get_current_user)) -> User:
    if user.role != "commissioner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Commissioner access required",
        )
    return user


# ── Team ownership guard ──────────────────────────────────────────────────────

def assert_own_team(team_id: int, current_user: User) -> None:
    """Raise 403 unless current_user owns team_id or is commissioner.

    ADMINISTRATIVE AUTHORITY, AND ONLY THAT. The commissioner exemption here is
    deliberate and is still relied on by oversight surfaces that READ a team's
    records. It must never be used to authorize spending a team's Credits — see
    `assert_wagering_team_owner`, which is the guard for that and takes no role
    into account at all.
    """
    if current_user.role != "commissioner" and current_user.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: team {team_id} is not yours",
        )


def assert_wagering_team_owner(team_id: int, current_user: User,
                               action: str = "wager with its Credits") -> None:
    """Raise 403 unless current_user IS the GM of team_id. No role exemption.

    `action` names what is being refused, for the message only — it never
    affects the decision. S8-P4C-4 added it because Pool picks reuse this guard
    and move no Credits: telling a GM they may not "wager with its Credits"
    when they tried to submit a pick describes the wrong act, and a refusal a
    GM cannot map onto what they did is a bad refusal even when it is correct.

    WAGERING IDENTITY IS OWNERSHIP, NOT RANK. A wager commits a specific team's
    Credits, so the only person who may act for that team is the GM whose money
    it is. `assert_own_team` cannot serve here: its commissioner exemption was
    written for administrative reads, and under the funded lifecycle it would
    let a commissioner move another GM's real money into escrow.

    THE DEFECT THIS CLOSES was latent before S8-P4C-1 and became live with it.
    On the legacy path a commissioner issuing "as" another GM created an
    unfunded row that reserved nothing; once issuance posts real escrow, the
    same call debits that GM's wallet. The authorization rule did not change —
    what changed was the cost of it being wrong.

    A COMMISSIONER IS NOT DISADVANTAGED. They wager for their own team on
    exactly these terms, because they are that team's GM. What they lose is only
    the ability to wager as someone else, which was never an administrative
    capability.

    Cross-league authority needs no separate test: a GM owns one team, so a team
    in another league can never satisfy this equality.
    """
    if current_user.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: only team {team_id}'s own GM may {action}",
        )


def assert_own_wallet(wallet_id: int, current_user: User, db: Session) -> None:
    """Raise 403 unless wallet belongs to current_user's team or user is commissioner."""
    from db.schema import Wallet
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Wallet not found")
    if current_user.role != "commissioner" and wallet.team_id != current_user.team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: not your wallet",
        )


# ── Business logic ────────────────────────────────────────────────────────────

def register_user(email: str, password: str, db: Session) -> User:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if db.query(User).filter(User.email == email).first():
        raise ValueError("Email already registered")

    team = db.query(Team).filter(Team.email == email).first()
    user = User(
        email           = email,
        hashed_password = hash_password(password),
        team_id         = team.id if team else None,
        role            = "gm",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(email: str, password: str, db: Session) -> User:
    user = db.query(User).filter(User.email == email, User.is_active == 1).first()
    # WP3D.1 — AN ACCOUNT WITH NO PASSWORD HAS NO PASSWORD LOGIN.
    #
    # A Yahoo-created account carries `hashed_password = NULL`, and passing that
    # to `verify_password` would raise inside passlib rather than refuse
    # cleanly. Absence of a hash is not a match and is not an error the caller
    # should have to distinguish: it is the same 401 as a wrong password, so the
    # form cannot be used to discover which accounts authenticate through Yahoo.
    if not user or not user.hashed_password             or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return user


def promote_user(target_email: str, new_role: str, db: Session) -> User:
    if new_role not in ("gm", "commissioner"):
        raise ValueError(f"Invalid role: {new_role!r}")
    user = db.query(User).filter(User.email == target_email).first()
    if not user:
        raise ValueError(f"No user found for {target_email}")
    user.role = new_role
    db.commit()
    db.refresh(user)
    return user


def seed_users(db: Session) -> list[User]:
    """
    Create one User per team.  Team-1 owner becomes commissioner.
    Password for all accounts: SEED_PASSWORD (printed to stdout).
    Safe to call on an already-seeded DB — skips existing emails.
    """
    teams = db.query(Team).order_by(Team.id).all()
    if not teams:
        raise RuntimeError("seed_users: no teams found — run seed_from_mock first")

    hashed = hash_password(SEED_PASSWORD)
    created: list[User] = []

    for i, team in enumerate(teams):
        if db.query(User).filter(User.email == team.email).first():
            continue
        role = "commissioner" if i == 0 else "gm"
        user = User(
            email           = team.email,
            hashed_password = hashed,
            team_id         = team.id,
            role            = role,
        )
        db.add(user)
        created.append(user)

    db.commit()
    return created


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    from db.schema import SessionLocal, create_all

    create_all()   # ensure users table exists (additive)

    with SessionLocal() as db:
        existing = db.query(User).count()
        if existing == 0:
            print("No users found — seeding from teams...")
            users = seed_users(db)
            print(f"Created {len(users)} users  (password: '{SEED_PASSWORD}')\n")
        else:
            print(f"Found {existing} existing users.\n")

        # ── Show all users ────────────────────────────────────────────────────
        all_users = db.query(User).order_by(User.id).all()
        print("┌────┬──────────────────────────────────┬───────────────┬──────────┬──────────┐")
        print("│ ID │ Email                            │ Team          │ Role     │ Active   │")
        print("├────┼──────────────────────────────────┼───────────────┼──────────┼──────────┤")
        for u in all_users:
            tname = u.team.team_name if u.team else "(no team)"
            print(f"│ {u.id:<2} │ {u.email:<32} │ {tname:<13} │ {u.role:<8} │ {'yes' if u.is_active else 'no':<8} │")
        print("└────┴──────────────────────────────────┴───────────────┴──────────┴──────────┘")

        # ── Login test: commissioner ──────────────────────────────────────────
        print("\n── Login tests ────────────────────────────────────────────────")
        comm_user = db.query(User).filter(User.role == "commissioner").first()
        comm_token = None
        if comm_user:
            user_obj  = authenticate_user(comm_user.email, SEED_PASSWORD, db)
            comm_token = create_access_token(user_obj)
            payload   = _decode_token(comm_token)
            print(f"\nCommissioner login: {comm_user.email}")
            print(f"  token (first 40): {comm_token[:40]}...")
            print(f"  decoded claims  : sub={payload['sub']}  team_id={payload['team_id']}"
                  f"  role={payload['role']}")

        # ── Login test: wrong password ─────────────────────────────────────────
        print("\nWrong-password test (expect 401):")
        try:
            authenticate_user(comm_user.email, "wrongpassword", db)
            print("  ERROR: should have raised!")
        except Exception as e:
            print(f"  Blocked correctly: HTTP {e.status_code} — {e.detail}")

        # ── Login test: regular GM ─────────────────────────────────────────────
        gm_user = db.query(User).filter(User.role == "gm").first()
        if gm_user:
            gm_obj   = authenticate_user(gm_user.email, SEED_PASSWORD, db)
            gm_token = create_access_token(gm_obj)
            payload  = _decode_token(gm_token)
            print(f"\nGM login: {gm_user.email}")
            print(f"  decoded claims: sub={payload['sub']}  team_id={payload['team_id']}"
                  f"  role={payload['role']}")

        # ── Promote / demote test ──────────────────────────────────────────────
        print("\nPromote/demote test:")
        if gm_user:
            promoted = promote_user(gm_user.email, "commissioner", db)
            print(f"  {promoted.email} → role={promoted.role}")
            demoted  = promote_user(gm_user.email, "gm", db)
            print(f"  {demoted.email} → role={demoted.role} (reverted)")

        # ── assert_own_team test ───────────────────────────────────────────────
        print("\nassert_own_team tests:")
        if comm_user and gm_user:
            # Commissioner can access any team
            try:
                assert_own_team(99, comm_user)
                print("  Commissioner: team 99 access OK")
            except Exception as e:
                print(f"  Commissioner: UNEXPECTED block — {e.detail}")

            # GM blocked from another team
            other_team_id = (gm_user.team_id or 1) + 1
            try:
                assert_own_team(other_team_id, gm_user)
                print(f"  GM: accessed team {other_team_id} — SHOULD NOT HAPPEN")
            except Exception as e:
                print(f"  GM: correctly blocked from team {other_team_id} — {e.detail}")

            # GM can access own team
            try:
                assert_own_team(gm_user.team_id, gm_user)
                print(f"  GM: own team {gm_user.team_id} access OK")
            except Exception as e:
                print(f"  GM: UNEXPECTED block from own team — {e.detail}")

        print("\nP1.1 JWT auth — smoke test complete.")
        print(f"\nSeeded accounts (password: '{SEED_PASSWORD}'):")
        for u in all_users:
            print(f"  {u.role:<12}  {u.email}")
