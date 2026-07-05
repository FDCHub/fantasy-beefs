"""
betting/per_bet_lock.py

Per-GM per-bet lock for versus (beef) bets.

A versus bet locks *independently per GM*: a GM is locked once any player they
rostered for the bet is in an NFL game that has already kicked off for that week.
Pool bets use the simpler week-level lock (_nfl_lock_time) instead.

Public API:
    from betting.per_bet_lock import is_bet_locked_for_gm
    locked = is_bet_locked_for_gm(conn, ["KC", "PHI"], week=3)
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import bindparam, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Schedule season intentionally differs from CURRENT_SEASON while projections
# and the NFL schedule are on different release cycles. Mirrors the same
# constant in beef_engine.py so both files always agree on which season to query.
from config import LOCK_SEASON

_log = logging.getLogger(__name__)


def is_bet_locked_for_gm(
    conn,
    player_nfl_teams: list[str],
    week: int,
    now_utc: datetime | None = None,
    *,
    season: int = LOCK_SEASON,
) -> bool:
    """
    Returns True if ANY of this GM's staked players is in a game that has
    already kicked off for the given week. Locked = at least one game started.

    Args:
        conn:              SQLAlchemy connection (not Session).
        player_nfl_teams:  NFL team abbreviations for the players this GM staked.
                           Must match nfl_schedule.home_team / away_team dialect.
        week:              NFL week number (1-17).
        now_utc:           Comparison timestamp; defaults to datetime.now(UTC).
        season:            NFL season year; defaults to LOCK_SEASON.

    Bye-week behaviour:
        A player on bye has no game scheduled that week — that player does not
        cause the GM to lock. If all of a GM's players are on bye the GM stays
        open. "Team has no game this week" is a valid bye, not an error.

    Data-gap behaviour:
        If a team code appears nowhere in nfl_schedule for the whole season
        (not just this week), a WARNING is logged and the function returns
        True (locked). A game the code can't find might already be in
        progress — the safe default is to block, not to allow.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if not player_nfl_teams:
        return False

    _teams = list(player_nfl_teams)

    # Games this week involving any of this GM's teams.
    week_stmt = text(
        "SELECT home_team, away_team, kickoff_utc "
        "FROM nfl_schedule "
        "WHERE season = :season AND week = :week "
        "  AND (home_team IN :teams OR away_team IN :teams)"
    ).bindparams(bindparam("teams", expanding=True))

    rows = conn.execute(week_stmt, {"season": season, "week": week, "teams": _teams}).fetchall()

    if not rows:
        # Check whether the teams appear in this season at all (bye vs data gap).
        season_stmt = text(
            "SELECT 1 FROM nfl_schedule "
            "WHERE season = :season "
            "  AND (home_team IN :teams OR away_team IN :teams) "
            "LIMIT 1"
        ).bindparams(bindparam("teams", expanding=True))
        found = conn.execute(season_stmt, {"season": season, "teams": _teams}).fetchone()

        if found is None:
            _log.warning(
                "is_bet_locked_for_gm: teams %s not found in nfl_schedule "
                "season=%d at all — possible wrong abbreviation or un-synced schedule",
                _teams,
                season,
            )
            # Data gap — can't confirm the game hasn't started. Protect the money.
            return True
        # True bye — team exists in the season but has no game this week.
        return False

    earliest = min(r[2] for r in rows)
    if isinstance(earliest, str):
        earliest = datetime.fromisoformat(earliest)
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=timezone.utc)

    return earliest <= now_utc


