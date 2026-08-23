#!/usr/bin/env python3
"""FINAL POR · WP-9 certification — the Regular-Season Points Championship.

    F1  it EXISTS iff the Weekly Skunk Fee is above 0
    F2  the authoritative pot is the Skunk ACTUALLY assessed
    F3  the projection is fee x weeks, is a display figure, and is never posted
    F4  the pot is paid 60/30/10 through the ONE canonical split
    F5  ranking is regular-season Points For
    F6  a true tie is a DEAD HEAT, and the provider tiebreak is honestly absent
    F7  it settles only after every regular-season week is final
    F8  the distribution conserves and is exactly-once
    F9  a LEGACY season still pays the whole pot to the Points For leader

WHY F1 SEPARATES "EXISTS" FROM "FUNDED". Three different questions get the same
answer of 0 and must not be conflated: a league that set the fee to 0 has NO
Points Championship; a league with a real fee whose weeks have so far all tied
HAS one with nothing in it yet; and §20 later counts FUNDED pillars, which is a
third question again. F1 builds both leagues and requires them to report
differently.

WHY F3 IS AN ASSERTION AND NOT A COMMENT. The projection and the pot are equal
in the ordinary case, which is exactly when a bug substituting one for the other
would be invisible. The fixture is built so they DIFFER — a week where every
matchup tied assesses nothing — and then requires the paid amount to be the
assessed figure.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import ledger.ledger as ledger_module
from db.schema import (
    Base, League, LeagueSeasonEconomyConfig, Matchup, Team, Wallet,
)
from economy.championship_distribution import CHAMPIONSHIP_SPLIT
from economy.economy_events import points_championship_account
from economy.points_championship import (
    PointsChampionshipError,
    distribute,
    exists,
    pot_cents,
    projected_pot_cents,
    provider_tiebreak_available,
    view,
)
from economy.skunk import assess_weekly_skunk, distribute_season_skunk
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
WEEKS = 4                  # a short regular season: playoffs start at week 5
FEE = 500                  # 5 Credits per Skunk
TEAMS = (1, 2, 3, 4)
POT = points_championship_account(LEAGUE, SEASON)


def _build(*, final_por: bool = True, fee_cents: int = FEE):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=LEAGUE, name="L", season=SEASON, start_week=1,
                  playoff_start_week=WEEKS + 1))
    for t in TEAMS:
        db.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider_team_key=f"k{t}"))
        db.add(Wallet(team_id=t, balance=0.0))
    db.add(LeagueSeasonEconomyConfig(
        league_id=LEAGUE, season=SEASON,
        weekly_bet_minimum_cents=1_000,
        championship_contribution_cents=8_000,
        skunk_fee_cents=fee_cents,
        regular_season_week_count=WEEKS,
        active_team_count=len(TEAMS),
        start_week_used=1, playoff_start_week_used=WEEKS + 1,
        frozen_at=NAIVE))
    db.commit()
    if final_por:
        stamp_ruleset(db, league_id=LEAGUE, season=SEASON,
                      version=RULESET_FINAL_POR)
        db.commit()
    return db


def _week(db, week: int, scores, *, finalized: bool = True, base_id: int = 0):
    """Two matchups for one week. `scores` is (h1, a1, h2, a2)."""
    h1, a1, h2, a2 = scores
    stamp = NAIVE if finalized else None
    db.add(Matchup(id=base_id + 1, league_id=LEAGUE, week=week,
                   home_team_id=1, away_team_id=2,
                   home_score=h1, away_score=a1,
                   winner_team_id=(1 if h1 > a1 else 2 if a1 > h1 else None),
                   finalized_at=stamp))
    db.add(Matchup(id=base_id + 2, league_id=LEAGUE, week=week,
                   home_team_id=3, away_team_id=4,
                   home_score=h2, away_score=a2,
                   winner_team_id=(3 if h2 > a2 else 4 if a2 > h2 else None),
                   finalized_at=stamp))
    db.commit()


def _bal(db, account: str) -> int:
    return ledger_module._balance_of_in_session(db, account)


# ── F1 · exists iff the fee is above zero ────────────────────────────────────

print("\nWP9-F1 · the championship exists iff the Weekly Skunk Fee > 0")
with_fee = _build(fee_cents=FEE)
no_fee = _build(fee_cents=0)

_assert("a league with a real fee HAS a Points Championship",
        exists(with_fee, league_id=LEAGUE, season=SEASON))
_assert("  · a league with a 0 fee does NOT",
        not exists(no_fee, league_id=LEAGUE, season=SEASON))

v_fee = view(with_fee, league_id=LEAGUE, season=SEASON)
v_none = view(no_fee, league_id=LEAGUE, season=SEASON)
_assert("  · the fee league reports exists=True, funded=False before any week",
        v_fee.exists and not v_fee.funded, str(v_fee.as_dict()))
_assert("  · the 0-fee league reports exists=False AND funded=False",
        not v_none.exists and not v_none.funded, str(v_none.as_dict()))
_assert("  · so `exists` and `funded` are genuinely different questions",
        v_fee.exists != v_none.exists and v_fee.funded == v_none.funded)

try:
    distribute(no_fee, league_id=LEAGUE, season=SEASON, now=NOW)
    _assert("  · settling a 0-fee league is refused by name", False, "accepted")
except PointsChampionshipError as exc:
    _assert("  · settling a 0-fee league is refused by name",
            exc.reason == "POINTS_NO_CHAMPIONSHIP", exc.reason)


# ── F2/F3 · assessed vs projected ────────────────────────────────────────────

print("\nWP9-F2/F3 · the pot is what was ASSESSED; the projection is display only")
db = _build()
# Week 1: team 3 is skunked. Week 2: EVERY matchup ties, so nothing is assessed.
# Weeks 3-4: team 3 skunked again. Three of four weeks assess a fee.
_week(db, 1, (100.0, 98.0, 60.0, 120.0), base_id=0)
_week(db, 2, (100.0, 100.0, 90.0, 90.0), base_id=10)
_week(db, 3, (110.0, 100.0, 70.0, 130.0), base_id=20)
_week(db, 4, (105.0, 100.0, 80.0, 125.0), base_id=30)
for wk in (1, 2, 3, 4):
    try:
        assess_weekly_skunk(db, league_id=LEAGUE, week=wk, now=NOW)
    except Exception as exc:            # a fully tied week assesses nothing
        print(f"      (week {wk} assessed nothing: {type(exc).__name__})")
db.commit()

assessed = pot_cents(db, league_id=LEAGUE, season=SEASON)
projected = projected_pot_cents(db, league_id=LEAGUE, season=SEASON)

_assert("the projection is fee x regular-season weeks",
        projected == FEE * WEEKS, f"{projected} vs {FEE * WEEKS}")
_assert("  · the assessed pot is 3 weeks, not 4 — week 2 tied entirely",
        assessed == FEE * 3, f"{assessed} vs {FEE * 3}")
_assert("  · so the two figures genuinely DIFFER in this fixture",
        assessed != projected, f"assessed={assessed} projected={projected}")
_assert("  · the ledger holds the assessed figure and no other",
        _bal(db, POT) == assessed, str(_bal(db, POT)))
_assert("  · the projection was never posted anywhere",
        db.execute(text(
            "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
            "WHERE account = :a AND amount_cents = :p"),
            {"a": POT, "p": projected}).scalar() == 0)

from economy.championship_pots import ChampionshipPotError, mint_pot  # noqa: E402
from economy.economy_events import PILLAR_POINTS  # noqa: E402

try:
    mint_pot(db, league_id=LEAGUE, season=SEASON, pillar=PILLAR_POINTS,
             amount_cents=projected, now=NOW)
    _assert("  · and the pot cannot be minted to the projection", False,
            "accepted")
except ChampionshipPotError as exc:
    db.rollback()
    _assert("  · and the pot cannot be minted to the projection",
            exc.reason == "POT_NOT_MINTABLE", exc.reason)


# ── F4/F5 · 60/30/10 on Points For ──────────────────────────────────────────

print("\nWP9-F4/F5 · paid 60/30/10, ranked on regular-season Points For")
result = distribute(db, league_id=LEAGUE, season=SEASON, now=NOW)
db.commit()

by_team = {t: (place, amount, pf) for t, place, amount, pf in result.placements}
order = [t for t, _p, _a, _pf in result.placements]
points = {t: pf for t, _p, _a, pf in result.placements}

_assert("the pot paid is the assessed pot", result.pot_cents == assessed,
        str(result.pot_cents))
_assert("  · first place takes 60%",
        by_team[order[0]][1] == assessed * CHAMPIONSHIP_SPLIT[0] // 100
        + assessed - sum(assessed * p // 100 for p in CHAMPIONSHIP_SPLIT),
        f"{by_team[order[0]][1]} of {assessed}")
_assert("  · second place takes 30%",
        by_team[order[1]][1] == assessed * CHAMPIONSHIP_SPLIT[1] // 100,
        str(by_team[order[1]][1]))
_assert("  · third place takes 10%",
        by_team[order[2]][1] == assessed * CHAMPIONSHIP_SPLIT[2] // 100,
        str(by_team[order[2]][1]))
_assert("  · fourth place is paid nothing", by_team[order[3]][1] == 0,
        str(by_team[order[3]][1]))
_assert("  · the places are 1,2,3,4", [by_team[t][0] for t in order]
        == [1, 2, 3, 4], str([by_team[t][0] for t in order]))
_assert("  · the order really is descending Points For",
        all(points[order[i]] >= points[order[i + 1]] for i in range(3)),
        str([(t, points[t]) for t in order]))
_assert("  · team 4 leads on Points For and takes first",
        order[0] == 4, f"{order[0]} with {points[order[0]]}")
_assert("  · the Skunked GM is not excluded from the ranking, only outscored",
        3 in points, str(sorted(points)))
_assert("  · every award reached a Wallet",
        all(_bal(db, f"wallet:{t}") == by_team[t][1] for t in TEAMS),
        str({t: _bal(db, f"wallet:{t}") for t in TEAMS}))


# ── F6 · dead heat, and the honestly absent provider tiebreak ───────────────

print("\nWP9-F6 · a true tie is a dead heat; the provider tiebreak is absent")
_assert("no provider standings source is registered, and it says so",
        provider_tiebreak_available(db, league_id=LEAGUE) is False)
_assert("  · the view reports that to any reader",
        view(db, league_id=LEAGUE, season=SEASON)
        .provider_tiebreak_available is False)

tie = _build()
# Teams 1 and 2 finish level on Points For; 3 is skunked and last.
_week(tie, 1, (100.0, 98.0, 60.0, 120.0), base_id=0)
_week(tie, 2, (98.0, 100.0, 60.0, 120.0), base_id=10)
_week(tie, 3, (100.0, 100.0, 60.0, 120.0), base_id=20)
_week(tie, 4, (100.0, 100.0, 60.0, 120.0), base_id=30)
for wk in (1, 2, 3, 4):
    try:
        assess_weekly_skunk(tie, league_id=LEAGUE, week=wk, now=NOW)
    except Exception:
        pass
tie.commit()
tie_result = distribute(tie, league_id=LEAGUE, season=SEASON, now=NOW)
tie.commit()

tie_by = {t: (place, amount, pf) for t, place, amount, pf in tie_result.placements}
_assert("teams 1 and 2 really are level on Points For",
        tie_by[1][2] == tie_by[2][2], f"{tie_by[1][2]} vs {tie_by[2][2]}")
_assert("  · the result reports a dead heat", tie_result.dead_heat is True)
_assert("  · they share the SAME place, not an arbitrary 2nd and 3rd",
        tie_by[1][0] == tie_by[2][0], f"{tie_by[1][0]} vs {tie_by[2][0]}")
_assert("  · and the SAME award, to the cent",
        tie_by[1][1] == tie_by[2][1], f"{tie_by[1][1]} vs {tie_by[2][1]}")
_assert("  · neither was promoted by list order or by team id",
        tie_by[1][1] > 0 and tie_by[2][1] > 0)
_assert("  · the whole pot was still paid",
        sum(a for _t, _p, a, _pf in tie_result.placements)
        == tie_result.pot_cents,
        f"{sum(a for _t, _p, a, _pf in tie_result.placements)} of "
        f"{tie_result.pot_cents}")
_assert("  · and the pot account is empty afterwards",
        _bal(tie, POT) == 0, str(_bal(tie, POT)))


# ── F7 · finality ───────────────────────────────────────────────────────────

print("\nWP9-F7 · it settles only after every regular-season week is final")
pending = _build()
_week(pending, 1, (100.0, 98.0, 60.0, 120.0), base_id=0)
_week(pending, 2, (110.0, 100.0, 70.0, 130.0), base_id=10)
_week(pending, 3, (105.0, 100.0, 80.0, 125.0), base_id=20)
_week(pending, 4, (105.0, 100.0, 80.0, 125.0), finalized=False, base_id=30)
for wk in (1, 2, 3):
    assess_weekly_skunk(pending, league_id=LEAGUE, week=wk, now=NOW)
pending.commit()

_assert("the pot is funded and the championship exists",
        pot_cents(pending, league_id=LEAGUE, season=SEASON) > 0
        and exists(pending, league_id=LEAGUE, season=SEASON))
try:
    distribute(pending, league_id=LEAGUE, season=SEASON, now=NOW)
    _assert("  · but an unfinalised regular-season week refuses settlement",
            False, "accepted")
except PointsChampionshipError as exc:
    _assert("  · but an unfinalised regular-season week refuses settlement",
            exc.reason == "POINTS_REGULAR_SEASON_NOT_FINAL", exc.reason)
_assert("  · nothing was paid", all(_bal(pending, f"wallet:{t}") == 0
                                    for t in TEAMS))
_assert("  · and the pot is untouched",
        pot_cents(pending, league_id=LEAGUE, season=SEASON) > 0)

# The provider corrects the week; it finalises; settlement now proceeds.
for m in pending.query(Matchup).filter(Matchup.week == 4).all():
    m.finalized_at = NAIVE
pending.commit()
late = distribute(pending, league_id=LEAGUE, season=SEASON, now=NOW)
pending.commit()
_assert("  · once the week finalises, it settles",
        sum(a for _t, _p, a, _pf in late.placements) == late.pot_cents)
_assert("  · and the pot is drained", _bal(pending, POT) == 0)


# ── F8 · conservation and exactly-once ──────────────────────────────────────

print("\nWP9-F8 · the distribution conserves and is exactly-once")
_assert("the awards total exactly the pot",
        sum(a for _t, _p, a, _pf in result.placements) == result.pot_cents,
        f"{sum(a for _t, _p, a, _pf in result.placements)} of {result.pot_cents}")
_assert("  · the pot account is empty", _bal(db, POT) == 0, str(_bal(db, POT)))
_assert("  · the global trial balance is zero",
        ledger_module.trial_balance() == 0,
        str(ledger_module.trial_balance()))

from economy.economy_events import DuplicateEconomyEvent  # noqa: E402

wallets_before = {t: _bal(db, f"wallet:{t}") for t in TEAMS}
try:
    distribute(db, league_id=LEAGUE, season=SEASON, now=NOW)
    _assert("  · a replay is refused rather than paying twice", False,
            "accepted")
except (DuplicateEconomyEvent, PointsChampionshipError) as exc:
    db.rollback()
    _assert("  · a replay is refused rather than paying twice", True,
            type(exc).__name__)
_assert("  · and no Wallet moved on the replay",
        {t: _bal(db, f"wallet:{t}") for t in TEAMS} == wallets_before,
        str({t: _bal(db, f"wallet:{t}") for t in TEAMS}))
_assert("  · exactly one distribution event exists",
        db.execute(text("SELECT COUNT(*) FROM economy_event "
                        "WHERE event_type = 'SKUNK_DISTRIBUTION'")).scalar()
        == 1)


# ── F9 · the legacy era ─────────────────────────────────────────────────────

print("\nWP9-F9 · a LEGACY season still pays the whole pot to the leader")
old = _build(final_por=False)
_week(old, 1, (100.0, 98.0, 60.0, 120.0), base_id=0)
_week(old, 2, (110.0, 100.0, 70.0, 130.0), base_id=10)
for wk in (1, 2):
    assess_weekly_skunk(old, league_id=LEAGUE, week=wk, now=NOW)
old.commit()

legacy_pot = _bal(old, f"skunk:{LEAGUE}")
_assert("the legacy pot is the season-less `skunk:{league}`",
        legacy_pot == FEE * 2 and _bal(old, POT) == 0,
        f"skunk={legacy_pot} points={_bal(old, POT)}")
legacy = distribute_season_skunk(old, league_id=LEAGUE, now=NOW)
old.commit()

_assert("  · exactly one GM is paid", len(legacy.winners) == 1,
        str(legacy.winners))
_assert("  · and they take the WHOLE pot, not 60%",
        legacy.winners[0][1] == legacy_pot,
        f"{legacy.winners[0][1]} of {legacy_pot}")
_assert("  · which is the Points For leader",
        legacy.winners[0][0] == 4, str(legacy.winners[0][0]))
_assert("  · the legacy pot is drained", _bal(old, f"skunk:{LEAGUE}") == 0)
try:
    distribute(old, league_id=LEAGUE, season=SEASON, now=NOW)
    _assert("  · and the Final POR path refuses a legacy season", False,
            "accepted")
except PointsChampionshipError as exc:
    old.rollback()
    _assert("  · and the Final POR path refuses a legacy season",
            exc.reason == "POINTS_WRONG_ERA", exc.reason)


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-9 Regular-Season Points Championship: all assertions passed")
