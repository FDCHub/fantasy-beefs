# FantasyStakes — Production Operations Runbook

Operational, executable, and current as of PROD-HARDEN-1. Every command here is
real and has been run. Where something is an operator action that this
repository cannot perform, it says so rather than implying it is done.

---

## 1. Process topology

Three roles. Two run today.

| Role | Command | Config | Notes |
|---|---|---|---|
| **web** | `uvicorn api.main_rc2:app --host 0.0.0.0 --port $PORT` | `railway.toml` | Healthcheck `/health`; readiness gate `/ready`. Scales horizontally. |
| **final_lock worker** | `python -m workers.final_lock --loop --interval 60` | `railway.final_lock.toml` | Resident loop. Holds a durable claim with a 15-minute TTL, so multiple replicas are safe. No HTTP listener by design. |
| **release command** | `python -m migrations.run` | one-off | Run **once per release, before the web deploy**. Not a process. |

There is no separate scheduler process. The only periodic economic actor is the
final-lock worker, and it protects itself with a durable claim rather than with
an assumption about replica count.

---

## 2. The one database command before a release

```bash
python -m migrations.run            # apply pending, in manifest order
python -m migrations.run --status   # what is applied / pending — changes nothing
python -m migrations.run --dry-run  # what would run
```

**A fresh database needs none of this.** The startup bootstrap builds the full
schema on first start and stamps the manifest. Migrations exist to carry an
**existing** database forward. On a production process the bootstrap is inert
once the database has tables, so schema never changes as a side effect of a
process starting.

Ordering lives in `migrations/manifest.py`. Six entries are ACTIVE
(`0001_yahoo_identity` … `0006_rc2_championship_correction`); twenty-six
historical scripts are recorded there as **not to be run** — their effects are
already in `db/schema.py`, and one is a one-shot data conversion that must never
be replayed.

Applied migrations are recorded in `schema_migrations` (identifier, applied_at,
release, version). A failed migration records nothing and exits non-zero — the
release must not proceed.

### The record is checked against the schema

Each manifest entry also names the tables and columns it creates. `/ready`
verifies every migration recorded as applied against the **live** schema, so a
database whose record claims work the schema cannot corroborate is refused
rather than trusted.

This matters because the record is a claim. A database stamped `0001`–`0006`
whose championship tables are absent previously answered `/ready` 200 with
`migrations: ok`; it now answers 503 with
`schema: unverified:<identifier>: table <name> missing`.

| `/ready` field | Meaning |
|---|---|
| `ready` | the gate — the platform reads this |
| `process` | this process booted and is configured |
| `database` | reachable **and** at the schema this code needs |
| `checks.migrations` | `ok` \| `pending:<ids>` \| `unknown` |
| `checks.schema` | `ok` \| `unverified:<detail>` \| `unknown` |

`process: true` with `database: false` means the build is fine and the **schema**
is the problem — run `python -m migrations.run`, or investigate a record that
disagrees with the schema. `process: false` is a configuration problem, and a
rollback (§9) is the likely answer. A schema state that cannot be determined
fails **closed**.

---

## 3. Required configuration

Startup **refuses** in production without these:

| Variable | Why |
|---|---|
| `DATABASE_URL` | Without it the process silently uses a SQLite file inside an ephemeral container. |
| `FS_TOKEN_ENCRYPTION_KEY` | Without it Yahoo sign-ins succeed and the grant each produces is silently dropped. |
| `JWT_SECRET_KEY` | Session signing. |

Degraded but serviceable without: `FS_YAHOO_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI`
(Demo and all reads still work), `FS_PUBLIC_BASE_URL`, `FS_RELEASE`.

Must **not** be set in production: `FS_COOKIE_INSECURE`.

Check any deployment: `GET /ready`.

---

## 4. Encryption key — provisioning

```bash
python -c "from auth.token_crypto import generate_key; print(generate_key())"
```

Set the output as `FS_TOKEN_ENCRYPTION_KEY` in the deployment's secret store.
**Never commit it. Never place it in the database backup.** A backup and its key
must be recoverable independently, or a restore yields grants nobody can open.

## 5. Encryption key — rotation

The envelope is versioned (`v1.<key_id>.<nonce>.<ciphertext>`), so rotation
needs no migration and no downtime.

1. Keep the current key, and set it under an explicit id:
   `FS_TOKEN_ENCRYPTION_KEY_old=<current>`
2. Generate a new key. Set `FS_TOKEN_ENCRYPTION_KEY=<new>` and
   `FS_TOKEN_KEY_ID=v2`.
3. Deploy. New writes seal with `v2`; existing grants still name `old` and still
   open.
