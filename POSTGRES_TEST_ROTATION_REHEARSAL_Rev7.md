# `postgres-test` Credential Rotation Rehearsal

**Rev 7, DRAFT. Authored 2026-07-25. Returned at Rev 1–6; corrections applied. Awaiting seventh review.**

Companion to `FR_SEC_DB_1_DESYNC_RESPONSE_PROCEDURE_DRAFT_Rev3.md`.

---

## 0. Rev 6 → Rev 7 changelog

| # | Correction | Section |
|---|---|---|
| 1 | **M9 added** — authenticates the *current* `DATABASE_PUBLIC_URL`. M1 is historical after T1 | §3.1 |
| 2 | **`R(Tn)` snapshot primitive** — one control-plane read per transition, before every derived measurement | §3.2 |
| 3 | **Mutation 3 gate widened** — M7 equality **and** no unresolved v2/v5/v6 divergence | §6.1 |
| 4 | **S0–S6 demoted** to a base role-transition label; surface consistency recorded separately | §4.1 |
| 5 | **Mechanism A rewritten as measured behavior.** Nested shell heredoc retired, CRLF recorded as cause | §5.2, §6 |
| 6 | **M6's byte count is the present-and-nonempty gate**, replacing the shell `-z` test lost with the wrapper | §3.1, §6.1 |
| 7 | **Negative-control rule** adopted as a testing standard | §3.4 |
| 8 | Teardown uses **verified service and volume IDs**; bare `railway delete` prohibited | §6.2 |
| 9 | Fidelity upgraded from inference to **measured image string and psql version** | §2 |
| 10 | Preconditions 1, 5, 6 **cleared with evidence** | §5 |

---

## 1. Scope

> **The rehearsal validates the database-side transition model and recovery mechanics. It does not validate the complete production configuration model.**

Value 4 — `fantasy-beefs`'s hand-typed literal `DATABASE_URL` — cannot be exercised here, because nothing references `postgres-test`. That is exactly why it is safe to use.

**Production S1 still requires a mandatory manual dependent correction and deployment step even if this rehearsal is flawless.**

**Not tested:** value 4 propagation · dependent service behavior · the twelve hand-rolled migration scripts · the production dump and restore path · anything about `Postgres` itself.

---

## 2. Fidelity record — measured, not inferred

| Property | `Postgres` | `postgres-test` | Match |
|---|---|---|---|
| **Image** | `ghcr.io/railwayapp-templates/postgres-ssl:18` | identical string | ✅ measured |
| **psql client** | `18.4 (Debian 18.4-1.pgdg13+1)` | identical string | ✅ measured |
| Server version | `PostgreSQL 18.4 (Debian 18.4-1.pgdg13+1)` | identical | ✅ |
| Railway SSH | `ssh-ok` | `ssh-ok` | ✅ |
| OS user | `root` | `root` | ✅ |
| Socket trust, `env -u PGPASSWORD ... -w` | succeeds | succeeds | ✅ |
| `pg_hba_file_rules` | 7 rows, lines 117–128 | identical, same line numbers | ✅ |
| Logging × 7 | `none`/`error`/`-1`/`-1`/`0`/`stderr`/`off` | identical | ✅ |

**The image string replaces an inference.** Earlier revisions argued same-image-generation from matching HBA line numbers. Both services run the same named image. Neither is stock `postgres:18`.

**Bench fidelity, stated honestly.** Mechanism A was proven on stock `postgres:18`. Production runs `postgres-ssl:18`. The transfer rests on the **psql client version being byte-identical**, `18.4 (Debian 18.4-1.pgdg13+1)`, since mechanism A runs psql inside the target container. `\getenv` requires psql 14 or later and is therefore available.

**Service identities, measured 2026-07-25:**

