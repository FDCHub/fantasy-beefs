"""
yahoo_scoreboard.py — shared Yahoo Fantasy scoreboard fetcher.

Pulls one week's matchup scores from the Yahoo Fantasy API via yfpy.
Caller supplies an already-authenticated YahooFantasySportsQuery object so
this module has no opinion about league_id, game_id, or credentials.

Used by:
  • seed_real_2025_season_LIVE.py  — initial season seed (all weeks)
  • (future) weekly score sync     — single-week refresh after games finish

Public API
----------
fetch_week_scoreboard(query, week) -> list[dict] | None

Status semantics
----------------
Yahoo's matchup.status field returns one of three values:
  "postevent"  → game week is complete; scores are final
  "midevent"   → game week is in progress; scores are partial
  "preevent"   → game week has not started; score will be 0.0

These are mapped to caller-friendly strings:
  "postevent"  → "final"
  "midevent"   → "in_progress"
  "preevent"   → "not_started"
  (anything else) → "unknown"

A caller MUST check status before treating a score as settled.  A score of
0.0 with status "not_started" or "in_progress" is meaningless — it does not
mean the team scored zero points.
"""

from __future__ import annotations

from typing import Optional


# ── Yahoo status → app status ─────────────────────────────────────────────────

_STATUS_MAP: dict[str, str] = {
    "postevent": "final",
    "midevent":  "in_progress",
    "preevent":  "not_started",
}


# ── Private helpers ───────────────────────────────────────────────────────────

def _s(v) -> str:
    """Coerce a yfpy value (possibly bytes or None) to a plain str."""
    if v is None:
        return ""
    return v.decode() if isinstance(v, bytes) else str(v)


def _get_team_score(team_obj) -> float:
    """
    Extract the numeric score from a yfpy Team object on a scoreboard response.

    yfpy's model exposes the score under different attribute paths depending on
    the API version and context.  This helper tries the known paths in order and
    returns 0.0 only when nothing is found.

    NOTE: a return value of 0.0 is ambiguous — it may mean "score not available"
    (e.g. for a preevent or midevent week) rather than a true zero.  Callers
    should use the matchup status to decide how to interpret the score.
    """
    for pts_attr in ("team_points", "points", "team_projected_points"):
        pts = getattr(team_obj, pts_attr, None)
        if pts is None:
            continue
        for sub in ("total", "season_total", "value", "week"):
            sub_val = getattr(pts, sub, None)
            if sub_val is not None:
                try:
                    return float(_s(sub_val))
                except (ValueError, TypeError):
                    pass
        try:
            return float(_s(pts))
        except (ValueError, TypeError):
            pass
    return 0.0


def _parse_winner_team_id(winner_team_key: str) -> Optional[int]:
    """
    Parse the integer team ID from a Yahoo team key string.

    Yahoo team keys have the format: "<game_id>.l.<league_id>.t.<team_id>"
    Example: "461.l.488800.t.7" → 7

    Returns None if the key is absent, empty, or unparseable.
    """
    if not winner_team_key:
        return None
    parts = winner_team_key.split(".")
    # Standard format: last two segments are "t" and "<team_id>"
    if len(parts) >= 2 and parts[-2] == "t":
        try:
            return int(parts[-1])
        except ValueError:
            pass
    # Fallback: try the last segment alone
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_week_scoreboard(query, week: int) -> list[dict] | None:
    """
    Pull one week's matchup scores from Yahoo via yfpy.

    Parameters
    ----------
    query : YahooFantasySportsQuery
        An authenticated yfpy query object for the target league.
    week : int
        NFL week number (1-based).

    Returns
    -------
    list[dict] | None
        One dict per matchup::

            {
                "home_team_id":   int,          # lower of the two Yahoo team IDs
                "away_team_id":   int,          # higher of the two Yahoo team IDs
                "home_score":     float,        # actual or partial score; see status
                "away_score":     float,        # actual or partial score; see status
                "status":         str,          # "final"|"in_progress"|"not_started"|"unknown"
                "winner_team_id": int | None,   # set when final & not tied; else None
            }

        Returns None when Yahoo returns no matchup data for the requested week
        (the normal end-of-season signal — week is beyond the schedule).
        Returns [] when Yahoo acknowledges the week but has zero matchups listed.

    Raises
    ------
    Re-raises every exception except ``KeyError('scoreboard')``.

    ``KeyError('scoreboard')`` is the specific signal yfpy raises when Yahoo's
    API response contains no scoreboard key for the requested week — the normal
    case for a week that is beyond the end of the season schedule (e.g. week 19
    of an 18-week season).  That specific error is caught here and converted to
    a ``None`` return so callers don't have to distinguish it from real failures.

    Everything else — auth failures (HTTP 401), rate limits (HTTP 429), network
    errors, or any other ``KeyError`` key name — propagates unchanged.  A weekly
    sync job can therefore treat any non-``None`` return as data and any raised
    exception as a real failure requiring retry / alerting.
    """
    try:
        scoreboard = query.get_league_scoreboard_by_week(week)
    except KeyError as exc:
        # yfpy raises KeyError('scoreboard') at query.py:527 when Yahoo returns
        # a response with no scoreboard key — week is past the season schedule.
        # Any other KeyError (different key name) is an unexpected API shape
        # change and must surface as a real failure.
        if exc.args and exc.args[0] == "scoreboard":
            return None
        raise

    raw_matchups = getattr(scoreboard, "matchups", None)

    if raw_matchups is None:
        return None

    try:
        raw_list = list(raw_matchups) if not isinstance(raw_matchups, list) else raw_matchups
    except TypeError:
        raw_list = []

    if not raw_list:
        return []

    results: list[dict] = []

    for m in raw_list:
        yahoo_status = _s(getattr(m, "status", ""))
        status       = _STATUS_MAP.get(yahoo_status, "unknown")

        # Derive winner from Yahoo's authoritative winner_team_key when final.
        # Fall back to None for ties, in-progress, and unknown states.
        winner_team_id: Optional[int] = None
        if status == "final":
            is_tied = int(getattr(m, "is_tied", 0))
            if not is_tied:
                wtk            = _s(getattr(m, "winner_team_key", ""))
                winner_team_id = _parse_winner_team_id(wtk)

        teams = getattr(m, "teams", None) or []
        try:
            teams = list(teams) if not isinstance(teams, list) else teams
        except TypeError:
            teams = []

        if len(teams) < 2:
            continue  # malformed matchup — skip

        t0_id  = int(_s(getattr(teams[0], "team_id", "0")))
        t1_id  = int(_s(getattr(teams[1], "team_id", "0")))
        t0_pts = _get_team_score(teams[0])
        t1_pts = _get_team_score(teams[1])

        # Convention: home = lower team ID (matches seed script ordering)
        if t0_id <= t1_id:
            home_id, away_id, home_pts, away_pts = t0_id, t1_id, t0_pts, t1_pts
        else:
            home_id, away_id, home_pts, away_pts = t1_id, t0_id, t1_pts, t0_pts

        results.append({
            "home_team_id":   home_id,
            "away_team_id":   away_id,
            "home_score":     home_pts,
            "away_score":     away_pts,
            "status":         status,
            "winner_team_id": winner_team_id,
        })

    return results
