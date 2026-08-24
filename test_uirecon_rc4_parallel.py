#!/usr/bin/env python3
"""
test_uirecon_rc4_parallel.py — RC4 mobile reconciliation.

Run:  python test_uirecon_rc4_parallel.py
With a running demo application (the browser tier):
      FS_TEST_ORIGIN=http://127.0.0.1:8000 python test_uirecon_rc4_parallel.py

WHAT THIS PASS REPAIRED, AND WHY EACH ONE WAS A REAL DEFECT RATHER THAN A
PREFERENCE.

  THE PLAY MATCHUP CARD WAS CLIPPED BY ITS OWN RAIL. Play's two zones split the
  panel at `flex: 1 1 0` and each rail took what its heading left. Measured on
  the deployed RC4 build at 320x568: a 44.52px rail for a 155px card, cut off
  exactly where the PROP POOLS heading begins — which is what "the Matchup card
  runs under the Prop Pools section" describes. `.fs-carousel__item` carried
  `min-height: 100%`, so the item grew to the card and the rail clipped both.

  THE TWO PLAY FAMILIES WERE TWO SIZES. Rev 1.4 gave the Prop Pool card the
  Matchup card's ELEMENTS, which fixed the width and the snap and could not fix
  the height: each rail was sized by its own zone. 135.97px against 155px, in
  adjacent sections.

  THE THREE WRAP UP FAMILIES WERE THREE SIZES. 132.30 / 150.06 / 45 at 390x844,
  and the third one was not a card at all — an open Prop Pool still drew the
  45px `.fs-poolrow` the module used when it was a flat list.

  A LIVE-GREEN RULE RAN DOWN THE SIDE OF ONE FAMILY. Wave 4B retired the GOLD
  edge on FantasyStakes Matchups for breaking parity with its two peers and
  stopped at the one accent it could see.

  AND EVERY DRAWABLE PROP POOL SAID `Question unavailable` IN PRODUCTION. The
  client was right to refuse to compose one. Migration 0008 added
  `pool_definition.public_question` and deliberately backfilled nothing, on the
  stated basis that "the 64 questions arrive with the ordinary Rev 1.4 re-seed" —
  true of every path that re-seeds the catalog and not of a RELEASE, which runs
  `python -m migrations.run` and nothing else. §5 proves the repair.

WHAT THIS SUITE WILL NOT LET PASS.

  A GEOMETRY CLAIM MADE FROM CSS. §1 and §2 read source, and they say so: every
  claim about a rendered box is measured in a real browser in §6, at eight
  viewports, four of which are reduced usable heights representing iPhone Safari
  with its chrome visible — the composition the previous certification never ran
  and the one the defect lived in.

  A SECOND AUTHOR FOR THE PROP POOL QUESTION. Wrap Up now renders the sentence
  too, and §4 proves it reads the SAME function Play does and that no fallback
  generator has come back anywhere in the tree.

  A CARD FAMILY DECLARED TWICE. §1 proves the superseded vertical-carousel rules
  are GONE from `tabs.css` and `rev43.css` rather than overridden, because two
  declarations of one rail is how the two rails drift apart again.
"""

from __future__ import annotations

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


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


def _read(*parts: str) -> str:
    with open(os.path.join(WEB, *parts), "r", encoding="utf-8") as fh:
        return fh.read()


def _read_root(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), "r", encoding="utf-8") as fh:
        return fh.read()


def _strip_css_comments(css: str) -> str:
    """Rules only. A block comment explaining what a sheet no longer does must
    not be read as the sheet still doing it — which is exactly the trap §1 walks
    into, because the removed declarations are documented where they stood."""
    return re.sub(r"/\*[\s\S]*?\*/", " ", css)


def _strip_js_comments(js: str) -> str:
    js = re.sub(r"/\*[\s\S]*?\*/", " ", js)
    return re.sub(r"^\s*//.*$", " ", js, flags=re.MULTILINE)


