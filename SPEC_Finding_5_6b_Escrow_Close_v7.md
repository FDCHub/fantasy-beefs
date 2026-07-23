# Finding 5.6b — Two-Sided Escrow-Close — MODULE_SPEC, Rev 7 — DESIGN COMPLETE

**Status:** Rev 7. Seven rulings made, seven Opus review passes complete. **The design phase is closed.** Opus's seventh pass confirmed no further rounding surface, gap, or ruling is needed — the only two changes this revision makes are to the Section 4 live-code verification prompt itself (one new question, one re-weighted priority), not to any design decision. Next step: run Section 4 against the live codebase.

**What changed from Rev 6:** Opus's seventh pass (findings 5.6b-31 through 5.6b-33) confirmed the whole-cents induction is trivially and correctly satisfied by Ruling 7, and confirmed the design itself needs no further revision. It found two things that belong in the verification prompt rather than the design: Ruling 7 defers all funding checks to acceptance-time, which means "the initiator can no longer fund their own offer by the time someone accepts it" is a real case the verification questions didn't yet ask about — added as question 11. And the pre-build summary had flattened question 1 into an ordinary precondition, losing Section 4's own point that a failure there is a live production bug independent of 5.6b entirely — re-flagged with that urgency below.

---

## PRE-BUILD SUMMARY — read this before writing any code

*(Added per Opus 5.6b-30. The chronological Opus Review Log in Section 8 remains the full audit trail; this is the extract a builder actually needs.)*

**Read this one first — it's not like the others (Opus 5.6b-32):**
- **(q1) The acceptor's stake must be exclusively derived from the shared odds line by one function, with no code path that lets it be entered independently.** If this comes back wrong, it is not "revise the spec" — it means **live versus bets are already mismatched in production today, independent of whether 5.6b is ever built.** Treat a failure here as an immediate, standalone bug to assess, not just a precondition for this spec.

**Four blocking conditions — Section 4 must confirm all four before this spec is buildable as designed:**
1. (q6) `escrow.py` Rev 2.0 recomputes each drift from the acceptance-locked original stakes, not from a prior drift's intermediate result.
2. (q7, first half) Rev 2.0 never re-derives the acceptor's stake from raw odds on drift — it only rescales the frozen, already-rounded acceptance stakes.
3. (q7, second half) Rev 2.0's rescale computes from the frozen original stake, not from a prior drift's already-rescaled result.
4. (q8) Rev 2.0's against-the-cap recalculation computes fresh from the frozen originals plus the current cap, not from a prior drift's already-capped-and-recalculated result.

*If any of the four comes back the wrong way, 5.6b's drift-handling is blocked until `escrow.py` is modified — this is a prerequisite of 5.6b, not a coexisting, separately-tracked defect.*

**Ordinary preconditions — Section 4 must also confirm these:**
- (q5) The escrow schema holds two rows per bet, one per side, not one combined row.
- (q9) The initiator's entered stake is validated as whole cents at the input boundary — this is the base case the entire whole-cents induction (Section 5) rests on.

**One open lifecycle gap, now resolved by ruling, still needs a code-side check:**
- Ruling 7: an offer does not escrow the initiator's stake until the acceptor actually accepts. This means an offered-but-never-accepted bet needs no expiry/cancellation drain — there's nothing in escrow to return. Section 4 should confirm the live acceptance flow actually works this way (escrow posts only on acceptance, not on offer) rather than assuming it. (q10)

**NEW (Opus 5.6b-31) — the consequence of Ruling 7 that needs its own check:** deferring all funding to acceptance-time means an initiator can offer a bet, then spend the money elsewhere before anyone accepts. If someone accepts before the initiator can actually fund it, the acceptance-time escrow posting fails on the initiator's side. Section 4 must confirm: does acceptance post both sides' escrow atomically (both post or neither does), and what does the live code actually do today if the initiator can't fund their side? (q11) This is not a UI concern — it's the acceptance-time analogue of the atomicity the spec already requires at settle.

