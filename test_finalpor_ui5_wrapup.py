#!/usr/bin/env python3
"""
FINAL POR · UI-5 §29 — Wrap Up, driven in a real browser.

THIS SUITE IS CURRENTLY RED, AND THAT IS ITS PURPOSE. UI-5 is PARTIAL: the
collapsed layout is done and certified (36 assertions), and four named gaps
remain. Every failing line here is a measured gap, not a probe artefact — the
two probe defects found while writing it were fixed, and both are recorded in
`FINALPOR_ACCEPTANCE_MATRIX.md` because both produced false CONFIDENCE rather
than false failure.

    GAP 1  provider-backed Yahoo matchups carry no `data-card-action` and do
           not expand. Needs a data decision first: §29 wants a Fantasy
           Football Breakdown and also forbids fabricating one.
    GAP 2  the Prop Pool expansion has no Fantasy Football drivers section.
    GAP 3  the close control is UPPER-LEFT by a recorded owner ruling that
           explicitly superseded a §25 upper-right requirement. NOT flipped.
           A ruling is required.
    GAP 4  the fixture seeds no settled FantasyStakes wager, so that section's
           expansion is UNVERIFIED rather than passing. Belongs to WP-17.

Run it to see exactly what remains; it turns green when UI-5 lands.

── the original header ──────────────────────────────────────────────────────

FINAL POR · UI-5 §29 — Wrap Up, driven in a real browser.

DRIVER ONLY. It starts the application against a disposable database and hands
the origin to `web/tests/finalpor_ui5_wrapup.mjs`, which makes every
assertion inside a headless Chrome at the three certified phone widths.

WHY A BROWSER IS THE ONLY PLACE THIS CAN BE SETTLED. §26 is a list of
MEASUREMENTS: six columns present at 320px, no page-level horizontal scroll, no
header ellipsis, TEAM still usable, header and body on one grid, no bottom-nav
collision. A CSS rule that looks right and a table that fits are different
claims, and the entire risk in adding a sixth column to a 320px phone lives in
the gap between them.

THE `.mjs` CANNOT RUN BARE. Without `FS_TEST_ORIGIN` the page serves with no
backend, nothing mounts, and every geometry assertion passes against an empty
document — zero columns do not overflow. That is why the suite's first check is
that the application mounted, and why this driver exists.

USAGE:
    python test_finalpor_ui5_wrapup.py
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
print("FINAL POR UI-5 - Wrap Up sections and expansions, in a browser")
print("=" * 70)

with AppServer(seed_pool_slate=True) as server:
    env = dict(os.environ)
    env.update({"FS_TEST_ORIGIN": server.origin,
                "FS_TEST_AUTH_EMAIL": GM_EMAIL,
                "FS_TEST_AUTH_PASSWORD": PASSWORD})
    proc = subprocess.run(
        ["node", os.path.join("web", "tests", "finalpor_ui5_wrapup.mjs")],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stdout.write(proc.stderr[-2000:])
    passed = proc.stdout.count("[PASS]")
    failed = proc.stdout.count("[FAIL]")
    _assert("UI-5 Wrap Up",
            proc.returncode == 0 and failed == 0,
            f"{passed} PASS / {failed} FAIL, exit {proc.returncode}")

print("\n" + "=" * 70)
if _failures:
    print(f"FAILED: {len(_failures)} run(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("FINAL POR UI-5 - all assertions PASSED")
