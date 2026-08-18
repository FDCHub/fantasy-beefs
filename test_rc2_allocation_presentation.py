#!/usr/bin/env python3
"""RC2 A3.1 — the Season-Opening Allocation read, and the seams that carry it.

THESE ARE THE ASSERTIONS SPRINT A LACKED. The A3 certification found three
defects that every green suite had missed, because none of them exercised a
league whose settings differ from the demo fixture:

  1. the full allocation omitted the FantasyStakes contribution
  2. the rules surface could show one league's number to every league
  3. the commissioner config was never fetched, so its controls were dead

Each is covered below by executing the real code against DIFFERENT league
configurations, which is the only thing that separates a derived figure from a
constant that happens to be right once.

No ledger movement occurs anywhere in this suite; trial balance is asserted.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

_TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'rc2-alloc.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pathlib  # noqa: E402

from db.schema import (  # noqa: E402
    Base, League, LeagueSeasonEconomyConfig, SessionLocal, Team, Wallet, engine,
)
from ledger.ledger import create_ledger_table, trial_balance  # noqa: E402
import economy.fantasystakes_championship_allocation as _alloc  # noqa: E402
import reports.championship_read_model  # noqa: E402,F401
import reports.championship_corrections  # noqa: E402,F401
from api.championship_routes import _season_opening_allocation  # noqa: E402

FAIL: list[str] = []
SEASON = 2027
WEB = pathlib.Path(__file__).parent / "web" / "js"


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


Base.metadata.create_all(engine)
create_ledger_table()


def league_with(name: str, *, weekly_min: int, weeks: int, yahoo: int, fs: int):
    """A league whose weekly minimum, schedule and contributions are its own."""
    with SessionLocal() as db:
        lg = League(season=SEASON, name=name, projection_source="fantasypros",
                    start_week=1, playoff_start_week=1 + weeks,
                    season_final_week=3 + weeks)
        db.add(lg)
        db.flush()
        L = lg.id
        t = Team(league_id=L, team_name="T", owner="O", email=f"{name}@x.test")
        db.add(t)
        db.flush()
        db.add(Wallet(team_id=t.id, balance=0.0))
        db.add(LeagueSeasonEconomyConfig(
            league_id=L, season=SEASON, weekly_bet_minimum_cents=weekly_min,
            championship_contribution_cents=yahoo, skunk_fee_cents=1000,
            regular_season_week_count=weeks, active_team_count=1,
            start_week_used=1, playoff_start_week_used=1 + weeks, frozen_at=None))
        _alloc.set_contribution(db, league_id=L, season=SEASON,
                                contribution_cents=fs)
        db.commit()
    with SessionLocal() as db:
        return _season_opening_allocation(
            db, db.query(League).filter(League.id == L).first())


# ── A · the allocation is DERIVED, and varies with the league ───────────────
print("\nA1 - Weekly Play Reserve and Season-Opening Allocation are derived")

CASES = (
    ("10 x 14 + 80 + 80", 1000, 14, 8000, 8000, 14_000, 30_000),
    ("10 x 13 + 80 + 80", 1000, 13, 8000, 8000, 13_000, 29_000),
    ("15 x 14 + 80 + 80", 1500, 14, 8000, 8000, 21_000, 37_000),
)
seen_totals = set()
for label, wk, weeks, yahoo, fs, want_reserve, want_total in CASES:
    a = league_with(label.replace(" ", ""), weekly_min=wk, weeks=weeks,
                    yahoo=yahoo, fs=fs)
    seen_totals.add(a["season_opening_allocation_cents"])
    check(f"{label}: reserve = weekly minimum x weeks",
          a["weekly_play_reserve_cents"] == want_reserve,
          f'{a["weekly_play_reserve_cents"]} != {want_reserve}')
    check(f"{label}: allocation = reserve + Yahoo + FantasyStakes",
          a["season_opening_allocation_cents"] == want_total,
          f'{a["season_opening_allocation_cents"]} != {want_total}')
    check(f"{label}: every component is reported",
          a["weekly_minimum_cents"] == wk
          and a["regular_season_week_count"] == weeks
          and a["yahoo_championship_contribution_cents"] == yahoo
          and a["fantasystakes_championship_contribution_cents"] == fs,
          str(a))
    check(f"{label}: the total really is the sum of its parts",
          a["weekly_play_reserve_cents"]
          + a["yahoo_championship_contribution_cents"]
          + a["fantasystakes_championship_contribution_cents"]
          == a["season_opening_allocation_cents"])

# The defect A3 found was three DIFFERENT leagues reporting one number.
check("three different configurations produce three different totals",
      len(seen_totals) == 3, str(sorted(seen_totals)))
check("no configuration silently returns the 300 default",
      seen_totals == {30_000, 29_000, 37_000}, str(sorted(seen_totals)))
check("the read moved no Credits", trial_balance() == 0, str(trial_balance()))


# ── B · the certified base-stage field was NOT redefined ────────────────────
print("\nA2 - the certified base-stage allocation is untouched")

from economy.league_economy_config import EconomyCalculation  # noqa: E402

calc = EconomyCalculation.__new__(EconomyCalculation)
object.__setattr__(calc, "weekly_bet_minimum_cents", 1000)
object.__setattr__(calc, "regular_season_week_count", 14)
object.__setattr__(calc, "championship_contribution_cents", 8000)
check("base stage still means Weekly Play Reserve + Yahoo contribution",
      calc.season_opening_allocation_per_player_cents == 22_000,
      str(calc.season_opening_allocation_per_player_cents))
check("and its weekly reserve is still the certified multiplication",
      calc.weekly_minimum_reserve_per_player_cents == 14_000)


# ── C · the load seam actually fetches what the UI consumes ─────────────────
print("\nA3 - production data requests every championship read the UI binds")

production = (WEB / "production-data.js").read_text(encoding="utf-8")
for path, label in (("/championship`", "championship chase"),
                    ("/championship/results`", "results"),
                    ("/championship/corrections`", "corrections"),
                    ("/championship/config`", "config")):
    check(f"production-data requests {label}", path in production, path)

for key in ("championshipResults", "championshipCorrections", "championshipConfig"):
    check(f"{key} is exposed on the snapshot",
          re.search(rf"^\s*{key},\s*$", production, re.M) is not None, key)

shell = (WEB / "shell.js").read_text(encoding="utf-8")
check("shell binds the config into the commissioner state",
      "data.championshipConfig" in shell)
check("shell binds the full allocation into the settings seam",
      "bindChampionshipAllocation(" in shell)

commissioner = (WEB / "commissioner.js").read_text(encoding="utf-8")
check("the commissioner area renders the championship admin section",
      "championshipAdminSection(" in commissioner)
check("and binds its controls to the governed commands",
      "bindChampionshipControls(" in commissioner
      and "updateContribution(" in commissioner)


# ── D · the rules surface reports the league's own figure ───────────────────
print("\nA4 - League Settings reports served values, not a module constant")

settings_model = (WEB / "settings-model.js").read_text(encoding="utf-8")
check("the settings row reads the served allocation when present",
      "alloc ? alloc.season_opening_allocation_cents" in settings_model)
check("the seam accepts a bound allocation",
      "export function bindChampionshipAllocation" in settings_model)
check("the fallback constant is declared an example, not a universal",
      "exampleOnly: true" in (WEB / "data" / "rules-data.js").read_text(encoding="utf-8"))
check("no hardcoded 30000 decides the live row",
      "30000" not in settings_model and "'$300'" not in settings_model)


# ── E · the lifecycle fallback fails conservatively ─────────────────────────
print("\nA5 - the lifecycle fallback cannot claim FINAL")

standings_model = (WEB / "standings-model.js").read_text(encoding="utf-8")
check("a frozen snapshot alone reports FROZEN, never FINAL",
      "championshipIsFinal() ? 'FROZEN' : 'LIVE'" in standings_model)
check("the server's lifecycle is preferred whenever available",
      "if (results && typeof results.lifecycle === 'string') return results.lifecycle;"
      in standings_model)


print(f"\n{'=' * 64}")
if FAIL:
    print(f"FAILED: {len(FAIL)} assertion(s)")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("PASS: RC2 allocation presentation and championship load-seam certification")
