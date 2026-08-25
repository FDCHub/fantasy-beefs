# FantasyStakes — Pool Catalog, Rotation & Settlement
# Product of Record, Revision 1.4

| | |
|---|---|
| **Artifact** | `spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_4.md` |
| **Revision** | 1.4 |
| **Status** | **Product of Record — current** |
| **Adopted** | 2026-08-21, by owner ruling |
| **Machine-readable catalog** | `spec/pool_catalog_rev1_4.json` |
| **Canonical stat vocabulary** | `spec/pool_stat_vocabulary_rev1_0.json` |
| **Supersedes** | `spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_3.md` and `spec/pool_catalog_rev1_3.json` |
| **Implementation scope** | `spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_3.md` |

> **This document is the current Product of Record** for FantasyStakes Pool
> catalog composition, Pool eligibility, weekly Pool rotation, Pool rollover
> behavior, Pool settlement classification, and Pool selection rules.
>
> Revision 1.3 is **superseded** and is retained UNCHANGED as historical
> authority. Revisions 1.0, 1.1 and 1.2 remain historical. No superseded
> revision may be edited.
>
> Where current code, legacy pool constants, archived documents, UI mock data,
> or prior Pool concepts conflict with this POR, this POR governs product
> behavior unless a newer approved Pool POR explicitly supersedes it.

**THIS IS A DELTA DOCUMENT AND SAYS SO.** Revision 1.4 changes three things and
carries the rest of Revision 1.3 forward by reference, item by item, in §8.
Reading §8 is not optional: it is the list of what still governs, and every rule
named there is unchanged and remains binding under this revision.

---

## 0. What this revision is, and what it is not

Rev 1.4 makes exactly three changes.

1. **Public names.** The `display_name` of the 64 currently
   runtime-eligible definitions is replaced with a branded name (§5).
2. **A new governed field.** `public_question` carries the plain-English question
   a GM answers, per definition (§3).
3. **The weekly scope composition.** The normal four-Pool regular-season slate
   is **3 TEAM + 1 MATCHUP** (§4.2).

It changes **nothing else**. No key, no predicate, no `metric_expression`, no
threshold, no scope, no `evaluator_shape`, no `evaluator_family`, no eligibility
flag, no rollover flag, no tie rule, no `self_pick_rule`, no `data_dependency`,
no economics, no settlement classification, no postseason rule.

`test_s4_pool_catalog_unit.py` asserts that field by field across all 80
definitions and the retired block, against `pool_catalog_rev1_3.json`, and
requires **zero governed-field drift**. That assertion runs on every invocation;
it is not a claim made once at authoring time.

### 0.1 Why the names changed

The Rev 1.3 names are accurate and unusable as a brand. Sixty-four contests were
named in the register's own voice — *Most Passing Yards*, *Highest Combined
Yards per Reception*, *Matchups Where Both Teams Had 100+ Rushing Yards* — with
a mean length of 28.6 characters and a worst case of 54. On a phone card they
read as database rows, because that is what they were.

Every Rev 1.4 name is at most four words and at most 18 characters, and
every one is strictly shorter than the Rev 1.3 name the card rendered before it.
No card can grow, wrap further, or overflow as a result of adoption.

### 0.2 Why a question field came with them

The application derived its pick prompt from **scope alone**:

> Which team do you think takes this Prop Pool?

That sentence was the same on all sixty-four. It told a GM what kind of thing to
tap and nothing whatsoever about what the contest measured. A branded name laid
on top of it would have made the surface *less* legible, not more: *Kicker
Chaos* above *"Which team do you think takes this Prop Pool?"* asks a GM to
guess.

So the name and the question are adopted together, as a pair. The question
carries the meaning the name is now allowed to stop carrying.

### 0.3 Why a name change is a catalog revision at all

Because the names are governed. All eighty Rev 1.3 display names appear verbatim
in the Rev 1.3 POR; two of them were fixed by a dated binding owner ruling
(Rev 1.3 §1.8); and `test_s4_pool_catalog_unit.py` enforced those two by string
equality. A display name in this product is not a label the UI owns. It is
catalog content, and changing it is a catalog revision.

---

## 1. Supersession

### 1.1 What Rev 1.4 supersedes

| Superseded | Replaced by |
|---|---|
| `spec/pool_catalog_rev1_3.json` | `spec/pool_catalog_rev1_4.json` |
| `spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_3.md` | this document |
| The 64 Rev 1.3 public display names listed in §5 | the 64 Rev 1.4 names listed in §5 |
| The Rev 1.3 §1.8 kicker NAMING ruling | §2 of this document |
| The unconstrained four-slot draw of Rev 1.3 §4 | the scope composition of §4.2 |

`betting.pool_catalog.CATALOG_PATH` resolves to `spec/pool_catalog_rev1_4.json`.
`betting.pool_catalog.CATALOG_PATH_REV1_3` is retained so suites can load the
superseded artifact deliberately, which is what makes the zero-drift assertion
possible; no runtime path reads it.

### 1.2 Keys are immutable, and this revision relies on that

Rev 1.3 §1.8, carried forward without change:

