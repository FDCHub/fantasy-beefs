# FR-7.30 — Players Table Growth (yahoo_id identity + runtime sync)

**Status:** APPROVED and SHIPPED 2026-07-16. Built unchanged from this spec.
Five commits: `5169507` (schema+migration), `746fa40` (backfill), `4ee941d`
(sync step), `385a50e` (capture refactor). 18/18 suites green. Not deployed.
**Date:** 2026-07-15
**Money-path:** No. Not Opus-gated.
**Depends on:** Nothing. Blocks FR-7.29, FR-6.9.
**Findings addressed:** FR-7.30

---

## 1. Problem

The `players` table never grows. Only two one-time seeders write to it
(`seed_real_2025_season_LIVE.py:592`, `db/schema.py:1072`). No runtime path
inserts a player.

A mid-season practice-squad call-up is therefore invisible to the system,
and it hard-fails FR-5.7's weekly capture: `_step_capture_roster_slots`
resolves players by `player_map.get(name.lower())`, appends any miss to
`unresolved`, and returns `_fail(...)` writing zero rows for the entire
league (`tuesday_sync.py:585-603`). One unknown player aborts the whole
week's capture.

Root cause is narrower than "no insert path." The `players` table has **no
external ID column**. `name` (unique) is the sole join key to any external
system. Yahoo's roster response carries `player_id`; `player_id_map` carries
`yahoo_id` for 4,361 of 4,777 rows. Both are unusable — there is no column
on `players` to bridge into. Every path terminates in a name string match.

---

## 2. Rulings

### R1 — Identity key is Yahoo `player_id`, stored on `players`

Add `players.yahoo_id`. Yahoo is the system of record for who is rostered;
resolution keys on Yahoo's ID, not on a name both systems happen to spell
the same way.

**Verified:** Yahoo returns a stable numeric `player_id` for every rostered
entity including team defenses (DEF occupies a dedicated 100000-range, e.g.
`100033` = Ravens, with full `player_key` `461.p.100033`). DEF is not a
special case.

### R2 — `yahoo_id` is UNIQUE, nullable

`unique=True, nullable=True`. Postgres permits multiple NULLs in a unique
column, so the one un-backfillable row (see R5) does not block the
constraint.

Rationale: `yahoo_id` is the real identity key. A non-unique identity column
invites the duplicate-player problem this finding exists to prevent. A
double-insert bug throws loudly at write time rather than silently
duplicating.

### R3 — Crosswalk (`player_id_map`) is NOT used

`player_id_map` covers 148/180 of the current roster union. The 32 misses
are all 14 team DEFs (a player crosswalk has no team defenses) plus ~18
2025 rookies (Cam Skattebo, Ashton Jeanty, Tyler Warren, Quinshon Judkins,
Tetairoa McMillan, Tyler Loop, et al).

Yahoo's roster response supplies every field `players` needs — `full_name`,
`display_position`, `editorial_team_abbr` — so the crosswalk adds nothing
and imports an 18% gap. Critically, the gap population *is* the target
population: a call-up is a rookie by definition.

The crosswalk stays dormant. It remains a projections concern
(`fantasypros_id`), not a roster concern.

### R4 — New sync step hoists the fetch; capture accepts it

New `_step_sync_players(league_id, week, db) -> (StepResult, rosters)` at
**Step 0.25** — after `_step_refresh_scores` (Step 0), before
`_step_capture_roster_slots` (Step 0.5). Hard requirement is *before
capture*; ordering relative to refresh is immaterial.

`_step_capture_roster_slots` signature becomes
`(league_id, week, db, rosters=None)`. When `rosters` is provided it uses
them; when `None` it fetches its own (preserves current behavior, keeps
existing tests green, and covers the case where sync failed).

**Why hoist rather than let each step fetch:** `_build_yahoo_query()` is not
cheap to call twice. yfpy's `YahooFantasySportsQuery.__init__` calls
`self._authenticate()` (`query.py:231`), which constructs an OAuth2 session
and refreshes the access token over the network if expired
(`query.py:330-331`). Two independent steps = two OAuth setups, up to two
token refreshes, and 24 `get_team_roster_by_week` calls per Tuesday instead
of 12 — plus a race window where sync and capture see different rosters.

The orchestrator already uses the return-and-pass idiom twice
(`r, refresh_result = _step_refresh_scores(...)`,
`r, settlement = _step_settle_bets(...)`). This follows that pattern; it
does not invent one.

### R5 — Backfill is one-time, name-bootstrapped, one manual row

**Verified:** `players` (180) ≡ `rosters` (180) ≡ week-1 Yahoo roster union.
15 players × 12 teams, zero orphans, zero roster rows with a missing player.
Every existing row is currently rostered, so a roster sweep reaches all 180.

Name-match coverage: **179/180**. The single miss is `id=147 WR Joshua
Palmer` — a Josh/Joshua spelling variance, not an unrostered player.

