"""
test_stake_precision_validation.py — FR-7.50 verification.

Proves the fix: sub-cent stakes are now REJECTED at entry (before storage,
before the MIN_BET check) at all three in-scope entry points —
issue_challenge(), counter_challenge(), and place_straight_bet() (the single
funnel for all four single-party routes) — via _dollars_to_cents(), now
promoted to ledger/ledger.py. Whole-cent stakes and the float-artifact case
($20.10 stored as 20.099999999999998) still pass. Check ordering
(whole-cents before MIN_BET) is proven with $4.99. The pool boundary is
unchanged, now routed through the moved function.

Fixtures (FR-7.50 Section 6):
  - 20.005 → raises at issue_challenge(), counter_challenge(), place_straight_bet()
  - 20.00  → accepted at all three
  - 20.10  → accepted at all three (float artifact must NOT be rejected —
             the case that proves the fix isn't over-broad)
  - 0.1 + 0.2 → raises (regression guard against a future computing caller)
  - 4.99   → reports the MIN_BET error, NOT a precision error (check ordering)
  - pool config: 10.005 still rejected via the moved function

Setup follows test_stake_precision_characterization.py verbatim (temp SQLite,
DATABASE_URL set before any db/schema import, script-style _assert + sys.exit
summary, ledger-seed funding, FUTURE_KO NflSchedule so the beef locks never
fire).
"""

import os
import sys
import tempfile

# ── Must set DATABASE_URL before any project import touches db/schema.py ──────
_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_stake_precision_validation.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime

from db.schema import (
    Base, engine, SessionLocal,
    Bet, League, Matchup, NflSchedule, Player, Roster, Team, Wallet,
)
from betting.bet_engine import place_straight_bet
from betting.exceptions import BetValidationError
from beefs.beef_engine import issue_challenge, counter_challenge
from betting.per_bet_lock import LOCK_SEASON
from config import CURRENT_SEASON as SEASON
from ledger.ledger import balance_of, trial_balance, create_ledger_table, post as ledger_post, _dollars_to_cents
import api.pool_routes as pool_routes

# ── Helpers (same style as test_stake_precision_characterization.py) ──────────

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _capture(fn):
    """Run fn(); return (exception_or_None, result_or_None)."""
    try:
        return None, fn()
    except Exception as e:  # noqa: BLE001 — we inspect type/message in-place
        return e, None


_PRECISION_MARKER = "whole number of cents"
_MINBET_MARKER = "below the minimum"


# ── DB bootstrap ──────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)
create_ledger_table()

# Real wall-clock this session is July 2026 — kickoff far in the future so the
# beef week/per-bet locks never fire (same reasoning as the char test).
FUTURE_KO = datetime(2026, 9, 14, 18, 0, 0)

_BEEF_WEEK = 5
_BET_WEEK = 6

with SessionLocal() as _db:
    league = League(season=SEASON, name="Stake Precision Validation League", projection_source="fantasypros")
    _db.add(league)
    _db.flush()

    # tA/tB — beef path (issue_challenge / counter_challenge), week 5
    tA = Team(league_id=league.id, team_name="Val TA", owner="OwnerA", email="va@t.com")
    tB = Team(league_id=league.id, team_name="Val TB", owner="OwnerB", email="vb@t.com")
    # tC/tD — single-party path (place_straight_bet), week 6
    tC = Team(league_id=league.id, team_name="Val TC", owner="OwnerC", email="vc@t.com")
    tD = Team(league_id=league.id, team_name="Val TD", owner="OwnerD", email="vd@t.com")
    _db.add_all([tA, tB, tC, tD])
    _db.flush()

    for team, nfl_team in ((tA, "KC"), (tB, "PHI"), (tC, "SF"), (tD, "DAL")):
        for i in range(9):
            p = Player(name=f"{team.team_name}-P{i}", position="WR", nfl_team=nfl_team)
            _db.add(p); _db.flush()
            _db.add(Roster(team_id=team.id, player_id=p.id))

    for team in (tA, tB, tC, tD):
        _db.add(Wallet(team_id=team.id, balance=1000.0))

    _db.add(Matchup(league_id=league.id, week=_BEEF_WEEK,
                     home_team_id=tA.id, away_team_id=tB.id,
                     home_score=0.0, away_score=0.0))
    _db.add(Matchup(league_id=league.id, week=_BET_WEEK,
                     home_team_id=tC.id, away_team_id=tD.id,
                     home_score=0.0, away_score=0.0))

    # Beef path consults the schedule (_nfl_lock_time) at issue and counter.
    _db.add(NflSchedule(season=LOCK_SEASON, week=_BEEF_WEEK,
                         home_team="KC", away_team="PHI",
                         kickoff_utc=FUTURE_KO))

    _db.commit()
    tA_id, tB_id, tC_id, tD_id = tA.id, tB.id, tC.id, tD.id
    bet_matchup_id = _db.query(Matchup).filter(Matchup.week == _BET_WEEK).first().id
    with SessionLocal() as _wdb:
        walletC_id = _wdb.query(Wallet).filter(Wallet.team_id == tC_id).first().id

