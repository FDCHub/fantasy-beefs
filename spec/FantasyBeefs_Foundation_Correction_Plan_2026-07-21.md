# Fantasy Beefs — Foundation Correction Plan

**Status:** FINAL. Documentation-only. No code, schema, migration, or test is written or authorized by this document.
**Date:** 2026-07-21
**Thread type:** Plan-only.
**Branch:** `remediation/foundation-phase-1` @ `a8ef2e2`.
**Authority:** Findings Register v12.2 §§7–12 (§12 is the plan home); cleared spec text where propagated (Spec 1 Rev 3, Spec 2 v2). Code is evidence, never authority.
**Input:** Step 1 recon, register Section 13. Production is empty on every money-bearing table. That posture is assumed valid and re-stated per finding, not re-derived.

**Two design rulings folded in (2026-07-21):**
- **Ruling 1 — Event identity topology.** Generalized `ProtocolEvent` table is the single idempotency authority. Sharpens P1-L6.
- **Ruling 2 — Wallet scaffolding.** The 12 wallet + 12 faab_wallet rows are reviewed non-economic scaffolding; ledger starts at zero. Sharpens P1-L2 / P1-L3A migration touch.

**Locked build sequence — do not reorder:**
P1-L2 → P1-L3B → P1-L6 → P1-L7 → **then** P1-L4.

The four primitives are the ground P1-L4 stands on. Escrow-at-issue posts real money through the ledger, gates on funded balance, keys on event identity, and locks the row. It uses all four. Build it last, or build it twice.

---

## A standing note on line numbers

Section 12 §7 rules that recorded line references are 2026-07-20 evidence, not fixed coordinates. Section 13 re-grepped at HEAD and confirmed all findings still live, some with a wider footprint. Every location below carries a **re-grep-at-build** flag. Recorded is not still-live until re-verified against the branch on the day the fix ships. No exception.

---

## Section 1 — P1-L2: off-ledger balance mutation

**Defect.** Money paths write `.balance` directly, skipping the ledger. The ledger is the source of truth. A direct write is a lie the ledger never hears.

**Live at HEAD (re-grep required).**
- `wallet_manager.deposit` — `w.balance = round(...)`, no `ledger_post`. Reached via `faab init_season` and `create_bet_topup`.
- `faab_wallet.transfer` — two float mutation sites.
- Extended by P2-W5 (`settlement_engine` single-party credit, now scope-narrowed under the P3-S1 retirement).

**Governing authority.** Section 12 §1 (Foundation blocker) and §3 (Foundation home). Preserve the integer-cent zero-sum ledger and the funded-balance guard (§5).

**Correction shape (described, not coded).** Route every balance change on a money path through the ledger primitive. No direct `.balance =` write survives on any money path. The `.balance` float, if it stays, becomes a derived display mirror of the ledger, never an authority.

**Migration touch — sharpened by Ruling 2.** Intersects the P1-L3A float-column reshape and the wallet-scaffolding reset. Flag: **REVIEWED-BACKFILL** — 12 wallet rows and 12 faab_wallet rows exist, but hold no ledger-backed economic history. Row-level structural reshape, not a money backfill. The scaffolding rows are reset to zero under the reviewed protocol in Section 6; the ledger begins at zero; no opening-balance postings are created.

**Test obligations.** An off-ledger-write regression test that fails if any money path writes `.balance` directly. Zero-sum preserved across deposit and transfer. Fixture data where the float and the ledger cents diverge — equal or clean-dividing values prove nothing.

---

## Section 2 — P1-L3B: float funding gate

**Defect.** Funding decisions read the float `.balance`, not the ledger cents. The gate asks the wrong oracle.

**Live at HEAD (re-grep required).**
- `beef_engine._place_beef_side` — `wallet.balance < amount` on a float.
- Absorbs P2-W4 — `faab_wallet.transfer` second gate.

**Governing authority.** Section 12 §1, §3, §3a (P2-W4 absorbed here).

**Correction shape.** Every funding and withdrawal gate reads the integer-cent ledger balance. No money decision consults a float.

**Migration touch.** None of its own. Rides the P1-L2 / P1-L3A reshape.

**Test obligations.** Gate correctness at the single-cent boundary. A fixture where the float balance and the ledger-cent balance disagree, so a float-reading gate and a ledger-reading gate return different verdicts. That divergence is the whole test.

