#!/usr/bin/env python3
"""
test_wp6c_pool_claim_browser.py — WP6C · the Pool pick, driven from Rev 4.2.

DRIVER ONLY. Two runs against the same fixture, differing only in who is signed
in — an ordinary GM and the commissioner. Both are ordinary players here: a
Pool pick is a competitive choice and rank confers nothing, so the two identities
must behave IDENTICALLY, and a divergence would mean the commissioner exemption
that S8-P4C-4 removed had crept back in through the interface.

WHAT THE NODE SUITE ASSERTS is that a GM using the shipped controls produces a
row `betting/pool_settlement` will pay — verified by re-reading the
authoritative slate after the press, never by trusting the confirmation the page
drew for itself.
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
                                  "wp6c_pool_claim_browser.mjs")],
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
print("WP6C — the governed Pool pick, in a browser")
print("=" * 70)

_run("an ordinary GM submits a governed Pool claim", GM_EMAIL)
_run("and so does a commissioner, as an ordinary player", COMMISSIONER_EMAIL)

print("\n" + "=" * 70)
if _failures:
    print(f"FAILED: {len(_failures)} run(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("WP6C POOL CLAIM BROWSER — all assertions PASSED")
