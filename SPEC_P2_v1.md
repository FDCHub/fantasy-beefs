# Fantasy Beefs — P2 MODULE_SPEC
> Generated: May 26, 2026
> Status: Ready for build
> Stack: Python 3.12 · SQLAlchemy 2.0 · SQLite · FastAPI · NumPy

---

## P2 Overview

P1 delivered the core engine — auth, betting, wallet, FAAB, commissioner rules, Tuesday automation, weekly wrap-up, and power rankings. P2 completes the product for real-league deployment. It has two tracks:

- **Track A — P1 Carryover:** Features scoped in P1 but not yet built
- **Track B — New Features:** Designed in the P2 planning session (May 26, 2026)

---

## Track A — P1 Carryover

### A1 — Real Data Ingestion (Yahoo API)
```
Priority : CRITICAL — nothing else works without this
Files    : (new) data/ingestion/yahoo_client.py
           (new) data/ingestion/injury_feed.py
           (new) data/ingestion/score_ingestion.py
           db/schema.py (no changes needed)

Context
  • Replaces mock_league.py entirely
  • Yahoo Fantasy Sports API — private league, OAuth read-only
  • GM identity anchors to Yahoo email address (not team name)
  • Team name is display-only — can change anytime — never used as PK
  • Custom scoring rules read from Yahoo at season start — no hardcoding
  • Supports up to 20 teams (12 or 14 expected)

What's needed
  Yahoo OAuth Flow
    • GM clicks "Connect Yahoo Account" — OAuth popup
    • Yahoo returns access token + user profile (email + Yahoo GUID)
    • Email stored as permanent GM identity in users table
    • Onboarding screen shows captured email for GM confirmation
    • One-time setup per GM per season

  Data pulls (read-only)
    • League settings and scoring rules → league_scoring table
    • Season schedule and week boundaries → matchups table
    • All 10 teams and GM info → teams table (email as anchor)
    • Weekly rosters and starting lineups → rosters table
    • Live and final scores → matchups.home_score / away_score
    • Individual player point totals → projections.actual_points
    • Projected scores (pre-week) → projections.projected_points
    • FAAB budget per team → faab_wallets.waiver_balance
    • FAAB bid amounts → faab_transactions
    • Waiver wire pickups and drops → feed_events
    • Trades → trade_proposals table (new — see B2)
    • Player stats weekly and season → projections table
    • Injury status → projections.injury_status
    • Ownership percentages → players table (new column)

  Scheduled jobs
    • Daily projection refresh (pre-kickoff Thursday)
    • Post-game actual score ingestion → triggers settlement
    • Injury status refresh — maps Yahoo tags to: OUT, IR, DOUBTFUL, QUESTIONABLE

  IR rule
    • Players on IR with no return date flagged automatically
    • Feeds into The Grill collusion detection (see B2)

  Commish read access
    • Pull whatever Yahoo exposes in commissioner tools
    • Read-only — no write operations back to Yahoo ever
```

---

### A2 — Push Notifications
```
Priority : P1-HIGH
Files    : (new) notifications/notify_engine.py
           api/main.py (new notification endpoints)

What's needed
  Trigger events
    • Challenge issued       → notify challenged GM
    • Challenge expiring     → 2h warning to challenged GM
    • Challenge accepted     → notify challenger + staleness_warning if True
    • Settlement complete    → notify both GMs with P&L summary
    • Injury detected        → notify both GMs if bench_battle pending
                               and bench player injury_status → out/ir
    • Trade posted           → notify all GMs (public Grill fires)
    • Trade accepted         → notify all GMs
    • Trade vetoed           → notify trade participants
    • Wallet obligation due  → remind GM of pending top-up before Tuesday
    • Commish alert          → Sus Gauge hits yellow→red zone

  Transport
    • V1: SendGrid email
    • Stretch: FCM push or Slack webhook
```

---

