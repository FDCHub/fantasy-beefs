# FR-8.7 MODULE_SPEC — Settlement Claim-First Two-Phase Rebuild (Rev 5 — Opus round 3 CLEARED, build-ready)

**File:** `betting/settlement_engine.py` (NOT `settlement/` — corrected by 2026-07-19 grep)
**Model:** `db/schema.py` — `WeekSettlement` (lines 890–905)
**Finding:** FR-8.7 — settlement completion-first crash gap. **LAUNCH-BLOCKING.**
**Status:** Rev 5 — **BUILD-READY.** All three Opus rounds cleared and approved. No code, no migration, no `railway up` until Fraser's explicit build go. Money-path.
**Scope ruling (Fraser, 2026-07-19): Option 3 — minimal three-state lifecycle for Aug 1; automated stale-claim recovery (lease/owner/expiry/CAS) tracked as a SEPARATE post-launch finding.**
**Opus Math Review — round 3 CLEARED (Fraser approved all three, 2026-07-19):** the `recovery_token` mechanism wired end-to-end.
- **MS-8.7-9 (Option A):** the token must pass **Phase 1**, not just Phase 2. `settle_week(..., recovery_token=None)`; on a `CLAIMED` conflict — no token stops, matching token proceeds, mismatch stops. §3 Phase 1 branch rewritten.
- **MS-8.7-7 (Option A):** §3 Phase 2 step 2 now revalidates under the lock — normal claimant requires row token `NULL`; recovery claimant requires exact matching non-null token; any mismatch aborts before money moves. The `COMPLETED` update clears `recovery_token=NULL` **atomically** with payouts.
- **MS-8.7-8 (Option A):** stranded-token state documented in §5b — `CLAIMED` + non-null token = authorized-but-incomplete; normal calls stay blocked; a later controlled recovery overwrites the old token with a fresh one under lock after confirming the prior recovery process is dead; old token has no economic effect and is never hand-edited. A crashed recovery is itself recoverable.
- **Round-3 result:** recovery path complete and coherent — matching token clears the Phase-1 conflict branch, is revalidated under `FOR UPDATE`, payouts + token-clear commit atomically, unrelated invocations cannot enter, and a crashed recovery recovers safely. §2/§3/§5b describe one mechanism.

**Round 2 CLEARED (Fraser approved all three, 2026-07-19):**
- **MS-8.7-4 (Option A):** §3's lock rationale rewritten to match §5b. Unique-index claim is the primary admission guard; `FOR UPDATE` serializes only workers that have reached Phase 2; it does NOT cover the claim-to-lock window; §5b step 1 exists precisely for a worker stalled before the lock.
- **MS-8.7-5 (Option B + concrete signal):** §5b step 1 requires the settlement **process/container confirmed exited or forcibly terminated** — not "slow." Exact evidence recorded in the recovery audit.
- **MS-8.7-6 (Option A):** atomic **reclaim-in-transaction** via a dedicated one-shot `recovery_token` column (not a `CLAIMED_RECOVERY` status); `status` stays two values.
- **Targets 1–5, 7, 8: CLEAN.** Rerun idempotency and balance-invariant idempotency airtight given full-rollback atomicity, grep-confirmed.
- **Documented root:** Option 3 has no in-DB liveness signal, so single-worker safety rests on operational facts, not machine-enforced ones. Safe for the Aug-1 single-process/single-commissioner deployment — no double-pay.

**Prior-round history (round 1 → Rev 3):** row-lock concurrency gap closed, scope cut to Option 3, idempotency-key premise corrected (no key exists; balance-invariant guard), liveness precondition added.
**Grounded on:** 2026-07-19 read-only recon of live `settle_week()` and `WeekSettlement`. Code is truth.
**Pattern source:** MS-SIM-10 (Simulation Engine Rev 7, §29). This spec is the settlement-side instance of the **same durable claim-first, recoverable two-phase idempotency protocol**. Building it first de-risks Final Lock, which needs the identical machinery.

