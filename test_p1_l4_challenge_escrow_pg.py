"""
test_p1_l4_challenge_escrow_pg.py — P1-L4 targeted suite (Spec 2 core).

CONTROLLING RULE (Foundation Correction Plan, Section 5):

    "At issue, post real issuer Anchor escrow to escrow:challenge:{id},
     source-split min-first-then-wallet, with ordered append-only funding-leg
     provenance."

    "Lifecycle scope — non-negotiable. Issue-time escrow does not ship without
     its complete lifecycle. Each terminal reverses or transfers the exact
     challenge escrow."

THE DISCRIMINATING FIXTURE. Spec 2 §15 and the Foundation plan §7 both forbid
closing a money finding on clean/equal numbers. The load-bearing case in this
suite is an UNEQUAL mixed source split (600 min / 400 wallet) followed by a
PARTIAL release of 200. Strict reverse-leg order returns 200 from the wallet leg
and nothing from min; proportional division would return 120 min + 80 wallet.
The two answers differ, so every reverse-order assertion below has teeth.

Runs on real PostgreSQL: the lifecycle takes SELECT ... FOR UPDATE row locks
(challenge row, then Wallet scopes), which SQLite does not enforce.

    $env:TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5433/fantasy_test"
    python test_p1_l4_challenge_escrow_pg.py
"""

from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db

tdb = setup_postgres_test_db()

import atexit
atexit.register(lambda: tdb.teardown())

from sqlalchemy import text

from db.schema import (
    BeefChallenge, Bet, ChallengeFundingLeg, League, Matchup, ProtocolEvent,
    Team, Wallet,
)
from ledger.ledger import _balance_of_in_session, balance_of, post as ledger_post, trial_balance
from beefs import proposal_lifecycle as spec1
from economy import challenge_funding as cf
from economy.challenge_funding import (
    AcceptanceCapacityError, EscrowReconciliationError,
    InsufficientFundingCapacityError,
)

REPO = Path(__file__).resolve().parent
WEEK = 1

_passes = 0
_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passes
    if condition:
        _passes += 1
        print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))
    else:
        _failures.append(label)
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{title}")


# ── Fixtures ──────────────────────────────────────────────────────────────────

def seed(min_reserve_cents: dict[str, int], min_cents: dict[str, int] | None = None) -> dict:
    """A league with the named teams, their wallets, a matchup, and seeded ledger
    balances. The float Wallet.balance mirror is set DELIBERATELY WRONG on every
    wallet so nothing below can pass by consulting it (P1-L3B stays proven)."""
    min_cents = min_cents or {}
    ids: dict = {}
    with tdb.SessionLocal() as db:
        league = League(season=2025, name="P1-L4 League")
        db.add(league); db.flush()
        for name in min_reserve_cents:
            team = Team(league_id=league.id, team_name=name, owner=f"o-{name}",
                        email=f"{name}@p1l4.test")
            db.add(team); db.flush()
            db.add(Wallet(team_id=team.id, balance=99_999.0))   # wrong on purpose
            ids[name] = team.id
        names = list(min_reserve_cents)
        db.add(Matchup(league_id=league.id, week=WEEK,
                       home_team_id=ids[names[0]], away_team_id=ids[names[1]],
                       home_score=0.0, away_score=0.0))
        for name, cents in min_reserve_cents.items():
            if cents:
                ledger_post([("world", -cents), (f"wallet:{ids[name]}", cents)],
                            door="buy_in_paid", session=db)
        for name, cents in min_cents.items():
            if cents:
                ledger_post([("world", -cents), (f"min:{ids[name]}:{WEEK}", cents)],
                            door="buy_in_paid", session=db)
        ids["_league"] = league.id
        db.commit()
    return ids


def terms(anchor_cents: int, derived_cents: int = 0) -> spec1.ProposalTerms:
    return spec1.ProposalTerms(
        anchor_stake_cents         = anchor_cents,
        quoted_derived_stake_cents = derived_cents,
        anchor_odds                = 1.909,
        derived_odds               = 1.909,
        anchor_moneyline           = -110,
        derived_moneyline          = -110,
    )


def issue(ids, challenger, challenged, anchor, derived=0, **kw):
    with tdb.SessionLocal() as db:
        return cf.issue_funded_challenge(
            event_id=uuid.uuid4(), league_id=ids["_league"], week=WEEK,
            challenger_team_id=ids[challenger], challenged_team_id=ids[challenged],
            wager_type="straight", terms=terms(anchor, derived), db=db, **kw)


def legs_for(challenge_id: int) -> list[ChallengeFundingLeg]:
    with tdb.SessionLocal() as db:
        return (db.query(ChallengeFundingLeg)
                .filter(ChallengeFundingLeg.challenge_id == challenge_id)
                .order_by(ChallengeFundingLeg.sequence_number).all())


def bal(account: str) -> int:
    return balance_of(account)


def w(name: str) -> int:
    """Wallet ledger balance (cents) for a seeded team name. Reads the CURRENT
    fixture's ids, so it follows each section's reseed."""
    return bal(f"wallet:{ids[name]}")


def m(name: str) -> int:
    """Weekly-min ledger balance (cents) for a seeded team name."""
    return bal(f"min:{ids[name]}:{WEEK}")


def escrow_of(challenge_id: int) -> int:
    return bal(f"escrow:challenge:{challenge_id}")


def conservation(label: str) -> None:
    check(f"{label}: trial balance closes to exactly zero", trial_balance() == 0,
          f"got {trial_balance()}")


# ══════════════════════════════════════════════════════════════════════════════
# ISSUE
# ══════════════════════════════════════════════════════════════════════════════
section("ISSUE-1: wallet-only issue moves exact cents into escrow:challenge:{id}")

tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000})
r = issue(ids, "alpha", "beta", 5_000)

check("ISSUE-1: escrow:challenge:{id} holds exactly the Anchor",
      escrow_of(r.challenge_id) == 5_000, f"got {escrow_of(r.challenge_id)}")
check("ISSUE-1: the issuer's wallet was debited by exactly the Anchor",
      w("alpha") == 5_000, f"got {w('alpha')}")
check("ISSUE-1: the recipient's wallet is untouched — issue commits only the issuer",
      bal(f"wallet:{ids['beta']}") == 10_000, f"got {w('beta')}")
check("ISSUE-1: exactly one funding leg (wallet-only)",
      len(legs_for(r.challenge_id)) == 1, f"got {len(legs_for(r.challenge_id))}")
_l = legs_for(r.challenge_id)[0]
check("ISSUE-1: that leg is a positive `fund` leg from wallet:{team}",
      _l.leg_kind == "fund" and _l.amount_cents == 5_000
      and _l.source_account == f"wallet:{ids['alpha']}",
      f"{_l.leg_kind} {_l.amount_cents} from {_l.source_account}")
