"""
test_stripe_removal_regression.py — B2 Stripe removal regression guard.

Product of record: Stripe is out of the FantasyStakes MVP. Season allocation
plus the internal Credits ledger is the sole funding and accounting model.

This suite fails loudly if any of that is undone. It asserts, in order:

  1. NO REGISTERED ROUTE exposes Stripe funding, webhook, connected-account or
     payout behaviour. Checked against the live FastAPI app's route table, not
     against source text, so a route reintroduced under any name or module is
     still caught.
  2. payments.stripe_connect is NOT importable, and NO production module
     imports the stripe SDK.
  3. activate_season_allocation() is the SOLE production call site that posts a
     reserve:{team_id} ledger leg — proven structurally against the AST.
  4. A second season allocation CANNOT duplicate funding: the replay returns
     created=False, posts nothing, and leaves every balance unchanged.
  5. The championship reserve total remains correct after the relocation of
     _championship_total out of the deleted Stripe module.

Uses a temp SQLite DB so prod is never touched.
"""

import ast
import glob
import importlib.util
import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_stripe_removal.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.schema import Base, engine, SessionLocal, League, Team
from ledger.ledger import balance_of, create_ledger_table
from economy.championship import _championship_total
from economy.season_allocation import activate_season_allocation

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        _failures.append(label)


Base.metadata.create_all(engine)
create_ledger_table()

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def _production_py_files():
    for path in glob.glob(os.path.join(_REPO_ROOT, "**", "*.py"), recursive=True):
        rel = os.path.relpath(path, _REPO_ROOT)
        base = os.path.basename(rel)
        if base.startswith("test_") or rel.startswith("test_"):
            continue
        if os.sep + "test" in rel.lower():
            continue
        yield rel, path


# ── ITEM 1: no registered route exposes Stripe behaviour ─────────────────────

print("\nItem 1: the registered FastAPI route table exposes no Stripe surface")

import api.main as api_main

_routes = sorted({getattr(r, "path", "") for r in api_main.app.routes})
_FORBIDDEN_FRAGMENTS = (
    "webhook", "payout", "connect-link", "connect-onboarding",
    "buyin-link", "buyin-confirm", "buyin-status", "treasury", "stripe",
    # B-2 closure: the unfinished FAAB issuance surface is also forbidden
    # until the B6 issuance-ledger model exists.
    "topup", "top-up", "apply-pending",
)
_offenders = [p for p in _routes if any(f in p.lower() for f in _FORBIDDEN_FRAGMENTS)]

_assert("no registered route matches a Stripe/payment fragment",
        _offenders == [], f"got {_offenders}")
_assert("the season-allocation route IS registered",
        "/league/{league_id}/season-allocation" in _routes,
        f"routes containing 'season-allocation': "
        f"{[p for p in _routes if 'season-allocation' in p]}")
_assert("the app still registers a substantial route table (sanity)",
        len(_routes) > 50, f"got {len(_routes)}")


# ── ITEM 2: the Stripe module and SDK are absent from production ─────────────

print("\nItem 2: payments.stripe_connect is gone and no production module imports stripe")

_assert("payments/stripe_connect.py does not exist on disk",
        not os.path.exists(os.path.join(_REPO_ROOT, "payments", "stripe_connect.py")))
_assert("payments.stripe_connect is not importable",
        importlib.util.find_spec("payments.stripe_connect") is None)

