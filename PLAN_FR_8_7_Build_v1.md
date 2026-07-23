# FR-8.7 — Claude Code Build Plan (Rev 5)

**Controlling spec:** `FR_8_7_SETTLEMENT_CLAIM_FIRST_MODULE_SPEC_Rev5.md` (build-ready, 3 Opus rounds cleared).
**Scope:** Option 3 minimal lifecycle. `betting/settlement_engine.py` + one migration + one recovery function + tests.
**Hard gate:** NO production migration, NO `railway up --service fantasy-beefs`, NO deploy until implementation + tests are reviewed by Fraser. All work lands local + committed to a branch first. This plan is the work order; it is not authorization to deploy.
**Machine/tool for every step below:** ThinkPad X13 — PyCharm terminal (Claude Code CLI), unless stated otherwise.

---

## Sequencing principle

Build in dependency order, seam-locked. Each step's interface is fixed before the next depends on it. Money-path steps (2–5) are one reviewable unit — do not commit a half-wired `settle_week`. Tests (step 7) are written against the finished money path, then the whole batch is reviewed before anything touches production.

Suggested branch: `fr-8.7-settlement-claim-first`. Confirm `git status` clean and `master` at `6da6dca` synced before branching.

---

## Step 0 — Pre-build recon (existence-check gate)

