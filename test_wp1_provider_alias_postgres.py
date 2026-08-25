#!/usr/bin/env python3
"""
test_wp1_provider_alias_postgres.py — WP1 · the alias table on PostgreSQL.

WHY THIS SUITE EXISTS SEPARATELY FROM `test_wp1_cross_provider_identity.py`.

That suite is deliberately offline and deterministic: SQLite in memory, no
network, no credential, no clock. That is the right shape for certifying a
RESOLVER, whose behaviour is the same on every dialect. It is the wrong shape
for certifying a CONSTRAINT, because a constraint is not behaviour this
repository implements — it is behaviour a particular database engine implements,
and WP1's two constraints are not the same kind of object:

    uq_provider_player_alias_key            a plain UNIQUE, spanning retired
                                            rows, so a provider identifier can
                                            never be reused

    uq_provider_player_alias_active_player  a PARTIAL unique index, WHERE
                                            status = 'active', so a superseded
                                            mapping can be retired instead of
                                            deleted

SQLite accepting a partial unique index says nothing about PostgreSQL, which is
the engine production runs on. Worse, a partial index is exactly the kind of
object that can be silently DEGRADED rather than rejected: emit it as a full
unique and every insert still succeeds until the day a mapping is retired, at
which point the retirement — a recovery action, taken under pressure — fails.
So the invariants are asserted here against a real PostgreSQL server, by
INSERTING rows that must be refused and observing the refusal.

── WHAT IS PROVED, IN THE ORDER IT MATTERS ────────────────────────────────

    1  the migration applies to a real pre-WP1 PostgreSQL database, and applying
       it a second time changes nothing
    2  PostgreSQL refuses one provider subject claimed by two canonical players
    3  PostgreSQL refuses one canonical player holding two ACTIVE subjects
    4  a RETIRED mapping frees the player and still occupies its provider key —
       both halves, because either alone is the wrong table
    5  the status CHECK and the players foreign key are real, not documentation
    6  the migrated schema and `create_all` converge on the same table

── FAILS, NEVER SKIPS ─────────────────────────────────────────────────────

Without a PostgreSQL target this exits non-zero and says so. A certification
that can silently not-run is one that will eventually not-run, and the property
at stake here is the one that only PostgreSQL can settle.

Every database it touches is created by it, carries the `_test` marker the other
harnesses require, and is dropped afterwards.

    TEST_DATABASE_URL=postgresql://.../fantasy_test python test_wp1_provider_alias_postgres.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import create_engine, inspect, text                # noqa: E402
from sqlalchemy.engine import make_url                             # noqa: E402
from sqlalchemy.exc import DatabaseError                           # noqa: E402

TABLE = "provider_player_alias"

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


print("=" * 78)
print("WP1 · PROVIDER_PLAYER_ALIAS ON POSTGRESQL")
print("=" * 78)

_ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if not _ADMIN_URL:
    print("  [FAIL] TEST_DATABASE_URL is not set")
    print("\nWP1 POSTGRESQL — cannot run without a PostgreSQL target. The "
          "partial unique index is the whole point of this suite and SQLite "
          "cannot settle it.")
    sys.exit(2)

_url = make_url(_ADMIN_URL)
if not _url.drivername.startswith("postgresql"):
    print(f"  [FAIL] TEST_DATABASE_URL is not PostgreSQL ({_url.drivername})")
    sys.exit(2)
# THE SAME MARKER EVERY OTHER HARNESS REQUIRES.
if "_test" not in (_url.database or ""):
    print("  [FAIL] the admin database name must contain '_test'")
    sys.exit(2)
for _forbidden in ("railway", "rlwy"):
    if _forbidden in (_url.host or ""):
        print(f"  [FAIL] refusing a {_forbidden} host")
        sys.exit(2)

_admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
with _admin.connect() as _c:
    _version = _c.execute(text("show server_version")).scalar()
print(f"  server            PostgreSQL {_version}")
print(f"  host class        "
      f"{'localhost' if _url.host in ('127.0.0.1', 'localhost') else 'explicit test URL'}")

_CREATED: list[str] = []


def _new_db(tag: str) -> str:
    name = f"wp1alias_{tag}_{uuid.uuid4().hex[:8]}_test"
    with _admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    _CREATED.append(name)
    # Unmasked deliberately: this string is handed to a child process and to
    # create_engine, and is never printed. The report shows the host class only.
    return _url.set(database=name).render_as_string(hide_password=False)


def _drop_all() -> None:
    for name in _CREATED:
        try:
            with _admin.connect() as c:
                c.execute(text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"),
                    {"n": name})
                c.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        except Exception:                       # pragma: no cover - cleanup
            pass


def _child(url: str, body: str) -> subprocess.CompletedProcess:
    """Run `body` in a child bound to `url`.

    IN A SUBPROCESS BECAUSE `db.schema.engine` BINDS TO DATABASE_URL AT IMPORT.
    A same-process rebind would certify an engine no deployment ever uses.
    """
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-c", body],
        capture_output=True, text=True, errors="replace", timeout=600,
        env=dict(os.environ, DATABASE_URL=url, PYTHONPATH=ROOT, PYTHONUTF8="1"),
        cwd=ROOT)


# ── 1 · the migration applies to a real pre-WP1 PostgreSQL database ──────────

_section("1 · the migration runs on PostgreSQL, and runs twice")

_MIGRATE = f"""
from sqlalchemy import inspect
from db.schema import Base, engine
Base.metadata.create_all(engine, tables=[t for n, t in Base.metadata.tables.items()
                                         if n != {TABLE!r}])
