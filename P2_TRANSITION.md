# Fantasy Beefs — P2 Session Transition Document

**Date:** 2026-05-25
**Status:** P1 Complete. P2 not started.
**Working directory:** `C:\Users\frase\PycharmProjects\`
**Start P2 prompt (copy-paste into next session):**

> "This is Fantasy Beefs. P1 is complete.
> PROJECT_STATUS.md is at C:\Users\frase\PycharmProjects\PROJECT_STATUS.md
> Start P2."

---

## Session Summary

P1 is fully complete. The platform is a working 10-team fantasy football betting
league with a FastAPI backend, SQLite database, Monte Carlo odds engine, full GM
authentication, Stripe Connect treasury, FAAB split wallets, AI-powered weekly
wrap-up emails, power rankings, and a Tuesday automation pipeline that runs all of
it end-to-end with one command.

Two bet type updates were also completed as a bridge between P1 and P2:
- Prop bet redefined as top projected starter vs top projected starter (head-to-head,
  app auto-selects both players)
- The Full Beef added: best-of-3 structured matchup across DEF, K, and Bench, win 2+
  legs to win — no vig, no ties possible

Total: 78 API routes, 25 DB tables, 10 migrations, ~4,500 lines of Python.

---

## P1 Completion Record

### P1.1 — JWT Authentication  ✅
Files: `auth/jwt_auth.py`, `db/migrate_auth.py`

HS256 JWT with 8h expiry. GM and Commissioner roles. `assert_own_wallet` and
`assert_own_team` helpers. `seed_users()` creates 10 accounts on DB reset.
Commissioner: kevin.mahoney@gmail.com. Default password: `beefs2024`.
Guards on all write endpoints. bcrypt 4.0.1 pinned for passlib 1.7.4 compat.

### P1.2 — Stripe Connect Payments  ✅
Files: `payments/stripe_connect.py`, `db/migrate_payments.py`

Treasury setup, buy-in Payment Links, Stripe Connect onboarding, payout preview
and execution. Mock mode when `STRIPE_SECRET_KEY` unset. All amounts in cents
internally. `get_buyin_gate()` FastAPI dependency blocks /bets/* and /beef if
buy-in unpaid. Default payout split: [60, 30, 10].

### P1.3 — FAAB Split Wallets  ✅
Files: `wallet/faab_wallet.py`, `db/migrate_faab.py`

Separate bet and waiver wallets. Bet wallet auto-freezes at $0. Waiver top-ups
queue for Tuesday 03:00 UTC. Transfer in both directions (commissioner-configurable).
`get_bet_funded()` dependency replaces `get_buyin_gate()` on all bet endpoints
(chains auth → buy-in → freeze check). Zero vig in FAAB mode.

### P1.4 — Commissioner Rules Engine  ✅
Files: `admin/commissioner_rules.py`, `db/migrate_rules.py`

AI-parsed natural language rules (Ollama → Anthropic → heuristic fallback).
Weekly and end-of-season rule types. Obligation and payout effects. Escrow
accounts with auto-release at end of season. Full audit trail. Idempotent execution.
12 API endpoints.

### P1.5 — Tuesday Automation  ✅
Files: `notifications/tuesday_sync.py`, `db/migrate_sync.py`

9-step weekly pipeline: settle bets → execute rules → freeze wallets → apply
top-ups → FAAB report → email commissioner → weekly wrap-up → power rankings
→ email GMs. APScheduler cron at Tuesday 12:01am UTC. Step isolation: one failure
never kills the run. Full run history in DB. Mock email mode when SMTP unset.
Smoke test: 9/9 steps OK, 21 emails, 55.6s.

### P1.6 — Weekly Wrap-Up + Roast Beef  ✅
Files: `reports/weekly_wrap.py`, `reports/__init__.py`, `db/migrate_wrap.py`

League Edition (all matchup recaps, Beef of the Week, Roast Beef) + My Edition
(personalized per GM with lineup grade, bet performance, status tag, playoff prob).
AI chain: Ollama → Anthropic Claude → template fallback (always produces output).
Jedi brand voice. 6 API endpoints. 10 GM editions per wrap-up, stored in DB.

Status tags: Contender · On the Bubble · Spoiler · The Beef Is Strong Within You
Lineup grades: A (<5 pts left) · B (5–15) · C (15–25) · D (>25)

### P1.7 — Power Rankings  ✅
Files: `reports/power_rankings.py`, `db/migrate_rankings.py`

Three dimensions: On-Field (50%), Betting (30%), Waiver Wire (20%).
Composite GM Rating via min-max normalization + weighted sum.
Rank change week-over-week. Status tags matching wrap-up system.
Feed post on compute. Season arc queryable. 4 API endpoints.

Weights:
  On-Field  = win_rate(50%) + pts_for(35%) + SOS(15%)
  Betting   = bet_win_rate(45%) + ROI(40%) + streak(15%)
  Waiver    = pts per FAAB dollar (0.5 for all teams when no activity)

### Bet Type Updates (P1 → P2 bridge)  ✅
Files: `betting/bet_engine.py`, `betting/settlement_engine.py`,
       `db/migrate_full_beef.py`, `api/main.py`

**Prop bet (redefined):** `place_prop_bet(matchup_id, wallet_id, picked_team_id,
amount, week, db)`. App auto-selects each team's highest projected starter (slots 1–9).
Simulates both players via Monte Carlo. Pick whose player scores more.
DB storage: `player_id` = home top player ID, `side` = str(away top player ID).
Settlement compares actual_points of the two stored player IDs.

**The Full Beef (new):** `place_full_beef(matchup_id, wallet_id, picked_team_id,
amount, week, db)`. Best-of-3: DEF vs DEF (leg 1), K vs K (leg 2), Bench vs Bench
(leg 3). All legs simulated independently. Win 2+ legs to win the bet. No ties
possible. Returns `BetResult.legs` with per-leg player names and projections.
Settlement uses `_position_actual()` helper to look up actual scored points.
Migration v10 recreated the bets table via rename/copy/drop to add 'full_beef'
to the ck_bet_type CHECK constraint. 6 existing rows preserved.

---

## Repository Layout (Current State)

```
C:\Users\frase\PycharmProjects\
│
├── db/
│   ├── schema.py             ORM models, engine, seeder — all 25 tables
│   ├── deps.py               Shared FastAPI get_db() dependency
│   ├── fantasy.db            SQLite database (generated)
│   ├── migrate_scoring.py    Migration v1  — league_scoring, projection_source
│   ├── migrate_v2.py         Migration v2  — bench_battle, injury_status, staleness
│   ├── migrate_auth.py       Migration v3  — users table + seed accounts
│   ├── migrate_payments.py   Migration v4  — Stripe tables + user columns
│   ├── migrate_faab.py       Migration v5  — FAAB wallet tables
│   ├── migrate_rules.py      Migration v6  — Commissioner rules + escrow tables
│   ├── migrate_sync.py       Migration v7  — tuesday_sync_runs table
│   ├── migrate_wrap.py       Migration v8  — weekly_wrap_ups + gm_editions tables
│   ├── migrate_rankings.py   Migration v9  — power_rankings table
│   └── migrate_full_beef.py  Migration v10 — bets table recreated with full_beef
│
├── auth/
│   └── jwt_auth.py           JWT auth, role guards, register/login, seed_users
│
├── odds/
│   └── monte_carlo.py        N_SIMS=10,000 · scoring adjustment · simulate_player_scores
│
├── betting/
│   ├── bet_engine.py         6 bet types: straight, spread, over_under, prop,
│   │                           bench_battle (beef), full_beef
│   └── settlement_engine.py  settle_week() · _eval_prop · _eval_full_beef_bet
│
├── wallet/
│   ├── wallet_manager.py     Deposit / withdraw / balance / tx history; bet-sizing
│   └── faab_wallet.py        FAAB: split wallets, top-ups, transfers, freeze/unfreeze
│
├── beefs/
│   └── beef_engine.py        GM-to-GM challenges · staleness_warning · bench_battle
│
├── feed/
│   └── league_feed.py        Activity feed · challenge + settlement events · trash talk
│
├── payments/
│   └── stripe_connect.py     Treasury · buy-ins · Stripe Connect · payouts · webhook
│
├── admin/
│   └── commissioner_rules.py AI-parsed rules · escrow · weekly + EOS execution
│
├── notifications/
│   └── tuesday_sync.py       9-step Tuesday pipeline · APScheduler · ASCII report
│
├── reports/
│   ├── __init__.py
│   ├── weekly_wrap.py        AI wrap-up · My Edition + League Edition · Roast Beef
│   └── power_rankings.py     3-dimension composite GM Rating · rank_change · arc
│
├── mock_league.py            10-team NPC seed data (replaced by Yahoo in P2.3)
│
└── api/
    └── main.py               FastAPI app · 78 routes · port 8007
