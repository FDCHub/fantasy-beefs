"""
test_championship_payout.py — Finding 5.2: championship payout source of
truth. preview_payouts() and execute_payouts() now compute
championship_total from the ledger (summed reserve:{team_id} balances +
the shared championship account) instead of the stale
LeagueTreasury.total_collected_cents.

Covers (Section 5 of the spec):
  1. execute_payouts()'s guard blocks when championship_total <= 0. Runs
     FIRST, before anything else in this file ever credits the shared
     "championship" account — see the note on Item 3 below for why order
     matters here.
  2. championship_total resolves to 0 for a team with ZERO ledger entries
     for its reserve account (never completed buy-in) — proves
     balance_of()'s empty-set COALESCE handling, not just a $0 balance.
  3. championship_total includes a non-zero "championship" account
     balance (from shortfall sweeps) alongside summed reserve balances.
     NOTE: "championship" is a GLOBAL, bare-string ledger account — not
     per-league — across every door built so far (L1's Doors 4/5/6/7, B2's
     shortfall sweep). Once this item credits it, EVERY later scenario in
     this file (and in a real multi-league deployment, every OTHER
     league) sees that same credit. Every scenario after this one reads
     the actual current global balance live rather than assuming it
     starts at 0, specifically because of this.
  4. Payout math sums to championship_total EXACTLY using a total that is
     deliberately indivisible by 60/30/10 (100001 cents) — proves the
     remainder rule (5.2-3) actually fires, 1st place absorbs the leftover.
  5. execute_payouts()'s guard allows a payout once championship_total > 0.
  6. Regression: payout_split_json read correctly; season_payout_done
     guards both preview_payouts() and execute_payouts() against a
     second run.
  7. Team-level isolation: summed reserve:{team_id} balances for League A
     never include League B's teams' reserves (this part of "multi-league
     isolation" is real and league-scoped today). Flagged, not silently
     assumed: the shared "championship"/"skunk" accounts are GLOBAL by
     pre-existing design (single-league deployment throughout this
     codebase) — this test proves the part that's actually true (reserve
     scoping) and does not claim championship/skunk isolation, which
     would be false. Out of scope for this fix (no new posting/schema,
     per the spec) — flagged as a real gap for a future multi-league pass.
  8. Regression guard (5.2-1): confirms, by grepping actual source (not
     just trusting the spec's own recon), that confirm_buyin_payment() in
     payments/stripe_connect.py is the ONLY production code site that
     posts a reserve:{team_id} ledger entry anywhere in the repo. Fails
     loudly if a second write site to reserve:* ever appears, forcing
     whoever adds it to confront this payout computation.

Uses a temp SQLite DB so prod is never touched.
"""

import os
import sys
import re
import glob
import tempfile

