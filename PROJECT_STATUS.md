# Fantasy Beefs — Project Status

> Platform: 10-team fantasy football league with GM-to-GM betting, Monte Carlo odds engine,
> wallet management, and settlement automation.
> Stack: Python 3.12 · SQLAlchemy 2.0 · SQLite · FastAPI · NumPy · python-jose · passlib[bcrypt] · stripe

---

## Repository Layout

```
C:\Users\frase\PycharmProjects\
│
├── db/
│   ├── schema.py            ORM models, engine, seeder (seed_from_mock) — includes User model
│   ├── deps.py              Shared FastAPI get_db() dependency (avoids circular imports)
│   ├── migrate_scoring.py   Migration v1 — league_scoring table, projection_source column
│   ├── migrate_v2.py        Migration v2 — bench_battle, injury_status, staleness_warning
│   ├── migrate_auth.py      Migration v3 — users table + seed one account per team
│   ├── migrate_payments.py  Migration v4 — Stripe payment tables + user columns
│   ├── migrate_faab.py      Migration v5 — FAAB wallet tables
│   ├── migrate_rules.py     Migration v6 — Commissioner rules + escrow tables
│   ├── migrate_sync.py      Migration v7 — tuesday_sync_runs table
│   └── fantasy.db           SQLite database (generated)
│
├── auth/
│   └── jwt_auth.py          JWT auth: tokens, password hashing, FastAPI dependencies,
│                              register_user, authenticate_user, seed_users
│
├── mock_league.py           10-team mock data: rosters (15/team), 17-week schedule, scores
│
├── odds/
│   └── monte_carlo.py       Simulation engine: odds, bench projections, scoring adjustments
│
├── betting/
│   ├── bet_engine.py        Six bet types placed against scheduled matchups
│   └── settlement_engine.py Weekly batch settlement — scores all pending bets
│
├── wallet/
│   └── wallet_manager.py    Deposit / withdraw / balance / tx history; bet-sizing rules
│
├── beefs/
│   └── beef_engine.py       GM-to-GM challenge system — any two teams, any week
│
├── feed/
│   └── league_feed.py       Activity feed — challenge + settlement events with trash talk
│
├── payments/
│   └── stripe_connect.py    Stripe Connect: treasury, buy-ins, payouts, audit log,
│                              buy-in gate dependency
│
└── api/
    └── main.py              FastAPI app (port 8007)

├── wallet/
│   └── faab_wallet.py       FAAB: split bet+waiver wallets, top-ups, transfers,
│                              freeze/unfreeze, Tuesday queue, bet-funded gate
│
├── admin/
│   └── commissioner_rules.py Commissioner Rules Engine: AI-parsed natural language rules,
│                              escrow accounts, weekly + end-of-season execution, audit trail
│
├── notifications/
│   └── tuesday_sync.py      Tuesday Automation: 9-step weekly job, APScheduler, step isolation,
│                              ASCII commissioner report, per-GM email, mock mode, run history
│
├── reports/
│   ├── __init__.py          Package init
│   ├── weekly_wrap.py       AI Weekly Wrap-Up: matchup recaps, Beef of the Week, Roast Beef,
│   │                         standings snapshot, per-GM personalized edition, status tags,
│   │                         lineup grade, playoff probability, Ollama → Anthropic → template
│   │                         fallback chain, feed posting, email delivery, DB archive
│   └── power_rankings.py    Power Rankings: on-field + betting + waiver composite GM Rating,
│                              rank_change week-over-week, status tags, feed posting, season arc
│
└── db/
    ├── migrate_wrap.py      Migration v8 — weekly_wrap_ups + wrap_up_gm_editions tables
    └── migrate_rankings.py  Migration v9 — power_rankings table
```

---

## Database Tables