```

---

## Database Tables

```
┌─────────────────────┬──────────────────────────────────────────────────────────────────┐
│ Table               │ Purpose & Key Columns                                            │
├─────────────────────┼──────────────────────────────────────────────────────────────────┤
│ leagues             │ id, season, name, projection_source                              │
│ league_scoring      │ league_id (1:1), scoring_type*, rec_points, pass_td_points,     │
│                     │   rush_td_points, rec_td_points, bonus_100yd_rush/rec            │
│ teams               │ id, league_id, team_name, owner, email                          │
│ players             │ id, name, position* (QB/RB/WR/TE/FLEX/K/DEF)                   │
│ rosters             │ team_id + player_id (unique); slots 1-9 = starters, 10+ = bench │
│ matchups            │ id, league_id, week, home_team_id, away_team_id,                │
│                     │   home_score, away_score, winner_team_id                         │
│ wallets             │ id, team_id (1:1), balance (default $1,000)                     │
│ bets                │ id, matchup_id, wallet_id, picked_team_id, player_id,           │
│                     │   bet_type*, line, side, amount, odds, status*,                  │
│                     │   placed_at, settled_at, beef_challenge_id                       │
│                     │   bet_type values: straight · spread · over_under · prop ·       │
│                     │     bench_battle · full_beef                                     │
│ transactions        │ id, wallet_id, amount (+credit / -debit), type*, bet_id         │
│ projections         │ id, player_id, week, season, source*, projected_points,         │
│                     │   actual_points, injury_status†                                  │
│ beef_challenges     │ id, challenger/challenged team_id, week, bet_type*, amount,     │
│                     │   line, side, player_id, challenger/challenged_odds + moneyline, │
│                     │   status*, expires_at, projection_snapshot, staleness_warning†   │
│ feed_events         │ id, league_id, week, event_type, actor_team_id,                │
│                     │   target_team_id, challenge_id, bet_id,                         │
│                     │   headline, trash_talk, created_at                               │
│                     │   INDEX on (league_id, created_at)                               │
│ users               │ id, email (unique), hashed_password, team_id (unique FK),       │
│                     │   role* (gm|commissioner), is_active, buy_in_paid,              │
│                     │   stripe_account_id, created_at, last_login_at                  │
│ league_treasury     │ id, league_id (1:1), buy_in_amount_cents, payout_split_json,   │
│                     │   total_collected_cents, total_paid_out_cents, season_payout_done│
│ buy_in_records      │ id, league_id, team_id (1:1/season), user_id, amount_cents,    │
│                     │   status* (pending|paid|refunded), stripe_payment_link_id/url,  │
│                     │   stripe_session_id, stripe_payment_intent_id, paid_at          │
│ payout_records      │ id, league_id, team_id, user_id, place, amount_cents, pct,     │
│                     │   status* (pending|sent|failed), stripe_transfer_id,            │
│                     │   stripe_connected_account, sent_at                             │
│ stripe_audit_log    │ id, league_id, team_id, event_type, stripe_object,             │
│                     │   amount_cents, description, raw_response,                      │
│                     │   performed_by_user_id, created_at                              │
│                     │   INDEX on (league_id, created_at)                              │
│ faab_config         │ id, league_id (1:1), opening_bet, opening_waiver,              │
│                     │   allow_bet_to_waiver, allow_waiver_to_bet, season_initialized  │
│ faab_wallets        │ id, team_id (1:1), league_id, waiver_balance,                 │
│                     │   pending_waiver_topup (queued for Tuesday), bet_frozen         │
│ faab_transactions   │ id, league_id, team_id, type*, amount, wallet_from, wallet_to, │
│                     │   status*, note, stripe_link_id/url, apply_on, applied_at       │
│                     │   INDEX on (team_id, created_at)                                │
│                     │   types: opening_credit · topup_bet · topup_waiver ·            │
│                     │     transfer_bet_to_waiver · transfer_waiver_to_bet ·           │
│                     │     waiver_bid · waiver_refund · funding_alert                  │
├─────────────────────┼──────────────────────────────────────────────────────────────────┤
│ commissioner_rules  │ id, league_id, raw_text, rule_type* (weekly|end_of_season),    │
│                     │   effect_type* (obligation|payout),                             │
│                     │   target* (biggest_loss_margin|missed_lineup|points_leader|     │
│                     │           commissioner_manual),                                 │
│                     │   amount, has_escrow, escrow_release_trigger,                  │
│                     │   escrow_release_target, ai_interpretation, ai_model_used,     │
│                     │   status* (draft|active|paused|completed), week_start, week_end │
│ escrow_accounts     │ id, league_id, rule_id (1:1), name, balance,                  │
│                     │   status* (open|released|refunded),                             │
│                     │   release_trigger* (end_of_season|manual),                     │
│                     │   release_team_id, released_at                                  │
│ escrow_transactions │ id, escrow_id, league_id, team_id, direction* (in|out),        │
│                     │   amount, description, created_at                               │
│ rule_executions     │ id, rule_id, league_id, week, team_id, effect_type*,           │
│                     │   amount, description,                                          │
│                     │   status* (pending|collected|held_in_escrow|paid_out|           │
│                     │           waived|failed), escrow_id, executed_at, settled_at   │
│ rule_audit_log      │ id, rule_id, league_id, performed_by_user_id, event_type,      │
│                     │   description, ai_model, ai_latency_ms, raw_data, created_at   │
├─────────────────────┼──────────────────────────────────────────────────────────────────┤
│ tuesday_sync_runs   │ id, run_id (UUID hex), league_id, week,                        │
│                     │   status* (running|completed|completed_with_errors|failed),     │
│                     │   mock_mode, steps_json, error_count, emails_sent,             │
│                     │   started_at, finished_at                                       │
├─────────────────────┼──────────────────────────────────────────────────────────────────┤
│ weekly_wrap_ups     │ id, run_id (UUID hex), league_id, week,                        │
│                     │   status* (draft|ready|sent), league_body, roast_beef,         │
│                     │   ai_model_used, ai_latency_ms, commissioner_edited,           │
│                     │   created_at, updated_at, sent_at                               │
│ wrap_up_gm_editions │ id, wrap_up_id (FK), league_id, team_id, week, body,          │
│                     │   status_tag* (contender|bubble|spoiler|chaos),                │
│                     │   playoff_prob_change, sent, sent_at, created_at               │
├─────────────────────┼──────────────────────────────────────────────────────────────────┤
│ power_rankings      │ id, league_id, week, team_id (UNIQUE per league+week+team),    │
│                     │   on_field_rank, on_field_score (0–1),                         │
│                     │   wins, losses, points_for, points_against, sos,               │
│                     │   betting_rank, betting_score (0–1),                           │
│                     │   bet_wins, bet_losses, roi, best_win_amount,                  │
│                     │   worst_loss_amount, bet_streak (+n=hot / -n=cold),            │
│                     │   waiver_rank, waiver_score (0–1),                             │
│                     │   waiver_dollars_spent, waiver_pts_added, pts_per_dollar,      │
│                     │   composite_rank, composite_score (0–1),                       │
│                     │   rank_change (+n=up / -n=down; NULL first week),              │
│                     │   status_tag* (contender|bubble|spoiler|chaos), created_at     │
│                     │   INDEX on (league_id, week)                                   │
└─────────────────────┴──────────────────────────────────────────────────────────────────┘