> A key is an immutable identifier and does not track a display name.

Every persisted `pool_instance.definition_key` therefore survives adoption
untouched, and every settled Pool in every league keeps pointing at the same
definition it always did. `betting.pool_rotation.digest_for` hashes
`definition_key`, `league_id`, `season` and `rotation_cycle` — **never
`display_name`** — so the ORDERING of the candidate ranking is bit-identical
before and after adoption. A league mid-season sees its Pools renamed; it does
not see them re-ranked.

The **composition** of §4.2 does change which of the ranked candidates a week
draws. That is a deliberate, ruled change to selection and is treated as such in
§4.2, separately from the naming pass.

---

## 2. Kicker definition names — owner ruling, 2026-08-21, binding

**This section supersedes the NAMING half of Rev 1.3 §1.8, and nothing else in
it.**

Rev 1.3 §1.8 was a dated binding owner ruling (2026-08-01) that fixed both
kicker contests by name and disposed of *their* predecessors in the same breath.
That ruling was about naming as well as scoring, so it could not be superseded
by implication. The owner ruling of 2026-08-21 supersedes it explicitly:

| # | Rev 1.3 name (superseded) | **Rev 1.4 name (binding)** | Scope |
|---|---|---|---|
| 18 | Highest Scoring Kicker | **Kicker Chaos** | TEAM |
| 77 | Highest Scoring Kicker Matchup | **Kicker Duel** | MATCHUP |

The Rev 1.4 proposal offered *Double Kickers* for #77. It was **refused**;
*Kicker Duel* is the ruled name.

### 2.1 The scoring basis is unchanged and was not open

Both contests continue to settle on **actual Yahoo fantasy football points
scored under the league's governing Yahoo scoring settings**, carried by the
canonical operand `kicking_points`:

- **#18** compares the actual Yahoo fantasy points of each TEAM subject's active
  starting kicker.
- **#77** sums the actual Yahoo fantasy points of the two active starting kickers
  in each scheduled MATCHUP subject.

Neither is computed from raw field-goal counts, from made-field-goal distance,
or from any `3 × FG + 1 × XP` reconstruction. Yahoo scores field goals by
distance bracket, so a count-based reconstruction would produce a different
winner than the league's own scoring. **Nothing in Rev 1.4 touches this.** The
Rev 1.3 §1.8 scoring ruling survives verbatim and remains binding.

Persisted keys are unchanged: #18 remains `most_kicking_points` and #77 remains
`highest_combined_kicker_points`.

### 2.2 The superseded names

*Highest Scoring Kicker* and *Highest Scoring Kicker Matchup* are superseded and
must not appear on any surface. So are their own predecessors, *Most Kicking
Points* and *Highest Combined Kicker Points*, which Rev 1.3 §1.8 retired and
which this ruling does not revive.

---

## 3. The `public_question` field

### 3.1 Definition

`public_question` is a governed presentation string carrying the question a GM
is answering when they make a pick. It is:

- **plain English**, with no catalog vocabulary — no operand names, no
  `SUM_BOTH_TEAMS`, no `EACH_TEAM`, no scope enum
- **specific to the metric**, so the offered choices make sense
- **silent about configurable numbers.** #89, #90, #91 and #94 carry
  `threshold_configurable: true`. Their questions say *"the target"* rather than
  a literal, because a league that reconfigured one would otherwise be shown a
  number its own settlement does not use. The exact condition still renders from
  `threshold_condition` on the Pool detail surface.

### 3.2 Authority — the catalog, and no settlement power

**THE CATALOG IS AUTHORITATIVE.** No surface may compose a question from scope,
from a key, or from a display name. The scope-derived prompt is retained in
`web/js/league.js::poolQuestion` as a fallback for exactly two cases — the demo
fixture, and a definition the catalog left without a question (§7) — and is
never preferred over a served question.

`public_question` carries **no settlement authority whatsoever**. Where a
question and a `predicate`, `metric_expression` or `threshold_condition` could
be read as disagreeing, the governed field wins and the question is the defect.
This mirrors the existing treatment of `display_terms` in the proposal
lifecycle, which is non-authoritative by the same rule and for the same reason.

### 3.3 It is absent on the 16 non-drawable definitions

Only definitions a league can actually draw carry one. See §7. A reader must
therefore handle `NULL` permanently, and the column may never be tightened to
NOT NULL on the strength of "they are all populated now".

### 3.4 Runtime plumbing — adopted in full

| # | Site | What it carries |
|---|---|---|
| 1 | `betting.pool_catalog.PoolDefinitionSpec.public_question` | parsed beside `display_name` |
| 2 | `db.schema.PoolDefinition.public_question` | `VARCHAR NULL` |
| 3 | `migrations/add_pool_definition_public_question.py`, manifest `0008_pool_definition_public_question` | one additive nullable column |
| 4 | `betting.pool_catalog.seed_definitions` | `row.public_question = spec.public_question`, rewritten in place on every re-seed |
| 5 | `api.main.PoolSlotOut.public_question` | served beside `display_name` |
| 6 | `web/js/pool-slate-model.js` → `question` | carried through the slate read model |
| 7 | `web/js/league.js::poolQuestion` | prefers the served question; scope fallback only |
| 8 | `web/js/data/league-data.js` | the four illustrative rows, in lockstep with the catalog |