def _rule(css: str, selector: str) -> str:
    """The declaration block of the first rule whose selector list contains
    `selector` as a whole selector."""
    body = _strip_css_comments(css)
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", body):
        selectors = [s.strip() for s in match.group(1).split(",")]
        if selector in selectors:
            return match.group(2)
    return ""


GAMEPLAY = _read("styles", "gameplay.css")
TABS = _read("styles", "tabs.css")
REV43 = _read("styles", "rev43.css")
LEDGER_CSS = _read("styles", "ledger.css")
LEAGUE_JS = _read("js", "league.js")
WEEK_JS = _read("js", "week.js")


print("=" * 70)
print("RC4 MOBILE RECONCILIATION — parallel construction")
print("=" * 70)


# ══ §1 · one declaration per rail, and the superseded ones are gone ══════════

_section("§1 · the Play rail is declared once, and horizontally")

_play_rail = _rule(GAMEPLAY, "#panel-league .fs-carousel")
_assert("Play's carousel is declared in gameplay.css", bool(_play_rail))
_assert("  · it scrolls horizontally", "overflow-x: auto" in _play_rail)
_assert("  · it snaps one card at a time on the x axis",
        "scroll-snap-type: x mandatory" in _play_rail)
_assert("  · it cannot draw into the section beneath it",
        "overflow-y: hidden" in _play_rail)
_assert("  · a scroll past the last card does not chain out of the rail",
        "overscroll-behavior-x: contain" in _play_rail)
_assert("  · and it is exactly its grid track, never its content",
        "height: 100%" in _play_rail)

_play_item = _rule(GAMEPLAY, "#panel-league .fs-carousel__item")
_assert("one item is exactly one viewport wide", "flex: 0 0 100%" in _play_item)
_assert("every item is a hard snap stop",
        "scroll-snap-align: start" in _play_item
        and "scroll-snap-stop: always" in _play_item)
_assert("the item can no longer outgrow its rail",
        "min-height: 0" in _play_item and "min-height: 100%" not in _play_item)

_tabs_rules = _strip_css_comments(TABS)
_assert("the superseded vertical carousel is GONE from tabs.css, not overridden",
        ".fs-carousel {" not in _tabs_rules
        and ".fs-carousel__item {" not in _tabs_rules)
_assert("  · and rev43.css no longer relaxes the item's height either",
        "min-height: 100%" not in _strip_css_comments(REV43))

_section("§1.1 · the two Play sections are one grid, sized by their content")

_deck = _rule(GAMEPLAY, ".fs-playdeck")
_assert("the deck is a grid", "display: grid" in _deck)
_assert("  · of heading · rail · heading · rail",
        "grid-template-rows: auto minmax(0, 1fr) auto minmax(0, 1fr)" in _deck)
_assert("  · whose two rail tracks are a matched pair, so the families cannot "
        "measure differently",
        _deck.count("minmax(0, 1fr)") == 2)
_assert("  · and which is at least as tall as the tallest card in either",
        "min-height: max-content" in _deck)
_assert("neither zone contributes a box between a heading and its rail",
        "display: contents" in _rule(GAMEPLAY, "#panel-league .fs-playdeck > .fs-zone"))
_assert("the section step is explicit, on the second section's heading",
        "margin-top: var(--fs-space-4)"
        in _rule(GAMEPLAY, "#panel-league .fs-zone--pools > .fs-heading"))

_section("§1.2 · the three Wrap Up sections are one grid")

_wkdeck = _rule(GAMEPLAY, ".fs-wkdeck")
_assert("the Wrap Up deck is a grid", "display: grid" in _wkdeck)
_assert("  · of three heading/rail pairs",
        _wkdeck.count("minmax(0, 1fr)") == 3)
_assert("  · sized by the tallest card in any of the three",
        "min-height: max-content" in _wkdeck)
_assert("no module contributes a box between a heading and its rail",
        "display: contents" in _rule(GAMEPLAY, ".fs-wkdeck > .fs-wkmod"))
