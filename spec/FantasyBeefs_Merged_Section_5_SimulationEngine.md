# Fantasy Beefs — Merged Hybrid · Section 5 — Simulation Engine

*Fair odds, model versioning, Handshake pricing, Dynamic refreshes, Final Lock,
and simulation audit.*

> **[HYBRID] Section-level note.** This is where the Row 2 (asymmetric stake
> derivation) and Row 3 (floor-both rounding) overrides become the stated
> pricing law, inside The Adjustment (5.10) and the rounding rule (SIM-807).
> Dynamic Challenge pricing (5.8–5.10) is LIVE per Row 1. "Simulation Engine" is
> the canonical name for what earlier docs called the "odds engine"; the certified
> JS Odds Calculator (Tab 5) is the reference math for the port. All money-path
> **[OPUS-GATED]**.

## 5.1 Purpose

The Simulation Engine prices Fantasy Beefs Versus Bets by producing reproducible
fair probabilities, fair odds, stake limits, and payout values. The Simulation
Engine does not determine actual wager winners. Actual outcomes are determined
solely by the settlement rules and official Yahoo Fantasy Football data
identified by the applicable Wager Definition.

## 5.2 Simulation Principles

**SIM-001 — Fair Pricing**
Every official probability and price SHALL be produced without vigorish,
commission, spread padding, or any other house advantage.

**SIM-002 — No House Position**
Fantasy Beefs SHALL NOT use the Simulation Engine to create a house-side
position, rebalance exposure for platform profit, or modify pricing based on
platform liability.

**SIM-003 — Deterministic Execution**
Given identical model code, model version, projection dataset, Yahoo inputs,
league scoring settings, random seed, and simulation count, the Simulation Engine
SHALL produce identical outputs.

**SIM-004 — Outcome Independence**
Simulation outputs estimate likelihood and price wagers only. They SHALL NOT
determine settlement, substitute for Yahoo results, or override a protocol-defined
Push or Void.

**SIM-005 — Reproducibility**
Every official simulation SHALL retain sufficient inputs, identifiers, and outputs
to be reproduced independently.

**SIM-006 — No Subjective Override**
No GM, Commissioner, administrator, or model operator may manually alter an
official probability, odds value, stake, payout, or simulation result after
publication.

## 5.3 Required Inputs

**SIM-101 — Yahoo Inputs**
Every simulation SHALL use the applicable Yahoo Fantasy Football data required by
the Wager Definition, including as relevant: league membership and team
ownership; league scoring rules; rosters and starting lineups; Fantasy Week and
Yahoo matchup schedule; player and team identifiers.

**SIM-102 — Projection Inputs**
Every simulation SHALL use the active Fantasy Beefs projection dataset identified
by an immutable dataset version.

**SIM-103 — Model Inputs**
Every simulation SHALL use one identified Simulation Model Version and its
associated configuration, distributions, correlation rules, simulation count, and
random-seed protocol.

**SIM-104 — Wager Definition Inputs**
Every simulation SHALL use the exact Wager Definition governing the challenge,
including covered entities, scoring aggregate, pricing method, Push condition, and
settlement shape.

**SIM-105 — Input Validation**
Before execution, the Simulation Engine SHALL validate that all required inputs
exist, reference the same League and Fantasy Week, and satisfy the Wager
Definition. An official simulation SHALL NOT run on incomplete or inconsistent
inputs.

**SIM-106 — Unavailable Projection**
If a required projection is unavailable, the System SHALL apply only the
deterministic fallback defined by the active model configuration. If no fallback
exists, the wager SHALL not be offered or SHALL Void at Final Lock as applicable.

## 5.4 Model Versioning

**SIM-201 — Version Identity**
Every Simulation Model Version SHALL have a unique immutable identifier.

**SIM-202 — Version Contents**
The version record SHALL identify the executable model logic and all model
configuration required to reproduce results, including distribution assumptions,
correlation rules, simulation count, precision rules, and random-seed method.

**SIM-203 — Active Version**
The System SHALL designate exactly one active model version for new offer pricing
at a given time.

**SIM-204 — No Retroactive Change**
Activating a new model version SHALL NOT alter any accepted or settled wager.

**SIM-205 — Locked Challenge Version**
A Locked Challenge SHALL retain the model version used to generate the accepted
odds even though no later repricing occurs.

**SIM-206 — Dynamic Challenge Freeze**
A Dynamic Challenge SHALL freeze its model version at Handshake. All later
informational refreshes and the official Final Lock simulation SHALL use that same
frozen version.

**SIM-207 — Projection Version Independence**
Freezing a model version does not freeze the projection dataset for a Dynamic
Challenge. Updated projections MAY be used before Final Lock while the model
version remains fixed.

