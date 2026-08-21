"""
migrations/add_pool_definition_public_question.py — Pool Catalog Rev 1.4 §3.

WHAT IT DOES, AND NOTHING ELSE:

    pool_definition.public_question    VARCHAR NULL

ONE NULLABLE COLUMN. That is the entire change.

WHY A MIGRATION AT ALL, WHEN THE RENAME NEEDS NONE. Rev 1.4 changes two
presentation fields on the 64 runtime-eligible definitions: `display_name`, which
already has a column and which `betting.pool_catalog.seed_definitions` rewrites
in place on every re-seed, and `public_question`, which is new. So the branded
naming half of the revision ships as a re-seed and touches no schema; only the
question needs a column, and this is it.

ADDITIVE, NON-DESTRUCTIVE, AND VALID FOR EVERY EXISTING ROW.

  · Nothing is dropped, renamed, retyped or relaxed. No governed column changes
    nullability. No existing row is read, updated or deleted by this migration.
  · The column is NULLABLE WITH NO DEFAULT and no backfill. Every one of the 80
    existing `pool_definition` rows is valid the instant the ALTER lands,
    carrying NULL, which reads as "no question seeded yet" — the truth at that
    moment. The 64 questions arrive with the ordinary Rev 1.4 re-seed, through
    the same idempotent seeder that has always written this table.
  · NULL IS ALSO A PERMANENT PRODUCT STATE, not just a pre-seed one. POR Rev 1.4
    §7 deliberately leaves the 16 definitions no league can currently draw —
    #7, #46 and #85 BLOCKED, plus thirteen whose source mapping is incomplete —
    without a question, so a reader must handle NULL forever and the column can
    never be tightened to NOT NULL on the strength of "they are all populated
    now".
  · A deployment rolled back to pre-Rev-1.4 code simply never selects the
    column. The values sit there, harmless, and are still correct if the code
    rolls forward again.
  · No Ledger, wager, escrow, pot, claim, championship, team or economic value
    is touched, and no Pool's settlement basis is reachable from here:
    `public_question` carries NO settlement authority whatsoever (POR Rev 1.4
    §3.2). Where it and a `predicate`, `metric_expression` or
    `threshold_condition` could be read as disagreeing, the governed field wins
    and the question is the defect.

    python migrations/add_pool_definition_public_question.py

Idempotent: `ADD COLUMN` is guarded by an inspector read, so a second run
reports there is nothing to do rather than failing on a duplicate column.

BOTH DIALECTS TAKE THE SAME STATEMENT. Adding a nullable column with no default
is one of the few ALTERs SQLite performs without rebuilding the table, so
PostgreSQL — the production target — and SQLite — the test path — run identical
DDL here and there is no dialect branch to get wrong. SQLite still builds this
schema from `db.schema` on a fresh database and therefore proves nothing about
PostgreSQL's ALTER behaviour; the PostgreSQL execution is a separate, explicit
certification (see `test_pg_cert1_migrations.py`).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text                               # noqa: E402

from db.schema import engine as _default_engine                    # noqa: E402

#: Kept beside the DDL rather than imported, so the migration is readable as a
#: single artifact and does not change meaning when the model changes.
TABLE = "pool_definition"
COLUMN = "public_question"


def upgrade(engine=None) -> list[str]:
    """Apply the change. Returns what it did, for the caller to print.

    `engine` is optional and defaults to the application's. `migrations.run`
    calls `upgrade()` with no argument, which is the production path; a
    certification suite that has rebuilt this table from the historical
    migrations passes its own bound engine so the DDL is exercised against the
    database it just built rather than against whichever one was imported first.
    """
    engine = engine if engine is not None else _default_engine
    done: list[str] = []

    with engine.begin() as connection:
        inspector = inspect(connection)

        if TABLE not in inspector.get_table_names():
            # A database with no catalog table is a fresh build, which
            # `db.schema.create_all` will produce complete and already carrying
            # the column. Refusing here would fail readiness on exactly the
            # deployment that needs no migration at all.
            return [f"{TABLE} does not exist — fresh build, nothing to alter"]

        columns = {c["name"] for c in inspector.get_columns(TABLE)}
        if COLUMN in columns:
            done.append(f"{TABLE}.{COLUMN} already exists")
        else:
            connection.execute(text(
                f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} VARCHAR"))
            done.append(f"added {TABLE}.{COLUMN}")

    return done or ["nothing to do — already applied"]


if __name__ == "__main__":
    for line in upgrade():
        print(f"  · {line}")
    print("Pool Catalog Rev 1.4 public_question migration complete.")
