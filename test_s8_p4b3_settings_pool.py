#!/usr/bin/env python3
"""
test_s8_p4b3_settings_pool.py — Sprint 8 P4B-3 · settings and Pool slate.

WHAT IT PROVES, IN THREE LAYERS.

  1. THE COMMAND, against a real server: the Standard Pool Bet write goes to the
     governed route, writes the governed column, enforces the governed bounds
     and freeze, and is refused for everyone without league commissioner
     authority.
  2. THE MODELS, driven directly: settings and slate carry the same
     demo/authoritative/unavailable discipline the accounting models do, so a
     refused read can never reveal illustrative settings or the four launch
     Pools.
  3. THE DRAWN SLATE, which no other suite can see. The certification
     environment has gate 2 unsatisfied — `selectable_now: 0`, provider access
     refused — so every browser suite runs against an UNDRAWN week. The
     four-slot contract, continuation-occupies-a-slot, and the ordering claims
     therefore have nowhere else to live, and are certified here against a
     persisted fixture slate.

The fixture writes `PoolInstance` rows directly, which is the persisted output
of `betting/pool_slate.build_and_persist_slate`. Calling the builder itself is
not possible here and would not be honest: it requires four definitions passing
BOTH gates, and gate 2 is exactly the environmental precondition this
environment does not meet. Nothing below weakens a gate or fabricates a
provider measurement — it seeds the RESULT the builder would persist, and then
tests that the UI reads it rather than composing one.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 's8p4b3.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import json  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from auth.jwt_auth import hash_password  # noqa: E402
from auth.session import CSRF_COOKIE, CSRF_HEADER  # noqa: E402
from betting.pool_funding import (  # noqa: E402
    GOVERNED_MAX_WEEKLY_ENTRY_CENTS, GOVERNED_MIN_WEEKLY_ENTRY_CENTS,
)
from db.schema import (  # noqa: E402
    Base, League, LeagueCommissioner, PoolConfig, PoolDefinition, PoolInstance,
    SessionLocal, Team, User, engine,
)
from ledger.ledger import create_ledger_table  # noqa: E402

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


# ── Fixtures: two leagues, and a DRAWN slate for league A ────────────────────

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "sprint8-password"
A_COMM, A_GM = "comm.a@x.test", "gm.a@x.test"
B_COMM = "comm.b@x.test"
SEASON, WEEK = 2026, 5

with SessionLocal() as db:
    hashed = hash_password(PASSWORD)
    ids = {}
    for tag, comm_email, gm_email in (("A", A_COMM, A_GM), ("B", B_COMM, None)):
        league = League(name=f"League {tag}", season=SEASON)
        db.add(league); db.flush()
        comm_team = Team(team_name=f"{tag} Comm", owner="C", email=comm_email,
                         league_id=league.id)
        db.add(comm_team); db.flush()
        comm = User(email=comm_email, hashed_password=hashed,
                    team_id=comm_team.id, role="commissioner")
        db.add(comm); db.flush()
        db.add(LeagueCommissioner(league_id=league.id, user_id=comm.id,
                                  source="bootstrap"))
        if gm_email:
            gm_team = Team(team_name=f"{tag} Gravy", owner="G", email=gm_email,
                           league_id=league.id)
            db.add(gm_team); db.flush()
            db.add(User(email=gm_email, hashed_password=hashed,
                        team_id=gm_team.id, role="gm"))
        ids[tag] = league.id

    # THE REAL Rev1.3 CATALOG, seeded through its own governed seeder rather
    # than hand-built. `PoolInstance.definition_key` is a foreign key to
    # `pool_definition.key`, so a slate slot must name a real catalog
    # definition — and hand-rolling rows would both fight a dozen CHECK
    # constraints and let the fixture drift from the artifact it is supposed to
    # represent. The slate below therefore draws four ACTUAL definitions.
    from betting.pool_catalog import seed_definitions
    seed_definitions(db)
    db.flush()

    SLATE_KEYS = [d.key for d in db.query(PoolDefinition)
                  .order_by(PoolDefinition.catalog_number).limit(4).all()]
    assert len(SLATE_KEYS) == 4, SLATE_KEYS

    # The slate. Slot 1 is a CONTINUATION — it points at the prior week's
    # instance, which is how a carried pot is recorded. It occupies a slot; it
    # does not add one.
    prior = PoolInstance(league_id=ids["A"], season=SEASON, week=WEEK - 1,
                         phase="REGULAR", rotation_cycle=1,
                         definition_key=SLATE_KEYS[0], slot=1, pot_cents=1000,
                         rollover_cents=0, settled=True)
    db.add(prior); db.flush()

    for slot, key in enumerate(SLATE_KEYS, start=1):
        db.add(PoolInstance(
            league_id=ids["A"], season=SEASON, week=WEEK, phase="REGULAR",
            rotation_cycle=1, definition_key=key, slot=slot,
            pot_cents=100 * slot, rollover_cents=1000 if slot == 1 else 0,
            origin_instance_id=prior.id if slot == 1 else None,
            settled=False))
    db.commit()

A_LEAGUE, B_LEAGUE = ids["A"], ids["B"]
SLATE_KEY_0 = SLATE_KEYS[0]
SLATE_NAMES = None


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _session(email: str) -> TestClient:
    c = _client()
    r = c.post("/auth/session", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def _put(client: TestClient, league_id: int, cents: int):
    return client.put(f"/league/{league_id}/settings/pool-entry",
                      json={"cents": cents},
                      headers={CSRF_HEADER: client.cookies.get(CSRF_COOKIE)})


print("=" * 70)
print("S8-P4B-3 — settings and weekly Pool slate")
print("=" * 70)


# ── 1 · Settings read ────────────────────────────────────────────────────────

_section("1 · Settings read from /league/{id}/settings")

comm_a, comm_b, gm_a = _session(A_COMM), _session(B_COMM), _session(A_GM)
body = comm_a.get(f"/league/{A_LEAGUE}/settings").json()

_assert("a league member may read the settings",
        gm_a.get(f"/league/{A_LEAGUE}/settings").status_code == 200)
_assert("a non-member may not",
        comm_b.get(f"/league/{A_LEAGUE}/settings").status_code == 403)

_assert("the Economy Stop is read-only",
        body["economy_stop"]["editable"] is False)
_assert("the Skunk Fee is read-only", body["skunk"]["editable"] is False)
_assert("the Championship split is read-only",
        body["championship_split"]["editable"] is False)
_assert("the Standard Pool Bet is the one mutable row",
        body["pool_entry"]["editable"] is True)
_assert("it publishes the governed bounds",
        body["pool_entry"]["min_cents"] == GOVERNED_MIN_WEEKLY_ENTRY_CENTS
        and body["pool_entry"]["max_cents"] == GOVERNED_MAX_WEEKLY_ENTRY_CENTS,
        f"{body['pool_entry']['min_cents']}–{body['pool_entry']['max_cents']}")


# ── 2 · The command: authority, bounds, freeze ───────────────────────────────

_section("2 · The Standard Pool Bet command")

_assert("an ordinary GM cannot mutate it",
        _put(gm_a, A_LEAGUE, 300).status_code == 403)
_assert("a commissioner of another league cannot mutate this one",
        _put(comm_b, A_LEAGUE, 300).status_code == 403)

ok = _put(comm_a, A_LEAGUE, 300)
_assert("the league's own commissioner may set it", ok.status_code == 200,
        f"{ok.status_code} {ok.text[:120]}")
_assert("the response IS the refreshed authoritative read",
        ok.json()["pool_entry"]["cents"] == 300, ok.text[:120])

with SessionLocal() as db:
    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == A_LEAGUE).first()
    written, legacy = cfg.pool_weekly_entry_cents, cfg.weekly_entry_cents

_assert("it wrote the GOVERNED column, pool_weekly_entry_cents",
        written == 300, str(written))
_assert("and did NOT write the legacy three-pot weekly_entry_cents",
        legacy != 300, f"legacy column is {legacy}")

low = _put(comm_a, A_LEAGUE, GOVERNED_MIN_WEEKLY_ENTRY_CENTS - 1)
high = _put(comm_a, A_LEAGUE, GOVERNED_MAX_WEEKLY_ENTRY_CENTS + 1)
_assert("below the bound is refused, not clamped", low.status_code == 400,
        str(low.status_code))
_assert("above the bound is refused, not clamped", high.status_code == 400,
        str(high.status_code))

with SessionLocal() as db:
    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == A_LEAGUE).first()
    unchanged = cfg.pool_weekly_entry_cents
_assert("a refused write changed nothing — no silent clamp landed",
        unchanged == 300, str(unchanged))

# Freeze, through the governed setter's own recorded state.
from datetime import datetime, timezone  # noqa: E402

with SessionLocal() as db:
    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == A_LEAGUE).first()
    cfg.pool_weekly_entry_frozen_at = datetime.now(timezone.utc)
    db.commit()

frozen = _put(comm_a, A_LEAGUE, 400)
_assert("a frozen entry refuses the change with 409", frozen.status_code == 409,
        str(frozen.status_code))
_assert("and names the governed reason",
        frozen.json()["detail"]["reason_code"] == "ENTRY_FROZEN",
        json.dumps(frozen.json())[:140])
_assert("the settings read then reports it frozen and not editable",
        comm_a.get(f"/league/{A_LEAGUE}/settings").json()["pool_entry"]["frozen"] is True
        and comm_a.get(f"/league/{A_LEAGUE}/settings").json()["pool_entry"]["editable"] is False)


# ── 3 · The slate read ───────────────────────────────────────────────────────

_section("3 · The weekly Pool slate")

drawn = comm_a.get(f"/league/{A_LEAGUE}/pool/slate/{WEEK}").json()
undrawn = comm_a.get(f"/league/{A_LEAGUE}/pool/slate/{WEEK + 1}").json()

_assert("a drawn week reports drawn", drawn["drawn"] is True)
_assert("with exactly four governed slots", len(drawn["slots"]) == 4,
        str(len(drawn["slots"])))
_assert("the governed slot count is four", drawn["slot_count"] == 4)
_assert("slots are ordered by slot number",
        [s["slot"] for s in drawn["slots"]] == [1, 2, 3, 4])
_assert("the continuation occupies slot 1 rather than adding a fifth",
        drawn["slots"][0]["is_continuation"] is True
        and len(drawn["slots"]) == 4)
_assert("no other slot is a continuation",
        [s["is_continuation"] for s in drawn["slots"]] == [True, False, False, False])
_assert("definition identity comes from the catalog, not a frontend list",
        all(s["display_name"] and s["catalog_number"] for s in drawn["slots"]))

_assert("an undrawn week reports drawn: false", undrawn["drawn"] is False)
_assert("and returns NO slots — nothing is synthesised",
        undrawn["slots"] == [], str(undrawn["slots"]))
_assert("a non-member cannot read the slate",
        comm_b.get(f"/league/{A_LEAGUE}/pool/slate/{WEEK}").status_code == 403)


# ── 4 · The models, and the production/demo boundary ─────────────────────────

_section("4 · Settings and slate models keep the production boundary")

NODE_PROBE = r"""
const base = %s;
const S = await import(base + 'settings-model.js');
const P = await import(base + 'pool-slate-model.js');
const R = await import(base + 'rules.js');
const W = await import(base + 'week.js');

