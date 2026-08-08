# Simulation Engine MODULE_SPEC — Rev 9 (Opus Round 3 documentary corrections)

**File:** `simulation_engine.py` (formerly the planned `odds_engine.py`)
**Findings covered:** FR-8.1 (Dynamic live), FR-8.2 (asymmetric derivation), FR-8.3 (derived-stake floor), plus The Adjustment.
**Status:** Rev 9. **Not a new architecture revision.** It incorporates the two documentary corrections required by Opus Math Review Round 3's `REJECT — CORRECTION REQUIRED` verdict on Rev 8, and records Round 3's non-blocking notes as carry-forward. Every substantive architecture and math finding Opus confirmed is preserved unchanged. Money-path. **No P3-D2 code ships until Opus confirms these corrections.**
**Grounded on:** the 2026-07-18 grep pass (code is truth), the certified Odds Calculator Rev 1.9 JS (`Odds_Calc_Rev1_9.html`, READ-ONLY reference), and the committed P3-D1 implementation (`odds/dynamic_pricing.py`, commit `79a81cf54de94a07167ca13ad93e5276c9867d0d`) as executable confirmation of the ruled formula.

---

## Rev 9 change note — what changed and why

Opus Round 3 confirmed Rev 8's arithmetic, the canonical anchor derivation, ESCROW-A, FINALSTATE-A, the claim protocol and the recovery policy. It rejected on **one point**, and the rejection is correct.

### The error Rev 8 made

Rev 8 established a true fact about the pure `adjust_escrow` function — that it can produce two positive refunds when issuer escrow exceeds the Anchor — and then **weakened a production invariant to accommodate it.** Specifically it added an issuer-side `>=` allowance to the Final-Lock first-entry precondition, with the phrase "where the deployment permits such an overshoot."

That was an over-generalisation from a mathematical possibility to a permitted transaction state, and Opus's reasoning for rejecting it is sound and closes the question:

- **Handshake exit requires exact equality** between issuer escrow and the recorded issuer ceiling (MS-SIM-8).
- **The Handshake→Final-Lock window is closed** — the MS-SIM-6 grep proved no path writes escrow in that window.
- **No authorized post-Handshake writer increases issuer escrow.**

Therefore an issuer escrow above the recorded ceiling at Final Lock is not a fundable overshoot. It is **an invariant violation with no legitimate cause**, and refunding it as a normal success path would launder an unexplained balance into a GM's wallet and destroy the evidence of whatever produced it.

### OVERSHOOT-B — INVALID TRANSACTION STATE (Opus ruling, incorporated)

**Correction 1.** §2 invariant 3 restored to strict equality on both sides. All deployment-dependent language removed. An issuer balance above its recorded ceiling at Final Lock fails loud and posts nothing.

**Correction 2.** The overshoot fixture is retained with its arithmetic intact, and **reclassified** as `PURE-FUNCTION FIXTURE ONLY — NOT A LEGITIMATE P3-D2 TRANSACTION STATE`. It still does the one job it was added for: proving MS-SIM-9(b)'s original blanket "mathematically unreachable" was too strong. It establishes nothing about production reachability.

**No P3-D1 code change is required.** The pure function's behaviour is correct and Opus confirmed it. The correction is entirely about what the P3-D2 *caller* may accept as an entry state.

**Composition note (necessary for Correction 1 to actually bind — flagged for confirmation).** Strict equality alone does not force a zero issuer refund unless the recorded issuer ceiling *is* the Anchor. §5 already rules that the exposure ceilings freeze at the accepted amounts at Handshake, so `recorded_ceiling(issuer) == anchor`. Rev 9 states both facts together, because either alone leaves a door open: a challenge recorded with `issuer_ceiling = 6000` against `anchor = 5000` would satisfy strict equality at escrow 6000 and yield `refund_issuer = 1000`, reintroducing precisely the state Opus outlawed through a different route. See §2 invariant 3a.

**Rev 8 changes retained (all Opus-confirmed):**
- **§9 Favorite-better corrected to 555¢ / 542¢** (ruling R7-A), with the 609 / 488 frozen-pot lineage note preserved.
- **MS-SIM-9(b) corrected** — the distinction between the odds-driven invariant and the pure-function possibility, now sharpened per Correction 2.
- **Final-Lock stale-claim recovery fully specified** — 15-minute TTL, system-worker-only reclaim by the acquiring worker, in-place conditional reclaim, four crash cases, different-event-ID double-execution closed.
- **Claim vocabulary reduced to three states** — `claimed`, `completed`, `failed`; `in_progress` eliminated as unreachable under a two-phase commit.
- **ESCROW-A** and the forward-migration ruling; **FINALSTATE-A**; dedicated `ChallengeFinalLockClaim` with `UNIQUE(challenge_id)`.

**Rev 7 change note retained (the MS-SIM-10 correction):**
- Rev 6 incorrectly treated the once-only marker as part of a **single completion transaction** and instructed the implementation to **mirror the current settlement guard**. The FR-8.7 grep proved the settlement guard is a **cautionary example, not a template**: it commits `settled=True` *before* the economic work, with no in-progress state and no recovery path, so a mid-work crash strands the week permanently.
- Rev 7 replaced that with a **durable claim-first, recoverable two-phase protocol**. Only `completed` may suppress future execution permanently.
- **The settlement completion-first pattern is explicitly NOT controlling.**
- The Final-Lock escrow-equals-ceiling first-entry precondition (MS-SIM-12) is **preserved as a secondary backstop only** — the durable claim and completed-state check are the primary idempotency controls.

**Rev 6 changes retained (Opus round 2, MS-SIM-11..14 + two corrections):**
- **MS-SIM-11 (A):** the pot never grows, enforced by the **ceiling cap, not the derivation**. §0 restated.
- **MS-SIM-12 (A):** the escrow==ceiling comparison is a **first-entry Final-Lock precondition**, not a timeless invariant.
- **MS-SIM-13 (A):** all "floor-both" terminology removed — only the opponent's Derived Stake floors.
- **MS-SIM-14 (A):** round-3 targets set.
- **Correction:** deleted §2's stale "No Change 1¢ refund" paragraph.
- **Correction:** §1 label "Floor-both rounding" → "Derived-stake floor rounding."

**The wager model (the spine — read this first):**
A Dynamic Challenge is **asymmetric**. The issuer commits a fixed amount — "I'm putting up $X" (the **Anchor Stake**). Dynamic pricing determines how much the **opponent** must risk against that fixed commitment, capped at the opponent's original Handshake ceiling. The opponent's stake is the **only** odds-derived stake. At Final Lock the engine re-derives the **opponent's** stake from final probabilities and caps it; the issuer's stake never moves on odds. **The issuer does not receive an odds-driven refund** when its probability worsens — the anchor is a fixed commitment, by design. **In the authorized P3-D2 lifecycle the issuer receives no Final-Lock refund at all**: escrow equals the Anchor at Handshake exit and nothing may change it before Final Lock, so the subtraction is zero. A nonzero issuer refund is not a funding event to be paid — it is an invariant violation to be refused (§2 invariant 3).

**Prior-round changes retained:**
- **MS-SIM-7 (frozen-pot REMOVED):** Final Lock uses canonical anchor derivation.
- **MS-SIM-8 (Handshake-exit assertion):** independent-read check that the true-up landed escrow and ceiling consistently.
- **MS-SIM-9 (named-account checks):** refunds verified by specific account. **9(b) final wording in Rev 9 §2.**
- **MS-SIM-10 (durable claim-first two-phase idempotency):** recovery policy defined in §5.
- **MS-SIM-4 (floor ruling), MS-SIM-2 (posting-level self-check), MS-SIM-6 (window-closure grep).**
- Money moves at the Dynamic Handshake; `residue_cents` removed; model freezes at Handshake, reused at Final Lock.

---

## 0 — The ruling this spec is built on (challenge mode is the switch)

*Unchanged.*

