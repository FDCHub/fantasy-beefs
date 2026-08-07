"""
P1.3 FAAB Wallet — split bet + waiver architecture per GM.

Bet wallet  : existing wallets table — managed by wallet_manager.py.
Waiver wallet: faab_wallets table — managed here.

Architecture
  • Commissioner calls setup_faab_config() to set opening balances + transfer rules.
  • Commissioner calls init_season_wallets() once to credit opening balances to all teams.
  • Opening balance can be $0 (betting is then opt-in via top-up).
  • GMs request a bet-wallet top-up → recorded pending, awaiting commissioner approval.
  • GMs request a waiver-wallet top-up → recorded pending, queued until next Tuesday.
  • GMs may transfer between wallets subject to FaabConfig.allow_* flags.
  • If a GM's bet wallet balance reaches $0, betting is frozen until they top up.
  • All FAAB movements are logged to faab_transactions for a full audit trail.

Funding model
  • No payment processing. Stripe was removed from the MVP: there is no payment
    link, webhook, connected account or payout path here. A top-up is an
    internal request that a commissioner confirms; no real money moves through
    the application. See spec/SPEC_B2_Stripe_Removal_Addendum_v1.md.
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

class TopUpsUnavailableError(RuntimeError):
    """Raised when a FAAB/BAB top-up would be applied while the B6
    issuance-ledger model is unavailable.

    This is a refusal, not a failure: it is raised BEFORE any wallet,
    transaction or ledger state is read for mutation, so nothing is left
    half-applied. Callers that treat it as a step outcome should record the
    step as unavailable — never as applied."""


DEFAULT_OPENING_BET    = 50.00
DEFAULT_OPENING_WAIVER = 50.00


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
    payment_url: Optional[str]  # always None in the MVP; no payment rail exists


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


def create_bet_topup(
    team_id:      int,
    amount:       float,
    db:           Session,
    performer_id: Optional[int] = None,
) -> TopupResult:
    """
    REFUSES (B6 §11.5). Creating a top-up request through this path would open a
    request the B6 issuance service does not govern: no frozen cap check, no
    allocation lock, no League-row serialization, and no route to a balanced
    issuance posting. It raises TopUpsUnavailableError as its FIRST executable
    statement — before any FaabWallet read, any FaabTransaction insert, any flush
    and any commit — so no row can be written by it.

    The replacement is POST /league/{league_id}/top-offs, served by
    economy/top_off.py. That is the ONE production issuance path.

    The refusal is structural rather than an environment flag, and it is not a
    silent no-op: a no-op would report a request that does not exist.

    This writer is also already unrepresentable at the database. It builds its
    row through _log_tx(), which sets `status` but no `decision`, and a
    topup_bet row with a NULL decision violates ck_faab_tx_topup_bet_lifecycle
    (§4.4). Refusing here turns an opaque IntegrityError into a diagnosis.

    The body below is retained UNREACHED as historical reference; the B6
    replacement does not derive from it.
    """
    raise TopUpsUnavailableError(
        "Legacy FAAB/BAB bet top-up requests are retired. Creating one here "
        "would open a request outside the B6 issuance service, with no frozen "
        "cap check, no allocation lock and no path to a balanced issuance "
        "posting. Use POST /league/{league_id}/top-offs. Nothing was written."
    )

    if amount <= 0:
        raise ValueError("Top-up amount must be positive")

    fw   = _get_faab_wallet(team_id, db)
    team = fw.team

    tx = _log_tx(
        db,
        fw.league_id,
        team_id,
        "topup_bet",
        amount,
        wallet_from="issuance",
        wallet_to="bet",
        status="pending",
        note=f"Bet top-up request: ${amount:.2f} — awaiting commissioner approval",
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
    )



def create_waiver_topup(
    team_id:      int,
    amount:       float,
    db:           Session,
    performer_id: Optional[int] = None,
) -> TopupResult:
    """
    REFUSES (B6 §11.5). Queuing a waiver top-up would create a pending row for
    the Tuesday pipeline to apply, and applying one is itself refused by
    apply_pending_topups() because it would mint wallet balance with no balanced
    issuance posting behind it. Creating work that can only ever be refused is
    not a lifecycle; it raises TopUpsUnavailableError as its FIRST executable
    statement, before any FaabWallet read, insert, flush or commit.

    WAIVER TOP-UPS ARE OUT OF B6 ENTIRELY (§3.5). Credits land in
    wallet:{team_id} and nowhere else; the waiver lifecycle is not a top-off and
    gets no replacement route here. There is deliberately no B6 equivalent to
    point at, which is why this is a plain retirement rather than a redirect.

    The body below is retained UNREACHED as historical reference.
    """
    raise TopUpsUnavailableError(
        "Legacy FAAB waiver top-up requests are retired. The Tuesday apply step "
        "that would have consumed them refuses outright, and waiver top-ups are "
        "excluded from B6 issuance entirely. Nothing was written."
    )

    if amount <= 0:
        raise ValueError("Top-up amount must be positive")

    fw      = _get_faab_wallet(team_id, db)
    team    = fw.team
    tuesday = _next_tuesday()

    tx = _log_tx(db, fw.league_id, team_id, "topup_waiver", amount,
                 wallet_from="issuance", wallet_to="waiver",
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
    )



def confirm_topup(
    faab_tx_id: int,
    db:         Session,
) -> TopupResult:
    """
    REFUSES (B6 §11.5). This is the writer B6 exists to replace: it credited a
    wallet through wallet_manager.deposit() on a commissioner's say-so, with no
    balanced ledger posting, no issuance counterparty, no frozen cap, no
    disclosure and no locks. It raises TopUpsUnavailableError as its FIRST
    executable statement — before the FaabTransaction lookup, before any status
    change, before any deposit and before any commit — so no balance can move.

    The replacement is POST /league/{league_id}/top-offs/{request_id}/approve,
    served by approve_top_off() in economy/top_off.py, which posts two balanced
    legs, mirrors the Wallet from the ledger's own post-state, writes the durable
    disclosure and commits once, all under three row locks.

    It is also already unrepresentable at the database: setting a topup_bet row
    to status='applied' without both linkage fields violates
    ck_faab_tx_topup_bet_linkage (§4.4). Refusing here reports the retirement
    instead of an opaque IntegrityError.

    The body below is retained UNREACHED as historical reference.
    """
    raise TopUpsUnavailableError(
        "Legacy FAAB/BAB top-up confirmation is retired. Confirming here would "
        "credit a wallet with no balanced issuance-ledger posting, no frozen cap "
        "check and no disclosure record. Use POST "
        "/league/{league_id}/top-offs/{request_id}/approve. No balance was "
        "changed and nothing was written."
    )

    tx = db.query(FaabTransaction).filter(FaabTransaction.id == faab_tx_id).first()
    if not tx:
        raise ValueError(f"FAAB transaction {faab_tx_id} not found")
    if tx.status == "applied":
        return _tx_to_topup_result(tx)
    if tx.status not in ("pending",):
        raise ValueError(f"Transaction {faab_tx_id} has status '{tx.status}' — cannot confirm")

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
        tx.note = (tx.note or "") + " [confirmed by commissioner]"
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
        payment_url = None,
    )


def apply_pending_topups(db: Session) -> list[FaabTxRecord]:
    """
    REFUSES. Applying a pending top-up would mint wallet balance with no
    counterparty and no ledger posting behind it, which is not an acceptable
    Credits issuance model.

    Stripe is out of the MVP and the B6 issuance-ledger model does not exist
    yet, so there is currently no correct way to apply a top-up. This function
    therefore raises TopUpsUnavailableError as its FIRST statement — before any
    query, any FaabWallet read, any status change and any ledger call — so no
    pending row, wallet balance or ledger entry can be touched.

    This is deliberately not an environment flag and not a silent no-op: a
    no-op would report success while quietly applying nothing, which is worse
    than refusing.

    B6 must supply a balanced ledger posting, an issuance counterparty/account,
    approver identity and request-to-credit provenance before this refusal is
    lifted. The body below is retained unreached as B6's starting point.

    See spec/SPEC_B2_Stripe_Removal_Addendum_v1.md and
    FantasyBeefs_BAB_TopOff_UIUX_Spec_2026-07-21.md item B6.
    """
    raise TopUpsUnavailableError(
        "FAAB/BAB top-ups are unavailable: applying one would credit a wallet "
        "with no balanced issuance-ledger posting behind it. This remains "
        "refused until the B6 issuance-ledger model provides a balanced "
        "posting, an issuance counterparty account, approver identity and "
        "request-to-credit provenance. No pending top-up was applied and no "
        "balance was changed."
    )

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
