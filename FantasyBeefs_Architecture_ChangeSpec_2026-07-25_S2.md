# Architecture Change Spec — 2026-07-25, session 2

**Applies to `fantasy_beefs_architecture_print_v14.html`.**

A change spec, not a regenerated HTML file. The 07-25 session-1 spec (`FantasyBeefs_Architecture_v15_ChangeSpec_2026-07-25.md`) is still unapplied, so v15 does not yet exist. These edits fold into the same pending regeneration rather than forking a v16.

---

## 1. No percent-complete badge changes

**Nothing shipped this session.** No code was written, no commit made, no migration run, nothing deployed. Every build-layer badge on v14 is correct as printed.

This is worth stating explicitly because the standing rule warns against percent-complete holding steady against a changed denominator. Here the denominator did not change either. Phase B is infrastructure work that sits outside the build layers entirely.

---

## 2. Infrastructure layer — three edits

### 2.1 Restore point — replace the existing backup note

The current note describes the 07-23 artifact as the sole restore point. Replace with:

> **Restore capability — two encrypted artifacts, one verified against a live passphrase.**
> `fantasy_beefs_prod_2026-07-25_UTC.dump.gpg`, 116,922 bytes, created 2026-07-25 15:54 UTC. Source `railway` production via `hayabusa.proxy.rlwy.net:15707`. `pg_dump` custom format, TOC-verified at 410 entries and **40 tables**. GnuPG 2.4.5 symmetric AES256.CFB. **Recovery proven with `--no-symkey-cache`: genuine passphrase prompt, plaintext returned at 243,863 bytes exact.** Schema baseline is **pre-Spec-1** — no `beef_proposals`, no `beef_proposal_starters`.
> The 07-23 artifact (116,928 bytes) is retained. Both copied to `C:\Users\frase\OneDrive\FantasyBeefs_Restore\`. **Physical offsite copy outstanding.**
> Railway backups and PITR remain unavailable at the current plan tier, verified on both Backups tabs. These local artifacts are the entire restore capability.

### 2.2 Local PostgreSQL containers — replace the single-container note

v14 shows one test container. There are two, on the same port bind:

> **Two `postgres:16` containers, both mapped `5433:5432`.**
> `pg-fantasy-test` — `f34c34e847ff`, **running**, database `fantasy_test`. Protected for FR-VAL10-ac's serialization proof. Do not stop or remove.
> `fb-test-pg` — `58e009fb95bf`, **stopped**, 6 days idle, undocumented. See **FR-INFRA-DOCK-1**. Do not start.
> A harness pointed at `localhost:5433` trusts a port with two possible occupants. Same shape as the Guard 5 defect — a safety check aimed at the wrong target.
> Docker Desktop engine 29.6.1. `postgres:18` image cached locally for production-version dumps; a client 16 cannot dump an 18.x server.

### 2.3 Credential transfer path — new note in the infrastructure layer

> **DSN transfer is clipboard-free.** `railway variables list --service Postgres --environment production --json`, captured into a variable, parsed, and assigned without ever printing. The clipboard is out of the credential path entirely — see **FR-PROC-CLIP-1**.
> Validation is by **shape, not substring**: `postgresql://` prefix, no whitespace, anchored host/port/database. A substring match on the hostname admits malformed input and did so on 07-25.
> The linked Railway service is `fantasy-beefs`, so `--service Postgres` is mandatory on any variables call.

---

## 3. Security layer — two edits

### 3.1 FR-SEC-DB-1 — update the gate note

> Steps 8–11 outstanding. **The fresh-dump precondition is satisfied as of 2026-07-25.** Now gated solely on the desynchronization response procedure, which has not been drafted.
> **Option B rotation order governs.** Fresh verified dump → rotate → external role-authentication verification → app-variable correction → restart. The original "disable public networking first" step is superseded: the public proxy is both the dump path and the external-authentication path the post-rotation diagnostic requires. Proxy removal returns as available hardening afterward.
> `RAILWAY_TCP_PROXY_DOMAIN` and `RAILWAY_TCP_PROXY_PORT` on the `Postgres` service are the proxy's own self-record — the instrument for confirming proxy survival post-rotation.

### 3.2 FR-SEC-DB-5 — new block

> **FR-SEC-DB-5 — OPEN, UNVERIFIED.** `C:\FantasyBeefs_Backups\fantasy-beefs_9ff096b.zip`, 25,991,636 bytes, unencrypted, dated 07-24, stored beside the encrypted database artifacts. `c353d2b` removed hardcoded connection strings from the working tree but not from Git history, so an included `.git` directory would carry them. 26MB is consistent with `.git` inclusion. Outside OneDrive, so exposure is bounded to this machine. Not asserted — two commands settle it.

---

## 4. Document-integrity layer — new block

> **FR-DOC-REG-1 — the Findings Register is two disjoint volumes.**
> **vol. I** = `Findings_Register_v12_2.md`, Sections 1–14. The fifteen money-model rulings, the five-spec split, the locked build order 1 → 2 → 3 → 5 → 4, Spec 2's Opus dispositions, Passes 1–5, the consolidated audit package.
> **vol. II** = `Findings_Register_v17.md`, Sections 14–19. Tracked lineage v14 → v15 → v16 → v17, entering Git at `9ff096b`.
> A heading-level comparison returned every heading from both files — zero overlap. **Both volumes contain a Section 14 with different binding content.** Cite as vol. I §N or vol. II §N. Never a bare section number.
> The money-path half has no verified Git provenance. The half with provenance does not govern the money path.

---

## 5. Build-authorization note — replace wherever "no builds" appears

> **RULING-BUILD-1.** The gate is **reversibility**, not productivity. Working-tree code, tests, local Docker, and scratch work need no authorization. `git commit`, `git push`, migrations, `railway up --service fantasy-beefs`, and money-path shipping are each individually gated. **Opus Math Review remains a hard gate on all money-path code.** Never `git add .` on a money-path commit.

---

## 6. Unchanged and explicitly reaffirmed

- Binding build order §17
- Spec layer statuses — Spec 1 committed and unshipped, Spec 2 Opus-cleared and unbuilt, Specs 3A/3B/5/4 not started
- FR-8.7 six outstanding closure items
- VAL-10 Rev 23 frozen with four implementation gates
- Milestones: August 1 platform live and **not betting**; NFL Week 1 betting activation
- Runtime baseline `59be320`, re-proven at `233d89d`

---

## 7. Regeneration note

Two change specs are now pending against v14 — the 07-25 session-1 spec and this one. **Apply both in a single regeneration to v15.** Regenerating twice invites the cross-section drift the composition-review rule exists to catch.

This is well-suited to Claude Code: multi-section HTML edits, no secrets, no shell-state dependency, and green under RULING-BUILD-1 since the output is a working-tree file.
