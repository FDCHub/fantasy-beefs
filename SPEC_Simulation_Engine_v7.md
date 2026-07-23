# Simulation Engine MODULE_SPEC — Rev 7 (post-review MS-SIM-10 correction)

**File:** `simulation_engine.py` (formerly the planned `odds_engine.py`)
**Findings covered:** FR-8.1 (Dynamic live), FR-8.2 (asymmetric derivation), FR-8.3 (derived-stake floor), plus The Adjustment.
**Status:** Rev 7. Incorporates the post-review MS-SIM-10 correction — Final Lock uses a **durable claim-first, recoverable two-phase idempotency protocol**, replacing Rev 6's single-transaction-with-completion-marker framing. Opus Math Review rounds 1–3 otherwise stand (MS-SIM-1..14). Money-path. No code ships until Opus signs off.
**Grounded on:** the 2026-07-18 grep pass (code is truth) and the certified Odds Calculator Rev 1.9 JS (`Odds_Calc_Rev1_9.html`, READ-ONLY reference).

**Rev 7 change note (the MS-SIM-10 correction):**
- Rev 6 incorrectly treated the once-only marker as part of a **single completion transaction** and instructed the implementation to **mirror the current settlement guard**. The FR-8.7 grep proved the settlement guard is a **cautionary example, not a template**: it commits `settled=True` *before* the economic work, with no in-progress state and no recovery path, so a mid-work crash strands the week permanently.
- Rev 7 replaces that with a **durable claim-first, recoverable two-phase protocol**: a `CLAIMED/IN_PROGRESS` claim is committed *first and separately* (to exclude concurrent workers), then all economic work commits atomically in a second transaction that flips the claim to `COMPLETED`. Only `COMPLETED` may suppress future execution permanently.
- **The settlement completion-first pattern is explicitly NOT controlling.** All "mirror the settlement guard" and "completion marker commits first" language is removed.
- The Final-Lock escrow-equals-ceiling first-entry precondition (MS-SIM-12) is **preserved as a secondary backstop only** — the durable claim and completed-state check are the primary idempotency controls.

**Rev 6 changes retained (Opus Math Review round 3, MS-SIM-11..14 + two corrections):**
- **MS-SIM-11 (A):** the pot never grows, but under the canonical model this is enforced by the **ceiling cap, not the derivation** — when the issuer worsens, the derivation demands a larger opponent stake and the immutable ceiling caps it. §0 restated: the ceiling is the load-bearing no-increase guard. Assert final exposure and funded escrow never exceed the Handshake ceilings.
- **MS-SIM-12 (A):** the escrow==ceiling comparison is a **first-entry Final-Lock precondition**, not a timeless invariant. Passes on first legitimate entry before refunds; after a completed Adjustment it is no longer expected to hold; a duplicate run reaching it fails *by design* (a secondary backstop to the MS-SIM-10 primary controls). §2 invariant 3 relabeled.
- **MS-SIM-13 (A):** all "floor-both" terminology removed — only the opponent's Derived Stake floors; the anchor is whole cents and fixed. §3 rewritten around the single-floor adversarial line.
- **MS-SIM-14 (A):** §7 advanced — MS-SIM-1..10 marked resolved, round-3 targets set.
- **Correction:** deleted §2's stale "No Change 1¢ refund" paragraph — canonical derivation makes unchanged odds an exact fixed point with zero refund.
- **Correction:** §1 label "Floor-both rounding" → "Derived-stake floor rounding."

**The wager model (the spine — read this first):**
A Dynamic Challenge is **asymmetric**. The issuer commits a fixed amount — "I'm putting up $X" (the **Anchor Stake**). Dynamic pricing determines how much the **opponent** must risk against that fixed commitment, capped at the opponent's original Handshake ceiling. The opponent's stake is the **only** odds-derived stake. At Final Lock the engine re-derives the **opponent's** stake from final probabilities and caps it; the issuer's stake never moves on odds. **The issuer does not receive an odds-driven refund** when its probability worsens — the anchor is a fixed commitment, by design. An issuer refund occurs *only* if a separate true-up left the issuer's escrow above the accepted anchor (a funding-correctness event, never an odds event).

