# Session Handoff — 2026-07-25, session 2

**Headline: Phase B is complete. A verified restore point exists. Rotation is now gated on one document that has not been written.**

---

## 1. What was authorized and what happened

Phase B was already authorized entering the session. It was executed end to end and finished. Nothing else was authorized, and nothing else was done to production.

No commit. No push. No migration. No deployment. No rotation. No networking change.

---

## 2. Phase B — step by step, with the evidence

| Step | Command shape | Result |
|---|---|---|
| Cleanup | `cmd /c del` + `\\?\` | No-op. Neither target existed. |
| DSN | `railway variables list --json` → capture → assign | `True` / `False` / `True`, length 87 |
| B2 | `docker run --rm -e DATABASE_URL ... postgres:18 sh /out/dump.sh` | 243,863 bytes |
| B3 | `pg_restore --list` | 410 TOC entries, **40 tables** |
| B4 | `& $gpg --symmetric --cipher-algo AES256` | 116,922 bytes |
| B5 | `& $gpg --no-symkey-cache --decrypt` | Real prompt, 243,863 exact |
| B6 | Five `cmd /c del` + two `Test-Path` | Both `False` |
| B7 | `Copy-Item` to OneDrive | Both lengths verified |

**Cleanup being a no-op confirms vol. II §19.16.** The 07-25 session-1 failures changed no state — not even a partial dump on disk. They failed before PostgreSQL, on quoting and a malformed DSN.

**The 40-table match is the meaningful B3 number.** The 410 TOC count against a recorded "~399" is within the tilde; table count is the hard figure and it agrees exactly.

**B5 is the step that makes this a restore point.** See §5.

---

## 3. Artifact of record

| Property | Value |
|---|---|
| Path | `C:\FantasyBeefs_Backups\` |
| Filename | `fantasy_beefs_prod_2026-07-25_UTC.dump.gpg` |
| Ciphertext | 116,922 bytes |
| Plaintext | 243,863 bytes |
| Created | 2026-07-25 15:54 UTC (08:54 PDT) |
| Source | `railway`, production, PostgreSQL 18.x, via `hayabusa.proxy.rlwy.net:15707` |
| Encryption | GnuPG 2.4.5 symmetric AES256.CFB, one passphrase, same as 07-23 |
| Schema baseline | **Pre-Spec-1** |
| Offsite | `C:\Users\frase\OneDrive\FantasyBeefs_Restore\` — both 07-23 and 07-25 artifacts |
| Physical copy | **OUTSTANDING** |

Both plaintexts measure 243,863 bytes exactly, because nothing has been deployed since 07-23. The 6-byte ciphertext difference comes from `pg_dump`'s embedded creation timestamp shifting ZLIB output before encryption.

**Two cautions.** The OneDrive copy is not offsite until sync completes — confirm a green check, not a spinner. And the passphrase must not live in that folder in any form; colocating it makes the encryption decorative.

---

## 4. The DSN problem, solved structurally

Four transfer attempts failed across two sessions. Root cause:

`Get-Clipboard` without `-Raw` returns a **string array**, one element per line. `.Trim()` applies via member enumeration, per element. Assigning the resulting array to an environment variable stringifies it, **joined with spaces**. Newlines silently become spaces and the output looks like a plausible single-line value.

Measured signature: 128 characters, whitespace present, no `postgresql://`, `hayabusa` present, `=` present, line count 1.

**The fix removes the clipboard entirely:**

```
$raw = (railway variables list --service Postgres --environment production --json | Out-String)
$obj = $raw.Substring($raw.IndexOf('{')) | ConvertFrom-Json
$env:DATABASE_URL = $obj.DATABASE_PUBLIC_URL
$env:DATABASE_URL.StartsWith('postgresql://')
$env:DATABASE_URL -match '\s'
$env:DATABASE_URL -match 'hayabusa\.proxy\.rlwy\.net:15707/railway$'
```

`IndexOf('{')` strips the CLI version banner. `$raw` and `$obj` hold `PGPASSWORD` — scrub after the dependent step completes, never in the same block.

