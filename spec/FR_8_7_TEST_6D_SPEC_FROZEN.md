# FR-8.7 Test 6d — PostgreSQL Crash & Concurrency Specification

**Status:** FROZEN for review. Specification only — no implementation authorized.
**Basis:** Two independent blind-parallel taxonomies (Claude architect + independent reviewer), folded after convergence diff. Original semantic review of `betting/settlement_engine.py` was performed at HEAD `1d2a09e`; all line-number anchors were reverified and re-anchored at HEAD `21ec171` (post-FR-8.7-BUG-1), which is the operative source HEAD for every citation in this document.
**Line-number re-anchor:** all `settlement_engine.py` line citations below are current as of HEAD `21ec171` (post-FR-8.7-BUG-1). The BUG-1 comment insertion shifted lines below it +1: the Phase-2 commit is now 781 (was 780), `log_settlement_events` 782 (was 781), `_abort_recovery` rollback 897 (was 896), `recover_week` commit 1032 (was 1031). Unchanged (above the insertion): Phase-1 commit 360, FOR UPDATE lock 435/439, `_abort_phase2` rollback 426, idempotent-no-op rollback 459.
**Denominator:** Seven crash/concurrency scenarios. Empty-week completion and post-commit feed behavior are adjacent functional assertions, deliberately kept out of the crash denominator (§B).

---

## Provenance

The seven-scenario skeleton was reached independently by both producers from the same source recon, with no cross-contamination. Both derived the crash boundaries from the three commits (360, 781, 1032) and three rollbacks (426, 459, 897). Both independently landed on the mid-payout atomicity guarantee as the central money-path assertion, and both independently rejected a crash-just-after-781 as a separate scenario. The seventh scenario (two authorized recoveries racing) was contributed by the reviewer and adopted on the ruling that serialization correctness and replacement correctness fail independently and each warrants its own proof.

**Evidence labels used throughout:** *Verified* — read from source at the cited line. *Reported* — stated by a prior document. *Inferred* — concluded from guard logic or lock semantics, not executed. Retry outcomes and concurrency orderings are *inferred* until a real PostgreSQL run confirms them; confirming them is the purpose of 6d.

---

## Crash-surface map (verified)

| Boundary | Line | Meaning |
|---|---|---|
| Commit #1 — Phase-1 claim | 360 | `CLAIMED` row committed alone, before payouts |
| Rollback — abort helper | 426 | `_abort_phase2`: releases lock, raises |
| Rollback — idempotent no-op | 459 | releases lock before COMPLETED early-return |
| Lock acquisition | 435 | `SELECT … FOR UPDATE` — pre/post divider |
| Commit #2 — payouts + flip | 781 | all payouts, ledger postings, and COMPLETED flip commit together |
| Rollback — recovery abort | 897 | `_abort_recovery`: releases lock, raises |
| Commit #3 — recovery auth | 1032 | audit row + token overwrite commit together, before settle_week re-entry at 1037 |

**Atomicity foundation (verified):** every `ledger_post` in the payout loop uses `session=db` and stages transaction-local; nothing in the payout loop commits independently. The single commit at 781 makes the entire week's payouts all-or-nothing. This is the property scenario 6d-2 exists to prove.

---

## PART A — The seven crash/concurrency scenarios

Each scenario specifies all six required fields: injected event and exact point; expected durable state; recovery authority; recovery-token behavior; retry expectations; ledger invariants.

### 6d-1 — Post-claim / pre-lock crash

**Injection.** Terminate the process after the Phase-1 commit at 360 and before the `SELECT … FOR UPDATE` at 435. No Phase-2 query executes.

**Durable state.** One `week_settlements` row: `status='CLAIMED'`, `settled=FALSE`, `settled_at=NULL`, `recovery_token=NULL`. Zero bets touched, zero ledger postings, zero audit rows.

**Recovery authority.** `recover_week` only, with operator-supplied `actor` and `exit_evidence`. Exact production authority unresolved under FR-8.7-OPS-1 — a fixture assumption here, not a product-policy assertion.

**Token behavior.** Row carries no token. `recover_week` mints a fresh token (uuid4, line 993), fingerprints it (sha256, 994), writes it under lock (1016), commits with the audit row (1032).

**Retry expectations.** A normal caller takes the conflict path, reads CLAIMED with no token (guard at 394), raises the manual-recovery `ValueError` (395) — fail-closed, no economic writes. Only `recover_week` proceeds.

**Ledger invariants.** All escrow balances equal their pre-settlement state. Trial balance zero. No `wager_settled` postings exist.

### 6d-2 — Mid-payout / pre-commit crash *(central atomicity proof)*

