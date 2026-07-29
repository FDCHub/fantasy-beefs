"""
test_support_crash.py — real-process crash injection for FR-8.7 test 6d.

INFRASTRUCTURE, NOT A TEST. No assertions of its own; the 6d scenario suites
import it.

WHY A SUBPROCESS. FR_8_7_TEST_6D_SPEC_FROZEN 6d-2 requires "forced transaction
termination with rollback, not a caught Python exception with no session
cleanup." A raised exception inside the test process proves nothing about
durability across process death: SQLAlchemy unwinds, the session may roll back
cleanly, and atexit handlers run. This module spawns a CHILD process that calls
settle_week and dies via os._exit() at a named boundary — no unwinding, no
rollback handler, no atexit. PostgreSQL sees the client vanish and aborts the
open transaction exactly as it would on a real crash.

TWO ROLES, ONE FILE. Imported, it is the parent-side helper. Executed as
__main__, it is the child that crashes. The parent spawns `python <this file>`.

INJECTION POINTS (line anchors re-verified at HEAD f230d33; the frozen spec's
anchors were at 21ec171 and have drifted +2 to +25):

    PRE_LOCK             die immediately BEFORE the Phase-2
                         `SELECT ... FOR UPDATE` at settlement_engine.py 437-441.
                         The Phase-1 claim commit at 362 has already landed.
                         No Phase-2 query executes.                    -> 6d-1

    PRE_PHASE2_COMMIT    die immediately BEFORE commit #2 at 793, with the
                         entire payout loop staged transaction-local.
                         Everything must roll back.                    -> 6d-2

    POST_PHASE2_COMMIT   die immediately AFTER commit #2 at 793 returns and
                         before the feed block at 801 / the report return.
                         The week is durably COMPLETED.                -> 6d-3

COMMIT COUNTING — WHY INSTANCE-LEVEL, NOT CLASS-LEVEL. On the winning-claimant
path settle_week commits exactly twice on the session it was handed: the Phase-1
claim (362) and the Phase-2 payouts+flip (793). No ledger_post in the payout loop
commits independently (verified: every call passes session=db and stages
transaction-local). BUT balance_of() opens its OWN session, and beef settlement
reads through it. Patching Session.commit at CLASS level would count those
foreign commits and land the injection at the wrong boundary. This module
patches the settlement session INSTANCE only.

FALSE-GREEN GUARD. A child that dies from an import error also fails to complete
settle_week, and a naive parent would read that as a successful crash. So the
child prints a marker to stdout immediately before dying and exits with a
distinctive code. assert_crashed() requires BOTH. Anything else is a fixture
failure, not a scenario result.

SAFETY. The child does NOT call setup_postgres_test_db() — that guard set
requires an EMPTY database, and by the time the child runs the parent has
already created and seeded the schema. The child therefore binds DATABASE_URL
itself, and re-applies the two categorical guards from the 6a harness (name must
contain "_test"; host must not look like Railway) so that this is not a
guard-free path into a live database.

USAGE (from a 6d scenario suite, after the parent has seeded the week):

    from test_support_crash import (
        run_settle_week_crashing, assert_crashed, PRE_LOCK,
    )

    proc = run_settle_week_crashing(_WEEK, LEAGUE_ID, PRE_LOCK)
    ok, detail = assert_crashed(proc)
    _assert("0: child crashed at the injection point", ok, detail=detail)
"""

from __future__ import annotations

import os
import subprocess
import sys

# ── Injection point names (import these; do not pass raw strings) ─────────────
PRE_LOCK = "PRE_LOCK"
PRE_PHASE2_COMMIT = "PRE_PHASE2_COMMIT"
POST_PHASE2_COMMIT = "POST_PHASE2_COMMIT"

INJECTION_POINTS = (PRE_LOCK, PRE_PHASE2_COMMIT, POST_PHASE2_COMMIT)

# Distinctive exit code for a successful injected crash. Deliberately not 0
# (clean), not 1 (assertion failure), not 2 (harness/config error, matching the
# 6a convention), and not 70+128 territory used by signals.
CRASH_EXIT_CODE = 70

# Printed by the child immediately before os._exit(). The parent requires it.
CRASH_MARKER = "[CRASH-INJECTED]"

