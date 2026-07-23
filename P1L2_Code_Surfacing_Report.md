# P1-L2 READ-ONLY CODE SURFACING — OPUS MONEY-PATH REVIEW INPUT

**Repository:** `C:\Users\frase\OneDrive\PycharmProjects\fantasy-beefs`
**Branch / HEAD:** `remediation/foundation-phase-1 @ 77fd23c3ef6ce8f30af66fa5f4406e7e76e55758`
**Pass type:** READ-ONLY source inspection. No files edited. No DB writes. No migration. P1-L2 NOT authorized, NOT implemented.

**Scope recap.** P1-L2 routes three off-ledger `.balance` writes through the ledger primitive:
- `wallet/wallet_manager.py:141` — deposit credit
- `wallet/faab_wallet.py:663` — transfer bet→waiver debit
- `wallet/faab_wallet.py:679` — transfer waiver→bet credit

Plus scope-adjacent context (NOT in P1-L2 scope): the single-party settlement credit at `betting/settlement_engine.py:715`.

---

## 1. FULL FUNCTION BODIES

### 1a. `wallet_manager.deposit()` — `wallet/wallet_manager.py:133-150`

```python
def deposit(wallet_id: int, amount: float, db: Session) -> WalletState:
    """Credit wallet and write a deposit transaction."""
    if amount <= 0:
        raise ValueError("Deposit amount must be positive")
    if amount > 1_000_000:
        raise ValueError("Deposit amount exceeds maximum of $1,000,000")

    w = _get_wallet(wallet_id, db)
    w.balance = round(w.balance + amount, 2)          # <-- :141 off-ledger .balance WRITE
    db.add(Transaction(
        wallet_id  = wallet_id,
        amount     = amount,
        type       = "deposit",
        created_at = datetime.now(timezone.utc),
    ))
    db.commit()                                        # <-- OWNS + COMMITS its own transaction
    db.refresh(w)
    return _wallet_state(w, db)
```

**Transaction boundary:** `deposit()` receives a `Session` (`db`) but **commits it itself** (`db.commit()` at line 148). It does not open the session — the caller supplies it — but it unconditionally commits, so any caller that supplied an open transaction has that transaction committed inside `deposit()`.

**`.balance` reads/writes inside:** one read + one write, combined at line 141 (`w.balance = round(w.balance + amount, 2)`). The read (`_wallet_state → w.balance` at line 119) after `db.refresh(w)` is a read-only snapshot for the return value.

**Ledger / transaction-log call:** **ABSENT.** No `ledger.post`, no `ledger_post`, no `balance_of` import or call anywhere in `wallet/wallet_manager.py`. Search performed: `grep -n "ledger\|post\|balance_of" wallet/wallet_manager.py` → no ledger references (module imports only `db.schema`, `betting.exceptions`, `sqlalchemy.orm.Session`, see `wallet/wallet_manager.py:18-23`). The only audit artifact written is a `Transaction` row (the legacy `transactions` table, float dollars), lines 142-147.

---

### 1b. `faab_wallet.transfer()` — `wallet/faab_wallet.py:621-704`

```python
def transfer(
    team_id:      int,
    from_wallet:  str,
    to_wallet:    str,
    amount:       float,
    db:           Session,
    performer_id: Optional[int] = None,
) -> TransferResult:
    """
    Move funds between a GM's bet and waiver wallets.

    from_wallet / to_wallet : "bet" | "waiver"
    Subject to FaabConfig.allow_bet_to_waiver / allow_waiver_to_bet.
    """
    if from_wallet not in ("bet", "waiver") or to_wallet not in ("bet", "waiver"):
        raise ValueError("wallet must be 'bet' or 'waiver'")
    if from_wallet == to_wallet:
        raise ValueError("from_wallet and to_wallet must differ")
    if amount <= 0:
        raise ValueError("Transfer amount must be positive")

    fw  = _get_faab_wallet(team_id, db)
    cfg = db.query(FaabConfig).filter(FaabConfig.league_id == fw.league_id).first()

    # Check transfer direction allowed
    if from_wallet == "bet" and to_wallet == "waiver":
        if cfg and not cfg.allow_bet_to_waiver:
            raise ValueError("Bet → Waiver transfers are disabled by the commissioner")
        # Source: betting wallet (via wallet_manager.withdraw equivalent)
        bet_wallet = _get_bet_wallet(team_id, db)
        open_bets  = db.query(Bet).filter(
            Bet.wallet_id == bet_wallet.id, Bet.status == "pending"
        ).all()
        pending_exp        = round(sum(b.amount for b in open_bets), 2)
        ch_reserved = _challenge_reserved(team_id, db)
        available   = round(bet_wallet.balance - pending_exp - ch_reserved, 2)   # <-- :656 available-balance GATE
        if amount > available:
            raise ValueError(
                f"Cannot transfer ${amount:.2f}: only ${available:.2f} is available "
                f"(${bet_wallet.balance:.2f} balance, ${pending_exp:.2f} in pending bets, "
                f"${ch_reserved:.2f} reserved for pending challenges)"
            )
        bet_wallet.balance      = round(bet_wallet.balance - amount, 2)   # <-- :663 off-ledger .balance WRITE (debit bet)
        fw.waiver_balance       = round(fw.waiver_balance + amount, 2)    # <-- :664 waiver_balance WRITE (credit waiver)
        fw.updated_at           = _now()
        tx_type = "transfer_bet_to_waiver"

    else:  # waiver → bet
        if cfg and not cfg.allow_waiver_to_bet:
            raise ValueError("Waiver → Bet transfers are disabled by the commissioner")
        if amount > fw.waiver_balance:                                     # <-- waiver-side balance GATE
            raise ValueError(
                f"Insufficient waiver balance: ${fw.waiver_balance:.2f} available, "
                f"${amount:.2f} requested"
            )
        bet_wallet              = _get_bet_wallet(team_id, db)
        fw.waiver_balance       = round(fw.waiver_balance - amount, 2)    # <-- :677 waiver_balance WRITE (debit waiver)
        fw.updated_at           = _now()
        bet_wallet.balance      = round(bet_wallet.balance + amount, 2)   # <-- :679 off-ledger .balance WRITE (credit bet)
        tx_type = "transfer_waiver_to_bet"

    _log_tx(db, fw.league_id, team_id, tx_type, amount,
            wallet_from=from_wallet, wallet_to=to_wallet,
            note=f"${amount:.2f} from {from_wallet} to {to_wallet}",
            applied_at=_now())

    # Check if bet wallet is now zero after a bet→waiver transfer
    if tx_type == "transfer_bet_to_waiver":
        _check_and_freeze(team_id, fw, bet_wallet, db)
    else:
        _unfreeze_if_funded(team_id, fw, bet_wallet, db)

    db.commit()                                                           # <-- OWNS + COMMITS its own transaction
    db.refresh(fw)
    db.refresh(bet_wallet)

    return TransferResult(
        team_id              = team_id,
        from_wallet          = from_wallet,
        to_wallet            = to_wallet,
        amount               = amount,
        bet_balance_after    = round(bet_wallet.balance, 2),
        waiver_balance_after = round(fw.waiver_balance, 2),
    )
```

