# Fantasy Beefs — Plan

**Version:** 1.0
**Established:** 2026-07-23
**Changes only by explicit ruling.** When it changes, the Findings Register records why.

**What this document is.** The arc from here to a GM placing a correctly priced bet, and the gates along the way. It holds what should be stable between sessions.

**What this document is not.** It carries no status table, no percentages, and no "what is true today." Current state lives in the Package and is regenerated every session. This separation is deliberate: two documents claiming current state is what produced the Master Plan v8 reconciliation conflicts.

**Supersedes** `FantasyBeefs_MasterPlan_v8_LaunchPath.md` for all planning purposes. v8 is retained as history only.

---

## 1. Milestones

| Milestone | Date | Meaning |
|---|---|---|
| **Platform launch** | **August 1, 2026** | League setup and the draft window. **Not betting.** |
| **Betting activation** | **NFL Week 1, September** | Requires the complete path to a GM placing a correctly priced bet, verified. |

**August 1 must never be described as "betting live."** Any document that does is stale and must be corrected before further schedule decisions.

**Reasoning of record.** August 1 is the draft window, not the first scoring week. No real money moves until September. Recognizing that bought roughly five weeks without cutting anything. Holding August 1 as the wagering date would have forced scope cuts under time pressure; shipping versus wagering with symmetric stakes because the odds engine is unported was considered and rejected as a money-path defect.

**No temporary symmetric-stake fallback is authorized.** Not for launch pressure, not for demonstration, not for testing against real GMs.

---

## 2. Build path

```
Security remediation
  → FR-8.7 closure
  → controlled foundation deployment
  → FR-AC-ISO-1 gate
  → Spec 2
  → Spec 3A
  → Spec 3B
  → Spec 5
  → Spec 4
```

**The five-spec internal order is unchanged: 1 → 2 → 3 → 5 → 4.** What the path above adds is prerequisites and one implementation decomposition. Spec 1 is complete as a stage and does not appear.

**FR-AC-ISO-1 is a gate, not a build stage.** It is an entry condition on Spec 2.

**Spec 3A/3B is an implementation decomposition, not a scope reduction.** Full Spec 3 remains required before betting activation.

---

## 3. Stages

### 3.1 — Security remediation

**Delivers:** a production environment where credentials are rotated, exposure is closed, and deployment is safe to attempt.

| Item | Content |
|---|---|
| FR-SEC-DB-2 | Classify `reseau.proxy.rlwy.net:54032`. Credential-free TCP reachability check first. Any authenticated identity probe requires a separate ruling. |
| FR-SEC-DB-1 | Steps 8–11 of the rotation sequence: disable public networking, rotate, verify role authentication **and** propagated service variables before restarting dependents. Steps 1–7 are complete and do not repeat. |
| Git history | Deferred. Gated on the FR-SEC-DB-2 outcome. `git filter-repo` is not authorized. |
| Ambient variable | Unset the production `DATABASE_URL` in the Claude Code CLI shell and leave it unset. Not repointed. |

**Gate:** production credentials rotated and verified; no known live exposed credential; a rollback procedure exists.

**Why first:** every later migration and deployment inherits this state. Accumulating undeployed schema and money-path changes on top of an unresolved credential exposure increases the eventual blast radius.

### 3.2 — FR-8.7 closure

**Delivers:** claim-first settlement with proven crash recovery, deployed and production-confirmed.

**Status correction that produced this stage.** The principal service surface is present in tracked source — `settle_week(..., recovery_token=None)`, `recover_week(...)`, `CLAIMED`/`COMPLETED` lifecycle handling, row-locking queries, recovery-token validation, atomic completion updates, plus `WeekSettlement.status`, `WeekSettlement.recovery_token`, and the migrations. The register previously carried this as "PARTIAL," which undersold it.

**Correct status:** *implementation present; verification, migration, and deployment outstanding.*

