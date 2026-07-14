# Fantasy Beefs — Master Plan: BAB MVP Path (with Deferral Appendix and Playoff Probabilities Scoping) — Rev 4

**Date:** July 7, 2026 (updated end of Opus Plan Audit session — 15 findings resolved, lock-timing decision recorded)
**Status:** BAB Wallet Model committed as the plan. This document reconciles the prior Master Plan lineage — the Master Plan Corrected (July 4), the Deferred Work Appendix (July 4), the BAB Architecture and Strategy decision (July 5), and Rev 3 (July 7) — into one source of truth. Rev 4 folds in the Opus Plan Audit: the plan is now more honest about what it has and has not verified, and it flags several estimates that were resting on unchecked labels.

**A note on how Rev 4 differs from Rev 3.** Rev 4 changes almost no product decisions. What it changes is the plan's honesty about its own certainty. Several estimates that read as settled were resting on labels nobody had checked — counts asserted in prose, build sizes painted on unverified states, a core money-path formula referenced eight times and never written down. Rev 4 marks each of those as provisional and names the cheap check that would confirm it. This makes the plan look *less* complete than Rev 3. That is the point. Rev 3 looked complete while hiding the same class of gap that cost a full session on the RosterSlot backfill. Rev 4 surfaces those gaps instead of hiding them.

**Current percent-complete (against this reconciled plan):**
- Backend: ~62%
- Middleware/Wiring: ~38%
- Frontend/UI&UX: ~20%
- Overall: ~46%

**Percentages held unchanged this session — and this session did not touch code.** The Plan Audit was a document review, not a build. Nothing shipped, nothing was estimated up or down against real new work. One caveat carried from Rev 3 still stands: the RosterSlot backfill, previously counted as "1 session, mechanical," is confirmed blocked on an unscoped Yahoo lineup-slot-sync dependency (see Zone 3, 2026-07-07). That dependency has no estimate yet. Rev 4 additionally flags a second unscoped item — the reserve-ceiling formula (see Finding-driven changes below) — which was previously hiding inside the BAB build's 3–4 session estimate. Both are now named open items. The percentages are held as-is with both flags attached rather than guessing numbers that would repeat the exact failure this audit exists to prevent.

Batch C is built and verified but not committed or deployed. It, plus prior undeployed commits, sit pending a `railway up --service fantasy-beefs` (see the Deploy Gap section — now tracked as its own line, not a header caveat).

**How to read this document:** Part 1 is what's left to reach a launchable BAB-based MVP. It now opens with two new sections: **What a GM Can Bet On** (the locked bet roster, stated in the plan for the first time) and a **DRAFT Launch Gate** (the minimum capabilities for August 1). Part 2 is the pruning ledger. Appendix A is Rev 2.0 deferred work, updated for BAB. Appendix A-2 is Multi-League Support. Appendix B is Decision Engine and My Team, formally deferred. Appendix C is Playoff Probabilities, deferred alongside B. A new **Recommended Next Sequence** section near the end proposes an order of operations — recommendation only, Fraser makes the call.

---

## The one-line summary

FAAB drops out of wagering entirely. One wallet, one currency — BAB, Beef Action Budget — funded by a single $200 season buy-in. No Cash bucket. No Stripe, ever. `MAX_BET_PCT` is gone, replaced by a reserve-formula ceiling — **which is not yet written down and is now a flagged open item requiring its own spec and Opus Math Review.** Everything else on the board gets reordered around what BAB needs, not replaced by it.

---

## A word on units and vocabulary (new in Rev 4)

**"Session" defined.** Every estimate in this document is denominated in sessions. A session is **one fully exploited context window — roughly an hour of work.** This is the unit; multiply by it to convert any estimate to real time.

**Calendar reality-check.** At roughly 20 sessions per week, the ~25–34 sessions of *scoped* work remaining (Backend 10–14, Frontend 13–17, Middleware 2–3) run roughly 1.5–2 weeks against a ~3.5-week runway to August 1. The buffer is real, but it is the entire margin for two unscoped items (Yahoo slot-sync, reserve-ceiling formula) plus any "small/mechanical" label that grows once checked. The Launch Gate below is the insurance against that risk: if the gate cleanly separates must-have from fast-follow, an unscoped item ballooning threatens the fast-follow list, not the launch date.

**"Locked/confirmed" vs. "decided, unverified."** Rev 4 adopts a standing vocabulary rule. **Locked / confirmed** is reserved for things with visible evidence — a commit hash, a query result, a quoted decision. **Decided, unverified** is used for product calls that are settled as decisions but whose code state nobody has checked. Where Rev 3 used "locked" to mean both at once, Rev 4 splits them. **Honest limit:** this sweep catches only the cases the document itself admits are unverified. It does not independently verify every "confirmed" — that is a code-check, not a plan-read. A "confirmed" that is actually false but not self-admitted will survive this pass.

---

# PART 1 — Path to BAB-Based MVP

## What a GM Can Bet On (new in Rev 4)

This is the product surface, stated in the plan for the first time. **Sourcing note:** the roster below was reconstructed from dated session history (the versus roster and Bench Battle/Parlay retirement locked July 1, 2026; the pool roster and Bench Burn refinement locked June 30, 2026). It is **not** drawn from the Creative Bible, which is brand/lore and is stale on bet mechanics. Rev 4 is the first document to state these together. Full mechanical rules, where they exist, live in the module specs — this section names the roster and its settlement intent, not the implementation.

**Versus bets — exactly 4, locked (Bench Battle and The Parlay formally retired):**

| Bet | Definition |
|---|---|
| **Moneyline** | Who wins the matchup outright. Straight win or loss. |
| **Spread** | Monte Carlo derives the median projected point differential between the two teams; posts as a line rounded to .5 to avoid a push. Favorite must win by more than the line; underdog covers by staying within it. |
| **O/U** | Monte Carlo derives the median projected *combined* score of both teams; posts as a line rounded to .5. Bet is over or under that total. |
| **The Lineup** | Compares how many starters on each side beat their individual **Yahoo** projections (not FantasyPros). Whoever has more starters outperform their own projection wins. |

**Pool bets — exactly 4, locked:**

| Bet | Definition |
|---|---|
| **Biggest Winner** | Head-to-head record vs. the field for the week (e.g., "went 9-2 vs. the field"). |
| **Worst Beat** | Prediction bet — each GM picks which matchup will produce the biggest point-differential loss that week. |
| **Special Teams Supremacy** | Highest combined real NFL Kicker + Defense points. |
| **Bench Burn** | Predict which GM has a legal, game-changing benched player — one who (1) had a legal open roster slot to be started in, and (2) whose point total would have swung the matchup by more than the actual margin of defeat. Both conditions required; self-picks blocked. |

### Lock timing (decision recorded this session)

The lock model was reopened and re-decided during the Plan Audit. The result:

