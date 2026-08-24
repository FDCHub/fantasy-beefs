#!/usr/bin/env python3
"""FINAL POR UI FREEZE CANDIDATE — the rendered guard.

Runs `web/tests/finalpor_freeze_browser.mjs` in a real headless Chrome at the
three locked phone sizes.

WHY THIS TIER EXISTS. The rulings it certifies are all statements about
COMPOSITION — that a region is spent rather than left half empty, that nothing
is drawn on top of anything else, that a card says enough to be read without
opening a sheet. None of those can be answered from source, and the pass that
tried to answer them from geometry alone certified a screen the owner rejected
on sight.

IT NEEDS THE SHOWCASE, NOT THE FIXTURE. Every ruling here is about a POPULATED
surface: four lifecycle rails each carrying a card, an incoming offer to price,
and a completed week to recap. The S7 certification fixture has one wager and
no settled week, so it cannot answer these questions — this suite therefore
requires `FS_TEST_ORIGIN` to name an application serving the seeded Demo, and
refuses rather than reporting a pass it did not earn.
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

origin = os.environ.get("FS_TEST_ORIGIN", "").strip()
if not origin:
    print("FS_TEST_ORIGIN is required: it must name an application serving the")
    print("seeded Demo showcase (python -m demo.seed against its database).")
    print("The rendered freeze guard cannot run without one and will not")
    print("report a pass it did not earn.")
    raise SystemExit(2)

env = dict(os.environ)
env["FS_TEST_ORIGIN"] = origin

result = subprocess.run(
    ["node", os.path.join("web", "tests", "finalpor_freeze_browser.mjs")],
    cwd=ROOT, env=env, check=False,
)

print()
print("FINAL POR FREEZE: all rendered assertions passed" if result.returncode == 0
      else "FINAL POR FREEZE: FAILED")
sys.exit(result.returncode)
