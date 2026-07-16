# Fantasy Beefs — New Thread Handoff — v48

**Session date:** 2026-07-15 (Session 2)
**HEAD at close:** `8201617` — FR-5.7, pushed to origin/master, working tree level with origin.
**Launch:** August 1, 2026. Season starts September.

---

## What shipped

**FR-5.7 — RosterSlot weekly capture + week-aware settlement reads.** Commit `8201617`. Built, tested (26 new assertions, 18/18 suites, zero regressions), committed, pushed. **Not deployed** — deliberate, see FR-7.34.

Full detail in `FantasyBeefs_Findings_Register_Update_2026-07-15_Session2.md`. Short version: new Step 0.5 capture job in `tuesday_sync.py`, new `db/roster_read.py` helper (`_roster_for_week`), four read-sites repointed to week-aware reads, one dead function deleted.

---

## What was ruled

**FR-7.29's design is complete** — all four open questions resolved. Spec: `FR_7_29_ROSTER_REFRESH_MODULE_SPEC_DRAFT.md`. 6-hour refresh floor; GM-triggered refresh-and-quote on the vs-card; both teams refreshed at challenge issuance; structured diff to GM B; one-round accept/decline/rechallenge terminating with GM A's accept-or-decline. Pool bets need nothing beyond the floor.

**The trio ranks ahead of the ledger-migration family.** Odds accuracy is visible to every GM on every screen. The ledger family is real debt but invisible so long as balances come out correct. Visible trust problem beats invisible plumbing debt with an August 1 launch.

**FR-7.31's fix is a two-function module, not one consolidated helper.** `roster_for_week()` and `roster_current()`. The value is that every call-site must declare which question it's asking.

---

## The big find: FR-7.30

**The `players` table never grows.** No runtime path adds a player — two one-time seeders, nothing else. A practice-squad call-up is invisible everywhere (scores zero, no projection, no roster row) *and* breaks FR-5.7's weekly capture indefinitely, since capture is all-or-nothing on unresolved players.

**This blocks FR-7.29.** You cannot refresh a `Roster` to include a player who doesn't exist in `players`.

**Dependency chain is now: FR-7.30 → FR-7.29 → FR-6.9.** FR-5.7 already shipped.

Surfaced from a direct question about practice-squad call-ups, not from any plan. Not yet ruled — "insert on unrecognized" is the obvious candidate but is a ruling to make. Related: player resolution is name-based (`player_map[name.lower()]`), which is fragile; `player_id_map` (DynastyProcess crosswalk) exists and should be evaluated as the bridge.

---

## Open findings from this session

- **FR-7.30** — `players` never grows. Blocks FR-7.29. Needs design session.
- **FR-7.31** — twelve week-blind `Roster` reads across seven files. Four repointed by FR-5.7; the rest need classification (current-read vs. week-read) before refactor. Do not bulk find-replace.
- **FR-7.32** — pool ST K/DEF matches on `player.position` not `slot`, includes bench. Left deliberately (one commit, one concern).
- **FR-7.33** — all 12 GMs share one seed password, no change-password path. **Launch blocker.**
- **FR-7.34** — Railway shows 2 pending variable changes (`YAHOO_CONSUMER_SECRET`, `YAHOO_PRIVATE_JSON`). Last session's "confirmed working end-to-end" used `railway run`, which injects variables locally — it proves the credentials are valid, **not** that the deployed service can see them. Verify before FR-7.29 deploys.

---

## Corrections made this session (recorded so they aren't re-made)

**FR-5.7's spec said use `display_position`.** Wrong rule for that job. `display_position` is player eligibility; `selected_position.position` is the week's lineup slot. Reading `display_position` would have captured zero bench players — exactly what FR-5.8 needs. The standing rule still holds everywhere it was written for.

**FR-5.7's spec said three read-sites.** There are twelve. Became FR-7.31.

**Claude Code's first pass claimed `RosterSlot` had no `player` relationship.** It does — `db/schema.py:159`. Caught by Claude Code itself on a later trace; the helper was simplified before commit.

**`_position_actual()` was assumed to need a bug-fix finding.** It's dead code — zero callers. Deleted instead.

**Claude in this session claimed pool bets don't read roster data.** They do — pool Special Teams. Corrected by trace; the two sites went into FR-5.7's diff.

---

## Next session

**In order:**
1. **FR-7.30** — design and build. How does `players` grow? Rule the name-based vs. `player_id_map` bridge question at the same time.
2. **FR-7.31** — classify twelve read-sites, get rulings on the ambiguous ones (`bet_engine` previews, `beef_engine` snapshotting, `monte_carlo` odds), then refactor to two functions.
3. **FR-7.29** — build, once 1 lands. Design is done.
4. **FR-6.9** — last, depends on `Roster` actually being current.

FR-7.33 (passwords) is a launch blocker but small and self-contained — can slot anywhere before August 1.

---

## Standing reminders, still binding

- **Clone the repo and read live code before ruling.** This has caught something real in every session that's done it. This session: the `display_position` rule was wrong for this job, `_position_actual` was dead, pool bets *do* read roster data, and the read-site count was 4× the spec's claim.
- **A shared theme is not a shared dependency.** FR-5.7-before-FR-7.29 is the *opposite* — two items that looked independent turned out to have a hard order between them, found by reading code.
- **Correct prior in-session claims out loud, immediately.** Several above.
- **Third-party API/hosting/UI questions get a real web search, every time.** Yahoo's rate limits were checked live this session — no published quota; enforcement targets short bursts, not steady volume.
- **Propose before building.** No code, commits, migrations, or `railway up --service fantasy-beefs` without Fraser's explicit word.
- **Money-path work is Opus-gated, minimum two passes** — one on design, one on the diff. Nothing in the current trio is money-path.
- **`git status` / `git log` vs `origin`** before closing any session or starting a new thread.
