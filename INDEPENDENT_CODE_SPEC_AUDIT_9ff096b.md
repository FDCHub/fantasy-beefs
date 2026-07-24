# INDEPENDENT_CODE_SPEC_AUDIT_9ff096b.md

**Label:** Independent audit at repository HEAD `9ff096b`.  
**Reviewer:** ChatGPT, acting as an independent code-and-spec reviewer.  
**Claude status:** This audit was not reproduced or independently verified by Claude.  
**Scope:** Tracked repository contents exported with `git archive`, plus the authoritative specifications supplied for review.  
**Important limitation:** The archive contained no `.git` directory. Commit identity, branch state, push state, deployment state, and Git history could not be independently verified from the archive itself.

---

## 1. Audit purpose

This audit answers four questions:

1. What exists in tracked code?
2. What do the governing specifications require that is absent?
3. Which state claims are verified, reported, or inferred?
4. What sequencing follows from the code and specification dependencies, before considering Claude’s build order?

This is an evidence record. It is not a Master Plan, Findings Register, transition package, or build authorization.

No counts in this document are converted into completion percentages.

---

# 2. Evidence classification

## 2.1 Verified from tracked repository contents

The following conclusions come directly from source, schema, migrations, tests, and specifications present in the archive.

### Repository scale

The audit counted:

- **243 public runtime callables**
- **90 API route functions**
- **17 subsystem groups** in the callable inventory
- substantial existing code for challenges, legacy bets, settlement, ledger, wallets, pools, odds, data providers, authentication, reports, commissioner rules, and synchronization

These counts use the counting method defined later in this document.

### Spec 1 schema exists

Tracked code contains the additive Spec 1 structures:

- `BeefProposal`
- `BeefProposalStarter`
- new proposal-lifecycle fields on `BeefChallenge`
- same-challenge composite foreign-key declarations
- a PostgreSQL migration
- SQLite and PostgreSQL tests for the Spec 1 structures

### Spec 1 service integration is absent

The live challenge service in `beefs/beef_engine.py` does not use the new proposal model.

No references were found there to:

- `BeefProposal`
- `BeefProposalStarter`
- `active_proposal_id`
- `accepted_proposal_id`
- `challenge_mode`
- proposal-lifecycle `response_status`
- the new persisted `wager_type`

The live challenge path continues to use the legacy challenge fields and behaviors.

### Spec 2 is absent as a subsystem

No implementation was found for the Spec 2 source-aware challenge-funding model.

The code does not presently implement:

- issuer escrow at challenge issue
- `escrow:challenge:{id}` source-aware funding
- min-first-then-wallet funding
- ordered funding-leg provenance
- explicit reversal linkage
- reverse-order refunds
- proposal-aware atomic Locked acceptance
- Spec 2 protocol-event identity
- the Spec 2 wallet-locking transaction

The repository contains legacy reservation and accept-time escrow behavior. That behavior is not the Spec 2 subsystem.

### Monte Carlo engines exist

The repository contains code for:

- team-score Monte Carlo simulation
- player-score simulation
- database-backed odds calculation
- headless odds calculation
- probability-to-American-odds conversion in existing modules

### The specified Simulation Engine surface is absent

No `simulation_engine.py` was found.

No concrete implementation was found for the specified operations:

- `o2p`
- `p2o`
- `derive_stakes`
- `adjust_escrow`
- Dynamic Handshake
- informational refresh
- Final-Lock claim
- Final-Lock economic execution
- Final-Lock recovery

### FR-8.7 principal service implementation is present

Tracked code contains substantial FR-8.7 implementation.

`betting/settlement_engine.py` includes:

- `settle_week(..., recovery_token=None)`
- `recover_week(...)`
- `CLAIMED` and `COMPLETED` state handling
- row-locking queries
- recovery-token validation
- completion-state updates
- recovery-oriented audit behavior

Tracked schema and migrations contain:

- `WeekSettlement.status`
- `WeekSettlement.recovery_token`
- settlement-recovery audit fields
- related migrations

