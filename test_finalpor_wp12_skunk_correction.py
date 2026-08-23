#!/usr/bin/env python3
"""FINAL POR · WP-12 certification — Skunk reverse / re-derive / re-post.

    F1  a correction that changes nothing writes nothing
    F2  a corrected week REVERSES, RE-DERIVES and RE-POSTS, in that ledger order
    F3  the reversal is SOURCE-FAITHFUL — the standing posting's own legs, negated
    F4  the FantasyStakes Score nets to the corrected figure, with no special case
    F5  the pot ends up holding exactly one week's fee, not two
    F6  correction-aware event keys make each generation exactly-once
    F7  provenance is preserved — nothing deleted, nothing updated
    F8  a week may be corrected repeatedly and the chain stays balanced
    F9  a correction after the pot was distributed is refused, having posted nothing
    F10 a LEGACY season is refused

WHY F4 IS THE ASSERTION THAT MATTERS MOST. A correction that balances the ledger
but leaves the wrongly-charged GM still carrying the fee in their FantasyStakes
Score has corrected the accounting and not the competition. The suite charges the
wrong GM, corrects it, and then requires the standings read model — untouched by
WP-12 — to report 0 for them and the full fee for the GM who was really skunked.

WHY F3 READS THE LEGS BACK RATHER THAN RECOMPUTING THEM. A reversal that
recomputes what the original "should have" been would silently diverge from what
was really posted if the fee had been reconfigured since. The suite reverses a
posting made at one fee after changing the governing fee, and requires the
reversal to match the ORIGINAL legs.
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
from economy.economy_events import (
    DOOR_SKUNK_ASSESSMENT,
    DOOR_SKUNK_CORRECTION_REPOST,
    DOOR_SKUNK_CORRECTION_REVERSAL,
    EVENT_SKUNK_ASSESSMENT,
    EVENT_SKUNK_ASSESSMENT_CORRECTION,
    EVENT_SKUNK_ASSESSMENT_REVERSAL,
    points_championship_account,
)
from economy.skunk import assess_weekly_skunk, skunk_fees_by_team
from economy.skunk_correction import (
    SkunkCorrectionError, correct_weekly_skunk, history, standing_assessment,
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
FEE = 500
TEAMS = (1, 2, 3, 4)
POT = points_championship_account(LEAGUE, SEASON)


def _build(*, final_por: bool = True, fee_cents: int = FEE):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=LEAGUE, name="L", season=SEASON, start_week=1,
                  playoff_start_week=15))
    for t in TEAMS:
        db.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider_team_key=f"k{t}"))
        db.add(Wallet(team_id=t, balance=0.0))
    db.add(LeagueSeasonEconomyConfig(
        league_id=LEAGUE, season=SEASON,
        weekly_bet_minimum_cents=1_000,
        championship_contribution_cents=8_000,
        skunk_fee_cents=fee_cents,
        regular_season_week_count=14,
        active_team_count=len(TEAMS),
        start_week_used=1, playoff_start_week_used=15,
        frozen_at=NAIVE))
    db.commit()
    if final_por:
        stamp_ruleset(db, league_id=LEAGUE, season=SEASON,
                      version=RULESET_FINAL_POR)
        db.commit()
    return db


def _week1(db, scores):
    """Two week-1 matchups. `scores` is (h1, a1, h2, a2)."""
    h1, a1, h2, a2 = scores
    db.add(Matchup(id=1, league_id=LEAGUE, week=1, home_team_id=1,
                   away_team_id=2, home_score=h1, away_score=a1,
                   winner_team_id=(1 if h1 > a1 else 2 if a1 > h1 else None),
                   finalized_at=NAIVE))
    db.add(Matchup(id=2, league_id=LEAGUE, week=1, home_team_id=3,
                   away_team_id=4, home_score=h2, away_score=a2,
                   winner_team_id=(3 if h2 > a2 else 4 if a2 > h2 else None),
                   finalized_at=NAIVE))
    db.commit()


def _correct_scores(db, scores):
    """The provider restates week 1. Same rows, corrected values."""
    h1, a1, h2, a2 = scores
    m1 = db.query(Matchup).filter(Matchup.id == 1).first()
    m2 = db.query(Matchup).filter(Matchup.id == 2).first()
    m1.home_score, m1.away_score = h1, a1
    m1.winner_team_id = 1 if h1 > a1 else 2 if a1 > h1 else None
    m2.home_score, m2.away_score = h2, a2
    m2.winner_team_id = 3 if h2 > a2 else 4 if a2 > h2 else None
    db.commit()


def _bal(db, account: str) -> int:
    return ledger_module._balance_of_in_session(db, account)


def _legs_under(db, door: str):
    return [(r[0], r[1]) for r in db.execute(text(
        "SELECT account, amount_cents FROM ledger_entries "
        "WHERE door = :d ORDER BY account"), {"d": door}).fetchall()]


def _events(db):
    return [(r[0], r[1], r[2]) for r in db.execute(text(
        "SELECT event_type, event_key, amount_cents FROM economy_event "
        "ORDER BY id")).fetchall()]


# ── F1 · a correction that changes nothing writes nothing ───────────────────

print("\nWP12-F1 · a correction that changes nothing writes nothing")
quiet = _build()
# Team 3 is skunked: loses by 60, the widest margin.
_week1(quiet, (100.0, 98.0, 60.0, 120.0))
assess_weekly_skunk(quiet, league_id=LEAGUE, week=1, now=NOW)
quiet.commit()
before_events = len(_events(quiet))
before_entries = quiet.execute(text(
    "SELECT COUNT(*) FROM ledger_entries")).scalar()

# The provider refreshes the week; the margins move but the Skunk does not.
_correct_scores(quiet, (101.0, 98.0, 61.0, 121.0))
unchanged = correct_weekly_skunk(quiet, league_id=LEAGUE, week=1, now=NOW)
quiet.commit()

_assert("the result reports no change", unchanged.changed is False)
_assert("  · the same GM is still assessed",
        unchanged.previous_assessed == unchanged.corrected_assessed
        == ((3, FEE),), str(unchanged.corrected_assessed))
_assert("  · NO event was recorded", len(_events(quiet)) == before_events,
        f"{before_events} -> {len(_events(quiet))}")
_assert("  · NO ledger entry was written",
        quiet.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()
        == before_entries)
_assert("  · the chain is still one link long",
        len(history(quiet, league_id=LEAGUE, week=1)) == 1,
        str(len(history(quiet, league_id=LEAGUE, week=1))))


# ── F2/F3 · reverse, re-derive, re-post ─────────────────────────────────────

print("\nWP12-F2/F3 · a corrected week reverses, re-derives and re-posts")
db = _build()
_week1(db, (100.0, 98.0, 60.0, 120.0))          # team 3 skunked, margin 60
assess_weekly_skunk(db, league_id=LEAGUE, week=1, now=NOW)
db.commit()
original_legs = _legs_under(db, DOOR_SKUNK_ASSESSMENT)

_assert("team 3 is charged the fee originally",
        _bal(db, "receivable:3") == -FEE, str(_bal(db, "receivable:3")))
_assert("  · and the pot holds one fee", _bal(db, POT) == FEE)

# The provider restates: team 1's opponent actually lost by 90, so team 2 is
# the Skunk and team 3 never was.
_correct_scores(db, (190.0, 100.0, 118.0, 120.0))
result = correct_weekly_skunk(db, league_id=LEAGUE, week=1, now=NOW)
db.commit()

_assert("the correction reports a change", result.changed is True)
_assert("  · it names who WAS charged", result.previous_assessed == ((3, FEE),),
        str(result.previous_assessed))
_assert("  · and who IS charged now", result.corrected_assessed == ((2, FEE),),
        str(result.corrected_assessed))
_assert("  · it is generation 1", result.generation == 1, str(result.generation))
_assert("  · reversed and reposted the same amount",
        result.reversed_cents == result.reposted_cents == FEE,
        f"{result.reversed_cents}/{result.reposted_cents}")

reversal_legs = _legs_under(db, DOOR_SKUNK_CORRECTION_REVERSAL)
repost_legs = _legs_under(db, DOOR_SKUNK_CORRECTION_REPOST)

_assert("the reversal is the original legs, negated, leg for leg",
        reversal_legs == [(a, -amt) for a, amt in original_legs],
        f"{reversal_legs} vs {original_legs}")
_assert("  · which un-charges team 3 exactly",
        ("receivable:3", FEE) in reversal_legs, str(reversal_legs))
_assert("  · and takes the fee back out of the pot",
        (POT, -FEE) in reversal_legs, str(reversal_legs))
_assert("the re-post charges team 2",
        ("receivable:2", -FEE) in repost_legs, str(repost_legs))
_assert("  · and puts the fee back into the pot",
        (POT, FEE) in repost_legs, str(repost_legs))
_assert("  · under its OWN door, distinct from an ordinary assessment",
        DOOR_SKUNK_CORRECTION_REPOST != DOOR_SKUNK_ASSESSMENT)
_assert("team 3 now carries no receivable at all",
        _bal(db, "receivable:3") == 0, str(_bal(db, "receivable:3")))
_assert("  · and team 2 carries the fee",
        _bal(db, "receivable:2") == -FEE, str(_bal(db, "receivable:2")))

# F3's real teeth: the fee is reconfigured, then an OLDER posting is reversed.
print("\nWP12-F3b · a reversal is faithful even after the fee changes")
refee = _build(fee_cents=FEE)
_week1(refee, (100.0, 98.0, 60.0, 120.0))
assess_weekly_skunk(refee, league_id=LEAGUE, week=1, now=NOW)
refee.commit()
old_legs = _legs_under(refee, DOOR_SKUNK_ASSESSMENT)
# The commissioner's frozen fee is edited directly — a state this module must
# tolerate rather than one it endorses; the point is the reversal must not
# recompute from it.
row = refee.query(LeagueSeasonEconomyConfig).first()
row.skunk_fee_cents = 900
refee.commit()
_correct_scores(refee, (190.0, 100.0, 118.0, 120.0))
r2 = correct_weekly_skunk(refee, league_id=LEAGUE, week=1, now=NOW)
refee.commit()

_assert("the reversal used the ORIGINAL 500, not the new 900",
        r2.reversed_cents == FEE, str(r2.reversed_cents))
_assert("  · reversing exactly the legs that were posted",
        _legs_under(refee, DOOR_SKUNK_CORRECTION_REVERSAL)
        == [(a, -amt) for a, amt in old_legs])
_assert("  · while the RE-POST correctly uses the governing fee, 900",
        r2.reposted_cents == 900, str(r2.reposted_cents))
_assert("  · so the previously charged GM is left at exactly zero",
        _bal(refee, "receivable:3") == 0, str(_bal(refee, "receivable:3")))


# ── F4 · the FantasyStakes Score nets ───────────────────────────────────────

print("\nWP12-F4 · the FantasyStakes Score nets to the corrected figure")
fees = skunk_fees_by_team(db, league_id=LEAGUE, season=SEASON)
_assert("the wrongly-charged GM's Skunk total is 0",
        fees.get(3, 0) == 0, str(fees.get(3, 0)))
_assert("  · the correctly-charged GM's is the full fee",
        fees.get(2, 0) == FEE, str(fees.get(2, 0)))
_assert("  · and the season total is one fee, not two",
        sum(fees.values()) == FEE, str(fees))

rows = {r.team_id: r for r in league_standings(db, league_id=LEAGUE).rows}
_assert("the standings read model reports 0 Skunk for the cleared GM",
        rows[3].skunk_fees_cents == 0, str(rows[3].skunk_fees_cents))
_assert("  · the full fee for the charged GM",
        rows[2].skunk_fees_cents == FEE, str(rows[2].skunk_fees_cents))
_assert("  · their FantasyStakes Score is -500",
        rows[2].net_cents == -FEE, str(rows[2].net_cents))
_assert("  · and the cleared GM's Score is back to 0",
        rows[3].net_cents == 0, str(rows[3].net_cents))
_assert("  · which the read model achieved with no WP-12 code of its own",
        "skunk_correction" not in
        __import__("inspect").getsource(
            __import__("reports.standings_read_model", fromlist=["x"])))


# ── F5 · the pot holds one fee ──────────────────────────────────────────────

print("\nWP12-F5 · the pot holds exactly one week's fee, not two")
_assert("the pot holds one fee", _bal(db, POT) == FEE, str(_bal(db, POT)))
_assert("  · the global trial balance is zero",
        ledger_module.trial_balance() == 0,
        str(ledger_module.trial_balance()))
_assert("  · the reversal legs sum to zero",
        sum(a for _acct, a in _legs_under(db, DOOR_SKUNK_CORRECTION_REVERSAL))
        == 0)
_assert("  · the re-post legs sum to zero",
        sum(a for _acct, a in _legs_under(db, DOOR_SKUNK_CORRECTION_REPOST))
        == 0)


# ── F6/F7 · keys, and provenance ───────────────────────────────────────────

print("\nWP12-F6 · correction-aware keys make each generation exactly-once")
events = _events(db)
keys = [k for _t, k, _a in events]
_assert("the original key is the plain league-week key",
        f"{EVENT_SKUNK_ASSESSMENT}:{LEAGUE}:{SEASON}:1" in keys, str(keys))
_assert("  · the reversal key names the generation it reverses",
        f"{EVENT_SKUNK_ASSESSMENT_REVERSAL}:{LEAGUE}:{SEASON}:1:gen0" in keys,
        str(keys))
_assert("  · the restatement key names its own generation",
        f"{EVENT_SKUNK_ASSESSMENT_CORRECTION}:{LEAGUE}:{SEASON}:1:gen1" in keys,
        str(keys))
_assert("  · every key is distinct", len(keys) == len(set(keys)), str(keys))
_assert("  · a plain league-week key could not have carried the restatement",
        f"{EVENT_SKUNK_ASSESSMENT_CORRECTION}:{LEAGUE}:{SEASON}:1" not in keys)

print("\nWP12-F7 · provenance is preserved — nothing deleted, nothing updated")
_assert("the original assessment event is still present, unchanged",
        (EVENT_SKUNK_ASSESSMENT,
         f"{EVENT_SKUNK_ASSESSMENT}:{LEAGUE}:{SEASON}:1", FEE) in events,
        str(events))
_assert("  · the original posting's legs are still readable",
        _legs_under(db, DOOR_SKUNK_ASSESSMENT) == original_legs,
        str(_legs_under(db, DOOR_SKUNK_ASSESSMENT)))
_assert("  · three events exist where one did — appended, not replaced",
        len(events) == 3, str(len(events)))

chain = history(db, league_id=LEAGUE, week=1)
_assert("  · the chain reads back oldest-first", len(chain) == 3,
        str([g.event_type for g in chain]))
_assert("  · and answers who was charged, and when it changed",
        chain[0].assessed == ((3, FEE),) and chain[-1].assessed == ((2, FEE),),
        f"{chain[0].assessed} -> {chain[-1].assessed}")
_assert("  · the standing assessment is the latest restatement",
        standing_assessment(db, league_id=LEAGUE, week=1).assessed
        == ((2, FEE),))


# ── F8 · repeated corrections ──────────────────────────────────────────────

print("\nWP12-F8 · a week may be corrected repeatedly and stays balanced")
_correct_scores(db, (105.0, 100.0, 20.0, 130.0))   # team 3 skunked again
third = correct_weekly_skunk(db, league_id=LEAGUE, week=1, now=NOW)
db.commit()

_assert("it is generation 2", third.generation == 2, str(third.generation))
_assert("  · reversing generation 1", third.previous_assessed == ((2, FEE),),
        str(third.previous_assessed))
_assert("  · and charging team 3 again",
        third.corrected_assessed == ((3, FEE),),
        str(third.corrected_assessed))
_assert("  · the pot STILL holds exactly one fee", _bal(db, POT) == FEE,
        str(_bal(db, POT)))
_assert("  · team 2 is back to zero", _bal(db, "receivable:2") == 0,
        str(_bal(db, "receivable:2")))
_assert("  · team 3 carries the fee once", _bal(db, "receivable:3") == -FEE,
        str(_bal(db, "receivable:3")))
final_fees = skunk_fees_by_team(db, league_id=LEAGUE, season=SEASON)
_assert("  · and the Score agrees after two corrections",
        final_fees.get(3, 0) == FEE and final_fees.get(2, 0) == 0,
        str(final_fees))
_assert("  · the trial balance is still zero",
        ledger_module.trial_balance() == 0)
_assert("  · five events now, all distinct",
        len(_events(db)) == 5
        and len({k for _t, k, _a in _events(db)}) == 5,
        str(len(_events(db))))


# ── F9 · after distribution ────────────────────────────────────────────────

print("\nWP12-F9 · a correction after the pot was distributed is refused")
paid = _build()
_week1(paid, (100.0, 98.0, 60.0, 120.0))
assess_weekly_skunk(paid, league_id=LEAGUE, week=1, now=NOW)
paid.commit()
# Drain the pot the way a settled Points Championship would.
from ledger.ledger import post as _post  # noqa: E402

_post([(POT, -FEE), ("wallet:1", FEE)], door="skunk_distribution", session=paid)
paid.commit()
_correct_scores(paid, (190.0, 100.0, 118.0, 120.0))
receivables_before = {t: _bal(paid, f"receivable:{t}") for t in TEAMS}
try:
    correct_weekly_skunk(paid, league_id=LEAGUE, week=1, now=NOW)
    _assert("the correction is refused by name", False, "accepted")
except SkunkCorrectionError as exc:
    paid.rollback()
    _assert("the correction is refused by name",
            exc.reason == "SKUNK_CORRECTION_POT_DISTRIBUTED", exc.reason)
_assert("  · nothing was posted",
        {t: _bal(paid, f"receivable:{t}") for t in TEAMS} == receivables_before,
        str({t: _bal(paid, f"receivable:{t}") for t in TEAMS}))
_assert("  · no correction event was recorded",
        not any(t in (EVENT_SKUNK_ASSESSMENT_REVERSAL,
                      EVENT_SKUNK_ASSESSMENT_CORRECTION)
                for t, _k, _a in _events(paid)), str(_events(paid)))
_assert("  · and the pot was not driven negative",
        _bal(paid, POT) == 0, str(_bal(paid, POT)))


# ── F10 · the legacy era ───────────────────────────────────────────────────

print("\nWP12-F10 · a LEGACY season is refused")
old = _build(final_por=False)
_week1(old, (100.0, 98.0, 60.0, 120.0))
assess_weekly_skunk(old, league_id=LEAGUE, week=1, now=NOW)
old.commit()
_correct_scores(old, (190.0, 100.0, 118.0, 120.0))
try:
    correct_weekly_skunk(old, league_id=LEAGUE, week=1, now=NOW)
    _assert("a legacy season's Skunk cannot be restated", False, "accepted")
except SkunkCorrectionError as exc:
    old.rollback()
    _assert("a legacy season's Skunk cannot be restated",
            exc.reason == "SKUNK_CORRECTION_WRONG_ERA", exc.reason)
_assert("  · its original assessment stands untouched",
        _bal(old, "receivable:3") == -FEE, str(_bal(old, "receivable:3")))
_assert("  · in the legacy pot, which is unaffected",
        _bal(old, f"skunk:{LEAGUE}") == FEE, str(_bal(old, f"skunk:{LEAGUE}")))

never = _build()
_week1(never, (100.0, 98.0, 60.0, 120.0))
try:
    correct_weekly_skunk(never, league_id=LEAGUE, week=1, now=NOW)
    _assert("  · and an unassessed week cannot be corrected", False, "accepted")
except SkunkCorrectionError as exc:
    never.rollback()
    _assert("  · and an unassessed week cannot be corrected",
            exc.reason == "SKUNK_CORRECTION_NEVER_ASSESSED", exc.reason)


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-12 Skunk reverse / re-derive / re-post: all assertions passed")
