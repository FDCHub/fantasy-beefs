"""
scripts/resolve_player_nfl_teams.py

Read-only: resolves an NFL team abbreviation for every player in our players
table using four matching passes against player_id_map. Prints a coverage report.
No DB writes, no file writes.

Importable API:
    from scripts.resolve_player_nfl_teams import build_nfl_team_mapping
    mapping = build_nfl_team_mapping(conn)   # -> dict[int, str | None]

Passes:
  0. Exact name match -> real team (145 baseline)
  1. DEF players -- hardcoded city/nickname -> NFL abbreviation (14 players)
  2a. Suffix-stripped match (strip Jr./Sr./II/III from both sides)
  2b. Period-normalized match (remove dots: "D.J." -> "DJ")
  3. FA players -- in crosswalk but team='FA' (stale/unsigned as of 2026 offseason)
                   no NFL team data exists in our DB -> returns None
"""

import os
import re

from sqlalchemy import text

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Set it in the environment before running this script."
    )

# -- Bucket 1: DEF player name -> NFL team abbreviation -----------------------
DEF_MAP: dict[str, str] = {
    "bills":      "BUF",
    "broncos":    "DEN",
    "cardinals":  "ARI",
    "chargers":   "LAC",
    "chiefs":     "KC",
    "commanders": "WAS",
    "eagles":     "PHI",
    "jets":       "NYJ",
    "lions":      "DET",
    "packers":    "GB",
    "rams":       "LAR",
    "ravens":     "BAL",
    "steelers":   "PIT",
    "vikings":    "MIN",
}

# -- Name normalization --------------------------------------------------------
_SUFFIX_RE = re.compile(r"\s+(Jr\.?|Sr\.?|I{2,3}|IV)$", re.IGNORECASE)

def _strip_suffix(name: str) -> str:
    return _SUFFIX_RE.sub("", name.strip()).strip()

def _strip_dots(name: str) -> str:
    """'D.J. Moore' -> 'DJ Moore'"""
    return re.sub(r"\.", "", name).strip()

def _normalize(name: str) -> str:
    return _strip_dots(_strip_suffix(name))


# -- Core lookup builder -------------------------------------------------------

def _build_team_lookup(
    map_rows: list,
) -> tuple[dict[str, str], set[str]]:
    """
    Returns:
      team_lookup  -- name-key -> best real NFL team abbreviation (FA excluded)
      in_map       -- set of name-keys that appear in player_id_map at all
    """
    team_lookup: dict[str, str] = {}
    in_map: set[str] = set()

    for row in map_rows:
        raw_name: str = (row[0] or "").strip()
        team: str | None = row[1]
        if not raw_name:
            continue
        for key in {
            raw_name.lower(),
            _strip_suffix(raw_name).lower(),
            _strip_dots(raw_name).lower(),
            _normalize(raw_name).lower(),
        }:
            in_map.add(key)
            if team and team not in ("FA", ""):
                if key not in team_lookup:
                    team_lookup[key] = team

    return team_lookup, in_map


def _resolve_one(
    pid: int,
    name: str,
    position: str,
    team_lookup: dict[str, str],
    in_map: set[str],
) -> dict:
    """Return a resolution result dict for a single player."""
    keys = {
        "exact":     name.lower().strip(),
        "suffix":    _strip_suffix(name).lower(),
        "dots":      _strip_dots(name).lower(),
        "full_norm": _normalize(name).lower(),
    }

    if position == "DEF":
        abbr = DEF_MAP.get(name.lower().strip())
        return {"id": pid, "name": name, "position": position,
                "team": abbr, "bucket": 1, "method": "DEF_MAP"}

    if team_lookup.get(keys["exact"]):
        return {"id": pid, "name": name, "position": position,
                "team": team_lookup[keys["exact"]], "bucket": 0, "method": "exact"}

    if team_lookup.get(keys["suffix"]):
        return {"id": pid, "name": name, "position": position,
                "team": team_lookup[keys["suffix"]], "bucket": 2, "method": "suffix"}

    for method_key, label in (("dots", "dots"), ("full_norm", "suffix+dots")):
        if team_lookup.get(keys[method_key]):
            return {"id": pid, "name": name, "position": position,
                    "team": team_lookup[keys[method_key]], "bucket": 2, "method": label}

    in_any = any(k in in_map for k in keys.values())
    return {"id": pid, "name": name, "position": position,
            "team": None, "bucket": 3 if in_any else -1,
            "method": "crosswalk_FA" if in_any else "no_match"}


# -- Public API ---------------------------------------------------------------

