# Fantasy Beefs — Merged Hybrid · Section 3 — Ledger

*Authoritative double-entry accounting for every BAB movement.*

> **[HYBRID] Section-level note.** Two account types are ADDED to the model per
> Row 6: `reserve:{team_id}` and `frozen:{team_id}`. All additions are
> **[OPUS-GATED]** (money-path).

## 3.1 Purpose

The Ledger is the authoritative accounting record for Fantasy Beefs. Every
issuance, reservation, transfer, refund, contribution, payout, rollover, and
retirement of BAB SHALL be recorded through balanced double-entry transactions.
Wallet, Escrow, and Pot balances SHALL be derived from posted Ledger entries and
SHALL NOT be maintained as independent authoritative values.

## 3.2 Ledger Principles

**LED-001 — Double-Entry Requirement**
Every posted transaction SHALL contain one or more debit entries and one or more
credit entries whose total BAB amounts are exactly equal.

**LED-002 — Immutable Posting**
A posted Ledger transaction SHALL NOT be edited, deleted, reordered, or
overwritten. A correction SHALL be made only through one or more new compensating
transactions that reference the original transaction.

**LED-003 — Authoritative Balance**
The balance of every Ledger account SHALL equal the algebraic sum of all posted
entries assigned to that account. Cached balances MAY be used for performance,
but the Ledger-derived balance governs whenever a discrepancy exists.

**LED-004 — Atomicity**
All entries belonging to one transaction SHALL post atomically. If any entry
fails validation or persistence, no entry from that transaction SHALL post.

**LED-005 — Idempotency**
Each protocol event that creates a transaction SHALL use a unique idempotency
key. Reprocessing the same event SHALL return the original transaction and SHALL
NOT create additional entries.

**LED-006 — Integer Precision**
All Ledger amounts SHALL be stored and posted as integer BAB cents. Fractional
BAB cents are prohibited.

**LED-007 — No Manual Mutation**
No GM, Commissioner, administrator, or support user may directly set an account
balance. Every balance change SHALL arise from an authorized protocol
transaction.

**LED-008 — Canonical Event Link**
Every transaction SHALL identify the exact protocol event that caused it and,
where applicable, the related League, season, Fantasy Week, wager, Pool
occurrence, GM, and approval record.

## 3.3 Account Model

**LED-101 — Account Ownership**
Every Ledger account SHALL belong to exactly one League season and SHALL have one
immutable account type and one immutable owner or protocol purpose.

**LED-102 — GM Wallet Account**
Each active GM SHALL have one Wallet account per League season. The Wallet
represents BAB immediately available to that GM, subject to all other protocol
restrictions.

**LED-103 — GM Escrow Account**
Each active GM SHALL have one Escrow account per League season. The Escrow
account represents BAB reserved against unresolved wager obligations and
unavailable for new commitments.

**LED-104 — Championship Pot Account**
Each League season with an enabled Championship Pot SHALL have one Championship
Pot account. BAB credited to this account SHALL remain there until a
protocol-authorized season-end distribution or correction.

**LED-105 — Skunk Pot Account**
Each League season with an enabled Skunk Pot SHALL have one Skunk Pot account.
BAB credited to this account SHALL remain there until the protocol-authorized
Skunk Pot distribution or correction.

**LED-106 — Pool Rollover Account**
Each Pool Wager Definition with an active rollover SHALL have a distinct rollover
account for the relevant League season. Rollover BAB SHALL remain associated with
that Pool definition until its next eligible occurrence or season-end sweep.

**LED-107 — BAB Issuance Account**
Each League season SHALL have one BAB Issuance account used only as the balancing
account for protocol-authorized creation of BAB, including initial allocations
and approved Top-Offs.

**LED-108 — BAB Retirement Account**
Each League season MAY have one BAB Retirement account used only when a protocol
expressly authorizes permanent removal of BAB from circulation.

**LED-109 — Clearing Account**
A Clearing account MAY be used within a single atomic transaction to express
multi-party settlement. Its balance SHALL be zero after the transaction posts. A
nonzero Clearing balance is prohibited.

**LED-110 — No Shared GM Accounts**
Wallet and Escrow accounts SHALL NOT be shared across GMs, Leagues, or seasons.

