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
from betting.exceptions import BetValidationError
from ledger.ledger import _dollars_to_cents
# P1-L4 — the provenance-derived real challenge escrow this display model reports
# alongside the legacy soft reservation.
#
# IMPORTED FROM THE VIEW MODULE, NOT FROM economy.challenge_funding, AND THAT IS
# LOAD-BEARING. challenge_funding imports beefs.proposal_lifecycle in order to
# drive it, so importing it here would put the whole new challenge lifecycle into
# the application's import graph — and Package 2A's gate suite (G2) proves the
# lifecycle is UNREACHABLE from api.main, which is the guarantee that the new
# money path cannot go live by accident. The view module reads the same
# provenance and imports only db.schema.
from economy.challenge_escrow_view import team_open_challenge_escrow_cents

# ── Bet-sizing constants (imported by bet_engine) ─────────────────────────────
MIN_BET     = 5.00
MAX_BET_PCT = 0.20

# P1-L3B: MAX_BET_PCT expressed in basis points, DERIVED from the constant above
# so the product rule has exactly one source and the two cannot drift. Used only
# by validate_bet_amount()'s integer-cent cap arithmetic — MAX_BET_PCT itself is
# unchanged and remains what every display/report site reads.
_MAX_BET_BPS = round(MAX_BET_PCT * 10_000)   # 2000 bps == 20%


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


def _challenge_reserved(team_id: int, db: Session, exclude_challenge_id: int | None = None) -> float:
    """LEGACY-MODEL SOFT RESERVATION ONLY. Dollars, not authoritative for money.

    P1-L4 DISPOSITION — the `response_status IS NULL` filter is the whole point of
    this docstring. A new-model challenge (Spec 1 Rev 3) posts REAL escrow at
    issue: the stake has already left `wallet:{team}` as a ledger debit, so any
    caller reading the ledger balance is already seeing it excluded. This function
    also populates the legacy NOT NULL `status` column with 'pending' at issue
    (proposal_lifecycle.py), so WITHOUT this filter every new-model challenge
    would be counted here as well — and a gate doing
    `ledger_balance − _challenge_reserved` would subtract the same committed
    money TWICE. That double-count is precisely what the Foundation Correction
    Plan §5 and Spec 2 §14 forbid.

    So the retirement is scoped, not blanket: this value is now authoritative for
    NOTHING on the new-model path (economy/challenge_funding.py never imports it,
    and computes availability as min + wallet ledger cents alone), and it survives
    only to keep the LEGACY beef_engine flow — which still posts no escrow at
    issue — from overcommitting. Deleting it outright today would not retire a
    soft reservation; it would remove the only capacity control the legacy path
    has. It goes when the legacy path goes.

    For the real committed-money figure on the new model, read
    economy.challenge_escrow_view.team_open_challenge_escrow_cents(), which
    derives it from the funding provenance.

    READ IT FROM THE VIEW MODULE, NOT FROM economy.challenge_funding. The
    orchestrator re-exports the same name, but importing it drags
    beefs.proposal_lifecycle into the application's import graph and breaks
    Package 2A's G2 unreachability gate — the assertion that the new challenge
    lifecycle cannot be reached from api.main. The view module reads the same
    provenance and imports only db.schema.
    """
    query = db.query(BeefChallenge).filter(
        BeefChallenge.challenger_team_id == team_id,
        BeefChallenge.status.in_(["pending", "countered"]),
        # Legacy rows only — a new-model challenge carries response_status and is
        # backed by real escrow (see docstring).
        BeefChallenge.response_status.is_(None),
    )
    if exclude_challenge_id is not None:
        query = query.filter(BeefChallenge.id != exclude_challenge_id)
    total = 0.0
    for c in query.all():
        total += c.countered_amount if c.countered_amount is not None else c.amount
    return round(total, 2)


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
    # P1-L4 — DISPLAY MODEL, reading the new provenance (Foundation Plan §5:
    # "the 2 display models read the new provenance"). Two disjoint sources,
    # summed once and never double-counted:
    #   legacy challenges  → soft reservation (no escrow exists for them)
    #   new-model challenges → REAL escrow, from the funding legs
    # _challenge_reserved now excludes new-model rows, so the two sets cannot
    # overlap and no challenge contributes twice.
    challenge_reserved = round(
        _challenge_reserved(w.team_id, db)
        + team_open_challenge_escrow_cents(db, w.team_id) / 100.0,
        2,
    )

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

    _dollars_to_cents(amount)
    w = _get_wallet(wallet_id, db)
    w.balance = round(w.balance + amount, 2)
    db.add(Transaction(
        wallet_id  = wallet_id,
        amount     = amount,
        type       = "deposit",
        created_at = datetime.now(timezone.utc),
    ))
    db.flush()
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


def validate_bet_amount(amount: float, wallet_balance_cents: int) -> None:
    """
    Raise BetValidationError if amount violates bet-sizing rules.
    Called by bet_engine before any bet is placed.

    P1-L3B: `wallet_balance_cents` is the AUTHORITATIVE integer-cent ledger
    balance for the funding account — not the float Wallet.balance mirror, which
    this function no longer accepts. A float (or any non-int) argument is refused
    outright rather than coerced: silently accepting one would reintroduce exactly
    the binary-float capacity decision this correction exists to remove. That
    refusal is the only caller-visible behavior change; the product rules
    themselves (MIN_BET, the MAX_BET_PCT cap, the message text) are unchanged.

    ROUNDING — the 20% cap is still ROUNDED to the nearest cent, exactly as the
    prior `round(wallet_balance * MAX_BET_PCT, 2)` was. It is NOT floored. The
    integer form below is half-up:

        max_allowed_cents = (balance_cents * 2000 + 5000) // 10000

    and half-up is exactly nearest here, with no tie-breaking ambiguity at all:
    20% of an integer number of cents is balance_cents / 5, whose fractional part
    is always one of {.0, .2, .4, .6, .8} — never .5. So the tie case is
    unreachable by construction and the result is fully deterministic. Where
    floor and round disagree (any balance_cents % 5 in {3, 4}) this preserves the
    ROUNDED, more permissive result the product rule has always had.

    The basis-point multiplier is DERIVED from MAX_BET_PCT rather than hard-coded,
    so the constant remains the single source of the 20% product rule and the two
    cannot drift apart.
    """
    if amount < MIN_BET:
        raise BetValidationError(
            f"Bet amount ${amount:.2f} is below the minimum of ${MIN_BET:.2f}"
        )

    if isinstance(wallet_balance_cents, bool) or not isinstance(wallet_balance_cents, int):
        raise TypeError(
            f"wallet_balance_cents must be integer cents from authoritative ledger "
            f"state, not {type(wallet_balance_cents).__name__} "
            f"({wallet_balance_cents!r}). P1-L3B: no float wallet mirror may drive "
            f"a funding-capacity decision."
        )

    amount_cents      = _dollars_to_cents(amount)
    max_allowed_cents = (wallet_balance_cents * _MAX_BET_BPS + 5_000) // 10_000
    if amount_cents > max_allowed_cents:
        raise BetValidationError(
            f"Bet amount ${amount:.2f} exceeds the maximum of "
            f"{MAX_BET_PCT:.0%} of your balance (${max_allowed_cents / 100:.2f})"
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