**The anchored gate is confirmed sound.** The malformed string passed `-match 'hayabusa'`. Only the anchored check — prefix, no whitespace, anchored host/port/database — rejected it. On 07-25 session 1 a substring check let a malformed DSN reach `pg_dump`. Keep the anchored form.

---

## 5. The verification correction that matters most

GnuPG 2.x caches symmetric passphrases in `gpg-agent`. A decrypt that succeeds from cache proves the ciphertext is well-formed and proves **nothing** about whether the passphrase is held.

With one restore point, that gap is the whole exposure. An artifact encrypted under a forgotten passphrase is worse than no artifact, because it presents as coverage.

B5 used `--no-symkey-cache`. A prompt appeared. The passphrase was entered from memory. The plaintext came back at exactly 243,863 bytes.

**Standing rule:** restore-artifact verification requires cache bypass plus operator confirmation that a prompt appeared and was answered. Without both, the step is incomplete. Same family as vol. II §14.7, where a TOC listing was mistaken for proof of restorability.

---

## 6. Four new findings

**FR-DOC-REG-1 — RULED.** The Findings Register is two disjoint volumes. A heading comparison returned every heading from both files, meaning zero overlap. Sections 1–13 exist only in `v12_2`: the money-model rulings, the five-spec split, the locked build order, Passes 1–5, the consolidated audit package. The tracked lineage v14 → v15 → v16 → v17 begins at Section 14. Both volumes have a Section 14 with different binding content. Ruled Option A — **vol. I / vol. II citation convention immediately**, renumbering deferred.

**FR-PROC-CLIP-1 — CLOSED** by the design change in §4.

**FR-INFRA-DOCK-1 — OPEN, unverified.** `fb-test-pg`, `postgres:16`, container `58e009fb95bf`, stopped 6 days, mapped `5433:5432` — the same bind as the protected `pg-fantasy-test`. It appears in no artifact. Nothing is broken because two containers cannot bind one port, but a harness trusting `localhost:5433` trusts a port with two possible occupants. Same shape as the Guard 5 defect: a safety check aimed at the wrong target. **Do not start it.**

**FR-SEC-DB-5 — OPEN, unverified.** `fantasy-beefs_9ff096b.zip`, 25,991,636 bytes, unencrypted, dated 07-24, sitting beside the encrypted database artifacts. `c353d2b` removed hardcoded connection strings from the working tree but not from Git history, so if the archive contains `.git` it carries them. 26MB is consistent with that. Outside OneDrive, so exposure is bounded to this machine. Two commands in the opener settle it.

---

## 7. What was corrected — five self-corrections

1. **The date.** Claude asserted 07-26, inferring it from the 07-25 opener's filename. The HEAD commit timestamp, the dump's `LastWriteTime`, and the clock all read 07-25. Claude used the wrong date to rename a backup artifact in the same message that explained why wrong dates on backups are traps. Corrected before encryption. **Opener naming convention changed** to authored-date.

2. **Register lineage.** Claude read the range-diff arrow `v15.md => v17.md` as history and concluded v16 was never tracked. That arrow is an endpoint pair from rename detection. `git log --follow` showed v14 → v15 → v16 → v17. **Rule: endpoints are not history.**

3. **Command sequencing.** Claude shipped `Remove-Variable raw, obj` in the same block as the assignment that depended on `$obj`. The scrub ran, the assignment did not. **Rule: destructive cleanup goes in its own turn.**

4. **Delegation.** Claude proposed sending B3 to Claude Code because it needs no credential, then withdrew it. B3 is three lines; the MSYS path-rewriting risk that cost two cycles on 07-23 outweighs any benefit. Claude Code belongs on multi-file document work with no secrets and no shell-state dependency.

5. **Four wrong hypotheses about the malformed DSN** — clipboard collision, keyword/value conninfo, `psql` command line, sealed variable. Each was killed in one probe round by a pre-registered interpretation table. The guesses were wrong; the method contained them.

---

## 8. On the independent review of the Phase B block

