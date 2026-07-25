# FR-SEC-DB-1 — Desynchronization Response Procedure

**Rev 3, DRAFT. Authored 2026-07-25. Returned at Rev 1 and Rev 2; corrections applied. Awaiting third review.**

Sole gate on Phase C. Rotation does not proceed until this passes review.

`_final` is earned by implementation clearance, not by drafting and not by review clearance of a design.

---

## 0. Scope and status

| Property | Value |
|---|---|
| Governs | `Postgres` service, `production` environment, project `e8904b9e` |
| Rotation control | `Postgres` → Database view → **Credentials** tab → Regenerate |
| Rotation order | Option B — dump → rotate → external auth verification → variable correction → apply |
| Restore point | `fantasy_beefs_prod_2026-07-25_UTC.dump.gpg`, verified, pre-Spec-1 |
| Repo HEAD | `fd08e84` — runtime neutrality **proven at HEAD**, §9 precondition 13 ✅ |
| `postgres-test` scope | **OPEN** — §8.1 |
| Trust-mode repair | **NOT EXECUTABLE** — candidate only, §7 |
| Recovery preference, this event | **Replacement** over unproven repair — §6.2 |
| **S2 exit path** | **NO AUTHORIZED EXIT EXISTS** — §11.2 question 1 |

### 0.1 Rev 2 → Rev 3 changelog

| # | Correction | Section |
|---|---|---|
| 1 | Axis 2 changed from changed/unchanged to identity comparison against both captured values | §1.1, §3 |
| 2 | §10 rebuilt as a one-row-per-state derivation table mirroring §1.2; only S4 enters recovery | §10 |
| 3 | Bounded S6 server-identity diagnostic added | §3.1 |
| 4 | Clipboard exception made explicit; clipboard cleared after capture | §2.2 |
| 5 | Precondition 12 resolved to an **exact variable-only mechanism**; `railway up` expressly excluded | §10.1 |
| 6 | Precondition 13 marked cleared with evidence | §9 |
| 7 | **New:** `railway redeploy` / `railway restart` availability on CLI 5.6.2 unverified | §10.1 |
| 8 | **New:** S2 has no authorized exit — raised, not answered | §11.2 |

---

## 1. The failure mode, stated precisely

Railway Postgres holds the `postgres` role password in two places.

1. Inside the database, as a SCRAM-SHA-256 verifier in `pg_authid`.
2. Outside, as Railway service variables — `POSTGRES_PASSWORD`, `PGPASSWORD`, and composed into `DATABASE_URL` and `DATABASE_PUBLIC_URL`.

Regenerate is documented to update both together. The desync class is that it updates one.

The mechanism is initialization timing. `POSTGRES_PASSWORD` is consumed when the database is first initialized. On an existing persistent volume it is not continuously reapplied to the role. A variable can therefore change while the role keeps its original password, and the two drift apart with no error anywhere.

### 1.1 Classification requires two axes

Authentication alone cannot classify the outcome. Role authentication proves what PostgreSQL accepts. It says nothing about what Railway stored.

**Axis 1 — role authentication.** Probe with OLD, then with NEW. §2.3.

| Code | Result |
|---|---|
| **A1** | OLD authenticates, NEW does not |
| **A2** | NEW authenticates, OLD does not |
| **A3** | Neither authenticates |
| **A4** | **Both** authenticate |
| **A5** | Authentication never reached — transport failure |

**Axis 2 — Railway variable identity.** Compare the current `DATABASE_PUBLIC_URL` against **both** captured values. §3, instrument 3.

| Code | Result |
|---|---|
| **V-NEW** | Current variable exactly equals captured NEW |
| **V-OLD** | Current variable exactly equals captured OLD |
| **V-OTHER** | Valid DSN shape, matches neither |
| **V-ERR** | Missing, malformed, or shape-invalid |

**"Changed from OLD" does not prove "equals NEW."** Rev 2's changed/unchanged test admitted a third value, partial propagation, an unexpected regeneration, or an unrelated configuration mutation, and reported all of them as success. Three values are available — OLD, NEW, current — so compare identities directly.

