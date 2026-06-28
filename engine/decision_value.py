"""Evaluate a candidate roster move by diffing two TeamHealth snapshots.

evaluate_move(before, after) -> DecisionValue

Pairs WeekResult entries by week number across rest_of_season and playoffs,
computes per-week win_prob deltas, and derives a verdict.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.team_health import TeamHealth


@dataclass
class DecisionValue:
    win_prob_delta:     float        # mean win_prob change across rest_of_season weeks
    playoff_odds_delta: float        # mean win_prob change across playoff weeks
    champ_odds_delta:   float        # product(after playoff win_probs) - product(before)
    weekly_deltas:      list[float]  # per-week win_prob_after - win_prob_before (rest_of_season)
    verdict:            str          # "upgrade" | "downgrade" | "neutral"
    confidence:         float        # mean confidence across all weeks compared


def _champ_prob(health: TeamHealth) -> float:
    """Probability of winning every playoff game = product of weekly win_probs."""
    probs = [w.win_prob for w in health.playoffs]
    if not probs:
        return 0.0
    result = 1.0
    for p in probs:
        result *= p
    return result


def evaluate_move(before: TeamHealth, after: TeamHealth) -> DecisionValue:
    """Diff two TeamHealth snapshots produced from the same team_id and week.

    before: TeamHealth with the current roster.
    after:  TeamHealth with the candidate move applied.
    Returns a DecisionValue summarising the expected impact.
    """
    before_ros = {w.week: w for w in before.rest_of_season}
    after_ros  = {w.week: w for w in after.rest_of_season}
    shared_ros = sorted(set(before_ros) & set(after_ros))

    weekly_deltas = [
        after_ros[wk].win_prob - before_ros[wk].win_prob
        for wk in shared_ros
    ]
    win_prob_delta = (
        sum(weekly_deltas) / len(weekly_deltas) if weekly_deltas else 0.0
    )

    before_po = {w.week: w for w in before.playoffs}
    after_po  = {w.week: w for w in after.playoffs}
    shared_po = sorted(set(before_po) & set(after_po))

    po_deltas = [
        after_po[wk].win_prob - before_po[wk].win_prob
        for wk in shared_po
    ]
    playoff_odds_delta = (
        sum(po_deltas) / len(po_deltas) if po_deltas else 0.0
    )

    champ_odds_delta = _champ_prob(after) - _champ_prob(before)

    # Mean confidence from the before snapshot — represents simulation certainty
    # across all weeks used in the comparison (earlier weeks are sharper).
    conf_weeks = (
        [before_ros[wk] for wk in shared_ros]
        + [before_po[wk] for wk in shared_po]
    )
    confidence = (
        sum(w.confidence for w in conf_weeks) / len(conf_weeks)
        if conf_weeks else 0.0
    )

    if win_prob_delta > 0.03:
        verdict = "upgrade"
    elif win_prob_delta < -0.03:
        verdict = "downgrade"
    else:
        verdict = "neutral"

    return DecisionValue(
        win_prob_delta     = round(win_prob_delta, 4),
        playoff_odds_delta = round(playoff_odds_delta, 4),
        champ_odds_delta   = round(champ_odds_delta, 4),
        weekly_deltas      = [round(d, 4) for d in weekly_deltas],
        verdict            = verdict,
        confidence         = round(confidence, 4),
    )