| Resource | Service ID | Volume | Volume ID |
|---|---|---|---|
| `postgres-test` — **the target** | `f03178f3-ecce-4a12-9d58-39125e41a161` | `postgres-volume-F_kl` | `9f491b83-81f5-4609-bcfd-7b223db06794` |
| `Postgres` — **never touch** | `cd0ba357-63dc-4c9e-800f-362b004246e7` | `postgres-volume` | `16983665-ead5-4225-9abf-7bfd29a08b96` |
| `fantasy-beefs` | `9400fc77-6050-4f34-b6a2-d5a2f963716a` | none | — |

`f03` against `cd0`, `9f4` against `169`. Unlike `postgres-volume-F_kl` against `postgres-volume`, these cannot be misread. **Today's IDs are evidence and a cross-check, not permission to assume they remain current** — §6.2 requires a fresh capture immediately before deletion.

---

## 3. Six credential-bearing surfaces

| # | Value | Surface | Measurable here |
|---|---|---|---|
| 1 | Role credential | `pg_authid` | yes |
| 2 | Railway `PGPASSWORD` | `railway variables list` | yes |
| 3 | Container credential | `$PGPASSWORD` inside the container | yes |
| 4 | Dependent literal | `fantasy-beefs` `DATABASE_URL` | **no** — no dependents |
| 5 | Regeneration-UI display | Credentials tab | yes, **representation-typed** |
| 6 | Railway `DATABASE_PUBLIC_URL` credential | `railway variables list` | yes |

**Values 2 and 6 come from one command and remain distinct surfaces.** One is a discrete variable, the other a credential embedded in a composed URL.

**Value 5 has two possible representations and they are not interchangeable.**

| Type | Captured as | Consequences |
|---|---|---|
| **v5-DSN** | `PT_NEW_DSN` | M5 compares v6 to v5 by string. M2 uses the DSN form. |
| **v5-password** | `PT_NEW_PW` | M5 cannot compare v6 to v5 by string. M2 uses the discrete-variable form. v5 ↔ v6 is established functionally by **M2 and M9** both authenticating. |

**Never coerce one representation into the other to make a comparison run.** Composing a DSN from a password reintroduces percent-encoding hazards; parsing a password out of a DSN reintroduces them in reverse.

**Never infer equality between any pair of surfaces.** That applies to two fields of one JSON object as much as to two services.

### 3.1 Measurement kit

| ID | Probe | Relation | Cadence |
|---|---|---|---|
| **M1** | External auth, `PT_OLD_DSN` | **T0: v1 == v6.** Later: does the role still accept the pre-rotation credential | every transition |
| **M2** | External auth, value 5 | **v1 == v5** | T1 onward |
| **M3** | In-container TCP, ambient credential | **v1 == v3** | every transition |
| **M4** | In-container socket connect | **control** | every transition |
| **M5** | `R(Tn).DATABASE_PUBLIC_URL` vs captured DSNs | **v6 vs v5 and OLD** — v5-DSN only | every transition |
| **M6** | Container byte count and digest | **v3 present, nonempty, and changed?** | every transition |
| **M7** | Full-digest equality, `R(Tn).PGPASSWORD` vs container | **v2 == v3** | every transition |
| **M8** | External auth, discrete env vars carrying `R(Tn).PGPASSWORD` | **v1 == v2** | T0, T1, T2, then on demand |
| **M9** | External auth, **current** `R(Tn).DATABASE_PUBLIC_URL` | **v1 == current v6** | every transition |

**Cadence is stated by name, never by count.**

**Why M9 exists.** M1 is captured at T0 and becomes historical after Mutation 1. Without M9, nothing functionally tests the *current* `DATABASE_PUBLIC_URL` after Regenerate. At T0, M1 and M9 use the same candidate — that duplication is calibration, not waste.

**M4 is a control, not a probe.** Socket trust bypasses passwords, so it succeeds regardless of credential state. An M4 failure means the apparatus is broken.

**M6 does three jobs.** Byte count zero means value 3 is empty — a **gate condition**, replacing the shell `-z` test that disappeared with the heredoc wrapper. Digest compared against the previous transition detects change. Digest compared against `R(Tn)` is M7.

### 3.2 `R(Tn)` — the snapshot primitive

