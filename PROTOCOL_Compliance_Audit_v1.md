# Deterministic-Protocol Compliance Audit — Money-Path Retroactive Sweep

**Status:** Launch-gate item. Read-only recon first; findings ruled individually; launch-blockers fixed before Aug 1.
**Origin:** FR-8.7 (2026-07-19) hardened a set of deterministic money-path protocols. FR-8.7 was *built* to them. This audit asks whether code that predates them *complies* with them. Prompted by the observation that the cross-league scoping defect (`2384b14`) was found only *incidentally* during FR-8.7 recon — meaning similar pre-existing defects are found by accident, not systematically.
**Scope:** Every money-path module NOT authored under the FR-8.7 protocols. Read-only sweep; no fixes without individual rulings and (for money-path) the Opus gate.
**Register:** New findings numbered FR-8.8-{n} (audit findings), distinct from the FR-8.7 lifecycle.

---

## 0 — Why this exists (the core argument)

FR-8.7 fixed *one instance* of a *class* of bug: a completion marker (`settled=True`) written before the payouts it claims. We fixed `settle_week`. We did not ask whether the same class recurs elsewhere. It very likely does — the closest structural sibling, `pool_engine.py`'s `PoolPot.settled` guard, has the identical "mark settled, then pay" shape and was probably written by the same hand with the same mental model that produced the `settle_week` defect. **We repaired a symptom in one module; we never checked the pattern across the codebase.**

The scoping bug is the proof of method-failure: `settle_week` took a `league_id` argument and never used it in its pending query. That survived until recovery recon happened to need the predicate. Incidental discovery is not a strategy. This audit replaces "we'll notice if we trip over it" with a deliberate sweep.

---

## 1 — The protocols to audit against (the checklist)

Each is a deterministic invariant FR-8.7 established or relied on. The audit greps every money-path module for violations of each.

| # | Protocol | Violation signature |
|---|---|---|
| P1 | **Completion commits WITH payouts, never before.** A "settled/completed/paid/closed" marker must not commit in a transaction separate from (and earlier than) the money movement it asserts. | A status/boolean flip to a done-state that commits before the payout loop it represents. The exact FR-8.7 bug. |
| P2 | **`FOR UPDATE` holders roll back on every abort.** Any code holding a row lock must `rollback()` before every `raise`/early-`return`, or the lock leaks. | A `SELECT … FOR UPDATE` followed by a `raise`/`return` path with no `rollback()` first. |
| P3 | **Transaction-local reads inside locked transactions.** Reads that inform a decision made under a lock must run on the same session, not a separate-session helper. | `balance_of()` (opens its own session) called inside a `FOR UPDATE` transaction to gate a decision. Contrast: `_balance_of_in_session(db, …)`. |
| P4 | **No direct balance mutation — all money through the ledger.** Money moves via `ledger_post`/`ledger_post(session=db)`, never `wallet.balance = …` or direct account writes. | Direct `.balance =` assignment, or a bare INSERT to a balance-bearing row, on the money path. |
| P5 | **Arguments that scope money are actually used.** A function taking `league_id` (or team/week scoping) must apply it in its queries. | A scoping parameter accepted but absent from the WHERE clause. The `2384b14` defect class. |
| P6 | **Fail closed on unknown state.** Money-path branches on a status/enum must reject unrecognized values, not treat "not X" as "therefore Y." | An `if status == "COMPLETED" … else <proceed>` shape with no explicit reject of unknown/NULL. |
| P7 | **Idempotent claim-then-complete.** Any run-once money operation must have a durable claim that a retry can distinguish from a completed run — not a two-state boolean that reads "done" the instant it's claimed. | A run-once guard that permanently suppresses retries without distinguishing in-progress from complete. |
| P8 | **Once-only settlement guard present.** A settlement/payout path must have a guard preventing a second payout of the same obligation (balance-invariant or key-based). | A payout path with no double-pay protection. |

