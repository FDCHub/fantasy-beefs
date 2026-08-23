#!/usr/bin/env python3
"""FINAL POR · WP-8 certification — FantasyStakes lifecycle LIVE → FINAL → PAID.

    F1  postseason FantasyStakes scoring is LIVE — no playoff-boundary freeze
    F2  the boundary gate is retired, and a postseason action passes it freely
    F3  `freeze_fantasystakes_championship` REFUSES a Final POR season
    F4  `REASON_POSTSEASON_CONTAMINATED` is unreachable for a Final POR season
    F5  the three states, derived from posted state and never stored
    F6  the finality window is SEASON-WIDE and derived, not a cutoff literal
    F7  the pot is authoritative at FINAL, and refused while LIVE
    F8  a postseason result really does move the FantasyStakes Score
    F9  a LEGACY season keeps its boundary freeze, unchanged

WHY F8 EXISTS SEPARATELY FROM F1. F1 shows the GATE is gone. F8 shows the
CONSEQUENCE: a wager settled in a postseason week changes the GM's FantasyStakes
Score, which under RC2 it could not — the score had been snapshotted before the
postseason began. Retiring a gate that changed nothing would be cosmetic; this
is the assertion that the championship is actually decided differently.

WHY F6 CHECKS THE CUTOFF IS DERIVED. `unresolved_eligible_contests` asks about
weeks below a cutoff. Passing a literal 18 would work today and would be a
second, quieter assumption about season length — the same class of assumption
§18 exists to remove. The fixture uses a short season and requires the window to
follow the data.
"""
from __future__ import annotations

import inspect
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import ledger.ledger as ledger_module
# IMPORTED FOR ITS SIDE EFFECT, and it is a real one: the RC2 distribution-run
# model registers itself on `db.schema.Base` at import time, so a fixture that
# calls `create_all` before importing it builds a schema without that table.
# `api/main_rc2` imports the RC2 modules explicitly for the same reason.
import economy.fantasystakes_championship_settlement  # noqa: F401
from db.schema import (
    Base, BeefChallenge, Bet, League, LeagueSeasonEconomyConfig, Matchup, Team,
    Wallet,
)
from economy.championship_scoring_gate import (
    ChampionshipScoringGateError, require_championship_frozen_for_postseason,
)
from economy.fantasystakes_lifecycle import (
    LIFECYCLE_FINAL, LIFECYCLE_LIVE, LIFECYCLE_PAID, LIFECYCLE_STATES,
    FantasyStakesLifecycleError, authoritative_pot_cents, blockers,
    lifecycle_state, pot_cents, season_wide_cutoff, view,
)
from economy.weekly_minimum import expire_week, release_week
from ledger.ledger import (
    APPROVED_BAB_TOPOFF_DOOR, SEASON_ALLOCATION_DOOR, post as ledger_post,
)
from reports.championship_read_model import (
    FantasyStakesChampionshipError, freeze_fantasystakes_championship,
)
from reports.standings_read_model import league_standings
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
PLAYOFF_START = 5          # a short season: weeks 1-4 regular, 5-6 postseason
LAST_WEEK = 6
WEEKLY = 1_000
TEAMS = (1, 2, 3, 4)
POT = f"fantasystakes_championship:{LEAGUE}:{SEASON}"


def _build(*, final_por: bool = True):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=LEAGUE, name="L", season=SEASON, start_week=1,
                  playoff_start_week=PLAYOFF_START))
    for t in TEAMS:
        db.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider_team_key=f"k{t}"))
        db.add(Wallet(team_id=t, balance=0.0))
    mid = 0
    for week in range(1, LAST_WEEK + 1):
        mid += 1
        db.add(Matchup(id=mid, league_id=LEAGUE, week=week, home_team_id=1,
                       away_team_id=2, home_score=100.0, away_score=90.0,
                       winner_team_id=1, finalized_at=NAIVE))
        mid += 1
        db.add(Matchup(id=mid, league_id=LEAGUE, week=week, home_team_id=3,
                       away_team_id=4, home_score=80.0, away_score=95.0,
                       winner_team_id=4, finalized_at=NAIVE))
    db.add(LeagueSeasonEconomyConfig(
        league_id=LEAGUE, season=SEASON,
        weekly_bet_minimum_cents=WEEKLY,
        championship_contribution_cents=8_000,
        skunk_fee_cents=500,
        regular_season_week_count=PLAYOFF_START - 1,
        active_team_count=len(TEAMS),
        start_week_used=1, playoff_start_week_used=PLAYOFF_START,
        frozen_at=NAIVE))
    db.commit()
    if final_por:
        stamp_ruleset(db, league_id=LEAGUE, season=SEASON,
                      version=RULESET_FINAL_POR)
    for t in TEAMS:
        ledger_post([(f"season_issuance:{LEAGUE}:{SEASON}",
                      -WEEKLY * (PLAYOFF_START - 1)),
                     (f"min_reserve:{t}", WEEKLY * (PLAYOFF_START - 1))],
                    door=SEASON_ALLOCATION_DOOR, session=db)
    # Team 1 carries Wallet Credits so the fixture can place a POSTSEASON
    # wager, which §9F says is Wallet-only — exactly the state WP-8 governs.
    # Issued through the canonical approved Top-Off door rather than by writing
    # a balance, so the funded-balance guard is exercised as in production.
    for t in (1, 2):
        ledger_post([(f"bab_issuance:{LEAGUE}:{SEASON}", -1_000),
                     (f"wallet:{t}", 1_000)],
                    door=APPROVED_BAB_TOPOFF_DOOR, session=db)
    db.commit()
    return db


