#!/usr/bin/env python3
"""
Sprint 2B · provider_component_projection on PostgreSQL.

WHY THIS IS A SEPARATE SUITE, AND WHY IT CANNOT BE FOLDED INTO THE OFFLINE ONE.
The offline suite certifies BEHAVIOUR — what the store does, what the selector
returns, what a refusal is called — and behaviour is the same on every dialect.
Three things in this table are NOT behaviour and are not the same on every
dialect:

    THE JSON DOCUMENT       `components` is `JSON().with_variant(JSONB(),
                            "postgresql")`. SQLite keeps it as TEXT and hands
                            back whatever `json.loads` makes of it; PostgreSQL
                            keeps it as JSONB, which does not preserve key
                            order, normalises numbers, and rejects some values
                            SQLite accepts. A component payload that round-trips
                            in one and not the other would be discovered by a
                            scorer, in production, weeks later.

    THE UNIQUE KEY          the idempotency guarantee is a database constraint,
                            not an `if` in `persist_snapshot`. Two workers
                            ingesting the same week concurrently is exactly the
                            race that `if not exists: insert` loses, and only
                            the engine can settle it.

    THE CHECK               `provenance IN ('LIVE','FIXTURE_SYNTHETIC')` is what
                            stops replayed synthetic material from ever being
                            stored as live. SQLite enforces CHECKs too, but the
                            production engine is the one whose answer counts.

── FAILS, NEVER SKIPS ─────────────────────────────────────────────────────

Without a PostgreSQL target this exits non-zero and says so.

Every database it touches is created by it, carries the `_test` marker the other
harnesses require, and is dropped afterwards.

    TEST_DATABASE_URL=postgresql://.../fantasy_test python test_sprint2b_component_projections_postgres.py
"""

from __future__ import annotations

import json
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

TABLE = "provider_component_projection"

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
print("SPRINT 2B · PROVIDER_COMPONENT_PROJECTION ON POSTGRESQL")
print("=" * 78)

_ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if not _ADMIN_URL:
    print("  [FAIL] TEST_DATABASE_URL is not set")
    print("\nSPRINT 2B POSTGRESQL — cannot run without a PostgreSQL target. "
          "JSONB round-tripping and the engine-enforced idempotency key are the "
          "point of this suite, and SQLite settles neither.")
    sys.exit(2)

_url = make_url(_ADMIN_URL)
if not _url.drivername.startswith("postgresql"):
    print(f"  [FAIL] TEST_DATABASE_URL is not PostgreSQL ({_url.drivername})")
    sys.exit(2)
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
    name = f"s2b_{tag}_{uuid.uuid4().hex[:8]}_test"
    with _admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    _CREATED.append(name)
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
    """Run `body` in a child bound to `url` — db.schema.engine binds at import."""
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-c", body],
        capture_output=True, text=True, errors="replace", timeout=600,
        env=dict(os.environ, DATABASE_URL=url, PYTHONPATH=ROOT, PYTHONUTF8="1"),
        cwd=ROOT)


# ── 1 · the migration on a real pre-Sprint-2B PostgreSQL database ────────────

_section("1 · the migration runs on PostgreSQL, twice, and leaves `projections` "
         "alone")

_MIGRATE = f"""
from sqlalchemy import inspect
from db.schema import Base, engine
Base.metadata.create_all(engine, tables=[t for n, t in Base.metadata.tables.items()
                                         if n != {TABLE!r}])
insp = inspect(engine)
print("DIALECT=" + engine.dialect.name)
print("BEFORE=" + str({TABLE!r} in insp.get_table_names()))
print("PROJECTIONS_BEFORE=" + str(sorted(c["name"] for c in insp.get_columns("projections"))))
from migrations.add_provider_component_projection import upgrade
print("FIRST=" + str(upgrade()))
print("SECOND=" + str(upgrade()))
insp = inspect(engine)
print("AFTER=" + str({TABLE!r} in insp.get_table_names()))
print("PROJECTIONS_AFTER=" + str(sorted(c["name"] for c in insp.get_columns("projections"))))
"""

