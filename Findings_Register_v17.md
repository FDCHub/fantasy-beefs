# Fantasy Beefs — Findings Register v17

**Supersedes:** v16 (which superseded v15, v14, v13)
**Date:** 2026-07-23 (Session 2, close)
**v17 change:** adds Section 19 — the 2026-07-25 verification and security-inventory session. v16 added Section 18. **Section 15's gate table is superseded by Section 17.**

**Authority note.** Sections 1–14 are carried verbatim. Sections 16, 17, 18 and 19 are additive. Section 18 carries the four FR-8.7-LOG-2 amendments, which govern over the Rev1 rulings retained in place as history. Where they contradict an earlier section, the later section governs. Two such contradictions exist and both are marked: the 12.9 unreconciled flag (resolved in 14.1) and Section 15's gate table (superseded by Section 17).

**Working-tree convention.** v17 is tracked; v16 and v15 are removed from the working tree in the same commit. Git history preserves it. Only the latest register enters future transition packages.

---

## Section 14 — 2026-07-23 security-remediation session

### 14.1 — SCOPE RULING (BINDING)

**The five-spec program is authoritative. Master Plan v8 is superseded on the odds-port placement.**

This resolves the 12.9 "Unreconciled" flag. It is a scope ruling, not a document edit, and it was made before any build work started because it determines what gets built.

**The revised milestones:**

| Milestone | Meaning |
|---|---|
| **August 1, 2026** | Platform live for league setup and the draft window. **Not** betting live. |
| **NFL Week 1 (September)** | Betting activation gate. Requires Spec 2 → Simulation Engine → frontend wiring → GM walkthrough, complete and verified. |

**Reasoning of record.** August 1 is not the first date on which wager settlement or scoring-dependent betting must operate. Deferring betting activation to Week 1 preserves the locked architecture without cutting the odds-dependent stake-and-return mechanic. Launching versus wagering with symmetric stakes despite asymmetric odds was considered and rejected — that is a money-path defect, not an acceptable temporary simplification. Holding August 1 as the wagering date was also rejected: it converts a planning-date mismatch into an engineering emergency and raises the chance of unsafe scope cuts.

**Recorded consequences — all six binding:**

1. Master Plan v8 is superseded on this scope point. Its placement of the odds port below the line no longer governs.
2. Spec 3 remains on the locked build path.
3. The August 1 milestone must not be described as "betting live." It is the platform/draft-window launch milestone.
4. The Week 1 milestone is the betting activation gate, not an aspirational date. Activation requires the complete path to a GM placing a correctly priced bet.
5. **No temporary symmetric-stake fallback is authorized.**
6. Any plan or status document still treating August 1 as the wagering launch date must be updated before further schedule decisions are made.

**Build order unchanged:** 1 → 2 → 3 → 5 → 4.

### 14.2 — FR-SEC-DB-1 — rotation sequence, steps 1–7 COMPLETE, PAUSED at step 8

Rotation was ruled blocked until a fresh, verified production backup existed. The approved eleven-step order was executed through step 7 and then paused by ruling.

**Step 1 — Railway backups: NONE EXIST, AND NONE CAN.**
Backups and point-in-time recovery are Pro-plan features. The Postgres service's Backups tab reports no backups on this volume. Railway's own snapshot backups are snapshot-based with an hours-to-a-day data-loss window; PITR (pgBackRest, weekly full plus daily incremental, ~4-week window, restores to a new service) is unavailable on the current plan. **Consequence: the local dump is not a supplement to Railway backups. It is the only restore point that exists.**

**Step 2 — Local `pg_dump`: EXIT 0.**
Production Postgres runs **18.x** (Settings tab offers an upgrade to 18.4). The `pg-fantasy-test` container's client is 16.14 and cannot dump an 18.x server. A disposable `postgres:18` container supplied `pg_dump` 18.4. Dump written with `--format=custom --no-owner --no-privileges`. 39 tables dumped, all expected objects present.

**Step 3 — `pg_restore --list`: VALID.**
399 TOC entries, 40 tables with both schema and data sections, all primary keys, unique constraints, 12 indexes, and the full FK web. Archive created 2026-07-23 22:29:32 UTC, dbname `railway`, PostgreSQL 18.4, custom format, gzip.

**Step 4 — Restore drill: PASSED.**
Restored into a throwaway `postgres:18` container (`pg-restore-drill`, port 5434), separate from `pg-fantasy-test` which was left untouched for FR-VAL10-ac. `pg_restore` exit 0, 40 tables, FKs restored end-to-end.

Row counts from the **restored copy** — 12 non-empty tables:

| Table | Rows |
|---|---|
| `player_id_map` | 4,777 |
| `projections` | 2,407 |
| `nfl_schedule` | 272 |
| `rosters` | 180 |
| `players` | 180 |
| `matchups` | 98 |
| `teams` / `wallets` / `faab_wallets` | 12 each |
| `leagues` / `faab_config` / `league_scoring` | 1 each |

**FR-5.13's invariant independently reconfirmed.** `bets`, `ledger_entries`, `transactions`, `escrow_accounts`, `escrow_transactions`, `beef_challenges`, `beef_starters`, `users`, and all `pool_*` tables are empty. Zero bets or settlements have ever been written to production. This is now verified from a restored copy rather than asserted from prior sessions.

**Step 5 — Encryption: VERIFIED.**
7-Zip absent from the machine. GnuPG 2.4.5 present, bundled with Git for Windows at `C:\Program Files\Git\usr\bin\gpg.exe`, not on PATH. Encrypted with `--symmetric --cipher-algo AES256`. Decryption test returned exit 0 — the passphrase works and the archive opens.

**Step 6 — Unencrypted copy removed. Verified.**

**Step 7 — Credential dependent inventory: COMPLETE. Surfaced FR-SEC-DB-2 (see 14.3).**

- No `.env` files anywhere in the repo.
- `secrets/` contains `private.json` and `yahoo_oauth.json`; gitignored, nothing tracked under it.
- `.env` was **not** covered by `.gitignore`. Closed this session.
- The `fantasy-beefs` Railway service carries exactly one database variable: `DATABASE_URL`. No `DATABASE_PUBLIC_URL`, no discrete `PG*` variables.
- Three tracked, pushed source files hardcoded a full production connection string. **This is FR-SEC-DB-2.**

**Steps 8–11 — NOT STARTED, deliberately.** Public-networking disable, rotation, and post-rotation verification are gated on FR-SEC-DB-2 classification.

**Approved sequence adjustment.** The original order placed "disable public networking" before the dump. The ThinkPad cannot reach `postgres.railway.internal`, so the dump required the public endpoint alive. Order was revised and approved: dump → verify → encrypt → remove plaintext → inventory → disable public networking → rotate → verify.

**Workflow change recorded.** Direct ThinkPad-to-production PostgreSQL access is **intentionally retired** once public networking is disabled. Future production database work requires a separately authorized Railway-internal method. The ambient `DATABASE_URL` in the Claude Code CLI shell is to be unset and left unset — not repointed. Per-command explicit variables only: temporary `sqlite:///...` for SQLite tests, `TEST_DATABASE_URL` for local Postgres, deliberate task-specific injection with separate authorization for production. Accidental production access fails closed.

### 14.3 — FR-SEC-DB-2 — OPEN. Production connection strings in tracked source and pushed history

| Field | Content |
|---|---|
| **Issue** | Three tracked files on GitHub embedded a full PostgreSQL connection string — host, user, and password — as a fallback default: `seed_player_id_map.py:34`, `scripts/backfill_nfl_teams.py:33`, `scripts/resolve_player_nfl_teams.py:28`. Host `reseau.proxy.rlwy.net`, port `54032`. |
| **Status** | Working-tree fix **committed and pushed** (`c353d2b`). Credential **remains in pushed history**. Host classification **incomplete**. |

**Working-tree remediation — DONE.** All three files converted to a fail-closed read of `DATABASE_URL` from the environment. No embedded host, user, password, or fallback URL. `RuntimeError` raised when unset; error text names the variable only, never a URL. `.gitignore` gained `.env`, `.env.*`, `!.env.example`. Commit `c353d2b`, pushed to `origin/remediation/foundation-phase-1`, local and remote in sync.

**A rejected inference, recorded because the reasoning matters.** Claude Code compared the embedded password against a live variable, found a mismatch, and concluded the credential was "already dead — rotation already neutralized it." **Rejected by ruling.** No rotation had occurred; the session was at step 7 of a sequence whose step 10 *is* the rotation. A password mismatch does not prove rotation or revocation, particularly when the hostnames differ. The inference was repeated three times across the session and corrected each time by binding instruction.

**Read-only classification — three checks run, no credential used:**

| Check | Result | What it establishes |
|---|---|---|
| Current production public host | `hayabusa`: true, `reseau`: false | `reseau` is not the current public endpoint |
| History introduction | `b1bd1b8`, `480ede2` — both pushed | Credential is on GitHub in history |
| DNS | Resolves. A record `66.33.22.224` | Proxy front-end exists in DNS. Nothing about identity. |

**Current production endpoint is `hayabusa.proxy.rlwy.net:15707`. The embedded string points at `reseau.proxy.rlwy.net:54032`.** Different host, different port — two distinct endpoints, not a renamed one.

**Supporting but non-decisive.** `Findings_Register_v12_2.md:535` records `reseau`/`54032` as a stale stored local `DATABASE_URL`. That is prior documentation, not proof. It is the only independent evidence about what `reseau` is, and it is consistent with a reassigned endpoint for the same database. It remains an inference.

