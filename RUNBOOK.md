# FantasyStakes — Runbook

Everything needed to **edit → test → run → deploy** without reconstructing
commands. Written at S8-P5. If a command here stops working, fix the command
here rather than working around it in a shell.

---

## 1 · Prerequisites

| Thing | Version used at P5 | Notes |
|---|---|---|
| Python | 3.13 | `requirements.txt` pins the dependency set |
| Node | 24.x | browser/component suites only |
| Chrome or Edge | any recent | headless, driven over CDP |
| Docker | 29.x | **only** for the PostgreSQL test database |
| PostgreSQL | 16.14 (container) | required for the P5 hardening suites |

```bash
python -m pip install -r requirements.txt
```

Node has no package manifest: the suites use only the standard library and talk
to Chrome over the DevTools protocol.

---

## 2 · Configuration

Two environment variables matter, and neither has a safe default:

| Variable | Purpose | Failure if unset |
|---|---|---|
| `DATABASE_URL` | the application's database | falls back to a local SQLite file |
| `JWT_SECRET_KEY` | session/token signing | **falls back to a dev-only secret — set this in any deployment** |

Optional:

| Variable | Purpose |
|---|---|
| `FS_ALLOWED_ORIGINS` | comma-separated exact origins for CORS. Empty means none — there is no wildcard. |
| `FS_COOKIE_INSECURE` | drops `Secure` on cookies so http test harnesses work. **Never set in production.** |
| `TEST_DATABASE_URL` | disposable PostgreSQL for the PG suites. Never the live database. |
| `YAHOO_PRIVATE_JSON` + `YAHOO_CONSUMER_SECRET` | live provider access. Absent → the gateway refuses and the UI shows its provider-unavailable state. |

### 2.1 Authentication (WP3D.1)

Production authentication is **Sign in with Yahoo**. There is no production
username/password login, no forgot-password flow and no password reset.

| Variable | Purpose | Failure if unset |
|---|---|---|
| `FS_ENV` | `production` \| `development`. Defaults to `development`. | **A deployment that does not set `production` will still accept the development password login. Set it.** |
| `FS_YAHOO_CLIENT_ID` | Yahoo OIDC client id | production sign-in refuses; `/health` reports `degraded` |
| `FS_YAHOO_CLIENT_SECRET` | Yahoo OIDC client secret — server-side only, never in the frontend | as above |
| `FS_YAHOO_REDIRECT_URI` | the exact callback this deployment registered with Yahoo, e.g. `https://your-host/auth/yahoo/callback`. Must be `https`, or `localhost` for development. | as above |

**Fail closed, not fail back.** A process with `FS_ENV=production` refuses the
password routes whether or not the Yahoo configuration is present — a missing
client id produces a broken sign-in, never a silent downgrade to passwords.
`GET /health` reports `status: degraded` and lists the missing variable NAMES
(never values) in `auth_missing`, so a deployment can be inspected before it is
trusted. `GET /auth/methods` reports which logins the running process offers.

The development password login (`POST /auth/session`) is what the automated
suites and a local Rev 4.3 review use. It is unavailable whenever
`FS_ENV=production`, and the browser gate does not render a password field
unless the server declares the method.

Run the identity migration once per database before the first production deploy
of this change:

```bash
python migrations/add_yahoo_identity.py
```

It is additive, idempotent and non-destructive: it adds `users.auth_provider`
and `users.provider_subject`, adds the unique index that makes one Yahoo account
one FantasyStakes account, and drops nothing. Existing password hashes are left
in place so a rollback to pre-WP3D.1 code still works.

Secrets live in `secrets/` or the environment. `.gitignore` covers `secrets/`,
`.env` and `.env.*`; nothing secret is tracked.

---

## 3 · Local run, from a fresh shell

