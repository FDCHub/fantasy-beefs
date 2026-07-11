"""
test_pool_engine_conversion.py — end-to-end coverage for the ledger-based
conversion of betting/pool_engine.py's collect_weekly_entries() and
settle_pool(). Exercises the real functions against a real (temp SQLite)
database — no mocks — since the whole point is confirming real ledger
postings conserve money correctly.

Covers:
  1. Basic single-week settlement — all three pots pay out, no rollover.
  2. Walletless team at collection — the whole collection aborts before
     any team is charged, not a partial charge of the teams that do have
     wallets.
  3. Rollover carry-forward across two real weeks (collect → settle →
     collect → settle) — no gain, no loss across the week boundary.
  4. No-predictors sweep — zero predictions submitted at all, rollover
     OFF, sweeps immediately to championship:{league_id} rather than
     paying every team (the old, incorrect behavior) or waiting for
     week 14.
  5. Week-14 expiry — unclaimed rollover sweeps to championship:{league_id}
     specifically at week 14, not before. Companion case: week 14 WITH a
     correct predictor pays the winner the full accumulated pool and does
     NOT sweep — proving the winner-branch-before-expiry-branch ordering
     (SP-9) holds in practice.
  6. Double-settlement guard — pot.settled fires before any second round
     of postings, not after a partial re-payout.
  7. Doubly-indivisible chained floor-division — total_pot_cents not
     evenly divisible by 3 (three-way split's st_share absorbs a real
     remainder) AND Biggest Winner has a genuine 2-way tie so its own
     _split_even() also absorbs a remainder, in the same settlement.
  8. Mid-season jackpot win — three consecutive rollover weeks (none
     week 14) accumulate, then a correct predictor in the fourth week
     collects the full three-week pile, not just that week's own share.
  9. FC-2 guard actually raises — a corrupted pot.total_pot_cents (not
     matching the real ledger balance) aborts settlement before any
     posting fires, not after a partial one.
  10. _credit()'s null-wallet check actually raises — a team that loses
      its wallet between collection and settlement aborts the ENTIRE
      settlement (one transaction, SP-3), not just the one pot it would
      have won.
  11. SP-1's primary branch — rollover OFF, predictors exist, none
      correct: the predictors split the pot: non-predicting teams get
      nothing from Worst Beat specifically (distinct from scenario 4,
      where zero predictions exist at all).
  12. FC-6b all-prior-weeks-settled guard — collect_weekly_entries()
      refuses to collect week N+1 while an earlier week is still
      unsettled, and confirms the guard does not block the normal,
      correctly-ordered collect -> settle -> collect flow.

Every scenario also asserts the PCM-9 conservation invariant explicitly:
    balance_of(f"pool:{league_id}") after settlement ==
    the new unpaid rollover amount for that pot (0 if fully paid out or
    swept, or the carried amount if it rolled forward).
This is deliberately NOT "sum of pool_payout postings this week ==
total_pot_cents this week" — that equality is false by design on any
rollover week.

Uses a temp SQLite DB so prod is never touched.
"""

import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_pool_engine_conversion.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone

from db.schema import (
    Base, engine, SessionLocal,
    League, Team, Wallet, Matchup, Player, Roster, Projection,
    PoolConfig, PoolPot, PoolPrediction,
)
from config import CURRENT_SEASON as SEASON
from betting.pool_engine import (
    setup_pool_config,
    collect_weekly_entries,
    submit_worst_beat_prediction,
    settle_pool,
)
from ledger.ledger import post as ledger_post, balance_of, create_ledger_table

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


# ── DB bootstrap ──────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)
create_ledger_table()

ENTRY_CENTS = 1000  # $10.00/week, the default economy stop
FUND_CENTS  = 100_000_00  # $100,000 — comfortably enough for any scenario here


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _make_league(name: str, worst_beat_rollover: bool = True, entry_cents: int = ENTRY_CENTS) -> int:
    with SessionLocal() as db:
        league = League(season=SEASON, name=f"Pool Conv Test {name}", projection_source="fantasypros")
        db.add(league)
        db.flush()
        league_id = league.id
        setup_pool_config(league_id, entry_cents / 100.0, worst_beat_rollover, db)
        cfg = db.query(PoolConfig).filter(PoolConfig.league_id == league_id).first()
        cfg.weekly_entry_cents = entry_cents
        db.commit()
        return league_id


def _make_team(league_id: int, name: str, fund_cents: int = FUND_CENTS) -> int:
    with SessionLocal() as db:
        team = Team(league_id=league_id, team_name=f"Pool {name}", owner=name, email=f"{name}@poolconv.com")
        db.add(team)
        db.flush()
        team_id = team.id
        db.add(Wallet(team_id=team_id, balance=1000.0))
        db.commit()
    ledger_post([("world", -fund_cents), (f"wallet:{team_id}", fund_cents)], door="buy_in_paid")
    return team_id


def _make_team_no_wallet(league_id: int, name: str) -> int:
    with SessionLocal() as db:
        team = Team(league_id=league_id, team_name=f"Pool {name}", owner=name, email=f"{name}@poolconv.com")
        db.add(team)
        db.commit()
        return team.id


def _seed_matchup(league_id: int, week: int, home_id: int, away_id: int, home_score: float, away_score: float) -> None:
    with SessionLocal() as db:
        db.add(Matchup(league_id=league_id, week=week, home_team_id=home_id, away_team_id=away_id,
                        home_score=home_score, away_score=away_score))
        db.commit()


_st_roster_cache: dict[int, tuple[int, int]] = {}  # team_id -> (k_player_id, def_player_id)


