# Fantasy Beefs — Next-Thread Opener (v48)

Paste this as the first message of the next thread.

---

I'm continuing the Fantasy Beefs build. Load handoff **v48**, the **architecture diagram (v9)**, and the **Build Sequencing Update (2026-07-15 Session 2)** from project files before anything else — the Session 2 sequencing doc supersedes the Session 1 version, don't work from the older one.

**Before ruling on anything code-related, clone the actual repo** (`FDCHub/fantasy-beefs` on GitHub) into a sandbox and read the live code yourself, rather than trusting this handoff's account of it. This has caught something real in every session that's done it. Last session alone it caught: a standing data rule (`display_position`) being wrong for the job at hand, a function I was about to write a bug-fix finding for that turned out to be dead code with zero callers, a claim I'd made that pool bets don't read roster data (they do), and a read-site count that was 4× what my own spec claimed. Don't skip it.

**Where we are:** FR-5.7 shipped last session — built, tested (26 assertions, 18/18 suites, zero regressions), committed `8201617`, pushed. Deliberately **not deployed** (see FR-7.34). FR-7.29's design is fully ruled and spec'd but is now **blocked**.

**The blocker, found last session and not in any prior plan:** **FR-7.30 — the `players` table never grows.** No runtime path adds a player; two one-time seeders, nothing else. A practice-squad call-up is invisible everywhere *and* breaks FR-5.7's weekly capture indefinitely (capture is all-or-nothing on unresolved players). FR-7.29 refreshes `Roster` — but `Roster` can't hold a player who doesn't exist in `players`. **`players` must grow before `Roster` can refresh.**

**This session's task, in order:**

1. **FR-7.30 first** — design and build. Not ruled yet. Real open questions: is the fix "insert on unrecognized" (Yahoo returns name + position on the roster fetch), or something else? Player resolution is currently name-based (`player_map[name.lower()]`) which is fragile — `player_id_map` (DynastyProcess crosswalk) exists and should be evaluated as the bridge instead of string matching. Rule both together.
2. **FR-7.31 second** — the two-function consolidation. Twelve week-blind `Roster` reads across seven files; FR-5.7 repointed four. **Ruled: the fix is `roster_for_week()` + `roster_current()` in `db/roster_read.py`, not one consolidated helper** — live reads (roster endpoint, war-room free agents) have no week and mean *now*; passing `week=current` would be consolidation in name only. **Classification comes before refactor.** Some sites are obviously current-reads, some obviously week-reads, and several are genuinely unclear — `bet_engine` previews, `beef_engine` snapshotting (which freezes a lineup *into* `beef_starters`, so it may be a week-read wearing current-read clothes), `monte_carlo` odds. Each needs a look at what the function does with the roster *after* it reads it. **Do not bulk find-replace** — some sites are currently correct by accident.
3. **FR-7.29 third** — build. Design is done, spec is written (`FR_7_29_ROSTER_REFRESH_MODULE_SPEC_DRAFT.md`). Verify FR-7.34 (Railway variable propagation) before deploying anything that touches Yahoo.
4. **FR-6.9 last** — depends on `Roster` actually being current.

**Also open, not urgent but don't lose:** FR-7.33 (all 12 GMs share one seed password, no change-password endpoint — **launch blocker**, but small and self-contained, ~30 lines reusing existing `hash_password`/`verify_password`). FR-7.32 (pool ST matches K/DEF on `player.position` not `slot`, includes bench — left deliberately, one commit one concern).

**Standing reminders, reinforced last session, still binding:**
- A shared theme is not a shared dependency — but FR-5.7-before-FR-7.29 was the opposite: two items that looked independent had a hard order between them, found only by reading live code.
- Correct prior in-session claims out loud, immediately, the moment further checking contradicts them.
- Third-party API/hosting/UI questions get a real web search every time, not a recollection from training.
- Propose before building. No code, no commits, no `railway up --service fantasy-beefs` without Fraser's explicit word.
- Money-path work is Opus-gated, minimum two passes — one on design, one on the diff once built. Nothing in the current trio is money-path.