**Funding-decision / validation logic:**
- **bet→waiver gate** at `:651-662`: computes `available = bet_wallet.balance - pending_exp - ch_reserved` (line 656), rejecting when `amount > available`. This deducts pending bet exposure and pending challenge reservations from the raw `.balance`.
- **waiver→bet gate** at `:671-675`: simple `amount > fw.waiver_balance` check against the raw waiver balance (no exposure/reservation deduction).

**Both `.balance` mutation sites (the two P1-L2 targets):**
- `:663` `bet_wallet.balance = round(bet_wallet.balance - amount, 2)` (bet-wallet debit; paired with `:664` `fw.waiver_balance += amount`)
- `:679` `bet_wallet.balance = round(bet_wallet.balance + amount, 2)` (bet-wallet credit; paired with `:677` `fw.waiver_balance -= amount`)

Note both directions touch **two** balance columns each — the `wallets.balance` float (the P1-L2 target line) AND the `faab_wallets.waiver_balance` float. Only the `wallets.balance` sites (`:663`, `:679`) are named in P1-L2 scope; the paired `waiver_balance` writes (`:664`, `:677`) are the counter-legs.

**Logging:** a `FaabTransaction` row IS written — via `_log_tx(...)` at `:682-685`, `type` = `transfer_bet_to_waiver` | `transfer_waiver_to_bet`, on the `faab_transactions` table (float dollars). `_log_tx` (`wallet/faab_wallet.py:105-136`) only does `db.add(tx)` — it does not flush/commit.

**Ledger call:** **ABSENT.** No `ledger.post`/`ledger_post`/`balance_of` in `wallet/faab_wallet.py`. Search: `grep -n "ledger\|balance_of\|post(" wallet/faab_wallet.py` → module imports (`wallet/faab_wallet.py:36-51`) pull in `db.schema`, `db.deps`, `auth.jwt_auth`, `payments.stripe_connect`, and `wallet.wallet_manager` (`deposit as wm_deposit`, `_challenge_reserved`) only. No ledger primitive.

**Commit / flush / session behavior:** `transfer()` receives `db` from the caller and **commits it itself** at `:693` (`db.commit()`), then `db.refresh(fw)` / `db.refresh(bet_wallet)`. `_log_tx` adds but does not flush; the freeze helpers (`_check_and_freeze` / `_unfreeze_if_funded`) mutate flags in-session without committing (the enclosing `transfer` commit covers them).

---

### 1c. Settlement single-party credit — `betting/settlement_engine.py:715` (context only, NOT P1-L2 scope)

**Enclosing function:** `settle_week(week, db, league_id, recovery_token=None)` — `betting/settlement_engine.py:316-813`. The `.balance` write at `:715` is inside the per-bet loop, in the **single-party** branch (straight / spread / over_under / prop / the_lineup). The matched-**beef** branch immediately above (`:531-674`) is already ledger-routed via `ledger_post(...)` and is NOT an off-ledger `.balance` write.

**Imports (`betting/settlement_engine.py:34-37`):**
```python
from db.schema import Bet, BeefChallenge, Matchup, Projection, SettlementRecoveryAudit, Transaction, Wallet
from db.roster_read import _roster_for_week
from feed.league_feed import log_settlement_events
from ledger.ledger import post as ledger_post, balance_of, _balance_of_in_session
```
So the ledger primitive IS imported into this module and IS used — but only by the beef branch. The single-party branch is not.