---

## 0 — The bug, stated exactly

`settle_week()` (lines 310–625) has two separate commits.

- **Commit #1 (line 345)** writes `settled=True` to `week_settlements` via `INSERT … ON CONFLICT (league_id, week) DO NOTHING RETURNING id`. This is the claim.
- **Commit #2 (line 592)** commits every payout: beef ledger postings, `bet.status`/`settled_at` flips, wallet mutations, all `Transaction` rows.

The entire payout loop (lines 355–590) sits between them.

The defect is not a missing claim. The claim exists. The defect is that **`settled` is a two-state boolean that already reads `True` the instant the claim commits — before one cent moves.** A crash anywhere in 355–590 leaves the week marked settled with payouts unfinished. Every retry hits the `ON CONFLICT DO NOTHING`, gets `claimed is None`, and returns early at 347–353. The week is stranded. The docstring at 321–326 acknowledges this as a known, accepted, deferred tradeoff with manual commissioner recovery only.

**Analogy:** the current code stamps the envelope "delivered" the moment the mail carrier picks it up, not when it lands in the box. If the truck crashes en route, the system swears it arrived.

---

## 1 — The fix, in one sentence

Replace the two-state `settled` boolean with a **three-state lifecycle** so a retry can tell "finished" apart from "died mid-loop," and give the incomplete state a **safe resume path** instead of a permanent skip.

Three states:
- `CLAIMED` — a worker has the week; payouts not yet durably committed. Excludes concurrent workers. Does **not** suppress a retry.
- `COMPLETED` — payouts committed atomically. The **only** state that suppresses future execution permanently.
- (absent row) — never claimed; claim and execute.

This mirrors MS-SIM-10 verbatim: *"a `CLAIMED/IN_PROGRESS` claim commits first and separately to exclude concurrent workers; the economic work commits atomically second… Only `COMPLETED` suppresses future execution; a claimed-but-incomplete event is recoverable."*

---

## 2 — Schema change (migration, Fraser-gated) — Option A, minimal (Option 3 scope)

Add `status`, retain `settled` temporarily, make `status` the sole authoritative field. `settled` is written for back-compat only and read by nothing after this ships; removed in a later cleanup. The `uq_week_settlement_league_week` unique constraint on `(league_id, week)` stays as the run-once serialization guard and remains the `ON CONFLICT` target.

New columns on `WeekSettlement`:

| Column | Type | Meaning |
|---|---|---|
| `status` | `String`, `nullable=False`, `default="CLAIMED"` | **Sole authoritative lifecycle state.** `CLAIMED` or `COMPLETED` — exactly two values. |
| `recovery_token` | `String`, `nullable=True` | One-shot authorization marker for a recovery rerun (see §5b). Null in normal operation; set only when a row is reclaimed for authorized recovery; cleared atomically with the `COMPLETED` flip. Authorization is kept **separate from lifecycle** — this is why recovery does not need a third `status` value. |

`completed_at` uses the existing `settled_at` column, whose meaning stays **completion** (set only on the flip to `COMPLETED`, never at claim time). No `claimed_at`, `claim_owner`, `claim_expires_at`, `report_ref`, heartbeat, or version columns — those belong to the deferred post-launch automated-recovery finding. The one exception is `recovery_token` (above), which is in Aug-1 scope because MS-8.7-6's atomic reclaim requires it; it carries no lease semantics (no expiry/heartbeat).

**On the `COMPLETED`-suppress return.** With no persisted `report_ref` in this minimal scope, a retry that finds `COMPLETED` returns an idempotent "already settled" `SettlementReport` (a truthful no-op report), not a reconstructed payout report. It must not present as if fresh payouts occurred. Whether to persist a report reference for exact-original replay is deferred to the post-launch finding. **Flag for Opus:** confirm the no-op report cannot mislead a caller.

