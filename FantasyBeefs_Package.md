# Fantasy Beefs — Transition Package

**Cycle:** 2026-07-23 → next
**Read by:** Claude (architect) and ChatGPT (independent reviewer). One file, both threads.

---

## How to read this file

**Claude:** read straight through. You own the plan; the gate does not apply to you.

**ChatGPT:** read Parts A, B, and D. Form and state your own sequencing view. **Then** read Part C.

Part C contains the build order and next actions. Reading it first will anchor you — you will find the reasoning sound, agree, and produce nothing. Your value is the view you form before you see ours.

**Part E is your standing brief.** Read it first, every cycle.

---

# PART A — Verified state

Everything here is labeled. **Verified** means observed this cycle by direct command output. **Reported** means stated by a prior session without re-verification. **Inferred** means concluded from evidence, not observed.

## A.1 — Repository

| Fact | Status |
|---|---|
| Branch `remediation/foundation-phase-1` | **Verified** |
| HEAD `9ff096b`, local and remote in sync | **Verified** — `git status -sb` no ahead/behind marker; `git log origin/..HEAD` empty |
| `c353d2b` — security fix, pushed | **Verified** |
| `9ff096b` — register v14 tracked, pushed | **Verified** |
| Nothing deployed this cycle or the two prior | **Verified** — no `railway up` issued |
| No migration executed | **Verified** |
| No credential rotated | **Verified** |

## A.2 — Production infrastructure

| Fact | Status |
|---|---|
| Production Postgres is **18.x** | **Verified** — Settings tab offers upgrade to 18.4 |
| Public endpoint `hayabusa.proxy.rlwy.net:15707` → 5432 | **Verified** |
| **Public networking is ENABLED** | **Verified** |
| Private endpoint `postgres.railway.internal` live, IPv4 and IPv6 | **Verified** |
| **Railway backups and PITR are Pro-plan only — unavailable** | **Verified** — Backups tab |
| Second service `postgres-test` Online, own volume, **purpose unaudited** | **Verified** it exists; purpose unknown |
| `pg-fantasy-test` container running, `postgres:16`, port 5433 | **Verified** — reserved for FR-VAL10-ac |
| Deployed image predates `0f4a04d` | **Reported** |

**Do not click "Upgrade to 18.4."** A version bump on a production database mid-remediation is the wrong order.

**Do not stop or remove `pg-fantasy-test`.**

## A.3 — Backup — first verified restore point in project history

