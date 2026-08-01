# FantasyStakes — Pool Catalog, Rotation & Settlement
# Product of Record, Revision 1.2

**Status:** Product of Record — current
**Date:** 2026-08-01
**Source artifact:** `FR-6_1_CATALOG_CLASSIFICATION.md` (96-row classified catalog)
**Machine-readable catalog:** `spec/pool_catalog_rev1_2.json`
**Implementation scope:** `spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_2.md`

**Revision 1.2 supersedes Revision 1.1 as the current Product of Record. Revisions 1.0 and 1.1 are retained unchanged as historical authority.**

---

## 0. Authority

> This document is the current Product of Record for FantasyStakes Pool catalog composition, Pool eligibility, weekly Pool rotation, Pool rollover behavior, Pool settlement classification, and Pool selection rules.
>
> Where current code, legacy pool constants, archived documents, UI mock data, or prior Pool concepts conflict with this POR, this POR governs product behavior unless a newer approved Pool POR explicitly supersedes it.
>
> UI/UX Rev 4.1 governs presentation only and does not redefine Pool mechanics.

This document is standalone. No reader needs Rev 3.x, the Rev3.1 POR register, transition packages, legacy `POOL_BET_TYPES`, or UI mock data to build the Pool product.

Current code is implementation evidence, never authority.

---

## 1. Catalog composition

The source artifact classifies **96** numbered definitions. Two are retired for anti-tanking. **94 are active.**

| Figure | Count | Derivation |
|---|---|---|
| Source catalog | 96 | `FR-6_1_CATALOG_CLASSIFICATION.md` |
| Retired for anti-tanking | 2 | #57, #96 |
| **Active** | **94** | 96 − 2 |
| Team-Level | 55 | #1–#55 |
| Matchup | 39 | 41 − #57 − #96 |
| Dependency-blocked | 9 | §7 |
| **Currently rotatable** | **85** | 94 − 9 |
| Rollover-eligible | 21 | All `QUALIFIER`; 20 rotatable, #7 blocked |

**Original catalog numbers 1..96 are preserved for provenance. The active 94 are not renumbered.** Numbers 57 and 96 are absent by retirement, not reassigned. Any future addition takes 97 onward.

### 1.1 Retired

| # | Name | Reason |
|---|---|---|
| 57 | Lowest Combined Passing Yards | Anti-tanking. Source marks self-pick **BLOCKED** — a QB-owning GM could deliberately throttle passing volume to win. |
| 96 | Defensive Slugfest | Anti-tanking. The only bet rewarding deliberately lower output on a fully controllable stat. Naming also unresolved. |
| — | The Lineup | **Legacy implementation name.** Never part of the 96-row catalog. Exists as a single-party `Bet.bet_type` settled by `settlement_engine._eval_the_lineup`. Retired from Pool scope. |
| — | Bench Burn | **Legacy implementation name.** Never part of the 96-row catalog. Present in `POOL_BET_TYPES` with no evaluator and no settlement branch. Retired from Pool scope. |

The Lineup and Bench Burn were never classified definitions. They are legacy constants retired from Pool scope, recorded here so no future reader mistakes them for catalog entries.

---

## 2. Anti-tanking rule

**No Pool may reward a GM for intentionally worsening their own team or lineup.**

Applied to all 96 at classification. Two failed and are retired. **All 94 active definitions allow self-pick.**

A `MIN`-direction definition is not automatically a tank vector. Fewest Interceptions, Fewest Fumbles Lost, Fewest Turnovers and their matchup equivalents reward avoiding real mistakes — an aligned incentive, no vector. Those carry `anti_tanking_review: REVIEWED_ALLOWED_ALIGNED_INCENTIVE`.

Any new definition must pass this review before entering the catalog.

---

## 3. Mechanic and evaluator families

**Mechanic and evaluator family are different axes. Do not conflate them.**

**Mechanic** is how a GM enters. All 94 active definitions are `PREDICTION` — the GM selects one team or one matchup. Every outcome resolves to one GM/team or one Yahoo matchup of exactly two GMs; a raw stat may *define* a contest but is never the selectable outcome. The `RANK` mechanic (auto-entry, no pick) has **no active definitions** following The Lineup's retirement.

