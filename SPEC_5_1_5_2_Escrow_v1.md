# Handoff — Money-Path Queue: Escrow, Acceptance-Reprice & Pool Entry Fee

**For:** the next thread (continuing from the settlement-engine verification work).
**Priority:** Top of transition package. Three money-path items, all recon-first and Opus-gated. Items 1–2 block the Locked-vs-Dynamic cascade; item 3 is independent but shares the same review.

---

## What was decided (in the UI/UX design thread, 2026-07-19)

A new **proposal-freeze model** for Locked Bets was ADOPTED (Sections 1–4 of `LOCKED_VS_DYNAMIC_WAGER_MODEL_RULING.md`, now in project docs). Read that document first — it is the model of record. Core principle:

> A Locked proposal freezes when it is created. A counter creates a new frozen proposal. Acceptance selects one proposal and makes its frozen lineup, odds, stakes, and settlement terms mutually binding. Later Yahoo lineup changes do not alter the accepted Locked Bet.

This **amends** the prior rule (SIMULATION_ENGINE Rev 7, §Locked Challenge, line 39) that froze Locked Bets only at acceptance. Now each proposal freezes at creation; acceptance selects among frozen proposals.

Of the three gates in that ruling: **5.3 is cleared** (UI copy fix to Rev 7 — done). **5.1 and 5.2 remain open** and are this thread's job.

---

## The money-path items

### Gate 5.1 — Escrow treatment across offer / counter / accept (NOT YET RULED — money-path)

Four questions, all requiring resolution + Opus Math Review before any escrow code moves:

1. Does Refresh & Relock (the Locked counter) change the issuer's Anchor Stake, or only lineup and odds?
2. If a counter lowers the Anchor Stake, does the issuer's escrow stay put until acceptance?
3. If a counter raises it, is the higher amount only validated, or also temporarily reserved?
4. When the original issuer accepts the counter, whose escrow adjusts, and in what order?

**Current behavior (to verify against live code, not assume):** issuer's Anchor Stake escrows at initial-offer issue; a counter currently moves no money; a true-up occurs at acceptance. That skeleton may survive — but the four questions must be answered explicitly.

### Gate 5.2 — No acceptance-time repricing for Locked Bets (RULED by the model — implementation gated)

The rule is already settled by proposal-freeze semantics: a Locked Bet does **not** reprice at acceptance — acceptance selects the frozen proposal on the table. If acceptance recalculated odds, it wouldn't be selecting the frozen proposal. So this is **not a new decision** — it follows from the adopted model.

**But** current engine behavior conflicts: `beef_engine.py respond_to_challenge` (~line 919) recomputes odds at acceptance today (via `_compute_odds_from_inputs`). Opus must verify the downstream math and implementation consequences of removing that acceptance-time reprice for the Locked path — Dynamic behavior must be unaffected.

### Item 3 — Pool entry fee: per-pool → league-wide commissioner flat fee (NEW, 2026-07-19 — money-path)

**Decision (from the UI/UX thread):** pool entry fee becomes a single **league-level commissioner setting**, one flat value applied uniformly to every pool, **bounded $1–$5** (100–500 cents). This replaces the current apparent per-pool `weekly_entry_cents` model. Fraser considered a hardcoded flat $1 but chose a commish-set range instead.

**Why it's money-path, not just a UI/config change:** entry fee feeds the pot; the pot feeds payout; payout is the n-way split already flagged as needing work (the old `total_cents // 3` → dynamic n-way split). Changing how the fee is set changes how the pot forms, so it touches payout math and must be Opus-verified.

**Questions to resolve (recon-first, against live code):**
1. Is `weekly_entry_cents` today actually per-pool, or is there already a league-level setting? (Verify — don't assume from the doc label.)
2. Where is entry fee read — pool creation, entry validation, pot accrual, payout split? Each site must move to the league-level value.
3. Does the fee lock at season kickoff (like the weekly-min sweep setting) or stay adjustable mid-season? Sub-decision for Fraser.
4. Enforce the $1–$5 bound where? (Config write validation, mirroring the economy-stop slider pattern.)

**Independent of the cascade:** unlike 5.1/5.2, this does not block the Locked-vs-Dynamic work. It rides along in the same MODULE_SPEC only because it's the same money path and the same Opus review — batching, not dependency.

---

## Next steps — in order (DO NOT skip the recon)

**Step 1 — Recon first (existence-check discipline).** Before writing ANY ruling, grep the live working tree — not the docs, not this handoff's "current behavior" claims. Read the actual code:
- `beefs/beef_engine.py` — escrow-at-issue on offer creation; the counter/respond path; `respond_to_challenge` (~line 919) reprice call.
- `ledger/ledger.py` — the postings used for escrow, and the true-up path.
- Pool config + entry path (`pool_engine.py` and wherever `weekly_entry_cents` is defined/read) — confirm whether the fee is per-pool or league-level today, and every site that reads it (creation, entry validation, pot accrual, payout split).
- Confirm what actually escrows/charges, when, and whether the counter path touches money today.
- The rule: read the live code, don't trust the label or any spec's own claims — including this handoff's.

**Step 2 — Answer the open questions** against what recon found, in the four-part findings format (Name / Issue / Options / Recommendation & Reasoning): 5.1's four escrow questions, and item 3's four pool-fee questions. Each proposed ledger posting must sum to zero by direct arithmetic — self-check before Opus.

**Step 3 — Write the MODULE_SPEC** covering 5.1 (escrow), 5.2 (remove Locked acceptance-reprice), and item 3 (league-wide pool entry fee, $1–$5). One spec — same money path, same review. Item 3 is separable if it complicates the spec, but batching is the default.

**Step 4 — Opus Math Review** — hard gate. Issues only, table format, Fraser approves each finding individually before any fix is built.

**Step 5 — Cascade.** After Opus clears 5.1 and 5.2, the Section 6 Locked-vs-Dynamic cascade begins (Game Engine, Simulation Engine, Settlement, Response Card Spec, UI/UX). Item 3's cascade is smaller and independent — pool config schema (one league-scoped field, 100–500 bound), commish settings UI (a slider like the economy stops), and the pool entry cards (which just read the value).

---

## Guardrails carried from the design thread

- **Propose before building.** No code, commits, or migrations without Fraser's explicit word.
- **Money-path = Opus gate.** All three items cross it (escrow, reprice, pool fee). No shortcut.
- **Settlement authority (from the adopted model):** Locked settlement must read the accepted FantasyBeefs lineup snapshot — not either GM's later Yahoo lineup. Yahoo = source of actual stats; FantasyBeefs = source of which player IDs are covered. This is one of the largest downstream changes and settlement code will need it — but it's Section 6 cascade work, gated behind 5.1/5.2, not part of this spec.
- **Reference doc:** `LOCKED_VS_DYNAMIC_WAGER_MODEL_RULING.md` (adopted 2026-07-19) is authoritative for the model. This handoff is just the pointer + the escrow work framing.

---

## One-line summary for the transition package

Locked-bet proposal-freeze model adopted; gate 5.3 cleared. Three money-path items queued for one MODULE_SPEC, recon-first then Opus-gated: 5.1 (escrow across offer/counter/accept) and 5.2 (remove Locked acceptance-reprice) — both block the Locked-vs-Dynamic cascade; plus item 3 (pool entry fee → league-wide commissioner flat fee, $1–$5) — independent, batched for the same review.
