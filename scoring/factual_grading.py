"""Sprint 6B · factual lineup totals -> the EXISTING grading vocabulary.

WHAT THIS IS, IN ONE SENTENCE: an adapter, not an engine.

`betting/settlement_engine.py` already knows how to grade a moneyline, a spread
and a total. It has known since long before BALLDONTLIE existed, it is
certified, and its arithmetic prices real money. Sprint 6B does not restate any
of it. It hands the same functions the same shapes they already read, with the
scores coming from BALLDONTLIE facts instead of from Yahoo's scoreboard, and
returns the vocabulary they already return.

── HOW THE REUSE IS LITERAL ────────────────────────────────────────────────

`_eval_spread(bet, matchup)` reads four attributes: `bet.picked_team_id`,
`bet.line`, `matchup.home_team_id`, and the two scores. `_eval_over_under`
reads three. None of them touches a Session, a ledger or an ORM identity map —
they are pure functions over attribute access that happen to be typed against
ORM classes. So this module builds two tiny frozen shims carrying exactly those
attributes and calls the real functions. If someone changes a grading rule in
`settlement_engine.py`, this adapter changes with it, silently and correctly,
because there is no second copy of the rule to forget.

The one rule not delegated is the TIE. `_eval_straight` returns a bool and has
no push, because a Yahoo matchup has a `winner_team_id` that is simply null on
a tie; `_eval_beef` — the GM-vs-GM product these markets actually are — treats
an equal score as a push explicitly. This module follows `_eval_beef`, and says
so here rather than quietly picking one.

── WHAT THIS MODULE MUST NEVER DO ──────────────────────────────────────────

Move money, compute a stake, size a pot, decide a payout, or write
`finalized_at`. It imports nothing from `ledger`, `economy`, or the money paths
of `betting`; the Sprint 6B suite asserts that by parsing the import graph. Its
output is a string from the vocabulary the settlement engine already accepts —
"won", "lost", "push" — plus a refusal when the facts do not support grading at
all.

── A REFUSAL IS NOT A RESULT ───────────────────────────────────────────────

`NOT_READY` is deliberately not in the same space as won/lost/push. A market
whose evidence is short has not drawn and has not been voided; it has not been
graded, and the settlement path must not be handed a value it could mistake for
an outcome. That is why `grade_versus` returns a `VersusGrade` whose `outcome`
is None until every gate passes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from scoring.factual import LineupScore

__all__ = ["VersusGrade", "Outcome", "MarketType", "grade_versus",
           "settlement_scores"]


class Outcome:
    """The vocabulary `Bet.status` already permits. Nothing new is invented."""

    WON = "won"
    LOST = "lost"
    PUSH = "push"


class MarketType:
    """The Versus market types `settlement_engine._EVALUATORS` dispatches on."""

    MONEYLINE = "straight"
    SPREAD = "spread"
    TOTAL = "over_under"


@dataclass(frozen=True)
class _BetShim:
    """Exactly the attributes the real evaluators read off a `Bet`."""

    picked_team_id: Any
    line: float | None
    side: str | None


@dataclass(frozen=True)
class _MatchupShim:
    """Exactly the attributes the real evaluators read off a `Matchup`."""

    home_team_id: Any
    away_team_id: Any
    home_score: float
    away_score: float
    winner_team_id: Any


@dataclass
class VersusGrade:
    """A graded market, or a named reason it could not be graded."""

    market_type: str
    outcome: str | None = None
    ready: bool = False
    home_score: float | None = None
    away_score: float | None = None
    line: float | None = None
    side: str | None = None
    evidence_fingerprint: str | None = None
    refusals: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"market_type": self.market_type, "outcome": self.outcome,
                "ready": self.ready, "home_score": self.home_score,
                "away_score": self.away_score, "line": self.line,
                "side": self.side,
                "evidence_fingerprint": self.evidence_fingerprint,
                "refusals": list(self.refusals)}


def _readiness_refusals(home: LineupScore, away: LineupScore, *,
                        week_is_final: bool) -> list:
    """Every reason this market may not be graded FINAL. §5's gate, in one place."""
    from scoring.factual import settlement_eligible

    eligible, reasons = settlement_eligible([home, away],
                                            week_is_final=week_is_final)
    return [] if eligible else list(reasons)