**One control-plane read at the start of every transition, before any derived measurement.**

```
$raw = (railway variables list --service postgres-test --environment production --json | Out-String)
$obj = $raw.Substring($raw.IndexOf('{')) | ConvertFrom-Json
```

**M5, M7, M8, and M9 all derive from that single `$obj`.** Do not re-read mid-transition.

This guarantees v2 and v6 were observed at the same control-plane moment, and prevents a subtler failure: a full SHA-256 comparison against a stale `$obj` from the previous transition is *worse* than a weak one, because it looks rigorous. Rev 6 made "M5 happens first" an accidental requirement of listing order. It is now a named step.

The proxy self-record — `RAILWAY_TCP_PROXY_DOMAIN`, `RAILWAY_TCP_PROXY_PORT` — comes from the same snapshot.

`$raw` and `$obj` hold credentials. Scrub in a separate turn, after every dependent measurement.

### 3.3 Probe forms — stdin transports only

**Prohibited, both measured mangling their SQL:** `docker ... sh -c 'psql ... -c "..."'` and `railway ssh ... -Atc "..."`.

**Prohibited, measured this session:** any **nested shell heredoc** over this transport. PowerShell here-strings emit CRLF — verified by `od -c` returning `l i n e 1 \r \n` — so `sh` compares `SQL\r` against `SQL`, never terminates, and feeds the terminator line to psql as a statement. psql itself tolerates CRLF; only exact-terminator matching does not. **Plain `sh`-over-stdin remains valid and is not implicated** — M6 depends on it.

**M1, M2 when v5 is a DSN, and M9** — set `$env:PGURI` immediately before each call:

```
@'
SELECT 1;
'@ | docker run --rm -i -e PGURI --entrypoint sh postgres:18 -c 'psql "$PGURI" -At'
$LASTEXITCODE
```

`0` success, `2` connection or authentication failure. For M9, `$env:PGURI = $obj.DATABASE_PUBLIC_URL` from the current `R(Tn)`.

**M3:**

```
@'
SELECT 1;
'@ | railway ssh --service postgres-test --environment production psql -U postgres -d postgres -w -At
```

**M4** — control, all tokens space-free:

```
railway ssh --service postgres-test --environment production env -u PGPASSWORD psql -h /run/postgresql -U postgres -w -Atl
```

**M5** — v5-DSN path only:

```
$cur = $obj.DATABASE_PUBLIC_URL
$cur -ceq $env:PT_OLD_DSN
$cur -ceq $env:PT_NEW_DSN
```

If v5 is password-only, skip the second comparison and record v5 ↔ v6 as established functionally by M2 and M9.

**M6:**

```
$out = @'
printf %s "$PGPASSWORD" | wc -c
printf %s "$PGPASSWORD" | sha256sum | cut -d" " -f1
'@ | railway ssh --service postgres-test --environment production sh
$c_len = ($out -match '^\d+$')[0]
$c_dig = ($out -match '^[0-9a-f]{64}$')[0]
```

The regex filters discard the CLI banner and connection lines without depending on their position.

**M7** — full digest, computed to match M6 exactly:

```
$r_len = [System.Text.Encoding]::UTF8.GetByteCount($obj.PGPASSWORD)
$r_dig = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::HashData([System.Text.Encoding]::UTF8.GetBytes($obj.PGPASSWORD))).Replace('-','').ToLower()
$c_dig -ceq $r_dig
[int]$c_len -eq $r_len
$c_dig.Substring(0,8)
```

The first line is the **gate**. The second distinguishes a whitespace artifact from a real mismatch. The third is the **matrix entry only** — 32 bits must never authorize a credential mutation.

`.ToLower()` is required: `sha256sum` emits lowercase, `BitConverter` uppercase. `UTF8.GetByteCount` matches `wc -c`; `.Length` counts .NET characters against Unix bytes.

**M8** — external auth with `PGPASSWORD`, **no DSN assembled**:

```
$env:PGPASSWORD = $obj.PGPASSWORD
$env:PGHOST = $obj.RAILWAY_TCP_PROXY_DOMAIN
$env:PGPORT = $obj.RAILWAY_TCP_PROXY_PORT
$env:PGUSER = 'postgres'
$env:PGDATABASE = 'railway'
@'
SELECT 1;
'@ | docker run --rm -i -e PGPASSWORD -e PGHOST -e PGPORT -e PGUSER -e PGDATABASE --entrypoint sh postgres:18 -c 'psql -w -At'
$LASTEXITCODE
```

psql reads discrete variables — nothing composed, nothing parsed. **When v5 is password-only, M2 uses this same form.** Scrub `$env:PGPASSWORD` in a separate turn.

### 3.4 TESTING STANDARD — negative controls

> **When a probe's success would look identical under a permissive path, it is not evidence until the same path has been shown to reject a known-invalid input.**

Earned by measurement. A bench `SELECT 1` over `-h 127.0.0.1` returned `1` and proved nothing, because line 119 is `host all all 127.0.0.1 trust`. The identical output over `-h 172.17.0.3` became evidence **only** after `PGPASSWORD=definitelywrong` was shown to fail on that same path.

Applies to authentication probes, authorization checks, and signature or hash verification. Does not apply to configuration reads, where a wrong answer is self-evident.

**M1, M2, M8, M9 are all authentication probes.** Each is subject to this standard on any path whose enforcement has not already been demonstrated.

---

## 4. Transition matrix

| | T0 | T1 Regenerate | T2 redeploy | T3 repair | T4a restart | T4b redeploy |
|---|---|---|---|---|---|---|
| `R(Tn)` taken | | | | | | |
| M1 (T0: v1==v6) | | | | | | |
| M2 v1 == v5 | n/a | | | | | |
| M3 v1 == v3 | | | | | | |
| M4 control | | | | | | |
| M5 v6 vs v5/OLD | | | | | | |
| M6 len / changed | | | | | | |
| M7 v2 == v3 | | | | | | |
| M8 v1 == v2 | | | | on demand | on demand | on demand |
| M9 v1 == current v6 | | | | | | |
| **Base role state** | n/a | | | | | |
| **Surface status** | | | | | | |

### 4.1 Base state and surface status are separate records

S0–S6 was designed when fewer surfaces were distinguished. It cannot encode a state where the role matches v5 while v2 and v6 hold different values. **Do not redesign S0–S6 here.**

**Record two things.**

*Base role state* — S0 through S6, describing the role's relationship to OLD and to the intended new credential, per the desync procedure's classifier.

*Surface status* — the measured equalities, written explicitly:

```
Base state: S1
Surface status: v2=v3, v5=v6, v2≠v5  → DIVERGENT
```

> **INVARIANT: no S0–S6 state containing unresolved surface divergence is a clean success state.**

Calling the example above "S1 SUCCESS" would erase the rehearsal's main result. Rev 4 of the desync procedure rebuilds the production classifier from measured behavior rather than guessing it now.

### 4.2 What each transition answers

**T1** — does Regenerate produce S1 or S2 here. M5 answers whether v6 and v5 agree; M7 whether v2 tracked; M8 and M9 locate a divergence rather than merely detecting one.

**T1 → T2** — if M6's digest is unchanged at T1 and changed at T2, the container environment updates only on deployment. During a live S2 the container would hold OLD, and repairing to `$PGPASSWORD` would set the role to the password that already works.

**T2** — gates Mutation 3, §6.1.

**T3 → T4a** — does a socket-set credential survive a restart of the existing deployment.

**T4a → T4b** — does a fresh deployment change v3 or role behavior. Together these settle FR-DEPLOY-1 empirically.

**Do not describe a redeploy result as "survived a restart."**

---

## 5. Preconditions