> **[HYBRID] LED-111 — GM Reserve Account (Row 6).** Each active GM SHALL have
> one `reserve:{team_id}` account per League season when the Reserve mechanic is
> enabled. BAB is credited to Reserve at buy-in (a fixed fraction, default 4/11 =
> 36.4% of buy-in) and released weekly toward the GM's wagerable Wallet by the
> reserve-ceiling formula. Any Reserve balance remaining at season end transfers
> to the Championship Pot. Reserve SHALL NOT be spent directly on wagers; only
> released Wallet BAB is wagerable. **[OPUS-GATED]**
>
> **[HYBRID] LED-112 — GM Frozen Account (Row 6).** Each active GM MAY have one
> `frozen:{team_id}` account per League season when the commissioner selects
> Frozen as the unspent-weekly-minimum destination. Frozen BAB never releases
> weekly and is returned to the GM only at final season reconciliation. Frozen
> is distinct from Reserve. The destination choice (Championship vs Frozen) is
> LOCKED at season kickoff and not adjustable mid-season. **[OPUS-GATED]**
>
> **[HYBRID] LED-113 — Weekly Minimum Pot Account.** Each active GM MAY have a
> per-week `min:{team}:{week}` holding account when the Weekly Minimum sourcing
> sequence is enabled (Row 5). Funded at weekly release; accepted-bet spend
> draws from it first, spend beyond the minimum draws from Wallet; winnings land
> only in Wallet, never back into min. Unspent min at week close sweeps per the
> commissioner destination (Championship or Frozen). **[OPUS-GATED]**

## 3.4 Transaction Record

**LED-201 — Transaction Identity**
Every transaction SHALL have a globally unique immutable Transaction ID and one
immutable posting timestamp.

**LED-202 — Transaction Contents**
Every transaction SHALL record: Transaction ID and idempotency key; transaction
type and protocol identifier; League ID and season ID; Fantasy Week when
applicable; related wager, Pool occurrence, Pot distribution, Top-Off, or
correction identifier when applicable; actor or initiating system process when
applicable; posting timestamp and Specification version; all debit and credit
entries; human-readable description sufficient to explain the movement; original
transaction reference when the transaction is a reversal or correction.

**LED-203 — Entry Contents**
Every Ledger entry SHALL record the Transaction ID, Account ID, entry direction,
integer BAB-cent amount, and resulting account balance or sufficient data to
derive it deterministically.

**LED-204 — Chronological Ordering**
Transactions SHALL be ordered by committed posting timestamp and a deterministic
sequence number for transactions committed at the same timestamp.

**LED-205 — Transaction Types**
Only protocol-defined transaction types may post. At minimum, the Ledger SHALL
support: initial BAB allocation; wager escrow reservation; Final Lock escrow
refund; wager payout; Push refund; Void or cancellation refund; Pool entry
reservation; Pool payout; Pool rollover transfer; Weekly Minimum contribution;
Skunk contribution; Championship Pot distribution; Skunk Pot distribution;
approved BAB Top-Off; compensating correction; protocol-authorized BAB
retirement.

> **[HYBRID]** Add transaction types: Reserve credit at buy-in; weekly Reserve
> release to Wallet; season-end Reserve sweep to Championship; Frozen credit;
> Frozen return at reconciliation; weekly-min pot funding; weekly-min spend;
> weekly-min sweep. (Rows 5, 6.)

## 3.5 Posting Protocols

### 3.5.1 Initial Allocation and Top-Offs

**LED-301 — Initial BAB Allocation**
When a League season initializes, each eligible GM SHALL receive the configured
initial BAB allocation through one transaction per GM or one atomic batch
transaction: debit the League BAB Issuance account; credit the GM Wallet account;
record the League Configuration and season initialization event.

> **[HYBRID]** When Reserve is enabled, initial allocation splits: debit
> Issuance; credit the GM Wallet for the released/wagerable portion; credit
> `reserve:{team_id}` for the reserved fraction (default 4/11). Both legs in one
> atomic transaction; total equals the configured buy-in. (Row 6.)

**LED-302 — Approved Top-Off**
An approved Top-Off SHALL post as follows: debit the BAB Issuance account for the
approved amount; credit the approved GM Wallet for the same amount; reference the
request, approval, approver, GM, amount, and timestamp.

**LED-303 — Rejected Top-Off**
A rejected or expired Top-Off request SHALL produce no Ledger transaction.

### 3.5.2 Escrow Reservation and Release

**LED-311 — Versus Escrow Reservation**
When a Versus Bet is accepted, each GM's maximum possible loss SHALL move from
that GM's Wallet to that GM's Escrow: debit the GM Wallet; credit the same GM
Escrow; reference the wager acceptance or Dynamic Handshake.

