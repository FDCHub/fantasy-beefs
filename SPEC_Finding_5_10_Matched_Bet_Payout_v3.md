# Finding 5.10 — Matched-Bet Payout Doesn't Match the Escrow — MODULE_SPEC (Rev 3 — FINAL, both Opus passes folded in, ready for Claude Code CLI)

**Status:** Opus Math Review Pass 1 (combined derivation) and Pass 2 (verification) both complete. All findings ruled and folded. No code written.

**Severity:** Launch-blocking, structurally. Confirmed unreachable in practice today (FR-5.12).

**Companion spec:** Ships with FR-5.9 Rev 4. See that spec's Section 6 for the full composed posting design.

---

## 1. The problem, in plain English

*(unchanged)* Odds-scaled payout can exceed the pot whenever the line isn't a coin flip.

---

## 2. What's confirmed, verbatim, from the live-code read

*(unchanged — stakes always equal today, including counter-offers; payout formula and `house_edge` reused verbatim from the GM-vs-house model.)*

---

## 3. What "correct" looks like

*(unchanged from Rev 2)* Winner's payout is the sum of what the two escrow accounts actually hold at settlement — equals `2 × bet.amount` today under equal stakes, but that's the expected value, not the posted one. Odds/moneylines remain display-only.

---

## 4. Design options

*(unchanged from Rev 2 — payout formula, posting mechanism, and scope-to-beef-only rows all approved by Opus Pass 1 and confirmed faithful by Pass 2. See FR-5.9 Rev 4 Section 4 for the `Transaction`-row row, updated there.)*

---

## 5. Verification — complete

*(unchanged — all items hold, including the direct production check confirming zero bets/settlements exist, which resolved the single-party scope question.)*

---

## 6. What "done" looks like (Rev 3 — fixture requirement strengthened per Opus Pass 2, finding 5.10-5)

- `settle_week()`'s beef branch posts the escrow-sourced payout through FR-5.9's joint mechanism, replacing `amount × odds` entirely for matched bets.
- Single-party bets out of scope, per FR-5.12.
- **Test fixture, revised — same requirement as FR-5.9 Rev 4 Section 7.** A fixture using only equal stakes cannot distinguish the escrow-sourced fix (what this spec rules should be built) from the `2 × amount` shortcut (the regression it exists to prevent) — both produce identical numbers when the two escrows hold equal balances. **At least one fixture case must seed the two escrows with deliberately unequal balances** and assert the credit equals their actual sum, not `2 × either`. This is the only test that proves the fix was actually implemented, not just that odds-scaling was removed.
- Full fixture set: (1) unequal-escrow win — proves escrow-sourcing; (2) equal-stakes win, non-50/50 odds — proves odds don't drive payout; (3) push; (4) even-odds win. All close to zero.
- No further Opus pass required — both passes complete, both sets of findings folded.

---

## 7. Explicitly not in this spec

*(unchanged)* Asymmetric Flex Stakes, The_Lineup, FR-5.9's posting mechanism (referenced, not restated), FR-5.11.

**Single-party bet settlement — explicitly out of scope, tracked as FR-5.12.** Per Opus Pass 2: this exclusion is a **maintained invariant**, holding only as long as single-party bet placement stays parked per the launch cut line. If ever switched back on, this fix becomes a hard prerequisite for that path first.

---

## 8. Review log

**Internal (Sonnet) pass** — superseded.

**Opus Math Review Pass 1 (combined with FR-5.9)** — complete. 5.10-1/5.10-2 (escrow-sourced payout) approved; 5.10-3 (scope) resolved via direct production check, logged as FR-5.12; 5.10-4 (cross-spec consistency) approved.

**Opus Math Review Pass 2 (verification-only)** — complete. Confirmed the fold was faithful, no stale posted-value language survived. One finding directly relevant to this spec:
- **5.10-5** (win fixture can't distinguish the fix from the regression on equal-stakes data) — **Approved.** Folded into Section 6 above.

(5.10-6, the `Transaction`-row asymmetry finding, is folded into FR-5.9 Rev 4 Section 4, where that table lives.)

**No further Opus pass scheduled.** Ready for Claude Code CLI to verify against live code at build time. No code, no commit, no `railway up --service fantasy-beefs` without Fraser's explicit word.
