#!/usr/bin/env python3
"""RC2 Championship economy certification on a temporary SQLite database.

This suite deliberately creates REAL base Season-Opening Allocation ledger
postings. Fabricated SeasonAllocation rows alone cannot certify Current Settle or
GM obligation attribution, which is the exact failure mode caught by the Opus
money-path audit.
"""
from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'rc2-econ.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text  # noqa: E402
from db.schema import (  # noqa: E402
    Base, League, LeagueSeasonEconomyConfig, SeasonAllocation, SessionLocal,
    Team, Wallet, engine,
)
from economy.current_settle import current_settle  # noqa: E402
from economy.fantasystakes_championship_allocation import (  # noqa: E402
    FantasyStakesChampionshipAllocation, FantasyStakesChampionshipConfig,
    DOOR_FS_CHAMPIONSHIP_COMMITMENT, pot_account, read_config, set_contribution,
)
from economy.rc2_season_activation import activate_fantasystakes_championship_stage  # noqa: E402
from ledger.ledger import (  # noqa: E402
    SEASON_ALLOCATION_DOOR, balance_of, create_ledger_table, post as ledger_post,
    trial_balance,
)

FAIL: list[str] = []
SEASON = 2027  # Intentionally differs from config.ALLOCATION_SEASON (2026).


def check(label: str, ok: bool, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


Base.metadata.create_all(engine)
create_ledger_table()

with SessionLocal() as db:
    league = League(
        season=SEASON,
        name="RC2 Economy",
        projection_source="fantasypros",
        start_week=1,
        playoff_start_week=15,
        season_final_week=17,
    )
    db.add(league)
    db.flush()
    league_id = league.id
    team_ids = []
    for i in range(4):
        t = Team(league_id=league_id, team_name=f"Team {i+1}", owner=f"Owner {i+1}",
                 email=f"econ-{i+1}@example.test")
        db.add(t)
        db.flush()
        team_ids.append(t.id)
        db.add(Wallet(team_id=t.id, balance=0.0))

    db.add(LeagueSeasonEconomyConfig(
        league_id=league_id,
        season=SEASON,
        weekly_bet_minimum_cents=1000,
        championship_contribution_cents=8000,
        skunk_fee_cents=1000,
        regular_season_week_count=14,
        active_team_count=4,
        start_week_used=1,
        playoff_start_week_used=15,
        frozen_at=None,
    ))

    # Certified RC1 base shape: $140 Weekly Play Reserve + $80 Yahoo reserve.
    for tid in team_ids:
        db.add(SeasonAllocation(
            league_id=league_id,
            team_id=tid,
            season=SEASON,
            buyin_cents=22000,
            min_reserve_cents=14000,
            reserve_cents=8000,
        ))
        ledger_post(
            [(f"season_issuance:{league_id}:{SEASON}", -22000),
             (f"min_reserve:{tid}", 14000),
             (f"reserve:{tid}", 8000)],
            door=SEASON_ALLOCATION_DOOR,
            session=db,
        )
    db.commit()

print("\nRC2-E1 · default and independent commissioner edit")
with SessionLocal() as db:
    view = read_config(db, league_id=league_id)
    check("FS contribution defaults equal to Yahoo contribution",
          view.season == SEASON
          and view.yahoo_championship_contribution_cents == 8000
          and view.fantasystakes_championship_contribution_cents == 8000
          and view.contributions_match)
    set_contribution(db, league_id=league_id, contribution_cents=10000)
    db.commit()

with SessionLocal() as db:
    before = {
        tid: current_settle(db, team_id=tid, league_id=league_id, season=SEASON)
        for tid in team_ids
    }
    check("base RC1 advance is 220 credits per GM",
          all(v.season_advance_cents == 22000 for v in before.values()), str(before))
    check("base Current Settle is -80 credits per GM before RC2 contribution",
          all(v.current_settle_cents == -8000 for v in before.values()), str(before))

print("\nRC2-E2 · activation attributes contribution to each GM and fixes the pot")
with SessionLocal() as db:
    result = activate_fantasystakes_championship_stage(league_id, db)
    check("league.season is authoritative even when config allocation season differs",
          result.season == SEASON, str(result))
    check("RC2 total opening allocation adds the edited FS contribution",
          result.weekly_plus_yahoo_per_gm_cents == 22000
          and result.fantasystakes_championship_per_gm_cents == 10000
          and result.season_opening_allocation_per_gm_cents == 32000,
          str(result))
    check("fixed FS pot equals per-GM contribution times active field",
          result.fantasystakes_championship_pot_cents == 40000)

with SessionLocal() as db:
    after = {
        tid: current_settle(db, team_id=tid, league_id=league_id, season=SEASON)
        for tid in team_ids
    }
    check("posted season advance is now 320 credits per GM",
          all(v.season_advance_cents == 32000 for v in after.values()), str(after))
    check("each GM is charged exactly the additional 100-credit FS contribution",
          all(after[tid].current_settle_cents == before[tid].current_settle_cents - 10000
              for tid in team_ids), str(after))

check("isolated FS pot contains exactly 400 credits",
      balance_of(pot_account(league_id, SEASON)) == 40000)
check("trial balance remains exactly zero after RC2 funding", trial_balance() == 0)

with SessionLocal() as db:
    replay = activate_fantasystakes_championship_stage(league_id, db)
    check("activation replay is idempotent and does not mint or charge again",
          not replay.created and replay.fantasystakes_championship_pot_cents == 40000)
check("replay leaves fixed pot unchanged", balance_of(pot_account(league_id, SEASON)) == 40000)
check("replay leaves trial balance zero", trial_balance() == 0)

with SessionLocal() as db:
    frozen_refused = False
    try:
        set_contribution(db, league_id=league_id, contribution_cents=12000)
    except Exception:
        frozen_refused = True
        db.rollback()
    check("FS contribution cannot change after activation", frozen_refused)

# A normal Top-Off is a different issuance door and cannot touch the FS pot.
ledger_post([("bab_issuance:test", -5000), (f"wallet:{team_ids[0]}", 5000)],
            door="approved_bab_topoff")
check("top-off movement does not grow FS Championship Pot",
      balance_of(pot_account(league_id, SEASON)) == 40000)

with SessionLocal() as db:
    cfg_rows = db.query(FantasyStakesChampionshipConfig).all()
    alloc_rows = db.query(FantasyStakesChampionshipAllocation).all()
    check("one frozen FS config row exists for the league season",
          len(cfg_rows) == 1 and cfg_rows[0].season == SEASON
          and cfg_rows[0].frozen_at is not None)
    check("one immutable FS allocation row exists per GM",
          len(alloc_rows) == len(team_ids)
          and {r.season for r in alloc_rows} == {SEASON})

    commitment_sum = db.execute(text(
        "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
        "WHERE door=:door AND account=:pot"),
        {"door": DOOR_FS_CHAMPIONSHIP_COMMITMENT,
         "pot": pot_account(league_id, SEASON)}).scalar()
    check("only the RC2 commitment door funds the FS pot",
          int(commitment_sum or 0) == 40000)

print("\n" + "=" * 64)
if FAIL:
    print(f"FAILED: {len(FAIL)} assertion(s)")
    for item in FAIL:
        print(f"  - {item}")
    sys.exit(1)
print("PASS: RC2 championship economy certification")