**The single-party credit region — `betting/settlement_engine.py:708-736`:**
```python
        # -----------------------------------------------------------------

        bet.status     = status
        bet.settled_at = now

        wallet = wallets[bet.wallet_id]
        if status in ("won", "push"):   # push returns stake; won returns stake+profit
            wallet.balance = round(wallet.balance + payout, 2)   # <-- :715 off-ledger .balance WRITE (single-party)
            db.add(Transaction(
                wallet_id  = bet.wallet_id,
                amount     = payout,
                type       = "payout",
                bet_id     = bet.id,
                created_at = now,
            ))

        settlements.append(BetSettlement(
            bet_id      = bet.id,
            bet_type    = bet.bet_type,
            description = bet.description or "",
            wallet_id   = bet.wallet_id,
            owner       = wallet.team.owner,
            team_name   = wallet.team.team_name,
            amount      = bet.amount,
            odds_dec    = bet.odds,
            payout      = payout,
            profit      = profit,
            status      = status,
        ))
```

**Transaction boundary of `settle_week`:** the function drives the whole settlement transaction itself. Two commits:
- **Commit #1** — the claim: `INSERT ... ON CONFLICT DO NOTHING RETURNING id` then `db.commit()` at `:360` (WeekSettlement claim, committed alone before any payout).
- Phase-2 acquires a `SELECT ... FOR UPDATE` row lock (`:435-442`, open transaction held to the end).
- All per-bet payouts (including the `:715` write and the beef-branch `ledger_post` calls) are staged in that same open transaction.
- The `UPDATE week_settlements SET status='COMPLETED' ...` flip (`:746-766`), then **Commit #2** at `:780` (`db.commit()`), commits payouts + completion flip atomically. On flip `rowcount != 1` it routes through `_abort_phase2` (`:425-427`, `db.rollback()` then raise) so payouts roll back.

So the `:715` `.balance` write commits (or rolls back) as part of Commit #2, under the FOR-UPDATE lock. The single-party payout writes both a mutated `wallet.balance` (float) AND a `Transaction` row; it does **not** post to the ledger.

---

## 2. LEDGER PRIMITIVE — `ledger/ledger.py`

### 2a. `post()` — `ledger/ledger.py:223-310` (+ shared checks/writer `_run_checks_and_write` `:163-220`)

```python
def post(
    entries: list[tuple[str, int]],
    door: str,
    session: Session | None = None,
) -> uuid.UUID:
    """
    Atomically write one posting — a balanced set of ledger entries sharing
    one new posting_id — after three checks, in order, all before any write:

      a. entries must sum to exactly zero (LedgerImbalanceError if not).
      b. MS-L1-5.1 — for every account being debited (negative amount_cents)
         in this posting, its balance after this posting must not go
         negative (InsufficientFundsError if it would). Applies to every
         door, not just wager placement — EXCEPT "world" and "receivable:*"
         accounts, which represent capital flowing into/out of the ledger
         from outside it (real bank/Stripe transactions, or IOUs owed by a
         team) and are not bounded pools. Door 1 (buy_in_paid) debits
         "world" from 0, and Door 2 (buy_in_tab) debits "receivable:{team}"
         from 0 — both go negative by design, not by error. Every other
         account (wallet:*, escrow:*, reserve:*, championship, skunk) is a
         real accumulated pool and stays fully guarded.
      c. MS-L1-5.2 — if door == "wager_settled", every escrow:* account
         being debited must have a nonzero CURRENT balance before this
         posting applies (AlreadySettledError if it's already 0 — this
         bet has already been settled).

    Implementation note: for door == "wager_settled" specifically, (c) is
    evaluated before (b) in code — an escrow account already at 0 always
    also fails (b)'s generic test, so checking (b) first would make (c)
    unreachable and a repeated settlement would surface as a generic
    InsufficientFundsError instead of the more specific AlreadySettledError.
    Every other debited account, and every other door, is unaffected.

    session=None (default): post() opens its own SessionLocal(), runs all
    checks and the write against it, and commits internally before
    returning — this is the original L2 behavior, unchanged.

    session=<a Session>: post() runs the exact same checks (same ordering,
    same exemptions) and the same write against the CALLER's session
    instead of opening its own, and does NOT call commit() — the caller
    owns and commits (or rolls back) that transaction. This lets a caller
    like beefs/beef_engine.py's respond_to_challenge() — which commits
    once, covering both sides of an accepted beef plus a challenge status
    flip, as one atomic unit — post through the ledger as part of that
    same atomic unit instead of the ledger silently committing early on
    its own and breaking that atomicity. Because it's the same session,
    the funded-balance and once-only-settlement reads also see any of the
    caller's own uncommitted writes earlier in that same transaction.

    Either way, (b) and (c) read balances inside the same transaction as
    the write (not as separate earlier queries), and — on Postgres, and
    only on the session=None path where post() opens its own connection —
    that transaction runs at REPEATABLE READ, so a concurrent posting
    against the same account can't land between the check and the commit
    and produce a stale read (same pattern already used in
    beefs/beef_engine.py's respond_to_challenge()). On the session=provided
    path, isolation level is the caller's responsibility — the caller
    already owns the transaction and may already have set its own
    isolation level before ever calling post().

    Returns the new posting_id either way — on the session=None path only
    after a successful commit; on the session=provided path, once the
    entries are written to that session (still uncommitted).
    """
    total = sum(amount for _, amount in entries)
    if total != 0:
        raise LedgerImbalanceError(
            f"Posting for door {door!r} does not balance: entries sum to "
            f"{total} cents, not zero. Entries: {entries}"
        )

    posting_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    if session is not None:
        _run_checks_and_write(session, entries, door, posting_id, now)
        return posting_id

    with SessionLocal() as db:
        # Elevated isolation for Postgres only — see docstring above.
        # Only applies here, where post() opens its own connection.
        if db.get_bind().dialect.name != "sqlite":
            db.connection(execution_options={"isolation_level": "REPEATABLE READ"})

        _run_checks_and_write(db, entries, door, posting_id, now)
        db.commit()

    return posting_id
```

