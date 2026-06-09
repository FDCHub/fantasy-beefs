# Fantasy Beefs — Step 0 Findings

> Created: June 8, 2026
> Purpose: Ground truth from B1–B4 grep audit. Overrides any assumption
> in P3_1_REV1_MODULE_SPEC.md that conflicts with findings below.
> Read this alongside the spec. Findings win.

---

## B1 — Per-Week Monte Carlo

**Status: EXISTS. Do not rebuild.**

File: `odds/monte_carlo.py`

**Public functions:**

```python
run(
    matchup_id: int,
    home_team:  Team,
    away_team:  Team,
    week:       int,
    db:         Session,
    n_sims:     int = N_SIMS,       # default 10,000
    scoring:    ScoringSettings | None = None,
) -> OddsResult
```

```python
simulate_scores(
    home_team: Team,
    away_team: Team,
    week:      int,
    db:        Session,
    n_sims:    int = N_SIMS,
    scoring:   ScoringSettings | None = None,
) -> tuple[np.ndarray, np.ndarray]   # (home_scores, away_scores) shape (n_sims,)
```

**Key internals:**
- `N_SIMS = 10_000`
- `STD_PCT = 0.20` — 20% of projected points as σ
- `MIN_STD = 0.5` — floor for zero-projection players
- `N_START = 9` — QB RB RB WR WR TE FLEX K DEF
- Seed = `matchup_id * 1_000 + week` — deterministic per matchup/week
- `_simulate_team(pts, rng)` — draws Normal(proj, σ) per starter, sums, returns (N_SIMS,) array

**Scoring adjustment — already exists here:**
`_adjust_for_scoring(raw_ppr_pts, position, scoring)` converts FantasyPros PPR
projections to the target scoring system using position-average stat proxies
(`_AVG_STATS`). This is approximate (position averages, not real player stats).
The FantasyPros API key (pending approval) will enable raw stats → exact conversion.
Until then, this function is the live scoring adjustment path.

**`ScoringSettings` dataclass:**
```python
@dataclass
class ScoringSettings:
    scoring_type:     str    # standard | half_ppr | ppr | custom
    rec_points:       float
    pass_td_points:   float
    rush_td_points:   float
    rec_td_points:    float
    bonus_100yd_rush: float
    bonus_100yd_rec:  float
```

Presets defined: `STANDARD`, `HALF_PPR`, `PPR`.
`load_scoring_from_db(league_id, db)` loads league-specific settings; falls back to
`HALF_PPR` if not found.

**SeasonSimulator interface implication:**
`season_sim.py` calls `simulate_scores()` — NOT `run()`. `run()` requires a
`Matchup` DB object and returns full `OddsResult`. `simulate_scores()` takes
two `Team` objects and returns raw score arrays — lighter, right shape for the
season loop.

---

## B2 — Normalized Models

**Status: EXISTS but THIN. Extension required for decision engine.**

File: `connectors/models.py`

**What exists:**

```python
@dataclass
class NormalizedPlayer:
    name:     str
    position: str   # QB | RB | WR | TE | FLEX | K | DEF

@dataclass
class NormalizedRoster:
    team_id:    int
    team_name:  str
    owner:      str
    email:      str
    players:    list[NormalizedPlayer]
    week_score: float   # past actual score — NOT a projection

@dataclass
class NormalizedMatchup:
    week:  int
    home:  NormalizedRoster
    away:  NormalizedRoster
    # properties: winner, loser, margin

@dataclass
class NormalizedLeague:
    season:   int
    week:     int
    matchups: list[NormalizedMatchup]
    # properties: teams, highest_scorer, lowest_scorer
```

**What is MISSING for the decision engine:**

| Missing field | Needed by | Impact |
|---|---|---|
| `player_id` on `NormalizedPlayer` | ProjectionEngine lookup | Can't match player to projection without ID |
| `injury_status` on `NormalizedPlayer` | LineupOptimizer | Can't exclude OUT/IR players |
| Scoring rules | ProjectionEngine | No league scoring config in the model |
| Playoff week config | SeasonSimulator | Can't identify playoff weeks |
| Roster slot / position eligibility | LineupOptimizer | Can't build legal lineup |
| `week_score` is historical | SeasonSimulator | Forward-looking model needs projected score, not actual |

**Decision:** define new extended models for the decision engine alongside the
existing ones. Do NOT modify the existing models — they're used by the feed
and other live systems. New models live in `data/provider.py`.

**New models needed in `data/provider.py`:**

```python
@dataclass
class PlayerProj:
    player_id:     int
    name:          str
    position:      str
    injury_status: str | None   # None | "questionable" | "doubtful" | "out" | "ir"
    projected_pts: float        # league-scoring-adjusted (from ProjectionEngine)

@dataclass
class RosterState:
    team_id:   int
    team_name: str
    week:      int
    players:   list[PlayerProj]

@dataclass
class ScheduleEntry:
    week:           int
    home_team_id:   int
    away_team_id:   int

@dataclass
class LeagueConfig:
    league_id:      int
    season:         int
    n_teams:        int
    playoff_start_week: int
    n_playoff_teams:    int
    scoring:        ScoringSettings   # reuse from monte_carlo.py
    roster_slots:   dict[str, int]    # e.g. {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1}
```

