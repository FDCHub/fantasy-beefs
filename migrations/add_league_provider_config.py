"""Sprint 7 migration — per-league provider and simulation-model selection.

    CREATE TABLE league_provider_config (
        id, league_id, season,
        projection_source, factual_source, simulation_model,
        note, updated_by, created_at, updated_at
    )

── ADDITIVE, AND IT CHANGES NOTHING BY EXISTING ────────────────────────────

A new table. No column is added to, renamed in or dropped from any existing
one; `leagues.provider` is untouched, `leagues.projection_source` is untouched,
`projections` is untouched, and no economic table is read or written. Applying
this migration to a live database changes no behaviour at all, because
behaviour follows from a ROW, and this creates none.

That is the point. A league-season with no row keeps its legacy projections,
its legacy factual path and sim-v1, exactly as before. Activation is a
deliberate INSERT by an operator, one league at a time, and rollback is an
UPDATE of that same row rather than a deletion of anything BALLDONTLIE
produced.

── THE VOCABULARIES ARE ENFORCED BY THE ENGINE ─────────────────────────────

Three CHECK constraints close three vocabularies: a source is `legacy` or
`balldontlie`, a model is `sim-v1` or `sim-v2`, and there is no `auto`. A
misconfigured league cannot be stored, so it cannot silently fall back at read
time — the failure lands at write, where an operator is present to see it.

`legacy` is a real value rather than a placeholder: `leagues.projection_source`
already chooses between `yahoo`, `espn` and `fantasypros` for the SCALAR
`projections` table, and BALLDONTLIE writes components rather than scalars. The
two selectors compose instead of competing.

Idempotent: a schema already carrying the table is observed and left alone.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from db.schema import engine  # noqa: E402

TABLE = "league_provider_config"


def upgrade() -> list[str]:
    dialect = engine.dialect.name
    pk = ("SERIAL PRIMARY KEY" if dialect == "postgresql"
          else "INTEGER PRIMARY KEY AUTOINCREMENT")
    timestamp_type = ("TIMESTAMP WITH TIME ZONE" if dialect == "postgresql"
                      else "TIMESTAMP")

    with engine.begin() as connection:
        inspector = inspect(connection)
        if TABLE in set(inspector.get_table_names()):
            # ALREADY PRESENT — BUT CHECK THE SPRINT 7B COLUMN.
            #
            # This migration is uncommitted and has been applied to no
            # production database, so in practice the branch below runs only
            # against a schema an earlier run of THIS file created. It is here
            # anyway because "the table exists" and "the table is current" are
            # different facts, and a migration that conflates them leaves a
            # half-built schema reporting success.
            columns = {c["name"] for c in inspector.get_columns(TABLE)}
            if "scoring_profile_id" in columns:
                return [f"{TABLE} already exists"]
            connection.execute(text(
                f"ALTER TABLE {TABLE} ADD COLUMN scoring_profile_id VARCHAR"))
            return [f"{TABLE} already existed; added scoring_profile_id"]
        connection.execute(text(f"""
            CREATE TABLE {TABLE} (
                id                {pk},
                league_id         INTEGER NOT NULL REFERENCES leagues(id),
                season            INTEGER NOT NULL,
                projection_source VARCHAR NOT NULL,
                factual_source    VARCHAR NOT NULL,
                simulation_model  VARCHAR NOT NULL,
                -- SPRINT 7B. Nullable on purpose: a league with no profile
                -- named here cannot be scored by CSPS, and the product refuses
                -- to price it rather than choosing a rule set on its behalf.
                scoring_profile_id VARCHAR,
                note              TEXT,
                updated_by        VARCHAR,
                created_at        {timestamp_type} NOT NULL,
                updated_at        {timestamp_type} NOT NULL,
                -- ON ONE LINE: SQLAlchemy's SQLite inspector recovers unique
                -- constraints by parsing this DDL, and a wrapped column list
                -- defeats that parse, which makes a fresh and a migrated schema
                -- appear to differ even though both enforce it.
                CONSTRAINT uq_lpc_league_season UNIQUE (league_id, season),
                CONSTRAINT ck_lpc_projection_source
                    CHECK (projection_source IN ('legacy', 'balldontlie')),
                CONSTRAINT ck_lpc_factual_source
                    CHECK (factual_source IN ('legacy', 'balldontlie')),
                CONSTRAINT ck_lpc_simulation_model
                    CHECK (simulation_model IN ('sim-v1', 'sim-v2'))
            )
        """))
        connection.execute(text(
            f"CREATE INDEX ix_lpc_league_season ON {TABLE} "
            f"(league_id, season)"))
        return [f"created {TABLE}; created uq_lpc_league_season "
                f"(one selection per league-season); created "
                f"ix_lpc_league_season"]
