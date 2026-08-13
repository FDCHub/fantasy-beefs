# WP6D — Final End-to-End Product Lifecycle Certification

**Branch** `postmvp/wired-product-reconciliation`
**Starting HEAD** `b2801712251d131cb0083af752b8a662999e974f` — *WP6C — cut Pool picks over to governed claims*
**Working tree at start** clean
**Certified S8** tag `core-mvp-certified-s8` → commit `5613e4a31f2b6e4d79c417024155ec357c914456` — untouched

This report supersedes the *findings* of `WP6_END_TO_END_LIFECYCLE_REPORT.md`,
which remains in the tree as the historical record of what WP6 found before
WP6B and WP6C were built.

---

## 0 · The answer, first

**NO — BLOCKED AT step 36 (Season Close): `verify_preconditions` step 8
`pool_rollover`.** Two Pool occurrences end the run carrying a live rollover, so
`POST /league/{id}/season/close` refuses with 409.

**That refusal is a CERTIFICATION-CORPUS HORIZON, not a product wiring gap, and
the suite proves the distinction rather than asserting it.** Both rollovers are
`ZERO_ELIGIBLE_CLAIMS` — the SUBJECT layer, where no matchup in the recorded
corpus satisfied the predicate — and this run put **six real governed claims on
each of them through the production route** and they still classified
subject-zero. POR §5 resolves such a pot by sweeping it to Championship at
`season_final_week`. This league's final week is **17**, stated by the provider's
own payload; the recorded WP2B-C corpus covers **weeks 1 and 2**.

**Both blockers WP6 reported are CLOSED, and this run proves each end to end:**

| WP6 blocker | Status | Proof in this run |
|---|---|---|
| 1 — Dynamic Final Lock had no production caller | **CLEARED (WP6B)** | §12: `python -m workers.final_lock` locks the wager at its governed kickoff; per-side escrow drained, Bet rows created, escrow resolved through ordinary weekly settlement; `escrow_resolved` is now MET |
| 2 — governed Pool claims had no production route | **CLEARED (WP6C)** | §6/§13: 28 governed `PoolClaim` rows created by authenticated GMs through `POST /pool/pick`; zero legacy rows; the production settlement route pays the winning tickets and nobody else |

`escrow_resolved` — the prerequisite that WP6 called "the blocker that actually
stops the lifecycle" — is now satisfied: **not one escrow account in the database
carries a balance.**

---

## 1 · Stale WP6 assertions retired and replaced

Two assertions existed only to prove the blockers. Each is replaced by a
strictly stronger one: the old assertion demanded a surface be **absent**; the
new one demands it **exist and behave**.

| Retired | Replaced by |
|---|---|
| §6.1 `/pool/pick` returns 200 **and writes ZERO governed claims** | §6.1 `/pool/pick` creates **exactly one governed `PoolClaim` per submitting GM and no other**, and writes no legacy `PoolBetPick`/`PoolPrediction` row |
| §6.2 **no GOVERNED claim route is mounted anywhere** | §6.2 the **LEGACY request shape is refused (422)**; the pick surface is still exactly one route (`/pool/pick`), because the cutover changed what it *writes*, not how many ways in there are |
| §6.3 **ENGINE DEMONSTRATION** — `submit_claim()` called directly to manufacture claims | **Deleted.** §6.4 asserts this file's own source neither imports nor calls the claim engine, so §8's payout cannot be reached by any means but the product |
| §12 `run_final_lock` exists **and NOTHING in the product calls it** — tree walk returning an empty caller list | §12 `python -m workers.final_lock --dry-run` runs and declines **before** kickoff; `run_once(now=kickoff)` returns `LOCKED`; one `ChallengeFinalLock` row; two `Bet` rows; per-side escrow drained into per-bet escrow |
| §12 handshaken Dynamic escrow is **STRANDED** / Season Close refused at `escrow_resolved` | §12 + §14 + §15 the Dynamic legs settle through the **same** weekly automation as the Locked wager, and `escrow_resolved` is MET — `open_escrow_accounts() == []` |

