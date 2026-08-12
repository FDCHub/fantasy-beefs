#!/usr/bin/env python3
"""
test_wp6a_skunk_ui.py — WP6A: SKUNK OF THE WEEK in The Week / Wrap Up.

TWO LAYERS.

  1. THE MODEL AND THE VIEW, driven directly. Which states draw a callout and
     which draw nothing; that the precision shown follows the authoritative
     values rather than a house style; and that the browser is never in a
     position to work out who was skunked.
  2. THE BROWSER, as an ordinary GM, against a league whose week was assessed by
     the certified engine — including the measured claim that the point
     differential is drawn LARGER than the final score, and three phone widths.

THE STATES THAT DRAW NOTHING ARE THE POINT OF LAYER 1. A Skunk callout names a
real GM as the week's worst loss and states a real $10 obligation against them.
An unassessed week, a tied week, a refused read and demo mode each have no such
result, and drawing a placeholder in any of them would put that sentence beside
a league that has not had one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'wp6aui.db')}"
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
print("WP6A — SKUNK OF THE WEEK, model and surface")
print("=" * 78)


# ══ 1 · the model and the view ══════════════════════════════════════════════

_section("1 · which states draw a callout, and which deliberately do not")

SERVED = {
    "league_id": 1, "season": 2026, "week": 5, "assessed": True,
    "classification": "ASSESSED", "amount_cents": 1000,
    "assessed_at": "2026-08-12T00:00:00+00:00",
    "entries": [{
        "team_id": 1, "team_name": "Gravy Train", "score": 101.83,
        "opponent_team_id": 2, "opponent_team_name": "The Braintrust",
        "opponent_score": 132.47, "margin": 30.64, "cents": 1000,
    }],
    "replayed": False,
}

NODE_PROBE = r"""
const base = %s;
const S = await import(base + 'skunk-model.js');
const W = await import(base + 'week.js');
const SERVED = %s;
const out = {};
const draws = (html) => /class="fs-skunk"/.test(html);

/* ── The states that must draw NOTHING ── */
out.demo = { mode: S.skunkMode(), callout: W.skunkCallout() };

S.markSkunkUnavailable();
out.unavailable = { mode: S.skunkMode(), callout: W.skunkCallout() };

S.bindSkunk({ ...SERVED, assessed: false, classification: null, entries: [] });
out.unassessed = { callout: W.skunkCallout(), model: S.skunkOfTheWeek() };

S.bindSkunk({ ...SERVED, classification: 'NO_LOSER', amount_cents: 0, entries: [] });
out.noLoser = { callout: W.skunkCallout(), model: S.skunkOfTheWeek() };

S.bindSkunk({ ...SERVED, week: 9 });
out.wrongWeek = { callout: W.skunkCallout() };

