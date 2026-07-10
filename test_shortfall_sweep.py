"""
test_shortfall_sweep.py — B2, Section 6: the weekly shortfall-to-
championship sweep.

Covers:
  A. Wagered exactly the weekly-min via versus bets — no shortfall, no sweep.
  B. Shortfall fully covered by the wallet — no receivable leg posted
     (no zero-value rows), trial_balance closes.
  C. Shortfall partially covered — both legs post (wallet+championship,
     receivable+championship), no zero rows, trial_balance closes.
  D. Wallet has zero funds — fully uncovered, only the receivable leg
     posts (the wallet leg is omitted entirely, not posted as $0).
  E. Pool participation (PoolPot.entries_collected) counts toward the
     weekly-min for every team in the league, independent of PoolBetPick.
  F. Idempotency — sweeping the same team/week twice does not double-post.
  G. Guard interaction (B2-6.2) — the pre-split posting never hands the
     ledger a raw shortfall against an unfunded wallet; no
     InsufficientFundsError even when the wallet can't fully cover.
  H. sweep_shortfall_for_week() sweeps every team in the league in one call.

Uses a temp SQLite DB so prod is never touched.
"""

import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_shortfall_sweep.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone

from db.schema import (
    Base, engine, SessionLocal,
    League, Team, Wallet, Matchup, Player, Roster, Bet,
    PoolConfig, PoolPot, ShortfallSweepRecord,
)
from payments.economy_config import set_league_economy_stop, ECONOMY_STOPS
from betting.shortfall_sweep import (
    sweep_shortfall_for_team,
    sweep_shortfall_for_week,
    sweep_explanation_text,
)
from ledger.ledger import post as ledger_post, balance_of, trial_balance, create_ledger_table

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

DEFAULT_STOP = ECONOMY_STOPS[1]  # weekly_min_cents=1000 ($10.00/week)


def _make_league(name: str, weekly_min_cents: int = 1000) -> int:
    with SessionLocal() as db:
        league = League(season=2025, name=f"Sweep Test {name}", projection_source="fantasypros")
        db.add(league)
        db.flush()
        set_league_economy_stop(league.id, weekly_min_cents, db)
        return league.id


def _make_team(league_id: int, name: str, wallet_balance_dollars: float = 1000.0) -> tuple[int, int]:
    with SessionLocal() as db:
        team = Team(league_id=league_id, team_name=f"Sweep {name}", owner=name, email=f"{name}@sweep.com")
        db.add(team)
        db.flush()
        for i in range(9):
            p = Player(name=f"{name}-P{i}", position="WR", nfl_team="KC")
            db.add(p); db.flush()
            db.add(Roster(team_id=team.id, player_id=p.id))
        wallet = Wallet(team_id=team.id, balance=wallet_balance_dollars)
        db.add(wallet)
        db.commit()
        return team.id, wallet.id


def _make_opponent_matchup(league_id: int, team_id: int, week: int) -> int:
    with SessionLocal() as db:
        opp = Team(league_id=league_id, team_name=f"Opp-{team_id}-{week}", owner="Opp", email=f"opp{team_id}{week}@sweep.com")
        db.add(opp)
        db.flush()
        m = Matchup(league_id=league_id, week=week, home_team_id=team_id, away_team_id=opp.id,
                    home_score=0.0, away_score=0.0)
        db.add(m)
        db.commit()
        return m.id


def _place_versus_bet(wallet_id: int, matchup_id: int, amount: float) -> None:
    with SessionLocal() as db:
        db.add(Bet(matchup_id=matchup_id, wallet_id=wallet_id, bet_type="straight",
                    description="test bet", amount=amount, odds=1.909, status="pending",
                    placed_at=datetime.now(timezone.utc)))
        db.commit()


def _fund_ledger_wallet(team_id: int, cents: int) -> None:
    ledger_post([("world", -cents), (f"wallet:{team_id}", cents)], door="buy_in_paid")


