# FantasyStakes UI/UX — Continuation / Transition Package · Rev 2.1

**Status:** UI/UX POR through this session, committed. Backend implementation gaps remain authoritative per prior recon — this package is product/UX authority plus a backend-contract ledger, not a claim that the backend produces these values today.
**Supersedes:** Rev 2.0 (`spec/FantasyStakes_UIUX_Continuation_Package_Rev2_0.md`).
**Canonical prototype:** `spec/FantasyStakes_UIUX_Prototype_Rev2_1.html` — byte-identical to `tools/prototype/index.html`.
**Brand:** FantasyStakes (visible) / FantasyBeefs (repo). Tagline OUR THING · YOUR LEAGUE. Bone/gold. Yahoo OAuth purple `#5f01d2`.

---

## 1. Scope of Rev 2.1

Rev 2.1 froze the accounting model for My Ledger and rebuilt the tab as an auditable double-entry statement. My League and My Action are unchanged POR. Wrap Up and Rules & Settings remain baseline, not yet walked. The defining event of this session was an independent Opus math/accounting review that ruled on how unresolved escrow and the season-opening allocation enter Current Settle.

---

## 2. Opus accounting ruling (accepted as POR)

**MODEL B is correct.** Deciding principle: *a transfer among GM-owned settlement-relevant asset accounts does not change the GM's economic position.*

- The GM's **own** unresolved wager stake in escrow / In Play is a settlement-relevant asset at posted own-stake value.
- Funding a wager (Wallet/Weekly Min → escrow) is a **reclassification**, not a loss: **Current Settle delta = $0** at commitment.
- Model A (excluding open escrow) is rejected: it makes the stake vanish at commitment and reappear at settlement, including on PUSH/VOID where no economic event occurred.
- **In Play for Current Settle = ONLY the GM's own funded open stake.** Never opponent stake, total pot, potential winnings, projected payout, or upside. Asymmetric wagers count only the GM's own funding legs.

**General form:** `Current Settle = settlement-relevant GM assets − GM obligations`.
- **Assets:** Wallet, remaining Weekly Min Reserve, Weekly Min left, GM's own unresolved In Play/escrow, Out of circulation, earned season awards.
- **Excluded asset:** Championship Reserve once irrevocably contributed.
- **Obligations:** opening BAB advance, Top-Off advances, Skunk fines, other governed settlement obligations.

**Load-bearing invariants (record in backend contract):**
1. Whole ledger balances to zero.
2. Pure transfers among GM asset accounts do not change Current Settle.
3. Wallet/Weekly Min → In Play is reclassification, not loss.
4. In Play = GM's own funded unresolved stake only.
5. Top-Off issuance: asset +X / advance −X → Current Settle Δ $0.
6. Weekly Min → Out of circulation → Current Settle Δ $0.
7. PUSH/VOID returning escrow → Current Settle Δ $0.
8. Actual win/loss changes Current Settle only by the true economic result.
9. Skunk fine reduces Current Settle without touching Wallet.
10. Championship contribution not GM-recoverable.
11. Earned award raises Current Settle only when entitlement is final.
12. **Week-close invariant:** a Weekly Min cent exists in exactly one of {Weekly Min left, open escrow, Out of circulation} at any instant — never two, never zero. Escrow-committed funds are NOT unused and must not be swept.

---

## 3. Core economic POR

- Season opening advances **$220** of BAB credit → **−$220 opening obligation**. Allocated $140 Weekly Min Reserve + $80 Championship Reserve + $0 Wallet.
- Winnings and credits pay the obligation down. Assets > obligations → Current Settle positive (league owes GM); obligations > assets → negative (GM owes).
- Current Settle is the exact receivable/payable position — **not** profit/loss vs buy-in. **Buy-in IS part of the math** (this supersedes the prior "buy-in not subtracted" line).
- **Top-Off** is an additional advance: −$X obligation / +$X Wallet, Current Settle Δ $0 at issuance.
- **Championship Reserve:** $80 irrevocable, does not return; pot pays 60/30/10 (champion/runner-up/third). Earned payout is a positive season award only when final.
- **Weekly Min:** distinct from Wallet, funds wagers first; unused expires at **Fantasy Week Close** (not first kickoff) → Out of circulation, owed back. No commissioner discretion.
- **Skunk:** $10, weekly worst-margin loser, posted once, off-Wallet, reduces Current Settle; user term "Skunk fines −$X"; strip shows count.

---

## 4. Screen-by-screen POR

### My League — POR (frozen)
Fixed three-rail sportsbook (Big Board, Pool Bets, Yahoo Matchups), equal-height siblings, horizontal scroll only inside rails, Pool rail never below four options. No vertical page scroll. Header: Yahoo league name / `Fantasy Sportsbook · Week X · Regular Season`. Strip: League record/rank | Wallet | Weekly min left | Available to bet, where **Available = Wallet + Weekly min left**. Whole-card Versus tap → wager sheet.

