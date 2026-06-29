# Fantasy Beefs — New Thread Handoff v4.0
*Generated: June 28, 2026*
*Status: Active development. Load this document to resume.*

---

## Session Summary (June 28, 2026 — Session 2)

### What shipped this session:

**Phase 1 — COMPLETE**
- odds/odds_engine_headless.py — headless Monte Carlo port, all invariants passing
- Railway verified live: https://fantasy-beefs-production.up.railway.app
- Commits: 05be01a → c14c37c (10 commits)

**Phase 2 — Backend COMPLETE**
- betting/bet_engine.py — seam swap to odds_engine_headless, 8 bet functions (4 traditional + 4 Fantasybook)
- betting/pool_engine.py — Mode 3 pool engine, PoolConfig/PoolPrediction/PoolPot schema
- beefs/beef_engine.py — fixed (seam swap + bench_battle removed)
- betting/settlement_engine.py — dead full_beef code removed
- api/main.py — 8 bet routes + 4 Fantasybook routes wired with auth, full_beef dead route removed
- api/pool_routes.py — 6 pool endpoints with commissioner/GM auth
- api/bet_routes.py — DELETED (was unauthenticated duplicate)
- db/schema.py — PoolConfig, PoolPrediction, PoolPot models added

**Audited as already complete (no work needed):**
- wallet/wallet_manager.py — complete
- wallet/faab_wallet.py — complete (dual-wallet, Stripe, 3 buckets)
- reports/weekly_wrap.py — complete (The Sit-Down, AI-generated, email delivery)
- betting/settlement_engine.py — complete
- beefs/beef_engine.py — complete after fix

---

## Current State

**Railway:** Live at https://fantasy-beefs-production.up.railway.app
**Branch:** master, commit c14c37c
**DB:** PostgreSQL on Railway, 10 teams, 134 players, 6,834 projections (mock data)

**Backend routes live:**
- GET /league/standings
- GET /bets/{matchup_id}
- POST /bets/straight, /spread, /over_under, /prop
- POST /bets/more-overs, /closest-to-proj, /position-groups, /most-tds
- POST /pool/config, /collect, /predict, /settle
- GET /pool/config/{league_id}, /pool/predictions/{league_id}/{week}
- GET /health/team/{team_id}?week=N
- POST /war-room/evaluate
- GET /faab/wallet/{team_id}
- GET /reports/wrap-up/{league_id}/{week}
- Full auth, beef challenge, wallet, FAAB, stripe routes (pre-existing)

---

## What's Next — Phase 2 Frontend

**This is the next priority.** Backend is complete. Frontend build starts now.

### UI Decisions Locked
- Mobile-first web, same design language as odds calculator
- Background: #F5F2ED (warm off-white), system-ui fonts
- Single app shell: tools/app.html + tools/components.css
- One HTML shell, 5 tab views swapped via JavaScript
- Odds calculator logic extracted (copy, never modify tools/index.html)

### App Structure (locked)
5 principal tabs, bottom nav:
My League · My Action · My Team · My Account · My Commish

**My League:**
- VP1 Standings — GET /league/standings
- VP2 The Book — GET /bets/{matchup_id} + GET /pool/predictions/{league_id}/{week}

**My Action:**
- VP1 This Week — GET /bets/{matchup_id} (active bets)
- VP2 My Record — GET /wallet/{team_id}/history
- VP3 My History — GET /wallet/{team_id}/history (paginated)

**My Team:**
- VP1 Team Health — GET /health/team/{team_id}?week=N (already has team_health.html — port to shell)
- VP2 War Room — POST /war-room/evaluate (already has war_room.html — port to shell)
- VP3 My Outlook — GET /health/team/{team_id}?week=N (playoffs array)

**My Account:**
- VP1 Wallet — GET /faab/wallet/{team_id}

**My Commish:**
- VP1 Settings — GET /pool/config/{league_id} + commissioner routes
- VP2 Operations — POST /pool/collect, /pool/settle, settlement triggers

### Existing Tools (port to shell, DO NOT MODIFY originals)
- tools/index.html — odds calculator (extract JS pricing logic only)
- tools/team_health.html — Team Health (port layout/logic to shell VP)
- tools/war_room.html — War Room (port layout/logic to shell VP)

### Build Order
1. tools/components.css — design tokens, all reusable components
2. tools/app.html — shell with bottom nav, tab switching, auth header
3. My League VP1 Standings — first screen, establishes all core patterns
4. My Team VP1 Health — port existing team_health.html
5. My Action VP1 The Book — most complex, builds on established patterns
6. Remaining VPs in dependency order

### Reusable Components to Define in components.css
- Stat card (rank, W/L, PF/PA, bankroll)
- Moneyline display (American odds, fav/dog styling)
- Player row (name, position, projected pts, injury flag)
- Opponent card (collapsed + expanded states)
- Bet chip (tap to select bet type)
- Bet slip drawer (slides up from bottom)
- Pool card (pinned to top of The Book)
- Section label
- Badge (your game, injury status)
- Bottom nav bar

---

## Key Architecture Decisions (carry forward)

- odds_engine_headless.py is the single source of truth for all bet pricing
- Data provider seam: mock now, Yahoo swap-in at Phase 3 end
- Escrow: Flexible Stake and Return with Max Stake Ceiling
- Mode 2 ZBB'd, Mode 4 deferred to V2+
- Bench Battle ZBB'd
- Qwen never starts a module until Claude Code locks the seam
- Mobile-first web, 380px viewport target
- tools/index.html is READ-ONLY — never modify

---

## Three-Engine Model (unchanged)
1. Claude (this chat) — architecture, specs, decisions
2. Claude Code CLI (PyCharm terminal, ThinkPad X13) — multi-file builds, seams
3. Qwen (100.127.74.98:3000, Open WebUI) — single-file algorithmic modules

## Dev Environment (unchanged)
- ThinkPad X13 Gen 3, Windows 11 Pro, PyCharm
- Project: C:\Users\frase\OneDrive\PycharmProjects\fantasy-beefs\
- GitHub: FDCHub/fantasy-beefs, branch: master
- Railway: https://fantasy-beefs-production.up.railway.app
- Qwen: 100.127.74.98:3000 (Open WebUI)

---

*Load this document at the start of the next thread. Then write the Claude Code prompt for tools/components.css + tools/app.html shell.*
