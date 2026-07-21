# Fantasy Beefs — Merged Hybrid · Section 7 — League Configuration

*Season initialization, configurable parameters, commissioner authority, and
season close.*

> **[HYBRID] Section-level note.** Adds the five-stop commissioner economy slider
> (Row 7), Reserve/Frozen configuration (Row 6), the Weekly-Minimum sourcing and
> playoff-exemption config (Row 5 + postseason), and the Dynamic-mode enablement
> confirmation (Row 1). The slider values populate the otherwise-generic
> configurable amounts.

## 7.1 Purpose

League Configuration defines the parameters selected for one Fantasy Beefs League
season. Configuration determines which protocol-defined features are enabled and
supplies their permitted values. Configuration SHALL NOT override the deterministic
mechanics established in Sections 1 through 6.

## 7.2 Configuration Principles

**CFG-001 — One Configuration per Season**
Each Fantasy Beefs League season SHALL operate under exactly one active League
Configuration version at a time.

**CFG-002 — Configuration Scope**
A League Configuration applies only to its identified League and fantasy season.

**CFG-003 — Protocol Boundaries**
A configuration parameter MAY select among choices expressly permitted by this
Specification. It SHALL NOT create a new wager mechanic, accounting rule,
settlement rule, or Commissioner power.

**CFG-004 — Equal Application**
Unless a protocol expressly allows GM-specific treatment, every configured rule
SHALL apply equally to all eligible GMs in the League.

**CFG-005 — Integer BAB Values**
Every configurable BAB amount SHALL be expressed as integer BAB cents and SHALL
satisfy the minimum, maximum, and increment rules of the applicable protocol.

**CFG-006 — Configuration Audit**
Every creation, publication, permitted amendment, and archival action affecting
League Configuration SHALL generate an immutable audit record.

## 7.3 League Initialization

**CFG-101 — Initialization Requirement**
Before the first wager may be offered, the League SHALL complete and publish its
season configuration.

**CFG-102 — Required League Identity**
League ID and Yahoo League ID; fantasy season; Commissioner GM or authorized
Commissioners; eligible GM membership list; Specification version; Configuration
version and effective timestamp.

**CFG-103 — Yahoo Synchronization**
Initialization SHALL verify that Yahoo League membership, team ownership, scoring
configuration, matchup schedule, and season week structure are available and
internally consistent.

**CFG-104 — GM Mapping**
Each Fantasy Beefs GM SHALL map to exactly one Yahoo-managed fantasy team in the
League for the season. Duplicate or missing mappings SHALL block initialization.

**CFG-105 — Equal Initial BAB**
Every eligible GM SHALL receive the same configured initial BAB allocation unless a
future Specification expressly permits unequal issuance. Version 1.0 does not.

**CFG-106 — Publication**
The complete active configuration SHALL be visible to all eligible GMs before the
first accepted wager.

**CFG-107 — First-Acceptance Freeze**
The first accepted wager freezes all parameters designated as season-fixed under
this section.

## 7.4 Required Configurable Parameters

**CFG-201 — Initial BAB Allocation**
The League SHALL specify the amount of BAB issued to each eligible GM at season
initialization.

> **[HYBRID] Five-stop economy slider (Row 7).** Initial allocation is set via one
> of five discrete commissioner stops (no freeform). Each stop lands on round
> dollars by construction: wallet = weekly-min × 14 Yahoo weeks; reserve = 4/11
> (36.4%) of total buy-in. The stops:
>
> | Weekly min | Wallet | Buy-in | Reserve |
> |---|---|---|---|
> | $5 | $70 | $110 | $40 |
> | **$10 (default)** | **$140** | **$220** | **$80** |
> | $15 | $210 | $330 | $120 |
> | $20 | $280 | $440 | $160 |
> | $25 | $350 | $550 | $200 |
>
> `League.economy_stop_weekly_min_cents` is the sole source of truth; the other
> values derive from it. **[OPUS-GATED]**

**CFG-202 — Weekly Minimum**
The League SHALL specify whether a Weekly Minimum is enabled and, if enabled, the
required BAB commitment per GM per applicable Fantasy Week.

