#!/usr/bin/env python3
"""
test_uirecon_refresh_ux.py — the two-level odds refresh, and governed questions.

Run:  python test_uirecon_refresh_ux.py
With a running demo application (the browser tier):
      FS_TEST_ORIGIN=http://127.0.0.1:8000 python test_uirecon_refresh_ux.py

WHAT THIS PASS CHANGED, AND WHAT IT DELIBERATELY DID NOT.

  THE REFRESH WAS RIGHT UNDERNEATH AND WRONG ON TOP. Rev 1.4 built the Dynamic
  informational refresh properly — a server route, a shared persisted result,
  no credit movement, no escrow movement, no mutation of an agreed term — and
  then put it behind a full-width `↻ REFRESH ODDS` button on ONE card, reachable
  only after a wager already existed. A button that wide is the size this
  product uses for decisions, and the screen where prices are actually shopped
  had no way to re-read them at all.

  So the machinery is untouched and the surface is replaced: one small glyph,
  four states, at two levels — a heading control that re-reads Play's whole
  board and a per-card control that re-reads one pairing.

  THE PLAY CONTROLS ARE NOT THE WAGER ROUTE. A Play card is an OPPONENT, not a
  wager; there is no stake, no escrow and no agreed term on that surface because
  nothing has been proposed. Both Play controls call the SAME GET the cards were
  drawn from — `/league/{id}/versus/board`, with the route's own
  `opponent_team_id` filter for one card — which writes nothing. §3 below proves
  that by reading the source rather than by asserting it.

  AND THE CLIENT STOPPED WRITING PROP POOL QUESTIONS. Rev 1.4 made
  `public_question` governed catalog data and left the old scope-derived
  sentence in place as a fallback. A client-side generator that produces
  plausible product copy is indistinguishable from the governed field it stands
  in for — so the one case it exists for, broken catalog data, is exactly the
  case in which it hides the breakage. §6 proves it is gone.

WHAT THIS SUITE WILL NOT LET PASS.

  A REFRESH THAT COULD MOVE MONEY. §3 reads every module this pass touched for
  a write verb, a ledger term or an economic identifier.

  A LOCKED WAGER WHOSE TERMS A SURFACE COULD REWRITE. §5 proves the Locked
  block draws `LOCKED ODDS` from the card contract and `CURRENT ODDS` from the
  market board, that no control on it targets the wager, and that an absent
  board line reads `Unavailable` rather than a fabricated figure.

  A QUESTION THIS REPOSITORY INVENTED. §6 greps the whole tree for the retired
  sentence and asserts the generator is not merely unused but absent.
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


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


def _read(*parts: str) -> str:
    with open(os.path.join(WEB, *parts), "r", encoding="utf-8") as fh:
        return fh.read()


def _read_root(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), "r", encoding="utf-8") as fh:
        return fh.read()


def _strip_comments(js: str) -> str:
    """Code only. A rule about what a module DOES must not be satisfied — or
    broken — by a sentence in a comment explaining what it does not do."""
    js = re.sub(r"/\*[\s\S]*?\*/", " ", js)
    return re.sub(r"^\s*//.*$", " ", js, flags=re.MULTILINE)


def _identifiers_only(js: str) -> str:
    """Comments AND string literals stripped.

    THE DIFFERENCE MATTERS FOR THE ECONOMIC SWEEP BELOW. `explainBoardRefusal`
    contains the sentence "The postseason field is not settled yet" — product
    copy about a schedule, in which the word `settled` is English rather than an
    accounting term. Scanning raw source would read that as a settlement
    identifier and fail a module that touches no such thing.
    """
    js = _strip_comments(js)
    js = re.sub(r"`(?:[^`\\]|\\.)*`", " ", js)
    js = re.sub(r"'(?:[^'\\\n]|\\.)*'", " ", js)
    return re.sub(r'"(?:[^"\\\n]|\\.)*"', " ", js)


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*[\s\S]*?\*/", " ", css)


print("=" * 70)
print("UIRECON — refresh UX and governed Prop Pool questions")
print("=" * 70)

ODDS_REFRESH = _read("js", "odds-refresh.js")
PLAY_REFRESH = _read("js", "play-odds-refresh.js")
REFRESH_ODDS = _read("js", "refresh-odds.js")
MOUNT = _read("js", "refresh-odds-mount.js")
LEAGUE = _read("js", "league.js")
MARKET_MODEL = _read("js", "market-model.js")
MARKET_CMD = _read("js", "versus-market-command.js")
COMPONENTS_CSS = _read("styles", "components.css")
WAGER_CSS = _read("styles", "wager.css")
API = _read_root("api", "main.py")


# ══ §1 · the control itself ═════════════════════════════════════════════════

_section("§1 · one small control, four states, an accessible name")

_assert("the idle glyph is ↻", "export const REFRESH_GLYPH = '↻';" in ODDS_REFRESH)
_assert("the brief acknowledgement is a check", "export const DONE_GLYPH = '✓';"
        in ODDS_REFRESH)
_assert("all four states are named",
        all(f"STATE_{s} = '{s.lower()}'" in ODDS_REFRESH
            for s in ("IDLE", "WORKING", "DONE", "ERROR")))
_assert("the control carries its scope and its target, so a binder needs no "
        "closure", "data-refresh-scope" in ODDS_REFRESH
        and "data-refresh-target" in ODDS_REFRESH)
_assert("every control is a real button, typed so it can never submit a form",
        'type="button"' in ODDS_REFRESH)
_assert("the subject is in the ACCESSIBLE NAME, which a keyboard and a screen "
        "reader both reach — not in a tooltip, which neither does",
        'aria-label="${escapeHtml(label)}"' in ODDS_REFRESH
        and "title=" not in _strip_comments(ODDS_REFRESH))
_assert("a control with no label draws nothing rather than an unnamed button",
        "if (!scope || !label) return '';" in ODDS_REFRESH)
_assert("working sets aria-busy and disables the control",
        "setAttribute('aria-busy', 'true')" in ODDS_REFRESH
        and "button.disabled = true;" in ODDS_REFRESH)
_assert("done and error DO NOT disable it — a GM watching a line move may ask "
        "again immediately, and a refusal may have since resolved",
        "button.disabled = false;" in ODDS_REFRESH)
_assert("done reverts itself, so no success state outlives being news",
        "STATE_DONE) {" in ODDS_REFRESH and "setRefreshState(button, STATE_IDLE)"
        in ODDS_REFRESH)
_assert("the status line is a polite live region",
        'role="status" aria-live="polite"' in ODDS_REFRESH)
_assert("a second press while working is refused rather than queued",
        "if (button.dataset.refreshState === STATE_WORKING) return false;"
        in ODDS_REFRESH)


# ══ §2 · the timestamp is the server's ══════════════════════════════════════

_section("§2 · the stamp reports a server fact, never a client clock")

_assert("the board response carries `computed_at`",
        "computed_at:    datetime" in API)
_assert("it is stamped AFTER the pricing loop, so it reports completion",
        "computed_at=datetime.now(timezone.utc)" in API)
_assert("the model carries it through verbatim",
        "export function marketComputedAt()" in MARKET_MODEL
        and "return SERVED.computed_at || null;" in MARKET_MODEL)
_assert("the stamp formats a SERVED value and reads no clock of its own",
        "Date.now()" not in _strip_comments(ODDS_REFRESH)
        and "new Date()" not in _strip_comments(ODDS_REFRESH))
_assert("no timestamp means NO SENTENCE, rather than an invented one",
        "return time === null ? '' : " in ODDS_REFRESH)
_assert("a naive server timestamp is read as UTC, not as the viewer's own hour",
        "hasZone ? text : `${text}Z`" in ODDS_REFRESH)
_assert("the hour is formatted here rather than by toLocaleTimeString, whose "
        "output varies by locale data",
        "toLocaleTimeString" not in _strip_comments(ODDS_REFRESH))

_node = shutil.which("node")
if _node:
    probe = subprocess.run(
        [_node, "--input-type=module", "-e", """
        import { oddsStamp, clockTime } from './web/js/odds-refresh.js';
        const out = {
          utc: clockTime('2026-08-21T18:47:03Z'),
          none: clockTime(null),
          rubbish: clockTime('not a time'),
          stampNone: oddsStamp(null),
          stamp: oddsStamp('2026-08-21T18:47:03Z'),
        };
        console.log(JSON.stringify(out));
        """], cwd=ROOT, capture_output=True, text=True)
    try:
        got = json.loads((probe.stdout or "").strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        got = {}
    _assert("a valid timestamp renders as `H:MM AM/PM`",
            bool(re.fullmatch(r"\d{1,2}:\d{2} (AM|PM)", got.get("utc") or "")),
            str(got.get("utc")))
    _assert("an absent timestamp yields no stamp at all",
            got.get("none") is None and got.get("stampNone") == "",
            f"{got.get('none')} / {got.get('stampNone')!r}")
    _assert("an unparseable timestamp yields no stamp rather than `NaN:NaN`",
            got.get("rubbish") is None, str(got.get("rubbish")))
    _assert("the stamp reads `Odds updated H:MM AM/PM`",
            bool(re.fullmatch(r"Odds updated \d{1,2}:\d{2} (AM|PM)",
                              got.get("stamp") or "")),
            str(got.get("stamp")))
else:
    print("  [SKIP] clock probe — node is not on PATH")


# ══ §3 · Play's two controls re-read; they never price and never write ══════

_section("§3 · the Play controls are a GET, and cannot move money")

_assert("the heading control re-reads the whole board",
        "export async function refreshBoard(panel)" in PLAY_REFRESH)
_assert("the per-card control re-reads ONE pairing",
        "export async function refreshPairing(panel, teamId)" in PLAY_REFRESH)
_assert("both call the board command and nothing else",
        "requestMarketBoard(CONTEXT.leagueId, CONTEXT.week)" in PLAY_REFRESH
        and "requestMarketBoard(CONTEXT.leagueId, CONTEXT.week, teamId)"
        in PLAY_REFRESH)
_assert("the per-pairing read uses the route's OWN filter rather than a new "
        "endpoint", "opponent_team_id=" in MARKET_CMD)

_play_code = _identifiers_only(PLAY_REFRESH)
_WRITE_VERBS = ("method: 'POST'", "method: 'PUT'", "method: 'PATCH'",
                "method: 'DELETE'")
_assert("nothing in the Play refresh module issues a write",
        not [v for v in _WRITE_VERBS if v in _play_code],
        str([v for v in _WRITE_VERBS if v in _play_code]))
_ECONOMIC = ("stake", "escrow", "ledger", "wallet", "credit", "settle",
             "final_lock", "finalLock", "pot_cents", "potCents")
_leaked = [t for t in _ECONOMIC if t.lower() in _play_code.lower()]
_assert("the sweep is over identifiers, so it cannot be satisfied by deleting "
        "a comment", "requestMarketBoard" in _play_code)
_assert("and it names no economic quantity at all — no stake, escrow, ledger, "
        "wallet, credit, settlement, final lock or pot",
        not _leaked, str(_leaked))
_assert("the board route itself states that it writes nothing",
        "NOTHING IS WRITTEN." in API)
_assert("a one-row response is MERGED, so refreshing one card cannot blank the "
        "rest of the rail",
        "export function applyMarketRow(board)" in MARKET_MODEL
        and "applyMarketRow(board)" in PLAY_REFRESH)
_assert("a single row is refused as a whole board",
        "board.markets.length !== 1" in MARKET_MODEL)


# ══ §4 · the controls coexist with everything already on the card ══════════

_section("§4 · the control does not collide with the card it sits on")

_assert("the per-card control is inside the head and OUTSIDE the challenge "
        "button — a button inside a button is invalid and unreachable by "
        "keyboard",
        "+ '</button>'\n    // THE PER-CARD REFRESH, in the head's trailing slot."
        in LEAGUE)
_assert("Play's handler claims the click, so a refresh is never also a "
        "challenge",
        "event.preventDefault();" in PLAY_REFRESH
        and "event.stopPropagation();" in PLAY_REFRESH)
_assert("the Status control claims its click too",
        "event.stopPropagation();" in REFRESH_ODDS)
_assert("Play binds by DELEGATION from the panel, so controls survive the "
        "redraw that replaces every card element",
        "panel.addEventListener('click'" in PLAY_REFRESH
        and "closest('[data-odds-refresh]')" in PLAY_REFRESH)
_assert("binding is idempotent, so re-entry on every panel build is free",
        "dataset.oddsRefreshBound" in PLAY_REFRESH)
_assert("cards are patched in place rather than re-rendered, so the carousel "
        "does not scroll back to the first opponent under a thumb",
        "repaintMarketCells" in PLAY_REFRESH
        and "buildLeaguePanel" not in _strip_comments(PLAY_REFRESH))
_assert("the control cannot grow the card: it is exactly the governed touch "
        "size, and the row it sits in was already that tall",
        "width: var(--fs-c-touch);" in COMPONENTS_CSS
        and "height: var(--fs-c-touch);" in COMPONENTS_CSS
        and ".fs-oddsref::after" not in COMPONENTS_CSS)
_assert("  · and the target is MEASURED in the browser rather than asserted "
        "from the stylesheet",
        "walk(-1, 0) + walk(1, 0) + 1"
        in _read("tests", "uirecon_refresh_ux_browser.mjs"))
_assert("and it declares no min-height, which would have grown the row",
        "min-height" not in _strip_css_comments(COMPONENTS_CSS)
        .split(".fs-oddsref {")[1].split("}")[0])
_assert("reduced motion still gets a working STATE, just not an animation",
        "prefers-reduced-motion" in COMPONENTS_CSS
        and "animation: none;" in COMPONENTS_CSS)
_assert("the heading control sits with the word it refreshes, not with the "
        "count", ".fs-heading__lead" in COMPONENTS_CSS
        and "fs-heading__lead" in _read("js", "components.js"))
_assert("  · and the shared heading is what places it, so every section that "
        "gains an action gets the same arrangement",
        "export function sectionHeading(text, helper = '', action = '')"
        in _read("js", "components.js"))


# ══ §5 · semantics by wager state ══════════════════════════════════════════

_section("§5 · uncommitted, Dynamic and Locked each mean something different")

_assert("an UNCOMMITTED Play card refreshes the market board — there is no "
        "wager on that surface to refresh",
        "requestMarketBoard" in PLAY_REFRESH
        and "odds/refresh" not in PLAY_REFRESH)
_assert("an existing DYNAMIC wager still goes through the governed refresh "
        "route", "odds/refresh" in _read("js", "refresh-odds-command.js"))
_assert("the Dynamic control is still gated on the server's own window",
        "export function canRefreshOdds(card)" in REFRESH_ODDS
        and "card.mode !== 'dynamic'" in REFRESH_ODDS)
_assert("the Dynamic confirmation still says the wager did not move",
        "'Wager unchanged'" in REFRESH_ODDS)

_assert("a LOCKED card gets a comparison, not a wager refresh",
        "export function canCompareLockedOdds(card)" in REFRESH_ODDS
        and "card.mode !== 'locked'" in REFRESH_ODDS)
_assert("`LOCKED ODDS` is drawn from the card's own odds of record",
        "formatOdds(card.yourMoneyline)" in REFRESH_ODDS)
_assert("  · which is carried verbatim from the contract, never re-derived",
        "yourMoneyline: Number.isInteger(row.your_moneyline)"
        in _read("js", "action-model.js"))
_assert("`CURRENT ODDS` is the market board's line for the same pairing",
        "acting_moneyline" in MOUNT and "marketFor(card.opponentTeamId)" in MOUNT)
_assert("a board priced for ANOTHER WEEK is not quoted as current",
        "marketWeek() !== card.weekNumber" in MOUNT)
_assert("an absent current line reads `Unavailable`, never a fabricated figure",
        "CURRENT_ODDS_UNAVAILABLE = 'Unavailable'" in REFRESH_ODDS)
# THE LOCKED BLOCK CARRIES NO CONTROL AT ALL, for two reasons that agree.
#
# SPACE, MEASURED: a Status lifecycle card is a fixed-height carousel item and
# Rev 1.4 Part 11 tuned all four rails to one mobile viewport. A glyph in this
# block took it to 36px, and the card then needed 142px inside 136 and clipped
# its own foot at every certified viewport — caught by UIRECON Wave 1.
#
# AND MEANING: Rev 1.4's own note argued that a refresh affordance on a Locked
# card would sit beside Refresh & Relock, putting two very different verbs
# together — one that changes nothing, and one that replaces the wager.
_assert("the Locked comparison offers no control of its own",
        "fs-oddsref--inline" not in REFRESH_ODDS)
_assert("  · so nothing on a Locked card can be pressed to reach the wager",
        "requestMarketBoard" not in MOUNT)
_assert("the CURRENT figure is still addressable, so a later board read can "
        "repaint it without redrawing the card",
        "data-current-odds" in REFRESH_ODDS)
_assert("  · while LOCKED ODDS is not addressable at all",
        "data-locked-odds-value" not in REFRESH_ODDS)
_assert("the figure still moves, because it is the same board Play refreshes",
        "marketFor(card.opponentTeamId)" in MOUNT)
_assert("Final Lock is not reachable from any refresh surface",
        not any("final_lock" in _strip_comments(src).lower()
                for src in (PLAY_REFRESH, ODDS_REFRESH, REFRESH_ODDS, MOUNT)))


# ══ §6 · the client no longer writes Prop Pool questions ═══════════════════

_section("§6 · public_question is catalog data, and only catalog data")

# ASSEMBLED FROM PARTS so this suite — and the component suite beside it —
# do not contain the very string they are asserting the absence of. Both files
# quote it deliberately, and a literal here would make the sweep find itself.
_RETIRED = " ".join(["do you think", "takes this Prop Pool"])
_SEARCH_EXEMPT = {"test_uirecon_refresh_ux.py",
                  os.path.join("web", "tests",
                               "uirecon_refresh_ux_component.mjs")}
_hits = []
for folder, _dirs, files in os.walk(ROOT):
    if any(part in folder for part in (".git", "node_modules", "__pycache__")):
        continue
    for name in files:
        if not name.endswith((".js", ".mjs", ".py")):
            continue
        path = os.path.join(folder, name)
        try:
            relative = os.path.relpath(path, ROOT)
            if relative in _SEARCH_EXEMPT:
                continue
            with open(path, "r", encoding="utf-8") as fh:
                if _RETIRED in fh.read():
                    _hits.append(relative)
        except OSError:
            continue
_assert("the retired scope-derived sentence appears NOWHERE in the tree — not "
        "unused, absent", not _hits, str(_hits))

_league_code = _strip_comments(LEAGUE)
_assert("`poolQuestion` returns the served question or the neutral state, and "
        "composes nothing",
        "if (pool && pool.question) return pool.question;" in _league_code
        and "MISSING_QUESTION_TEXT" in _league_code)
_assert("it branches on no scope, mechanic or display name",
        "pool.scope ===" not in _league_code.split("function poolQuestion")[1]
        .split("\n}")[0])
_assert("the neutral state describes the ABSENCE, not the contest",
        "export const MISSING_QUESTION_TEXT = 'Question unavailable';" in LEAGUE)
_assert("a missing question is registered as an integrity event, not swallowed",
        "export function missingPoolQuestions()" in LEAGUE
        and "console.warn" in LEAGUE)
_assert("  · and marked on the card, so it is machine-visible as well as "
        "readable", "data-question-missing" in LEAGUE)
_assert("one warning per definition, so the first is not buried under its own "
        "repetitions", "if (!MISSING_QUESTIONS.has(subject))" in LEAGUE)

# The governed field, end to end.
CATALOG = json.loads(_read_root("spec", "pool_catalog_rev1_4.json"))
_eligible = [d for d in CATALOG["definitions"]
             if d.get("definition_runtime_eligible")]
_left = [d for d in CATALOG["definitions"]
         if not d.get("definition_runtime_eligible")]
_assert("all 64 runtime-eligible definitions carry a governed public_question",
        len(_eligible) == 64
        and all((d.get("public_question") or "").strip() for d in _eligible),
        f"{len(_eligible)} eligible, "
        f"{sum(1 for d in _eligible if (d.get('public_question') or '').strip())} "
        f"with a question")
_assert("the 16 non-drawable definitions are still allowed to carry none",
        len(_left) == 16
        and all(d.get("public_question") is None for d in _left),
        str(len(_left)))
_assert("the API serves the field",
        "public_question: Optional[str]" in API)
_assert("the slate read model carries it through",
        "question: slot.public_question || null"
        in _read("js", "pool-slate-model.js"))


# ══ §7 · the wide button is gone ═══════════════════════════════════════════

_section("§7 · the superseded full-width button")

_assert("`.fs-refresh__btn` is no longer declared in any stylesheet",
        ".fs-refresh__btn {" not in WAGER_CSS
        and ".fs-refresh__btn {" not in COMPONENTS_CSS)
_assert("and nothing renders it",
        "fs-refresh__btn" not in REFRESH_ODDS)
_assert("the Status control is now the shared small glyph",
        "refreshControl({" in REFRESH_ODDS
        and "fs-oddsref--card" in REFRESH_ODDS)
_assert("its label became the accessible name rather than visible caps",
        "REFRESH_LABEL = 'Refresh odds for this Matchup'" in REFRESH_ODDS)


# ══ §8 · component tier ════════════════════════════════════════════════════

def _run_node(script: str, label: str) -> None:
    node = shutil.which("node")
    if node is None:
        _assert(f"{label} — node is available", False, "node not on PATH")
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


_run_node("uirecon_refresh_ux_component.mjs",
          "§8 · refresh UX component suite (Node, no browser)")


# ══ §9 · browser tier ══════════════════════════════════════════════════════

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


_run_browser("uirecon_refresh_ux_browser.mjs",
             "§9 · refresh UX browser suite (headless Chrome, "
             "320x568 / 375x667 / 390x844 / 768x1024 / 1024x768)")


print("\n" + "=" * 70)
if _failures:
    print(f"REFRESH UX — {len(_failures)} FAILED")
    for label in _failures:
        print(f"  - {label}")
    sys.exit(1)
print("REFRESH UX — ALL PASSED")