**Exposure is broader than GitHub.** During the source fix, Claude Code's edit-tool display printed the full connection string, password included, on the removed diff lines. That text is now in a conversation transcript. Whatever `reseau` turns out to be, **treat its credential as fully exposed.**

**FR-SEC-DB-1 rotation on `hayabusa` alone cannot close FR-SEC-DB-2.** If `reseau` is a separate live database, rotating `hayabusa` leaves it untouched.

**Next steps, in order:**

1. **Credential-free TCP reachability check on `reseau:54032`.** Cheap, uses no credential, and genuinely decisive in one direction: a closed port ends the investigation.
2. If open — **separate ruling required** before any authenticated, read-only identity probe. Reachability does not mean it is Fantasy Beefs.
3. **History treatment deferred.** If `reseau` is live: revoke or rotate there immediately, then decide on history. If decommissioned or definitively unreachable: the secret is non-operational but the history issue remains, and whether the security benefit justifies rewriting shared history is a separate decision. `git filter-repo` is not authorized.

**Not a problem:** `Findings_Register_v12_2.md:535` retains a host/port reference with no password. A findings register documenting an exposure is doing its job.

### 14.4 — FR-SEC-DB-3 — REMEDIATED. Plaintext production dump written to a synced directory

| Field | Content |
|---|---|
| **Issue** | The GnuPG decryption-verification step used `--output NUL`. On Windows, GnuPG treats `NUL` as an ordinary filename rather than the null device. A real 243,863-byte file named `NUL` — the **fully decrypted production database dump** — was created at the repo root, inside OneDrive. |
| **Cause** | A Unix idiom applied on Windows. The correct form writes to a temp path outside any synced directory and deletes explicitly. |
| **Status** | **Remediated, with one qualification.** |

