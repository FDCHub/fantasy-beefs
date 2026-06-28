# Fantasy Beefs — New Thread Handoff v3.0
*Generated: June 28, 2026*
*Status: Active development. Load this document to resume.*

---

## What Shipped Today (June 28, 2026)

- Decision Engine Rev 2 complete — decision_value.py, war_room_routes.py, war_room.html
- Railway deploy complete — live at https://fantasy-beefs-production.up.railway.app
- PostgreSQL provisioned and seeded — 10 teams, 134 players, 6,834 projections
- Railway Hobby plan active — $5/month, no expiry
- team_health.html rebuilt — single screen, readable, heat map working on Railway
- App structure locked — 5 principal cards, all VP tabs defined

---

## Major Product Decisions Locked June 28

### Betting Architecture — Replaces P2.2 Spec

Mode 1: Traditional sportsbook + Fantasybook bets (head-to-head, peer-to-peer, both GMs must accept)
Mode 3: Closed betting pool (mandatory $10/week entry, redistributed Tuesday 12:01am)
Mode 2 (Exchange): ZBB'd — insufficient liquidity for 12-team league
Mode 4 (Prediction Markets): Deferred to V2+

### Buy-In Structure
Configured in My Commish settings post-launch. Reference numbers for Fraser's league:
- $100 championship pot per GM — 60/30/10 split (champ/runner-up/3rd)
- $170 betting bankroll per GM — $10 mandatory weekly pool entry x 17 weeks
- $270 total buy-in x 12 GMs = $3,240 total league money
- Betting bankroll is closed — total never changes, only distribution shifts
- Fantasy Beefs Champion = GM with largest bankroll at season end

### Three Wallet Buckets
- FAAB ($100) — not real money, waiver wire only
- Betting Bankroll ($170) — real money, pool entry source
- Real Money Wallet — Mode 1 versus bets, peer-to-peer

### Four Traditional Sportsbook Bets (locked)
1. Moneyline — your team scores more fantasy points than opponent
2. Point Spread — your team covers the generated spread
3. Team Total O/U — your team scores over or under a posted total
4. Player Prop O/U — a player exceeds or falls below a projected stat or point line

### Four Fantasybook Bets (locked)
All four calculable from official fantasy scoring data. All four priceable once odds engine is ported.
1. More Overs — more of your starters beat their projections than opponent's starters
2. Closest to Projection — whose lineup finishes nearest its projected team total
3. Position Group Wins — QB vs QB, RB vs RB etc., most group wins takes the bet
4. Most Offensive TDs — whose starters score more offensive touchdowns

### Three Weekly Pool Bets (locked)
$40 per pool bet. $120 total pot per week ($10 x 12 GMs).
1. Biggest Winner — whose team goes best vs the field ("Mahomes Alone went 9-2 vs the field — $40 collected")
2. Worst Beat — predict which GM takes the biggest point differential loss that week. $40 rolls to next week if nobody picks correctly.
3. Special Teams Supremacy — highest combined real NFL K + DEF points (FG=3, PAT=1, sacks/takeaways/def TDs as real NFL points)

### Pool Mechanics
- $10 auto-deducted from every GM's bankroll Thursday 12:01am
- Pool bets PUBLIC — all predictions visible to league from Thursday
- Versus bets PRIVATE — hidden until Tuesday 12:01am
- Both revealed in The Sit-Down
- Ties split the relevant share
- Worst Beat $40 rolls to next week if no correct prediction

### Privacy Rules
- Versus bets: hidden until Tuesday 12:01am
- Pool predictions: visible to all GMs from Thursday lock
- The Sit-Down publishes everything Tuesday 12:01am

### Escrow Mechanic (unchanged)
- Flexible Stake and Return with Max Stake Ceiling
- Both GMs must accept — "Beef with Honor"
- Stakes adjust proportionally if odds shift before lock

---

## App Structure (locked)

Navigation: 5 principal cards on bottom nav bar
My League · My Action · My Team · My Account · My Commish

---

### MY LEAGUE

VP1 — The Standings
League table: W/L/PF/PA + bankroll, wager record W/L, wager success rate %, FAAB remaining, pool standing rank
Below table (personalized): GM's bankroll, wager record, wager success rate, FAAB, pool standing, available to bet this week, this week's betting odds vs opponent, what's driving the line (injuries, bye weeks, projection differentials), CTA to The Book, CTA to My Team

VP2 — The Book
Section 1 — Mode 3 Pool Card (leads):
- $120 pot, 12 GMs, Week N
- Three pool bets listed with current predictions
- GM's Worst Beat prediction input
- CONFIRM MY ENTRY button — one tap
- Pool entry status (confirmed/pending)

Section 2 — Mode 1 Matrix (below pool card):
- Rows: all 11 opponents, this week's fantasy matchup opponent pinned and highlighted at top
- Columns: Moneyline | Spread | O/U | Prop | More Overs | Closest | Position | Most TDs
- Tap any cell to open bet slip
- Bet slip: choose side, enter stake, see escrow calculation, "Put Out a Contract" confirm button
- Rat Detector caveat visible if suspicious lineup detected