# ── Self-test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    from sqlalchemy import create_engine

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    DB = os.environ.get("DATABASE_URL")
    if not DB:
        print("ERROR: DATABASE_URL environment variable not set.")
        raise SystemExit(1)
    engine = create_engine(DB, connect_args={"connect_timeout": 10})

    with engine.connect() as conn:
        # ── Find anchors from real schedule data ───────────────────────────────
        # Week 1, earliest game
        anchor = conn.execute(text(
            "SELECT home_team, away_team, kickoff_utc "
            "FROM nfl_schedule "
            "WHERE season = :s AND week = 1 "
            "ORDER BY kickoff_utc LIMIT 1"
        ), {"s": LOCK_SEASON}).fetchone()

        if not anchor:
            print(f"ERROR: no week-1 games found for season {LOCK_SEASON} in nfl_schedule")
            raise SystemExit(1)

        home_team, away_team, kickoff = anchor
        kickoff_aware = kickoff.replace(tzinfo=timezone.utc) if kickoff.tzinfo is None else kickoff

        # Verify KC is on bye in week 5 (expected from DB query earlier)
        bye_team = "KC"
        bye_week = 5
        bye_check = conn.execute(text(
            "SELECT COUNT(*) FROM nfl_schedule "
            "WHERE season=:s AND week=:w AND (home_team=:t OR away_team=:t)"
        ), {"s": LOCK_SEASON, "w": bye_week, "t": bye_team}).scalar()
        if bye_check != 0:
            # Fallback: find a real bye team for week 5
            print(f"WARNING: {bye_team} is NOT on bye in week {bye_week} — finding a real bye team")
            all_w5 = conn.execute(text(
                "SELECT home_team, away_team FROM nfl_schedule WHERE season=:s AND week=5"
            ), {"s": LOCK_SEASON}).fetchall()
            playing = {r[0] for r in all_w5} | {r[1] for r in all_w5}
            all_teams = conn.execute(text(
                "SELECT DISTINCT home_team FROM nfl_schedule WHERE season=:s "
                "UNION SELECT DISTINCT away_team FROM nfl_schedule WHERE season=:s"
            ), {"s": LOCK_SEASON}).fetchall()
            all_set = {r[0] for r in all_teams}
            byes = sorted(all_set - playing)
            bye_team = byes[0] if byes else None

        print(f"\nTest anchor  : {home_team} vs {away_team}  kickoff_utc={kickoff_aware.isoformat()}")
        print(f"Bye anchor   : {bye_team} is on bye in week {bye_week}\n")

        # ── Case 1: game in the past → expect True ─────────────────────────────
        now_past = kickoff_aware.replace(
            hour=kickoff_aware.hour + 3 if kickoff_aware.hour <= 20 else 23,
            minute=0,
        )
        result1 = is_bet_locked_for_gm(conn, [home_team], week=1, now_utc=now_past, season=LOCK_SEASON)
        print(f"Case 1 — game in the past")
        print(f"  team={home_team!r}  week=1  kickoff={kickoff_aware.isoformat()}")
        print(f"  now_utc={now_past.isoformat()}  (3h after kickoff)")
        print(f"  result={result1}  expected=True  {'PASS' if result1 is True else 'FAIL'}")

        # ── Case 2: game in the future → expect False ──────────────────────────
        now_future = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)  # today, well before season
        result2 = is_bet_locked_for_gm(conn, [home_team], week=1, now_utc=now_future, season=LOCK_SEASON)
        print(f"\nCase 2 — game in the future")
        print(f"  team={home_team!r}  week=1  kickoff={kickoff_aware.isoformat()}")
        print(f"  now_utc={now_future.isoformat()}  (pre-season)")
        print(f"  result={result2}  expected=False  {'PASS' if result2 is False else 'FAIL'}")

        # ── Case 3: bye week → expect False, no warning ────────────────────────
        if bye_team:
            print(f"\nCase 3 — bye week")
            print(f"  team={bye_team!r}  week={bye_week}  (verified bye in nfl_schedule)")
            # Logging at WARNING so we can tell if the bye-vs-data-gap branch warns
            import io
            log_capture = io.StringIO()
            handler = logging.StreamHandler(log_capture)
            handler.setLevel(logging.WARNING)
            _log.addHandler(handler)

            result3 = is_bet_locked_for_gm(conn, [bye_team], week=bye_week, now_utc=now_future, season=LOCK_SEASON)

            _log.removeHandler(handler)
            warned = log_capture.getvalue().strip()

            print(f"  now_utc={now_future.isoformat()}")
            print(f"  result={result3}  expected=False  {'PASS' if result3 is False else 'FAIL'}")
            print(f"  warning emitted: {bool(warned)}  expected=False  {'PASS' if not warned else 'FAIL'}")
            if warned:
                print(f"  warning text: {warned}")
        else:
            print("\nCase 3 — SKIP: no bye team found for week 5")

        # ── Case 4: team code not in season schedule at all (data gap) → True ──
        import io as _io
        log_capture4 = _io.StringIO()
        handler4 = logging.StreamHandler(log_capture4)
        handler4.setLevel(logging.WARNING)
        _log.addHandler(handler4)

        result4 = is_bet_locked_for_gm(conn, ["KCX"], week=1, now_utc=now_future, season=LOCK_SEASON)

        _log.removeHandler(handler4)
        warned4 = log_capture4.getvalue().strip()

        print(f"\nCase 4 — data gap (team code not in season schedule)")
        print(f"  team='KCX'  week=1  (KCX has zero rows in nfl_schedule for season {LOCK_SEASON})")
        print(f"  now_utc={now_future.isoformat()}")
        print(f"  result={result4}  expected=True   {'PASS' if result4 is True else 'FAIL'}")
        print(f"  warning emitted: {bool(warned4)}  expected=True   {'PASS' if warned4 else 'FAIL'}")
        if warned4:
            print(f"  warning text: {warned4}")
