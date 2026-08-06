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

> **SUPERSEDED on the deployment mechanism — see vol. II 23.3.** The
> paragraph below is preserved as historical audit evidence.

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

---

## Section 21 — 2026-07-25 session 3 measurement session

**Session shape:** measurement session. Zero production mutations. Zero commits. Nine artifacts drafted, none authorized.

---

### 21.1 — FR-SEC-DB-6 — NEW, VERIFIED. No vendor password recovery at any tier; Hobby has no guaranteed support response

**Issue Summary**

Railway's support documentation places Trial, Free, and Hobby on community support through Central Station, with employee participation possible and **responses not guaranteed**. Pro gets direct help, usually within 72 hours, plus private threads. Ordinary support is not an email channel.

At **every** tier, Railway has stated publicly that they do not offer password recovery services, and that a password set through SQL is stored in a form their support team cannot retrieve. A Hobby user posting the exact desync-lockout scenario was not given a reset.

**Consequence**

"Stop and escalate to Railway support" is not a recovery step. It is a place to wait. Escalation is informational, never a dependency.

Pro is worth buying for whatever backup and PITR capability is **verified on this workspace** — see 21.9 — and for private threads. Not for a password reset. No tier provides one.

---

### 21.2 — FR-SEC-DB-7 — NEW, VERIFIED. Railway SSH is database-administrative independent of the PostgreSQL password

**Statement**

> Railway SSH authorization is database-superuser-equivalent on this service. A registered SSH key reaches OS root; the container receives the live PostgreSQL credential through `PGPASSWORD`; and Unix-socket HBA trust independently permits passwordless access as `postgres`. Rotating the PostgreSQL password revokes neither path.

**Evidence, measured 2026-07-25**

- `railway ssh --service Postgres --environment production whoami` → `root`
- `env -u PGPASSWORD psql -h /run/postgresql -U postgres -w -Atl` → database list. Credential removed, prompting disabled, access survived. **Socket trust proven by removal, not inferred from the file.**
- The same command **without** `-h /run/postgresql` → `fe_sendauth: no password supplied`, establishing that ambient TCP access depends on `PGPASSWORD` and that no `.pgpass` fallback exists.

**Provenance correction.** This is a **rediscovery**, not a discovery. The 2026-07-08 session already used `pg_dump -U postgres -h /run/postgresql railway` over the socket, documenting it as bypassing the broken external-auth path. Seventeen days of planning then designed a `pg_hba` trust-mode edit to obtain access the record showed already working.

**Consequence.** Railway account and SSH-key control must be treated as at least as privileged as the PostgreSQL password.

---

### 21.3 — FR-SEC-DB-9 — NEW, VERIFIED. Governing Railway rotation path is wrong

> **FR-SEC-DB-9 — Governing Railway rotation path is wrong.**
>
> Live production observation on 2026-07-25 established the actual control as **Postgres → Database → Config → Connection → Regenerate**. Current governing artifacts that specify **Database → Credentials → Regenerate** are incorrect. The bad path originated as a v15 "correction" to the v14 Config path; live observation shows v14 was right on that point. Rev 8 of the rehearsal and Rev 4 of the desync procedure must use the measured path.

**Affected artifacts:** `FantasyBeefs_Architecture_v15_ChangeSpec_2026-07-25.md` §5 · desync procedure Rev 3 · rehearsal Rev 7 Mutation 1.

**Root cause.** The v15 correction was derived from Railway's documentation, which describes a Credentials tab. The deployed dashboard presents `Data · Stats · Config` under Database. **A documentation page is not a UI observation.**

**Also measured on that panel:**

| Fact | Value |
|---|---|
| Credential shown at rest | Yes — Username `postgres`, Password masked, with reveal and copy controls |
| Representation | **Password only.** No DSN anywhere on the panel |
| Control label | `Regenerate`, under a `Regenerate Password` heading |
| Warning text | *Breaks existing connections until they use the new password.* |
| Adjacent mutation controls | `Convert to HA`, `Add PgBouncer` — **prohibited during credential work** |
| Extensions installed | `plpgsql v1.0` only — restore-comparison baseline |

**On the warning text — do not overread it.** PostgreSQL does not re-authenticate established sessions against the role password. Whether Railway's Regenerate additionally terminates backends is **unmeasured**. The defensible statement:

> Regenerate is expected to disrupt dependent database connectivity because `fantasy-beefs` continues to hold stale value 4. New or recycled connections using that literal cannot authenticate after the role moves. Whether already-established sessions are terminated immediately by Regenerate remains to be measured.

The rehearsal's new M10 probe settles it.

---

### 21.4 — FR-DOC-V15-1 — NEW. v15's UI-derived claims lose their presumption of correctness

Scoped by **evidence type**, not blanket.

**Reclassified UNVERIFIED:** any v15 claim about dashboard navigation, tab names, or control labels. FR-SEC-DB-9 is one instance; others are unaudited.

**Standing:** v15 claims derived from CLI or API measurement — the deploy mechanism, the FR-DEPLOY-1 widening — since those were re-measured directly this session.

**Load-bearing item in the reclassified bucket:** the claim that Backups and PITR are Pro-gated, verified on both Backups tabs on 07-25. That is UI-derived and it underpins the entire restore-point argument. **Re-reading the live Backups tab is the first evidence item in the next session's queue.**

---

### 21.5 — FR-PROC-ALTER-1 — NEW. The "manual SQL failed previously" prohibition is unsourced

**Issue Summary**

Exhaustive literal grep across the project panel. Every document mentioning `ALTER USER` or `ALTER ROLE` is July 7–8 era — Master Plan v4, v5, v6, handoff v37, opener v37, the MVP roadmap — and **all of them describe the operation as queued and deliberately not executed**.

No document anywhere records an executed attempt.

The claim *"manual SQL — that path failed previously"* first appears in `fantasy_beefs_architecture_print_v14.html`, dated 7/23, two weeks after the deferral. It then propagates into the 07-25 opener, register v16, the 07-24 handoff, and the v15 change spec. Register v16 attributes it to the opener; the opener asserts it flatly. **Circular, and no carrier names the operation it prohibits.**

The only July 9 artifact contains zero occurrences of *rotation*, *password*, *credential*, or *D2*.

**Disposition**

> Prior project artifacts claim a manual SQL password-change failure, but no underlying executed attempt has been located. Earlier artifacts instead show the operation queued and deliberately deferred. The claimed historical failure is therefore **UNVERIFIED**, and the operation is presently **UNTESTED**.

**Caveat.** Absence in the panel is not absence in reality. Sessions between July 9 and July 23 may have artifacts outside the panel.

**Corroborating measurement.** `grep -rn POSTGRES_PASSWORD /usr/local/bin` inside the production container returns hits only in `initdb --pwfile`, `file_env`, validation warnings, and an init-block `PGPASSWORD` export. `grep -rn ALTER` returns only `ALTER SYSTEM` and `ALTER DATABASE ... REFRESH COLLATION VERSION`. **No boot-time password reapplication exists in the image.** So `ALTER ROLE` should hold durably, and the historical failure has no in-container mechanism.

**Residual, not testable from inside.** Railway's control plane performs Regenerate from outside the container. If it ever re-asserts a password it believes correct, a socket-set value could silently revert. Unresolved; the rehearsal's T4a/T4b transitions probe it.

---

### 21.6 — 18.4 arrival is now bounded to a deployment

`Postgres` deployment `e1f535d9` created **2026-07-09T00:26:44Z**. Postmaster start **2026-07-09T00:27:47Z** — 63 seconds later.

> Production runs PostgreSQL 18.4, delivered by a deployment on 2026-07-09, not by a spontaneous image pull. Artifacts written after that date describing "upgrade production to 18.4" as a future action were stale. The actor that initiated the deployment remains unclassified.

Uptime at measurement: 16 days, no restart.

---

### 21.7 — FR-INFRA-CRLF-1 — NEW, VERIFIED. PowerShell stdin carries CRLF

`@'line1'@ | docker exec -i guardtest od -c` → `l i n e 1 \r \n`.

**Consequence.** Any construct requiring exact line-terminator matching is unsafe on this path. A nested shell heredoc fails: `sh` compares `SQL\r` against `SQL`, never terminates, and feeds the terminator line to psql as a statement — observed as `ERROR: syntax error at or near "SQL"`.

**Scope.** psql tolerates CRLF; every backslash command in the same run worked. **Plain `sh`-over-stdin remains valid and is not implicated.** Only exact-terminator constructs are affected.

**Retired:** nested shell heredocs over this transport.

---

### 21.8 — FR-INFRA-SSH-ARG-1 — NEW, VERIFIED. `railway ssh` joins argv and does not preserve grouping

`railway ssh ... sh -c 'echo A;echo B'` → `B` only. `railway ssh ... psql -Atc "SHOW log_statement"` → `database "log_statement" does not exist`.

`railway ssh` joins its positional arguments with spaces and hands the string to a remote shell, which reparses it. `echo a b c` returning `a b c` was consistent with joining and never tested grouping.

**Prohibition.** A credential must never pass through `railway ssh` argv — a `;`, `$`, or backtick in a generated password would execute remotely as root.

