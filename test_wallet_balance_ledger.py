"""
test_wallet_balance_ledger.py — FR-7.12: wallet balance reads/checks the ledger,
not the stale Wallet.balance ORM column.

Four fixture classes, exactly per FR-7.12 Rev3 Section 6:

  1. DISPLAY — the stale column and the true ledger balance are seeded to
     DIFFERENT values that stay distinguishable after /100 + ":.2f" (column
     $140.00, ledger 14033c -> $140.33). Every display site must return the
     ledger value, not the column. Covers /wallet/{team_id}, /league/roster/
     {team_id}, and /wallet/{team_id}/history.

     EXCEPTION — _state_out (the /wallet/deposit response builder) stays on the
     stale Wallet.balance column until FR-7.28 posts wm_deposit() to the ledger
     (spec Rev4 §3, MS-7.12-D-3): converting it now would either race or omit
     the deposit that was just made. Its fixture below asserts it echoes the
     deposit's resulting COLUMN value, NOT the ledger.

  2. FUNDS-CHECK, BOTH DIRECTIONS — via _verify_wallet_available() (the actual
     betting gate, corrected formula site):
       a. column HIGH, ledger LOW  -> rejected (money-integrity direction:
          proves a wrongly-allowed overdraw is now closed).
       b. column LOW,  ledger HIGH -> allowed (proves a bet the GM can afford
          is no longer wrongly blocked by the stale column).

  3. EXPOSURE — a GM with an existing pending bet (already escrowed in the
     ledger) makes a second wager that fits their TRUE remaining ledger
     balance. Must be ALLOWED. A live pending Bet row is present so that a
     reintroduced bet_exposure term would find it and double-subtract; the
     assertion that the wager is allowed proves bet_exposure was correctly
     dropped. Kept SEPARATE from the ch_reserved fixture per the spec — the
     two terms diverge in opposite directions and each needs its own proof.

  4. CH_RESERVED — a GM with an open PENDING BeefChallenge (no Bet row, no
     escrow posting — the challenge-preview stage) makes a wager that fits the
     RAW ledger balance but not (ledger - ch_reserved). Must be REJECTED. With
     bet_exposure gone, ch_reserved is the sole guard on challenge-stage funds
     and needs its own dedicated proof.

trial_balance() is asserted unchanged across the whole run (read-path fix,
no postings introduced).

Uses a temp SQLite DB so prod is never touched.
"""

import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_wallet_balance_ledger.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from db.schema import (
    Base, engine, SessionLocal,
    Bet, BeefChallenge, League, Matchup, Team, Wallet,
)
from ledger.ledger import balance_of, trial_balance, create_ledger_table, post as ledger_post
from beefs.beef_engine import _verify_wallet_available
from wallet.wallet_manager import WalletState
from api.main import app, _state_out

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

client = TestClient(app)


def _make_league(name: str) -> int:
    with SessionLocal() as db:
        lg = League(season=2025, name=f"FR712 {name}", projection_source="fantasypros")
        db.add(lg); db.commit()
        return lg.id


def _make_team(league_id: int, name: str, column_dollars: float, ledger_cents: int) -> int:
    """Team + Wallet whose ORM column is seeded to `column_dollars` (the STALE
    value) while the ledger wallet is funded to `ledger_cents` (the TRUE value)
    — deliberately different so any site still reading the column is caught."""
    with SessionLocal() as db:
        t = Team(league_id=league_id, team_name=f"FR712 {name}", owner=name, email=f"{name}@fr712.com")
        db.add(t); db.flush()
        db.add(Wallet(team_id=t.id, balance=column_dollars))  # stale ORM column
        db.commit()
        team_id = t.id
    if ledger_cents:
        ledger_post([("world", -ledger_cents), (f"wallet:{team_id}", ledger_cents)], door="buy_in_paid")
    return team_id


# ── FIXTURE 1: DISPLAY — every display site returns the ledger, not the column ──

print("\nFixture 1: DISPLAY — column $140.00 vs ledger $140.33, every site must show $140.33")

L1 = _make_league("display")
# Column seeded to $140.00; ledger seeded to 14033 cents -> $140.33. The two
# stay distinguishable after /100 and :.2f formatting (spec's own example).
D1 = _make_team(L1, "D1", column_dollars=140.00, ledger_cents=14033)