**Kept deliberately:** the assertion that **no Final-Lock HTTP route is mounted.**
Rev9 §5.5 fixes the actor class as a scheduled system worker — "not an end user,
not a GM, not a commissioner, not reachable from any HTTP route." A route would
have been the wrong repair. WP6 refused to add one and WP6B did not add one, so
its absence is still worth proving.

**Nothing was weakened.** Assertion count rose from 130 to **188**, all passing.

---

## 2 · Synthetic league topology

| | |
|---|---|
| League | id **19**, season **2025**, WP2B-C Economic Proof League |
| Provider identity | `999.l.100001` (publication-safe; no real Yahoo id appears in any fixture) |
| Teams | **6**, `999.l.100001.t.1` … `t.6`, one wallet each |
| Users | 1 commissioner (team 1) + 5 GMs, all password-authenticated, all JWT-bearer |
| Boundaries | `season_final_week` **17**, `playoff_start_week` **15** — agreeing with the corpus payload, so `_reconcile_boundary` records no conflict |
| Corpus | 17 `yahoo_wp2bc*` fixtures, every one `provenance=SYNTHETIC`, every payload's SHA-256 recomputed against its manifest |
| Isolation league | a second league + commissioner, created in §16 |
| Weeks driven | **1 and 2** (the recorded corpus's full extent) |

**The one substitution is the transport.** `providers.yahoo.transport.YahooLiveTransport`
is pointed at `FixtureTransport`, patched on the module so every production
consumer — the Pool activation route, the Pool settlement route and
`notifications.tuesday_sync`, which builds its own — is served from the corpus by
one seam. Routes, authorization, assembly, identity resolution, stat source,
census, engines, ledger and the Final-Lock worker are all production.

---

## 3 · Fixture-only bootstrap actions (declared, not hidden)

Each exists because the product genuinely exposes no self-serve path for it.

| # | Action | Why no product path |
|---|---|---|
| 1–3 | League row, team rows, wallets, provider identity binding | no league-creation route; RUNBOOK §6.3 records onboarding as deliberate post-MVP scope |
| 4 | Rosters + projections | the odds model reads `Roster`+`Projection`; no route ingests projections |
| **4b (new)** | **`NflSchedule` for `LOCK_SEASON`** | the Final-Lock worker's dueness comes from `_nfl_lock_time(LOCK_SEASON, week)`; `seed_economic_league` seeds only `CURRENT_SEASON`. Both years are seeded so each reader finds its own. No route ingests the NFL schedule |
| 5/6 | User accounts and the FIRST league commissioner | no onboarding/OAuth flow; no first-commissioner grant that does not already require a commissioner |
| 7 | Replay-clock re-stamp of the Pool support measurement | the corpus observes at a frozen 2025 instant and gate 2 fails closed beyond 24h — **which §3 proves first**, before re-stamping. Supplies the `measured_at` a live provider would; changes no gate rule |
| 8 | The NOT_FINAL week-2 scoreboard | the state a live league is in **while** its GMs wager. The product has no action that produces "the games have not finished" — a real league has simply not finished playing |

Item 4b is the only addition WP6D makes to the list.

---

## 4 · Lifecycle sequence, and the production surface used at every step

| # | Capability | Surface | Actor | Result |
|---|---|---|---|---|
| 1–2 | league / users / teams | fixture-only (declared) | — | 6 teams, 6 authenticated users |
| 3 | commissioner authority | `GET /auth/me`; `POST /league/{id}/week/1/open` as a GM | commissioner / GM | 200 `role=commissioner`; **403** for the GM |
| 4–8 | season-opening allocation | `POST /league/{id}/season-allocation` | commissioner | 200 `created=true` |
| 9 | Pool catalog | `scripts/bootstrap_pool_catalog` (deployment action) | operator | 80 definitions |
| 10 | Pool readiness / provider measurement | `POST /league/{id}/pool/activate?week=1` | commissioner | 200, 12 definitions ready, measured from what the payload actually carried |
| 11 | Week Open | `POST /league/{id}/week/1/open` | commissioner | 200 |
| 12 | Weekly Minimum release | (same call) | commissioner | 6 × 1000 cents |
| 13–15 | Versus create / counter / accept | `POST /beef/challenge` → `/beef/counter` → `/beef/respond` | GM(T2), GM(T3), GM(T2) | 201 / 200 / 200 |
| 16 | escrow / funding | (same chain) | — | `escrow:1`=300, `escrow:2`=300 |
| 17 | Dynamic mode | `POST /beef/challenge` `challenge_mode=dynamic` → `/beef/respond` | GM(T4), GM(T5) | 201 / 200 |
| **18** | **production Final Lock worker** | **`python -m workers.final_lock`** | **system worker** | **`LOCKED`** |
| 19 | Anchor / Derived Bet creation | (Final Lock) | system worker | `Bet [3, 4]` pending |
| **20** | **Pool claim submission** | **`POST /pool/pick`** | **GMs** | **28 governed `PoolClaim` rows** |
| 21 | Pool collection | `POST /league/{id}/pool/collect/{week}` | commissioner | 200, 4 occurrences, 150 each |
| 22 | Yahoo roster/stat path | `POST /admin/tuesday-sync` | commissioner | 200, provider gateway |
| 23 | provider finality | (same) | — | 3 matchups with persisted `finalized_at` |
| 24 | Versus settlement | `POST /admin/tuesday-sync`, `POST /league/{id}/settle/{week}` | commissioner | both wagers terminal |
| 25 | Pool settlement on REAL claims | `POST /league/{id}/pool/settle/{week}` | commissioner | 200 |
| 26 | zero-winner / rollover | (same) | — | rollover and sweep both exercised |
| 27 | Week Close | `POST /league/{id}/week/{week}/close` | commissioner | 200 |
| 28–29 | automatic Skunk + exact figures | (same call — there is deliberately no separate "assess Skunk" action) | commissioner | see §9 below |
| 30 | Weekly Minimum expiry | (same call) | commissioner | `min:{t}:{w}` → 0, `expired_min` funded |
| 31 | Ledger | `GET .../ledger/positions`, `/ledger/reconciliation`, `/ledger/me` | commissioner + GM | 200, `reconciles=true` |
| 32 | The Week / Wrap Up | `GET .../week/{w}/matchups`, `/week/{w}/skunk`, `/pool/slate/{w}`, `/action/me` | GM | 200 |
| 33 | retry Week Close | `POST .../week/1/close` again | commissioner | 200 `already_closed=true`, zero movement |
| 34 | second governed week | full week-2 cycle | commissioner + GMs | 200 |
| 35 | season-close prerequisites | `verify_preconditions` | — | **8 of 9 met** |
| **36** | **Season Close** | `POST /league/{id}/season/close` | commissioner | **409 `pool_rollover`** |
| 37–40 | Skunk season reconciliation, Championship 60/30/10, expired-minimum reconciliation, Current Settle | (steps of `close_season_economy`) | — | **NOT REACHED** |
| 41 | trial balance zero | `ledger.trial_balance()` | — | **0** at every checkpoint |
| 42 | repeat Season Close | `POST .../season/close` again | commissioner | 409 again, zero mutation |
| 43 | league isolation | four routes as a FOREIGN commissioner | other commissioner | **403 × 4** |

---

## 5 · Opening 220-Credit proof

`POST /league/19/season-allocation` → 200 `created=true`

| Component | Route reported | Ledger |
|---|---|---|
| Weekly Minimum Reserve | `min_reserve_cents` **14000** | `min_reserve:{t}` = **14000** for all six |
| Championship Reserve | `reserve_cents` **8000** | `reserve:{t}` = **8000** for all six |
| Total obligation | `buyin_cents` **22000** | 140 + 80 = 220 |
| League total | `total_buyin_cents` **132000** | 6 × 22000 |
| **Wallet** | — | **0 for every GM** — nothing is spendable at opening |

Trial balance **0** after issuance. Repeat → 200 `created=false`, reserves
unchanged.

---

## 6 · Weekly Minimum proof

`POST /league/19/week/1/open` → 200, `total_released_cents` **6000** = 6 × **1000**.

- `min:{t}:1` = **1000** each — spendable.
- `min_reserve:{t}` = **13000** each — fell by exactly what was released.
- Duplicate Week Open → 200 `already_open=true`, releases nothing.
- After two governed weeks: `min_reserve:{t}` = **12000** = 14000 − 2 × 1000.

---

## 7 · Versus lifecycle proof

| Step | Surface | Result |
|---|---|---|
| create (Locked, $2.00) | `POST /beef/challenge` | 201; `escrow:challenge:1` = **200**, sourced from `min:{T2}:2` |
| counter to $3.00 | `POST /beef/counter` | 200; escrow **unchanged** — a counter moves no money (Spec 2 §10) |
| counterer tries to accept | `POST /beef/respond` | **403** — a counter hands the decision back to the issuer |
| issuer accepts | `POST /beef/respond` | 200; two pending `Bet` rows |
| escrow migration | — | `escrow:1` = **300**, `escrow:2` = **300**; pooled challenge escrow **0** |
| settlement | `POST /admin/tuesday-sync` (`settle_bets`) | both legs terminal; every escrow account drained |
| retry | `POST /league/19/settle/2` | 200 `already_settled=true`, zero movement |

Trial balance **0** across the whole negotiation.

---

## 8 · Dynamic Final Lock worker proof — WP6B closure

**Before the worker**

- `escrow:challenge:2:anchor` = **100** (the anchor stake exactly)
- `escrow:challenge:2:derived` = **620** (the opponent's full Derived ceiling, equal to `opponent_ceiling_cents` from the handshake reply)
- **0** `Bet` rows — the Derived side is priced at Final Lock, and that absence is the protocol
- Season Close refused with the wager outstanding

**The worker runs**

```
python -m workers.final_lock --league 19 --dry-run     -> exit 0
[final-lock] examined=1 (not_due=1)
  challenge 2 (league 19, week 2): not_due — due at 2026-08-17T17:00:00+00:00
```

Before the governed kickoff it locks nothing; escrow is exactly as the Handshake
left it. At the challenge's earliest covered kickoff:

```
run_once(worker_id="wp6d-lifecycle-worker", now=<kickoff>, league_id=19)
  challenge 2: locked — final locked
```

**After the worker**

| Claim | Observed |
|---|---|
| Dynamic escrow exists before Final Lock | 100 + 620 = **720** cents held per-side |
| production worker runs | `workers.final_lock.main([...])` — the `Procfile` `final_lock` process type; `railway.final_lock.toml` its own service |
| Final Lock creates governed Bet state | **2** `Bet` rows (`[3, 4]`, pending) + **1** `ChallengeFinalLock` row |
| per-side escrow drained | anchor **0**, derived **0** |
| Credits migrated, not cancelled | `escrow:3` = 100, `escrow:4` = 620 — **720 of 720**; the challenge is priced, not voided |
| escrow resolves through normal lifecycle | both legs terminal on the **same** `POST /admin/tuesday-sync` run that settled the Locked wager — no Dynamic branch anywhere in the settlement chain |
| no stranded Dynamic escrow blocks Season Close | `open_escrow_accounts()` = **[]**; `escrow_resolved` is **MET** |
| actor class unchanged | **no** route matching `final`/`lock`/`dynamic` is mounted — no GM and no commissioner could have done this |
| trial balance | **0** across issue, handshake, Final Lock and settlement |

---

## 9 · Pool claim production-path proof — WP6C closure

| Claim | Observed |
|---|---|
| GM submits a Pool pick through the running product | `POST /pool/pick` with the governed body (`pool_instance_id` + `subject_id`), authenticated as each GM — 200 |
| exactly one governed PoolClaim | week 1: **4** claims on occurrence 4, one per submitting GM, subjects exactly as posted. Week 2: **24**, one per GM per occurrence. **28** total |
| active path writes no legacy row | `PoolBetPick` = **0**, `PoolPrediction` = **0**, for the whole database, at every checkpoint |
| the legacy request shape no longer works | `{bet_type, pick}` → **422**, and the refusal writes nothing legacy or governed |
| production Pool settlement sees that claim | `POST /league/19/pool/settle/1` → `most_passing_yards` `CLAIMS_PRESENT`, `winning_team_ids=[2,3,4]`, `distributed_cents=150` |
| settlement resolved TICKETS, not teams | every paid GM's **persisted** claim named the same subject — read back from `pool_claim`, not from the reply (a Pool is a blind prediction, so the route does not publish the winning subject) |
| winning ticket receives governed payout | each of the 3 winners: wallet **+50** cents |
| losing ticket receives none | the GM who backed the losing subject: **+0** |
| abstainer receives none | the GM who never picked: **+0** |
| no manual `submit_claim()` is used | §6.4 asserts this suite's own source neither imports nor calls the claim engine — needles assembled at runtime so the assertion text is not its own match |
| a pick is a claim, not funding | trial balance **0**; `pool:19` unchanged by submission, refusal and replacement alike |
| blind until settlement | the submitting GM sees `my_subject_id`; another GM sees `null` but the same public `claim_count` |

---

## 10 · Pool collection / settlement proof

`POST /league/19/pool/collect/1` → 200: 6 GMs charged once at the governed
100-cent entry, `total_cents` 600, **4** occurrences opened at 150 each.
Duplicate → **409 ALREADY_COLLECTED**, `pool:19` unchanged.

Week 1 settlement (all four resolved, `all_settled=true`):

| Occurrence | Classification | Pot | Distributed | Rolled | Swept |
|---|---|---|---|---|---|
| `matchups_where_neither_team_threw_an_interception` | ZERO_ELIGIBLE_CLAIMS | 150 | 0 | **150** | 0 |
| `matchups_with_zero_total_turnovers` | ZERO_ELIGIBLE_CLAIMS | 150 | 0 | **150** | 0 |
| `highest_combined_passing_yards` | CLAIMS_PRESENT | 150 | 0 | 0 | **150** (not rollover-eligible) |
| `most_passing_yards` | CLAIMS_PRESENT | 150 | **150** | 0 | 0 |

Week 2 settlement — the week-1 carries arrive as **continuations** (pot 300 each,
larger than a fresh week's 150 share) and the fresh draws pay their claimants:

| Occurrence | Classification | Pot | Distributed | Rolled |
|---|---|---|---|---|
| `matchups_where_neither_team_threw_an_interception` (continuation) | ZERO_ELIGIBLE_CLAIMS | 300 | 0 | **300** |
| `matchups_with_zero_total_turnovers` (continuation) | ZERO_ELIGIBLE_CLAIMS | 300 | 0 | **300** |
| `shootout_of_the_week` | CLAIMS_PRESENT | 150 | **150** | 0 |
| `fewest_combined_turnovers` | CLAIMS_PRESENT | 150 | **150** | 0 |

Every occurrence conserved its pot exactly; no occurrence paid more than its pot.
Duplicate settlement → 200 with every entry `replayed=true` and **zero** further
movement.

---

## 11 · Provider / finality proof

`POST /admin/tuesday-sync` → 200. `refresh_scores` succeeds through the provider
gateway; **3** `Matchup` rows carry a persisted `finalized_at`, so finality is
governed by a timestamp and not by a status string.

Three of the nine sync steps fail closed offline and are named rather than
hidden: `sync_players`, `capture_roster_slots` (both build their own live Yahoo
query and refuse without credentials) and `apply_topups` (refuses on accepted B6
issuance-ledger grounds). None is on the economic path.

**Finality negative** — `POST .../pool/settle/2` and `POST .../week/2/close`
against the NOT_FINAL week both refuse **409 `RESULTS_NOT_READY`**, the refusal
names all three unfinalized matchup ids, and **nothing moved**: pool account,
every wallet, every `expired_min` and every `min:{t}:2` unchanged, trial balance
untouched. The refused close did not partly close the week.

---

## 12 · Skunk + point differential + $10 proof

Assessed **automatically inside Week Close** — there is deliberately no separate
"assess Skunk" action.

| | |
|---|---|
| Skunked team | **team 3** (`team_id` = T3) |
| Opponent | **team 4** |
| Final score | **87.0** vs **131.75** |
| Point differential | **44.75**, equal to `opponent_score − score` to the cent of a point |
| Amount | **$10** — `amount_cents` 1000 |
| Receivable | `receivable:{T3}` = **−1000** |
| League Skunk pot | `skunk:19` = **+1000** |
| Other GMs | **0** — no other GM carries a Skunk obligation |
| Wallets | **untouched** — the Skunk is ledger-only |
| Events | exactly **1** `SKUNK_ASSESSMENT` for the week; **2** across two governed weeks, never two for one |

It is the week's **worst** loss, not the narrower defeat in another game. Readable
by an ordinary GM at `GET /league/19/week/1/skunk` with the same team, margin and
amount the close reported.

---

## 13 · Week Close proof

`POST /league/19/week/1/close` → 200. Skunk assessed; unused Weekly Minimum
expired for every GM (`min:{t}:1` → **0**), moved to `expired_min:{t}` and not
into a wallet, with the sum of the six matching `total_expired_cents` exactly.

**Retry:** 200 `already_closed=true`, `skunk.replayed=true`; receivable, Skunk pot
and every expiry balance unchanged; still exactly one assessment event. Trial
balance **0**.

---

## 14 · Ledger / The Week proof

| Read | Result |
|---|---|
| `GET .../ledger/positions` | 200, six positions |
| `GET .../ledger/reconciliation` | 200, **`reconciles=true`** — two independent routes to the same number agree |
| `GET .../ledger/me` (GM) | 200, carries the expired minimum this week produced |
| `GET .../week/1/matchups` | 200, three matchups, all `final` |
| `GET .../week/1/skunk` | 200, matches the close |
| `GET .../pool/slate/1` | 200, every occurrence `settled` |
| `GET .../action/me` | 200 |
| `GET .../lifecycle` | 200, week 2 `opened`, `closed`, `skunk_assessed` |

---

## 15 · Second-week continuation proof

Week 2 opens and releases its own minimum; its fixtures are published and **none
is final** — the state a league is actually in while wagering. GMs wager, all six
claim on all four occurrences, the Dynamic wager Final-Locks, results ingest,
both wagers settle, Pools settle with the week-1 carry consumed, and the week
closes with its **own** Skunk. Two governed weeks, two Skunk assessments, two
expiries, trial balance **0**.

---

## 16 · Season-close prerequisite proof

`POST /league/19/season/close` → **409**
`{"reason_code":"pool_rollover","message":"[pool_rollover] 2 Pool occurrence(s) still carry a live rollover.","league_id":19,"final_week":17}`

| # | Prerequisite | Met? |
|---|---|---|
| 1 | `versus_terminal` | ✅ both the Locked and the Final-Locked Dynamic wager settled — **0** pending |
| 2 | `pool_settled` | ✅ all eight occurrences settled |
| 3 | `escrow_resolved` | ✅ **CLEARED BY WP6B** — `open_escrow_accounts()` = `[]` |
| 4/5 | `weekly_minimum_expiry` | ✅ weeks 1 and 2 fully expired |
| 6/7 | `results_not_ready` / `skunk_assessed` | ✅ both weeks final and assessed |
| 8 | `pool_rollover` | ❌ **2 occurrences carry a live rollover** |
| 9 | `pool_zero` | — not reached |
| 9b | `provider_conflict` | ✅ none recorded |

**Eight of nine met. WP6 had two failing; WP6D has one.**

### Why `pool_rollover` is a corpus horizon and not a wiring gap

```
w2 slot1 matchups_where_neither_team_threw_an_interception = 300 cents
    [ZERO_ELIGIBLE_CLAIMS] SUBJECT-layer zero — no matchup qualified;
    sweeps at season_final_week 17; 6 governed claim(s) were submitted
w2 slot2 matchups_with_zero_total_turnovers = 300 cents
    [ZERO_ELIGIBLE_CLAIMS] SUBJECT-layer zero — no matchup qualified;
    sweeps at season_final_week 17; 6 governed claim(s) were submitted
```

Three facts, each asserted:

1. **Both are SUBJECT-layer zeros.** No matchup in the recorded corpus threw zero
   interceptions or committed zero turnovers, in either week.
2. **Both carried a full claim phase.** Six governed claims each, created through
   `POST /pool/pick`. Under WP6's BLOCKER 2 the count would have been zero and
   the classification would have been a zero-winning-**ticket** rollover. It is
   not, and no surviving rollover in this run is of that shape.
3. **The resolution is the final week.** POR §5 sweeps a carried pot to
   Championship at `season_final_week`, which is **17** for this league — a value
   stated by the provider payload and reconciled without conflict. The recorded
   corpus covers weeks 1 and 2.

A live league reaches week 17, the pots sweep, `pool_rollover` and `pool_zero`
clear, and the close proceeds. This run cannot reach week 17 because the corpus
does not record it, and this package did **not** manufacture one — see §21.

---

## 17 · Championship 60/30/10, Skunk season reconciliation, expired-minimum reconciliation, final Current Settle

**NOT REACHED.** All four are steps of `close_season_economy`, which never runs
because `verify_preconditions` refuses first.

Their engines remain certified by `test_s5_p3_season_close_pg.py`; their **wiring
through the production route** — including Championship 60/30/10 — remains
certified by `test_wp3_season_close_pg.py`; and `POST /league/19/season/close`
returning **200 on this very league** is certified by
`test_wp6b_blocker_cleared_pg.py`, which drives the same league with no Pool
collection and therefore no carry. All three were green in this run's regression
gate. What WP6D cannot certify is those steps **in the same run as a Pool
lifecycle**, and it does not claim to.

---

## 18 · Retry / idempotency proof

| Action | Repeat behaviour | Economic movement |
|---|---|---|
| season allocation | 200 `created=false` | none |
| Week Open | 200 `already_open=true` | none |
| Pool collection | **409 ALREADY_COLLECTED** | none |
| Pool settlement | 200, every entry `replayed=true` | none |
| Versus settlement | 200 `already_settled=true` | none |
| Week Close | 200 `already_closed=true`, `skunk.replayed=true` | none — receivable, pot and expiry all unchanged; still one assessment event |
| Final Lock worker | second sweep returns `REPLAYED` (claim mutex + TTL recovery) | none |
| Pool pick | resubmission **replaces in place** — one row per GM per occurrence, held by `uq_pool_claim_instance_gm` | none |
| Season Close | **409 again**, same reason code | none |

---

## 19 · Trial-balance proof

`ledger.trial_balance() == 0` at **every** checkpoint: at open; after issuance;
after Week Open; after Pool collection; after the claim phase; after Pool
settlement; after Week Close; after the whole Versus negotiation; after Final
Lock; after week-2 settlement and close; after the refused Season Close; and at
the end of the run with two leagues present.

No GM holds a negative wallet or a negative Weekly Minimum reserve at any point.
No GM's Championship Reserve (8000) was touched by weekly play.

---

## 20 · League-isolation proof

A foreign commissioner is refused **403** on all four: close this league's week,
collect its Pools, close its season, read its accounting. This league's
economics never touched the other — `skunk:{other}` = 0, `pool:{other}` = 0,
`wallet:{other team}` = 0 — and every economy event is league-scoped (**0**
foreign events). Trial balance still **0** with two leagues present.

---

## 21 · Remaining end-to-end blocker, and what would clear it

**One, and it is a certification-fixture gap:** the recorded WP2B-C corpus covers
weeks 1–2 while the league's own `season_final_week` is 17, so POR §5's
final-week rollover sweep — the governed resolution of a carried pot — cannot be
reached, and `pool_rollover` refuses the close.

**Three repairs were considered and rejected**, each because it would have
manufactured a green run rather than earned one:

1. **Set the league's `season_final_week` to 2.** The provider payload states
   `end_week 17`; `_reconcile_boundary` would record a `FROZEN_BOUNDARY`
   conflict, and §9b would then block the close on the conflict instead — trading
   one refusal for another and inventing a disagreement with the provider.
2. **Change the corpus's `end_week` to 2.** The `yahoo_wp2bc_league` payload is
   shared with WP2B-C, WP2B-D and the Sprint 6 certification, and WP2B-C's
   rollover/continuation assertions depend on week 2 **not** being the final
   week. It would break accepted suites to make this one pass.
3. **Write week-17 `Matchup` rows directly.** That is fabricating provider
   results outside the gateway — the exact substitution this suite exists to
   refuse.

**What would clear it** is a corpus that records the league's final week:
a league payload with `current_week=17` (so the §6 ingestion horizon admits it),
a week-17 scoreboard and six week-17 rosters with stat lines, authored through
`providers/fixtures/build_wp2bc_corpus.py` and served by the same transport seam.
The lifecycle would then run Week Open 17 → Pool collect 17 → claims → ingest →
settle 17 (the carried pots sweep to Championship at the final week) → Week Close
17 → Season Close, reaching Championship 60/30/10 and the final reconciliation
through the production route.

That is **new synthetic-fixture authoring**, including postseason-phase Pool
eligibility decisions (week 17 is ≥ `playoff_start_week` 15, so its fresh draws
come from POR §8's postseason subset). It is a design decision belonging to the
corpus, not a certification action, and WP6D's scope fence forbids starting it
unasked. It is recommended as the next package.

**No other end-to-end blocker remains.** No certified-but-unwired capability
remains: both of WP6's are wired, and this run exercised each through its
production surface.

---

## 22 · UI-operability proof

| Suite | What it drives | Result |
|---|---|---|
| `test_wp6c_pool_claim_browser.py` | headless Chrome: the Pool claim command posts the governed body from the real shell | PASS |
| `test_s7_full_ui_certification.py` | the S7 package, five tabs | PASS |
| `test_s8_p4c5_integration.py` | five tabs × 375/390/430 viewports | PASS |
| `test_s8_p4c4_pool_pick_browser.py` | the Pool pick control | PASS |
| `test_s8_p4c2_action_browser.py` | seven Action states | PASS |
| `test_s8_p4c3_provider_browser.py` | bound + pending provider | PASS |
| `test_s8_p4b3r_browser.py` | settings + Pool slate | PASS |
| `test_wp4_commissioner_lifecycle_ui.py` | the commissioner lifecycle UI | PASS |
| `test_wp6a_skunk_ui.py` | Skunk of the Week surface | PASS |

---

## 23 · Files changed

| File | Change |
|---|---|
| `test_wp6_end_to_end_lifecycle_pg.py` | the two stale blocker sections retired and replaced; production Pool claim phase in weeks 1 and 2; production Final-Lock worker run; season-close prerequisite attribution; `LOCK_SEASON` kickoff bootstrap |
| `WP6D_END_TO_END_LIFECYCLE_REPORT.md` | this report (new) |

No production code was changed by WP6D. The certification is a read of the
product as WP6B and WP6C left it.
