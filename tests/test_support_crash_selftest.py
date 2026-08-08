"""
test_support_crash_selftest.py — pytest self-test for the crash harness itself.

FR-8.7 6d-6. Covers the entry/injection compatibility matrix, both launchers'
pre-spawn refusals, and every child-side guard added for the RECOVER_WEEK entry
path. Runs with NO PostgreSQL server: every guard exercised here fires before the
child reaches the db.schema import, so no connection is ever attempted.

WHY THIS FILE EXISTS. The harness's failure mode is not a red suite. An
injection point aimed at the wrong entry path still crashes the child, still
prints CRASH_MARKER, still exits 70, and assert_crashed() still returns True —
the scenario just measured a different boundary than the one it names. Nothing in
the four PostgreSQL 6d suites can catch that, because from their side it looks
identical to success. The guards are the detection mechanism, so the guards need
their own proof.

CRITICAL — WHY EVERY SPAWNING TEST SETS A VALID TEST_DATABASE_URL. The child
signals SIX distinct guard failures with the SAME exit code, _GUARD_EXIT_CODE=2,
and two of them run BEFORE any injection validation: the "_test" dbname marker
check (test_support_crash.py 482) and the Railway host-pattern check (489). A
spawning test that leaves TEST_DATABASE_URL unset or bogus exits 2 on the dbname
guard, never reaches the guard under test, and passes — a green test proving
nothing at all. So _spawn_child() always supplies a syntactically valid URL whose
database name contains "_test" and whose host matches no forbidden pattern, and
EVERY spawning assertion pairs the exit code with distinctive stdout text naming
the specific guard that refused. Exit code 2 alone is not evidence.

NOT COVERED HERE, DELIBERATELY. The default-entry integration proof (absent
CRASH_ENTRY behaving as SETTLE_WEEK against a real database) belongs to the four
existing PostgreSQL suites, which exercise it on every run. Nothing here reaches
production code.

    pytest test_support_crash_selftest.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

import test_support_crash as tsc
from test_support_crash import (
    ENTRY_POINTS,
    ENTRY_RECOVER_WEEK,
    ENTRY_SETTLE_WEEK,
    INJECTION_POINTS,
    POST_PHASE2_COMMIT,
    POST_RECOVERY_AUTH_COMMIT,
    PRE_LOCK,
    PRE_PHASE2_COMMIT,
    injection_compatible,
    run_recover_week_crashing,
    run_settle_week_crashing,
)

_CHILD_PATH = os.path.abspath(tsc.__file__)

# Passes the two pre-existing categorical guards: dbname contains "_test", host
# matches none of _FORBIDDEN_HOST_PATTERNS. Never connected to — every guard
# under test fires before the db.schema import.
_SAFE_URL = "postgresql://u:p@127.0.0.1:5432/fantasy_beefs_selftest_test"

_VALID_EVIDENCE = {"category": "container_exit", "detail": "task 7f3 exited 137"}

_GUARD = tsc._GUARD_EXIT_CODE


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _spawn_child(**overrides) -> subprocess.CompletedProcess:
    """Run the harness as a child with a hand-built env.

    Starts from a copy of the real environment (Windows needs SYSTEMROOT et al.
    for the interpreter to start), strips every inherited CRASH_* key so a stale
    value cannot decide the outcome, then applies a base that satisfies the
    pre-existing guards. An override whose value is None deletes the key.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("CRASH_")}
    env.update({
        "TEST_DATABASE_URL": _SAFE_URL,
        "CRASH_WEEK": "5",
        "CRASH_LEAGUE_ID": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value

    return subprocess.run(
        [sys.executable, _CHILD_PATH],
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def _output(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout or "") + (proc.stderr or "")


def _assert_guard_refusal(proc, marker: str) -> None:
    """Exit code 2 AND distinctive text. Neither alone is evidence."""
    out = _output(proc)
    assert proc.returncode == _GUARD, (
        f"expected exit {_GUARD}, got {proc.returncode}. output={out.strip()[-600:]!r}"
    )
    assert marker in out, (
        f"exit {_GUARD} but no {marker!r} in output — a different guard refused, "
        f"so this test proved nothing. output={out.strip()[-600:]!r}"
    )


@pytest.fixture
def no_spawn(monkeypatch):
    """Make any subprocess.run a hard failure. Proves refusal happens BEFORE spawn."""
    def _boom(*args, **kwargs):
        raise AssertionError(
            "subprocess.run was called — the launcher spawned a child instead of "
            "refusing up front."
        )
    monkeypatch.setattr(subprocess, "run", _boom)


@pytest.fixture
def captured_spawn(monkeypatch):
    """Capture the env/argv a launcher would spawn with, without spawning."""
    captured = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(
            args=argv, returncode=tsc.CRASH_EXIT_CODE,
            stdout=tsc.CRASH_MARKER + "\n", stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    return captured


# ─────────────────────────────────────────────────────────────────────────────
# constants
# ─────────────────────────────────────────────────────────────────────────────

def test_injection_points_appended_without_reordering():
    assert INJECTION_POINTS == (
        PRE_LOCK, PRE_PHASE2_COMMIT, POST_PHASE2_COMMIT, POST_RECOVERY_AUTH_COMMIT,
    )
    # The three originals keep their positions; the new one is appended last.
    assert INJECTION_POINTS[:3] == (PRE_LOCK, PRE_PHASE2_COMMIT, POST_PHASE2_COMMIT)
    assert INJECTION_POINTS[-1] == POST_RECOVERY_AUTH_COMMIT


def test_entry_point_constants():
    assert ENTRY_SETTLE_WEEK == "SETTLE_WEEK"
    assert ENTRY_RECOVER_WEEK == "RECOVER_WEEK"
    assert ENTRY_POINTS == (ENTRY_SETTLE_WEEK, ENTRY_RECOVER_WEEK)


def test_preexisting_public_surface_intact():
    for name in (
        "PRE_LOCK", "PRE_PHASE2_COMMIT", "POST_PHASE2_COMMIT", "INJECTION_POINTS",
        "CRASH_EXIT_CODE", "CRASH_MARKER", "run_settle_week_crashing",
        "assert_crashed", "assert_completed_cleanly",
    ):
        assert hasattr(tsc, name), f"{name} disappeared"
    assert tsc.CRASH_EXIT_CODE == 70
    assert tsc.CRASH_MARKER == "[CRASH-INJECTED]"


# ─────────────────────────────────────────────────────────────────────────────
# injection_compatible — the matrix
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED = [
    (ENTRY_SETTLE_WEEK, PRE_LOCK),
    (ENTRY_SETTLE_WEEK, PRE_PHASE2_COMMIT),
    (ENTRY_SETTLE_WEEK, POST_PHASE2_COMMIT),
    (ENTRY_RECOVER_WEEK, POST_RECOVERY_AUTH_COMMIT),
]

# (entry, injection, anchors the message must cite)
_REFUSED = [
    (ENTRY_SETTLE_WEEK, POST_RECOVERY_AUTH_COMMIT, ("1057", "362")),
    (ENTRY_RECOVER_WEEK, PRE_LOCK, ("928", "439")),
    (ENTRY_RECOVER_WEEK, PRE_PHASE2_COMMIT, ("362", "793")),
    (ENTRY_RECOVER_WEEK, POST_PHASE2_COMMIT, ("362", "793")),
]


@pytest.mark.parametrize("entry,inject", _ALLOWED)
def test_allowed_pairs(entry, inject):
    ok, msg = injection_compatible(entry, inject)
    assert ok is True
    assert msg == ""


@pytest.mark.parametrize("entry,inject,_anchors", _REFUSED)
def test_refused_pairs(entry, inject, _anchors):
    ok, msg = injection_compatible(entry, inject)
    assert ok is False
    assert msg.strip()


@pytest.mark.parametrize("entry,inject,anchors", _REFUSED)
def test_refusal_messages_cite_line_anchors(entry, inject, anchors):
    _, msg = injection_compatible(entry, inject)
    for anchor in anchors:
        assert anchor in msg, (
            f"({entry}, {inject}) refusal does not cite {anchor}: {msg!r}"
        )


def test_matrix_is_exhaustive_over_known_constants():
    """Every (entry, injection) combination resolves, and exactly four allow."""
    allowed = [
        (e, i) for e in ENTRY_POINTS for i in INJECTION_POINTS
        if injection_compatible(e, i)[0]
    ]
    assert sorted(allowed) == sorted(_ALLOWED)


def test_unrecognized_entry_point_refused():
    ok, msg = injection_compatible("RESETTLE_WEEK", PRE_LOCK)
    assert ok is False
    assert "RESETTLE_WEEK" in msg
    assert "PRE_LOCK" in msg


def test_unrecognized_injection_point_refused():
    ok, msg = injection_compatible(ENTRY_SETTLE_WEEK, "PRE_FEED_EMIT")
    assert ok is False
    assert "PRE_FEED_EMIT" in msg
    assert ENTRY_SETTLE_WEEK in msg


@pytest.mark.parametrize("entry", list(ENTRY_POINTS))
def test_future_constant_is_fail_closed_on_both_entry_paths(entry):
    """The allow-list requirement, stated as a test.

    A deny-list implementation ("refuse these four, else allow") passes every
    other test in this file and fails only this one: an unclassified constant
    would be ALLOWED on both entry paths.
    """
    ok, msg = injection_compatible(entry, "POST_FUTURE_BOUNDARY_COMMIT")
    assert ok is False, (
        f"unclassified injection point was ALLOWED on {entry} — the matrix is a "
        f"deny-list, not an allow-list"
    )
    assert "POST_FUTURE_BOUNDARY_COMMIT" in msg


def test_both_values_unrecognized_refused():
    ok, msg = injection_compatible("NOPE", "ALSO_NOPE")
    assert ok is False
    assert "NOPE" in msg and "ALSO_NOPE" in msg


# ─────────────────────────────────────────────────────────────────────────────
# run_settle_week_crashing — pre-spawn refusal and check ORDER
# ─────────────────────────────────────────────────────────────────────────────

def test_settle_launcher_refuses_recovery_injection_before_spawn(no_spawn, monkeypatch):
    """The only refused pair reachable through this launcher (it takes no entry).

    The message assertions pin the check ORDER. POST_RECOVERY_AUTH_COMMIT is now
    a member of INJECTION_POINTS, so the membership check passes it through and
    compatibility must be what refuses it. If the two checks were reversed —
    or if compatibility ran later, after the TEST_DATABASE_URL check — the
    caller would get the membership enumeration, which lists
    POST_RECOVERY_AUTH_COMMIT as a valid value for a launcher that cannot
    accept it.
    """
    monkeypatch.setenv("TEST_DATABASE_URL", _SAFE_URL)

    with pytest.raises(ValueError) as exc:
        run_settle_week_crashing(5, 1, POST_RECOVERY_AUTH_COMMIT)

    msg = str(exc.value)
    assert "1057" in msg and "362" in msg, f"no teaching text: {msg!r}"
    assert str(INJECTION_POINTS) not in msg, (
        "the membership enumeration reached the caller — the checks are in the "
        "wrong order"
    )
    assert "Expected one of" not in msg


def test_settle_launcher_refuses_recovery_injection_without_db_url(no_spawn, monkeypatch):
    """Compatibility precedes the TEST_DATABASE_URL check, so the teaching
    message survives even in an unconfigured environment."""
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

    with pytest.raises(ValueError) as exc:
        run_settle_week_crashing(5, 1, POST_RECOVERY_AUTH_COMMIT)
    assert "1057" in str(exc.value)


def test_settle_launcher_still_rejects_unknown_constant_by_membership(no_spawn):
    with pytest.raises(ValueError) as exc:
        run_settle_week_crashing(5, 1, "NOT_A_POINT")
    assert "Unknown injection_point" in str(exc.value)


@pytest.mark.parametrize("inject", [PRE_LOCK, PRE_PHASE2_COMMIT, POST_PHASE2_COMMIT])
def test_settle_launcher_accepts_its_three_points(captured_spawn, monkeypatch, inject):
    monkeypatch.setenv("TEST_DATABASE_URL", _SAFE_URL)
    run_settle_week_crashing(5, 1, inject)
    env = captured_spawn["env"]
    assert env["CRASH_INJECT"] == inject
    assert env["CRASH_WEEK"] == "5"
    assert env["CRASH_LEAGUE_ID"] == "1"


def test_settle_launcher_does_not_set_crash_entry(captured_spawn, monkeypatch):
    """Absent CRASH_ENTRY must keep meaning SETTLE_WEEK."""
    monkeypatch.setenv("TEST_DATABASE_URL", _SAFE_URL)
    monkeypatch.setenv("CRASH_ENTRY", tsc.ENTRY_RECOVER_WEEK)
    run_settle_week_crashing(5, 1, PRE_LOCK)
    assert "CRASH_ENTRY" not in captured_spawn["env"]


# ─────────────────────────────────────────────────────────────────────────────
# run_recover_week_crashing — pre-spawn refusal, validation, transport
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("inject,anchors", [
    (PRE_LOCK, ("928", "439")),
    (PRE_PHASE2_COMMIT, ("362", "793")),
    (POST_PHASE2_COMMIT, ("362", "793")),
])
def test_recover_launcher_refuses_settle_injections_before_spawn(
    no_spawn, monkeypatch, inject, anchors
):
    monkeypatch.setenv("TEST_DATABASE_URL", _SAFE_URL)

    with pytest.raises(ValueError) as exc:
        run_recover_week_crashing(5, 1, inject, "ops:fraser", dict(_VALID_EVIDENCE))

    msg = str(exc.value)
    for anchor in anchors:
        assert anchor in msg, f"{inject} refusal does not cite {anchor}: {msg!r}"
    assert str(INJECTION_POINTS) not in msg
    assert "Expected one of" not in msg


def test_recover_launcher_rejects_unknown_constant_by_membership(no_spawn):
    with pytest.raises(ValueError) as exc:
        run_recover_week_crashing(5, 1, "NOT_A_POINT", "ops", dict(_VALID_EVIDENCE))
    assert "Unknown injection_point" in str(exc.value)


@pytest.mark.parametrize("actor", [None, "", "   ", 17, b"ops"])
def test_recover_launcher_rejects_bad_actor(no_spawn, monkeypatch, actor):
    monkeypatch.setenv("TEST_DATABASE_URL", _SAFE_URL)
    with pytest.raises(ValueError) as exc:
        run_recover_week_crashing(
            5, 1, POST_RECOVERY_AUTH_COMMIT, actor, dict(_VALID_EVIDENCE)
        )
    assert "actor" in str(exc.value)


@pytest.mark.parametrize("evidence", [
    None,
    "container_exit",
    ["container_exit"],
    {},
    {"detail": "no category"},
    {"category": "container_exit"},
    {"category": "", "detail": "d"},
    {"category": "   ", "detail": "d"},
    {"category": "c", "detail": ""},
    {"category": "c", "detail": "  "},
    {"category": 7, "detail": "d"},
    {"category": "c", "detail": 7},
])
def test_recover_launcher_rejects_bad_evidence(no_spawn, monkeypatch, evidence):
    monkeypatch.setenv("TEST_DATABASE_URL", _SAFE_URL)
    with pytest.raises(ValueError) as exc:
        run_recover_week_crashing(
            5, 1, POST_RECOVERY_AUTH_COMMIT, "ops:fraser", evidence
        )
    assert "exit_evidence" in str(exc.value)


def test_recover_launcher_rejects_unserializable_evidence(no_spawn, monkeypatch):
    monkeypatch.setenv("TEST_DATABASE_URL", _SAFE_URL)
    evidence = {"category": "c", "detail": "d", "when": object()}
    with pytest.raises(ValueError) as exc:
        run_recover_week_crashing(
            5, 1, POST_RECOVERY_AUTH_COMMIT, "ops:fraser", evidence
        )
    assert "JSON-serializable" in str(exc.value)


def test_recover_launcher_requires_test_database_url(no_spawn, monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError) as exc:
        run_recover_week_crashing(
            5, 1, POST_RECOVERY_AUTH_COMMIT, "ops:fraser", dict(_VALID_EVIDENCE)
        )
    assert "TEST_DATABASE_URL" in str(exc.value)


def test_recover_launcher_env_shape(captured_spawn, monkeypatch):
    monkeypatch.setenv("TEST_DATABASE_URL", _SAFE_URL)
    monkeypatch.setenv("CRASH_RECOVERY_TOKEN", "stale-token-from-a-prior-spawn")

    run_recover_week_crashing(
        9, 3, POST_RECOVERY_AUTH_COMMIT, "ops:fraser", dict(_VALID_EVIDENCE)
    )

    env = captured_spawn["env"]
    assert env["CRASH_ENTRY"] == ENTRY_RECOVER_WEEK
    assert env["CRASH_INJECT"] == POST_RECOVERY_AUTH_COMMIT
    assert env["CRASH_WEEK"] == "9"
    assert env["CRASH_LEAGUE_ID"] == "3"
    assert env["CRASH_ACTOR"] == "ops:fraser"
    assert json.loads(env["CRASH_EXIT_EVIDENCE"]) == _VALID_EVIDENCE
    assert env["PYTHONUNBUFFERED"] == "1"
    # An inherited token must not reach a recover child — it mints its own.
    assert "CRASH_RECOVERY_TOKEN" not in env

    assert captured_spawn["argv"] == [sys.executable, _CHILD_PATH]
    kwargs = captured_spawn["kwargs"]
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["timeout"] == 60


def test_recover_launcher_transports_padded_values_unstripped(captured_spawn, monkeypatch):
    """Validate stripped, transport RAW.

    recover_week strips actor at settlement_engine.py 883 and category/detail at
    894-895 and records the stripped values. If this harness stripped before
    transport, that production normalization would be handed already-clean input
    and never actually run. A padded value must pass validation here and arrive
    at the child byte-identical.
    """
    monkeypatch.setenv("TEST_DATABASE_URL", _SAFE_URL)

    padded_actor = "  ops:fraser\t"
    padded_evidence = {
        "category": "\n container_exit  ",
        "detail": "  task 7f3 exited 137 \t",
        "extra": "  preserved  ",
    }

    run_recover_week_crashing(
        5, 1, POST_RECOVERY_AUTH_COMMIT, padded_actor, padded_evidence
    )

    env = captured_spawn["env"]
    assert env["CRASH_ACTOR"] == padded_actor
    assert env["CRASH_ACTOR"].encode("utf-8") == padded_actor.encode("utf-8")

    decoded = json.loads(env["CRASH_EXIT_EVIDENCE"])
    assert decoded == padded_evidence
    assert decoded["category"] == "\n container_exit  "
    assert decoded["detail"] == "  task 7f3 exited 137 \t"
    assert decoded["extra"] == "  preserved  "


# ─────────────────────────────────────────────────────────────────────────────
# child side — real spawns, no database
# ─────────────────────────────────────────────────────────────────────────────

def test_child_baseline_guards_pass_with_safe_url():
    """Sanity: the base env clears the dbname and host guards.

    Without this, every child test below could be exiting 2 on a pre-existing
    guard while appearing to prove something about a new one. Here the child is
    handed a known-bad CRASH_INJECT, so the injection guard — which runs AFTER
    both pre-existing guards — must be what refuses.
    """
    proc = _spawn_child(CRASH_INJECT="NOT_A_POINT")
    _assert_guard_refusal(proc, "Unknown CRASH_INJECT")
    out = _output(proc)
    assert "does not contain" not in out, "dbname guard fired — base env is wrong"
    assert "forbidden Railway" not in out, "host guard fired — base env is wrong"


def test_child_dbname_guard_still_fires_for_a_bad_url():
    """Proves the safe URL above is doing real work, not being ignored."""
    proc = _spawn_child(
        TEST_DATABASE_URL="postgresql://u:p@127.0.0.1:5432/fantasy_beefs_prod",
        CRASH_INJECT=PRE_LOCK,
    )
    _assert_guard_refusal(proc, "does not contain")


@pytest.mark.parametrize("entry,inject,_anchors", _REFUSED)
def test_child_refuses_incompatible_pairs(entry, inject, _anchors):
    """Hand-built env bypasses the launchers entirely; the child re-checks."""
    _, expected = injection_compatible(entry, inject)
    proc = _spawn_child(
        CRASH_ENTRY=entry,
        CRASH_INJECT=inject,
        CRASH_ACTOR="ops:fraser",
        CRASH_EXIT_EVIDENCE=json.dumps(_VALID_EVIDENCE),
    )
    _assert_guard_refusal(proc, "[CHILD GUARD: INJECTION-COMPAT]")
    assert expected in _output(proc), "child did not print the helper's message"


def test_child_refuses_recovery_injection_on_default_entry():
    """Absent CRASH_ENTRY means SETTLE_WEEK, so this pair must still be refused."""
    _, expected = injection_compatible(ENTRY_SETTLE_WEEK, POST_RECOVERY_AUTH_COMMIT)
    proc = _spawn_child(CRASH_ENTRY=None, CRASH_INJECT=POST_RECOVERY_AUTH_COMMIT)
    _assert_guard_refusal(proc, "[CHILD GUARD: INJECTION-COMPAT]")
    assert expected in _output(proc)


@pytest.mark.parametrize("entry", ["RESETTLE_WEEK", "settle_week", "recover", "  "])
def test_child_refuses_unknown_entry(entry):
    proc = _spawn_child(CRASH_ENTRY=entry, CRASH_INJECT=PRE_LOCK)
    _assert_guard_refusal(proc, "[CHILD GUARD: ENTRY]")


@pytest.mark.parametrize("overrides,marker", [
    ({"CRASH_ACTOR": None},
     "[CHILD GUARD: RECOVER-ACTOR-MISSING]"),
    ({"CRASH_ACTOR": "   \t "},
     "[CHILD GUARD: RECOVER-ACTOR-BLANK]"),
    ({"CRASH_EXIT_EVIDENCE": None},
     "[CHILD GUARD: RECOVER-EVIDENCE-MISSING]"),
    ({"CRASH_EXIT_EVIDENCE": "{not json"},
     "[CHILD GUARD: RECOVER-EVIDENCE-JSON]"),
    ({"CRASH_EXIT_EVIDENCE": '"container_exit"'},
     "[CHILD GUARD: RECOVER-EVIDENCE-TYPE]"),
    ({"CRASH_EXIT_EVIDENCE": '["container_exit"]'},
     "[CHILD GUARD: RECOVER-EVIDENCE-TYPE]"),
    ({"CRASH_EXIT_EVIDENCE": json.dumps({"detail": "d"})},
     "[CHILD GUARD: RECOVER-EVIDENCE-CATEGORY]"),
    ({"CRASH_EXIT_EVIDENCE": json.dumps({"category": "c"})},
     "[CHILD GUARD: RECOVER-EVIDENCE-DETAIL]"),
    ({"CRASH_EXIT_EVIDENCE": json.dumps({"category": "  ", "detail": "d"})},
     "[CHILD GUARD: RECOVER-EVIDENCE-CATEGORY]"),
    ({"CRASH_EXIT_EVIDENCE": json.dumps({"category": "c", "detail": " \t "})},
     "[CHILD GUARD: RECOVER-EVIDENCE-DETAIL]"),
    ({"CRASH_EXIT_EVIDENCE": json.dumps({"category": 7, "detail": "d"})},
     "[CHILD GUARD: RECOVER-EVIDENCE-CATEGORY]"),
    ({"CRASH_EXIT_EVIDENCE": json.dumps({"category": "c", "detail": None})},
     "[CHILD GUARD: RECOVER-EVIDENCE-DETAIL]"),
])
def test_child_recover_payload_guards(overrides, marker):
    env = {
        "CRASH_ENTRY": ENTRY_RECOVER_WEEK,
        "CRASH_INJECT": POST_RECOVERY_AUTH_COMMIT,
        "CRASH_ACTOR": "ops:fraser",
        "CRASH_EXIT_EVIDENCE": json.dumps(_VALID_EVIDENCE),
    }
    env.update(overrides)
    _assert_guard_refusal(_spawn_child(**env), marker)


def test_child_recover_guard_markers_are_all_distinct():
    """_GUARD_EXIT_CODE is shared with five pre-existing guards, so the marker
    text is the only diagnostic. Two guards sharing one marker would make a
    failure ambiguous."""
    markers = [
        "[CHILD GUARD: ENTRY]",
        "[CHILD GUARD: INJECTION-COMPAT]",
        "[CHILD GUARD: RECOVER-ACTOR-MISSING]",
        "[CHILD GUARD: RECOVER-ACTOR-BLANK]",
        "[CHILD GUARD: RECOVER-EVIDENCE-MISSING]",
        "[CHILD GUARD: RECOVER-EVIDENCE-JSON]",
        "[CHILD GUARD: RECOVER-EVIDENCE-TYPE]",
        "[CHILD GUARD: RECOVER-EVIDENCE-CATEGORY]",
        "[CHILD GUARD: RECOVER-EVIDENCE-DETAIL]",
    ]
    assert len(markers) == len(set(markers))
    with open(_CHILD_PATH, encoding="utf-8") as fh:
        source = fh.read()
    for marker in markers:
        assert source.count(marker) == 1, f"{marker} is not unique in the harness"
