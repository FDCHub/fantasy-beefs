# Fantasy Beefs — P3.1 Rev 1 MODULE_SPEC: Team Health

> Location: `fantasy-beefs/tools/`
> Created: June 7, 2026
> Status: Ready to build · Mock-first
> Stack: Python 3.12 · SQLAlchemy 2.0 · SQLite → PostgreSQL · FastAPI · NumPy
> Prereq reading: `DECISION_ENGINE_ROADMAP.md`
> Build target: ≈2–3 weeks (sim core already exists; this schedules it across a season)

---

## Scope of Rev 1

Read the roster + schedule (mock now, Yahoo later), run the **existing per-week Monte
Carlo** across the **remaining schedule**, and render a **three-horizon heat map** of
team health. **No hypotheticals in Rev 1** — evaluate the team as it stands. Answers:
*where am I strong/weak, and when.*

Out of scope for Rev 1 (later revs): trades, waivers, candidate moves, Decision Value,
before/after diffs, The War Room, The Sit-Down, Cooperating.

**LLM conversational window — NOT in Rev 1.** The query box ("what's my biggest weakness
in Weeks 12–17?" — The Brain) lands in Rev 3. Reason: a conversational assistant is only
as good as what it can query, and Rev 1 has no concept of a *move* — only the team as it
stands. A chat layer in Rev 1 could narrate the heat map but could not recommend
anything, because recommendations need roster-state evaluation + Decision Value (Rev 2+).
It would invite the exact questions it cannot answer ("so what do I DO?"). The
conversational layer is also where the Qwen-vs-Claude-API inference architecture (prompt
packing, latency, cost) actually bites — real work that would balloon a 2–3 week rev.

**Optional Rev 1 stretch — static AI summary (not a chat).** A single generated
paragraph describing the team's three-horizon health (the docs' free-tier "weekly
outlook"). One call, no back-and-forth, makes no recommendations. Cheap and honest.
Stretch goal, not core. If built, it runs through the same local-Qwen / Claude-API
path that the Rev 3 conversational layer will later use — a small forward-compatible
toehold, not a throwaway.

---

## Architecture (Rev 1 slice of the spine)

```
DataProvider (interface)
  ├── MockProvider      [build now]   reads seeded 17-week mock league
  └── YahooProvider     [stub now, fill when OAuth lands]
        │ emits NormalizedLeague / NormalizedRoster / NormalizedMatchup
        │ get_projections() returns RAW production stats (NOT fantasy points)
        ▼
ProjectionEngine       [NEW]   raw production + league scoring rules → fantasy points
        │                       (league logic, NOT source logic — one path, all leagues)
        │ emits ProjDist (mean + variance) in THIS league's fantasy points
        ▼
LineupOptimizer        [NEW]   picks the highest-projected legal lineup for a roster/week
        ▼
SeasonSimulator        [NEW]   week loop calling the EXISTING per-week sim
        │                       (per-week sim = P0 Module 6, DO NOT rebuild)
        ▼
TeamHealth             [NEW]   assembles three-horizon results per team
        ▼
/health API + Heat-Map view    [NEW]
```

**The data-provider seam is the load-bearing join.** Engine consumes normalized models
only. Mock and Yahoo providers both emit the SAME normalized shapes (P0:
`NormalizedLeague`/`NormalizedRoster`/`NormalizedMatchup`). Build the interface first.

---

## Files

```
NEW:
  data/provider.py            — DataProvider ABC + MockProvider + YahooProvider stub
  engine/projection_engine.py — raw FantasyPros production → league fantasy points
  engine/lineup_optimizer.py  — optimal legal lineup for (roster, week)
  engine/season_sim.py        — week-loop wrapper over existing per-week sim
  engine/team_health.py       — three-horizon assembly per team
  api/health_routes.py        — /health/* endpoints
  tools/team_health.html      — standalone heat-map view (Playbook design system)

REUSE (do not rebuild):
  <existing per-week Monte Carlo module from P0 M6>
  <FantasyPros projection loader, P0 M3>
  <NormalizedLeague / NormalizedRoster / NormalizedMatchup models, P0>
  mock_league.py (17-week seeded data)
```

---

## Component Specs

### 1. DataProvider seam — `data/provider.py`  `[CLAUDE-CODE]`

Abstract base class. Both providers return normalized models so the engine is
source-agnostic. This is the swap point; it is the join everything else hangs on.

```
class DataProvider(ABC):
    def get_league(self, league_id) -> NormalizedLeague        # settings, playoff weeks, roster rules
    def get_roster(self, team_id, week) -> NormalizedRoster     # full roster as of week
    def get_schedule(self, league_id) -> list[NormalizedMatchup]# full regular-season schedule
    def get_projections(self, week) -> dict[player_id, RawProj]# RAW production stats per player

class MockProvider(DataProvider):   # reads mock_league.py — deterministic
class YahooProvider(DataProvider):  # STUB now; fill when OAuth lands
```

`RawProj` = projected production line (pass/rush/rec yards, receptions, TDs, etc.) —
NOT fantasy points. Fantasy points are league-relative and are computed downstream by
the ProjectionEngine. Keeping raw production here means scoring lives in ONE place.

**Acceptance:** MockProvider returns valid normalized models for all 17 weeks; swapping
provider requires changing one instantiation line, nothing in the engine.

---

### 1b. ProjectionEngine — `engine/projection_engine.py`  `[QWEN]`

Ingest raw FantasyPros production projections, load the league's scoring rules (from
`NormalizedLeague`), apply the scoring formula per player per position, and emit
`ProjDist` (mean + variance) in **this league's** fantasy points. Sits between the
provider and the optimizer — nothing downstream ever sees raw stats.

