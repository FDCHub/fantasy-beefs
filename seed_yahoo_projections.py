#!/usr/bin/env python3
"""
seed_yahoo_projections.py  —  Backfill Projection table with Yahoo fantasy
points for every player × team × week of the 2025 season.

Uses the confirmed-working raw HTTP endpoint (no yfpy model wrapper):
  GET /team/{team_key}/roster;week={week}/players/stats
  (no type= param — type=projected/week/projected_week all return HTTP 400)

Field path for projected points: player[2].player_points.total

SAFE:
  - Only writes source='yahoo' rows — never touches source='fantasypros' rows.
  - Upsert on (player_id, week, season=2025, source='yahoo'):
    - Existing row: updates projected_points only; actual_points untouched.
    - New row: inserts with actual_points=0.0 (updated at week settlement).
  - Requires --confirm flag before any DB write.

USAGE:
  python seed_yahoo_projections.py              # dry-run: prints plan, no writes
  python seed_yahoo_projections.py --confirm    # live write to DATABASE_URL (or local SQLite)

  Optional: --weeks 1-17      (default: all weeks 1-17)
            --team 11          (single team only, for spot-checking)
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

# ── Config ────────────────────────────────────────────────────────────────────

GAME_KEY   = 461
LEAGUE_ID  = "488800"
SEASON     = 2025
ALL_WEEKS  = list(range(1, 18))   # weeks 1-17
API_DELAY  = 0.5                  # seconds between Yahoo API calls
BASE_URL   = "https://fantasysports.yahooapis.com/fantasy/v2"
TOKEN_URL  = "https://api.login.yahoo.com/oauth2/get_token"

# ── CLI args ──────────────────────────────────────────────────────────────────

CONFIRM      = "--confirm" in sys.argv
SINGLE_TEAM  = None
WEEKS        = ALL_WEEKS

for i, arg in enumerate(sys.argv[1:], 1):
    if arg == "--team" and i < len(sys.argv) - 1:
        SINGLE_TEAM = int(sys.argv[i + 1])
    if arg == "--weeks" and i < len(sys.argv) - 1:
        parts = sys.argv[i + 1].split("-")
        WEEKS = list(range(int(parts[0]), int(parts[-1]) + 1))

# ── DB imports (after arg parsing so --help-style usage doesn't trigger engine) ─

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db.schema import Projection, Player, Team, SessionLocal

# ── Token loading + refresh ───────────────────────────────────────────────────

def _load_tokens() -> tuple[dict, dict]:
    with open("secrets/private.json") as f:
        private = json.load(f)
    with open("secrets/yahoo_oauth.json") as f:
        oauth = json.load(f)
    return private, oauth


def _get_access_token(private: dict, oauth: dict) -> str:
    age = time.time() - private.get("token_time", 0)
    if age < 3000:
        print(f"[token] valid (age {int(age)}s)")
        return private["access_token"]

    print(f"[token] expired (age {int(age)}s) — refreshing ...")
    basic = base64.b64encode(
        f"{oauth['consumer_key']}:{oauth['consumer_secret']}".encode()
    ).decode()
    body = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "redirect_uri":  "oob",
        "refresh_token": private["refresh_token"],
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body,
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type":  "application/x-www-form-urlencoded"},
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
    with open("secrets/private.json", "w") as f:
        json.dump(private, f, indent=4)
    print("[token] refreshed and saved.")
    return private["access_token"]

# ── Raw Yahoo API call ────────────────────────────────────────────────────────

def _yahoo_get(path: str, token: str) -> dict:
    url = f"{BASE_URL}/{path}?format=json"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:300]}")

# ── JSON parsing (same as test_yahoo_projected_stats.py, confirmed working) ───

def _extract_players(raw: dict) -> list:
    try:
        team_node    = raw["fantasy_content"]["team"]
        roster_node  = team_node[1]["roster"]
        players_node = roster_node["0"]["players"]
        count        = int(players_node.get("count", 0))
        return [players_node[str(i)]["player"] for i in range(count)]
    except (KeyError, IndexError, TypeError):
        return []


def _player_name(p) -> str:
    try:
        for item in p[0]:
            if isinstance(item, dict) and "name" in item:
                return item["name"].get("full", "")
    except Exception:
        pass
    return ""


def _player_yahoo_key(p) -> str | None:
    """Return Yahoo player_key (e.g. '461.p.30977') from player metadata."""
    try:
        for item in p[0]:
            if isinstance(item, dict) and "player_key" in item:
                return str(item["player_key"])
    except Exception:
        pass
    return None


def _projected_pts(p) -> float | None:
    """
    Scan all dict elements of the player list for player_points.total.
    Yahoo's player node length varies by team (3 or 4+ elements depending
    on whether selected_position/is_editable are included), so don't hardcode index.
    """
    for item in p:
        if not isinstance(item, dict):
            continue
        pts_obj = item.get("player_points")
        if pts_obj and isinstance(pts_obj, dict):
            total = pts_obj.get("total")
            if total is not None and total != "" and total != "-":
                try:
                    return float(total)
                except (ValueError, TypeError):
                    pass
    return None

# ── DB helpers ────────────────────────────────────────────────────────────────

def _build_player_name_map(session) -> dict[str, int]:
    """Return {player_name_lower: player_id} for all players in DB."""
    rows = session.query(Player.id, Player.name).all()
    return {name.lower(): pid for pid, name in rows}


def _yahoo_team_id_from_email(email: str) -> int | None:
    """Extract Yahoo team ID from 'yahoo-team-{id}@fantasy-beefs.local'."""
    try:
        prefix = "yahoo-team-"
        local  = email.split("@")[0]
        if local.startswith(prefix):
            return int(local[len(prefix):])
    except Exception:
        pass
    return None


def _get_yahoo_team_ids(session) -> list[int]:
    """Return sorted list of Yahoo team IDs from the teams table."""
    teams = session.query(Team.email).all()
    ids   = []
    for (email,) in teams:
        yid = _yahoo_team_id_from_email(email)
        if yid is not None:
            ids.append(yid)
    return sorted(ids)


def _upsert_projection(
    session,
    player_id: int,
    week: int,
    proj_pts: float,
    dry_run: bool,
) -> str:
    """
    UPSERT one Projection row for source='yahoo'.
    Returns 'inserted' | 'updated' | 'dry_insert' | 'dry_update'.
    Does NOT commit — caller commits in batches.
    """
    existing = (
        session.query(Projection)
        .filter_by(player_id=player_id, week=week, season=SEASON, source="yahoo")
        .first()
    )
    if existing:
        if not dry_run:
            existing.projected_points = proj_pts
        return "dry_update" if dry_run else "updated"
    else:
        if not dry_run:
            session.add(Projection(
                player_id        = player_id,
                week             = week,
                season           = SEASON,
                projected_points = proj_pts,
                actual_points    = 0.0,    # placeholder; updated at week settlement
                source           = "yahoo",
            ))
        return "dry_insert" if dry_run else "inserted"

# ── Summary state ─────────────────────────────────────────────────────────────

@dataclass
class RunStats:
    total_inserted:  int = 0
    total_updated:   int = 0
    total_unmatched: int = 0
    total_no_pts:    int = 0
    failed_calls:    list[str] = field(default_factory=list)
    unmatched:       list[str] = field(default_factory=list)  # "Name (week W)"

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    dry_run = not CONFIRM

    print("\nseed_yahoo_projections.py")
    print(f"  season={SEASON}  weeks={WEEKS[0]}-{WEEKS[-1]}  "
          f"single_team={SINGLE_TEAM}  mode={'DRY-RUN' if dry_run else 'LIVE WRITE'}")
    if dry_run:
        print("\n  !! DRY-RUN — pass --confirm to write to DB\n")
    else:
        print("\n  !! LIVE WRITE — writing source='yahoo' rows to DB\n")

    # ── Auth ──────────────────────────────────────────────────────────────────
    private, oauth = _load_tokens()
    token          = _get_access_token(private, oauth)

    # ── DB setup ──────────────────────────────────────────────────────────────
    with SessionLocal() as session:
        player_map    = _build_player_name_map(session)
        all_yahoo_ids = _get_yahoo_team_ids(session)

    print(f"[db] {len(player_map)} players loaded")
    print(f"[db] {len(all_yahoo_ids)} Yahoo team IDs: {all_yahoo_ids}")

    yahoo_team_ids = (
        [SINGLE_TEAM] if SINGLE_TEAM is not None else all_yahoo_ids
    )
    if SINGLE_TEAM is not None and SINGLE_TEAM not in all_yahoo_ids:
        print(f"[WARN] team {SINGLE_TEAM} not found in DB — aborting")
        sys.exit(1)

    total_calls = len(yahoo_team_ids) * len(WEEKS)
    print(f"[plan] {len(yahoo_team_ids)} team(s) × {len(WEEKS)} week(s) = {total_calls} API calls")

    stats = RunStats()

    # ── Main loop ─────────────────────────────────────────────────────────────
    with SessionLocal() as session:
        call_n = 0
        for yahoo_tid in yahoo_team_ids:
            team_key = f"{GAME_KEY}.l.{LEAGUE_ID}.t.{yahoo_tid}"

            for week in WEEKS:
                call_n += 1
                path   = f"team/{team_key}/roster;week={week}/players/stats"

                try:
                    raw = _yahoo_get(path, token)
                except RuntimeError as e:
                    msg = f"Team {yahoo_tid} Week {week:>2}: FAILED — {e}"
                    print(f"  {msg}")
                    stats.failed_calls.append(msg)
                    time.sleep(API_DELAY)
                    continue

                players         = _extract_players(raw)
                n_matched        = 0
                n_unmatched      = 0
                n_no_pts         = 0
                n_inserted       = 0
                n_updated        = 0

                for p in players:
                    name     = _player_name(p)
                    proj_pts = _projected_pts(p)

                    if proj_pts is None:
                        n_no_pts += 1
                        continue

                    player_id = player_map.get(name.lower())
                    if player_id is None:
                        n_unmatched += 1
                        stats.total_unmatched += 1
                        label = f"{name} (week {week}, team {yahoo_tid})"
                        if label not in stats.unmatched:
                            stats.unmatched.append(label)
                        continue

                    action = _upsert_projection(session, player_id, week, proj_pts, dry_run)
                    n_matched += 1
                    if "insert" in action:
                        n_inserted += 1
                        stats.total_inserted += 1
                    else:
                        n_updated += 1
                        stats.total_updated += 1

                stats.total_no_pts += n_no_pts

                print(
                    f"  Team {yahoo_tid:>2}  Week {week:>2}  "
                    f"{len(players):>2} players  "
                    f"matched={n_matched}  unmatched={n_unmatched}  "
                    f"no_pts={n_no_pts}  "
                    f"inserted={n_inserted}  updated={n_updated}"
                    + ("  [DRY]" if dry_run else "")
                )

                # Commit after each team×week to keep transaction small
                if not dry_run:
                    session.commit()

                # Refresh token if needed (204 calls can span several hours)
                if call_n % 50 == 0:
                    private2, oauth2 = _load_tokens()
                    token = _get_access_token(private2, oauth2)

                time.sleep(API_DELAY)

    # ── Summary ───────────────────────────────────────────────────────────────
    mode_label = "DRY-RUN" if dry_run else "LIVE"
    print(f"\n{'='*60}")
    print(f"  SUMMARY ({mode_label})")
    print(f"{'='*60}")
    print(f"  Teams processed  : {len(yahoo_team_ids)}")
    print(f"  Weeks processed  : {len(WEEKS)} ({WEEKS[0]}–{WEEKS[-1]})")
    print(f"  API calls made   : {call_n}")
    print(f"  Failed API calls : {len(stats.failed_calls)}")
    print(f"  Rows inserted    : {stats.total_inserted}")
    print(f"  Rows updated     : {stats.total_updated}")
    print(f"  Unmatched players: {stats.total_unmatched}")
    print(f"  No-pts players   : {stats.total_no_pts}")

    if stats.failed_calls:
        print(f"\n  FAILED CALLS:")
        for msg in stats.failed_calls:
            print(f"    {msg}")

    if stats.unmatched:
        print(f"\n  UNMATCHED PLAYERS (first 30):")
        for label in stats.unmatched[:30]:
            print(f"    {label}")
        if len(stats.unmatched) > 30:
            print(f"    ... and {len(stats.unmatched) - 30} more")

    if dry_run:
        print(f"\n  !! DRY-RUN complete — no rows written. Re-run with --confirm to write.")
    else:
        print(f"\n  WRITE COMPLETE — {stats.total_inserted + stats.total_updated} rows upserted.")

    print()


if __name__ == "__main__":
    main()
