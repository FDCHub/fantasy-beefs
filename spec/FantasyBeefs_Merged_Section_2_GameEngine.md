# Fantasy Beefs — Merged Hybrid · Section 2 — Game Engine

*Common wager lifecycle, Versus Bets, Pool Bets, Final Lock, and settlement.*

> **[HYBRID] Section-level note.** Dynamic Challenges (2.10, 2.11) are **LIVE at
> launch** — this reverses the prior "no-drift" Ruling 1, which described the
> current code, not the product. Building Dynamic requires the repricing trigger
> and The Adjustment, both **[PENDING CODE-VERIFY]** and **[OPUS-GATED]**. Versus
> stake derivation is asymmetric (2.8) per Row 2.

## 2.1 Purpose

The Game Engine governs creation, acceptance, locking, settlement, and
finalization of every Fantasy Beefs wager. Common behavior is defined once in
the Wager Lifecycle. Versus Bets and Pool Bets inherit that lifecycle and add
only their unique mechanics.

## 2.2 Wager Classes and Definitions

**GE-001 — Supported Wager Classes**
Fantasy Beefs supports exactly two wager classes: Versus Bet and Pool Bet.

**GE-002 — Versus Bet Definition**
A Versus Bet is a challenge between exactly two GMs. Only three Versus Bet types
are permitted: Moneyline, Spread, Over/Under.

**GE-003 — Pool Bet Definition**
A Pool Bet is a multi-participant wager whose winning outcome is represented
exclusively by either one GM name or one Yahoo matchup consisting of two GM
names.

**GE-004 — Wager Definition Registry**
Every enabled wager SHALL be represented by an immutable Wager Definition. A
Wager Definition SHALL specify all data required for validation, pricing,
locking, and settlement. New wager definitions MAY be added without modifying
the Game Engine if they comply with this Specification.

## 2.3 Common Wager Lifecycle

**GE-101 — Lifecycle States**
Every wager SHALL occupy exactly one state: Draft, Offered, Accepted, Pending,
Final, Expired, Cancelled, Push, Void.

**GE-102 — Permitted State Transitions**
Draft → Offered. Offered → Accepted, Expired, or Cancelled. Accepted → Pending,
Cancelled, or Void. Pending → Final, Push, or Void.

**GE-103 — Terminal States**
Final, Expired, Cancelled, Push, and Void are terminal. A terminal wager SHALL
NOT transition to another state.

**GE-104 — Atomic State Change**
Every state transition SHALL be atomic. If any required validation, Ledger
posting, audit record, or data write fails, no part of the transition SHALL
persist.

**GE-105 — Idempotency**
A repeated request for an already completed transition SHALL return the original
result and SHALL NOT create duplicate state changes, Ledger entries, or audit
records.

## 2.4 Week Timeline

**GE-201 — Fantasy Week Opening**
A Fantasy Week opens for wager creation when Yahoo exposes the applicable week
and Fantasy Beefs has synchronized the league, roster, lineup, schedule, and
scoring configuration required by the enabled wager definitions.

**GE-202 — Offer Window**
Offers MAY be created only while the applicable Wager Definition remains open for
the referenced Fantasy Week.

**GE-203 — Acceptance Window**
An offer MAY be accepted only before both its one-hour expiration and the
applicable wager lock, whichever occurs first.

**GE-204 — Final Lock**
Each wager locks at its protocol-defined Final Lock. No participant action may
alter the wager after Final Lock.

**GE-205 — Competition Period**
After Final Lock, the wager remains Pending while Yahoo records and corrects the
applicable fantasy results.

**GE-206 — Yahoo Finalization**
Settlement SHALL occur after Yahoo finalizes the required weekly data. Yahoo stat
corrections received before Fantasy Beefs settlement SHALL apply. Changes
received after settlement SHALL NOT reopen or modify the wager.

**GE-207 — Later Weeks**
Finalization of one week SHALL NOT prevent creation of offers for a later Yahoo
week when the later week is available and the applicable Wager Definition is
open.

## 2.5 Offer Protocol