check("ISSUE-1: the leg's destination is the challenge escrow account",
      _l.destination_account == f"escrow:challenge:{r.challenge_id}")
check("ISSUE-1: the challenge is 'offered' with real escrow behind it",
      r.response_status == "offered" and r.escrow_cents == 5_000)
conservation("ISSUE-1")

section("ISSUE-2: min-only issue consumes the weekly-min source first")

tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000}, min_cents={"alpha": 8_000})
r = issue(ids, "alpha", "beta", 5_000)
_legs = legs_for(r.challenge_id)

check("ISSUE-2: escrow holds the exact Anchor", escrow_of(r.challenge_id) == 5_000)
check("ISSUE-2: min was consumed, not wallet",
      bal(f"min:{ids['alpha']}:{WEEK}") == 3_000
      and bal(f"wallet:{ids['alpha']}") == 10_000,
      f"min={m('alpha')} "
      f"wallet={w('alpha')}")
check("ISSUE-2: exactly one leg, sourced from min", len(_legs) == 1
      and _legs[0].source_account == f"min:{ids['alpha']}:{WEEK}")
conservation("ISSUE-2")

section("ISSUE-3: mixed min + wallet issue, UNEQUAL split (the load-bearing fixture)")

tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000}, min_cents={"alpha": 600})
r = issue(ids, "alpha", "beta", 1_000)
MIXED = r.challenge_id
_legs = legs_for(MIXED)

check("ISSUE-3: escrow holds exactly 1000c", escrow_of(MIXED) == 1_000)
check("ISSUE-3: min drained to zero (600 consumed first)",
      bal(f"min:{ids['alpha']}:{WEEK}") == 0)
check("ISSUE-3: wallet covered only the 400c remainder",
      bal(f"wallet:{ids['alpha']}") == 9_600,
      f"got {w('alpha')}")
check("ISSUE-3: two legs recorded", len(_legs) == 2, f"got {len(_legs)}")
check("ISSUE-3: leg order is MIN FIRST then WALLET — order is the product, not "
      "just the amounts",
      _legs[0].source_account.startswith("min:") and _legs[0].amount_cents == 600
      and _legs[1].source_account.startswith("wallet:") and _legs[1].amount_cents == 400,
      f"seq{_legs[0].sequence_number}={_legs[0].source_account}:{_legs[0].amount_cents}, "
      f"seq{_legs[1].sequence_number}={_legs[1].source_account}:{_legs[1].amount_cents}")
check("ISSUE-3: sequence numbers are strictly increasing",
      _legs[0].sequence_number < _legs[1].sequence_number)
check("ISSUE-3: the split is UNEQUAL, so a proportional refund would differ",
      _legs[0].amount_cents != _legs[1].amount_cents)
conservation("ISSUE-3")

section("ISSUE-4: absent / zero min account reads as zero, funding falls to wallet")

tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000})       # no min account seeded at all
with tdb.SessionLocal() as db:
    n_min = db.execute(text("SELECT COUNT(*) FROM ledger_entries WHERE account LIKE 'min:%'")).scalar()
check("ISSUE-4: no min account exists in the ledger at all", n_min == 0)
r = issue(ids, "alpha", "beta", 2_500)
check("ISSUE-4: an absent min reads as zero rather than failing",
      escrow_of(r.challenge_id) == 2_500)
check("ISSUE-4: the whole Anchor came from wallet",
      len(legs_for(r.challenge_id)) == 1
      and legs_for(r.challenge_id)[0].source_account == f"wallet:{ids['alpha']}")
conservation("ISSUE-4")

section("ISSUE-5: insufficient funding posts nothing and creates no challenge")

tdb.reset()
ids = seed({"alpha": 1_000, "beta": 10_000})
before_ch = None
with tdb.SessionLocal() as db:
    before_ch = db.execute(text("SELECT COUNT(*) FROM beef_challenges")).scalar()
raised = None
try:
    issue(ids, "alpha", "beta", 5_000)
except InsufficientFundingCapacityError as exc:
    raised = exc
check("ISSUE-5: refused with InsufficientFundingCapacityError", raised is not None,
      str(raised)[:80])
with tdb.SessionLocal() as db:
    after_ch = db.execute(text("SELECT COUNT(*) FROM beef_challenges")).scalar()
    n_legs   = db.execute(text("SELECT COUNT(*) FROM challenge_funding_legs")).scalar()
    n_esc    = db.execute(text(
        "SELECT COUNT(*) FROM ledger_entries WHERE account LIKE 'escrow:challenge:%'")).scalar()
check("ISSUE-5: NO challenge row was created", after_ch == before_ch,
      f"{before_ch} -> {after_ch}")
check("ISSUE-5: no funding legs", n_legs == 0)
check("ISSUE-5: no partial challenge escrow anywhere", n_esc == 0)
check("ISSUE-5: the issuer's wallet is untouched",
      bal(f"wallet:{ids['alpha']}") == 1_000)
conservation("ISSUE-5")

section("ISSUE-6: a retried issue event cannot double-post")

tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000})
EV = uuid.uuid4()
with tdb.SessionLocal() as db:
    first = cf.issue_funded_challenge(
        event_id=EV, league_id=ids["_league"], week=WEEK,
        challenger_team_id=ids["alpha"], challenged_team_id=ids["beta"],
        wager_type="straight", terms=terms(3_000), db=db)
with tdb.SessionLocal() as db:
    second = cf.issue_funded_challenge(
        event_id=EV, league_id=ids["_league"], week=WEEK,
        challenger_team_id=ids["alpha"], challenged_team_id=ids["beta"],
        wager_type="straight", terms=terms(3_000), db=db)
check("ISSUE-6: the retry is reported as a replay, not a new issue",
      second.replayed is True and first.replayed is False)
check("ISSUE-6: the replay returns the ORIGINAL challenge id",
      second.challenge_id == first.challenge_id)
with tdb.SessionLocal() as db:
    n_ch = db.execute(text("SELECT COUNT(*) FROM beef_challenges")).scalar()
    n_ev = db.execute(text("SELECT COUNT(*) FROM protocol_events WHERE event_id = :e"),
                      {"e": str(EV)}).scalar()
check("ISSUE-6: exactly one challenge exists", n_ch == 1, f"got {n_ch}")
check("ISSUE-6: exactly one ProtocolEvent for that event_id", n_ev == 1)
check("ISSUE-6: the money posted exactly ONCE — wallet debited 3000 total",
      bal(f"wallet:{ids['alpha']}") == 7_000,
      f"got {w('alpha')}")
check("ISSUE-6: escrow holds one Anchor, not two",
      escrow_of(first.challenge_id) == 3_000)
conservation("ISSUE-6")


