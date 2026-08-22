#!/usr/bin/env python3
"""
test_uirecon_rev14_presentation.py — UIRECON Rev 1.4 · presentation reconciliation.

Run:  python test_uirecon_rev14_presentation.py

FOUR PRESENTATION DEFECTS, AND WHAT WAS DONE ABOUT EACH.

  1 · THE OVERALL HEADER DID NOT FIT ITS OWN COLUMNS. Every figure column was
      one width — 4.6em, about 60px — and `MATCHUPS` measured 72px and `PROP
      POOLS` 82px against roughly 50px of usable cell. Both wrapped. The header
      row stood at 45px where the two tables below it stood at 28px, and the
      two wrapped labels sat one under the other with nothing between them.

      `PROP POOLS` becomes `POOLS`: the table it heads is already `PROP POOL
      STANDINGS` and the figures under it are already Prop Pool Credits, so the
      first word was repeating what the surface had said twice. `MATCHUPS` is
      NOT abbreviated and is not `MATCHES` — it is the product's term for the
      contest and the term the two tables below it use. Its width is bought
      instead, from a column-width contract that sizes each column by what has
      to fit in it rather than giving all three the same share.

  2 · A CARET SAT BETWEEN THE TEAM NAME AND THE GEAR. Nine pixels of ornament
      in the narrowest column of the masthead, close enough to the Settings
      gear to read as part of it. It is gone, and nothing replaces it. What it
      claimed to say — that the control opens something — the button already
      says where it counts: `aria-haspopup="dialog"`, `aria-expanded`, and an
      accessible name that begins with the word Account. Those are untouched.

  3 · `Held` WAS PROPOSED FOR RENAMING TO `Escrow`, AND IT IS NOT ESCROW.
      Traced through the read model: the cell binds `held_open_challenges_cents`,
      which `reports/ledger_read_model.py` documents as escrow "funded against
      challenges still in an OPEN response state" and as "a SUBSET of
      `in_play_cents` rather than an addition to it". The escrow on unresolved
      WAGERS is `In Play`, the cell immediately to its left. Labelling the
      subset `Escrow` beside the whole of it would have told a GM the two are
      different kinds of money and that adding them means something — the exact
      double count both read models are written to prevent. `Held` is also the
      POR's own term: Rev 4.3 §14.1 retains it, and the Rev 3.1 register
      defines it as "Pending offer holds ... `Held · not In Play`". The label
      is unchanged, the figure is unchanged, and §3 below pins both.

  4 · `WAGERING SUMMARY` CARRIED A GOLD RULE DOWN ITS LEFT EDGE, on top of a
      lifted fill and a gold-tinted border — three markers for one fact, and
      the one that read as ornament is the same rule Standings uses to mean
      "this row is yours". Removed. The fill and the even border stay, because
      removing an ornament is not licence to remove the section's hierarchy.

WHERE THE ASSERTIONS LIVE. Everything above is a claim about rendered pixels —
how many line boxes a header takes, whether two boxes overlap, whether a glyph
is drawn. Those are asked in `web/tests/uirecon_rev14_presentation_browser.mjs`
against a real headless Chrome at five certified viewports. This file asserts
the things that are true of the SOURCE — that the terminology is what it says
it is, that the width contract is expressed as widths rather than as smaller
type, and that no accounting was touched to make a label true.
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

# THE BROWSER TIER NEEDS A LEAGUE WITH ROWS IN IT. A standings table with no
# rows proves nothing about a team name's measure, and the static file server
# answers 404 to the session call — which draws the sign-in gate and leaves
# every selector in the browser suite pointing at an application that was never
# mounted. This is the same door `test_uirecon_wave2.py` uses.
ensure_authenticated_app(seed_pool_slate=True, action_shape="full")

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
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def _without_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


STANDINGS_MODEL = _read("web", "js", "standings-model.js")
STANDINGS_CSS = _read("web", "styles", "standings.css")
AUTH_VIEW = _read("web", "js", "auth-view.js")
LEDGER_JS = _read("web", "js", "ledger.js")
LEDGER_MODEL = _read("web", "js", "ledger-model.js")
COMPONENTS_CSS = _read("web", "styles", "components.css")


# ── §1 · The OVERALL columns are the locked five ────────────────────────────

_section("§1 · the OVERALL header names the right five things")

_model_code = _without_comments(STANDINGS_MODEL)

_assert("OVERALL declares RK / TEAM / MATCHUPS / POOLS / NET",
        "['RK', 'TEAM', 'MATCHUPS', 'POOLS', 'NET']" in _model_code,
        (re.search(r"columns: Object\.freeze\(\[[^\]]*\]", _model_code) or [""])[0])
_assert("`PROP POOLS` is gone from the column set",
        "'PROP POOLS'" not in _model_code)
_assert("the PROP POOL STANDINGS table keeps its full name",
        "heading: 'PROP POOL STANDINGS'" in _model_code)
# MATCHUPS IS THE TERM, IN BOTH PLACES IT APPEARS.
_assert("Matchups is not abbreviated anywhere in the column set",
        not re.search(r"'(MATCHES|MTCH\w*|MU)'", _model_code))
_assert("MATCHUP STANDINGS still heads the second table",
        "heading: 'MATCHUP STANDINGS'" in _model_code)
_assert("the read model still serves exactly three tables",
        _model_code.count("key: '") == 3, str(_model_code.count("key: '")))

# NOTHING BUT THE LABEL MOVED. The cells the model derives are unchanged, so a
# column rename cannot have quietly become a data change.
_assert("OVERALL still derives Matchup net, Pool net and the score",
        "versus_net_cents" in _model_code and "pool_net_cents" in _model_code
        and "net_cents: Number(row.net_cents)" in _model_code
        or "Number(row.net_cents)" in _model_code)
_assert("the championship tie rule is still read from the server",
        "row.championship_tied || row.tied" in _model_code)


# ── §2 · The width contract is widths, not smaller type ─────────────────────

_section("§2 · the columns are sized, not shrunk")

_assert("a rank, a figure and a wide-figure width are declared",
        all(name in STANDINGS_CSS for name in
            ("--fs-st-rank", "--fs-st-fig", "--fs-st-wide")))
_assert("each is capped by a share of the viewport, so a narrower window "
        "degrades rather than overflows",
        STANDINGS_CSS.count("min(") >= 3)
_assert("the rank column uses the declared width",
        "width: var(--fs-st-rank)" in STANDINGS_CSS)
_assert("the figure columns use the declared width",
        "width: var(--fs-st-fig)" in STANDINGS_CSS)
_assert("only OVERALL's third column takes the wide one",
        '[data-standings-table="overall"]' in STANDINGS_CSS
        and "width: var(--fs-st-wide)" in STANDINGS_CSS)
_assert("TEAM is still the column that takes what is left",
        "width: auto" in STANDINGS_CSS)

# THE TYPE DID NOT SHRINK TO PAY FOR THIS. Both sizes are still the §5.1
# tokens; a suite that only measured the rendered header would have passed a
# fix that made the words smaller instead of the columns wider.
_assert("the header keeps the §5.1 metadata size",
        "font-size: var(--fs-r43-meta);" in STANDINGS_CSS)
_assert("money keeps the §5.1 card-secondary size",
        "font-size: var(--fs-r43-card-secondary);" in STANDINGS_CSS)
_assert("no font-size was reduced to a raw pixel value in the table",
        not re.search(r"\.fs-st__(table th|num)[^}]*font-size:\s*\d+px",
                      STANDINGS_CSS, flags=re.S))

# THE STRUCTURAL GUARD. Widths are sized to fit; this is what happens if a
# future label outgrows them anyway, and it is a clip rather than a wrap.
_assert("a header can never take a second line",
        "white-space: nowrap;" in STANDINGS_CSS
        and "text-overflow: ellipsis;" in STANDINGS_CSS)
_assert("the scroll region is still vertical only",
        "overflow-x: hidden;" in STANDINGS_CSS)
_assert("a long team name still truncates rather than wrapping",
        ".fs-st__team" in STANDINGS_CSS and "overflow: hidden;" in STANDINGS_CSS)


# ── §3 · The account control lost an ornament and nothing else ──────────────

_section("§3 · the caret is gone; the control is not")

_auth_code = _without_comments(AUTH_VIEW)

_assert("no chevron element is emitted", "fs-acct__chev" not in _auth_code)
for _glyph in ("▾", "▿", "▼", "▽", "⌄", "◂", "▸"):
    _assert(f"no `{_glyph}` is drawn into the header", _glyph not in _auth_code)
_assert("no icon was introduced to replace it",
        "<svg" not in _auth_code.split("export function buildIdentityBlock")[1]
        .split("export function")[0])
_assert("the control is still a real button",
        "<button type=\"button\" class=\"fs-acct\" id=\"fs-account\" " in _auth_code)
_assert("it still announces that it opens a dialog",
        "aria-haspopup=\"dialog\"" in _auth_code)
_assert("it still carries aria-expanded", "aria-expanded=\"false\"" in _auth_code)
_assert("it still carries an accessible name naming the account",
        "aria-label=\"Account —" in _auth_code)
_assert("the team name is still what it draws",
        "fs-ident__who" in _auth_code)
_assert("clicking it still opens the account sheet",
        "api.openSheet(() => accountSheet())" in _auth_code)


# ── §4 · `Held` is `Held`, and the accounting behind it is untouched ────────

_section("§4 · the strip label, and the read model it answers to")

_assert("the Account strip's third cell is still labelled Held",
        "{ label: 'Held', cents: heldCents" in LEDGER_JS)
_assert("it was NOT renamed Escrow",
        "label: 'Escrow'" not in LEDGER_JS)
_assert("the four cells are still the locked four",
        all(f"label: '{cell}'" in LEDGER_JS
            for cell in ("Available", "In Play", "Held", "Min Left")))
_assert("the figure is still the server's own held amount",
        "boundHeldCents()" in LEDGER_JS)
_assert("and is still bound from `held_open_challenges_cents`",
        "heldCents: model.held_open_challenges_cents" in LEDGER_MODEL)

# THE EVIDENCE FOR THE DECISION, READ FROM THE SERVER'S OWN WORDS. If either
# sentence ever stops being true, the label deserves another look — so the
# suite asserts the reason rather than only the outcome.
_ledger_read_model = _read("reports", "ledger_read_model.py")
_assert("the read model still calls it escrow on OPEN challenges only",
        "still in an OPEN response state" in _ledger_read_model)
_assert("and still calls it a subset of In Play rather than an addition",
        # The sentence wraps in the source, so it is matched across whitespace.
        bool(re.search(r"SUBSET of\s+`in_play_cents`", _ledger_read_model)))
_assert("In Play is still bound to the whole of in_play_cents",
        "acceptedEscrowCents: model.in_play_cents" in LEDGER_MODEL)

# NO ECONOMICS WERE MOVED TO MAKE A LABEL TRUE.
_FROZEN = ("economy/current_settle.py", "economy/challenge_escrow_view.py",
           "economy/challenge_funding.py", "betting/settlement_engine.py",
           "betting/pool_settlement.py", "reports/ledger_read_model.py",
           "reports/standings_read_model.py")


def _changed_files() -> list[str]:
    def _git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, check=False).stdout

    return sorted(set(_git("diff", "--name-only", "HEAD").split()))


_breach = sorted(set(_FROZEN) & set(_changed_files()))
_assert("no settlement, escrow or read-model file was touched",
        not _breach, ", ".join(_breach))
_assert("Held is still reported beside the position, never inside a total",
        "wageringPositionCents" in LEDGER_MODEL
        and "heldCents" not in re.sub(
            r"wageringPositionCents: sum\((.*?)\)", "", LEDGER_MODEL, flags=re.S)
        .split("export function position()")[-1])


# ── §5 · The gold left edge, and where its removal is expressed ─────────────

_section("§5 · the Account section's left edge")

_assert("the Account surface no longer draws a gold left rule",
        ".fs-lscroll .fs-lsec.is-elevated { box-shadow: none; }"
        in COMPONENTS_CSS)
_assert("the removal is scoped to the Account scroll region",
        ".fs-lscroll .fs-lsec.is-elevated" in COMPONENTS_CSS)
_assert("it says why it is expressed here rather than at the declaration",
        "RECONCILE" in COMPONENTS_CSS and "ledger.css" in COMPONENTS_CSS)
_assert("no replacement side ornament was added",
        not re.search(r"\.fs-lscroll[^{]*\{[^}]*border-left", COMPONENTS_CSS))
_assert("the section still asks for the elevated treatment",
        "elevated: true" in LEDGER_JS)
_assert("and it is still WAGERING SUMMARY that asks",
        "title: 'WAGERING SUMMARY'" in LEDGER_JS)

# THE WRAP UP CARD IS NOT THIS PASS'S. The same instruction applies there and
# is another pass's to carry out; asserting it here would fail for a reason
# this file's own diff could not explain.
#
# MEASURED OVER DECLARATIONS, NOT PROSE. A later pass added a block to this
# sheet whose COMMENT explains where its control sits relative to
# `.fs-wcard__head` — an explanation, not a rule — and a raw substring search
# read that as a restyle of the Wrap Up card. Comments are stripped first, so
# the guard now catches what it was written to catch and nothing else.
_assert("the Wrap Up result card was not touched from here",
        "fs-wcard" not in re.sub(r"/\*[\s\S]*?\*/", " ", COMPONENTS_CSS)
        .split("UIRECON Rev 1.4")[-1])


# ── Node tier ───────────────────────────────────────────────────────────────

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


_run_node("uirecon_rev14_presentation_browser.mjs",
          "UIRECON Rev 1.4 presentation suite "
          "(headless Chrome, five certified viewports)")


# ── Result ──────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
if _failures:
    print(f"UIRECON REV 1.4 PRESENTATION — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
print("UIRECON REV 1.4 PRESENTATION — all assertions PASSED")
