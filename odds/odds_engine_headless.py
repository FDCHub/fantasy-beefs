"""
Headless Monte Carlo odds engine.

Identical math to odds/monte_carlo.py but with no database or SQLAlchemy
dependencies. All inputs are plain Python / NumPy — suitable for use in
workers, tests, or any context where a DB session is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from odds.model_registry import SimModelConfig

# ── Constants ─────────────────────────────────────────────────────────────────
#
# P3-D2 / MODEL-A + N-B — THE PROBABILITY-AFFECTING CONSTANTS ARE GONE FROM THIS
# MODULE. `N_SIMS`, `STD_PCT`, `MIN_STD`, `INJURY_MULTIPLIERS`, `_AVG_STATS` and
# the `_FP_*` reference-scoring values now live in odds/model_registry.py as
# fields of a versioned, immutable SimModelConfig, and every function below
# receives one explicitly.
#
# THEY WERE DELETED RATHER THAN LEFT AS DEFAULTS, DELIBERATELY. A module-level
# constant that any function may read is exactly the bypass MODEL-A exists to
# close: an unconverted caller would silently inherit whatever model is currently
# deployed, and a Dynamic wager would Final-Lock under rules it never froze. A
# default that is *usually* right is worse here than no default, because the
# failure is silent and lands on real money. `model_config` is keyword-only and
# has no default on every public entry point, so omitting it is an immediate
# TypeError rather than a wrong probability.
#
# N-B additionally removes the per-call `n_sims` parameter. It was a second,
# independent source for the simulation count, and in this module it disagreed
# with itself: `_simulate_team` drew `N_SIMS` rows while `run()` divided by the
# `n_sims` argument, so any caller passing a non-default value got a probability
# computed against the wrong denominator. The count now comes from exactly one
# place, `model_config.n_sims`, and is used for both the draw size and every
# denominator in the same invocation.
#
# N_START is retained: it is a roster-selection constant used by callers, and it
# does not enter any probability computation in this module.

N_START = 9

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

def _adjust_for_scoring(raw_ppr_pts: float, position: str, *,
                        model_config: SimModelConfig) -> float:
    """Convert a FantasyPros PPR projection to the model's scoring system.

    Every constant this once read from module scope — the per-position average
    stat profile, the FantasyPros reference scoring, the target scoring settings
    and the rounding precision — now comes from the versioned config.
    """
    s        = model_config.avg_stats_for(position)
    scoring  = model_config.scoring
    delta = (
        (scoring.rec_points      - model_config.fp_ref("rec"))     * s["rec"]
      + (scoring.pass_td_points  - model_config.fp_ref("pass_td")) * s["pass_td"]
      + (scoring.rush_td_points  - model_config.fp_ref("rush_td")) * s["rush_td"]
      + (scoring.rec_td_points   - model_config.fp_ref("rec_td"))  * s["rec_td"]
      + scoring.bonus_100yd_rush * s["r100"]
      + scoring.bonus_100yd_rec  * s["c100"]
    )
    return max(0.0, round(raw_ppr_pts + delta, model_config.points_round_dp))


def _prob_to_american(prob: float) -> int:
    """Convert win probability [0,1] to American moneyline integer."""
    prob = max(0.001, min(0.999, prob))
    if prob > 0.5:
        return -round(100 * prob / (1 - prob))
    if prob < 0.5:
        return round(100 * (1 - prob) / prob)
    return 100


def _simulate_team(pts: np.ndarray, rng: np.random.Generator, *,
                   model_config: SimModelConfig) -> np.ndarray:
    """
    pts: shape (n_starters,) — projected points per starter
    Returns shape (model_config.n_sims,) — simulated team total per trial.

    N-B: the draw size comes from `model_config.n_sims`, the SAME value every
    denominator in this invocation uses. Previously this read module-level
    N_SIMS while the caller divided by its own `n_sims` argument, so the two
    could disagree.

    Starters are drawn as INDEPENDENT normals and summed — there is no
    covariance structure. `model_config.starter_correlation` records that
    absence explicitly, so introducing correlation later must mint a new model
    version rather than silently alter sim-v1.
    """
    sigma = np.maximum(np.abs(pts) * model_config.std_pct, model_config.min_std)
    draws = rng.normal(loc=pts, scale=sigma,
                       size=(model_config.n_sims, len(pts)))
    if model_config.truncate_draws_at_zero:
        draws = np.maximum(draws, 0.0)
    return draws.sum(axis=1)


def simulate_team_with_sigma(pts: np.ndarray, sigmas: np.ndarray,
                            rng: np.random.Generator, *,
                            model_config: SimModelConfig) -> np.ndarray:
    """The sim-v2 draw: one sigma PER PLAYER, supplied by IPRM.

    ADDED BESIDE `_simulate_team`, NOT INSTEAD OF IT. v1 derives every sigma
    from one global `std_pct` inside the draw; v2 receives a sigma per player,
    because IPRM may model a quarterback and a defence differently even when
    their means match. Leaving v1's function untouched is what makes the
    sim-v1 freeze provable by inspection as well as by fixture.

    The truncation decision is read from the config rather than assumed: v1
    clamps at zero, v2 does not, and both are recorded fields of their frozen
    versions.
    """
    if len(pts) != len(sigmas):
        raise ValueError(
            f"each starter needs exactly one sigma: {len(pts)} means against "
            f"{len(sigmas)} sigmas")
    safe = np.maximum(np.asarray(sigmas, dtype=float), model_config.min_std)
    draws = rng.normal(loc=pts, scale=safe,
                       size=(model_config.n_sims, len(pts)))
    if model_config.truncate_draws_at_zero:
        draws = np.maximum(draws, 0.0)
    return draws.sum(axis=1)


# ── Private helper ────────────────────────────────────────────────────────────

def _build_starter_lines(
    players: list[PlayerProj],
    *,
    model_config: SimModelConfig,
) -> list[StarterLine]:
    """The injury STATUS on each PlayerProj is a live input; the multiplier
    TABLE it indexes is model config. Keeping those apart is what lets Final
    Lock read a player's current status while still pricing under the model
    frozen at Handshake."""
    lines = []
    for p in players:
        inj_mult  = model_config.injury_multiplier(p.injury_status)
        adjusted  = _adjust_for_scoring(p.projected_points * inj_mult, p.position,
                                        model_config=model_config)
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
    *,
    model_config:   SimModelConfig,
) -> OddsResult:
    """Run Monte Carlo simulation and return OddsResult.

    `model_config` is keyword-only and has NO default: a caller cannot silently
    inherit whatever model is currently deployed (MODEL-A). The former `n_sims`
    and `scoring` parameters are gone — both were probability-affecting and both
    now come from the resolved config (N-B).
    """
    if not home_starters:
        raise ValueError("home_starters must not be empty")
    if not away_starters:
        raise ValueError("away_starters must not be empty")

    home_lines = _build_starter_lines(home_starters, model_config=model_config)
    away_lines = _build_starter_lines(away_starters, model_config=model_config)

    home_pts = np.array([s.adjusted_points for s in home_lines])
    away_pts = np.array([s.adjusted_points for s in away_lines])

    rng = np.random.default_rng(seed=matchup_id * 1_000 + week)

    home_scores = _simulate_team(home_pts, rng, model_config=model_config)
    away_scores = _simulate_team(away_pts, rng, model_config=model_config)

    # N-B: the denominator is the SAME n_sims that sized the draws, so the two
    # can no longer disagree. `home_scores` has exactly this many entries.
    n_sims        = model_config.n_sims
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
        scoring_type   = model_config.scoring.scoring_type,
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
    *,
    model_config:  SimModelConfig,
    matchup_id:    int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (home_scores, away_scores) arrays of shape (model_config.n_sims,).

    SEED DERIVATION IS THE CONFIGURED RULE; THE SEED ITSELF IS A LIVE INPUT.
    `model_config.seed_method` names the rule — matchup-seeded when a shared
    matchup id is supplied, team-pair-seeded otherwise — while the integer it
    produces comes from matchup/team/week identity, which is per-challenge data
    and deliberately not part of the model version.
    """
    if not home_starters:
        raise ValueError("home_starters must not be empty")
    if not away_starters:
        raise ValueError("away_starters must not be empty")

    home_lines = _build_starter_lines(home_starters, model_config=model_config)
    away_lines = _build_starter_lines(away_starters, model_config=model_config)

    home_pts = np.array([s.adjusted_points for s in home_lines])
    away_pts = np.array([s.adjusted_points for s in away_lines])

    if matchup_id is not None:
        rng = np.random.default_rng(seed=matchup_id * 1_000 + week)
    else:
        rng = np.random.default_rng(seed=home_team_id * 10_000 + away_team_id * 100 + week)
    return (_simulate_team(home_pts, rng, model_config=model_config),
            _simulate_team(away_pts, rng, model_config=model_config))


def simulate_player_scores(
    projected_points: float,
    player_id: int,
    week: int,
    *,
    model_config: SimModelConfig,
) -> np.ndarray:
    """Return score array of shape (model_config.n_sims,) for a single player."""
    rng   = np.random.default_rng(seed=player_id * 1_000 + week)
    sigma = max(abs(projected_points) * model_config.std_pct, model_config.min_std)
    draws = rng.normal(loc=projected_points, scale=sigma,
                       size=model_config.n_sims)
    if model_config.truncate_draws_at_zero:
        draws = np.maximum(draws, 0.0)
    return draws