Before writing a line, re-confirm against live code (the spec's grep was 2026-07-19; verify nothing shifted):

- `betting/settlement_engine.py` — `settle_week` signature at line 310, commit #1 at 345, commit #2 at 592, FR-5.9 comment 330–335.
- `db/schema.py` — `WeekSettlement` at 890–905; confirm current columns are exactly `id, league_id, week, settled, settled_at`.
- Grep every reader of `WeekSettlement.settled` / `week_settlements.settled` across the repo. Record the list — step 8 must prove it goes to zero authoritative reads.
- Confirm the migration mechanism in use (Alembic? raw SQL migration script? how prior column adds were done — match the existing pattern, do not introduce a new one).

Output: a short recon note confirming line numbers still hold or flagging drift. **If drift, stop and report — do not build against stale numbers.**

---

## Step 1 — Migration: add `status` and `recovery_token`

**Depends on:** Step 0 (migration mechanism confirmed).

Add two columns to `week_settlements`, matching the repo's existing migration pattern:
- `status` — `String`, `NOT NULL`, `DEFAULT 'CLAIMED'`.
- `recovery_token` — `String`, `NULL`able.

Also update the `WeekSettlement` model in `db/schema.py` to declare both columns.

Constraints:
- Do NOT touch `uq_week_settlement_league_week`.
- Do NOT drop `settled` (retained-but-unread until a later cleanup finding).
- Migration must be reversible (down-migration drops the two columns).
- Table is empty in production (FR-5.13) — no backfill needed; the default covers any row appearing between migration and deploy.

**Seam locked after this step:** the two new columns exist in the model. Steps 2–6 code against them.

**Gate:** migration written and runnable against a LOCAL/test DB only. NOT run against production.

---

## Step 2 — `settle_week` signature + Phase 1 token branch

**Depends on:** Step 1 (columns exist in model).

Change the signature to `settle_week(week, db, league_id, recovery_token=None)`.

Rewrite the Phase-1 claim block (around 336–353) per spec §3 Phase 1:
- INSERT ... ON CONFLICT DO NOTHING RETURNING id, writing `status='CLAIMED'` (and `settled=FALSE` for back-compat), commit #1 unchanged in position.
- Row returned → normal fresh claimant → Phase 2.
- Conflict → read `status` + `recovery_token`, branch:
  - `COMPLETED` → return idempotent no-op report.
  - `CLAIMED` + `recovery_token is None` supplied → STOP, "manual recovery required."
  - `CLAIMED` + supplied token MATCHES row token → recovery claimant → Phase 2.
  - `CLAIMED` + supplied token MISMATCH (or row token NULL while caller holds one) → STOP.

Carry a flag/enum through to Phase 2 indicating normal-vs-recovery claimant (so step 4's revalidation knows which assertion to apply).

---

## Step 3 — Phase 2 `FOR UPDATE` lock + token revalidation

**Depends on:** Step 2 (claimant type known entering Phase 2).

At the very start of Phase 2 (before any payout write), per spec §3 Phase 2 steps 1–2:
- `SELECT * FROM week_settlements WHERE league_id=:lid AND week=:wk FOR UPDATE` on `db`. Held to commit/rollback.
- Revalidate under the lock:
  - Normal claimant → assert `status=='CLAIMED'` AND `recovery_token IS NULL`.
  - Recovery claimant → assert `status=='CLAIMED'` AND `recovery_token == handed_token`.
  - Any mismatch / forbidden-present / required-missing / `status=='COMPLETED'` → abort + rollback before money moves (COMPLETED → return no-op report).

**Critical:** no payout, ledger post, wallet mutation, or status flip may execute before the lock is acquired and revalidation passes. Order is load-bearing.

---

## Step 4 — Payout loop untouched; atomic `COMPLETED` + token clear

**Depends on:** Step 3.

- The payout loop body (355–590) stays functionally as-is — do NOT alter payout math, escrow sourcing, or the live FR-5.9/5.10 fixes. It already runs on `session=db` (grep-confirmed); leave it.
- Replace commit #2's precursor (the old implicit completion) with the explicit flip, per §3 step 4:
  `UPDATE week_settlements SET status='COMPLETED', settled_at=now, settled=TRUE, recovery_token=NULL WHERE league_id=:lid AND week=:wk AND status='CLAIMED'`.
  Zero rows affected → abort + rollback (defensive backstop under lock).
- `db.commit()` at 592 now lands payouts + COMPLETED + token-clear atomically.

**Seam locked after steps 2–4:** the money path is complete and single-transaction. This is the reviewable money-path unit — do not commit it half-wired.

---

## Step 5 — Controlled audited recovery function

**Depends on:** Steps 2–4 (the rerun it invokes must be finished).

New function (name/loc TBD — propose alongside; likely a `recover_week()` in `betting/settlement_engine.py` or a dedicated recovery module). Implements spec §5b nine-step sequence:
1. **Operational precondition (OUTSIDE the DB, before txn):** require caller to pass explicit exit-evidence (process/container exited / failed job-runner record / operator-kill-confirmed). NOT "slow." Function refuses to proceed without it. (Design the interface so this can't be skipped — e.g. a required `exit_evidence` argument that is recorded, not a boolean flag.)
2. Begin transaction.
3. `SELECT ... FOR UPDATE` the row.
4. Require `status=='CLAIMED'` (abort if COMPLETED).
5. Verify no Phase-2 effects committed — bets still `pending`, escrow balances intact.
6. Write immutable recovery audit record: actor, week, timestamp, observed pre-state, exit-evidence.
7. Generate fresh `recovery_token` (uuid4), write to row. `status` stays `CLAIMED`. Row never absent.
8. Commit.
9. Invoke `settle_week(..., recovery_token=<the fresh token>)` as the authorized recovery claimant.

Handle the crashed-recovery case per §5b MS-8.7-8: a later recovery on a `CLAIMED`+non-null-token row overwrites the old token with a fresh one under lock (after step-1 exit evidence). No special-casing needed — the overwrite is the same step 7.

**Where does the audit record live?** Propose: a `settlement_recovery_audit` table or append to an existing audit/event log — match whatever `log_settlement_events` already uses if suitable. Flag for Fraser: new table vs. reuse.

---

## Step 6 — Failure-injection tests

**Depends on:** Steps 1–5 complete.

Tests run on SQLite local (per repo test convention `DATABASE_URL=sqlite:///...`), EXCEPT any test asserting `FOR UPDATE` / true row-lock concurrency semantics, which must run against a **local Postgres** instance — SQLite does not enforce `SELECT ... FOR UPDATE` row locks the same way, so a concurrency test on SQLite proves nothing. Flag this split explicitly; mark Postgres-required tests.

Each scenario asserts BOTH ledger integrity (trial balance sums to zero, no double-pay, no lost payout) AND lifecycle state (`status`, `recovery_token`, bet statuses):

1. **Crash after claim (before Phase 2):** simulate process death after commit #1. Assert row = `CLAIMED`, token NULL, zero payouts committed, all bets still `pending`. Then a normal retry STOPS ("recovery required"). Then recovery → clean settle. Trial balance intact throughout.
2. **Crash during Phase 2 (mid payout loop):** force an exception inside 355–590 before commit #2. Assert full rollback: bets back to `pending`, escrow balances restored to nonzero, row still `CLAIMED`, no partial payouts. Recovery → clean settle.
3. **Wrong / stale token:** call `settle_week` with a non-matching token against a `CLAIMED` row (and against a NULL-token row). Assert STOP at Phase 1, no money moved. Also test mismatch surfacing at Phase-2 revalidation (token changed between Phase 1 read and lock) → abort, rollback.
4. **Concurrent normal invocation:** two `settle_week(recovery_token=None)` on the same week. Assert exactly one wins the claim and settles; the other sees `CLAIMED`, STOPS, moves no money. (Postgres-required for the true concurrency variant.)
5. **Crashed recovery → second recovery:** authorize recovery (token A), crash the rerun mid-Phase-2. Assert row = `CLAIMED` + token A + zero payouts. Second recovery (after exit evidence) overwrites token A with token B, reruns, settles clean. Assert token A can no longer be used; final row `COMPLETED`, token NULL.
6. **Duplicate call after COMPLETED:** settle a week clean, then call `settle_week` again (normal, and with a stale token). Assert both return the idempotent no-op report, no second payout, trial balance unchanged, `recovery_token` still NULL.

**Fixture discipline (per money-path rule):** use data where bug and fix diverge — asymmetric stakes / non-clean-dividing amounts so rounding bugs surface. Equal-stakes fixtures prove nothing about the escrow-close path.

---

## Step 7 — Grep: zero authoritative reads of `settled`

**Depends on:** Steps 1–6.

Re-run the Step-0 `settled`-reader grep. For every hit, classify: (a) the back-compat WRITE in Phase 1/Phase 2 (allowed), or (b) an authoritative READ that gates logic (must be ZERO — migrate any such read to `status`). Produce the list and the classification. If any authoritative read of `settled` remains, it's a defect — `status` is the sole authority.

---

## Step 8 — Assemble review package (NO deploy)

Bundle for Fraser review before anything touches production:
- The diff (migration + `settle_week` + recovery function).
- Test run output (SQLite suite + Postgres-required concurrency tests, both green).
- The Step-7 grep classification proving zero authoritative `settled` reads.
- `git status` / `git log --oneline` vs `origin` on the branch.

**Then STOP.** Production migration and `railway up --service fantasy-beefs` happen only on Fraser's explicit word after this review. "Build complete" from Claude Code means the image/branch is ready — the deploy gate is separate and manual.

---

## Post-build (separate, not this plan)

- Opus does NOT re-review implementation by default (the spec was the gated artifact); flag if the code diverges from Rev 5 in any money-path way, which would re-trigger the gate.
- The Simulation Engine Final Lock (MS-SIM-10) reuses this claim-first pattern — once FR-8.7 ships and proves in production, that build references the proven implementation.
- Deferred post-launch finding: automated stale-claim recovery (lease/owner/expiry/CAS) — tracked separately, not built here.