def _seed_special_teams(team_id: int, week: int, k_pts: float, def_pts: float) -> None:
    """
    _special_teams_score()/_st_breakdown() pick the FIRST-ever-rostered K/DEF
    player (by Roster.id) and look up THAT player's Projection for the
    requested week — they do not reselect a "current" K/DEF per week. So the
    K/DEF roster slots must be created exactly ONCE per team (persistent
    across weeks, like a real roster), and each week just adds a new
    Projection row for those same two player_ids. Creating fresh K/DEF
    players per week (as an earlier version of this helper did) leaves
    every subsequent week reading a stale, unprojected player and silently
    scoring 0.0 — a test-fixture bug, not a pool_engine.py bug (confirmed
    via direct instrumentation before concluding this).
    """
    if team_id not in _st_roster_cache:
        with SessionLocal() as db:
            k_player = Player(name=f"K-{team_id}", position="K", nfl_team="KC")
            d_player = Player(name=f"DEF-{team_id}", position="DEF", nfl_team="KC")
            db.add_all([k_player, d_player])
            db.flush()
            db.add(Roster(team_id=team_id, player_id=k_player.id))
            db.add(Roster(team_id=team_id, player_id=d_player.id))
            db.commit()
            _st_roster_cache[team_id] = (k_player.id, d_player.id)

    k_id, d_id = _st_roster_cache[team_id]
    with SessionLocal() as db:
        db.add(Projection(player_id=k_id, week=week, season=SEASON, source="fantasypros", actual_points=k_pts))
        db.add(Projection(player_id=d_id, week=week, season=SEASON, source="fantasypros", actual_points=def_pts))
        db.commit()


def _predict(league_id: int, team_id: int, predicted_team_id: int, week: int) -> None:
    with SessionLocal() as db:
        submit_worst_beat_prediction(league_id, team_id, predicted_team_id, week, db)


def _pot(league_id: int, week: int):
    with SessionLocal() as db:
        return db.query(PoolPot).filter(PoolPot.league_id == league_id, PoolPot.week == week).first()


# ── SCENARIO 1: basic single-week settlement, all three pots pay out ─────────

print("\nScenario 1: basic single-week settlement — all three pots pay out, no rollover")

L1 = _make_league("S1", worst_beat_rollover=True)
A1 = _make_team(L1, "A1")
B1 = _make_team(L1, "B1")
C1 = _make_team(L1, "C1")
D1 = _make_team(L1, "D1")

_seed_matchup(L1, 1, A1, B1, 150.0, 90.0)   # margin 60 — B1 is the worst beat
_seed_matchup(L1, 1, C1, D1, 110.0, 100.0)  # margin 10
_seed_special_teams(A1, 1, 12.0, 8.0)   # 20 — highest
_seed_special_teams(B1, 1, 5.0, 5.0)    # 10
_seed_special_teams(C1, 1, 9.0, 6.0)    # 15
_seed_special_teams(D1, 1, 2.0, 3.0)    # 5

_predict(L1, A1, B1, 1)  # correct
_predict(L1, C1, B1, 1)  # correct
_predict(L1, D1, A1, 1)  # wrong

with SessionLocal() as db:
    collect_weekly_entries(L1, 1, db)

pot1_before_settle = _pot(L1, 1)
_assert("S1: total_pot_cents == entry_cents * num_teams exactly", pot1_before_settle.total_pot_cents == ENTRY_CENTS * 4, f"got {pot1_before_settle.total_pot_cents}")

wallets_before_s1 = {tid: balance_of(f"wallet:{tid}") for tid in (A1, B1, C1, D1)}
champ_before_s1 = balance_of(f"championship:{L1}")

with SessionLocal() as db:
    result1 = settle_pool(L1, 1, db)

wallets_after_s1 = {tid: balance_of(f"wallet:{tid}") for tid in (A1, B1, C1, D1)}
champ_after_s1 = balance_of(f"championship:{L1}")

credited_total = sum(wallets_after_s1[tid] - wallets_before_s1[tid] for tid in (A1, B1, C1, D1))
champ_remainder = champ_after_s1 - champ_before_s1
_assert(
    "S1: sum of all pool_payout credits + any championship remainder == total_pot_cents",
    credited_total + champ_remainder == pot1_before_settle.total_pot_cents,
    f"credited={credited_total} champ_remainder={champ_remainder} total={pot1_before_settle.total_pot_cents}",
)
_assert("S1: no championship remainder this cycle (no rollover, no sweep)", champ_remainder == 0, f"got {champ_remainder}")
_assert("S1: Biggest Winner (A1) got credited", wallets_after_s1[A1] > wallets_before_s1[A1])
_assert("S1: Worst Beat correct predictors (A1, C1) got credited", wallets_after_s1[C1] > wallets_before_s1[C1])
_assert("S1: PCM-9 — pool balance == 0 (new unpaid rollover for this pot)", balance_of(f"pool:{L1}") == 0, f"got {balance_of(f'pool:{L1}')}")

pot1_after = _pot(L1, 1)
_assert("S1: pot.settled == True", pot1_after.settled is True)
_assert("S1: pot.settled_at is set", pot1_after.settled_at is not None)


# ── SCENARIO 2: walletless team at collection ─────────────────────────────────

print("\nScenario 2: walletless team — collection aborts before ANY team is charged")

L2 = _make_league("S2")
E2 = _make_team(L2, "E2")            # has a wallet, created FIRST (lower id)
F2 = _make_team_no_wallet(L2, "F2")  # no Wallet row at all

wallet_e2_before = balance_of(f"wallet:{E2}")
pool_before_s2   = balance_of(f"pool:{L2}")

raised_s2 = False
try:
    with SessionLocal() as db:
        collect_weekly_entries(L2, 1, db)
except ValueError:
    raised_s2 = True
_assert("S2: collect_weekly_entries() raises ValueError for the walletless team", raised_s2)
_assert(
    "S2: the earlier team (E2, processed before the walletless one) was NOT charged either — whole collection rolled back",
    balance_of(f"wallet:{E2}") == wallet_e2_before,
    f"before={wallet_e2_before} after={balance_of(f'wallet:{E2}')}",
)
_assert("S2: zero pool_entry_collected postings landed — pool balance unchanged", balance_of(f"pool:{L2}") == pool_before_s2, f"before={pool_before_s2} after={balance_of(f'pool:{L2}')}")


# ── SCENARIO 3: rollover carry-forward across two real weeks ─────────────────

print("\nScenario 3: rollover carry-forward across two real weeks — no gain, no loss at the boundary")