```
┌─────────────────────┬──────────────────────────────────────────────────────────────────┐
│ Table               │ Purpose & Key Columns                                            │
├─────────────────────┼──────────────────────────────────────────────────────────────────┤
│ leagues             │ id, season, name, projection_source                              │
│ league_scoring      │ league_id (1:1), scoring_type, rec_points, pass_td_points,      │
│                     │   rush_td_points, rec_td_points, bonus_100yd_rush/rec            │
│ teams               │ id, league_id, team_name, owner, email                          │
│ players             │ id, name, position (QB/RB/WR/TE/FLEX/K/DEF)                    │
│ rosters             │ team_id + player_id (unique); slots 1-9 = starters, 10+ = bench │
│ matchups            │ id, league_id, week, home_team_id, away_team_id,                │
│                     │   home_score, away_score, winner_team_id                         │
│ wallets             │ id, team_id (1:1), balance (default $1,000)                     │
│ bets                │ id, matchup_id, wallet_id, picked_team_id, player_id,           │
│                     │   bet_type*, line, side, amount, odds, status*, placed_at,       │
│                     │   settled_at, beef_challenge_id                                  │
│ transactions        │ id, wallet_id, amount (+credit / -debit), type*, bet_id         │
│ projections         │ id, player_id, week, season, source*, projected_points,         │
│                     │   actual_points, injury_status†                                  │
│ beef_challenges     │ id, challenger/challenged team_id, week, bet_type*, amount,     │
│                     │   line, side, player_id, challenger/challenged_odds + moneyline, │
│                     │   status*, expires_at, projection_snapshot, staleness_warning†   │
│ feed_events         │ id, league_id, week, event_type, actor_team_id, target_team_id, │
│                     │   challenge_id, bet_id, headline, trash_talk, created_at         │
│                     │   INDEX on (league_id, created_at)                               │
│ users               │ id, email (unique), hashed_password, team_id (unique FK),       │
│                     │   role* (gm|commissioner), is_active, buy_in_paid,              │
│                     │   stripe_account_id, created_at, last_login_at                  │
│ league_treasury     │ id, league_id (1:1), buy_in_amount_cents, payout_split_json,    │
│                     │   total_collected_cents, total_paid_out_cents, season_payout_done│
│ buy_in_records      │ id, league_id, team_id (1:1/season), user_id, amount_cents,     │
│                     │   status* (pending|paid|refunded), stripe_payment_link_id/url,  │
│                     │   stripe_session_id, stripe_payment_intent_id, paid_at          │
│ payout_records      │ id, league_id, team_id, user_id, place, amount_cents, pct,      │
│                     │   status* (pending|sent|failed), stripe_transfer_id,            │
│                     │   stripe_connected_account, sent_at                             │
│ stripe_audit_log    │ id, league_id, team_id, event_type, stripe_object, amount_cents,│
│                     │   description, raw_response, performed_by_user_id, created_at   │
│                     │   INDEX on (league_id, created_at)                              │
│ faab_config         │ id, league_id (1:1), opening_bet, opening_waiver,               │
│                     │   allow_bet_to_waiver, allow_waiver_to_bet, season_initialized  │
│ faab_wallets        │ id, team_id (1:1), league_id, waiver_balance,                  │
│                     │   pending_waiver_topup (queued for Tuesday), bet_frozen          │
│ faab_transactions   │ id, league_id, team_id, type*, amount, wallet_from, wallet_to, │
│                     │   status*, note, stripe_link_id/url, apply_on, applied_at       │
│                     │   INDEX on (team_id, created_at)                                │
│                     │   * types: opening_credit, topup_bet, topup_waiver,             │
│                     │     transfer_bet_to_waiver, transfer_waiver_to_bet,             │
│                     │     waiver_bid, waiver_refund, funding_alert                    │
├─────────────────────┼──────────────────────────────────────────────────────────────────┤
│ commissioner_rules  │ id, league_id, raw_text, rule_type* (weekly|end_of_season),     │
│                     │   effect_type* (obligation|payout),                              │
│                     │   target* (biggest_loss_margin|missed_lineup|points_leader|      │
│                     │           commissioner_manual),                                  │
│                     │   amount, has_escrow, escrow_release_trigger, escrow_release_    │
│                     │   target, ai_interpretation, ai_model_used, status*             │
│                     │   (draft|active|paused|completed), week_start, week_end         │
│                     │   INDEX on (league_id, status)                                  │
│ escrow_accounts     │ id, league_id, rule_id (1:1), name, balance, status*           │
│                     │   (open|released|refunded), release_trigger* (end_of_season|    │
│                     │   manual), release_team_id, released_at                         │
│ escrow_transactions │ id, escrow_id, league_id, team_id, direction* (in|out),        │
│                     │   amount, description, created_at                               │
│                     │   INDEX on (escrow_id, created_at)                              │
│ rule_executions     │ id, rule_id, league_id, week, team_id, effect_type*,           │
│                     │   amount, description, status* (pending|collected|             │
│                     │   held_in_escrow|paid_out|waived|failed),                       │
│                     │   escrow_id, executed_at, settled_at                            │
│                     │   INDEX on (rule_id, week)                                      │
│ rule_audit_log      │ id, rule_id, league_id, performed_by_user_id, event_type,      │
│                     │   description, ai_model, ai_latency_ms, raw_data, created_at    │
│                     │   INDEX on (league_id, created_at)                              │
├─────────────────────┼──────────────────────────────────────────────────────────────────┤
│ tuesday_sync_runs   │ id, run_id (unique UUID hex), league_id, week, status*          │
│                     │   (running|completed|completed_with_errors|failed), mock_mode,  │
│                     │   steps_json (JSON array of StepResult), error_count,           │
│                     │   emails_sent, started_at, finished_at                          │
│                     │   INDEX on (league_id, started_at)                              │
├─────────────────────┼──────────────────────────────────────────────────────────────────┤
│ weekly_wrap_ups     │ id, run_id (unique UUID hex), league_id, week,                  │
│                     │   status* (draft|ready|sent), league_body (TEXT),               │
│                     │   roast_beef (TEXT), ai_model_used, ai_latency_ms,              │
│                     │   commissioner_edited (0/1), created_at, updated_at, sent_at    │
│                     │   INDEX on (league_id, week)                                    │
│ wrap_up_gm_editions │ id, wrap_up_id (FK → weekly_wrap_ups), league_id, team_id, week,│
│                     │   body (TEXT), status_tag* (contender|bubble|spoiler|chaos),    │
│                     │   playoff_prob_change (Float), sent (0/1), sent_at, created_at  │
│                     │   INDEX on (wrap_up_id, team_id)                                │
├─────────────────────┼──────────────────────────────────────────────────────────────────┤
│ power_rankings      │ id, league_id, week, team_id (UNIQUE per league+week+team),     │
│                     │   on_field_rank, on_field_score (0–1),                          │
│                     │   wins, losses, points_for, points_against, sos,                │
│                     │   betting_rank, betting_score (0–1),                            │
│                     │   bet_wins, bet_losses, roi, best_win_amount,                   │
│                     │   worst_loss_amount, bet_streak (+n=hot / -n=cold),             │
│                     │   waiver_rank, waiver_score (0–1),                              │
│                     │   waiver_dollars_spent, waiver_pts_added, pts_per_dollar,       │
│                     │   composite_rank, composite_score (0–1),                        │
│                     │   rank_change (+n=up / -n=down vs prev week; NULL first week), │
│                     │   status_tag* (contender|bubble|spoiler|chaos), created_at      │
│                     │   INDEX on (league_id, week)                                    │
└─────────────────────┴──────────────────────────────────────────────────────────────────┘

* CHECK constraint enforced   † Added in migration v2
```

**Seeded data** — `python db/schema.py` resets and seeds:
- 1 league · 10 teams · 150 unique players · 170 roster slots
- 85 matchups (17 weeks × 5 games) with actual scores
- 7,650 projections (150 players × 17 weeks × 3 sources: fantasypros · espn · yahoo)
- 10 wallets starting at $1,000 each

---

## Module Reference

### `auth/jwt_auth.py` — JWT Authentication  ✅ P1.1

```
Token: HS256 JWT · 8h expiry · SECRET_KEY from JWT_SECRET_KEY env-var
Claims: sub (user_id), email, team_id, role, exp

┌──────────────────────────────────────┬────────────────────────────────────────────────┐
│ Export                               │ Description                                    │
├──────────────────────────────────────┼────────────────────────────────────────────────┤
│ hash_password(plain)                 │ bcrypt hash                                    │
│ verify_password(plain, hashed)       │ constant-time compare                          │
│ create_access_token(user)            │ sign JWT with claims                           │
│ get_current_user(token, db)          │ FastAPI Depends — decodes token → User row     │
│ get_current_gm(user)                 │ Depends wrapper — any authenticated user       │
│ require_commissioner(user)           │ Depends wrapper — role=commissioner only       │
│ assert_own_team(team_id, user)       │ raises 403 if user.team_id != team_id          │
│                                      │   (commissioners bypass)                       │
│ assert_own_wallet(wallet_id, user, db│ raises 403 if wallet doesn't belong to team   │
│ register_user(email, pwd, db)        │ email must match existing team; role=gm        │
│ authenticate_user(email, pwd, db)    │ verifies password, updates last_login_at       │
│ promote_user(email, role, db)        │ gm ↔ commissioner; commissioner-only endpoint │
│ seed_users(db)                       │ creates one User per team; team-1 = commissioner│
└──────────────────────────────────────┴────────────────────────────────────────────────┘

Guarded endpoints (require Bearer token)
  POST /bets/*         — get_current_gm + assert_own_wallet
  POST /wallet/deposit │
  POST /wallet/withdraw│ — get_current_gm + assert_own_wallet
  POST /league/{league_id}/settle/{week}  — commissioner of THAT league
       (S8-P2: was a state-changing GET; S8-P2R: league is no longer hard-coded)
  POST /beef/challenge — get_current_gm + assert_own_team(challenger)
  POST /beef/respond   — get_current_gm + assert_own_team(challenged)
  GET  /beef/pending/* — get_current_gm + assert_own_team
  GET  /auth/me        — get_current_gm
  POST /auth/promote   — require_commissioner

Open endpoints (no auth): all GET /league/*, /projections/*, /odds/*, /feed/*, /health
```