### A3 — Live / Real-Time Odds (WebSocket)
```
Priority : P1-HIGH
Files    : api/main.py (new WebSocket endpoint)
           odds/monte_carlo.py (no changes needed)

What's needed
  • WebSocket endpoint re-runs Monte Carlo when projections refresh
  • Clients subscribe to matchup_id / challenge_id channel
  • Server pushes updated OddsResult when projected_points change > threshold
  • UI shows "odds shifted" alert without GM refreshing
  • Feeds into The Grill trade evaluator (rest-of-season odds update live)
```

---

### A4 — Parlay Engine
```
Priority : P1-MEDIUM
Files    : (new) betting/parlay_engine.py
           db/schema.py (new parlay_bet + parlay_leg tables)
           api/main.py (POST /bets/parlay)

What's needed
  • Combine 2–6 bet legs; all must win for payout
  • Parlay odds = product of individual leg decimal odds
  • Correlated-leg detection (two legs from same matchup) — warn or block
  • Settlement: check all legs; first loss settles whole parlay as lost
  • Denomination: FAAB or Cash (challenger picks, same flow as single bets)
```

---

### A5 — Roster / Lineup Management
```
Priority : P1-MEDIUM
Files    : (new) roster/lineup_manager.py
           db/schema.py (new lineup table)
           api/main.py (/roster/lineup/{team_id}/{week} PATCH)

New table
  lineup: team_id, week, player_id, slot_position

What's needed
  • GMs set active lineup before each week locks (Thursday 7pm ET)
  • bench_battle and prop bets use GM's ACTIVE lineup (not static insertion order)
  • Lineup lock prevents changes after kickoff
  • Feeds into Trade Evaluator roster before/after view (see B2)
```

---

### A6 — Admin & Audit Controls
```
Priority : P1-MEDIUM
Files    : (new) admin/admin_engine.py
           api/main.py (/admin/* endpoints behind commissioner auth)

What's needed
  • Void a bet (refund stake, no settlement impact)
  • Override settlement outcome for single bet
  • Manual injury tagging (writes injury_status until real feed exists)
  • Audit log of all admin actions
  • View all open challenges + wallet exposures across league
  • Manual wallet credit (Commish confirms offline payment — honor system)
  • Wallet obligation ledger (tracks every GM's real money owed)
```

---

### A7 — Responsible Gambling Controls
```
Priority : P1-LOW (pre-launch requirement)
Files    : wallet/wallet_manager.py (add limit checks)
           db/schema.py (new gambling_limits table)

What's needed
  • Per-GM deposit limit (daily / weekly / monthly)
  • Session wager cap (max total bets per week)
  • Cooling-off period: GM can lock themselves out for N days
  • Advisory for private league but good practice
```

---

## Track B — New Features

