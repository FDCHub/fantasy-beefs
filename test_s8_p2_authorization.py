#!/usr/bin/env python3
"""
test_s8_p2_authorization.py — Sprint 8 Package 2 · league-scoped authorization.

WHAT THIS SUITE IS FOR. P2 moved 30 routes from "any user whose global role
string says commissioner" to "a commissioner OF THIS LEAGUE". Almost everything
below is therefore negative: the risk in a change like this is not that the
authorized case breaks — that fails loudly the first time anyone tries it — but
that some route was missed, or that a narrowing silently locked out the person
who should still be able to act.

THE FOUR CLAIMS, made against EVERY changed route rather than a sample:

  1. a commissioner of League A cannot act on League B;
  2. a global role string with no LeagueCommissioner row cannot act;
  3. owning a team in the league does not imply commissioner authority;
  4. the league's real commissioner still succeeds.

Sampling would be the wrong shape here. The failure mode P2 exists to fix is
"one route was overlooked", and a suite that checks a handful of routes cannot
distinguish a complete fix from a partial one. So the route list is declared
once, below, and every claim is asserted against all of it.

TWO LEAGUES, FOUR USERS. League A and League B each have a commissioner and a
GM. Nothing is shared but the schema, so "cannot act on League B" is a
statement about real rows rather than about an id that happens not to exist.

DATABASE. A temp SQLite file per run. No assertion here concerns row locking,
isolation or concurrency — these are authorization decisions taken before any
write — so nothing below is weakened by the absence of PostgreSQL. The one
claim that DOES depend on Postgres semantics (Top-Off's re-check of live
authority under a row lock) is named and deferred to P5 rather than asserted
here.
"""

from __future__ import annotations

import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 's8p2.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient

from api.main import app
from auth.jwt_auth import hash_password
from auth.session import CSRF_COOKIE, CSRF_HEADER, STATE_CHANGING_GET_PREFIXES
from db.schema import (
    Base, CommissionerRule, EscrowAccount, League, LeagueCommissioner,
    SessionLocal, Team, TuesdaySyncRun, User, WeeklyWrapUp, engine,
)
from ledger.ledger import create_ledger_table

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


# ── Fixtures: two complete leagues ───────────────────────────────────────────

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "sprint8-password"
A_COMM, A_GM = "comm.a@example.test", "gm.a@example.test"
B_COMM, B_GM = "comm.b@example.test", "gm.b@example.test"
ROLE_ONLY = "roleonly@example.test"     # global role string, no league row

with SessionLocal() as db:
    hashed = hash_password(PASSWORD)
    ids = {}

    for tag, comm_email, gm_email in (("A", A_COMM, A_GM), ("B", B_COMM, B_GM)):
        league = League(name=f"League {tag}", season=2026)
        db.add(league); db.flush()

        comm_team = Team(team_name=f"{tag} Commissioners", owner=f"{tag} Comm",
                         email=comm_email, league_id=league.id)
        gm_team = Team(team_name=f"{tag} Gravy", owner=f"{tag} Gm",
                       email=gm_email, league_id=league.id)
        db.add_all([comm_team, gm_team]); db.flush()

        comm = User(email=comm_email, hashed_password=hashed,
                    team_id=comm_team.id, role="commissioner")
        gm = User(email=gm_email, hashed_password=hashed,
                  team_id=gm_team.id, role="gm")
        db.add_all([comm, gm]); db.flush()

        db.add(LeagueCommissioner(league_id=league.id, user_id=comm.id,
                                  source="bootstrap"))

        ids[tag] = {"league": league.id, "gm_team": gm_team.id,
                    "comm_team": comm_team.id, "comm_user": comm.id}

    # The user P2 exists to stop: role says commissioner, holds no authority
    # row for any league. Before P2 this account could act on every league.
    db.add(User(email=ROLE_ONLY, hashed_password=hashed, team_id=None,
                role="commissioner"))

    # Child entities in League A, so the entity-resolved routes have something
    # real to resolve. A commissioner of B must not reach any of them.
    # Values chosen to satisfy the table's own CHECK constraints — a fixture
    # that dodged them would be testing authorization against a row shape the
    # schema does not permit.
    rule = CommissionerRule(league_id=ids["A"]["league"], raw_text="test rule",
                            rule_type="weekly", effect_type="obligation",
                            target="commissioner_manual", amount=100.0,
                            has_escrow=False, status="draft")
    db.add(rule); db.flush()

    escrow = EscrowAccount(league_id=ids["A"]["league"], rule_id=rule.id,
                           name="test escrow", balance=0.0, status="open",
                           release_trigger="end_of_season")
    wrap = WeeklyWrapUp(run_id="run-a-1", league_id=ids["A"]["league"], week=5,
                        status="draft")
    sync = TuesdaySyncRun(run_id="sync-a-1", league_id=ids["A"]["league"],
                          week=5, status="completed", mock_mode=True)
    db.add_all([escrow, wrap, sync]); db.flush()

    ids["entities"] = {"rule": rule.id, "escrow": escrow.id,
                       "wrap": wrap.id, "sync_run": sync.run_id}
    db.commit()