const out = { demo: {}, unavailable: {}, drawn: {}, undrawn: {} };

out.demo.settingsMode = S.settingsMode();
out.demo.slateMode = P.slateMode();
out.demo.rows = S.settingsRows().length;
// RC4 - the Wrap Up Prop Pool item is the shared result card now, not a 45px
// list row, so a Pool is counted by the attribute that makes it a Pool rather
// than by the class of the component that used to draw it.
out.demo.poolsInPanel = (W.buildWeekPanel().match(/data-card-action="pool"/g) || []).length;

S.markSettingsUnavailable();
P.markSlateUnavailable();
out.unavailable.settingsMode = S.settingsMode();
out.unavailable.slateMode = P.slateMode();
out.unavailable.rulesHasSettingsMoney =
  R.buildRulesPanel().includes('fs-setrow__value');
out.unavailable.pools = (W.buildWeekPanel().match(/data-card-action="pool"/g) || []).length;

P.bindSlate(%s);
out.drawn.mode = P.slateMode();
out.drawn.rows = P.slateRows().length;
out.drawn.continuations = P.slateRows().filter(r => r.continuation).length;
out.drawn.names = P.slateRows().map(r => r.name);
out.drawn.honours = P.slateHonoursSlotContract();
out.drawn.poolsInPanel = (W.buildWeekPanel().match(/data-card-action="pool"/g) || []).length;

