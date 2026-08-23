#!/usr/bin/env python3
"""FINAL POR · WP-14 seam certification — the Grand Championship on the wire.

    G1  a FINAL POR season is served by §20's model, not the retired 3/2/1
    G2  the payload carries credits and a state, and NOT pooled points
    G3  PLACEHOLDER returns no rows -- not rows of zeros
    G4  a LEGACY season still gets the retired model, unchanged
    G5  each payload SAYS which model produced it
    G6  a refusal travels in the payload rather than failing the response

WHY THIS SUITE EXISTS AT ALL. WP-14 replaced the Grand Championship: §20 wins it
on the finalized championship CREDITS a GM holds across the pillars their league
actually funded, needs at least two funded pillars, and makes an exact tie a
co-championship with no tiebreak. The engine was certified on that. The ROUTE
was not -- it kept calling `reports.grand_champion`, so a Final POR league read
its Grand Championship as 3/2/1 recognition points for a competition that season
never ran.

WHY THE OLD KEY IS KEPT AND LEFT NULL rather than reused. The retired payload's
`yahoo_points` / `fantasystakes_points` / `combined_points` describe pooled
Fractions that no longer exist. Putting credit figures in those fields would let
a client keep reading the old rule and get plausible numbers out -- the worst
available outcome, because nothing would look wrong. G2 asserts the absence.

WHY G4 MATTERS AS MUCH AS G1. The retired model still governs every legacy
season, exactly as `reserve:{team}` still does in `current_settle.py`. This
change was a routing fix and not a removal, and a legacy season whose Grand
Champion quietly became something else would be a silent rewrite of a finished
competition.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import ledger.ledger as ledger_module
from db.schema import (
    Base, League, LeagueSeasonEconomyConfig, Matchup, Team, Wallet,
)
from economy.grand_championship import (
    GRAND_PLACEHOLDER, MINIMUM_FUNDED_PILLARS, REASON_WRONG_ERA,
    GrandChampionshipError, view as grand_view,
)
from ruleset import RULESET_FINAL_POR, stamp_ruleset

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
NAIVE = NOW.replace(tzinfo=None)
LEAGUE = 1
SEASON = 2026


def _build(*, final_por: bool):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=LEAGUE, name="L", season=SEASON, start_week=1,
                  playoff_start_week=15, topoff_cap_multiplier_bps=5000))
    for t in range(1, 5):
        db.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider_team_key=f"k{t}"))
        db.add(Wallet(team_id=t, balance=0.0))
    db.add(Matchup(id=1, league_id=LEAGUE, week=1, home_team_id=1,
                   away_team_id=2, home_score=100.0, away_score=98.0,
                   winner_team_id=1, finalized_at=NAIVE))
    db.add(LeagueSeasonEconomyConfig(
        league_id=LEAGUE, season=SEASON,
        weekly_bet_minimum_cents=1_000,
        championship_contribution_cents=8_000,
        skunk_fee_cents=500, ff_championship_pot_cents=5_000,
        regular_season_week_count=14, active_team_count=4,
        start_week_used=1, playoff_start_week_used=15, frozen_at=NAIVE))
    db.commit()
    if final_por:
        stamp_ruleset(db, league_id=LEAGUE, season=SEASON,
                      version=RULESET_FINAL_POR)
        db.commit()
    return db


# -- G1 . a FINAL POR season is served by §20's model --------------------------

print("\nWP14R-G1 " + chr(0x00b7) + " the era decides which model answers")

final_db = _build(final_por=True)
legacy_db = _build(final_por=False)

view = grand_view(final_db, league_id=LEAGUE, season=SEASON)
_assert("a Final POR season resolves §20's view",
        view.state in ("PLACEHOLDER", "LIVE", "FINAL"), view.state)
_assert("  . reporting the pillars the league actually funded",
        isinstance(view.funded_pillars, tuple),
        str(view.funded_pillars))
_assert("  . and saying whether §20's two-pillar minimum is met",
        view.meets_pillar_minimum is (len(view.funded_pillars)
                                      >= MINIMUM_FUNDED_PILLARS),
        f"{view.funded_pillars} -> {view.meets_pillar_minimum}")
try:
    grand_view(legacy_db, league_id=LEAGUE, season=SEASON)
    _assert("a LEGACY season is refused by §20's view", False, "it answered")
except GrandChampionshipError as exc:
    _assert("a LEGACY season is refused by §20's view",
            exc.reason == REASON_WRONG_ERA, exc.reason)
    _assert("  . and the refusal names the retired model as its owner",
            "grand_champion" in str(exc), str(exc)[:140])


# -- G2 . credits and a state, never pooled points -----------------------------

print("\nWP14R-G2 " + chr(0x00b7) + " the payload carries credits, not pooled points")

import inspect  # noqa: E402

import api.championship_routes as _routes  # noqa: E402

_src = inspect.getsource(_routes)
# COMMENTS STRIPPED. This file EXPLAINS the retired fields at length, and a
# plain text search would find the explanation and call it a usage -- which is
# how three earlier assertions on this branch first failed against correct code.
_code = "\n".join(line for line in _src.splitlines()
                  if not line.lstrip().startswith("#"))

_final_block = _code[_code.index('grand_final_por = {'):
                     _code.index('except GrandChampionshipError')]
for retired in ('yahoo_points', 'fantasystakes_points', 'combined_points',
                'combined_display'):
    _assert(f"the Final POR payload carries no `{retired}`",
            retired not in _final_block, retired)
for required in ('by_pillar', 'total_cents', 'funded_pillars',
                 'finalized_pillars', 'meets_pillar_minimum', 'state'):
    _assert(f"  . and does carry `{required}`", required in _final_block,
            required)

# THE RETIRED FIELDS STILL EXIST FOR THE LEGACY PATH, which is the half that
# proves this was a routing change and not a deletion.
_legacy_block = _code[_code.index('grand_champion = {'):]
_assert("the LEGACY payload still carries its pooled points",
        all(f in _legacy_block for f in
            ('yahoo_points', 'fantasystakes_points', 'combined_points')))

# NO TIEBREAK EXISTS UNDER §20, and it is reported false rather than omitted so
# a client cannot mistake absence for "we did not check".
_assert("the Final POR payload reports tiebreak_used as a literal False",
        '"tiebreak_used": False' in _final_block)


# -- G3 . PLACEHOLDER returns no rows ------------------------------------------

print("\nWP14R-G3 " + chr(0x00b7) + " PLACEHOLDER is empty, not rows of zeros")

_assert("the regular season is PLACEHOLDER",
        view.state == GRAND_PLACEHOLDER, view.state)
_assert("  . and carries NO rows at all", view.rows == (), str(view.rows))
_assert("  . nor any champion", view.champion_team_ids == (),
        str(view.champion_team_ids))
# A TABLE OF GMs ON ZERO IS A CLAIM THAT THEY ARE LEVEL. During the regular
# season there is nothing to be level about, which is why empty and zero are
# different answers here rather than the same one.
_assert("  . so no GM is reported as level with any other",
        len(view.rows) == 0)


# -- G4 . the LEGACY model is untouched ----------------------------------------

print("\nWP14R-G4 " + chr(0x00b7) + " a legacy season keeps the retired model")

from reports.grand_champion import (  # noqa: E402
    ChampionshipFinish, calculate_grand_champion,
)

_legacy = calculate_grand_champion(
    yahoo_finishes=(ChampionshipFinish(team_id=1, place=1),
                    ChampionshipFinish(team_id=2, place=2),
                    ChampionshipFinish(team_id=3, place=3)),
    fantasystakes_finishes=(ChampionshipFinish(team_id=2, place=1),
                            ChampionshipFinish(team_id=1, place=2),
                            ChampionshipFinish(team_id=3, place=3)),
    fantasystakes_scores={1: 100, 2: 900, 3: 50})
_assert("the retired calculator still runs and still decides",
        _legacy is not None and len(_legacy.champion_team_ids) >= 1,
        str(_legacy.champion_team_ids))
_assert("  . still on 3/2/1 pooled points",
        all(hasattr(r, "combined_points") for r in _legacy.rows))
_assert("  . and its Championship Score tiebreak still exists for legacy use",
        hasattr(_legacy, "tiebreak_used"))
# THE RETIRED MODULE IS NOT DELETED. WP-16 made this a rule for every
# retirement: a legacy season must still be readable by the rule it played
# under.
_assert("the retired module is still importable and still whole",
        callable(calculate_grand_champion))


# -- G5 . each payload says which model produced it ----------------------------

print("\nWP14R-G5 " + chr(0x00b7) + " the payload names its own rule")

_assert("the Final POR payload declares FINAL_POR",
        '"model": "FINAL_POR"' in _final_block)
_assert("  . and the legacy payload declares LEGACY_3_2_1",
        '"model": "LEGACY_3_2_1"' in _legacy_block)
# ONE KEY EACH, so an existing client reading `grand_champion` gets null on a
# season the retired rule never ran -- correct -- rather than a payload whose
# field names it recognises and whose meaning has changed underneath it.
_assert("the two live under different response keys",
        '"grand_champion": grand_champion' in _code
        and '"grand_championship": grand_final_por' in _code)


# -- G6 . a refusal travels rather than failing the response -------------------

print("\nWP14R-G6 " + chr(0x00b7) + " a refusal is carried, not raised")

_assert("the route catches §20's named refusal",
        "except GrandChampionshipError" in _code)
_assert("  . and puts its reason in the payload",
        '"unavailable_reason": _refusal.reason' in _code)
# THE PODIUMS BESIDE IT STAY READABLE. A response that failed entirely because
# one section does not apply would blank a page that has three other correct
# sections on it.
_assert("  . while the rest of the response is still returned",
        _code.index('"unavailable_reason": _refusal.reason')
        < _code.index('"fantasystakes_podium"'))

_assert("§20's pillar minimum is still two",
        MINIMUM_FUNDED_PILLARS == 2, str(MINIMUM_FUNDED_PILLARS))


print()
if _failures:
    print("=" * 52)
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("=" * 52)
print("WP-14 Grand Championship route: ALL ASSERTIONS PASS")
