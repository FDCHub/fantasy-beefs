# FantasyStakes — MVP Decision and Finding Index

**Status:** Governing index. Sanitized.
**Purpose:** Resolve every `FR-*` reference that appears in a retained MVP
specification, so the clean repository is self-contained.

This is **not** a findings register. It carries one governing ruling per item.
It carries no session chronology, no investigative evidence, no severity
history, and no security material. Security findings are held separately under
restricted access and are deliberately absent — their absence is not an
omission.

Where a retained specification already states a ruling in full, this index does
not restate it. It points at that specification. See §B.

**Ruling references in this index are document-qualified**, in the form
`<full document title> · <ruling identifier>`. Ruling numbering is
document-local; a bare "Ruling N" is not a citation. See §A5.

---

## A. Governing rulings — items with no other home

### A1 · Money path and accounting

**FR-COMM-1 — Direct money-balance mutation in the commissioner rules module**
Module 17 · **OPEN — audit scheduled, not a confirmed defect**
Ruling: direct money-balance mutations exist in `admin/commissioner_rules.py`
and are **unclassified** — it is not established which are authoritative writes,
which are deliberate compatibility mirrors, or whether any path can create
ledger/float divergence. Audit at transaction level before converting any site
to a ledger posting; converting first could remove a mirror something reads.
Governing spec: **none — this module has no spec denominator.**
Referenced by: no retained spec. **Directly replaceable: NO.**

**FR-8.7-LOG-5 — Feed payout headline diverges from the ledger**
Module 8 · **OPEN, money-path-adjacent**
Ruling: the feed computes a payout with the retired `amount × odds` formula
while authoritative settlement derives payout from actual escrow cents. For
asymmetric odds the feed states a payout the ledger never made. Fix by passing
the true payout through from settlement. No money moves either way; this is a
trust defect on a betting product.
Governing spec: `spec/SPEC_Finding_5_10_Matched_Bet_Payout_v3.md` retired the
formula. **Directly replaceable: PARTIAL** — 5_10 states the rule, not this
instance.

**FR-8.7-LOG-7 — Payout reported against unchanged balances**
Module 7 · **OPEN, uninvestigated**
Ruling: the settlement report's wallet-movement rows report a real payout while
before and after balances are identical, because both read a stored balance the
ledger-based path correctly never writes. Same family as LOG-5; LOG-5 computes
the payout wrong, LOG-7 sources the balances wrong.
Governing spec: none. **Directly replaceable: NO.**

**FR-8.7-LOG-4 — Post-commit settlement-report exposure**
Module 7 · **OPEN, not launch-blocking**
Ruling: after the economic commit, report building performs further session
work; a failure there raises after money is durable — the same misreport class
the feed-isolation fix removed, through a different door. Preferred fix: build
the report from values already in memory rather than wrapping the region.
Requires a transient database failure inside a narrow window.
Governing spec: none. **Directly replaceable: NO.**

**FR-5.6b-q11 — Initiator funding failure at acceptance**
Module 7 · **OPEN — acceptance-blocking, money-path**
Ruling: **current behavior has not yet been established.** The live code must be
inspected to determine whether an initiator funding failure at the moment of
acceptance can leave a partially posted, money-inventing, or money-losing state.
If that state is reachable, acceptance must fail **atomically**, with a governed
rollback or a no-post outcome. **No implementation change is authorized during
Phase 2A.**
Governing spec: `spec/SPEC_Finding_5_6b_Escrow_Close_v7.md`, which carries the
full governing context. This index does not restate it.
**Directly replaceable: PARTIAL** — the spec states the contract, this index
records the finding's status.

### A2 · Pools

**FR-POOL-1 — Empty evaluator result reported as distributed**
Module 5 · **OPEN, money-path**
Ruling: when an evaluator returns an empty result set the pot is never paid, yet
its share is still added to the reported distributed total. **The ledger remains
conserved** — nothing was posted — but every consuming surface states money moved
when it did not.
The governed settlement behavior is now stated at
`spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_3.md` §6.2. **That rule does not close
this finding.** §6.2's closing paragraph is an express carve-out: *"Reported
distribution arithmetic is not governed here. The `total_distributed_cents`
correction remains linked FR-POOL-1 work and is not absorbed into this rule."*
The reported-total defect, the stranded cents, and the reconciliation
interaction therefore remain this finding's own work.
Governing spec: `spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_3.md` §6.2.
**Directly replaceable: NO.**

