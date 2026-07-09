"""
betting/per_bet_lock.py

Per-GM per-bet lock for versus (beef) bets.

A versus bet locks *independently per GM*: a GM is locked once any player they
rostered for the bet is in an NFL game that has already kicked off for that week.
Pool bets use the simpler week-level lock (_nfl_lock_time) instead.

Public API:
    from betting.per_bet_lock import is_bet_locked_for_gm, LockCheck
    result = is_bet_locked_for_gm(conn, ["KC", "PHI"], week=3)
    if result.locked:
        ...  # result.reason tells you why: "in_progress" | "schedule_not_ready" | "data_gap"
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import NamedTuple

from sqlalchemy import bindparam, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Schedule season intentionally differs from CURRENT_SEASON while projections
# and the NFL schedule are on different release cycles. Mirrors the same
# constant in beef_engine.py so both files always agree on which season to query.
from config import LOCK_SEASON

_log = logging.getLogger(__name__)

# Dedup gate for the placeholder-band tripwire warning below — each unique
# (home, away, week, season, kickoff) occurrence logs exactly once per
# process lifetime, not once per call, so live traffic doesn't flood logs
# and bury the one signal that actually needs a human to look at it.
# In-memory only, resets on process restart — intentional; this is a
# monitoring aid, not a money-path decision, so no TTL/external cache needed.
_tripwire_warned: set[tuple] = set()


class LockCheck(NamedTuple):
    locked: bool
    reason: str | None  # None, "in_progress", "schedule_not_ready", "data_gap"


def _is_real_kickoff(kickoff_utc: datetime) -> bool:
    """
    A real NFL kickoff sits between 09:00 UTC and 02:00 UTC the next day.
    Folding hours below 9 up by 24 turns that window into one contiguous
    band, [9, 26]. Placeholder rows (NFL hasn't posted a real time yet)
    fall outside it — confirmed pattern: every game in a placeholder week
    shares one identical timestamp, in the 05:00-08:00 UTC zone this band
    rejects.

    Duplicated from the equivalent inline check in
    betting/pool_engine.py's _nfl_lock_time() — not yet extracted into a
    shared helper. Accepted debt for a future consolidation pass; flagged
    here rather than forked silently.
    """
    hour = kickoff_utc.hour
    folded = hour + 24 if hour < 9 else hour
    return 9 <= folded <= 26


def _is_placeholder_week(conn, week: int, season: int) -> bool:
    """
    A genuine placeholder week has every game sharing one identical
    kickoff_utc — a real NFL week never does, since real slates always
    span multiple kickoff times (Thursday, Sunday early/late, Sunday
    night, Monday). Requires MORE THAN TWO game rows sharing that one
    timestamp, not just one distinct value — a real, light-game week can
    coincidentally have exactly two games at the same kickoff slot (e.g.
    two Sunday 1pm games), and a week with only one or two rows loaded
    (e.g. mid-sync) would trivially have one distinct timestamp too. A
    genuine placeholder week always has many more rows sharing one
    timestamp, so requiring >2 keeps real placeholder-week detection
    intact while excluding the 2-game coincidence.
    Zero-row weeks are out of scope here by design — they fall through
    to the existing bye-vs-data-gap path, unchanged.
    """
    rows = conn.execute(text(
        "SELECT kickoff_utc FROM nfl_schedule "
        "WHERE season = :season AND week = :week"
    ), {"season": season, "week": week}).fetchall()
    if len(rows) <= 2:
        return False
    distinct_stamps = {r[0] for r in rows}
    return len(distinct_stamps) == 1


def is_bet_locked_for_gm(
    conn,
    player_nfl_teams: list[str],
    week: int,
    now_utc: datetime | None = None,
    *,
    season: int = LOCK_SEASON,
) -> LockCheck:
    """
    Returns LockCheck(locked, reason). locked is True if ANY of this GM's
    staked players is in a game that has already kicked off for the given
    week, OR if the schedule can't yet confirm that safely (quiet fail-safe
    — no exception raised here; that's a different file's convention).

    reason is one of:
        None                  — not locked, no ambiguity.
        "in_progress"         — a real kickoff has passed; genuinely locked.
        "schedule_not_ready"  — rows exist for the week, but every one is a
                                 placeholder (NFL hasn't posted real times
                                 yet). Locked, quiet fail-safe.
        "data_gap"            — the team code can't be confirmed anywhere in
                                 the season via a real (non-placeholder) row.
                                 Locked, quiet fail-safe.

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
        open. "Team has no game this week" is a valid bye, not an error — but
        only when at least one real (non-placeholder) row confirms the team
        is genuinely tracked in the season. A team whose only appearances
        anywhere in the season are placeholder rows is a data_gap, not a bye
        — a placeholder row proves nothing about whether the team plays.

    Data-gap behaviour:
        If a team code appears nowhere in nfl_schedule for the whole season
        with a real (non-placeholder) row, a WARNING is logged and the
        function returns locked=True, reason="data_gap". A game the code
        can't find might already be in progress — the safe default is to
        block, not to allow.

    Placeholder behaviour:
        nfl_schedule can hold placeholder kickoff times for weeks the NFL
        hasn't officially scheduled yet. A raw MIN() over kickoff_utc would
        let a placeholder masquerade as the real kickoff — including in a
        week where a GM's staked players span multiple NFL teams and only
        SOME of those teams' games are placeholder-only. This function
        filters placeholders out via _is_real_kickoff() before computing the
        earliest real kickoff, so a real kickoff from one team is never
        shadowed by an earlier-sorting placeholder timestamp from another.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if not player_nfl_teams:
        return LockCheck(False, None)

    _teams = list(player_nfl_teams)

    def _to_dt(value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value

    # Whole-week placeholder detection — every game in the week shares one
    # identical timestamp. If so, this GM is locked (schedule_not_ready)
    # regardless of which teams are staked; skip the per-team query entirely.
    # This does NOT replace _is_real_kickoff()/the band below — it only
    # closes the whole-week placeholder case (Weeks 16/17/18-style). A single
    # real early-hour game (e.g. an 08:00 UTC international kickoff) sitting
    # inside an otherwise normal, multi-timestamp week still falls through to
    # the band logic below, and the band's latent risk on that narrower case
    # is still open — see the tripwire warning in the per-row loop.
    if _is_placeholder_week(conn, week, season):
        return LockCheck(True, "schedule_not_ready")

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
        # Fetch every candidate row across the season (not just LIMIT 1) so a
        # real bye can be distinguished from a team that only ever appears
        # via placeholder rows — the latter is a data gap, not a confirmed bye.
        # A season row only counts as real evidence if BOTH its own week is
        # not a whole-week placeholder AND it individually passes
        # _is_real_kickoff() — a row from a placeholder week could otherwise
        # fall inside the band's accepted hours by coincidence and be
        # misread as proof the team is genuinely tracked (the unsafe
        # direction: a false "true bye" instead of a data_gap).
        season_stmt = text(
            "SELECT week, kickoff_utc FROM nfl_schedule "
            "WHERE season = :season "
            "  AND (home_team IN :teams OR away_team IN :teams)"
        ).bindparams(bindparam("teams", expanding=True))
        season_rows = conn.execute(season_stmt, {"season": season, "teams": _teams}).fetchall()

        has_real_row = any(
            not _is_placeholder_week(conn, r_week, season) and _is_real_kickoff(_to_dt(r_kickoff))
            for r_week, r_kickoff in season_rows
        )

        if not season_rows or not has_real_row:
            _log.warning(
                "is_bet_locked_for_gm: teams %s not found in nfl_schedule "
                "season=%d with any confirmed (non-placeholder) game — "
                "possible wrong abbreviation, un-synced schedule, or "
                "placeholder-only data",
                _teams,
                season,
            )
            # Data gap — can't confirm the game hasn't started. Protect the money.
            return LockCheck(True, "data_gap")
        # True bye — team has at least one real row in the season, none this week.
        return LockCheck(False, None)

    real_rows = []
    for r in rows:
        dt = _to_dt(r[2])
        if _is_real_kickoff(dt):
            real_rows.append(r)
        else:
            # Tripwire — this individual row failed the band, but the
            # whole-week placeholder check above already confirmed this week
            # is NOT a placeholder week. That makes this row's rejection
            # worth a closer look: it might be a real early-hour kickoff
            # (e.g. an 08:00 UTC international game) being misclassified by
            # the band, not a genuine placeholder. Monitoring only — does
            # not change locked/reason behavior. Deduped so live traffic
            # doesn't flood logs with the same occurrence on every call.
            tripwire_key = (r[0], r[1], week, season, dt.isoformat())
            if tripwire_key not in _tripwire_warned:
                _tripwire_warned.add(tripwire_key)
                _log.warning(
                    "is_bet_locked_for_gm: row for %s in week %d falls in the "
                    "rejected placeholder-band hour zone (%s) but its week is NOT a "
                    "placeholder week — possible real early-hour kickoff being "
                    "misclassified. Manual check recommended.",
                    f"{r[0]} vs {r[1]}", week, dt.isoformat(),
                )
    if not real_rows:
        # Every row for this GM's teams this week is placeholder-only — the
        # NFL hasn't posted real kickoff times yet. Quiet fail-safe: locked,
        # no exception, matching this file's existing convention.
        return LockCheck(True, "schedule_not_ready")

    earliest = min(_to_dt(r[2]) for r in real_rows)
    locked = earliest <= now_utc
    return LockCheck(locked, "in_progress" if locked else None)


# ── Self-test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    from sqlalchemy import create_engine

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    def _run_live_data_cases(conn) -> bool:
        """Cases 1-5 — need a real, populated nfl_schedule to run against.
        Any failure here (missing DATABASE_URL, connection error, empty
        table) is caught by the caller and must not prevent cases 6-7
        (self-contained, no live data needed) from running. Returns True
        only if all five cases actually ran to completion; False if
        skipped early (e.g. no week-1 anchor found)."""
        # ── Find anchors from real schedule data ───────────────────────────────
        # Week 1, earliest game
        anchor = conn.execute(text(
            "SELECT home_team, away_team, kickoff_utc "
            "FROM nfl_schedule "
            "WHERE season = :s AND week = 1 "
            "ORDER BY kickoff_utc LIMIT 1"
        ), {"s": LOCK_SEASON}).fetchone()

        if not anchor:
            print(f"NOTE: no week-1 games found for season {LOCK_SEASON} in nfl_schedule "
                  f"— skipping live-data cases 1-5.")
            return False

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

        # ── Case 1: game in the past → expect locked=True ──────────────────────
        now_past = kickoff_aware.replace(
            hour=kickoff_aware.hour + 3 if kickoff_aware.hour <= 20 else 23,
            minute=0,
        )
        result1 = is_bet_locked_for_gm(conn, [home_team], week=1, now_utc=now_past, season=LOCK_SEASON)
        print(f"Case 1 — game in the past")
        print(f"  team={home_team!r}  week=1  kickoff={kickoff_aware.isoformat()}")
        print(f"  now_utc={now_past.isoformat()}  (3h after kickoff)")
        print(f"  result={result1}  expected locked=True  "
              f"{'PASS' if result1.locked is True and result1.reason == 'in_progress' else 'FAIL'}")

        # ── Case 2: game in the future → expect locked=False ───────────────────
        now_future = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)  # today, well before season
        result2 = is_bet_locked_for_gm(conn, [home_team], week=1, now_utc=now_future, season=LOCK_SEASON)
        print(f"\nCase 2 — game in the future")
        print(f"  team={home_team!r}  week=1  kickoff={kickoff_aware.isoformat()}")
        print(f"  now_utc={now_future.isoformat()}  (pre-season)")
        print(f"  result={result2}  expected locked=False  "
              f"{'PASS' if result2.locked is False and result2.reason is None else 'FAIL'}")

        # ── Case 3: bye week → expect locked=False, no warning ─────────────────
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
            print(f"  result={result3}  expected locked=False  "
                  f"{'PASS' if result3.locked is False and result3.reason is None else 'FAIL'}")
            print(f"  warning emitted: {bool(warned)}  expected=False  {'PASS' if not warned else 'FAIL'}")
            if warned:
                print(f"  warning text: {warned}")
        else:
            print("\nCase 3 — SKIP: no bye team found for week 5")

        # ── Case 4: team code not in season schedule at all (data gap) ─────────
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
        print(f"  result={result4}  expected locked=True, reason=data_gap  "
              f"{'PASS' if result4.locked is True and result4.reason == 'data_gap' else 'FAIL'}")
        print(f"  warning emitted: {bool(warned4)}  expected=True   {'PASS' if warned4 else 'FAIL'}")
        if warned4:
            print(f"  warning text: {warned4}")

        # ── Case 5: placeholder-only week → expect schedule_not_ready ──────────
        # Confirmed placeholder weeks this session: 16, 17, 18 (one shared
        # timestamp per week, every game in that week). Use whichever team
        # played in week 16 in this season's real data.
        print(f"\nCase 5 — placeholder-only week (schedule not yet posted)")
        ph_week = 16
        ph_row = conn.execute(text(
            "SELECT home_team, kickoff_utc FROM nfl_schedule "
            "WHERE season = :s AND week = :w LIMIT 1"
        ), {"s": LOCK_SEASON, "w": ph_week}).fetchone()

        if ph_row:
            ph_team, ph_kickoff = ph_row
            ph_kickoff_aware = ph_kickoff.replace(tzinfo=timezone.utc) if ph_kickoff.tzinfo is None else ph_kickoff
            result5 = is_bet_locked_for_gm(conn, [ph_team], week=ph_week, now_utc=now_future, season=LOCK_SEASON)
            print(f"  team={ph_team!r}  week={ph_week}  kickoff_utc={ph_kickoff_aware.isoformat()}")
            print(f"  result={result5}  expected locked=True, reason=schedule_not_ready  "
                  f"{'PASS' if result5.locked is True and result5.reason == 'schedule_not_ready' else 'FAIL'}")
        else:
            print(f"  SKIP: no rows found for week {ph_week} season {LOCK_SEASON} — cannot verify live")

        return True

    live_cases_ran = False
    DB = os.environ.get("DATABASE_URL")
    if not DB:
        print("NOTE: DATABASE_URL not set — skipping live-data cases 1-5, "
              "running constructed cases 6-7 only.\n")
    else:
        try:
            engine = create_engine(DB, connect_args={"connect_timeout": 10})
            with engine.connect() as conn:
                live_cases_ran = _run_live_data_cases(conn)
        except Exception as e:
            print(f"NOTE: could not run live-data cases (1-5) — {type(e).__name__}: {e}")
            print("Skipping to constructed cases 6-7.\n")

    # ── Cases 6 & 7 use a small constructed local SQLite fixture ────────────────
    # These properties (a real row winning MIN() over an earlier-sorting
    # placeholder; a placeholder-only team not being misread as a true bye)
    # are not reproducible against today's live data on demand — production
    # currently has no naturally-occurring "mixed" week, and every real team
    # already has real rows elsewhere in the season, so a data_gap-via-bye
    # case can't be demonstrated with a real team code either. Both are
    # constructed here, clearly labeled, rather than skipped.
    print("\n" + "=" * 60)
    print("Cases 6-7 — constructed local fixture (not live production data)")
    print("=" * 60)

    from sqlalchemy import create_engine as _create_engine

    _local_engine = _create_engine("sqlite:///:memory:")
    with _local_engine.connect() as lconn:
        lconn.execute(text(
            "CREATE TABLE nfl_schedule ("
            "  season INTEGER, week INTEGER, "
            "  home_team VARCHAR, away_team VARCHAR, kickoff_utc TIMESTAMP)"
        ))

        TEST_SEASON = 9999
        MIX_WEEK    = 20

        # Case 6 fixture: same week, one real kickoff (hour=18, within band)
        # for TEAMA, one placeholder (hour=6, outside band) for TEAMB — the
        # exact shape a GM staking players across two different NFL teams
        # would create if one team's game is confirmed and the other's isn't.
        _case6_real_ko        = datetime(2026, 12, 20, 18, 0, 0)
        _case6_placeholder_ko = datetime(2026, 12, 20, 6, 0, 0)

        # Fix 4 (MS-PBL-3): confirm the fixture's chosen hours actually sit on
        # the sides of the band they're meant to, before trusting the
        # sort-order assertions below. If the band's definition ever changes,
        # these fail with a message pointing at the band, not a confusing
        # sort-order failure.
        assert _is_real_kickoff(_case6_real_ko) is True, \
            "test fixture assumption broken: real kickoff hour no longer passes the band"
        assert _is_real_kickoff(_case6_placeholder_ko) is False, \
            "test fixture assumption broken: placeholder hour no longer fails the band"

        lconn.execute(text(
            "INSERT INTO nfl_schedule VALUES (:season, :week, :home, :away, :ko)"
        ), {"season": TEST_SEASON, "week": MIX_WEEK, "home": "TEAMA", "away": "OPPA",
            "ko": _case6_real_ko})
        lconn.execute(text(
            "INSERT INTO nfl_schedule VALUES (:season, :week, :home, :away, :ko)"
        ), {"season": TEST_SEASON, "week": MIX_WEEK, "home": "TEAMB", "away": "OPPB",
            "ko": _case6_placeholder_ko})
        lconn.commit()

        # now_utc sits after the placeholder's hour (6) but before the real
        # kickoff's hour (18). A raw, unfiltered MIN() would pick the
        # placeholder (06:00 < 10:00) and wrongly report locked=True. The
        # fix must filter it out and use the real 18:00 row instead, which
        # hasn't started yet at 10:00 — locked=False.
        now6 = datetime(2026, 12, 20, 10, 0, 0, tzinfo=timezone.utc)
        result6 = is_bet_locked_for_gm(
            lconn, ["TEAMA", "TEAMB"], week=MIX_WEEK, now_utc=now6, season=TEST_SEASON
        )
        print(f"\nCase 6 — mixed real+placeholder week, real row must win MIN()")
        print(f"  TEAMA real kickoff=18:00Z (within band)   TEAMB placeholder=06:00Z (outside band)")
        print(f"  now_utc={now6.isoformat()}  (after placeholder hour, before real kickoff)")
        print(f"  result={result6}  expected locked=False (real 18:00 row governs, not the 06:00 placeholder)  "
              f"{'PASS' if result6.locked is False and result6.reason is None else 'FAIL'}")

        # Sanity companion: same fixture, now_utc after the REAL kickoff —
        # must correctly report locked=True, proving the real row is what's
        # actually being compared, not just always returning False.
        now6b = datetime(2026, 12, 20, 19, 0, 0, tzinfo=timezone.utc)
        result6b = is_bet_locked_for_gm(
            lconn, ["TEAMA", "TEAMB"], week=MIX_WEEK, now_utc=now6b, season=TEST_SEASON
        )
        print(f"  companion: now_utc={now6b.isoformat()} (after real 18:00 kickoff)")
        print(f"  result={result6b}  expected locked=True, reason=in_progress  "
              f"{'PASS' if result6b.locked is True and result6b.reason == 'in_progress' else 'FAIL'}")

        # Case 7 fixture: TEAMC appears ONLY via a placeholder row, in a
        # different week (21) than the one being queried (22, a bye for
        # TEAMC). A real team always has real rows elsewhere in the season,
        # so this can't be shown with a real team code — TEAMC is
        # placeholder-only by construction to isolate the fix.
        lconn.execute(text(
            "INSERT INTO nfl_schedule VALUES (:season, :week, :home, :away, :ko)"
        ), {"season": TEST_SEASON, "week": 21, "home": "TEAMC", "away": "OPPC",
            "ko": datetime(2026, 12, 27, 6, 0, 0)})
        lconn.commit()

        result7 = is_bet_locked_for_gm(
            lconn, ["TEAMC"], week=22, now_utc=now6, season=TEST_SEASON
        )
        print(f"\nCase 7 — bye-detection fix: placeholder-only team must be data_gap, not a bye")
        print(f"  TEAMC's only row all season is a week-21 placeholder (06:00Z); queried week=22 (no row)")
        print(f"  result={result7}  expected locked=True, reason=data_gap (NOT a true bye)  "
              f"{'PASS' if result7.locked is True and result7.reason == 'data_gap' else 'FAIL'}")

    # ── Fix 5 (MS-PBL-4): make a skipped live-data run loud, not silently clean ──
    if not live_cases_ran:
        print("\n" + "!" * 60)
        print("INCOMPLETE: Live-data Cases 1-5 did NOT run. Only the")
        print("constructed Cases 6-7 executed. This is NOT a clean full pass.")
        print("!" * 60)
        sys.exit(1)
