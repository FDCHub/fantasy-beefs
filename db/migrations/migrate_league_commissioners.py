"""
db/migrations/migrate_league_commissioners.py — create the
league_commissioners table.

UPGRADE PATH ONLY. A clean install never calls this: db.schema.create_all()
(and the Postgres test harness) build league_commissioners directly from the
LeagueCommissioner model. This module exists solely to bring an ALREADY-DEPLOYED
database up to the model.

Additive and idempotent. Creates the table, its three named foreign keys, the
named unique constraint and the named source check constraint if they are
absent, and DROPS NOTHING. Safe to run repeatedly; safe on an empty database;
safe on a database that already holds users and leagues.

IT BACKFILLS NOTHING. No authority row is invented from User.team_id, from
audit rows, from commissioner-created records, from emails, from names, or from
the global User.role. An empty table after migration is the correct outcome:
authority must be granted explicitly, not inferred.

Follows migrate_season_allocation.py: the work lives in run_migration(), not
under the main guard, so it can be imported, tested and composed.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from db.schema import LeagueCommissioner, engine

TABLE_NAME  = "league_commissioners"
UQ_NAME     = "uq_league_commissioner_league_user"
CK_NAME     = "ck_league_commissioner_source"
FK_LEAGUE   = "fk_league_commissioner_league"
FK_USER     = "fk_league_commissioner_user"
FK_ASSIGNER = "fk_league_commissioner_assigned_by"


def run_migration() -> dict:
    """Create league_commissioners and its named constraints if missing.

    Returns what this run actually did:
        {"table_created": bool, "constraints_added": [...]}
    A second run reports table_created False and an empty list. Drops nothing.
    """
    inspector = inspect(engine)
    table_existed = TABLE_NAME in inspector.get_table_names()

    # checkfirst=True: creates the table WITH all three named FKs, the named
    # unique constraint and the named check constraint straight from the model,
    # and is a no-op when the table already exists.
    LeagueCommissioner.__table__.create(engine, checkfirst=True)

    added: list[str] = []

    if table_existed:
        # The table predates this run and may have come from an older,
        # incomplete migration, so verify each named constraint is present and
        # add whichever are missing.
        #
        # SQLite cannot ALTER TABLE ADD CONSTRAINT. It is not a deployment
        # target for this upgrade path (production is Postgres), and on the
        # clean-install path the model already carries every constraint, so the
        # repair block is Postgres-only by design.
        if engine.dialect.name != "sqlite":
            inspector = inspect(engine)

            existing_uq = {u["name"] for u in inspector.get_unique_constraints(TABLE_NAME)}
            existing_fk = {f["name"] for f in inspector.get_foreign_keys(TABLE_NAME)}
            try:
                existing_ck = {c["name"] for c in inspector.get_check_constraints(TABLE_NAME)}
            except NotImplementedError:          # dialect without check introspection
                existing_ck = set()

            with engine.begin() as conn:
                if UQ_NAME not in existing_uq:
                    conn.execute(text(
                        f'ALTER TABLE {TABLE_NAME} ADD CONSTRAINT {UQ_NAME} '
                        f'UNIQUE (league_id, user_id)'
                    ))
                    added.append(UQ_NAME)

                if CK_NAME not in existing_ck:
                    conn.execute(text(
                        f"ALTER TABLE {TABLE_NAME} ADD CONSTRAINT {CK_NAME} "
                        f"CHECK (source IN ('yahoo_sync','local_grant','bootstrap'))"
                    ))
                    added.append(CK_NAME)

                for fk_name, col, target in (
                    (FK_LEAGUE,   "league_id",           "leagues(id)"),
                    (FK_USER,     "user_id",             "users(id)"),
                    (FK_ASSIGNER, "assigned_by_user_id", "users(id)"),
                ):
                    if fk_name not in existing_fk:
                        conn.execute(text(
                            f'ALTER TABLE {TABLE_NAME} ADD CONSTRAINT {fk_name} '
                            f'FOREIGN KEY ({col}) REFERENCES {target}'
                        ))
                        added.append(fk_name)

    return {"table_created": not table_existed, "constraints_added": added}


if __name__ == "__main__":
    result = run_migration()
    if result["table_created"]:
        print(f"created table {TABLE_NAME} with all named constraints")
    else:
        print(f"table {TABLE_NAME} already present")
    if result["constraints_added"]:
        print("added missing constraints: " + ", ".join(result["constraints_added"]))
    else:
        print("no constraints needed adding")
    print("nothing was dropped; no authority row was backfilled")
