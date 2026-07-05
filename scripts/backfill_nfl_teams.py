"""
scripts/backfill_nfl_teams.py

Backfills players.nfl_team for all 180 players.

Run order:
  1. python -X utf8 scripts/backfill_nfl_teams.py --lookup
       Prints player ids for Pittman/Jackson and previews all 13 overrides.
       STOP here and confirm with the user before continuing.

  2. python -X utf8 scripts/backfill_nfl_teams.py --run
       Issues ALTER TABLE (idempotent), backfills all 180, and verifies.

Usage:
  DATABASE_URL=<pg_url> python -X utf8 scripts/backfill_nfl_teams.py --lookup
  DATABASE_URL=<pg_url> python -X utf8 scripts/backfill_nfl_teams.py --run
"""

import os
import sys

# Allow importing from project root and scripts/
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from sqlalchemy import create_engine, text

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:EpxiNiHsfDEMRRCJbhXqewappXXfVeOW@reseau.proxy.rlwy.net:54032/railway",
)

# ---------------------------------------------------------------------------
# Manual overrides — keyed by internal player id (integer).
# Applied LAST so they always win over auto-resolution.
#
# FA bucket (11): teams confirmed by user; DynastyProcess crosswalk shows FA.
# Collision fixes (2): auto-match picked wrong player due to name collision.
#   Pittman:  suffix-strip "Michael Pittman Jr." -> "Michael Pittman" collided
#             with father's entry (PIT). Correct team is IND.
#   Jackson:  two "Lamar Jackson" rows in crosswalk; auto-picked CAR. BAL is ours.
# ---------------------------------------------------------------------------
OVERRIDES: dict[int, str] = {
    # -- FA bucket (11 players, teams provided by user) -----------------------
    279: "MIN",   # Adam Thielen      (WR)
    159: "LAC",   # Austin Ekeler     (RB)
    161: "SF",    # Deebo Samuel      (WR)
    146: "CIN",   # Joe Mixon         (RB)
    266: "MIA",   # Jonnu Smith       (TE)
    177: "LAC",   # Keenan Allen      (WR)
    313: "PIT",   # Najee Harris      (RB)
    137: "CLE",   # Nick Chubb        (RB)
    224: "HOU",   # Stefon Diggs      (WR)
    304: "MIA",   # Tyreek Hill       (WR)
    164: "ARI",   # Zach Ertz         (TE)
    # -- Collision fixes: confirmed by user 2026-07-02 -------------------------
    169: "IND",   # Michael Pittman Jr. (WR) — suffix collision auto->PIT (father)
    255: "BAL",   # Lamar Jackson       (QB) — name collision  auto->CAR (wrong player)
}

# DynastyProcess dialect -> ESPN/schedule dialect. These 9 differ; all
# other abbreviations are identical across both sources.
TEAM_NORMALIZE: dict[str, str] = {
    "GBP": "GB",
    "JAC": "JAX",
    "KCC": "KC",
    "LVR": "LV",
    "NEP": "NE",
    "NOS": "NO",
    "SFO": "SF",
    "TBB": "TB",
    "WAS": "WSH",
}


def _lookup_ids(conn) -> None:
    """Print player ids for Pittman/Jackson and preview all 13 overrides."""
    print("=" * 64)
    print("  OVERRIDE LOOKUP — confirm before running --run")
    print("=" * 64)

    # Fetch names for all OVERRIDES already defined
    ids_list = list(OVERRIDES.keys())
    rows = conn.execute(
        text("SELECT id, name, position FROM players WHERE id = ANY(:ids) ORDER BY id"),
        {"ids": ids_list},
    ).fetchall()

    # Also fetch auto-resolution for each to show old -> new
    from resolve_player_nfl_teams import build_nfl_team_mapping
    auto = build_nfl_team_mapping(conn)

    print("\n-- 11 FA overrides already in OVERRIDES dict ----------------")
    print(f"  {'id':>5}  {'pos':6}  {'name':<28}  {'auto':>6}  ->  {'override'}")
    print(f"  {'-'*5}  {'-'*6}  {'-'*28}  {'-'*6}      {'-'*8}")
    for row in rows:
        pid, name, pos = row
        auto_team = auto.get(pid, "None") or "None"
        new_team  = OVERRIDES[pid]
        flag = "  *** SAME ***" if auto_team == new_team else ""
        print(f"  {pid:>5}  {pos:6}  {name:<28}  {auto_team:>6}  ->  {new_team}{flag}")

    # Now look up Pittman and Jackson
    print("\n-- NEED IDs for 2 collision fixes ---------------------------")
    targets = [
        ("Michael Pittman Jr.", "WR", "IND", "suffix-strip collision: auto->PIT (father)"),
        ("Lamar Jackson",       "QB", "BAL", "name collision: two rows in crosswalk, auto->CAR"),
    ]
    for name, pos, correct_team, note in targets:
        found = conn.execute(
            text("SELECT id, name, position FROM players WHERE name = :n"),
            {"n": name},
        ).fetchall()
        if found:
            for pid, pname, ppos in found:
                auto_team = auto.get(pid, "None") or "None"
                print(f"  id={pid:4d}  {ppos:6}  {pname:<28}  auto={auto_team:>6}  ->  {correct_team}")
                print(f"          note: {note}")
        else:
            print(f"  NOT FOUND in players table: {name!r}")

    print("\n-- ACTION REQUIRED ------------------------------------------")
    print("  Confirm all 13 entries above look correct, then add the two")
    print("  collision-fix ids to OVERRIDES in this script and run:")
    print("    python -X utf8 scripts/backfill_nfl_teams.py --run")
    print("=" * 64)