Untracked by git, so never committed. Deletion required `cmd /c del` with the `\\?\` extended-path prefix — `Remove-Item` reported no error but did not delete it, and the file survived the first attempt. Absence verified after.

OneDrive checked: no `NUL` in `PycharmProjects > fantasy-beefs` live files (folder-scoped search), none in the primary recycle bin (sorted by deletion date; newest entry 9 hours old, while the deletion was ~20 minutes prior). No second-stage recycle bin exists in this personal account view.

**Recorded outcome: no synced copy found.** Whether the file ever uploaded remains unproven. Reserved device names are commonly rejected by sync clients before upload, which would explain the absence — but that stays an inference, not a finding.

**Low content severity.** The dump holds reference and seed data only: one league, 12 teams, schedule, projections, ID crosswalk. No user accounts, no money-path rows.

**Deferred, separate decision:** whether to exclude the repo from OneDrive sync entirely. A workflow-wide change, out of scope for a security remediation.

### 14.5 — Findings CLOSED or advanced

**`.gitignore` `.env` gap — CLOSED.** No `.env` existed, so nothing was exposed, but no pattern covered one either. `.env`, `.env.*`, `!.env.example` added in `c353d2b`.

**FR-5.13 — reconfirmed independently.** Zero bets and zero settlements in production, verified by row count against a restored copy of the backup rather than a live query.

**FR-5.7 — production status observed.** `roster_slots` exists in production and carries rows. The migration is live, not merely written. Worth reconciling against the register's prior status language.

### 14.6 — Infrastructure facts established

| Fact | Detail |
|---|---|
| Production Postgres version | **18.x.** Settings tab offers an upgrade to 18.4. Any dump client must be ≥ the server major version. |
| Public endpoint | `hayabusa.proxy.rlwy.net:15707` → 5432. **Public networking is ENABLED.** |
| Private endpoint | `postgres.railway.internal`, IPv4 and IPv6, live |
| Backups / PITR | **Pro-plan only. Unavailable.** |
| Second database | **`postgres-test` service exists and is Online**, own volume (`postgres-volume-F_kl`). Purpose and usage unaudited. Own credential; unaffected by any `hayabusa` rotation. |
| Stopped container | `fb-test-pg`, exited 15 hours ago. Harmless leftover. Left in place — cleanup during a security remediation is unnecessary risk. |
| Live container | `pg-fantasy-test`, `postgres:16`, port 5433. **Do not stop or remove** until FR-VAL10-ac is complete. |

**Do not click "Upgrade to 18.4."** A minor version bump on a production database, mid-remediation, is the wrong order. It goes on the list after rotation.

### 14.7 — Process rules EXTENDED

**Command instructions must name the execution shell, not just the machine.**

Three failures this session share one root: instructions written for one execution environment, pasted into another.

- `Read-Host -AsSecureString` pasted into the Claude Code CLI, whose shell is non-interactive with stdin on the null device. The prompt never reached the user; the variable came back empty; `pg_dump` fell through to a local socket. Cost: two cycles.
- `--output NUL` — a Unix null-device idiom — executed on Windows, creating a real plaintext file. That is FR-SEC-DB-3.
- Container-internal `/backup/...` paths run through Git Bash, where MSYS rewrote them to `C:/Program Files/Git/backup/...`. Twice.

**Rule.** The existing formatting rule names the machine and tool in bold. It is now extended: where a command's behavior depends on the shell — interactive prompts, path translation, environment persistence — the instruction must state which shell and why. "PowerShell (your own window, not Claude Code)" is the shape.

**Corollary — Claude Code's shell does not persist state between tool calls.** Each call is a fresh process. A variable set in one call is gone by the next. Any sequence requiring a variable to survive from setup to use must run in a single interactive session.

**Verification claims must be checked against the command that actually ran.** Claude Code described a restore as `--exit-on-error`-equivalent; that flag was in its own earlier proposal, not in the executed command. It also called a TOC listing proof that the backup was "restorable" — a TOC proves the archive is readable and well-formed, nothing more. The restore drill exists precisely because those are different claims.

**The existence-check rule, extended to diagnosis (from 12.7), earned its keep.** Applied three times: to the "credential is dead" inference, to the `--exit-on-error` claim, and to the "restorable" claim. All three were reversals of a finding or an overstatement of evidence, and all three would have been accepted without it.

### 14.8 — Repository state

**One commit this session, pushed:**

| Commit | Content |
|---|---|
| `c353d2b` | security: remove hardcoded DB connection strings from three scripts; add `.env` patterns to `.gitignore` |

`git status -sb` reports no ahead/behind marker. `git log origin/remediation/foundation-phase-1..HEAD` is empty. **Local and remote in sync at `c353d2b`.**

Untracked and expected: `Findings_Register_v13.md`, `fantasy_beefs_architecture_print_v14.html`, `FantasyBeefs_NextThread_Opener_2026-07-24.md`, `FantasyBeefs_Session_Handoff_2026-07-23.md`, `Odds Calc Rev1.9.html`.

**Nothing was deployed. No migration was run. No credential was rotated.**

### 14.9 — Backup artifact of record

| Property | Value |
|---|---|
| Path | `C:\FantasyBeefs_Backups\` |
| Filename | `fantasy_beefs_prod_2026-07-23_UTC.dump.gpg` |
| Size | 116,928 bytes encrypted (243,863 plaintext) |
| Created | 2026-07-23 22:29:32 UTC |
| Source | `railway` database, production, PostgreSQL 18.4 |
| Format | `pg_dump` custom, gzip, `--no-owner --no-privileges` |
| Encryption | GnuPG symmetric, AES-256. Decryption verified exit 0. |
| Restore proof | `pg_restore` into disposable `postgres:18`, exit 0, 40 tables, row counts confirmed |
| Schema baseline | **Pre-Spec-1.** No `beef_proposals` / `beef_proposal_starters`. |
| Passphrase | Held by Fraser. Stored separately from the artifact. **Not recoverable if lost.** |

**This is the first verified production restore point in the project's history.** It is also the correct rollback point for the Spec 1 migration whenever that is authorized.

---

## Section 15 — Current gate status (supersedes Section 13)

| Gate | Status |
|---|---|
| **Scope authority** | **RULED.** Five-spec program authoritative. 12.9 flag resolved. |
| FR-SEC-DB-1 | **PAUSED** at step 8 of 11. Steps 1–7 complete and non-repeating. Gated on FR-SEC-DB-2. |
| FR-SEC-DB-2 | **OPEN.** Source fixed and pushed; history unremediated; host unclassified. |
| FR-SEC-DB-3 | **REMEDIATED**, qualified. |
| FR-VAL10-af | SATISFIED — not deployed |
| Spec 1 | SHIPPED `dd6d363` — migration written, **not executed** |
| Spec 2 | Opus-ready, not reviewed. Dependency satisfied. |
| Spec 3 | **On the launch path** — not started |
| Spec 5 / Spec 4 | Not started |
| FR-VAL10-ac | Spec Rev 3 approved, unblocked. `pg-fantasy-test` running. Check FR-AC-ISO-1 first. |
| FR-DEPLOY-1 | Open — three bodies of committed code running nowhere |
| FR-INFRA-3 / FR-INFRA-4 | Open |
| FR-8.7 | PARTIAL |

**Build order LOCKED:** 1 → 2 → 3 → 5 → 4.

---

## Section 16 — Independent code audit and status corrections (2026-07-23 S2 close)

### 16.1 — The audit

An independent review was run against the tracked repository archive at HEAD `9ff096b` — 269 entries, no Git metadata. The reviewer inspected source and specs directly and could not verify commit hash, branch, push status, or remote parity; those remained reported facts on its side.

**Evidence record:** `INDEPENDENT_CODE_SPEC_AUDIT_9ff096b.md`. Reviewer-authored. Not reproduced or independently verified by Claude.

**Method.** Public top-level functions and public class methods in runtime modules. Excludes leading-underscore names, model classes with no methods, tests, migration entry scripts, one-off seed scripts, and Pydantic request/response classes. **243 public runtime callables** across 17 subsystem groups.

**Counting discipline adopted.** Exact counts where a spec defines a closed denominator. `≥` where only a lower bound exists. "Unavailable" where specs define behavior without separable operations. **`~25` missing high-authority operations is a summary estimate, not an audited total.** These do not convert to completion percentages.

### 16.2 — What the audit established

**Spec 1's schema exists but is disconnected from the live flow.** `beefs/beef_engine.py` references none of `BeefProposal`, `BeefProposalStarter`, `active_proposal_id`, `accepted_proposal_id`, `challenge_mode`, `response_status`, or the new `wager_type`. Old and new challenge models run in parallel with no feature-gate boundary. This is consistent with the additive S1-R1 ruling and was not previously stated as a code fact.

**Spec 2 has zero implementation.** No `escrow:challenge:{id}` at issue, no ordered funding legs, no reversal linkage, no protocol-event identity, no min-first funding, no atomic acceptance against the new schema. The legacy flow uses reservation arithmetic and places both sides into bet escrow at acceptance.

**No `simulation_engine.py` exists.** Monte Carlo team and player simulation and probability-to-American conversion are present. The specified surface — `o2p`, `p2o`, `derive_stakes`, `adjust_escrow`, Handshake, informational refresh, Final-Lock claim, Final-Lock execution, Final-Lock recovery — is absent.

**The frontend makes zero core challenge calls.** `tools/app.html` calls neither `/beef/challenge` nor `/beef/respond`. Backend routes exist.

**Direct float mutation persists in three modules** — `wallet/wallet_manager.py` deposit, `admin/commissioner_rules.py` several sites, `betting/settlement_engine.py` payout mirrors. Confirms the ledger is not the exclusive write authority.

### 16.3 — FR-COMM-1 — OPENED

| Field | Content |
|---|---|
| **Name** | Direct money-balance mutation in `admin/commissioner_rules.py` |
| **Issue Summary** | Direct money-balance mutations exist in `admin/commissioner_rules.py`. Their classification as approved compatibility mirrors or unauthorized ledger bypasses is **unresolved**. **Verified:** the mutations exist. **Not verified:** which are authoritative writes; which are deliberate mirrors; whether paired ledger entries occur elsewhere in the same transaction; whether any path can create ledger/float divergence. The module has no spec denominator. |
| **Options** | **A.** Transaction-level caller and posting audit now. **B.** Defer to Spec 5, which owns economy account identity. **C.** Convert all sites to `ledger_post()` without auditing first. |
| **Recommendation & Reasoning** | **A, scheduled — not immediately.** This is an open audit finding, not a confirmed defect, and treating it as one would be the same error as the rejected "credential is dead" inference. But it is a money path outside the ledger in a module with no denominator, and production has zero money rows today — the cheapest possible time to audit. C is wrong: converting before classifying could remove a deliberate mirror that something reads. Fold the audit into the FR-8.7 settled-reader grep, which already walks money-path readers. |

### 16.4 — Status corrections ADOPTED

Six corrections. Each because a document contradicted its own evidence.

| Item | Was | Now |
|---|---|---|
| **FR-8.7** | "PARTIAL — implemented, validated to 6b, not shipped" | **Implementation present; verification, migration, and deployment outstanding.** |
| **Spec 1** | "SHIPPED `dd6d363`" | **Implemented, tested, and committed; migration and deployment pending.** |
| **Backend** | "Built, tested, deployed-pending" | **Legacy engines and infrastructure present; target proposal, escrow, pricing, Dynamic, and frontend path incomplete.** |
| **Auth** | "No UI, token hardcoded `'dev-stub-token'`" | **Backend authentication and authorization present** (12 callables: hashing, JWT, current-user/GM dependencies, commissioner and ownership checks, registration, authentication). **Frontend login absent or development-stubbed.** Two separate facts, previously conflated. |
| **Endpoints** | "two distinct endpoints" | **Two distinct network addresses; database and service identity unresolved.** |
| **FR-5.7** | Listed as an open gap | **`roster_slots` exists in production and carries rows.** Migration is live. |

**On FR-8.7.** The principal service surface is in tracked source: `settle_week(..., recovery_token=None)`, `recover_week(...)`, `CLAIMED`/`COMPLETED` lifecycle handling, row-locking queries, recovery-token validation, atomic completion updates, recovery audit behavior. Schema and migrations carry `WeekSettlement.status`, `WeekSettlement.recovery_token`, and settlement recovery audit fields. **Outstanding:** tests 6c and 6d; settled-reader grep; review package; final review; migration execution; deployment and production confirmation.

**On Spec 1.** "Shipped" implies reaching an operating environment. The migration is unexecuted and nothing is deployed.

**On backend.** Individual legacy engines are built. The target betting backend is not — it lacks Spec 1 service integration, all Spec 2 behavior, the Simulation Engine, asymmetric stakes, Dynamic Handshake and Final Lock, frontend integration, several pool behaviors, and ledger-exclusive money writes.

### 16.5 — Build order REVISED (RULING)

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

**The five-spec internal order is unchanged: 1 → 2 → 3 → 5 → 4.** This ruling refines prerequisites and internal implementation boundaries. It does not change the authoritative spec order.

**Two prerequisites inserted before Spec 2:**

**FR-8.7 closure.** The remaining scope is bounded, it governs settlement safety, and Spec 2 adds settlement-relevant escrow complexity. Unresolved claim-first behavior becomes harder to reason about once more money paths sit on top of it.

**FR-AC-ISO-1 gate — not a build stage.** Spec 2's atomic acceptance depends on deterministic wallet-row locking. The warning at `beef_engine.py:877` reports an isolation level ignored because the connection was already established. Configuration intent is not evidence.

**Four gate criteria, all required:**

1. The actual PostgreSQL transaction isolation level used by the relevant application transaction.
2. `SELECT ... FOR UPDATE` serializes conflicting acceptance paths as intended.
3. Two concurrent attempts yield exactly one valid economic result — no duplicate posting, no partial posting.
4. The proof uses the same engine, session, and transaction-construction pattern Spec 2 will use.

**A configuration setting or intended isolation level does not satisfy this gate. Observed concurrent outcomes do.** This may not require completing every remaining FR-VAL10-ac item; the isolation and concurrency proof comes first.

**Spec 3 decomposed — implementation boundary only:**

**3A — pricing kernel.** `o2p`, `p2o`, `derive_stakes`, immutable pricing result types, adversarial math tests, pricing provenance contract. Sufficient for correctly priced Locked proposals; lets the frontend contract stabilize.

**3B — Dynamic Handshake and Final Lock.** Handshake funding and ceilings, model freeze, informational refresh, `adjust_escrow`, Final-Lock claim-first execution, refunds, recovery, final-term freeze.

**Boundary reasoning.** Spec Rev 7 separates mode-agnostic pricing from lifecycle orchestration and states the caller decides whether `adjust_escrow` runs — Locked never calls it, Dynamic calls it exactly once. `adjust_escrow` is part of the certified Flexible Stake and Return mechanism, but specifically its Dynamic Final-Lock half. It is not needed to price or accept a Locked Challenge.

**Full Spec 3 remains required before betting activation.** The decomposition is not permission to activate betting before 3B completes.

**Frontend may begin in parallel** after Spec 2's proposal/escrow API shape and Spec 3A's pricing payload both freeze. Build against explicit fixtures. Dynamic-specific cards and Adjustment states do not freeze until 3B settles. **Caution:** the locked response card designs were written to work under either symmetric or asymmetric stakes because pricing was unsettled when designed. Freezing the frontend contract before pricing freezes reintroduces that ambiguity.

### 16.6 — Transition process ESTABLISHED

Three documents replace five. Two change every cycle.

| File | Role | Changes |
|---|---|---|
| `FantasyBeefs_Package.md` | Current state, next actions, reviewer carry-forward | Every cycle |
| `Findings_Register_vN.md` | Permanent additive record. Tracked. | Every cycle |
| `FantasyBeefs_Plan.md` | The arc and its gates | By ruling only |
| `INDEPENDENT_CODE_SPEC_AUDIT_*.md` | Evidence record. Reviewer-authored. | When re-audited |

**`FantasyBeefs_MasterPlan_v8_LaunchPath.md` is superseded for all planning purposes** by `FantasyBeefs_Plan.md`. Retained as history.

**Architecture diagram retired** in favor of the Part B module inventory table, which is code-derived rather than estimated.

**The Package is read-order gated.** Parts A, B, D, E are open. Part C — build order and next actions — is quarantined from the reviewer until it states its own sequencing view. Reading our order first produces agreement, which is worth nothing.

**Reviewer appends, does not author.** At its session close it produces a Reviewer's Carry-Forward — what it challenged and how it resolved, what remains open, what it could not verify, what was in progress. Folded into the next Package as Part F. One file, both perspectives.

**Carry-forward records open questions and unverified items, not settled conclusions.** Reading its own prior conclusions would anchor it on itself — the same independence failure, self-inflicted. Standing instruction: re-derive, do not recall.

### 16.7 — The reviewer's independence failure, recorded

The reviewer correctly quarantined the build order last cycle. It then accepted our **problem framing** in four places without independent evidence:

1. **FR-SEC-DB-2** — recorded `reseau` as unclassified pending investigation, using our framing, our finding, our proposed next step. Never asked whether a TCP check is the right first move.
2. **The scope ruling** — ratified Option B and carried the reasoning forward as settled. Never tested whether Week 1 is achievable given what it later found: ~25 missing operations and a frontend making zero core calls. It had the evidence to challenge a schedule claim and did not.
3. **The five-spec decomposition** — reviewed sequencing *within* the structure, never asked whether five specs is the right decomposition.
4. **"Two distinct endpoints"** — caught the wording but framed it as phrasing rather than asking whether anyone has determined what `reseau` is.

**Quarantining a build order protects one decision. The pattern is broader: accepting our framing and reviewing inside it.**

**Countermeasure adopted:** `FantasyBeefs_Plan.md` Section 5 lists twelve load-bearing assumptions as explicit challenge targets. Each pass must also name what it could not verify. Stating "I examined assumption N and found no basis to challenge it" is a required output form, not a non-answer.

### 16.8 — Repository state at close

| Commit | Content |
|---|---|
| `c353d2b` | security: remove hardcoded DB connection strings from three scripts |
| `9ff096b` | docs: track Findings Register v14 |

Both pushed. `git status -sb` no ahead/behind marker; `git log origin/..HEAD` empty. **In sync at `9ff096b`.**

**Repository archive** for review: `fantasy-beefs_9ff096b.zip`, 269 entries, built via `git archive`. Filter for `secrets/`, `.env`, `.db`, `.dump`, `.gpg` returned nothing.

**Nothing deployed. No migration run. No credential rotated.**

---

## Section 17 — Current gate status (supersedes Section 15)

| Gate | Status |
|---|---|
| **Scope authority** | **RULED.** Five-spec program authoritative. |
| **Build order** | **REVISED.** Security → FR-8.7 → deployment → FR-AC-ISO-1 → Spec 2 → 3A → 3B → 5 → 4 |
| FR-SEC-DB-1 | **PAUSED** at step 8 of 11. Steps 1–7 complete, non-repeating. |
| FR-SEC-DB-2 | **OPEN.** Source fixed and pushed; history unremediated; host unclassified. |
| FR-SEC-DB-3 | **REMEDIATED**, qualified. |
| **FR-COMM-1** | **OPEN — new.** Commissioner-rules float mutation unclassified. |
| FR-VAL10-af | SATISFIED — not deployed |
| Spec 1 | **Implemented, tested, committed; migration and deployment pending** |
| **FR-8.7** | **Implementation present; verification, migration, deployment outstanding.** Six items. |
| FR-AC-ISO-1 | **OPEN — promoted to Spec 2 entry gate.** Four criteria. |
| Spec 2 | Opus-ready, not reviewed. Two prerequisites now precede it. |
| Spec 3A / 3B | Not started. Both required before betting activation. |
| Spec 5 / Spec 4 | Not started |
| FR-VAL10-ac | Unblocked. `pg-fantasy-test` running. FR-AC-ISO-1 is the gating subset. |
| FR-DEPLOY-1 | Open — four commits running nowhere |
| FR-INFRA-3 / FR-INFRA-4 | Open |

**Five-spec internal order unchanged: 1 → 2 → 3 → 5 → 4.**

**Milestones:** August 1, 2026 = platform launch, draft window. NFL Week 1 = betting activation. **No symmetric-stake fallback authorized.**


## Section 18 — FR-8.7-LOG-2 independent review and FR-8.7-LOG-1 ship

### 18.1 — FR-8.7-LOG-1 — CLOSED, SHIPPED

Feed logging ran on `settle_week`'s economic session and committed there. A feed failure after the commit at line 781 poisoned that session, the report block at 785–800 then threw, and `settle_week` raised after money was durable. Both live callers misreported it as a settlement failure.

Fixed by a pre-commit scalar boundary: challenge IDs collected before the commit, `log_settlement_events` retyped to `list[int]`, feed work run on its own throwaway `SessionLocal()`, failures caught with a defensive `db.rollback()` and a rendered `%`-style error log.

Shipped `59be320`. Baseline `21ec171`. Not deployed. Full detail in `FR_8_7_LOG_1_FEED_ISOLATION_MODULE_SPEC_FINAL.md`.

### 18.2 — FR-8.7-LOG-2 — AMENDED, not closed

Two independent reviews converged, with no cross-contamination, on a defect the finding never examined.

**Amendment 1 — Option 1 was insufficient.** Call-site session isolation does not isolate. `pending` holds ORM `Bet` objects owned by the settlement session; `expire_on_commit` defaults `True` (the string appears nowhere in the repo); so reading `bet.beef_challenge_id` at `league_feed.py:248` refreshes through `object_session(bet)` — the settlement session — whatever session the function was handed. Measured on PostgreSQL 16.

**Amendment 2 — Q4 OVERRULED.** "No settlement-session rollback" is false for the shape as ruled, and too broad even for the corrected shape. Its stated reasoning failed on both halves: the report block runs *after* the except clause, so no report state exists at the catch, and that block performs only reads. There was nothing uncommitted to discard. `db.rollback()` after 781 is a verified no-op on a healthy idle session and is retained defensively.

The defensible claim is narrow: *a failure originating in the isolated feed transaction cannot poison the settlement session.* Post-commit failures arising in the report block itself remain possible — FR-8.7-LOG-4.

**Amendment 3 — recon classification.** LOG-2 never examined settlement-owned ORM objects crossing the proposed boundary. The finding does not mention `beef_challenge_id`, ORM object ownership, or session expiry anywhere. **This was an existence-check/recon miss, not a rejected argument.** The corrective attaches to the recon step, not to the reasoning.

**Amendment 4 — the locked snippet is RETRACTED. Four verified defects:**

| # | Defect | Consequence |
|---|---|---|
| 1 | False session isolation | Amendment 1 |
| 2 | `SessionLocal` not imported at module scope — only at `settlement_engine.py:1046` inside `__main__` | `NameError` |
| 3 | `logger` undefined in that module | `NameError` **inside the except block** — converts a swallowed feed failure into a raised one after commit. LOG-1's bug delivered by LOG-1's fix |
| 4 | `extra={...}` renders nothing under this repo's plain stdlib logging | The Q6 signal fires without naming league or week — the one thing Q6 exists to guarantee |

**Sustained and upgraded from asserted to verified:** Q3 sole caller (repo-wide grep, all 139 `.py` files, three hits); Q5 atomicity (forced mid-batch failure persisted 0 rows); Q6 no idempotency (`feed_events` carries only a non-unique `Index("ix_feed_league_created", league_id, created_at)`); LOG-3 count accurate as written (commits at 135, 161, 185, 233, 297 — five total, four siblings; the 428 commit sits in a `__main__` demo).

### 18.3 — FR-8.7-LOG-4 — NEW. Post-commit settlement-report exposure

**Issue summary.** After the economic commit at 781, `settle_week` builds its report with further settlement-session work: `db.expire_all()` at 785, `db.query(Wallet)` at 788, lazy `w.team` at 792. A failure there raises after money is durable — the same misreport class LOG-1 removed, arriving through a door no change at 782 can close.

**Options.** (a) Wrap the post-781 region so a report-building failure returns a degraded-but-truthful success. (b) Build the report from values already in memory — `settlements` and `balance_before` are plain floats; only `Wallet.balance` and `w.team.team_name` require queries. (c) Accept the exposure and document it.

**Recommendation & reasoning.** (b). It removes the failure surface rather than catching it, and the data is nearly all in hand already. (a) leaves a partially-populated report shape to define. Not launch-blocking: it requires a transient DB failure inside a narrow window. `recover_week` reaches the same block via `settle_week:1037` and inherits the exposure; its guards fail closed, so the cost there is noise, not loss.

### 18.4 — FR-8.7-LOG-5 — NEW. Feed payout headline diverges from the ledger

**Issue summary.** `feed/league_feed.py:266` and `:272` compute `round(bet.amount * bet.odds, 2)` and pass it into `_hl_settled` as the payout. That is the formula FR-5.10 retired. Authoritative settlement derives payout from actual escrow cents at `settlement_engine.py:569` and `:620`, and the comment at 528 says so explicitly. For asymmetric odds the feed headline states a payout the ledger never made.

**Options.** (a) Pass the actual payout through from settlement. (b) Have the feed re-read escrow. (c) Drop the figure from the headline.

**Recommendation & reasoning.** (a). The settlement path already holds the true number and the feed already receives a caller-supplied payload. No money moves either way — but a GM reads a figure that disagrees with his own ledger, which is a trust defect on a betting product. Lines were deliberately neither edited nor commented during LOG-1.

### 18.5 — FR-8.7-LOG-6 — NEW. Feed-path test coverage

**Issue summary.** Before this session, zero tests touched the feed path. `test_fr87_log1_feed_isolation_pg.py` is the first, and it covers the settlement-isolation boundary only.

Two named gaps:

1. **Scenario 4 never added.** The forced failure injects a Python-level `RuntimeError` from `before_flush`. That exercises the handler but cannot poison a session, because no database error occurs. The error class that actually aborts a PostgreSQL transaction — a real server-side statement error producing `InFailedSqlTransaction` — is not exercised. The zero-SQL binding assertion subsumes it structurally, but "impossible by construction" is the claim under review and should be proven against the real class. Authorized as a deliberate skip, recorded so it does not read as done.
2. **The other five committing feed functions are untested.** `log_challenge_issued`, `_accepted`, `_declined`, `_countered` all commit a passed-in session; `log_challenge_expired` does not. No test covers any of them.

**Recommendation & reasoning.** Add Scenario 4 when the feed module is next opened — cheapest at that moment, and it touches no production code. Broader coverage sequences with FR-8.7-LOG-3.

### 18.6 — FR-AC-ISO-1 — reproduced from an unrelated path

The SAWarning at `beef_engine.py:877` — REPEATABLE READ ignored because the connection was already established — surfaced again during the LOG-1 test run, emitted by the beef-acceptance fixture. That is a second, independent path with no isolation concern of its own.

**Consequence.** The isolation level requested there is not taking effect, confirmed twice. FR-VAL10-ac's concurrency proof depends on isolation being real. Resolve ISO-1 before ac's assertions are frozen, or ac proves something about a weaker isolation level than it claims.

### 18.7 — FR-SEC-DB-1 — SHARPENED. Exposure is wider than logged

**New evidence.** Commit `c353d2b` (2026-07-23 16:26) is titled *"security: remove hardcoded DB conn strings."* It removed them from the working tree. It did not remove them from history. Every commit before `c353d2b` still contains them.

**And the branch is publicly readable.** During this session the full branch tarball was retrieved from `codeload.github.com` with no GitHub credentials present in the retrieving environment. `raw.githubusercontent.com` served individual files the same way. `secrets/private.json` is correctly absent and a targeted grep of HEAD found no hardcoded production DSN — but the pre-`c353d2b` history is reachable by anyone who knows the repository name.

The exposed value was deliberately **not** retrieved or reproduced. The commit title plus public readability is sufficient evidence of exposure; pulling the credential into a transcript would enlarge the problem.

**Consequence.** Removing a secret from HEAD while history stays public is not remediation. Rotation is mandatory and first. Separately decide whether history needs rewriting or the branch needs to go private. Rotation path per the opener: Postgres service → Database → Config → Regenerate. Not manual SQL — that path failed previously.

**This is the only item on the board with a deadline.**

### 18.8 — Architecture diagram — assessed, no update required

`fantasy_beefs_architecture_print_v14.html` contains zero references to `log_settlement_events`, `feed_events`, or `league_feed`. It depicts `settle_week() — escrow-close (FR-5.9 / FR-5.10)` and no feed subsystem at all.

LOG-1 therefore changed nothing the diagram shows, and no v15 was generated — regenerating an identical file would be churn.

**But the omission is itself a gap worth recording.** An undepicted subsystem containing five functions that commit their callers' sessions (FR-8.7-LOG-3) is exactly the kind of coupling a diagram exists to surface. Add the feed subsystem when the diagram is next revised for a reason that genuinely changes it.

---

## Section 19 — 2026-07-25 verification and security-inventory session

### 19.1 — Repository state

HEAD `07a8c0b910002e9a65f006ff68b8036c5153c4aa`. Local, local tracking ref, and remote server identical. `git log origin/remediation/foundation-phase-1..HEAD` empty. Tracked working tree clean; all status entries untracked.

**Runtime source unchanged from `59be320`.** One intervening commit, `07a8c0b`, touching four paths: `.gitignore` modified, plus `FR_8_7_LOG_1_FEED_ISOLATION_MODULE_SPEC_Rev1.md`, `FR_8_7_LOG_2_HIDDEN_FEED_TRANSACTION_FINDING.md`, and `Findings_Register_v16.md` added. 725 insertions, zero deletions.

**Method note.** `git merge-base --is-ancestor` alone does **not** establish an unchanged baseline — it proves only that a commit is somewhere in history. The commit range plus the path diff are what establish it. A conclusion was stated ahead of that evidence earlier in the session and corrected.

### 19.2 — FR-SEC-DB-2 — CLASSIFIED

**`reseau.proxy.rlwy.net:54032` answers HTTP, not PostgreSQL.**

`pg_dump` against it returned:

```
connection to server at "reseau.proxy.rlwy.net" (66.33.22.224), port 54032 failed:
received invalid response to SSL negotiation: H
```

`H` is the first byte of `HTTP/`. The Railway TCP proxy port has been recycled to a non-PostgreSQL service that is not ours. This is the "port recycled to another customer" branch, now evidenced rather than hypothesised.

**No credential was transmitted.** `pg_dump` sends an 8-byte `SSLRequest` first, carrying no username or password. The server replied with HTTP bytes and the connection aborted before the startup packet. Recorded as a near-miss: had negotiation succeeded, the production role password would have been sent to a foreign host.

**Consequences.**

- Rotation scope is `Postgres` and `postgres-test`. No third credential path exists.
- The dashboard inventory finding (no service in the sole `production` environment owns `54032`) is corroborated by protocol evidence.
- The former-production-proxy theory is no longer needed to explain the address, and remains **inference**, not finding, where it appears.
- **Do not use the embedded `reseau` credential.** Do not probe the address further; it belongs to a third party.

### 19.3 — The ambient `DATABASE_URL` was pointing at `reseau:54032`

The standing opener claim — *"The ambient `DATABASE_URL` in the Claude Code CLI shell is production PostgreSQL"* — was **false**. It held a stale DSN for the dead recycled address, and that claim had propagated across multiple openers as a safety premise.

**Do not restore that variable to any shell profile.** While it holds a malformed or dead value, code reading it fails closed rather than connecting somewhere wrong.

### 19.4 — Guard 5 credit WITHDRAWN

`test_support_postgres.py` Guard 5 refuses to run when the harness destination resolves to the same host, port, and database as the ambient `DATABASE_URL`. It was credited earlier in the session as a real production-write guard.

**Withdrawn.** It has been comparing against a dead foreign address. It would **not** have blocked a harness aimed at real production on `hayabusa:15707`. The mechanism is sound; the reference value it compares against is wrong. Requires re-derivation before it is relied on.

### 19.5 — FR-SEC-DB-4 — NEW

`postgres-test` is a second, orphaned, publicly reachable PostgreSQL service in the `production` environment.

| Field | Value |
|---|---|
| Public | `sakura.proxy.rlwy.net:12561` → `:5432` |
| Private | `postgres-ym7q.railway.internal` |
| Volume | `postgres-volume-F_kl` |
| Status | Online |
| Inbound references | **None.** No service points at it on the project canvas |
| Contents | Two default databases (`postgres`, `railway`), **zero user tables**, `railway` at 7,678 kB — baseline |
| Backups | None; none possible on this plan |
| Credential | Never rotated, never audited |

Previously logged only as "unaudited, running and billing." That undersold it: it is a second public attack surface with its own role password.

**Classification:** same security stage as FR-SEC-DB-1. **Not independently launch-blocking.**

**Disposition undecided.** Deletion of a volume-backed service is irreversible and there is no restore path on this plan. Two inspection gaps remain: the `postgres` database itself was not inspected, and the volume below the database layer is unexamined. "Nothing references it" is strong evidence of orphaning, not proof that deletion has no operational consequence.

### 19.6 — No restore point beyond the local dump — both services verified

Both Backups tabs, 2026-07-25:

> *"Backups and point-in-time recovery (PITR) are only available for customers on the Pro plan."*

No Create control. No schedule options. No backups on either volume.

**A volume-restore credential recovery path is therefore unavailable.** This matters because restoring a volume would otherwise recover the old role password — the password lives in the PostgreSQL data directory.

**Self-correction recorded.** Mid-session, the §14.2 step-1 observation was challenged on the grounds that Railway's volume-backups documentation states no plan gate. That argued from documentation silence against a direct dashboard measurement, and it was wrong. The register's original observation stands. **A measurement outranks documentation silence.**

### 19.7 — Sole restore point, single copy

`C:\FantasyBeefs_Backups\`

| File | Size | Written |
|---|---|---|
| `fantasy_beefs_prod_2026-07-23_UTC.dump.gpg` | 116,928 bytes | 7/23 3:45:24 PM local (22:29 UTC; PDT −7) |
| `fantasy-beefs_9ff096b.zip` | 25,991,636 bytes | 7/24 9:08 AM |

Outside OneDrive, correct per FR-SEC-DB-3. **One copy, one disk, one machine — the daily driver.**

**Recommended before rotation:** a second copy of the `.gpg` on independent storage. Already AES-256, 114 KB. Passphrase stays separate and is not recoverable if lost. This is not a database backup mechanism; it removes the single-disk failure mode around the only verified restore artifact.

**Open reconciliation.** The register records the accidental plaintext decryption at 243,863 bytes; the encrypted artifact is 116,928. GnuPG compression is the plausible explanation but is unverified. Compare at Phase B's `pg_restore --list` step.

### 19.8 — Option B RULED — rotation order

**Governing order:** fresh verified restore point → rotate with the TCP proxy intact → externally verify role authentication **and** variable propagation → correct the app variable → restart `fantasy-beefs` → **then** decide on public networking.

**The original "disable public networking first" step 8 is SUPERSEDED for this operation.**

Reasoning of record:

- There is no disable toggle. For a database, public networking **is** the TCP proxy entry; removal means deleting it, and a recreated proxy receives a **new domain and port**.
- Removing it first destroys the local `pg_dump` path — the fresh restore point must be taken while the proxy exists.
- Removing it first destroys the external authentication test, which is the strongest detector for the desync failure mode, precisely when it is needed. Railway's internal query box authenticates through Railway, not through the role credential over the wire.
- Rotation is the remediation; proxy removal is defense in depth. Once rotated, the exposed credential is dead and what remains is the generic risk of a reachable Postgres — a different finding.

**Public-networking window is bounded to that sequence.** P3 establishes that a migration needs the public proxy *when it runs*, not that the proxy must remain continuously exposed until then. Removal is reversible; the app uses the private hostname and is unaffected either way. Future administrative work re-creates the proxy, accepts the new address, and removes it again.

### 19.9 — App `DATABASE_URL` is a literal

`fantasy-beefs` → Variables holds a hand-typed literal on `postgres.railway.internal:5432/railway`, not a `${{Postgres.DATABASE_URL}}` reference.

**Consequences.** Regeneration will **not** propagate — the Credentials tab keeps the Postgres service's own variables in sync and cannot rewrite a literal in another service. Also: the app does not depend on the public proxy, so proxy removal is safe for production.

| | Approach |
|---|---|
| **A** | Rotate, then hand-edit `fantasy-beefs`'s `DATABASE_URL`, then restart |
| **B** | Convert the literal to `${{Postgres.DATABASE_URL}}` first, verify it resolves, then rotate |

**B is preferred** — it fixes the root cause and every future rotation inherits the fix. It became available once P7 cleared the accidental-deployment risk. **It is a production configuration change and is not authorized.**

### 19.10 — FR-DEPLOY-1 SHARPENED

Deployments are `railway up` from the CLI. **No GitHub connection, no connected branch, no "deploy latest commit" path.** The deployment row menu offers View logs / Restart / Redeploy / Remove. `Restart` is the correct instrument for a variable change; `Redeploy` re-runs the existing snapshot; `Remove` sits directly below it and is destructive.

**No commit SHA is recoverable from any deployment.** `railway up` uploads a working-tree snapshot, so nothing links the running image to a commit. "The production image predates `0f4a04d`" is **inference from timing**, not verified fact.

**The finding is therefore wider than logged.** It is not only that four commits run nowhere; it is that **what is running in production cannot be established.**

Related: `railway up` uploads the working tree, which currently carries ~24 untracked documents, an `archive/` directory, and a 26 MB repo zip. `.railwayignore` **already exists** (620 bytes, 7/23) — its contents still need review before the controlled deployment.

### 19.11 — Migration execution path

**No Alembic.** `alembic.ini` absent. Twelve hand-rolled migration scripts in `db\migrations\`, plus a separate set of root-level `migrate_*.py` and a third top-level `migrations\` directory.

All twelve follow one shape: read `DATABASE_URL` from the environment, Postgres-only, refuse to run without it, print a "Re-run with `DATABASE_URL`" hint. This includes `migrate_spec1_proposal_lifecycle.py` — 21,626 bytes, 7/23 9:12 AM.

**Migrations therefore execute from the ThinkPad over the public TCP proxy.** Removing public networking permanently would block the Spec 1 migration. Decisive evidence for Option B's ordering.

### 19.12 — Findings Register v16 identity defect — verified in the tracked blob

Confirmed via `git show HEAD:Findings_Register_v16.md`, not only the project-panel copy. Five items, listed in this document's front-matter amendment above.

**This is the root cause of the recurring version confusion.** The 2026-07-24 opener said v13; the 07-24 Master Plan Zone 1 said "active version is v15." Neither was careless — the artifact tells the reader it is v15 on line 1. The convention on line 9 also explains why v15 remains tracked: the sentence naming which file to remove was never updated.

**Related:** `FR_8_7_LOG_1_..._Rev1.md` is 21 minutes **newer** and larger than `..._FINAL.md` (6:29 PM vs 6:08 PM; 8,957 vs 8,923 bytes). Tracking Rev1 at `07a8c0b` was therefore likely deliberate. An earlier inference that Git held the superseded copy was wrong. The integrity item stands, reframed: two near-identical files where the naming no longer indicates which governs. Resolve by content history, not filename.

### 19.13 — Stale Railway rotation path — three artifacts

v16 §18.7, the 2026-07-25 opener, and `fantasy_beefs_architecture_print_v14.html` all specify *Postgres service → Database → Config → Regenerate*. `Config` is a real tab in the Database view — it is not the control. Wrong-but-plausible, which is why it survived three artifacts by copy.

**Canonical replacement, to be propagated:**

> **Rotation path:** Postgres service → **Database view → Credentials tab → Regenerate**. This regenerates the password while keeping the database and its environment variables synchronized, avoiding the authentication mismatch that manual variable edits cause. Dependent services must then be **manually redeployed**. Do **not** edit `POSTGRES_PASSWORD` by hand. Do **not** use manual SQL — that path failed previously. If the role password and the propagated variables disagree afterward, **stop and assess**; do not restart dependents into a desync.

Multiple 2026 Railway Central Station threads document the desync class, including a Hobby-plan lockout with no backups. Keep the warning attached to the path wherever it propagates.

### 19.14 — TCP classification method DISCARDED

Three credential-free `Test-NetConnection` probes:

| Target | Result |
|---|---|
| `reseau.proxy.rlwy.net:54032` — target | `True` |
| `reseau.proxy.rlwy.net:54871` — arbitrary same-host control | `True` |
| `hayabusa.proxy.rlwy.net:15707` — known positive | `True` |

The control port answered although nothing should be listening on it. **The method cannot distinguish an exposed database from Railway's proxy edge accepting a connection.**

**This records the method's failure, not reachability.** It is specifically **not** evidence that `reseau:54032` is live — §19.2 later established that it is not even a PostgreSQL server. The control port is the only reason the false positive was caught, and it was pre-registered before the result was known.

### 19.15 — Preflight gate P1–P7 — COMPLETE

| Gate | Result |
|---|---|
| **P1** | Current `Postgres` credential captured offline. Preserves the first desync recovery lever |
| **P2** | App `DATABASE_URL` is a **literal** on the private hostname (§19.9) |
| **P3** | Migrations run from the ThinkPad over the public proxy (§19.11) |
| **P4** | 07-23 encrypted dump verified present outside OneDrive, 116,928 bytes; passphrase retrievable (§19.7) |
| **P5** | `postgres-test`: two default databases, zero user tables, baseline size (§19.5) |
| **P6** | No backups, no PITR, none creatable — both services (§19.6) |
| **P7** | CLI-only deployments; no GitHub build path; Restart / Redeploy / Remove (§19.10) |

### 19.16 — Phase B — authorized, attempted, incomplete

Bounded authorization granted: fresh `pg_dump` through the existing proxy, credential via environment variable only, custom-format with reviewed flags, `pg_restore --list` verification, encrypt before retention, decrypt-verify to a temp path outside OneDrive, never `--output NUL`, extended-path delete with absence verified, offsite copy, stop after Phase B.

**Three attempts, three failures, none in PostgreSQL:**

1. Connected to `reseau:54032` — produced §19.2, the session's most consequential finding.
2. `invalid option -- 'm'` — PowerShell mangled the quoted `sh -c` string; `--format=custom` was chewed. Twice, in two command shapes.
3. `invalid connection option "$env:DATABASE_URL"` — the variable's *value* contained the literal text `$env:DATABASE_URL` plus whitespace. A whole command line had been pasted into it rather than a bare DSN.

**No state changed.** No credential rotated. Two artifacts to clean up: a zero-byte `.dump` and `dump.sh` in `C:\FantasyBeefs_Backups\`.

**Gate correction adopted.** Substring checks on a DSN are insufficient — a command line containing the DSN passes them. Validate by **shape**: `StartsWith('postgresql://')`, no whitespace, anchored host/port/database match.

### 19.17 — Process note — DSN handling

A DSN or DSN-bearing command line reached the transcript three times during this session. Passwords were redacted each time, so **no credential leaked**.

**Standing rule reaffirmed:** connection strings transfer by clipboard into `(Get-Clipboard).Trim()`. They are never typed into chat, never echoed to a terminal, and never placed on a command line — container invocations pass the variable **by name** (`-e DATABASE_URL`), not by value, so no shell expands it.

### 19.18 — Gate status changes from this session

| Gate | Status |
|---|---|
| **FR-SEC-DB-2** | **CLASSIFIED.** `reseau:54032` is not a PostgreSQL service and is not ours |
| **FR-SEC-DB-1** | Steps 8–11 **unblocked** by DB-2 classification, but reordered per Option B. Phase B incomplete |
| **FR-SEC-DB-4** | **OPEN — new.** Orphaned public `postgres-test`. Disposition undecided |
| **FR-DEPLOY-1** | **WIDENED.** Running image provenance unrecoverable |
| **Guard 5** | **Credit withdrawn.** Needs re-derivation |
| Git history remediation | Still deferred. `git filter-repo` not authorized |
| Everything else | Unchanged from Section 17 |

**Five-spec internal order unchanged: 1 → 2 → 3 → 5 → 4.**

**Milestones unchanged:** August 1, 2026 = platform launch and draft window. NFL Week 1 = betting activation. **No symmetric-stake fallback authorized.**

**Nothing deployed. No migration run. No credential rotated. Nothing committed.**

---

## Section 20 — Phase B completion and document-integrity session

### 20.1 — Repository state

No commit this session. Phase B touched no tracked file.

HEAD `233d89db373664e08b64636e933f56a2d926fa21`. Local, tracking ref, and remote confirmed identical. `git log origin/remediation/foundation-phase-1..HEAD` empty. No tracked working-tree changes. Untracked list unchanged from session open.

Runtime baseline re-derived at `233d89d`: four paths across `59be320..HEAD`, all documentation, `.gitignore`, or a register rename. Zero `.py`. **`59be320` still describes the deployable runtime.** Established by commit range plus path diff, not ancestry alone.

`.gitignore` assessed and excluded as runtime-relevant: it governs Git tracking; `railway up` reads `.railwayignore`, untouched since 07-23.

Nothing deployed. No migration run. No credential rotated.

---

### 20.2 — Phase B — COMPLETE

Executed end to end in a single interactive PowerShell session on the ThinkPad X13.

| Step | Result |
|---|---|
| Cleanup | No-op. Neither artifact existed. Confirms vol. II §19.16 — the 07-25 failures changed no state, including no partial dump. |
| DSN | Railway CLI JSON capture. Clipboard removed from the path. Shape checks `True`/`False`/`True`, length 87. |
| B2 | `pg_dump -Fc -O -x` via disposable `postgres:18`. 243,863 bytes. |
| B3 | `pg_restore --list` → 410 TOC entries, **40 tables**. Exact match to 07-23 baseline. |
| B4 | GnuPG 2.4.5 symmetric AES-256. 116,922 bytes. |
| B5 | `--no-symkey-cache` decrypt. **Genuine passphrase prompt.** 243,863 exact. |
| B6 | Five deletions via `cmd /c del` + `\\?\`. Both `Test-Path` `False`. |
| B7 | OneDrive copy, both artifacts, lengths verified. Physical copy **outstanding**. |

Plaintext window: 08:54–09:00 local, six minutes, in `C:\FantasyBeefs_Backups\` which is outside OneDrive.

**The public proxy was preserved throughout.** Phase B touched no networking setting.

---

### 20.3 — Backup artifact of record — supersedes vol. II §14.9

| Property | Value |
|---|---|
| Path | `C:\FantasyBeefs_Backups\` |
| Filename | `fantasy_beefs_prod_2026-07-25_UTC.dump.gpg` |
| Ciphertext | 116,922 bytes |
| Plaintext | 243,863 bytes |
| Created | 2026-07-25 15:54 UTC |
| Source | `railway` database, production, PostgreSQL 18.x, via `hayabusa.proxy.rlwy.net:15707` |
| Format | `pg_dump` custom, gzip, `--no-owner --no-privileges` equivalents (`-O -x`) |
| Encryption | GnuPG 2.4.5 symmetric, AES256.CFB, one passphrase |
| Recovery proof | Cache-bypassed decrypt, real prompt, exact length |
| Schema baseline | **Pre-Spec-1.** No `beef_proposals` / `beef_proposal_starters`. |
| Passphrase | Held by Fraser. Same as the 07-23 artifact. Stored separately. |
| Offsite | `C:\Users\frase\OneDrive\FantasyBeefs_Restore\` |

The 07-23 artifact (116,928 bytes) is retained and also copied offsite.

**Byte-count observation.** Both plaintexts are 243,863 bytes exactly. Nothing deployed since 07-23, no migration run, Spec 1 committed and unshipped — so schema and the 12 wallet rows are unchanged. The 6-byte ciphertext delta (116,928 → 116,922) traces to `pg_dump`'s embedded creation timestamp shifting ZLIB output before encryption. Benign, and it is why B5 is load-bearing rather than ceremonial.

---

### 20.4 — Verification-method correction: cached passphrase is not recovery proof

**Recorded as a method finding, not a defect.**

GnuPG 2.x caches symmetric passphrases in `gpg-agent`. A decrypt that succeeds from cache proves the ciphertext is well-formed and proves nothing about whether the passphrase is held.

For a sole restore point, that distinction is the whole point. An artifact encrypted under a forgotten passphrase is worse than no artifact, because it presents as coverage.

**Rule.** Any decrypt-verify of a restore artifact must use `--no-symkey-cache`, and the operator must confirm a prompt appeared and was answered from memory. Absent that confirmation, the step is incomplete.

Same family as vol. II §14.7, where a TOC listing was mistaken for proof of restorability. Different claims require different tests.

---

### 20.5 — FR-DOC-REG-1 — NEW. Findings Register is two disjoint volumes with a Section 14 collision

**Issue Summary**

A heading-level `Compare-Object` between `Findings_Register_v12_2.md` and `Findings_Register_v17.md` returned **every heading from both files**. `Compare-Object` emits only differences. Zero shared headings.

Sections 1–13 exist only in v12_2: the fifteen money-model rulings, the five-spec split, the locked build order 1 → 2 → 3 → 5 → 4, Spec 2's Opus Math Review dispositions, Passes 1–5, the consolidated audit package. None of it is in v17.

The tracked lineage v14 → v15 → v16 → v17, entering Git at `9ff096b`, is a **continuation volume** that begins at Section 14. So the half of the register governing the money path has no verified Git provenance, and the half with provenance does not govern the money path.

Both files contain a Section 14 with different content. v12_2's is the Foundation Correction Plan Opus dispositions. v17's is the 07-23 security-remediation session. Both binding.

v17 carries dangling cross-references as corroboration: §15 supersedes Section 13, §17 supersedes Section 15. Section 13 is not in v17.

**Options**

| | Approach | Cost |
|---|---|---|
| A | Two-volume register. Citation convention now, renumber v17 to start at Section 20 at a later close. | Minutes now, mechanical later |
| B | Merge into a single v18. | ~130KB of register surgery, one session |
| C | Leave it, cite by filename. | Free, collision recurs |

**Recommendation & Reasoning — RULED: Option A**

B is correct and could not happen today without displacing the authorized Phase B work, and a merge that large invites the cross-section drift the composition-review rule exists to catch. C leaves a live trap: any future bare "Section 14" citation is ambiguous, and ambiguity in a binding document is the mechanism by which a retired mechanic like Worst Beat stays funded.

**In force immediately:** cite as **vol. I §N** (v12_2, Sections 1–14) or **vol. II §N** (v17, Sections 14–19). Never a bare section number. This Section 20 append is the first step of the renumbering.

**Open sub-questions, non-blocking:**
- Is `Findings_Register_v12_2.md` tracked, untracked, or `.gitignore`-swallowed? It did not appear in `git status` untracked output and is not the tracked path. `git log --all -- <path>` and `git check-ignore -v` pending.
- Does v17 hold anything below Section 14? Expected no; grep pending.

**Related observation.** Register filenames do not track content or succession. v10 is 14KB, v13 is 12KB, v12_2 is 70KB, v17 is 60KB. Some are full registers, some are session deltas, and they share a naming scheme implying succession. A reader taking the highest number gets the right file by accident. Tracked history starts at v14; v13 and below have no Git provenance.

---

### 20.6 — FR-PROC-CLIP-1 — NEW, CLOSED by design change. `Get-Clipboard` without `-Raw` silently corrupts multi-line values

**Issue Summary**

The DSN transfer step in the 07-25 handoff §6 reads `$env:DATABASE_URL = (Get-Clipboard).Trim()`.

Without `-Raw`, `Get-Clipboard` returns a **string array** — one element per line. `.Trim()` then applies via member enumeration, per element, returning an array. Assigning an array to an environment variable stringifies it, **joined with spaces**.

Newlines become spaces. The result is a single-line string of plausible length that passes casual inspection and fails anchored validation. Measured: 128 characters, whitespace present, no `postgresql://` prefix, `hayabusa` present, `=` present, line count 1.

