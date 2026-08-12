# WP6 — Final End-to-End Product Lifecycle Certification

**Branch** `postmvp/wired-product-reconciliation`
**Baseline** `882e8a566942fa9e9de7fe6c9b8ec0a9bd7dc1a1` (WP6A, accepted)
**Certified S8 tag** `core-mvp-certified-s8` → `5613e4a31f2b6e4d79c417024155ec357c914456`
**Suite** `test_wp6_end_to_end_lifecycle_pg.py` — 151 assertions, all PASS, exit 0

---

## 0 · The answer, first

**NO — BLOCKED AT lifecycle step 14 (Dynamic mode / Final Lock): `economy.dynamic_challenge.run_final_lock` has no production caller — no route, no scheduler, no worker — so a Dynamic wager that the product itself lets a GM issue and handshake can never be priced. Both sides' Credits stay in `escrow:challenge:{id}:anchor` and `:derived` permanently, and `POST /league/{id}/season/close` is refused at prerequisite `escrow_resolved` forever.**

A second, independent certified-but-unwired blocker was found at **step 19**: `betting.pool_claims.submit_claim` also has no production caller, and the Pool pick control the UI actually posts (`POST /pool/pick`) writes the *legacy* prediction model that the Rev1.3 settlement engine never reads. No GM can hold a winning Pool ticket through the product.

Everything else in the 38-step lifecycle was driven successfully through production routes and is reported below.

---

## 1 · Synthetic league / session topology

| | |
|---|---|
| League | `WP2B-C Economic Proof League`, internal id **19**, season **2025** |
| Provider identity | **`999.l.100001`** — publication-safe, reserved-range, synthetic |
| Teams | **6** (`999.l.100001.t.1` … `.t.6` → internal 1–6) |
| Weeks with provider data | **1** and **2**, three matchups each |
| `season_final_week` / `playoff_start_week` | 17 / 15 (as the corpus payload declares) |
| Commissioner | `wp6-comm@x.test`, team 1, `LeagueCommissioner(source=bootstrap)` |
| GMs | `wp6-gm2@x.test` … `wp6-gm6@x.test`, teams 2–6 |
| Isolation league | second league + commissioner, used only for §16 |

No real Yahoo league, team or player identifier appears anywhere. §0 asserts this
over the raw fixture **bytes**, not the parsed payload, and re-verifies every
payload's SHA-256 against its manifest (17 fixtures, all `provenance: SYNTHETIC`).

Six teams exercise weekly head-to-head matchups, Versus, Pools, Skunk and the
Championship split, and match the existing WP2B-C certification corpus exactly as
the brief preferred.

---

## 2 · Bootstrap actions that were FIXTURE-ONLY

Each exists because the product exposes no self-serve path for it in this
baseline. Every one is labelled `FIXTURE-ONLY` in the suite source.

| # | Action | Why no product path |
|---|---|---|
| 1 | Create the `League` row | No league-creation route. RUNBOOK §6.3 records commissioner onboarding + Yahoo import as known post-MVP scope. |
| 2 | Create six `Team` rows and their `Wallet` rows | Same — created by league import, which does not exist yet. |
| 3 | Bind provider league/team identity (`bind_league_identity`, `bind_team_identity`) | No OAuth authorization flow, so no import can bind identity. |
| 4 | Seed `Player` / `Roster` / `Projection` rows | The odds model reads Roster + Projection. The provider corpus carries provider-side roster entries and stat lines — a different table for a different purpose. No route ingests projections. |
| 5 | Create `User` accounts | `/auth/register` requires an email matching an existing team, which requires (1)–(2) first. |
| 6 | Create the FIRST `LeagueCommissioner` row | `POST /league/{id}/commissioners` requires an existing league commissioner. The first one is a genesis problem with no product answer. |
| 7 | Re-stamp the Pool readiness `measured_at` to now | The corpus observes at a frozen 2025 instant; gate 2 fails closed beyond 24 h. **The suite proves the gate is fail-closed at the frozen instant first** (`eligible_this_phase == 0`, `sufficient_for_slate == false`) and only then supplies the `measured_at` a live provider would have supplied. No gate rule is changed. |
| 8 | Ingest the week-2 **NOT_FINAL** scoreboard via `refresh_league_week` | The product has no action that makes a result non-final — a real league has simply not finished playing. The corpus carries the state as a named payload whose **scores are identical** to the final one, so a score-watching implementation could not pass the §13 negative. |

