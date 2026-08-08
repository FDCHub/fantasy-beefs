# Fantasy Beefs — Merged Hybrid · Section 6 — System

*Operational execution, validation, audit, authorization, recovery, and version
control.*

> **[HYBRID] Section-level note.** Section 6 is adopted essentially verbatim — it
> governs HOW protocols execute, not WHAT they decide, so the money-path overrides
> don't touch it. Two clarifying notes are added where the overrides need
> operational support (concurrency on the pending-bucket check; the repricing
> trigger as a scheduled event).

## 6.1 Purpose

The System section governs how Fantasy Beefs executes protocols, validates
requests, controls authorization, records history, handles failures, protects
League isolation, and applies Specification and model versions. This section does
not redefine wager, Ledger, BAB, Simulation, or League Configuration rules
established elsewhere.

## 6.2 Protocol Execution

**SYS-001 — Protocol Authority**
Every state-changing action SHALL execute according to this Specification and the
applicable immutable Wager Definition or League Configuration. Manual discretion
SHALL NOT replace a deterministic protocol.

**SYS-002 — Deterministic Execution**
Given identical authoritative inputs, configuration, Wager Definition,
Specification version, and model version, the System SHALL produce the same
protocol result.

**SYS-003 — Execution Order**
1. Authenticate and authorize the requester or scheduled system process.
2. Load the current authoritative object state.
3. Validate the requested action and all required inputs.
4. Acquire the concurrency controls required to prevent conflicting writes.
5. Execute the protocol logic.
6. Post all required Ledger transactions.
7. Persist object state and immutable audit records.
8. Release concurrency controls.
9. Generate notifications.

**SYS-004 — Atomicity**
Steps that change wager state, Wallets, Escrow, Pots, Ledger records, or audit
records SHALL commit as one atomic transaction. Partial protocol completion is
prohibited.

**SYS-005 — Effective Timestamp**
Each protocol event SHALL use one System-generated effective timestamp. All
records created by that event SHALL reference the same effective timestamp.

**SYS-006 — Authoritative Clock**
Server time in Coordinated Universal Time SHALL govern offer expiration, Final
Lock, settlement ordering, and all protocol deadlines. Displayed local times are
informational only.

**SYS-007 — Event Identity**
Every state-changing protocol request or scheduled event SHALL have a unique
immutable event ID.

**SYS-008 — No Hidden Rules**
A protocol outcome SHALL depend only on recorded authoritative inputs,
configuration, Wager Definitions, model versions, and Specification rules.
Undocumented operator preferences or unpublished calculations are prohibited.

## 6.3 Validation

**SYS-101 — Precondition Validation**
Before execution, the System SHALL validate every precondition required by the
applicable protocol.

**SYS-102 — Required Validation Categories**
Object existence and immutable identity; League and season scope; GM eligibility
and authorization; current lifecycle state; Fantasy Week and timing window; Wager
Definition and League Configuration status; available BAB and Escrow requirements;
duplicate and active-wager limits; required Yahoo, projection, schedule, and
simulation inputs; referential and arithmetic integrity.

> **[HYBRID]** Add to available-BAB validation: the pending-bucket check (Wallet +
> remaining min, minus all pending and locked commitments) so a GM can never
> commit more than he holds (GE-308 [HYBRID]). This check gates offer creation and
> whether an incoming card can be shown.

**SYS-103 — Invalid Request**
If any precondition fails, the System SHALL reject the request, preserve the prior
valid state, and create no Ledger movement.

**SYS-104 — Validation Result**
A rejected request SHALL return a deterministic reason code identifying the first
failed protocol precondition under the System's fixed validation order.

**SYS-105 — No Client Trust**
Client-supplied balances, odds, payouts, state, timestamps, participant
eligibility, and settlement values SHALL be treated as untrusted. The System SHALL
calculate or retrieve authoritative values independently.

**SYS-106 — Revalidation at Commit**
Time-sensitive and balance-sensitive preconditions SHALL be revalidated within the
atomic commit transaction.