L3 = _make_league("S3", worst_beat_rollover=True)
G3 = _make_team(L3, "G3")
H3 = _make_team(L3, "H3")
I3 = _make_team(L3, "I3")
J3 = _make_team(L3, "J3")

# Week 5: zero correct Worst Beat predictors (rollover branch).
_seed_matchup(L3, 5, G3, H3, 140.0, 95.0)   # margin 45 — H3 is worst beat
_seed_matchup(L3, 5, I3, J3, 105.0, 100.0)  # margin 5
_seed_special_teams(G3, 5, 10.0, 8.0)
_seed_special_teams(H3, 5, 5.0, 4.0)
_seed_special_teams(I3, 5, 6.0, 6.0)
_seed_special_teams(J3, 5, 3.0, 2.0)
_predict(L3, G3, I3, 5)  # wrong — nobody correctly predicts H3
_predict(L3, H3, I3, 5)  # wrong

with SessionLocal() as db:
    collect_weekly_entries(L3, 5, db)

wallets_before_wk5 = {tid: balance_of(f"wallet:{tid}") for tid in (G3, H3, I3, J3)}

with SessionLocal() as db:
    settle_pool(L3, 5, db)

pot3_wk5 = _pot(L3, 5)
wb_share_cents_wk5 = 1000 * 4 // 3  # 1333, same math every week here (4 teams, $10 entry)
_assert("S3 week5: no pool_payout posted for Worst Beat this week", balance_of(f"wallet:{H3}") == wallets_before_wk5[H3], f"got delta {balance_of(f'wallet:{H3}') - wallets_before_wk5[H3]}")
_assert("S3 week5: pot.worst_beat_rollover_cents == this week's wb_share_cents (nothing carried in yet)", pot3_wk5.worst_beat_rollover_cents == wb_share_cents_wk5, f"got {pot3_wk5.worst_beat_rollover_cents}")
_assert("S3 week5: PCM-9 — pool balance == the new unpaid rollover (retained, not drained)", balance_of(f"pool:{L3}") == wb_share_cents_wk5, f"got {balance_of(f'pool:{L3}')}")

# Week 6: collect again — must pick up week 5's rollover exactly.
_seed_matchup(L3, 6, G3, H3, 130.0, 90.0)
_seed_matchup(L3, 6, I3, J3, 108.0, 101.0)
_seed_special_teams(G3, 6, 11.0, 7.0)
_seed_special_teams(H3, 6, 4.0, 4.0)
_seed_special_teams(I3, 6, 6.0, 5.0)
_seed_special_teams(J3, 6, 3.0, 2.0)

with SessionLocal() as db:
    collect_weekly_entries(L3, 6, db)

pot3_wk6_after_collect = _pot(L3, 6)
_assert(
    "S3 week6 (post-collect): incoming rollover == exactly what week5 retained — no gain, no loss",
    pot3_wk6_after_collect.worst_beat_rollover_cents == wb_share_cents_wk5,
    f"got {pot3_wk6_after_collect.worst_beat_rollover_cents}, expected {wb_share_cents_wk5}",
)

pot3_wk5_after_consume = _pot(L3, 5)
_assert("S3: week5's own rollover_cents reset to 0 after being consumed into week6", pot3_wk5_after_consume.worst_beat_rollover_cents == 0, f"got {pot3_wk5_after_consume.worst_beat_rollover_cents}")

# Week 6 has exactly one correct predictor this time.
_predict(L3, I3, H3, 6)  # correct — H3 is again the worst beat (margin 40 > margin 7)
_predict(L3, J3, G3, 6)  # wrong

wallet_i3_before_wk6 = balance_of(f"wallet:{I3}")

with SessionLocal() as db:
    settle_pool(L3, 6, db)

wb_total_expected_wk6 = wb_share_cents_wk5 + wb_share_cents_wk5  # this week's share + full carried rollover (same math both weeks)
_assert(
    "S3 week6: sole correct predictor (I3) gets THIS week's share PLUS the full carried rollover",
    balance_of(f"wallet:{I3}") - wallet_i3_before_wk6 == wb_total_expected_wk6,
    f"got {balance_of(f'wallet:{I3}') - wallet_i3_before_wk6}, expected {wb_total_expected_wk6}",
)
pot3_wk6_after_settle = _pot(L3, 6)
_assert("S3 week6: pot.worst_beat_rollover_cents == 0 after a winner takes it all", pot3_wk6_after_settle.worst_beat_rollover_cents == 0, f"got {pot3_wk6_after_settle.worst_beat_rollover_cents}")
_assert("S3 week6: PCM-9 — pool balance fully drained (0), winner took it all", balance_of(f"pool:{L3}") == 0, f"got {balance_of(f'pool:{L3}')}")


# ── SCENARIO 4: no-predictors sweep ───────────────────────────────────────────

print("\nScenario 4: no-predictors sweep — zero predictions submitted, rollover OFF")

L4 = _make_league("S4", worst_beat_rollover=False)
K4 = _make_team(L4, "K4")
M4 = _make_team(L4, "M4")
N4 = _make_team(L4, "N4")
O4 = _make_team(L4, "O4")

_seed_matchup(L4, 1, K4, M4, 130.0, 80.0)
_seed_matchup(L4, 1, N4, O4, 105.0, 100.0)
_seed_special_teams(K4, 1, 10.0, 9.0)
_seed_special_teams(M4, 1, 4.0, 4.0)
_seed_special_teams(N4, 1, 6.0, 6.0)
_seed_special_teams(O4, 1, 3.0, 2.0)
# Deliberately zero PoolPrediction rows submitted for this league/week at all.

with SessionLocal() as db:
    collect_weekly_entries(L4, 1, db)

champ_before_s4 = balance_of(f"championship:{L4}")
pool_before_settle_s4 = balance_of(f"pool:{L4}")

with SessionLocal() as db:
    result4 = settle_pool(L4, 1, db)

_assert("S4: num_correct == 0 (no predictions exist at all)", result4.worst_beat["correct_predictors"] == 0)

