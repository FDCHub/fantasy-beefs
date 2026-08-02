# Weekly Pool Rotation — Implementation Scope, Revision 1.3

**Status:** Scope — not authorized for build
**Date:** 2026-08-01
**Product authority:** `spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_3.md`
**Canonical stat vocabulary:** `spec/pool_stat_vocabulary_rev1_0.json`
**Catalog data:** `spec/pool_catalog_rev1_3.json`

**Revision 1.3 is DRAFT. It supersedes Revision 1.2 only on adoption. Revisions 1.0, 1.1 and 1.2 are retained unchanged as historical authority.**

**Correction pass, 2026-08-01.** This copy supersedes the pre-correction Revision 1.3 scope, SHA-256 `DAF6B0D4DB9D44873A27C3392E3E04246C7A785DF6351FE50FFBC528A1BF25B9`. It applies the accepted independent-review findings and the owner kicker and tied-payout-remainder rulings.

**NOTHING IN THIS DOCUMENT AUTHORIZES BUILD.** No migration, no code, no deployment, no production-data change. Every requirement is Stage H work behind the existing review gate.

---

## 0. Authority

Product behavior is governed by the Pool POR. This document specifies how to implement it. Where the two disagree, the POR governs and this document is wrong.

**Current code is implementation evidence, never authority.** Every code reference below is evidence dated 2026-07-30, not an immutable coordinate. Re-grep before building against any line number here.

---

## A. Current state

### A1 — Approved (per POR)

80 active definitions · 44 Team-Level, 36 Matchup · 77 product-enabled, 3 product-blocked · **64 definition-runtime-eligible (a Gate-1 ceiling, not a forecast)**, **0 league-activation-ready**, **0 selectable now** · 13 source-incomplete enabled · 16 rollover-eligible · 2 evaluator families classifying settlement behavior, `RANK_EXTREMUM` 64 and `QUALIFIER` 16 · **8 governed evaluator shapes** defining computation · exactly 4 pools per week · system-selected, auditable · no regular-season repeat within a cycle · fixed postseason 32-subset (list unresolved) · anti-tanking enforced at classification.

### A2 — Implemented

| Finding | Evidence |
|---|---|
| **No weekly slate model exists** | Nothing records which pools ran in which week |
| **`PoolPot` is week-level only** | `db/schema.py:1029` — one row per league/week, `UNIQUE(league_id, week)` |
| **`PoolConfig` has no week column** | `db/schema.py:996`, keyed `league_id` unique — league-scoped, permanent |
| **4 legacy names, 3 working evaluators** | `POOL_BET_TYPES`, `betting/pool_engine.py:57-63` — a Python constant, not a catalog |
| **Settlement hardcodes three shares** | `pool_engine.py:651-654`, `total_cents // 3`, remainder absorbed by Special Teams |
| **Worst Beat rollover is legacy special-case code** | `PoolPot.worst_beat_rollover_cents`; accumulate at `:716`, sweep-forward `:246-259, :317`, week-14 expiry `:705-714`; guard `:562-595` states it must be rewritten if a second type gains rollover |
| **Creation is manual** | Sole writer `PoolPot(...)` at `:316` inside `collect_weekly_entries`, triggered only by `POST /pool/collect` with the week in the request body |
| **No scheduler creates pool slates** | Only job is `notifications/tuesday_sync.py:1593`, twelve steps, zero pool references, and not started by the Procfile or `railway.toml` in production |
| **Collection lacks an atomic claim** | Read-then-write guard `:214-220` against `UNIQUE(league_id, week)` |
| **`bench_burn` acceptance is stale** | Catalog line `:61` only; `_VALID_BET_TYPES` accepts picks, nothing settles them |
| **Lock is shared and correct** | `_nfl_lock_time` `:73-122`, `MIN(NflSchedule.kickoff_utc)`, one moment per week |
| **One dedicated test suite** | `test_pool_engine_conversion.py`, 12 scenarios |

### A3 — Delta

**No Rev1.3 definition is supported by the current settlement engine.** The comparison is against **legacy working evaluators**, not against product-enabled or active counts: the engine carries a small number of hardcoded single-purpose bet evaluators and none is a catalog-driven Pool definition. All 80 active definitions therefore require new engine support, of which 77 are product-enabled, 64 are definition-runtime-eligible and 0 are currently league-activation-ready. **64 is the Gate-1 ceiling. It is not a count that returns on restored provider access.** No catalog table, no slate model, no selection, no rotation cycle, no per-definition rollover, no lineage, no postseason phase, wrong slot divisor.

---

## B. Gap

**No weekly slate model exists.** That is the load-bearing absence. Everything else follows.

The four-name constant, `// 3`, single-column rollover and stale `bench_burn` acceptance are **implementation debt** — replaced, not debated.

The engine work is eight governed evaluator shapes (§C8) plus a settlement loop. Two of the eight — `CLOSED_SUM` and `CLOSED_RATIO` — cover 59 definitions from declarative metadata alone. **No formula is pending:** Revision 1.3 defined #42, #43 and #46 and retired #44, #45, #47 and #88, and all 16 qualifier predicates are structured. The remaining constraints are source and runtime dependencies (§C10), not undefined formulas.

