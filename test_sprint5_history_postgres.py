#!/usr/bin/env python3
"""
test_sprint5_history_postgres.py — provider_historical_rate on PostgreSQL.

WHY A SEPARATE SUITE. The offline suite certifies what the models DO, and that
is dialect-independent. Three things about this table are not:

    THE JSON DOCUMENT    `parameters` is JSON on SQLite and JSONB on PostgreSQL.
                         A derivation's counts and exclusions round-tripping in
                         one and not the other would be discovered by an
                         auditor, months later, asking why a rate cannot be
                         explained.

    THE APPEND-ONLY KEY  idempotency is a database constraint, not an `if`.
                         Two refresh runs racing is exactly what
                         `if not exists: insert` loses, and only the engine
                         settles it.

    THE CHECKS           `entity_type IN (...)` and the non-negative sample
                         guard are what stop a malformed derivation being
                         stored at all.

── FAILS, NEVER SKIPS ─────────────────────────────────────────────────────

Without a PostgreSQL target this exits non-zero and says so.

    TEST_DATABASE_URL=postgresql://.../fantasy_test python test_sprint5_history_postgres.py
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

TABLE = "provider_historical_rate"

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


print("=" * 78)
print("SPRINT 5 · PROVIDER_HISTORICAL_RATE ON POSTGRESQL")
print("=" * 78)

_ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if not _ADMIN_URL:
    print("  [FAIL] TEST_DATABASE_URL is not set")
    print("\nSPRINT 5 POSTGRESQL — cannot run without a PostgreSQL target.")
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

_CREATED: list[str] = []


def _new_db(tag: str) -> str:
    name = f"s5hist_{tag}_{uuid.uuid4().hex[:8]}_test"
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
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-c", body],
        capture_output=True, text=True, errors="replace", timeout=600,
        env=dict(os.environ, DATABASE_URL=url, PYTHONPATH=ROOT, PYTHONUTF8="1"),
        cwd=ROOT)


# ── 1 · the migration ────────────────────────────────────────────────────────

print("\n1 · the migration runs on PostgreSQL, twice, and touches nothing else")

_upgrade_url = _new_db("upgrade")
_run = _child(_upgrade_url, f"""
from sqlalchemy import inspect
from db.schema import Base, engine
Base.metadata.create_all(engine, tables=[t for n, t in Base.metadata.tables.items()
                                         if n != {TABLE!r}])
