"""RC2-CHAMP-ECON — additive FantasyStakes Championship economy tables."""
from __future__ import annotations

from sqlalchemy import inspect, text

from db.schema import engine

CONFIG_TABLE = "fantasystakes_championship_config"
ALLOC_TABLE = "fantasystakes_championship_allocation"


def upgrade() -> list[str]:
    done: list[str] = []
    dialect = engine.dialect.name
    id_col = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    uuid_type = "UUID" if dialect == "postgresql" else "CHAR(32)"
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "TIMESTAMP"

    with engine.begin() as c:
        tables = set(inspect(c).get_table_names())
        if CONFIG_TABLE not in tables:
            c.execute(text(f"""
                CREATE TABLE {CONFIG_TABLE} (
                    id {id_col},
                    league_id INTEGER NOT NULL REFERENCES leagues(id),
                    season INTEGER NOT NULL,
                    contribution_cents INTEGER NOT NULL,
                    frozen_at {timestamp_type},
                    CONSTRAINT uq_fs_champ_config_league_season UNIQUE (league_id, season),
                    CONSTRAINT ck_fs_champ_config_contribution CHECK (contribution_cents BETWEEN 100 AND 100000)
                )
            """))
            done.append(f"created {CONFIG_TABLE}")

        tables = set(inspect(c).get_table_names())
        if ALLOC_TABLE not in tables:
            c.execute(text(f"""
                CREATE TABLE {ALLOC_TABLE} (
                    id {id_col},
                    league_id INTEGER NOT NULL REFERENCES leagues(id),
                    season INTEGER NOT NULL,
                    team_id INTEGER NOT NULL REFERENCES teams(id),
                    contribution_cents INTEGER NOT NULL,
                    posting_id {uuid_type} NOT NULL,
                    created_at {timestamp_type} NOT NULL,
                    CONSTRAINT uq_fs_champ_alloc_league_season_team UNIQUE (league_id, season, team_id),
                    CONSTRAINT uq_fs_champ_alloc_posting UNIQUE (posting_id),
                    CONSTRAINT ck_fs_champ_alloc_positive CHECK (contribution_cents > 0)
                )
            """))
            done.append(f"created {ALLOC_TABLE}")

    return done or ["nothing to do — RC2 championship economy already present"]


if __name__ == "__main__":
    for line in upgrade():
        print(f"  · {line}")