**Injection.** Acquire the lock, enter the payout loop (525–675), inject a fatal failure after at least one `ledger_post(session=db)` has staged and related bet/transaction mutations are pending — but before the commit at 781. For the beef path, inject after the joint escrow-close posting is staged. Model as forced transaction termination with rollback, not a caught Python exception with no session cleanup.

**Durable state.** Because Phase-2 is one transaction committing only at 781, the forced rollback discards everything staged. Durable: `status='CLAIMED'`, `settled=FALSE`, `settled_at=NULL`, `recovery_token=NULL`. **No partial escrow drain survives.** No bet leaves `pending`. This is the assertion the whole test exists for: `session=db` + single commit means atomic all-or-nothing across every payout in the week.

**Recovery authority.** `recover_week`, after establishing prior process exit.

**Token behavior.** Failed normal run leaves no token. Recovery mints and commits fresh before re-entering settle_week.

**Retry expectations.** Normal caller refused while CLAIMED. Recovery caller's STEP 5 gate (931–964) re-checks all bets still pending; since the crash rolled back, they are; recovery settles cleanly. Retry after recovery completion → idempotent no-op.

**Ledger invariants.** Failed state: zero durable postings from the aborted attempt; every escrow and wallet exactly at pre-attempt balance; trial balance zero. Recovered state: one and only one posting set; escrows drained exactly once; wallet credits equal drained escrow totals; economic totals reconcile to *actual* escrow balances, never recomputed symmetric assumptions.

### 6d-3 — Post-commit / pre-return crash

**Injection.** Terminate after the commit at 781 and before the `SettlementReport` return (~804). Note this window contains the bare `log_settlement_events` call at 782 — see §B-2.

**Durable state.** Fully settled: `status='COMPLETED'`, `settled=TRUE`, `settled_at` set, `recovery_token=NULL`, all escrows drained, all wallets credited. The crash costs only the return value (and, if the crash is *after* 781, the feed events at 782).

**Recovery authority.** None needed — the week is done. `recover_week`'s STEP 4 (908) sees non-CLAIMED and aborts as non-recoverable.

**Token behavior.** N/A.

**Retry expectations.** Normal caller hits the claim conflict, reads COMPLETED (guard at 386), returns idempotent `already_settled=True`. Both the normal path and a mistaken recovery attempt correctly no-op.

**Ledger invariants.** Trial balance zero; every escrow at zero; wallet credits equal drained escrow totals exactly. No duplicate payout possible on retry.

### 6d-4 — Two normal callers race the claim

**Injection.** Two PostgreSQL sessions call `settle_week` against the same `(league_id, week)` with no existing row. Coordinate the Phase-1 claim (351–360) as near-simultaneous as possible. Concurrency injection, not a crash.

**Durable state.** The `INSERT … ON CONFLICT DO NOTHING RETURNING id` lets exactly one win. Winner's RETURNING yields a row and proceeds; loser's yields nothing and takes the conflict path. Exactly one economic settlement.

**Recovery authority.** None if the winner completes. If the winner is deliberately paused/killed after the claim commit, this degrades into 6d-1.

**Token behavior.** N/A on the happy path.

**Retry expectations.** Loser reads CLAIMED + no token → guard 394 → `ValueError`, fail-closed, no economic writes. Winner settles. The losing caller must make *no* economic writes.

**Ledger invariants.** Escrows drained exactly once. No double payout, no wallet credited twice. For a beef pair: both sides settled by the single winning worker; the partner-skip mechanism (532–533) must not allow a second worker to re-close the pair. Trial balance zero.

### 6d-5 — Recovery caller vs normal caller

**Injection.** Prepare a CLAIMED row with a committed recovery token via `recover_week`. Then race a recovery `settle_week(recovery_token=current)` against a normal `settle_week(recovery_token=None)`, coordinated around the conflict read and the Phase-2 `FOR UPDATE`.

**Durable state.** Normal caller performs no economic work. Recovery caller acquires the lock and completes: `COMPLETED`, `settled=TRUE`, `settled_at` set, `recovery_token=NULL`, one economic settlement. If the normal caller reaches the post-lock guard first, it aborts and releases the lock (guard at 474–481, normal claimant with live token → `_abort_phase2`) without changing durable state; the recovery caller then proceeds.

**Recovery authority.** Only the holder of the current token minted by the authorized `recover_week`. The normal route has no recovery authority.

**Token behavior.** Normal caller with no token rejected. Stale/incorrect token rejected. Matching token revalidated *again* under the lock (482–488). Successful recovery clears the token in the same commit as payouts and COMPLETED (781).

