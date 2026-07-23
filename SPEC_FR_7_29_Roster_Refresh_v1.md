# FR-7.29 — Roster/Projection Refresh Cadence & Cross-Team Freshness — MODULE SPEC (DRAFT)

**Status:** Design ruled this session. Not built. Not Opus-gated — touches odds display and eligibility, not fund movement or the ledger.

**Existence-check performed:** repo cloned live (`FDCHub/fantasy-beefs`, HEAD `9989d4b`, matches handoff v47). All claims below marked "confirmed live" were verified by reading the actual code, not assumed from prior docs.

---

## 1. Problem Recap

`Roster` has been written exactly once, ever — the initial season seed. `Projection` has the same gap. Confirmed live: `GET /odds/{matchup_id}/{week}` calls `mc_run()` fresh on every request, no caching layer, reading `Roster` directly. Odds accuracy is 100% downstream of `Roster` accuracy.

---

## 2. Ruled Design

### 2.1 Scheduled floor — both bet families

**Ruling: refresh all teams' Roster + Projection data every 6 hours.**

Volume check, corrected during this session: 6-hour cadence = 4 refresh cycles/day. Yahoo's API is per-team (`get_team_roster_by_week(team_id, week)`), so each cycle = 12 calls (one per GM). **48 Yahoo calls/day from the floor alone**, plus separate FantasyPros calls for projections, plus on-demand GM-triggered refreshes. Confirmed via Yahoo's published developer terms: no fixed daily quota exists; enforcement is against short-burst excessive use, not steady moderate volume. 48 spread-out calls/day for a 12-team private league is not in that territory.

### 2.2 Vs-bet (Beef) flow — GM-triggered refresh, no floor-only reliance

**Ruling, full sequence:**

1. GM sees the vs-card with posted odds (whatever the last computation was — floor-refreshed or prior on-demand).
2. GM A opens the card. A refresh button is present.
3. GM A clicks refresh → app pulls live Roster + Projection for **both** teams, compares against current posted state.
   - If nothing changed: original odds are confirmed as still valid (not just assumed).
   - If something changed: odds are regenerated.
4. GM A reviews the (confirmed or updated) odds and either **cancels** or **issues the challenge**.
5. GM B is notified. The notification states which roster/projection state the challenge is based on.
6. App runs a diff: state-as-of-issue vs. GM B's current live state.
7. GM B, seeing the diff, chooses one of three:
   - **Accept** — takes the bet as posted.
   - **Decline** — nothing happens.
   - **Rechallenge** — GM B counters with new odds, computed from GM B's own current (fresher) state.
8. If rechallenged, GM A gets exactly one choice: **accept** or **decline**. No further countering, no third freshness check. The chain terminates here either way.

**Explicitly ruled out:** re-refreshing again at GM A's final accept/decline on a rechallenge. One round of back-and-forth maximum, by design, to keep this bounded inside the 24-hour acceptance window.

### 2.3 Pool bets — lock-time clarification

**Confirmed live:** `_nfl_lock_time()` returns `MIN(kickoff_utc)` across the **entire week** — one lock timestamp for all pool bets that week, not per-game. (`pot.lock_time` can override this per-pot, but is still one timestamp for the whole week.)

**Ruling: 6-hour floor is sufficient for pool bets.** No per-game-day refresh needed — once the week's single lock passes, no pool bet for that week can be placed or altered regardless of any later refresh, so refreshing after lock has no placement-relevant effect.

**Known, accepted residual gap:** in the worst case, data can be just under 6 hours stale at the exact moment of lock. A very last-minute inactive (e.g., announced ~90 min pre-kickoff) could land in that window. Ruled acceptable — stated explicitly, not silently accepted.

---

## 3. New / Changed Data Model

| Table | Change | Reason |
|---|---|---|
| `teams` | Add `last_refreshed_at` (DateTime, nullable) | Powers the rate-limit/cooldown guard on the GM-triggered refresh button. Confirmed live: no such field exists today. |
| `beef_challenges` | Add new status value `rechallenged` to the `ck_beef_status` CHECK constraint (`pending, countered, accepted, declined, expired` today — confirmed live) | The rechallenge lifecycle (2.2, steps 6–8) is a **different state machine** from the existing stake-only `countered` path (see §4.1) and must not overload it. Requires a migration. |
| `beef_challenges` | Add fields to carry the structured diff shown to GM B (e.g. `state_diff_json`) | Extends today's `staleness_warning` (a bare boolean) into an actual per-slot diff. See §4.2. |

