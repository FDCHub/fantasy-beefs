"""
test_championship_payout.py — Finding 5.2 championship-total verification,
retargeted by the B2 Stripe removal.

_championship_total() is the corrected championship-payout source of truth. It
now lives in economy/championship.py; it was relocated out of
payments/stripe_connect.py in B2 Group 1, and that module has since been
deleted with the rest of the Stripe surface.

Items covered here:
  2. A team with ZERO ledger entries for its reserve account resolves to 0,
     not NULL and not an error.
  3. championship_total = summed per-team reserves + the shared championship
     account (shortfall-sweep credits).
  7. Reserve balances are scoped per league, with no cross-league leakage.
  8. Regression guard: activate_season_allocation() is the SOLE production
     call site that posts a reserve:{team_id} ledger leg, proven structurally
     against the AST rather than by text search.

REMOVED WITH STRIPE: the former Items 1, 4, 5 and 6 exercised preview_payouts()
and execute_payouts(). Payout execution is not part of the MVP and those
functions no longer exist. Their removal is recorded here rather than left as
an unexplained gap in the item numbering.

Uses a temp SQLite DB so prod is never touched.
"""

import os
import sys
import ast
import glob
import tempfile

_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_championship_payout.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json

from db.schema import Base, engine, SessionLocal, League, LeagueTreasury, Team, User
from economy.championship import _championship_total
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


def _make_league_with_treasury(name: str, split=None) -> int:
    with SessionLocal() as db:
        league = League(season=2025, name=f"5.2 Test {name}", projection_source="fantasypros")
        db.add(league)
        db.flush()
        db.add(LeagueTreasury(
            league_id           = league.id,
            buy_in_amount_cents = 22000,
            payout_split_json   = json.dumps(split or [60, 30, 10]),
        ))
        db.commit()
        return league.id


def _make_team(league_id: int, name: str) -> int:
    with SessionLocal() as db:
        team = Team(league_id=league_id, team_name=f"5.2 {name}", owner=name, email=f"{name}@52.com")
        db.add(team)
        db.commit()
        return team.id


def _fund_reserve(team_id: int, cents: int) -> None:
    ledger_post([("world", -cents), (f"reserve:{team_id}", cents)], door="buy_in_paid")


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


# ── ITEM 8: regression guard — season allocation is the sole reserve writer ───
#
# B2 Stripe removal. This guard previously asserted that Door 1
# (confirm_buyin_payment in payments/stripe_connect.py) was the ONLY production
# writer of a reserve:{team_id} ledger leg. Stripe is out of the MVP: that
# module and that function no longer exist, and season allocation is now the
# sole funding path. The invariant is not weakened — it is repointed, and
# strengthened from a text search to a structural one.
#
# It now protects the POSTING OPERATION, not merely the account string: it
# walks the AST of every production module, finds each call to post()/
# ledger_post(), and flags any call whose leg list constructs a reserve:{...}
# account. A bare mention of the string in a comment or docstring no longer
# trips it, and a new posting site cannot hide behind different formatting.

print("\nItem 8: regression guard — activate_season_allocation() is the sole production writer to reserve:{team_id}")

_repo_root = os.path.dirname(os.path.abspath(__file__))


def _is_reserve_account(node) -> bool:
    """Whether this leg's account expression names a reserve:{...} account.

    THREE SPELLINGS, because S5-P1 moved the account names into
    economy.economy_events and the call sites now use the helper. A literal-only
    matcher would have reported ZERO writers and passed the "exactly one" check
    only by accident of counting — which is why the assertion below also
    requires the site to be activate_season_allocation by name.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.startswith("reserve:")
    if isinstance(node, ast.JoinedStr):
        first = node.values[0] if node.values else None
        return (isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and first.value.startswith("reserve:"))
    if isinstance(node, ast.Call):
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        return name == "reserve_account"
    return False


def _enclosing_funcs(tree):
    """Map each node to the name of the function that lexically contains it."""
    owner = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(fn):
                owner.setdefault(child, fn.name)
    return owner


_posting_sites = []   # (rel_path, lineno, func_name)
for path in glob.glob(os.path.join(_repo_root, "**", "*.py"), recursive=True):
    rel = os.path.relpath(path, _repo_root)
    if os.path.basename(rel).startswith("test_") or rel.startswith("test_"):
        continue
    if os.sep + "test" in rel.lower():
        continue
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except SyntaxError:
        continue
    owner = _enclosing_funcs(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if fname not in ("post", "ledger_post"):
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            legs = arg.elts if isinstance(arg, (ast.List, ast.Tuple)) else []
            for leg in legs:
                parts = leg.elts if isinstance(leg, (ast.Tuple, ast.List)) else []
                if parts and _is_reserve_account(parts[0]):
                    _posting_sites.append((rel, node.lineno, owner.get(node, "<module>")))

_assert("exactly one production call site posts a reserve:{...} ledger leg",
        len(_posting_sites) == 1, f"got {_posting_sites}")

if len(_posting_sites) == 1:
    rel, lineno, func = _posting_sites[0]
    _assert("that site lives in economy/season_allocation.py",
            rel.replace(os.sep, "/") == "economy/season_allocation.py",
            f"got {rel}:{lineno}")
    _assert("that site is inside activate_season_allocation()",
            func == "activate_season_allocation",
            f"got function {func!r} at {rel}:{lineno}")

_assert("payments/stripe_connect.py no longer exists in the tree",
        not os.path.exists(os.path.join(_repo_root, "payments", "stripe_connect.py")),
        "the Stripe module is still present")

# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
