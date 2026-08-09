#!/usr/bin/env python3
"""
migrate_s5_weekly_economy.py — S5-P1 schema.

Two changes, both additive-or-renaming, no data movement:

  1. season_allocations.wallet_cents -> min_reserve_cents (RENAME, values kept
     byte-for-byte). Under owner ruling S5-R2 that allocation goes to
     min_reserve:{team}, not the Wallet, and the old label would have gone on
     silently meaning Weekly Minimum Reserve. The Top-Off cap basis reads this
     same column and its arithmetic is unchanged.

  2. economy_event — the Sprint 5 exactly-once carrier, one deterministic
     event_key under a plain UNIQUE. See db/schema.py for why a single NOT NULL
     text key beats four partial indexes over nullable columns here.

NO ALLOCATION MIGRATION POSTING. The S5-P1 preflight found no legitimate
old-shape (140-in-Wallet) activation anywhere reachable: fantasy_test carried
zero tables, no local SQLite dev database exists, and production DATABASE_URL is
unset by standing policy. Future initialization changes only; no live balance is
touched by this file.

Postgres-only, idempotent, one transaction — the existing migration convention.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import text

_CREATE_ECONOMY_EVENT = """
    CREATE TABLE economy_event (
        id           SERIAL PRIMARY KEY,
        event_key    VARCHAR NOT NULL,
        league_id    INTEGER NOT NULL REFERENCES leagues(id),
        season       INTEGER NOT NULL,
        week         INTEGER,
        team_id      INTEGER REFERENCES teams(id),
        event_type   VARCHAR NOT NULL,
        posting_id   UUID,
        amount_cents BIGINT NOT NULL,
        created_at   TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_economy_event_key UNIQUE (event_key),
        CONSTRAINT ck_economy_event_amount_nonneg CHECK (amount_cents >= 0)
    )
"""

_CREATE_INDEX = """
    CREATE INDEX ix_economy_event_league_season
        ON economy_event (league_id, season)
"""


def _table_exists(conn, table: str) -> bool:
    return conn.execute(text("""
        SELECT EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_schema='public' AND table_name=:t)
    """), {"t": table}).scalar()


def _column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(text("""
        SELECT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema='public'
                         AND table_name=:t AND column_name=:c)
    """), {"t": table, "c": column}).scalar()


def upgrade(engine) -> None:
    with engine.begin() as conn:
        has_old = _column_exists(conn, "season_allocations", "wallet_cents")
        has_new = _column_exists(conn, "season_allocations", "min_reserve_cents")
        if has_old and has_new:
            raise RuntimeError(
                "season_allocations carries BOTH wallet_cents and "
                "min_reserve_cents. One allocation cannot have two labels for "
                "one fact; resolve manually rather than letting this migration "
                "choose between two populated columns.")
        if has_old and not has_new:
            conn.execute(text("ALTER TABLE season_allocations "
                              "RENAME COLUMN wallet_cents TO min_reserve_cents"))
            print("  season_allocations.wallet_cents -> min_reserve_cents")

        # Matchup economic finality (S5-P2 owner ruling). Additive and
        # nullable, so every EXISTING row is left NOT FINAL. Backfilling from
        # refreshed_at, from a non-null score or from age would fabricate
        # finality for results nobody declared final — the migration has no
        # deterministic authoritative evidence of finality for historical rows,
        # so it asserts none.
        if not _column_exists(conn, "matchups", "finalized_at"):
            conn.execute(text(
                "ALTER TABLE matchups ADD COLUMN finalized_at TIMESTAMP"))
            print("  matchups.finalized_at added (existing rows left NOT final)")

        if not _table_exists(conn, "economy_event"):
            conn.execute(text(_CREATE_ECONOMY_EVENT))
            conn.execute(text(_CREATE_INDEX))
            print("  economy_event created")

    with engine.connect() as conn:
        if not _table_exists(conn, "economy_event"):
            raise RuntimeError("verification failed -- economy_event absent")
    print("\n  MIGRATION COMPLETE.")


def downgrade(engine) -> None:
    """Drop economy_event and rename the column back. NOT auto-invoked."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS economy_event CASCADE"))
        if (_column_exists(conn, "season_allocations", "min_reserve_cents")
                and not _column_exists(conn, "season_allocations",
                                       "wallet_cents")):
            conn.execute(text("ALTER TABLE season_allocations "
                              "RENAME COLUMN min_reserve_cents TO wallet_cents"))
    print("  DOWNGRADE COMPLETE.")


if __name__ == "__main__":
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    print("\nmigrate_s5_weekly_economy.py  --  S5-P1 schema\n")
    from db.schema import engine  # noqa: E402

    db_url = str(engine.url)
    if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
        print("!! ERROR: Postgres target not detected.")
        sys.exit(1)
    try:
        upgrade(engine)
    except Exception as exc:  # noqa: BLE001
        print(f"\n!! ERROR: migration failed and rolled back: {exc}")
        sys.exit(1)
