# Mechanics Validation Program — Staged Gate 1

**Date:** 2026-07-29
**Branch:** `remediation/foundation-phase-1` · **HEAD:** `ff70f56572411a134a6e2e84ae98a086bb01b8dc`
**Supersedes:** `GATE_1_OPUS_MECHANICS_REVIEW_PACKAGE_DRAFT.md` (deleted — it framed Gate 1 as a
single monolithic review, which duplicated the queued Spec 2 pass).
**Authorizes nothing.** No build, no commit, no deploy, no UI rebuild, no new mechanics.

---

## 1. What Gate 1 is

Gate 1 is a **program**, not an event. Each subsystem is reviewed when its governing
specification becomes authoritative. No subsystem is certified early, and no Opus pass repeats
material another pass already covered.

| Stage | Trigger | Review | Status |
|---|---|---|---|
| **G1-a** | Spec 2 authoritative | Existing Spec 2 Opus money-path review | Queued. Prerequisites ahead of it: FR-8.7 closure, FR-AC-ISO-1 |
| **G1-b** | Specs 3A/3B authoritative | Pricing and Dynamic review | Blocked — specs not started |
| **G1-c** | Spec 5 authoritative | Economy, Weekly Min, account identity review | Blocked — spec not started |
| **G1-d** | Spec 4 authoritative | Pool catalog and settlement review, as its scope requires | Blocked — spec not started |
| **G1-e** | G1-a…d individually cleared | One integrated mechanics/accounting audit across the complete deterministic model | Blocked on all of the above |

The existing backend build order is unchanged:
Security → FR-8.7 → deployment → FR-AC-ISO-1 → Spec 2 → 3A → 3B → 5 → 4.

**No new Opus gate is created by this document.** G1-a is the review Spec 2 has always been
waiting on.

---

## 2. Skunk supersession — RULED 2026-07-29

**Governing Skunk mechanic:**

- Skunk fine is **fixed at $10**. Not commissioner configurable.
- Trigger is the governed widest-margin Yahoo matchup loser for the week.
- Assessment is **off-Wallet**, as a settlement obligation.
- Wallet and Available to bet are **unchanged** by the assessment.
- **No Credits are collected or transferred into an in-season Skunk pot.**
- **Do not model a funded `skunk:{league}:{season}` holding account** merely to represent the
  obligation.
- At season settlement, governed Skunk obligations are owed to the GM with the highest
  regular-season total fantasy points.

**Superseded on these points:** Findings Register v12.2 §I-3, insofar as it specifies a
commissioner-configured fee, a funded `skunk:{league}:{season}` account, and
`maximum pot = regular-season weeks × configured fee`. That text must not govern new Spec 5 work.

**Preserved from prior Skunk work, subject to the newer model:** deterministic trigger
detection, idempotency guarantees, and the regular-season points-champion recipient.

**Record discipline:** I-3 stays in the register with a superseded marker on those points. Not
rewritten, not deleted.

**Consequence for Spec 5:** the Skunk submodule models an obligation and a receivable, not a
pot. `receivable:skunk:{team}:{season}` remains conceptually compatible; the pot account does not.

---

## 3. Fold-in to the existing Spec 2 Opus package

Targeted regression only. **No separate gate. Do not reopen unrelated conclusions.**

RR-1 (2026-07-26) reversed Ruling 7 of `FINDING_5_6B`: challenge escrow now begins **at issue**,
not at acceptance. Two prior Opus clearances predate that reversal.

Re-test only conclusions whose reasoning depended on either:

1. **no funding before acceptance**, or
2. **no decline / withdraw / expiry refund path**.

| Item | Cleared under | Regression question |
|---|---|---|
| `FINDING_5_9` Rev 4 — settlement escrow gap | acceptance-time funding | Does the escrow-close posting shape still hold when the issuer's Anchor was funded at issue? |
| `FINDING_5_10` Rev 3 — matched-bet payout | acceptance-time funding | Payout is escrow-sourced. Does escrow-at-issue change the sourcing basis, or only the timing of when the source is populated? |
| Ruling 7 dependents generally | "nothing escrowed until acceptance, therefore no expiry/cancellation drain" | Every conclusion resting on the absence of a drain path now needs one. |

Also carried into the same package, as **existing scope questions rather than new rulings**:

- **Active-challenge cap.** Canonical Rules state a limit of 10 active challenges. Spec 2 already
  owns capacity validation. Confirm the cap is expressed there, and what "active" counts.
- **Challenge expiry window.** Canonical Rules state 60 minutes or games-lock, whichever comes
  first. Confirm the constant's home and whether the clock restarts on counter.
- **Counter-sender hold.** Canonical Rules state no hold is taken from a counter-sender, and the
  original issuer's stake remains held. This is already tracked as an open SI-09 delta
  (pending-bucket gate, acceptance true-up, decline/expiry reversal). Classify it inside the
  existing diff. **Escrow-at-issue is baseline and must not be reopened.**

---

## 4. NOT YET REVIEWABLE — GOVERNING SPEC PENDING

Recorded, not certified. No inference from prototype copy, legacy code, or draft findings.

### Spec 3A / 3B — pending
- Stake and pricing math
- Dynamic wager behavior after acceptance
- Final Lock semantics
- Asymmetric Anchor/Derived stake handling
- Adjustment states