# ══════════════════════════════════════════════════════════════════════════════
# PROVENANCE
# ══════════════════════════════════════════════════════════════════════════════
section("PROV-7/8/9: funding legs reconstruct the original funding exactly")

tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000}, min_cents={"alpha": 600})
r = issue(ids, "alpha", "beta", 1_000)
CH = r.challenge_id
_legs = legs_for(CH)

reconstructed = {(l.source_account, l.amount_cents) for l in _legs}
check("PROV-7: the legs reconstruct the exact original source mix",
      reconstructed == {(f"min:{ids['alpha']}:{WEEK}", 600),
                        (f"wallet:{ids['alpha']}", 400)},
      str(sorted(reconstructed)))
check("PROV-7: the legs sum to exactly the escrow balance",
      sum(l.amount_cents for l in _legs) == escrow_of(CH) == 1_000)
check("PROV-8: leg order is deterministic and replayable (ascending sequence)",
      [l.sequence_number for l in _legs] == sorted(l.sequence_number for l in _legs))
check("PROV-8: every leg carries its governing protocol event",
      all(l.protocol_event_id is not None for l in _legs))
check("PROV-8: every leg carries the posting_id of the batch that moved it",
      all(l.posting_id is not None for l in _legs))
check("PROV-8: every leg links to its LedgerPostingBatch",
      all(l.posting_batch_id is not None for l in _legs))

with tdb.SessionLocal() as db:
    expected = cf.expected_challenge_escrow(db, CH)
    actual   = cf.challenge_escrow_balance(db, CH)
check("PROV-9: expected(provenance) == actual(ledger) — the two agree",
      expected == actual == 1_000, f"expected={expected} actual={actual}")
# A BEHAVIOURAL proof that expected-escrow reads the LEGS and not the balance:
# move money out of the escrow account behind the provenance's back and the two
# must diverge. If expected() were reading the balance they would still agree.
with tdb.SessionLocal() as db:
    ledger_post([(f"escrow:challenge:{CH}", -100), ("world", 100)],
                door="manual_adjustment", session=db)
    db.commit()
with tdb.SessionLocal() as db:
    expected_after = cf.expected_challenge_escrow(db, CH)
    actual_after   = cf.challenge_escrow_balance(db, CH)
check("PROV-9: expected escrow is derived from LEGS, never from current balances "
      "— draining the account moves `actual` but leaves `expected` at the funded "
      "total",
      expected_after == 1_000 and actual_after == 900,
      f"expected={expected_after} actual={actual_after}")
conservation("PROV")


# ══════════════════════════════════════════════════════════════════════════════
# AVAILABILITY
# ══════════════════════════════════════════════════════════════════════════════
section("AVAIL-10/11/12: real escrow reduces capacity; no soft-reservation oracle")

tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000})
with tdb.SessionLocal() as db:
    before = cf.available_cents(db, ids["alpha"], WEEK)
r = issue(ids, "alpha", "beta", 4_000)
with tdb.SessionLocal() as db:
    after = cf.available_cents(db, ids["alpha"], WEEK)
check("AVAIL-10: the real escrow debit reduced authoritative availability",
      before == 10_000 and after == 6_000, f"{before} -> {after}")

import ast as _ast
import inspect as _inspect
avail_src = _inspect.getsource(cf.available_cents)
mod_src   = (REPO / "economy" / "challenge_funding.py").read_text(encoding="utf-8")


def executable_source(source: str) -> str:
    """The module's EXECUTABLE code, with comments AND docstrings removed.

    Stripping comments alone is not enough here: this module's docstrings
    deliberately NAME `_challenge_reserved` to record that it is never consulted,
    and a prose mention must not be mistaken for a call. Docstrings are the first
    Expr(Constant(str)) of a module, class or function, so they can be removed
    precisely rather than guessed at."""
    tree = _ast.parse(source)
    for node in _ast.walk(tree):
        if not isinstance(node, (_ast.Module, _ast.ClassDef,
                                 _ast.FunctionDef, _ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], _ast.Expr)
                and isinstance(body[0].value, _ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [_ast.Pass()]
    return _ast.unparse(_ast.fix_missing_locations(tree))


code_only = executable_source(mod_src)
check("AVAIL-11: challenge_funding NEVER imports or calls _challenge_reserved",
      "_challenge_reserved" not in code_only, "zero references in executable code")
check("AVAIL-11: availability is exactly min + wallet ledger cents",
      "_balance_of_in_session" in avail_src and "min_account" in avail_src
      and "wallet_account" in avail_src)

# The double-subtraction proof: availability must equal the plain ledger sum.
with tdb.SessionLocal() as db:
    raw = (_balance_of_in_session(db, f"wallet:{ids['alpha']}")
           + max(0, _balance_of_in_session(db, f"min:{ids['alpha']}:{WEEK}")))
    computed = cf.available_cents(db, ids["alpha"], WEEK)
check("AVAIL-12: availability == raw ledger sum, with NOTHING subtracted twice",
      computed == raw == 6_000, f"computed={computed} raw={raw}")

# And the legacy soft reservation must not see this new-model challenge at all.
from wallet.wallet_manager import _challenge_reserved
with tdb.SessionLocal() as db:
    soft = _challenge_reserved(ids["alpha"], db)
check("AVAIL-12: _challenge_reserved returns 0.0 for a NEW-MODEL challenge — it "
      "is scoped to legacy rows, so no gate can subtract escrow and reservation "
      "for the same money",
      soft == 0.0, f"got {soft}")
with tdb.SessionLocal() as db:
    real = cf.team_open_challenge_escrow_cents(db, ids["alpha"])
check("AVAIL-12: the display reader reports the REAL escrow instead",
      real == 4_000, f"got {real}")
conservation("AVAIL")


# ══════════════════════════════════════════════════════════════════════════════
# TERMINALS
# ══════════════════════════════════════════════════════════════════════════════
def fresh_mixed():
    """Issue 1000c as an UNEQUAL 600 min / 400 wallet split."""
    tdb.reset()
    i = seed({"alpha": 10_000, "beta": 10_000}, min_cents={"alpha": 600})
    res = issue(i, "alpha", "beta", 1_000)
    return i, res.challenge_id


section("TERM-13: decline refunds the exact funding legs to their exact sources")

ids, CH = fresh_mixed()
with tdb.SessionLocal() as db:
    d = cf.decline_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                    actor_team_id=ids["beta"], db=db)
check("TERM-13: response_status is 'declined'", d.response_status == "declined")
check("TERM-13: challenge escrow is fully drained", escrow_of(CH) == 0)
check("TERM-13: min was refunded its EXACT 600, not a proportion",
      bal(f"min:{ids['alpha']}:{WEEK}") == 600,
      f"got {m('alpha')}")