**SYS-107 — Immutable Input Snapshot**
Every accepted wager, Handshake, Final Lock, and settlement SHALL store the
authoritative input snapshot required to reproduce the protocol result.

## 6.4 Idempotency and Concurrency

**SYS-201 — Idempotent Execution**
Submitting the same event ID more than once SHALL return the original completed
result and SHALL NOT create duplicate state changes, Ledger entries, payouts,
refunds, or audit records.

**SYS-202 — Concurrent Action Control**
The System SHALL serialize competing actions affecting the same wager, Pool
occurrence, Wallet, Escrow account, Pot, or configuration object.

**SYS-203 — First Valid Commit**
When two mutually exclusive actions compete, the first action that validly commits
SHALL govern. The later action SHALL observe the committed state and be rejected or
returned as already resolved.

**SYS-204 — Balance Concurrency**
Available BAB SHALL be validated and reserved under concurrency control so the same
BAB cannot fund more than one simultaneous obligation.

> **[HYBRID]** Balance concurrency SHALL cover the pending-bucket so the same
> Wallet+min BAB cannot back two simultaneous issued challenges. (Money-model
> ruling.)

**SYS-205 — Scheduled Event Uniqueness**
Expiration, Final Lock, settlement, Weekly Minimum, Skunk, and season-close jobs
SHALL each execute no more than once for the same scope and protocol key.

> **[HYBRID]** Add the Dynamic Challenge repricing/Final-Lock trigger as a
> scheduled event with a deterministic scope key (wager ID + Final Lock time), so
> it fires exactly once per Dynamic Challenge. (Row 1.) **[PENDING CODE-VERIFY]**
> — confirm no such trigger exists yet.

**SYS-206 — Duplicate Delivery**
Repeated delivery of a Yahoo update, schedule event, projection version, or
internal message SHALL NOT duplicate protocol effects.

## 6.5 State Machines

**SYS-301 — Defined States Only**
Every protocol object SHALL occupy a state explicitly defined by this
Specification or its immutable definition.

**SYS-302 — Valid Transition Only**
The System SHALL reject any transition not expressly permitted for the object's
current state.

**SYS-303 — Terminal State Protection**
Terminal objects SHALL NOT be reopened, repriced, relocked, resettled, or
otherwise altered except by a compensating operational correction expressly
allowed by this Specification.

**SYS-304 — State and Ledger Consistency**
A wager SHALL NOT enter a state whose required Ledger condition is false. In
particular, an accepted or Pending wager SHALL have the required Escrow, and a
completed wager SHALL have zero wager Escrow.

**SYS-305 — State Reconstruction**
The current state of every material protocol object SHALL be reconstructable from
its immutable event and audit history.

## 6.6 Audit System

**SYS-401 — Audit Requirement**
Every protocol action that changes state or authoritative data SHALL create an
immutable audit record.

**SYS-402 — Audit Record Contents**
Audit record ID; effective timestamp; event ID and protocol ID; actor type and
actor ID, if applicable; League ID and season ID; Fantasy Week, if applicable;
related wager, Pool, transaction, Wallet, Pot, configuration, or simulation IDs;
prior state and resulting state; authoritative input references; result and
deterministic reason code; Specification version; Wager Definition, configuration,
projection, and model versions when applicable.

**SYS-403 — Audit Immutability**
Posted audit records SHALL NOT be edited or deleted. Corrections SHALL be
represented by new linked audit records.

**SYS-404 — Actor Attribution**
The audit record SHALL distinguish GM actions, Commissioner actions, administrator
actions, automated scheduled actions, and external data synchronization events.

**SYS-405 — Reproducibility**
The audit history SHALL contain or reference sufficient immutable data to reproduce
acceptance, Handshake, Final Lock, settlement, Weekly Minimum, Skunk, Top-Off, and
season-close outcomes.

**SYS-406 — Chronological Ordering**
Audit records SHALL preserve both effective timestamp and a monotonic sequence
within each League so simultaneous events have a deterministic order.