**Outstanding:** tests 6c and 6d; settled-reader grep; review package; final review; migration execution; deployment and production confirmation.

**Gate:** all six complete. Production-confirmed.

**Why before Spec 2:** the remaining scope is bounded, it governs settlement safety, and Spec 2 adds settlement-relevant escrow complexity. Unresolved claim-first behavior becomes harder to reason about once more money paths sit on top of it.

**Open assumption.** "Zero service functions absent" does not prove the implementation satisfies the entire frozen spec. The outstanding six are what close it.

### 3.3 — Controlled foundation deployment

**Delivers:** af-1, af-2, Spec 1 schema, and FR-8.7 running in production.

| Carries | Effect |
|---|---|
| af-1 engine control surface (`0f4a04d`) | First production run of the engine factory |
| af-2 FK-enforced suite (`c961e2a`) | — |
| Spec 1 proposal lifecycle (`dd6d363`) | Migration execution requires **separate authorization** |
| FR-INFRA-3 fix | `/health.db_path` reports the real dialect, masked |
| FR-INFRA-4 diagnosis | The window to investigate the deployed import hang |

**Gate:** deployment succeeds, health-checked green in the Deployments tab — not "Online." FR-INFRA-4 diagnosed or explicitly deferred with reasoning.

**Note.** This changes infrastructure behavior before it enables new product flow. Deploying Spec 1's schema does not make the proposal lifecycle reachable — Spec 2 does that. The value is that Spec 2 gets built and tested against the schema and engine behavior production actually runs.

**The verified backup is the rollback point.** `fantasy_beefs_prod_2026-07-23_UTC.dump.gpg`, pre-Spec-1 baseline.

### 3.4 — FR-AC-ISO-1 gate

**Not a build stage. An entry condition on Spec 2.**

Spec 2's atomic acceptance depends on deterministic wallet-row locking. A warning at `beef_engine.py:877` reports that an isolation level was ignored because the connection was already established. **Configuration intent is not evidence.**

**Four criteria. All four required:**

1. The actual PostgreSQL transaction isolation level used by the relevant application transaction.
2. `SELECT ... FOR UPDATE` serializes conflicting acceptance paths as intended.
3. Two concurrent attempts yield exactly one valid economic result — no duplicate posting, no partial posting.
4. The proof uses the same engine, session, and transaction-construction pattern Spec 2 will use.

**A configuration setting or intended isolation level does not satisfy this gate. Observed concurrent outcomes do.**

This may not require completing every remaining FR-VAL10-ac item. The isolation and concurrency proof comes first.

### 3.5 — Spec 2: Challenge Escrow & Atomic Acceptance

**Delivers:** the point at which the proposal model becomes economically real. Without it, Spec 1's schema is unreachable structure.

**Scope:** real issuer Anchor escrow at issue (`escrow:challenge:{id}`) drawn min-first-then-wallet; ownership of the `min:{team}:{week}` account contract; ordered funding-leg provenance with explicit `reverses_funding_leg_id` linkage; strict reverse-order refunds; asymmetric Anchor/Derived placement; atomic Locked acceptance with issuer true-up; fail-closed `expire_challenge`; protocol-event and audit layer; deterministic Wallet-row locking.

**Covers findings** A1, A4, A5-money, A6, A7-capacity, A8.

**Hard money-path Opus gate.** Not yet reviewed.

**Pre-build recons pending:** `post()` caller inventory; Wallet-row lock-order conflict check.

**Ledger prerequisite.** Spec 2 requires two things `ledger/ledger.py` does not currently expose: externally supplied protocol-event or idempotency identity on `post()`, and a native source-funding-leg provenance and reversal API. The current surface is `post(entries, door, session)`.

**Gate:** Opus-reviewed, each finding approved individually, built, tested, deployed.

**Open assumption.** Nine absent operations are protocol capabilities, not necessarily nine callable functions. One transaction service may own several.

### 3.6 — Spec 3A: Pricing kernel