**Proven transports:** PowerShell here-string → stdin → `psql`, and PowerShell here-string → stdin → `sh` (no arguments, script wholly on stdin, quoting parsed by the container shell where it behaves normally).

---

### 21.9 — Measured infrastructure facts

**Both database services**

| Property | Value |
|---|---|
| Image | `ghcr.io/railwayapp-templates/postgres-ssl:18` — **not stock `postgres:18`** |
| Server | `PostgreSQL 18.4 (Debian 18.4-1.pgdg13+1)` |
| psql client | `18.4 (Debian 18.4-1.pgdg13+1)` — `\getenv` available |
| HBA file | `/var/lib/postgresql/data/pgdata/pg_hba.conf` — the published path, verified |
| HBA rules | 7 rows, lines 117–128, `error` null throughout, **identical across services** |
| Active rules | `local all all trust` (117) · `host all all 127.0.0.1 trust` (119) · `host all all ::1 trust` (121) · replication equivalents (124–126) · `host all all all scram-sha-256` (128) |
| Include directives | **None active.** `include`/`include_if_exists`/`include_dir` appear only in comments |
| Logging | `log_statement=none` · `log_min_error_statement=error` · `log_min_duration_statement=-1` · `log_min_duration_sample=-1` · `log_transaction_sample_rate=0` · `log_destination=stderr` · `logging_collector=off` |
| initdb.d | `99-pgbackrest-init.sh`, `init-ssl.sh` |

**Line 128 is stock.** The unaligned appended rule comes from the stock entrypoint's `pg_setup_hba_conf`, called only inside the initialization branch. An earlier inference that its formatting proved a non-stock image was **wrong**; the image is customized elsewhere — `wrapper.sh`, pgBackRest, `init-ssl.sh`.

**`logging_collector=off` with `log_destination=stderr`** means PostgreSQL writes to stderr, the container captures it, and Railway ingests it into the dashboard log store. There is no local logfile to rotate. A failed plaintext statement's text would land in Railway's retained logs — which is why mechanism A's PANIC guard exists.

**Service and volume identities**

| Resource | Service ID | Volume | Volume ID |
|---|---|---|---|
| `postgres-test` | `f03178f3-ecce-4a12-9d58-39125e41a161` | `postgres-volume-F_kl` | `9f491b83-81f5-4609-bcfd-7b223db06794` |
| `Postgres` | `cd0ba357-63dc-4c9e-800f-362b004246e7` | `postgres-volume` | `16983665-ead5-4225-9abf-7bfd29a08b96` |
| `fantasy-beefs` | `9400fc77-6050-4f34-b6a2-d5a2f963716a` | none | — |

`fantasy-beefs` has `source: null` — no connected source, reinforcing the `--from-source` prohibition. Latest deployment `7cc12e15`, created 2026-07-18T02:47:02Z. That yields no commit SHA — FR-DEPLOY-1 stands — but bounds the running tree to a July 18 upload.

`postgres-test` deployed 2026-07-23T07:26:36Z, during the security work and newer than `Postgres`.

**CLI surface, read from the installed binary (5.6.2)**

- `railway redeploy` — *"Redeploy the latest deployment of a service."* `--from-source` is the opt-in to pull new source; **the default touches no source**
- `railway restart` — *"Restart the latest deployment of a service (without rebuilding)"*; says nothing about variables
- `railway service delete --service <ID> --environment production` — exists; `--2fa-code` required non-interactively when 2FA is enabled
- `railway volume delete --volume <ID>` — exists
- **`railway delete` / `rm` / `remove` deletes the PROJECT.** One word from `railway service delete`

**Variable application resolution.** Use `railway redeploy --service fantasy-beefs --environment production`. Never `--from-source`, never `-y` during an incident, never `railway up` — `railway up` uploads a working-tree snapshot and would change running code as a side effect of fixing a password.

**FR-DEPLOY-1's Restart note reclassified.** It recorded that Restart picks up variable changes without a rebuild. That is a prior observation possibly involving an already-applied variable or older platform behavior. **Needs re-derivation.** The rehearsal's T4a/T4b settle it empirically.

**`postgres-test` size reconciliation**

> The 134.9 MB Railway volume metric does not represent 134.9 MB of live PostgreSQL database contents. Current `PGDATA` usage is 47 MB and both ordinary databases are 7,678 kB each. The source of the remaining accounting difference is unclassified.

The unexplained portion **inside** the 47 MB likewise stays unclassified. Production shows the same inflation: 221.6 MB reported against a 243,863-byte dump. **Do not read the Railway volume figure as evidence of stored data.** Table count remains the authoritative empty-service gate; size is a sanity check.

---

### 21.10 — Mechanism A — VERIFIED end to end on the bench

Local disposable `postgres:18`, psql `18.4 (Debian 18.4-1.pgdg13+1)` — client build identical to both Railway services.

| Property | Evidence |
|---|---|
| Blocks when the guard is unsatisfied | `ABORT-GUARD-NOT-ESTABLISHED`; verifier `ptQJH` **unchanged** |
| Blocks when `PGPASSWORD` is absent | `ABORT-PGPASSWORD-ABSENT`; verifier unchanged; `\q` exits cleanly |
| Permits when satisfied | `REPAIR-APPLIED`; verifier `ptQJH` → `2bXfm` |
| **Installs the intended value unmangled** | `guard1` authenticates over `172.17.0.3`, a path where `definitelywrong` is rejected |
| psql primitives | `\getenv` · `:{?newpw}` · `\gset` · `\if` · `:'newpw'` all exercised |
| Transport | Direct PowerShell here-string → psql stdin, no shell wrapper |

**The fourth row took four attempts and is the one that matters.** A changed verifier proves a statement ran, not that the intended credential landed — SCRAM re-salts on every set, so a mangled or truncated value moves it too. Only the authenticated round trip with its negative control distinguishes them.

**Shipping form** — no shell layer, so CRLF is irrelevant and no terminator exists to mismatch:

```
\getenv newpw PGPASSWORD
\if :{?newpw}
\else
\echo ABORT-PGPASSWORD-ABSENT
\q
\endif
SET log_min_error_statement = 'PANIC';
SELECT lower(current_setting('log_min_error_statement')) = 'panic' AS guard_ok \gset
\if :guard_ok
ALTER ROLE postgres PASSWORD :'newpw';
\echo REPAIR-APPLIED
\else
\echo ABORT-GUARD-NOT-ESTABLISHED
\endif
```

Emptiness is gated upstream by a byte-count measurement, since `\getenv` leaves the variable set when the environment variable exists but is empty.

---

### 21.11 — New standing process rules

**Negative controls.**

> When a probe's success would look identical under a permissive path, it is not evidence until the same path has been shown to reject a known-invalid input.

Earned by measurement. A bench `SELECT 1` over `-h 127.0.0.1` returned `1` and proved nothing, because line 119 is `host all all 127.0.0.1 trust`. The identical output over `-h 172.17.0.3` became evidence only after a wrong password was shown to fail on that same path. Applies to authentication, authorization, and signature or hash verification. Not to configuration reads.

**Non-mutating production inspection is GREEN.** Closes the RULING-BUILD-1 classification gap.

> Non-mutating production inspection is GREEN when the exact command and target are named beforehand, it alters no filesystem, process, configuration, database, network, deployment, or credential state, and its purpose is diagnostic verification of a precondition.

Green: `railway ssh ... echo` · `railway ssh ... cat <verified-path>` · `railway variables list` · reading logs · an authenticating `SELECT`. Not green, and not made green by arriving over SSH: `sed -i` · `ALTER USER` · package installation · file mutation · redeploy, restart, or `railway up` · network changes · an interactive shell with unspecified actions.

**No second credential mutation.**

> No second credential mutation while the result of the first credential mutation is unresolved. Preserve every candidate credential. Diagnose the resulting state first.

**Credential transport.** Never pass a production credential in a local CLI argument or a `-e NAME=value` flag when it can remain inside the remote or container environment. Bench values reached PSReadLine history via `docker exec -e`; the production design keeps `$PGPASSWORD` inside the container for exactly this reason.

**A failed diagnostic proves nothing until the diagnostic is calibrated.**

**Counts in documents are a drift generator.** Name instruments — "M1–M8" — never "all seven." A count goes stale the moment an instrument is added; a name does not.

**Read the live UI, not the documentation.** FR-SEC-DB-9 originated in a doc page describing a surface the deployed dashboard does not present.

---

### 21.12 — Composition-drift tally

Eight instances this session, all one shape: a careful local section written correctly, then a downstream section written from memory of the pre-edit state rather than derived from it.

1. Desync Rev 1 — options table contradicted itself two rows apart
2. Desync Rev 1 — classification table could not use its own discriminator
3. Desync Rev 2 — axis 2 too coarse to prove what it claimed
4. Desync Rev 2 — §10 branching contradicted §1.2
5. Rehearsal Rev 2 — prose described a program different from the code beneath it
6. Rehearsal Rev 3 — §3.3 contradicted its own matrix
7. Rehearsal Rev 5 — "all seven" left stale after M8 was added
8. Rehearsal Rev 6 — M1's changed semantics ignored by the password-only branch