**Entries argument shape:** `entries: list[tuple[str, int]]` — a list of `(account, amount_cents)` pairs, integer signed cents, positive = credit, negative = debit. `door: str` audit tag. `session: Session | None` — when provided, `post()` joins the caller's transaction and does **not** commit (caller owns commit); when `None`, `post()` opens its own `SessionLocal()`, elevates to REPEATABLE READ on non-SQLite, and commits internally.

**Zero-sum enforcement:** `:287-292` — `total = sum(amount ...)`; if `total != 0`, raise `LedgerImbalanceError`, nothing written.

**Funded-balance guard (the `:198-209` block, inside `_run_checks_and_write`):**
```python
    # (b) MS-L1-5.1 — funded-balance guard, every door, every debited account,
    # except "world" and "receivable:*" — see docstring above for why these
    # two are exempt (unbounded external/IOU accounts, not real pools).
    for account, amount in entries:
        if amount < 0 and account != "world" and not account.startswith("receivable:"):
            current = _balance_of_in_session(db, account)
            if current + amount < 0:
                raise InsufficientFundsError(
                    f"Posting for door {door!r} would take {account!r} to "
                    f"{current + amount} cents (current {current}, debit {amount}) "
                    f"— insufficient funds. Posting rejected, nothing written."
                )
```

**Full `_run_checks_and_write` — `ledger/ledger.py:163-220`:**
```python
def _run_checks_and_write(
    db: Session,
    entries: list[tuple[str, int]],
    door: str,
    posting_id: uuid.UUID,
    now: datetime,
) -> None:
    """
    Runs checks (b) and (c) and writes (d) — see post()'s docstring for the
    full check semantics and ordering rationale. Shared by both of post()'s
    paths (its own session, or a caller-supplied one) so the checks and the
    write behave identically either way; does not commit — the caller (post())
    decides who owns and commits the transaction.
    """
    # (c) MS-L1-5.2 — once-only settlement guard, wager_settled doors only.
    # Deliberately checked BEFORE (b) below, for wager_settled postings
    # only: an escrow account already at 0 will ALWAYS also fail (b)'s
    # generic funded-balance test (debiting anything from a zero balance
    # is negative by definition), so if (b) ran first a repeated
    # settlement attempt would surface as a generic InsufficientFundsError
    # and this more specific, more diagnostic AlreadySettledError would
    # never actually be reachable. Checking (c) first for this one door
    # gives the caller the correct, specific reason without weakening (b)
    # — every other debited account in this same posting, and every
    # other door, still goes through the unmodified check below.
    if door == "wager_settled":
        escrow_debits = [a for a, amt in entries if amt < 0 and a.startswith("escrow:")]
        for escrow_account in escrow_debits:
            current = _balance_of_in_session(db, escrow_account)
            if current == 0:
                raise AlreadySettledError(
                    f"{escrow_account!r} is already at 0 cents — this bet has "
                    f"already been settled. Posting rejected, nothing written."
                )

    # (b) MS-L1-5.1 — funded-balance guard, every door, every debited account,
    # except "world" and "receivable:*" — see docstring above for why these
    # two are exempt (unbounded external/IOU accounts, not real pools).
    for account, amount in entries:
        if amount < 0 and account != "world" and not account.startswith("receivable:"):
            current = _balance_of_in_session(db, account)
            if current + amount < 0:
                raise InsufficientFundsError(
                    f"Posting for door {door!r} would take {account!r} to "
                    f"{current + amount} cents (current {current}, debit {amount}) "
                    f"— insufficient funds. Posting rejected, nothing written."
                )

    # (d) All checks passed — write every entry under the same posting_id,
    # in this one transaction. Commits together or not at all.
    for account, amount in entries:
        db.add(LedgerEntry(
            account=account,
            amount_cents=amount,
            posting_id=posting_id,
            door=door,
            created_at=now,
        ))
```

### 2b. `trial_balance()` — `ledger/ledger.py:150-160`

```python
def trial_balance() -> int:
    """
    Sum of amount_cents across every ledger entry, all accounts, all doors.
    Must always be exactly 0 — this is the continuous integrity check
    referenced throughout the L1 spec and the Launch Gate register.
    """
    with SessionLocal() as db:
        result = db.execute(
            text("SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries")
        ).scalar()
        return int(result)
```

### 2c. `balance_of()` — `ledger/ledger.py:108-115` (+ in-session variant `:89-105`)

```python
def balance_of(account: str) -> int:
    """
    Returns the current balance of `account` in integer cents.
    0 for an account with no entries yet — an unfunded wallet is a valid
    state (e.g. before Door 1 posts), not an error.
    """
    with SessionLocal() as db:
        return _balance_of_in_session(db, account)
```

```python
def _balance_of_in_session(db: Session, account: str) -> int:
    """Same query as balance_of(), but reusing an already-open session/
    transaction — used by post() so its funded-balance and once-only-
    settlement reads are part of the SAME transaction as the write below,
    not a separate earlier query that a concurrent posting could race past.

    EXPORTED entry point (FR-7.12): funds-check sites that read a balance
    immediately before a write in the SAME request transaction import this
    instead of balance_of() so the pre-check sees the same data the write
    will. The leading underscore is retained for continuity, but this is a
    supported cross-module import (see FR-7.12 §4). No caller precondition
    beyond ordinary autoflush, which is the codebase-wide default."""
    result = db.execute(
        text("SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries WHERE account = :account"),
        {"account": account},
    ).scalar()
    return int(result)
```

