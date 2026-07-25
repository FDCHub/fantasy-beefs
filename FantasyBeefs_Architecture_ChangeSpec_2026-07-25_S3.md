# Architecture Diagram — Change Specification, 2026-07-25 session 3

**Source artifact:** `fantasy_beefs_architecture_print_v14.html` (35,446 bytes, 7/23).
**Status:** change spec only. v15 HTML still not regenerated.

**Two prior change specs are now outstanding against v14** — `FantasyBeefs_Architecture_v15_ChangeSpec_2026-07-25.md`, `FantasyBeefs_Architecture_ChangeSpec_2026-07-25_S2.md`, and this one. **Apply in order, and apply §1 of this spec as a correction to the first.**

**Percent-complete badges are not updated here.** No build work shipped this session, so no badge denominators moved. Any badge edit requires the v14 source loaded in full.

---

## 1. CORRECTION to the v15 change spec — the rotation path

**The v15 change spec §5 is wrong and must not be applied as written.**

It replaced v14's `Database → Config → Regenerate` with `Database view → Credentials tab → Regenerate`. Live observation on 2026-07-25 shows the Database view presents **`Data · Stats · Config`**. There is no Credentials tab.

Replacement text for the FR-SEC-DB-1 block:

> **Rotation path, verified from the live dashboard 2026-07-25:** `Postgres` → **Database → Config → Connection → Regenerate Password → Regenerate**.
>
> The Connection panel shows Username `postgres` and a masked Password with reveal and copy controls. **The credential is displayed at rest as a password, not a DSN.** Railway's warning text reads *"Breaks existing connections until they use the new password."*
>
> **Do not touch `Convert to HA` or `Add PgBouncer`** — both sit on the same scrolled panel and are unrelated mutations. PgBouncer would insert a pooler into the connection path mid-security-work.
>
> **Rotation has no direct credential rollback control, and Railway performs no password recovery at any tier.** Recovery is local-socket repair or restore into a new service.

---

## 2. Security layer — three new blocks

**FR-SEC-DB-6:**

> Railway support: Trial, Free, and Hobby receive community support with **no guaranteed response**; Pro adds direct help and private threads. **No tier provides password recovery.** Escalation is informational, never a recovery dependency.

**FR-SEC-DB-7:**

> Railway SSH authorization is database-superuser-equivalent on both database services. A registered key reaches OS **root**; `local all all trust` permits passwordless access as `postgres` over the Unix socket; and the container additionally holds the live credential in `PGPASSWORD`. **Rotating the PostgreSQL password revokes neither path.** Railway account and SSH-key control must be treated as at least as privileged as the database password. Established 2026-07-08, rediscovered and proven by removal 2026-07-25.

**FR-SEC-DB-9 and FR-DOC-V15-1:**

> Governing artifacts specified a `Credentials` tab that does not exist. Root cause: a correction derived from documentation rather than observation. **v15's UI-derived claims lose their presumption of correctness; CLI- and API-derived claims stand.** The Pro-gated Backups/PITR claim is UI-derived and awaits re-reading.

---

## 3. Recovery layer — replace the trust-mode block entirely

Delete any depiction of `pg_hba` trust-mode recovery. Replace with:

> **Local-socket credential repair.** `railway ssh` → OS root → `psql -h /run/postgresql` → `local all all trust` → role `postgres`. **No `pg_hba` edit. No authentication-disabled window. No public-proxy removal. No redeploy.**
>
> Guarded by a session-scoped `SET log_min_error_statement = 'PANIC'` with a read-back enforced by a psql `\if` branch, and `\getenv` plus `:'var'` so psql performs SQL-literal quoting. **Bench-verified end to end 2026-07-25**, including the abort branch and an authenticated round trip on a path proven to reject a wrong password.
>
> **Guaranteed recovery remains restore into a new service**, because it depends on nothing Railway has to do.

---

## 4. Both database nodes — measured properties

| Property | Both services |
|---|---|
| Image | `ghcr.io/railwayapp-templates/postgres-ssl:18` |
| Server / client | PostgreSQL 18.4 / psql 18.4, `Debian 18.4-1.pgdg13+1` |
| HBA file | `/var/lib/postgresql/data/pgdata/pg_hba.conf` |
| HBA rules | 7 rows, lines 117–128, identical, no active include directives |
| Logging | `none` / `error` / `-1` / `-1` / `0` / `stderr` / `off` |
| SSH | reachable, OS `root`, ed25519 key registered |

> **`logging_collector=off` with `log_destination=stderr`** means PostgreSQL writes to stderr and **Railway ingests it into the dashboard log store**. There is no local logfile to rotate. A failed plaintext statement's text would land in Railway's retained logs.

**Node identities — use IDs, never names:**

| Resource | Service ID | Volume ID |
|---|---|---|
| `postgres-test` | `f03178f3-…` | `9f491b83-…` |
| `Postgres` | `cd0ba357-…` | `16983665-…` |
| `fantasy-beefs` | `9400fc77-…` | none |

> **`railway delete` / `rm` / `remove` deletes the PROJECT.** One word from `railway service delete`.

**Volume-size annotation for both database nodes:**

> Railway's volume figure is **not** a measure of database contents. `postgres-test` reports 134.92 MB while both its databases measure 7,678 kB and `PGDATA` measures 47 MB. `Postgres` reports 221.6 MB against a 243,863-byte dump. The accounting difference is unclassified.

---

## 5. Deployment layer — narrow FR-DEPLOY-1

> `fantasy-beefs` has **`source: null`** — no connected source, so `--from-source` has nothing to pull. Latest deployment `7cc12e15`, created **2026-07-18T02:47:02Z**. No commit SHA is recoverable; the running tree is bounded to that upload.
>
> **Variable application is `railway redeploy --service <name> --environment production`.** Its default redeploys the existing deployment and touches no source. **Never `railway up` for credential correction** — it uploads a working-tree snapshot and would change running code as a side effect.
>
> **The v14 note that Restart picks up variable changes needs re-derivation.** `railway restart` reuses the existing deployment and its help text says nothing about variables. The rehearsal settles it empirically.

---

## 6. Timeline annotation — 18.4

> `Postgres` deployment `e1f535d9` created 2026-07-09T00:26:44Z; postmaster start 00:27:47Z. **18.4 arrived by deployment on 2026-07-09**, not by a spontaneous image pull. The initiating actor is unclassified. Artifacts written after that date treating "upgrade to 18.4" as a future action were stale.

---

## 7. Transport layer — new block

> **PowerShell here-strings carry CRLF over stdin**, verified by `od -c`. Constructs requiring exact line-terminator matching are unsafe on this path; **nested shell heredocs are retired**. psql tolerates CRLF.
>
> **`railway ssh` joins its positional arguments** and hands the string to a remote shell that reparses it. Quoted multi-word arguments do not survive. **A credential must never pass through `railway ssh` argv.**
>
> **Proven transports:** here-string → `psql` stdin; here-string → `sh` with no arguments.
