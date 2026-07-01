"""
Wallet manager — deposit, withdraw, balance check, and transaction history.

Bet-sizing rules enforced here and re-exported for bet_engine:
  MIN_BET     = $5.00
  MAX_BET_PCT = 0.20  (20 % of current balance per single bet)

All mutating functions write a Transaction row and return a WalletState snapshot.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Bet, BeefChallenge, Transaction, Wallet, Team

# ── Bet-sizing constants (imported by bet_engine) ─────────────────────────────
MIN_BET     = 5.00
MAX_BET_PCT = 0.20


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class WalletState:
    wallet_id:         int
    team_id:           int
    team_name:         str
    owner:             str
    balance:           float
    max_single_bet:    float   # 20 % of balance
    open_bets:           int
    pending_exposure:    float   # sum of amounts still pending settlement
    challenge_reserved:  float   # sum of stakes in pending BeefChallenges issued by this team
    total_deposited:     float
    total_withdrawn:   float
    total_wagered:     float
    total_payout:      float

    @property
    def net_pnl(self) -> float:
        return round(self.total_payout - self.total_wagered, 2)


@dataclass
class TxRecord:
    tx_id:       int
    wallet_id:   int
    amount:      float
    type:        str        # deposit | withdrawal | bet | payout
    created_at:  str        # ISO-8601
    bet_id:      int | None = None
    bet_type:    str | None = None
    bet_desc:    str | None = None
    bet_status:  str | None = None


@dataclass
class TransactionHistory:
    wallet_id:  int
    team_name:  str
    owner:      str
    balance:    float
    total:      int          # total rows (before limit/offset)
    page_size:  int
    page_offset: int
    records:    list[TxRecord] = field(default_factory=list)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_wallet(wallet_id: int, db: Session) -> Wallet:
    w = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not w:
        raise ValueError(f"Wallet {wallet_id} not found")
    return w


def _challenge_reserved(team_id: int, db: Session) -> float:
    """Sum of stakes in pending BeefChallenges issued by this team (soft-locked at issue time)."""
    rows = (
        db.query(BeefChallenge)
        .filter(
            BeefChallenge.challenger_team_id == team_id,
            BeefChallenge.status == "pending",
        )
        .all()
    )
    return round(sum(c.amount for c in rows), 2)


def _wallet_state(w: Wallet, db: Session) -> WalletState:
    txns = db.query(Transaction).filter(Transaction.wallet_id == w.id).all()

    total_deposited  = sum(t.amount for t in txns if t.type == "deposit")
    total_withdrawn  = sum(abs(t.amount) for t in txns if t.type == "withdrawal")
    total_wagered    = sum(abs(t.amount) for t in txns if t.type == "bet")
    total_payout     = sum(t.amount for t in txns if t.type == "payout")

    open_bets = db.query(Bet).filter(
        Bet.wallet_id == w.id, Bet.status == "pending"
    ).all()
    pending_exposure   = round(sum(b.amount for b in open_bets), 2)
    challenge_reserved = _challenge_reserved(w.team_id, db)

    return WalletState(
        wallet_id          = w.id,
        team_id            = w.team_id,
        team_name          = w.team.team_name,
        owner              = w.team.owner,
        balance            = w.balance,
        max_single_bet     = round(w.balance * MAX_BET_PCT, 2),
        open_bets          = len(open_bets),
        pending_exposure   = pending_exposure,
        challenge_reserved = challenge_reserved,
        total_deposited    = round(total_deposited, 2),
        total_withdrawn    = round(total_withdrawn, 2),
        total_wagered      = round(total_wagered, 2),
        total_payout       = round(total_payout, 2),
    )


# ── Public API ────────────────────────────────────────────────────────────────

def deposit(wallet_id: int, amount: float, db: Session) -> WalletState:
    """Credit wallet and write a deposit transaction."""
    if amount <= 0:
        raise ValueError("Deposit amount must be positive")
    if amount > 1_000_000:
        raise ValueError("Deposit amount exceeds maximum of $1,000,000")

    w = _get_wallet(wallet_id, db)
    w.balance = round(w.balance + amount, 2)
    db.add(Transaction(
        wallet_id  = wallet_id,
        amount     = amount,
        type       = "deposit",
        created_at = datetime.now(timezone.utc),
    ))
    db.commit()
    db.refresh(w)
    return _wallet_state(w, db)


def withdraw(wallet_id: int, amount: float, db: Session) -> WalletState:
    """Debit wallet and write a withdrawal transaction."""
    if amount <= 0:
        raise ValueError("Withdrawal amount must be positive")

    w = _get_wallet(wallet_id, db)
    if amount > w.balance:
        raise ValueError(
            f"Insufficient balance: requested ${amount:.2f}, available ${w.balance:.2f}"
        )

    open_bets          = db.query(Bet).filter(
        Bet.wallet_id == wallet_id, Bet.status == "pending"
    ).all()
    pending_exposure   = sum(b.amount for b in open_bets)
    ch_reserved        = _challenge_reserved(w.team_id, db)
    available          = round(w.balance - pending_exposure - ch_reserved, 2)
    if amount > available:
        raise ValueError(
            f"Cannot withdraw ${amount:.2f}: ${pending_exposure:.2f} is locked in "
            f"{len(open_bets)} pending bet(s) and ${ch_reserved:.2f} is reserved for "
            f"pending challenges. Available to withdraw: ${available:.2f}"
        )

    w.balance = round(w.balance - amount, 2)
    db.add(Transaction(
        wallet_id  = wallet_id,
        amount     = -amount,
        type       = "withdrawal",
        created_at = datetime.now(timezone.utc),
    ))
    db.commit()
    db.refresh(w)
    return _wallet_state(w, db)


def balance_check(wallet_id: int, db: Session) -> WalletState:
    """Return current wallet state without modifying anything."""
    return _wallet_state(_get_wallet(wallet_id, db), db)


def balance_check_by_team(team_id: int, db: Session) -> WalletState:
    w = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    if not w:
        raise ValueError(f"No wallet found for team {team_id}")
    return _wallet_state(w, db)


def transaction_history(
    wallet_id: int,
    db:        Session,
    limit:     int = 50,
    offset:    int = 0,
) -> TransactionHistory:
    """Return paginated transaction history with bet metadata joined in."""
    w = _get_wallet(wallet_id, db)

    total = db.query(Transaction).filter(Transaction.wallet_id == wallet_id).count()

    rows = (
        db.query(Transaction)
        .filter(Transaction.wallet_id == wallet_id)
        .order_by(Transaction.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    records: list[TxRecord] = []
    for t in rows:
        bet = t.bet
        records.append(TxRecord(
            tx_id      = t.id,
            wallet_id  = t.wallet_id,
            amount     = t.amount,
            type       = t.type,
            created_at = t.created_at.isoformat() if t.created_at else "",
            bet_id     = t.bet_id,
            bet_type   = bet.bet_type   if bet else None,
            bet_desc   = bet.description if bet else None,
            bet_status = bet.status     if bet else None,
        ))

    return TransactionHistory(
        wallet_id   = wallet_id,
        team_name   = w.team.team_name,
        owner       = w.team.owner,
        balance     = w.balance,
        total       = total,
        page_size   = limit,
        page_offset = offset,
        records     = records,
    )


def validate_bet_amount(amount: float, wallet_balance: float) -> None:
    """
    Raise ValueError if amount violates bet-sizing rules.
    Called by bet_engine before any bet is placed.
    """
    if amount < MIN_BET:
        raise ValueError(
            f"Bet amount ${amount:.2f} is below the minimum of ${MIN_BET:.2f}"
        )
    max_allowed = round(wallet_balance * MAX_BET_PCT, 2)
    if amount > max_allowed:
        raise ValueError(
            f"Bet amount ${amount:.2f} exceeds the maximum of "
            f"{MAX_BET_PCT:.0%} of your balance (${max_allowed:.2f})"
        )


# ── CLI demo ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    from db.schema import SessionLocal

    team_id   = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    dep_amt   = float(sys.argv[2]) if len(sys.argv) > 2 else 500.0

    with SessionLocal() as db:
        w0 = db.query(Wallet).filter(Wallet.team_id == team_id).first()
        if not w0:
            print(f"No wallet for team {team_id}")
            sys.exit(1)

        print(f"\nWallet manager demo — team {team_id}: {w0.team.team_name}")
        print(f"  Starting balance: ${w0.balance:,.2f}\n")

        # Deposit
        state = deposit(w0.id, dep_amt, db)
        print(f"  deposit(${dep_amt:.2f})  → balance ${state.balance:,.2f}  "
              f"max_bet ${state.max_single_bet:,.2f}")

        # Max bet (20 % of new balance)
        max_bet = state.max_single_bet
        print(f"  Max single bet at this balance: ${max_bet:,.2f}\n")

        # Withdraw a small amount
        small_wd = 50.0
        state2 = withdraw(w0.id, small_wd, db)
        print(f"  withdraw(${small_wd:.2f})  → balance ${state2.balance:,.2f}")

        # Balance check
        bc = balance_check(w0.id, db)
        print(f"\n  Balance check:")
        print(f"    balance          ${bc.balance:>10,.2f}")
        print(f"    max_single_bet   ${bc.max_single_bet:>10,.2f}")
        print(f"    open_bets        {bc.open_bets:>10}")
        print(f"    total_deposited  ${bc.total_deposited:>10,.2f}")
        print(f"    total_withdrawn  ${bc.total_withdrawn:>10,.2f}")
        print(f"    total_wagered    ${bc.total_wagered:>10,.2f}")
        print(f"    total_payout     ${bc.total_payout:>10,.2f}")
        print(f"    net_pnl          ${bc.net_pnl:>+10,.2f}")

        # Transaction history
        hist = transaction_history(w0.id, db, limit=10)
        print(f"\n  Last {len(hist.records)} transactions (of {hist.total} total)\n")
        print("  ┌──────┬────────────┬──────────────┬────────────────────────────────────────────────┐")
        print("  │  TX  │ Type       │ Amount       │ Detail                                         │")
        print("  ├──────┼────────────┼──────────────┼────────────────────────────────────────────────┤")
        for r in hist.records:
            sign   = "+" if r.amount >= 0 else ""
            detail = r.bet_desc or ""
            if r.bet_status:
                detail = f"[{r.bet_status}] {detail}"
            print(f"  │ {r.tx_id:<4} │ {r.type:<10} │ {sign}{r.amount:>+11.2f} │ {detail[:46]:<46} │")
        print("  └──────┴────────────┴──────────────┴────────────────────────────────────────────────┘")
