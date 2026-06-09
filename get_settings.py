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
    settings = query.get_league_settings()

    print(f"Playoff start week : {settings.playoff_start_week}")
    print(f"Playoff teams      : {settings.num_playoff_teams}")
    print()

    print("=== Roster Positions ===")
    for rp in settings.roster_positions:
        label = "(bench)" if rp.is_bench else ("(starting)" if rp.is_starting_position else "")
        print(f"  {_s(rp.position):8}  count={rp.count}  {label}")
    print()

    print("=== Scoring Rules ===")
    id_to_name = {stat.stat_id: _s(stat.display_name) for stat in settings.stat_categories.stats}
    for stat in settings.stat_modifiers.stats:
        name = id_to_name.get(stat.stat_id, f"stat_{stat.stat_id}")
        print(f"  {name:30}  {stat.value}")

except Exception:
    import traceback
    traceback.print_exc()