This proves that the principal service surface exists in source.

It does not prove full specification completion, migration execution, deployment, or production confirmation.

### Direct float-balance mutation remains

Direct money-balance mutations exist in tracked runtime code.

Examples include:

- `wallet/wallet_manager.py`
- `admin/commissioner_rules.py`
- settlement wallet mirrors in `betting/settlement_engine.py`

The repository alone does not establish which of these are:

- approved compatibility mirrors
- authoritative writes
- prohibited ledger bypasses
- paired with ledger postings elsewhere in the same transaction

### Backend authentication exists

The backend contains real authentication and authorization functions, including:

- password hashing
- password verification
- JWT creation
- current-user resolution
- current-GM resolution
- commissioner authorization
- team ownership checks
- wallet ownership checks
- registration
- authentication
- promotion
- user seeding

A status statement that says only “login is a hardcoded development token” is incomplete when applied to the backend.

That statement may still describe the frontend or deployed configuration.

### Primary frontend lacks the core challenge calls

`tools/app.html` contains no calls to:

- `/beef/challenge`
- `/beef/respond`

The backend routes exist. The reviewed primary frontend does not invoke them.

### Pool implementation does not match the full target catalog

The pool engine includes existing configuration, entry collection, prediction, pick, retrieval, and settlement functions.

Concrete target gaps identified include:

- Bench Burn evaluator
- dynamic n-way payout allocation
- a true 12-GM The Lineup rank-pool implementation
- removal of the retired Worst Beat behavior

A complete pool denominator could not be established because no frozen Spec 4 document defining the final callable surface was available.

### Engine construction governance exists

Tracked code contains:

- `db/engine_factory.py`
- governed engine construction
- the SQLite foreign-key connection hook
- the AST-based bypass-control test

This proves the source implementation exists.

It does not prove deployment.

### Current tracked source no longer embeds the identified database URL

The three identified scripts now read `DATABASE_URL` from the environment and fail closed when it is absent.

Tracked `.gitignore` content includes `.env` protections.

The archive contains no Git history, so historical exposure could not be independently inspected.

---

## 2.2 Reported state not independently verified from the archive

The following claims came from supplied handoffs, registers, or user-provided command results.

They were not independently verified from the `git archive` because the archive contains no Git metadata and no production access.

- Branch is `remediation/foundation-phase-1`.
- Repository HEAD is `9ff096b`.
- `9ff096b` is pushed.
- `c353d2b` is pushed.
- Local and remote are in sync.
- Production still runs an image predating af-1, af-2, and Spec 1.
- The Spec 1 migration has not been executed.
- Production PostgreSQL is version 18.x.
- Production public networking is enabled.
- A restore-tested encrypted production dump exists.
- Production contains no wager or settlement rows.
- Current public production network address uses `hayabusa`.
- Historical source used `reseau:54032`.
- The historical credential remains present in pushed Git history.
- `reseau:54032` has not yet been classified by a TCP check or authenticated identity probe.
- FR-8.7 migrations have not been run.
- FR-8.7 has not been deployed.
- af-1, af-2, Spec 1, and the credential-source fix have not been deployed.

---

## 2.3 Inferences

The following conclusions are reasoned interpretations rather than direct observations.

### Parallel old and new challenge models

**Inference:** The repository currently carries two parallel challenge representations:

- the new additive Spec 1 schema
- the legacy service flow

This follows from the new schema existing while the challenge service continues to use only legacy fields.

### A deployment would activate foundation behavior without enabling the new product flow

**Inference:** Deploying the engine-factory changes and Spec 1 schema would change infrastructure and schema behavior, but would not make the proposal lifecycle reachable because the service layer remains unconnected.

### Correctly priced Locked Challenges can use a pure pricing kernel before Dynamic orchestration exists

**Inference:** Pure pricing functions can be separated from the Dynamic Handshake and Final-Lock lifecycle.

This follows from the Simulation Engine specification separating:

- odds/probability conversion
- stake derivation
- Dynamic adjustment and lifecycle execution

This decomposition must still be checked against the complete certified JavaScript mechanic and the frozen Simulation Engine specification before build authorization.

### `reseau` may represent an old endpoint for the same database

**Inference only:** The historical `reseau` address may be a stale Railway proxy assignment for the same database.

DNS resolution and hostname mismatch do not prove this.

---

# 3. Counting method

## 3.1 Included

The audit counted public runtime callables in tracked production modules:

- top-level functions
- public class methods
- public computed properties where they form part of the runtime service surface
- API route functions

## 3.2 Excluded

The following were excluded from the 243-callable count:

- names beginning with `_`
- tests
- migration entry points
- one-time data-seeding scripts
- one-time maintenance scripts
- Pydantic request and response classes
- SQLAlchemy model classes that define no runtime methods
- HTML/JavaScript callbacks that could not be normalized reliably into the Python callable inventory
- broad protocol behaviors that do not map cleanly to one callable

## 3.3 Meaning of absent counts

An absent count represents concrete required operations with no implementation found in the relevant runtime source.

It does not necessarily mean the final implementation must contain the same number of functions.

Several protocol operations may be combined into one transactional service.

## 3.4 Denominator labels

Each module uses one of these denominator labels:

- **Exact:** the governing specification defines a concrete, countable operation surface.
- **Lower bound:** at least the listed operations are absent, but the full denominator cannot be established.
- **Unavailable:** the available specifications do not define a complete countable operation surface.

---

# 4. Module inventory

## 4.1 API and application surface

**Purpose:** HTTP access to authentication, league data, bets, challenges, wallets, payments, FAAB/BAB, rules, synchronization, and reports.

### Present

**90 route functions**

Counted route groups:

- Authentication: 4
- League, roster, standings, projections, and odds: 9
- Legacy bets and settlement: 8
- Wallet: 3
- Beef challenges: 4
- Feed: 2
- Payments and treasury: 12
- FAAB/BAB: 12
- Commissioner rules: 12
- Tuesday synchronization: 3
- Reports and account: 15
- Pool routes: 8
- Health and war-room functions: 5

### Absent

**6 concrete route capabilities identified**

1. Proposal-based challenge issuance.
2. Proposal-based counter.
3. Proposal-based acceptance.
4. Proposal revive.
5. Dynamic informational refresh.
6. Final-Lock status or result retrieval.

### Denominator

**Lower bound / medium confidence.**

The specifications define service behavior more precisely than final HTTP routing.

---

## 4.2 Authentication

**Purpose:** Registration, login, JWT authentication, role checks, and ownership authorization.

### Present

**12 public functions**

- `hash_password`
- `verify_password`
- `create_access_token`
- `get_current_user`
- `get_current_gm`
- `require_commissioner`
- `assert_own_team`
- `assert_own_wallet`
- `register_user`
- `authenticate_user`
- `promote_user`
- `seed_users`

### Absent

**0 backend function-level omissions identified**

This does not assess frontend login completeness or deployed auth configuration.

### Denominator

**Unavailable / medium confidence.**

No single frozen authentication specification defines the full product denominator.

---

## 4.3 Challenge engine

**Purpose:** Issue, respond to, counter, and retrieve bilateral Versus Challenges.

### Present

**4 public functions**

- `issue_challenge`
- `respond_to_challenge`
- `counter_challenge`
- `get_pending_challenges`

### Absent

**7 Spec 1 lifecycle capabilities**

1. Create an immutable initial proposal.
2. Create a counter as a new immutable proposal.
3. Move the active-proposal pointer.
4. Accept the active proposal without repricing.
5. Perform actor-authorized decline, cancel, and expiry transitions.
6. Revive into a new challenge with lineage.
7. Serialize first-valid-commit transitions with row locking.

### Denominator

**Exact at capability level / high confidence.**

The seven items are a functional decomposition. They are not necessarily seven separate production functions.

---

## 4.4 Challenge escrow and atomic acceptance