**Then assign state.**

| Axis 1 | Axis 2 | State | Production reachable |
|---|---|---|---|
| A2 | V-NEW | **S1 SUCCESS** | yes, on NEW |
| A1 | V-NEW | **S2 ROLE-STALE** | yes, on OLD |
| A2 | V-OLD | **S3 VAR-STALE** | yes, on NEW |
| A1 | V-OLD | **S0 NO-OP** | yes, on OLD |
| A3 | any | **S4 LOCKOUT** | no |
| A5 | any | **S5 NOT-AUTH** | unknown |
| A4 | any | **S6 AMBIGUOUS** | hard stop |
| any | V-OTHER | **S6 AMBIGUOUS** | hard stop |
| any | V-ERR | **S6 AMBIGUOUS** | hard stop |

### 1.2 What each state means, and what it is

| State | Meaning | Class |
|---|---|---|
| **S1** | Rotation held | Proceed |
| **S2 ROLE-STALE** | Variables moved, role did not. Working credential in hand. **No authorized exit — §11.2.** | Failed rotation |
| **S3 VAR-STALE** | Role moved, Railway variables did not. Dependents carry OLD and will fail on apply. | Configuration repair |
| **S0 NO-OP** | Nothing changed. Role takes OLD, Railway stores OLD, despite the UI showing a new value. Either the operation did not fire or propagation has not landed. | Non-event |
| **S4 LOCKOUT** | Neither credential authenticates | **Recovery** |
| **S5 NOT-AUTH** | Not a credential problem | Transport diagnosis |
| **S6 AMBIGUOUS** | Two credentials accepted for one role, or a variable matching neither. Not a normal SCRAM outcome. The likeliest explanation is that you are not connected to the database you believe you are. | Epistemic failure |

**S2 is the good bad outcome and the most likely failure.** Production is not down. You hold a working credential. The trap is that the reflex to press Regenerate again destroys the recovery — §4.3.

**Only S4 is inherently a recovery-path state.** S2 is serious but not a lockout. S3 is configuration. S5 is transport. S6 is a broken model of the target.

---

## 2. Question 1 — proving whether OLD still authenticates

### 2.1 Capture OLD before pressing Regenerate

**ThinkPad X13 — PowerShell.** Clipboard-free, per FR-PROC-CLIP-1.

```
$raw = (railway variables list --service Postgres --environment production --json | Out-String)
$obj = $raw.Substring($raw.IndexOf('{')) | ConvertFrom-Json
$env:OLD_DSN = $obj.DATABASE_PUBLIC_URL
```

Validate by **shape, not substring**:

```
$env:OLD_DSN.StartsWith('postgresql://')
$env:OLD_DSN -match '\s'
$env:OLD_DSN -match 'hayabusa\.proxy\.rlwy\.net:15707/railway$'
```

Expect `True`, `False`, `True`.

Fingerprint **for the incident log only** — not the authoritative equality test:

```
$env:OLD_DSN.Length
[System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::HashData([System.Text.Encoding]::UTF8.GetBytes($env:OLD_DSN))).Replace('-','').Substring(0,8)
```

**`$raw` and `$obj` hold the password.** Scrub in a **separate turn**, after every dependent step has run.

### 2.2 Capture NEW after pressing Regenerate

If variables are stale — S3 — the CLI returns OLD, so the CLI cannot supply the NEW candidate. The source is the credential value presented by the regeneration UI.

**Bounded exception to the clipboard-free rule.** FR-PROC-CLIP-1's defect was silent line-joining, which `-Raw` plus shape validation neutralizes. Hand-typing is worse: a single typo manufactures a false S4, which is the most expensive wrong answer this procedure can produce.

Required constraints, all of them:

- Copy directly from the credential surface presented by the regeneration UI
- Immediate `Get-Clipboard -Raw`
- Trim once
- Validate DSN shape
- Store only in `$env:NEW_DSN`
- **Clear the clipboard immediately after successful capture and validation**
- Never echo the value
- Scrub the environment variable at procedure end

