# VAL-10 MODULE_SPEC
## BAB Top-Off Issuance Governance

**Revision:** Rev 23 (FROZEN — design approved)  
**Revision date:** 2026-07-21  
**Status:** Design APPROVED; Opus money-path review CLOSED; implementation authorization pending carried gates  
**Review gate:** Opus money-path review — CLOSED. Findings 1–15 resolved; composition gate FR-VAL10-z executed; Opus clean-close confirmed Rev 22 (no substantive issue)  
**Baseline:** HEAD `19aa0bef26d3e9e684c9722e3d0b5e35290d40ec`  
**Branch:** `remediation/foundation-phase-1`  
**Design session:** 2026-07-21

### Revision history

| Rev | Date | Change |
|---|---|---|
| 1 | 2026-07-21 | Initial MODULE_SPEC (R1–R10, findings a–v). |
| 2 | 2026-07-21 | Four pre-Opus fidelity fixes. |
| 3 | 2026-07-21 | Finding 1 → FR-VAL10-w. Findings a–w (23). |
| 4 | 2026-07-21 | Finding 2 → FR-VAL10-x (two-lock model). Findings a–x (24). |
| 5 | 2026-07-21 | Finding 3 → FR-VAL10-y. Findings a–y (25). |
| 6 | 2026-07-21 | Failure-boundary clarification: FR-VAL10-y init backstop pinned pre-write. |
| 7 | 2026-07-21 | Finding 4 → §3 Invariant 10 + FR-VAL10-aa. Register a–y + aa (26). |
| 8 | 2026-07-21 | Finding 5 → §3 Invariant 11 + FR-VAL10-ab (three-lock model) + carried GATING FR-VAL10-ac. Register a–y + aa, ab, ac. |
| 9 | 2026-07-21 | Contradiction fix (pre-send): §7 split authorization-attempt failure from rejection; §12 Part 2 no-op edge. |
| 10 | 2026-07-21 | Composition fixes (pre-send): §7 terminal-state no re-transition; §12 Part 4 two→three locks. |
| 11 | 2026-07-21 | Composition fixes (pre-send, no new finding): distinguished four negative-outcome categories (request rejection / authorization-attempt abort / integrity-attempt abort / terminal-state no-op). R6b snapshot anomaly and §5 steps 9–11 (snapshot, divisibility, missing `BabSeasonAllocation`) changed from "fail-closed rejection" to integrity-attempt abort (request stays pending). R7 step 3 and §5 step 3 sharpened from "reject if not pending" to terminal-state no-op. Added §7 integrity-failure subsection and a four-outcome taxonomy; §7 retitled. Updated FR-VAL10-w and -y register entries. Swept all reject/fail-closed uses. |
| 12 | 2026-07-21 | Opus Finding 6 resolved (Option B). Added FR-VAL10-ad (transactional disclosure durability): every approved issuance commits a self-contained disclosure-outbox record atomically with the issuance; `approved/applied` requires the disclosure record; async idempotent publication from the outbox. Added §10 disclosure-outbox table, §5 steps 19–21 (persist record → commit → async publish), §12 Part 2 disclosure biconditional, Part 4 commit set, Part 5 self-approval note. Register a–y + aa, ab, ac, ad (z reserved). |
| 13 | 2026-07-21 | Opus Finding 7 resolved. Added FR-VAL10-ae (approval/disclosure structural linkage): `FaabTransaction.disclosure_event_id` + portable CHECK enforcing the full R5 matrix; PostgreSQL FK; canonical ordering; three-way posting-group reconciliation. Added carried test-infra dependency FR-VAL10-af. Extended R5; reordered §5 18–19; added §10 CHECK and reconciliation; updated §12 Part 2. Register a–y + aa..af. |
| 14 | 2026-07-21 | Opus Finding 8 resolved (Preferred-staged). Enable `PRAGMA foreign_keys=ON` in the central connect hook; FK effective on both databases. FR-VAL10-af reclassified to required enforcement control. §10/FR-VAL10-ae/§12 updated. |
| 15 | 2026-07-21 | Opus Finding 9 resolved (proof-boundary): §12 Part 2 split commit-time structural vs post-commit semantic integrity; reconciliation reclassified as detection backstop; R5 field-list drift fixed. |
| 16 | 2026-07-21 | Opus Finding 10 resolved. Scoped the R5 CHECK by `tx.type` (FR-VAL10-ag) to reconcile with R9 waiver nullability and R5 legacy posture on the shared table; legacy via `val10_legacy_exempt` flag (A1). Register a–y + aa..ag. |
| 17 | 2026-07-21 | Opus Finding 11 resolved. "Self-approval reason missing" reclassified from request rejection to attempt-validation abort (FR-VAL10-ah); §7 fifth negative-outcome category + unifying principle. Register a–y + aa..ah. |
| 18 | 2026-07-21 | Opus Finding 12 resolved (Alternative). Removed `val10_legacy_exempt`; relocate unprovable historical `topup_bet` rows to application-read-only `faab_transaction_legacy` (FR-VAL10-ai). Governed table has no exempt branch. §12 proof total over `topup_bet`. Register a–y + aa..ai. |
| 19 | 2026-07-21 | Opus Finding 13 resolved (economic-model + credit-path recon). Historical cap consumption proven where `topup_bet`+`applied`+exact-cents+known team/season (FR-VAL10-aj), stored as `cap_consumption_cents`; cap sum = governed ledger + proven legacy. Four terminology tightenings. Register a–y + aa..aj. |
| 20 | 2026-07-21 | Opus Finding 14 resolved (composition). Scoped the legacy-table boundary precisely (FR-VAL10-ak): no write path; one narrow cap-accounting read; one history/audit read. Amended §10, FR-VAL10-ai, §12 Part 2. Register a–y + aa..ak. |
| 21 | 2026-07-21 | Opus Finding 15 resolved (composition). Aligned §10 no-writer sentence to the two-read-path boundary (FR-VAL10-ak); added FR-VAL10-al. Register a–y + aa..al (z reserved). |
| 22 | 2026-07-21 | FR-VAL10-z composition gate executed (Option 2: systematic sweep). Claim matrix over every repeated assertion verified for identical domain/exceptions/timing/failure-semantics/proof-strength. Two operative drifts corrected: §12 Part 4 "prior applied issuance"→two-source `prior_issued_topoff_cents`; §7 taxonomy item 3 "steps 9–11"→"9–12". Formally added FR-VAL10-z; register a–z + aa..al complete. Consolidated for Opus clean-close. |
| 23 | 2026-07-21 | **Opus clean-close: design APPROVED, money-path review CLOSED — no substantive issue in Rev 22.** Applied two non-blocking editorial cleanups (no mechanism/proof/economics change): §1 "approves the design finding-by-finding"→"confirms the consolidated composition-reviewed design"; §12 Part 2 now names historical-indeterminacy among integrity-attempt abort examples (matching §7 and §5 step 12). FROZEN copy. Implementation remains gated on FR-VAL10-ac, FR-VAL10-af, FR-VAL10-ai/-aj/-ak/-al, OPR-10. |

---

## 1. Purpose and Scope

VAL-10 defines the canonical governance, accounting, approval, and ledger behavior for **BAB Top-Offs**.

A BAB Top-Off is an additional in-app BAB credit issued to a GM during the season. Fantasy Beefs is a closed internal league economy. No real money is collected, held, transferred, processed, or settled by the application. Any real-world obligations among league members are handled outside the application.

VAL-10 applies only to the **bet-wallet BAB path**. Waiver top-ups remain outside this module.

Implementation remains unauthorized until the carried implementation gates are satisfied.

---

## 2. Canonical Terminology

### Season-Opening BAB Allocation
The frozen per-team BAB allocation established by the league economy tier for the season.

Schema anchor: `EconomyStop.wallet_cents`, where the current economy invariant is:

`wallet_cents = weekly_min_cents × 14`

### BAB Top-Off
An additional amount of BAB credited to a GM's bet wallet during the season.

### BAB Top-Off Cap
The maximum cumulative amount of BAB a GM may receive through BAB Top-Offs during a season.

`cap_cents = opening_allocation_cents × multiplier_bps / 10000`

### Remaining BAB Top-Off Capacity
The amount a GM may still receive:

`remaining_capacity_cents = cap_cents - prior_issued_topoff_cents`

where `prior_issued_topoff_cents` is BAB *actually issued* (governed ledger issuance + proven legacy cap consumption; FR-VAL10-aj), never mere requests or `type = topup_bet` labels.

### BAB Top-Off Cap Multiplier
A league-wide preseason setting represented in integer basis points.

Examples:
- `0` = 0%
- `5000` = 50%
- `10000` = 100% (default)
- `15000` = 150%
- `20000` = 200%

The same multiplier applies to every GM, including the Commissioner.

---

## 3. Governing Invariants

1. BAB issuance is represented in integer cents.
2. Every approved top-off produces exactly one balanced two-leg ledger posting.
3. The ledger is authoritative.
4. The request amount, approved amount, and issued amount are identical for every applied top-off.
5. A GM's cumulative issued top-offs may never exceed the frozen BAB Top-Off Cap.
6. Commissioner self-approval is permitted only when no eligible independent Commissioner exists, and even then only under the identical frozen cap as every other GM, with no personal increase or override, a mandatory reason, and league-visible disclosure. The permission and its bounding are one invariant and must never be cited apart.
7. Waiver top-ups cannot enter the BAB issuance path.
8. The temporary `Wallet.balance` mirror is compatibility state only and must be removed after all named read sites migrate to the ledger.
9. UI behavior may prevent illegal actions, but UI behavior is never the enforcement control.
10. **Derived-state authority.** Every mirror, snapshot, aggregate, or other derived value is written from its authoritative source, never calculated by incrementing, editing, or otherwise trusting its own prior derived value. Locks and transaction boundaries govern *when* the write occurs; this invariant governs *the basis* of the value written. Applications: `Wallet.balance` is recomputed from the ledger post-state; the multiplier snapshot is copied once from validated configuration and never subsequently edited; cumulative top-off issuance is recomputed from authoritative applied-issuance/ledger state, never maintained by incrementing an unverified cached total; `BabSeasonAllocation.opening_allocation_cents` is copied once from the validated Economy Tier and then frozen. This is the rule-level closure of the wrong-basis pattern surfaced by Findings 1, 2, and 4.
11. **Authorization stability.** Any role, permission, or eligibility determination that authorizes a money-path write must still be true when the write occurs. The authorizing state must either remain protected by a shared serialization lock held through commit, or be re-verified under that lock immediately before the authorized posting. A check performed earlier in the transaction is not sufficient if the underlying authority state may change concurrently. This applies to: the decision-maker's live Commissioner authority; the existence of another eligible independent Commissioner; and whether self-approval remains permissible. This is the authority-axis analog of Invariant 10 — 10 governs the basis of a derived *value*; 11 governs the freshness of an authorization *decision*.