> **[HYBRID]** The issuer's Anchor Stake escrows at ISSUE (GE-308 [HYBRID]); the
> opponent's Derived Stake escrows at acceptance, with the issuer's escrow
> trued-up to any countered amount at the same instant (GE-505 [HYBRID]). Each
> side's escrowed amount is its own floored whole-cent stake (Rows 2, 3), not a
> shared equal amount. Weekly-min spend draws from `min:{team}:{week}` first,
> then Wallet (Row 5). **[OPUS-GATED]**

**LED-312 — Pool Entry Reservation**
When a Prediction Pool ticket is created or an automatic Rank contribution
becomes due, the required entry amount SHALL move from the participant Wallet to
participant Escrow or directly to a dedicated Pool holding account if the
implementation preserves the same ownership and audit guarantees.

**LED-313 — Insufficient Wallet**
A reservation SHALL NOT post when the required Wallet debit would cause a negative
Wallet balance. The related acceptance or entry SHALL fail atomically.

**LED-314 — Final Lock Refund**
When The Adjustment reduces a Dynamic Challenge obligation, excess BAB SHALL
return to the originating GM: debit that GM's Escrow; credit that GM's Wallet;
reference the Final Lock and Adjustment record.

**LED-315 — Cancellation Refund**
When a protocol permits cancellation after a reservation but before Pending, each
reserved amount SHALL move from the participant Escrow back to the originating
Wallet.

> **[HYBRID]** On decline or expiry of an issued-but-unaccepted Versus Bet, the
> issuer's issue-time escrow reverses back to Wallet/min (GE-308 [HYBRID]).

**LED-316 — Push Refund**
A Push SHALL move every participant's remaining wager Escrow back to the
originating Wallet. No BAB SHALL transfer between participants.

**LED-317 — Void Refund**
A Void SHALL move every participant's remaining wager or Pool Escrow back to the
originating Wallet. No BAB SHALL transfer between participants or Pots unless a
previously posted unrelated contribution remains valid under its own protocol.

### 3.5.3 Versus Settlement

**LED-321 — Two-Party Versus Payout**
A final two-party Versus settlement SHALL distribute all remaining wager Escrow
according to the frozen official payout terms. The settlement MAY use direct
account-to-account entries or a zero-ending Clearing account, but SHALL produce
the same final balances.

**LED-322 — Direct Versus Posting**
When direct posting is used: debit the losing GM Escrow by the losing amount;
debit the winning GM Escrow by any return-of-stake amount held there; credit the
winning GM Wallet with the complete official payout, including returned stake
where applicable; credit the losing GM Wallet with any unused or refundable
Escrow, if applicable; leave both wager-specific Escrow obligations at zero.

> **[HYBRID]** Payout is sourced from the actual escrow balances (the two floored
> asymmetric stakes), never recomputed as `2 × amount`. The winner receives the
> true sum of both escrowed stakes. (Rows 2, 3; FR-5.9/5.10 precedent.)

**LED-323 — No House Account**
No portion of a Versus settlement SHALL credit Fantasy Beefs, a Commissioner, an
administrator, or any house-revenue account. The platform charges no vig and is
never the counterparty.

**LED-324 — Payout Conservation**
The total BAB credited from a Versus settlement SHALL equal the total BAB debited
from the associated Escrow accounts, excluding separately recorded protocol
contributions that were not part of that wager.

### 3.5.4 Pool Settlement and Rollover

**LED-331 — Pool Balance**
The distributable Pool balance SHALL equal the sum of valid entry contributions
plus any attached rollover, less only protocol-authorized refunds or transfers
recorded before settlement.

**LED-332 — Pool Payout**
A Pool settlement with winning claims SHALL: debit the Pool holding, participant
Escrow, and any attached rollover accounts for the full distributable balance;
credit each winning GM Wallet with that GM's integer BAB-cent payout; credit the
Championship Pot with any indivisible equal-split remainder; leave the Pool
occurrence with zero unsettled balance.

**LED-333 — Pool Rollover**
When no eligible winning claim exists and the Wager Definition requires rollover:
debit the Pool occurrence holding balance; credit the dedicated rollover account
for the same Pool Wager Definition; reference the originating and next eligible
Pool occurrence when known.

**LED-334 — Rollover Attachment**
When the next eligible Pool occurrence opens, its attached rollover SHALL be
recorded without creating or destroying BAB. The rollover remains in its
dedicated account until settlement or a protocol-authorized season-end sweep.