_upgrade_url = _new_db("upgrade")
_run = _child(_upgrade_url, _MIGRATE)
_out = dict(line.split("=", 1) for line in _run.stdout.splitlines() if "=" in line)
_assert("a pre-Sprint-2B PostgreSQL database is built from the models",
        _out.get("DIALECT") == "postgresql" and _out.get("BEFORE") == "False",
        (_run.stderr or "").strip().splitlines()[-1][:150] if _run.returncode
        else f"dialect {_out.get('DIALECT')}")
_assert("the migration creates the table and its append-only guard",
        "created provider_component_projection" in _out.get("FIRST", "")
        and "append-only guard" in _out.get("FIRST", ""),
        _out.get("FIRST", "?")[:100])
_assert("applying it a second time is a no-op, not an error",
        "already exists" in _out.get("SECOND", ""), _out.get("SECOND", "?")[:60])
_assert("`projections` is byte-for-byte the same table afterwards",
        _out.get("PROJECTIONS_BEFORE") == _out.get("PROJECTIONS_AFTER")
        and "projected_points" in _out.get("PROJECTIONS_AFTER", ""),
        _out.get("PROJECTIONS_AFTER", "?")[:80])

_migrated = create_engine(_upgrade_url)
_insp = inspect(_migrated)
_columns = {c["name"]: c for c in _insp.get_columns(TABLE)}
_assert("components is stored as JSONB, not as text",
        str(_columns["components"]["type"]).upper().startswith("JSONB"),
        str(_columns["components"]["type"]))
_assert("  · and so is components_present",
        str(_columns["components_present"]["type"]).upper().startswith("JSONB"),
        str(_columns["components_present"]["type"]))
_assert("the observation unique constraint exists on the migrated table",
        "uq_component_projection_observation"
        in {u["name"] for u in _insp.get_unique_constraints(TABLE)},
        str(sorted(u["name"] for u in _insp.get_unique_constraints(TABLE))))
_assert("the provenance CHECK exists",
        any("provenance" in (ck.get("sqltext") or "")
            for ck in _insp.get_check_constraints(TABLE)),
        str([ck["name"] for ck in _insp.get_check_constraints(TABLE)]))
_assert("the foreign key points at players.id",
        [(f["referred_table"], tuple(f["referred_columns"]))
         for f in _insp.get_foreign_keys(TABLE)] == [("players", ("id",))])
_assert("the selector's index exists on the migrated table",
        "ix_component_projection_lookup"
        in {i["name"] for i in _insp.get_indexes(TABLE)},
        str(sorted(i["name"] for i in _insp.get_indexes(TABLE))))


# ── 2 · the engine enforces what the code assumes ────────────────────────────

_section("2 · PostgreSQL itself enforces idempotency and provenance")

_NOW = "2025-12-24T20:00:00+00:00"


def _insert(conn, *, digest="dig-a", provenance="LIVE", player=9001,
            week=17, season=2025, provider="balldontlie",
            components='{"receiving_yards": 84.3}'):
    conn.execute(text(f"""
        INSERT INTO {TABLE}
          (provider, provider_player_key, player_id, season, week, source_kind,
           provenance, vocabulary_version, components, components_present,
           observation_digest, observed_at, captured_at, created_at)
        VALUES (:provider, 'bdl.p.113', :player, :season, :week,
                'fantasy/projections', :provenance, 'bdl.fantasy.v1',
                CAST(:components AS JSONB), CAST('["receiving_yards"]' AS JSONB),
                :digest, :now, :now, :now)
    """), {"provider": provider, "player": player, "season": season,
           "week": week, "provenance": provenance, "digest": digest,
           "components": components, "now": _NOW})


with _migrated.begin() as _c:
    _c.execute(text(f"DELETE FROM {TABLE}"))
    _c.execute(text("INSERT INTO players (id, name, position) "
                    "VALUES (9001, 'Amon-Ra St. Brown', 'WR'), "
                    "       (9002, 'Somebody Else', 'WR') "
                    "ON CONFLICT (id) DO NOTHING"))


def _refused(label: str, **kwargs) -> None:
    try:
        with _migrated.begin() as conn:
            _insert(conn, **kwargs)
    except DatabaseError as exc:
        _assert(label, True, type(exc.orig).__name__)
    else:
        _assert(label, False, "PostgreSQL ACCEPTED it")


