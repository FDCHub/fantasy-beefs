#!/usr/bin/env python3
"""
test_wp3d_provider_attribution.py — WP3D · provider identity and Yahoo attribution.

FOUR CLAIMS, AND THEY FAIL IN DIFFERENT WAYS.

  1. THE ATTRIBUTION IS CONTRACTUAL TEXT. `Fantasy data provided by Yahoo
     Fantasy` is required character for character by the executed Yahoo API
     Access and Use Agreement, recorded in Rev 4.3 §23. A paraphrase is not a
     smaller version of compliance; it is non-compliance. §1 asserts the exact
     bytes and asserts that every disallowed substitution is absent.

  2. DEMO MUST NEVER CARRY IT. The same five-tab component renders both a
     synthetic Demo league and a live Yahoo one, so the decision cannot come
     from the page — it must come from the authoritative provider binding. §3
     drives the real application under all four reachable server states and
     reads what each one renders.

  3. DIAGNOSTICS STAY BEHIND THE AUTHORIZATION BOUNDARY. An ordinary member
     must not be able to read — or be sent — provider exception detail, HTTP
     codes, endpoint names or sync internals. §5 proves the boundary from both
     sides: refused for a GM, served for a commissioner.

  4. THE SIXTH LABEL IS DEFINED AND UNREACHABLE, on purpose. `YAHOO · SYNCING`
     stays in the vocabulary; no backend fact can select it, and §2 asserts
     that rather than leaving a reader to wonder whether it was forgotten.

DATABASE. A temp SQLite file per run for the in-process fixture; the browser
tier runs against disposable application servers of its own.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'wp3d.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient                          # noqa: E402

from api.main import app                                           # noqa: E402
from auth.jwt_auth import hash_password                            # noqa: E402
from db.schema import (                                            # noqa: E402
    Base, League, LeagueCommissioner, SessionLocal, Team, User, Wallet, engine,
)
from ledger.ledger import create_ledger_table                      # noqa: E402
from reports.league_read_model import (                            # noqa: E402
    PROVIDER_ABSENT, PROVIDER_BOUND, PROVIDER_PENDING, _provider_state,
)
from test_support_app_server import (                              # noqa: E402
    AppServer, COMMISSIONER_EMAIL as APP_COMM_EMAIL,
    GM_EMAIL as APP_GM_EMAIL, PASSWORD as APP_PASSWORD,
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


WEB = os.path.join(ROOT, "web", "js")


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _code_only(source: str) -> str:
    """Executable JavaScript, with comments removed but strings KEPT.

    STRINGS ARE THE SUBJECT HERE, which is the opposite of the WP3C scans. This
    package is about exact rendered copy, so a scan that stripped string
    literals would be unable to see the thing it is checking. Comments still go:
    the modules below discuss the forbidden phrases at length in order to
    explain why they are forbidden.
    """
    stripped = re.sub(r"/\*[\s\S]*?\*/", " ", source)
    return re.sub(r"^\s*//.*$", " ", stripped, flags=re.M)


# ── 1 · The contractual string, exactly ──────────────────────────────────────

_section("1 · The attribution is the agreement's own words, and only those")

REQUIRED = "Fantasy data provided by Yahoo Fantasy"
HREF = "https://football.fantasysports.yahoo.com/"

ATTRIBUTION_JS = _read("web", "js", "attribution.js")
# CODE ONLY FOR THE COUNT. The module's own header quotes the required string in
# order to say that it is contractual and must not be edited — a scan that
# counted that sentence would punish the documentation for existing.
ATTRIBUTION_CODE = _code_only(ATTRIBUTION_JS)

_assert("the required text appears in the product, byte for byte",
        REQUIRED in ATTRIBUTION_CODE)
_assert("and it is written ONCE, so there is one thing to audit",
        ATTRIBUTION_CODE.count(REQUIRED) == 1,
        f"{ATTRIBUTION_CODE.count(REQUIRED)} occurrences")
_assert("it is a constant, not assembled from parts at render time",
        f"YAHOO_ATTRIBUTION_TEXT = '{REQUIRED}'" in ATTRIBUTION_CODE)
_assert("the hyperlink target is the ruled official Yahoo Fantasy destination",
        f"YAHOO_ATTRIBUTION_HREF = '{HREF}'" in ATTRIBUTION_JS)
_assert("and the URL is a link target, never visible copy",
        f">{HREF}<" not in ATTRIBUTION_JS
        and f"escapeHtml(YAHOO_ATTRIBUTION_HREF)" not in ATTRIBUTION_JS)

# THE WHOLE FRONTEND, not just the attribution module. A forbidden phrase is
# forbidden wherever it is written, and the one place nobody would think to
# check is the place it would survive.
FRONTEND = "\n".join(
    _code_only(_read("web", "js", name))
    for name in sorted(os.listdir(WEB)) if name.endswith(".js"))
FRONTEND += "\n" + "\n".join(
    _code_only(_read("web", "js", "data", name))
    for name in sorted(os.listdir(os.path.join(WEB, "data")))
    if name.endswith(".js"))

for banned in ("Powered by Yahoo", "Official Yahoo partner",
               "Yahoo-approved sportsbook", "Yahoo-approved",
               "Yahoo sportsbook", "Yahoo odds", "Built with Yahoo",
               "Yahoo Fantasy Sports data", "Yahoo data",
               "in partnership with Yahoo", "endorsed by Yahoo"):
    _assert(f"no disallowed substitution: {banned!r}",
            banned not in FRONTEND)

# CODE ONLY FOR THE PHRASE SCANS BELOW, for the same reason: `preview.js` and
# `week.js` both explain at length WHY they no longer claim official standing,
# and `attribution.js` lists the forbidden substitutions in its header so the
# next reader does not have to rediscover them.
_assert("no Yahoo logo, mark or image is introduced",
        not re.search(r"yahoo[^\"']*\.(svg|png|jpg|gif|webp)", FRONTEND, re.I)
        and "yahoo-logo" not in FRONTEND.lower())

_assert("the attribution is a real anchor, not a div pretending to be one",
        '<a class="fs-attribution__link"' in ATTRIBUTION_JS)
_assert("with rel=noopener, because it leaves the product",
        'rel="noopener noreferrer"' in ATTRIBUTION_JS)


# ── 2 · The six-label vocabulary, and the one that cannot be reached ─────────

_section("2 · Six labels, five reachable, and the sixth says so")

PROVIDER_JS = _read("web", "js", "provider-state.js")

for label in ("DEMO", "YAHOO · CONNECTED", "YAHOO · SYNCING",
              "YAHOO · NOT SYNCED YET", "NOT CONNECTED", "LEAGUE UNAVAILABLE"):
    _assert(f"the vocabulary defines {label!r}", f"'{label}'" in PROVIDER_JS)

_assert("YAHOO · SYNCING is recorded as currently unreachable",
        "SYNCING_REACHABLE = false" in PROVIDER_JS)
_assert("and no branch can select it — no backend fact maps to it",
        "SOURCE_YAHOO_SYNCING" not in _code_only(PROVIDER_JS)
        .split("export const SOURCE_LABELS")[1].split("export function sourceState")[0]
        or "return frozen(SOURCE_YAHOO_SYNCING" not in PROVIDER_JS,
        "no return path")
_assert("open provider conflicts are NOT relabelled as syncing",
        "conflict" not in _code_only(PROVIDER_JS).lower())
_assert("and the state model reads no diagnostic route at all",
        "provider/status" not in PROVIDER_JS
        and "open_provider_conflicts" not in PROVIDER_JS)

# THE MODEL INVENTS NOTHING. Every branch reads a served field.
_assert("the model derives from the served context and nothing else",
        "servedContext()" in PROVIDER_JS and "providerState()" in PROVIDER_JS)
_assert("it never reads the league's NAME to decide Demo",
        "leagueName" not in PROVIDER_JS)


# ── 3 · The backend states the mapping consumes ──────────────────────────────

_section("3 · Demo and Yahoo are decided by the binding, never by a name")

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "wp3d-password"


class _Row:
    """The two fields `_provider_state` and `is_demo_league` actually read."""

    def __init__(self, provider, key, week):
        self.provider = provider
        self.provider_league_key = key
        self.provider_current_week = week


_assert("a Yahoo league with a stated week is BOUND",
        _provider_state(_Row("yahoo", "461.l.x", 5)) == PROVIDER_BOUND)
_assert("a Yahoo league that has never been refreshed is PENDING",
        _provider_state(_Row("yahoo", "461.l.x", None)) == PROVIDER_PENDING)
_assert("a league with no provider is ABSENT",
        _provider_state(_Row(None, None, None)) == PROVIDER_ABSENT)
_assert("and a provider with no league key is ABSENT too",
        _provider_state(_Row("yahoo", None, 5)) == PROVIDER_ABSENT)

from api.demo_routes import is_demo_league                         # noqa: E402

_assert("a demo-bound league IS demo",
        is_demo_league(_Row("demo", "demo.l.certification", 3)) is True)
_assert("a YAHOO league named nothing of the sort is NOT demo",
        is_demo_league(_Row("yahoo", "461.l.certification", 3)) is False)

with SessionLocal() as db:
    hashed = hash_password(PASSWORD)

    # THE TRAP, SEEDED DELIBERATELY. A live Yahoo league whose owner called it
    # "Demo League", and a genuine Demo league called something else. If the
    # marker were ever derived from the name, the first would be badged as
    # synthetic — telling a GM their real money-adjacent league is a sandbox —
    # and the second would be presented as live Yahoo data.
    trap = League(name="Demo League", season=2026, provider="yahoo",
                  provider_league_key="461.l.trap", provider_current_week=4)
    real_demo = League(name="Sunday Gravy Invitational", season=2026,
                       provider="demo",
                       provider_league_key="demo.l.wp3d",
                       provider_current_week=4)
    bare = League(name="Unbound League", season=2026)
    db.add_all([trap, real_demo, bare])
    db.flush()
    TRAP_ID, DEMO_ID, BARE_ID = trap.id, real_demo.id, bare.id

    def _member(name, email, league_id, commissioner=False):
        t = Team(team_name=name, owner=f"{name} Owner", email=email,
                 league_id=league_id)
        db.add(t)
        db.flush()
        db.add(Wallet(team_id=t.id, balance=0.0))
        u = User(email=email, hashed_password=hashed, team_id=t.id,
                 role="commissioner" if commissioner else "gm")
        db.add(u)
        db.flush()
        if commissioner:
            db.add(LeagueCommissioner(league_id=league_id, user_id=u.id,
                                      source="bootstrap"))
            db.flush()
        return t.id

    TRAP_GM = _member("Trap GM", "trap@wp3d.test", TRAP_ID)
    _member("Trap Comm", "trapcomm@wp3d.test", TRAP_ID, commissioner=True)
    DEMO_GM = _member("Demo GM", "demogm@wp3d.test", DEMO_ID)
    BARE_GM = _member("Bare GM", "baregm@wp3d.test", BARE_ID)
    db.commit()


def _client() -> TestClient:
    return TestClient(app)


def _sign_in(client: TestClient, email: str) -> None:
    r = client.post("/auth/session", json={"email": email,
                                           "password": PASSWORD})
    assert r.status_code == 200, r.text


def _context(client: TestClient, league_id: int):
    return client.get(f"/league/{league_id}/context/me")


with _client() as client:
    _sign_in(client, "trap@wp3d.test")
    r = _context(client, TRAP_ID)
    _assert("the context read serves for a Yahoo league", r.status_code == 200,
            r.text[:160])
    body = r.json()
    _assert('a live Yahoo league CALLED "Demo League" is NOT marked demo',
            body["demo"] is False, str(body["demo"]))
    _assert("and it reports itself bound",
            body["provider_state"] == PROVIDER_BOUND, body["provider_state"])

with _client() as client:
    _sign_in(client, "demogm@wp3d.test")
    body = _context(client, DEMO_ID).json()
    _assert("a demo-BOUND league is marked demo whatever it is called",
            body["demo"] is True, str(body["demo"]))

with _client() as client:
    _sign_in(client, "baregm@wp3d.test")
    body = _context(client, BARE_ID).json()
    _assert("an unbound league reports absent and is not demo",
            body["provider_state"] == PROVIDER_ABSENT
            and body["demo"] is False,
            f"{body['provider_state']} demo={body['demo']}")


# ── 4 · WP3D added no backend state ──────────────────────────────────────────

_section("4 · No new provider persistence, no new provider calls")

import subprocess as _sp                                           # noqa: E402

_diff = _sp.run(["git", "diff", "--name-only", "HEAD"],
                cwd=ROOT, capture_output=True, text=True).stdout.split()

for untouched in ("db/schema.py", "providers/yahoo", "providers/persist.py",
                  "providers/incident.py", "reports/league_read_model.py"):
    _assert(f"{untouched} is unmodified by this package",
            not any(f.startswith(untouched) for f in _diff),
            ", ".join(f for f in _diff if f.startswith(untouched)))

_assert("no refresh-progress model was added, per the owner ruling",
        "refresh_in_progress" not in _read("db", "schema.py")
        and "SYNCING" not in _read("api", "main.py"))
_assert("and the frontend makes no provider network call of its own",
        "provider/status" not in FRONTEND.replace(
            _code_only(_read("web", "js", "commissioner.js")), ""))


# ── 5 · Diagnostics stay behind the authorization boundary ───────────────────

_section("5 · Raw diagnostics are commissioner-only, from both sides")

with _client() as client:
    _sign_in(client, "trap@wp3d.test")
    r = client.get(f"/league/{TRAP_ID}/provider/status")
    _assert("an ordinary GM is REFUSED the provider diagnostics",
            r.status_code in (401, 403), str(r.status_code))
    _assert("and the refusal leaks no diagnostic content",
            not any(k in r.text for k in
                    ("last_provider_refresh", "stuck_pools", "blocked_reason",
                     "unfinalized_matchup_ids", "open_provider_conflicts")),
            r.text[:120])

with _client() as client:
    _sign_in(client, "trapcomm@wp3d.test")
    r = client.get(f"/league/{TRAP_ID}/provider/status")
    _assert("the commissioner still gets them", r.status_code == 200,
            r.text[:160])
    if r.status_code == 200:
        body = r.json()
        _assert("with the operator detail intact",
                all(k in body for k in
                    ("last_provider_refresh", "open_provider_conflicts",
                     "unfinalized_matchup_ids", "blocked_reason",
                     "stuck_pools")),
                ", ".join(sorted(body)))

with _client() as client:
    r = client.get(f"/league/{TRAP_ID}/provider/status")
    _assert("an unauthenticated caller is refused",
            r.status_code in (401, 403), str(r.status_code))

with _client() as client:
    _sign_in(client, "demogm@wp3d.test")
    _assert("a member of another league cannot read this league's context",
            _context(client, TRAP_ID).status_code == 403,
            str(_context(client, TRAP_ID).status_code))

# THE MEMBER CONTRACT ITSELF CARRIES NO DIAGNOSTICS. The route a player-facing
# surface actually reads must not be a diagnostic channel by another name.
with _client() as client:
    _sign_in(client, "trap@wp3d.test")
    member_body = _context(client, TRAP_ID).json()
    for leaked in ("last_provider_refresh", "open_provider_conflicts",
                   "stuck_pools", "blocked_reason", "unfinalized_matchup_ids",
                   "classification", "detail", "access_token", "refresh_token"):
        _assert(f"the member context does not carry {leaked}",
                leaked not in member_body)


# ── 6 · The frontend never renders a diagnostic ──────────────────────────────

_section("6 · No raw diagnostic reaches member-facing chrome")

CHROME = _code_only(_read("web", "js", "provider-state.js")) \
    + _code_only(_read("web", "js", "attribution.js"))

for forbidden in ("status_code", "statusText", "stack", "Traceback",
                  "oauth", "OAuth", "access_token", "refresh_token",
                  "fantasysports.yahooapis", "ProviderError", "HTTPException",
                  "ECONNREFUSED", "endpoint"):
    _assert(f"the source chip and attribution never render {forbidden!r}",
            forbidden not in CHROME)

_assert("the six labels are the only strings the chip can draw",
        len(re.findall(r"SOURCE_[A-Z_]+ = '", PROVIDER_JS)) == 6,
        str(len(re.findall(r"SOURCE_[A-Z_]+ = '", PROVIDER_JS))))


# ── 7 · The superseded banner is gone ────────────────────────────────────────

_section("7 · OFFICIAL YAHOO FANTASY MATCHUP is retired")

PREVIEW = _read("web", "js", "preview.js")
_assert("the phrase no longer renders anywhere in the product",
        "OFFICIAL YAHOO FANTASY MATCHUP" not in _code_only(PREVIEW)
        and "OFFICIAL YAHOO FANTASY MATCHUP" not in FRONTEND)
_assert("nor does any other claim of official standing",
        not re.search(r"official\s+yahoo", FRONTEND, re.I),
        (re.search(r".{0,50}official\s+yahoo.{0,50}", FRONTEND, re.I)
         or [""])[0])
_assert("the preview still distinguishes a Yahoo matchup from a wager",
        "not a FantasyStakes wager" in PREVIEW)
_assert("and it is attributed only when it is actually showing one",
        "showsYahooInformation: fromYahoo" in PREVIEW)


# ── 8 · Placement — one per surface, never more ──────────────────────────────

_section("8 · Every Yahoo surface is attributed, exactly once")

for panel in ("standings.js", "league.js", "action.js", "week.js",
              "ledger.js", "rules.js"):
    body = _read("web", "js", panel)
    calls = len(re.findall(r"attributionFooter\(", _code_only(body)))
    _assert(f"{panel} renders the attribution exactly once", calls == 1,
            f"{calls} call sites")

# §22 — A REFERENCE IS NOT A DISPLAY, and the two must not be conflated.
#
# The rules copy names Yahoo repeatedly, because Yahoo really does decide the
# podium and what happened on the field, and explaining a FantasyStakes rule by
# naming its authority is this product describing itself. None of those
# sentences is Yahoo Fantasy Information, and none of them is attributed: the
# Rules panel carries ONE attribution, in its legal footer, for the league name
# in its header and the provider-backed values the commissioner region reports.
_RULES_DATA = _read("web", "js", "data", "rules-data.js")
_assert("the rules copy does reference Yahoo, as the product rules require",
        _RULES_DATA.count("Yahoo") >= 4, str(_RULES_DATA.count("Yahoo")))
_assert("and not one of those references is individually attributed",
        "attribution" not in _RULES_DATA.lower())
_RULES_JS = _read("web", "js", "rules.js")
_LEGAL_FOOTER = _RULES_JS.split("function legalFooter")[1].split("\n}\n")[0]
_assert("the Rules panel attributes the SURFACE, in its legal footer, once",
        "attributionFooter()" in _LEGAL_FOOTER
        and _RULES_JS.count("attributionFooter()") == 1)

_assert("and it is not smuggled into the static HTML shell instead",
        REQUIRED not in _read("web", "index.html"))
_assert("nor into the persistent chrome, where it would sit over the nav",
        REQUIRED not in _read("web", "js", "shell.js"))


# ── 9 · The frontend tiers ───────────────────────────────────────────────────

def _run_node(script: str, label: str, env_extra: dict | None = None) -> None:
    node = shutil.which("node")
    if node is None:
        _assert(f"{label} — node is available", False, "node not on PATH")
        return
    print(f"\n{label}")
    env = dict(os.environ)
    env.update(env_extra or {})
    proc = subprocess.run(
        [node, os.path.join(ROOT, "web", "tests", script)],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print(proc.stderr.rstrip()[-2000:])
    passes = proc.stdout.count("[PASS]")
    fails = proc.stdout.count("[FAIL]")
    _assert(f"{label} is green", proc.returncode == 0 and fails == 0,
            f"{passes} PASS / {fails} FAIL, exit {proc.returncode}")


_section("9 · The chrome and the panels, driven")

_run_node("wp3d_component_tests.mjs", "WP3D component suite (Node)")

# FOUR SERVERS, ONE PER REACHABLE PROVIDER STATE. The label and the attribution
# are decided by the binding, so the only way to certify all four is to run the
# real page against four differently-bound leagues. `LEAGUE UNAVAILABLE` is the
# fifth and is certified at the component tier, where a failed context read can
# be produced deliberately.
_BROWSER_RUNS = [
    ("connected", dict(seed_priceable_versus=True), APP_GM_EMAIL),
    ("pending", dict(provider_week=None), APP_GM_EMAIL),
    ("demo", dict(provider_binding="demo"), APP_GM_EMAIL),
    ("absent", dict(provider_binding="none"), APP_GM_EMAIL),
    ("commissioner", dict(seed_priceable_versus=True), APP_COMM_EMAIL),
]

for mode, fixture, email in _BROWSER_RUNS:
    with AppServer(**fixture) as _server:
        _run_node("wp3d_browser.mjs",
                  f"WP3D browser suite — {mode}",
                  {"FS_TEST_ORIGIN": _server.origin,
                   "FS_TEST_AUTH_EMAIL": email,
                   "FS_TEST_AUTH_PASSWORD": APP_PASSWORD,
                   "FS_WP3D_MODE": mode})


print("\n" + "=" * 66)
if _failures:
    print(f"WP3D PROVIDER IDENTITY + ATTRIBUTION — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("WP3D PROVIDER IDENTITY + ATTRIBUTION — all assertions PASSED")