**GE-301 — Offer Creation**
A valid offer SHALL record: League ID and Fantasy Week; Wager Class and Wager
Definition ID; Offering GM and required participant or participant field; Wager
mode when applicable; Proposed BAB commitment; All wager parameters required by
the Wager Definition; Creation timestamp and expiration timestamp.

> **[HYBRID]** For a Versus Bet, "Proposed BAB commitment" is the issuer's
> **Anchor Stake** only. The opponent's Derived Stake is computed by the
> Simulation Engine and displayed; it is not entered by either GM. (Row 2.)

**GE-302 — Offer Validation**
Before an offer becomes Offered, the System SHALL verify: the creator is an
authenticated, active GM in the League; the referenced week and Wager Definition
are open; all parameters satisfy the Wager Definition; the offer is not a
prohibited duplicate; the creator does not exceed the active Versus Bet limit;
any required immediate reservation is fully funded.

> **[HYBRID] Both-sides $1 floor at issue.** For a Versus Bet, the System SHALL
> reject offer creation if either the Anchor Stake or the Derived Stake computed
> from preview odds would fall below the $1 structural floor. Checked at issue
> against preview odds, before any escrow. Cleared at issue = cleared for good;
> not re-checked at acceptance even though acceptance recomputes odds. Message
> names the number, e.g. "Too lopsided. At these odds your opponent would only
> put up $0.40 — under the $1 minimum. Raise your stake or pick a different
> beef." (Rows 2, 7.) **[OPUS-GATED]**

**GE-303 — One-Hour Expiration**
An unanswered offer expires exactly one hour after creation or at the applicable
wager lock, whichever occurs first.

**GE-304 — Expiration Priority**
Acceptance SHALL be rejected when received at or after the expiration timestamp,
even if the offer remained visible on a participant screen.

**GE-305 — Withdrawal**
The offering GM MAY withdraw an unanswered offer before acceptance. A withdrawn
offer becomes Cancelled immediately.

**GE-306 — Rejection**
A required participant MAY reject an offer before acceptance. A rejected offer
becomes Cancelled immediately.

**GE-307 — Concurrent Actions**
When acceptance, rejection, withdrawal, or expiration compete, the first valid
action committed by the System SHALL govern. All later actions SHALL return the
terminal result and have no additional effect.

**GE-308 — No BAB Movement While Offered**
Offer creation, viewing, rejection, withdrawal, and expiration SHALL NOT transfer
BAB unless the Wager Definition explicitly requires a temporary reservation. Any
such reservation SHALL be released when the offer terminates without acceptance.

> **[HYBRID] Escrow-at-issue for Versus Bets.** The issuer's Anchor Stake
> escrows at ISSUE (challenge creation), not only at accept, superseding the old
> soft-reservation-only model. On decline or expiry, the issuer's escrowed
> anchor reverses out of escrow back to wallet/min. A pending-bucket check
> (wallet + remaining min, minus all pending and locked commitments) gates every
> new bet so a GM can never commit more than he holds. Reversal/un-escrow on
> decline or expiry is required. (Money-model ruling.) **[OPUS-GATED]**

## 2.6 Eligibility, Duplicates, and Limits

**GE-401 — League Eligibility**
All participants in a wager SHALL be active GMs in the same Fantasy Beefs League
for the referenced season.

**GE-402 — Self-Challenge**
A GM SHALL NOT create or accept a Versus Bet against themselves.

**GE-403 — Cross-Matchup Eligibility**
A GM MAY challenge any other eligible GM in the League regardless of the official
Yahoo weekly matchup.

**GE-404 — Duplicate Versus Bets**
Two active Versus Bets are duplicates when they have identical League, Fantasy
Week, wager type, participating GMs, direction, line or threshold, covered Yahoo
entities, and settlement condition. A duplicate request SHALL be rejected.

**GE-405 — Participant Order**
Reversing challenger and challenged GM SHALL NOT avoid duplicate detection when
the economic position and settlement condition are otherwise identical.

**GE-406 — Active Versus Bet Limit**
A GM SHALL NOT be a participant in more than ten active Versus Bets at one time.
Offered, Accepted, and Pending Versus Bets count toward the limit. Final, Push,
Void, Expired, and Cancelled wagers do not.