VP3 — The Sit-Down
Published Tuesday 12:01am. Left/right week navigation for archive access.
1. Pool Results — Biggest Winner ("X went 9-2 vs the field"), Worst Beat result, Special Teams Supremacy winner, redistribution breakdown
2. The Reveal — all versus bets exposed, winners named, amounts collected
3. Week in Review — one short paragraph per matchup (why winner won, why loser lost, what was out of GM's control)
4. Bankroll Shifts — updated standings post-settlement, week-over-week movement
5. Wagering Power Rankings — ranked by betting performance, season's sharpest GM

---

### MY ACTION

VP1 — This Week
- Pool bets status: Biggest Winner (where my team stands vs field), Worst Beat (my prediction + current leader), Special Teams Supremacy (my K+DEF total vs field)
- Versus bets below: each active bet with winning/losing indicator
- One line of Brain line mover intel per active bet (delivered as push notification for MVP)

VP2 — My Record
- This week: pool bets won/lost/pending, versus bets won/lost/pending, net P&L
- Season long: pool record W/L by week, versus record W/L, wager success rate overall and by bet type, net bankroll change since Week 1, best week, worst week

VP3 — My History
- Full personal bet ledger, most recent first
- Left/right week navigation
- Each entry: bet type, opponent, stake, odds, result, amount collected or lost
- Season summary: total wagered, total collected, net P&L, best/worst bet type

---

### MY TEAM

Banner (always visible at top): The Path
"You need to win X of your next Y games. Team Z needs to lose N of their next M."
Clinching and elimination scenarios updated weekly.

VP1 — My Roster
- Team Health diagnostic — positional strengths and weaknesses across three horizons: This Week, Rest of Season, Playoffs
- Lineup optimizer — who should start this week
- Injury alerts — practice participation, official designations, late scratches
- Bye week exposure — conflicts and depth vulnerabilities flagged
- Strength of schedule ahead
- Season outlook heat map — week by week win probability

VP2 — The War Room (private — GM's eyes only)
Move Builder:
- Input any action: trade, waiver add, or hold
- Rules check fires first — roster size, IR flags, drop designator for uneven trades
- Forced drops and waiver replacements automatically identified and factored into true cost

Trade Trap Scanner (fires automatically on every proposed trade):
1. Forced Drop Trap
2. Waiver Replacement Trap
3. Bye Week Trap
4. Depth Illusion Trap
5. Playoff Schedule Trap
6. Injury Correlation Trap
7. Opportunity Cost Trap
8. Lineup Trap
9. Short-Term vs. Long-Term Trap
10. Replacement-Level Trap

Unified Move Ranker — all actions ranked by Decision Value = championship odds gain / resources consumed:
- Option A: Proposed trade → championship odds delta + acceptance probability (rule-based MVP)
- Option B: Best waiver add → championship odds delta + FAAB cost
- Option C: Hold → null delta
- Verdict: UPGRADE / NEUTRAL / DOWNGRADE
- The Brain's plain English recommendation

Output: before/after roster view, before/after win probability and playoff odds, weekly impact heat map

VP3 — My Outlook
- Championship odds — Monte Carlo output, updated weekly
- Playoff odds — probability of qualifying
- Season win probability — week by week
- The Path — full scenario: what you need to do + what you need from others + clinching/elimination scenarios
- Competitor analysis — which teams fight for same playoff spots, their schedules, their form
- Positional trajectory — where roster gets stronger or weaker as season progresses

---

### MY ACCOUNT

VP1 — My Wallet
- Current betting bankroll balance
- FAAB remaining
- Pool standing — rank in closed economy, gap to next GM
- Available to bet this week (beyond mandatory $10)
- Championship pot tracker — $1,200 total, current fantasy standings context

VP2 — My Season
- Bankroll trajectory — week by week chart
- Best week and worst week
- Wager success rate by bet type
- Season P&L summary
- Net bankroll change since Week 1

VP3 — My Settings
- Display name and team name
- Notification preferences — bet lock reminders, settlement alerts, Sit-Down published
- Wallet top-up requests — queued for Tuesday reconciliation only
- League rules reference
- Commissioner contact

---

### MY COMMISH (Commissioner only)

VP1 — Command
- Skipper rules reference — FAQ-based for MVP, full AI agent V2
- Rat Detector — league-wide integrity monitoring:
  - Suspicious trade patterns (repeat partners, lopsided value)
  - Cooperating flags (GM sacrificing team to help another win)
  - Betting anomalies (unusual pool predictions, suspicious patterns)
  - IR trading alerts
  - Late season lopsided trades (Week 10+ weighted heavier)
  - Pattern recognition — has this GM been flagged before?
  - Each flag: what triggered it, severity, recommended action
  - Commissioner can dismiss, investigate, or Whack

VP2 — Settings
Financial: buy-in per GM, championship pot amount and split, betting bankroll per GM, FAAB budget, mandatory pool entry amount, max versus bet, min versus bet, wallet top-up rules
Pool: pool bet types enabled/disabled, redistribution formula, Worst Beat window, tie-breaking rules
Betting: bet types enabled/disabled, betting window rules, settlement source, void rules, Rat Detector sensitivity
League: number of teams, playoff structure, regular season weeks, playoff weeks, scoring rules reference

VP3 — Operations
- League governance: Commissioner drafts rule proposals, GMs vote thumbs up/down from My League tab, vote tracker, vote history, Commissioner announcements
- Tuesday reconciliation: wallet top-up queue, settlement confirmation, manual overrides for edge cases, weekly reconciliation log

---

## Trade Scenario Matrix (complete)

By roster size:
- 1-for-1: clean swap
- 2-for-2: clean swap
- 2-for-1: giving GM under roster minimum, must pick up free agent
- 1-for-2: receiving GM over roster limit, must designate drop
- 3-for-2: giving GM under, must pick up
- 2-for-3: receiving GM over, must designate drop
- 3-for-3: clean swap

By player status:
- IR player involved: automatic flag
- IR with no return date: automatic push to red
- Injured but active: injury risk factored into evaluation

By timing:
- Early season Weeks 1-6: future value weighted heavily
- Mid season Weeks 7-10: balance present and future
- Late season Week 10+: immediate impact weighted heavily, lopsided trades flagged harder
- Post playoff clinch: Cooperating risk highest

By motivation:
- Win-win, win-lose, Cooperating, repeat trade partners flagged

By complexity:
- Trade + drop: uneven trade requiring waiver move as part of transaction cost
- Trade + FAAB bid: giving GM needs free agent, FAAB cost factors into Decision Value
- Multi-week sequenced trades: sometimes optimal strategy is sequence of transactions

---

## MVP vs V2 Scope

### Ships August 1 (MVP)
- All 5 principal cards with VP tabs
- Mode 1 betting: 4 traditional + 4 Fantasybook bets
- Mode 3 pool: 3 pool bets, mandatory $10, redistribution engine
- The Book matrix — all 11 opponents, pool card leads
- The Sit-Down — 5 sections, weekly archive navigation
- The War Room — unified move ranker, 10-trap scanner, rule-based acceptance probability
- The Path — rule-based playoff scenario analysis
- My Commish — Settings and Operations only
- Skipper as FAQ-based rules reference
- Line mover intel as push notifications

### V2 (post August 1)
- The Skipper full AI agent (conversational, dispute resolution)
- Trade acceptance probability ML modeling
- Live line mover intel in-app feed
- Full league governance voting system
- Alternate Spread bet type
- Full prediction market contracts (Mode 4)

---

## Still Pending from Before

- odds_engine.py headless port — prerequisite for pricing all bets programmatically (Phase 1 gate)
- Yahoo player ID bridge — unlocks consensus projection blend
- ROS projections — unlocks SeasonSimulator full season accuracy
- Injury multipliers — unlocks INJURY_MULTIPLIERS in Monte Carlo
- P2.2 spec needs update to reflect new architecture

---

## Dev Model (unchanged)

- Claude (chat): architecture, specs, design decisions — propose before implementing
- Claude Code (PyCharm terminal, ThinkPad X13): multi-file builds, seams, targeted fixes
- Qwen (100.127.74.98:3000): single-file algorithmic modules, fully self-contained prompts only
- All projects: C:\Users\frase\OneDrive\PycharmProjects\
- Fantasy Beefs: C:\Users\frase\OneDrive\PycharmProjects\fantasy-beefs\
- GitHub: FDCHub/fantasy-beefs, branch: master
- Railway: https://fantasy-beefs-production.up.railway.app
- PostgreSQL public proxy: reseau.proxy.rlwy.net:54032

---

## Next Thread Priorities

1. Decide: new betting plan vs old P2.2 spec — deadline July 7
2. odds_engine.py headless port — Phase 1 gate, start immediately
3. Phase 2 build — The Book, pool mechanics, betting platform
4. Update P2.2 spec to reflect new architecture
5. Fantasybook bet pricing models — built on top of odds engine port

---

## Key Gotchas (carry forward)

- yfpy 17.0.0: pass game_id=461 into constructor, merge consumer_secret INTO token dict
- Yahoo backend lags ~15 min after editing redirect URI
- yfpy wraps actual scored stats only — forward projections use FantasyPros
- Railway DATABASE_URL uses internal URL (postgres.railway.internal) — use public proxy for local seeding
- Qwen prompts must be fully self-contained — no imports from markdown, no project file references
- Claude Code handles all multi-file seams — Qwen never starts until seam interface is locked
- All commands must specify machine AND tool

---

*Load this file at the start of every new thread. Also load DECISION_ENGINE_ROADMAP.md for engine context.*