**Evaluator family** is how the winner is computed.

| Family | Count | Behavior |
|---|---|---|
| `RANK_EXTREMUM` | 73 | Compute one value per subject, rank, return all tied at the extreme |
| `QUALIFIER` | 21 | Evaluate a boolean per subject, split among qualifiers, roll on zero |

### 3.1 Ruling — the catalog is metadata-driven

**The 94-definition catalog does NOT imply 94 bespoke evaluator functions.**

The intended architecture is two reusable evaluator families driven by declarative parameters: `scope`, `metric_expression`, `metric_kind`, `direction`, `threshold_condition`.

**Zero bespoke evaluators are currently required**, subject to resolution of the seven pending formula definitions (§7). If a formula proves inexpressible as a metric expression, that definition alone becomes bespoke. None currently looks likely to.

Adding a definition is a catalog row, not a deployment.

### 3.2 Aggregate-over-aggregate — binding

**Every `RATIO` definition computes `sum(numerator) / sum(denominator)` across the roster or matchup. It must never silently become an average of individual per-player ratios.**

The two produce different winners on the same data. This is a wrong-winner defect, not a crash, and it will not announce itself.

Rows requiring it carry `aggregate_over_aggregate_required: true`.

### 3.3 Zero-denominator — fail closed

Any `RATIO` definition whose denominator can be zero in a real week must **fail closed**, never divide, never coerce to zero, never award. Rows carry `zero_denominator_guard: true`.

Explicitly flagged in the source: #41 Best Roster Completion Percentage, #61 Best Combined Completion Percentage — both can face a week with no real pass attempts.

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

Rollover eligibility follows evaluator family. The 21 `QUALIFIER` definitions are rollover-eligible. The 73 `RANK_EXTREMUM` definitions are not. A `RANK_EXTREMUM` definition resolves to a winner or a tie for any valid non-empty subject set, so nothing is left to carry. A `QUALIFIER` definition may legitimately produce zero qualifying subjects, and that outcome follows the rollover lifecycle. `rollover_eligible` remains explicit per-definition metadata, never a derived value, even though every active Rev1.2 definition currently follows the family rule. A `RANK_EXTREMUM` definition that returns zero claimants over a complete, non-empty evaluated field is an invariant violation, not a rollover condition (§6.2).

**The legacy `worst_beat_rollover` boolean on `PoolConfig` is implementation debt, not product authority.** It is a single league-wide flag scoped to one retired definition. It must not be generalized into a product rule.

---

## 6. Settlement classification

**The table below applies only after §6.2 classification returns `ZERO_ELIGIBLE_CLAIMS` or `CLAIMS_PRESENT`. No other classification reaches it.**

| Outcome | Behavior |
|---|---|
| Single winner | Pot to the winner |
| Tie / multiple winners | **Even split.** Indivisible remainder resolved deterministically. Does not roll. |
| Zero eligible claims, rollover-eligible, before final week | Pot carries forward as a continuation. No posting. |
| Zero eligible claims, rollover-eligible, final week | Sweep to `championship:{league_id}`. Carry zeroed. |
| Zero eligible claims, not rollover-eligible | Sweep to `championship:{league_id}`. |

Default `tie_rule` is `EVEN_SPLIT` on all 94 rows.

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

**Reported distribution arithmetic is not governed here.** The `total_distributed_cents` correction remains linked FR-POOL-1 work and is not absorbed into this rule.

---

## 7. Dependency-blocked definitions

**9 definitions are blocked. They must never enter a slate while blocked.**

| # | Definition | Block |
|---|---|---|
| 7 | Recorded a Two-Point Conversion | Yahoo 2-pt scoring settings unconfirmed |
| 85 | Highest Combined Two-Point Conversions | Yahoo 2-pt scoring settings unconfirmed |
| 42 | Most Complete Offensive Production | Formula undefined |
| 43 | Best Run-Pass Balance | Formula undefined |
| 44 | Best Pass-Scrimmage Balance | Formula undefined |
| 45 | Most Balanced Skill Production | Formula undefined |
| 46 | Most Diverse Touchdown Production | Formula undefined |
| 47 | Most Diverse Scoring Production | Formula undefined |
| 88 | Highest Combined Scoring-Category Diversity | Formula undefined |