# ── SCENARIO A: wagered exactly the weekly-min — no shortfall ────────────────

print("\nScenario A: wagered exactly the weekly-min via versus bets — no shortfall")

league_a = _make_league("A")
t_a, w_a = _make_team(league_a, "A1")
m_a = _make_opponent_matchup(league_a, t_a, week=1)
_place_versus_bet(w_a, m_a, 10.0)  # exactly $10 = weekly_min_cents=1000
_fund_ledger_wallet(t_a, 100_000_00)

with SessionLocal() as db:
    result_a = sweep_shortfall_for_team(t_a, league_a, 1, db)

_assert("A: wagered_cents == 1000", result_a.wagered_cents == 1000, f"got {result_a.wagered_cents}")
_assert("A: shortfall_cents == 0", result_a.shortfall_cents == 0, f"got {result_a.shortfall_cents}")
_assert("A: swept is False", result_a.swept is False)
_assert("A: wallet:t_a ledger balance unchanged (no sweep)", balance_of(f"wallet:{t_a}") == 100_000_00, f"got {balance_of(f'wallet:{t_a}')}")
_assert("A: championship untouched", balance_of("championship") == 0, f"got {balance_of('championship')}")
_assert("A: trial_balance closes to 0", trial_balance() == 0, f"got {trial_balance()}")


# ── SCENARIO B: shortfall fully covered by the wallet ────────────────────────

print("\nScenario B: shortfall fully covered by the wallet — no receivable leg, no zero rows")

league_b = _make_league("B")
t_b, w_b = _make_team(league_b, "B1")
m_b = _make_opponent_matchup(league_b, t_b, week=1)
_place_versus_bet(w_b, m_b, 4.0)  # $4 wagered, $10 min -> $6 shortfall
_fund_ledger_wallet(t_b, 100_000_00)

championship_before_b = balance_of("championship")
with SessionLocal() as db:
    result_b = sweep_shortfall_for_team(t_b, league_b, 1, db)

_assert("B: shortfall_cents == 600 ($6.00)", result_b.shortfall_cents == 600, f"got {result_b.shortfall_cents}")
_assert("B: fully covered — covered_cents == 600", result_b.covered_cents == 600, f"got {result_b.covered_cents}")
_assert("B: uncovered_cents == 0", result_b.uncovered_cents == 0, f"got {result_b.uncovered_cents}")
_assert("B: swept is True", result_b.swept is True)
_assert("B: wallet:t_b debited $6.00", balance_of(f"wallet:{t_b}") == 100_000_00 - 600, f"got {balance_of(f'wallet:{t_b}')}")
_assert("B: championship credited $6.00", balance_of("championship") == championship_before_b + 600, f"got {balance_of('championship')}")
_assert("B: receivable:t_b untouched (no zero-value row)", balance_of(f"receivable:{t_b}") == 0, f"got {balance_of(f'receivable:{t_b}')}")
_assert("B: trial_balance closes to 0", trial_balance() == 0, f"got {trial_balance()}")


# ── SCENARIO C: shortfall partially covered — both legs post ────────────────

print("\nScenario C: shortfall partially covered — wallet leg + receivable leg both post")

league_c = _make_league("C")
t_c, w_c = _make_team(league_c, "C1")
m_c = _make_opponent_matchup(league_c, t_c, week=1)
# No versus bets at all -> full $10.00 shortfall. Fund wallet with only $4.00.
_fund_ledger_wallet(t_c, 400)

championship_before_c = balance_of("championship")
with SessionLocal() as db:
    result_c = sweep_shortfall_for_team(t_c, league_c, 1, db)