**FR-POOL-2 — Empty evaluator result raises instead of failing closed**
Module 5 · **OPEN, money-path**
Ruling: an empty result set on the Special Teams branch raises a generic
`ValueError` with no domain message. Rollback prevents partial payout and the
ledger remains conserved, but an operator sees a stack trace rather than a
reason, and retry reproduces it.
The remedy is the census at `spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_3.md`
§6.2 — not a rule written inside one evaluator family. §6.2 classifies from an
authoritative subject census rather than from a bare result list, requires every
refusal to raise a **named domain error** carrying definition key, league, week,
classification and the census counts, and gives `INVARIANT_VIOLATION` a distinct
error type — a complete `RANK_EXTREMUM` field with zero claimants is an
evaluator fault, not a data condition, and is not resolved by waiting.
Implementation remains Stage H behind the Opus math review gate.
Governing spec: `spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_3.md` §6.2.
**Directly replaceable: NO.**

**Shared context for FR-POOL-1 and FR-POOL-2 — governed at POR §6.2**
> What is the governed settlement behavior when an evaluator returns an empty
> result set?

**The rule now exists.** `spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_3.md` §6.2
governs it: a bare empty result set never determines an outcome; classification
is computed from a subject census read from the authoritative weekly league
structure and never from the stat source; behavior follows the classification.

**An empty evaluator result is not equivalent to zero eligible claims.** §6.2
governs them as separate classifications — `NO_SUBJECTS`,
`NO_EVALUABLE_SUBJECTS` and `INCOMPLETE_FIELD` fail closed and never settle,
post, roll, sweep, or report completion, while `ZERO_ELIGIBLE_CLAIMS` is the
only zero-claim path into §6. Equating the two remains wrong.

Both findings remain **OPEN** for the work §6.2 does not do: FR-POOL-1's
reported-distribution arithmetic, expressly carved out, and FR-POOL-2's
implementation of the census and its named domain errors.

**FR-POOL-AUTH-1 — Pool build authorization**
Module 5 · **OPEN — blocking scope narrowed by ruling**
Ruling (owner, 2026-08-01) · `spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_3.md`
· Option B with a strict boundary: Pool product-definition work may proceed
ahead of Stage H **only** to author and validate catalog semantics and their
governed document representation.
*Authorized:* predicate, quantifier and threshold semantics; required
source-stat mappings; revision of POR, Scope and catalog JSON; pure read-only
invariant controls.
*Not authorized:* database columns or tables, ORM changes, migrations,
evaluator code, collection integration, settlement or rollover execution,
balance movement, production wiring, deployment.
Governing spec: `spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_3.md`, whose
status line reads **"Scope — not authorized for build."**
**Directly replaceable: PARTIAL** — the Scope states the status, this index
states the authorized/not-authorized split.

**FR-POOL-H15-1 — Trial-balance wording in the pool test program**
Module 19 · **OPEN, non-blocking**
Ruling: the harness section states every scenario asserts a zero trial balance,
including pure-evaluator scenarios that post nothing. Wording debt. Does not
invalidate existing tests.
Governing spec: **none — represented here.** The validation-programme document
this was drawn from is archived and does not enter the clean tree, so no path is
cited; this row is the governing statement.
**Directly replaceable: NO.**

**FR-POOL-H19-1 — Two unreachability claims conflated**
Module 5 · **OPEN, scoping precision**
Ruling: a test proving pool-scope unreachability proves nothing about the legacy
single-party path. "The Lineup" is retired from Pool scope while a live
single-party bet type settled outside it still exists. Keep the two claims
separate.
Governing spec: none. **Directly replaceable: NO.**

**FR-5.7 — Weekly roster-slot capture**
Modules 2, 5, 7 · **OWNER-APPROVED MVP CURRENT-BEHAVIOR BASELINE**
· invariants 1, 2, 3, 4, 6 DEMONSTRATED · invariant 5 PARTIALLY DEMONSTRATED
· **invariant 7 OPEN, acceptance-blocking, money-path**

This row records approved current behavior. It is a baseline, not a completed
contract: the dedicated specification and acceptance gate named below is where
the remaining obligations are discharged.

**Carried as governing baseline invariants — 1, 2, 3, 4, 6**