**Structural mitigations adopted:** derivation tables instead of prose summaries · instruments named, never counted · one-row-per-state branch tables mirroring the state definition exactly.

---

## Section 22 — 2026-07-30 → 2026-08-01: Pool catalog Rev1.1, FR-8.7 test 6d progress, Pool settlement findings, and Pool authorization

**Checkpoint:** `c60f73a7e38dae0c4a3af794320f858c745df6cf` · branch `remediation/foundation-phase-1` · HEAD equals origin.

**Sources folded.** Five, listed with provenance:

| | Source | Status |
|---|---|---|
| A | `FantasyBeefs_Findings_Register_Delta_2026-07-30.md` | untracked working tree · destination retargeted from v16 to v17 |
| B | `FantasyBeefs_Findings_Register_Delta_2026-07-31.md` | untracked working tree |
| C | `FantasyBeefs_Findings_Register_Delta_2026-08-01.md` | panel-only, not on disk |
| D | `spec/POOL_SETTLEMENT_FINDINGS_2026-07-30.md` | **tracked** · preserved unchanged as dated evidence |
| E | Current-session rulings | integrated into the findings they update, not listed separately |

Source D is preserved unchanged by this consolidation and receives no superseded marker. It set its own fold condition — *"Fold them into the register once its authority is settled"* — and that condition is satisfied by FR-DOC-REG-1. **This section is the register authority for FR-POOL-1 and FR-POOL-2.** Source D remains the dated evidence they were derived from, including its Rev1.0 product-authority pointer, which is historical provenance and is not to be rewritten.

Sources A, B, and C function as pending append instructions in this consolidation. Whether such delta artifacts are governed to remain untracked is unresolved under candidate FR-DOC-DELTA-1.

---

### 22.1 — FR-8.7-LOG-7 — NEW, OPEN. WalletMovement reports a payout against unchanged balances

`SettlementReport.WalletMovement` reports a real payout while its before and after balances are identical. Both read `Wallet.balance`, which the legacy float settlement correctly never writes.

Same family as LOG-5, distinct instance. LOG-5 computes the payout wrong. LOG-7 sources the balances wrong.

Open, uninvestigated. Routed to B2.

### 22.2 — FR-8.7-TEST-1 — NEW, OPEN. The shared fixture cannot discriminate the payout path

The $25/$40 at 2.60-odds fixture yields 65.00 under both actual-escrow payout and `amount × odds`. Every 6500 assertion across 6d-2, 6d-3, and 6d-5a is therefore blind.

The ledger is structurally safe — a three-leg posting must sum to zero. Report and feed surfaces are not.

Discriminating variant for LOG-5's regression test: stake 25.00, odds 3.00, opponent 40.00. Wrong path yields 75.00, right path 65.00.

Open. Routed to B2.

### 22.3 — FR-8.7-TEST-2 — NUMBER ASSIGNED this session. PARTIAL. Vacuous-on-empty assertions

6d-6 assertions 22 through 25 would have passed against an empty serialization: `token not in ""` is True, and `findall("")` returns `[]`. Guarded before commit with a hard `RuntimeError` precondition rather than a 45th assertion.

The same class may exist in 6d-1, 6d-2, 6d-3, and 6d-5a. Never checked.

Fixed in 6d-6. Unaudited in the four siblings. The number was proposed in source A and is assigned here.

### 22.4 — FR-8.7 test 6d — status

Five of eight execution units green: 6d-1, 6d-2, 6d-3, 6d-5a, 6d-6.
Remaining: 6d-5b, 6d-4, 6d-7 — all isolation-gated behind FR-AC-ISO-1.

Assertion counts, source-counted, labels 0-indexed and contiguous:

| Unit | Sites |
|---|---|
| 6d-1 | 19 |
| 6d-2 | 20 |
| 6d-3 | 25 |
| 6d-5a | 37 |
| 6d-6 | 44 |
| **Total** | **145** |

Prior figures of 97 and 37/37 were low by one per suite. Zero-indexed labels with assertion 0 scrolled off truncated console tails. Systematic, not random.

### 22.5 — Amendment: 6d-6 coverage boundary

The frozen 6d-5/6d-6 expectation that a no-token normal caller is refused at `settlement_engine.py` 479–482 is **incorrect for sequential execution.**

Both refusals reachable without concurrency are pre-lock bare raises: 397 for no token supplied, 407 for token mismatch. The `SELECT … FOR UPDATE` sits at 437–444. The under-lock revalidation guards' refusal branches require a concurrent state change between the pre-lock read and the locked re-read, and belong to 6d-4, 6d-5b, and 6d-7. 6d-6 Phase E passes through the under-lock revalidation on its admit branch only.

Corrected wording is committed in the 6d-6 module docstring and repeated above its Phase D.

### 22.6 — Carried observations — not findings

- The one-file-per-process rule for the 6d suites holds, but its stated cause is unverified. The observed failure was the empty-database ownership guard after a stranded schema, not a Guard 5 destination collision.
- `_SAFE_URL` in `test_support_crash_selftest.py` is port 5432 against a 5433 Docker instance. Guard-passing syntax only. No connectivity is claimed.
- `_balance_of_in_session` populates `escrow_accounts_verified` only where `beef_challenge_id is not None`. Straight wagers contribute no escrow evidence to the recovery audit. May be correct by design.
- `recover_week`'s JSON-serializability guard at 905–911 is unreachable through the crash harness by construction. Not a defect. Recorded so no later document claims coverage.
- The 6d-6 docstring states 6d-5a's magnitude assertion is sound because its sibling context pins the intent. That is softer than FR-8.7-TEST-1. Reconcile the committed comment when TEST-1 is actioned.

---

### 22.7 — FR-POOL-ROLL-1 — CLOSED by `53fe0ba`. Rollover eligibility misclassified for #84 and #87

Rev1.0 marked 19 definitions rollover-eligible. The non-rollover 75 were 73 RANK_EXTREMUM plus 2 QUALIFIER: #84 `matchups_where_neither_team_lost_a_fumble` and #87 `matchups_with_zero_total_turnovers`.

**Cause.** `FR-6_1_CATALOG_CLASSIFICATION.md` assigned rollover eligibility by section — §1 Milestone & Achievement, 12 rows, and §12 Binary Qualifier Pools, 7 rows, each marked all rollover-eligible. `evaluator_family` was assigned later by bet shape. The two methods were never reconciled. #84 and #87 are QUALIFIER-shaped bets sitting in §11 Turnovers, outside both blanket-marked sections.

Arithmetic closes: 21 QUALIFIER = 12 + 7 + 2 strays.

**Inherited, not introduced.** Handoff v43 states 19 rollover-eligible and "the other 77 are rank-based" at 96 rows. Retiring #57 and #96 turned 77 into 75. The miscount rode through three artifacts unchanged.

**RULING (Fraser, 2026-07-31):** rollover eligibility follows evaluator family without exception. RANK_EXTREMUM `false`, QUALIFIER `true`. #84 and #87 are metadata defects, not governed exceptions.

Rev1.1 sets both to `true` and the declared count to 21. Rev1.0 preserved byte-for-byte. Guarded permanently by `test_pool_catalog_invariants.py` assertions 2, 3, 4, and 5.

Supersedes carried finding 7 from the 07-31 opener, which raised this as an open product question.

### 22.8 — FR-POOL-POR-1 — CLOSED by `53fe0ba`. POR stated the wrong derivation twice

`SPEC_Pool_Catalog_Rotation_POR_Rev1_0.md` carried the section-based derivation in two independent places: line 39 as a table cell, Section 5 as prose. Correcting one and missing the other would have left the document internally contradictory.

Rev1.1 corrects both. Line 39 reads 21, All QUALIFIER. Section 5 is rewritten to derive eligibility from evaluator family.

### 22.9 — FR-POOL-POR-2 — NEW, CLOSED by `53fe0ba`. POR Section 10 table was a third unswept location

The approved edit plan covered four POR changes: pointers, supersession, the line 39 count cell, and the Section 5 prose. It missed the Section 10 catalog table, which carries an RO column across all 94 rows and encoded 19, with #84 and #87 blank.

Executing the plan as written would have produced a Rev1.1 stating 21 at line 39, 21 in prose at line 140, and 19 in the table. Internally inconsistent on its face — FR-POOL-POR-1 firing a second time inside the document meant to remediate it.

Caught during pre-execution review. Lines 325 and 328 set to `Y`. Guarded permanently by assertion 10, which parses the Section 10 table and compares it row by row against the JSON.

### 22.10 — FR-POOL-SCOPE-1 — CLOSED by `53fe0ba`, git-verified. §I step 8 wording debt

**Closure determined this session. No source delta recorded it.**

§I step 8 read "Seed 85 rotatable definitions" while §C1 read "94 rows seeded." The committed schema carries `dependency_state` ENABLED|BLOCKED and `block_reason`, so 94 rows with 9 excluded is fully supported. Seed-scope wording only — not a product decision, database blocker, or count conflict.

**Verification.** `HEAD:spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_1.md`, 278 lines. §I heading at line 238, §J heading at line 263, each unique. Within that bounded range, exactly one row matched `^\|\s*8\s*\|`:

    | 8 | Seed all 94 active definitions — 85 `ENABLED`, 9 `BLOCKED` and excluded from rotation | no | — |