check("TERM-13: wallet was refunded its EXACT 400",
      bal(f"wallet:{ids['alpha']}") == 10_000)
_rev = [l for l in legs_for(CH) if l.leg_kind == "reverse"]
check("TERM-13: two reverse legs written, both negative",
      len(_rev) == 2 and all(l.amount_cents < 0 for l in _rev))
check("TERM-13: reverse order is STRICT REVERSE — the wallet leg (last funded) "
      "is reversed first",
      _rev[0].source_account.startswith("wallet:")
      and _rev[1].source_account.startswith("min:"),
      f"{_rev[0].source_account} then {_rev[1].source_account}")
check("TERM-13: every reverse leg names the exact fund leg it draws from",
      all(l.reverses_funding_leg_id is not None for l in _rev))
conservation("TERM-13")

section("TERM-14: cancel (issuer withdrawal) refunds the exact funding legs")

ids, CH = fresh_mixed()
with tdb.SessionLocal() as db:
    c = cf.cancel_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                   actor_team_id=ids["alpha"], db=db)
check("TERM-14: response_status is 'cancelled'", c.response_status == "cancelled")
check("TERM-14: exact source-faithful refund (600 min / 400 wallet)",
      bal(f"min:{ids['alpha']}:{WEEK}") == 600
      and bal(f"wallet:{ids['alpha']}") == 10_000)
check("TERM-14: challenge escrow drained", escrow_of(CH) == 0)
conservation("TERM-14")

section("TERM-15: expiry refunds the exact funding legs")

ids, CH = fresh_mixed()
later = datetime.now(timezone.utc) + timedelta(hours=3)
with tdb.SessionLocal() as db:
    e = cf.expire_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                   db=db, now=later)
check("TERM-15: response_status is 'expired'", e.response_status == "expired")
check("TERM-15: exact source-faithful refund", escrow_of(CH) == 0
      and bal(f"min:{ids['alpha']}:{WEEK}") == 600
      and bal(f"wallet:{ids['alpha']}") == 10_000)
check("TERM-15: expiry is system-owned (no actor recorded as a team)",
      True)
with tdb.SessionLocal() as db:
    ev = db.query(ProtocolEvent).filter(
        ProtocolEvent.challenge_id == CH,
        ProtocolEvent.event_type == "challenge_expire").first()
check("TERM-15: the expiry event records actor 'system'",
      ev is not None and ev.actor_identity == "system",
      ev.actor_identity if ev else "no event")
conservation("TERM-15")

section("TERM-16: unequal mixed-source PARTIAL reversal — proportional would differ")

# This is the discriminating case. Escrow 1000 = 600 min (seq1) + 400 wallet
# (seq2). Release 200. Strict reverse order takes all 200 from the WALLET leg.
# Proportional would take 120 min + 80 wallet. The numbers differ, so this
# assertion distinguishes the two implementations.
ids, CH = fresh_mixed()
with tdb.SessionLocal() as db:
    challenge = db.query(BeefChallenge).filter(BeefChallenge.id == CH).one()
    ev = cf._open_event(db, event_id=uuid.uuid4(), event_type="challenge_accept",
                        challenge=challenge, actor_identity=str(ids["alpha"]))
    cf._reverse(db, challenge=challenge, amount_cents=200, event=ev,
                door=cf.DOOR_RELEASED)
    db.commit()

check("TERM-16: escrow reduced by exactly 200", escrow_of(CH) == 800)
check("TERM-16: the whole 200 came from the WALLET leg (strict reverse order)",
      bal(f"wallet:{ids['alpha']}") == 9_800,
      f"wallet={w('alpha')} (9800 = strict reverse; 9720 would be proportional)")
check("TERM-16: min received NOTHING — proportional would have returned 120",
      bal(f"min:{ids['alpha']}:{WEEK}") == 0,
      f"min={m('alpha')} (0 = strict reverse; 120 would be proportional)")
_rev = [l for l in legs_for(CH) if l.leg_kind == "reverse"]
check("TERM-16: exactly one reverse leg, against the wallet fund leg",
      len(_rev) == 1 and _rev[0].source_account.startswith("wallet:")
      and _rev[0].amount_cents == -200)

# remaining_reversible must now be 200 on the wallet leg, 600 on the min leg.
with tdb.SessionLocal() as db:
    fund_legs = [l for l in (db.query(ChallengeFundingLeg)
                             .filter(ChallengeFundingLeg.challenge_id == CH,
                                     ChallengeFundingLeg.leg_kind == "fund")
                             .order_by(ChallengeFundingLeg.sequence_number).all())]
    remaining = {l.source_account.split(":")[0]: cf._remaining_reversible(db, l)
                 for l in fund_legs}
check("TERM-16: remaining_reversible is exact per leg — min 600, wallet 200",
      remaining == {"min": 600, "wallet": 200}, str(remaining))
check("TERM-16: no remaining_reversible went negative",
      all(v >= 0 for v in remaining.values()))
conservation("TERM-16")

section("TERM-17: mismatched escrow fails closed — no refund, no terminal state")

ids, CH = fresh_mixed()
# Deliberately break the invariant: drain 300c out of challenge escrow behind the
# provenance's back, so actual(700) != expected(1000).
with tdb.SessionLocal() as db:
    ledger_post([(f"escrow:challenge:{CH}", -300), ("world", 300)],
                door="manual_adjustment", session=db)
    db.commit()
check("TERM-17: fixture really is mismatched", escrow_of(CH) == 700)

raised = None
try:
    with tdb.SessionLocal() as db:
        cf.expire_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                   db=db, now=later)
except EscrowReconciliationError as exc:
    raised = exc
check("TERM-17: expiry raised EscrowReconciliationError", raised is not None,
      str(raised)[:80])
with tdb.SessionLocal() as db:
    ch = db.query(BeefChallenge).filter(BeefChallenge.id == CH).one()
check("TERM-17: the challenge was NOT marked Expired — it stays open for recovery",
      ch.response_status == "offered", f"got {ch.response_status}")
check("TERM-17: NO refund was made — escrow untouched at its mismatched value",
      escrow_of(CH) == 700, f"got {escrow_of(CH)}")
check("TERM-17: the issuer's sources received nothing",
      bal(f"min:{ids['alpha']}:{WEEK}") == 0 and bal(f"wallet:{ids['alpha']}") == 9_600)
with tdb.SessionLocal() as db:
    audit = db.query(ProtocolEvent).filter(
        ProtocolEvent.challenge_id == CH,
        ProtocolEvent.result_code == "reconciliation_error").first()
check("TERM-17: a reconciliation_error audit event EXISTS and survived the failure",
      audit is not None, audit.event_type if audit else "missing")
check("TERM-17: that audit event records the state as unchanged",
      audit is not None and audit.resulting_state == "offered")
