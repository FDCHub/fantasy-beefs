#!/usr/bin/env python3
"""
test_s8_p3_read_models.py — Sprint 8 Package 3 · authoritative read models.

WHAT THIS SUITE IS FOR. P3 added three accounting surfaces. The danger in that
is not that they return wrong numbers — a wrong number is loud — but that they
return numbers of their OWN: three plausible answers computed three ways, which
agree on the fixture and diverge the first time the accounting is corrected.
So the suite tests two different things and keeps them separate:

  · ARITHMETIC — every figure equals what `economy.current_settle` says, on
    real posted ledger state rather than on a stub;
  · STRUCTURE — there is only one place that arithmetic can come from, asserted
    against the source so a second formula cannot be added quietly.

POSTED STATE, NOT MOCKS. Positions are built by posting real balanced entries
through `ledger.post()` under the real doors the read model reads. A mocked
balance would test that this suite can add up, not that the read model reads
what the protocol writes.

WHY THE TOP-OFF TEST POSTS RATHER THAN CALLING approve_top_off(). The approval
path takes three `SELECT ... FOR UPDATE` locks, which SQLite cannot parse — that
is why every existing top-off lifecycle suite is `_pg`. What P3 owns is whether
an APPROVED ISSUANCE is reflected in the read model exactly once, and issuance
is a posting under `approved_bab_topoff`. That is posted directly here. The
lifecycle claim — that approval under concurrent load posts once — is a
concurrency claim and stays P5's, and is named as deferred rather than implied.

DATABASE. A temp SQLite file per run. Nothing here asserts locking, isolation
or concurrency.
"""

from __future__ import annotations

import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 's8p3.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient

from api.main import app
from auth.jwt_auth import hash_password
from auth.session import CSRF_COOKIE, CSRF_HEADER
from db.schema import (
    Base, FaabTransaction, League, LeagueCommissioner, SessionLocal, Team, User,
    engine,
)
from economy.current_settle import (
    DOOR_APPROVED_TOPOFF, DOOR_SEASON_ALLOCATION, current_settle,
)
from economy.economy_events import (
    min_account, min_reserve_account, receivable_account, wallet_account,
)
from ledger.ledger import create_ledger_table, post as ledger_post, trial_balance
from reports.ledger_read_model import (
    gm_ledger, league_positions, league_reconciliation,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


# ── Fixtures ─────────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "sprint8-password"
A_COMM, A_GM, A_GM2 = "comm.a@x.test", "gm.a@x.test", "gm2.a@x.test"
B_COMM, B_GM = "comm.b@x.test", "gm.b@x.test"
ROLE_ONLY = "roleonly@x.test"
PLATFORM = "platform@x.test"

SEASON = 2026

with SessionLocal() as db:
    hashed = hash_password(PASSWORD)
    ids: dict = {}

    for tag, comm_email, gm_emails in (("A", A_COMM, [A_GM, A_GM2]),
                                       ("B", B_COMM, [B_GM])):
        league = League(name=f"League {tag}", season=SEASON)
        db.add(league); db.flush()

        comm_team = Team(team_name=f"{tag} Commissioners", owner=f"{tag} Comm",
                         email=comm_email, league_id=league.id)
        db.add(comm_team); db.flush()
        comm = User(email=comm_email, hashed_password=hashed,
                    team_id=comm_team.id, role="commissioner")
        db.add(comm); db.flush()
        db.add(LeagueCommissioner(league_id=league.id, user_id=comm.id,
                                  source="bootstrap"))

        gm_teams = []
        for i, gm_email in enumerate(gm_emails):
            t = Team(team_name=f"{tag} Team {i}", owner=f"{tag} Owner {i}",
                     email=gm_email, league_id=league.id)
            db.add(t); db.flush()
            db.add(User(email=gm_email, hashed_password=hashed,
                        team_id=t.id, role="gm"))
            gm_teams.append(t.id)

        ids[tag] = {"league": league.id, "comm_team": comm_team.id,
                    "gm_teams": gm_teams}

    db.add(User(email=ROLE_ONLY, hashed_password=hashed, team_id=None,
                role="commissioner"))
    # A platform operator for the global integrity route. Same global role —
    # S8-P2 established that role is platform-scoped and grants no league.
    db.add(User(email=PLATFORM, hashed_password=hashed, team_id=None,
                role="commissioner"))
    db.commit()

A, B = ids["A"], ids["B"]
A_TEAM, A_TEAM2 = A["gm_teams"][0], A["gm_teams"][1]

# ── Post a real, known position for A_TEAM ───────────────────────────────────
#
# Deliberately ODD-CENT values throughout. A rounding bug anywhere between the
# ledger and the JSON body would round these and the assertions would catch it;
# figures like 5000 would survive several kinds of wrongness unnoticed.

OPENING_MIN_RESERVE = 14_000_33      # min_reserve leg of the season advance
OPENING_RESERVE     =  8_000_11      # championship reserve leg
WEEK_MIN_RELEASED   =  1_000_07
SKUNK_RECEIVABLE    =  1_000_01
TOPOFF_APPROVED     =  2_000_09

# Each posting commits on its own, the way production posts do. The ledger's
# funded-balance check reads committed state, so a later posting that debits an
# account an earlier one funded must see that funding already landed.

# Season allocation: the GM is advanced min_reserve + reserve from world.
ledger_post([
    (min_reserve_account(A_TEAM), OPENING_MIN_RESERVE),
    (f"reserve:{A_TEAM}",         OPENING_RESERVE),
    ("world", -(OPENING_MIN_RESERVE + OPENING_RESERVE)),
], door=DOOR_SEASON_ALLOCATION)

# A week's minimum released from min_reserve into the live weekly account.
ledger_post([
    (min_account(A_TEAM, 5),      WEEK_MIN_RELEASED),
    (min_reserve_account(A_TEAM), -WEEK_MIN_RELEASED),
], door="weekly_minimum_release")

# A Skunk assessment: a receivable obligation against the GM.
ledger_post([
    (receivable_account(A_TEAM), -SKUNK_RECEIVABLE),
    ("skunk:1",                   SKUNK_RECEIVABLE),
], door="skunk_assessment")


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _cookie(email: str) -> TestClient:
    c = _client()
    r = c.post("/auth/session", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, f"{email}: {r.text}"
    return c


def _bearer(email: str) -> dict:
    r = _client().post("/auth/login", data={"username": email,
                                            "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


print("=" * 66)
print("S8-P3 — authoritative accounting read models")
print("=" * 66)


# ── 1 · The GM read model IS the authoritative calculation ───────────────────

_section("1 · The GM read model reports the authoritative Current Settle")

with SessionLocal() as db:
    authority = current_settle(db, team_id=A_TEAM, league_id=A["league"],
                               season=SEASON)
    model = gm_ledger(db, team_id=A_TEAM, league_id=A["league"])

_assert("every CurrentSettle component is carried through unchanged",
        all(getattr(model, f"{name}_cents") == getattr(authority, f"{name}_cents")
            for name in ("wallet", "weekly_min_live", "min_reserve",
                         "expired_min", "in_play", "season_advance",
                         "topoff_issued", "receivable")))
_assert("assets match the authority", model.assets_cents == authority.assets_cents,
        f"{model.assets_cents} vs {authority.assets_cents}")
_assert("obligations match the authority",
        model.obligations_cents == authority.obligations_cents,
        f"{model.obligations_cents} vs {authority.obligations_cents}")
_assert("Current Settle matches the authority",
        model.current_settle_cents == authority.current_settle_cents,
        f"{model.current_settle_cents} vs {authority.current_settle_cents}")

# The grouping identity the POR states: assets − obligations = Current Settle.
_assert("the model's own arithmetic closes",
        model.assets_cents - model.obligations_cents == model.current_settle_cents)

# Against the posted fixture, term by term.
# Both legs, and unaffected by the later weekly release: `season_advance_cents`
# sums the season-allocation DOOR, and the release posts under a different one.
# That is what makes the obligation stable while the assets move.
_assert("the season advance is the whole opening allocation, both legs",
        model.season_advance_cents == OPENING_MIN_RESERVE + OPENING_RESERVE,
        str(model.season_advance_cents))
_assert("the championship reserve is advanced but is NOT a GM asset — which "
        "is why this position is negative",
        model.current_settle_cents == model.assets_cents - model.obligations_cents
        < 0 and model.assets_cents < model.season_advance_cents,
        f"assets {model.assets_cents} vs advance {model.season_advance_cents}")
_assert("the released weekly minimum is live and counted as an asset",
        model.weekly_min_live_cents == WEEK_MIN_RELEASED,
        str(model.weekly_min_live_cents))
_assert("the Skunk receivable is an obligation, sign-corrected",
        model.receivable_cents == SKUNK_RECEIVABLE,
        str(model.receivable_cents))
_assert("Available groups wallet with released weekly minimum",
        model.available_cents == model.wallet_cents + model.weekly_min_live_cents)
_assert("Total Virtual Stakes is advance plus approved Top-Offs, excluding "
        "the receivable",
        model.total_virtual_stakes_cents
        == model.season_advance_cents + model.topoff_issued_cents)


# ── 2 · The commissioner's cards use the same calculation ────────────────────

_section("2 · Commissioner GM cards come from the same calculation")

with SessionLocal() as db:
    positions = league_positions(db, league_id=A["league"])
    solo = gm_ledger(db, team_id=A_TEAM, league_id=A["league"])

_assert("the league returns one position per team actually in it",
        len(positions) == 3, f"{len(positions)} positions")
_assert("membership is read, not assumed to be twelve",
        [p.team_id for p in positions]
        == sorted([A["comm_team"], A_TEAM, A_TEAM2]),
        str([p.team_id for p in positions]))
_assert("ordering is deterministic",
        [p.team_id for p in positions] == sorted(p.team_id for p in positions))

card = next(p for p in positions if p.team_id == A_TEAM)
_assert("the commissioner's view of a GM is that GM's own position, field for "
        "field", card.as_dict() == solo.as_dict())


# ── 3 · League reconciliation aggregates those same positions ────────────────

_section("3 · League reconciliation is the sum of the authoritative positions")

with SessionLocal() as db:
    recon = league_reconciliation(db, league_id=A["league"])
    positions = league_positions(db, league_id=A["league"])

_assert("the position count is the real league size",
        recon.position_count == len(positions) == 3)
_assert("aggregate assets equal the sum of the positions' assets",
        recon.aggregate_assets_cents == sum(p.assets_cents for p in positions))
_assert("aggregate obligations equal the sum of the positions' obligations",
        recon.aggregate_obligations_cents
        == sum(p.obligations_cents for p in positions))
_assert("aggregate Current Settle equals the sum of the GMs' own figures",
        recon.aggregate_current_settle_cents == recon.sum_of_gm_settles_cents
        == sum(p.current_settle_cents for p in positions))
_assert("the league arithmetic reconciles",
        recon.reconciles is True,
        f"assets {recon.aggregate_assets_cents} - obligations "
        f"{recon.aggregate_obligations_cents} vs sum "
        f"{recon.sum_of_gm_settles_cents}")
_assert("aggregate Total Virtual Stakes sums the positions",
        recon.aggregate_total_virtual_stakes_cents
        == sum(p.total_virtual_stakes_cents for p in positions))

# The exceptions must be visible WITHOUT entering a total.
_assert("pending challenge holds are reported, not counted as a liability",
        recon.exceptions["pending_challenge_holds"].settlement_liability is False)
_assert("open Top-Off requests are reported, not counted as a liability",
        recon.exceptions["open_top_offs"].settlement_liability is False)


# ── 4 · Structure: one calculation, not three ────────────────────────────────

_section("4 · There is exactly one settlement calculation in the read layer")

import ast  # noqa: E402
import pathlib  # noqa: E402

rm_src = pathlib.Path("reports/ledger_read_model.py").read_text(encoding="utf-8")
rm_tree = ast.parse(rm_src)

calls: dict[str, list[str]] = {}
for node in ast.walk(rm_tree):
    if isinstance(node, ast.FunctionDef):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                name = getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
                if name in ("current_settle", "gm_ledger", "league_positions"):
                    calls.setdefault(name, []).append(node.name)

_assert("current_settle() is called from exactly one function",
        calls.get("current_settle") == ["gm_ledger"],
        str(calls.get("current_settle")))
_assert("league_positions builds its cards from gm_ledger",
        "league_positions" in calls.get("gm_ledger", []),
        str(calls.get("gm_ledger")))
_assert("league_reconciliation aggregates league_positions",
        "league_reconciliation" in calls.get("league_positions", []),
        str(calls.get("league_positions")))

# The API layer must shape and authorize, never compute.
api_src = pathlib.Path("api/main.py").read_text(encoding="utf-8")
_assert("the API layer never calls current_settle directly",
        "current_settle(" not in api_src)
# The read layer must never recompute a GM position from ledger accounts of its
# own. If it imports the balance primitives or queries the entry table
# directly, it has stopped reporting the authority and started competing with
# it.
#
# PARSED, NOT GREPPED. A substring scan matches this module's own prose — its
# docstring says the authority derives positions "from posted ledger_entries" —
# and would fail on the documentation while a real violation hid in a function.
# The AST sees imports and calls, and no comment.
_BANNED_NAMES = {"_balance_of_in_session", "balance_of", "trial_balance"}
_leaked: list[str] = []
for _node in ast.walk(rm_tree):
    if isinstance(_node, ast.ImportFrom) and (_node.module or "").startswith("ledger"):
        _leaked += [a.name for a in _node.names if a.name in _BANNED_NAMES]
    if isinstance(_node, ast.Call):
        _name = getattr(_node.func, "id", None) or getattr(_node.func, "attr", None)
        if _name in _BANNED_NAMES | {"text", "execute"}:
            _leaked.append(_name)

_assert("the read layer calls no ledger primitive and issues no raw query",
        _leaked == [], f"found {_leaked}")


# ── 5 · Exact cents survive the API boundary ─────────────────────────────────

_section("5 · Exact integer cents survive the API boundary")

gm_a = _cookie(A_GM)
body = gm_a.get(f"/league/{A['league']}/ledger/me").json()

MONEY_FIELDS = [k for k in body if k.endswith("_cents")]
_assert("every monetary field is an integer, not a float or a string",
        all(isinstance(body[k], int) for k in MONEY_FIELDS),
        str({k: type(body[k]).__name__ for k in MONEY_FIELDS
             if not isinstance(body[k], int)}))
_assert("no formatted dollar string is published as an authoritative value",
        not any(isinstance(v, str) and "$" in v for v in body.values()))

_assert("odd cents survive exactly — the weekly minimum",
        body["weekly_min_live_cents"] == WEEK_MIN_RELEASED,
        f"{body['weekly_min_live_cents']} vs {WEEK_MIN_RELEASED}")
_assert("odd cents survive exactly — the season advance",
        body["season_advance_cents"] == OPENING_MIN_RESERVE + OPENING_RESERVE)
_assert("a NEGATIVE Current Settle survives with its sign",
        body["current_settle_cents"] < 0,
        f"{body['current_settle_cents']}")
_assert("the API figure equals the module figure exactly",
        body["current_settle_cents"] == model.current_settle_cents)

# Zero: a team with no postings at all.
zero = _cookie(A_GM2).get(f"/league/{A['league']}/ledger/me").json()
_assert("a GM with no posted state reports exact zeros, not nulls",
        all(zero[k] == 0 for k in MONEY_FIELDS), str(zero))


# ── 6 · Top-Off accounting: exactly once, and only when issued ───────────────

_section("6 · Approved Top-Off raises obligations exactly once")

with SessionLocal() as db:
    before = gm_ledger(db, team_id=A_TEAM, league_id=A["league"])

    # A PENDING request row — no posting. Must move nothing.
    db.add(FaabTransaction(league_id=A["league"], team_id=A_TEAM,
                           type="topup_bet", amount=20.0,
                           amount_cents=TOPOFF_APPROVED, season=SEASON,
                           status="pending", decision="pending"))
    db.commit()

with SessionLocal() as db:
    with_pending = gm_ledger(db, team_id=A_TEAM, league_id=A["league"])

_assert("a pending Top-Off request changes no position figure",
        with_pending.as_dict() == before.as_dict())

with SessionLocal() as db:
    rejected = FaabTransaction(league_id=A["league"], team_id=A_TEAM,
                               type="topup_bet", amount=20.0,
                               amount_cents=TOPOFF_APPROVED, season=SEASON,
                               status="rejected", decision="rejected")
    cancelled = FaabTransaction(league_id=A["league"], team_id=A_TEAM,
                                type="topup_bet", amount=20.0,
                                amount_cents=TOPOFF_APPROVED, season=SEASON,
                                status="cancelled", decision="cancelled")
    db.add_all([rejected, cancelled]); db.commit()

with SessionLocal() as db:
    with_decided = gm_ledger(db, team_id=A_TEAM, league_id=A["league"])

_assert("rejected and cancelled requests change no position figure",
        with_decided.as_dict() == before.as_dict())

# Now the ISSUANCE — a real posting under the canonical approved door.
ledger_post([
    (wallet_account(A_TEAM), TOPOFF_APPROVED),
    ("world",              -TOPOFF_APPROVED),
], door=DOOR_APPROVED_TOPOFF)

with SessionLocal() as db:
    after = gm_ledger(db, team_id=A_TEAM, league_id=A["league"])

_assert("an approved Top-Off raises obligations by exactly the amount, once",
        after.obligations_cents - before.obligations_cents == TOPOFF_APPROVED,
        f"delta {after.obligations_cents - before.obligations_cents}")
_assert("it raises Total Virtual Stakes by exactly the amount",
        after.total_virtual_stakes_cents - before.total_virtual_stakes_cents
        == TOPOFF_APPROVED)
_assert("it raises assets by the same amount — the Credits are real",
        after.assets_cents - before.assets_cents == TOPOFF_APPROVED)
_assert("so Current Settle is UNCHANGED — an advance is not winnings",
        after.current_settle_cents == before.current_settle_cents,
        f"{before.current_settle_cents} -> {after.current_settle_cents}")
_assert("and it is counted once, not twice",
        after.topoff_issued_cents == TOPOFF_APPROVED,
        str(after.topoff_issued_cents))


# ── 7 · Authorization ────────────────────────────────────────────────────────

_section("7 · Authorization — P2's model, preserved")

comm_a, comm_b = _cookie(A_COMM), _cookie(B_COMM)
role_only, gm_b = _cookie(ROLE_ONLY), _cookie(B_GM)

POSITIONS_A = f"/league/{A['league']}/ledger/positions"
RECON_A = f"/league/{A['league']}/ledger/reconciliation"
ME_A = f"/league/{A['league']}/ledger/me"

_assert("the league's commissioner reads its positions",
        comm_a.get(POSITIONS_A).status_code == 200)
_assert("and its reconciliation", comm_a.get(RECON_A).status_code == 200)

_assert("a commissioner of another league cannot read positions",
        comm_b.get(POSITIONS_A).status_code == 403)
_assert("a commissioner of another league cannot read the reconciliation",
        comm_b.get(RECON_A).status_code == 403)
_assert("a global role string with no league row cannot read positions",
        role_only.get(POSITIONS_A).status_code == 403)
_assert("owning a team in the league is not commissioner authority",
        gm_a.get(POSITIONS_A).status_code == 403)

_assert("a GM reads their own position",
        gm_a.get(ME_A).status_code == 200)
_assert("a GM of another league is refused",
        gm_b.get(ME_A).status_code == 403)
_assert("an unauthenticated caller is refused",
        _client().get(ME_A).status_code == 401)

# The team is not a parameter, so there is nothing to substitute. Proven by
# the route table rather than by trying values: an absent parameter cannot be
# supplied, and a query string the route does not declare is ignored.
own = gm_a.get(ME_A).json()
spoofed = gm_a.get(f"{ME_A}?team_id={A_TEAM2}").json()
_assert("a GM cannot substitute another team id",
        own["team_id"] == spoofed["team_id"] == A_TEAM,
        f"{own['team_id']} / {spoofed['team_id']}")

# Bearer / cookie parity.
mismatch = []
for path, cookie_client, bearer_email in (
        (POSITIONS_A, comm_a, A_COMM), (POSITIONS_A, comm_b, B_COMM),
        (RECON_A, comm_a, A_COMM), (RECON_A, comm_b, B_COMM),
        (ME_A, gm_a, A_GM), (ME_A, gm_b, B_GM)):
    api = _client().get(path, headers=_bearer(bearer_email)).status_code
    browser = cookie_client.get(path).status_code
    if (api == 403) != (browser == 403):
        mismatch.append(f"{path} as {bearer_email}: bearer={api} cookie={browser}")
_assert("cookie and Bearer reach the same authorization outcome",
        mismatch == [], str(mismatch))


# ── 8 · Global integrity stays BACKEND-ONLY ──────────────────────────────────

_section("8 · The global trial balance is backend-only, by design")

# S8-P3R. P3 briefly served this invariant at GET /ledger/integrity, guarded by
# the global commissioner role. That role is the strongest tier this system
# has — and it is also the tier an ordinary league commissioner holds, because
# the seeding convention grants it. The governing instruction is that when the
# authority model cannot express platform-operator authority, the invariant
# stays backend-only rather than being served under an authority that does not
# fit it. The route is gone.
#
# This is an authority boundary, not a missing feature. Everything below
# asserts the boundary holds from BOTH sides: the invariant still exists and
# still works for backend and certification callers, and no HTTP caller of any
# privilege can reach it.

_assert("trial_balance() still exists and is callable from backend code",
        callable(trial_balance))
_assert("it still answers the global conservation question",
        trial_balance() == 0, f"imbalance {trial_balance()}")

# GLOBAL means global: it takes no league argument and accepts none.
import inspect  # noqa: E402

_assert("it remains global — it takes no league parameter",
        list(inspect.signature(trial_balance).parameters) == [],
        str(list(inspect.signature(trial_balance).parameters)))

# No HTTP surface, at any spelling, for any caller.
_INTEGRITY_SPELLINGS = ("/ledger/integrity", "/ledger/trial-balance",
                        "/ledger/trial_balance", "/integrity",
                        f"/league/{A['league']}/ledger/integrity",
                        f"/league/{A['league']}/ledger/trial-balance")

_registered = {getattr(r, "path", "") for r in app.routes}
_assert("no route in the application serves the global invariant",
        all(sp not in _registered for sp in _INTEGRITY_SPELLINGS),
        str(sorted(_registered & set(_INTEGRITY_SPELLINGS))))

# Proven by request too, and specifically for the most privileged caller the
# role model can produce — if anyone could reach it, it would be this account.
platform = _cookie(PLATFORM)
_unreachable = {sp: platform.get(sp).status_code for sp in _INTEGRITY_SPELLINGS}
_assert("even a holder of the global role cannot obtain it over HTTP",
        all(code in (404, 405) for code in _unreachable.values()),
        str(_unreachable))

_assert("and neither can an ordinary league commissioner",
        all(comm_a.get(sp).status_code in (404, 405)
            for sp in _INTEGRITY_SPELLINGS))

# The boundary must not have been evaded by inventing a league-scoped version.
_assert("no league-scoped trial-balance derivation was invented",
        "trial_balance" not in pathlib.Path(
            "reports/ledger_read_model.py").read_text(encoding="utf-8"))
_assert("the API layer no longer imports trial_balance at all",
        "trial_balance" not in [
            n.name
            for node in ast.walk(ast.parse(api_src))
            if isinstance(node, ast.ImportFrom)
            for n in node.names],
        "api/main.py still imports the global invariant")

# The commissioner is not left without an answer: the LEAGUE question has a
# league-scoped surface, and it still works.
_assert("League Reconciliation remains available to the league's commissioner",
        comm_a.get(RECON_A).status_code == 200)
_assert("and it answers the league question, reporting its own league",
        comm_a.get(RECON_A).json()["league_id"] == A["league"])

# The seam must SAY all of this, so P4 binds the right surface and does not go
# looking for a global integrity row to display.
_seam_src = pathlib.Path("web/js/commissioner-model.js").read_text(encoding="utf-8")
_seam = _seam_src[_seam_src.index("export const TRIAL_BALANCE_SEAM"):]
_seam = _seam[:_seam.index("});") + 3]

_assert("the seam records the invariant as existing and backend-only",
        "GLOBAL INVARIANT EXISTS · BACKEND-ONLY" in _seam)
_assert("it names the computation", "trial_balance()" in _seam)
_assert("it declares no endpoint", "endpoint: null" in _seam)
_assert("it states the scope is global", "scope: 'global'" in _seam)
_assert("it gives the authority reason rather than implying a deficiency",
        "no distinct platform-operator tier" in _seam)
_assert("it states what the invariant does not prove",
        "doesNotProve: 'individual league reconciliation'" in _seam)
_assert("and it points the commissioner at League Reconciliation",
        "commissionerSurface: 'GET /league/{league_id}/ledger/reconciliation'"
        in _seam)


# ── 9 · No cross-league leakage ──────────────────────────────────────────────

_section("9 · No cross-league data leaks through any read model")

a_positions = comm_a.get(POSITIONS_A).json()
a_team_ids = {p["team_id"] for p in a_positions}
with SessionLocal() as db:
    b_team_ids = {t.id for t in db.query(Team).filter(
        Team.league_id == B["league"]).all()}

_assert("league A's positions contain no league B team",
        a_team_ids.isdisjoint(b_team_ids),
        f"overlap {a_team_ids & b_team_ids}")
_assert("the reconciliation counts only league A's positions",
        comm_a.get(RECON_A).json()["position_count"] == len(a_team_ids))
_assert("league B's own reconciliation is independent",
        comm_b.get(f"/league/{B['league']}/ledger/reconciliation")
        .json()["position_count"] == 2)


# ── Deferred to P5 ───────────────────────────────────────────────────────────

_section("Deferred to P5 (PostgreSQL-dependent)")
print("  [DEFER] approve_top_off() end-to-end under its three FOR UPDATE locks "
      "— the issuance ACCOUNTING is proven above from posted state; that "
      "approval posts exactly once under concurrency is a locking claim "
      "SQLite cannot express.")
print("  [DEFER] read-model consistency against a concurrent settlement or "
      "issuance — requires real isolation semantics.")


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 66)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P3 READ MODELS — all assertions PASSED")