---

## 4. Rotation — amended

### 4.1 What is unchanged

Every rotation rule of Rev 1.3 §4 survives verbatim and remains binding:

- **Exactly 4 active Pools per fantasy week.** Not three, not a variable count.
- Selection is **system-driven and auditable**. Every draw is a persisted row
  carrying week, slot, cycle and lineage.
- **Rollover continuations are placed first.** Each occupies one normal slate
  slot.
- **No regular-season repeat while unused eligible definitions remain.**
- Fresh draws are tracked by `rotation_cycle`.
- **A rollover continuation does not count as fresh use in the new cycle.**
- The selector excludes carried definitions from the same-week fresh candidate
  pool.
- **A cycle resets only when the remaining unused eligible set cannot satisfy
  the required fresh slots** — at the draw that cannot be satisfied, not at a
  week boundary and not on a schedule.
- **Every reset is auditable** — one row recording league, season, cycle,
  opening week, and eligible-set size at open.
- The SHA-256 digest ranking and its pinned serialization are **untouched**. The
  payload, the key order, the separators, the ascii flag, the field types and
  the tie-breakers are all exactly as Rev 1.1 pinned them, so every historical
  cycle ordering remains reproducible and audit reconstruction still works.
- §4.1 activation depth is unchanged: technical validity requires at least 4
  fully supported eligible definitions.

### 4.2 Weekly scope composition — owner ruling, 2026-08-21, binding

> **The normal four-Pool REGULAR-phase weekly slate is 3 TEAM + 1 MATCHUP.**

**WHY THIS IS A RULING AND NOT A PREFERENCE.** Rev 1.3 imposed no composition at
all: the selector ranked the whole eligible set by digest and took the top four.
Of the 64 runtime-eligible definitions, 29 are
MATCHUP-scoped, so an unconstrained ordering routinely produced weeks that were
mostly matchup-vs-matchup contests — measured on the governed eligible set, a
1 TEAM / 3 MATCHUP week. That shape was an accident of a hash, not a product
decision. This section makes the decision.

**IT IS APPLIED IN THE SELECTOR, NOT ON A SURFACE.** The composition is enforced
inside `betting.pool_rotation.build_week_slate`, before any `pool_instance` row
is written. A presentation filter that hid a drawn Pool, or reordered cards to
look like a different mix, would leave the persisted week disagreeing with the
week a GM was shown.

#### 4.2.1 The allocation rule

Continuations are placed first and are never displaced — each holds a live pot.
The quota is therefore expressed as a **deficit** against what the carries have
already contributed:

```
deficit(scope) = max(0, target(scope) - carried(scope))
```

Fresh slots are handed out in the **declared order of the mix** — TEAM, then
MATCHUP. Because the targets sum to the slot count, the deficits sum to at least
the fresh-slot count in every carry configuration, so the allocation is total;
the order only ever decides which deficit is TRIMMED when carries have
over-filled the other scope. Pinning that order is what makes the outcome
deterministic in every carry configuration.

| Carries | Fresh slots | TEAM quota | MATCHUP quota |
|---|---|---|---|
| none | 4 | 3 | 1 |
| 1 TEAM | 3 | 2 | 1 |
| 1 MATCHUP | 3 | 3 | 0 |
| 2 MATCHUP | 2 | 2 | 0 |
| 3 TEAM | 1 | 0 | 1 |
| 4 TEAM | 0 | 0 | 0 |

#### 4.2.2 Composition decides membership; ranking still decides order

Each scope takes its quota off the top of its own slice of the same global
digest ranking. The chosen definitions are then laid into slots in **global rank
order**, so a slate reads exactly as it always did and the composition changes
only WHICH four definitions a week draws.

#### 4.2.3 Shortfall — cross-scope fallback

"Exactly 4 active Pools per fantasy week" (§4.1) is the stronger invariant. If a
scope cannot fill its share from its own unused eligible candidates, the
shortfall is filled from the remaining candidates of the other scope through the
**same** digest ranking, in rank order.

A cycle reset is still signalled **only** when the TOTAL unused eligible set
cannot fill the total fresh slots. The composition is a preference about shape
and is never a second exhaustion condition.

#### 4.2.4 What the composition does not do

- It does not weaken catalog eligibility. Both gates are evaluated exactly as
  before, and the composition sees only the set that already passed them.
- Blocked and source-incomplete definitions remain non-drawable.
- No definition may appear twice in one slate. Carried keys and keys already
  used fresh in the cycle are subtracted BEFORE ranking, as they always were,
  and the composition selects from what survives that subtraction.
- Rollover behaviour is unchanged.
- Economics are unchanged. Slot count, entry, funding split, pot handling and
  settlement are untouched.

#### 4.2.5 The postseason is excluded