* CHECK constraint enforced   † Added in migration v2
Total: 25 tables
```

**Seeded data** — `python db/schema.py` resets and seeds:
- 1 league · 10 teams · 150 unique players · 170 roster slots
- 85 matchups (17 weeks × 5 games) with actual scores
- 7,650 projections (150 players × 17 weeks × 3 sources: fantasypros · espn · yahoo)
- 10 wallets at $1,000 each · 10 user accounts (password: beefs2024)

---

## Migration History

```
┌──────────────────────┬──────────────────────────────────────────────────────────────┐
│ Script               │ What it does                                                 │
├──────────────────────┼──────────────────────────────────────────────────────────────┤
│ schema.py            │ Full reset — drop_all, create_all, seed_from_mock            │
│ migrate_scoring.py   │ v1  — league_scoring table, projection_source column         │
│ migrate_v2.py        │ v2  — bench_battle, injury_status, staleness_warning         │
│ migrate_auth.py      │ v3  — users table + seed 10 accounts                        │
│ migrate_payments.py  │ v4  — Stripe tables + users.buy_in_paid/stripe_account_id   │
│ migrate_faab.py      │ v5  — faab_config, faab_wallets, faab_transactions           │
│ migrate_rules.py     │ v6  — 5 commissioner rules tables                           │
│ migrate_sync.py      │ v7  — tuesday_sync_runs table                               │
│ migrate_wrap.py      │ v8  — weekly_wrap_ups + wrap_up_gm_editions                 │
│ migrate_rankings.py  │ v9  — power_rankings table                                  │
│ migrate_full_beef.py │ v10 — bets table recreated (rename/copy/drop) for full_beef │
└──────────────────────┴──────────────────────────────────────────────────────────────┘
```

---

## API Endpoints (All 78)

Server: `uvicorn api.main:app --port 8007`

```
┌──────────┬────────────────────────────────────┬──────────────────────────────────────┐
│ Method   │ Path                               │ Description                      Auth │
├──────────┼────────────────────────────────────┼──────────────────────────────────────┤
│ POST     │ /auth/register                     │ Create GM account (email→team)  open │
│ POST     │ /auth/login                        │ OAuth2 form → JWT token         open │
│ GET      │ /auth/me                           │ Current user info               gm   │
│ POST     │ /auth/promote                      │ Set role (gm ↔ commissioner)    comm │
├──────────┼────────────────────────────────────┼──────────────────────────────────────┤
│ GET      │ /health                            │ DB check + league info          open │
├──────────┼────────────────────────────────────┼──────────────────────────────────────┤
│ GET      │ /league/standings                  │ Sorted win/loss/PF/PA           open │
│ GET      │ /league/matchups/{week}            │ All matchups with scores        open │
│ GET      │ /league/roster/{team_id}           │ 15-player roster + balance      open │
├──────────┼────────────────────────────────────┼──────────────────────────────────────┤
│ GET      │ /projections/{week}                │ Player projections ?source=     open │
│ GET      │ /odds/{matchup_id}/{week}          │ Monte Carlo moneylines + lines  open │
├──────────┼────────────────────────────────────┼──────────────────────────────────────┤
│ POST     │ /bets/straight                     │ Team wins outright              gm†  │
│ POST     │ /bets/spread                       │ Team covers a spread            gm†  │
│ POST     │ /bets/over_under                   │ Combined score over/under       gm†  │
│ POST     │ /bets/prop                         │ Top starter vs top starter      gm†  │
│ POST     │ /bets/full_beef                    │ DEF/K/Bench best-of-3           gm†  │
│ GET      │ /bets/{matchup_id}                 │ All bets on a matchup           open │
│ GET      │ /settle/{week}                     │ Settle pending bets             comm │
├──────────┼────────────────────────────────────┼──────────────────────────────────────┤
│ POST     │ /wallet/deposit                    │ Credit wallet                   gm   │
│ POST     │ /wallet/withdraw                   │ Debit (blocked if exposed)      gm   │
│ GET      │ /wallet/{team_id}                  │ Balance + open bets + txns      open │
│ GET      │ /wallet/{team_id}/history          │ Paginated tx history            open │
├──────────┼────────────────────────────────────┼──────────────────────────────────────┤
│ POST     │ /beef/challenge                    │ Issue GM-to-GM challenge        gm†  │
│ POST     │ /beef/respond                      │ Accept or decline challenge     gm   │
│ GET      │ /beef/pending/{team_id}            │ Sent + received challenges      gm   │
├──────────┼────────────────────────────────────┼──────────────────────────────────────┤
│ POST     │ /payments/setup-treasury           │ Set buy-in + payout split       comm │
│ GET      │ /payments/treasury/{league_id}     │ Treasury state + progress       open │
│ GET      │ /payments/buyin-status/{league_id} │ All teams' buy-in status        gm   │
│ POST     │ /payments/buyin-link/{team_id}     │ Stripe Payment Link for buy-in  gm   │
│ POST     │ /payments/buyin-confirm            │ Manual buy-in confirmation      comm │
│ GET      │ /payments/connect-link/{team_id}   │ Stripe Connect onboarding URL   gm   │
│ GET      │ /payments/payout-preview/{league_id}│ Preview season payout amounts  comm │
│ POST     │ /payments/payout-execute           │ Execute payouts via Stripe      comm │
│ GET      │ /payments/audit-log/{league_id}    │ Full Stripe event audit trail   comm │
│ POST     │ /payments/webhook                  │ Stripe webhook receiver         open │
├──────────┼────────────────────────────────────┼──────────────────────────────────────┤
│ POST     │ /faab/setup                        │ Configure wallets + rules       comm │
│ GET      │ /faab/config/{league_id}           │ View FAAB config                gm   │
│ POST     │ /faab/init-season                  │ Credit opening balances         comm │
│ GET      │ /faab/wallet/{team_id}             │ Combined bet+waiver state       gm   │
│ GET      │ /faab/league/{league_id}           │ All teams' FAAB states          gm   │
│ POST     │ /faab/topup-bet                    │ Top up bet wallet (Stripe)      gm   │
│ POST     │ /faab/topup-waiver                 │ Queue waiver top-up (Tuesday)   gm   │
│ POST     │ /faab/topup-confirm                │ Confirm pending top-up          comm │
│ POST     │ /faab/apply-pending                │ Apply due waiver top-ups        comm │
│ POST     │ /faab/transfer                     │ Move funds bet ↔ waiver         gm   │
│ GET      │ /faab/transactions/{team_id}       │ FAAB transaction history        gm   │
│ POST     │ /faab/freeze                       │ Freeze/unfreeze bet wallet      comm │
├──────────┼────────────────────────────────────┼──────────────────────────────────────┤
│ POST     │ /rules/parse                       │ AI-parse text → preview         comm │
│ POST     │ /rules/create                      │ Save as draft rule              comm │
│ GET      │ /rules/league/{league_id}          │ List rules ?status=             comm │
│ GET      │ /rules/{rule_id}                   │ Get one rule                    comm │
│ POST     │ /rules/activate/{rule_id}          │ Draft → active + escrow         comm │
│ POST     │ /rules/pause/{rule_id}             │ Pause active rule               comm │
│ DELETE   │ /rules/draft/{rule_id}             │ Delete draft rule               comm │
│ POST     │ /rules/execute-weekly              │ Run active weekly rules         comm │
│ POST     │ /rules/execute-end-of-season       │ Run EOS rules + release escrow  comm │
│ GET      │ /rules/executions/{league_id}      │ Paginated execution history     comm │
│ POST     │ /rules/release-escrow/{escrow_id}  │ Manually release escrow         comm │
│ GET      │ /rules/audit/{league_id}           │ Full rule audit trail           comm │
├──────────┼────────────────────────────────────┼──────────────────────────────────────┤
│ POST     │ /admin/tuesday-sync                │ Trigger Tuesday run (mock=T)    comm │
│ GET      │ /admin/tuesday-sync/runs/{league_id}│ Run history (limit=20)         comm │
│ GET      │ /admin/tuesday-sync/run/{run_id}   │ Full step detail for a run      comm │
├──────────┼────────────────────────────────────┼──────────────────────────────────────┤
│ POST     │ /reports/wrap-up/generate          │ Generate wrap-up (AI)           comm │
│ GET      │ /reports/wrap-up/{league_id}/{week}│ Get wrap-up for a week          comm │
│ GET      │ /reports/wrap-up/{league_id}       │ List wrap-ups ?limit=           comm │
│ PUT      │ /reports/wrap-up/{wrap_up_id}      │ Edit league_body or roast_beef  comm │
│ POST     │ /reports/wrap-up/{league_id}/send  │ Re-send after edits             comm │
│ GET      │ /reports/wrap-up/{league_id}/editions│ Per-GM edition detail         comm │
├──────────┼────────────────────────────────────┼──────────────────────────────────────┤
│ POST     │ /reports/rankings/compute          │ Compute power rankings          comm │
│ GET      │ /reports/rankings/{league_id}/{week}│ All teams for a week           open │
│ GET      │ /reports/rankings/{league_id}/arc  │ All weeks — season arc          open │
│ GET      │ /reports/rankings/{id}/team/{id}   │ One team's history              open │
│ GET      │ /docs                              │ Swagger UI                      open │
│ GET      │ /redoc                             │ ReDoc                           open │
│ GET      │ /openapi.json                      │ OpenAPI schema                  open │
└──────────┴────────────────────────────────────┴──────────────────────────────────────┘