```
$env:NEW_DSN = (Get-Clipboard -Raw).Trim()
$env:NEW_DSN.StartsWith('postgresql://')
$env:NEW_DSN -match '\s'
$env:NEW_DSN -match 'hayabusa\.proxy\.rlwy\.net:15707/railway$'
$env:NEW_DSN.Length
```

Expect `True`, `False`, `True`, then a length. **Only after those pass:**

```
Set-Clipboard ''
```

If the UI exposes only a password rather than a full DSN, compose the DSN in the shell from the known host, port, and database. Never by editing a string containing OLD.

**Then re-read the CLI.** That produces axis 2. §3, instrument 3. If the UI value and the CLI value disagree, that disagreement **is** the finding — it is S3.

### 2.3 The authentication probe

`pg_isready` is **not** an authentication test. It reports server responsiveness and does not require valid credentials. It will show a healthy database in the middle of a lockout.

A real authentication attempt followed by a harmless read. Secret passed by environment inheritance so it never enters `argv`:

```
docker run --rm -e PGURI --entrypoint sh postgres:18 -c 'psql "$PGURI" -c "select current_user, current_database(), inet_server_port()"'
```

Set `$env:PGURI` from `$env:OLD_DSN`, run; then from `$env:NEW_DSN`, run again. `-e PGURI` with no `=value` inherits from the calling shell — the credential never appears on a command line and never enters PSReadLine history.

**Establish this probe works before rotation**, read-only, against production.

### 2.4 Reading the result

| Observation | Axis 1 |
|---|---|
| `select` returns a row | authenticates |
| `FATAL: password authentication failed for user "postgres"` | reached auth, credential rejected |
| timeout, `Connection refused`, `could not translate host name` | **A5** |
| `invalid response to SSL negotiation: H` | wrong service on the port |

**What the `FATAL` proves, narrowly.** The client reached a PostgreSQL authentication endpoint through the specified host and port, and the supplied credential was rejected. It does **not** prove any TLS property unless `sslmode` is expressly forced and verified.

---

## 3. Question 2 — separating role failure from DSN, variable, and config failure

Four instruments, in this order.

**Instrument 1 — error-text discrimination.** §2.4.

**Instrument 2 — the proxy's own record of itself.** `RAILWAY_TCP_PROXY_DOMAIN` and `RAILWAY_TCP_PROXY_PORT` on the `Postgres` service. Not secrets.

```
$raw = (railway variables list --service Postgres --environment production --json | Out-String)
$obj = $raw.Substring($raw.IndexOf('{')) | ConvertFrom-Json
$obj.RAILWAY_TCP_PROXY_DOMAIN
$obj.RAILWAY_TCP_PROXY_PORT
```

Not `hayabusa.proxy.rlwy.net` and `15707` means the proxy was reassigned. That is **S5**.

**Instrument 3 — variable identity. Mandatory. This is axis 2.**

```
$current = $obj.DATABASE_PUBLIC_URL
$current -ceq $env:NEW_DSN
$current -ceq $env:OLD_DSN
```

`True`/`False` → **V-NEW**. `False`/`True` → **V-OLD**. `False`/`False` with valid shape → **V-OTHER**. Missing or shape-invalid → **V-ERR**.

`-ceq` is case-sensitive. Password characters are case-significant, so `-eq` would admit a false match. Neither value is printed.

**Instrument 4 — the app's own error.** `fantasy-beefs` connects over private networking, a different path from the public proxy. If the proxy authenticates on NEW but the app fails, suspect the app's own `DATABASE_URL`. That is variable correction, not recovery.

**Do not start at instrument 4.** The app failing is the symptom that triggers panic and the weakest evidence in the set.

### 3.1 Server identity diagnostic — S6 only

> **Both passwords working is not permission to continue. It means your model of the target is wrong until proven otherwise.**

Bounded. Six steps. No mutation at any point.

1. Confirm proxy domain and port from Railway service variables — instrument 2
2. Authenticate with whichever credential works
3. Read server identity:

```
docker run --rm -e PGURI --entrypoint sh postgres:18 -c 'psql "$PGURI" -c "select current_database(), current_user, inet_server_addr(), inet_server_port()"'
```