def grade_versus(*, home: LineupScore, away: LineupScore,
                 home_team_id: Any, away_team_id: Any,
                 market_type: str, picked_team_id: Any = None,
                 line: float | None = None, side: str | None = None,
                 week_is_final: bool = False) -> VersusGrade:
    """Two factual lineup totals + a market line -> the existing outcome vocabulary.

    THE GRADING ITSELF IS NOT DONE HERE. `_eval_spread` and `_eval_over_under`
    are imported from the settlement engine and called with shims carrying the
    factual scores. The tie-to-push rule follows `_eval_beef`, which is the
    behaviour of the GM-vs-GM product these markets are.
    """
    from betting.settlement_engine import _eval_over_under, _eval_spread

    grade = VersusGrade(market_type=market_type, line=line, side=side)
    grade.refusals = _readiness_refusals(home, away, week_is_final=week_is_final)
    if grade.refusals:
        return grade

    home_points = home.points
    away_points = away.points
    grade.home_score = home_points
    grade.away_score = away_points

    from scoring.factual import lineup_fingerprint
    grade.evidence_fingerprint = lineup_fingerprint(home) + ":" \
        + lineup_fingerprint(away)

    winner = (home_team_id if home_points > away_points
              else away_team_id if away_points > home_points else None)
    matchup = _MatchupShim(home_team_id=home_team_id, away_team_id=away_team_id,
                           home_score=home_points, away_score=away_points,
                           winner_team_id=winner)
    bet = _BetShim(picked_team_id=picked_team_id, line=line, side=side)

    if market_type == MarketType.MONEYLINE:
        # THE TIE IS A PUSH, following `_eval_beef`. `_eval_straight` cannot
        # express it — it returns a bool against a possibly-null winner — so
        # the rule is stated here once, beside its source, rather than left to
        # a false that would read as a loss.
        if winner is None:
            grade.outcome = Outcome.PUSH
        else:
            grade.outcome = (Outcome.WON if picked_team_id == winner
                             else Outcome.LOST)
    elif market_type == MarketType.SPREAD:
        margin = (home_points - away_points if picked_team_id == home_team_id
                  else away_points - home_points)
        if margin == (line or 0.0):
            grade.outcome = Outcome.PUSH          # `_eval_beef`'s spread push
        else:
            grade.outcome = (Outcome.WON if _eval_spread(bet, matchup)
                             else Outcome.LOST)
    elif market_type == MarketType.TOTAL:
        combined = home_points + away_points
        if combined == (line or 0.0):
            grade.outcome = Outcome.PUSH          # `_eval_beef`'s total push
        else:
            grade.outcome = (Outcome.WON if _eval_over_under(bet, matchup)
                             else Outcome.LOST)
    else:
        grade.refusals.append(
            f"UNSUPPORTED_MARKET: {market_type!r} is not a Versus market type "
            f"this adapter grades")
        return grade

    grade.ready = True
    return grade


def settlement_scores(home: LineupScore, away: LineupScore
                      ) -> tuple[float, float]:
    """The two numbers the existing settlement engine consumes.

    Every Versus market in `settlement_engine.py` reaches its answer through
    `Matchup.home_score` / `away_score` — `_eval_spread` reads them directly and
    `_eval_beef` reaches them through `_team_score_for_week`. So the whole of a
    factual result's contact with settlement is this pair of floats, written to
    the field Yahoo already writes. There is no second field, no parallel table
    and no new enum: the provider changed, and nothing downstream can tell.
    """
    return home.points, away.points