## 2.7 Acceptance and Escrow

**GE-501 — Acceptance Validation**
Before acceptance, the System SHALL revalidate eligibility, offer status,
expiration, lock timing, duplicate status, active wager limits, wager
parameters, and available BAB for every required reservation.

**GE-502 — Acceptance Finality**
A valid acceptance is final. After acceptance, no GM or Commissioner may cancel
or modify the wager except through an explicit protocol-defined Void.

**GE-503 — Escrow Requirement**
Acceptance SHALL reserve each participant's maximum possible BAB loss before the
wager can become Accepted or Pending.

**GE-504 — Insufficient BAB**
If any required participant lacks sufficient available BAB at acceptance,
acceptance SHALL fail and no state or Ledger change SHALL occur.

**GE-505 — Acceptance Record**
A successful acceptance SHALL create an immutable acceptance record containing
the accepted terms, participants, timestamps, Specification version, and all
identifiers needed to reproduce settlement.

> **[HYBRID] Escrow true-up at acceptance.** The recipient's Derived Stake
> escrows at acceptance (the Handshake), at the same instant odds recompute and
> lock. If a counter changed the stake before acceptance, the issuer's
> issue-time escrow no longer matches; the accept step SHALL true up the issuer's
> escrow (partial release or adjust) to the countered amount at the same moment
> the recipient's stake escrows fresh. A counter proposes a number and moves no
> money; the recipient's stake never escrows at counter or while pending. This
> true-up is new code. (Money-model ruling.) **[OPUS-GATED]**

## 2.8 Versus Engine

**GE-601 — Versus Participants**
A Versus Bet SHALL contain exactly two GMs.

**GE-602 — Permitted Versus Types**
Only Moneyline, Spread, and Over/Under Versus Bets may be challenged. Prop
challenges and every other challenge shape are prohibited unless introduced by a
future Specification version.

**GE-603 — Versus Wager Definition**
Every Versus Wager Definition SHALL specify: wager type (Moneyline, Spread, or
Over/Under); covered Yahoo entities or scoring aggregates; winning and Push
conditions; pricing method and simulation requirements; allowed mode (Locked,
Dynamic, or both); maximum stake and payout rules; Final Lock trigger;
settlement function.

> **[HYBRID] Asymmetric stake derivation (Row 2).** Every Versus Wager
> Definition's pricing method SHALL derive the two stakes asymmetrically from
> fair odds, not set them equal:
>
> ```
> fairPot        = anchor_stake / p_issuer
> derived_stake  = floor(fairPot × p_opponent)   # whole BAB cents
> ```
>
> The issuer's Anchor Stake is the fixed input; the opponent's stake derives.
> There is NO Max Stake Ceiling forcing equal stakes and NO "size me at" toggle.
> Decline is the opponent's protection (Betfair precedent — the layer's
> liability is unchecked); the pending-bucket check (GE-308) gates whether the
> card can be shown. **[OPUS-GATED]**
>
> **[HYBRID] Floor-both rounding (Row 3).** Both stakes floor to whole BAB
> cents. The residue (fairPot minus the sum of the two floored stakes, strictly
> under one cent) is UNCOLLECTED — never staked, never entered into the Ledger,
> posts nowhere. Escrow holds exactly `anchor_stake_cents +
> derived_stake_cents`. This is the stated law; **Opus is invited to break it at
> Math Review** on an adversarial line (e.g. −150 not dividing clean) — no
> fractional cent may enter the Ledger. This OVERRIDES the general
> remainder-to-Championship rule for two-sided versus derivation. **[OPUS-GATED]**

### 2.8.1 Moneyline

**GE-611 — Moneyline Condition**
A Moneyline wager compares the final Yahoo-derived value of Side A against Side B
without applying a handicap. The side with the greater value wins unless the
Wager Definition expressly defines the lower value as favorable.

**GE-612 — Moneyline Push**
If both sides finish with the same settlement value and the Wager Definition
permits a tie, the wager SHALL Push. A tiebreaker is valid only if defined before
the offer opens.

