#!/usr/bin/env python3
"""
test_s8_p4b2_binding.py — Sprint 8 P4B-2 · production accounting binding.

THREE THINGS THIS PROVES, AND THEY NEED DIFFERENT TOOLS.

  1. STRUCTURE, by parsing source: the shell reads its league from /auth/me and
     nowhere else, and no hard-coded league id survives anywhere in the app.
  2. MODE DISCIPLINE, by driving the models directly: a refused slice enters
     UNAVAILABLE, never DEMO — which is the single property that stops a GM
     being shown the prototype's money.
  3. BEHAVIOUR, in two real browser sessions: an ordinary GM sees a real Ledger
     and an unavailable commissioner surface; a league commissioner sees real
     cards and a real reconciliation, and the same GM's figure agrees across
     both surfaces to the cent.

The browser halves run against the real application on the P4B-1 fixture, so
every money assertion below is posted ledger state rather than a constant.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_app_server import (  # noqa: E402
    COMMISSIONER_EMAIL, GM_EMAIL, PASSWORD, AppServer,
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


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", " ", source, flags=re.MULTILINE)


print("=" * 70)
print("S8-P4B-2 — production accounting binding")
print("=" * 70)


# ── 1 · Structure: context comes from the server, never from a constant ──────

_section("1 · The acting league comes from /auth/me and nowhere else")

SHELL = _read("web", "js", "shell.js")
SHELL_CODE = _strip_comments(SHELL)
APP_JS = [os.path.join(dp, f)
          for dp, _dn, fn in os.walk(os.path.join(ROOT, "web", "js"))
          for f in fn if f.endswith(".js")]
APP_CODE = "\n".join(_strip_comments(open(p, encoding="utf-8").read())
                     for p in APP_JS)

_assert("the shell reads acting_league_id from the identity",
        "acting_league_id" in SHELL_CODE)
_assert("and refuses to act when the context is ambiguous",
        "acting_context_ambiguous" in SHELL_CODE)
_assert("NO hard-coded default league id exists anywhere in the app",
        not re.search(r"DEFAULT_LEAGUE_ID|leagueId\s*=\s*1\b|league_id\s*=\s*1\b",
                      APP_CODE),
        "a production fallback league survives")
_assert("no module fabricates a league id from a literal",
        not re.search(r"/league/1/", APP_CODE))
_assert("the shell loads production data before mounting the application",
        SHELL_CODE.index("bindAuthoritativeData") < SHELL_CODE.index("mountApplication()")
        if "bindAuthoritativeData" in SHELL_CODE else False)
_assert("sign-out clears production state",
        "clearAuthoritativeData" in SHELL_CODE
        and "clearProductionData" in SHELL_CODE)
_assert("no module outside session.js reaches the network",
        sorted(os.path.basename(p) for p in APP_JS
               if re.search(r"\bfetch\s*\(", _strip_comments(
                   open(p, encoding="utf-8").read()))) == ["session.js"])
# A URL, not the function name. `TRIAL_BALANCE_SEAM` legitimately NAMES
# `ledger/ledger.py · trial_balance()` as the computation while declaring
# `endpoint: null` — that is the seam doing its job, and a check that tripped
# on it would be punishing the documentation of the boundary it is enforcing.
_assert("no frontend module names a global integrity ENDPOINT",
        not re.search(r"['\"`]/ledger/integrity|/ledger/trial[-_]balance", APP_CODE))
_assert("and the trial-balance seam still declares no endpoint",
        re.search(r"TRIAL_BALANCE_SEAM[\s\S]{0,600}?endpoint:\s*null", APP_CODE)
        is not None)


# ── 2 · Mode discipline, driven directly ─────────────────────────────────────

_section("2 · A refused slice enters UNAVAILABLE, never DEMO")

NODE_PROBE = r"""
const base = %s;
const L = await import(base + 'ledger-model.js');
const C = await import(base + 'commissioner-model.js');
const V = await import(base + 'commissioner.js');
const LV = await import(base + 'ledger.js');

const out = { demo: {}, unavailable: {}, bound: {} };

out.demo.ledgerMode = L.ledgerMode();
out.demo.commMode = C.commissionerMode();
out.demo.cards = C.gmPositions().length;

