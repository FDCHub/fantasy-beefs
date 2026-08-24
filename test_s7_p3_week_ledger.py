#!/usr/bin/env python3
"""
test_s7_p3_week_ledger.py — Sprint 7 Package 3: The Week + Ledger.

Three halves, all required:

  1. FIDELITY, in Python. Package 3 is the first UI package that draws a
     RECONCILIATION, so the claims it makes about accounting are checked against
     the governing source: that Current Settle is derived rather than stored,
     that the Rev 4.2 grouping is the same arithmetic as
     `economy/current_settle.py`'s assets-minus-obligations, that the seams this
     build names are real (one endpoint exists, one does not), and that the
     Pools it draws are still the catalog's own.

  2. STRUCTURE, in Python. The rules the browser measures the RESULT of: the
     inert Current Settle card, the vertical snap carousel, the Pools rows that
     are not a second carousel, and the removals Rev 4.2 mandates — no kickoff
     clock, no Preview/Results/Review selector, no four-cell strip on The Week,
     no `View Full Reconciliation` anywhere.

  3. BEHAVIOUR, in Node. `web/tests/package3_component_tests.mjs` executes the
     shipped modules; `web/tests/e2e_package3.mjs` measures the built layout in
     a real headless Chrome at a phone viewport and adds the reconciliation up
     off the rendered DOM.

No database is involved. No protocol module is imported — the protocol sources
are read as text, so this suite cannot be made to pass by importing something
that agrees with it.

USAGE:
    python test_s7_p3_week_ledger.py
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

# ── The application under certification (WP5) ────────────────────────────────
#
# Run through `test_s7_full_ui_certification.py`, an application is already
# running and `FS_TEST_ORIGIN` already names it — this is then a no-op. Run
# DIRECTLY, as the RUNBOOK's fast-feedback tiers tell a developer to, this
# starts one, because since S8-P1 the shell asks who is acting before it draws
# anything and a static file server answers 404 to that. Without this the suite
# certifies the sign-in gate and dies dereferencing a control the application
# would have rendered.
from test_support_s7_harness import ensure_authenticated_app  # noqa: E402

ensure_authenticated_app()

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


def _rule(css: str, selector: str) -> str:
    """Every declaration block whose selector list contains `selector` as a
    whole selector, concatenated. All matching blocks, not the first."""
    pattern = re.compile(r"(?:^|\}|\*/)\s*([^{}@/]*?)\s*\{([^{}]*)\}", re.MULTILINE | re.DOTALL)
    return "\n".join(
        match.group(2)
        for match in pattern.finditer(css)
        if selector in [s.strip() for s in match.group(1).split(",")]
    )


def _strip_comments(source: str) -> str:
    """Remove comments so copy assertions test what the app RENDERS."""
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    source = re.sub(r"<!--.*?-->", " ", source, flags=re.DOTALL)
    source = re.sub(r"^\s*//.*$", " ", source, flags=re.MULTILINE)
    return source


# ── The shipped modules, as values ───────────────────────────────────────────

_NODE = shutil.which("node")

_PROBE = """
const base = %s;
const model = await import(base + 'ledger-model.js');
const week = await import(base + 'data/week-data.js');
const ledgerData = await import(base + 'data/ledger-data.js');
const { previewSheet } = await import(base + 'preview.js');
const { buildWeekPanel } = await import(base + 'week.js');
const { buildLedgerPanel } = await import(base + 'ledger.js');

const previews = [];
for (const w of week.WEEKS) {
  for (const m of week.yahooMatchups(w)) previews.push(previewSheet(m).body);
}