### 2.8.2 Spread

**GE-621 — Spread Condition**
A Spread wager applies the accepted handicap to the designated side before
comparing the two final Yahoo-derived values.

**GE-622 — Spread Settlement**
The designated side covers when its adjusted settlement value exceeds the
opposing settlement value. It loses when the adjusted value is lower. Equality
SHALL Push.

**GE-623 — Frozen Line**
The accepted spread SHALL remain fixed through settlement. Yahoo lineup or
projection changes SHALL NOT alter the line after Locked acceptance or Dynamic
Final Lock.

### 2.8.3 Over/Under

**GE-631 — Over/Under Condition**
An Over/Under wager compares the final Yahoo-derived settlement total against the
accepted threshold.

**GE-632 — Over/Under Settlement**
The Over wins when the final total exceeds the threshold. The Under wins when the
final total is below the threshold. Equality SHALL Push.

**GE-633 — Covered Total**
The Wager Definition SHALL identify the exact Yahoo-derived team, player group,
or matchup aggregate included in the total. Data outside that defined aggregate
SHALL NOT affect settlement.

## 2.9 Locked Challenges

**GE-701 — Locked Mode**
A Locked Challenge freezes its covered Yahoo entity IDs, odds, stake, maximum
loss, and payout when accepted.

**GE-702 — Post-Acceptance Changes**
Yahoo roster, lineup, injury, projection, or schedule changes after Locked
acceptance SHALL NOT alter the frozen wager terms or covered entity IDs.

**GE-703 — Transition to Pending**
A Locked Challenge SHALL enter Pending immediately upon successful acceptance
when no later protocol action is required. If its Wager Definition requires a
later universal lock, it SHALL remain Accepted until that lock and then enter
Pending without repricing.

## 2.10 Dynamic Challenges

> **[HYBRID] LIVE AT LAUNCH (Row 1).** This subsection is in force for v1.0, not
> disabled. It requires the repricing trigger and The Adjustment. **[PENDING
> CODE-VERIFY]** the three odds write sites and accept path before building.

**GE-801 — Dynamic Mode**
A Dynamic Challenge permits covered Yahoo starting lineups and projection inputs
to refresh before Final Lock while preventing either GM's maximum BAB exposure
from increasing after acceptance.

**GE-802 — Handshake Sequence**
1. Revalidate the offer and both GMs.
2. Run the initial simulation using current Yahoo data, the active projection
   dataset, and the active model version.
3. Calculate the maximum permitted stake and maximum permitted payout.
4. Verify sufficient available BAB for each maximum possible loss.
5. Move each required maximum loss from Wallet to Escrow through the Ledger.
6. Freeze the simulation model version.
7. Record maximum stake, maximum payout, initial probabilities, initial odds,
   projection dataset version, covered market definition, and Handshake
   timestamp.
8. Create the acceptance and Handshake audit records.
9. Transition the wager to Accepted.

**GE-803 — Handshake Ceiling**
The Handshake establishes an immutable ceiling on each GM's stake, loss, payout
obligation, and escrow requirement. No later protocol may increase those values.

**GE-804 — Informational Refresh**
Either participating GM MAY request an informational refresh before Final Lock.
The refresh MAY use current Yahoo lineups and updated projections but SHALL use
the frozen model version.

**GE-805 — Informational Output**
A refresh MAY display current estimated probabilities, odds, official-stake
estimate, payout estimate, and expected escrow refund.

**GE-806 — No Refresh Effect**
An informational refresh SHALL NOT change wager state, official terms, Escrow,
Wallet balances, Ledger entries, maximum exposure, or the Handshake record.

**GE-807 — Refresh Frequency**
The System MAY limit refresh frequency for operational reasons, but every
completed refresh remains informational and has no protocol effect.

## 2.11 Final Lock and The Adjustment

**GE-901 — Final Lock Trigger**
For a Dynamic Challenge, Final Lock occurs immediately before the earliest
scheduled NFL kickoff involving any player in either final Yahoo starting lineup
covered by the wager. Once any covered starting player locks in Yahoo, the entire
wager SHALL Final Lock.