wb_share_cents_s4 = 1000 * 4 // 3  # 1333
champ_after_s4 = balance_of(f"championship:{L4}")
_assert(
    "S4: full wb_total_pool_cents credited to championship:{league_id}",
    champ_after_s4 - champ_before_s4 == wb_share_cents_s4,
    f"got {champ_after_s4 - champ_before_s4}, expected {wb_share_cents_s4}",
)

pot4 = _pot(L4, 1)
_assert("S4: pot.worst_beat_rollover_cents == 0 (swept, not carried)", pot4.worst_beat_rollover_cents == 0, f"got {pot4.worst_beat_rollover_cents}")
_assert("S4: PCM-9 — pool balance == 0 (fully drained: BW + swept-WB + ST)", balance_of(f"pool:{L4}") == 0, f"got {balance_of(f'pool:{L4}')}")


# ── SCENARIO 5: week-14 expiry, plus companion case with a correct predictor ──

print("\nScenario 5a: week-14 expiry — unclaimed rollover sweeps to championship, not carried again")

L5 = _make_league("S5a", worst_beat_rollover=True)
P5 = _make_team(L5, "P5")
Q5 = _make_team(L5, "Q5")
R5 = _make_team(L5, "R5")
S5 = _make_team(L5, "S5")

# Week 13 — a real, full rollover cycle (identical shape to Scenario 3's week 5).
_seed_matchup(L5, 13, P5, Q5, 140.0, 95.0)
_seed_matchup(L5, 13, R5, S5, 105.0, 100.0)
_seed_special_teams(P5, 13, 10.0, 8.0)
_seed_special_teams(Q5, 13, 5.0, 4.0)
_seed_special_teams(R5, 13, 6.0, 6.0)
_seed_special_teams(S5, 13, 3.0, 2.0)
_predict(L5, P5, R5, 13)  # wrong — nobody correctly predicts Q5 (the real worst beat)

with SessionLocal() as db:
    collect_weekly_entries(L5, 13, db)
with SessionLocal() as db:
    settle_pool(L5, 13, db)

wb_share_cents_wk13 = 1000 * 4 // 3  # 1333
pot5_wk13 = _pot(L5, 13)
_assert("S5a fixture check: week13 rolled over as expected", pot5_wk13.worst_beat_rollover_cents == wb_share_cents_wk13, f"got {pot5_wk13.worst_beat_rollover_cents}")

# Week 14 — collect (picks up week13's rollover), then settle with zero correct predictors.
_seed_matchup(L5, 14, P5, Q5, 130.0, 90.0)
_seed_matchup(L5, 14, R5, S5, 108.0, 101.0)
_seed_special_teams(P5, 14, 11.0, 7.0)
_seed_special_teams(Q5, 14, 4.0, 4.0)
_seed_special_teams(R5, 14, 6.0, 5.0)
_seed_special_teams(S5, 14, 3.0, 2.0)
_predict(L5, P5, R5, 14)  # wrong

with SessionLocal() as db:
    collect_weekly_entries(L5, 14, db)

champ_before_s5a = balance_of(f"championship:{L5}")

with SessionLocal() as db:
    settle_pool(L5, 14, db)

wb_total_wk14_expected = wb_share_cents_wk13 + wb_share_cents_wk13  # week14's own share + full carried rollover
champ_after_s5a = balance_of(f"championship:{L5}")
_assert(
    "S5a: full accumulated pool (this week's share + carried rollover) credited to championship, NOT carried again",
    champ_after_s5a - champ_before_s5a == wb_total_wk14_expected,
    f"got {champ_after_s5a - champ_before_s5a}, expected {wb_total_wk14_expected}",
)
pot5_wk14 = _pot(L5, 14)
_assert("S5a: pot.worst_beat_rollover_cents == 0 (expired, not carried)", pot5_wk14.worst_beat_rollover_cents == 0, f"got {pot5_wk14.worst_beat_rollover_cents}")
_assert("S5a: PCM-9 — pool balance == 0 (swept, nothing left unpaid)", balance_of(f"pool:{L5}") == 0, f"got {balance_of(f'pool:{L5}')}")


print("\nScenario 5b: week-14 companion — a correct predictor collects the full pool, NO expiry sweep fires")

L5b = _make_league("S5b", worst_beat_rollover=True)
P5b = _make_team(L5b, "P5b")
Q5b = _make_team(L5b, "Q5b")
R5b = _make_team(L5b, "R5b")
S5b = _make_team(L5b, "S5b")

# Week 13 — same rollover setup as 5a.
_seed_matchup(L5b, 13, P5b, Q5b, 140.0, 95.0)
_seed_matchup(L5b, 13, R5b, S5b, 105.0, 100.0)
_seed_special_teams(P5b, 13, 10.0, 8.0)
_seed_special_teams(Q5b, 13, 5.0, 4.0)
_seed_special_teams(R5b, 13, 6.0, 6.0)
_seed_special_teams(S5b, 13, 3.0, 2.0)
_predict(L5b, P5b, R5b, 13)  # wrong

with SessionLocal() as db:
    collect_weekly_entries(L5b, 13, db)
with SessionLocal() as db:
    settle_pool(L5b, 13, db)

pot5b_wk13 = _pot(L5b, 13)
wb_share_cents_wk13b = 1000 * 4 // 3

# Week 14 — this time WITH a correct predictor.
_seed_matchup(L5b, 14, P5b, Q5b, 130.0, 90.0)   # margin 40 — Q5b is worst beat again
_seed_matchup(L5b, 14, R5b, S5b, 108.0, 101.0)
_seed_special_teams(P5b, 14, 11.0, 7.0)
_seed_special_teams(Q5b, 14, 4.0, 4.0)
_seed_special_teams(R5b, 14, 6.0, 5.0)
_seed_special_teams(S5b, 14, 3.0, 2.0)
_predict(L5b, R5b, Q5b, 14)  # CORRECT this time

with SessionLocal() as db:
    collect_weekly_entries(L5b, 14, db)

champ_before_s5b = balance_of(f"championship:{L5b}")
wallet_r5b_before = balance_of(f"wallet:{R5b}")

with SessionLocal() as db:
    result5b = settle_pool(L5b, 14, db)