**If all of the above come back clean, Rev 7 is buildable exactly as designed. If any come back wrong, that specific item blocks until fixed — read the relevant ruling's row in Section 5 for what "fixed" means in each case.**

---

## 1. The problem, in plain English

A versus bet has two sides. Each side stakes money. One side wins. The winner gets paid from the loser's stake. That much everyone agrees on.

No spec ever wrote down the actual math. `settle_week()` computes each side's `amount × odds` on its own. Nothing ties those two numbers together. Nothing proves the loser's escrow actually covers the winner's payout. Nothing says what happens on a push. Nothing said what happens to an offer that's never accepted.

This gap sat under every versus bet since day one. It only surfaced because Finding 2.2's settle-body read flagged it.

---

## 2. What the ledger law already promises (from L1, certified)

The seven-account chart already states the general rule:

- **Wager placed:** debit GM wallet, credit escrow.
- **Wager settle:** debit escrow, credit winner wallet — winner takes the full pot, no vig (Fraser's ruling, Finding 2.8, Door 5).

That's correct as far as it goes. It assumes the pot is already a known, closed number by the time settle runs. It does not say how two independent stakes, placed by two different GMs under two different odds, become one closed pot in the first place. That's the actual gap. 5.6b lives one layer below L1, not in conflict with it.

---

## 3. The real open question

Fantasy Beefs has no house. No one sets a line and takes the other side. Two GMs bet each other directly. So the stakes on both sides have to be **matched to the odds at acceptance**, or the pot won't close without either a house edge (ruled out) or a shortfall (unacceptable).

Example: GM A offers a bet at -150 (must risk $3 to win $2). GM B accepts at the other side, +150 (risks $2 to win $3). For this to close clean:

- A escrows $30, B escrows $20.
- Pot = $50.
- A wins → A takes the full $50 (gets back $30, wins B's $20 — profit $20, matches -150 odds).
- B wins → B takes the full $50 (gets back $20, wins A's $30 — profit $30, matches +150 odds).

This example closes clean only because -150/+150 happens to divide evenly. Most odds don't. This spec states three distinct, deterministic rounding rules across the bet's lifecycle: acceptance-time derivation (Rulings 1 and 4), drift rescale (Ruling 5), and ceiling-cap recalculation (Ruling 6) — three separate rounding events, each round up, each with its own stated basis. A proof by induction (Section 5) confirms these three, plus Settle and Push, cover every operation that touches a stake or escrow value — no fourth rounding surface exists.

This works, but only if the acceptor's stake is **derived from the initiator's stake and the odds**, not chosen independently, and only if nothing is escrowed before both sides have actually committed — see Ruling 7 for that.

**Nobody has confirmed whether the current acceptance flow enforces the stake-matching link.** That's the first thing to check, before writing a single line of settle-side code.

---

## 4. Verification needed before this spec can be finalized

Run these against the live codebase before any code is written. Same discipline as every prior finding — read the function body, don't trust the label.

**PyCharm terminal — Claude Code CLI:**
```
Read betting/bet_engine.py's _place_bet() and the accept-side function it calls (grep for "accept" in betting/bet_engine.py and beefs/beef_engine.py if versus bets share code with beefs). Report back, verbatim:
1. When a GM accepts a versus bet, is the acceptor's stake calculated from the initiator's stake and odds, or entered independently?
2. Is there a stored "odds" field per bet, per side, or one shared field?
3. Does escrow.py's Flexible Stake and Return logic ever touch the ORIGINAL stake-matching math, or does it only handle post-acceptance odds drift?
4. What does settle_week() currently do with the two stake amounts and odds when a bet settles — show the actual arithmetic, not a paraphrase.
5. Does the escrow schema actually hold two rows per bet, one per side, or one combined row for the whole pot?
6. Does escrow.py Rev 2.0's actual code recalculate each drift event from the acceptance-locked original stakes and current odds, or does it compound on the prior drift's intermediate result? BLOCKING if it compounds.
7. Does escrow.py Rev 2.0's drift recalculation ever re-derive the acceptor's stake from the current odds and re-round it, or does it only rescale the two already-rounded, acceptance-locked whole-cent stakes together? FURTHER: when it rescales, does it always use the frozen acceptance-locked stake as input, or the prior drift's already-rescaled result? BOTH halves BLOCKING if answered the wrong way.
8. When Rev 2.0's drift recalculation caps a stake at its Max Stake Ceiling and recalculates the other side against that cap, does that recalculation compute fresh from the frozen original stakes and the current cap each time, or does it build on a prior drift's already-capped-and-recalculated result? BLOCKING if it compounds.
9. NEW: is the initiator's entered stake validated as integer cents at the point of entry (bet offer creation) — the versus-side analogue of the pool-cents `weekly_entry_cents` input boundary? This is the base case the entire whole-cents rounding induction (Section 5) depends on.
10. Does making a versus-bet offer post any escrow entry at all (debit initiator's wallet, credit escrow), or does escrow only get posted at the moment the acceptor accepts? Ruling 7 assumes the latter — confirm which the live code actually does.
11. NEW (Opus 5.6b-31): Ruling 7 defers all funding checks to acceptance-time — meaning an initiator can offer a bet, then spend the money elsewhere before anyone accepts. Does the live acceptance flow post both sides' escrow as one atomic event (both post or neither does), and what does it actually do today if the initiator's side fails the funded-balance guard at the moment of acceptance? This is not a UI question — it's whether a half-posted, money-inventing or money-losing state is reachable today when an accepted offer turns out to be unfundable.
```

The answer to #1 decides most of Section 5 — and per the pre-build summary, if it comes back showing the acceptor's stake is entered independently rather than derived, treat that as a live production bug to assess immediately, not merely a precondition for this spec. The answers to #6, #7, and #8 together are the four blocking conditions in the pre-build summary above. The answer to #9 confirms the rounding induction's base case. The answer to #10 confirms whether Ruling 7's "nothing to drain on expiry" reasoning actually holds. The answer to #11 confirms whether acceptance is atomic and fails cleanly when the initiator can't fund their own offer — a real money-path case Ruling 7 makes reachable.

---

## 5. Design options for the closing rule

**Schema note, applies to the Settle-side, Push, Ceiling-recalculation, and Multi-drift-recalculation rows below:** all four assume the escrow schema holds two rows per bet, one per side. Unconfirmed — see Section 4, question 5.

**Definition, applies throughout this section:** "original committed stakes" or "acceptance-locked stakes" mean the whole-cent stake pair fixed at acceptance, after Ruling 1's round-up has been applied exactly once. Rescaling it (Ruling 5) and capping one side against its ceiling (Ruling 6) are further, distinct rounding events — neither is a repeat of the acceptance-time derivation or of each other.

| Name | Issue Summary | Options | Recommendation & Reasoning |
|---|---|---|---|
| **Stake-matching at acceptance** | Whether the acceptor's stake is derived from odds or chosen freely. | (a) Derive acceptor's stake from initiator's stake + odds, lock both at acceptance. (b) Let both sides pick stakes independently; settle-time math converts via ratio. | (a). Deriving the stake relocates any rounding to acceptance time, where it happens once and deterministically. |
| **Rounding rule for the derived stake (Ruling 1)** | Most odds don't divide the derived stake into a whole cent. No championship account to sweep a leftover cent into. | (a) Round up, always. (b) Round down, always. (c) Fixed rule naming one side. | **RULED (Fraser): round up, always.** Round-down risks shortchanging a winner; round-up never does. Acceptance-time derivation only — see Ruling 4 for frequency, Ruling 5 for rescale rounding, Ruling 6 for ceiling-cap rounding. |
| **Round-up frequency at acceptance (Ruling 4)** | Composed with Ruling 3, nothing stated whether the acceptance round-up fires once or re-fires per drift. | (a) Round up once, at acceptance only; drifts rescale the frozen pair. (b) Re-round every drift from raw odds. | **RULED (Fraser): option (a).** The acceptance-time derivation never repeats. *Depends on Section 4 question 7 — BLOCKING if Rev 2.0 re-derives from raw odds on drift.* |
| **Rescale-rounding rule (Ruling 5)** | Rescaling a frozen stake by a drift ratio doesn't generally land on a whole cent — a distinct, recurring rounding event. | (a) Round up, always computed from the frozen stake, never from a prior rescaled result. (b) Round down. (c) Compute from the prior result. | **RULED (Fraser): option (a).** Same direction as Ruling 1. Confirmed determinate and non-accumulating by direct walk (910 × 1.15 → 1047; a different ratio applied to the same frozen 910 → 838, independent of the first). *Depends on Section 4 question 7's second half — BLOCKING if Rev 2.0 rescales from a prior result.* |
| **Ceiling-cap recalculation rounding (Ruling 6)** | The against-the-cap recalculation computes from the cap, not the frozen original — Ruling 5's discipline can't reach it, and it rounds with no stated rule. Reachable whenever a ceiling is hit. | (a) Round up, always computed fresh from the frozen originals and the current cap. (b) Round down. (c) Compute from a prior capped result. | **RULED (Fraser): option (a).** Same direction, same discipline extended to the one remaining computation that needed it. Confirmed determinate and non-accumulating even under a two-sided-capping stress walk (both GMs capped at different drifts produce fresh, path-independent results). *Depends on Section 4 question 8 — BLOCKING if Rev 2.0 compounds on a prior capped result.* |
| **Pre-acceptance escrow timing (NEW — Ruling 7)** | The spec never stated whether making a bet offer escrows the initiator's stake before anyone accepts. If it does, an expired or cancelled unaccepted offer needs a drain-back-to-wallet posting the spec never defined — money could sit stranded in escrow with no return path. | (a) Offer escrows the initiator's stake immediately; expiry/cancellation drains it back. (b) Nothing is escrowed until the acceptor actually accepts — an offer is a proposal, not yet a funded commitment. | **RULED (Fraser): option (b).** Nothing else in this system escrows on a mere proposal — commitment and funding happen together, at acceptance, consistent with how the rest of the ledger law treats every other door. This also means there is no expiry/cancellation drain to design: an unaccepted offer never touched escrow, so there's nothing to return. *Depends on Section 4 question 10 — confirm the live acceptance flow actually escrows only at acceptance, not at offer creation. If it turns out offers do escrow today, that's a real gap needing its own drain posting, on the same footing as the other blocking conditions.* |
| **Settle-side posting** | What `settle_week()` should actually post. | (a) Single paired posting: debit both escrow rows, credit winner wallet with the summed pot. (b) Two postings. | (a). **Confirmed rounding-free by construction** — sums two already-whole-cent balances. Needs its own per-bet `settled` guard, independent of `settle_week()`'s week-level claim lock. *(Assumes the two-row escrow schema.)* |
| **Push (tie) handling** | Never specified anywhere in any prior document. | (a) Both stakes return to their own origin wallets. (b) Push forfeits to championship. | (a). "Drain each escrow to its own origin wallet at current balance." **Confirmed rounding-free by construction** — moves an existing whole-cent balance, never computes a new one. *(Assumes the two-row escrow schema.)* |
| **Odds representation** | Shared field vs. per-side fields. | (a) One shared line. (b) Two independent per-side fields. | (a). Makes stake-matching possible; enforcement still depends on Section 4 question 1. |
| **Max Stake Ceiling vs. stake ratio (Ruling 2)** | Ratio-preservation vs. the ceiling promise, in direct conflict under asymmetric drift. | (a) Ratio wins. (b) Ceiling wins, other side recalculates against the cap. | **RULED (Fraser): ceiling wins.** Rounding and basis for the recalculation governed by Ruling 6. Resulting smaller pot needs no remainder handling — closes clean on its own. *(Assumes the two-row escrow schema.)* |
| **Multi-drift baseline (Ruling 3)** | Caps could compound or stick across repeated drifts without a stated baseline. | (a) Recompute fresh each drift from the acceptance-locked originals. (b) Sticky caps. | **RULED (Fraser): option (a).** Matches "reductions refunded." *Depends on Section 4 question 6 — BLOCKING if Rev 2.0 compounds.* |
| **Multi-party extension (FR-6.2)** | Matchup-vs-matchup needs a 1v2/2v2 escrow-close. | (a) Design generally now. (b) Solve 1v1 first, generalize later. | (b), per the prior session's ruling. The single-posting settle design generalizes cleanly later. |

---

## 6. What "done" looks like

**Contingent on Section 4 question 5 confirming a two-rows-per-bet escrow schema.**

**Blocking condition (four checks — Section 4 questions 6, 7-first, 7-second, and 8):** if Rev 2.0 misbehaves on any of the four drift-recalculation behaviors, 5.6b's drift-handling cannot ship until Rev 2.0 is modified.

**Additional confirmation needed, not a drift-behavior blocker but load-bearing (Section 4 questions 9 and 10):** the initiator's stake is validated as whole cents at entry (the rounding induction's base case), and offers don't escrow anything until acceptance (Ruling 7's basis for needing no expiry drain). If question 10 comes back the other way, a drain posting must be designed before this spec is complete.

- Stake-matching enforced at acceptance, exclusively through the derivation function reading the shared odds line.
- The acceptor's derived stake rounds up, once, at acceptance, never re-derived again (Rulings 1, 4).
- Every later drift rescale rounds up, always from the frozen acceptance-locked stake (Ruling 5).
- Every ceiling-cap recalculation rounds up, always fresh from the frozen originals plus the current cap (Ruling 6).
- An offer, before acceptance, posts no escrow entry at all (Ruling 7) — there is no pre-acceptance state requiring a drain, provided Section 4 question 10 confirms this matches the live code.
- `settle_week()` posts one paired entry per bet: debit both escrow rows, credit winner's wallet, the full whole-cent pot, no vig — rounding-free at this step.
- The escrow-close carries its own per-bet `settled` guard.
- Push drains each escrow to its own origin wallet at current balance — rounding-free at this step.
- Every drift recalculation computes from the acceptance-locked originals (and, where relevant, the current cap) fresh each time, never from a prior intermediate, rescaled, or capped result.
- **The whole-cents invariant holds by induction** (Section 5's rulings, proven in Pass 6): base case is acceptance producing two whole cents (given whole-cent initiator input, Section 4 q9); every subsequent operation — rescale, cap, cap-release, settle, push — is whole-cents-in, whole-cents-out. Any future operation added to versus bets must be shown to preserve this invariant or it breaks the proof visibly.
- A canonical test fixture set:
  1. asymmetric odds that divide evenly (e.g., -150/+150),
  2. odds that don't divide evenly (e.g., -110),
  3. a push, including one on a bet with a prior drift adjustment,
  4. a single drift breaching a ceiling,
  5. a second, reversing drift releasing a cap the first drift set,
  6. three or more drift events confirming the acceptor's frozen stake never grows or re-derives,
  7. a drift rescale landing on a fractional cent, confirming correct rounding and non-accumulation across two such drifts from the same frozen original,
  8. a drift breaching a ceiling where the against-the-cap recalculation also lands on a fractional cent, confirming correct rounding and non-accumulation on the cap path,
  9. **NEW: an offer that expires or is cancelled before acceptance — confirm no escrow entry exists to return, per Ruling 7 and Section 4 question 10.**
- Opus Math Review, same issues-only format as L1 and the pool-cents migration, against this Rev 6 and the actual code, before any of this ships.

---

## 7. Explicitly not in this spec

- FR-6.2 (matchup-vs-matchup, multi-party escrow) — deferred, per Section 5's last row.
- Anything about `_nfl_lock_time()` or lock timing — that's Finding 1.1's territory, already resolved.
- The Flexible Stake and Return odds-drift mechanic's own certified math — that's `escrow.py` Rev 2.0. Section 4 questions 6 through 8 ask Rev 2.0 to be re-read for behaviors this spec depends on; if it doesn't already behave this way, that's a blocking prerequisite, stated plainly.
- Any bet type or mechanic other than the two-party versus bet's acceptance-through-settlement lifecycle. Partial-week settlement was checked and confirmed not applicable — each versus bet settles on its own definite outcome, no fractional-settle state exists. RosterSlot/Bench Burn (Findings 5.7/5.8) share the ledger's posting primitives but not the escrow-close arithmetic — confirmed no shared rounding surface.

---

## 8. Opus Review Log

*(Full chronological audit trail. See the PRE-BUILD SUMMARY at the top of this document for the extracted "what gates the code" view.)*

### Pass 1 (folded into Rev 1)

| # | Finding | Resolution |
|---|---|---|
| 5.6b-1 | Worked example closes clean only because it divides evenly | **RESOLVED.** Ruling 1: round up, always. |
| 5.6b-2 | "No rounding surface" claim was false | **RESOLVED, reasoning corrected.** |
| 5.6b-3 | Settle-side posting can't borrow week-level idempotency | **RESOLVED** — per-bet `settled` guard required. |
| 5.6b-4 | Push handling ambiguous on original-vs-current escrow balance | **RESOLVED** — drains current balance to origin wallet. |
| 5.6b-5 | Shared odds line makes matching possible, not enforced | **RESOLVED** — enforcement confirmed via Section 4 q1. |
| 5.6b-6 | Pool remainder rule doesn't transfer to a two-party bet | **RESOLVED by Ruling 1.** |
| 5.6b-7 | Ratio-preservation through drift is design intent, not verified code | **OPEN, tracked in Section 4 as q6.** |
| 5.6b-8 | "Ratio wins" only holds for symmetric drift | **RESOLVED by Ruling 2.** |
| 5.6b-9 | Two-rows-per-bet schema assumed, unconfirmed | **RESOLVED — flagged.** |

### Pass 2 (folded into Rev 2)

| # | Finding | Resolution |
|---|---|---|
| 5.6b-10 | Ruling 1 described as outcome-neutral; the stake round-up is role-fixed | **RESOLVED — description corrected.** |
| 5.6b-11 | Ruling 2 written for a single drift; multi-drift could compound or stick a cap | **RESOLVED by Ruling 3.** |
| 5.6b-12 | Schema assumption flagged in Section 6 only, not Section 5 | **RESOLVED — extended.** |
| 5.6b-13 | Ruling 2's shortfall wrongly cross-referenced to Ruling 1's surplus | **RESOLVED — cross-reference removed.** |

### Pass 3 (folded into Rev 3)

| # | Finding | Resolution |
|---|---|---|
| 5.6b-14 | "Original committed stakes" ambiguous | **RESOLVED — defined explicitly.** |
| 5.6b-15 | Round-up could re-fire per drift, ratcheting an unbounded cost | **RESOLVED by Ruling 4.** |
| 5.6b-16 | Rev 2.0 dependency's failure branch understated | **RESOLVED — restated as blocking.** |
| 5.6b-17 | Schema flag covered only two of four rows | **RESOLVED — extended to all four.** |

### Pass 4 (folded into Rev 4)

| # | Finding | Resolution |
|---|---|---|
| 5.6b-18 | Confirmation: Ruling 4 closes the stake-level ratchet | **CONFIRMED.** |
| 5.6b-19 | The drift *rescale* of the frozen stake produces its own fractional cent | **RESOLVED by Ruling 5.** |
| 5.6b-20 | Ruling 4's row lacked the explicit blocker its dependency implies | **RESOLVED.** |
| 5.6b-21 | No fixture forced a rescale onto a fractional cent | **RESOLVED — seventh fixture added.** |

### Pass 5 (folded into Rev 5)

| # | Finding | Resolution |
|---|---|---|
| 5.6b-22 | Confirmation: Ruling 5's rescale-rounding is determinate and non-accumulating | **CONFIRMED.** |
| 5.6b-23 | The against-the-cap recalculation computes from the cap, not the frozen original, and rounds with no stated rule | **RESOLVED by Ruling 6.** |
| 5.6b-24 | Confirmation: Settle and Push introduce no new rounding | **CONFIRMED, stated explicitly.** |
| 5.6b-25 | No fixture composed a ceiling breach with a fractional-cent cap recalculation | **RESOLVED — eighth fixture added.** |
| 5.6b-26 | Three blocking conditions didn't cover the against-the-cap recalculation's basis | **RESOLVED — fourth blocking condition added.** |

### Pass 6 (folded into Rev 6)

| # | Finding | Resolution |
|---|---|---|
| 5.6b-27 | Pre-acceptance lifecycle (offer, expiry, cancellation) never specified — possible undrained escrow if offers escrow immediately | **RESOLVED by Ruling 7** — offers don't escrow until acceptance, so there's nothing to drain. Depends on Section 4 q10 confirming the live code matches. |
| 5.6b-28 | Confirmation: Ruling 6 survives a two-sided-capping stress walk (both GMs capped at different drifts) with no path-dependence on prior caps | **CONFIRMED.** |
| 5.6b-29 | The whole-cents invariant holds by induction across every operation — no fourth rounding surface exists. Base case rests on the initiator's stake being whole cents, previously unverified | **CONFIRMED — induction stated as the closure argument.** Base-case assumption added to Section 4 as question 9. |
| 5.6b-30 | The chronological review log had grown hard to extract "what gates the code" from, across 5 passes and 26 findings | **RESOLVED — PRE-BUILD SUMMARY added** at the top of this document. |

**Pass 6 summary (Opus):** rounding is closed by proof — an adversarial hunt for a seventh rounding surface (cancellation, two-sided capping, partial-settle, 5.7/5.8 interaction) came back clean, stated plainly rather than manufactured. Two non-rounding completeness gaps surfaced instead (pre-acceptance lifecycle, induction base case) and are resolved by Ruling 7 and an added verification question, respectively.

### Pass 7 (folded into Rev 7 — verification prompt only, no design changes)

| # | Finding | Resolution |
|---|---|---|
| 5.6b-31 | Ruling 7 defers all funding to acceptance-time, which makes "initiator can't fund their own offer by the time it's accepted" a real money-path case the verification questions didn't yet cover | **RESOLVED — added as Section 4 question 11.** No new ruling; this is an acceptance-time atomicity check, same class as the settle-side atomicity already required. |
| 5.6b-32 | The pre-build summary flattened q1 into an ordinary assumption, losing Section 4's own point that a q1 failure is a live production bug independent of 5.6b | **RESOLVED — q1 re-flagged** at the top of the pre-build summary with its full urgency, separate from the ordinary-precondition bucket. |
| 5.6b-33 | Confirmation: Ruling 7 (no pre-acceptance escrow) satisfies the whole-cents induction trivially — "no operation occurs" is not a hidden gap, since Ruling 7 asserts the absence of a state rather than a state that skips the invariant | **CONFIRMED, no change needed.** Contingent on Section 4 question 10 confirming the live code matches Ruling 7. |

**Pass 7 summary (Opus):** ready for live-code verification. No eighth ruling, no further design revision — the rounding design and all seven rulings stand as certified in Pass 6. The only two changes this pass produced are additions to what the Section 4 verification prompt asks, not to what the spec decides. Opus's own words: "the paper phase is genuinely complete."

### Design phase: CLOSED. Next: Section 4 live-code verification.

Seven rulings, seven Opus passes, closed by proof on the rounding question and by explicit confirmation on completeness. No code, no commit, no `railway up --service fantasy-beefs` without Fraser's explicit word. Next action is running the Section 4 prompt (eleven questions) against the live codebase via Claude Code CLI.