_sdk_importers = []
for rel, path in _production_py_files():
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "stripe" or a.name.startswith("stripe."):
                    _sdk_importers.append((rel, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "stripe" or mod.startswith("stripe.") or mod.endswith("stripe_connect"):
                _sdk_importers.append((rel, node.lineno))

_assert("no production module imports the stripe SDK or stripe_connect",
        _sdk_importers == [], f"got {_sdk_importers}")


# ── ITEM 3: activate_season_allocation is the sole reserve-posting site ──────

print("\nItem 3: activate_season_allocation() is the sole production writer of a reserve:{...} leg")


def _is_reserve_account(node) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.startswith("reserve:")
    if isinstance(node, ast.JoinedStr):
        first = node.values[0] if node.values else None
        return (isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and first.value.startswith("reserve:"))
    return False


_sites = []
for rel, path in _production_py_files():
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except SyntaxError:
        continue
    owner = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(fn):
                owner.setdefault(child, fn.name)
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
                    _sites.append((rel.replace(os.sep, "/"), node.lineno, owner.get(node, "<module>")))

_assert("exactly one production call site posts a reserve:{...} leg",
        len(_sites) == 1, f"got {_sites}")
if len(_sites) == 1:
    rel, lineno, func = _sites[0]
    _assert("that site is economy/season_allocation.py", rel == "economy/season_allocation.py", f"got {rel}")
    _assert("inside activate_season_allocation()", func == "activate_season_allocation", f"got {func!r}")


# ── ITEM 4: a second allocation cannot duplicate funding ─────────────────────

print("\nItem 4: replaying season allocation posts nothing and duplicates no funding")

with SessionLocal() as db:
    league = League(season=2025, name="Stripe-removal regression league",
                    projection_source="fantasypros")
    db.add(league)
    db.flush()
    for n in ("R1", "R2"):
        db.add(Team(league_id=league.id, team_name=f"Team {n}", owner=n, email=f"{n}@sr.com"))
    db.commit()
    league_id = league.id
    team_ids = [t.id for t in db.query(Team).filter(Team.league_id == league_id).all()]

with SessionLocal() as db:
    first = activate_season_allocation(league_id, db)

_assert("first activation created the allocation", first.created is True, f"created={first.created}")
_assert("first activation returned one posting id per team",
        len(first.posting_ids) == len(team_ids), f"got {len(first.posting_ids)} for {len(team_ids)} teams")

_before = {
    "world": balance_of("world"),
    **{f"wallet:{t}": balance_of(f"wallet:{t}") for t in team_ids},
    **{f"reserve:{t}": balance_of(f"reserve:{t}") for t in team_ids},
}

with SessionLocal() as db:
    replay = activate_season_allocation(league_id, db)

_after = {k: balance_of(k) for k in _before}

_assert("replay returned created=False", replay.created is False, f"created={replay.created}")
_assert("replay posted nothing (posting_ids empty)", replay.posting_ids == (), f"got {replay.posting_ids}")
_assert("replay moved NO money — every balance byte-identical",
        _after == _before, f"before={_before} after={_after}")
_assert("wallet credited exactly once per team",
        all(_after[f"wallet:{t}"] == first.wallet_cents for t in team_ids),
        f"got {[_after[f'wallet:{t}'] for t in team_ids]}")
_assert("reserve credited exactly once per team",
        all(_after[f"reserve:{t}"] == first.reserve_cents for t in team_ids),
        f"got {[_after[f'reserve:{t}'] for t in team_ids]}")


# ── ITEM 5: championship reserve total remains correct ───────────────────────

print("\nItem 5: the relocated championship total still sums the season-allocation reserves")

with SessionLocal() as db:
    total = _championship_total(league_id, db)

_expected = first.reserve_cents * len(team_ids) + balance_of("championship") + balance_of(f"championship:{league_id}")
_assert("championship_total = summed reserves + shared championship accounts",
        total == _expected, f"got {total}, expected {_expected}")
_assert("championship_total counts the season-allocation reserves specifically",
        total >= first.reserve_cents * len(team_ids),
        f"got {total} for {len(team_ids)} teams at {first.reserve_cents}c each")


# ── ITEM 6: the unfinished FAAB mint surface is not registered ───────────────

print("\nItem 6: no registered route can mint Credits through the FAAB top-up flow")

_FAAB_MINT_ROUTES = (
    "/faab/topup-bet",
    "/faab/topup-waiver",
    "/faab/topup-confirm",
    "/faab/apply-pending",
)
for _r in _FAAB_MINT_ROUTES:
    _assert(f"{_r} is NOT registered", _r not in _routes)

_assert("no registered path contains 'topup'",
        [p for p in _routes if "topup" in p.lower()] == [],
        f"got {[p for p in _routes if 'topup' in p.lower()]}")

# The read-only FAAB surface must survive — this is a mint removal, not a
# feature deletion.
for _keep in ("/faab/wallet/{team_id}", "/faab/league/{league_id}", "/faab/setup"):
    _assert(f"{_keep} IS still registered (read/config surface preserved)",
            _keep in _routes)

# wm_deposit is the mint. Prove no route handler can reach it: api.main must
# not import the functions that call it.
import api.main as _am
for _gone in ("confirm_topup", "create_bet_topup", "create_waiver_topup",
              "apply_pending_topups"):
    _assert(f"api.main no longer imports {_gone}", not hasattr(_am, _gone))

# RECORDED, NOT ASSERTED AWAY: notifications/tuesday_sync.py::_step_apply_topups
# still calls apply_pending_topups(), reachable via POST /admin/tuesday-sync.
# With the request routes gone, no route can create an eligible pending record,
# but that is a database precondition rather than a structural guarantee. This
# assertion documents the residue instead of pretending it is absent.
import notifications.tuesday_sync as _ts
_assert("KNOWN RESIDUE: tuesday_sync still references apply_pending_topups",
        "apply_pending_topups" in open(_ts.__file__, encoding="utf-8").read(),
        "if this ever fails, the residue is gone and the note can be dropped")


# ── Summary ──────────────────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
