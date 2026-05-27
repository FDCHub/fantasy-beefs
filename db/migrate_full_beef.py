"""Migration v10 — recreate bets table to add 'full_beef' to bet_type CHECK constraint.

SQLite doesn't support ALTER TABLE … CHECK, so we use the rename/copy/drop pattern.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from db.schema import engine


def run_migration() -> None:
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text("""
            CREATE TABLE bets_new (
                id                INTEGER  PRIMARY KEY AUTOINCREMENT,
                matchup_id        INTEGER  NOT NULL REFERENCES matchups(id),
                wallet_id         INTEGER  NOT NULL REFERENCES wallets(id),
                picked_team_id    INTEGER  REFERENCES teams(id),
                player_id         INTEGER  REFERENCES players(id),
                bet_type          TEXT     NOT NULL DEFAULT 'straight',
                line              REAL,
                description       TEXT,
                amount            REAL     NOT NULL,
                odds              REAL     NOT NULL DEFAULT 1.909,
                side              TEXT,
                status            TEXT     NOT NULL DEFAULT 'pending',
                placed_at         DATETIME,
                settled_at        DATETIME,
                beef_challenge_id INTEGER  REFERENCES beef_challenges(id),
                CHECK (status IN ('pending','won','lost')),
                CHECK (amount > 0),
                CHECK (bet_type IN ('straight','spread','over_under','prop','bench_battle','full_beef'))
            )
        """))
        conn.execute(text("INSERT INTO bets_new SELECT * FROM bets"))
        conn.execute(text("DROP TABLE bets"))
        conn.execute(text("ALTER TABLE bets_new RENAME TO bets"))
        conn.execute(text("PRAGMA foreign_keys=ON"))

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM bets")).scalar()
    print(f"[migrate_full_beef] bets table recreated with full_beef constraint — {count} existing row(s) preserved")


if __name__ == "__main__":
    run_migration()