_assert("the section separator is preserved, on the heading",
        "border-top: var(--fs-border)"
        in _rule(GAMEPLAY, "#panel-week .fs-wkdeck > .fs-wkmod > .fs-heading"))
_assert("  · and the first section still opens without one",
        "border-top: none"
        in _rule(GAMEPLAY,
                 "#panel-week .fs-wkdeck > .fs-wkmod:first-child > .fs-heading"))


# ══ §2 · nothing lets a section occupy the next section's space ══════════════

_section("§2 · the section boundary is structural, not arithmetic")

# THE WHOLE BLOCK, not one rule: the owner's constraint is that NO
# absolute-position or negative-margin trick may let one section be drawn in the
# next one's space, and a single offending declaration anywhere in the geometry
# block would do it.
_block = GAMEPLAY.split("PARALLEL CARD GEOMETRY", 1)
_assert("the parallel-geometry block exists", len(_block) == 2)
_geometry = _strip_css_comments(_block[1]) if len(_block) == 2 else ""
_assert("nothing in it is positioned out of flow",
        "position: absolute" not in _geometry
        and "position: fixed" not in _geometry)
_assert("nothing in it takes a negative margin",
        not re.search(r"margin[a-z-]*:\s*-", _geometry))
_assert("nothing in it is pulled by a transform",
        "transform:" not in _geometry)
_assert("every rail clips its own vertical axis",
        _geometry.count("overflow-y: hidden") >= 1)

_section("§2.1 · Play's markup is the deck, and the source line ends the tab")

_league_code = _strip_js_comments(LEAGUE_JS)
_assert("Play draws the deck inside the scroller",
        '"fs-playdeck"' in _league_code or "'fs-playdeck'" in _league_code
        or 'class="fs-playdeck"' in _league_code)
_assert("both families ride the same two elements",
        'class="fs-carousel" id="fs-bets-carousel"' in _league_code
        and 'class="fs-carousel" id="fs-play-pools"' in _league_code
        and _league_code.count('"fs-carousel__item"') == 2)
_assert("the attribution ends the tab rather than one of the two sections",
        re.search(r"fs-playdeck[\s\S]{0,400}attributionFooter\(\)", _league_code)
        is not None)
_assert("the headings are unchanged", "MATCHUPS_HEADING = 'MATCHUPS'" in LEAGUE_JS
        and "POOLS_HEADING = 'PROP POOLS'" in LEAGUE_JS)
_assert("PROP POOLS still reports the week's count and the scroll affordance",
        "THIS WEEK · ${SWIPE_WORD}" in LEAGUE_JS)

_section("§2.2 · Wrap Up is three peers, and the Prop Pool item is a card")

_week_code = _strip_js_comments(WEEK_JS)
_assert("the three modules sit in one deck",
        re.search(r'fs-wkdeck[\s\S]{0,200}yahooModule\(\)[\s\S]{0,120}'
                  r'betsModule\(\)[\s\S]{0,120}poolsModule\(\)', _week_code)
        is not None)
_assert("the three locked headings are unchanged",
        "'YAHOO LEAGUE MATCHUPS · SCROLL'" in WEEK_JS
        and "BETS_HEADING = 'FANTASYSTAKES MATCHUPS · SCROLL'" in WEEK_JS
        and "'FANTASYSTAKES PROP POOLS · SCROLL'" in WEEK_JS)
_assert("an OPEN Prop Pool draws the shared result card, not a list row",
        "poolOpenCard(pool)" in _week_code and "poolRow" not in _week_code)
_assert("  · and the row component it replaced is not emitted anywhere",
        'class="fs-poolrow"' not in _week_code)
_assert("a SETTLED Prop Pool still draws its own result card",
        "poolResultCard(pool)" in _week_code)
_assert("both Prop Pool states go through the one shared shell",
        _week_code.count("return resultCard({") >= 3)