champ_after_s5b = balance_of(f"championship:{L5b}")
wb_total_wk14b_expected = wb_share_cents_wk13b + wb_share_cents_wk13b  # week14's share + carried rollover
_assert("S5b: NO expiry sweep — championship balance unchanged by this settlement", champ_after_s5b == champ_before_s5b, f"before={champ_before_s5b} after={champ_after_s5b}")
_assert(
    "S5b: the correct predictor (R5b) collects the FULL accumulated pool (this week's share + rollover)",
    balance_of(f"wallet:{R5b}") - wallet_r5b_before == wb_total_wk14b_expected,
    f"got {balance_of(f'wallet:{R5b}') - wallet_r5b_before}, expected {wb_total_wk14b_expected}",
)
pot5b_wk14 = _pot(L5b, 14)
_assert("S5b: pot.worst_beat_rollover_cents == 0 (winner took it all, nothing to expire)", pot5b_wk14.worst_beat_rollover_cents == 0, f"got {pot5b_wk14.worst_beat_rollover_cents}")
_assert("S5b: PCM-9 — pool balance == 0", balance_of(f"pool:{L5b}") == 0, f"got {balance_of(f'pool:{L5b}')}")


# ── SCENARIO 6: double-settlement guard ───────────────────────────────────────

print("\nScenario 6: double-settlement guard — the pot.settled guard fires before any second round of postings")

L6 = _make_league("S6")
T6 = _make_team(L6, "T6")
U6 = _make_team(L6, "U6")
V6 = _make_team(L6, "V6")
W6 = _make_team(L6, "W6")

_seed_matchup(L6, 1, T6, U6, 145.0, 88.0)
_seed_matchup(L6, 1, V6, W6, 112.0, 99.0)
_seed_special_teams(T6, 1, 12.0, 9.0)
_seed_special_teams(U6, 1, 4.0, 4.0)
_seed_special_teams(V6, 1, 7.0, 6.0)
_seed_special_teams(W6, 1, 2.0, 2.0)
_predict(L6, T6, U6, 1)  # correct

with SessionLocal() as db:
    collect_weekly_entries(L6, 1, db)
with SessionLocal() as db:
    settle_pool(L6, 1, db)

pool_after_first_settle_s6    = balance_of(f"pool:{L6}")
champ_after_first_settle_s6   = balance_of(f"championship:{L6}")
wallets_after_first_settle_s6 = {tid: balance_of(f"wallet:{tid}") for tid in (T6, U6, V6, W6)}

raised_s6 = False
try:
    with SessionLocal() as db:
        settle_pool(L6, 1, db)
except ValueError:
    raised_s6 = True
_assert("S6: settle_pool() raises ValueError on a second call for the same week", raised_s6)

_assert("S6: pool balance unchanged by the second (rejected) call", balance_of(f"pool:{L6}") == pool_after_first_settle_s6, f"before={pool_after_first_settle_s6} after={balance_of(f'pool:{L6}')}")
_assert("S6: championship balance unchanged by the second (rejected) call", balance_of(f"championship:{L6}") == champ_after_first_settle_s6, f"before={champ_after_first_settle_s6} after={balance_of(f'championship:{L6}')}")
for tid in (T6, U6, V6, W6):
    _assert(f"S6: wallet:{tid} unchanged by the second (rejected) call", balance_of(f"wallet:{tid}") == wallets_after_first_settle_s6[tid], f"got delta {balance_of(f'wallet:{tid}') - wallets_after_first_settle_s6[tid]}")


# ── SCENARIO 7: doubly-indivisible chained floor-division (FC-1) ─────────────
# entry_cents=700, 4 teams -> total_pot_cents=2800, NOT divisible by 3
# (share=933, remainder=1 -> st_share_cents=934). Biggest Winner is a
# genuine 2-way tie (933 not divisible by 2 -> _split_even() ALSO absorbs
# a remainder). Both floor-division stages fire with a nonzero remainder
# in the same settlement.

print("\nScenario 7: doubly-indivisible chained floor-division — both remainder stages fire together")

L7 = _make_league("S7", worst_beat_rollover=True, entry_cents=700)
X7 = _make_team(L7, "X7")
Y7 = _make_team(L7, "Y7")
Z7 = _make_team(L7, "Z7")
W7 = _make_team(L7, "W7")

# X7 and Y7 tie at the SAME score (100) -> neither beats the other, but
# both beat Z7(50) and W7(40) -> a genuine 2-way tie for Biggest Winner,
# both at 2 wins each (the max).
_seed_matchup(L7, 1, X7, Y7, 100.0, 100.0)  # margin 0
_seed_matchup(L7, 1, Z7, W7, 90.0, 40.0)    # margin 50 — W7 is the clear worst beat
_seed_special_teams(X7, 1, 10.0, 8.0)   # 18 — clear ST winner, no tie
_seed_special_teams(Y7, 1, 4.0, 4.0)    # 8
_seed_special_teams(Z7, 1, 6.0, 5.0)    # 11
_seed_special_teams(W7, 1, 2.0, 2.0)    # 4

_predict(L7, Z7, W7, 1)  # correct — sole correct predictor

with SessionLocal() as db:
    collect_weekly_entries(L7, 1, db)

pot7 = _pot(L7, 1)
_assert("S7: fixture check — total_pot_cents == 2800, NOT divisible by 3", pot7.total_pot_cents == 2800 and pot7.total_pot_cents % 3 != 0, f"got {pot7.total_pot_cents}")

wallets_before_s7 = {tid: balance_of(f"wallet:{tid}") for tid in (X7, Y7, Z7, W7)}

with SessionLocal() as db:
    result7 = settle_pool(L7, 1, db)

wallets_after_s7 = {tid: balance_of(f"wallet:{tid}") for tid in (X7, Y7, Z7, W7)}
deltas_s7 = {tid: wallets_after_s7[tid] - wallets_before_s7[tid] for tid in (X7, Y7, Z7, W7)}