print("DIALECT=" + engine.dialect.name)
print("BEFORE=" + str({TABLE!r} in inspect(engine).get_table_names()))
from migrations.add_provider_player_alias import upgrade
first = upgrade()
print("FIRST=" + str(first))
second = upgrade()
print("SECOND=" + str(second))
print("AFTER=" + str({TABLE!r} in inspect(engine).get_table_names()))
"""

_upgrade_url = _new_db("upgrade")
_run = _child(_upgrade_url, _MIGRATE)
_out = dict(line.split("=", 1) for line in _run.stdout.splitlines() if "=" in line)
_assert("a pre-WP1 PostgreSQL database is built from the models",
        _out.get("DIALECT") == "postgresql" and _out.get("BEFORE") == "False",
        (_run.stderr or "").strip().splitlines()[-1][:160]
        if _run.returncode else f"dialect {_out.get('DIALECT')}")
_assert("the migration creates the table, its partial unique and its index",
        "created provider_player_alias" in _out.get("FIRST", "")
        and "partial unique" in _out.get("FIRST", ""), _out.get("FIRST", "?")[:110])
_assert("applying it a second time is a no-op, not an error",
        "already exists" in _out.get("SECOND", ""), _out.get("SECOND", "?")[:80])
_assert("the table is present afterwards", _out.get("AFTER") == "True")

_migrated = create_engine(_upgrade_url)
_insp = inspect(_migrated)
_indexes = {i["name"]: i for i in _insp.get_indexes(TABLE)}
_uniques = {u["name"] for u in _insp.get_unique_constraints(TABLE)}

_assert("the provider-key side is a UNIQUE CONSTRAINT on (provider, key)",
        "uq_provider_player_alias_key" in _uniques, str(sorted(_uniques)))
_assert("the player side is a UNIQUE INDEX, not a constraint",
        _indexes.get("uq_provider_player_alias_active_player", {}).get("unique") is True,
        str(sorted(_indexes)))

# PostgreSQL is asked DIRECTLY whether the index carries a predicate. A degraded
# emission — the same index without its WHERE — passes every insert test above
# and only fails the day a mapping is retired.
with _migrated.connect() as _c:
    _predicate = _c.execute(text(
        "SELECT pg_get_expr(i.indpred, i.indrelid) FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE c.relname = 'uq_provider_player_alias_active_player'")).scalar()
_assert("and PostgreSQL records it as PARTIAL — the WHERE really landed",
        _predicate is not None and "active" in _predicate, str(_predicate))
_assert("the foreign key points at players.id — canonical identity is the "
        "existing row",
        [(f["referred_table"], tuple(f["referred_columns"]))
         for f in _insp.get_foreign_keys(TABLE)] == [("players", ("id",))])
_assert("the status CHECK is present on the migrated table",
        any("status" in (ck.get("sqltext") or "")
            for ck in _insp.get_check_constraints(TABLE)),
        str([ck["name"] for ck in _insp.get_check_constraints(TABLE)]))


# ── 2 · the invariants, enforced by the engine and not by the writer ─────────

_section("2 · PostgreSQL itself refuses every way the mapping could stop "
         "being a bijection")

_NOW = "2026-01-01T00:00:00+00:00"


def _insert(conn, key: str, player: int, status: str = "active") -> None:
    conn.execute(text(f"""
        INSERT INTO {TABLE}
          (provider, provider_player_key, player_id, status, method,
           manual_override, created_at, updated_at)
        VALUES ('balldontlie', :k, :p, :s, 'normalized_discovery', FALSE,
                :n, :n)
    """), {"k": key, "p": player, "s": status, "n": _NOW})


with _migrated.begin() as _c:
    _c.execute(text(f"DELETE FROM {TABLE}"))
    _c.execute(text("INSERT INTO players (id, name, position) "
                    "VALUES (9001, 'Alias Subject A', 'WR'), "
                    "       (9002, 'Alias Subject B', 'RB') "
                    "ON CONFLICT (id) DO NOTHING"))


def _refused(label: str, key: str, player: int, status: str = "active") -> None:
    """The row must be REFUSED BY THE DATABASE. An accepted row fails the gate."""
    try:
        with _migrated.begin() as conn:
            _insert(conn, key, player, status)
    except DatabaseError as exc:
        _assert(label, True, type(exc.orig).__name__)
    else:
        _assert(label, False, "PostgreSQL ACCEPTED it")


with _migrated.begin() as _c:
    _insert(_c, "bdl.p.1", 9001)
_assert("a first active mapping is accepted", True)

_refused("one provider subject claimed by two players is refused",
         "bdl.p.1", 9002)
_refused("one player holding two ACTIVE subjects is refused",
         "bdl.p.2", 9001)
_refused("a status outside {active, retired} is refused by the CHECK",
         "bdl.p.3", 9002, status="lapsed")
_refused("a player_id with no players row is refused by the foreign key",
         "bdl.p.4", 9999)

# RETIREMENT IS THE CASE THE PARTIAL INDEX EXISTS FOR. Both halves are asserted,
# because a full unique fails the first and a DELETE-based retirement fails the
# second — and the second is the id-reuse guard.
with _migrated.begin() as _c:
    _c.execute(text(f"UPDATE {TABLE} SET status = 'retired' "
                    f"WHERE provider_player_key = 'bdl.p.1'"))
    _insert(_c, "bdl.p.9", 9001)
_assert("a RETIRED mapping frees its player for a new active subject", True)
_refused("but the retired row still occupies its provider key — an identifier "
         "reissued by the provider cannot be picked up",
         "bdl.p.1", 9002)

with _migrated.begin() as _c:
    _rows = _c.execute(text(f"SELECT provider_player_key, status FROM {TABLE} "
                            f"ORDER BY id")).all()
_assert("the superseded mapping is still on disk, retired rather than deleted",
        [tuple(r) for r in _rows] == [("bdl.p.1", "retired"), ("bdl.p.9", "active")],
        str([tuple(r) for r in _rows]))


# ── 3 · fresh and upgraded databases converge ───────────────────────────────

_section("3 · a FRESH PostgreSQL database and an UPGRADED one agree")

_FRESH = """
from sqlalchemy import inspect
from db.schema import Base, engine
Base.metadata.create_all(engine)
print("OK=True")
"""

_fresh_url = _new_db("fresh")
_fresh_run = _child(_fresh_url, _FRESH)
_assert("a fresh database is built by create_all, the way api/main.py builds one",
        "OK=True" in _fresh_run.stdout,
        (_fresh_run.stderr or "").strip().splitlines()[-1][:160]
        if _fresh_run.returncode else "")

_fresh_engine = create_engine(_fresh_url)
_fresh_insp = inspect(_fresh_engine)


def _describe(insp) -> dict:
    """The structural facts the two paths must agree on.

    NOT A BYTE COMPARISON — index and constraint NAMES are compared, because
    both paths name them explicitly, but nothing here depends on column order.
    """
    return {
        "columns": {c["name"]: (str(c["type"]).split("(")[0], c["nullable"])
                    for c in insp.get_columns(TABLE)},
        "uniques": {u["name"]: tuple(u["column_names"])
                    for u in insp.get_unique_constraints(TABLE)},
        "indexes": {i["name"]: (tuple(i["column_names"]), i.get("unique"))
                    for i in insp.get_indexes(TABLE)},
        "foreign_keys": {(f["referred_table"], tuple(f["referred_columns"]))
                         for f in insp.get_foreign_keys(TABLE)},
    }


_a, _b = _describe(_fresh_insp), _describe(_insp)
for _facet in ("columns", "uniques", "indexes", "foreign_keys"):
    _assert(f"fresh and migrated agree on {_facet}", _a[_facet] == _b[_facet],
            "" if _a[_facet] == _b[_facet]
            else f"fresh={_a[_facet]!r} migrated={_b[_facet]!r}"[:200])

with _fresh_engine.connect() as _c:
    _fresh_predicate = _c.execute(text(
        "SELECT pg_get_expr(i.indpred, i.indrelid) FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE c.relname = 'uq_provider_player_alias_active_player'")).scalar()
_assert("and the FRESH database's index is partial too — the model's "
        "postgresql_where reached the server",
        _fresh_predicate is not None and "active" in _fresh_predicate,
        str(_fresh_predicate))


# ── 4 · the resolver's own writes land on PostgreSQL ────────────────────────

_section("4 · the resolver writes through this table on PostgreSQL, not only "
         "on SQLite")

_RESOLVE = """
from db.schema import Base, Player, ProviderPlayerAlias, engine
from sqlalchemy.orm import sessionmaker
from providers.balldontlie_identity import directory_from_fixture
from providers.cross_identity import resolve_player

Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()
db.query(ProviderPlayerAlias).delete()
db.commit()
player = Player(name="Amon-Ra St. Brown", position="WR", nfl_team="DET")
db.add(player)
db.flush()

