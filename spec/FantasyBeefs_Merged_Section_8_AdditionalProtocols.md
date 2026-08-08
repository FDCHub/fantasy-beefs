# Fantasy Beefs — Merged Hybrid · Section 8 — Additional Protocols

*Completion, controlling amendments, verified additions, and explicit
exclusions.*

> **[HYBRID] Section-level note.** Section 8 is adopted nearly verbatim. Hybrid
> touches: The Adjustment formula notes asymmetric+floor-both (AP-213); the
> equal-split remainder rule is scoped to POOL splits, not Versus derivation
> (AP-314); Worst Beat is dropped from the catalog; Dynamic is live. All
> money-path items **[OPUS-GATED]**.

## 8.1 Purpose, Scope, and Precedence

Section 8 completes Fantasy Beefs Official Game Specification v1.0 without
restructuring Sections 1 through 7. It adds remaining protocols, supplies
controlling detail where an earlier protocol is abbreviated, verifies previously
approved product decisions, and identifies implementation matters intentionally
excluded from the game protocol.

**AP-001 — Controlling Completion**
Sections 1 through 7 and this Section 8 together constitute Fantasy Beefs
Official Game Specification v1.0.

**AP-002 — Precedence**
Where a protocol in Section 8 directly conflicts with an earlier protocol, the
more specific Section 8 protocol SHALL govern. A Section 8 clarification SHALL be
read together with, and not as a repeal of, every compatible earlier protocol.

> **[HYBRID]** The merged-hybrid overrides (Rows 1, 2, 3, 5, 6, 7 and the
> money-model rulings) are the most specific statements of their rules and govern
> under AP-002 wherever they touch an earlier requirement.

**AP-003 — No New Discretion**
Section 8 SHALL NOT create Commissioner, administrator, or participant discretion
unless that discretion is expressly stated and bounded by a deterministic rule.

**AP-004 — Canonical Home**
A protocol defined elsewhere remains in force. Section 8 repeats a concept only
when necessary to complete, clarify, or verify its controlling behavior.

**AP-005 — Version Freeze**
Upon publication of all eight sections, Version 1.0 SHALL be treated as complete.
New gameplay mechanics SHALL require a later published Specification version
rather than informal amendment.

## 8.2 Category A — Remaining Protocols

### 8.2.1 League Membership

**AP-101 — Active GM Eligibility**
Only a GM recognized by Yahoo as controlling a team in the applicable League
season and activated in Fantasy Beefs may create, accept, enter, or receive a
wager.

**AP-102 — Midseason Join**
A GM who joins after the season begins SHALL receive the League-configured
midseason starting allocation. If no midseason allocation is configured, the GM
SHALL receive the same initial BAB allocation provided to all GMs at season
initialization.

**AP-103 — Midseason Join Effective Time**
A joining GM becomes wager-eligible only after League membership, Wallet
issuance, configuration assignment, and audit creation complete atomically.

**AP-104 — League Departure**
A GM leaving a League SHALL lose the ability to create or accept new wagers
immediately upon deactivation.

**AP-105 — Existing Obligations After Departure**
Accepted and Pending wagers involving a departing GM SHALL continue to Final,
Push, or Void under the same protocols. The departing GM's Wallet, Escrow,
Ledger, tickets, and historical records SHALL remain intact until all obligations
settle.

**AP-106 — No Balance Transfer on Departure**
A departing GM's BAB SHALL NOT be transferred to another GM, Commissioner, or
League account except through an explicit season-close distribution protocol.

### 8.2.2 Week and Season Transition

**AP-111 — Week Open**
A Fantasy Week opens when Yahoo makes the week available and Fantasy Beefs has
synchronized the data required to create valid Wager Definitions for that week.

**AP-112 — Wager-Specific Close**
Each wager closes at its own Final Lock. A week MAY remain open for other wager
definitions whose Final Lock has not occurred.