share_cents_s7 = 2800 // 3       # 933
st_share_cents_s7 = 2800 - share_cents_s7 - share_cents_s7  # 934 — absorbs the three-way remainder
_assert("S7: three-way split sums exactly to total_pot_cents (933 + 933 + 934 == 2800)", share_cents_s7 * 2 + st_share_cents_s7 == 2800)

# Biggest Winner: X7 and Y7 tied, 933 cents split 2 ways -> 466/467, NOT
# evenly divisible by 2 -> _split_even()'s own remainder fires here.
# X7/Y7 might ALSO receive Worst Beat or Special Teams credit independently
# of Biggest Winner, so isolate BW specifically via the known other pots:
# Z7 is the sole Worst Beat predictor (gets wb_total_pool_cents fully),
# and Special Teams' sole winner is X7 (seeded to be the clear max).
wb_total_pool_cents_s7 = share_cents_s7  # no rollover yet, fresh league
_assert("S7: sole correct predictor (Z7) got the full Worst Beat share", deltas_s7[Z7] == wb_total_pool_cents_s7, f"got {deltas_s7[Z7]}, expected {wb_total_pool_cents_s7}")

# X7's total delta = its Biggest-Winner share (466 or 467) + the full
# Special Teams share (934, sole winner). Y7's total delta = its
# Biggest-Winner share only (the other half of the 933/2 split).
bw_share_x7_or_y7_sum = (deltas_s7[X7] - st_share_cents_s7) + deltas_s7[Y7]
_assert("S7: Biggest Winner's own _split_even() sums exactly to bw_share_cents (933), first team absorbs the 1-cent remainder", bw_share_x7_or_y7_sum == share_cents_s7, f"got {bw_share_x7_or_y7_sum}, expected {share_cents_s7}")
_assert("S7: the two Biggest-Winner co-winners did NOT split evenly (933 is odd) — confirms _split_even()'s remainder actually fired", (deltas_s7[X7] - st_share_cents_s7) != deltas_s7[Y7], f"got {deltas_s7[X7] - st_share_cents_s7} vs {deltas_s7[Y7]}")

grand_total_s7 = sum(deltas_s7.values())
_assert(
    "S7: GRAND TOTAL paid across all three pots' actual credits == total_pot_cents exactly — no leak between remainder stages",
    grand_total_s7 == 2800,
    f"got {grand_total_s7}",
)
_assert("S7: PCM-9 — pool balance == 0 (no rollover fired)", balance_of(f"pool:{L7}") == 0, f"got {balance_of(f'pool:{L7}')}")


# ── SCENARIO 8: mid-season jackpot win (FC-3) ─────────────────────────────────
# Three consecutive rollover weeks (none week 14), then a correct
# predictor in the fourth week collects the FULL three-week pile.

print("\nScenario 8: mid-season jackpot — three weeks of rollover, then a real winner takes it all")

L8 = _make_league("S8", worst_beat_rollover=True)
AA8 = _make_team(L8, "AA8")
BB8 = _make_team(L8, "BB8")
CC8 = _make_team(L8, "CC8")
DD8 = _make_team(L8, "DD8")

wb_share_cents_s8 = 1000 * 4 // 3  # 1333, same math as scenarios 1-6

def _seed_week_s8(week: int) -> None:
    _seed_matchup(L8, week, AA8, BB8, 140.0, 95.0)
    _seed_matchup(L8, week, CC8, DD8, 105.0, 100.0)
    _seed_special_teams(AA8, week, 10.0, 8.0)
    _seed_special_teams(BB8, week, 5.0, 4.0)
    _seed_special_teams(CC8, week, 6.0, 6.0)
    _seed_special_teams(DD8, week, 3.0, 2.0)

# Weeks 3, 4, 5 — zero correct predictors each week, rollover ON, at
# least one (wrong) prediction submitted each week (predictor-exists
# rollover path, not the no-predictors sweep).
expected_rollover_s8 = 0
for wk in (3, 4, 5):
    _seed_week_s8(wk)
    _predict(L8, AA8, CC8, wk)  # wrong every time — BB8 is always the real worst beat
    with SessionLocal() as db:
        collect_weekly_entries(L8, wk, db)
    with SessionLocal() as db:
        settle_pool(L8, wk, db)
    expected_rollover_s8 += wb_share_cents_s8
    pot8_wk = _pot(L8, wk)
    _assert(f"S8 week{wk}: rollover accumulates correctly (running total {expected_rollover_s8})", pot8_wk.worst_beat_rollover_cents == expected_rollover_s8, f"got {pot8_wk.worst_beat_rollover_cents}")

_assert("S8: fixture check — three weeks accumulated to exactly 3x one week's share", expected_rollover_s8 == wb_share_cents_s8 * 3, f"got {expected_rollover_s8}")

# Week 6 (N+3) — a correct predictor this time.
_seed_week_s8(6)
_predict(L8, CC8, BB8, 6)  # correct — BB8 is the worst beat again

with SessionLocal() as db:
    collect_weekly_entries(L8, 6, db)

pot8_wk6_after_collect = _pot(L8, 6)
_assert("S8 week6 (post-collect): incoming rollover == the full three-week accumulation", pot8_wk6_after_collect.worst_beat_rollover_cents == expected_rollover_s8, f"got {pot8_wk6_after_collect.worst_beat_rollover_cents}")

# Snapshot AFTER collection (this week's $10 entry debit already applied
# to every team, CC8 included) and BEFORE settlement — matching the
# pattern Scenario 3 already established, so the delta below isolates
# only the settlement-time Worst Beat credit, not the entry charge too.
wallet_cc8_before = balance_of(f"wallet:{CC8}")

with SessionLocal() as db:
    settle_pool(L8, 6, db)