### `odds/monte_carlo.py` — Simulation Engine

```
┌─────────────────────────────────┬────────────────────────────────────────────────────┐
│ Export                          │ Description                                        │
├─────────────────────────────────┼────────────────────────────────────────────────────┤
│ run(matchup_id, home, away,     │ Full simulation → OddsResult with moneylines,      │
│   week, db, scoring)            │ projected score distributions, starter lines       │
│ simulate_scores(h, a, week, db, │ (home_scores, away_scores) ndarrays for bet_engine │
│   scoring)                      │                                                    │
│ simulate_bench_scores(h, a,     │ (home_bench, away_bench) ndarrays — bench_battle   │
│   week, db, scoring)            │ uses injury-adjusted projections                   │
│ simulate_player_scores(pts,     │ Single-player score array — prop bets              │
│   player_id, week)              │                                                    │
│ bench_players(team, week, db,   │ list[BenchPlayerLine] — injury_status + effective  │
│   scoring)                      │ pts after multiplier + scoring adjustment          │
│ load_scoring_from_db(league_id) │ → ScoringSettings from league_scoring table        │
└─────────────────────────────────┴────────────────────────────────────────────────────┘

Constants: N_SIMS=10,000 · STD_PCT=0.20 · N_START=9 · MIN_HEALTHY_BENCH=6
Injury multipliers: out/ir → 0.0 × · doubtful → 0.25 × · questionable → 0.60 ×
Scoring presets: STANDARD (0 rec) · HALF_PPR (0.5 rec) · PPR (1.0 rec)
Scoring adjustment: converts FantasyPros PPR baseline using position-averaged
  reception counts, pass TD averages, rush/rec TD averages per position
```

### `betting/bet_engine.py` — Scheduled Matchup Bets

```
┌──────────────────────────────────────────────────┬───────────────────────────────────┐
│ Function                                         │ What it does                      │
├──────────────────────────────────────────────────┼───────────────────────────────────┤
│ place_straight_bet(matchup_id, wallet_id,        │ Team wins outright                │
│   picked_team_id, amount, week, db)              │                                   │
│ place_spread_bet(matchup_id, wallet_id,          │ Team covers a point spread        │
│   picked_team_id, spread, amount, week, db)      │                                   │
│ place_over_under(matchup_id, wallet_id,          │ Combined score over/under a line  │
│   total_line, pick, amount, week, db)            │                                   │
│ place_prop_bet(matchup_id, wallet_id,            │ Top projected starter vs top      │
│   picked_team_id, amount, week, db)              │ projected starter — pick whose    │
│                                                  │ player scores more                │
│ place_full_beef(matchup_id, wallet_id,           │ Best-of-3: DEF vs DEF, K vs K,   │
│   picked_team_id, amount, week, db)              │ Bench vs Bench — win 2+ legs      │
└──────────────────────────────────────────────────┴───────────────────────────────────┘

All functions: simulate odds → validate amount → write Bet(status=pending)
  + debit Transaction → return BetResult (full_beef includes legs=[...]).
Bet sizing enforced via wallet_manager.validate_bet_amount (min $5, max 20% balance).

Prop bet DB storage
  player_id = home team's top projected starter ID
  side      = str(away team's top projected starter ID)
  picked_team_id = bettor's choice; settlement compares actual_points

Full Beef DB storage
  picked_team_id = bettor's choice (who wins 2+ legs)
  No player_id / side needed — settlement resolves from matchup + Roster + Projection
```

### `betting/settlement_engine.py` — Weekly Settlement

```
settle_week(week, db) → SettlementReport

Outcome rules
  straight   : won if picked_team_id == matchup.winner_team_id
  spread     : won if picked team's actual margin > line
  over_under : won if (home+away) actual > line (over) or < line (under)
  prop       : won if picked team's top starter actual_points > opponent top starter actual_points
  bench_battle (beef): won if picked team's bench actual total > opponent bench total
  full_beef  : won if picked team wins 2+ of 3 legs (DEF actual, K actual, Bench actual)

On win: wallet credited payout = stake × odds_dec; payout Transaction written.
On loss: no wallet change (stake already deducted at placement).
Returns SettlementReport with per-bet BetSettlement rows + per-wallet WalletMovement rows.
```

### `wallet/wallet_manager.py` — Wallet Operations

```
┌───────────────────────────────────────┬───────────────────────────────────────────────┐
│ Function                              │ Notes                                         │
├───────────────────────────────────────┼───────────────────────────────────────────────┤
│ deposit(wallet_id, amount, db)        │ Max single deposit $1,000,000                 │
│ withdraw(wallet_id, amount, db)       │ Blocked if withdrawal > (balance − exposure)  │
│ balance_check(wallet_id, db)          │ Read-only snapshot                            │
│ balance_check_by_team(team_id, db)    │ Same, keyed by team                           │
│ transaction_history(wallet_id, db,    │ Paginated; joins bet metadata                 │
│   limit, offset)                      │                                               │
│ validate_bet_amount(amount, balance)  │ Raises ValueError — imported by bet_engine    │
└───────────────────────────────────────┴───────────────────────────────────────────────┘

WalletState fields: balance · max_single_bet · open_bets · pending_exposure
  · total_deposited · total_withdrawn · total_wagered · total_payout · net_pnl
```

### `beefs/beef_engine.py` — GM-to-GM Challenges

```
Flow: issue_challenge → 24h pending window → respond_to_challenge (accept/decline)

┌──────────────────────────────────────────────────────┬─────────────────────────────────┐
│ Function                                             │ Notes                           │
├──────────────────────────────────────────────────────┼─────────────────────────────────┤
│ issue_challenge(ch_team, cd_team, week, bet_type,    │ Computes odds, snapshots        │
│   amount, db, line, side, player_id)                 │ projections, writes             │
│                                                      │ BeefChallenge(pending)          │
│ respond_to_challenge(challenge_id, accept, db)       │ On accept: staleness check,     │
│                                                      │ place two Bets atomically,      │
│                                                      │ debit both wallets              │
│ get_pending_challenges(team_id, db)                  │ Returns sent + received;        │
│                                                      │ auto-expires stale ones         │
└──────────────────────────────────────────────────────┴─────────────────────────────────┘

Supported bet_types: straight · spread · over_under · prop · bench_battle
No shared-matchup required — any two GMs, any week.
Settlement compares each team's actual weekly score from their own game.

bench_battle specifics
  • Validation: both teams must have ≥ 6 non-Out/IR bench players
  • Odds: simulate_bench_scores on each team's 6 bench slots
  • Settlement: sum actual_points for bench slots from Projection table

Staleness warning
  • At issue_challenge: snapshot projected_points for all relevant players → JSON
  • At respond (accept): re-query projections; if any player shifted > 10%,
    staleness_warning=True is set on BeefChallenge and returned in AcceptResult
  • Enables UI warning: "Odds may be stale — projections changed since challenge was issued"
```

---

## API Endpoints

Server runs on port **8007** — `uvicorn api.main_rc2:app --port 8007`