This defect shipped in the handoff block and is a candidate cause for one or more of the three 07-25 Phase B failures.

**Recommendation & Reasoning — CLOSED, superseded**

`-Raw` is the minimal fix. The adopted fix is stronger: **remove the clipboard from the credential path entirely** via `railway variables list --service Postgres --environment production --json`, captured into a variable and never printed. See opener for the block.

The clipboard was also the vector that put a DSN in the transcript three times on 07-25 and the shared channel for transcript-sharing during the same session. Eliminating it is structural, not disciplinary.

**Corroborating evidence for the gate design.** The malformed string passed `-match 'hayabusa'`. Only the anchored shape check — prefix, no whitespace, anchored host/port/database — rejected it. Substring validation would have admitted it to `pg_dump`, which is what happened on 07-25. **The anchored gate is sound and stays.**

---

### 20.7 — FR-INFRA-DOCK-1 — NEW, OPEN. Undocumented container shares the protected 5433 bind

**Issue Summary**

Docker Desktop shows two containers on `postgres:16`, both mapped `5433:5432`:

- `pg-fantasy-test`, `f34c34e847ff`, **running**, 2 days. Database `fantasy_test`. Protected for FR-VAL10-ac's serialization proof.
- `fb-test-pg`, `58e009fb95bf`, **stopped**, 6 days. **Appears in no artifact held.**