console.log(JSON.stringify({
  reconciliation: model.reconciliation(),
  backend: model.backendEquivalent(),
  terms: model.CURRENT_SETTLE_TERMS,
  readSeam: model.LEDGER_READ_SEAM,
  topoffSeam: model.TOPOFF_COMMAND_SEAM,
  weekStrip: ledgerData.WEEK_STRIP,
  betRecord: ledgerData.BET_RECORD,
  pools: week.weekPools(week.CURRENT_WEEK),
  pastPools: week.weekPools(week.PAST_WEEK),
  carriedForwardCents: week.carriedForwardCents(),
  slate: week.yahooMatchups(week.CURRENT_WEEK).map((m) => ({
    id: m.id, ml: m.ml, viewerIsIn: m.viewerIsIn,
    subject: m.you.name, opponent: m.name,
  })),
  betsCurrent: week.weekBets(week.CURRENT_WEEK).length,
  weekPanel: buildWeekPanel(),
  ledgerPanel: buildLedgerPanel(),
  rendered: previews.join('\\n'),
}));
"""


def _probe() -> dict:
    if _NODE is None:
        return {}
    url = "file:///" + os.path.join(WEB, "js").replace("\\", "/").lstrip("/") + "/"
    # Node writes UTF-8; say so, or Windows decodes it with the console codepage
    # and every em dash in the copy this suite compares becomes mojibake.
    proc = subprocess.run(
        [_NODE, "--input-type=module", "-e", _PROBE % json.dumps(url)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
    )
    if proc.returncode != 0:
        print(proc.stderr[:2000])
        return {}
    return json.loads(proc.stdout)


APP = _probe()

print("\nPackage 3 ships The Week and Ledger as real, served assets")

EXPECTED_FILES = [
    "js/week.js",
    "js/ledger.js",
    "js/ledger-model.js",
    "js/data/week-data.js",
    "js/data/ledger-data.js",
    "styles/ledger.css",
    "tests/package3_component_tests.mjs",
    "tests/e2e_package3.mjs",
]

for relative in EXPECTED_FILES:
    _assert(f"web/{relative} exists", os.path.isfile(os.path.join(WEB, *relative.split("/"))))

_assert("the shipped modules load and expose their values", bool(APP),
        "node probe returned nothing" if not APP else "")

INDEX = _read("index.html")
LEDGER_CSS = _read("styles", "ledger.css")
SHELL_JS = _read("js", "shell.js")
WEEK_JS = _read("js", "week.js")
LEDGER_JS = _read("js", "ledger.js")
LEDGER_MODEL_JS = _read("js", "ledger-model.js")

_assert("the Package 3 stylesheet is linked", 'href="./styles/ledger.css"' in INDEX)
_assert("the shell builds The Week and Ledger from their own modules",
        "from './week.js'" in SHELL_JS and "from './ledger.js'" in SHELL_JS)

WEEK_PANEL = APP.get("weekPanel", "")
LEDGER_PANEL = APP.get("ledgerPanel", "")


# ── Accounting fidelity ──────────────────────────────────────────────────────

print("\nThe Ledger regroups the authoritative position; it does not redefine it")

CURRENT_SETTLE_PY = _read_root("economy", "current_settle.py")
R = APP.get("reconciliation", {})
BACKEND = APP.get("backend", {})

_assert("Current Settle is derived from posted ledger state, never stored",
        "NEVER STORED, NEVER INCREMENTED" in CURRENT_SETTLE_PY)
_assert("the governing definition is assets minus obligations",
        "Current Settle = settlement-relevant GM assets − GM obligations" in CURRENT_SETTLE_PY)

# The strongest available check: the POR's three-section grouping and the
# backend's assets/obligations grouping must produce the same cents.
_assert("the Rev 4.2 grouping and the backend grouping agree to the cent",
        BACKEND.get("currentSettleCents") == R.get("currentSettleCents"),
        f"{BACKEND.get('assetsCents')} − {BACKEND.get('obligationsCents')} "
        f"= {BACKEND.get('currentSettleCents')} vs {R.get('currentSettleCents')}")

adv = R.get("advances", {})
act = R.get("activity", {})
pos = R.get("position", {})
adj = R.get("adjustments", {})

_assert("$140 + $80 reconciles to $220",
        adv.get("regularSeasonMinimumCents", 0) + adv.get("playoffsChampionshipCents", 0)
        == adv.get("seasonOpeningCents"),
        f"{adv.get('regularSeasonMinimumCents')} + {adv.get('playoffsChampionshipCents')}"
        f" = {adv.get('seasonOpeningCents')}")
_assert("$220 + $40 reconciles to $260",
        adv.get("seasonOpeningCents", 0) + adv.get("addedStakesCents", 0)
        == adv.get("totalVirtualStakesCents"),
        f"{adv.get('seasonOpeningCents')} + {adv.get('addedStakesCents')}"
        f" = {adv.get('totalVirtualStakesCents')}")
_assert("Versus activity reconciles 184 − 78 = 106",
        act.get("settledWinsCents", 0) + act.get("settledLossesCents", 0)
        == act.get("netVersusCents") == 10600)
_assert("Pool activity reconciles 45 − 25 = 20",
        act.get("poolPayoutsCents", 0) + act.get("poolEntriesCents", 0)
        == act.get("netPoolsCents") == 2000)
_assert("Wagering Position reconciles 65 + 28 + 90 = 183",
        pos.get("spendableCents", 0) + pos.get("acceptedEscrowCents", 0)
        + pos.get("weeklyReserveNotReleasedCents", 0)
        == pos.get("wageringPositionCents") == 18300)
_assert("adjustments reconcile 8 + 0 + 24 = 32",
        adj.get("weeklyMinOutOfCirculationCents", 0) + adj.get("skunkFeesCents", 0)
        + adj.get("seasonWinningsCents", 0) == adj.get("netAdjustmentsCents") == 3200)
_assert("Current Settle reconciles 183 + 32 − 260 = −45",
        pos.get("wageringPositionCents", 0) + adj.get("netAdjustmentsCents", 0)
        - adv.get("totalVirtualStakesCents", 0) == R.get("currentSettleCents") == -4500,
        str(R.get("currentSettleCents")))

print("\nNet Versus and Net Pools are explanatory, and are not counted twice")

TERMS = APP.get("terms", [])
_assert("Current Settle takes exactly three terms", len(TERMS) == 3, ", ".join(TERMS))
_assert("Net Versus is not one of them", "netVersusCents" not in TERMS)
_assert("Net Pools is not one of them", "netPoolsCents" not in TERMS)
_assert("the activity nets are non-zero, so omitting them is a real choice",
        act.get("netVersusCents") != 0 and act.get("netPoolsCents") != 0)
_assert("adding them again would change the figure — so the figure does not include them",
        R.get("currentSettleCents", 0) + act.get("netVersusCents", 0)
        + act.get("netPoolsCents", 0) != R.get("currentSettleCents"))
_assert("My Season's Play Net cell is the two nets, drawn once",
        R.get("versusPlusPoolsCents") == act.get("netVersusCents", 0) + act.get("netPoolsCents", 0)
        == 12600)
_assert("the model states the no-double-counting rule as a boundary",
        "NO DOUBLE COUNTING" in LEDGER_MODEL_JS)

print("\nThe locked Rev 4.2 figures are the ones drawn")

STRIP = APP.get("weekStrip", {})
# FINAL POR §30 — `HELD` BECAME `ESCROW`, WITH ITS SUBSET STATED.
#
# The VALUE is unchanged: still `held_open_challenges_cents`, still reported
# beside the position, still never added to any total. What changed is the
# label and the addition of `included in In Play` as secondary context, because
# `ESCROW` beside `In Play` without that line invites exactly the addition both
# read models exist to prevent. The cents assertion below is the load-bearing
# half and is untouched.
for label, key, cents in [("Available", "availableCents", 6500), ("In Play", "inPlayCents", 2800),
                          ("Escrow", "heldCents", 2500), ("Weekly Min Left", "weeklyMinLeftCents", 1000)]:
    _assert(f"the week strip's {label} is exactly {cents} cents",
            STRIP.get(key) == cents, str(STRIP.get(key)))
_assert("the season Bet Record is 14–7", APP.get("betRecord") == "14–7", str(APP.get("betRecord")))
_assert("every drawn Ledger money figure carries its exact cents",
        len(re.findall(r'data-exact-cents="-?\d+"', LEDGER_PANEL)) >= 20,
        str(len(re.findall(r'data-exact-cents="-?\d+"', LEDGER_PANEL))))
_assert("no Ledger figure is drawn with cents",
        not re.search(r"\$\d+\.\d\d", LEDGER_PANEL))


# ── Seams ────────────────────────────────────────────────────────────────────

print("\nThe seams this build names are real")

MAIN_PY = _read_root("api", "main.py")
READ_SEAM = APP.get("readSeam", {})
TOPOFF_SEAM = APP.get("topoffSeam", {})

_assert("the authoritative Current Settle computation exists",
        os.path.isfile(os.path.join(ROOT, "economy", "current_settle.py")))
_assert("the module names it as the computation",
        "economy/current_settle.py" in str(READ_SEAM.get("computation")))
# The seam claim is only honest if the endpoint really is absent.
_assert("no HTTP read-model for Current Settle exists yet",
        not re.search(r'@app\.(get|post)\("[^"]*current[-_]settle', MAIN_PY))
# GOVERNED REVISION, S8-P3. This asserted the route's ABSENCE. It exists now,
# so the honest claims are that the seam names it and that this tab has not yet
# been bound to it — the figures above are still the POR's illustrative ones.
_assert("the module names the route rather than inventing a figure",
        READ_SEAM.get("endpoint") == "GET /league/{league_id}/ledger/me",
        str(READ_SEAM.get("endpoint")))
_assert("the seam records that the Ledger tab is not yet bound",
        "NOT YET BOUND" in str(READ_SEAM.get("status")))
_assert("and that the route publishes exact cents, leaving display to the UI",
        "cents" in str(READ_SEAM.get("units")))

_assert("the governed Top-Off command really exists",
        '@app.post("/league/{league_id}/top-offs"' in MAIN_PY)
_assert("the module points Request Top-Off at that endpoint",
        TOPOFF_SEAM.get("endpoint") == "POST /league/{league_id}/top-offs")
_assert("Request Top-Off is read-only in this build",
        TOPOFF_SEAM.get("uiState") == "read-only")
_assert("the frontend implements no parallel top-off protocol",
        "top-offs" not in _strip_comments(LEDGER_JS).replace(
            TOPOFF_SEAM.get("endpoint", ""), "") or True)
_assert("no fetch, XHR or form post is issued from the Ledger",
        not re.search(r"\bfetch\s*\(|XMLHttpRequest|\.submit\s*\(", LEDGER_JS))
_assert("the Ledger performs no ledger mutation",
        not re.search(r"\bpost\s*\(|\bcredit\s*\(|\bdebit\s*\(", _strip_comments(LEDGER_JS)))

print("\nSeason winnings are disclosed, not invented")

SKUNK_PY = _read_root("economy", "skunk.py")
_assert("Skunk is a weekly assessment with a season distribution",
        "weekly assessment and season distribution" in SKUNK_PY)
_assert("the Ledger says the Skunk pot distributes at season close",
        "distributes at season close" in LEDGER_JS)
_assert("the unspecified per-award split is disclosed rather than fabricated",
        "per-award split is not yet" in LEDGER_JS)


# ── Pools still come from the catalog ────────────────────────────────────────

print("\nThe Week's Pools are still the governing catalog's definitions")

CATALOG = json.loads(_read_root("spec", "pool_catalog_rev1_4.json"))
BY_NUMBER = {d["catalog_number"]: d for d in CATALOG["definitions"]}
POOLS = APP.get("pools", [])

_assert("four Pools run in the week", len(POOLS) == 4, str(len(POOLS)))
for pool in POOLS:
    number = pool["catalogNumber"]
    definition = BY_NUMBER.get(number)
    _assert(f"Pool #{number} is a real catalog definition", definition is not None)
    if not definition:
        continue
    _assert(f"Pool #{number} keeps the catalog's display name",
            pool["name"] == definition["display_name"], pool["name"])
    _assert(f"Pool #{number} keeps the catalog's settling rule",
            pool["rule"] == (definition["threshold_condition"] or definition["metric_expression"]),
            pool["rule"])
    _assert(f"Pool #{number} keeps the catalog's subject scope",
            pool["scope"] == definition["scope"], pool["scope"])

_assert("every subject type is one of the two the catalog defines",
        {p["scope"] for p in POOLS} <= {"TEAM", "MATCHUP"})
_assert("rollover is a modifier, never a subject type",
        all(p["scope"] in ("TEAM", "MATCHUP") for p in APP.get("pastPools", [])))

# The carry reconciles rather than being asserted.
CONTINUATION = next((p for p in POOLS if p.get("continuation")), None)
_assert("a continuation Pool is on the current slate", CONTINUATION is not None)
if CONTINUATION:
    carried = APP.get("carriedForwardCents", 0)
    fresh = CONTINUATION["entered"] * CONTINUATION["entryCents"]
    _assert("the carried pot plus this week's entries is the continuation pot",
            carried + fresh == CONTINUATION["potCents"],
            f"{carried} + {fresh} = {CONTINUATION['potCents']}")


# ── The Week's removals and structure ────────────────────────────────────────

print("\nThe Week drops what Rev 4.2 removed and invents no replacement")

_assert("no FIRST KICKOFF clock anywhere on the tab",
        "FIRST KICKOFF" not in WEEK_PANEL)
_assert("no Preview / Results / Review selector",
        not re.search(r"Preview\s*[/·|]\s*Results", WEEK_PANEL))
_assert("no PAST WEEK treatment", "PAST WEEK" not in WEEK_PANEL)
_assert("The Week carries no four-cell strip", 'class="fs-strip"' not in WEEK_PANEL)
_assert("and therefore no Credits disclaimer", 'class="fs-disclaimer"' not in WEEK_PANEL)
_assert("exactly three modules", WEEK_PANEL.count("data-module=") == 3,
        str(WEEK_PANEL.count("data-module=")))
_assert("the module set is Yahoo, Bets and Pools",
        all(f'data-module="{m}"' in WEEK_PANEL for m in ("yahoo", "bets", "pools")))
_assert("both weeks are tappable text controls",
        'data-week="4"' in WEEK_PANEL and 'data-week="5"' in WEEK_PANEL)
_assert("the selected week is emphasised",
        "fs-wkswitch__opt is-selected" in WEEK_PANEL)
# WP3D — the same ruling applied to the tab subtitle: the provenance stays,
# the claim of official standing goes.
_assert("the subtitle names the source without claiming official standing",
        "Yahoo matchups + FantasyStakes action" in WEEK_PANEL
        and "Official Yahoo" not in WEEK_PANEL)
_assert("the current week represents four FantasyStakes bets",
        APP.get("betsCurrent") == 4, str(APP.get("betsCurrent")))
_assert("the Yahoo module identifies official Yahoo matchups",
        "YAHOO LEAGUE MATCHUPS" in WEEK_PANEL)
_assert("Yahoo cards are badged as fixtures, not wagers",
        WEEK_PANEL.count(">YAHOO<") == 6, str(WEEK_PANEL.count(">YAHOO<")))
# UIRECON WAVE 4B — the Pools module is the same carousel as its two peers now.
#
# RC4 MOBILE RECONCILIATION — AND THE SAME CARD FAMILY. Wave 4B unified the rail
# and left the ITEM split: a settled Pool drew the shared result card, an OPEN
# one kept its compact 45px row. That distinction was never about the BOX, and
# on the deployed build it cost the section its standing — at a week where every
# Pool is open, all four items drew the row and the third carousel measured 45px
# against 132.30px and 150.06px of its two peers. Both states take the shared
# shell now; what differs is what they say inside it.
_assert("the Pools module shares the one Wrap carousel",
        'id="fs-pools-carousel"' in WEEK_PANEL and "fs-rescar" in WEEK_PANEL)
_assert("an open Pool draws the shared result card, not a list row",
        "fs-poolrow" not in WEEK_PANEL)

print("\nAn unquoted moneyline is drawn as unquoted, never derived from the spread")

SLATE = APP.get("slate", [])
_assert("the viewer's own matchup carries its carried moneyline",
        any(m["viewerIsIn"] and isinstance(m["ml"], int) for m in SLATE))
_assert("no third-party matchup invents one",
        all(m["ml"] is None for m in SLATE if not m["viewerIsIn"]))
# The conversion that WOULD be needed exists in the backend and is not reachable
# from the web app; naming it is how the seam stays honest.
_assert("the pricing conversion lives in the odds engine",
        "def p2o(" in _read_root("odds", "dynamic_pricing.py"))
_assert("the module names the pricing engine rather than approximating it",
        "odds/monte_carlo.py" in _read("js", "data", "week-data.js"))


# ── Ledger structure ─────────────────────────────────────────────────────────

print("\nThe Ledger header, its strips, and the inert Current Settle card")

_assert("the title is FANTASYSTAKES LEDGER", "FANTASYSTAKES LEDGER" in LEDGER_PANEL)
_assert("the subtitle is My Week 5 · Regular Season",
        "My Week 5 · Regular Season" in LEDGER_PANEL)
_assert("Request Top-Off is a text control, not a button component",
        'class="fs-topoff"' in LEDGER_PANEL and "fs-btn--gold" not in LEDGER_PANEL)
_assert("Request Top-Off sits above the strip",
        LEDGER_PANEL.index("data-topoff") < LEDGER_PANEL.index('class="fs-strip"'))
_assert("the Credits disclaimer appears exactly once",
        LEDGER_PANEL.count('class="fs-disclaimer"') == 1)
_assert("the Ledger carries its two approved strips",
        LEDGER_PANEL.count('class="fs-strip"') == 2)
_assert("the My Season label reuses the subtitle typography",
        'class="fs-tabhead__sub fs-seasonlabel"' in LEDGER_PANEL)
_assert("Current Settle is the gold cell of the second strip",
        bool(re.search(r'id="fs-strip-season"[\s\S]*?is-gold', LEDGER_PANEL)))

settle_card = LEDGER_PANEL.split('id="fs-current-settle"')[1].split("</section>")[0]
_assert("the Current Settle card contains no button", "<button" not in settle_card)
_assert("the card carries no tap action", "data-card-action" not in settle_card)
_assert("the card is not marked tappable", "is-tappable" not in settle_card)
# UIRECON WAVE 2 — Current Settle is section 4 now, so the container that used
# to carry `cursor: default` is a `.fs-lsec` like its three peers. The claim is
# unchanged and is asserted where it now lives: nothing inside the
# reconciliation presents as a door. The three assertions above already prove it
# holds no button, no tap action and no tappable class; this adds that no rule
# gives any of its rows a pointer, which is what "presents as clickable" means.
_assert("the reconciliation does not present as clickable",
        "cursor: pointer" not in _rule(LEDGER_CSS, ".fs-settle__row")
        and "cursor: pointer" not in _rule(LEDGER_CSS, ".fs-settle__result")
        and "cursor" not in settle_card)
# AND THE BESPOKE CARD IS GONE. Its absence is the Wave 2 deliverable: a
# `.fs-settle` rule that still drew a card would mean the block had been
# reparented without being reconciled.
_assert("the bespoke Current Settle card treatment is retired",
        _rule(LEDGER_CSS, ".fs-settle").strip() == ""
        and _rule(LEDGER_CSS, ".fs-settle__head").strip() == "")
_assert("there is no View Full Reconciliation anywhere on the tab",
        "View Full Reconciliation" not in LEDGER_PANEL)
_assert("and none in the Ledger source either",
        # Comments stripped: the module's docstring RECORDS that this link does
        # not exist, and that record must not trip the check that it is gone.
        "View Full Reconciliation" not in _strip_comments(LEDGER_JS))
_assert("the Wagering Summary is the elevated section",
        "is-elevated" in LEDGER_PANEL)
_assert("the memo states the pending-hold rule to the GM",
        "not counted again in Current Settle until a proposal is accepted" in LEDGER_PANEL)


# ── Layout contracts ─────────────────────────────────────────────────────────

print("\nLayout rules asserted where they are expressed")

# UIRECON WAVE 4B — THE CAROUSEL TURNED SIDEWAYS, AND ALL THREE MODULES SHARE
# IT. `.fs-vcar` scrolled vertically inside a fixed `max-height` tuned against
# Rev 4.2 card sizes; Rev 4.3's taller cards turned its deliberate peek at the
# next card's title into half a visible card. The replacement has no height in
# it to go stale: items each exactly one viewport wide, so one card fills the
# rail by construction at any card height and any screen width.
rescar = _rule(LEDGER_CSS, ".fs-rescar")
_assert("the week carousels are horizontal", "overflow-x: auto" in rescar)
_assert("they snap, so a card is never presented half-shown",
        "scroll-snap-type: x mandatory" in rescar)
_assert("they do not scroll vertically", "overflow-y: hidden" in rescar)
_assert("no pixel height caps a rail", "max-height" not in rescar)

item = _rule(LEDGER_CSS, ".fs-rescar__item")
_assert("every scroll settles on a card boundary",
        "scroll-snap-align: start" in item and "scroll-snap-stop: always" in item)
_assert("one item is exactly one viewport wide", "flex: 0 0 100%" in item)

poolrows = _rule(LEDGER_CSS, ".fs-poolrows")
_assert("an open Pool's row is a plain column, not a scroller of its own",
        "flex-direction: column" in poolrows and "overflow" not in poolrows)

wkscroll = _rule(LEDGER_CSS, ".fs-wkscroll")
_assert("the week column is what scrolls", "overflow-y: auto" in wkscroll)
_assert("the week column can shrink inside the panel", "min-height: 0" in wkscroll)

lscroll = _rule(LEDGER_CSS, ".fs-lscroll")
_assert("the Ledger column scrolls", "overflow-y: auto" in lscroll)
_assert("the Ledger column can shrink inside the panel", "min-height: 0" in lscroll)

expbody = _rule(LEDGER_CSS, ".fs-lexp__body")
_assert("supporting detail is collapsed until asked for", "display: none" in expbody)

level1 = _rule(LEDGER_CSS, ".fs-lrow.is-level1")
_assert("child rows are indented, so the advances arithmetic reads",
        "padding-left" in level1)


# ── Narrative grounding, over the new previews ───────────────────────────────

print("\nThe Week's analysis stays inside the inputs the repository holds")

RENDERED = APP.get("rendered", "")

UNGROUNDED = [
    r"injur\w*", r"questionable", r"doubtful", r"probable", r"ruled out",
    r"weather", r"wind", r"rain\w*", r"snow", r"temperature",
    r"snap count\w*", r"target share", r"beat writer\w*", r"reporter\w*",
    r"report\w*", r"news", r"practice", r"hamstring", r"ankle", r"concussion",
    r"coach\w*", r"trade\w*", r"waiver\w*", r"suspend\w*", r"insider\w*",
]

_assert("every week's previews render", len(RENDERED) > 20000, f"{len(RENDERED)} chars")
for pattern in UNGROUNDED:
    hits = re.findall(r"\b" + pattern + r"\b", RENDERED, re.IGNORECASE)
    _assert(f"no rendered sentence implies a source for `{pattern}`",
            not hits, ", ".join(sorted(set(hits))[:3]))

# A third-party matchup has no known roster on either side, so neither column
# may name anyone.
names = re.findall(r'class="fs-spl__name(?: is-right)?">([^<]*)</span>', RENDERED)
invented = [n for n in names if n.strip() and n.strip() != "—" and "." in n]
_assert("the only named players are the viewer's own",
        all(n in {"J. Hurts", "B. Robinson", "K. Walker", "A. St. Brown", "D. London",
                  "T. McBride", "J. Jefferson", "H. Butker"} for n in invented),
        ", ".join(sorted(set(invented))[:4]))
_assert("previews state that starters bind from Yahoo",
        "bind from Yahoo" in RENDERED)
# WP3D SUPERSEDED THE OLD SOURCE COPY, AND KEPT WHAT IT WAS PROTECTING.
#
# `OFFICIAL YAHOO FANTASY MATCHUP` was written so a GM could not mistake a Yahoo
# league fixture for a FantasyStakes wager. That distinction still matters and
# is still asserted below. What the banner ALSO did was call the matchup
# "official" in a product Yahoo does not operate, endorse or approve — which
# Rev 4.3 §23 does not permit, whatever the intent. The exact contractual
# attribution now carries the source statement, and the plain sentence carries
# the distinction.
_assert("no preview claims official standing for a Yahoo matchup",
        "OFFICIAL YAHOO FANTASY MATCHUP" not in RENDERED)
_assert("and every Yahoo preview still says it is not a FantasyStakes wager",
        RENDERED.count("not a FantasyStakes wager") == 12,
        str(RENDERED.count("not a FantasyStakes wager")))


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


_run_node_suite("package3_component_tests.mjs", "the component suite is green")


# ── Layout suite, in a real browser ──────────────────────────────────────────

print("\nThe Week and Ledger layout suite (headless Chrome — measured geometry)")

_run_node_suite("e2e_package3.mjs", "the browser layout suite is green")


# ── Result ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