> **[HYBRID]** The Weekly Minimum amount is the selected stop's weekly-min value.
> Sourcing follows the auto-sequence (min pot first, then wallet; Row 5). Playoff
> weeks (default 15–17) are exempt from the mandatory Weekly Minimum; only the $1
> bet floor applies there.

**CFG-203 — Championship Pot**
The League SHALL specify whether the Championship Pot is enabled and its permitted
funding and distribution rules.

> **[HYBRID]** Default distribution 60/30/10 (1st/2nd/3rd), leftover cents to 1st.
> Funding includes Reserve sweeps and Weekly-Min shortfalls (Row 6).

**CFG-204 — Skunk Pot**
The League SHALL specify whether the Skunk Pot is enabled and, if enabled, the
weekly Skunk contribution and season-ending award rule.

> **[HYBRID]** Default $10/week, weeks 1–14, widest-margin loser pays; season pot
> to the regular-season Points-For leader.

**CFG-205 — Enabled Versus Types**
The League SHALL specify which of Moneyline, Spread, and Over/Under Versus Bets are
enabled. No other Versus type may be enabled under Version 1.0.

**CFG-206 — Enabled Challenge Modes**
For each enabled Versus Wager Definition, the League SHALL specify whether Locked,
Dynamic, or both challenge modes are available, subject to the Wager Definition.

> **[HYBRID] Dynamic is enabled at launch (Row 1).** The MVP ships with Dynamic
> mode available, not disabled. This requires the repricing trigger and The
> Adjustment. **[PENDING CODE-VERIFY]** / **[OPUS-GATED]**.

**CFG-207 — Pool Catalog**
The League SHALL specify the enabled Pool Wager Definitions from the approved Pool
Registry.

> **[HYBRID]** Launch Pool set: Biggest Winner, Special Teams Supremacy, The
> Lineup (rank); Bench Burn (prediction). Worst Beat is retired (duplicative of
> Skunk). The ~96-bet catalog is data under the common Pool Engine (AP-323);
> **[PENDING CATALOG READ]** to confirm every entry fits the two outcome shapes.

**CFG-208 — Pool Scheduling**
For each enabled Pool, the League SHALL specify or adopt its protocol-defined
occurrence schedule, including regular-season and postseason eligibility.

**CFG-209 — Top-Off Policy**
The League SHALL specify whether BAB Top-Off requests are permitted. If permitted,
every Top-Off remains subject to Commissioner approval and the BAB Economy
protocols.

**CFG-210 — Postseason Scope**
The League SHALL specify which wager definitions remain enabled during the Yahoo
postseason, provided the wager definition can be deterministically settled from
eligible Yahoo data.

> **[HYBRID] Postseason rules.** Versus bets require an active matchup for both
> GMs (eliminated/bye teams cannot participate as bettor or subject). Pool bets:
> anyone may wager; a Pool subject is eligible only if its roster still scores real
> points that week (`roster_scores(team_id, week)`), not on having an active
> matchup. Self-pick rules hold year-round. Config: `playoff_start_week` (15),
> `season_final_week` (17).

## 7.5 Weekly Minimum Configuration

**CFG-301 — Weekly Minimum Status**
The Weekly Minimum SHALL be either Enabled or Disabled for the entire season.

**CFG-302 — Weekly Minimum Amount**
If enabled, one nonnegative integer BAB amount SHALL apply equally to all eligible
GMs for each applicable week.

**CFG-303 — Applicable Weeks**
The League SHALL specify the first and last Yahoo weeks subject to the Weekly
Minimum. The range SHALL be fixed before first acceptance.

> **[HYBRID]** Default applicable weeks 1–14; playoff weeks exempt (Row 5 +
> postseason).

**CFG-304 — Qualifying Commitments**
All accepted BAB commitments that the BAB Economy defines as qualifying SHALL count
toward the configured Weekly Minimum. League Configuration SHALL NOT selectively
exclude individual GMs or accepted wagers.

**CFG-305 — Shortfall Destination**
Every Weekly Minimum shortfall SHALL transfer to the Championship Pot. If the
Championship Pot is disabled, the Weekly Minimum SHALL also be disabled.

