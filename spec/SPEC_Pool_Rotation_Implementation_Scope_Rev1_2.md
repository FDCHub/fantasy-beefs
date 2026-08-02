# Weekly Pool Rotation — Implementation Scope, Revision 1.2

**Status:** Scope — not authorized for build
**Date:** 2026-08-01
**Product authority:** `spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_2.md`
**Catalog data:** `spec/pool_catalog_rev1_2.json`

**Revision 1.2 is superseded by Revision 1.3. It superseded Revision 1.1 as implementation scope. Revisions 1.0 and 1.1 are retained unchanged as historical authority.**

---

## 0. Authority

Product behavior is governed by the Pool POR. This document specifies how to implement it. Where the two disagree, the POR governs and this document is wrong.

**Current code is implementation evidence, never authority.** Every code reference below is evidence dated 2026-07-30, not an immutable coordinate. Re-grep before building against any line number here.

---

## A. Current state

### A1 — Approved (per POR)

94 active definitions · 55 Team-Level, 39 Matchup · 9 dependency-blocked, 85 rotatable · 21 rollover-eligible · 2 evaluator families, `RANK_EXTREMUM` 73 and `QUALIFIER` 21 · exactly 4 pools per week · system-selected, auditable · no regular-season repeat within a cycle · fixed postseason 32-subset (list unresolved) · anti-tanking enforced at classification.

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

**91 approved definitions are not supported by the current settlement engine.** No catalog table, no slate model, no selection, no rotation cycle, no per-definition rollover, no lineage, no postseason phase, wrong slot divisor.

---

## B. Gap

**No weekly slate model exists.** That is the load-bearing absence. Everything else follows.

The four-name constant, `// 3`, single-column rollover and stale `bench_burn` acceptance are **implementation debt** — replaced, not debated.

The engine work is two parameterized evaluators plus a settlement loop. The bulk of remaining effort is catalog data and the seven pending formulas, neither of which is engine work.

---

## C. Minimal design

### C1 — `pool_definition`

94 rows seeded from `pool_catalog_rev1_2.json`. Columns mirror the JSON keys.

```
key PK · catalog_number · display_name · category
scope TEAM|MATCHUP · mechanic PREDICTION|RANK
evaluator_family RANK_EXTREMUM|QUALIFIER
metric_kind SIMPLE_AGG|RATIO|COMPOSITE
direction MAX|MIN NULL · metric_expression NULL
threshold_condition NULL · threshold_configurable
self_pick_rule · anti_tanking_review
data_dependency · dependency_state ENABLED|BLOCKED · block_reason NULL
regular_season_eligible · postseason_eligible NULL · rollover_eligible
tie_rule · aggregate_over_aggregate_required · zero_denominator_guard
```

`postseason_eligible` is nullable and stays null until the 32-subset is supplied. A null must be treated as *not yet eligible*, never as false-by-default and never as true.

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

`QUALIFIER(subjects, threshold_condition)` — evaluate a boolean per subject, return all qualifiers. **An empty qualifier set is a legitimate result only over a fully evaluated field.** Over an incomplete or unevaluable field it is not an outcome and is classified per C6.

Neither function knows any definition by name.

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
        winners or tie      -> even split, pot drains, NO ROLL
        zero claims, eligible, before season_final_week
                            -> rollover_cents = pot_cents, no posting
        zero claims, eligible, at season_final_week
                            -> sweep championship:{league_id}, zero carry
        zero claims, not eligible
                            -> sweep championship:{league_id}
        mark instance settled
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

Separately, `settle_pool` has no `FOR UPDATE` on `PoolPot`; idempotency rests on the `pot.settled` flag at `:543-544` plus a balance-keyed reconciliation guard. That is balance-keyed, not event-keyed, and does not prevent a double payout under retry. Covered by scenario 10.

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
| 11 | Duplicate collection | Concurrent collect: one `PoolPot`, four instances, no partial postings survive |
| 12 | Ties do not roll | Multi-winner settles, `rollover_cents` stays 0 |
| 13 | Final-week expiry with a live carry | Sweeps once at `season_final_week`, carry zeroed, no re-roll |
| 14 | `RANK_EXTREMUM` `MIN` | Fewest-style definitions pick the minimum |
| 15 | Aggregate-over-aggregate | `sum(y)/sum(t)`, never mean of per-player ratios; a fixture where the two disagree |
| 16 | Zero-denominator guard | #41 and #61 shapes fail closed |
| 17 | `QUALIFIER` with zero qualifiers | Rolls if eligible, sweeps if not |
| 18 | Blocked definitions excluded | None of the 9 ever enters a slate |
| 19 | Retired definitions unreachable | #57, #96, `the_lineup`, `bench_burn` cannot be drawn or picked |
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

Scenario 17's sweep branch is generic engine behavior. Every active Rev1.2 `QUALIFIER` definition is rollover-eligible, so that branch is exercised only with explicitly synthetic, test-only metadata — never a catalog row.

Scenario 20 is blocked on the postseason subset.

Scenario 28 is the discriminating control for C6. A census derived from the stat source passes scenarios 23 through 27 and fails only here.

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
| 8 | Seed all 94 active definitions — 85 `ENABLED`, 9 `BLOCKED` and excluded from rotation | no | — |
| 9 | Backfill historical pots; migrate rollover cents | **yes** | — |
| 10 | Wire slate creation into collection | **yes** | 7, 8 |
| 11 | `settle_pool` loops instances, divides by 4 | **yes** | 5, 6, 10 |
| 11a | Classification gate wired ahead of settlement branches | **yes** | 5a, 11 |
| 12 | Reconciliation guard `:562-595` per instance | **yes** | 11 |
| 13 | Retire `bench_burn` acceptance | no | — |
| 14 | `season_final_week` / `playoff_start_week` reader | no | POR §12.5 |
| 15 | Regression suite §H | no | all |
| 16 | Opus math review before 9, 10, 11, 11a, 12 ship | gate | — |

Steps 1–7 change no money behavior and are testable without any product ruling. **Prove the two evaluators against a dozen hand-picked definitions before seeding all 85.** The catalog load looks like the natural first move because it is the biggest pile of data; it is also the step most likely to be reworked if the metadata schema shifts.

---

## J. Blockers

Only items that prevent implementation or production activation.

| # | Blocker | Blocks |
|---|---|---|
| 1 | **Postseason 32-subset list** — not located in any current artifact | Postseason activation, step 20 of §H, `postseason_eligible` on all 94 rows |
| 2 | **Seven formula definitions** — #42–47, #88 | 7 of 94 definitions |
| 3 | **Yahoo 2-pt scoring confirmation** — #7, #85 | 2 of 94 definitions |
| 4 | **Mid-season unblocking behavior** — live or frozen at season start | Whether the eligible set is computed per draw or snapshotted |
| 5 | **`season_final_week` / `playoff_start_week` reader** — ruled, unbuilt | Expiry timing and phase transition |
| 6 | **Live cutover policy** if shipping mid-season | `// 3` → 4-slot division and the rollover column move both land on live balances |

Settled and not reopened: catalog count, four-slot weekly slate, anti-tanking, retired definitions, system selection, no-repeat, rollover occupancy, entry economics, evaluator-family architecture.

**Blockers 2 and 3 do not gate activation.** 85 rotatable definitions vastly exceed the four needed for a valid slate. Blocker 1 gates postseason only. Blockers 4, 5 and 6 gate correctness at specific boundaries, not the build.
