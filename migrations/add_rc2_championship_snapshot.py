"""migrations/add_rc2_championship_snapshot.py — RC2 championship freeze.

Creates the two additive tables that preserve the FantasyStakes Championship
standings at the Yahoo regular-season/postseason boundary:

    fantasystakes_championship_freeze
    fantasystakes_championship_score

No existing row or money-bearing table is changed. A rollback to RC1 simply
ignores these new tables. The application never rewrites a frozen score.

Fresh databases get the same tables from SQLAlchemy metadata; this migration is
for an EXISTING production database and is registered as ACTIVE migration 0003.

Idempotent: running it again observes both tables and makes no change.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from db.schema import engine  # noqa: E402

FREEZE_TABLE = "fantasystakes_championship_freeze"
SCORE_TABLE = "fantasystakes_championship_score"


def _freeze_ddl(dialect: str) -> str:
    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return f"""
CREATE TABLE {FREEZE_TABLE} (
    id                   {pk},
    league_id            INTEGER NOT NULL REFERENCES leagues (id),
    season               INTEGER NOT NULL,
    playoff_start_week   INTEGER NOT NULL,
    scoring_through_week INTEGER NOT NULL,
    frozen_at            TIMESTAMP NOT NULL,
    CONSTRAINT uq_fs_champ_freeze_league_season UNIQUE (league_id, season),
    CONSTRAINT ck_fs_champ_freeze_playoff_week CHECK (playoff_start_week > 0),
    CONSTRAINT ck_fs_champ_freeze_cutoff
        CHECK (scoring_through_week = playoff_start_week - 1)
)
"""


def _score_ddl(dialect: str) -> str:
    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    bigint = "BIGINT"
    return f"""
CREATE TABLE {SCORE_TABLE} (
    id                       {pk},
    freeze_id                INTEGER NOT NULL REFERENCES {FREEZE_TABLE} (id),
    league_id                INTEGER NOT NULL REFERENCES leagues (id),
    season                   INTEGER NOT NULL,
    team_id                  INTEGER NOT NULL REFERENCES teams (id),
    matchup_net_cents        {bigint} NOT NULL,
    prop_pool_net_cents      {bigint} NOT NULL,
    championship_score_cents {bigint} NOT NULL,
    CONSTRAINT uq_fs_champ_score_freeze_team UNIQUE (freeze_id, team_id),
    CONSTRAINT uq_fs_champ_score_league_season_team UNIQUE (league_id, season, team_id),
    CONSTRAINT ck_fs_champ_score_sum
        CHECK (championship_score_cents = matchup_net_cents + prop_pool_net_cents)
)
"""


def upgrade() -> list[str]:
    """Apply the additive RC2 championship schema. Returns an audit summary."""
    done: list[str] = []
    dialect = engine.dialect.name

    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())

        if FREEZE_TABLE not in tables:
            connection.execute(text(_freeze_ddl(dialect)))
            done.append(f"created {FREEZE_TABLE}")
        else:
            done.append(f"{FREEZE_TABLE} already exists")

        # Refresh after the first CREATE because this table depends on it.
        tables = set(inspect(connection).get_table_names())
        if SCORE_TABLE not in tables:
            connection.execute(text(_score_ddl(dialect)))
            connection.execute(text(
                f"CREATE INDEX ix_fs_champ_score_league_season "
                f"ON {SCORE_TABLE} (league_id, season)"))
            done.append(f"created {SCORE_TABLE}")
            done.append("created ix_fs_champ_score_league_season")
        else:
            done.append(f"{SCORE_TABLE} already exists")

    return done or ["nothing to do — already applied"]


if __name__ == "__main__":
    for line in upgrade():
        print(f"  · {line}")
    print("RC2 FantasyStakes championship snapshot migration complete.")
