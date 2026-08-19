# FantasyStakes — Railway deployment, HA and public synthetic demo

**Scope.** This is the deployment architecture for `app.fantasystakesapp.com`:
the FantasyStakes application serving the **certified synthetic demo**, on
Railway, on PostgreSQL, across two replicas.

**What this deployment is not.** It is not a Yahoo-connected production launch.
The Yahoo data-retention question is **OPEN** (`ops/yahoo_retention.py`, GATE)
and nothing here resolves, narrows or works around it. §12 records exactly what
keeps a Yahoo-connected workflow out of this deployment, and that gating is a
configuration fact an operator can check, not a promise.

`docs/PRODUCTION_RUNBOOK.md` remains the operations manual. This document adds
only what is specific to Railway, to running more than one replica, and to the
public demo; where the runbook already answers a question, it is referenced
rather than restated, because two answers drift.

---

## 1. Source of truth

| | |
|---|---|
| Deployment branch | `deploy/fantasystakesapp-demo` |
| Branched from | `fantasystakes-1.0.0-rc3` → `9490127` |
| Demo surfaces from | `preprod/demo-environment` → `8b3daaf` |

The branch is **RC3 plus the certified demo surfaces**, never the reverse. The
demo branch was cut from RC2 and therefore does not contain the two RC3 test
hardenings (`test_stripe_removal_regression.py`, `test_support_postseason.py`);
those files are RC3's on this branch, deliberately, and that is the entire
difference between this branch and the demo commit. Nothing is merged back into
RC3 and no tag is moved.

---

## 2. Services

Two Railway services point at this repository. They share `DATABASE_URL` and
nothing else.

| Service | Config path | Replicas | Deployed for the demo? |
|---|---|---|---|
| `web` | `railway.toml` | 2 | **yes** |
| `final_lock` | `railway.final_lock.toml` | 1 | **no** — see below |

**`final_lock` is not deployed in the demo phase.** It is the Dynamic Final Lock
trigger, and Final Lock fires at a real NFL kickoff computed from
`_nfl_lock_time`. The synthetic showcase is a fixed fixture at a fixed instant
with no live kickoff to wait for, so the worker would have nothing due, forever.
Running it would add a second writer to the demo database in exchange for no
behaviour. It is required for the Yahoo-connected launch and not before.

**If it is ever run alongside two web replicas, it must stay at one replica.**
Its safety comes from a durable claim protocol with a 15-minute TTL, not from
being the only process on the machine; a second worker is recoverable but
pointless, and `numReplicas` is deliberately absent from its config.

---

## 3. Runtime

| | |
|---|---|
| Builder | NIXPACKS |
| Entrypoint | `uvicorn api.main_rc2:app --host 0.0.0.0 --port $PORT` |
| Bind | `0.0.0.0`, port from `$PORT` — platform-supplied, never hardcoded |
| Pre-deploy | `python -m migrations.run` — once, before any instance starts |
| Healthcheck | `/ready` |
| Restart policy | `ON_FAILURE` |

**`api.main_rc2`, not `api.main`.** The RC2 entrypoint registers the additive
championship models *before* importing the RC1 application. Starting `api.main`
would let the fresh-database bootstrap stamp migrations 0003–0006 as applied
while creating none of the six championship tables — `/ready` would then answer
healthy against a schema that cannot run a championship. `railway.toml`'s
`startCommand` wins over `Procfile` on this platform; both say the same thing
and must stay in step.

### Liveness and readiness are different endpoints and only one is the gate

- `/health` — always 200. Reports `ok` / `degraded` in a JSON field and never
  sets a failing status code. Useful to a human; **useless as a deploy gate**,
  because a replica with pending migrations passes it.
- `/ready` — 503 when the database is unreachable, when a critical configuration
  value is absent, when migrations are pending, when the recorded manifest
  cannot be corroborated against the live schema, or when it cannot establish
  the answer at all. **Fails closed.** This is the healthcheck.

Yahoo does **not** gate `/ready`, by design: a deployment with no provider
configuration serves the demo, every read and every ledger surface. That is what
makes this launch possible while the retention gate is open.

---

## 4. Multi-replica safety

