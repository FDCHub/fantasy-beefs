import json
from yfpy.query import YahooFantasySportsQuery

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
    standings = query.get_league_standings()
    print(f"{'Rank':<5} {'Team':<30} {'W-L-T':<8} {'PF':>8} {'PA':>8}")
    print("-" * 64)
    for team in standings.teams:
        record = f"{team.wins}-{team.losses}-{team.ties}"
        print(f"{str(team.rank):<5} {_s(team.name):<30} {record:<8} {team.points_for:>8.2f} {team.points_against:>8.2f}")
except Exception:
    import traceback
    traceback.print_exc()
