"""
Monte Carlo odds engine.

For each team, draws N_SIMS samples per starter from
  Normal(projected_points, STD_PCT * projected_points)
sums the 9 starter scores, counts wins, and converts to American moneyline odds.

Seed is derived from matchup_id + week so the same matchup always returns
the same odds within a session (reproducible without being user-visible).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import LeagueScoring, Matchup, Projection, Roster, SessionLocal, Team

N_SIMS           = 10_000
STD_PCT          = 0.20   # 20 % of projected points as σ
MIN_STD          = 0.5    # floor so zero-projection players still vary
N_START          = 9      # QB RB RB WR WR TE FLEX K DEF
SEASON           = 2024
SOURCE           = "fantasypros"
MIN_HEALTHY_BENCH = 6     # bench_battle requires this many non-Out/IR bench players per team

INJURY_MULTIPLIERS: dict[str, float] = {
    "out":          0.00,
    "ir":           0.00,
    "doubtful":     0.25,
    "questionable": 0.60,
}

# ── Scoring settings ──────────────────────────────────────────────────────────

@dataclass
class ScoringSettings:
    scoring_type:     str    # standard | half_ppr | ppr | custom
    rec_points:       float
    pass_td_points:   float
    rush_td_points:   float
    rec_td_points:    float
    bonus_100yd_rush: float
    bonus_100yd_rec:  float


STANDARD = ScoringSettings("standard", 0.0, 4.0, 6.0, 6.0, 0.0, 0.0)
HALF_PPR = ScoringSettings("half_ppr", 0.5, 4.0, 6.0, 6.0, 0.0, 0.0)
PPR      = ScoringSettings("ppr",      1.0, 4.0, 6.0, 6.0, 0.0, 0.0)

_SCORING_PRESETS = {
    "standard": STANDARD,
    "half_ppr": HALF_PPR,
    "ppr":      PPR,
}

# FantasyPros PPR-scrape baseline assumptions used for adjustment
_FP_REC_PTS     = 1.0
_FP_PASS_TD_PTS = 4.0
_FP_RUSH_TD_PTS = 6.0
_FP_REC_TD_PTS  = 6.0

# Position-average stats per game used to convert PPR→custom scoring
_AVG_STATS: dict[str, dict] = {
    "QB":   {"rec": 0.0, "pass_td": 1.8, "rush_td": 0.20, "rec_td": 0.00, "r100": 0.02, "c100": 0.00},
    "RB":   {"rec": 3.5, "pass_td": 0.0, "rush_td": 0.70, "rec_td": 0.20, "r100": 0.15, "c100": 0.03},
    "WR":   {"rec": 5.0, "pass_td": 0.0, "rush_td": 0.05, "rec_td": 0.50, "r100": 0.01, "c100": 0.18},
    "TE":   {"rec": 3.5, "pass_td": 0.0, "rush_td": 0.00, "rec_td": 0.35, "r100": 0.00, "c100": 0.08},
    "FLEX": {"rec": 3.5, "pass_td": 0.0, "rush_td": 0.35, "rec_td": 0.35, "r100": 0.08, "c100": 0.10},
    "K":    {"rec": 0.0, "pass_td": 0.0, "rush_td": 0.00, "rec_td": 0.00, "r100": 0.00, "c100": 0.00},
    "DEF":  {"rec": 0.0, "pass_td": 0.0, "rush_td": 0.00, "rec_td": 0.00, "r100": 0.00, "c100": 0.00},
}


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


def load_scoring_from_db(league_id: int, db) -> ScoringSettings:
    """Load scoring settings for a league; falls back to HALF_PPR if not found."""
    row = db.query(LeagueScoring).filter_by(league_id=league_id).first()
    if row is None:
        return HALF_PPR
    if row.scoring_type in _SCORING_PRESETS:
        preset = _SCORING_PRESETS[row.scoring_type]
        # Check if any custom values deviate from the preset
        if (row.pass_td_points != preset.pass_td_points
                or row.rush_td_points != preset.rush_td_points
                or row.rec_td_points  != preset.rec_td_points
                or row.bonus_100yd_rush != preset.bonus_100yd_rush
                or row.bonus_100yd_rec  != preset.bonus_100yd_rec):
            return ScoringSettings(
                scoring_type     = row.scoring_type,
                rec_points       = row.rec_points,
                pass_td_points   = row.pass_td_points,
                rush_td_points   = row.rush_td_points,
                rec_td_points    = row.rec_td_points,
                bonus_100yd_rush = row.bonus_100yd_rush,
                bonus_100yd_rec  = row.bonus_100yd_rec,
            )
        return _SCORING_PRESETS[row.scoring_type]
    return ScoringSettings(
        scoring_type     = row.scoring_type,
        rec_points       = row.rec_points,
        pass_td_points   = row.pass_td_points,
        rush_td_points   = row.rush_td_points,
        rec_td_points    = row.rec_td_points,
        bonus_100yd_rush = row.bonus_100yd_rush,
        bonus_100yd_rec  = row.bonus_100yd_rec,
    )


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class BenchPlayerLine:
    player_id:       int
    name:            str
    position:        str
    injury_status:   str | None   # None = healthy
    raw_points:      float        # FP PPR projection (pre-injury)
    adjusted_points: float        # after injury multiplier + scoring adjustment


@dataclass
class StarterLine:
    player_id:        int
    name:             str
    position:         str
    projected_points: float   # raw FantasyPros PPR projection
    adjusted_points:  float   # after scoring-system conversion


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
    # win probabilities
    home_win_prob:  float
    away_win_prob:  float
    # American moneyline (e.g. -150 / +130)
    home_moneyline: int
    away_moneyline: int
    # simulated score distributions
    home_proj_mean: float
    away_proj_mean: float
    home_proj_std:  float
    away_proj_std:  float
    # individual starter projections used
    home_starters:  list[StarterLine] = field(default_factory=list)
    away_starters:  list[StarterLine] = field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _prob_to_american(prob: float) -> int:
    """Convert win probability [0,1] to American moneyline integer."""
    prob = max(0.001, min(0.999, prob))
    if prob > 0.5:
        return -round(100 * prob / (1 - prob))
    if prob < 0.5:
        return round(100 * (1 - prob) / prob)
    return 100


def _starters(
    team: Team,
    week: int,
    db: Session,
    scoring: ScoringSettings | None = None,
) -> list[StarterLine]:
    """
    Return the first N_START roster slots with FantasyPros projected_points
    and adjusted_points for the given scoring system.
    """
    if scoring is None:
        scoring = PPR
    slots = (
        db.query(Roster)
        .filter(Roster.team_id == team.id)
        .order_by(Roster.id)
        .limit(N_START)
        .all()
    )
    lines = []
    for slot in slots:
        p = slot.player
        proj = (
            db.query(Projection)
            .filter_by(player_id=p.id, week=week, season=SEASON, source=SOURCE)
            .first()
        )
        raw = proj.projected_points if proj else 0.0
        lines.append(StarterLine(
            player_id        = p.id,
            name             = p.name,
            position         = p.position,
            projected_points = raw,
            adjusted_points  = _adjust_for_scoring(raw, p.position, scoring),
        ))
    return lines


def _simulate_team(pts: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """
    pts: shape (n_starters,) — projected points per starter
    Returns shape (N_SIMS,) — simulated team total per trial.
    """
    sigma = np.maximum(np.abs(pts) * STD_PCT, MIN_STD)
    draws = rng.normal(loc=pts, scale=sigma, size=(N_SIMS, len(pts)))
    draws = np.maximum(draws, 0.0)   # no negative scores
    return draws.sum(axis=1)


# ── Public API ────────────────────────────────────────────────────────────────

def run(
    matchup_id: int,
    home_team:  Team,
    away_team:  Team,
    week:       int,
    db:         Session,
    n_sims:     int = N_SIMS,
    scoring:    ScoringSettings | None = None,
) -> OddsResult:
    """Run Monte Carlo simulation and return OddsResult."""
    if scoring is None:
        scoring = PPR
    home_lines = _starters(home_team, week, db, scoring)
    away_lines = _starters(away_team, week, db, scoring)

    home_pts = np.array([s.adjusted_points for s in home_lines])
    away_pts = np.array([s.adjusted_points for s in away_lines])

    # Seed from matchup + week → same inputs always produce same odds
    rng = np.random.default_rng(seed=matchup_id * 1_000 + week)

    home_scores = _simulate_team(home_pts, rng)
    away_scores = _simulate_team(away_pts, rng)

    home_wins     = int((home_scores > away_scores).sum())
    home_win_prob = home_wins / n_sims
    away_win_prob = 1.0 - home_win_prob

    return OddsResult(
        matchup_id     = matchup_id,
        week           = week,
        simulations    = n_sims,
        scoring_type   = scoring.scoring_type,
        home_team_id   = home_team.id,
        home_team_name = home_team.team_name,
        away_team_id   = away_team.id,
        away_team_name = away_team.team_name,
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


# ── Shared simulation helpers (used by bet_engine) ───────────────────────────

def simulate_scores(
    home_team: Team,
    away_team: Team,
    week: int,
    db: Session,
    n_sims: int = N_SIMS,
    scoring: ScoringSettings | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (home_scores, away_scores) arrays of shape (n_sims,)."""
    if scoring is None:
        scoring = PPR
    home_lines = _starters(home_team, week, db, scoring)
    away_lines = _starters(away_team, week, db, scoring)
    home_pts   = np.array([s.adjusted_points for s in home_lines])
    away_pts   = np.array([s.adjusted_points for s in away_lines])
    # Seed consistent with run() so straight/spread/ou share the same game sim
    rng = np.random.default_rng(seed=home_team.id * 10_000 + away_team.id * 100 + week)
    return _simulate_team(home_pts, rng), _simulate_team(away_pts, rng)


