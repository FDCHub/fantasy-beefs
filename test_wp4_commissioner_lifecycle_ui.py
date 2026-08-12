#!/usr/bin/env python3
"""
test_wp4_commissioner_lifecycle_ui.py — WP4 · commissioner lifecycle UI.

WHAT THIS CERTIFIES, IN THREE LAYERS.

  1. THE READ MODEL, against a real server. `GET /league/{id}/lifecycle` is the
     only thing WP4 adds to the backend, and it exists because the UI could not
     otherwise answer "Not measured / Insufficient / Ready", could not disable a
     completed action, and could not keep Season Close unavailable without
     reimplementing the close preconditions in the browser — which the scope
     forbids and which would be wrong anyway. It is asserted to be
     commissioner-scoped, to agree with the engines it delegates to, and to
     WRITE NOTHING.

  2. THE MODULES, driven directly. Mode discipline, active-league isolation,
     the duplicate-click guard, and the reason-code translation — including the
     property that matters most, that no governed code ever reaches the page.

  3. THE BROWSER, twice: once as the league's commissioner and once as an
     ordinary GM, against the same build and the same fixture.

NOTHING HERE IS PROVED BY A SCREENSHOT. Every assertion reads state, the DOM,
or the network timeline.

WHAT THIS SUITE DOES NOT CLAIM. The finality refusal's HTTP shape —
ResultsNotReadyError to a 409 carrying `RESULTS_NOT_READY` — is WP2B-D's and is
already accepted; the settle route reaches Yahoo before it reaches the finality
gate, so no credential-free environment can produce that refusal over the wire.
WP4 owns what the SURFACE does with it, and that is certified against the real
command module, the real model and the real rendered DOM.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'wp4.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


print("=" * 78)
print("WP4 — commissioner lifecycle UI")
print("=" * 78)


# ══ Fixture ═════════════════════════════════════════════════════════════════

from datetime import datetime, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from auth.jwt_auth import hash_password  # noqa: E402
from auth.session import CSRF_COOKIE, CSRF_HEADER  # noqa: E402
from betting.pool_catalog import seed_definitions  # noqa: E402
from betting.pool_gates import record_activation_measurement  # noqa: E402
from betting.pool_rotation import DEFAULT_SLOT_COUNT  # noqa: E402
from db.schema import (  # noqa: E402
    Base, League, LeagueCommissioner, PoolDefinition, PoolInstance, SessionLocal,
    Team, User, Wallet, engine,
)
from ledger.ledger import create_ledger_table, trial_balance  # noqa: E402
from providers.yahoo.pool_source import PROVIDER  # noqa: E402

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "wp4-password"
SEASON, WEEK = 2026, 5
A_COMM, A_GM, B_COMM = "comm.a@wp4.test", "gm.a@wp4.test", "comm.b@wp4.test"


def _seed_team(db, league, name, email, role="gm"):
    team = Team(team_name=name, owner=name, email=email, league_id=league.id)
    db.add(team); db.flush()
    db.add(User(email=email, hashed_password=hash_password(PASSWORD),
                team_id=team.id, role=role))
    db.add(Wallet(team_id=team.id, balance=0.0))
    db.flush()
    return team


with SessionLocal() as db:
    league_a = League(name="WP4 League", season=SEASON, provider="yahoo",
                      provider_league_key="461.l.wp4",
                      provider_current_week=WEEK)
    league_b = League(name="Other League", season=SEASON)
    db.add_all([league_a, league_b]); db.flush()

    comm_team = _seed_team(db, league_a, "The Chair", A_COMM, role="commissioner")
    gm_team = _seed_team(db, league_a, "Gravy Train", A_GM)
    b_team = _seed_team(db, league_b, "Elsewhere", B_COMM, role="commissioner")

    for lg, email in ((league_a, A_COMM), (league_b, B_COMM)):
        db.add(LeagueCommissioner(
            league_id=lg.id, source="bootstrap",
            user_id=db.query(User).filter(User.email == email).one().id))

    seed_definitions(db)

    # THE SEASON ALLOCATION, POSTED UNDER ITS OWN GOVERNING DOOR. Week Open
    # releases from `min_reserve:{team}` and refuses rather than over-releasing
    # an allocation that was never made — which is the service working, not a
    # fixture inconvenience. A league that has not been activated genuinely
    # cannot open a week, so the fixture activates it the way the real path
    # does instead of relaxing the guard.
    from economy.current_settle import DOOR_SEASON_ALLOCATION
    from economy.economy_events import min_reserve_account
    from ledger.ledger import post as ledger_post

    for _team in (comm_team, gm_team):
        ledger_post([(min_reserve_account(_team.id), 14_000),
                     ("world", -14_000)],
                    door=DOOR_SEASON_ALLOCATION, session=db)
        db.flush()

    db.commit()
    A_LEAGUE, B_LEAGUE = league_a.id, league_b.id
    COMM_TEAM, GM_TEAM = comm_team.id, gm_team.id


def _session(email: str | None) -> TestClient:
    client = TestClient(app, raise_server_exceptions=False)
    if email:
        r = client.post("/auth/session", json={"email": email,
                                               "password": PASSWORD})
        assert r.status_code == 200, r.text
    return client


comm_a, gm_a, comm_b, anon = (_session(A_COMM), _session(A_GM),
                              _session(B_COMM), _session(None))


def _lifecycle(client: TestClient, league_id: int = A_LEAGUE):
    return client.get(f"/league/{league_id}/lifecycle")


# ══ 1 · The read model is commissioner-scoped ═══════════════════════════════

_section("1 · Authority on the lifecycle read")

_assert("the league's own commissioner may read it",
        _lifecycle(comm_a).status_code == 200,
        str(_lifecycle(comm_a).status_code))
_assert("an ordinary GM of the same league may NOT",
        _lifecycle(gm_a).status_code == 403,
        str(_lifecycle(gm_a).status_code))
_assert("a commissioner of ANOTHER league may not read this one",
        _lifecycle(comm_b).status_code == 403,
        str(_lifecycle(comm_b).status_code))
_assert("an unauthenticated request is refused",
        _lifecycle(anon).status_code in (401, 403),
        str(_lifecycle(anon).status_code))


# ══ 2 · The read writes nothing ═════════════════════════════════════════════

_section("2 · A readiness question leaves no transaction behind it")


def _state_fingerprint() -> tuple:
    with SessionLocal() as db:
        return (
            db.query(PoolInstance).count(),
            db.query(Team).count(),
            trial_balance(),
            db.query(League).filter(League.id == A_LEAGUE).one().season_closed_at,
        )


_before_fp = _state_fingerprint()
for _ in range(3):
    _lifecycle(comm_a)
_after_fp = _state_fingerprint()

_assert("three lifecycle reads changed nothing at all",
        _before_fp == _after_fp, f"{_before_fp} → {_after_fp}")
_assert("and the ledger still balances", trial_balance() == 0,
        str(trial_balance()))


# ══ 3 · Pool support: the three governed answers ════════════════════════════

_section("3 · Pool support — Not measured / Insufficient / Ready")

body = _lifecycle(comm_a).json()
_assert("a league that has never been measured reports not_measured",
        body["pool_support"]["state"] == "not_measured",
        json.dumps(body["pool_support"]))
_assert("and names no measurement time",
        body["pool_support"]["measured_at"] is None)
_assert("the slate requirement is the governed slot count, not a UI constant",
        body["pool_support"]["required_for_slate"] == DEFAULT_SLOT_COUNT,
        f"{body['pool_support']['required_for_slate']} vs {DEFAULT_SLOT_COUNT}")

# ONE READY DEFINITION IS NOT A SLATE. Measured, but short of the four a week
# needs — which is exactly the state the product calls "Insufficient" and the
# state a two-valued on/off answer would have hidden.
with SessionLocal() as db:
    gate1_keys = [d.key for d in db.query(PoolDefinition)
                  .filter(PoolDefinition.definition_runtime_eligible.is_(True))
                  .order_by(PoolDefinition.catalog_number).all()]
    now = datetime.now(timezone.utc)
    record_activation_measurement(db, league_id=A_LEAGUE, provider=PROVIDER,
                                  definition_key=gate1_keys[0], ready=True,
                                  measured_at=now)
    db.commit()

body = _lifecycle(comm_a).json()
_assert("a measured league short of a full slate reports insufficient",
        body["pool_support"]["state"] == "insufficient",
        json.dumps(body["pool_support"]))
_assert("and it now carries the measurement time",
        body["pool_support"]["measured_at"] is not None,
        str(body["pool_support"]["measured_at"]))

with SessionLocal() as db:
    for key in gate1_keys[:DEFAULT_SLOT_COUNT]:
        record_activation_measurement(db, league_id=A_LEAGUE, provider=PROVIDER,
                                      definition_key=key, ready=True,
                                      measured_at=datetime.now(timezone.utc))
    db.commit()

body = _lifecycle(comm_a).json()
_assert("a full slate's worth of ready definitions reports ready",
        body["pool_support"]["state"] == "ready",
        json.dumps(body["pool_support"]))

# THE GATE'S OWN ANSWER, NOT A ROW COUNT. A stale measurement fails closed
# inside `selectable_definitions`, and the read model must inherit that rather
# than counting `ready` columns and disagreeing with the slate builder.
with SessionLocal() as db:
    for key in gate1_keys[:DEFAULT_SLOT_COUNT]:
        record_activation_measurement(
            db, league_id=A_LEAGUE, provider=PROVIDER, definition_key=key,
            ready=True, measured_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    db.commit()

stale = _lifecycle(comm_a).json()["pool_support"]
_assert("a STALE measurement falls back to insufficient, not ready",
        stale["state"] == "insufficient", json.dumps(stale))
_assert("the read defers to the gate rather than to the ready flag",
        stale["definitions_ready"] >= DEFAULT_SLOT_COUNT
        and stale["eligible_for_slate"] < DEFAULT_SLOT_COUNT,
        f"{stale['definitions_ready']} rows ready, "
        f"{stale['eligible_for_slate']} selectable")

with SessionLocal() as db:
    for key in gate1_keys[:DEFAULT_SLOT_COUNT]:
        record_activation_measurement(db, league_id=A_LEAGUE, provider=PROVIDER,
                                      definition_key=key, ready=True,
                                      measured_at=datetime.now(timezone.utc))
    db.commit()


# ══ 4 · The week: state tracks the governed services ════════════════════════

_section("4 · The week — opened, collected, settled, closed")

week = _lifecycle(comm_a).json()["week"]
_assert("the week comes from the league, not from the client",
        week["week"] == WEEK and week["week_resolved"] is True,
        json.dumps(week))
_assert("nothing has been opened yet",
        week["opened"] is False and week["released_teams"] == 0,
        json.dumps(week))
_assert("and nothing collected or settled",
        week["collected"] is False and week["settled"] is False)

# Week Open through the governed route, then read the state back.
open_r = comm_a.post(f"/league/{A_LEAGUE}/week/{WEEK}/open",
                     headers={CSRF_HEADER: comm_a.cookies.get(CSRF_COOKIE)})
_assert("Week Open is accepted for the league's commissioner",
        open_r.status_code == 200, f"{open_r.status_code} {open_r.text[:120]}")

week = _lifecycle(comm_a).json()["week"]
_assert("the read then reports the week OPEN",
        week["opened"] is True, json.dumps(week))
_assert("with every team released",
        week["released_teams"] == week["teams"] == 2, json.dumps(week))

# A REPEAT IS SAFE AND IS REPORTED AS A REPLAY. This is what lets the surface
# distinguish "this call did the work" from "the work was already done".
repeat = comm_a.post(f"/league/{A_LEAGUE}/week/{WEEK}/open",
                     headers={CSRF_HEADER: comm_a.cookies.get(CSRF_COOKIE)})
_assert("a repeated Week Open is safe and reports already_open",
        repeat.status_code == 200 and repeat.json()["already_open"] is True,
        f"{repeat.status_code} {repeat.text[:120]}")

# Collection state is read from the persisted occurrences.
with SessionLocal() as db:
    for slot, key in enumerate(gate1_keys[:DEFAULT_SLOT_COUNT], start=1):
        db.add(PoolInstance(league_id=A_LEAGUE, season=SEASON, week=WEEK,
                            phase="REGULAR", rotation_cycle=1,
                            definition_key=key, slot=slot, pot_cents=100 * slot,
                            rollover_cents=0, settled=False))
    db.commit()

week = _lifecycle(comm_a).json()["week"]
_assert("a week with occupied Pool slots reports collected",
        week["collected"] is True and week["pool_instances"] == DEFAULT_SLOT_COUNT,
        json.dumps(week))
_assert("and NOT settled while any occurrence is open",
        week["settled"] is False and week["pool_settled"] == 0,
        json.dumps(week))

with SessionLocal() as db:
    for instance in (db.query(PoolInstance)
                     .filter(PoolInstance.league_id == A_LEAGUE,
                             PoolInstance.week == WEEK).all()):
        instance.settled = True
    db.commit()

week = _lifecycle(comm_a).json()["week"]
_assert("once every occurrence is settled the week reports settled",
        week["settled"] is True
        and week["pool_settled"] == week["pool_instances"],
        json.dumps(week))

close_r = comm_a.post(f"/league/{A_LEAGUE}/week/{WEEK}/close",
                      headers={CSRF_HEADER: comm_a.cookies.get(CSRF_COOKIE)})
_assert("Week Close is accepted", close_r.status_code == 200,
        f"{close_r.status_code} {close_r.text[:120]}")

week = _lifecycle(comm_a).json()["week"]
_assert("and the read then reports the week CLOSED",
        week["closed"] is True and week["expired_teams"] == week["teams"],
        json.dumps(week))


# ══ 5 · Season close readiness is the orchestrator's own answer ═════════════

_section("5 · Season close readiness comes from verify_preconditions")

season = _lifecycle(comm_a).json()["season_close"]
_assert("the season is not closed", season["closed"] is False)
_assert("and readiness is a definite answer", isinstance(season["ready"], bool),
        json.dumps(season))

# WHATEVER THE ANSWER, IT MUST AGREE WITH THE ORCHESTRATOR ITSELF. Calling
# `verify_preconditions` directly and comparing is what makes this a delegation
# rather than a second opinion that happens to look similar.
from betting.pool_season_boundary import season_final_week  # noqa: E402
from economy.season_close_orchestrator import (  # noqa: E402
    SeasonClosePreconditionError, verify_preconditions,
)

with SessionLocal() as db:
    _league = db.query(League).filter(League.id == A_LEAGUE).one()
    _final = season_final_week(_league)
    try:
        verify_preconditions(db, league_id=A_LEAGUE, final_week=_final)
        direct_ready, direct_step = True, None
    except SeasonClosePreconditionError as exc:
        direct_ready, direct_step = False, exc.step
    db.rollback()

_assert("the route's readiness matches the orchestrator's own verdict",
        season["ready"] == direct_ready,
        f"route={season['ready']}, orchestrator={direct_ready}")
_assert("and the blocking code is the orchestrator's step name, passed through",
        season["blocking_reason_code"] == direct_step,
        f"route={season['blocking_reason_code']}, orchestrator={direct_step}")
_assert("the final week is the league's own, never taken from a caller",
        season["final_week"] == _final, str(season["final_week"]))

# THE BLOCKED PATH, DRIVEN RATHER THAN WAITED FOR. A suite that only ever saw
# whichever verdict the fixture happened to produce would certify one branch and
# assume the other. An unsettled occurrence is the cleanest governed blocker to
# introduce, and it is removed again afterwards.
with SessionLocal() as db:
    # A definition the week-5 slate did NOT use: within one rotation cycle a
    # definition is unique per league-season, which is the rotation's own
    # anti-redraw constraint doing its job.
    _blocker = PoolInstance(league_id=A_LEAGUE, season=SEASON, week=WEEK + 1,
                            phase="REGULAR", rotation_cycle=1,
                            definition_key=gate1_keys[DEFAULT_SLOT_COUNT],
                            slot=1, pot_cents=100, rollover_cents=0,
                            settled=False)
    db.add(_blocker); db.commit()
    _blocker_id = _blocker.id

blocked = _lifecycle(comm_a).json()["season_close"]
_assert("an unsettled Pool occurrence makes the season NOT ready to close",
        blocked["ready"] is False, json.dumps(blocked))
_assert("and the governed step name is passed through untouched",
        blocked["blocking_reason_code"] == "pool_settled",
        str(blocked["blocking_reason_code"]))
_assert("with the orchestrator's own operator prose alongside it",
        isinstance(blocked["blocking_message"], str)
        and "unsettled" in blocked["blocking_message"],
        str(blocked["blocking_message"])[:90])

with SessionLocal() as db:
    db.query(PoolInstance).filter(PoolInstance.id == _blocker_id).delete()
    db.commit()

_assert("removing the blocker restores readiness — the read is live, not cached",
        _lifecycle(comm_a).json()["season_close"]["ready"] is True)

# THE GOVERNED VOCABULARY THE SCOPE NAMES. Asserted against the orchestrator's
# source so the client's translation table cannot drift from what can arrive.
GOVERNED_STEPS = {
    "versus_terminal", "pool_settled", "escrow_resolved",
    "weekly_minimum_expiry", "results_not_ready", "skunk_assessed",
    "pool_rollover", "pool_zero", "provider_conflict",
}
_orch_src = open(os.path.join(ROOT, "economy", "season_close_orchestrator.py"),
                 encoding="utf-8").read()
_missing_steps = sorted(s for s in GOVERNED_STEPS
                        if f'"{s}"' not in _orch_src and s != "results_not_ready")
_assert("every governed step the scope names still exists in the orchestrator",
        not _missing_steps, f"absent: {_missing_steps}")


# ══ 6 · The frontend modules ════════════════════════════════════════════════

_section("6 · Mode discipline, active-league isolation, duplicate-click")

LIFECYCLE_BODY = {
    "league_id": A_LEAGUE, "season": SEASON,
    "pool_support": {"state": "ready", "measured_at": "2026-08-01T00:00:00+00:00",
                     "definitions_ready": 4, "eligible_for_slate": 4,
                     "required_for_slate": 4, "provider": "yahoo"},
    "week": {"week": 5, "week_resolved": True, "is_release_week": True,
             "teams": 2, "released_teams": 0, "expired_teams": 0,
             "opened": False, "closed": False, "pool_instances": 0,
             "pool_settled": 0, "collected": False, "settled": False},
    "season_close": {"final_week": 14, "closed": False, "closed_at": None,
                     "ready": False, "blocking_reason_code": "pool_settled",
                     "blocking_message": "3 Pool occurrence(s) are unsettled "
                                         "for league 1."},
}

NODE_PROBE = r"""
const base = %s;
const M = await import(base + 'lifecycle-model.js');
const V = await import(base + 'lifecycle.js');
const C = await import(base + 'lifecycle-command.js');
const R = await import(base + 'rules.js');