- **Launch model — Option C: versus bets lock at acceptance.** When both GMs agree, the odds freeze at the agreed number. Lineup changes after acceptance settle on actual scores — "that's on them." This rides on **Batch D** (odds-lock-at-offer).
- **Pool bets: week-level Thursday lock, unchanged.** Per-participant lock timing does not apply to whole-slate bets — every pool bet involves the entire league, so there is no single player's kickoff to lock against. They lock at the week's first kickoff via `_nfl_lock_time(season, week)`.
- **The willingness bridge — a My Commish setting.** Option C freezes odds at acceptance, which risks GMs holding off on Thursday because Saturday/Sunday lineup optimization shifts the picture. Two league-selectable answers:
  - **(a) Lock at acceptance, live with it.** Odds freeze on agreement. Simple. Rewards conviction.
  - **(b) Flexible Stake and Return with Max Stake Ceiling** keeps adjusting an already-accepted bet as odds drift, up to kickoff. Stakes only shrink, refunds hit wallets, neither GM exceeds original commitment. This makes locking early *safe* against later drift — it removes the downside of early commitment.
  - **Default: (b).** Reasoning: (b) is the setting that actually cures the engagement problem — it makes an early lock the safe move rather than the sucker move. (a) is the purist option for a league that wants conviction to matter. Made a Commish toggle so the league's temperament isn't decided for it, same pattern as The Reveal vs. Quiet Ledger and non-participant handling.
- **Target state — Option B: per-player lock, versus-only, post-launch.** A Beef locks when its earliest involved player kicks off; Sunday-only Beefs stay live and accurate into Sunday morning. Likely available only after launch. Pools stay week-level even under Option B.

**OPEN FLAG, not assumed away:** setting (b) reprices *live, already-accepted* bets. The escrow mechanic itself exists in `escrow.py`. But the trigger that fires it on the Saturday/Sunday odds-refresh cadence for open bets may live inside **Batch E** (repricing / lineup-change) and may not be built. Before v-anything calls setting (b) launch-ready, that trigger must be checked against code or scoped. Do not label it done until verified.

---

## DRAFT Launch Gate — the minimum for August 1 (new in Rev 4)

**STATUS: DRAFT — pending a dedicated Launch Gate Audit.** This gate is drawn from what the plan implies is load-bearing. Every line is marked as inference. It has not been independently verified as *necessary and sufficient* — that is the job of a separate Opus pass (the Launch Gate Audit Protocol, produced alongside this document, to be run in a fresh thread). Do not treat this gate as settled. Its purpose is to give the sufficiency audit a real artifact to attack, not to be the final word.

A GM can do the following, end-to-end, against real BAB wallet balances, or the product does not launch:

1. **Fund BAB.** The $200 buy-in exists as a wallet balance ($140 visible / $60 reserved). *(inference — no funding-flow completion is confirmed in the plan; this needs verification)*
2. **See their wallet.** Single BAB balance with the visible/reserved split rendered. *(inference — depends on BAB wallet display, currently unbuilt)*
3. **Place at least one versus bet end-to-end.** Offer → accept (Beef accept flow) → lock → settle, against real balances. *(inference — Beef accept flow "doesn't exist at all" today; this is almost certainly launch-blocking)*
4. **Place at least one pool bet end-to-end.** Pick → lock at Thursday kickoff → settle. *(inference — pool engine exists but has not run against production without the ck_tx_type fix, which is pending deploy)*
5. **The week locks correctly.** `_nfl_lock_time()` returns the right kickoff for the live 2026 season; `per_bet_lock.py` placeholder fix shipped. *(inference — `_nfl_lock_time` fix deployed; `per_bet_lock` fix specced, not built)*
6. **Settlement moves real money correctly.** No invented money (Batch C), penny-exact splits, fail-loud on missing wallets. *(inference — Batch C built and verified, pending deploy)*
7. **The reserve-ceiling holds.** A GM cannot wager beyond the ceiling. *(inference — but the ceiling formula is not written yet; see the flagged open item. This line may be the single biggest risk to the gate.)*

**Everything not on this list is explicitly fast-follow** — the live leaderboard, My Action restructure, GM-vs-Field tables, the Lite power ranking, counter-offer UI polish, and so on. They improve the product; the week still settles without them.

**Why this gate is not yet trustworthy:** it can only be as complete as the plan it was drawn from. If the plan silently omits a required capability, this gate omits it too. That blind spot is exactly what the separate Launch Gate Audit is for — an adversarial pass whose only job is to find the missing necessary item.

---

## Backend

### Accomplished

- Yahoo OAuth, read-only, working.
- Railway deployment — live and stable.
- Real 2025 season data seeded — 12 teams, 180 players, 98 matchups, 12 wallets, 12 FAAB wallets.
- Per-bet lock pair fix, Opus-reviewed, committed `d9e9664`.
- Unit One — `POST /bets/place`: client-odds, auth, self-settlement all closed. Committed `dc7e495`.
- Unit Two — `settle_week()` run-once race + freshness gate, three Opus passes, closed. Committed `cfd559a`, `357ab2a`.
- `WeekSettlement` table, additive migration, applied and verified.
- Exception-typing fix for `place_bet` and sibling routes — `NotFoundError`/`BetValidationError`, 14 raise sites retyped, all four routes branch by type. Committed `77b0dd6`.
- **Wallet audit Batch A — reservation-accounting cluster. Closed.** Six sites across `wallet_manager.py`, `beef_engine.py`, and `faab_wallet.py` all computed `challenge_reserved` by summing `challenge.amount`, ignoring `countered_amount`. Consolidated into one shared `_challenge_reserved()` helper in `wallet/wallet_manager.py`. Reviewed by Opus across three rounds. Committed `70e0add`. Two related surveys — the inter-wallet transfer check and the `pending_exposure` double-count check — both confirmed clean, no further fix needed there.
- `per_bet_lock.py` audit — confirmed real, wired, non-duplicative. Untracked-file bug found and fixed (was never committed despite being live code). Committed.
- `BeefStarter` missing `UniqueConstraint` — fixed, migration run, confirmed live via `pg_constraint`. Committed `666c8c5`.
- `RosterSlot` table — created, migration confirmed against production.
- PyCharm stray-folder cleanup — closed. Seven stray practice folders untracked and removed from the repo. Committed `a45a919`.
- Working tree triage — closed. Every modified and untracked file sorted; two additional untracked-live-code bugs found and fixed (`per_bet_lock.py`, `yahoo_scoreboard.py`).
- **Six `_nfl_lock_time()` callers wired to `ScheduleNotReadyError` — committed `c7ebad8`, deployed, confirmed live.** Real site count was six, not nine — four in `beefs/beef_engine.py`, two in `betting/pool_engine.py`. Opus-reviewed, four findings, all resolved. Verified two ways (existing suite + new smoke test), deployed, live traffic confirmed normal.
- **`per_bet_lock.py` placeholder-window fix — MODULE_SPEC written, Opus-reviewed, all five findings resolved this session. Ready for Claude Code CLI build. NOT yet built, NOT committed.** Same class of bug as the already-shipped `_nfl_lock_time()` fix: a raw `MIN()` over `kickoff_utc` with no placeholder filter. See Zone 3, 2026-07-07, for the full finding-by-finding resolution. Spec file: `PER_BET_LOCK_PLACEHOLDER_FIX_MODULE_SPEC.md`. **Rev 4 note (Finding 4.6):** the "half session to build" label is contingent on re-running the caller grep at *build* time — see Remaining.

### In process