**Migration safety.** Two additive columns: `status` (`nullable=False default="CLAIMED"`) and `recovery_token` (`nullable=True`). FR-5.13 holds the table is empty in production, so there are no rows to backfill; the default covers any that appear between migration and deploy. Unique constraint untouched.

---

## 3 — Rewritten control flow (Rev 3 — minimal lifecycle + row lock)

**Core rules:**
- No auto-resume. A `CLAIMED` week a retry did not itself just claim means "stuck — manual recovery required." Stop and report.
- `COMPLETED` commits *with* the payouts, never before.
- Phase 2 opens under a `SELECT … FOR UPDATE` row lock so two workers can never execute the payout loop concurrently.

**Phase 1 — Claim acquisition (commit #1, at current line 345):**

`settle_week(week, db, league_id, recovery_token=None)` — `recovery_token` is `None` on the normal path and non-null only when invoked as an authorized recovery rerun (§5b step 9).

1. Attempt the claim (unchanged INSERT, now writing `status`):
   `INSERT INTO week_settlements (league_id, week, status, settled) VALUES (:lid, :wk, 'CLAIMED', FALSE) ON CONFLICT (league_id, week) DO NOTHING RETURNING id`.
2. `db.commit()`.
3. Branch:
   - **Row returned (I won the claim):** normal fresh claim — I hold no recovery token, and the row's `recovery_token` is NULL. Proceed to Phase 2 as the normal claimant.
   - **No row (conflict — a row exists):** read its `status` and `recovery_token`.
     - **`COMPLETED`** → return the idempotent "already settled" no-op report. **Permanent suppress.**
     - **`CLAIMED`, and I presented NO token** (`recovery_token=None`) → **STOP.** Return / instruct "settlement in progress or incomplete — manual recovery required." No Phase 2. (This is every normal invocation — a normal caller can never pass this gate on a claimed week.)
     - **`CLAIMED`, and I presented a token that MATCHES the row's `recovery_token`** → I am the authorized recovery rerun. Proceed to Phase 2 as the recovery claimant. (The match will be **revalidated** under the Phase-2 `FOR UPDATE` lock before any money moves — Phase 1's read is not trusted alone.)
     - **`CLAIMED`, and I presented a token that does NOT match** (mismatch, or row token is NULL while I hold one) → **STOP.** A stale or wrong token authorizes nothing.