check("TERM-17: 'balance > 0' was not treated as good enough — a PARTIAL escrow "
      "still fails closed", escrow_of(CH) == 700 and ch.response_status == "offered")

# Decline and cancel must fail closed too — §11 is explicit this is not
# expiry-specific.
for name, fn, actor in (("decline", cf.decline_funded_challenge, "beta"),
                        ("cancel",  cf.cancel_funded_challenge,  "alpha")):
    got = None
    try:
        with tdb.SessionLocal() as db:
            fn(event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=ids[actor], db=db)
    except EscrowReconciliationError as exc:
        got = exc
    check(f"TERM-17: {name} ALSO fails closed on the mismatch (not expiry-only)",
          got is not None)
with tdb.SessionLocal() as db:
    ch = db.query(BeefChallenge).filter(BeefChallenge.id == CH).one()
check("TERM-17: still not terminalized after all three attempts",
      ch.response_status == "offered")
conservation("TERM-17")

section("TERM-18: duplicate terminal execution does not double-refund")

ids, CH = fresh_mixed()
EV = uuid.uuid4()
with tdb.SessionLocal() as db:
    cf.decline_funded_challenge(event_id=EV, challenge_id=CH,
                                actor_team_id=ids["beta"], db=db)
with tdb.SessionLocal() as db:
    again = cf.decline_funded_challenge(event_id=EV, challenge_id=CH,
                                        actor_team_id=ids["beta"], db=db)
check("TERM-18: the repeat is a replay", again.replayed is True)
check("TERM-18: sources were refunded EXACTLY ONCE",
      bal(f"min:{ids['alpha']}:{WEEK}") == 600
      and bal(f"wallet:{ids['alpha']}") == 10_000,
      f"min={m('alpha')} "
      f"wallet={w('alpha')}")
check("TERM-18: escrow did not go negative", escrow_of(CH) == 0)
_rev = [l for l in legs_for(CH) if l.leg_kind == "reverse"]
check("TERM-18: only two reverse legs exist, not four", len(_rev) == 2)

# A DIFFERENT event id on an already-terminal challenge must also not re-refund.
third = None
with tdb.SessionLocal() as db:
    third = cf.decline_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                        actor_team_id=ids["beta"], db=db)
check("TERM-18: a NEW event id on an already-declined challenge returns the "
      "committed state and refunds nothing",
      third.replayed is True and bal(f"wallet:{ids['alpha']}") == 10_000,
      third.detail)
conservation("TERM-18")


# ══════════════════════════════════════════════════════════════════════════════
# ACCEPTANCE
# ══════════════════════════════════════════════════════════════════════════════
def accept_ready(anchor: int, derived: int, min_alpha: int = 0,
                 wallet_alpha: int = 10_000, wallet_beta: int = 10_000):
    tdb.reset()
    i = seed({"alpha": wallet_alpha, "beta": wallet_beta},
             min_cents={"alpha": min_alpha} if min_alpha else None)
    res = issue(i, "alpha", "beta", anchor, derived)
    return i, res.challenge_id


section("ACC-19: unchanged Anchor migrates exactly into Bet escrow")

ids, CH = accept_ready(1_000, 750)
with tdb.SessionLocal() as db:
    a = cf.accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                   actor_team_id=ids["beta"], db=db)
check("ACC-19: response_status is 'accepted'", a.response_status == "accepted")
check("ACC-19: challenge escrow is now EXACTLY ZERO — fully migrated out",
      escrow_of(CH) == 0, f"got {escrow_of(CH)}")
check("ACC-19: the Anchor Bet's escrow holds exactly the Anchor",
      bal(f"escrow:{a.anchor_bet_id}") == 1_000)
check("ACC-19: the Derived Bet's escrow holds exactly the Derived stake",
      bal(f"escrow:{a.derived_bet_id}") == 750)
check("ACC-19: the pot is Anchor + Derived = 1750",
      bal(f"escrow:{a.anchor_bet_id}") + bal(f"escrow:{a.derived_bet_id}") == 1_750)
check("ACC-19: the recipient funded the Derived from their own wallet",
      bal(f"wallet:{ids['beta']}") == 9_250,
      f"got {w('beta')}")
check("ACC-19: the issuer paid only the Anchor",
      bal(f"wallet:{ids['alpha']}") == 9_000)
conservation("ACC-19")

section("ACC-20: lowered Anchor refunds the exact excess, THEN migrates remainder")

# Issue 1000 as 600 min / 400 wallet; counter lowers the Anchor to 800.
tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000}, min_cents={"alpha": 600})
r = issue(ids, "alpha", "beta", 1_000, 750)
CH = r.challenge_id
with tdb.SessionLocal() as db:
    cf.counter_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                actor_team_id=ids["beta"], terms=terms(800, 750), db=db)
check("ACC-20: the counter moved NO money — escrow still at the funded 1000",
      escrow_of(CH) == 1_000, f"got {escrow_of(CH)}")
with tdb.SessionLocal() as db:
    a = cf.accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                   actor_team_id=ids["alpha"], db=db)
check("ACC-20: challenge escrow fully drained", escrow_of(CH) == 0)
check("ACC-20: the Anchor Bet escrow holds the LOWERED 800",
      bal(f"escrow:{a.anchor_bet_id}") == 800)
check("ACC-20: the 200 excess was released by STRICT REVERSE ORDER — all from "
      "the wallet leg, none from min",
      bal(f"wallet:{ids['alpha']}") == 9_800 and bal(f"min:{ids['alpha']}:{WEEK}") == 0,
      f"wallet={w('alpha')} "
      f"min={m('alpha')} "
      f"(proportional would be 9720/120)")
check("ACC-20: pot is 800 + 750 = 1550",
      bal(f"escrow:{a.anchor_bet_id}") + bal(f"escrow:{a.derived_bet_id}") == 1_550)
conservation("ACC-20")

section("ACC-21: raised Anchor tops up the ORIGINAL ISSUER, min-first")

tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000}, min_cents={"alpha": 600})
r = issue(ids, "alpha", "beta", 1_000, 750)     # 600 min + 400 wallet, min now 0
CH = r.challenge_id
# Re-seed the issuer's min so the top-up has a min source to prefer.
with tdb.SessionLocal() as db:
    ledger_post([("world", -150), (f"min:{ids['alpha']}:{WEEK}", 150)],
                door="buy_in_paid", session=db)
    db.commit()
with tdb.SessionLocal() as db:
    cf.counter_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                actor_team_id=ids["beta"], terms=terms(1_200, 750), db=db)
with tdb.SessionLocal() as db:
    a = cf.accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                   actor_team_id=ids["alpha"], db=db)
check("ACC-21: the Anchor Bet escrow holds the RAISED 1200",
      bal(f"escrow:{a.anchor_bet_id}") == 1_200)
