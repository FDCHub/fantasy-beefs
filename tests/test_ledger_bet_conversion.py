"""
test_ledger_bet_conversion.py — Verifies betting/bet_engine.py's
_place_bet() posts through the ledger (Session L3 conversion) instead
of the old direct wallet.balance mutation.

No prior test coverage existed for bet_engine.py at all (confirmed via
this session's recon) — these are the only tests for this file, not a
supplement to something established.

Three scenarios, each with its own small fixture:

  I.   A normal successful bet (place_straight_bet()) posts the debit
       and escrow credit correctly through the ledger, and
       trial_balance() still closes to zero.

  II.  validate_bet_amount()'s existing MIN_BET/MAX_BET_PCT guard still
       fires and blocks placement BEFORE any ledger posting is
       attempted — the old guard and the new ledger guard don't
       conflict or double-fire.

  III. Atomicity proof. The original plan for this site was
       ledger.post(session=None) — its own, independent commit — since
       recon showed _place_bet() commits its own transaction and
       nothing else needs to share it. Running Scenario I against that
       plan surfaced a real, unconditional failure (not just a rare
       edge case): db.flush() above already opens an uncommitted write
       transaction on `db`; a second, separate SQLite connection
       (session=None) can't get a write lock while that's open, so it
       deadlocked with "database is locked" on every call. Switched to
       session=db instead — the ledger write now joins _place_bet()'s
       own existing transaction. This scenario proves that fix holds:
       if _place_bet()'s own final commit fails, the ledger posting
       (added to the SAME session, never separately committed) rolls
       back with everything else — no orphaned escrow entry, no bet-less
       debit.

Uses a temp SQLite DB so prod is never touched. DATABASE_URL is set
before any project import touches db/schema.py, matching the pattern
established in test_beef_starters.py / test_ledger_beef_conversion.py.
"""

import os
import sys
import tempfile

# ── Must set DATABASE_URL before any project import touches db/schema.py ──────
_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_ledger_bet_conversion.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.schema import (
    Base, engine, SessionLocal,
    Bet, League, Matchup, Player, Roster, Team, Wallet,
)
from betting.bet_engine import place_straight_bet
from betting.exceptions import BetValidationError
from config import CURRENT_SEASON as SEASON
from ledger.ledger import balance_of, trial_balance, create_ledger_table, post as ledger_post, LedgerEntry

# ── Helpers (same style as test_beef_starters.py / test_ledger_beef_conversion.py) ─

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

with SessionLocal() as _db:
    league = League(season=SEASON, name="Ledger Bet Conversion Test League", projection_source="fantasypros")
    _db.add(league)
    _db.flush()

    # t1/t2 — Scenario I (successful bet placement)
    t1 = Team(league_id=league.id, team_name="Bet T1", owner="Owner1", email="b1@t.com")
    t2 = Team(league_id=league.id, team_name="Bet T2", owner="Owner2", email="b2@t.com")
    # t3/t4 — Scenario II (validate_bet_amount guard, both sub-cases)
    t3 = Team(league_id=league.id, team_name="Bet T3", owner="Owner3", email="b3@t.com")
    t4 = Team(league_id=league.id, team_name="Bet T4", owner="Owner4", email="b4@t.com")
    # t5/t6 — Scenario III (ordering-concern reproduction)
    t5 = Team(league_id=league.id, team_name="Bet T5", owner="Owner5", email="b5@t.com")
    t6 = Team(league_id=league.id, team_name="Bet T6", owner="Owner6", email="b6@t.com")
    _db.add_all([t1, t2, t3, t4, t5, t6])
    _db.flush()

    for team, nfl_team in ((t1, "KC"), (t2, "PHI"), (t3, "SF"), (t4, "DAL"), (t5, "NO"), (t6, "GB")):
        for i in range(9):
            p = Player(name=f"{team.team_name}-P{i}", position="WR", nfl_team=nfl_team)
            _db.add(p); _db.flush()
            _db.add(Roster(team_id=team.id, player_id=p.id))

    for team in (t1, t2, t3, t4, t5, t6):
        _db.add(Wallet(team_id=team.id, balance=1000.0))

    _db.add(Matchup(league_id=league.id, week=1,
                     home_team_id=t1.id, away_team_id=t2.id,
                     home_score=0.0, away_score=0.0))
    _db.add(Matchup(league_id=league.id, week=2,
                     home_team_id=t3.id, away_team_id=t4.id,
                     home_score=0.0, away_score=0.0))
    _db.add(Matchup(league_id=league.id, week=3,
                     home_team_id=t5.id, away_team_id=t6.id,
                     home_score=0.0, away_score=0.0))

    _db.commit()
    t1_id, t2_id, t3_id, t4_id, t5_id, t6_id = t1.id, t2.id, t3.id, t4.id, t5.id, t6.id
    matchup1_id = _db.query(Matchup).filter(Matchup.week == 1).first().id
    matchup2_id = _db.query(Matchup).filter(Matchup.week == 2).first().id
    matchup3_id = _db.query(Matchup).filter(Matchup.week == 3).first().id

    with SessionLocal() as _wdb:
        wallet1_id = _wdb.query(Wallet).filter(Wallet.team_id == t1_id).first().id
        wallet3_id = _wdb.query(Wallet).filter(Wallet.team_id == t3_id).first().id
        wallet5_id = _wdb.query(Wallet).filter(Wallet.team_id == t5_id).first().id

