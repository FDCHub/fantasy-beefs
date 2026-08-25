#!/usr/bin/env python3
"""
FINAL POR · The universal close-X ruling, driven in a real browser.

Owner ruling, LOCKED: the close control is UPPER-LEFT, visually attached to the
active card, sheet, modal or detail view, everywhere in the application
including Wrap Up. It supersedes every older upper-right reference.

THE RULING IS POSITIONAL, AND THIS SUITE EXISTS TO PROVE IT IS ONLY POSITIONAL.
An absolutely-positioned control in a corner is exactly the shape that quietly
overlaps a title, steals a badge's space, pushes a sheet past the viewport or
grows an expansion past its bound. Each of those is measured on Play, Status and
Wrap Up at 320x568, 375x667 and 390x844 rather than assumed.

DRIVER ONLY. It starts the application against a disposable database and hands
the origin to `web/tests/finalpor_closex.mjs`, which makes every
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
    python test_finalpor_closex.py
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

with AppServer(seed_pool_slate=True) as server:
    env = dict(os.environ)
    env.update({"FS_TEST_ORIGIN": server.origin,
                "FS_TEST_AUTH_EMAIL": GM_EMAIL,
                "FS_TEST_AUTH_PASSWORD": PASSWORD})
    proc = subprocess.run(
        ["node", os.path.join("web", "tests", "finalpor_closex.mjs")],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stdout.write(proc.stderr[-2000:])
    passed = proc.stdout.count("[PASS]")
    failed = proc.stdout.count("[FAIL]")
    _assert("universal close-X",
            proc.returncode == 0 and failed == 0,
            f"{passed} PASS / {failed} FAIL, exit {proc.returncode}")

print("\n" + "=" * 70)
if _failures:
    print(f"FAILED: {len(_failures)} run(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("FINAL POR CLOSE-X - all assertions PASSED")
