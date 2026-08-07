"""
test_b6_group_f_migration_pg.py — B6 Package 3 Group F, §15 item 20: the
deployed-database migration (PostgreSQL).

THE METHOD, because it is the whole reason this suite is trustworthy. The
harness builds the FULL B6 schema from the models — that is the clean-install
truth, and it is captured first as the reference. The suite then DEVOLVES that
schema to a deployed pre-B6 shape by removing exactly what Groups A-E added, runs
the migration against it, and asserts the result matches the captured reference
object for object. A migration that produced a *different* uniqueness contract,
a differently-named constraint or a non-partial index would be caught, because
the comparison is against what the model actually produces rather than against a
second copy of the migration's own intentions.

    R10             a nonzero legacy census HALTS before any repair
    NB-E5           uq_faab_tx_one_open_topoff reaches a deployed database, and
                    is PARTIAL with the right predicate
    ck_faab_tx_status   known-old -> replaced; known-target -> no-op;
                    unrecognised -> fail closed; absent -> fail closed
    idempotency     a second run reports nothing and changes nothing
    non-destruction row counts and legacy rows are untouched throughout
    status default  the column acquires NO server default

Devolution is TEST SETUP, not a migration operation. The migration itself drops
nothing except the one stated ck_faab_tx_status replacement; this suite is
allowed to dismantle a disposable test database in order to have something to
migrate.

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] B6 Group F migration suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    from pathlib import Path

    from sqlalchemy import inspect, text

    from db.schema import Base
    from ledger.ledger import create_ledger_table
    from auth.jwt_auth import hash_password

    import db.migrations.migrate_b6_top_off as mig
    from db.migrations.migrate_b6_top_off import (
        run_migration, LegacyCensusError, UnexpectedConstraintError,
        CK_FAAB_TX_STATUS, CK_FAAB_TX_DECISION, CK_FAAB_TX_LIFECYCLE,
        CK_FAAB_TX_LINKAGE, CK_LEAGUES_MULTIPLIER,
        FK_FAAB_TX_REQUESTER, FK_FAAB_TX_DECIDED_BY,
        UQ_FAAB_TX_POSTING, UQ_FAAB_TX_DISCLOSURE,
        IX_FAAB_TX_ONE_OPEN, IX_LEDGER_POSTING, IX_LEDGER_DOOR_ACCT,
        OLD_STATUS_VALUES, TARGET_STATUS_VALUES,
        FAAB_TX_COLUMNS, LEAGUES_COLUMNS,
    )

    engine = tdb.engine

    # ── inspection helpers ────────────────────────────────────────────────

    def _cols(table: str) -> set:
        return {c["name"] for c in inspect(engine).get_columns(table)}

    def _checks(table: str) -> dict:
        return {c["name"]: (c.get("sqltext") or "")
                for c in inspect(engine).get_check_constraints(table)}

    def _uniques(table: str) -> set:
        return {u["name"] for u in inspect(engine).get_unique_constraints(table)}

    def _fks(table: str) -> set:
        return {f["name"] for f in inspect(engine).get_foreign_keys(table)}

    def _indexes(table: str) -> set:
        return {i["name"] for i in inspect(engine).get_indexes(table)}

    def _tables() -> set:
        return set(inspect(engine).get_table_names())

    def _indexdef(name: str):
        with engine.connect() as c:
            return c.execute(text(
                "SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
                {"n": name}).scalar()

    def _column_default(table: str, column: str):
        with engine.connect() as c:
            return c.execute(text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"),
                {"t": table, "c": column}).scalar()

    def _status_values() -> set:
        import re as _re
        return set(_re.findall(r"'([^']*)'",
                               _checks("faab_transactions").get(CK_FAAB_TX_STATUS, "")))

    def _exec(*statements: str) -> None:
        with engine.begin() as c:
            for s in statements:
                c.execute(text(s))

    def _rebuild() -> None:
        """Back to the clean-install state: drop everything, recreate from the
        models.

        tdb.reset() cannot be used in this suite. It TRUNCATEs the full model
        table list, and a scenario that has devolved the schema no longer has
        some of those tables — nor, on the tables that survive, the columns the
        models declare. Only a full rebuild restores the clean-install truth
        this suite compares against.
        """
        tdb.teardown()
        Base.metadata.create_all(engine)
        create_ledger_table()

    def _devolve(status_check_sql: str | None =
                 "status IN ('pending','applied','cancelled','failed')") -> None:
        """Turn the model-built schema into a deployed PRE-B6 shape.

        TEST SETUP ONLY. The migration under test drops nothing but the one
        stated constraint; this dismantles a disposable database so there is a
        pre-B6 database to migrate. `status_check_sql=None` leaves
        ck_faab_tx_status ABSENT, for the fail-closed case.
        """
        _exec(
            "DROP TABLE IF EXISTS top_off_disclosure",
            "DROP TABLE IF EXISTS league_season_topoff_config",
            f"ALTER TABLE leagues DROP CONSTRAINT IF EXISTS {CK_LEAGUES_MULTIPLIER}",
            "ALTER TABLE leagues DROP COLUMN IF EXISTS topoff_cap_multiplier_bps",
            "ALTER TABLE leagues DROP COLUMN IF EXISTS season_closed_at",
            f"ALTER TABLE faab_transactions DROP CONSTRAINT IF EXISTS {CK_FAAB_TX_LINKAGE}",
            f"ALTER TABLE faab_transactions DROP CONSTRAINT IF EXISTS {CK_FAAB_TX_LIFECYCLE}",
            f"ALTER TABLE faab_transactions DROP CONSTRAINT IF EXISTS {CK_FAAB_TX_DECISION}",
            f"ALTER TABLE faab_transactions DROP CONSTRAINT IF EXISTS {UQ_FAAB_TX_POSTING}",
            f"ALTER TABLE faab_transactions DROP CONSTRAINT IF EXISTS {UQ_FAAB_TX_DISCLOSURE}",
            f"ALTER TABLE faab_transactions DROP CONSTRAINT IF EXISTS {FK_FAAB_TX_REQUESTER}",
            f"ALTER TABLE faab_transactions DROP CONSTRAINT IF EXISTS {FK_FAAB_TX_DECIDED_BY}",
            f"DROP INDEX IF EXISTS {IX_FAAB_TX_ONE_OPEN}",
            *[f"ALTER TABLE faab_transactions DROP COLUMN IF EXISTS {c}"
              for c, _ in FAAB_TX_COLUMNS],
            f"DROP INDEX IF EXISTS {IX_LEDGER_POSTING}",
            f"DROP INDEX IF EXISTS {IX_LEDGER_DOOR_ACCT}",
            f"ALTER TABLE faab_transactions DROP CONSTRAINT IF EXISTS {CK_FAAB_TX_STATUS}",
        )
        if status_check_sql is not None:
            _exec(f"ALTER TABLE faab_transactions ADD CONSTRAINT "
                  f"{CK_FAAB_TX_STATUS} CHECK ({status_check_sql})")

    _seed_n = {"i": 0}

    def _seed_minimal() -> tuple:
        """A league, a team and a user, so FK targets exist for legacy rows.

        RAW SQL, not the ORM, and deliberately so: this is called against a
        DEVOLVED pre-B6 schema where the League model's B6 columns do not exist
        yet. An ORM insert would emit them and fail. Only pre-B6 columns are
        named here, which is exactly what a deployed database would have.
        """
        _seed_n["i"] += 1
        tag = f"mig{_seed_n['i']}"
        with engine.begin() as c:
            # Every NOT NULL column whose default is CLIENT-side must be named
            # explicitly — a raw INSERT gets no help from SQLAlchemy defaults.
            lid = c.execute(text(
                "INSERT INTO leagues (season, name, projection_source, "
                "buyin_enforcement_active) "
                "VALUES (2025, :n, 'fantasypros', false) RETURNING id"),
                {"n": tag}).scalar()
            tid = c.execute(text(
                "INSERT INTO teams (league_id, team_name, owner, email) "
                "VALUES (:l, :n, :n, :e) RETURNING id"),
                {"l": lid, "n": tag, "e": f"{tag}@gg.test"}).scalar()
            uid = c.execute(text(
                "INSERT INTO users (email, hashed_password, role, is_active, "
                "buy_in_paid) VALUES (:e, :p, 'gm', 1, 0) RETURNING id"),
                {"e": f"{tag}u@gg.test", "p": hash_password("x")}).scalar()
        return lid, tid, uid

    # ══════════════════════════════════════════════════════════════════════
    # Capture the clean-install reference
    # ══════════════════════════════════════════════════════════════════════
    print("\nM-ref  capture the clean-install truth from the models")
    _rebuild()
    REF = {
        "tables":        _tables(),
        "leagues_cols":  _cols("leagues"),
        "faab_cols":     _cols("faab_transactions"),
        "faab_checks":   set(_checks("faab_transactions")),
        "faab_uniques":  _uniques("faab_transactions"),
        "faab_fks":      _fks("faab_transactions"),
        "faab_indexes":  _indexes("faab_transactions"),
        "ledger_idx":    _indexes("ledger_entries"),
        "leagues_chk":   set(_checks("leagues")),
        "status_values": _status_values(),
        "one_open_def":  _indexdef(IX_FAAB_TX_ONE_OPEN),
        "status_default": _column_default("faab_transactions", "status"),
    }
    _assert("M-ref the model-built schema carries both new B6 tables",
            {"league_season_topoff_config", "top_off_disclosure"} <= REF["tables"])
    _assert("M-ref it carries the partial unique index",
            IX_FAAB_TX_ONE_OPEN in REF["faab_indexes"])
    _assert("M-ref its ck_faab_tx_status is the B6 TARGET set",
            REF["status_values"] == set(TARGET_STATUS_VALUES),
            str(sorted(REF["status_values"])))
    _assert("M-ref the clean-install status column has NO server default",
            REF["status_default"] is None, repr(REF["status_default"]))
    _assert("M-ref the clean-install unique constraint names are the ones the "
            "migration reproduces",
            {UQ_FAAB_TX_POSTING, UQ_FAAB_TX_DISCLOSURE} <= REF["faab_uniques"],
            str(sorted(REF["faab_uniques"])))

    # ══════════════════════════════════════════════════════════════════════
    # M-a — the migration brings a pre-B6 schema up to the model
    # ══════════════════════════════════════════════════════════════════════
    print("\nM-a   the migration upgrades a deployed pre-B6 schema to the model")
    _rebuild()
    _devolve()
    _assert("M-a precondition: the schema is genuinely pre-B6",
            "top_off_disclosure" not in _tables()
            and "amount_cents" not in _cols("faab_transactions")
            and "season_closed_at" not in _cols("leagues")
            and _status_values() == set(OLD_STATUS_VALUES),
            f"status={sorted(_status_values())}")

    report = run_migration()

    _assert("M-a the report says it applied", report["applicable"] is True)
    _assert("M-a the census found zero applied legacy rows",
            report["legacy_applied_topup_bet"] == 0,
            str(report["legacy_applied_topup_bet"]))
    _assert("M-a both B6 tables were created",
            set(report["tables_created"])
            == {"league_season_topoff_config", "top_off_disclosure"},
            str(report["tables_created"]))
    _assert("M-a all ten faab_transactions columns were added",
            {f"faab_transactions.{c}" for c, _ in FAAB_TX_COLUMNS}
            <= set(report["columns_added"]), str(report["columns_added"]))
    _assert("M-a both leagues columns were added",
            {f"leagues.{c}" for c, _ in LEAGUES_COLUMNS}
            <= set(report["columns_added"]), str(report["columns_added"]))
    _assert("M-a ck_faab_tx_status was REPLACED, known-old -> known-target",
            report["status_check_action"] == "replace"
            and report["constraints_replaced"] == [CK_FAAB_TX_STATUS],
            f"{report['status_check_action']} / {report['constraints_replaced']}")

    # Object-for-object comparison against the captured clean-install reference.
    _assert("M-a tables now match the clean install",
            _tables() == REF["tables"],
            str(REF["tables"].symmetric_difference(_tables())))
    _assert("M-a leagues columns now match the clean install",
            _cols("leagues") == REF["leagues_cols"],
            str(REF["leagues_cols"].symmetric_difference(_cols("leagues"))))
    _assert("M-a faab_transactions columns now match the clean install",
            _cols("faab_transactions") == REF["faab_cols"],
            str(REF["faab_cols"].symmetric_difference(_cols("faab_transactions"))))
    _assert("M-a faab_transactions CHECK constraints now match",
            set(_checks("faab_transactions")) == REF["faab_checks"],
            str(REF["faab_checks"].symmetric_difference(set(_checks("faab_transactions")))))
    _assert("M-a faab_transactions UNIQUE constraints now match — the migration "
            "reproduced the clean-install uniqueness contract, not a new one",
            _uniques("faab_transactions") == REF["faab_uniques"],
            str(REF["faab_uniques"].symmetric_difference(_uniques("faab_transactions"))))
    _assert("M-a faab_transactions foreign keys now match",
            _fks("faab_transactions") == REF["faab_fks"],
            str(REF["faab_fks"].symmetric_difference(_fks("faab_transactions"))))
    _assert("M-a faab_transactions indexes now match",
            _indexes("faab_transactions") == REF["faab_indexes"],
            str(REF["faab_indexes"].symmetric_difference(_indexes("faab_transactions"))))
    _assert("M-a leagues CHECK constraints now match",
            set(_checks("leagues")) == REF["leagues_chk"],
            str(REF["leagues_chk"].symmetric_difference(set(_checks("leagues")))))
    _assert("M-a ledger_entries indexes now match",
            _indexes("ledger_entries") == REF["ledger_idx"],
            str(REF["ledger_idx"].symmetric_difference(_indexes("ledger_entries"))))
    _assert("M-a ck_faab_tx_status now permits exactly the B6 target set",
            _status_values() == set(TARGET_STATUS_VALUES),
            str(sorted(_status_values())))

    # ══════════════════════════════════════════════════════════════════════
    # NB-E5 — the partial unique index reaches a deployed database
    # ══════════════════════════════════════════════════════════════════════
    print("\nNB-E5  the partial unique index exists AND is partial, with the "
          "right predicate")
    _assert("NB-E5 uq_faab_tx_one_open_topoff exists after migration",
            IX_FAAB_TX_ONE_OPEN in _indexes("faab_transactions"),
            str(sorted(_indexes("faab_transactions"))))
    got_def = (_indexdef(IX_FAAB_TX_ONE_OPEN) or "").lower()
    _assert("NB-E5 it is UNIQUE", "create unique index" in got_def, got_def[:120])
    _assert("NB-E5 it covers (league_id, team_id, season)",
            "league_id" in got_def and "team_id" in got_def and "season" in got_def,
            got_def[:140])
    _assert("NB-E5 it is PARTIAL — a full unique index here would forbid a team "
            "a second terminal row",
            "where" in got_def and "topup_bet" in got_def and "pending" in got_def,
            got_def[:200])
    _assert("NB-E5 the migrated definition matches the clean-install definition "
            "exactly",
            _indexdef(IX_FAAB_TX_ONE_OPEN) == REF["one_open_def"],
            f"migrated={_indexdef(IX_FAAB_TX_ONE_OPEN)!r}")

    # It must actually bite: two open requests for one team-season are refused,
    # while a second TERMINAL row for the same triple is permitted.
    lid, tid, uid = _seed_minimal()
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO faab_transactions (league_id, team_id, type, amount, "
            "amount_cents, season, status, decision, requester_user_id) VALUES "
            "(:l,:t,'topup_bet',10,1000,2026,'pending','pending',:u)"),
            {"l": lid, "t": tid, "u": uid})
    dup_failed = False
    try:
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO faab_transactions (league_id, team_id, type, amount, "
                "amount_cents, season, status, decision, requester_user_id) VALUES "
                "(:l,:t,'topup_bet',10,1000,2026,'pending','pending',:u)"),
                {"l": lid, "t": tid, "u": uid})
    except Exception:                             # noqa: BLE001 — expected
        dup_failed = True
    _assert("NB-E5 a SECOND open request for the same league/team/season is "
            "refused by the index", dup_failed is True)
    second_terminal_ok = True
    try:
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO faab_transactions (league_id, team_id, type, amount, "
                "amount_cents, season, status, decision, requester_user_id) VALUES "
                "(:l,:t,'topup_bet',10,1000,2026,'cancelled','cancelled',:u)"),
                {"l": lid, "t": tid, "u": uid})
    except Exception:                             # noqa: BLE001 — recording
        second_terminal_ok = False
    _assert("NB-E5 a terminal row for the same triple is still PERMITTED — the "
            "index is scoped to open requests only", second_terminal_ok is True)

    # ══════════════════════════════════════════════════════════════════════
    # M-b — idempotency and non-destruction
    # ══════════════════════════════════════════════════════════════════════
    print("\nM-b   a second run changes nothing")
    with engine.connect() as c:
        rows_before = c.execute(text("SELECT COUNT(*) FROM faab_transactions")).scalar()
    before_shape = (_tables(), _cols("faab_transactions"),
                    set(_checks("faab_transactions")), _uniques("faab_transactions"),
                    _indexes("faab_transactions"), _indexes("ledger_entries"))
    report2 = run_migration()
    with engine.connect() as c:
        rows_after = c.execute(text("SELECT COUNT(*) FROM faab_transactions")).scalar()

    _assert("M-b the second run created no table, column, constraint or index",
            report2["tables_created"] == [] and report2["columns_added"] == []
            and report2["constraints_added"] == []
            and report2["constraints_replaced"] == []
            and report2["indexes_created"] == [], str(report2))
    _assert("M-b ck_faab_tx_status is now a NO-OP (known-target)",
            report2["status_check_action"] == "noop",
            report2["status_check_action"])
    _assert("M-b the schema is byte-for-byte the same shape",
            before_shape == (_tables(), _cols("faab_transactions"),
                             set(_checks("faab_transactions")),
                             _uniques("faab_transactions"),
                             _indexes("faab_transactions"),
                             _indexes("ledger_entries")))
    _assert("M-b NO row was inserted, updated or deleted",
            rows_before == rows_after, f"{rows_before} -> {rows_after}")

    # ══════════════════════════════════════════════════════════════════════
    # M-c — the status column acquires no server default
    # ══════════════════════════════════════════════════════════════════════
    print("\nM-c   faab_transactions.status acquires NO server default")
    _assert("M-c the migrated column has no server default",
            _column_default("faab_transactions", "status") is None,
            repr(_column_default("faab_transactions", "status")))
    _assert("M-c which matches the clean install exactly",
            _column_default("faab_transactions", "status") == REF["status_default"])
    _assert("M-c CONTROL: the column that SHOULD have one does — leagues"
            ".topoff_cap_multiplier_bps",
            (_column_default("leagues", "topoff_cap_multiplier_bps") or "")
            .startswith("10000"),
            repr(_column_default("leagues", "topoff_cap_multiplier_bps")))

    # ══════════════════════════════════════════════════════════════════════
    # R10 — the census halts before any repair
    # ══════════════════════════════════════════════════════════════════════
    print("\nR10   a nonzero legacy census HALTS before any schema repair "
          "(§11.4)")
    _rebuild()
    _devolve()
    lid, tid, uid = _seed_minimal()
    # A legacy applied top-up: no requester, no approver, no posting, no
    # disclosure — exactly the row the B6 constraints cannot admit. It is
    # insertable now precisely because the pre-B6 schema has no such constraint.
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO faab_transactions (league_id, team_id, type, amount, "
            "status) VALUES (:l,:t,'topup_bet',25.0,'applied')"),
            {"l": lid, "t": tid})
    pre_tables  = _tables()
    pre_cols    = _cols("faab_transactions")
    pre_checks  = set(_checks("faab_transactions"))
    pre_status  = _status_values()
    pre_ledgeri = _indexes("ledger_entries")

    census_exc = None
    try:
        run_migration()
    except Exception as exc:                      # noqa: BLE001 — recording
        census_exc = exc

    _assert("R10 raises LegacyCensusError (by TYPE)",
            isinstance(census_exc, LegacyCensusError),
            f"got {type(census_exc).__name__}: {census_exc}")
    _assert("R10 NO table was created", _tables() == pre_tables,
            str(pre_tables.symmetric_difference(_tables())))
    _assert("R10 NO column was added", _cols("faab_transactions") == pre_cols,
            str(pre_cols.symmetric_difference(_cols("faab_transactions"))))
    _assert("R10 NO constraint was added",
            set(_checks("faab_transactions")) == pre_checks,
            str(pre_checks.symmetric_difference(set(_checks("faab_transactions")))))
    _assert("R10 ck_faab_tx_status was NOT replaced — the halt precedes it",
            _status_values() == pre_status, str(sorted(_status_values())))
    _assert("R10 NO ledger index was created",
            _indexes("ledger_entries") == pre_ledgeri)
    with engine.connect() as c:
        legacy_still = c.execute(text(
            "SELECT COUNT(*) FROM faab_transactions "
            "WHERE type='topup_bet' AND status='applied'")).scalar()
    _assert("R10 the legacy row is UNTOUCHED — no backfill, no classification, "
            "no quarantine", legacy_still == 1, str(legacy_still))
    _assert("R10 the refusal names the count so an operator can act on it",
            census_exc is not None and "1 legacy row" in str(census_exc),
            str(census_exc)[:110])

    # ══════════════════════════════════════════════════════════════════════
    # M-d — ck_faab_tx_status fail-closed rule
    # ══════════════════════════════════════════════════════════════════════
    print("\nM-d   ck_faab_tx_status: recognised definitions only, else fail "
          "closed")

    # (i) already the target -> no-op, and nothing else regresses.
    _rebuild()
    _devolve(status_check_sql="status IN ('pending','applied','rejected',"
                              "'cancelled','failed')")
    rep_target = run_migration()
    _assert("M-d (target) reports a no-op",
            rep_target["status_check_action"] == "noop"
            and rep_target["constraints_replaced"] == [],
            str(rep_target["status_check_action"]))
    _assert("M-d (target) the constraint still permits the target set",
            _status_values() == set(TARGET_STATUS_VALUES),
            str(sorted(_status_values())))
    _assert("M-d (target) the rest of the migration still ran",
            IX_FAAB_TX_ONE_OPEN in _indexes("faab_transactions")
            and "top_off_disclosure" in _tables())

    # (ii) an unrecognised third definition -> fail closed, nothing replaced.
    _rebuild()
    _devolve(status_check_sql="status IN ('pending','applied')")
    pre_status_iii = _status_values()
    pre_tables_iii = _tables()
    unexpected_exc = None
    try:
        run_migration()
    except Exception as exc:                      # noqa: BLE001 — recording
        unexpected_exc = exc
    _assert("M-d (unrecognised) raises UnexpectedConstraintError (by TYPE)",
            isinstance(unexpected_exc, UnexpectedConstraintError),
            f"got {type(unexpected_exc).__name__}")
    _assert("M-d (unrecognised) the unknown constraint was NOT dropped",
            _status_values() == pre_status_iii, str(sorted(_status_values())))
    _assert("M-d (unrecognised) no table was created either — it fails before "
            "any DDL", _tables() == pre_tables_iii)

    # (iii) absent -> fail closed. A missing constraint is not an invitation to
    # invent one on a table whose current rules are unknown.
    _rebuild()
    _devolve(status_check_sql=None)
    absent_exc = None
    try:
        run_migration()
    except Exception as exc:                      # noqa: BLE001 — recording
        absent_exc = exc
    _assert("M-d (absent) raises UnexpectedConstraintError (by TYPE)",
            isinstance(absent_exc, UnexpectedConstraintError),
            f"got {type(absent_exc).__name__}")
    _assert("M-d (absent) no constraint was invented",
            CK_FAAB_TX_STATUS not in _checks("faab_transactions"))

    # ══════════════════════════════════════════════════════════════════════
    # M-e — the migration drops nothing else, and touches no data
    # ══════════════════════════════════════════════════════════════════════
    print("\nM-e   the migration is additive apart from the one stated "
          "replacement")
    _rebuild()
    _devolve()
    lid, tid, uid = _seed_minimal()
    # Legacy history that must survive untouched: dormant waiver rows and an
    # unrelated transfer row, none of which is a B6 request (§11.5). The
    # topup_bet-scoped CHECKs do not reach them, which is precisely why they can
    # be migrated over without being touched.
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO faab_transactions (league_id, team_id, type, amount, "
            "status, note) VALUES (:l,:t,'topup_waiver',5.0,'pending','legacy')"),
            {"l": lid, "t": tid})
        c.execute(text(
            "INSERT INTO faab_transactions (league_id, team_id, type, amount, "
            "status, note) VALUES "
            "(:l,:t,'transfer_bet_to_waiver',7.0,'applied','legacy')"),
            {"l": lid, "t": tid})
    with engine.connect() as c:
        before_rows = c.execute(text(
            "SELECT id, type, amount, status, note FROM faab_transactions "
            "ORDER BY id")).fetchall()
        before_leagues = c.execute(text("SELECT COUNT(*) FROM leagues")).scalar()

    rep_e = run_migration()

    with engine.connect() as c:
        after_rows = c.execute(text(
            "SELECT id, type, amount, status, note FROM faab_transactions "
            "ORDER BY id")).fetchall()
        after_leagues = c.execute(text("SELECT COUNT(*) FROM leagues")).scalar()

    _assert("M-e the migration completed", rep_e["applicable"] is True)
    _assert("M-e it reported the legacy census truthfully",
            rep_e["legacy_topup_bet_total"] == 0
            and rep_e["legacy_applied_topup_bet"] == 0
            and rep_e["legacy_undecided_topup_bet"] == 0,
            f"total={rep_e['legacy_topup_bet_total']}")
    _assert("M-e EVERY legacy row survives byte-identical — no conversion, no "
            "backfill", before_rows == after_rows,
            f"{before_rows} -> {after_rows}")
    _assert("M-e no league row was touched", before_leagues == after_leagues)
    _assert("M-e the only constraint ever replaced is ck_faab_tx_status",
            rep_e["constraints_replaced"] == [CK_FAAB_TX_STATUS],
            str(rep_e["constraints_replaced"]))
    _assert("M-e the legacy topup_waiver row was NOT given a decision",
            after_rows[0][1] == "topup_waiver" and after_rows[0][3] == "pending")

    # ══════════════════════════════════════════════════════════════════════
    # M-g — an UNDECIDED legacy topup_bet row halts too
    # ══════════════════════════════════════════════════════════════════════
    print("\nM-g   a dormant UNDECIDED legacy topup_bet row halts before any "
          "schema change")
    # §11.4 names only the applied count, but ck_faab_tx_topup_bet_lifecycle
    # refuses ANY topup_bet row with a NULL decision — and every pre-B6 row is
    # one, because the column did not exist. A `pending` legacy request is the
    # ordinary case: create_bet_topup() wrote exactly that shape. Without this
    # second precondition the migration would create two tables and then die on
    # ADD CONSTRAINT, leaving a half-migrated schema.
    _rebuild()
    _devolve()
    lid, tid, uid = _seed_minimal()
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO faab_transactions (league_id, team_id, type, amount, "
            "status, note) VALUES (:l,:t,'topup_bet',9.0,'pending','legacy')"),
            {"l": lid, "t": tid})
    pre_tables_g = _tables()
    pre_cols_g   = _cols("faab_transactions")

    undecided_exc = None
    try:
        run_migration()
    except Exception as exc:                      # noqa: BLE001 — recording
        undecided_exc = exc

    _assert("M-g raises LegacyCensusError (by TYPE)",
            isinstance(undecided_exc, LegacyCensusError),
            f"got {type(undecided_exc).__name__}")
    _assert("M-g the refusal explains that a decision cannot be invented",
            undecided_exc is not None
            and "never becomes a B6 request" in str(undecided_exc),
            str(undecided_exc)[:120])
    _assert("M-g NO table was created — the halt precedes even the table "
            "creation that sits outside the repair transaction",
            _tables() == pre_tables_g,
            str(pre_tables_g.symmetric_difference(_tables())))
    _assert("M-g NO column was added", _cols("faab_transactions") == pre_cols_g)
    with engine.connect() as c:
        legacy_g = c.execute(text(
            "SELECT status, note FROM faab_transactions "
            "WHERE type='topup_bet'")).fetchall()
    _assert("M-g the dormant row is untouched — no decision was written to it",
            legacy_g == [("pending", "legacy")], str(legacy_g))

    # ══════════════════════════════════════════════════════════════════════
    # M-h — ATOMICITY: a late failure rolls the WHOLE repair back
    # ══════════════════════════════════════════════════════════════════════
    print("\nM-h   a failure late in the repair rolls back EVERY B6 object, "
          "including the two new tables")
    # THE MECHANISM IS A REAL COLLISION, NOT A PATCH. An index name is unique
    # per schema in PostgreSQL, but inspect().get_indexes('ledger_entries')
    # only reports indexes ON that table. Planting an index called
    # ix_ledger_entries_posting_id on a DIFFERENT table therefore passes every
    # precondition and then makes the LAST statement of the repair fail with a
    # genuine "already exists" — which is exactly the shape of an unexpected
    # late failure in a deployed database, and needs no instrumentation of the
    # migration itself.
    #
    # By the time it fires, the repair has already created both tables, added
    # twelve columns, added every constraint and created the partial unique
    # index. If ANY of that ran outside the transaction it survives, and the
    # assertions below fail. That is what makes this a transactional-boundary
    # test rather than an error-handling one.
    _rebuild()
    _devolve()
    _exec("CREATE INDEX ix_ledger_entries_posting_id ON faab_transactions (id)")

    pre_tables_h  = _tables()
    pre_lg_cols_h = _cols("leagues")
    pre_fx_cols_h = _cols("faab_transactions")
    pre_checks_h  = set(_checks("faab_transactions"))
    pre_uqs_h     = _uniques("faab_transactions")
    pre_fks_h     = _fks("faab_transactions")
    pre_idx_h     = _indexes("faab_transactions")
    pre_status_h  = _status_values()
    _assert("M-h precondition: the schema is devolved and the decoy index is "
            "invisible to the migration's ledger_entries inspection",
            "league_season_topoff_config" not in pre_tables_h
            and IX_LEDGER_POSTING not in _indexes("ledger_entries")
            and pre_status_h == set(OLD_STATUS_VALUES),
            f"status={sorted(pre_status_h)}")

    atomic_exc = None
    try:
        run_migration()
    except Exception as exc:                      # noqa: BLE001 — recording
        atomic_exc = exc

    _assert("M-h the late failure really happened",
            atomic_exc is not None,
            f"got {type(atomic_exc).__name__}")
    _assert("M-h it was the index-name collision, not a precondition refusal",
            atomic_exc is not None
            and "ix_ledger_entries_posting_id" in str(atomic_exc)
            and not isinstance(atomic_exc, (LegacyCensusError,
                                            UnexpectedConstraintError)),
            f"{type(atomic_exc).__name__}: {str(atomic_exc)[:120]}")

    _assert("M-h league_season_topoff_config was NOT left behind — the CREATE "
            "TABLE rolled back with everything else",
            "league_season_topoff_config" not in _tables(),
            str(sorted(_tables() - pre_tables_h)))
    _assert("M-h top_off_disclosure was NOT left behind",
            "top_off_disclosure" not in _tables(),
            str(sorted(_tables() - pre_tables_h)))
    _assert("M-h the full table set is exactly what it was",
            _tables() == pre_tables_h,
            str(pre_tables_h.symmetric_difference(_tables())))
    _assert("M-h no leagues column was partially added",
            _cols("leagues") == pre_lg_cols_h,
            str(pre_lg_cols_h.symmetric_difference(_cols("leagues"))))
    _assert("M-h no faab_transactions column was partially added",
            _cols("faab_transactions") == pre_fx_cols_h,
            str(pre_fx_cols_h.symmetric_difference(_cols("faab_transactions"))))
    _assert("M-h no B6 CHECK constraint remains",
            set(_checks("faab_transactions")) == pre_checks_h,
            str(pre_checks_h.symmetric_difference(set(_checks("faab_transactions")))))
    _assert("M-h no B6 unique constraint remains",
            _uniques("faab_transactions") == pre_uqs_h,
            str(pre_uqs_h.symmetric_difference(_uniques("faab_transactions"))))
    _assert("M-h no B6 foreign key remains",
            _fks("faab_transactions") == pre_fks_h,
            str(pre_fks_h.symmetric_difference(_fks("faab_transactions"))))
    _assert("M-h uq_faab_tx_one_open_topoff is ABSENT",
            IX_FAAB_TX_ONE_OPEN not in _indexes("faab_transactions"),
            str(sorted(_indexes("faab_transactions"))))
    _assert("M-h faab_transactions indexes are exactly what they were",
            _indexes("faab_transactions") == pre_idx_h,
            str(pre_idx_h.symmetric_difference(_indexes("faab_transactions"))))
    _assert("M-h ck_faab_tx_status still carries its ORIGINAL known-old "
            "definition — the DROP/ADD pair rolled back too",
            _status_values() == set(OLD_STATUS_VALUES),
            str(sorted(_status_values())))
    _assert("M-h no ledger index was left behind either",
            IX_LEDGER_DOOR_ACCT not in _indexes("ledger_entries"),
            str(sorted(_indexes("ledger_entries"))))

    # And once the collision is removed the very same database migrates cleanly,
    # proving the rollback left it usable rather than merely empty.
    _exec("DROP INDEX ix_ledger_entries_posting_id")
    rep_h = run_migration()
    _assert("M-h with the collision gone the SAME database migrates cleanly",
            rep_h["applicable"] is True
            and set(rep_h["tables_created"])
            == {"league_season_topoff_config", "top_off_disclosure"},
            str(rep_h["tables_created"]))
    _assert("M-h and reaches the same end state as a clean install",
            _tables() == REF["tables"]
            and _cols("faab_transactions") == REF["faab_cols"]
            and _status_values() == set(TARGET_STATUS_VALUES))

    # ══════════════════════════════════════════════════════════════════════
    # M-f — the module is inert on import and on SQLite
    # ══════════════════════════════════════════════════════════════════════
    print("\nM-f   the migration runs nothing on import, and is a stated no-op "
          "on SQLite")
    _assert("M-f run_migration is a plain callable, not module-level work",
            callable(run_migration))
    _assert("M-f the module states the SQLite position rather than leaving it "
            "to be discovered",
            "sqlite" in (mig.__doc__ or "").lower()
            and "rebuilt from the models" in (mig.__doc__ or "").lower())
    _assert("M-f no down migration is offered — the house idiom has none",
            not any(hasattr(mig, n) for n in
                    ("downgrade", "rollback", "revert", "undo_migration")))

    # Structural companion to M-h: every mutating statement in run_migration()
    # is issued on the ONE transactional Connection. A future edit that reached
    # for the Engine again — the exact defect M-h exists to catch — would fail
    # here as well, and would say why.
    import re as _re
    src = (Path(mig.__file__).read_text(encoding="utf-8"))
    body = src[src.index("def run_migration"):]
    _assert("M-f exactly ONE engine.begin() repair transaction",
            len(_re.findall(r"with engine\.begin\(\)", body)) == 1,
            str(len(_re.findall(r"with engine\.begin\(\)", body))))
    _assert("M-f no table is created against the Engine — that would commit "
            "independently and survive a later failure",
            _re.search(r"create\(\s*engine", body) is None)
    _assert("M-f the tables are created bound to the repair Connection",
            "create(bind=conn" in body)
    _assert("M-f no statement is executed directly on the Engine",
            _re.search(r"engine\.execute\(", body) is None)


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