def build_nfl_team_mapping(conn) -> dict[int, str | None]:
    """
    Query players + player_id_map via conn and return {player_id: nfl_team}.
    nfl_team is None for FA/unresolved players.
    Does NOT apply manual overrides — callers do that on top.
    """
    players  = conn.execute(
        text("SELECT id, name, position FROM players ORDER BY id")
    ).fetchall()
    map_rows = conn.execute(
        text("SELECT name, team FROM player_id_map")
    ).fetchall()

    team_lookup, in_map = _build_team_lookup(map_rows)
    result: dict[int, str | None] = {}
    for pid, name, position in players:
        r = _resolve_one(pid, name, position, team_lookup, in_map)
        result[pid] = r["team"]
    return result


# -- Main (report only) -------------------------------------------------------

def main() -> None:
    # FR-VAL10-af: route through the canonical engine control surface. This
    # script has no repo-root bootstrap at module scope (it is importable as
    # scripts.resolve_player_nfl_teams, where the importer supplies the path),
    # so bootstrap here for the direct-execution path before importing db.*.
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db.engine_factory import get_engine

    engine = get_engine(DB_URL, connect_args={"connect_timeout": 15})

    with engine.connect() as conn:
        players  = conn.execute(
            text("SELECT id, name, position FROM players ORDER BY position, name")
        ).fetchall()
        map_rows = conn.execute(
            text("SELECT name, team FROM player_id_map")
        ).fetchall()

    team_lookup, in_map = _build_team_lookup(map_rows)

    results:          list[dict]               = []
    bucket1_resolved: list[tuple[str, str]]    = []
    bucket2_recovered:list[tuple[str,str,str]] = []
    bucket3_fa:       list[tuple[int,str,str]] = []
    still_unresolved: list[tuple[int,str,str]] = []

    for pid, name, position in players:
        r = _resolve_one(pid, name, position, team_lookup, in_map)
        results.append(r)
        if r["bucket"] == 1:
            bucket1_resolved.append((name, r["team"]))
        elif r["bucket"] == 2:
            bucket2_recovered.append((name, r["team"], r["method"]))
        elif r["bucket"] == 3:
            bucket3_fa.append((pid, name, position))
        elif r["bucket"] == -1:
            still_unresolved.append((pid, name, position))

    total    = len(players)
    resolved = sum(1 for r in results if r["team"] is not None)
    baseline = sum(1 for r in results if r["bucket"] == 0)

    print("=" * 60)
    print("  PLAYER -> NFL TEAM RESOLUTION REPORT")
    print("=" * 60)
    print(f"\n  Total players:               {total}")
    print(f"  Resolved to real NFL team:   {resolved}  ({100*resolved//total}%)")
    print(f"    Pass 0 (exact match):      {baseline}")
    print(f"    Bucket 1 (DEF map):        {len(bucket1_resolved)}")
    print(f"    Bucket 2 (suffix/dots):    {len(bucket2_recovered)}")
    print(f"  Bucket 3 (FA / stale):       {len(bucket3_fa)}  -> REQUIRES MANUAL OVERRIDE")
    print(f"  Still unresolved:            {len(still_unresolved)}")

    print("\n-- BUCKET 1: DEF players ------------------------------------------")
    for name, abbr in sorted(bucket1_resolved):
        print(f"  {name:<22s}  ->  {abbr}")

    print("\n-- BUCKET 2: suffix / dot-removal recoveries ----------------------")
    if bucket2_recovered:
        for name, abbr, method in sorted(bucket2_recovered, key=lambda r: r[0]):
            norm = _normalize(name)
            print(f"  {name:<30s}  [{method:<12s}]  ->  {abbr}  (norm: {norm!r})")
    else:
        print("  (none)")

    print("\n-- BUCKET 3: FA / stale team (None returned) ----------------------")
    for pid, name, pos in sorted(bucket3_fa, key=lambda r: r[1]):
        print(f"  id={pid:4d}  {pos:6s}  {name}")

    if still_unresolved:
        print("\n-- STILL UNRESOLVED -----------------------------------------------")
        for pid, name, pos in still_unresolved:
            print(f"  id={pid:4d}  {pos:6s}  {name}")
    else:
        print("\n-- No players unresolved after all passes --------------------------")

    print("\n-- FULL RESOLVED TABLE --------------------------------------------")
    for r in sorted(results, key=lambda x: (x["position"], x["name"])):
        if r["team"]:
            tag = f"[B{r['bucket']}]" if r["bucket"] > 0 else "    "
            print(f"  {tag}  {r['position']:6s}  {r['name']:<30s}  {r['team']:<6s}  ({r['method']})")


if __name__ == "__main__":
    main()
