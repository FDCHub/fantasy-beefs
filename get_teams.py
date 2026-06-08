import json
from yfpy.query import YahooFantasySportsQuery

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

teams = query.get_league_teams()
for team in teams:
    name = team.name
    if isinstance(name, bytes):
        name = name.decode()
    print(name)