| Property | Value |
|---|---|
| Path | `C:\FantasyBeefs_Backups\` |
| File | `fantasy_beefs_prod_2026-07-23_UTC.dump.gpg` |
| Size | 116,928 bytes encrypted (243,863 plaintext) |
| Created | 2026-07-23 22:29:32 UTC |
| Format | `pg_dump` custom, gzip, `--no-owner --no-privileges` |
| Encryption | GnuPG symmetric AES-256, **decryption verified exit 0** |
| Restore proof | **`pg_restore` into disposable `postgres:18`, exit 0, 40 tables, FKs restored, row counts confirmed from the restored copy** |
| Schema baseline | **Pre-Spec-1.** No `beef_proposals` / `beef_proposal_starters`. |
| Passphrase | Held by Fraser, stored separately. **Not recoverable if lost.** |

**All verified.** A table of contents proves an archive is readable; the restore drill proves it restores. Both were run.

**Row counts from the restored copy:** `player_id_map` 4,777 · `projections` 2,407 · `nfl_schedule` 272 · `rosters` 180 · `players` 180 · `matchups` 98 · `teams`/`wallets`/`faab_wallets` 12 each · `leagues`/`faab_config`/`league_scoring` 1 each.

**Every money-path table is empty.** `bets`, `ledger_entries`, `transactions`, `escrow_accounts`, `escrow_transactions`, `beef_challenges`, `beef_starters`, `users`, all `pool_*`. **FR-5.13's invariant is now verified from a restored copy, not asserted.**

**Repository archive** for review: `C:\FantasyBeefs_Backups\fantasy-beefs_9ff096b.zip` — 269 entries, `git archive` at `9ff096b`, filter for `secrets/`, `.env`, `.db`, `.dump`, `.gpg` returned nothing.

## A.4 — Security findings

**FR-SEC-DB-1 — rotation PAUSED at step 8 of 11.**

Steps 1–7 complete and non-repeating: Railway backups confirmed unavailable; dump created (exit 0); TOC verified (399 entries); restore drilled; encrypted and decrypt-verified; plaintext removed; dependents inventoried.

Steps 8–11 gated on FR-SEC-DB-2. Rotating `hayabusa` while `reseau` is unclassified closes half a problem.

Railway's Regenerate control has a documented desync class — env variables update while the role password does not, with outcomes from twelve hours of downtime to full production lockout. **If desync occurs, stop and assess.** Trust-mode `pg_hba.conf` recovery requires its own reviewed procedure.

**FR-SEC-DB-2 — OPEN.**

Three tracked, pushed files hardcoded a full production connection string as a fallback default: `seed_player_id_map.py:34`, `scripts/backfill_nfl_teams.py:33`, `scripts/resolve_player_nfl_teams.py:28`. Host `reseau.proxy.rlwy.net`, port `54032`.

**Source fixed and pushed** (`c353d2b`) — fail-closed `DATABASE_URL` reads, no fallback, error text never naming a URL. `.gitignore` gained `.env`, `.env.*`, `!.env.example`.

**Credential remains in pushed history** at `b1bd1b8` and `480ede2`. It also passed through a session transcript when an edit tool printed the removed diff lines. **Treat as fully exposed.**

Classification, from three credential-free checks:

| Check | Result | Establishes |
|---|---|---|
| Current production host | `hayabusa` true, `reseau` false | `reseau` is not the current endpoint |
| History introduction | `b1bd1b8`, `480ede2` — pushed | Credential is on GitHub |
| DNS | Resolves, A record `66.33.22.224` | Proxy infrastructure exists. **Nothing about identity.** |

**Wording note.** `hayabusa:15707` and `reseau:54032` are **two distinct network addresses; database and service identity is unresolved.** Earlier documents said "two distinct endpoints," which overstated it.

**A rejected inference, recorded because the reasoning matters.** A password mismatch against a live variable does not prove rotation or revocation, particularly when hostnames differ. That inference was raised three times last cycle and rejected each time. **The credential is unclassified, not dead.**

**Git history treatment deferred.** `git filter-repo` not authorized.

**FR-SEC-DB-3 — REMEDIATED, qualified.**

A GnuPG verification used `--output NUL`. On Windows that is a filename, not the null device — a 243,863-byte plaintext copy of the production database landed at the repo root inside OneDrive. Untracked, never committed. `Remove-Item` reported no error and left it in place; `cmd /c del` with the `\\?\` prefix removed it, absence verified. OneDrive live files and primary recycle bin both clean; no second-stage bin in this account view.

**Recorded as "no synced copy found," not as proof it never uploaded.**

## A.5 — Status corrections adopted this cycle

Six corrections, each because a document contradicted its own evidence.

| Item | Was | Now |
|---|---|---|
| **FR-8.7** | "PARTIAL — implemented, validated to 6b" | **Implementation present; verification, migration, and deployment outstanding.** Principal service surface is in tracked source. |
| **Spec 1** | "SHIPPED" | **Implemented, tested, and committed; migration and deployment pending.** "Shipped" implies it reached its operating environment. It has not. |
| **Backend** | "Built, tested, deployed-pending" | **Legacy engines and infrastructure present; target proposal, escrow, pricing, Dynamic, and frontend path incomplete.** |
| **Auth** | "No UI, token hardcoded `'dev-stub-token'`" | **Backend authentication and authorization present** (12 callables). **Frontend login absent or development-stubbed.** Two separate facts. |
| **Endpoints** | "two distinct endpoints" | **Two distinct network addresses; database and service identity unresolved.** |
| **FR-5.7** | Listed as a gap | **`roster_slots` exists in production and carries rows.** Migration is live. |

---

# PART B — Module inventory

**Source:** independent ChatGPT repository audit at HEAD `9ff096b`. **Not reproduced or independently verified by Claude.** Full evidence in `INDEPENDENT_CODE_SPEC_AUDIT_9ff096b.md`.

**Counting method.** Public top-level functions and public class methods in runtime modules. Excludes names beginning with `_`, model classes with no methods, tests, migration entry scripts, one-off seed scripts, and Pydantic request/response classes.

**Reading the "Absent" column.** Exact numbers where the spec defines a closed denominator. `≥` where only a lower bound exists. "Unavailable" where the specs define behavior without separable operations.

| Module | Present | Absent | Denominator confidence |
|---|---|---|---|
| API surface | 90 routes | 6 — proposal issue/counter/accept/revive, refresh, Final-Lock status | Medium |
| Auth (backend) | 12 | 0 at function level | Medium |
| Challenge engine | 4 | 7 — full proposal lifecycle, unconnected to Spec 1 schema | **High** |
| Challenge escrow (Spec 2) | **0** | 9 — issue escrow, provenance, refunds, atomic accept | **High** |
| Legacy bets | 5 | Unavailable. Routes still live. | — |
| Pool engine | 8 | 4 — Bench Burn, n-way payout, Lineup rank pool, Worst Beat removal | Low–med |
| Settlement / FR-8.7 | 2 + lifecycle code | **0 service functions.** Verification outstanding. | **High** |
| Ledger | 4 | 2 — event identity on `post()`, funding-leg provenance | **High** |
| Wallet / FAAB | 20 | ≥3 — min-first funding, reverse-order refund, ledger-exclusive deposit | Insufficient |
| Odds / simulation | 7 | 9 — `o2p`, `p2o`, `derive_stakes`, `adjust_escrow`, Handshake, Final Lock | **High** |
| Data providers | 20 | Unavailable | Low (operational) |
| Decision engine | 9 | ≥1 — beef frozen-lineup scoring | Low |
| Tuesday sync | 5 | ≥1 — Final-Lock trigger integration | Medium |
| Payments / economy | 18 | ≥3 — config freeze, championship scoping, min lifecycle | Low–med |
| Commissioner rules | 12 | Unavailable. **Open finding: direct float mutation.** | — |
| Reports / feed | 20 | ≥3 — proposal-aware events, Final-Lock events, frozen-lineup display | Low |
| DB runtime | 5 | 0 against the engine-control spec | **High** |
| Frontend | **0 core calls** | 2 immediate — issue, respond | — |

**Total public runtime callables: 243** across 17 subsystem groups.

**The shape.** 243 callables surround a missing chain of roughly 25 high-authority operations. **`~25` is a summary estimate, not an audited total.** The gaps cluster in three places: Spec 1's services, Spec 2 entire, and the Simulation Engine.

**Not a completion percentage.** The modules differ enormously in risk and complexity.

## B.1 — Findings from the audit

**Spec 1's schema exists but is disconnected.** `beefs/beef_engine.py` references none of `BeefProposal`, `BeefProposalStarter`, `active_proposal_id`, `accepted_proposal_id`, `challenge_mode`, `response_status`, or the new `wager_type`. The old and new challenge models run in parallel with no feature-gate boundary between them.

**Direct float mutation persists in three modules.** `wallet/wallet_manager.py` deposit, `admin/commissioner_rules.py` several sites, `betting/settlement_engine.py` payout mirrors.

> **Open finding — commissioner rules.** Direct money-balance mutations exist in `admin/commissioner_rules.py`. Their classification as approved compatibility mirrors or unauthorized ledger bypasses is **unresolved**. A transaction-level caller and posting audit is required. Verified: the mutations exist. Not verified: which are authoritative writes, which are deliberate mirrors, whether paired ledger entries occur elsewhere in the same transaction, or whether any path can create ledger/float divergence.

**No `simulation_engine.py` exists.** The Monte Carlo engine is present; the specified Simulation Engine surface is not.

**The frontend makes zero core challenge calls.** Backend routes exist. `tools/app.html` does not call them.

---

# PART C — Plan and next actions

**ChatGPT: do not read this section until you have stated your own sequencing view.**

## C.1 — Build order

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

Five-spec internal order unchanged: **1 → 2 → 3 → 5 → 4.** The path adds prerequisites and one implementation decomposition.

**FR-AC-ISO-1 is a gate, not a build stage.** Entry condition on Spec 2.

**Spec 3A/3B is implementation decomposition only.** Full Spec 3 remains required before betting activation.

Full stage definitions, gates, and reasoning: `FantasyBeefs_Plan.md`.

## C.2 — Next action

**One credential-free TCP reachability check on `reseau.proxy.rlwy.net:54032`.**

Decisive in one direction: a closed port ends the FR-SEC-DB-2 investigation. If open, an authenticated read-only identity probe requires a **separate ruling** — reachability does not establish identity.

Everything else waits on it. FR-SEC-DB-1's steps 8–11 are gated on this classification.

## C.3 — Then, in order

| # | Action | Gate |
|---|---|---|
| 1 | FR-SEC-DB-1 steps 8–11 — disable public networking, rotate, verify role auth **and** variable propagation | Credentials rotated, no known live exposure, rollback exists |
| 2 | FR-8.7 closure — tests 6c/6d, settled-reader grep, review package, final review, migration, deployment | Production-confirmed |
| 3 | Controlled foundation deployment — af-1, af-2, Spec 1 schema, FR-INFRA-3 fix, FR-INFRA-4 diagnosis | Green "Success" in Deployments tab, not "Online" |
| 4 | FR-AC-ISO-1 gate — four criteria, all required | Observed concurrent outcomes, not configuration claims |
| 5 | Spec 2 — Opus review first | Each finding approved individually |

## C.4 — Milestones

| Milestone | Date | Meaning |
|---|---|---|
| Platform launch | **August 1, 2026** | League setup, draft window. **Not betting.** |
| Betting activation | **NFL Week 1, September** | Full verified path to a correctly priced bet |

**No symmetric-stake fallback is authorized.**

---

# PART D — Open items and constraints

## D.1 — Open findings

| ID | Status | Next |
|---|---|---|
| **FR-SEC-DB-2** | Open | TCP check on `reseau:54032` |
| **FR-SEC-DB-1** | Paused at step 8/11 | Resume after DB-2 classification |
| Git history remediation | Deferred | Gated on DB-2. `filter-repo` not authorized. |
| **Commissioner-rules float mutation** | **Open, new** | Transaction-level caller and posting audit |
| FR-DEPLOY-1 | Open | Four commits running nowhere |
| FR-INFRA-3 | Open | `/health.db_path` hardcoded, misleading. Rides the next deployment. |
| FR-INFRA-4 | Open | Deployed `db.schema` import hung >120s. Cause unknown. |
| FR-AC-ISO-1 | Open | Promoted to Spec 2 entry gate |
| FR-8.7 | Implementation present | Six outstanding items |
| Spec 1 migration | Written, unexecuted | Separate authorization required |
| `postgres-test` service | Unaudited | Running and billing |
| Spec 2 | Opus-ready, unreviewed | Money-path gate |

## D.2 — Do not do these

- **Do not click "Upgrade to 18.4."**
- **Do not stop or remove `pg-fantasy-test`.**
- **Do not describe August 1 as "betting live."**
- **Do not describe FK enforcement as an active production control.** Live in the code path, proven by tests; the deployed image predates it.
- **Do not run `git filter-repo`.**
- **Do not use the embedded `reseau` credential** without a separate ruling.
- **Do not treat the `reseau` credential as dead.**

## D.3 — Process constraints

**Propose before building.** No code, commits, migrations, or `railway up` without explicit authorization.

**Money-path work is Opus-gated.** Issues only, four-part format. Each finding approved individually.

**Existence-check, extended to diagnosis.** Grep before referencing a named file or function as confirmed to exist. Before treating any observed value as evidence of system state, verify what produces it.

**Verification claims must match the command that ran.** A TOC proves an archive is readable. Only a restore proves it restores.

**Command instructions name the machine and the shell.** Three failures last cycle came from commands written for one shell and pasted into another: `Read-Host` in a non-interactive shell, `--output NUL` as a Unix idiom on Windows, container paths through MSYS. Claude Code's shell is non-interactive and does not persist environment variables between tool calls.

**Status-sweep, extended to dependency language.** "Not X until Y" goes stale exactly like a status line.

**Check content, not names.** Content repeatedly exists under a different filename than the one searched.

**Commits:** no `Co-Authored-By` or any other trailer unless requested.

## D.4 — Files

| File | Role | Changes |
|---|---|---|
| `FantasyBeefs_Package.md` | This file. Current state, next actions, reviewer carry-forward. | Every cycle |
| `Findings_Register_vN.md` | Permanent additive record. Tracked in repo. | Every cycle |
| `FantasyBeefs_Plan.md` | The arc and its gates. | By ruling only |
| `INDEPENDENT_CODE_SPEC_AUDIT_9ff096b.md` | Evidence record. ChatGPT-authored. | When re-audited |

Register versioning: v15 supersedes v14, tracked, with v14 removed from the working tree in the same commit. Git history preserves it. Only the latest register enters future packages.

---

# PART E — Reviewer's standing brief

**ChatGPT: read this first, every cycle.**

## E.1 — Your role

Independent review. A second set of eyes. Catch what Claude and Fraser miss.

Claude is the architect and owns the planning documents. You do not author them. You produce evidence and challenge.

**You are not here to ratify.** Agreement reached after reading our reasoning is worth nothing. Agreement reached independently, then compared, is evidence.

## E.2 — The failure mode to avoid

Last cycle you correctly quarantined the build order. But you accepted our **problem framing** in four places without independent evidence:

1. **FR-SEC-DB-2.** You recorded `reseau` as unclassified pending investigation — our framing, our finding, our proposed next step. You never asked whether a TCP check is the right first move, or whether Railway support is faster.
2. **The scope ruling.** You ratified Option B and carried the reasoning forward as settled. You never tested whether Week 1 is achievable given what you later found — ~25 missing operations and a frontend making zero core calls. You had the evidence to challenge a schedule claim and did not.
3. **The five-spec decomposition.** You reviewed sequencing *within* the structure. You never asked whether five specs is the right decomposition.
4. **"Two distinct endpoints."** You caught the wording — good — but framed it as phrasing rather than asking whether anyone has determined what `reseau` is.

**Quarantining the build order protects one decision. The pattern is broader: accepting our framing and reviewing inside it.**

## E.3 — Standing instructions

**Challenge the assumptions.** `FantasyBeefs_Plan.md` Section 5 lists twelve load-bearing premises. Challenge any where evidence supports it. **State explicitly when evidence does not** — "I examined assumption 2 and found no basis to challenge it" is a real output.

**Name what you could not verify.** Every pass ends with what you lacked evidence for and why. This is required, not optional. It resists drift toward confident agreement.

**Re-derive, do not recall.** Your carry-forward records open questions and unverified items, not settled conclusions. If you read your own prior conclusions and build on them, you anchor on yourself — the same independence failure, self-inflicted.

**Respect the Part C gate.** Form your sequencing view from Parts A, B, and D. Then read Part C and compare. Say for each point of agreement whether you reached it independently or would have deferred.

**Distinguish verified from reported from inferred.** In your own output, not just when reading ours.

## E.4 — Your carry-forward

At your session close, produce a **Reviewer's Carry-Forward**: what you challenged and how it resolved; what you flagged that remains open; what you could not verify and why; what was in progress when the thread ended.

Fraser pastes it to Claude, who folds it into the next package as Part F. **One file, both perspectives.** You append; you do not author.

---

# PART F — Reviewer's carry-forward

**Authored by the reviewer at its 2026-07-23 thread close. Carried verbatim in substance.**

**Reviewer: these are re-examination targets, not conclusions. Do not inherit them without re-deriving from current source and evidence.**

## F.1 — Challenges raised that require fresh confirmation

- Whether FR-8.7 is construction-incomplete or mainly verification-incomplete.
- Whether the Spec 1 schema remains disconnected from the live challenge service.
- Whether backend authentication is present while only frontend login remains incomplete.
- Whether labels like "backend built" or "Spec 1 shipped" still overstate operating state.
- Whether the historical and current database addresses identify different services or only different network addresses.
- Whether Spec 3 can safely decompose into a pure pricing kernel and Dynamic orchestration.
- Whether FR-AC-ISO-1 is a necessary Spec 2 entry gate.
- Whether frontend implementation can overlap once pricing and escrow contracts freeze.

## F.2 — Open findings to re-audit

Direct float-balance mutations in commissioner rules and wallet paths, and their classification as mirrors, authoritative writes, or ledger bypasses. FR-8.7 tests 6c/6d, settled-reader coverage, review status, migrations, deployment, production confirmation. Spec 1 migration and deployment state. Production credential rotation and public-networking state. `reseau:54032` reachability, identity, and credential status. Git-history treatment for the exposed credential. Deployed `db.schema` import hang. Health database-path reporting. Actual PostgreSQL isolation and concurrent wallet-lock behavior. Frozen-lineup beef scoring. Legacy single-party wager and settlement routes. Pool catalog and remainder-account conformance. Frontend challenge integration.

## F.3 — Not independently verified by the reviewer

Branch and HEAD. Local/remote parity. Push status. Deployment state. Production PostgreSQL version. Backup existence and restoreability. Production row counts. Migration execution state. Public-networking state. Historical Git-secret exposure.

**Reason:** the review used a tracked-file `git archive` with no `.git` metadata and no production access. These require Git metadata or production evidence.

**Claude's note.** Part A of this package labels each of these verified, reported, or inferred from Claude's side. That labeling is Claude's evidence, not independent corroboration. Where the reviewer needs its own, it should ask for the specific command output rather than accept Part A.

## F.4 — Work in progress at the reviewer's thread close

The reviewer recorded that a streamlined documentation package, a new register version, and the revised sequencing were under discussion, with no in-thread evidence that the edits were completed.

**Resolved.** They were completed at Claude's session close, after the reviewer's thread ended:

| Item | Status |
|---|---|
| `Findings_Register_v15.md` | Sections 16 and 17 written. Section 17 supersedes Section 15's gate table. |
| `FantasyBeefs_Plan.md` | Written. Supersedes Master Plan v8 for planning. |
| `FantasyBeefs_Package.md` | This file. |
| FR-8.7 closure before Spec 2 | **Ruled.** In the build order. |
| FR-AC-ISO-1 as Spec 2 entry gate | **Ruled.** Four criteria, all required. |
| Spec 3A/3B decomposition | **Ruled.** Implementation boundary only. |
| Commit state | Register v15 tracked, v14 removed from working tree in the same commit. |

**One thing the reviewer flagged that Claude has not resolved.** The 3A/3B boundary "must be validated against the complete certified JavaScript calculator and Spec Rev 7 before implementation." That validation has not been performed. It is a prerequisite on Spec 3A, not a settled fact — recorded in `FantasyBeefs_Plan.md` §3.6.