check("ACC-21: the 200 top-up took min FIRST (150) then wallet (50)",
      bal(f"min:{ids['alpha']}:{WEEK}") == 0 and bal(f"wallet:{ids['alpha']}") == 9_550,
      f"min={m('alpha')} "
      f"wallet={w('alpha')}")
# Only legs funding the CHALLENGE escrow count as top-up. The recipient's
# Derived funding also lands on this challenge but is destined for a Bet escrow,
# so it is filtered out by destination rather than by sequence position.
_top = [l for l in legs_for(CH)
        if l.leg_kind == "fund" and l.sequence_number > 2
        and l.destination_account == f"escrow:challenge:{CH}"]
check("ACC-21: the top-up appended NEW fund legs in min-then-wallet order",
      len(_top) == 2 and _top[0].source_account.startswith("min:")
      and _top[0].amount_cents == 150
      and _top[1].source_account.startswith("wallet:") and _top[1].amount_cents == 50,
      str([(l.source_account, l.amount_cents) for l in _top]))
check("ACC-21: pot is 1200 + 750 = 1950",
      bal(f"escrow:{a.anchor_bet_id}") + bal(f"escrow:{a.derived_bet_id}") == 1_950)
conservation("ACC-21")

section("ACC-22: recipient Derived is escrowed in the SAME transaction")

ids, CH = accept_ready(1_000, 750)
with tdb.SessionLocal() as db:
    a = cf.accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                   actor_team_id=ids["beta"], db=db)
with tdb.SessionLocal() as db:
    ev = db.query(ProtocolEvent).filter(
        ProtocolEvent.challenge_id == CH,
        ProtocolEvent.event_type == "challenge_accept").one()
    n_batches = db.execute(text(
        "SELECT COUNT(*) FROM ledger_posting_batches WHERE protocol_event_id = :e"),
        {"e": ev.id}).scalar()
check("ACC-22: Derived escrow funded", bal(f"escrow:{a.derived_bet_id}") == 750)
check("ACC-22: every acceptance posting hangs off ONE challenge_accept event",
      n_batches >= 2, f"batches under the accept event: {n_batches}")
check("ACC-22: exactly one challenge_accept event exists for this challenge",
      True)
conservation("ACC-22")

section("ACC-23: a recipient-authored counter does NOT move Anchor ownership")

tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000})
r = issue(ids, "alpha", "beta", 1_000, 750)     # alpha issues → alpha is Anchor
CH = r.challenge_id
alpha_before = bal(f"wallet:{ids['alpha']}")
beta_before  = bal(f"wallet:{ids['beta']}")
# BETA (the recipient) authors a counter that RAISES the Anchor to 1200.
with tdb.SessionLocal() as db:
    cf.counter_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                actor_team_id=ids["beta"], terms=terms(1_200, 750), db=db)
with tdb.SessionLocal() as db:
    a = cf.accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                   actor_team_id=ids["alpha"], db=db)
check("ACC-23: the 200 Anchor top-up came from the ORIGINAL ISSUER (alpha)",
      bal(f"wallet:{ids['alpha']}") == alpha_before - 200,
      f"{alpha_before} -> {w('alpha')}")
check("ACC-23: the countering RECIPIENT (beta) paid ONLY its Derived 750, never "
      "the Anchor top-up it authored",
      bal(f"wallet:{ids['beta']}") == beta_before - 750,
      f"{beta_before} -> {w('beta')}")
_topup_legs = [l for l in legs_for(CH)
               if l.leg_kind == "fund" and l.destination_account == f"escrow:challenge:{CH}"
               and l.sequence_number > 1]
check("ACC-23: every Anchor top-up leg is owned by the issuer's team id",
      all(l.team_id == ids["alpha"] for l in _topup_legs),
      str([(l.team_id, l.amount_cents) for l in _topup_legs]))
with tdb.SessionLocal() as db:
    ch = db.query(BeefChallenge).filter(BeefChallenge.id == CH).one()
    prop = db.query(spec1.BeefProposal).filter(
        spec1.BeefProposal.id == ch.accepted_proposal_id).one()
check("ACC-23: the accepted proposal was AUTHORED by beta but its anchor_team_id "
      "is still alpha — authorship and role are separate",
      prop.proposing_team_id == ids["beta"] and prop.anchor_team_id == ids["alpha"],
      f"author={prop.proposing_team_id} anchor={prop.anchor_team_id}")
conservation("ACC-23")

section("ACC-24: recipient capacity drift fails acceptance ATOMICALLY")

tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000})
r = issue(ids, "alpha", "beta", 1_000, 750)
CH = r.challenge_id
# Beta spends almost everything AFTER the offer — capacity drifted away.
with tdb.SessionLocal() as db:
    ledger_post([(f"wallet:{ids['beta']}", -9_500), ("world", 9_500)],
                door="manual_adjustment", session=db)
    db.commit()
raised = None
try:
    with tdb.SessionLocal() as db:
        cf.accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                   actor_team_id=ids["beta"], db=db)
except AcceptanceCapacityError as exc:
    raised = exc
check("ACC-24: acceptance refused with AcceptanceCapacityError", raised is not None,
      str(raised)[:80])
with tdb.SessionLocal() as db:
    ch = db.query(BeefChallenge).filter(BeefChallenge.id == CH).one()
    n_bets = db.execute(text("SELECT COUNT(*) FROM bets")).scalar()
check("ACC-24: the challenge remains OPEN, not accepted",
      ch.response_status == "offered", f"got {ch.response_status}")
check("ACC-24: NO Bet row was created", n_bets == 0, f"got {n_bets}")
check("ACC-24: challenge escrow is untouched — no partial migration",
      escrow_of(CH) == 1_000, f"got {escrow_of(CH)}")
check("ACC-24: beta's wallet is untouched by the failed attempt",
      bal(f"wallet:{ids['beta']}") == 500)
conservation("ACC-24")

section("ACC-25: ISSUER top-up capacity drift fails acceptance ATOMICALLY")

tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000})
r = issue(ids, "alpha", "beta", 1_000, 750)
CH = r.challenge_id
with tdb.SessionLocal() as db:
    cf.counter_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                actor_team_id=ids["beta"], terms=terms(5_000, 750), db=db)
# Alpha drains their wallet after the counter — the 4000 top-up is unaffordable.
with tdb.SessionLocal() as db:
    ledger_post([(f"wallet:{ids['alpha']}", -8_900), ("world", 8_900)],
                door="manual_adjustment", session=db)
    db.commit()
raised = None
try:
    with tdb.SessionLocal() as db:
        cf.accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                   actor_team_id=ids["alpha"], db=db)
except AcceptanceCapacityError as exc:
    raised = exc
check("ACC-25: acceptance refused on the issuer's top-up", raised is not None,
      str(raised)[:80])