The composition governs the REGULAR phase four-slot slate only. The postseason
subset is fixed and the championship round is themed by
`CHAMPIONSHIP_PREFERRED_KEYS` (WP1B §12); imposing a scope quota there would
fight the theme. A caller requesting a slot count the mix was not written for
receives the pre-Rev-1.4 pure ranking rather than a silently rescaled quota no
owner ruled on.

#### 4.2.6 Where the rule lives

`spec/pool_catalog_rev1_4.json::weekly_slate_composition` carries the ruling as
data, because the mix is a product ruling and the catalog is where product
rulings live. `betting.pool_rotation.DEFAULT_SCOPE_MIX` carries it as the pure
selector's default, because that module performs no I/O and may not read a file.
`betting.pool_catalog.load_catalog` **refuses to load** any catalog whose block
disagrees with that constant — reason `SCOPE_MIX_MISMATCH` — so the artifact and
the code cannot drift apart.

---

## 5. The naming set — 64 definitions

Grouped by scope, ordered by catalog number. "Mechanic" is the governed rule as
it stands after Rev 1.3 and is **unchanged** by this revision.

Constraints held across the whole set: **no duplicate names**, maximum **four
words**, maximum **18 characters**.

Four names in the Rev 1.4 proposal were revised by the owner on adoption and are
marked **[amended]**; a fifth, #84, was revised to satisfy §6 and is marked
**[§6]**. Every other proposal name — including those the proposal itself flagged
for owner attention — is owner-accepted as written.

### 5.1 TEAM scope — 35 definitions