Railway provides no sticky sessions. The application does not need them.

| Concern | Where the state lives | Verdict |
|---|---|---|
| Authentication session | Signed JWT in an HttpOnly cookie (`auth/session.py`) — verified from the signature, no server-side session store | **stateless** |
| CSRF | Signed double-submit: the token is a claim *inside* the session JWT and a readable cookie; verification is a signature check | **stateless** |
| Demo visitor seating | `users.team_id` in PostgreSQL | **shared, durable** |
| Demo canonical reset | PostgreSQL **session-level advisory lock** `pg_advisory_lock(0x46534D4F44454D4F)` on its own connection (`demo/reset.showcase_lock`) | **cross-replica** |
| Economic writes | `SELECT … FOR UPDATE` row locks + ledger invariants | **cross-replica** |
| Release identity cache | `ops/release._CACHE` — immutable per build | per-process, harmless |
| Pool catalog | `functools.lru_cache` over two read-only JSON files | per-process, harmless |
| Filesystem | Static assets only; no writes, no uploads, no local SQLite in production | **none required** |

### The process-local fallback is not the production lock

`demo/reset.py` holds a `threading.Lock` beside the advisory lock. It is
selected **only** when `engine.dialect.name != "postgresql"` — i.e. the SQLite
developer path. In this deployment the dialect is PostgreSQL, the advisory lock
is taken, and the `threading.Lock` is never reached. `ops/demo_ledger_check`
asserts the dialect explicitly so that "we are on the PostgreSQL path" is a
verified fact rather than an assumption.

A session-level lock (not `pg_advisory_xact_lock`) is correct here because the
critical section spans more than one transaction — the in-place restore commits
and the rebuild fallback opens its own sessions. It is released in `finally`,
and a dropped connection releases it anyway, so a killed replica cannot wedge
the demo shut.

### One ordering constraint, and it is operational

`api/main.py`'s startup bootstrap is **inert** against a production database that
already has tables. On a genuinely **empty** one, two replicas would race
`create_all`. Both would not corrupt anything — PostgreSQL DDL is transactional
and the loser crashes, restarts under `ON_FAILURE`, and finds the tables present
— but a crash-looping replica during a first deploy is an incident nobody needs.

**Therefore the database is bootstrapped and seeded once, by an operator, before
the service is scaled to two.** §7 is the sequence.

---

## 5. PostgreSQL

**Provision Railway's PostgreSQL with high availability and automatic failover
if the selected plan offers it.** Whether it does is a platform fact at
provisioning time; this repository cannot configure it and does not claim it
exists. If HA is unavailable on the chosen plan, that is a deployment decision to
record, not a code change to make — and the demo can launch on single-instance
PostgreSQL with PITR provided §6 is satisfied.

**The application is already built for failover.** `db/engine_factory.py` sets,
for PostgreSQL only:

- `pool_pre_ping=True` — one round trip before a pooled connection is used, so a
  socket that died during a failover is discarded and replaced transparently
  instead of failing a request;
- `pool_recycle=300` — connections retire on our schedule rather than being
  dropped on a proxy's idle timeout.

There is **no retry loop around writes**, deliberately. Pre-ping revalidates
*before* the transaction begins, so a statement that already ran is never
re-issued. A failed transaction still fails and durable idempotency decides what
happens next.

Compatibility, all already exercised on PostgreSQL by the certified suites:
SQLAlchemy 2.0.49 / psycopg2-binary 2.9.10, transactions, `SELECT … FOR UPDATE`,
`pg_advisory_lock` / `pg_advisory_unlock`, the additive migration runner.

### Private networking

Use Railway's **internal** database hostname in `DATABASE_URL`. `db/schema.py`
normalizes the legacy `postgres://` scheme to `postgresql://`, so either form
Railway supplies is accepted.

**Do not enable a public PostgreSQL endpoint.** If an operator task genuinely
requires one — a `pg_dump` from a workstation — enable it for that task, record
why, and disable it afterwards. `railway run` and the Railway shell reach the
database over the private network and are the first choice for every procedure
in this document.

### Connection pooling — PgBouncer is NOT required at launch