---

## Section 3 — P1-L6: event-identity primitive (RULED — generalized ProtocolEvent)

**Defect.** The ledger has no durable, unique protocol-event identity. `post()` mints its own `posting_id` per call. Idempotency and once-only-settlement key on balance, not on the event. A balance can be reached two ways; an event id cannot.

**Live at HEAD (re-grep required).**
- `post()` in `ledger.py` — `posting_id = uuid.uuid4()`, no external event arg.
- `LedgerEntry` carries no `event_id` / `challenge_id` / `bet_id`.
- Absorbs P3-S2 — the beef-only, balance-keyed settlement guard folds into the shared identity.

**Governing authority.** Section 12 §1, §3 (shared infrastructure — built once, keyed by many), §3a. This primitive also serves pool settlement (P4-B5) and the system-wide concurrency pattern. Build it right once.

**Correction shape — RULED topology.** Three durable tiers, each owning one identity concern:

```
ProtocolEvent  1 → many  LedgerPostingBatch  1 → many  LedgerEntry
```

- **`ProtocolEvent`** — a generalized, persistent domain-event record. It is the **single idempotency authority**, with a database-enforced `UNIQUE(event_id)`. It must support challenge, Beef, pool, buy-in, settlement, shortfall, and any other governed money operation — not challenges only. One event may produce several balanced posting batches during a complex atomic operation.
- **`LedgerPostingBatch`** — the balanced accounting-transaction identity. The existing `posting_id` is retained as this batch identity, but it must be durably associated with its governing `ProtocolEvent`. One batch contains multiple ledger legs and sums to zero.
- **`LedgerEntry`** — an individual accounting leg. It stays simple. A denormalized `event_id` may be retained on the entry **for traceability only**; it is not the idempotency authority and must not create a second event home. There is **no independent `LedgerEntry`-level uniqueness rule** for `event_id`.

Idempotency asks "does this `ProtocolEvent` exist," not "is this ledger row unique." Once-only-settlement fires on the event key, not on a reconstructed balance.

The `post()` signature change is source-compatible with the inventoried 10 callers (Register §3 recon), all passing `session=db`; the new event argument is optional and trailing, covered by a test matrix across `session=db` and `session=None`.

**Migration touch.** New `ProtocolEvent` and `LedgerPostingBatch` structures; `LedgerEntry` gains a batch reference (and optional denormalized `event_id` for traceability). Flag: **CLEAN-RECREATE / ALTER** — ledger holds 0 rows. Clean forward migration on empty tables.

**Test obligations.** A duplicate event re-post returns the original result and posts once (`UNIQUE(event_id)` on `ProtocolEvent`). The once-only guard fires on the event key, not the balance. One event spanning multiple balanced batches is enforced idempotent at the event level, with each batch still zero-sum. Full `post()` caller matrix across both session modes.

**Build-time flag (mandatory).** Re-grep `post()`, `posting_id`, and all callers at HEAD before the migration. Confirm the 10-caller `session=db` inventory and the self-minted `posting_id` still hold on the branch the day this ships.

> The re-grep must confirm no caller passes trailing positional arguments to `post()` — not merely that the new event argument is optional. A trailing positional would bind `event_id` by position and break. (Obligation 2, OPR-2.)

---

## Section 4 — P1-L7: lock discipline

**Defect.** No deterministic row lock on the money-path reads in issue and accept. Two racers read the same balance, both pass, both commit. The gap between read and write is where the double-spend lives.

**Live at HEAD (re-grep required).**
- No `FOR UPDATE` / `with_for_update` in `beef_engine.py` issue or accept paths.
- `_balance_of_in_session` is a lock-free SUM.
- REPEATABLE READ is set too late in the transaction to be relied on.

**Governing authority.** Section 12 §1, §3. The P3-S3 `week_settlements` lock is CONFIRMED sound (§5) — **preserve it, model on it, do not regress it.** Spec 2 recon confirms no existing Wallet-row lock, so this establishes the first canonical order: ascending `team_id`, no deadlock.

**Correction shape.** Row-lock the money-path reads that precede a posting, on ascending `team_id`. Do not rely on the isolation level. Consistent with the retained settlement lock.