| # | Precondition | Status |
|---|---|---|
| 1 | Fidelity verified | ✅ **CLEARED** §2 |
| 2 | This procedure reviewed | ❌ Rev 7 |
| 3 | Zero inbound references across **all** non-database services | ❌ execution-time, §5.1 |
| 4 | Zero user tables | ❌ execution-time, §5.1 |
| 5 | Mechanism A guard proven to block **and** to install the intended credential | ✅ **CLEARED** §5.2 |
| 6 | Teardown mechanism verified to exist | ✅ **CLEARED** §5.3 |
| 7 | Value 5 representation determined | ❌ §10 q3 |
| 8 | Proxy self-record captured | ❌ at T0 |
| 9 | `PT_OLD_DSN` captured, shape-validated | ❌ at T0 |

**No dump precondition.** Zero user tables, and the dump path is already proven on production.

### 5.1 Executable precondition instruments

**Precondition 4 — zero user tables.** Both databases:

```
@'
SELECT current_database(), count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');
'@ | railway ssh --service postgres-test --environment production psql -h /run/postgresql -U postgres -d railway -At
```

Repeat with `-d postgres`. Expected `railway|0` and `postgres|0`. **Any nonzero count aborts.**

**Volume size is not a data indicator.** Railway reports `postgres-volume-F_kl` at 134.92 MB, while both databases measure **7,678 kB** — matching the 07-25 baseline exactly — and `du -sh /var/lib/postgresql/data` returns **47M**. Production shows the same inflation: 221.6 MB reported against a 243,863-byte dump. The 47M-versus-135M gap is unexplained, likely filesystem reserve or deleted-but-open files, and gates nothing. **Do not read the Railway volume figure as evidence of stored data.**

**Precondition 3 — full inventory first, then every consumer.**

```
railway status
```

Today: `fantasy-beefs`, `Postgres`, `postgres-test`. **If any additional non-database service exists at execution time, it must be checked too.**

For each non-database service:

```
$raw = (railway variables list --service <name> --environment production --json | Out-String)
$raw -match 'postgres-test'
$raw -match 'postgres-ym7q'
$raw -match 'sakura'
```

Expected `False`, `False`, `False`. Then:

```
$obj = $raw.Substring($raw.IndexOf('{')) | ConvertFrom-Json
$obj.DATABASE_URL -match 'hayabusa\.proxy\.rlwy\.net:15707'
```

Expected `True`. **Any match on the first three, or a failure on the fourth, aborts.**

Record: *every current non-database service has been checked for references to `postgres-test`.*

### 5.2 Precondition 5 — CLEARED by measurement

Bench: disposable `postgres:18`, psql `18.4 (Debian 18.4-1.pgdg13+1)`, identical client build to both Railway services.

| Property | Evidence |
|---|---|
| Blocks when the guard is unsatisfied | `ABORT-GUARD-NOT-ESTABLISHED`; verifier `ptQJH` **unchanged** |
| Blocks when `PGPASSWORD` is absent | `ABORT-PGPASSWORD-ABSENT`; verifier unchanged; `\q` exits cleanly |
| Permits when satisfied | `REPAIR-APPLIED`; verifier `ptQJH` → `2bXfm` |
| **Installs the intended value unmangled** | `guard1` authenticates over `172.17.0.3` — a path where `definitelywrong` is rejected |
| `\getenv` · `:{?newpw}` · `\gset` · `\if` · `:'newpw'` | all exercised on psql 18.4 |
| Direct PowerShell → psql stdin | no error, no wrapper |

**The last row took four attempts and is the one that matters.** A changed verifier proves a statement ran, not that the intended credential landed — SCRAM re-salts on every set, so a mangled or truncated value would also move it. Only the authenticated round trip, with its negative control, distinguishes them.

### 5.3 Precondition 6 — CLEARED

`railway service delete --service <ID> --environment production` and `railway volume delete --volume <ID>` both exist on CLI 5.6.2, read from the installed binary.

`--2fa-code` is required for non-interactive deletion when 2FA is enabled. **Run teardown interactively, without `-y`**, so the confirmation dialog appears. On the most destructive step, a prompt is a feature.

---

## 6. Execution sequence