# Same Finding 5.1 gap as Site 2 (test_ledger_beef_conversion.py): no code
# path anywhere in this repo funds a team's wallet:{team_id} ledger account
# yet. Seed t1 and t5 (the two teams that successfully place a bet below) so
# the CONVERSION itself can be verified — this does not fix the real,
# separate production gap. t3 is deliberately left UNFUNDED (0 cents) — see
# Scenario II, where that's used to prove the ledger is never even reached.
_SEED_CENTS = 100_000_00
for _team_id in (t1_id, t5_id):
    ledger_post(
        [("world", -_SEED_CENTS), (f"wallet:{_team_id}", _SEED_CENTS)],
        door="buy_in_paid",
    )


# ── SCENARIO I: successful bet — ledger debit + escrow credit ─────────────────

print("\nScenario I: place_straight_bet() posts the debit and escrow credit through the ledger")
with SessionLocal() as db:
    result = place_straight_bet(matchup1_id, wallet1_id, t1_id, 10.0, 1, db)

_assert("bet placed, pending status", result.status == "pending")
_assert("wallet:t1 ledger balance debited $10.00", balance_of(f"wallet:{t1_id}") == _SEED_CENTS - 1000, f"got {balance_of(f'wallet:{t1_id}')}")
_assert("escrow:<bet_id> holds $10.00", balance_of(f"escrow:{result.bet_id}") == 1000, f"got {balance_of(f'escrow:{result.bet_id}')}")
_assert("trial_balance still closes to 0 after Scenario I", trial_balance() == 0, f"got {trial_balance()}")

with SessionLocal() as db:
    w1 = db.query(Wallet).filter(Wallet.team_id == t1_id).first()
    _assert("wallet.balance (ORM column) unchanged — still $1000.00, NOT decremented by this path",
            w1.balance == 1000.0, f"got {w1.balance}")


# ── SCENARIO II: validate_bet_amount()'s guard fires before any ledger post ───
# t3's ledger wallet is deliberately left unfunded (0 cents) — if the ledger
# were reached at all for these attempts, InsufficientFundsError would fire
# instead of BetValidationError, or the balance would move off 0. Neither
# should happen: validate_bet_amount() must reject first, every time.

print("\nScenario II: validate_bet_amount() guard blocks placement before the ledger is ever touched")

bet_count_before = None
with SessionLocal() as db:
    bet_count_before = db.query(Bet).filter(Bet.matchup_id == matchup2_id).count()

# II.a — below MIN_BET ($5.00)
raised_min = False
try:
    with SessionLocal() as db:
        place_straight_bet(matchup2_id, wallet3_id, t3_id, 1.0, 2, db)
except BetValidationError:
    raised_min = True
_assert("II.a: BetValidationError raised for amount below MIN_BET", raised_min)

# II.b — above MAX_BET_PCT (20% of $1000.00 = $200.00)
raised_max = False
try:
    with SessionLocal() as db:
        place_straight_bet(matchup2_id, wallet3_id, t3_id, 250.0, 2, db)
except BetValidationError:
    raised_max = True
_assert("II.b: BetValidationError raised for amount above MAX_BET_PCT", raised_max)

with SessionLocal() as db:
    bet_count_after = db.query(Bet).filter(Bet.matchup_id == matchup2_id).count()
_assert("no Bet rows created by either rejected attempt", bet_count_after == bet_count_before, f"before={bet_count_before} after={bet_count_after}")
_assert("wallet:t3 ledger balance still 0 — the ledger was never reached", balance_of(f"wallet:{t3_id}") == 0, f"got {balance_of(f'wallet:{t3_id}')}")
_assert("trial_balance still closes to 0 after Scenario II", trial_balance() == 0, f"got {trial_balance()}")


# ── SCENARIO III: atomicity proof (session=db, post-deadlock-fix) ─────────────
# Force _place_bet()'s own final db.commit() to fail. Since the ledger
# posting now shares this SAME session (session=db, not session=None), it was
# never separately committed — it should roll back right along with the
# Bet/Transaction rows when the session closes on the exception. Proves the
# fix actually holds, not just that it compiles.

print("\nScenario III: atomicity proof — a failed final commit rolls back the ledger post too, not just Bet/Transaction")

tb_before_scenario_iii = trial_balance()

with SessionLocal() as db:
    def _raise_on_commit():
        raise RuntimeError("Simulated failure in _place_bet's own final commit")
    db.commit = _raise_on_commit

    raised_final_commit = False
    try:
        place_straight_bet(matchup3_id, wallet5_id, t5_id, 20.0, 3, db)
    except RuntimeError:
        raised_final_commit = True
_assert("place_straight_bet propagated the simulated final-commit failure", raised_final_commit)

with SessionLocal() as db:
    bet_count_t5 = db.query(Bet).filter(Bet.matchup_id == matchup3_id).count()
_assert("no Bet row exists for the failed-commit attempt", bet_count_t5 == 0, f"got {bet_count_t5}")
_assert(
    "wallet:t5 ledger balance UNCHANGED — the ledger post rolled back with everything else, no orphan",
    balance_of(f"wallet:{t5_id}") == _SEED_CENTS,
    f"got {balance_of(f'wallet:{t5_id}')}",
)
with SessionLocal() as _le_db:
    stray_entry = (
        _le_db.query(LedgerEntry)
        .filter(LedgerEntry.door == "wager_placed", LedgerEntry.account.like("escrow:%"))
        .filter(LedgerEntry.amount_cents == 2000)
        .first()
    )
_assert("no stray escrow entry for this attempt exists anywhere in the ledger", stray_entry is None)
_assert("trial_balance unchanged after the rolled-back posting", trial_balance() == tb_before_scenario_iii, f"before={tb_before_scenario_iii} after={trial_balance()}")


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