| # | Key | Rev 1.3 name | **Rev 1.4 name** | Public question | Mechanic |
|---|---|---|---|---|---|
| 1 | `the_grand_slam` | The Grand Slam | **Grand Slam** | Which team scores a passing, rushing and receiving touchdown and a field goal? | Qualifier: `passing_td >= 1 AND rushing_td >= 1 AND receiving_td >= 1 AND field_goals_made >= 1` |
| 2 | `passing_rushing_receiving_td_trifecta` | Passing-Rushing-Receiving TD Trifecta | **Triple Threat** | Which team scores a passing, a rushing and a receiving touchdown? | Qualifier: `passing_td >= 1 AND rushing_td >= 1 AND receiving_td >= 1` |
| 3 | `recorded_both_a_rushing_and_receiving_td` | Recorded Both a Rushing and Receiving TD | **Ground and Air** | Which team scores both a rushing and a receiving touchdown? | Qualifier: `rushing_td >= 1 AND receiving_td >= 1` |
| 4 | `recorded_a_passing_and_rushing_td` | Recorded a Passing and Rushing TD | **Arm and Legs** | Which team scores both a passing and a rushing touchdown? | Qualifier: `passing_td >= 1 AND rushing_td >= 1` |
| 5 | `recorded_a_passing_and_receiving_td` | Recorded a Passing and Receiving TD | **Pitch and Catch** | Which team scores both a passing and a receiving touchdown? | Qualifier: `passing_td >= 1 AND receiving_td >= 1` |
| 6 | `recorded_both_a_td_and_a_field_goal` | Recorded Both a TD and a Field Goal | **Six and Three** | Which team scores both a touchdown and a field goal? | Qualifier: `total_touchdown_credits >= 1 AND field_goals_made >= 1` |
| 13 | `most_total_touchdowns` | Most Total Touchdowns | **Touchdown Machine** | Which team scores the most touchdowns? | MAX `sum(total_touchdowns)` |
| 14 | `most_total_offensive_yards` | Most Total Offensive Yards | **Every Yard** | Which team gains the most total offensive yards? | MAX `sum(offensive_yards)` |
| 15 | `most_scrimmage_yards` | Most Scrimmage Yards | **Scrimmage Kings** | Which team gains the most rushing and receiving yards combined? | MAX `sum(rushing_yards + receiving_yards)` |
| 16 | `most_skill_position_touchdowns` | Most Skill-Position Touchdowns | **Skill Show** | Which team's runners and receivers score the most touchdowns? | MAX `sum(rushing_td + receiving_td)` |
| 17 | `most_dual_threat_yards` | Most Dual-Threat Yards | **Dual Threat** | Which team's quarterback gains the most passing and rushing yards combined? | Highest individual `passing_yards + rushing_yards` among active QB-eligible starters |
| 18 | `most_kicking_points` | Highest Scoring Kicker | **Kicker Chaos** | Which team gets the most fantasy points from its kicker? | MAX `sum(kicking_points)` — actual Yahoo points, active starting kicker |
| 19 | `most_total_scoring_events` | Most Total Scoring Events | **Scoring Spree** | Which team records the most touchdowns, field goals and extra points? | MAX `sum(touchdowns + field_goals + extra_points)` |
| 20 | `most_passing_yards` | Most Passing Yards | **Air Raid** | Which team throws for the most yards? | MAX `sum(passing_yards)` |
| 21 | `most_rushing_yards` | Most Rushing Yards | **Ground Game** | Which team runs for the most yards? | MAX `sum(rushing_yards)` |
| 22 | `most_receiving_yards` | Most Receiving Yards | **Catch Crew** | Which team gains the most receiving yards? | MAX `sum(receiving_yards)` |
| 23 | `most_passing_touchdowns` | Most Passing Touchdowns | **Air Mail** | Which team throws the most touchdowns? | MAX `sum(passing_td)` |
| 24 | `most_rushing_touchdowns` | Most Rushing Touchdowns | **Goal Line Grind** | Which team runs in the most touchdowns? | MAX `sum(rushing_td)` |
| 25 | `most_receiving_touchdowns` | Most Receiving Touchdowns | **Touchdown Catches** | Which team catches the most touchdowns? | MAX `sum(receiving_td)` |
| 26 | `most_field_goals_made` | Most Field Goals Made | **Field Goal Fest** | Which team makes the most field goals? | MAX `sum(field_goals_made)` |
| 27 | `most_extra_points_made` | Most Extra Points Made | **Extra Credit** | Which team makes the most extra points? | MAX `sum(extra_points_made)` |
| 28 | `fewest_interceptions_thrown` | Fewest Interceptions Thrown | **Clean Pocket** | Which team throws the fewest interceptions? | **MIN** `sum(interceptions_thrown)` |
| 29 | `fewest_fumbles_lost` | Fewest Fumbles Lost | **Sure Hands** | Which team loses the fewest fumbles? | **MIN** `sum(fumbles_lost)` |
| 30 | `fewest_total_turnovers` | Fewest Total Turnovers | **Ball Security** | Which team gives the ball away the fewest times? | **MIN** `sum(interceptions_thrown + fumbles_lost)` |
| 31 | `highest_yards_per_touch` | Highest Yards per Touch | **Touch Value** | Which team gains the most yards per touch? | MAX `sum(yards) / sum(touches)` |
| 35 | `highest_yards_per_rush` | Highest Yards per Rush | **Hit the Hole** | Which team gains the most yards per carry? | MAX `sum(rushing_yards) / sum(rush_attempts)` |
| 36 | `highest_yards_per_reception` | Highest Yards per Reception | **Big Targets** | Which team gains the most yards per catch? | MAX `sum(receiving_yards) / sum(receptions)` |
| 38 | `highest_rushing_td_rate` | Highest Rushing TD Rate | **Pay Dirt Rate** | Which team runs in a touchdown on the highest share of its carries? | MAX `sum(rushing_td) / sum(rush_attempts)` |
| 39 | `highest_receiving_td_rate` | Highest Receiving TD Rate | **End Zone Rate** | Which team catches a touchdown on the highest share of its catches? | MAX `sum(receiving_td) / sum(receptions)` |
| 40 | `highest_tds_per_touch` | Highest TDs per Touch | **Score Rate** | Which team scores a touchdown on the highest share of its touches? | MAX `sum(touchdowns) / sum(touches)` |
| 42 | `most_complete_offensive_production` | Week's Top Offense | **Squad Points** | Which team's starters score the most fantasy points? | MAX fantasy points of active starters at QB/RB/WR/TE/Flex/Superflex/K, excluding D/ST |
| 43 | `best_run_pass_balance` | Best Run-Pass Balance | **Balanced Attack** | Which team splits its fantasy points most evenly between the run and the pass? | MAX `min(run_pts, pass_pts) / max(run_pts, pass_pts)`; RB vs WR+TE, excluding QB/K/D-ST |
| 48 | `most_offensive_touches` | Most Offensive Touches | **Heavy Usage** **[amended]** | Which team's starters get the most touches? | MAX `sum(touches)` |
| 54 | `most_rushing_attempts` | Most Rushing Attempts | **Carry Count** | Which team runs the ball the most times? | MAX `sum(rush_attempts)` |
| 55 | `most_receptions` | Most Receptions | **Catch Count** | Which team's receivers make the most catches? | MAX `sum(receptions)` |

### 5.2 MATCHUP scope — 29 definitions