**GE-902 — Final Lock Data**
At Final Lock, the System SHALL retrieve and record the final available Yahoo
starting lineups, league scoring configuration, covered entity IDs, current
projection dataset, frozen model version, and NFL schedule data required by the
Wager Definition.

**GE-903 — Official Simulation**
The System SHALL run exactly one official Final Lock simulation using the Final
Lock data and frozen model version.

**GE-904 — The Adjustment Algorithm**
1. Calculate fair probabilities and fair odds from the official simulation.
2. Calculate the stake and payout implied by those odds under the accepted Wager
   Definition.
3. Cap each official stake and payout at the corresponding Handshake maximum.
4. Reduce, but never increase, any participant obligation required to remain
   within all Handshake ceilings.
5. Calculate each participant's excess Escrow as reserved Escrow minus official
   maximum loss.
6. Refund each excess amount from Escrow to the originating Wallet through
   balanced Ledger entries.
7. Freeze official probabilities, odds, stake, payout, covered Yahoo entity IDs,
   and settlement parameters.
8. Create the Final Lock simulation and Adjustment audit records.
9. Transition the wager to Pending.

> **[HYBRID]** Steps 1–2 derive both stakes asymmetrically (Row 2) and floor
> both (Row 3) before any cap or refund is computed — derive, derive, then cap,
> then refund. The uncollected residue is not a refund leg. **[OPUS-GATED]**

**GE-905 — Adjustment Direction**
The Adjustment MAY preserve or reduce a stake, payout, or escrow amount. It SHALL
NEVER increase any Handshake maximum or require additional BAB.

**GE-906 — Final Lock Failure**
If required data cannot be deterministically established at Final Lock, the wager
SHALL become Void and all Escrow SHALL be refunded. No participant or
administrator may choose replacement terms.

**GE-907 — Finality**
After Final Lock, no lineup, projection, injury, schedule, participant,
Commissioner, or administrator action may change official wager terms.

## 2.12 Pool Engine

**GE-1001 — Pool Outcome Invariant**
Every Pool Bet SHALL settle to exactly one winning outcome option. Every option
SHALL be represented by either one GM name or one Yahoo matchup consisting of
exactly two GM names. A raw stat, number, line, player name, or narrative answer
SHALL NOT be a wagerable Pool outcome.

**GE-1002 — Single-GM Outcome**
A Single-GM outcome represents one fantasy team. The option set SHALL consist of
the eligible GMs defined by the Pool Wager Definition.

**GE-1003 — Matchup Outcome**
A Matchup outcome represents one Yahoo fantasy matchup and SHALL be displayed and
stored as exactly two GM identifiers. The option set SHALL consist of the
eligible Yahoo matchups defined by the Pool Wager Definition.

**GE-1004 — Name-Agnostic Settlement Key**
The payout engine SHALL treat a winning Single-GM option and a winning Matchup
option as the same abstract settlement key: one winning option identifier matched
against eligible tickets or rank associations.

**GE-1005 — Pool Mechanics**
Every Pool Bet SHALL use exactly one mechanic: Prediction Bet or Rank Bet.

### 2.12.1 Prediction Bets

**GE-1011 — Stored Pick**
Each Prediction Bet entry SHALL store one participating GM as the picker and
exactly one eligible option as that GM's pick.

**GE-1012 — Ticket Creation**
A valid pick and entry-fee reservation create one Pool ticket. Unless the Pool
Wager Definition expressly permits multiple tickets, each GM may hold no more
than one ticket in that Pool occurrence.

**GE-1013 — Winning Ticket**
A Prediction ticket wins when its stored option equals the Pool's final winning
option.

**GE-1014 — Positive Classification**
A positive Prediction Bet rewards superior or successful fantasy performance. A
GM MAY pick themselves or a Matchup option containing themselves in a positive
Prediction Bet.

**GE-1015 — Negative Classification**
A negative Prediction Bet rewards inferior, losing, or otherwise adverse fantasy
performance. A GM SHALL NOT pick themselves or a Matchup option containing
themselves in a negative Prediction Bet.

