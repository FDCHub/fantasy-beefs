#!/usr/bin/env python3
"""
test_s8_p4c4_pool_pick_browser.py — Sprint 8 P4C-4 · Pool pick authority in a browser.

DRIVER ONLY. Two runs against the same fixture, differing only in WHO IS SIGNED
IN — which is the whole point: the repair is about identity, and the two
identities that must behave identically here are the ones that behaved
differently before.

    gm             an ordinary GM cannot pick for another team;
    commissioner   neither can a commissioner — the exemption that used to let
                   them is gone — and they can still pick for their own team.

Each run also re-reads the authoritative Pool state after the refusal and
asserts it is byte-identical, because a 403 that had already written a row
would satisfy a status check and still have changed someone's week.
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


def _run(label: str, email: str) -> None:
    print(f"\n── {label} " + "─" * max(0, 54 - len(label)))
    with AppServer(seed_pool_slate=True) as server:
        env = dict(os.environ)
        env.update({"FS_TEST_ORIGIN": server.origin,
                    "FS_TEST_AUTH_EMAIL": email,
                    "FS_TEST_AUTH_PASSWORD": PASSWORD})
        proc = subprocess.run(
            ["node", os.path.join("web", "tests",
                                  "p4c4_pool_pick_browser.mjs")],
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
print("S8-P4C-4 — Pool pick authority, in a browser")
print("=" * 70)

_run("an ordinary GM cannot pick for another team", GM_EMAIL)
_run("nor can a commissioner", COMMISSIONER_EMAIL)

print("\n" + "=" * 70)
if _failures:
    print(f"FAILED: {len(_failures)} run(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4C-4 POOL PICK BROWSER — all assertions PASSED")