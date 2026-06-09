import json
from yfpy.query import YahooFantasySportsQuery

REGULAR_SEASON_WEEKS = range(1, 15)  # weeks 1-14 (playoffs start week 15)

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
    for week in REGULAR_SEASON_WEEKS:
        matchups = query.get_league_matchups_by_week(week)
        print(f"Week {week}:")
        for matchup in matchups:
            teams = matchup.teams
            if len(teams) >= 2:
                print(f"  {_s(teams[0].name)}  vs  {_s(teams[1].name)}")
        print()
except Exception:
    import traceback
    traceback.print_exc()