A, B = ids["A"], ids["B"]
ENT = ids["entities"]


def _client() -> TestClient:
    """A client that reports a route's internal error as a 500 rather than
    re-raising it into this process.

    WHY. This suite drives 31 routes with deliberately minimal payloads,
    because what it measures is the authorization decision taken BEFORE a route
    looks at its body. Several of those routes then fail on the stub payload,
    or on an absent AI key, or on a slate that was never built — all of which
    are correct behaviour and none of which are this suite's subject. With
    exceptions re-raised, the first such route would abort the run and the
    remaining authorization checks would never be made.

    This does not weaken any assertion. Every check below is stated in terms of
    401/403/405, so a 500 can satisfy only the checks that say "not refused" —
    and a route that reached its own internal error has, by definition, passed
    authorization, which is exactly the claim.
    """
    return TestClient(app, raise_server_exceptions=False)


def _cookie_session(email: str) -> TestClient:
    c = _client()
    r = c.post("/auth/session", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, f"{email}: {r.text}"
    return c


def _bearer(email: str) -> dict:
    r = _client().post("/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _call(client: TestClient, verb: str, path: str, body=None) -> int:
    """Issue a request on a cookie session, attaching the CSRF token.

    The token is always attached so that a 403 in these tests can only mean an
    AUTHORIZATION refusal. Without that, a missing-CSRF 403 would be
    indistinguishable from the thing each assertion is trying to measure, and
    every negative test would pass for the wrong reason.
    """
    headers = {}
    token = client.cookies.get(CSRF_COOKIE)
    if token:
        headers[CSRF_HEADER] = token
    return client.request(verb, path, json=body, headers=headers).status_code


# ── The routes P2 changed ────────────────────────────────────────────────────
#
# (verb, path-template, body) — `{L}` is substituted with the league under test.
# Declared once and used by every claim below, so a route cannot be covered by
# one check and missed by another.

LEAGUE_SCOPED_ROUTES = [
    # league in the PATH — require_league_commissioner
    ("GET",    "/rules/league/{L}",                  None),
    ("GET",    "/rules/executions/{L}",              None),
    ("GET",    "/rules/audit/{L}",                   None),
    ("GET",    "/admin/tuesday-sync/runs/{L}",       None),
    ("GET",    "/reports/wrap-up/{L}/5",             None),
    ("GET",    "/reports/wrap-up/{L}",               None),
    ("GET",    "/reports/settlement/{L}",            None),
    # league in the BODY or query — assert_league_commissioner
    ("POST",   "/payments/buyin-enforcement",        {"league_id": "{L}", "active": True}),
    ("POST",   "/faab/setup",                        {"league_id": "{L}"}),
    ("POST",   "/faab/init-season?league_id={L}",    None),
    ("POST",   "/rules/parse",                       {"league_id": "{L}", "raw_text": "x"}),
    ("POST",   "/rules/create",                      {"league_id": "{L}", "raw_text": "x", "spec": {}}),
    ("POST",   "/rules/execute-weekly",              {"league_id": "{L}", "week": 5}),
    ("POST",   "/rules/execute-end-of-season",       {"league_id": "{L}"}),
    ("POST",   "/admin/tuesday-sync",                {"league_id": "{L}", "week": 5}),
    ("POST",   "/reports/wrap-up/generate",          {"league_id": "{L}", "week": 5}),
    ("POST",   "/reports/rankings/compute",          {"league_id": "{L}", "week": 5}),
    ("POST",   "/pool/config",                       {"league_id": "{L}", "weekly_entry": 1.0}),
    ("POST",   "/pool/collect",                      {"league_id": "{L}", "week": 5}),
    ("POST",   "/pool/settle",                       {"league_id": "{L}", "week": 5}),
    # S8-P2R: settlement is league-parameterised like everything else here, so
    # it is covered by all four claims below rather than only by its own
    # section. It moved out of the entity/fixed list when it stopped being a
    # route with a hard-coded league.
    ("POST",   "/league/{L}/settle/5",               None),
]

# Entity-resolved routes. Every entity below belongs to LEAGUE A, so a
# commissioner of B must be refused on all of them.
ENTITY_ROUTES_IN_A = [
    ("GET",    f"/rules/{ENT['rule']}",                        None),
    ("POST",   f"/rules/activate/{ENT['rule']}",               None),
    ("POST",   f"/rules/pause/{ENT['rule']}",                  None),
    ("DELETE", f"/rules/draft/{ENT['rule']}",                  None),
    ("POST",   f"/rules/release-escrow/{ENT['escrow']}",       {}),
    ("PUT",    f"/reports/wrap-up/{ENT['wrap']}",              {"league_body": "x"}),
    # A body, not None: FastAPI validates a required body while solving
    # dependencies, so a missing one returns 422 BEFORE the endpoint — and the
    # authorization check would never run. The 422 was the test's fault, not a
    # gap in the route, but a negative test that passes on a validation error
    # rather than a refusal proves nothing, so the payload is made valid.
    ("POST",   f"/reports/wrap-up/{ENT['wrap']}/send",         {"mock_mode": True}),
    ("GET",    f"/reports/wrap-up/{ENT['wrap']}/editions",     None),
    ("POST",   "/faab/freeze",                                 {"team_id": A["gm_team"], "frozen": True}),
    ("GET",    f"/admin/tuesday-sync/run/{ENT['sync_run']}",   None),
]


def _fill(path, body, league_id):
    path = path.replace("{L}", str(league_id))
    if isinstance(body, dict):
        body = {k: (league_id if v == "{L}" else v) for k, v in body.items()}
    return path, body


print("=" * 64)
print("S8-P2 — league-scoped commissioner authorization")
print("=" * 64)
print(f"\nLeague A = {A['league']}, League B = {B['league']}, "
      f"{len(LEAGUE_SCOPED_ROUTES)} league-parameterised + "
      f"{len(ENTITY_ROUTES_IN_A)} entity/fixed routes")


# ── 1 · A commissioner of League A cannot act on League B ────────────────────

_section("1 · A commissioner of one league cannot act on another")

comm_a = _cookie_session(A_COMM)
leaked = []
for verb, path, body in LEAGUE_SCOPED_ROUTES:
    p, b = _fill(path, body, B["league"])
    if _call(comm_a, verb, p, b) != 403:
        leaked.append(f"{verb} {p}")

_assert("every league-parameterised route refuses a commissioner of another league",
        leaked == [], f"leaked: {leaked}")

comm_b = _cookie_session(B_COMM)
leaked_entities = []
for verb, path, body in ENTITY_ROUTES_IN_A:
    if _call(comm_b, verb, path, body) != 403:
        leaked_entities.append(f"{verb} {path}")

_assert("every entity-resolved route refuses a commissioner of another league",
        leaked_entities == [], f"leaked: {leaked_entities}")


# ── 2 · A global role string with no league row cannot act ───────────────────

_section("2 · The global role string no longer grants league authority")

role_only = _cookie_session(ROLE_ONLY)
_assert("this account's role really does say commissioner",
        role_only.get("/auth/me").json()["role"] == "commissioner")
_assert("and the server reports it holds no league authority",
        role_only.get("/auth/me").json()["capabilities"]["commissioner_league_ids"] == [])

role_leaked = []
for verb, path, body in LEAGUE_SCOPED_ROUTES:
    p, b = _fill(path, body, A["league"])
    if _call(role_only, verb, p, b) != 403:
        role_leaked.append(f"{verb} {p}")
for verb, path, body in ENTITY_ROUTES_IN_A:
    if _call(role_only, verb, path, body) != 403:
        role_leaked.append(f"{verb} {path}")

_assert("a global-role-only commissioner is refused on every changed route",
        role_leaked == [], f"leaked: {role_leaked}")


# ── 3 · Owning a team grants nothing ─────────────────────────────────────────

_section("3 · Owning a team in the league is not commissioner authority")

gm_a = _cookie_session(A_GM)
gm_leaked = []
for verb, path, body in LEAGUE_SCOPED_ROUTES:
    p, b = _fill(path, body, A["league"])
    if _call(gm_a, verb, p, b) != 403:
        gm_leaked.append(f"{verb} {p}")
for verb, path, body in ENTITY_ROUTES_IN_A:
    if _call(gm_a, verb, path, body) != 403:
        gm_leaked.append(f"{verb} {path}")

_assert("a GM of the league itself is refused on every changed route",
        gm_leaked == [], f"leaked: {gm_leaked}")

_assert("but that GM's own team-owned surface still works",
        gm_a.get(f"/account/{A['gm_team']}/summary").status_code == 200)


# ── 4 · The league's real commissioner still succeeds ────────────────────────

_section("4 · The league's own commissioner is not locked out")

# The claim is specifically that AUTHORIZATION passes. A route may still refuse
# for its own reasons — a missing slate, an unparseable rule, an absent AI key
# — so the check is "not 401 and not 403", which is what P2 is responsible for.
# Asserting 200 would be asserting that unrelated subsystems are configured.
denied = []
for verb, path, body in LEAGUE_SCOPED_ROUTES:
    p, b = _fill(path, body, A["league"])
    code = _call(comm_a, verb, p, b)
    if code in (401, 403):
        denied.append(f"{verb} {p} -> {code}")
for verb, path, body in ENTITY_ROUTES_IN_A:
    code = _call(comm_a, verb, path, body)
    if code in (401, 403):
        denied.append(f"{verb} {path} -> {code}")

_assert("the real commissioner passes authorization on every changed route",
        denied == [], f"denied: {denied}")


# ── 5 · Cookie and Bearer resolve identically ────────────────────────────────

_section("5 · Browser cookie and API Bearer reach the same authorization outcome")

bearer_a = _bearer(A_COMM)
bearer_b = _bearer(B_COMM)
mismatch = []

for verb, path, body in LEAGUE_SCOPED_ROUTES:
    # Authorized: A's commissioner on A. Refused: B's commissioner on A.
    for headers, session, expect_denied in ((bearer_a, comm_a, False),
                                            (bearer_b, comm_b, True)):
        p, b = _fill(path, body, A["league"])
        api = _client().request(verb, p, json=b, headers=headers).status_code
        browser = _call(session, verb, p, b)
        if (api == 403) != (browser == 403):
            mismatch.append(f"{verb} {p}: bearer={api} cookie={browser}")
        if expect_denied and api != 403:
            mismatch.append(f"{verb} {p}: bearer NOT denied ({api})")

_assert("every changed route authorizes a Bearer caller exactly as it does a cookie caller",
        mismatch == [], f"mismatches: {mismatch[:6]}")


# ── 6 · The state-changing GET is gone ───────────────────────────────────────

_section("6 · Settlement names its league, and the superseded spellings are gone")

SETTLE_A = f"/league/{A['league']}/settle/5"
SETTLE_B = f"/league/{B['league']}/settle/5"

# ── The two superseded spellings ─────────────────────────────────────────────

_assert("the original mutating GET /settle/{week} is gone",
        _client().get("/settle/5", headers=bearer_a).status_code in (404, 405),
        f"status {_client().get('/settle/5', headers=bearer_a).status_code}")

_assert("the unscoped POST /settle/{week} is gone — no settlement path omits "
        "its league",
        _client().post("/settle/5", headers=bearer_a).status_code in (404, 405),
        f"status {_client().post('/settle/5', headers=bearer_a).status_code}")

_assert("no compatibility settlement path answers at any shorter spelling",
        all(_client().get(p, headers=bearer_a).status_code in (404, 405)
            for p in ("/settle", "/settle/5", f"/league/{A['league']}/settle")))

_assert("the league-scoped route refuses a GET",
        _client().get(SETTLE_A, headers=bearer_a).status_code == 405)

# ── Cross-league authorization ───────────────────────────────────────────────

_assert("League A's commissioner passes authorization on League A settlement",
        _client().post(SETTLE_A, headers=bearer_a).status_code
        not in (401, 403, 404, 405),
        f"status {_client().post(SETTLE_A, headers=bearer_a).status_code}")

_assert("League B's commissioner passes authorization on League B settlement",
        _client().post(SETTLE_B, headers=bearer_b).status_code
        not in (401, 403, 404, 405),
        f"status {_client().post(SETTLE_B, headers=bearer_b).status_code}")

_assert("League B's commissioner CANNOT settle League A",
        _client().post(SETTLE_A, headers=bearer_b).status_code == 403,
        f"status {_client().post(SETTLE_A, headers=bearer_b).status_code}")

_assert("League A's commissioner CANNOT settle League B",
        _client().post(SETTLE_B, headers=bearer_a).status_code == 403,
        f"status {_client().post(SETTLE_B, headers=bearer_a).status_code}")

_assert("a global role string with no league row cannot settle either league",
        _call(role_only, "POST", SETTLE_A) == 403
        and _call(role_only, "POST", SETTLE_B) == 403)

_assert("owning a team in the league cannot settle it",
        _call(gm_a, "POST", SETTLE_A) == 403)

# ── The league that was authorized is the league that gets settled ───────────
#
# The claim the P2R correction actually rests on. Authorizing league A and then
# settling league 1 would satisfy every check above and still be the bug — so
# the engine and the freshness precondition are observed directly, and both
# must receive the league from the PATH.

import api.main as _main_mod  # noqa: E402

seen: dict[str, list] = {"fresh": [], "settle": []}
_real_fresh = _main_mod._assert_slate_fresh
_real_settle = _main_mod.settle_week


def _spy_fresh(league_id, week, db, **kw):
    """Record the league, then report the slate ready.

    Forced ready deliberately. The real precondition would refuse this fixture
    — no provider-bound slate exists — and the route would return 400 before
    settle_week was ever called, leaving the engine's league_id unobserved.
    What is being proved here is that ONE league flows from path to engine, and
    that requires reaching the engine.
    """
    seen["fresh"].append(league_id)
    return (True, "", 0)


def _spy_settle(week, db, league_id, **kw):
    """Record the league and stop.

    Raising rather than settling: this suite observes routing and authority,
    not settlement economics, and actually running a settlement would post
    ledger entries no assertion here reads.
    """
    seen["settle"].append(league_id)
    raise RuntimeError("settlement halted — this suite observes routing, not economics")


_main_mod._assert_slate_fresh = _spy_fresh
_main_mod.settle_week = _spy_settle
try:
    _client().post(SETTLE_B, headers=bearer_b)
finally:
    _main_mod._assert_slate_fresh = _real_fresh
    _main_mod.settle_week = _real_settle

_assert("the freshness precondition receives the league from the path",
        seen["fresh"] == [B["league"]], str(seen["fresh"]))
_assert("the settlement engine receives that same league",
        seen["settle"] == [B["league"]], str(seen["settle"]))
_assert("authorization, precondition and engine all name one league",
        seen["fresh"] == seen["settle"] == [B["league"]],
        f"fresh={seen['fresh']} settle={seen['settle']} authorized={B['league']}")

# League B is not league 1, so a surviving hard-coded default could not
# masquerade as a correct answer here.
_assert("the league proved is NOT the hard-coded 1 that P2R removed",
        B["league"] != 1, f"League B is {B['league']}")

# ── CSRF on the corrected route ──────────────────────────────────────────────

_assert("settlement by cookie is CSRF-protected",
        comm_a.post(SETTLE_A).status_code == 403,
        f"status {comm_a.post(SETTLE_A).status_code}")
_assert("and it is refused for the CSRF reason, not the authority one",
        "CSRF" in comm_a.post(SETTLE_A).json().get("detail", ""))
_assert("settlement by cookie succeeds with the CSRF token",
        _call(comm_a, "POST", SETTLE_A) not in (401, 403))
_assert("settlement by Bearer needs no CSRF token",
        _client().post(SETTLE_A, headers=bearer_a).status_code != 403)


# ── 7 · Controls: nothing was missed ─────────────────────────────────────────

_section("7 · Controls — no state-changing GET, and no unclassified global guard")

_assert("the P1 exception mechanism carries no entries",
        STATE_CHANGING_GET_PREFIXES == (), str(STATE_CHANGING_GET_PREFIXES))

# A route scan, so a NEW mutating GET added later fails this suite rather than
# being discovered by whatever it settles.
import re  # noqa: E402
import pathlib  # noqa: E402

mutating_gets = []
for f in ("api/main.py", "api/pool_routes.py", "api/war_room_routes.py",
          "api/health_routes.py"):
    src = pathlib.Path(f).read_text(encoding="utf-8")
    for block in re.split(r'\n(?=@(?:app|router)\.(?:get|post|put|patch|delete)\()', src):
        m = re.match(r'@(?:app|router)\.get\("([^"]+)"', block)
        if not m:
            continue
        if re.search(r'\b(db\.commit|db\.add|settle_week|ledger_post|close_season'
                     r'|set_[a-z_]+|activate_|approve_|collect_)\b', block[:4000]):
            mutating_gets.append(f"{f}: GET {m.group(1)}")

_assert("no GET route in the API changes state", mutating_gets == [],
        str(mutating_gets))

# Every remaining global guard must be one P2 deliberately kept.
#
# PARSED, NOT PATTERN-MATCHED. An earlier version of this control sliced each
# route's signature at the first `):` and searched that. Routes written with a
# return annotation — `) -> PoolConfigOut:` — have no such `):`, so the slice
# came back empty and every one of them was silently reported as unguarded-and-
# therefore-fine. That is the exact failure this control exists to catch, in
# the control itself, and it would have passed a build with the whole pool
# router still on the global guard. The AST knows where a signature ends.
import ast  # noqa: E402

DELIBERATELY_GLOBAL = {"/auth/promote"}


def _guarded_routes():
    """(verb, path, guard) for every route carrying a commissioner guard."""
    for f in ("api/main.py", "api/pool_routes.py", "api/war_room_routes.py",
              "api/health_routes.py"):
        tree = ast.parse(pathlib.Path(f).read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            route = None
            for d in node.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                        and d.func.attr in ("get", "post", "put", "patch", "delete")
                        and d.args):
                    route = (d.func.attr.upper(), ast.literal_eval(d.args[0]))
            if not route:
                continue

            deps = set()
            for dflt in (list(node.args.defaults)
                         + [d for d in node.args.kw_defaults if d]):
                if (isinstance(dflt, ast.Call)
                        and getattr(dflt.func, "id", "") == "Depends" and dflt.args):
                    deps.add(getattr(dflt.args[0], "id", ""))
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]))

            if "require_league_commissioner" in deps:
                yield (*route, "dep:league", deps, node)
            elif "assert_league_commissioner" in body:
                yield (*route, "assert:league", deps, node)
            elif "require_commissioner" in deps:
                yield (*route, "global", deps, node)