---

## C. Minimal design

### C1 — `pool_definition`

80 rows seeded from `pool_catalog_rev1_3.json`. Columns mirror the JSON keys. **Every one of the 80 active definitions carries the identical field set below.** The two rows that formerly lacked seven of these fields, #97 and #98, are retired and are not seeded.

```
key PK · catalog_number · display_name · category
scope TEAM|MATCHUP · mechanic PREDICTION|RANK
evaluator_family RANK_EXTREMUM|QUALIFIER
evaluator_shape CLOSED_SUM|CLOSED_RATIO|QUALIFIER_PREDICATE|
                PLAYER_EXTREMUM_WITHIN_SUBJECT|SLOT_FILTERED_POINTS_SUM|
                BALANCE_RATIO|DISTINCT_CATEGORY_COUNT|MATCHUP_SCORE_SUM
metric_kind · direction MAX|MIN NULL · metric_expression NULL
governed_definition NULL          -- authoritative for non-CLOSED_* shapes
threshold_condition NULL          -- human-readable only, never evaluated
predicate NULL                    -- structured, evaluated form
predicate_quantifier TEAM|MATCHUP_COMBINED|MATCHUP_EACH NULL
threshold_configurable · threshold_default NULL
required_stats [] NULL            -- canonical vocabulary keys only
required_stats_unresolved_reason NULL
required_stats_resolved BOOL
source_mapping_complete BOOL
unmapped_required_stats [] NULL
starter_slot_rule · slot_filter [] NULL · slot_exclusions [] NULL
self_pick_rule · anti_tanking_review
data_dependency
dependency_state ENABLED|BLOCKED  -- PRODUCT approval
blocked_reason NULL               -- sole canonical product block field
product_complete BOOL             -- mathematically complete w/o commissioner input
definition_runtime_eligible BOOL  -- GATE 1, persistent definition metadata
definition_block_reason NULL
-- GATE 2 is NOT a pool_definition column. See C1.1.
regular_season_eligible · postseason_eligible NULL · rollover_eligible
tie_rule · aggregate_over_aggregate_required · zero_denominator_guard
```

`postseason_eligible` is nullable and stays null until the 32-subset is supplied. A null must be treated as *not yet eligible*, never as false-by-default and never as true.

### C1.1 — Gate 2 carrier (NOT `pool_definition`)

`league_activation_ready` is **transient environment state** and must never be stored on `pool_definition`. Storing a provider outage inside catalog metadata would make a product artifact carry an operational fact with no timestamp and no scope.

Two acceptable treatments; the choice is implementation scope:

**A. Computed dynamically** at selection time from live provider and population checks. No persistence.

**B. A separate readiness carrier**, conceptually:

```
league_id · provider
definition_key OR required_source_set
league_activation_ready BOOL
league_activation_block_reasons []
measured_at TIMESTAMP
```

Either way the selector requires `definition_runtime_eligible AND league_activation_ready`, and a stale measurement must be treated as not-ready rather than as ready.

### C2 — `pool_instance`

```
id · league_id · season · week · phase REGULAR|POSTSEASON · rotation_cycle
definition_key -> pool_definition.key
slot 1..4
pot_cents · rollover_cents
origin_instance_id NULL     -- NULL = fresh draw, set = continuation
settled · settled_at

UNIQUE (league_id, season, week, definition_key)
UNIQUE (league_id, season, week, slot)
UNIQUE (league_id, season, rotation_cycle, definition_key)
   WHERE origin_instance_id IS NULL AND phase = 'REGULAR'
```

The partial index is how the no-repeat invariant is **proved** rather than asserted. An ordering heuristic can be correct on every observed input and still permit a violation; a constraint cannot.

`rotation_cycle` is what makes reset and no-repeat coexist. Without it the index would forbid exactly what the reset rule permits.

### C3 — `pool_rotation_cycle`

One row per cycle open: `league_id, season, rotation_cycle, opened_week, eligible_set_size, opened_at`. Satisfies the POR's auditable-reset requirement.

### C4 — Retained

`PoolPot` stays as the week container — entry collection, lock time, week settled flag. `PoolConfig` unchanged.

### C5 — Evaluator framework

Two functions reading declarative parameters.

`RANK_EXTREMUM(subjects, metric_expression, metric_kind, direction)` — compute one value per subject, return all tied at the extreme. `RATIO` computes `sum(num)/sum(den)`; a present denominator of zero yields an undefined metric and the subject is unevaluable (POR §3.3, §6.2).

`QUALIFIER_PREDICATE(subjects, predicate, predicate_quantifier, threshold_value)` — evaluate the structured `predicate` per subject under the declared `predicate_quantifier`, return all qualifiers.

**`threshold_condition` is human-readable prose and is NEVER evaluated.** It exists for documentation only. The executable form is `predicate`. An evaluator that parses `threshold_condition` is non-conformant.