**Phase 2 — Economic work, under row lock (commit #2, at current line 592):**

1. **Acquire the claim-row lock — first statement of Phase 2:**
   `SELECT * FROM week_settlements WHERE league_id=:lid AND week=:wk FOR UPDATE`
   on the same `db` session. Hold until this transaction commits or rolls back.
2. **Revalidate ownership under the lock, before any payout write:**
   - **Normal claimant** (entered via the fresh-claim branch): assert `status == 'CLAIMED'` **and `recovery_token IS NULL`**. A normal run must never execute against a row carrying a live recovery token.
   - **Recovery claimant** (entered via the token-match branch): assert `status == 'CLAIMED'` **and the row's `recovery_token` equals the exact token this run was handed.** Phase 1's read is revalidated here under the lock because the row could have changed between the Phase-1 commit and lock acquisition.
   - **Any mismatch, missing-where-required, or present-where-forbidden, or `status == 'COMPLETED'`** → abort and roll back before money moves. (COMPLETED means another run finished; return the no-op report.)
3. Run the payout loop (355–590) — beef ledger postings (`session=db`), single-party settlements, status flips, wallet mutations, `Transaction` rows. All on `db`, all inside this locked transaction.
4. **Flip to `COMPLETED` and clear the token in the same transaction:**
   `UPDATE week_settlements SET status='COMPLETED', settled_at=now, settled=TRUE, recovery_token=NULL WHERE league_id=:lid AND week=:wk AND status='CLAIMED'`.
   Clearing `recovery_token=NULL` **atomically with the `COMPLETED` flip** guarantees no window where a completed week still carries a live token a later stray call could match. If this affects zero rows, abort and roll back (defensive backstop under the lock).
5. `db.commit()` — payouts, the `COMPLETED` flip, and the token clear land atomically, releasing the row lock. Either all persist or none do.

**What the `FOR UPDATE` lock does — and what it does not (reconciled with §5b).** The lock serializes two workers **that have both reached Phase 2's lock statement**: the second blocks there until the first commits or rolls back, then wakes to find `status='COMPLETED'` (abort) or, after a crash+rollback, a recoverable row. It is intra-Phase-2 defense. It does **not** cover the window between the Phase-1 claim commit and the Phase-2 lock acquisition: a worker stalled in that gap holds no lock, so the lock cannot serialize against it. That window is exactly why §5b's manual recovery requires an operational dead-worker confirmation as step 1 — the lock can't prove a pre-lock worker is dead.

So the single-worker guarantee has a clear division of labor:
- **Primary admission guard: the Phase-1 unique-index claim.** `ON CONFLICT … DO NOTHING` admits exactly one worker per `(league_id, week)`, and a conflicting `CLAIMED` read makes every other worker STOP (no auto-execute). This is what keeps two workers from both entering Phase 2 in normal operation.
- **Intra-Phase-2 defense: the `FOR UPDATE` row lock.** For any case where a second worker nonetheless reaches Phase 2 (a future concurrent trigger), the lock serializes them there so the payout loop and the FR-5.9 escrow-close check never run for two callers at once.
- **Operational backstop: §5b step 1.** Covers the one thing neither the index nor the lock can see — a live-but-stalled worker in the claim-to-lock window — by requiring a human to confirm the original process is dead before recovery resets the claim.

**The critical inversion:** today `settled=True` commits *before* the work. In the fix, `COMPLETED` commits *with* the work, under a row lock held across the whole loop. `CLAIMED` commits early but never authorizes a *second* worker to execute — a conflicting reader stops.

---

## 4 — §4 grep — COMPLETED 2026-07-19 (results folded in)

The recon ran read-only against live code before this rev. Results:

1. **No internal commits or escaping side effects in 355–590 — CONFIRMED.** No `db.commit()` in the span; the only commits are line 345 (before) and 592 (after). One caveat: `balance_of()` opens a *separate read-only* session for `SELECT COALESCE(SUM(...))` (ledger.py 108–115, called at 411/454/455). It writes nothing and cannot survive or defeat a rollback. No external HTTP, no queue publish. Read-only second-session SELECT is harmless.
2. **Single shared `db` session for all writes — CONFIRMED.** Beef postings pass `session=db` (412–419, 458–466); status/`settled_at` flips on ORM objects from `db` (420–421, 468–471, 564–565); wallet mutation at 569; `Transaction` inserts via `db.add` (423, 487, 494, 570). Only non-`db` usage is the read-only `balance_of` above.
3. **`ledger_post` does not commit on `session=db` — CONFIRMED.** `post()` at ledger.py 297–299 returns immediately after `_run_checks_and_write` with no commit; internal commit (line 308) is reachable only on the `session=None` branch, which settlement never uses. Deferred-commit pattern intact.
4. **Pending query reselects off committed status — CONFIRMED.** `db.query(Bet).join(Matchup).filter(Matchup.week==week, Bet.status=="pending")` (355–361) reads a persisted column in SQL. A rolled-back Phase 2 reverts both DB and in-memory object state to `pending`, so a clean rerun reselects every untouched bet.
5. **Ledger idempotency — CORRECTED (premise was wrong).** There is **no deterministic per-bet idempotency key**, and no timestamp/random dedup token either. `posting_id` is a random `uuid4` (ledger.py 294) — a per-posting group id, *not* a dedup key. Duplicate prevention is **balance-based**: `wager_settled` postings raise `AlreadySettledError` if the escrow account is already at zero (ledger.py 188–193). **This is post-commit protection, not a retry idempotency key.** For FR-8.7's purposes this is sufficient, because §4-1..4 prove the payout loop has no independently committed effect: a rolled-back Phase 2 restores escrow balances and bet statuses *completely*, returning escrow to nonzero, so a rerun is permitted and correct. The safety rests on **transactional atomicity + the balance invariant**, not on a persisted key.
6. **Isolation / claim mechanism — CONFIRMED Postgres; MECHANISM SIMPLIFIED.** Production is Postgres (`DATABASE_URL`, schema.py 27–35); SQLite is local/test only. The claim's single-winner property rests on the `uq_week_settlement_league_week` **unique index**, not on isolation level, so default READ COMMITTED suffices for the `ON CONFLICT` insert. **The new `SELECT … FOR UPDATE` row lock (§3) also holds under READ COMMITTED** — row locks are enforced regardless of isolation level. No lease/owner/expiry columns exist (correct — Option 3 does not add them).
7. **FR-5.9 serialization (330–335) — CONFIRMED intact.** The beef escrow-close skip relies solely on the claim admitting one caller per `(league_id, week)`; the in-loop `handled_beef_bet_ids` set is intra-pass dedup within that single serialized caller, not a concurrency guard.

**Conclusion:** the resume/rerun is provably clean — payout loop has no internal commit, all economic writes ride the one `db` transaction, and a rollback restores state fully. The corrected idempotency understanding (balance invariant, not key) does not weaken this; it is exactly why a rerun after full rollback is safe. Ready for Opus.

---

## 5 — Finding 5.9 dependency (do not break)

Lines 330–335 tie FR-5.9's beef escrow-close concurrency safety to this claim serializing callers per `(league_id, week)`. The fix **preserves and strengthens** that on two fronts:

1. **Claim admission (initial insert):** `ON CONFLICT … DO NOTHING` on the unchanged unique constraint still admits exactly one worker per week — the guarantee FR-5.9 already depends on, unchanged.
2. **Phase-2 row lock (new):** `SELECT … FOR UPDATE` on the `week_settlements` row serializes execution of the payout loop itself. Even if a second worker somehow reached Phase 2 (a future concurrent trigger), it blocks on the lock until the first commits or rolls back — so the beef escrow-close skip check inside the loop is never evaluated by two callers at once.

FR-5.9's single-worker-per-week contract is intact — strengthened, because the old code's stranded-week failure mode (a commissioner "fixed" it by hand, outside any serialization guarantee) is replaced by an honest `CLAIMED` state and a controlled, audited recovery (§5b). **Flag for Opus:** confirm the `FOR UPDATE` lock holds under production READ COMMITTED (it does — row locks are isolation-independent) and that the in-loop `handled_beef_bet_ids` set remains intra-pass dedup, not a concurrency control.

---

## 5b — Manual recovery (Option 3, commissioner-driven)

A crashed Phase 2 rolls back fully (grep §4-1..4) and leaves the row at `CLAIMED` with no committed payouts. Recovery is **not** ad hoc database editing. It is a controlled, authorized, audited operation.

**The liveness limitation (why step 1 exists).** Option 3 has no owner token, heartbeat, or lease, so the system **cannot distinguish a crashed worker from a slow live one** — both present identically as a `CLAIMED` row. The `FOR UPDATE` row lock prevents recovery from racing an *active Phase-2 transaction* (one that has reached its own `SELECT … FOR UPDATE`), but it does **not** prove that an uncommitted worker is dead: a worker stalled *before* it acquires the lock holds nothing, so recovery could reset its claim out from under it while it is still alive and about to proceed. That double-execution risk is closed only by an **operational precondition** confirmed by a human, not by any in-DB check. This prerequisite is what makes manual recovery safe under the minimal launch design.

**Step 1 — the concrete exit criterion (MS-8.7-5).** "Appears slow" or "has not responded" is **insufficient** and must not authorize recovery. Recovery may proceed only after confirming the original settlement **process or container has exited or been forcibly terminated** — the OS process, not merely a thread. The operator records the exact evidence in the recovery audit (step 6). Acceptable evidence for the Aug-1 single-process deployment:
- process/container **exit status** observed (the container/process is gone), or
- a **failed or terminated job-runner record** for that settlement invocation, or
- **explicit operator termination** (kill the process/container) **followed by confirmation the process is gone**.

A hung thread inside a still-running process does **not** qualify — the whole process must be confirmed exited. This is the one place double-pay safety rests entirely on a human; the instruction to that human is therefore exact, not a judgment call. (When the deferred automated-recovery finding adds a real in-DB liveness signal, this operational criterion tightens into a machine check.)

**Recovery sequence (atomic reclaim-in-transaction — MS-8.7-6, Option A):** the row is **never** deleted or left generally claimable between authorization and rerun. No unrelated trigger can win the week during recovery.

1. **Confirm the original process is dead** per the step-1 exit criterion above. Operational, outside the DB, before the transaction opens.
2. Begin a database transaction.
3. `SELECT … FOR UPDATE` the `week_settlements` row for `(league_id, week)`.
4. Require `status == 'CLAIMED'`. If `COMPLETED`, abort — a completed week must never be recovered (double-pay).
5. Verify no Phase-2 effects committed — the week's bets are still `pending`, escrow balances intact.
6. Write the immutable recovery audit record: actor, week, timestamp, observed pre-state, **and the step-1 exit evidence**.
7. **Re-initialize the same row as a fresh claim owned by this recovery execution** — write a fresh one-shot `recovery_token` (uuid4) to the row (see the token subsection below). `status` stays `CLAIMED`; the row stays present throughout and never returns to the absent/generally-claimable state.
8. Commit.
9. Run `settle_week` **as the already-authorized recovery claimant**, handing it the token from step 7. Its Phase-2 entry validates the handed token against the row's `recovery_token` under the `FOR UPDATE` lock before executing, and clears the token atomically with the `COMPLETED` flip. Any unrelated invocation carries no token, sees `CLAIMED` at Phase 1, and stops.

**The recovery-execution token (narrow, not a lease) — DESIGN CHOSEN.** MS-8.7-6's implication: an atomic reclaim only closes the race if the rerun can *prove* it is the authorized claimant. **Chosen design (Fraser, 2026-07-19): a dedicated one-shot `recovery_token` column** — NOT a `CLAIMED_RECOVERY` status value. `status` stays exactly two values (`CLAIMED`, `COMPLETED`); authorization lives in a separate, explicit, auditable column. Semantics:
- **Creation:** step 7 generates a fresh token (uuid4) and writes it to `recovery_token` on the reclaimed row, inside the recovery transaction.
- **Storage:** `recovery_token = Column(String, nullable=True)`. Null in normal operation; non-null only for a row awaiting an authorized recovery rerun.
- **Validation:** step 9's `settle_week`, run as the recovery claimant, is handed the token and checks it matches the row's `recovery_token` under the Phase-2 `FOR UPDATE` lock before executing. A normal (non-recovery) `settle_week` presents no token; it reaches Phase 1, sees `CLAIMED`, and stops — it never validates against or consumes the token.
- **Consumption:** the token is cleared (`recovery_token = NULL`) **atomically with the flip to `COMPLETED`** in Phase 2's single commit — so a successful recovery rerun leaves a clean `COMPLETED` row with no dangling token.
- This is **narrower than the deferred lease machine**: no expiry, no heartbeat, no automated reclaim — a single-use marker consumed by the immediate authorized rerun.

**If the recovery rerun itself crashes (MS-8.7-8).** Should step 9 die before or during its Phase 2, the row is left `CLAIMED` with a **non-null `recovery_token`** and — because Phase 2 is atomic (grep §4) — **no committed payouts.** This state is well-defined and safe:
- `CLAIMED` + non-null token means *recovery was authorized but did not complete.*
- **Normal invocations stay blocked** — they present no token, hit the `CLAIMED`+no-token gate, and stop. No stray call can proceed against a stranded-token row.
- The old token has **no committed economic effect** (nothing was paid) and **must never be hand-edited** out.
- **A second recovery is safe.** After confirming the prior recovery process is dead (step 1 exit criterion, again), a later controlled recovery re-enters the locked recovery transaction and **overwrites the old token with a fresh one** (step 7). The overwrite happens under `FOR UPDATE`, so it cannot race the dead run (already gone) or any normal call (blocked at Phase 1). The fresh token authorizes the new rerun; the old token is simply gone. A crashed recovery is therefore itself recoverable, by the same mechanism.

Still narrower than a lease, and in scope for Aug 1 because without it, re-initializing the row to fresh `CLAIMED` re-opens the stray-trigger window MS-8.7-6 flags.

The guard is `CLAIMED`-only with no committed result, and it can never touch a `COMPLETED` week. This recovery function is in scope for Aug 1 — it is the *recovery* half of the launch-blocker fix. Its guard is itself a money-path assertion and goes through the Opus gate.

---

## 6 — Opus Math Review targets (issues-only, table format, each approved individually)

Send these for the gate (issues-only, table format, each approved individually):
1. **Zero ledger effect of status writes.** No ledger postings change in this spec. Confirm every `status`/`settled_at`/`settled` write carries zero ledger effect (status writes, not money moves).
2. **Rerun idempotency (§4-1..4, grep-confirmed).** A rolled-back Phase 2 leaves zero committed payouts and restores escrow balances + bet statuses fully, so a rerun is clean. Confirm the argument holds — the load-bearing money-path claim.
3. **Idempotency mechanism is the balance invariant, not a key (§4-5, corrected).** Confirm the zero-escrow `AlreadySettledError` is adequate *given full rollback*, and that no path could reach a rerun with escrow partially at zero (which would wrongly raise or wrongly permit).
4. **`FOR UPDATE` row-lock serialization (§3, §5).** Confirm the lock serializes Phase 2 under production READ COMMITTED and that no payout write precedes lock acquisition.
5. **`COMPLETED`-suppress return fidelity.** A retry finding `COMPLETED` returns an idempotent no-op report (no persisted `report_ref` in Option 3). Confirm it cannot mislead a caller into thinking fresh payouts occurred.
6. **Recovery guard + liveness precondition (§5b).** The recovery function acts only on `CLAIMED` rows with no committed result, is audited, and can never touch a `COMPLETED` week. **Critically:** because Option 3 has no owner/heartbeat/lease, the DB cannot tell a crashed worker from a slow one; recovery requires an operational dead-worker confirmation (step 1) *before* the transaction opens. Confirm the row lock alone is insufficient (it does not prove an uncommitted pre-lock worker is dead) and that the step-1 precondition closes the double-execution race. Confirm no interleaving double-pays.
7. **Migration (Option A minimal).** Single additive `status` column, `settled` retained-but-unread, unique constraint untouched — confirm no read path still keys off `settled`.
8. **FR-5.9 serialization preservation (§5).**

---

## 7 — Explicitly out of scope

- No change to payout math, escrow sourcing, or the FR-5.9/5.10 fixes (already live, `38f8291`).
- No change to the `uq_week_settlement_league_week` constraint.
- No frontend. This is settlement-engine + one migration + one recovery function only.
- **Deferred to a separate post-launch finding — automated stale-claim recovery.** Owner token, lease expiry, heartbeat/version, and CAS reclaim semantics. Adds *unattended* crash recovery on top of this minimal lifecycle. Justified only after the three-state lifecycle is proven in production. Under today's single-process, commissioner-triggered, single-league settlement, concurrent entry is N/A, so the manual recovery in §5b is sufficient for Aug 1.

---

## 8 — Sequencing note

Build this **before** the Simulation Engine Final Lock. Same claim-first pattern, lower surface area (no odds derivation), live-and-blocking. Proving the pattern here validates the identical machinery MS-SIM-10 needs — one idempotency protocol, tested twice.