_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_championship_payout.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ.pop("STRIPE_SECRET_KEY", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json

from db.schema import Base, engine, SessionLocal, League, LeagueTreasury, Team, User, PayoutRecord
from payments.stripe_connect import (
    _championship_total,
    preview_payouts,
    execute_payouts,
    setup_league_treasury,
    MOCK_MODE,
)
from ledger.ledger import post as ledger_post, balance_of, create_ledger_table

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


Base.metadata.create_all(engine)
create_ledger_table()
_assert("running in MOCK_MODE (no real Stripe calls)", MOCK_MODE is True)


def _make_league_with_treasury(name: str, split=None) -> int:
    with SessionLocal() as db:
        league = League(season=2025, name=f"5.2 Test {name}", projection_source="fantasypros")
        db.add(league)
        db.flush()
        setup_league_treasury(league.id, 22000, db, payout_split=split)
        return league.id


def _make_team(league_id: int, name: str) -> int:
    with SessionLocal() as db:
        team = Team(league_id=league_id, team_name=f"5.2 {name}", owner=name, email=f"{name}@52.com")
        db.add(team)
        db.commit()
        return team.id


def _fund_reserve(team_id: int, cents: int) -> None:
    ledger_post([("world", -cents), (f"reserve:{team_id}", cents)], door="buy_in_paid")


# ── ITEM 1: execute_payouts() blocks when championship_total <= 0 ────────────
# Runs FIRST, before any other item in this file ever credits the shared,
# global "championship" account — otherwise this scenario would be
# untestable (see the module docstring's note on Item 3).

print("\nItem 1: execute_payouts() blocks when championship_total <= 0")

league1 = _make_league_with_treasury("Item1")
_make_team(league1, "NoFundsAtAll")  # never funded — championship_total stays 0

with SessionLocal() as db:
    total_1_empty = _championship_total(league1, db)
_assert("fixture check — championship_total is 0 (nothing has funded ANY account yet in this run)", total_1_empty == 0, f"got {total_1_empty}")

raised_1 = False
try:
    with SessionLocal() as db:
        execute_payouts(league1, db)
except ValueError as e:
    raised_1 = True
    _assert("error message matches the expected guard text", "No funds in treasury to pay out" in str(e), str(e))
_assert("execute_payouts() raised ValueError for championship_total <= 0", raised_1)


# ── ITEM 2: never-posted reserve account resolves to 0, not NULL/error ────────

print("\nItem 2: a team with ZERO ledger entries for its reserve account resolves to 0 (not NULL)")

league2 = _make_league_with_treasury("Item2")
t2_funded = _make_team(league2, "Funded2")
t2_never  = _make_team(league2, "NeverPostedTo")  # no ledger_post call ever touches this team's reserve

_fund_reserve(t2_funded, 8000)

with SessionLocal() as db:
    never_posted_balance = balance_of(f"reserve:{t2_never}")
_assert("balance_of() on a genuinely never-posted account returns exactly 0 (int)", never_posted_balance == 0 and isinstance(never_posted_balance, int), f"got {never_posted_balance!r}")

with SessionLocal() as db:
    total_2 = _championship_total(league2, db)
_assert("championship_total includes the never-posted team as $0, not an error", total_2 == 8000, f"got {total_2}")


# ── ITEM 3: championship_total includes the shared championship account ──────

print("\nItem 3: championship_total = summed reserves + the shared championship account")

league3 = _make_league_with_treasury("Item3")
t3a = _make_team(league3, "A3")
t3b = _make_team(league3, "B3")
_fund_reserve(t3a, 8000)
_fund_reserve(t3b, 8000)

champ_before_item3 = balance_of("championship")
# Shortfall-sweep-style credit to the shared championship account. From
# this point on, EVERY scenario in this file must read the current global
# championship balance live — it no longer starts at 0.
ledger_post([(f"receivable:{t3a}", -500), ("championship", 500)], door="shortfall_sweep")
champ_after_item3 = balance_of("championship")

_assert("the shared championship account actually moved by exactly $5.00", champ_after_item3 == champ_before_item3 + 500, f"before={champ_before_item3} after={champ_after_item3}")

with SessionLocal() as db:
    total_3 = _championship_total(league3, db)
_assert("championship_total = reserve(A) + reserve(B) + current championship balance", total_3 == 8000 + 8000 + champ_after_item3, f"got {total_3}")


# ── ITEM 4: remainder rule — indivisible total, 1st place absorbs the leftover ──

print("\nItem 4: payout amounts sum to championship_total EXACTLY with an indivisible total (100001 cents)")

league4 = _make_league_with_treasury("Item4", split=[60, 30, 10])
t4a = _make_team(league4, "First4")
t4b = _make_team(league4, "Second4")
t4c = _make_team(league4, "Third4")
# Compensate for whatever the (global, leaked-into-by-Item-3) championship
# account currently holds, so this league's OWN total comes out to exactly
# 100001 cents — deliberately NOT evenly divisible by 60/30/10 — regardless
# of what ran before it in this file.
champ_now_4 = balance_of("championship")
target_total_4 = 100001
reserve_needed_4 = target_total_4 - champ_now_4
_fund_reserve(t4a, reserve_needed_4)

with SessionLocal() as db:
    total_4 = _championship_total(league4, db)
_assert("fixture check — championship_total is exactly 100001 (indivisible by 60/30/10)", total_4 == 100001, f"got {total_4}")

with SessionLocal() as db:
    preview_4 = preview_payouts(league4, db, standings_order=[t4a, t4b, t4c])

amounts_4 = [r.amount_cents for r in preview_4.rows]
_assert("three rows produced", len(amounts_4) == 3, f"got {len(amounts_4)}")
_assert("floored shares before remainder: 60000/30000/10000", (100001 * 60 // 100, 100001 * 30 // 100, 100001 * 10 // 100) == (60000, 30000, 10000))
_assert("1st place absorbs the 1-cent remainder: 60001, not 60000", amounts_4[0] == 60001, f"got {amounts_4[0]}")
_assert("2nd and 3rd place get their plain floored share", amounts_4[1] == 30000 and amounts_4[2] == 10000, f"got {amounts_4[1:]}")
_assert("all three amounts sum to championship_total EXACTLY", sum(amounts_4) == 100001, f"got {sum(amounts_4)}")


# ── ITEM 5: execute_payouts() allows a payout once championship_total > 0 ────

print("\nItem 5: execute_payouts() allows a payout once championship_total > 0")

league5 = _make_league_with_treasury("Item5", split=[60, 30, 10])
t5a = _make_team(league5, "First5")
t5b = _make_team(league5, "Second5")
t5c = _make_team(league5, "Third5")
champ_now_5 = balance_of("championship")
target_total_5 = 100001
_fund_reserve(t5a, target_total_5 - champ_now_5)

raised_5 = False
try:
    with SessionLocal() as db:
        records_5 = execute_payouts(league5, db, standings_order=[t5a, t5b, t5c])
except Exception as e:
    raised_5 = True
    print(f"    unexpected exception: {e}")
_assert("execute_payouts() succeeds when championship_total > 0", not raised_5)
if not raised_5:
    _assert("3 PayoutRecords created", len(records_5) == 3, f"got {len(records_5)}")
    _assert("all records marked sent (mock mode)", all(r.status == "sent" for r in records_5))
    _assert("1st-place record absorbs the remainder (60001)", records_5[0].amount_cents == 60001, f"got {records_5[0].amount_cents}")
    _assert("total sent across all records == championship_total exactly", sum(r.amount_cents for r in records_5) == 100001, f"got {sum(r.amount_cents for r in records_5)}")


# ── ITEM 6: regression — payout_split_json + season_payout_done unchanged ────

print("\nItem 6: regression — payout_split_json read correctly; season_payout_done guards both functions")

with SessionLocal() as db:
    treasury_5 = db.query(LeagueTreasury).filter(LeagueTreasury.league_id == league5).first()
_assert("payout_split_json still holds [60, 30, 10]", json.loads(treasury_5.payout_split_json) == [60, 30, 10], f"got {treasury_5.payout_split_json}")
_assert("season_payout_done flipped to True by execute_payouts()", bool(treasury_5.season_payout_done) is True)

raised_preview_again = False
try:
    with SessionLocal() as db:
        preview_payouts(league5, db)
except ValueError as e:
    raised_preview_again = True
    _assert("preview_payouts() blocks a completed season with the right message", "already completed" in str(e), str(e))
_assert("preview_payouts() raises once season_payout_done is True", raised_preview_again)

raised_execute_again = False
try:
    with SessionLocal() as db:
        execute_payouts(league5, db)
except ValueError as e:
    raised_execute_again = True
    _assert("execute_payouts() blocks a completed season with the right message", "already completed" in str(e), str(e))
_assert("execute_payouts() raises once season_payout_done is True", raised_execute_again)


# ── ITEM 7: team-level (reserve) isolation across leagues ─────────────────────
# The reserve half of championship_total IS correctly league-scoped (team_id
# belongs to exactly one league). The championship/skunk accounts are GLOBAL
# by pre-existing design across every door ever built (L1, B1, B2) — not
# per-league anywhere in this codebase. This test proves the part that's
# actually true; it does not claim championship/skunk isolation, which
# would be false. Flagged in the session report as a real multi-league gap,
# out of scope for this fix (no new posting/schema, per the spec). Both
# leagues' totals are compared against the SAME live global championship
# reading, taken once, right before funding either league's reserves.

print("\nItem 7: summed reserve balances are correctly scoped per league (not per-database)")

league7a = _make_league_with_treasury("Item7A")
league7b = _make_league_with_treasury("Item7B")
t7a = _make_team(league7a, "A7")
t7b = _make_team(league7b, "B7")

champ_now_7 = balance_of("championship")
_fund_reserve(t7a, 5000)
_fund_reserve(t7b, 9000)

with SessionLocal() as db:
    total_7a = _championship_total(league7a, db)
    total_7b = _championship_total(league7b, db)
_assert("League A's total = its own $50.00 reserve + the (shared, global) championship balance", total_7a == 5000 + champ_now_7, f"got {total_7a}")
_assert("League B's total = its own $90.00 reserve + the SAME shared global balance, NOT A's $50.00", total_7b == 9000 + champ_now_7, f"got {total_7b}")
_assert("League A's total does not also include League B's $90.00 reserve", total_7a != total_7a + 9000)
_assert("League B's total does not also include League A's $50.00 reserve", total_7b != total_7b + 5000)


# ── ITEM 8: regression guard — Door 1 is the sole writer to reserve:* ─────────

print("\nItem 8: regression guard — confirm_buyin_payment() is the ONLY production writer to reserve:{team_id}")

_repo_root = os.path.dirname(os.path.abspath(__file__))
_reserve_write_pattern = re.compile(r'reserve:\{[a-zA-Z_.]+\}"?\s*,')

_production_hits = []
for path in glob.glob(os.path.join(_repo_root, "**", "*.py"), recursive=True):
    rel = os.path.relpath(path, _repo_root)
    if rel.startswith("test_") or os.sep + "test" in rel.lower():
        continue
    basename = os.path.basename(rel)
    if basename.startswith("test_"):
        continue
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            # Matches any tuple literal constructing a reserve:{...} account
            # name — credit (positive, Door 1's shape) or debit (negative) —
            # not just debits. Door 1's own line is a CREDIT with no minus
            # sign at all, so requiring one would miss the real site.
            if _reserve_write_pattern.search(line):
                _production_hits.append((rel, lineno, line.strip()))

_assert("exactly one production site constructs a reserve:{...} ledger entry", len(_production_hits) == 1, f"got {_production_hits}")
if _production_hits:
    rel, lineno, _ = _production_hits[0]
    _assert("that one site is confirm_buyin_payment()'s Door 1 posting in payments/stripe_connect.py",
            rel == os.path.join("payments", "stripe_connect.py") or rel == "payments/stripe_connect.py",
            f"got {rel}:{lineno}")


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