`predicate_quantifier` selects the frame: `TEAM` against one team's totals, `MATCHUP_COMBINED` against both summed, `MATCHUP_EACH` requiring the condition per participating team. `threshold_value` defaults to `threshold_default` unless overridden.

**An empty qualifier set is a legitimate result only over a fully evaluated field.** Over an incomplete or unevaluable field it is not an outcome and is classified per C6.

Neither function knows any definition by name.

**C5 classifies settlement behavior; it is not the executable shape inventory.** Revision 1.3 governs **eight** evaluator shapes (§C8). `RANK_EXTREMUM` and `QUALIFIER` remain the family axis and determine rollover eligibility and zero-claim interpretation. They do not determine computation.

### C6 — Subject census and classification gate

Implements POR §6.2. Every requirement here is Stage H work behind the existing Opus math review gate. **Nothing in this section authorizes build.**

**Census carrier.** Each evaluator returns a census alongside its result: `subjects_considered`, `subjects_evaluated`, `subjects_claiming`. A bare list is not an acceptable return shape.

**Subject identity.**

```
scope TEAM      -> one league team
scope MATCHUP   -> one scheduled matchup, never its two teams separately
                   evaluable only when both participants are evaluable
```

**`subjects_considered` reads from the authoritative weekly league structure** — teams from the roster of record, matchups from the schedule — **never from the stat source.** A census derived from the stat feed shrinks to match `subjects_evaluated` whenever data are missing, so the gate would pass on a broken week. The two counts must come from independent sources or the control is non-discriminating.

**Full-field evaluability gate.** Classification runs before any claim computation and before any economic work.

```
considered == 0                      -> NO_SUBJECTS
evaluated  == 0                      -> NO_EVALUABLE_SUBJECTS
evaluated  <  considered             -> INCOMPLETE_FIELD
evaluated  == considered, claims 0   -> ZERO_ELIGIBLE_CLAIMS
evaluated  == considered, claims >=1 -> CLAIMS_PRESENT
evaluated  == considered, claims 0,
             family RANK_EXTREMUM    -> INVARIANT_VIOLATION   (precedence)
```

`subjects_claiming` is not computed, stored, or logged unless `evaluated == considered`.

**Fail-closed states are `NO_SUBJECTS`, `NO_EVALUABLE_SUBJECTS`, `INCOMPLETE_FIELD` and `INVARIANT_VIOLATION`.** Each refuses the settlement transaction. For each: no posting, no rollover, no sweep, no `settled` flag, and no surface reporting completion or distribution — not the settlement result, not the feed, not commissioner reconciliation.

**Named domain errors.** Each refusal raises a domain error carrying definition key, league, week, classification and the census counts. `INCOMPLETE_FIELD` additionally carries the unevaluable subject identities. A bare `ValueError` is not acceptable.

**`INVARIANT_VIOLATION` is a distinct error type from the three data conditions.** Its cause is the evaluator, not the data, and it is not resolved by retry. Collapsing it into a data error would leave an operator waiting for data that already arrived.

`ZERO_ELIGIBLE_CLAIMS` is the only zero-claim path into the §E settlement branches.

---

## D. Data model impact

Changes required. New `pool_definition`, `pool_instance`, `pool_rotation_cycle`, the partial index, and migration of live `worst_beat_rollover_cents` into `pool_instance.rollover_cents`.

**The rollover migration moves real money.** A league mid-season carries a live balance on that column. **Opus math review gate.**

---

## E. Weekly lifecycle

```
Week N first kickoff
    lock fires — _nfl_lock_time, MIN kickoff, one shared moment
    picks close on all four instances

Yahoo results final
    settle_pool(N) — loop week N instances:
        census + classification gate (C6) runs first
        NO_SUBJECTS | NO_EVALUABLE_SUBJECTS |
        INCOMPLETE_FIELD | INVARIANT_VIOLATION
                            -> refuse, no posting, no roll, no sweep,
                               instance NOT marked settled
        winners or tie      -> even split per POR 6.3:
                                 base  = pot_cents // winner_count
                                 rem   = pot_cents %  winner_count
                                 order winners by canonical GM ID ASC
                                 every winner gets base
                                 first `rem` winners get one extra cent
                               pot drains, full pot conserved, NO ROLL
                               posting + settled in ONE transaction,
                               keyed WINNER_DISTRIBUTION (G1)
        zero claims, eligible, before season_final_week
                            -> rollover_cents = pot_cents, no posting
        zero claims, eligible, at season_final_week
                            -> sweep championship:{league_id}, zero carry
                               keyed ROLLOVER_EXPIRY_SWEEP (G1)
        zero claims, not eligible
                            -> sweep championship:{league_id}
                               keyed CHAMPIONSHIP_SWEEP (G1)
        mark instance settled  -- SAME transaction as the posting
    PoolPot(N).settled = true

Rollover determination
    no separate pass — a field write inside settlement

Week N+1 slate
    collect_weekly_entries(N+1)
        atomic week claim (G)
        all-prior-weeks-settled guard (existing :228-238)
        build_week_slate(N+1, phase):
            carry   = week N instances with rollover_cents > 0
            slots   = 4 - len(carry)
            pool    = REGULAR ? (eligible - used_in_cycle) - carried_keys
                              : postseason_subset
            if len(pool) < slots and phase = REGULAR:
                rotation_cycle += 1
                write pool_rotation_cycle audit row
                recompute pool
            fresh   = draw(slots) from pool
        write 4 instances — carries first at slots 1..n, fresh after
        collect entries, divide across the four
        remainder -> championship:{league_id}
        PoolPot(N+1).entries_collected = true

Publication
    the slate is published when its four rows exist
```

