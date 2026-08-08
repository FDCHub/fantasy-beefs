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

    POST_RECOVERY_AUTH_COMMIT
                         die immediately AFTER commit #1 at 1057 returns —
                         recover_week's STEP-8 commit, which lands the audit row
                         and the fresh-token overwrite together — and before the
                         settle_week invocation at 1062. The recovery
                         authorization is durable; the recovered settlement never
                         starts.                                       -> 6d-6

TWO ENTRY PATHS, AND WHY THE MATRIX IS NOT FREE. An injection point is defined
against a specific boundary in a specific call path, and the two hooks that
implement them are path-blind: _watched_execute fires on the FIRST "FOR UPDATE"
it sees, and _watched_commit counts commits from 1 on whatever call it was
handed. Enter through recover_week instead of settle_week and every one of those
ordinals retargets — the first FOR UPDATE becomes the recovery lock at 928 rather
than the Phase-2 lock at 439, and commit n==2 becomes the Phase-1 claim at 362
rather than the Phase-2 payouts+flip at 793. The crash still happens, the child
still prints the marker and exits 70, and assert_crashed() still returns True.
The suite would be GREEN while measuring a different boundary than the one it
names. That is a silent mislabel, not a failure, so it is refused before spawn:
injection_compatible() is an explicit fail-closed ALLOW-LIST of the four
classified (entry, injection) pairs, enforced in both launchers and again in the
child.

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

import json
import os
import subprocess
import sys

# ── Injection point names (import these; do not pass raw strings) ─────────────
PRE_LOCK = "PRE_LOCK"
PRE_PHASE2_COMMIT = "PRE_PHASE2_COMMIT"
POST_PHASE2_COMMIT = "POST_PHASE2_COMMIT"
POST_RECOVERY_AUTH_COMMIT = "POST_RECOVERY_AUTH_COMMIT"

INJECTION_POINTS = (
    PRE_LOCK,
    PRE_PHASE2_COMMIT,
    POST_PHASE2_COMMIT,
    POST_RECOVERY_AUTH_COMMIT,
)

# ── Entry paths. Which production function the child calls. ───────────────────
ENTRY_SETTLE_WEEK = "SETTLE_WEEK"
ENTRY_RECOVER_WEEK = "RECOVER_WEEK"

ENTRY_POINTS = (ENTRY_SETTLE_WEEK, ENTRY_RECOVER_WEEK)

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
# ENTRY / INJECTION COMPATIBILITY — the single source of truth
# ─────────────────────────────────────────────────────────────────────────────
#
# ALLOW-LIST, NOT DENY-LIST. This is deliberate and the whole point of the
# extension. A deny-list ("refuse these four pairs, else allow") is correct only
# for the constants that exist the day it is written: the next injection point
# added to this file would be silently ALLOWED on BOTH entry paths, having been
# classified against neither. That is exactly the silent-mislabel failure mode
# this check exists to prevent, reintroduced by the shape of the check itself.
# So: a pair is refused unless it appears here.

_ALLOWED_PAIRS = frozenset({
    (ENTRY_SETTLE_WEEK, PRE_LOCK),
    (ENTRY_SETTLE_WEEK, PRE_PHASE2_COMMIT),
    (ENTRY_SETTLE_WEEK, POST_PHASE2_COMMIT),
    (ENTRY_RECOVER_WEEK, POST_RECOVERY_AUTH_COMMIT),
})