**Do not invent formulas for the seven.** The source artifact records them as undefined; each needs one explicit line before build. Their catalog rows carry `metric_expression: null` by design.

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

94 active definitions. Machine-readable form with complete metadata is `spec/pool_catalog_rev1_2.json`.

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
| 8 | `fixed_passing_yard_threshold` | Fixed Passing-Yard Threshold | T | QUAL | SIMP | — | Y | ok |
| 9 | `fixed_rushing_yard_threshold` | Fixed Rushing-Yard Threshold | T | QUAL | SIMP | — | Y | ok |
| 10 | `fixed_receiving_yard_threshold` | Fixed Receiving-Yard Threshold | T | QUAL | SIMP | — | Y | ok |
| 11 | `fixed_scrimmage_yard_threshold` | Fixed Scrimmage-Yard Threshold | T | QUAL | SIMP | — | Y | ok |
| 12 | `fixed_total_touchdown_threshold` | Fixed Total-Touchdown Threshold | T | QUAL | SIMP | — | Y | ok |
| 13 | `most_total_touchdowns` | Most Total Touchdowns | T | RANK | SIMP | MAX |  | ok |
| 14 | `most_total_offensive_yards` | Most Total Offensive Yards | T | RANK | SIMP | MAX |  | ok |
| 15 | `most_scrimmage_yards` | Most Scrimmage Yards | T | RANK | SIMP | MAX |  | ok |
| 16 | `most_skill_position_touchdowns` | Most Skill-Position Touchdowns | T | RANK | SIMP | MAX |  | ok |
| 17 | `most_dual_threat_yards` | Most Dual-Threat Yards | T | RANK | SIMP | MAX |  | ok |
| 18 | `most_kicking_points` | Most Kicking Points | T | RANK | SIMP | MAX |  | ok |
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
| 42 | `most_complete_offensive_production` | Most Complete Offensive Production | T | RANK | COMP | MAX |  | BLOCKED |
| 43 | `best_run_pass_balance` | Best Run-Pass Balance | T | RANK | COMP | MAX |  | BLOCKED |
| 44 | `best_pass_scrimmage_balance` | Best Pass-Scrimmage Balance | T | RANK | COMP | MAX |  | BLOCKED |
| 45 | `most_balanced_skill_production` | Most Balanced Skill Production | T | RANK | COMP | MAX |  | BLOCKED |
| 46 | `most_diverse_touchdown_production` | Most Diverse Touchdown Production | T | RANK | COMP | MAX |  | BLOCKED |
| 47 | `most_diverse_scoring_production` | Most Diverse Scoring Production | T | RANK | COMP | MAX |  | BLOCKED |
| 48 | `most_offensive_touches` | Most Offensive Touches | T | RANK | SIMP | MAX |  | ok |
| 49 | `most_offensive_opportunities` | Most Offensive Opportunities | T | RANK | SIMP | MAX |  | ok |
| 50 | `most_passing_production` | Most Passing Production | T | RANK | SIMP | MAX |  | ok |
| 51 | `most_rushing_production` | Most Rushing Production | T | RANK | SIMP | MAX |  | ok |
| 52 | `most_receiving_production` | Most Receiving Production | T | RANK | SIMP | MAX |  | ok |
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
| 77 | `highest_combined_kicker_points` | Highest Combined Kicker Points | M | RANK | SIMP | MAX |  | ok |
| 78 | `highest_combined_yards_per_touch` | Highest Combined Yards per Touch | M | RANK | RATI | MAX |  | ok |
| 79 | `highest_combined_yards_per_opportunity` | Highest Combined Yards per Opportunity | M | RANK | RATI | MAX |  | ok |
| 80 | `highest_combined_passing_efficiency` | Highest Combined Passing Efficiency | M | RANK | RATI | MAX |  | ok |
| 81 | `highest_combined_rushing_efficiency` | Highest Combined Rushing Efficiency | M | RANK | RATI | MAX |  | ok |
| 82 | `highest_combined_receiving_efficiency` | Highest Combined Receiving Efficiency | M | RANK | RATI | MAX |  | ok |
| 83 | `fewest_combined_fumbles_lost` | Fewest Combined Fumbles Lost | M | RANK | SIMP | MIN |  | ok |
| 84 | `matchups_where_neither_team_lost_a_fumble` | Matchups Where Neither Team Lost a Fumble | M | QUAL | SIMP | — | Y | ok |
| 85 | `highest_combined_two_point_conversions` | Highest Combined Two-Point Conversions | M | RANK | SIMP | MAX |  | BLOCKED |
| 86 | `fewest_combined_turnovers` | Fewest Combined Turnovers | M | RANK | SIMP | MIN |  | ok |
| 87 | `matchups_with_zero_total_turnovers` | Matchups With Zero Total Turnovers | M | QUAL | SIMP | — | Y | ok |
| 88 | `highest_combined_scoring_category_diversity` | Highest Combined Scoring-Category Diversity | M | RANK | COMP | MAX |  | BLOCKED |
| 89 | `matchups_with_10plus_combined_tds` | Matchups with 10+ Combined TDs | M | QUAL | SIMP | — | Y | ok |
| 90 | `matchups_with_500plus_combined_rushing_yards` | Matchups with 500+ Combined Rushing Yards | M | QUAL | SIMP | — | Y | ok |
| 91 | `matchups_with_700plus_combined_offensive_yards` | Matchups with 700+ Combined Offensive Yards | M | QUAL | SIMP | — | Y | ok |
| 92 | `matchups_where_both_teams_scored_a_passing_td` | Matchups Where Both Teams Scored a Passing TD | M | QUAL | SIMP | — | Y | ok |
| 93 | `matchups_where_both_teams_scored_a_rushing_td` | Matchups Where Both Teams Scored a Rushing TD | M | QUAL | SIMP | — | Y | ok |
| 94 | `matchups_where_both_teams_had_100plus_rushing_yards` | Matchups Where Both Teams Had 100+ Rushing Yards | M | QUAL | SIMP | — | Y | ok |
| 95 | `matchups_where_neither_team_threw_an_interception` | Matchups Where Neither Team Threw an Interception | M | QUAL | SIMP | — | Y | ok |