const BODY = %s;
const A = %d, B = %d;
const out = {};
const controls = (html) => (html.match(/data-lifecycle-action=/g) || []).length;

/* ── Nothing bound: no controls, and NO invented state ── */
out.demo = {
  mode: M.lifecycleMode(),
  controls: controls(R.buildRulesPanel()),
  poolSupport: M.poolSupport(),
  week: M.weekLifecycle(),
};

/* ── A non-commissioner, even with state bound ── */
V.setLifecycleCapability(false);
M.applyLeague(A);
M.bindLifecycle(A, BODY);
out.gm = {
  controls: controls(R.buildRulesPanel()),
  state: (R.buildRulesPanel().match(/id="fs-lifecycle" data-league="\d+" data-state="([a-z-]+)"/) || [])[1],
};

/* ── The commissioner ── */
V.setLifecycleCapability(true);
V.setSeasonBlocker(C.explainPrerequisite(BODY.season_close.blocking_reason_code));
let html = R.buildRulesPanel();
out.commissioner = {
  mode: M.lifecycleMode(),
  controls: controls(html),
  sections: (html.match(/data-lifecycle="(setup|week|season)"/g) || []).length,
  league: (html.match(/id="fs-lifecycle" data-league="(\d+)"/) || [])[1],
  seasonDisabled: /data-lifecycle-action="season-close" disabled/.test(html),
  seasonWhy: (html.match(/data-lifecycle-why="season-close">([^<]*)</) || [])[1],
  settleDisabled: /data-lifecycle-action="pool-settle" disabled/.test(html),
  openEnabled: /data-lifecycle-action="week-open">/.test(html),
};

