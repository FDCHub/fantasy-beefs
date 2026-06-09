# Fantasy Beefs — New Thread Handoff

> Created: June 7, 2026
> Last updated: June 8, 2026 (end of day)
> Purpose: Load a fresh dev thread with full current context.

---

## Current Status (June 8, 2026 EOD)

**Rev 1 Decision Engine: COMPLETE (mock-first). Railway: LIVE.**

All seven engine modules built, tested, committed, and pushed to GitHub.
Railway PostgreSQL seeded with mock data. Live API confirmed responding.

**Public URL:** `https://fantasy-beefs-api-production.up.railway.app`
**Test:** `GET /health/team/1?week=1` → 200 OK

---

## What Was Built Today

### Decision Engine Rev 1 — All Modules Done
```
data/provider.py          ✅ DataProvider ABC, MockProvider, YahooProvider stub
engine/projection_engine  ✅ PPR→league scoring, ProjDist(mean, std) output
engine/lineup_optimizer   ✅ Config-driven slot filling, FLEX after starters
engine/season_sim         ✅ Week loop wrapping simulate_scores(), confidence decay
engine/team_health        ✅ Three-horizon assembly, double-discount playoffs
api/health_routes         ✅ /health/team and /health/league endpoints
tools/team_health.html    ✅ Three-horizon heat map, Playbook theme, mock-first
```

### Infrastructure
```
Railway deploy            ✅ FastAPI backend live on Railway US West
PostgreSQL                ✅ Provisioned, seeded (10 teams, 134 players, 6834 projections)
CircularDependencyError   ✅ Fixed in db/schema.py (use_alter=True on beef_challenges/bets FKs)
```

### Data & Auth
```
Yahoo OAuth               ✅ Live end-to-end (cleared June 8)
FantasyPros API key       🔄 Request submitted June 8 — under review
Step 0 grep audit         ✅ Complete — STEP_0_FINDINGS.md committed
```

---

## Immediate Next Actions (priority order)

### 1. YahooProvider fill-in [CLAUDE-CODE]
Fill `data/provider.py` YahooProvider stub with real DB queries.
- `get_league()` → query `LeagueScoring` table + league settings
- `get_roster()` → query `Roster` + `Player` + `Projection` tables
- `get_schedule()` → query `Matchup` table
- `get_projections()` → query `Projection` table (source='fantasypros')
- YAHOO SWAP POINT in `engine/season_sim.py` — replace DB Team lookups
  with provider calls once YahooProvider is live
- OAuth is live; this is unblocked

### 2. Regression test suite [CLAUDE-CODE]
Build `tests/test_rev1.py` with known-answer assertions:
- Same player stat line → correct fantasy points under mock league scoring
- Same line → different points under different scoring config
- Known mock roster/week → correct optimal lineup
- Known matchup → stable win prob (seeded sim)
- Playoff cells flagged low confidence
Required before Yahoo swap per spec.

### 3. FantasyPros API key (pending)
- Request submitted June 8 2026
- Approved → upgrade `connectors/fantasypros_connector.py` to store
  raw stats instead of pre-scored PPR; `ProjectionEngine` does exact
  conversion. One provider file change, engine untouched.
- Not approved → ship with existing PPR + `_adjust_for_scoring()` path.
  Either way Rev 1 ships.

### 4. Phase 2 betting platform [starts next]
Railway is live — Phase 2 is now unblocked.
See `P2_1_MODULE_SPEC.md` and `P2_2_MODULE_SPEC.md` for full spec.
Deadline: Aug 1, 2026.

---

## Key Architecture Facts (ground truth)

**Monte Carlo:** `odds/monte_carlo.py`
- Public functions: `run()`, `simulate_scores()`, `bench_players()`
- `simulate_scores(home_team, away_team, week, db, n_sims, scoring)` → `(np.ndarray, np.ndarray)`
- Seed = `home_team.id * 10_000 + away_team.id * 100 + week`
- `_adjust_for_scoring(raw_ppr_pts, position, scoring)` — MVP scoring conversion

**DataProvider seam:** `data/provider.py`
- New models: `PlayerProj`, `RosterState`, `ScheduleEntry`, `LeagueConfig`
- `MockProvider` reads `mock_league.py` (TEAMS, SCHEDULE) — 10 teams
- `YahooProvider` raises `NotImplementedError` — stub only
- Real league: 12 teams, 14 regular weeks, playoff_start_week=15, 6 playoff teams

