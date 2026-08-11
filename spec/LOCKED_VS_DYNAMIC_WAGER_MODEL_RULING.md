# Locked vs. Dynamic Wager Model Ruling

## ADOPTED — Sections 1–4 · gates 5.1–5.2 open · gate 5.3 cleared

**Status:** Sections 1–4 ADOPTED 2026-07-19 as the model of record. Gate 5.3 cleared 2026-07-19. The Section 6 cascade remains blocked until gates 5.1 and 5.2 are also cleared, including Opus Math Review where specified.
**Amends on adoption:** The current Locked Challenge lifecycle, by replacing the acceptance-freeze rule with proposal-freeze semantics (SIMULATION_ENGINE Rev 7, §Locked Challenge, line 39). The rest of the Locked Challenge model is unchanged.
**Owner:** Fraser (sole decision-maker).
**Purpose:** State the wager-freezing model once, so every downstream spec references this instead of redefining it.

---

## 1. The central principle

A Locked proposal freezes when it is created. A counter creates a new frozen proposal. Acceptance selects one proposal and makes its frozen lineup, odds, stakes, and settlement terms mutually binding. Later Yahoo lineup changes do not alter the accepted Locked Bet.

This is the one sentence every other document should quote.

---

## 1a. Why this change

The previous model froze Locked Bets only at acceptance. This created ambiguity whenever Yahoo lineups changed between offer and acceptance. Proposal-freeze semantics eliminate that ambiguity by ensuring every proposal represents an immutable betting snapshot. Acceptance no longer creates the snapshot — it chooses between immutable snapshots.

---

## 2. Locked Bet — the ruled model

**Initial offer.** Creating the offer captures and freezes an immutable snapshot: the FantasyBeefs snapshot of both Yahoo lineups, the projection snapshot, the odds, the line, both stakes, and the payout. (FantasyBeefs does not maintain an independent lineup — it snapshots Yahoo at the moment the proposal is created.) Later Yahoo lineup changes by either GM do not alter that offer.

**Counter response ("Refresh & Relock").** The recipient may first change their lineup in Yahoo. FantasyBeefs then pulls the updated lineup and creates a *new* frozen counter snapshot, with its own recalculated odds and stakes. The counter replaces the proposal on the table; it does not modify the original record, which remains immutable for history.

**Agreement.** Accepting either the initial offer or the counter makes that exact frozen snapshot the mutually agreed bet. No subsequent Yahoo lineup change by either GM affects it. No re-counter is permitted — once a counter is on the table, the original issuer may only accept or decline.

**Settlement authority.** Locked settlement reads the accepted FantasyBeefs lineup snapshot — not either GM's later Yahoo starting lineup. Yahoo remains the source of actual player *statistics*; FantasyBeefs becomes the source of *which player IDs are covered* by the bet.

**What changed from current behavior:** Today the bet freezes only at acceptance. This model creates frozen proposal snapshots *before* acceptance, and makes acceptance a *selection* of a frozen proposal rather than the freezing event itself.

---

## 3. Dynamic Bet — unchanged, restated for contrast

Initial lineups and odds are displayed. At Handshake, three things freeze: the model version, each side's maximum exposure, and the escrow ceiling (the pot). Lineups, projections, and odds remain live until Final Lock. Final terms lock at the applicable kickoff. Informational refreshes between Handshake and Final Lock are nonbinding and move no money.

No Dynamic protocol behavior changes are introduced by this ruling. This section exists solely to contrast the Locked model, so the Locked/Dynamic distinction lives in one place. It restates existing Rev 7 behavior and modifies nothing.

---

## 4. UI consequence (ruled)

The Locked vs. Dynamic distinction must be visible before a GM accepts — in the offer framing and status, not in fine print. Every initial offer, both modes, shows lineups and odds. The Locked offer additionally explains, in plain language, that its terms are frozen inside FantasyBeefs, that Yahoo changes never touch them at any stage, and that the only way to put different terms on the table is Refresh & Relock in-app.

---

## 5. GATED — resolve before this becomes plan

These items block the Section 6 cascade. Sections 1–4 may be adopted independently, but the documentation and code cascade remains blocked until gates 5.1 and 5.2 are resolved. The items differ in kind: **5.1 is not yet ruled** (needs a money-path decision, Opus-gated); **5.2 is ruled by the adopted model** but its implementation is gated on Opus verification; **5.3 is RULED and cleared** (product/UI ruling, 2026-07-19). Cascade begins once 5.1 and 5.2 also clear.

### 5.1 — Escrow treatment across offer / counter / accept (money-path — Opus gate)

Unresolved questions, all requiring Opus Math Review before any escrow code moves:
- Does Refresh & Relock change the issuer's Anchor Stake, or only lineup and odds?
- If a counter lowers the Anchor Stake, does the issuer's escrow stay put until acceptance?
- If a counter raises it, is the higher amount only validated, or also temporarily reserved?
- When the original issuer accepts the counter, whose escrow adjusts, and in what order?