expected_jackpot_s8 = wb_share_cents_s8 + expected_rollover_s8  # this week's own share + full 3-week pile
_assert(
    "S8: winner's payout == THIS week's share PLUS the FULL three-week accumulated rollover, not just one week's worth",
    balance_of(f"wallet:{CC8}") - wallet_cc8_before == expected_jackpot_s8,
    f"got {balance_of(f'wallet:{CC8}') - wallet_cc8_before}, expected {expected_jackpot_s8}",
)
pot8_wk6_after_settle = _pot(L8, 6)
_assert("S8: pot.worst_beat_rollover_cents resets to 0 after the jackpot pays out", pot8_wk6_after_settle.worst_beat_rollover_cents == 0, f"got {pot8_wk6_after_settle.worst_beat_rollover_cents}")
_assert("S8: PCM-9 — pool balance back to 0 (fully paid out, nothing pending)", balance_of(f"pool:{L8}") == 0, f"got {balance_of(f'pool:{L8}')}")


# ── SCENARIO 9: FC-2 guard actually raises ────────────────────────────────────

print("\nScenario 9: FC-2 reconciliation guard — a corrupted total_pot_cents aborts before any posting")

L9 = _make_league("S9")
EE9 = _make_team(L9, "EE9")
FF9 = _make_team(L9, "FF9")
GG9 = _make_team(L9, "GG9")
HH9 = _make_team(L9, "HH9")

_seed_matchup(L9, 1, EE9, FF9, 130.0, 90.0)
_seed_matchup(L9, 1, GG9, HH9, 108.0, 100.0)
_seed_special_teams(EE9, 1, 10.0, 8.0)
_seed_special_teams(FF9, 1, 5.0, 4.0)
_seed_special_teams(GG9, 1, 6.0, 5.0)
_seed_special_teams(HH9, 1, 3.0, 2.0)
_predict(L9, GG9, FF9, 1)  # correct

with SessionLocal() as db:
    collect_weekly_entries(L9, 1, db)

# Deliberately corrupt the pot's total_pot_cents — simulates a seed script
# or manual DB edit populating this field without a real, matching ledger
# posting. This is the exact case FC-2 exists to catch.
with SessionLocal() as db:
    pot9 = db.query(PoolPot).filter(PoolPot.league_id == L9, PoolPot.week == 1).first()
    pot9.total_pot_cents = pot9.total_pot_cents + 500  # now mismatched vs. the real ledger balance
    db.commit()

pool_before_s9    = balance_of(f"pool:{L9}")
wallets_before_s9 = {tid: balance_of(f"wallet:{tid}") for tid in (EE9, FF9, GG9, HH9)}

raised_s9 = False
error_msg_s9 = ""
try:
    with SessionLocal() as db:
        settle_pool(L9, 1, db)
except ValueError as e:
    raised_s9 = True
    error_msg_s9 = str(e)
_assert("S9: settle_pool() raises ValueError for the corrupted total_pot_cents", raised_s9)
_assert("S9: error message mentions the mismatch", "mismatch" in error_msg_s9.lower(), error_msg_s9)

_assert("S9: pool balance unchanged — guard aborted before any posting", balance_of(f"pool:{L9}") == pool_before_s9, f"before={pool_before_s9} after={balance_of(f'pool:{L9}')}")
for tid in (EE9, FF9, GG9, HH9):
    _assert(f"S9: wallet:{tid} unchanged — no partial payout landed", balance_of(f"wallet:{tid}") == wallets_before_s9[tid], f"got delta {balance_of(f'wallet:{tid}') - wallets_before_s9[tid]}")


# ── SCENARIO 10: _credit()'s null-wallet check actually raises ───────────────

print("\nScenario 10: _credit()'s null-wallet check — a team losing its wallet after collection aborts the WHOLE settlement")

L10 = _make_league("S10")
II10 = _make_team(L10, "II10")
JJ10 = _make_team(L10, "JJ10")
KK10 = _make_team(L10, "KK10")
LL10 = _make_team(L10, "LL10")

# II10 is set up to be the SOLE Biggest Winner — the first pot _credit()
# touches, so its missing wallet is hit as early as possible.
_seed_matchup(L10, 1, II10, JJ10, 150.0, 90.0)
_seed_matchup(L10, 1, KK10, LL10, 105.0, 100.0)
_seed_special_teams(II10, 1, 10.0, 8.0)
_seed_special_teams(JJ10, 1, 5.0, 4.0)
_seed_special_teams(KK10, 1, 6.0, 5.0)
_seed_special_teams(LL10, 1, 3.0, 2.0)
_predict(L10, JJ10, KK10, 1)  # a harmless prediction, correctness irrelevant here

with SessionLocal() as db:
    collect_weekly_entries(L10, 1, db)

# II10 had a wallet at collection time (it was successfully charged) —
# now remove it, simulating the wallet disappearing between collection
# and settlement.
with SessionLocal() as db:
    db.query(Wallet).filter(Wallet.team_id == II10).delete()
    db.commit()

pool_before_s10    = balance_of(f"pool:{L10}")
champ_before_s10   = balance_of(f"championship:{L10}")
wallets_before_s10 = {tid: balance_of(f"wallet:{tid}") for tid in (JJ10, KK10, LL10)}

raised_s10 = False
try:
    with SessionLocal() as db:
        settle_pool(L10, 1, db)
except ValueError:
    raised_s10 = True
_assert("S10: settle_pool() raises ValueError from _credit()'s null-wallet check", raised_s10)

_assert("S10: pool balance unchanged — the whole settlement rolled back, not just Biggest Winner's pot", balance_of(f"pool:{L10}") == pool_before_s10, f"before={pool_before_s10} after={balance_of(f'pool:{L10}')}")
_assert("S10: championship balance unchanged", balance_of(f"championship:{L10}") == champ_before_s10, f"before={champ_before_s10} after={balance_of(f'championship:{L10}')}")
for tid in (JJ10, KK10, LL10):
    _assert(f"S10: wallet:{tid} unchanged — no posting landed for ANY pot", balance_of(f"wallet:{tid}") == wallets_before_s10[tid], f"got delta {balance_of(f'wallet:{tid}') - wallets_before_s10[tid]}")


# ── SCENARIO 11: SP-1's primary branch — predictors exist, rollover OFF, none correct ──

print("\nScenario 11: SP-1 primary branch — rollover OFF, predictors exist but none correct, only predictors split the pot")

