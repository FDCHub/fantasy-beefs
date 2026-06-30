#!/usr/bin/env python3
"""
get_real_league_data.py  —  READ-ONLY Yahoo data verification

Pulls all 12 teams and their week-N rosters from the real Yahoo league
(CULV Appreciation Society, league_id=488800) and prints a summary.
No database writes of any kind.

Usage:  python get_real_league_data.py [week]    (default: week 1)

Sanity check enforced:
  - All player positions are read from player.display_position (actual position)
  - NOT from player.selected_position_value (lineup slot — e.g. FLEX/BN/W-R-T)
  - Any position value outside {QB, RB, WR, TE, K, DEF} is flagged as a warning.
"""

import json
import sys
import traceback
from collections import defaultdict

from yfpy.query import YahooFantasySportsQuery

LEAGUE_ID      = "488800"
GAME_CODE      = "nfl"
GAME_ID        = 461
WEEK           = int(sys.argv[1]) if len(sys.argv) > 1 else 1
VALID_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}


def _s(v) -> str:
    """Decode bytes → str, pass str through, convert None to empty string."""
    if v is None:
        return ""
    return v.decode() if isinstance(v, bytes) else str(v)


def _build_query() -> YahooFantasySportsQuery:
    with open("secrets/private.json") as f:
        token = json.load(f)
    with open("secrets/yahoo_oauth.json") as f:
        creds = json.load(f)
    # yfpy gotcha: consumer_secret must be merged from the OAuth creds file
    token["consumer_secret"] = creds["consumer_secret"]
    return YahooFantasySportsQuery(
        league_id=LEAGUE_ID,
        game_code=GAME_CODE,
        game_id=GAME_ID,
        yahoo_access_token_json=token,
        browser_callback=False,
    )


def _owner_name(team) -> str:
    """Extract nickname from team.managers list, with fallback."""
    try:
        managers = team.managers
        if managers:
            return _s(managers[0].nickname)
    except Exception:
        pass
    try:
        return _s(team.manager.nickname)
    except Exception:
        return "?"


def _injury_label(player) -> str:
    """Return a human-readable injury label, or empty string if healthy."""
    full = _s(getattr(player, "status_full", None))
    if full:
        return full
    code = _s(getattr(player, "status", None))
    return code  # e.g. "Q", "NA", ""


def main() -> None:
    print(f"\n{'='*72}")
    print(f"  CULV Appreciation Society — Yahoo league {LEAGUE_ID}  |  Week {WEEK}")
    print(f"{'='*72}")

    query = _build_query()

    # ── Fetch all teams ───────────────────────────────────────────────────────
    print("\nFetching team list ...", end="", flush=True)
    try:
        teams = query.get_league_teams()
    except Exception as e:
        print(f"\nFATAL: could not fetch team list: {e}")
        traceback.print_exc()
        sys.exit(1)

    print(f" {len(teams)} teams found.\n")

    # ── Team summary header ───────────────────────────────────────────────────
    print(f"  {'ID':<4} {'Team Name':<32} {'Owner':<25} {'Players':>7}")
    print(f"  {'-'*4} {'-'*32} {'-'*25} {'-'*7}")

    roster_data: list[dict] = []     # accumulate all players across all teams
    position_counts: dict[str, int] = defaultdict(int)
    unknown_position_players: list[dict] = []
    failed_teams: list[tuple[int, str, str]] = []

    for team in teams:
        team_id   = int(team.team_id)
        team_name = _s(team.name)
        owner     = _owner_name(team)

        print(f"  {team_id:<4} {team_name:<32} {owner:<25}", end="", flush=True)

        try:
            roster = query.get_team_roster_by_week(team_id, WEEK)
            players = getattr(roster, "players", []) or []

            print(f" {len(players):>7}")

            for p in players:
                name     = _s(p.full_name)
                # Use display_position (real position) NOT selected_position_value (lineup slot)
                disp_pos = _s(p.display_position)
                slot     = _s(p.selected_position_value)
                injury   = _injury_label(p)

                # Primary position: first value if comma-separated (e.g. "WR,TE" → "WR")
                primary_pos = disp_pos.split(",")[0].strip()

                position_counts[primary_pos] += 1

                row = {
                    "team_id":    team_id,
                    "team_name":  team_name,
                    "owner":      owner,
                    "name":       name,
                    "disp_pos":   disp_pos,      # full display string, may be "WR,TE"
                    "primary_pos": primary_pos,  # parsed first position
                    "slot":       slot,
                    "injury":     injury,
                }
                roster_data.append(row)

                if primary_pos not in VALID_POSITIONS:
                    unknown_position_players.append(row)

        except Exception as e:
            print(f"  ERROR")
            err_msg = str(e)
            failed_teams.append((team_id, team_name, err_msg))
            traceback.print_exc()

    # ── Per-team roster tables ────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print(f"  ROSTER DETAIL  —  Week {WEEK}")
    print(f"{'='*72}")

    current_team_id = None
    for row in roster_data:
        if row["team_id"] != current_team_id:
            current_team_id = row["team_id"]
            print(f"\n  Team {row['team_id']}: {row['team_name']}  ({row['owner']})")
            print(f"  {'Player Name':<30} {'Pos':<10} {'Slot':<10} Injury")
            print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*20}")

        inj   = row["injury"] or "—"
        pos   = row["disp_pos"]
        slot  = row["slot"]
        flag  = "  <-- UNEXPECTED POS" if row["primary_pos"] not in VALID_POSITIONS else ""
        print(f"  {row['name']:<30} {pos:<10} {slot:<10} {inj}{flag}")

    # ── Errors for failed teams ───────────────────────────────────────────────
    if failed_teams:
        print(f"\n{'='*72}")
        print(f"  FAILED ROSTER FETCHES")
        print(f"{'='*72}")
        for tid, tname, err in failed_teams:
            print(f"  Team {tid} ({tname}): {err}")

    # ── Global summary ────────────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print(f"  SUMMARY")
    print(f"{'='*72}")
    print(f"  League:          {LEAGUE_ID}  (CULV Appreciation Society)")
    print(f"  Week:            {WEEK}")
    print(f"  Teams fetched:   {len(teams) - len(failed_teams)} / {len(teams)}")
    print(f"  Total players:   {len(roster_data)}")

    print(f"\n  Position breakdown (from display_position — real positions):")
    for pos in sorted(position_counts):
        flag = "  <-- NOT in valid set" if pos not in VALID_POSITIONS else ""
        print(f"    {pos:<10} {position_counts[pos]:>3}{flag}")

    if unknown_position_players:
        print(f"\n  *** WARNING: {len(unknown_position_players)} player(s) with unexpected position values ***")
        print(f"  This may indicate slot-vs-position confusion. Investigate:")
        for row in unknown_position_players:
            print(f"    Team {row['team_id']:>2} | {row['name']:<30} | "
                  f"display_position={row['disp_pos']!r}  slot={row['slot']!r}")
    else:
        print(f"\n  Position sanity check PASSED — all positions in {{QB, RB, WR, TE, K, DEF}}.")
        print(f"  No slot-vs-position confusion detected.")

    print()


if __name__ == "__main__":
    main()
