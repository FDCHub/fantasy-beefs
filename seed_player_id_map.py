"""
seed_player_id_map.py  --  Create and populate the player_id_map crosswalk table.

Source: DynastyProcess db_playerids.csv (open, community-maintained, no auth required).
        https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv

CSV column -> player_id_map column mapping:
  fantasypros_id -> fantasypros_id  (PK; rows where this is "NA" are skipped)
  yahoo_id       -> yahoo_id        ("NA" stored as NULL)
  name           -> name
  position       -> position
  team           -> team            ("NA" stored as NULL; "FA" kept as-is = free agent)

Usage:
  python seed_player_id_map.py              # against local SQLite (dev)
  DATABASE_URL=<pg_url> python seed_player_id_map.py   # explicit URL
  (Railway: run via `railway run` or the public Postgres URL)
"""

import csv
import io
import os
import sys
import urllib.request
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

CSV_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:EpxiNiHsfDEMRRCJbhXqewappXXfVeOW@reseau.proxy.rlwy.net:54032/railway",
)

# ── Pull schema into scope ────────────────────────────────────────────────────
# Import after DB_URL is determined so we don't accidentally hit SQLite default
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.schema import Base, PlayerIdMap  # noqa: E402

# ── Step 1: create table if missing ──────────────────────────────────────────

engine = create_engine(DB_URL, connect_args={"connect_timeout": 15})
insp   = inspect(engine)

if "player_id_map" not in insp.get_table_names():
    print("Creating player_id_map table...")
    PlayerIdMap.__table__.create(engine)
    print("  Done.")
else:
    print("player_id_map already exists — upsert only.")

Session = sessionmaker(bind=engine)

# ── Step 2: download CSV ──────────────────────────────────────────────────────

print(f"\nDownloading {CSV_URL} ...")
with urllib.request.urlopen(CSV_URL, timeout=30) as resp:
    raw_bytes = resp.read()
raw_text = raw_bytes.decode("utf-8", errors="replace")
print(f"  Downloaded {len(raw_bytes):,} bytes.")

reader  = csv.DictReader(io.StringIO(raw_text))
all_rows = list(reader)
print(f"  Total CSV rows: {len(all_rows):,}")

# ── Step 3: filter and transform rows ─────────────────────────────────────────

now_utc = datetime.now(timezone.utc)

def _none_if_na(val: str) -> str | None:
    v = val.strip()
    return None if v in ("NA", "", "N/A") else v

upsert_rows: list[dict] = []
skipped_no_fpid = 0

for row in all_rows:
    fpid = _none_if_na(row.get("fantasypros_id", ""))
    if fpid is None:
        skipped_no_fpid += 1
        continue

    upsert_rows.append({
        "fantasypros_id": fpid,
        "yahoo_id":       _none_if_na(row.get("yahoo_id", "")),
        "name":           row.get("name", "").strip() or None,
        "position":       _none_if_na(row.get("position", "")),
        "team":           _none_if_na(row.get("team", "")),
        "last_updated":   now_utc,
    })

print(f"  Rows with fantasypros_id: {len(upsert_rows):,}")
print(f"  Rows skipped (no FP ID):  {skipped_no_fpid:,}")

# ── Step 4: upsert ────────────────────────────────────────────────────────────

print("\nUpserting rows into player_id_map...")

# Use raw SQL UPSERT for efficiency (avoids 11k+ ORM round-trips)
dialect = engine.dialect.name

BATCH = 500
loaded = 0

with engine.begin() as conn:
    for i in range(0, len(upsert_rows), BATCH):
        batch = upsert_rows[i : i + BATCH]

        if dialect == "postgresql":
            conn.execute(text("""
                INSERT INTO player_id_map
                    (fantasypros_id, yahoo_id, name, position, team, last_updated)
                VALUES
                    (:fantasypros_id, :yahoo_id, :name, :position, :team, :last_updated)
                ON CONFLICT (fantasypros_id)
                DO UPDATE SET
                    yahoo_id     = EXCLUDED.yahoo_id,
                    name         = EXCLUDED.name,
                    position     = EXCLUDED.position,
                    team         = EXCLUDED.team,
                    last_updated = EXCLUDED.last_updated
            """), batch)
        else:
            # SQLite: INSERT OR REPLACE
            conn.execute(text("""
                INSERT OR REPLACE INTO player_id_map
                    (fantasypros_id, yahoo_id, name, position, team, last_updated)
                VALUES
                    (:fantasypros_id, :yahoo_id, :name, :position, :team, :last_updated)
            """), batch)

        loaded += len(batch)
        print(f"  Upserted {loaded:,} / {len(upsert_rows):,} ...", end="\r")

print()  # newline after \r progress

# ── Step 5: report ────────────────────────────────────────────────────────────

with engine.connect() as conn:
    total = conn.execute(text("SELECT COUNT(*) FROM player_id_map")).scalar()
    with_team = conn.execute(text(
        "SELECT COUNT(*) FROM player_id_map WHERE team IS NOT NULL AND team NOT IN ('FA', '')"
    )).scalar()

print(f"\n=== player_id_map populated ===")
print(f"  Total rows:           {total:,}")
print(f"  With real NFL team:   {with_team:,}")
print(f"  Free agent / no team: {total - with_team:,}")

# ── Coverage check against our players table ──────────────────────────────────

try:
    with engine.connect() as conn:
        # Check if players table exists in this DB
        tables = inspect(engine).get_table_names()
        if "players" not in tables:
            print("\n(players table not found in this DB — skipping coverage check)")
        else:
            n_players = conn.execute(text("SELECT COUNT(*) FROM players")).scalar()

            matched = conn.execute(text("""
                SELECT COUNT(DISTINCT p.id)
                FROM players p
                JOIN player_id_map m
                  ON lower(trim(p.name)) = lower(trim(m.name))
                WHERE m.team IS NOT NULL AND m.team NOT IN ('FA', '')
            """)).scalar()

            print(f"\n=== Coverage against our players table ===")
            print(f"  Total players:   {n_players}")
            print(f"  Matched to team: {matched}")
            print(f"  Coverage:        {matched}/{n_players}  ({100*matched//n_players}%)")

            unmatched = conn.execute(text("""
                SELECT p.id, p.name, p.position
                FROM players p
                WHERE NOT EXISTS (
                    SELECT 1 FROM player_id_map m
                    WHERE lower(trim(p.name)) = lower(trim(m.name))
                      AND m.team IS NOT NULL AND m.team NOT IN ('FA', '')
                )
                ORDER BY p.position, p.name
                LIMIT 20
            """)).fetchall()

            print(f"\n  Unmatched players (up to 20):")
            for r in unmatched:
                print(f"    id={r[0]:4d}  {r[2]:6s}  {r[1]}")
except Exception as exc:
    print(f"\nCoverage check error: {exc}")