### Spec 5 — pending
- Season-opening advance postings
- Weekly Min Reserve → Weekly Min Left release lifecycle
- Fantasy Week Close
- Out of circulation
- Championship contribution
- Final Awards
- Skunk submodule implementation (mechanic now ruled — see §2 — implementation still pending)
- Account identity and canonical `championship:{league_id}` scoping

### Spec 4 — pending
- Pool entry, eligibility, own-pick restriction
- Pool lock, pot calculation, tie handling
- Winner distribution, no-winner outcome
- Rollover and repeated rollover
- `DECIDED → SETTLING → SETTLED` transitions and their postings
- Pool ledger account naming and posting shape

### Unresolved product anchor — standing
- **Top-Off Cap numeric anchor.** Unresolved by standing ruling. Not a new question. Cap
  *mechanism* is reviewable under VAL-10 Rev 23; the *bound* is not. Do not invent one.

---

## 5. UI dependency register

UI/UX work continues. Architecture, navigation, information hierarchy, minimalism, and
already-ruled surfaces are not blocked by absent backend specs.

**Standing rule:** where the UI depends on a not-yet-authoritative mechanic, record the
dependency. Do not invent the backend contract, and do not treat the prototype's depiction as
backend-authoritative.

| UI surface | Depends on | Dependency status |
|---|---|---|
| Pool tiles — WAITING / LIVE / OUT | Spec 4 entry and lock | **PENDING** |
| Pool `SETTLING` state, pending return | Spec 4 DECIDED→SETTLED postings | **PENDING** |
| Pool rollover copy | Spec 4 rollover | **PENDING** |
| In Play figure including Pool entries | Spec 4 account naming | **PENDING** — mechanic ruled (F3), posting home undefined |
| `DYNAMIC` badge, mode selector | Spec 3B | **PENDING** |
| Stake/pot/win-net/lose-net economics | Spec 3A | **PENDING** |
| Weekly Min Left, Out of circulation, Current Settle rows | Spec 5 | **PENDING** |
| Top-Off Remaining | VAL-10 + unresolved cap anchor | **PARTIAL** |
| Skunk row | §2 ruling | **RULED** — mechanic settled, implementation pending |
| Versus create / accept / counter / pass | Spec 1 + Spec 2 | **AUTHORITATIVE** (Spec 2 pending its review) |
| Issuer hold, Available to bet drop on send | Spec 2 + RR-1 | **AUTHORITATIVE** |
| Navigation, tab structure, Rules sheets | Product POR | **AUTHORITATIVE** |

The prototype's own lifecycle cards already carry `SUPPORTED AFTER SPEC 5` labels. That
labelling convention should extend to the Spec 3 and Spec 4 dependent surfaces above.

---

## 6. Ambiguity register — reclassified

My prior nine were over-scoped. Most were not decisions required now.

| Ref | Was | Now |
|---|---|---|
| A1 ten-challenge cap | product ruling request | **Spec 2 package scope question** (§3) |
| A2 sixty-minute window | product ruling request | **Spec 2 package scope question** (§3) |
| A3 counter-sender hold | product ruling request | **Existing SI-09 delta** (§3) |
| A4 Skunk contradiction | product ruling request | **RULED** (§2) |
| A5 pool entry ledger account | product ruling request | **NOT YET REVIEWABLE** (§4) |
| A6 DECIDED→SETTLED postings | product ruling request | **NOT YET REVIEWABLE** (§4) |
| A7 Top-Off Cap anchor | product ruling request | **Standing open item** (§4) |
| A8 Gate 1 vs Spec 2 review | product ruling request | **CLOSED** — Gate 1 is staged; G1-a *is* the Spec 2 review |
| A9 Gate 1 gate conditions | product ruling request | **CLOSED** — G1-a inherits Spec 2's prerequisites unchanged |

**Zero open product rulings requested by this document.**

---

## 7. Open UI findings, deferred

| Ref | Finding | Status |
|---|---|---|
| **UI-VS-1** | One Versus interaction = one persistent workspace | RECORDED · NOT IMPLEMENTED · Rev3.1 |
| **UI-COMMISH-TOPOFF-1** | Commissioner Top-Off approval surface missing | RECORDED · NOT IMPLEMENTED · Rev3.1 |
| **F7** | LOCKED/DYNAMIC mode propagation to outgoing offer | OPEN · implemented inside UI-VS-1 |
| **F3 residual** | Ledger In Play block labelled `Versus wagers`; Pool entries need their own subsection or the label is false | OPEN · Rev3.1 |

---

## 8. Artifact state

- `FantasyStakes_UIUX_Prototype_Rev3_0.html` — `f8b3edac…de5c6cea`, 130,349 bytes. **Immutable.**
  Committed at `ff70f56`.
- `FantasyStakes_UIUX_Prototype_Rev3_1_partial.html` — `087ba445…f236f5f`, 126,691 bytes.
  **Intermediate correction artifact.** Not Rev3.1. Not committed.

Closed in the correction pass: F1, F2, F5, F6, F8, duplicate Pool identities, Top-Off stale
Wallet pairs, rollover week residue.
Open: F3 component amounts, F4 future-week settled results, F7.

**Prototype-data reconciliation stays deprioritized.** Remaining F3/F4 items are logged as
illustrative-coherence work, to be resolved during the Rev3.1 rebuild rather than as a
standalone pass.
