# HANDOFF — Economy & Skunk Reconciliation Finding-Set (Rev 2, review-corrected)

**From:** UI/UX feature branch (My Ledger design session, 2026-07-20).
**To:** Main development line → money-path thread.
**Status:** Revised after design review. Four review defects corrected; three open questions RULED (R1–R3, below) and baked in. Ready for Opus.
**Queue note:** Joins gate 5.1 / 5.2 / pool-fee already on the money-path queue. Sequence as ONE Opus batch — all share escrow / buy-in / min surfaces. Findings 1+2 = one review; Finding 3 independent; Finding 4 gates the UI.

**Rev 2 changes from Rev 1:**
1. Available to Bet — removed the commitment subtraction (double-counted under Spec 2 real-escrow). Now `wallet + current-week min`.
2. 4/11 ratio — resolved as **target ratio, integer-cent formula off the weekly-min reserve** (R1).
3. Skunk — elevated from "delete BAB-505" to a **formal receivable/liability money path** (R2).
4. Skunk tie — **deterministic split ruling** added (R3).

---

## THE LOCKED MODEL (product-owner approved)

Four buckets, wallet starts $0. Default $10 stop, 14-week league:

| # | Bucket | Account | Default | Wagerable |
|---|---|---|---|---|
| 1 | Wallet | `wallet:{team}` | **$0** | Yes — winnings + top-offs only |
| 2 | Weekly-Min account | `min:{team}:{week}` | $0, +rate/Tue | Yes — this week only |
| 3 | Weekly-Min Reserve | `min_reserve:{team}` *(NEW name — must NOT reuse `reserve:{team}`)* | rate × weeks | No — releases weekly into #2 |
| 4 | Championship Reserve | `reserve:{team}` | ~4/11 buy-in | No — season-end / title only |

---

## RULINGS (R1–R3) — apply before/within Opus review

### R1 — Championship Reserve ratio (resolves Finding 2's integer-cent gap)
No league is restricted by week count. Compute in integer cents:
```
weekly_min_reserve_cents = weekly_min_rate_cents × yahoo_regular_season_weeks
championship_reserve_cents = round_half_up(weekly_min_reserve_cents × 4 / 7)
buy_in_cents = weekly_min_reserve_cents + championship_reserve_cents
```
- Yahoo determines regular-season week count.
- 4/11 is a **target ratio, NOT an exact invariant** for every league length.
- The two reserves **always sum to buy-in exactly** (buy-in is defined as their sum).
- Default check: reserve 14000¢ → champ round(14000×4/7)=8000¢ → buy-in 22000¢. Matches current table.

### R2 — Skunk liability account (resolves Finding 3's conservation break)
Skunk is an **off-wallet obligation** on the GM's tab. Canonical accounts:
```
receivable:skunk:{team_id}:{season}
skunk:{league_id}:{season}
```
Weekly assessment (balanced):
```
receivable:skunk:{team_id}:{season}   −assessment_cents
skunk:{league_id}:{season}            +assessment_cents      sum=0
```
Season payout to points champion (balanced):
```
skunk:{league_id}:{season}            −pot_cents
wallet:{winner_team_id}               +pot_cents             sum=0
```
Isolation rules (all mandatory):
- Never debits Wallet.
- Does NOT reduce Available to Bet.
- Does NOT reduce escrow capacity.
- Does NOT block wagers or gameplay.
- NOT auto-collected from future BAB credits.
- A GM MAY finish the season with an unpaid receivable; it stays attached to the archived season.
- Offline settlement is a **separate reconciliation record** — settling the real-world tab creates/destroys/transfers no BAB.
- Pot credited to champion's Wallet (postseason-spendable) once all weekly assessments are final.

### R3 — Skunk tie (resolves "exactly one is unsafe")
Fractional points reduce but don't eliminate ties. If multiple GMs tie for widest margin of defeat, **one** configured fee is split equally:
```
base_share = weekly_skunk_fee_cents // tied_gm_count
remainder  = weekly_skunk_fee_cents %  tied_gm_count
```
Each tied GM gets base_share; remainder assigned one cent at a time, ascending GM ID. Three-way example:
```
receivable:skunk:{gm_1}:{season}   −334
receivable:skunk:{gm_2}:{season}   −333
receivable:skunk:{gm_3}:{season}   −333
skunk:{league_id}:{season}        +1000                      sum=0
```
- Only ONE fee per week regardless of tie count.
- Tied assessments sum to the fee exactly.
- No Yahoo tiebreaker. No tied GM charged the full fee.

---

## FINDING 1 — Economy topology: code & spec are 2-bucket funded-wallet; model is 4-bucket $0-wallet

**Existence-check (2026-07-20):** `economy_config.py:42–46` funds `wallet_cents` (=14000 → $140 start). Spec §4 BAB-107 = same 2-bucket funded-wallet. No `min` separation at config layer.

**Fix:** Wallet seeds at $0 at buy-in. `economy_config.py`'s `wallet_cents` is semantically the **Weekly-Min Reserve** — rename to `weekly_min_reserve_cents` and route it to a NEW `min_reserve:{team}` account (NOT `reserve:{team}`, which is the Championship Reserve). Buy-in Door 1 posting seeds wallet 0, min_reserve full, reserve per R1. Rewrite BAB-107 for four buckets. **Opus-gated. Bundle with Finding 2.**

---