> The mutex is the `Wallet` row's existence, not its value. The row is team-keyed (12 rows); the funding scope is team-season. Confirm the row grain is at least as coarse as the funding scope — team-coarser-than-team-season over-serializes harmlessly; a scope finer than the row would leave the mutex absent. Guarantee the row's presence by constraint, not by seeding. (Obligation 4, OPR-5.)

**Migration touch.** None. Behavioral, not structural.

**Test obligations.** Two racing issues by one team cannot both pass the funds check. Two concurrent accepts by overlapping teams serialize by ascending `team_id` with no deadlock. The test passes on the explicit lock, not on the isolation set — a REPEATABLE-READ-non-reliance assertion.

---

## Section 5 — P1-L4: issue-time challenge escrow (Spec 2 core deliverable)

Builds last, on the four above. This is the Spec 2 core, not a fifth prerequisite.

**Defect.** `issue_challenge` posts zero to the ledger. The stake is soft-reserved only, through `_challenge_reserved` — a display ghost, not real money. No `escrow:challenge:` account exists anywhere.

**Live at HEAD (re-grep required).**
- `beef_engine.issue_challenge` — zero `ledger_post`.
- `beef_engine` posts only at accept.
- `_challenge_reserved` — 6 call sites: accept check, issue check, counter check, transfer availability, 2 display models.
- No `escrow:challenge:` string anywhere.

**Governing authority.** Spec 2 v2, Opus-cleared. A1: issue posts real money to `escrow:challenge:{challenge_id}`, drawn min-first-then-wallet. `_challenge_reserved` retired from availability math at all 6 sites — once real escrow debits the wallet, subtracting a soft reservation double-counts. Spec 1 Rev 3 bundled as the named dependency (stake fields, accepted-proposal, escrow seam). Opus dispositions MS-2-2 (Anchor funding follows `anchor_team_id`, the original issuer, not proposal authorship) and MS-2-3 (acceptance re-reads and revalidates capacity under lock; on shortfall, post nothing, create no Bets, leave the challenge open) are integrated and govern.

**Correction shape.** At issue, post real issuer Anchor escrow to `escrow:challenge:{id}`, source-split min-first-then-wallet, with ordered append-only funding-leg provenance. Retire `_challenge_reserved`: the 4 functional gates switch to real-escrow-aware availability; the 2 display models read the new provenance. This is the first source-aware Versus funding subsystem, not "move wallet to escrow." Every posting batch here is a `ProtocolEvent` under the Section 3 topology.

**Lifecycle scope — non-negotiable.** Issue-time escrow does not ship without its complete lifecycle. Each terminal reverses or transfers the exact challenge escrow:
- **Decline → Declined**, **issuer withdrawal → Cancelled**, **TTL/kickoff lapse → Expired** — each refunds the exact escrow via strict reverse-leg reversal (last leg first, per recorded order).
- **Expiry** runs the dedicated fail-closed `expire_challenge` transaction: row-lock, verify open and deadline passed, reconcile actual escrow to expected funded Anchor, refund, set Expired, commit once. Escrow ≠ expected → no refund, no Expired, `reconciliation_error` audit.
- **Acceptance reconciliation** trues up issuer challenge escrow to the selected Anchor (refund excess or top up deficiency, min-first on any top-up delta), migrates Anchor to Bet escrow, escrows recipient Derived, all in one atomic commit. If a counter changed the stake, the true-up is where issue-time escrow and the accepted amount reconcile.

**Migration touch.** Proposal / challenge / starter recreate. Flag: **CLEAN-RECREATE** — 0 challenges, 0 starters, `beef_proposals` table absent, 0 escrow. New tables `ChallengeFundingLeg` and the challenge protocol-event linkage (now generalized under `ProtocolEvent`, Section 3). Migrations described only, unrun.

**Test obligations.** Issue posts real escrow. Availability math no longer reads `_challenge_reserved`. Source split across min-only / wallet-only / mixed / min-absent-reads-zero. Provenance round-trip returns the exact mix. Strict reverse-order release on an **unequal** min/wallet split — proportional refund is the wrong answer; recorded-leg-order is the right one. Each terminal (cancel, expire, reject) reverses exact escrow. Fail-closed expiry on a deliberately mismatched balance. Acceptance capacity drift: party spends BAB after counter, acceptance revalidation fails atomically, posts nothing. Anchor-role-vs-authorship: a recipient-authored counter that raises the Anchor tops up the original issuer's sources, never the recipient's.