## 5.5 Fair Probability Protocol

**SIM-301 — Outcome Space**
The Simulation Engine SHALL calculate probabilities only for the complete
mutually exclusive outcome space defined by the Wager Definition.

**SIM-302 — Probability Sum**
After protocol-defined precision and normalization, all outcome probabilities for
a wager SHALL sum to 100 percent.

**SIM-303 — Push Probability**
When a Push is possible, the Simulation Engine SHALL calculate or deterministically
derive a Push probability and SHALL exclude the Push from winning-side payout
conversion in the manner defined by the Wager Definition.

**SIM-304 — Precision**
Probabilities, odds, stakes, and payouts SHALL be calculated at internal precision
sufficient to avoid material rounding drift. Display rounding SHALL NOT alter
stored official values.

**SIM-305 — Fair Decimal Odds**
For an outcome with conditional win probability p after protocol-defined Push
treatment, fair decimal odds SHALL equal 1 divided by p.

> **[HYBRID] Probability clamp hoisted (FR-7.62).** The probability used for both
> odds and stake derivation SHALL be clamped once at the derivation site
> (`max(0.001, min(0.999, p))`), so odds AND stakes derive from the same bounded
> number. The raw simulated probability may be exactly 0.0 or 1.0; the clamp is a
> pure division-by-zero protection at width 0.001 (FR-7.66). Measure the actual
> probability distribution against real data before launch. **[OPUS-GATED]**

**SIM-306 — Equivalent Odds Formats**
American, fractional, or other displayed odds formats MAY be derived from the
stored fair probability or fair decimal odds. The stored fair probability and fair
decimal odds SHALL remain authoritative.

**SIM-307 — No Vig Normalization**
The System SHALL NOT reduce both sides' fair payouts to create an overround. Any
normalization SHALL only correct numerical precision so that the defined
probability space totals 100 percent.

## 5.6 Offer Pricing

**SIM-401 — Pre-Offer Simulation**
A Versus Bet offer requiring simulated odds SHALL be priced from a simulation
completed before the offer becomes Offered.

**SIM-402 — Offer Snapshot**
The offer SHALL store the pricing snapshot used to display its probabilities,
odds, proposed stake, maximum exposure, and potential payout.

> **[HYBRID]** The offer snapshot stores the issuer's Anchor Stake and the
> opponent's Derived Stake computed from preview odds. The both-sides $1 floor is
> checked here at issue (GE-302 [HYBRID]). (Rows 2, 7.)

**SIM-403 — Offer Expiration and Repricing**
An expired or cancelled offer SHALL not be revived using its prior pricing
snapshot. A new offer SHALL be repriced using current valid inputs.

**SIM-404 — Offer Visibility**
Both GMs SHALL see the same stored pricing snapshot for the same offer.
Client-side recalculation or display differences SHALL NOT alter official terms.

## 5.7 Locked Challenge Pricing

**SIM-501 — Accepted Price**
For a Locked Challenge, the pricing snapshot accepted by both GMs SHALL become the
official simulation record.

**SIM-502 — Frozen Terms**
At acceptance, official probabilities, odds, stake, payout, covered entity IDs,
model version, and projection dataset version SHALL freeze.

**SIM-503 — No Repricing**
A Locked Challenge SHALL NOT be repriced because of lineup edits, projection
changes, injuries, inactive status, weather, news, or later model versions.

**SIM-504 — Settlement Separation**
The official Locked Challenge simulation record SHALL remain available for audit
but SHALL not be consulted to determine the actual winner.

## 5.8 Dynamic Challenge Handshake

> **[HYBRID] LIVE per Row 1.** Requires **[PENDING CODE-VERIFY]** of the three
> odds write sites and the accept path before build.

**SIM-601 — Initial Simulation**
At Handshake, the System SHALL run and store an initial simulation using current
Yahoo data, the active projection dataset, the active model version, and the
accepted Wager Definition.

**SIM-602 — Handshake Outputs**
The Handshake simulation SHALL produce and record: initial outcome probabilities;
initial fair odds; maximum permitted stake for each side; maximum permitted payout
for each side; maximum possible loss and required Escrow for each GM; model version
and projection dataset version; random-seed and simulation-count identifiers;
covered Yahoo entity identifiers.

> **[HYBRID]** The per-side maximum stakes are the asymmetric Anchor and Derived
> stakes (Row 2), each floored to whole cents (Row 3). They are ceilings, not
> equal amounts. **[OPUS-GATED]**

