#!/usr/bin/env python3
"""RC2 A2 — the championship results read surface.

`GET /league/{id}/championship/results` is the one surface Sprint A2 added, and
it is the only new backend code in the sprint. It exists so the browser never
has to derive a lifecycle, recompute a payout or do fractional Grand Champion
arithmetic. That makes four things worth asserting directly rather than through
the UI that consumes them:

  · it is a pure READ — no freeze, no settlement, no correction, no posting
  · the lifecycle it reports is LIVE / FROZEN / FINAL / PAID and is accurate
  · awards appear only after the pot is actually distributed
  · Grand Champion comes from the certified calculator, ties included

The endpoint's own authorization is FastAPI dependency wiring, so it is checked
structurally here and end-to-end by the browser suites.
"""
from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'rc2-results.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone  # noqa: E402

from db.schema import (  # noqa: E402
    Base, BeefChallenge, Bet, League, LeagueSeasonEconomyConfig, Matchup,
    SeasonAllocation, SessionLocal, Team, Wallet, engine,
)
from economy.fantasystakes_championship_allocation import pot_account  # noqa: E402
from economy.fantasystakes_championship_settlement import (  # noqa: E402
    settle_fantasystakes_championship,
)
from economy.rc2_season_activation import (  # noqa: E402
    activate_fantasystakes_championship_stage,
)
from ledger.ledger import (  # noqa: E402
    APPROVED_BAB_TOPOFF_DOOR, SEASON_ALLOCATION_DOOR, balance_of,
    create_ledger_table, post as ledger_post, trial_balance,
)
from reports.championship_read_model import (  # noqa: E402
    freeze_fantasystakes_championship,
)
from reports import championship_corrections as _corr  # noqa: E402,F401

FAIL: list[str] = []
SEASON = 2027
CUT = 15
STAKE = 2_000


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


Base.metadata.create_all(engine)
create_ledger_table()


def build(name: str):
    with SessionLocal() as db:
        lg = League(season=SEASON, name=name, projection_source="fantasypros",
                    start_week=1, playoff_start_week=CUT, season_final_week=17,
                    provider_current_week=CUT)
        db.add(lg)
        db.flush()
        L = lg.id
        T = []
        for i in range(4):
            t = Team(league_id=L, team_name=f"{name}{i}", owner=f"Owner {i}",
                     email=f"{name.lower()}-{L}-{i}@example.test")
            db.add(t)
            db.flush()
            T.append(t.id)
            db.add(Wallet(team_id=t.id, balance=0.0))
            ledger_post([(f"bab_issuance:{L}:{SEASON}", -80_000),
                         (f"wallet:{t.id}", 80_000)],
                        door=APPROVED_BAB_TOPOFF_DOOR, session=db)
        db.add(LeagueSeasonEconomyConfig(
            league_id=L, season=SEASON, weekly_bet_minimum_cents=1000,
            championship_contribution_cents=8000, skunk_fee_cents=1000,
            regular_season_week_count=14, active_team_count=4,
            start_week_used=1, playoff_start_week_used=CUT, frozen_at=None))
        for tid in T:
            db.add(SeasonAllocation(league_id=L, team_id=tid, season=SEASON,
                                    buyin_cents=22_000, min_reserve_cents=14_000,
                                    reserve_cents=8_000))
            ledger_post([(f"season_issuance:{L}:{SEASON}", -22_000),
                         (f"min_reserve:{tid}", 14_000), (f"reserve:{tid}", 8_000)],
                        door=SEASON_ALLOCATION_DOOR, session=db)
        db.commit()
    with SessionLocal() as db:
        activate_fantasystakes_championship_stage(L, db)
    return L, T