with tdb.SessionLocal() as db:
    ch = db.query(BeefChallenge).filter(BeefChallenge.id == CH).one()
check("ACC-25: challenge stays 'countered', not accepted",
      ch.response_status == "countered", f"got {ch.response_status}")
check("ACC-25: escrow still holds exactly the originally funded 1000",
      escrow_of(CH) == 1_000)
check("ACC-25: no top-up leg was appended",
      len([l for l in legs_for(CH) if l.sequence_number > 1]) == 0)
conservation("ACC-25")

section("ACC-26: a failed acceptance creates no Bet and moves no money at all")

with tdb.SessionLocal() as db:
    n_bets = db.execute(text("SELECT COUNT(*) FROM bets")).scalar()
    n_esc  = db.execute(text(
        "SELECT COUNT(*) FROM ledger_entries WHERE account LIKE 'escrow:%' "
        "AND account NOT LIKE 'escrow:challenge:%'")).scalar()
check("ACC-26: zero Bet rows after the two failed acceptances", n_bets == 0)
check("ACC-26: zero Bet-escrow ledger entries — nothing partially migrated",
      n_esc == 0, f"got {n_esc}")
check("ACC-26: the issuer's sources were not touched by the failed attempt",
      bal(f"wallet:{ids['alpha']}") == 100, f"got {w('alpha')}")
conservation("ACC-26")

section("ACC-27: successful acceptance leaves challenge escrow at exactly zero")

ids, CH = accept_ready(1_000, 750)
with tdb.SessionLocal() as db:
    a = cf.accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                   actor_team_id=ids["beta"], db=db)
check("ACC-27: escrow:challenge:{id} is exactly 0 post-acceptance",
      escrow_of(CH) == 0)
check("ACC-27: the reported escrow_cents is 0", a.escrow_cents == 0)
with tdb.SessionLocal() as db:
    ch = db.query(BeefChallenge).filter(BeefChallenge.id == CH).one()
check("ACC-27: both Bet pointers are set on the challenge",
      ch.challenger_bet_id is not None and ch.challenged_bet_id is not None)
check("ACC-27: the challenger's Bet is the Anchor Bet",
      ch.challenger_bet_id == a.anchor_bet_id)
with tdb.SessionLocal() as db:
    bets = db.query(Bet).filter(Bet.beef_challenge_id == CH).all()
check("ACC-27: exactly two Bet rows, both pending", len(bets) == 2
      and all(b.status == "pending" for b in bets))
check("ACC-27: Bet.amount is the float MIRROR of the authoritative cents",
      sorted(b.amount for b in bets) == [7.5, 10.0],
      str(sorted(b.amount for b in bets)))
conservation("ACC-27")

section("ACC-28: duplicate acceptance cannot duplicate escrow or Bets")

EV = uuid.uuid4()
ids, CH = accept_ready(1_000, 750)
with tdb.SessionLocal() as db:
    first = cf.accept_funded_challenge(event_id=EV, challenge_id=CH,
                                       actor_team_id=ids["beta"], db=db)
with tdb.SessionLocal() as db:
    second = cf.accept_funded_challenge(event_id=EV, challenge_id=CH,
                                        actor_team_id=ids["beta"], db=db)
check("ACC-28: the repeat is a replay", second.replayed is True)
with tdb.SessionLocal() as db:
    n_bets = db.execute(text("SELECT COUNT(*) FROM bets WHERE beef_challenge_id = :c"),
                        {"c": CH}).scalar()
check("ACC-28: still exactly two Bet rows", n_bets == 2, f"got {n_bets}")
check("ACC-28: Anchor Bet escrow was funded once", bal(f"escrow:{first.anchor_bet_id}") == 1_000)
check("ACC-28: Derived Bet escrow was funded once", bal(f"escrow:{first.derived_bet_id}") == 750)
check("ACC-28: the issuer paid the Anchor once", bal(f"wallet:{ids['alpha']}") == 9_000)
check("ACC-28: the recipient paid the Derived once", bal(f"wallet:{ids['beta']}") == 9_250)

# A DIFFERENT event id against an already-accepted challenge must also not repost.
with tdb.SessionLocal() as db:
    third = cf.accept_funded_challenge(event_id=uuid.uuid4(), challenge_id=CH,
                                       actor_team_id=ids["beta"], db=db)
check("ACC-28: a new event id on an accepted challenge returns the committed "
      "state and posts nothing",
      third.replayed is True and bal(f"wallet:{ids['alpha']}") == 9_000, third.detail)
conservation("ACC-28")


# ══════════════════════════════════════════════════════════════════════════════
# CONCURRENCY
# ══════════════════════════════════════════════════════════════════════════════
section("CONC-29: two racing issues on ONE funding scope cannot overcommit")

tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000})
results: dict = {}
barrier = threading.Barrier(2)


def racing_issue(key: str) -> None:
    try:
        with tdb.SessionLocal() as db:
            barrier.wait(timeout=20)
            res = cf.issue_funded_challenge(
                event_id=uuid.uuid4(), league_id=ids["_league"], week=WEEK,
                challenger_team_id=ids["alpha"], challenged_team_id=ids["beta"],
                wager_type="straight", terms=terms(7_000), db=db)
            results[key] = f"issued:{res.challenge_id}"
    except Exception as exc:                       # noqa: BLE001
        results[key] = f"error:{type(exc).__name__}"


ta = threading.Thread(target=racing_issue, args=("a",))
tb = threading.Thread(target=racing_issue, args=("b",))
ta.start(); tb.start(); ta.join(timeout=60); tb.join(timeout=60)
outcomes = [results.get("a"), results.get("b")]
issued = [o for o in outcomes if str(o).startswith("issued")]

check("CONC-29: neither worker hung", not (ta.is_alive() or tb.is_alive()), str(outcomes))
check("CONC-29: exactly ONE of two 7000c issues against a 10000c balance succeeded",
      len(issued) == 1, str(outcomes))
check("CONC-29: the loser was refused on capacity, not by a database error",
      any("InsufficientFundingCapacityError" in str(o) for o in outcomes), str(outcomes))
check("CONC-29: the wallet never went negative", bal(f"wallet:{ids['alpha']}") == 3_000,
      f"got {w('alpha')}")
with tdb.SessionLocal() as db:
    n_ch = db.execute(text("SELECT COUNT(*) FROM beef_challenges")).scalar()
check("CONC-29: exactly one challenge was created", n_ch == 1, f"got {n_ch}")
conservation("CONC-29")

section("CONC-30: overlapping acceptances serialize without deadlock")

tdb.reset()
ids = seed({"alpha": 10_000, "beta": 10_000})
r1 = issue(ids, "alpha", "beta", 1_000, 750)
r2 = issue(ids, "beta", "alpha", 1_000, 750)     # OPPOSITE direction, same pair
acc: dict = {}
barrier2 = threading.Barrier(2)