Each step is its own turn. Take `R(Tn)` first. Record the matrix before proceeding.

**T0.** Take `R(T0)`. Capture `PT_OLD_DSN` and the proxy self-record from it. Run **M1, M3, M4, M5, M6, M7, M8, M9**. **Calibrate per §6.3 before proceeding.**

**Mutation 1 — Regenerate.** `postgres-test` → Database view → Credentials tab → Regenerate.

**T1.** Take `R(T1)`. Capture value 5 in whichever representation the UI provides, including `Set-Clipboard ''`. Run **M1–M9**. Record base state and surface status.

**Mutation 2 — apply the variable change.**

```
railway redeploy --service postgres-test --environment production
```

Never `--from-source`. Never `-y`. Never `railway up`.

**T2.** Take `R(T2)`. Run **M1–M9**. Record base state and surface status.

### 6.1 GATE — Mutation 3 requires equality **and** consistency

> **Mechanism A installs value 3 into the role. It may execute only when all three hold at T2:**
>
> 1. **M6 byte count is nonzero** — value 3 is present and not empty
> 2. **`$c_dig -ceq $r_dig` returns `True`** — full-digest equality, v2 == v3
> 3. **No unresolved divergence among v2, v5, v6** — surface status is consistent

Any failure → **stop and bank the finding.** A T2 state of `v2 = v3` with `v5` and `v6` elsewhere passes equality but means the authoritative surface is unknown. Executing mechanism A there would choose a winner by mutation rather than by measurement — and the service is disposable, so there is no reason to force the experiment past the exact condition it exists to discover.

**Mutation 3 — mechanism A, direct to psql, no shell wrapper.**

```
@'
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
'@ | railway ssh --service postgres-test --environment production psql -h /run/postgresql -U postgres -d postgres -At
```

**Four safety properties, all measured.**

`\if :guard_ok` is a real branch — `ALTER ROLE` is unreachable unless the read-back returned `panic`. `:{?newpw}` blocks an absent variable; **emptiness is caught upstream by M6's byte count**, since `\getenv` leaves the variable set when the environment variable exists but is empty. `\getenv` + `:'newpw'` puts SQL-literal quoting in psql's hands, so a credential containing a quote cannot reshape the statement. The PowerShell `@'...'@` does not expand, and **no shell parses the program at all** — psql reads it directly from stdin.

**Abort on any `ABORT-` marker.** `REPAIR-APPLIED` is the only success token.

**T3.** Take `R(T3)`. Run **M1–M7 and M9**, M8 on demand. Record base state and surface status.

**Mutation 4a — restart.**

```
railway restart --service postgres-test --environment production
```

**T4a.** Take `R(T4a)`. Run **M1–M7 and M9**, M8 on demand.

**Mutation 4b — redeploy.**

```
railway redeploy --service postgres-test --environment production
```

**T4b.** Take `R(T4b)`. Run **M1–M7 and M9**, M8 on demand.

### 6.2 Mutation 5 — teardown

Own turn. Six steps, none improvised.

> **NEVER `railway delete`, `railway rm`, or `railway remove`. Those are project-level commands and would destroy `Postgres` along with everything else.**
>
> The only permitted primitives are `railway service delete` and `railway volume delete`, with IDs.

1. **Re-verify zero inbound references** — repeat §5.1 precondition 3 in full, including a fresh `railway status`.
2. **Re-capture IDs.** Today's values are a cross-check, not permission.

```
railway service list --json
```

```
railway volume list --json
```

3. **Confirm the relationships still hold.** Target: service `f03178f3-…` named `postgres-test`, volume `9f491b83-…` named `postgres-volume-F_kl`. Never: service `cd0ba357-…` named `Postgres`, volume `16983665-…`. **If any ID has changed, stop** — a service was recreated and the assumptions behind this procedure need re-derivation.
4. **Delete the service, interactively, by ID:**

```
railway service delete --service f03178f3-ecce-4a12-9d58-39125e41a161 --environment production
```

Answer the confirmation. Do not pass `-y`.