Read from tracked HEAD, not from the project panel. Closure confirmed.

**Method note.** Two earlier probes failed before this one succeeded. The first matched row 8 in both §H and §I, because both tables number from 1. The second bounded the start at §I but left the end at end-of-file. Only the §I-to-§J bounded slice produced a single unambiguous row. Recorded under FR-PROC-SWEEP-1.

The 08-01 delta's CLOSED list omitted this finding. Also recorded as an FR-PROC-SWEEP-1 instance: a closure sweep that covered the findings named in the edit plan and missed one the same commit also resolved.

### 22.11 — FR-POOL-SCOPE-2 — NEW, CLOSED by `53fe0ba`. Scope line 22 stated 19 alongside 21

`SPEC_Pool_Rotation_Implementation_Scope_Rev1_0.md` line 22 read "85 rotatable, 19 rollover-eligible, 2 evaluator families, RANK_EXTREMUM 73 and QUALIFIER 21" — contradicting itself eight words apart.

Not in the approved edit plan. Caught during pre-execution review. Rev1.1 reads 21.

### 22.12 — FR-POOL-TITLE-1 — NEW, CLOSED by `53fe0ba`. Both Rev1.1 titles still declared Revision 1.0

The plan's pointer sweep used the filename token `rev1_0`, blind to the prose form. POR line 2 and Scope line 1 both read "Revision 1.0." Each file would have declared itself Revision 1.0 on its title line and Revision 1.1 in a supersession block two lines below.

Caught during pre-execution review. Both corrected. Both Date lines updated to 2026-08-01 by ruling.

### 22.13 — FR-REPO-CRLF-1 — NEW, CLOSED by `002ea4a`. core.autocrlf could rewrite governed catalog files to CRLF

`core.autocrlf` is `true` from system config. `git ls-files --eol` measured `attr/` empty on both `pool_catalog_rev*.json` files, so the next checkout, reset, stash, or branch switch would have rewritten them to CRLF and broken the working-tree Rev1.0 hash fence until the files were restored byte-for-byte.

The pre-existing `.gitattributes` rule `spec/*.md text eol=lf` already covered all four governed Markdown files. Only the two JSON files were exposed. The originally proposed exposure was overstated.

Remediated by appending `spec/pool_catalog_rev*.json text eol=lf`. Verified: no tracked-file renormalization occurred, both JSON files report `i/lf w/lf attr/text eol=lf`, all three Rev1.0 hashes intact.

### 22.14 — FR-REPO-CRLF-2 — OPEN, not blocking. The protector is itself unprotected

`.gitattributes` and repo-root Python remain subject to platform line-ending conversion. Neither is currently governed by a byte-level hash requirement, so this is a consistency and future-proofing issue, not an active authority-integrity failure.

`.gitattributes` now pins six governed spec files to LF but carries `attr/` itself, and `git add` warned on it during `002ea4a`. Repo-root Python sits outside every pattern; the same warning fired on `test_pool_catalog_invariants.py` during `c60f73a`.

Resolvable later as its own scoped change. Deliberately excluded from `002ea4a` to hold that commit to one path.

### 22.15 — FR-PROC-SWEEP-1 — OPEN, process. Token sweeps find filenames, not meaning

FR-POOL-POR-2, FR-POOL-SCOPE-2, and FR-POOL-TITLE-1 share one cause. The edit plan swept for the token `rev1_0` and treated the result as complete. That grep cannot see the prose form "Revision 1.0," cannot see a stale count 19, and cannot see a blank cell in a table column.

Three defects, three disguises, one missed pass. All three were caught only because the target text was read before being written to.

**Standing rule proposed:** a revision sweep is not complete until it covers filename tokens, prose revision references, every restated count, and every table column encoding the changed property. Token match is a starting point, never a completion criterion.

A related failure occurred inside the same session's validation block. A hardcoded index `[21]` was written against pre-insertion line numbering while the same document ordered an insertion two lines above it. The check could only pass if the insertion were skipped. Replaced with a content-anchored assertion rather than renumbered — renumbering resets the same trap.

**Extended this session.** Four further instances, all arising during this register consolidation:

1. A `git show` probe against an assumed `spec/` path returned exit 128 while five token counts read 0. The empty variable made every count vacuous. A positive-control token and an emptiness guard were added; the corrected probe returned control count 2. **Standing rule: every absence probe carries a token that must be present.**
2. `git ls-files | Select-String 'Findings_Register'` returned two entries and both 07-30/07-31 deltas were absent from it. That absence was read as presence. Direct `git ls-files --error-unmatch` returned `TRACKED=False` for both. **Standing rule: absence from a filtered listing is not evidence. Ask the index directly.**
3. A Step 8 probe matched two rows, because §H and §I both number their tables from 1, and a subsequent fix bounded only the start of the range. **Standing rule: bound a structural slice at both edges by unique anchors, and assert the expected match count before reading the value.**
4. The 07-31 delta's "all seven measurable fields" was carried forward into later documents after `c60f73a` replaced hand-counting with an automated nine-key control. **Standing rule: when a control is added over a previously hand-measured quantity, re-derive every prior figure from the control.**

### 22.16 — FR-POOL-H15-1 — OPEN. §H trial-balance wording

§H states every scenario asserts trial balance zero, including pure-evaluator scenarios 14, 15, and 16. Existing pure tests prove evaluator behavior. A future integrated §H scenario may still want a no-ledger-movement assertion. Not resolved. Does not invalidate existing tests.

Step 15 harness-design clarification.

### 22.17 — FR-POOL-H19-1 — OPEN. Scenario 19 conflates two unreachability claims

Scoping precision, not a defect.

§H scenario 19 covers four items with two truth conditions. #57 and #96 are absent from the active catalog. `bench_burn` acceptance was retired at `13b4fef`. **The Lineup is retired from Pool scope while a live single-party `Bet.bet_type` settled by `settlement_engine._eval_the_lineup` still exists outside it.**

A test proving Pool-scope unreachability proves nothing about the legacy path. Connects to existing single-party retirement work. The claim is the catalog's; `settlement_engine.py` was not read.

### 22.18 — FR-POOL-DEP-1 — WITHDRAWN 2026-07-31. Do not record as a finding

Hypothesis: ENABLED QUALIFIER rows with null `metric_expression` are enabled-but-unexecutable, making `dependency_state` an insufficient draw guard.

**Wrong at the layer.** `metric_expression` is the RANK_EXTREMUM carrier. QUALIFIER governs through `threshold_condition`. A null expression on a QUALIFIER is the family's designed shape, confirmed by the catalog's own note: *"metric_expression is a declarative settlement basis, not implementation code."*

The real blocker was already recorded — step 6 needs structured predicate and threshold catalog fields authored. No `EVALUATOR_UNBUILT` state is authorized.

**Process note:** this re-derived a known blocker under a new name and pointed it at the wrong artifact. Cause: treating one evaluator family's contract as universal. `pool_definition` holds two families in one table; a null in a family-specific column proves nothing until the owning family is known.

### 22.19 — FR-PROC-PANEL-2 — CLOSED this session. Pool authority files absent from project panel

`git ls-files` confirmed all three Pool authority files tracked while none appeared in the project panel. A thread opening on Pool work and reaching for the panel found nothing and reconstructed intent from legacy sources.

**Closed by panel swap, verified 2026-08-01.** Rev1.0 POR, Scope, and catalog JSON are absent from the panel. All three Rev1.1 files are present.

**Provenance qualifier.** Verification is panel-side. The panel is the system this finding measures, so panel-side verification is sufficient for closure. No claim is made about repository file retention.

The finding's related clause cited 45 untracked files at repo root and in `spec/`. That count predates the three commits of 2026-08-01 and is not carried forward. The untracked-artifact exposure is recorded at 22.27 and remains subject to a separate read-only inventory.

---

### 22.20 — FR-POOL-1 — OPEN, money-path. Biggest Winner empty result reported as distributed

**Recorded, not fixed. Product ruling required. Opus-gated before implementation.**

Source: `spec/POOL_SETTLEMENT_FINDINGS_2026-07-30.md`, preserved unchanged. Line references are evidence dated 2026-07-30 — re-grep before implementing.

**Location.** `betting/pool_engine.py` · `settle_pool` · evaluator `_biggest_winner` at approximately 419–446, accounting at approximately 782.

**Behavior.** `_biggest_winner` returns every team tied at maximum wins. When no matchups produce a result the list is empty, `_split_even([], ...)` returns `{}`, no `_credit` call fires, and no ledger posting occurs. The Biggest Winner pot is never paid. `bw_share_cents` is nonetheless added into `total_distributed_cents`.

**Ledger remains conserved.** Nothing was posted, so conservation holds and trial balance remains zero. The defect is in reporting.

**Reported distribution is false.** `PoolSettlementResult` reports a distribution that did not happen. Any consuming surface — settlement report, feed, commissioner reconciliation — states that money moved when it did not. Same family as FR-8.7-LOG-5 and FR-8.7-LOG-7: the ledger is right and a derived surface is wrong.