| | |
|---|---|
| Replicas | 2 |
| SQLAlchemy pool per replica | default `pool_size=5`, `max_overflow=10` → 15 worst case |
| Worst-case backend connections | **30** |
| Railway PostgreSQL default limit | ~100+ |

Thirty against a hundred is not a pooling problem. Adding PgBouncer would add a
component, and in **transaction pooling mode** it would break two things this
application depends on: session-level advisory locks (which must outlive a
transaction — that is why `pg_advisory_lock` was chosen over the `_xact_` form)
and server-side prepared statements. Session pooling mode would avoid that and
also provide none of the multiplexing benefit at this scale.

**Revisit when replica count × 15 approaches the connection limit**, i.e. beyond
roughly six replicas — and if it is ever added, it must be session mode, or the
demo reset lock silently stops serializing anything.

---

## 6. Backups, PITR and restore

**Enable Railway's managed PostgreSQL backups and point-in-time recovery in the
dashboard, and record the retention window achieved.** This repository cannot
configure them and does not assert they are on. `docs/PRODUCTION_RUNBOOK.md` §7
and §8 remain the authority on logical backup and restore; this section adds
only what a *restored* database must prove before it becomes the active one.

**There is no application-layer substitute for PostgreSQL recovery, and none is
invented here.** The ledger is an append-only accounting record, not a backup
format; `trial_balance()` verifies a database, it cannot reconstruct one.

### Policy

| | |
|---|---|
| Mechanism | Railway managed PostgreSQL backups + PITR (verify plan support) |
| Logical backup | `pg_dump --format=custom` per runbook §7, stored off-instance |
| Encryption key | stored **separately** from every backup (runbook §4) |
| Restore drill | on a schedule — a backup never restored is a hypothesis |

### Restore validation — every gate, in order

Restore into a **new** database first; never over the live one.

```bash
# 1. restore (runbook §8)
pg_restore --no-owner --no-privileges --dbname fs_restore fs-<timestamp>.dump

# 2. schema at head, ledger balanced, showcase canonical
DATABASE_URL=postgresql://…/fs_restore python -m ops.demo_ledger_check --require-demo

# 3. the full standing audit — must report CLEAN
DATABASE_URL=postgresql://…/fs_restore python -m ops.audit
```

`ops/demo_ledger_check` asserts, and fails closed on any it cannot establish:

1. the dialect is PostgreSQL;
2. **migrations are current** — nothing pending;
3. **the recorded manifest is corroborated by the live schema** — this is the
   check that catches a restore whose *record* is wrong, which a pending-count
   alone cannot;
4. **trial balance = 0**, exactly;
5. the showcase demo league exists and matches the **canonical fingerprint**
   (gated by `--require-demo`, so a Yahoo deployment is not failed for having no
   demo league).

### Making a restored database the active one

1. Disable writes on the application: `FS_WRITES_DISABLED=1` with a reason
   (runbook §11). Reads, sign-in and commissioner diagnostics stay up.
2. Point `DATABASE_URL` at the restored database. **Scale `web` to 1 replica**
   for the cutover, for the §4 reason.
3. `python -m migrations.run` — if the backup predates a release, this is where
   the schema catches up.
4. `python -m ops.demo_ledger_check --require-demo` and `python -m ops.audit`.
   **Both must pass before the next step.**
5. `GET /ready` returns 200.
6. Scale back to 2 replicas, confirm `/ready` on the new instances, then clear
   `FS_WRITES_DISABLED`.
7. `python -m ops.smoke --base-url …` and, for the demo, `python -m
   ops.demo_probe --base-url …`.

**Recovery owner:** the operator holding the Railway project and the
`FS_TOKEN_ENCRYPTION_KEY` custody described in runbook §4. A restore performed
without that key yields a database whose provider grants nobody can open.

---

## 7. Seeding the showcase — operator only

`POST /demo/enter` **never seeds**. A missing showcase returns a controlled
**404 `demo_not_seeded`**, and that is certified behaviour, not an oversight: a
public route that can bring a league into existence is a public route that can be
made to bring leagues into existence repeatedly. There is no public seed
endpoint and none is added.

### First-deploy sequence