# Specific teaching messages for the four KNOWN-BUT-WRONG pairs. Every message
# names the boundary the injection point is defined against and the boundary it
# would actually land on, because "incompatible" alone does not tell the reader
# why a crash that looks successful would be measuring the wrong thing.
# Messages are single-line and ASCII: they are printed by the child and matched
# as substrings by the selftest.
_REFUSAL_MESSAGES = {
    (ENTRY_SETTLE_WEEK, POST_RECOVERY_AUTH_COMMIT): (
        "POST_RECOVERY_AUTH_COMMIT is a RECOVER_WEEK-only injection point: it "
        "fires after commit n==1, which on the recover_week path is the "
        "recovery-authorization commit at settlement_engine.py 1057 (audit row "
        "+ fresh-token overwrite, landed together). The settle_week path has no "
        "recovery-auth commit at 1057 at all; its commit n==1 is the Phase-1 "
        "claim commit at 362. Injecting here would kill the process just after "
        "the claim and durably produce 6d-1's state while the suite reports "
        "6d-6's. Use run_recover_week_crashing() for this injection point."
    ),
    (ENTRY_RECOVER_WEEK, PRE_LOCK): (
        "PRE_LOCK fires on the FIRST statement containing 'FOR UPDATE' executed "
        "on the settlement session. On the recover_week path that first FOR "
        "UPDATE is the recovery lock at settlement_engine.py 928, not the "
        "Phase-2 settlement lock at 439 that PRE_LOCK is defined against. The "
        "crash would land before the recovery audit is even staged, leaving an "
        "untouched CLAIMED week rather than 6d-1's post-claim/pre-lock state. "
        "Use run_settle_week_crashing() for PRE_LOCK."
    ),
    (ENTRY_RECOVER_WEEK, PRE_PHASE2_COMMIT): (
        "PRE_PHASE2_COMMIT fires before commit n==2. On the recover_week path "
        "commit n==1 is the recovery-authorization commit at "
        "settlement_engine.py 1057, so the whole counter retargets by one and "
        "n==2 is the Phase-1 claim commit at 362 (inside the settle_week call "
        "at 1062), NOT the Phase-2 payouts+flip commit at 793 that this "
        "injection point is defined against. Use run_settle_week_crashing() "
        "for PRE_PHASE2_COMMIT."
    ),
    (ENTRY_RECOVER_WEEK, POST_PHASE2_COMMIT): (
        "POST_PHASE2_COMMIT fires after commit n==2 returns. On the "
        "recover_week path commit n==1 is the recovery-authorization commit at "
        "settlement_engine.py 1057, so the whole counter retargets by one and "
        "n==2 is the Phase-1 claim commit at 362 (inside the settle_week call "
        "at 1062), NOT the Phase-2 payouts+flip commit at 793 that this "
        "injection point is defined against. The crash would land just after "
        "the claim rather than after the atomic COMPLETED flip. Use "
        "run_settle_week_crashing() for POST_PHASE2_COMMIT."
    ),
}