**Stranded cents and reconciliation interaction remain unresolved.** The pot balance is neither swept nor carried, so cents are stranded in `pool:{league_id}` with no lineage record. A later week's reconciliation guard at approximately 562–595 computes against expected balances and may or may not surface the discrepancy. Not investigated.

**Minimum reproduction.** A league/week where the evaluator returns an empty set — no `Matchup` rows, or no matchup with a determinable result — with a funded pot. Assert `total_distributed_cents` against actual `wager`-door postings, not against the reported figure. The fixture must be discriminating: reported and actual distribution must differ. A zero pot proves nothing.

**Why separate from rotation.** Rotation changes which definitions run and how the pot is divided. It does not change what an evaluator does with an empty result set. This defect exists at three pots today and would exist at four, or at ninety-four. Fixing it inside rotation work would fuse an accounting correction with a structural change, and the two fail for different reasons.

**Candidate treatments, not chosen.** Either exclude unpaid shares from `total_distributed_cents` and route the unpaid pot through the governed zero-claim rule per POR §6; or fail closed on an empty evaluator result and refuse to settle the week, on the grounds that an empty result at a funded pot indicates missing upstream data rather than a legitimate outcome. Both depend on 22.22.

### 22.21 — FR-POOL-2 — OPEN, money-path. Special Teams empty result raises instead of failing closed

**Recorded, not fixed. Product ruling required. Opus-gated before implementation.**

Source: `spec/POOL_SETTLEMENT_FINDINGS_2026-07-30.md`, preserved unchanged.

**Location.** `betting/pool_engine.py` · `settle_pool` · Special Teams branch at approximately 753–775, `max()` call at approximately 757. No empty guard. When `st_scores` is empty, Python raises `ValueError: max() arg is an empty sequence`.

**Rollback prevents partial payout. Ledger remains conserved.** The raise aborts the transaction. Whatever postings the settlement had staged roll back, so no partial payout survives.

**A generic ValueError is not a governed domain refusal.** The failure surfaces as a `ValueError` indistinguishable from any other. It carries no domain message, names no cause, and is not routed through the fail-closed discipline the rest of the settlement path uses. An operator sees a stack trace, not a reason. Retry reproduces it. The week cannot settle until upstream data changes, and nothing in the error says so.

**Minimum reproduction.** A league/week reaching the Special Teams branch with empty `st_scores`. Assert that settlement raises a **named domain error** identifying the empty result set, distinguishable from the general `ValueError` surface. Asserting only that it raises is non-discriminating — the current code raises too. The test must assert on the message.

**Why separate from rotation.** An evaluator-level guard, not a slate-level concern. Under the two-family architecture the guard belongs to `RANK_EXTREMUM` generally, not to Special Teams specifically — an argument for fixing it in the evaluator framework rather than patching one branch.

**Candidate treatments, not chosen.** The narrow fix is an empty guard on the Special Teams branch with a named domain error. The better fix is a single empty-result rule inside the `RANK_EXTREMUM` evaluator specified in the POR, applied uniformly across all 73 definitions in that family. Both depend on 22.22.

### 22.22 — Shared unresolved dependency for FR-POOL-1 and FR-POOL-2

> **What is the governed settlement behavior when an evaluator returns an empty result set?**

FR-POOL-1 treats an empty result as a silent no-op. FR-POOL-2 treats it as a crash. Neither is a governed outcome. Whatever rule is chosen applies to both.

**An empty evaluator result must not be assumed equivalent to zero eligible claims.** POR §6's zero-eligible-claims rule addresses a different condition. Treating the two as the same requires an explicit product ruling and has not received one.

**Split of authorization.**

| Work | Authorization |
|---|---|
| Define the rule — what an empty result set means, written into POR §6 and the catalog | Rev1.2 catalog and specification authoring · **authorized under FR-POOL-AUTH-1 Option B** |
| Implement the rule — evaluator guards, named domain errors, `total_distributed_cents` correction | Evaluator implementation · **Stage H, Opus math review gate** |

The rule must exist before the fix can be specified. Rev1.2 authoring is the precondition for these two findings, not a detour from them.

---

### 22.23 — FR-POOL-AUTH-1 — OPEN, blocking scope narrowed by ruling. Pool work proceeded ahead of Stage H without a ruling

**Original finding, 2026-08-01.** Pool specification and control work proceeded ahead of Stage H in the merged build sequence. No authorizing ruling was found. The three pushed commits do not violate the Scope status, because they changed specification authority, metadata durability, and read-only invariant controls only.

Evidence: `Merged_Build_Sequence_2026-07-26.md` places Spec 4 at Stage H, behind Stages A through G. `SPEC_Pool_Rotation_Implementation_Scope_Rev1_1.md` line 3 reads **"Status: Scope — not authorized for build,"** preserved deliberately in Rev1.1 by ruling.

**RULING (Fraser, 2026-08-01). Option B approved with a strict boundary.**

Pool product-definition work may proceed ahead of Stage H only to author and validate Rev1.2 catalog semantics and their governed document representation.

**Authorized now:**
- define structured predicate semantics
- define quantifier semantics
- define threshold semantics and catalog fields
- identify required source-stat mappings
- revise the POR, Scope, and catalog JSON
- add pure, read-only invariant controls for those authored semantics

**Not authorized:**
- database columns or tables
- ORM model changes
- migrations
- evaluator code
- collection integration
- settlement or rollover execution
- balance movement
- production wiring
- deployment

Those remain Stage H work and remain covered by the current status: **Scope — not authorized for build.**

**Blocking scope after this ruling:**
- no longer blocks Rev1.2 catalog and specification authoring
- continues to block all Pool implementation

Status remains **OPEN.**

### 22.24 — Terminology ruling: catalog field versus database carrier

**RULED (Fraser, 2026-08-01).** "Schema carrier" is retired as ambiguous. It has been used for both a JSON key and a database column, which are on opposite sides of the FR-POOL-AUTH-1 boundary.

| Term | Meaning |
|---|---|
| **catalog field** / **catalog structure** | JSON and POR representation. Authorized under Option B |
| **database carrier** | persisted database columns or tables. Stage H |

**Candidate Rev1.2 terminology edits located; no governed file changed.** In `spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_1.md`: line 243, §I row 2, `pool_definition` schema — means a database table, should read database carrier. Line 259, "if the metadata schema shifts" — means JSON key structure, should read catalog structure. Lines 31–32 reference `db/schema.py` as a filename and are not the ambiguity; do not sweep them.

`SPEC_Pool_Catalog_Rotation_POR_Rev1_1.md` carries zero occurrences.

Correction is a Rev1.2 edit. Not executed.

### 22.25 — Step 6 restatement

**RULED (Fraser, 2026-08-01).** The Step 6 description is replaced with:

> Step 6 cannot begin as evaluator implementation. It first requires governed Rev1.2 catalog authoring to define structured predicate, quantifier, threshold, and source-stat semantics. Database carriers, ORM changes, migrations, and evaluator code remain Stage H work.

Placement in `SPEC_Pool_Rotation_Implementation_Scope_Rev1_1.md` is undecided. §I is a four-column implementation-order table spanning lines 238 to 262; the replacement text is prose and does not fit a cell. Candidates: a prose note beneath the §I table, a new row in §J Blockers alongside the existing six, or both. Not executed.

---

### 22.26 — Verified facts, no finding