**The only substitution in the whole run** is the transport:
`providers.yahoo.transport.YahooLiveTransport` is replaced by a subclass of
`FixtureTransport` (carrying the real `league_number` classmethod, which is pure
string parsing). One seam serves the Pool activation route, the Pool settlement
route and `notifications.tuesday_sync` alike. Routes, authorization, assembly,
identity resolution, stat source, census, engines and ledger are all production.

Nothing else was set up directly in the database, and **no engine was called to
substitute for a missing production entry point.** The two places where that
would have been required are reported as blockers instead.

---

## 3 · Lifecycle sequence followed

```
§2   season-opening allocation                    POST /league/19/season-allocation
§3   Pool catalog + measured provider support     scripts/bootstrap_pool_catalog · POST /league/19/pool/activate?week=1
§4   Week 1 Open                                  POST /league/19/week/1/open
§5   Week 1 Pool collection                       POST /league/19/pool/collect/1
§6   governed Pool claim                          ── BLOCKER 2 ── (+ engine demonstration)
§7   week 1 results ingested                      POST /admin/tuesday-sync {week:1}
§8   Week 1 Pool settlement                       POST /league/19/pool/settle/1
§9   Week 1 Close (Skunk + expiry)                POST /league/19/week/1/close
§10  Ledger + The Week reads                      GET  ledger/*, week/1/matchups, week/1/skunk, pool/slate/1, action/me
§11  Week 2 Open + Versus locked lifecycle        POST /league/19/week/2/open · /beef/challenge · /beef/counter · /beef/respond
§12  Dynamic issue + Handshake                    POST /beef/challenge · /beef/respond   ── BLOCKER 1 ──
§13  Week 2 Pool collection + finality negative   POST /league/19/pool/collect/2 · pool/settle/2 · week/2/close
§14  Week 2 results, settlement, close            POST /admin/tuesday-sync {week:2} · settle/2 · pool/settle/2 · week/2/close
§15  Season Close                                 POST /league/19/season/close        ── REFUSED ──
§16  invariants + league isolation
```

---

## 4 · Production route / UI action used for every lifecycle step

| # | Lifecycle capability | Surface | Actor | Result |
|---|---|---|---|---|
| 1 | league exists / setup complete | fixture (no route) | — | seeded |
| 2 | users and fantasy teams exist | fixture (no route) | — | seeded |
| 3 | commissioner authority exists | `GET /auth/me` | commissioner | 200 |
| 4 | season-opening allocation runs | `POST /league/19/season-allocation` | commissioner | 200 `created=true` |
| 5 | opening economy is exactly 0 / 140 / 80 / 220 | same | commissioner | proven, §5 below |
| 6 | Pool catalog/runtime definitions available | `scripts/bootstrap_pool_catalog` (deployment action) | operator | 80 definitions |
| 7 | provider support measured / Pool ready | `POST /league/19/pool/activate?week=1` | commissioner | 200, 12 ready |
| 8 | Week Open succeeds | `POST /league/19/week/1/open` | commissioner | 200 |
| 9 | weekly minimum released | same | commissioner | 6 × 1000 cents |
| 10 | GM creates a Versus challenge | `POST /beef/challenge` | GM (team 2) | 201 |
| 11 | counter/response lifecycle | `POST /beef/counter` | GM (team 3) | 200 |
| 12 | challenge acceptance | `POST /beef/respond` | GM (team 2) | 200 |
| 13 | escrow/funding state correct | same | GM | per-bet escrow 300/300 |
| **14** | **Dynamic mode / Final Lock** | **NONE** | **—** | **BLOCKED** |
| 15 | weekly Pool collection | `POST /league/19/pool/collect/{1,2}` | commissioner | 200 |
| 16 | Yahoo roster/player-stat read via provider path | `POST /admin/tuesday-sync` | commissioner | 200 |
| 17 | finality governed by persisted `finalized_at` | same + `betting/finality_gate` | commissioner | proven |
| 18 | Versus settlement | `POST /admin/tuesday-sync` step `settle_bets`; `POST /league/19/settle/2` | commissioner | 200 |
| **19** | **Pool winner settlement** | **NONE for the claim; `/pool/pick` writes the legacy model** | **GM** | **BLOCKED** |
| 20 | zero-winner / rollover not regressed | `POST /league/19/pool/settle/{1,2}` | commissioner | 200 |
| 21 | Week Close runs | `POST /league/19/week/{1,2}/close` | commissioner | 200 |
| 22 | Skunk assessed automatically in Week Close | same | commissioner | `assessed=true` |
| 23 | exact Skunk team/opponent/score/margin available | same + `GET /league/19/week/1/skunk` | commissioner, GM | exact |
| 24 | $10 Skunk posts exactly once | same | commissioner | 1000 cents, 1 event |
| 25 | unused Weekly Minimum expires | same | commissioner | `min:{t}:1 → 0` |
| 26 | Ledger reflects the week | `GET /league/19/ledger/{me,positions,reconciliation}` | commissioner, GM | 200, reconciles |
| 27 | The Week reflects Yahoo / Bets / Pools / SKUNK | `GET week/1/matchups`, `week/1/skunk`, `pool/slate/1`, `action/me` | GM | 200 |
| 28 | repeat Week Close moves nothing | `POST .../week/1/close` again | commissioner | `already_closed=true` |
| 29 | advance to another governed week | week 2, full cycle | commissioner + GMs | 200 |
| 30 | season-close prerequisites | `verify_preconditions` via the route | commissioner | 8 of 9 met |
| 31 | Season Close succeeds | `POST /league/19/season/close` | commissioner | **409 `escrow_resolved`** |
| 32–35 | Skunk season reconciliation, Championship 60/30/10, expired-minimum reconciliation, Current Settle | same route | commissioner | **NOT REACHED** |
| 36 | trial balance = 0 | ledger invariant | — | 0 throughout |
| 37 | repeat Season Close safe | `POST .../season/close` again | commissioner | 409, zero mutation |
| 38 | final state league-scoped and consistent | §16 | — | proven |