**LED-335 — Season-End Rollover Sweep**
A remaining rollover swept to the Championship Pot SHALL post as a debit to the
Pool rollover account and an equal credit to the Championship Pot account.

### 3.5.5 Pot Contributions and Distributions

**LED-341 — Weekly Minimum Shortfall**
A Weekly Minimum shortfall contribution SHALL post as: debit the responsible GM
Wallet for the shortfall amount; credit the Championship Pot for the same amount;
reference the Fantasy Week and shortfall calculation.

> **[HYBRID]** When the commissioner selects Frozen as the destination, the
> shortfall/unspent-min credits `frozen:{team_id}` instead of Championship. The
> destination is locked at season kickoff. (Row 6.)

**LED-342 — Insufficient Wallet for Required Contribution**
If a required protocol contribution exceeds the GM's available Wallet, the System
SHALL apply the BAB Economy protocol governing deficiency or Top-Off. The Ledger
SHALL NOT create a negative Wallet or an unbalanced receivable unless a later
Specification expressly creates such an account type.

**LED-343 — Skunk Contribution**
A weekly Skunk contribution SHALL post as a debit to the designated GM Wallet and
an equal credit to the Skunk Pot, referencing the Fantasy Week and deterministic
Skunk result.

**LED-344 — Championship Pot Distribution**
At authorized season close, the complete distributable Championship Pot balance
SHALL be debited and the recipient Wallets SHALL be credited according to League
Configuration. Any integer remainder SHALL follow the configured deterministic
remainder rule.

> **[HYBRID]** Championship distribution is 60/30/10 (1st/2nd/3rd) by default;
> leftover cents from the floor-division split go to 1st place so payouts sum to
> the total exactly. Reserve sweeps and Frozen returns resolve before this
> distribution. (Row 6.)

**LED-345 — Skunk Pot Distribution**
At authorized season close, the complete distributable Skunk Pot balance SHALL be
debited and the winning GM Wallet or configured recipient Wallets SHALL be
credited according to League Configuration.

> **[HYBRID]** Default Skunk recipient is the GM with the highest cumulative
> regular-season Points For. Weekly Skunk is the widest-margin loser, weeks 1–14
> only, $10 default, off-wallet obligation. Tie-split remainder rule is
> **[OPUS-GATED]** (open).

**LED-346 — No Early Pot Withdrawal**
BAB credited to a Pot SHALL NOT return to a GM or be redirected before the
protocol-defined distribution, except by a compensating correction for an invalid
original transaction.

## 3.6 Corrections and Reversals

**LED-401 — Compensating Transaction**
A correction SHALL be implemented through a new balanced transaction that
reverses or offsets the erroneous entries and references the original Transaction
ID.

**LED-402 — No Silent Correction**
The System SHALL NOT replace an incorrect amount, account, timestamp,
description, or reference in a posted transaction. The original record and
correction SHALL both remain visible.

**LED-403 — Correction Authority**
Only a protocol-authorized system process may post a correction. Administrative
approval MAY authorize the process but SHALL NOT permit discretionary
modification of a valid wager outcome.

**LED-404 — Outcome Protection**
A correction MAY repair duplicate posting, wrong account assignment, arithmetic
error, or failed atomic processing. It SHALL NOT be used to override Yahoo
results, official odds, accepted terms, or a valid settlement decision.

**LED-405 — Duplicate Transaction Reversal**
If a duplicate transaction posts despite idempotency controls, the System SHALL
post one compensating transaction for each unauthorized duplicate and SHALL
preserve all related audit records.

## 3.7 Balance and Conservation Invariants

**LED-501 — Nonnegative Wallet**
A GM Wallet SHALL NEVER have a negative posted balance.

**LED-502 — Nonnegative Escrow**
A GM Escrow account SHALL NEVER have a negative posted balance.

**LED-503 — Escrow Reconciliation**
The aggregate balance of all GM Escrow accounts SHALL equal the aggregate
unresolved obligations represented by accepted and Pending wagers and Pools.

**LED-504 — Completed Wager Escrow**
Every Final, Push, Void, Expired, or Cancelled wager SHALL have zero remaining
associated Escrow.

**LED-505 — Zero Clearing**
Every Clearing account SHALL have a zero balance after each transaction and at
the end of every reconciliation cycle.

**LED-506 — BAB Conservation**
Except for explicit postings through the BAB Issuance or BAB Retirement accounts,
the total BAB across all accounts in a League season SHALL remain constant.

