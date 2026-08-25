"""Sprint 2B migration — provider component projection snapshots.

WP2 gave this product a BALLDONTLIE client that produces normalized component
projections. Nothing could persist them: `projections` holds one SCALAR
`projected_points` per (player, week, season, source), which is a league's
fantasy points AFTER scoring, and a component projection is the forty-odd
upstream quantities BEFORE it.

    CREATE TABLE provider_component_projection (
        id, provider, provider_player_key, player_id -> players.id,
        season, week, provider_game_id, nfl_team, position,
        source_kind, provenance, provider_record_id, vocabulary_version,
        components, components_present, observation_digest,
        observed_at, captured_at, created_at
    )

── ADDITIVE, AND `projections` IS NOT TOUCHED ──────────────────────────────

Not one existing table is altered, not one row is read, and
`projections.projected_points` keeps its column, its meaning, its
yahoo|espn|fantasypros source vocabulary and all twelve of its readers —
`odds/monte_carlo.py` and `betting/bet_engine.py` among them. That is the whole
point of a second table: the path that prices money keeps working exactly as it
did, and the new material sits beside it until WP4's evaluator can convert it.

── THE TWO STORAGE DECISIONS, AND WHY EACH IS THE SMALL ONE ────────────────

COMPONENTS ARE ONE JSON DOCUMENT. The vocabulary is the provider's and moves
when the provider moves; nothing reads a single component in isolation, because
CSPS evaluates a whole subject-week under a whole rule set. A row per component
would be ~40 rows per subject-week plus a dimension table to keep the names
honest, and would turn "the provider added a category" into a migration. JSON on
SQLite, JSONB on PostgreSQL, matching what `projection_input_snapshot` and
`pool_definition.required_stats` already do in this schema.

HISTORY IS APPEND-ONLY, AND DE-DUPLICATED BY DIGEST. A projection is a forecast
that changes, and BALLDONTLIE publishes no point-in-time history at all — Phase 0
measured `?date=2025-09-03` returning zero rows. So this table is the only place
that can ever hold what was knowable before kickoff, and it must not overwrite.
`uq_component_projection_observation` on
(provider, player_id, season, week, observation_digest) is what keeps that from
becoming duplication: the digest covers the identity and the normalized payload
but NOT `captured_at`, so re-fetching an unchanged projection collides and is
skipped, while a projection that really moved lands beside its predecessor.

Idempotent: a schema already carrying the table is observed and left alone.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from db.schema import engine  # noqa: E402

TABLE = "provider_component_projection"


def upgrade() -> list[str]:
    dialect = engine.dialect.name
    pk = ("SERIAL PRIMARY KEY" if dialect == "postgresql"
          else "INTEGER PRIMARY KEY AUTOINCREMENT")
    timestamp_type = ("TIMESTAMP WITH TIME ZONE" if dialect == "postgresql"
                      else "TIMESTAMP")
    # JSONB on PostgreSQL for the same reason the model declares the variant:
    # it is the type this product already stores structured provider material
    # in. SQLite has no JSON type and stores the document as TEXT, which is what
    # SQLAlchemy's JSON() does there too — so both dialects round-trip the same
    # Python object through the same model.
    json_type = "JSONB" if dialect == "postgresql" else "TEXT"

    with engine.begin() as connection:
        if TABLE in set(inspect(connection).get_table_names()):
            return [f"{TABLE} already exists"]
        connection.execute(text(f"""
            CREATE TABLE {TABLE} (
                id                  {pk},
                provider            VARCHAR NOT NULL,
                provider_player_key VARCHAR NOT NULL,
                player_id           INTEGER NOT NULL REFERENCES players (id),
                season              INTEGER NOT NULL,
                week                INTEGER NOT NULL,
                provider_game_id    VARCHAR,
                nfl_team            VARCHAR(4),
                position            VARCHAR,
                source_kind         VARCHAR NOT NULL,
                provenance          VARCHAR NOT NULL,
                provider_record_id  VARCHAR,
                vocabulary_version  VARCHAR NOT NULL,
                components          {json_type} NOT NULL,
                components_present  {json_type} NOT NULL,
                observation_digest  VARCHAR(64) NOT NULL,
                observed_at         {timestamp_type} NOT NULL,
                captured_at         {timestamp_type} NOT NULL,
                created_at          {timestamp_type} NOT NULL,
                -- ON ONE LINE DELIBERATELY. SQLAlchemy's SQLite inspector
                -- recovers unique constraints by parsing this DDL text, and a
                -- wrapped column list defeats that parse: the constraint is
                -- still ENFORCED, but `get_unique_constraints` reports none, so
                -- a fresh schema and a migrated one appear to differ when they
                -- do not. PostgreSQL reads its catalogs and never cared.
                CONSTRAINT uq_component_projection_observation UNIQUE (provider, player_id, season, week, observation_digest),
                CONSTRAINT ck_component_projection_provenance
                    CHECK (provenance IN ('LIVE', 'FIXTURE_SYNTHETIC'))
            )
        """))
        connection.execute(text(
            f"CREATE INDEX ix_component_projection_lookup "
            f"ON {TABLE} (provider, player_id, season, week, observed_at)"))
        connection.execute(text(
            f"CREATE INDEX ix_component_projection_week "
            f"ON {TABLE} (provider, season, week)"))
    return [f"created {TABLE}",
            "created uq_component_projection_observation (append-only guard)",
            "created ix_component_projection_lookup",
            "created ix_component_projection_week"]


if __name__ == "__main__":
    for line in upgrade():
        print("  - " + line)
