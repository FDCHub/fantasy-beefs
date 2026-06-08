import json
from yfpy.query import YahooFantasySportsQuery

with open("secrets/private.json") as f:
    token = json.load(f)
with open("secrets/yahoo_oauth.json") as f:
    creds = json.load(f)
token["consumer_secret"] = creds["consumer_secret"]

# league_id is required by the constructor but unused by user/game queries
query = YahooFantasySportsQuery(
    league_id="488800",
    game_code="nfl",
    yahoo_access_token_json=token,
    browser_callback=False,
)

games = query.get_user_games()
for game in games:
    try:
        leagues = query.get_user_leagues_by_game_key(game.game_key)
        for league in leagues:
            name = league.name
            if isinstance(name, bytes):
                name = name.decode()
            game_key = league.league_key.split(".l.")[0]
            print(f"season={league.season}  game_key={game_key}  league_id={league.league_id}  name={name}")
    except Exception as e:
        print(f"season={game.season}  game_key={game.game_key}  (skipped: {e})")
