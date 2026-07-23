# Master Plan — Current-State Pointer (2026-07-20)

**Purpose:** A short authoritative pointer to current state, written because the master plan is scattered across a base document (`MasterPlan_v8_LaunchPath.md`) plus five dated update files, and several of its claims are now stale or contradicted by later rulings. This note does NOT reconcile the plan — it points at the current source of truth and flags what's stale, so the next thread doesn't read the wrong model. **A full master-plan reconciliation into one `MasterPlan_v9` is a separate pending task (its own thread).**

**Authoritative source for findings/rulings:** `Findings_Register_v12_2.md`. Where this note or the master plan disagrees with v12.2, v12.2 wins.

---

## Current state as of 2026-07-20

**Economy model — CHANGED. The master plan's funded-wallet model is STALE.**
- The economy is a **four-bucket, $0-wallet** model, NOT the old two-bucket funded-wallet ("$220 buy-in → $140 wallet → $80 reserve").
- Buckets: (1) `wallet:{team}` seeds at **$0** (winnings + top-offs only); (2) `min:{team}:{week}` weekly wagerable; (3) `min_reserve:{team}` weekly runway (NEW account, distinct from `reserve:{team}`); (4) `reserve:{team}` championship reserve.
- Reserve math is the R1 integer-cent formula off a weekly-min rate × Yahoo regular-season weeks — NOT a hardcoded ×14.
- Source: register v12.2, Section 6, findings I-1/I-2 and ruling R1. Any master-plan text describing a funded wallet or a $140 wallet seed is superseded.

**Spec status — CHANGED.**
- **Spec 1 (Proposal Lifecycle):** frozen, architecture-reviewed. Current file: `SPEC_1_Proposal_Lifecycle_v3.md`.
- **Spec 2 (Challenge Escrow & Atomic Acceptance):** **OPUS-CLEARED** this line (MS-2-1 rejected, MS-2-2/MS-2-3 approved and integrated). Current file: `SPEC_2_Challenge_Escrow_v2.md`.
- Build order unchanged: **1 → 2 → 3 → 5 → 4.** Specs 1 and 2 build together on an unreleased branch; neither independently enabled.

**Spec 5 scope — EXPANDED.**
- Beyond its original economy-config/account-identity charter, Spec 5 now owns: the four-bucket $0-wallet topology (I-1/I-2, R1); the skunk liability submodule (I-3, R2/R3); and the **I-5 championship payout placement-authority correction** (shipped-code fix — Championship Pot must pay by finalized Yahoo postseason bracket placement, not regular-season standings; needs a new Yahoo bracket reader, fail-closed pending behavior, and a `standings_order`→`placement_order` migration).
- I-5 is distinct: it corrects **shipped, tested code**, so it carries an implementation-clearance gate (diff review + default-path regression), not just design clearance.
- Season-close money model: **two pots, two axes** — Championship Pot → postseason bracket placement; Skunk Pot → regular-season Points For. Skunk unchanged.

**Enablement gate (tightened).**
- Spec 2 may be built before Spec 5 on the unreleased branch, but the four-bucket economy cannot be **enabled** until Spec 5 seeds `min_reserve`, releases the current-week `min`, and establishes the buy-in postings. Until then wallet reads $0 and `min` is absent.

**Build-thread first action (unchanged, gated on explicit word).**
- Read-only production count of `BeefChallenge` / `BeefStarter` / `Bet` rows before any migration is designed. Zero rows → clean schema recreate; any rows → stop for a reviewed backfill plan. No schema/code without explicit authorization.

---

## What this note supersedes (for reading purposes)

For current economy model, spec status, and Spec 5 scope, read THIS note + `Findings_Register_v12_2.md` — not the master-plan base or the five dated updates, which are stale on the economy model. The dated master-plan updates (`_Update_2026-07-17` through `_2026-07-20`) remain as history but should not be treated as current on economy topology.

## Pending (not done here)

- **Full master-plan reconciliation** into one `MasterPlan_v9.md` under the naming convention (version in filename, no dates), folding the v8 base + five updates + this note + v12.2 into a single current document, then retiring the update pile. Its own thread.
- Architecture diagram and roadmap may also be stale on the four-bucket economy — check during the reconciliation.
