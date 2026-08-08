"""
test_pool_rotation_schema_pg.py — Pool rotation schema, steps 2/3/4 (PostgreSQL).

Covers the three tables added by §C1/§C2/§C3 and the migration that creates them.

WHAT IS ACTUALLY BEING PROVEN. Creating an index proves nothing. Every assertion
here proves ENFORCEMENT, individually, never in aggregate:

  H1 fresh REGULAR row                      -> ACCEPTED
  H2 second fresh, same 4 cycle key columns -> REJECTED
  H3 continuation (origin_instance_id set)  -> ACCEPTED
  H4 fresh, phase != 'REGULAR'              -> ACCEPTED

run against BOTH backends and against BOTH schema sources — the ORM declaration
(Base.metadata.create_all, which is what every test suite gets) and the real
migration's own DDL (which is what production gets). Those are two independent
authorings of the same predicate and nothing in the repo keeps them in sync, so
proving one says nothing about the other.

CONTROLS ARE TEST-ONLY. db/schema.py and the migration are NEVER edited to
manufacture a broken variant. Every control is a separate MetaData or a separate
DDL string declared inside this file, targeting a differently-named table, so a
hash fence over the implementation files is flat across the whole run. A control
that requires mutating the thing under test cannot prove the thing under test.

  CONTROL A  ORM index with sqlite_where omitted, run on SQLite
             -> H3/H4 must be REJECTED (silently degraded to a FULL unique index)
  CONTROL B  ORM index with postgresql_where omitted, run on PostgreSQL
             -> H3/H4 must be REJECTED
  CONTROL C  migration DDL with the WHERE clause removed
             -> M3/M4 must be REJECTED

If a control does NOT fail as predicted, the corresponding positive assertions
are not discriminating and the result is worthless. That is reported, not
adjusted.

TEARDOWN IS GUARANTEED. Every table this file creates is dropped in a finally
block. Public-schema table count is recorded before and after and must return to
its starting value — a crashed run that stranded tables would poison every later
suite on this database.

Requires TEST_DATABASE_URL -> local, port 5433, _test-named, non-Railway.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST — applies its guards, binds DATABASE_URL, imports db.schema.
from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] Pool rotation schema suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _rev13_definition_row(key: str) -> dict:
    """The fixture definition, taken from the GOVERNED Rev1.3 catalog.

    S4-P1 widened pool_definition to the Rev1.3 field set and renamed
    block_reason to blocked_reason, so the hand-written Rev1.0 literal this
    replaced no longer constructs a valid row. Reading the real catalog instead
    of re-typing a literal means this fixture cannot drift from the artifact the
    seeder uses."""
    from betting.pool_catalog import load_catalog

    spec = load_catalog().by_key(key)
    return {
        "key": spec.key, "catalog_number": spec.catalog_number,
        "display_name": spec.display_name, "category": spec.category,
        "scope": spec.scope, "mechanic": spec.mechanic,
        "evaluator_family": spec.evaluator_family,
        "evaluator_shape": spec.evaluator_shape,
        "metric_kind": spec.metric_kind, "direction": spec.direction,
        "metric_expression": spec.metric_expression,
        "governed_definition": spec.governed_definition,
        "threshold_condition": spec.threshold_condition,
        "predicate": spec.predicate,
        "predicate_quantifier": spec.predicate_quantifier,
        "threshold_configurable": spec.threshold_configurable,
        "threshold_default": spec.threshold_default,
        "required_stats": list(spec.required_stats) or None,
        "required_stats_resolved": spec.required_stats_resolved,
        "required_stats_unresolved_reason":
            spec.required_stats_unresolved_reason,
        "source_mapping_complete": spec.source_mapping_complete,
        "unmapped_required_stats": list(spec.unmapped_required_stats) or None,
        "starter_slot_rule": spec.starter_slot_rule,
        "slot_filter": list(spec.slot_filter) or None,
        "slot_exclusions": list(spec.slot_exclusions) or None,
        "self_pick_rule": spec.self_pick_rule,
        "anti_tanking_review": spec.anti_tanking_review,
        "data_dependency": spec.data_dependency,
        "dependency_state": spec.dependency_state,
        "blocked_reason": spec.blocked_reason,
        "product_complete": spec.product_complete,
        "definition_runtime_eligible": spec.definition_runtime_eligible,
        "definition_block_reason": spec.definition_block_reason,
        "regular_season_eligible": spec.regular_season_eligible,
        "postseason_eligible": spec.postseason_eligible,
        "rollover_eligible": spec.rollover_eligible,
        "tie_rule": spec.tie_rule,
        "aggregate_over_aggregate_required":
            spec.aggregate_over_aggregate_required,
        "zero_denominator_guard": spec.zero_denominator_guard,
    }


def _insert_definition(conn, key: str) -> None:
    """Insert one governed definition row through a raw connection.

    Used where the test drives a bare Connection rather than a Session — the
    values still come from the Rev1.3 catalog, so this cannot drift from the
    seeder."""
    from sqlalchemy import text as _text

    row = _rev13_definition_row(key)
    import json as _json

    for json_column in ("required_stats", "unmapped_required_stats",
                        "slot_filter", "slot_exclusions"):
        if row[json_column] is not None:
            row[json_column] = _json.dumps(row[json_column])

    columns = ", ".join(row)
    binds = ", ".join(f":{c}" for c in row)
    conn.execute(
        _text(f"INSERT INTO pool_definition ({columns}) VALUES ({binds})"), row)


def main(tdb) -> None:
    from sqlalchemy import (
        BigInteger, Boolean, CheckConstraint, Column, DateTime, Index, Integer,
        MetaData, String, Table, UniqueConstraint, create_engine, inspect, text,
    )

    from db.schema import Base, SessionLocal, engine, League, PoolDefinition
    from db.migrations.migrate_pool_rotation_tables import (
        upgrade, _PARTIAL_PREDICATE,
    )
    from db.migrations.migrate_s4_common_pool_engine import (
        upgrade as s4_upgrade,
    )

    PUBLIC_COUNT = ("SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public'")
    with engine.connect() as c:
        tables_at_start = c.execute(text(PUBLIC_COUNT)).scalar()
    print(f"\n  public-schema tables at start: {tables_at_start}")

    # ── shared fixture values ────────────────────────────────────────────────
    SEASON, CYCLE, DKEY = 2026, 1, "most_total_touchdowns"

    with SessionLocal() as db:
        lg = League(season=SEASON, name="pool-rotation-schema",
                    projection_source="fantasypros")
        db.add(lg)
        db.commit()
        LEAGUE_ID = lg.id
    with SessionLocal() as db:
        db.add(PoolDefinition(**_rev13_definition_row(DKEY)))
        db.commit()

    # ── generic 4-probe driver, reused by every variant ──────────────────────
    def probe(conn, tbl_ins, *, league_id, needs_fk_rows):
        """Run H1..H4 against a table, each insert in its own transaction.
        Returns {'H1': (accepted, err), ...}. tbl_ins is a callable taking the
        row dict and returning an executable insert."""
        out = {}
        base = dict(league_id=league_id, season=SEASON,
                    rotation_cycle=CYCLE, definition_key=DKEY)

        def ins(**over):
            row = dict(base); row.update(over)
            tx = conn.begin_nested() if conn.in_transaction() else conn.begin()
            try:
                res = conn.execute(tbl_ins(row))
                rid = res.inserted_primary_key[0] if res.inserted_primary_key else None
                tx.commit()
                return True, rid, ""
            except Exception as exc:
                tx.rollback()
                first = str(getattr(exc, "orig", exc)).strip().splitlines()
                return False, None, f"{type(exc).__name__}: {first[0] if first else ''}"

        ok1, id1, e1 = ins(week=1, phase="REGULAR", slot=1, origin_instance_id=None)
        out["H1"] = (ok1, e1)
        ok2, _, e2 = ins(week=2, phase="REGULAR", slot=1, origin_instance_id=None)
        out["H2"] = (ok2, e2)
        ok3, _, e3 = ins(week=3, phase="REGULAR", slot=1, origin_instance_id=id1)
        out["H3"] = (ok3, e3)
        ok4, _, e4 = ins(week=4, phase="POSTSEASON", slot=1, origin_instance_id=None)
        out["H4"] = (ok4, e4)
        return out

    def control_table(md, name, *, sqlite_where, postgresql_where):
        """TEST-ONLY table mirroring pool_instance's cycle-index shape. Declared
        here, never in db/schema.py. FKs deliberately omitted — the FK is not
        what is under test and would only add unrelated failure modes."""
        kw = {}
        if sqlite_where is not None:
            kw["sqlite_where"] = text(sqlite_where)
        if postgresql_where is not None:
            kw["postgresql_where"] = text(postgresql_where)
        t = Table(
            name, md,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("league_id", Integer, nullable=False),
            Column("season", Integer, nullable=False),
            Column("week", Integer, nullable=False),
            Column("phase", String, nullable=False),
            Column("rotation_cycle", Integer, nullable=False),
            Column("definition_key", String, nullable=False),
            Column("slot", Integer, nullable=False),
            Column("origin_instance_id", Integer, nullable=True),
        )
        Index(f"uq_{name}_cycle_fresh",
              t.c.league_id, t.c.season, t.c.rotation_cycle, t.c.definition_key,
              unique=True, **kw)
        return t

    PREDICATE = "origin_instance_id IS NULL AND phase = 'REGULAR'"
    base_cols = ("league_id, season, week, phase, rotation_cycle, "
                 "definition_key, slot")
    created_control_tables: list[str] = []

    try:
        # ================================================================
        # TEST A — the ORM declaration, on BOTH backends.
        # ================================================================
        print("\n-- TEST A: ORM declaration (Base.metadata.create_all) --")

        # --- SQLite ---
        sq = create_engine("sqlite://")
        Base.metadata.create_all(sq)
        from db.schema import PoolInstance
        with sq.connect() as c:
            c.execute(text("INSERT INTO leagues (id, season, name, projection_source, "
                           "buyin_enforcement_active) VALUES (1, 2026, 'x', 'fantasypros', 0)"))
            # The FK parent for the pool_instance probes below. Built from the
            # governed Rev1.3 catalog rather than a hand-written column list:
            # S4-P1 added seven NOT NULL columns to pool_definition, and a
            # literal INSERT here would have to be re-typed every time the
            # governed field set moves. Only the FK target matters to this
            # test; which columns carry it does not.
            _insert_definition(c, DKEY)
            c.commit()
            rs = probe(c, lambda r: PoolInstance.__table__.insert().values(**r),
                       league_id=1, needs_fk_rows=False)
        for i, (h, want) in enumerate(zip(("H1","H2","H3","H4"), (True, False, True, True))):
            got, err = rs[h]
            _assert(f"{i}: SQLite ORM {h} -> {'ACCEPTED' if want else 'REJECTED'}",
                    got == want,
                    detail=(err or "accepted") + f" (expected {'ACCEPT' if want else 'REJECT'})")

        # --- PostgreSQL ---
        with engine.connect() as c:
            rs = probe(c, lambda r: PoolInstance.__table__.insert().values(**r),
                       league_id=LEAGUE_ID, needs_fk_rows=False)
        for i, (h, want) in enumerate(zip(("H1","H2","H3","H4"), (True, False, True, True)), start=4):
            got, err = rs[h]
            _assert(f"{i}: PostgreSQL ORM {h} -> {'ACCEPTED' if want else 'REJECTED'}",
                    got == want,
                    detail=(err or "accepted") + f" (expected {'ACCEPT' if want else 'REJECT'})")

        # ================================================================
        # CONTROL A / CONTROL B — dialect-kwarg omission, TEST-ONLY tables.
        # ================================================================
        print("\n-- CONTROL A: sqlite_where omitted, run on SQLite --")
        mdA = MetaData()
        tA = control_table(mdA, "zz_ctrl_instance_a",
                           sqlite_where=None, postgresql_where=PREDICATE)
        sqA = create_engine("sqlite://")
        mdA.create_all(sqA)
        with sqA.connect() as c:
            rsA = probe(c, lambda r: tA.insert().values(**r), league_id=1, needs_fk_rows=False)
        _assert("8: CONTROL A - SQLite H3 continuation REJECTED (degraded to full unique)",
                rsA["H3"][0] is False, detail=rsA["H3"][1] or "ACCEPTED (control did not bite)")
        _assert("9: CONTROL A - SQLite H4 non-REGULAR REJECTED (degraded to full unique)",
                rsA["H4"][0] is False, detail=rsA["H4"][1] or "ACCEPTED (control did not bite)")

        print("\n-- CONTROL B: postgresql_where omitted, run on PostgreSQL --")
        mdB = MetaData()
        tB = control_table(mdB, "zz_ctrl_instance_b",
                           sqlite_where=PREDICATE, postgresql_where=None)
        mdB.create_all(engine)
        created_control_tables.append("zz_ctrl_instance_b")
        with engine.connect() as c:
            rsB = probe(c, lambda r: tB.insert().values(**r),
                        league_id=LEAGUE_ID, needs_fk_rows=False)
        _assert("10: CONTROL B - PostgreSQL H3 continuation REJECTED (full unique)",
                rsB["H3"][0] is False, detail=rsB["H3"][1] or "ACCEPTED (control did not bite)")
        _assert("11: CONTROL B - PostgreSQL H4 non-REGULAR REJECTED (full unique)",
                rsB["H4"][0] is False, detail=rsB["H4"][1] or "ACCEPTED (control did not bite)")

        # ================================================================
        # TEST C — conventions: CHECK domains and the named self-FK.
        # ================================================================
        print("\n-- TEST C: CHECK constraints and self-FK --")

        def try_raw(sql):
            with engine.connect() as c:
                tx = c.begin()
                try:
                    c.execute(text(sql))
                    tx.commit()
                    return True, ""
                except Exception as exc:
                    tx.rollback()
                    f = str(getattr(exc, "orig", exc)).strip().splitlines()
                    return False, f"{type(exc).__name__}: {f[0] if f else ''}"

        ok_phase, err_phase = try_raw(
            f"INSERT INTO pool_instance ({base_cols}) VALUES "
            f"({LEAGUE_ID}, {SEASON}, 90, 'PRESEASON', {CYCLE}, '{DKEY}', 1)")
        _assert("12: phase CHECK rejects an out-of-domain value ('PRESEASON')",
                ok_phase is False, detail=err_phase or "ACCEPTED — CHECK absent")

        ok_slot, err_slot = try_raw(
            f"INSERT INTO pool_instance ({base_cols}) VALUES "
            f"({LEAGUE_ID}, {SEASON}, 91, 'REGULAR', {CYCLE}, '{DKEY}', 5)")
        _assert("13: slot CHECK rejects an out-of-domain value (5)",
                ok_slot is False, detail=err_slot or "ACCEPTED — CHECK absent")

        with engine.connect() as c:
            fks = inspect(engine).get_foreign_keys("pool_instance")
        self_fk = [f for f in fks if f.get("referred_table") == "pool_instance"]
        _assert("14: self-FK on pool_instance exists and is named fk_pool_instance_origin",
                len(self_fk) == 1 and self_fk[0].get("name") == "fk_pool_instance_origin"
                and self_fk[0].get("constrained_columns") == ["origin_instance_id"],
                detail=f"{[(f.get('name'), f.get('constrained_columns'), f.get('referred_table')) for f in fks]}")

        # ================================================================
        # TEST B — the REAL migration's own DDL.
        # Drop the three tables create_all made, then let upgrade(engine)
        # rebuild them. leagues survives, so the FK target still exists.
        # ================================================================
        print("\n-- TEST B: real migration upgrade(engine) --")
        with engine.begin() as c:
            for t in ("pool_claim", "pool_economic_event",
                      "pool_league_activation", "pool_rotation_cycle",
                      "pool_instance", "pool_definition"):
                c.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))

        upgrade(engine)          # <- the real production DDL, not a copy
        # S4-P1 extends that Rev1.0 schema rather than replacing it, and
        # production applies the two in this order. Running only the first
        # would leave the ORM and the migration describing different tables,
        # which is the two-disagreeing-schema-sources defect this file exists
        # to catch.
        s4_upgrade(engine)

        with SessionLocal() as db:
            db.add(PoolDefinition(**_rev13_definition_row(DKEY)))
            db.commit()

        with engine.connect() as c:
            rsM = probe(c, lambda r: PoolInstance.__table__.insert().values(**r),
                        league_id=LEAGUE_ID, needs_fk_rows=False)
        for i, (h, want, name) in enumerate(zip(
                ("H1","H2","H3","H4"), (True, False, True, True),
                ("M1 fresh", "M2 duplicate fresh", "M3 continuation", "M4 non-REGULAR")), start=15):
            got, err = rsM[h]
            _assert(f"{i}: migration DDL {name} -> {'ACCEPTED' if want else 'REJECTED'}",
                    got == want,
                    detail=(err or "accepted") + f" (expected {'ACCEPT' if want else 'REJECT'})")

        # idempotency — second call must be a clean no-op
        second_ok, second_err = True, ""
        try:
            upgrade(engine)
        except Exception as exc:
            second_ok, second_err = False, f"{type(exc).__name__}: {exc}"
        with engine.connect() as c:
            still = c.execute(text(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' "
                "AND table_name IN ('pool_definition','pool_instance','pool_rotation_cycle')"
            )).scalar()
            rows_kept = c.execute(text("SELECT count(*) FROM pool_instance")).scalar()
        _assert("19: upgrade(engine) is idempotent — second call is a clean no-op",
                second_ok and still == 3 and rows_kept == 3,
                detail=f"second call {'ok' if second_ok else second_err}; "
                       f"tables={still} (expected 3); pool_instance rows preserved="
                       f"{rows_kept} (expected 3, proving no drop/recreate)")

        # CONTROL C — the migration DDL with the WHERE clause removed.
        print("\n-- CONTROL C: migration DDL, WHERE clause removed --")
        ctrl_ddl = """
            CREATE TABLE zz_ctrl_migration_instance (
                id                  SERIAL PRIMARY KEY,
                league_id           INTEGER NOT NULL,
                season              INTEGER NOT NULL,
                week                INTEGER NOT NULL,
                phase               VARCHAR NOT NULL,
                rotation_cycle      INTEGER NOT NULL,
                definition_key      VARCHAR NOT NULL,
                slot                INTEGER NOT NULL,
                origin_instance_id  INTEGER
            )
        """
        ctrl_idx = ("CREATE UNIQUE INDEX uq_zz_ctrl_migration_cycle_fresh "
                    "ON zz_ctrl_migration_instance "
                    "(league_id, season, rotation_cycle, definition_key)")
        with engine.begin() as c:
            c.execute(text(ctrl_ddl))
            c.execute(text(ctrl_idx))
        created_control_tables.append("zz_ctrl_migration_instance")
        ctrl_md = MetaData()
        tC = Table("zz_ctrl_migration_instance", ctrl_md, autoload_with=engine)
        with engine.connect() as c:
            rsC = probe(c, lambda r: tC.insert().values(**r),
                        league_id=LEAGUE_ID, needs_fk_rows=False)
        _assert("20: CONTROL C - migration DDL without WHERE rejects M3 continuation",
                rsC["H3"][0] is False, detail=rsC["H3"][1] or "ACCEPTED (control did not bite)")
        _assert("21: CONTROL C - migration DDL without WHERE rejects M4 non-REGULAR",
                rsC["H4"][0] is False, detail=rsC["H4"][1] or "ACCEPTED (control did not bite)")

        # the predicate the migration actually used
        print(f"\n  migration _PARTIAL_PREDICATE = {_PARTIAL_PREDICATE!r}")
        _assert("22: migration predicate is character-identical to the ORM predicate",
                _PARTIAL_PREDICATE == PREDICATE,
                detail=f"migration={_PARTIAL_PREDICATE!r} orm={PREDICATE!r}")

        # The two schema sources must agree on SERVER defaults, not just on
        # columns. Column(default=...) is client-side and emits no DDL DEFAULT,
        # so without server_default a raw INSERT omitting the money columns
        # would succeed against the migration's schema and fail against the
        # ORM's. This asserts the DDL-level default directly, on whichever
        # schema is currently live (the migration's, at this point in the run).
        with engine.connect() as c:
            tx = c.begin()
            raw_ok, raw_err = True, ""
            try:
                c.execute(text(
                    f"INSERT INTO pool_instance ({base_cols}) VALUES "
                    f"({LEAGUE_ID}, {SEASON}, 92, 'REGULAR', {CYCLE + 99}, '{DKEY}', 2)"))
                tx.commit()
            except Exception as exc:
                tx.rollback()
                f = str(getattr(exc, "orig", exc)).strip().splitlines()
                raw_ok, raw_err = False, f"{type(exc).__name__}: {f[0] if f else ''}"
            defaults = None
            if raw_ok:
                defaults = c.execute(text(
                    "SELECT pot_cents, rollover_cents, settled FROM pool_instance "
                    "WHERE week = 92")).fetchone()
        _assert("23: server defaults exist in the DDL — raw INSERT omitting "
                "pot_cents/rollover_cents/settled succeeds and lands 0/0/false",
                raw_ok and defaults is not None and tuple(defaults) == (0, 0, False),
                detail=(f"pot_cents={defaults[0]} rollover_cents={defaults[1]} "
                        f"settled={defaults[2]}" if raw_ok and defaults
                        else raw_err or "no row"))

        # §C2 gives an explicit field list. Both schema sources must carry
        # exactly it — no more, no less. Checking the ORM model AND the live
        # migration-created table, because changing only one recreates the
        # divergence the server_default fix cured, in the opposite direction.
        C2_FIELDS = [
            "id", "league_id", "season", "week", "phase", "rotation_cycle",
            "definition_key", "slot", "pot_cents", "rollover_cents",
            "origin_instance_id", "settled", "settled_at",
        ]
        # S4-P1 additions, enumerated rather than folded into C2_FIELDS so the
        # governed baseline stays visible and any FURTHER unmanaged growth still
        # fails this assertion.
        #
        # Authority: POR §6.2's behaviour table distinguishes three reportable
        # end states — "Unsettled", "Settled" and "Settled, distributed" — and
        # binds that "no surface may report the pot as settled, completed, or
        # distributed" on a fail-closed classification. `settled` alone cannot
        # carry that three-way distinction, so the classification and the
        # distributed amount are recorded on the row, in the same transaction as
        # the posting they describe. Scope §0: "Where the two disagree, the POR
        # governs and this document is wrong" — and §C2 is headed "Minimal
        # design", not an exhaustive prohibition.
        S4P1_FIELDS = ["settlement_classification", "distributed_cents"]
        EXPECTED = C2_FIELDS + S4P1_FIELDS

        model_cols = [c.name for c in PoolInstance.__table__.columns]
        live_cols = [c["name"] for c in inspect(engine).get_columns("pool_instance")]
        _assert("24: pool_instance carries exactly §C2's 13 fields plus the 2 "
                "governed S4-P1 additions, in BOTH schema sources (ORM model "
                "and the live migration-created table)",
                sorted(model_cols) == sorted(EXPECTED)
                and sorted(live_cols) == sorted(EXPECTED),
                detail=f"model={len(model_cols)} cols, live={len(live_cols)} cols, "
                       f"expected={len(EXPECTED)} (C2 {len(C2_FIELDS)} + S4-P1 "
                       f"{len(S4P1_FIELDS)}); "
                       f"model-only={sorted(set(model_cols) - set(EXPECTED))} "
                       f"live-only={sorted(set(live_cols) - set(EXPECTED))} "
                       f"missing={sorted(set(EXPECTED) - set(model_cols))}")
        _assert("24a: the two schema sources agree with each other exactly "
                "(the drift this assertion exists to catch)",
                sorted(model_cols) == sorted(live_cols),
                detail=f"model-only={sorted(set(model_cols) - set(live_cols))} "
                       f"live-only={sorted(set(live_cols) - set(model_cols))}")

    finally:
        # Guaranteed teardown of every control table this file created.
        try:
            with engine.begin() as c:
                for t in created_control_tables:
                    c.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] control-table cleanup failed: {exc}")

    with engine.connect() as c:
        tables_at_end = c.execute(text(PUBLIC_COUNT)).scalar()
    _assert("25: public-schema table count returned to its starting value",
            tables_at_end == tables_at_start,
            detail=f"start={tables_at_start} end={tables_at_end}")


if __name__ == "__main__":
    try:
        main(tdb)
    finally:
        tdb.teardown()

    print()
    if _failures:
        print(f"RESULT: {len(_failures)} assertion(s) FAILED")
        for label in _failures:
            print(f"  - {label}")
        sys.exit(1)
    print("RESULT: all pool rotation schema assertions PASSED")