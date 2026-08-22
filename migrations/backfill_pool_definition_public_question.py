"""
migrations/backfill_pool_definition_public_question.py — Pool Catalog Rev 1.4 §3.

WHAT IT DOES, AND NOTHING ELSE:

    pool_definition.public_question    ← the governed catalog's sentence,
                                          matched on `pool_definition.key`

ONE COLUMN, ON ROWS THAT ALREADY EXIST. No table is created, no column is added,
no row is inserted and no row is deleted.

── WHY THIS MIGRATION EXISTS AT ALL ─────────────────────────────────────────

Migration 0008 added the column and deliberately performed NO backfill; its own
docstring records the reasoning — "the 64 questions arrive with the ordinary
Rev 1.4 re-seed, through the same idempotent seeder that has always written this
table". That is true of every path that RE-SEEDS the catalog: a fresh database,
a locally rebuilt one, `demo.seed`, and every test fixture. It is NOT true of a
deployed database.

MEASURED ON THE DEPLOYED RC4 BUILD. The release command is
`python -m migrations.run` (railway.toml `preDeployCommand`) and nothing in that
path calls `betting.pool_catalog.seed_definitions`. A database whose
`pool_definition` rows were written BEFORE Rev 1.4 therefore took the ALTER and
kept eighty NULLs, and Play drew `Question unavailable` on four active drawable
Pools — the client refusing, correctly, to invent a sentence the catalog was
supposed to supply. The defect was never in the read model, the serializer or
the client; it was that the governed values had no way to reach an existing
database.

So the re-seed's ONE presentation field gets a migration of its own, which is
the only artifact a release actually runs.

── DETERMINISTIC, AND THE CATALOG IS THE SOLE SOURCE ────────────────────────

  · The value written is `PoolDefinitionSpec.public_question` from
    `betting.pool_catalog.load_catalog()` — the same governed artifact
    `seed_definitions` writes from, loaded through the same validating loader.
    Nothing is composed, paraphrased or derived here, and a definition the
    catalog gives no question keeps NULL.
  · Rows are matched on `key`, which POR §1.8 fixes as the immutable identity.
    NO pool identity, catalog number, display name, predicate, metric,
    threshold, eligibility or settlement field is read or written.
  · A key in the catalog with no row in the database is SKIPPED, not inserted.
    Creating catalog rows is the seeder's job and doing it here would let a
    release add definitions to a league's rotation as a side effect of a
    presentation fix.
  · Idempotent and re-runnable: it writes only where the stored value DIFFERS
    from the catalog's, so a second run reports zero updates.

── WHAT IT CANNOT AFFECT ────────────────────────────────────────────────────

`public_question` carries NO settlement authority whatsoever (POR Rev 1.4 §3.2).
It is not read by any evaluator, selector, rotation, claim, pot, escrow, ledger
or championship path — `spec_from_row` carries it onto the frozen spec purely so
the read model can publish it. The 16 non-drawable definitions keep NULL by
design (§7), so the column can never be tightened to NOT NULL.

    python migrations/backfill_pool_definition_public_question.py

BOTH DIALECTS TAKE THE SAME STATEMENT — a parameterised UPDATE of one VARCHAR
column, with no DDL at all, so PostgreSQL and SQLite run identical SQL.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text                               # noqa: E402

from db.schema import engine as _default_engine                    # noqa: E402

#: Kept beside the SQL rather than imported from the model, so the migration is
#: readable as a single artifact and does not change meaning when the model does.
TABLE = "pool_definition"
COLUMN = "public_question"


def upgrade(engine=None) -> list[str]:
    """Apply the change. Returns what it did, for the caller to print."""
    engine = engine if engine is not None else _default_engine
    done: list[str] = []

    with engine.begin() as connection:
        inspector = inspect(connection)

        if TABLE not in inspector.get_table_names():
            # A database with no catalog table is a fresh build; `create_all`
            # produces the column and the ordinary seed writes the values.
            return [f"{TABLE} does not exist — fresh build, nothing to backfill"]

        columns = {c["name"] for c in inspector.get_columns(TABLE)}
        if COLUMN not in columns:
            # 0008 is ordered before this one and adds it. Reaching here means
            # the manifest was run out of order; say so rather than writing to a
            # column that is not there.
            return [f"{TABLE}.{COLUMN} is absent — migration 0008 has not run"]

        # IMPORTED HERE, NOT AT MODULE SCOPE. `migrations.run` imports every
        # manifest module to apply it, and the catalog loader reads and
        # validates a JSON artifact — work that must happen when this migration
        # runs, not when the runner enumerates what to run.
        from betting.pool_catalog import load_catalog

        catalog = load_catalog()
        governed = {
            spec.key: spec.public_question
            for spec in catalog.definitions
            if spec.public_question
        }

        stored = {
            row[0]: row[1] for row in connection.execute(
                text(f"SELECT key, {COLUMN} FROM {TABLE}")).all()
        }

        written = 0
        for key, question in governed.items():
            if key not in stored:
                continue                    # not this database's to create
            if stored[key] == question:
                continue                    # already governed and identical
            connection.execute(
                text(f"UPDATE {TABLE} SET {COLUMN} = :q WHERE key = :k"),
                {"q": question, "k": key},
            )
            written += 1

        absent = sorted(k for k in governed if k not in stored)
        done.append(f"catalog carries {len(governed)} governed questions")
        done.append(f"{written} row(s) brought onto the governed sentence")
        if absent:
            done.append(
                f"{len(absent)} catalog key(s) have no row here and were not "
                f"inserted (first: {absent[0]})")

    return done


if __name__ == "__main__":
    for line in upgrade():
        print(f"  · {line}")
    print("Pool Catalog Rev 1.4 public_question backfill complete.")