# Seed ledger funds for the teams whose balances get READ (issue_challenge
# reads the challenger's; counter_challenge reads the challenged team's;
# place_straight_bet posts from the bettor's). Same Finding 5.1 gap as the
# other tests — nothing in prod funds wallet:{team} yet.
_SEED_CENTS = 100_000_00
for _team_id in (tA_id, tB_id, tC_id):
    ledger_post(
        [("world", -_SEED_CENTS), (f"wallet:{_team_id}", _SEED_CENTS)],
        door="buy_in_paid",
    )


# ── Entry point 1: issue_challenge() ──────────────────────────────────────────

print("\nissue_challenge(): sub-cent rejected, whole-cent accepted")

def _issue(amount):
    with SessionLocal() as db:
        return issue_challenge(tA_id, tB_id, week=_BEEF_WEEK, bet_type="straight", amount=amount, db=db)

exc, _ = _capture(lambda: _issue(20.005))
_assert("issue_challenge(20.005) raises",
        isinstance(exc, ValueError) and _PRECISION_MARKER in str(exc), f"got {exc!r}")

exc, out = _capture(lambda: _issue(20.00))
_assert("issue_challenge(20.00) accepted", exc is None and out is not None and out.challenge_id is not None, f"exc={exc!r}")

exc, out = _capture(lambda: _issue(20.10))
_assert("issue_challenge(20.10) accepted (float artifact 20.0999… NOT rejected)",
        exc is None and out is not None and out.challenge_id is not None, f"exc={exc!r}")


# ── Entry point 2: counter_challenge() ────────────────────────────────────────
# Each counter needs a fresh pending challenge (issued at a valid amount).

print("\ncounter_challenge(): sub-cent rejected, whole-cent accepted")

def _fresh_pending():
    with SessionLocal() as db:
        return issue_challenge(tA_id, tB_id, week=_BEEF_WEEK, bet_type="straight", amount=10.00, db=db).challenge_id

def _counter(cid, amount):
    with SessionLocal() as db:
        return counter_challenge(cid, amount, db)

cid_raise = _fresh_pending()
exc, _ = _capture(lambda: _counter(cid_raise, 20.005))
_assert("counter_challenge(20.005) raises",
        isinstance(exc, ValueError) and _PRECISION_MARKER in str(exc), f"got {exc!r}")

cid_ok = _fresh_pending()
exc, res = _capture(lambda: _counter(cid_ok, 20.00))
_assert("counter_challenge(20.00) accepted", exc is None and res is not None and res.countered_amount == 20.00, f"exc={exc!r} res={res!r}")

cid_art = _fresh_pending()
exc, res = _capture(lambda: _counter(cid_art, 20.10))
_assert("counter_challenge(20.10) accepted (float artifact NOT rejected)",
        exc is None and res is not None, f"exc={exc!r}")


# ── Entry point 3: place_straight_bet() (single-party funnel) ─────────────────

print("\nplace_straight_bet(): sub-cent rejected, whole-cent accepted")

