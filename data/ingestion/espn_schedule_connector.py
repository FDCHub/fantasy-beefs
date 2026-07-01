"""
ESPN schedule connector — data pump for NFL game schedules.

Pulls from ESPN's public scoreboard endpoint (no API key required) and
upserts rows into the NflSchedule table.  No scoring or business logic lives
here — this module fetches, parses, and persists raw schedule data only.

Public functions
----------------
fetch_week_schedule(season, week) -> list[dict]
    Returns one dict per game: {home_team, away_team, kickoff_utc}

upsert_week_schedule(season, week, db) -> int
    Calls fetch_week_schedule and upserts into NflSchedule.
    Returns the number of rows written (inserted + updated).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from db.schema import NflSchedule

# ESPN public scoreboard — no auth required.
# seasontype=2 → regular season; 1 = preseason, 3 = postseason
_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
)


def fetch_week_schedule(season: int, week: int) -> list[dict]:
    """
    Fetch the NFL game schedule for one regular-season week from ESPN.

    Returns a list of dicts, one per game::

        [
            {
                "home_team":   "KC",          # ESPN team abbreviation
                "away_team":   "DET",
                "kickoff_utc": datetime(..., tzinfo=timezone.utc),
            },
            ...
        ]

    Raises requests.HTTPError on non-2xx responses.
    """
    params = {
        "dates":      str(season),
        "seasontype": "2",            # regular season
        "week":       str(week),
    }
    resp = requests.get(_SCOREBOARD_URL, params=params, timeout=10)
    resp.raise_for_status()

    data   = resp.json()
    events = data.get("events", [])
    games: list[dict] = []

    for event in events:
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        comp = competitions[0]

        # Parse kickoff — ESPN sends ISO 8601 UTC, e.g. "2024-09-06T00:20Z"
        raw_dt = comp.get("date") or event.get("date", "")
        kickoff_utc = _parse_espn_dt(raw_dt)
        if kickoff_utc is None:
            continue

        home_team = away_team = None
        for competitor in comp.get("competitors", []):
            abbr = competitor.get("team", {}).get("abbreviation", "")
            if competitor.get("homeAway") == "home":
                home_team = abbr
            elif competitor.get("homeAway") == "away":
                away_team = abbr

        if home_team and away_team:
            games.append({
                "home_team":   home_team,
                "away_team":   away_team,
                "kickoff_utc": kickoff_utc,
            })

    return games


def upsert_week_schedule(season: int, week: int, db: Session) -> int:
    """
    Fetch the schedule for the given season/week and upsert into NflSchedule.

    Keyed on (season, week, home_team, away_team).  Existing rows have their
    kickoff_utc and last_synced_at updated; missing rows are inserted.

    Returns the number of rows written (inserted + updated).
    """
    games   = fetch_week_schedule(season, week)
    now     = datetime.now(timezone.utc)
    written = 0

    for g in games:
        row = (
            db.query(NflSchedule)
            .filter_by(
                season    = season,
                week      = week,
                home_team = g["home_team"],
                away_team = g["away_team"],
            )
            .first()
        )
        if row is not None:
            row.kickoff_utc    = g["kickoff_utc"]
            row.last_synced_at = now
        else:
            db.add(NflSchedule(
                season         = season,
                week           = week,
                home_team      = g["home_team"],
                away_team      = g["away_team"],
                kickoff_utc    = g["kickoff_utc"],
                last_synced_at = now,
            ))
        written += 1

    db.commit()
    return written


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_espn_dt(raw: str) -> datetime | None:
    """
    Parse an ESPN ISO 8601 datetime string to a timezone-aware UTC datetime.

    ESPN sends strings like "2024-09-06T00:20Z" or "2024-09-06T00:20:00Z".
    Python 3.11+ accepts the 'Z' suffix natively; for 3.9/3.10 we normalise it.
    """
    if not raw:
        return None
    # Normalise 'Z' → '+00:00' so fromisoformat works on all Python 3.x
    normalised = raw.rstrip("Z") + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(normalised)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    week   = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    print(f"\nESPN schedule fetch — season {season}  week {week}")
    print("-" * 54)
    games = fetch_week_schedule(season, week)
    print(f"  {len(games)} games returned\n")
    for g in games:
        kt = g["kickoff_utc"].strftime("%Y-%m-%d %H:%MZ")
        print(f"  {g['away_team']:>4} @ {g['home_team']:<4}  kickoff {kt}")
    print()
