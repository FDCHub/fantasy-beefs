"""
odds/dynamic_pricing.py — P3-D1 / SIMULATION ENGINE Rev 7: the pure Dynamic
pricing math.

WHAT THIS MODULE IS. The asymmetric pricing law for Dynamic wagers, as pure
functions. No database, no ledger, no session, no commit, no I/O. Everything
here is a total function of its arguments, which is what lets the math be frozen
and verified before any money transaction is built on it (P3-D2).

THE WAGER MODEL (Rev 7 spine — read this first). A Dynamic Challenge is
ASYMMETRIC. The issuer commits a fixed amount, the Anchor Stake: "I'm putting up
$X." Dynamic pricing then determines how much the OPPONENT must risk against
that fixed commitment, capped at the opponent's Handshake ceiling. The opponent's
stake is the ONLY odds-derived stake. At Final Lock the engine re-derives the
OPPONENT's stake from final probabilities and caps it; the issuer's stake never
moves on odds.

    fairPotFinal    = anchor / p_issuer_final
    issuerFinal     = anchor                                  # never floored
    opponentDerived = floor(fairPotFinal * p_opponent_final)  # ONLY this floors
    opponentFinal   = min(opponentDerived, opponent_ceiling)

THE CEILING IS LOAD-BEARING, NOT DECORATIVE (MS-SIM-11). It is tempting to read
the cap as a belt-and-braces limit that the derivation would respect anyway. It
would not. When the issuer's probability WORSENS, the derivation mathematically
demands a LARGER opponent stake — at p_issuer 0.82 -> 0.70 on a 5000c anchor the
raw derivation asks 2142c against a 1097c ceiling. The immutable ceiling is what
caps it back down. Remove or "optimize away" the cap and the pot grows, charging
a GM above the commitment they agreed to. Rev 7 §0: the ceiling, not the
derivation, is the no-increase guard.

THE ISSUER NEVER REPRICES ON ODDS. `refund_issuer` is STRUCTURALLY zero whenever
the issuer's escrow equals the accepted anchor, because `issuer_final` IS the
anchor. An issuer refund can arise only if a separate true-up left the issuer's
escrow above the accepted anchor — a funding-correctness event, never an odds
event. Three independent authorities agree: Rev 7's spine, Rev 7 §2's canonical
derivation, and the Locked-vs-Dynamic ruling §5.3 (cleared 2026-07-19: "Your
stake stays put — but if the odds shift, your opponent's stake can come down
(never up, never past the max set now)").

NO AUTHORITATIVE RESIDUE CENTS (MS-SIM-4 / Rev 7 §3). `fairPot * p_opponent`
before flooring may carry a fraction of a cent. That fraction is NEVER funded —
never escrowed, never posted, never refunded, never was BAB. It is not
"stranded" or "destroyed"; it never existed as money. There is deliberately no
`residue_cents` field anywhere in this module: an integer-cent name implies a
postable cent. Where audit math wants the value, `residue_decimal` on the result
is DIAGNOSTIC ONLY and must never reach a posting.

WHY THIS MODULE DOES NOT REUSE `odds_engine_headless._prob_to_american`. That
function is a different, non-interchangeable conversion: it clamps probability
into [0.001, 0.999] and treats ONLY exactly 0.5 as even money. Rev 7 §2 certifies
a distinct pair (`o2p`/`p2o`) from the Odds Calculator Rev 1.9 reference, whose
even-money branch is a BAND, |p - 0.5| < 0.0001, and which returns magnitude and
sign separately. Porting Rev 7's certified behaviour is the requirement ("port
their behavior exactly; do not re-derive"), so the two coexist rather than one
being expressed through the other. The simulation core (`run`, `simulate_scores`,
`PlayerProj`, `N_SIMS`) is NOT duplicated here — P3-D2 calls it directly and
feeds its probabilities in.

FLOAT DISCIPLINE. The derivation is float64 because probabilities are float64,
exactly as the certified JS reference computes it; Python and JS share IEEE-754
double semantics, so the ported arithmetic is bit-identical. Everything that
CROSSES INTO MONEY is an integer cent, produced by a single floor on the derived
side. No float tolerance is used in any comparison against cents (Rev 7 §2: "No
float tolerance; integer cents, exact" — the JS 0.005 tolerance is a float
artifact, deliberately not ported).

SCOPE FENCE. This package is P3-D1. It contains no Handshake, no Final Lock, no
claim, no escrow movement, no schema and no lifecycle. Those are P3-D2.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ── Rev 7 constants ───────────────────────────────────────────────────────────

# §2 — p2o's even-money branch is a BAND, not an equality test. A probability
# within this distance of 0.5 prices as +100 rather than producing +/-100.00001
# style noise on either side of the pivot.
EVEN_MONEY_BAND = 0.0001

# §2 invariant 1 — "round(p_issuer_final + p_opponent_final, 6) == 1". Six
# decimal places is the ruled tolerance; it absorbs float representation error
# without admitting a genuinely mispriced pair.
PROBABILITY_SUM_DECIMALS = 6

# The even-money American price, returned as a positive magnitude.
EVEN_MONEY_MAGNITUDE = 100


# ── Errors ────────────────────────────────────────────────────────────────────

class DynamicPricingError(ValueError):
    """Base for every refusal in this module. Subclasses are distinct TYPES so
    callers and tests branch on type, never on message text."""


class InvalidProbabilityError(DynamicPricingError):
    """A probability is outside (0, 1), is not a real number, or the pair does
    not sum to 1 within the Rev 7 tolerance. Zero and one are BOTH rejected: a
    zero issuer probability makes `anchor / p_issuer` undefined, and a certainty
    is not a wager."""


class InvalidStakeError(DynamicPricingError):
    """A cent quantity is negative, non-integral, or an anchor is not positive.
    Money quantities are integer cents; a float cent is a category error here."""


class CeilingViolationError(DynamicPricingError):
    """The issuer's ceiling is below the fixed Anchor Stake.

    THIS IS NOT CLAMPED, DELIBERATELY. Rev 7 writes `issuerFinal = min(anchor,
    issuer_ceiling)` and immediately notes it "== anchor normally". Silently
    taking the min would reduce the issuer below the commitment they actually
    made and would mask an inconsistent Handshake write — the exact class of
    inconsistency Rev 7 §2 invariant 2 exists to catch AT THE SOURCE. The
    spec-defined cap applies to the OPPONENT's derived stake and to nothing
    else."""


class EscrowShortfallError(DynamicPricingError):
    """A side's live escrow is below its calculated final exposure, so the
    Adjustment would require COLLECTING more money at Final Lock.

    Final Lock refunds; it never collects. Rev 7 §2 invariant 4 states both
    refunds are non-negative, and the whole reason the Handshake funds each
    side's MAXIMUM exposure is so that Final Lock can only ever hand money
    back. A negative refund means an upstream funding error, not a legitimate
    top-up, so this fails loud and posts nothing."""


# ── Results ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StakePair:
    """One Handshake-time derivation. All fields integer cents."""
    issuer_cents:     int
    opponent_cents:   int
    funded_pot_cents: int
    # DIAGNOSTIC ONLY — never postable, never authoritative. See the module
    # docstring on why there is no `residue_cents`.
    fair_pot_decimal: float = 0.0
    residue_decimal:  float = 0.0


@dataclass(frozen=True)
class AdjustmentResult:
    """The Final-Lock Adjustment (Rev 7 §2/§4). All cent fields are integers.

    `opponent_derived_raw_cents` is the derivation BEFORE the ceiling cap. It is
    exposed because it is the evidence that the cap did work: when the issuer
    worsens, this exceeds the ceiling and `opponent_final_cents` does not. A test
    that asserts only the capped value cannot tell a working cap from a
    derivation that never needed one.
    """
    issuer_final_cents:         int
    opponent_final_cents:       int
    refund_issuer_cents:        int
    refund_opponent_cents:      int
    final_funded_escrow_cents:  int
    opponent_derived_raw_cents: int
    ceiling_applied:            bool
    # DIAGNOSTIC ONLY — never postable, never authoritative.
    fair_pot_decimal:           float = 0.0
    residue_decimal:            float = 0.0


# ── Validation helpers ────────────────────────────────────────────────────────

def _require_cents(value: int, name: str, *, positive: bool = False) -> int:
    """Money is integer cents. `bool` is rejected explicitly because it is an
    `int` subclass in Python and `True` silently meaning 1 cent is not a
    behaviour any money path should inherit."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidStakeError(
            f"{name} must be an integer number of cents; got {value!r} "
            f"({type(value).__name__}).")
    if positive and value <= 0:
        raise InvalidStakeError(f"{name} must be positive; got {value}.")
    if not positive and value < 0:
        raise InvalidStakeError(f"{name} must not be negative; got {value}.")
    return value