> **[HYBRID]** Pool bets share one week-level lock (earliest kickoff in the
> week); Versus bets lock per-challenge at the earliest kickoff of their specific
> players/teams. (Lock-timing ruling.)

**AP-113 — Week Settlement Completion**
A Fantasy Week is complete for Fantasy Beefs only after every wager and Pool
occurrence for that week is Final, Push, Void, Expired, or Cancelled and every
related Ledger transaction has posted.

**AP-114 — New Season**
A new season SHALL create a new season identifier, League Configuration, Wallet
set, Championship Pot, Skunk Pot, Pool occurrences, and audit sequence.

**AP-115 — Historical Preservation**
Starting a new season SHALL NOT reset, overwrite, reopen, or delete prior-season
wagers, balances, simulations, Ledger entries, or audit records.

**AP-116 — No Automatic BAB Carryover**
Unused BAB SHALL NOT carry into a new season unless League Configuration
expressly defines a protocol-authorized carryover. Absent such a rule, new-season
Wallet balances SHALL be created solely from the configured initial allocation.

**AP-117 — Season Reset Order**
1. Finalize every regular-season and postseason wager.
2. Resolve every remaining Pool occurrence and rollover.
3. Release all Escrow.
4. Assess any final Weekly Minimum or Skunk obligations.
5. Distribute Championship and Skunk Pots.
6. Reconcile the Ledger.
7. Archive the completed season.
8. Initialize the new season under a new configuration.

> **[HYBRID]** Insert before step 5: sweep `reserve:{team_id}` to Championship;
> return `frozen:{team_id}` to Wallet; zero `min:{team}:{week}`. (Rows 5, 6.)

### 8.2.3 Yahoo Finalization and Stat Corrections

**AP-121 — Settlement Data Cutoff**
The official settlement input SHALL be the most recent valid Yahoo data retrieved
before the Fantasy Beefs settlement transaction commits.

**AP-122 — Pre-Settlement Corrections**
Yahoo stat corrections received before settlement commits SHALL apply
automatically.

**AP-123 — Post-Settlement Corrections**
A Yahoo correction received after settlement commits SHALL NOT reopen, reverse,
or modify a settled wager in Version 1.0.

**AP-124 — Delayed Yahoo Finalization**
If Yahoo delays finalization, affected wagers SHALL remain Pending until the
required data is available or the protocol determines that deterministic
settlement is impossible.

**AP-125 — No Alternate Statistics**
Participant screenshots, third-party box scores, television graphics, or
Commissioner judgment SHALL NOT replace Yahoo settlement data.

### 8.2.4 Championship Pot Distribution

**AP-131 — Distribution Authority**
The Championship Pot SHALL be distributed only according to the League
Configuration fixed for the applicable season.

**AP-132 — Distribution Preconditions**
All season wagers and Pool occurrences are terminal; all Escrow balances equal
zero; all Pool rollovers have been resolved or swept; all Weekly Minimum and other
Pot contributions have posted; the Ledger reconciles.

> **[HYBRID]** Add precondition: all Reserve accounts swept and all Frozen
> accounts returned. (Row 6.)

**AP-133 — Recipient Determination**
The recipient or recipients SHALL be determined solely by the configured
Yahoo-derived championship result or other configured deterministic distribution
key.

**AP-134 — Multiple Recipients**
When the configured distribution requires equal division among multiple
recipients, integer BAB cents SHALL be divided equally and any remainder SHALL
remain in the Championship Pot until the final configured recipient allocation.
If no later allocation exists, the final indivisible remainder SHALL be assigned
by the League Configuration's deterministic remainder rule.

> **[HYBRID]** Default distribution 60/30/10; leftover cents to 1st place so the
> three payouts sum exactly to the pot. (Row 6.)

**AP-135 — Distribution Posting**
Championship Pot distribution SHALL debit the Championship Pot and credit
recipient Wallets through balanced Ledger transactions.

