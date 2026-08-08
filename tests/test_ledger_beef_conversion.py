"""
test_ledger_beef_conversion.py — Verifies beefs/beef_engine.py's
_place_beef_side() posts through the ledger (Session L3 conversion)
instead of the old direct wallet.balance mutation.

Two scenarios, each with its own small fixture (kept separate from
test_beef_starters.py's own tightly-tuned schedule/lock fixture, to
avoid perturbing it):

  I.  A normal accepted beef — both sides' wallet:{team_id} ledger
      balance reflects the debit, both escrow:{bet_id} accounts hold
      the staked amount, and trial_balance() still closes to zero.

  II. Atomicity proof — if respond_to_challenge() fails during its own
      final commit (simulated here by making that commit raise), the
      ledger postings made earlier in the SAME transaction (via
      _place_beef_side()'s session=db) must not be persisted either,
      since they share one session/transaction with everything else
      respond_to_challenge() writes.

Uses a temp SQLite DB so prod is never touched. DATABASE_URL is set
before any project import touches db/schema.py, matching the pattern
established in test_beef_starters.py.
"""

import os
import sys
import tempfile

# ── Must set DATABASE_URL before any project import touches db/schema.py ──────
_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_ledger_beef_conversion.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

from db.schema import (
    Base, engine, SessionLocal,
    Bet, League, Matchup, NflSchedule, Player, Roster, Team, Wallet,
)
from beefs.beef_engine import issue_challenge, respond_to_challenge
from betting.per_bet_lock import LOCK_SEASON
from config import CURRENT_SEASON as SEASON
from ledger.ledger import balance_of, trial_balance, create_ledger_table, post as ledger_post

# ── Helpers (same style as test_beef_starters.py) ─────────────────────────────

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

# Real wall-clock during this session is July 2026 — kickoffs below are set
# far enough in the future that neither the week-level nor per-bet lock in
# respond_to_challenge ever fires, same reasoning as test_beef_starters.py.
FUTURE_KO = datetime(2026, 9, 14, 18, 0, 0)

with SessionLocal() as _db:
    league = League(season=SEASON, name="Ledger Conversion Test League", projection_source="fantasypros")
    _db.add(league)
    _db.flush()

    # t1/t2 — Scenario I (successful accept)
    t1 = Team(league_id=league.id, team_name="Ledger T1", owner="Owner1", email="o1@t.com")
    t2 = Team(league_id=league.id, team_name="Ledger T2", owner="Owner2", email="o2@t.com")
    # t3/t4 — Scenario II (simulated commit failure)
    t3 = Team(league_id=league.id, team_name="Ledger T3", owner="Owner3", email="o3@t.com")
    t4 = Team(league_id=league.id, team_name="Ledger T4", owner="Owner4", email="o4@t.com")
    _db.add_all([t1, t2, t3, t4])
    _db.flush()

    for team, nfl_team in ((t1, "KC"), (t2, "PHI"), (t3, "SF"), (t4, "DAL")):
        for i in range(9):
            p = Player(name=f"{team.team_name}-P{i}", position="WR", nfl_team=nfl_team)
            _db.add(p); _db.flush()
            _db.add(Roster(team_id=team.id, player_id=p.id))

    for team in (t1, t2, t3, t4):
        _db.add(Wallet(team_id=team.id, balance=1000.0))

    _db.add(Matchup(league_id=league.id, week=1,
                     home_team_id=t1.id, away_team_id=t2.id,
                     home_score=0.0, away_score=0.0))
    _db.add(Matchup(league_id=league.id, week=2,
                     home_team_id=t3.id, away_team_id=t4.id,
                     home_score=0.0, away_score=0.0))

    _db.add(NflSchedule(season=LOCK_SEASON, week=1,
                         home_team="KC", away_team="PHI",
                         kickoff_utc=FUTURE_KO))
    _db.add(NflSchedule(season=LOCK_SEASON, week=2,
                         home_team="SF", away_team="DAL",
                         kickoff_utc=FUTURE_KO))

    _db.commit()
    t1_id, t2_id, t3_id, t4_id = t1.id, t2.id, t3.id, t4.id

# IMPORTANT — flagged, not a fixture-only workaround for a test quirk:
# No code path anywhere in this repo currently posts a buy_in_paid/buy_in_tab
# entry crediting wallet:{team_id} in the ledger — Wallet rows are created
# directly (as above) and the retired payment module only flipped a
# User.buy_in_paid flag, never touching the ledger. Without a Door 1 posting
# like this, _place_beef_side()'s new ledger_post() call would raise
# InsufficientFundsError for every team, every time, since every wallet:*
# ledger account starts and stays at 0 cents. This posting simulates funding
# that nothing in production actually performs yet, purely so the CONVERSION
# itself (does _place_beef_side debit/escrow correctly, atomically) can be
# verified in isolation. See the final report: this is a real, separate gap,
# not something this test papering over it makes any less real in prod.
_SEED_CENTS = 100_000_00
for _team_id in (t1_id, t2_id, t3_id, t4_id):
    ledger_post(
        [("world", -_SEED_CENTS), (f"wallet:{_team_id}", _SEED_CENTS)],
        door="buy_in_paid",
    )


