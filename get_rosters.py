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
    roster = query.get_team_roster_by_week(TEAM_ID, WEEK)
    print(f"Team {TEAM_ID} roster — week {WEEK}")
    print(f"{'Name':<30} {'Pos':<10} {'Slot'}")
    print("-" * 54)
    for player in roster.players:
        print(f"{_s(player.full_name):<30} {player.display_position:<10} {player.selected_position_value}")
except Exception:
    import traceback
    traceback.print_exc()
