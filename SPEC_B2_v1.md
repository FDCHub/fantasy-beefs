# B2 — Stripe Decouple + Shortfall Sweep MODULE_SPEC

**Status:** DRAFT — Section 4 (buyin_enforcement_active) and Section 6 (shortfall
sweep) await Opus Math Review. Section 5 (5.4 retirement) is pre-cleared —
verified redundant against an already-certified guard, no new money logic.
No code ships against Section 4 or Section 6 until certified.
**Gate lines closed:** none yet — B1 closed Finding 5.1; this spec closes 5.3,
5.4, and the original B2 shortfall-sweep scope.
**Source of truth:** `FantasyBeefs_Launch_Gate_Audit_Findings_Register_v5.md`,
Findings 5.2 (out of scope here — its own spec), 5.3, 5.4. This document
formalizes both findings' recon (this thread) into buildable steps, plus the
shortfall sweep B2 was originally scoped for.

---

## 1. Recap — how this spec came to be shaped this way

B2 opened as one task: shortfall-sweep-to-championship. Recon-first (same
discipline as B1) found two real prerequisites hiding under Finding 2.7's old
description — 2.7 said "the buy-in gate is the sole betting gate, decouple
from Stripe," which was true as far as it went, but never examined the gate's
own activation condition (5.3) or noticed a second, entirely separate gate
chained onto it (5.4). Both are fixed here, ahead of the sweep, because
building the sweep on top of two gates that either silently disable
themselves or block betting for reasons unrelated to BAB would be building on
a bad foundation.

---

## 2. Live-code findings, as verified this thread

**`get_buyin_gate()`** (`payments/stripe_connect.py:782`) goes inactive —
lets betting proceed with no buy-in check at all — whenever
`LeagueTreasury.buy_in_amount_cents == 0` or no treasury row exists. B1
stopped writing to `LeagueTreasury`; nothing keeps this current.

**`get_league_economy_stop()`** (`payments/economy_config.py:121`) cannot
replace it. That function is built to *never* signal "off" — an unconfigured
league falls through to `DEFAULT_STOP` by design, so a real charge never
computes against missing config. Correct for its own job; structurally wrong
for answering "should the gate be active."

**`get_bet_funded()`** (`wallet/faab_wallet.py:811`) is gated onto all six
live betting/challenge endpoints (`place_bet`, `bet_straight`, `bet_spread`,
`bet_over_under`, `bet_prop`, `beef_challenge`) and checks
`FaabWallet.balance <= 0` — a defunct FAAB wallet model, unrelated to the BAB
ledger. `init_season_wallets()` (`wallet/faab_wallet.py:286`, called from
`api/main.py:1840`) still seeds `FaabWallet` rows every season. This is a
live gate, not dead code — confirmed by tracing all six endpoints down to
their engine calls:

| Endpoint | Engine call | Ledger-routed? |
|---|---|---|
| `place_bet` (`/bets/place`) | `place_straight_bet()` → `_place_bet()` | Yes — `ledger.post()` |
| `bet_straight` (`/bets/straight`) | `place_straight_bet()` → `_place_bet()` | Yes |
| `bet_spread` (`/bets/spread`) | `place_spread_bet()` → `_place_bet()` | Yes |
| `bet_over_under` (`/bets/over_under`) | `place_over_under()` → `_place_bet()` | Yes |
| `bet_prop` (`/bets/prop`) | `place_prop_bet()` → `_place_bet()` | Yes |
| `beef_challenge` (`/beef/challenge`) | `issue_challenge()` → `_place_beef_side()` | Yes — converted in L3, Opus-certified |

All six resolve to `ledger.post()`, which already enforces a funded-balance
guard on every posting (MS-L1-5.1, certified in L1). `betting/pool_engine.py`
and `betting/settlement_engine.py` still write `wallet.balance` directly and
are **not** ledger-routed — but none of the six `get_bet_funded()`-gated
endpoints call into either file. That direct-write pattern is real and stays
on the roadmap as its own recon-then-convert task (L3's last unresolved
site), untouched by this spec.

---

## 3. Ruled this thread