**SYS-407 — No Audit Dependency**
Failure to deliver or display an audit record to a user SHALL NOT change the
underlying protocol result, provided the immutable record was successfully
committed.

## 6.7 Notifications

**SYS-501 — Notification Events**
The System MAY generate notifications for material protocol events, including
offers, acceptance, rejection, expiration, cancellation, Handshake, Final Lock,
settlement, Push, Void, Pool results, Weekly Minimum, Skunk, Top-Off, and season
close.

**SYS-502 — Informational Status**
Notifications are informational only. Delivery failure, delay, suppression, or user
nonreceipt SHALL NOT invalidate or postpone a protocol event.

**SYS-503 — Authoritative Record**
The authoritative state displayed in the Fantasy Beefs application and recorded in
the audit history SHALL govern over notification text.

**SYS-504 — Notification Timing**
Notifications SHALL be generated only after the related protocol event commits
successfully.

**SYS-505 — No Acceptance by Notification**
Opening, clicking, dismissing, or failing to receive a notification SHALL NOT
constitute acceptance, rejection, withdrawal, or any other protocol action.

## 6.8 External Data Synchronization

**SYS-601 — Yahoo Data Authority**
The System SHALL use Yahoo Fantasy Football as the authoritative source for League
membership, teams, rosters, starting lineups, scoring rules, schedules, fantasy
results, and stat corrections.

**SYS-602 — Projection Authority**
The active Fantasy Beefs projection dataset and recorded version SHALL govern
simulation inputs. Projection data SHALL NOT override actual Yahoo results.

**SYS-603 — NFL Schedule Authority**
The System SHALL use its designated authoritative NFL schedule source solely to
determine kickoff and lock timing. The source and retrieved schedule version SHALL
be recorded when used for Final Lock.

**SYS-604 — Synchronization Record**
Every imported authoritative dataset used in a state-changing protocol SHALL record
source, source identifier, retrieval timestamp, effective version, and integrity
status.

**SYS-605 — Stale Data**
The System SHALL NOT knowingly execute a protocol using data that fails the
freshness requirements of the applicable protocol.

**SYS-606 — Unavailable Data**
When required authoritative data is unavailable, the System SHALL retry according
to a fixed operational policy. If the applicable protocol deadline passes without
sufficient data, the protocol-defined failure, delay, or Void result SHALL apply.

**SYS-607 — Conflicting Data**
When successive authoritative updates conflict before settlement, the most recent
valid authoritative update SHALL govern. After settlement, later changes SHALL not
modify the wager unless this Specification expressly provides otherwise.

**SYS-608 — No Manual Substitution**
An administrator SHALL NOT substitute personal judgment, unofficial statistics,
screenshots, media reports, or participant testimony for missing authoritative
data.

## 6.9 Error Handling and Recovery

**SYS-701 — Fail Closed**
If the System cannot prove that a state-changing action is valid, funded,
authorized, and deterministic, it SHALL reject or defer the action rather than
execute it.

**SYS-702 — Rollback**
A failed atomic transaction SHALL roll back every state, balance, Ledger, and audit
write attempted by that transaction.

**SYS-703 — Recovery from Interruption**
After interruption, the System SHALL determine whether the event committed by
checking its event ID and immutable records. It SHALL either return the committed
result or safely resume the uncommitted event.

**SYS-704 — Compensating Correction**
If an operational defect is discovered after commit, the original records SHALL
remain immutable. Any permitted correction SHALL use linked compensating Ledger
entries, state records, and audit records.

**SYS-705 — Correction Limits**
An operational correction MAY repair duplicated technical execution, malformed
storage, or misapplied system mechanics. It SHALL NOT change a legitimate protocol
outcome based on hindsight, participant preference, Commissioner discretion, or
later projections.

**SYS-706 — Unresolvable Wager**
If a wager cannot be deterministically completed because of an operational defect
or missing required data, it SHALL follow the protocol-defined Void process.

**SYS-707 — Error Visibility**
Material failures affecting a user's action or balance SHALL be visible through a
deterministic error status and audit reference.

