#!/usr/bin/env python3
"""
test_s8_p4c2_action_browser.py — Sprint 8 P4C-2 · Action in a real browser.

DRIVER ONLY. It starts seven differently-seeded application servers and runs
`web/tests/p4c2_action_browser.mjs` against each as the seeded GM. The
assertions live in the browser suite; this file decides which situation each run
sees, because the situation is the only thing separating these seven claims:

    empty       zero proposals — genuine empty rails and, above all, NO demo
                cards on a signed-in GM's page;
    issuer      a Locked proposal the GM sent — WAITING;
    recipient   a Locked proposal the GM received — ACTION REQUIRED, Incoming;
    countered   the opponent countered — the decision comes BACK to the GM, and
                the sections reverse while the direction does not;
    accepted    accepted — LIVE, escrow migrated;
    declined    declined — terminal, and Held restored;
    dynamic     a real Dynamic proposal — mode and terms from the governing
                backend.

WHY SEVEN SERVERS AND NOT SEVEN PHASES OF ONE. These are states, not steps: a
GM cannot simultaneously have nothing and have a countered wager, and a run that
advanced through them in order could only assert the last one honestly. Separate
disposable databases keep each claim independent and order-free.

EVERY SHAPE IS SEEDED THROUGH THE FUNDED LIFECYCLE, never by writing rows — so
what the browser certifies is what the real protocol produces.
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
    COMMISSIONER_EMAIL, GM_EMAIL, PASSWORD, AppServer,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _run(shape: str, label: str, *, as_email: str = GM_EMAIL) -> None:
    print(f"\n── {label} " + "─" * max(0, 58 - len(label)))
    with AppServer(action_shape=shape) as server:
        env = dict(os.environ)
        env.update({"FS_TEST_ORIGIN": server.origin,
                    "FS_TEST_AUTH_EMAIL": as_email,
                    "FS_TEST_AUTH_PASSWORD": PASSWORD})
        proc = subprocess.run(
            ["node", os.path.join("web", "tests", "p4c2_action_browser.mjs"),
             f"--mode={shape}"],
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
print("S8-P4C-2 — Action browser certification")
print("=" * 70)

# A GM WITH NO HISTORY, not the fixture GM with none left.
_run("empty", "A · empty GM draws no demo cards",
     as_email="empty@certification.test")
_run("issuer", "B · issued Locked proposal sits in WAITING")
_run("recipient", "C · received proposal is Incoming in ACTION REQUIRED")
_run("countered", "D · counter reverses decision ownership")
_run("accepted", "E · accepted proposal is LIVE")
_run("declined", "F · declined proposal is terminal, escrow restored")
_run("dynamic", "G · Dynamic renders from the governing backend")

print("\n" + "=" * 70)
if _failures:
    print(f"FAILED: {len(_failures)} run(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4C-2 ACTION BROWSER — all assertions PASSED")