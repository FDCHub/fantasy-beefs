"""RC2 migration — independent FantasyStakes Championship contribution/funding.

Creates only additive tables. Existing SeasonAllocation rows and Yahoo
Championship configuration are not altered or reinterpreted.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from db.schema import engine  # noqa: E402

CONFIG_TABLE = "fantasystakes_championship_config"
ALLOCATION_TABLE = "fantasystakes_championship_allocation"


def _config_ddl(dialect: str) -> str:
    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return f"""
CREATE TABLE {CONFIG_TABLE} (
    id                 {pk},
    league_id          INTEGER NOT NULL REFERENCES leagues (id),
    season             INTEGER NOT NULL,
    contribution_cents INTEGER NOT NULL,
    frozen_at          TIMESTAMP,
    created_at         TIMESTAMP NOT NULL,
    CONSTRAINT uq_fs_champ_config_league_season UNIQUE (league_id, season),
    CONSTRAINT ck_fs_champ_config_contribution
        CHECK (contribution_cents BETWEEN 100 AND 100000)
)
"""


def _allocation_ddl(dialect: str) -> str:
    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    uuid_type = "UUID" if dialect == "postgresql" else "CHAR(32)"
    return f"""
CREATE TABLE {ALLOCATION_TABLE} (
    id                 {pk},
    league_id          INTEGER NOT NULL REFERENCES leagues (id),
    season             INTEGER NOT NULL,
    team_id            INTEGER NOT NULL REFERENCES teams (id),
    contribution_cents INTEGER NOT NULL,
    ledger_posting_id  {uuid_type} NOT NULL,
    created_at         TIMESTAMP NOT NULL,
    CONSTRAINT uq_fs_champ_alloc_league_season_team
        UNIQUE (league_id, season, team_id),
    CONSTRAINT ck_fs_champ_alloc_positive CHECK (contribution_cents > 0)
)
"""


def upgrade() -> list[str]:
    done: list[str] = []
    dialect = engine.dialect.name

    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        if CONFIG_TABLE not in tables:
            connection.execute(text(_config_ddl(dialect)))
            done.append(f"created {CONFIG_TABLE}")
        else:
            done.append(f"{CONFIG_TABLE} already exists")

        tables = set(inspect(connection).get_table_names())
        if ALLOCATION_TABLE not in tables:
            connection.execute(text(_allocation_ddl(dialect)))
            done.append(f"created {ALLOCATION_TABLE}")
        else:
            done.append(f"{ALLOCATION_TABLE} already exists")

    return done or ["nothing to do — already applied"]


if __name__ == "__main__":
    for line in upgrade():
        print(f"  · {line}")
    print("RC2 FantasyStakes championship economy migration complete.")
