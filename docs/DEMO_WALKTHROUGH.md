# FantasyStakes — Demo Walkthrough

**Internal product material.** Not marketing copy, not a script to read aloud.
It is the order to click in so a three-to-five minute demonstration lands.

> **Every figure below is asserted by a test.** The leader, the pool-win ranges,
> the moneyline / spread / total ranges, the Championship Scores, the podium and
> the Grand Champion are all asserted in `test_d24_complete_lifecycle.py`
> against the real read models — section 11 pins the exact numbers this document
> quotes, for CURRENT and for FINAL. If a fixture change moves one of them that
> suite fails, rather than this document quietly going out of date.
>
> Do not hand-edit a number here. An earlier revision stated the FINAL pool-win
> range in the week-11 section and nothing caught it, because the suite only
> checked that pool wins were non-zero — which is exactly why the ranges are now
> pinned rather than described.

---

## Before you start

> **The demo requires PostgreSQL.** `betting/settlement_engine.py` takes the
> week settlement row with `SELECT … FOR UPDATE` — the mutex that stops a week
> being paid twice — and SQLite has no such statement. A demo that genuinely
> settles its weeks therefore cannot run on SQLite, and the mutex is not
> something to weaken to make it. Individual modules still run on SQLite; the
> complete interactive demo does not.

```bash
python -m demo.seed --status     # is a showcase league present?
python -m demo.seed              # build it
python -m demo.reset             # back to canonical CURRENT
python -m demo.reset --check     # what reset would touch — writes nothing
python -m demo.states            # which state is it in?
python -m demo.states --to final # play the season out and close it
```

**You do not have to reset by hand before a demonstration.** Clicking *Try
Demo* restores canonical CURRENT itself — see below. Reset stays available for
when you want to be certain, or to undo a season you advanced to FINAL.

---

## The league you are showing

**FantasyStakes Demo League** — 12 GMs, season 2026, **live in week 11** of a
14-week regular season. Ten weeks are complete; four remain.

Every team, GM, player and result is invented. No Yahoo data, no Yahoo
connection, no Yahoo account.

The season is **played, not painted**. Ten weeks of FantasyStakes matchups and
prop pools were struck, accepted and settled through the same engines a live
league uses, so the standings are a consequence rather than a fixture.

| | |
|---|---|
| **Gravy Seal Team Six** | leads the Championship Chase at week 11, unbeaten in FantasyStakes matchups — and the eventual champion |
| **Special Teams Only** | keeps losing by the widest margin and keeps paying the Skunk — and still finishes runner-up on the Chase |
| **Pain Sanders** | **the seat you are sitting in** |
| **Third and Long Island** | wins the Yahoo league, and takes third on the Chase |

Week 11 is genuinely undecided — three live matchups and four open prop pools —
which is the point: there is something at stake on screen.

---

## The sequence

### 1 · Enter the demo — 20 seconds
Click **Try Demo**. No sign-in, no Yahoo, nothing to fill in.

You are seated as **Pain Sanders**, an ordinary GM — *not* the commissioner. The
commissioner is a separate account you are not holding, which is what makes the
commissioner screens honest rather than yours to click.

> "This is sample data. No Yahoo account is connected and nothing here came
> from Yahoo."

**Every visitor gets the same league.** Entry restores canonical CURRENT before
seating you, so whatever the last visitor did is gone. It restores *in place* —
the league keeps its identity, so the pool slate and every number below are the
same for you as for the person before you.

### 2 · Standings, and the Championship Chase — 60 seconds
The **FantasyStakes Championship** table is the one that matters. Land the rule
early, because it is the thing people get wrong:

> "Championship Score is your **net winnings** from FantasyStakes matchups and
> prop pools. Your wallet balance does not count."

Point at the top of the table — **Gravy Seal Team Six** leads at week 11, on
the strength of the prop pools as much as the matchups — then at **Special
Teams Only**, who is paying the Skunk every week and is still second on the
Chase. That is the rule landing: the Chase counts net winnings, not wallet.

Then show **Matchup Standings** and **Prop Pool Standings** underneath: the same
season, split by where the Credits were actually won. Every GM has a real
matchup record and real pool wins.

### 3 · A FantasyStakes matchup — 60 seconds
Open week 11. Three live contests are on the board, one per market — moneyline,
spread and over/under — and the prices are **calculated**, not stored: the
production odds engine simulates both rosters from their projections. The six
week-11 boards price out at moneylines from **−112 to −186**, spreads from
**0.5 to 3.5**, and totals from **177.5 to 192.0**.

> "A Yahoo matchup decides your fantasy record. A FantasyStakes matchup is a
> separate contest between two GMs, on top of it."