---

## 4. Ruling Register

### R1 — Issuance Source Account

Use the dedicated league-season account:

`bab_issuance:{league_id}:{season}`

The issued total is:

`issued_total_cents = -balance_of(bab_issuance_account)`

The source is not `world`. The dedicated account provides an auditable BAB-issuance surface separate from other unbounded ledger sources.

### R2 — Funded-Guard Exemption

A debit from `bab_issuance:*` is exempt from the funded-account guard only when the posting door is exactly:

`approved_bab_topoff`

The exemption is door-bound. The account prefix alone is insufficient.

The only legal posting shape under this door is:

- debit `bab_issuance:{league_id}:{season}`
- credit `wallet:{team_id}`

The two amounts must be equal and opposite integer cents.

### R3 — Canonical Door

The canonical door is:

`approved_bab_topoff`

The constant `APPROVED_BAB_TOPOFF_DOOR` is defined in `ledger/ledger.py` and imported by the issuance module.

The door is limited to approved eligible BAB Top-Off issuance. It is not a generic mint, opening allocation, correction, refund, or waiver door.

### R4 — Destination Account

The destination account is:

`wallet:{team_id}`

`team_id` means `Team.id`.

The destination is derived from the persisted `FaabTransaction.team_id`. Caller-supplied ledger account text is prohibited.

### R5 — Approval Identity and Linkage Schema

`FaabTransaction` gains:

- `requester_user_id`
- `decided_by_user_id`
- `decision`
- `decision_reason`
- `decided_at`
- `ledger_posting_id`
- `disclosure_event_id` (FR-VAL10-ae; added for the disclosure biconditional)
- `amount_cents`

Migration posture:

- legacy rows may remain nullable where exact historical values or identities cannot be proven;
- all new BAB Top-Off requests require the new authoritative fields.

`ledger_posting_id` uses the same UUID type as `LedgerEntry.posting_id` and is unique when non-null.

Legal states:

| Decision | Status | Posting ID | Meaning |
|---|---|---:|---|
| pending | pending | absent | Awaiting decision |
| approved | applied | present | Issued |
| rejected | unapplied/rejected | absent | Denied |
| cancelled | cancelled | absent | Withdrawn/cancelled |

Biconditional (extended by FR-VAL10-ae to cover disclosure linkage):

`(decision == approved AND status == applied) iff (ledger_posting_id IS NOT NULL AND disclosure_event_id IS NOT NULL)`

For every other legal decision/status combination (pending/pending, rejected/rejected, cancelled/cancelled), **both** `ledger_posting_id` and `disclosure_event_id` are absent. The matrix is enforced portably by a CHECK constraint (FR-VAL10-ae) **scoped to `topup_bet` rows** (FR-VAL10-ag; there is no exemption — unprovable historical rows are relocated out of the table entirely per FR-VAL10-ai, so every `topup_bet` row in `FaabTransaction` satisfies the matrix). It both (a) requires both linkage fields present on approved/applied and (b) forbids either linkage field on any non-applied state — not merely "applied implies links present." This makes an `approved/applied` request without its disclosure obligation, and a non-applied request carrying stray linkage, both unrepresentable at commit on every supported database. Waiver rows and other non-issuance types are governed by separate branches of the same CHECK (linkage-absence fence), not by this approval-state biconditional — see FR-VAL10-ag and §10.

### R6a — Approval Authority and Commissioner Self-Approval

Live Commissioner authority is always required and must be verified from the current persisted user record inside the approval transaction, never from stale token claims.

Independent approval is required whenever another eligible Commissioner exists.

If no eligible independent Commissioner exists, the sole Commissioner may approve a top-off for their own team under the following controls:

- identical R6b cap formula;
- no personal cap increase or override;
- required non-empty decision reason;
- explicit self-approval classification where `requester_user_id == decided_by_user_id`;
- league-visible audit/activity disclosure;
- same atomic posting and state-write rules as any other approval.

The eligible-independent-approver predicate is dynamic. Promotion of a second Commissioner disables self-approval without a code change. Demotion back to a sole Commissioner re-enables it.

### R6b — BAB Top-Off Eligibility and Cap

The seasonal cap is:

`cap_cents = opening_allocation_cents × frozen_multiplier_bps / 10000`

Inputs:

- `opening_allocation_cents`: the **Season-Opening BAB Allocation** — the Wallet amount from the frozen League Economy Tier (`EconomyStop.wallet_cents = weekly_min_cents × 14`), NOT the internal Buy-In or Championship Reserve. Frozen into the `BabSeasonAllocation` record at initialization (FR-VAL10-x) and read from that record at approval, never re-read live from `get_league_economy_stop`. The cap is anchored to this Wallet allocation only;
- `frozen_multiplier_bps`: the multiplier read from the insert-only league-season snapshot record (FR-VAL10-w), fixed at season initialization.

Default multiplier: `10000` (100%).

Exact-cent policy (structural — FR-VAL10-y):

V1 permits only approved League Economy Tier allocations and approved BAB Top-Off Cap multipliers. Every permitted combination produces an exact integer-cent cap by construction. Unsupported allocation or multiplier values are rejected before season initialization.

- Permitted allocations are the five certified tier values `{7000, 14000, 21000, 28000, 35000}` cents (all multiples of 7000; enforced at HEAD by `validate_stop` and `set_league_economy_stop`).
- Permitted `bab_topoff_cap_multiplier_bps` values are `{0, 5000, 10000, 15000, 20000}` (all multiples of 100). The config setter rejects any other value at selection time.
- Because every permitted allocation is a multiple of 7000 and every permitted multiplier is a multiple of 100, `allocation × multiplier / 10000` is always a whole cent. The fractional-cent hazard cannot arise for any permitted combination.
- Backstop (integrity check, not a Commissioner-facing validation path): both initialization and approval assert `opening_allocation_cents × multiplier_bps % 10000 == 0`. On failure — fail closed, create no issuance, never round or truncate, record an integrity/audit event. This detects only corrupted or unsupported state that bypassed the menu constraints. **At initialization the assertion runs after the tier and multiplier values are resolved but before any multiplier snapshot, `BabSeasonAllocation` record, wallet initialization, or `season_initialized` state is written; a failure aborts initialization with no persistent season-initialization state, so the backstop cannot leave a partially-initialized season.**
- Approval never rounds or truncates the cap.

Cumulative headroom:

`remaining_capacity_cents = cap_cents - prior_issued_topoff_cents`

where (FR-VAL10-aj):

`prior_issued_topoff_cents = governed_ledger_issued_topoff_cents + proven_legacy_cap_consumption_cents`

- `governed_ledger_issued_topoff_cents`: the sum of BAB actually issued through the governed VAL-10 path for the same team and season — proven by ledger postings (`approved_bab_topoff` door), the authoritative future-issuance evidence.
- `proven_legacy_cap_consumption_cents`: the sum of `cap_consumption_cents` from relocated legacy records for the same team and season (FR-VAL10-aj) — migration-derived historical evidence, not a fabricated ledger posting. Counts only historical rows proven issued (see FR-VAL10-aj evidence rule); pending/rejected/cancelled/test rows count zero; genuinely broken historical records trigger a historically-indeterminate block for that team-season only.

"Received" means cumulative **issued** top-offs (governed ledger issuance + proven legacy consumption) — not requests submitted, rejected requests, pending requests, waiver activity, or the original Season-Opening BAB Allocation. The original allocation is never "Received." `type = topup_bet` alone is never issuance; the amount is never inferred from current wallet balance.

A BAB Top-Off increases spendable BAB (Available to Bet) only. It does not modify the Season-Opening BAB Allocation, Weekly Minimum, Championship Reserve, internal Buy-In, or Championship Pot seeding.

A request above remaining capacity is rejected in full. No partial approval, automatic reduction, or silent rewrite is permitted.

Zero-headroom causes must be distinguished:

1. top-offs disabled (`multiplier_bps == 0`);
2. no valid season allocation;
3. cap exhausted.

#### Freeze model

The multiplier snapshot is stored in a **dedicated, insert-only league-season allocation record**, distinct from the editable preseason configuration field. The record is created once, during season initialization, and is never updated in place by any application route, admin function, or governed migration (FR-VAL10-w).

Ordering:

1. Commissioner selects the multiplier on the editable live configuration (permitted only before season initialization).
2. `init_season_wallets()`: resolve the tier allocation and the selected multiplier; **assert `opening_allocation_cents × multiplier_bps % 10000 == 0` for every team before any write (FR-VAL10-y pre-write backstop) — on failure, abort with no persistent season-initialization state**; then copy the multiplier into the league-season snapshot record; establish the Season-Opening BAB Allocations and `BabSeasonAllocation` records.
3. `season_initialized = 1`.
4. Top-off requests become reachable.

Top-off creation is prohibited before season initialization.

The live config setter must reject writes after season initialization.

The snapshot record is insert-only: keyed to one league and season, written once at initialization, and never updated or replaced afterward by normal application code. It — not the live configuration — is the sole source read by top-off creation and approval.

Approval must read the frozen multiplier snapshot, not the live config value. Approval must also perform an integrity check (FR-VAL10-w) and fail closed on any anomaly:

- the required league-season snapshot exists;
- exactly one snapshot exists for that league and season;
- its league and season match the request;
- the computed cap uses that snapshot;
- the snapshot has not been superseded or replaced.