def injection_compatible(entry_point: str, injection_point: str) -> tuple[bool, str]:
    """Return (ok, message) for an (entry path, injection point) pair.

    ok is True ONLY for the four explicitly classified pairs in _ALLOWED_PAIRS;
    message is "" in that case. Everything else is refused: the four
    known-but-wrong pairs get their specific teaching message, and ANY other
    input — an unrecognized entry path, an unrecognized injection point, or a
    future constant added to this file and not yet classified against both entry
    paths — gets the generic fail-closed message naming both values received.

    Pure: no environment, no I/O, no process state. Both the launchers and the
    child call this same function, so the matrix is encoded exactly once.
    """
    pair = (entry_point, injection_point)

    if pair in _ALLOWED_PAIRS:
        return True, ""

    if pair in _REFUSAL_MESSAGES:
        return False, _REFUSAL_MESSAGES[pair]

    return False, (
        f"Unclassified injection pair: entry_point={entry_point!r}, "
        f"injection_point={injection_point!r}. injection_compatible() is a "
        f"fail-closed allow-list -- a pair is refused unless it has been "
        f"explicitly classified against BOTH entry paths. If this is a newly "
        f"added injection point, decide what boundary it lands on for "
        f"{ENTRY_SETTLE_WEEK} and for {ENTRY_RECOVER_WEEK} and add it to "
        f"_ALLOWED_PAIRS or _REFUSAL_MESSAGES before use."
    )


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

    # ORDER IS LOAD-BEARING. The membership check above enumerates INJECTION_POINTS
    # in its error, and that tuple now contains POST_RECOVERY_AUTH_COMMIT — a
    # constant this launcher cannot accept. Running compatibility IMMEDIATELY
    # after membership means a known-but-incompatible constant is met with the
    # specific teaching message below rather than an enumeration that advertises
    # it as valid here. Reverse these two and the caller is told to use a value
    # that will then be refused.
    ok, why = injection_compatible(ENTRY_SETTLE_WEEK, injection_point)
    if not ok:
        raise ValueError(why)

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
    # Absence, not a declaration. This launcher does not set CRASH_ENTRY — an
    # absent value is what the child resolves to SETTLE_WEEK — but dict(os.environ)
    # would carry an inherited CRASH_ENTRY straight through, silently redirecting
    # this child to the recover_week entry path. Popping makes the absence a fact
    # rather than an assumption about the operator's shell. Unconditional: it must
    # hold on the recovery-token path too.
    env.pop("CRASH_ENTRY", None)
    # Unbuffered so the marker reaches the pipe before os._exit().
    env["PYTHONUNBUFFERED"] = "1"

    return subprocess.run(
        [sys.executable, os.path.abspath(__file__)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def run_recover_week_crashing(
    week: int,
    league_id: int,
    injection_point: str,
    actor: str,
    exit_evidence: dict,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Spawn a child that runs recover_week and dies at `injection_point`.

    Sibling of run_settle_week_crashing for the RECOVER_WEEK entry path. The
    parent must have seeded the week into the CLAIMED state already (typically by
    crashing a settle_week first). Returns the CompletedProcess for
    assert_crashed().

    actor and exit_evidence are recover_week's mandatory operator-supplied proof
    that the original settlement process has exited; they are validated here so a
    malformed payload is a launcher-side ValueError rather than a child that dies
    on a production ValueError and is misread as a fixture failure.

    VALIDATED STRIPPED, TRANSPORTED RAW. recover_week does its own normalization —
    actor at settlement_engine.py 883, category/detail at 894-895 — and records
    the stripped values. If this harness stripped before transport, that
    production normalization would receive already-clean input, become a no-op,
    and never be exercised by any 6d scenario. So a whitespace-padded value passes
    validation here and arrives at recover_week still padded.

    A TimeoutExpired is deliberately NOT caught, for the same reason as the
    settle_week launcher.
    """
    if injection_point not in INJECTION_POINTS:
        raise ValueError(
            f"Unknown injection_point {injection_point!r}. "
            f"Expected one of {INJECTION_POINTS}."
        )

    # Same load-bearing ordering as run_settle_week_crashing: compatibility runs
    # immediately after membership so the three settle-only constants get their
    # teaching message instead of an enumeration that lists them as valid.
    ok, why = injection_compatible(ENTRY_RECOVER_WEEK, injection_point)
    if not ok:
        raise ValueError(why)

    # ── Payload validation. Mirrors recover_week's STEP-1 contract (873-895):
    # actor a nonempty string, exit_evidence a dict with nonempty string
    # "category" and "detail", the whole thing JSON-serializable. Checked against
    # the STRIPPED form; the RAW value is what gets transported. ───────────────
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError(
            f"actor must be a nonempty string (nonempty after strip) identifying "
            f"who authorized the recovery; got {actor!r}."
        )

    if not isinstance(exit_evidence, dict):
        raise ValueError(
            f"exit_evidence must be a dict with nonempty 'category' and "
            f"'detail'; got {type(exit_evidence).__name__}."
        )

    category = exit_evidence.get("category")
    if not isinstance(category, str) or not category.strip():
        raise ValueError(
            f"exit_evidence['category'] must be a nonempty string (nonempty "
            f"after strip); got {category!r}."
        )

    detail = exit_evidence.get("detail")
    if not isinstance(detail, str) or not detail.strip():
        raise ValueError(
            f"exit_evidence['detail'] must be a nonempty string (nonempty after "
            f"strip); got {detail!r}."
        )

    # Serialize the RAW mapping — this is both the serializability check and the
    # transport encoding, so there is no way for the two to disagree.
    try:
        evidence_json = json.dumps(exit_evidence)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"exit_evidence must be JSON-serializable to cross the process "
            f"boundary: {exc}"
        ) from exc

    test_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not test_url:
        raise RuntimeError(
            "run_recover_week_crashing requires TEST_DATABASE_URL to be set — the "
            "child binds to it directly. It is unset/empty."
        )

    env = dict(os.environ)
    env["CRASH_ENTRY"] = ENTRY_RECOVER_WEEK
    env["CRASH_INJECT"] = injection_point
    env["CRASH_WEEK"] = str(week)
    env["CRASH_LEAGUE_ID"] = str(league_id)
    env["CRASH_ACTOR"] = actor                 # RAW, unstripped
    env["CRASH_EXIT_EVIDENCE"] = evidence_json  # RAW values, unstripped
    # recover_week mints its own fresh token; an inherited one from a prior
    # settle-path spawn must not reach this child.
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

    # ── Entry path. Absent or empty CRASH_ENTRY means SETTLE_WEEK, which keeps
    # every pre-existing caller (and the four PostgreSQL 6d suites) working
    # unchanged without setting anything new. ─────────────────────────────────
    entry = os.environ.get("CRASH_ENTRY", "") or ENTRY_SETTLE_WEEK
    if entry not in ENTRY_POINTS:
        print(
            f"[CHILD GUARD: ENTRY] Unknown CRASH_ENTRY={entry!r}. "
            f"Expected one of {ENTRY_POINTS}, or unset for {ENTRY_SETTLE_WEEK}."
        )
        sys.exit(_GUARD_EXIT_CODE)

    # Re-checked child-side rather than trusted to the launcher: the child is
    # spawnable directly with a hand-built env, and an incompatible pair does not
    # fail loudly — it crashes successfully at the WRONG boundary and reports
    # green. Same helper, same matrix, no second copy.
    compatible, why = injection_compatible(entry, inject)
    if not compatible:
        print(f"[CHILD GUARD: INJECTION-COMPAT] {why}")
        sys.exit(_GUARD_EXIT_CODE)

    # ── RECOVER_WEEK payload. Same contract as the launcher; validated against
    # the stripped form, carried forward RAW so recover_week's own normalization
    # at 883/894-895 is genuinely exercised. Every message names its specific
    # guard: _GUARD_EXIT_CODE is shared with five pre-existing guards, so the
    # exit code alone cannot tell the reader which check refused. ─────────────
    actor = None
    exit_evidence = None
    if entry == ENTRY_RECOVER_WEEK:
        raw_actor = os.environ.get("CRASH_ACTOR")
        if raw_actor is None:
            print(
                "[CHILD GUARD: RECOVER-ACTOR-MISSING] CRASH_ACTOR is not set. "
                f"{ENTRY_RECOVER_WEEK} entry requires an actor."
            )
            sys.exit(_GUARD_EXIT_CODE)
        if not raw_actor.strip():
            print(
                f"[CHILD GUARD: RECOVER-ACTOR-BLANK] CRASH_ACTOR={raw_actor!r} "
                "is empty after strip."
            )
            sys.exit(_GUARD_EXIT_CODE)

        raw_evidence = os.environ.get("CRASH_EXIT_EVIDENCE")
        if not raw_evidence:
            print(
                "[CHILD GUARD: RECOVER-EVIDENCE-MISSING] CRASH_EXIT_EVIDENCE is "
                f"unset/empty. {ENTRY_RECOVER_WEEK} entry requires exit evidence."
            )
            sys.exit(_GUARD_EXIT_CODE)
        try:
            parsed_evidence = json.loads(raw_evidence)
        except (TypeError, ValueError) as exc:
            print(
                "[CHILD GUARD: RECOVER-EVIDENCE-JSON] CRASH_EXIT_EVIDENCE is not "
                f"valid JSON ({exc})."
            )
            sys.exit(_GUARD_EXIT_CODE)
        if not isinstance(parsed_evidence, dict):
            print(
                "[CHILD GUARD: RECOVER-EVIDENCE-TYPE] CRASH_EXIT_EVIDENCE decoded "
                f"to {type(parsed_evidence).__name__}, not a dict."
            )
            sys.exit(_GUARD_EXIT_CODE)

        raw_category = parsed_evidence.get("category")
        if not isinstance(raw_category, str) or not raw_category.strip():
            print(
                "[CHILD GUARD: RECOVER-EVIDENCE-CATEGORY] exit_evidence "
                f"'category' must be a nonempty string; got {raw_category!r}."
            )
            sys.exit(_GUARD_EXIT_CODE)

        raw_detail = parsed_evidence.get("detail")
        if not isinstance(raw_detail, str) or not raw_detail.strip():
            print(
                "[CHILD GUARD: RECOVER-EVIDENCE-DETAIL] exit_evidence 'detail' "
                f"must be a nonempty string; got {raw_detail!r}."
            )
            sys.exit(_GUARD_EXIT_CODE)

        # NOT stripped. See the launcher docstring.
        actor = raw_actor
        exit_evidence = parsed_evidence

    week = int(os.environ["CRASH_WEEK"])
    league_id = int(os.environ["CRASH_LEAGUE_ID"])
    token = os.environ.get("CRASH_RECOVERY_TOKEN") or None

    # Bind db.schema's engine to the test database BEFORE importing it. db.schema
    # builds its engine from DATABASE_URL at import time.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ["DATABASE_URL"] = test_url

    from db.schema import SessionLocal, engine

    # Belt-and-braces: prove the engine actually bound where we intended before
    # any statement runs. Mirrors the 6a harness's post-import ordering check.
    bound = engine.url.database or ""
    if _REQUIRED_DBNAME_MARKER not in bound:
        print(f"[CHILD GUARD] engine bound to {bound!r}, not a '_test' database.")
        sys.exit(_GUARD_EXIT_CODE)

    from betting.settlement_engine import settle_week, recover_week

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
        # RECOVER_WEEK entry only (injection_compatible refuses it elsewhere):
        # n == 1 is recover_week's STEP-8 commit at 1057, landing the audit row
        # and the fresh-token overwrite together. POST-delegate is mandatory —
        # firing before the real commit would roll both back and leave exactly
        # 6d-1's durable state while the suite reported 6d-6's.
        if inject == POST_RECOVERY_AUTH_COMMIT and n == 1:
            _die()
        return result

    db.execute = _watched_execute
    db.commit = _watched_commit

    try:
        if entry == ENTRY_RECOVER_WEEK:
            recover_week(week, db, league_id, actor, exit_evidence)
        else:
            settle_week(week, db, league_id=league_id, recovery_token=token)
    finally:
        # Reached only if the injection never fired — which is itself a finding,
        # surfaced through a clean exit that assert_crashed() will reject.
        db.close()


if __name__ == "__main__":
    _child_main()
