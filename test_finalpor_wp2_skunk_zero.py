#!/usr/bin/env python3
"""FINAL POR · WP-2/WP-3 certification — optional Skunk and its season derivation.

    S1  a Weekly Skunk Fee of 0 validates, stores and freezes
    S2  the widened CHECK is live in the database, not just in the validator
    S3  the API contract admits 0
    S4  per-team Skunk is derived through economy_event, season-scoped
    S5  a tied week attributes each GM their SHARE, not the whole fee
    S6  a second season does not inherit the first season's Skunk
    S7  a shortfall-style receivable is NOT counted as Skunk
    S8  fee 0 means no assessment and therefore no Skunk in any Score

S7 IS THE ONE THAT MATTERS MOST. `receivable:{team}` is written by more than the
Skunk engine and carries no season. If the derivation ever reads that balance
directly, a GM's FantasyStakes Score silently absorbs a foreign obligation —
and, across seasons, last year's Skunk too.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import ledger.ledger as ledger_module
from db.schema import Base, League, LeagueSeasonEconomyConfig, Matchup, Team
from economy.economy_events import (
    EVENT_SKUNK_ASSESSMENT, league_week_key, receivable_account, record_event,
    skunk_account,
)
from economy.league_economy_config import (
    MIN_SKUNK_FEE_CENTS, EconomyConfigError, validate_inputs,
)
from economy.skunk import (
    DEFAULT_SKUNK_CONTRIBUTION_CENTS, assess_weekly_skunk,
    cumulative_skunk_fees_cents, skunk_fees_by_team,
)
from ledger.ledger import post as ledger_post

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def _db():
    """A disposable SQLite database, with the ledger pointed at it.

    `ledger.post(session=...)` writes through the caller's session, so the only
    redirection needed is the engine the schema was built on.
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    # `ledger_entries` lives on its own metadata, so it is built by the ledger's
    # own creator rather than by `Base.metadata.create_all`.
    ledger_module.engine = engine
    ledger_module._LedgerBase.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(db, *, league_id=1, season=2026, teams=(1, 2, 3, 4)):
    db.add(League(id=league_id, name=f"L{league_id}", season=season,
                  start_week=1, playoff_start_week=15))
    for t in teams:
        db.add(Team(id=t, league_id=league_id, team_name=f"T{t}",
                    owner=f"O{t}", email=f"t{t}@example.test",
                    provider_team_key=f"k{t}"))
    db.commit()


print("\nWP2-S1 · a Weekly Skunk Fee of 0 is a governed choice")
_assert("the governed minimum is 0", MIN_SKUNK_FEE_CENTS == 0,
        str(MIN_SKUNK_FEE_CENTS))
weekly, champ, skunk = validate_inputs(
    weekly_bet_minimum_cents=1000, championship_contribution_cents=8000,
    skunk_fee_cents=0)
_assert("validate_inputs accepts a 0 Skunk Fee", skunk == 0, str(skunk))
try:
    validate_inputs(weekly_bet_minimum_cents=1000,
                    championship_contribution_cents=8000, skunk_fee_cents=-100)
    _assert("a NEGATIVE Skunk Fee is still refused", False, "no exception")
except EconomyConfigError as exc:
    _assert("a NEGATIVE Skunk Fee is still refused", True, exc.reason)
try:
    validate_inputs(weekly_bet_minimum_cents=1000,
                    championship_contribution_cents=8000, skunk_fee_cents=150)
    _assert("a fractional-Credit Skunk Fee is still refused", False, "no exception")
except EconomyConfigError as exc:
    _assert("a fractional-Credit Skunk Fee is still refused", True, exc.reason)


print("\nWP2-S2 · the widened CHECK is live in the database")
db = _db()
_seed(db)
db.add(LeagueSeasonEconomyConfig(
    league_id=1, season=2026, weekly_bet_minimum_cents=1000,
    championship_contribution_cents=8000, skunk_fee_cents=0,
    created_at=NOW.replace(tzinfo=None)))
try:
    db.commit()
    _assert("a 0 Skunk Fee row commits against the live constraint", True)
except Exception as exc:                                     # noqa: BLE001
    db.rollback()
    _assert("a 0 Skunk Fee row commits against the live constraint", False,
            str(exc)[:120])

db.add(LeagueSeasonEconomyConfig(
    league_id=1, season=2027, weekly_bet_minimum_cents=1000,
    championship_contribution_cents=8000, skunk_fee_cents=-1,
    created_at=NOW.replace(tzinfo=None)))
try:
    db.commit()
    _assert("a NEGATIVE Skunk Fee is still refused by the database", False,
            "commit succeeded")
except Exception:
    db.rollback()
    _assert("a NEGATIVE Skunk Fee is still refused by the database", True)


print("\nWP2-S3 · the API contract admits 0")
from api.main import EconomyConfigUpdateRequest as EconomyConfigIn  # noqa: E402

_assert("the request model accepts skunk_fee_cents=0",
        EconomyConfigIn(weekly_bet_minimum_cents=1000,
                        championship_contribution_cents=8000,
                        skunk_fee_cents=0).skunk_fee_cents == 0)
try:
    EconomyConfigIn(weekly_bet_minimum_cents=1000,
                    championship_contribution_cents=8000, skunk_fee_cents=-1)
    _assert("the request model still refuses a negative fee", False, "accepted")
except Exception:
    _assert("the request model still refuses a negative fee", True)


print("\nWP2-S4 · per-team Skunk is derived through economy_event")
db = _db()
_seed(db)
# Team 3 loses week 1 by the widest margin.
db.add(Matchup(id=1, league_id=1, week=1, home_team_id=1, away_team_id=2,
               home_score=100.0, away_score=98.0, winner_team_id=1,
               finalized_at=NOW.replace(tzinfo=None)))