guarded = list(_guarded_routes())
still_global = [path for _v, path, guard, _d, _n in guarded if guard == "global"]

_assert("every remaining global commissioner guard is one P2 deliberately kept",
        set(still_global) == DELIBERATELY_GLOBAL,
        f"found {sorted(still_global)}, expected {sorted(DELIBERATELY_GLOBAL)}")

_assert("no route carrying a league_id path parameter uses the global guard",
        not any("{league_id}" in p for p in still_global), str(still_global))

# A route that checks authority imperatively must have an authenticated user
# and a session to check it with. Without both, the call would be a NameError
# at request time — a 500, which is a refusal, but for the wrong reason and
# only on the paths that happen to be exercised.
malformed = [
    f"{v} {p}" for v, p, guard, deps, _n in guarded
    if guard == "assert:league"
    and not ({"get_current_gm", "get_current_user"} & deps and "get_db" in deps)
]
_assert("every imperative league check has an authenticated user and a db session",
        malformed == [], str(malformed))

_assert("the changed surface is league-scoped almost everywhere",
        len([g for _v, _p, g, _d, _n in guarded if g != "global"]) >= 35,
        f"{len(guarded)} guarded routes, {len(still_global)} still global")


# ── Deferred to P5 ───────────────────────────────────────────────────────────

_section("Deferred to P5 (PostgreSQL-dependent)")
print("  [DEFER] Top-Off's re-check of live commissioner authority under "
      "SELECT ... FOR UPDATE — the re-check is a concurrency claim and SQLite "
      "cannot express the lock, so it is certified in P5, not here.")
print("  [DEFER] Authority revoked concurrently with an in-flight decision — "
      "same reason: the interleaving only exists under real row locking.")


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 64)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P2 AUTHORIZATION — all assertions PASSED")