**LED-507 — No Implicit Issuance**
Rounding, settlement, refunds, rollover, and Pot distribution SHALL NOT create
BAB. Every credited BAB cent SHALL have an equal debit.

> **[HYBRID]** The floor-both Versus rounding rule (Row 3) satisfies LED-507 by
> construction: the uncollected residue is never credited anywhere, so no BAB is
> created. Escrow holds only the two floored whole-cent stakes.

**LED-508 — No Implicit Destruction**
No BAB cent may disappear because of rounding, truncation, failed settlement,
abandoned Pool, or season close. Every amount SHALL be paid, refunded, rolled
over, transferred to a Pot, or explicitly retired by protocol.

> **[HYBRID] Reconciliation of Row 3 against LED-508.** The floor-both residue is
> NOT destroyed BAB — it is BAB that was never issued into the bet. FairPot is a
> derived ceiling, not a funded balance; the sub-cent gap between fairPot and the
> summed stakes was never staked by either GM, so there is nothing to destroy.
> This must be verified at Opus Math Review: confirm no adversarial line causes a
> funded cent to vanish. **[OPUS-GATED]**

**LED-509 — League Isolation**
No transaction may debit an account from one League season and credit an account
from another League season.

**LED-510 — Account-Type Restrictions**
An account SHALL accept only transaction types authorized for that account type.
For example, BAB Issuance SHALL NOT receive wager winnings and a GM Escrow
account SHALL NOT receive a Top-Off directly.

## 3.8 Reconciliation and Audit

**LED-601 — Continuous Reconciliation**
After every posted transaction, the System SHALL verify that debits equal credits
and that no affected account violates its invariant.

**LED-602 — Wager Reconciliation**
For every accepted wager, the System SHALL be able to reproduce: each participant
reservation; every Final Lock refund; the final settlement or refund; the zero
remaining Escrow balance; the exact net Wallet change for each participant.

**LED-603 — Pool Reconciliation**
For every Pool occurrence, the System SHALL be able to reproduce entry
contributions, attached rollover, refunds, winning claims, payouts, Championship
Pot remainder, rollover transfer, and zero remaining unsettled balance.

**LED-604 — Pot Reconciliation**
For each Pot, the System SHALL be able to identify every funding transaction and
every distribution transaction and reproduce the current balance exactly.

**LED-605 — Season Reconciliation**
Before season archive, the System SHALL verify: all accepted wagers and Pools are
terminal; all GM Escrow balances are zero; all Clearing balances are zero; every
required Pot distribution or rollover sweep has posted; all transactions balance;
total BAB reconciles to authorized issuance less authorized retirement.

> **[HYBRID]** Season reconciliation SHALL additionally verify all
> `reserve:{team_id}` and `frozen:{team_id}` accounts have resolved (Reserve
> swept to Championship; Frozen returned to Wallet) and all `min:{team}:{week}`
> accounts are zero. (Rows 5, 6.)

**LED-606 — Reconciliation Failure**
A failed reconciliation SHALL block season close and create an operational error
record. It SHALL NOT permit manual balance editing or discretionary settlement.

**LED-607 — Historical Reproduction**
The complete balance history of every account SHALL be reproducible solely from
immutable Ledger transactions, without relying on mutable application state.

**LED-608 — Retention**
Ledger transactions, entries, references, and correction chains SHALL be retained
permanently for the life of the Fantasy Beefs record.

## 3.9 Ledger Invariants

**LED-INV-001** — Every Ledger transaction balances exactly.
**LED-INV-002** — Every BAB movement has one canonical transaction record.
**LED-INV-003** — No posted transaction is edited or deleted.
**LED-INV-004** — No Wallet or Escrow balance becomes negative.
**LED-INV-005** — No completed wager retains Escrow.
**LED-INV-006** — No Clearing account retains a balance.
**LED-INV-007** — BAB is created only through the Issuance account.
**LED-INV-008** — BAB is destroyed only through the Retirement account.
**LED-INV-009** — No settlement credits a house, vig, or platform-revenue
account.
**LED-INV-010** — Every League season can be fully reconciled from the Ledger
alone.

### End of Section 3

Section 3 establishes the Ledger as the sole authoritative accounting system.
The merged-hybrid additions (Reserve, Frozen, and Weekly-Min accounts, LED-111
through LED-113) and the floor-both reconciliation notes (LED-507/508) are all
money-path and Opus-gated. Section 4 governs the economic rules that authorize
these movements.