**Purpose:** Source-aware issue escrow, capacity validation, refunds, and atomic proposal acceptance.

### Present

**0 Spec 2 services identified**

Legacy reservation and accept-time bet escrow exist but do not implement Spec 2.

### Absent

**9 Spec 2 capabilities**

1. Fund issuer challenge escrow at issue.
2. Draw funds min-first and then wallet.
3. Record ordered funding-leg provenance.
4. Link every reversal to its original funding leg.
5. Validate counter top-up and refund capacity without moving funds.
6. Reverse issue escrow on decline.
7. Reverse issue escrow on cancellation or expiry.
8. Perform atomic Locked acceptance with issuer true-up and recipient funding.
9. Emit idempotent protocol events under deterministic wallet locking.

### Denominator

**Exact at capability level / high confidence.**

These may be implemented through fewer than nine public functions.

---

## 4.5 Legacy bet placement and locking

**Purpose:** Place single-party straight, spread, over/under, and prop bets and determine lock time.

### Present

**5 public functions**

- `place_straight_bet`
- `place_spread_bet`
- `place_over_under`
- `place_prop_bet`
- `is_bet_locked_for_gm`

### Absent

No reliable final denominator was established.

### Verified concern

The legacy routes remain live in tracked source.

### Denominator

**Unavailable.**

The target retirement policy is not expressed as one complete callable specification.

---

## 4.6 Pool engine

**Purpose:** Pool setup, weekly entries, predictions, picks, retrieval, and settlement.

### Present

**8 public functions**

- `setup_pool_config`
- `get_pool_config`
- `collect_weekly_entries`
- `submit_worst_beat_prediction`
- `get_pool_predictions`
- `settle_pool`
- `get_pool_week`
- `submit_pool_pick`

### Absent

**At least 4 target capabilities**

1. Bench Burn evaluator.
2. Dynamic n-way payout allocation.
3. True 12-GM The Lineup rank-pool settlement.
4. Removal of Worst Beat behavior.

### Denominator

**Lower bound / low-to-medium confidence.**

No frozen Spec 4 callable denominator was available.

---

## 4.7 Settlement and FR-8.7

**Purpose:** Evaluate wagers, close escrow, update balances, claim weekly settlement, and recover interrupted settlement.

### Present

**2 principal service functions**

- `settle_week`
- `recover_week`

Additional public computed values:

- `WalletMovement.net`
- `SettlementReport.house_edge`

Tracked implementation also includes lifecycle handling for:

- `CLAIMED`
- `COMPLETED`
- recovery tokens
- row locking
- completion updates
- recovery audit behavior

### Absent

**0 principal FR-8.7 service functions identified as absent**

### Verification work still outstanding or unverified

- Tests 6c and 6d.
- Settled-reader audit.
- Review package.
- Final review.
- Migration execution.
- Deployment.
- Production confirmation.

### Other settlement gaps

**At least 2**

1. Frozen-lineup beef scoring.
2. Removal of the legacy single-party settlement branch.

### Denominator

- **FR-8.7 principal service surface: exact / high confidence.**
- **Full settlement roadmap: unavailable.**

“Zero service functions absent” does not mean the full FR-8.7 specification is complete.

---

## 4.8 Ledger

**Purpose:** Balanced postings and account-balance authority.

### Present

**4 public functions**

- `create_ledger_table`
- `balance_of`
- `trial_balance`
- `post`

### Absent

**2 concrete Spec 2 integration capabilities**

1. Externally supplied protocol-event or idempotency identity on `post`.
2. Native funding-leg provenance and reversal linkage.

### Denominator

**Exact for the identified Spec 2 integration surface / high confidence.**

---

## 4.9 Wallet and FAAB/BAB

**Purpose:** Deposits, balances, transaction history, top-offs, transfers, freezes, and seasonal wallets.

### Present

**20 public callables**

Wallet:

- `deposit`
- `balance_check`
- `balance_check_by_team`
- `transaction_history`
- `validate_bet_amount`
- `WalletState.net_pnl`