**Opus obligations folded in (2026-07-21).**

> Lower-branch ordering: in the lower true-up branch, release and migrate both touch `escrow:challenge`. Release must sequence before migrate, or migrate reads a stale balance. (Obligation 3, OPR-3.)
>
> No write before revalidation: no write — Bet rows, migrate, Derived fund, or top-up — commits before acceptance revalidation passes against the re-read balances. The single-transaction boundary makes this atomic; the plan states it explicitly so no implementer adds an early commit. (Obligation 5, OPR-8.)
>
> Foundation feature gate (sequencing): all intermediate Foundation states remain disabled and unreleased through the L6→L7 gap. The money path stays gated until L7 lands, not merely until L4. Idempotency (L6) guards duplicate delivery; the row lock (L7) guards concurrent distinct operations on one funding scope. Between L6 and L7, event-keyed idempotent posting exists without the serialization mutex — safe only while no money path is live. (Obligation 6, OPR-9.)

---

## Section 6 — Consolidated migration plan (described only)

No migration written this thread. Each described, flagged, left for the implementation-authorization gate.

| Migration | Flag | Basis |
|---|---|---|
| `ProtocolEvent` + `LedgerPostingBatch` + `LedgerEntry` batch/event linkage (P1-L6) | CLEAN-RECREATE / ALTER | ledger empty, 0 rows |
| Wallet / faab float→ledger reshape + scaffolding zero-reset (P1-L2, P1-L3A) | REVIEWED-BACKFILL | 12 + 12 rows, economically empty, row-level only |
| Proposal / challenge / starter recreate (P1-L4) | CLEAN-RECREATE | 0 rows, proposals table absent |

The two REVIEWED-BACKFILL rows are empty containers, not economic history. Buy-ins are zero, reserve and wallet ledger balances are zero, no ledger entries exist.

### 6a. Wallet scaffolding zero-reset protocol (RULED — Ruling 2)

The 12 `wallet` and 12 `faab_wallet` rows are classified as **reviewed non-economic scaffolding**. Treatment:
- authoritative ledger balance begins at zero;
- no opening-balance postings are created;
- no liability is manufactured from legacy float values;
- float fields are reset or normalized to zero;
- any retained float fields become derived compatibility mirrors only;
- future funding occurs exclusively through governed ledger postings.

**Before migration — mandatory review steps:**
1. Capture the existing row IDs and float values in the migration review record.
2. Reconfirm production still has: zero ledger entries; zero buy-ins; zero transactions; zero wager and escrow balances.
3. **STOP** if any value is linked to a real economic event or obligation. That would reopen Ruling 2.

This aligns with the four-bucket $0-wallet model (I-1): wallet starts at $0; real balances arrive through Spec 5's Door-1 buy-in postings and weekly-min release, as proper economic events with real contra postings.

> The 24-value review is a hard migration gate, not a logged formality. The four zero-counts prove the ledger side is empty; they do not by themselves prove the 24 legacy floats are non-economic. The capture-and-review of all 24 values against economic history is what licenses the reset. Stop if any float ties to a real economic event or obligation. (Obligation 7, OPR-10.)

### 6b. Separate deployment dependency — not a Foundation finding

`week_settlements` ALTER (FR-8.7) — adds `status` and `recovery_token` to production's pre-FR-8.7 schema. Forward-only on an empty table (0 rows). It must precede any FR-8.7-dependent deploy, because the branch settlement code already reads those columns. This is **not** one of the five Foundation findings and does **not** alter their locked build order. Register Section 13.7.

---

## Section 7 — Consolidated test plan (obligations, not code)

Per Section 12 §6 and money-path discipline:
- **Concurrency (P1-L7)** — racing issues/accepts produce exactly one commit.
- **Event-idempotency (P1-L6)** — duplicate event returns original, posts once; enforced at the `ProtocolEvent` level, batches still zero-sum.
- **Funded-balance at the cent boundary (P1-L3B)** — float and ledger cents diverge in the fixture.
- **Off-ledger-write regression (P1-L2)** — fails if any money path writes `.balance` directly.
- **Issue-time escrow + full lifecycle reversal + availability-without-`_challenge_reserved` (P1-L4)** — every terminal reverses exact escrow.

**Hard rule, restated.** No money-path finding closes on synthetic-input-only proof. Every fixture uses data where the bug and the fix produce different numbers. Equal-stakes and clean-dividing examples prove nothing about the branch that matters.

