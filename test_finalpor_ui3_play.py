#!/usr/bin/env python3
"""
FINAL POR · UI-3A/B/C §27 — the Play carousels and odds refresh, driven in a real browser.

DRIVER ONLY. It starts the application against a disposable database and hands
the origin to `web/tests/finalpor_ui3_play.mjs`, which makes every
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
    python test_finalpor_ui3_play.py
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
print("FINAL POR UI-3 - Play carousels, odds refresh and market microcopy")
print("=" * 70)

# ── UI-3D runs FIRST, and needs no server ───────────────────────────────────
#
# §27D's three sentences are pure functions of served numbers, so they are
# certified as a component suite: a browser can only show the ONE sentence the
# live board happened to produce, and §27D's prohibition ("do not call −118 a
# heavy favorite") names a case no live board is guaranteed to serve.
_micro = subprocess.run(
    ["node", os.path.join("web", "tests", "finalpor_ui3_microcopy.mjs")],
    cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    errors="replace")
sys.stdout.write(_micro.stdout)
if _micro.stderr.strip():
    sys.stdout.write(_micro.stderr[-2000:])
_assert("UI-3D market microcopy",
        _micro.returncode == 0 and _micro.stdout.count("[FAIL]") == 0,
        f"{_micro.stdout.count('[PASS]')} PASS / "
        f"{_micro.stdout.count('[FAIL]')} FAIL, exit {_micro.returncode}")

with AppServer(seed_pool_slate=True) as server:
    env = dict(os.environ)
    env.update({"FS_TEST_ORIGIN": server.origin,
                "FS_TEST_AUTH_EMAIL": GM_EMAIL,
                "FS_TEST_AUTH_PASSWORD": PASSWORD})
    proc = subprocess.run(
        ["node", os.path.join("web", "tests", "finalpor_ui3_play.mjs")],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stdout.write(proc.stderr[-2000:])
    passed = proc.stdout.count("[PASS]")
    failed = proc.stdout.count("[FAIL]")
    _assert("UI-3 Play carousels and refresh",
            proc.returncode == 0 and failed == 0,
            f"{passed} PASS / {failed} FAIL, exit {proc.returncode}")

print("\n" + "=" * 70)
if _failures:
    print(f"FAILED: {len(_failures)} run(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("FINAL POR UI-3 - all assertions PASSED")