/* ── The assessed state ── */
S.bindSkunk(SERVED);
const html = W.skunkCallout();
const panel = W.buildWeekPanel();
out.assessed = {
  draws: draws(html),
  eyebrow: (html.match(/fs-skunk__eyebrow">([^<]*)</) || [])[1],
  line: (html.match(/data-skunk-line>([\s\S]*?)<\/div>/) || [])[1]
          .replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim(),
  margin: (html.match(/fs-skunk__marginvalue">([^<]*)</) || [])[1],
  final: (html.match(/data-skunk-final>([^<]*)</) || [])[1],
  fee: (html.match(/data-skunk-fee[^>]*>([^<]*)</) || [])[1],
  feeCents: (html.match(/data-skunk-fee[^>]*data-exact-cents="(\d+)"/) || [])[1],
  inPanel: draws(panel),
  modules: (panel.match(/data-module="(\w+)"/g) || []).map(m => m.split('"')[1]),
  isModule: /class="fs-skunk"[^>]*data-module=/.test(html),
  beforeYahoo: panel.indexOf('fs-skunk') < panel.indexOf('data-module="yahoo"'),
};

/* ── Precision follows the authoritative values ── */
const withScores = (score, opp, margin) => {
  S.bindSkunk({ ...SERVED, entries: [{ ...SERVED.entries[0],
    score, opponent_score: opp, margin }] });
  const h = W.skunkCallout();
  return {
    margin: (h.match(/fs-skunk__marginvalue">([^<]*)</) || [])[1],
    final: (h.match(/data-skunk-final>([^<]*)</) || [])[1],
  };
};
out.precision = {
  two: withScores(101.83, 132.47, 30.64),
  one: withScores(106.4, 110.5, 4.1),
  zero: withScores(100, 130, 30),
};

/* ── A tie splits the one contribution, and says so ── */
S.bindSkunk({ ...SERVED, entries: [
  { ...SERVED.entries[0], team_id: 1, team_name: 'Alpha', cents: 500 },
  { ...SERVED.entries[0], team_id: 3, team_name: 'Bravo', cents: 500 },
]});
const tied = W.skunkCallout();
out.tie = {
  draws: draws(tied),
  saysSplit: /split between them/.test(tied),
  count: S.skunkOfTheWeek().tiedCount,
  fee: (tied.match(/data-skunk-fee[^>]*data-exact-cents="(\d+)"/) || [])[1],
};

/* ── Sign-out returns it to demo ── */
S.unbindSkunk();
out.afterUnbind = { mode: S.skunkMode(), callout: W.skunkCallout() };

console.log(JSON.stringify(out));
"""

_url = ("file:///" + os.path.join(ROOT, "web", "js").replace("\\", "/").lstrip("/")
        + "/")
_proc = subprocess.run(
    ["node", "--input-type=module", "-e",
     NODE_PROBE % (json.dumps(_url), json.dumps(SERVED))],
    capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
if _proc.returncode != 0:
    print(_proc.stderr[:2000])
probe = json.loads(_proc.stdout) if _proc.returncode == 0 else {}

_assert("the model probe ran", _proc.returncode == 0,
        _proc.stderr[:200] if _proc.returncode else "exit 0")

_assert("nothing bound draws NO callout — there is no illustrative Skunk",
        probe.get("demo", {}).get("mode") == "demo"
        and probe.get("demo", {}).get("callout") == "")
_assert("a refused read draws no callout, and enters unavailable",
        probe.get("unavailable", {}).get("mode") == "unavailable"
        and probe.get("unavailable", {}).get("callout") == "")
_assert("an UNASSESSED week draws nothing — not 'no Skunk this week'",
        probe.get("unassessed", {}).get("callout") == ""
        and probe.get("unassessed", {}).get("model") is None,
        "Week Close has not run; that is not a result")
_assert("a genuinely tied week (NO_LOSER) draws nothing either",
        probe.get("noLoser", {}).get("callout") == ""
        and probe.get("noLoser", {}).get("model") is None)
_assert("a result bound for ANOTHER week is not drawn under this one",
        probe.get("wrongWeek", {}).get("callout") == "",
        "week 9 result, week 5 panel")
_assert("sign-out returns the model to demo and clears the callout",
        probe.get("afterUnbind", {}).get("mode") == "demo"
        and probe.get("afterUnbind", {}).get("callout") == "")

_section("2 · the assessed callout says what the ruling requires")

a = probe.get("assessed", {})
_assert("the callout renders", a.get("draws") is True)
_assert("the eyebrow is SKUNK OF THE WEEK",
        a.get("eyebrow") == "SKUNK OF THE WEEK", str(a.get("eyebrow")))
_assert("it reads '{skunked} got skunked by {opponent}'",
        a.get("line") == "Gravy Train got skunked by The Braintrust",
        str(a.get("line")))
_assert("the point differential is shown exactly",
        a.get("margin") == "30.64", str(a.get("margin")))
_assert("the final score is winner–loser",
        a.get("final") == "Final: 132.47–101.83", str(a.get("final")))
_assert("the $10 Skunk effect is stated",
        a.get("fee") == "$10 Skunk", str(a.get("fee")))
_assert("with the exact cents behind it",
        a.get("feeCents") == "1000", str(a.get("feeCents")))

_section("3 · it integrates into The Week, and adds no fourth module")

_assert("the callout appears in the built Week panel", a.get("inPanel") is True)
_assert("the locked three modules are untouched",
        a.get("modules") == ["yahoo", "bets", "pools"], str(a.get("modules")))
_assert("the callout is not itself a module", a.get("isModule") is False)
_assert("and it leads the scroll, above the Yahoo module",
        a.get("beforeYahoo") is True)

_section("4 · decimal precision follows the authoritative values")

p = probe.get("precision", {})
_assert("two-decimal scoring is shown to two decimals",
        p.get("two", {}).get("margin") == "30.64"
        and p.get("two", {}).get("final") == "Final: 132.47–101.83",
        json.dumps(p.get("two")))
_assert("one-decimal scoring is NOT padded to two",
        p.get("one", {}).get("margin") == "4.1"
        and p.get("one", {}).get("final") == "Final: 110.5–106.4",
        json.dumps(p.get("one")))
_assert("whole-number scoring invents no decimals at all",
        p.get("zero", {}).get("margin") == "30"
        and p.get("zero", {}).get("final") == "Final: 130–100",
        json.dumps(p.get("zero")))

_section("5 · an exact-margin tie splits one contribution, and says so")

t = probe.get("tie", {})
_assert("a tie still draws one callout", t.get("draws") is True)
_assert("it shows this GM's SHARE, not the whole $10",
        t.get("fee") == "500", str(t.get("fee")))
_assert("and states that the single Skunk is split",
        t.get("saysSplit") is True and t.get("count") == 2,
        f"{t.get('count')} tied")

_section("6 · the browser never decides who was skunked")

import re  # noqa: E402


def _strip(src: str) -> str:
    src = re.sub(r"/\*[\s\S]*?\*/", " ", src)
    return re.sub(r"^\s*//.*$", " ", src, flags=re.MULTILINE)


_model = _strip(open(os.path.join(ROOT, "web", "js", "skunk-model.js"),
                     encoding="utf-8").read())
_week = _strip(open(os.path.join(ROOT, "web", "js", "week.js"),
                    encoding="utf-8").read())

_assert("the client computes no margin of its own",
        "home_score" not in _model and "away_score" not in _model
        and "home_score" not in _week,
        "the differential is served, not derived")
_assert("and runs no comparison to pick a loser",
        not re.search(r"Math\.(max|min)\s*\(|largest|worst", _model),
        "selection is the engine's")
_assert("the model reads the served entries and nothing else",
        "SERVED.entries" in _model)
_assert("only the session module reaches the network",
        "fetch(" not in _model and "fetch(" not in _week)

_app_js = [os.path.join(dp, f)
           for dp, _, fs in os.walk(os.path.join(ROOT, "web", "js"))
           for f in fs if f.endswith(".js")]
_offenders = sorted(os.path.basename(q) for q in _app_js
                    if re.search(r"\bfetch\s*\(", _strip(
                        open(q, encoding="utf-8").read())))
_assert("no second network door was opened",
        _offenders == ["session.js"], str(_offenders))


# ══ 7 · the browser ═════════════════════════════════════════════════════════

_section("7 · the browser, as an ordinary GM")

from test_support_app_server import AppServer, GM_EMAIL, PASSWORD  # noqa: E402

with AppServer(seed_skunk_week=True) as server:
    result = subprocess.run(
        ["node", os.path.join("web", "tests", "wp6a_skunk_browser.mjs"),
         *server.browser_args(authenticate_as=GM_EMAIL)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT, timeout=900)

passed = result.stdout.count("[PASS]")
failed = result.stdout.count("[FAIL]")
if failed or result.returncode != 0:
    print(result.stdout[-6000:])
    if result.stderr:
        print(result.stderr[-2000:])
_assert("the browser suite is green",
        failed == 0 and result.returncode == 0,
        f"{passed} PASS / {failed} FAIL, exit {result.returncode}")


print("\n" + "=" * 78)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("WP6A SKUNK UI — all assertions PASSED")