4. Optional: re-authorization by any user re-seals their grant with the active
   key. No forced rewrap is required.
5. Verify with `python -m ops.audit` — the `grant_readability` check reports any
   grant the configured keys cannot open.
6. Remove `FS_TOKEN_ENCRYPTION_KEY_old` only once step 5 reports zero
   unreadable grants.

**Do not** rotate by replacing the key without retaining the old one. That
invalidates every stored Yahoo connection at once.

---

## 6. Release procedure

1. Tests green (see §12 below).
2. Note the release SHA. Confirm a recent backup exists (§7).
3. `python -m migrations.run --dry-run` against production — review.
4. `python -m migrations.run` — must exit 0. **If it fails, stop; do not deploy.**
5. Deploy the backend.
6. Gate on readiness: `GET /ready` must return 200 with `migrations: ok`,
   `schema: ok`, and both `process` and `database` true.
7. Deploy frontend assets if released separately (§10).
8. `python -m ops.smoke --base-url https://<host> --expect-release <sha>`
9. Watch errors and the final-lock worker for one cycle.
10. If the gate fails: roll back (§9).

---

## 7. Backup

**Platform capability is an operator action.** Railway's managed PostgreSQL
backup features must be enabled and verified in the Railway dashboard; this
repository cannot configure them and does not claim they exist.

Independent of platform features, a logical backup is always available:

```bash
pg_dump --format=custom --no-owner --no-privileges "$DATABASE_URL" > fs-$(date +%F-%H%M).dump
```

Requirements:
- store **off-instance**;
- retain long enough to cover a full season plus one;
- store the encryption key **separately** (§4);
- record the release SHA alongside the dump.

Verify restorability on a schedule — a backup that has never been restored is a
hypothesis. §8 is the drill.

---

## 8. Restore

```bash
createdb fs_restore
pg_restore --no-owner --no-privileges --dbname fs_restore fs-<timestamp>.dump
DATABASE_URL=postgresql://…/fs_restore python -m ops.audit
```

The audit must report **CLEAN** before the restored database is trusted. It
checks schema presence, Ledger balance, protected accounts, grant referential
integrity, grant decryptability with the configured key, credential owners and
stuck claims. It **never repairs** — a finding is for a human.

Then: point the application at the restored database, start with writes disabled
(§11), re-run the audit, and re-enable writes.

---

## 9. Bad release

1. Disable writes (§11) if economic state may be affected.
2. Roll the **application** back to the previous release. Do **not** roll the
   database back by deleting committed rows.
3. Migrations in this product are additive, so the previous application reads
   the newer schema safely — a column it does not know about is a column it does
   not select.
4. `GET /ready`, then `python -m ops.audit`.
5. Re-enable writes.

---

## 10. Frontend-only release

The frontend has no build step; the ES modules are served as authored.

1. Copy the changed files under `web/`.
2. Do **not** run migrations. Do **not** restart for schema reasons.
3. The service worker's cache namespace is derived from the release identifier
   the server substitutes at serve time, so a new release is a new namespace
   automatically and the previous cache is deleted on activation.
4. Verify: `python -m ops.smoke --base-url https://<host>`.

Backend state is untouched by a frontend release.

---

## 10a. API compatibility contract

There is no `/v1` prefix and 1.0 does not need one. What the frontend and
backend rely on instead is a stated contract:

| Change | Release |
|---|---|
| **Adding** a response field | Backend alone. The frontend reads named fields and never compares a response's key set, so an unknown key is ignored. |
| **Adding** an optional request field | Backend alone. |
| **Adding** a route | Backend alone; frontend follows when it wants it. |
| **Removing** or **renaming** a response field | **Coordinated.** Deploy the backend that still emits both, then the frontend, then remove. |
| **Changing** a field's type or meaning | **Coordinated**, and treat it as a rename — emit the new field alongside, migrate the frontend, retire the old one. |
| **Changing** a route's authorization | **Coordinated.** |

The frontend is independently deployable for everything in the first group,
which is the ordinary case. The second group is expand/contract applied to an
API instead of a schema, and follows the same discipline as §2's migrations.

---

## 11. Emergency write-disable

```bash
FS_WRITES_DISABLED=1
FS_WRITES_DISABLED_REASON="restore verification 2026-08-17"
```

Set it, redeploy or restart. Every authoritative Ledger posting then refuses
with reason code `writes_disabled` and a 503 — **not** a 500, so an operator
watching an error rate can tell a deliberate hold from a defect.

Reads, sign-in and commissioner diagnostics continue. Unset the variable and
restart to resume.