> **[HYBRID]** The commissioner MAY instead select Frozen (`frozen:{team_id}`) as
> the unspent-min/shortfall destination. This choice is LOCKED at season kickoff,
> not adjustable mid-season. (Row 6.)

**CFG-306 — No Midweek Waiver**
The Commissioner SHALL NOT waive or reduce a GM's Weekly Minimum after the
applicable week opens.

## 7.6 Championship Pot Configuration

**CFG-401 — Championship Pot Status**
The Championship Pot SHALL be either Enabled or Disabled for the season.

**CFG-402 — Permitted Funding Sources**
Weekly Minimum shortfalls; equal-split integer remainders; season-end Pool rollover
sweeps; League-configured equal preseason contributions, if enabled; other funding
sources expressly defined by this Specification.

> **[HYBRID]** Add: season-end Reserve sweeps (Row 6).

**CFG-403 — No Discretionary Confiscation**
The Commissioner SHALL NOT transfer BAB from a GM Wallet to the Championship Pot
except through a published protocol-defined obligation.

**CFG-404 — Distribution Definition**
Before first acceptance, the League SHALL select one approved Championship Pot
distribution definition. The definition SHALL identify recipients, shares, tie
handling, and required Yahoo result fields.

> **[HYBRID]** Default definition: 60/30/10 by final Yahoo regular-season standing;
> leftover cents to 1st. (Row 6.)

**CFG-405 — Deterministic Recipient**
Every Championship Pot recipient SHALL be determinable from official Yahoo season
results or another protocol-defined immutable result. Commissioner selection is
prohibited.

**CFG-406 — Integer Distribution**
All Championship Pot distributions SHALL use integer BAB cents. Any final
indivisible remainder SHALL be assigned by the selected distribution definition; if
unspecified, it SHALL be awarded to the highest-priority recipient under that
definition.

**CFG-407 — Distribution Timing**
Distribution SHALL occur only after all season wagers, Pools, Weekly Minimum
assessments, Skunk assessments, and rollover sweeps are complete.

> **[HYBRID] CFG-408 — Reserve Configuration (Row 6).** The League SHALL specify
> whether the Reserve mechanic is enabled and, if so, the reserve fraction (default
> 4/11 of buy-in) and the weekly reserve-ceiling release formula. The choice of
> unspent-min destination (Championship sweep vs Frozen return) SHALL be fixed at
> season kickoff. **[OPUS-GATED]**

## 7.7 Skunk Pot Configuration

**CFG-501 — Skunk Pot Status**
The Skunk Pot SHALL be either Enabled or Disabled for the season.

**CFG-502 — Weekly Contribution**
If enabled, the League SHALL configure one equal integer BAB Skunk contribution
assessed against the weekly Skunk GM.

**CFG-503 — Weekly Skunk Definition**
The weekly Skunk GM SHALL be the GM suffering the largest official Yahoo margin of
defeat for the applicable week.

**CFG-504 — Skunk Tie**
If two or more GMs tie for the largest margin of defeat, each tied GM SHALL
contribute the full configured Skunk amount unless the approved Skunk definition
expressly specifies equal division. The selected rule SHALL be fixed before first
acceptance.

**CFG-505 — No Defeat**
A GM who ties or wins their Yahoo matchup SHALL NOT be the weekly Skunk. If no GM
records a defeat, no Skunk contribution is assessed for that week.

**CFG-506 — Applicable Weeks**
The League SHALL specify the regular-season weeks subject to Skunk assessment.
Postseason weeks SHALL be excluded unless the approved Skunk definition expressly
includes them.

**CFG-507 — Season Winner**
Under the default Version 1.0 Skunk distribution, the complete Skunk Pot SHALL be
awarded to the GM with the highest cumulative Yahoo regular-season Points For.

**CFG-508 — Season Winner Tie**
If multiple GMs tie for highest cumulative regular-season Points For, the Skunk Pot
SHALL be divided equally among them, with any indivisible BAB cent remainder
transferred to the Championship Pot.