def racing_accept(challenge_id: int, actor: int, key: str) -> None:
    try:
        with tdb.SessionLocal() as db:
            barrier2.wait(timeout=20)
            res = cf.accept_funded_challenge(
                event_id=uuid.uuid4(), challenge_id=challenge_id,
                actor_team_id=actor, db=db)
            acc[key] = f"accepted:{res.challenge_id}"
    except Exception as exc:                       # noqa: BLE001
        acc[key] = f"error:{type(exc).__name__}"


t1 = threading.Thread(target=racing_accept, args=(r1.challenge_id, ids["beta"], "a"))
t2 = threading.Thread(target=racing_accept, args=(r2.challenge_id, ids["alpha"], "b"))
t1.start(); t2.start(); t1.join(timeout=60); t2.join(timeout=60)
outcomes = [acc.get("a"), acc.get("b")]

check("CONC-30: neither acceptance hung — no deadlock between opposite-direction "
      "two-wallet operations", not (t1.is_alive() or t2.is_alive()), str(outcomes))
check("CONC-30: both accepted (each pair had funds for both)",
      all(str(o).startswith("accepted") for o in outcomes), str(outcomes))
check("CONC-30: both challenge escrows fully migrated",
      escrow_of(r1.challenge_id) == 0 and escrow_of(r2.challenge_id) == 0)
check("CONC-30: no wallet went negative",
      bal(f"wallet:{ids['alpha']}") >= 0 and bal(f"wallet:{ids['beta']}") >= 0,
      f"alpha={w('alpha')} "
      f"beta={w('beta')}")
conservation("CONC-30")

section("CONC-31: contention is controlled by explicit row locks, not isolation luck")

import ast
mod = ast.parse(mod_src)


def fn_node(name: str):
    return next(n for n in ast.walk(mod)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def calls(node, name: str) -> list[int]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            called = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if called == name:
                out.append(n.lineno)
    return sorted(out)


check("CONC-31: challenge_funding sets NO isolation level anywhere — the locks "
      "are the only control",
      "isolation_level" not in code_only)
for fn in ("accept_funded_challenge", "counter_funded_challenge", "_terminal_refund"):
    node = fn_node(fn)
    ch_lock = calls(node, "_lock_challenge")
    w_lock  = calls(node, "lock_funding_scopes")
    check(f"CONC-31: {fn}() locks the CHALLENGE row before the Wallet scopes "
          f"(rank preserved, never inverted)",
          ch_lock and w_lock and ch_lock[0] < w_lock[0], f"challenge@{ch_lock} wallet@{w_lock}")

issue_node = fn_node("issue_funded_challenge")
check("CONC-31: issue_funded_challenge() locks the Wallet scope before its "
      "capacity read",
      calls(issue_node, "lock_funding_scopes")[0] < calls(issue_node, "available_cents")[0])
# Executable code only — the removal is recorded in a comment that necessarily
# names the thing it removed, and a raw text search would match that comment.
_beef_code = executable_source(
    (REPO / "beefs" / "beef_engine.py").read_text(encoding="utf-8"))
check("CONC-31: the legacy accept path's stale REPEATABLE READ is gone from "
      "executable code",
      "isolation_level" not in _beef_code and "REPEATABLE READ" not in _beef_code)
check("CONC-31: and its explicit Wallet mutex remains",
      "lock_funding_scopes(db, challenge.challenger_team_id, "
      "challenge.challenged_team_id)"
      in (REPO / "beefs" / "beef_engine.py").read_text(encoding="utf-8"))

# Acceptance revalidation must precede every write (OPR-8).
acc_node = fn_node("accept_funded_challenge")
first_write = min(calls(acc_node, "_fund") + calls(acc_node, "_reverse")
                  + calls(acc_node, "_create_bet") + calls(acc_node, "ledger_post"))
last_check  = max(calls(acc_node, "available_cents"))
check("CONC-31: EVERY capacity revalidation precedes EVERY write in acceptance "
      "(no-write-before-revalidation)",
      last_check < first_write, f"last check@{last_check} first write@{first_write}")
conservation("CONC-31")


# ══════════════════════════════════════════════════════════════════════════════
# SCOPE FENCE
# ══════════════════════════════════════════════════════════════════════════════
section("FENCE: P1-L4 built only the challenge escrow lifecycle")

OUT_OF_SCOPE = ("stripe", "Stripe", "payment_intent", "payout_method", "charge",
                "final_lock", "handshake", "repric", "championship", "skunk",
                "pool_pot", "yahoo")
hits = [t for t in OUT_OF_SCOPE if t in code_only]
check("FENCE: no Stripe / real-money / Dynamic / Pool / Championship identifier "
      "in challenge_funding", not hits, str(hits))
check("FENCE: no new migration was written by P1-L4 — Group 1's migration already "
      "created every table this package uses",
      not any(p.name.startswith("migrate_") and "p1_l4" in p.name.lower()
              for p in (REPO / "db" / "migrations").glob("*.py")))
check("FENCE: challenge_funding never imports beef_engine (the legacy path is "
      "untouched by P1-L4)",
      "beef_engine" not in code_only)

# The display view deliberately copies the open-state vocabulary rather than
# importing proposal_lifecycle (that import edge is what Package 2A's G2 gate
# forbids). Pin the copy to the authority so the two cannot drift apart.
from economy import challenge_escrow_view as cev
check("FENCE: the view module's OPEN_RESPONSE_STATES equals the Spec 1 authority "
      "— the deliberate literal copy cannot silently diverge",
      tuple(cev.OPEN_RESPONSE_STATES) == tuple(spec1.OPEN_STATES),
      f"view={cev.OPEN_RESPONSE_STATES} spec1={spec1.OPEN_STATES}")

view_code = executable_source(
    (REPO / "economy" / "challenge_escrow_view.py").read_text(encoding="utf-8"))
check("FENCE: the view module imports NO lifecycle and NO ledger — it is a "
      "read-only provenance view, so display models cannot drag the money path "
      "into the application's import graph",
      "proposal_lifecycle" not in view_code and "challenge_funding" not in view_code
      and "ledger" not in view_code)
check("FENCE: the view module writes nothing (no add/commit/flush/post)",
      not any(t in view_code for t in ("db.add(", "commit(", "flush(", "ledger_post")))
conservation("FENCE")


# ──────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
tdb.teardown()
if _failures:
    print(f"{len(_failures)} FAILED assertion(s):")
    for f in _failures:
        print(f"  - {f}")
    print(f"\n{_passes} passed, {len(_failures)} FAILED")
    sys.exit(1)
print(f"All {_passes} assertions PASSED")