/* ── A refused read shows no state and no controls ── */
M.markLifecycleUnavailable(A);
out.unavailable = {
  mode: M.lifecycleMode(),
  controls: controls(R.buildRulesPanel()),
  poolSupport: M.poolSupport(),
};

/* ── Completed actions are disabled, each with a stated reason ── */
M.bindLifecycle(A, { ...BODY, week: { ...BODY.week, opened: true,
  collected: true, settled: true, closed: true } });
html = R.buildRulesPanel();
out.completed = {
  disabled: (html.match(/data-lifecycle-action="[a-z-]+" disabled/g) || []).length,
  whys: (html.match(/data-lifecycle-why="[a-z-]+"/g) || []).length,
};

/* ── ACTIVE-LEAGUE ISOLATION ── */
M.recordResult(A, 'week-open', { status: 'success', message: 'LEAGUE-A-BANNER' });
out.isolation = {};
out.isolation.beforeSwitch = R.buildRulesPanel().includes('LEAGUE-A-BANNER');

const switched = M.applyLeague(B);
html = R.buildRulesPanel();
out.isolation.switchReported = switched;
out.isolation.staleBanner = html.includes('LEAGUE-A-BANNER');
out.isolation.staleWeek = /data-lifecycle="week" data-week="5"/.test(html);
out.isolation.modeAfter = M.lifecycleMode();
out.isolation.leagueAfter = M.lifecycleLeagueId();
out.isolation.controlsAfter = controls(html);