def _bal(db, account: str) -> int:
    return ledger_module._balance_of_in_session(db, account)


def _open_wager(db, *, week: int, challenge_id: int, bet_id: int,
                stake_cents: int, matchup_id: int):
    """A funded, still-pending TWO-SIDED wager between teams 1 and 2.

    BOTH SIDES ARE FUNDED, and that is not fixture detail. A one-sided stake
    that is returned in full is a PUSH — net zero — so it could never show a
    postseason result moving the Score, which is what F8 asks. Team 1 stakes,
    team 2 stakes, and the winner takes both.

    Built directly rather than through `issue_funded_challenge`: what WP-8
    governs is when the championship may be declared final, and what blocks
    finality is a PENDING Bet on an eligible contest. The funding path's own
    certification lives in WP-13's suite.
    """
    db.add(BeefChallenge(id=challenge_id, league_id=LEAGUE, week=week,
                         challenger_team_id=1, challenged_team_id=2,
                         bet_type="straight", amount=stake_cents / 100.0,
                         challenger_odds=2.0, challenged_odds=2.0,
                         challenger_moneyline=100, challenged_moneyline=100,
                         expires_at=NAIVE,
                         status="accepted", response_status="accepted",
                         created_at=NAIVE))
    for offset, team_id in ((0, 1), (1, 2)):
        wallet = db.query(Wallet).filter(Wallet.team_id == team_id).first()
        db.add(Bet(id=bet_id + offset, matchup_id=matchup_id,
                   wallet_id=wallet.id, amount=stake_cents / 100.0,
                   picked_team_id=team_id, status="pending",
                   placed_at=NAIVE, beef_challenge_id=challenge_id))
    db.flush()
    for offset, team_id in ((0, 1), (1, 2)):
        ledger_post([(f"wallet:{team_id}", -stake_cents),
                     (f"escrow:{bet_id + offset}", stake_cents)],
                    door="wager_placed", session=db)
    db.commit()


# ── F1/F2 · the gate is retired ─────────────────────────────────────────────

print("\nWP8-F1/F2 · postseason scoring is LIVE; the boundary gate is retired")
db = _build()
try:
    require_championship_frozen_for_postseason(db, league_id=LEAGUE,
                                               week=PLAYOFF_START)
    _assert("a postseason action passes the gate with no freeze", True)
except ChampionshipScoringGateError as exc:
    _assert("a postseason action passes the gate with no freeze", False,
            exc.reason)
_assert("  · and the LAST postseason week passes too",
        require_championship_frozen_for_postseason(
            db, league_id=LEAGUE, week=LAST_WEEK) is None)
_assert("  · no freeze marker was written",
        db.execute(text("SELECT COUNT(*) FROM "
                        "fantasystakes_championship_freeze")).scalar() == 0)

gate_src = inspect.getsource(require_championship_frozen_for_postseason)
_assert("  · the gate consults the one era predicate",
        "is_final_por" in gate_src)
_assert("  · and returns BEFORE the playoff_start_week requirement",
        gate_src.index("is_final_por(db, league_id=league_id")
        < gate_src.index("league.playoff_start_week is None"))


# ── F3/F4 · the freeze and the contamination refusal ───────────────────────

print("\nWP8-F3/F4 · the freeze refuses, so contamination is unreachable")
try:
    freeze_fantasystakes_championship(db, league_id=LEAGUE, now=NOW)
    _assert("freezing a Final POR season is refused", False, "accepted")
except FantasyStakesChampionshipError as exc:
    db.rollback()
    _assert("freezing a Final POR season is refused",
            exc.reason == "FS_CHAMPIONSHIP_FREEZE_RETIRED", exc.reason)
_assert("  · nothing was written",
        db.execute(text("SELECT COUNT(*) FROM "
                        "fantasystakes_championship_freeze")).scalar() == 0)