---

## 5 · Opening 220-Credit proof

`POST /league/19/season-allocation` → 200, `created=true`:

```json
{"league_id":19,"season":2026,"team_ids":[1,2,3,4,5,6],
 "buyin_cents":22000,"min_reserve_cents":14000,"reserve_cents":8000,
 "total_buyin_cents":132000,"created":true}
```

Read back off the ledger, per GM, all six identical:

| Account | Cents | Credits |
|---|---|---|
| `wallet:{team}` | **0** | 0 |
| `min_reserve:{team}` | **14000** | 140 |
| `reserve:{team}` | **8000** | 80 |
| total obligation | **22000** | **220** |

140 + 80 = 220 asserted as arithmetic, not restated. Trial balance 0.
Retry: `created=false`, reserves unchanged — **no duplicate issuance.**

---

## 6 · Weekly minimum proof

`POST /league/19/week/1/open` → 200, `total_released_cents = 6000`
(6 GMs × 1000 cents = one governed week of the 14-week, 14000-cent reserve).

- `min:{team}:1` = 1000 for every GM (spendable)
- `min_reserve:{team}` = 13000 for every GM (fell by exactly what was released)
- Duplicate Week Open → 200 `already_open=true`, nothing released twice.

---

## 7 · Versus proposal / acceptance / escrow proof

Week 2, team 2 vs team 3, `straight`, locked mode.

| Step | Surface | Effect |
|---|---|---|
| issue $2.00 | `POST /beef/challenge` | `escrow:challenge:1` = **200**, sourced from `min:2:2` (1000 → 800) |
| counter $3.00 | `POST /beef/counter` | escrow still **200** — **a counter moves no money** (Spec 2 §10) |
| counterer tries to accept | `POST /beef/respond` | **403** — a counter hands the decision back to the issuer |
| issuer accepts | `POST /beef/respond` | `escrow:1` = **300**, `escrow:2` = **300**; `escrow:challenge:1` = **0** (fully migrated, not double-counted); two `Bet` rows `pending` |

No GM went negative. Trial balance 0 across the whole negotiation.

---

## 8 · Dynamic / Final Lock proof — **BLOCKER 1**

Team 4 vs team 5, `straight`, **dynamic** mode, anchor $1.00.

- `POST /beef/challenge` → **201**. The mode is not an internal setting: the UI's
  own command layer exports `MODE_DYNAMIC` and sends `challenge_mode`
  (`web/js/action-command.js`, `web/js/wager-model.js`), and the composer offers it.
- `POST /beef/respond` → **200**, `detail: "dynamic handshake: both ceilings funded"`.
  - `escrow:challenge:2:anchor` = **100** (exactly the anchor stake)
  - `escrow:challenge:2:derived` = **620** (exactly the reported `opponent_ceiling_cents`)
  - **0 `Bet` rows** — correct: the Derived side is priced at Final Lock.

Then the lifecycle stops:

```
routes matching final|lock|dynamic ............ []
run_final_lock exists and is certified ........ yes (test_p3_d2_dynamic_final_lock_pg.py)
non-test callers of run_final_lock /
  acquire_final_lock_claim .................... []      (whole-repo walk, §12)
cents stranded on challenge 2 ................. 720
season-close prerequisite reached ............. escrow_resolved (REFUSED)
```