1. **Tuesday-flow participation — DEMONSTRATED.** The weekly roster-slot
   capture step participates in the Tuesday synchronization flow before
   settlement processing for that run.
2. **Week-specific authority precedence — DEMONSTRATED.** When complete
   week-specific `RosterSlot` rows exist for a team and week, downstream
   roster-authority reads use those captured rows in preference to current
   static `Roster` state.
3. **Same-week idempotency — DEMONSTRATED, with known implementation
   limitations.** Re-running capture for the same league and week does not
   create duplicate completed slot rows and may return an idempotent no-op for
   an already captured week. Known limitations, which belong to the dedicated
   specification and acceptance gate: the guard is keyed by league and week
   while some reads are keyed by team and week; a partially captured week is not
   fully governed by this baseline; the current count-then-write sequence is not
   established as transactionally atomic. **These limitations do not disprove
   the measured same-week no-duplicate behavior and must not be described as
   doing so.**
4. **Starter/bench preservation — DEMONSTRATED.** Captured roster-slot rows
   preserve the starter-versus-bench designation supplied by the weekly roster
   source rather than recomputing or flattening that status.
6. **Static-roster fallback on absence — DEMONSTRATED AS CURRENT BEHAVIOR.**
   When no applicable week-specific captured roster-slot rows are available, the
   current downstream path may use static `Roster` state as its fallback roster
   authority. This records measured current behavior only. **It does not
   authorize fallback after an attempted capture has failed** — see invariant 7.

**Recorded as measured supporting evidence, not as a binding invariant — 5**

5. **Yahoo-to-database team resolution — PARTIALLY DEMONSTRATED.** The
   implementation contains both fallback and prefetched Yahoo-to-database
   team-resolution paths, and may be cited as measured supporting evidence. It
   is **not** yet a complete binding baseline invariant, because focused tests
   remain missing for resolver failure and for active prefetched-path pairing
   behavior. Those tests are assigned to the dedicated specification and
   acceptance gate.

**OPEN acceptance-blocking defect — 7**

7. **Capture-failure settlement behavior — CURRENT IMPLEMENTATION
   NONCOMPLIANT.**

   *Approved MVP behavior.* Once week-specific roster-slot capture has been
   attempted and fails, settlement must not silently proceed for that week using
   static `Roster` state as a different roster authority. Capture failure is
   explicit; the affected week remains unresolved; settlement is blocked; payout
   is blocked; completion is blocked; settled presentation is blocked; a named
   domain failure or an equally explicit governed state identifies the reason;
   no silent change of roster basis is permitted; any commissioner recovery
   procedure requires separate specification and approval.

   *Measured current behavior — noncompliant.* The capture step can fail without
   writing incomplete slot rows; `run_tuesday_sync` records the failed step and
   continues; settlement may then use static `Roster` fallback.

   The gap between those two paragraphs is the defect. It is **OPEN and
   acceptance-blocking**. **No implementation change is authorized during
   Phase 2A.**

**Dedicated-spec gate:** **FR-5.7 Dedicated Roster-Slot Capture Specification
and Acceptance Gate.** It must cover at minimum: the seven invariants above;
resolver-failure tests; active prefetched-path pairing tests; partial-week
behavior; league/week versus team/week identity consistency; transactional
atomicity of capture; explicit capture-failure propagation; settlement blocking;
and a commissioner recovery procedure, if one is later approved.

Governing spec: **none — represented here**, pending the dedicated
specification named above.
**Directly replaceable: NO.**

### A3 · Testing and verification

**FR-8.7-TEST-1 — The shared fixture cannot discriminate the payout path**
Module 19 · **OPEN**
Ruling: the shared crash-suite fixture yields the same figure under both the
correct actual-escrow payout and the retired formula, so every assertion on that
figure is blind. The ledger is structurally safe — a three-leg posting must sum
to zero — but report and feed surfaces are not. Any regression test for LOG-5
must use a **discriminating** fixture where the two paths yield different values.
Governing spec: `spec/FR_8_7_TEST_6D_SPEC_FROZEN.md`.
**Directly replaceable: PARTIAL.**

**FR-8.7-TEST-2 — Vacuous-on-empty assertions**
Module 19 · **PARTIAL — fixed in one suite, unaudited in four**
Ruling: assertions of the form "token not in serialization" pass trivially
against an empty serialization. Guard with a hard precondition that the
serialization is non-empty, not with another assertion. Fixed in the stale-token
suite; the same class may exist in four sibling suites and has never been
checked.
Governing spec: `spec/FR_8_7_TEST_6D_SPEC_FROZEN.md`.
**Directly replaceable: PARTIAL.**