**How balance is currently derived from the ledger:** `balance_of(account)` = `SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries WHERE account = :account` — pure derived sum of integer cents, **no stored balance column in the ledger module.** (P1-L2's intent — making `Wallet.balance` a derived mirror — has NOT been implemented: the `wallets` table still carries an independent float `balance` column mutated directly by the three paths in §1. The ledger's own accounts are already derived; the `wallets`/`faab_wallets` tables are not yet reconciled to them.)

**Ledger money unit:** integer cents everywhere (`amount_cents = Column(BigInteger)`). No float represents money in `ledger/ledger.py`. This is a **unit mismatch** with the §1 paths, which mutate `.balance` as float dollars (`round(..., 2)`).

---

## 3. MODELS

### `Wallet` — `db/schema.py:188-198`
```python
class Wallet(Base):
    __tablename__ = "wallets"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    team_id    = Column(Integer, ForeignKey("teams.id"), nullable=False, unique=True)
    balance    = Column(Float,   nullable=False, default=1000.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    team         = relationship("Team",        back_populates="wallet")
    bets         = relationship("Bet",         back_populates="wallet")
    transactions = relationship("Transaction", back_populates="wallet")
```
> ⚠️ **`.balance` COLUMN TYPE: `Float`** (dollars), `nullable=False, default=1000.0`. NOT integer cents. This is the column written off-ledger at `wallet_manager.py:141`, `faab_wallet.py:663`, `faab_wallet.py:679`, and `settlement_engine.py:715`. The ledger primitive stores money as `BigInteger` cents — a type mismatch the P1-L2 review must reconcile.

### `FaabWallet` — `db/schema.py:505-519`
```python
class FaabWallet(Base):
    """Per-team FAAB wallet — waiver budget + bet-frozen flag."""
    __tablename__ = "faab_wallets"

    id                   = Column(Integer,  primary_key=True, autoincrement=True)
    team_id              = Column(Integer,  ForeignKey("teams.id"),    nullable=False, unique=True)
    league_id            = Column(Integer,  ForeignKey("leagues.id"),  nullable=False)
    waiver_balance       = Column(Float,    nullable=False, default=0.0)
    pending_waiver_topup = Column(Float,    nullable=False, default=0.0)  # queued for Tuesday
    bet_frozen           = Column(Integer,  nullable=False, default=0)    # 1 = frozen
    created_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    team   = relationship("Team")
    league = relationship("League")
```
> ⚠️ **`waiver_balance` COLUMN TYPE: `Float`** (dollars), `nullable=False, default=0.0`. NOT integer cents. This is the counter-leg column mutated at `faab_wallet.py:664` and `:677` (paired with the P1-L2 `wallets.balance` writes). `pending_waiver_topup` is also `Float`. FaabWallet has **no** `bet_balance` column — the "bet wallet" balance lives entirely in the `wallets` table; FaabWallet holds only waiver funds + the `bet_frozen` flag.

### `Transaction` — `db/schema.py:238-255`
```python
class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(
            "type IN ('deposit','withdrawal','bet','payout','pool_entry','pool_payout')",
            name="ck_tx_type",
        ),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    wallet_id  = Column(Integer, ForeignKey("wallets.id"), nullable=False)
    amount     = Column(Float,  nullable=False)   # positive = credit, negative = debit
    type       = Column(String, nullable=False)
    bet_id     = Column(Integer, ForeignKey("bets.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    wallet = relationship("Wallet", back_populates="transactions")
    bet    = relationship("Bet",    back_populates="transactions")
```
> `amount` is `Float` dollars. This is the legacy audit table `deposit()` / `transfer()` (indirectly, via the bet wallet) / `settle_week()` write to — separate from `ledger_entries`.

### `FaabTransaction` — `db/schema.py:522-557`
```python
class FaabTransaction(Base):
    """FAAB-specific audit trail — covers top-ups, transfers, bids, and alerts."""
    __tablename__ = "faab_transactions"
    __table_args__ = (
        CheckConstraint(
            "type IN ("
            "'opening_credit','topup_bet','topup_waiver',"
            "'transfer_bet_to_waiver','transfer_waiver_to_bet',"
            "'waiver_bid','waiver_refund','funding_alert')",
            name="ck_faab_tx_type",
        ),
        CheckConstraint(
            "status IN ('pending','applied','cancelled','failed')",
            name="ck_faab_tx_status",
        ),
        Index("ix_faab_tx_team_created", "team_id", "created_at"),
    )

    id               = Column(Integer,  primary_key=True, autoincrement=True)
    league_id        = Column(Integer,  ForeignKey("leagues.id"), nullable=False)
    team_id          = Column(Integer,  ForeignKey("teams.id"),   nullable=False)
    type             = Column(String,   nullable=False)
    amount           = Column(Float,    nullable=False, default=0.0)
    wallet_from      = Column(String,   nullable=True)   # "bet" | "waiver" | "stripe"
    wallet_to        = Column(String,   nullable=True)   # "bet" | "waiver"
    status           = Column(String,   nullable=False,  default="applied")
    note             = Column(String,   nullable=True)
    stripe_link_id   = Column(String,   nullable=True)
    stripe_link_url  = Column(String,   nullable=True)
    stripe_session_id = Column(String,  nullable=True)
    apply_on         = Column(DateTime, nullable=True)   # NULL = immediate; set for Tuesday queue
    applied_at       = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    team   = relationship("Team")
    league = relationship("League")
```
> `amount` is `Float` dollars. `transfer()` writes a row here with `type` in `transfer_bet_to_waiver` / `transfer_waiver_to_bet`.

