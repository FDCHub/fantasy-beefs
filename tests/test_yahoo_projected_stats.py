"""
Read-only probe: Yahoo Fantasy projected stats endpoint — raw HTTP, no yfpy models.

Confirms whether Yahoo returns per-player projected points for a given team+week,
and identifies the exact JSON field path where the projected value lives.

yfpy gotcha: yfpy's get_team_roster_by_week() only unwraps *actual* scored stats,
not projected stats. This script bypasses yfpy's model wrapper entirely.

No DB writes. No yfpy model objects. Standalone diagnostic.

Usage:  python test_yahoo_projected_stats.py
"""

import base64
import json
import os
import time
import urllib.request
import urllib.error
import urllib.parse

# ── Config ────────────────────────────────────────────────────────────────────

GAME_KEY   = 461
LEAGUE_ID  = "488800"
TEAM_ID    = 11          # any real seeded team; 11 is the first in the league
BASE_URL   = "https://fantasysports.yahooapis.com/fantasy/v2"
TOKEN_URL  = "https://api.login.yahoo.com/oauth2/get_token"

# ── Token loading + refresh ───────────────────────────────────────────────────

def _load_tokens():
    with open("secrets/private.json") as f:
        private = json.load(f)
    with open("secrets/yahoo_oauth.json") as f:
        oauth = json.load(f)
    return private, oauth


def _refresh_if_needed(private: dict, oauth: dict) -> str:
    """Return a valid access token, refreshing via refresh_token if expired."""
    age = time.time() - private.get("token_time", 0)
    if age < 3000:
        # Still fresh (Yahoo tokens expire at 3600s; 3000s gives 10-min buffer)
        print(f"[token] access_token still valid (age {int(age)}s)")
        return private["access_token"]

    print(f"[token] expired (age {int(age)}s) — refreshing ...")
    consumer_key    = oauth["consumer_key"]
    consumer_secret = oauth["consumer_secret"]
    basic = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()

    body = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "redirect_uri":  "oob",
        "refresh_token": private["refresh_token"],
    }).encode()

    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            token = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Token refresh failed ({e.code}): {e.read().decode()}")

    private["access_token"]  = token["access_token"]
    private["refresh_token"] = token.get("refresh_token", private["refresh_token"])
    private["token_time"]    = time.time()
    # Preserve other keys (fantasypros_api_key, guid, etc.)
    with open("secrets/private.json", "w") as f:
        json.dump(private, f, indent=4)
    print("[token] refreshed and saved to secrets/private.json")
    return private["access_token"]


# ── Raw Yahoo API call ────────────────────────────────────────────────────────

def _yahoo_get(path: str, access_token: str) -> dict:
    """GET {BASE_URL}/{path}?format=json and return parsed JSON."""
    url = f"{BASE_URL}/{path}?format=json"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"HTTP {e.code} for {url}\n{body}")


# ── JSON path walker — find first occurrence of a key deep in a tree ──────────

