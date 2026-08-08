"""
db/migrations/migrate_season_allocation.py — create the season_allocation table.

UPGRADE PATH ONLY. A clean install never calls this: db.schema.create_all()
(and the Postgres test harness) build season_allocation directly from the
SeasonAllocation model. This module exists solely to bring an ALREADY-DEPLOYED
database up to the model.

Additive and idempotent. Creates the table, both named foreign keys and the
named unique constraint if they are absent, and DROPS NOTHING. Safe to run
repeatedly; safe to run against a database where the table already exists.

The work lives in run_migration(), NOT in `if __name__ == "__main__":`.
db/migrations/migrate_ledger_entries.py puts its entire body under the main
guard, so importing it does nothing and it cannot be called, tested or
composed — that defect is deliberately not copied here. The main guard below
only calls run_migration() and prints; it holds no logic of its own.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from db.schema import SeasonAllocation, engine

TABLE_NAME = "season_allocation"
UQ_NAME    = "uq_season_allocation_league_team_season"
FK_LEAGUE  = "fk_season_allocation_league"
FK_TEAM    = "fk_season_allocation_team"


def run_migration() -> dict:
    """Create season_allocation and its named constraints if missing.

    Returns a dict of what this run actually did, so a caller (or the main
    guard) can report it: {"table_created": bool, "constraints_added": [...]}.
    Idempotent — a second run reports nothing done. Drops nothing.
    """
    inspector = inspect(engine)
    table_existed = TABLE_NAME in inspector.get_table_names()

    # checkfirst=True: creates the table WITH both named FKs and the named
    # unique constraint straight from the model, and is a no-op if it exists.
    SeasonAllocation.__table__.create(engine, checkfirst=True)

    added: list[str] = []

    if table_existed:
        # The table predates this run. It may have been created by an older,
        # incomplete migration, so verify the named constraints are actually
        # present and add whichever are missing.
        #
        # SQLite cannot ALTER TABLE ADD CONSTRAINT at all. It is also not a
        # deployment target for this upgrade path (production is Postgres),
        # and on the clean-install path the model already carries every
        # constraint — so the repair below is Postgres-only by design.
        if engine.dialect.name == "sqlite":
            return {"table_created": False, "constraints_added": [], "skipped_repair": "sqlite"}

        inspector = inspect(engine)
        existing_uq = {c.get("name") for c in inspector.get_unique_constraints(TABLE_NAME)}
        existing_fk = {c.get("name") for c in inspector.get_foreign_keys(TABLE_NAME)}

        statements: list[tuple[str, str]] = []
        if UQ_NAME not in existing_uq:
            statements.append((UQ_NAME, (
                f"ALTER TABLE {TABLE_NAME} ADD CONSTRAINT {UQ_NAME} "
                f"UNIQUE (league_id, team_id, season)"
            )))
        if FK_LEAGUE not in existing_fk:
            statements.append((FK_LEAGUE, (
                f"ALTER TABLE {TABLE_NAME} ADD CONSTRAINT {FK_LEAGUE} "
                f"FOREIGN KEY (league_id) REFERENCES leagues (id)"
            )))
        if FK_TEAM not in existing_fk:
            statements.append((FK_TEAM, (
                f"ALTER TABLE {TABLE_NAME} ADD CONSTRAINT {FK_TEAM} "
                f"FOREIGN KEY (team_id) REFERENCES teams (id)"
            )))

        if statements:
            with engine.begin() as conn:
                for name, sql in statements:
                    conn.execute(text(sql))
                    added.append(name)

    return {"table_created": not table_existed, "constraints_added": added}


if __name__ == "__main__":
    result = run_migration()
    if result["table_created"]:
        print(f"{TABLE_NAME} table created (with {UQ_NAME}, {FK_LEAGUE}, {FK_TEAM}).")
    else:
        print(f"{TABLE_NAME} table already existed — nothing created.")
    if result.get("skipped_repair"):
        print(f"Constraint repair skipped: {result['skipped_repair']} cannot ALTER TABLE ADD CONSTRAINT.")
    elif result["constraints_added"]:
        print(f"Constraints added: {', '.join(result['constraints_added'])}")
    else:
        print("All named constraints already present — nothing added.")
    print("Migration complete. Nothing was dropped.")