### Ledger entry model — `LedgerEntry` — `ledger/ledger.py:45-66`
```python
class LedgerEntry(_LedgerBase):
    """
    One row per side of one posting. No stored balance anywhere — an
    account's balance is always SUM(amount_cents) WHERE account = :account,
    computed on demand by balance_of()/trial_balance().
    """
    __tablename__ = "ledger_entries"

    # SQLite only grants ROWID autoincrement to a column that compiles as
    # exactly INTEGER; BigInteger compiles to BIGINT there and silently gets
    # no autoincrement. Postgres keeps the real bigint PK via the variant.
    id           = Column(Integer().with_variant(BigInteger, "postgresql"), primary_key=True, autoincrement=True)
    account      = Column(String, nullable=False)
    # Signed integer cents. Positive = credit, negative = debit. Integer
    # cents ONLY — no float representation of money anywhere in this file
    # or its callers.
    amount_cents = Column(BigInteger, nullable=False)
    # Groups every entry in one atomic posting together.
    posting_id   = Column(Uuid, nullable=False)
    # Audit trail — which door produced this entry.
    door         = Column(String, nullable=False)
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))
```
> **`amount_cents` = `BigInteger` (signed integer cents).** Declared on a **separate `_LedgerBase = declarative_base()`** (`ledger/ledger.py:42`), NOT `db.schema.Base` — deliberately isolated so `db/schema.py` is untouched. `create_ledger_table()` (`:83-86`) creates only this one table. **Type contrast for the review: `ledger_entries.amount_cents` is `BigInteger` cents; `wallets.balance` and `faab_wallets.waiver_balance` are `Float` dollars.**

---

## 4. ALL CALLERS OF THE THREE MUTATION PATHS

Search commands: `grep -n "deposit(\|wm_deposit(" **/*.py`, `grep -n "transfer(\|faab_transfer" **/*.py`, `grep -n "settle_week(" **/*.py`.

### 4a. Callers of `wallet_manager.deposit()` (imported elsewhere as `wm_deposit`)

| # | Caller | File:line | Transaction context |
|---|--------|-----------|---------------------|
| 1 | `wallet_deposit` (FastAPI route `POST /wallet/deposit`) | `api/main.py:1003` | `db` from `Depends(get_db)` — a request-scoped `SessionLocal()` that `get_db` only `close()`s, never commits (`db/deps.py:6-11`). `deposit()` itself commits. No enclosing transaction the route holds open across other writes. |
| 2 | `init_season_wallets` (FAAB season init — **named reacher "faab init_season"**) | `wallet/faab_wallet.py:330` | Inside a per-team loop that has already `db.flush()`ed a new `FaabWallet` and called `_log_tx` (uncommitted). `wm_deposit(...)` at :330 then **commits the whole in-flight transaction** mid-loop (its `db.commit()`), including the pending FaabWallet insert and opening-credit log rows for that team. Loop then continues; final `db.commit()` at `faab_wallet.py:342`. ⚠️ deposit's internal commit crosses the caller's multi-row transaction boundary. |
| 3 | `create_bet_topup` (mock-mode immediate apply — **named reacher "create_bet_topup"**) | `wallet/faab_wallet.py:420` | Mock branch. `wm_deposit(bet_wallet.id, amount, db)` commits; then `_log_tx(...)` + `db.flush()` + `_unfreeze_if_funded(...)` + a second `db.commit()` at `:428`. So the FaabTransaction audit row for the top-up is written AFTER deposit's commit, in a second transaction. ⚠️ deposit's balance credit and its own audit row commit before the `topup_bet` FaabTransaction row exists. |
| 4 | `confirm_topup` (Stripe webhook / manual confirm, `topup_bet` branch) | `wallet/faab_wallet.py:553` | `wm_deposit(bet_wallet.id, tx.amount, db)` commits, then `_unfreeze_if_funded`, then sets `tx.status='applied'` / `tx.applied_at` and a further `db.commit()` at `:558`. Same two-commit shape as #3. |
| 5 | CLI demo (`__main__`) | `wallet/wallet_manager.py:250` | Dev script only, `with SessionLocal() as db:`. Not a production path. |

