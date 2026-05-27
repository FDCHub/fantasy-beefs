"""
One-time migration: add projection_source to leagues, create league_scoring table,
and seed LeagueScoring for the existing league (id=1, half_ppr, pass_td=5.0).
Safe to re-run — all steps are idempotent.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import inspect, text

from db.schema import Base, LeagueScoring, SessionLocal, engine


def _column_exists(table: str, column: str) -> bool:
    return column in {c["name"] for c in inspect(engine).get_columns(table)}


def run_migration() -> None:
    # 1. Add projection_source column to leagues (if missing)
    if not _column_exists("leagues", "projection_source"):
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE leagues ADD COLUMN projection_source TEXT NOT NULL DEFAULT 'fantasypros'"
            ))
            conn.commit()
        print("  + leagues.projection_source added")
    else:
        print("  . leagues.projection_source already exists")

    # 2. Create league_scoring table (create_all is additive — skips existing tables)
    Base.metadata.create_all(engine)
    print("  + league_scoring table ensured")

    # 3. Seed LeagueScoring for league_id=1 if not present
    with SessionLocal() as db:
        existing = db.query(LeagueScoring).filter_by(league_id=1).first()
        if existing is None:
            db.add(LeagueScoring(
                league_id        = 1,
                scoring_type     = "half_ppr",
                rec_points       = 0.5,
                pass_td_points   = 5.0,
                rush_td_points   = 6.0,
                rec_td_points    = 6.0,
                bonus_100yd_rush = 0.0,
                bonus_100yd_rec  = 0.0,
            ))
            db.commit()
            print("  + LeagueScoring seeded for league_id=1 (half_ppr, pass_td=5.0)")
        else:
            print(f"  . LeagueScoring already exists for league_id=1 "
                  f"(scoring_type={existing.scoring_type!r})")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("Running scoring migration...")
    run_migration()
    print("Done.")
