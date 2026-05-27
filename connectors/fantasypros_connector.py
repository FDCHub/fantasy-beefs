"""
FantasyPros connector — fetches 2024 weekly consensus projections from
public FantasyPros pages (no API key required) and upserts them into the
projections table with source='fantasypros'.

Actual points are preserved from the existing synthetic seed; only
projected_points is overwritten with real FantasyPros consensus figures.

Usage:
    python -X utf8 connectors/fantasypros_connector.py           # week 1 only (demo)
    python -X utf8 connectors/fantasypros_connector.py --all     # all 17 weeks
"""

from __future__ import annotations

import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Player, Projection, SessionLocal

# ── Constants ─────────────────────────────────────────────────────────────────

SEASON = 2024
SOURCE = "fantasypros"
BASE   = "https://www.fantasypros.com/nfl/projections/{slug}.php"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.fantasypros.com/",
}

# Our position label → FantasyPros URL slug
POS_SLUGS: dict[str, str] = {
    "QB":   "qb",
    "RB":   "rb",
    "WR":   "wr",
    "TE":   "te",
    "FLEX": "wr",   # FLEX players appear under their real position; WR covers most
    "K":    "k",
    "DEF":  "dst",
}

# FantasyPros DST full-name → our DB name (already identical for most)
# Included so future teams/renames can be patched here without touching logic.
DST_ALIASES: dict[str, str] = {
    "Washington Commanders": "Washington Commanders",
    "Las Vegas Raiders":     "Las Vegas Raiders",
}


# ── Name normalisation ────────────────────────────────────────────────────────

def _norm(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", name)
    name = name.replace("’", "'").replace("‘", "'")   # smart quotes
    name = re.sub(r"[^a-z0-9\s'\-\.]", "", name)
    return re.sub(r"\s+", " ", name).strip()


# ── HTTP fetch ────────────────────────────────────────────────────────────────

def _fetch(slug: str, week: int) -> str | None:
    url = BASE.format(slug=slug)
    try:
        r = requests.get(
            url,
            params={"week": week, "scoring": "PPR", "year": SEASON},
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        return r.text
    except requests.RequestException as exc:
        print(f"    [warn] {url} wk{week}: {exc}")
        return None


# ── HTML parsing ──────────────────────────────────────────────────────────────

def _parse(html: str) -> list[tuple[str, float]]:
    """Return [(canonical_player_name, fpts), ...] for one page."""
    soup  = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="data")
    if not table:
        return []

    # FPTS is always the last column; verify via headers
    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    fpts_col = len(headers) - 1
    if "FPTS" in headers:
        fpts_col = headers.index("FPTS")

    results: list[tuple[str, float]] = []
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) <= fpts_col:
            continue

        # Player name — prefer the fp-player-name attribute on the <a> tag
        name_cell = cells[0]
        link      = name_cell.find("a", class_="player-name")
        if link:
            name = link.get("fp-player-name") or link.get_text(strip=True)
        else:
            # DST rows have plain text: "Minnesota Vikings"
            name = name_cell.get_text(strip=True)

        fpts_raw = cells[fpts_col].get_text(strip=True).replace(",", "")
        try:
            fpts = float(fpts_raw)
        except ValueError:
            continue

        name = DST_ALIASES.get(name, name)   # apply any alias overrides
        results.append((name, fpts))

    return results


# ── DB upsert ─────────────────────────────────────────────────────────────────

def _upsert(session: Session, player: Player, week: int, fpts: float) -> bool:
    """Update projected_points if row exists, otherwise insert. Returns True if changed."""
    proj = (
        session.query(Projection)
        .filter_by(player_id=player.id, week=week, season=SEASON, source=SOURCE)
        .first()
    )
    if proj:
        proj.projected_points = fpts
        return True

    # Pull actual_points from any existing row for this player-week
    existing = (
        session.query(Projection)
        .filter_by(player_id=player.id, week=week, season=SEASON)
        .first()
    )
    session.add(Projection(
        player_id        = player.id,
        week             = week,
        season           = SEASON,
        projected_points = fpts,
        actual_points    = existing.actual_points if existing else 0.0,
        source           = SOURCE,
    ))
    return True


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_and_populate(
    weeks: range = range(1, 2),
    session: Session | None = None,
) -> dict:
    """
    Fetch FantasyPros projections for the given weeks and upsert into DB.
    Returns a summary dict with matched/skipped/total counts.
    """
    close_after = session is None
    if session is None:
        session = SessionLocal()

    # Build name-lookup from DB: normalized_name → Player
    all_players: list[Player] = session.query(Player).all()
    norm_lookup: dict[str, Player] = {_norm(p.name): p for p in all_players}

    matched_total = skipped_total = 0
    seen_slugs: set[str] = set()          # avoid fetching same slug twice per week

    try:
        for week in weeks:
            print(f"  week {week:02d}:")
            seen_slugs.clear()

            for pos, slug in POS_SLUGS.items():
                if slug in seen_slugs:    # FLEX shares slug with WR — skip duplicate fetch
                    continue
                seen_slugs.add(slug)

                html = _fetch(slug, week)
                if not html:
                    continue

                rows = _parse(html)
                if not rows:
                    print(f"    {pos:4} ({slug}): no rows parsed")
                    continue

                matched_week = 0
                for raw_name, fpts in rows:
                    player = norm_lookup.get(_norm(raw_name))
                    if not player:
                        skipped_total += 1
                        continue
                    _upsert(session, player, week, fpts)
                    matched_week  += 1
                    matched_total += 1

                print(f"    {pos:4} ({slug:3}): {len(rows):3} fetched  {matched_week:3} matched")
                time.sleep(0.4)

        session.commit()

    except Exception:
        session.rollback()
        raise
    finally:
        if close_after:
            session.close()

    return {"matched": matched_total, "skipped": skipped_total}


# ── Demo ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    fetch_all = "--all" in sys.argv
    weeks     = range(1, 18) if fetch_all else range(1, 2)

    print(f"Fetching FantasyPros 2024 projections — {'all 17 weeks' if fetch_all else 'week 1 only'}\n")
    summary = fetch_and_populate(weeks=weeks)
    print(f"\nTotal matched={summary['matched']}  skipped={summary['skipped']}")

    # Print projected vs actual for week 1, source=fantasypros
    with SessionLocal() as s:
        rows = (
            s.query(Projection)
             .filter_by(week=1, season=SEASON, source=SOURCE)
             .join(Player)
             .order_by(Player.position, Player.name)
             .all()
        )

        if not rows:
            print("\nNo week 1 fantasypros projections found.")
            sys.exit(0)

        print(f"\nFantasyPros week 1 projections vs synthetic actuals  ({len(rows)} matched players)\n")
        print("┌────────────────────────────┬──────┬──────────┬──────────┬──────────┐")
        print("│ Player                     │ Pos  │ FP Proj  │ Actual   │  Delta   │")
        print("├────────────────────────────┼──────┼──────────┼──────────┼──────────┤")
        for pr in rows:
            delta = pr.projected_points - pr.actual_points
            print(
                f"│ {pr.player.name:<26} │ {pr.player.position:<4} │"
                f" {pr.projected_points:>8.2f} │ {pr.actual_points:>8.2f} │ {delta:>+8.2f} │"
            )
        print("└────────────────────────────┴──────┴──────────┴──────────┴──────────┘")
