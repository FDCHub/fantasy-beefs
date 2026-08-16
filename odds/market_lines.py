"""
odds/market_lines.py — the one authority for FantasyStakes Versus market lines.

WP3C.2, under the OWNER RULING — FANTASYSTAKES MARKET LINE METHODOLOGY.

WHAT THIS OWNS, AND ONLY THIS. Given the simulated score arrays the pricing
model already produces for a pairing, this module decides the offered SPREAD and
the offered TOTAL. It decides nothing else. It runs no simulation, touches no
database, prices no wager, moves no money, and knows nothing about stakes,
escrow or settlement.

THE RULING, RESTATED AS CODE:

    spread = round_to_nearest_half( median(anchor_scores - opposite_scores) )
    total  = round_to_nearest_half( median(anchor_scores + opposite_scores) )

    Nearest 0.5. Whole numbers permitted. NO half-point hook.
    Favourite displays negative; underdog displays positive.

WHY THE MEDIAN AND NOT THE MEAN. The median is the point at which the simulated
distribution splits in half, so a line placed there is the line at which the two
sides of the wager are as close to an even proposition as this model can make
them. The mean is the balance point of the distribution, which coincides with
the median only when the distribution is symmetric — and a fantasy score
distribution built from nine independently drawn starters is not reliably so.
Measured on this engine, a line placed at the rounded median prices out at
p ≈ 0.508 for the anchor: a real market, not a coin flip dressed up as one.

WHY NO HOOK. `floor(x) + 0.5` guarantees a whole number can never be the line
and therefore that a PUSH can never occur. FantasyStakes already has certified
push semantics — GE-622 for the spread, GE-632 for the total, both implemented
in `betting/settlement_engine.py` — and a hook would make those branches
structurally unreachable. The owner ruled the hook out and push in; this module
rounds to the nearest half and lets whole numbers stand.

── THE SIGN RECONCILIATION, WHICH IS THE SUBTLE PART ────────────────────────

There are TWO signed numbers here and they are NEGATIONS OF ONE ANOTHER. Read
this before touching anything in this file.

  1. THE CANONICAL PRICING THRESHOLD — `MatchupLines.spread_line`.

     This is the number the certified engine has always meant by `line`:

         p_anchor = P( (anchor_score - opposite_score) > line )

     and settlement, unchanged, grades `margin > line` with equality a push
     (`betting/settlement_engine.py::_eval_spread`). It is stored on
     `BeefChallenge.line`, `BeefProposal.line` and `Bet.line`. WP3C.2 does not
     move it, rename it, negate it in the database, or reinterpret it. A wager
     written before this package settles exactly as it always would have.

     Under the ruling it takes the value `round_to_nearest_half(median margin)`,
     so a favourite anchor gets a POSITIVE threshold: it must win by more than
     that many points.

  2. THE SPORTSBOOK DISPLAY LINE — `sportsbook_spread(canonical)`.

     This is what a GM reads on the card, and the ruling fixes its convention:
     favourite negative, underdog positive. A favourite that must win by more
     than 3.5 is shown as −3.5.

     Therefore  display = −canonical,  exactly, in both directions:

         anchor favourite by 3.4  → canonical +3.5 → anchor shows −3.5
         anchor underdog by 2.8   → canonical −3.0 → anchor shows +3.0

     and the opposite side always shows the negation of the anchor's display,
     which is the canonical value itself.

WHY NOT JUST STORE THE SPORTSBOOK NUMBER. Because the stored number is a
settlement input. Negating it in the database would silently invert every
spread wager's grading and would require changing `_eval_spread`, which is
certified. The smallest architecture that satisfies the ruling is the one taken
here: the persisted canonical threshold is untouched, and the sportsbook sign is
a presentation translation performed ONCE, on the server, by the function below.
The browser never converts, and could not — it is served the display value.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

import numpy as np

__all__ = [
    "MatchupLines",
    "lines_from_scores",
    "median_margin",
    "median_total",
    "round_to_nearest_half",
    "sportsbook_spread",
]


def round_to_nearest_half(value: float) -> float:
    """Round to the nearest 0.5, halves away from zero.

    DECIMAL, NOT `round()`. Python's built-in `round` is banker's rounding: it
    breaks ties toward the even neighbour, so `round(3.25 * 2) / 2` is 3.0 while
    `round(3.75 * 2) / 2` is 4.0 — two different answers to the same question
    depending on which side of the tie you happen to land. A market line decided
    that way would be unexplainable to a GM and unstable across a language
    change. `ROUND_HALF_UP` on a `Decimal` is one rule, stated once.

    `Decimal(repr(...))` rather than `Decimal(float)` deliberately: the latter
    takes the exact binary value, so 3.25 arrives as 3.25000000000000008882…
    and a tie that should round up rounds up for the wrong reason. `repr` gives
    the shortest decimal that round-trips, which is the number the caller meant.

    HALVES GO AWAY FROM ZERO, symmetrically: +3.75 → +4.0 and −3.75 → −4.0. The
    ruling states the rule for nonnegative magnitudes and requires negatives to
    be tested explicitly; away-from-zero IS "round the magnitude half-up, then
    reapply the sign", so one call covers both and the suite proves it.

    NEGATIVE ZERO IS NORMALISED. `-0.0` is a real float and it prints as "-0.0",
    which on a market card would read as a spread with a direction. There is no
    such market: a line of zero has no favourite.

    :param value: any real number, typically a simulated median
    :returns: the nearest multiple of 0.5
    """
    doubled = Decimal(repr(float(value))) * 2
    rounded = doubled.quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2
    result = float(rounded)
    return 0.0 if result == 0 else result


def median_margin(anchor_scores: Sequence[float],
                  opposite_scores: Sequence[float]) -> float:
    """The median simulated margin, from the ANCHOR team's perspective.

    Positive means the anchor is the favourite. Raw and unrounded — the caller
    rounds, so a test can inspect the estimator and the rounding separately.
    """
    return float(np.median(np.asarray(anchor_scores) - np.asarray(opposite_scores)))


def median_total(anchor_scores: Sequence[float],
                 opposite_scores: Sequence[float]) -> float:
    """The median simulated combined score. Raw and unrounded."""
    return float(np.median(np.asarray(anchor_scores) + np.asarray(opposite_scores)))


@dataclass(frozen=True)
class MatchupLines:
    """The two offered lines for one pairing, in CANONICAL form.

    `spread_line` is the pricing threshold described at the top of this module —
    the value that goes into `BeefChallenge.line`. Call `sportsbook_spread` to
    get what a GM should read.

    `total_line` needs no translation: a total is unsigned and means the same
    thing to both sides.

    The raw medians are carried alongside so a diagnostic surface can show what
    the line was rounded FROM without re-deriving it, and so a test can prove
    the rounding was applied to the number this module actually measured.
    """

    spread_line:   float
    total_line:    float
    raw_margin:    float
    raw_total:     float


def lines_from_scores(anchor_scores: Sequence[float],
                      opposite_scores: Sequence[float]) -> MatchupLines:
    """Derive both offered lines from ONE pair of simulated score arrays.

    THE SAME ARRAYS THAT PRICE THE WAGER. This function takes the simulation's
    output rather than the teams, which is what makes the board internally
    coherent: the caller simulates once and hands the result here and to the
    probability calculation, so the line and the odds cannot come from two
    different draws of the same matchup.

    :param anchor_scores: simulated scores for the team the line is anchored on
    :param opposite_scores: simulated scores for the other team
    """
    raw_m = median_margin(anchor_scores, opposite_scores)
    raw_t = median_total(anchor_scores, opposite_scores)
    return MatchupLines(
        spread_line=round_to_nearest_half(raw_m),
        total_line=round_to_nearest_half(raw_t),
        raw_margin=raw_m,
        raw_total=raw_t,
    )


def sportsbook_spread(canonical_line: float) -> float:
    """The DISPLAY spread for the side the canonical threshold is anchored on.

    Favourite negative, underdog positive — the convention the owner ruling
    fixes as POR. See the sign reconciliation at the top of this module: the
    display value is the negation of the canonical threshold, and this one-line
    function is the only place in the system where that negation is performed.

    :param canonical_line: a `MatchupLines.spread_line`, anchored on some team
    :returns: what that team's spread cell should read
    """
    flipped = -float(canonical_line)
    return 0.0 if flipped == 0 else flipped