**Delivers:** correctly priced Locked proposals, and a frontend contract that can freeze.

**Scope:** `o2p`, `p2o`, `derive_stakes`, immutable pricing result types, adversarial math tests, pricing provenance contract.

**Boundary reasoning.** Spec Rev 7 separates mode-agnostic pricing functions from lifecycle orchestration, and states the caller decides whether `adjust_escrow` runs — Locked never calls it, Dynamic calls it exactly once. `adjust_escrow` is part of the certified Flexible Stake and Return mechanism, but it is the Dynamic Final-Lock half. It is not needed to price or accept a Locked Challenge.

**Canonical source.** The mechanic is implemented and certified in JavaScript in the Odds Calculator, Rev 1.9, Tab 5. The Python port does not exist. `odds_engine.py` is not built.

**Gate:** pricing functions produce results matching the certified JS calculator on adversarial cases, including non-50/50 odds and rounding boundaries.

**Open assumption.** The nine absent Simulation Engine items mix pure functions with durable services and recovery workflows. They are not nine equivalent implementation units. This stage takes the pure functions only.

### 3.7 — Spec 3B: Dynamic Handshake & Final Lock

**Delivers:** the Dynamic wager mode, end to end.

**Scope:** Handshake funding and ceilings; model and projection version identities; model freeze; informational refresh; `adjust_escrow`; Final-Lock timestamp and trigger; official simulation record; Adjustment and refunds; claim-first Final-Lock execution; recovery and final-term freeze.

**Entirely greenfield.** Recon confirmed none of this exists.

**Reuses** Spec 2's funding, provenance, event, and locking primitives.

**Gate:** own Opus review, own phased build plan.

**3A and 3B together constitute Spec 3. Both are required before betting activation.**

### 3.8 — Frontend

**May begin in parallel, after two contracts freeze:**

- Spec 2's proposal and escrow API shape
- Spec 3A's pricing payload

**Build against explicit fixtures:** Locked offer, counter, acceptance, asymmetric Anchor/Derived stakes, funded-pot and payout display.

**Do not freeze Dynamic-specific cards or Adjustment states until 3B's contract settles.**

**Caution.** The locked response card designs were written to work under either symmetric or asymmetric stakes, because pricing was unsettled when they were designed. Freezing the frontend contract before pricing freezes reintroduces that ambiguity — which is why 3A precedes frontend work rather than running alongside it.

**Current state:** `tools/app.html` makes zero calls to `/beef/challenge` or `/beef/respond`. The backend routes exist; the primary UI does not call them.

**Activation stays blocked** until the full money path is verified, regardless of frontend readiness.

### 3.9 — Spec 5: League Economy Config & Account Identity

**Delivers:** canonical account identity, before anything routes money to those accounts.

**Scope:** B5 (fee bound 100–500¢, default 100, confirm at init, freeze at first accepted wager); B6 (season-fixed config guard — economy stop and fee freeze at first accepted wager, unspent-min destination locked at kickoff, no amendment after an accepted wager references terms); B7 (canonicalize `championship:{league_id}` — the tree currently posts to both bare and scoped strings, breaking league isolation). Owns the `min:{team}:{week}` lifecycle whose contract Spec 2 defines.

**Why before Spec 4:** pool remainders route to Championship. That destination must be correct first.

### 3.10 — Spec 4: Pool Catalog & Settlement

**Delivers:** the five-bet pool catalog, correctly settled.

**Scope:** B1 (Bench Burn evaluator — FR-5.7 RosterSlot capture is built, the evaluator is absent); B2 (remove Worst Beat — still funded in code despite protocol retirement); B3 (dynamic n-way allocation with remainder to `championship:{league_id}`, replacing hardcoded `// 3`); B4 (The Lineup as a 12-GM Rank Pool — the legacy single-party `the_lineup` Bet is not equivalent).

**Open product ruling:** The Lineup tie behavior.