Two containers cannot bind 5433 simultaneously, so nothing is currently broken. The exposure is that starting `fb-test-pg` either fails on the bind or — worse — a test harness pointed at `localhost:5433` reaches a database nobody documented.

**Risk class.** Identical in shape to the Guard 5 defect (vol. II §19.4): a safety mechanism aimed at the wrong target. Guard 5 compared the harness destination against a dead foreign address. A harness trusting `5433` trusts a port with two possible occupants.

**Recommendation & Reasoning**

Classify before acting. Inspect `fb-test-pg`'s database contents and creation provenance, then remove it or document it. **Do not start it** — that is the one action that could produce a wrong-target connection.

Deferred. Does not gate the desync procedure or rotation. Should be closed before FR-VAL10-ac's serialization proof runs, since that work depends on 5433 resolving unambiguously.

---

### 20.8 — FR-SEC-DB-5 — NEW, OPEN, UNVERIFIED. Unencrypted repository archive may carry pre-rotation credentials

**Issue Summary**

`C:\FantasyBeefs_Backups\fantasy-beefs_9ff096b.zip`, 25,991,636 bytes, dated 2026-07-24. Unencrypted. Sitting beside the encrypted database artifacts.

`c353d2b` removed hardcoded production connection strings from the working tree but **not from Git history** — that is the standing FR-SEC-DB-1 position. So if the archive contains `.git`, it carries those credentials regardless of which commit it was cut from. 26MB is consistent with `.git` inclusion.

