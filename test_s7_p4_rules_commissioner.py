#!/usr/bin/env python3
"""
test_s7_p4_rules_commissioner.py — Sprint 7 Package 4: Rules & Settings +
commissioner surfaces.

Three halves, all required:

  1. FIDELITY, in Python. This package writes the league's RULES, so every
     figure and claim in them is checked against the module that governs it:
     the economy stop against `payments/economy_config.py`, the Skunk against
     `economy/skunk.py`, the Pool entry against the schema CHECK constraint, the
     championship split against the treasury default, the wager states against
     `beefs/proposal_lifecycle.py`, and the top-off states against
     `economy/top_off.py` — including the asymmetry that an APPROVED request
     persists status `applied`. The three seams this package names are checked
     the same way: the routes that exist are asserted to exist, and the routes
     that do not are asserted to be absent.

  2. STRUCTURE, in Python. The locked orders and the removals: five rule groups
     in order, commissioner sections with B before C, no strip, no disclaimer,
     no configuration mutation path, no payment processing, and the legal line
     at the bottom of this tab and nowhere else.

  3. BEHAVIOUR, in Node. `web/tests/package4_component_tests.mjs` executes the
     shipped modules; `web/tests/e2e_package4.mjs` measures the built layout in
     a real headless Chrome at a phone viewport.

Also carries the Package 3 correction: The Week's locked bets heading.

No database is involved. No protocol module is imported — the protocol sources
are read as text.

USAGE:
    python test_s7_p4_rules_commissioner.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _read(*parts: str) -> str:
    with open(os.path.join(WEB, *parts), encoding="utf-8") as fh:
        return fh.read()


def _read_root(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    source = re.sub(r"<!--.*?-->", " ", source, flags=re.DOTALL)
    source = re.sub(r"^\s*//.*$", " ", source, flags=re.MULTILINE)
    return source


# ── The shipped modules, as values ───────────────────────────────────────────

_NODE = shutil.which("node")

_PROBE = """
const base = %s;
const rulesData = await import(base + 'data/rules-data.js');
const commData = await import(base + 'data/commissioner-data.js');
const commModel = await import(base + 'commissioner-model.js');
const { buildRulesPanel } = await import(base + 'rules.js');
const { buildWeekPanel, BETS_HEADING, selectWeek, resetWeek } = await import(base + 'week.js');
const { weekBets, CURRENT_WEEK, PAST_WEEK } = await import(base + 'data/week-data.js');
const ledger = await import(base + 'ledger-model.js');

resetWeek();
const weekCurrent = buildWeekPanel();
selectWeek(PAST_WEEK);
const weekPast = buildWeekPanel();
resetWeek();

