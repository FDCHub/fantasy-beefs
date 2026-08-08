"""
JWT authentication for Fantasy Beefs.

Flow
  1. POST /auth/login  →  verify bcrypt password  →  sign HS256 JWT
                          claims: sub (user_id), team_id, role, exp
  2. Subsequent requests: Authorization: Bearer <token>
  3. get_current_user() dependency decodes + validates token → User row
  4. require_commissioner() wraps get_current_user and enforces role

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

from fastapi import Depends, HTTPException, status
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
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── Token helpers ─────────────────────────────────────────────────────────────

def create_access_token(user: User) -> str:
    payload = {
        "sub":     str(user.id),
        "email":   user.email,
        "team_id": user.team_id,
        "role":    user.role,
        "exp":     datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI dependencies ──────────────────────────────────────────────────────

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db:    Session = Depends(get_db),
) -> User:
    payload = _decode_token(token)
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
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
    """Raise 403 unless current_user owns team_id or is commissioner."""
    if current_user.role != "commissioner" and current_user.team_id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: team {team_id} is not yours",
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
    if not user or not verify_password(password, user.hashed_password):
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