5. **Confirm volume disposition.** `railway volume list --json`. If `9f491b83-…` remains, delete it by ID, interactively.
6. **Post-delete verification:**

```
railway status
```

Expected: `fantasy-beefs` and `Postgres` only. **If `Postgres` is absent, stop immediately** — the encrypted dump becomes the operative artifact.

### 6.3 T0 calibration

At T0, `PT_OLD_DSN` is the current `DATABASE_PUBLIC_URL`, so M1 and M9 use the same candidate.

```
M1, M9 succeed  →  v1 == v6
M3 succeeds     →  v1 == v3
M8 succeeds     →  v1 == v2
M7 equal        →  v2 == v3
therefore          v1 = v2 = v3 = v6
```

A role has exactly one password, so the transitivity holds. **All must agree before proceeding.** Running M8 and M9 here calibrates those instruments.

| Observation | Reading |
|---|---|
| M7 unequal, M8 succeeds, M3 succeeds | M7 instrument defective |
| M7 unequal, M8 fails, M1 succeeds | v2 differs from the live role while v6 authenticates — **real Railway divergence** |
| M8 fails at T0 while M1 succeeds | **Stop. Do not classify.** M8 is uncalibrated at that moment; check the probe before believing the finding. |

> **A failed diagnostic does not prove the phenomenon it was designed to detect until the diagnostic itself has been calibrated.**

M2 is `n/a` at T0 — no value 5 exists yet.

---

## 7. Abort conditions

1. **M4 fails.** Apparatus broken or socket trust lost.
2. **T0 calibration unresolved.**
3. **Any of the three §6.1 gate conditions fails at T2.**
4. Any `ABORT-` marker from mechanism A.
5. Preconditions 3 or 4 fail at execution-time verification.
6. `RAILWAY_TCP_PROXY_DOMAIN` or `_PORT` changes unexpectedly.
7. Any service or volume ID changed since §2.
8. Any unanticipated exit code.

**Abort means stop and record, not roll back.** The service is disposable; a botched rehearsal is deleted, and the failure is the finding. Do not improvise — improvising is the behavior being trained out.

---

## 8. What a clean result licenses

**Does:** writing §7 of the desync procedure with a known-authoritative value source · the classifier validated and rebuilt from measured behavior · desync-procedure precondition 5 cleared · `postgres-test` deleted, closing FR-SEC-DB-4 · FR-DEPLOY-1's restart-versus-redeploy question settled · the v2 / v5 / v6 consistency questions answered.

**Does not:** skipping the value-4 dependent correction in production S1 · rotating production before the remaining blockers clear — second passphrase copy, desync-procedure review · treating production-specific state as tested.

---

## 9. Optional, post-T4b, pre-teardown — mechanism C

Only after every gate-producing measurement is banked. C answers no blocking question; A is proven end to end and fits better, since `\password` cannot read `$PGPASSWORD` from the environment and would require transporting the secret inward.

Run `\password` over piped stdin with a verifier read **before and after**, plus an authenticated round trip subject to §3.4. Skip entirely if anything earlier aborted.

---

## 10. Open questions

1. **Does Regenerate behave the same on a service with no dependents?** If Railway's propagation walks reference edges, having none may itself change the outcome. Unfalsifiable here by construction — the fidelity gap the surrogate's own safety creates.
2. **Does psql `\q` accept an exit-status argument on 18?** Not relied upon; the abort path is proven by the marker plus an unchanged verifier.
3. **What does the Credentials tab display, and when?** **Precondition 7.** Railway's own support statements say the current password can be found there, so it likely shows a credential at rest — but whether it presents a full DSN or a password alone, and whether that shape differs before and after Regenerate, is unverified. If it shows a credential at rest, v5 can be compared against v2 and v6 on **production today**, read-only, independent of this rehearsal. Third-party UI pre-check before any navigation instruction.
4. **Why does `du` report 47M against Railway's 134.92 MB?** Unexplained, gates nothing. `df -h /var/lib/postgresql/data` would settle it.