**SYS-708 — No Silent Balance Change**
The System SHALL NOT change a Wallet, Escrow account, or Pot without a posted Ledger
transaction, even during recovery or correction.

## 6.10 Authentication and Authorization

**SYS-801 — Authentication**
Only an authenticated identity MAY initiate a GM, Commissioner, or administrator
action.

**SYS-802 — GM Authority**
A GM MAY act only for themselves and only within Leagues in which they are an active
member, except where a protocol explicitly allows viewing historical records.

**SYS-803 — Commissioner Authority**
A Commissioner MAY perform only the configuration and Top-Off approval actions
expressly granted by this Specification.

**SYS-804 — Commissioner Prohibitions**
Creating or accepting wagers for another GM; cancelling accepted wagers; changing
odds, stakes, payouts, lines, picks, Pool entries, or settlement values; editing
Ledger or audit history; overriding Yahoo results, simulations, Final Lock, Push,
Void, or settlement; changing in-season configuration except where expressly
permitted.

**SYS-805 — Administrator Authority**
Administrators MAY maintain infrastructure, repair operational defects through
permitted compensating actions, and manage access. Administrators SHALL NOT
exercise gameplay discretion.

**SYS-806 — Least Privilege**
Every role SHALL receive only the minimum permissions required for its protocol
responsibilities.

**SYS-807 — Sensitive Action Record**
Every Commissioner or administrator action affecting configuration, access,
Top-Offs, recovery, or corrections SHALL be audited with actor identity and reason.

## 6.11 League and Season Isolation

**SYS-901 — League Isolation**
A protocol action SHALL affect only the League identified by the authoritative
object and authenticated context.

**SYS-902 — Season Isolation**
Wallets, Pots, configurations, wagers, simulations, and settlement records SHALL be
scoped to one League season unless expressly defined as historical references.

**SYS-903 — Cross-League Prohibition**
BAB, Escrow, wagers, Pools, balances, and configuration SHALL NOT transfer between
Leagues.

**SYS-904 — Cross-Season Prohibition**
BAB and unresolved obligations SHALL NOT carry into a new season except through an
explicit season-close or new-season issuance protocol.

**SYS-905 — Historical Access**
Archived League seasons MAY remain visible for reporting and audit but SHALL be
read-only.

## 6.12 Data Integrity

**SYS-1001 — Immutable Identity**
Every League, season, GM membership, wager, Pool occurrence, ticket, Wallet, Escrow
account, Pot, Ledger transaction, simulation, configuration, Wager Definition, and
audit record SHALL have a unique immutable identifier.

**SYS-1002 — Referential Integrity**
Every stored reference SHALL point to an existing valid object in the same
permitted League and season scope.

**SYS-1003 — Integer BAB**
All BAB amounts SHALL be stored and calculated as integer BAB cents. Floating-point
storage is prohibited.

**SYS-1004 — Arithmetic Integrity**
The System SHALL use deterministic integer arithmetic and explicit rounding rules
for every BAB calculation.

> **[HYBRID]** The explicit rounding rule for Versus derivation is floor-both
> (Row 3, SIM-805/807 [HYBRID]); for Pool splits it is equal-division with
> remainder-to-Championship (GE-1045). Both are deterministic integer rules.

**SYS-1005 — Balance Derivation**
Wallet, Escrow, and Pot balances SHALL be derived from or continuously reconciled to
the Ledger.

**SYS-1006 — Integrity Check**
Before and after each balance-changing transaction, the System SHALL verify balanced
debits and credits, nonnegative protected accounts, and required wager Escrow.

**SYS-1007 — Data Hash or Integrity Marker**
Immutable input snapshots and official simulation outputs SHALL include an integrity
marker sufficient to detect later alteration.

**SYS-1008 — No Destructive Deletion**
Material protocol records SHALL NOT be physically deleted as part of ordinary
operation. Status changes and corrections SHALL preserve historical identity and
relationships.

## 6.13 Versioning

**SYS-1101 — Specification Version**
Every League season SHALL operate under one published Fantasy Beefs Specification
version.