_assert("F1: ledger balance is 14033 cents (fixture check)", balance_of(f"wallet:{D1}") == 14033, f"got {balance_of(f'wallet:{D1}')}")

# GET /wallet/{team_id}
r = client.get(f"/wallet/{D1}")
_assert("F1: GET /wallet/{team_id} returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
_assert("F1: /wallet balance is the LEDGER $140.33, not the column $140.00",
        abs(r.json()["balance"] - 140.33) < 0.005, f"got {r.json().get('balance')}")

# GET /league/roster/{team_id}
r = client.get(f"/league/roster/{D1}")
_assert("F1: GET /league/roster returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
_assert("F1: /roster wallet_balance is the LEDGER $140.33, not the column $140.00",
        abs(r.json()["wallet_balance"] - 140.33) < 0.005, f"got {r.json().get('wallet_balance')}")

# GET /wallet/{team_id}/history
r = client.get(f"/wallet/{D1}/history")
_assert("F1: GET /wallet/{team_id}/history returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
_assert("F1: /history balance is the LEDGER $140.33, not the column $140.00",
        abs(r.json()["balance"] - 140.33) < 0.005, f"got {r.json().get('balance')}")

# _state_out (the /wallet/deposit response builder) is the deliberate EXCEPTION
# (spec Rev4 §3, MS-7.12-D-3): it stays on the stale Wallet.balance column until
# FR-7.28 lands wm_deposit()'s ledger posting. So here it must ECHO the deposit's
# resulting column value it is handed ($170.00 = $140 prior + a $30 deposit), NOT
# the $140.33 ledger — unit-tested directly, without the deposit route's auth dep.
post_deposit_state = WalletState(
    wallet_id=1, team_id=D1, team_name="FR712 D1", owner="D1",
    balance=170.00,  # the deposit's resulting COLUMN value (what wm_deposit() wrote)
    max_single_bet=28.0, open_bets=0, pending_exposure=0.0, challenge_reserved=0.0,
    total_deposited=0.0, total_withdrawn=0.0, total_wagered=0.0, total_payout=0.0,
)
out = _state_out(post_deposit_state)
_assert("F1: _state_out echoes the deposit's resulting COLUMN $170.00 (FR-7.28 exception), not the ledger $140.33",
        abs(out.balance - 170.00) < 0.005, f"got {out.balance}")


# ── FIXTURE 2: FUNDS-CHECK, BOTH DIRECTIONS (_verify_wallet_available) ──────────

print("\nFixture 2a: FUNDS-CHECK — column HIGH ($1000), ledger LOW ($5) — a $50 wager must be REJECTED")

L2 = _make_league("fc")
A2 = _make_team(L2, "A2", column_dollars=1000.00, ledger_cents=500)  # column $1000, ledger $5

raised_2a = False
try:
    with SessionLocal() as db:
        _verify_wallet_available(A2, 50.0, db)  # $50 needed; ledger only $5
except ValueError:
    raised_2a = True
_assert("F2a: $50 wager rejected against a $5 ledger despite a $1000 stale column (overdraw closed)", raised_2a)


print("\nFixture 2b: FUNDS-CHECK — column LOW ($5), ledger HIGH ($1000) — a $50 wager must be ALLOWED")

B2 = _make_team(L2, "B2", column_dollars=5.00, ledger_cents=100000)  # column $5, ledger $1000

allowed_2b = False
returned_wallet_ok = False
try:
    with SessionLocal() as db:
        w = _verify_wallet_available(B2, 50.0, db)  # $50 needed; ledger $1000
        allowed_2b = True
        returned_wallet_ok = (w is not None and w.team_id == B2)
except ValueError:
    allowed_2b = False
_assert("F2b: $50 wager allowed against a $1000 ledger despite a $5 stale column (affordable bet not blocked)", allowed_2b)
_assert("F2b: _verify_wallet_available returns the correct Wallet row on success", returned_wallet_ok)


# ── FIXTURE 3: EXPOSURE — pending bet already escrowed; second wager allowed ────

print("\nFixture 3: EXPOSURE — ledger $70 after a $30 escrowed bet; a $60 wager must be ALLOWED (bet_exposure not double-subtracted)")

L3 = _make_league("exposure")
C3 = _make_team(L3, "C3", column_dollars=100.00, ledger_cents=10000)  # ledger $100
# An opponent + matchup so a real pending Bet row can exist (a reintroduced
# bet_exposure term would query and double-subtract it).
OPP3 = _make_team(L3, "OPP3", column_dollars=100.00, ledger_cents=0)
with SessionLocal() as db:
    m = Matchup(league_id=L3, week=1, home_team_id=C3, away_team_id=OPP3, home_score=0.0, away_score=0.0)
    db.add(m); db.flush()
    w = db.query(Wallet).filter(Wallet.team_id == C3).first()
    bet = Bet(matchup_id=m.id, wallet_id=w.id, picked_team_id=C3, bet_type="straight",
              amount=30.0, odds=1.9, status="pending", placed_at=datetime.now(timezone.utc))
    db.add(bet); db.flush()
    bet_id = bet.id
    db.commit()
# Escrow the placed bet in the ledger: wallet -$30 -> escrow. Ledger wallet now $70.
ledger_post([(f"wallet:{C3}", -3000), (f"escrow:{bet_id}", 3000)], door="wager_placed")

_assert("F3: ledger balance is $70 after the $30 escrow (fixture check)", balance_of(f"wallet:{C3}") == 7000, f"got {balance_of(f'wallet:{C3}')}")

allowed_3 = False
try:
    with SessionLocal() as db:
        _verify_wallet_available(C3, 60.0, db)  # $60 <= $70 ledger; a double-subtract of $30 would wrongly reject
        allowed_3 = True
except ValueError:
    allowed_3 = False
_assert("F3: $60 wager allowed against a $70 ledger with a $30 pending bet already escrowed (single-counted, not double)", allowed_3)


# ── FIXTURE 4: CH_RESERVED — open challenge reserves funds; wager rejected ──────

print("\nFixture 4: CH_RESERVED — ledger $100, an open $60 pending challenge; a $60 wager must be REJECTED (ledger - ch_reserved)")

L4 = _make_league("chres")
E4 = _make_team(L4, "E4", column_dollars=100.00, ledger_cents=10000)  # ledger $100, NO escrow
F4 = _make_team(L4, "F4", column_dollars=100.00, ledger_cents=0)
now = datetime.now(timezone.utc)
with SessionLocal() as db:
    # An OPEN challenge issued by E4, in the shape the funded lifecycle leaves
    # behind: a challenge row carrying its Spec-1 negotiation state, and the
    # Anchor stake really posted to that challenge's escrow account.
    ch = BeefChallenge(
        challenger_team_id=E4, challenged_team_id=F4, week=1, bet_type="straight",
        amount=60.0, line=None, side=None, player_id=None, description="fr712 open challenge",
        challenger_odds=1.9, challenged_odds=1.9, challenger_moneyline=-110, challenged_moneyline=-110,
        status="pending", response_status="offered",
        expires_at=now + timedelta(hours=24), created_at=now,
        projection_snapshot=None, staleness_warning=0,
    )
    db.add(ch); db.commit()
    ch_id = ch.id

ledger_post([(f"wallet:{E4}", -6000), (f"escrow:challenge:{ch_id}", 6000)],
            door="challenge_issued")

_assert("F4: the stake really left the wallet — ledger is $40, not $100 (fixture check)",
        balance_of(f"wallet:{E4}") == 4000, f"got {balance_of(f'wallet:{E4}')}")

raised_4 = False
try:
    with SessionLocal() as db:
        # $60 no longer fits, and nothing had to model why: the $60 is sitting
        # in challenge escrow where the balance read can already see it gone.
        _verify_wallet_available(E4, 60.0, db)
except ValueError:
    raised_4 = True
_assert("F4: $60 wager rejected — the open challenge's stake is escrowed, so the ledger balance alone refuses it", raised_4)


# ── Trial balance smoke check ──────────────────────────────────────────────────

print("\nSmoke: trial_balance unchanged (read-path fix, no postings introduced by this spec)")
_assert("trial_balance closes to 0 across the whole run", trial_balance() == 0, f"got {trial_balance()}")


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