Current behavior for reference: the issuer's Anchor Stake escrows at initial-offer issue; a counter currently moves no money; a true-up occurs at acceptance. That skeleton may survive, but the four questions above must be answered explicitly.

### 5.2 — Acceptance-time repricing for Locked Bets (required consequence — implementation gate)

Under the proposal-freeze model, a Locked Bet does **not** reprice at acceptance. Acceptance selects the frozen proposal visibly on the table. Current engine behavior in `beef_engine.py respond_to_challenge` (~line 919) recomputes odds at acceptance and therefore conflicts with Sections 1–2. Opus must verify the downstream math and implementation consequences before code changes, but the behavioral rule itself follows from the adopted model — it is not a separate decision.

### 5.3 — Dynamic stake-language reconciliation (UI-vs-spec conflict) — RULED 2026-07-19, gate cleared

**Resolution:** Fix the UI copy to match Rev 7, not the protocol. The issuer's Anchor Stake is fixed and never moves on odds; only the opponent's Derived Stake reprices, capped at its Handshake ceiling (can hold or decrease, never increase). This is a product/UI ruling — no Opus Math Review required, because the copy is being conformed to already-verified math.

**Corrected card copy (Dynamic offer):** "Lineups and odds stay live until Final Lock, just before the first covered player’s game begins. Your Anchor Stake stays fixed; the opponent’s Derived Stake may come down, never above the acceptance ceiling."

**Timing clause amended 2026-08-11 (S8-P4C-2R2), on explicit authorisation.** The economics are unchanged and were not reopened: the Anchor is fixed, only the Derived Stake moves, it may only come down, and it is bounded by the acceptance ceiling. What changed is WHEN the copy says that happens.

The superseded clause read "lock in at kickoff". Checked against the governing trigger, that phrase is ambiguous rather than merely loose: GE-901 and AP-212 fix Final Lock immediately before the EARLIEST scheduled NFL kickoff involving any player in EITHER covered final Yahoo starting lineup. "Kickoff" invites a GM to picture their own fantasy matchup’s Sunday start, when a covered Thursday-night starter — on either side of the wager — locks the whole thing days earlier. It understated how soon the opponent’s stake is fixed, on the one card where the timing is the product.

An intermediate wording, "when the first of your players takes the field", is recorded here as ALSO rejected: it corrected the day and broke the ownership, because the earliest covered player may be the opponent’s. The adopted clause names the first COVERED player’s game and is neutral as to whose lineup supplies it.

Certified by `test_s8_p4c2r2_final_lock_copy.py`, which proves the trigger fires on the opponent’s Thursday starter while the GM’s own lineup plays Sunday, and asserts the shipped copy against that same rule.

Superseded copy, for history: "Both lineups and the odds stay live and lock in at kickoff. Your stake stays put — but if the odds shift, your opponent's stake can come down (never up, never past the max set now). That ceiling never grows."

Original conflict (for history): draft UI copy said the stake could "flex up or down," contradicting Rev 7 (§Dynamic Challenge, line 23; Adjustment formula, lines 91, 98–100).

---

## 6. Documentation cascade (only after adoption + gates clear)

In order:
1. Adopt Sections 1–4 (done 2026-07-19) and clear the remaining Section 5 gates 5.1 and 5.2 (5.3 cleared 2026-07-19).
2. Update Game Engine spec — offer creation stores immutable snapshots; counter becomes a versioned frozen proposal; acceptance references a proposal version.
3. Update Simulation Engine spec — distinguish offer / counter / accepted authoritative pricing records; state no acceptance-time repricing for Locked.
4. Update Settlement — read the accepted FantasyBeefs snapshot, not Yahoo's live lineup.
5. Update Response Card Specification (Rev 1.1 → next rev) — amend Incoming, Countered, Accepted, and Was/Is rules; retire or Dynamic-limit the "counter changes only the Anchor Stake" line.
6. Update Mobile UI/UX specification and screen copy.
7. Update ledger/escrow code once 5.1 is ruled.

Docs first in this order, then the code each doc describes. Money-path pieces Opus-gated as always.

---

## 7. Adoption

Adopting this document means: Sections 1–4 are ruled and become the model of record. Gates 5.1 and 5.2 remain open and block the Section 6 cascade. Gate 5.3 was cleared on 2026-07-19. No protocol doc or code changes until adoption is explicit and the relevant gate has cleared.

Fraser's decision: **ADOPTED 2026-07-19** — Sections 1–4 are the model of record. Gates 5.1 and 5.2 remain to be cleared before the Section 6 cascade begins. Gate 5.3 was cleared on 2026-07-19.