---

## Section 8 — Sound components to preserve (do not regress)

From Section 12 §5. Four Foundation blockers remaining does not mean these are unsafe — these are the sound floor the corrections build on:
- Beef settlement economics — escrow-sourced, unequal-tolerant, closes to zero (FR-5.9/5.10 holding).
- Integer-cent zero-sum ledger — migrations must not weaken zero-sum enforcement.
- Funded-balance guard — exempts `world`/`receivable`; preserve.
- P3-S3 settlement serialization — the `week_settlements` lock P1-L7 models on.
- C-1 reserve integrity — no weekly release leaks from `reserve:{team}`; do not reintroduce one.

---

## Section 9 — Gates before any implementation

1. This plan reviewed and approved by Fraser. *(Both design rulings closed 2026-07-21.)*
2. Money-path code Opus-Math-Review-gated — issues-only, table format (Name / Issue / Options / Recommendation & Reasoning), Fraser approves each finding individually before any fix is built.
3. P1-L4 rides the Spec 2 Opus package; Spec 1 Rev 3 bundled as the named dependency.
4. Nothing builds until 1–3 clear.

---

## Section 10 — Next sequence

1. Finalize plan — **DONE (this document).**
2. Documentation-only write and commit.
3. Opus issues-only review.
4. Separately authorize **P1-L2 implementation first.**

---

## Section 11 — Opus Issues-Only Review Dispositions (2026-07-21)

Plan-level Opus Math Review complete. All ten findings dispositioned individually by Fraser. **Plan-level Opus gate CLEARED.** Implementation remains UNAUTHORIZED — P1-L2 requires separate explicit authorization from a fresh thread beginning at this documentation commit.

Opus independently re-verified all twelve Spec 2 posting tables zero-sum by hand and confirmed the three pot totals (1750 / 1950 / 1550). No settled math reopened.

### Disposition record

| Finding | Disposition |
|---|---|
| OPR-1 Event topology contradiction | APPROVED — Option 1. Ruling 1 governs. Spec 2 §7 clearance check passed: no cleared finding (MS-2-1/2/3) relied on entry-level `LedgerEntry` uniqueness. Spec 2 §7 supersession note added. |
| OPR-2 `post()` blast radius | APPROVED — with mandatory "no trailing positional arguments" caller check. |
| OPR-3 Event→batch cardinality | APPROVED — one batch per zero-sum group. Lower-branch fixed as release-before-migrate. |
| OPR-4 Zero-posting counter idempotency | APPROVED as ruled — `ProtocolEvent` allows zero-to-many batches. |
| OPR-5 Wallet-row mutex under reset | APPROVED — Wallet-row grain verified at least as coarse as the funding scope. |
| OPR-6 Refund reconciliation target | APPROVED as ruled — refund target = funded-leg sum; acceptance target = proposal Anchor; fail-closed every path. |
| OPR-7 Strict reverse-order release | APPROVED — unequal-split reversal test mandatory. |
| OPR-8 Acceptance capacity revalidation | APPROVED — with explicit no-write-before-revalidation obligation. |
| OPR-9 L6→L7 concurrency window | APPROVED — all intermediate Foundation states remain disabled and unreleased through the L6→L7 gap. |
| OPR-10 Zero-reset stop-condition sufficiency | APPROVED — the 24-value review is a hard migration gate, not a logged formality. |

### Seven binding obligations (folded into this plan)

1. **Spec 2 §7 supersession** — recorded in Spec 2 v2 §7 (not this plan). Ruling 1 governs; entry-level `event_id` is traceability only.
2. **`post()` trailing-positional check** — folded into Section 3 build-time flag.
3. **Lower-branch release-before-migrate ordering** — folded into Section 5 (P1-L4).
4. **Wallet mutex grain requirement** — folded into Section 4 (P1-L7).
5. **No write before acceptance revalidation** — folded into Section 5 (P1-L4).
6. **Foundation feature gate through L6→L7** — folded into Section 5 sequencing.
7. **Mandatory 24-value review before reset** — folded into Section 6a.

---

## STOP

This document is the finalized Foundation Correction Plan. No code, schema, migration, or test is written or authorized here. Implementation is a separately authorized step, beginning with P1-L2, after the Opus issues-only review.
