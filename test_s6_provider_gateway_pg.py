#!/usr/bin/env python3
"""
test_s6_provider_gateway_pg.py — Sprint 6 provider gateway suite (PostgreSQL).

A THIN WRAPPER, DELIBERATELY. The Sprint 6 gates C-1 through C-17 live in
`providers/certify/run.py`, because §17 requires a standalone offline
certification harness that can be run and reported on its own. Duplicating them
here would create two definitions of "Sprint 6 is green" that could disagree.

This file exists so the gateway is discoverable by the repository's own test
convention — a `test_*_pg.py` script run standalone against TEST_DATABASE_URL,
reporting [PASS]/[FAIL] lines and exiting non-zero on failure — exactly like
every other accepted suite. Anyone sweeping test_*.py picks Sprint 6 up.

USAGE:
    export TEST_DATABASE_URL="postgresql://.../fantasy_test"
    python test_s6_provider_gateway_pg.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("\n=== S6 provider gateway certification (PostgreSQL) ===")
    print("    delegating to providers/certify/run.py — the §17 gate\n")

    from providers.certify import run as certify

    exit_code = certify.main()

    # Re-emit each gate in the repository's [PASS]/[FAIL] assertion style, so a
    # sweep that counts those markers counts Sprint 6 the same way it counts
    # every accepted suite.
    print("\n--- gate summary in suite format ---")
    failures = []
    for result in certify.RESULTS:
        mark = "PASS" if result.passed else "FAIL"
        print(f"  [{mark}] {result.gate}: {result.title}")
        if not result.passed:
            failures.append(f"{result.gate}: {result.title}")

    print(f"\n  {len(failures)} failure(s)")
    for failure in failures:
        print(f"    FAILED: {failure}")
    if not failures:
        print("  ALL PASS")
    sys.exit(exit_code)