/* A reply that lands AFTER the switch is dropped, not merged. */
M.bindLifecycle(A, BODY);
out.isolation.lateBindIgnored = M.servedLifecycle() === null;
M.recordResult(A, 'week-open', { status: 'success', message: 'LATE-A-BANNER' });
out.isolation.lateResultIgnored = M.actionResult('week-open') === null;
out.isolation.lateBannerDrawn = R.buildRulesPanel().includes('LATE-A-BANNER');

/* ── DUPLICATE-CLICK GUARD ── */
out.duplicate = {
  first: M.claimAction('week-open'),
  second: M.claimAction('week-open'),
  third: M.claimAction('week-open'),
};
M.releaseAction('week-open');
out.duplicate.afterRelease = M.claimAction('week-open');
M.releaseAction('week-open');

/* An in-flight action draws its control disabled and busy. */
M.applyLeague(B);
M.bindLifecycle(B, BODY);
M.claimAction('week-open');
html = R.buildRulesPanel();
out.inFlight = {
  disabled: /data-lifecycle-action="week-open" disabled/.test(html),
  busy: /aria-busy="true"/.test(html),
  label: /Working…/.test(html),
};
M.releaseAction('week-open');

/* ── REASON-CODE TRANSLATION ── */
const CODES = %s;
out.translation = {};
for (const code of CODES) {
  const err = new C.LifecycleCommandError(409, code, '[' + code + '] operator prose', {});
  const sentence = C.explainRefusal(err);
  out.translation[code] = {
    sentence,
    leaksCode: sentence.toLowerCase().includes(code.toLowerCase()),
    isSentence: /[a-z]{3,}\s+[a-z]{3,}/i.test(sentence) && sentence.length > 25,
    waiting: C.isWaitingState(err),
  };
}
out.uppercaseFolds =
  C.explainRefusal(new C.LifecycleCommandError(409, 'RESULTS_NOT_READY', 'x', {}))
  === C.explainRefusal(new C.LifecycleCommandError(409, 'results_not_ready', 'y', {}));