```bash
# ── with the web service at 1 REPLICA (see §4) ──────────────────────────────
railway run python -m migrations.run          # no-op on a fresh database
railway run python -m demo.seed --status      # expect: "no showcase demo league exists"
railway run python -m demo.seed               # ~20s; builds the showcase
railway run python -m ops.demo_ledger_check --require-demo
# ── then scale web to 2 replicas ────────────────────────────────────────────
```

### Idempotency, stated exactly

`python -m demo.seed` is **not** a no-op when a showcase already exists — it
retires the current one and builds a fresh league. That is safe (it refuses to
touch any league that is not demo-provider-bound, via
`demo.reset.assert_demo_league`) but it is not idempotent, and it changes the
`league_id`.

**So the safe operator command is `--status` first, always.** Run the bare seed
only when `--status` reports no showcase. The genuinely idempotent operation is
`ensure_canonical()`, which the public entry route calls and which rebuilds only
on fingerprint drift.

### Expected state after seeding

| | |
|---|---|
| League name | `FantasyStakes Demo League` |
| Provider | `demo` |
| League key | `<DEMO_LEAGUE_KEY_PREFIX>showcase.<league_id>` |
| Teams | 12 |
| Season weeks | start 1, playoffs 15, final 17 |
| Current week | **11** |
| Completed through | week 10 |
| Weekly bet minimum | 1000 cents |
| Visitor seat | ordinal 7 — **Pain Sanders** |
| Demo GM | `demo.gm@fantasystakes.invalid` (password `!demo-no-login` — not a bcrypt hash, can never validate) |
| Demo owner | `demo.owner@fantasystakes.invalid` — commissioner of demo leagues only |
| **Trial balance** | **0** — `demo.seed` exits 3 if it is not |

The seed prints every one of these; capture the output with the deploy record.

---

## 8. Deployment certification — concurrent public entry

**Do not run this until the deployment exists.** Prepared here, executed in
WEBDEPLOY-2.

```bash
python -m ops.demo_probe --base-url https://app.fantasystakesapp.com --concurrency 12
railway run python -m ops.demo_ledger_check --require-demo
railway run python -m demo.reset --check
```

`ops/demo_probe` fires twelve genuinely simultaneous `POST /demo/enter` requests
across the load balancer — so they land on both replicas — and asserts:

- all 12 answered **200**;
- all 12 report the **same `league_id`** — no duplicate showcase;
- all 12 report `demo: true`;
- **at most one** triggered a `rebuilt` action — the fingerprint short-circuit is
  working, so the public route is not a way to make the deployment replay a
  season on demand;
- the issued session authenticates and is seated on **Pain Sanders**;
- no body contains a credential term, a traceback, or `StaleDataError`.

`ops/demo_ledger_check` then supplies, from inside the deployment, the two facts
no HTTP surface exposes and none should: **trial balance = 0** and the
**canonical fingerprint**. The probe says plainly that it cannot prove those,
because a probe that claimed a zero balance it had not read would be worse than
one that admits the limit.

**The in-process gate stays too.** `test_d251_concurrent_entry.py` certifies the
code; the probe certifies the deployment. Neither substitutes for the other —
the pytest cannot observe a second replica, and the probe cannot see the ledger.

---

## 9. Railway configuration

Committed in `railway.toml`:

```toml
[deploy]
preDeployCommand   = "python -m migrations.run"
startCommand       = "uvicorn api.main_rc2:app --host 0.0.0.0 --port $PORT"
healthcheckPath    = "/ready"
healthcheckTimeout = 300
restartPolicyType  = "ON_FAILURE"
numReplicas        = 2
```

**Region — US West — is set on the service at provisioning, not in this file.**
Railway's region identifiers and its multi-region replica schema are
platform-generated values; writing a guessed key into deploy configuration is how
a deploy fails on a typo rather than on a fact. Select US West in the service
settings, then record the exact identifier here. This is the same rule §13
applies to DNS: capture generated values, never assume them.

**Load balancing is the platform's.** Railway distributes across replicas; there
is nothing to configure and nothing this application must do to cooperate,
because §4 establishes it holds no per-replica state.