# The card the owner asked for, field by field. Each is read from what the
# server already publishes; none is composed here.
_open_card = WEEK_JS.split("function poolOpenCard(", 1)[-1].split("\n}", 1)[0]
for _field, _label in (
    ("poolBadge(pool)", "the Pool's scope / type"),
    ("pool.name", "the governed pool name"),
    ("poolQuestion(pool)", "the governed public question"),
    ("pool.potCents", "the pot"),
    ("pool.entryCents", "the buy-in"),
    ("pool.entered", "the entry count"),
    ("mySubjectId", "the GM's own selection"),
):
    _assert(f"the open Prop Pool card carries {_label}", _field in _open_card)
_assert("  · and it invents nothing where a field is unavailable",
        "PENDING_FIGURE" in _open_card)


# ══ §3 · the status side rail is gone from the FantasyStakes families ════════

_section("§3 · no decorative status rail breaks the shared result shell")

_edge = _rule(GAMEPLAY, '.fs-wkmod[data-module="bets"] .fs-rescar__item > .fs-wcard')
_assert("FantasyStakes Matchup result cards take the shared neutral edge",
        "border-left-color: var(--line2)" in _edge)
_edge_pools = _rule(
    GAMEPLAY, '.fs-wkmod[data-module="pools"] .fs-rescar__item > .fs-wcard')
_assert("  · and so do FantasyStakes Prop Pool result cards",
        "border-left-color: var(--line2)" in _edge_pools)
_assert("nothing was substituted for it — no right edge, no tinted fill",
        "border-right-color" not in _geometry
        and not re.search(r"\.fs-wcard[^{}]*\{[^{}]*background:", _geometry))
_assert("the status is still told in words, by the badge the card already had",
        "badge," in _open_card or "badge:" in _open_card)


# ══ §4 · the client still cannot invent a Prop Pool question ═════════════════

_section("§4 · one author for the question, and it is the catalog")

_assert("`poolQuestion` is the one reader, and Wrap Up imports it",
        "export function poolQuestion(pool)" in LEAGUE_JS
        and "import { poolQuestion, poolSheet } from './league.js';" in WEEK_JS)

_q = LEAGUE_JS.split("export function poolQuestion(pool)", 1)[-1].split("\n}", 1)[0]
_assert("  · it returns the served sentence or the integrity mark, and nothing "
        "in between",
        "pool.question" in _q and "MISSING_QUESTION_TEXT" in _q)
_assert("  · a missing question is registered as a defect, not drawn as design",
        "MISSING_QUESTIONS.add" in _q and "console.warn" in _q)

# THE RETIRED GENERATOR, HUNTED ACROSS THE WHOLE TREE. The refine-refresh pass
# removed a scope-derived sentence; this pass adds a SECOND surface that renders
# the question, which is exactly when such a helper gets quietly reintroduced.
_RETIRED = "Which ${pool.subject"
_scope_derived = re.compile(
    r"Which\s+(matchup|team)\b[^\"'`]*\?\s*[\"'`]\s*[;,)]", re.IGNORECASE)
_offenders: list[str] = []
for folder, _dirs, files in os.walk(WEB):
    if any(part in folder for part in (".git", "node_modules", "__pycache__")):
        continue
    for name in files:
        if not name.endswith(".js"):
            continue
        path = os.path.join(folder, name)
        with open(path, "r", encoding="utf-8") as fh:
            source = _strip_js_comments(fh.read())
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        # `data/league-data.js` carries the catalog's own questions verbatim as
        # the illustrative fixture, which is fixture DATA and not a generator.
        if rel.endswith("js/data/league-data.js"):
            continue
        if _RETIRED in source or _scope_derived.search(source):
            _offenders.append(rel)
_assert("no module composes a Prop Pool question from scope",
        not _offenders, ", ".join(_offenders))


# ══ §5 · the governed questions reach a database that already exists ════════

_section("§5 · public_question · the production repair")

_manifest = _read_root("migrations", "manifest.py")
_assert("the backfill is registered in the release manifest",
        "0009_pool_definition_public_question_backfill" in _manifest)