_assert("C: shortfall_cents == 1000 ($10.00)", result_c.shortfall_cents == 1000, f"got {result_c.shortfall_cents}")
_assert("C: covered_cents == 400 (bounded by wallet's funded balance)", result_c.covered_cents == 400, f"got {result_c.covered_cents}")
_assert("C: uncovered_cents == 600", result_c.uncovered_cents == 600, f"got {result_c.uncovered_cents}")
_assert("C: wallet:t_c drained to 0", balance_of(f"wallet:{t_c}") == 0, f"got {balance_of(f'wallet:{t_c}')}")
_assert("C: receivable:t_c shows $6.00 owed", balance_of(f"receivable:{t_c}") == -600, f"got {balance_of(f'receivable:{t_c}')}")
_assert("C: championship credited the full $10.00 (both legs)", balance_of("championship") == championship_before_c + 1000, f"got {balance_of('championship')}")
_assert("C: trial_balance closes to 0", trial_balance() == 0, f"got {trial_balance()}")


# ── SCENARIO D: wallet has zero funds — fully uncovered, wallet leg omitted ──

print("\nScenario D: unfunded wallet — fully uncovered, only the receivable leg posts")

league_d = _make_league("D")
t_d, w_d = _make_team(league_d, "D1")
m_d = _make_opponent_matchup(league_d, t_d, week=1)
# t_d's ledger wallet is never funded at all — stays at 0.

championship_before_d = balance_of("championship")
with SessionLocal() as db:
    result_d = sweep_shortfall_for_team(t_d, league_d, 1, db)

_assert("D: shortfall_cents == 1000", result_d.shortfall_cents == 1000, f"got {result_d.shortfall_cents}")
_assert("D: covered_cents == 0", result_d.covered_cents == 0, f"got {result_d.covered_cents}")
_assert("D: uncovered_cents == 1000 (fully via receivable)", result_d.uncovered_cents == 1000, f"got {result_d.uncovered_cents}")
_assert("D: wallet:t_d stays at 0 (no wallet leg posted at all)", balance_of(f"wallet:{t_d}") == 0, f"got {balance_of(f'wallet:{t_d}')}")
_assert("D: receivable:t_d shows the full $10.00 owed", balance_of(f"receivable:{t_d}") == -1000, f"got {balance_of(f'receivable:{t_d}')}")
_assert("D: championship credited $10.00", balance_of("championship") == championship_before_d + 1000, f"got {balance_of('championship')}")
_assert("D: trial_balance closes to 0", trial_balance() == 0, f"got {trial_balance()}")


# ── SCENARIO E: pool participation counts toward the weekly-min ─────────────

print("\nScenario E: PoolPot.entries_collected credits every team the flat weekly_entry, independent of PoolBetPick")

league_e = _make_league("E")
t_e, w_e = _make_team(league_e, "E1")
m_e = _make_opponent_matchup(league_e, t_e, week=1)
_fund_ledger_wallet(t_e, 100_000_00)

with SessionLocal() as db:
    db.add(PoolConfig(league_id=league_e, weekly_entry=10.0))
    db.add(PoolPot(league_id=league_e, week=1, entries_collected=True, total_pot=10.0))
    db.commit()

# No versus bets, no PoolBetPick row for this team at all — but the pool
# was collected league-wide, so this team should still get full credit.
with SessionLocal() as db:
    result_e = sweep_shortfall_for_team(t_e, league_e, 1, db)

_assert("E: wagered_cents == 1000 (pool credit alone, no PoolBetPick needed)", result_e.wagered_cents == 1000, f"got {result_e.wagered_cents}")
_assert("E: shortfall_cents == 0 (pool credit alone met the minimum)", result_e.shortfall_cents == 0, f"got {result_e.shortfall_cents}")
_assert("E: swept is False", result_e.swept is False)


# ── SCENARIO F: idempotency — sweeping twice does not double-post ───────────

print("\nScenario F: idempotency — sweeping the same team/week twice does not double-post")

tb_before_f = trial_balance()
champ_before_f = balance_of("championship")
with SessionLocal() as db:
    result_f_repeat = sweep_shortfall_for_team(t_b, league_b, 1, db)  # same team/week as Scenario B