**AP-136 — No Commissioner Allocation**
A Commissioner SHALL NOT choose, change, accelerate, delay, or redirect
Championship Pot recipients or amounts.

### 8.2.5 Weekly Skunk Protocol

**AP-141 — Skunk Activation**
The Weekly Skunk protocol applies only when enabled in League Configuration.

**AP-142 — Skunk Definition**
The weekly Skunk SHALL be the GM with the largest Yahoo matchup defeat margin for
the applicable Fantasy Week unless League Configuration defines another
deterministic Yahoo-derived Skunk metric.

**AP-143 — Defeat Margin**
Defeat margin equals the winning Yahoo team score minus the losing Yahoo team
score for each completed League matchup.

**AP-144 — Skunk Tie**
If multiple GMs tie for the weekly Skunk, the configured Skunk contribution SHALL
be divided equally among the tied GMs. Any indivisible contribution remainder
SHALL be assigned using the League Configuration's deterministic remainder rule.

> **[HYBRID]** The tie-split remainder rule for the Skunk contribution is
> **[OPUS-GATED]** and remains an open finding.

**AP-145 — Skunk Contribution**
Each assessed GM SHALL transfer the required BAB from Wallet to Skunk Pot. If
available BAB is insufficient, the unpaid amount SHALL become a recorded BAB
obligation and SHALL be satisfied from the next BAB credited to that Wallet before
BAB becomes available for wagering.

> **[HYBRID]** Default weekly Skunk $10, regular season only (weeks 1–14). The
> obligation is off-wallet (added to dues owed). Its pre-settlement home
> (candidate `receivable:{team_id}`) is **[OPUS-GATED]** open. (Skunk Fee ruling.)

**AP-146 — Skunk Pot Winner**
Unless League Configuration specifies another deterministic recipient, the Skunk
Pot SHALL be awarded after the regular season to the GM with the highest
cumulative Yahoo Points For.

**AP-147 — Skunk Winner Tie**
A tie for highest cumulative Points For SHALL be resolved by the configured
deterministic tiebreaker. If no tiebreaker is configured, the Skunk Pot SHALL be
divided equally and any indivisible remainder SHALL transfer to the Championship
Pot.

**AP-148 — Skunk Audit**
Every weekly assessment and season-ending Skunk Pot distribution SHALL identify
the Yahoo inputs, calculation, assessed GM or GMs, amount, and Ledger
transaction.

### 8.2.6 BAB Top-Off Workflow

**AP-151 — Top-Off Request**
A Top-Off request SHALL identify the requesting GM, League season, requested BAB
amount, request timestamp, and any League-required offline reconciliation
reference.

**AP-152 — Pending Request**
A submitted Top-Off request SHALL create no BAB and no Wallet balance until
approved.

**AP-153 — Commissioner Decision**
The Commissioner SHALL approve or reject the exact requested amount. Partial
approval requires rejection of the original request and submission of a new
request for the approved amount.

**AP-154 — Approval Preconditions**
The requesting GM is active in the League season; the amount is a positive integer
number of BAB cents; the request has not already been resolved; any configured
Top-Off limit is satisfied; the Commissioner is authorized for that League season.

**AP-155 — Approval Posting**
1. Create the protocol-defined BAB issuance entry.
2. Credit the requesting GM's Wallet.
3. Record the approving Commissioner and timestamp.
4. Link the request, Ledger transaction, and audit record.
5. Mark the request Approved.

> **[HYBRID]** Topped-off BAB is above-and-beyond wagerable money, not subject to
> the reserve ceiling. **[PENDING CODE-VERIFY]** — the deposit path currently
> writes off-ledger and must route through this posting sequence.

**AP-156 — Rejection**
A rejected request SHALL create no Ledger transaction and SHALL be permanently
recorded as Rejected.

**AP-157 — No Direct Balance Editing**
A Commissioner or administrator SHALL NOT increase a Wallet by editing its
balance. Every Top-Off SHALL pass through the approved request and Ledger
workflow.