**Prior-round changes retained:**
- **MS-SIM-7 (frozen-pot REMOVED):** Final Lock uses canonical anchor derivation. Issuer refund structurally zero; only the opponent reprices.
- **MS-SIM-8 (Handshake-exit assertion):** independent-read check that true-up landed escrow and ceiling consistently.
- **MS-SIM-9 (named-account checks):** refunds verified by specific account; both-positive fixture N/A (unreachable).
- **MS-SIM-10 (durable claim-first two-phase idempotency):** a `CLAIMED/IN_PROGRESS` claim commits first and separately to exclude concurrent workers; the economic work (simulation, Adjustment, refunds, frozen terms, Pending transition, audit record, flip to `COMPLETED`) commits atomically second. Only `COMPLETED` suppresses future execution; a claimed-but-incomplete event is recoverable. Does NOT mirror the settlement guard (see FR-8.7).
- **MS-SIM-4 (floor ruling), MS-SIM-2 (posting-level self-check), MS-SIM-6 (window-closure grep).**
- Money moves at the Dynamic Handshake; `residue_cents` removed; model freezes at Handshake, reused at Final Lock.

---

## 0 — The ruling this spec is built on (challenge mode is the switch)

The accept-to-kickoff window behaves differently by challenge mode. This is the load-bearing decision; every section below inherits it.

- **Locked Challenge** — a handshake is a handshake. At acceptance, the line, odds, both stakes, payout, and covered entities freeze. A later scratch or lineup change does **not** reprice. Settlement reads the terms frozen at acceptance.
- **Dynamic Challenge** — at the Handshake, three things freeze: the model version, each side's **maximum exposure**, and the **escrow ceiling** (the pot). The final odds do **not** freeze. Between Handshake and Final Lock, informational refreshes are nonbinding — they move no money. At **Final Lock**, the engine runs **exactly one** official simulation on the final lineup, applies The Adjustment once, and may **preserve or reduce** each side's exposure but **never increase** it. Settlement reads the terms frozen at Final Lock.