**SYS-1102 — Recorded Version**
Every accepted wager and settled Pool occurrence SHALL permanently record the
Specification version that governed it.

**SYS-1103 — Wager Definition Version**
Every wager SHALL record the immutable Wager Definition version used at creation and
acceptance.

**SYS-1104 — Configuration Version**
Every wager SHALL record or reference the League Configuration version applicable at
acceptance.

**SYS-1105 — Simulation Versions**
Every official simulation SHALL record the model version and projection dataset
version used.

**SYS-1106 — No Retroactive Rule Change**
A later Specification, Wager Definition, configuration, model, or projection version
SHALL NOT alter an accepted or settled wager unless the original governing protocol
expressly incorporates later data before Final Lock.

**SYS-1107 — In-Season Upgrade**
A League season SHALL NOT change Specification versions after its first accepted
wager unless a future Specification defines a deterministic migration protocol.
Version 1.0 provides no such migration.

**SYS-1108 — Historical Reproduction**
Historical outcomes SHALL be reproducible using the versions recorded at the time of
execution.

## 6.14 Data Retention and Archive

**SYS-1201 — Permanent Protocol History**
Wagers, Pool tickets, Ledger transactions, official simulations, configuration
versions, and audit records SHALL be retained for the life of the Fantasy Beefs
record system unless deletion is legally required.

**SYS-1202 — Season Archive**
After season close, the League season SHALL become an immutable archive.

**SYS-1203 — Personal Access Change**
Loss of active League membership SHALL NOT delete or alter the GM's historical
participation records.

**SYS-1204 — Export Consistency**
Any exported report SHALL reconcile to the authoritative stored records and SHALL
identify its generation timestamp and applicable League season.

**SYS-1205 — Legal Deletion**
If law requires removal of personal information, the System SHALL preserve
nonpersonal accounting and protocol integrity through anonymization or legally
permitted substitute identifiers wherever possible.

## 6.15 Operational Requirements

**SYS-1301 — Protocol Priority**
Correctness, accounting integrity, and deterministic execution SHALL take priority
over notification speed, display freshness, or convenience.

**SYS-1302 — Read Availability**
Temporary inability to display records SHALL NOT change their authoritative stored
state.

**SYS-1303 — Write Protection During Incident**
When the System cannot safely guarantee atomic and deterministic writes, it SHALL
suspend affected state-changing actions.

**SYS-1304 — Scheduled Processing**
Protocol jobs SHALL use deterministic scope keys and resumable execution so delayed
processing does not create duplicate results.

**SYS-1305 — Performance Neutrality**
A slow client, delayed notification, or refresh frequency SHALL NOT provide a
different protocol outcome from the same valid server-side action and timestamp.

**SYS-1306 — Out-of-Scope Implementation Detail**
Database technology, API style, user-interface layout, notification wording, hosting
architecture, and programming language are implementation choices and SHALL NOT
change protocol behavior.

## 6.16 System Invariants

**SYS-INV-001** — No state-changing action commits partially.
**SYS-INV-002** — No event executes its economic effect more than once.
**SYS-INV-003** — No Wallet, Escrow account, or Pot changes without a balanced
Ledger transaction.
**SYS-INV-004** — No user interface or notification overrides authoritative stored
state.
**SYS-INV-005** — No Commissioner or administrator may exercise gameplay discretion.
**SYS-INV-006** — No later version retroactively changes an accepted or settled
wager.
**SYS-INV-007** — Every material protocol result is auditable and reproducible.
**SYS-INV-008** — Every League and season remains isolated.
**SYS-INV-009** — Every unresolved protocol failure resolves through retry,
rejection, or protocol-defined Void — never subjective substitution.

### End of Section 6

Section 6 defines the operational controls that make the Fantasy Beefs protocols
deterministic, atomic, auditable, isolated, and recoverable. The only hybrid
touches are operational support for the pending-bucket concurrency (SYS-204) and
the Dynamic repricing trigger as a scheduled event (SYS-205) — both serve the Row
1 and money-model overrides without changing System mechanics.
