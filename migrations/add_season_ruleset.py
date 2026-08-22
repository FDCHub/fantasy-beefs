"""WP-1 migration — the season-level ruleset era gate.

Creates ONE additive table:

    league_season_ruleset

NOTHING IS BACKFILLED, AND THAT IS THE POINT. An existing league-season has no
row here after this migration, and `ruleset.resolve_ruleset_version` reads that
absence as `RULESET_LEGACY`. Every historical season therefore keeps its
original scoring, economy, lifecycle and reconciliation rules without a single
row being written, a single frozen score being recomputed, or a single paid
award being revisited.

No existing table is altered. No existing row is touched. A rollback to the
prior release simply ignores this table: the era gate reads absence as legacy,
which is what a pre-WP-1 build assumes anyway.

Fresh databases get the table from SQLAlchemy metadata (`db.schema` declares
`LeagueSeasonRuleset` against `Base`), so `create_all` builds it with no
explicit registration step. This migration is for an EXISTING database.

Idempotent: running it again observes the table and makes no change.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from db.schema import engine  # noqa: E402

TABLE = "league_season_ruleset"


def upgrade() -> list[str]:
    dialect = engine.dialect.name
    pk = ("SERIAL PRIMARY KEY" if dialect == "postgresql"
          else "INTEGER PRIMARY KEY AUTOINCREMENT")
    timestamp_type = ("TIMESTAMP WITH TIME ZONE" if dialect == "postgresql"
                      else "TIMESTAMP")

    with engine.begin() as connection:
        if TABLE in set(inspect(connection).get_table_names()):
            return [f"{TABLE} already exists"]
        connection.execute(text(f"""
            CREATE TABLE {TABLE} (
                id              {pk},
                league_id       INTEGER NOT NULL REFERENCES leagues (id),
                season          INTEGER NOT NULL,
                ruleset_version INTEGER NOT NULL,
                stamped_at      {timestamp_type} NOT NULL,
                CONSTRAINT uq_lsr_league_season UNIQUE (league_id, season),
                CONSTRAINT ck_lsr_version_positive CHECK (ruleset_version >= 1)
            )
        """))
    return [f"created {TABLE}"]


if __name__ == "__main__":
    for line in upgrade():
        print(f"  · {line}")