### 8.2.7 Pool Rollover and Jackpot Completion

**AP-161 — No-Winner Rollover**
When a Pool Wager Definition specifies rollover and no eligible winning claim
exists, the full distributable Pool balance SHALL roll to the next occurrence of
the same Wager Definition.

> **[HYBRID]** Only qualifier/threshold-style Pool bets (where "zero qualifiers"
> is a real outcome) are rollover-eligible; rank bets always resolve. (Rollover
> ruling.)

**AP-162 — Rollover Identity**
Rolled BAB SHALL retain the originating League, season, Pool Wager Definition, and
rollover lineage.

**AP-163 — Added Entry Fees**
The next occurrence's distributable balance SHALL equal the incoming rollover plus
all valid new entry fees and other contributions expressly permitted by the Wager
Definition.

**AP-164 — Jackpot**
A Jackpot is a Pool balance containing one or more rollovers. Jackpot status
changes the balance only; it SHALL NOT change outcome options, winning conditions,
self-pick rules, ticket eligibility, or payout rules.

**AP-165 — No Cross-Pool Transfer**
A rollover SHALL NOT move to another Pool Wager Definition during the season.

**AP-166 — Season-End Sweep**
Any unresolved rollover after the final eligible occurrence of the season SHALL
transfer to the Championship Pot unless the fixed League Configuration specifies
another protocol-defined destination.

> **[HYBRID]** The terminal sweep fires at `season_final_week`, not a hardcoded
> week 14. (Postseason ruling.)

## 8.3 Category B — Controlling Protocol Amendments

### 8.3.1 Acceptance and Handshake Completion

**AP-201 — Acceptance Completion**
An acceptance is complete only when validation, required Escrow reservation,
immutable term storage, audit creation, and state transition all commit
atomically.

**AP-202 — Dynamic Handshake Completion**
1. Confirm the offer remains Offered and unexpired.
2. Confirm both GMs remain eligible and within active-wager limits.
3. Load current Yahoo lineups, scoring settings, projections, and NFL schedule
   data.
4. Run the initial simulation.
5. Calculate fair odds and each GM's maximum possible BAB loss and payout
   obligation.
6. Confirm sufficient available BAB.
7. Reserve maximum required Escrow.
8. Freeze the simulation model version.
9. Record the initial projection version, probabilities, odds, maximum stake,
   maximum payout, covered market, and participant identities.
10. Create immutable Ledger and audit records.
11. Transition the wager to Accepted.

> **[HYBRID]** Step 5 computes the asymmetric per-side stakes (anchor ÷ p × p)
> and floors both (Rows 2, 3). Step 7 also trues up the issuer's issue-time
> escrow to any countered amount (GE-505 [HYBRID]). Dynamic is live (Row 1).
> **[OPUS-GATED]**

**AP-203 — Handshake Failure**
Failure of any Handshake step SHALL leave the offer unaccepted and SHALL create
no partial Escrow, Ledger, simulation, or wager-state effect.

**AP-204 — Maximum Exposure**
The Handshake's maximum loss and payout values are hard ceilings. Final Lock and
The Adjustment MAY preserve or reduce them but SHALL NEVER increase them.

### 8.3.2 Final Lock and The Adjustment Completion

**AP-211 — Single Official Final Lock**
Each Dynamic Challenge SHALL execute exactly one official Final Lock.

**AP-212 — Final Lock Sequence**
1. Determine the earliest kickoff among all players in either covered final Yahoo
   starting lineup.
2. Close participant actions immediately before that kickoff.
3. Retrieve and store final Yahoo lineups and required scoring settings.
4. Use the current projection dataset and the frozen model version.
5. Run the official simulation.
6. Calculate official fair probabilities and odds.
7. Execute The Adjustment.
8. Refund excess Escrow.
9. Freeze player IDs, lineups, probabilities, odds, stake, payout, and settlement
   parameters.
10. Create the official simulation, Ledger, and audit records.
11. Transition the wager to Pending.