| # | Key | Rev 1.3 name | **Rev 1.4 name** | Public question | Mechanic |
|---|---|---|---|---|---|
| 56 | `highest_combined_passing_yards` | Highest Combined Passing Yards | **Air Show** | Which matchup produces the most passing yards between the two teams? | MAX `sum(both teams passing_yards)` |
| 58 | `highest_combined_passing_tds` | Highest Combined Passing TDs | **Passing Duel** | Which matchup produces the most passing touchdowns between the two teams? | MAX `sum(both teams passing_td)` |
| 62 | `fewest_combined_interceptions` | Fewest Combined Interceptions | **No Picks** | Which matchup produces the fewest interceptions between the two teams? | **MIN** `sum(both teams interceptions_thrown)` |
| 63 | `highest_combined_rushing_yards` | Highest Combined Rushing Yards | **Ground War** | Which matchup produces the most rushing yards between the two teams? | MAX `sum(both teams rushing_yards)` |
| 64 | `highest_combined_rushing_tds` | Highest Combined Rushing TDs | **Rushing Duel** | Which matchup produces the most rushing touchdowns between the two teams? | MAX `sum(both teams rushing_td)` |
| 65 | `most_combined_rushing_attempts` | Most Combined Rushing Attempts | **Run Heavy** | Which matchup sees the most rushing attempts between the two teams? | MAX `sum(both teams rush_attempts)` |
| 66 | `highest_combined_yards_per_rush` | Highest Combined Yards per Rush | **Carry Value** | Which matchup averages the most yards per carry across both teams? | MAX `sum(both teams rushing_yards) / sum(both teams rush_attempts)` |
| 67 | `highest_combined_receiving_yards` | Highest Combined Receiving Yards | **Catch Fest** | Which matchup produces the most receiving yards between the two teams? | MAX `sum(both teams receiving_yards)` |
| 68 | `highest_combined_receptions` | Highest Combined Receptions | **Catch Traffic** | Which matchup produces the most catches between the two teams? | MAX `sum(both teams receptions)` |
| 69 | `highest_combined_receiving_tds` | Highest Combined Receiving TDs | **Receiving Duel** | Which matchup produces the most receiving touchdowns between the two teams? | MAX `sum(both teams receiving_td)` |
| 70 | `highest_combined_yards_per_reception` | Highest Combined Yards per Reception | **Catch Value** | Which matchup averages the most yards per catch across both teams? | MAX `sum(both teams receiving_yards) / sum(both teams receptions)` |
| 71 | `highest_combined_offensive_yards` | Highest Combined Offensive Yards | **Yardage Battle** | Which matchup produces the most total offensive yards? | MAX `sum(both teams offensive_yards)` |
| 72 | `highest_combined_scrimmage_yards` | Highest Combined Scrimmage Yards | **Scrimmage Slugfest** | Which matchup produces the most rushing and receiving yards combined? | MAX `sum(both teams scrimmage_yards)` |
| 73 | `highest_combined_offensive_tds` | Highest Combined Offensive TDs | **End Zone Party** | Which matchup produces the most offensive touchdowns? | MAX `sum(both teams offensive_td)` |
| 74 | `highest_combined_touches` | Highest Combined Touches | **Touch Total** | Which matchup sees the most touches between the two teams? | MAX `sum(both teams touches)` |
| 76 | `shootout_of_the_week` | Shootout of the Week (Highest Combined Fantasy Points) | **Shootout** | Which matchup produces the highest combined fantasy score? | MAX `None` |
| 77 | `highest_combined_kicker_points` | Highest Scoring Kicker Matchup | **Kicker Duel** **[amended]** | Which matchup produces the most kicker fantasy points between the two teams? | MAX `sum(both teams kicking_points)` — actual Yahoo points, both active starting kickers |
| 78 | `highest_combined_yards_per_touch` | Highest Combined Yards per Touch | **Touch Efficiency** **[amended]** | Which matchup averages the most yards per touch across both teams? | MAX `sum(both teams yards) / sum(both teams touches)` |
| 83 | `fewest_combined_fumbles_lost` | Fewest Combined Fumbles Lost | **Sticky Fingers** | Which matchup loses the fewest fumbles between the two teams? | **MIN** `sum(both teams fumbles_lost)` |
| 84 | `matchups_where_neither_team_lost_a_fumble` | Matchups Where Neither Team Lost a Fumble | **Fumble Free** **[§6]** | Which matchup ends with neither team losing a fumble? | Qualifier: `SUM_BOTH_TEAMS(fumbles_lost) == 0` |
| 86 | `fewest_combined_turnovers` | Fewest Combined Turnovers | **Ball Control** | Which matchup produces the fewest turnovers between the two teams? | **MIN** `sum(both teams interceptions_thrown + fumbles_lost)` |
| 87 | `matchups_with_zero_total_turnovers` | Matchups With Zero Total Turnovers | **Turnover Free** | Which matchup ends with no turnovers by either team? | Qualifier: `SUM_BOTH_TEAMS(interceptions_thrown + fumbles_lost) == 0` |
| 89 | `matchups_with_10plus_combined_tds` | Matchups with 10+ Combined TDs | **Touchdown Frenzy** | Which matchup clears the combined touchdown target? | Qualifier: `SUM_BOTH_TEAMS(total_touchdown_credits) >= threshold_value` (default 10, configurable) |
| 90 | `matchups_with_500plus_combined_rushing_yards` | Matchups with 500+ Combined Rushing Yards | **Ground Explosion** | Which matchup clears the combined rushing-yards target? | Qualifier: `SUM_BOTH_TEAMS(rushing_yards) >= threshold_value` (default 500, configurable) |
| 91 | `matchups_with_700plus_combined_offensive_yards` | Matchups with 700+ Combined Offensive Yards | **Yardage Explosion** | Which matchup clears the combined offensive-yards target? | Qualifier: `SUM_BOTH_TEAMS(offensive_yards) >= threshold_value` (default 700, configurable) |
| 92 | `matchups_where_both_teams_scored_a_passing_td` | Matchups Where Both Teams Scored a Passing TD | **Trading Touchdowns** | Which matchup sees both teams throw a touchdown? | Qualifier: `EACH_TEAM(passing_td >= 1)` |
| 93 | `matchups_where_both_teams_scored_a_rushing_td` | Matchups Where Both Teams Scored a Rushing TD | **Both on the Ground** | Which matchup sees both teams run in a touchdown? | Qualifier: `EACH_TEAM(rushing_td >= 1)` |
| 94 | `matchups_where_both_teams_had_100plus_rushing_yards` | Matchups Where Both Teams Had 100+ Rushing Yards | **Ground Tandem** **[amended]** | Which matchup sees both teams clear the rushing-yards target? | Qualifier: `EACH_TEAM(rushing_yards >= threshold_value)` (default 100, configurable) |
| 95 | `matchups_where_neither_team_threw_an_interception` | Matchups Where Neither Team Threw an Interception | **Pick Free** | Which matchup ends with neither team throwing an interception? | Qualifier: `SUM_BOTH_TEAMS(interceptions_thrown) == 0` |