**Last in build order.**

---

## 4. Betting activation gate

**All of the following, verified:**

1. Security remediation complete
2. FR-8.7 closed and production-confirmed
3. Foundation deployed
4. FR-AC-ISO-1 gate passed
5. Spec 2 shipped and deployed
6. Spec 3A and 3B shipped and deployed
7. Frontend wired to the full challenge path
8. GM walkthrough completed successfully

**Specs 5 and 4 are not activation gates for versus wagering.** They gate pool bets and season-end reconciliation. Whether pool bets open at Week 1 alongside versus, or later, is unruled.

---

## 5. Assumptions open to challenge

**These are load-bearing premises, not decisions. The reviewer's standing instruction is to challenge any of them where evidence supports it, and to state explicitly when evidence does not.**

| # | Assumption | Reasoning that produced it |
|---|---|---|
| 1 | Five specs is the right decomposition | Emerged from decomposing fifteen ruled findings (A1–A9, B1–B7). Never independently tested. Spec 2 carries nine operations — whether that should be one spec is unexamined. |
| 2 | Week 1 betting activation is achievable | Rests on the stage estimates above. Roughly 25 high-authority operations are absent across Spec 1 services, Spec 2, and the Simulation Engine, and the frontend makes zero core calls. Nobody has tested the estimate against that. |
| 3 | The build order's dependencies are real | Some are structural — Spec 1 before Spec 2, Spec 5 before Spec 4. Others may be convention. Which is which is not documented. |
| 4 | FR-SEC-DB-2's next step is a TCP check | Cheap and decisive in one direction. Railway support may be faster and more definitive. Not compared. |
| 5 | The matched-bet architecture ruling still holds | Every versus bet is a matched GM-vs-GM pair. Ruled July 2026; single-party code parked, not deleted. Not revisited since. |
| 6 | Module completion percentages are not computable | Denominators shift as scope changes. Counts and named gaps were adopted instead. This may be too conservative. |
| 7 | FR-8.7 completeness | The principal service surface is present, but that does not prove the implementation satisfies the entire frozen spec. Tests 6c/6d, settled-reader coverage, migrations, and final review remain open. |
| 8 | Spec 1 service denominator | Seven absent lifecycle operations is a reasonable functional decomposition, not necessarily seven separately required production functions. |
| 9 | Spec 2 denominator | Nine absent operations are high-confidence protocol capabilities, not necessarily nine callables. |
| 10 | Simulation Engine denominator | Nine absent items mix pure functions with durable services and recovery workflows. Not nine equivalent units. |
| 11 | "Everything else is broadly present" | Too strong unqualified. Correct form: *most supporting subsystems have substantial existing code, but several remain nonconforming or operationally unverified* — direct float mutations, legacy single-party routes, pool catalog mismatch, frontend absence, frozen-lineup scoring absence, deployment lag. |
| 12 | DB runtime "0 absent" | Means no missing callable against the engine-control spec. Does not close FR-INFRA-3, FR-INFRA-4, deployment, or production-observability gaps. |

---

## 6. Standing constraints

**Money-path work is Opus-gated.** Issues only, four-part format — Name / Issue Summary / Options / Recommendation & Reasoning. Each finding approved individually before any fix is built.

**Propose before building.** No code, commits, migrations, or `railway up` without explicit authorization.

**Existence-check, extended to diagnosis.** Grep before referencing a named file or function as confirmed to exist. Before treating any observed value as evidence of system state, verify what produces it.

**Verification claims must match the command that ran.** A table of contents proves an archive is readable. Only a restore proves it restores.

**Command instructions name the machine and the shell.** Where behavior depends on the shell — interactive prompts, path translation, environment persistence — say which shell and why.

**Ledger discipline.** Read actual escrow balances; never recompute from stake amounts. `session=db` for all ledger calls inside existing transactions. All postings sum to zero. Integer cents end to end.
