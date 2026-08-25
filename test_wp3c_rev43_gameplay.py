#!/usr/bin/env python3
"""
test_wp3c_rev43_gameplay.py — WP3C · the Rev 4.3 gameplay surfaces.

Three tiers, in this repository's usual shape:

  1. STRUCTURAL, in Python. The claims that must hold in the SOURCE and that a
     browser cannot make — that no production surface can fall back to
     illustrative content, that eligibility cannot be inferred, that no second
     economic engine appeared, and that the governing specs are untouched.

  2. BEHAVIOURAL, in Node. `web/tests/wp3c_component_tests.mjs` runs the shipped
     modules against served bodies shaped as the routes return them.

  3. MEASURED, in headless Chrome. `web/tests/wp3c_browser.mjs` drives the real
     application at four viewports.

WHAT THIS SUITE GUARDS AGAINST. Two things above all.

  FABRICATED PRODUCTION CONTENT. Play rendered eleven invented opponents with
  invented lines to every signed-in GM. The danger in fixing that is a partial
  fix — one surface bound and another still falling through to the fixture —
  so §1 below classifies EVERY illustrative export by who may read it, and
  asserts that no production path can reach one.

  INFERRED ELIGIBILITY. Postseason Versus admission belongs to the championship
  track. A frontend that guessed it from a week number would offer wagers the
  funding gate refuses, which is the pre-WP1C defect wearing a new coat. §3
  asserts the frontend has nothing to guess FROM.

USAGE:
    python test_wp3c_rev43_gameplay.py
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

from test_support_s7_harness import ensure_authenticated_app  # noqa: E402

ensure_authenticated_app()

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


def _read(*parts: str) -> str:
    with open(os.path.join(WEB, *parts), encoding="utf-8") as fh:
        return fh.read()


def _read_root(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _strip_comments_py(source: str) -> str:
    """Python comments and docstrings removed, for source claims about code."""
    source = re.sub(r'"""[\s\S]*?"""', " ", source)
    source = re.sub(r"^\s*#.*$", " ", source, flags=re.MULTILINE)
    return source


def _strip_comments(source: str) -> str:
    """Remove comments so source assertions test what the app DOES.

    A comment explaining why an input is absent must not itself trip the check
    that the input is absent.
    """
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    source = re.sub(r"<!--.*?-->", " ", source, flags=re.DOTALL)
    source = re.sub(r"^\s*//.*$", " ", source, flags=re.MULTILINE)
    return source


LEAGUE_JS = _read("js", "league.js")
VERSUS_JS = _read("js", "versus-model.js")
PREVIEW_JS = _read("js", "preview.js")
COMPOSER_JS = _read("js", "composer.js")
ACTION_JS = _read("js", "action.js")
COUNTER_JS = _read("js", "counter-stake.js")
WEEK_JS = _read("js", "week.js")
LEDGER_JS = _read("js", "ledger.js")
PHASE_JS = _read("js", "phase.js")
RULES_DATA_JS = _read("js", "data", "rules-data.js")
SETTINGS_JS = _read("js", "settings-model.js")
SHELL_JS = _read("js", "shell.js")
GAMEPLAY_CSS = _read("styles", "gameplay.css")
INDEX_HTML = _read("index.html")

ALL_JS = "\n".join(
    open(os.path.join(dirpath, f), encoding="utf-8").read()
    for dirpath, _dirs, files in os.walk(os.path.join(WEB, "js"))
    for f in files if f.endswith(".js"))
RENDERED = _strip_comments(ALL_JS)


# ── 1 · No fabricated production content — WP3C §4, §32 ──────────────────────

_section("1 · No production path can reach illustrative content")

# EVERY ILLUSTRATIVE MODULE IS CLASSIFIED, and the classification is asserted
# rather than described. WP3C §32 asks for exactly this: each occurrence is a
# test fixture, a governed Demo source, or a prohibited production fallback.
#
#   data/league-data.js   fixture. Play no longer imports its OPPONENTS or its
#                         `allMatchups`; it keeps `POOLS` for the demo grid and
#                         `poolBadge`, which is a pure formatter.
#   data/week-data.js     fixture, Wrap Up, gated on `slateMode() === demo`.
#   data/action-data.js   fixture, Status, gated on `actionMode() === demo`.
#   data/ledger-data.js   fixture, Account, gated on `ledgerMode()`.
_assert("Play imports no illustrative opponent list",
        "OPPONENTS" not in LEAGUE_JS and "allMatchups" not in LEAGUE_JS)
_assert("Play's Versus discovery reads the served opponents and nothing else",
        "from './versus-model.js'" in LEAGUE_JS
        and "servedAction()" in VERSUS_JS)
_assert("the Versus model has NO fallback source at all",
        "league-data" not in _strip_comments(VERSUS_JS)
        and "ILLUSTRATIVE" not in _strip_comments(VERSUS_JS),
        "it imports only the Action read")
_assert("an unbound Versus model returns an empty list, never a fixture",
        "if (MODE !== VERSUS_MODE_AUTHORITATIVE) return [];" in VERSUS_JS)
_assert("Play's Pools read the governed slate, gated on demo mode",
        "slateMode() === SLATE_MODE_DEMO ? POOLS : slateRows()" in LEAGUE_JS)
# THE IDENTIFIER, NOT THE WORD. `FANTASYSTAKES PROP POOLS` is a heading and says
# nothing about the constant; counting bare occurrences would count it twice.
#
# UIRECON WAVE 1 renamed the heading to the locked public term; UIRECON REV 1.4
# PART 3 shortened it again, to `PROP POOLS`, and hoisted it into a named
# constant. Stripping the SHORTER string covers both spellings — the Wave 1 form
# contains it — so this keeps counting identifiers rather than headings. The
# claim is untouched: the demo `POOLS` constant is reachable only through the
# `slateMode()` gate above.
_POOLS_IDENT = re.findall(r"(?<![A-Z_'\"])POOLS(?![A-Z_])",
                          _strip_comments(LEAGUE_JS)
                          .replace("PROP POOLS", ""))
_assert("and the demo Pool constant is reachable ONLY through that gate",
        len(_POOLS_IDENT) == 2, f"{len(_POOLS_IDENT)} references")

# THE CARD ITSELF CARRIES NO INVENTED FIGURE. Rev 4.2's card printed a record, a
# rank, two projections, a teaser and three quoted lines; none had a source for
# an arbitrary pairing.
#
# WP3C.2 GAVE THREE OF THEM A SOURCE, and only three. The owner ruling on market
# line methodology created an authoritative market board — a served moneyline,
# spread and total per real pairing — so `formatOdds` and `formatSpread` are now
# legitimate on this card: they draw figures the SERVER computed. What has no
# source is unchanged and still banned below. The claim this loop protects was
# never "no numbers" — it was "no numbers nobody produced" — and WP3C.2's own
# suite proves the three that arrived came off the board and not out of the
# browser.
for banned in ("m.record", "m.rank", "yourProjection", "opponentProjection",
               "teaser"):
    _assert(f"the discovery card renders no {banned}",
            banned not in _strip_comments(LEAGUE_JS))

_assert("the card's market figures come from the SERVED board, not a fixture",
        "marketFor(" in _strip_comments(LEAGUE_JS)
        and "acting_spread" in _strip_comments(LEAGUE_JS))
_assert("and it derives no sign, no median and no rounding of its own",
        not re.search(r"-\s*(row|board|served)\.\w*spread",
                      _strip_comments(LEAGUE_JS))
        and "median" not in _strip_comments(LEAGUE_JS).lower()
        and "Math.round(" not in _strip_comments(LEAGUE_JS))

# EVERY ILLUSTRATIVE FIGURE SITS ON THE DEMO BRANCH, and the check is
# positional: each `ILLUSTRATIVE.` reference must appear AFTER a `:` on a line
# that also tests `production`, which is the false arm of the ternary. A figure
# moved to the true arm — the production one — fails this.
_ILLUSTRATIVE_LINES = [ln for ln in _strip_comments(LEAGUE_JS).split("\n")
                       if "ILLUSTRATIVE." in ln]
_assert("Play references illustrative money only on a demo branch",
        len(_ILLUSTRATIVE_LINES) > 0
        and all(":" in ln.split("ILLUSTRATIVE.")[0] for ln in _ILLUSTRATIVE_LINES),
        f"{len(_ILLUSTRATIVE_LINES)} references, all on the false arm")
_assert("and every one of those branches is guarded by the production test",
        _strip_comments(LEAGUE_JS).count("production ?") >= len(_ILLUSTRATIVE_LINES))


_section("2 · Real data, or an intentional state — never a substitute")

for state in ("VERSUS_STATE_NO_DATA", "VERSUS_STATE_UNAVAILABLE",
              "VERSUS_STATE_FIELD_UNKNOWN", "VERSUS_STATE_NONE_ELIGIBLE"):
    _assert(f"{state} has its own copy", state in LEAGUE_JS)
_assert("an undrawn Pool slate draws its own state, not four invented Pools",
        "data-pools-state" in LEAGUE_JS and "No Pools drawn yet" in LEAGUE_JS)
# THE COPY, NOT THE KEYS. `VERSUS_COPY` is keyed by the state constants, which
# are legitimately SCREAMING_SNAKE; what must not leak is a code shape inside a
# heading or body string.
_COPY_BLOCK = _strip_comments(LEAGUE_JS).split("const VERSUS_COPY")[1] \
    .split("});")[0]
_COPY_STRINGS = " ".join(re.findall(r"'([^']{8,})'", _COPY_BLOCK))
_assert("no empty-state copy carries a reason code or identifier",
        not re.search(r"[a-z]_[a-z]|[A-Z]+_[A-Z]+|\.py\b", _COPY_STRINGS),
        (re.search(r"[a-z]_[a-z]|[A-Z]+_[A-Z]+", _COPY_STRINGS) or [""])[0])


# ── 3 · Eligibility is read, never inferred — WP3C §6 ────────────────────────

_section("3 · The frontend has nothing to infer postseason eligibility FROM")

_VERSUS_CODE = _strip_comments(VERSUS_JS)
_assert("the Versus model imports no week", "currentWeek" not in _VERSUS_CODE)
_assert("no phase helper either — presentation phase is a separate concept",
        "phase.js" not in _VERSUS_CODE)
_assert("no standings, seed, rank or record input",
        not re.search(r"standings|seed|\brank\b|record", _VERSUS_CODE, re.I))
_assert("eligibility is read straight off the served row",
        "o.versus_eligible !== false" in VERSUS_JS)
_assert("an undeterminable field admits NOBODY",
        "if (!fieldDeterminable()) return VERSUS_STATE_FIELD_UNKNOWN" in VERSUS_JS)

# THE BACKEND SIDE. The rule is `beefs/postseason_versus`'s and the composition
# layer supplies it; `reports/` marks the list and decides nothing.
ARM = _read_root("reports", "action_read_model.py")
MAIN = _read_root("api", "main.py")
_assert("the read model does not compute eligibility",
        "postseason" not in ARM.lower().replace("phase_postseason", "")
        or "eligible_team_ids: Optional[frozenset] = None" in ARM)
_assert("it receives the eligible set rather than deriving one",
        "eligible_team_ids: Optional[frozenset] = None" in ARM
        and "eligible_team_ids is None\n                             or t.id in eligible_team_ids"
        in ARM)
_assert("the composition layer calls the governed authority",
        "from beefs.postseason_versus import" in MAIN
        and "eligible_team_ids(state, resolver)" in MAIN)
_assert("the regular season short-circuits before any provider work",
        "if not is_postseason_week(league, week):" in MAIN)
_assert("and every failure mode fails CLOSED, admitting nobody",
        "return frozenset(), PHASE_POSTSEASON, False" in MAIN)
_assert("the funding gate is untouched — nothing here replaces it",
        "assert_admissible" in _read_root("economy", "challenge_funding.py"))


# ── 4 · The projection/odds coupling — WP3C §10, §35 ─────────────────────────

_section("4 · Versus odds read the league's own season and provider")

ENGINE = _read_root("beefs", "beef_engine.py")
_assert("a projection context resolver exists",
        "def projection_context_for_team" in ENGINE)
_assert("it reads the league's own season and projection source",
        "League.season, League.projection_source" in ENGINE)
_assert("no projection query on the odds path names the global season",
        "season=SEASON, source=SOURCE" not in _strip_comments_py(ENGINE)
        .replace("GLOBAL_PROJECTION_CONTEXT = ProjectionContext("
                 "season=SEASON, source=SOURCE)", ""),
        "every query reads the resolved context")
_assert("the globals survive only as the named fallback",
        "GLOBAL_PROJECTION_CONTEXT = ProjectionContext(season=SEASON, source=SOURCE)"
        in ENGINE)
_assert("the odds model itself is untouched",
        "LEGACY_MODEL_CONFIG" in ENGINE
        and "def _compute_odds_from_inputs" in ENGINE)
_assert("no Demo season is hard-coded anywhere on the path",
        "2100" not in _strip_comments_py(ENGINE),
        "the only mention is the comment explaining the defect")
_assert("the focused regression suite exists",
        os.path.isfile(os.path.join(ROOT, "test_wp3c_projection_context.py")))


# ── 5 · No second economic engine — Rev 4.3 §28 ──────────────────────────────

_section("5 · The frontend recreates no economic or eligibility logic")

def _code_only(source: str) -> str:
    """Source with comments and string literals removed."""
    return re.sub(r"'[^'\n]*'|\"[^\"\n]*\"|`[^`]*`", "''",
                  _strip_comments(source)).replace("*/", "")


for name, src in (("versus-model.js", VERSUS_JS), ("phase.js", PHASE_JS),
                  ("preview.js", PREVIEW_JS)):
    _assert(f"{name}: contains no arithmetic", "*" not in _code_only(src)
            and not re.search(r"(?<![/*])/(?![/*])", _code_only(src)), name)

_assert("counter-stake.js multiplies only at the Credits boundary",
        _code_only(COUNTER_JS).count("*") == 1
        and "credits * 100" in COUNTER_JS)
_assert("and clamps nothing — the server owns every bound",
        not re.search(r"Math\.(min|max)", COUNTER_JS))
_assert("no WP3C module imports a protocol module",
        not re.search(r"from ['\"](\.\./)+(economy|ledger|beefs|betting|wallet|api)/",
                      VERSUS_JS + PREVIEW_JS + COUNTER_JS + PHASE_JS))
_assert("the phase helper exposes no eligibility answer",
        "eligib" not in _code_only(PHASE_JS).lower())


# ── 6 · No browser-native interaction survives — WP3C §15 ────────────────────

_section("6 · window.prompt is gone from the application")

_assert("no module calls window.prompt",
        "window.prompt(" not in RENDERED)
_assert("no module calls window.confirm or window.alert",
        "window.confirm(" not in RENDERED and "window.alert(" not in RENDERED)
_assert("the shell no longer supplies a prompt hook",
        "promptStake" not in _strip_comments(SHELL_JS))
_assert("the counter sheet replaces it, in the shared sheet grammar",
        "counterStakeSheet" in ACTION_JS and "api.push" in ACTION_JS)
_assert("with a field, a deliberate send, a cancel and somewhere for a refusal",
        all(x in COUNTER_JS for x in
            ("fs-cstake-input", "fs-cstake-send", "fs-cstake-cancel",
             "fs-cstake-error")))


# ── 7 · The dynamic season phase — WP3C §17, §21, §27 ────────────────────────

_section("7 · The season phase is read on every surface")

_assert("the phase helper exists and is centralised",
        os.path.isfile(os.path.join(WEB, "js", "phase.js")))
_assert("it reads the served context, deciding nothing",
        "servedContext()" in PHASE_JS and "context.phase" in PHASE_JS)
_assert("the backend derives it from the league's own boundaries",
        "def _season_phase" in _read_root("reports", "league_read_model.py")
        and "phase_for_week" in _read_root("reports", "league_read_model.py"))
_assert("it supports all four user-facing states",
        all(p in PHASE_JS for p in ("Regular Season", "Postseason",
                                    "Championship", "Season Complete")))
for name, src in (("Play", LEAGUE_JS), ("Status", ACTION_JS),
                  ("Account", LEDGER_JS)):
    _assert(f"{name} reads the phase helper", "from './phase.js'" in src)


# ── 8 · Readability uses the WP3B scale — WP3C §30 ───────────────────────────

_section("8 · One readability system, not two")

_sizes = re.findall(r"font-size:\s*([^;]+);", GAMEPLAY_CSS)
# UIRECON WAVE 1 ADDED A SECOND ACCEPTED PREFIX, AND IT IS NOT A SECOND SCALE.
# `--fs-c-*` is the canonical ALIAS layer: every one of those names is defined
# in `tokens.css` as exactly `var(--fs-r43-…)`, and `test_uirecon_wave1.py`
# asserts each alias resolves to its target one by one. A shared primitive reads
# the alias so it names ONE answer instead of choosing between the Rev 4.2 and
# Rev 4.3 scales — which is this section's own claim, not an exception to it.
# A raw px value is still a failure, and that is what this catches.
_ACCEPTED_SCALE = ("--fs-r43-", "--fs-c-size-")
_assert("every font-size in the WP3C sheet is a Rev 4.3 token",
        all(any(p in v for p in _ACCEPTED_SCALE) for v in _sizes),
        ", ".join(v.strip() for v in _sizes
                  if not any(p in v for p in _ACCEPTED_SCALE)) or "all tokens")
# THE DECLARATIONS, NOT THE PROSE. A comment may name the figure it is
# explaining; what must not appear is a `44px` in a rule.
_CSS_CODE = re.sub(r"/\*[\s\S]*?\*/", " ", GAMEPLAY_CSS)
_assert("every touch minimum is the token, not a literal",
        "44px" not in _CSS_CODE and "--fs-r43-touch" in _CSS_CODE)
_assert("no parallel scale was introduced",
        "--fs-wp3c" not in GAMEPLAY_CSS and "--fs-r44" not in GAMEPLAY_CSS)
_assert("the sheet loads after the WP3B foundation",
        INDEX_HTML.index("gameplay.css") > INDEX_HTML.index("rev43.css"))
_assert("the locked palette is untouched",
        "--gold" not in GAMEPLAY_CSS.split(":root")[0].split("{")[0]
        if ":root" in GAMEPLAY_CSS else True)
_assert("the WP3C sheet declares no palette token at all",
        ":root" not in GAMEPLAY_CSS)


# ── 9 · Locked language survives — Rev 4.3 §2, §3 ────────────────────────────

_section("9 · The Rev 4.3 shell and its locked strings are intact")

NAV_JS = _read("js", "nav.js")
_assert("the five primary tabs are unchanged",
        "'Standings'" in NAV_JS and "'Play'" in NAV_JS and "'Status'" in NAV_JS
        and "'Wrap Up'" in NAV_JS and "'Account'" in NAV_JS)
_assert("Standings is still first and default",
        "DEFAULT_DESTINATION_ID = 'standings'" in NAV_JS)
_assert("Rules & Settings is still secondary",
        "SECONDARY_DESTINATIONS" in NAV_JS)
_assert("the primary tagline is exact",
        "'Real odds. Fantasy stakes. More ways to win.'"
        in _read("js", "demo-state.js"))
_assert("the Ledger trust anchor is exact",
        "'Real odds. Fantasy stakes. Ledger keeps score.'" in LEDGER_JS)
_assert("and it appears on Account only once",
        LEDGER_JS.count("LEDGER_TRUST_ANCHOR") == 2, "one definition, one use")


_section("10 · Stale terminology is gone from user-visible copy")

_SEAMLESS = re.sub(r"^\s*(computation|serverAuthority|readModel|endpoint|"
                   r"commissionerSurface):.*$", " ", RENDERED, flags=re.M)
for term in ("BAB", "Economy Stop", "fourteen weeks", "capped at",
             "five certified stops"):
    _assert(f"no user-visible {term!r}",
            term not in _SEAMLESS, term)
_assert("no user-visible python or web/js citation",
        not re.search(r"['\"][^'\"]*(\.py\b|web/js/)", _SEAMLESS),
        (re.search(r"['\"][^'\"]{0,60}(\.py\b|web/js/)", _SEAMLESS) or [""])[0])
_assert("no rendered heading carries a directional arrow",
        "↕" not in RENDERED)


# ── 11 · Governing artifacts untouched — WP3C §42 ────────────────────────────

_section("11 · The governing artifacts are unmodified")

# THE PROTOTYPE AND THE PUBLISHED PAGE STAY FROZEN. Nothing has been ruled
# about either, so the original guard applies to them unchanged.
for path in ("spec/FantasyStakes_UIUX_Prototype_Rev4_2_FINAL_POR.html",
             "docs/index.html"):
    proc = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", path],
                          cwd=ROOT, capture_output=True)
    _assert(f"{path} is unmodified", proc.returncode == 0)

# THE REV 4.3 POR IS NARROWLY OPEN, AND ONLY ON ONE SUBJECT.
#
# WP3C §42 froze it outright, which was right while no ruling touched it. The
# owner has since ruled the universal close control upper-left and instructed
# that the written specification be brought into line, so a blanket freeze would
# now hold the document permanently out of step with the product it governs.
#
# The guard is therefore narrowed rather than dropped: the file may differ from
# the last committed release, and every line that differs must be about the
# close control. A synchronization that quietly edited economics, navigation or
# provider behaviour would pass a filename check and fail this one.
_POR_PATH = "spec/FantasyStakes_UIUX_Rev4_3_FINAL_POR.md"
_por_diff = subprocess.run(
    ["git", "diff", "-U0", "bc2de7b", "--", _POR_PATH],
    cwd=ROOT, capture_output=True, text=True,
    encoding="utf-8", errors="replace").stdout
_por_changed = [ln[1:].strip() for ln in _por_diff.splitlines()
                if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
_OFF_SUBJECT = (r"wager", r"credits?", r"settle\w*", r"escrow", r"Ledger",
                r"postseason", r"Yahoo", r"navigation", r"tab bar", r"odds",
                r"buy-?in", r"payout", r"provider", r"market line")
_stray = [ln for ln in _por_changed
          if any(re.search(rf"\b{term}\b", ln.replace("FantasyStakes", ""), re.I)
                 for term in _OFF_SUBJECT)]
_assert(f"{_POR_PATH} touched nothing governed by another package",
        not _stray, " | ".join(_stray)[:200])
# AND THE EDIT IS SMALL. A close-control synchronization is three passages; a
# diff of eighty lines would be a rewrite wearing its name.
_assert("and the synchronization is narrow in size",
        len(_por_changed) <= 40, f"{len(_por_changed)} changed line(s)")
_assert("and it now specifies the governing upper-left treatment",
        "positioned **upper-left**" in _read_root(_POR_PATH))

# ANCHORED TO WP3C'S OWN COMMIT RANGE. §43 forbade WP3C from touching the
# shortfall sweep, and it did not — but diffing against a moving HEAD turned
# that into a claim about every later package too. PG-CERT-1 legitimately
# parameterized the sweep against the configurable economy, which is its own
# governed work and not a WP3C scope violation.
WP3C_PARENT, WP3C_COMMIT = "0786f73", "ef3a74b"
_assert("betting/shortfall_sweep.py is untouched (§43)",
        subprocess.run(["git", "diff", "--quiet", WP3C_PARENT, WP3C_COMMIT,
                        "--", "betting/shortfall_sweep.py"],
                       cwd=ROOT, capture_output=True).returncode == 0)


# ── Node tiers ───────────────────────────────────────────────────────────────

def _run_node(script: str, label: str) -> None:
    node = shutil.which("node")
    if node is None:
        _assert(f"{label} — node is available", False, "node not on PATH")
        return
    print(f"\n{label}")
    proc = subprocess.run([node, os.path.join(WEB, "tests", script)],
                          cwd=ROOT, capture_output=True, text=True)
    print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print(proc.stderr.rstrip())
    passes = proc.stdout.count("[PASS]")
    fails = proc.stdout.count("[FAIL]")
    _assert(f"{label} is green", proc.returncode == 0,
            f"{passes} PASS / {fails} FAIL, exit {proc.returncode}")


_run_node("wp3c_component_tests.mjs", "WP3C component suite (Node)")
_run_node("wp3c_browser.mjs", "WP3C browser suite (headless Chrome)")


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 66)
if _failures:
    print(f"WP3C REV 4.3 GAMEPLAY — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("WP3C REV 4.3 GAMEPLAY — all assertions PASSED")