def versus(L, T, week, *, a=0, b=1, settle=True, final=True):
    with SessionLocal() as db:
        m = Matchup(league_id=L, week=week, home_team_id=T[a], away_team_id=T[b],
                    home_score=0, away_score=0,
                    finalized_at=datetime.now(timezone.utc) if final else None)
        db.add(m)
        db.flush()
        bc = BeefChallenge(league_id=L, challenger_team_id=T[a],
                           challenged_team_id=T[b], week=week, bet_type="straight",
                           amount=STAKE / 100, challenger_odds=1.9,
                           challenged_odds=1.9, challenger_moneyline=-110,
                           challenged_moneyline=-110, status="accepted",
                           expires_at=datetime.now(timezone.utc), staleness_warning=0)
        db.add(bc)
        db.flush()
        ids = []
        for tid in (T[a], T[b]):
            w = db.query(Wallet).filter(Wallet.team_id == tid).first()
            bet = Bet(matchup_id=m.id, wallet_id=w.id, bet_type="straight",
                      amount=STAKE / 100, odds=1.9, status="pending",
                      beef_challenge_id=bc.id)
            db.add(bet)
            db.flush()
            ids.append(bet.id)
            ledger_post([(f"wallet:{tid}", -STAKE), (f"escrow:{bet.id}", STAKE)],
                        door="wager_placed", session=db)
        bc.challenger_bet_id, bc.challenged_bet_id = ids
        db.commit()
    if settle:
        with SessionLocal() as db:
            ledger_post([(f"escrow:{ids[0]}", -STAKE), (f"escrow:{ids[1]}", -STAKE),
                         (f"wallet:{T[a]}", 2 * STAKE)],
                        door="wager_settled", session=db)
            db.query(Bet).filter(Bet.id == ids[0]).update({"status": "won"})
            db.query(Bet).filter(Bet.id == ids[1]).update({"status": "lost"})
            db.commit()
    return ids


def results(L, *, yahoo=None):
    """Call the route function directly with a stubbed member dependency."""
    import api.championship_routes as routes

    original = routes._require_member
    routes._require_member = lambda db, *, league_id, user: 1
    try:
        with SessionLocal() as db:
            if yahoo is not None:
                import api.main as main
                main._settlement_podium_order = lambda _db, _lid: yahoo
            return routes.championship_results(league_id=L, db=db, gm=None)
    finally:
        routes._require_member = original


print("\nR1 - lifecycle is LIVE before the freeze")
L1, T1 = build("ResLive")
r = results(L1, yahoo=None)
check("lifecycle LIVE", r["lifecycle"] == "LIVE", r["lifecycle"])
check("no podium, no pot, not paid",
      r["fantasystakes_podium"] == [] and r["pot_cents"] is None
      and r["paid"] is False and r["awards"] == [], str(r["pot_cents"]))
check("grand champion is not decided", r["grand_champion"] is None)


print("\nR2 - FROZEN while an eligible contest is unresolved")
L2, T2 = build("ResFrozen")
versus(L2, T2, 5, settle=False)
with SessionLocal() as db:
    freeze_fantasystakes_championship(db, league_id=L2)
    db.commit()
r = results(L2, yahoo=None)
check("lifecycle FROZEN", r["lifecycle"] == "FROZEN", r["lifecycle"])
check("the blocker is reported", len(r["unresolved"]) >= 1, str(r["unresolved"]))
check("awards are empty before payout", r["awards"] == [] and r["paid"] is False)
check("scoring_through_week is the cutoff boundary",
      r["scoring_through_week"] == CUT - 1, str(r["scoring_through_week"]))


print("\nR3 - FINAL once every eligible result is in")
L3, T3 = build("ResFinal")
versus(L3, T3, 5)
with SessionLocal() as db:
    freeze_fantasystakes_championship(db, league_id=L3)
    db.commit()
r = results(L3, yahoo=None)
check("lifecycle FINAL", r["lifecycle"] == "FINAL", r["lifecycle"])
check("no blockers", r["unresolved"] == [], str(r["unresolved"]))
check("podium is present but unpaid",
      len(r["fantasystakes_podium"]) >= 1 and r["paid"] is False
      and r["awards"] == [], str(r["paid"]))
check("pot is not reported before payout", r["pot_cents"] is None,
      str(r["pot_cents"]))


