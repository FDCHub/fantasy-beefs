"""
Creates the ledger_entries table in production. Wraps L2's
create_ledger_table() -- additive only, per its own docstring: "safe to
call repeatedly -- does not touch or inspect any other table."

No backfill. Confirmed 2026-07-10: every existing Wallet.balance row is
stale test-seed data ($50 flat across all 12 teams, contradicting the
schema's own default of $1000 -- neither figure reflects anything real).
No real buy-in has ever been confirmed through confirm_buyin_payment().
Wallets start clean at $0 (a valid, unfunded state per balance_of()'s
docstring) and fill correctly, per League.economy_stop_weekly_min_cents,
the moment each GM is actually confirmed this season.
"""
from ledger.ledger import create_ledger_table, trial_balance

if __name__ == "__main__":
    create_ledger_table()
    print("ledger_entries table created (or already existed).")

    balance = trial_balance()
    print(f"Trial balance: {balance} cents (expect 0 -- table is empty).")
    if balance != 0:
        print("WARNING: non-zero trial balance on an empty table. Investigate before proceeding.")