**SIM-603 — Exposure Ceiling**
The Handshake maximums SHALL be immutable ceilings. No later simulation, projection
update, or lineup change may increase stake, payout obligation, maximum loss, or
Escrow above them.

**SIM-604 — Model Freeze**
The Simulation Model Version SHALL freeze at Handshake before the wager enters
Accepted.

**SIM-605 — Handshake Failure**
If the initial simulation, pricing, exposure calculation, or Escrow validation
cannot complete atomically, the Handshake SHALL fail and the offer SHALL remain
unaccepted or terminate according to the Game Engine. No partial record or partial
reservation may remain.

## 5.9 Informational Refreshes

**SIM-701 — Refresh Availability**
Either participating GM MAY request a Dynamic Challenge refresh before Final Lock,
subject to operational rate limits applied equally to both GMs.

**SIM-702 — Refresh Inputs**
A refresh MAY use the latest valid Yahoo lineups and active projection dataset
available at the refresh timestamp, but SHALL use the frozen Handshake model
version and accepted Wager Definition.

**SIM-703 — Refresh Outputs**
A completed refresh MAY display updated estimated probabilities, fair odds,
official-stake estimate, payout estimate, and expected Escrow refund.

**SIM-704 — Informational Status**
Every pre-lock refresh is informational only. It SHALL NOT change the accepted
wager, official terms, Handshake ceilings, Wallet balances, Escrow, Ledger, or
wager state.

**SIM-705 — Refresh Audit**
Each completed refresh SHALL record its timestamp, requester, input versions,
probabilities, odds, and estimates. A failed refresh SHALL record the failure
without altering the wager.

**SIM-706 — Unequal Viewing**
A refresh requested or viewed by one GM need not be separately requested or
acknowledged by the other GM. Both GMs SHALL nevertheless have access to the same
stored refresh result.

## 5.10 Final Lock Simulation

**SIM-801 — Single Official Run**
A Dynamic Challenge SHALL have exactly one official Final Lock simulation.

**SIM-802 — Final Lock Inputs**
The official simulation SHALL use: the final available Yahoo starting lineups
captured at Final Lock; the League scoring rules applicable to the Fantasy Week;
the active projection dataset at Final Lock; the model version frozen at Handshake;
the accepted Wager Definition and covered market; the protocol-defined random seed
and simulation count.

**SIM-803 — Final Lock Outputs**
The official simulation SHALL calculate official probabilities, fair odds, and the
values required by The Adjustment.

**SIM-804 — The Adjustment Inputs**
The Adjustment SHALL use only the official Final Lock outputs, Handshake ceilings,
accepted wager parameters, and protocol-defined pricing rules.

**SIM-805 — The Adjustment Sequence**

> **[HYBRID] Asymmetric derivation + floor-both (Rows 2, 3).** The sequence
> derives BOTH stakes before any cap or refund:

1. Compute the clamped official probabilities (SIM-305 [HYBRID]).
2. Derive `fairPot = anchor_stake / p_issuer`.
3. Derive `stake_opponent = floor(fairPot × p_opponent)`; the anchor is already
   whole cents. Both stakes are now whole BAB cents.
4. The uncollected residue (fairPot minus the sum of the two floored stakes,
   strictly under one cent) is NOT staked and posts nowhere.
5. Compare each derived stake with its Handshake ceiling; cap any value that
   exceeds it (SIM-806).
6. Determine each GM's official maximum loss from the (possibly capped) floored
   stakes.
7. Calculate excess Escrow as reserved Escrow minus official maximum loss.
8. Return excess Escrow to the originating Wallet through the Ledger.
9. Freeze official probabilities, odds, stake, payout, and covered entity IDs.

> **This OVERRIDES the spec's original deferral (old SIM-807) to the general
> remainder rule.** Floor-both/residue-uncollected is the stated law for Versus
> derivation. **Opus is invited to break it at Math Review** using an adversarial
> line (e.g. an anchor priced at −150 that does not divide clean); the test is
> that no fractional cent enters the Ledger and trial balance closes exactly.
> **[OPUS-GATED]**

**SIM-806 — No Increase**
The Adjustment SHALL preserve or reduce exposure. It SHALL NEVER increase stake,
payout obligation, loss, or Escrow after Handshake.

**SIM-807 — Rounding Order** *(overridden)*

> **[HYBRID] REPLACED.** The original SIM-807 deferred remainder treatment to the
> BAB Economy and Ledger protocols (which route remainders to Championship — a
> POOL rule). For Versus derivation this is superseded by the floor-both rule in
> SIM-805 [HYBRID]: both stakes floor to whole BAB cents at the derivation site,
> the residue is uncollected and never enters the Ledger, and no remainder is
> routed anywhere. Internal precision is applied before flooring. The
> round-direction question raised for equal stakes (round up, once, at
> acceptance) does NOT apply under asymmetry — floor-both is deterministic with no
> tiebreak and requires no "who eats the cent" policy. **[OPUS-GATED]**