```
┌──────────┬───────────────────────────────┬─────────────────────────────────────────────┐
│ Method   │ Path                          │ Description                             Auth │
├──────────┼───────────────────────────────┼─────────────────────────────────────────────┤
│ POST     │ /auth/register                │ Create account (email must match team)  open │
│ POST     │ /auth/login                   │ OAuth2 form → JWT access_token          open │
│ GET      │ /auth/me                      │ Caller's user info                      gm   │
│ POST     │ /auth/promote                 │ Set a user's role (gm ↔ commissioner)   comm │
├──────────┼───────────────────────────────┼─────────────────────────────────────────────┤
│ GET      │ /health                       │ DB connection check, league info        open │
├──────────┼───────────────────────────────┼─────────────────────────────────────────────┤
│ GET      │ /league/standings             │ Win/loss/PF/PA sorted standings             │
│ GET      │ /league/matchups/{week}       │ All matchups for a week with scores         │
│ GET      │ /league/roster/{team_id}      │ Full 15-player roster + wallet balance      │
├──────────┼───────────────────────────────┼─────────────────────────────────────────────┤
│ GET      │ /projections/{week}           │ Player projections; ?source= ?position=     │
│ GET      │ /odds/{matchup_id}/{week}     │ Monte Carlo odds: moneylines, score distrs, │
│          │                               │ starter lines (PPR; scoring_type in resp)   │
├──────────┼───────────────────────────────┼─────────────────────────────────────────────┤
│ POST     │ /bets/straight                │ Pick a team to win outright                 │
│ POST     │ /bets/spread                  │ Team covers a spread                        │
│ POST     │ /bets/over_under              │ Combined score over/under a total           │
│ POST     │ /bets/prop                    │ Top starter vs top starter head-to-head     │
│ POST     │ /bets/full_beef               │ Best-of-3: DEF/K/Bench — win 2+ legs        │
│ GET      │ /bets/{matchup_id}            │ All bets placed on a matchup                │
│ POST     │ /league/{id}/settle/{week}   │ Settle a week for one named league   L-comm │
├──────────┼───────────────────────────────┼─────────────────────────────────────────────┤
│ POST     │ /wallet/deposit               │ Credit a wallet                         gm   │
│ POST     │ /wallet/withdraw              │ Debit (blocked if pending exposure)     gm   │
│ GET      │ /wallet/{team_id}             │ Balance + open bets + recent transactions open│
│ GET      │ /wallet/{team_id}/history     │ Paginated tx history with bet metadata  open │
├──────────┼───────────────────────────────┼─────────────────────────────────────────────┤
│ POST     │ /beef/challenge               │ Issue a GM-to-GM challenge              gm†  │
│ POST     │ /beef/respond                 │ Accept or decline; returns staleness_warning gm│
│ GET      │ /beef/pending/{team_id}       │ Sent + received pending challenges      gm   │
├──────────┼───────────────────────────────┼─────────────────────────────────────────────┤
│ POST     │ /payments/setup-treasury      │ Set buy-in amount + payout split        comm │
│ GET      │ /payments/treasury/{id}       │ Treasury state (pot, split, progress)   open │
│ GET      │ /payments/buyin-status/{id}   │ All teams' buy-in status                gm   │
│ POST     │ /payments/buyin-link/{id}     │ Generate Stripe Payment Link for buy-in gm   │
│ POST     │ /payments/buyin-confirm       │ Manual buy-in confirmation              comm │
│ GET      │ /payments/connect-link/{id}   │ Stripe Connect onboarding URL (payouts) gm   │
│ GET      │ /payments/payout-preview/{id} │ Preview season payout amounts           comm │
│ POST     │ /payments/payout-execute      │ Execute season payouts via Stripe       comm │
│ GET      │ /payments/audit-log/{id}      │ Full Stripe event audit trail           comm │
│ POST     │ /payments/webhook             │ Stripe webhook receiver                 open │
├──────────┼───────────────────────────────┼─────────────────────────────────────────────┤
│ POST     │ /faab/setup                   │ Configure opening balances + transfer rules comm│
│ GET      │ /faab/config/{league_id}      │ View FAAB configuration                 gm   │
│ POST     │ /faab/init-season             │ Credit opening balances to all teams    comm │
│ GET      │ /faab/wallet/{team_id}        │ Combined bet+waiver wallet state        gm   │
│ GET      │ /faab/league/{league_id}      │ All teams' FAAB wallet states           gm   │
│ POST     │ /faab/topup-bet               │ Top up bet wallet via Stripe            gm   │
│ POST     │ /faab/topup-waiver            │ Queue waiver top-up for Tuesday         gm   │
│ POST     │ /faab/topup-confirm           │ Manually confirm pending top-up         comm │
│ POST     │ /faab/apply-pending           │ Apply due waiver top-ups (Tuesday job)  comm │
│ POST     │ /faab/transfer                │ Move funds between bet/waiver wallets   gm   │
│ GET      │ /faab/transactions/{team_id}  │ FAAB transaction history                gm   │
│ POST     │ /faab/freeze                  │ Manually freeze/unfreeze bet wallet     comm │
├──────────┼───────────────────────────────┼─────────────────────────────────────────────┤
│ POST     │ /rules/parse                  │ AI-parse raw text → preview (no save)   comm │
│ POST     │ /rules/create                 │ Save parsed spec as draft rule          comm │
│ GET      │ /rules/league/{league_id}     │ List rules (?status= filter)            comm │
│ GET      │ /rules/{rule_id}              │ Get specific rule                       comm │
│ POST     │ /rules/activate/{rule_id}     │ Draft → active; creates escrow if needed comm│
│ POST     │ /rules/pause/{rule_id}        │ Pause active rule                       comm │
│ DELETE   │ /rules/draft/{rule_id}        │ Delete a draft rule                     comm │
│ POST     │ /rules/execute-weekly         │ Run all active weekly rules for a week  comm │
│ POST     │ /rules/execute-end-of-season  │ Run EOS rules + release escrow accounts comm │
│ GET      │ /rules/executions/{league_id} │ Paginated execution history             comm │
│ POST     │ /rules/release-escrow/{id}    │ Manually release escrow to a team       comm │
│ GET      │ /rules/audit/{league_id}      │ Full rule audit trail                   comm │
├──────────┼───────────────────────────────┼─────────────────────────────────────────────┤
│ POST     │ /admin/tuesday-sync           │ Trigger Tuesday sync (mock_mode=T default)  comm│
│ GET      │ /admin/tuesday-sync/runs/{id} │ Run history for a league                comm │
│ GET      │ /admin/tuesday-sync/run/{id}  │ Full detail for a single run            comm │
├──────────┼───────────────────────────────┼─────────────────────────────────────────────┤
│ POST     │ /reports/wrap-up/generate     │ Generate weekly wrap-up (triggers AI)   comm │
│ GET      │ /reports/wrap-up/{id}/{week}  │ Get wrap-up for a league+week           comm │
│ GET      │ /reports/wrap-up/{id}         │ List wrap-ups for a league (?limit=)    comm │
│ PUT      │ /reports/wrap-up/{wrap_up_id} │ Edit league_body or roast_beef section  comm │
│ POST     │ /reports/wrap-up/{id}/send    │ Re-send wrap-up emails                  comm │
│ GET      │ /reports/wrap-up/{id}/editions│ Per-GM edition detail                   comm │
├──────────┼───────────────────────────────┼─────────────────────────────────────────────┤
│ POST     │ /reports/rankings/compute     │ Compute power rankings + post to feed   comm │
│ GET      │ /reports/rankings/{id}/{week} │ All teams' rankings for a week          open │
│ GET      │ /reports/rankings/{id}/arc    │ All weeks' rankings — full season arc   open │
│ GET      │ /reports/rankings/{id}/team/{id}│ One team's ranking history            open │
└──────────┴───────────────────────────────┴─────────────────────────────────────────────┘

Total: **78 routes** (including /docs, /redoc, /openapi.json)

† /bets/* and /beef/challenge also require: buy-in paid + bet wallet not frozen
  HTTP 402 if treasury configured (buy_in_amount_cents > 0) and GM hasn't paid,
  OR if FAAB system initialized and bet wallet balance <= $0 (frozen).

Auth column: open = no token required · gm = any authenticated user · comm = commissioner only
```