**AP-213 — The Adjustment Formula**
For each participant, Official Exposure SHALL equal the lesser of the exposure
calculated from the Final Lock fair odds and the Handshake maximum exposure.
Excess Escrow SHALL equal reserved Handshake Escrow minus Official Exposure.

> **[HYBRID]** "Exposure calculated from the Final Lock fair odds" is the
> asymmetric derivation: `fairPot = anchor_stake / p_issuer`, then
> `derived_stake = floor(fairPot × p_opponent)`, both floored to whole BAB cents,
> residue uncollected (Rows 2, 3). The cap to the Handshake ceiling applies after
> derivation. No fractional cent may enter the Ledger. **Opus is invited to break
> the floor-both rule on an adversarial line at Math Review.** **[OPUS-GATED]**

**AP-214 — No Negative Refund**
If calculated Excess Escrow is zero, no refund SHALL post. A negative Excess
Escrow value is invalid and SHALL trigger protocol failure rather than additional
collection.

**AP-215 — Adjustment Once**
The Adjustment SHALL run exactly once and SHALL NOT be rerun because of later
projection, lineup, injury, or schedule changes.

### 8.3.3 Settlement Completion

**AP-221 — Settlement Preconditions**
The wager is Pending; the applicable Yahoo data is available; the Wager Definition
and frozen terms are identifiable; required Escrow exists; the wager has not
previously settled.

**AP-222 — Settlement Sequence**
1. Retrieve the authoritative Yahoo settlement values.
2. Apply the frozen Wager Definition and parameters.
3. Determine Final, Push, or Void.
4. Calculate winning claims and integer BAB payouts.
5. Post all ownership transfers, refunds, Pot transfers, and remainders.
6. Set wager Escrow to zero.
7. Create the settlement audit record.
8. Transition to the terminal state.

> **[HYBRID]** In step 5, the Versus payout is the sum of the two floored
> escrowed stakes, sourced from actual escrow balances, never recomputed as
> `2 × amount` (Rows 2, 3; FR-5.9/5.10 precedent).

**AP-223 — Settlement Failure**
If settlement cannot complete atomically, the wager SHALL remain Pending and no
partial payout or refund SHALL persist.

**AP-224 — No Manual Winner**
A participant, Commissioner, or administrator SHALL NOT select a winner or
settlement value.

### 8.3.4 Weekly Minimum Completion

**AP-231 — Weekly Commitment**
A GM's Weekly Commitment SHALL equal the sum of BAB that became irrevocably
committed by that GM to accepted wagers for the applicable week, measured by the
amount at risk after any Dynamic Final Lock reduction.

**AP-232 — No Double Counting**
The same BAB commitment SHALL count once even if represented by multiple Ledger
movements such as reservation, refund, and settlement.

**AP-233 — Minimum Evaluation**
After all applicable wagers have Final Locked and no further accepted commitment
can be created for the week, the System SHALL compare each GM's Weekly Commitment
with the configured Weekly Minimum.

**AP-234 — Shortfall**
Shortfall SHALL equal the greater of zero and Weekly Minimum minus Weekly
Commitment.

**AP-235 — Shortfall Contribution**
The Shortfall SHALL transfer from the GM's Wallet to the Championship Pot. If the
Wallet is insufficient, the unpaid Shortfall SHALL become a BAB obligation
satisfied from future Wallet credits before BAB becomes wager-available.

> **[HYBRID]** The sourcing sequence draws min:{team}:{week} first then Wallet
> (Row 5); the shortfall/unspent-min destination is Championship or Frozen per the
> season-kickoff-locked commissioner choice (Row 6). No mandatory minimum applies
> in playoff weeks (postseason ruling).

**AP-236 — Outcome Irrelevance**
A wager's win, loss, Push, or Void after valid commitment SHALL NOT retroactively
change the amount counted toward the Weekly Minimum, except a wager Void caused by
invalid acceptance SHALL not count.

