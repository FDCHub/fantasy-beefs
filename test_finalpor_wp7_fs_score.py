#!/usr/bin/env python3
"""FINAL POR · WP-7 certification — FantasyStakes Score gains its Skunk term.

    F1  the identity is Matchups + Pools - Skunk
    F2  a LEGACY-ruleset season keeps the two-term identity
    F3  a FINAL POR season subtracts what its Skunk machinery posted
    F4  the SKUNK figure is a POSITIVE magnitude on the row and on the wire
    F5  Skunk changes the ranking, not just the display
    F6  Top-Off principal contributes nothing to the Score
    F7  the row still leaks no accounting state

F2 IS THE HISTORICAL-SAFETY ASSERTION. A legacy season's Score was frozen, paid
and recorded under the two-term identity. If the gate ever admits the Skunk term
there, every historical standing silently changes.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import ledger.ledger as ledger_module
from db.schema import Base, League, Matchup, Team, Wallet
from economy.skunk import assess_weekly_skunk
from ledger.ledger import APPROVED_BAB_TOPOFF_DOOR, post as ledger_post
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


def _build(final_por: bool):
    """A league with one skunked GM, under the requested ruleset."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=1, name="L", season=2026, start_week=1,
                  playoff_start_week=15))
    for t in (1, 2, 3, 4):
        db.add(Team(id=t, league_id=1, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider_team_key=f"k{t}"))
        db.add(Wallet(team_id=t, balance=0.0))
    # Team 3 loses week 1 by the widest margin and is the Skunk.
    db.add(Matchup(id=1, league_id=1, week=1, home_team_id=1, away_team_id=2,
                   home_score=100.0, away_score=98.0, winner_team_id=1,
                   finalized_at=NAIVE))
    db.add(Matchup(id=2, league_id=1, week=1, home_team_id=3, away_team_id=4,
                   home_score=60.0, away_score=120.0, winner_team_id=4,
                   finalized_at=NAIVE))
    db.commit()

    if final_por:
        stamp_ruleset(db, league_id=1, season=2026, version=RULESET_FINAL_POR)
        db.commit()

    assess_weekly_skunk(db, league_id=1, week=1, contribution_cents=500,
                        now=NOW)
    db.commit()
    return db


def _rows(db):
    return {r.team_id: r for r in league_standings(db, league_id=1).rows}


print("\nWP7-F1 · the identity")
import inspect  # noqa: E402

from reports.standings_read_model import StandingsRow  # noqa: E402

src = inspect.getsource(StandingsRow.net_cents.fget)
_assert("net_cents is versus + pool - skunk",
        "self.versus_net_cents + self.pool_net_cents - self.skunk_fees_cents"
        in src)


print("\nWP7-F2 · a LEGACY season keeps the two-term identity")
legacy = _rows(_build(final_por=False))
_assert("the skunked GM's row reports 0 Skunk under the legacy ruleset",
        legacy[3].skunk_fees_cents == 0, str(legacy[3].skunk_fees_cents))
_assert("  · so their Score is exactly Matchups + Pools",
        legacy[3].net_cents == legacy[3].versus_net_cents + legacy[3].pool_net_cents,
        str(legacy[3].net_cents))
_assert("  · and every GM's Score is unchanged at 0",
        all(r.net_cents == 0 for r in legacy.values()),
        str({t: r.net_cents for t, r in legacy.items()}))


print("\nWP7-F3 · a FINAL POR season subtracts what was posted")
db = _build(final_por=True)
final = _rows(db)
_assert("the skunked GM carries a 500 Skunk figure",
        final[3].skunk_fees_cents == 500, str(final[3].skunk_fees_cents))
_assert("  · and their FantasyStakes Score is -500",
        final[3].net_cents == -500, str(final[3].net_cents))
_assert("  · while an unskunked GM is unaffected",
        final[1].skunk_fees_cents == 0 and final[1].net_cents == 0)


print("\nWP7-F4 · SKUNK is a positive magnitude, on the row and on the wire")
_assert("the row's figure is positive", final[3].skunk_fees_cents > 0)
_assert("  · the serialised contract carries it positively",
        final[3].as_dict()["skunk_fees_cents"] == 500,
        str(final[3].as_dict()["skunk_fees_cents"]))
_assert("  · and net_cents has ALREADY subtracted it, so a client must not",
        final[3].as_dict()["net_cents"]
        == final[3].as_dict()["versus_net_cents"]
        + final[3].as_dict()["pool_net_cents"]
        - final[3].as_dict()["skunk_fees_cents"])


print("\nWP7-F5 · Skunk changes the RANKING, not just the display")
overall = [r.team_id for r in league_standings(db, league_id=1).overall]
_assert("the skunked GM ranks last on FantasyStakes Score",
        overall[-1] == 3, str(overall))
_assert("  · and ranks last only because of the Skunk term",
        final[3].versus_net_cents == 0 and final[3].pool_net_cents == 0,
        f"versus={final[3].versus_net_cents} pool={final[3].pool_net_cents}")


print("\nWP7-F6 · Top-Off principal contributes nothing to the Score")
before = _rows(db)[1].net_cents
ledger_post([("bab_issuance:1:2026", -2_000), ("wallet:1", 2_000)],
            door=APPROVED_BAB_TOPOFF_DOOR, session=db)
db.commit()
after = _rows(db)[1].net_cents
_assert("a 20 VC approved Top-Off moves the Score by exactly 0",
        after == before, f"{before} -> {after}")
_assert("  · even though the Wallet really was credited",
        ledger_module._balance_of_in_session(db, "wallet:1") == 2_000,
        str(ledger_module._balance_of_in_session(db, "wallet:1")))


print("\nWP7-F7 · the row still leaks no accounting state")
FORBIDDEN = ("wallet", "available", "current_settle", "settle", "obligation",
             "advance", "receivable", "topoff", "top_off", "reserve",
             "in_play", "held", "expired_min")
keys = set(final[3].as_dict())
_assert("no accounting field appears on the competitive row",
        not any(any(f in k for f in FORBIDDEN) for k in keys),
        " ".join(sorted(keys)))
_assert("  · and the Skunk column is the competitive figure, not the receivable",
        "skunk_fees_cents" in keys and "receivable_cents" not in keys)


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-7 FantasyStakes Score with Skunk: all assertions passed")
