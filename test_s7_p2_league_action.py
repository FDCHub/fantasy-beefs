#!/usr/bin/env python3
"""
test_s7_p2_league_action.py — Sprint 7 Package 2: League + Action.

Three halves, all required:

  1. FIDELITY, in Python. Package 2 is the first UI package that makes claims
     ABOUT THE PROTOCOL — market names, the minimum stake, proposal states,
     Response Card names, Pool definitions and the Locked/Dynamic explanations.
     Every one of those is checked here against the governing source rather than
     against a copy of it, so a UI string cannot drift from the rule it quotes.
     These assertions read the real modules' values, not their source text.

  2. STRUCTURE, in Python. The layout contracts the browser measures the RESULT
     of, asserted at the point they are expressed: the vertical snap carousel,
     the non-scrolling 2x2 Pools grid, the single-row rails, and the equal
     billing of League's two zones.

  3. BEHAVIOUR, in Node. `web/tests/package2_component_tests.mjs` executes the
     shipped ES modules; `web/tests/e2e_package2.mjs` measures the built layout
     in a real headless Chrome at a phone viewport.

No database is involved. No protocol module is imported — the protocol sources
are read as text, so this suite cannot be made to pass by importing something
that agrees with it.

USAGE:
    python test_s7_p2_league_action.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# As in Package 1: this suite reports on typography — the middot, the em dash,
# the U+2212 minus and the typographic apostrophe. On a Windows console
# defaulting to cp1252 those would raise UnicodeEncodeError mid-run and report a
# green suite as a crash.
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


def _plain(text: str) -> str:
    """Normalise typographic punctuation so a quotation is compared on its
    words. A specification written with straight quotes and a UI rendering it
    with typographic ones are the same sentence, and a suite that failed on that
    difference would teach the next reader to paste the wrong character."""
    swaps = {"’": "'", "‘": "'", "“": '"', "”": '"',
             "—": "-", "–": "-", "−": "-", " ": " "}
    for bad, good in swaps.items():
        text = text.replace(bad, good)
    return re.sub(r"\s+", " ", text).strip()


# ── The shipped modules, as values ───────────────────────────────────────────
#
# One Node call hands back what the app actually holds: the mode copy, the
# market table, the minimum, the Pool rows, the wager cards, and the fully
# rendered Matchup Preview for all eleven matchups. Asserting against these
# values rather than against source text is the point — a suite that grepped
# wager-model.js would pass on a string that never reaches a GM.

_NODE = shutil.which("node")

_PROBE = """
const base = %s;
const model = await import(base + 'wager-model.js');
const league = await import(base + 'data/league-data.js');
const action = await import(base + 'data/action-data.js');
const { previewSheet } = await import(base + 'preview.js');
console.log(JSON.stringify({
  modeCopy: model.MODE_COPY,
  markets: model.MARKETS,
  minStakeCents: model.MIN_STAKE_CENTS,
  pools: league.POOLS,
  poolEntryCents: league.POOL_ENTRY_CENTS,
  cards: action.CARDS,
  rendered: league.allMatchups().map((m) => previewSheet(m).body).join('\\n'),
}));
"""


def _probe() -> dict:
    if _NODE is None:
        return {}
    url = "file:///" + os.path.join(WEB, "js").replace("\\", "/").lstrip("/") + "/"
    # Node writes UTF-8. Without saying so, Python decodes it with the console
    # codepage, and on Windows every em dash and apostrophe in the copy this
    # suite compares would arrive as mojibake — turning a verbatim quotation
    # into a false failure.
    proc = subprocess.run(
        [_NODE, "--input-type=module", "-e", _PROBE % json.dumps(url)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
    )
    if proc.returncode != 0:
        print(proc.stderr[:2000])
        return {}
    return json.loads(proc.stdout)


APP = _probe()

print("\nPackage 2 ships League and Action as real, served assets")

EXPECTED_FILES = [
    "js/league.js",
    "js/action.js",
    "js/composer.js",
    "js/preview.js",
    "js/narrative.js",
    "js/wagercard.js",
    "js/wager-model.js",
    "js/data/league-data.js",
    "js/data/action-data.js",
    "styles/wager.css",
    "styles/tabs.css",
    "tests/package2_component_tests.mjs",
    "tests/e2e_package2.mjs",
    "tests/browser-harness.mjs",
]

for relative in EXPECTED_FILES:
    _assert(f"web/{relative} exists", os.path.isfile(os.path.join(WEB, *relative.split("/"))))

_assert("the shipped modules load and expose their values", bool(APP),
        "node probe returned nothing" if not APP else "")

INDEX = _read("index.html")
TABS_CSS = _read("styles", "tabs.css")
WAGER_CSS = _read("styles", "wager.css")
COMPONENTS_CSS = _read("styles", "components.css")
# UIRECON Rev 1.4 — Play's Pool carousel is markup in `league.js` and geometry
# in `gameplay.css`, so both are read here.
GAMEPLAY_CSS = _read("styles", "gameplay.css")
LEAGUE_JS = _read("js", "league.js")
COMPOSER_JS = _read("js", "composer.js")
SHELL_JS = _read("js", "shell.js")

_assert("both Package 2 stylesheets are linked",
        'href="./styles/wager.css"' in INDEX and 'href="./styles/tabs.css"' in INDEX)
_assert("the shell builds League and Action from their own modules",
        "from './league.js'" in SHELL_JS and "from './action.js'" in SHELL_JS)


# ── Protocol fidelity ────────────────────────────────────────────────────────
#
# Each block below reads the governing source as text and compares it to the
# value the app holds.

print("\nThe UI quotes the protocol rather than paraphrasing it")

LIFECYCLE_PY = _read_root("beefs", "proposal_lifecycle.py")
WALLET_PY = _read_root("wallet", "wallet_manager.py")

# Markets — the persisted value, not the display label.
valid_types = re.search(r"VALID_WAGER_TYPES\s*=\s*\(([^)]*)\)", LIFECYCLE_PY)
persisted_protocol = set(re.findall(r'"([^"]+)"', valid_types.group(1))) if valid_types else set()
persisted_ui = {m["persisted"] for m in APP.get("markets", [])}
_assert("every market persists a value the proposal lifecycle accepts",
        bool(persisted_ui) and persisted_ui <= persisted_protocol,
        f"{sorted(persisted_ui)} vs {sorted(persisted_protocol)}")
_assert("the UI offers every wager type the protocol defines",
        persisted_ui == persisted_protocol,
        f"{sorted(persisted_ui)} vs {sorted(persisted_protocol)}")
_assert("ML is a display label for the persisted `straight`, not a new type",
        any(m["id"] == "ml" and m["persisted"] == "straight" for m in APP.get("markets", [])))

# The minimum stake.
min_bet = re.search(r"^MIN_BET\s*=\s*([0-9.]+)", WALLET_PY, re.MULTILINE)
_assert("the composer's minimum is the wallet's MIN_BET, in cents",
        bool(min_bet) and APP.get("minStakeCents") == round(float(min_bet.group(1)) * 100),
        f"{APP.get('minStakeCents')} vs {min_bet.group(1) if min_bet else '?'}")

# MAX_BET_PCT is a single-party bet-sizing cap. Enforcing it on a challenge
# would fabricate a limit the challenge engine does not apply, so its absence
# from the composer is asserted, not merely commented.
WAGER_MODEL_JS = _read("js", "wager-model.js")
_assert("the composer does not invent the single-party MAX_BET_PCT cap",
        "MAX_BET_PCT" not in re.sub(r"/\*.*?\*/", " ", WAGER_MODEL_JS, flags=re.DOTALL))

# Proposal states.
protocol_states = {
    value for value in re.findall(
        r"^(?:OFFERED|COUNTERED|ACCEPTED|DECLINED|EXPIRED|CANCELLED)\s*=\s*\"([a-z]+)\"",
        LIFECYCLE_PY, re.MULTILINE)
}
card_states = {c["protocolState"] for c in APP.get("cards", [])}
_assert("every card carries a persisted proposal state",
        bool(card_states) and card_states <= protocol_states,
        f"{sorted(card_states)} vs {sorted(protocol_states)}")

# Rail names are a place to look, never a state — so no card may carry one.
RAIL_NAMES = {"action", "waiting", "live", "completed", "action required"}
_assert("no card stores a rail name where a protocol state belongs",
        not (card_states & RAIL_NAMES))

# Response Cards — the taxonomy is five, and Rev1.1 introduces no sixth.
RESPONSE_SPEC = _read_root("FantasyBeefs_Response_Card_Specification_Rev1_1.md")
FIVE_CARDS = {"Incoming", "Accepted", "Countered", "Declined", "Expired"}
card_names = {c["responseCard"] for c in APP.get("cards", [])}
_assert("the Response Card taxonomy is still the five cards",
        "taxonomy remains five cards" in RESPONSE_SPEC)
_assert("every card names a Response Card from that taxonomy",
        bool(card_names) and card_names <= FIVE_CARDS,
        f"{sorted(card_names)}")

# The Countered card is perspective-aware: the issuer view is actionable and
# the recipient view is read-only (Rev1.1 §6). Action's rails must reproduce
# that split rather than putting both on one rail.
countered = [c for c in APP.get("cards", []) if c["protocolState"] == "countered"]
_assert("the specification makes the Countered card perspective-aware",
        "issuer actionable, recipient read-only" in RESPONSE_SPEC)
_assert("a countered wager is actionable for the issuer and read-only for the recipient",
        {c["role"] for c in countered} == {"issuer", "recipient"} and len(countered) == 2,
        f"{[(c['id'], c['role']) for c in countered]}")
_assert("the read-only pending-counter view carries no actions",
        all("actions" not in c for c in countered if c["role"] == "recipient"))

# A counter carries its own terms (§7.2) — so a countered card may not show a
# wager with no money in it.
_assert("the proposal lifecycle lets a counter set its own stake",
        "counter may change the Anchor Stake" in LIFECYCLE_PY)
_assert("every card shows real terms, and the pot is both stakes",
        all(c["potCents"] == c["yourStakeCents"] + c["opponentStakeCents"] and c["potCents"] > 0
            for c in APP.get("cards", [])),
        f"{[c['id'] for c in APP.get('cards', []) if c['potCents'] <= 0]}")

# Locked and Dynamic, quoted from the adopted ruling.
RULING = _read_root("spec", "LOCKED_VS_DYNAMIC_WAGER_MODEL_RULING.md")
quoted = re.search(r"Corrected card copy \(Dynamic offer\):\*\*\s*[\"“](.+?)[\"”]", RULING, re.DOTALL)
dynamic_body = APP.get("modeCopy", {}).get("dynamic", {}).get("body", "")
_assert("the ruling's corrected Dynamic copy is on file", bool(quoted))
_assert("the Dynamic explanation is that copy, verbatim",
        bool(quoted) and _plain(dynamic_body) == _plain(quoted.group(1)),
        "" if (quoted and _plain(dynamic_body) == _plain(quoted.group(1))) else _plain(dynamic_body)[:90])
_assert("gate 5.3 is cleared, so the copy may be shipped",
        "Gate 5.3 was cleared" in RULING or "gate 5.3 cleared" in RULING.lower())

# The superseded draft said a stake could flex both ways. It contradicts the
# model and must appear nowhere in what a GM reads.
all_mode_copy = json.dumps(APP.get("modeCopy", {}))
_assert("the superseded 'flex up or down' draft copy is gone",
        "flex up" not in _plain(all_mode_copy).lower())
# REVISED BY S8-P4C-2R2. `"never up"` was the phrasing the superseded clause
# used for the one-way ceiling; the amended ruling says "may come down, never
# above the acceptance ceiling", which states the same two facts in different
# words. The claim is the ECONOMICS — one direction of travel, and a bound — so
# both halves are asserted rather than a phrase that happens to carry them.
_dyn = _plain(dynamic_body).lower()
_assert("the Dynamic explanation states one-way movement",
        "come down" in _dyn, _plain(dynamic_body)[:90])
_assert("the Dynamic explanation states the ceiling that bounds it",
        "never above" in _dyn and "ceiling" in _dyn, _plain(dynamic_body)[:90])


# ── Pool catalog fidelity ────────────────────────────────────────────────────

print("\nThe four Pools are read from the governing catalog, not paraphrased")

CATALOG = json.loads(_read_root("spec", "pool_catalog_rev1_4.json"))
BY_NUMBER = {d["catalog_number"]: d for d in CATALOG["definitions"]}
POOLS = APP.get("pools", [])

_assert("the catalog of record is Rev 1.4, Product of Record",
        CATALOG.get("revision") == "1.4"
        and CATALOG.get("status") == "Product of Record")
_assert("exactly four Pools run in a fantasy week", len(POOLS) == 4, str(len(POOLS)))

for pool in POOLS:
    number = pool["catalogNumber"]
    definition = BY_NUMBER.get(number)
    _assert(f"Pool #{number} is a real catalog definition", definition is not None)
    if not definition:
        continue
    _assert(f"Pool #{number} uses the catalog's display name",
            pool["name"] == definition["display_name"], pool["name"])
    # REV 1.4 §3 — the question is catalog content, so the fixture may not
    # paraphrase it any more than it may paraphrase the name.
    _assert(f"Pool #{number} uses the catalog's public question",
            pool.get("question") == definition.get("public_question"),
            str(pool.get("question")))
    _assert(f"Pool #{number} uses the catalog's subject scope",
            pool["scope"] == definition["scope"], pool["scope"])
    # A QUALIFIER settles on its threshold condition; a RANK_EXTREMUM on its
    # metric expression. The rule shown is whichever the definition carries.
    governed = definition["threshold_condition"] or definition["metric_expression"]
    _assert(f"Pool #{number} states the catalog's own settling rule",
            pool["rule"] == governed, pool["rule"])
    _assert(f"Pool #{number} is eligible for a regular-season slate",
            definition["regular_season_eligible"] is True
            and definition.get("definition_runtime_eligible") is True)
    _assert(f"Pool #{number} claims rollover eligibility only where the catalog grants it",
            pool["rolloverEligible"] == definition["rollover_eligible"])

# Rollover is a MODIFIER on a subject type, never a third type.
_assert("every Pool's subject type is one of the two the catalog defines",
        {p["scope"] for p in POOLS} <= {"TEAM", "MATCHUP"},
        str(sorted({p["scope"] for p in POOLS})))
_assert("a continuation is a rollover-eligible definition that carried",
        all(p["rolloverEligible"] and p.get("carriedFromWeek")
            for p in POOLS if p.get("continuation")))
_assert("a rolling Pool takes a marked badge, never a gold card",
        ".fs-pool__pot.is-carried" in TABS_CSS and ".fs-pool.is-gold" not in TABS_CSS)
_assert("the rollover badge is a modifier on the type badge, not its own badge",
        ".fs-pool__badge.is-rollover" in TABS_CSS)

# Entry sits inside the governed bounds.
MIGRATION = _read_root("db", "migrations", "migrate_s4_common_pool_engine.py")
_assert("the weekly entry bound is the governed one",
        "ck_pool_config_weekly_entry_bounds" in MIGRATION)
_assert("the illustrative entry is inside $1–$5",
        100 <= APP.get("poolEntryCents", 0) <= 500, str(APP.get("poolEntryCents")))


# ── Narrative grounding ──────────────────────────────────────────────────────
#
# The Matchup Preview's prose is GENERATED from the matchup's own figures, and
# that is what makes the grounding rule hold: there is no source in this
# repository for injuries, weather, real-NFL news, snap counts or beat
# reporting, so no sentence may imply one. The check is run against the fully
# rendered preview for all eleven matchups, not against narrative.js, because
# what matters is what reaches a GM.

print("\nMatchup analysis stays inside the inputs the repository actually holds")

RENDERED = APP.get("rendered", "")

UNGROUNDED = [
    r"injur\w*", r"questionable", r"doubtful", r"probable", r"ruled out",
    r"weather", r"wind", r"rain\w*", r"snow", r"temperature",
    r"snap count\w*", r"target share", r"beat writer\w*", r"reporter\w*",
    r"report\w*", r"news", r"practice", r"hamstring", r"ankle", r"concussion",
    r"coach\w*", r"trade\w*", r"waiver\w*", r"suspend\w*", r"insider\w*",
]

_assert("the rendered preview is non-empty", len(RENDERED) > 5000, f"{len(RENDERED)} chars")
for pattern in UNGROUNDED:
    hits = re.findall(r"\b" + pattern + r"\b", RENDERED, re.IGNORECASE)
    _assert(f"no rendered sentence implies a source for `{pattern}`",
            not hits, ", ".join(sorted(set(hits))[:3]))

_assert("the preview says opponent starters bind from Yahoo, rather than naming them",
        "bind from Yahoo" in RENDERED)
# Naming eleven opposing rosters would fabricate ninety-nine player-to-team
# assignments no source supports. Every cell in the opponent's name column must
# therefore be a dash or empty — checked across all eleven previews.
opponent_names = re.findall(r'class="fs-spl__name is-right">([^<]*)</span>', RENDERED)
named = [n for n in opponent_names if n.strip() not in ("", "—", "-")]
_assert("the opponent's name column is rendered for every slot",
        len(opponent_names) >= 9 * 11, str(len(opponent_names)))
_assert("no opposing player is named", not named, ", ".join(sorted(set(named))[:3]))


# ── Layout contracts ─────────────────────────────────────────────────────────
#
# The browser suite measures the RESULT of these rules. They are asserted here
# at the point they are expressed, so a change that breaks the intent is caught
# where it is made rather than only where it shows.

print("\nLeague's two zones, and the layout rules that keep them honest")

zone_rule = _rule(COMPONENTS_CSS, ".fs-zones > .fs-zone")
_assert("neither zone can grow at the other's expense", "flex: 1 1 0" in zone_rule)
_assert("both zones can shrink inside the column", "min-height: 0" in zone_rule)

carousel = _rule(TABS_CSS, ".fs-carousel")
_assert("the Bets carousel is vertical", "overflow-y: auto" in carousel)
_assert("it snaps, so a card is never presented half-shown",
        "scroll-snap-type: y mandatory" in carousel)
_assert("it does not scroll sideways", "overflow-x: hidden" in carousel)

item = _rule(TABS_CSS, ".fs-carousel__item")
_assert("one complete card fills the carousel at a time", "height: 100%" in item)
_assert("every scroll settles on a card boundary",
        "scroll-snap-align: start" in item and "scroll-snap-stop: always" in item)

# UIRECON REV 1.4 PART 4 — THE 2x2 GRID IS SUPERSEDED, AND BY A PRODUCT
# RULING RATHER THAN A PREFERENCE.
#
# Rev 4.2 put four Pools in one zone as quarter-tiles. That shape carried its
# own cost in `tabs.css`'s own words — "the card compresses and clips instead" —
# and Rev 4.3 §K2 already had to invert half of it. What a quarter-tile could
# never hold is a LINE OF PROSE, which is why Rev 4.3 §8.5 moved the settle
# condition off the card: it could say WHICH Pool, never WHAT it asked.
#
# POR Rev 1.4 §3 gives every drawable definition a `public_question`, and §4 of
# the reconciliation package rules that Play's Pools become a one-card-at-a-time
# carousel so the question has a line to sit on.
#
# SO THE ASSERTION MOVES TO THE THING THAT IS NOW TRUE: Play's Pools use the
# SAME two elements as the Matchups carousel directly above them, which is the
# only way the two rails cannot drift apart. The carousel rules asserted just
# above — vertical, `y mandatory`, `overflow-x: hidden`, `height: 100%`,
# `scroll-snap-stop: always` — are therefore the Pool rail's rules too, and are
# not restated here.
_assert("Play's Pools ride the Matchups carousel itself, not a parallel rail",
        'class="fs-carousel" id="fs-play-pools"' in LEAGUE_JS
        and '"fs-carousel__item"' in LEAGUE_JS)
_assert("the Pool card takes the CARD radius the Matchup card takes, not the "
        "tile radius a grid cell took",
        "border-radius: var(--fs-radius-card)"
        in _rule(GAMEPLAY_CSS, ".fs-pool--card"))
_assert("one card fills its carousel item, so a second can never be half-shown",
        "height: 100%" in _rule(GAMEPLAY_CSS, ".fs-pool--card"))
_assert("the card carries the served question, not a scope-derived stand-in",
        'class="fs-pool__question"' in LEAGUE_JS
        and "if (pool.question) return pool.question;" in LEAGUE_JS)

print("\nAction's four rails stay single rows")

rail = _rule(COMPONENTS_CSS, ".fs-rail")
_assert("a rail is a row", "display: flex" in rail)
_assert("a rail never wraps to a second row", "flex-wrap" not in rail)
_assert("a rail scrolls horizontally", "overflow-x: auto" in rail)
_assert("a rail does not scroll vertically", "overflow-y: hidden" in rail)

rails_column = _rule(TABS_CSS, ".fs-rails")
_assert("the rails column is what scrolls vertically", "overflow-y: auto" in rails_column)
_assert("the rails column can shrink inside the panel", "min-height: 0" in rails_column)

print("\nThe Matchup Preview is pushed over the composer, not opened in place")

# The mechanism, not the outcome: the browser suite proves the stake survives a
# trip through the preview, and this proves it survives BECAUSE the preview is
# a new level rather than a replacement.
_assert("the composer pushes the preview onto the sheet stack",
        "api.push(" in COMPOSER_JS)
_assert("the composer never replaces itself with the preview",
        "openSheet(" not in COMPOSER_JS)
_assert("the shell keeps a sheet stack", "sheetStack" in SHELL_JS)
_assert("dismissing a level pops it rather than closing the sheet",
        "popSheet" in SHELL_JS and re.search(r"data-fs-close.*\n?.*popSheet", SHELL_JS))
_assert("composer state lives outside the DOM, so a re-render cannot lose it",
        "let session = null" in _read("js", "composer.js"))


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


_run_node_suite("package2_component_tests.mjs", "the component suite is green")


# ── Layout suite, in a real browser ──────────────────────────────────────────

print("\nLeague and Action layout suite (headless Chrome — measured geometry)")

_run_node_suite("e2e_package2.mjs", "the browser layout suite is green")


# ── Result ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")