### My Action — POR (frozen)
Four buckets: ACTION REQUIRED (explicit decision pending) → WAITING (committed, awaiting party/clock) → LIVE (competitively unresolved committed only) → COMPLETED (competitively terminal). Compact 2-up card grammar across all buckets. Pool DECIDED → COMPLETED as **SETTLING** (DECIDED ≠ SETTLED): shows winner/outcome, won/lost, exact pending payout; excluded from Settled and Season Bet Record; pending net stays in Upside left; no BAB movement until settlement commits. Strip: Season Bet Record | Bet this week | Upside left | Settled. Reconciled sample **14–7 | $129 | +$129.33 | +$20** (do not reopen). Parked: counter-received tile opens generic sheet; counter-specific accept/decline sheet deferred to consolidated interaction pass.

### My Ledger — POR (rebuilt this session, Model B)
Auditable accounting statement. Header: `My Ledger` + compact `[Request Top-Off]` button on the title row; no subtitle, no full-width bar. All four-cell strips: labels left, values centered. **THIS WEEK:** Wallet | Weekly min left | In Play | Available to bet. **THIS SEASON:** Net winnings | Skunks (count) | Top-Off Remaining | Current Settle (gold). Signed money everywhere (`+$X` / `−$X` / `$X`), never "$X due" as the amount. Ledger organized as accounting groups: **CURRENT POSITION → HOW WE GOT HERE (Wallet) → WHAT IS STILL COMMITTED (In Play) → WEEKLY MIN → WHAT WILL SETTLE LATER (Season settlement) → WHAT YOU OWE BACK (Obligations) → BOTTOM LINE (Current Settle)**. Collapsible sections, drill sheets. Current Settle banner shows full assets-minus-obligations reconciliation. All ledger text unified to one bone color; Current Settle heading right-justified.

**Reconciled Model B sample:** assets Wallet $152 + Weekly min left $10 + Weekly Min Reserve $120 + In Play $89 + Out of circulation $20 + awards $0 = **$391**; obligations advance −$260 + skunk −$20 = **−$280**; **Current Settle = +$111**. (This replaces the prior Model-A +$152; the +$152 is now Wallet only.)

**Top-Off lifecycle:** REQUEST (PENDING, requested amount, remaining-before, timestamp, optional note) → COMMISSIONER DECISION (APPROVED, amount, commissioner, timestamp, remaining-after) → POSTED RECEIPT (+$X to Wallet, Wallet before→after, remaining-after, posting ref). Failure state `APPROVED · POSTING PENDING` shows no Wallet credit. GM-facing may merge approval+posting into one receipt; backend events stay distinct. Pending requests are NOT shown in the accounting Ledger. My Ledger is the primary Top-Off entry point; My League gets a later contextual secondary action; no permanent Top-Off in My Action or Wrap Up.

### Wrap Up / Rules & Settings — NOT YET FULLY WALKED
Baseline preserved. Carried future edits: remove commissioner Weekly-Min-treatment option from Rules & Settings; preserve commissioner role boundaries; Rules explains Top-Offs but the GM's primary Top-Off action lives in My Ledger; commissioner retains approval controls.

---

## 5. Sample-data / provenance notes (prototype)
All figures are STATIC prototype values for UX rendering. No backend calculation is authoritative in the HTML. Values classified: Wallet/Available reads are ledger-derivable today (B-class); Current Settle, In Play per-GM sum, Weekly-Min lifecycle, Out-of-circulation, Skunk dues, Top-Off workflow, advance obligations are ruled-but-backend-pending; drill-down rows and the Top-Off cap are static/pending.

---

## 6. Backend contracts introduced or clarified by UI/UX Rev 2.1

Classification: **CONFIRMED** (exists, verified) · **CLARIFIED** (exists, meaning sharpened) · **NEW** (must be built) · **CONFLICT** (spec change required).