L.markLedgerUnavailable();
C.markCommissionerUnavailable();
out.unavailable.ledgerMode = L.ledgerMode();
out.unavailable.commMode = C.commissionerMode();
out.unavailable.cards = C.gmPositions().length;
const area = V.commissionerArea();
out.unavailable.areaHasMoney = area.includes('data-exact-cents');
out.unavailable.sections = (area.match(/data-state="unavailable"/g) || []).length;
out.unavailable.leaksNames = /Gravy|Braintrust|Destroyers/i.test(area);
out.unavailable.ledgerHasPending = LV.buildLedgerPanel().includes('is-pending');

L.bindLedger({available_cents:6500,in_play_cents:2800,min_reserve_cents:9000,
  expired_min_cents:800,receivable_cents:0,season_advance_cents:22000,
  topoff_issued_cents:4000,current_settle_cents:-6900,
  held_open_challenges_cents:0,weekly_min_live_cents:1000},
  {economy_stop:{min_reserve_cents:14000,reserve_cents:8000}});
out.bound.settle = L.reconciliation().currentSettleCents;
out.bound.server = L.boundCurrentSettleCents();
out.bound.winningsResolved = L.seasonWinningsResolved();
const adv = L.advances();
out.bound.openingLeg = adv.regularSeasonMinimumCents;
out.bound.champReserve = adv.playoffsChampionshipCents;
out.bound.tvs = adv.totalVirtualStakesCents;

console.log(JSON.stringify(out));
"""

url = "file:///" + os.path.join(ROOT, "web", "js").replace("\\", "/").lstrip("/") + "/"
import json  # noqa: E402

proc = subprocess.run(["node", "--input-type=module", "-e",
                       NODE_PROBE % json.dumps(url)],
                      capture_output=True, text=True, encoding="utf-8",
                      errors="replace", cwd=ROOT)
if proc.returncode != 0:
    print(proc.stderr[:1500])
probe = json.loads(proc.stdout) if proc.returncode == 0 else {}

_assert("the models default to demo for isolated review",
        probe.get("demo", {}).get("ledgerMode") == "demo"
        and probe.get("demo", {}).get("commMode") == "demo")
_assert("demo still carries the illustrative twelve",
        probe.get("demo", {}).get("cards") == 12)

u = probe.get("unavailable", {})
_assert("a refused slice enters unavailable, not demo",
        u.get("ledgerMode") == "unavailable" and u.get("commMode") == "unavailable")
_assert("unavailable shows NO commissioner cards", u.get("cards") == 0)
_assert("and NO money anywhere in the commissioner area",
        u.get("areaHasMoney") is False)
_assert("all three commissioner sections declare themselves unavailable",
        u.get("sections") == 3, str(u.get("sections")))
_assert("and no prototype GM name leaks", u.get("leaksNames") is False)
_assert("the Ledger draws unresolved rather than figures",
        u.get("ledgerHasPending") is True)

b = probe.get("bound", {})
_assert("bound Current Settle equals the server's exactly",
        b.get("settle") == b.get("server") == -6900,
        f"{b.get('settle')} vs {b.get('server')}")
_assert("season winnings stays unresolved when figures are real",
        b.get("winningsResolved") is False)
_assert("the opening split is the Economy Stop's $140/$80",
        b.get("openingLeg") == 14000 and b.get("champReserve") == 8000,
        f"{b.get('openingLeg')}/{b.get('champReserve')}")
_assert("Total Virtual Stakes is $260", b.get("tvs") == 26000, str(b.get("tvs")))


# ── 3 · Two real browser sessions ────────────────────────────────────────────

_section("3 · Real browser: ordinary GM, then league commissioner")


def _run_browser(script: str, email: str, label: str) -> None:
    with AppServer() as server:
        env = dict(os.environ)
        env.update({"FS_TEST_ORIGIN": server.origin,
                    "FS_TEST_AUTH_EMAIL": email,
                    "FS_TEST_AUTH_PASSWORD": PASSWORD})
        proc = subprocess.run(["node", os.path.join("web", "tests", script)],
                              cwd=ROOT, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        sys.stdout.write(proc.stdout)
        if proc.stderr.strip():
            sys.stdout.write(proc.stderr[-1500:])
        passed = proc.stdout.count("[PASS]")
        failed = proc.stdout.count("[FAIL]")
        _assert(label, proc.returncode == 0 and failed == 0,
                f"{passed} PASS / {failed} FAIL, exit {proc.returncode}")


_run_browser("p4b2_gm_browser.mjs", GM_EMAIL,
             "the ordinary-GM session is green")
_run_browser("p4b2_commissioner_browser.mjs", COMMISSIONER_EMAIL,
             "the commissioner session is green")


print("\n" + "=" * 70)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4B-2 BINDING — all assertions PASSED")