### B1 — Wallet Honor System Adaptation
```
Priority : CRITICAL — Stripe deferred to V2
Files    : wallet/wallet_manager.py (updates)
           wallet/faab_wallet.py (updates)
           admin/admin_engine.py (new Commish controls)
           api/main.py (new endpoints)
           db/schema.py (new wallet_obligations table)

Architecture Decision
  Stripe deferred to V2. V1 runs on the honor system.
  App is the ledger. Commish is the bank. Money moves offline.
  All balances reconcile every Tuesday. Season-end ledger exported for settlement.

Three tiers of money — communicated clearly at onboarding and every top-up:

  ┌─────────────────────────┬────────────┬──────────────────────────┐
  │ Money Type              │ Real?      │ Settled When             │
  ├─────────────────────────┼────────────┼──────────────────────────┤
  │ Initial $100 FAAB       │ No         │ Expires end of season    │
  │ FAAB top-ups            │ YES        │ Collected by Commish EOS │
  │ Cash wallet initial $50 │ YES        │ Collected by Commish EOS │
  │ Cash wallet top-ups     │ YES        │ Collected by Commish EOS │
  │ Wager winnings (cash)   │ YES        │ Collected by Commish EOS │
  └─────────────────────────┴────────────┴──────────────────────────┘

Obligation warning (shown every time a GM adds funds)
  "By requesting this top-up you are creating a real financial
   obligation of $[X]. This will be collected at end of season.
   Your current total obligation: $[Y]."

Wallet rules (locked)
  FAAB Bucket — 3 ways to add:
    1. Commish manually credits (offline payment confirmed)
    2. Transfer from Cash bucket ($1:$1)
    3. Win a FAAB-denominated wager
  FAAB → Cash: never
  FAAB expires end of season

  Cash Bucket — 2 ways to add:
    1. Commish manually credits (offline payment confirmed)
    2. Win a Cash-denominated wager
  Cash → FAAB: allowed $1:$1 anytime
  Cash withdrawable end of season

Tuesday Reconciliation Day
  • All top-up requests submitted anytime during the week
  • App queues them — status: pending
  • Every Tuesday Commish reviews queue, confirms offline payment received
  • Commish credits wallets in one session
  • GM wallet shows "pending" until Commish flips switch
  • Aligns with waiver wire processing (Yahoo Tuesday morning)

Season-End Ledger
  • Full export: every GM's total obligation, winnings, net balance
  • Commish uses this to collect / pay out offline
  • Format: PDF or CSV export from /admin/season-ledger endpoint

New table
  wallet_obligations: id, league_id, team_id, amount, type
    (topup_faab|topup_cash|wager_loss), status (pending|confirmed|collected),
    created_at, confirmed_at, collected_at

Commish endpoints (new)
  POST /admin/wallet/credit          — manually credit a GM wallet after payment confirmed
  POST /admin/wallet/confirm-topup   — confirm offline payment, release pending credit
  GET  /admin/wallet/obligations     — full league obligation ledger
  GET  /admin/wallet/season-ledger   — season-end settlement export
  POST /admin/wallet/collect         — mark obligation as collected
```

---