with _migrated.begin() as _c:
    _insert(_c)
_assert("a first snapshot is accepted", True)

_refused("the SAME observation twice is refused by the engine, not by an "
         "if-statement", digest="dig-a")
_refused("a provenance outside {LIVE, FIXTURE_SYNTHETIC} is refused",
         digest="dig-b", provenance="INVENTED")
_refused("a player_id with no players row is refused by the foreign key",
         digest="dig-c", player=9999)

# The four axes that must NOT collide: a changed forecast, another provider,
# another season, another week.
for _label, _kwargs in (
        ("a CHANGED forecast is a new snapshot", {"digest": "dig-b"}),
        ("another provider is a new snapshot",
         {"digest": "dig-a", "provider": "some_other_provider"}),
        ("another season is a new snapshot",
         {"digest": "dig-a", "season": 2024}),
        ("another week is a new snapshot", {"digest": "dig-a", "week": 16})):
    with _migrated.begin() as _c:
        _insert(_c, **_kwargs)
    _assert(_label, True)

with _migrated.begin() as _c:
    _count = _c.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar()
_assert("history accumulated rather than overwriting: five rows for one subject",
        _count == 5, f"{_count} rows")


# ── 3 · the JSON document survives the round trip ────────────────────────────

_section("3 · a component payload round-trips through JSONB unchanged")

_PAYLOAD = {
    "passing_yards": 268.4, "passing_touchdowns": 1.8,
    "passing_interceptions": 0.7, "rushing_yards": 14.2,
    "passing_300_to_399_yard_games": 0.24, "field_goals_made_yards": 68.4,
    "dst_points_allowed": 21.3, "zero_valued_component": 0.0,
}

_ROUNDTRIP = """
import json
from datetime import datetime, timezone
from sqlalchemy.orm import sessionmaker
from db.schema import Base, Player, ProviderComponentProjection, engine
from providers.component_projections import (
    ComponentProjection, persist_snapshot, select_snapshot)
from providers.cross_identity import BALLDONTLIE, CanonicalSubject, \
    CrossProviderResolution, Outcome

Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()
player = Player(name="Amon-Ra St. Brown", position="WR", nfl_team="DET")
db.add(player); db.flush()

payload = json.loads(%(payload)s)
now = datetime(2025, 12, 24, 20, 0, tzinfo=timezone.utc)
resolution = CrossProviderResolution(
    outcome=Outcome.RESOLVED, provider=BALLDONTLIE,
    canonical=CanonicalSubject(player_id=player.id, name=player.name,
                               position="WR", nfl_team="DET"),
    provider_player_key="bdl.p.113", method="normalized_discovery")
projection = ComponentProjection(
    provider=BALLDONTLIE, provider_player_key="bdl.p.113", season=2025,
    week=17, components=payload, components_present=tuple(sorted(payload)),
    nfl_team="DET", position="WR", observed_at=now)
first = persist_snapshot(db, resolution=resolution, projection=projection,
                         captured_at=now, provenance="LIVE")
db.commit()
again = persist_snapshot(db, resolution=resolution, projection=projection,
                         captured_at=now, provenance="LIVE")
db.commit()
row = select_snapshot(db, provider=BALLDONTLIE, player_id=player.id,
                      season=2025, week=17)

# THE SELECTOR'S AS-OF, ON THE PRODUCTION ENGINE. Timestamps are where dialects
# diverge — PostgreSQL compares TIMESTAMPTZ, SQLite compares text — and "what
# was knowable on Thursday" is the question Sprint 3 will ask most often.
from datetime import timedelta
later = ComponentProjection(
    provider=BALLDONTLIE, provider_player_key="bdl.p.113", season=2025,
    week=17, components=dict(payload, passing_yards=999.0),
    components_present=tuple(sorted(payload)), nfl_team="DET", position="WR",
    observed_at=now + timedelta(days=1))
persist_snapshot(db, resolution=resolution, projection=later,
                 captured_at=now + timedelta(days=1), provenance="LIVE")
db.commit()
latest = select_snapshot(db, provider=BALLDONTLIE, player_id=player.id,
                         season=2025, week=17)
as_of = select_snapshot(db, provider=BALLDONTLIE, player_id=player.id,
                        season=2025, week=17, as_of=now + timedelta(hours=6))
before_any = select_snapshot(db, provider=BALLDONTLIE, player_id=player.id,
                             season=2025, week=17,
                             as_of=now - timedelta(days=7))
print("LATEST=" + str(latest.components["passing_yards"]))
print("ASOF=" + str(as_of.components["passing_yards"]))
print("BEFORE_ANY=" + str(before_any is None))
print("FIRST=" + first.outcome)
print("AGAIN=" + again.outcome)
print("MATCH=" + str(row.components == payload))
print("KEYS=" + str(sorted(row.components)))
print("ZERO=" + repr(row.components["zero_valued_component"]))
print("PRESENT=" + str(row.components_present == sorted(payload)))
print("ROWS=" + str(db.query(ProviderComponentProjection).count()))
print("SCALAR_UNTOUCHED=" + str(db.execute(
    __import__("sqlalchemy").text("SELECT count(*) FROM projections")).scalar()))
""" % {"payload": repr(json.dumps(_PAYLOAD))}

