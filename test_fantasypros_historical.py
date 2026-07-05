"""
Read-only probe: FantasyPros historical projections API.
Checks two weeks (1 and 10) for QB PPR projections in 2025.

API key resolution order:
  1. Env var FANTASYPROS_API_KEY
  2. secrets/private.json -> "fantasypros_api_key"
"""

import json
import os
import urllib.request

# ── Key resolution ────────────────────────────────────────────────────────────

api_key = os.environ.get("FANTASYPROS_API_KEY")

if api_key:
    print("[key] loaded from env var FANTASYPROS_API_KEY")
else:
    secrets_path = os.path.join(os.path.dirname(__file__), "secrets", "private.json")
    try:
        with open(secrets_path) as f:
            secrets = json.load(f)
        api_key = secrets.get("fantasypros_api_key")
        if api_key:
            print('[key] loaded from secrets/private.json -> "fantasypros_api_key"')
        else:
            print("[key] FANTASYPROS_API_KEY not set and not found in secrets/private.json")
            print(f"      keys present in private.json: {list(secrets.keys())}")
    except FileNotFoundError:
        print(f"[key] FANTASYPROS_API_KEY not set and {secrets_path} not found")

if not api_key:
    raise SystemExit("No API key available — aborting.")

# ── Probe ─────────────────────────────────────────────────────────────────────

BASE_URL = "https://api.fantasypros.com/public/v2/json/nfl/2025/projections"

for week in (1, 10):
    url = f"{BASE_URL}?position=QB&scoring=PPR&week={week}"
    print(f"\n{'='*60}")
    print(f"Week {week}: GET {url}")
    print("=" * 60)

    req = urllib.request.Request(url, headers={"x-api-key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            raw = resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read()
    except Exception as e:
        print(f"  [error] {e}")
        continue

    print(f"  status      : {status}")
    print(f"  body non-empty: {bool(raw)}")

    if not raw:
        print("  (empty response)")
        continue

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [json error] {e}")
        print(f"  raw (first 200 chars): {raw[:200]}")
        continue

    if not isinstance(data, dict):
        print(f"  top-level type: {type(data).__name__}")
        print(f"  value: {str(data)[:300]}")
        continue

    print(f"  top-level keys: {list(data.keys())}")

    # Locate the players array — FantasyPros wraps it differently by endpoint
    players = None
    for candidate in ("projections", "players", "data", "results"):
        if candidate in data and isinstance(data[candidate], list):
            players = data[candidate]
            print(f"  players array : data['{candidate}'] ({len(players)} players)")
            break

    if players is None:
        print("  (no recognised players array; full response below)")
        print(f"  {json.dumps(data, indent=2)[:600]}")
        continue

    if not players:
        print("  (players array is empty)")
        continue

    first = players[0]
    name = (
        first.get("player_name")
        or first.get("name")
        or first.get("player", {}).get("name")
        or first.get("player", {}).get("player_name")
        or "(name field not found)"
    )
    print(f"  first player  : {name}")
    print(f"  raw fields    : {json.dumps(first, indent=4)[:800]}")

    if "public_api_limited" in data:
        print(f"  public_api_limited: {data['public_api_limited']}")

    stats = first.get("stats", {})
    if "player_yahoo_id" in first:
        print(f"  player_yahoo_id (top-level): YES — {first['player_yahoo_id']}")
    elif "player_yahoo_id" in stats:
        print(f"  player_yahoo_id (in stats): YES — {stats['player_yahoo_id']}")
    else:
        print("  player_yahoo_id: NO (not in top-level player or stats{})")