The backfill bootstraps off the very name-matching this finding retires.
That is acceptable because it runs **once**: after backfill, resolution is
ID-based and the name-match is dead. Palmer gets a manual `UPDATE`.

### R6 — Sync inserts silently; failure degrades to current behavior

Sync inserts unrecognized players without halting. Logs each insert. Does
not flag for review.

Rationale: 12 GMs, no one watching Tuesday runs. A blocking flag means a
call-up stalls capture until a human looks — worse than the status quo it
replaces.

**Verified failure semantics:** the orchestrator is log-and-continue —
"Each step is isolated — failures are logged and the run continues"
(`tuesday_sync.py:1238`). Only the settlement gate breaks isolation. So a
failed `_step_sync_players` does not halt the run; capture proceeds, hits an
unresolved player, and fails all-or-nothing exactly as it does today.
**Sync failing degrades to current behavior, never worse.** This is correct
and intentional.

### R7 — Sync touches `players` only, never `Roster`

`Roster` is seeder-only at runtime (`seed_real_2025_season_LIVE.py:606`,
`db/schema.py:1085`) — same status as `players`. Growing `Roster` is
FR-7.29's job. FR-7.30 is strictly `players`.

---

## 3. Build

### 3.1 Migration — `db/migrations/migrate_players_yahoo_id.py`

Follows the established idiom exactly (per
`migrate_leagues_economy_columns.py`): standalone script, run manually, not
imported anywhere. No Alembic exists in this repo.

- Guard: `from db.schema import engine`; abort unless `DATABASE_URL` set and
  `"postgres" in str(engine.url)`.
- Idempotent: read `information_schema.columns` for `table_name='players'`
  before altering; skip if `yahoo_id` present.
- DDL inside one `engine.begin()`:
  - `ALTER TABLE players ADD COLUMN yahoo_id VARCHAR`
  - `CREATE UNIQUE INDEX ... ON players (yahoo_id)` — as a separate
    statement so the NULL semantics are explicit and the index is nameable.
- Verify: re-read columns, ORM smoke read.
- Three-part structure (before / add / after), additive only.

### 3.2 Schema — `db/schema.py`

```python
yahoo_id = Column(String, nullable=True, unique=True)
```

Matches the existing `nfl_team = Column(String(4), nullable=True)` precedent.
`Player` currently has no `__table_args__`, no `UniqueConstraint`, no
`Index` — only the inline `unique=True` on `name`. This adds a second inline
unique; no `__table_args__` needed.

`name` keeps its `unique=True` for now. Retiring it is out of scope.

### 3.3 Backfill — `scripts/backfill_players_yahoo_id.py`

One-time, offline, matching `scripts/resolve_player_nfl_teams.py` in shape.

1. `_build_yahoo_query(...)` once.
2. Fetch all 12 rosters, week 1.
3. Build `{full_name.lower(): player_id}`.
4. For each of the 180 rows: `UPDATE players SET yahoo_id = ... WHERE id =
   ...` on name match.
5. Report matched / unmatched. Expect 179 / 1.
6. Print the unmatched row(s) with a ready-to-run manual `UPDATE`.

Idempotent: skips rows that already have a `yahoo_id`.

### 3.4 New step — `notifications/tuesday_sync.py`

```python
def _step_sync_players(league_id, week, db) -> tuple[StepResult, list | None]:
```

- Nested `_fail(...)` closure, matching the per-step idiom (there is no
  module-level `_fail`).
- `_build_yahoo_query(yahoo_league_id)` once.
- Resolve DB team ids → Yahoo ids via the existing `resolver.db_to_yahoo`.
- Fetch each team's roster; collect into `rosters`.
- Build `existing = {yahoo_id: player_id}` from `players` where `yahoo_id`
  is not null.
- For each roster player not in `existing`: insert
  `Player(name=full_name, position=display_position,
  nfl_team=editorial_team_abbr.upper(), yahoo_id=player_id)`.
- **`editorial_team_abbr` is mixed-case from Yahoo** (`Bal`, `Pit`) vs the
  DB's uppercase `nfl_team` (`BAL`). Must `.upper()`. Verified in recon.
- `display_position` per the standing rule — never
  `selected_position_value`.
- One `db.commit()`. On exception: `db.rollback()`, return `_fail(...)`.
- Return `(StepResult(..., {"inserted": n, "teams": 12}), rosters)`.
- On any failure return `(StepResult(success=False, ...), None)` — capture
  then falls back to its own fetch.

### 3.5 Capture refactor — `_step_capture_roster_slots`

- Signature: `(league_id, week, db, rosters=None)`.
- If `rosters is None`: build query, fetch as today.
- If `rosters` provided: skip the query build and the fetch loop entirely.
- `player_map` changes from `{name.lower(): pid}` to `{yahoo_id: pid}`,
  built from `players` where `yahoo_id` is not null.