**GE-1016 — Matchup Self-Pick**
For self-pick validation, a GM has picked themselves whenever their GM identifier
appears on either side of the selected Matchup option.

**GE-1017 — Tanking Guard**
A self-pick prohibited by GE-1015 SHALL be rejected before ticket creation. This
restriction applies during the regular season and postseason.

### 2.12.2 Rank Bets

**GE-1021 — Automatic Entry**
A Rank Bet has no picker and no stored pick. Eligible participants SHALL be
auto-entered according to the Pool Wager Definition.

**GE-1022 — Rank Field**
At settlement, the System SHALL rank all eligible Single-GM or Matchup options by
the Wager Definition's metric and ordering rule.

**GE-1023 — Winning Rank**
The top-ranked option SHALL be the winning outcome. A participant wins by being
associated with the winning option, not by predicting it.

**GE-1024 — Self-Inclusion**
Self-inclusion is automatic and always permitted in Rank Bets. No self-pick
restriction applies because no participant makes a pick.

### 2.12.3 Pool Definition and Entry

**GE-1031 — Pool Wager Definition**
Every Pool Wager Definition SHALL specify: outcome shape (Single-GM or Matchup);
mechanic (Prediction or Rank); eligible option set; deterministic metric and
winning condition; ordering direction and all tie rules; positive or negative
classification for Prediction Bets; entry fee or automatic contribution; minimum
participation requirement; maximum tickets per GM; open time and Final Lock;
rollover behavior; settlement function.

**GE-1032 — Pool Entry**
A participant enters a Prediction Bet by submitting a valid pick and funding the
required entry fee before Pool Final Lock. A participant enters a Rank Bet
automatically when the Wager Definition's eligibility condition is met.

**GE-1033 — Equal Entry Fee**
All tickets within a Pool occurrence SHALL have the same entry fee unless the
Wager Definition defines the Pool as a no-choice automatic Rank contribution.

**GE-1034 — Pool Final Lock**
At Pool Final Lock, Prediction picks and ticket counts freeze, no new entry is
permitted, and the Pool enters Pending if its minimum participation requirement
is satisfied.

> **[HYBRID] Pool lock timing.** Pool bets lock at the week's single earliest
> kickoff (one shared moment for the whole league), distinct from Versus bets,
> which lock per-challenge at the earliest kickoff of the specific players/teams
> involved.

**GE-1035 — Minimum Participation**
If a Pool does not meet its minimum participation requirement at Final Lock, it
SHALL become Void and all entry fees SHALL be refunded.

### 2.12.4 Pool Settlement, Ties, and Rollover

**GE-1041 — Outcome First**
Pool settlement SHALL determine the winning option from Yahoo-derived results
before evaluating any Prediction tickets or Rank associations. Participant
selections SHALL NOT influence which option wins.

**GE-1042 — Tie Rule Requirement**
Each Pool Wager Definition SHALL contain a deterministic tie rule or expressly
permit multiple tied winning options.

**GE-1043 — Multiple Winning Options**
When a Wager Definition permits multiple tied winning options, every eligible
ticket or participant associated with any tied winning option SHALL be a winning
claim.

**GE-1044 — Winning Claims**
The distributable Pool balance SHALL be divided equally among winning claims, not
merely among distinct GMs or distinct outcome options, unless the Wager
Definition expressly defines one claim per participant.

**GE-1045 — Integer Remainder**
All payouts SHALL use integer BAB cents. Any indivisible remainder after equal
distribution SHALL transfer to the Championship Pot.

> **[HYBRID] Scope note.** GE-1045's remainder-to-Championship rule governs POOL
> splits (n-way division of a collected pot). It does NOT govern two-sided Versus
> stake derivation, which uses the floor-both/uncollected-residue rule (GE-603
> [HYBRID], Row 3). The two remainder situations are distinct.

**GE-1046 — No Winner**
When no eligible winning claim exists, the Pool balance SHALL follow the Wager
Definition's rollover rule.

**GE-1047 — Rollover**
A rollover SHALL remain attached to the same Pool Wager Definition and transfer
to its next eligible occurrence. It SHALL NOT be distributed, redirected, or
merged except as expressly defined by League Configuration.