If confirmed, this is a plaintext production credential in an unencrypted file — the same class as FR-SEC-DB-3.

**Not asserted.** Two commands settle it:

```
git merge-base --is-ancestor 9ff096b c353d2b
$LASTEXITCODE
cmd /c "cd /d C:\FantasyBeefs_Backups && tar -tf fantasy-beefs_9ff096b.zip" | Select-String -Pattern "^[^/]+/\.git/" | Measure-Object -Line
```

Nonzero from the counter means `.git` is present.

**Recommendation & Reasoning**

Verify before ruling. If `.git` is present, the archive is credential-bearing and must be encrypted or deleted — and rotation makes the embedded credential worthless, which is a further argument for completing FR-SEC-DB-1 rather than a reason to defer this.

Note the archive is **outside OneDrive**, so it is not syncing. That bounds the exposure to this machine.

---

### 20.9 — Verified tool and platform facts

**GnuPG.** `C:\Program Files\Git\usr\bin\gpg.exe`, version 2.4.5, libgcrypt 1.9.4, MSYS2-built, home `C:\Users\frase\.gnupg`. **The only `gpg.exe` on the machine** — established by recursive scan of both Program Files trees. By elimination, it produced the 07-23 artifact. Not on PATH; invoke via a session variable and the `&` call operator. AES256 present in supported ciphers. `gpgconf.exe` co-located.

