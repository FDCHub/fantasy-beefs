# Finding 5.9 — Beef Settlement Never Closes Escrow — MODULE_SPEC (Rev 4 — FINAL, both Opus passes folded in, ready for Claude Code CLI)

**Status:** Opus Math Review Pass 1 (combined derivation) and Pass 2 (verification) both complete. All findings ruled and folded. No code written.

**Severity:** Launch-blocking, structurally. Confirmed zero bets and zero settlements exist in production today (FR-5.13) — a landmine, not an active incident.

**Companion spec:** Ships with FR-5.10 Rev 3. See Section 6 for the composed posting design.

---

## 1. The problem, in plain English

*(unchanged)* Settlement should close both sides' escrow when a matched bet settles. Instead it mutates `wallet.balance` directly and never debits escrow. The stake never comes back out.

---

## 2. What's confirmed, verbatim, from live-code reads

*(unchanged from Rev 3 — see that revision for full eight-item detail, plus item 9: zero bets and zero settlements exist in production, confirmed not a broken join.)*

---

## 3. What "correct" looks like

*(unchanged)* Escrow debits and a winner credit that net to zero, closing cleanly, per L1's ledger law (Finding 2.8, Door 4).

---

## 4. Design options (Rev 4 — `Transaction`-row row updated per Opus Pass 2 finding 5.10-6)

| Name | Issue Summary | Options | Recommendation & Reasoning |
|---|---|---|---|
| **Settlement posting mechanism** | *(unchanged from Rev 3)* Debit each escrow's actual balance; credit the winner the sum of the two debited values. | (a) Escrow-sourced, as specified. (b) Recomputed `amount`. | (a) — approved, both Opus passes. |
| **Push handling** | *(unchanged)* | (a) Two independent postings, each escrow-sourced. | (a) — approved. |
| **Idempotency** | *(unchanged)* | (a) In-memory tracking + existing status filter. | (a) — approved, confirmed safe. |
| **`Transaction` table under joint posting** | **Revised per Opus Pass 2, finding 5.10-6.** Under a joint win posting, the two `Transaction` rows are *not* symmetric: the winner's bet involves both its own escrow debit (`b_w`) *and* the full combined credit (`b_w + b_l`); the loser's bet involves only its own escrow debit (`b_l`) and no credit. Saying "each bet carries its own share" implies a clean symmetric split that doesn't exist — the winner's row carries the loser's stake flowing through it too. | (a) One `Transaction` row per `Bet` (two per challenge). The **winner's row** carries its own escrow debit (`b_w`) and the **full combined credit** (`b_w + b_l`) — explicitly asymmetric, not "its own share." The **loser's row** carries only its escrow debit (`b_l`), no credit. (b) Some other split not yet specified. | (a), once the still-pending grep (does any report expect exactly one `Transaction` row per bet, and does it expect each row to balance on its own?) confirms this shape is compatible with existing consumers. **Not yet finalized** — this row states the correct *shape* now (asymmetric, not "each bet's own share"), so whoever runs the grep and builds this knows what to look for, but the grep itself is still pending, same as it was in Rev 3. |

---

## 5. Verification — complete

*(All nine items from Rev 3 hold — no new verification needed for this revision; Pass 2 was a language/design check, not a live-code question.)*

---

## 6. Composition with FR-5.10 (unchanged from Rev 3 — confirmed faithful by Opus Pass 2)

- **Win:** debit `escrow:{winner_bet.id}` its actual balance `b_w`, debit `escrow:{loser_bet.id}` its actual balance `b_l`, credit `wallet:{winner_team}` `b_w + b_l`. Closes by construction: `−b_w − b_l + (b_w + b_l) = 0`.
- **Push:** two independent postings, each escrow-sourced, one per side.
- **Loss:** folded into the win posting's second debit leg.
- `2 × bet.amount` remains the **expected value** of `b_w + b_l` under today's equal-stakes reality — useful for display and preview — but is never the posted value. Confirmed by Opus Pass 2: no surviving reference anywhere in either spec describes `2 × amount` as posted.

---

## 7. What "done" looks like (Rev 4 — fixture requirement strengthened per Opus Pass 2, finding 5.10-5)

- `settle_week()` settles each `BeefChallenge` jointly: win posts the three-leg escrow-sourced entry; push posts two independent two-leg entries; both replace the direct `wallet.balance =` mutation for beef bets.
- Single-party bets remain out of scope — FR-5.13, confirmed unreachable in production today.
- `Transaction`-row shape resolved per Section 4 above, pending its grep.
- **Test fixture, revised — this is the load-bearing change from Pass 2.** The original fixture description ("one won matched pair with non-50/50 odds") is **necessary but not sufficient**: because it uses equal stakes, it cannot distinguish the escrow-sourced fix from the `2 × amount` shortcut it exists to catch — both produce the identical number when the two escrows hold equal balances. **The fixture must include at least one case where the two escrows are deliberately seeded with unequal balances** (e.g., post two different amounts directly at the ledger level before settling, rather than relying on today's placement path, which always produces equal stakes) — and assert the credit equals `b_w + b_l` exactly, **not** `2 × either` value. This is the only test that actually proves the escrow-sourced implementation was built, rather than a recomputation that happens to agree with it on equal-stakes data. Without this case, a builder could implement the `2 × amount` regression, pass every fixture, and ship the exact bug Opus caught.
- Full fixture set, revised: (1) unequal-escrow win — proves escrow-sourcing, not just non-odds-scaling; (2) won matched pair, equal stakes, non-50/50 odds — proves odds no longer drive payout; (3) pushed pair; (4) lost/won pair at even odds. Trial balance closes to zero in every case.
- No further Opus pass required before build — Pass 1 derived the design, Pass 2 verified the fold and caught the one thing that mattered (the fixture gap). Both are now addressed in this revision.

---

## 8. Explicitly not in this spec

*(unchanged)* 5.6b's asymmetric stakes, The_Lineup, FR-5.13, bet.amount/odds cents migration.

**FR-5.13's scope, clarified per Opus Pass 2:** the single-party path's "unreachable" status is a **maintained invariant, not a permanent fact** — it holds only as long as single-party bet placement stays parked per the launch cut line. If single-party betting is ever switched back on, this escrow-close fix becomes a hard prerequisite for that path, not an afterthought. Tie FR-5.13 to the parked-code decision explicitly so this isn't forgotten later.

---

## 9. Review log

**Internal (Sonnet) pass** — superseded by Opus Pass 1.

**Opus Math Review Pass 1 (combined derivation, FR-5.9 + FR-5.10)** — complete. Four findings (5.10-1 through 5.10-4), all ruled and folded into Rev 3: escrow-sourced debits and credit (approved), scope narrowed to beef/matched only per direct production check (resolved, logged as FR-5.13), cross-spec consistency (approved).

**Opus Math Review Pass 2 (verification-only)** — complete. Confirmed the escrow-sourced fold was faithful in prose, no stale `2 × amount`-as-posted-value language survived. Two findings:
- **5.10-5** (win fixture can't distinguish the fix from the regression on equal-stakes data) — **Approved.** Folded into Section 7 above; this is the one that mattered.
- **5.10-6** (`Transaction`-row asymmetry under a joint win, language implied a clean split that doesn't exist) — **Approved.** Folded into Section 4 above.

**No further Opus pass scheduled.** Both revisions are ready for Claude Code CLI to verify against live code at build time and implement. No code, no commit, no `railway up --service fantasy-beefs` without Fraser's explicit word.