---

## B3 — FantasyPros Projections

**Status: CONNECTOR EXISTS. Do not rebuild.**

File: `connectors/fantasypros_connector.py`

**What it does:**
- HTML scraper (BeautifulSoup) — NOT CSV download, NOT API
- Fetches six positions: QB, RB, WR, TE, K, DST
- No authentication required
- Upserts into `Projection` table with `source='fantasypros'`
- Week parameter passed as query string `?week=N&scoring=PPR&year=2024`

**What it stores:**
`projected_points` = pre-scored **PPR fantasy points** (the FPTS column).
This is NOT raw production stats (yards/TDs/rec). It is already scored under
FantasyPros' PPR system.

**Scoring implication:**
The `_adjust_for_scoring()` function in `monte_carlo.py` converts the stored
PPR number to the league's scoring using position-average proxies. This path
works for MVP but is approximate.

**Post-MVP upgrade path (when FantasyPros API key arrives):**
Replace HTML scrape with API call. Store raw production stats (pass_yds,
rush_yds, rec, TDs etc.) instead of pre-scored FPTS. `ProjectionEngine` then
does exact scoring conversion using real player stat lines. This is the
"upgrade to raw stats" milestone — one provider file change, engine untouched.

**`Projection` DB schema fields (from `db/schema.py`):**
```
player_id        int
week             int
season           int
projected_points float   # PPR pre-scored
actual_points    float
source           str     # 'fantasypros' | 'yahoo' | 'espn'
injury_status    str     # nullable
```

**`DataProvider.get_projections()` implication:**
The MockProvider reads from `mock_league.py` seed data.
The YahooProvider stub reads from the `Projection` table (already populated
by `fantasypros_connector.py`). No new fetcher needed for MVP — the connector
is the data pump; the provider is just the query layer.

---

## B4 — Mock League

**Status: EXISTS. Ready to use.**

File: `mock_league.py` (repo root)

**Entry points:**
```python
from mock_league import TEAMS, SCHEDULE
```

```python
# db/schema.py
def seed_from_mock(session: Session | None = None) -> None
```

**Called by:** `db/schema.py` (main seed), `feed/league_feed.py`, `auth/jwt_auth.py`

**MockProvider implication:**
`MockProvider` in `data/provider.py` imports `TEAMS` and `SCHEDULE` from
`mock_league.py` and calls `seed_from_mock()` to populate the DB for testing.
This is the deterministic fixture for all Rev 1 acceptance tests.

---

## Spec Corrections Summary

| Spec assumption | Reality | Action |
|---|---|---|
| Build `FantasyProsProvider` from scratch | `fantasypros_connector.py` already exists | Wire to existing connector; don't rebuild |
| `ProjectionEngine` receives raw stats | Stored projections are pre-scored PPR | MVP: use `_adjust_for_scoring()` from monte_carlo.py; post-MVP: upgrade to raw stats via API |
| `NormalizedLeague/Roster` are sufficient | Models are thin — missing player_id, injury_status, scoring config, playoff config | Define new `LeagueConfig`, `RosterState`, `PlayerProj` models in `data/provider.py` |
| `simulate_scores()` signature unknown | Confirmed: takes two `Team` objects + week + db + scoring | `SeasonSimulator` calls `simulate_scores()` directly — interface locked |
| Mock league existence unconfirmed | `mock_league.py` confirmed, `seed_from_mock()` confirmed | MockProvider reads directly from these |

---

## Build Order Correction (Rev 1)

Original spec order stands with these amendments:

```
1. data/provider.py                [CLAUDE-CODE]
   — Define new models: LeagueConfig, RosterState, PlayerProj
   — MockProvider reads mock_league.py (confirmed exists)
   — YahooProvider stub queries Projection table (populated by existing connector)
   — DataProvider.get_projections() returns PlayerProj (pre-scored, adjusted)

2. engine/projection_engine.py     [QWEN]
   — MVP: wraps _adjust_for_scoring() from monte_carlo.py
   — Input: pre-scored PPR float + position + ScoringSettings
   — Output: league-adjusted float
   — Post-MVP hook: raw stats path ready for API upgrade

3. engine/lineup_optimizer.py      [QWEN]
   — Uses PlayerProj.injury_status to exclude OUT/IR
   — Uses LeagueConfig.roster_slots for legal lineup rules

4. engine/season_sim.py            [CLAUDE-CODE]
   — Calls simulate_scores() from odds/monte_carlo.py (DO NOT REBUILD)
   — Signature confirmed: (home_team, away_team, week, db, n_sims, scoring)

5–7. team_health.py, health_routes.py, team_health.html  [QWEN]
   — Unchanged from spec
```

---

## Open Decision (non-blocking for Rev 1)

**FantasyPros API key** — request submitted June 8 2026, under review.
- Approved → upgrade connector to store raw stats; `ProjectionEngine` does exact conversion
- Not approved / delayed → ship Rev 1 with existing PPR + `_adjust_for_scoring()` path
- Either way, Rev 1 ships. The seam makes the upgrade mechanical.

---

*Fantasy Beefs — Step 0 Findings · June 8, 2026*
*Our Thing. Your League.*