---

## Key Design Decisions

```
┌────────────────────────────────┬──────────────────────────────────────────────────────┐
│ Decision                       │ Rationale                                            │
├────────────────────────────────┼──────────────────────────────────────────────────────┤
│ Pending bet lifecycle          │ Stake deducted at placement; wallet credited only on  │
│                                │ settlement win. Prevents double-spend during week.    │
│ Deferred settlement            │ settle_week(week) runs after real games complete.     │
│                                │ Enables betting all week on actual upcoming matchups. │
│ Cross-matchup beefs            │ Challenger vs challenged compares each team's score   │
│                                │ from their own scheduled game — no shared matchup     │
│                                │ needed. Any two GMs can beef any week.               │
│ FantasyPros PPR baseline       │ Projections scraped with scoring=PPR. All Monte Carlo │
│                                │ simulations convert to target scoring via             │
│                                │ _adjust_for_scoring() using position-avg stats.       │
│ Bench battle min-healthy rule  │ Requires ≥ 6 non-Out/IR bench players per team.      │
│                                │ Prevents gaming with a squad of injured benchers.    │
│ Beef bypass of 20% cap         │ Both GMs agreed to amount at challenge time.          │
│                                │ Only balance ≥ amount is checked (no pct cap).       │
│ SQLite + no FK enforcement     │ Allows circular FK (bets ↔ beef_challenges) without  │
│                                │ constraint violations. Migrations use rename/copy     │
│                                │ pattern to update CHECK constraints.                 │
└────────────────────────────────┴──────────────────────────────────────────────────────┘
```

---

## Migration History

```
┌───────────┬────────────────────────┬──────────────────────────────────────────────────┐
│ Script    │ Safe to re-run?        │ What it does                                     │
├───────────┼────────────────────────┼──────────────────────────────────────────────────┤
│ schema.py │ No (drops DB)          │ Full reset — drop_all, create_all, seed_from_mock │
│ migrate_  │ Yes (idempotent)       │ Add leagues.projection_source, create             │
│ scoring.py│                        │ league_scoring table, seed half_ppr row          │
│ migrate_  │ Yes (idempotent cols;  │ Add projections.injury_status; add               │
│ v2.py     │ recreates bets/beefs)  │ beef_challenges.projection_snapshot +            │
│           │                        │ staleness_warning; update ck_bet_type +          │
│           │                        │ ck_beef_bet_type to include bench_battle         │
│ migrate_  │ Yes (additive create;  │ Create users table; seed one User per team;      │
│ auth.py   │ skips existing emails) │ team-1 owner = commissioner, all others = gm    │
│ migrate_  │ Yes (create_all +      │ Create league_treasury, buy_in_records,          │
│ payments  │ idempotent ALTER)      │ payout_records, stripe_audit_log tables;         │
│ .py       │                        │ add users.buy_in_paid + stripe_account_id        │
│ migrate_  │ Yes (create_all only;  │ Create faab_config, faab_wallets,                │
│ faab.py   │ no existing changes)   │ faab_transactions tables                         │
│ migrate_  │ Yes (create_all only;  │ Create commissioner_rules, escrow_accounts,       │
│ rules.py  │ no existing changes)   │ escrow_transactions, rule_executions,            │
│           │                        │ rule_audit_log tables                            │
│ migrate_  │ Yes (create_all only;  │ Create tuesday_sync_runs table                   │
│ sync.py   │ no existing changes)   │                                                  │
│ migrate_  │ Yes (create_all only;  │ Create weekly_wrap_ups, wrap_up_gm_editions      │
│ wrap.py   │ no existing changes)   │ tables                                           │
│ migrate_  │ Yes (create_all only;  │ Create power_rankings table                      │
│ rankings  │ no existing changes)   │                                                  │
│ .py       │                        │                                                  │
│ migrate_  │ No (rename/copy pattern│ Recreate bets table to add 'full_beef' to        │
│ full_beef │ — preserves all rows)  │ ck_bet_type CHECK constraint                     │
│ .py       │                        │                                                  │
└───────────┴────────────────────────┴──────────────────────────────────────────────────┘
```

---

## P1 Next Steps

These are the highest-leverage features needed to move from demo to a real league deployment.

### 1 — Real Data Ingestion
```
Priority : P1-CRITICAL
Files    : (new) data/ingestion/fantasypros_scraper.py
           (new) data/ingestion/injury_feed.py
           db/schema.py (no changes needed — injury_status column already exists)

What's needed
  • Replace mock_league.py with live FantasyPros projection scraper
    (currently scraped with scoring=PPR; already stored in projections table)
  • Scheduled job to refresh projections and injury_status daily (or pre-kickoff)
  • FantasyPros injury report maps to: OUT, IR, DOUBTFUL, QUESTIONABLE tags
  • Actual score ingestion post-game (populate actual_points + matchup scores)
    to trigger settlement
```

### 2 — Authentication & User Sessions  ✅ COMPLETE (P1.1)
```
Files    : auth/jwt_auth.py          ← all auth logic
           db/schema.py              ← User model added
           db/deps.py                ← shared get_db() dependency
           db/migrate_auth.py        ← users table + seeding
           api/main.py               ← 4 auth endpoints + guards on write ops

Implemented
  • HS256 JWT · 8h expiry · SECRET_KEY from env-var
  • POST /auth/register — email must match team; role=gm by default
  • POST /auth/login — OAuth2PasswordRequestForm → access_token
  • GET  /auth/me — current user info from token
  • POST /auth/promote — commissioner-only role assignment
  • get_current_gm / require_commissioner FastAPI dependencies
  • assert_own_team / assert_own_wallet helpers — commissioner bypasses
  • Guards on: /bets/*, /wallet/deposit, /wallet/withdraw,
    /settle/*, /beef/challenge, /beef/respond, /beef/pending/*
  • seed_users() seeds 10 accounts (password: beefs2024)
    kevin.mahoney@gmail.com = commissioner; all others = gm
  • bcrypt 4.0.1 pinned for passlib 1.7.4 compatibility
```