**ProjectionEngine:** `engine/projection_engine.py`
- `adjust(player, scoring) → float` — wraps `_adjust_for_scoring()`
- `adjust_roster(players, scoring) → dict[int, ProjDist]` — keyed by player_id
- `ProjDist(mean, std)` — carries variance for Monte Carlo draws

**LineupOptimizer:** `engine/lineup_optimizer.py`
- Config-driven slot counts — adapts to any roster_slots config
- FLEX fills after RB×2 and WR×2 are locked
- Silent skip on empty slots

**SeasonSimulator:** `engine/season_sim.py`
- `simulate(team_id, roster, schedule, config, current_week, db) → list[WeekResult]`
- `WeekResult(week, win_prob, point_margin, opponent_team_id, confidence)`
- `_confidence()` standalone function — reusable by TeamHealth
- YAHOO SWAP POINT marked at two DB Team lookups
- db always injected — never calls SessionLocal()

**TeamHealthAssembler:** `engine/team_health.py`
- `assemble(team_id, week_results, roster, config, current_week) → TeamHealth`
- this_week overlaps rest_of_season (intentional — convenience pointer)
- Playoff confidence = original × 0.6 (double-discount: distance + unknown seeding = 0.36)
- Imports WeekResult from engine.season_sim — not redefined

**Health routes:** `api/health_routes.py`
- `GET /health/team/{team_id}?week=1`
- `GET /health/league/{league_id}?week=1`
- Registered in `api/main.py` via `app.include_router(health_router)`

---

## Qwen Coder-Node Lessons Learned

Qwen (10.0.0.11, Qwen2.5-Coder-7B) works well for pure algorithmic single-file modules.
It fails on anything that calls methods on other project classes.

**Rules for Qwen prompts:**
- Paste actual dataclass definitions inline — never say "read file X"
- Specify exact method signatures inline — never reference them by name only
- State the exact file path explicitly — it defaults to wrong paths
- Do not use for multi-file joins or route handlers

**Claude Code handles:**
- Any module that imports from other project files
- Multi-file joins and route registration
- Anything with external method calls

---

## Security Notes

1. **Yahoo OAuth Client Secret** — appeared in chat June 8. Low risk (read-only
   fantasy access, personal league). No action needed; rotates on app recreate.
2. **Railway PostgreSQL password** — appeared in chat June 8. Low risk (mock data
   only, no PII, no financial data). Rotate via Railway dashboard when convenient:
   `railway.app` → project → Postgres → Settings → Regenerate credentials.

---

## Post-MVP Upgrades (documented, not blocking)

- **FantasyPros → Fantasy Nerds API** ($400/yr) — upgrade projection source
  post-MVP. Fantasy Nerds has weekly + ROS + playoff projections via proper
  REST API. Swap behind DataProvider seam. Engine untouched.
  Documented in `DECISION_ENGINE_ROADMAP.md` § Post-MVP Upgrades.

---

## Railway Info

- **Project:** fantasy-beefs
- **Public URL:** `https://fantasy-beefs-api-production.up.railway.app`
- **Plan:** Trial (30 days / $5.00) — upgrade to Hobby ($5/mo) before trial expires
- **DB:** PostgreSQL, seeded with mock data
- **Deploy:** `railway up` from repo root
- **Seed:** `$env:DATABASE_URL="<PUBLIC_URL>"; python db/schema.py`

---

## Dev Environment

- **Primary:** Lenovo ThinkPad X13 Gen 3, Windows 11, PyCharm
- **Repo:** `FDCHub/fantasy-beefs`, branch: `master`
- **Local path:** `C:\Users\frase\PycharmProjects\fantasy-beefs\`
- **Coder-node:** Qwen 2.5-Coder at `10.0.0.11:11434` via Ollama
- **Claude Code CLI:** PyCharm terminal, repo root

---

## Overall Progress: ~52%

```
Phase 1 — Foundation    ████████████ 100%  ✅ DONE
Phase 2 — Betting       ░░░░░░░░░░░░   0%  ← NEXT
Phase 3 — Decision Eng  ████████░░░░  65%  (Rev 1 mock-first done; Yahoo swap + tests remain)
Phase 4 — Integration   ░░░░░░░░░░░░   0%
```

Deadline: Aug 1, 2026. On pace.

---

*Fantasy Beefs · Our Thing. Your League.*
*Updated June 8, 2026*