# ── SCENARIO I: successful accept — ledger balances reflect both debits ───────

print("\nScenario I: accepted beef posts both debits through the ledger")
with SessionLocal() as db:
    out = issue_challenge(t1_id, t2_id, week=1, bet_type="straight", amount=10.0, db=db)
    cid1 = out.challenge_id

    result = respond_to_challenge(cid1, accept=True, db=db)
    _assert("accept succeeded, both bet ids populated",
            result.challenger_bet_id is not None and result.challenged_bet_id is not None)

    challenger_bet_id = result.challenger_bet_id
    challenged_bet_id = result.challenged_bet_id

_assert("wallet:t1 ledger balance debited $10.00", balance_of(f"wallet:{t1_id}") == _SEED_CENTS - 1000, f"got {balance_of(f'wallet:{t1_id}')}")
_assert("wallet:t2 ledger balance debited $10.00", balance_of(f"wallet:{t2_id}") == _SEED_CENTS - 1000, f"got {balance_of(f'wallet:{t2_id}')}")
_assert("escrow:<challenger_bet_id> holds $10.00", balance_of(f"escrow:{challenger_bet_id}") == 1000, f"got {balance_of(f'escrow:{challenger_bet_id}')}")
_assert("escrow:<challenged_bet_id> holds $10.00", balance_of(f"escrow:{challenged_bet_id}") == 1000, f"got {balance_of(f'escrow:{challenged_bet_id}')}")
_assert("trial_balance still closes to 0 after Scenario I", trial_balance() == 0, f"got {trial_balance()}")

# Confirms the flagged transition-period gap: wallet.balance itself (the ORM
# column api/main.py's /faab/wallet/{team_id} route reads) is NO LONGER
# mutated by _place_beef_side() after this conversion — only the ledger is.
# This is expected during the transition (Finding 2 migrates that route),
# not a bug in this pass, but worth proving explicitly rather than assuming.
with SessionLocal() as db:
    w1 = db.query(Wallet).filter(Wallet.team_id == t1_id).first()
    _assert("wallet.balance (ORM column) unchanged — still $1000.00, NOT decremented by this path",
            w1.balance == 1000.0, f"got {w1.balance}")


# ── SCENARIO II: simulated failure between the ledger posts and the final ─────
# commit — proves the ledger posts do NOT survive if respond_to_challenge's
# own commit never succeeds, since they share one session/transaction.

print("\nScenario II: simulated commit failure — ledger posts must not persist")
tb_before_scenario_ii = trial_balance()

with SessionLocal() as db:
    out2 = issue_challenge(t3_id, t4_id, week=2, bet_type="straight", amount=15.0, db=db)
    cid2 = out2.challenge_id

    # Force respond_to_challenge's own final db.commit() to fail. Everything
    # up to that point — both _place_beef_side() calls (ledger posts + Bet/
    # Transaction rows) and the challenge.status="accepted" assignment — has
    # already been added/flushed into this SAME uncommitted transaction, so
    # this reproduces "a failure occurs after the ledger posts but before a
    # successful commit" without needing to edit beef_engine.py itself.
    def _raise_on_commit():
        raise RuntimeError("Simulated failure — commit never succeeds")
    db.commit = _raise_on_commit

    raised = False
    try:
        respond_to_challenge(cid2, accept=True, db=db)
    except RuntimeError:
        raised = True
    _assert("respond_to_challenge propagated the simulated commit failure", raised)
    # The session is left with a failed/uncommitted transaction; closing the
    # `with` block below rolls it back (SQLAlchemy's own session.close()
    # behavior for an unflushed/uncommitted transaction on exit).

with SessionLocal() as _check_db:
    bet_count_after_failure = _check_db.query(Bet).filter(Bet.beef_challenge_id == cid2).count()
_assert("no Bet rows exist for the failed-commit challenge", bet_count_after_failure == 0, f"got {bet_count_after_failure}")
_assert("wallet:t3 ledger balance unaffected by the rolled-back posting", balance_of(f"wallet:{t3_id}") == _SEED_CENTS, f"got {balance_of(f'wallet:{t3_id}')}")
_assert("wallet:t4 ledger balance unaffected by the rolled-back posting", balance_of(f"wallet:{t4_id}") == _SEED_CENTS, f"got {balance_of(f'wallet:{t4_id}')}")
_assert("trial_balance unchanged after the rolled-back posting", trial_balance() == tb_before_scenario_ii, f"before={tb_before_scenario_ii} after={trial_balance()}")


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
