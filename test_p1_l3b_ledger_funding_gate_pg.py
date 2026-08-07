"""
test_p1_l3b_ledger_funding_gate_pg.py — P1-L3B targeted suite.

CONTROLLING RULE (Foundation Correction Plan, Section 2):

    "Every funding and withdrawal gate reads the integer-cent ledger balance.
     No money decision consults a float."

    Test obligation: "Gate correctness at the single-cent boundary. A fixture
    where the float balance and the ledger-cent balance disagree, so a
    float-reading gate and a ledger-reading gate return different verdicts.
    That divergence is the whole test."

Every divergence fixture below is built so that Wallet.balance (the float
compatibility mirror) and the wallet:{team_id} ledger balance DELIBERATELY
DISAGREE, and so that the pre-correction float-reading implementation would
return the OPPOSITE verdict from the corrected ledger-reading one. Each such
assertion therefore has teeth: it fails against HEAD~ and passes only against
the corrected gate.

Two live P1-L3B violations are covered — the complete live inventory:

  1. beefs/beef_engine.py  _place_beef_side()  — legacy Beef accept path,
     reachable via /beef/respond.
  2. wallet/wallet_manager.py validate_bet_amount(), fed from
     betting/bet_engine.py _place_bet() — legacy single-party wagering path,
     reachable via /bets/*.

SCOPE FENCE. This suite proves the correction is MINIMAL as well as correct:
L3B-11 and L3B-12 assert that no real-money/processor surface and no Package 2B
Group 2 funding-primitive surface was introduced by these three edits.

OUT OF SCOPE, deliberately untouched and NOT asserted here: the P1-L7 Wallet-row
mutex decision, Package 2B Group 2 funding primitives, legacy route retirement,
Weekly Minimum, and general float cleanup (display mirrors, settlement payout
writes, the faab bet_frozen flag).

Runs on real PostgreSQL — ledger.post()'s funded-account guard and the
in-session balance reads are the behaviour under test, so the disposable
Postgres harness is used rather than SQLite.

    $env:TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5433/fantasy_test"
    python test_p1_l3b_ledger_funding_gate_pg.py
"""

from __future__ import annotations

import ast
import io
import os
import sys
import tokenize
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST — db.schema binds its engine at import time.
from test_support_postgres import setup_postgres_test_db

tdb = setup_postgres_test_db()

from db.schema import Bet, League, Matchup, Player, Roster, Team, Wallet  # noqa: E402
from beefs.beef_engine import _place_beef_side, _to_cents  # noqa: E402
from betting.bet_engine import place_straight_bet  # noqa: E402
from betting.exceptions import BetValidationError  # noqa: E402
from wallet.wallet_manager import (  # noqa: E402
    MAX_BET_PCT, MIN_BET, _MAX_BET_BPS, validate_bet_amount,
)
from ledger.ledger import (  # noqa: E402
    InsufficientFundsError, balance_of, post as ledger_post, trial_balance,
)
from config import CURRENT_SEASON as SEASON  # noqa: E402