_roundtrip_url = _new_db("roundtrip")
_rt = _child(_roundtrip_url, _ROUNDTRIP)
_res = dict(line.split("=", 1) for line in _rt.stdout.splitlines() if "=" in line)
_assert("a snapshot persists against PostgreSQL through the production store",
        _res.get("FIRST") == "PERSISTED",
        _res.get("FIRST", (_rt.stderr or "").strip().splitlines()[-1][:150]
                 if _rt.returncode else "?"))
_assert("the component document comes back EXACTLY as it went in",
        _res.get("MATCH") == "True", _res.get("KEYS", "?")[:80])
_assert("  · including a genuinely zero-valued component",
        _res.get("ZERO") == "0.0", _res.get("ZERO", "?"))
_assert("  · and components_present survives as its own list",
        _res.get("PRESENT") == "True")
# TWO ROWS IS THE CORRECT ANSWER HERE, and it is the whole append-only story in
# one number: the identical re-persist wrote NOTHING, and the forecast that
# genuinely moved added exactly one row beside its predecessor.
_assert("re-persisting the same observation against PostgreSQL is a DUPLICATE",
        _res.get("AGAIN") == "DUPLICATE", _res.get("AGAIN", "?"))
_assert("  · so the table holds two rows: the original, and the moved forecast "
        "— never a third from the duplicate",
        _res.get("ROWS") == "2", f"{_res.get('ROWS')} row(s)")
_assert("and not one scalar projection row was written along the way",
        _res.get("SCALAR_UNTOUCHED") == "0", _res.get("SCALAR_UNTOUCHED", "?"))
_assert("the selector returns the LATEST snapshot on PostgreSQL",
        _res.get("LATEST") == "999.0", _res.get("LATEST", "?"))
_assert("  · and an as-of returns what was knowable THEN, not what came later",
        _res.get("ASOF") == "268.4", _res.get("ASOF", "?"))
_assert("  · and an as-of before every snapshot returns nothing at all",
        _res.get("BEFORE_ANY") == "True", _res.get("BEFORE_ANY", "?"))


# ── 4 · fresh and migrated converge ──────────────────────────────────────────

_section("4 · a FRESH PostgreSQL database and an UPGRADED one agree")

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
        (_fresh_run.stderr or "").strip().splitlines()[-1][:150]
        if _fresh_run.returncode else "")

_fresh_insp = inspect(create_engine(_fresh_url))


def _describe(insp) -> dict:
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
            else f"fresh={_a[_facet]!r} migrated={_b[_facet]!r}"[:190])


# ── report ──────────────────────────────────────────────────────────────────

_drop_all()

print()
print("=" * 78)
if _failures:
    print(f"SPRINT 2B POSTGRESQL — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  · {_f}")
    print("=" * 78)
    sys.exit(1)
print(f"SPRINT 2B POSTGRESQL — provider_component_projection certified on "
      f"PostgreSQL {_version.split(' ')[0]}: JSONB round-trips exactly, the "
      f"engine enforces\nthe append-only idempotency key and the provenance "
      f"CHECK, and `projections` is untouched.")
print("=" * 78)
