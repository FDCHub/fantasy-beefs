"""
test_yahoo_scoreboard.py — live Yahoo API smoke test for fetch_week_scoreboard.

Calls the real Yahoo API (no mocks).  Requires secrets/ directory to be present.

Tests:
  1. Completed week (week 1 of the 2025 NFL season, game_id=461)
     • Returns a list, not None
     • All matchups have status == "final"
     • All matchups have at least one non-zero score
     • Non-tied matchups have winner_team_id populated
     • Full table printed for manual verification against seeded DB values

  2. End-of-season probe (week 19 — beyond the 2025 NFL schedule)
     • Observes what Yahoo returns; expected signal is None (no data)
     • No assertions — this is a documentation / sanity probe

  3. Optional DB comparison (only when DATABASE_URL is set)
     • Fetches matchups from DB for week 1 and compares to Yahoo scores
     • Reports any discrepancies

Usage:
    python test_yahoo_scoreboard.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yfpy.query import YahooFantasySportsQuery
from ingestion.yahoo_scoreboard import fetch_week_scoreboard

LEAGUE_ID = "488800"
GAME_CODE  = "nfl"
GAME_ID    = 461   # 2025 NFL season


# ── Query builder ─────────────────────────────────────────────────────────────

def _build_query() -> YahooFantasySportsQuery:
    with open("secrets/private.json") as f:
        token = json.load(f)
    with open("secrets/yahoo_oauth.json") as f:
        creds = json.load(f)
    token["consumer_secret"] = creds["consumer_secret"]
    return YahooFantasySportsQuery(
        league_id=LEAGUE_ID,
        game_code=GAME_CODE,
        game_id=GAME_ID,
        yahoo_access_token_json=token,
        browser_callback=False,
    )


# ── Assertion helper ──────────────────────────────────────────────────────────

_pass_count = 0
_fail_count = 0


def _check(label: str, cond: bool, got=None) -> None:
    global _pass_count, _fail_count
    if cond:
        _pass_count += 1
        print(f"  PASS  {label}")
    else:
        _fail_count += 1
        detail = f"  (got: {got!r})" if got is not None else ""
        print(f"  FAIL  {label}{detail}")


# ── Test 1: completed week ────────────────────────────────────────────────────

def test_completed_week(query: YahooFantasySportsQuery) -> list[dict]:
    """
    Fetch week 1 of the 2025 NFL season.
    The entire season is complete, so every matchup should be "final".
    """
    print("\n── Test 1: completed week (week 1, 2025 season) ──")
    result = fetch_week_scoreboard(query, week=1)

    _check("returns a list (not None)", result is not None, result)
    if result is None:
        print("  SKIP  remaining assertions (None returned)")
        return []

    _check("at least 1 matchup returned", len(result) >= 1, len(result))

    print(f"\n  {len(result)} matchup(s) returned:\n")
    print(f"  {'Home ID':>8}  {'Away ID':>8}  {'Home Score':>12}  {'Away Score':>12}"
          f"  {'Status':<14}  {'Winner ID':>10}")
    print(f"  {'-'*8}  {'-'*8}  {'-'*12}  {'-'*12}  {'-'*14}  {'-'*10}")
    for m in result:
        print(f"  {m['home_team_id']:>8}  {m['away_team_id']:>8}"
              f"  {m['home_score']:>12.2f}  {m['away_score']:>12.2f}"
              f"  {m['status']:<14}  {str(m['winner_team_id']):>10}")

    print()
    all_final = all(m["status"] == "final" for m in result)
    _check("all matchups have status='final'", all_final,
           [m["status"] for m in result])

    any_score = all(m["home_score"] > 0 or m["away_score"] > 0 for m in result)
    _check("all matchups have at least one non-zero score", any_score,
           [(m["home_score"], m["away_score"]) for m in result])

    non_tied = [m for m in result if m["home_score"] != m["away_score"]]
    winners_set = all(m["winner_team_id"] is not None for m in non_tied)
    _check(f"all {len(non_tied)} non-tied matchup(s) have winner_team_id set",
           winners_set,
           [m["winner_team_id"] for m in non_tied])

    return result


# ── Test 2: end-of-season probe ───────────────────────────────────────────────

def test_end_of_season(query: YahooFantasySportsQuery) -> None:
    """
    Week 19 does not exist in the 2025 NFL schedule (max is 18).

    Yahoo's API returns a response with no 'scoreboard' key for this week.
    yfpy raises KeyError('scoreboard') at query.py:527.  fetch_week_scoreboard
    now catches that specific error internally and returns None — so this test
    expects None, not an exception.  Any exception that does surface here is a
    real failure (auth, network, rate-limit) and should fail the test.
    """
    print("\n── Test 2: end-of-season probe (week 19, 2025 season) ──")
    print("  (Requesting a week beyond the end of the 2025 schedule.)")
    print("  Expected: None — KeyError('scoreboard') caught inside fetch_week_scoreboard.\n")

    result = fetch_week_scoreboard(query, week=19)

    if result is None:
        print("  Result: None")
        print("  yfpy raised KeyError('scoreboard') internally; function converted it to None.")
        _check("week 19 returns None (end-of-season signal)", True)
    elif len(result) == 0:
        print("  Result: []  (empty list — also a valid stop signal)")
        _check("week 19 returns [] (valid stop signal)", True)
    else:
        print(f"  Result: {len(result)} matchup(s) — unexpected for week 19.")
        for m in result:
            print(f"    status={m['status']!r}  "
                  f"home_score={m['home_score']}  away_score={m['away_score']}")
        _check("week 19 returns None or []", False,
               f"{len(result)} matchup(s) returned unexpectedly")


# ── Test 3: optional DB comparison ───────────────────────────────────────────

def test_db_comparison(yahoo_week1: list[dict]) -> None:
    """
    Compare Yahoo week-1 scores to what's in the DB.
    Runs only when DATABASE_URL is set in the environment.

    Team ID mapping: the DB stores internal Team.id values; Yahoo returns its own
    1-based per-league team IDs.  The seed encodes Yahoo team IDs in each team's
    email as 'yahoo-team-{id}@fantasy-beefs.local', so we JOIN the teams table
    and parse the email to recover the Yahoo ID for each matchup side.
    """
    print("\n── Test 3: DB comparison (week 1) ──")
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("  SKIP  DATABASE_URL not set — cannot compare against seeded data.")
        print("  (Set DATABASE_URL=<postgres_url> to enable this check.)")
        return

    try:
        from sqlalchemy import text as sa_text
        from db.engine_factory import get_engine  # FR-VAL10-af: canonical engine control surface
        engine = get_engine(db_url, connect_args={"connect_timeout": 10})
        with engine.connect() as conn:
            # JOIN teams to recover the Yahoo team ID encoded in each email.
            rows = conn.execute(sa_text(
                "SELECT m.home_team_id, m.away_team_id, "
                "       m.home_score, m.away_score, "
                "       ht.email AS home_email, at.email AS away_email "
                "FROM matchups m "
                "JOIN teams ht ON ht.id = m.home_team_id "
                "JOIN teams at ON at.id = m.away_team_id "
                "WHERE m.week = 1 "
                "ORDER BY m.home_team_id"
            )).fetchall()
    except Exception as e:
        print(f"  SKIP  DB query failed: {e}")
        return

    if not rows:
        print("  SKIP  No week-1 rows found in matchups table.")
        return

    def _yahoo_id_from_email(email: str) -> int | None:
        """Parse Yahoo team ID from 'yahoo-team-{id}@fantasy-beefs.local'."""
        try:
            local = email.split("@")[0]
            if local.startswith("yahoo-team-"):
                return int(local[len("yahoo-team-"):])
        except Exception:
            pass
        return None

    print(f"  DB has {len(rows)} week-1 matchup row(s).")
    print(f"  Yahoo returned {len(yahoo_week1)} week-1 matchup(s).\n")

    yahoo_by_key = {
        (m["home_team_id"], m["away_team_id"]): m for m in yahoo_week1
    }

    discrepancies = 0
    for row in rows:
        db_h, db_a, db_home_score, db_away_score, home_email, away_email = row
        yahoo_h = _yahoo_id_from_email(home_email)
        yahoo_a = _yahoo_id_from_email(away_email)

        if yahoo_h is None or yahoo_a is None:
            print(f"  WARN  Cannot parse Yahoo ID from emails: {home_email!r}, {away_email!r}")
            discrepancies += 1
            continue

        yahoo_m = yahoo_by_key.get((yahoo_h, yahoo_a))
        if yahoo_m is None:
            print(f"  WARN  No Yahoo counterpart for DB ({db_h},{db_a}) = Yahoo ({yahoo_h},{yahoo_a})")
            discrepancies += 1
            continue

        home_ok = abs(yahoo_m["home_score"] - db_home_score) < 0.05
        away_ok = abs(yahoo_m["away_score"] - db_away_score) < 0.05
        ok = home_ok and away_ok
        if not ok:
            discrepancies += 1
        tag = "MATCH" if ok else "DIFF "
        print(f"  {tag}  Yahoo ({yahoo_h:>2} vs {yahoo_a:>2})  "
              f"home DB={db_home_score:.2f} Yahoo={yahoo_m['home_score']:.2f}  "
              f"away DB={db_away_score:.2f} Yahoo={yahoo_m['away_score']:.2f}")

    _check(f"all {len(rows)} week-1 matchups match DB scores",
           discrepancies == 0, f"{discrepancies} discrepancy/ies")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("test_yahoo_scoreboard.py")
    print(f"  league_id={LEAGUE_ID}  game_id={GAME_ID}  (2025 NFL season)")

    query = _build_query()

    yahoo_week1 = test_completed_week(query)
    test_end_of_season(query)
    test_db_comparison(yahoo_week1)

    print(f"\n── Summary: {_pass_count} passed, {_fail_count} failed ──")
    sys.exit(0 if _fail_count == 0 else 1)
