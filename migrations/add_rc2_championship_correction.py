"""RC2 migration — append-only authoritative championship result corrections.

Creates one additive table:

    fantasystakes_championship_correction

No existing row or money-bearing table is changed, and nothing is backfilled: a
league with no corrections simply has no rows, and its Championship Score stays
exactly the frozen snapshot. A rollback to an earlier RC2 build ignores the
table.

Fresh databases get the same table from SQLAlchemy metadata; this migration is
for an EXISTING database and is registered as ACTIVE migration 0006.

Idempotent: running it again observes the table and makes no change.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from db.schema import engine

TABLE = "fantasystakes_championship_correction"


def upgrade() -> list[str]:
    dialect = engine.dialect.name
    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp_type = ("TIMESTAMP WITH TIME ZONE" if dialect == "postgresql"
                      else "TIMESTAMP")
    uuid_type = "UUID" if dialect == "postgresql" else "CHAR(32)"

    with engine.begin() as c:
        if TABLE in set(inspect(c).get_table_names()):
            return [f"{TABLE} already exists"]
        c.execute(text(f"""
            CREATE TABLE {TABLE} (
                id {pk},
                freeze_id INTEGER NOT NULL
                    REFERENCES fantasystakes_championship_freeze(id),
                league_id INTEGER NOT NULL REFERENCES leagues(id),
                season INTEGER NOT NULL,
                team_id INTEGER NOT NULL REFERENCES teams(id),
                competition_type VARCHAR NOT NULL,
                contest_ref INTEGER NOT NULL,
                scoring_week INTEGER NOT NULL,
                revision INTEGER NOT NULL,
                previous_net_cents BIGINT NOT NULL,
                corrected_net_cents BIGINT NOT NULL,
                delta_cents BIGINT NOT NULL,
                reason VARCHAR NOT NULL,
                source VARCHAR NOT NULL,
                correction_key VARCHAR NOT NULL,
                posting_id {uuid_type},
                created_at {timestamp_type} NOT NULL,
                CONSTRAINT uq_fs_champ_correction_key_team
                    UNIQUE (correction_key, team_id),
                CONSTRAINT uq_fs_champ_correction_revision
                    UNIQUE (league_id, season, competition_type, contest_ref,
                            team_id, revision),
                CONSTRAINT ck_fs_champ_correction_delta
                    CHECK (delta_cents = corrected_net_cents - previous_net_cents),
                CONSTRAINT ck_fs_champ_correction_revision CHECK (revision > 0),
                CONSTRAINT ck_fs_champ_correction_week CHECK (scoring_week > 0),
                CONSTRAINT ck_fs_champ_correction_type
                    CHECK (competition_type IN ('versus','prop_pool'))
            )
        """))
        c.execute(text(
            f"CREATE INDEX ix_fs_champ_correction_league_season "
            f"ON {TABLE} (league_id, season)"))
    return [f"created {TABLE}", "created ix_fs_champ_correction_league_season"]


if __name__ == "__main__":
    for line in upgrade():
        print(f"  · {line}")