# COMMENTS ARE STRIPPED BEFORE THE ORDERING IS READ. Both reason codes are
# NAMED in the prose that explains the retirement, and an index over the raw
# source finds the explanation rather than the raise it explains — which is how
# this assertion first failed while the code was correct.
freeze_src = chr(10).join(
    line for line in
    inspect.getsource(freeze_fantasystakes_championship).splitlines()
    if not line.lstrip().startswith("#"))
_assert("  · the refusal precedes the contamination check",
        freeze_src.index("REASON_FREEZE_RETIRED")
        < freeze_src.index("REASON_POSTSEASON_CONTAMINATED"),
        "the contamination check would be reached first")
_assert("  · so REASON_POSTSEASON_CONTAMINATED is unreachable for this era",
        "is_final_por" in freeze_src)
_assert("  · but the replay branch still precedes BOTH",
        freeze_src.index("_existing_snapshot")
        < freeze_src.index("REASON_FREEZE_RETIRED"),
        "an already-snapshotted season would start raising")


# ── F5/F6 · the states, and the window ─────────────────────────────────────

print("\nWP8-F5 · three states, derived from posted state and never stored")
_assert("the lifecycle has exactly three states",
        LIFECYCLE_STATES == (LIFECYCLE_LIVE, LIFECYCLE_FINAL, LIFECYCLE_PAID),
        str(LIFECYCLE_STATES))
_assert("  · and no FROZEN among them",
        not any("FROZEN" in s for s in LIFECYCLE_STATES), str(LIFECYCLE_STATES))

import economy.fantasystakes_lifecycle as lc  # noqa: E402

_assert("  · no state is persisted — nothing here writes",
        all(token not in inspect.getsource(lc)
            for token in ("db.add(", "db.commit()", "ledger_post(")),
        "the module writes")

_assert("a clean season with no open contest is FINAL",
        lifecycle_state(db, league_id=LEAGUE) == LIFECYCLE_FINAL,
        lifecycle_state(db, league_id=LEAGUE))

# A pending POSTSEASON wager must hold the championship LIVE. Under RC2 it
# could not: postseason contests were not eligible at all.
_open_wager(db, week=PLAYOFF_START, challenge_id=1, bet_id=1,
            stake_cents=300, matchup_id=9)
_assert("  · an open POSTSEASON wager makes it LIVE",
        lifecycle_state(db, league_id=LEAGUE) == LIFECYCLE_LIVE,
        lifecycle_state(db, league_id=LEAGUE))
_assert("  · and names what is open",
        blockers(db, league_id=LEAGUE) != (),
        str(blockers(db, league_id=LEAGUE)))

print("\nWP8-F6 · the finality window is SEASON-WIDE and derived")
cutoff = season_wide_cutoff(db, league_id=LEAGUE, season=SEASON)
_assert("the cutoff sits ABOVE the last week played",
        cutoff > LAST_WEEK, f"{cutoff} vs last week {LAST_WEEK}")
_assert("  · it is not a hardcoded 18", cutoff != 18, str(cutoff))
_assert("  · it follows the data, not the calendar",
        cutoff == LAST_WEEK + 1, str(cutoff))
_assert("  · it is never below the playoff boundary",
        cutoff >= PLAYOFF_START)
cut_src = inspect.getsource(season_wide_cutoff)
_assert("  · derived from max(week) across the three contest tables",
        "func.max(Matchup.week)" in cut_src
        and "func.max(BeefChallenge.week)" in cut_src
        and "func.max(PoolInstance.week)" in cut_src)
_assert("  · the view reports the window it considered",
        view(db, league_id=LEAGUE).weeks_considered == LAST_WEEK,
        str(view(db, league_id=LEAGUE).weeks_considered))


# ── F7 · the pot at finality ───────────────────────────────────────────────

print("\nWP8-F7 · the pot is authoritative at FINAL, refused while LIVE")
release_week(db, league_id=LEAGUE, week=1, now=NOW)
db.commit()
expire_week(db, league_id=LEAGUE, week=1, now=NOW)
db.commit()
live_pot = pot_cents(db, league_id=LEAGUE, season=SEASON)

_assert("the pot has real money in it while LIVE", live_pot > 0, str(live_pot))
_assert("  · and `pot_cents` reports it for display",
        live_pot == _bal(db, POT), str(live_pot))
try:
    authoritative_pot_cents(db, league_id=LEAGUE, season=SEASON)
    _assert("  · but the AUTHORITATIVE pot is refused while LIVE", False,
            "accepted")
except FantasyStakesLifecycleError as exc:
    _assert("  · but the AUTHORITATIVE pot is refused while LIVE",
            exc.reason == "FS_LIFECYCLE_NOT_FINAL", exc.reason)