- **Wallet audit Batch B — needs re-scope, not a straight fix.** Originally: enforce `MAX_BET_PCT` on Beef challenges, fix the commissioner-obligation function's `challenge_reserved` check. **`MAX_BET_PCT` is going away under BAB.** Fixing Batch B as originally spec'd would harden a rule about to be retired. The real fix, once BAB's reserve-ceiling logic exists, is wiring Batch B's original intent — enforcement on Beef challenges — into the new ceiling formula instead. **Rev 4 (Finding 2.1):** Batch B's estimate is therefore *conditional* — it cannot be honestly sized until the reserve-ceiling formula exists and is Opus-Math-Reviewed. See the Pruning Ledger, Part 2, for the deletion side of this, and the flagged open item below for the formula itself.
- **Wallet audit Batch C — pool-settlement fix. Built and verified, not committed or deployed.** Re-scoped through investigation, then shrunk against source: no longer a shortfall-tracking system (all-or-nothing per team, no partial-shortfall event). The built fix is three things: (1) settlement reads a persisted `PoolPot.total_pot` instead of recomputing, closing the invented-money bug; (2) penny-exact splits via a `_split_even()` remainder pattern; (3) fail-loud guards replacing silent walletless skips. Verified end-to-end locally. Opus-reviewed, four findings, all approved and folded in. Pending commit and deploy.
- **Production `ck_tx_type` constraint gap — found, migration written, pending deploy.** Production's constraint was missing `pool_entry` and `pool_payout` — meaning the pool engine had never run against production without being rejected mid-write. Migration widens the constraint to all six values. Must deploy alongside Batch C.
- **`Transaction.type` granularity check.** Needs a read-only pass to confirm waiver spend, wager win, wager loss, and top-up are distinguishable in the log. Feeds both the remaining wallet audit work and BAB's season-end ledger.
- **Roster sync — RE-SCOPED, bigger than previously understood.** `RosterSlot` schema and table exist. The backfill for the existing 180 `Roster` rows was believed mechanical. **Confirmed false:** a direct query against production shows all 180 `Roster.slot` values are `NULL` (`total_rows=180, null_slots=180, teams=12`). `RosterSlot.slot` is `NOT NULL` — there is nothing to copy. The real, unscoped dependency is a **Yahoo lineup-slot sync** that populates `Roster.slot` with real starter/bench data first. No estimate exists yet — do not reuse the old "1 session, mechanical" figure. See Zone 3, 2026-07-07, and Open Questions.

### Remaining

- **Live 2026 season validation.** `_nfl_lock_time()` fixed and deployed, callers wired and deployed. `per_bet_lock.py`'s matching placeholder-window gap is specced and Opus-reviewed (see Accomplished) — ready to build.
  - **Rev 4 (Finding 4.6):** the "half session to build" estimate is **contingent on re-running the caller grep at build time.** The single-production-caller claim was confirmed at *spec* time. The `_nfl_lock_time` sibling — same class of fix, same session — under-counted callers (implied fewer, found six). This fix is a deliberate, loud contract break (`bool` → `LockCheck(locked, reason)`); a loud break is only safe if the caller inventory is complete and current. Re-grep before trusting half a session. Do not trust the spec-time count.
- **`api/main.py`'s hardcoded `league_id = 1`.** Needs a real league-resolution source before multi-league support lands.
- **Dedup of not-found checks.**
  - **Rev 4 (Finding 4.1):** the count ("four") and the "raise `NotFoundError` consistently" claim are **unverified** — asserted in prose, not backed by a grep, the same shape as the v30 "nine callers, actually six" error. Confirm count and consistency via one repo-wide grep before estimating. Half-session, low-risk label is **provisional on that check.**
- **Beef challenge lifecycle, Batch D and E.**
  - Batch D (odds-lock-at-offer revert) — drafted, not landed. **This is the seam where the Option C launch lock model gets implemented** (see Lock timing).
  - **Batch E — this is where BAB gets built, not retrofitted.** Denomination removal lands here natively. **Rev 4 (Finding 2.2):** Batch E is a *consumer* of the reserve-ceiling formula, not its author — the formula is authored in the BAB Wallet Model build (piece 2). Batch E owns the repricing / lineup-change work, including the live-bet repricing trigger that setting (b) of the lock model depends on. No bolting BAB onto code written for two currencies.
- **"Lite" power ranking.** Record, PF/PA, recent form. No FantasyPros dependency.
  - **Rev 4 (Finding 4.5):** the "no dependencies, half session" label is **provisional on confirming the standings/matchup data (record, PF/PA, recent form) is clean and complete for all 12 teams.** The field-name history (see Frontend/Middleware Accomplished — field-name mismatches needed fixing) means "no dependencies" is not verified. One query confirms it. *(Canonical statement of this item lives here; the Appendix A and Appendix C references point back to this line rather than repeating the label.)*
- **`GM_TEAM_ID` real login flow.** Currently resolved via `/auth/me` with a dev-stub token. Separate, future work.
- **BAB Wallet Model — full backend build.** The pieces:
  1. $200 buy-in split — $140 visible, $60 reserved for the championship pool (60/30/10 at season end).
  2. **Reserve-formula ceiling — THIS IS THE HOME OF THE FORMULA (Finding 2.2).** Replaces `MAX_BET_PCT`. Depends on Batch A's corrected `pending_exposure`/`challenge_reserved` math (closed and available). **The formula itself is not yet written — see the flagged open item below. It must be drafted and run through the Opus Math Review Protocol before this piece, or any of its four dependents, is built.** This piece is no longer silently absorbed into the 3–4 session bundle estimate; its authorship is a named, unscoped prerequisite.
  3. Top-up endpoint and flow — GM-prompted, commissioner-approved, app-tracked, reconciled at season end (decided).
  4. Weekly compliance report — flags a GM under the $10 weekly minimum. Soft enforcement only; no auto-enforcement, no auto-placed bets (decided).
  5. Season-end ledger calculation — replaces the old Wednesday FAAB reconciliation cycle. BAB reconciles once, at season end.
  6. FAAB read-only mirror — app displays Yahoo's own FAAB number, no independent tracking, no obligation, no top-up queue of its own.
  7. **`create_team()` factory — the permanent wallet-existence guarantee.** An atomic team-plus-wallet creation helper that every creation path routes through, consolidating the seven scattered `Team(` call sites. Deferred deliberately because BAB rewrites team-and-wallet creation wholesale. The Batch C fail-loud guards are the interim cover until this lands.
  Sequenced after Batch A (closed) and the `Transaction.type` check.
- **Skunk Fee — separate table or column, tracked off-wallet.** $10/week from the worst-margin loser, paid to the regular-season points leader at season end. Deliberately not part of BAB's balance math.
- **FAAB demotion — needs a deliberate code check, not an assumption.** Any validation code, wallet-lookup helper, or route still branching on `denomination == 'faab'` is a live wire until found and removed. Rides along with the frontend contract audit.
- **Denomination field removal.** The `faab`/`cash` field on every bet and challenge becomes dead weight under one currency. Remove from schema, API contract, and every frontend call site. Rides along with the contract audit.

### FLAGGED OPEN ITEM — Reserve-ceiling formula (new in Rev 4, Finding 3.1)

**The reserve-formula ceiling is referenced throughout this document as the replacement for `MAX_BET_PCT`. The actual formula has never been written down.** It is the money-path rule that decides how much a GM can wager. It blocks four items: Wallet audit Batch B, the GM pre-bet limit notification, the My Action BAB display, and Batch E (as consumer).

Until the formula exists on paper, its true scope is unknown — it could be simple (a fixed fraction of the $60 reserve) or complex (dynamic, exposure-aware, interacting with the Batch A `challenge_reserved` / `pending_exposure` math). The plan cannot tell you which, because the rule was never stated.