def bench_players(
    team: Team,
    week: int,
    db: Session,
    scoring: ScoringSettings | None = None,
) -> list[BenchPlayerLine]:
    """
    Return bench roster slots (offset N_START) with injury-adjusted projections.
    Out/IR → 0.0 pts; Doubtful → 0.25×; Questionable → 0.60×.
    """
    from db.schema import Roster as _Roster
    if scoring is None:
        scoring = PPR
    slots = (
        db.query(_Roster)
        .filter(_Roster.team_id == team.id)
        .order_by(_Roster.id)
        .offset(N_START)
        .all()
    )
    lines: list[BenchPlayerLine] = []
    for slot in slots:
        p = slot.player
        proj = (
            db.query(Projection)
            .filter_by(player_id=p.id, week=week, season=SEASON, source=SOURCE)
            .first()
        )
        raw        = proj.projected_points if proj else 0.0
        inj_status = proj.injury_status    if proj else None
        inj_mult   = INJURY_MULTIPLIERS.get(inj_status or "", 1.0)
        adj        = _adjust_for_scoring(raw * inj_mult, p.position, scoring)
        lines.append(BenchPlayerLine(
            player_id       = p.id,
            name            = p.name,
            position        = p.position,
            injury_status   = inj_status,
            raw_points      = raw,
            adjusted_points = adj,
        ))
    return lines