**Why this suite does not simply add a route.** `SIMULATION_ENGINE_MODULE_SPEC_Rev9`
fixes the actor class:

> **Actor class.** The same scheduled system worker/process class that acquires
> fresh claims. Not an end user, not a GM, not a commissioner, **not reachable
> from any HTTP route.** Final Lock is machine-triggered at kickoff; a human
> "retry" button would be a second admission path into the money path and there
> is no product requirement for one.

and the trigger:

> A single scheduled event, fired at the challenge's earliest covered kickoff
> (`_nfl_lock_time` / per-challenge kickoff already computed in `beef_engine`).

The missing production surface is therefore a **kickoff-time scheduled trigger**,
not an endpoint. Adding an HTTP route would violate the governing spec and open
the second admission path it exists to forbid. Building the scheduler is new
infrastructure, outside a certification package and outside WP6's stated scope.
**The blocker is reported, not patched.**

The engine itself is not in question — `test_p3_d2_dynamic_final_lock_pg.py`
certifies it, and this run leaves the trial balance at 0: the Credits are
**stranded, not lost.**

---

## 9 · Pool collection proof

`POST /league/19/pool/collect/1` → 200:

```json
{"weekly_entry_cents":100,"teams_charged":6,"total_cents":600,
 "per_pool_share_cents":150,"remainder_to_championship_cents":0,
 "rotation_cycle":1,"instance_ids":[1,2,3,4]}
```

Six GMs charged exactly once at the governed 100-cent entry; four occurrences
opened and funded evenly; `pool:19` = 600.
Duplicate collection → **409 `ALREADY_COLLECTED`**, `pool:19` unchanged.
Week 2 collection succeeded only because week 1 was fully settled — the engine's
own `PRIOR_WEEK_UNSETTLED` guard, observed live.

---

## 10 · Yahoo provider / stat proof

`POST /admin/tuesday-sync {league_id:19, week:1}` → 200. Step `refresh_scores`:

> week 1: 3 matchup(s) refreshed through the provider gateway — 3 inserted,
> 0 updated, 0 unchanged, **3 newly final**; full slate, all provider identities
> resolved

- Three `Matchup` rows persisted, every one carrying a real `finalized_at`.
- Pool settlement independently rebuilds the week's provider snapshot with
  rosters (`fetch_week_snapshot(..., with_rosters=True)` → `bind_pool_stat_source`
  → `YahooProviderStatSource`) and the census evaluates real per-player stats —
  that is how §8's `most_passing_yards` produced a genuine extremum winner.

**Three sync steps fail closed offline, and are named rather than hidden:**
`sync_players` and `capture_roster_slots` build their own live Yahoo query and
refuse without credentials (the documented RUNBOOK §4.5 condition — they refuse
rather than inventing data); `apply_topups` refuses on the accepted B6
issuance-ledger grounds. None is on the economic path this lifecycle needs, and
the suite asserts the failing set is exactly those three.

---

## 11 · Finality-negative proof

Week 2, fixtures published, **no game final**, both Pools and the close attempted:

| Attempt | Result |
|---|---|
| `POST /league/19/pool/settle/2` | **409** `RESULTS_NOT_READY`, naming all **3** unfinalized matchup ids |
| `POST /league/19/week/2/close` | **409** `RESULTS_NOT_READY` |

Zero mutation, checked on four independent axes:

- `pool:19` unchanged
- no wallet moved
- **no weekly minimum expired** — `min:{t}:2` unchanged, `expired_min:{t}` unchanged, so the week is not *partly* closed
- trial balance unchanged at 0

The week-2 pending payload carries **identical scores** to the final one, so this
negative cannot be passed by an implementation that watches scores instead of
`finalized_at`.

---

## 12 · Versus settlement proof

`POST /admin/tuesday-sync {week:2}` step `settle_bets` → success.

- Both legs of the accepted wager reached a terminal state (`won`/`lost`).
- `escrow:challenge:1`, `escrow:{anchor_bet}` and `escrow:{derived_bet}` all
  drained to **0** — nothing stranded.
- No GM holds a negative balance.
- Retry through the explicit commissioner route `POST /league/19/settle/2` →
  200 `already_settled=true`, **every wallet byte-identical.**

---

## 13 · Pool settlement proof — and **BLOCKER 2**

### 13.1 The blocker