---

## F. Rollover handling

A continuation takes a slot rather than sitting beside the slate.

One pool rolls: the continuation occupies slot 1 with carried cents already in `pot_cents`, plus this week's share. Three fresh draws fill slots 2–4 from the unused set, so a rollover never causes a repeat.

`origin_instance_id` is the lineage chain. The UI walks it to render *"carried from Week 4"*, satisfying the POR's UI-visibility requirement.

Four rollovers is a valid slate with zero fresh draws.

---

## G. Idempotency and concurrency

The current guard is unsound under contention. Two concurrent `POST /pool/collect` for the same league and week both read `existing = None` at `:215`, both proceed through wallet debits and ledger postings, and one loses at commit. Same transaction so it rolls back — but it surfaces as `IntegrityError`, not the `ValueError` the guard intends.

**The fix already exists in this codebase.** `WeekSettlement` was built on this exact pattern and then given `INSERT ... ON CONFLICT DO NOTHING` at `settlement_engine.py:357`. `PoolPot` never received it.

Claim the week atomically before any economic work. The three `pool_instance` constraints then prevent duplicate instances, duplicate slots, and duplicate fresh draws across a cycle.

No advisory lock. Constraints are the claim.

### G1 — Settlement idempotency, binding

Current state: `settle_pool` has no `FOR UPDATE` on `PoolPot`; idempotency rests on the `pot.settled` flag at `:543-544` plus a balance-keyed reconciliation guard. That is balance-keyed, not event-keyed, and does not prevent a double payout under retry.

**A row lock is not a sufficient substitute for replay safety, and this document does not present it as one.** A lock serializes concurrent attempts inside one process lifetime. It says nothing about a retry that arrives after the lock is released, and nothing about a crash between posting and response. Balance-keyed reconciliation is likewise a supplement: it compares amounts, not events, and two legitimate identical amounts are indistinguishable to it.

**Two requirements govern together, per POR §6.4. Neither replaces the other.**

**1. Atomicity.** Ledger posting and the corresponding `pool_instance.settled` transition occur inside **one** database transaction. A `settled` flag written outside the posting transaction, or a posting committed ahead of the flag, is non-conformant.

**2. Event-keyed idempotency under a database uniqueness constraint.** Every economic settlement or sweep generated by a pool instance carries a stable idempotency key, and a database `UNIQUE` constraint enforces it. Replay after a crash or an ambiguous retry then collides at the constraint and is harmless.

Conceptual key shape:

```
idempotency_key = (pool_instance_id, economic_event_type)

economic_event_type ENUM:
    WINNER_DISTRIBUTION        -- single winner or tie, per POR 6.3
    CHAMPIONSHIP_SWEEP         -- zero claims, not rollover-eligible
    ROLLOVER_EXPIRY_SWEEP      -- zero claims, eligible, at season_final_week

UNIQUE (pool_instance_id, economic_event_type)
```

The key must be **recomputable from the event itself** — never a timestamp, never a random value, never a wall-clock retry counter. One pool instance may produce at most one posting per event type, ever.

The enumeration is sufficient to discriminate the three economic outcomes a single pool instance can generate. A continuation produces no posting at all, so it needs no key. Any future economic posting from a pool instance requires its own enumerated type before it may ship.

**Defence in depth, optional.** A `UNIQUE (league_id, season, rotation_cycle)` constraint on `pool_rotation_cycle` would prevent a duplicate cycle-open audit row. It is recommended, not required, and is not a substitute for either requirement above.

**Implementation is Stage H behind the Opus math review gate. Nothing here authorizes build.**

---

## H. Test plan

Postgres suite, script shape, `_assert` into `_failures`, teardown in `finally`, one file per pytest process. Every scenario asserts trial balance zero.

