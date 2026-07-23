# FR-VAL10-af IMPLEMENTATION MODULE_SPEC
## Canonical Engine Control Surface and SQLite Foreign-Key Enforcement

**Revision:** Rev 8 (FR-VAL10-af SATISFIED)
**Revision date:** 2026-07-22
**Parent:** `VAL-10_MODULE_SPEC_Rev23_FROZEN.md` — FR-VAL10-af
**Baseline:** HEAD `19aa0bef26d3e9e684c9722e3d0b5e35290d40ec` (recon-confirmed, no drift)
**Branch:** `remediation/foundation-phase-1`
**Money-path status:** NOT money-path. Moves no cents, touches no ledger, no cap arithmetic. No Opus math-review gate required.
**Recon status:** Live anchors confirmed 2026-07-22. All eight engine constructors classified.

### Revision history

| Rev | Date | Change |
|---|---|---|
| 1 | 2026-07-22 | Initial implementation spec against live HEAD anchors. |
| 8 | 2026-07-22 | **FR-VAL10-af SATISFIED.** af-2 PostgreSQL parity executed and green. §6 completion criteria marked satisfied with the execution record: local Docker `postgres:16` (`pg-fantasy-test`, port 5433, db `fantasy_test`); `test_support_postgres.py` created 41 tables, reset/teardown OK, exit 0; `test_beef_settlement_escrow_close_pg.py` S1–S4 passed under real `FOR UPDATE`/`REPEATABLE READ`, exit 0. Recorded why the Railway-hosted instance was abandoned: Guard 4 (`:177`) categorically forbids Railway hosts at any database name, and **Guard 4 was not weakened, bypassed, or reinterpreted** — relaxing a destructive-operation safety check to pass a gate inverts the discipline held since af-1's T4a failure. §11 updated from blocked to satisfied. Carried forward, not closed: FR-AF-ENC-1 (encoding hazard, 24 scripts unscanned), FR-AC-ISO-1 (`beef_engine.py:877` isolation-ignored warning, verify during ac), environment parity 3.13/3.12. Container left running for ac. §1 Purpose also updated: it still read "At HEAD there is no mechanism" (present tense, true at Rev 1, false since `0f4a04d`) — caught by the status-sweep rule. Also corrected in §6: "The legacy migration (ai–al) may be designed in parallel with af-2. It is not implementation-verified until the FK-enforced suite is green" — a forward-looking dependency statement, true until af-2 closed. Replaced with the satisfied-prerequisite wording. Note the class: **dependency language goes stale exactly like status language**, and the status-sweep rule should be read to cover both. |
| 7 | 2026-07-22 | **af-2 scope established by read-only discovery scan** (run at `0f4a04d`, no edits). §6 af-2 rewritten from "unbounded" to the measured result: 25 runnable scripts, 23 pass, 2 fail — one FK teardown (`test_pool_engine_conversion.py:754`, authorized repair) and one Windows cp1252 encoding defect (`test_beef_starters.py:386`, separate authorized cleanup, not FK-related). Every test body and setup already FK-clean. Inventory reconciled: 30 files − 6 P1-L2 − 1 af-1 = the historical 23; no correction needed. Added: explicit exclusion of the three external-provider integration tests as **out of scope and unrun** (not "passed by inspection"); binding af-2 completion criteria making PostgreSQL parity a required deliverable that a safe skip does not satisfy; §6.1 recording `db/migrate_full_beef.py:16` `PRAGMA foreign_keys=OFF` as a bounded migration-local exception rather than reporting no matches. **af-2 is blocked on the same `TEST_DATABASE_URL` instance as FR-VAL10-ac §11.2.** Also corrected: §11 still carried the Rev 1 line "af-2: NOT YET AUTHORIZED. Scope is unknown until af-1 lands" — stale through six revisions and directly contradicting §11's own authorization statement four paragraphs above it. Replaced with the PostgreSQL-parity blocker. |
| 6 | 2026-07-22 | **Post-build corrections. Documentation only — no behavioral change, no rebuild, no re-authorization.** (1) §3 site 6 path corrected from `scripts/seed_player_id_map.py:45` to `seed_player_id_map.py:45` — the file is at repo root. The recon table carried the wrong directory. Count was and remains exactly eight; T6 independently reconfirmed the inventory at the current tree, so no stop condition fired and the build is unaffected. (2) Added §5.7 recording the accepted implementation variance in `scripts/resolve_player_nfl_teams.py` — a function-local repo-root bootstrap inside `main()`, required because that site alone lacked a direct-execution import path to the `db` package. Disposition A, placement not to be moved to module scope. (3) Build outcome recorded: af-1 control-surface green, 13/13 Rev 6 control tests, smoke-verified on the production engine path. FR-VAL10-af remains unsatisfied pending af-2. (4) §11 control-tests status line corrected from "Rev 4 — red baseline, ready to run" (stale by two revisions, and contradicted by the build outcome recorded immediately above it) to "Rev 6 — 13/13 green". |
| 5 | 2026-07-22 | Editorial cleanup, non-blocking, no change to authorization. §5.4 still read "Grep-based assertion is acceptable," which predated the Rev 4 AST ruling and would have licensed a weaker guard than §9 Test 6 requires. Replaced with the explicit AST requirement covering aliases and both the `sqlalchemy` and `sqlalchemy.engine` namespaces. §5.4 and §9 now state the same control. |
| 4 | 2026-07-22 | **Structural contract recorded.** Rev 3 authorized the build without stating the symbol names and attachment target the af-1 control tests assert against. Added: §5.1 contract table (module `db.engine_factory`, factory `get_engine`, hook `_sqlite_foreign_keys_on_connect`, attached to the individual SQLite engine's **pool** `connect` event, never to PostgreSQL pools), with the note that the private symbol exists solely to make registration scope exactly testable and is **not application API**. Added §5.6 af-1 environment prerequisite: a PostgreSQL DBAPI driver (`psycopg2`/`psycopg2-binary`) must be importable because `create_engine()` imports the driver at **construction** time; no live server needed for T4/T4a/T4b; `TEST_DATABASE_URL` (T4c) optional for af-1, mandatory separately for ac. Test table updated to the delivered set: 4/4a/4b/4c split, 6 restated as AST-based across both SQLAlchemy namespaces, 6b added. Empirical basis for the pool-vs-engine distinction recorded. No change to the requirement, the option policy, the af-1/af-2 split, or authorization. |
| 3 | 2026-07-22 | **af-1 authorized for build against HEAD `19aa0be`.** Two editorial corrections, non-blocking: §5.3 now defers to §5.5 rather than saying "preserve each site's existing options" (broader than the policy); §5.5 categories tightened to separate **excluded** (recognized for another dialect, silent) from **rejected** (recognized for no dialect, raises), removing the ambiguity that let `connect_timeout` under SQLite read as both. Tests 5a/5b realigned to the two dispositions. |
| 2 | 2026-07-22 | Two ruled corrections. (1) `season_sim` phase contradiction resolved: af-1 completion defined narrowly as **control-surface green**, not full behavioral-suite green; §6 and §7 revised; no exemption, no pragma disabling, no unmigrated constructor. (2) Dialect-incompatible option passthrough removed: §5.4 replaced with a canonical option policy (dialect-scoped, reject unknown/incompatible rather than forward); Test 5 rewritten. Test 3 wording refined to scope the guarantee to construction *through the helper*, with the bypass guard as the separate control. |

---

## 1. Purpose

FR-VAL10-af requires that every SQLite connection enforce foreign keys, that the
test suite run with enforcement active, and that no opt-outs exist.

At the recon baseline (`19aa0be`) there was no mechanism through which that
requirement could be delivered. This spec built one.

The requirement was never changed. Only the mechanism was corrected.

**Status: SATISFIED 2026-07-22.** `db/engine_factory.py` is the single governed
construction point (`0f4a04d`); the SQLite suite is green under enforcement
(`c961e2a`); PostgreSQL parity is green. See §11.

---

## 2. Frozen-Specification Implementation Variance

**Recorded explicitly, per ruling 2026-07-22.**

The frozen FR-VAL10-af requirement remains unchanged: every SQLite connection
must enforce foreign keys, the suite must run with enforcement active, and no
opt-outs are permitted.

Its frozen implementation premise was inaccurate at HEAD. The frozen text
directs adding `PRAGMA foreign_keys=ON` to an existing central connect hook in
`db/session.py`, "alongside the WAL/busy_timeout pragmas," and asserts that all
application and test connections pass through a single `get_engine()` factory.

Recon establishes that none of these exist:

| Frozen premise | HEAD reality |
|---|---|
| `db/session.py` module | Does not exist |
| `get_engine()` factory | Does not exist |
| Central connect hook | Does not exist |
| WAL pragma | Does not exist |
| busy_timeout pragma | Does not exist |
| Single factory for all connections | Eight direct `create_engine` sites |
| Test fixture layer | No `conftest.py`, no `pytest.ini`, 23 standalone scripts |

The frozen implementation sequence steps 1–2 ("add the pragma to the connect
hook; verify it returns `1`") are unexecutable as written — their target does
not exist.

**This is an implementation-premise correction, not a design reopening.** The
design freeze holds. FR-VAL10-af's obligations, tests, and no-opt-out standard
are carried forward unaltered.

---

## 3. Engine Constructor Classification (recon-grounded)

**There are no genuinely PostgreSQL-only constructors among the eight sites.**

The single canonical URL resolution point is `db/schema.py:29-35`:

```
_ENV_URL = os.environ.get("DATABASE_URL", "")
if _ENV_URL:
    DB_URL = _ENV_URL.replace("postgres://", "postgresql://", 1)
else:
    DB_URL = f"sqlite:///{DB_PATH}"
```

`DATABASE_URL` set → PostgreSQL. Unset → SQLite fallback. Every constructor
reading `DB_URL` or `DATABASE_URL` is therefore dialect-flexible.

| # | Site | Config at HEAD | Dialect | In scope |
|---|---|---|---|---|
| 1 | `db/schema.py:37` | `create_engine(DB_URL, echo=False)` | Flexible | Yes — primary |
| 2 | `betting/per_bet_lock.py:437` | `create_engine(DB, connect_args={"connect_timeout": 10})` | Flexible (CLI self-test) | Yes |
| 3 | `betting/per_bet_lock.py:458` | `create_engine("sqlite:///:memory:")` | SQLite, hardcoded | Yes |
| 4 | `engine/season_sim.py:130` | `create_engine("sqlite:///:memory:")` | SQLite, hardcoded | Yes — see §7 |
| 5 | `scripts/resolve_player_nfl_teams.py:160` | `DB_URL` + `connect_timeout` | Flexible | Yes |
| 6 | `seed_player_id_map.py:45` | `DB_URL` + `connect_timeout` | Flexible | Yes |
| 7 | `scripts/backfill_nfl_teams.py:220` | `DB_URL` + `connect_timeout` | Flexible | Yes |
| 8 | `test_yahoo_scoreboard.py:173` | `DB_URL` + `connect_timeout` | Flexible | Yes |

`connect_timeout` is a libpq/psycopg argument. Its presence signals author
intent, not a dialect guarantee. Sites 2 and 5–8 will construct SQLite whenever
`DATABASE_URL` is unset or points at a file — which is exactly what all 23 test
scripts do, forwarding a PostgreSQL argument to a SQLite DBAPI each time. It is
**not** assumed inert under SQLite; §5.5 governs its handling.

**Out of scope — genuinely PostgreSQL-only, correctly separate:**
`test_support_postgres.py` requires `TEST_DATABASE_URL`, hard-rejects any
non-PostgreSQL scheme (`:161`), refuses to resolve to the live database
(`:184-206`), and refuses a non-empty target (`:236`). Every guard raises
loudly; none skips silently. This harness already enforces foreign keys via the
production dialect and already protects against live-database use. It remains
separate, unmodified, and mandatory for parity testing.

---

## 4. Why Not a Global Listener

Rejected on 2026-07-22.

A global `event.listens_for(Engine, "connect")` listener fires only for engines
constructed after the registering module is imported. Sites 3, 4, and 5–8
include standalone scripts and CLI self-test blocks with no guaranteed import
path through any listener module. Coverage would be assumed, not proven.

FR-VAL10-af's standard is explicit, testable coverage with no opt-outs. An
import-order-dependent mechanism cannot satisfy it.

---

## 5. Required Implementation

### 5.1 Canonical engine module

**Structural contract (binding — Rev 4).** The af-1 control tests assert against
these exact symbols. They are not suggestions; a different choice breaks the
tests and must be recorded as a spec variance before it is made.

| Element | Required value |
|---|---|
| Canonical module | `db.engine_factory` |
| Public factory | `get_engine` |
| SQLite connect hook | `_sqlite_foreign_keys_on_connect` (module-owned, private) |
| Hook attachment target | the **individual SQLite engine's pool** `connect` event |
| PostgreSQL pools | the same callable **must not** be attached |

**Why the hook is a named private symbol.** `_sqlite_foreign_keys_on_connect`
exists solely to make registration *scope* exactly testable. The control test
uses `event.contains(engine.pool, "connect", _sqlite_foreign_keys_on_connect)`
to assert exact identity — the hook is present on SQLite pools and absent from
PostgreSQL pools.

Without a stable named symbol the test can only guess at listener identity from
`__name__` or `__doc__` substrings, which is not a proof. It **is not
application API**: no application code should import or call it, and it carries
no compatibility guarantee beyond the control tests.

**Attachment is per-engine-pool, not global.** `connect` is a pool event. A
listener attached with `event.listen(engine, "connect", hook)` lands on
`engine.pool.dispatch.connect`, not reliably on `engine.dispatch.connect` —
verified empirically 2026-07-22: on a registered hook,
`event.contains(engine, "connect", hook)` returns `False` while
`event.contains(engine.pool, "connect", hook)` returns `True`. Attach to the
pool and test against the pool.

The module owns:

1. **URL resolution and normalization.** Lift the `postgres://` →
   `postgresql://` rewrite from `db/schema.py:32`. Single point of truth.
2. **Dialect detection.** Derive dialect from the resolved URL, never from
   caller intent or the presence of a dialect-specific `connect_arg`.
3. **SQLite connection initialization.** On SQLite dialect only, a `connect`
   event hook issuing `PRAGMA foreign_keys=ON`.
4. **Canonical option policy (dialect-scoped).** See §5.5. Options are
   normalized by resolved dialect, never forwarded blindly.

The module must not import `db/schema.py`. `db/schema.py` imports it. This
prevents a circular import and keeps the governed point below the model layer.

### 5.2 Pragma verification

The hook applies the pragma. A separate assertion proves it took effect:
`PRAGMA foreign_keys` must return `1` on a live governed SQLite connection.

Applying a pragma and verifying its effect are different acts. The spec
requires both.

### 5.3 Constructor migration

Route all eight sites (§3) through the canonical module. Preserve each site's
intended, dialect-compatible behavior and options in accordance with §5.5.

### 5.4 Bypass guard

A repository-level test asserting no direct SQLite-capable `create_engine` call
exists outside the canonical module. The repository-level guard must use
AST-based detection covering aliases and both `sqlalchemy` and
`sqlalchemy.engine` namespaces. It must fail on a newly introduced ungoverned
constructor.

This is the control that keeps §5.3 true over time. Without it, migration is a
one-time cleanup rather than an enforced boundary.

### 5.5 Canonical option policy

**Options must be normalized by resolved dialect. Blind passthrough is
prohibited.**

A PostgreSQL DBAPI option cannot be assumed valid or inert under SQLite. Rev 1
described `connect_timeout` as "inert under SQLite" and used that to justify
preserving caller options unchanged. Inert-in-practice is an observation, not a
policy — it does not generalize to other options, other DBAPI drivers, or future
call sites.

The canonical helper must:

1. **Preserve dialect-neutral options.** `echo` and equivalents pass through for
   every dialect.
2. **Apply dialect-specific options only to their own dialect.** An option
   recognized for a dialect other than the resolved one is **excluded** — not an
   error, not forwarded. `connect_timeout` under a resolved SQLite dialect is
   this case: it is a recognized libpq/psycopg option, so it is dropped from the
   SQLite construction rather than raising.
3. **Apply SQLite-only options only to SQLite.** Including the
   `PRAGMA foreign_keys=ON` connect hook (§5.1.3) and any future SQLite
   `connect_args`.
4. **Reject unknown options and invalid combinations.** An option recognized for
   no dialect, or a combination the policy cannot resolve, **raises** at
   construction. It is not silently dropped and not forwarded.

**Excluded and rejected are distinct dispositions.** A recognized
other-dialect option is excluded silently, because the caller's intent is
legible and the correct handling is unambiguous. An unrecognized option is
rejected loudly, because the helper cannot know whether dropping it changes
behavior. Conflating the two would make `connect_timeout` on SQLite both
"excluded" and "rejected" — the ambiguity this section exists to remove.

Rejection over silent-drop for the unknown case is deliberate. An unrecognized
option quietly discarded produces behavior no one attributes to the helper; a
raise at construction names the problem at its source.

**This matters most for the five flexible constructors** (sites 2, 5, 6, 7, 8 in
§3). Each passes `connect_timeout` while resolving dialect from `DATABASE_URL`
at runtime. Each therefore forwards a PostgreSQL argument to a SQLite DBAPI
whenever that variable is unset — the exact condition under which all 23 test
scripts run.

---

## 5.6 af-1 Environment Prerequisite

**A PostgreSQL DBAPI driver supported by the project — currently `psycopg2` /
`psycopg2-binary` — must be importable.**

`create_engine()` on a `postgresql://` URL imports the DBAPI driver at
**construction** time, not connect time. Without the driver installed, the
deterministic dialect-scoping tests (T4 / T4a / T4b) raise `ModuleNotFoundError`
before asserting anything. The test reports that as an explicitly **unproven
gate** — never a pass, never an unrelated crash.

**No live PostgreSQL server is required for T4 / T4a / T4b.** Construction does
not connect. A dummy URL pointed at a nonexistent database is sufficient to
resolve the dialect and inspect pool registration.

**The live `TEST_DATABASE_URL` check (T4c) is optional for af-1** and does not
affect af-1's green status. It runs as an additional confirmation when an
instance happens to be available.

`TEST_DATABASE_URL` remains **mandatory and separate** for FR-VAL10-ac's
concurrency proof (ac spec §8.1, §11.2), where SQLite cannot demonstrate
`SELECT ... FOR UPDATE` serialization. The two requirements are unrelated: af-1
needs a *driver*, ac needs a *server*.

---

## 5.7 Implementation Variance — `scripts/resolve_player_nfl_teams.py`

**Recorded 2026-07-22, disposition A (accepted as implemented).**

> `scripts/resolve_player_nfl_teams.py` required a function-local repository-root
> bootstrap inside `main()` because, unlike the other migrated sites, it lacked an
> existing direct-execution import path to the `db` package. Placement inside
> `main()` preserves its module-import behavior while maintaining direct-script
> execution.

The spec authorizes routing the constructor (§5.3). It does not authorize adding
a path bootstrap, so this is a variance and is recorded as one.

Seven of the eight sites already placed repo root on `sys.path` — either directly
(`seed_player_id_map.py:39`, `scripts/backfill_nfl_teams.py:24`,
`test_yahoo_scoreboard.py:30`, `betting/per_bet_lock.py:26`) or via an existing
`db` import in the same block (`engine/season_sim.py:124`). Site 5 had neither.
Routing it to `db.engine_factory` without a bootstrap would have broken direct
execution, violating §5.3's requirement to preserve each site's intended
behavior.

**Placement inside `main()` is deliberate and must not be moved to module
scope.** The module is importable as `scripts.resolve_player_nfl_teams`, where the
importer already supplies the path; module-scope `sys.path` manipulation would
mutate the path for every importer as an import side effect. Function-local
placement confines the bootstrap to the direct-execution path that needs it.

Rejected alternatives: moving to module scope (cosmetic consistency at a real
behavioral cost); leaving the site unmigrated (creates the first af-1 opt-out and
fails T6).

---

## 6. Phasing

### af-1 — engine control surface

Bounded. Deliverables:

- canonical engine module with conditional SQLite connect hook;
- canonical option policy (§5.5) implemented;
- `PRAGMA foreign_keys` returns `1` on a governed SQLite connection;
- all eight constructors migrated;
- bypass guard test passing;
- PostgreSQL support harness left unmodified.

**Definition of af-1 completion — control-surface green.**

> af-1 completion requires all eight constructors to use the canonical helper
> and all af-1 control tests to pass. Functional regressions exposed by newly
> enabled FK enforcement, including simulation-fixture ordering failures, are
> af-2 triage items and do not invalidate successful delivery of the control
> surface.

af-1 proves the mechanism is in place and governs every constructor. It does not
claim the behavioral suite is green — that is af-2's deliverable. The two are
separate gates and must not be conflated: FR-VAL10-af is satisfied only when
**both** are met.

### af-2 — enforcement fallout

**Scope established by read-only discovery scan, 2026-07-22** (run against
`0f4a04d`, no edits). Triage is no longer unknown.

#### Inventory reconciliation

30 `test_*.py` files exist. The spec's original "23 standalone scripts" was the
pre-P1-L2 baseline: 30 − 6 (`test_p1l2_*_red.py`) − 1
(`test_af1_engine_control_surface_red.py`) = 23. No correction required; the
historical count stands.

#### Discovery result

25 scripts runnable under a temp-SQLite floor. **23 passed, 2 failed.** Every
test *body* and *setup* is already FK-clean — fixtures create parents before
children. The sole FK exposure is one teardown.

| Script | Bucket | Disposition |
|---|---|---|
| `test_pool_engine_conversion.py:754` | FK-enforcement fallout | **af-2 repair, authorized** |
| `test_beef_starters.py:386` | Environment / harness defect | Separate cleanup, authorized |

`test_pool_engine_conversion.py:754` — `db.query(Wallet).filter(...).delete()`
in teardown, blocked by a child row holding a `wallet_id` FK. All S1–S5b scenario
assertions passed first. Pre-af-1 this delete succeeded silently because SQLite
did not enforce. **Repair is teardown ordering only: delete dependent child
records before the referenced `Wallet`. Do not add cascade behavior merely to
make the test pass unless the production schema already requires it.**
Production `pool_engine.py` never deletes wallets — no production defect.

`test_beef_starters.py:386` — `UnicodeEncodeError` on a `→` under Windows cp1252,
before any DB operation. Not FK, not af-1. Passes under `PYTHONIOENCODING=utf-8`.
**Repair: replace the non-ASCII arrow with ASCII (`->`).** Preferred over
requiring a shell environment variable, so the test runs under the project's
normal Windows terminal without special configuration.

#### Explicit scope exclusion — external-provider integration tests

> External-provider integration smoke tests are outside af-2 because they do not
> exercise governed SQLite fixture creation, mutation, or teardown. Their health
> remains a separate integration gate.

Excluded: `test_fantasypros_historical.py`, `test_yahoo_projected_stats.py`,
`test_yahoo_scoreboard.py`.

These are **out of scope and unrun.** They are not "passed by inspection" — the
discovery scan did not execute them, and reading their source is not evidence
about their behavior. Running them would consume API quota and OAuth state
without producing enforcement signal.

#### af-2 completion criteria — SATISFIED 2026-07-22

af-2 is complete when **all** of the following hold:

1. ✅ `test_pool_engine_conversion.py` teardown repaired; all 25 safely runnable
   scripts pass under FK enforcement. — **Green 25/25, committed `c961e2a`.**
2. ✅ **Both PostgreSQL parity tests green against an empty, non-production
   `TEST_DATABASE_URL`:** `test_beef_settlement_escrow_close_pg.py` and
   `test_support_postgres.py`. — **Both green 2026-07-22.**
3. ✅ No blanket opt-outs, no FK disabling around failing tests. — **Confirmed;
   the single bounded exception at `db/migrate_full_beef.py` is recorded in §6.1
   and is migration-local, not a runtime or test opt-out.**

**PostgreSQL parity execution record (2026-07-22).**

Target: local Docker `postgres:16`, container `pg-fantasy-test`, host port 5433 →
container 5432, database `fantasy_test`.

The Railway-hosted instance provisioned earlier **could not** satisfy the harness
and was abandoned. `test_support_postgres.py` enforces two string checks before
any connection is opened:

| Guard | Line | Requirement |
|---|---|---|
| 3 | `:168` | database name must contain `_test` (`_REQUIRED_DBNAME_MARKER`) |
| 4 | `:177` | host must not match `("railway", "rlwy", "proxy.rlwy")` |

A Railway-hosted database fails Guard 4 categorically, at any database name. The
harness runs `CREATE`/`TRUNCATE`/`DROP`; it is designed never to do that against
a Railway-shaped target. **Guard 4 was not weakened, bypassed, or reinterpreted.**
Ruled 2026-07-22: relaxing a destructive-operation safety check to make a gate
pass is the inverse of the discipline this spec has held throughout — when a
control test failed during af-1 (T4a), the implementation was corrected, not the
test. Same principle applied here.

All six guards passed against the local container. Results:

- `test_support_postgres.py` — 41 tables created, `reset()` OK, `teardown()` OK,
  smoke check passed, exit 0.
- `test_beef_settlement_escrow_close_pg.py` — assertions S1–S4 passed under real
  PostgreSQL `FOR UPDATE` / `REPEATABLE READ` semantics, exit 0.

Proviso confirmed at execution: HEAD `c961e2a`, tracked tree clean, no
intervening changes to the SQLite suite.

**Container lifecycle:** `pg-fantasy-test` is left **running** to serve the
FR-VAL10-ac serialization proof (ac spec §8.1, §11.2). Do not stop, remove, or
prune it until ac is complete.

The FK-enforced suite prerequisite for ai–al is now satisfied. The ai–al legacy
migration remains not started and requires its own authorization and
implementation verification.

---

## 6.1 Recorded Exception — `db/migrate_full_beef.py`

Surfaced by the discovery scan's control-integrity search (Step E). Recorded as
a **bounded exception to the no-opt-out rule**, not as a clean result.

```
db/migrate_full_beef.py:16   PRAGMA foreign_keys=OFF
db/migrate_full_beef.py:42   PRAGMA foreign_keys=ON
```

This is the standard SQLite table-rebuild idiom. Disposition:

- permitted only for the bounded SQLite table-rebuild transaction;
- **not** a runtime or test-suite opt-out;
- must restore `foreign_keys=ON`;
- must not be copied into application or fixture code;
- should be re-verified after the migration completes.

Does not block af-2. But af-2's standard is "no blanket opt-outs," and this is an
opt-out — however narrowly scoped. Recording it as a known exception is more
honest than reporting no matches.

Other control-integrity results were clean: no ungoverned `create_engine` outside
`db/engine_factory.py`, no direct `sqlite3.connect` in project source, no other
pragma manipulation.

---

## 7. `engine/season_sim.py:130` — RULED

Site 4 is a simulation sandbox. It touches no money path and no VAL-10
invariant. FK enforcement there delivers no direct VAL-10 benefit.

**Ruling (2026-07-22): no exemption.** `season_sim` is migrated to the canonical
helper in af-1 like every other constructor. Its pragma is not disabled. Its
constructor is not left unmigrated.

**Repair timing.** If routing surfaces fixture-ordering breakage in the
simulation harness, that breakage is an af-2 triage item. Per the §6 completion
definition, it does not invalidate af-1's control-surface green.

The distinction is between **governance** and **behavior**. The constructor is
governed in af-1 unconditionally. Whatever the newly active enforcement then
exposes inside the simulation harness is a functional regression, repaired in
af-2 alongside the other 23 scripts. No opt-out is created, because the site is
routed and enforced either way — only the repair sits in the later phase.

---

## 8. Test-Fidelity Constraint (carried forward)

Recorded here because af owns suite fidelity. **Binding on the FR-VAL10-ab and
FR-VAL10-ad build, not on af.**

> Any test of Commissioner self-approval, authority serialization, disclosure,
> or approval races must seed a Commissioner who owns a team. A teamless
> Commissioner cannot exercise the self-approval branch and would produce a
> false green.

Recon basis: tests seed commissioners as `User(team_id=None,
role="commissioner", ...)` (`test_buyin_enforcement.py:121`,
`test_shortfall_reporting.py:120`). Production seeds a team-owning commissioner
(`auth/jwt_auth.py:200`, Team-1 owner). `db/schema.py:381` makes `team_id`
nullable, so both are legal.

The self-approval path that R6a, FR-VAL10-ab, and FR-VAL10-ad exist to govern is
therefore **structurally unreachable under the current test convention**. A
concurrency test written against a teamless commissioner would pass without
exercising self-approval at all — a false green on the design's Blocking
governance case.

---

## 9. Required Tests

| # | Test | Phase |
|---|---|---|
| 1 | `PRAGMA foreign_keys` returns `1` on a governed SQLite connection | af-1 |
| 2 | A dangling foreign-key reference is rejected at insert on SQLite | af-1 |
| 3 | The hook applies whenever an engine is constructed **through the canonical helper**, independent of whether `db.schema` was imported first | af-1 |
| 4 | PostgreSQL construction resolves the `postgresql` dialect (deterministic, no live server; requires the DBAPI driver per §5.6) | af-1 |
| 4a | `_sqlite_foreign_keys_on_connect` **is** registered on the SQLite engine's pool `connect` event (exact-symbol `event.contains`) | af-1 |
| 4b | The same callable is **not** registered on a PostgreSQL engine's pool | af-1 |
| 4c | Live PostgreSQL connection succeeds — **optional**, runs only with `TEST_DATABASE_URL`; does not affect af-1 green | af-1 |
| 5 | Dialect-compatible options survive routing; dialect-incompatible DBAPI options are excluded or rejected per the canonical option policy (§5.5) | af-1 |
| 5a | An option recognized for another dialect (`connect_timeout` under resolved SQLite) is **excluded** from construction without raising | af-1 |
| 5b | An option recognized for no dialect, or an unresolvable combination, **raises** at construction rather than being silently dropped or forwarded | af-1 |
| 6 | Bypass guard fails on a newly introduced ungoverned SQLite-capable constructor. **AST-based**, resolving import aliases and both namespaces: `create_engine`, `create_engine as _x`, `sqlalchemy.create_engine`, `sa.create_engine`, `from sqlalchemy.engine import create_engine`, `sqlalchemy.engine.create_engine`, `from sqlalchemy import engine as eng` | af-1 |
| 6b | Every project source file parses — an unparseable file is an **unproven** file, not a skipped one | af-1 |
| 7 | `postgres://` → `postgresql://` normalization preserved through the canonical point | af-1 |
| 8 | Full standalone suite passes with enforcement active | af-2 |
| 9 | No test disables FK enforcement or opts out | af-2 |
| 10 | PostgreSQL integration tests remain green (dialect parity) | af-2 |

Test 3 is the direct answer to the rejected global-listener approach (§4). It
proves the helper's guarantee holds without an import-order precondition. Note
the scope: no design can govern an arbitrary constructor that **bypasses** the
helper — that case is covered by the bypass guard (Test 6), which is a separate
control. Test 3 proves the helper works; Test 6 proves nothing escapes it.

Tests 4, 4a, and 4b guard against applying a SQLite pragma on the production
dialect. They test **exact symbol identity** against `engine.pool` per §5.1 —
not `engine.dispatch`, and not heuristic matching on `__name__`/`__doc__`.
Verified empirically 2026-07-22: a registered hook reports `False` on
`engine.dispatch` and `True` on `engine.pool`, so an engine-level assertion
would pass unconditionally on both dialects regardless of implementation.

4a and 4b are a matched pair. The negative alone cannot distinguish "correctly
scoped" from "never registered anywhere."

Test 6 is AST-based rather than regex-based because a regex on
`create_engine\s*\(` cannot see
`from sqlalchemy import create_engine as _create_engine` — the exact form at
`betting/per_bet_lock.py:456-458`. Since Test 6 is the persistent architectural
control, textual matching is insufficient.

Tests 5, 5a, and 5b enforce §5.5. They matter most for the five flexible
constructors, which resolve dialect at runtime from `DATABASE_URL`.

---

## 10. Sequencing Position

Per ruling 2026-07-22:

1. **ac** — `AuthoritySerializationLock` schema and final-Commissioner guard (independent, runs in parallel)
2. **af-1** — this spec, engine control surface and FK-on enforcement
3. **af-2** — full standalone-suite triage
4. **ai–al** — legacy migration and cap-consumption (design may run in parallel with af-2)
5. **OPR-10** — 24-value reset

---

## 11. Authorization State

Revision: **Rev 8**
Design: N/A — implementation spec under a frozen design
Money-path: **No** — no Opus math gate required
Recon: **Live anchors confirmed at HEAD `19aa0be`**
Ruled corrections: **All applied** — §6/§7 af-1 completion definition; §5.5 canonical option policy; Rev 3 editorial tightening; Rev 4 structural contract + environment prerequisite; Rev 5 §5.4 AST alignment; Rev 6 post-build path + variance record; Rev 7 af-2 discovery scope; Rev 8 parity execution + gate satisfaction
Control tests: **`test_af1_engine_control_surface_red.py` Rev 6** — 13/13 green
Open calls: **None**

**af-1: COMPLETE** — committed `0f4a04d`, control-surface green (2026-07-22).

**af-2: COMPLETE** (2026-07-22) — SQLite 25/25 at `c961e2a` (teardown repair
`test_pool_engine_conversion.py:754` plus harness cleanup
`test_beef_starters.py:386`), and PostgreSQL parity green against a local
Docker container. §6 completion criteria all satisfied.

af-1 build record:

Built against tree `8fdd410` (recon baseline `19aa0be` plus the BOM strip `ca3d729`
and the control package `8fdd410`; neither touched any of the eight constructors).
All 13 Rev 6 control tests pass. Smoke-verified: `db.schema.engine` builds through
the factory with `PRAGMA foreign_keys = 1` and the hook registered on its pool —
FK enforcement is live on the production engine path, not only on test engines.

Original authorization (2026-07-22), discipline as executed:

Build discipline (binding):

1. tests first;
2. one governed helper;
3. migrate constructors individually;
4. show the diff after each edit;
5. run af-1 control tests before declaring control-surface green;
6. **do not claim FR-VAL10-af satisfied until af-2 is also green.**

**af-2 PostgreSQL parity: GREEN 2026-07-22.** Both tests executed against a local
Docker `postgres:16` container (`pg-fantasy-test`, port 5433, database
`fantasy_test`). All six harness guards passed; Guard 4 unmodified. See §6.

**FR-VAL10-af: SATISFIED 2026-07-22.**

- af-1 — control surface, 13/13 control tests, `0f4a04d`
- af-2 SQLite — 25/25 runnable scripts, `c961e2a`
- af-2 PostgreSQL parity — both tests green

FK enforcement is live on the production engine path through a single governed
factory, protected by an AST-based bypass guard.

**Findings carried out of this gate, not closed by it:**

- **FR-AF-ENC-1** — Windows console encoding hazard. Non-cp1252 characters in
  executed test output crash standalone scripts under the normal Windows
  terminal. `test_beef_starters.py` held one executed `U+2192` (repaired) plus 14
  comment-only `U+2192` and 580 `U+2500`. Future edits moving such characters
  into `print()` output reproduce the failure. The other 24 scripts are unscanned.
  Disposition: later test-output hygiene sweep, not FR-VAL10-af.
- **FR-AC-ISO-1** — Investigate the pre-existing `beef_engine.py:877` warning
  that an isolation level was ignored because the connection was already
  established. Confirm the ac serialization tests establish isolation **before**
  connection checkout, and prove locking behavior through observed concurrent
  outcomes rather than configuration claims alone. Disposition: verify during ac,
  before its concurrency tests are trusted.
- **Environment parity** — local Python 3.13 versus Railway build 3.12 (cp312
  wheels). Register item, not af-owned.