_assert("  · and the view says the pot is not authoritative",
        view(db, league_id=LEAGUE).pot_is_authoritative is False)

# The pot GROWS after the boundary — which is the whole reason it cannot be
# read as authoritative early.
release_week(db, league_id=LEAGUE, week=2, now=NOW)
db.commit()
expire_week(db, league_id=LEAGUE, week=2, now=NOW)
db.commit()
_assert("  · the pot really did grow after the first reading",
        pot_cents(db, league_id=LEAGUE, season=SEASON) > live_pot,
        f"{live_pot} -> {pot_cents(db, league_id=LEAGUE, season=SEASON)}")

# Resolve the open postseason wager; the championship becomes FINAL.
# Team 1 wins the postseason wager and takes BOTH stakes.
db.query(Bet).filter(Bet.id == 1).first().status = "won"
db.query(Bet).filter(Bet.id == 2).first().status = "lost"
ledger_post([("escrow:1", -300), ("escrow:2", -300), ("wallet:1", 600)],
            door="wager_settled", session=db)
db.commit()

_assert("  · once every contest resolves it is FINAL",
        lifecycle_state(db, league_id=LEAGUE) == LIFECYCLE_FINAL,
        lifecycle_state(db, league_id=LEAGUE))
final_pot = authoritative_pot_cents(db, league_id=LEAGUE, season=SEASON)
_assert("  · and the authoritative pot is now readable",
        final_pot == _bal(db, POT), str(final_pot))
_assert("  · the view agrees it is authoritative",
        view(db, league_id=LEAGUE).pot_is_authoritative is True)
_assert("  · with no blockers left", view(db, league_id=LEAGUE).blockers == ())

from economy.fantasystakes_championship_settlement import (  # noqa: E402
    FantasyStakesChampionshipDistributionRun as Run,
)

db.add(Run(league_id=LEAGUE, season=SEASON, pot_cents=final_pot,
           posting_id=__import__("uuid").uuid4(), awards_json=[],
           distributed_at=NOW))
db.commit()
_assert("  · and once distributed it is PAID",
        lifecycle_state(db, league_id=LEAGUE) == LIFECYCLE_PAID,
        lifecycle_state(db, league_id=LEAGUE))
_assert("  · PAID still reports the pot as authoritative",
        view(db, league_id=LEAGUE).pot_is_authoritative is True)


# ── F8 · a postseason result really moves the Score ────────────────────────

print("\nWP8-F8 · a postseason result really does move the FantasyStakes Score")
score = {r.team_id: r.net_cents
         for r in league_standings(db, league_id=LEAGUE).rows}
_assert("the GM who won a POSTSEASON wager carries a positive Score",
        score[1] > 0, str(score))
_assert("  · by exactly their opponent's stake",
        score[1] == 300, str(score[1]))
_assert("  · and the loser's Score fell by the same amount",
        score[2] == -300, str(score[2]))
_assert("  · which under RC2's boundary freeze neither could have",
        score[1] + score[2] == 0 and score[1] != 0, str(score))
_assert("  · and no snapshot row exists to have excluded it",
        db.execute(text("SELECT COUNT(*) FROM "
                        "fantasystakes_championship_freeze")).scalar() == 0)

from reports.standings_read_model import league_standings as _ls  # noqa: E402

_assert("  · the read model applies no week cutoff at all",
        "playoff_start_week" not in inspect.getsource(
            __import__("reports.standings_read_model",
                       fromlist=["x"])._door_net_cents))


# ── F9 · the legacy era ────────────────────────────────────────────────────

print("\nWP8-F9 · a LEGACY season keeps its boundary freeze, unchanged")
old = _build(final_por=False)
try:
    require_championship_frozen_for_postseason(old, league_id=LEAGUE,
                                               week=PLAYOFF_START)
    _assert("the legacy gate still tries to freeze at the boundary", False,
            "passed without a freeze")
except ChampionshipScoringGateError as exc:
    old.rollback()
    _assert("the legacy gate still tries to freeze at the boundary",
            exc.reason == "FS_CHAMPIONSHIP_NOT_FROZEN", exc.reason)
_assert("  · a regular-season week still passes it freely",
        require_championship_frozen_for_postseason(
            old, league_id=LEAGUE, week=1) is None)
try:
    lifecycle_state(old, league_id=LEAGUE)
    _assert("  · and the Final POR lifecycle refuses to describe it", False,
            "accepted")
except FantasyStakesLifecycleError as exc:
    _assert("  · and the Final POR lifecycle refuses to describe it",
            exc.reason == "FS_LIFECYCLE_WRONG_ERA", exc.reason)


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-8 FantasyStakes lifecycle LIVE -> FINAL -> PAID: all assertions passed")
