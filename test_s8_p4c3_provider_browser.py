#!/usr/bin/env python3
"""
test_s8_p4c3_provider_browser.py — Sprint 8 P4C-3 · League and Week in a browser.

DRIVER ONLY. Two differently-seeded application servers, because the two claims
cannot both be true of one database:

    bound      the league states a current week and has persisted matchups —
               the page shows the real identity, week, orientation and scores;
    pending    the league is provider-bound but no refresh has ever stated
               anything — the page says so, and shows NO illustrative league,
               NO fixture matchup and NO 14-7 record.

THE SECOND RUN IS THE IMPORTANT ONE. Yahoo credentials are absent here, so
"the provider has told us nothing" is the state a real deployment meets first.
A page that answers it with the fixture is indistinguishable from a working one
and every figure on it belongs to someone else.
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

from test_support_app_server import AppServer, GM_EMAIL, PASSWORD  # noqa: E402

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _run(mode: str, label: str, **fixture) -> None:
    print(f"\n── {label} " + "─" * max(0, 56 - len(label)))
    with AppServer(**fixture) as server:
        env = dict(os.environ)
        env.update({"FS_TEST_ORIGIN": server.origin,
                    "FS_TEST_AUTH_EMAIL": GM_EMAIL,
                    "FS_TEST_AUTH_PASSWORD": PASSWORD})
        proc = subprocess.run(
            ["node", os.path.join("web", "tests", "p4c3_provider_browser.mjs"),
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
print("S8-P4C-3 — League and Week browser certification")
print("=" * 70)

_run("bound", "league states a week and has matchups", provider_week=5)
_run("pending", "no provider refresh — nothing illustrative appears",
     provider_week=None)

print("\n" + "=" * 70)
if _failures:
    print(f"FAILED: {len(_failures)} run(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4C-3 PROVIDER BROWSER — all assertions PASSED")
