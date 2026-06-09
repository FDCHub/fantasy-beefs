import json
from dataclasses import dataclass, asdict
from typing import List
import requests
import time
from threading import Lock
from http.client import HTTPException

API_KEY = None
KEY_LOCK = Lock()

@dataclass
class RawProj:
    fpid: str = None
    yahoo_player_id: str = None
    name: str = None
    position: str = None
    team: str = None
    bye_week: int = None
    pass_att: float = 0.0
    pass_yds: float = 0.0
    pass_tds: float = 0.0
    pass_int: float = 0.0
    rush_att: float = 0.0
    rush_yds: float = 0.0
    rush_tds: float = 0.0
    rec_rec: float = 0.0
    rec_yds: float = 0.0
    rec_tds: float = 0.0
    fumbles: float = 0.0
    ret_tds: float = 0.0
    two_pt_tds: float = 0.0

def load_api_key():
    global API_KEY
    with KEY_LOCK:
        if not API_KEY:
            with open("secrets/private.json") as f:
                secrets = json.load(f)
                API_KEY = secrets["fantasypros_api_key"]

def fetch_raw_proj_data(position: str, week: int) -> List[RawProj]:
    url = "https://api.fantasypros.com/public/v2/json/nfl/2025/projections"
    params = {
        "position": position,
        "scoring": "PPR",
        "week": week
    }
    headers = {
        "x-api-key": API_KEY
    }

    response = requests.get(url, params=params, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"HTTP error: {response.url}")

    data = response.json()
    raw_projs = []
    for player in data["players"]:
        proj = RawProj(
            fpid=player.get("fpid"),
            yahoo_player_id=player.get("player_yahoo_id"),
            name=player.get("name"),
            position=player.get("position_id"),
            team=player.get("team_id"),
            bye_week=player.get("bye_week"),
            pass_att=player.get("stats", {}).get("pass_att", 0.0),
            pass_yds=player.get("stats", {}).get("pass_yds", 0.0),
            pass_tds=player.get("stats", {}).get("pass_tds", 0.0),
            pass_int=player.get("stats", {}).get("pass_ints", 0.0),
            rush_att=player.get("stats", {}).get("rush_att", 0.0),
            rush_yds=player.get("stats", {}).get("rush_yds", 0.0),
            rush_tds=player.get("stats", {}).get("rush_tds", 0.0),
            rec_rec=player.get("stats", {}).get("rec_rec", 0.0),
            rec_yds=player.get("stats", {}).get("rec_yds", 0.0),
            rec_tds=player.get("stats", {}).get("rec_tds", 0.0),
            fumbles=player.get("stats", {}).get("fumbles", 0.0),
            ret_tds=player.get("stats", {}).get("ret_tds", 0.0),
            two_pt_tds=player.get("stats", {}).get("2pt_tds", 0.0)
        )
        raw_projs.append(proj)

    return raw_projs

def fetch_projections(week: int) -> List[RawProj]:
    load_api_key()
    positions = ["QB", "RB", "WR", "TE", "K", "DST"]
    all_projs = []

    for pos in positions:
        projs = fetch_raw_proj_data(pos, week)
        all_projs.extend(projs)
        time.sleep(0.3)

    return all_projs

def fetch_projections_by_position(position: str, week: int) -> List[RawProj]:
    load_api_key()
    return fetch_raw_proj_data(position, week)

if __name__ == "__main__":
    projs = fetch_projections(1)
    print(f"Total player count: {len(projs)}")

    positions = ["QB", "RB", "WR", "TE", "K", "DST"]
    for pos in positions:
        pos_players = [p for p in projs if p.position == pos][:3]
        print(f"\n{pos} players ({len(pos_players)} shown):")
        for proj in pos_players:
            print(asdict(proj))

    hurts_proj = next((proj for proj in projs if proj.name == "Jalen Hurts"), None)
    if hurts_proj:
        print("\nJalen Hurts' full stat line:")
        print(asdict(hurts_proj))