A missing, duplicate, mismatched, superseded, or inconsistent snapshot causes a fail-closed **approval-attempt abort** and an integrity/audit event: no economic or approval-state write occurs, and the request **remains pending** unless it independently became invalid. A corrupted system snapshot makes the approval path temporarily unsafe; it does not make the GM's request invalid, so it must not transition the request to rejected. This check is not permission to recompute the cap from live configuration; approval continues to read the frozen snapshot only.

**Correction mechanism.** There is no ordinary "edit frozen multiplier" function. A legitimate preseason mistake discovered after initialization requires a separately ruled, audited season-reset or correction protocol; it may not be handled by updating the snapshot record in place.

### R7 — Exactly-Once Issuance

The canonical approval flow:

1. row-lock the persisted `FaabTransaction`;
2. re-read decision and status under the lock;
3. if the request is no longer pending, abort the attempted decision with no state change — only a pending request may transition; an already-applied, rejected, or cancelled request is a terminal state and is never rewritten (this is a no-op, not a transition to rejected);
4. perform the ledger post, mirror write, approval-state transition, approver identity, timestamp, and linkage write in one caller-owned transaction;
5. commit once.

The ledger call must use:

`post(session=db)`

`session=None` is prohibited for this door.

The status re-read must occur after lock acquisition.

This closes, via the request-row lock:

- one request producing multiple postings;
- concurrent approval of the *same request* racing;
- crash windows between posting and state write.

The request-row lock does NOT close concurrent approval of *different requests consuming the same team-season cap* — that race is closed separately by the `BabSeasonAllocation` row lock (FR-VAL10-x). Both locks are mandatory and independent: the request-row lock guards same-request duplication; the allocation-row lock guards same-team cap consumption.

R5's unique `ledger_posting_id` closes a third direction: multiple requests attempting to claim one posting.

### R8 — Cents Representation

The submitted dollar amount is converted exactly once at request validation using:

`_dollars_to_cents`

Sub-cent requests are rejected. `_to_cents` is prohibited for the authoritative issuance path because it silently rounds.

The returned integer is persisted in:

`FaabTransaction.amount_cents`

`amount_cents` is the sole authoritative amount for:

- headroom checks;
- approval-time rechecks;
- ledger posting;
- reconciliation;
- audit;
- legacy mirror derivation.

The existing float `amount` field may remain temporarily for compatibility or display, but it is non-authoritative. Display values must be derived from `amount_cents`, never the reverse.

### R9 — Waiver Top-Off Treatment

Waiver top-ups are excluded from VAL-10.

They remain off-ledger and use the existing waiver reserve-to-application lifecycle.

Within shared top-off code, `tx.type` is a security boundary:

- `topup_bet` may enter the BAB issuance path;
- `topup_waiver` may not;
- unknown types reject;
- waiver code cannot construct an `approved_bab_topoff` posting;
- bet top-offs cannot execute the waiver branch.

Nullable VAL-10 approval fields on waiver rows are legal because waiver rows do not carry BAB-issuance semantics. This is enforced structurally, not only by code: the `tx.type`-scoped CHECK (FR-VAL10-ag) has a dedicated `topup_waiver` branch requiring both linkage fields absent while permitting null VAL-10 decision fields, so a waiver row can never carry issuance linkage and the R5 approval-state biconditional does not apply to it.

### R10 — Legacy `Wallet.balance` Mirror

Until every named bet-wallet funds gate and freeze check reads the ledger, approved issuance must:

- credit the ledger via `post(session=db)`;
- set `Wallet.balance` by **recomputing from the ledger post-state**: read `balance_of(wallet:{team_id})` through the same caller-owned session (so it sees this issuance's own uncommitted posting), and set `Wallet.balance` to that exact integer-cent balance converted for compatibility — never `Wallet.balance += amount`, never from the legacy float field, never from the mirror's own prior value;
- perform both in the same transaction, committing atomically.

The ledger is authoritative. The mirror is a pure function of the ledger post-state, re-anchored on every write (Governing Invariant 10; FR-VAL10-aa) — so it cannot compound prior drift, and an incrementing-float accumulation hazard cannot arise.

On any divergence, the ledger is correct.

Named exit checklist:

- `bet_engine.py:114`
- `beef_engine.py:571`
- `beef_engine.py:574`
- `faab_wallet.py:636`
- `faab_wallet.py:641`
- `faab_wallet.py:654`
- `faab_wallet.py:669`

The mirror is removed only after every named read site uses the ledger.

---

## 5. Canonical Approval Flow

Three locks participate. Two are acquired up front (request row, then `BabSeasonAllocation` row); the third (`AuthoritySerializationLock`) is acquired late, immediately before the authority revalidation and post, because it protects the final authorization decision, not the earlier cap work. Lock acquisition order is fixed — request row → `BabSeasonAllocation` → `AuthoritySerializationLock` — and must be identical on every path that takes any subset, or concurrent transactions could deadlock. Role transitions acquire only `AuthoritySerializationLock` (never a request or allocation lock), so no reverse-order cycle exists with the current design.

1. Load and row-lock the persisted `FaabTransaction` request row.
2. Row-lock the `BabSeasonAllocation` record for the request's team and season (FR-VAL10-x). Held through commit. Two sibling approvals for the same team contend on this one row; approvals for different teams lock different rows and do not block each other.
3. Re-read decision and status under the request-row lock; if the request is no longer pending, abort with no state change (terminal states are never rewritten — a no-op, not a transition to rejected). This re-read serializes concurrent approval of the *same request* (R7); the `BabSeasonAllocation` lock serializes concurrent approval of *different requests for the same team-season* (FR-VAL10-x).
4. Read requester identity from the locked request.
5. Preliminary authority check — verify the decision-maker's live Commissioner authority.
6. Preliminary — determine whether another eligible Commissioner exists.
7. Preliminary — enforce independent approval when one exists.
8. Preliminary — apply self-approval controls when none exists: the self-approval reason must be present and non-empty and the self-approval classification present. If attempt-supplied decision data (reason, classification, or decision input) is missing or malformed, this is an **attempt-validation abort** (FR-VAL10-ah): no ledger, mirror, outbox, linkage, or approval-state write; the request **remains pending**; the Commissioner may retry with valid data or another lawful approver may decide it — it is not rejected, because the defect is in the attempt, not the request. (Steps 5–8 are preliminary: they gate whether the flow proceeds, but the binding authority decision is revalidated under lock at step 15 — a preliminary check alone does not satisfy Invariant 11.)
9. Read the team's frozen `opening_allocation_cents` from the locked `BabSeasonAllocation` record. If the record is missing or invalid, this is an **integrity-attempt abort** (frozen system state is corrupt): no economic or approval-state write, integrity/audit event, and the request remains pending unless independently invalid.
10. Load the season's frozen BAB Top-Off Cap multiplier snapshot from the insert-only league-season snapshot record. Verify the snapshot exists, is unique for that league and season, matches the request's league and season, and has not been superseded (FR-VAL10-w); on any anomaly, **integrity-attempt abort** with an integrity/audit event — no economic or approval-state write, request remains pending unless independently invalid.
11. Compute the exact integer-cent cap from the frozen allocation and frozen multiplier. Assert `opening_allocation_cents × multiplier_bps % 10000 == 0` (FR-VAL10-y backstop); on failure, **integrity-attempt abort** — integrity/audit event, no issuance, no approval-state write, never round or truncate, request remains pending unless independently invalid.
12. Compute `prior_issued_topoff_cents` for the same team and season (FR-VAL10-aj): `governed_ledger_issued_topoff_cents` (ledger-proven governed issuance) + `proven_legacy_cap_consumption_cents` (sum of `cap_consumption_cents` on relocated legacy records for that team-season). Read under the `BabSeasonAllocation` lock, so a concurrent sibling approval cannot post between this read and commit. If the team-season carries an unresolved historical-indeterminacy flag (a legacy record with malformed/sub-cent amount, unknown team/season, or contradictory evidence — FR-VAL10-aj), this is an **integrity-attempt abort** for that team-season only: no economic or approval-state write, integrity/audit event, request remains pending; unrelated team-seasons proceed normally.
13. Compute remaining capacity.
14. Reject in full if the request exceeds remaining capacity.
15. **Authority revalidation under lock (Invariant 11, FR-VAL10-ab).** Acquire `AuthoritySerializationLock`; re-read the decision-maker's persisted live role; recompute the eligible-independent-approver predicate; confirm the selected independent/self-approval path is still lawful. If authority changed — the decision-maker is no longer Commissioner, or an eligible independent Commissioner now exists making a self-approval unlawful — abort with **no** economic effect: no post, no mirror, no metadata, no linkage. The request **remains pending** (not rejected) when another lawful approver may still decide it; it is rejected only if the request itself became independently invalid. Hold `AuthoritySerializationLock` through commit.
16. Post the two-leg balanced issuance using `post(session=db)`.
17. Read the post-issuance balance of `wallet:{team_id}` through the same database session used by `post(session=db)`, then set `Wallet.balance` to that exact integer-cent ledger balance converted for compatibility display/storage. Never increment the existing mirror, never write from the legacy float request field, never write from the mirror's own prior value (Governing Invariant 10; FR-VAL10-aa).
18. Persist one self-contained disclosure-outbox record (FR-VAL10-ad) carrying the full immutable payload — event type, self-approval classification, league, season, request id, posting id, requester, approver, team, `amount_cents`, decision reason, decision timestamp, durable event id, creation timestamp. Fully reconstructable without re-resolving mutable live state. If this write fails, the entire issuance transaction rolls back.
19. Persist approval metadata and status, setting **both** `ledger_posting_id` (from the posting) and `disclosure_event_id` (from the persisted outbox record's durable event id — never caller-supplied text). The R5 CHECK constraint (FR-VAL10-ae) requires both present for `approved/applied`; a missing either aborts the transaction.
20. Commit once, releasing all three locks. The `approved/applied` transition, the posting linkage, and the disclosure obligation commit atomically together — an issuance is applied only if both linkage fields committed with it.
21. Asynchronously publish the committed outbox record to the activity feed, idempotently, with retries. Publication failure cannot erase or invalidate the committed disclosure obligation; the durable record — not the feed delivery — is the disclosure of record.

Failure of any check produces no ledger posting, no wallet mutation, and no economically applied request.

**Role-transition path (`promote_user`).** Begin a caller-owned transaction; lock `AuthoritySerializationLock`; re-read the target user; validate and apply the role transition; commit once. It acquires only `AuthoritySerializationLock` — never a request or `BabSeasonAllocation` lock. Any future path that takes both authority and money-path locks must follow the canonical order (request → allocation → authority) and receive explicit review.

---

## 6. Posting Specification

For `amount_cents > 0`:

| Account | Amount |
|---|---:|
| `bab_issuance:{league_id}:{season}` | `-amount_cents` |
| `wallet:{team_id}` | `+amount_cents` |

Direct arithmetic:

`(-amount_cents) + (+amount_cents) = 0`

No other leg is legal under `approved_bab_topoff`.

---

## 7. Negative-Outcome Semantics (Rejection, Aborts, No-ops)

### Creation-time rejection

If the request is invalid before a `FaabTransaction` is created, no transaction row is created.

Examples:

- season not initialized;
- no valid season allocation;
- top-offs disabled;
- amount exceeds remaining capacity;
- sub-cent amount;
- malformed amount.

### Approval-time rejection

If a pending request becomes *independently invalid* before approval, the existing request remains economically unapplied and transitions to the legal rejected state.

Examples (the request itself became invalid while still pending):

- prior issuance consumed headroom;
- the request exceeds remaining capacity;
- the request type is not `topup_bet`;
- the authoritative request amount is invalid or corrupted;
- the pending request independently became invalid before decision.

Only a request in the pending state can transition to rejected. A request already approved, rejected, or cancelled is a legal terminal state and is **not transitioned again**: an attempted decision on it aborts with no state change. In particular, a `cancelled` request retains its `cancelled/cancelled` state (R5) and is simply non-decidable — it never becomes `rejected`, and an already-applied request is never rewritten.

No partial issuance is permitted.

### Approval-attempt authorization failure

Distinct from rejection. If final authority revalidation (§5 step 15, FR-VAL10-ab) fails because:

- the decision-maker is no longer a Commissioner; or
- an independent Commissioner now exists and self-approval is no longer permitted,

then:

- no economic or approval-state write occurs;
- the attempted decision aborts;
- the request **remains pending** when another lawful Commissioner may still decide it;
- the request is rejected **only** if it independently became invalid (per the rejection examples above).

The distinction is load-bearing: an *unauthorized attempt* is not an *invalid request*. A role change during one approval attempt invalidates that attempt, not the request — which may still be lawfully decided by an eligible approver. Marking such a request rejected would contradict FR-VAL10-ab and the Invariant 11 pending semantics.

No partial issuance is permitted.

### Approval-attempt integrity failure

Distinct from both rejection and authorization failure. An integrity failure in frozen system state — a missing, duplicate, mismatched, superseded, or inconsistent multiplier snapshot; an approval-time divisibility-assertion failure; a missing or invalid `BabSeasonAllocation` record discovered during approval; or an unresolved historical-indeterminacy flag on the team-season (a legacy cap-consumption record that cannot be cleanly quantified — FR-VAL10-aj) — aborts the attempted decision with no economic or approval-state effect and records an integrity/audit event. The request **remains pending** unless it independently became invalid. Corrupt system state (or unquantifiable historical issuance) makes the approval path temporarily unsafe for that team-season; it does not make the GM's request invalid, so it must never transition the request to rejected. A historical-indeterminacy flag blocks only its own team-season; unrelated team-seasons proceed normally.

### Approval-attempt validation failure

Distinct from rejection. When attempt-specific decision data supplied during the approval is missing or invalid — a required self-approval reason absent or empty, malformed decision input, or a required self-approval classification absent — the attempt aborts with no economic or approval-state effect:

- no ledger, mirror, outbox, linkage, or approval-state write occurs;
- the attempted decision aborts;
- the request **remains pending**;
- the Commissioner may retry with valid decision data, or another lawful approver may decide it.

The distinction is load-bearing and parallels the authority case: `decision_reason` and classification are supplied by the *decision-maker during the attempt*, not intrinsic properties of the pending GM request. A defective form does not invalidate the request — it invalidates that one attempt. Marking the request rejected because a sole Commissioner omitted a reason would permanently deny a request that is still valid for a retry or for an independent approver, making the outcome depend on *who attempted* rather than on the request's own validity.

### Taxonomy of negative outcomes

Five distinct outcomes must never be conflated. The governing principle: **only the request becoming independently invalid writes `rejected`; every other negative outcome is a no-transition abort that leaves the request decidable.**

1. **Request rejection** — a *pending* request independently became invalid (over capacity, wrong type, corrupted amount). Transitions to the `rejected` terminal state. Also covers creation-time input rejection (before any request row exists).
2. **Authorization-attempt abort** — the decision-maker's authority changed (§5 step 15). No state change; request stays pending for a lawful approver.
3. **Integrity-attempt abort** — frozen system state is corrupt, or historical issuance is unquantifiable (§5 steps 9–12). No state change; request stays pending; integrity/audit event.
4. **Attempt-validation abort** — attempt-supplied decision data (self-approval reason, classification, decision input) is missing or malformed (§5 steps 5–8). No state change; the Commissioner may retry or another approver may decide.
5. **Terminal-state no-op** — the request is already applied, rejected, or cancelled. No state change; the terminal state is never rewritten.

Only outcome 1 writes a state transition. Outcomes 2–5 are non-writes: the request's persisted state is unchanged. The dividing line is always the same — did the *request* become invalid (outcome 1), or did a particular *attempt* fail for a reason extrinsic to the request (outcomes 2–5)?

---

## 8. User-Facing Rules Language

**Terminology separation (do not imply real money enters the app).** GM-facing language uses **League Economy Tier**, **Season-Opening BAB Allocation**, and **Available to Bet**. Internal schema may retain the `wallet_cents`, `reserve`, and Buy-In column names, but "Buy-In" is an internal/backend label, not GM-facing copy. Nothing in GM-facing surfaces should imply the application collects or processes real currency; a top-off is the league issuing more of its own in-app BAB, never a cash deposit.

### BAB Top-Offs

Each GM may request additional BAB during the season, subject to the league's BAB Top-Off Cap.

Before the season is initialized, the Commissioner selects a league-wide BAB Top-Off Cap. The setting applies equally to every GM, including the Commissioner, and is locked for the season.

A GM's BAB Top-Off Cap is calculated from the GM's Season-Opening BAB Allocation and the league's locked cap setting. The cap is cumulative across the season.

A request above the GM's Remaining BAB Top-Off Capacity is rejected in full. The system does not automatically reduce or partially approve the request.

The Commissioner approves BAB Top-Off requests. When no other eligible Commissioner exists, the Commissioner may approve a request for their own team within the same system-enforced cap. Commissioner self-approvals require a written reason and are disclosed in the league activity log.

BAB is an in-app league accounting unit. Fantasy Beefs does not collect, hold, transfer, process, or settle real money.

---

## 9. UI Obligations

### GM request surface

Show:

- current BAB balance;
- BAB Top-Off Cap;
- BAB Top-Offs already issued this season;
- Remaining BAB Top-Off Capacity;
- requested amount;
- rejection reason.

Over-cap message:

> Your requested BAB Top-Off exceeds your Remaining BAB Top-Off Capacity of X BAB. Submit a new amount.

Do not offer automatic reduction.

### Commissioner queue

Show:

- GM/team;
- requested amount;
- remaining capacity;
- request time;
- status;
- Approve;
- Reject.

Approval must recheck capacity.

### Commissioner self-approval

Show:

- explicit self-approval label;
- mandatory reason field;
- same cap and capacity figures;
- league-visible disclosure notice.

### Commissioner setting

Label:

**BAB Top-Off Cap**

Description:

> Sets the maximum total additional BAB each GM may receive during the season.

Recommended choices:

- Disabled — 0%
- 50%
- 100% — default
- 150%
- 200%

Show a live example based on the Season-Opening BAB Allocation.

Before initialization: editable.  
After initialization: read-only with **Locked for this season**.

### Activity log

Independent approval:

> BAB Top-Off Approved: Team Alpha received 50 BAB. Approved by Commissioner.

Self-approval:

> Commissioner Self-Approved BAB Top-Off: Commissioner's Team received 50 BAB. Reason: [reason].

---

## 10. Schema and Migration Specification

### `FaabTransaction`

Add:

- `requester_user_id`
- `decided_by_user_id`
- `decision`
- `decision_reason`
- `decided_at`
- `ledger_posting_id`
- `disclosure_event_id` (FR-VAL10-ae)
- `amount_cents`

Constraints:

- `ledger_posting_id` unique when non-null;
- `disclosure_event_id` unique when non-null; single-direction FK to the disclosure-outbox durable event id (FR-VAL10-ae). With `PRAGMA foreign_keys=ON` enabled on every SQLite connection (FR-VAL10-af), this FK enforces referenced-row existence on **both** PostgreSQL and SQLite — a dangling `disclosure_event_id` is rejected at insert on either database.
- `val10_legacy_exempt` is **removed** — no exemption flag or dormant CHECK branch remains (FR-VAL10-ai). Unprovable historical rows are relocated out of the governed table entirely (see Legacy relocation below), so there is nothing in `FaabTransaction` for a new row to masquerade as.
- **Portable CHECK constraint (load-bearing, FR-VAL10-ae, scoped by `tx.type` per FR-VAL10-ag)** — honored on PostgreSQL and SQLite, branching exhaustively on `tx.type` (NOT NULL, value-constrained by `ck_faab_tx_type`, aligned with R9's `tx.type` boundary):
  - **`topup_bet`** (no exemption): the full R5 matrix, with no legacy carve-out —
    `(decision=approved AND status=applied AND ledger_posting_id IS NOT NULL AND disclosure_event_id IS NOT NULL)`
    OR `(decision/status ∈ {pending/pending, rejected/rejected, cancelled/cancelled} AND ledger_posting_id IS NULL AND disclosure_event_id IS NULL)`. Every `topup_bet` row in `FaabTransaction` satisfies this; there is no exempt branch.
  - **`topup_waiver`**: `ledger_posting_id IS NULL AND disclosure_event_id IS NULL`; VAL-10 decision fields may be null (R9 fence).
  - **Other known non-issuance types** (`opening_credit`, retained historical transfer types): both linkage fields absent; no access to the approved/applied state combination.
  - **Unknown or null `tx.type`**: default-deny. The CHECK and `ck_faab_tx_type` must remain aligned.
- new top-off requests require authoritative `amount_cents`;
- do not invent historical requester identities or cents values.

### Legacy relocation (FR-VAL10-ai)

Add a dedicated `faab_transaction_legacy` table for unprovable pre-VAL-10 `topup_bet` rows. Migration behavior, in one controlled transaction where the database supports transactional DDL/data migration (equivalent safely-ordered process where it does not):

1. classify every pre-migration `topup_bet` row;
2. backfill rows whose lawful R5 state and authoritative fields can be proven — these stay in `FaabTransaction`;
3. copy unprovable rows into `faab_transaction_legacy` with available source values and explicit migration provenance;
4. verify the copied population (count + identity reconciliation — no row lost or duplicated);
5. remove the relocated rows from `FaabTransaction`;
6. install the governed CHECK with no legacy branch.

Legacy-table contents (preserve, do not fabricate): original `FaabTransaction.id`; original type, status, amount, team, league, timestamps, available identities; source-table name; migration revision; migration timestamp; explicit reason the row could not be lawfully backfilled; a stable legacy-record identity; and — for cap-consumption preservation (FR-VAL10-aj) — a `cap_consumption_cents` field holding the proven historical issuance amount (the exact persisted cents where `type = topup_bet`, `status = applied`, team and season known, and amount converts exactly to integer cents), or zero for non-economic rows (pending/rejected/cancelled/test), or a historical-indeterminacy flag where the amount is malformed/sub-cent, the team/season is unknown, or the evidence is contradictory. `cap_consumption_cents` is migration-derived historical evidence, not a fabricated VAL-10 ledger posting; the amount is never inferred from current wallet balance and no retroactive ledger posting is created. Do not fabricate missing cents, posting ids, disclosure ids, requester identities, or decision states.

**Application-unreachable historical storage (honest proof boundary).** The legacy table's isolation is an *architectural no-writer* guarantee, not a database-immutability claim: no ORM or service write function exists for it; no route, approval flow, posting flow, or admin function inserts/updates/deletes its rows; it is populated only by the migration; application access is read-only and limited to two purposes (FR-VAL10-ak) — unified history/audit retrieval, and the narrowly scoped cap-accounting read of `team_id`, `league_id`, `season`, `cap_consumption_cents`, and historical-indeterminacy state for the matching team-season; and repository recon plus tests verify no application writer exists. This is not a claim that a DBA or raw SQL physically cannot alter the table — only that no application path can. Stated honestly rather than overclaimed.

### History compatibility

`get_faab_transactions` returns unified per-team history from live governed `FaabTransaction` rows **and** relocated `faab_transaction_legacy` rows (union), so relocation is not a history-completeness regression. Legacy rows are clearly classified as historical/unverified and are never returned as pending, approvable, or economically actionable. `confirm_topup` continues to read only live pending rows in `FaabTransaction` (never legacy). The legacy table is excluded from request, approval-state, posting, issuance, settlement, and **all write** paths. The cap gate has **one narrowly defined read-only exception** (FR-VAL10-ak): during the headroom calculation it reads, for the matching team-season under the `BabSeasonAllocation` lock, only these legacy fields — `team_id`, `league_id`, `season`, `cap_consumption_cents`, and historical-indeterminacy state. Approval may not treat a legacy row as a request, lock it as an approval object, transition it, post from it, or attach disclosure/linkage to it. Unified history additionally reads the legacy display/audit fields.

### Disclosure outbox

Add a disclosure-outbox table. Exactly one record is persisted per approved BAB Top-Off issuance, in the same caller-owned transaction as the issuance (FR-VAL10-ad). Self-contained immutable payload — fully reconstructable without re-resolving mutable live user/team/role/request state:

- event type
- self-approval classification (whether `requester_user_id == approver_user_id`)
- league id
- season
- request id
- posting id
- requester user id
- approver user id
- team id
- `amount_cents`
- decision reason (mandatory and non-empty for self-approval; nullable for independent approval only if the governing approval rules allow)
- decision timestamp
- durable event id
- creation timestamp
- delivery status and retry metadata

Structural controls:

- unique disclosure identity (durable event id);
- unique approved-top-off request linkage and unique posting linkage (or an equivalent constraint) preventing duplicate disclosure obligations;
- no deletion of an undelivered record through normal application paths;
- the publisher is idempotent (re-publishing a delivered record is a no-op).

Foreign keys may be retained for traceability, but publication uses the snapshotted payload, never a rebuild from current user/team/role/request data.

### Three-way reconciliation (FR-VAL10-ae)

A reconciliation job verifies the identity `FaabTransaction ↔ ledger posting ↔ disclosure outbox` for every `approved/applied` request, as the runtime backstop to the CHECK and FK (it catches semantic mismatches the structural constraints cannot — e.g. a payload field disagreeing with the request — on both databases):

- the request's `ledger_posting_id` identifies exactly one valid two-leg `approved_bab_topoff` posting **group** — `posting_id` identifies the balanced group (a debit leg and a credit leg sharing the id), not one globally unique ledger row (`ledger_entries.posting_id` is unique per account, not per posting);
- that group contains the correct issuance-source (`bab_issuance:*`) and `wallet:{team}` legs with equal-opposite `amount_cents` summing to zero;
- the request's `disclosure_event_id` identifies exactly one outbox record;
- the outbox payload's request id and posting id match the same request and posting group;
- requester, approver, team, `amount_cents`, league, season, self-approval classification, and reason agree across the request, the posting group, and the outbox payload.

Any mismatch is a reconciliation alarm (integrity event), never a silent correction.

### Authority serialization lock

Add `AuthoritySerializationLock` — a dedicated singleton row representing the global Commissioner-authority domain at the current baseline (Commissioner role is global at HEAD: `User` has no `league_id`, `promote_user` is the sole runtime role mutator). Exactly one canonical row, database-enforced (fixed primary key or unique canonical key — not an application-process mutex), created by migration or bootstrap before any role change or approval is reachable, never deleted or replaced. It is locked by every runtime `User.role` mutation (`promote_user`) and by every BAB Top-Off approval immediately before final authority revalidation (§5 step 15), held through commit (FR-VAL10-ab). Its global scope is intentional — it matches the current global Commissioner role; a per-league lock would under-protect the global eligible-approver predicate. If authority ever becomes league-scoped, narrowing this lock requires a separately reviewed authority-model migration.

### Per-team-season issuance-control record

Add `BabSeasonAllocation` — exactly one record per team and season, enforced by `UniqueConstraint("league_id", "team_id", "season")` (the same composite-uniqueness idiom the codebase already uses for `shortfall_sweep_records` and `pool_predictions`). It contains at minimum:

- `league_id`
- `team_id`
- `season`
- frozen `opening_allocation_cents` (the team's Season-Opening BAB Allocation)
- reference to (or unambiguous identity for) the league-season multiplier snapshot
- creation timestamp

Created once during `init_season_wallets()`, alongside the Season-Opening BAB Allocation and the multiplier snapshot. Stable for the entire season; never replaced. It is the per-team-season lock target for the cap gate (FR-VAL10-x) and the source the cap computation reads the frozen allocation from. It is distinct from the FR-VAL10-w multiplier snapshot: the snapshot is per-league-season (one multiplier for the league); `BabSeasonAllocation` is per-team-season (one allocation and one lock per team).

### League economy configuration

Add:

- `bab_topoff_cap_multiplier_bps`, integer, default `10000` — the editable preseason configuration field. Permitted values are constrained to the menu `{0, 5000, 10000, 15000, 20000}`; the config setter rejects any other value at selection time (FR-VAL10-y).

Add a **dedicated, insert-only league-season snapshot record** (distinct from the config field above), keyed to one league and season, storing the multiplier copied at initialization. This record is the sole source read by top-off creation and approval (FR-VAL10-w).

Write rules:

- live config field editable only before season initialization;
- post-init setter attempts on the live config field reject;
- the snapshot record is written exactly once, at initialization, and is never updated or replaced in place by any application route, admin function, or governed migration;
- approval reads the snapshot record, never the live config field, and fails closed on a missing, duplicate, mismatched, or superseded snapshot;
- correction of a post-init mistake requires a separately governed season-reset/correction protocol, never an in-place snapshot update.

### Ledger

Add:

- `APPROVED_BAB_TOPOFF_DOOR`;
- door-bound funded-guard exemption for `bab_issuance:*`.

### Enum cleanup

Dead retired transfer values are removed only inside the same migration that already rewrites the affected `FaabTransaction` constraint for the R5 columns. This cleanup does not justify a standalone migration and is not performed if that constraint rewrite is not already occurring (FR-VAL10-a).

---

## 11. Finding and Test Register

### Structure and governance

- **FR-VAL10-a:** Dead transfer enum values may be cleaned in the migration.
- **FR-VAL10-b:** the legacy audit log is precedent only, not the approval record.
- **FR-VAL10-c:** Use one canonical construction point for the issuance account key.
- **FR-VAL10-d:** The door has exactly one legal posting shape.
- **FR-VAL10-e:** Door constant lives in the ledger module.
- **FR-VAL10-f:** No wallet-key helper exists; use the live `wallet:{team_id}` convention verbatim.
- **FR-VAL10-g:** Enforce the decision/status matrix and posting-link biconditional.
- **FR-VAL10-h:** Link request and posting by matching UUID type.
- **FR-VAL10-i:** Verify authority from the live user row.
- **FR-VAL10-j:** Independent-approver availability is dynamic.
- **FR-VAL10-k:** The eligible-independent-approver predicate requires dedicated tests.

### Money-path invariants

- **FR-VAL10-l:** `post(session=db)` is mandatory.
- **FR-VAL10-m:** Concurrency tests must use real overlapping transactions.
- **FR-VAL10-n:** `_dollars_to_cents` is the sole legal converter.
- **FR-VAL10-o:** Test the waiver fence in both directions.
- **FR-VAL10-p:** Test mirror atomicity, cent agreement, and recompute-not-increment. After issuance, `Wallet.balance × 100 == balance_of(wallet:{team})`; and starting from a deliberately-drifted mirror, one issuance re-anchors it to ledger truth (proving recompute, not increment — an incrementing implementation passes the clean-mirror test but fails this one). See FR-VAL10-aa for the full test set.
- **FR-VAL10-q:** Track the mirror exit checklist as an implementation obligation.
- **FR-VAL10-r:** Headroom non-negativity is an inductive invariant preserved only because every issuance path applies the cap gate while holding the corresponding `BabSeasonAllocation` row lock (FR-VAL10-x). Without that lock the induction fails: a concurrent sibling approval could read stale prior-applied issuance and breach the cap.
- **FR-VAL10-s:** Lock ordering is enforced structurally by the FaabWallet-existence barrier: `create_bet_topup()` requires a FaabWallet that only `init_season_wallets()` creates, and the multiplier is snapshotted in that same initialization, so no top-off can be reached while the multiplier is still editable. Test: editable before initialization, immutable after, and no top-off reachable while editable.
- **FR-VAL10-t:** The setter must reject post-initialization writes.
- **FR-VAL10-u:** Snapshot the multiplier at initialization; approval reads the snapshot, not live config.
- **FR-VAL10-v:** Distinguish the three zero-headroom causes in rejection responses.
- **FR-VAL10-w:** Structural multiplier-snapshot immutability. The BAB Top-Off Cap multiplier is stored in a dedicated, insert-only league-season snapshot record created during season initialization. No normal application path may update or replace it after creation. Top-off creation and approval read only this snapshot, never live configuration. On a missing, duplicate, mismatched, superseded, or inconsistent snapshot, approval performs an integrity-attempt abort (§7): no economic or approval-state write, integrity/audit event, request remains pending unless independently invalid — never a transition to rejected. Any correction requires a separately governed protocol and may not mutate the frozen snapshot in place. Required tests: no application path can update the snapshot after initialization; approval aborts (request stays pending) on anomalous snapshot state; cap computation reads the snapshot rather than live configuration.
- **FR-VAL10-x:** Per-team-season cap-gate serialization. Season initialization creates exactly one stable `BabSeasonAllocation` record per team and season, enforced by a composite unique constraint on league, team, and season. Every BAB Top-Off approval locks that record before calculating cumulative prior issuance and holds the lock through ledger posting, request-state transition, mirror update, and commit. The request-row lock prevents duplicate approval of one request; the allocation-row lock prevents sibling requests from consuming the same stale headroom. Both locks are mandatory. Lock acquisition order is fixed (request row, then allocation row) to prevent deadlock. Required tests: two concurrent same-team approvals against a cap must yield one issuance and one rejection, not two issuances, under genuinely overlapping transactions; two concurrent different-team approvals must not block each other.
- **FR-VAL10-y:** Structural exact-cent cap enforcement. V1 restricts Season-Opening BAB Allocations to the approved League Economy Tier values `{7000,14000,21000,28000,35000}` cents and restricts `bab_topoff_cap_multiplier_bps` to `{0, 5000, 10000, 15000, 20000}`. Every permitted allocation-and-multiplier combination produces an exact integer-cent cap by construction (permitted allocations are multiples of 7000; permitted multipliers are multiples of 100; the product always divides by 10000). Unsupported values reject before season initialization, enforced at the config setter (multiplier menu) and the existing tier setter (allocation). Initialization and approval repeat the assertion `opening_allocation_cents × multiplier_bps % 10000 == 0` as a fail-closed integrity backstop; neither path may round or truncate. At initialization a failure aborts init pre-write with no persistent season-initialization state (see below). At approval a failure is an integrity-attempt abort (§7): no issuance, no approval-state write, integrity/audit event, request remains pending unless independently invalid. At initialization the assertion runs after the tier and multiplier values are resolved but before any multiplier snapshot, `BabSeasonAllocation` record, wallet initialization, or `season_initialized` state is written, so a failure aborts initialization with no persistent season-initialization state and cannot leave a partially-initialized season. Confirmed against HEAD 19aa0be: allocations are always `EconomyStop.wallet_cents = weekly_min_cents × 14` from the five certified tiers, `set_league_economy_stop` rejects non-tier values, and the free-form `opening_bet` field is a distinct FAAB-config quantity, not the allocation — so no custom-allocation path exists and Option (b) is sufficient without a per-team init-validation gate. Required tests: config setter rejects out-of-menu multipliers; the approval-time divisibility backstop aborts (request stays pending) on a synthetically corrupted allocation/multiplier pair; every tier×menu combination computes an exact whole-cent cap.

- **FR-VAL10-aa:** Mirror recompute from authoritative ledger state. After the issuance posting is staged with `post(session=db)`, the compatibility mirror is set from the wallet ledger account's post-state balance using the same caller-owned session. `Wallet.balance` must never be updated through `+= amount`, from the legacy float request field, or from its own prior value. The mirror write, ledger posting, request-state transition, and linkage commit atomically. Required tests: (1) after issuance, the mirror equals the wallet ledger balance converted from integer cents; (2) beginning from a deliberately drifted mirror, one approved issuance re-anchors it to ledger truth; (3) the in-transaction balance read sees the uncommitted issuance posting; (4) failure of the mirror write rolls back the ledger post and approval state; (5) no float participates before the final compatibility conversion from exact ledger cents.
- **FR-VAL10-ab:** Authority-state serialization. A dedicated singleton `AuthoritySerializationLock` row represents the global Commissioner-authority domain at the current baseline. Every runtime Commissioner promotion or demotion and every BAB Top-Off approval's final authority revalidation locks this row. Approval acquires it after the request and `BabSeasonAllocation` locks, re-verifies persisted authority and the eligible-independent-approver predicate, and holds it through posting and commit. A self-approval may post only if no eligible independent Commissioner exists at that protected point. If authority changed, the attempted decision produces no economic effect and the request remains pending when another lawful approver may decide it (not rejected merely because authority changed). Three-lock order: request row → `BabSeasonAllocation` → `AuthoritySerializationLock`; `promote_user` takes only the authority lock, so no reverse-order cycle exists. Required tests: (1) promotion racing a self-approval past its preliminary check — the self-approval must not post; (2) demotion racing an independent approval — the decision-maker's authority is re-evaluated before posting; (3) demotion to sole Commissioner makes later self-approval available with no code change; (4) stale token claims cannot override persisted role state; (5) failed revalidation leaves posting, mirror, and linkage absent; (6) the request remains pending when it can still be lawfully decided.
- **FR-VAL10-ac (carried implementation dependency — GATING):** Commissioner availability dependency. HEAD permits demotion of the final Commissioner (`promote_user` has no last-Commissioner guard). VAL-10 does not own role-management policy, but its approval lifecycle depends on at least one eligible Commissioner existing — a zero-Commissioner state makes all pending top-offs permanently undecidable and prevents restoration through the Commissioner-gated promotion route. Before VAL-10 implementation is authorized, the role-management subsystem must either prevent removal of the final Commissioner or provide a separately governed recovery path that restores Commissioner authority without relying on an existing Commissioner. This is a carried dependency, not a change to BAB issuance economics; it remains a gate until the role-management owner supplies one of those two guarantees.
- **FR-VAL10-ad:** Transactional disclosure durability. Every approved BAB Top-Off issuance persists one self-contained disclosure-outbox record in the same caller-owned transaction as the ledger posting, mirror recomputation, approval state, approver identity, decision metadata, and posting linkage. An `approved/applied` request is legal only if its disclosure record commits atomically with it — this makes R6a's league-visible-disclosure condition of self-approval a structural guarantee, not a post-commit side effect. The payload is self-contained (event type, self-approval classification, league, season, request id, posting id, requester, approver, team, `amount_cents`, decision reason, decision timestamp, durable event id, creation timestamp) and reconstructable without re-resolving mutable live state. External activity-feed publication occurs after commit from the durable record, is idempotent, and retries until delivered; publication failure cannot erase or invalidate the committed obligation. Applies to all approved issuances (Option B — one durable path, not a self-approval-only path); self-approval is the Blocking governance case because R6a makes disclosure a condition of permission. Integrity-attempt events may use the same outbox but are not part of the approved-issuance biconditional (no issuance occurs). Structural controls: unique disclosure identity; unique request and posting linkage (or equivalent) preventing duplicate obligations; delivery-status/retry metadata; idempotent publisher; no normal-path deletion of an undelivered record. Required tests: an issuance cannot commit without its disclosure record (simulated disclosure-write failure rolls back the whole issuance); self-approval with no persisted disclosure record is unreachable; publication is idempotent under retry; the outbox payload publishes correctly without live-table joins; a self-approval disclosure has a non-empty reason.

- **FR-VAL10-ae:** Approval/disclosure structural linkage. The Part 2 biconditional ("applied requires disclosure") is delivered by four controls with distinct, non-overlapping roles — three enforce at commit, one detects after:
  - **CHECK constraint** — enforces legal state/linkage *shape* at commit, **scoped to `topup_bet` rows** (FR-VAL10-ag; no exemption — unprovable historical rows are relocated out of the table per FR-VAL10-ai): `(approved AND applied)` iff `(ledger_posting_id AND disclosure_event_id both present)`, both absent for every non-applied state. Portable across PostgreSQL and SQLite. Enforces shape, not referenced-row existence. Waiver and other non-issuance rows fall under separate branches of the same CHECK, not this matrix.
  - **FK** (`FaabTransaction.disclosure_event_id` → outbox durable event id) — enforces referenced-row *existence* at commit, effective on both databases with `PRAGMA foreign_keys=ON` (FR-VAL10-af). A dangling id is rejected at insert.
  - **Uniqueness** (`disclosure_event_id` and `ledger_posting_id` unique-when-non-null) — prevents *duplicate* linkage at commit.
  - **Reconciliation** — *detects* post-commit *semantic disagreement* among request, two-leg posting group, and outbox payload (team, amount, requester, approver, league, season, posting id, reason). This is a detection backstop, **not** a commit-time preventive control; semantic agreement is established by the canonical transaction, not made database-unrepresentable.

  Together the three commit-time controls make an applied request with missing linkage or a dangling reference unrepresentable at commit; reconciliation catches semantic mismatches the structural constraints cannot. Canonical application ordering (post → mirror → persist outbox → set both linkage ids from persisted rows → commit) sets `disclosure_event_id` from the persisted outbox object, never caller-supplied text, and is what establishes semantic agreement in the first place. Reconciliation treats `posting_id` as a balanced two-leg posting group, not a globally unique row. Required tests: portable CHECK tests (approved/applied without either linkage rejected; non-applied with stray linkage rejected); a nonexistent `disclosure_event_id` rejected on SQLite (with FK-on) and PostgreSQL; the complete approval transaction succeeds when the outbox row exists; a direct applied-state write with a dangling disclosure id fails on both databases; a reconciliation test detecting a semantically-mismatched-but-structurally-valid payload; canonical-order tests; a PostgreSQL integration test for production-dialect parity.
- **FR-VAL10-af (required implementation and test-fidelity control):** SQLite foreign-key enforcement. Every SQLite connection created by the canonical engine enables `PRAGMA foreign_keys=ON`, added to the existing central connect hook (`db/session.py`, alongside the WAL/busy_timeout pragmas), so all application and test connections through the single `get_engine()` factory enforce foreign keys. The test suite must run with enforcement active; `PRAGMA foreign_keys` must return `1`. Dangling disclosure and other foreign-key references must fail. Any fixture exposed as invalid by enablement must be corrected to create its required parent rows — no blanket opt-outs, no disabling FK enforcement around failing tests. PostgreSQL integration tests remain mandatory for production-dialect parity. Implementation sequence: (1) add the pragma to the connect hook; (2) verify it returns `1`; (3) run the full suite; (4) repair fixtures creating dangling references; (5) no opt-outs; (6) preserve PostgreSQL integration tests. This is no longer a documented limitation — enabling FK-on *resolves* the system-wide SQLite FK-fidelity gap, making every FK-based invariant test-enforced. Fixture triage is a bounded implementation task and does not reopen the design; implementation authorization remains blocked until the suite passes with SQLite FK enforcement active.

- **FR-VAL10-ag:** Shared-table state-domain scoping. The R5 state/linkage CHECK applies by `FaabTransaction.tx.type`, not globally (the table is shared with waiver, opening-credit, and other non-issuance rows; a global CHECK would reject lawful null-bearing waiver rows — R9). The CHECK branches exhaustively: `topup_bet` rows satisfy the complete R5 matrix (no exemption — see FR-VAL10-ai); `topup_waiver` and other known non-issuance rows require both linkage fields absent (cannot carry BAB-issuance linkage); unknown/null `tx.type` is default-denied (aligned with `ck_faab_tx_type` and R9's `tx.type` boundary). Unprovable pre-migration `topup_bet` rows are not exempted in place — they are relocated out of the governed table (FR-VAL10-ai), so no exemption flag or legacy CHECK branch exists. Required tests: governed bet rows satisfy the matrix; waiver rows with null VAL-10 fields and no links are accepted; other non-issuance types with no links accepted; unknown/null `tx.type` rejected; no `val10_legacy_exempt` flag or legacy branch exists in the schema.

- **FR-VAL10-ah:** Attempt-specific validation semantics. Attempt-supplied decision data (self-approval reason present and non-empty, self-approval classification, decision input) is validated during the approval attempt; if missing or malformed, the attempt aborts with no ledger/mirror/outbox/linkage/approval-state write and the request **remains pending** — the Commissioner may retry or another lawful approver may decide it. A defective attempt does not invalidate the request; classification of the negative outcome depends on the request's own validity, never on who attempted the decision or how. `decision_reason` and classification are attempt properties, not intrinsic request properties, so their absence is an attempt-validation abort (outcome 4 of the §7 taxonomy), not request rejection. This closes the Rev 16 miscategorization that would have permanently rejected a valid request on a sole Commissioner's incomplete form. Required tests: a self-approval with an empty/absent reason aborts and leaves the request pending (not rejected); the same request is then approvable by retry-with-reason or by an independent Commissioner; malformed decision input aborts without state change; only genuine request-invalidity (wrong type, over-capacity, corrupted amount) writes rejected.

- **FR-VAL10-ai:** Historical-row isolation. Unprovable pre-VAL-10 `topup_bet` rows are relocated from `FaabTransaction` into a dedicated application-read-only `faab_transaction_legacy` table. The governed table contains no exemption flag or legacy CHECK branch (`val10_legacy_exempt` is removed); every `topup_bet` row remaining in it satisfies the complete R5 matrix, so a new row cannot masquerade as legacy because the legacy category does not exist in the governed table — the bypass is eliminated by relocation, not guarded by a flag. Provable historical rows are backfilled and retained. The legacy table is populated only by migration, has no application writer, and is excluded from request, approval-state, posting, issuance, settlement, and all write paths — with **one narrow read-only exception**: the cap gate reads proven `cap_consumption_cents` and historical-indeterminacy state for the matching team-season under the `BabSeasonAllocation` lock (FR-VAL10-aj, FR-VAL10-ak). The table is also included in unified historical/audit reads. Isolation is an **architectural no-writer guarantee** (no ORM/service/route/admin write path exists; verifiable by repository recon and tests), stated honestly — not a database-immutability claim that a DBA or raw SQL cannot alter the table. Required tests: all governed `topup_bet` rows satisfy R5; no exempt flag or branch remains in the schema; provable historical rows backfilled; unprovable rows relocated with provenance; relocated rows absent from the governed table; history includes both populations without presenting legacy rows as actionable; approval by a legacy-table id fails; **cap calculation includes matching proven legacy consumption; cap calculation detects matching historical indeterminacy; approval never loads a legacy row as an actionable request; issuance, posting, settlement, and all write paths do not access the legacy table; unrelated team-season legacy rows do not affect the cap**; repository/application paths contain no legacy-table writer (grep + test); migration count and identity reconciliation proves no row lost or duplicated.

- **FR-VAL10-aj:** Historical cap-consumption preservation. A real pre-VAL-10 bettable-BAB credit path existed (`confirm_topup` → `wm_deposit` → `Wallet.balance += amount`, and pre-edit a self-serve mock path in `create_bet_topup`), so historical `topup_bet` rows can represent genuine issuance — but the credit was a float column mutation with no ledger posting, so historical issuance is proven under an explicit legacy evidence rule, not by a ledger entry the old system never produced. Evidence rule: a historical row consumes cap where `type = topup_bet` AND `status = applied` AND team known AND season known AND amount converts exactly to integer cents — its exact persisted amount is stored as `cap_consumption_cents` on the relocated legacy record. Non-economic (count zero): pending, rejected, cancelled, test/non-production, never-confirmed/never-applied rows. Historically indeterminate (block that team-season only, via integrity-attempt abort): missing/malformed amount, sub-cent/non-exact amount, unknown team/season, contradictory status-vs-economic evidence, or irreconcilable duplicates. The cap sum becomes `prior_issued_topoff_cents = governed_ledger_issued_topoff_cents + proven_legacy_cap_consumption_cents`, same-team same-season only. Never treat `type = topup_bet` alone as issuance; never infer amount from current wallet balance; never fabricate a retroactive ledger posting; preserve the old row and migration provenance for why an amount was counted. Required tests: a historical applied row with exact amount consumes cap; old mock-path and commissioner-confirmed rows treated consistently; pending rows consume zero; governed + legacy issuance sums correctly; malformed applied history blocks only its team-season; no current wallet balance used to infer historical issuance; no retroactive ledger posting fabricated.

- **FR-VAL10-ak:** Legacy-table read-boundary composition. The relocated `faab_transaction_legacy` table has exactly one write-path status and two read-path statuses, stated so no section contradicts another. **Write:** none — populated only by migration, no application writer (FR-VAL10-ai). **Read 1 (cap accounting):** the cap gate reads, for the matching team-season under the `BabSeasonAllocation` lock, only `team_id`, `league_id`, `season`, `cap_consumption_cents`, and historical-indeterminacy state (FR-VAL10-aj) — it may not treat a legacy row as a request, lock it as an approval object, transition it, post from it, or attach disclosure/linkage. **Read 2 (history/audit):** unified history reads the display/audit fields. All other paths — request creation, approval-state, posting, issuance, settlement — ignore the table entirely. This resolves the Rev 18↔Rev 19 contradiction where Finding 12's "cap paths ignore the legacy table" survived alongside Finding 13's requirement that the cap sum include proven legacy consumption. Required tests (superset of FR-VAL10-ai's cap tests): the cap read touches only the five permitted fields; no write path accesses the table; approval cannot load a legacy row as actionable; the two read paths are the only accesses.

- **FR-VAL10-al:** Legacy access-boundary wording closure. Every prose-level declaration of legacy-table access across the spec must state the same boundary as FR-VAL10-ak — read-only, exactly two purposes (history/audit retrieval; the five-field cap-accounting read), no application write path. This finding closes a stale §10 no-writer sentence ("read-only, limited to history/audit retrieval") that survived the Finding 14 fix and still stated the pre-Finding-14 single-read model, contradicting the operative boundary in the adjacent History-compatibility section, FR-VAL10-ai/aj/ak, and §12 Part 2. Prose duplicates drift independently of structured sections; the composition gate (FR-VAL10-z) must therefore sweep duplicate *access-boundary statements*, not only register entries and proof sections. Required test: FR-VAL10-ak's composition test asserts every prose-level legacy-access declaration matches the two-read-path boundary (no sentence narrower or broader).

- **FR-VAL10-z:** Composition-review gate (executed). A systematic cross-section sweep of every repeated design assertion, run once against Rev 21 to close the review rather than discover duplicate-language drift one Opus finding at a time (the mode that produced Findings 14 and 15). Method: a claim matrix, one row per repeated assertion, columns per section, verifying identical domain, exceptions, timing, failure-semantics, and proof-strength; that the mechanism actually supports the wording; and no stale field names, step numbers, counts, or prior-revision qualifiers. Claims swept: cap formula and two-source prior-issuance sum; lock count/order/scope/release; negative-outcome classifications and step references; request-state matrix and linkage biconditional; disclosure durability vs publication; structural vs semantic proof boundaries; waiver fence; legacy-table write/read boundary; historical evidence classification; mirror recompute; snapshot immutability; Commissioner authority and self-approval; exact-cent constraints; terminology and real-money disclaimers; and every "cannot / only / immutable / unavailable / exactly / unrepresentable" claim. Drifts found and corrected in Rev 22: (1) §12 Part 4 said "cap-gate read of prior applied issuance" — replaced with the two-source `prior_issued_topoff_cents` (governed ledger + proven legacy, FR-VAL10-aj); (2) §7 taxonomy item 3 cited integrity aborts as "§5 steps 9–11" — corrected to "9–12" (historical indeterminacy is the step-12 integrity abort). All other swept claims verified consistent across sections (values, domains, timing, and failure-semantics identical; mechanisms support the wording). Scope explicitly includes duplicate *prose access-boundary statements* (FR-VAL10-al), not only register entries and proof sections. This is the composition gate the review deferred to `z`; its execution consumes the reserved slot.

**Register note:** the interim findings run a–y then aa, ab, … al (the a–y-then-aa lettering is the original finding-by-finding sequence). The letter **z** was held reserved throughout for FR-VAL10-z, the composition gate, and is placed **last** — after al — because it is the closing gate that swept all the entries before it. So the register reads a–y, aa–al, then z as the final composition-review entry. No entry is dropped; the sequence is complete and z is now filled.

### OPR-10 carried gate

The OPR-10 24-value reset remains a separate hard gate and must be satisfied during implementation.

---

## 12. Internal Consistency Proof

### Part 1 — Posting arithmetic

Proven.

The only legal posting contains two equal-opposite integer-cent legs and sums to zero.

### Part 2 — State-machine completeness

Proven.

The four legal states are exhaustive. No ruling authorizes a posting ID on a non-applied request or an applied request without a posting ID.

**Commit-time structural integrity (`topup_bet` rows).** Every `topup_bet` row in `FaabTransaction` is governed by the complete R5 state/linkage matrix — there is no exemption qualifier (unprovable historical rows are relocated to `faab_transaction_legacy`, outside the live state machine, per FR-VAL10-ai). For those rows, an applied request with missing linkage or a dangling disclosure reference is **unrepresentable at commit on every supported database**, enforced by two controls together (FR-VAL10-ae, FR-VAL10-af): the CHECK enforces state/linkage *shape* (portable across PostgreSQL and SQLite), and the FK enforces referenced-row *existence* (effective on both databases with `PRAGMA foreign_keys=ON`). Remove either and the guarantee weakens. Uniqueness additionally prevents duplicate linkage identifiers. These are commit-time guarantees: the malformed state cannot be persisted.

`topup_waiver` and other known non-issuance rows are governed by the linkage-absence fence (both linkage fields null), not by the approval-state biconditional (R9, FR-VAL10-ag). The relocated legacy population is outside the live state machine and carries no money-path *authority* — it is never a request, never approvable, never posted from, never written by the application — but it is read in exactly two ways: unified historical/audit display, and the narrow cap-accounting read of `cap_consumption_cents` + indeterminacy state for the matching team-season (FR-VAL10-aj, FR-VAL10-ak). It is never presented as pending, approvable, or economically actionable.

**Post-commit semantic integrity.** Cross-record *agreement* — that the request, the two-leg posting group, and the disclosure payload all describe the same economic event (same team, amount, requester, approver, league, season, posting id, reason) — is established by the canonical approval transaction and verified after commit by reconciliation (FR-VAL10-ae). A mismatch (e.g. an outbox payload naming the wrong team or amount while all linkage ids are valid and unique) is *detectable* by reconciliation but is **not** currently database-unrepresentable at commit. Reconciliation is a detection backstop, not a commit-time preventive control; the proof does not claim otherwise. Making semantic agreement structurally unrepresentable at commit would require additional constraints beyond the current design and is not asserted here.

An **aborted approval attempt causes no state transition** (FR-VAL10-ab, FR-VAL10-ah, §7): when final authority revalidation fails, when frozen system state is corrupt (a bad multiplier snapshot, a divisibility-assertion failure, a missing `BabSeasonAllocation` record, or an unresolved historical-indeterminacy flag on the team-season — §5 step 12, FR-VAL10-aj), or when attempt-supplied decision data (self-approval reason, classification, decision input) is missing or malformed, the request is not moved to rejected — it stays in its prior state (pending) so a retry or another lawful approver may decide it. These are not new states; they are the *absence* of a transition (no-op edges back to pending). The rejected state is reached only by independent request-invalidity, never by an authority, integrity, or attempt-validation failure of a particular attempt. So the four-state machine remains exhaustive: attempt failures don't add a state, they add no-op edges back to pending.

### Part 3 — Ceiling arithmetic

Proven.

Both cap inputs are frozen integers. Exact-cent safety is structural (FR-VAL10-y): permitted allocations `{7000,14000,21000,28000,35000}` (multiples of 7000) times permitted multipliers `{0,5000,10000,15000,20000}` (multiples of 100) always divide by 10000 to a whole cent, so no permitted combination is fractional; unsupported values reject before initialization, and a divisibility assertion at init and approval backstops any corrupted state fail-closed. Every issuance consumes no more than current headroom, where headroom = `cap_cents - prior_issued_topoff_cents` and `prior_issued_topoff_cents` sums governed ledger-proven issuance plus proven legacy cap-consumption (FR-VAL10-aj) — both in exact integer cents, never inferred from wallet balance. This preserves headroom ≥ 0 inductively, contingent on the FR-VAL10-x per-team-season lock; a team-season with unquantifiable historical issuance is blocked (integrity-attempt abort) rather than approved against an uncertain prior sum.

### Part 4 — Atomicity

Proven, contingent on FR-VAL10-x and FR-VAL10-ab.

Three locks participate, acquired in fixed order to prevent deadlock. Two precede the cap reads: the request-row lock (same-request serialization) and the `BabSeasonAllocation` row lock (same-team-season cap serialization). The third, `AuthoritySerializationLock`, is acquired *late* — immediately before the final authority revalidation and post — because it protects authorization stability (Invariant 11), not the cap read; acquiring it late minimizes contention on the global authority row. The cap-gate computation of `prior_issued_topoff_cents` (governed ledger issuance plus proven legacy cap-consumption, FR-VAL10-aj) occurs under the allocation lock, so a concurrent sibling approval cannot post between that read and commit; the authority revalidation occurs under the authority lock, so a concurrent role transition cannot invalidate the decision between revalidation and commit. Posting, mirror, decision, status, approver, timestamps, linkage, and the disclosure-outbox record (FR-VAL10-ad) commit together, releasing all three locks. `session=None` is prohibited. Cap-gate atomicity is delivered by the allocation-row lock (Finding 2); authorization atomicity by the authority lock (Finding 5); neither is delivered by the request-row lock alone.

### Part 5 — Authority

Proven by design.

Authority is live. Independent approval is dynamic. Self-approval is permitted only when structurally necessary and remains bounded by the same cap, whose multiplier is immutable by storage shape and lifecycle (FR-VAL10-w) rather than by assertion or a single guarded setter. The boundedness of self-approval rests on a delivered immutability, not a claimed one. The *authorization* decision is stabilized against concurrent role change (Invariant 11, FR-VAL10-ab): the eligible-approver predicate and live role are re-verified under the `AuthoritySerializationLock` immediately before posting, held through commit, and a role transition must take the same lock — so a self-approval cannot post if a promotion made it unlawful after the preliminary check. This proof is design-level; the concurrent promotion/demotion race tests (FR-VAL10-ab) are the recorded test obligation, and it is contingent on the carried FR-VAL10-ac guarantee that at least one eligible Commissioner exists. R6a's league-visible-disclosure condition of self-approval is made structural by FR-VAL10-ad: a self-approval reaches `applied` only if its disclosure record committed atomically, so the permission's disclosure condition cannot fail after the money moved.

### Part 6 — Representation

Proven.

Amounts and multipliers remain integer-based. No float participates in authoritative issuance or cap arithmetic.

### Part 7 — Authority transition

Recorded test obligation; not yet demonstrated.

Required tests:

- promoting a second Commissioner disables self-approval without a code change;
- demoting back to a sole Commissioner re-enables self-approval;
- stale token claims do not override the live role state.

---

## 13. Opus Review Instructions

Review issues only.

For each issue, use:

1. **Finding**
2. **Risk**
3. **Required correction**
4. **Approval status**

Approve findings one-by-one.

Highest-value scrutiny targets:

1. multiplier setter lock;
2. multiplier snapshot immutability;
3. approval-time cap calculation;
4. row-lock and exactly-once composition;
5. `post(session=db)` enforcement;
6. mirror atomicity;
7. state-matrix reachability;
8. dynamic Commissioner transition behavior.

---

## 14. Authorization State

Revision: **Rev 23** (2026-07-21) — **FROZEN, design approved**  
Design: **APPROVED; Opus money-path review CLOSED**  
Internal self-check: **six proven; one test obligation recorded**  
Opus review: **CLOSED — Findings 1–15 resolved; FR-VAL10-z executed; Opus clean-close confirmed Rev 22 with no substantive issue**  
Implementation: **unauthorized — gated on: carried FR-VAL10-ac (last-Commissioner guarantee); FR-VAL10-af (suite passes with SQLite FK enforcement active); FR-VAL10-ai/-aj/-ak/-al legacy relocation, cap-consumption, and access-boundary migration tests; OPR-10 reset**

No code, migration, or test implementation may begin until FR-VAL10-ac, FR-VAL10-af, FR-VAL10-ai/-aj/-ak/-al, and OPR-10 are satisfied.