def _find_key(obj, target: str, path: str = "") -> tuple[str, object] | None:
    """DFS through nested dicts/lists; return (dotted_path, value) or None."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else k
            if k == target:
                return here, v
            result = _find_key(v, target, here)
            if result:
                return result
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            result = _find_key(item, target, f"{path}[{i}]")
            if result:
                return result
    return None


# ── Player extractor ──────────────────────────────────────────────────────────

def _extract_players(raw: dict) -> list[dict]:
    """
    Walk the raw Yahoo JSON to find the players list regardless of nesting.
    Yahoo wraps everything under fantasy_content.team[1].roster.0.players
    Returns a flat list of raw player dicts.
    """
    # Locate players list — Yahoo's nesting is: fantasy_content → team → [0,1] → roster → 0 → players
    try:
        fc = raw["fantasy_content"]
        team_node = fc["team"]
        # team_node is a list: [team_meta_dict, {"roster": ...}]
        roster_node = team_node[1]["roster"]
        # roster_node is {"0": {"players": {...}}, "count": N}
        players_node = roster_node["0"]["players"]
        count = int(players_node.get("count", 0))
        return [players_node[str(i)]["player"] for i in range(count)]
    except (KeyError, IndexError, TypeError):
        # Fall back: DFS scan for "players" key
        found = _find_key(raw, "players")
        if found:
            _, pval = found
            if isinstance(pval, dict):
                count = int(pval.get("count", 0))
                try:
                    return [pval[str(i)]["player"] for i in range(count)]
                except Exception:
                    pass
        return []


def _player_name(player_node) -> str:
    """Extract display name from raw player node (list-wrapped by Yahoo)."""
    try:
        meta = player_node[0]   # list of dicts
        for item in meta:
            if isinstance(item, dict) and "name" in item:
                name_obj = item["name"]
                return name_obj.get("full", "(no name)")
    except Exception:
        pass
    # DFS fallback
    found = _find_key(player_node, "full")
    return found[1] if found else "(name not found)"


def _player_position(player_node) -> str:
    try:
        meta = player_node[0]
        for item in meta:
            if isinstance(item, dict) and "display_position" in item:
                return item["display_position"]
    except Exception:
        pass
    found = _find_key(player_node, "display_position")
    return found[1] if found else "?"


def _projected_points(player_node) -> tuple[str | None, object]:
    """
    Return (field_path, value) for the projected points field, or (None, None).
    Candidate keys Yahoo uses for projected totals: 'total', 'projected_points',
    'player_points_value' — we scan all of them and report the actual path.
    """
    # player_node[1] is the stats section (second element of the player list)
    try:
        stats_section = player_node[1]
        # Expected shape: {"player_points": {"coverage_type": "week", "week": "N", "total": "X"}}
        # or: {"player_stats": {"stats": [...], "coverage_type": ...}}
        for key in ("player_points", "player_projected_points"):
            if key in stats_section:
                pts_obj = stats_section[key]
                if isinstance(pts_obj, dict) and "total" in pts_obj:
                    total = pts_obj["total"]
                    if total not in (None, "", "-"):
                        return f"player[1].{key}.total", total
    except (IndexError, TypeError):
        pass

    # DFS fallback over the whole player node
    for candidate in ("total", "player_points_value", "projected_points"):
        result = _find_key(player_node, candidate)
        if result:
            path, val = result
            if val not in (None, "", "-"):
                return path, val

    return None, None


# ── Main probe ────────────────────────────────────────────────────────────────

def probe_week(week: int, access_token: str) -> None:
    team_key = f"{GAME_KEY}.l.{LEAGUE_ID}.t.{TEAM_ID}"

    # Try candidate type values in order — Yahoo's docs are sparse on projected stats
    candidate_types = [
        "projected",
        "week",
        "",   # no type param — use base roster+stats path
    ]

    raw = None
    winning_path = None
    for stat_type in candidate_types:
        if stat_type:
            path = f"team/{team_key}/roster;week={week}/players/stats;type={stat_type}"
        else:
            path = f"team/{team_key}/roster;week={week}/players/stats"
        try:
            raw = _yahoo_get(path, access_token)
            winning_path = path
            break
        except RuntimeError as e:
            err_str = str(e)
            print(f"  [type={stat_type!r}] {err_str.splitlines()[0]}")

    print(f"\n{'='*60}")
    print(f"Week {week}: GET {BASE_URL}/{winning_path or '(all failed)'}")
    print("=" * 60)

    if raw is None:
        print("  All candidate type values rejected by Yahoo — see errors above.")
        return

    players = _extract_players(raw)
    total   = len(players)
    print(f"  Total players on roster : {total}")

    if total == 0:
        print("  NOT FOUND: no players array located in response")
        print(f"  Raw keys at top level   : {list(raw.keys())}")
        try:
            print(f"  fantasy_content keys    : {list(raw['fantasy_content'].keys())}")
        except Exception:
            pass
        return

    # Scan all players for projected points
    mapped   = 0
    unmapped = 0
    field_path_seen = None
    preview  = []

    for p in players:
        name  = _player_name(p)
        pos   = _player_position(p)
        fpath, val = _projected_points(p)

        if fpath is not None:
            mapped += 1
            if field_path_seen is None:
                field_path_seen = fpath
            if len(preview) < 3:
                preview.append((name, pos, val, fpath))
        else:
            unmapped += 1

    print(f"  Players with projected pts: {mapped} / {total}")
    print(f"  Players WITHOUT proj pts  : {unmapped} / {total}")

    if field_path_seen:
        print(f"  Field path (first match)  : {field_path_seen}")
    else:
        print("  NOT FOUND: projected-points field absent in all player nodes")

    print(f"\n  First {len(preview)} players with projected points:")
    print(f"  {'Name':<28} {'Pos':<6} {'Proj Pts':<12} Field path")
    print(f"  {'-'*28} {'-'*6} {'-'*12} {'-'*40}")
    for name, pos, val, fp in preview:
        print(f"  {name:<28} {pos:<6} {str(val):<12} {fp}")

    if unmapped and mapped == 0:
        print(f"\n  NOT FOUND — dumping raw player[0][1] for inspection:")
        try:
            print(json.dumps(players[0][1], indent=4)[:800])
        except Exception:
            print(json.dumps(players[0], indent=4)[:800])


def main() -> None:
    print("\ntest_yahoo_projected_stats.py — raw HTTP projected stats probe")
    print(f"League: {LEAGUE_ID}  |  game_key: {GAME_KEY}  |  team_id: {TEAM_ID}")

    private, oauth = _load_tokens()
    access_token   = _refresh_if_needed(private, oauth)

    for week in (1, 10):
        probe_week(week, access_token)

    print("\nDone.")


if __name__ == "__main__":
    main()