> A ledger write inserted into `deposit()` under P1-L2 would ride deposit's own `db.commit()` (line 148). For callers #2–#4 that supply an already-dirty session, that commit already flushes the caller's other pending rows — so a ledger posting added inside `deposit()` would commit together with whatever the caller had staged up to that point, in deposit's transaction, not the caller's final one. `session=db` would be the mechanism (post() joins the caller session and does not itself commit; deposit's existing `db.commit()` is what would persist it).

### 4b. Callers of `faab_wallet.transfer()`

| # | Caller | File:line | Transaction context |
|---|--------|-----------|---------------------|
| 1 | `faab_do_transfer` (FastAPI route `POST /faab/transfer`) | `api/main.py:1993` (imported as `faab_transfer` at `api/main.py:139`) | `db` from `Depends(get_db)` (request-scoped, `get_db` never commits — `db/deps.py`). `transfer()` owns and commits its own transaction at `faab_wallet.py:693`. No other writes wrapped by the route around it. The route just maps `TransferResult` → `TransferOut`. |

> Single production caller. A ledger posting added inside `transfer()` (both legs) would commit on `transfer()`'s own `db.commit()` at `:693` via `session=db`.

### 4c. Callers of the single-party settlement credit function (`settle_week`) — context only

| # | Caller | File:line | Transaction context |
|---|--------|-----------|---------------------|
| 1 | `settle_bets_week` (FastAPI route `POST /settle/...`) | `api/main.py:908` | `db` from `Depends(get_db)`. `settle_week` owns its own two-commit transaction (claim commit + payout/completion commit). |
| 2 | Tuesday automation `settle_bets` step | `notifications/tuesday_sync.py:823` | `settle_week(week, db, league_id=league_id)` inside the Tuesday-sync orchestrator; `settle_week` manages its own commits. |
| 3 | `recover_week` (authorized recovery rerun) | `betting/settlement_engine.py:1036` | Calls `settle_week(week, db, league_id, recovery_token=fresh_token)` after staging a recovery audit row on the same `db`; `settle_week` runs the `claimant_type="recovery"` path. |
| 4 | CLI demo `__main__` | `betting/settlement_engine.py:1050` | Dev script. |
| 5 | Feed demo script | `feed/league_feed.py:476` | Demo script, `league_id=1`. |

> The single-party `:715` credit is already inside `settle_week`'s FOR-UPDATE-locked Phase-2 transaction (Commit #2 at `:780`). The beef branch in the same loop already posts to the ledger via `ledger_post(..., session=db)`, so the wiring pattern for routing `:715` through the ledger in the same transaction already exists in-function — **but this is explicitly out of P1-L2 scope; surfaced for context only.**

---

## 5. TESTS

Search: `grep -rn "def test_\|deposit\|transfer\|settle_week\|Imbalance\|InsufficientFunds\|trial_balance" test_*.py`; full test inventory via `glob **/test_*.py` (23 files).

### 5a. `deposit()` — **NO direct execution coverage. ABSENT.**
- `test_wallet_balance_ledger.py` references deposit only in prose and constructs a **hand-built** `WalletState(balance=170.00, ...)` at `:144-148` to test the `_state_out` response builder (`:150-152`, `F1`). It asserts `_state_out` echoes the stale column value `$170.00` (the deliberate FR-7.28 exception) rather than the ledger `$140.33`. **It never calls `deposit()` / `wm_deposit()`** — the `.balance` write at `wallet_manager.py:141` is not exercised or asserted anywhere.
- Search: `grep -rn "deposit(" test_*.py` → only `wallet/wallet_manager.py:250` (the CLI, not a test) and prose mentions. No test invokes `deposit`.
- **Verdict: the deposit `.balance` write path has NO automated test coverage.**

### 5b. FAAB `transfer()` both directions — **NO coverage. ABSENT.**
- Search: `grep -rn "transfer" test_*.py` → matches only `test_beef_starters.py:434` ("transfer LV player from t5 to t6") which is a **roster** move, and `test_wallet_balance_ledger.py` (deposit prose). **No test imports or calls `faab_wallet.transfer` / `faab_transfer`.** Neither the bet→waiver (`:663`) nor waiver→bet (`:679`) mutation, nor the `:656` available-balance gate, nor the waiver-side gate, is asserted.
- **Verdict: both transfer directions have NO automated test coverage.**

### 5c. Single-party settlement credit (`settlement_engine.py:715`) — **NO direct coverage. ABSENT.**
- `test_settle_the_lineup.py` tests only the pure helper `_lineup_winner()` (header `:2`, prints `:188`); it does **not** call `settle_week()` and does not exercise the `.balance` credit.
- `test_beef_settlement_escrow_close_pg.py` DOES call `settle_week()` (`:178, :228, :264, :300`) but exclusively through the **beef (matched-escrow) branch** — every bet is created via `issue_challenge(..., bet_type="straight", ...)` (`:149`), i.e. matched beef bets that hit the `bet.beef_challenge_id is not None` branch (`settlement_engine.py:531`) and settle through `ledger_post`. Its assertions check the ledger-routed `Transaction` rows (`:197-200`, `:280-282`, etc.), **never** the single-party `:715` path. No test places a straight/spread/over_under/prop/the_lineup bet with `beef_challenge_id IS NULL` and settles it to assert the `wallet.balance += payout` credit.
- Search: `grep -rn "settle_week(" test_*.py` → only `test_beef_settlement_escrow_close_pg.py` (beef branch).
- **Verdict: the single-party payout `.balance` credit at `:715` has NO automated test coverage.**

### 5d. Ledger `post()` funded-balance guard and zero-sum — **COVERED.** `test_ledger.py`
Standalone assertion-style test (uses a local `_assert(label, condition, detail)` harness, not `pytest def test_*`). Relevant assertions:

- **Zero-sum / imbalance rejection** — `test_ledger.py:181-190`:
  - `:187` catches `LedgerImbalanceError` for a non-zero-sum posting.
  - `:189` `_assert("LedgerImbalanceError raised for non-zero-sum entries", raised)`.
  - `:190` `_assert("trial_balance unchanged after the rejected imbalance", trial_balance() == tb_before_imbalance, ...)` — proves nothing was written.
- **Funded-balance guard (MS-L1-5.1)** — `test_ledger.py:146-157`:
  - `:154` catches `InsufficientFundsError` on an over-debit.
  - `:156` `_assert("InsufficientFundsError raised for over-debit", raised)`.
  - `:157` `_assert("trial_balance unchanged after the rejected posting", trial_balance() == tb_before, ...)`.
- **Once-only-settlement guard (MS-L1-5.2, `AlreadySettledError`)** — `test_ledger.py:170-177`: asserts the rejected repeat raises and `:177` `trial_balance()` unchanged. (Imports `AlreadySettledError` at `:32`.)
- **`trial_balance() == 0` invariant** asserted after every door: `:62, :73, :77, :87, :113, :124, :132, :143, :203, :214, :236, :248`.
- **`session=`-provided commit/rollback semantics** — `:226-236` (caller-owned commit reflected) and `:239-248` (rolled-back posting leaves `trial_balance` unchanged).
- Imports under test — `test_ledger.py:28-32`: `post`, `trial_balance`, `balance_of`, `LedgerImbalanceError`, `InsufficientFundsError`, `AlreadySettledError`.
- **Verdict: the ledger primitive's zero-sum and funded-balance guards ARE well covered — but ONLY at the primitive level, on `ledger_entries` accounts. There is no test asserting that any of the three P1-L2 `.balance` paths post to the ledger (because they do not yet), so once P1-L2 is implemented these guard tests would NOT retroactively cover the deposit/transfer/settlement call sites.**

### Test coverage summary

| Path | Test coverage | Evidence |
|------|---------------|----------|
| `deposit()` `.balance` write (`wallet_manager.py:141`) | **ABSENT** | No test calls `deposit()`; `test_wallet_balance_ledger.py` only tests `_state_out` on a hand-built state |
| `transfer()` bet→waiver (`:663`) | **ABSENT** | No test references `faab_transfer`/`transfer()` |
| `transfer()` waiver→bet (`:679`) | **ABSENT** | Same |
| single-party settlement credit (`:715`) | **ABSENT** | `settle_week` tests exercise only the beef/ledger branch |
| ledger `post()` zero-sum | **COVERED** | `test_ledger.py:181-190` |
| ledger `post()` funded-balance guard | **COVERED** | `test_ledger.py:146-157` |
| ledger `post()` once-only-settlement | **COVERED** | `test_ledger.py:170-177` |

---

## Cross-cutting observations for the review (surfaced, not acted on)

1. **Unit mismatch.** All three P1-L2 target columns (`wallets.balance`, `faab_wallets.waiver_balance`) are `Float` dollars; the ledger stores `BigInteger` cents. Routing these writes through `post()` requires a dollars→cents conversion at each site (`ledger._dollars_to_cents` at `ledger/ledger.py:129-147` exists and rejects sub-cent amounts; `_to_cents` at `:118-126` rounds).
2. **Commit ownership.** `deposit()` and `transfer()` each call `db.commit()` themselves. `post(session=db)` deliberately does NOT commit — so a ledger posting added inside them would persist on their existing internal commit, joining whatever the caller had already staged. The `init_season_wallets` / `create_bet_topup` / `confirm_topup` callers rely on deposit's mid-flow commit (§4a #2–#4), which already crosses their own multi-row transactions.
3. **Counter-leg accounts.** `transfer()` moves value between `wallets.balance` and `faab_wallets.waiver_balance`. A balanced ledger posting needs a ledger account for the waiver side (e.g. `waiver:{team}`) as the counter-leg to `wallet:{team}` — no such account name currently appears in the ledger doors.
4. **The beef branch is already ledger-routed** (`settlement_engine.py:558-565, 604-612` via `ledger_post(..., session=db)`), so an in-function precedent for `session=db` posting under `settle_week`'s FOR-UPDATE transaction exists — relevant to the scope-adjacent `:715` credit only.

---

*END OF READ-ONLY SURFACING PASS. No repository source, schema, migration, test, environment, or production data was modified. P1-L2 was not authorized, prepared, or implemented.*

---

## VAL-9a PROVENANCE — verbatim citations

Each line below was re-read live from source at `remediation/foundation-phase-1 @ 77fd23c` and quoted exactly as it appears (not copied from any prior summary). No line differed from its expected description; all five verified as-is.

**1. `betting/settlement_engine.py:561` — the `wallet:{team_id}` push-leg string**
```python
561:                            (f"wallet:{side_wallet.team_id}",  side_escrow_cents),
```

**2. `betting/settlement_engine.py:608` — the `wallet:{team_id}` won/lost-leg string**
```python
608:                        (f"wallet:{winner_wallet.team_id}",  combined_credit_cents),
```

**3. `betting/settlement_engine.py:515` — the `wallets = {w.id: w ...}` dict (wallet_id → Wallet resolution)**
```python
515:    wallets       = {w.id: w for w in db.query(Wallet).filter(Wallet.id.in_(wallet_ids)).all()}
```

**4. `wallet/wallet_manager.py:80-84` — `_get_wallet` body (`WHERE Wallet.id == wallet_id`)**
```python
80:def _get_wallet(wallet_id: int, db: Session) -> Wallet:
81:    w = db.query(Wallet).filter(Wallet.id == wallet_id).first()
82:    if not w:
83:        raise ValueError(f"Wallet {wallet_id} not found")
84:    return w
```

**5. `test_roster_slots_capture.py:127-129` — the insertion-order ID-space fixture (Yahoo 3 → DB 11, not +10)**
```python
127:    # Insertion order (Yahoo 3, 1, 2) → DB ids 11, 12, 13.
128:    #   Yahoo 3 -> DB 11 | Yahoo 1 -> DB 12 | Yahoo 2 -> DB 13
129:    # +10 arithmetic would say Yahoo 1 -> DB 11, which is WRONG here.
```

*Verification note: all five lines match their VAL-9a descriptions verbatim — no discrepancies to flag.*
