"""
Headless Monte Carlo odds engine.

Identical math to odds/monte_carlo.py but with no database or SQLAlchemy
dependencies. All inputs are plain Python / NumPy — suitable for use in
workers, tests, or any context where a DB session is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# ── Constants ─────────────────────────────────────────────────────────────────

N_SIMS  = 10_000
STD_PCT = 0.20
MIN_STD = 0.5
N_START = 9

INJURY_MULTIPLIERS: dict[str, float] = {
    "out":          0.00,
    "ir":           0.00,
    "doubtful":     0.25,
    "questionable": 0.60,
}

# ── Scoring settings ──────────────────────────────────────────────────────────

@dataclass
class ScoringSettings:
    scoring_type:     str
    rec_points:       float
    pass_td_points:   float
    rush_td_points:   float
    rec_td_points:    float
    bonus_100yd_rush: float
    bonus_100yd_rec:  float


STANDARD = ScoringSettings("standard", 0.0, 4.0, 6.0, 6.0, 0.0, 0.0)
HALF_PPR = ScoringSettings("half_ppr", 0.5, 5.0, 6.0, 6.0, 0.0, 0.0)
PPR      = ScoringSettings("ppr",      1.0, 4.0, 6.0, 6.0, 0.0, 0.0)

_FP_REC_PTS     = 1.0
_FP_PASS_TD_PTS = 4.0
_FP_RUSH_TD_PTS = 6.0
_FP_REC_TD_PTS  = 6.0

_AVG_STATS: dict[str, dict] = {
    "QB":   {"rec": 0.0, "pass_td": 1.8, "rush_td": 0.20, "rec_td": 0.00, "r100": 0.02, "c100": 0.00},
    "RB":   {"rec": 3.5, "pass_td": 0.0, "rush_td": 0.70, "rec_td": 0.20, "r100": 0.15, "c100": 0.03},
    "WR":   {"rec": 5.0, "pass_td": 0.0, "rush_td": 0.05, "rec_td": 0.50, "r100": 0.01, "c100": 0.18},
    "TE":   {"rec": 3.5, "pass_td": 0.0, "rush_td": 0.00, "rec_td": 0.35, "r100": 0.00, "c100": 0.08},
    "FLEX": {"rec": 3.5, "pass_td": 0.0, "rush_td": 0.35, "rec_td": 0.35, "r100": 0.08, "c100": 0.10},
    "K":    {"rec": 0.0, "pass_td": 0.0, "rush_td": 0.00, "rec_td": 0.00, "r100": 0.00, "c100": 0.00},
    "DEF":  {"rec": 0.0, "pass_td": 0.0, "rush_td": 0.00, "rec_td": 0.00, "r100": 0.00, "c100": 0.00},
}

# ── Input / result dataclasses ────────────────────────────────────────────────

@dataclass
class PlayerProj:
    player_id:        int
    name:             str
    position:         str
    projected_points: float
    injury_status:    str | None


@dataclass
class StarterLine:
    player_id:        int
    name:             str
    position:         str
    projected_points: float
    adjusted_points:  float


@dataclass
class OddsResult:
    matchup_id:     int
    week:           int
    simulations:    int
    scoring_type:   str
    home_team_id:   int
    home_team_name: str
    away_team_id:   int
    away_team_name: str
    home_win_prob:  float
    away_win_prob:  float
    home_moneyline: int
    away_moneyline: int
    home_proj_mean: float
    away_proj_mean: float
    home_proj_std:  float
    away_proj_std:  float
    home_starters:  list[StarterLine] = field(default_factory=list)
    away_starters:  list[StarterLine] = field(default_factory=list)


# ── Core math ─────────────────────────────────────────────────────────────────

def _adjust_for_scoring(raw_ppr_pts: float, position: str, scoring: ScoringSettings) -> float:
    """Convert a FantasyPros PPR projection to the target scoring system."""
    s = _AVG_STATS.get(position, _AVG_STATS["FLEX"])
    delta = (
        (scoring.rec_points      - _FP_REC_PTS)     * s["rec"]
      + (scoring.pass_td_points  - _FP_PASS_TD_PTS) * s["pass_td"]
      + (scoring.rush_td_points  - _FP_RUSH_TD_PTS) * s["rush_td"]
      + (scoring.rec_td_points   - _FP_REC_TD_PTS)  * s["rec_td"]
      + scoring.bonus_100yd_rush * s["r100"]
      + scoring.bonus_100yd_rec  * s["c100"]
    )
    return max(0.0, round(raw_ppr_pts + delta, 4))


def _prob_to_american(prob: float) -> int:
    """Convert win probability [0,1] to American moneyline integer."""
    prob = max(0.001, min(0.999, prob))
    if prob > 0.5:
        return -round(100 * prob / (1 - prob))
    if prob < 0.5:
        return round(100 * (1 - prob) / prob)
    return 100


def _simulate_team(pts: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """
    pts: shape (n_starters,) — projected points per starter
    Returns shape (N_SIMS,) — simulated team total per trial.
    """
    sigma = np.maximum(np.abs(pts) * STD_PCT, MIN_STD)
    draws = rng.normal(loc=pts, scale=sigma, size=(N_SIMS, len(pts)))
    draws = np.maximum(draws, 0.0)
    return draws.sum(axis=1)


# ── Private helper ────────────────────────────────────────────────────────────

def _build_starter_lines(
    players: list[PlayerProj],
    scoring: ScoringSettings,
) -> list[StarterLine]:
    lines = []
    for p in players:
        inj_mult  = INJURY_MULTIPLIERS.get(p.injury_status or "", 1.0)
        adjusted  = _adjust_for_scoring(p.projected_points * inj_mult, p.position, scoring)
        lines.append(StarterLine(
            player_id        = p.player_id,
            name             = p.name,
            position         = p.position,
            projected_points = p.projected_points,
            adjusted_points  = adjusted,
        ))
    return lines


# ── Public API ────────────────────────────────────────────────────────────────

def run(
    matchup_id:     int,
    home_team_id:   int,
    home_team_name: str,
    home_starters:  list[PlayerProj],
    away_team_id:   int,
    away_team_name: str,
    away_starters:  list[PlayerProj],
    week:           int,
    n_sims:         int = N_SIMS,
    scoring:        ScoringSettings = HALF_PPR,
) -> OddsResult:
    """Run Monte Carlo simulation and return OddsResult."""
    if not home_starters:
        raise ValueError("home_starters must not be empty")
    if not away_starters:
        raise ValueError("away_starters must not be empty")

    home_lines = _build_starter_lines(home_starters, scoring)
    away_lines = _build_starter_lines(away_starters, scoring)

    home_pts = np.array([s.adjusted_points for s in home_lines])
    away_pts = np.array([s.adjusted_points for s in away_lines])

    rng = np.random.default_rng(seed=matchup_id * 1_000 + week)

    home_scores = _simulate_team(home_pts, rng)
    away_scores = _simulate_team(away_pts, rng)

    home_wins     = int((home_scores > away_scores).sum())
    home_win_prob = home_wins / n_sims
    away_win_prob = 1.0 - home_win_prob

    if abs(home_win_prob + away_win_prob - 1.0) > 1e-9:
        raise ValueError(
            f"Probability invariant violated: {home_win_prob} + {away_win_prob} != 1.0"
        )

    return OddsResult(
        matchup_id     = matchup_id,
        week           = week,
        simulations    = n_sims,
        scoring_type   = scoring.scoring_type,
        home_team_id   = home_team_id,
        home_team_name = home_team_name,
        away_team_id   = away_team_id,
        away_team_name = away_team_name,
        home_win_prob  = round(home_win_prob, 4),
        away_win_prob  = round(away_win_prob, 4),
        home_moneyline = _prob_to_american(home_win_prob),
        away_moneyline = _prob_to_american(away_win_prob),
        home_proj_mean = round(float(home_scores.mean()), 2),
        away_proj_mean = round(float(away_scores.mean()), 2),
        home_proj_std  = round(float(home_scores.std()),  2),
        away_proj_std  = round(float(away_scores.std()),  2),
        home_starters  = home_lines,
        away_starters  = away_lines,
    )


def simulate_scores(
    home_team_id:  int,
    away_team_id:  int,
    home_starters: list[PlayerProj],
    away_starters: list[PlayerProj],
    week:          int,
    n_sims:        int = N_SIMS,
    scoring:       ScoringSettings = HALF_PPR,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (home_scores, away_scores) arrays of shape (n_sims,)."""
    if not home_starters:
        raise ValueError("home_starters must not be empty")
    if not away_starters:
        raise ValueError("away_starters must not be empty")

    home_lines = _build_starter_lines(home_starters, scoring)
    away_lines = _build_starter_lines(away_starters, scoring)

    home_pts = np.array([s.adjusted_points for s in home_lines])
    away_pts = np.array([s.adjusted_points for s in away_lines])

    rng = np.random.default_rng(seed=home_team_id * 10_000 + away_team_id * 100 + week)
    return _simulate_team(home_pts, rng), _simulate_team(away_pts, rng)


def simulate_player_scores(
    projected_points: float,
    player_id: int,
    week: int,
    n_sims: int = N_SIMS,
) -> np.ndarray:
    """Return score array of shape (n_sims,) for a single player."""
    rng   = np.random.default_rng(seed=player_id * 1_000 + week)
    sigma = max(abs(projected_points) * STD_PCT, MIN_STD)
    draws = rng.normal(loc=projected_points, scale=sigma, size=n_sims)
    return np.maximum(draws, 0.0)