def simulate_bench_scores(
    home_team: Team,
    away_team: Team,
    week: int,
    db: Session,
    n_sims: int = N_SIMS,
    scoring: ScoringSettings | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (home_bench_scores, away_bench_scores) arrays of shape (n_sims,)."""
    home_lines = bench_players(home_team, week, db, scoring)
    away_lines = bench_players(away_team, week, db, scoring)

    # Use a seed offset distinct from the starter simulation
    rng = np.random.default_rng(
        seed=home_team.id * 10_000 + away_team.id * 100 + week + 1_000
    )

    if home_lines:
        home_pts    = np.array([b.adjusted_points for b in home_lines])
        home_scores = _simulate_team(home_pts, rng)
    else:
        home_scores = np.zeros(n_sims)

    if away_lines:
        away_pts    = np.array([b.adjusted_points for b in away_lines])
        away_scores = _simulate_team(away_pts, rng)
    else:
        away_scores = np.zeros(n_sims)

    return home_scores, away_scores


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


# ── CLI demo ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    matchup_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    week       = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    _COMPARE_SCORINGS = [STANDARD, HALF_PPR, PPR]

    with SessionLocal() as db:
        matchup = db.query(Matchup).filter(Matchup.id == matchup_id).first()
        if not matchup:
            print(f"Matchup {matchup_id} not found.")
            sys.exit(1)

        results = [
            run(
                matchup_id = matchup.id,
                home_team  = matchup.home_team,
                away_team  = matchup.away_team,
                week       = week,
                db         = db,
                scoring    = sc,
            )
            for sc in _COMPARE_SCORINGS
        ]
        home_name = matchup.home_team.team_name
        away_name = matchup.away_team.team_name

        # Capture starters from the league's own scoring for the detail table
        league_scoring = load_scoring_from_db(matchup.league_id, db)
        league_result  = run(
            matchup_id = matchup.id,
            home_team  = matchup.home_team,
            away_team  = matchup.away_team,
            week       = week,
            db         = db,
            scoring    = league_scoring,
        )

    # ── Scoring comparison table ───────────────────────────────────────────────
    print(f"\nMonte Carlo Odds — matchup {matchup_id}  week {week}"
          f"  n={results[0].simulations:,}\n")
    print(f"  {home_name}  vs  {away_name}\n")

    h16 = home_name[:16]
    a16 = away_name[:16]
    COL = 16
    print(f"┌{'─'*26}┬{'─'*(COL*2+5)}┬{'─'*(COL*2+5)}┬{'─'*(COL*2+5)}┐")
    print(f"│{'':26}│ {'Standard':^{COL*2+4}} │ {'Half-PPR':^{COL*2+4}} │ {'PPR':^{COL*2+4}} │")
    print(f"│{'':26}│ {h16:^{COL}} {a16:^{COL}} │ {h16:^{COL}} {a16:^{COL}} │ {h16:^{COL}} {a16:^{COL}} │")
    print(f"├{'─'*26}┼{'─'*(COL*2+5)}┼{'─'*(COL*2+5)}┼{'─'*(COL*2+5)}┤")

    row_mean = "│ {:<24} │".format("Proj score (mean)")
    row_prob = "│ {:<24} │".format("Win probability")
    row_ml   = "│ {:<24} │".format("American moneyline")
    for r in results:
        row_mean += " {:>6.1f}    {:>6.1f}    │".format(r.home_proj_mean, r.away_proj_mean)
        row_prob += " {:>6.1%}   {:>6.1%}    │".format(r.home_win_prob,  r.away_win_prob)
        row_ml   += " {:>+6}    {:>+6}    │".format(r.home_moneyline, r.away_moneyline)
    print(row_mean)
    print(row_prob)
    print(row_ml)
    print(f"└{'─'*26}┴{'─'*(COL*2+5)}┴{'─'*(COL*2+5)}┴{'─'*(COL*2+5)}┘")

    # ── Per-starter detail (league scoring) ───────────────────────────────────
    def _print_starters(label: str, starters: list[StarterLine], sc_type: str) -> None:
        print(f"\n{label} starters  [{sc_type}]\n")
        print("  ┌──────┬────────────────────────────┬──────────┬──────────┐")
        print("  │ Pos  │ Player                     │ FP (PPR) │ Adjusted │")
        print("  ├──────┼────────────────────────────┼──────────┼──────────┤")
        for s in starters:
            print(f"  │ {s.position:<4} │ {s.name:<26} │ {s.projected_points:>8.2f} │ {s.adjusted_points:>8.2f} │")
        raw_total = sum(s.projected_points for s in starters)
        adj_total = sum(s.adjusted_points  for s in starters)
        print("  ├──────┼────────────────────────────┼──────────┼──────────┤")
        print(f"  │      │ {'TOTAL':26} │ {raw_total:>8.2f} │ {adj_total:>8.2f} │")
        print("  └──────┴────────────────────────────┴──────────┴──────────┘")

    _print_starters(home_name, league_result.home_starters, league_result.scoring_type)
    _print_starters(away_name, league_result.away_starters, league_result.scoring_type)
