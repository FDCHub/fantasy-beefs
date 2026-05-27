from pathlib import Path
from yfpy.query import YahooFantasySportsQuery

query = YahooFantasySportsQuery(
    auth_dir=Path("secrets"),
    league_id="488800",
    game_code="nfl",
    yahoo_consumer_key=None,
    yahoo_consumer_secret=None,
)

teams = query.get_league_teams()
for team in teams:
    name = team.name
    if isinstance(name, bytes):
        name = name.decode()
    print(name)