The review asserted the "B2 through B7" block was absent from retrievable materials and offered a five-step reconstruction as the supported shape.

The block was **§6 of `FantasyBeefs_Session_Handoff_2026-07-25.md`**, retrieved at session open. It has six steps.

The five-step summary **omitted B7, the offsite copy** — the one step addressing the sole-restore-point condition the register had already recorded in vol. II §19.7. Following the review as written would have reproduced the exact condition it was meant to guard against.

The same review correctly identified that "six outputs" was a Claude fabrication with no provenance in any artifact. That half was accepted.

**Both halves recorded.** A reviewer's characterisation of a document is a claim to verify, not accept — and a reviewer can find a real defect and assert a false absence in the same message.

---

## 9. Sequencing lesson

Four consecutive turns of document-integrity recon ran before Phase B started, while production had no fresh restore point.

Each check was individually cheap and individually justified. FR-DOC-REG-1 came out of it and is a real finding. But the aggregate displaced the authorized task for most of the session.

**Recon that does not gate the authorized work should be deferred to where it does not compete with it.** The deferred-verification block in the opener is that discipline applied.

---

## 10. Verified tool facts

**GnuPG** — `C:\Program Files\Git\usr\bin\gpg.exe`, 2.4.5, MSYS2-built, the only `gpg.exe` on the machine per recursive scan of both Program Files trees. By elimination it produced the 07-23 artifact. Not on PATH; use a session variable and `& $gpg`. Windows absolute paths only — POSIX paths get MSYS-rewritten. `gpgconf.exe` co-located. No permanent PATH edit was made.

**Railway CLI** — 5.6.2 installed, 5.28.0 available, **upgrade deliberately deferred** as an unmeasured variable mid-security-sequence. Linked service is `fantasy-beefs`, so `--service Postgres --environment production` is mandatory. `DATABASE_PUBLIC_URL` present, not sealed, length 87. `RAILWAY_TCP_PROXY_DOMAIN` and `RAILWAY_TCP_PROXY_PORT` exist and are the proxy's own self-record — the instrument for confirming proxy survival after rotation.

**Docker** — engine 29.6.1, `postgres:18` cached locally.

---

## 11. Unresolved decisions carried forward

| Item | State |
|---|---|
| Desync recovery procedure | **Not drafted. Six questions. Gates Phase C.** |
| FR-SEC-DB-1 steps 8–11 | Dump precondition satisfied. Gated on desync procedure. |
| Physical offsite copy | Outstanding. Destination not chosen. |
| Railway support tier | Unknown. Needed for desync answer 4. |
| `postgres-test` disposition | Rotate vs delete. Undecided. |
| App variable Path A vs Path B | B preferred, unauthorized (production config change) |
| FR-DOC-REG-1 renumbering | Deferred. Section 20 append is step one. |
| `v12_2` tracking status | Unknown. Two commands pending. |
| FR-INFRA-DOCK-1 | Open, unverified |
| FR-SEC-DB-5 | Open, unverified |
| Guard 5 re-derivation | Mechanism sound, reference value wrong |
| `Plan.md` / `Package.md` untracked | Governing artifacts, no Git history, no remote copy |
| Railway path-correction wording | Agreed. Three artifacts unamended. |
| Architecture v15 HTML | Change spec issued 07-25. Regeneration outstanding. |
| Pro-plan upgrade | Raised, deliberately not ruled |
| Railway CLI upgrade | Deliberately deferred |
| FR-8.7 closure | Six items, unchanged, behind the security stage |

---

## 12. Repository state at close

HEAD `233d89db373664e08b64636e933f56a2d926fa21`. Local, tracking ref, and remote identical. `git log origin/remediation/foundation-phase-1..HEAD` empty. No tracked working-tree changes. Untracked list unchanged from session open — 24 documentation files plus `archive/`.

Runtime source unchanged from `59be320`, proven at `233d89d` by commit range plus path diff. Four paths, all documentation or `.gitignore`, zero `.py`.

**Nothing deployed. No migration run. No credential rotated.**
