"""
test_spec2_2b_migration_pg.py — SPEC 2 · Package 2B **Group 1**: the foundation
migration (PostgreSQL).

    M1  clean-install / applicability
    M2  the precondition census runs BEFORE any mutation
    M3  a nonzero legacy beef census fails closed
    M4  protocol_events created correctly
    M5  ledger_posting_batches created correctly
    M6  challenge_funding_legs created correctly
    M7  ledger_entries.batch_id added correctly
    M8  required indexes and unique constraints exact
    M9  event uniqueness exists ONLY at the authoritative tier
    M10 a repeat migration is idempotent
    M11 unexpected schema state fails closed
    M12 a failed late DDL rolls back the ENTIRE mutation phase
    M13 the same database migrates once the blocking condition is removed

THE METHOD. The harness builds the full schema from the models — that is the
clean-install truth, captured first as the reference. Each scenario then DEVOLVES
to a pre-Group-1 shape, runs the migration, and asserts the result matches the
captured reference object for object. A migration that produced a different
uniqueness contract, a differently-named constraint, or a batch column of the
wrong shape would be caught, because the comparison is against what the models
actually produce rather than against a second copy of the migration's intentions.

Devolution is TEST SETUP, not a migration operation: the migration under test
drops nothing at all.

M12 IS THE ATOMICITY TEST and uses a real name collision rather than
instrumentation — an index name is unique per schema in PostgreSQL, but
inspect().get_indexes('ledger_entries') reports only indexes ON that table, so a
decoy elsewhere passes every precondition and makes the LAST statement fail.

Requires TEST_DATABASE_URL pointing at a dedicated, empty, _test-named,
non-Railway PostgreSQL database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] Package 2B Group 1 migration suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []
_seq = {"n": 0}


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _uniq(prefix: str) -> str:
    _seq["n"] += 1
    return f"{prefix}{_seq['n']}"


def main(tdb) -> None:
    from datetime import datetime
    from pathlib import Path

    from sqlalchemy import inspect, text

    from db.schema import Base
    from ledger.ledger import create_ledger_table

    import db.migrations.migrate_spec2_challenge_escrow as mig
    from db.migrations.migrate_spec2_challenge_escrow import (
        run_migration, LegacyBeefCensusError, UnexpectedSchemaError,
        T_PROTOCOL_EVENT, T_POSTING_BATCH, T_FUNDING_LEG, T_LEDGER,
        UQ_EVENT_ID, UQ_BATCH_POSTING, UQ_LEG_SEQUENCE,
        CK_LEG_KIND, CK_LEG_LINKAGE, CK_LEG_AMOUNT_SIGN,
        COL_LEDGER_BATCH_ID, IX_LEDGER_BATCH_ID, LEG_CHECKS,
    )

    engine = tdb.engine

    # ── inspection helpers ────────────────────────────────────────────────
    def _tables() -> set:
        return set(inspect(engine).get_table_names())

    def _cols(t: str) -> set:
        return {c["name"] for c in inspect(engine).get_columns(t)}

    def _col(t: str, name: str) -> dict:
        return next(c for c in inspect(engine).get_columns(t) if c["name"] == name)

    def _uniques(t: str) -> set:
        return {u["name"] for u in inspect(engine).get_unique_constraints(t)}

    def _checks(t: str) -> set:
        return {c["name"] for c in inspect(engine).get_check_constraints(t)}

    def _indexes(t: str) -> set:
        return {i["name"] for i in inspect(engine).get_indexes(t)}

    def _fks(t: str) -> set:
        return {f["name"] for f in inspect(engine).get_foreign_keys(t)}

    def _exec(*statements: str) -> None:
        with engine.begin() as c:
            for s in statements:
                c.execute(text(s))

    def _rebuild() -> None:
        """Back to clean-install state. tdb.reset() cannot be used here: it
        TRUNCATEs the full model table list, and a devolved schema no longer has
        some of those tables."""
        tdb.teardown()
        Base.metadata.create_all(engine)
        create_ledger_table()

    def _devolve() -> None:
        """Turn the model-built schema into a pre-Group-1 shape. TEST SETUP
        ONLY — the migration under test drops nothing."""
        _exec(
            f"DROP TABLE IF EXISTS {T_FUNDING_LEG}",
            f"DROP TABLE IF EXISTS {T_POSTING_BATCH}",
            f"DROP TABLE IF EXISTS {T_PROTOCOL_EVENT}",
            f"DROP INDEX IF EXISTS {IX_LEDGER_BATCH_ID}",
            f"ALTER TABLE {T_LEDGER} DROP COLUMN IF EXISTS {COL_LEDGER_BATCH_ID}",
        )

    def _seed_legacy_beef() -> None:
        """One legacy challenge — the condition Spec 2 §14 halts on."""
        with engine.begin() as c:
            lg = c.execute(text(
                "INSERT INTO leagues (season, name, projection_source, "
                "buyin_enforcement_active) VALUES (2025, :n, 'fantasypros', false) "
                "RETURNING id"), {"n": _uniq("mig")}).scalar()
            t1 = c.execute(text(
                "INSERT INTO teams (league_id, team_name, owner, email) "
                "VALUES (:l, :n, :n, :e) RETURNING id"),
                {"l": lg, "n": _uniq("T"), "e": f"{_uniq('e')}@gg.test"}).scalar()
            t2 = c.execute(text(
                "INSERT INTO teams (league_id, team_name, owner, email) "
                "VALUES (:l, :n, :n, :e) RETURNING id"),
                {"l": lg, "n": _uniq("T"), "e": f"{_uniq('e')}@gg.test"}).scalar()
            # Every NOT NULL column whose default is CLIENT-side must be named
            # explicitly — a raw INSERT gets no help from SQLAlchemy defaults.
            c.execute(text(
                "INSERT INTO beef_challenges (challenger_team_id, challenged_team_id, "
                "week, bet_type, amount, challenger_odds, challenged_odds, "
                "challenger_moneyline, challenged_moneyline, status, expires_at, "
                "staleness_warning) "
                "VALUES (:a, :b, 1, 'straight', 10.0, 1.9, 1.9, -110, -110, "
                "'pending', :x, 0)"),
                {"a": t1, "b": t2, "x": datetime(2026, 9, 13, 12, 0, 0)})

    # ══════════════════════════════════════════════════════════════════════
    # Reference — the clean-install truth
    # ══════════════════════════════════════════════════════════════════════
    print("\nM-ref  capture the clean-install truth from the models")
    _rebuild()
    REF = {
        "tables":       _tables(),
        "pe_uniques":   _uniques(T_PROTOCOL_EVENT),
        "pe_indexes":   _indexes(T_PROTOCOL_EVENT),
        "pe_cols":      _cols(T_PROTOCOL_EVENT),
        "pb_uniques":   _uniques(T_POSTING_BATCH),
        "pb_cols":      _cols(T_POSTING_BATCH),
        "pb_fks":       _fks(T_POSTING_BATCH),
        "leg_uniques":  _uniques(T_FUNDING_LEG),
        "leg_checks":   _checks(T_FUNDING_LEG),
        "leg_cols":     _cols(T_FUNDING_LEG),
        "leg_fks":      _fks(T_FUNDING_LEG),
        "leg_indexes":  _indexes(T_FUNDING_LEG),
        "ledger_cols":  _cols(T_LEDGER),
        "ledger_idx":   _indexes(T_LEDGER),
        "batch_col":    _col(T_LEDGER, COL_LEDGER_BATCH_ID),
    }
    _assert("M-ref the model build carries all three new tables",
            {T_PROTOCOL_EVENT, T_POSTING_BATCH, T_FUNDING_LEG} <= REF["tables"])
    _assert("M-ref and the ledger batch column", COL_LEDGER_BATCH_ID in REF["ledger_cols"])
    _assert("M-ref clean-install batch_id is nullable integer",
            REF["batch_col"]["nullable"] is True
            and "INT" in str(REF["batch_col"]["type"]).upper(),
            str(REF["batch_col"]["type"]))

    # ══════════════════════════════════════════════════════════════════════
    # M1 / M2 / M4-M8 — the migration brings a pre-Group-1 schema up
    # ══════════════════════════════════════════════════════════════════════
    print("\nM1-M8  the migration upgrades a pre-Group-1 schema to the models")
    _rebuild(); _devolve()
    _assert("M1 precondition: the schema is genuinely pre-Group-1",
            T_PROTOCOL_EVENT not in _tables()
            and COL_LEDGER_BATCH_ID not in _cols(T_LEDGER),
            str(sorted(_tables() & {T_PROTOCOL_EVENT, T_POSTING_BATCH, T_FUNDING_LEG})))

    report = run_migration()

    _assert("M1 the report says it applied", report["applicable"] is True)
    _assert("M2 the census ran and is reported",
            report["census"] is not None and report["census"]["total"] == 0,
            str(report["census"]))
    _assert("M1 all three tables were created",
            set(report["tables_created"])
            == {T_PROTOCOL_EVENT, T_POSTING_BATCH, T_FUNDING_LEG},
            str(report["tables_created"]))
    _assert("M7 the ledger batch column was added",
            report["columns_added"] == [f"{T_LEDGER}.{COL_LEDGER_BATCH_ID}"],
            str(report["columns_added"]))
    _assert("M7 and its index", report["indexes_created"] == [IX_LEDGER_BATCH_ID],
            str(report["indexes_created"]))

    _assert("M4 protocol_events matches the clean install exactly",
            _cols(T_PROTOCOL_EVENT) == REF["pe_cols"]
            and _uniques(T_PROTOCOL_EVENT) == REF["pe_uniques"]
            and _indexes(T_PROTOCOL_EVENT) == REF["pe_indexes"],
            str(REF["pe_cols"].symmetric_difference(_cols(T_PROTOCOL_EVENT))))
    _assert("M5 ledger_posting_batches matches the clean install exactly",
            _cols(T_POSTING_BATCH) == REF["pb_cols"]
            and _uniques(T_POSTING_BATCH) == REF["pb_uniques"]
            and _fks(T_POSTING_BATCH) == REF["pb_fks"],
            str(REF["pb_cols"].symmetric_difference(_cols(T_POSTING_BATCH))))
    _assert("M6 challenge_funding_legs matches the clean install exactly",
            _cols(T_FUNDING_LEG) == REF["leg_cols"]
            and _uniques(T_FUNDING_LEG) == REF["leg_uniques"]
            and _checks(T_FUNDING_LEG) == REF["leg_checks"]
            and _fks(T_FUNDING_LEG) == REF["leg_fks"]
            and _indexes(T_FUNDING_LEG) == REF["leg_indexes"],
            str(REF["leg_cols"].symmetric_difference(_cols(T_FUNDING_LEG))))
    _assert("M7 the migrated batch column matches the clean install",
            _col(T_LEDGER, COL_LEDGER_BATCH_ID)["nullable"]
            == REF["batch_col"]["nullable"]
            and str(_col(T_LEDGER, COL_LEDGER_BATCH_ID)["type"])
            == str(REF["batch_col"]["type"]),
            str(_col(T_LEDGER, COL_LEDGER_BATCH_ID)["type"]))
    _assert("M7 ledger_entries columns and indexes match the clean install",
            _cols(T_LEDGER) == REF["ledger_cols"]
            and _indexes(T_LEDGER) == REF["ledger_idx"],
            str(REF["ledger_cols"].symmetric_difference(_cols(T_LEDGER))))

    _assert("M8 the exact authority constraints exist",
            UQ_EVENT_ID in _uniques(T_PROTOCOL_EVENT)
            and UQ_BATCH_POSTING in _uniques(T_POSTING_BATCH)
            and UQ_LEG_SEQUENCE in _uniques(T_FUNDING_LEG))
    _assert("M8 all three funding-leg CHECKs exist by name",
            set(LEG_CHECKS) <= _checks(T_FUNDING_LEG),
            str(sorted(_checks(T_FUNDING_LEG))))
    _assert("M8 the funding leg's self-referencing reversal FK exists",
            any("reverses" in f for f in _fks(T_FUNDING_LEG)),
            str(sorted(_fks(T_FUNDING_LEG))))

    # ══════════════════════════════════════════════════════════════════════
    # M9 — uniqueness only at the authoritative tier
    # ══════════════════════════════════════════════════════════════════════
    print("\nM9   event uniqueness exists ONLY at the authoritative tier "
          "(Ruling 1)")
    _assert("M9 ledger_entries has NO unique constraint at all",
            _uniques(T_LEDGER) == set(), str(_uniques(T_LEDGER)))
    _assert("M9 no ledger_entries index is unique",
            not any(i.get("unique")
                    for i in inspect(engine).get_indexes(T_LEDGER)),
            str([(i["name"], i.get("unique"))
                 for i in inspect(engine).get_indexes(T_LEDGER)]))
    _assert("M9 ledger_entries has no event_id column to be an authority on",
            "event_id" not in _cols(T_LEDGER), str(sorted(_cols(T_LEDGER))))
    _assert("M9 the ONLY event_id uniqueness in the database is on "
            "protocol_events",
            UQ_EVENT_ID in _uniques(T_PROTOCOL_EVENT)
            and "event_id" not in _cols(T_POSTING_BATCH))

    # ══════════════════════════════════════════════════════════════════════
    # M10 — idempotency
    # ══════════════════════════════════════════════════════════════════════
    print("\nM10  a second run changes nothing")
    before = (_tables(), _cols(T_LEDGER), _indexes(T_LEDGER),
              _uniques(T_FUNDING_LEG), _checks(T_FUNDING_LEG))
    report2 = run_migration()
    _assert("M10 the second run created no table, column or index",
            report2["tables_created"] == [] and report2["columns_added"] == []
            and report2["indexes_created"] == [], str(report2))
    _assert("M10 the schema shape is identical",
            before == (_tables(), _cols(T_LEDGER), _indexes(T_LEDGER),
                       _uniques(T_FUNDING_LEG), _checks(T_FUNDING_LEG)))

    # ══════════════════════════════════════════════════════════════════════
    # M3 — the legacy beef census fails closed
    # ══════════════════════════════════════════════════════════════════════
    print("\nM3   a nonzero legacy beef census HALTS before any mutation "
          "(§14 / Spec 1 §11)")
    _rebuild(); _devolve()
    _seed_legacy_beef()
    pre_tables = _tables()
    pre_cols   = _cols(T_LEDGER)

    census_exc = None
    try:
        run_migration()
    except Exception as exc:                      # noqa: BLE001 — recording
        census_exc = exc

    _assert("M3 raises LegacyBeefCensusError (by TYPE)",
            isinstance(census_exc, LegacyBeefCensusError),
            f"got {type(census_exc).__name__}")
    _assert("M3 the refusal states the counts an operator must act on",
            census_exc is not None and "1 challenge(s)" in str(census_exc),
            str(census_exc)[:110])
    _assert("M2/M3 NO table was created — the census precedes all DDL",
            _tables() == pre_tables,
            str(pre_tables.symmetric_difference(_tables())))
    _assert("M3 NO column was added", _cols(T_LEDGER) == pre_cols)
    with engine.connect() as c:
        still = c.execute(text("SELECT COUNT(*) FROM beef_challenges")).scalar()
    _assert("M3 the legacy row is UNTOUCHED — nothing dropped or rewritten",
            still == 1, str(still))

    # M13 — remove the blocking condition and the same database migrates.
    _exec("DELETE FROM beef_challenges")
    rep13 = run_migration()
    _assert("M13 with the legacy rows gone the SAME database migrates cleanly",
            rep13["applicable"] is True
            and set(rep13["tables_created"])
            == {T_PROTOCOL_EVENT, T_POSTING_BATCH, T_FUNDING_LEG},
            str(rep13["tables_created"]))
    _assert("M13 and reaches the clean-install end state",
            _cols(T_LEDGER) == REF["ledger_cols"] and _tables() == REF["tables"])

    # ══════════════════════════════════════════════════════════════════════
    # M11 — unexpected schema fails closed
    # ══════════════════════════════════════════════════════════════════════
    print("\nM11  an unrecognisable existing schema fails closed")

    # (i) protocol_events present WITHOUT its idempotency authority.
    _rebuild(); _devolve()
    _exec("CREATE TABLE protocol_events (id SERIAL PRIMARY KEY, "
          "event_id UUID NOT NULL, event_type VARCHAR NOT NULL)")
    pre_i = _tables()
    exc_i = None
    try:
        run_migration()
    except Exception as exc:                      # noqa: BLE001 — recording
        exc_i = exc
    _assert("M11 (no UNIQUE(event_id)) raises UnexpectedSchemaError",
            isinstance(exc_i, UnexpectedSchemaError), f"got {type(exc_i).__name__}")
    _assert("M11 (no UNIQUE) the refusal names the idempotency authority",
            exc_i is not None and UQ_EVENT_ID in str(exc_i), str(exc_i)[:110])
    _assert("M11 (no UNIQUE) nothing else was created",
            _tables() == pre_i, str(pre_i.symmetric_difference(_tables())))

    # (ii) a batch_id column of the wrong type.
    _rebuild(); _devolve()
    _exec(f"ALTER TABLE {T_LEDGER} ADD COLUMN {COL_LEDGER_BATCH_ID} VARCHAR")
    pre_ii = _tables()
    exc_ii = None
    try:
        run_migration()
    except Exception as exc:                      # noqa: BLE001 — recording
        exc_ii = exc
    _assert("M11 (wrong batch_id type) raises UnexpectedSchemaError",
            isinstance(exc_ii, UnexpectedSchemaError),
            f"got {type(exc_ii).__name__}")
    _assert("M11 (wrong type) no table was created",
            _tables() == pre_ii, str(pre_ii.symmetric_difference(_tables())))

    # (iii) a funding-leg table missing its structural guards.
    _rebuild(); _devolve()
    _exec(f"CREATE TABLE {T_FUNDING_LEG} (id SERIAL PRIMARY KEY, "
          "challenge_id INTEGER NOT NULL, sequence_number INTEGER NOT NULL)")
    exc_iii = None
    try:
        run_migration()
    except Exception as exc:                      # noqa: BLE001 — recording
        exc_iii = exc
    _assert("M11 (funding legs without CHECKs/UNIQUE) raises "
            "UnexpectedSchemaError",
            isinstance(exc_iii, UnexpectedSchemaError),
            f"got {type(exc_iii).__name__}")
    _assert("M11 the refusal explains why the guards are load-bearing",
            exc_iii is not None and "reverse" in str(exc_iii).lower(),
            str(exc_iii)[:120])

    # ══════════════════════════════════════════════════════════════════════
    # M12 — a late failure rolls back the entire mutation phase
    # ══════════════════════════════════════════════════════════════════════
    print("\nM12  a failure late in the migration rolls back EVERY object")
    # An index name is unique per SCHEMA in PostgreSQL, but the migration only
    # inspects indexes ON ledger_entries. A decoy of the same name on another
    # table therefore passes every precondition and makes the LAST statement
    # fail — with all three tables and the column already created inside the
    # transaction. If any of that ran outside it, the assertions below fail.
    _rebuild(); _devolve()
    _exec(f"CREATE INDEX {IX_LEDGER_BATCH_ID} ON beef_challenges (id)")
    pre_tables_12 = _tables()
    pre_cols_12   = _cols(T_LEDGER)

    atomic_exc = None
    try:
        run_migration()
    except Exception as exc:                      # noqa: BLE001 — recording
        atomic_exc = exc

    _assert("M12 the late failure really happened", atomic_exc is not None,
            f"got {type(atomic_exc).__name__}")
    _assert("M12 it was the index collision, not a precondition refusal",
            atomic_exc is not None and IX_LEDGER_BATCH_ID in str(atomic_exc)
            and not isinstance(atomic_exc, (LegacyBeefCensusError,
                                            UnexpectedSchemaError)),
            f"{type(atomic_exc).__name__}: {str(atomic_exc)[:110]}")
    _assert("M12 protocol_events was NOT left behind",
            T_PROTOCOL_EVENT not in _tables())
    _assert("M12 ledger_posting_batches was NOT left behind",
            T_POSTING_BATCH not in _tables())
    _assert("M12 challenge_funding_legs was NOT left behind",
            T_FUNDING_LEG not in _tables())
    _assert("M12 the full table set is exactly what it was",
            _tables() == pre_tables_12,
            str(pre_tables_12.symmetric_difference(_tables())))
    _assert("M12 the ledger batch column was NOT left behind",
            _cols(T_LEDGER) == pre_cols_12,
            str(pre_cols_12.symmetric_difference(_cols(T_LEDGER))))

    # M13 (second form) — remove the collision and the same database migrates.
    _exec(f"DROP INDEX {IX_LEDGER_BATCH_ID}")
    rep_after = run_migration()
    _assert("M13 with the collision gone the SAME database migrates cleanly",
            set(rep_after["tables_created"])
            == {T_PROTOCOL_EVENT, T_POSTING_BATCH, T_FUNDING_LEG},
            str(rep_after["tables_created"]))
    _assert("M13 and reaches the clean-install end state exactly",
            _tables() == REF["tables"] and _cols(T_LEDGER) == REF["ledger_cols"]
            and _checks(T_FUNDING_LEG) == REF["leg_checks"])

    # ══════════════════════════════════════════════════════════════════════
    # Structural companions
    # ══════════════════════════════════════════════════════════════════════
    print("\nM-struct  the migration's own shape")
    import re as _re
    src  = Path(mig.__file__).read_text(encoding="utf-8")
    body = src[src.index("def run_migration"):]
    _assert("M-struct exactly ONE engine.begin() repair transaction",
            len(_re.findall(r"with engine\.begin\(\)", body)) == 1,
            str(len(_re.findall(r"with engine\.begin\(\)", body))))
    _assert("M-struct no table is created against the Engine — that would "
            "commit independently and survive a later failure",
            _re.search(r"create\(\s*engine", body) is None)
    _assert("M-struct tables are created bound to the repair Connection",
            "create(bind=conn" in body)
    _assert("M-struct the migration DROPS nothing",
            _re.search(r"\bDROP\b", body) is None, "no DROP in run_migration")
    _assert("M-struct and writes no row",
            _re.search(r"\bINSERT\b|\bUPDATE\b|\bDELETE\b", body) is None)
    _assert("M-struct no down migration is offered — the house idiom has none",
            not any(hasattr(mig, n) for n in
                    ("downgrade", "rollback", "revert", "undo_migration")))
    _assert("M-struct the SQLite position is stated, not discovered",
            "sqlite" in (mig.__doc__ or "").lower())


try:
    main(tdb)
finally:
    tdb.teardown()

print("\n" + "=" * 60)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("All assertions PASSED")