- Three commits pushed as a fast-forward from `fb6a71b`: `53fe0ba` (8 paths, 3074 insertions, 12 deletions), `002ea4a` (1 path, 5 insertions), `c60f73a` (1 path, 287 insertions)
- HEAD equals origin at `c60f73a7e38dae0c4a3af794320f858c745df6cf`
- `test_pool_catalog_invariants.py`: 10 assertions, 0 failures, exit 0. 287 lines at tracked HEAD
- **`pool_catalog_rev1_1.json` declares nine `counts` keys:** `active`, `blocked`, `matchup`, `qualifier`, `rank_extremum`, `retired`, `rollover_eligible`, `rotatable`, `team`. Assertion 6 builds a nine-entry measured set and asserts three conditions together — no value drift, nothing measured-but-undeclared, nothing declared-but-unmeasured. Label: *"6. Declared counts equal measured counts, all nine keys."* Read from `HEAD:test_pool_catalog_invariants.py` and `HEAD:spec/pool_catalog_rev1_1.json`
- **Supersedes the 2026-07-31 delta's "all seven measurable fields,"** a hand-count taken before `c60f73a` added the control. The verified figure is nine. Recorded as an FR-PROC-SWEEP-1 instance at 22.15
- The Rev1.0 hash fence held at every gate: pre-flight, mid-edit, after each of the three commits, and after the push
- Exactly two rollover corrections, #84 and #87. 73 definitions remain `rollover_eligible: false`, all RANK_EXTREMUM
- `pool_catalog_rev1_0.json` has no terminal newline; Rev1.1 preserves that. It explains the 2403-line diff stat against 2402 counted lines
- `SPEC_Pool_Rotation_Implementation_Scope_Rev1_1.md` is 278 lines at tracked HEAD. §I heading at line 238, §J heading at line 263, each unique
- 96 classified rows − 2 anti-tanking retirements = 94 active
- `counts.retired: 4` spans two kinds: classified-then-retired (#57, #96) and never-classified legacy names (The Lineup, Bench Burn)
- Retired records carry 4 fields and **no `key`**. `key` is the `pool_definition` PK, so a retired definition cannot be expressed as a row. Retirement-by-absence is structurally the only option. No RETIRED state required or authorized
- Scope line 43's "91 approved definitions" = 94 − 3 currently supported
- `db/schema.py:1186` — `rollover_eligible` Boolean, `nullable=False`, no default, no CHECK. Rev1.1 needs no database change
- §E weekly lifecycle branches generically on eligibility, never on identity
- No production code loads the catalog. All `betting/` references are comments
- Volume II ends at Section 21 prior to this append. Section 22 heading count 0, measured against tracked `HEAD:Findings_Register_v17.md`, 1257 lines, with positive control `FR-DOC-REG-1` returning 2
- Tracked registers are exactly two: `Findings_Register_v12_2.md` (vol. I) and `Findings_Register_v17.md` (vol. II). `v16` is neither tracked nor in the panel
- `Findings_Register_v10.md` and `Findings_Register_v13.md` remain untracked in the working tree, contrary to the v17 working-tree convention
- The 2026-07-30 and 2026-07-31 deltas are untracked working-tree files, measured by `git ls-files --error-unmatch`. The 2026-08-01 delta exists only in the project panel and is not on disk
- Nothing deployed. No migration run. Railway untouched

### 22.27 — Untracked artifacts

The working tree carries a substantial set of untracked entries at the repo root and under `spec/`, including an `archive/` directory, planning documents, prototypes, superseded registers, and execution instruction files.

**Untracked does not mean immaterial.** Some may be current authority that never reached the repository. Others may be superseded and safe to remove. Which is which is unknown.

A separate read-only inventory and disposition review is required before any recovery, tracking, archiving, or deletion. Do not treat the untracked list as noise. Do not clean it incidentally during other work.

Same class as FR-PROC-PANEL-2 at 22.19, which recorded the panel-versus-repo divergence from the other direction.

### 22.28 — Candidates raised and not adopted

**FR-POOL-PTR-1 — DROPPED by ruling.** Proposed on the grounds that `spec/POOL_SETTLEMENT_FINDINGS_2026-07-30.md` cites Rev1.0 as product authority. **Rejected:** the artifact is dated 2026-07-30 and records evidence from that time. Its Rev1.0 pointer is historical provenance, not a stale current-authority pointer. It is not to be rewritten to Rev1.1.

**FR-DOC-DELTA-1 — CANDIDATE, held. Not adopted into this section.** Proposed on the grounds that findings deltas accumulate outside version control, creating a window in which findings exist only as untracked or panel-only files.

Held pending inspection of the documented convention governing delta and update artifacts. If deltas are governed temporary append instructions that are intentionally untracked, the exposure is absorption lag rather than absent version control, and the wording and severity change accordingly.

Lead, not evidence: eight `FantasyBeefs_Findings_Register_Update_*.md` files dating to 2026-07-16 are also untracked, which is consistent with a standing convention but does not establish one. No written convention has been located. The inspection has not been run.

---

## Section 23 — Documentation Lifecycle and Deployment-Surface Corrections

Session of 2026-07-31, Step 3 review. All entries below rest on direct
measurement taken this session. Absorbing commit for Section 22 is
`65b4e2ccd3030a979d00e373d1b20f445c91963a`, committer date 2026-07-31.

---

### 23.1 — FR-DOC-DELTA-1 — NEW, ADOPTED. Findings-delta artifacts carry no absorption record

**Severity: LOW.**

**Issue Summary**

A findings delta is a temporary append instruction. It names a destination
register and a placement, is consumed into that register, and then has no
further authority. Nothing on the artifact records that consumption.

The defect fired inside the artifact that documents it. The 2026-08-01 delta
opens by stating that whether the 07-30 and 07-31 deltas had been absorbed was
unconfirmed, and that assigning a section number before checking risked a
second collision on top of the one FR-DOC-REG-1 already records.

A reader encountering a delta on disk cannot distinguish "pending, apply this"
from "spent, ignore this." The two states look identical and carry opposite
instructions.

**Ruling — ADOPTED, severity LOW**

Every delta receives an absorption stamp once its content is committed into the
governing register. Stamp format:

    Status: ABSORBED — DO NOT REAPPLY
    Destination: Findings_Register_v17.md, volume II
    Section: 22
    Absorbing commit: <full SHA>
    Absorption date: <YYYY-MM-DD, committer date of the absorbing commit>

The stamp is additive. It does not modify, remove, or supersede delta content.
Severity is LOW because absorbed content is committed and hash-fenced in the
register; the exposure is reader confusion and duplicate application, not loss.

**Committer date, not author date.** The two coincided for `65b4e2c`, but the
committer date is the measure of when a commit entered history and is the
governing field.

**A session date is not a commit date.** The delta named 2026-08-01 is absorbed
by a commit dated 2026-07-31. Both are correct. `c60f73a` landed at 19:58 and
`65b4e2c` at 22:24, both on the evening of 31 July, Pacific. A session carries
its working label; a commit carries its clock. Do not reconcile the two.

**Visibility is part of the control.** A pending delta must remain visible in
`git status`. This finding was discovered because the deltas appeared there.
Any ignore rule that conceals a delta before absorption reproduces the defect
in a less detectable form. See 23.2.

**Applied this session** to the two disk deltas at
`spec/FantasyBeefs_Findings_Register_Delta_2026-07-30.md` and
`spec/FantasyBeefs_Findings_Register_Delta_2026-07-31.md`.

**Not applied** to `FantasyBeefs_Findings_Register_Delta_2026-08-01.md`, which
was measured absent from disk at both `spec/` and the repository root and exists
only in the Claude project panel. No disk copy was created for the purpose of
stamping it.

---

### 23.2 — FR-DOC-IGNORE-1 — NEW, ADOPTED. Findings deltas escaped a valid ignore convention through two independent changes

**Severity: LOW.**

**Issue Summary**

`.gitignore` line 25 reads `/FantasyBeefs_*_Update_*.md`. Lines 23 and 24 state
the intent: loose planning docs at the repo root are kept local and never
tracked, and the leading slash means subfolders are deliberately unaffected.

The convention works. Measured this session: 66 ignored entries, including
eight `FantasyBeefs_Findings_Register_Update_*.md` files at the repo root.

The current findings deltas escape it through two changes, either of which
alone would have been sufficient:

  - the family name changed from `_Update_` to `_Delta_`
  - placement moved from the repo root to `spec/`

Measured directly. `spec/FantasyBeefs_Findings_Register_Delta_2026-07-30.md`
and `_2026-07-31.md` both return `git ls-files --error-unmatch` exit 1 and
`git check-ignore -q` exit 1. `git check-ignore -v --no-index` reports no
matching rule for either, so no negation or override is involved.

They are **untracked and unignored** — a third state with neither Git history
nor deliberate exclusion.

**The convention did not break. The artifacts moved out from under it.**

**Ruling — ADOPTED, severity LOW**

Remediation is scoped to the two existing absorbed deltas by exact name.

A family-wide glob over `/spec/FantasyBeefs_Findings_Register_Delta_*.md` was
drafted and **rejected**. It would ignore every future delta on creation,
including one not yet absorbed, concealing pending instructions and defeating
the visibility control recorded at 23.1. The proposed remedy would have
reproduced the defect it was meant to close.

A rename into an explicitly absorbed family, ignored by glob, is lifecycle-
correct and remains available. It was not adopted here because Section 22 and
the session transition packages cite these artifacts by full path, and a rename
would dangle every one of those pointers.

Exact names also match the convention already documented at `.gitignore` lines
28 to 30: exact names rather than globs, so each versioned file is a deliberate
decision.

Severity is LOW. A companion deployment-surface finding was investigated and
**not opened** — see 23.3.

---

### 23.3 — Authoritative correction to vol. II §19.10 — deployment mechanism

**§19.10 is preserved unchanged as historical audit evidence. Its
deployment-mechanism statement is superseded by this section.**

§19.10 states that `railway up` uploads the working tree, naming untracked
documents, `archive/`, and a 26 MB repo zip as deployment inputs. That
mechanism claim is wrong.

**Measured rule:**

  - default `railway up` respects **both** `.gitignore` and `.railwayignore`
  - `--no-gitignore` disables `.gitignore` handling only
  - `.railwayignore` is the deployment-specific exclusion layer and remains in
    force under `--no-gitignore`

Source: Railway CLI documentation for `railway up`, read 2026-07-31.

`.railwayignore` measured this session: 24 lines, excluding `*.md`, `spec/`,
`archive/`, `*.sql`, and named scratch artifacts. `.gitignore` independently
excludes `secrets/`, `backups/`, `*.zip`, `*.db`, and
`.claude/settings.local.json`.

Under the default path none of the artifacts named in §19.10 reaches
production. `archive/` measures 11 files and 146,881 bytes and is excluded
regardless.

**No deployment-surface finding is opened.**

**FR-DEPLOY-IGN-1 — HELD as a defense-in-depth candidate, not a finding.**
`.railwayignore` alone does not exclude `secrets/`, `*.zip`, `*.db`, or
`.claude/`. Those depend on `.gitignore`. No evidence exists that
`--no-gitignore` is used or authorized. Mirroring the four categories into
`.railwayignore` may be proposed later as hardening.

**Process note.** Two successive deployment-surface hazards were proposed
during this review and both were killed by measurement — first the untracked
documents, then the repo zip. The pattern is hunting for a finding rather than
measuring a surface. Recorded so the reflex is visible next time.

---

### 23.4 — Measurements taken this session

Recorded because several supersede figures carried in earlier documents.

| Measure | Value |
|---|---|
| Untracked entries | 54 |
| Ignored entries | 66 |
| `archive/` | 11 files, 146,881 bytes |
| `.gitignore` | 48 lines |
| `.railwayignore` | 24 lines |
| Tracked text files scanned for the v17 hash | 270 |
| Tracked references to the v17 hash | **0** |
| Untracked references to the v17 hash | 2, both in the 2026-08-01 Rev2 session-close package |

**The register's own hash fence lives only in an untracked document.** Zero
tracked files record it. Recorded as an observation, not a finding.

**`Findings_Register_v12_2.md` is tracked.** This closes the open sub-question
carried at vol. II 20.5, which asked whether vol. I was tracked, untracked, or
gitignore-swallowed. Measured: `git ls-files --error-unmatch` exit 0.

**`Findings_Register_v15.md` and `Findings_Register_v16.md` are absent from
disk and absent from the index.** They exist only in the Claude project panel.
Panel removal is therefore not provably lossless and is deferred indefinitely.
Note that `git ls-files` reads the current index only; vol. II 19.12 records a
successful `git show HEAD:Findings_Register_v16.md` at an earlier HEAD, so v16
was tracked once and has since been removed.

**The project panel served a stale vol. II.** The panel copy measured 99,345
bytes, 1,257 lines, eight section headings ending at Section 21, hashing
`48A40850EDB942CE335ED21098C6DD1A0AB4C1037E412A728937AE8A84CA22C8`. It does not
contain Section 22. The panel is not a substitute for the repository and must
not be used as a base for register edits.

---

### 23.5 — Absorption record authority — AMENDMENT to 23.1

**This subsection amends 23.1. Where 23.1 describes the absorption stamp as the
remedy, this subsection governs.**

23.1 as first written left FR-DOC-DELTA-1 remediated by artifacts that a fresh
clone would not contain. The two stamped deltas are ignored at `.gitignore:54`
and `:55` and exist only in one working tree. A control that lives outside
version control is not a control.

**1. The governing register entry and its commit history are the durable,
authoritative absorption record.** Absorption is established by what this
register says and by the commit that put it here. Nothing else.

**2. A local stamp on an untracked delta is a convenience marker only.** It
helps a reader who encounters the file on disk. Its loss does not erase
absorption, does not reverse it, and does not reopen FR-DOC-DELTA-1. A missing
stamp is not evidence that a delta is pending — the ledger below is.

**3. Every future absorption must be recorded in the governing register** with
all five fields:

  - delta identity and path
  - destination volume and section
  - absorbing commit SHA
  - committer date of the absorbing commit
  - `ABSORBED — DO NOT REAPPLY` status

A stamp on the delta file itself is optional. The register entry is not.

---

**Absorption ledger — deltas absorbed at `65b4e2c`**

| Delta identity and path | Destination | Absorbing commit | Committer date | Status |
|---|---|---|---|---|
| `spec/FantasyBeefs_Findings_Register_Delta_2026-07-30.md` | vol. II, Section 22 | `65b4e2ccd3030a979d00e373d1b20f445c91963a` | 2026-07-31 | ABSORBED — DO NOT REAPPLY |
| `spec/FantasyBeefs_Findings_Register_Delta_2026-07-31.md` | vol. II, Section 22 | `65b4e2ccd3030a979d00e373d1b20f445c91963a` | 2026-07-31 | ABSORBED — DO NOT REAPPLY |
| `FantasyBeefs_Findings_Register_Delta_2026-08-01.md` (panel only, absent from disk) | vol. II, Section 22 | `65b4e2ccd3030a979d00e373d1b20f445c91963a` | 2026-07-31 | ABSORBED — DO NOT REAPPLY |

All three destinations were retargeted to vol. II as recorded at 23.1. The
2026-07-30 delta originally named `Findings_Register_v16.md`.

The third row is the point of this ledger. That delta has no disk file and can
carry no stamp. It is nonetheless absorbed, and this row is the proof. The same
holds for the other two if their working-tree copies are ever lost.

**The two disk deltas are ignored by default and are not intended to be
committed.** That is the disposition ruled at 23.2 and it stands. Their stamps
are convenience markers over the ledger above, not the record itself.

**Committer date, not author date.** They coincided for `65b4e2c`
(`2026-07-31T22:24:50-07:00`). The committer date remains the governing field.

## Section 24 — B2 Group 2 documentary closeout (2026-08-02)

Documentary only. No code, schema, test, or migration changed. Nothing staged,
committed, or pushed. Group 3 not begun.

The Group 2 season-allocation contract of record is established at
`spec/SPEC_B2_Group2_Season_Allocation_Contract_v1.md`, Revision 1. No prior
durable contract existed; a tracked-document sweep returned zero hits. That file
is authoritative for the five-state model, season authority, commit discipline,
transaction ownership, isolation posture, the gate surface, concurrency evidence,
integrity checkpoint, and deployment order. This section records only the
dispositions that belong to the register.

### 24.1 — R-6 — Group 2 revert posture

**Disposition:** RECORDED. Revert Group 2 **as a unit** unless separately
reviewed.

Production `buy_in_paid` distribution is **unknown**. It has not been measured.
Measuring it requires separate read-only authorization and a production read,
neither of which exists.

Partial revert is not authorized. The Group 2 changes were verified together, as
one set, against one manifest. No subset has been verified independently. A
partial revert would ship a combination that was never tested.

Reverting only the gate retarget would restore `User.buy_in_paid` as the
enforcement source. With the production distribution unknown, that could block
users who should pass or permit users on stale legacy state.

### 24.2 — R-11 — accepted risks and debt

**Disposition:** RECORDED. **No behavior change is authorized by this entry.**
All items below verified by direct source read of `auth/allocation_gate.py`
(SHA-256 `98657F17…37D3D5C0`) and `payments/stripe_connect.py` on 2026-08-02.

**Accepted risks — enumerated, in evaluation order:**

- commissioner role → bypass, evaluated first, ahead of every other branch;
- `current_user.team_id is None` → fail open;
- `Team` row missing → fail open;
- `League` row missing → fail open.

The League branch is compound: `if not league or not league.buyin_enforcement_active`.
Only the missing-League half is accepted risk. Enforcement-off is deliberate
design under Finding 5.3, not a risk, and must not be reclassified as one.

**No behavior change to these branches is authorized in Group 2.**

They are recorded so acceptance is explicit rather than inherited by silence.

**Compensating control.** The wallet non-negative ledger guard. It does not remove
the accepted risks above. It bounds the consequence.

**Policy-drift debt — classified.**

Two independent policy-read implementations exist. The status route calls
`get_allocation_enforcement_active()`, while the enforcement dependency separately
reads `League.buyin_enforcement_active` inline. Compatibility aliases in
`api/main.py` and `payments/stripe_connect.py` expose those same implementations
under legacy names; they do not create additional implementations. The drift risk
is that one policy is evaluated through two independently maintained code paths.

`set_buyin_enforcement_active()` in `payments/stripe_connect.py` is a writer, not
an enforcement-decision reader. It was retained in that module because it writes
`StripeAuditLog` through the module-private `_log` helper, and is deferred to
Group 3.

Classified as **policy-drift debt, not unused-helper cleanup.** The distinction is
load-bearing. Treating it as an unused helper invites deleting the helper, which
would leave the inline read as the sole path and hide the drift rather than close
it. Any future fix must converge the two paths, not remove one.

**Debt — temporary compatibility aliases.**

- `api/main.py` exports `get_buyin_gate` as a temporary compatibility alias,
  marked in-source for removal during Group 5.
- `payments/stripe_connect.py` exports compatibility aliases pending deletion of
  that module in later B2 work: `get_buyin_gate`,
  `get_buyin_enforcement_active`, and `set_allocation_enforcement_active`.

The `set_allocation_enforcement_active` binding runs the **reverse direction** of
the others: the new name points at an implementation that still lives in the old
module, because `set_buyin_enforcement_active` was deliberately not relocated in
Group 1.

Recorded so the removals are not lost. No change authorized in Group 2.

**Debt.** Free-text ledger door names. Recorded, unaddressed.

**Debt — stale docstring.** `payments/stripe_connect.py:787` refers to
`get_buyin_gate` reading the column fresh. That name now resolves only through an
alias. The behavior described is accurate; the name is stale. No change
authorized.

### 24.3 — Method rules confirmed this pass

- `git grep` searches tracked files only. Any sweep required to be complete must
  include untracked files. A tracked-only sweep on this branch would have returned
  a false clean (R-5).
- A hash proves bytes are intact, not that they are the right bytes. Pair every
  hash with a marker or content check.
- The untracked manifest cannot detect edits to tracked files. Tracked-file changes
  require a separate per-file diffstat assertion. File-count alone cannot
  distinguish a documentary edit from a code edit.
- A symbol appearing in a module is not an implementation of that symbol. Imports
  and alias bindings must be read as source before being counted. This pass
  initially over-counted the enforcement-policy implementations on symbol reach
  alone.

### 24.4 — Append method — direct append, deliberately

This section was appended directly to the register rather than written as a delta
for later absorption under the Section 23 mechanism.

The choice is deliberate. No commit and no cross-session transfer is occurring.
The delta mechanism exists to carry content across those boundaries until an
absorbing commit retires it. Creating a delta here would produce a second artifact
requiring its own absorption row later, for no transfer benefit.

Direct append is therefore the correct instrument for this pass, and no absorption
row is owed for Section 24.

### 24.5 — Documentation divergence recorded, not corrected

`economy/season_allocation.py` states "ONE top-level commit" in its opening
summary while its own COMMIT COUNT section states the precise rule: at most one
commit per invocation, exactly one on create, zero on replay, zero on errors. The
summary is overbroad.

Recorded in full at §3.4 of the contract, which adopts the COMMIT COUNT rule and
not the summary. Not duplicated here, and **not corrected in this pass.** Changing
the Python file requires separat






e authorization.

## Section 25 — B2 Stripe removal (2026-08-05)

### 25.1 — Finding 5.2-1 sole-writer invariant: SUPERSEDED

**Superseded:** `confirm_buyin_payment()` is the only production writer to
`reserve:{team_id}`.

**In force:** `activate_season_allocation()` is the sole production writer of the
season-opening wallet and championship-reserve funding posting.

The superseded statement was correct for the Stripe-funded design. It is retained
in this register rather than deleted, so a future reader comparing Finding 5.2
against the shipped code finds the divergence explained.

Governing document: `spec/SPEC_B2_Stripe_Removal_Addendum_v1.md`.

### 25.2 — B-1 blocker: CLOSED

B-1 was raised when `test_championship_payout.py` Item 8 failed after B2 added a
second `reserve:{team_id}` writer while the Group 2 contract stayed silent on the
invariant.

Door 1 reachability evidence established that `confirm_buyin_payment()` was
production-reachable at `86e7402` via `POST /payments/buyin-confirm`, a registered
route gated only by `require_commissioner`, with no Stripe secret, webhook
signature or feature flag on the path. The two funding paths held zero
cross-references, so double funding was possible and no conservation check would
have detected it — each posting was independently balanced.

B-1 is closed by **removal, not by mutual exclusion**: Door 1 and the entire
Stripe surface are gone. Proven by `test_stripe_removal_regression.py` Items 1–3.

### 25.3 — Guard strengthened from text search to structural check

The replacement sole-writer guard walks the AST of every production module,
finds each `post()` / `ledger_post()` call, and flags any whose leg list
constructs a `reserve:{...}` account, reporting the enclosing function. It no
longer trips on comments or docstrings and cannot be defeated by reformatting.

### 25.4 — Second Stripe funding rail found in FAAB top-ups

`wallet/faab_wallet.py` carried an independent Stripe rail that the removal plan
did not enumerate: `_create_stripe_link()`, the `stripe` SDK import,
`STRIPE_SECRET_KEY`, `MOCK_MODE`, and real-mode branches in both top-up creators,
reachable via `POST /faab/topup-bet` and `POST /faab/topup-waiver`. Removed.

Consistent with `FantasyBeefs_BAB_TopOff_UIUX_Spec_2026-07-21.md`, which already
ruled a top-off an internal BAB issuance event with no real money moving through
the application. That spec's item B6 issuance ledger model remains **unbuilt** —
the issuance account and door are unpinned, and approver identity and
request↔credit linkage are absent. Not invented here.

### 25.5 — DEBT: pre-existing gate-test failures, NOT caused by this package

`test_buyin_enforcement.py` (13 pass / 2 fail) and
`test_bet_funded_retirement.py` (17 pass / 3 fail) fail because the B2 Group 2
gate retarget made `SeasonAllocation` existence the gate condition, while those
tests still set only `User.buy_in_paid`. Every failure is a 402 from the gate.

Verified pre-existing: both produce **identical** pass/fail counts when run
against a clean checkout of `86e7402`, before any Stripe-removal change. They are
recorded as Group 2 test debt and were deliberately not repaired inside a Stripe
removal package.

Classified **REQUIRED — next package**.

### 25.6 — DEBT: commissioner authorization is global

`require_commissioner` tests `user.role` only; it takes no `league_id`, and
`User` has no league column. Any commissioner can invoke any commissioner route
for any league, including `POST /league/{league_id}/season-allocation` — now the
only registered money-moving commissioner route.

Not created or widened by this package. League-scoping the dependency touches 38
route declarations and is an authorization redesign.

Classified **REQUIRED — next package**.


## Section 26 — B-2 closure (2026-08-05)

### 26.1 — B-2: CLOSED

B-2 was the last B2 blocker: the accepted championship distribution arithmetic
and remainder rule lived only inside payout code deleted with the Stripe
surface, and would otherwise have been lost with it.

Closed by preserving the rule as a pure function,
`economy.championship.championship_distribution()`.

### 26.2 — Finding 5.2-3, Option A — the accepted rule, now in code

1. Each ordinary amount is `floor(total_cents * pct / 100)`.
2. The ENTIRE remainder after flooring every place goes to FIRST PLACE.
3. Therefore `sum(amount_cents) == total_cents` for every valid input.

Integer cents only, verified at AST level: zero true-division nodes, zero float
literals, one floor-division node. Invalid input raises `ValueError` and is never
silently normalised. `bool` is rejected explicitly because it is an `int`
subclass.

Covered by `test_championship_distribution.py` — 280 assertions including a
10,000-case sweep proving the sum identity and that no non-first place ever
receives remainder.

### 26.3 — What was NOT built

`championship_distribution()` is ARITHMETIC ONLY. No database, no session, no
ledger, no posting. **Internal Credits championship settlement remains UNBUILT**
and is not part of this closure package. Nothing in this section may be read as
evidence that a season can be settled.

Idempotent settlement and payout-split configurability remain later decisions.

`ECONOMY_STOPS` does NOT define payout splits — it carries only
`weekly_min_cents`, `wallet_cents`, `buyin_cents`, `reserve_cents`. The only
splits in the codebase are `reports.standings.DEFAULT_PAYOUT_SPLIT = [60,30,10]`
and the `LeagueTreasury.payout_split_json` column default. The test matrix uses
stop reserve totals as POT TOTALS combined with that accepted split, and says so.

### 26.4 — Season-funding invariant

PRESERVED: at most one season-opening funding posting per (team, season).

Enforced by removal of every alternative production writer plus the
`SeasonAllocation` unique constraint on (league_id, team_id, season). There is no
cross-writer runtime exclusion check, because there is no second writer to
exclude. The stale `confirm_buyin_payment()` sole-writer docstring in
`economy/championship.py` was corrected to say this.

### 26.5 — Persisted ledger-door assertion

The B2 PostgreSQL suite now reads persisted `LedgerEntry` rows back and asserts
every `reserve:%` row carries `door = "season_allocation"` (scenario (t), 4 new
assertions; suite total 108 -> 112).

SCOPE STATED EXACTLY: rows produced by that suite's own setup in the disposable
`_test` database. No production database is inspected; no claim is made about
historical production rows.

Other SQLite suites (`test_ledger.py`, `test_championship_payout.py`)
deliberately post reserve legs with `door="buy_in_paid"` / `"buy_in_tab"` as
historical pre-B2 fixtures. Different database, different scope. The assertion
was NOT weakened to accommodate them.

### 26.6 — FAAB top-up routes deregistered pending B6

`POST /faab/topup-bet`, `/faab/topup-waiver`, `/faab/topup-confirm` and
`/faab/apply-pending` are no longer registered. The temporary
request-and-confirm flow mints wallet balance with no counterparty and no ledger
posting, which is not an acceptable permanent Credits issuance model.

Unavailable until B6 provides a balanced ledger posting, an issuance
counterparty/account, approver identity, and request-to-credit provenance. The
implementation in `wallet/faab_wallet.py` is retained as B6's starting point; the
read-only FAAB surface survives. Route count 86 -> 82.

### 26.7 — DEBT: residual non-route mint reachability

`notifications/tuesday_sync.py::_step_apply_topups` still calls
`apply_pending_topups()`, which credits `FaabWallet.waiver_balance` directly with
no ledger posting, and that pipeline is reachable via `POST /admin/tuesday-sync`.

With the request routes gone no route can create an eligible pending record — but
that is a DATABASE PRECONDITION, not a structural guarantee, and it is recorded
here rather than assumed away. `test_stripe_removal_regression.py` Item 6 asserts
the residue exists so its eventual removal is noticed.

Classified **REQUIRED — next package**. Neutralising the Tuesday step is outside
a B-2 closure package.