Consequences that bound the whole build:
- **No continuous ledger-changing repricing.** The Adjustment posts money exactly once per Dynamic challenge, at Final Lock.
- **No settlement-time repricing.** Settlement is a pure read of frozen terms.
- The Handshake sets a **per-side** exposure ceiling. Each side's ceiling is a hard cap; their sum is the maximum funded pot. **The pot never grows — but under the canonical anchor model this is enforced by the ceiling cap, not by the derivation.** When the issuer's odds worsen, the Final-Lock derivation mathematically *demands a larger* opponent stake (`floor(anchor/p_iss_final × p_opp_final)` can exceed the opponent's Handshake ceiling); the immutable opponent ceiling caps it back down. The ceiling is therefore the **load-bearing no-increase guard**, not merely an exposure limit — remove or "optimize away" the cap check and the pot grows, charging a GM above their commitment. Per-side final exposure and final funded escrow must never exceed the Handshake ceilings.

---

## 1 — What already exists (from the grep pass — do not rebuild)

The Monte Carlo core is **already built** in `odds/odds_engine_headless.py`. The port is **not** from zero. Confirmed function surface:

- `run(...)` — top-level simulation entry.
- `simulate_scores(...)`, `simulate_player_scores(...)` — score distributions.
- `_simulate_team(pts, rng)` — draws Normal(proj, σ) per starter, sums, returns `(N_SIMS,)` array.
- `_prob_to_american(prob)` — probability → American odds.
- `_adjust_for_scoring(...)`, `_build_starter_lines(...)`, `N_SIMS`, `PlayerProj`.

The accept path in `beefs/beef_engine.py` **already recomputes odds at acceptance** (`respond_to_challenge`, ~line 919) via `_compute_odds_from_inputs`, overwriting preview odds. This is the lock-at-accept behavior. **Confirmed: no repricing trigger, no drift, no refresh machinery exists yet.** That is the greenfield part.

**So the real remaining work is four layers on top of a working simulator:**
1. Port the stake/pot math (asymmetric derivation) — pure functions, from the certified JS.
2. Derived-stake floor rounding (FR-8.3).
3. The Adjustment (Dynamic Final-Lock reprice + refund).
4. The genuinely new machinery: Final-Lock trigger + model-freeze + nonbinding informational refresh.

---

## 2 — Reference math to port (certified JS, Rev 1.9)

These are certified and READ-ONLY. Port their behavior exactly; do not re-derive.

**Odds ↔ probability (pure, port as-is):**
```
o2p(odds, isNeg):  isNeg ? odds/(odds+100) : 100/(odds+100)
p2o(p):            |p-0.5|<0.0001 → +100 (even)
                   p>0.5 → round(p/(1-p)*100), negative
                   else  → round((1-p)/p*100), positive
```

**Asymmetric stake derivation (FR-8.2) — the pricing law:**
```
fairPot        = anchor / p_issuer          # issuer enters Anchor Stake (whole BAB cents)
issuer_stake   = anchor                      # NOT re-floored — already whole cents
opponent_stake = floor(fairPot × p_opponent) # only the derived side floors (FR-8.3)
```
The favorite risks more. There is no "size me at" toggle. Decline is the opponent's protection.

**The Adjustment (Dynamic only, once at Final Lock) — canonical anchor derivation:**

The Adjustment re-runs the **asymmetric derivation** on the final-lineup probabilities. It does **not** reallocate a pot. The issuer's Anchor Stake is fixed; only the opponent's Derived Stake reprices, capped at its Handshake ceiling. Refunds come from actual escrow balances.

```
# inputs frozen at Handshake: anchor, issuer_ceiling, opponent_ceiling,
# and the two live escrow balances.

fairPotFinal    = anchor / p_issuer_final
issuerFinal     = anchor                                  # fixed; = min(anchor, issuer_ceiling)
opponentDerived = floor(fairPotFinal × p_opponent_final)  # only the derived side floors (FR-8.3)
opponentFinal   = min(opponentDerived, opponent_ceiling)  # capped at Handshake ceiling

refund_issuer   = issuer_escrow_balance   - issuerFinal   # 0 under normal repricing
refund_opponent = opponent_escrow_balance - opponentFinal
final_funded_escrow = issuerFinal + opponentFinal
```

The issuer commits a fixed amount; Dynamic pricing determines how much the opponent must risk against it, subject to the opponent's original ceiling. `refund_issuer` is **structurally zero** under normal Final-Lock repricing because the anchor never moves on odds. An issuer refund occurs **only** if the issuer's escrow exceeds the accepted anchor because of a separate true-up or correction — a funding-correctness event, never an odds event. Dynamic Final Lock ordinarily refunds only the **Derived (opponent) side**.

The opponent's stake behaves as follows: if the issuer's win-probability **improves**, the opponent's fair stake shrinks below its ceiling → opponent refunded. If the issuer's win-probability **worsens**, the opponent's fair stake would rise above its ceiling → capped, no change, no refund either side. The issuer, having committed the anchor, carries that fixed exposure regardless.

**Invariant guards (fail loud, post nothing on failure — integer cents, exact):**

The Rev 3 invariant "refunds == pot drop" was a **tautology** (MS-SIM-2): `(iss_esc − iss_final) + (opp_esc − opp_final)` and `(iss_esc + opp_esc) − (iss_final + opp_final)` are the same subtraction, so the check could never fail and proved nothing. Replaced with **posting-level double-entry checks** — the load-bearing law the ledger's own `post()` guard enforces:

```
1.  probabilities sum to 1 at final lineup:
    round(p_issuer_final + p_opponent_final, 6) == 1

2.  HANDSHAKE-EXIT assertion (MS-SIM-8) — escrow and recorded ceiling agree,
    read INDEPENDENTLY (ledger balance vs challenge-row ceiling):
    assert escrow_balance(issuer)   == recorded_ceiling(issuer)
    assert escrow_balance(opponent) == recorded_ceiling(opponent)
    # a true-up that writes escrow and ceiling inconsistently fails HERE, at
    # Handshake exit — not silently at Final Lock.

3.  FINAL-LOCK first-entry PRECONDITION (MS-SIM-6, MS-SIM-12) — NOT a timeless
    invariant. Must pass on the first legitimate execution, BEFORE refunds post:
    assert escrow_balance(issuer)   == recorded_ceiling(issuer)
    assert escrow_balance(opponent) == recorded_ceiling(opponent)
    # Holds on first entry (nothing touched escrow in the window). After a
    # completed Adjustment it is NO LONGER expected to hold — the refund dropped
    # escrow below ceiling. This precondition is a SECONDARY backstop only — the
    # primary idempotency controls are the durable claim + COMPLETED-state check
    # (MS-SIM-10). If a duplicate somehow bypasses those and reaches here on
    # already-refunded escrow, its FAILURE is the intended backstop, not a spec violation. A test author must NOT assert this "always passes":
    # it is a precondition that fires on first entry and is DESIGNED to fail on
    # an illegitimate re-entry.

4.  exposure never grows — both refunds non-negative:
    refund_issuer   = escrow_balance(issuer)   - issuerFinal   >= 0
    refund_opponent = escrow_balance(opponent) - opponentFinal >= 0

5.  each refund posted as a balanced escrow->wallet PAIR summing to zero, by
    NAMED account (MS-SIM-9a):
    post([("escrow:issuer",   -refund_issuer),   ("wallet:issuer",   refund_issuer)])
    post([("escrow:opponent", -refund_opponent), ("wallet:opponent", refund_opponent)])
    # assert wallet:issuer rose by exactly refund_issuer BY NAME (not "a wallet rose")

6.  after refunds: escrow holds exactly each side's final stake, trial balance 0:
    escrow_balance(issuer)   == issuerFinal
    escrow_balance(opponent) == opponentFinal
    trial_balance() == 0
```

Checks read **live integer escrow balances** and post **real ledger pairs by named account**. No float tolerance; integer cents, exact. (The JS `0.005` tolerance is a float artifact, deliberately not ported.)

**On the sub-cent residue (MS-SIM-3/5):** `fairPotFinal × p_opponent_final` before flooring may carry a fraction of a cent. Per the MS-SIM-4 ruling, that fraction is **never funded** — never escrowed, never posted, never refunded, never was BAB. It is not "stranded" or "destroyed"; it never existed as money. No conservation proof required: nothing leaves escrow that did not enter it. See §3.

**Under the canonical anchor model there is no "No Change" refund artifact.** When probabilities are unchanged from Handshake, the Final-Lock derivation repeats the Handshake calculation exactly: issuer_final is the raw anchor (no floor), opponent re-derives to precisely its ceiling. Zero refund, both sides. (The 1¢ artifact belonged to the removed frozen-pot model, where a double-floor made "No Change" not a fixed point. Canonical derivation makes it an exact fixed point.)

---

## 3 — FR-8.3: Derived-stake floor rounding (OPUS-GATED)

Only **one** side ever floors: the opponent's Derived Stake. The issuer's Anchor Stake is already whole BAB cents and fixed — never floored, at Handshake or Final Lock. ("Floor-both" was frozen-pot language, where both allocations floored; that model is removed. There is no floor-both.)

The sub-cent residue (`fairPot × p_opponent` minus its floor) is **never funded** — never escrowed, never posted, never refunded, never was BAB (MS-SIM-4). Naming: there is **no `residue_cents` field** — an integer-cent name implies a postable cent, and this residue never posts. Where audit math needs the value, expose it as `residue_decimal` (diagnostic only). Otherwise verify the funded pot directly: `funded_pot_cents = issuer_cents + opponent_cents`.

**Open adversarial question for Opus (the single-floor line, not floor-both):** does the opponent-side floor, re-run at Final Lock on new odds, ever produce a stake that fails to reconcile against its escrow balance by named account? Adversarial cases to bring:
- **Extreme favorite, near-zero derived stake:** p_iss = 0.95 → opponent Handshake stake `floor(6097 × 0.05) = 304`; then Final Lock improves to p_iss = 0.98 → `opponentDerived = floor(5000/0.98 × 0.02) = floor(102.04) = 102`, refund 202. Reconciles by named account?
- **Above-ceiling derivation:** issuer worsens so `floor(fairPotFinal × p_opp_final)` exceeds the opponent ceiling → cap applies, no refund; confirm no pot growth.
- **Exact-ceiling derivation:** a line where the derived stake lands exactly on the ceiling — no refund, no cap needed; confirm the boundary.
- **Non-dividing residue:** anchor/probability combos where `fairPot` carries a fraction; confirm the residue is never funded and never appears in any posting.

---

## 4 — Module surface (proposed)

Pure functions first; the engine stays free of DOM/DB coupling (the JS was braided into `getElementById`/`alert`/`innerHTML` — that all gets stripped).

```
# conversions (ported pure)
o2p(odds: int, is_neg: bool) -> float
p2o(p: float) -> tuple[int, bool]            # (val, is_neg)

# pricing (FR-8.2, integer cents) — anchor is whole cents, only derived side floors
derive_stakes(anchor_cents: int, p_issuer: float, p_opponent: float)
    -> StakePair(issuer_cents, opponent_cents, funded_pot_cents)
    # issuer_cents == anchor_cents (not re-floored)
    # opponent_cents == floor(fairPot * p_opponent) (FR-8.3)
    # funded_pot_cents == issuer_cents + opponent_cents
    # NO residue_cents field. residue is sub-cent, never posts. If audit needs it,
    # a separate residue_decimal is diagnostic-only.

# adjustment (Dynamic only, once at Final Lock) — canonical anchor derivation.
# Reprices ONLY the opponent (derived) side. Issuer stake = anchor, fixed.
adjust_escrow(
    anchor_cents: int,                           # issuer's fixed commitment
    p_issuer_final: float, p_opponent_final: float,
    issuer_ceiling_cents: int, opponent_ceiling_cents: int,
    issuer_escrow_balance_cents: int, opponent_escrow_balance_cents: int,
) -> AdjustmentResult(
        issuer_final_cents, opponent_final_cents,
        refund_issuer_cents, refund_opponent_cents,
        final_funded_escrow_cents,
    )
    # issuer_final = min(anchor, issuer_ceiling) == anchor normally.
    # opponent_final = min(floor(anchor/p_iss_final * p_opp_final), opponent_ceiling).
    # refund_issuer structurally 0 (anchor fixed); refund_opponent >= 0.
    # ONLY the opponent side reprices on odds. raises on invariant failure:
    #   probs sum to 1; handshake-exit + window-closure assertions;
    #   both refunds non-negative; postings balance by named account.
```

Signatures are proposals — confirm against the headless engine's existing types (`PlayerProj`, `N_SIMS`) so the sim core and this pricing layer share models rather than duplicating them. Note `adjust_escrow` takes the **anchor** and the two ceilings and the two live escrow balances. It reprices only the opponent's derived side; the issuer stake is the anchor, fixed.

---

## 5 — The new machinery (Dynamic only — greenfield, confirmed absent)

Smaller than the opener's framing, because the challenge-mode ruling bounds it:

- **Handshake — funds both sides, freezes the model.** The Handshake atomically establishes and **fully funds** each side's maximum exposure: the issuer's issue-time escrow is trued up to the accepted amount, the recipient's Derived Stake moves into escrow, both maximum losses are fully funded, and the simulation **model version** + per-side exposure ceilings freeze on the challenge row. **Money moves here** — this is not a bookkeeping-only step. (This matches the escrow-at-issue ruling: the issuer already escrowed at issue, so Handshake is a true-up on the issuer side plus a fresh escrow on the recipient side, atomic.) **On Handshake exit (MS-SIM-8):** assert `escrow_balance(side) == recorded_ceiling(side)` for both sides, reading the escrow from the **ledger** and the ceiling from the **challenge row** — two independent reads. This catches a true-up that lands escrow and ceiling on different floored numbers *here*, at the source, rather than letting the inconsistency ride invisibly to Final Lock. The counter-true-up (memory-flagged as "new code, not yet designed") is the writer that sets both values; this assertion is how we prove it set them consistently.
- **Informational refresh (nonbinding).** Between Handshake and Final Lock, a display-only re-sim may show GMs where the line sits. Writes nothing to the ledger. **Only these refreshes move no money.**
- **Final-Lock trigger — reprice once, under the two-phase protocol below, using the model frozen at Handshake.** A single scheduled event, fired at the challenge's earliest covered kickoff (`_nfl_lock_time` / per-challenge kickoff already computed in `beef_engine`). The economic work (Phase 2) proceeds only after the durable claim (Phase 1) is committed. On execution: **assert the escrow balances still equal the Handshake ceilings** (MS-SIM-6 closure check — proves nothing touched escrow in the window), then run **one** official simulation on the final lineup **under the Handshake-frozen model version** → `adjust_escrow` (canonical anchor derivation, opponent side only) → post refunds as balanced escrow→wallet pairs by named account → freeze final terms. The model is **not** frozen at Final Lock — it was frozen at Handshake and is **reused** here.

  **Durable two-phase idempotency (MS-SIM-10) — claim-first, recoverable:**

  **Phase 1 — durable claim.** Atomically create or acquire a unique Final-Lock execution claim keyed on the challenge ID + Final-Lock event key. The claim represents `CLAIMED` or `IN_PROGRESS` — **never** `COMPLETED`, `DONE`, or any final-success state. Commit this claim **separately, before** any official simulation or BAB movement. Its sole purpose is to exclude concurrent workers.

  **Phase 2 — atomic economic work.** In one database transaction, perform and commit together:
  1. Revalidate the claim is still valid and not already completed.
  2. Run or persist the official Final-Lock simulation result.
  3. Execute the canonical Anchor/Derived Adjustment (opponent side only).
  4. Post all escrow→wallet refunds through balanced Ledger entries (by named account).
  5. Freeze the official Final-Lock probabilities, odds, stakes, payout, covered entities, and settlement terms.
  6. Transition the challenge to `Pending`.
  7. Create the immutable audit record.
  8. Flip the Final-Lock claim from `CLAIMED/IN_PROGRESS` to `COMPLETED`.
  9. Persist the completed result reference needed for idempotent retries.

  These commit together. A Phase 2 failure rolls back **all** Phase 2 writes while leaving the Phase 1 durable claim available for recovery.

  **Retry / recovery behavior:**
  - **No claim exists** → create the claim and execute.
  - **`COMPLETED`** → return the original committed result without rerunning simulation, Adjustment math, or Ledger postings.
  - **`CLAIMED/IN_PROGRESS`** → do NOT silently return success and do NOT create a second execution; resume or reclaim under a deterministic stale-claim recovery policy.
  - A crash **after Phase 1 but before Phase 2 completes** leaves the event recoverable.
  - A crash **during Phase 2** rolls back all Phase 2 economic and state writes.
  - Only `COMPLETED` may suppress future execution permanently.

  **This does NOT mirror the current settlement guard.** Settlement (`settle_week`) commits `settled=True` *before* the economic work with no in-progress state and no recovery path — the exact crash-recovery gap tracked as FR-8.7 (launch-blocking). That completion-first pattern is a **cautionary example, not a template**, and must not be copied here.

  **Backstop (secondary only):** the Final-Lock escrow-equals-ceiling first-entry precondition (MS-SIM-12) remains as secondary protection — if a duplicate somehow bypasses the claim controls and reaches the precondition on already-refunded escrow, it fails loud and posts nothing. But the **durable claim and the `COMPLETED`-state check are the primary idempotency controls**; the precondition is a backstop, not the mechanism.

  *MS-SIM-6 note:* the grep proved the Handshake→Final-Lock window is closed in current code (no cancel/void/reverse paths exist; Tuesday-sync touches rosters/scores/players not escrow; shortfall sweep posts to `wallet:` at settlement, not `escrow:` mid-window). The Final-Lock repricing this spec adds is itself a new escrow writer, but it fires **at** the boundary, not mid-window. The closure assertion guards against any future change that opens the window — turning Opus's "stranded bet" failure into a caught, named error.

**No always-on repricing loop. No settlement-time work.** The machinery is: fund-and-freeze at Handshake, optionally show, reprice-once at Final Lock, done.

---

## 6 — Locked vs Dynamic: where the branch lives

| Stage | Locked | Dynamic |
|---|---|---|
| At acceptance / Handshake | Freeze line, odds, stakes, payout, entities (both stakes already escrowed) | **Fully fund both sides' max exposure** (issuer true-up + recipient fresh escrow), then freeze model version + per-side ceilings |
| Between accept and kickoff | Nothing — inert | Nonbinding informational refresh (no money) |
| At Final Lock | N/A (already frozen) | One official sim → Adjustment → refund → freeze |
| At settlement | Read frozen-at-acceptance terms | Read frozen-at-Final-Lock terms |

The engine functions in §4 are mode-agnostic — they compute stakes and adjustments. The **caller** (challenge lifecycle in `beef_engine`) decides whether to call `adjust_escrow` at all: Locked never does; Dynamic does exactly once.

---

## 7 — What Opus reviews (money-path findings, each approved individually)

Rounds 1–2 complete (MS-SIM-1..10, all resolved/ruled above). This is Rev 6, for **round 3**, issues only, no fixes, table format (Name / Issue Summary / Options / Recommendation & Reasoning). Round 3 targets what the canonical-model reversal (MS-SIM-7) changed downstream:

1. **The canonical-model reversal (MS-SIM-7) itself** — issuer stake fixed at anchor, only opponent reprices, issuer refund structurally zero. Re-derive all four branches fresh; confirm the reversal is sound and the self-check reconciles by hand.
2. **The ceiling as conservation guard (MS-SIM-11)** — under canonical derivation the pot never grows *only because the ceiling caps it*; the derivation alone would grow the opponent stake when the favorite worsens. Confirm §0's restated invariant is correct and that final exposure/funded escrow never exceed the Handshake ceilings.
3. **The two-assertion split (MS-SIM-8 vs MS-SIM-6/12)** — handshake-exit assertion (true-up correctness, at Handshake) vs Final-Lock first-entry precondition (window closure, designed to fail on illegitimate re-entry). Confirm the two are correctly distinguished and that invariant 3 is a precondition, not a timeless invariant.
4. **The single-floor adversarial line (MS-SIM-13)** — only the opponent's derived stake floors. Bring the sharp cases: extreme favorite with near-zero derived stake (p_iss=0.95→0.98), above-ceiling derivation, exact-ceiling derivation, non-dividing residue. Confirm each reconciles by named account and none grows the pot.
5. **Idempotency (MS-SIM-10)** — confirm the durable **claim-first two-phase** protocol: a `CLAIMED/IN_PROGRESS` claim committed first and separately; then simulation + Adjustment + refunds + frozen terms + Pending transition + audit record + flip to `COMPLETED` committed atomically in a second transaction. Confirm retry behavior (no claim → execute; `COMPLETED` → return original; `CLAIMED/IN_PROGRESS` → resume under recovery policy, never double-execute). Confirm it does NOT copy the settlement completion-first guard (FR-8.7). Confirm the escrow==ceiling precondition is treated as a secondary backstop only.

---

## 8 — Self-check before this goes to Opus (per the standing rule)

The self-check models a **real double-entry ledger** with canonical anchor Adjustment, plus the MS-SIM-8 handshake-exit assertion, MS-SIM-9(a) named-account checks, and the MS-SIM-10 durable claim-first idempotency (a duplicate trigger returns the original `COMPLETED` result without re-executing; a claimed-but-incomplete event is recoverable). Every escrow movement is a debit/credit pair; the ledger rejects any pair that doesn't sum to zero; trial balance is asserted zero throughout.

**Line used:** anchor $50.00 (5000¢), issuer favorite at p=0.82. `fairPot` = 6097.56¢ (non-dividing, exposes floor residue). Handshake: issuer 5000¢ (unfloored anchor), opponent `floor(6097.56 × 0.18) = 1097¢`, residue 0.56¢ (never funded).

| Branch | p_iss final | issuer_final | opp_final | refund_iss | refund_opp | HS-exit | double-fire | named-acct | TB |
|---|---|---|---|---|---|---|---|---|---|
| No Change | 0.82 | 5000 | 1097 | 0 | 0 | ✓ | orig, no repost | ✓ | 0 |
| Favorite worse | 0.70 | 5000 | 1097 | 0 | 0 | ✓ | orig, no repost | ✓ | 0 |
| Favorite better | 0.90 | 5000 | 609 | 0 | 488 | ✓ | orig, no repost | ✓ | 0 |
| Roles reversed | 0.35 | 5000 | 1097 | 0 | 0 | ✓ | orig, no repost | ✓ | 0 |

Confirmed programmatically, every branch:
- **Issuer refund is always 0** — the anchor is fixed; the issuer never reprices on odds. This is the canonical asymmetric design (MS-SIM-7), not a bug.
- Only the **opponent** refunds, and only when the issuer's odds **improve** (favorite-better: opponent's fair stake shrinks to 609¢, refund 488¢). When the issuer's odds worsen, the opponent's fair stake would rise above its ceiling → capped → no refund either side.
- Handshake-exit assertion holds (escrow == ceiling, independent reads).
- Double-fire returns the original `COMPLETED` result, posts nothing new (durable claim + completed-state check).
- Refunds verified by **named account**: `wallet:OPP` rose by exactly `refund_opponent`, `wallet:ISS` by exactly `refund_issuer`.
- Escrow holds each side's final stake; trial balance 0 after Handshake and after Adjustment.