- Resolution: `pid = player_map.get(str(p.player_id))`.
- The `unresolved` / all-or-nothing contract is **unchanged**. After sync
  has run, an unresolved player should be impossible — but the guard stays
  as a correctness backstop.

### 3.6 Orchestrator — `run_tuesday_sync`

Between current lines 1261 and 1263:

```python
# Step 0.25 — grow the players table from live rosters (FR-7.30), and
# hand the fetched rosters forward so capture doesn't re-fetch.
r, rosters = _step_sync_players(league_id, week, db)
steps.append(r)
print(f"  [0.25] sync_players  — {'OK' if r.success else 'FAILED'}: {r.message}")

# Step 0.5 — capture this week's roster slots (FR-5.7). ...
r = _step_capture_roster_slots(league_id, week, db, rosters=rosters)
```

---

## 4. Tests

1. Migration idempotency — run twice, second is a no-op.
2. Unique constraint — two rows, same `yahoo_id` → raises.
3. Multiple NULL `yahoo_id` rows coexist (the Palmer case).
4. Backfill matches 179/180 against a fixture; reports Palmer unmatched.
5. Backfill is idempotent — second run updates zero rows.
6. Sync inserts an unrecognized player with correct name/position/team,
   `nfl_team` uppercased from Yahoo's mixed-case.
7. Sync inserts nothing when all players are known.
8. Sync returns `rosters`; capture consumes them without calling
   `_build_yahoo_query` (assert via mock — this is the fetch-once proof).
9. Capture with `rosters=None` still fetches its own (backward compat).
10. Sync failure → returns `(fail, None)` → capture falls back to its own
    fetch → run continues (log-and-continue preserved).
11. Capture resolves by `yahoo_id`, not name — fixture where a player's DB
    name and Yahoo name differ but `yahoo_id` matches: resolves cleanly.
12. Capture still fails all-or-nothing on a genuinely unknown `yahoo_id`.
13. DEF round-trip: `100033` / `Ravens` inserts and resolves.
14. Existing FR-5.7 suite: 18/18, zero regressions.

Fixture discipline: test 11 is the one that proves the fix. A fixture where
name and `yahoo_id` both match proves nothing — the bug and the fix must
diverge in the data.

---

## 5. Sequencing

1. Migration script written, reviewed, run against production.
2. Schema column added.
3. Backfill run. Palmer resolved manually. Verify 180/180 non-null.
4. Sync step + capture refactor + orchestrator wiring built and tested.
5. Commit. **Do not deploy** — FR-7.34 (Railway variable propagation)
   unverified.

Steps 1-3 must complete before step 4's tests are meaningful — capture keys
on `yahoo_id`, which does not exist until the backfill lands.

---

## 6. Open items recorded, not addressed here

- **FR-7.35 (new)** — `player_id_map` docstring claims it resolves NFL teams
  "for per-game kickoff locking." It does not. Nothing queries it live;
  `players.nfl_team` was backfilled offline by
  `scripts/resolve_player_nfl_teams.py`. Third doc-vs-reality gap this
  session. Docstring fix + register entry.
- **FR-7.31 count correction** — the v48 opener's "twelve week-blind Roster
  reads across seven files" is wrong. Live: 12 read *statements* across **4**
  files (`bet_engine` 7, `beef_engine` 3, `monte_carlo` 1, `war_room` 1), or
  13 *functions* across 7 files. Two additional Roster-reading files the
  opener omits entirely: `api/main.py:443` (roster endpoint — a genuine
  current-read) and `feed/league_feed.py:414` (a `__main__` demo). True
  footprint is 9 files. FR-7.31's classification pass must work from the
  enumerated table, not the 12/7 figure.
- **Naming** — the opener writes `roster_for_week()`; the live helper is
  `_roster_for_week` (leading underscore). FR-7.31 should confirm intent
  before adding `roster_current()` beside it.
- **`players.name` unique** — retained. Retiring it once `yahoo_id` is the
  identity key is a separate decision.
- **Season rollover** — 2026 rosters will contain ~1500 unknown players.
  Sync is a trickle, not a bulk loader. A separate 2026 seed runs first;
  sync handles in-season deltas only. Out of scope here.

---

## 7. FR-7.31 collision check

**No shared functions.** Verified:

- `_step_capture_roster_slots` reads `RosterSlot` and `players`. It does not
  read the `Roster` table. None of the 15 Roster-read sites are in
  `tuesday_sync.py`.
- `player_map` keying exists in exactly two places: the capture step and
  `seed_yahoo_projections._build_player_name_map`. No FR-7.31 Roster-read
  site uses `player_map`.
- Only shared module is `db/roster_read.py` — FR-7.31 adds `roster_current()`
  there; FR-7.30 adds nothing there. Additive, not a collision.

Safe to build independently.