---

## 4. New / Changed Functions & Endpoints

### 4.1 Existence-check finding: `counter_challenge()` is NOT reusable for "rechallenge"

Confirmed live, `beef_engine.py`: `counter_challenge()`'s own docstring states *"Bet type, week, and odds remain locked; only the stake changes."* No roster read, no odds recompute. This is a stake-haggle mechanism, answering a different question than "rechallenge with fresher odds." **Do not overload it.** Rechallenge needs its own function and its own status value, per §3.

### 4.2 Existence-check finding: `staleness_warning` is a narrower, pre-existing mechanism — not what closes this gap alone

Confirmed live: `staleness_warning` already exists, computed via `_check_staleness()`, but only compares **projected points** (`projection_snapshot` vs. live points), after the roster has already been frozen into `BeefStarter` at issue time. It says nothing about whether the *lineup itself* was stale when issued — which is the actual gap this spec closes.

**Recommendation:** extend `_check_staleness()` (or add a sibling function) to return a structured diff — which player/slot changed, not just a boolean — so GM B sees "RB slot: Player X → Player Y" rather than a bare flag. Matches the transparency already ruled for the challenge notification (§2.2, step 5).

### 4.3 New two-step split required for `issue_challenge()`

Confirmed live: today, `POST /beef/challenge` → `issue_challenge()` computes preview odds **and** creates the `BeefChallenge` row in one call. The docstring already calls its own odds "a preview only" — implying a two-step shape that was never actually built.

**Required split:**
- **New: refresh-and-quote step.** Refreshes both teams' Roster/Projection, compares vs. current posted state, returns confirmed-or-updated odds. No DB write.
- **Changed: commit step.** Creates the `BeefChallenge` row using the confirmed state from the refresh-and-quote step immediately prior. (Assumption: no re-refresh needed between quote and commit, since they occur back-to-back in the same GM action — flag if this assumption is wrong.)

### 4.4 New scheduled job

A new step in `notifications/tuesday_sync.py`'s job family (or a new dedicated job, if 6-hour cadence doesn't fit the existing daily/weekly sync cycle — **open build question, not yet resolved**): refresh all teams' Roster + Projection every 6 hours.

### 4.5 Rate limiting / cooldown

**Recommendation (stated, not yet explicitly voted on):** a simple `last_refreshed_at` check on `Team` — a short cooldown window (exact minutes TBD at build time) preventing a GM from hammering the refresh button in quick succession. Also needed: catch Yahoo's throttle response cleanly (confirmed live via search: Yahoo issues temporary blocks under burst load) and surface it as "refresh temporarily unavailable, try again shortly," not a crash.

---

## 5. Interaction with FR-5.7 and FR-6.9 (unchanged from the original finding)

- **FR-5.7** (`RosterSlot` weekly-capture job) is separate and settlement-only — retrospective by design, cannot serve any of the pre-lock questions this spec answers. No overlap in logic, only in touched territory (`Roster`).
- **FR-6.9** (`_has_scheduled_player()` eligibility check) depends on `Roster` actually being current — this spec is the prerequisite. FR-6.9 can now be scoped correctly, since the refresh mechanism it depends on is designed.

---

## 6. Self-Check — Internal Consistency

- §2.1's 6-hour floor and §2.2's GM-triggered refresh are **not redundant**: the floor guarantees a ceiling on staleness for GMs who never interact; the on-demand path guarantees near-real-time accuracy at the moment a bet is actually issued or accepted. Both needed, confirmed non-overlapping in purpose.
- §2.3's ruling depends on §2.1 (the floor) already existing — consistent, no forward reference to an unbuilt mechanism.
- §3's new `rechallenged` status and §4.1's finding agree: the CHECK constraint change is required precisely because the new lifecycle is confirmed distinct from the existing `countered` one.
- §4.3's two-step split is required by §2.2 step 3–4 (refresh-and-decide-before-committing) — the current single-call `issue_challenge()` cannot serve that sequence as-is. Confirmed no contradiction between the ruled UX flow and the required code shape.

---

## 7. Open Build-Time Questions (not design questions — implementation detail, flag before building)

- Exact cooldown window length for the refresh-button rate limit (§4.5).
- Whether the 6-hour floor job lives inside `tuesday_sync.py`'s existing cycle or needs its own scheduler entry, given `tuesday_sync.py`'s name implies a weekly, not 6-hourly, cadence (§4.4).