**MS-SIM-9(b) — both-positive fixture is N/A.** Under the canonical model, issuer refund is structurally 0, so a both-positive refund is **mathematically unreachable**. Confirmed by exhaustive sweep of p_iss ∈ [0.05, 0.95]: no line produces two positive refunds. No fixture added; documenting unreachability is the correct response to the ruling's conditional.

**One documented artifact (MS-SIM-5):** with the canonical anchor model, the "No Change" 1¢ artifact from Rev 4 **disappears** — issuer_final is exactly the anchor (5000, no floor), and the opponent at unchanged odds re-derives to exactly its ceiling (1097). No spurious 1¢ refund. The canonical model is cleaner here than frozen-pot was.

**Self-check status: PERFORMED at posting level, PASS.** Ready for Opus round 3.

---

## 9 — Open items flagged during the grep pass (not part of this spec, carried to session close)

- **FR — MIN_BET $5→$1.** Live constant `wallet_manager.py:26` is `5.00`; ruling is `1.00` (universal, playoffs included). Fix is constant + docstring + **re-fixture `test_stake_precision_validation.py`** (swap $4.99 for a sub-$1 value — $4.99 stops being below-floor at $1) + fix the comment in `test_ledger_bet_conversion.py`. Money-path.
- **FR-5.7 writer absent.** `roster_slots` table exists in production but is **empty**. Migration ran; the weekly-capture **writer** does not exist. Settlement runs on the static-Roster fallback. Needs a launch ruling: is the fallback acceptable for Aug 1, or does the writer ship first?
- **deposit() not ledger-integrated.** `wallet_manager.py:141` mutates the float column, writes a Transaction row, never calls the ledger. Money-path.