- **Locked Challenge** — a handshake is a handshake. At acceptance, the line, odds, both stakes, payout, and covered entities freeze. A later scratch or lineup change does **not** reprice. Settlement reads the terms frozen at acceptance.
- **Dynamic Challenge** — at the Handshake, three things freeze: the model version, each side's **maximum exposure**, and the **escrow ceiling** (the pot). The final odds do **not** freeze. Between Handshake and Final Lock, informational refreshes are nonbinding — they move no money. At **Final Lock**, the engine runs **exactly one** official simulation on the final lineup, applies The Adjustment once, and may **preserve or reduce** each side's exposure but **never increase** it. Settlement reads the terms frozen at Final Lock.

Consequences that bound the whole build:
- **No continuous ledger-changing repricing.** The Adjustment posts money exactly once per Dynamic challenge, at Final Lock.
- **No settlement-time repricing.** Settlement is a pure read of frozen terms.
- The Handshake sets a **per-side** exposure ceiling. Each side's ceiling is a hard cap; their sum is the maximum funded pot. **The pot never grows — but under the canonical anchor model this is enforced by the ceiling cap, not by the derivation.** When the issuer's odds worsen, the Final-Lock derivation mathematically *demands a larger* opponent stake (`floor(anchor/p_iss_final × p_opp_final)` can exceed the opponent's Handshake ceiling); the immutable opponent ceiling caps it back down. The ceiling is therefore the **load-bearing no-increase guard**. Per-side final exposure and final funded escrow must never exceed the Handshake ceilings.

---

## 1 — What already exists (do not rebuild)

The Monte Carlo core is **already built** in `odds/odds_engine_headless.py`. Confirmed function surface: `run(...)`, `simulate_scores(...)`, `simulate_player_scores(...)`, `_simulate_team(pts, rng)`, `_prob_to_american(prob)`, `_adjust_for_scoring(...)`, `_build_starter_lines(...)`, `N_SIMS`, `PlayerProj`.

The accept path in `beefs/beef_engine.py` already recomputes odds at acceptance via `_compute_odds_from_inputs`. **No repricing trigger, no drift, no refresh machinery exists yet.** That is the greenfield part.

**Layers 1–3 are built and committed.** `odds/dynamic_pricing.py` (commit `79a81cf5`) implements the §2 conversions, the asymmetric derivation and the Adjustment as pure functions, independently reviewed and accepted (P3-D1). It has no ledger, session, ORM or event coupling, proven by a token-scanned fence with a scan control. The §9 self-check is confirmed **against that committed module**, not only by hand.

**Remaining work:**
1. ~~Port the stake/pot math~~ — **DONE, P3-D1.**
2. ~~Derived-stake floor rounding (FR-8.3)~~ — **DONE, P3-D1.**
3. ~~The Adjustment as pure math~~ — **DONE, P3-D1.**
4. The new machinery: Dynamic Handshake funding, Final-Lock trigger, model-freeze, nonbinding informational refresh, and the durable claim protocol. **This is P3-D2, and it is not authorized until Opus confirms Rev 9's corrections.**

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

**Rounding convention.** `round` here is the **JavaScript** rule — half away from zero. Python's built-in `round` is round-half-to-even, so `round(162.5)` is 162 in Python and 163 in JS. All magnitudes are positive, so `floor(x + 0.5)` is exactly JS's rule and is the required port. Inheriting whichever language's default happens to run would produce one-unit price discrepancies against the certified calculator at every tie.

**Asymmetric stake derivation (FR-8.2) — the pricing law:**
```
fairPot        = anchor / p_issuer          # issuer enters Anchor Stake (whole BAB cents)
issuer_stake   = anchor                      # NOT re-floored — already whole cents
opponent_stake = floor(fairPot × p_opponent) # only the derived side floors (FR-8.3)
```
The favorite risks more. There is no "size me at" toggle. Decline is the opponent's protection.

**The Adjustment (Dynamic only, once at Final Lock) — canonical anchor derivation:**

The Adjustment re-runs the **asymmetric derivation** on the final-lineup probabilities. It does **not** reallocate a pot. The issuer's Anchor Stake is fixed; only the opponent's Derived Stake reprices, capped at its Handshake ceiling.

```
# inputs frozen at Handshake: anchor, issuer_ceiling, opponent_ceiling,
# and the two live escrow balances.

fairPotFinal    = anchor / p_issuer_final
issuerFinal     = anchor                                  # fixed; = min(anchor, issuer_ceiling)
opponentDerived = floor(fairPotFinal × p_opponent_final)  # only the derived side floors (FR-8.3)
opponentFinal   = min(opponentDerived, opponent_ceiling)  # capped at Handshake ceiling

refund_issuer   = issuer_escrow_balance   - issuerFinal    # ZERO in every legitimate path
refund_opponent = opponent_escrow_balance - opponentFinal
final_funded_escrow = issuerFinal + opponentFinal
```

**`fairPotFinal` is recomputed, never reused.** It is derived from `p_issuer_final`, not carried forward from the Handshake. Reusing the Handshake pot is exactly the defect corrected in §9.1.

If the issuer's win-probability **improves**, the opponent's fair stake shrinks below its ceiling → opponent refunded. If it **worsens**, the opponent's fair stake would rise above its ceiling → capped, no change, no refund either side. The issuer, having committed the anchor, carries that fixed exposure regardless.

### MS-SIM-9(b) — final wording (Rev 9)

Rev 7 said a both-positive refund was "mathematically unreachable" without qualification. Rev 8 corrected that but over-corrected in the other direction, treating the mathematical possibility as a permitted production state. Rev 9 states both halves precisely and keeps them apart.

**Mathematical statement.** Two positive refunds **are reachable in the pure `adjust_escrow` function** if issuer escrow independently exceeds the Anchor. The function computes `refund_issuer = issuer_escrow − anchor` and `refund_opponent = opponent_escrow − opponentFinal`; supply `issuer_escrow = 5250`, `anchor = 5000`, `opponent_escrow = opponent_ceiling = 1097` and `p_issuer_final = 0.90`, and it correctly returns 250 and 542. The arithmetic is right, the function is right, and Rev 7's blanket "mathematically unreachable" was therefore too strong. **This is the whole of the mathematical claim.**

**Production-state statement.** In the authorized P3-D2 transaction lifecycle:

1. Issuer escrow **must equal** the recorded issuer ceiling at Handshake exit (MS-SIM-8, exact equality, independent reads).
2. The recorded issuer ceiling **is** the accepted Anchor (§5 Handshake: exposure ceilings freeze at the accepted amounts).
3. The Handshake→Final-Lock window is **closed** — MS-SIM-6's grep proved no authorized path writes escrow in that window, and Final Lock itself fires *at* the boundary, not inside it.

Therefore, in every legitimate Final-Lock entry:

- `issuer_escrow == anchor == issuerFinal`, so **`refund_issuer == 0` identically**;
- **odds movement never creates an issuer refund** — the invariant Opus confirmed;
- **the legitimate P3-D2 Final-Lock path cannot produce a both-positive refund state**;
- if issuer escrow nonetheless exceeds the recorded ceiling, that is an invariant violation with no authorized cause. **Fail loud. Do not refund it.**

**The two statements do not conflict, and neither licenses the other.** The pure function is mode-agnostic and correctly computes whatever it is handed; the caller is what decides which inputs are admissible. A mathematically valid output is not evidence of a reachable state.

**No P3-D1 change is implied.** `adjust_escrow` keeps its current behaviour. The admissibility check belongs to the P3-D2 caller, ahead of the call.

**Invariant guards (fail loud, post nothing on failure — integer cents, exact):**

The Rev 3 invariant "refunds == pot drop" was a **tautology** (MS-SIM-2): `(iss_esc − iss_final) + (opp_esc − opp_final)` and `(iss_esc + opp_esc) − (iss_final + opp_final)` are the same subtraction, so the check could never fail and proved nothing. Replaced with **posting-level double-entry checks** — the load-bearing law the ledger's own `post()` guard enforces:

```
1.  probabilities sum to 1 at final lineup:
    round(p_issuer_final + p_opponent_final, 6) == 1

2.  HANDSHAKE-EXIT assertion (MS-SIM-8) — escrow and recorded ceiling agree,
    read INDEPENDENTLY (ledger balance vs challenge-row ceiling), EXACT EQUALITY:
    assert escrow_balance(issuer)   == recorded_ceiling(issuer)
    assert escrow_balance(opponent) == recorded_ceiling(opponent)
    # a true-up that writes escrow and ceiling inconsistently fails HERE, at
    # Handshake exit — not silently at Final Lock.

3.  FINAL-LOCK first-entry PRECONDITION (MS-SIM-6, MS-SIM-12, OVERSHOOT-B) —
    NOT a timeless invariant. Must pass on the first legitimate execution,
    BEFORE refunds post. STRICT EQUALITY ON BOTH SIDES:
    assert escrow_balance(issuer)   == recorded_ceiling(issuer)
    assert escrow_balance(opponent) == recorded_ceiling(opponent)
    #
    # Holds on first entry: nothing touched escrow in the window. After a
    # completed Adjustment it is NO LONGER expected to hold — the refund dropped
    # opponent escrow below ceiling. SECONDARY BACKSTOP ONLY — the primary
    # idempotency controls are the durable claim + completed-state check (§5).
    # A test author must NOT assert this "always passes": it fires on first entry
    # and is DESIGNED to fail on an illegitimate re-entry.
    #
    # OVERSHOOT-B: there is NO >= allowance on either side, and the strictness
    # does not vary by deployment, league, environment or configuration.
    # escrow_balance(side) > recorded_ceiling(side) at Final Lock is an INVARIANT
    # VIOLATION with no authorized cause: Handshake exit required equality
    # (guard 2), and the window contains no authorized escrow writer (MS-SIM-6).
    # On violation: FAIL LOUD, POST NOTHING. The Final-Lock transaction must not
    # normalize the balance, must not refund the unexplained excess, and must not
    # treat it as a success path. Refunding it would move an unexplained balance
    # into a GM's wallet and erase the evidence of whatever produced it.

3a. CEILING COMPOSITION (Rev 9) — guard 3 only forces a zero issuer refund
    because the recorded issuer ceiling IS the Anchor:
    assert recorded_ceiling(issuer) == anchor
    # Ruled at §5 (Handshake freezes ceilings at the accepted amounts). Stated
    # here because guard 3 alone is insufficient: a challenge recorded with
    # issuer_ceiling 6000 against anchor 5000 would satisfy guard 3 at escrow
    # 6000 and produce refund_issuer 1000 — the state OVERSHOOT-B outlaws,
    # reached through a different door.

4.  exposure never grows — both refunds non-negative:
    refund_issuer   = escrow_balance(issuer)   - issuerFinal   >= 0
    refund_opponent = escrow_balance(opponent) - opponentFinal >= 0
    # With guards 3 and 3a passed, the issuer limb is provably == 0, not merely
    # >= 0. It is retained as a backstop, not as a live branch.

5.  each refund posted as a balanced escrow->wallet PAIR summing to zero, by
    NAMED account (MS-SIM-9a):
    post([("escrow:challenge:{id}:derived", -refund_opponent),
          ("wallet:{opponent}",              refund_opponent)])
    # assert wallet:{opponent} rose by exactly refund_opponent BY NAME
    # (not "a wallet rose"). Account strings per §7.1 ESCROW-A.
    #
    # There is NO issuer refund pair in the legitimate path. refund_issuer is
    # identically zero (guards 3 + 3a), and a zero-amount posting is not written.
    # A P3-D2 implementation that contains an issuer-refund posting branch has
    # built a path that can only execute on an invariant violation guard 3
    # already refused.

6.  after refunds: escrow holds exactly each side's final stake, trial balance 0:
    escrow_balance(issuer)   == issuerFinal
    escrow_balance(opponent) == opponentFinal
    trial_balance() == 0
```

Checks read **live integer escrow balances** and post **real ledger pairs by named account**. No float tolerance; integer cents, exact. (The JS `0.005` tolerance is a float artifact, deliberately not ported.)

**On the sub-cent residue (MS-SIM-3/5):** `fairPotFinal × p_opponent_final` before flooring may carry a fraction of a cent. Per the MS-SIM-4 ruling, that fraction is **never funded** — never escrowed, never posted, never refunded, never was BAB. It is not "stranded" or "destroyed"; it never existed as money. No conservation proof required: nothing leaves escrow that did not enter it. See §3.

**Under the canonical anchor model there is no "No Change" refund artifact.** When probabilities are unchanged from Handshake, the Final-Lock derivation repeats the Handshake calculation exactly: `issuerFinal` is the raw anchor (no floor), and the opponent re-derives to precisely its ceiling. Zero refund, both sides.

---

## 3 — FR-8.3: Derived-stake floor rounding (OPUS-CONFIRMED)

*Unchanged.*

Only **one** side ever floors: the opponent's Derived Stake. The issuer's Anchor Stake is already whole BAB cents and fixed — never floored, at Handshake or Final Lock. ("Floor-both" was frozen-pot language; that model is removed. There is no floor-both.)

The sub-cent residue is **never funded** (MS-SIM-4). There is **no `residue_cents` field** — an integer-cent name implies a postable cent, and this residue never posts. Where audit math needs the value, expose it as `residue_decimal` (diagnostic only). Otherwise verify the funded pot directly: `funded_pot_cents = issuer_cents + opponent_cents`.

**Adversarial cases (single-floor line):**
- **Extreme favorite, near-zero derived stake:** p_iss = 0.95 → opponent Handshake stake `floor(6097.56 × 0.05)`; then Final Lock improves to p_iss = 0.98 → `opponentDerived = floor(5000/0.98 × 0.02) = floor(102.04) = 102`. This example **recomputes** `fairPotFinal = 5000/0.98`; it does not reuse the Handshake pot.
- **Above-ceiling derivation:** issuer worsens so `floor(fairPotFinal × p_opp_final)` exceeds the opponent ceiling → cap applies, no refund; no pot growth.
- **Exact-ceiling derivation:** the derived stake lands exactly on the ceiling — no refund, no cap needed.
- **Non-dividing residue:** `fairPot` carries a fraction; the residue is never funded and never appears in any posting.

---

## 4 — Module surface

*Unchanged. Layers 1–3 are committed; these are the shipped signatures.*

```
# conversions (ported pure)
o2p(odds: int, is_neg: bool) -> float
p2o(p: float) -> tuple[int, bool]            # (magnitude, is_negative)

# pricing (FR-8.2, integer cents) — anchor is whole cents, only derived side floors
derive_stakes(anchor_cents: int, p_issuer: float, p_opponent: float)
    -> StakePair(issuer_cents, opponent_cents, funded_pot_cents,
                 fair_pot_decimal, residue_decimal)
    # issuer_cents == anchor_cents (not re-floored)
    # opponent_cents == floor(fairPot * p_opponent) (FR-8.3)
    # NO residue_cents field. residue_decimal is diagnostic-only.
    # opponent_cents at Handshake IS the opponent's Handshake ceiling.

# adjustment (Dynamic only, once at Final Lock) — canonical anchor derivation.
adjust_escrow(
    anchor_cents: int,
    p_issuer_final: float, p_opponent_final: float,
    issuer_ceiling_cents: int, opponent_ceiling_cents: int,
    issuer_escrow_balance_cents: int, opponent_escrow_balance_cents: int,
) -> AdjustmentResult(
        issuer_final_cents, opponent_final_cents,
        refund_issuer_cents, refund_opponent_cents,
        final_funded_escrow_cents,
        opponent_derived_raw_cents, ceiling_applied,
        fair_pot_decimal, residue_decimal,
    )
    # raises on invariant failure: probabilities out of range or not summing to 1;
    # issuer ceiling below the fixed anchor; opponent final above ceiling;
    # either refund negative (Final Lock refunds, it never collects).
```

These functions are **mode-agnostic**: they compute stakes and adjustments and know nothing about challenges, escrow accounts, events, claims or admissible entry states. The **caller** decides whether to call `adjust_escrow` at all — Locked never does, Dynamic does exactly once — **and whether the inputs it is about to pass are a legitimate transaction state.** §2 guard 3 is the caller's obligation, not the function's.

---

## 5 — The new machinery (Dynamic only — greenfield, P3-D2)

- **Handshake — funds both sides, freezes the model.** The Handshake atomically establishes and **fully funds** each side's maximum exposure: the issuer's issue-time escrow is trued up to the accepted amount and moved into the Anchor account, the recipient's Derived Stake moves into the Derived account, both maximum losses are fully funded, and the simulation **model version** + per-side exposure ceilings freeze on the challenge row. **The recorded ceilings freeze at the accepted amounts — the issuer's ceiling is the accepted Anchor** (see §2 guard 3a). **Money moves here.** Account topology per §7.1. **On Handshake exit (MS-SIM-8):** assert `escrow_balance(side) == recorded_ceiling(side)` for both sides, exact equality, reading escrow from the **ledger** and the ceiling from the **challenge row** — two independent reads. The counter-true-up is the writer that sets both values; this assertion is how we prove it set them consistently.
- **Informational refresh (nonbinding).** Between Handshake and Final Lock, a display-only re-sim may show GMs where the line sits. Writes nothing to the ledger. **Only these refreshes move no money.**
- **Final-Lock trigger — reprice once, under the two-phase protocol below, using the model frozen at Handshake.** A single scheduled event, fired at the challenge's earliest covered kickoff (`_nfl_lock_time` / per-challenge kickoff already computed in `beef_engine`). The economic work (Phase 2) proceeds only after the durable claim (Phase 1) is committed. On execution: assert §2 guard 3 (strict equality, both sides), then run **one** official simulation on the final lineup **under the Handshake-frozen model version** → `adjust_escrow` → post the Derived refund as a balanced escrow→wallet pair by named account → freeze final terms → migrate. The model is **not** frozen at Final Lock — it was frozen at Handshake and is **reused** here.

### 5.1 — Durable two-phase idempotency (MS-SIM-10), claim-first and recoverable

**Phase 1 — durable claim.** Atomically acquire a unique Final-Lock execution claim for the challenge. Commit it **separately, before** any official simulation or BAB movement. Its sole purpose is to exclude concurrent workers.

**Phase 2 — atomic economic work. ONE transaction, ONE commit.** Perform and commit together:
1. Revalidate the claim is still owned by this worker and not already completed.
2. Assert §2 guard 3 (first-entry precondition, strict equality both sides). **On violation: abort. Post nothing. Do not transition. Record the violation.**
3. Run or persist the official Final-Lock simulation result.
4. Execute the canonical Adjustment. **Opponent side only** — with guards 3 and 3a passed, `refund_issuer` is identically zero and there is no issuer branch to take.
5. Post the Derived escrow→wallet refund through balanced Ledger entries, by named account.
6. Freeze the official Final-Lock probabilities, odds, stakes, payout, covered entities and settlement terms into the immutable `ChallengeFinalLock` record (§7.3).
7. Migrate the remaining per-side escrow into the two Bet escrow accounts (§7.1).
8. Transition the challenge to `Pending`.
9. Create the immutable audit record.
10. Flip the claim to `completed`, setting `completed_at`, `final_lock_id` and `protocol_event_id`.

**Step ordering 5-before-7 is load-bearing, not incidental.** The refund must post before the migration, so the migration moves a settled balance. Migrating first would carry the pre-refund amount into Bet escrow and leave the refund with nothing to draw against. This mirrors the release-before-migrate ordering already accepted on the Locked acceptance path.

These commit together. A Phase 2 failure rolls back **all** Phase 2 writes while leaving the Phase 1 durable claim available for recovery. **Phase 2 is not to be split into multiple transactions for convenience or for progress reporting** — see §5.3 on why a separately-committed intermediate state is not part of this protocol.

**This does NOT mirror the current settlement guard.** `settle_week` commits `settled=True` *before* the economic work with no in-progress state and no recovery path — the FR-8.7 crash-recovery gap. That completion-first pattern is a **cautionary example, not a template.**

### 5.2 — Claim structure and uniqueness

Use a dedicated **`ChallengeFinalLockClaim`** concept/table. It is the *execution right*; `ChallengeFinalLock` (§7.3) is the *frozen result*. Separate records, separate lifetimes.

```
challenge_final_lock_claims
  id                    PK
  challenge_id          NOT NULL, FK -> beef_challenges.id,
                        UNIQUE   <- uq_challenge_final_lock_claim_challenge
  status                NOT NULL, CHECK IN ('claimed','completed','failed')
  claimed_by            NOT NULL          -- worker/process identity
  claimed_at            NOT NULL
  claim_expires_at      NOT NULL          -- staleness is DATA, not a hardcoded guess
  attempt_count         NOT NULL DEFAULT 1
  previous_claimed_by   NULL              -- audit trail across reclaims
  last_reclaimed_at     NULL
  failure_reason        NULL              -- set with status='failed'
  completed_at          NULL
  final_lock_id         NULL, FK -> challenge_final_locks.id
  protocol_event_id     NULL, FK -> protocol_events.id   -- original result reference;
                                          -- written by Phase 2 step 10 ONLY, never
                                          -- at acquisition or reclaim

  CHECK  (status = 'completed') = (completed_at  IS NOT NULL)
  CHECK  (status = 'completed') = (final_lock_id IS NOT NULL)
```

**`UNIQUE(challenge_id)` is the mutex.** One Final-Lock execution right exists per challenge, forever. The constraint says exactly that, which is why the key is `challenge_id` alone on a dedicated table rather than `(challenge_id, operation_kind)` on a shared one: a kind column would weaken the statement to "each kind happens once," and would silently permit a second row the day a second kind appeared.

**`ProtocolEvent.event_id` is NOT the mutex.** It remains delivery/idempotency identity per Ruling 1 of the Foundation Correction Plan, which assigns one identity concern per tier and forbids a second uniqueness rule competing with `event_id`.

**Acquisition is a single atomic statement, never a `SELECT ... FOR UPDATE` on a possibly-absent row.** P1-L7 established why: a `FOR UPDATE` matching zero rows locks nothing and raises nothing, which is how a worker comes to believe it was serialized when it was not. Two admission paths, each atomic:

```
-- fresh acquisition
INSERT INTO challenge_final_lock_claims
       (challenge_id, status, claimed_by, claimed_at, claim_expires_at, attempt_count)
VALUES (:cid, 'claimed', :worker, now(), now() + interval '15 minutes', 1)
ON CONFLICT (challenge_id) DO NOTHING
RETURNING *;
-- rowcount 1 -> this worker owns execution. rowcount 0 -> read the row and branch.

-- reclaim (only when the existing claim is reclaimable)
UPDATE challenge_final_lock_claims
   SET claimed_by = :worker,
       previous_claimed_by = claimed_by,
       claimed_at = now(),
       last_reclaimed_at = now(),
       claim_expires_at = now() + interval '15 minutes',   -- MUST be refreshed
       attempt_count = attempt_count + 1,
       status = 'claimed',
       failure_reason = NULL
 WHERE challenge_id = :cid
   AND status <> 'completed'
   AND (status = 'failed' OR claim_expires_at < now())
RETURNING *;
-- rowcount 1 -> this worker now owns execution. rowcount 0 -> someone else won,
-- or the claim is live and not yet stale, or it is already completed. Do not retry
-- in a tight loop; back off and re-read.
```

**The conditional `UPDATE` with a rowcount check is the reclaim mutex.** A unique index does nothing on an update, so the predicate carries the exclusion: two workers racing to reclaim the same stale claim produce exactly one rowcount of 1.

**Refreshing `claim_expires_at` on reclaim is load-bearing.** A reclaim that inherits the expired timestamp hands the new owner a claim that is already stale, so a third worker could reclaim it out from underneath immediately and both would execute. The `SET claim_expires_at = now() + TTL` clause is not bookkeeping.

**Lock rank is unaffected, and the claim table sits outside it.** Phase 1 commits before Phase 2 begins, so no lock is held across the boundary and the claim row is never held while a challenge or Wallet row is locked. Phase 2 then takes the challenge row, then Wallet rows ascending by `team_id`, per Spec 2 §8 and P1-L7. The claim table introduces no new edge into the lock graph and therefore no inversion.

### 5.3 — Claim state vocabulary: three states, not four

Rev 7 spoke of a claim representing "`CLAIMED` or `IN_PROGRESS`." **`in_progress` is eliminated as unreachable.** Retained: `claimed`, `completed`, `failed`.

**Why `in_progress` cannot exist under this protocol.** To be observable it must be *committed*. Writing it at the start of Phase 2 does not commit it — Phase 2 is one transaction, so a crash or failure rolls that write back with everything else, and a completing run overwrites it with `completed` in the same transaction. No external observer can ever read it. Making it observable would require committing it separately, turning the ruled two-phase protocol into three phases for a purely diagnostic gain. Retaining an unreachable member in a money-path CHECK invites a future branch that can never execute.

**`claimed`** — owned, not complete. Rev 7's "CLAIMED or IN_PROGRESS" collapsed into the one thing that distinction tracked: someone holds the execution right and has not finished. Reclaimable on expiry.

**`completed`** — the only suppressing state. Structurally implies both `completed_at` and `final_lock_id` via the two biconditional CHECKs, so half-completion is unrepresentable. **Never reclaimable.**

**`failed`** — the immediate-release path. A worker that hits a deterministic error (bad projection data, a failed §2 guard 3, an invariant violation) marks `failed` with a reason and releases ownership at once, instead of forcing every other worker to wait out the full staleness window for a claim whose owner is already gone. Without it, a deliberate failure must masquerade as an expiry or delete the row and lose the audit trail. `failed` is an attempt outcome, not a challenge outcome.

### 5.4 — Recovery decision A: staleness threshold

**Ruled: 15 minutes, as a named constant with that default.**

```
FINAL_LOCK_CLAIM_TTL = timedelta(minutes=15)
```

**Rationale.** The long pole in Phase 2 is one Monte Carlo run over `N_SIMS` for two teams — seconds to low tens of seconds on the existing headless engine. Everything else (the Adjustment arithmetic, a handful of ledger postings, the frozen record, the audit row) is sub-second database work. Fifteen minutes is roughly two orders of magnitude of headroom, so a live owner will not expire underneath itself even on a degraded host or under contention on the challenge and Wallet rows.

Bounded on the other side by the recovery window: Final Lock fires at the earliest covered kickoff, and nothing downstream reads the frozen terms until settlement runs after the games conclude. A dead worker is detected and its challenge recovered with hours to spare.

A constant with a default, **not** configurable-without-default. Making it tunable per-league or per-environment is deliberately out of MVP scope: a staleness threshold settable to zero is a way to break the mutex from configuration.

### 5.5 — Recovery decision B: who may reclaim

**Ruled: only an authorized Final-Lock system worker, and the reclaim is performed by the acquiring worker itself.**

- **Actor class.** The same scheduled system worker/process class that acquires fresh claims. Not an end user, not a GM, not a commissioner, not reachable from any HTTP route. Final Lock is machine-triggered at kickoff; a human "retry" button would be a second admission path into the money path and there is no product requirement for one.
- **Mechanism owner.** Reclaim is folded into the **acquisition path** — a worker that fails the `INSERT ... ON CONFLICT DO NOTHING` reads the row and, if reclaimable, attempts the conditional `UPDATE`. There is deliberately **no separate sweeper process**: a sweeper would be a second writer of the ownership fields and a second thing to keep correct.
- **Commissioner override is explicitly deferred.** If operations later show a need to force-release a claim, that is a new ruling with its own authorization and audit requirements. Not MVP, and not to be added as an incidental admin route.

### 5.6 — Recovery decision C: reclaim mechanism

**Ruled: in-place reclaim of the existing unique row. Never supersession.**

`UNIQUE(challenge_id)` makes supersession impossible without weakening the constraint, and the constraint *is* the mutex — so a second row is not a less tidy option, it is an option that requires dismantling the exclusion mechanism. Rev 9 does not weaken `UNIQUE(challenge_id)`.

Auditability is preserved on the row: `attempt_count` incremented on every reclaim; `claimed_by` and `previous_claimed_by`; `claimed_at`, `last_reclaimed_at`, `claim_expires_at`; `failure_reason` recording why the previous attempt released deliberately, cleared on reclaim.

If a deployment later needs the full attempt history rather than the last transition, the correct shape is an append-only child audit table keyed to the claim — **not** a second claim row.

### 5.7 — Crash semantics (explicit)

**Crash before the durable claim commits.** No execution ownership exists; no row is present. Another worker acquires normally through the fresh-acquisition path. No money moved; nothing to recover.

**Crash after the claim commits but before Phase 2 begins.** The claim survives at `claimed`. **No money moved** — Phase 1 posts nothing by construction. Reclaimable once `claim_expires_at` passes. `attempt_count` records it.

**Crash during Phase 2, before its commit.** All Phase 2 writes roll back atomically: no simulation result persisted, no refund posted, no `ChallengeFinalLock` row, no escrow migration, no `Pending` transition, no audit record, and the claim is **not** flipped to `completed`. The claim survives at `claimed` and becomes recoverable on expiry. **Escrow is exactly as the Handshake left it, so §2 guard 3's strict equality still holds for the recovering worker** — that is the property making recovery safe rather than merely possible, and it is a second reason the guard must stay strict: a `>=` allowance would let a recovering worker proceed against a balance a crash had left inconsistent.

**Crash after Phase 2 commits.** Final Lock is complete. The claim is `completed` with `final_lock_id` set. Every subsequent trigger — whatever its `event_id` — reads the completed claim and **returns the committed result**, running no simulation, executing no Adjustment, posting nothing. `completed` is the only state suppressing execution permanently, and it is never reclaimable.

### 5.8 — Two callers, two different event IDs

`ProtocolEvent.UNIQUE(event_id)` alone does **not** prevent double execution: two workers presenting **different** UUIDs for the **same** challenge both satisfy event-id uniqueness and, absent a challenge-scoped claim, both proceed.

The claim closes it. Both attempt `INSERT ... ON CONFLICT (challenge_id) DO NOTHING`; exactly one gets rowcount 1. The loser reads the row and branches:

- `claimed` and not expired → **do not execute, do not report success.** Back off; the owner is working.
- `claimed` and expired → attempt the conditional reclaim; proceed only on rowcount 1.
- `completed` → return the original committed result. Post nothing.
- `failed` → attempt the conditional reclaim; proceed only on rowcount 1.

`event_id` keeps its own job: it de-duplicates *delivery* of the same trigger, and the `ProtocolEvent` written in Phase 2 records which delivery performed the execution. The two mechanisms answer different questions and neither substitutes for the other.

**Backstop (secondary only):** §2 guard 3 remains secondary protection — if a duplicate bypasses the claim controls and reaches it on already-refunded escrow, it fails loud and posts nothing. The **durable claim and the `completed`-state check are the primary controls.**

*MS-SIM-6 note:* the grep proved the Handshake→Final-Lock window is closed in current code (no cancel/void/reverse paths exist; Tuesday-sync touches rosters/scores/players not escrow; shortfall sweep posts to `wallet:` at settlement, not `escrow:` mid-window). The Final-Lock repricing this spec adds is itself a new escrow writer, but it fires **at** the boundary, not mid-window. **This closed window is the factual basis for OVERSHOOT-B**: with no authorized in-window escrow writer, an issuer overshoot at Final Lock has no legitimate cause, which is why §2 guard 3 refuses rather than accommodates it.

**No always-on repricing loop. No settlement-time work.** The machinery is: fund-and-freeze at Handshake, optionally show, reprice-once at Final Lock, done.

---

## 6 — Locked vs Dynamic: where the branch lives

*Unchanged.*

| Stage | Locked | Dynamic |
|---|---|---|
| At acceptance / Handshake | Freeze line, odds, stakes, payout, entities (both stakes already escrowed) | **Fully fund both sides' max exposure** (issuer true-up + recipient fresh escrow) into the per-side accounts, then freeze model version + per-side ceilings |
| Between accept and kickoff | Nothing — inert | Nonbinding informational refresh (no money) |
| At Final Lock | N/A (already frozen) | One official sim → Adjustment → Derived refund → freeze → migrate to Bet escrows |
| At settlement | Read frozen-at-acceptance terms | Read frozen-at-Final-Lock terms |

The engine functions in §4 are mode-agnostic. The **caller** decides whether to call `adjust_escrow` at all — Locked never does; Dynamic does exactly once — and whether the entry state is admissible.

---

## 7 — Accepted P3-D2 architecture (Opus-confirmed, not reopened)

### 7.1 — ESCROW-A: per-side Dynamic escrow topology

**Before the Dynamic Handshake** — unchanged from Spec 2. Issue, counter, decline, cancel, expire and revive all use the pooled account:

```
escrow:challenge:{challenge_id}
```

**At the Dynamic Handshake** — the pooled balance moves forward into per-side accounts, and the opponent funds its full ceiling:

```
escrow:challenge:{challenge_id}:anchor      <- issuer/Anchor maximum exposure
escrow:challenge:{challenge_id}:derived     <- opponent full Handshake ceiling
```

**At Final Lock** — only the Derived side receives a refund (§2: the issuer's is identically zero in every legitimate path). The remaining per-side balances then migrate into the Bet escrow accounts, which use the account shape already established on the Locked acceptance path:

```
escrow:{anchor_bet_id}      <- from escrow:challenge:{id}:anchor
escrow:{derived_bet_id}     <- from escrow:challenge:{id}:derived
```

**Why per-side accounts are required rather than preferred. Four of §2's invariant guards are inexpressible against a pooled account.** Guards 2 and 3 compare *one side's* escrow balance against *that side's* recorded ceiling; a pooled balance is the sum and cannot be compared to one ceiling. Guard 5 requires refunds posted **by named account** with the assertion that a specific wallet rose by a specific amount — a debit from an account naming no side is not a named-account refund. Guard 6 requires each side's escrow to equal that side's final stake. Under a pooled account these properties could at best be inferred, and inference is exactly what MS-SIM-9(a) forbids.

**Cost: no schema change.** `ChallengeFundingLeg.destination_account` is already a string column, and Spec 2's provenance machinery already discriminates on it — `expected_challenge_escrow()` filters by destination and `_reverse()` selects only legs whose destination is the challenge account. Two new destination strings slot in unchanged.

**The funded-account guard covers the new accounts automatically.** `ledger.post()` guards every debited account except `world`, `receivable:*` and the door-bound `bab_issuance:*`. Two new `escrow:` strings inherit full protection with no exemption and no code change. **No exemption may be added for them.**

### 7.2 — The Handshake movement is a forward migration, not a reverse leg

Moving the pooled balance into `escrow:challenge:{id}:anchor` is a **forward migration**: a plain balanced posting, exactly like the challenge→Bet escrow migration at Locked acceptance. It writes **no `reverse` funding leg**.

A `reverse` leg means money returned to its **original funding source**. This money is not returned to anyone's wallet or weekly-minimum account; it moves onward. Writing a reverse leg would drive `remaining_reversible_cents` to zero on the original fund legs, and any later legitimate reversal would then fail closed against provenance that is perfectly sound.

**Reconciliation scope, restated:**

- The pooled reconciliation `balance(escrow:challenge:{id}) == SUM(unreversed legs whose destination is that account)` applies **pre-Handshake**.
- After a successful Handshake the pooled account may legitimately be **zero** while historical positive fund legs remain. That is the healthy end state, not a discrepancy.
- **Closed/advanced-state detection must run before the pre-Handshake reconciliation invariant is applied** — the pattern already accepted for Locked acceptance: check state first, reconcile second. Applying the reconciliation to a Handshaken challenge would read its healthy end state as an error and report a reconciliation failure forever after.

### 7.3 — FINALSTATE-A: Final-Lock completion representation

One immutable **`ChallengeFinalLock`** record per challenge, with **`UNIQUE(challenge_id)`** so "one per challenge" is structural rather than conventional. It carries the frozen Final-Lock result and the audit/provenance §5 requires: final-lock timestamp, final probabilities, final odds, final Anchor cents, final Derived cents, frozen market terms and covered entities, simulation/model provenance, and the governing Final-Lock event linkage.

**Do NOT add a new `BeefChallenge.response_status` value** for "awaiting Final Lock" or "final locked." §5 already transitions the challenge to `Pending` — the existing vocabulary. `ck_beef_response_status` is a closed six-value CHECK whose members Spec 1 §4 partitions into open, negotiation-terminal and accepted; a seventh value forces a partition question with no good answer, and every lifecycle path branches on that partition.

**Authoritative completion is exactly two things:** the `ChallengeFinalLock` row exists, and the governing `ChallengeFinalLockClaim` is `completed`. A status value would be a third representation of the same fact — and a duplicate source of truth has already cost this project one defect.

### 7.4 — The Anchor, restated unequivocally

**The issuer's Anchor Stake never reprices because of odds. Only the opponent's Derived Stake reprices.** This holds at Handshake and at Final Lock, in every branch, for every probability in the valid range.

**And in the authorized P3-D2 lifecycle the issuer receives no Final-Lock refund at all.** Guards 2, 3 and 3a compose to `issuer_escrow == recorded_ceiling(issuer) == anchor == issuerFinal`, so `refund_issuer` is identically zero. A nonzero issuer refund is therefore **not a funding-correctness event to be paid out** — Rev 8 said that, and Opus correctly rejected it. It is an invariant violation with no authorized cause, and §2 guard 3 refuses the transaction before any Adjustment runs. Investigate what wrote the escrow; do not refund the difference.

---

## 8 — What Opus reviews

Rounds 1–2 complete. **Round 3 complete on substance:** Opus confirmed the corrected arithmetic, the canonical anchor re-derivation, the per-side escrow and refund invariants, and the claim-first Final Lock with its recovery policy, and returned `REJECT — CORRECTION REQUIRED` on one point only — the Rev 8 issuer-side `>=` allowance, ruled **OVERSHOOT-B — INVALID TRANSACTION STATE**.

**Rev 9 requests confirmation of that correction only.** See the correction confirmation request below. No other target is reopened, and no previously confirmed finding is resubmitted.

---

## 9 — Self-check (per the standing rule)

The self-check models a **real double-entry ledger** with canonical anchor Adjustment, plus the MS-SIM-8 handshake-exit assertion, MS-SIM-9(a) named-account checks, and MS-SIM-10 durable claim-first idempotency. Every escrow movement is a debit/credit pair; the ledger rejects any pair that doesn't sum to zero; trial balance is asserted zero throughout.

**Line used:** anchor $50.00 (5000¢), issuer favorite at p=0.82. Handshake `fairPot` = 6097.560976¢ (non-dividing, exposes the floor residue). Handshake: issuer 5000¢ (unfloored anchor), opponent `floor(6097.560976 × 0.18) = 1097¢`, residue 0.561¢ (never funded). Recorded ceilings: issuer 5000¢ (= the Anchor, §2 guard 3a), opponent 1097¢.

**Every row recomputes `fairPotFinal = 5000 / p_iss_final`. None reuses the Handshake pot.**

### 9.0 — Production branches (legitimate transaction states)

All four rows enter with `issuer_escrow = 5000` — strict equality with the recorded issuer ceiling, per §2 guard 3.

| Branch | p_iss final | fairPotFinal | opponentDerived (raw) | issuer_final | opp_final | refund_iss | refund_opp | funded escrow | capped | guard 3 | double-fire | named-acct | TB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| No Change | 0.82 | 6097.560976 | 1097 | 5000 | 1097 | 0 | 0 | 6097 | no | ✓ PASS | orig, no repost | ✓ | 0 |
| Favorite worse | 0.70 | 7142.857143 | 2142 | 5000 | 1097 | 0 | 0 | 6097 | **yes** | ✓ PASS | orig, no repost | ✓ | 0 |
| **Favorite better** | **0.90** | **5555.555556** | **555** | **5000** | **555** | **0** | **542** | **5555** | no | ✓ PASS | orig, no repost | ✓ | 0 |
| Roles reversed | 0.35 | 14285.714286 | 9285 | 5000 | 1097 | 0 | 0 | 6097 | **yes** | ✓ PASS | orig, no repost | ✓ | 0 |

**`refund_iss` is 0 in every production branch.** Not "structurally zero as a design intention" — arithmetically zero, because guard 3 admits only `issuer_escrow == 5000` and `issuerFinal` is 5000.

**Confirmed two independent ways:** derived by hand from the §2 formula, and executed against the committed P3-D1 module (`odds/dynamic_pricing.py`, `79a81cf5`). Both agree on all four rows, every column.

- **The Anchor never reprices on odds** — `refund_iss` is 0 throughout.
- **Only the opponent refunds**, and only when the issuer's probability improves. When it worsens, the derived stake would rise above the ceiling → capped → no refund either side. Note the two capped rows: the raw derivation demands 2142¢ and 9285¢ against a 1097¢ ceiling. **The cap does the conservation work, not the derivation** (MS-SIM-11).
- Handshake-exit assertion holds, exact equality, independent reads.
- Double-fire returns the original `completed` result and posts nothing new (§5).
- Refunds verified **by named account**: `wallet:{opponent}` rose by exactly `refund_opponent`. No issuer pair is posted.
- Escrow holds each side's final stake; trial balance 0 after Handshake and after Adjustment.

### 9.0a — PURE-FUNCTION FIXTURE ONLY — NOT A LEGITIMATE P3-D2 TRANSACTION STATE

This row is **not** a production branch and must not be read as one. It exercises `adjust_escrow` directly, outside any transaction lifecycle.

| Fixture | p_iss final | issuer escrow | fairPotFinal | raw | issuer_final | opp_final | refund_iss | refund_opp | funded | **guard 3 (transaction-state invariant)** |
|---|---|---|---|---|---|---|---|---|---|---|
| True-up overshoot | 0.90 | **5250** | 5555.555556 | 555 | 5000 | 555 | 250 | 542 | 5555 | ✗ **FAILS — INVALID TRANSACTION STATE (OVERSHOOT-B). Pure-function fixture only.** |

**The arithmetic is retained and is correct.** `adjust_escrow` returns `refund_issuer = 250` and `refund_opponent = 542`, confirmed executably against the committed module. That is what the fixture is for.

**What this fixture establishes:** that `adjust_escrow` **can mathematically produce two positive refunds**, and therefore that MS-SIM-9(b)'s original blanket "mathematically unreachable" was too strong.

**What this fixture does NOT establish:**
- It does **not** establish production reachability.
- Presented as a real Handshake result it would **fail the Handshake-exit invariant** (§2 guard 2), which requires exact equality between issuer escrow and the recorded issuer ceiling.
- It **must never reach a legitimate Final Lock**, because the production window contains **no authorized issuer-escrow writer** (MS-SIM-6). Any real occurrence of this state is an invariant violation, not a fundable overshoot.
- §2 guard 3 **refuses** this entry state before any Adjustment runs. The 250¢ is not refunded on a success path; the transaction fails loud, posts nothing, and records the violation.

**Correct home for this fixture:** the P3-D1 pure-function suite, where it already lives. It must **not** appear in any P3-D2 lifecycle test as a valid Handshake result or a valid Final-Lock entry. A P3-D2 test using these inputs must assert **refusal**, not a two-sided refund.

### 9.1 — LINEAGE NOTE: the corrected Favorite-better row (do not erase)

**Rev 7 §8 gave this row as opponent 609¢ / refund 488¢. Both figures were wrong.**

609¢ is `floor((5000 / 0.82) × 0.10)` — the **Handshake** fair pot (6097.560976) multiplied by the **final** opponent probability. That is frozen-pot arithmetic: it reuses a pot instead of re-deriving one. MS-SIM-7 removed the frozen-pot model, and §2 states that the Adjustment "does not reallocate a pot."

The normative formula recomputes: `fairPotFinal = 5000 / 0.90 = 5555.555556`, and `floor(5555.555556 × 0.10) = 555`. Refund `1097 − 555 = 542`. **Opus Round 3 confirmed this result.**

**How it survived Rev 7.** The error is invisible in three of the four rows. No Change is unchanged-odds, so the two pots are identical. Favorite worse and Roles reversed both cap at the ceiling, so both models produce 1097. **The table was wrong in exactly the one row where the two models diverge** — the signature of arithmetic carried forward and never recomputed when the model was reversed.

**Correction to the Rev 7 confirmation claim.** Rev 7 §8 asserted "Confirmed programmatically, every branch." That was false for this row, which means the Rev 7 self-check harness itself carried the frozen-pot expression. The Rev 9 table is confirmed against the committed P3-D1 implementation and by hand, and the committed P3-D1 test suite pins **both** values arithmetically — asserting `floor((5000/0.82) × 0.10) == 609` and `floor((5000/0.90) × 0.10) == 555` — so the erratum is recorded in executable form rather than only in prose.

### 9.2 — MS-SIM-9(b): fixture retained, reclassified

Rev 7 said the both-positive fixture was "N/A… mathematically unreachable… No fixture added." **That was too strong**, and the fixture in §9.0a disproves it.

Rev 8 then went too far the other way, presenting the fixture as a production branch of the self-check with a passing `issuer >=` compliance cell. **Opus rejected that, correctly** (OVERSHOOT-B). A mathematically valid function output is not evidence of a reachable transaction state, and weakening a production invariant to accommodate one inverts the relationship between the two.

**Rev 9's position, in two sentences that must not be collapsed into one:**

- **Mathematically:** two positive refunds are reachable in the pure Adjustment function if issuer escrow independently exceeds the Anchor. The fixture proves it. Guards 4 and 6 hold for it in isolation (`5250 − 250 = 5000 = issuerFinal`; `1097 − 542 = 555 = opponentFinal`).
- **In production:** the authorized P3-D2 lifecycle cannot produce that state. Issuer escrow equals the Anchor at Handshake exit and nothing may change it before Final Lock, so `refund_issuer` is identically zero; and if escrow nonetheless exceeds the recorded ceiling, §2 guard 3 fails loud and posts nothing rather than refunding it.

**Self-check status: PERFORMED at posting level, corrected per OVERSHOOT-B, PASS. Production branches and pure-function fixtures are now separately tabulated.**

---

## 10 — Open items from the grep pass (not part of this spec, carried to session close)

*Unchanged.*

- **FR — MIN_BET $5→$1.** Live constant `wallet_manager.py` is `5.00`; ruling is `1.00` (universal, playoffs included). Fix is constant + docstring + re-fixture `test_stake_precision_validation.py` (swap $4.99 for a sub-$1 value) + fix the comment in `test_ledger_bet_conversion.py`. Money-path.
- **FR-5.7 writer absent.** `roster_slots` exists in production but is **empty**. Migration ran; the weekly-capture **writer** does not exist. Settlement runs on the static-Roster fallback. Needs a launch ruling.
- **deposit() not ledger-integrated.** `wallet_manager.py` mutates the float column, writes a Transaction row, never calls the ledger. Money-path.
- **`_nfl_lock_time()` 2026 season verification.** Becomes load-bearing at P3-D2: the Final-Lock trigger fires at the earliest covered kickoff computed by that helper.
- **Structural Wallet presence constraint (OPR-5).** Not yet satisfied; the P1-L7 mutex fails closed. Pre-production money-path gate. Handshake funding and Final-Lock refunds both rely on that mutex.

---

## 11 — Opus Round 3 non-blocking notes (carry-forward for P3-D2)

Recorded, not treated as blockers. Items marked **incorporated** are already reflected in the text above; the rest are P3-D2 build or test obligations.

| # | Note | Disposition |
|---|---|---|
| 1 | Direct module-level 555/542 regression assertion | **P3-D2 / P3-D1 test obligation.** The value is currently proved through the `adjust` helper; add a bare `adjust_escrow(...)` call asserting `opponent_final_cents == 555` and `refund_opponent_cents == 542` so the regression survives a helper refactor |
| 2 | Direct `p2o` half-up fixture | **P3-D1 test obligation.** Present coverage proves `math.floor(x+0.5)` differs from `round()`; add one assertion pinning a specific `p2o(p)` at a tie boundary so the claim is about the function, not about a builtin |
| 3 | Assert raw capped Derived values and `ceiling_applied` | **Incorporated** in the §9.0 table (raw 2142 and 9285 against the 1097 ceiling, `capped` column). Also a P3-D2 assertion obligation |
| 4 | Name exact Bet escrow account topology | **Incorporated** — §7.1 now names `escrow:{anchor_bet_id}` and `escrow:{derived_bet_id}` |
| 5 | Record refund-before-migration ordering as load-bearing | **Incorporated** — §5.1, steps 5 before 7, with the reason stated |
| 6 | Editorial: "three guards" → "four guards" | **Incorporated** — §7.1 now reads four, matching the four it names (2, 3, 5, 6) |
| 7 | Document claim-table interaction in lock-order notes | **Incorporated** — §5.2 states the claim row is never held while a challenge or Wallet row is locked and adds no edge to the lock graph |
| 8 | Record that reclaim must refresh `claim_expires_at` | **Incorporated** — §5.2, in the SQL and called out as load-bearing, with the third-worker failure mode named |
| 9 | Specify writer for `protocol_event_id` | **Incorporated** — §5.2 field comment: written by Phase 2 step 10 only, never at acquisition or reclaim |
| 10 | Preserve Phase 2 as one transaction | **Incorporated** — §5.1 states it and forbids splitting for progress reporting; §5.3 gives the reason `in_progress` is not a state |

---

# REV8 → REV9 CHANGELOG

| # | Change | Location |
|---|---|---|
| **1** | **Issuer Final-Lock precondition restored to strict equality.** §2 invariant 3 now requires `escrow_balance(issuer) == recorded_ceiling(issuer)` and `escrow_balance(opponent) == recorded_ceiling(opponent)`, both exact. The Rev 8 issuer-side `>=` allowance is removed. | §2 guard 3 |
| **2** | **Deployment-dependent `>=` language removed.** The phrase "where the deployment permits such an overshoot" is deleted, and §2 guard 3 now states affirmatively that the strictness does not vary by deployment, league, environment or configuration. An issuer balance above its recorded ceiling at Final Lock is declared an invariant violation that must fail loud and post nothing, with an explicit prohibition on normalizing or refunding unexplained excess escrow. | §2 guard 3 |
| **3** | **Overshoot row retained as a pure-function-only fixture.** All arithmetic values preserved (issuer escrow 5250¢, Anchor 5000¢, opponent escrow 1097¢, p_iss 0.90, refunds 250¢ and 542¢). Moved out of the production branch table into a separately headed §9.0a labelled `PURE-FUNCTION FIXTURE ONLY — NOT A LEGITIMATE P3-D2 TRANSACTION STATE`. Its compliance cell no longer shows a passing `issuer >=` condition; it now shows **✗ FAILS — INVALID TRANSACTION STATE (OVERSHOOT-B)**. What it does and does not establish is enumerated, and its correct home is named as the P3-D1 pure-function suite. | §9.0a, §9.2 |
| **4** | **Production both-positive state declared unreachable and fail-loud.** MS-SIM-9(b) final wording splits the mathematical statement from the production-state statement and keeps them apart: reachable in the pure function; unreachable in the authorized lifecycle because issuer escrow equals the Anchor at Handshake exit and the window contains no authorized escrow writer. Odds movement never creates an issuer refund; §2 guard 5 notes there is no issuer refund pair in the legitimate path; §7.4's Rev 8 line directing an auditor to "audit funding history" is corrected to "refuse the transaction"; §5.1 step 4 no longer contemplates an issuer branch. | §2 (MS-SIM-9(b), guards 4 and 5), §5.1, §7.4, §9.2 |
| **5** | **No P3-D1 code change required.** `adjust_escrow` keeps its current behaviour, which Opus confirmed as correct. The correction is entirely in what the P3-D2 caller may accept as an entry state; §4 now states that guard 3 is the caller's obligation, not the function's. Commit `79a81cf5` stands. | §2, §4 |
| 6 | **Composition note added (flagged for confirmation).** Strict equality binds only because `recorded_ceiling(issuer) == anchor`, ruled at §5. Stated as guard 3a, because guard 3 alone would permit an inflated recorded ceiling to reproduce the outlawed state through a different door. | §2 guard 3a, §5 |
| 7 | Ten Opus non-blocking notes recorded; six incorporated inline, four carried as P3-D2/P3-D1 obligations. | §11 |
| 8 | §8 reduced to a record of Round 3's outcome; no confirmed target resubmitted. | §8 |

**Preserved unchanged (all Opus-confirmed):** 555¢/542¢ Favorite-better; canonical `fairPotFinal = anchor / p_issuer_final`; fixed Anchor; Derived-only odds repricing; opponent ceiling as the load-bearing no-increase guard; single-floor Derived rounding; no authoritative residue cents; ESCROW-A; forward migration with no reverse funding leg; reconciliation scope ending at Handshake; FINALSTATE-A; dedicated `ChallengeFinalLockClaim`; `UNIQUE(challenge_id)`; fresh `INSERT ... ON CONFLICT DO NOTHING`; conditional in-place reclaim; 15-minute TTL; system-worker-only reclaim; the three claim states `claimed` / `completed` / `failed`; elimination of `in_progress`; the crash matrix; `ProtocolEvent.event_id` as delivery identity only; the two-phase Final-Lock transaction; Challenge → Wallet lock rank; every other previously accepted MS-SIM finding.

---

# OPUS ROUND 3 CORRECTION CONFIRMATION REQUEST

**Document:** `SIMULATION_ENGINE_MODULE_SPEC_Rev9.md`
**Predecessor:** Rev 8, rejected on one point (OVERSHOOT-B)
**Scope of this request: B-1 and B-2 only.** Do not re-review any finding confirmed in Round 3. No other section is reopened.

Please confirm only whether the two required corrections are made:

**B-1 — Final-Lock first-entry precondition.** Is the issuer-side precondition restored to strict equality, with all deployment-dependent `>=` language removed, and is an issuer balance above its recorded ceiling now declared an invariant violation that fails loud and posts nothing rather than being normalized or refunded? (§2 guard 3, and the guard 3a composition note added to make the equality actually bind.)

**B-2 — True-up overshoot fixture.** Is the fixture retained with its arithmetic intact, reclassified as `PURE-FUNCTION FIXTURE ONLY — NOT A LEGITIMATE P3-D2 TRANSACTION STATE`, removed from the production branch table, and shown as failing the transaction-state invariant rather than passing an `issuer >=` condition? (§9.0a, §9.2.)

**Please return exactly one:**

- **ACCEPT**
- **REJECT — CORRECTION REQUIRED**

If accepted, please state exactly:

**MS-SIM ROUND 3 COMPLETE — P3-D2 AUTHORIZED**