# Guards mirrored from test_support_postgres (Guards 3 and 4). Categorical.
_FORBIDDEN_HOST_PATTERNS = ("railway", "rlwy", "proxy.rlwy")
_REQUIRED_DBNAME_MARKER = "_test"

# Child-side guard failure. Matches the 6a harness convention.
_GUARD_EXIT_CODE = 2


# ─────────────────────────────────────────────────────────────────────────────
# PARENT SIDE
# ─────────────────────────────────────────────────────────────────────────────

def run_settle_week_crashing(
    week: int,
    league_id: int,
    injection_point: str,
    recovery_token: str | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Spawn a child process that runs settle_week and dies at `injection_point`.

    The parent must have seeded the week already. Returns the CompletedProcess so
    the caller can assert on exit code and stdout via assert_crashed().

    `recovery_token` is forwarded to settle_week when supplied, so the same
    fixture drives the recovery-path scenarios (6d-5, 6d-6) without a second
    child script.

    A TimeoutExpired is deliberately NOT caught: a child that hangs instead of
    crashing is a real finding (most likely blocking on a row lock), and
    swallowing it would hide that.
    """
    if injection_point not in INJECTION_POINTS:
        raise ValueError(
            f"Unknown injection_point {injection_point!r}. "
            f"Expected one of {INJECTION_POINTS}."
        )

    test_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not test_url:
        raise RuntimeError(
            "run_settle_week_crashing requires TEST_DATABASE_URL to be set — the "
            "child binds to it directly. It is unset/empty."
        )

    env = dict(os.environ)
    env["CRASH_INJECT"] = injection_point
    env["CRASH_WEEK"] = str(week)
    env["CRASH_LEAGUE_ID"] = str(league_id)
    if recovery_token is not None:
        env["CRASH_RECOVERY_TOKEN"] = recovery_token
    else:
        env.pop("CRASH_RECOVERY_TOKEN", None)
    # Unbuffered so the marker reaches the pipe before os._exit().
    env["PYTHONUNBUFFERED"] = "1"

    return subprocess.run(
        [sys.executable, os.path.abspath(__file__)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def assert_crashed(proc: subprocess.CompletedProcess) -> tuple[bool, str]:
    """Return (ok, detail). ok is True only if the child died BY INJECTION.

    Requires both the marker on stdout and the distinctive exit code. Either one
    alone is insufficient: a child that dies from an import error produces
    neither, but a child that somehow printed the marker and then exited normally
    would not have crashed where we asked.
    """
    saw_marker = CRASH_MARKER in (proc.stdout or "")
    right_code = proc.returncode == CRASH_EXIT_CODE

    if saw_marker and right_code:
        return True, f"exit={proc.returncode}, marker present"

    parts = [f"exit={proc.returncode}", f"marker={'yes' if saw_marker else 'NO'}"]
    if proc.returncode == _GUARD_EXIT_CODE:
        parts.append("child refused on its own safety guards")
    if proc.stdout:
        parts.append(f"stdout={proc.stdout.strip()[-400:]!r}")
    if proc.stderr:
        parts.append(f"stderr={proc.stderr.strip()[-400:]!r}")
    return False, "; ".join(parts)


def assert_completed_cleanly(proc: subprocess.CompletedProcess) -> tuple[bool, str]:
    """Return (ok, detail) for a child that was expected NOT to crash — used by
    scenarios where the second actor is meant to run to completion."""
    if proc.returncode == 0:
        return True, "exit=0"
    detail = [f"exit={proc.returncode}"]
    if proc.stdout:
        detail.append(f"stdout={proc.stdout.strip()[-400:]!r}")
    if proc.stderr:
        detail.append(f"stderr={proc.stderr.strip()[-400:]!r}")
    return False, "; ".join(detail)


# ─────────────────────────────────────────────────────────────────────────────
# CHILD SIDE
# ─────────────────────────────────────────────────────────────────────────────

def _die() -> None:
    """Print the marker, flush, and terminate WITHOUT unwinding.

    os._exit() skips finally blocks, context-manager __exit__, SQLAlchemy session
    cleanup, and atexit. The open transaction is never rolled back by this
    process; PostgreSQL aborts it when the connection drops. That is the point.
    """
    sys.stdout.write(CRASH_MARKER + "\n")
    sys.stdout.flush()
    os._exit(CRASH_EXIT_CODE)


def _child_main() -> None:
    test_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not test_url:
        print("[CHILD GUARD] TEST_DATABASE_URL is unset/empty — refusing to run.")
        sys.exit(_GUARD_EXIT_CODE)

    # ── Guards mirrored from the 6a harness. The child bypasses
    # setup_postgres_test_db() (which demands an EMPTY database, and the parent
    # has already seeded it), so these two categorical checks are re-applied here
    # rather than trusted to the parent. ──────────────────────────────────────
    from urllib.parse import urlparse

    normalized = test_url.replace("postgres://", "postgresql://", 1)
    parsed = urlparse(normalized)
    dbname = (parsed.path or "").lstrip("/")
    host = (parsed.hostname or "").lower()

    if _REQUIRED_DBNAME_MARKER not in dbname:
        print(
            f"[CHILD GUARD] Refusing: database {dbname!r} does not contain "
            f"{_REQUIRED_DBNAME_MARKER!r}."
        )
        sys.exit(_GUARD_EXIT_CODE)

    if any(pattern in host for pattern in _FORBIDDEN_HOST_PATTERNS):
        print(
            f"[CHILD GUARD] Refusing: host {host!r} matches a forbidden Railway "
            f"pattern ({', '.join(_FORBIDDEN_HOST_PATTERNS)})."
        )
        sys.exit(_GUARD_EXIT_CODE)

    inject = os.environ.get("CRASH_INJECT", "")
    if inject not in INJECTION_POINTS:
        print(f"[CHILD GUARD] Unknown CRASH_INJECT={inject!r}.")
        sys.exit(_GUARD_EXIT_CODE)

    week = int(os.environ["CRASH_WEEK"])
    league_id = int(os.environ["CRASH_LEAGUE_ID"])
    token = os.environ.get("CRASH_RECOVERY_TOKEN") or None

    # Bind db.schema's engine to the test database BEFORE importing it. db.schema
    # builds its engine from DATABASE_URL at import time.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.environ["DATABASE_URL"] = test_url

    from db.schema import SessionLocal, engine

    # Belt-and-braces: prove the engine actually bound where we intended before
    # any statement runs. Mirrors the 6a harness's post-import ordering check.
    bound = engine.url.database or ""
    if _REQUIRED_DBNAME_MARKER not in bound:
        print(f"[CHILD GUARD] engine bound to {bound!r}, not a '_test' database.")
        sys.exit(_GUARD_EXIT_CODE)

    from betting.settlement_engine import settle_week

    db = SessionLocal()

    # ── Instance-level hooks. Class-level patching would also intercept the
    # separate sessions opened by balance_of(), miscounting commits and landing
    # the injection at the wrong boundary. ────────────────────────────────────
    _orig_execute = db.execute
    _orig_commit = db.commit
    _commits = {"n": 0}

    def _watched_execute(statement, *args, **kwargs):
        if inject == PRE_LOCK and "FOR UPDATE" in str(statement).upper():
            # Phase-1 claim (362) has already committed. Phase 2's first act is
            # this lock acquisition (437-441) and it must never execute.
            _die()
        return _orig_execute(statement, *args, **kwargs)

    def _watched_commit(*args, **kwargs):
        _commits["n"] += 1
        n = _commits["n"]
        # n == 1 -> Phase-1 claim (362). n == 2 -> Phase-2 payouts+flip (793).
        if inject == PRE_PHASE2_COMMIT and n == 2:
            _die()
        result = _orig_commit(*args, **kwargs)
        if inject == POST_PHASE2_COMMIT and n == 2:
            _die()
        return result

    db.execute = _watched_execute
    db.commit = _watched_commit

    try:
        settle_week(week, db, league_id=league_id, recovery_token=token)
    finally:
        # Reached only if the injection never fired — which is itself a finding,
        # surfaced through a clean exit that assert_crashed() will reject.
        db.close()


if __name__ == "__main__":
    _child_main()
