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
  3. EVERY production call site that posts a reserve:{team_id} ledger leg is a
     certified economy site — proven structurally against the AST, and named in
     an allowlist so a payment path reintroduced under any name is caught.
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


# ── ITEM 3: every reserve-posting site is certified economy, never a payment ─

print("\nItem 3: every production writer of a reserve:{...} leg is certified economy")


def _is_reserve_account(node) -> bool:
    """Whether this leg's account expression names a reserve:{...} account.

    THREE SPELLINGS, because S5-P1 moved the account names into
    economy.economy_events and the call sites now use the helper. A literal-only
    matcher would have reported ZERO writers, which would have made the check
    below vacuous — which is why it also asserts that the scan found something.
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

#: The production sites certified to post a `reserve:{...}` leg.
#:
#: ── WHY THIS IS AN ALLOWLIST AND NO LONGER A COUNT ──────────────────────────
#:
#: This item used to assert "exactly one" such call site. That was a HISTORICAL
#: IMPLEMENTATION COUNT, not the product rule, and it went stale the moment the
#: RC2 FantasyStakes Championship shipped: `stage_allocation` legitimately posts
#: twice per GM — issuance -> reserve under the season-allocation door, then
#: reserve -> championship pot under the commitment door. Both move VIRTUAL
#: CREDITS between internal accounts. Neither is a payment.
#:
#: The rule being protected is not "one writer". It is that FantasyStakes takes
#: no deposits, processes no payments, makes no payouts and uses no Stripe. So
#: the assertion now names every certified writer and fails on any OTHER one —
#: which is exactly what a reintroduced payment path would be. Adding a new
#: certified economy site here is a deliberate, reviewable act; a payment path
#: cannot be added without someone stating plainly what they are doing.
_CERTIFIED_RESERVE_SITES = {
    ("economy/season_allocation.py", "activate_season_allocation"),
    ("economy/fantasystakes_championship_allocation.py", "stage_allocation"),
}

_found = {(rel, func) for rel, _lineno, func in _sites}
_unexpected = _found - _CERTIFIED_RESERVE_SITES

_assert("every production reserve:{...} writer is a certified economy site",
        not _unexpected, f"uncertified writer(s): {sorted(_unexpected)}")
_assert("the Season-Opening Allocation is still one of them",
        ("economy/season_allocation.py", "activate_season_allocation") in _found,
        f"got {sorted(_found)}")
_assert("no reserve:{...} leg is posted from a payment-shaped module",
        not [site for site in _found
             if any(word in site[0].lower()
                    for word in ("payment", "stripe", "checkout", "billing",
                                 "deposit", "payout"))],
        f"got {sorted(_found)}")
_assert("at least one writer was found — the AST scan still works",
        bool(_found), "the scan produced no sites at all")


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
    **{f"min_reserve:{t}": balance_of(f"min_reserve:{t}") for t in team_ids},
    **{f"reserve:{t}": balance_of(f"reserve:{t}") for t in team_ids},
}

with SessionLocal() as db:
    replay = activate_season_allocation(league_id, db)

_after = {k: balance_of(k) for k in _before}

_assert("replay returned created=False", replay.created is False, f"created={replay.created}")
_assert("replay posted nothing (posting_ids empty)", replay.posting_ids == (), f"got {replay.posting_ids}")
_assert("replay moved NO money — every balance byte-identical",
        _after == _before, f"before={_before} after={_after}")
_assert("min_reserve credited exactly once per team (S5-R2)",
        all(_after[f"min_reserve:{t}"] == first.min_reserve_cents
            for t in team_ids),
        f"got {[_after[f'min_reserve:{t}'] for t in team_ids]}")
_assert("Wallet received nothing from activation (S5-R2)",
        all(_after[f"wallet:{t}"] == 0 for t in team_ids),
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

# ── ITEM 7: the Tuesday-sync top-up mint is structurally refused ─────────────
#
# The previous revision of this suite merely RECORDED that
# notifications/tuesday_sync.py still called apply_pending_topups(). That
# residue is now closed: apply_pending_topups() refuses as its first statement.
# These assertions prove the refusal happens BEFORE any mutation, using a real
# pending row in the disposable test database.

print("\nItem 7: the Tuesday-sync top-up mint is structurally refused")

from wallet.faab_wallet import (
    TopUpsUnavailableError, apply_pending_topups, _log_tx,
)
from db.schema import FaabWallet, FaabTransaction, Wallet
from datetime import datetime, timedelta, timezone

with SessionLocal() as db:
    _t = db.query(Team).filter(Team.league_id == league_id).first()
    db.add(Wallet(team_id=_t.id, balance=0.0))
    db.add(FaabWallet(league_id=league_id, team_id=_t.id,
                      waiver_balance=0.0, pending_waiver_topup=25.0))
    db.commit()
    _tx = _log_tx(db, league_id, _t.id, "topup_waiver", 25.0,
                  wallet_from="issuance", wallet_to="waiver", status="pending",
                  apply_on=datetime.now(timezone.utc) - timedelta(days=1))
    db.commit()
    _tx_id, _team_id = _tx.id, _t.id

def _mint_state():
    with SessionLocal() as db:
        fw = db.query(FaabWallet).filter(FaabWallet.team_id == _team_id).first()
        tx = db.query(FaabTransaction).filter(FaabTransaction.id == _tx_id).first()
        w  = db.query(Wallet).filter(Wallet.team_id == _team_id).first()
        n  = db.query(FaabTransaction).count()
        # bet balance lives on Wallet, not FaabWallet
        return (tx.status, fw.waiver_balance, w.balance,
                fw.pending_waiver_topup, n, balance_of(f"wallet:{_team_id}"))

_before = _mint_state()
_raised = None
try:
    apply_pending_topups_result = apply_pending_topups(None)   # arg irrelevant; refuses first
except TopUpsUnavailableError as _e:
    _raised = _e
except Exception as _e:
    _raised = _e
_after = _mint_state()

_assert("apply_pending_topups() raises TopUpsUnavailableError",
        isinstance(_raised, TopUpsUnavailableError),
        f"got {type(_raised).__name__ if _raised else 'no exception'}")
_assert("the refusal message names the B6 issuance-ledger model",
        _raised is not None and "B6" in str(_raised) and "issuance" in str(_raised).lower(),
        f"message: {str(_raised)[:80]}")
_assert("it refuses even when passed no session at all (refusal precedes any query)",
        isinstance(_raised, TopUpsUnavailableError))

_assert("the due pending row did NOT change status",
        _before[0] == _after[0] == "pending", f"{_before[0]} -> {_after[0]}")
_assert("FaabWallet.waiver_balance unchanged",
        _before[1] == _after[1], f"{_before[1]} -> {_after[1]}")
_assert("Wallet.balance (bet side) unchanged",
        _before[2] == _after[2], f"{_before[2]} -> {_after[2]}")
_assert("FaabWallet.pending_waiver_topup unchanged",
        _before[3] == _after[3], f"{_before[3]} -> {_after[3]}")
_assert("no FaabTransaction row was added or removed",
        _before[4] == _after[4], f"{_before[4]} -> {_after[4]}")
_assert("no ledger entry was added for the team wallet",
        _before[5] == _after[5], f"{_before[5]} -> {_after[5]}")

# The Tuesday pipeline step must surface this as unavailable, never as applied.
import notifications.tuesday_sync as _ts
_step_res, _applied = _ts._step_apply_topups(None)
_assert("/admin/tuesday-sync step reports success=False for top-ups",
        _step_res.success is False, f"success={_step_res.success}")
_assert("the step message says unavailable pending B6",
        "unavailable" in _step_res.message.lower() and "B6" in _step_res.message,
        f"message={_step_res.message!r}")
_assert("the step applied ZERO top-ups", _applied == [], f"got {_applied}")
_assert("the step data records applied_count 0 and unavailable=True",
        _step_res.data.get("applied_count") == 0 and _step_res.data.get("unavailable") is True,
        f"data={_step_res.data}")
_assert("state STILL unchanged after the pipeline step ran",
        _mint_state() == _before, f"{_before} -> {_mint_state()}")


# ── Summary ──────────────────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
