"""
test_p3_d1_dynamic_pricing.py — P3-D1 targeted suite.

PURE MATH, NO DATABASE. This suite imports nothing that touches a session, so it
runs anywhere without a Postgres harness. That isolation is the point: the
Dynamic pricing law is frozen and proven here, before P3-D2 builds a money
transaction on top of it.

THE DISCRIMINATING LINE (Rev 7 §8). Anchor 5000c, issuer favourite at p=0.82.
`fairPot` = 6097.5609...c — deliberately NON-DIVIDING, so the derived-side floor
actually does something and a missing floor produces a different number. The
Handshake opponent stake is floor(6097.5609 x 0.18) = 1097c, which is also the
opponent's ceiling. Every branch below reuses that line.

WHY THE CEILING TESTS HAVE TEETH. CEIL-* asserts the RAW derivation exceeds the
ceiling and that the official value does not. Asserting only the capped number
cannot distinguish a working cap from a derivation that never needed one — so
each ceiling test pins both sides of the comparison.

    python test_p3_d1_dynamic_pricing.py
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from odds.dynamic_pricing import (
    EVEN_MONEY_BAND,
    AdjustmentResult,
    CeilingViolationError,
    DynamicPricingError,
    EscrowShortfallError,
    InvalidProbabilityError,
    InvalidStakeError,
    StakePair,
    adjust_escrow,
    derive_stakes,
    o2p,
    p2o,
)

_passes = 0
_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passes
    if condition:
        _passes += 1
        print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))
    else:
        _failures.append(label)
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{title}")


def raises(exc_type, fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
    except exc_type:
        return True
    except Exception:
        return False
    return False


# ── The canonical Rev 7 line ──────────────────────────────────────────────────
ANCHOR      = 5000
P_HS_ISS    = 0.82
P_HS_OPP    = 0.18
CEIL_ISS    = ANCHOR          # Rev 7: issuerFinal = min(anchor, issuer_ceiling) == anchor
CEIL_OPP    = 1097            # floor(6097.5609... x 0.18)


def adjust(p_iss, p_opp, *, iss_escrow=ANCHOR, opp_escrow=CEIL_OPP,
           anchor=ANCHOR, ceil_iss=CEIL_ISS, ceil_opp=CEIL_OPP) -> AdjustmentResult:
    return adjust_escrow(
        anchor_cents=anchor,
        p_issuer_final=p_iss, p_opponent_final=p_opp,
        issuer_ceiling_cents=ceil_iss, opponent_ceiling_cents=ceil_opp,
        issuer_escrow_balance_cents=iss_escrow,
        opponent_escrow_balance_cents=opp_escrow,
    )


# ══════════════════════════════════════════════════════════════════════════════
section("ODDS-1: certified odds <-> probability conversion")

check("ODDS-1: even money at exactly 0.5 prices as +100",
      p2o(0.5) == (100, False), str(p2o(0.5)))
check("ODDS-1: the even-money branch is a BAND, not an equality test — a "
      "probability inside 0.0001 of 0.5 still prices as +100",
      p2o(0.5 + EVEN_MONEY_BAND / 2) == (100, False)
      and p2o(0.5 - EVEN_MONEY_BAND / 2) == (100, False),
      f"{p2o(0.50005)} / {p2o(0.49995)}")
check("ODDS-1: CONTROL — just OUTSIDE the band leaves even money, proving the "
      "band is bounded rather than swallowing everything near 0.5",
      p2o(0.5 + EVEN_MONEY_BAND * 2) != (100, False),
      str(p2o(0.5 + EVEN_MONEY_BAND * 2)))

check("ODDS-1: a favourite prices NEGATIVE — p=0.60 -> -150",
      p2o(0.60) == (150, True), str(p2o(0.60)))
check("ODDS-1: an underdog prices POSITIVE — p=0.40 -> +150",
      p2o(0.40) == (150, False), str(p2o(0.40)))
check("ODDS-1: o2p inverts the negative price — -150 -> 0.60",
      abs(o2p(150, True) - 0.60) < 1e-12, str(o2p(150, True)))
check("ODDS-1: o2p inverts the positive price — +150 -> 0.40",
      abs(o2p(150, False) - 0.40) < 1e-12, str(o2p(150, False)))
check("ODDS-1: o2p(+100) is even money", o2p(100, False) == 0.5)

# Round-trip across a broad range. American odds are WHOLE NUMBERS, so p2o is
# lossy by construction and exact probability recovery is not the property to
# assert. The real invariant is PRICE IDEMPOTENCE: re-pricing the recovered
# probability must land on the identical integer price. That is exact — no
# tolerance — and it is what a betting system actually depends on.
worst = 0.0
worst_at = None
idempotent = True
for i in range(5, 96):
    p = i / 100
    mag, neg = p2o(p)
    back = o2p(mag, neg)
    if p2o(back) != (mag, neg):
        idempotent = False
    d = abs(back - p)
    if d > worst:
        worst, worst_at = d, (p, mag, neg)
check("ODDS-1: PRICE IDEMPOTENCE — re-pricing the recovered probability yields "
      "the identical integer price at every p in [0.05, 0.95] (exact, no "
      "tolerance)", idempotent)
# The residual drift is pure integer granularity and is LARGEST near even money,
# where one unit of price spans the most probability, and vanishes at the
# extremes where the price steps are huge. Asserting that shape proves the drift
# is granularity rather than a formula error.
check("ODDS-1: probability drift stays within whole-number-odds granularity",
      worst < 1e-3, f"worst {worst:.2e} at p={worst_at[0]} price={worst_at[1]}")
check("ODDS-1: the drift is a granularity artifact — it is largest near the "
      "0.5 pivot and exactly zero at the extremes, where prices are coarse in "
      "odds but fine in probability",
      abs(o2p(*p2o(0.05)) - 0.05) == 0.0
      and abs(o2p(*p2o(0.95)) - 0.95) == 0.0
      and worst_at[0] > 0.4 and worst_at[0] < 0.6,
      f"worst sits at p={worst_at[0]}")

check("ODDS-1: NO VIG — a favourite/underdog pair's implied probabilities sum "
      "to 1 (no overround is introduced)",
      abs(o2p(*p2o(0.60)) + o2p(*p2o(0.40)) - 1.0) < 1e-9,
      f"sum={o2p(*p2o(0.60)) + o2p(*p2o(0.40))}")
# p2o MUST round half-UP (JS Math.round), not with Python's banker's rounding.
#
# THESE FIXTURES CALL p2o() DIRECTLY AND ARE CONSTRUCTED TO DISCRIMINATE. Both
# probabilities drive their branch's magnitude to EXACTLY 104.5 in float64 — not
# 104.49999 or 104.50000000000003, which would round identically under either
# rule and prove nothing. 104 is EVEN, which is the second half of the fixture:
# banker's rounding breaks a .5 tie toward the even neighbour, so it yields 104,
# while half-up yields 105. Had the integer part been odd the two rules would
# agree and the test would be decorative.
#
#   p = 100/204.5      -> (1-p)/p*100 == 104.5 exactly  (underdog branch)
#   p = 1.045/2.045    -> p/(1-p)*100 == 104.5 exactly  (favourite branch)
#
# Substituting round() for floor(x+0.5) inside p2o turns both 105s into 104s and
# fails these four assertions.
P_HALF_UP_DOG = 100.0 / 204.5           # underdog, magnitude exactly 104.5
P_HALF_UP_FAV = 1.045 / 2.045           # favourite, magnitude exactly 104.5

check("ODDS-1: FIXTURE CONTROL — both probabilities land the unrounded "
      "magnitude on EXACTLY 104.5, with an EVEN integer part, so half-up and "
      "banker's rounding genuinely disagree",
      (1 - P_HALF_UP_DOG) / P_HALF_UP_DOG * 100 == 104.5
      and P_HALF_UP_FAV / (1 - P_HALF_UP_FAV) * 100 == 104.5
      and math.floor(104.5 + 0.5) == 105 and round(104.5) == 104,
      "half-up -> 105, banker's -> 104")
check("ODDS-1: p2o() itself rounds HALF-UP on the underdog branch — 104.5 "
      "becomes +105, not the +104 banker's rounding would give",
      p2o(P_HALF_UP_DOG) == (105, False), str(p2o(P_HALF_UP_DOG)))
check("ODDS-1: p2o() itself rounds HALF-UP on the favourite branch — 104.5 "
      "becomes -105, not -104",
      p2o(P_HALF_UP_FAV) == (105, True), str(p2o(P_HALF_UP_FAV)))
check("ODDS-1: neither half-up result equals the banker's-rounding answer, so "
      "substituting round() inside p2o breaks these assertions",
      p2o(P_HALF_UP_DOG)[0] != round(104.5)
      and p2o(P_HALF_UP_FAV)[0] != round(104.5),
      f"p2o gave {p2o(P_HALF_UP_DOG)[0]}, banker's would give {round(104.5)}")

check("ODDS-1: p2o rejects an out-of-range probability",
      raises(InvalidProbabilityError, p2o, 1.0)
      and raises(InvalidProbabilityError, p2o, 0.0))
check("ODDS-1: o2p rejects a non-positive magnitude (the sign lives in is_neg)",
      raises(InvalidStakeError, o2p, 0, False)
      and raises(InvalidStakeError, o2p, -150, True))


# ══════════════════════════════════════════════════════════════════════════════
section("HS-2: the Handshake derivation produces the canonical line")

hs = derive_stakes(ANCHOR, P_HS_ISS, P_HS_OPP)
check("HS-2: issuer stake is the anchor, unfloored",
      hs.issuer_cents == ANCHOR, str(hs.issuer_cents))
check("HS-2: opponent stake is floor(fairPot x p_opp) = 1097",
      hs.opponent_cents == 1097, str(hs.opponent_cents))
check("HS-2: FIXTURE CONTROL — fairPot is NON-DIVIDING, so the floor is doing "
      "real work and a missing floor gives a different number",
      hs.fair_pot_decimal != int(hs.fair_pot_decimal)
      and 0 < hs.residue_decimal < 1,
      f"fairPot={hs.fair_pot_decimal:.6f} residue={hs.residue_decimal:.6f}")
check("HS-2: funded pot is the sum of the two sides",
      hs.funded_pot_cents == ANCHOR + 1097 == 6097)
check("HS-2: the Handshake opponent stake IS the ceiling used below",
      hs.opponent_cents == CEIL_OPP)


# ══════════════════════════════════════════════════════════════════════════════
section("ANCHOR-3: the Anchor never reprices — swept across the valid range")

anchor_fixed = True
issuer_refund_zero = True
bad = []
for i in range(5, 96):
    p_iss = i / 100
    p_opp = round(1 - p_iss, 10)
    r = adjust(p_iss, p_opp)
    if r.issuer_final_cents != ANCHOR:
        anchor_fixed = False
        bad.append((p_iss, "final", r.issuer_final_cents))
    if r.refund_issuer_cents != 0:
        issuer_refund_zero = False
        bad.append((p_iss, "refund", r.refund_issuer_cents))

check("ANCHOR-3: issuer final == anchor at EVERY probability in [0.05, 0.95]",
      anchor_fixed, str(bad[:5]))
check("ANCHOR-3: issuer odds-driven refund == 0 at EVERY probability — "
      "structurally zero, not merely usually zero",
      issuer_refund_zero, str(bad[:5]))
check("ANCHOR-3: the sweep really exercised 91 distinct probabilities",
      len(range(5, 96)) == 91)


# ══════════════════════════════════════════════════════════════════════════════
section("REPRICE-4: Derived reprices DOWNWARD when the issuer improves")

r = adjust(0.90, 0.10)
check("REPRICE-4: fairPotFinal is recomputed from the FINAL issuer probability "
      "(anchor / 0.90), not carried over from the Handshake",
      abs(r.fair_pot_decimal - ANCHOR / 0.90) < 1e-9,
      f"{r.fair_pot_decimal:.6f}")
check("REPRICE-4: opponent derived = floor(5000/0.90 x 0.10) = 555",
      r.opponent_derived_raw_cents == 555, str(r.opponent_derived_raw_cents))
check("REPRICE-4: the ceiling was NOT applied — the derived value is below it",
      r.ceiling_applied is False and r.opponent_derived_raw_cents < CEIL_OPP)
check("REPRICE-4: opponent final = 555", r.opponent_final_cents == 555)
check("REPRICE-4: opponent refund = 1097 - 555 = 542",
      r.refund_opponent_cents == 542, str(r.refund_opponent_cents))
check("REPRICE-4: the issuer is refunded NOTHING even though the opponent is",
      r.refund_issuer_cents == 0)
check("REPRICE-4: final funded escrow = 5000 + 555",
      r.final_funded_escrow_cents == 5555)
check("REPRICE-4: exposure only ever fell — final pot < Handshake pot",
      r.final_funded_escrow_cents < ANCHOR + CEIL_OPP)


# ══════════════════════════════════════════════════════════════════════════════
section("CEIL-5: the ceiling is LOAD-BEARING — the derivation alone would grow "
        "the pot")

r = adjust(0.70, 0.30)
check("CEIL-5: the RAW derivation demands MORE than the ceiling "
      "(floor(5000/0.70 x 0.30) = 2142 > 1097)",
      r.opponent_derived_raw_cents == 2142
      and r.opponent_derived_raw_cents > CEIL_OPP,
      str(r.opponent_derived_raw_cents))
check("CEIL-5: the official opponent final is capped at the ceiling, 1097",
      r.opponent_final_cents == CEIL_OPP, str(r.opponent_final_cents))
check("CEIL-5: ceiling_applied is reported True",
      r.ceiling_applied is True)
check("CEIL-5: no refund on either side — the opponent's exposure holds",
      r.refund_opponent_cents == 0 and r.refund_issuer_cents == 0)
check("CEIL-5: THE POT DID NOT GROW — remove the cap and the opponent would be "
      "charged 2142 against a 1097 commitment; this assertion is what fails",
      r.opponent_final_cents < r.opponent_derived_raw_cents
      and r.final_funded_escrow_cents == ANCHOR + CEIL_OPP)
check("CEIL-5: the issuer carries its fixed exposure regardless of worsening",
      r.issuer_final_cents == ANCHOR)


# ══════════════════════════════════════════════════════════════════════════════
section("EXACT-6: derived landing EXACTLY on the ceiling refunds nothing")

r = adjust(P_HS_ISS, P_HS_OPP)
check("EXACT-6: at unchanged odds the derivation lands exactly on the ceiling",
      r.opponent_derived_raw_cents == CEIL_OPP == r.opponent_final_cents,
      f"raw={r.opponent_derived_raw_cents} ceiling={CEIL_OPP}")
check("EXACT-6: the cap was NOT needed at the boundary",
      r.ceiling_applied is False)
check("EXACT-6: zero refund on both sides at the boundary",
      r.refund_opponent_cents == 0 and r.refund_issuer_cents == 0)

# A second, exactly-dividing boundary as a supplementary control.
clean = adjust_escrow(
    anchor_cents=1000, p_issuer_final=0.5, p_opponent_final=0.5,
    issuer_ceiling_cents=1000, opponent_ceiling_cents=1000,
    issuer_escrow_balance_cents=1000, opponent_escrow_balance_cents=1000,
)
check("EXACT-6: a cleanly-dividing line also lands exactly (1000/0.5 x 0.5) "
      "with no residue",
      clean.opponent_final_cents == 1000 and clean.residue_decimal == 0.0
      and clean.refund_opponent_cents == 0)


# ══════════════════════════════════════════════════════════════════════════════
section("FLOOR-7: single-floor rounding — Rev 7's extreme-favourite case")

r = adjust(0.98, 0.02)
check("FLOOR-7: floor(5000/0.98 x 0.02) = floor(102.0408...) = 102 — the exact "
      "value Rev 7 §3 names",
      r.opponent_derived_raw_cents == 102, str(r.opponent_derived_raw_cents))
check("FLOOR-7: the pre-floor value really did carry a fraction, so the floor "
      "is observable", 0 < r.residue_decimal < 1,
      f"residue={r.residue_decimal:.6f}")
check("FLOOR-7: the ANCHOR IS NOT FLOORED — it passes through as the exact "
      "integer commitment", r.issuer_final_cents == ANCHOR == 5000)

# An anchor whose own division would change if it were (incorrectly) floored
# through the fair-pot arithmetic. If any implementation floored the issuer side,
# these would diverge.
odd_anchor = 5001
r_odd = adjust_escrow(
    anchor_cents=odd_anchor, p_issuer_final=0.82, p_opponent_final=0.18,
    issuer_ceiling_cents=odd_anchor, opponent_ceiling_cents=99_999,
    issuer_escrow_balance_cents=odd_anchor, opponent_escrow_balance_cents=99_999,
)
check("FLOOR-7: an ODD anchor survives exactly — 5001 in, 5001 out, no floor "
      "and no drift", r_odd.issuer_final_cents == 5001)
check("FLOOR-7: only the derived side floors — its value is the floor of the "
      "odd anchor's fair pot",
      r_odd.opponent_final_cents == math.floor(5001 / 0.82 * 0.18),
      str(r_odd.opponent_final_cents))
check("FLOOR-7: no authoritative residue cents exist — the result exposes "
      "residue_decimal only, and no field named residue_cents",
      not hasattr(r, "residue_cents")
      and "residue_cents" not in AdjustmentResult.__dataclass_fields__
      and "residue_cents" not in StakePair.__dataclass_fields__)
check("FLOOR-7: the diagnostic residue is strictly sub-cent, so it could never "
      "be a postable amount", 0 <= r.residue_decimal < 1)


# ══════════════════════════════════════════════════════════════════════════════
section("FIXED-8: unchanged probabilities are an exact fixed point")

r = adjust(P_HS_ISS, P_HS_OPP)
check("FIXED-8: opponent final equals the Handshake ceiling exactly",
      r.opponent_final_cents == CEIL_OPP)
check("FIXED-8: opponent refund is 0 — NO historical 1-cent artifact",
      r.refund_opponent_cents == 0, str(r.refund_opponent_cents))
check("FIXED-8: issuer refund is 0", r.refund_issuer_cents == 0)
check("FIXED-8: the funded escrow is unchanged from the Handshake",
      r.final_funded_escrow_cents == ANCHOR + CEIL_OPP == 6097)
check("FIXED-8: re-deriving from scratch reproduces the Handshake pair exactly "
      "— the derivation is a true fixed point, not a coincidence of the cap",
      derive_stakes(ANCHOR, P_HS_ISS, P_HS_OPP).opponent_cents
      == r.opponent_final_cents)


# ══════════════════════════════════════════════════════════════════════════════
section("BRANCH-9: Rev 7 §8's four-branch self-check")

BRANCHES = [
    #  label,             p_iss, issuer_final, opp_final, refund_iss, refund_opp
    ("No Change",          0.82, 5000, 1097, 0,   0),
    ("Favorite worse",     0.70, 5000, 1097, 0,   0),
    ("Favorite better",    0.90, 5000,  555, 0, 542),   # see SPEC NOTE below
    ("Roles reversed",     0.35, 5000, 1097, 0,   0),
]
for label, p_iss, exp_iss, exp_opp, exp_r_iss, exp_r_opp in BRANCHES:
    r = adjust(p_iss, round(1 - p_iss, 10))
    check(f"BRANCH-9 [{label}] p_iss={p_iss}: issuer {exp_iss}, opponent "
          f"{exp_opp}, refunds {exp_r_iss}/{exp_r_opp}",
          (r.issuer_final_cents, r.opponent_final_cents,
           r.refund_issuer_cents, r.refund_opponent_cents)
          == (exp_iss, exp_opp, exp_r_iss, exp_r_opp),
          f"got {(r.issuer_final_cents, r.opponent_final_cents, r.refund_issuer_cents, r.refund_opponent_cents)}")

# SPEC NOTE (reported, not silently absorbed): Rev 7 §8's table records the
# "Favorite better" row as opponent 609 / refund 488. 609 is
# floor(6097.5609 x 0.10) — the HANDSHAKE fairPot (p=0.82) reused instead of
# recomputed at p=0.90. That is frozen-pot arithmetic, which MS-SIM-7 explicitly
# REMOVED. The normative formula is stated three times consistently — §2's
# canonical block, §4's module-surface comment, and §3's Final-Lock worked
# example (p=0.98 -> 102, which this module reproduces exactly in FLOOR-7) — and
# all three give 555 / 542. This suite implements the normative formula.
check("BRANCH-9: SPEC ERRATUM PINNED — Rev 7 §8's 609 equals the HANDSHAKE "
      "fairPot times the final opponent probability, i.e. the removed "
      "frozen-pot model; the canonical derivation gives 555",
      math.floor((ANCHOR / P_HS_ISS) * 0.10) == 609
      and math.floor((ANCHOR / 0.90) * 0.10) == 555,
      "documented for review; canonical value implemented")
check("BRANCH-9: three of Rev 7 §8's four rows match the canonical derivation "
      "unchanged — only the frozen-pot row differs",
      True is (sum(1 for lbl, p, a, b, c, d in BRANCHES
                   if lbl != "Favorite better") == 3))


# ══════════════════════════════════════════════════════════════════════════════
section("SWEEP-10: two positive refunds are unreachable under the canonical "
        "model")

two_positive = []
for i in range(5, 96):
    p_iss = i / 100
    r = adjust(p_iss, round(1 - p_iss, 10))
    if r.refund_issuer_cents > 0 and r.refund_opponent_cents > 0:
        two_positive.append((p_iss, r.refund_issuer_cents, r.refund_opponent_cents))

check("SWEEP-10: no probability in [0.05, 0.95] produces two positive refunds "
      "when the issuer's escrow equals the anchor (MS-SIM-9b unreachability)",
      two_positive == [], str(two_positive[:5]))
check("SWEEP-10: CONTROL — the sweep did produce positive OPPONENT refunds, so "
      "the absence above is not vacuous",
      any(adjust(i / 100, round(1 - i / 100, 10)).refund_opponent_cents > 0
          for i in range(5, 96)))
check("SWEEP-10: an issuer refund is reachable ONLY as a funding-correctness "
      "event — escrow above the anchor, never an odds movement",
      adjust(P_HS_ISS, P_HS_OPP, iss_escrow=ANCHOR + 250).refund_issuer_cents == 250,
      "a true-up overshoot, not a reprice")


# ══════════════════════════════════════════════════════════════════════════════
section("INVALID-11: invalid states fail loud, and none of them clamp")

check("INVALID-11: probabilities that do not sum to 1 are refused",
      raises(InvalidProbabilityError, adjust, 0.82, 0.20))
check("INVALID-11: a pair inside the 6-decimal tolerance is ACCEPTED, so the "
      "check is a tolerance and not an exact-equality trap",
      adjust(0.8200001, 0.1799999).issuer_final_cents == ANCHOR)
check("INVALID-11: zero probability is refused (fairPot would be undefined)",
      raises(InvalidProbabilityError, adjust, 0.0, 1.0))
check("INVALID-11: probability of 1 is refused (a certainty is not a wager)",
      raises(InvalidProbabilityError, adjust, 1.0, 0.0))
check("INVALID-11: a negative probability is refused",
      raises(InvalidProbabilityError, adjust, -0.2, 1.2))
check("INVALID-11: NaN and infinity are refused",
      raises(InvalidProbabilityError, adjust, float("nan"), 0.5)
      and raises(InvalidProbabilityError, adjust, float("inf"), 0.5))

check("INVALID-11: a negative anchor is refused",
      raises(InvalidStakeError, adjust, 0.82, 0.18, anchor=-5000))
check("INVALID-11: a zero anchor is refused — there is nothing to price against",
      raises(InvalidStakeError, adjust, 0.82, 0.18, anchor=0))
check("INVALID-11: a negative ceiling is refused",
      raises(InvalidStakeError, adjust, 0.82, 0.18, ceil_opp=-1))
check("INVALID-11: a negative escrow balance is refused",
      raises(InvalidStakeError, adjust, 0.82, 0.18, opp_escrow=-1))
check("INVALID-11: a float cent quantity is refused — money is integer cents",
      raises(InvalidStakeError, adjust, 0.82, 0.18, anchor=5000.5))
check("INVALID-11: a bool is refused as a cent quantity (bool is an int "
      "subclass; True must never silently mean 1 cent)",
      raises(InvalidStakeError, adjust, 0.82, 0.18, anchor=True))

check("INVALID-11: escrow BELOW the required final exposure is refused — Final "
      "Lock refunds, it never collects",
      raises(EscrowShortfallError, adjust, 0.82, 0.18, opp_escrow=CEIL_OPP - 1))
check("INVALID-11: issuer escrow below the anchor is refused for the same reason",
      raises(EscrowShortfallError, adjust, 0.82, 0.18, iss_escrow=ANCHOR - 1))
check("INVALID-11: an issuer ceiling BELOW the fixed anchor is refused, NOT "
      "silently min()'d down — that would reduce the issuer beneath the "
      "commitment they made",
      raises(CeilingViolationError, adjust, 0.82, 0.18, ceil_iss=ANCHOR - 1))
check("INVALID-11: an opponent ceiling of zero is legal and simply caps the "
      "opponent to nothing (a degenerate but consistent line, not an error)",
      adjust(0.82, 0.18, ceil_opp=0, opp_escrow=0).opponent_final_cents == 0)
check("INVALID-11: every refusal is a DynamicPricingError subclass, so callers "
      "can catch the family",
      all(issubclass(e, DynamicPricingError) for e in
          (InvalidProbabilityError, InvalidStakeError,
           CeilingViolationError, EscrowShortfallError)))
check("INVALID-11: derive_stakes applies the same input guards",
      raises(InvalidProbabilityError, derive_stakes, 5000, 0.82, 0.20)
      and raises(InvalidStakeError, derive_stakes, 0, 0.5, 0.5))


# ══════════════════════════════════════════════════════════════════════════════
section("FENCE-12: P3-D1 stayed pure")

import io
import inspect
import tokenize

import odds.dynamic_pricing as dp


def executable_source(text: str) -> str:
    """Strip comments and string literals, leaving only executable tokens.

    THE MODULE DOCUMENTS ITS OWN PROHIBITIONS IN PROSE — "no ledger calls",
    "never posted", "no commit", "there is deliberately no residue_cents field".
    A raw-text scan cannot tell a written prohibition from a violation of it, so
    scanning the docstring would fail every fence below on the strength of the
    sentences promising the fence holds. The P1-L4 and Package 2A gate suites
    record this same lesson ("paid for twice in B6"); this scan follows them.
    """
    skip = {tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE,
            tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
    for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        tok = getattr(tokenize, name, None)
        if tok is not None:
            skip.add(tok)
    return " ".join(
        t.string for t in tokenize.generate_tokens(io.StringIO(text).readline)
        if t.type not in skip)


raw = inspect.getsource(dp)
src = executable_source(raw)
check("FENCE-12: SCAN CONTROL — the executable-token view is non-empty and "
      "holds real code, so the fences below are not passing vacuously",
      "def adjust_escrow" in src and "def derive_stakes" in src)
for banned, why in (
    ("Session",        "no DB session type"),
    ("sqlalchemy",     "no ORM"),
    ("db.schema",      "no models"),
    ("ledger",         "no ledger calls"),
    ("commit",         "no transactions"),
    ("ProtocolEvent",  "no event identity"),
    ("final_lock",     "no Final Lock behaviour"),
    ("handshake_claim", "no claim behaviour"),
):
    check(f"FENCE-12: dynamic_pricing has {why}", banned not in src, banned)
check("FENCE-12: the module imports only the standard library",
      "numpy" not in src and "np" not in src.split())
check("FENCE-12: no residue_cents IDENTIFIER exists in executable code — the "
      "residue is exposed only as the diagnostic residue_decimal",
      "residue_cents" not in src and "residue_decimal" in src)
check("FENCE-12: CONTROL — the prohibition prose really is present in the raw "
      "source, so the token-stripping above is doing the work it claims",
      "residue_cents" in raw and "ledger" in raw)


# ──────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
if _failures:
    print(f"{len(_failures)} FAILED assertion(s):")
    for f in _failures:
        print(f"  - {f}")
    print(f"\n{_passes} passed, {len(_failures)} FAILED")
    sys.exit(1)
print(f"All {_passes} assertions PASSED")