---

## 11. Conformance checklist

1. Exactly 4 active Pools per fantasy week
2. Catalog contains 94 active definitions, numbers 1..96 with 57 and 96 absent
3. No active definition is renumbered
4. All 94 allow self-pick; the 2 anti-tanking failures are retired, not blocked
5. The Lineup and Bench Burn are unreachable as Pools
6. Two evaluator families cover the catalog; zero bespoke evaluators
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
19. The 9 blocked definitions never enter a slate
20. Weekly contribution is league-level, divided across active pools, remainder to `championship:{league_id}`
21. Final-week expiry uses `season_final_week`, never a hardcoded 14
22. No formula is invented for the seven pending definitions
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

---

## 12. Open items

| # | Item | Blocks |
|---|---|---|
| 1 | **Postseason 32-subset list** — not located | Postseason activation |
| 2 | **Seven formula definitions** — #42–47, #88 | 7 of 94 |
| 3 | **Yahoo 2-pt scoring confirmation** — #7, #85 | 2 of 94 |
| 4 | **Mid-season unblocking behavior** — live or frozen | Eligible-set computation |
| 5 | **`season_final_week` / `playoff_start_week` reader** — ruled, unbuilt | Expiry and phase transition |
| 6 | **Live cutover policy** if shipping mid-season | Migration timing |

This POR governs the presentation and behavior of these. It does not resolve them.

### 12.1 Resolved in Revision 1.2

**No row in the table above is closed by Revision 1.2.** None of the six was the empty-result question.

| Item | Recorded at | Disposition |
|---|---|---|
| Governed behavior when an evaluator returns an empty result set | vol. II 22.22 | **Product layer resolved.** The rule now exists at §6.2. The implementation split is unchanged — Stage H, Opus math review gate |
| FR-POOL-1 | vol. II 22.20 | Remains **OPEN**. Its blocking product dependency is discharged. `total_distributed_cents` remains its own linked requirement |
| FR-POOL-2 | vol. II 22.21 | Remains **OPEN**. Its blocking product dependency is discharged. The named domain error is specified at §6.2 |
| FR-POOL-AUTH-1 | vol. II 22.23 | Remains **OPEN**. The Option B boundary is unchanged. Revision 1.2 is authoring only |
