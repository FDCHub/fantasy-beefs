#!/usr/bin/env python3
"""
run_pg_suites.py — run the PostgreSQL suites, each against a fresh database.

WHY A RUNNER EXISTS AT ALL. The PG suites split into two harness families with
incompatible expectations about the database they are handed:

  SCHEMA-OWNING   creates its own tables and tears down what it created. Runs
                  happily in a database that already has a schema.
  EMPTY-ONLY      refuses outright unless the database is empty, so that
                  "ownership of every table is unambiguous and teardown can
                  safely drop the full schema it created".

Both guards are right, and neither can be satisfied by one long-lived database:
the first suite to run leaves 61 tables behind and every EMPTY-ONLY suite after
it refuses. Rather than weaken a guard — they exist precisely because these
suites TRUNCATE and DROP — this gives each suite its own database and drops it
afterwards.

THE SAFETY RULES ARE THE HARNESSES' OWN, KEPT: every database created here is
named `<base>_test_<suite>`, which satisfies the `_test` substring rule the
harnesses check before they will drop anything, and every one is dropped when
the suite finishes.

USAGE

    export TEST_DATABASE_URL=postgresql://user:pass@host:port/fantasy_p5_test
    python run_pg_suites.py                  # every test_*_pg.py
    python run_pg_suites.py --only spec1     # substring filter
    python run_pg_suites.py --keep           # leave databases for inspection

The URL's own database must already exist; it is used as the ADMIN connection
from which the per-suite databases are created and dropped. It is never itself
written to by a suite.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _admin_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        sys.exit("TEST_DATABASE_URL is not set. This runner fails closed "
                 "rather than silently falling back to SQLite.")
    if not url.startswith("postgresql://"):
        sys.exit(f"TEST_DATABASE_URL must be a plain postgresql:// URL; got "
                 f"{url.split('://')[0]}://. The suites check the scheme.")
    return url


def _db_name_for(suite: str) -> str:
    """A per-suite database name that keeps the harnesses' `_test` rule."""
    stem = re.sub(r"[^a-z0-9]+", "_", suite.lower())
    stem = stem.replace("test_", "").replace("_pg_py", "")[:40].strip("_")
    return f"fs_{stem}_test"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="substring filter")
    parser.add_argument("--keep", action="store_true",
                        help="do not drop the per-suite databases")
    args = parser.parse_args()

    from sqlalchemy import create_engine, text

    admin_url = _admin_url()
    base, _, admin_db = admin_url.rpartition("/")

    suites = sorted(os.path.basename(p)
                    for p in glob.glob(os.path.join(ROOT, "test_*_pg.py")))

    # WP5 — THREE SUITES NEED THIS HARNESS AND DO NOT CARRY THE `_pg` SUFFIX.
    # The glob above is a naming convention, and these three predate or sit
    # outside it while calling `setup_postgres_test_db()` exactly like the rest.
    # Left out, they were invisible to the one command the RUNBOOK gives for
    # "run the PostgreSQL suites" — so a developer could run this, see every
    # suite pass, and never learn that three of them had not been run at all.
    #
    # Named rather than detected by grepping for the import: an explicit list
    # fails loudly when a file is renamed, where a scan would silently find
    # nothing and report success.
    for extra in ("test_spec1_2a_gate.py",
                  "test_b6_group_f_legacy_closure.py",
                  "test_s8_p5_postgres_hardening.py"):
        path = os.path.join(ROOT, extra)
        if not os.path.isfile(path):
            sys.exit(f"{extra} is named as a PostgreSQL suite but is missing. "
                     f"Fix the list in run_pg_suites.py rather than dropping "
                     f"the suite from the gate.")
        if extra not in suites:
            suites.append(extra)
    suites = sorted(suites)

    if args.only:
        suites = [s for s in suites if args.only in s]
    if not suites:
        sys.exit("no PostgreSQL suites matched")

    # AUTOCOMMIT: CREATE DATABASE and DROP DATABASE cannot run inside a
    # transaction block, and SQLAlchemy opens one by default.
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    results: list[tuple[str, int, float, str]] = []
    print("=" * 78)
    print(f"PostgreSQL suites — {len(suites)} to run, one fresh database each")
    print("=" * 78)

    for suite in suites:
        db_name = _db_name_for(suite)
        suite_url = f"{base}/{db_name}"
        started = time.time()

        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))

        env = dict(os.environ)
        env["TEST_DATABASE_URL"] = suite_url
        # UTF-8 FOR THE CHILD'S STDOUT. Several suites print governed symbols —
        # `→` in state transitions, `−` in signed money — and on
        # Windows a piped stdout defaults to the ANSI codepage, which cannot
        # encode them. The suite then dies with a UnicodeEncodeError that looks
        # exactly like a PostgreSQL failure and is nothing of the kind.
        #
        # Set here rather than by editing the suites: the console encoding is a
        # property of how they are RUN, and the newer suites already reconfigure
        # their own streams for the same reason.
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run([sys.executable, suite], cwd=ROOT, env=env,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        elapsed = time.time() - started

        tail = ""
        if proc.returncode != 0:
            lines = [ln for ln in (proc.stdout + proc.stderr).splitlines()
                     if ln.strip()]
            fails = [ln for ln in lines if "[FAIL]" in ln or "ERROR" in ln]
            tail = (fails[0] if fails else (lines[-1] if lines else ""))[:150]

        results.append((suite, proc.returncode, elapsed, tail))
        mark = "PASS" if proc.returncode == 0 else f"FAIL({proc.returncode})"
        print(f"  [{mark:8s}] {suite:<48s} {elapsed:5.1f}s"
              + (f"\n              {tail}" if tail else ""))

        if not args.keep:
            with admin.connect() as conn:
                conn.execute(text(
                    f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))

    passed = sum(1 for _, code, _, _ in results if code == 0)
    print("\n" + "=" * 78)
    print(f"{passed} / {len(results)} PostgreSQL suites passed")
    failed = [(s, t) for s, code, _, t in results if code != 0]
    if failed:
        print("\nFAILED:")
        for suite, tail in failed:
            print(f"  - {suite}")
            if tail:
                print(f"      {tail}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())