FAAB/BAB:

- `setup_faab_config`
- `get_faab_config`
- `init_season_wallets`
- `get_faab_wallet`
- `get_league_faab`
- `create_bet_topup`
- `create_waiver_topup`
- `confirm_topup`
- `apply_pending_topups`
- `transfer`
- `check_and_freeze`
- `set_freeze`
- `get_faab_transactions`
- `get_bet_funded`

### Absent or nonconforming

**At least 3**

1. Challenge issue funding from weekly minimum and then wallet.
2. Strict reverse-order source refund.
3. Ledger-exclusive deposit authority.

### Denominator

**Lower bound.**

The complete VAL-10 denominator spans schema, authority, reconciliation, migration, idempotency, and UI behavior. It cannot be represented reliably as a function count.

---

## 4.10 Odds and Simulation Engine

**Purpose:** Outcome simulation, probability conversion, odds, stake derivation, Handshake, and Final Lock.

### Present

**7 public functions**

- `load_scoring_from_db`
- two `run` functions
- two `simulate_scores` functions
- two `simulate_player_scores` functions

### Absent

**9 specified capabilities**

1. `o2p`
2. `p2o`
3. `derive_stakes`
4. `adjust_escrow`
5. Handshake funding and model freeze
6. Informational refresh
7. Durable Final-Lock claim
8. Atomic Final-Lock economic execution
9. Deterministic Final-Lock recovery or reclaim

### Denominator

**Exact at capability level / high confidence.**

These nine items are not equivalent implementation units. They mix pure functions, durable services, and recovery workflows.

---

## 4.11 Data providers and ingestion

**Purpose:** Provider abstraction, Yahoo and mock data access, FantasyPros projections, scoring normalization, and NFL schedule ingestion.

### Present

**20 public callables**

The count includes:

- provider-interface and provider-implementation methods
- FantasyPros ingestion functions
- week normalization
- schedule-ingestion functions

### Absent

No complete operational denominator was established.

### Denominator

**Unavailable.**

Static presence does not prove Yahoo production authentication, freshness, completeness, or runtime reliability.

---

## 4.12 Decision and roster-analysis engine

**Purpose:** Projection distributions, roster evaluation, lineup optimization, season simulation, and team health.

### Present

**9 public callables**

- `evaluate_move`
- `LineupOptimizer.optimize`
- `score_raw`
- `ProjectionEngine.to_dist`
- `ProjectionEngine.to_player_proj`
- `ProjectionEngine.score_roster`
- `RosterStateEngine.apply_move`
- `SeasonSimulator.simulate`
- `TeamHealthAssembler.assemble`

### Absent

**At least 1**

- beef-specific frozen-lineup scoring

### Denominator

**Lower bound / low confidence.**

No single frozen decision-engine specification defines the complete surface.

---

## 4.13 Tuesday synchronization

**Purpose:** Scheduled refresh, settlement, rule execution, freezes, top-ups, wrap generation, rankings, and notifications.

### Present

**5 public callables**

- `StepResult.as_dict`
- `run_tuesday_sync`
- `setup_scheduler`
- `get_run_history`
- `get_run_detail`

The module also contains private step functions not counted here.

### Absent

**At least 1**

- Dynamic Final-Lock trigger integration

### Denominator

**Lower bound / medium confidence.**

---

## 4.14 Payments and economy

**Purpose:** Economy configuration, treasury, buy-ins, Stripe events, and payouts.

### Present

**18 public callables**

- Economy configuration: 5
- Stripe and treasury: 13

### Absent

**At least 3**

1. Season-fixed configuration freeze at the first accepted wager.
2. Canonical league-scoped championship-account enforcement across all paths.
3. Weekly-minimum account lifecycle under the target economy model.

### Denominator

**Lower bound / low-to-medium confidence.**

No frozen Spec 5 callable denominator was available.

---

## 4.15 Commissioner rules

**Purpose:** Parse, draft, activate, execute, and audit commissioner rules.