| Observation | Result |
|---|---|
| `POST /pool/pick` (the endpoint the UI's pick control posts to — `web/tests/p4c4_pool_pick_browser.mjs`) | **200** |
| `PoolClaim` rows written by it | **0** |
| governed claim routes mounted | **none** — `['/pool/pick']` is the only pick surface |
| non-test callers of `betting.pool_claims.submit_claim` | **none** |

`/pool/pick` writes the **legacy** prediction model (`betting/pool_engine.submit_pool_pick`).
The Rev1.3 settlement engine resolves winners from `PoolClaim` via
`claims_for_instance`. The two never meet, so through the product every governed
occurrence resolves with **zero winning tickets** and rolls over instead of
paying. Lifecycle step 19 is unreachable.

WP2B-C already recorded the gap in its own source — *"NO HTTP ROUTE EXPOSES CLAIM
SUBMISSION YET … it is the same function any future route would call"* — and WP6
is the run that shows what it costs end to end.

### 13.2 The engine is sound (labelled ENGINE DEMONSTRATION, not a lifecycle pass)

With four claims submitted through the certified path directly, the **same
production settlement route** paid a real winner:

```json
{"definition_key":"most_passing_yards","classification":"CLAIMS_PRESENT",
 "winning_team_ids":[2,3,4,5],"pot_cents":150,"distributed_cents":150,
 "rolled_over_cents":0,"swept_to_championship_cents":0}
```

Exact §6.3 even split, pot conserved to the cent. The defect is the **admission
path**, not the engine.

### 13.3 Retry

Duplicate `POST /league/19/pool/settle/1` → 200 with every occurrence
`replayed=true`, every wallet unchanged — **no duplicate Pool payout.**

---

## 14 · Zero-winner / rollover regression result

**Not regressed.** Week 1 `matchups_with_zero_total_turnovers`:

```json
{"classification":"ZERO_ELIGIBLE_CLAIMS","winning_team_ids":[],
 "pot_cents":150,"distributed_cents":0,"rolled_over_cents":150}
```

A genuine **subject-layer** zero — no matchup satisfied the predicate — rolled
over rather than paying anyone. No occurrence paid more than its pot. The carry
was then followed into week 2 and **consumed as a continuation**: week 2 pots were
`[300, 300, 150, 150]`, the two 300s being a fresh 150 share plus the 150 carry.

---

## 15 · Week Close proof

`POST /league/19/week/1/close` → 200, in one transaction:

- **Skunk assessed automatically** — `assessed=true`, `classification=ASSESSED`.
  There is deliberately no separate "assess Skunk" action, and §0 of the WP6A
  suite already asserts no such route exists.
- Weekly Minimum expired for all six GMs: `min:{t}:1` → 0, moved to
  `expired_min:{t}`, never into a wallet.
- Duplicate close → 200 `already_closed=true`, `skunk.replayed=true`, and
  receivable, Skunk pot and every `expired_min` byte-identical.

---

## 16 · Skunk selection + exact point differential + $10 proof

| Field | Value |
|---|---|
| skunked team | **3** (`WP2BC Team 3`) |
| opponent | **4** (`WP2BC Team 4`) |
| score | **87.0** |
| opponent score | **131.75** |
| **margin** | **44.75** |
| amount | **1000 cents = $10** |

- The worst loss of the week was selected, not the narrower defeat in another game.
- The margin is exact to the cent of a point and equals `131.75 − 87.0`, the two
  scores printed beside it.
- `receivable:{team 3}` = **−1000**; `skunk:{league 19}` = **+1000**.
- No other GM carries a Skunk obligation.
- **Ledger-only** — the Skunk debited no wallet.
- Exactly **one** `SKUNK_ASSESSMENT` event; a duplicate is impossible.
- Two governed weeks produced exactly **two** assessments — one per week.

---

## 17 · Weekly Minimum expiry proof

Week 1 close expired every GM's unspent minimum: `min:{t}:1` → 0 for all six, and
the sum of `expired_min:{t}` equals the close's own `total_expired_cents`. The
expired Credits sit in `expired_min:{team}` awaiting the season-close
reconciliation — which is **not reached**, because Season Close is refused.

---

## 18 · Ledger / The Week proof

| Read | Result |
|---|---|
| `GET /league/19/ledger/positions` | 200, six GM positions |
| `GET /league/19/ledger/reconciliation` | 200, **`reconciles: true`** — aggregate assets − obligations, the sum of GMs' own Current Settle, and the aggregate Current Settle all agree |
| `GET /league/19/ledger/me` (GM) | 200, carries the GM's own `expired_min_cents` |
| `GET /league/19/week/1/matchups` (GM) | 200, three matchups, all `final: true` |
| `GET /league/19/week/1/skunk` (GM) | 200, team 3, margin 44.75, 1000 cents — identical to what the close reported |
| `GET /league/19/pool/slate/1` (GM) | 200, all four occurrences `settled: true` |
| `GET /league/19/action/me` (GM) | 200 |
| `GET /league/19/lifecycle` | 200, current week `opened`, `closed`, `skunk_assessed` all true |

SKUNK OF THE WEEK is readable by an ordinary GM, and the browser never decides
who was skunked — WP6A's UI suite asserts the client computes no margin and runs
no comparison.

---

## 19 · Second-week continuation proof

Week 2 ran the whole cycle again through the same routes: Open (6000 released) →
Versus issue/counter/accept → Dynamic issue/handshake → Pool collection →
finality refusal → provider ingest → Versus settlement → Pool settlement
(consuming week 1's carry) → Close (its own Skunk, its own expiry).

Two governed weeks, two Skunk assessments, trial balance 0. The lifecycle
**continues**; it does not merely close one isolated week.

---

## 20 · Season-close prerequisite proof

`POST /league/19/season/close` → **409**:

```json
{"reason_code":"escrow_resolved",
 "message":"[escrow_resolved] unresolved escrow: [('escrow:challenge:2:anchor', 100), ('escrow:challenge:2:derived', 620)]",
 "league_id":19,"final_week":17}
```

Prerequisite state at the end of the run:

| # | Step | Met? |
|---|---|---|
| 1 | `versus_terminal` | ✅ both legs settled |
| 2 | `pool_settled` | ✅ all eight occurrences settled |
| 3 | `escrow_resolved` | ❌ **720 cents stranded by BLOCKER 1** |
| 4/5 | `weekly_minimum_expiry` | ✅ weeks 1 and 2 fully expired |
| 6/7 | `results_not_ready` / `skunk_assessed` | ✅ both weeks final and assessed |
| 8 | `pool_rollover` | ❌ 2 occurrences carry live rollover — **see below** |
| 9 | `pool_zero` | — not reached |
| 9b | `provider_conflict` | ✅ none recorded |

**`pool_rollover` is NOT a blocker consequence, and the report does not claim it
is.** The suite attributes each surviving rollover:

```
w2 slot1 matchups_where_neither_team_threw_an_interception = 300 cents [ZERO_ELIGIBLE_CLAIMS]
w2 slot2 matchups_with_zero_total_turnovers                = 300 cents [ZERO_ELIGIBLE_CLAIMS]
```

Both are **subject-layer** zeros — no matchup satisfied the predicate — so no GM
claim could have changed them and BLOCKER 2 is not their cause. Such a pot rolls
forward to `season_final_week` and sweeps to Championship under POR §5. This
league's final week is **17**; a two-week certification fixture never reaches it.
That is a property of the fixture, not a defect.

**The blocker that actually stops the lifecycle is `escrow_resolved`.**

---

## 21–24 · Championship 60/30/10, Skunk season reconciliation, expired-minimum reconciliation, Current Settle

**NOT REACHED.** All four are steps of `close_season_economy`, which never runs
because `verify_preconditions` refuses first. Their engines remain certified by
`test_s5_p3_season_close_pg.py` and their wiring by `test_wp3_season_close_pg.py`
(both green in this run's regression gate), but WP6 cannot certify them
**through the running product**, and does not claim to.

---

## 25 · Retry / idempotency proof

| Action | Repeat behaviour | Economic movement |
|---|---|---|
| season allocation | 200 `created=false` | none |
| Week Open | 200 `already_open=true` | none |
| Pool collection | **409 `ALREADY_COLLECTED`** | none |
| Pool settlement | 200, every occurrence `replayed=true` | none |
| Versus settlement | 200 `already_settled=true` | none |
| Week Close | 200 `already_closed=true`, `skunk.replayed=true` | none |
| Skunk | duplicate structurally impossible (deterministic league-week event key) | 1 event, always |
| Season Close | 409 again, same reason | none |
| settlement before finality | 409 `RESULTS_NOT_READY` | **zero mutation on all four axes** |

No failure left partially committed economic state anywhere in the run.

---

## 26 · Trial-balance proof

`ledger.trial_balance() == 0` asserted **after every economically material stage**:
issuance, Week Open, each negotiation step, the Dynamic handshake, collection,
each settlement, each close, every refusal, and finally with two leagues present.
It never left zero — including while 720 cents sit stranded, which is what makes
"stranded, not lost" a measured claim rather than a reassurance.

Also proven throughout: no negative wallet, no negative Weekly Minimum reserve,
no GM's Championship Reserve touched by weekly play, and exactly two weeks of
reserve consumed by two governed weeks (`min_reserve` 14000 → 12000 for all six).

---

## 27 · League-isolation proof

A second league with its own commissioner was created, and that commissioner was
refused on every league-scoped surface of league 19:

| Attempt | Result |
|---|---|
| `POST /league/19/week/1/close` | 403 |
| `POST /league/19/pool/collect/1` | 403 |
| `POST /league/19/season/close` | 403 |
| `GET /league/19/ledger/reconciliation` | 403 |

And league 19's economics never touched the other: its Skunk pot, Pool account
and wallet are all 0, and it carries **0** economy events against league 19's
many. Trial balance still 0 with both leagues present.

---

## 28 · UI-operability proof

Not a new UI certification — the existing suites were re-run and are green.

`web/js/lifecycle-model.js` exports exactly the six controls the brief names:

```js
export const LIFECYCLE_ACTIONS = Object.freeze([
  'pool-support', 'week-open', 'pool-collect', 'pool-settle', 'week-close',
  'season-close',
]);
```

| Suite | Result |
|---|---|
| `test_wp4_commissioner_lifecycle_ui.py` | **PASS** — all six controls; 17/17 governed reason codes translated into sentences, none echoed raw; `RESULTS_NOT_READY` classified as WAITING rather than a refusal; commissioner browser 56 PASS / 0 FAIL; non-commissioner browser 31 PASS / 0 FAIL |
| `test_wp6a_skunk_ui.py` | **PASS** — Skunk drawn in The Week from served data; the client computes no margin and runs no comparison; GM browser 44 PASS / 0 FAIL |

So the commissioner can operate Pool support measurement, Week Open, Pool
collection, Pool settlement, Week Close and Season Close from the authenticated
UI without direct API calls, and Skunk is automatically included in Week Close
and displayed in The Week.

**No new controls were added.** The run did not prove one was required: the two
missing capabilities are a *scheduled trigger* (BLOCKER 1, which the spec forbids
exposing as a control at all) and a *governed claim route* (BLOCKER 2, whose
repair is a decision for the owner, not for a certification package).

---

## 29 · Regression counts

All re-run in this session, against PostgreSQL 16.14 in a disposable container.

| Gate | Command | Result |
|---|---|---|
| **PostgreSQL suite runner** (WP1–WP6A, B6, S4–S8, Spec 1/2, FR-8.7, pool engine/economy, season close — one fresh database each) | `python run_pg_suites.py` | **54 / 54 PASS** |
| — including the new WP6 suite, picked up by the runner's own `test_*_pg.py` glob | `test_wp6_end_to_end_lifecycle_pg.py` | **PASS** (80.9 s) |
| — including season close | `test_s5_p3_season_close_pg.py`, `test_wp3_season_close_pg.py`, `test_b6_group_d_season_close_pg.py` | **PASS** |
| — including pool engine/economy | `test_s4_pool_money_path_pg.py`, `test_s4_pool_idempotency_pg.py`, `test_s4_pool_legacy_rollover_pg.py`, `test_s4_p2_lifecycle_pg.py`, `test_s4_p2_season_arc_pg.py`, `test_pool_atomic_claim_pg.py`, `test_pool_rotation_schema_pg.py`, `test_wp2b*` | **PASS** |
| — including Dynamic Final Lock | `test_p3_d2_dynamic_final_lock_pg.py` | **PASS** — the engine is certified; only its caller is missing |
| **S6 provider certification** | `python -m providers.certify.run` | **17 / 17 gates PASS**, 0 FAIL; corpus CAPTURED = 0, SYNTHETIC = 36 |
| **S7 current UI certification** | `test_s7_p1_ui_shell.py`, `test_s7_p2_league_action.py`, `test_s7_p3_week_ledger.py`, `test_s7_p4_rules_commissioner.py`, `test_s7_full_ui_certification.py` | **5 / 5 PASS** |
| **S8 auth / authorization / security** | the seventeen-suite Sprint 8 stack (RUNBOOK §4.5) | **17 / 17 PASS** |
| **Pool engine / catalog units** | `pytest test_s4_pool_engine_unit.py test_s4_pool_catalog_unit.py` | **18 passed** |
| **Node component suites** | `package2` / `package3` / `package4` / `ui_component_tests.mjs` | **4 / 4 PASS** |
| **Commissioner lifecycle UI** | `test_wp4_commissioner_lifecycle_ui.py` | **PASS** (browser 56 P / 0 F commissioner, 31 P / 0 F GM) |
| **Skunk UI** | `test_wp6a_skunk_ui.py` | **PASS** (browser 44 P / 0 F) |

**No unexplained current-product failures.**

The only refusals observed anywhere in the run are the three documented
offline/governed ones inside `POST /admin/tuesday-sync` — `sync_players` and
`capture_roster_slots` (no Yahoo credentials; RUNBOOK §4.5) and `apply_topups`
(the accepted B6 issuance-ledger refusal). The WP6 suite asserts the failing set
is **exactly** those three, so a fourth would fail the gate rather than blend in.

---

## 30 · Files changed

```
A  test_wp6_end_to_end_lifecycle_pg.py     the WP6 certification suite (151 assertions)
A  WP6_END_TO_END_LIFECYCLE_REPORT.md      this report
```

**No production code was changed.** WP6 required none: the run needed no repair
to reach the two blockers, and neither blocker is repairable within this
package's scope (§8, §13.1).

---

## 31 · Commit SHA

```
903ba8a1b28076553ac9f0abf8c9087038485e4b
WP6 — certify end-to-end product lifecycle
```

---

## 32 · Git status

```
branch : postmvp/wired-product-reconciliation
HEAD   : 903ba8a1b28076553ac9f0abf8c9087038485e4b
status : clean (working tree and index)
parent : 882e8a566942fa9e9de7fe6c9b8ec0a9bd7dc1a1  (WP6A, accepted)
pushed : NO — not pushed, as instructed
```

---

## 33 · Certified S8 integrity

```
core-mvp-certified-s8  ->  5613e4a31f2b6e4d79c417024155ec357c914456
```

Unchanged and reachable as an ancestor of this branch. Nothing in WP6 touched it.

---

## 34 · Remaining certified-but-unwired lifecycle capability

| Capability | Certified by | Callers | Consequence |
|---|---|---|---|
| **Dynamic Final Lock** — `economy.dynamic_challenge.run_final_lock`, `acquire_final_lock_claim` | `test_p3_d2_dynamic_final_lock_pg.py` | **none** | A Dynamic wager the UI lets a GM place can never be priced. Both sides' escrow is stranded permanently and Season Close is refused at `escrow_resolved` forever. Needs a **kickoff-time scheduled worker**; Rev 9 forbids an HTTP route. |
| **Governed Pool claim submission** — `betting.pool_claims.submit_claim` | `test_s4_p2_lifecycle_pg.py`, `test_s4_pool_money_path_pg.py`, `test_s4_pool_idempotency_pg.py`, `test_wp2bc_pool_economic_settlement_pg.py` | **none** | No GM can hold a winning Pool ticket. Every occurrence with a real winner resolves as zero-winning-tickets and rolls over. Needs a **governed claim route** beside `GET /league/{id}/pool/slate/{week}`. |
| `economy.dynamic_challenge.informational_refresh` | `test_p3_d2_dynamic_final_lock_pg.py` | none | Non-binding display-only quote between Handshake and Final Lock. No economic effect; not a lifecycle blocker. |

---

## 35 · FINAL ANSWER

**CAN A LEAGUE COMPLETE THE FANTASYSTAKES GAME LIFECYCLE THROUGH THE RUNNING PRODUCT?**

> **NO — BLOCKED AT lifecycle step 14 (Dynamic mode / Final Lock).**
>
> **Exact technical reason:** `economy.dynamic_challenge.run_final_lock` has no
> production caller — no HTTP route, no scheduler, no worker, no management
> command. A Dynamic challenge can be issued (`POST /beef/challenge`,
> `challenge_mode: "dynamic"` — the mode the UI's own command layer offers) and
> handshaken (`POST /beef/respond`), which posts both sides' maximum exposure to
> `escrow:challenge:{id}:anchor` and `escrow:challenge:{id}:derived` and
> deliberately creates no `Bet` rows. Nothing in the product can then run Final
> Lock to price the Derived side, so that escrow is never migrated or refunded.
> `POST /league/{id}/season/close` is refused at prerequisite `escrow_resolved`
> — permanently, with no product path to clear it.
>
> **Second, independent blocker at step 19 (Pool winner settlement):**
> `betting.pool_claims.submit_claim` likewise has no production caller, and the
> Pool pick control the UI posts (`POST /pool/pick`) writes the legacy
> prediction model that the Rev1.3 settlement engine never reads. No GM can hold
> a winning Pool ticket through the product, so every occurrence with a real
> winner rolls over instead of paying.

Both are the WP5 shape exactly — a certified engine with no caller — and both
must be wired before the lifecycle question can be answered green.