### 8.3.5 Push, Void, and Refund Completion

**AP-241 — Push Ownership**
A Push SHALL return every participant's remaining Escrow to the same Wallet from
which it originated.

**AP-242 — Void Ownership**
A Void SHALL return all remaining wager Escrow or Pool entry fees to their
originating Wallets.

**AP-243 — No Gain on Push or Void**
No GM, Pot, Protocol account, or house account SHALL gain BAB from a Push or Void
except an indivisible remainder already governed by a separate completed
distribution.

**AP-244 — Cancellation Before Acceptance**
Cancellation, rejection, withdrawal, or expiration before acceptance SHALL not
count toward Weekly Minimum and SHALL not create wager settlement.

> **[HYBRID]** On decline or expiry of an issued Versus Bet, the issuer's
> issue-time escrow reverses back to Wallet/min (GE-308 [HYBRID]); the recipient
> never had escrow. The reissue paths are asymmetric per the money-model ruling.

**AP-245 — Accepted Wager Cancellation Prohibited**
An accepted wager SHALL NOT be cancelled by a GM or Commissioner. It may terminate
only through Final, Push, or protocol-defined Void.

## 8.4 Category C — Verified Protocol Additions

**AP-301 — No House and No Vig**
Fantasy Beefs SHALL never be a wagering counterparty and SHALL not retain a
spread, fee, commission, vigorish, or payout percentage from wager settlement.

**AP-302 — BAB-Only Platform**
All in-platform wagers, entry fees, payouts, Pots, Escrow, and balances SHALL use
BAB only. Any real-world reconciliation occurs outside Fantasy Beefs and is not a
platform settlement event.

**AP-303 — Versus Bet Taxonomy**
Only Spread, Moneyline, and Over/Under may be challenged as Versus Bets in Version
1.0.

**AP-304 — Cross-Matchup Challenges**
Any eligible GM may challenge any other eligible GM in the same League regardless
of Yahoo's scheduled matchup.

**AP-305 — Offer Expiration**
A Versus offer expires one hour after creation or at the applicable lock,
whichever occurs first.

> **[HYBRID]** "One hour" is the locked 60-minute response window. Effective
> window = sooner of 60 minutes or the challenge's own kickoff.

**AP-306 — Duplicate Prevention**
Economically identical active Versus wagers between the same GMs for the same week
and market SHALL be rejected.

**AP-307 — Active Limit**
A GM may participate in no more than ten active Versus wagers at one time.

**AP-308 — Locked Challenge**
Locked acceptance freezes odds, stake, payout, settlement parameters, and covered
Yahoo entity IDs immediately.

**AP-309 — Dynamic Challenge**
Dynamic acceptance creates the Handshake; later refreshes are informational; Final
Lock runs the official simulation and The Adjustment.

> **[HYBRID]** Dynamic is LIVE at launch (Row 1). **[PENDING CODE-VERIFY]** /
> **[OPUS-GATED]**.

**AP-310 — Model Freeze**
A Dynamic Challenge's simulation model version freezes at Handshake and remains
unchanged through Final Lock.

**AP-311 — Projection Refresh**
Dynamic informational and Final Lock simulations may use updated projections, but
informational refreshes SHALL not change Ledger balances, Escrow, or official
terms.

**AP-312 — No Special Bye Rule**
Fantasy Beefs applies no special bye-week adjustment. Yahoo lineup eligibility and
scoring govern.

**AP-313 — Integer BAB Cents**
Every BAB balance, stake, payout, contribution, refund, and remainder SHALL be
stored and calculated as integer BAB cents.

**AP-314 — Equal-Split Remainder**
Unless another specific deterministic remainder rule applies, an indivisible
equal-split remainder SHALL transfer to the Championship Pot.