| # | Scenario | Proves |
|---|---|---|
| 1 | Fresh week, no carry | 4 instances, distinct definitions, slots 1–4, remainder to championship once |
| 2 | One rollover | Continuation slot 1, cents intact, `origin_instance_id` set, 3 fresh, still 4 |
| 3 | Two rollovers | Independent carries, 2 fresh, neither reads the other's balance |
| 4 | Four rollovers | All continuations, zero fresh, no crash, no fifth slot |
| 5 | Repeat attempt | Fresh draw of an already-drawn definition raises on the partial index |
| 6 | Continuation is not a repeat | Same key in a later week with `origin` set is accepted |
| 7 | Cycle boundary | Reset fires only on insufficient fresh set, increments once, writes an audit row |
| 8 | Continuation across a cycle boundary | Carry survives the increment, does not mark used in the new cycle |
| 9 | Carry plus fresh draw of the same key, same week | Refused by the week-level unique |
| 10 | Settlement retry after crash | Re-entry is a no-op, no double credit |
| 10a | Crash before posting | Transaction rolls back whole: no ledger rows, `settled` still false, pot intact, trial balance zero |
| 10b | Crash after posting attempt, before response | Retry collides on the `(pool_instance_id, economic_event_type)` unique constraint. Exactly one set of ledger rows survives, `settled` true, no duplicate payout |
| 10c | Retry after commit | Replaying the identical settlement request produces no second posting and no second `settled` transition |
| 10d | Concurrent settlement attempts | Two settlements of the same instance run at once. One commits, one is refused at the uniqueness constraint. No duplicate payout, no duplicate sweep, no partial posting survives |
| 10e | Row lock alone is insufficient | With the uniqueness constraint removed and only a row lock in place, a post-release retry double-pays. **Discriminating: a lock-only implementation passes 10 and fails here** |
| 10f | No duplicate sweep | A non-rollover championship sweep and a final-week rollover-expiry sweep on the same instance are distinct event types; neither replays, and neither is mistaken for the other |
| 10g | No duplicate continuation | A rollover continuation generates no economic posting; a replayed rollover determination creates no second continuation instance |
| 10h | Atomic posting plus `settled` | A failure injected between posting and the `settled` write leaves neither. **Discriminating: a two-transaction implementation passes 10 and fails here** |
| 11 | Duplicate collection | Concurrent collect: one `PoolPot`, four instances, no partial postings survive |
| 12 | Ties do not roll | Multi-winner settles, `rollover_cents` stays 0 |
| 12a | Tie remainder allocation | `pot_cents` 1000 across 3 winners with canonical GM IDs 4, 9, 21 pays 334 / 333 / 333. The extra cent lands on the lowest canonical GM ID |
| 12b | Remainder ordering key | The same fixture returned in reverse database order, and with display names that sort differently, produces the identical per-GM allocation. **Discriminating: an implementation ordering by query result or display name passes 12a and fails here** |
| 12c | Remainder conservation | Across a sweep of `pot_cents` and `winner_count` combinations, `sum(payouts) == pot_cents` exactly, every time. No cent absorbed, none swept to championship |
| 12d | Remainder determinism under retry | A retried tie settlement reproduces the identical per-GM allocation cent for cent |
| 13 | Final-week expiry with a live carry | Sweeps once at `season_final_week`, carry zeroed, no re-roll |
| 14 | `RANK_EXTREMUM` `MIN` | Fewest-style definitions pick the minimum |
| 15 | Aggregate-over-aggregate | `sum(y)/sum(t)`, never mean of per-player ratios; a fixture where the two disagree |
| 16 | Zero-denominator guard | #41 and #61 shapes fail closed |
| 17 | `QUALIFIER` with zero qualifiers | Rolls if eligible, sweeps if not |
| 18 | Product-blocked excluded | None of the 3 product-blocked definitions (#7, #46, #85) ever enters a slate |
| 18a | Gate 1 excludes source-incomplete | All 13 source-incomplete definitions carry `dependency_state: ENABLED` yet `definition_runtime_eligible: false`, and none enters a slate. Discriminating: a selector filtering on `dependency_state` passes 18 and fails here |
| 18b | Gate 1 alone never suffices | With all 64 gate-1 definitions eligible and `league_activation_ready: false`, the selector draws **zero**. Discriminating: a selector honouring only gate 1 passes 18a and fails here |
| 18c | Provider refusal changes no product status | Under provider refusal, `dependency_state` and `definition_runtime_eligible` are byte-identical to their values under provider availability; only gate 2 differs |
| 18g | Restored access alone does not open the slate | With provider access restored but source population unverified, the selector still draws **zero**. **Discriminating: an implementation treating access restoration as full Gate-2 satisfaction passes 18b and fails here** |
| 18h | Selectable count is measured, not assumed | With provider access restored and a partial Gate-2 pass, the selectable count equals the measured passing set, not 64. No code path hardcodes 64 as a post-access count |
| 18d | Retired numbers unseedable | Seeding rejects catalog numbers 8, 9, 10, 11, 12, 97 and 98; the selector cannot draw them; their numbers and keys are never reassigned |
| 18e | No unbound predicate variable | Every active `predicate` resolves with no free variable. Discriminating: reintroducing an unbound `threshold_value` fails |
| 18f | Commissioner settings cannot complete a definition | A commissioner-supplied threshold, formula or winner rule does not make an incomplete definition executable; it remains gate-1 ineligible |
| 19 | Retired definitions unreachable | #57, #96, `the_lineup`, `bench_burn` cannot be drawn or picked |
| 19a | #97/#98 unreachable | Catalog numbers 97 and 98 and keys `most_field_goal_yards` and `highest_combined_field_goal_yards` are absent from the seeded set, rejected by the seeder, undrawable by the selector, and unpickable. Their numbers and keys are never reassigned |
| 19b | No active dependency on `made_field_goal_distance` | No seeded definition declares `made_field_goal_distance` in `required_stats`; the operand's absence from the source blocks no active Pool |
| 19c | Kicker definitions settle on fantasy points | #18 and #77 read `kicking_points` — actual Yahoo fantasy points for the active starting kicker or kickers. **Discriminating: a fixture where `3 × FG + 1 × XP` and the league's bracket scoring disagree must resolve to the bracket-scored winner** |
| 20 | Postseason phase | Draws only from the 32-subset; the regular-season partial index does not fire |
| 21 | Migration | Live `worst_beat_rollover_cents` preserved exactly into `pool_instance` |
| 22 | Entry division | Contribution splits across 4, remainder lands on `championship:{league_id}` exactly once |
| 23 | `NO_SUBJECTS` | Zero considered subjects refuses settlement with the named error; no posting, no roll, no sweep, instance not settled |
| 24 | `NO_EVALUABLE_SUBJECTS` | Subjects present, none evaluable: same refusal, distinct classification in the error |
| 25 | `INCOMPLETE_FIELD` | One subject unevaluable out of a full field refuses settlement; no threshold settles it, no partial payout survives |
| 26 | `MATCHUP` subject identity | A matchup counts as one subject; one unevaluable participant makes the matchup unevaluable |
| 27 | `INVARIANT_VIOLATION` | A complete `RANK_EXTREMUM` field with zero claimants raises an error type distinct from the three data conditions |
| 28 | Census source independence | `subjects_considered` still reports the full field when the stat source is empty; a census read from the stat feed would pass this and must fail |

Scenario 15 requires a fixture where aggregate-over-aggregate and average-of-ratios produce **different winners**. A fixture where they agree proves nothing.

Scenario 17's sweep branch is generic engine behavior. Every active Rev1.3 `QUALIFIER` definition is rollover-eligible, so that branch is exercised only with explicitly synthetic, test-only metadata — never a catalog row.

Scenario 20 is blocked on the postseason subset.

Scenario 28 is the discriminating control for C6. A census derived from the stat source passes scenarios 23 through 27 and fails only here.

Scenarios 10e and 10h are the discriminating controls for §G1. An implementation relying on a row lock, or writing the `settled` flag in a second transaction, passes scenario 10 and fails those two.

Scenario 12b is the discriminating control for POR §6.3. An implementation that splits correctly but orders winners by query result or display name passes 12a and 12c and fails 12b.

Every scenario asserts trial balance zero, including 10a through 10h and 12a through 12d.

---

## I. Implementation order

| # | Step | Money path | Blocked on |
|---|---|---|---|
| 1 | Atomic week claim | no | — |
| 2 | `pool_definition` schema | no | — |
| 3 | `pool_instance` + constraints + partial index | no | — |
| 4 | `pool_rotation_cycle` audit table | no | — |
| 5 | `RANK_EXTREMUM` evaluator | no | — |
| 5a | Subject census + classification gate (C6) | no | — |
| 6 | `QUALIFIER` evaluator | no | — |
| 7 | `build_week_slate` — pure function | no | — |
| 8 | Seed all 80 active definitions — 77 product-`ENABLED`, 3 `BLOCKED`; the selector draws only definitions passing BOTH gates (§C7.4) | no | — |
| 9 | Backfill historical pots; migrate rollover cents | **yes** | — |
| 10 | Wire slate creation into collection | **yes** | 7, 8 |
| 11 | `settle_pool` loops instances, divides by 4 | **yes** | 5, 6, 10 |
| 11a | Classification gate wired ahead of settlement branches | **yes** | 5a, 11 |
| 11b | Event-keyed idempotency: `economic_event_type` enum, `UNIQUE (pool_instance_id, economic_event_type)`, posting and `settled` in one transaction (§G1) | **yes** | 11 |
| 12 | Reconciliation guard `:562-595` per instance — supplements §G1, never replaces it | **yes** | 11, 11b |
| 13 | Retire `bench_burn` acceptance | no | — |
| 14 | `season_final_week` / `playoff_start_week` reader | no | POR §12.5 |
| 15 | Regression suite §H | no | all |
| 16 | Opus math review before 9, 10, 11, 11a, 11b, 12 ship | gate | — |

Steps 1–7 change no money behavior and are testable without any product ruling. **Prove the closed-grammar evaluators against a dozen hand-picked definitions before seeding all 80**, then the five non-closed shapes individually — each carries exactly one definition, so each needs its own fixture. The catalog load looks like the natural first move because it is the biggest pile of data; it is also the step most likely to be reworked if the metadata schema shifts.

---

## J. Blockers

Only items that prevent implementation or production activation.

| # | Blocker | Blocks |
|---|---|---|
| 1 | **Postseason 32-subset list** — not located in any current artifact | Postseason activation, step 20 of §H, `postseason_eligible` on all 80 rows |
| 2 | ~~Seven formula definitions~~ | **Resolved in Rev1.3.** #42, #43, #46 defined; #44, #45, #47, #88 retired |
| 3 | **Two-point conversion confirmation** — #7, #85 | 2 of 80 definitions |
| 4 | **Mid-season unblocking behavior** — live or frozen at season start | Whether the eligible set is computed per draw or snapshotted |
| 5 | **`season_final_week` / `playoff_start_week` reader** — ruled, unbuilt | Expiry timing and phase transition |
| 6 | **Live cutover policy** if shipping mid-season | `// 3` → 4-slot division and the rollover column move both land on live balances |

Settled and not reopened: catalog count, four-slot weekly slate, anti-tanking, retired definitions, system selection, no-repeat, rollover occupancy, entry economics, evaluator-family architecture.

**Item 2 is resolved and is no longer a blocker.** Revision 1.3 defined #42, #43 and #46 and retired #44, #45, #47 and #88; no formula is pending. **Blocker 3 does not gate activation:** the Gate-1 ceiling of 64 definitions vastly exceeds the four needed for a valid slate, provided enough of them clear every Gate-2 requirement. How many clear it is measured, never assumed. Blocker 1 gates postseason only. Blockers 4, 5 and 6 gate correctness at specific boundaries, not the build.

---

## C7 — Provider-neutral input boundary

Implements POR Rev1.3. Every requirement is Stage H. **Nothing here authorizes build.**

**The evaluator layer is provider-neutral.** It receives normalized subjects and canonical stat values and knows nothing about where they came from. Provider identity — endpoint shapes, identifiers, response formats, authentication — lives entirely in an adaptor boundary the evaluator never sees. Substituting a provider must not require an evaluator change.

Two inputs cross the boundary and nothing else: **subjects**, per POR §6.2 subject identity, and **canonical stat values** keyed by vocabulary name, with subject-level coverage.

### C7.1 Starter-slot construction

The adaptor constructs each subject from **active starter slots only**, per POR §1.3. Bench, IR, taxi and other non-starting assets are excluded before any value reaches the evaluator. Flex and Superflex resolve by the actual occupying player. Each starter contributes once.

Definitions narrowing further supply `slot_filter` and `slot_exclusions`; the adaptor applies both.

**Weekly roster history is required.** The current roster is not the week-N roster. Starter construction for a completed week must read that week's recorded slot assignment.

### C7.2 Canonical stat normalization

The adaptor maps source fields to canonical vocabulary names. Aliases resolve to canonical names before the boundary; the evaluator never sees an alias. Governed derived stats are computed from their vocabulary formulas.

**`field_goals_made` requires pre-evaluator normalization.** Its five bracket inputs exceed the closed grammar's three-operand limit, so it is supplied as a single canonical operand.

### C7.3 required_stats and coverage validation

Each definition declares `required_stats` as canonical keys. The adaptor supplies, per subject, an **independent subject-level coverage signal** proving which required stats were completely ingested — either normalized subject-level aggregates with every required stat explicitly present including explicit zero, or component dictionaries plus a coverage set.

**A subject is evaluable only when every required stat has affirmative subject-level coverage.** Only then may a structurally inapplicable component omit a key and contribute zero. **Absence of coverage means unevaluable and is never inferred as zero.**

Component-key presence alone is insufficient: a kicker row legitimately lacks passing yards, so presence at the component layer cannot carry a subject-level claim.

### C7.4 Two-gate selector enforcement

**The selector requires BOTH gates.** It does not draw from `dependency_state` alone, and it does not draw from gate 1 alone.

```
definition_runtime_eligible ==            -- GATE 1, persistent
    dependency_state == ENABLED
    AND required_stats resolved
    AND every required stat authoritatively source-mapped
    AND product_complete            -- no unbound variable, no commissioner input

league_activation_ready ==                -- GATE 2, transient, per league+provider
    provider access authorized and operational
    AND every required source population-verified
    AND league-specific enabled-stat behavior confirmed where required
    AND required local fields population-verified

selectable == definition_runtime_eligible AND league_activation_ready
```

77 product-enabled · 64 gate 1 · **0 gate 2** · **0 selectable now**.

**64 is the Gate-1 ceiling, not a promised post-access count.** Restoring provider access clears the first Gate-2 line above and nothing else. The remaining Gate-2 lines — source population verification, league-specific enabled-stat confirmation, required local-field population verification, governed missing-versus-zero measurement where applicable, and a non-stale readiness measurement — are each measured per league, per provider, and per definition or required-source set. **The selectable count is recomputed only after all of them pass, and must not be stated in advance.** Any value from 0 to 64 is possible.

**Transient provider availability is never written into definition metadata.** A provider refusal sets gate 2 false for the environment; it never changes `dependency_state` and never retires a definition.

---

## C8 — Governed evaluator shapes

Eight shapes. **The closed SUM/RATIO grammar is unchanged.** The five non-closed shapes are separate governed evaluators; none is a grammar extension.

**`CLOSED_SUM` (42) and `CLOSED_RATIO` (17)** — the ratified grammar, unchanged. Aggregate-over-aggregate only. Zero denominator fails closed.

**`QUALIFIER_PREDICATE` (16)** — evaluates a structured `predicate` against canonical stats. `predicate_quantifier` selects the evaluation frame: `TEAM` against one team's totals, `MATCHUP_COMBINED` against both summed, `MATCHUP_EACH` requiring the condition per participating team. Configurable thresholds read `threshold_default` unless overridden. **An empty qualifier set is a legitimate result only over a fully evaluated field.**

**`PLAYER_EXTREMUM_WITHIN_SUBJECT` (1, #17)** — the subject remains the team; the metric is the maximum individual value among active starters in the declared slots. Not a sum. A subject with no qualifying starter is unevaluable, never zero.

**`SLOT_FILTERED_POINTS_SUM` (1, #42)** — sums actual fantasy points over the declared starter slots, applying `slot_exclusions`. Source basis is scored fantasy points, not raw stats.

**`BALANCE_RATIO` (1, #43)** — components clamped with `max(0, …)` before the ratio. Both components zero yields a **defined score of 0**, not an unevaluable subject. Clamping removes the divide-by-zero path; no zero-denominator guard applies.

**`DISTINCT_CATEGORY_COUNT` (1, #46, blocked)** — counts distinct touchdown categories, each at most once. Not implementable until source granularity is confirmed.

**`MATCHUP_SCORE_SUM` (1, #76)** — sums the two matchup scores from the league matchup record. Team-level totals, not per-player stats. Not expressible under the ratified grammar; `metric_expression` is null.

**A null `metric_expression` on a non-closed shape is correct.** The `governed_definition` is authoritative.

---

## C9 — Census, fail-closed and settlement prohibition

Every evaluator returns a census alongside its result: `subjects_considered`, `subjects_evaluated`, `subjects_claiming`. A bare list is not an acceptable return shape.

`subjects_considered` reads from the authoritative weekly league structure, **never from the stat source** — a census derived from the stat feed shrinks to match `subjects_evaluated` whenever data are missing, so the gate would pass on a broken week.

Six classifications per POR §6.2: `NO_SUBJECTS`, `NO_EVALUABLE_SUBJECTS`, `INCOMPLETE_FIELD`, `ZERO_ELIGIBLE_CLAIMS`, `CLAIMS_PRESENT`, `INVARIANT_VIOLATION`.

**Four are fail-closed:** `NO_SUBJECTS`, `NO_EVALUABLE_SUBJECTS`, `INCOMPLETE_FIELD`, `INVARIANT_VIOLATION`. Each refuses the settlement transaction. **No posting, no rollover, no sweep, no settled flag, and no surface reporting completion or distribution.** Each raises a named domain error carrying definition key, league, week, classification and census counts.

`ZERO_ELIGIBLE_CLAIMS` is the only zero-claim path into settlement. `INVARIANT_VIOLATION` carries a distinct error type — its cause is the evaluator, not the data, and it is not resolved by retry.

---

## C10 — Deferred measurements and open compliance work

### C10.1 Provider runtime measurements — deferred pending access approval

Four measurements are deferred. **None blocks specification.**

`pass_attempts` stat identifier · `completions` stat identifier · live missing-versus-zero response behavior · league-specific enabled-stat behavior.

The third is the keystone. If the source returns zero for a subject with no data, absence and zero are indistinguishable on the wire and `subjects_evaluated` cannot be derived at all.

### C10.2 Retention constraint — UNRESOLVED

**The provider's API terms impose a 24-hour retention limit on provider user data**, unless the API documents explicitly identify data as storable indefinitely. No such carve-out has been located.

The term "user data" is **not defined** in those terms. Player statistics and schedule data are arguably factual sports data; league settings, team names, rosters, starter assignments and matchup results are arguably user data.

**Season-long analytics require retained weekly history by design.** Whether the constraint reaches league and roster data is unresolved and is a legal question, not an engineering one.

**No retention architecture is specified here.** Writing one against an undefined term would encode a guess as a requirement. This is recorded as a binding open constraint on any future retention design.

### C10.3 Privacy policy — OPEN COMPLIANCE WORK

The API terms require an accessible privacy policy disclosing collection, use, sharing and retention, and stating that a third party is involved. They separately bar storing provider user data in a repository permitting third-party access unless the user permits it and the policy discloses it, and bar sharing account GUIDs with any third party.

No such policy exists. **Open compliance work, not implementation scope.**

### C10.4 Provider access — currently refused

A fresh OAuth Authorization Code grant completed successfully and the new token received the identical application-level refusal. The stored user grant is not the cause. An access application has been submitted. **The blocker is access, not design.**

---

## C11 — What this document does not authorize

No migration. No schema change. No evaluator, adaptor, selector or settlement code. No deployment. No production-data change. No collection integration. No balance movement.

Every requirement above is Stage H, behind the existing review gate. **Status remains: Scope — not authorized for build.**