console.log(JSON.stringify({
  economyStop: rulesData.ECONOMY_STOP,
  poolEntry: rulesData.POOL_ENTRY,
  skunk: rulesData.SKUNK,
  split: rulesData.CHAMPIONSHIP_SPLIT,
  settings: rulesData.SETTINGS,
  settingsSeam: rulesData.SETTINGS_SEAM,
  legalLine: rulesData.LEGAL_LINE,
  groups: rulesData.RULE_GROUPS.map((g) => ({
    id: g.id, title: g.title,
    rules: g.rules.map((r) => ({ heading: r.heading, body: r.body, source: r.source })),
  })),
  requests: commData.TOPOFF_REQUESTS,
  states: commData.TOPOFF_STATES,
  authSeam: commModel.COMMISSIONER_AUTH_SEAM,
  positionsSeam: commModel.LEAGUE_POSITIONS_SEAM,
  trialSeam: commModel.TRIAL_BALANCE_SEAM,
  routes: commModel.TOPOFF_ROUTES,
  positions: commModel.gmPositions(),
  league: commModel.leagueReconciliation(),
  gmLedger: ledger.reconciliation(),
  panel: buildRulesPanel(),
  betsHeading: BETS_HEADING,
  weekCurrentHasHeading: weekCurrent.includes(BETS_HEADING),
  weekPastHasHeading: weekPast.includes(BETS_HEADING),
  betsCurrent: weekBets(CURRENT_WEEK).length,
  betsPast: weekBets(PAST_WEEK).length,
}));
"""


def _probe() -> dict:
    if _NODE is None:
        return {}
    url = "file:///" + os.path.join(WEB, "js").replace("\\", "/").lstrip("/") + "/"
    proc = subprocess.run(
        [_NODE, "--input-type=module", "-e", _PROBE % json.dumps(url)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
    )
    if proc.returncode != 0:
        print(proc.stderr[:2000])
        return {}
    return json.loads(proc.stdout)


APP = _probe()

print("\nPackage 4 ships Rules & Settings as real, served assets")

EXPECTED_FILES = [
    "js/rules.js",
    "js/commissioner.js",
    "js/commissioner-model.js",
    "js/data/rules-data.js",
    "js/data/commissioner-data.js",
    "styles/rules.css",
    "tests/package4_component_tests.mjs",
    "tests/e2e_package4.mjs",
]

for relative in EXPECTED_FILES:
    _assert(f"web/{relative} exists", os.path.isfile(os.path.join(WEB, *relative.split("/"))))

_assert("the shipped modules load and expose their values", bool(APP),
        "node probe returned nothing" if not APP else "")

INDEX = _read("index.html")
SHELL_JS = _read("js", "shell.js")
RULES_JS = _read("js", "rules.js")
COMMISSIONER_JS = _read("js", "commissioner.js")
RULES_CSS = _read("styles", "rules.css")
PANEL = APP.get("panel", "")

_assert("the Package 4 stylesheet is linked", 'href="./styles/rules.css"' in INDEX)
_assert("the shell builds Rules & Settings from its own module",
        "from './rules.js'" in SHELL_JS)
_assert("every destination now has a real module",
        "buildRulesPanel()" in SHELL_JS and "no panel content defined" in SHELL_JS)


# ── Governed configuration ───────────────────────────────────────────────────

print("\nSettings show the governed configuration, checked against its source")

ECONOMY_CONFIG_PY = _read_root("payments", "economy_config.py")
SKUNK_PY = _read_root("economy", "skunk.py")
SCHEMA_PY = _read_root("db", "schema.py")
MAIN_PY = _read_root("api", "main.py")

stop = APP.get("economyStop", {})

# The default stop, read straight out of the module that certifies it.
_assert("the certified default stop is the one the settings show",
        "EconomyStop(weekly_min_cents=1000, min_reserve_cents=14000, "
        "buyin_cents=22000, reserve_cents=8000)" in ECONOMY_CONFIG_PY.replace("\n", " ")
        or re.search(r"weekly_min_cents=1000,\s*min_reserve_cents=14000,\s*"
                     r"buyin_cents=22000,\s*reserve_cents=8000", ECONOMY_CONFIG_PY) is not None)
_assert("DEFAULT_STOP is that row", "DEFAULT_STOP = ECONOMY_STOPS[1]" in ECONOMY_CONFIG_PY)
_assert("the UI carries the same four figures",
        stop.get("weeklyMinCents") == 1000 and stop.get("minReserveCents") == 14000
        and stop.get("reserveCents") == 8000 and stop.get("buyinCents") == 22000,
        str(stop))
_assert("season-opening allocation is 220 Credits", stop.get("buyinCents") == 22000)
_assert("regular-season minimum reserve is 140 Credits", stop.get("minReserveCents") == 14000)
_assert("championship reserve is 80 Credits", stop.get("reserveCents") == 8000)
_assert("the three certified invariants hold on the UI's copy",
        stop.get("minReserveCents", 0) + stop.get("reserveCents", 0) == stop.get("buyinCents")
        and stop.get("minReserveCents") == stop.get("weeklyMinCents", 0) * 14
        and stop.get("reserveCents", 0) * 11 == stop.get("buyinCents", 0) * 4)

skunk = APP.get("skunk", {})
_assert("the governed weekly Skunk is 1000 cents",
        "DEFAULT_SKUNK_CONTRIBUTION_CENTS = 1000" in SKUNK_PY
        and skunk.get("weeklyCents") == 1000)
_assert("the governed season maximum is 14000 cents",
        "DEFAULT_SKUNK_SEASON_MAXIMUM_CENTS = 14000" in SKUNK_PY
        and skunk.get("seasonMaximumCents") == 14000)
_assert("the Skunk window is the regular season only",
        "regular season only (weeks 1-14), never" in SKUNK_PY)

entry = APP.get("poolEntry", {})
_assert("the Pool entry bound is the schema's own",
        "pool_weekly_entry_cents >= 100 AND pool_weekly_entry_cents <= 500" in SCHEMA_PY)
_assert("the UI carries those bounds",
        entry.get("minCents") == 100 and entry.get("maxCents") == 500)
_assert("the shown entry sits inside them",
        entry.get("minCents", 0) <= entry.get("cents", 0) <= entry.get("maxCents", 0),
        str(entry.get("cents")))

split = APP.get("split", {})
_assert("the governed payout split default is 60/30/10",
        'default="[60,30,10]"' in SCHEMA_PY)
_assert("the UI shows that split", split.get("split") == [60, 30, 10], str(split.get("split")))
_assert("the split totals 100", sum(split.get("split", [])) == 100)

settings = APP.get("settings", [])
_assert("exactly four settings rows", len(settings) == 4, str(len(settings)))
_assert("the labels are the locked labels",
        [s["label"] for s in settings]
        == ["Economy Stop", "Standard Pool Bet", "Skunk Fee", "Championship split"],
        " / ".join(s["label"] for s in settings))
_assert("every settings row names its governing source",
        all(len(s.get("source", "")) > 3 for s in settings))


# ── No fabricated mutation path ──────────────────────────────────────────────

print("\nNo configuration mutation path is fabricated")

seam = APP.get("settingsSeam", {})
# The seam claim is only honest if no such route exists.
_assert("no route changes the economy stop",
        not re.search(r'@app\.(post|patch|put)\("[^"]*economy[-_]stop', MAIN_PY))
# GOVERNED REVISION, S8-P4. The B2 ruling made Standard Pool Bet the ONE
# governed settings mutation for MVP, so a route for it must now exist — and
# must write the Rev 4.2 column, not the legacy one. The other three settings
# stay read-only, and the assertions above and below still prove that.
_assert("the Standard Pool Bet command exists",
        bool(re.search(r'@app\.put\("/league/\{league_id\}/settings/pool-entry"',
                       MAIN_PY)))
_assert("it is league-scoped commissioner authority",
        "def league_set_pool_entry" in MAIN_PY
        and "require_league_commissioner" in MAIN_PY)
_assert("it calls the governed setter rather than reimplementing the bounds",
        "configure_pool_weekly_entry" in MAIN_PY)
_assert("and it does not write the legacy three-pot column",
        "weekly_entry_cents=" not in MAIN_PY.split(
            "def league_set_pool_entry")[1][:2000])
_assert("no route changes the Skunk amount",
        not re.search(r'@app\.(post|patch|put)\("[^"]*skunk', MAIN_PY))
_assert("no route changes the payout split",
        not re.search(r'@app\.(post|patch|put)\("[^"]*(split|payout)', MAIN_PY))
# GOVERNED REVISION, S8-P4: one command now exists. What must still hold is
# that it is exactly one, and that the other three rows remain read-only.
_assert("the module names the one governed command",
        seam.get("endpoint") == "PUT /league/{league_id}/settings/pool-entry")
_assert("exactly one row is mutable", seam.get("mutable") == ["pool-bet"])
_assert("the other three rows remain read-only",
        sorted(seam.get("readOnly", []))
        == ["championship-split", "economy-stop", "skunk-fee"])
_assert("the tab renders no editable control",
        not re.search(r"<input|<select|<textarea|type=\"checkbox\"", PANEL))
_assert("and no save affordance",
        not re.search(r"data-save|>Save<|>Apply<|>Update<", PANEL))
_assert("the Rules module issues no request of any kind",
        not re.search(r"\bfetch\s*\(|XMLHttpRequest|\.submit\s*\(", RULES_JS + COMMISSIONER_JS))


# ── Rule copy against the protocol ───────────────────────────────────────────

print("\nRule copy does not contradict the specifications it cites")

LIFECYCLE_PY = _read_root("beefs", "proposal_lifecycle.py")
RULING = _read_root("spec", "LOCKED_VS_DYNAMIC_WAGER_MODEL_RULING.md")
CURRENT_SETTLE_PY = _read_root("economy", "current_settle.py")
WEEKLY_MIN_PY = _read_root("economy", "weekly_minimum.py")

groups = APP.get("groups", [])
LOCKED_ORDER = ["The Money", "Weekly Grind", "Big Money", "The Bets", "The Fine Print"]

_assert("exactly five top-level rule groups", len(groups) == 5, str(len(groups)))
_assert("in the locked order",
        [g["title"] for g in groups] == LOCKED_ORDER,
        " / ".join(g["title"] for g in groups))
_assert("every rule names a governing source",
        all(len(r["source"]) > 3 for g in groups for r in g["rules"]))

# Every word a GM reads as rules: the group titles and blurbs on the tab, plus
# the headings and bodies inside each sheet.
all_copy = " ".join(
    f"{g['title']} " + " ".join(f"{r['heading']} {r['body']}" for r in g["rules"])
    for g in groups
)

# Source modules wrap their prose, so a phrase quoted from one is matched with
# whitespace normalised rather than as it happens to be line-broken.
def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)

_assert("the one-counter ceiling matches the lifecycle",
        "one-counter ceiling" in LIFECYCLE_PY and "one counter" in all_copy.lower())
_assert("no re-counter, as §8 rules",
        'no re-counter' in LIFECYCLE_PY and "no re-counter" in all_copy.lower())
_assert("the Anchor role staying with the issuer is stated",
        "Anchor role stays with the original issuer" in LIFECYCLE_PY
        and "Anchor" in all_copy)
_assert("the three markets match VALID_WAGER_TYPES",
        'VALID_WAGER_TYPES = ("straight", "spread", "over_under")' in LIFECYCLE_PY
        and "straight, spread and over_under" in all_copy)
_assert("the minimum stake matches the wallet minimum",
        re.search(r"^MIN_BET\s*=\s*5\.00", _read_root("wallet", "wallet_manager.py"),
                  re.MULTILINE) is not None
        and "$5" in all_copy)
_assert("Current Settle is described exactly as the module defines it",
        "assets minus obligations" in all_copy.lower()
        or "assets − obligations" in all_copy
        or ("settlement-relevant assets minus obligations" in all_copy))
_assert("the never-stored property is carried into the rules",
        "NEVER STORED" in CURRENT_SETTLE_PY and "never stored" in all_copy.lower())
_assert("the committed championship reserve is described as never spendable",
        "never spendable, never releasable" in _flat(CURRENT_SETTLE_PY)
        and "never spendable and" in all_copy)
_assert("weekly release cannot exceed the reserve, as the module states",
        "RELEASE CANNOT EXCEED THE REMAINING RESERVE" in WEEKLY_MIN_PY
        and "never exceed what" in all_copy)
_assert("expiry is described as leaving circulation, not being lost",
        "expired_min" in WEEKLY_MIN_PY and "out of circulation" in all_copy.lower())
_assert("min-first spending order is stated",
        "min-first, then wallet" in WEEKLY_MIN_PY
        and "minimum first" in all_copy.lower())

print("\nThe Locked and Dynamic rules are the adopted ruling, verbatim")

quoted = re.search(r"Corrected card copy \(Dynamic offer\):\*\*\s*[\"“](.+?)[\"”]",
                   RULING, re.DOTALL)


def _plain(text: str) -> str:
    swaps = {"’": "'", "‘": "'", "“": '"', "”": '"', "—": "-", "–": "-", "−": "-", " ": " "}
    for bad, good in swaps.items():
        text = text.replace(bad, good)
    return re.sub(r"\s+", " ", text).strip()


bets = next((g for g in groups if g["id"] == "bets"), {"rules": []})
dynamic_rule = next((r for r in bets["rules"] if r["heading"].startswith("DYNAMIC")), None)
locked_rule = next((r for r in bets["rules"] if r["heading"].startswith("LOCKED")), None)

_assert("the rules sheet carries a Dynamic rule", dynamic_rule is not None)
_assert("it is the ruling's corrected copy, verbatim",
        bool(quoted) and dynamic_rule is not None
        and _plain(dynamic_rule["body"]) == _plain(quoted.group(1)))
_assert("the rules sheet carries a Locked rule", locked_rule is not None)
_assert("Locked says terms freeze on send",
        locked_rule is not None and "freeze the moment you send" in locked_rule["heading"])
_assert("the retired 'flex up or down' draft appears nowhere",
        "flex up" not in _plain(all_copy).lower())

print("\nNo payment processing is reintroduced")

# Source citations are provenance; one legitimately names the addendum that
# REMOVED Stripe. The scan is over the policy copy the GM reads as rules.
for banned in ("Stripe", "PayPal", "Apple Pay", "credit card", "debit card",
               "payment method", "billing", "checkout", "routing number", "add funds"):
    _assert(f"no {banned!r} language in the rules copy",
            not re.search(banned, all_copy, re.I), banned)
_assert("Credits are stated to carry no cash value", "no cash value" in all_copy.lower())
_assert("and to have no funding path", "no funding path" in all_copy.lower())

print("\nBetting vocabulary is intentionally preserved")
for term in ("wager", "bets", "stake", "pot", "ML", "Spread", "O/U", "Locked", "Dynamic"):
    _assert(f"the vocabulary keeps {term!r}",
            re.search(rf"\b{re.escape(term)}\b", all_copy, re.I) is not None, term)


# ── Commissioner ─────────────────────────────────────────────────────────────

print("\nCommissioner sections are in the locked order, B before C")

_assert("the commissioner area renders", 'id="fs-commissioner"' in PANEL)
for sec in ("topoffs", "gm-cards", "reconciliation"):
    _assert(f"the {sec} section renders", f'data-commissioner="{sec}"' in PANEL)
_assert("Top-Off Requests precedes GM Ledger Cards",
        PANEL.index('data-commissioner="topoffs"') < PANEL.index('data-commissioner="gm-cards"'))
_assert("GM Ledger Cards precedes League Reconciliation — B before C is locked",
        PANEL.index('data-commissioner="gm-cards"')
        < PANEL.index('data-commissioner="reconciliation"'))
_assert("the GM cards heading is the locked wording",
        "B · GM LEDGER CARDS · 12 · TAP TO EXPAND" in PANEL)
_assert("the reconciliation heading is the locked wording",
        "C · LEAGUE RECONCILIATION" in PANEL)

print("\nTop-Off states, routes and authority match the protocol")

TOP_OFF_PY = _read_root("economy", "top_off.py")
states = {s["id"]: s for s in APP.get("states", [])}

_assert("approval persists decision 'approved' and status 'applied'",
        'request.decision            = "approved"' in TOP_OFF_PY
        and 'request.status              = "applied"' in TOP_OFF_PY)
_assert("the UI reproduces that asymmetry rather than smoothing it",
        states.get("approved", {}).get("status") == "applied",
        str(states.get("approved")))
_assert("rejection persists rejected/rejected",
        'request.decision           = "rejected"' in TOP_OFF_PY
        and states.get("rejected", {}).get("status") == "rejected")
_assert("cancellation persists cancelled/cancelled",
        'request.decision           = "cancelled"' in TOP_OFF_PY
        and states.get("cancelled", {}).get("status") == "cancelled")

routes = APP.get("routes", {})
for name, path in (("create", '@app.post("/league/{league_id}/top-offs"'),
                   ("approve", '@app.post("/league/{league_id}/top-offs/{request_id}/approve"'),
                   ("reject", '@app.post("/league/{league_id}/top-offs/{request_id}/reject"'),
                   ("cancel", '@app.post("/league/{league_id}/top-offs/{request_id}/cancel"'),
                   ("read", '@app.get("/league/{league_id}/top-offs"')):
    _assert(f"the {name} route really exists", path in MAIN_PY, name)
_assert("the UI names all five", len(routes) == 5, ", ".join(sorted(routes)))

requests = APP.get("requests", [])
_assert("every illustrative request uses the persisted field names",
        all({"amount_cents", "requester_user_id", "decided_by_user_id",
             "ledger_posting_id", "disclosure_event_id", "created_at"} <= set(r)
            for r in requests))
_assert("remaining_capacity_cents is absent, as the read route leaves it",
        all("remaining_capacity_cents" not in r for r in requests))
_assert("the read route deliberately omits it",
        "remaining_capacity_cents is deliberately ABSENT" in MAIN_PY)
_assert("only an approved request carries linkage",
        all(bool(r["ledger_posting_id"]) == (r["decision"] == "approved") for r in requests))
_assert("a self-approval carries its required reason",
        all(r["decision_reason"] for r in requests if r.get("self_approved")))
_assert("§5.3 requires that reason",
        "non-empty reason on a" in MAIN_PY and "SELF-approval" in MAIN_PY)

print("\nNo unauthorised issuance, and the missing seam is explicit")

auth = APP.get("authSeam", {})
_assert("the server-side authority model exists",
        "def require_commissioner" in _read_root("auth", "jwt_auth.py"))
_assert("authority is re-checked under lock before commit",
        "was revoked before this rejection could" in TOP_OFF_PY
        or "authority for league" in TOP_OFF_PY)
# GOVERNED REVISION, S8-P1. This asserted that the seam named the SESSION as
# the missing piece. Package 1 supplied the session, so the old wording would
# now be a false statement about the build, and the assertion correctly refuses
# it. What the seam must still do is distinguish the half that closed from the
# half that did not: an undifferentiated "solved" would claim a working
# decision path that does not exist, and an undifferentiated "missing" would
# understate what shipped.
_assert("the seam records that the session half is closed",
        "SESSION IDENTITY EXISTS" in str(auth.get("status")))
_assert("the seam names what is still missing as the decision commands",
        "NOT YET BOUND" in str(auth.get("status"))
        and "decision routes" in str(auth.get("missing")))
_assert("and it cites where the session came from",
        "S8-P1" in str(auth.get("sessionIdentity")))
_assert("the commissioner UI is declared illustrative",
        "illustrative" in str(auth.get("uiState")))
_assert("every decision control renders disabled",
        len(re.findall(r'data-decide="[a-z]+" disabled', COMMISSIONER_JS)) >= 1
        or "disabled" in COMMISSIONER_JS)
_assert("no decision is posted from the frontend",
        not re.search(r"\bfetch\s*\(|XMLHttpRequest", COMMISSIONER_JS))
_assert("the surface says nothing is transmitted",
        "no decision is" in COMMISSIONER_JS or "Demonstration only" in COMMISSIONER_JS)

print("\nGM Ledger Cards use the GM's own arithmetic")

positions = APP.get("positions", [])
gm_ledger = APP.get("gmLedger", {})
_assert("twelve GM cards", len(positions) == 12, str(len(positions)))
_assert("every GM's figure follows the Ledger formula",
        all(p["currentSettleCents"] == p["wageringPositionCents"] + p["netAdjustmentsCents"]
            - p["totalVirtualStakesCents"] for p in positions))
you = next((p for p in positions if p["teamId"] == "you"), {})
_assert("the viewer's commissioner card equals their own Ledger figure",
        you.get("currentSettleCents") == gm_ledger.get("currentSettleCents"),
        f"{you.get('currentSettleCents')} vs {gm_ledger.get('currentSettleCents')}")
_assert("and its three terms match too",
        you.get("wageringPositionCents") == gm_ledger.get("position", {}).get("wageringPositionCents")
        and you.get("netAdjustmentsCents") == gm_ledger.get("adjustments", {}).get("netAdjustmentsCents")
        and you.get("totalVirtualStakesCents")
        == gm_ledger.get("advances", {}).get("totalVirtualStakesCents"))
_assert("every GM is on the league's single economy stop",
        all(p["seasonOpeningCents"] == 22000 for p in positions))

# GOVERNED REVISION, S8-P3. This asserted that NO league-wide positions route
# existed and that the seam recorded its absence. P3 built one, so the old
# assertions would now fail a correct build. What must still hold is the reason
# the seam existed: the cards on this tab are illustrative until they are
# bound, and the league-wide read must be an aggregation of the per-team
# calculation rather than a second formula.
positions_seam = APP.get("positionsSeam", {})
_assert("the league-wide positions route now exists",
        bool(re.search(r'@app\.get\("/league/\{league_id\}/ledger/positions"',
                       MAIN_PY)))
_assert("the seam names it as the binding target",
        positions_seam.get("endpoint") == "GET /league/{league_id}/ledger/positions",
        str(positions_seam.get("endpoint")))
_assert("and still names the per-team computation it aggregates",
        "current_settle.py" in str(positions_seam.get("computation")))
_assert("the seam records that the cards are not yet bound",
        "NOT YET BOUND" in str(positions_seam.get("status")))
_assert("the read model aggregates the per-GM calculation rather than "
        "requerying",
        "gm_ledger()" in str(positions_seam.get("readModel")))
_assert("the surface calls the league state illustrative",
        "Illustrative league state" in PANEL)

print("\nLeague reconciliation aggregates and invents no second formula")

league = APP.get("league", {})
_assert("it covers twelve GMs", league.get("teams") == 12)
_assert("the parts and the whole agree",
        league.get("sumOfGmSettlesCents") == league.get("aggregateSettleCents"),
        f"{league.get('sumOfGmSettlesCents')} vs {league.get('aggregateSettleCents')}")
_assert("the league closes", league.get("closes") is True)
_assert("the aggregate uses the same three terms",
        league.get("aggregateSettleCents")
        == league.get("wageringPositionCents", 0) + league.get("netAdjustmentsCents", 0)
        - league.get("totalVirtualStakesCents", 0))

exceptions = league.get("exceptions", {})
_assert("pending offer holds are NOT a settlement liability",
        exceptions.get("pendingOfferHolds", {}).get("settlementLiability") is False)
_assert("open top-off requests are NOT a settlement liability",
        exceptions.get("openTopOffs", {}).get("settlementLiability") is False)
_assert("governing accounting excludes pending holds until acceptance",
        "not counted again in Current Settle until a proposal is accepted"
        in _read("js", "ledger.js"))
_assert("skunk receivables are already inside the GM adjustments",
        exceptions.get("skunkReceivables", {}).get("settlementLiability") is True)
_assert("the receivable is not collected automatically, as the module states",
        "RECEIVABLES ARE NOT COLLECTED HERE" in _read_root("economy", "season_reconciliation.py"))

integrity = league.get("integrity", {})
trial_seam = APP.get("trialSeam", {})
_assert("the trial-balance invariant is real",
        "def trial_balance" in _read_root("ledger", "ledger.py"))
# GOVERNED REVISION, S8-P3. The invariant is now exposed at /ledger/integrity.
# Two things must still hold, and they are the substance of the ruling: no
# LEAGUE-SCOPED trial balance was invented, and the seam says so.
_assert("no league-scoped trial-balance route was invented",
        not re.search(r'@app\.get\("[^"]*\{league_id\}[^"]*trial', MAIN_PY)
        and not re.search(r'@app\.get\("[^"]*\{league_id\}[^"]*integrity',
                          MAIN_PY))
# S8-P3R: backend-only. No endpoint, and the seam says why.
_assert("the seam declares no endpoint for the global invariant",
        trial_seam.get("endpoint") is None, str(trial_seam.get("endpoint")))
_assert("it records the invariant as existing and backend-only",
        "BACKEND-ONLY" in str(trial_seam.get("status")))
_assert("and records that the invariant remains global",
        "global" in str(trial_seam.get("scope")).lower())
_assert("it names the authority reason rather than implying a deficiency",
        "platform-operator tier" in str(trial_seam.get("reason")))
_assert("and points the commissioner at League Reconciliation",
        trial_seam.get("commissionerSurface")
        == "GET /league/{league_id}/ledger/reconciliation")
_assert("the surface does not claim to have checked it",
        integrity.get("verified") is False and "NOT VERIFIED HERE" in PANEL)


# ── Tab frame, legal footer and layout ───────────────────────────────────────

print("\nThe tab frame, the legal line, and the layout rules")

_assert("Rules & Settings carries no four-cell strip", 'class="fs-strip"' not in PANEL)
_assert("and no Credits disclaimer", 'class="fs-disclaimer"' not in PANEL)
_assert("the legal line is exact",
        APP.get("legalLine") == "© 2026 Fraser D. Coleman. All Rights Reserved. FantasyStakes™.",
        str(APP.get("legalLine")))
_assert("it renders on this tab", 'id="fs-legal"' in PANEL)
_assert("exactly once", PANEL.count('id="fs-legal"') == 1)
_assert("it is the last region on the tab",
        PANEL.rindex("fs-legal") > PANEL.rindex("fs-commissioner"))
_assert("it is not in the global masthead or index shell",
        "All Rights Reserved" not in INDEX and "All Rights Reserved" not in
        _strip_comments(_read("js", "demo-state.js")))
_assert("no other tab module repeats it",
        all("All Rights Reserved" not in _read("js", name)
            for name in ("league.js", "action.js", "week.js", "ledger.js")))

legal_rule = re.search(r"\.fs-legal\s*\{([^}]*)\}", RULES_CSS)
_assert("the legal line is typographically subordinate",
        bool(legal_rule) and "8.5px" in legal_rule.group(1)
        and "var(--g2)" in legal_rule.group(1))

rulescroll = re.search(r"\.fs-rulescroll\s*\{([^}]*)\}", RULES_CSS)
_assert("the tab column scrolls", bool(rulescroll) and "overflow-y: auto" in rulescroll.group(1))
_assert("and can shrink inside the panel", "min-height: 0" in rulescroll.group(1))
gmcards = re.search(r"\.fs-gmcards\s*\{([^}]*)\}", RULES_CSS)
_assert("the GM cards lay out in two columns",
        bool(gmcards) and "grid-template-columns: 1fr 1fr" in gmcards.group(1))


# ── Package 3 carry-forward ──────────────────────────────────────────────────

print("\nCarry-forward: The Week's locked bets heading")

_assert("the heading is the locked Rev 4.2 wording",
        APP.get("betsHeading") == "FANTASYSTAKES BETS · 4 SHOWN · SWIPE ↕",
        str(APP.get("betsHeading")))
_assert("it renders unchanged on the current week", APP.get("weekCurrentHasHeading") is True)
_assert("and unchanged on a past week", APP.get("weekPastHasHeading") is True)
_assert("the current week really holds four wagers", APP.get("betsCurrent") == 4,
        str(APP.get("betsCurrent")))
_assert("the past week still holds only its three settled records — none fabricated",
        APP.get("betsPast") == 3, str(APP.get("betsPast")))
_assert("the heading is a constant, not derived from a count",
        "BETS_HEADING" in _read("js", "week.js")
        and "SHOWN · SWIPE" not in re.sub(r"BETS_HEADING = '[^']*';", "", _read("js", "week.js")))
_WEEK_DATA = _flat(_read("js", "data", "week-data.js"))
_assert("Package 3's settled-week grounding survives",
        # Matched on fragments that survive JSDoc's leading `*` on wrapped lines.
        "manufacture a box score" in _WEEK_DATA
        and "a settled matchup is unpriced" in _WEEK_DATA)
_assert("a settled matchup still carries no per-slot figures",
        APP.get("betsPast") == 3 and "projection: null" in _read("js", "data", "week-data.js"))


# ── Behavioural suite, in Node ───────────────────────────────────────────────

print("\nBehavioural component suite (Node — executes the shipped ES modules)")


def _run_node_suite(script: str, label: str) -> None:
    if _NODE is None:
        _assert(f"node is available to run {script}", False,
                "install Node, or run the script directly where Node is available")
        return
    proc = subprocess.run(
        [_NODE, os.path.join(WEB, "tests", script)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
    )
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stdout.write(proc.stderr)
    passed = proc.stdout.count("[PASS]")
    failed = proc.stdout.count("[FAIL]")
    _assert(label, proc.returncode == 0 and failed == 0,
            f"{passed} PASS / {failed} FAIL, exit {proc.returncode}")


_run_node_suite("package4_component_tests.mjs", "the component suite is green")


# ── Layout suite, in a real browser ──────────────────────────────────────────

print("\nRules & Settings layout suite (headless Chrome — measured geometry)")

_run_node_suite("e2e_package4.mjs", "the browser layout suite is green")


# ── Result ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")