### 5.3 Owner amendments applied on adoption

| # | Proposal name | **Adopted name** | Authority |
|---|---|---|---|
| 48 | Workload | **Heavy Usage** | Owner revision, 2026-08-21 |
| 77 | Double Kickers | **Kicker Duel** | Owner ruling, 2026-08-21 (§2) |
| 78 | Efficiency Battle | **Touch Efficiency** | Owner revision, 2026-08-21 |
| 84 | Clean Hands | **Fumble Free** | §6 convention, 2026-08-21 |
| 94 | Two Ground Games | **Ground Tandem** | Owner revision, 2026-08-21 |

#18 **Kicker Chaos** was approved as proposed.

---

## 6. The fewest-vs-zero naming convention — binding

> **MIN / FEWEST contests use ordinary branded football language.
> EXACT-ZERO qualifiers reserve "Free" terminology.**

A *fewest* contest and an *exact-zero* contest over the same statistic are two
genuinely different Pools, and the Rev 1.4 proposal named several of them in
ways a GM could confuse — *Sticky Fingers* beside *Clean Hands*, both hand
metaphors, one a MIN and one a `== 0`. The convention removes the ambiguity by
reserving one word for one mechanic.

**THE NAME DESCRIBES THE EXISTING MECHANIC.** No predicate, direction, threshold
or evaluator shape was altered to fit a name. #84 was renamed to satisfy the
convention; the other eight already did.

### 6.1 The MIN contests — no "Free"

| # | Scope | Name | Metric |
|---|---|---|---|
| 28 | TEAM | **Clean Pocket** | `sum(interceptions_thrown)` |
| 29 | TEAM | **Sure Hands** | `sum(fumbles_lost)` |
| 30 | TEAM | **Ball Security** | `sum(interceptions_thrown + fumbles_lost)` |
| 62 | MATCHUP | **No Picks** | `sum(both teams interceptions_thrown)` |
| 83 | MATCHUP | **Sticky Fingers** | `sum(both teams fumbles_lost)` |
| 86 | MATCHUP | **Ball Control** | `sum(both teams interceptions_thrown + fumbles_lost)` |

### 6.2 The exact-zero qualifiers — "Free" reserved

| # | Scope | Name | Predicate |
|---|---|---|---|
| 84 | MATCHUP | **Fumble Free** | `SUM_BOTH_TEAMS(fumbles_lost) == 0` |
| 87 | MATCHUP | **Turnover Free** | `SUM_BOTH_TEAMS(interceptions_thrown + fumbles_lost) == 0` |
| 95 | MATCHUP | **Pick Free** | `SUM_BOTH_TEAMS(interceptions_thrown) == 0` |

### 6.3 Scope of the rule

The active catalog contains exactly 6 MIN contests and
3 exact-zero qualifiers, and every one is listed above, so the
convention is currently exhaustive. It is nevertheless a RULE and not a list:
any future definition in either family must follow it, and
`test_s4_pool_catalog_unit.py` enforces it by reading `direction` and `predicate`
rather than by checking a hard-coded set of numbers.

---

## 7. The 16 definitions deliberately left alone

Sixteen definitions keep their Rev 1.3 names and receive **no**
`public_question`, because no league can currently draw them. Branding a contest
nobody can play would put a name into the register that has never appeared on a
surface and may not be right by the time it does.

**Blocked — `dependency_state: BLOCKED` (3)**

| # | Key | Name kept |
|---|---|---|
| 7 | `recorded_a_two_point_conversion` | Recorded a Two-Point Conversion |
| 46 | `most_diverse_touchdown_production` | Most Diverse Touchdown Production |
| 85 | `highest_combined_two_point_conversions` | Highest Combined Two-Point Conversions |

**Enabled but source-mapping incomplete — not `definition_runtime_eligible`
(13)**

#32, #33, #34, #37, #41, #49, #53, #59, #60, #61, #75, #79, #80 — all gated on `opportunities`, `pass_attempts` or
`completions`, which the provider does not currently supply.

When a dependency resolves, that definition should be branded in the revision
that unblocks it, as part of the same ruling. Their mechanics are unchanged by
Rev 1.4 in every respect.

---

## 8. What Rev 1.3 carries forward, unchanged and binding