def _bet(amount):
    with SessionLocal() as db:
        return place_straight_bet(bet_matchup_id, walletC_id, tC_id, amount, _BET_WEEK, db)

exc, _ = _capture(lambda: _bet(20.005))
_assert("place_straight_bet(20.005) raises",
        isinstance(exc, ValueError) and _PRECISION_MARKER in str(exc), f"got {exc!r}")

exc, res = _capture(lambda: _bet(20.00))
_assert("place_straight_bet(20.00) accepted", exc is None and res is not None and res.status == "pending", f"exc={exc!r}")
if res is not None:
    _assert("place_straight_bet(20.00) escrow == 2000", balance_of(f"escrow:{res.bet_id}") == 2000, f"got {balance_of(f'escrow:{res.bet_id}')}")

exc, res = _capture(lambda: _bet(20.10))
_assert("place_straight_bet(20.10) accepted (float artifact NOT rejected)", exc is None and res is not None, f"exc={exc!r}")
if res is not None:
    _assert("place_straight_bet(20.10) escrow == 2010 (round of the artifact is exact)",
            balance_of(f"escrow:{res.bet_id}") == 2010, f"got {balance_of(f'escrow:{res.bet_id}')}")


# ── Regression guard: a COMPUTING caller (0.1 + 0.2) is rejected ──────────────
# q4 confirms no live caller computes a stake by arithmetic today; this pins
# the rejection so a FUTURE refactor that introduces float arithmetic fails
# loudly instead of silently rounding. 0.1 + 0.2 == 0.30000000000000004, which
# does not round-trip through Decimal(str(...)). It is also below MIN_BET —
# so this doubly proves ordering: it must report the PRECISION error, never
# MIN_BET, because the whole-cents check runs first.

print("\nRegression guard: computing caller (0.1 + 0.2) rejected as precision, before MIN_BET")

exc, _ = _capture(lambda: _bet(0.1 + 0.2))
_assert("place_straight_bet(0.1 + 0.2) raises a PRECISION error, not MIN_BET",
        isinstance(exc, ValueError) and _PRECISION_MARKER in str(exc) and _MINBET_MARKER not in str(exc),
        f"got {exc!r}")


# ── Check ordering: $4.99 is a valid whole cent but below MIN_BET ─────────────
# 4.99 -> 499 cents, whole, so _dollars_to_cents() passes; then MIN_BET fires.
# Must report the minimum, NOT a precision error — proving whole-cents runs
# first and does not swallow a well-formed below-minimum request.

print("\nCheck ordering: $4.99 reports MIN_BET, not a precision error")

exc, _ = _capture(lambda: _bet(4.99))
_assert("place_straight_bet(4.99) reports MIN_BET, not precision",
        isinstance(exc, BetValidationError) and _MINBET_MARKER in str(exc) and _PRECISION_MARKER not in str(exc),
        f"got {exc!r}")


# ── Pool boundary unchanged, via the moved function ───────────────────────────
# create_pool_config still rejects 10.005 exactly as before. Prove it routes
# through the SAME promoted function, and that the function's behavior is intact.

print("\nPool boundary: routed through the moved _dollars_to_cents(), 10.005 still rejected")

_assert("pool_routes uses the promoted ledger._dollars_to_cents (same object)",
        pool_routes._dollars_to_cents is _dollars_to_cents)

exc, _ = _capture(lambda: pool_routes._dollars_to_cents(10.005))
_assert("pool path: _dollars_to_cents(10.005) still rejected",
        isinstance(exc, ValueError) and _PRECISION_MARKER in str(exc), f"got {exc!r}")

exc, val = _capture(lambda: pool_routes._dollars_to_cents(50.00))
_assert("pool path: _dollars_to_cents(50.00) == 5000 (valid behavior intact)", exc is None and val == 5000, f"exc={exc!r} val={val!r}")


# ── Integrity ─────────────────────────────────────────────────────────────────

_assert("trial_balance still closes to 0", trial_balance() == 0, f"got {trial_balance()}")


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED (FR-7.50 fix verified)")