**FR-8.7-LOG-6 — Feed-path test coverage**
Module 19 · **OPEN, two named gaps**
Ruling: (1) The forced-failure scenario injects a Python-level error, which
exercises the handler but cannot poison a session because no database error
occurs; the real aborting error class is not exercised. Authorized as a
deliberate skip, recorded so it does not read as done. (2) Five other committing
feed functions have no test at all.
Governing spec: none. **Directly replaceable: NO.**

**FR-AC-ISO-1 — Requested isolation level is not taking effect**
Modules 7, 19 · **OPEN — confirmed twice, from two independent paths**
Ruling: an isolation level is requested after the connection is already
established and is therefore ignored. Any concurrency proof that assumes the
requested level proves something about a weaker level than it claims. Resolve
before freezing concurrency assertions.
Governing spec:
`spec/FR_VAL10_AF_ENGINE_CONTROL_SURFACE_MODULE_SPEC_Rev8.md` — carried forward;
it governs the single engine-construction point at which connection-time options
are applied. **Directly replaceable: PARTIAL.**

**FR-AF-ENC-1 — Non-ASCII characters crash standalone test output**
Module 19 · **OPEN, hygiene**
Ruling: non-cp1252 characters reaching `print()` crash standalone scripts under
the default Windows terminal. Comment-only occurrences are safe; a future edit
moving one into printed output reproduces the failure. Most suites are unscanned.
Governing spec:
`spec/FR_VAL10_AF_ENGINE_CONTROL_SURFACE_MODULE_SPEC_Rev8.md` — carried forward.
**Directly replaceable: PARTIAL.**

**FR-8.8 — Protocol compliance audit**
Module 19 · **NOT STARTED**
Ruling: a full money-path compliance sweep is required after settlement
verification and code review, before final launch sign-off. Not imminent, not
cancelled.
Governing spec: none. **Directly replaceable: NO.**

### A4 · BAB Top-Off and engine control surface

**FR-VAL10-af — Canonical engine control surface**
Module 18 · **SATISFIED — built and proven. Not deployed.**
Ruling: `db/engine_factory.py` is the **single governed engine-construction
point**. `get_engine()` is public; the SQLite foreign-key pragma is attached
per-engine to the pool connect event and never to PostgreSQL pools. Dialect-scoped
option policy: recognized other-dialect options are excluded silently, unknown
options raise at construction. All direct engine constructors are routed through
it, and an AST-based guard resolves import aliases to prevent bypass.
**A safety control was not weakened to make a gate pass** — a non-compliant
hosted test instance was abandoned rather than relaxing the harness host guard,
and when a control test failed the implementation was corrected, not the test.
Governing spec:
`spec/FR_VAL10_AF_ENGINE_CONTROL_SURFACE_MODULE_SPEC_Rev8.md`.
Control test: `tests/test_af1_engine_control_surface_red.py`.
**Directly replaceable: YES.**

**FR-VAL10-ac — Concurrency proof**
Module 19 · **UNBLOCKED, gated on FR-AC-ISO-1**
Ruling: concurrency assertions must prove locking through observed concurrent
outcomes, not through configuration claims. Do not freeze them until ISO-1 is
resolved.
Governing spec: `spec/VAL-10_MODULE_SPEC_Rev23_FROZEN.md`.
**Directly replaceable: PARTIAL.**

**FR-VAL10-ai–al — Remaining VAL-10 gates**
Module 6 · **NOT STARTED.** Prerequisite (foreign-key-enforced suite) satisfied.
Ruling: BAB Top-Off issuance governance is design-approved and frozen;
implementation authorization remains pending on these carried gates. Open gates
make the feature **incomplete, not post-MVP**.
Governing spec: `spec/VAL-10_MODULE_SPEC_Rev23_FROZEN.md`.
**Directly replaceable: PARTIAL.**

### A5 · Repository, deployment, and process

**Process finding — document-local ruling labels must be document-qualified**
Module 1 · **ADOPTED, binding going forward**
Two documents each carry a document-local **Ruling 1**, and the two are
unrelated:

| Document | Its `Ruling 1` | Supersession status |
|---|---|---|
| `FantasyBeefs_Foundation_Correction_Plan_2026-07-21.md` | Event identity topology — the generalized `ProtocolEvent` table is the single idempotency authority | Governing. It **superseded** a ledger-linkage option in `SPEC_2_Challenge_Escrow_v2.md` §7 |
| `spec/SPEC_Finding_5_6b_Escrow_Close_v7.md` | Round up, always | **Superseded by nothing** |

An earlier revision of this index conflated them, recording FR-5.6b as
*"Ruling 1 SUPERSEDED"* with the instruction *"do not cite the original
ruling."* That supersession belongs to a different document's Ruling 1 and was
never true of the escrow-close rounding rule. Both statements are withdrawn.

**Binding going forward: every ruling reference is document-qualified**, in the
form `<full document title> · <ruling identifier>`. A bare "Ruling N" is not a
citation, because ruling numbering is document-local and two documents may
legitimately each have a Ruling 1.
Governing spec: this index. **Directly replaceable: NO.**

**FR-REPO-CRLF-1 — Governed data files could be rewritten to CRLF**
Module 21 · **CLOSED**
Ruling: line-ending auto-conversion is enabled from system configuration. Any
file whose **byte identity is product authority** must be pinned to LF in
`.gitattributes`, or the next checkout, reset, stash, or branch switch silently
breaks its hash. Closed by pinning the governed catalog data files.
Governing spec: `.gitattributes` itself. **Directly replaceable: YES.**

**FR-REPO-CRLF-2 — The protector is itself unprotected**
Module 21 · **OPEN, not blocking**
Ruling: `.gitattributes` and repository-root Python remain subject to platform
line-ending conversion and are not themselves covered by a byte-level hash
requirement. Consistency and future-proofing, not an active authority failure.
Governing spec: `.gitattributes`. **Directly replaceable: PARTIAL.**

**FR-REPO-CRLF-3 — Governed stat vocabulary pinned**
Module 5 · **CLOSED**
Ruling: the canonical stat vocabulary is governed data whose byte identity is
product authority and is pinned to LF on checkout.
Governing spec: `.gitattributes`. **Directly replaceable: YES.**

**FR-DOC-DELTA-1 — Delta artifacts carry no absorption record**
Module 1 · **ADOPTED, severity LOW**
Ruling, **as amended and governing**: the destination document entry and its
commit history are the **durable authoritative absorption record**. A stamp on a
pending-change artifact is a convenience marker only; its absence is not evidence
that a change is pending, and its loss does not reverse absorption. Every
absorption must be recorded in the destination document with five fields —
artifact identity and path, destination section, absorbing commit, committer date
of that commit, and `ABSORBED — DO NOT REAPPLY`.
**A control that lives outside version control is not a control.**
Corollaries: committer date governs, not author date. A session label is not a
commit date; do not reconcile the two. A pending change must remain visible in
`git status` — any ignore rule that conceals one before absorption reproduces the
defect in a less detectable form.
Governing spec: this index. **Directly replaceable: NO.**

**FR-DOC-IGNORE-1 — Ignore rules must not conceal pending changes**
Module 21 · **ADOPTED**
Ruling: ignore entries for absorbed artifacts use **exact names, never a glob**,
so each future artifact is a deliberate decision and a pending one stays visible.
Governing spec: `.gitignore`, which carries the reasoning inline.
**Directly replaceable: YES.**

**FR-PROC-SWEEP-1 — Token sweeps find filenames, not meaning**
Module 21 · **OPEN, process**
Ruling: a revision sweep is not complete until it covers filename tokens, prose
revision references, every restated count, and every table column encoding the
changed property. **Token match is a starting point, never a completion
criterion.** Standing corollaries: every absence probe must carry a token that
must be present, or an empty result makes the probe vacuous; absence from a
filtered listing is not evidence — ask the authoritative source directly; bound a
structural slice at both edges by unique anchors and assert the expected match
count before reading a value; when an automated control replaces a hand-measured
quantity, re-derive every prior figure from the control.
Governing spec: this index. **Directly replaceable: NO.**

**FR-INFRA-3 — Health endpoint reports a value unrelated to the real binding**
Modules 10, 20 · **OPEN**
Ruling: the health route reports a hardcoded string with no relationship to the
actual database binding. It has already produced two false launch-blocking
findings. Report the real dialect only, masked — which also converts the binding
from inference into a publicly observable fact at zero production-access cost.
Governing spec: none. **Directly replaceable: NO.**