Every ruling in Revision 1.3 that is not a public name, not the §1.8 kicker
NAMING ruling, and not the unconstrained four-slot draw survives **verbatim**.
Named explicitly because each has been the subject of a prior owner ruling or a
conformance item:

- **§0 Authority** — the POR governs over code, legacy constants, archived
  documents and UI mock data.
- **§1.1 Retirement** — retired numbers and keys are reserved PERMANENTLY and
  never reused: #8–#12, #44, #45, #47, #50–#52, #81, #82, #88, #97, #98.
- **§1.2 Two gates** — Gate 1 `definition_runtime_eligible` is persistent
  definition metadata; Gate 2 `league_activation_ready` is transient environment
  state and is never stored on a definition. The selector requires BOTH.
  64 remains a Gate-1 CEILING, not a forecast.
- **§1.3 The global active-starter rule.**
- **§1.4 Canonical stat vocabulary** — aliases resolve to canonical names before
  the evaluator boundary; the evaluator never sees an alias.
- **§1.5 Structured qualifier predicates** — `threshold_condition` is prose and
  is NEVER evaluated; `predicate` is the executable form.
- **§1.6 Touchdown-credit semantics** (owner ruling Q-VOCAB-1).
- **§1.7 Catalog completeness principle** — a definition requiring commissioner
  interpretation to become mathematically complete is not eligible for the
  active catalog.
- **§1.8 Kicker SCORING basis** (owner ruling 2026-08-01) — see §2.1 above. Only
  the naming half of §1.8 is superseded.
- **§2 Anti-tanking rule.**
- **§3.1 The catalog is metadata-driven** (AP-323).
- **§3.2 Aggregate-over-aggregate**, **§3.3 zero-denominator fail-closed**,
  **§3.4 the eight governed evaluator shapes.**
- **§4 Rotation** — carried forward as §4.1 above, amended only by §4.2.
- **§5 Rollover** — rollover eligibility follows evaluator family: the 16
  QUALIFIER definitions are rollover-eligible, the 64
  RANK_EXTREMUM definitions are not. Rollover fires only on
  `ZERO_ELIGIBLE_CLAIMS`. Ties settle and never roll.
- **§6 Settlement classification**, **§6.1 entry economics**, **§6.2 the
  subject-census rule**, **§6.3 the EVEN_SPLIT indivisible-remainder algorithm**
  (owner ruling 2026-08-01), **§6.4 settlement idempotency.**
- **§7 Dependency-blocked definitions** and **§7.1 mid-season unblocking.**
- **§8 Postseason**, as resolved by WP1B: 44 definitions `postseason_eligible`,
  and the WP1B §5 prohibition on MATCHUP/RANK_EXTREMUM in the postseason, which
  `load_catalog` refuses to let a later edit undo.
- **§9 Season boundary.**
- **§11 The single weekly lock moment.**
- **§12 / §13** open items and Yahoo-dependent unresolved items.

---

## 9. Adoption record and conformance

### 9.1 What adoption required, and what was done

| Step | Result |
|---|---|
| Owner ruling on the kicker names | #18 Kicker Chaos approved; #77 ruled **Kicker Duel**, *Double Kickers* refused (§2) |
| Owner rulings on the flagged names | #48, #78, #94 revised; all other flagged names accepted as written (§5.3) |
| Fewest-vs-zero convention | Adopted; #84 renamed **Fumble Free** (§6) |
| Governed-field drift | **Zero**, asserted field by field across all 80 definitions and the retired block |
| Catalog `status` | `Product of Record` |
| `betting.pool_catalog.CATALOG_PATH` | `spec/pool_catalog_rev1_4.json` |
| `public_question` plumbing | All eight sites (§3.4) |
| Migration | `0008_pool_definition_public_question`, additive, one nullable column |
| Weekly scope composition | 3 TEAM + 1 MATCHUP, enforced in the selector (§4.2) |
| Rev 1.3 artifacts | Untouched on disk, superseded, retained as historical authority |

### 9.2 Conformance items this revision adds

Each is asserted by a suite, not by this document.

1. The runtime catalog is Rev 1.4 and its `status` is `Product of Record`.
2. Rev 1.3's artifacts are byte-unchanged and carry `status`
   `Product of Record` in their own historical sense — they are superseded by
   this document, not edited.
3. All 64 runtime-eligible definitions carry a non-empty
   `display_name` and a non-empty `public_question`.
4. The 16 non-drawable definitions carry no `public_question` and are
   mechanically identical to Rev 1.3.
5. No two active definitions share a `display_name`.
6. The five owner-amended names and the two kicker names are exact.
7. No MIN contest's name contains "Free"; every exact-zero qualifier's does
   (§6).
8. A REGULAR four-slot draw over the governed eligible set is 3 TEAM +
   1 MATCHUP.
9. The draw is deterministic: the same inputs produce the same slate in every
   process.
10. `load_catalog` refuses a catalog whose `weekly_slate_composition` disagrees
    with `DEFAULT_SCOPE_MIX`.
11. `public_question` reaches the browser from the server and is never composed
    client-side from scope.

---

*End of Revision 1.4. Revision 1.3 is superseded and retained as historical
authority.*