_ROOT = Path(os.path.dirname(os.path.abspath(__file__)))

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _fn_node(path: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((_ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path}")


def _code_tokens(path: str) -> set[str]:
    """Identifier/keyword tokens of a source file with COMMENT and STRING
    tokens stripped — modules in this tree document their own prohibitions in
    prose, so a raw text scan would match the documentation rather than the
    code. Positive-controlled below."""
    src = (_ROOT / path).read_text(encoding="utf-8")
    out: set[str] = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        if tok.type == tokenize.NAME:
            out.add(tok.string)
        elif getattr(tokenize, "FSTRING_MIDDLE", None) is not None and tok.type in (
            tokenize.FSTRING_START, tokenize.FSTRING_MIDDLE, tokenize.FSTRING_END,
        ):
            continue
    return out


_CHANGED_FILES = (
    "beefs/beef_engine.py",
    "betting/bet_engine.py",
    "wallet/wallet_manager.py",
)


# ── Fixture ───────────────────────────────────────────────────────────────────
# Every team below gets a float Wallet.balance that DISAGREES with its ledger
# wallet:{team_id} balance. The mirror is never synchronised on purpose.

tdb.reset()

_MIRROR_HIGH = 100_000.00     # float mirror says the team is rich
_MIRROR_LOW  = 0.00           # float mirror says the team is broke

with tdb.SessionLocal() as _db:
    _league = League(season=SEASON, name="P1-L3B Gate League", projection_source="fantasypros")
    _db.add(_league)
    _db.flush()

    #                          mirror         seeded ledger cents
    _SPEC = {
        "beef_hi_lo":   (_MIRROR_HIGH,        1_00),      # L3B-2  float HIGH / ledger LOW
        "beef_lo_ok":   (_MIRROR_LOW,     5_000_00),      # L3B-3  float LOW  / ledger SUFFICIENT
        "beef_exact":   (_MIRROR_LOW,        50_00),      # L3B-7  ledger == stake exactly
        "beef_short1":  (_MIRROR_HIGH,       49_99),      # L3B-7  ledger one cent short
        "bet_hi_lo":    (_MIRROR_HIGH,        1_00),      # L3B-5  float HIGH / ledger LOW
        "bet_lo_ok":    (_MIRROR_LOW,       500_00),      # L3B-6  float LOW  / ledger SUFFICIENT
        "bet_opp":      (_MIRROR_HIGH,      500_00),      # opponent, unused for funding
        "guard":        (_MIRROR_HIGH,       10_00),      # L3B-9  final ledger defense
    }

    _teams: dict[str, Team] = {}
    for _i, (_key, (_mirror, _cents)) in enumerate(_SPEC.items()):
        _t = Team(league_id=_league.id, team_name=f"L3B {_key}", owner=f"O{_i}", email=f"l3b{_i}@t.com")
        _db.add(_t)
        _db.flush()
        _teams[_key] = _t
        for _j in range(9):
            _p = Player(name=f"{_key}-P{_j}", position="WR", nfl_team="KC")
            _db.add(_p)
            _db.flush()
            _db.add(Roster(team_id=_t.id, player_id=_p.id))
        _db.add(Wallet(team_id=_t.id, balance=_mirror))

    _db.flush()
    # One matchup per Beef-side team (record-keeping only) plus the ordinary-bet matchups.
    _db.add(Matchup(league_id=_league.id, week=1,
                    home_team_id=_teams["beef_hi_lo"].id, away_team_id=_teams["beef_lo_ok"].id,
                    home_score=0.0, away_score=0.0))
    _db.add(Matchup(league_id=_league.id, week=2,
                    home_team_id=_teams["beef_exact"].id, away_team_id=_teams["beef_short1"].id,
                    home_score=0.0, away_score=0.0))
    _db.add(Matchup(league_id=_league.id, week=3,
                    home_team_id=_teams["bet_hi_lo"].id, away_team_id=_teams["bet_opp"].id,
                    home_score=0.0, away_score=0.0))
    _db.add(Matchup(league_id=_league.id, week=4,
                    home_team_id=_teams["bet_lo_ok"].id, away_team_id=_teams["bet_opp"].id,
                    home_score=0.0, away_score=0.0))
    _db.commit()

    TID = {k: t.id for k, t in _teams.items()}
    WID = {k: _db.query(Wallet).filter(Wallet.team_id == t.id).first().id for k, t in _teams.items()}
    MU = {m.week: m.id for m in _db.query(Matchup).all()}

for _key, (_mirror, _cents) in _SPEC.items():
    if _cents:
        ledger_post([("world", -_cents), (f"wallet:{TID[_key]}", _cents)], door="buy_in_paid")

print("\nFixture: every wallet's float mirror deliberately disagrees with its ledger balance")
with tdb.SessionLocal() as _db:
    _diverge = all(
        abs(_db.query(Wallet).filter(Wallet.team_id == TID[k]).first().balance * 100
            - balance_of(f"wallet:{TID[k]}")) > 0
        for k in _SPEC
    )
_assert("fixture: float mirror != ledger cents for every team in this suite", _diverge)


# ── L3B-1 — _place_beef_side makes no Wallet.balance capacity decision ────────

print("\nL3B-1: _place_beef_side contains no Wallet.balance capacity decision")

_beef_fn = _fn_node("beefs/beef_engine.py", "_place_beef_side")
_beef_balance_reads = [
    n for n in ast.walk(_beef_fn)
    if isinstance(n, ast.Attribute) and n.attr == "balance"
]
_assert("L3B-1: zero `.balance` attribute accesses inside _place_beef_side",
        not _beef_balance_reads,
        f"found {len(_beef_balance_reads)}")

_beef_calls = {
    n.func.id for n in ast.walk(_beef_fn)
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
}
_assert("L3B-1: _place_beef_side calls _balance_of_in_session (authoritative ledger read)",
        "_balance_of_in_session" in _beef_calls)
_assert("L3B-1: _place_beef_side still calls _to_cents — same conversion as the posting below",
        "_to_cents" in _beef_calls)

# Positive control: the detector above must actually fire on a float-mirror read.
_control = ast.parse("def f(wallet, amount):\n    if wallet.balance < amount:\n        raise ValueError()\n")
_control_fn = _control.body[0]
_assert("L3B-1 positive control: the detector DOES flag `wallet.balance` when present",
        any(isinstance(n, ast.Attribute) and n.attr == "balance" for n in ast.walk(_control_fn)))


# ── L3B-2 — Beef: float mirror HIGH, ledger LOW → refuse ─────────────────────
# Pre-correction, `wallet.balance < amount` read $100,000.00 and ALLOWED this.

print("\nL3B-2: Beef — float mirror HIGH ($100,000.00), ledger LOW ($1.00) → refuse")

_l3b2_raised = False
_l3b2_msg = ""
with tdb.SessionLocal() as db:
    _w = db.query(Wallet).filter(Wallet.team_id == TID["beef_hi_lo"]).first()
    _mirror_seen = _w.balance
    try:
        _place_beef_side(
            db, _w, 50.00, "straight", MU[1], TID["beef_hi_lo"], None, None, None,
            "L3B-2 divergence probe", 1.909, beef_challenge_id=None,
        )
    except ValueError as exc:
        _l3b2_raised = True
        _l3b2_msg = str(exc)
    db.rollback()

_assert("L3B-2: float mirror really did say the team could afford it",
        _mirror_seen >= 50.00, f"mirror ${_mirror_seen:.2f}")
_assert("L3B-2: funding REFUSED on the ledger balance, not the mirror", _l3b2_raised)
_assert("L3B-2: refusal message reports the LEDGER balance ($1.00), not the mirror",
        "$1.00 <" in _l3b2_msg and "100000" not in _l3b2_msg.replace(",", ""),
        _l3b2_msg)
_l3b2_after = balance_of(f"wallet:{TID['beef_hi_lo']}")
_assert("L3B-2: no ledger movement — the gate refused before any posting",
        _l3b2_after == 1_00, f"got {_l3b2_after}")


# ── L3B-3 — Beef: float mirror LOW, ledger SUFFICIENT → do NOT falsely refuse ─
# Pre-correction, `wallet.balance < amount` read $0.00 and REFUSED this.

print("\nL3B-3: Beef — float mirror LOW ($0.00), ledger SUFFICIENT ($5,000.00) → funded")

_l3b3_err = None
_l3b3_bet_id = None
with tdb.SessionLocal() as db:
    _w = db.query(Wallet).filter(Wallet.team_id == TID["beef_lo_ok"]).first()
    _mirror_seen = _w.balance
    try:
        _bet = _place_beef_side(
            db, _w, 50.00, "straight", MU[1], TID["beef_lo_ok"], None, None, None,
            "L3B-3 divergence probe", 1.909, beef_challenge_id=None,
        )
        db.commit()
        _l3b3_bet_id = _bet.id
    except Exception as exc:      # noqa: BLE001 — any refusal is the failure mode under test
        _l3b3_err = exc
        db.rollback()

_assert("L3B-3: float mirror really did say the team was broke",
        _mirror_seen < 50.00, f"mirror ${_mirror_seen:.2f}")
_assert("L3B-3: NOT falsely refused — the ledger, not the mirror, decided",
        _l3b3_err is None, repr(_l3b3_err))
_assert("L3B-3: Bet row written", _l3b3_bet_id is not None)
_l3b3_after = balance_of(f"wallet:{TID['beef_lo_ok']}")
_assert("L3B-3: ledger debited exactly 5000 cents",
        _l3b3_after == 5_000_00 - 50_00, f"got {_l3b3_after}")
_assert("L3B-3: escrow holds exactly 5000 cents",
        _l3b3_bet_id is not None and balance_of(f"escrow:{_l3b3_bet_id}") == 50_00)
with tdb.SessionLocal() as db:
    _post_mirror = db.query(Wallet).filter(Wallet.team_id == TID["beef_lo_ok"]).first().balance
_assert("L3B-3: Wallet.balance mirror untouched by this correction",
        _post_mirror == _MIRROR_LOW, f"got {_post_mirror}")


# ── L3B-4 — ordinary Bet funding makes no Wallet.balance capacity decision ────

print("\nL3B-4: ordinary Bet funding contains no Wallet.balance capacity decision")

_pb_fn = _fn_node("betting/bet_engine.py", "_place_bet")
_pb_balance_reads = [
    n for n in ast.walk(_pb_fn) if isinstance(n, ast.Attribute) and n.attr == "balance"
]
_assert("L3B-4: zero `.balance` attribute accesses inside _place_bet",
        not _pb_balance_reads, f"found {len(_pb_balance_reads)}")

_vba_call = next(
    (n for n in ast.walk(_pb_fn)
     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
     and n.func.id == "validate_bet_amount"),
    None,
)
_assert("L3B-4: _place_bet still calls validate_bet_amount", _vba_call is not None)
_assert("L3B-4: its capacity argument is a _balance_of_in_session(...) call",
        _vba_call is not None and len(_vba_call.args) == 2
        and isinstance(_vba_call.args[1], ast.Call)
        and isinstance(_vba_call.args[1].func, ast.Name)
        and _vba_call.args[1].func.id == "_balance_of_in_session")

_vba_fn = _fn_node("wallet/wallet_manager.py", "validate_bet_amount")
_vba_params = [a.arg for a in _vba_fn.args.args]
_assert("L3B-4: validate_bet_amount's balance parameter is named for integer cents",
        _vba_params[1] == "wallet_balance_cents", str(_vba_params))
_assert("L3B-4: zero `.balance` attribute accesses inside validate_bet_amount",
        not [n for n in ast.walk(_vba_fn) if isinstance(n, ast.Attribute) and n.attr == "balance"])

# Behavioural half: a float balance is REFUSED, never coerced. This is what makes
# "no binary-float wallet state drives the result" structural rather than stylistic.
_float_refused = False
try:
    validate_bet_amount(10.00, 100_000.00)
except TypeError:
    _float_refused = True
_assert("L3B-4: a float balance argument is refused outright (not silently coerced)",
        _float_refused)
_bool_refused = False
try:
    validate_bet_amount(10.00, True)
except TypeError:
    _bool_refused = True
_assert("L3B-4: bool is refused too (bool is an int subclass — would otherwise slip through)",
        _bool_refused)
_int_ok = True
try:
    validate_bet_amount(10.00, 100_00)
except Exception:      # noqa: BLE001
    _int_ok = False
_assert("L3B-4: an integer-cent balance is accepted normally", _int_ok)


# ── L3B-5 — ordinary Bet: float HIGH, ledger LOW → refuse ────────────────────
# Pre-correction the cap was 20% of the $100,000.00 mirror = $20,000.00, so a
# $10.00 stake sailed through validate_bet_amount() and only died later inside
# ledger.post(). The distinct exception TYPE is the proof of which oracle ran.

print("\nL3B-5: ordinary Bet — float mirror HIGH, ledger LOW ($1.00) → refuse")

_l3b5_exc = None
with tdb.SessionLocal() as db:
    try:
        place_straight_bet(MU[3], WID["bet_hi_lo"], TID["bet_hi_lo"], 10.00, 3, db)
    except Exception as exc:      # noqa: BLE001
        _l3b5_exc = exc
        db.rollback()

_assert("L3B-5: refused", _l3b5_exc is not None)
_assert("L3B-5: refused by the CAPACITY GATE (BetValidationError), not by the "
        "downstream ledger guard — proves the gate itself read the ledger",
        isinstance(_l3b5_exc, BetValidationError), repr(_l3b5_exc))
_assert("L3B-5: refusal quotes the ledger-derived cap ($0.20 = 20% of $1.00)",
        "$0.20" in str(_l3b5_exc), str(_l3b5_exc))
_assert("L3B-5: ledger untouched", balance_of(f"wallet:{TID['bet_hi_lo']}") == 1_00)
with tdb.SessionLocal() as db:
    _n_bets = db.query(Bet).filter(Bet.matchup_id == MU[3]).count()
_assert("L3B-5: no Bet row created", _n_bets == 0, f"got {_n_bets}")


# ── L3B-6 — ordinary Bet: float LOW, ledger SUFFICIENT → do NOT falsely refuse ─
# Pre-correction the cap was 20% of a $0.00 mirror = $0.00 — every stake refused.

print("\nL3B-6: ordinary Bet — float mirror LOW ($0.00), ledger SUFFICIENT ($500.00) → funded")

_l3b6_exc = None
_l3b6_result = None
with tdb.SessionLocal() as db:
    try:
        _l3b6_result = place_straight_bet(MU[4], WID["bet_lo_ok"], TID["bet_lo_ok"], 10.00, 4, db)
    except Exception as exc:      # noqa: BLE001
        _l3b6_exc = exc
        db.rollback()

_assert("L3B-6: NOT falsely refused by the float mirror", _l3b6_exc is None, repr(_l3b6_exc))
_assert("L3B-6: bet placed, pending", _l3b6_result is not None and _l3b6_result.status == "pending")
_l3b6_after = balance_of(f"wallet:{TID['bet_lo_ok']}")
_assert("L3B-6: ledger debited exactly 1000 cents",
        _l3b6_after == 500_00 - 10_00, f"got {_l3b6_after}")
with tdb.SessionLocal() as db:
    _post_mirror6 = db.query(Wallet).filter(Wallet.team_id == TID["bet_lo_ok"]).first().balance
_assert("L3B-6: Wallet.balance mirror still $0.00 — unchanged by this correction",
        _post_mirror6 == _MIRROR_LOW, f"got {_post_mirror6}")


# ── L3B-7 — single-cent boundary decisions use integer cents ─────────────────

print("\nL3B-7: single-cent boundary — exactly-enough accepted, one cent short refused")

# Beef gate, ledger exactly == stake.
_exact_err = None
with tdb.SessionLocal() as db:
    _w = db.query(Wallet).filter(Wallet.team_id == TID["beef_exact"]).first()
    try:
        _place_beef_side(db, _w, 50.00, "straight", MU[2], TID["beef_exact"], None, None, None,
                         "L3B-7 exact", 1.909, beef_challenge_id=None)
        db.commit()
    except Exception as exc:      # noqa: BLE001
        _exact_err = exc
        db.rollback()
_assert("L3B-7: ledger exactly 5000c accepts a $50.00 stake (no off-by-one refusal)",
        _exact_err is None, repr(_exact_err))
_assert("L3B-7: that wallet's ledger balance is now exactly 0",
        balance_of(f"wallet:{TID['beef_exact']}") == 0)

# Beef gate, ledger exactly one cent short — and the float mirror says $100,000.00.
_short_err = None
with tdb.SessionLocal() as db:
    _w = db.query(Wallet).filter(Wallet.team_id == TID["beef_short1"]).first()
    try:
        _place_beef_side(db, _w, 50.00, "straight", MU[2], TID["beef_short1"], None, None, None,
                         "L3B-7 one cent short", 1.909, beef_challenge_id=None)
        db.commit()
    except ValueError as exc:
        _short_err = exc
        db.rollback()
_assert("L3B-7: ledger 4999c REFUSES a $50.00 stake — a single cent decides it",
        _short_err is not None)
_assert("L3B-7: refusal reports $49.99 (integer-cent arithmetic, not float drift)",
        _short_err is not None and "$49.99" in str(_short_err), str(_short_err))
_assert("L3B-7: one-cent-short wallet's ledger balance unmoved",
        balance_of(f"wallet:{TID['beef_short1']}") == 49_99)

# Bet cap, single-cent boundary in the corrected integer arithmetic.
_cap_exact_ok = True
try:
    validate_bet_amount(20.00, 100_00)        # 20% of $100.00 == $20.00 exactly
except BetValidationError:
    _cap_exact_ok = False
_assert("L3B-7: bet cap accepts a stake exactly equal to the cap", _cap_exact_ok)
_cap_over = False
try:
    validate_bet_amount(20.01, 100_00)        # one cent over the exact cap
except BetValidationError:
    _cap_over = True
_assert("L3B-7: bet cap refuses one cent over the cap", _cap_over)


# ── L3B-8 — MAX_BET_PCT rounding parity: ROUNDED cents, not floor ────────────
#
# The prior rule was `round(wallet_balance * MAX_BET_PCT, 2)` — the cap is
# ROUNDED to the nearest cent. The corrected integer form is
#
#     (balance_cents * _MAX_BET_BPS + 5000) // 10000        [_MAX_BET_BPS == 2000]
#
# which is half-up. Half-up is exactly nearest here with no reachable tie: 20% of
# an integer cent count is balance_cents / 5, whose fractional part is always one
# of {.0, .2, .4, .6, .8} and never .5. Floor and round therefore DISAGREE by one
# cent whenever balance_cents % 5 is 3 or 4 — those are the cases proved below.

print("\nL3B-8: MAX_BET_PCT rounding parity — rounded cents preserved, floor NOT silently adopted")

_assert("L3B-8: _MAX_BET_BPS is derived from MAX_BET_PCT and still means 20%",
        _MAX_BET_BPS == 2000 and MAX_BET_PCT == 0.20,
        f"bps={_MAX_BET_BPS} pct={MAX_BET_PCT}")


def _expected_cap_cents(balance_cents: int) -> int:
    """The INTENDED rule, derived independently of the implementation: 20% of the
    balance, rounded to the nearest cent (Decimal, ROUND_HALF_UP). Deliberately
    NOT a copy of the production expression — if it were, this suite would only
    prove the implementation equals itself."""
    return int((Decimal(balance_cents) * Decimal(2) / Decimal(10))
               .quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _floor_cap_cents(balance_cents: int) -> int:
    """The cap a naive floor conversion would produce — the exact regression this
    package must NOT have introduced."""
    return (balance_cents * 2) // 10


def _cap_accepts(balance_cents: int, amount: float) -> bool:
    """Probes the PRODUCTION function — never a local reimplementation."""
    try:
        validate_bet_amount(amount, balance_cents)
        return True
    except BetValidationError:
        return False


_MIN_BET_CENTS = round(MIN_BET * 100)


def _observed_cap_cents(balance_cents: int) -> int:
    """The production function's effective cap, observed behaviourally: the
    largest stake it accepts. Bisection over the cent range, so it depends on no
    assumption about how the cap is computed. Returns -1 when the cap sits below
    MIN_BET, where the minimum-bet rule dominates and the cap isn't probeable."""
    lo, hi = _MIN_BET_CENTS, max(balance_cents, _MIN_BET_CENTS)
    if not _cap_accepts(balance_cents, lo / 100):
        return -1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _cap_accepts(balance_cents, mid / 100):
            lo = mid
        else:
            hi = mid - 1
    return lo


# $125.03 → 20% is 2500.6c. floor = $25.00, ROUNDED = $25.01. They differ.
_B = 125_03
_floor = _floor_cap_cents(_B)
_round = _expected_cap_cents(_B)
_assert("L3B-8: chosen fixture is one where floor and rounded DIFFER by one cent",
        _round - _floor == 1, f"floor={_floor} round={_round}")
_assert("L3B-8: production returns the ROUNDED cap, not the floored one",
        _observed_cap_cents(_B) == _round,
        f"observed {_observed_cap_cents(_B)}, floor={_floor}, round={_round}")
_assert("L3B-8: $25.01 ACCEPTED on a $125.03 balance — a floor implementation would refuse this",
        _cap_accepts(_B, 25.01))
_assert("L3B-8: $25.02 REFUSED on a $125.03 balance (one cent over the rounded cap)",
        not _cap_accepts(_B, 25.02))

# The other rounding-down neighbour, to prove it is genuinely round-to-nearest
# rather than always-up: $125.02 → 2500.4c → $25.00.
_B2 = 125_02
_assert("L3B-8: $125.02 rounds DOWN to a $25.00 cap (nearest, not always-up)",
        _observed_cap_cents(_B2) == 2500, f"observed {_observed_cap_cents(_B2)}")
_assert("L3B-8: $25.00 accepted at that cap (exact-boundary acceptance)",
        _cap_accepts(_B2, 25.00))
_assert("L3B-8: $25.01 refused at that cap (one cent over)",
        not _cap_accepts(_B2, 25.01))

# Behavioural parity sweep. Every balance is probed through the PRODUCTION
# function (accept at the expected cap, refuse one cent over) — never through a
# local copy of its formula. Covers every residue class of balance_cents mod 5,
# and counts how many of those the naive floor conversion would have got wrong,
# so the sweep is proven to have teeth rather than trivially agreeing.
_mismatch: list[tuple[int, int, int]] = []
_floor_would_break = 0
for _bc in range(2_500, 52_501):
    _want = _expected_cap_cents(_bc)
    if _want != _floor_cap_cents(_bc):
        _floor_would_break += 1
    if not _cap_accepts(_bc, _want / 100):
        _mismatch.append((_bc, _want, -1))
    elif _cap_accepts(_bc, (_want + 1) / 100):
        _mismatch.append((_bc, _want, _want + 1))
_assert("L3B-8: production accepts exactly the rounded-cent cap and refuses one cent "
        "over it, for every balance $25.00..$525.00",
        not _mismatch, f"{len(_mismatch)} mismatches, first {_mismatch[:3]}")
_assert("L3B-8: the sweep really does cover balances where floor would be wrong",
        _floor_would_break == 20_000, f"got {_floor_would_break}")
_assert("L3B-8: no half-cent tie is reachable — 20% of integer cents never ends in .5",
        all((_bc * 2) % 10 != 5 for _bc in range(0, 10_000)))

# The min-bet rule is untouched by the cents conversion.
_min_still = False
try:
    validate_bet_amount(MIN_BET - 0.01, 1_000_00)
except BetValidationError:
    _min_still = True
_assert("L3B-8: MIN_BET rule preserved unchanged", _min_still)


# ── L3B-9 — ledger.post()'s funded guard remains the final defense ───────────

print("\nL3B-9: ledger.post() funded-account guard still fires when a higher gate is bypassed")

_guard_raised = False
with tdb.SessionLocal() as db:
    try:
        ledger_post(
            [(f"wallet:{TID['guard']}", -50_00), ("escrow:l3b9-probe", 50_00)],
            door="wager_placed",
            session=db,
        )
    except InsufficientFundsError:
        _guard_raised = True
    db.rollback()
_assert("L3B-9: a $50.00 debit against a $10.00 ledger balance raises InsufficientFundsError "
        "even with no gate in front of it", _guard_raised)
_assert("L3B-9: guarded wallet's ledger balance unchanged",
        balance_of(f"wallet:{TID['guard']}") == 10_00)
_assert("L3B-9: trial_balance still closes to zero across the whole suite",
        trial_balance() == 0, f"got {trial_balance()}")


# ── L3B-10 — retired faab_wallet.transfer remains structurally unreachable ───

print("\nL3B-10: faab_wallet.transfer remains structurally refused")

for _retired in ("transfer", "confirm_topup", "create_bet_topup",
                 "create_waiver_topup", "apply_pending_topups"):
    _fn = _fn_node("wallet/faab_wallet.py", _retired)
    _stmts = [s for s in _fn.body
              if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    _assert(f"L3B-10: faab_wallet.{_retired}'s first executable statement is still `raise`",
            bool(_stmts) and isinstance(_stmts[0], ast.Raise),
            type(_stmts[0]).__name__ if _stmts else "empty body")


# ── L3B-11 — no real-money / processor surface introduced ───────────────────

print("\nL3B-11: no Stripe / processor / payout-method / real-money surface introduced")

_MONEY_TOKENS = {
    "stripe", "Stripe", "payment_intent", "PaymentIntent", "connected_account",
    "ConnectedAccount", "plaid", "Plaid", "braintree", "paypal", "PayPal",
    "processor", "cash_out", "real_money", "payout_method", "ach_transfer",
    "card_charge", "withdraw_to_bank",
}
for _f in _CHANGED_FILES:
    _hits = _code_tokens(_f) & _MONEY_TOKENS
    _assert(f"L3B-11: {_f} introduces no real-money/processor identifier", not _hits, str(sorted(_hits)))

# Positive control: the tokeniser must be able to see a real identifier, and must
# NOT see one that exists only in a comment or docstring.
_probe = "x = 1  # stripe\n'''plaid'''\nprocessor = 2\n"
_probe_toks = {t.string for t in tokenize.generate_tokens(io.StringIO(_probe).readline)
               if t.type == tokenize.NAME}
_assert("L3B-11 positive control: scanner sees a real code identifier", "processor" in _probe_toks)
_assert("L3B-11 negative control: scanner ignores comment/docstring prose",
        "stripe" not in _probe_toks and "plaid" not in _probe_toks)


# ── L3B-12 — no Package 2B Group 2 functionality introduced ─────────────────

print("\nL3B-12: no Package 2B Group 2 functionality pulled forward")

_assert("L3B-12: economy/challenge_funding.py still does not exist",
        not (_ROOT / "economy" / "challenge_funding.py").exists())

_G2_TOKENS = {
    "ProtocolEvent", "LedgerPostingBatch", "ChallengeFundingLeg", "protocol_event_id",
    "challenge_funding", "get_available_to_bet", "weekly_minimum", "WeeklyMinimum",
    "fund_challenge", "reverse_funding_leg",
}
for _f in _CHANGED_FILES:
    _hits = _code_tokens(_f) & _G2_TOKENS
    _assert(f"L3B-12: {_f} introduces no Group 2 funding-primitive identifier",
            not _hits, str(sorted(_hits)))

# The corrected gates read plain wallet:{team_id} — no released-minimum term.
_assert("L3B-12: beef gate reads plain wallet:{team_id}, no min: account",
        "min:" not in ast.get_source_segment(
            (_ROOT / "beefs/beef_engine.py").read_text(encoding="utf-8"), _beef_fn))
_assert("L3B-12: bet gate reads plain wallet:{team_id}, no min: account",
        "min:" not in ast.get_source_segment(
            (_ROOT / "betting/bet_engine.py").read_text(encoding="utf-8"), _pb_fn))

# validate_bet_amount was NOT converted into an availability calculator.
_assert("L3B-12: validate_bet_amount takes exactly two parameters (no availability inputs)",
        len(_vba_params) == 2, str(_vba_params))


# ── Summary ──────────────────────────────────────────────────────────────────

tdb.teardown()

print(f"\n{'=' * 60}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
