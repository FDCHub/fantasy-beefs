# Fantasy Beefs — Findings Register v14

**Supersedes:** v13
**Date:** 2026-07-23 (Session 2)
**v14 change:** adds Section 14 — the 2026-07-23 security-remediation session. Records the scope ruling that supersedes Master Plan v8 on the odds-port question; the first verified production restore point in the project's history; FR-SEC-DB-2 opened and partially classified; FR-SEC-DB-3 opened and remediated; FR-SEC-DB-1 rotation paused mid-sequence with steps 1–7 complete. All prior content carried unchanged from v13.

**Authority note.** Sections 1–13 are carried verbatim from v13. Section 14 is additive. Where Section 14 contradicts an earlier section, Section 14 governs — this applies to exactly one item, the 12.9 unreconciled flag, now resolved.

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