4. Read known production identity markers — **table count must be 40**, and row counts must match the recorded baseline: `player_id_map` 4,777 · `projections` 2,407 · `nfl_schedule` 272 · `rosters` 180. These are non-sensitive, already recorded from the verified restore, and specific enough that a coincidental match is not plausible.
5. Confirm the service and environment the CLI is actually resolving — the linked service is `fantasy-beefs`, not `Postgres`, so `--service Postgres --environment production` is mandatory on every variables call and its omission is a candidate cause of S6
6. If identity still cannot be proved: **no mutation.** Escalate to §5 and treat replacement as the only path.

---

## 4. Question 3 — what may be attempted safely

### 4.1 Permitted, non-mutating

Reading Railway variables via CLI, any service · authentication probes with OLD and NEW · reading `RAILWAY_TCP_PROXY_DOMAIN` / `_PORT` · reading deploy and database logs · `railway ssh --service Postgres --environment production cat <verified-path>` · the §3.1 identity reads · opening a Central Station thread with no credentials.

### 4.2 Prohibited without separate authorization

| Action | Why |
|---|---|
| **A second credential mutation before the first is resolved** | §4.3. Converts S2 into S4. |
| **Restart or Redeploy of `Postgres` before diagnosis** | Unnecessary mutation during an active incident; alters availability and evidence you have not finished measuring |
| **`railway up` for credential correction** | Uploads a working-tree snapshot. Changes running code as a side effect of fixing a password. §10.1 |
| Hand-editing `POSTGRES_PASSWORD` | The documented cause of desync, not a fix for it |
| Improvised `ALTER USER` | Failed previously on this project. Makes the resulting hash unrecoverable by anyone, Railway included. |
| `railway ssh --session` | Installs tmux if absent. Mutates the production container. |
| Applying variable changes to dependents while in a known desync | Standing rule |
| Deleting the `Postgres` service | An intact locked database is a better artifact than none |
| Restoring the dump **over** the live database | Destroys evidence and fallback in one action |
| Upgrading the Railway CLI mid-incident | Unmeasured variable |
| Clicking "Upgrade to 18.4" | Standing prohibition |
| `git filter-repo` | Standing prohibition |

### 4.3 STANDING RULE — no second credential mutation

> **No second credential mutation while the result of the first credential mutation is unresolved. Preserve every candidate credential. Diagnose the resulting state first.**

Tool-independent by design. In S2 you hold OLD and it works. A second mutation can move the role to NEW1 while variables advance to NEW2. You then need NEW1, which you may never have captured, and OLD has stopped working. Self-inflicted lockout, and the single most likely way this rotation goes badly.

### 4.4 RULING — non-mutating production inspection is GREEN

> **Non-mutating production inspection is GREEN when the exact command and target are named beforehand, it alters no filesystem, process, configuration, database, network, deployment, or credential state, and its purpose is diagnostic verification of a precondition.**

**Green:** `railway ssh ... echo ssh-ok` · `railway ssh ... cat <verified-path>` · `railway variables list ...` · reading logs · an authenticating `SELECT` · the §3.1 identity reads.

**Not green, and not made green by arriving over SSH:** `sed -i` · `ALTER USER` · package installation · `touch`/`rm`/`mv` · redeploy, restart, or `railway up` · network or proxy changes · an interactive shell with unspecified actions.

---

## 5. Question 4 — stop conditions and the escalation reality

### 5.1 Hard stop conditions

1. **S4** — neither OLD nor NEW authenticates
2. **S5** — error text indicates a non-auth failure
3. **S6** — both authenticate, or axis 2 returns V-OTHER or V-ERR
4. `RAILWAY_TCP_PROXY_DOMAIN` or `_PORT` changed unexpectedly
5. `pg_hba.conf` content does not match expectation exactly — §7
6. Any command produces an unanticipated exit code
7. You are about to improvise

### 5.2 The escalation path does not recover credentials

**FR-SEC-DB-6 — Railway has no vendor password-recovery service; Hobby has no guaranteed direct support response.**

