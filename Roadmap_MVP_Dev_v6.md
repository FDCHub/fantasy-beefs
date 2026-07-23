# Fantasy Beefs — MVP Dev Roadmap v6

**Updated:** 2026-07-10 session.

---

## Session L-Deploy — Ledger primitive production deployment — ✅ COMPLETE 2026-07-10
- **Goal:** close the gap between L2 (built/tested locally) and production, which had never actually received the `ledger_entries` table.
- **Build:** `db/migrations/migrate_ledger_entries.py` (wraps L2's existing `create_ledger_table()`, additive), run against production via Railway/Postgres subshell. Verified via `check_drift.py`: 0/12 teams with drift, $0.00 total delta. Stale legacy `Wallet.balance` test data ($50 flat, all 12 teams — confirmed dead seed scaffolding, not real data) zeroed out.
- **Also produced:** `.railwayignore`, preventing `backup_final.sql` and scratch scripts from ever shipping in a deploy.
- **Exit:** ✅ MET. Ledger is live, clean, verified, ready for real buy-in confirmations.

## Session PCM — Pool Config Integer-Cent Migration — ✅ SPEC CERTIFIED (Rev 7), 🟡 BUILD NOT STARTED
- **Goal:** eliminate float-dollar exposure throughout the pool subsystem (`PoolConfig`, `PoolPot`, `pool_engine.py`'s full `settle_pool()`), converting to integer cents end-to-end and routing all pool-entry/payout postings through the ledger. Started as the narrower Finding 5.6a (two mutation-site swap) and expanded through recon into the full migration below.
- **Design decisions locked (Rev 7):**
  - New continuous per-league ledger account `pool:{league_id}` (Option A over per-week accounts) — rollover carries naturally as retained ledger balance, no explicit inter-week transfer needed.
  - Predictor-only payout on no-winner Worst Beat weeks (not all 12 teams) — a GM who paid the flat entry but never predicted doesn't share a prediction-pool payout they didn't participate in.
  - Shared rollover toggle across Worst Beat and Bench Burn (once the latter is built) — one flag, not two.
  - Week-14 unclaimed rollover sweeps to `championship:{league_id}`, correctly league-scoped from creation — the jackpot mechanic (final-week winner collects the full accumulated rollover) is explicitly the intended design, not an emergent surprise.
  - Migration gate is stop-agnostic: verifies each row against its own correctly-converted old value, not a hardcoded constant — catches a real conversion bug regardless of which of the five economy stops a league is on.
  - Single-deploy cutover: schema + backfill + verification gate + old-column drop, all one transaction, all one deploy. No dual-write transition window (justified by solo-dev, single-instance scale).
  - Temporary dual-key bridge added to 5.2's `execute_payouts()`/`preview_payouts()`, since the migration's correctly-scoped new writers would otherwise be invisible to the still-bare-string-reading payout calculation (cross-references Finding 5.5).
- **Build status:** migration script (`db/migrations/migrate_pool_cents.py`) written and reviewed by Claude Code — schema changes additive, compiles clean, correctly refuses a non-Postgres target. **Not run against production.** `pool_engine.py`, `api/pool_routes.py`, and the 5.2 bridge are **not yet converted** — this is the literal next session's first task, per the three-step sequencing in the v41 handoff.
- **Opus gate:** money-path — CERTIFIED, unconditional, across seven revision rounds (PCM-1 through PCM-17, all closed).
- **Exit:** NOT YET MET. Spec certified; build pending.

## Reg Season Bet Min/Max — Rev 6, CERTIFIED-CONDITIONAL → clears to unconditional once PCM builds
- **Condition:** "5.6 lands and debits `wallet:{team_id}` specifically" — satisfied by the PCM migration's `pool_entry_collected` door design, but only once that migration actually deploys, not merely once it's specced.
- **Build status:** zero code written. Blocked dependents once unblocked: GM pre-bet limit notification, My Action BAB display.

---

## Everything else unchanged from Roadmap v5 unless superseded above.
