#!/usr/bin/env python3
"""
seed_nfl_schedule_from_csv.py  --  Load 2026 NFL schedule from CSV into NflSchedule.

Reads data/nfl_2026_27_regular_season_schedule.csv, converts Eastern kickoff
times to UTC (honouring DST via zoneinfo), normalises the one known abbreviation
mismatch (WAS -> WSH), and upserts all non-TBD games into NflSchedule.

Upsert key: (season, week, home_team, away_team) — existing rows are updated,
not duplicated.  TBD rows are skipped and reported.

USAGE:
  python seed_nfl_schedule_from_csv.py              # against dev (SQLite)
  DATABASE_URL=<pg_url> python seed_nfl_schedule_from_csv.py   # Postgres
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.schema import Base, NflSchedule, SessionLocal, engine

# ── Config ────────────────────────────────────────────────────────────────────

CSV_PATH = Path(__file__).parent / "data" / "nfl_2026_27_regular_season_schedule.csv"
SEASON   = 2026
EASTERN  = ZoneInfo("America/New_York")

# One-entry normalization: CSV uses 'WAS'; ESPN (and NflSchedule) uses 'WSH'
ABBR_MAP: dict[str, str] = {"WAS": "WSH"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize(abbr: str) -> str:
    return ABBR_MAP.get(abbr, abbr)


def _parse_kickoff_utc(date_str: str, kickoff_et: str) -> datetime:
    """
    Parse M/D/YYYY + H:MM AM/PM (Eastern) into a timezone-aware UTC datetime.

    Uses zoneinfo so DST transitions (EDT = UTC-4, EST = UTC-5) are handled
    automatically.  Raises ValueError if either string is unparseable.
    """
    date  = datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
    time_ = datetime.strptime(kickoff_et.strip(), "%I:%M %p").time()
    eastern_dt = datetime(
        date.year, date.month, date.day,
        time_.hour, time_.minute, 0,
        tzinfo=EASTERN,
    )
    return eastern_dt.astimezone(timezone.utc)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\nseed_nfl_schedule_from_csv.py  --  season {SEASON}")
    print(f"  source : {CSV_PATH}")
    print(f"  target : {str(engine.url).split('@')[-1] if '@' in str(engine.url) else engine.url}\n")

    # Ensure table exists locally (create_all is a no-op for existing tables)
    Base.metadata.create_all(engine)

    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    print(f"  CSV rows read : {len(rows)}")

    inserted     = 0
    updated      = 0
    skipped_tbd  = 0
    skipped_weeks: dict[str, int] = {}
    normalizations_applied = 0
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        for row in rows:
            date_str   = row["Date"].strip()
            kickoff_et = row["Kickoff_ET"].strip()
            week       = int(row["Week"])

            # Skip TBD rows
            if date_str.upper() == "TBD" or kickoff_et.upper() == "TBD":
                skipped_tbd += 1
                skipped_weeks[str(week)] = skipped_weeks.get(str(week), 0) + 1
                continue

            raw_home = row["Home_Abbr"].strip()
            raw_away = row["Away_Abbr"].strip()
            home     = _normalize(raw_home)
            away     = _normalize(raw_away)

            if home != raw_home or away != raw_away:
                normalizations_applied += 1

            kickoff_utc = _parse_kickoff_utc(date_str, kickoff_et)

            existing = (
                db.query(NflSchedule)
                .filter_by(season=SEASON, week=week, home_team=home, away_team=away)
                .first()
            )
            if existing is not None:
                existing.kickoff_utc    = kickoff_utc
                existing.last_synced_at = now
                updated += 1
            else:
                db.add(NflSchedule(
                    season         = SEASON,
                    week           = week,
                    home_team      = home,
                    away_team      = away,
                    kickoff_utc    = kickoff_utc,
                    last_synced_at = now,
                ))
                inserted += 1

        db.commit()

    # ── Summary ───────────────────────────────────────────────────────────────

    print()
    print("=" * 56)
    print("SEED SUMMARY")
    print("=" * 56)
    print(f"  Rows inserted            : {inserted}")
    print(f"  Rows updated             : {updated}")
    print(f"  Rows skipped (TBD)       : {skipped_tbd}")
    if skipped_weeks:
        by_week = ", ".join(f"wk{w}={n}" for w, n in sorted(skipped_weeks.items(), key=lambda x: int(x[0])))
        print(f"    breakdown              : {by_week}")
    print(f"  Abbrev normalizations    : {normalizations_applied}  (WAS->WSH)")
    print()

    # ── Verification spot-checks ──────────────────────────────────────────────

    print("=" * 56)
    print("SPOT-CHECKS")
    print("=" * 56)

    with SessionLocal() as db:
        total = db.query(NflSchedule).filter_by(season=SEASON).count()
        wk1   = db.query(NflSchedule).filter_by(season=SEASON, week=1).count()
        print(f"  Total rows (season {SEASON}) : {total}")
        print(f"  Week 1 rows               : {wk1}")
        print()

        # Wed Sept 9: NE @ SEA (8:20 PM ET = 00:20 UTC Sept 10)
        ne_sea = (
            db.query(NflSchedule)
            .filter_by(season=SEASON, week=1, away_team="NE", home_team="SEA")
            .first()
        )
        if ne_sea:
            k = ne_sea.kickoff_utc
            # Ensure we have a timezone-aware datetime for display
            if k.tzinfo is None:
                k = k.replace(tzinfo=timezone.utc)
            print(f"  NE @ SEA  kickoff_utc : {k.strftime('%Y-%m-%d %H:%MZ')}")
            expected_ne_sea = datetime(2026, 9, 10, 0, 20, tzinfo=timezone.utc)
            status = "OK" if abs((k - expected_ne_sea).total_seconds()) < 60 else "MISMATCH"
            print(f"  Expected              : 2026-09-10 00:20Z  [{status}]")
        else:
            print("  NE @ SEA  : NOT FOUND in DB")
        print()

        # Thu Sept 10: SF @ LAR (8:35 PM ET = 00:35 UTC Sept 11)
        sf_lar = (
            db.query(NflSchedule)
            .filter_by(season=SEASON, week=1, away_team="SF", home_team="LAR")
            .first()
        )
        if sf_lar:
            k = sf_lar.kickoff_utc
            if k.tzinfo is None:
                k = k.replace(tzinfo=timezone.utc)
            print(f"  SF @ LAR  kickoff_utc : {k.strftime('%Y-%m-%d %H:%MZ')}")
            expected_sf_lar = datetime(2026, 9, 11, 0, 35, tzinfo=timezone.utc)
            status = "OK" if abs((k - expected_sf_lar).total_seconds()) < 60 else "MISMATCH"
            print(f"  Expected              : 2026-09-11 00:35Z  [{status}]")
        else:
            print("  SF @ LAR  : NOT FOUND in DB")
        print()

        # Confirm WSH (not WAS) is in DB
        wash_rows = db.query(NflSchedule).filter(
            (NflSchedule.home_team == "WSH") | (NflSchedule.away_team == "WSH")
        ).filter_by(season=SEASON).count()
        was_rows = db.query(NflSchedule).filter(
            (NflSchedule.home_team == "WAS") | (NflSchedule.away_team == "WAS")
        ).filter_by(season=SEASON).count()
        # 17 WAS games in CSV; 3 are TBD (wk16, wk17, wk18) and skipped — 14 land in DB
        print(f"  WSH rows in DB (normalized)  : {wash_rows}  (expected 14)")
        print(f"  WAS rows in DB (should be 0) : {was_rows}")
        wsh_ok = wash_rows == 14 and was_rows == 0
        print(f"  Normalization check          : {'OK' if wsh_ok else 'FAIL'}")

    print()


if __name__ == "__main__":
    main()
