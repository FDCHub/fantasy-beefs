"""Sprint 5 migration — derived historical model parameters.

Sprint 4 built the three projection models IPRM needs and left every one of them
MODEL_UNRESOLVED, because a rate with no measured sample behind it is a number
picked to make a test pass. This table is where the measured samples live.

    CREATE TABLE provider_historical_rate (
        id, provider, model_type, model_version, entity_type, entity_key,
        position, season_window, as_of, numerator, denominator, rate,
        sample_size, source_kind, parameters, fingerprint, generated_at,
        created_at
    )

── DERIVED PARAMETERS, NOT RAW HISTORY ─────────────────────────────────────

BALLDONTLIE's terms permit raw retention outright (§6 grants copy, cache, store
and archive; §17 preserves it after termination), so this is a design choice
rather than a licensing one. Pricing needs a rate and a sample size; it does not
need forty thousand play rows, and a table nothing queries is still a table
every backup, migration and reader has to carry. Raw payloads stay in the
fixture corpus, where deterministic certification actually needs them.

── ADDITIVE, AND NOTHING EXISTING IS READ ──────────────────────────────────

A new table. No column is added to, renamed in or dropped from any existing
one. `projections.projected_points` is untouched for the third sprint running,
`provider_component_projection` is untouched, and no economic table is read.

── APPEND-ONLY, KEYED BY FINGERPRINT ───────────────────────────────────────

The unique key ends in `fingerprint`, which is a digest over the derivation's
inputs and outputs. Re-deriving unchanged history reproduces the digest and
collides, so a refresh that learned nothing writes nothing. A provider
CORRECTION produces a different digest and lands beside its predecessor, which
is what lets a wager priced a week ago still be replayed against the parameters
that priced it. Frozen inputs are never mutated.

Idempotent: a schema already carrying the table is observed and left alone.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from db.schema import engine  # noqa: E402

TABLE = "provider_historical_rate"


def upgrade() -> list[str]:
    dialect = engine.dialect.name
    pk = ("SERIAL PRIMARY KEY" if dialect == "postgresql"
          else "INTEGER PRIMARY KEY AUTOINCREMENT")
    timestamp_type = ("TIMESTAMP WITH TIME ZONE" if dialect == "postgresql"
                      else "TIMESTAMP")
    json_type = "JSONB" if dialect == "postgresql" else "TEXT"

    with engine.begin() as connection:
        if TABLE in set(inspect(connection).get_table_names()):
            return [f"{TABLE} already exists"]
        connection.execute(text(f"""
            CREATE TABLE {TABLE} (
                id            {pk},
                provider      VARCHAR NOT NULL,
                model_type    VARCHAR NOT NULL,
                model_version VARCHAR NOT NULL,
                entity_type   VARCHAR NOT NULL,
                entity_key    VARCHAR NOT NULL,
                position      VARCHAR,
                season_window VARCHAR NOT NULL,
                as_of         {timestamp_type} NOT NULL,
                numerator     DOUBLE PRECISION NOT NULL,
                denominator   DOUBLE PRECISION NOT NULL,
                rate          DOUBLE PRECISION NOT NULL,
                sample_size   INTEGER NOT NULL,
                source_kind   VARCHAR NOT NULL,
                parameters    {json_type} NOT NULL,
                fingerprint   VARCHAR(64) NOT NULL,
                generated_at  {timestamp_type} NOT NULL,
                created_at    {timestamp_type} NOT NULL,
                -- ON ONE LINE: SQLAlchemy's SQLite inspector recovers unique
                -- constraints by parsing this DDL, and a wrapped column list
                -- defeats that parse (the constraint is still enforced, but a
                -- fresh and a migrated schema then appear to differ).
                CONSTRAINT uq_historical_rate_observation UNIQUE (provider, model_type, model_version, entity_type, entity_key, season_window, as_of, fingerprint),
                CONSTRAINT ck_historical_rate_entity
                    CHECK (entity_type IN ('PLAYER', 'TEAM', 'POSITION', 'LEAGUE')),
                CONSTRAINT ck_historical_rate_sample
                    CHECK (sample_size >= 0 AND denominator >= 0)
            )
        """))
        connection.execute(text(
            f"CREATE INDEX ix_historical_rate_lookup ON {TABLE} "
            f"(provider, model_type, entity_type, entity_key, as_of)"))
        connection.execute(text(
            f"CREATE INDEX ix_historical_rate_model ON {TABLE} "
            f"(provider, model_type, model_version)"))
    return [f"created {TABLE}",
            "created uq_historical_rate_observation (append-only guard)",
            "created ix_historical_rate_lookup",
            "created ix_historical_rate_model"]


if __name__ == "__main__":
    for line in upgrade():
        print("  - " + line)
