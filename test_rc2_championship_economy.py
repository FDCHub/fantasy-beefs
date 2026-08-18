#!/usr/bin/env python3
"""RC2 Championship economy + Grand Champion certification on temp SQLite."""
from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'rc2-econ.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from db.schema import (  # noqa: E402
    Base, League, LeagueSeasonEconomyConfig, SeasonAllocation, SessionLocal,
    Team, Wallet, engine,
)
from economy.fantasystakes_championship_allocation import (  # noqa: E402
    FantasyStakesChampionshipAllocation, FantasyStakesChampionshipConfig,
    pot_account, read_config, set_contribution,
)
from economy.rc2_season_activation import activate_fantasystakes_championship_stage  # noqa: E402
from ledger.ledger import balance_of, create_ledger_table, post as ledger_post  # noqa: E402
from reports.grand_champion import (  # noqa: E402
    ChampionshipFinish, GrandChampionError, REASON_COMPONENT_TIE_UNRESOLVED,
    calculate_grand_champion,
)

FAIL: list[str] = []


def check(label: str, ok: bool, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


Base.metadata.create_all(engine)
create_ledger_table()

with SessionLocal() as db:
    league = League(
        season=config.ALLOCATION_SEASON,
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
    # Existing Yahoo economy configuration: $10 x 14 + $80 = $220 base.
    db.add(LeagueSeasonEconomyConfig(
        league_id=league_id,
        season=config.ALLOCATION_SEASON,
        weekly_bet_minimum_cents=1000,
        championship_contribution_cents=8000,
        skunk_fee_cents=1000,
        regular_season_week_count=14,
        active_team_count=4,
        start_week_used=1,
        playoff_start_week_used=15,
        frozen_at=None,
    ))
    for tid in team_ids:
        db.add(SeasonAllocation(
            league_id=league_id, team_id=tid, season=config.ALLOCATION_SEASON,
            buyin_cents=22000, min_reserve_cents=14000, reserve_cents=8000))
    db.commit()

print("\nRC2-E1 · default and independent commissioner edit")
with SessionLocal() as db:
    view = read_config(db, league_id=league_id, season=config.ALLOCATION_SEASON)
    check("FS contribution defaults equal to Yahoo contribution",
          view.yahoo_championship_contribution_cents == 8000
          and view.fantasystakes_championship_contribution_cents == 8000
          and view.contributions_match)
    set_contribution(db, league_id=league_id, season=config.ALLOCATION_SEASON,
                     contribution_cents=10000)
    db.commit()

with SessionLocal() as db:
    view = read_config(db, league_id=league_id, season=config.ALLOCATION_SEASON)
    check("commissioner may edit FS contribution independently before freeze",
          view.yahoo_championship_contribution_cents == 8000
          and view.fantasystakes_championship_contribution_cents == 10000
          and not view.contributions_match)

print("\nRC2-E2 · activation, fixed pot and opening-allocation arithmetic")
with SessionLocal() as db:
    result = activate_fantasystakes_championship_stage(league_id, db)
    check("RC2 total opening allocation adds FS championship contribution",
          result.weekly_plus_yahoo_per_gm_cents == 22000
          and result.fantasystakes_championship_per_gm_cents == 10000
          and result.season_opening_allocation_per_gm_cents == 32000,
          str(result))
    check("fixed FS pot equals per-GM contribution times active field",
          result.fantasystakes_championship_pot_cents == 40000)

check("ledger pot balance equals fixed funded amount",
      balance_of(pot_account(league_id, config.ALLOCATION_SEASON)) == 40000)

with SessionLocal() as db:
    replay = activate_fantasystakes_championship_stage(league_id, db)
    check("activation replay is idempotent and does not mint again",
          not replay.created and replay.fantasystakes_championship_pot_cents == 40000)
check("replay leaves fixed pot unchanged",
      balance_of(pot_account(league_id, config.ALLOCATION_SEASON)) == 40000)

with SessionLocal() as db:
    frozen_refused = False
    try:
        set_contribution(db, league_id=league_id, season=config.ALLOCATION_SEASON,
                         contribution_cents=12000)
    except Exception:
        frozen_refused = True
        db.rollback()
    check("FS contribution cannot change after activation", frozen_refused)

# A Top-Off-like wallet issuance cannot change this dedicated fixed pot.
ledger_post([("bab_issuance:test", -5000), (f"wallet:{team_ids[0]}", 5000)],
            door="approved_bab_topoff")
check("top-off movement does not grow FS Championship Pot",
      balance_of(pot_account(league_id, config.ALLOCATION_SEASON)) == 40000)

print("\nRC2-E3 · Grand Champion recognition")
normal = calculate_grand_champion(
    yahoo_finishes=(ChampionshipFinish(team_ids[0], 1), ChampionshipFinish(team_ids[1], 2),
                    ChampionshipFinish(team_ids[2], 3)),
    fantasystakes_finishes=(ChampionshipFinish(team_ids[1], 1), ChampionshipFinish(team_ids[0], 2),
                            ChampionshipFinish(team_ids[3], 3)),
)
check("3/2/1 combined scoring chooses the best combined season",
      normal.champion_team_ids == (team_ids[0], team_ids[1]) and normal.co_champions,
      str(normal))

component_tie_refused = None
try:
    calculate_grand_champion(
        yahoo_finishes=(ChampionshipFinish(team_ids[0], 1), ChampionshipFinish(team_ids[1], 1)),
        fantasystakes_finishes=(ChampionshipFinish(team_ids[2], 1),),
    )
except GrandChampionError as exc:
    component_tie_refused = exc.reason
check("unruled component-podium tie fails closed rather than inventing points",
      component_tie_refused == REASON_COMPONENT_TIE_UNRESOLVED,
      str(component_tie_refused))

with SessionLocal() as db:
    cfg_rows = db.query(FantasyStakesChampionshipConfig).all()
    alloc_rows = db.query(FantasyStakesChampionshipAllocation).all()
    check("one frozen FS config row exists", len(cfg_rows) == 1 and cfg_rows[0].frozen_at is not None)
    check("one immutable FS allocation row exists per GM", len(alloc_rows) == len(team_ids))

print("\n" + "=" * 64)
if FAIL:
    print(f"FAILED: {len(FAIL)} assertion(s)")
    for item in FAIL:
        print(f"  - {item}")
    sys.exit(1)
print("PASS: RC2 championship economy and Grand Champion certification")
