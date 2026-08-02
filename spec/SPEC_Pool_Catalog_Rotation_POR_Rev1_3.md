# FantasyStakes — Pool Catalog, Rotation & Settlement
# Product of Record, Revision 1.3

**Status:** Product of Record — current
**Date:** 2026-08-01
**Source artifact:** `FR-6_1_CATALOG_CLASSIFICATION.md` (96-row classified catalog)
**Machine-readable catalog:** `spec/pool_catalog_rev1_3.json`
**Canonical stat vocabulary:** `spec/pool_stat_vocabulary_rev1_0.json`
**Implementation scope:** `spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_3.md`

**Revision 1.3 supersedes Revision 1.2 as the current Product of Record. Revision 1.2 is marked superseded. Revisions 1.0 and 1.1 are retained unchanged as historical authority.**

**Revision 1.3 applies the owner deterministic-formula rulings of 2026-08-01.**

**Correction pass, 2026-08-01.** This copy supersedes the pre-correction Revision 1.3 draft, SHA-256 `5F2B5640F7A40A6AA5E284EB91603C5F4AA1FF7960267070E55C6F0C4BC26F7D`. It applies the accepted independent-review findings and two owner rulings: the kicker ruling (#18 and #77 renamed, #97 and #98 retired) and the tied-payout-remainder ruling (§6.3). This document was **DRAFT** at the time of that correction pass and was adopted as Product of Record on 2026-08-02. Nothing here authorizes implementation, migration, seeding, deployment or any production-data change.

---

## 0. Authority

> **This document is the current Product of Record** for FantasyStakes Pool catalog composition, Pool eligibility, weekly Pool rotation, Pool rollover behavior, Pool settlement classification, and Pool selection rules.
>
> Where current code, legacy pool constants, archived documents, UI mock data, or prior Pool concepts conflict with this POR, this POR governs product behavior unless a newer approved Pool POR explicitly supersedes it.
>
> UI/UX Rev 4.1 governs presentation only and does not redefine Pool mechanics.

This document is standalone. No reader needs Rev 3.x, the Rev3.1 POR register, transition packages, legacy `POOL_BET_TYPES`, or UI mock data to build the Pool product.

Current code is implementation evidence, never authority.

---

## 1. Catalog composition

The source artifact classifies **96** numbered definitions. Revision 1.3 retires sixteen. Two of the sixteen — #97 and #98 — were authored inside Revision 1.3 and retired inside Revision 1.3, so they never entered the active catalog. Net additions are zero.

| Figure | Count | Derivation |
|---|---|---|
| Rev1.2 active | 94 | prior Product of Record |
| Retired in Rev1.3 from the Rev1.2 active set | 14 | §1.1 |
| Authored and retired within Rev1.3 | 2 | #97, #98 — never active |
| Net added in Rev1.3 | 0 | |
| **Active** | **80** | 94 − 14 |
| Team-Level | 44 | |
| Matchup | 36 | |
| **Product-enabled** | **77** | `dependency_state = ENABLED` |
| **Product-blocked** | **3** | #7, #46, #85 |
| **Definition-runtime-eligible** | **64** | §1.2 gate 1 — a **ceiling**, not a forecast |
| League-activation-ready | *env. snapshot* | §1.2 gate 2 — not a catalog count |
| Selectable now | *env. snapshot* | 0 as of 2026-08-01; see §1.2 |
| Source-incomplete enabled | 13 | §1.2 |
| Product-incomplete enabled | 0 | §1.7 |
| `RANK_EXTREMUM` | 64 | |
| `QUALIFIER` | 16 | all rollover-eligible |
| Retired, cumulative | 20 | 4 prior + 16 in Rev1.3 |

**Original catalog numbers are preserved. Active definitions are not renumbered; retired numbers remain reserved and are never reused.**

### 1.1 Retired

| # | Name | Reason |
|---|---|---|
| 57 | Lowest Combined Passing Yards | Anti-tanking. Source marks self-pick **BLOCKED** — a QB-owning GM could deliberately throttle passing volume to win. |
| 96 | Defensive Slugfest | Anti-tanking. The only bet rewarding deliberately lower output on a fully controllable stat. Naming also unresolved. |
| — | The Lineup | **Legacy implementation name.** Never part of the 96-row catalog. Exists as a single-party `Bet.bet_type` settled by `settlement_engine._eval_the_lineup`. Retired from Pool scope. |
| — | Bench Burn | **Legacy implementation name.** Never part of the 96-row catalog. Present in `POOL_BET_TYPES` with no evaluator and no settlement branch. Retired from Pool scope. |

**Retired in Revision 1.3:**

| # | Name | Class | Reason |
|---|---|---|---|
| 44 | Best Pass-Scrimmage Balance | ZBB | Formula never defined and not authored. Removed under zero-based budgeting rather than left `BLOCKED` in the active catalog. |
| 45 | Most Balanced Skill Production | ZBB | As #44. |
| 47 | Most Diverse Scoring Production | ZBB | As #44. |
| 88 | Highest Combined Scoring-Category Diversity | ZBB | As #44. |
| 50 | Most Passing Production | Duplicate | Duplicate of #20. The global active-starter rule (§1.3) makes starters-only counting universal, so a "Starting-Lineup" variant computes the identical value. |
| 51 | Most Rushing Production | Duplicate | Duplicate of #21. As #50. |
| 52 | Most Receiving Production | Duplicate | Duplicate of #22. As #50. |
| 81 | Highest Combined Rushing Efficiency | Duplicate | Byte-identical metric expression to #66. #66 retained. |
| 82 | Highest Combined Receiving Efficiency | Duplicate | Byte-identical metric expression to #70. #70 retained. |

| 8 | Fixed Passing-Yard Threshold | ZBB | Unbound `threshold_value`; no universal product threshold governed; commissioner configuration would make it commissioner-interpreted (§1.7); overlaps an existing extremum Pool on the same statistic; configuration and explanation burden not justified by conceptual diversity. |
| 9 | Fixed Rushing-Yard Threshold | ZBB | As #8. |
| 10 | Fixed Receiving-Yard Threshold | ZBB | As #8. |
| 11 | Fixed Scrimmage-Yard Threshold | ZBB | As #8. |
| 12 | Fixed Total-Touchdown Threshold | ZBB | As #8. |

| 97 | Most Field-Goal Yards | Duplicate/replacement | Retired in favor of **#18 Highest Scoring Kicker**, which uses actual Yahoo fantasy points. #97 contested the same kicking outcome on an unsupported basis — the official distance of each made field goal, which the feed does not expose. Authored and retired within Revision 1.3; never active. |
| 98 | Highest Combined Field-Goal Yards | Duplicate/replacement | Retired in favor of **#77 Highest Scoring Kicker Matchup**, which uses the two starting kickers' combined actual Yahoo fantasy points. Otherwise as #97. |

**Retired numbers are reserved permanently and are never reused. #8–#12 are not replaced in this revision.** New definitions take the next unused number. Revision 1.3 authored 97 and 98 and then retired both; **97 and 98 are burned numbers and are never reassigned**, and their keys `most_field_goal_yards` and `highest_combined_field_goal_yards` are reserved with them. The next unused number is 99.

The Lineup and Bench Burn were never classified definitions. They are legacy constants retired from Pool scope, recorded here so no future reader mistakes them for catalog entries.

### 1.2 Two gates — binding

**A product-approved definition is not automatically drawable.** Three states are distinct and conflating any two is the defect this section prevents.

`dependency_state` is the **product** decision: approved and formula-complete.

**Gate 1 — `definition_runtime_eligible`.** Persistent definition metadata. True only when the definition is product-`ENABLED`; its `required_stats` are resolved; every required stat carries an authoritative source mapping; and the definition is **mathematically complete without commissioner interpretation** (§1.7). Each false carries a `definition_block_reason`.

**Gate 2 — `league_activation_ready`.** Transient environment state for a given league and provider. **It is never stored on a definition.** Its carrier is keyed by league, provider and definition or required-source set, and carries a measurement timestamp; the persistence choice is implementation scope. True only when provider access is authorized and operational; every required source is population-verified; league-specific enabled-stat behavior is confirmed where required; and required local fields are population-verified. Each false carries a `league_activation_block_reason`.

**The selector requires BOTH.** Transient provider availability is never folded into persistent definition metadata, and a definition never loses product approval because an environment is unavailable.

77 product-enabled · 64 definition-runtime-eligible. **Dated environment snapshot, 2026-08-01: 0 league-activation-ready, 0 selectable now.** Those two are environment measurements, not catalog counts.

Zero is the correct current figure. Provider access is refused (§13), so no required source is population-verified. Product status is unchanged by this and no ruling is reversed.

**The Gate-1 count is a ceiling, not a forecast — binding.** 64 is the current maximum number of definitions that could ever be selectable, not a count that returns on any event. **Restoring provider access clears one Gate-2 precondition. It does not by itself return any definition to selectable status.** Gate 2 additionally requires current source-population verification, league-specific enabled-stat confirmation, required local-field population verification, governed missing-versus-zero measurement where applicable, and a non-stale readiness measurement. Each of those is measured per league, per provider, and per definition or required-source set.

**The post-access selectable count must not be stated in advance.** It is computed only after every Gate-2 requirement is satisfied for the particular set being measured, and it may be any value from 0 to 64. No document, field or UI surface may assert that access restoration alone yields 64 selectable definitions.

### 1.7 Catalog completeness principle — binding

**Every Pool definition must be complete and deterministic at the product level. Commissioner configuration may enable or disable a governed definition, but may not supply a missing formula, threshold, data meaning, scoring interpretation, winner rule, or settlement behavior.**

**A definition requiring commissioner interpretation to become mathematically complete is not eligible for the active catalog.** It must be completed by owner ruling or retired under zero-based budgeting.

The owner prefers a smaller catalog of highly diverse, easily understood and fully deterministic Pools over preserving marginal definitions through commissioner interpretation or additional configuration.

#89, #90, #91 and #94 carry explicit governed thresholds — 10, 500, 700 and 100 — and require no commissioner interpretation. They are unaffected.

---

### 1.3 The global active-starter rule — binding

**Unless a definition expressly requires otherwise:**

- count only players or defenses occupying **active starter slots**;
- exclude bench, IR, taxi and all other non-starting rostered assets;
- Flex and Superflex count by the **actual player occupying the starting slot**;
- count each starter once;
- a Pool may use either raw player statistics or actual fantasy points under the league's governing scoring settings.

Every definition carries `starter_slot_rule`. Definitions narrowing further carry `slot_filter` and `slot_exclusions`.

### 1.4 Canonical stat vocabulary — authority

`spec/pool_stat_vocabulary_rev1_0.json` is the single authority for stat identity. Every `required_stats` entry is a canonical key from it. The catalog stores canonical keys only — never source identifiers, aliases, formulas or missing-value rules.

Governed aliases resolve to canonical names and are not separate stats:

| Alias | Canonical |
|---|---|
| `yards` | `scrimmage_yards` |
| `touchdowns`, `offensive_td`, `total_touchdowns` | `total_touchdown_credits` |
| `field_goals` | `field_goals_made` |
| `extra_points` | `extra_points_made` |
| `offensive_opportunities` | `opportunities` |

Governed derived stats: `touches` = `rush_attempts + receptions`; `opportunities` = `pass_attempts + rush_attempts`; `offensive_yards` = `passing_yards + rushing_yards`; `scrimmage_yards` = `rushing_yards + receiving_yards`; `field_goals_made` = the sum of Yahoo's five bracket counters.

**`offensive_yards` excludes receiving yards** — including both passing and receiving would double-count completed-pass yardage. **`scrimmage_yards`** excludes passing and all return yardage. **All-purpose yards is not in the governed vocabulary** and is not an alias for either.

### 1.5 Structured qualifier predicates

All 16 `QUALIFIER` definitions carry a structured `predicate`, a `predicate_quantifier` and deterministic `required_stats`. `threshold_condition` prose is retained for human reading only and is not the evaluated form.

`predicate_quantifier` takes exactly three values: `TEAM` evaluates against one team's totals; `MATCHUP_COMBINED` evaluates against both teams summed; `MATCHUP_EACH` requires the condition to hold for each participating team independently.

Configurable thresholds carry `threshold_configurable: true` and a `threshold_default`. Defaults: #89 = 10, #90 = 500, #91 = 700, #94 = 100.

### 1.6 Touchdown-credit semantics — binding

**`total_touchdown_credits` counts fantasy touchdown credits. It is not a count of unique NFL scoring plays and must never be described as one.**

`total_touchdown_credits = passing_td + rushing_td + receiving_td`.

A touchdown pass from an active starting quarterback to an active starting receiver on the same fantasy team yields **two credits** — one passing, one receiving. **This is intentional.** Counting unique NFL offensive touchdowns would require event-level deduplication the weekly aggregate feed does not support.

Affects active definitions #13, #19, #40, #73, and qualifiers #6 and #89. Retired #12 also used this stat; recorded for migration provenance only.

### 1.8 Kicker definitions — binding

**Owner ruling, 2026-08-01.** Two definitions contest kicker output. Both settle on **actual Yahoo fantasy football points scored under the league's governing Yahoo scoring settings**, carried by the canonical operand `kicking_points`.

| # | Name | Scope | Rule |
|---|---|---|---|
| 18 | **Highest Scoring Kicker** | TEAM | Compare the actual Yahoo fantasy points of each TEAM subject's **active starting kicker**. |
| 77 | **Highest Scoring Kicker Matchup** | MATCHUP | Sum the actual Yahoo fantasy points of the **two active starting kickers** in each scheduled MATCHUP subject. |

Neither is computed from raw field-goal counts, from made-field-goal distance, or from any `3 × FG + 1 × XP` reconstruction. Yahoo scores field goals by distance bracket, so a count-based reconstruction would produce a different winner than the league's own scoring.

**Persisted keys are unchanged.** #18 remains `most_kicking_points` and #77 remains `highest_combined_kicker_points`. A key is an immutable identifier and does not track a display name. Renaming a key would break every persisted `pool_instance` reference for no product gain.

The prior names — Most Kicking Points and Highest Combined Kicker Points — are superseded and must not appear on any surface.

---

## 2. Anti-tanking rule

**No Pool may reward a GM for intentionally worsening their own team or lineup.**

Applied to all 96 at classification. Two failed anti-tanking and are retired. **All 80 active definitions allow self-pick.** The sixteen definitions retired in Revision 1.3 were removed for zero-based budgeting, duplication, unbound thresholds, or duplicate/replacement overlap — never for anti-tanking, so the assertion is unweakened. #18 Highest Scoring Kicker and #77 Highest Scoring Kicker Matchup are `MAX`-direction scoring definitions and introduce no tank vector: suppressing output cannot win them.

A `MIN`-direction definition is not automatically a tank vector. Fewest Interceptions, Fewest Fumbles Lost, Fewest Turnovers and their matchup equivalents reward avoiding real mistakes — an aligned incentive, no vector. Those carry `anti_tanking_review: REVIEWED_ALLOWED_ALIGNED_INCENTIVE`.

Any new definition must pass this review before entering the catalog.

---

## 3. Mechanic and evaluator families

**Mechanic and evaluator family are different axes. Do not conflate them.**

**Mechanic** is how a GM enters. All 80 active definitions are `PREDICTION` — the GM selects one team or one matchup. Every outcome resolves to one GM/team or one Yahoo matchup of exactly two GMs; a raw stat may *define* a contest but is never the selectable outcome. The `RANK` mechanic (auto-entry, no pick) has **no active definitions** following The Lineup's retirement.

**Evaluator family** is how the winner is computed.

| Family | Count | Behavior |
|---|---|---|
| `RANK_EXTREMUM` | 64 | Compute one value per subject, rank, return all tied at the extreme |
| `QUALIFIER` | 16 | Evaluate a boolean per subject, split among qualifiers, roll on zero |

### 3.1 Ruling — the catalog is metadata-driven

**The 80-definition catalog does NOT imply 80 bespoke evaluator functions.**

Two axes govern computation and they are not the same thing.

**Evaluator families classify settlement behavior.** `RANK_EXTREMUM` (64) and `QUALIFIER` (16). The family determines rollover eligibility and how a zero-claim outcome is interpreted. It does not determine how a value is computed.

**Evaluator shapes define executable computation.** There are **eight** (§3.4). The family axis alone is not the executable inventory, and treating it as one is the error this section exists to prevent.

**The closed SUM/RATIO grammar is unchanged and remains the dominant shape.** 42 `CLOSED_SUM` and 17 `CLOSED_RATIO` are driven entirely by declarative metadata — `scope`, `metric_expression`, `metric_kind`, `direction`. 16 `QUALIFIER_PREDICATE` definitions are driven by a structured `predicate` and `predicate_quantifier` (§1.5).

**The five remaining shapes are explicitly governed, not miscellaneous logic.** `PLAYER_EXTREMUM_WITHIN_SUBJECT`, `SLOT_FILTERED_POINTS_SUM`, `BALANCE_RATIO`, `DISTINCT_CATEGORY_COUNT` and `MATCHUP_SCORE_SUM` each carry one definition and a prose `governed_definition`. They are not `COMPOSITE` placeholders and they are not undefined. Each is a named shape with a deterministic rule.

**No formula is pending.** Revision 1.3 resolved every previously undefined formula: #42, #43 and #46 were defined; #44, #45, #47 and #88 were retired under zero-based budgeting. Remaining constraints are source and runtime dependencies (§13), not missing product definitions.

### 3.2 Aggregate-over-aggregate — binding

**Every `RATIO` definition computes `sum(numerator) / sum(denominator)` across the roster or matchup. It must never silently become an average of individual per-player ratios.**

The two produce different winners on the same data. This is a wrong-winner defect, not a crash, and it will not announce itself.

Rows requiring it carry `aggregate_over_aggregate_required: true`.

### 3.3 Zero-denominator — fail closed

Any `RATIO` definition whose denominator can be zero in a real week must **fail closed**, never divide, never coerce to zero, never award. Rows carry `zero_denominator_guard: true`.

Explicitly flagged in the source: #41 Best Roster Completion Percentage, #61 Best Combined Completion Percentage — both can face a week with no real pass attempts.

---

### 3.4 Governed evaluator shapes

**The closed SUM/RATIO grammar is preserved unchanged.** Formulas outside it are not forced into it and are not expressed as `metric_expression` strings. Each carries a distinct governed `evaluator_shape` and a prose `governed_definition`.

| Shape | Count | `metric_expression` |
|---|---|---|
| `CLOSED_SUM` | 42 | present |
| `CLOSED_RATIO` | 17 | present |
| `QUALIFIER_PREDICATE` | 16 | null; `predicate` instead |
| `PLAYER_EXTREMUM_WITHIN_SUBJECT` | 1 | null (#17) |
| `SLOT_FILTERED_POINTS_SUM` | 1 | null (#42) |
| `BALANCE_RATIO` | 1 | null (#43) |
| `DISTINCT_CATEGORY_COUNT` | 1 | null (#46, blocked) |
| `MATCHUP_SCORE_SUM` | 1 | null (#76) |

A null `metric_expression` on a non-`CLOSED_*` shape is **correct and expected**, not a missing formula. The governed definition is authoritative.

#43 is ruled in full: components are clamped with `max(0, …)` before the ratio; both components zero yields a **defined `balance_score` of 0**, not an unevaluable subject.

---

## 4. Rotation

**Exactly 4 active Pools per fantasy week.** Not three, not a variable count.

- Selection is **system-driven and auditable**. Every draw is a persisted row carrying week, slot, cycle and lineage.
- **Rollover continuations are placed first.** Each occupies one normal slate slot.
- Remaining slots are filled from eligible unused definitions.
- **No regular-season repeat while unused eligible definitions remain.**
- Fresh draws are tracked by `rotation_cycle`.
- **A rollover continuation does not count as fresh use in the new cycle.** A continuation is one instance persisting, not a second draw.
- The selector excludes carried definitions from the same-week fresh candidate pool.
- **A cycle resets only when the remaining unused eligible set cannot satisfy the required fresh slots.** Not at a week boundary, not on a schedule — at the draw that cannot be satisfied.
- **Every reset is auditable** — one row recording league, season, cycle, opening week, and eligible-set size at open.

### 4.1 Activation depth

**Technical validity requires at least 4 fully supported eligible definitions** — one week's slate.

Greater catalog depth reduces cycle reuse. For a 14-week regular season, 56 is the **maximum** fresh-slot demand assuming zero rollovers; every continuation reduces it. **56 is not a mandatory activation threshold.**

---

## 5. Rollover

- **Only rollover-eligible definitions may roll.** Eligibility is a per-definition property, `rollover_eligible`.
- **Rollover occurs only on the `ZERO_ELIGIBLE_CLAIMS` classification (§6.2).** It never fires on `NO_SUBJECTS`, `NO_EVALUABLE_SUBJECTS`, `INCOMPLETE_FIELD`, or `INVARIANT_VIOLATION`. **Missing or undefined data must never manufacture a continuation.**
- **Ties and multiple winners settle normally and do not roll.**
- Rollover carries the existing pot forward.
- The continuation occupies one slot in the next eligible week.
- **Rollover lineage must be auditable and available to the UI** — a GM must be able to see a pool carried from a prior week and which week it came from.
- A continuation does not count as a fresh repeat.
- **Final-week expiry follows the governing season boundary (§9), not a hardcoded week number.**

Rollover eligibility follows evaluator family. The 16 `QUALIFIER` definitions are rollover-eligible. The 64 `RANK_EXTREMUM` definitions are not. A `RANK_EXTREMUM` definition resolves to a winner or a tie for any valid non-empty subject set, so nothing is left to carry. A `QUALIFIER` definition may legitimately produce zero qualifying subjects, and that outcome follows the rollover lifecycle. `rollover_eligible` remains explicit per-definition metadata, never a derived value, even though every active Rev1.3 definition currently follows the family rule. A `RANK_EXTREMUM` definition that returns zero claimants over a complete, non-empty evaluated field is an invariant violation, not a rollover condition (§6.2).

**The legacy `worst_beat_rollover` boolean on `PoolConfig` is implementation debt, not product authority.** It is a single league-wide flag scoped to one retired definition. It must not be generalized into a product rule.

---

## 6. Settlement classification

**The table below applies only after §6.2 classification returns `ZERO_ELIGIBLE_CLAIMS` or `CLAIMS_PRESENT`. No other classification reaches it.**

| Outcome | Behavior |
|---|---|
| Single winner | Pot to the winner |
| Tie / multiple winners | **Even split per §6.3.** The indivisible remainder follows the exact governed algorithm — no discretion. Does not roll. |
| Zero eligible claims, rollover-eligible, before final week | Pot carries forward as a continuation. No posting. |
| Zero eligible claims, rollover-eligible, final week | Sweep to `championship:{league_id}`. Carry zeroed. |
| Zero eligible claims, not rollover-eligible | Sweep to `championship:{league_id}`. |

Default `tie_rule` is `EVEN_SPLIT` on all 80 rows. `EVEN_SPLIT` is fully specified at §6.3 and carries no implementation discretion.

Settlement is protocol-driven. **The commissioner cannot pick a winner, alter settlement, or redirect a pot.**

### 6.1 Entry economics — ruled

The weekly Pool contribution is **league-level and fixed**, not per-pool. `weekly_entry_cents`, bounded `100 ≤ x ≤ 500`, default 100, frozen at first accepted wager.

**The contribution is divided dynamically across the active funded pool occurrences** — denominator is the count of active funded occurrences, which under §4 is 4. **The top-level indivisible remainder credits `championship:{league_id}`.**

The legacy `// 3` divisor and the remainder-to-Special-Teams behavior are implementation debt and are forbidden going forward.

### 6.2 Empty and incomplete result sets — census before behavior

**A bare empty result set never determines an outcome.** Classification is computed from a census of the subject set. Behavior follows the classification.

**Subject identity.** The counted subject is the selectable outcome unit — the thing a GM picks. Not the thing the metric reads from.

| `scope` | Counted subject |
|---|---|
| `TEAM` | One league team, from the authoritative weekly league structure |
| `MATCHUP` | One scheduled matchup. **Not its two teams separately** |

**A `MATCHUP` subject is evaluable only when both participants are evaluable.** There is no partial matchup.

`PLAYER`, `POSITION` and `LEAGUE` are not current catalog scopes and inherit no subject rule. Any future definition introducing one requires its own subject ruling before entering the catalog.

**`subjects_considered` is read from the authoritative weekly league structure, never from the stat source.** Teams from the roster of record; matchups from the schedule. A count derived from the stat feed would shrink to equal `subjects_evaluated` whenever data were missing, and the guard would pass on a broken week.

`subjects_considered` is per-week and actual. A legitimately smaller field is a smaller `considered`, not an incomplete one.

**Evaluability.** A subject is evaluable when its required `data_dependency` is present for the week and its governed `metric_expression` yields a defined value. **Absence of a stat is not a stat of zero.** A subject with complete source data is evaluable at zero only when the governed metric expression is defined at zero. For a ratio, a present denominator of zero produces an undefined metric and the subject is unevaluable under the zero-denominator rule (§3.3).

**Census.**

| # | `subjects_considered` | `subjects_evaluated` | `subjects_claiming` | Classification |
|---|---|---|---|---|
| 1 | 0 | — | — | `NO_SUBJECTS` |
| 2 | > 0 | 0 | — | `NO_EVALUABLE_SUBJECTS` |
| 3 | > 0 | 0 < e < `considered` | not computed | `INCOMPLETE_FIELD` |
| 4 | > 0 | = `considered` | 0 | `ZERO_ELIGIBLE_CLAIMS` |
| 5 | > 0 | = `considered` | ≥ 1 | `CLAIMS_PRESENT` |
| 6 | > 0 | = `considered` | 0, family `RANK_EXTREMUM` | `INVARIANT_VIOLATION` |

**Row 6 takes precedence over row 4.**

**Full-field requirement.** Any week where `subjects_evaluated < subjects_considered` fails closed as `INCOMPLETE_FIELD`. **There is no completeness threshold. There is no family-specific or definition-specific exception.** A subject that was not evaluated could have held the extremum or met the threshold, and no completeness short of the full field excludes that.

**Ordering.** `subjects_claiming` is computed only once `subjects_evaluated == subjects_considered`. A claim count over an incomplete field is not computed, not stored, and not logged.

**Behavior.**

| Classification | Settles | Pot | Rollover | Sweep | Reported as |
|---|---|---|---|---|---|
| `NO_SUBJECTS` | No | Untouched in `pool:{league_id}` | Never | Never | Unsettled |
| `NO_EVALUABLE_SUBJECTS` | No | Untouched | Never | Never | Unsettled |
| `INCOMPLETE_FIELD` | No | Untouched | Never | Never | Unsettled |
| `ZERO_ELIGIBLE_CLAIMS` | Yes | Per §6 | Per §6 | Per §6 | Settled |
| `CLAIMS_PRESENT` | Yes | Per §6 | Never | Never | Settled, distributed |
| `INVARIANT_VIOLATION` | No | Untouched | Never | Never | Unsettled |

Binding on all four fail-closed classifications:

- The settlement transaction is refused. Nothing partial survives.
- No posting occurs. The pot is neither carried nor swept.
- **No surface may report the pot as settled, completed, or distributed** — not the settlement result, not the feed, not commissioner reconciliation.
- Every refusal raises a **named domain error** carrying definition key, league, week, classification, and the census counts. `INCOMPLETE_FIELD` additionally carries the identity of the unevaluable subjects.

`NO_SUBJECTS`, `NO_EVALUABLE_SUBJECTS` and `INCOMPLETE_FIELD` are data conditions. The remedy is retry once the missing structure or data is present.

**`INVARIANT_VIOLATION` carries a distinct error type.** Its cause is the evaluator, not the data. It is not resolved by waiting, and it must be distinguishable on the error surface from the three data conditions.

**`ZERO_ELIGIBLE_CLAIMS` is the only zero-claim path into §6.** `CLAIMS_PRESENT` uses §6 winner and split behavior unchanged.

**Explicit zero versus missing data — binding.** A stat present at zero and a stat that never arrived are different states and must never be conflated. A subject with complete source coverage and a genuine zero is **evaluable at zero**. A subject whose required stat did not arrive is **unevaluable**. The vocabulary carries `explicit_zero_is_valid` and `missing_value_behavior` per stat; the catalog carries `required_stats`; the adaptor supplies subject-level coverage. Absence is never inferred as zero at any layer.

**Reported distribution arithmetic is not governed here.** The `total_distributed_cents` correction remains linked FR-POOL-1 work and is not absorbed into this rule.

### 6.3 Tied payout — exact remainder algorithm, binding

**Owner ruling, 2026-08-01.** `EVEN_SPLIT` is a complete algorithm, not a policy direction. No implementation may choose its own remainder rule.

Given `pot_cents` and the set of winning GMs:

```
winner_count      = number of winning GMs
base_share_cents  = floor(pot_cents / winner_count)
remainder_count   = pot_cents % winner_count

order the winning GMs by canonical GM identifier, ASCENDING

every winner receives                        base_share_cents
the first remainder_count winners in that
order each receive one ADDITIONAL cent
```

Binding properties:

- **Ordered recipient identity.** The recipients are the winning GMs of that pool instance, and no one else.
- **Stable ordering key.** The **canonical GM identifier**, ascending. Never a display name, never a roster position, never claim order, never database-return order. An unordered or query-order allocation is non-conformant even when the totals happen to match.
- **Conservation.** `base_share_cents × winner_count + remainder_count == pot_cents`. Every cent is distributed. Nothing is rounded away, nothing is absorbed, nothing is swept.
- **Distributed exactly once.** The pot drains in a single posting.
- **Deterministic under retry.** A retry must reproduce the identical per-GM allocation, cent for cent. The allocation is a pure function of `pot_cents` and the ordered winner set.
- **Ties never roll.** A tie is a settled outcome (§5).

Worked example. `pot_cents = 1000`, three winners with canonical IDs 4, 9 and 21. `base_share_cents = 333`, `remainder_count = 1`. GM 4 receives 334; GM 9 receives 333; GM 21 receives 333. Total 1000.

This is a different remainder from §6.1. §6.1 divides the weekly league contribution across active pool occurrences and credits its remainder to `championship:{league_id}`. **§6.3 governs payout to winners and never credits the championship account.** The two must not be collapsed.

### 6.4 Settlement idempotency — binding

**Two requirements govern together. Neither substitutes for the other.**

**1. Atomicity.** Ledger posting and the corresponding `pool_instance.settled` transition occur inside **one** database transaction. A settled flag written outside the posting transaction, or a posting committed before the flag, is non-conformant.

**2. Event-keyed idempotency.** Every economic settlement or sweep carries an **event-keyed idempotency key protected by a database uniqueness constraint**, so that replay after a crash or an ambiguous retry is harmless. The key is stable — recomputable from the event itself, never a timestamp, never a random value — and sufficient to distinguish:

- a normal winner or tie distribution;
- a non-rollover championship sweep;
- a final-week rollover-expiry sweep;
- any other economic posting generated by the same pool instance.

Conceptual key shape: the pool instance identity plus the economic-event discriminator — `(pool_instance_id, economic_event_type)`, where `economic_event_type` enumerates the distinct postings above. One pool instance may produce at most one posting per event type, ever.

**A row lock may supplement this protocol. It cannot replace it.** A lock serializes concurrent attempts inside one process lifetime; it says nothing about a retry arriving after the lock is released, and nothing about a crash between posting and response. Balance-keyed reconciliation is likewise a supplement, not a substitute: it compares amounts, not events, and two legitimate identical amounts are indistinguishable to it.

Implementation is Stage H behind the Opus math review gate. **Nothing here authorizes build.**

---

## 7. Dependency-blocked definitions

**The Revision 1.2 blocked table is superseded and deleted. §7.0 is controlling.**

### 7.0 Blocked definitions in Revision 1.3

Three definitions are product-approved and source-blocked. **No Pool was redefined to fit the source.**

| # | Scope | `data_dependency` | Blocked because |
|---|---|---|---|
| 7 | TEAM | `yahoo_two_point_conversion_scoring` | Pending live confirmation that the governed league's data exposes and populates two-point conversions sufficiently for deterministic evaluation. |
| 85 | MATCHUP | `yahoo_two_point_conversion_scoring` | As #7. |
| 46 | TEAM | `yahoo_touchdown_category_granularity` | The source collapses touchdown categories: kickoff and punt returns share one counter, D/ST touchdown types share another, and no blocked-kick-return category is exposed. The approved category list cannot be represented. |

**`yahoo_made_field_goal_distance` is no longer a blocking dependency.** It supported only #97 and #98, both retired (§1.1). `made_field_goal_distance` remains in the stat vocabulary as unsupported historical and source documentation, is required by no active definition, and blocks no active Pool.

Every blocked definition carries a non-null `blocked_reason`. `blocked_reason` is the single canonical field and is null on all 77 non-blocked active definitions.

**A blocked definition is a source limitation, not a rejected product concept.** Each unblocks unchanged when its source support is confirmed.

### 7.1 Mid-season unblocking — OPEN

**No current POR settles whether a definition unblocked mid-season becomes immediately eligible or whether eligibility is frozen at season start.**

This is an open product decision, recorded, not invented. It determines whether the eligible set is computed live at each draw or snapshotted at season open.

---

## 8. Postseason — UNRESOLVED

The Rotation POR states postseason uses a **fixed approved 32-Pool subset**.

**That list was not located.** Searched: `FR-6_1_CATALOG_CLASSIFICATION.md`, the Findings Registers, transition packages and continuation packages. No 32-definition list exists in any current artifact.

**No postseason subset is defined in this POR. It is not invented.**

Every catalog row carries `postseason_eligible: null` pending the list. This is the single unresolved postseason blocker.

**One adjacent ruling exists and may or may not be the same thing.** The 2026-07-14 playoff policy states: *"Championship week (final 2 GMs) — themed Super Bowl-style prop slate. Active rollovers from the prior week take priority."* Whether the 32-subset is the pool this themed slate draws from, or a separate construct, is not settled here.

Other playoff rulings already in force and preserved:

- Pool bets are open to **anyone, always, including eliminated GMs**.
- Pool subject eligibility keys on `roster_scores(team_id, week)` — a GM with real logged stats is an eligible subject regardless of bracket status.
- Self-pick allowed for "win" outcomes, blocked for "bad/loss" outcomes, year-round. Consistent with §2.
- No mandatory weekly minimum in the playoffs; the standard $1 bet floor applies.
- The rollover mechanic applies to pool bets only, never versus bets.

---

## 9. Season boundary

**The hardcoded week 14 is implementation debt and is not product authority.**

Governing boundary is Yahoo-derived, held on `League`:

| Field | Fallback | Use |
|---|---|---|
| `season_final_week` | 17 | Final-week rollover expiry sweep (§5) |
| `playoff_start_week` | 15 | Postseason phase begins |

Rollover expiry fires at `season_final_week`, not at 14. Regular-season rotation and the no-repeat rule apply to weeks before `playoff_start_week`; the postseason subset (§8) governs from `playoff_start_week` onward.

Both fields are ruled and unbuilt. The reader that populates them from Yahoo does not yet exist.

---

## 10. The full catalog

**80 active definitions.** Sixteen rows retired in Revision 1.3 (#8–#12, #44, #45, #47, #50, #51, #52, #81, #82, #88, #97, #98) are absent. #97 and #98 were authored and retired within this revision and never appear here. Machine-readable form with complete metadata is `spec/pool_catalog_rev1_3.json`.

Legend — **T** Team-Level, **M** Matchup · **RANK** `RANK_EXTREMUM`, **QUAL** `QUALIFIER` · **RO** rollover-eligible.

| # | Key | Name | Sc | Family | Metric | Dir | RO | State |
|---|---|---|---|---|---|---|---|---|
| 1 | `the_grand_slam` | The Grand Slam | T | QUAL | SIMP | — | Y | ok |
| 2 | `passing_rushing_receiving_td_trifecta` | Passing-Rushing-Receiving TD Trifecta | T | QUAL | SIMP | — | Y | ok |
| 3 | `recorded_both_a_rushing_and_receiving_td` | Recorded Both a Rushing and Receiving TD | T | QUAL | SIMP | — | Y | ok |
| 4 | `recorded_a_passing_and_rushing_td` | Recorded a Passing and Rushing TD | T | QUAL | SIMP | — | Y | ok |
| 5 | `recorded_a_passing_and_receiving_td` | Recorded a Passing and Receiving TD | T | QUAL | SIMP | — | Y | ok |
| 6 | `recorded_both_a_td_and_a_field_goal` | Recorded Both a TD and a Field Goal | T | QUAL | SIMP | — | Y | ok |
| 7 | `recorded_a_two_point_conversion` | Recorded a Two-Point Conversion | T | QUAL | SIMP | — | Y | BLOCKED |
| 13 | `most_total_touchdowns` | Most Total Touchdowns | T | RANK | SIMP | MAX |  | ok |
| 14 | `most_total_offensive_yards` | Most Total Offensive Yards | T | RANK | SIMP | MAX |  | ok |
| 15 | `most_scrimmage_yards` | Most Scrimmage Yards | T | RANK | SIMP | MAX |  | ok |
| 16 | `most_skill_position_touchdowns` | Most Skill-Position Touchdowns | T | RANK | SIMP | MAX |  | ok |
| 17 | `most_dual_threat_yards` | Most Dual-Threat Yards | T | RANK | SIMP | MAX |  | ok |
| 18 | `most_kicking_points` | Highest Scoring Kicker | T | RANK | SIMP | MAX |  | ok |
| 19 | `most_total_scoring_events` | Most Total Scoring Events | T | RANK | SIMP | MAX |  | ok |
| 20 | `most_passing_yards` | Most Passing Yards | T | RANK | SIMP | MAX |  | ok |
| 21 | `most_rushing_yards` | Most Rushing Yards | T | RANK | SIMP | MAX |  | ok |
| 22 | `most_receiving_yards` | Most Receiving Yards | T | RANK | SIMP | MAX |  | ok |
| 23 | `most_passing_touchdowns` | Most Passing Touchdowns | T | RANK | SIMP | MAX |  | ok |
| 24 | `most_rushing_touchdowns` | Most Rushing Touchdowns | T | RANK | SIMP | MAX |  | ok |
| 25 | `most_receiving_touchdowns` | Most Receiving Touchdowns | T | RANK | SIMP | MAX |  | ok |
| 26 | `most_field_goals_made` | Most Field Goals Made | T | RANK | SIMP | MAX |  | ok |
| 27 | `most_extra_points_made` | Most Extra Points Made | T | RANK | SIMP | MAX |  | ok |
| 28 | `fewest_interceptions_thrown` | Fewest Interceptions Thrown | T | RANK | SIMP | MIN |  | ok |
| 29 | `fewest_fumbles_lost` | Fewest Fumbles Lost | T | RANK | SIMP | MIN |  | ok |
| 30 | `fewest_total_turnovers` | Fewest Total Turnovers | T | RANK | SIMP | MIN |  | ok |
| 31 | `highest_yards_per_touch` | Highest Yards per Touch | T | RANK | RATI | MAX |  | ok |
| 32 | `highest_offensive_yards_per_opportunity` | Highest Offensive Yards per Opportunity | T | RANK | RATI | MAX |  | ok |
| 33 | `highest_yards_per_pass_attempt` | Highest Yards per Pass Attempt | T | RANK | RATI | MAX |  | ok |
| 34 | `highest_yards_per_completion` | Highest Yards per Completion | T | RANK | RATI | MAX |  | ok |
| 35 | `highest_yards_per_rush` | Highest Yards per Rush | T | RANK | RATI | MAX |  | ok |
| 36 | `highest_yards_per_reception` | Highest Yards per Reception | T | RANK | RATI | MAX |  | ok |
| 37 | `highest_passing_td_rate` | Highest Passing TD Rate | T | RANK | RATI | MAX |  | ok |
| 38 | `highest_rushing_td_rate` | Highest Rushing TD Rate | T | RANK | RATI | MAX |  | ok |
| 39 | `highest_receiving_td_rate` | Highest Receiving TD Rate | T | RANK | RATI | MAX |  | ok |
| 40 | `highest_tds_per_touch` | Highest TDs per Touch | T | RANK | RATI | MAX |  | ok |
| 41 | `best_roster_completion_percentage` | Best Roster Completion Percentage | T | RANK | RATI | MAX |  | ok |
| 42 | `most_complete_offensive_production` | Week's Top Offense | T | RANK | PTAG | MAX |  | ok |
| 43 | `best_run_pass_balance` | Best Run-Pass Balance | T | RANK | BALR | MAX |  | ok |
| 46 | `most_diverse_touchdown_production` | Most Diverse Touchdown Production | T | RANK | CATC | MAX |  | BLOCKED |
| 48 | `most_offensive_touches` | Most Offensive Touches | T | RANK | SIMP | MAX |  | ok |
| 49 | `most_offensive_opportunities` | Most Offensive Opportunities | T | RANK | SIMP | MAX |  | ok |
| 53 | `most_pass_attempts` | Most Pass Attempts | T | RANK | SIMP | MAX |  | ok |
| 54 | `most_rushing_attempts` | Most Rushing Attempts | T | RANK | SIMP | MAX |  | ok |
| 55 | `most_receptions` | Most Receptions | T | RANK | SIMP | MAX |  | ok |
| 56 | `highest_combined_passing_yards` | Highest Combined Passing Yards | M | RANK | SIMP | MAX |  | ok |
| 58 | `highest_combined_passing_tds` | Highest Combined Passing TDs | M | RANK | SIMP | MAX |  | ok |
| 59 | `most_combined_pass_attempts` | Most Combined Pass Attempts | M | RANK | SIMP | MAX |  | ok |
| 60 | `most_combined_completions` | Most Combined Completions | M | RANK | SIMP | MAX |  | ok |
| 61 | `best_combined_completion_percentage` | Best Combined Completion Percentage | M | RANK | RATI | MAX |  | ok |
| 62 | `fewest_combined_interceptions` | Fewest Combined Interceptions | M | RANK | SIMP | MIN |  | ok |
| 63 | `highest_combined_rushing_yards` | Highest Combined Rushing Yards | M | RANK | SIMP | MAX |  | ok |
| 64 | `highest_combined_rushing_tds` | Highest Combined Rushing TDs | M | RANK | SIMP | MAX |  | ok |
| 65 | `most_combined_rushing_attempts` | Most Combined Rushing Attempts | M | RANK | SIMP | MAX |  | ok |
| 66 | `highest_combined_yards_per_rush` | Highest Combined Yards per Rush | M | RANK | RATI | MAX |  | ok |
| 67 | `highest_combined_receiving_yards` | Highest Combined Receiving Yards | M | RANK | SIMP | MAX |  | ok |
| 68 | `highest_combined_receptions` | Highest Combined Receptions | M | RANK | SIMP | MAX |  | ok |
| 69 | `highest_combined_receiving_tds` | Highest Combined Receiving TDs | M | RANK | SIMP | MAX |  | ok |
| 70 | `highest_combined_yards_per_reception` | Highest Combined Yards per Reception | M | RANK | RATI | MAX |  | ok |
| 71 | `highest_combined_offensive_yards` | Highest Combined Offensive Yards | M | RANK | SIMP | MAX |  | ok |
| 72 | `highest_combined_scrimmage_yards` | Highest Combined Scrimmage Yards | M | RANK | SIMP | MAX |  | ok |
| 73 | `highest_combined_offensive_tds` | Highest Combined Offensive TDs | M | RANK | SIMP | MAX |  | ok |
| 74 | `highest_combined_touches` | Highest Combined Touches | M | RANK | SIMP | MAX |  | ok |
| 75 | `highest_combined_offensive_opportunities` | Highest Combined Offensive Opportunities | M | RANK | SIMP | MAX |  | ok |
| 76 | `shootout_of_the_week` | Shootout of the Week (Highest Combined Fantasy Points) | M | RANK | SIMP | MAX |  | ok |
| 77 | `highest_combined_kicker_points` | Highest Scoring Kicker Matchup | M | RANK | SIMP | MAX |  | ok |
| 78 | `highest_combined_yards_per_touch` | Highest Combined Yards per Touch | M | RANK | RATI | MAX |  | ok |
| 79 | `highest_combined_yards_per_opportunity` | Highest Combined Yards per Opportunity | M | RANK | RATI | MAX |  | ok |
| 80 | `highest_combined_passing_efficiency` | Highest Combined Passing Efficiency | M | RANK | RATI | MAX |  | ok |
| 83 | `fewest_combined_fumbles_lost` | Fewest Combined Fumbles Lost | M | RANK | SIMP | MIN |  | ok |
| 84 | `matchups_where_neither_team_lost_a_fumble` | Matchups Where Neither Team Lost a Fumble | M | QUAL | SIMP | — | Y | ok |
| 85 | `highest_combined_two_point_conversions` | Highest Combined Two-Point Conversions | M | RANK | SIMP | MAX |  | BLOCKED |
| 86 | `fewest_combined_turnovers` | Fewest Combined Turnovers | M | RANK | SIMP | MIN |  | ok |
| 87 | `matchups_with_zero_total_turnovers` | Matchups With Zero Total Turnovers | M | QUAL | SIMP | — | Y | ok |
| 89 | `matchups_with_10plus_combined_tds` | Matchups with 10+ Combined TDs | M | QUAL | SIMP | — | Y | ok |
| 90 | `matchups_with_500plus_combined_rushing_yards` | Matchups with 500+ Combined Rushing Yards | M | QUAL | SIMP | — | Y | ok |
| 91 | `matchups_with_700plus_combined_offensive_yards` | Matchups with 700+ Combined Offensive Yards | M | QUAL | SIMP | — | Y | ok |
| 92 | `matchups_where_both_teams_scored_a_passing_td` | Matchups Where Both Teams Scored a Passing TD | M | QUAL | SIMP | — | Y | ok |
| 93 | `matchups_where_both_teams_scored_a_rushing_td` | Matchups Where Both Teams Scored a Rushing TD | M | QUAL | SIMP | — | Y | ok |
| 94 | `matchups_where_both_teams_had_100plus_rushing_yards` | Matchups Where Both Teams Had 100+ Rushing Yards | M | QUAL | SIMP | — | Y | ok |
| 95 | `matchups_where_neither_team_threw_an_interception` | Matchups Where Neither Team Threw an Interception | M | QUAL | SIMP | — | Y | ok |

---

## 13. Yahoo-dependent unresolved items

Four items require live source measurement. **None blocks product authoring.** Each is recorded honestly. The first two are reflected in `definition_runtime_eligible`; the last two in `league_activation_ready`.

| Item | Effect | Resolves from |
|---|---|---|
| `pass_attempts` stat ID | No authoritative source mapping; transitively unmaps `opportunities` | full game stat-category list |
| `completions` stat ID | No authoritative source mapping | full game stat-category list |
| Live missing-versus-zero behavior | Governed `missing_value_behavior` for every source-derived stat. Keystone unknown for the coverage contract | bounded weekly stat-response measurement |
| League-specific enabled-stat behavior | Confirmation that the governed league enables each required category | league settings stat categories |

13 product-enabled definitions carry `source_mapping_complete: false` and are not runtime-rotatable: five on `pass_attempts`, four on `opportunities`, two on `completions`, two on both.

**The current blocker is access, not design.** A fresh OAuth Authorization Code grant completed successfully and the new token received the identical application-level refusal, so the stored user grant is not the cause. Approval through the provider's current access program is the only identified remediation path, although the provider has not formally confirmed the cause.

---

## 11. Conformance checklist

1. Exactly 4 active Pools per fantasy week
2. Catalog contains 80 active definitions; retired numbers are reserved and never reused
3. No active definition is renumbered
4. All 80 allow self-pick; the 2 anti-tanking failures are retired, not blocked
5. The Lineup and Bench Burn are unreachable as Pools
6. Two evaluator families classify settlement behavior; eight governed evaluator shapes define computation
7. Every `RATIO` definition computes aggregate-over-aggregate
8. Every zero-denominator-guarded definition fails closed
9. Selection is system-driven and every draw is persisted
10. Rollover continuations occupy slot positions ahead of fresh draws
11. No regular-season repeat within a rotation cycle
12. A continuation is not a fresh use in its cycle
13. A carried definition cannot also be drawn fresh in the same week
14. Cycle resets only on insufficient fresh set, and is audited
15. Only `rollover_eligible` definitions roll
16. Rollover fires only on the `ZERO_ELIGIBLE_CLAIMS` classification
17. Ties settle and never roll
18. Rollover lineage is queryable and exposed to the UI
19. The 3 product-blocked definitions (#7, #46, #85) never enter a slate
20. Weekly contribution is league-level, divided across active pools, remainder to `championship:{league_id}`
21. Final-week expiry uses `season_final_week`, never a hardcoded 14
22. No formula is invented to fit an available source
23. No postseason subset is asserted until the 32-list is supplied
24. Every settlement decision carries an authoritative subject census; no decision is made from a bare result list
25. A `TEAM` subject is one league team taken from the authoritative weekly league structure
26. A `MATCHUP` subject is one scheduled matchup, evaluable only when both participants are evaluable
27. `NO_SUBJECTS` fails closed
28. `NO_EVALUABLE_SUBJECTS` fails closed
29. `INCOMPLETE_FIELD` fails closed whenever `subjects_evaluated < subjects_considered`
30. `ZERO_ELIGIBLE_CLAIMS` is the only zero-claim path into §6
31. `CLAIMS_PRESENT` uses §6 winner and split behavior unchanged
32. A complete `RANK_EXTREMUM` field with zero claimants raises `INVARIANT_VIOLATION`
33. A fail-closed classification never settles, posts, rolls, sweeps, or reports completion
34. A definition is drawn only when `definition_runtime_eligible` AND `league_activation_ready` are both true
34a. A product-`ENABLED` definition with `definition_runtime_eligible: false` never enters a slate
34b. `definition_runtime_eligible: true` alone never bypasses `league_activation_ready`
34c. No active predicate contains an unbound variable
34d. Commissioner settings never make an incomplete catalog definition executable
34e. Retired definitions #8–#12, #97 and #98 can never be seeded, drawn or selected, and their numbers and keys are never reassigned
34f. Provider refusal prevents slate activation without changing any product status
35. Every `required_stats` entry is a canonical key present in the stat vocabulary
36. Every non-`CLOSED_*` evaluator shape carries a governed definition and a null `metric_expression`
37. Every `BLOCKED` definition carries a non-null `blocked_reason`; every non-blocked definition carries null
38. All 16 `QUALIFIER` definitions carry a structured predicate and deterministic `required_stats`
39. `total_touchdown_credits` is never described or computed as unique NFL scoring plays
40. A retired catalog number is never reused
41. No definition is redefined to fit an available source
42. A tied payout follows the §6.3 algorithm exactly: canonical GM ID ascending, `floor(pot_cents / winner_count)` to every winner, one extra cent to the first `pot_cents % winner_count` winners, full pot conserved, identical under retry
43. Every economic settlement or sweep posts its ledger entries and its `settled` transition in one transaction, and carries an event-keyed idempotency key under a database uniqueness constraint (§6.4)
44. A row lock is never presented or relied on as a substitute for event-keyed idempotency
45. #18 and #77 settle on actual Yahoo fantasy points from active starting kickers; no surface uses their superseded names
46. No statement asserts that restored provider access alone returns 64 definitions to selectable status; the post-access selectable count is never stated in advance

---

## 12. Open items

| # | Item | Blocks |
|---|---|---|
| 1 | **Postseason 32-subset list** — not located | Postseason activation |
| 2 | ~~Seven formula definitions~~ | **Resolved in Rev1.3.** #42, #43, #46 defined; #44, #45, #47, #88 retired |
| 3 | **Two-point conversion confirmation** — #7, #85 | 2 of 80 |
| 4 | **Mid-season unblocking behavior** — live or frozen | Eligible-set computation |
| 5 | **`season_final_week` / `playoff_start_week` reader** — ruled, unbuilt | Expiry and phase transition |
| 6 | **Live cutover policy** if shipping mid-season | Migration timing |

This POR governs the presentation and behavior of these. It does not resolve them.

### 12.1 Resolved in Revision 1.2 and 1.3

**No row in the table above is closed by Revision 1.2.** None of the six was the empty-result question.

| Item | Recorded at | Disposition |
|---|---|---|
| Governed behavior when an evaluator returns an empty result set | vol. II 22.22 | **Product layer resolved.** The rule now exists at §6.2. The implementation split is unchanged — Stage H, Opus math review gate |
| FR-POOL-1 | vol. II 22.20 | Remains **OPEN**. Its blocking product dependency is discharged. `total_distributed_cents` remains its own linked requirement |
| FR-POOL-2 | vol. II 22.21 | Remains **OPEN**. Its blocking product dependency is discharged. The named domain error is specified at §6.2 |
| FR-POOL-AUTH-1 | vol. II 22.23 | Remains **OPEN**. The Option B boundary is unchanged. Revision 1.2 is authoring only |

### 12.2 Resolved in Revision 1.3

| Item | Disposition |
|---|---|
| Q-VOCAB-1 touchdown semantics | **Resolved.** §1.6 |
| #50–52 versus #20–22 | **Resolved.** #50–52 retired as duplicates |
| #66/#81 and #70/#82 | **Resolved.** #81 and #82 retired; #66 and #70 retained |
| ZBB treatment of #44, #45, #47, #88 | **Resolved.** Retired with numbers and reasons preserved |
| Grammar treatment of new shapes | **Resolved.** §3.4. Closed grammar preserved |
| #43 negative fantasy points | **Resolved.** Clamped; both-zero is a defined score of 0 |
| Qualifier predicate structure | **Resolved.** §1.5. All 16 active `QUALIFIER` definitions structured |
| Product versus runtime eligibility | **Resolved.** §1.2 |

**Remains open:** §7.1 mid-season unblocking, §8 postseason, §12 items 1–6, and §13's four Yahoo-dependent items.

| Item | Disposition |
|---|---|
| #8–#12 unbound thresholds | **Resolved.** Retired under §1.7 |
| Runtime gate conflation | **Resolved.** §1.2 two gates |

### 12.3 Resolved in the 2026-08-01 correction pass

| Item | Disposition |
|---|---|
| #97/#98 incomplete field set | **Resolved by retirement, not repair.** Both retired (§1.1). Numbers and keys reserved permanently. All 80 active definitions now carry the identical Scope C1 field set |
| Kicker definition naming and basis | **Resolved.** §1.8. #18 Highest Scoring Kicker, #77 Highest Scoring Kicker Matchup, both on actual Yahoo fantasy points |
| `made_field_goal_distance` as a blocker | **Resolved.** Retained as unsupported historical/source documentation only; required by no active definition; blocks no active Pool |
| Tie-payout indivisible remainder | **Resolved.** §6.3 states the exact algorithm by owner ruling |
| Settlement idempotency | **Resolved at the product layer.** §6.4 requires atomic posting-plus-`settled` and event-keyed uniqueness. Implementation remains Stage H behind the Opus math review gate |
| Gate-1 / Gate-2 selectable-count contradiction | **Resolved.** §1.2. 64 is a ceiling; restored access clears one Gate-2 precondition only; the post-access count is never stated in advance |