**GE-1048 — Season-End Rollover Sweep**
Any Pool rollover remaining after its final eligible occurrence of the season
SHALL transfer to the Championship Pot unless League Configuration specifies
another protocol-defined season-end destination.

## 2.13 Common Settlement Engine

**GE-1101 — Yahoo Authority**
Settlement SHALL use the official Yahoo data fields and aggregation method
identified by the Wager Definition. The Simulation Engine SHALL NOT determine
actual winners.

**GE-1102 — Settlement Eligibility**
Only Pending wagers may settle.

**GE-1103 — Settlement Sequence**
1. Retrieve the required Yahoo final data.
2. Compute the settlement value for each covered side or outcome option.
3. Apply the Wager Definition's winning, Push, tie, and Void conditions.
4. Determine exactly one terminal result: Final, Push, or Void.
5. Post all required balanced Ledger transactions.
6. Credit winning Wallets, refund Push or Void amounts, and transfer any
   protocol-defined remainder or rollover.
7. Set all wager Escrow balances to zero.
8. Create the immutable settlement audit record.
9. Transition the wager to its terminal state.

**GE-1104 — Final Result**
A Final wager SHALL identify the winning side, option, ticket set, or rank
association required to reproduce its payout.

**GE-1105 — Push**
A Push SHALL return each participant's remaining Escrow to the originating
Wallet. No BAB changes ownership.

**GE-1106 — Void**
A Void SHALL return each participant's remaining Escrow or Pool entry fee to the
originating Wallet. No winner is declared.

**GE-1107 — Protocol Void Conditions**
A wager SHALL become Void when: the required Yahoo data cannot be
deterministically obtained; the covered event or entity is invalidated in a
manner not resolved by the Wager Definition; a protocol defect prevents
deterministic settlement; the wager was accepted from materially invalid inputs
that cannot be corrected without participant or administrator discretion.

**GE-1108 — No Manual Settlement**
No GM, Commissioner, or administrator may choose a winner, alter a settlement
value, substitute a tiebreaker, or override a protocol-defined Push or Void.

## 2.14 Bye Weeks and Availability

**GE-1201 — Bye Week Treatment**
Fantasy Beefs SHALL apply no special bye-week scoring adjustment. Yahoo lineup
eligibility and Yahoo scoring govern.

**GE-1202 — Unavailable Covered Entity**
If a covered player or entity produces zero under Yahoo rules, that zero SHALL
apply unless the Wager Definition expressly defines another deterministic
treatment before offer creation.

**GE-1203 — No Retroactive Replacement**
After Locked acceptance or Dynamic Final Lock, a covered Yahoo entity SHALL NOT
be replaced because of injury, benching, bye, inactive status, or
nonparticipation.

## 2.15 Game Engine Invariants

**GE-INV-001** — Every accepted wager has one immutable participant set.
**GE-INV-002** — Every accepted wager has one maximum BAB exposure per
participant.
**GE-INV-003** — No Dynamic Challenge increases exposure after Handshake.
**GE-INV-004** — Only Moneyline, Spread, and Over/Under may be offered as Versus
Bets.
**GE-INV-005** — Every Pool winning option is represented by one GM or one
Matchup of two GMs.
**GE-INV-006** — A GM may back their own success but may not profit from
selecting their own adverse outcome in a negative Prediction Bet.
**GE-INV-007** — Every Pending wager settles exactly once as Final, Push, or
Void.
**GE-INV-008** — Every completed wager has zero Escrow.
**GE-INV-009** — Yahoo results determine outcomes; simulations determine fair
pricing only.

### End of Section 2

Section 2 governs the complete deterministic lifecycle of Versus Bets and Pool
Bets. The merged-hybrid overrides — Dynamic live (Row 1), asymmetric stake
derivation (Row 2), floor-both rounding (Row 3), escrow-at-issue and the accept
true-up — attach to the Versus Engine and Final Lock. Sections 3–8 govern the
Ledger, BAB Economy, Simulation Engine, System, League Configuration, and
completion protocols.