L11 = _make_league("S11", worst_beat_rollover=False)
MM11 = _make_team(L11, "MM11")  # Biggest Winner + Special Teams winner, NOT a predictor
NN11 = _make_team(L11, "NN11")  # predictor (wrong)
OO11 = _make_team(L11, "OO11")  # predictor (wrong)
PP11 = _make_team(L11, "PP11")  # the actual worst beat — NOT a predictor, no picks at all

_seed_matchup(L11, 1, MM11, NN11, 150.0, 100.0)  # margin 50
_seed_matchup(L11, 1, OO11, PP11, 90.0, 20.0)     # margin 70 — PP11 is the real worst beat
_seed_special_teams(MM11, 1, 10.0, 8.0)   # 18 — clear winner, and MM11=150 is the sole
_seed_special_teams(NN11, 1, 4.0, 5.0)    # highest overall score too (sole Biggest Winner,
_seed_special_teams(OO11, 1, 5.0, 3.0)    # beats all 3 others: NN11=100, OO11=90, PP11=20)
_seed_special_teams(PP11, 1, 2.0, 2.0)

_predict(L11, NN11, MM11, 1)  # wrong — actual worst beat is PP11, not MM11
_predict(L11, OO11, MM11, 1)  # wrong, same guess
# MM11 and PP11 submit no prediction at all this week.

with SessionLocal() as db:
    collect_weekly_entries(L11, 1, db)

wallets_before_s11 = {tid: balance_of(f"wallet:{tid}") for tid in (MM11, NN11, OO11, PP11)}

with SessionLocal() as db:
    result11 = settle_pool(L11, 1, db)

wallets_after_s11 = {tid: balance_of(f"wallet:{tid}") for tid in (MM11, NN11, OO11, PP11)}
deltas_s11 = {tid: wallets_after_s11[tid] - wallets_before_s11[tid] for tid in (MM11, NN11, OO11, PP11)}

_assert("S11: fixture check — num_correct == 0 (both predictions wrong)", result11.worst_beat["correct_predictors"] == 0)

share_cents_s11 = 1000 * 4 // 3  # 1333 — same math as other 4-team, $10/week scenarios
wb_split_total_s11 = deltas_s11[NN11] + deltas_s11[OO11]
_assert("S11: the two predictors (NN11, OO11) together receive the full Worst Beat share", wb_split_total_s11 == share_cents_s11, f"got {wb_split_total_s11}, expected {share_cents_s11}")
_assert("S11: the two predictors did NOT split evenly (1333 is odd) — _split_even()'s remainder fired", deltas_s11[NN11] != deltas_s11[OO11], f"got {deltas_s11[NN11]} vs {deltas_s11[OO11]}")
_assert("S11: PP11 (the actual worst beat, non-predictor) gets NOTHING — correct outcome, not the loser being paid", deltas_s11[PP11] == 0, f"got {deltas_s11[PP11]}")

st_share_cents_s11 = 4000 - share_cents_s11 - share_cents_s11  # 1334
_assert(
    "S11: MM11's total delta == exactly BW share + ST share (no Worst Beat leakage to a non-predictor)",
    deltas_s11[MM11] == share_cents_s11 + st_share_cents_s11,
    f"got {deltas_s11[MM11]}, expected {share_cents_s11 + st_share_cents_s11}",
)
_assert("S11: PCM-9 — pool balance == 0 (rollover OFF, fully distributed to BW/ST winner + WB predictors)", balance_of(f"pool:{L11}") == 0, f"got {balance_of(f'pool:{L11}')}")


# ── SCENARIO 12: collection blocked while a prior week is unsettled (FC-6b) ──

print("\nScenario 12: collect_weekly_entries() refuses week N+1 while an earlier week is unsettled")

L12 = _make_league("S12")
QQ12 = _make_team(L12, "QQ12")
RR12 = _make_team(L12, "RR12")

with SessionLocal() as db:
    collect_weekly_entries(L12, 3, db)  # week 3 collected, deliberately NOT settled

wallets_before_s12 = {tid: balance_of(f"wallet:{tid}") for tid in (QQ12, RR12)}
pool_before_s12    = balance_of(f"pool:{L12}")

raised_s12a = False
error_msg_s12a = ""
try:
    with SessionLocal() as db:
        collect_weekly_entries(L12, 4, db)
except ValueError as e:
    raised_s12a = True
    error_msg_s12a = str(e)
_assert("S12: collecting week4 while week3 is unsettled raises ValueError", raised_s12a)
_assert("S12: error message references week 3 specifically", "week 3" in error_msg_s12a, error_msg_s12a)

_assert(
    "S12: no team was charged for week4 — guard fired before any posting",
    balance_of(f"wallet:{QQ12}") == wallets_before_s12[QQ12] and balance_of(f"wallet:{RR12}") == wallets_before_s12[RR12],
    f"got {balance_of(f'wallet:{QQ12}')}/{balance_of(f'wallet:{RR12}')}, expected unchanged",
)
_assert(
    "S12: pool balance reflects only week3's collection, nothing added for week4",
    balance_of(f"pool:{L12}") == pool_before_s12,
    f"before={pool_before_s12} after={balance_of(f'pool:{L12}')}",
)
_assert("S12: no PoolPot row was created for week4 by the blocked attempt", _pot(L12, 4) is None)

# Companion check: settle week3 properly, then the SAME week4 collection
# must now succeed — confirming the guard doesn't block the normal,
# correctly-ordered flow.
_seed_matchup(L12, 3, QQ12, RR12, 120.0, 80.0)
_seed_special_teams(QQ12, 3, 8.0, 6.0)
_seed_special_teams(RR12, 3, 4.0, 3.0)

with SessionLocal() as db:
    settle_pool(L12, 3, db)

raised_s12b = False
try:
    with SessionLocal() as db:
        collect_weekly_entries(L12, 4, db)
except ValueError:
    raised_s12b = True
_assert("S12: after week3 is settled, collecting week4 succeeds (guard does not block the correctly-ordered flow)", not raised_s12b)

pot12_wk4 = _pot(L12, 4)
_assert("S12: week4's pot was actually created and marked collected", pot12_wk4 is not None and pot12_wk4.entries_collected is True)


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
