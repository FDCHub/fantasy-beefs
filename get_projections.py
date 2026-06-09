import json
from yfpy.query import YahooFantasySportsQuery

TEAM_ID = 1
WEEK    = 1

def _s(v):
    return v.decode() if isinstance(v, bytes) else str(v)

with open("secrets/private.json") as f:
    token = json.load(f)
with open("secrets/yahoo_oauth.json") as f:
    creds = json.load(f)
token["consumer_secret"] = creds["consumer_secret"]

query = YahooFantasySportsQuery(
    league_id="488800",
    game_code="nfl",
    game_id=461,
    yahoo_access_token_json=token,
    browser_callback=False,
)

try:
    # Returns ACTUAL (scored) production stats per player per week — raw values such as
    # passing yards, TDs, receptions. These are NOT pre-scored fantasy points; multiply
    # each stat_id value by the league's scoring modifiers (see get_settings.py) to get
    # fantasy points. Yahoo's projected stats (type=projected) are not exposed as a
    # built-in yfpy 17.0.0 method.
    settings  = query.get_league_settings()
    id_to_name = {s.stat_id: _s(s.display_name) for s in settings.stat_categories.stats}

    players = query.get_team_roster_player_stats_by_week(TEAM_ID, WEEK)
    print(f"Team {TEAM_ID} player stats — week {WEEK}  (RAW production, not fantasy points)\n")
    for player in players:
        nonzero = [
            f"{id_to_name.get(s.stat_id, str(s.stat_id))}={s.value}"
            for s in (player.stats or [])
            if s.value is not None and str(s.value) not in ("0", "0.0", "")
        ]
        stat_line = "  ".join(nonzero) if nonzero else "(no stats)"
        print(f"{_s(player.full_name):<28} {player.display_position:<8} {stat_line}")
except Exception:
    import traceback
    traceback.print_exc()