**MSYS path caution.** Windows absolute paths pass through untouched. POSIX-style paths get rewritten — that is what turned `/backup/...` into `C:/Program Files/Git/backup/...` twice on 07-23. Use `C:\...` form exclusively with this binary.

**No permanent PATH edit was made.** A session variable was used. A PATH change is a system configuration change requiring separate authorization.

**Railway CLI.** 5.6.2 installed, 5.28.0 available. **Upgrade deliberately deferred** — a version change mid-security-sequence is an unmeasured variable.

`railway variables --help` flag surface read from the installed binary, not documentation: `--service`, `--environment`, `--project`, `--kv`, `--json`, `--set`, `--set-from-stdin`, `--skip-deploys`. The CLI's own automation note warns that JSON and KV output include raw values and that output from secret-bearing commands should not be shared.

**Linked service is `fantasy-beefs`, not `Postgres`.** `--service Postgres` is mandatory, not optional. Environment `production`, ID `6583038e-fe0a-4c31-a059-4885c4dec6b3`. Project `e8904b9e-a49c-47e8-a1c5-bb6d74118051`. Service `fantasy-beefs` ID `9400fc77-6050-4f34-b6a2-d5a2f963716a`, region `sfo`, status Online.

**`Postgres` service variables — 28 keys, names only.** `DATABASE_PUBLIC_URL` present and **not sealed**, length 87. `DATABASE_URL` resolves `postgres.railway.internal` and is unreachable from the ThinkPad.