db.add(Matchup(id=2, league_id=1, week=1, home_team_id=3, away_team_id=4,
               home_score=60.0, away_score=120.0, winner_team_id=4,
               finalized_at=NOW.replace(tzinfo=None)))
db.commit()

result = assess_weekly_skunk(db, league_id=1, week=1,
                             contribution_cents=500, now=NOW)
db.commit()
_assert("the week assesses one fee against the widest loser",
        result.classification == "ASSESSED" and result.total_cents == 500
        and result.assessed == ((3, 500),), str(result.assessed))

by_team = skunk_fees_by_team(db, league_id=1, season=2026)
_assert("the derivation reports the skunked GM a POSITIVE 500",
        by_team == {3: 500}, str(by_team))
_assert("the single-GM read agrees with the sweep",
        cumulative_skunk_fees_cents(db, league_id=1, season=2026,
                                    team_id=3) == 500)
_assert("a GM never skunked reads 0",
        cumulative_skunk_fees_cents(db, league_id=1, season=2026,
                                    team_id=1) == 0)
_assert("the pot holds exactly what was assessed",
        ledger_module._balance_of_in_session(db, skunk_account(1)) == 500)


print("\nWP2-S5 · a tied week attributes each GM their SHARE")
db = _db()
_seed(db)
# Both losers go down by exactly 40 — a real margin tie.
db.add(Matchup(id=1, league_id=1, week=1, home_team_id=1, away_team_id=2,
               home_score=60.0, away_score=100.0, winner_team_id=2,
               finalized_at=NOW.replace(tzinfo=None)))
db.add(Matchup(id=2, league_id=1, week=1, home_team_id=3, away_team_id=4,
               home_score=60.0, away_score=100.0, winner_team_id=4,
               finalized_at=NOW.replace(tzinfo=None)))
db.commit()
tied = assess_weekly_skunk(db, league_id=1, week=1,
                           contribution_cents=500, now=NOW)
db.commit()
shares = skunk_fees_by_team(db, league_id=1, season=2026)
_assert("two GMs tie for the worst loss", len(tied.assessed) == 2,
        str(tied.assessed))
_assert("each is attributed 2.5 VC, not the whole 5 VC",
        shares == {1: 250, 3: 250}, str(shares))
_assert("and the week still assessed exactly ONE fee",
        sum(shares.values()) == 500, str(sum(shares.values())))


print("\nWP2-S6 · a second season does not inherit the first season's Skunk")
# The SAME receivable account, a DIFFERENT season's event.
db.execute(text("UPDATE leagues SET season = 2027 WHERE id = 1"))
db.commit()
_assert("season 2027 reads no Skunk from season 2026's postings",
        skunk_fees_by_team(db, league_id=1, season=2027) == {},
        str(skunk_fees_by_team(db, league_id=1, season=2027)))
_assert("  · while season 2026 still reads its own",
        skunk_fees_by_team(db, league_id=1, season=2026) == {1: 250, 3: 250})


print("\nWP2-S7 · a foreign receivable is NOT counted as Skunk")
# A shortfall-shaped posting against the SAME account, with no Skunk event.
before = skunk_fees_by_team(db, league_id=1, season=2026)
ledger_post([(receivable_account(1), -9_999), ("championship", 9_999)],
            door="shortfall_sweep", session=db)
db.commit()
after = skunk_fees_by_team(db, league_id=1, season=2026)
_assert("a shortfall_sweep receivable does not enter the Skunk total",
        after == before, f"{before} -> {after}")
_assert("  · even though the raw account balance moved",
        ledger_module._balance_of_in_session(db, receivable_account(1)) == -10_249,
        str(ledger_module._balance_of_in_session(db, receivable_account(1))))

# And an event of a NON-Skunk type must not be admitted either.
posting = ledger_post([(receivable_account(2), -777), ("championship", 777)],
                      door="shortfall_sweep", session=db)
record_event(db, event_key="OTHER|1|2026|99", league_id=1, season=2026,
             week=99, event_type="SOME_OTHER_EVENT", amount_cents=777,
             posting_id=posting, now=NOW)
db.commit()
_assert("  · nor does a receivable carried by a non-Skunk event",
        skunk_fees_by_team(db, league_id=1, season=2026) == before,
        str(skunk_fees_by_team(db, league_id=1, season=2026)))


print("\nWP2-S8 · a 0 fee assesses nothing, so no Score carries Skunk")
db = _db()
_seed(db, league_id=2, season=2026, teams=(11, 12))
db.add(Matchup(id=1, league_id=2, week=1, home_team_id=11, away_team_id=12,
               home_score=50.0, away_score=120.0, winner_team_id=12,
               finalized_at=NOW.replace(tzinfo=None)))
db.commit()
zero = assess_weekly_skunk(db, league_id=2, week=1, contribution_cents=0,
                           now=NOW)
db.commit()
_assert("a 0-fee week records the assessment event",
        zero.total_cents == 0, str(zero.total_cents))
_assert("  · and attributes no Skunk to anybody",
        skunk_fees_by_team(db, league_id=2, season=2026) == {},
        str(skunk_fees_by_team(db, league_id=2, season=2026)))
_assert("  · leaving the Skunk pot empty",
        ledger_module._balance_of_in_session(db, skunk_account(2)) == 0)
_assert("the historical default fee is unchanged for legacy seasons",
        DEFAULT_SKUNK_CONTRIBUTION_CENTS == 1000,
        str(DEFAULT_SKUNK_CONTRIBUTION_CENTS))


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-2/WP-3 optional Skunk + season derivation: all assertions passed")