**FR-INFRA-4 — Engine import hung in the deployed container**
Module 20 · **OPEN, cause unknown**
Ruling: lazy engine construction should be instantaneous; an import blocked past
two minutes in a deployed container and was terminated. The image involved
predates the current engine control surface, so the hanging import is not the
current code. **Do not rely on production imports as diagnostics until resolved.**
Governing spec: none. **Directly replaceable: NO.**

**FR-DEPLOY-1 — Verified work is committed but not deployed**
Module 20 · **OPEN**
Ruling: controls proven by tests are **not** active production controls and must
not be described as such until deployed. This distinction is binding on any
status statement.
Governing spec: none. **Directly replaceable: NO.**

**FR-REPO-1a — Deployment excludes non-runtime material**
Module 20 · **RESOLVED**
Ruling: the deployment ignore file excludes documentation, specs, archives,
incoming drafts and scratch captures — using **specific patterns only**. It must
not exclude `*.txt` (that would exclude the dependency manifest and break the
build) or `*.html` (that would exclude the served UI). Verified: neither is
matched.
Governing spec: `.railwayignore`, which carries the reasoning inline.
**Directly replaceable: YES.**

---

## B. Items governed by a retained specification

For these, cite the specification. This index adds nothing.

| Reference | Cite instead |
|---|---|
| FR-8.7 | `spec/SPEC_FR_8_7_Settlement_ClaimFirst_v5.md` |
| FR-8.7-LOG-1 | `spec/FR_8_7_LOG_1_FEED_ISOLATION_MODULE_SPEC_FINAL.md` |
| FR-5.6b | `spec/SPEC_Finding_5_6b_Escrow_Close_v7.md` |
| FR-5.8 | `spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_3.md` — §1.1 Retired, and §11 conformance item 5 |
| FR-5.9 | `spec/SPEC_Finding_5_9_Settlement_Escrow_Gap_v4.md` |
| FR-5.10 | `spec/SPEC_Finding_5_10_Matched_Bet_Payout_v3.md` |
| FR-6.1 | `spec/FR-6.1_CATALOG_CLASSIFICATION.md` |
| FR-7.12 | `spec/SPEC_FR_7_12_Wallet_Balance_Ledger_v5_final.md` |
| FR-7.29 | `spec/SPEC_FR_7_29_Roster_Refresh_v1.md` |
| FR-7.30 | `spec/SPEC_FR_7_30_Players_Table_Growth_v1.md` |
| FR-7.50 | `spec/FR_7_50_STAKE_INPUT_VALIDATION_MODULE_SPEC_Rev7.md` |

**FR-5.7 is not in this table.** It carries a governing row at §A2 and is not
governed by a retained specification.

---

## C. Retired references

These appear in retained specifications but are closed, withdrawn, or folded
into a current governing document. **Cite the governing document, not the
identifier.**

FR-POOL-ROLL-1 · FR-POOL-POR-1 · FR-POOL-POR-2 · FR-POOL-SCOPE-1 ·
FR-POOL-SCOPE-2 · FR-POOL-TITLE-1 — all absorbed into the Pool Product of Record.

FR-8.7-LOG-2 · FR-8.7-LOG-3 — superseded by the shipped feed-isolation
specification and by the LOG-4/5/6 family.

FR-5.13 · FR-8.5 · FR-8.6 · FR-6.3 · FR-DEPLOY-IGN-1 — closed or never adopted.

FR-INFRA-1 · FR-INFRA-2 · FR-POOL-DEP-1 · FR-POOL-PTR-1 — **withdrawn as
incorrect.** Do not reintroduce.

---

## D. Deliberate omissions

Security findings are held separately under restricted access and are **not**
represented here in any form — not by identifier, status, or cross-reference.
Their absence is deliberate and is not an inventory gap.

Two operational facts belong in the runbook rather than in a finding, and are
stated once here because retained code depends on them:

- The PostgreSQL integration suites run against a **local container on port 5433
  only**. The harness forbids hosted database endpoints outright, at any database
  name, and its guards raise rather than skip.
- Ingestion currently depends on an existing long-lived credential. Re-issuing
  one requires an external application-setting change that is not currently
  authorized. Local refactoring may proceed without it.