Railway's support documentation places Trial, Free, and Hobby on community support through Central Station, with employee participation possible and responses **not guaranteed**. Pro gets direct help, usually within 72 hours, plus private threads — still not a production recovery commitment. Ordinary support is not an email channel.

At **every** tier: Railway has stated publicly that they do not offer password recovery services, and that a password set through SQL is stored in a form their support team cannot retrieve. A Hobby user posting the exact S4 scenario was not given a reset.

**Escalation is informational, not remedial.** Never a dependency.

### 5.3 What to post

Project ID `e8904b9e`, service `Postgres`, environment `production`, exact error text, actions in sequence, state from §1.1.

**No credentials. No DSN. No variable values. Not in a screenshot.**

### 5.4 Diagnosis clock — `[N]` = 30 minutes, mandatory early exit

- **T+0** — hard stop, state logged, escalation thread posted then treated as non-blocking
- **T+0 to T+30** — diagnosis under §3 only
- **T+30** — commit to an available recovery path

> **If diagnosis reaches a decisive state before T+30, act immediately. Do not wait out the clock.**

`[N]` is a maximum diagnosis window before committing to a path. It is not time spent waiting for Railway.

---

## 6. Question 5 — when restoring the dump is justified

### 6.1 The honest cost basis

Today's dump is **pre-Spec-1**. No `beef_proposals`, no `beef_proposal_starters`. Spec 1 is committed and unshipped, so restoring costs **zero in schema terms**.

Data loss is bounded to whatever changed after 2026-07-25 15:54 UTC. Every money-path table is empty and verified empty from a restored copy — `bets`, `ledger_entries`, `transactions`, `escrow_accounts`, `escrow_transactions`, `beef_challenges`, `beef_starters`, `users`, all `pool_*`.

**The blast radius will never be smaller than it is now.** On September 1 this same procedure risks live wagers.

### 6.2 Replacement versus repair

> **This rotation event:** prefer replacement over unproven in-place repair. The data-loss delta is near zero and the repair path is unreviewed, depends on an unverified file path on an image version no published account covers, and temporarily disables authentication.
>
> **Standing policy:** choose between reviewed in-place repair and replacement on recoverability, data-loss delta, and verified preconditions. After launch, repair may preserve transactions written since the latest restore point.

An unconditional preference for replacement would be wrong as policy and is correct for today.

### 6.3 Trigger conditions

Restore when **either** holds:

1. **S4** confirmed by §2.3 probes with both credentials, and repair is unavailable — not reviewed, `railway ssh` fails, `pg_hba` mismatch, or one attempt already failed; **or**
2. it is chosen deliberately under §6.2.

It is the **primary guaranteed** path because it depends on nothing Railway has to do for you.

### 6.4 Restore into a new service. Never over the old one.

1. Provision a **new** Postgres service in project `e8904b9e`
2. Decrypt and restore the verified artifact into it
3. Verify row counts against the recorded baseline — `player_id_map` 4,777 · `projections` 2,407 · `nfl_schedule` 272 · `rosters` 180 · `players` 180 · `matchups` 98 · `teams`/`wallets`/`faab_wallets` 12 each · `leagues`/`faab_config`/`league_scoring` 1 each
4. Confirm 40 tables
5. Repoint `fantasy-beefs` `DATABASE_URL`
6. **Apply the staged variable change by the §10.1 mechanism. Not `railway up`.**
7. Confirm green **Success** in the Deployments tab — not "Online"
8. **Retain the locked-out service.** Do not delete until the new one is proven and a fresh dump taken from it.

### 6.5 Dependencies of the restore path