**CFG-509 — Funding Failure**
If the assessed GM lacks sufficient available BAB, the Skunk obligation SHALL be
handled by the BAB Economy shortfall protocol and SHALL NOT be waived by the
Commissioner.

## 7.8 Versus Wager Configuration

**CFG-601 — Approved Registry Only**
A League MAY enable only Versus Wager Definitions contained in the published Version
1.0 Wager Definition Registry.

**CFG-602 — Permitted Types**
Every enabled Versus Wager Definition SHALL be Moneyline, Spread, or Over/Under.

**CFG-603 — Stake Bounds**
Each enabled Versus Wager Definition SHALL specify or inherit a minimum and maximum
BAB commitment. Bounds SHALL apply equally to every GM.

> **[HYBRID]** The structural minimum is the $1 bet floor (Row 7), applied to the
> issuer's Anchor Stake at issue and to the opponent's Derived Stake via the
> both-sides $1 floor (GE-302 [HYBRID]). A commissioner MAY raise the per-bet
> minimum to $5, which must divide the weekly-min. **[PENDING CODE-VERIFY]** —
> current code MIN_BET = 5.00; the $1 ruling is not yet built.

**CFG-604 — Allowed Increments**
Stake amounts SHALL use the increment specified by the Wager Definition or League
Configuration. The increment SHALL be an integer BAB cent amount.

**CFG-605 — Mode Compatibility**
A League SHALL NOT enable Dynamic mode for a Wager Definition that lacks
deterministic simulation and Adjustment support.

> **[HYBRID]** All three Versus types (Moneyline, Spread, O/U) support Dynamic mode
> at launch, since the Simulation Engine and The Adjustment are built for them
> (Row 1). **[PENDING CODE-VERIFY]**.

**CFG-606 — No Custom Lines after Acceptance**
League Configuration MAY define how lines or thresholds are generated or proposed
before acceptance but SHALL NOT permit Commissioner modification after acceptance.

**CFG-607 — Active Limit**
The Version 1.0 maximum of ten active Versus Bets per GM is protocol-fixed and SHALL
NOT be increased by League Configuration.

**CFG-608 — Offer Expiration**
The Version 1.0 one-hour offer expiration is protocol-fixed and SHALL NOT be
modified by League Configuration.

> **[HYBRID]** "One hour" equals the locked 60-minute response window; the
> effective window is the sooner of 60 minutes or the challenge's own kickoff.

## 7.9 Pool Configuration

**CFG-701 — Approved Pool Registry**
A League MAY enable only Pool Wager Definitions contained in the approved Pool
Registry for the governing Specification version.

**CFG-702 — Required Pool Properties**
Every enabled Pool SHALL retain its registered outcome shape, mechanic, option set
rule, metric, ordering, positive or negative classification, tie rule, Final Lock,
and settlement function.

**CFG-703 — Configurable Pool Properties**
Where the Pool Wager Definition permits, League Configuration MAY select the entry
fee, minimum participation, occurrence schedule, maximum tickets per GM, and
rollover status from the definition's approved values.

**CFG-704 — Self-Pick Rules Fixed**
League Configuration SHALL NOT override the Game Engine self-pick rules. Positive
Prediction self-picks remain permitted; negative Prediction self-picks remain
prohibited; Rank self-inclusion remains automatic.

**CFG-705 — Outcome Shape Fixed**
League Configuration SHALL NOT change a registered Pool outcome from Single-GM to
Matchup or from Matchup to Single-GM.

**CFG-706 — No Ad Hoc Pool**
A Commissioner SHALL NOT create an unregistered Pool, custom winning condition,
discretionary tiebreaker, or raw-stat outcome during the season.

**CFG-707 — Rollover Destination**
Every enabled rollover Pool SHALL use the registered next-occurrence rule. Any
unresolved final-season rollover SHALL transfer to the Championship Pot.

**CFG-708 — Insufficient Participation**
A Pool that fails its configured minimum participation SHALL Void and refund entry
fees; the Commissioner SHALL NOT force it to proceed.

## 7.10 BAB Top-Off Configuration

**CFG-801 — Top-Off Status**
BAB Top-Offs SHALL be either Permitted or Prohibited for the season.