| Requirement | Classification | Existing authority / evidence | Rev 2.1 effect | Backend action | Blocking |
|---|---|---|---|---|---|
| One authoritative double-entry ledger | CONFIRMED | `ledger/ledger.py` post/balance_of/trial_balance | Ledger is the sole source of truth for all Ledger values | none (exists) | No |
| Retire legacy `Wallet.balance` float mutation | CONFLICT | `db/schema.py:191` Float; `settlement:718`, `wallet_manager:143` mutate it | Ledger must be single authority | Remove float writes; repoint bet funds-check to `balance_of()` | **Yes** |
| Integer cents end-to-end | CONFLICT | settlement pays float dollars (`settlement:704–718`) | signed-cents accounting | convert settlement to cents + post | **Yes** |
| Authoritative Wallet query | CONFIRMED | `main.py:451,622,1030` use `balance_of` | Wallet strip reads ledger | none | No |
| Current Settle query/reconciliation | NEW | none in production | principal Ledger output | build assets−obligations function | **Yes** |
| Liability/obligation account architecture | CLARIFIED | `receivable:{team}` exists ("IOUs owed"), Door 2 `buy_in_tab` specced, no caller | advances must post obligations | wire Door 2; add `advance:{team}` + `skunk_due:{team}` (recommend separate accounts) | **Yes** |
| Opening −$220 advance / +$140 / +$80 / $0 | NEW | buy-in uses Door 1 `buy_in_paid`/`world` (`stripe_connect:331`) | opening obligation model | post advance via Door 2, split reserves | **Yes** |
| Top-Off: request→pending→approve→post→credit→capacity | NEW | `wm_deposit` mutates float (`main.py:1003,987`, FR-7.28 pending); FAAB is a different economy | full lifecycle + advance obligation | build request persistence, commissioner review, ledger `wm_deposit` + `advance` posting, cap math, idempotency | **Yes** |
| Weekly Min lifecycle (reserve→release→min-first→provenance→reversals→week close→sweep→one-destination) | NEW | only a threshold in `shortfall_sweep`; `min:{team}:{week}` specced in Spec 2 | funds-first + sweep + invariant | build `min:{team}:{week}`, funding-leg provenance, Week-Close sweep | **Yes** |
| In Play: per-GM own-stake query, asymmetric correctness, partial-settlement granularity, void/refund, cross-week-close | NEW | settlement reads individual `escrow:{bet}`, no per-GM sum | In Play asset value + Current Settle inclusion | build own-stake escrow sum keyed to GM funding legs only | **Yes** |
| Out of circulation: account, week-linked sweeps, cumulative query, settlement return | NEW | none | positive settlement asset | build `weekly_min_frozen:{team}` (ruled 2026-07-14) sweep + return | **Yes** |
| Skunk: weekly determination, once-only per GM/week, separate obligation, no Wallet/Available impact, pot routing | NEW/CLARIFIED | pot display only (`main.py:2675`); `fine` door test-only; rule MasterPlan v6:149 | dues as `skunk_due:{team}` | build assessment + once-only posting + settlement routing | Partial |
| Championship: $80 irrevocable, pot, 60/30/10, final entitlement posting | CLARIFIED | `settlement_report.py` computes pot distribution; distribution % **not** confirmed in specs | earned award only when final | confirm 60/30/10 authority; build entitlement posting | Partial (ruling) |
| Wager accounting: stake/settlement posting, PUSH, VOID, Dynamic refunds, Pool settlement, DECIDED vs SETTLED, own-stake escrow | CLARIFIED/CONFLICT | pool posts clean; Versus settlement dual-writes; no refund door | Model-B invariants | cents-only settlement; refund/void doors; own-stake escrow discipline | **Yes** |
| UI data contracts (My League strip, My Action strip, wager-adjusted LIVE, Bet this week, Upside left, Current Settle, Net winnings, Skunk count, Top-Off Remaining, Ledger histories) | NEW | none produce these live | strips surface authoritative values | build read models per tab | Partial |
| Prior dependencies retained | — | — | Yahoo live data/rank/name/kickoff; prediction persistence; mutation/history; Pool lock; DECIDED equivalents; claims/remainder; rollover; lineage; Simulation Engine reuse; Wrap Up sources; catalog formula gaps | carry forward | varies |