### 2.2 — FAAB Wallet  ✅ COMPLETE (P1.3)
```
Files    : wallet/faab_wallet.py      ← all FAAB logic
           db/schema.py               ← FaabConfig, FaabWallet, FaabTransaction models
           db/migrate_faab.py         ← creates 3 new tables
           api/main.py                ← 12 FAAB endpoints

Architecture
  • Bet wallet  : existing wallets table (wallet_manager.py) — unchanged
  • Waiver wallet: new faab_wallets table — managed by faab_wallet.py
  • All FAAB movements logged to faab_transactions (full audit trail)

Commissioner operations
  • setup_faab_config(opening_bet, opening_waiver, allow_b2w, allow_w2b)
      Default $50/$50; opening balance can be $0 for opt-in betting
      Configure which transfer directions are allowed
  • init_season_wallets() — credits opening balances to all teams (idempotent)
  • apply_pending_topups() — applies queued waiver top-ups (Tuesday job)
  • set_freeze(team_id, frozen) — manual freeze/unfreeze override

GM operations
  • create_bet_topup(amount) — Stripe Payment Link; mock: applies immediately
  • create_waiver_topup(amount) — always queued for next Tuesday regardless of mode
  • confirm_topup(faab_tx_id) — manual confirmation (or webhook dispatch)
  • transfer(from, to, amount) — move funds between wallets
      bet→waiver: respects pending bet exposure (can't move locked funds)
      waiver→bet: respects waiver_balance
      Both directions can be restricted by commissioner

Freeze / funding alert
  • If bet wallet balance <= $0: bet_frozen = True, logs funding_alert
  • Auto-unfreezes when balance goes positive (e.g. after top-up or waiver→bet transfer)
  • get_bet_funded() FastAPI dependency — chains: auth → buy-in check → freeze check
    Applied to all /bets/* and /beef/challenge endpoints (replaces get_buyin_gate)

Tuesday waiver queue
  • apply_on = next Tuesday 03:00 UTC set on all topup_waiver transactions
  • pending_waiver_topup tracks reserved amount not yet credited to waiver_balance
  • apply_pending_topups() finds all pending with apply_on <= now, credits balances

Endpoints (all under /faab/*)
  POST /faab/setup                 commissioner — configure opening balances + rules
  GET  /faab/config/{league_id}    gm — view FAAB config
  POST /faab/init-season           commissioner — credit opening balances to all teams
  GET  /faab/wallet/{team_id}      gm — combined bet+waiver state
  GET  /faab/league/{league_id}    gm — all teams' FAAB states
  POST /faab/topup-bet             gm — top up bet wallet via Stripe
  POST /faab/topup-waiver          gm — queue waiver top-up for Tuesday
  POST /faab/topup-confirm         commissioner — manually confirm pending top-up
  POST /faab/apply-pending         commissioner — apply due waiver top-ups
  POST /faab/transfer              gm — move funds between wallets
  GET  /faab/transactions/{id}     gm — FAAB transaction history
  POST /faab/freeze                commissioner — manually freeze/unfreeze bet wallet
```

### 2.1 — Stripe Connect Payments  ✅ COMPLETE (P1.2)
Files    : payments/stripe_connect.py ← all Stripe logic
           db/schema.py               ← 4 new models + 2 columns on users
           db/migrate_payments.py     ← creates new tables, adds columns
           api/main.py                ← 10 payment endpoints

Implemented
  • Mock mode when STRIPE_SECRET_KEY unset — fake IDs, no real API calls
  • setup_league_treasury(league_id, buy_in_cents, payout_split)
      Commissioner sets per-season buy-in amount and split percentages
  • create_buyin_link(league_id, team_id) → Stripe Payment Link URL
      Idempotent — returns existing link if already created; skips if paid
  • confirm_buyin_payment(record_id) → marks User.buy_in_paid=1, updates treasury total
      Called from Stripe webhook (checkout.session.completed) or manually
  • create_connect_onboarding_link(team_id) → Stripe Connect Standard onboarding URL
      GMs link their Stripe account for receiving payouts
  • preview_payouts(league_id) → shows who gets what based on standings
      Default: weeks 1-14 regular season record (desc wins, desc PF)
  • execute_payouts(league_id) → stripe.Transfer to each winner; idempotent
      In real mode: blocked if winners have no connected Stripe accounts
  • handle_stripe_webhook(payload, sig) → dispatch checkout.session.completed
  • get_audit_log(league_id) → append-only ledger of all Stripe events
  • get_buyin_gate() FastAPI dependency → 402 if buy-in unpaid (when configured)
      Blocks /bets/straight|spread|over_under|prop and /beef/challenge
      Commissioner always bypasses; gate inactive if buy_in_amount_cents=0
  • Default payout split: [60, 30, 10]; configurable by commissioner
  • All amounts in cents internally; dollar strings in API responses

