#!/usr/bin/env python3
"""
test_s8_p4b3r_browser.py — Sprint 8 P4B-3R · final browser acceptance.

DRIVER ONLY. It starts three differently-seeded application servers and runs
`web/tests/p4b3_browser_acceptance.mjs` against each as the seeded league
commissioner. The assertions live in the browser suite; this file decides which
fixture each run sees, because the fixture is the only thing that separates
these three claims:

    editable  a drawn week-5 slate and an unfrozen Pool entry — the successful
              commissioner update, and the four-slot slate;
    frozen    the governed frozen state, seeded as the season's first
              collection would write it — the refusal;
    undrawn   the plain fixture, with no slate — the regression that
              production still renders nothing rather than the launch four.

WHY THREE SERVERS AND NOT THREE PHASES OF ONE. Freezing is a one-way door: the
setter refuses every change after it, so a run that froze mid-way could not go
back to certify the editable path. Separate disposable databases keep each
claim independent and order-free.
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

from test_support_app_server import (  # noqa: E402
    COMMISSIONER_EMAIL, PASSWORD, AppServer,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _run(mode: str, label: str, **fixture) -> None:
    print(f"\n── {label} " + "─" * max(0, 60 - len(label)))
    with AppServer(**fixture) as server:
        env = dict(os.environ)
        env.update({"FS_TEST_ORIGIN": server.origin,
                    "FS_TEST_AUTH_EMAIL": COMMISSIONER_EMAIL,
                    "FS_TEST_AUTH_PASSWORD": PASSWORD})
        proc = subprocess.run(
            ["node", os.path.join("web", "tests", "p4b3_browser_acceptance.mjs"),
             f"--mode={mode}"],
            cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        sys.stdout.write(proc.stdout)
        if proc.stderr.strip():
            sys.stdout.write(proc.stderr[-1500:])
        passed = proc.stdout.count("[PASS]")
        failed = proc.stdout.count("[FAIL]")
        _assert(label, proc.returncode == 0 and failed == 0,
                f"{passed} PASS / {failed} FAIL, exit {proc.returncode}")


print("=" * 70)
print("S8-P4B-3R — final browser acceptance")
print("=" * 70)

_run("editable", "commissioner update and drawn slate", seed_pool_slate=True)
_run("frozen", "frozen entry refused by the server",
     seed_pool_slate=True, freeze_pool_entry=True)
_run("undrawn", "undrawn week renders nothing")

print("\n" + "=" * 70)
if _failures:
    print(f"FAILED: {len(_failures)} run(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4B-3R BROWSER ACCEPTANCE — all assertions PASSED")