**Retry expectations.** Normal caller during active recovery fails closed, no economic writes. Recovery caller settles once. Normal retry after completion → idempotent no-op. Recovery retry after completion must not reopen or resettle.

**Ledger invariants.** Only the matching-token claimant stages ledger entries. Payout, token-clear, and COMPLETED commit atomically at 781. No duplicate postings, no second escrow close, trial balance zero.

### 6d-6 — Stale-token replacement after a recovery crash

**Injection.** `recover_week` commits its token and audit at 1032, then crashes before or during the settle_week call at 1037. A second recovery is attempted. *Proves replacement correctness.*

**Durable state.** `status='CLAIMED'`, a *stale* token on the row, `settled=FALSE`. One audit row from the crashed authorization exists.

**Recovery authority.** A second authorized `recover_week` invocation, again satisfying exit-evidence and recoverability rules.

**Token behavior.** The second `recover_week` detects a prior token present, records `prior_recovery_token_present=TRUE` (schema field), mints a *new* token, atomically overwrites the stale one (1016–1028), appends a new audit row with the new fingerprint. The stale raw token must no longer authorize settlement after replacement.

**Retry expectations.** Normal caller supplying nothing → refused. Recovery caller with the *old* token → guard 404 (mismatch) → refused. Only the newest recovery proceeds. The crashed first recovery performed no settlement (it died before/at 1037's payout), so escrows are intact.

**Ledger invariants.** No settlement occurred under the stale token; escrows still intact; the new recovery settles them once. Multiple audit authorizations may exist, but only one payout set. A recovery-audit row itself never changes BAB.

### 6d-7 — Two authorized recoveries race *(serialization proof)*

**Injection.** Begin two `recover_week` calls in separate sessions for the same CLAIMED week. Coordinate both around the recovery `SELECT … FOR UPDATE` (900–907). Hold the first after it acquires the lock so the second demonstrably blocks. *Proves serialization correctness — distinct from 6d-6's replacement correctness. The two fail independently: a sequential stale-token test would not catch a lost-update race, overlapping audit inserts, or two callers both believing they hold current authority.*

**Durable state.** The row lock serializes authorization. The second caller cannot validate and overwrite the token concurrently with the first. Audit rows and token replacements occur in committed order. No two recovery claimants simultaneously pass Phase-2 token revalidation.

**Recovery authority.** Both sessions are independently authorized operators *for test purposes*. The test does not decide who may hold that authority in production (FR-8.7-OPS-1).

**Token behavior.** Only the currently committed token authorizes Phase-2. Required properties: no lost-update token race; no two simultaneously valid tokens; stale token rejected after replacement; each committed authorization has its own fingerprinted audit row; raw token never in the audit table.

**Retry expectations.**
- *Subcase A — first recovery completes:* second `recover_week` obtains the lock, observes non-CLAIMED (COMPLETED), aborts as non-recoverable without inserting a valid new authorization. Normal retry → completed no-op.
- *Subcase B — first crashes after token commit:* second recovery may replace the token serially (degrades into 6d-6); first token must fail; second token may complete.

**Ledger invariants.** At most one recovery claimant performs the economic commit. No duplicated wager settlement, no duplicated beef escrow close, no duplicate wallet credit. Trial balance zero. **Recovery-audit multiplicity must not imply economic multiplicity.**

---

## PART B — Adjacent functional assertions (NOT crash scenarios)

Deliberately separated from the seven-scenario denominator. These test functional lifecycle behavior, not crash boundaries, and must not dilute the crash taxonomy.

### B-1 — Empty-week completion *(UNBLOCKED — FR-8.7-BUG-1 shipped at 21ec171)*

**Pre-fix behavior (verified against pre-`21ec171` source):** the zero-pending-bet path returned early at 510–511 *after* the lock, executing no UPDATE, no commit, no rollback — the row remained `CLAIMED`, and a subsequent plain `settle_week` read CLAIMED + no token → raised the manual-recovery `ValueError` (395). The empty week was **persistently stranded as CLAIMED** — recoverable via authorized `recover_week` or repair, but not settleable by ordinary means.

**Current behavior at `21ec171`:** the early return is removed. Empty weeks fall through the empty setup (`wallet_ids`, `balance_before`, `settlements` all evaluate empty) and the zero-iteration payout loop to the shared claimant-specific guarded completion, reaching `COMPLETED` like any zero-outcome week. A retry is idempotent.

**Dependency — RESOLVED.** FR-8.7-BUG-1 was fixed, tested, and shipped at commit `21ec171` (branch `remediation/foundation-phase-1`). The empty-week completion assertion is no longer hypothetical: it is realized as `test_fr87_empty_week_completion_pg.py`, an 11-assertion PostgreSQL test that proved red against the pre-fix code and green after. Its assertions: an empty week reaches `COMPLETED`, `settled=TRUE`, `settled_at` set, `recovery_token=NULL`, via the shared claimant-specific guarded completion (not a naive flip); a retry returns idempotent `already_settled=True`; and no second `week_settlements` row is created. Verified green alongside 6c (11/11) and 6b (27/27). This adjacent assertion is therefore already satisfied and committed; 6d proper does not need to re-implement it, though 6d's crash scenarios may reuse the empty-week fixture shape.

### B-2 — Post-commit feed-logging behavior *(blocked on FR-8.7-LOG-1 ruling)*

**Current behavior (verified, line 782):** `log_settlement_events(pending, db)` runs bare after the 781 commit — no try/except, no retry. If it raises, `settle_week` propagates the exception after settlement has committed and the week is COMPLETED, before the report is built. Economic state correct; caller-visible signal corrupted.

**Dependency.** The expected caller-visible result cannot be frozen until FR-8.7-LOG-1 is ruled. Today's result: an exception after a successful commit. After the recommended fix: a successful `SettlementReport` plus a separately observable feed-failure signal. The 6d assertion is: **a post-781 logging failure never corrupts durable economic state** — true under both current and fixed behavior; only the caller-visible return differs.

### B-3 — Beef cross-session balance visibility *(test requirement, not a blocker)*

**Requirement (per ruling).** For beef settlement, the test must *demonstrate*, not assume, that every `balance_of()` read (which opens its own session) occurs before the transaction-local `ledger_post(session=db)` writes it depends on, and must assert named-account balances *after* commit. The cross-session visibility boundary — a separate-session read against writes staged in the open settlement transaction — must be shown correct, not presumed.

---

## PART C — Required cross-scenario helpers

Common assertion helpers, not per-scenario ad hoc checks.

**Durable lifecycle.** Every *failed* execution: `status='CLAIMED'`, `settled=FALSE`, `settled_at=NULL`; token state unchanged from before the failed Phase-2 transaction (unless the failure is post-recovery-authorization-commit). Every *completed* execution: `status='COMPLETED'`, `settled=TRUE`, `settled_at IS NOT NULL`, `recovery_token IS NULL`.

**Economic atomicity.** After a failed Phase-2 transaction: no new durable ledger entries, no new payout transactions, no bet leaves `pending`, no wallet or escrow balance change. After successful completion: each bet/beef pair settles exactly once; all relevant escrow closes exactly once; trial balance zero; totals reconcile to actual escrow, not symmetric assumptions.

**Audit integrity.** Every committed recovery authorization: exactly one append-only audit row; fingerprint stored, never the raw token; fingerprint corresponds to that authorization's token; stale-token replacement records `prior_recovery_token_present=TRUE`; a recovery validation that fails before the authorization commit creates no audit row.

**Concurrency mechanics.** Separate SQLAlchemy sessions and separate PostgreSQL connections; explicit synchronization barriers; lock-wait observation or bounded timeout proving the second session blocks; deterministic release order; no `sleep` as the sole concurrency proof.

---

## PART D — Dependencies and build order

1. **FR-8.7-BUG-1 — DONE.** Fixed, tested, and shipped at `21ec171`. The B-1 empty-week completion assertion is satisfied and committed (`test_fr87_empty_week_completion_pg.py`, 11/11 green). No longer a blocker.
2. **FR-8.7-LOG-1 ruled** before B-2's expected caller-visible result is frozen. Independent review required (changes the service's observed success/failure contract).
3. **The seven crash/concurrency scenarios must not be diluted** by these functional subcases. B-1, B-2, B-3 live in the marked adjacent section and never enter the crash denominator.
4. 6d implementation itself remains unauthorized. This document is frozen design only.

---

## PART E — Open items carried from the derivation

- **FR-8.7-OPS-1** (recovery invocation authority) is assumed as a fixture parameter throughout Part A; production authority is unresolved and must not be asserted as policy by these tests.
- **PostgreSQL isolation level** not yet observed. `FOR UPDATE` behavior is testable regardless, but broader snapshot-visibility assumptions must not be asserted until engine/session isolation is confirmed. Ties to FR-AC-ISO-1.
- **Cross-week bet contamination** (a bet belonging to two settlement scopes) — flagged as an unverified edge during derivation, not a scenario. The STEP 5 recoverability gate's handling of a bet settled by a different week's run was not confirmed from source.