def _require_probability(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidProbabilityError(
            f"{name} must be a real number; got {value!r} "
            f"({type(value).__name__}).")
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        raise InvalidProbabilityError(f"{name} must be finite; got {value!r}.")
    # Strict bounds: 0 makes fairPot undefined, 1 leaves the opponent nothing to
    # price. Neither is a wager.
    if not (0.0 < value < 1.0):
        raise InvalidProbabilityError(
            f"{name} must lie strictly between 0 and 1; got {value}.")
    return value


def _require_complementary(p_issuer: float, p_opponent: float) -> None:
    """§2 invariant 1 — the pair must describe one market."""
    if round(p_issuer + p_opponent, PROBABILITY_SUM_DECIMALS) != 1:
        raise InvalidProbabilityError(
            f"Probabilities must sum to 1 within {PROBABILITY_SUM_DECIMALS} "
            f"decimal places; got p_issuer={p_issuer} + "
            f"p_opponent={p_opponent} = {p_issuer + p_opponent}."
        )


# ── §2 Certified odds <-> probability conversion ──────────────────────────────

def o2p(odds: int, is_neg: bool) -> float:
    """American odds -> implied probability (certified Rev 1.9, ported as-is).

        is_neg ? odds/(odds+100) : 100/(odds+100)

    `odds` is the MAGNITUDE and `is_neg` carries the sign, mirroring the
    reference's two-argument shape. NO VIG is applied or removed: this is the
    fair conversion, and a favourite/underdog pair produced by `p2o` converts
    back to probabilities summing to 1 up to integer-rounding of the price.
    """
    if isinstance(odds, bool) or not isinstance(odds, int):
        raise InvalidStakeError(
            f"odds must be an integer magnitude; got {odds!r}.")
    if odds <= 0:
        raise InvalidStakeError(
            f"odds must be a positive magnitude with the sign carried by "
            f"is_neg; got {odds}.")
    if is_neg:
        return odds / (odds + 100)
    return 100 / (odds + 100)


def p2o(p: float) -> tuple[int, bool]:
    """Probability -> American odds, as (magnitude, is_negative).

        |p - 0.5| < 0.0001  -> (100, False)          # even money, a BAND
        p > 0.5             -> (round(p/(1-p)*100), True)
        else                -> (round((1-p)/p*100), False)

    ROUNDING IS HALF-UP, NOT PYTHON'S DEFAULT. The reference is JavaScript, whose
    `Math.round` rounds a .5 fraction away from zero, while Python's built-in
    `round` is banker's rounding (round-half-to-even): `round(162.5)` is 162 in
    Python and 163 in JS. A price landing exactly on .5 is reachable, so the
    ported behaviour is spelled out here rather than inherited from whichever
    language happens to run it. All magnitudes are positive, so `floor(x + 0.5)`
    is exactly JS's rule.
    """
    p = _require_probability(p, "p")
    if abs(p - 0.5) < EVEN_MONEY_BAND:
        return EVEN_MONEY_MAGNITUDE, False
    if p > 0.5:
        return math.floor(p / (1 - p) * 100 + 0.5), True
    return math.floor((1 - p) / p * 100 + 0.5), False


# ── §2 Asymmetric stake derivation (FR-8.2 / FR-8.3) ──────────────────────────

def derive_stakes(anchor_cents: int, p_issuer: float,
                  p_opponent: float) -> StakePair:
    """The pricing law. The issuer enters whole cents; only the opponent floors.

        fairPot        = anchor / p_issuer
        issuer_stake   = anchor                       # NOT re-floored
        opponent_stake = floor(fairPot * p_opponent)  # FR-8.3, the only floor

    The favourite risks more. There is no "size me at" toggle — declining is the
    opponent's protection.

    This is the Handshake-time derivation. Its `opponent_cents` is precisely what
    becomes the opponent's Handshake ceiling, which is why an unchanged-odds
    Final Lock is an exact fixed point with zero refund (see `adjust_escrow`).
    """
    _require_cents(anchor_cents, "anchor_cents", positive=True)
    p_issuer   = _require_probability(p_issuer,   "p_issuer")
    p_opponent = _require_probability(p_opponent, "p_opponent")
    _require_complementary(p_issuer, p_opponent)

    fair_pot        = anchor_cents / p_issuer
    opponent_exact  = fair_pot * p_opponent
    opponent_cents  = math.floor(opponent_exact)

    return StakePair(
        issuer_cents     = anchor_cents,          # fixed, never floored
        opponent_cents   = opponent_cents,
        funded_pot_cents = anchor_cents + opponent_cents,
        fair_pot_decimal = fair_pot,
        residue_decimal  = opponent_exact - opponent_cents,   # diagnostic only
    )


# ── §2 The Adjustment (Dynamic only, once at Final Lock) ──────────────────────

def adjust_escrow(
    *,
    anchor_cents: int,
    p_issuer_final: float,
    p_opponent_final: float,
    issuer_ceiling_cents: int,
    opponent_ceiling_cents: int,
    issuer_escrow_balance_cents: int,
    opponent_escrow_balance_cents: int,
) -> AdjustmentResult:
    """Re-run the asymmetric derivation on final-lineup probabilities.

    It does NOT reallocate a pot — the frozen-pot model was removed (MS-SIM-7).
    The issuer's Anchor Stake is fixed; only the opponent's Derived Stake
    reprices, capped at its Handshake ceiling. Refunds come from ACTUAL escrow
    balances, which is why both live balances are arguments rather than assumed.

        fairPotFinal    = anchor / p_issuer_final
        issuerFinal     = anchor
        opponentDerived = floor(fairPotFinal * p_opponent_final)
        opponentFinal   = min(opponentDerived, opponent_ceiling)
        refund_issuer   = issuer_escrow   - issuerFinal      # structurally 0
        refund_opponent = opponent_escrow - opponentFinal

    BEHAVIOUR BY BRANCH. If the issuer's win probability IMPROVES, the opponent's
    fair stake shrinks below its ceiling and the opponent is refunded. If it
    WORSENS, the opponent's fair stake would rise above its ceiling, so the cap
    holds it at the ceiling and neither side is refunded — the issuer, having
    committed the anchor, carries that fixed exposure regardless. Unchanged
    probabilities reproduce the Handshake calculation exactly: zero refund on
    both sides, with no 1-cent artifact (that artifact belonged to the removed
    frozen-pot model, where a double floor made "no change" not a fixed point).

    EVERY GUARD FAILS LOUD AND RETURNS NOTHING. A caller that gets a result has a
    result whose invariants all held; there is no partially-valid Adjustment.
    """
    # ── invariant inputs ──────────────────────────────────────────────────
    _require_cents(anchor_cents, "anchor_cents", positive=True)
    _require_cents(issuer_ceiling_cents,          "issuer_ceiling_cents")
    _require_cents(opponent_ceiling_cents,        "opponent_ceiling_cents")
    _require_cents(issuer_escrow_balance_cents,   "issuer_escrow_balance_cents")
    _require_cents(opponent_escrow_balance_cents, "opponent_escrow_balance_cents")

    # (1) probabilities valid and complementary
    p_issuer_final   = _require_probability(p_issuer_final,   "p_issuer_final")
    p_opponent_final = _require_probability(p_opponent_final, "p_opponent_final")
    _require_complementary(p_issuer_final, p_opponent_final)

    # (3) the issuer's ceiling must be able to hold the fixed anchor. Not
    # clamped — see CeilingViolationError.
    if issuer_ceiling_cents < anchor_cents:
        raise CeilingViolationError(
            f"Issuer ceiling {issuer_ceiling_cents} is below the fixed Anchor "
            f"Stake {anchor_cents}. The anchor never reprices, so a ceiling "
            f"beneath it is an inconsistent Handshake, not a cap to apply."
        )

    # ── the derivation ────────────────────────────────────────────────────
    fair_pot        = anchor_cents / p_issuer_final
    opponent_exact  = fair_pot * p_opponent_final
    opponent_raw    = math.floor(opponent_exact)          # FR-8.3, single floor

    issuer_final    = anchor_cents                        # (2) fixed, unfloored
    opponent_final  = min(opponent_raw, opponent_ceiling_cents)   # spec-defined cap
    ceiling_applied = opponent_raw > opponent_ceiling_cents

    # (4) the cap is what makes this true; assert it rather than trust it.
    if opponent_final > opponent_ceiling_cents:
        raise CeilingViolationError(
            f"Opponent final {opponent_final} exceeds the Handshake ceiling "
            f"{opponent_ceiling_cents}. The pot may never grow.")
    # (2)/(3) restated as assertions on the computed result.
    if issuer_final != anchor_cents:
        raise CeilingViolationError(
            f"Issuer final {issuer_final} is not the fixed Anchor "
            f"{anchor_cents}; the anchor must never reprice.")
    if issuer_final > issuer_ceiling_cents:
        raise CeilingViolationError(
            f"Issuer final {issuer_final} exceeds the issuer ceiling "
            f"{issuer_ceiling_cents}.")

    # ── refunds ───────────────────────────────────────────────────────────
    refund_issuer   = issuer_escrow_balance_cents   - issuer_final
    refund_opponent = opponent_escrow_balance_cents - opponent_final

    # (5)/(6)/(8) a negative refund is a collection, and Final Lock never
    # collects. Report the side by name so the caller knows which escrow is short.
    if refund_issuer < 0:
        raise EscrowShortfallError(
            f"Issuer escrow {issuer_escrow_balance_cents} is below the required "
            f"final exposure {issuer_final}; Final Lock would have to COLLECT "
            f"{-refund_issuer} more cents. Final Lock only refunds."
        )
    if refund_opponent < 0:
        raise EscrowShortfallError(
            f"Opponent escrow {opponent_escrow_balance_cents} is below the "
            f"required final exposure {opponent_final}; Final Lock would have to "
            f"COLLECT {-refund_opponent} more cents. Final Lock only refunds."
        )

    # (7) "the issuer's odds-driven refund is structurally zero when the issuer's
    # escrow equals the Anchor" is a THEOREM here, not a runtime condition, and
    # it deliberately carries no guard of its own.
    #
    # Once `issuer_final == anchor_cents` is established above, `refund_issuer`
    # is `issuer_escrow - anchor_cents` by construction, so `issuer_escrow ==
    # anchor_cents` forces `refund_issuer == 0` algebraically. A branch testing
    # for the contradiction could never fire on any input, and a guard that
    # cannot fail protects nothing while reading as though it does — it inflates
    # the apparent invariant count and invites a future reader to trust it.
    #
    # The rule it appears to protect is genuinely enforced in two places that CAN
    # fail: the `issuer_final != anchor_cents` check above, which fires the
    # moment the anchor is made odds-derived, and the cross-probability sweep in
    # the P3-D1 suite (ANCHOR-3), which is the actual discriminating evidence —
    # it re-derives at 91 distinct probabilities and asserts the issuer's final
    # exposure and refund never move. Invariance under changing odds cannot be
    # observed from inside a single call; only a sweep can see it.

    return AdjustmentResult(
        issuer_final_cents         = issuer_final,
        opponent_final_cents       = opponent_final,
        refund_issuer_cents        = refund_issuer,
        refund_opponent_cents      = refund_opponent,
        final_funded_escrow_cents  = issuer_final + opponent_final,
        opponent_derived_raw_cents = opponent_raw,
        ceiling_applied            = ceiling_applied,
        fair_pot_decimal           = fair_pot,
        residue_decimal            = opponent_exact - opponent_raw,  # diagnostic
    )