```bash
# 1 · dependencies
python -m pip install -r requirements.txt

# 2 · a local database (SQLite is fine for development)
export DATABASE_URL="sqlite:///$PWD/dev.db"
export JWT_SECRET_KEY="local-dev-only-change-me"

# 3 · schema + migrations
python -c "from db.schema import Base, engine; Base.metadata.create_all(engine)"
python -c "from ledger.ledger import create_ledger_table; create_ledger_table()"
python db/migrations/migrate_s8_provider_current_week.py

# 4 · seed a development league (optional but recommended)
#     This is the same authoritative Rev 4.2 fixture the suites use.
python - <<'PY'
from db.schema import Base, League, SessionLocal, Team, User, engine
from auth.jwt_auth import hash_password
from ledger.ledger import create_ledger_table
from test_support_rev42_fixture import _seed_accounting_fixture
Base.metadata.create_all(engine); create_ledger_table()
with SessionLocal() as db:
    league = League(name="Dev League", season=2026, provider_current_week=5)
    db.add(league); db.flush()
    gm = Team(team_name="Gravy Train", owner="Dev GM",
              email="gm@dev.test", league_id=league.id)
    opp = Team(team_name="The Braintrust", owner="Dev Opp",
               email="opp@dev.test", league_id=league.id)
    db.add_all([gm, opp]); db.flush()
    pw = hash_password("devpassword")
    db.add_all([User(email=gm.email,  hashed_password=pw, team_id=gm.id,  role="gm"),
                User(email=opp.email, hashed_password=pw, team_id=opp.id, role="commissioner")])
    db.flush()
    _seed_accounting_fixture(db, league, gm, opp)
    db.commit()
    print("seeded league", league.id)
PY

# 5 · run it — the API serves the frontend at /app from the same process
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload

# 6 · open  http://127.0.0.1:8000/app   and sign in as gm@dev.test / devpassword
```

**Stop:** `Ctrl-C`.
**Reset development data:** delete `dev.db` and repeat step 3.
There is no separate frontend server — `api/main.py` mounts `web/` at `/app`, so
a JS or CSS edit is visible on reload with no build step.

---

## 4 · Test workflow

Five tiers. Use the smallest one that covers the change.

### 4.1 Fast targeted — a component, copy or layout change

```bash
node web/tests/package2_component_tests.mjs     # League + Action
node web/tests/package3_component_tests.mjs     # The Week + Ledger
node web/tests/package4_component_tests.mjs     # Rules & Settings
```

Seconds. No server, no database.

### 4.2 Module regression — one backend subsystem

```bash
python test_s8_p4c1_lifecycle_cutover.py        # proposal lifecycle + money
python test_s8_p4c2_action.py                   # Action read model + commands
python test_s8_p4c3_provider_binding.py         # provider/current week
python test_s8_p4c4_pool_certification.py       # Pool reachability + ownership
python test_s8_p3_read_models.py                # accounting read models
```

### 4.3 Browser / UI certification — anything that renders

```bash
python test_s8_p4c5_integration.py              # five tabs x 375/390/430
python test_s8_p4c2_action_browser.py           # seven Action states
python test_s8_p4c3_provider_browser.py         # bound + pending provider
python test_s8_p4b3r_browser.py                 # settings + Pool slate
```

Each starts its own disposable SQLite app-server and headless Chrome.

### 4.4 PostgreSQL hardening — anything touching money, locking or schema

```bash
docker run -d --name fs-pg -e POSTGRES_PASSWORD=devpass -e POSTGRES_USER=fs \
  -e POSTGRES_DB=fantasy_p5_test -p 55432:5432 postgres:16

export TEST_DATABASE_URL="postgresql://fs:devpass@127.0.0.1:55432/fantasy_p5_test"

python run_pg_suites.py            # all 48 PG suites, fresh database each
python run_pg_suites.py --only spec1     # substring filter
python test_s8_p5_postgres_hardening.py  # concurrency / double-spend

# Sprint 6 provider certification, C-1 .. C-17. It needs its OWN empty database.
docker exec fs-pg psql -U fs -d fantasy_p5_test \
  -c 'DROP DATABASE IF EXISTS fs_s6_certify_test WITH (FORCE);' \
  -c 'CREATE DATABASE fs_s6_certify_test;'
TEST_DATABASE_URL="postgresql://fs:devpass@127.0.0.1:55432/fs_s6_certify_test" \
  python -m providers.certify.run

docker rm -f fs-pg
```

`run_pg_suites.py` exists because the suites split into two families — some own
their schema, some refuse a non-empty database — so each gets its own database,
dropped afterwards. See its docstring.

### 4.5 Full MVP certification — before closing a package

Run 4.1 → 4.4, then the Sprint 8 stack:

```bash
for t in test_s8_p1_session_auth.py test_s8_p2_authorization.py \
         test_s8_p3_read_models.py test_s8_p4b1_fixture.py \
         test_s8_p4b2_binding.py test_s8_p4b3_settings_pool.py \
         test_s8_p4b3r_browser.py test_s8_p4c1_lifecycle_cutover.py \
         test_s8_p4c1r_wagering_authority.py test_s8_p4c2_action.py \
         test_s8_p4c2_action_browser.py test_s8_p4c2r2_final_lock_copy.py \
         test_s8_p4c3_provider_binding.py test_s8_p4c3_provider_browser.py \
         test_s8_p4c4_pool_certification.py test_s8_p4c4_pool_pick_browser.py \
         test_s8_p4c5_integration.py; do
  python "$t" >/dev/null 2>&1 && echo "PASS $t" || echo "FAIL $t"
done
```

**Known environmental skips**, reproduced identically on the accepted baseline:

- `test_yahoo_*`, `test_fantasypros_historical` — need network/provider access

**Corrected at WP5.** This list previously also named the S7 `e2e_package*.mjs`
browser suites ("Chrome launch flakiness") and `test_s4_pool_engine_unit.py`.
Neither was environmental and neither was flaky:

- The browser suites failed because `browser-harness.mjs` falls back to a static
  file server when `FS_TEST_ORIGIN` is unset, and since S8-P1 the shell asks
  `/auth/me` before it draws anything — so a static server produced the sign-in
  gate and every selector dereferenced null. The four S7 package suites now call
  `test_support_s7_harness.ensure_authenticated_app()`, which starts a real
  application when one is not already supplied. They run standalone.
- Behind that failure, four Sprint 8 packages had left assertions pinned to
  superseded copy and to prototype figures. Those were invisible for as long as
  the suites were red for the harness reason, which is the actual cost of
  carrying a "known failure" on a list. See the WP5 report.
- `test_s4_pool_engine_unit.py` passes (18 tests) and always did under pytest;
  it collects nothing when run as a plain script.

**Run the S7 suites standalone** — each starts its own application:

```bash
python test_s7_p1_ui_shell.py
python test_s7_p2_league_action.py
python test_s7_p3_week_ledger.py
python test_s7_p4_rules_commissioner.py
```

On Windows, set `PYTHONIOENCODING=utf-8` before running suites that print `→`
or `−`, or they die with a `UnicodeEncodeError` that looks like a real failure.

---

## 5 · Deployment

**Classification: B — partial deployment artifacts exist.**

Present and coherent:

| Artifact | Contents |
|---|---|
| `Procfile` | `web:` the API; `final_lock:` the Dynamic Final Lock worker |
| `railway.toml` | NIXPACKS builder, the `web` start command, healthcheck `/health`, restart on failure |
| `railway.final_lock.toml` | NIXPACKS builder, `python -m workers.final_lock --loop --interval 60`, no healthcheck |
| `.railwayignore` | excludes `*.sql`, backups and scratch/debug artifacts |
| `requirements.txt` | the full dependency set |

### 5.1 The Final Lock worker (WP6B) — a required second process

**A deployment that runs only `web` is incomplete.** Dynamic challenges are
issued and handshaken over HTTP, but Final Lock is machine-triggered:
SIMULATION_ENGINE_MODULE_SPEC_Rev9 §5.5 fixes its actor as "the same scheduled
system worker/process class that acquires fresh claims. Not an end user, not a
GM, not a commissioner, not reachable from any HTTP route." With this process
absent, every handshaken Dynamic wager strands both sides' escrow and Season
Close is refused at `escrow_resolved` forever — the blocker WP6 reported.

```bash
python -m workers.final_lock --loop --interval 60   # production: resident worker
python -m workers.final_lock                        # one sweep, then exit
python -m workers.final_lock --dry-run              # what would lock; claims nothing
python -m workers.final_lock --league 19 --verbose  # one league, full report
```

It needs `DATABASE_URL` and nothing else. Run it as a second Railway service
whose config path is `railway.final_lock.toml`, or as the `final_lock` Procfile
process type on any platform that reads one.

**Cadence is not the timing rule.** `_nfl_lock_time(LOCK_SEASON, week)` alone
decides when a challenge is due — the earliest covered kickoff — and `--interval`
only bounds how long after that instant the worker notices. A resident loop is
used rather than a platform cron because Final Lock fires *at* kickoff and
platform cron granularity is coarse; sixty seconds of latency sits well inside
the fifteen-minute claim TTL and hours inside the settlement window.