Why its own module: scoring is *league* logic, not *source* logic. Half-PPR vs.
full-PPR, 4- vs. 6-point passing TDs, yardage bonuses — the same raw line becomes a
different point total per league. Your 10-GM and 12-GM leagues may score differently.
One engine, one scoring path, shared by both leagues and every future data source. If
conversion lived inside providers, the formula would scatter across every source.

Variance handling: carry FantasyPros range-of-outcome if available; otherwise derive
position-based variance (the per-week sim already expects mean + variance for betting —
reuse that variance convention).

**Acceptance:** a hand-checked player stat line yields the expected point total under
the mock league's scoring AND the *same* line yields a *different* total under a second
scoring config — proving it reads league settings rather than hardcoding.

---

### 2. LineupOptimizer — `engine/lineup_optimizer.py`  `[QWEN]`

Given a roster and a week, return the highest-projected legal starting lineup under the
league's roster rules (from `NormalizedLeague`). Honor positional slots, FLEX, bye
weeks (a player on bye projects 0 and won't be selected), and injury status (OUT/IR
excluded from the eligible pool; Questionable allowed).

**Acceptance:** for a known mock roster/week, returns the expected optimal lineup; a
player on bye is never selected; total projected points match a hand-checked figure.

---

### 3. SeasonSimulator — `engine/season_sim.py`  `[CLAUDE-CODE]`

The week loop. For each remaining week in the schedule:
1. Optimize the team's lineup (LineupOptimizer).
2. Optimize the scheduled opponent's lineup.
3. Call the **existing per-week Monte Carlo** on the two lineup totals → win prob.
4. Record win prob + projected point margin for that week.

Then aggregate:
- **This Week** = next scheduled week's result.
- **Rest of Season** = per-week results through the regular-season finish.
- **Playoffs** = playoff-week results. Rev 1 uses the **generic elite opponent** model
  (stable, no seeding). Mark playoff cells lower-confidence.

Confidence metric per cell: widen with distance (roster drift compounds). Near-term
cells report tight intervals; far cells report wide. Surface confidence so the heat map
can blur far cells.

**Acceptance:** runs the full remaining schedule on mock data without rebuilding the
per-week sim; results are deterministic given the seeded mock; playoff cells flagged
low-confidence.

---

### 4. TeamHealth — `engine/team_health.py`  `[QWEN]`