| Dependency | Status |
|---|---|
| Encrypted artifact, `C:\FantasyBeefs_Backups\` | Verified |
| OneDrive ciphertext copy | Verified, lengths match |
| **Second durable passphrase copy** | ❌ **BLOCKING — §9** |
| Physical ciphertext copy | Outstanding, non-blocking |
| `postgres:18` image | Cached locally |
| GnuPG 2.4.5, `C:\Program Files\Git\usr\bin\gpg.exe` | Verified sole binary. Windows absolute paths only. |

**The chain is ciphertext plus passphrase.** Two ciphertext copies and one irreplaceable passphrase is still one point of failure. Losing the disk costs nothing. Losing the sole passphrase deletes the only guaranteed path. That ranks the second passphrase copy **above** the physical dump copy.

---

## 7. Question 6 — trust-mode repair: candidate, NOT EXECUTABLE

### 7.1 Status

The prior rule held `pg_hba` trust-mode recovery **unauthorized**. That inverted in effect: it is the only published in-place repair, and no tier of Railway support performs a reset. A prohibition with no alternative is not a safety control.

**Revised status: not executable until a dedicated recovery procedure passes review.** The forum recipe is not authorized and must not be pasted.

**Rev 3 raises the stakes on this.** §11.2 question 1 shows S2 — the most likely failure state — also has no authorized exit without either trust-mode or an authorized variable write. The trust-mode review is load-bearing for the likely case, not only the worst case.

### 7.2 What the community sequence is

Recorded so review has a subject, **not** as instructions. Remove public access, SSH into the database service, change `pg_hba.conf` from `scram-sha-256` to `trust`, redeploy, connect locally with `psql`, reset the `postgres` password to Railway's stored value, restore SCRAM, redeploy again.

### 7.3 Required elements before this is executable

All nine. Any one missing means not executable.

1. Explicit preconditions, each independently verified
2. Service identity check — proof the session is on `Postgres`/`production`
3. Public-network removal **proof**, not assumption
4. Exact file and path verification on the running image
5. Rollback verification — SCRAM restored and confirmed
6. External authentication proof after SCRAM is restored
7. **Hard abort** if any expected `pg_hba.conf` line does not match exactly
8. **Bound and log the exposure window.** Trust mode authenticates anyone. Public proxy removal is step one, but **private networking stays live** — every service in the project reaches the database with no authentication for the duration. Record start and end timestamps.
9. **Do not trust the published path.** `/var/lib/postgresql/data/pgdata/pg_hba.conf` comes from posts against older images. You run **18.x**. Verify by read-only inspection first. This is why element 7 is the most important line in the document.

### 7.4 Pre-incident verification

Calm conditions, before rotation.

```
railway ssh keys
railway ssh --service Postgres --environment production echo ssh-ok
```

`railway ssh` is confirmed present on CLI 5.6.2 with non-interactive `[COMMAND]` support, which lets the reviewed procedure be discrete commands with individual exit codes.

**SSH requires a registered key.** First use may prompt to register one. Discovering that during a lockout would make the fast path fictional. Both checks are green under §4.4.

---

## 8. Open inputs

### 8.1 `postgres-test` scope — OPEN

A prior ruling put rotation scope at `Postgres` **and** `postgres-test`. Dropping it is probably right — reported orphaned, empty, unreferenced, and rotating it adds a mutation and a desync opportunity for no exposure reduction. But "orphaned" is a supplied characterization, and overturning a ruling needs a fact.

```
$raw = (railway variables list --service postgres-test --environment production --json | Out-String)
$obj = $raw.Substring($raw.IndexOf('{')) | ConvertFrom-Json
$obj.RAILWAY_TCP_PROXY_DOMAIN
```

Then, with that domain only — never the password:

```
git log --all -S"<domain>" --oneline
```

Empty means no exposure and it leaves scope. Non-empty means it stays. Verify the exact service name first; it has appeared as both `postgres-test` and `postgres_test`.

Deletion remains the better end state and dissolves the question. Separate cleanup, after production credential recovery settles.

### 8.2 Pro upgrade — recommended, not required

Buy it for whatever backup and PITR capability is **verified on this workspace**, and for private threads. Not for a password reset. No tier provides one.

---

## 9. Preconditions before Regenerate

| # | Precondition | Status |
|---|---|---|
| 1 | Verified encrypted dump, decrypt-proven with a real passphrase prompt | ✅ 2026-07-25 |
| 2 | Offsite ciphertext copy verified | ✅ OneDrive |
| 3 | **Second durable passphrase copy verified accessible** | ❌ **BLOCKING** |
| 4 | This procedure reviewed | ❌ Rev 3, awaiting third review |
| 5 | Trust-mode reviewed, **or** replacement accepted as sole path | ❌ open — see §11.2 q1 |
| 6 | `railway ssh` reachability and key registration proven, §7.4 | ❌ untested |
| 7 | Auth probe proven read-only against production, §2.3 | ❌ untested |
| 8 | OLD DSN captured, shape-validated, fingerprint logged, §2.1 | ❌ |
| 9 | Proxy self-record captured, §3 instrument 2 | ❌ |
| 10 | Dependent service inventory current | ✅ steps 1–7 |
| 11 | `postgres-test` scope ruled, §8.1 | ❌ open |
| 12 | **Exact variable-only application mechanism named and available on CLI 5.6.2** | ❌ open, §10.1 |
| 13 | Runtime neutrality proven at HEAD | ✅ **CLEARED** |
| — | Physical ciphertext copy | Outstanding, **non-blocking** |

**Precondition 13 evidence.** `233d89d` is an ancestor of HEAD, exit 0, no history rewrite. Only later commits are `194d78c` and `fd08e84`, both documentation. `git diff --name-only 59be320..HEAD` returns nine paths: `.gitignore` plus eight markdown. **Zero `.py`.** Nothing under `app/`, `db/`, `tests/`. Remote equals `fd08e84267ea3ffdc5d1da055f0b20c05d270e39`. Empty ahead-log, no modified tracked files.

`Findings_Register_v15.md` appears in that range as a rename endpoint pair, not as a change to v15. Endpoints are not history.

---

## 10. Execution sequence — Option B

Reference for once every §9 precondition clears. Not authorization.

1. Fresh verified dump — satisfied
2. Capture OLD, fingerprint, proxy self-record — §2.1, §3
3. **Regenerate** — `Postgres` → Database view → Credentials tab
4. Capture NEW from the regeneration UI, clear clipboard, re-read variables via CLI — §2.2
5. Authentication probe, OLD then NEW — §2.3
6. Assign axis 1, then axis 2, then state — §1.1
7. Branch by §10.2. **One row per state. No other paths exist.**
8. Post-rotation: scrub `$raw`, `$obj`, `$current`, `$env:OLD_DSN`, `$env:NEW_DSN`, `$env:PGURI` in a **separate turn**
9. Proxy removal returns as available hardening, not a prerequisite

Public networking stays enabled through steps 1–7 because the public proxy is both the dump path and the external-authentication path the diagnostic requires. The original "disable public networking first" step 8 is superseded.

**Interaction with repair.** If §7 is ever executed, its own step one is removing public access. Option B and the repair path do not conflict — the proxy stays up through rotation and comes down as the first act of repair.

### 10.1 Variable application — exact mechanism, and `railway up` is excluded

**The distinction Rev 2 collapsed.** Project deploy doctrine is `railway up --service fantasy-beefs`, which uploads a **working-tree snapshot** — that is the basis of FR-DEPLOY-1's finding that no commit SHA is recoverable from any deployment. Using it to apply a variable change would alter the running code as a side effect of fixing a password, from a tree that currently holds 23 untracked entries, with `.railwayignore` untouched since 07-23.

**`railway up` is prohibited for credential correction.** §4.2.

Current Railway documentation supports this resolution:

- Variable additions and changes are **staged changes that must be applied by a deployment**
- Dependent services must be **manually redeployed** after database credential regeneration
- `railway redeploy` creates a new deployment **from the same source** and is documented as the way to apply environment-variable changes
- `railway restart` restarts the **existing deployment** and reuses its image — it is not the documented staged-change application mechanism

> **Resolution: new or changed Railway variables require applying the staged change by redeploy from the same source. Restart alone is not the authoritative variable-application mechanism. `railway up` is not the mechanism and is prohibited here.**

**FR-DEPLOY-1's Restart note is reclassified.** It recorded that Restart picks up variable changes without a rebuild. That is a prior observation that may have involved a variable already applied before the Restart, or older platform behavior. Reclassified as **needs re-derivation** rather than declared wrong. Routes to the Findings Register.

**Availability on 5.6.2 is unverified.** This is the `railway ssh` lesson repeating: a procedure step depending on a CLI feature nobody checked. Green under §4.4.

```
railway redeploy --help
railway restart --help
```

Precondition 12 clears when the mechanism is named **and** confirmed present on the installed CLI. No mutation test on any service is required or authorized.

### 10.2 Branch table — mirrors §1.2 exactly

| State | Action | Enters §6/§7? |
|---|---|---|
| **S1** | Correct dependent variables → apply by §10.1 → confirm green Success | no |
| **S0** | Wait for propagation, re-read variables, re-probe. **No mutation.** | no |
| **S2** | Preserve OLD access. Diagnose role/variable divergence. **No second credential mutation.** No authorized exit exists — §11.2 q1. | no |
| **S3** | Correct Railway and dependent variables to NEW → apply by §10.1 → verify | no |
| **S4** | §5.4 clock → recovery decision under §6.2 | **yes** |
| **S5** | Transport and service-identity diagnosis — §3 instruments 1 and 2 | no |
| **S6** | §3.1 identity diagnostic. If identity cannot be proved, no mutation. | only if §3.1 step 6 |

**Rev 2 sent S2, S3, S5, and S6 into the recovery branch alongside S4.** S3 is configuration repair with PostgreSQL already accepting NEW; routing it to restore or trust-mode would have been a recovery action taken against a working database. Composition drift between §1.2 and §10, caught in review.

---

## 11. Review record

### 11.1 Answered questions

| Rev | Question | Disposition |
|---|---|---|
| 1 | Keep the parallel clock? | **Yes**, support fully non-blocking, mandatory early exit. §5.4 |
| 1 | Promote "do not Regenerate twice"? | **Yes**, generalized, tool-independent. §4.3 |
| 1 | Prefer replacement unconditionally? | **No.** Event preference, not standing policy. §6.2 |
| 1 | Rule read-only production access? | **Yes.** §4.4 |
| 1 | Second passphrase copy before rotation? | **Yes**, blocking, outranks physical dump copy. §9 |
| 2 | Settle deploy vs restart before rotation? | **Yes**, by documentation review. No mutation test. §10.1 |
| 2 | Does S6 need its own procedure? | **Yes**, bounded. §3.1 |
| 2 | Is the clipboard exception acceptable? | **Yes**, with eight constraints and `Set-Clipboard ''`. §2.2 |

### 11.2 Rev 3 open questions

**1. S2 has no authorized exit. This is the most important open item in the document.**

Surfaced by mirroring §10 to §1.2. In S2 the role holds OLD and Railway variables hold NEW. Three consequences compound:

- Production is reachable, but only until something applies the staged variable change to a dependent
- **The rotation failed.** OLD is the exposed credential the whole exercise exists to retire, and it is still live
- Both candidate exits are currently blocked. Reverting variables to OLD requires hand-editing `POSTGRES_PASSWORD` — prohibited, §4.2. Moving the role to NEW requires `ALTER USER` — prohibited — or trust-mode — not executable, §7

So S2 resolves only by replacement under §6, which is a full service migration to fix a password that never changed.

S2 is also the **most likely** failure state, being the documented desync class. The procedure therefore has no authorized response to its most probable bad outcome. Options: authorize a narrow variable-write path for revert-to-OLD; complete the §7 review so repair becomes available; or accept replacement as the S2 response and record that a failed rotation costs a service migration. Not decided here.

**2. Does S2 change the §6.2 event preference?** If S2 is the likely failure and its only authorized exit is replacement, replacement is not merely preferred — it is close to mandatory for this event, which makes the §7 review optional for rotation and deferrable. That is a cleaner sequence. It also means a likely outcome is a full migration.

**3. Is `Set-Clipboard ''` sufficient clipboard hygiene on Windows 11?** Clipboard history and cloud clipboard sync may retain the value beyond the current clipboard slot. Not verified. If either is enabled, the credential persists somewhere unaudited after capture.