Endpoints (all under /payments/*)
  POST /payments/setup-treasury       commissioner — set buy-in + split
  GET  /payments/treasury/{league_id} open — view current treasury state
  GET  /payments/buyin-status/{id}    gm — all teams' buy-in status
  POST /payments/buyin-link/{team_id} gm — generate payment link (own team)
  POST /payments/buyin-confirm        commissioner — manual buy-in confirmation
  GET  /payments/connect-link/{id}    gm — Stripe Connect onboarding URL
  GET  /payments/payout-preview/{id}  commissioner — preview season payouts
  POST /payments/payout-execute       commissioner — execute payouts
  GET  /payments/audit-log/{id}       commissioner — full audit trail
  POST /payments/webhook              Stripe webhook receiver (open)
```

### 2.3 — Commissioner Rules Engine  ✅ COMPLETE (P1.4)
```
Files    : admin/commissioner_rules.py ← all rules logic
           db/schema.py                ← 5 new models
           db/migrate_rules.py         ← creates 5 new tables
           api/main.py                 ← 12 rules endpoints

AI Parsing
  • Tries Ollama/Qwen first (OLLAMA_URL=http://10.0.0.11:11434, model=qwen2.5:7b)
  • Falls back to Anthropic Claude (claude-haiku-4-5-20251001) if Ollama unavailable
  • Heuristic keyword parser as final fallback (always succeeds)
  • OLLAMA_MODEL env-var overrides default model
  • Structured output validated: rule_type, effect_type, target, amount, has_escrow
  • ai_interpretation, ai_model_used, ai_latency_ms all returned for transparency

Rule Workflow (commissioner-only)
  1. POST /rules/parse        → AI parses raw_text → ParsePreview (no DB write)
  2. POST /rules/create       → Save preview spec as draft CommissionerRule
  3. POST /rules/activate/{id} → draft → active; creates EscrowAccount if has_escrow=True
  4a. POST /rules/execute-weekly {league_id, week}    → Tuesday automation
  4b. POST /rules/execute-end-of-season {league_id}   → final settlement
  (commissioner can also: pause, delete draft, manually release escrow)

Rule Types
  weekly      — executes at Tuesday 12:01am via execute_weekly_rules(league_id, week)
  end_of_season — executes at final settlement via execute_end_of_season_rules(league_id)

Effect Types
  obligation — debit team's bet wallet; if insufficient free balance → status=pending
  payout     — credit team's bet wallet from escrow or direct

Targets
  biggest_loss_margin  — team that lost by the most points that week
  missed_lineup        — lowest-scoring team that week (proxy for lineup miss)
  points_leader        — team with highest total points through week 14 (EOS only)
  commissioner_manual  — no automatic target; commissioner acts manually

Escrow Accounts (one per rule when has_escrow=True)
  • Funds collected weekly debit GM wallets → credit EscrowAccount.balance
  • EscrowTransaction records every in/out with full trail
  • Automatic release: execute_end_of_season_rules() resolves end_of_season triggers
    (finds points_leader, credits their wallet, marks escrow released)
  • Manual release: POST /rules/release-escrow/{escrow_id} with optional target_team_id
  • On release: held_in_escrow executions → paid_out

Idempotency
  • execute_weekly_rules: skips if RuleExecution already exists for (rule_id, week)
  • execute_end_of_season_rules: skips rules already completed; skips released escrows

Audit Trail
  • Every event logged to rule_audit_log: rule_created, rule_activated, rule_paused,
    rule_deleted, weekly_execution, end_of_season_execution, escrow_released,
    escrow_auto_release
  • AI model name + latency_ms stored for every parse operation

Test rules verified
  "Team with biggest loss margin each week owes $10, collect Tuesday, hold in escrow,
   pay to regular season points leader at end of season"
  → weekly · obligation · biggest_loss_margin · $10 · escrow=True · trigger=end_of_season

  "GM who misses a lineup owes $5 to the bet pool"
  → weekly · obligation · missed_lineup · $5 · escrow=False
```

### 2.4 — Tuesday Automation  ✅ COMPLETE (P1.5)
```
Files    : notifications/tuesday_sync.py  ← all sync logic
           db/schema.py                   ← TuesdaySyncRun model added
           db/migrate_sync.py             ← creates tuesday_sync_runs table
           api/main.py                    ← 3 admin endpoints

9-Step Execution Order (each step isolated — one failure never kills the run)
  1. settle_bets      — settle_week() from settlement_engine.py
  2. execute_rules    — execute_weekly_rules() from commissioner_rules.py
  3. freeze_wallets   — check_and_freeze() for all teams with FAAB wallets
  4. apply_topups     — apply_pending_topups() from faab_wallet.py
  5. faab_report      — build FAAB waiver budgets table for Yahoo import
  6. email_comm       — ASCII report to commissioner (settlement + rules + FAAB table)
  7. weekly_wrapup    — generate_weekly_wrap() from reports/weekly_wrap.py
  8. power_rankings   — compute_power_rankings() from reports/power_rankings.py + feed post
  9. email_gms        — per-GM weekly summary email (bets, rule charges, wallet state)

StepResult dataclass
  step, success, message, data: dict, error: Optional[str], duration_ms: int

TuesdayRunSummary dataclass
  run_id, league_id, week, started_at, finished_at, mock_mode,
  steps: list[StepResult], emails_sent, error_count, status

Email Transport
  MOCK_EMAIL_MODE = not bool(os.getenv("SMTP_HOST", ""))
  Live: smtplib STARTTLS using SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / EMAIL_FROM
  Mock: prints [MOCK EMAIL] blocks to stdout — no config required
  COMMISSIONER_EMAIL env-var overrides DB email for commissioner contact

APScheduler
  BlockingScheduler with CronTrigger(day_of_week="tue", hour=0, minute=1, timezone="UTC")
  setup_scheduler(league_ids, *, week_override, mock_mode) — call from service entrypoint

Week auto-detection (_determine_week)
  Priority: CURRENT_WEEK env-var → lowest pending-bet week → None (skip)

Idempotency
  TuesdaySyncRun saved after run completes; run_id is UUID hex (unique)
  Step isolation: each step in try/except, returns StepResult(success=False) on failure

Endpoints (all commissioner-only)
  POST /admin/tuesday-sync           — TuesdaySyncRequest(league_id, week, mock_mode=True)
  GET  /admin/tuesday-sync/runs/{id} — run history for a league (limit=20)
  GET  /admin/tuesday-sync/run/{id}  — full StepResult detail for a single run

CLI usage
  python notifications/tuesday_sync.py --league 1 --week 5      # single run
  python notifications/tuesday_sync.py --league 1 --week 5 --live # real email
  python notifications/tuesday_sync.py --schedule               # start APScheduler

Smoke test result (2026-05-25)
  9/9 steps: OK  |  errors=0  |  emails=21 (1 commissioner + 10 wrap-up + 10 GMs)  |  55.6s
```

### 2.5 — Weekly Wrap-Up + Roast Beef  ✅ COMPLETE (P1.6)
```
Files    : reports/weekly_wrap.py   ← all wrap-up logic (~600 lines)
           reports/__init__.py      ← package init
           db/schema.py             ← WeeklyWrapUp + WrapUpGmEdition models
           db/migrate_wrap.py       ← creates 2 new tables (migration v8)
           notifications/tuesday_sync.py ← step 7 replaced from placeholder
           api/main.py              ← 6 new endpoints

Two Editions
  League Edition (same for all GMs)
    • All matchup recaps (winner, loser, score, margin)
    • Beef of the Week callout (highest drama-score settled BeefChallenge)
    • Roast Beef section (biggest choke, beef streaks, rivalry alerts)
    • Standings snapshot + power rankings preview
  My Edition (personalized per GM)
    • Personal matchup recap + victory lap or taunt
    • Lineup grade (A/B/C/D based on pts left on bench)
    • Betting performance this week (won/lost/net)
    • Status tag + playoff probability change
    • Biggest mistake roast if applicable

Status Tags
  🔥 Contender  — top playoff spots + ≥60% win rate
  👀 On the Bubble — within 2 of playoff line
  😤 Spoiler     — default for middle-of-pack teams
  🍖 The Beef Is Strong Within You — bottom 3 + <35% win rate + ≤5 games left

Lineup Grade
  A — <5 pts left on bench   B — 5–15 pts   C — 15–25 pts   D — >25 pts

AI Writing Chain
  1. Ollama/Qwen (10.0.0.11:11434) — 5s timeout
  2. Anthropic Claude (claude-haiku-4-5-20251001) — fallback
  3. Template string generation — always produces valid output (Jedi brand voice)
  ai_model_used field records which chain level was used

Beef of the Week Detection
  • Primary: settled BeefChallenge with highest drama = amount × upset_factor
  • Fallback: closest regular matchup by margin (drama = 100 / (margin + 1))

Biggest Choke
  • Team that lost AND left the most pts on bench (>10 pt threshold required)

Commissioner Controls
  POST /reports/wrap-up/generate     — trigger; mock_mode=True by default
  PUT  /reports/wrap-up/{id}         — edit league_body or roast_beef before send
  POST /reports/wrap-up/{id}/send    — re-send after edits
  GET  /reports/wrap-up/{id}/editions — per-GM edition detail (status_tag, prob_change)

Email Delivery
  • League Edition + My Edition combined into single email per GM
  • [MOCK WRAP-UP] prefix in mock mode; own _send_email (avoids circular import)
  • Commissioner auto-receives first

DB Archive
  • Every wrap-up stored in weekly_wrap_ups (1 row per league+week)
  • 10 WrapUpGmEdition rows per wrap-up (one per GM)
  • Historical retrieval via GET /reports/wrap-up/{league_id}

Smoke test results (2026-05-25)
  tuesday_sync --week 6: 21 emails (1 commissioner + 10 wrap-up + 10 summary)
  weekly_wrap.py --week 8: run_id=ed40e03d · model=template · gm_editions=10 · status=sent
  DB: 3 wrap-up records · 30 GM editions · all sent=1
  Status tags: contenders (Phil #1, Mac #3, Marcy #5, Austin #8) · bubble (Kevin #2, Jackson #4)
```

### 2.6 — Power Rankings  ✅ COMPLETE (P1.7)
```
Files    : reports/power_rankings.py  ← all rankings logic (~350 lines)
           db/schema.py               ← PowerRanking model added
           db/migrate_rankings.py     ← creates power_rankings table (migration v9)
           notifications/tuesday_sync.py ← step 8 added (was 8 steps, now 9)
           api/main.py                ← 4 new endpoints

Three Ranking Dimensions
  ON-FIELD  (50%)  — win rate (50%), points for normalized (35%), strength of schedule (15%)
    SOS = avg opponent win rate across all matchups through current week
  BETTING   (30%)  — bet win rate (45%), ROI normalized (40%), hot/cold streak (15%)
    Streak: +n consecutive wins = hot, -n consecutive losses = cold
    ROI clipped to [-1, 3] before normalizing to 0–1
  WAIVER    (20%)  — FAAB pts-per-dollar spent on waiver bids
    Equal 0.5 score for all teams when no waiver activity (mock DB)

Composite GM Rating
  composite_score = on_field * 0.50 + betting * 0.30 + waiver * 0.20
  All three dimension scores normalized 0–1 within league before weighting

Status Tags (by composite rank + playoff elimination math)
  🔥 Contender              — composite rank ≤ 4 (in playoff position)
  👀 On the Bubble          — composite rank 5–6 (within 2 of playoff line)
  😤 Spoiler                — composite rank 7–10, not mathematically eliminated
  🍖 Beef Is Strong Within You — max_possible_wins < 4th place wins (week ≥ 5)

Rank Change
  rank_change = prev_week_rank - current_rank (+n = moved up, -n = moved down)
  NULL for first computed week; computed via lookup of previous week's stored row

Tuesday Integration
  Step 8 (new): fires after weekly_wrapup, before email_gms
  No emails — pure computation + feed post

Feed Post
  event_type = "power_rankings"
  headline: "Week N Power Rankings — Leader: {team} | Last: {team}"
  trash_talk: top 3 and bottom 3 teams

API Endpoints (all under /reports/rankings/*)
  POST /reports/rankings/compute              commissioner — trigger compute for league+week
  GET  /reports/rankings/{league_id}/{week}   open — all teams for a specific week
  GET  /reports/rankings/{league_id}/arc      open — all weeks keyed by week number
  GET  /reports/rankings/{league_id}/team/{id} open — one team's full history

DB Archive
  power_rankings: 1 row per team per week (UNIQUE constraint on league+week+team)
  Compute is idempotent — deletes and rewrites existing rows for the same league+week
  Historical arc retrievable across full 17-week season

Smoke test results (2026-05-25)
  week 6: 10 teams ranked — leader: Hurts So Good (W5-L1, PF 723.3, SOS 0.500)
  week 8: rank_change populated — Lamar Mania ↑2, Kelce Way ↓2
  week 9 via tuesday_sync: step 8 OK, 0 errors, 10 teams, feed event posted
  Route count: 77 total (73 + 4 new)
```

### 3 — Push Notifications
```
Priority : P1-HIGH
Files    : (new) notifications/notify_engine.py

What's needed
  • Challenge issued     → notify challenged GM (email or push)
  • Challenge expiring   → 2h warning to challenged GM
  • Challenge accepted   → notify challenger; include staleness_warning if True
  • Settlement complete  → notify both GMs with P&L summary
  • Injury detected      → notify both GMs if bench_battle is pending and a
                           bench player's injury_status changes to out/ir
  • Simple: SendGrid email; stretch: FCM push or Slack webhook
```

### 4 — Live / Real-Time Odds Updates
```
Priority : P1-HIGH
Files    : api/main.py (add WebSocket endpoint)
           odds/monte_carlo.py (no changes needed)

What's needed
  • WebSocket endpoint that re-runs Monte Carlo when projections are refreshed
  • Clients subscribe to a matchup_id / challenge_id channel
  • Server pushes updated OddsResult when projected_points change > threshold
  • Enables UI to show "odds shifted" alert without GM having to refresh
```

### 5 — Parlay / Multi-Leg Bets
```
Priority : P1-MEDIUM
Files    : (new) betting/parlay_engine.py
           db/schema.py (new parlay_bet + parlay_leg tables)
           api/main.py (POST /bets/parlay)

What's needed
  • Combine 2-6 bet legs; all must win for payout
  • Parlay odds = product of individual leg decimal odds
  • Correlated-leg detection (two legs from same matchup) — warn or block
  • Settlement: check all legs; first loss settles whole parlay as lost
```

### 6 — Roster / Lineup Management
```
Priority : P1-MEDIUM
Files    : (new) roster/lineup_manager.py
           db/schema.py (add lineup table: team_id, week, player_id, slot_position)
           api/main.py (/roster/lineup/{team_id}/{week} PATCH)

What's needed
  • GMs set their active lineup before each week locks (Thursday 7pm ET)
  • bench_battle and prop bets should use the GM's ACTIVE lineup, not
    static roster insertion order
  • Lineup lock prevents changes after kickoff
  • Currently: rosters are static insertion-order; starters = slots 1-9
```

### 7 — Admin & Audit Controls
```
Priority : P1-MEDIUM
Files    : (new) admin/admin_engine.py
           api/main.py (/admin/* endpoints behind admin-role auth)

What's needed
  • Void a bet (refund stake, no settlement impact)
  • Override settlement outcome for a single bet
  • Manual injury tagging (admin writes injury_status until real feed exists)
  • Audit log of all admin actions
  • View all open challenges + wallet exposures across the league
```

### 8 — Responsible Gambling Controls
```
Priority : P1-LOW (but pre-launch requirement)
Files    : wallet/wallet_manager.py (add limit checks)
           db/schema.py (add gambling_limits table)

What's needed
  • Per-GM deposit limit (daily / weekly / monthly)
  • Session wager cap (max total bets per week)
  • Cooling-off period: GM can lock themselves out for N days
  • These rules are advisory for a private league but good practice
```