P.bindSlate({ drawn: false, slots: [], slot_count: 4 });
out.undrawn.mode = P.slateMode();
out.undrawn.rows = P.slateRows().length;
out.undrawn.poolsInPanel = (W.buildWeekPanel().match(/data-card-action="pool"/g) || []).length;

S.bindSettings(%s);
out.bound = {
  mode: S.settingsMode(),
  values: S.settingsRows().map(r => [r.id, r.value, r.editable]),
  editableForCommissioner: S.poolEntryEditable(true),
  editableForGm: S.poolEntryEditable(false),
};

console.log(JSON.stringify(out));
"""

url = "file:///" + os.path.join(ROOT, "web", "js").replace("\\", "/").lstrip("/") + "/"
proc = subprocess.run(
    ["node", "--input-type=module", "-e",
     NODE_PROBE % (json.dumps(url), json.dumps(drawn), json.dumps(body))],
    capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
if proc.returncode != 0:
    print(proc.stderr[:1500])
probe = json.loads(proc.stdout) if proc.returncode == 0 else {}

d = probe.get("demo", {})
_assert("the models default to demo for isolated review",
        d.get("settingsMode") == "demo" and d.get("slateMode") == "demo")
_assert("demo still draws the four illustrative launch Pools",
        d.get("poolsInPanel") == 4, str(d.get("poolsInPanel")))

u = probe.get("unavailable", {})
_assert("a refused settings read enters unavailable, not demo",
        u.get("settingsMode") == "unavailable")
_assert("and shows NO settings figures",
        u.get("rulesHasSettingsMoney") is False)
_assert("a refused slate read enters unavailable, not demo",
        u.get("slateMode") == "unavailable")
_assert("and renders NO Pools — never the illustrative launch four",
        u.get("pools") == 0, str(u.get("pools")))

dr = probe.get("drawn", {})
_assert("a drawn slate binds to exactly the served slots",
        dr.get("rows") == 4 and dr.get("poolsInPanel") == 4,
        f"{dr.get('rows')} rows, {dr.get('poolsInPanel')} drawn")
_assert("the continuation is one of the four, not a fifth",
        dr.get("continuations") == 1 and dr.get("rows") == 4)
_assert("names come from the catalog-backed slate, not a frontend list",
        len(dr.get("names", [])) == 4
        and all(isinstance(n, str) and n for n in dr.get("names", [])),
        str(dr.get("names")))
_assert("the four-slot contract is honoured", dr.get("honours") is True)

# The contract is not only a UI convention: the SCHEMA refuses a fifth slot.
# Asserted here so "no fifth Pool" is grounded in something the database
# enforces rather than in a renderer's restraint.
with SessionLocal() as db:
    try:
        db.add(PoolInstance(league_id=A_LEAGUE, season=SEASON, week=WEEK,
                            phase="REGULAR", rotation_cycle=1,
                            definition_key=SLATE_KEY_0, slot=5, pot_cents=0,
                            rollover_cents=0, settled=False))
        db.flush()
        fifth_allowed = True
    except Exception:
        fifth_allowed = False
    db.rollback()

_assert("the database itself refuses a fifth slot",
        fifth_allowed is False)

ud = probe.get("undrawn", {})
_assert("an undrawn slate renders no Pools",
        ud.get("mode") == "undrawn" and ud.get("rows") == 0
        and ud.get("poolsInPanel") == 0,
        f"{ud.get('mode')}, {ud.get('poolsInPanel')} drawn")

bd = probe.get("bound", {})
_assert("bound settings report authoritative mode",
        bd.get("mode") == "authoritative")
_assert("all four rows are present in the locked order",
        [r[0] for r in bd.get("values", [])]
        == ["economy-stop", "pool-bet", "skunk-fee", "championship-split"],
        str([r[0] for r in bd.get("values", [])]))
_assert("only the Pool Bet row is editable",
        [r[2] for r in bd.get("values", [])] == [False, True, False, False],
        str([r[2] for r in bd.get("values", [])]))
_assert("editability additionally requires commissioner capability",
        bd.get("editableForCommissioner") is True
        and bd.get("editableForGm") is False)


# ── 5 · No legacy Pool surface is used as the rotating catalog ───────────────

_section("5 · The legacy three-pot list is not the rotating catalog")

import re  # noqa: E402
import pathlib  # noqa: E402


def _strip(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", " ", src, flags=re.MULTILINE)


APP_JS = [p for p in pathlib.Path("web/js").rglob("*.js")]
APP_CODE = "\n".join(_strip(p.read_text(encoding="utf-8")) for p in APP_JS)

_assert("no frontend module imports the legacy POOL_BET_TYPES",
        "POOL_BET_TYPES" not in APP_CODE)
_assert("no frontend module calls the legacy /pool/config mutation",
        "'/pool/config'" not in APP_CODE and '"/pool/config"' not in APP_CODE)
_assert("the Pool surface reads the governed slate route",
        "/pool/slate/" in APP_CODE)
_assert("Worst Beat never appears as rotating catalog content",
        not re.search(r"worst[\s_-]?beat", APP_CODE, re.I))

with SessionLocal() as db:
    keys = {r.definition_key for r in db.query(PoolInstance).all()}
_assert("no seeded slate slot is a Worst Beat definition",
        not any("worst" in k.lower() for k in keys), str(keys))


print("\n" + "=" * 70)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4B-3 SETTINGS AND POOL SLATE — all assertions PASSED")