### Present

**12 public functions**

- `parse_rule_text`
- `create_rule_draft`
- `activate_rule`
- `pause_rule`
- `delete_draft`
- `get_rule`
- `list_rules`
- `release_escrow`
- `execute_weekly_rules`
- `execute_end_of_season_rules`
- `get_rule_executions`
- `get_rule_audit_log`

### Absent

No complete denominator was established.

### Open audit risk

Direct money-balance mutations exist in `admin/commissioner_rules.py`.

Their classification remains unresolved.

Required follow-up:

- transaction-level caller inventory
- ledger-posting inventory
- approved-mirror versus authoritative-write classification
- divergence test

### Denominator

**Unavailable.**

---

## 4.16 Reports and feed

**Purpose:** Challenge feed, account summary, rankings, settlement reports, and weekly wrap-up.

### Present

**20 public callables**

- Feed: 8
- Account: 1
- Rankings: 4
- Settlement report: 1
- Weekly wrap-up: 6

### Absent

**At least 3**

1. Proposal-version-aware feed events.
2. Final-Lock and Adjustment events.
3. Display explanation when frozen beef scoring differs from Yahoo totals.

### Denominator

**Lower bound / low confidence.**

The obligations are distributed across several specifications.

---

## 4.17 Database runtime and engine governance

**Purpose:** Governed engine construction, database sessions, roster reads, and team-ID resolution.

### Present

**5 public callables**

- `get_engine`
- `get_db`
- `TeamResolver.yahoo_to_db`
- `TeamResolver.db_to_yahoo`
- `build_team_resolver`

### Absent

**0 missing callable requirements identified against the engine-control specification**

### Non-callable open issues

This count does not address:

- misleading health database-path reporting
- deployed `db.schema` import hang
- deployment lag
- production observability

### Denominator

**Exact for the governed engine-control callable surface / high confidence.**

---

## 4.18 Frontend

**Purpose:** GM-facing league and wager interaction.

The reviewed frontend is HTML and JavaScript rather than a Python callable module.

### Present

**0 core challenge API integrations identified**

### Immediately absent

**2**

1. Challenge issuance integration.
2. Challenge response integration.

Additional proposal, counter, refresh, Adjustment, and Final-Lock calls will be required after their backend contracts exist.

### Denominator

**Unavailable.**

The final API and UI contract is not yet stable enough for a complete count.

---

# 5. Aggregate counts

| Measure | Count |
|---|---:|
| Public runtime callables counted | 243 |
| API route functions | 90 |
| Existing challenge public functions | 4 |
| Spec 1 lifecycle capabilities absent | 7 |
| Spec 2 capabilities absent | 9 |
| Simulation Engine capabilities absent | 9 |
| FR-8.7 principal service functions present | 2 |
| FR-8.7 principal service functions absent | 0 identified |
| Frontend core challenge integrations present | 0 |
| Frontend immediately absent core integrations | 2 |

These counts do not form a project completion percentage.

The shorthand statement that “approximately 25 high-authority operations are missing” is a summary estimate only. It is not an audited total and must not be presented as one.

A more precise statement is:

> The highest-authority missing capabilities cluster in three areas: Spec 1 service integration, the Spec 2 funding-and-acceptance subsystem, and the Simulation Engine.

Most supporting subsystems have substantial existing code, but several remain nonconforming or operationally unverified.

---

# 6. Independent sequencing view

This sequence was formed before reading Claude’s quarantined build order.

## 6.1 Complete active production-security remediation

Before adding more production-facing money-path work:

- classify the historical `reseau` network address
- complete the current production credential rotation
- decide and verify public-networking state
- unset ambient production database variables
- establish the controlled deployment and rollback procedure

Reason:

Every later migration and deployment depends on a safe production-access model.

## 6.2 Close FR-8.7 verification and release work

The principal implementation already exists.

Complete:

- Tests 6c and 6d
- settled-reader audit
- review package
- final review
- migration authorization and execution
- deployment
- production confirmation

