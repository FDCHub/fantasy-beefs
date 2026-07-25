# Session Handoff — 2026-07-25, session 3

**Headline: trust-mode recovery is retired, its replacement is bench-proven end to end, and the rotation path in three governing artifacts points at a UI surface that does not exist.**

---

## 1. What was authorized and what happened

Nothing was authorized entering the session beyond drafting. **Zero production mutations. Zero commits. Zero pushes. Zero deployments. Zero credential changes.** Every Railway interaction was a read.

One local Docker container was created and destroyed as a bench.

---

## 2. The five results that matter

**1 — Trust-mode `pg_hba` recovery is unnecessary, and always was.**

`railway ssh` reaches OS **root** on both database services. Line 117 of `pg_hba.conf` is `local all all trust`, and it is **enforced** — proven by stripping `PGPASSWORD` and disabling prompting, and connecting anyway. The published recipe edits `pg_hba` to obtain access the container already grants.

**This is a rediscovery.** The 2026-07-08 session took its backup over that exact socket and wrote that it "bypasses the broken external-auth path entirely." Seventeen days of planning then designed around a file edit.

**2 — Mechanism A is proven end to end.**

Local-socket credential repair, guarded. Blocks when the logging guard is unsatisfied with the verifier unchanged, blocks on absent `PGPASSWORD`, permits when satisfied, and **the credential it installs authenticates over a path proven to reject a wrong password.**

That last property took four attempts. Two earlier "proofs" ran over trusted paths and measured nothing.

**3 — The rotation path is misdocumented in three artifacts.**

There is no Credentials tab. The control is **`Postgres → Database → Config → Connection → Regenerate`**. v14 had it right; the v15 "correction" was derived from Railway's documentation and broke it.

**4 — The "manual SQL failed previously" prohibition is unsourced.**

Every panel document mentioning `ALTER USER` is 07-07/07-08 era and describes the operation as **deliberately not executed**. The failure claim first appears two weeks later and propagates circularly. Corroborated from inside the container: no boot-time password reapplication exists in the image.

**5 — Railway performs no password recovery at any tier.**

Hobby has community support with no guaranteed response. Escalation is informational, never a recovery dependency. Restore into a new service is the guaranteed branch precisely because it depends on nothing Railway has to do.

---

## 3. Artifacts produced — nine, none authorized

| Artifact | Status |
|---|---|
| `FR_SEC_DB_1_DESYNC_RESPONSE_PROCEDURE_DRAFT_Rev3.md` | current; **needs Rev 4** for the six-surface model and the measured rotation path |
| `FR_SEC_DB_1_Rev3_Precondition_Clearance_Delta.md` | current |
| `POSTGRES_TEST_ROTATION_REHEARSAL_Rev7.md` | current; **sixteen-item Rev 8 intake pending** |
| Revs 1–2 of the procedure, Revs 1–6 of the rehearsal | superseded |

**These are downloads, not repo files.** Nothing was written into the working tree.

---

## 4. Preconditions — the rehearsal

**Cleared by measurement:** fidelity (identical image string, psql version, server version, HBA rules with matching line numbers, all seven logging settings) · mechanism A · teardown mechanism · value-5 representation.

**Execution-time:** zero inbound references · zero user tables · proxy self-record · `PT_OLD_DSN` capture.

**Outstanding:** the seventh review, then Rev 8.

---

## 5. Rev 8 intake — sixteen items

M9 for current-v6 authentication · `R(Tn)` snapshot primitive taken before every derived measurement · Mutation 3 gated on equality **plus** no unresolved v2/v5/v6 divergence · S0–S6 demoted to a base role-transition label with surface consistency recorded separately · mechanism A as measured behavior · nested heredoc retired with CRLF recorded as cause · byte count as the present-and-nonempty gate · C1a, C1b, C2 as T0 instrument calibration · the four-property bench-transfer wording · the narrowed volume finding verbatim · precondition 4 as authoritative gate plus sanity check · the unexplained portion inside 47 MB left unclassified · M10 with its two-statement read and four-row interpretation · the measured rotation path · value 5 fixed as password-only · `Convert to HA` and `Add PgBouncer` prohibited.

**M10's transport is the only unmeasured part.** Can a bounded, pre-specified psql session hold one backend across an operator-controlled pause, preserving PID and `backend_start`? Every transport proven this session is one-shot.

---

## 6. Eight composition drifts

All one shape: a careful local section, then a downstream section written from memory of the pre-edit state rather than derived from it. Options tables contradicting themselves two rows apart. A classification table unable to use its own discriminator. Prose describing a program different from the code beneath it. "All seven" left stale after an eighth instrument was added.

**Mitigations adopted:** derivation tables instead of prose summaries · instruments named, never counted · branch tables with one row per state, mirroring the state definition exactly.

Worth recording plainly: the review loop caught every one of these, and several were caught by re-deriving rather than re-reading.

---

## 7. Git state

No tracked files changed. Verify at next session open:

```
git rev-parse HEAD
git status -sb
git ls-remote origin remediation/foundation-phase-1
```

Expected `fd08e84267ea3ffdc5d1da055f0b20c05d270e39` on all three, empty ahead-log, no modified tracked files.

**Twenty-three untracked entries remain**, two of which gate FR-8.7 and exist in exactly one place: `FR_8_7_TEST_6D_SPEC_FROZEN.md` and `FR_8_7_LOG_1_FEED_ISOLATION_MODULE_SPEC_FINAL.md`. This session's whole argument is that a single local copy is not a restore point.

**`Findings_Register_v17.md` is tracked at HEAD.** It is absent only from the project panel. Both reviewers reported it missing; both were describing the panel.

---

## 8. The blocker that did not move

The second durable passphrase copy.

Every artifact built today treats restore into a new service as the guaranteed recovery branch. Restore needs ciphertext **and** passphrase. There are two ciphertext copies and one passphrase, held in one place, not recoverable if lost. **Two encrypted copies of a file nobody can decrypt is not a restore point.**

It needs no review and no authorization. It needs paper, an envelope, a location in a different failure domain — not a photograph, which would collapse the separation into cloud sync — and **one measurement**: independent transcription, then decrypting the artifact with that transcription using `--no-symkey-cache`.

Until that decrypt succeeds, the paper is a duplicate, not a verified credential. Same distinction the 07-23 artifact taught: an artifact that opens against a cached secret has not been shown to open.