### B2 — Trade Evaluator (The Grill)
```
Priority : HIGH — core engagement feature
Files    : (new) trades/trade_evaluator.py
           (new) trades/grill_engine.py
           (new) trades/trade_feed.py
           db/schema.py (new tables below)
           api/main.py (new /trades/* endpoints)

New tables
  trade_proposals:
    id, league_id, week, proposer_team_id, target_team_id,
    players_offered (JSON array of player_ids),
    players_requested (JSON array of player_ids),
    drops_proposed (JSON array of player_ids),
    denomination (faab|cash), status (pending|accepted|vetoed|expired),
    proposed_at, expires_at, accepted_at, vetoed_at, vetoed_by_user_id

  grill_evaluations:
    id, trade_id, evaluation_type (private|public),
    team_id (NULL for public), quality_score_a (0-100), quality_score_b (0-100),
    sus_score (0-100), case_for_a (TEXT), case_for_b (TEXT),
    verdict (TEXT), ai_model_used, ai_latency_ms,
    playoff_odds_before_a, playoff_odds_after_a,
    playoff_odds_before_b, playoff_odds_after_b,
    games_favored_before_a, games_favored_after_a,
    games_favored_before_b, games_favored_after_b,
    created_at

  trade_comments:
    id, trade_id, team_id, body (TEXT), created_at

Two Modes

  PRIVATE EVALUATOR — GM War Room
    Visible only to the GM running it. Partner never knows.

    Step 1 — GM builds the trade
      • Select trade partner from league roster
      • Pick players they give up (from own roster)
      • Pick players they acquire (from partner's roster)
      • Designate drops if trade pushes over roster limit

    Step 2 — League rules check (fires before evaluation)
      • Both rosters stay within legal size after trade
      • GM must designate drops if over limit — blocked until resolved
      • Position eligibility verified for both sides
      • IR rule: trading for player on IR with no return date
        → automatic flag, shown to GM before they proceed

    Step 3 — Claude evaluates (their side only)
      Inputs:
        • Rest-of-season FantasyPros value of each player
        • GM's current roster and positional needs
        • Current standings and playoff odds
        • Week of season and timing context
        • Bye week coverage rationale
        • Injury risk factors
        • IR status of any player involved

    Step 4 — Output (their side only)
      • Will I win or lose this trade if accepted?
      • Quality Gauge needle (Green → Red) — their side only
      • Claude's case for or against this trade in plain English
      • Roster before and after (side by side)
      • Playoff odds before and after (% chance of making playoffs)
      • Incremental remaining games favored to win

  PUBLIC EVALUATOR — The Grill
    Fires automatically when trade posted and pending.
    Visible to every GM in the league.

    Header
      • GM A gives [players] / GM B gives [players]
      • Trade status: Pending / Accepted / Vetoed
      • Veto countdown clock (hours remaining)

    Needle 1 — Quality Gauge (two needles, one per GM)
      • Green → Red
      • GM A needle: did they win this trade?
      • GM B needle: did they win this trade?
      • Shown side by side — imbalance visible instantly

    Needle 2 — Sus Gauge (one needle, the whole trade)
      Color scale: Green → Yellow → Red
        Green  = Legit win-win, both GMs have clear rational case
        Yellow = Murky — hard to make the case for one side
        Red    = Very suspicious — Commish needs to look now

      Sus signals Claude uses:
        • Rest-of-season value delta between players
        • Does the trade only improve one GM's standing?
        • Week of season (Week 10+ lopsided trades weighted heavier)
        • Positional need — does receiving GM actually need this player?
        • IR acquisition with no return date → automatic push toward Red
        • Pattern: have these two GMs made multiple imbalanced trades?
        • Would any other GM in the league make this trade?

      Commish alert fires automatically when needle hits Yellow → Red

    Claude's Case (three paragraphs, plain English)
      • Case for GM A: why this trade makes them more competitive
      • Case for GM B: why this trade makes them more competitive
      • The Verdict: who won, who lost, by how much

    After Trade Accepted
      • Playoff odds before and after — both GMs
      • Remaining games favored to win before and after — both GMs
      • Roster before and after — both GMs

    Commish Controls
      • Veto button below the gauge — one tap, no explanation required
      • League sees the veto, reason optional
      • Veto overrides acceptance within countdown window

    Comments Section
      • Every GM can comment
      • Threaded replies
      • Beef of the Week engine monitors for Tuesday pickup

The Grill Visual Spec
  Name: The Grill
  Raw steak (🥩) = legitimate trade / Green
  Cooked steak (🍖) = suspicious / Red

  Quality Gauge: Green → Red (did you win this trade?)
  Sus Gauge: Green → Yellow → Red (is this trade legit for both sides?)

  Five zones on Sus Gauge:
    Green       = Legit win-win
    Green-Yellow = One GM advantaged but explainable
    Yellow      = Murky — league decides
    Yellow-Red  = One GM's case falling apart
    Red         = Commish alert — veto territory
```

---

## New Database Tables Summary (P2)

```
wallet_obligations    — honor system obligation tracking
trade_proposals       — all trades proposed in the league
grill_evaluations     — Private + Public Grill outputs
trade_comments        — league comments on public trades
lineup                — active lineup per team per week (from A5)
gambling_limits       — per-GM responsible gambling limits (from A7)
```

---

## New API Endpoints Summary (P2)