### Section summary
- **New backend work:** Current Settle reconciliation; opening-advance posting; Top-Off workflow + advance obligation; Weekly-Min lifecycle; per-GM In Play sum; Out-of-circulation; Skunk assessment/dues.
- **Clarified existing work:** obligation-account architecture (`receivable`/Door 2 exist, unwired); Wallet reads (already ledger); championship distribution (compute exists, % unconfirmed).
- **Conflicts / spec changes needing Fraser:** retire `Wallet.balance` float; cents-only settlement; account disambiguation (`advance:` vs `skunk_due:` vs pot-`receivable`).
- **Fully supported today:** the `post()` primitive; pool stake/entry/settlement/rollover postings; Wallet/Available reads.
- **Recommended build order (Current Settle must come after the authoritative accounts it consumes):**
  - **P0** — single Ledger authority: retire `Wallet.balance` float writes, repoint bet funds-check to `balance_of()`, integer cents end-to-end (cents-only settlement).
  - **P1** — advance-liability architecture (`advance:{team}`, `skunk_due:{team}` — separate accounts) + opening $220 posting via Door 2 ($140 Weekly Min Reserve, $80 Championship contribution, $0 Wallet).
  - **P2** — Weekly Min lifecycle: reserve → weekly release → min-first funding → funding-leg provenance → **canonical Fantasy Week Close** (technical spec required) → unused sweep → Out of circulation, with the one-destination invariant.
  - **P3** — own-stake In Play/escrow + wager/refund/void accounting (per-GM own-stake sum, asymmetric correctness, partial-settlement granularity, PUSH/VOID Δ$0).
  - **P4** — Skunk obligations: weekly determination, once-only per GM/week posting, settlement routing.
  - **P5** — BAB Top-Off workflow + advance posting / cap mechanics (request→pending→approve→post→credit→capacity, idempotency).
  - **P6** — season-award / championship settlement posting (60/30/10 entitlement, final-only).
  - **P7** — authoritative Current Settle reconciliation/query — **last**, because it consumes every account above. Adjust ordering only where code dependencies prove necessary; Current Settle must never precede the balances it reads.
  - Money-path work is gated by Opus math review.

---

## 7. Unresolved product rulings
**Exactly one product/accounting ruling remains unresolved:**
1. **Top-Off Cap numeric anchor** — do not choose $140 or $220. Shown as "pending" in the prototype.

Everything else is POR:
- **Championship distribution is POR:** each GM irrevocably contributes $80; pot pays 60% champion / 30% runner-up / 10% third place. A non-winner's reserve stays contributed.
- **Weekly Min disposition/timing is POR:** unused Weekly Min sweeps at canonical **Fantasy Week Close** (not first kickoff), no commissioner discretion, returned through Out of circulation at season settlement.
- **Current Settle** is gross assets − obligations; buy-in is an obligation term, not separately subtracted.

*Technical (not a Fraser ruling):* the backend still needs a deterministic definition/implementation of the **canonical Fantasy Week Close event** to trigger the sweep. This is backend technical specification, tracked in the build order, not an open product decision.

---

## 8. Provenance
- Rev 2.0 durable: commit `54c57f72b37bff51ed317e458e59206750adef5a`, canonical HTML SHA `A00C882…BEA7`.
- **Rev 2.1 authoritative commit SHA: PENDING.** The sandbox produced a **local, unpushed** commit `353a95c3f09d1f8576e9cc038d5c875ecc2345dd` — this is a Claude-sandbox local commit, **NOT the authoritative Rev2.1 repo commit**. The authoritative commit does not exist until the ThinkPad integration + push.
- **Rev 2.1 canonical HTML SHA-256: candidate/PENDING** = `8860349db0c02eb8d848b5bc3d552033ef492f72de3510ec96d031f6db86c72d`. This is the expected normalized SHA from the sandbox; it is **not authoritative** until ThinkPad normalization, push, and fresh-worktree verification confirm it. If the ThinkPad's CRLF normalization differs, this candidate must be reconciled before it is trusted.
- Branch: `remediation/foundation-phase-1`.
- **Push status: NOT PUSHED. Fresh-origin provenance: NOT RUN.** Both pending the ThinkPad cycle.

---

## 9. Artifact disposition (desired vs completed)

**Desired end state** — repo = durable source of truth; Claude Project panel = operational retrieval surface.

| Artifact | Desired: repo | Desired: panel | Completed in repo? | Fraser action |
|---|---|---|---|---|
| Rev2.1 canonical HTML (`spec/...Prototype_Rev2_1.html`) | Yes | Optional | **Local commit only, NOT pushed** | Push from ThinkPad |
| Live `tools/prototype/index.html` | Yes | No | **Local commit only, NOT pushed** | Push from ThinkPad |
| Continuation package (this file) | Yes | **Yes** | **Local commit only, NOT pushed** | Push + upload to panel |
| Next-thread opener | Yes | **Yes** | **Local commit only, NOT pushed** | Push + upload to panel |
| `rev2_1_commit.bundle` | No (transport only) | No | n/a | Optional; delete after push |

**I cannot place files in the Claude Project panel directly.** After you push, upload these two files into the Project panel yourself so the next thread can retrieve them:
- `spec/FantasyStakes_UIUX_Continuation_Package_Rev2_1.md`
- `spec/FantasyStakes_UIUX_Next_Thread_Opener_Rev2_1.md`

The two HTML files belong in the repo (and GitHub Pages) only; they don't need to be in the panel.

## 10. Next steps
The next thread's first task is the **backend accounting build**, in the P0→P5 order above, gated by Opus math review per money-path discipline — OR continued UI/UX walk of Wrap Up and Rules & Settings. The Model-B Current Settle is now the target the backend must produce. No backend code was written this session.