_assert("F: already_run is True on the repeat call", result_f_repeat.already_run is True)
_assert("F: swept is False on the repeat call (no new posting)", result_f_repeat.swept is False)
_assert("F: repeat call returns the SAME shortfall figures as the original", result_f_repeat.shortfall_cents == 600 and result_f_repeat.covered_cents == 600)
_assert("F: championship balance unchanged by the repeat call", balance_of("championship") == champ_before_f, f"got {balance_of('championship')}")
_assert("F: trial_balance unchanged by the repeat call", trial_balance() == tb_before_f, f"before={tb_before_f} after={trial_balance()}")

with SessionLocal() as db:
    record_count = (
        db.query(ShortfallSweepRecord)
        .filter(ShortfallSweepRecord.league_id == league_b, ShortfallSweepRecord.team_id == t_b, ShortfallSweepRecord.week == 1)
        .count()
    )
_assert("F: exactly one ShortfallSweepRecord row exists for team_b/week1, not two", record_count == 1, f"got {record_count}")


# ── SCENARIO G: guard interaction — pre-split posting never trips InsufficientFundsError ──

print("\nScenario G: guard interaction (B2-6.2) — no InsufficientFundsError even when wallet can't fully cover")

league_g = _make_league("G")
t_g, w_g = _make_team(league_g, "G1")
m_g = _make_opponent_matchup(league_g, t_g, week=1)
_fund_ledger_wallet(t_g, 50)  # only $0.50 funded, shortfall will be $10.00

raised_g = False
try:
    with SessionLocal() as db:
        result_g = sweep_shortfall_for_team(t_g, league_g, 1, db)
except Exception as e:
    raised_g = True
    print(f"    unexpected exception: {e}")
_assert("G: no exception raised despite wallet covering only a tiny fraction of the shortfall", not raised_g)
if not raised_g:
    _assert("G: covered_cents bounded to the wallet's actual funded balance (50)", result_g.covered_cents == 50, f"got {result_g.covered_cents}")
    _assert("G: uncovered_cents makes up the rest (950)", result_g.uncovered_cents == 950, f"got {result_g.uncovered_cents}")


# ── SCENARIO H: sweep_shortfall_for_week() sweeps every team in the league ──

print("\nScenario H: sweep_shortfall_for_week() sweeps every team in one call")

league_h = _make_league("H")
t_h1, w_h1 = _make_team(league_h, "H1")
t_h2, w_h2 = _make_team(league_h, "H2")
_make_opponent_matchup(league_h, t_h1, week=1)
_make_opponent_matchup(league_h, t_h2, week=1)
_fund_ledger_wallet(t_h1, 100_000_00)
_fund_ledger_wallet(t_h2, 100_000_00)

with SessionLocal() as db:
    results_h = sweep_shortfall_for_week(league_h, 1, db)

# _make_team creates an opponent team too (via _make_opponent_matchup) that
# is NOT in the league's own team roster query result set for t_h1/t_h2
# (those opponents belong to league_h as well, since _make_opponent_matchup
# adds them to the same league_id) — so results_h covers every team in
# league_h, including the two synthetic opponents.
_assert("H: at least the two named teams were swept", {t_h1, t_h2}.issubset({r.team_id for r in results_h}))
_assert("H: both named teams show the full $10 shortfall (no bets, no pool)", all(r.shortfall_cents == 1000 for r in results_h if r.team_id in (t_h1, t_h2)))


# ── Explanation text sanity check ────────────────────────────────────────────

print("\nExplanation text: sweep_explanation_text() produces readable output for both cases")

_assert("no-shortfall explanation mentions 'no shortfall swept'", "no shortfall swept" in sweep_explanation_text(result_a))
_assert("swept explanation mentions the covered amount", "swept from your wallet" in sweep_explanation_text(result_b))
_assert("partially-covered explanation mentions the receivable", "outstanding balance" in sweep_explanation_text(result_c))


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
