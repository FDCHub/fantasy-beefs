# FR-7.29 — Zero Automated Refresh for Pre-Game Data (Roster, Projections)

**Status:** NEW, found live in conversation, not spec'd, not built. Needs its own dedicated scoping session, alongside FR-5.7 and the corrected FR-6.9.

---

## Issue Summary

`Roster` has been written to exactly once, ever, in production — the initial season seed (`seed_real_2025_season_LIVE.py`). Confirmed by grepping every write to the table across the whole repo: nothing since has refreshed it. No scheduled job, no on-demand trigger, no GM-facing action of any kind.

`Projection` has the identical gap — confirmed zero references anywhere in `notifications/tuesday_sync.py`; it's only ever touched by standalone manual scripts (`seed_yahoo_projections.py`, `fix_yahoo_projection_columns.py`), run by hand.

**This matters more than a typical staleness bug because odds are never cached.** `GET /odds/{matchup_id}/{week}` calls `mc_run()` fresh on every request — confirmed live, no stored odds table anywhere. So odds accuracy is 100% downstream of `Roster` accuracy, with no separate caching layer to also fix. Every odds display in the app has been running on day-one roster data all season, regardless of any trade, waiver claim, or lineup change made since — and will continue to, the moment `Roster` is fixed, with zero additional plumbing required.

This is distinct from two other data types that are already fine:
- **Scores** — refresh weekly via `tuesday_sync.py`'s `refresh_scores` step. Correct as-is, since scores are only meaningful after a week's games conclude.
- **The ledger** — needs no refresh mechanism of any kind. It's written synchronously, internally, by the app's own transactions — not externally sourced, so "refresh cadence" doesn't apply to it at all.

## What Fraser needs, stated directly

A GM should be able to open the app after editing their Yahoo lineup and see that change reflected — in odds, and in eligibility — without waiting for any scheduled job. This is a live, on-demand, user-triggered need, not a "make the weekly job more frequent" fix.

## What's already there, confirmed live

- **The Yahoo call pattern already works**, proven in `get_rosters.py`: `query.get_team_roster_by_week(team_id, week)` via yfpy, reading `selected_position_value` for lineup slot (correctly, not `display_position`, per this project's established convention).
- **The credentials-in-production question is resolved — and not the way it was expected to be.** `railway variables --service fantasy-beefs`, run live, confirms only `DATABASE_URL`, `JWT_SECRET_KEY`, and Railway's own auto-injected metadata exist. **Neither `YAHOO_PRIVATE_JSON` nor `YAHOO_CONSUMER_SECRET` is set.** `tuesday_sync.py` documents a Railway-first pattern for reading these, but the variables it expects aren't there. This means the scheduled weekly job has likely never successfully authenticated against Yahoo when run on Railway itself — if it's ever been triggered there, it would have had nothing to read (no env vars, and `secrets/` is gitignored, never deployed). **This is a confirmed, real prerequisite for FR-7.29, not a design nicety:** these two environment variables need to be added to the Railway service before any live, GM-facing Yahoo call — refresh endpoint or otherwise — can work in production.
- **This also puts a caveat on this session's earlier "scores already refresh correctly, weekly" framing.** That was true of the *design* (weekly is the right cadence for post-game data) — it is not yet confirmed that the job has ever actually *executed successfully* against production, given the missing credentials. Worth confirming directly: has `tuesday_sync.py` ever completed against production, with logs or output to show for it, or has every real run so far been local-only (against production's database, but via local Yahoo credentials)?
- **No shared, reusable Yahoo client helper exists anywhere in the app today.** Every single yfpy call across the whole codebase — a dozen-plus scripts, `tuesday_sync.py` included — duplicates its own auth-loading/query-construction logic. A GM-facing refresh endpoint should not be the next copy of that pattern; it should be the reason to finally extract a shared helper.
- **This would be the first time Yahoo gets called live, synchronously, inside a real user-facing request** — every prior use has been an offline script Fraser runs by hand, or a scheduled job. Worth designing real error handling for a slow or hiccuping Yahoo API response, rather than letting a script-style crash reach a GM's screen.

## Open design questions, not yet ruled — for the dedicated scoping session

0. **Confirmed prerequisite, not a design question:** add `YAHOO_PRIVATE_JSON` and `YAHOO_CONSUMER_SECRET` to the Railway service's environment variables before any live Yahoo call can work in production. Nothing else in this finding can be built until this is done.
1. **Scope of the refresh action:** single-team, GM-triggered (`POST /roster/{team_id}/refresh`) vs. a broader sync.
2. **Cross-team freshness at bet time:** if Team A refreshes but Team B (the team they're betting against) hasn't, odds compute from mixed-freshness data. Does issuing a challenge force-refresh both sides automatically, or is each GM responsible for their own, with a visible "last refreshed" timestamp so the other side can judge?
3. **Cadence floor:** on-demand only, or on-demand plus a scheduled baseline (e.g., daily) so a GM who forgets to hit refresh isn't stuck on stale data indefinitely?
4. **Rate-limiting/cooldown:** a lightweight guard against a GM hammering the refresh action repeatedly — likely a simple `last_refreshed_at` timestamp check, since `Team` has no such field today and would need one added.
5. **Interaction with FR-5.7 and FR-6.9:** FR-5.7's `RosterSlot` job is separate and settlement-only (confirmed, retrospective by design — cannot serve pre-lock questions). FR-6.9's corrected eligibility check (`_has_scheduled_player()`, using `NflSchedule` + current `Roster`) depends on `Roster` being reasonably fresh at pick-submission time — meaning FR-6.9 shouldn't be built until this finding's design is at least decided, even though its own code shape is already sketched and small.

## Recommendation

Scope this, FR-5.7, and the corrected FR-6.9 together as one dedicated session — not because they share a root cause (they don't; `RosterSlot` and this finding solve genuinely different problems, a correction from earlier tonight's conversation), but because FR-6.9 is blocked on this finding's design landing first, and both touch the same `Roster`/roster-refresh territory closely enough that scoping them apart risks rework.

**Not Opus-gated.** Touches odds display and eligibility, not fund movement or the ledger.