**SIM-808 — Finality**
After Final Lock, no later projection dataset, model version, lineup change, or
simulation result may alter the official wager terms.

## 5.11 Failure and Void Protocol

**SIM-901 — Pre-Acceptance Failure**
If pricing cannot be completed before acceptance, the offer SHALL not become valid
or accepted.

**SIM-902 — Refresh Failure**
Failure of an informational refresh SHALL have no effect on the accepted wager or
Handshake record.

**SIM-903 — Final Lock Data Failure**
If required Final Lock inputs cannot be obtained or validated, the System SHALL
retry according to its deterministic operational policy until the lock deadline.
If the official simulation still cannot be completed, the wager SHALL Void and all
Escrow SHALL be refunded.

**SIM-904 — Non-Reproducible Result**
If an official simulation record lacks the information required for deterministic
reproduction, the wager SHALL not settle under that record. The System SHALL use a
valid idempotent retry if permitted before Final Lock; otherwise the wager SHALL
Void.

**SIM-905 — No Substitute Model**
The System SHALL NOT substitute a different model version at Final Lock when the
frozen model version is unavailable. The wager SHALL Void if the frozen version
cannot execute.

**SIM-906 — No Manual Estimate**
A human estimate, external sportsbook line, or discretionary probability SHALL
NEVER replace a required official simulation.

## 5.12 Simulation Audit

**SIM-1001 — Official Record Contents**
Every official simulation record SHALL contain: simulation record ID and wager ID;
League ID, Fantasy Week, and Specification version; simulation purpose (offer,
Locked acceptance, Handshake, refresh, or Final Lock); execution timestamp and
completion status; model version and model configuration identifier; projection
dataset version; Yahoo input snapshot identifiers; Wager Definition ID and covered
entity IDs; simulation count and random-seed identifier; outcome probabilities,
fair odds, and Push probability when applicable; calculated stake, payout,
exposure, and refund values when applicable; validation results and failure reason
when applicable.

**SIM-1002 — Immutability**
Completed official simulation records SHALL NOT be modified or deleted.

**SIM-1003 — Corrections**
A correction to simulation infrastructure SHALL create a new model version or new
operational record. It SHALL NOT rewrite a historical official simulation.

**SIM-1004 — Linkage**
Every accepted Versus Bet SHALL reference its authoritative pricing record. Every
Dynamic Challenge SHALL additionally reference its Handshake record and Final Lock
record.

**SIM-1005 — Reproduction**
An authorized audit process SHALL be able to rerun an official simulation and
compare its outputs with the stored record using the same deterministic inputs and
versioned code.

**SIM-1006 — Display vs. Stored Values**
Displayed rounded probabilities and odds MAY differ in formatting from stored
values. Audit and settlement-related calculations SHALL use the stored
authoritative values.

## 5.13 Simulation Engine Invariants

**SIM-INV-001** — Simulation pricing contains no house edge or vig.
**SIM-INV-002** — The Simulation Engine never determines the actual winner.
**SIM-INV-003** — Every accepted Versus Bet references one authoritative pricing
record.
**SIM-INV-004** — Every Dynamic Challenge freezes one model version at Handshake.
**SIM-INV-005** — Projection data may update before Dynamic Final Lock; the model
version may not.
**SIM-INV-006** — Informational refreshes never move BAB or change official terms.
**SIM-INV-007** — A Dynamic Challenge has exactly one official Final Lock
simulation.
**SIM-INV-008** — The Adjustment never increases post-Handshake exposure.
**SIM-INV-009** — Every official result is reproducible from immutable versioned
inputs.
**SIM-INV-010** — Failure to produce a valid required official simulation results
in rejection or Void, never discretionary pricing.

> **[HYBRID] SIM-INV-011** — Versus stakes are derived asymmetrically from fair
> odds (anchor ÷ p, times opponent p) and both floored to whole BAB cents; the
> uncollected residue never enters the Ledger. (Rows 2, 3.) **[OPUS-GATED]**

### End of Section 5

Section 5 governs fair pricing and simulation behavior. The merged-hybrid
overrides — asymmetric derivation (Row 2), floor-both rounding (Row 3, replacing
SIM-807), the hoisted probability clamp, and Dynamic-live pricing (Row 1) — are
the money-path core and the subject of the Opus Math Review. Sections 6–8 govern
system execution, configuration, and completion.