**CFG-802 — Approval Requirement**
If permitted, each Top-Off request SHALL require explicit approval by an authorized
Commissioner before BAB issuance.

**CFG-803 — Published Limits**
The League MAY configure minimum, maximum, and season-total Top-Off limits, provided
they apply equally to all GMs.

**CFG-804 — No Selective Price or Terms**
Fantasy Beefs does not process real money. Any offline reconciliation associated
with Top-Offs is outside the platform and SHALL NOT alter the amount of BAB posted
by the approved request.

**CFG-805 — No Retroactive Funding**
A Top-Off SHALL NOT retroactively validate an offer or acceptance that failed for
insufficient BAB.

**CFG-806 — No Commissioner Balance Edit**
Commissioners SHALL use the Top-Off approval protocol and SHALL NOT directly edit
Wallet balances.

## 7.11 Commissioner Authority

**CFG-901 — Preseason Authority**
Create and publish the League Configuration; select approved enabled wager
definitions and approved parameter values; verify GM membership and Yahoo team
mappings; select authorized co-Commissioners, if supported; correct configuration
errors before the first accepted wager.

**CFG-902 — In-Season Authority**
Approve or reject BAB Top-Off requests when Top-Offs are enabled; maintain access
and membership records subject to the membership protocols; view audit and
reconciliation reports; initiate technical support without altering protocol
outcomes.

**CFG-903 — Prohibited Commissioner Actions**
Creating, accepting, rejecting, withdrawing, or selecting wagers for another GM;
cancelling or modifying accepted wagers; changing lines, odds, stakes, payouts,
picks, Pool entries, or locked participants; choosing a winner, tiebreaker, Push, or
Void result; editing Ledger, Wallet, Escrow, Pot, simulation, or audit records;
waiving a protocol-defined Weekly Minimum, Skunk contribution, or other BAB
obligation; applying unpublished or GM-specific rules.

**CFG-904 — Conflict of Roles**
A Commissioner who is also a GM retains the same wagering rights and restrictions as
every other GM. Commissioner status SHALL confer no gameplay advantage.

## 7.12 Configuration Changes

**CFG-1001 — Draft Changes**
Before publication, any configuration value MAY be changed within the choices
permitted by this Specification.

**CFG-1002 — Published Pre-Acceptance Changes**
After publication but before the first accepted wager, an authorized Commissioner
MAY amend the configuration. The amendment SHALL create a new configuration version
and notify all eligible GMs.

**CFG-1003 — Season-Fixed Parameters**
After the first accepted wager, the following SHALL NOT change for the season:
initial BAB allocation; Weekly Minimum status, amount, and applicable weeks;
Championship Pot funding and distribution definition; Skunk status, contribution,
applicable weeks, and distribution definition; Top-Off status and published limits;
enabled wager and Pool definitions, except disabling future creation under CFG-1005;
Specification version.

> **[HYBRID]** Also season-fixed at first acceptance: the economy stop (Row 7), the
> Reserve fraction and enablement, and the unspent-min destination (Championship vs
> Frozen) (Row 6).

**CFG-1004 — No Retroactive Change**
No configuration amendment SHALL alter an existing Offered, Accepted, Pending,
Final, Push, Void, Expired, or Cancelled wager.

**CFG-1005 — Emergency Prospective Disablement**
An authorized Commissioner or administrator MAY disable creation of new offers under
a Wager Definition when a technical or data defect prevents safe execution. Existing
accepted wagers SHALL continue under their recorded definition or follow
protocol-defined Void. Disablement SHALL be audited and SHALL NOT substitute a new
rule.

**CFG-1006 — Membership-Only Changes**
In-season membership changes SHALL follow the League Membership protocols and SHALL
NOT be used to evade existing obligations or alter historical records.

**CFG-1007 — Future Season Changes**
Any desired rule change not permitted in-season SHALL be configured only for a later
League season or future Specification version.

## 7.13 League Membership

**CFG-1101 — Initial Eligibility**
Only GMs mapped to active Yahoo teams at initialization SHALL receive initial BAB
and participate in Version 1.0 wagering.