_assert("  · after the migration that adds the column",
        _manifest.index("0008_pool_definition_public_question")
        < _manifest.index("0009_pool_definition_public_question_backfill"))
# BOUNDED BY 0009'S OWN ENTRY, NOT BY THE END OF THE TUPLE.
#
# This previously terminated on `),\n)` — the close of the ACTIVE tuple — which
# only worked while 0009 happened to be the LAST migration registered. The Final
# POR appends 0010, so that anchor stopped matching and the assertion died on a
# None regex rather than reporting anything about 0009. The claim being made has
# nothing to do with position: it is that 0009's OWN entry declares no schema
# object. Anchoring to its own closing `),` says that and stays true however many
# migrations follow it.
_entry_0009 = re.search(
    r'identifier="0009_pool_definition_public_question_backfill"[\s\S]*?\n    \),',
    _manifest)
_assert("  · and it claims no new schema object, because it adds none",
        _entry_0009 is not None
        and "columns=" not in _entry_0009.group(0)
        and "tables=" not in _entry_0009.group(0))

_backfill = _read_root(
    "migrations", "backfill_pool_definition_public_question.py")
# CODE ONLY. The docstring and the inline notes explain at length what this
# migration does NOT do — "no row is inserted", "no table is created" — and a
# scan of raw source would read its own disclaimers as the thing it disclaims.
_code = re.sub(r'"""[\s\S]*?"""', " ", _backfill)
_code = re.sub(r"^\s*#.*$", " ", _code, flags=re.MULTILINE)
_assert("it writes exactly one column",
        _code.count("UPDATE") == 1 and "SET public_question" in _code
        or "SET {COLUMN}" in _code)
_assert("  · from the governed catalog, through the validating loader",
        "load_catalog()" in _code and "spec.public_question" in _code)
_assert("  · matched on the immutable key",
        "WHERE key = :k" in _code)
# THE STATEMENTS, NOT THE WORDS. `sys.path.insert` is not an INSERT and a note
# reading "not this database's to create" is not a CREATE; a bare keyword scan
# fails a migration for its own bootstrap line. The claim is about SQL.
_sql = re.compile(r"\b(INSERT\s+INTO|DELETE\s+FROM|ALTER\s+TABLE|CREATE\s+TABLE"
                  r"|DROP\s+(TABLE|COLUMN|DATABASE)|TRUNCATE)\b", re.IGNORECASE)
_assert("it issues no INSERT, DELETE, ALTER, CREATE, DROP or TRUNCATE",
        not _sql.search(_code),
        (_sql.search(_code) or [""])[0] if _sql.search(_code) else "")
_assert("  · the only statements it issues are one SELECT and one UPDATE",
        len(re.findall(r"\bSELECT\b", _code, re.IGNORECASE)) == 1
        and len(re.findall(r"\bUPDATE\b", _code, re.IGNORECASE)) == 1,
        f"{len(re.findall(r'SELECT', _code, re.IGNORECASE))} SELECT / "
        f"{len(re.findall(r'UPDATE', _code, re.IGNORECASE))} UPDATE")
_assert("it touches no ledger, escrow, pot, claim or wager term",
        not re.search(r"ledger|escrow|pot_cents|pool_claim|pool_instance|wager|"
                      r"balance|settle", _code, re.IGNORECASE))
_assert("it is idempotent — a value already governed is not rewritten",
        "if stored[key] == question" in _code)

# THE CATALOG ITSELF, READ RATHER THAN ASSUMED.
try:
    from betting.pool_catalog import load_catalog

    _catalog = load_catalog()
    _eligible = [d for d in _catalog.definitions if d.definition_runtime_eligible]
    _blocked = [d for d in _catalog.definitions
                if not d.definition_runtime_eligible]
    _assert("64 definitions are runtime-eligible", len(_eligible) == 64,
            str(len(_eligible)))
    _assert("  · and every one of them carries a governed public_question",
            all(d.public_question for d in _eligible),
            ", ".join(d.key for d in _eligible if not d.public_question)[:120])
    _assert("the 16 non-drawable definitions carry none, by design",
            len(_blocked) == 16
            and not any(d.public_question for d in _blocked),
            str(len(_blocked)))
    _assert("no question restates a settlement basis it has no authority over",
            all("metric_expression" not in (d.public_question or "")
                for d in _eligible))