**Verify against the live schema before the first deploy.** `numReplicas` and
`healthcheckTimeout` are long-standing keys; if Railway's schema has moved, the
deploy log says so and the fix is a configuration edit, not a code change.

---

## 10. Logging and observability

Startup emits two structured, greppable lines carrying no value of anything:

```
[startup] fantasystakes version=… release=… source=… env=production
          serviceable=True replica=<RAILWAY_REPLICA_ID> region=<RAILWAY_REPLICA_REGION>
          yahoo=False token_storage=True [degraded=…]
[startup] database dialect=postgresql tables=<n>
```

`replica` and `region` were added for this deployment. With one replica, "the
log" and "this process" were the same thing; with two behind a load balancer they
are not, and an interleaved log in which no line says who wrote it cannot answer
the first question a multi-replica incident asks — *is this happening on both, or
on one?* Both identifiers are read defensively and fall back to `local`; neither
is a credential.

The `dialect` line makes "PostgreSQL, as deployed" observable rather than merely
asserted — under `FS_ENV=production`, `startup_guard` already refuses to start
without `DATABASE_URL`, and this prints the result of that guarantee.

Migration and version visibility: `GET /version` and `GET /ready` (which reports
`migrations`, `schema`, `configuration`, `writes` and `yahoo_sign_in` as named
checks).

**Never logged, and enforced by design:** OAuth tokens, Yahoo secrets, the
session secret, CSRF secrets, database passwords, connection URLs, user
payloads. `ops/config.py` returns variable **names** and booleans only, and
`/ready` deliberately does not report driver exception text because a psycopg2
error can carry the connection URL. `ops/smoke.py` sweeps every response body it
reads for credential markers and fails the deploy if one appears.

### External uptime monitoring is WEBDEPLOY-2

**Railway health checks are deployment health checks, not continuous runtime
monitoring.** They gate a release and then stop asking. An external monitor
polling `/ready` from outside the platform — and alerting a human — is required
before this is a service anyone should rely on. No vendor is added in this pass.

---

## 11. Environment variables

### REQUIRED for the synthetic demo launch