> **[HYBRID] Scope (Rows 3, 4 clarify).** AP-314 governs POOL splits and other
> equal-division cases. It does NOT govern two-sided Versus stake derivation,
> where "another specific deterministic remainder rule" — the floor-both/
> uncollected-residue rule (GE-603, SIM-805, AP-213 [HYBRID]) — applies instead.
> The Versus residue is never collected, so no remainder is routed to the
> Championship Pot.

**AP-315 — Commissioner Limits**
Commissioners may initialize permitted configuration and approve Top-Offs but
SHALL not create, modify, cancel, price, settle, or override wagers.

**AP-316 — Pool Outcome Vocabulary**
A Pool's wagerable and settleable outcome SHALL always be one GM or one Matchup of
exactly two GMs. No third outcome shape is permitted.

> **[HYBRID]** This matches the session pool ruling verbatim: "one name for team
> bets, two names for matchup bets; the GM bets an option; the winning option
> takes the pot." (Pool ruling.)

**AP-317 — Pool Mechanics**
Every Pool SHALL be either a Prediction Bet with a stored picker and pick or a
Rank Bet with automatic entry and no pick.

**AP-318 — Positive Self-Pick**
A GM may select themselves or a Matchup containing themselves in a positive
Prediction Bet.

**AP-319 — Negative Self-Pick Prohibited**
A GM may not select themselves or a Matchup containing themselves in a negative
Prediction Bet.

**AP-320 — Rank Self-Inclusion**
Self-inclusion is automatic and permitted in Rank Bets because no pick exists.

**AP-321 — Pool Outcome Independence**
The Pool's winning option SHALL be determined from the defined Yahoo-derived
metric without regard to which options participants selected.

**AP-322 — Winning Claims**
Pool payout division SHALL count eligible winning tickets or rank claims and SHALL
be indifferent to whether the winning settlement key contains one GM name or two.

**AP-323 — Pool Catalog**
The approved Pool catalog, including the previously defined set of Pool Wager
Definitions, SHALL be implemented as data under the common Pool Engine. A catalog
entry SHALL not create an exception to the common outcome, self-pick, tie,
rollover, settlement, or Ledger protocols.

> **[HYBRID]** Worst Beat is DROPPED from the catalog (duplicative of Skunk).
> Launch set: Biggest Winner, Special Teams Supremacy, The Lineup (rank); Bench
> Burn (prediction). The ~96-bet catalog is **[PENDING CATALOG READ]** — confirm
> every entry resolves to one GM or one matchup before building.

**AP-324 — Immutable Audit**
Every state change, simulation, BAB movement, configuration change, and
administrative approval SHALL be permanently auditable.

**AP-325 — Double-Entry Ledger**
Every BAB movement SHALL post balanced debit and credit entries. Posted
transactions SHALL not be edited or deleted; corrections use compensating entries.

**AP-326 — Escrow Ceiling**
No GM may lose more BAB on a wager than the amount validly reserved for that
wager.

**AP-327 — Yahoo Sole Result Authority**
Yahoo Fantasy Football is the exclusive authority for fantasy scoring and results;
simulations price wagers but never determine actual outcomes.

**AP-328 — One Week per Wager**
Every wager SHALL reference exactly one Fantasy Week.

**AP-329 — One Terminal Outcome**
Every accepted wager SHALL terminate exactly once as Final, Push, or Void.

**AP-330 — Season Close**
A season SHALL not close until all wagers and Pools are terminal, Escrow equals
zero, Pots are distributed, and the Ledger reconciles.

> **[HYBRID]** Add: Reserve swept, Frozen returned, weekly-min pots zeroed. (Rows
> 5, 6.)

## 8.5 Category D — Explicitly Out of Scope

The following matters are intentionally outside the Fantasy Beefs game protocol.
They may be specified in product, technical, security, compliance, or
user-experience documentation, but implementation choices SHALL not change the
deterministic behavior established by Sections 1 through 8.

**AP-401 — User Interface**
Screen layout, visual design, navigation, button placement, animation, and
copywriting are out of scope.

