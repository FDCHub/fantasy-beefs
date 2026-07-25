# FR-SEC-DB-1 Rev 3 — Precondition Clearance Delta

**Authored 2026-07-25. Attach alongside `FR_SEC_DB_1_DESYNC_RESPONSE_PROCEDURE_DRAFT_Rev3.md`.**

Rev 4 not cut. These clearances fold into Rev 4 after the third review, so that one rewrite absorbs both the review corrections and these.

---

## Precondition 6 — CLEARED

`railway ssh` reachability and key registration proven on CLI 5.6.2.

```
railway ssh keys
railway ssh --service Postgres --environment production echo ssh-ok
```

**Evidence.** One key registered: `ssh-ed25519`, fingerprint `SHA256:COMOCpfSHVrTnWOXd5eOA8XApCSPPeNd/fSQozcUGWQ`, source `C:\Users\frase\.ssh\id_ed25519.pub`. The probe returned `ssh-ok` and closed cleanly against `ssh.railway.com`.

**Consequence.** §7 trust-mode repair is **reachable**. Element 4 of §7.3 — exact file and path verification on the running image — is now executable as a read-only step under §4.4, without waiting for an incident.

**Cosmetic.** The registered key's label is `fraser.d.coleman@gmail. cat ~/.ssh/id_ed25519.pub`. A paste accident absorbed a command into the comment field. Harmless; useless as a label if a second key is ever registered.

**No action.** An unregistered `ssh-rsa` key `frase@tt` exists locally. Not registered with Railway.

---

## Precondition 12 — CLEARED

Exact variable-only application mechanism named and confirmed present on CLI 5.6.2.

```
railway redeploy --service fantasy-beefs --environment production
```

**Read from the installed binary, not documentation.** `railway redeploy` = "Redeploy the latest deployment of a service." Its `--from-source` flag = "Pull and deploy the latest commit or image from the configured source, **instead of** redeploying the existing deployment."

**So the default touches no source.** Pulling new source is opt-in. This is stronger than the documentation summary, which described redeploy as creating a new deployment from the same source.

`railway restart` = "Restart the latest deployment of a service (without rebuilding)." The help text says nothing about variables. Redeploy creates a new deployment and therefore a fresh environment; restart may reuse the existing one. Redeploy wins on certainty.

### Prohibitions added to §4.2

| Prohibited | Why |
|---|---|
| `railway up` for credential correction | Uploads a working-tree snapshot. Changes running code as a side effect of fixing a password. |
| `railway redeploy --from-source` | Pulls new source. Same defect as `railway up`, reached by a flag. |
| `-y` / `--yes` on redeploy or restart during an incident | The default confirmation dialog is a free check against acting on the wrong service |
| Omitting `--service` | Both commands default to the **linked** service, which is `fantasy-beefs`, not `Postgres` |

Both commands support `--json`, useful for logging exit state in the incident record.

---

## Rev 3 open question 2 — position changed

**Previously leaning:** defer the §7 review, on the possibility that repair was unreachable.

**Now:** complete the §7 review before rotation.

Reasoning. SSH reachability was the one precondition that could have made repair fictional, and it is satisfied. S2 — the documented desync class and the most likely failure — has no authorized exit without either a variable write or trust-mode. Leaving §7 unreviewed means the most probable bad outcome resolves only by full service migration.

**This keeps precondition 5 blocking rather than retiring it.** The cost is a review; the alternative cost is migrating a database to fix a password that never changed.

---

## Precondition status after this delta

| # | Precondition | Status |
|---|---|---|
| 1 | Verified encrypted dump, real passphrase prompt | ✅ |
| 2 | Offsite ciphertext copy | ✅ |
| 3 | **Second durable passphrase copy** | ❌ **BLOCKING** |
| 4 | Procedure reviewed | ❌ Rev 3 awaiting third review |
| 5 | Trust-mode reviewed | ❌ **BLOCKING** — see above |
| 6 | `railway ssh` reachability and key registration | ✅ **CLEARED** |
| 7 | Auth probe proven read-only against production | ❌ untested |
| 8 | OLD DSN captured, validated, fingerprinted | ❌ at rotation |
| 9 | Proxy self-record captured | ❌ at rotation |
| 10 | Dependent service inventory current | ✅ |
| 11 | `postgres-test` scope ruled | ❌ open |
| 12 | Variable-only application mechanism | ✅ **CLEARED** |
| 13 | Runtime neutrality at HEAD | ✅ **CLEARED** |
| — | Physical ciphertext copy | non-blocking |

**Three blocking, three open, seven cleared.**

Precondition 7 is the cheapest remaining item and is green under §4.4 — it needs the §2.3 probe run once against production with the current credential, read-only, before rotation.