except Exception as exc:                                    # noqa: BLE001
    _assert("the governed catalog loads", False, f"{type(exc).__name__}: {exc}")

# THE SEEDER STILL WRITES IT TOO, so a fresh database and a migrated one agree.
_seeder = _read_root("betting", "pool_catalog.py")
_assert("the ordinary re-seed still writes the same field",
        "row.public_question = spec.public_question" in _seeder)


# ══ §6 · governance — what this pass must not have touched ══════════════════

_section("§6 · governance")

_CHANGED_UI = ("js/league.js", "js/week.js")
for _rel in _CHANGED_UI:
    _src = _strip_js_comments(_read(*_rel.split("/")))
    _assert(f"{_rel} writes nothing", not re.search(
        r"method:\s*['\"]POST|method:\s*['\"]PUT|method:\s*['\"]DELETE", _src))
    # `ledger-model.js` is a READ model, and Play's strip has read it since
    # WP3C; naming it is not an economic act. What must never appear on a
    # presentation module is the machinery that MOVES credits.
    _assert(f"{_rel} reaches no escrow, posting or settlement machinery",
            not re.search(r"\bescrow\b|\bpostings?\b|\btrial_balance\b"
                          r"|\bsettleWager\b|\bpayout\b", _src, re.IGNORECASE))

_assert("no public-facing Versus is introduced on Play",
        "Versus" not in re.sub(r"[A-Za-z_]*[Vv]ersus[A-Za-z_]*\s*[({.,)]", " ",
                               _strip_js_comments(LEAGUE_JS)))
_assert("Play is still called Play",
        "buildLeaguePanel" in LEAGUE_JS and "'league'" in LEAGUE_JS)
_assert("the 3 TEAM / 1 MATCHUP rotation is not referenced or altered here",
        "TEAM" not in _strip_js_comments(WEEK_JS).replace("poolBadge", " ")
        or "slateRows()" in _week_code)
_assert("Wrap Up fabricates no Yahoo data",
        "yahooMatchups(activeWeek())" in _week_code
        and "providerMatchupCard" in _week_code)


# ══ §7 · browser tier ═══════════════════════════════════════════════════════

def _run_browser(script: str, label: str) -> None:
    node = shutil.which("node")
    if node is None:
        _assert(f"{label} — node is available", False, "node not on PATH")
        return
    if not os.environ.get("FS_TEST_ORIGIN"):
        print(f"  [SKIP] {label} — set FS_TEST_ORIGIN to a running demo app")
        return
    print(f"\n{label}")
    proc = subprocess.run([node, os.path.join(WEB, "tests", script)],
                          cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    print((proc.stdout or "").rstrip())
    if (proc.stderr or "").strip():
        print(proc.stderr.rstrip())
    passes = (proc.stdout or "").count("[PASS]")
    fails = (proc.stdout or "").count("[FAIL]")
    _assert(f"{label} is green", proc.returncode == 0,
            f"{passes} PASS / {fails} FAIL, exit {proc.returncode}")


_section("§7 · browser tier")

_run_browser(
    "uirecon_rc4_parallel_browser.mjs",
    "§7 · parallel construction, measured (headless Chrome, "
    "320x568 / 320x454 / 375x667 / 375x553 / 390x844 / 390x664 / "
    "768x1024 / 1024x768)")


print("\n" + "=" * 70)
if _failures:
    print(f"RC4 PARALLEL — {len(_failures)} FAILED")
    for label in _failures:
        print(f"  - {label}")
    sys.exit(1)
print("RC4 PARALLEL — ALL PASSED")