def _run_backfill(conn) -> None:
    """Issue ALTER TABLE, backfill all 180 players, verify."""
    from resolve_player_nfl_teams import build_nfl_team_mapping

    # (a) Idempotent schema change
    print("Step (a): ALTER TABLE players ADD COLUMN IF NOT EXISTS nfl_team ...")
    conn.execute(text(
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS nfl_team VARCHAR(4)"
    ))
    print("  Done.")

    # (b+c) Build mapping, apply overrides last
    print("\nStep (b+c): building auto-mapping + applying overrides ...")
    auto = build_nfl_team_mapping(conn)

    final: dict[int, str | None] = dict(auto)       # copy auto-resolution
    for pid, team in OVERRIDES.items():
        final[pid] = team                            # overrides always win
    # Normalize dialect last — applies to both auto-matched and overridden values
    final = {
        pid: (TEAM_NORMALIZE.get(team, team) if team else None)
        for pid, team in final.items()
    }

    # Sanity check: warn if any player is still None
    nulls = [pid for pid, team in final.items() if team is None]
    if nulls:
        print(f"  WARNING: {len(nulls)} players still map to None after overrides: {nulls}")
    else:
        print(f"  All {len(final)} players have a team assigned.")

    # (d) Backfill
    print("\nStep (d): updating players.nfl_team ...")
    rows_updated = 0
    for pid, team in final.items():
        conn.execute(
            text("UPDATE players SET nfl_team = :team WHERE id = :id"),
            {"team": team, "id": pid},
        )
        rows_updated += 1
    print(f"  Updated {rows_updated} rows.")

    # (e) Verify
    print("\nStep (e): verification ...")
    total     = conn.execute(text("SELECT COUNT(*) FROM players")).scalar()
    with_team = conn.execute(
        text("SELECT COUNT(*) FROM players WHERE nfl_team IS NOT NULL")
    ).scalar()
    no_team   = conn.execute(
        text("SELECT id, name, position FROM players WHERE nfl_team IS NULL")
    ).fetchall()

    print(f"  Total players:       {total}")
    print(f"  With nfl_team:       {with_team}")
    print(f"  Still NULL:          {len(no_team)}")
    if no_team:
        print("  NULL players:")
        for r in no_team:
            print(f"    id={r[0]:4d}  {r[2]:6}  {r[1]}")

    # Show 13 override rows as they now sit in prod
    override_ids = list(OVERRIDES.keys())
    print(f"\n  -- 13 override rows in prod --------------------------------")
    override_rows = conn.execute(
        text("SELECT id, name, position, nfl_team FROM players "
             "WHERE id = ANY(:ids) ORDER BY position, name"),
        {"ids": override_ids},
    ).fetchall()
    for r in override_rows:
        print(f"    id={r[0]:4d}  {r[2]:6}  {r[1]:<28}  nfl_team={r[3]!r}")

    # 5 spot-check auto-matched rows
    print(f"\n  -- 5 auto-matched spot-check rows --------------------------")
    spot = conn.execute(text("""
        SELECT id, name, position, nfl_team FROM players
        WHERE id NOT IN :oids AND nfl_team IS NOT NULL
        ORDER BY id LIMIT 5
    """), {"oids": tuple(override_ids)}).fetchall()
    for r in spot:
        print(f"    id={r[0]:4d}  {r[2]:6}  {r[1]:<28}  nfl_team={r[3]!r}")

    print("\n  Backfill complete.")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--lookup"
    if mode not in ("--lookup", "--run"):
        print(f"Usage: {sys.argv[0]} [--lookup | --run]")
        sys.exit(1)

    engine = create_engine(DB_URL, connect_args={"connect_timeout": 15})

    if mode == "--lookup":
        with engine.connect() as conn:
            _lookup_ids(conn)
    else:
        with engine.begin() as conn:  # transaction — commits on exit, rolls back on exception
            _run_backfill(conn)


if __name__ == "__main__":
    main()