Reason:

This is bounded work governing settlement crash recovery. Spec 2 will add more escrow complexity. Settlement claim and recovery behavior should not remain ambiguous while new money paths are added.

## 6.3 Deploy the completed foundation and Spec 1 schema

Use a controlled deployment window to:

- deploy the governed engine path
- activate SQLite foreign-key enforcement in the deployed code path
- apply the Spec 1 migration under separate authorization
- correct misleading health reporting
- investigate the deployed `db.schema` import hang
- verify rollback from the known backup

Reason:

Spec 2 should be built and tested against the engine, schema, and transaction patterns production will actually run.

## 6.4 Resolve the transaction-isolation entry gate

Before Spec 2 relies on deterministic wallet locking, prove:

1. the actual PostgreSQL isolation level used by the relevant transaction
2. `SELECT ... FOR UPDATE` serializes conflicts as intended
3. two concurrent attempts yield exactly one valid economic result
4. the test uses the same engine, session, and transaction-construction pattern intended for Spec 2

Reason:

An intended isolation setting is not evidence of actual isolation behavior.

## 6.5 Build Spec 2

Build the complete source-aware challenge-funding subsystem:

- issue escrow
- funding provenance
- reversal linkage
- capacity validation
- strict refunds
- atomic acceptance
- deterministic locking
- idempotent protocol events

Reason:

This connects the Spec 1 proposal model to real economic behavior.

## 6.6 Decompose Spec 3 for implementation

### Spec 3A — pure pricing kernel

Candidate surface:

- `o2p`
- `p2o`
- `derive_stakes`
- immutable result types
- adversarial math tests
- pricing provenance contract

### Spec 3B — Dynamic orchestration

Candidate surface:

- Handshake
- model freeze
- informational refresh
- `adjust_escrow`
- Final-Lock claim
- economic adjustment
- refunds
- recovery
- final-term freeze

This decomposition must be validated against the complete certified JavaScript calculator and Spec Rev 7 before implementation.

Full Spec 3 remains required before betting activation.

## 6.7 Begin frontend work against frozen contracts

Frontend work can overlap once:

- the Spec 2 proposal and escrow API shape is frozen
- the pricing payload is frozen

Use fixtures for:

- Locked offer
- incoming offer
- counter
- acceptance
- Anchor and Derived stakes
- funded pot
- payout display

Do not freeze Dynamic-specific Adjustment states until the Dynamic contract is settled.

## 6.8 Build economy and account identity before pools

Establish:

- canonical league-scoped championship identity
- fixed economy configuration
- weekly-minimum account lifecycle

Then rebuild the target pool catalog and settlement behavior.

Reason:

Pool remainder handling depends on the correctness of its destination accounts.

---

# 7. Comparison with Claude’s build order

This section was written only after the independent sequence above was complete.

## 7.1 Independent agreement

The following agreements were reached independently.

### Security remediation before further production work

Independent agreement.

The production-security state affects every later migration and deployment.

### Spec 2 as the next major product subsystem

Independent agreement.

Spec 1’s schema is not economically active without Spec 2.

### Spec 3 remains required before betting activation

Independent agreement.

The target product requires asymmetric pricing and Dynamic behavior. No symmetric fallback is acceptable.

### Economy/account identity before pools

Independent agreement.

Pool remainders and shared accounts require canonical account identity first.

### Frontend wiring and a GM walkthrough as activation gates

Independent agreement.

The reviewed frontend contains no core challenge calls.

## 7.2 Agreement reached after reviewing Claude’s material

No major sequencing conclusion was adopted solely because Claude’s plan stated it.

Claude’s documents reinforced several dependencies already reached independently.

## 7.3 Differences

### FR-8.7 should close before Spec 2

The independent audit found FR-8.7’s principal implementation already present.

Therefore, the remaining verification and release work should close before a larger escrow subsystem is opened.

### Spec 1 should not be labeled “shipped”

Recommended status:

> Implemented, tested, and committed; migration and deployment pending.

“Shipped” implies operating-environment delivery.

### The target backend should not be labeled broadly “built”

A more accurate statement is:

> Legacy engines and several foundation modules exist. The target proposal, source-aware escrow, asymmetric pricing, Dynamic lifecycle, and frontend path remain incomplete.

### Backend authentication and frontend login must be separated

Recommended status:

- backend authentication and authorization: present
- frontend login experience: absent, incomplete, or development-stubbed

### Spec 3 should be decomposed internally

The independent view separates pure pricing from Dynamic lifecycle work.

This is an implementation decomposition, not a change to the requirement that all of Spec 3 be completed before betting activation.

### Frontend work can overlap

Frontend work need not wait for every Dynamic service if stable Spec 2 and pricing contracts exist.

Activation must still wait for the full verified path.

### FR-VAL10-ac should be dependency-driven

The isolation and concurrency proof is a Spec 2 entry gate.

Other ac work should not automatically interrupt the main build path unless its dependency is established.

### Historical and current database addresses must not be described as proven distinct databases

Accurate wording:

> Two distinct network addresses; service and database identity unresolved.

---

# 8. Assumptions open to challenge

## 8.1 FR-8.7 completeness

The principal service surface exists.

This does not prove complete compliance with the frozen specification.

Open verification includes tests, reader coverage, migrations, review, deployment, and production behavior.

## 8.2 Spec 1 absent-operation count

The seven listed items are protocol capabilities.

A final implementation may combine them into fewer service functions.

## 8.3 Spec 2 absent-operation count

The nine listed items are protocol capabilities.

A final implementation may combine several into one transactional service.

## 8.4 Simulation Engine absent-operation count

The nine listed items mix:

- pure mathematical functions
- durable services
- transaction workflows
- recovery operations

They are not equivalent units of work.

## 8.5 “Most supporting subsystems are present”

This is directionally true at the source-code level.

It does not mean those subsystems are conforming, deployed, or operationally verified.

Known exceptions include:

- direct float mutations
- legacy single-party routes
- pool target mismatch
- frontend absence
- frozen-lineup scoring absence
- deployment lag

## 8.6 Commissioner-rules direct mutations

Verified fact:

- direct balance mutations exist

Unresolved:

- whether they are approved mirrors
- whether ledger postings occur in the same transaction
- whether they are authoritative writes
- whether they can produce divergence

This remains an audit finding, not a confirmed defect classification.

## 8.7 Database-runtime “0 absent”

This means no missing callable was identified against the engine-control specification.

It does not close:

- misleading health reporting
- deployed import hangs
- deployment
- observability
- production parity

## 8.8 Spec 3A and Spec 3B boundary

The proposed split is architectural.

It must be validated against:

- the complete certified JavaScript calculator
- Flexible Stake and Return behavior
- `adjust_escrow`
- Spec Rev 7 lifecycle authority

## 8.9 Static source presence versus operational correctness

A function being present does not prove:

- correct configuration
- real provider authentication
- production execution
- migration state
- concurrency behavior
- deployment
- runtime data quality

## 8.10 Archive limitations

Because the review used `git archive`, it could not independently verify:

- commit history
- branch identity
- remote parity
- historical credential exposure
- whether a commit was pushed
- deployment state

Those claims require Git metadata or production evidence.

---

# 9. Audit conclusion

The repository contains a large legacy and foundational backend.

The target MVP’s defining path remains incomplete:

> immutable proposal  
> → issue escrow  
> → source provenance  
> → asymmetric pricing  
> → atomic acceptance  
> → frontend interaction  
> → claim-safe settlement

The most consequential missing capabilities cluster in:

- Spec 1 service integration
- Spec 2
- the Simulation Engine

FR-8.7 is an exception to the project’s prior status language: its principal implementation is already present, while verification, migration, and deployment remain outstanding.

This audit should remain separate from Claude-owned planning documents. Planning documents may consume accepted corrections from it, but should not replace the evidence record.