out.forbidden403 = C.explainRefusal(new C.LifecycleCommandError(403, null, '', {}));
out.bareCodeNotEchoed =
  C.explainRefusal(new C.LifecycleCommandError(409, 'SOMETHING_NEW', 'SOMETHING_NEW', {}));

console.log(JSON.stringify(out));
"""

_url = ("file:///" + os.path.join(ROOT, "web", "js").replace("\\", "/").lstrip("/")
        + "/")
_codes = sorted(GOVERNED_STEPS | {
    "already_collected", "prior_week_unsettled", "not_applicable_week",
    "insufficient_reserve", "no_provider_identity", "provider_unavailable",
    "entry_frozen", "season_close_conflict",
})

_proc = subprocess.run(
    ["node", "--input-type=module", "-e",
     NODE_PROBE % (json.dumps(_url), json.dumps(LIFECYCLE_BODY), A_LEAGUE,
                   B_LEAGUE, json.dumps(_codes))],
    capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
if _proc.returncode != 0:
    print(_proc.stderr[:2000])
probe = json.loads(_proc.stdout) if _proc.returncode == 0 else {}

_assert("the module probe ran", _proc.returncode == 0,
        _proc.stderr[:200] if _proc.returncode else "exit 0")

d = probe.get("demo", {})
_assert("nothing bound means NO controls and NO invented lifecycle",
        d.get("controls") == 0 and d.get("poolSupport") is None
        and d.get("week") is None, json.dumps(d))

g = probe.get("gm", {})
_assert("a non-commissioner is drawn ZERO controls even with state bound",
        g.get("controls") == 0, str(g.get("controls")))
_assert("and the region says so rather than going blank",
        g.get("state") == "not-commissioner", str(g.get("state")))

c = probe.get("commissioner", {})
_assert("a commissioner is drawn all six lifecycle controls",
        c.get("controls") == 6, str(c.get("controls")))
_assert("in three sections", c.get("sections") == 3, str(c.get("sections")))
_assert("scoped to the active league", c.get("league") == str(A_LEAGUE),
        str(c.get("league")))
_assert("Season Close is unavailable while the server says it is not ready",
        c.get("seasonDisabled") is True)
_assert("and the outstanding prerequisite is explained in product language",
        isinstance(c.get("seasonWhy"), str)
        and len(c.get("seasonWhy") or "") > 25
        and "pool_settled" not in (c.get("seasonWhy") or ""),
        (c.get("seasonWhy") or "")[:90])
_assert("an action whose predecessor has not run is unavailable",
        c.get("settleDisabled") is True, "settle before collect")
_assert("and an action that is due is offered", c.get("openEnabled") is True)

u = probe.get("unavailable", {})
_assert("a refused lifecycle read enters unavailable, never demo",
        u.get("mode") == "unavailable", str(u.get("mode")))
_assert("and offers no control against a state nobody knows",
        u.get("controls") == 0 and u.get("poolSupport") is None,
        json.dumps(u))

comp = probe.get("completed", {})
_assert("every already-complete action is disabled",
        comp.get("disabled") == 5, f"{comp.get('disabled')} of 5 disabled")
_assert("and every disabled control states why",
        comp.get("whys") == comp.get("disabled"),
        f"{comp.get('whys')} reasons for {comp.get('disabled')} disabled")

iso = probe.get("isolation", {})
_assert("a result is shown for the league it belongs to",
        iso.get("beforeSwitch") is True)
_assert("switching leagues is reported as a switch",
        iso.get("switchReported") is True)
_assert("switching leagues clears the previous league's success state",
        iso.get("staleBanner") is False)
_assert("and the previous league's week state",
        iso.get("staleWeek") is False)
_assert("and offers no controls until the new league is read",
        iso.get("controlsAfter") == 0, str(iso.get("controlsAfter")))
_assert("the model now names the NEW league",
        iso.get("leagueAfter") == B_LEAGUE, str(iso.get("leagueAfter")))
_assert("a read that lands after the switch is DROPPED, not merged",
        iso.get("lateBindIgnored") is True)
_assert("and so is a result for the league that was left",
        iso.get("lateResultIgnored") is True
        and iso.get("lateBannerDrawn") is False)

dup = probe.get("duplicate", {})
_assert("the first click claims the action",
        dup.get("first") is True)
_assert("a second and third click in the same frame are REFUSED dispatch",
        dup.get("second") is False and dup.get("third") is False,
        json.dumps(dup))
_assert("and the action is claimable again once the request settles",
        dup.get("afterRelease") is True)

fl = probe.get("inFlight", {})
_assert("an in-flight control is disabled, marked busy and relabelled",
        fl.get("disabled") is True and fl.get("busy") is True
        and fl.get("label") is True, json.dumps(fl))


# ══ 7 · No governed code reaches the page ═══════════════════════════════════

_section("7 · Reason codes are translated, never exposed")

translation = probe.get("translation", {})
_assert("every governed reason code the routes can answer with is translated",
        len(translation) == len(_codes), f"{len(translation)} of {len(_codes)}")

_leaks = sorted(k for k, v in translation.items() if v.get("leaksCode"))
_assert("NO translation echoes the raw code back to the commissioner",
        not _leaks, f"leaked: {_leaks}")

_terse = sorted(k for k, v in translation.items() if not v.get("isSentence"))
_assert("and every one is a sentence, not a label",
        not _terse, f"not sentences: {_terse}")

_assert("RESULTS_NOT_READY is classified as WAITING, not as a refusal",
        translation.get("results_not_ready", {}).get("waiting") is True)
_assert("and it is the ONLY code treated that way",
        sorted(k for k, v in translation.items() if v.get("waiting"))
        == ["results_not_ready"],
        str(sorted(k for k, v in translation.items() if v.get("waiting"))))
_assert("its copy says results are not final yet",
        "not final yet" in translation.get("results_not_ready", {})
        .get("sentence", "").lower(),
        translation.get("results_not_ready", {}).get("sentence", "")[:90])

_assert("the two case conventions fold to one answer",
        probe.get("uppercaseFolds") is True,
        "RESULTS_NOT_READY and results_not_ready agree")
_assert("a 403 is explained as missing commissioner authority",
        "commissioner authority" in (probe.get("forbidden403") or ""),
        (probe.get("forbidden403") or "")[:90])
_assert("an UNKNOWN code is never echoed as prose either",
        "SOMETHING_NEW" not in (probe.get("bareCodeNotEchoed") or ""),
        (probe.get("bareCodeNotEchoed") or "")[:90])

# The surface itself must not name a route or a reason code in its copy.
import re  # noqa: E402


def _strip(src: str) -> str:
    src = re.sub(r"/\*[\s\S]*?\*/", " ", src)
    return re.sub(r"^\s*//.*$", " ", src, flags=re.MULTILINE)


_view = _strip(open(os.path.join(ROOT, "web", "js", "lifecycle.js"),
                    encoding="utf-8").read())
_assert("the lifecycle surface names no route path in its copy",
        "/league/" not in _view, "no endpoint drawn on the page")
_assert("and no engine identifier",
        not re.search(r"PoolDefinition|record_activation_measurement|"
                      r"pool_gates|definition_key|verify_preconditions", _view))

_app_js = [os.path.join(dp, f) for dp, _, fs in os.walk(os.path.join(ROOT, "web", "js"))
           for f in fs if f.endswith(".js")]
_offenders = sorted(os.path.basename(p) for p in _app_js
                    if re.search(r"\bfetch\s*\(", _strip(
                        open(p, encoding="utf-8").read())))
_assert("the lifecycle modules did not open a second network door",
        _offenders == ["session.js"], str(_offenders))


# ══ 8 · The browser ═════════════════════════════════════════════════════════

_section("8 · The browser — commissioner, and an ordinary GM")

from test_support_app_server import (  # noqa: E402
    COMMISSIONER_EMAIL, GM_EMAIL, AppServer,
)


def _run_browser(script: str, email: str, label: str) -> None:
    """Run one node browser suite against a disposable application."""
    # THE POOL SLATE IS SEEDED so the week has real occupied slots — which is
    # what puts "already collected" and "settle is offered" into the fixture.
    with AppServer(seed_pool_slate=True) as server:
        result = subprocess.run(
            [_node(), os.path.join("web", "tests", script),
             *server.browser_args(authenticate_as=email)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ROOT, timeout=600)

    passed = result.stdout.count("[PASS]")
    failed = result.stdout.count("[FAIL]")
    if failed or result.returncode != 0:
        print(result.stdout[-6000:])
        if result.stderr:
            print(result.stderr[-2000:])
    _assert(label, failed == 0 and result.returncode == 0,
            f"{passed} PASS / {failed} FAIL, exit {result.returncode}")


def _node() -> str:
    return "node"


_run_browser("wp4_lifecycle_browser.mjs", COMMISSIONER_EMAIL,
             "the commissioner browser suite is green")
_run_browser("wp4_lifecycle_gm_browser.mjs", GM_EMAIL,
             "the non-commissioner browser suite is green")


print("\n" + "=" * 78)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("WP4 COMMISSIONER LIFECYCLE UI — all assertions PASSED")