- **5.3:** Option C — a dedicated `League.buyin_enforcement_active` boolean,
  set explicitly by the commissioner, independent of any row's existence.
  (Option A, swapping in `get_league_economy_stop()`, was rejected — see
  Section 2. Option B, inferring activation from `BuyInRecord` existence, was
  superseded by C at Fraser's call.)
- **5.4:** Option A — retire `get_bet_funded()` outright from all six
  endpoints, fall back to `get_buyin_gate()` alone, rely on the ledger's own
  certified guard to reject an underfunded bet at the actual debit.

---

## 4. Build steps — Finding 5.3 (Opus-gated)

1. **Migration:** add `League.buyin_enforcement_active`, `Boolean`,
   `nullable=False`.
   - **Open question, flagged for Opus, not decided here:** default value.
     Every league in production today has no enforcement running. A default
     of `True` locks betting for every existing league the instant this
     migration deploys. A default of `False` leaves betting open,
     unenforced, until a commissioner explicitly flips it — closer to
     today's real-world state, but means no enforcement runs until someone
     remembers to turn it on. This is a real product-and-money-timing
     decision, same class as B1's TOCTOU finding — Opus rules it, Fraser
     confirms.
2. **Commissioner-facing control:** new endpoint (or an addition to an
   existing commissioner-settings endpoint) to read and flip the flag.
   Commissioner-only, same auth pattern as other commissioner actions
   (`assert_own_team`-style ownership check, adapted for league-level
   control).
3. **`get_buyin_gate()` rewritten:**
   ```
   if not league.buyin_enforcement_active:
       return current_user   # enforcement off — gate inactive by explicit choice
   # existing buy_in_paid check runs only if enforcement is on
   ```
   Replaces the current `LeagueTreasury.buy_in_amount_cents == 0` check
   entirely. The existing `buy_in_paid`-flag logic underneath is untouched —
   only the activation condition changes.
4. **Test coverage:** enforcement off → gate inactive regardless of
   `buy_in_paid`. Enforcement on + unpaid → HTTP 402 (existing behavior).
   Enforcement on + paid → passes through (existing behavior). Flag toggled
   mid-season → takes effect on the next request, no stale state.

---

## 5. Build steps — Finding 5.4 (pre-cleared, no Opus round)

1. Remove `Depends(get_bet_funded)` from all six endpoints listed in Section
   2's table; replace with `Depends(get_buyin_gate)` directly (same
   dependency `get_bet_funded()` itself chained onto internally, so no
   endpoint loses the buy-in check — only the FAAB-freeze layer disappears).
2. Leave `wallet/faab_wallet.py` itself untouched beyond this — `_get_faab_wallet()`,
   `setup_faab_config()`, `FaabConfig`, `init_season_wallets()`,
   `create_bet_topup()`, `create_waiver_topup()`, `transfer()` all remain live
   FAAB-mirror functions, out of scope for this finding. A broader "what to do
   with the rest of the FAAB module" question stays unscoped, noted on the
   roadmap.
3. **Cleanup note, not a fix:** `notifications/tuesday_sync.py:611-622` calls
   `check_and_freeze()` on its own schedule, independent of any endpoint.
   Once `get_bet_funded()` is gone, nothing reads the `is_frozen` flag that
   job computes — it keeps running, writing a value nobody consults. Not
   dangerous, just orphaned work. Low priority; safe to leave for a future
   FAAB-module cleanup pass rather than block this spec on it.
4. **Test coverage:** all six endpoints still enforce `get_buyin_gate()`
   (unpaid GM still blocked). A GM with `FaabWallet.balance <= 0` (or no
   `FaabWallet` row at all) can now place a bet, provided their BAB wallet
   (`wallet:{team_id}`) is actually funded — and an underfunded BAB wallet is
   still correctly rejected, by the ledger's guard, not by this gate.

---

## 6. Build steps — original B2 scope: shortfall sweep (Opus-gated)

**Shortfall-sweep-to-championship**, as a paired posting:
```
debit  wallet:{team}       $shortfall_amount
credit championship        $shortfall_amount
```
Dry-wallet guarded — the posting must not fire, or must fire for a smaller
amount, if it would take `wallet:{team}` negative. Exact guard mechanics,
trigger timing (weekly wrap vs. some other cadence), and how "shortfall" is
computed are the open design surface for the MODULE_SPEC's next draft —
**not yet fully specified in this document.** Fraser to confirm the trigger
definition before this section is written to full posting detail and sent to
Opus.

**Also required, same session:**
- Weekly-wrap sweep explanation — a plain-language summary shown to GMs of
  what swept and why, alongside the existing weekly wrap.
- My Account: Skunk pot summary and Championship pot summary, shown
  separately (per the existing design rule that skunk and championship have
  different transparency surfaces).

---

## 7. Exit criteria

- **5.3:** ✅ when `League.buyin_enforcement_active` exists, migration
  deployed, commissioner control live, `get_buyin_gate()` reads the new flag,
  Opus-certified on the default-value decision, test coverage passing.
- **5.4:** ✅ when all six endpoints route through `get_buyin_gate()` alone,
  `get_bet_funded()` no longer wired anywhere, test coverage passing. No
  Opus round required — already satisfied by this spec's recon.
- **Shortfall sweep:** ✅ when the paired posting is Opus-certified, built,
  dry-wallet-guarded, wired to weekly wrap, and the two My Account summaries
  are live.

---

## 8. Open questions carried to Opus

1. **5.3's default value** for `buyin_enforcement_active` — `True` or
   `False` on migration. See Section 4, Step 1.
2. **Shortfall-sweep trigger definition** — what counts as a "shortfall,"
   and on what cadence it sweeps. See Section 6. Needs Fraser's ruling before
   this section can be written to postable detail.