directory = directory_from_fixture()
first = resolve_player(db, player, directory)
db.commit()
print("FIRST=" + str(first.outcome) + "|" + str(first.provider_player_key)
      + "|" + str(first.method))

# The persisted mapping must win on the second call, with the name changed out
# from under it — the trade/rename case, on the production engine.
player.name = "Somebody Else Entirely"
player.nfl_team = "SEA"
db.flush()
second = resolve_player(db, player, directory)
db.commit()
rows = db.query(ProviderPlayerAlias).all()
print("SECOND=" + str(second.outcome) + "|" + str(second.provider_player_key)
      + "|" + str(second.method))
print("ROWS=" + str(len(rows)))

# WHAT MAKES THE LINE ABOVE EVIDENCE. Discovery run on the SAME renamed row
# finds nothing at all, so a RESOLVED second call cannot have come from it.
from providers.cross_identity import canonical_subject_from_player, discover
print("DISCOVERY=" + str(discover(canonical_subject_from_player(player),
                                  directory).outcome))
"""

_resolver_url = _new_db("resolver")
_resolver_run = _child(_resolver_url, _RESOLVE)
_res = dict(line.split("=", 1) for line in _resolver_run.stdout.splitlines()
            if "=" in line)
_assert("a first resolution discovers and persists against PostgreSQL",
        _res.get("FIRST", "").startswith("RESOLVED|bdl.p.113|"),
        _res.get("FIRST", (_resolver_run.stderr or "").strip()
                 .splitlines()[-1][:160] if _resolver_run.returncode else "?"))
_assert("a renamed, traded player still resolves to the SAME subject",
        _res.get("SECOND", "").startswith("RESOLVED|bdl.p.113|"),
        _res.get("SECOND", "?"))
_assert("  · and discovery on that same renamed row finds NOTHING — so the "
        "mapping, not the name, is what resolved it",
        _res.get("DISCOVERY") == "UNRESOLVED", _res.get("DISCOVERY", "?"))
_assert("exactly one alias row exists after both calls", _res.get("ROWS") == "1",
        _res.get("ROWS", "?"))


# ── report ──────────────────────────────────────────────────────────────────

_drop_all()

print()
print("=" * 78)
if _failures:
    print(f"WP1 POSTGRESQL — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  · {_f}")
    print("=" * 78)
    sys.exit(1)
print("WP1 POSTGRESQL — provider_player_alias certified on PostgreSQL "
      f"{_version.split(' ')[0]}: the migration applies and re-applies, the "
      "partial unique is partial, and every bijection violation is refused by "
      "the engine.")
print("=" * 78)
