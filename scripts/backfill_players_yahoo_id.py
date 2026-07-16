"""
scripts/backfill_players_yahoo_id.py

One-time offline backfill (FR-7.30 step 3): populate players.yahoo_id from the
Yahoo roster fetch, keyed by name.lower(). The players table's only external
join key today is name, so this first fill is necessarily name-based; once a
row has a yahoo_id, future resolution can key on the stable id instead.

Shape mirrors scripts/resolve_player_nfl_teams.py (offline, one-time, name-based
crosswalk against players) — but auth reuses the existing _build_yahoo_query
path and team bridging reuses TeamResolver (never +10 arithmetic).

SAFE / idempotent:
  - Only touches rows where yahoo_id IS NULL. A second run after a --commit
    updates zero rows.
  - DRY RUN IS THE DEFAULT. Prints the full match report and issues NO UPDATE
    unless --commit is passed explicitly.
  - All UPDATEs run inside ONE transaction; any failure rolls back everything.
  - Guard: refuses to run unless DATABASE_URL is set and points at Postgres —
    same check as db/migrations/migrate_players_yahoo_id.py. Run it the same
    way, with DATABASE_URL overridden to the Railway public proxy:
      railway run --service Postgres bash -c \\
        'DATABASE_URL="$DATABASE_PUBLIC_URL" python scripts/backfill_players_yahoo_id.py'
    Add --commit to that command to actually write.

Expected on first run: 179 matched, 1 unmatched (id=147 Joshua Palmer, WR).
Anything else means something is off — the dataset is known.

USAGE:
  python scripts/backfill_players_yahoo_id.py             # dry run (default)
  python scripts/backfill_players_yahoo_id.py --dry-run   # explicit dry run
  python scripts/backfill_players_yahoo_id.py --commit    # write yahoo_id rows
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

COMMIT  = "--commit" in sys.argv
DRY_RUN = not COMMIT           # dry run is the default; --commit is required to write

WEEK = 1   # 2025 week 1; season is game_id=461, baked into _build_yahoo_query

print("\nbackfill_players_yahoo_id.py  --  populate players.yahoo_id from Yahoo rosters (FR-7.30)")
print(f"  mode : {'LIVE WRITE (--commit)' if COMMIT else 'DRY RUN (default — no writes)'}\n")

from sqlalchemy import text
from db.schema import engine, SessionLocal, League, Team

# ── Guard: same DATABASE_URL / Postgres check as the migration ────────────────
db_url = str(engine.url)
if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
    print("!! ERROR: Postgres target not detected.")
    print("   DATABASE_URL is missing or does not point at a Postgres instance.")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


def _s(v) -> str:
    return v.decode() if isinstance(v, bytes) else str(v)


def _fetch_yahoo_rosters() -> tuple[dict[str, str], list[dict]]:
    """Fetch all team rosters (week 1) once.

    Returns:
      name_map -- {full_name.lower(): str(player_id)}
      records  -- list of {player_id, full_name, display_position,
                  editorial_team_abbr} for every fetched roster player. This is
                  the Yahoo side, used for the reverse/orphan report.

    Team DB->Yahoo bridging via TeamResolver; the Yahoo query is built ONCE.
    """
    from notifications.tuesday_sync import _build_yahoo_query
    from db.team_resolver import build_team_resolver

    yahoo_league_id = os.getenv("YAHOO_LEAGUE_ID", "488800")
    query = _build_yahoo_query(yahoo_league_id)   # built once; do not rebuild

    name_map: dict[str, str] = {}
    records: list[dict] = []
    with SessionLocal() as db:
        league_ids = [lid for (lid,) in db.query(League.id).all()]
        if len(league_ids) != 1:
            print(f"!! ERROR: expected exactly one league, found {league_ids}.")
            sys.exit(1)
        league_id = league_ids[0]

        resolver = build_team_resolver(db, league_id)
        teams = db.query(Team).filter(Team.league_id == league_id).all()

        for team in teams:
            yahoo_id = resolver.db_to_yahoo(team.id)
            roster = query.get_team_roster_by_week(yahoo_id, chosen_week=WEEK)
            for p in roster.players:
                full_name = _s(p.full_name)
                name_map[full_name.lower()] = str(p.player_id)
                records.append({
                    "player_id":           str(p.player_id),
                    "full_name":           full_name,
                    "display_position":    p.display_position,
                    "editorial_team_abbr": p.editorial_team_abbr,
                })

    return name_map, records


# ── Fetch Yahoo rosters (once) ────────────────────────────────────────────────
print("=" * 60)
print("STEP 1  -- Fetch Yahoo rosters (all 12 teams, week 1)")
print("=" * 60)

yahoo_name_map, yahoo_records = _fetch_yahoo_rosters()
print(f"\n  fetched Yahoo roster players:                {len(yahoo_records)}")
print(f"  distinct Yahoo (name -> player_id) entries:  {len(yahoo_name_map)}")


# ── Match every NULL-yahoo_id players row by name.lower() ─────────────────────
print()
print("=" * 60)
print("STEP 2  -- Match players (yahoo_id IS NULL) by name.lower()")
print("=" * 60)

with SessionLocal() as db:
    null_rows = db.execute(text(
        "SELECT id, name, position, nfl_team FROM players "
        "WHERE yahoo_id IS NULL ORDER BY id"
    )).fetchall()

    # All players names (lowercased) — used to find Yahoo orphans: fetched
    # roster players whose name matches NO players row at all.
    all_names_lower = {
        n.lower() for (n,) in db.execute(text("SELECT name FROM players")).fetchall()
    }
    _seen_orphan_ids: set[str] = set()
    orphans: list[dict] = []
    for rec in yahoo_records:
        if rec["full_name"].lower() in all_names_lower:
            continue
        if rec["player_id"] in _seen_orphan_ids:
            continue
        _seen_orphan_ids.add(rec["player_id"])
        orphans.append(rec)

    to_update: list[tuple[int, str]] = []             # (player_id, yahoo_id)
    unmatched: list[tuple[int, str, str, str]] = []   # (id, name, position, nfl_team)

    for pid, name, position, nfl_team in null_rows:
        yid = yahoo_name_map.get(name.lower())
        if yid is not None:
            to_update.append((pid, yid))
        else:
            unmatched.append((pid, name, position, nfl_team))

    print(f"\n  players with yahoo_id IS NULL: {len(null_rows)}")
    print(f"  matched to a Yahoo player_id:  {len(to_update)}")
    print(f"  unmatched:                     {len(unmatched)}")

    # ── Write (only under --commit), single transaction ──────────────────────
    print()
    print("=" * 60)
    print(f"STEP 3  -- {'Apply UPDATEs (--commit)' if COMMIT else 'DRY RUN — no writes'}")
    print("=" * 60)

    if not to_update:
        print("\n  nothing to update (0 matched NULL rows).")
    elif DRY_RUN:
        print(f"\n  DRY RUN: would UPDATE {len(to_update)} row(s). No writes issued.")
    else:
        try:
            for pid, yid in to_update:
                db.execute(
                    text("UPDATE players SET yahoo_id = :yid WHERE id = :id"),
                    {"yid": yid, "id": pid},
                )
            db.commit()
            print(f"\n  committed {len(to_update)} yahoo_id UPDATE(s).")
        except Exception as e:
            db.rollback()
            print(f"\n!! ERROR: backfill failed and the transaction was rolled back: {e}")
            print("   No rows were changed.")
            sys.exit(1)


# ── Report: the mismatch, both sides, + ready-to-run manual UPDATEs ───────────
# The two lists are printed adjacent so they read as a pair:
#   - unmatched DB rows : players (yahoo_id NULL) with no Yahoo name match
#   - Yahoo orphans     : fetched roster players matching no players row
# In the known dataset these pair 1:1 (DB "Joshua Palmer" <-> Yahoo "Josh Palmer").
print()
print("=" * 60)
print("STEP 4  -- Mismatch report (unmatched DB rows <-> Yahoo orphans)")
print("=" * 60)

print(f"\n  -- Unmatched DB rows (players.yahoo_id IS NULL, no Yahoo name) : {len(unmatched)}")
if unmatched:
    for pid, name, position, nfl_team in unmatched:
        print(f"       id={pid:<4}  {position:<4} {str(nfl_team):<5} {name}")
else:
    print("       (none)")

print(f"\n  -- Yahoo orphans (fetched roster players matching no DB row)   : {len(orphans)}")
if orphans:
    for o in orphans:
        print(f"       player_id={o['player_id']:<8} {str(o['display_position']):<4} "
              f"{str(o['editorial_team_abbr']):<4}  {o['full_name']!r}")
else:
    print("       (none)")

# Auto-fill ONLY the unambiguous case: exactly one unmatched DB row and exactly
# one Yahoo orphan, of the same position. Any other count/position pairing is
# ambiguous — fall back to the placeholder and let a human map it (a wrong
# auto-fill would write a bad id silently).
auto_id = None
if len(unmatched) == 1 and len(orphans) == 1 and \
        orphans[0]["display_position"] == unmatched[0][2]:
    auto_id = orphans[0]["player_id"]

if not unmatched:
    print("\n  All NULL rows matched — nothing to resolve by hand.")
elif auto_id is not None:
    pid, name, position, nfl_team = unmatched[0]
    o = orphans[0]
    print("\n  Ready-to-run UPDATE (auto-paired — 1 DB miss <-> 1 Yahoo orphan, "
          "same position):\n")
    print(f"  # DB '{name}' ({position}) <-> Yahoo '{o['full_name']}' "
          f"id={o['player_id']} ({o['display_position']}, {o['editorial_team_abbr']})")
    print(f"  UPDATE players SET yahoo_id = '{auto_id}' WHERE id = {pid};"
          f"  -- {name} ({position}, {nfl_team})")
else:
    reason = ("counts do not pair 1:1" if len(unmatched) != len(orphans)
              else "positions differ" if len(unmatched) == 1 and len(orphans) == 1
              else "ambiguous pairing")
    print(f"\n  Not auto-filling ({reason}) — resolve by hand using both lists above.")
    print("  Ready-to-run manual UPDATEs (fill in the real Yahoo player_id):\n")
    for pid, name, position, nfl_team in unmatched:
        print(f"  UPDATE players SET yahoo_id = '<YAHOO_ID>' WHERE id = {pid};"
              f"  -- {name} ({position}, {nfl_team})")

print("\n  DONE.\n")