It is environment-controlled, not database-controlled, on purpose: the situation
this exists for includes "the database is suspect".

---

## 11a. Yahoo connection and data retention

**The retention question is an OPEN CONTRACTUAL GATE.** The Yahoo agreement's
data storage and retention terms have not been clarified. Nothing in this
repository asserts a right to retain Yahoo data, no retention period is
implemented, and this section does not claim compliance.

What the software actually persists is inventoried:

```bash
python -m ops.yahoo_retention            # the full inventory
python -m ops.yahoo_retention --gate     # the open gate, alone
python -m ops.yahoo_retention --json     # machine-readable
```

The inventory is kept honest by `test_c1_yahoo_retention.py`, which fails when a
provider-origin column exists in `db/schema.py` and is not inventoried.

**Six persisted fields carry an economic dependency** — settled wagers, skunk
charges, pool settlements and Championship Scores were derived from them, and
they cannot be recomputed if the source is deleted. Those are the fields a
retention ruling actually governs. See the inventory's REQUIRES RULING list.

**Scopes are `openid`, `email`, `fspt-r`** — read-only. FantasyStakes writes
nothing to Yahoo.

**A user may disconnect their own authorization** at any time:

| | |
|---|---|
| `GET /provider/connection` | whether this account holds a grant |
| `POST /provider/disconnect` | clear it — self-service only, no user id parameter |

Disconnecting destroys the sealed OAuth material and marks the grant
disconnected. It touches **no** wager, settled result, Ledger row, wallet or
league membership. FantasyStakes cannot revoke at Yahoo — Yahoo documents no
revocation endpoint — so the response tells the user to remove the app from
their Yahoo account's connected apps if they want that too.

**Attribution** — "Fantasy data provided by Yahoo Fantasy" is rendered on every
surface displaying Yahoo Fantasy Information. It claims no sponsorship,
endorsement, partnership or affiliation, and `test_c1_yahoo_retention.py`
asserts the product makes no such claim anywhere.

---

## 12. Yahoo outage

Do nothing hasty. The architecture already fails closed:

- an expired-but-refreshable grant refreshes through the canonical store;
- `disconnected` / `reconnect_required` / missing refuses the read;
- there is **no** fallback to an operator credential or another member's grant;
- no settlement proceeds on stale or fabricated provider data.

Committed FantasyStakes state is unaffected by any provider condition. Wait,
then retry. If a commissioner's grant needs reconnecting, they sign in with
Yahoo again and reconnect the league.

---

## 13. Worker crash

Restart it. That is the whole procedure.

The final-lock worker holds a durable claim with a TTL; a killed worker's claim
is reclaimed after it expires and the work re-executes against the same
committed state. Settlement, week close, Pool settlement, the shortfall sweep
and Skunk assessment are each idempotent against durable records, so a retry
after a crash produces no second economic effect.

**Never** reconstruct a wallet by hand. The Ledger is the authority; if it and a
wallet disagree, that is a finding for §8's audit, not an arithmetic exercise.

---

## 14. Monitoring expectations

No external monitoring integration is configured by this repository. These are
the conditions worth alerting on, and the surface that reveals each:

| Condition | Surface |
|---|---|
| process not ready | `GET /ready` ≠ 200 |
| database unavailable | `/ready` → `checks.database` |
| schema behind code | `/ready` → `checks.migrations` |
| writes disabled | `/ready` → `checks.writes` |
| Ledger invariant broken | `python -m ops.audit` exit 1 |
| grant needs reconnect | commissioner provider diagnostic |
| worker crash loop | platform restart count on the worker service |
| wrong build serving | `/version` vs the deployed SHA |

---

## 15. Tests before a release

```bash
python test_prod_harden1_release.py
python test_prod_harden1_security.py
python test_b1_schema_readiness.py                       # readiness, on SQLite
B1_DATABASE_URL=postgresql://…/fantasy_test python test_b1_schema_readiness.py
TEST_DATABASE_URL=postgresql://…/fantasy_test python test_prod_harden1_recovery.py
TEST_DATABASE_URL=postgresql://…/fantasy_test python test_prod_harden1_restore.py
TEST_DATABASE_URL=postgresql://…/fantasy_test python run_pg_suites.py
```

`test_b1_schema_readiness.py` drives the four database states a deploy can land
in — healthy, stamped-but-unverifiable, behind the manifest, and unstamped — and
only the first may answer ready. Run it on **both** dialects: the production
target is PostgreSQL and the invariant must not be a SQLite accident.

`run_pg_suites.py` gives every `*_pg.py` suite its own database and drops it
afterwards, which is what the empty-database harness guard requires; do not run
those suites serially against one long-lived database.
