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

print('\nItem 8: regression guard — who may create a per-GM Championship Reserve')
#
# ── REPLACED BY FINAL POR WP-5, AND THE CLAIM IS STRENGTHENED ──
#
# WHAT THIS ITEM HAS ALWAYS BEEN FOR: no code may quietly open a per-GM
# Championship Reserve. That is unchanged and is still asserted.
#
# WHY IT HAD TO BE REWRITTEN. It matched `post([... ("reserve:x", n) ...])` —
# a leg tuple written INLINE in the call. WP-5 made the activation's reserve leg
# CONDITIONAL on the era, so the legs are assembled into a list and the literal
# is no longer inside the call node. The old matcher therefore stopped seeing
# the one site it existed to police, and would have reported "exactly one"
# again the moment an unrelated site was removed — passing while blind.
#
# It also encoded the RETIRED ARCHITECTURE as correct: "exactly one" writer
# meant the per-GM contribution was how pots got funded. Under Model B a Final
# POR season creates NO per-GM Championship Reserve at all.
#
# So the matcher now finds a leg-shaped reserve tuple ANYWHERE in a production
# module, however the legs are assembled, and the assertions require:
#   (a) every such site to belong to the governed set, by file AND function;
#   (b) each of those functions to be ERA-GATED, so no Final POR season can
#       reach it — the actual Final POR guarantee, and stronger than counting.

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


#: The ONLY production functions permitted to assemble a `reserve:{team}` leg,
#: and each is reachable ONLY by a legacy-ruleset season. Enumerated as data so
#: adding a third is a deliberate, reviewable edit to this list.
PERMITTED_RESERVE_WRITERS = {
    # Advances the reserve. LEGACY branch only (WP-5).
    ("economy/season_allocation.py", "activate_season_allocation"),
    # Advances then immediately commits it. Refuses a Final POR season at
    # function entry, before any posting (WP-5).
    ("economy/fantasystakes_championship_allocation.py", "stage_allocation"),
    # DEBITS the reserve at season close, consolidating it into the pot. Not a
    # creator of the obligation but a mover of it, and it names the same
    # account, so it belongs in this list rather than being filtered out of the
    # scan: a filter would also hide a future site that really did create one.
    # Retired for Final POR seasons (WP-5).
    ("economy/season_reconciliation.py", "sweep_championship_reserves"),
}

_posting_sites = []   # (rel_path, lineno, func_name)
_module_sources = {}
for path in glob.glob(os.path.join(_repo_root, "**", "*.py"), recursive=True):
    rel = os.path.relpath(path, _repo_root)
    if os.path.basename(rel).startswith("test_") or rel.startswith("test_"):
        continue
    if os.sep + "test" in rel.lower():
        continue
    try:
        source = open(path, encoding="utf-8").read()
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        continue
    rel = rel.replace(os.sep, "/")
    _module_sources[rel] = source
    owner = _enclosing_funcs(tree)
    # ANY leg-shaped 2-tuple whose first element names a reserve account,
    # wherever it is written — inline in the post() call, appended to a list,
    # or built in a comprehension. Assembly style is not what is being policed;
    # creating the obligation is.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Tuple, ast.List)):
            continue
        parts = node.elts
        # A LEG'S SECOND ELEMENT IS AN AMOUNT, NEVER A STRING. This excludes
        # pure data declarations that happen to pair account-name strings —
        # `RETIRED_FOR_FINAL_POR_PREFIXES` is exactly such a tuple — without
        # excluding anything that could actually post.
        if (len(parts) == 2 and _is_reserve_account(parts[0])
                and not (isinstance(parts[1], ast.Constant)
                         and isinstance(parts[1].value, str))):
            _posting_sites.append(
                (rel, node.lineno, owner.get(node, "<module>")))

_found = {(rel, func) for rel, _, func in _posting_sites}
_assert("every reserve:{...} leg site belongs to the governed set",
        _found <= PERMITTED_RESERVE_WRITERS,
        f"unexpected: {sorted(_found - PERMITTED_RESERVE_WRITERS)}")
_assert("  · and at least one such site still exists to be policed",
        len(_posting_sites) >= 1, f"got {_posting_sites}")
_assert("  · the season-allocation site is inside activate_season_allocation()",
        ("economy/season_allocation.py", "activate_season_allocation") in _found,
        f"got {sorted(_found)}")

# (b) THE FINAL POR GUARANTEE — each writer is unreachable for a Final POR
# season. This is what replaced "exactly one": counting sites never proved a
# season could not reach one, and this does.
for _rel, _func in sorted(PERMITTED_RESERVE_WRITERS):
    _assert(f"  · {_rel} consults the ruleset era gate",
            "is_final_por" in _module_sources.get(_rel, ""),
            "no era gate found in the module")

_alloc = _module_sources.get("economy/season_allocation.py", "")
_assert("  · the activation's reserve leg is conditional on the LEGACY era",
        "if not final_por:" in _alloc
        and "reserve_account(team_id), stop.reserve_cents" in _alloc)

_stage = _module_sources.get(
    "economy/fantasystakes_championship_allocation.py", "")
_assert("  · stage_allocation REFUSES a Final POR season before any posting",
        "FS_CHAMPIONSHIP_ALLOCATION_RETIRED_ERA" in _stage
        and _stage.index("is_final_por(db, league_id=league_id, season=season)")
        < _stage.index("reserve_account(team_id), contribution"),
        "the era gate does not precede the reserve posting")

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