insp = inspect(engine)
print("BEFORE=" + str({TABLE!r} in insp.get_table_names()))
print("PROJ_BEFORE=" + str(sorted(c["name"] for c in insp.get_columns("projections"))))
print("COMP_BEFORE=" + str(sorted(c["name"] for c in insp.get_columns("provider_component_projection"))))
from migrations.add_provider_historical_rate import upgrade
print("FIRST=" + str(upgrade()))
print("SECOND=" + str(upgrade()))
insp = inspect(engine)
print("AFTER=" + str({TABLE!r} in insp.get_table_names()))
print("PROJ_AFTER=" + str(sorted(c["name"] for c in insp.get_columns("projections"))))
print("COMP_AFTER=" + str(sorted(c["name"] for c in insp.get_columns("provider_component_projection"))))
""")
_out = dict(line.split("=", 1) for line in _run.stdout.splitlines() if "=" in line)
_assert("a pre-Sprint-5 PostgreSQL database is built from the models",
        _out.get("BEFORE") == "False",
        (_run.stderr or "").strip().splitlines()[-1][:140] if _run.returncode
        else "")
_assert("the migration creates the table, its guard and its indexes",
        "created provider_historical_rate" in _out.get("FIRST", "")
        and "append-only guard" in _out.get("FIRST", ""))
_assert("applying it a second time is a no-op",
        "already exists" in _out.get("SECOND", ""))
_assert("`projections` is unchanged — the scalar path is untouched for a "
        "fourth sprint",
        _out.get("PROJ_BEFORE") == _out.get("PROJ_AFTER")
        and "projected_points" in _out.get("PROJ_AFTER", ""))
_assert("`provider_component_projection` is unchanged too",
        _out.get("COMP_BEFORE") == _out.get("COMP_AFTER"))

_migrated = create_engine(_upgrade_url)
_insp = inspect(_migrated)
_columns = {c["name"]: c for c in _insp.get_columns(TABLE)}
_assert("parameters is stored as JSONB",
        str(_columns["parameters"]["type"]).upper().startswith("JSONB"),
        str(_columns["parameters"]["type"]))
_assert("the append-only unique constraint exists",
        "uq_historical_rate_observation"
        in {u["name"] for u in _insp.get_unique_constraints(TABLE)})
_assert("both CHECK constraints exist",
        {"ck_historical_rate_entity", "ck_historical_rate_sample"}
        <= {ck["name"] for ck in _insp.get_check_constraints(TABLE)},
        str(sorted(ck["name"] for ck in _insp.get_check_constraints(TABLE))))
_assert("the resolver's lookup index exists",
        "ix_historical_rate_lookup"
        in {i["name"] for i in _insp.get_indexes(TABLE)})


# ── 2 · the engine enforces what the code assumes ────────────────────────────

print("\n2 · PostgreSQL itself enforces idempotency and the entity vocabulary")

_NOW = "2026-03-01T00:00:00+00:00"


def _insert(conn, *, fingerprint="fp-a", entity_type="PLAYER",
            sample_size=196, denominator=196.0, entity_key="bdl.p.113"):
    conn.execute(text(f"""
        INSERT INTO {TABLE}
          (provider, model_type, model_version, entity_type, entity_key,
           position, season_window, as_of, numerator, denominator, rate,
           sample_size, source_kind, parameters, fingerprint, generated_at,
           created_at)
        VALUES ('balldontlie', 'reception-model', 'reception-model-v1',
                :entity_type, :entity_key, 'WR', '2024-2025', :now, 142.0,
                :denominator, 0.7245, :sample_size, 'fantasy/weekly_stats',
                CAST('{{"receptions": 142, "targets": 196}}' AS JSONB),
                :fingerprint, :now, :now)
    """), {"entity_type": entity_type, "entity_key": entity_key,
           "denominator": denominator, "sample_size": sample_size,
           "fingerprint": fingerprint, "now": _NOW})


with _migrated.begin() as _c:
    _c.execute(text(f"DELETE FROM {TABLE}"))
    _insert(_c)
_assert("a first parameter is accepted", True)


def _refused(label: str, **kwargs) -> None:
    try:
        with _migrated.begin() as conn:
            _insert(conn, **kwargs)
    except DatabaseError as exc:
        _assert(label, True, type(exc.orig).__name__)
    else:
        _assert(label, False, "PostgreSQL ACCEPTED it")


_refused("the SAME derivation twice is refused by the engine", fingerprint="fp-a")
_refused("an entity_type outside the vocabulary is refused",
         fingerprint="fp-b", entity_type="GOAT")
_refused("a negative sample is refused", fingerprint="fp-c", sample_size=-1)
_refused("a negative denominator is refused", fingerprint="fp-d",
         denominator=-5.0)

with _migrated.begin() as _c:
    _insert(_c, fingerprint="fp-corrected")
_assert("a CORRECTION — same key, different derivation — lands beside it",
        True)
with _migrated.begin() as _c:
    _count = _c.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar()
_assert("  · so the table holds both, and neither was overwritten",
        _count == 2, f"{_count} rows")


# ── 3 · the round trip, through the production store ────────────────────────

print("\n3 · derivation, storage and resolution round-trip on PostgreSQL")

_roundtrip_url = _new_db("roundtrip")
_rt = _child(_roundtrip_url, """
import json
from datetime import datetime, timezone
from sqlalchemy.orm import sessionmaker
from db.schema import Base, ProviderHistoricalRate as R, engine
from scoring import history as H

Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()
CUTOFF = datetime(2026, 3, 1, tzinfo=timezone.utc)
PRICED = datetime(2026, 9, 10, tzinfo=timezone.utc)
BEFORE = datetime(2025, 11, 1, tzinfo=timezone.utc)