Total: 78 routes

† /bets/* and /beef/challenge require: authenticated + buy-in paid (if configured) +
  bet wallet balance > $0 (if FAAB initialized). HTTP 402 if either gate fires.

Auth: open = no token · gm = any authenticated user · comm = commissioner only
```

---

## NPC League Details

```
┌────┬──────────────────────────┬──────────────────────────┬───────────────────────────┐
│ ID │ Team Name                │ Owner                    │ Email                     │
├────┼──────────────────────────┼──────────────────────────┼───────────────────────────┤
│  1 │ Mahomes Alone            │ Kevin Mahoney (COMM)     │ kevin.mahoney@gmail.com   │
│  2 │ Hurts So Good            │ Phil Hurtado             │ phil.hurtado@gmail.com    │
│  3 │ Run CMC                  │ Mac Forrester            │ mac.forrester@gmail.com   │
│  4 │ Lamar Mania              │ Jackson Raves            │ jackson.raves@gmail.com   │
│  5 │ Ja'Marr the Merrier      │ Marcy Bengston           │ marcy.bengston@gmail.com  │
│  6 │ Room to Grubb            │ Ryan Grubb               │ ryan.grubb@gmail.com      │
│  7 │ This Is The Kelce Way    │ Travis Mando             │ travis.mando@gmail.com    │
│  8 │ Mixon It Up              │ Jo Mixley                │ jo.mixley@gmail.com       │
│  9 │ Ekeler Island            │ Austin Webb              │ austin.webb@gmail.com     │
│ 10 │ Wren It Rains It Pours   │ Wren Stormfield          │ wren.stormfield@gmail.com │
└────┴──────────────────────────┴──────────────────────────┴───────────────────────────┘

Default password for all: beefs2024 (change before real deployment)

Key roster notes (for UI/UX context):
  Team 1 (Kevin/COMM) — Mahomes, Henry, Lamb, Jefferson, Butker K, Cowboys DEF
  Team 2 (Phil)       — Hurts, Barkley, Achane, Hill, Adams, 49ers DEF
  Team 3 (Mac)        — CMC, Josh Allen, Chase, Kelce TE, Ravens DEF
  Team 4 (Jackson)    — Lamar, Kamara, Andrews TE, Steelers DEF
  Team 5 (Marcy)      — Burrow, Chase, Kelce (conflict!), Jets DEF
  Team 6 (Ryan)       — Prescott, J.Taylor, Adams (conflict!), Dolphins DEF
  Team 7 (Travis)     — Travis Kelce TE, Herbert, Hill (conflict!), Browns DEF
  Team 8 (Jo)         — Mixon RB, Cousins, Higgins, Chiefs DEF
  Team 9 (Austin)     — Ekeler, T.Lawrence, Eagles DEF
  Team 10 (Wren)      — Goff, Harris, Bills DEF

Schedule: 14 regular season weeks (wks 1-14), 3 playoff weeks (wks 15-17)
  5 games/week regular season, 3/2/1 games in playoff weeks (quarterfinals/semis/final)
  Scores range 79–156 pts/week; all 17 weekly scores seeded per team

Season: 2024 · Projection sources: fantasypros (primary) · espn · yahoo
```

---

## Open Issues

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ BLOCKED: Yahoo Developer Portal                                                      │
│                                                                                      │
│ Status  : Application submitted. Approval required before Yahoo OAuth can be used.   │
│ Impact  : P2.3 (Yahoo OAuth) and P2.4 (real data ingestion) cannot start until      │
│           portal access is granted.                                                  │
│ Workaround: All development continues with mock_league.py NPC data. No code changes  │
│           needed — Yahoo connector will be a drop-in swap for mock_league.py.        │
│ Watch for: Approval email to fraser.d.coleman@gmail.com                              │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions (Do Not Forget)

```
┌──────────────────────────────────┬───────────────────────────────────────────────────┐
│ Decision                         │ Detail                                            │
├──────────────────────────────────┼───────────────────────────────────────────────────┤
│ No house — pure GM economy       │ Zero vig in FAAB mode. All money stays between    │
│                                  │ GMs. Odds set by Monte Carlo, not bookmaker.      │
│ Beef with Honor                  │ GM-to-GM challenges require explicit accept.      │
│                                  │ 24h window. Staleness warning if projections      │
│                                  │ shifted >10% since challenge was issued.          │
│ Prop = top player vs top player  │ App auto-selects highest projected starter from   │
│                                  │ each roster (slots 1–9). No manual player pick.  │
│                                  │ Settlement compares actual_points of both.        │
│ The Full Beef = best of 3        │ Leg 1: DEF actual pts · Leg 2: K actual pts ·    │
│                                  │ Leg 3: Bench aggregate actual pts. Win 2+ legs.  │
│                                  │ No ties possible. Both sides must accept as a     │
│                                  │ beef challenge if issued GM-to-GM.               │
│ Tuesday 12:01am UTC — auto       │ Everything runs in one pipeline: settle → rules   │
│                                  │ → wallets → wrap-up → rankings → emails.         │
│                                  │ Commissioner gets ASCII report. GMs get personal  │
│                                  │ email. No manual intervention needed.             │
│ Zero vig in FAAB mode            │ When FAAB is initialized, bet wallet funded by    │
│                                  │ FAAB dollars. Platform takes no cut.             │
│ Commissioner sets all parameters │ Buy-in amount, payout split, FAAB opening         │
│                                  │ balances, transfer rules, league rules — all      │
│                                  │ commissioner-controlled via API + frontend.       │
│ Joe is co-commissioner           │ Joe (co-commissioner) has identical permissions   │
│                                  │ to Kevin (commissioner). Both use role=commissioner│
│                                  │ in the users table. Both can trigger sync, edit  │
│                                  │ wrap-ups, settle bets, manage wallets.           │
│ Railway hosting                  │ FastAPI backend on Railway. React frontend on     │
│                                  │ Railway static hosting or Vercel. Auto-deploy     │
│                                  │ from GitHub push on main branch.                 │
│ React frontend                   │ GM-facing SPA. Yahoo link on league page.         │
│                                  │ Two role views: GM and Commissioner. All 9        │
│                                  │ sections of the GM dashboard.                    │
│ Status tag system                │ Contender · On the Bubble · Spoiler ·            │
│                                  │ The Beef Is Strong Within You (chaos tag).        │
│                                  │ Used in wrap-up My Edition + power rankings.     │
│ Roast Beef brand voice           │ Confident, funny, Jedi references. Template       │
│                                  │ fallback always uses this voice even without AI. │
│ AI chain: Ollama → Claude → tmpl │ Ollama at 10.0.0.11:11434, 5s timeout.           │
│                                  │ Anthropic claude-haiku-4-5-20251001 as fallback. │
│                                  │ Template always produces valid output.           │
│ SQLite → PostgreSQL in P2.2      │ SQLite for all P1/dev work. Railway deployment    │
│                                  │ swaps to PostgreSQL. ORM is already abstract;    │
│                                  │ only DB_URL changes (plus remove rename/copy     │
│                                  │ migration pattern — Postgres supports ALTER TABLE)│
│ Bet lifecycle: pending → settled │ Stake deducted at placement. Wallet credited      │
│                                  │ only on settlement win. Prevents double-spend.   │
│ Cross-matchup beefs              │ Any two GMs can beef any week. Settlement         │
│                                  │ compares each team's score from their own game.  │
│ Bench slots 10–15 = bench        │ Rosters are ordered by insertion slot.            │
│                                  │ Starters = slots 1–9. Bench = 10+. Static until  │
│                                  │ lineup manager is built in P2 or later.          │
└──────────────────────────────────┴───────────────────────────────────────────────────┘
```

---

## P2 Roadmap

### P2.1 — Frontend (React)  [ HIGHEST PRIORITY ]
```
Stack    : React 18 · TypeScript · Tailwind CSS · shadcn/ui components
           React Query for server state · React Router for navigation
           JWT stored in memory (not localStorage); refresh via cookie
           Vite dev server; Railway or Vercel for production hosting

Two Roles
  GM View          — all 9 sections below
  Commissioner View — all GM sections + commissioner dashboard

GM Dashboard — 9 Sections
  ┌────────────────────┬─────────────────────────────────────────────────────────────┐
  │ Section            │ What It Shows                                               │
  ├────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 1. My Dashboard    │ Wallet balance (bet + waiver split)                         │
  │                    │ This week's record + standings position                     │
  │                    │ Insight engine: "You're 3–2 against spread bets this season"│
  │                    │ Playoff probability % + magic number                        │
  │                    │ Path to playoffs: wins needed + who to root for             │
  ├────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 2. Betting Board   │ Live odds matrix — all this week's matchups                 │
  │                    │ Moneylines, spreads, totals, prop, Full Beef for each game  │
  │                    │ Tap a row → bet slip slides up → place bet                  │
  │                    │ Prop: shows auto-selected top starters for each side        │
  │                    │ Full Beef: shows all 3 legs (DEF/K/Bench) with projections  │
  │                    │ Odds refresh badge when projections update                  │
  ├────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 3. My Bets         │ Tabs: Active · Pending · Settled (this week + history)      │
  │                    │ Per-bet: type, description, stake, odds, to-win, status     │
  │                    │ Full Beef: leg-by-leg breakdown (DEF/K/Bench)               │
  │                    │ Real-time: "🔴 Losing DEF leg" during game day              │
  ├────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 4. League Pulse    │ Live activity feed (feed_events table)                      │
  │                    │ Challenge issued · challenge accepted · bet placed ·        │
  │                    │ bet settled · power rankings posted · wrap-up ready         │
  │                    │ Game day mode: live score tickers for active matchups       │
  ├────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 5. The Beeftable   │ All league bets this week — big table sortable by team,     │
  │                    │ type, amount. Who's got skin in the game. Total pot.        │
  │                    │ GM-to-GM challenge status (pending/accepted/settled)        │
  ├────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 6. Waiver Wire     │ Win-now pickups: top projected free agents by position      │
  │  Intel             │ Season-long pickups: breakout potential, target share        │
  │                    │ Competitor profiling: what each GM needs (bye weeks,        │
  │                    │ injury replacements, weak positions)                        │
  │                    │ Bid recommendations: suggested FAAB amount per player       │
  ├────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 7. Rivalry Center  │ Head-to-head history vs every other GM                     │
  │                    │ All-time record, avg margin, biggest win, worst loss        │
  │                    │ Revenge game badge (if you lost last matchup vs this opp.)  │
  │                    │ Upcoming matchup preview with odds                          │
  ├────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 8. Roast Beef      │ Warning shots: challenge a specific GM                      │
  │                    │ Trash talk feed: pre-game, post-game, beef acceptance msgs  │
  │                    │ Rivalry badges: Nemesis · The Beef Is Real · Rivalry Week   │
  │                    │ Quick-taunt button: pre-written Jedi-voice roasts           │
  ├────────────────────┼─────────────────────────────────────────────────────────────┤
  │ 9. Weekly Wrap-Up  │ My Edition: personal matchup recap, lineup grade,           │
  │  & Hooks           │   bet performance, status tag, playoff prob change          │
  │                    │ League Edition: all recaps, Beef of the Week, Roast Beef    │
  │                    │ Weekly hooks: 3 AI-generated hooks for the coming week      │
  │                    │   ("Mahomes Alone needs this matchup — Kevin's on life      │
  │                    │    support at 4–5 with 5 games left")                       │
  │                    │ Waiver report card: grades each GM's waiver moves this week │
  └────────────────────┴─────────────────────────────────────────────────────────────┘

Commissioner Dashboard (visible only when role=commissioner)
  ┌──────────────────────┬───────────────────────────────────────────────────────────┐
  │ Panel                │ Controls                                                  │
  ├──────────────────────┼───────────────────────────────────────────────────────────┤
  │ Rules Engine         │ Type a rule in plain English → AI preview → save + activate│
  │                      │ Active rules list with pause/delete/release-escrow        │
  ├──────────────────────┼───────────────────────────────────────────────────────────┤
  │ Wrap-Up Control      │ Generate → preview both editions → edit → send            │
  │                      │ View all historical wrap-ups                              │
  ├──────────────────────┼───────────────────────────────────────────────────────────┤
  │ Tuesday Sync         │ Trigger sync button (week selector, mock toggle)          │
  │                      │ Run history: each step with duration + status             │
  │                      │ Live run progress if currently running                    │
  ├──────────────────────┼───────────────────────────────────────────────────────────┤
  │ Settlement Approval  │ Settle week button → preview what will be settled →       │
  │                      │ confirm → SettlementReport                               │
  │                      │ Override single bet outcome (void / force win / force loss)│
  ├──────────────────────┼───────────────────────────────────────────────────────────┤
  │ GM Management        │ All GMs: balance, buy-in status, wallet freeze status     │
  │                      │ Promote/demote role. Freeze/unfreeze wallet. Manual top-up│
  ├──────────────────────┼───────────────────────────────────────────────────────────┤
  │ FAAB Config          │ Opening balances, transfer rules. Init season. Apply queue│
  └──────────────────────┴───────────────────────────────────────────────────────────┘

Implementation order within P2.1
  1. Auth flow (login, JWT storage, route guards for GM vs Commissioner)
  2. API client layer (React Query hooks for all 78 endpoints)
  3. My Dashboard — core health check for the data layer
  4. Betting Board — most complex; includes bet slip modal
  5. My Bets — read-heavy, fast to build
  6. League Pulse feed — real-time feel with polling or WebSocket
  7. Weekly Wrap-Up display — render existing DB content
  8. Commissioner panels — build alongside the GM views they mirror
  9. The Beeftable · Rivalry Center · Roast Beef · Waiver Wire Intel
```

### P2.2 — Railway Deployment
```
Steps
  1. Create Railway project. Add PostgreSQL plugin.
  2. Update DB_URL to read DATABASE_URL env-var (Railway injects it automatically).
  3. Replace SQLite-specific migrations (rename/copy/drop pattern) with standard
     ALTER TABLE statements for PostgreSQL.
  4. Add Procfile or railway.json: uvicorn api.main:app --host 0.0.0.0 --port $PORT
  5. Set env-vars on Railway:
       JWT_SECRET_KEY, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
       ANTHROPIC_API_KEY, OLLAMA_URL (if self-hosted is accessible from Railway),
       SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_FROM,
       COMMISSIONER_EMAIL, CURRENT_WEEK
  6. Connect GitHub repo → auto-deploy on push to main.
  7. Run migrations on deploy (or via Railway console one-time).
  8. Point React frontend at the Railway API URL.

SQLAlchemy note: ORM models are already DB-agnostic. Only change needed:
  schema.py:  DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")
  Remove SQLite PRAGMA FK hacks if any remain in migrations.
  PostgreSQL supports standard ALTER TABLE for constraint changes — no more
  rename/copy/drop pattern needed for future migrations.
```

### P2.3 — Yahoo OAuth  [ BLOCKED — portal pending ]
```
What it enables
  • Real GM login via Sign In With Yahoo instead of email/password
  • Real league data (teams, rosters, scores, projections) replaces mock_league.py
  • Yahoo link on the league home page

Implementation plan (when portal is approved)
  1. Register app on Yahoo Developer Portal → get client_id + client_secret
  2. Add Yahoo OAuth2 PKCE flow to auth/jwt_auth.py
     GET /auth/yahoo/login → redirect to Yahoo
     GET /auth/yahoo/callback → exchange code → fetch Yahoo user profile
     Match Yahoo email to Team.email → issue our JWT
  3. Create connectors/yahoo_connector.py
     fetch_league(league_key) → League, Teams, Rosters
     fetch_scores(week) → Matchup actual scores
     fetch_projections(week) → Projection rows (FantasyPros as backup)
     fetch_faab_balances() → sync waiver_balance per team
  4. Replace mock_league.py seed calls with yahoo_connector in schema.py or
     a new db/sync_yahoo.py migration-style script
  5. Commissioner sets league_key in /payments/setup-treasury or new endpoint

No backend changes needed before portal approval — everything is designed
to accept real data through the same DB tables mock data uses.
```

### P2.4 — Real Data Ingestion
```
Depends on: P2.3 (Yahoo OAuth) + FantasyPros API access

  • Scheduled daily projection refresh (FantasyPros scraper or Yahoo feed)
  • Injury status updates tied to refresh cycle
  • Actual score ingestion post-game (Saturday night + Monday night)
  • Trigger settle_week() automatically when all scores are posted
  • FantasyPros injury tags → injury_status column (OUT/IR/DOUBTFUL/QUESTIONABLE)
  • projections.actual_points → populated by same job post-game

Files needed (new):
  data/ingestion/fantasypros_scraper.py
  data/ingestion/injury_feed.py
  data/ingestion/yahoo_scores.py
  notifications/tuesday_sync.py → add step 0: score_ingestion

No schema changes needed — injury_status column exists since migration v2,
actual_points exists since original schema.py.
```

---

## Environment Variables Reference

```
┌──────────────────────────┬──────────────────────────────────────────────────────────┐
│ Variable                 │ Purpose                                                  │
├──────────────────────────┼──────────────────────────────────────────────────────────┤
│ JWT_SECRET_KEY           │ HS256 signing key — CHANGE IN PROD                      │
│ STRIPE_SECRET_KEY        │ Stripe live/test key — mock mode if unset               │
│ STRIPE_WEBHOOK_SECRET    │ Stripe webhook signature verification                   │
│ ANTHROPIC_API_KEY        │ Claude fallback in AI writing chain                     │
│ OLLAMA_URL               │ Ollama server URL (default: http://10.0.0.11:11434)     │
│ OLLAMA_MODEL             │ Model override (default: qwen2.5:7b)                    │
│ SMTP_HOST                │ Email server — mock mode if unset                       │
│ SMTP_PORT                │ Email port (typically 587)                              │
│ SMTP_USER                │ SMTP auth username                                      │
│ SMTP_PASS                │ SMTP auth password                                      │
│ EMAIL_FROM               │ From address for all outgoing emails                    │
│ COMMISSIONER_EMAIL       │ Overrides DB email for commissioner contact             │
│ CURRENT_WEEK             │ Force a specific week number for Tuesday sync            │
│ DATABASE_URL             │ PostgreSQL URL (Railway injects; SQLite fallback in dev) │
└──────────────────────────┴──────────────────────────────────────────────────────────┘
```

---

## Quick Start (Dev)

```bash
# Full reset + seed NPC data
python db/schema.py

# Run all migrations (cumulative — safe on fresh DB)
python db/migrate_scoring.py
python db/migrate_v2.py
python db/migrate_auth.py
python db/migrate_payments.py
python db/migrate_faab.py
python db/migrate_rules.py
python db/migrate_sync.py
python db/migrate_wrap.py
python db/migrate_rankings.py
python db/migrate_full_beef.py

# Start API
uvicorn api.main:app --port 8007 --reload

# Trigger full Tuesday pipeline (week 5, mock mode)
python notifications/tuesday_sync.py --league 1 --week 5

# Smoke test bet engine
python betting/bet_engine.py 1 1 3
```