```
/trades/*
  POST /trades/propose                    — GM proposes a trade
  GET  /trades/pending/{league_id}        — all pending trades in league
  GET  /trades/history/{league_id}        — completed trade history
  POST /trades/evaluate/private           — GM private war room evaluation
  GET  /trades/evaluate/public/{trade_id} — public Grill evaluation
  POST /trades/accept/{trade_id}          — GM accepts trade
  POST /trades/veto/{trade_id}            — Commish vetoes trade (comm only)
  POST /trades/comment/{trade_id}         — post comment on trade
  GET  /trades/comments/{trade_id}        — get all comments

/admin/wallet/*
  POST /admin/wallet/credit               — manually credit GM wallet
  POST /admin/wallet/confirm-topup        — confirm offline payment
  GET  /admin/wallet/obligations          — full league obligation ledger
  GET  /admin/wallet/season-ledger        — season-end settlement export
  POST /admin/wallet/collect              — mark obligation as collected

/yahoo/*
  GET  /yahoo/auth                        — OAuth initiation
  GET  /yahoo/callback                    — OAuth callback + email capture
  POST /yahoo/sync                        — manual data sync (comm only)
  GET  /yahoo/sync/status                 — last sync timestamp + health
```

---

## Tuesday Sync — P2 Additions

```
Current: 9 steps
P2 adds:
  Step 10: yahoo_sync    — pull latest Yahoo data (scores, rosters, FAAB, injuries)
  Step 11: trade_alerts  — check pending trades expiring within 24h, notify GMs
  Step 12: obligations   — remind GMs of pending wallet obligations due

New step order:
  1.  settle_bets
  2.  execute_rules
  3.  freeze_wallets
  4.  apply_topups
  5.  yahoo_sync         ← NEW
  6.  faab_report
  7.  email_comm
  8.  weekly_wrapup
  9.  power_rankings
  10. trade_alerts       ← NEW
  11. obligations        ← NEW
  12. email_gms
```

---

## Key Design Decisions (P2)

```
┌────────────────────────────────┬──────────────────────────────────────────────┐
│ Decision                       │ Rationale                                    │
├────────────────────────────────┼──────────────────────────────────────────────┤
│ Yahoo read-only forever        │ No write operations back to Yahoo ever.      │
│                                │ All actual moves happen in Yahoo app.        │
│ GM identity = Yahoo email      │ Team name changes constantly. Email is       │
│                                │ permanent. Captured once at OAuth onboarding.│
│ Honor system V1                │ Stripe deferred to V2. Commish is the bank.  │
│                                │ App is the ledger. Tuesday reconciliation.   │
│ Obligation warning on every    │ GMs must understand every top-up creates a   │
│ top-up                         │ real debt collected at season end.            │
│ IR trade = automatic Sus flag  │ Trading for IR player with no return date    │
│                                │ has no rational self-interest argument.       │
│ Private Grill = war room only  │ Partner never knows evaluation happened.      │
│                                │ No playoff odds shown — trade not accepted.  │
│ Public Grill fires on post     │ Automatic — no Commish trigger needed.       │
│ Two needles, one trade         │ Quality (did you win?) is separate from Sus  │
│                                │ (is this collusion?). Bad trade ≠ sus trade. │
│ Commish veto = one tap         │ No explanation required. League sees veto.   │
│                                │ Reason optional.                             │
│ Tuesday = Reconciliation Day   │ All wallet top-ups, Yahoo sync, obligations  │
│                                │ settle on Tuesday. One weekly Commish task.  │
└────────────────────────────────┴──────────────────────────────────────────────┘
```

---

## Build Order Recommendation

```
1. Yahoo OAuth + data ingestion     ← everything depends on real data
2. Wallet honor system adaptation   ← must work before season starts
3. Trade Evaluator DB + API         ← tables and endpoints first
4. The Grill engine (Claude calls)  ← wire in after DB ready
5. Push Notifications               ← wire in after trades + wallet
6. Roster / Lineup Management       ← needed before Week 1 kickoff
7. WebSocket / Live Odds            ← wire in after lineup management
8. Parlay Engine                    ← additive, lower risk
9. Admin & Audit Controls           ← wire in before launch
10. Responsible Gambling Controls   ← pre-launch gate
```

---

*End of P2 MODULE_SPEC — Fantasy Beefs*
*Next session: begin with Yahoo OAuth implementation (A1)*
