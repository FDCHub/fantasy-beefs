#!/usr/bin/env python3
"""
get_injury_statuses.py  —  READ-ONLY injury status audit

Pulls every team's full roster for weeks 1-N and collects every distinct
(status_code, status_full) pair that yfpy returns from Yahoo, with counts.

Goal: establish ground truth for what injury strings the API actually
returns before deciding how to map them into Projection.injury_status
(whose schema is: None | out | ir | doubtful | questionable).

Output:
  1. All distinct (code, full_text) pairs with occurrence counts and their
     auto-mapped bucket (where unambiguous).
  2. Separate "NEEDS MAPPING DECISION" section for anything that doesn't
     clearly map to one of the four stored buckets.
  3. One example player per unknown pair so the mapping call is concrete.

No database writes. Do not commit before review.

Usage:  python get_injury_statuses.py [max_week]    (default: weeks 1-4)
"""

import json
import sys
import traceback
from collections import defaultdict

from yfpy.query import YahooFantasySportsQuery

LEAGUE_ID  = "488800"
GAME_CODE  = "nfl"
GAME_ID    = 461
MAX_WEEK   = int(sys.argv[1]) if len(sys.argv) > 1 else 4
WEEKS      = list(range(1, MAX_WEEK + 1))
TEAMS      = list(range(1, 13))

# Conservative auto-map: only the five cases we are 100% certain about.
# Anything outside these goes to NEEDS MAPPING DECISION.
# Keys are the Yahoo short-code strings yfpy returns in player.status.
_CERTAIN_CODE_MAP: dict[str, str | None] = {
    "":   None,          # healthy — store as NULL in DB
    "Q":  "questionable",
    "D":  "doubtful",
    "O":  "out",
    "IR": "ir",
}


def _s(v) -> str:
    """Decode bytes → str; pass str through; convert None to ''."""
    if v is None:
        return ""
    return v.decode() if isinstance(v, bytes) else str(v)


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


def main() -> None:
    query = _build_query()

    # (status_code, status_full) → count of player-week observations
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)

    # (status_code, status_full) → first example player name seen
    pair_example: dict[tuple[str, str], str] = {}

    errors: list[str] = []
    total_obs = 0

    print(f"Fetching weeks {WEEKS[0]}–{WEEKS[-1]}, teams 1–12  ({len(WEEKS) * len(TEAMS)} calls)\n")

    for week in WEEKS:
        print(f"  Week {week}:", end="", flush=True)
        for team_id in TEAMS:
            print(f" t{team_id}", end="", flush=True)
            try:
                roster = query.get_team_roster_by_week(team_id, week)
                players = getattr(roster, "players", []) or []
                for p in players:
                    code = _s(getattr(p, "status",      None))
                    full = _s(getattr(p, "status_full", None))
                    name = _s(getattr(p, "full_name",   None))
                    key  = (code, full)
                    pair_counts[key] += 1
                    if key not in pair_example:
                        pair_example[key] = name
                    total_obs += 1
            except Exception as e:
                err = f"Week {week} team {team_id}: {e}"
                errors.append(err)
                print(f"[ERR]", end="", flush=True)
        print()  # newline after each week's progress

    # ── Split into auto-mapped vs. needs-decision ─────────────────────────────
    mapped:   list[tuple[str, str, int, str | None]] = []   # code, full, count, bucket
    unmapped: list[tuple[str, str, int, str]] = []          # code, full, count, example

    for (code, full), count in pair_counts.items():
        if code in _CERTAIN_CODE_MAP:
            mapped.append((code, full, count, _CERTAIN_CODE_MAP[code]))
        else:
            unmapped.append((code, full, count, pair_example[(code, full)]))

    # Sort: mapped by bucket name then full string; unmapped by full string
    mapped.sort(key=lambda r: (r[3] or "", r[1]))
    unmapped.sort(key=lambda r: r[1].lower())

    # ── Full list ─────────────────────────────────────────────────────────────
    print(f"\n{'='*78}")
    print(f"  ALL DISTINCT (status_code, status_full) PAIRS")
    print(f"  {total_obs:,} total player-week observations  |  "
          f"{len(pair_counts)} distinct pairs  |  "
          f"weeks {WEEKS[0]}–{WEEKS[-1]}")
    print(f"{'='*78}")
    print(f"\n  Auto-mapped pairs ({len(mapped)}):\n")
    print(f"  {'Code':<8} {'Count':>5}  {'DB bucket':>15}  Status Full")
    print(f"  {'-'*8} {'-'*5}  {'-'*15}  {'-'*45}")
    for code, full, count, bucket in mapped:
        disp_code = repr(code)
        disp_full = full if full else "(empty)"
        disp_bucket = bucket if bucket is not None else "NULL (healthy)"
        print(f"  {disp_code:<8} {count:>5}  {disp_bucket:>15}  {disp_full}")

    if unmapped:
        print(f"\n{'='*78}")
        print(f"  NEEDS MAPPING DECISION  ({len(unmapped)} pair(s))")
        print(f"{'='*78}")
        print(f"  These codes are outside the certain map {{Q, D, O, IR, ''}}.")
        print(f"  Each needs a deliberate choice: assign to an existing bucket,")
        print(f"  add a new bucket, or treat as NULL (healthy / no adjustment).")
        print()
        print(f"  {'Code':<8} {'Count':>5}  {'Status Full':<45}  Example player")
        print(f"  {'-'*8} {'-'*5}  {'-'*45}  {'-'*28}")
        for code, full, count, example in unmapped:
            disp_full = full if full else "(empty)"
            print(f"  {repr(code):<8} {count:>5}  {disp_full:<45}  {example}")
    else:
        print(f"\n  All observed pairs map to existing buckets. No decisions needed.")

    # ── Errors ────────────────────────────────────────────────────────────────
    if errors:
        print(f"\n{'='*78}")
        print(f"  FETCH ERRORS ({len(errors)})")
        print(f"{'='*78}")
        for e in errors:
            print(f"  {e}")

    print()


if __name__ == "__main__":
    print(f"\nInjury Status Audit — CULV Appreciation Society  (READ ONLY)\n")
    main()