**Required:** draft the formula as its own spec, then run it through the **Opus Math Review Protocol** before any dependent is built. This is now a named, unscoped prerequisite — pulled out of the BAB build's 3–4 session estimate, where it was hiding. Every reference elsewhere in this document points here rather than re-naming the formula.

---

## Frontend

### Accomplished

- Bet slip unprompted-display bug — fixed.
- The Book's matchup grouping bug — fixed.
- Canonical `fetchAuth()` wrapper and VP fetch pattern established.
- Field-name mismatches (standings, pool config, wallet) resolved. *(Note: this history is why the Lite power ranking's "no dependencies" claim is unverified — see Finding 4.5.)*

### In process / partially built

- **My League VP2 — The Book.** Core matchup-card rendering works. GM-vs-Field tables spec'd, not built. Depends on the backend odds endpoint.
- **My Team tab.** Exists on its own `my-team` branch, off the critical path by deliberate decision. Stays there until after launch.

### Remaining

- **Beef accept flow — doesn't exist at all.** No accept button, no confirmation view. A build, not a tweak. Shape depends on Batch D landing first. **This is almost certainly launch-blocking (see Launch Gate line 3).** The `per_bet_lock.py` fix makes a correct, specific "why this bet is locked" message available at the API layer (real kickoff / schedule not yet posted / data problem, three distinct messages) — this flow should surface that message once built, not a generic "locked" state.
- **Counter-offer UI on the bet slip.**
  - **Rev 4 (Finding 4.3):** the "1 session, backend already shipped" estimate is **contingent on the backend counter endpoint being confirmed complete — route and commit are unverified.** Verification is specific: confirm the endpoint exists *and* enforces the locked rules (one counter maximum, stake-only change). A route that exists but skips that logic is not "shipped" in the sense the estimate assumes.
- **Reveal vs. Quiet Ledger toggle. Decision locked, code status unverified (Finding 3.3).**
  - **Rev 4 (Finding 4.2):** split into two honest lines. **Verify whether it exists in `app.html` — half session** (real, bounded). **Build if missing — unestimated until verified.** The old "1 session if missing" figure is dropped; you cannot size a build you haven't confirmed you need.
- **Non-participant handling UI** (Pay and Forfeit / Auto-Pick / Lock Out). **Decision locked, code status unverified (Finding 3.3).**
  - **Rev 4 (Finding 4.2):** same split. **Verify — half session. Build if missing — unestimated until verified.**
- **Live leaderboard** during Sunday/Monday game windows for the four pool bets. Not started. *(Fast-follow per Launch Gate.)*
- **My Action rename and restructure.** "The Book" becomes "This Week," plus three new sections. Named, never built. *(Fast-follow.)*
- **My Action countdown widget.** Scoped, not built.
- **The Lineup UI** (starters/bench). **Blocked on the Yahoo slot-sync** (see Roster sync re-scope) — needs the slot-sync built first, not just the RosterSlot backfill.
- **Standings layout.** Three options discussed, no decision made.
- **Bet slip DOM scoping.** Lives only in the League tab. Needs relocation if My Action gets bettable content.
  - **Rev 4 (Finding 4.4):** the "half session, small, mechanical" label is questionable because the plan itself couples this to the My Action restructure (2 sessions). **Independence from the My Action restructure is unverified.** If coupled, fold this estimate into the My Action restructure rather than counting it separately — otherwise it double-counts or hides a dependency. Half-session estimate provisional on that check (an `app.html` read).
- **BAB wallet display.** Once the backend build lands: single BAB balance, $140/$60 visible-vs-reserved split, top-up control. *(Launch Gate line 2.)*
- **GM pre-bet limit notification.** **Blocked on the reserve-ceiling formula** (flagged open item).
- **My Action BAB display.** **Blocked on the reserve-ceiling formula** (flagged open item).

---

## Middleware / wiring (backend ↔ frontend)

### Accomplished

- `fetchAuth()` and the VP fetch pattern give every panel a working path to the backend.
- Field-name mismatches (standings, pool config, wallet) documented and fixed.

### In process / confirmed gaps

- **Final locked odds not shown in the UI.** `final_challenger_odds`/`final_challenged_odds` exist in the API response, unread by `app.html`.
- **`staleness_warning`** — present in the API, absent from the frontend. May become moot once Batch D lands.
- **Reveal toggle and non-participant handling** — decision locked, code status unverified (Finding 3.3). See Frontend Remaining for the two-line verify/build split.

### Remaining

- **Full frontend-to-backend contract audit.** Every API call in `app.html`, checked against a real route. Already queued before BAB. Includes denomination cleanup and the `denomination == 'faab'` branch check.
- **BAB-specific wiring.** The frontend needs to stop sending or expecting `denomination` anywhere it currently does, and wallet views need to point at the new single-balance shape.

---

## Where BAB actually lands in this plan

Three seams, not a rewrite:

1. **Backend build** — after the wallet audit remainder (Batch A closed, B conditional on the formula, C pending deploy) and the `Transaction.type` check. **The reserve-ceiling formula must be authored and Math-Reviewed first (piece 2 / flagged open item).**
2. **Beef Batch E** — denomination removal and the *consumption* of the reserve-ceiling logic; owns repricing / lineup-change including setting (b)'s live-bet trigger.
3. **Frontend + contract audit** — wallet display update and denomination cleanup ride along with work already queued.

---

## The Deploy Gap (tracked as its own line in Rev 4, Finding 5.5)

This is a standing risk with its own failure mode, not a completion metric. It is deliberately *not* folded into the percentages.

- Batch C plus prior undeployed commits sit pending a deploy.
- Deploys go out **only** via `railway up --service fantasy-beefs` — the explicit `--service` flag is mandatory. A deploy without it (2026-07-07) targeted the Postgres service, stopped the working database, and caused ~20 minutes of downtime. Recovery was clean, no data loss, but the rule is now hard: always name the service.
- Batch C and the `ck_tx_type` constraint migration must deploy together.
- Track this line until the pending work is live and confirmed green in the Deployments tab (not merely "online" on the project map).

---

# PART 2 — The Pruning Ledger

BAB doesn't just add work. It deletes some. Naming the prunes explicitly so nothing gets "re-scoped" that should just be removed.

| What | Why it's gone | Where it lives today |
|---|---|---|
| `MAX_BET_PCT` (flat 20% cap) | Replaced entirely by the reserve-formula ceiling (which must first be written — see flagged open item) | `wallet/wallet_manager.py`, `MAX_BET_PCT = 0.20` constant and every check against it |
| `denomination` field (`faab`/`cash`) | One currency means the field carries no information | Schema (`Bet`, `BeefChallenge` tables), API contract, every frontend call site |
| FAAB top-up queue / obligation logic | FAAB is read-only now — it creates no obligation, needs no queue | `wallet/faab_wallet.py`'s top-up and obligation-tracking functions |
| Weekly Wednesday FAAB reconciliation cycle (for wagering purposes) | BAB reconciles once, at season end. FAAB itself still needs its own separate Tuesday-morning manual sync to Yahoo, but that's a display-mirror update, not a reconciliation | Commissioner reconciliation workflow, `wallet/faab_wallet.py` |
| Cash bucket / Real Money Wallet as a second bucket | Folded into BAB, doesn't exist as a separate wallet anymore | Old three-wallet-bucket architecture (P2 spec, B1 module) |
| Stripe integration path | Not deferred — abandoned permanently. No payment processor, ever | Was never built past "deferred to V2" in the spec; nothing to delete in code, but remove any reference in specs/docs |
| Wallet audit Batch B's original scope (`MAX_BET_PCT` enforcement on Beef challenges) | The rule it would have enforced is being deleted | Batch B ticket itself — re-scope, don't build as originally written |
| `wallet/faab_wallet.py`'s `transfer()` function — dead entirely, both directions. **Decided by Fraser, settled.** | No app-side waiver balance to move real money into or out of once FAAB is read-only | Removed in Beef Batch E. Note: this function was the subject of Batch A's Finding 2 survey, which closed a real live bug while the function is still in production. That work stays valid until Batch E ships and the function is deleted. |
| Stripe-queued `topup_waiver` flow — `pending_waiver_topup`, the Tuesday batch-apply job | FAAB funding through the app stops being a concept once FAAB is a pure Yahoo mirror | `wallet/faab_wallet.py` |
| The old "three tiers of money" model | Collapses to one tier: BAB obligation | B1 module spec |
| `wallet_obligations` table's `topup_faab`/`topup_cash` type values | Replaced by a single `topup_bab` type, matching the GM-prompted/commissioner-approved top-up flow (decided) | `db/schema.py`, `wallet_obligations` table |
| Commissioner's Wednesday "Cash self-credits" mechanism | No Cash bucket to self-credit into | Commissioner wallet-management tool |
| Dual-wallet display code (FAAB balance and Cash balance shown separately) | Collapses into one BAB balance | Frontend wallet view |

**One live wire, decided as real cleanup work, not yet executed:** any code path — validation, a wallet-lookup helper, a frontend cell — that still branches on `denomination == 'faab'`. This needs to be found and removed, not assumed gone. Rides along with the frontend-to-backend contract audit.

---

# APPENDIX A — Rev 2.0 / Deferred Work

**A note on these numbers.** Every estimate assumes your actual working pattern — Claude architects, Qwen or Claude Code builds, Opus reviews money-touching code. Grounded in what's actually been observed: Batch A's reservation cluster, estimated at 1–2 sessions, took roughly that once expanded scope was found (six sites, not three). The RosterSlot backfill, estimated at "1 session, mechanical," turned out to be blocked entirely on an unscoped Yahoo slot-sync dependency. **Rev 4 adds a second layer of caution: several estimates below are now marked provisional because their labels were never checked against the code. Treat every number as a floor, and treat any "provisional" number as not-yet-real until the named check runs.**

## Backend

| Item | Estimate | Notes |
|---|---|---|
| Wallet audit Batch B (re-scoped: reserve-ceiling enforcement on Beef challenges) | **Conditional — cannot be sized until the reserve-ceiling formula exists and is Opus-Math-Reviewed** (Finding 2.1) | Original `MAX_BET_PCT` piece pruned; real work is wiring into the new ceiling formula. Blocked on the flagged open item. |
| Wallet audit Batch C (pool-settlement fix) | Built | Done and verified; pending commit + deploy |
| `Transaction.type` granularity check + fix | Half session to check, 1 session to fix if needed | Read-only check first |
| **Reserve-ceiling formula — authorship** | **UNSCOPED — must be drafted + Opus-Math-Reviewed (Finding 3.1)** | The money-path rule replacing `MAX_BET_PCT`. Blocks Batch B, GM pre-bet notification, My Action BAB display, Batch E. Pulled out of the BAB build's 3–4 session estimate where it was hiding. Draft first, review, then build dependents. |
| **Yahoo lineup-slot sync** | **UNSCOPED — no estimate yet** | Populate `Roster.slot` with real starter/bench data from Yahoo. The true blocker in front of the RosterSlot backfill. Must be scoped before any estimate is trusted. Do not reuse the old RosterSlot "1 session" figure. |
| Roster sync — `RosterSlot` backfill | 1 session, **once the Yahoo slot-sync above is done** | Table and schema built. Straight copy once `Roster.slot` is populated — the blocker was never the copy, it was the missing source data. |
| Live 2026 season validation (`per_bet_lock.py`) | Half session to build from the finished spec — **provisional on re-running the caller grep at build time (Finding 4.6)** | `_nfl_lock_time()` done, deployed. `per_bet_lock.py` specced + Opus-reviewed. Loud contract break — safe only if the caller inventory is complete and current. |
| Beef Batch D (odds-lock-at-offer revert) | 1 session | Drafted, needs Opus review before landing. Implements the Option C launch lock model. |
| Beef Batch E (repricing / lineup-change + BAB consumption) | 2–3 sessions | "Five or six sub-problems wearing one name." Consumes the reserve-ceiling formula (does not author it). Owns setting (b)'s live-bet repricing trigger — verify build state (lock-timing open flag). |
| "Lite" power ranking | Half session — **provisional (Finding 4.5), see canonical line in Backend Remaining** | Data-cleanliness for all 12 teams unverified; one query confirms |
| BAB Wallet Model — full backend build | 3–4 sessions **for pieces 1, 3–7** — piece 2 (reserve-ceiling formula) is pulled out as the unscoped flagged item above | Buy-in split, top-up endpoint, weekly compliance report, season-end ledger, FAAB read-only mirror, `create_team()` factory |
| `league_id=1` hardcode fix | Half session | Needs real league-resolution source |
| Dedup of not-found checks | Half session — **provisional on grep confirming count + consistency (Finding 4.1)** | "Four" and "consistently" are asserted, not verified |

**Backend total, roughly: 10–14 sessions of *scoped* work — PLUS two unscoped items (the reserve-ceiling formula authorship and the Yahoo slot-sync), either of which could be significant.** Treat the real total as "10–14 plus an unknown," not "10–14." Not counting Decision Engine (deferred, Appendix B).

## Frontend

| Item | Estimate | Notes |
|---|---|---|
| Beef accept flow (doesn't exist) | 2–3 sessions | Real build. Blocked on Batch D. Launch-blocking. Should surface the three-way lock-reason message once `per_bet_lock.py` ships |
| Counter-offer UI on bet slip | 1 session — **provisional on backend endpoint confirmed complete (route+commit unverified, must enforce one-counter-max + stake-only) (Finding 4.3)** | Display only *if* backend is genuinely shipped |
| Reveal vs. Quiet Ledger toggle | **Verify: half session. Build if missing: unestimated until verified (Finding 4.2)** | Decision locked, code unverified. Old "1 session if missing" figure dropped |
| Non-participant handling UI | **Verify: half session. Build if missing: unestimated until verified (Finding 4.2)** | Decision locked, code unverified. Old "1 session if missing" figure dropped |
| Live leaderboard (pool bets) | 2 sessions | New UI surface. Fast-follow |
| My Action restructure | 2 sessions | Named, never built. Fast-follow |
| My Action countdown widget | Half session | Small, self-contained |
| The Lineup UI (starters/bench) | 1 session, **blocked on the Yahoo slot-sync (unscoped), not just the RosterSlot backfill** | The true blocker is bigger than previously understood |
| Standings layout decision + build | 1 session | Decision first |
| Bet slip DOM scoping fix | Half session — **provisional on independence from My Action restructure (Finding 4.4); if coupled, fold into that item** | Do not count separately if coupled |
| BAB wallet display update | 1 session | Display change on existing view. Launch Gate |
| GM-vs-Field tables (My League VP2, Section 3) | 1–2 sessions | Depends on backend odds endpoint |

**Frontend total, roughly: 13–17 sessions — and this range also rests on the unscoped Yahoo slot-sync** (The Lineup UI is blocked on it). Same "range plus an unknown" caution as Backend. Several line items are provisional pending the verification pass.

## Middleware / wiring

| Item | Estimate | Notes |
|---|---|---|
| Full frontend-to-backend contract audit (includes denomination cleanup, FAAB branch check) | 1–2 sessions | Will find more than it's looking for, per the standing pattern |
| Wire final locked odds into UI | Half session | Small, contained |
| `staleness_warning` — build or retire | Half session | May become moot once Batch D lands |

**Middleware total, roughly:** 2–3 sessions.

---

# APPENDIX A-2 — Multi-League Support (Rev 1.5 / 2.0)

**Deferred. Off the Rev 1.0 / August 1 critical path.** Rev 1.0 launches one league — CULV, twelve teams. This appendix captures the multi-league strategy so it is not lost, not to pull it forward. Build it after the single league is live and proven.

## The capability, in one line

One Yahoo login opens every Fantasy Beefs league a person belongs to, no matter who runs those leagues. Commissioners invite into their own league only. GMs consolidate all their invited leagues into one app view and toggle between them.

## What we are enabling

**Commissioner-driven onboarding, straight from Yahoo.** A commissioner enters a Yahoo league ID and authenticates once with their Yahoo account. The app reads that league's roster from Yahoo — every team owner's email is already there. The app pulls those emails, generates league-scoped invite links, and sends them out. No hand-typed email lists.

**GM entry through OAuth, no passwords in the app.** Each GM clicks their invite link and authenticates with their own Yahoo account. The invite carries the `league_id` in the URL. No password ever touches Fantasy Beefs — OAuth handles that.

**Single-league GMs land straight in.** Log in, the app sees one league, skips the picker, drops them into it. Zero friction.

**Multi-league GMs get a toggle.** A GM in more than one Fantasy Beefs league logs in once and sees all their leagues. Same dashboard, different data underneath.

**GM-side consolidation across different commissioners.** A GM can be in three Yahoo leagues run by three different commissioners, none of whom know about the others. The GM sees all three in one place — a keyring of three keys, each handed over by a different commissioner.

**Commissioners in multiple leagues get the same toggle, applied to My Commish.**

## The rules that hold it together

**Everyone sees only the leagues they belong to.** The picker is built from each person's own Yahoo-verified access.

**Commissioner isolation falls out of scoping, not extra work.** A consequence of scoping everything by `league_id`, not a feature to bolt on.

**The GM's Yahoo identity is the thread.** Every league membership ties back to the same authenticated Yahoo account.

## Discovery model — invite-only (default)

The app surfaces only leagues where the GM acted on a commissioner's invite — not every league their Yahoo account happens to be in. Revisit only if the friction proves real.

## What has to get built

- Replace the `league_id=1` hardcode with real league resolution keyed on the GM's Yahoo identity.
- Invite-generation flow: read team-owner emails from Yahoo, scope invite links to a `league_id`, send them.
- League switcher in the GM UI and in My Commish.

## What is already there

- The database is multi-league at the schema level today. Everything scopes under `league_id` already.
- The Yahoo OAuth flow is multi-league-ready — one token reads any league the account owns.
- Team count does not matter. Custom scoring reads from Yahoo per league.

## Sequencing

Rev 1.5 or Rev 2.0. Not Rev 1.0. Launch CULV first, prove it, then build the multi-league layer.

---

# APPENDIX B — Decision Engine and My Team

**FORMALLY DEFERRED OUT OF MVP SCOPE — Fraser's explicit decision, July 7, 2026.** Decision Engine, playoff probabilities, and My Team are out of the August 1 launch entirely. Pull in only if schedule allows, not as a default plan. This is a firmer statement than the appendix's prior framing — it is now a closed decision, not an open risk. UI for the wagering core stays a must-have and is unaffected by this deferral. This deferral does **not** change the four-bucket percent-complete denominator: Decision Engine work was never counted in Backend/Middleware/Frontend/Overall to begin with.

## What actually exists today

A single-week, two-lineup Monte Carlo simulator. Two GMs' projected lineups for one week in, a win probability out. Already powers the odds and betting board. Proven, tested, live.

## What doesn't exist — the real gap

A multi-week, whole-season simulator. Never built, because betting only ever needed this week's numbers. Everything downstream — Team Health, Decision Value, trade evaluation, the War Room, and playoff probabilities (Appendix C) — depends on this piece existing first.

## Rev 1 — Team Health (heat map only, no hypotheticals)

Estimated 2–3 weeks in the original spec. **The real blocker is FantasyPros, not build time.** The `ros=true` parameter has never been tested. The key reset is one click, 24-hour cooldown, still undone.

**If `ros=true` doesn't deliver:** full replan required.

## Rev 2 — Trades, waivers, Decision Value, before/after diffs, the War Room

Not spec'd yet, by design. A materially bigger lift than Rev 1. Six-plus sessions is a reasonable floor.

## Rev 3 — The Brain (conversational assistant)

Gated on Rev 2 existing. No honest estimate exists two dependency layers deep into unstarted work.

## My Team tab — the container

Deliberately split onto its own branch, off the August 1 critical path. My Team isn't one item — it's this whole appendix, wearing a tab.

## The one thing worth saying plainly

**Nothing about Decision Engine, My Team, or playoff probabilities touches the August 1 target.** Cut from critical path on purpose, formally confirmed. Keep this off the burner until FantasyPros is resolved and schedule allows.

---

# APPENDIX C — Playoff Probabilities Scoping

**Deferred alongside Appendix B.** Pulled out on its own so it can be looked at directly, separate from the rest of Rev 1/Rev 2 sequencing — that separation is for clarity, not priority. This stays off the August 1 critical path.

## Correction to an earlier version of this section

An earlier draft claimed playoff probabilities needs "the season-long simulator loop and nothing else." That was wrong. Computing league-wide playoff odds requires the *same* simulation core as per-team Team Health — `ProjectionEngine` → `LineupOptimizer` → `SeasonSimulator`, run for all 12 teams and aggregated. None of these exist as standalone modules today.

**One thing genuinely independent of all of this:** the "lite" power ranking — record, PF/PA, recent form. No Decision Engine dependency at all. **See the canonical Lite power ranking line in Backend Remaining (Finding 4.5) — its "no dependencies" label is itself provisional on a data-cleanliness check; this reference points there rather than repeating the claim.**

## What playoff probabilities needs, mechanically

1. A season schedule for every team — already available from Yahoo.
2. A per-team point projection, repeatable across every remaining week — the `ProjectionEngine` piece, doesn't exist as a standalone module today.
3. A win-probability estimate for every remaining game — the existing Monte Carlo engine can do this once; it's never been asked to do it repeatedly.
4. A way to run the season forward many times and count playoff appearances — new orchestration logic, nothing like it exists today.
5. Standings and playoff-format rules — likely knowable from Yahoo's league settings, needs confirming.

## Two real paths, not one

**Path A — degraded, buildable today, no FantasyPros needed.** Use each team's current-week projected strength, repeated flat across the schedule.

**Path B — the real version, needs `ros=true`.** Blocked entirely on the same FantasyPros dependency that blocks all of Rev 1.

## Recommendation

Since this stays deferred, no sequencing decision is needed now. When Decision Engine work resumes, the `ProjectionEngine`, `LineupOptimizer`, and `SeasonSimulator` pieces get built once and serve both playoff probabilities and Team Health.

---

# Decisions Made This Pass (cumulative)

- **BAB top-up — decided.** GM-prompted, commissioner-approved, app-tracked, reconciled at season end.
- **Weekly compliance report enforcement — starting soft, deliberately.** No auto-enforcement, no auto-placed bets. Revisit if 12 people actually need chasing.
- **`denomination == 'faab'` — real cleanup, not hypothetical.** Rides along with the contract audit.
- **Lock timing (this session) — decided.** Launch: Option C (versus lock at acceptance, via Batch D). Pools: week-level Thursday lock. Willingness bridge: My Commish setting (a) or (b), default (b). Target state: Option B per-player, versus-only, post-launch. Open flag: setting (b)'s live-bet repricing trigger may live in Batch E and may be unbuilt — verify before calling launch-ready.

## New feature, scoped this pass

**Opt-in pool-bet auto-assignment.** A My Settings toggle, off by default. Opt-in only, never a default. **Estimate:** half a session, maybe a full one.

---

# Open Questions, Still Carried Forward

- **Reserve-ceiling formula — NEW as a named open item this session (Finding 3.1).** Undefined. Referenced throughout as the `MAX_BET_PCT` replacement, never written down. Money-path. Blocks four items. Must be drafted and run through the Opus Math Review Protocol before any dependent is built. Highest-priority unknown on the critical path.
- **Yahoo lineup-slot sync.** No scope, no estimate yet. Blocks The Lineup UI and the RosterSlot backfill. Needs its own MODULE_SPEC before any estimate is trusted.
- **FantasyPros `ros=true`.** Still untested. Blocks the deferred Decision Engine appendices entirely. Blocks nothing on the wagering-core path to August 1.
- **Setting (b) live-bet repricing trigger.** May live in Batch E, may be unbuilt. Verify against code before calling the lock-timing setting (b) launch-ready.
- **Railway Postgres password rotation.** Deferred to launch week (Fraser's decision, 2026-07-07). Current password works; exposure blast radius small (private 12-person league, no public signups). Backup-first mandatory whenever it runs. Runbook to be written at rotation time. Confirmed root cause: Railway service-variable edits do not change the underlying postgres role password; the supported path is pg_dump → SSH into Postgres → temporary pg_hba.conf trust flip → ALTER USER → flip back to scram-sha-256 → update DATABASE_URL → redeploy with `--service fantasy-beefs`. The "Regenerate" button is avoided (Hobby-plan lockout reports).

---

# Recommended Next Sequence (new in Rev 4, Finding 5.1)

**This is a recommendation, not a binding order. Fraser makes the actual sequencing call.** The recommendation is built on the audit's core lesson: checking a label early is cheap; discovering a mislabel late is expensive (RosterSlot). The single most valuable move is to stop doing verification one-at-a-time at build time and do it once, up front.

**Step 1 — The Verification Pass (do this first, before any build queue).** One focused sitting, roughly one session. Run every cheap check the audit surfaced:
- Grep: not-found-check count and consistency (Finding 4.1).
- Grep: counter-offer backend route exists *and* enforces one-counter-max + stake-only (Finding 4.3).
- Grep: `per_bet_lock` caller inventory, re-run current (Finding 4.6).
- `app.html` read: Reveal/Quiet toggle present? (Finding 4.2).
- `app.html` read: non-participant handling present? (Finding 4.2).
- `app.html` read: is the bet-slip DOM scoping independent of the My Action restructure? (Finding 4.4).
- Query: standings/matchup data (record, PF/PA, recent form) clean for all 12 teams? (Finding 4.5).
- Check: is setting (b)'s live-bet repricing trigger built, or is it Batch E scope? (lock-timing open flag).

This converts roughly a dozen provisional estimates into real ones in a single session.

**Step 2 — Scope the two unscoped items.** Write a MODULE_SPEC for the Yahoo slot-sync and a draft-plus-Math-Review for the reserve-ceiling formula. Both block real work downstream; scoping them converts fuzzy totals into real ones and unblocks their dependents.

**Step 3 — Author + Math-Review the reserve-ceiling formula** before building any of its four dependents (Batch B, GM pre-bet notification, My Action BAB display, Batch E consumption).

**Step 4 — Build against the Launch Gate first.** Prioritize the gate's must-have capabilities (fund BAB, wallet display, one versus bet end-to-end via the Beef accept flow, one pool bet end-to-end, correct week lock, real-money settlement, reserve ceiling). Everything off the gate is fast-follow.

**Throughout — keep the Deploy Gap line current** and deploy only with `--service fantasy-beefs`.

---

# Percent-Complete Methodology

Every handoff to a new thread reports a percent-complete estimate across four buckets: Backend, Middleware/Wiring, Frontend/UI&UX, and Overall.

**Cancelled work is not counted, in either direction.** Pruned items are removed from the denominator entirely once confirmed pruned.

**Any change to the plan resets the metrics.** New scope, a pruned item, a re-sequencing — any of these means updating this document first, then recalculating percent-complete against the new total. The Decision Engine deferral does not trigger a reset — it was never in the denominator. The Yahoo slot-sync and the reserve-ceiling formula are flagged but not yet numerically reset, since no honest estimate exists yet to reset against.

**Rev 4 did not change any percentage.** The Plan Audit was a document review, not a build. It changed the plan's honesty, not its completion state.

---

# Zone 3 — Decision Log (append-only, never overwrite)

2026-07-06 | ESPN parse rewrite killed — connector verified correct against live probe + official schedule. Site scoreboard endpoint returns all 16 Week 1 games including Wednesday opener. No rewrite needed.
2026-07-06 | 272-row 2026 schedule loaded to production via railway run --service Postgres subshell + DATABASE_PUBLIC_URL override. Load is idempotent.
2026-07-06 | Machine verify surfaced SQLAlchemy naive read-back behavior — stored UTC times return tzinfo=None. Not a data bug; a read pattern. Lock fix spec accounts for it.
2026-07-06 | Opus anchor review: 16/18 cleared. Week 12 (GB @ LAR, Thanksgiving Eve TNF) confirmed correct. Week 18 anchor (05:00Z) confirmed ESPN TBD placeholder — real times not yet announced. Fix: ScheduleNotReadyError on placeholder detection; refresh cadence picks up real times post-Week 17.
2026-07-06 | _nfl_lock_time() MODULE_SPEC written. Two-part fix: naive→UTC promotion, placeholder rejection via UTC hour guard [9,26]. New ScheduleNotReadyError exception. Opus-gated before code ships.
2026-07-06 | Refresh cadence decided: twice weekly, Tuesday + Thursday morning. Build alongside player-data freshness job, not this session.
2026-07-06 | Throwaway scripts load_2026_schedule.py and verify_2026_schedule.py sitting at repo root — delete before next commit.
2026-07-06 | _nfl_lock_time() found — lives in betting/pool_engine.py line 81, NOT the ESPN connector. Spec pointed at wrong file twice. Real signature is (season, week) — no db param; opens its own SessionLocal internally.
2026-07-06 | Bug was not the primary path — primary MIN(kickoff_utc) query + naive→UTC promotion already correct. Real bug was the fallback: hardcoded 2024 formula, ValueError for any other season. Task shrank from rewrite to three surgical edits.
2026-07-06 | Opus review of lock spec, four findings, all approved: (F2) raw MIN grabs placeholder and masks a ready week — must filter before MIN; (F1) hour guard demoted to backup with documented fold math; (F3) ScheduleNotReadyError placement; (F4) split not-loaded vs loaded-but-timeless messages.
2026-07-06 | F3 flipped by ground truth — betting/exceptions.py docstring mandates all typed exceptions subclass ValueError. ScheduleNotReadyError therefore subclasses ValueError, defined in exceptions.py.
2026-07-06 | Placeholder guard built in Python (not ORM query) to match per_bet_lock.py house pattern — fold hours below 9 up by 24, valid band [9,26]. Verified against real and placeholder times.
2026-07-06 | Three edits shipped via Claude Code CLI: ScheduleNotReadyError added to exceptions.py; placeholder guard + 2024-fallback replacement in _nfl_lock_time; dead imports removed.
2026-07-06 | LIVE TEST GREEN — _nfl_lock_time(2026,1) returns 2026-09-10 00:20:00+00:00 read from production. End-to-end proven.
2026-07-06 | Committed 48356f1 (2 files, +34/-24). Not pushed, not deployed — code-only fix; prod schedule already loaded; deploy deferred to caller-wiring task.
2026-07-06 | Housekeeping: load/verify scripts deleted. Two probe leftovers still untracked — sweep or gitignore next session.
2026-07-06 | FLAG: DATABASE_PUBLIC_URL password appeared in plaintext in session — rotate the Railway Postgres credential.
2026-07-06 | FLAG: _nfl_lock_time MODULE_SPEC in project panel is stale (wrong file path, wrong signature). Correct or delete before next thread inherits it.
2026-07-07 | Checked project panel for stale _nfl_lock_time MODULE_SPEC — none found as a standalone file. Flag closed.
2026-07-07 | Six real call sites confirmed via repo-wide grep (not nine as handoff v30 stated): beef_engine.py — issue_challenge, respond_to_challenge, counter_challenge, get_pending_challenges; pool_engine.py — get_pool_week, submit_pool_pick. Three of six were swallowing ScheduleNotReadyError via a bare except ValueError.
2026-07-07 | Opus review, four findings, all resolved (F1 re-wrap safe against api boundary; F2 both branches set flag; F3 flag threaded onto ChallengeOut + ChallengeOut_API; F4 lock_expired local-only, no external fix).
2026-07-07 | MODULE_SPEC built and handed to Claude Code CLI. All six sites wired. Verified only two constructors of ChallengeOut/ChallengeOut_API exist repo-wide before editing.
2026-07-07 | Existing test_beef_starters.py passed clean post-edit (18 assertions). New smoke test test_schedule_not_ready_smoke.py written and run (9/9).
2026-07-07 | Committed c7ebad8 (4 files, +201/-5).
2026-07-07 | INCIDENT: railway up (no --service flag) deployed to the wrong service — stopped the working Postgres container (~20 min downtime). Fix: always pass --service fantasy-beefs. Recovery clean, no data loss.
2026-07-07 | FLAG ESCALATED then RESOLVED: build-log "POSTGRES_PASSWORD" was DATABASE_URL's own parsed contents (Nixpacks reads DATABASE_URL as a build variable). No Dockerfile exists (Nixpacks builds at deploy). No POSTGRES_PASSWORD variable on the service. Fix = rotate the credential, not delete a nonexistent variable.
2026-07-07 | Password rotation researched, DEFERRED to launch week. Railway service-variable edits do not change the postgres role password. Supported path: pg_dump → SSH → pg_hba trust flip → ALTER USER → flip back → update DATABASE_URL → redeploy --service. Regenerate button avoided. Current password works; small blast radius. Backup-first mandatory.
2026-07-07 | RosterSlot backfill — STOPPED, not built. Prod query: all 180 Roster rows slot=NULL. RosterSlot.slot NOT NULL — nothing to copy. Mislabeled "180 rows, mechanical" in three places, none checked. True blocker: unscoped Yahoo lineup-slot sync. No estimate.
2026-07-07 | per_bet_lock.py placeholder-window fix — MODULE_SPEC written, Opus-reviewed, five findings resolved. Ready to build, NOT built. Return contract changes bool → LockCheck(locked, reason), deliberate loud break. Single production caller confirmed via grep at spec time.
2026-07-07 | Decision Engine (Appendix B) and Playoff Probabilities (Appendix C) formally deferred, Fraser's explicit decision. Out of August 1 MVP scope. Does not reset percent-complete (never counted).
2026-07-07 | Session-wide pattern flagged: at least three claims in prior revisions (Dockerfile "confirmed" bug, RosterSlot "mechanical", v30 caller count) were unverified assumptions stamped as facts. Fraser requested an Opus-driven Plan Audit Protocol.
2026-07-07 | PLAN AUDIT SESSION (Rev 3 → Rev 4). Opus ran the Plan Audit Protocol, 15 findings across 5 questions. All 15 resolved with Fraser one at a time. Key outcomes: bet roster stated in-plan for first time (4 versus / 4 pool, sourced from session history not the stale Bible); DRAFT Launch Gate added (pending separate sufficiency audit); reserve-ceiling formula flagged as named unscoped open item requiring spec + Math Review, pulled out of the BAB build estimate; "session" defined (one context window, ~1hr); calendar reality-check added (~20 sessions/wk, scoped work ~1.5–2wk vs ~3.5wk runway); locked/confirmed vs decided-unverified vocabulary rule adopted; six "small/mechanical" estimates relabeled provisional pending a batched verification pass; Recommended Next Sequence added (verification-first); Deploy Gap promoted to its own tracked line.
2026-07-07 | LOCK TIMING re-decided during audit. Launch: Option C (versus lock at acceptance, via Batch D). Pools: week-level Thursday lock (per-participant timing doesn't apply). Willingness bridge: My Commish setting (a) lock-and-live or (b) Flexible Stake and Return with Max Stake Ceiling adjusts open bets to kickoff; default (b). Target: Option B per-player, versus-only, post-launch. OPEN FLAG: setting (b)'s live-bet repricing trigger may be Batch E scope and unbuilt — verify before calling launch-ready.
2026-07-07 | Rev 4 changed no percentages — document review only, not a build. Changed the plan's honesty, not its completion state.
2026-07-13 | FLAG CLOSED — POSTGRES_PASSWORD in ARG/ENV: confirmed not-applicable, not fixed, nothing to fix. No Dockerfile exists anywhere in the repo (railway.toml: build.builder = NIXPACKS). grep for POSTGRES_PASSWORD across the whole codebase returns zero hits in any code/config file — the only match is this log's own prior entry (2026-07-07) describing the original finding.
2026-07-13 | FLAG CLOSED — JWT_SECRET_KEY duplicate ARG/ENV: confirmed not-applicable, not fixed, nothing to fix. Same root cause as the POSTGRES_PASSWORD flag — no Dockerfile means no ARG/ENV mechanism exists to duplicate in the first place. JWT_SECRET_KEY appears exactly once in code (auth/jwt_auth.py:39, a single os.getenv() call).