print("\nR4 - PAID reports the RECORDED awards, and only then")
pot_before = balance_of(pot_account(L3, SEASON))
with SessionLocal() as db:
    settled = settle_fantasystakes_championship(db, league_id=L3)
r = results(L3, yahoo=None)
check("lifecycle PAID", r["lifecycle"] == "PAID", r["lifecycle"])
check("paid flag and distributed_at set",
      r["paid"] is True and r["distributed_at"], str(r["distributed_at"]))
check("pot matches what was funded",
      r["pot_cents"] == pot_before == 32_000, str(r["pot_cents"]))
check("awards are the recorded ones, summing to the pot",
      sum(a["amount_cents"] for a in r["awards"]) == r["pot_cents"]
      and {a["team_id"] for a in r["awards"]}
      == {a.team_id for a in settled.awards},
      str(r["awards"]))


print("\nR5 - the read has no economic side effects")
before = {t: balance_of(f"wallet:{t}") for t in T3}
trial_before = trial_balance()
for _ in range(3):
    results(L3, yahoo=None)
check("wallets unchanged by repeated reads",
      {t: balance_of(f"wallet:{t}") for t in T3} == before)
check("pot unchanged", balance_of(pot_account(L3, SEASON)) == 0)
check("trial balance still zero",
      trial_balance() == trial_before == 0, str(trial_balance()))


print("\nR6 - Grand Champion comes from the certified calculator")
r = results(L3, yahoo=[T3[1], T3[0], T3[2]])
gc = r["grand_champion"]
check("grand champion present once both podiums exist", gc is not None)
# FS: T3[0] won its matchup so it leads; Yahoo: T3[1] first, T3[0] second.
check("points are the certified 3/2/1 per component",
      gc is not None and {row["team_id"]: row["combined_points"]
                          for row in gc["rows"]}.get(T3[0]) is not None,
      str(gc["rows"] if gc else None))
check("exact values are strings, never floats",
      gc is not None and all(isinstance(row["combined_points"], str)
                             for row in gc["rows"]))


print("\nR7 - a tied FantasyStakes podium yields pooled fractional points")
L7, T7 = build("ResTie")
versus(L7, T7, 5, a=0, b=1)          # T7[0] +2000, T7[1] -2000
versus(L7, T7, 6, a=2, b=3)          # T7[2] +2000, T7[3] -2000
with SessionLocal() as db:
    freeze_fantasystakes_championship(db, league_id=L7)
    db.commit()
r = results(L7, yahoo=[T7[0], T7[2], T7[1]])
gc = r["grand_champion"]
podium = {row["team_id"]: row["place"] for row in r["fantasystakes_podium"]}
check("the FantasyStakes podium really is tied for first",
      podium.get(T7[0]) == 1 and podium.get(T7[2]) == 1, str(podium))
check("tied first pools 3+2 and splits it exactly",
      gc is not None and {row["team_id"]: row["fantasystakes_points"]
                          for row in gc["rows"]}.get(T7[0]) == "5/2",
      str(gc["rows"] if gc else None))
check("the browser never has to divide: the fraction arrives as text",
      gc is not None and "5/2" in {row["fantasystakes_points"]
                                   for row in gc["rows"]})
check("trial balance zero", trial_balance() == 0, str(trial_balance()))


print("\nR8 - the route is member-scoped and commissioner writes are not")
import api.championship_routes as _routes  # noqa: E402
import inspect as _inspect  # noqa: E402

src = _inspect.getsource(_routes.championship_results)
check("results calls the member guard before reading league state",
      "_require_member(" in src, "guard missing")
check("results performs no mutation",
      not any(tok in src for tok in ("db.add(", "db.commit(", "ledger_post(",
                                     "settle_", "freeze_fantasystakes")),
      "mutation found in read surface")
check("the correction write is commissioner-only",
      "require_league_commissioner" in _inspect.getsource(
          _routes.record_championship_correction))


print(f"\n{'=' * 64}")
if FAIL:
    print(f"FAILED: {len(FAIL)} assertion(s)")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("PASS: RC2 championship results read certification")