**Strike one yourself.** You are Pain Sanders and week 11 is open — issue a
challenge, or accept one. It writes a real challenge, a real pair of wagers and
real escrow, and you can watch Status and Account move. Break whatever you like;
the next visitor gets the league back.

### 4 · A prop pool — 40 seconds
Week 11 carries **four open prop pools**, drawn from the governed catalog by the
same rotation a live league uses. Show an open one and a settled one from week
10 beside it, so the payout is visible.

Pool wins across the league run from **8 to 17** at week 11 — these are real
settled occurrences that credited a wallet, not decoration. By the end of the
season they reach 11 to 22.

### 5 · Status — 30 seconds
Completed action, live action, and what is still open. This is where "the week
is in progress" becomes concrete rather than asserted.

### 6 · The Ledger — 45 seconds
Ten weeks of real double-entry postings. Show the **Season-Opening Allocation**
and its parts, then the weekly release, the Top-Off, the stakes and the
settlements.

> "Credits decide how much you can play. Results decide whether you are winning.
> They are deliberately not the same number."

A **Top-Off** tops up a wallet so a GM can keep playing — and it moves through a
door that the Championship Score does not read, so **topping off can never buy
you a better finish**. That is worth saying out loud; it is the first thing a
sceptical commissioner asks.

No cash. No deposits. Nothing to buy. Say it before you are asked.

### 7 · Championship and Grand Champion — 45 seconds
Run `python -m demo.states --to final` beforehand if you want to show the
finished season. The last four weeks play through the same lifecycle, the season
is **closed** through the real orchestrator, and the championship is frozen and
paid.

**FantasyStakes Championship podium**

| | GM | Championship Score |
|---|---|---|
| 1 | Gravy Seal Team Six | 8241 |
| 2 | Special Teams Only | 5938 |
| 3 | Third and Long Island | 1816 |

The pot splits **60 / 30 / 10** across those three.

**Yahoo podium** (synthetic, invented for the demo): Third and Long Island,
then Gravy Seal Team Six, then Pain Sanders.

**Grand Champion: Gravy Seal Team Six.**

> "Yahoo finish and FantasyStakes finish, 3 / 2 / 1 points each. Highest total
> wins. If that ties, the higher FantasyStakes Championship Score takes it. If
> that ties too, they are co-Grand Champions."

This is the case the rule exists for, so say it plainly: Gravy Seal Team Six
**did not win the Yahoo league** — Third and Long Island did. Gravy Seal won
FantasyStakes and came second in Yahoo, five points to three, and takes the
overall title. Two GMs each won one thing; the Grand Champion is the GM who did
best across both.

---

## What to say if asked

**"Is this real data?"**
No. Every team, GM, player and result is invented for the demonstration.

**"Is it connected to Yahoo?"**
Not in the demo. The product connects to Yahoo for a live league — read-only,
for league settings, rosters, matchups and results. The demo needs none of it,
and neither demo account holds a Yahoo grant of any kind.

**"Is it real money?"**
No. Credits are virtual and there is no deposit, withdrawal or payment path
anywhere in the product.

**"Could I break it?"**
Yes, and it does not matter — clicking Try Demo again restores it.

**"Why is one GM in debt?"**
Special Teams Only lost by the week's widest margin ten times, and the Skunk fee
is charged to that GM each week. It shows as an obligation until the season
closes and the Skunk pot is distributed. That is the rule working, not a bug.

---

## What the demo is NOT showing

Be straight about these; a demo that oversells gets found out in the next
meeting.

- **No live Yahoo connection.** The connect flow exists and is certified; the
  demo deliberately does not use it.
- **The postseason is not played on screen.** The demo's Yahoo bracket is
  synthetic input used to derive the podium; FantasyStakes postseason play is
  not part of the showcase.
- **SQLite is not a supported runtime for the full demo.** See the note at the
  top — settlement requires PostgreSQL.
- **The Yahoo data-retention question is open.** It is a contractual matter, it
  is documented in `ops/yahoo_retention.py`, and the demo does not resolve it or
  depend on it either way.

---

## A note on the figures above

Every name and number on this page is READ FROM `test_d24_complete_lifecycle.py`
and `test_d1_demo_environment.py`, which assert the seeded showcase against the
real read models. The suites are the source; this page is written from them.

They were last re-measured on the adoption of **Pool Catalog & Rotation POR
Revision 1.4**, whose §4.2 rules the weekly slate at 3 TEAM + 1 MATCHUP. That
draws a different set of Prop Pools each week, so every GM's pool net — and with
it the Championship Chase — moved. The Matchup half did not: all twelve teams'
Versus records and Versus nets are byte-identical across the two builds.

The third-place name and the podium scores on this page had ALSO drifted from
the suites before that adoption, independently of it; they are corrected here to
what the suites now measure.
