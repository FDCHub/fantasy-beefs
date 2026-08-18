"""RC2 migration — durable exactly-once FantasyStakes Championship distribution."""
from __future__ import annotations

from sqlalchemy import inspect, text

from db.schema import engine

TABLE = "fantasystakes_championship_distribution_run"


def upgrade() -> list[str]:
    dialect = engine.dialect.name
    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    uuid_type = "UUID" if dialect == "postgresql" else "CHAR(32)"
    json_type = "JSONB" if dialect == "postgresql" else "JSON"
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "TIMESTAMP"

    with engine.begin() as c:
        if TABLE in set(inspect(c).get_table_names()):
            return [f"{TABLE} already exists"]
        c.execute(text(f"""
            CREATE TABLE {TABLE} (
                id {pk},
                league_id INTEGER NOT NULL REFERENCES leagues(id),
                season INTEGER NOT NULL,
                pot_cents BIGINT NOT NULL,
                posting_id {uuid_type} NOT NULL,
                awards_json {json_type} NOT NULL,
                distributed_at {timestamp_type} NOT NULL,
                CONSTRAINT uq_fs_champ_dist_league_season UNIQUE (league_id, season),
                CONSTRAINT uq_fs_champ_dist_posting UNIQUE (posting_id)
            )
        """))
    return [f"created {TABLE}"]


if __name__ == "__main__":
    for line in upgrade():
        print(f"  · {line}")
