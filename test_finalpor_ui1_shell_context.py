#!/usr/bin/env python3
"""
FINAL POR · UI-1 — shell context preservation, driven in a real browser.

DRIVER ONLY. It starts the application against a disposable database with a
drawn Pool slate and hands the origin to
`web/tests/finalpor_ui1_shell_context.mjs`, which makes the assertions inside a
headless Chrome.

WHY A BROWSER IS THE ONLY PLACE THIS CAN BE SETTLED. Every claim is about what
a reader sees after a local mutation — which tab is lit, where the carousel sits,
whether the page scrolls sideways. The defect it certifies was invisible to
every existing suite because all of them assert SERVER state, and the server was
never wrong: `mountApplication()` rebuilt the panels correctly and then
navigated the reader away from them.

USAGE:
    python test_finalpor_ui1_shell_context.py
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
print("FINAL POR UI-1 - shell context preservation, in a browser")
print("=" * 70)

with AppServer(seed_pool_slate=True) as server:
    env = dict(os.environ)
    env.update({"FS_TEST_ORIGIN": server.origin,
                "FS_TEST_AUTH_EMAIL": GM_EMAIL,
                "FS_TEST_AUTH_PASSWORD": PASSWORD})
    proc = subprocess.run(
        ["node", os.path.join("web", "tests", "finalpor_ui1_shell_context.mjs")],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stdout.write(proc.stderr[-2000:])
    passed = proc.stdout.count("[PASS]")
    failed = proc.stdout.count("[FAIL]")
    _assert("UI-1 shell context preservation",
            proc.returncode == 0 and failed == 0,
            f"{passed} PASS / {failed} FAIL, exit {proc.returncode}")

print("\n" + "=" * 70)
if _failures:
    print(f"FAILED: {len(_failures)} run(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("FINAL POR UI-1 - all assertions PASSED")