---

## 2 — Modules in scope (initial target list — recon confirms/extends)

Named money-path modules that predate the FR-8.7 protocols. The recon's first job is to confirm this list is complete (grep for every module that posts to the ledger, mutates a wallet, or writes a settlement/pot/escrow marker).

| Module | Why suspect | Highest-priority protocol to check |
|---|---|---|
| `betting/pool_engine.py` | **Top concern.** `PoolPot.settled` boolean guard — same "mark settled, pay out" shape as the `settle_week` bug FR-8.7 just fixed. Structural sibling. | P1 (settled-before-payout), P7, P8 |
| `beefs/beef_engine.py` | Accept path, escrow-at-issue, `_challenge_reserved`. Money-path, pre-protocol. | P2, P3, P4, P8 |
| `wallet/faab_wallet.py` | **Known open defect:** `transfer()` doesn't account for `challenge_reserved` — a GM could move soft-locked stake. Flagged, never fixed, never re-audited against escrow-at-issue. | P4, and the known `transfer()` gap |
| `ledger/ledger.py` | Core money primitive. Mostly trusted (FR-8.7 leaned on it), but confirm no separate-session gate inside a caller's transaction. | P3 |
| `betting/settlement_engine.py` (pre-FR-8.7 paths) | Single-party settlement branch, `_eval_*` helpers — were they audited, or only the beef branch FR-8.7 touched? | P1, P5, P6 |
| Any Stripe/deposit path (dormant) | `confirm_buyin_payment()`, deposit handling. Dormant but money-path. | P4, P8 |

---

## 3 — Method (read-only recon, per protocol)

For each protocol P1–P8, grep every in-scope module and produce a findings table: module / location / protocol / compliant? / evidence (quoted lines). No fixes. Existence-check rule throughout — quote live code, never assume.

Sequence:
1. **Confirm the module list** — grep the whole repo for ledger posts, wallet mutations, and settlement/pot/escrow markers; reconcile against §2.
2. **P1 sweep (highest value):** for every settlement/pot/payout path, find the completion marker and confirm it commits in the *same* transaction as, and *not before*, its payouts. `pool_engine.py` first.
3. **P2–P8 sweeps:** per the table.
4. **Findings register:** each violation → FR-8.8-{n}, four-part format (Name / Issue / Options / Recommendation & Reasoning). Classify launch-blocking vs. post-launch.

---

## 4 — Ruling & fix discipline

- Read-only recon produces findings only. No code without individual Fraser ruling.
- Every money-path fix goes through the Opus Math Review gate (issues-only, table format, each approved individually), same as FR-8.7.
- Launch-blockers (a live double-pay, strand, or cross-scope leak) fixed before Aug 1. Non-blockers → post-launch findings, tracked.
- Each fix committed standalone with its own register entry — never bundled (the lesson of `2384b14`).

---

## 5 — Slot in the launch path

- **Position:** after FR-8.7 tests (Step 6) and its Opus code-review gate, before final launch sign-off. FR-8.7 finishes first because it's the known live blocker; this audit catches the *unknown* ones.
- **Not a tooling project:** pure read-only grep sweep using existing tools. No new infrastructure.
- **Expected output:** a findings batch (FR-8.8-*), most likely dominated by whatever `pool_engine.py` P1 status turns out to be. If pool settlement has the settled-before-payout bug, that's a second launch-blocker of the same shape as FR-8.7 — and the FR-8.7 fix pattern (claim-first two-phase) is the ready-made remedy.

---

## 6 — The single most important question this audit answers

**Does `pool_engine.py` mark a pot settled before it pays out?**

If yes: it's the FR-8.7 bug in a second module, it's a launch-blocker, and we already have the fix pattern. If no: we've retired the highest-prior suspicion and can sweep the rest with lower urgency. Either way, we stop *guessing* whether the class recurs and *know*.