Assemble SeasonSimulator output into the three-horizon structure per team, plus simple
diagnostics that fall out for free: weakest position (lowest projected slot across the
season), upcoming bye clusters, future-weakness flag (a position strong now that dips
later from byes/schedule).

**Output shape:**
```
TeamHealth{
  team_id,
  this_week:  {win_prob, point_margin, opponent, confidence},
  rest_of_season: [ per-week {week, win_prob, point_margin, opponent, confidence} ],
  playoffs:   [ per-playoff-week {week, win_prob, point_margin, confidence} ],
  weakest_position, bye_clusters, future_weakness_flags
}
```

**Acceptance:** structure populated for every mock team; weakest-position call matches a
hand-checked roster.

---

### 5. API — `api/health_routes.py`  `[QWEN]`

```
GET /health/team/{team_id}        → TeamHealth JSON
GET /health/league/{league_id}    → all teams' TeamHealth (power-ranking style)
```

Thin. Calls the engine, serializes. No math in the route.

**Acceptance:** endpoints return well-formed JSON matching the TeamHealth shape.

---

### 6. Heat-Map view — `tools/team_health.html`  `[QWEN]`

Single self-contained HTML, **Playbook design system** (light parchment theme:
`--slate #f5f2ec`, orange `#c4501a`, gold `#8a6a20`, green `#1e6b46`, red `#8a2020`;
Playfair Display + DM Mono + DM Sans; mobile-first, max-width 480px). Matches the
existing tools' look and feel.

**The heat map:** rows = horizons (This Week / Rest of Season / Playoffs) or weeks;
columns = weeks within a horizon. Each cell:
- **color** = win-probability delta vs. a 50% baseline (green = favored, red = underdog)
- **number** = projected point margin
- **blur / opacity** = inverse of confidence (far cells visibly softer; sharpen as
  weeks approach)

Fetches from `/health/*`. **Mock-first:** ship with a baked-in mock JSON response and a
marked `// API SWAP POINT` where the real `fetch('/health/team/...')` plugs in — same
pattern as the Odds Calculator and the trade-tool demo.

**Acceptance:** renders three horizons from mock JSON; far cells visibly blurrier;
no external deps beyond the Google Fonts link.

---

## Build Order (Rev 1)

```
1. data/provider.py + MockProvider        [CLAUDE-CODE]  ← seam first, everything needs it
2. engine/projection_engine.py            [QWEN]         ← raw stats → league points
3. engine/lineup_optimizer.py             [QWEN]
4. engine/season_sim.py                   [CLAUDE-CODE]  ← wraps existing per-week sim
5. engine/team_health.py                  [QWEN]
6. api/health_routes.py                   [QWEN]
7. tools/team_health.html                 [QWEN]
8. YahooProvider fill-in                   [CLAUDE-CODE]  ← when OAuth lands; swap behind seam
```

Steps 2, 3, 5, 6, 7 can run on Qwen in parallel once the seam (1) and the sim wrapper
(4) exist and their interfaces are fixed. The ProjectionEngine (2) only needs the
provider's RawProj shape and the league scoring rules — both defined by the seam.

---

## Test Discipline (carry the Odds Calculator habit)

Deterministic mock data is the test fixture. Assert known-answer cases:
- A player's raw stat line yields a hand-checked fantasy-point total under the mock
  league's scoring — and a DIFFERENT total under a second scoring config (proves the
  ProjectionEngine reads league settings, not hardcoded points).
- A specific mock roster/week yields a hand-checked optimal lineup + point total.
- A specific matchup yields a stable win prob (seeded sim).
- Playoff cells are flagged low-confidence.
Lock these as a regression suite before the Yahoo swap, exactly as Rev 2.0 odds math was
verified in Node before going live.

---

## Definition of Done — Rev 1

- Three-horizon heat map renders for the mock league, every team.
- Engine reads only normalized models; provider swap is a one-line change.
- Existing per-week sim reused, not rebuilt.
- Regression suite green on mock data.
- YahooProvider swaps in cleanly once OAuth is live → real value on the real league.

---

*Fantasy Beefs — P3.1 Rev 1 MODULE_SPEC · June 7, 2026*