## FINDING 2 — `× 14` hardcoded AND enforced as a validation invariant

**Existence-check (2026-07-20):** `economy_config.py:14,61–64` — `wallet_cents == weekly_min_cents * 14` is an assertion that **raises** on any non-14 value. Spec §7 CFG-201 hardcodes ×14.

**Fix (per R1):** Stops become five weekly-min **rates**, not fixed dollar tables. Weekly-Min Reserve = rate × Yahoo regular-season weeks. Championship Reserve = round_half_up(reserve × 4/7). Buy-in = their sum. Rewrite the `×14` invariant to validate against the derived values, not a fixed 14. Source week count at league config (Yahoo = CORE-001). **Opus-gated. One review with Finding 1.**

---

## FINDING 3 — Skunk mechanic unbuilt; build as formal liability money path (per R2 + R3)

**Existence-check (2026-07-20):** `ledger.py:242` — "skunk" only in a comment. `schema.py:804` — `points_for` column exists, unused. No detection, assessment, pot, or payout anywhere.

**Locked mechanic:**
| Aspect | Rule |
|---|---|
| Trigger | Widest Yahoo margin of defeat that week; **ties → R3 split** |
| Amount | $10 default (commish-adjustable, separate locked setting) |
| Charge | **Off-wallet receivable (R2)** — never touches wallet |
| Pot | Accrues weeks 1 → regular-season end; max ≈ weeks × fee |
| Winner | Regular-season points champion (highest cumulative Points For) |
| Payout | Spendable BAB → champion's `wallet`, usable postseason, after all assessments final |
| Weeks | Yahoo-derived, not hardcoded |

**Build:** widest-margin detector (reads Yahoo finalized margins), R2 postings for assessment + payout, R3 tie split, idempotent weekly assessment + payout (immutable event identity). **Spec:** DELETE BAB-505 (wallet collection — contradicts R2); rewrite BAB-506/CFG-507 with wallet-destination + postseason spendability; rewrite AP-141–148 as the controlling skunk protocol. **Opus-gated. Independently buildable.** Fixture: a GM who is both a weekly skunk (owes receivable) and season points champ (wins pot) — paths must not net.

---

## FINDING 4 — Available to Bet (review-corrected: NO commitment subtraction)

**CORRECTED definition (post–Spec 2 real-escrow):**
> **Available to Bet = ledger_balance(`wallet:{team}`) + ledger_balance(`min:{team}:{current_week}`)**

**Why no subtraction:** Spec 2 debits the source accounts at ISSUE (issuer Anchor) and at ACCEPTANCE (Derived) — real escrow. Those commitments are **already absent** from posted wallet/min balances. Subtracting committed BAB again double-counts escrow. Counter proposals move no money and are not commitments.

**Existence-check (2026-07-20):** no `available_to_bet` / `pending_bucket` / `remaining_min` in code; availability computed inline as `ledger_cents − ch_reserved` at four sites.

**Fix:** Build one shared `get_available_to_bet(team, week, session=db)` = wallet + current-week min, no subtraction. Spec: keep BAB-104 as raw wallet; add **BAB-104a** = wallet + current-week min; **remove "− committed BAB"** from BAB-104a and BAB-210, stating escrow is already excluded because funding debits the source accounts. Affects Spec 2's availability helper and its retirement of `_challenge_reserved`. **Opus-gated. Gates the UI.**

---

## PROTOCOL-DOCUMENT IMPACT (money-path thread owns these edits)

**Section 3 — Ledger:** add canonical accounts + postings: `min_reserve:{team}` (weekly runway — MUST be distinct from `reserve:{team}`), `min:{team}:{week}`, `reserve:{team}` (Championship), `receivable:skunk:{team}:{season}`, `skunk:{league}:{season}`; weekly release; unspent-min sweep; skunk assessment + payout.

**Section 4 — BAB Economy:** BAB-101–109 for $0 wallet + four buckets; BAB-104/104a/210 for corrected non-double-counting Available to Bet; BAB-107/108 for separate Weekly-Min Reserve vs Championship Reserve; BAB-505–509 for off-wallet skunk liability + wallet payout; season-close ordering.

**Section 7 — League Config:** CFG-201 → five weekly rates (not fixed dollars); define Yahoo-derived regular-season-week field; adopt R1 integer-cent formula; Skunk Fee = separate locked setting; **replace ALL hardcoded weeks 1–14** (not just CFG-201); deterministic skunk tie (R3).

**Section 8 — Additional Protocols:** rewrite AP-141–148 as controlling skunk protocol — off-wallet liability, exact postings (R2), no wallet collection, tie handling (R3), wallet payout, postseason spendability, idempotency + audit.

**Spec 2:** Available to Bet = `ledger_balance(wallet) + ledger_balance(min:{team}:{current_week})`, not minus escrow. Name the weekly runway account as a Spec 5 dependency; Spec 2 consumes only released weekly min, never the runway directly.

---

## EXISTENCE-CHECK PROVENANCE
All greps 2026-07-20 vs `FDCHub/fantasy-beefs` working tree (PowerShell `Select-String` / `Get-ChildItem`). Economy: `economy_config.py`, `schema.py` — ×14 enforced, wallet funded. Skunk: recursive across `betting beefs ledger payments db` — two incidental hits (comment + unused column). Available-to-bet: absent, inline `ledger_cents − ch_reserved` at four sites. This package defines contracts to build, not behavior to document.
