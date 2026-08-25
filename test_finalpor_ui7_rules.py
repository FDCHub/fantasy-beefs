#!/usr/bin/env python3
"""
FINAL POR · UI-7 Rules and League Settings, driven in a real browser.

§24 gives the Rules four groups -- The Basics, Your Credits, Weekly Play, Season
Play -- and three paragraphs of approved copy that must appear verbatim. §23
gives League Settings a three-column table: VC ALLOCATION | AMOUNT | RATIO TO
WEEKLY MINIMUM, seven rows, four in-season read-only figures beneath it and five
Season Rules beneath those.

WHY A BROWSER IS THE ONLY PLACE THIS CAN BE SETTLED. "RATIO TO WEEKLY MINIMUM"
is twenty-three characters and does not fit one line at any certified width, so
whether the third column keeps its NAME is a measurement rather than a reading.
UI-2 established how that failure presents on this product: not as overflow,
which is visible, but as an ellipsed header, which is not -- the page looks
correct and a column silently loses its heading. Every header cell is measured
scrollWidth against clientWidth, and the computed `text-overflow` is read rather
than assumed.

IT ALSO GUARDS A SEAM. §23 renamed Standard Pool Bet to Prop Pool Entry while
the settings response, the command and the server's bound all still call it
`pool-bet`. One mapping reconciles them, and if it is lost the only editable
setting in the product silently becomes read-only -- with the row still
rendering perfectly, so nothing else would notice.

DRIVER ONLY. It starts the application against a disposable database and hands
the origin to `web/tests/finalpor_ui7_rules.mjs`, which makes every assertion
inside a headless Chrome at 320x568, 375x667 and 390x844.

    python test_finalpor_ui7_rules.py
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_app_server import GM_EMAIL, PASSWORD, AppServer  # noqa: E402

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


print("=" * 70)
print("FINAL POR CLOSE-X - upper-left everywhere, and what it must not break")
print("=" * 70)

# A FINAL POR SEASON, because §23's table cannot be derived from a legacy one:
# every ratio is taken against the Weekly Minimum, and a legacy stop carries
# constants rather than a weekly figure. The flag is opt-in so no other suite's
# fixture moves -- see `_SEED_FINAL_POR_ECONOMY`.
with AppServer(seed_pool_slate=True, seed_final_por=True) as server:
    env = dict(os.environ)
    env.update({"FS_TEST_ORIGIN": server.origin,
                "FS_TEST_AUTH_EMAIL": GM_EMAIL,
                "FS_TEST_AUTH_PASSWORD": PASSWORD})
    proc = subprocess.run(
        ["node", os.path.join("web", "tests", "finalpor_ui7_rules.mjs")],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stdout.write(proc.stderr[-2000:])
    passed = proc.stdout.count("[PASS]")
    failed = proc.stdout.count("[FAIL]")
    _assert("UI-7 Rules & League Settings",
            proc.returncode == 0 and failed == 0,
            f"{passed} PASS / {failed} FAIL, exit {proc.returncode}")

print("\n" + "=" * 70)
if _failures:
    print(f"FAILED: {len(_failures)} run(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("FINAL POR CLOSE-X - all assertions PASSED")
