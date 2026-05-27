"""
Migration v2: bench_battle + staleness_warning + injury_status.

Changes:
  1. projections     — ADD COLUMN injury_status TEXT
  2. beef_challenges — ADD COLUMN projection_snapshot TEXT
                     — ADD COLUMN staleness_warning INTEGER DEFAULT 0
  3. bets            — recreate to update ck_bet_type ('bench_battle' added)
  4. beef_challenges — recreate to update ck_beef_bet_type ('bench_battle' added)

Steps 3 & 4 use the standard SQLite approach:
  RENAME old table → CREATE new table → INSERT SELECT → DROP old.
FK enforcement is OFF by default in SQLite so circular FKs are not an issue.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import inspect, text

from db.schema import engine


def _col_exists(table: str, col: str) -> bool:
    return col in {c["name"] for c in inspect(engine).get_columns(table)}


def _table_exists(table: str) -> bool:
    return inspect(engine).has_table(table)


def run_migration() -> None:
    with engine.connect() as conn:

        # 1. injury_status on projections
        if not _col_exists("projections", "injury_status"):
            conn.execute(text("ALTER TABLE projections ADD COLUMN injury_status TEXT"))
            conn.commit()
            print("  + projections.injury_status added")
        else:
            print("  . projections.injury_status already exists")

        # 2. New columns on beef_challenges (add before recreation so data survives)
        for col, ddl in (
            ("projection_snapshot", "TEXT"),
            ("staleness_warning",   "INTEGER NOT NULL DEFAULT 0"),
        ):
            if not _col_exists("beef_challenges", col):
                conn.execute(text(f"ALTER TABLE beef_challenges ADD COLUMN {col} {ddl}"))
                conn.commit()
                print(f"  + beef_challenges.{col} added")
            else:
                print(f"  . beef_challenges.{col} already exists")

        # 3. Recreate bets with updated ck_bet_type constraint
        #    (SQLite cannot ALTER CHECK constraints — must rename/create/copy/drop)
        conn.execute(text("ALTER TABLE bets RENAME TO bets_old"))
        conn.execute(text("""
            CREATE TABLE bets (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                matchup_id        INTEGER NOT NULL REFERENCES matchups(id),
                wallet_id         INTEGER NOT NULL REFERENCES wallets(id),
                picked_team_id    INTEGER REFERENCES teams(id),
                player_id         INTEGER REFERENCES players(id),
                bet_type          VARCHAR NOT NULL DEFAULT 'straight',
                line              FLOAT,
                description       VARCHAR,
                amount            FLOAT NOT NULL,
                odds              FLOAT NOT NULL DEFAULT 1.909,
                side              VARCHAR,
                status            VARCHAR NOT NULL DEFAULT 'pending',
                placed_at         DATETIME,
                settled_at        DATETIME,
                beef_challenge_id INTEGER REFERENCES beef_challenges(id),
                CHECK (status  IN ('pending','won','lost')),
                CHECK (amount  > 0),
                CHECK (bet_type IN ('straight','spread','over_under','prop','bench_battle'))
            )
        """))
        conn.execute(text("""
            INSERT INTO bets
                SELECT id, matchup_id, wallet_id, picked_team_id, player_id,
                       bet_type, line, description, amount, odds, side,
                       status, placed_at, settled_at, beef_challenge_id
                FROM bets_old
        """))
        conn.execute(text("DROP TABLE bets_old"))
        conn.commit()
        print("  + bets table recreated (ck_bet_type updated)")

        # 4. Recreate beef_challenges with updated ck_beef_bet_type constraint.
        #    The new columns were already added in step 2, so they appear in SELECT *.
        conn.execute(text("ALTER TABLE beef_challenges RENAME TO beef_challenges_old"))
        conn.execute(text("""
            CREATE TABLE beef_challenges (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                challenger_team_id   INTEGER NOT NULL REFERENCES teams(id),
                challenged_team_id   INTEGER NOT NULL REFERENCES teams(id),
                week                 INTEGER NOT NULL,
                bet_type             VARCHAR NOT NULL,
                amount               FLOAT   NOT NULL,
                line                 FLOAT,
                side                 VARCHAR,
                player_id            INTEGER REFERENCES players(id),
                description          VARCHAR,
                challenger_odds      FLOAT   NOT NULL,
                challenged_odds      FLOAT   NOT NULL,
                challenger_moneyline INTEGER NOT NULL,
                challenged_moneyline INTEGER NOT NULL,
                status               VARCHAR NOT NULL DEFAULT 'pending',
                expires_at           DATETIME NOT NULL,
                created_at           DATETIME,
                responded_at         DATETIME,
                challenger_bet_id    INTEGER REFERENCES bets(id),
                challenged_bet_id    INTEGER REFERENCES bets(id),
                projection_snapshot  TEXT,
                staleness_warning    INTEGER NOT NULL DEFAULT 0,
                CHECK (status   IN ('pending','accepted','declined','expired')),
                CHECK (bet_type IN ('straight','spread','over_under','prop','bench_battle'))
            )
        """))
        conn.execute(text("""
            INSERT INTO beef_challenges (
                id, challenger_team_id, challenged_team_id, week, bet_type,
                amount, line, side, player_id, description,
                challenger_odds, challenged_odds, challenger_moneyline, challenged_moneyline,
                status, expires_at, created_at, responded_at,
                challenger_bet_id, challenged_bet_id,
                projection_snapshot, staleness_warning
            )
            SELECT
                id, challenger_team_id, challenged_team_id, week, bet_type,
                amount, line, side, player_id, description,
                challenger_odds, challenged_odds, challenger_moneyline, challenged_moneyline,
                status, expires_at, created_at, responded_at,
                challenger_bet_id, challenged_bet_id,
                projection_snapshot, staleness_warning
            FROM beef_challenges_old
        """))
        conn.execute(text("DROP TABLE beef_challenges_old"))
        conn.commit()
        print("  + beef_challenges table recreated (ck_beef_bet_type updated)")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("Running migration v2...")
    run_migration()
    print("Done.")