> **[HYBRID] Note (not a scope change).** The My League six-tab UI, the Open
> Contracts carousel, and the five locked response-card designs (Accepted /
> Countered / Declined / Expired / Incoming) are product decisions recorded
> elsewhere. They implement, and never override, the deterministic protocol here.

**AP-402 — API and Database Design**
Endpoint structure, database schema, indexing, caching, programming language,
framework, and hosting architecture are out of scope.

**AP-403 — Notification Wording**
Email, push, SMS, and in-app notification wording and presentation are out of
scope. Notification delivery remains informational only.

**AP-404 — Performance Targets**
Latency targets, capacity planning, uptime objectives, and infrastructure scaling
are out of scope except where system delay would change a protocol deadline or
outcome.

**AP-405 — Security Implementation**
Authentication technology, encryption method, key management, network controls,
monitoring tools, and incident-response implementation are out of scope. Required
authorization and data-integrity outcomes remain in scope.

**AP-406 — Real-Money Reconciliation**
Any offline exchange, collection, repayment, tax treatment, or legal
characterization of real money is out of scope. Fantasy Beefs records and settles
BAB only.

**AP-407 — Legal and Regulatory Opinion**
This Specification defines product behavior and is not a legal conclusion
regarding gambling, sweepstakes, taxation, licensing, age eligibility, or
jurisdictional availability.

**AP-408 — Projection Methodology**
The mathematical, statistical, machine-learning, or vendor methodology used to
produce player projections and simulations is out of scope, provided the recorded
engine satisfies the Simulation protocols.

> **[HYBRID]** FantasyPros is the canonical forward-projection source; yfpy
> returns actual scored stats only. This is a data-source note, not a protocol
> change.

**AP-409 — Yahoo API Mechanics**
Authentication flows, rate limits, polling intervals, retry implementation, and
field mapping are out of scope, provided Yahoo remains the authoritative source
required by this Specification.

**AP-410 — Future Wager Types**
Prop challenges, parlay challenges, in-game wagers, live betting, and any Versus
wager other than Spread, Moneyline, or Over/Under are out of scope for Version
1.0.

## 8.6 Final Completeness Invariants

**AP-INV-001** — Sections 1 through 8 collectively define Version 1.0.
**AP-INV-002** — Every accepted wager has a deterministic lifecycle, maximum
exposure, lock, settlement function, and terminal state.
**AP-INV-003** — Every BAB movement is balanced, attributable, and auditable.
**AP-INV-004** — Every Pool outcome is one GM or one Matchup of two GMs.
**AP-INV-005** — A GM may always back their own success and may never select their
own failure in a negative Prediction Bet.
**AP-INV-006** — No house, vig, commission, or platform counterparty exists.
**AP-INV-007** — No Commissioner or administrator may override gameplay outcomes.
**AP-INV-008** — Yahoo results settle wagers; the Simulation Engine supplies fair
odds only.
**AP-INV-009** — Version 1.0 contains no unresolved gameplay policy question.

> **[HYBRID] AP-INV-009 caveat.** The gameplay policy is resolved. What remains
> open is not policy but money-path implementation detail, tracked by the
> **[PENDING CODE-VERIFY]** and **[OPUS-GATED]** tags throughout this merged
> document (Dynamic write sites, MIN_BET, Top-Off deposit path, asymmetric
> derivation, floor-both rounding, reserve/frozen, Skunk tie-split). These clear
> at the next build session's grep and Opus Math Review, not by further policy
> rulings.

### End of Section 8

With Section 8, the Fantasy Beefs Merged Hybrid Specification v1.0 is complete.
The eight sections together constitute the deterministic operating protocol for
the peer-to-peer, no-house, no-vig wagering platform, with the July 18 money-path
overrides and the Dynamic-live decision baked into the requirement text. This
document is the canonical MVP reference once its [PENDING CODE-VERIFY] tags are
cleared by grep and its [OPUS-GATED] findings pass Opus Math Review.