rate = H.HistoricalRate(
    provider="balldontlie", model_type=R.MODEL_RECEPTION,
    model_version=H.RECEPTION_MODEL_VERSION, entity_type=R.ENTITY_PLAYER,
    entity_key="bdl.p.113", position="WR", season_window="2024-2025",
    as_of=CUTOFF, numerator=142.0, denominator=196.0, sample_size=196,
    source_kind="fantasy/weekly_stats",
    parameters={"receptions": 142, "targets": 196, "excluded": 3})
first = H.persist_rates(db, [rate]); db.commit()
again = H.persist_rates(db, [rate]); db.commit()
row = db.query(R).one()
print("FIRST=" + str(first["persisted"]))
print("AGAIN=" + str(again["duplicate"]))
print("PARAMS=" + json.dumps(row.parameters, sort_keys=True))
print("RATE=" + repr(round(row.rate, 6)))
after = H.resolve_bundle(db, provider="balldontlie", as_of=PRICED,
                         player_key="bdl.p.113", position="WR")
before = H.resolve_bundle(db, provider="balldontlie", as_of=BEFORE,
                          player_key="bdl.p.113", position="WR")
print("AFTER_LEVEL=" + after.reception.level)
print("BEFORE_LEVEL=" + before.reception.level)
print("ROWS=" + str(db.query(R).count()))
""")
_res = dict(line.split("=", 1) for line in _rt.stdout.splitlines() if "=" in line)
_assert("a parameter persists through the production store",
        _res.get("FIRST") == "1",
        _res.get("FIRST", (_rt.stderr or "").strip().splitlines()[-1][:140]
                 if _rt.returncode else "?"))
_assert("  · re-deriving it is a no-op on PostgreSQL too",
        _res.get("AGAIN") == "1" and _res.get("ROWS") == "1")
_assert("  · the derivation document round-trips through JSONB exactly",
        _res.get("PARAMS") == '{"excluded": 3, "receptions": 142, "targets": 196}',
        _res.get("PARAMS", "?"))
_assert("  · and the rate reads back as measured",
        _res.get("RATE") == repr(round(142 / 196, 6)), _res.get("RATE", "?"))
_assert("the as-of cutoff holds on PostgreSQL: in force after, invisible before",
        _res.get("AFTER_LEVEL") == "MODELLED_PLAYER_HISTORY"
        and _res.get("BEFORE_LEVEL") == "MODEL_UNRESOLVED",
        f"{_res.get('AFTER_LEVEL')} / {_res.get('BEFORE_LEVEL')}")


# ── 4 · fresh and migrated converge ──────────────────────────────────────────

print("\n4 · a FRESH PostgreSQL database and an UPGRADED one agree")

_fresh_url = _new_db("fresh")
_fresh_run = _child(_fresh_url, """
from db.schema import Base, engine
Base.metadata.create_all(engine)
print("OK=True")
""")
_assert("a fresh database is built by create_all",
        "OK=True" in _fresh_run.stdout,
        (_fresh_run.stderr or "").strip().splitlines()[-1][:140]
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
    }


_a, _b = _describe(_fresh_insp), _describe(_insp)
for _facet in ("columns", "uniques", "indexes"):
    _assert(f"fresh and migrated agree on {_facet}", _a[_facet] == _b[_facet],
            "" if _a[_facet] == _b[_facet] else str(_a[_facet])[:150])

_drop_all()

print()
print("=" * 78)
if _failures:
    print(f"SPRINT 5 POSTGRESQL — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  · {_f}")
    print("=" * 78)
    sys.exit(1)
print(f"SPRINT 5 POSTGRESQL — provider_historical_rate certified on PostgreSQL "
      f"{_version.split(' ')[0]}:\nJSONB round-trips exactly, the engine enforces "
      f"the append-only key and the entity\nvocabulary, and the as-of cutoff "
      f"holds.")
print("=" * 78)