**New instrument for post-rotation verification:** `RAILWAY_TCP_PROXY_DOMAIN` and `RAILWAY_TCP_PROXY_PORT` are the proxy's own record of itself. Better truth source than any document for confirming proxy survival. Values are not secrets.

`PGPASSWORD` and `POSTGRES_PASSWORD` both exist on the service. A JSON capture holds the production password twice; scrub the capture variables after the dependent step completes.

**Docker.** Desktop engine 29.6.1. `postgres:18` image cached locally — no pull needed. `--rm` containers cannot collide with the protected `pg-fantasy-test`.

**Railway UI behavior confirmed by search this session.** Sealed variables display as bullets, are write-only, cannot be un-sealed, and are excluded from CLI output, PR environments, service duplication, and sync diffs. Variable values may span multiple lines via Control+Enter or the Raw Editor. Neither applied here, but both are live failure modes for clipboard-based transfer.

---

### 20.10 — Process rules ESTABLISHED or EXTENDED

**Endpoints are not history.** A rename arrow in a range diff (`A.md => B.md`) is an endpoint pair produced by rename detection, not a chain. Claude read `v15.md => v17.md` as history and concluded v16 was never tracked. `git log --follow -- <path>` showed the real chain: v14 → v15 → v16 → v17. Same family as the ancestry rule from 07-25 — endpoints do not prove a path.

**Recon before premise applies to the date.** Claude asserted the current date was 07-26, inferring it from the 07-25 opener's filename, which was named for the session it opens. The HEAD commit timestamp, the dump's `LastWriteTime`, and the system clock all read 07-25. Claude used the wrong date to rename a backup artifact **in the same message where it explained why a wrong date on a backup is a trap**. Corrected before encryption. Cheapest available fact, unchecked.

**Opener naming convention CHANGED.** Openers are named for the date they were **authored**, not the session they open. The old convention supplied the wrong date to a downstream reader.

**Destructive cleanup goes in its own turn**, issued after the prerequisite is confirmed consumed. Claude shipped `Remove-Variable raw, obj` in the same block as the assignment that depended on `$obj`. The scrub ran, the assignment did not, and `$obj` was gone. One round trip lost, no harm.

**A reviewer's characterisation of a document is a claim to verify, not accept.** An independent review this session asserted the "B2 through B7" block was not present in retrievable materials and offered a five-step reconstruction. The block was §6 of the 07-25 handoff, retrieved at session open, and it has six steps. The five-step summary **dropped B7, the offsite copy** — the single step addressing the sole-restore-point condition the register had already flagged in vol. II §19.7. Accepting the review would have reproduced the exact condition it was meant to guard against.

The same review correctly caught that "six outputs" was a Claude invention with no provenance in any artifact. Both halves are recorded: the reviewer found a real fabrication and asserted a false absence in the same message.

**Pre-registered interpretation earned its keep, four times.** Claude formed four wrong hypotheses about the malformed DSN — clipboard collision with transcript text, keyword/value conninfo, a `psql` command line, and a sealed variable. Each was killed in a single probe round by a table written before the probe ran. The guesses were wrong and cost little because the tests were pre-committed.

**Minimize shell switching.** Claude proposed delegating B3 to Claude Code on the grounds that it needs no credential, then withdrew it. B3 is three lines; the upside of delegation is near zero and the downside is the MSYS path-rewriting failure that cost two cycles on 07-23. Claude Code earns its keep on multi-file document work with no secrets and no shell-state dependency.

**Diligence can eat the work.** Four consecutive turns of document-integrity recon ran before Phase B began, while production had no fresh restore point. Each check was individually cheap and individually justified. The aggregate displaced the authorized task. Recon that does not gate the authorized work should be deferred to the point where it does not compete with it.

---

### 20.11 — RULING-BUILD-1 — build authorization model replaced

Requested by Fraser this session. The former "no builds without explicit authorization" rule bundled four distinct risks under one gate.

**Gate is reversibility, not productivity.** Mechanical, not a judgment call — Claude does not assess whether a build is "productive," which would be Claude grading its own homework.

**Green, no authorization:** working-tree code, tests, local Docker, scratch scripts, spikes, refactors. Anything `git checkout --` undoes.

**Gated, explicit authorization each time:** `git commit`, `git push`, migrations, `railway up --service fantasy-beefs`, money-path code shipping.

**Unchanged:** Opus Math Review is a hard gate on all money-path code. Never `git add .` on a money-path commit. Separate commits for distinct defects. Production changes commit first, regression tests as a separate commit.

Claude states what it is about to build and why before building — one sentence, not a gate, and the mechanism for catching a wrong problem before 400 lines are spent on it.

**Practical effect today: none.** Every build item sits behind the security stage. Spec 2 waits on FR-AC-ISO-1, which waits on foundation deployment, which waits on FR-8.7 closure, which waits behind rotation.

---

### 20.12 — Gate status changes from this session

| Item | Before | After |
|---|---|---|
| Phase B | Authorized, attempted, incomplete | **COMPLETE** |
| Verified restore point | 07-23 only, cache-verified | **07-25, cache-bypass verified, offsite** |
| FR-SEC-DB-1 dump precondition | Unsatisfied | **Satisfied** |
| FR-SEC-DB-1 steps 8–11 | Blocked on dump | Blocked on desync procedure only |
| Phase C | Gated | Gated, unchanged |
| Desync procedure | Not drafted | Not drafted |
| Physical offsite copy | Not done | **Still not done** |
| FR-DOC-REG-1 | — | Ruled, cleanup deferred |
| FR-PROC-CLIP-1 | — | Closed by design change |
| FR-INFRA-DOCK-1 | — | Open, unverified |
| FR-SEC-DB-5 | — | Open, unverified |
| Build authorization | "No builds" | **RULING-BUILD-1** |
| Railway CLI upgrade | — | Deliberately deferred |
| FR-8.7 closure | Six items | Six items, unchanged |
