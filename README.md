# FantasyStakes

FantasyStakes is a **private-league companion application for Yahoo Fantasy
Football**. It is built for the members of an existing private Yahoo fantasy
league, to sit alongside the league they already play and add statistics,
analytics, and friendly peer-to-peer competition between those members.

It is not a commercial service, it is not open to the public, and it is not
affiliated with or endorsed by Yahoo.

---

## What the application does

* **Fantasy statistics and analytics** — weekly and season views built from the
  league's own data: standings, power rankings, projections, roster and lineup
  state, and matchup analysis.
* **Peer-to-peer head-to-head challenges** — one league member may challenge
  another over a given week. Both sides are league members; the application
  never takes a side.
* **League-wide pools** — optional weekly pools open to the whole league.
* **Internal Credits bookkeeping** — an integer-cent, double-entry ledger that
  records each member's Credits position so the league can see where things
  stand.
* **Proposal lifecycle** — immutable, versioned challenge proposals with
  both-team lineup snapshots, a single counter-offer, and deterministic
  accept / decline / cancel / expire transitions.
* **Challenge escrow** — Credits committed to an open challenge are held in a
  per-challenge escrow account and returned exactly, to their original source,
  if the challenge is declined, cancelled or expires.
* **Dynamic pricing** — an optional challenge mode where each side's maximum
  exposure is fixed at agreement time while lineups and odds remain live.
* **Final Lock** — at kickoff, a Dynamic challenge is priced once, deterministically,
  under the simulation model frozen at agreement time, and its terms are then
  immutable.

## Why Yahoo Fantasy API access is needed

The application mirrors a league the members are already playing in Yahoo. To do
that accurately it needs to read that league's own data:

* **league rosters** — who is on each team;
* **matchups** — the weekly schedule of team-vs-team fixtures;
* **scoring settings** — the league's scoring configuration, so calculations
  match what members see in Yahoo;
* **schedules** — the NFL week structure and kickoff timing that drive lineup
  lock;
* **starting lineups** — which players each member has started, captured as a
  snapshot at the moment a challenge is proposed;
* **projections** — where Yahoo makes them available;
* **weekly and live scoring data** — the actual results used to determine
  outcomes.

Yahoo data is used **only** to operate the companion experience for the
participating private league. It is not sold, not redistributed, and not used
outside the league it came from.

## What the application does **not** do

* **No house.** The application never takes a position against a member.
* **No rake.** No fee, commission or cut is taken from any challenge or pool.
* **No operator position against users.** Every challenge is between two league
  members.
* **No real-money processing.** There is no payment path in this codebase.
* **No payment processing of any kind.** No payment provider is integrated, and
  none is present in the dependencies.
* **Credits are internal bookkeeping units.** They are a record of standing
  within a private league, not currency and not a stored-value instrument.
* **Settlement between league members happens outside the application.**
  Whatever members choose to do among themselves is theirs to arrange; the
  application only keeps the record.
* **No affiliation with or endorsement by Yahoo.**

## Provider boundary while API access is pending

The application is written against a provider interface rather than against
Yahoo directly. While live Yahoo Fantasy API access is pending, development and
testing run on recorded and synthetic fixtures behind that boundary. Live Yahoo
access is not enabled in this repository.

## Current MVP status

| Sprint | Scope | Status |
|---|---|---|
| 1 | Foundation — ledger primitive, wallet, commissioner authority, season allocation | Complete |
| 2 | Proposal lifecycle and challenge escrow | Complete |
| 3 | Dynamic pricing and Final Lock | Complete |
| 4 | Common Pool Engine | In development |

This is active development work, not a finished product. Nothing here is
production-deployed or publicly available.

## Repository structure

```
api/            HTTP surface (FastAPI)
auth/           authentication and league access gating
beefs/          head-to-head challenge lifecycle
betting/        pools, per-bet locking, settlement
economy/        Credits economy: escrow, allocation, season close, championship
ledger/         integer-cent double-entry ledger primitive
odds/           Monte Carlo simulation, pricing, model-version registry
wallet/         member Credits balances
db/             schema and migrations
reports/        standings, rankings, weekly wrap, account views
feed/           league activity feed
notifications/  scheduled league sync
ingestion/      external fantasy-data ingestion
data/           reference data
spec/           module specifications
tests/          test suites
tools/          interface prototype
```

## Technical stack

* **Python**
* **FastAPI** — HTTP layer
* **SQLAlchemy** — ORM and schema
* **PostgreSQL** — primary datastore
* **NumPy** — Monte Carlo simulation

## Tests

Test suites live in `tests/`. Suites touching the Credits ledger require a
disposable PostgreSQL database, because they exercise real row-level locking and
transaction behaviour that SQLite does not enforce:

```bash
export TEST_DATABASE_URL="postgresql://<user>:<pass>@localhost:5432/<disposable_db>"
python tests/test_p3_d2_dynamic_final_lock_pg.py
```

Pure-computation suites, such as the Dynamic pricing primitives, need no
database:

```bash
python tests/test_p3_d1_dynamic_pricing.py
```

## License

Proprietary. All rights reserved.