| Variable | Why |
|---|---|
| `FS_ENV=production` | **Not the default.** Without it the deployment is "development": the password sign-in routes work and the dev sign-in control is drawn on the gate. This single variable is what retires them. |
| `DATABASE_URL` | Railway **internal** hostname. Without it a production process refuses to start (it would otherwise write the season into an ephemeral container's SQLite file). |
| `JWT_SECRET_KEY` | Session and CSRF signing. Strong, random, environment-supplied. Refuses to start without it. |
| `FS_TOKEN_ENCRYPTION_KEY` | Refuses to start without it, even with no Yahoo configured — see the note below. |

**Why the encryption key is required for a demo that has no Yahoo.**
`ops/config.py` grades it CRITICAL for any production process. The demo does not
use it, but the alternative is a deployment that would accept a Yahoo sign-in and
silently drop the grant if Yahoo were ever configured on it. Generate one with
`python -c "from auth.token_crypto import generate_key; print(generate_key())"`
and store it in Railway's secret store. Never commit it; never place it in a
database backup.

### OPTIONAL — set if applicable

| Variable | Effect if unset |
|---|---|
| `FS_PUBLIC_BASE_URL` | Degraded. Absolute URLs would come from a client-supplied Host header. Set to `https://app.fantasystakesapp.com` once DNS is authorized. |
| `FS_ALLOWED_ORIGINS` | **Leave empty.** Empty means no cross-origin access at all, which is correct for a single-origin app — same-origin requests never consult CORS. Exact origins only; there is no wildcard. |
| `FS_RELEASE` | Railway supplies `RAILWAY_GIT_COMMIT_SHA`, which the release identity already reads. |
| `FS_TOKEN_KEY_ID` | Only for encryption-key rotation (runbook §5). Unset until a rotation is in progress. |

### REQUIRED ONLY FOR THE YAHOO-CONNECTED LAUNCH — **do not set yet**

`FS_YAHOO_CLIENT_ID`, `FS_YAHOO_CLIENT_SECRET`, `FS_YAHOO_REDIRECT_URI`.

Absent, they are graded **degraded, not critical**: the deployment is ready,
serves the whole demo, and the sign-in surface says Yahoo is not configured in
product language. Setting them is what turns Yahoo sign-in on — see §12.

### MUST NOT BE SET

| Variable | Why |
|---|---|
| `FS_COOKIE_INSECURE` | Drops `Secure` from the session cookie. `production_readiness()` reports it as a production failure. |
| `FS_WRITES_DISABLED` | The emergency write-disable. Set it only during a restore cutover (§6). |
| `FS_TEST_AUTH_EMAIL` / `FS_TEST_AUTH_PASSWORD` / `FS_TEST_ORIGIN` | Harness variables. |
| `FS_YAHOO_*` | Until the retention gate closes and a Yahoo-connected launch is certified. |

**No secret is in Git**, and none is added by this deployment package.

---

## 12. Yahoo gating

**The retention gate is OPEN and this deployment does not change that.**
`ops/yahoo_retention.py` records what the software persists so the contractual
question can be answered against facts; it implements no retention rule, because
none has been granted, and nothing in this package deletes a safeguard to make
the question easier.

**What keeps a Yahoo-connected workflow out of this deployment is configuration,
and it is checkable:**

1. **`FS_YAHOO_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` are not set.**
   `auth_capabilities().yahoo` is then False, `GET /auth/methods` reports Yahoo
   as unavailable, the gate does not offer it, and `GET /ready` reports
   `yahoo_sign_in: not_configured`. There is no OAuth client to start a flow
   with, so the callback cannot be reached and no grant can be recorded.
2. **`FS_ENV=production` retires the password login.**
   `_refuse_password_login_in_production()` guards `/auth/register`,
   `/auth/token` and `/auth/login`, and the refusal is a named reason code, not
   a hidden control. The cutover **fails closed**: a production process with
   incomplete Yahoo configuration does *not* quietly re-enable passwords.
3. **`POST /demo/enter` is the only public way in**, it takes no parameters, and
   it seats the caller as the demo GM — an account whose stored password
   `!demo-no-login` is not a bcrypt hash and can never validate, which
   commissions demo leagues only and holds authority over no Yahoo, unbound or
   impostor league (`test_d1_demo_environment.py` drives exactly that).

**Verify on the deployment before announcing it:**

```bash
curl -s https://app.fantasystakesapp.com/ready   | grep yahoo_sign_in   # not_configured
curl -s https://app.fantasystakesapp.com/auth/methods                   # yahoo: false
```

This gating is **sufficient** and is a deployment blocker only if 1 and 2 are not
both true at launch. It is not a substitute for answering the retention
question — it is what makes the demo launch independent of the answer.

---

## 13. Custom domain — prepared, not applied

**No DNS change is authorized by this package and none has been made.**

| Host | Purpose | Phase |
|---|---|---|
| `fantasystakesapp.com` | marketing website | later |
| `app.fantasystakesapp.com` | this application + demo | when authorized |

When DNS is authorized:

1. Create the Railway service and deploy it. Confirm it serves on its
   `*.up.railway.app` hostname and that `/ready` returns 200.
2. Add `app.fantasystakesapp.com` as a custom domain **on the `web` service**.
3. **Railway then generates the DNS records to create.** Capture the generated
   values verbatim — host, type and target — and put them in the deploy record.
   **Do not pre-write a `CNAME` target here.** Railway's routing and verification
   targets are per-service and per-account; a value assumed in advance is a value
   that will be wrong and will look right.
4. Create the records at the registrar exactly as generated. Wait for Railway to
   report the domain verified and its certificate issued.
5. Set `FS_PUBLIC_BASE_URL=https://app.fantasystakesapp.com` and redeploy.
6. `python -m ops.smoke --base-url https://app.fantasystakesapp.com --expect-release <sha>`.

The apex `fantasystakesapp.com` is **not** pointed at this service. The marketing
site is a separate phase, and pointing the apex at the application now would make
the demo the front door of the company.

---

## 14. Pre-launch security checklist

| Check | State |
|---|---|
| Production debug off | No `debug=True` anywhere; FastAPI defaults off. `/ready` and `/health` report grades, never driver text — a psycopg2 error can carry the connection URL. |
| Secure cookies | `Secure`, `HttpOnly`, `SameSite=Lax`, `path=/` (`auth/session.py`). `Secure` is on unless `FS_COOKIE_INSECURE=1`, which **must not be set**, and is never inferred from the request scheme — a misconfigured proxy cannot downgrade it. |
| CSRF | Signed double-submit: token as a claim inside the signed session JWT plus a readable cookie, echoed in `X-FS-CSRF`, with Origin checked as defence in depth. A token minted for the API path carries no `csrf` claim and is refused in the cookie. |
| Session secret | `JWT_SECRET_KEY`, environment-supplied, refuses to start without it. |
| CORS | `FS_ALLOWED_ORIGINS`, exact origins, **no wildcard**. Leave empty. |
| Public database | **None.** Private networking only (§5). |
| Public operator seed | **None.** `/demo/enter` returns 404 on an unseeded deployment and never creates a league. |
| Test-only admin bypass | Password routes refuse under `FS_ENV=production`. `FS_TEST_AUTH_*` unset. |
| Showcase commissioner credential | `demo.owner@…` holds a non-validating password hash and is never seated by any public route; the visitor gets the GM's view. |
| Yahoo tokens | Sealed at rest under `FS_TOKEN_ENCRYPTION_KEY`; no grant exists on a deployment with no Yahoo configured. `ops/smoke.py` fails the deploy if any token term appears in a response body. |
| Stack traces to public users | None. Errors are named reason codes; `ops/demo_probe` fails if a traceback or driver error appears in any body. |

### `/demo/enter` abuse — the one open item

**There is no rate limit on `POST /demo/enter`,** and it is unauthenticated by
design. The exposure is bounded rather than absent:

- it takes no parameters and cannot name a league;
- it **cannot create** a league — an unseeded deployment returns 404;
- the expensive path is guarded by a fingerprint short-circuit: an unmodified
  showcase takes a cheap read, so the rebuild fires only after a visitor has
  actually changed something;
- concurrent callers **serialize on one advisory lock**, so a burst becomes a
  queue rather than a stampede.

The residual risk is a determined caller alternating mutation and re-entry to
force repeated rebuilds — a self-inflicted denial of the *demo*, not of the
application, and not a path to any real league. **Mitigate at the edge, not in
the application:** enable Railway's platform rate limiting on the route, or place
the demo behind a CDN/WAF rule, in WEBDEPLOY-2. Adding an in-application limiter
would put per-replica counters back into an application whose whole
multi-replica argument is that it holds none.

---

## 15. Resolved — S6 gate C-7 and the synthetic finality writer

**Closed by WEBDEPLOY-1a.** `test_s6_provider_gateway_pg.py` C-7 passes on this
branch. The record is kept because the shape of the problem matters more than
the fix.

### What failed, and where it came from

C-7 walks the repository and asserts that the four load-bearing `Matchup`
fields — `finalized_at`, `home_score`, `away_score`, `winner_team_id` — are
written in production code only by certified writers. `demo/states.py`'s
`finalize_week` assigns all four to post the showcase fixture's result onto
matchup rows the seeder already created, and `demo/` ships, so the `test_*`
fixture exemption did not cover it.

It was **inherited, not introduced by the composition.** Measured on all three
trees:

| Tree | C-7 before WEBDEPLOY-1a |
|---|---|
| `fantasystakes-1.0.0-rc3` (`9490127`) — no `demo/` | passes |
| `preprod/demo-environment` (`8b3daaf`) — certified demo | **FAILS** |
| `deploy/fantasystakesapp-demo` (`9051f72`) | **FAILS**, identically |

The certified demo commit fails a production gate its own certification never
ran. That is a gap in the demo certification, not in this composition — see §17.

### The certification model, and why it is not a path exemption

`allowed_orm` exempts whole FILES, which is right for the provider writers:
those modules exist to be the writer and hold nothing else. `demo/states.py` is
not like that — it is a 370-line module that also drives the season, the
championship and the close — so a file exemption would have licensed every
future function written in it.

So the grant is **(file, module-level function)**, resolved from the AST:

```python
_CERTIFIED_FUNCTION_WRITERS = {"demo/states.py": ("finalize_week",)}
```

`demo/evil_writer.py` fails even with a function of the same name; a second
function or a method in `demo/states.py` fails; a nested closure inside
`finalize_week` fails; module scope fails; a `demo/states.py` that will not parse
fails closed. Nine such cases run **inside the gate itself** against the real
classifier, so the grant cannot widen without C-7 saying so.

### The writer was made to guard itself

Before this, `finalize_week`'s safety was entirely its callers': `advance_to_final`
and `retire_showcase` each call `assert_demo_league` first and take their league
from `find_showcase` rather than from an argument. True, and fragile — the safety
of a certified writer should not be a property of the three call sites that
happen to exist today. `assert_demo_league(league)` is now its first statement,
matching the standard `providers/persist.py` is held to. No behaviour changes on
any existing path.

### It is proven by behaviour, not by comment

`test_d26_demo_finality_guard.py` builds five **structural clones** of the
showcase — same twelve team names, same week-11 pairings, rows unfinalized — under
five false identities, so the writer's own row lookup genuinely resolves against
them and a refusal cannot be an artefact of an empty query. All five are refused
and left byte-identical; a legitimate call reaches only its own league and week;
`finalized_at` moves NULL → timestamp and never back; a repeat call is an exact
no-op; and no HTTP route reaches the writer.

Removing the guard makes that suite fail with the Yahoo clone's rows actually
rewritten — measured, which is what makes the suite worth keeping.

---

## 16. Tests

Both suites must remain green on this branch — that is the claim the composition
makes. `docs/PRODUCTION_RUNBOOK.md` §15 lists the production gates; the demo
gates are `test_d1_demo_environment.py`, `test_d24_complete_lifecycle.py`,
`test_d24_hostile_gameplay.py`, `test_d24_determinism.py`,
`test_d251_concurrent_entry.py` and `test_d26_demo_finality_guard.py`.

**Run both families over the composed tree, every time.** `run_pg_suites.py`
covers the 63 production PostgreSQL suites and does NOT pick up the demo
suites, which carry no `_pg` suffix. Running only one family is exactly how a
production gate came to be failing on a certified demo branch for a whole
release — see §15.

**PostgreSQL is authoritative.** A SQLite pass is a smoke test of the test, not
of the product: advisory locks, `FOR UPDATE` semantics and JSONB behaviour are
exactly what the deployment depends on and exactly what SQLite does not have.

---

## 17. Status of the original demo certification

**The certified demo commit `8b3daaf` is immutable and is not being reissued.**
It is not moved, not rewritten and not retagged by this package.

**It should nonetheless be treated as certified INCOMPLETELY.** Not wrong — the
demo's own D1 and D2.x gates were run and passed there, and every finding in §15
concerns a control the demo commit never executed rather than a defect in what it
demonstrated. But `test_s6_provider_gateway_pg.py` fails on that commit as it
stands, and it fails for a real reason: the tree contains a fifth writer of the
protected `Matchup` fields, and nothing on that branch had asked whether that was
allowed.

The distinction that matters:

| | |
|---|---|
| Does the demo work as certified? | Yes — D1, D2.4 ×3 and D2.5.1 pass on `8b3daaf` |
| Was the demo's finality writer ever certified? | **No** — S6 was never run there |
| Is it certified now? | Yes, on `deploy/fantasystakesapp-demo` |

**So this work does more than unblock the deployment composition.** Had the demo
branch ever been merged, tagged or deployed on its own, it would have carried an
uncertified writer of the four fields that decide whether a settled result can be
rewritten. The composition is what surfaced it; the fix belongs to the demo
surface, not to the composition.

**What follows from that:**

1. Any future release that carries `demo/` must run **both** gate families — the
   production PostgreSQL sweep and the demo suites (§16). Neither is a superset
   of the other.
2. If `preprod/demo-environment` is ever advanced, the WEBDEPLOY-1a changes —
   the `assert_demo_league` self-guard in `finalize_week`, the function-scoped
   C-7 grant, and `test_d26_demo_finality_guard.py` — must travel with it.
3. Nothing here retroactively invalidates the demo's own certification of what
   it demonstrates. It records that one production control had not been applied
   to it, and that it now has been.
