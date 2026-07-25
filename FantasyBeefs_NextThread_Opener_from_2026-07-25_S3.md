# Next-Thread Opener — Fantasy Beefs

**Authored 2026-07-25, session 3. Paste this to open the next thread.**

> Openers are named for the date they were **authored**. Never infer today's date from a document title.

---

## Repository state — verify before citing

Branch `remediation/foundation-phase-1`, HEAD **`fd08e84267ea3ffdc5d1da055f0b20c05d270e39`** at session close. Nothing deployed.

Runtime source unchanged from `59be320`, proven at `fd08e84`: nine paths, `.gitignore` plus eight markdown, **zero `.py`**, nothing under `app/`, `db/`, `tests/`.

**Three openers running have now shipped stale SHAs.** The 07-25 S2 opener said `233d89d`; HEAD was already `fd08e84`. Verify:

```
git rev-parse HEAD
git status -sb
git ls-remote origin remediation/foundation-phase-1
```

**`Findings_Register_v17.md` is tracked at HEAD** and absent only from the project panel. Attach it from the repo.

Folder path:
`C:\Users\frase\OneDrive\PycharmProjects\fantasy-beefs\`

**Attach:** this opener · `FantasyBeefs_Session_Handoff_2026-07-25_S3.md` · `FantasyBeefs_Findings_Register_Update_2026-07-25_S3.md` · `FantasyBeefs_MasterPlan_Update_2026-07-25_S3.md` · `FantasyBeefs_Architecture_ChangeSpec_2026-07-25_S3.md` · `POSTGRES_TEST_ROTATION_REHEARSAL_Rev7.md` · `FR_SEC_DB_1_DESYNC_RESPONSE_PROCEDURE_DRAFT_Rev3.md` · `FR_SEC_DB_1_Rev3_Precondition_Clearance_Delta.md` · `Findings_Register_v17.md` (vol. II) · `Findings_Register_v12_2.md` (vol. I)

---

## Read these six before proposing anything

**1. The rotation control is `Postgres → Database → Config → Connection → Regenerate`.** Verified from the live dashboard. **There is no Credentials tab.** Three governing artifacts say otherwise; they inherited a v15 "correction" derived from documentation rather than observation. v14 was right. See FR-SEC-DB-9.

**2. Trust-mode `pg_hba` recovery is retired.** `railway ssh` reaches OS root on both database services, and `local all all trust` is enforced — proven by stripping `PGPASSWORD` and connecting anyway. The recovery design is **local-socket credential repair**, bench-proven end to end.

**3. Railway performs no password recovery at any tier.** Hobby has community support with no guaranteed response. Escalation is informational, never a dependency. Restore into a new service is the guaranteed branch.

**4. "Manual SQL failed previously" is unsourced.** Every panel document mentioning `ALTER USER` describes it as deliberately not executed. UNVERIFIED and UNTESTED, not established.

**5. A credential must never pass through `railway ssh` argv.** It joins positional arguments and a remote shell reparses them. PowerShell stdin carries CRLF, so nested shell heredocs are retired. Proven transports: here-string → `psql` stdin, and here-string → `sh` with no arguments.

**6. Six credential-bearing surfaces, never assumed equal.** Role · Railway `PGPASSWORD` · container `$PGPASSWORD` · `fantasy-beefs` hand-typed literal · regeneration-UI display (**password only**) · Railway `DATABASE_PUBLIC_URL`.

---

## FIRST TASK — the Backups reading

One read-only observation, and it is the only thing in the evidence queue.

Open **`Postgres` → Backups**. Observation only. No create, restore, enable, schedule, or upgrade.

Record six fields: existing backups · manual creation offered · scheduling offered · PITR present · exact restriction text · exact labels on disabled controls.

**Why it matters.** The claim that Backups and PITR are Pro-gated is UI-derived, and it underpins the entire restore-point argument. UI-derived claims lost their presumption of correctness this session. This reading **replaces** the prior claim rather than annotating it.

---

## Then, in order

1. **Second durable passphrase copy** — needs nothing from the thread. Paper, envelope, separate failure domain, no photograph. Then **one measurement**: independent transcription, then decrypt with `--no-symkey-cache`. Until that succeeds the paper is a duplicate, not a verified credential.
2. **Seventh review of the rehearsal**, then Rev 8 from the sixteen-item intake in the handoff.
3. **Rev 4 of the desync procedure** — six surfaces, measured rotation path, the S2-has-no-authorized-exit problem.
4. **M10 transport bench** — can a bounded, pre-specified psql session hold one backend across an operator-controlled pause, preserving PID and `backend_start`? Every proven transport is one-shot.
5. Rehearsal execution → `postgres-test` teardown → FR-SEC-DB-1 rotation.

**Rotation blocks on three:** the rehearsal, the desync Rev 4, and the passphrase copy.

---

## Standing process rules

**Negative controls.** *When a probe's success would look identical under a permissive path, it is not evidence until the same path has been shown to reject a known-invalid input.* A bench `SELECT 1` over `127.0.0.1` returned `1` and proved nothing, because line 119 is `host all all 127.0.0.1 trust`.

**A failed diagnostic proves nothing until the diagnostic is calibrated.**

**Non-mutating production inspection is GREEN** when the exact command and target are named beforehand and no state changes. Not green merely because it arrives over SSH.

**No second credential mutation** while the first is unresolved.

**Never pass a credential in a CLI argument or `-e NAME=value` flag** when it can stay inside the container.

**Read the live thing, not the documentation.** FR-SEC-DB-9 came from a doc page describing a surface the dashboard does not present.

**Counts in documents are a drift generator.** Name instruments — "M1–M8" — never "all seven."

**Recon before premise, including the date and the SHA.**

**Pre-register the interpretation before running the probe.** Multiple hypotheses died cleanly this session; the method held where the guesses did not.

**Destructive cleanup goes in its own turn**, after the prerequisite is confirmed consumed. A bench container was destroyed before its verifier was read, which is why mechanism C is still unresolved.

**Name the machine and the exact shell** on every command. Folder path and filename on separate lines.

**Propose before building**, within RULING-BUILD-1's gated set: commits, pushes, migrations, `railway up`, and money-path code.

**Full six-part transition package at every session close.**

---

## Prohibitions

- **`railway delete` / `rm` / `remove` deletes the PROJECT.** One word from `railway service delete`. Use service and volume **IDs**, not names.
- **`railway up` for credential correction** — uploads a working-tree snapshot; would change running code as a side effect.
- **`railway redeploy --from-source`** — same defect via a flag.
- **`-y` on any destructive command during an incident** — the confirmation dialog is the safety feature.
- **`railway ssh --session`** — installs tmux, mutates the container.
- **`Convert to HA` and `Add PgBouncer`** — same scrolled panel as Regenerate, unrelated mutations.
- **Upgrade to 18.4** — already running since 2026-07-09.
- **`git filter-repo`.**
- **Do not stop or remove `pg-fantasy-test`** (Docker, 5433) until FR-VAL10-ac is complete.
- **Do not start `fb-test-pg`** — same 5433 bind, undocumented.

---

## Milestones — Option C, unchanged

**August 1, 2026** — platform live for league setup and the draft window. **Not betting.**
**NFL Week 1** — betting activation gate.

## Binding build order (§17), unchanged

Security remediation → FR-8.7 closure → controlled foundation deployment → FR-AC-ISO-1 gate → Spec 2 → Spec 3A → Spec 3B → Spec 5 → Spec 4

**No deployment authorization. No migration authorization. No rotation authorization.**