**More than one instance is safe.** The claim table's `UNIQUE(challenge_id)` is
the mutex — concurrent workers race the same insert and exactly one proceeds. A
worker killed mid-execution rolls its economic work back atomically, and its
claim becomes reclaimable once the TTL passes.

**Not verified from this repository:** that a Railway project, service,
environment, database or domain actually exists. No credentials are present and
none were created. Nothing was deployed.

### What remains before a first deploy

1. A hosting target with a PostgreSQL instance.
2. Set in the target's environment:
   - `DATABASE_URL` — the managed PostgreSQL URL
   - `JWT_SECRET_KEY` — **a real secret.** Without it the app signs sessions
     with a published dev default.
   - `FS_ALLOWED_ORIGINS` — the exact frontend origin(s)
   - `YAHOO_PRIVATE_JSON` + `YAHOO_CONSUMER_SECRET` — optional; absent means the
     provider surfaces render their unavailable state honestly.
   - **Do not** set `FS_COOKIE_INSECURE`.
3. Run the schema + migration steps of §3 against the deployed database.
4. Confirm `/health` returns 200.
5. Start the `final_lock` worker process (§5.1). Confirm it logs
   `[final-lock] worker … starting`; without it Dynamic wagers cannot settle.

### Repeatable deploy path, once a target exists

```bash
# 1 · certify locally first — §4.5 plus §4.4
# 2 · commit
# 3 · deploy (Railway example; the platform builds from the repo)
railway up
# 4 · migrate
railway run python db/migrations/migrate_s8_provider_current_week.py
# 5 · verify
curl -fsS https://<host>/health
# 6 · verify the system worker is resident (§5.1) — no HTTP surface exists for it
railway logs --service final-lock | grep '\[final-lock\] worker'
```

Restart is the platform's own restart; the process is stateless apart from the
database.

---

## 6 · Post-MVP product modes — documented seam only (P6)

Not implemented. Recorded so P6 starts from the existing architecture.

### 6.1 production vs demo

The three-mode discipline already shipped — every read model is `demo`,
`authoritative` or `unavailable`, and **a failed production read never falls
back to demo**. Standalone Demo Mode reuses it:

- **exists**: mode plumbing in every model; illustrative fixtures under
  `web/js/data/`; a `FixtureTransport` that replays a recorded provider corpus.
- **missing**: a deployment-level switch that selects a synthetic provider and a
  seeded fictional league; a reset endpoint; a visible demo banner. The switch
  must be explicit — the existing rule that production never degrades into demo
  must survive it.

### 6.2 multi-league / multi-team membership

- **exists**: `/auth/me` already serves `acting_league_id`, `acting_team_id` and
  `acting_context_ambiguous`; `currentLeagueId()` returns `null` rather than
  guessing when a user has more than one context; every read route is
  league-scoped and refuses a non-member.
- **missing**: a `User ↔ Team` relation beyond `User.team_id` (one team per
  user today); a league switcher; persistence of the chosen active context.
  The refusal path is already correct, so this is additive.

### 6.3 commissioner onboarding + Yahoo import

- **exists**: `LeagueCommissioner` is league-scoped with a `source` column;
  `require_league_commissioner` / `assert_league_commissioner`; the whole
  provider gateway (`providers/yahoo/`) with identity, normalisation,
  persistence and conflict recording; `load_credentials()` fails closed.
- **missing**: an OAuth authorization flow, per-league token custody, a
  league-picker after authorization, and an import trigger.
  **FantasyStakes must never store a Yahoo password** — the flow is OAuth
  tokens only, which is what `load_credentials()` already expects.

---

## 7 · Security notes

- No secrets are tracked. `secrets/`, `.env`, `.env.*` are ignored.
- `JWT_SECRET_KEY` falls back to a published dev default — **this is the single
  most important variable to set in any deployment.**
- CORS is an explicit exact-origin allowlist; empty by default, no wildcard.
- Session cookie: `HttpOnly`, `Secure` (unless `FS_COOKIE_INSECURE`),
  `SameSite=Lax`, with a separate script-readable CSRF cookie and the
  `X-FS-CSRF` header required on every state-changing request.
- The browser persists **no token** — nothing in `localStorage` or
  `sessionStorage`.
- The frontend talks only to this application's own API. No direct Yahoo call
  is made from the browser.