**CFG-1102 — Midseason Join**
A new GM MAY join only if Yahoo recognizes a valid team ownership change or addition
and the System can deterministically map the GM to one team. The new GM SHALL receive
the League's initial BAB allocation unless the membership protocol in Section 8
specifies a prorated or replacement-owner treatment.

**CFG-1103 — Replacement Owner**
When a new GM replaces the owner of an existing Yahoo team, the League membership
record SHALL preserve the team's season identity while separately recording the
outgoing and incoming GM identities and effective timestamp.

**CFG-1104 — Existing Obligations**
A membership change SHALL NOT erase, reassign, or modify accepted wagers, Pool
tickets, Ledger records, Skunk obligations, Weekly Minimum obligations, or historical
audit records except as expressly defined by the controlling membership protocol in
Section 8.

**CFG-1105 — Departure**
A departing GM's historical records SHALL remain immutable. New wagering access SHALL
end at the recorded departure time.

**CFG-1106 — Commissioner Removal Limit**
A Commissioner MAY update membership to reflect authoritative Yahoo ownership but
SHALL NOT remove a GM solely to cancel a wager or avoid a BAB obligation.

## 7.14 Season Completion and Reset

**CFG-1201 — Season Close Preconditions**
All Versus Bets are in terminal states; all Pool occurrences are settled, Voided, or
swept under their rollover rules; all wager and Pool Escrow balances equal zero; all
Weekly Minimum and Skunk assessments are posted; the Championship Pot and Skunk Pot
are distributed; the Ledger reconciles exactly.

> **[HYBRID]** Add: all Reserve accounts swept to Championship; all Frozen accounts
> returned to Wallet; all weekly-min pot accounts zero. (Rows 5, 6.)

**CFG-1202 — Close Sequence**
1. Finalize the last applicable Yahoo week.
2. Settle or Void all remaining wagers and Pools.
3. Post final Weekly Minimum and Skunk obligations.
4. Sweep final Pool rollovers.
5. Distribute the Championship Pot.
6. Distribute the Skunk Pot.
7. Verify zero Escrow and Ledger reconciliation.
8. Create the season-close audit record.
9. Archive the League season.

> **[HYBRID]** Insert before step 5: sweep Reserve to Championship; return Frozen to
> Wallet. (Row 6.)

**CFG-1203 — Archive**
A closed season SHALL be read-only and permanently retain its configuration, Wager
Definitions, wagers, simulations, Ledger, and audit history.

**CFG-1204 — New Season**
A new fantasy season SHALL create a new season identity, new configuration, new
Wallet accounts, new Pots, and new wager records.

**CFG-1205 — No Automatic Carryover**
Wallet balances, Escrow, Pot balances, unresolved offers, and configuration choices
SHALL NOT carry into the new season unless an explicit Version 1.0 protocol directs
the transfer. Version 1.0 provides no general Wallet carryover.

**CFG-1206 — Historical Independence**
Creating a new season SHALL NOT modify or delete any prior-season record.

## 7.15 Configuration Invariants

**CFG-INV-001** — Every League season has one published configuration and one
governing Specification version.
**CFG-INV-002** — Every eligible GM receives the same initial BAB allocation.
**CFG-INV-003** — Only Moneyline, Spread, and Over/Under may be enabled as Versus
Bets.
**CFG-INV-004** — Only registered Pool Wager Definitions may be enabled.
**CFG-INV-005** — Configuration may select approved parameters but may not override
protocol mechanics.
**CFG-INV-006** — Season-fixed parameters do not change after the first accepted
wager.
**CFG-INV-007** — Commissioners administer configuration but do not control wager
outcomes.
**CFG-INV-008** — Every configuration change is versioned, visible, prospective, and
audited.
**CFG-INV-009** — Season close requires zero Escrow and exact Ledger reconciliation.

### End of Section 7

Section 7 defines the complete Version 1.0 configuration envelope, plus the
merged-hybrid additions: the five-stop economy slider (CFG-201), Reserve/Frozen
config (CFG-408), Dynamic-mode enablement (CFG-206), the $1 floor (CFG-603), and the
postseason scope (CFG-210). Section 8 controls completion and the verified additions.
