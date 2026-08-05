"""
P1.3 FAAB Wallet — split bet + waiver architecture per GM.

Bet wallet  : existing wallets table — managed by wallet_manager.py.
Waiver wallet: faab_wallets table — managed here.

Architecture
  • Commissioner calls setup_faab_config() to set opening balances + transfer rules.
  • Commissioner calls init_season_wallets() once to credit opening balances to all teams.
  • Opening balance can be $0 (betting is then opt-in via top-up).
  • GMs top up their bet wallet via Stripe → applied immediately.
  • GMs top up their waiver wallet via Stripe → queued until next Tuesday.
  • GMs may transfer between wallets subject to FaabConfig.allow_* flags.
  • If a GM's bet wallet balance reaches $0, betting is frozen until they top up.
  • All FAAB movements are logged to faab_transactions for a full audit trail.

Stripe
  • Real mode: STRIPE_SECRET_KEY env-var set → creates Stripe Payment Links.
  • Mock mode: env-var absent → fake link IDs; bet top-ups apply immediately.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import (
    Bet,
    BeefChallenge,
    FaabConfig,
    FaabTransaction,
    FaabWallet,
    League,
    Team,
    Wallet,
)
from db.deps import get_db
from auth.jwt_auth import get_current_gm
from auth.allocation_gate import get_season_allocation_gate
from wallet.wallet_manager import deposit as wm_deposit
from wallet.wallet_manager import _challenge_reserved

# ── Config ─────────────────────────────────────────────────────────────────────

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
MOCK_MODE         = not bool(STRIPE_SECRET_KEY)

DEFAULT_OPENING_BET    = 50.00
DEFAULT_OPENING_WAIVER = 50.00

if not MOCK_MODE:
    import stripe as _stripe
    _stripe.api_key = STRIPE_SECRET_KEY


# ── Date helpers ──────────────────────────────────────────────────────────────

def _next_tuesday(from_dt: Optional[datetime] = None) -> datetime:
    """Return the upcoming Tuesday at 03:00 UTC (waiver processing time)."""
    base = from_dt or datetime.now(timezone.utc)
    days_ahead = 1 - base.weekday()   # Tuesday = weekday 1
    if days_ahead <= 0:
        days_ahead += 7
    return (base + timedelta(days=days_ahead)).replace(
        hour=3, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
    )


def _mock_link_id(prefix: str = "plink") -> str:
    return f"{prefix}_faab_{uuid.uuid4().hex[:10]}"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_faab_wallet(team_id: int, db: Session) -> FaabWallet:
    fw = db.query(FaabWallet).filter(FaabWallet.team_id == team_id).first()
    if not fw:
        raise ValueError(
            f"FAAB wallet not found for team {team_id}. "
            "Run /faab/init-season to create wallets."
        )
    return fw


def _get_bet_wallet(team_id: int, db: Session) -> Wallet:
    w = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    if not w:
        raise ValueError(f"Betting wallet not found for team {team_id}")
    return w


def _log_tx(
    db: Session,
    league_id:    int,
    team_id:      int,
    tx_type:      str,
    amount:       float,
    *,
    wallet_from:  Optional[str]      = None,
    wallet_to:    Optional[str]      = None,
    status:       str                = "applied",
    note:         Optional[str]      = None,
    stripe_link_id:  Optional[str]   = None,
    stripe_link_url: Optional[str]   = None,
    apply_on:     Optional[datetime] = None,
    applied_at:   Optional[datetime] = None,
) -> FaabTransaction:
    tx = FaabTransaction(
        league_id       = league_id,
        team_id         = team_id,
        type            = tx_type,
        amount          = round(amount, 2),
        wallet_from     = wallet_from,
        wallet_to       = wallet_to,
        status          = status,
        note            = note,
        stripe_link_id  = stripe_link_id,
        stripe_link_url = stripe_link_url,
        apply_on        = apply_on,
        applied_at      = applied_at,
    )
    db.add(tx)
    return tx


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class FaabConfigState:
    league_id:           int
    opening_bet:         float
    opening_waiver:      float
    allow_bet_to_waiver: bool
    allow_waiver_to_bet: bool
    season_initialized:  bool


@dataclass
class FaabWalletState:
    faab_wallet_id:       int
    team_id:              int
    team_name:            str
    owner:                str
    # Bet wallet (from wallets table)
    bet_balance:          float
    bet_open_bets:        int
    bet_pending_exposure:   float
    bet_challenge_reserved: float   # stakes held in pending BeefChallenges issued by this team
    bet_max_single_bet:     float
    bet_frozen:             bool
    # Waiver wallet (from faab_wallets table)
    waiver_balance:       float
    pending_waiver_topup: float
    # Summary
    total_available:      float


@dataclass
class TopupResult:
    faab_tx_id:  int
    team_id:     int
    wallet_type: str          # "bet" | "waiver"
    amount:      float
    status:      str          # "applied" | "pending"
    apply_on:    Optional[str]  # ISO if pending, else None
    payment_url: Optional[str]  # Stripe link or None (mock-immediate)
    mock_mode:   bool


@dataclass
class TransferResult:
    team_id:              int
    from_wallet:          str
    to_wallet:            str
    amount:               float
    bet_balance_after:    float
    waiver_balance_after: float


@dataclass
class FaabTxRecord:
    id:           int
    team_id:      int
    tx_type:      str
    amount:       float
    wallet_from:  Optional[str]
    wallet_to:    Optional[str]
    status:       str
    note:         Optional[str]
    apply_on:     Optional[str]
    applied_at:   Optional[str]
    created_at:   str


# ── Wallet state builder ──────────────────────────────────────────────────────

def _build_state(fw: FaabWallet, db: Session) -> FaabWalletState:
    team  = fw.team
    bwallet = _get_bet_wallet(fw.team_id, db)

    open_bets = db.query(Bet).filter(
        Bet.wallet_id == bwallet.id, Bet.status == "pending"
    ).all()
    pending_exp        = round(sum(b.amount for b in open_bets), 2)
    ch_reserved = _challenge_reserved(fw.team_id, db)

    return FaabWalletState(
        faab_wallet_id          = fw.id,
        team_id                 = fw.team_id,
        team_name               = team.team_name,
        owner                   = team.owner,
        bet_balance             = round(bwallet.balance, 2),
        bet_open_bets           = len(open_bets),
        bet_pending_exposure    = pending_exp,
        bet_challenge_reserved  = ch_reserved,
        bet_max_single_bet      = round(bwallet.balance * 0.20, 2),
        bet_frozen              = bool(fw.bet_frozen),
        waiver_balance          = round(fw.waiver_balance, 2),
        pending_waiver_topup    = round(fw.pending_waiver_topup, 2),
        total_available         = round(bwallet.balance + fw.waiver_balance, 2),
    )


# ── Config ────────────────────────────────────────────────────────────────────

def setup_faab_config(
    league_id:          int,
    db:                 Session,
    opening_bet:        float = DEFAULT_OPENING_BET,
    opening_waiver:     float = DEFAULT_OPENING_WAIVER,
    allow_bet_to_waiver: bool = True,
    allow_waiver_to_bet: bool = True,
) -> FaabConfigState:
    """Create or update league FAAB configuration. Safe to call multiple times."""
    if opening_bet < 0 or opening_waiver < 0:
        raise ValueError("Opening balances cannot be negative")

    cfg = db.query(FaabConfig).filter(FaabConfig.league_id == league_id).first()
    if cfg is None:
        cfg = FaabConfig(league_id=league_id)
        db.add(cfg)

    cfg.opening_bet         = round(opening_bet, 2)
    cfg.opening_waiver      = round(opening_waiver, 2)
    cfg.allow_bet_to_waiver = 1 if allow_bet_to_waiver else 0
    cfg.allow_waiver_to_bet = 1 if allow_waiver_to_bet else 0
    cfg.updated_at          = _now()

    db.commit()
    return _cfg_state(cfg)


def _cfg_state(cfg: FaabConfig) -> FaabConfigState:
    return FaabConfigState(
        league_id           = cfg.league_id,
        opening_bet         = cfg.opening_bet,
        opening_waiver      = cfg.opening_waiver,
        allow_bet_to_waiver = bool(cfg.allow_bet_to_waiver),
        allow_waiver_to_bet = bool(cfg.allow_waiver_to_bet),
        season_initialized  = bool(cfg.season_initialized),
    )


def get_faab_config(league_id: int, db: Session) -> FaabConfigState:
    cfg = db.query(FaabConfig).filter(FaabConfig.league_id == league_id).first()
    if not cfg:
        raise ValueError(f"FAAB not configured for league {league_id}")
    return _cfg_state(cfg)


# ── Season init ───────────────────────────────────────────────────────────────

def init_season_wallets(
    league_id:    int,
    db:           Session,
    performer_id: Optional[int] = None,
) -> list[FaabWalletState]:
    """
    Create one FaabWallet per team and credit each team's opening balances.
    Idempotent per team — skips teams that already have a FaabWallet.
    Marks FaabConfig.season_initialized = True when all teams are done.
    """
    cfg = db.query(FaabConfig).filter(FaabConfig.league_id == league_id).first()
    if not cfg:
        raise ValueError(f"FAAB not configured for league {league_id}. Call /faab/setup first.")

    teams = db.query(Team).filter(Team.league_id == league_id).order_by(Team.id).all()
    if not teams:
        raise ValueError(f"No teams found in league {league_id}")

    states = []
    for team in teams:
        existing_fw = db.query(FaabWallet).filter(FaabWallet.team_id == team.id).first()
        if existing_fw:
            states.append(_build_state(existing_fw, db))
            continue

        fw = FaabWallet(
            team_id        = team.id,
            league_id      = league_id,
            waiver_balance = cfg.opening_waiver,
        )
        db.add(fw)
        db.flush()

        # Credit opening waiver balance in FAAB audit trail
        if cfg.opening_waiver > 0:
            _log_tx(db, league_id, team.id, "opening_credit", cfg.opening_waiver,
                    wallet_to="waiver",
                    note=f"Season opening waiver balance: ${cfg.opening_waiver:.2f}",
                    applied_at=_now())

        db.flush()
        db.refresh(fw)
        states.append(_build_state(fw, db))

    cfg.season_initialized = 1
    cfg.updated_at         = _now()
    db.commit()
    return states


# ── Read state ────────────────────────────────────────────────────────────────

def get_faab_wallet(team_id: int, db: Session) -> FaabWalletState:
    fw = _get_faab_wallet(team_id, db)
    return _build_state(fw, db)


def get_league_faab(league_id: int, db: Session) -> list[FaabWalletState]:
    wallets = (
        db.query(FaabWallet)
        .filter(FaabWallet.league_id == league_id)
        .order_by(FaabWallet.team_id)
        .all()
    )
    return [_build_state(fw, db) for fw in wallets]


# ── Top-ups ───────────────────────────────────────────────────────────────────

def _create_stripe_link(
    team: Team,
    amount: float,
    wallet_type: str,
    faab_tx_id: int,
) -> tuple[str, str]:
    """Return (link_id, link_url). Creates real Stripe link or mock."""
    if MOCK_MODE:
        link_id  = _mock_link_id()
        link_url = f"https://buy.stripe.com/mock/{link_id}"
        return link_id, link_url

    price = _stripe.Price.create(
        unit_amount  = int(amount * 100),
        currency     = "usd",
        product_data = {
            "name": f"Fantasy Beefs {wallet_type.title()} Wallet Top-Up — {team.team_name}",
        },
    )
    link_obj = _stripe.PaymentLink.create(
        line_items = [{"price": price.id, "quantity": 1}],
        metadata   = {
            "wallet_type": wallet_type,
            "team_id":     str(team.id),
            "faab_tx_id":  str(faab_tx_id),
        },
        after_completion = {
            "type":     "redirect",
            "redirect": {"url": f"https://fantasybeefs.com/faab/topup-done/{wallet_type}"},
        },
    )
    return link_obj.id, link_obj.url


def create_bet_topup(
    team_id:      int,
    amount:       float,
    db:           Session,
    performer_id: Optional[int] = None,
) -> TopupResult:
    """
    Top up the bet wallet via Stripe.

    Real mode : creates a Stripe Payment Link — funds applied on webhook / manual confirm.
    Mock mode : applies immediately (calls wallet_manager.deposit directly).
    """
    if amount <= 0:
        raise ValueError("Top-up amount must be positive")

    fw   = _get_faab_wallet(team_id, db)
    team = fw.team

    if MOCK_MODE:
        tx = _log_tx(
            db,
            fw.league_id,
            team_id,
            "topup_bet",
            amount,
            wallet_from="stripe",
            wallet_to="bet",
            status="pending",
            note=f"Mock bet top-up request: ${amount:.2f} — awaiting commissioner approval",
        )
        db.flush()
        db.commit()
        db.refresh(tx)
        return TopupResult(
            faab_tx_id=tx.id,
            team_id=team_id,
            wallet_type="bet",
            amount=amount,
            status="pending",
            apply_on=None,
            payment_url=None,
            mock_mode=True,
        )

    # Real mode: create Stripe link, return for GM to pay
    tx = _log_tx(db, fw.league_id, team_id, "topup_bet", amount,
                 wallet_from="stripe", wallet_to="bet",
                 status="pending",
                 note=f"Bet top-up ${amount:.2f} — awaiting Stripe payment")
    db.flush()
    link_id, link_url = _create_stripe_link(team, amount, "bet", tx.id)
    tx.stripe_link_id  = link_id
    tx.stripe_link_url = link_url
    db.commit()
    db.refresh(tx)
    return TopupResult(
        faab_tx_id  = tx.id,
        team_id     = team_id,
        wallet_type = "bet",
        amount      = amount,
        status      = "pending",
        apply_on    = None,
        payment_url = link_url,
        mock_mode   = False,
    )


def create_waiver_topup(
    team_id:      int,
    amount:       float,
    db:           Session,
    performer_id: Optional[int] = None,
) -> TopupResult:
    """
    Queue a waiver wallet top-up for the next Tuesday, even in mock mode.

    Real mode : creates a Stripe Payment Link — once paid, status becomes "pending"
                (awaiting Tuesday apply).
    Mock mode : creates a "pending" record with apply_on = next Tuesday (no Stripe call).
    """
    if amount <= 0:
        raise ValueError("Top-up amount must be positive")

    fw      = _get_faab_wallet(team_id, db)
    team    = fw.team
    tuesday = _next_tuesday()

    if MOCK_MODE:
        tx = _log_tx(db, fw.league_id, team_id, "topup_waiver", amount,
                     wallet_from="stripe", wallet_to="waiver",
                     status="pending",
                     note=f"Waiver top-up ${amount:.2f} — queued for {tuesday.date()}",
                     apply_on=tuesday)
        fw.pending_waiver_topup = round(fw.pending_waiver_topup + amount, 2)
        fw.updated_at           = _now()
        db.commit()
        db.refresh(tx)
        return TopupResult(
            faab_tx_id  = tx.id,
            team_id     = team_id,
            wallet_type = "waiver",
            amount      = amount,
            status      = "pending",
            apply_on    = tuesday.isoformat(),
            payment_url = None,
            mock_mode   = True,
        )

    # Real mode: create Stripe link; on payment webhook, status → pending (awaiting Tuesday)
    tx = _log_tx(db, fw.league_id, team_id, "topup_waiver", amount,
                 wallet_from="stripe", wallet_to="waiver",
                 status="pending",
                 note=f"Waiver top-up ${amount:.2f} — queued for {tuesday.date()}",
                 apply_on=tuesday)
    db.flush()
    link_id, link_url = _create_stripe_link(team, amount, "waiver", tx.id)
    tx.stripe_link_id  = link_id
    tx.stripe_link_url = link_url
    db.commit()
    db.refresh(tx)
    return TopupResult(
        faab_tx_id  = tx.id,
        team_id     = team_id,
        wallet_type = "waiver",
        amount      = amount,
        status      = "pending",
        apply_on    = tuesday.isoformat(),
        payment_url = link_url,
        mock_mode   = False,
    )


def confirm_topup(
    faab_tx_id:       int,
    db:               Session,
    stripe_session_id: Optional[str] = None,
) -> TopupResult:
    """
    Confirm payment for a pending top-up (called from webhook or manually).

    Bet top-up  : applies immediately — credits bet wallet via wallet_manager.deposit().
    Waiver topup: marks Stripe payment received; funds remain queued for Tuesday.
    """
    tx = db.query(FaabTransaction).filter(FaabTransaction.id == faab_tx_id).first()
    if not tx:
        raise ValueError(f"FAAB transaction {faab_tx_id} not found")
    if tx.status == "applied":
        return _tx_to_topup_result(tx)
    if tx.status not in ("pending",):
        raise ValueError(f"Transaction {faab_tx_id} has status '{tx.status}' — cannot confirm")

    if stripe_session_id:
        tx.stripe_session_id = stripe_session_id

    if tx.type == "topup_bet":
        bet_wallet = _get_bet_wallet(tx.team_id, db)
        wm_deposit(bet_wallet.id, tx.amount, db)
        fw = _get_faab_wallet(tx.team_id, db)
        _unfreeze_if_funded(tx.team_id, fw, bet_wallet, db)
        tx.status     = "applied"
        tx.applied_at = _now()
        db.commit()

    elif tx.type == "topup_waiver":
        # Payment confirmed — keep pending until Tuesday (applied by apply_pending_topups)
        tx.note = (tx.note or "") + " [Stripe payment received]"
        db.commit()

    db.refresh(tx)
    return _tx_to_topup_result(tx)


def _tx_to_topup_result(tx: FaabTransaction) -> TopupResult:
    return TopupResult(
        faab_tx_id  = tx.id,
        team_id     = tx.team_id,
        wallet_type = "bet" if tx.type == "topup_bet" else "waiver",
        amount      = tx.amount,
        status      = tx.status,
        apply_on    = tx.apply_on.isoformat() if tx.apply_on else None,
        payment_url = tx.stripe_link_url,
        mock_mode   = MOCK_MODE,
    )


def apply_pending_topups(db: Session) -> list[FaabTxRecord]:
    """
    Apply all waiver top-ups whose apply_on <= now.
    Commissioner calls this every Tuesday (or Tuesday Automation triggers it).
    """
    due = (
        db.query(FaabTransaction)
        .filter(
            FaabTransaction.type   == "topup_waiver",
            FaabTransaction.status == "pending",
            FaabTransaction.apply_on <= _now(),
        )
        .all()
    )

    applied = []
    for tx in due:
        fw = db.query(FaabWallet).filter(FaabWallet.team_id == tx.team_id).first()
        if not fw:
            tx.status = "failed"
            tx.note   = (tx.note or "") + " [no FaabWallet found]"
            continue

        fw.waiver_balance       = round(fw.waiver_balance + tx.amount, 2)
        fw.pending_waiver_topup = round(
            max(0.0, fw.pending_waiver_topup - tx.amount), 2
        )
        fw.updated_at = _now()

        tx.status     = "applied"
        tx.applied_at = _now()
        applied.append(tx)

    db.commit()
    return [_tx_record(t) for t in applied]


# ── Transfers ─────────────────────────────────────────────────────────────────

def transfer(
    team_id:      int,
    from_wallet:  str,
    to_wallet:    str,
    amount:       float,
    db:           Session,
    performer_id: Optional[int] = None,
) -> TransferResult:
    raise ValueError(
        "BAB-to-waiver transfers are retired under the four-bucket "
        "economy and are no longer supported."
    )


# ── Freeze / unfreeze ─────────────────────────────────────────────────────────

def _check_and_freeze(
    team_id:    int,
    fw:         FaabWallet,
    bet_wallet: Wallet,
    db:         Session,
) -> bool:
    """Freeze if balance <= 0. Returns True if now frozen."""
    if bet_wallet.balance <= 0 and not fw.bet_frozen:
        fw.bet_frozen = 1
        fw.updated_at = _now()
        _log_tx(db, fw.league_id, team_id, "funding_alert", 0.0,
                wallet_from="bet",
                note=f"Bet wallet balance ${bet_wallet.balance:.2f} — betting frozen",
                applied_at=_now())
        return True
    return bool(fw.bet_frozen)


def _unfreeze_if_funded(
    team_id:    int,
    fw:         FaabWallet,
    bet_wallet: Wallet,
    db:         Session,
) -> None:
    """Auto-unfreeze if balance is now positive."""
    if bet_wallet.balance > 0 and fw.bet_frozen:
        fw.bet_frozen = 0
        fw.updated_at = _now()


def check_and_freeze(team_id: int, db: Session) -> bool:
    """
    Public freeze check. Returns True if the bet wallet is currently frozen.
    Auto-unfreezes if the balance has recovered.
    """
    fw         = db.query(FaabWallet).filter(FaabWallet.team_id == team_id).first()
    bet_wallet = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    if not fw or not bet_wallet:
        return False

    if bet_wallet.balance <= 0:
        frozen = _check_and_freeze(team_id, fw, bet_wallet, db)
        db.commit()
        return frozen

    _unfreeze_if_funded(team_id, fw, bet_wallet, db)
    db.commit()
    return False


def set_freeze(team_id: int, frozen: bool, db: Session) -> FaabWalletState:
    """Commissioner override — manually freeze or unfreeze a bet wallet."""
    fw = _get_faab_wallet(team_id, db)
    fw.bet_frozen = 1 if frozen else 0
    fw.updated_at = _now()
    if frozen:
        _log_tx(db, fw.league_id, team_id, "funding_alert", 0.0,
                wallet_from="bet",
                note="Commissioner manually froze bet wallet",
                applied_at=_now())
    db.commit()
    db.refresh(fw)
    return _build_state(fw, db)


# ── Transaction history ───────────────────────────────────────────────────────

def get_faab_transactions(
    team_id: int,
    db:      Session,
    limit:   int = 50,
    offset:  int = 0,
) -> list[FaabTxRecord]:
    rows = (
        db.query(FaabTransaction)
        .filter(FaabTransaction.team_id == team_id)
        .order_by(FaabTransaction.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_tx_record(r) for r in rows]


def _tx_record(t: FaabTransaction) -> FaabTxRecord:
    return FaabTxRecord(
        id          = t.id,
        team_id     = t.team_id,
        tx_type     = t.type,
        amount      = t.amount,
        wallet_from = t.wallet_from,
        wallet_to   = t.wallet_to,
        status      = t.status,
        note        = t.note,
        apply_on    = t.apply_on.isoformat() if t.apply_on else None,
        applied_at  = t.applied_at.isoformat() if t.applied_at else None,
        created_at  = t.created_at.isoformat() if t.created_at else "",
    )


# ── FastAPI dependency — bet-funded gate ─────────────────────────────────────

def get_bet_funded(
    current_user: "User" = Depends(get_season_allocation_gate),
    db:           Session = Depends(get_db),
) -> "User":
    """
    FastAPI dependency — chains buy-in check + bet-frozen check.

    HTTP 402 if:
      • Treasury configured + GM hasn't paid buy-in (from get_buyin_gate)
      • FAAB system active + bet wallet is frozen (balance <= 0)

    Commissioner always bypasses both checks.
    Inactive if no FaabWallet exists for the team (FAAB system not initialized).
    """
    # Import here to avoid circular at module load
    from auth.jwt_auth import User  # type: ignore[assignment]

    if current_user.role == "commissioner":
        return current_user
    if not current_user.team_id:
        return current_user

    fw = db.query(FaabWallet).filter(FaabWallet.team_id == current_user.team_id).first()
    if not fw:
        return current_user  # FAAB not initialized — gate inactive

    is_frozen = check_and_freeze(current_user.team_id, db)
    if is_frozen:
        raise HTTPException(
            status_code = status.HTTP_402_PAYMENT_REQUIRED,
            detail      = (
                "Bet wallet is frozen (balance $0.00) — "
                "top up your bet wallet to resume betting"
            ),
        )
    return current_user
