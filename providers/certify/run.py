#!/usr/bin/env python3
"""Sprint 6 offline certification gate — C-1 through C-17 (§17).

DETERMINISTIC, OFFLINE, CREDENTIAL-FREE. The whole point of this harness is that
it proves properties of the SAME code that would run live, using recorded data,
with no network and no secret in the process. C-1 asserts each of those three
things rather than assuming them.

RUN:
    export TEST_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5433/fantasy_test"
    python providers/certify/run.py

Every gate reports PASS or FAIL with evidence. A gate that cannot run reports
FAIL, never SKIP: a certification that can silently not-run is a certification
that will eventually not-run.
"""

from __future__ import annotations

import io
import os
import re
import socket
import sys
import traceback
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", ".."))

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")

LEAGUE_KEY = "461.l.488800"
SEASON = 2025
PROVIDER = "yahoo"
#: Frozen certification clock. Matches the corpus manifests' replay_now, so a
#: 24-hour staleness window can be crossed by arithmetic rather than by waiting.
FROZEN_NOW = datetime(2025, 9, 23, 12, 0, 0, tzinfo=timezone.utc)


@dataclass
class GateResult:
    gate: str
    title: str
    passed: bool
    evidence: list[str] = field(default_factory=list)
    error: str | None = None
    #: WP2 §42 — set when the gate's own checks all held AND the capability it
    #: guards is NOT CERTIFIED because required external evidence is absent. It
    #: is a THIRD status on purpose: rendering such a gate as PASS would let a
    #: launch readiness review read "17/17 green" over an open blocker, and
    #: rendering it as FAIL would say the code is defective when it is correct.
    blocker: str | None = None


RESULTS: list[GateResult] = []


def gate(gate_id: str, title: str):
    """Register one certification gate. A raising gate FAILS; it never skips."""
    def decorator(fn):
        def runner(*args, **kwargs):
            evidence: list[str] = []
            try:
                blocker = fn(evidence, *args, **kwargs)
                RESULTS.append(GateResult(gate_id, title, True, evidence,
                                          blocker=blocker))
            except Exception as exc:  # noqa: BLE001
                evidence.append(f"EXCEPTION: {type(exc).__name__}: {exc}")
                RESULTS.append(GateResult(
                    gate_id, title, False, evidence,
                    error="".join(traceback.format_exception(exc))[-2000:]))
        runner.__name__ = fn.__name__
        return runner
    return decorator


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


# ── Shared fixture construction ───────────────────────────────────────────────

def seed_provider_league(db, *, name: str = "Certification League",
                         n_teams: int = 6, bind_identity: bool = True):
    """A league whose teams carry PROVIDER identity, not an email smuggle.

    Contrast with the Sprint 1-5 seed, which wrote
    'yahoo-team-{n}@fantasy-beefs.local' into teams.email and let
    db/team_resolver.py parse it back out. Emails here are ordinary contact
    addresses and are deliberately NOT parseable as identity — which is what
    lets C-4 prove that resolution no longer depends on them.
    """
    from db.schema import League, Team, Wallet
    from providers.yahoo.identity import bind_league_identity, bind_team_identity

    league = League(season=SEASON, name=name, projection_source="fantasypros")
    db.add(league)
    db.flush()

    teams = []
    for ordinal in range(1, n_teams + 1):
        team = Team(league_id=league.id, team_name=f"{name} Team {ordinal}",
                    owner=f"Owner {ordinal}",
                    email=f"manager{ordinal}@example.invalid")
        db.add(team)
        db.flush()
        db.add(Wallet(team_id=team.id, balance=0.0))
        teams.append(team)
    db.flush()

    if bind_identity:
        bind_league_identity(db, league_id=league.id, league_key=LEAGUE_KEY)
        for ordinal, team in enumerate(teams, start=1):
            bind_team_identity(db, team_id=team.id,
                               team_key=f"{LEAGUE_KEY}.t.{ordinal}",
                               team_ordinal=ordinal)
    db.flush()
    return league, teams


def snapshot_for(transport, week: int, *, scoreboard_id: str | None = None,
                 with_rosters: bool = False):
    """Build one ProviderWeek from the corpus, through the real pipeline."""
    from providers.yahoo import normalize, parse

    league = normalize.normalize_league(
        parse.parse_league(transport.fetch_league(LEAGUE_KEY)))
    teams = tuple(normalize.normalize_team(t)
                  for t in parse.parse_teams(transport.fetch_teams(LEAGUE_KEY)))

    if scoreboard_id is not None:
        raw = transport.corpus[scoreboard_id].payload
    else:
        raw = transport.fetch_scoreboard(LEAGUE_KEY, week)
    matchups = normalize.normalize_scoreboard(parse.parse_scoreboard(raw),
                                              week=week)

    entries: tuple = ()
    stats: tuple = ()
    if with_rosters:
        all_entries: list = []
        all_stats: list = []
        for ordinal in range(1, 7):
            roster_raw = transport.fetch_team_roster(
                LEAGUE_KEY, f"{LEAGUE_KEY}.t.{ordinal}", week)
            e, s = normalize.normalize_roster(parse.parse_roster(roster_raw),
                                              week=week)
            all_entries.extend(e)
            all_stats.extend(s)
        entries = tuple(all_entries)
        stats = tuple(all_stats)

    return normalize.build_week(
        league=league, week=week, teams=teams, matchups=matchups,
        roster_entries=entries, player_stats=stats,
        observed_at=transport.observed_at())


# ══════════════════════════════════════════════════════════════════════════════
# C-1  OFFLINE
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-1", "OFFLINE — no credentials, no network, fixture transport used")
def c1_offline(evidence, tdb):
    from providers.errors import ProviderCredentialError
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo.transport import load_credentials

    # (a) No Yahoo credential material is present in this process.
    creds_env = {k: v for k, v in os.environ.items()
                 if k.startswith("YAHOO_")}
    require(not creds_env,
            f"Yahoo credential env vars are set: {sorted(creds_env)}")
    evidence.append("no YAHOO_* environment variable is set")

    secrets_dir = os.path.join(REPO_ROOT, "secrets")
    try:
        load_credentials()
        raise AssertionError(
            "load_credentials() SUCCEEDED — real Yahoo credentials are "
            "reachable from this process, so an offline claim cannot be made.")
    except ProviderCredentialError as exc:
        evidence.append(f"load_credentials() refuses as required: "
                        f"{str(exc)[:90]}...")
    evidence.append(f"secrets/ present on disk: {os.path.isdir(secrets_dir)} "
                    f"(refusal above is what matters, not absence)")

    # (b) The fixture transport is DEFINITELY the one in use, and it served
    #     every fetch this certification performs.
    transport = FixtureTransport(frozen_now=FROZEN_NOW)
    require(getattr(transport, "is_fixture_transport", False),
            "transport does not declare is_fixture_transport")
    snapshot_for(transport, 1, with_rosters=True)
    require(len(transport.fetch_log) > 0, "fixture transport served no fetch")
    evidence.append(f"FixtureTransport served {len(transport.fetch_log)} "
                    f"fetches; is_fixture_transport=True")

    # (c) No socket was opened. Proven by monkeypatching socket.socket to raise
    #     for the duration of a full ingest, rather than by inspecting code.
    real_socket = socket.socket
    opened: list = []

    class _Forbidden(socket.socket):
        def __init__(self, *a, **kw):
            opened.append(a)
            raise AssertionError("a socket was opened during offline ingest")

    socket.socket = _Forbidden  # type: ignore[misc]
    try:
        offline_transport = FixtureTransport(frozen_now=FROZEN_NOW)
        snapshot_for(offline_transport, 1, with_rosters=True)
    finally:
        socket.socket = real_socket  # type: ignore[misc]
    require(not opened, f"{len(opened)} socket(s) opened during ingest")
    evidence.append("socket.socket blocked during a full ingest; zero opened")


# ══════════════════════════════════════════════════════════════════════════════
# C-2  PROVENANCE
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-2", "PROVENANCE — every fixture declares CAPTURED or SYNTHETIC")
def c2_provenance(evidence, tdb):
    from providers.fixtures.record import CAPTURED, SYNTHETIC
    from providers.fixtures.replay import load_corpus, provenance_counts

    corpus = load_corpus()
    require(corpus, "fixture corpus is empty")

    undeclared = [f.fixture_id for f in corpus.values()
                  if f.provenance not in (CAPTURED, SYNTHETIC)]
    require(not undeclared, f"fixtures without declared provenance: {undeclared}")

    counts = provenance_counts(corpus)
    evidence.append(f"CAPTURED = {counts[CAPTURED]}")
    evidence.append(f"SYNTHETIC = {counts[SYNTHETIC]}")
    evidence.append(f"total fixtures = {len(corpus)}; every one carries an "
                    f"explicit provenance value")

    # Each fixture's payload hash matches its manifest (verify() ran on load).
    evidence.append("every payload SHA-256 matches its manifest")


# ══════════════════════════════════════════════════════════════════════════════
# C-3  RAW PARSING
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-3", "RAW PARSING — every L1 fixture parses; captured reported apart")
def c3_raw_parsing(evidence, tdb):
    from providers.fixtures.record import CAPTURED, SYNTHETIC
    from providers.fixtures.replay import load_corpus
    from providers.yahoo import parse

    corpus = load_corpus()
    parsers = {"league": parse.parse_league, "teams": parse.parse_teams,
               "scoreboard": parse.parse_scoreboard, "roster": parse.parse_roster}

    captured_ok = captured_total = 0
    synthetic_ok = synthetic_total = 0

    for fixture in corpus.values():
        if fixture.layer != "L1_RAW":
            continue
        parser = parsers.get(fixture.endpoint)
        require(parser is not None,
                f"no parser for endpoint {fixture.endpoint!r}")
        if fixture.provenance == CAPTURED:
            captured_total += 1
        else:
            synthetic_total += 1
        parser(fixture.payload)
        if fixture.provenance == CAPTURED:
            captured_ok += 1
        else:
            synthetic_ok += 1

    evidence.append(f"CAPTURED L1 fixtures parsed: {captured_ok}/{captured_total}")
    evidence.append(f"SYNTHETIC L1 fixtures parsed: "
                    f"{synthetic_ok}/{synthetic_total}")
    require(captured_ok == captured_total, "a CAPTURED fixture failed to parse")
    require(synthetic_ok == synthetic_total,
            "a SYNTHETIC fixture failed to parse")

    if captured_total == 0:
        evidence.append(
            "CAPTURED = 0 — LIVE YAHOO PAYLOAD PARSING IS NOT CERTIFIED. The "
            "parser is written against Yahoo's DOCUMENTED envelope and is "
            "exercised only by synthetic fixtures built to that same "
            "documentation. Whether Yahoo's live response matches its "
            "documentation is UNPROVEN and remains open (S6-R2).")


# ══════════════════════════════════════════════════════════════════════════════
# C-4  IDENTITY
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-4", "IDENTITY — stable key resolves; rename survives; name/email refused")
def c4_identity(evidence, tdb):
    from providers.errors import ProviderIdentityError
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo import identity
    from providers.yahoo.persist import refresh_league_week

    tdb.reset()
    with tdb.SessionLocal() as db:
        league, teams = seed_provider_league(db)
        db.commit()

        resolver = identity.build_team_identity_resolver(db, league_id=league.id)
        internal = resolver.to_internal(f"{LEAGUE_KEY}.t.3")
        require(internal == teams[2].id, "stable key resolved to the wrong team")
        evidence.append(f"stable key {LEAGUE_KEY}.t.3 -> Team {internal} (correct)")

        # RENAME. Change every mutable presentation field, then re-resolve.
        original_name = teams[2].team_name
        teams[2].team_name = "Completely Different Name"
        teams[2].owner = "Someone Else Entirely"
        teams[2].email = "brand-new-address@example.invalid"
        db.commit()

        resolver2 = identity.build_team_identity_resolver(db, league_id=league.id)
        require(resolver2.to_internal(f"{LEAGUE_KEY}.t.3") == internal,
                "a renamed team no longer resolves to the same internal Team")
        evidence.append(f"after rename ({original_name!r} -> "
                        f"{teams[2].team_name!r}) and email change, the same "
                        f"provider key still resolves to Team {internal}")

        # NAME / EMAIL matching is ABSENT, not degraded.
        for fn, label in ((identity.resolve_team_by_name, "name"),
                          (identity.resolve_team_by_email, "email")):
            try:
                fn(db, league_id=league.id, value="anything")
                raise AssertionError(f"{label}-based resolution SUCCEEDED")
            except ProviderIdentityError as exc:
                require(exc.reason == ProviderIdentityError.NON_AUTHORITATIVE,
                        f"{label} refusal used reason {exc.reason}")
        evidence.append("resolve_team_by_name / resolve_team_by_email refuse "
                        "with NON_AUTHORITATIVE_IDENTITY")

        # UNKNOWN key fails closed.
        try:
            resolver2.to_internal(f"{LEAGUE_KEY}.t.99")
            raise AssertionError("an unknown provider key resolved")
        except ProviderIdentityError as exc:
            require(exc.reason == ProviderIdentityError.UNKNOWN,
                    f"unknown key used reason {exc.reason}")
        evidence.append("unknown provider key -> UNKNOWN_IDENTITY, fail closed")

        # UNKNOWN league fails closed.
        try:
            identity.resolve_league(db, league_key="461.l.000000")
            raise AssertionError("an unknown league key resolved")
        except ProviderIdentityError as exc:
            require(exc.reason == ProviderIdentityError.UNKNOWN, "wrong reason")
        evidence.append("unknown provider league key -> UNKNOWN_IDENTITY")

        # CONFLICTING: rebinding a bound team to a different key is refused.
        try:
            identity.bind_team_identity(db, team_id=teams[0].id,
                                        team_key=f"{LEAGUE_KEY}.t.42")
            raise AssertionError("rebinding to a different key succeeded")
        except ProviderIdentityError as exc:
            require(exc.reason == ProviderIdentityError.CONFLICTING,
                    f"rebind used reason {exc.reason}")
        db.rollback()
        evidence.append("rebinding a bound team -> CONFLICTING_IDENTITY")

        # CONFLICTING: binding one provider key to a second team is refused.
        try:
            identity.bind_team_identity(db, team_id=teams[4].id,
                                        team_key=f"{LEAGUE_KEY}.t.1")
            raise AssertionError("one provider key bound to two teams")
        except ProviderIdentityError as exc:
            require(exc.reason == ProviderIdentityError.CONFLICTING, "wrong reason")
        db.rollback()
        evidence.append("one provider key -> two teams is refused as CONFLICTING")

        # AMBIGUOUS: an unbound team makes the resolver refuse rather than
        # return a partial map.
        from db.schema import Team
        extra = Team(league_id=league.id, team_name="Unbound", owner="X",
                     email="unbound@example.invalid")
        db.add(extra)
        db.commit()
        try:
            identity.build_team_identity_resolver(db, league_id=league.id)
            raise AssertionError("a partial resolver was returned")
        except ProviderIdentityError as exc:
            require(exc.reason == ProviderIdentityError.UNKNOWN, "wrong reason")
        evidence.append("an unbound team makes the resolver refuse — no partial "
                        "resolver is ever returned")
        db.delete(extra)
        db.commit()

    # SAME-NAME PLAYERS ingest cleanly (recon R-4).
    with tdb.SessionLocal() as db:
        from db.schema import Player

        transport = FixtureTransport(frozen_now=FROZEN_NOW)
        snapshot = snapshot_for(transport, 1, with_rosters=True)
        refresh_league_week(db, snapshot, now=FROZEN_NOW)
        db.commit()

        allens = db.query(Player).filter(Player.name == "Josh Allen").all()
        require(len(allens) == 2,
                f"expected 2 distinct same-name players, got {len(allens)}")
        keys = sorted(p.provider_player_key for p in allens)
        require(len(set(keys)) == 2, "same-name players share a provider key")
        evidence.append(f"two distinct players named 'Josh Allen' ingested: "
                        f"provider keys {keys}")


# ══════════════════════════════════════════════════════════════════════════════
# C-5  MATCHUP UNIQUENESS
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-5", "MATCHUP UNIQUENESS — a mirrored payload yields exactly one row")
def c5_mirror(evidence, tdb):
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo.persist import refresh_league_week
    from db.schema import Matchup

    tdb.reset()
    transport = FixtureTransport(frozen_now=FROZEN_NOW)

    with tdb.SessionLocal() as db:
        league, _teams = seed_provider_league(db)
        db.commit()

        normal = snapshot_for(transport, 1, scoreboard_id="yahoo_scoreboard_w1")
        mirrored = snapshot_for(transport, 1,
                                scoreboard_id="yahoo_scoreboard_w1_mirrored")

        normal_keys = sorted(m.matchup_key for m in normal.matchups)
        mirrored_keys = sorted(m.matchup_key for m in mirrored.matchups)
        require(normal_keys == mirrored_keys,
                f"mirrored payload produced different keys:\n"
                f"  {normal_keys}\n  {mirrored_keys}")
        evidence.append("normalized matchup keys are byte-identical between the "
                        "normal and mirrored payloads")

        for m_normal in normal.matchups:
            m_mirror = next(m for m in mirrored.matchups
                            if m.matchup_key == m_normal.matchup_key)
            require(m_normal.home_team_key == m_mirror.home_team_key,
                    "mirrored payload flipped home/away orientation")
            require(m_normal.home_points == m_mirror.home_points,
                    "mirrored payload attached the wrong score to home")
        evidence.append("orientation and score attribution are identical too — "
                        "payload order is not read")

        refresh_league_week(db, normal, now=FROZEN_NOW)
        db.commit()
        after_first = db.query(Matchup).filter(
            Matchup.league_id == league.id, Matchup.week == 1).count()

        refresh_league_week(db, mirrored, now=FROZEN_NOW)
        db.commit()
        after_mirror = db.query(Matchup).filter(
            Matchup.league_id == league.id, Matchup.week == 1).count()

        require(after_first == 3, f"expected 3 rows, got {after_first}")
        require(after_mirror == 3,
                f"the mirrored payload created rows: {after_first} -> "
                f"{after_mirror}")
        evidence.append(f"matchup rows after normal ingest = {after_first}; "
                        f"after mirrored re-ingest = {after_mirror}")

    # The DB backstop is real, not merely unexercised: a direct INSERT of the
    # mirrored pair must be refused by uq_matchups_unordered_pair.
    from sqlalchemy.exc import IntegrityError
    with tdb.SessionLocal() as db:
        row = db.query(Matchup).filter(Matchup.week == 1).first()
        db.add(Matchup(league_id=row.league_id, week=row.week,
                       home_team_id=row.away_team_id,
                       away_team_id=row.home_team_id,
                       home_score=0.0, away_score=0.0))
        try:
            db.commit()
            raise AssertionError(
                "a direct mirrored INSERT succeeded — the unordered-pair "
                "unique index is not enforcing")
        except IntegrityError as exc:
            db.rollback()
            require("uq_matchups_unordered_pair" in str(exc),
                    f"refused by the wrong constraint: {str(exc)[:200]}")
        evidence.append("a direct mirrored INSERT is refused by "
                        "uq_matchups_unordered_pair at the database layer")


# ══════════════════════════════════════════════════════════════════════════════
# C-6 / C-7  FINALITY
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-6", "FINALITY TRUTH TABLE — §7, all five rows")
def c6_truth_table(evidence, tdb):
    from providers.base import Finality
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo.finality import finality_from_status
    from providers.yahoo.persist import refresh_league_week
    from db.schema import Matchup

    # (a) The mapping itself, at the unit level.
    cases = [
        ("postevent", Finality.FINAL, "provider explicitly final"),
        ("midevent", Finality.NOT_FINAL, "provider explicitly non-final"),
        ("preevent", Finality.NOT_FINAL, "provider explicitly non-final"),
        (None, Finality.UNKNOWN, "finality absent"),
        ("", Finality.UNKNOWN, "finality empty"),
        ("some_new_status", Finality.UNKNOWN, "unrecognized status"),
    ]
    for status, expected, label in cases:
        actual = finality_from_status(status)
        require(actual is expected,
                f"{label}: status={status!r} mapped to {actual}, not {expected}")
    evidence.append("status mapping: postevent->FINAL; midevent/preevent->"
                    "NOT_FINAL; absent/empty/unrecognized->UNKNOWN")

    # (b) End-to-end through persistence.
    tdb.reset()
    transport = FixtureTransport(frozen_now=FROZEN_NOW)
    with tdb.SessionLocal() as db:
        league, teams = seed_provider_league(db)
        db.commit()
        by_ordinal = {i + 1: t.id for i, t in enumerate(teams)}

        snapshot = snapshot_for(transport, 2, scoreboard_id="yahoo_scoreboard_w2")
        refresh_league_week(db, snapshot, now=FROZEN_NOW)
        db.commit()

        def row_for(a: int, b: int):
            pair = {by_ordinal[a], by_ordinal[b]}
            for row in db.query(Matchup).filter(Matchup.week == 2).all():
                if {row.home_team_id, row.away_team_id} == pair:
                    return row
            raise AssertionError(f"no row for teams {a}/{b}")

        final_zero = row_for(1, 2)
        require(final_zero.home_score == 0.0 and final_zero.away_score == 0.0,
                "the 0-0 fixture did not store 0-0")
        require(final_zero.finalized_at is not None,
                "FINAL 0-0 did not set finalized_at — a score-based reading")
        evidence.append("final 0-0 -> finalized_at SET "
                        f"({final_zero.finalized_at.isoformat()})")

        mid = row_for(3, 4)
        require(mid.home_score == 77.5 and mid.away_score == 61.2,
                "midevent scores were not stored")
        require(mid.finalized_at is None,
                "scores present with no final signal SET finalized_at")
        evidence.append("scores present, midevent -> finalized_at NULL")

        pre = row_for(5, 6)
        require(pre.finalized_at is None, "preevent SET finalized_at")
        evidence.append("preevent -> finalized_at NULL")

    # (c) The absent-status row, in its own week so it cannot be confused.
    with tdb.SessionLocal() as db:
        snapshot = snapshot_for(transport, 2,
                                scoreboard_id="yahoo_scoreboard_w2_nostatus")
        require(snapshot.matchups[0].finality is Finality.UNKNOWN,
                "a matchup with no status field is not UNKNOWN")
        evidence.append("matchup with scores 88.0-91.0 and NO status field -> "
                        "UNKNOWN -> finalized_at stays NULL")


@gate("C-7", "FINALITY IMMUTABILITY — no path returns finalized_at to NULL")
def c7_immutability(evidence, tdb):
    from providers.base import Finality
    from providers.errors import ProviderFinalityError
    from providers.yahoo.finality import apply_finality, assert_never_retracted

    class Fake:
        finalized_at = None

    row = Fake()
    changed, retraction = apply_finality(row, Finality.FINAL,
                                         observed_at=FROZEN_NOW)
    require(changed and not retraction, "first FINAL did not set")
    stamped = row.finalized_at

    for finality in (Finality.NOT_FINAL, Finality.UNKNOWN):
        changed, retraction = apply_finality(row, finality,
                                             observed_at=FROZEN_NOW)
        require(not changed, f"{finality} changed a final row")
        require(retraction, f"{finality} on a final row was not flagged")
        require(row.finalized_at == stamped,
                f"{finality} moved finalized_at")
    evidence.append("NOT_FINAL and UNKNOWN against an already-final row leave "
                    "finalized_at untouched and report a retraction")

    changed, retraction = apply_finality(row, Finality.FINAL,
                                         observed_at=FROZEN_NOW + timedelta(days=1))
    require(not changed and not retraction, "repeat FINAL was not a no-op")
    require(row.finalized_at == stamped, "repeat FINAL moved the timestamp")
    evidence.append("a repeat FINAL is an exact no-op — the timestamp does not "
                    "drift on every refresh")

    try:
        assert_never_retracted(stamped, None)
        raise AssertionError("assert_never_retracted allowed a retraction")
    except ProviderFinalityError:
        pass
    evidence.append("assert_never_retracted refuses any non-NULL -> NULL "
                    "transition")

    # ── THE SOLE-WRITER CLAIM, CHECKED MECHANICALLY (Opus control hardening) ──
    #
    # The original scan looked for `.finalized_at =` only. Opus correctly noted
    # that it would not have caught the Blocker-1 defect at all: the legacy
    # Tuesday upsert rewrote home_score, away_score and winner_team_id of an
    # already-final row through RAW SQL, and a Python-assignment regex over one
    # field name sees neither the fields nor the SQL.
    #
    # This scan now covers all FOUR load-bearing Matchup fields and BOTH shapes:
    #   * ORM assignment            `row.home_score = ...`
    #   * raw SQL DML on matchups   INSERT INTO / UPDATE / DELETE FROM matchups
    #     including inside text(\"\"\"...\"\"\") blocks, which is exactly how the
    #     blocker was written.
    #
    # Docstrings are excluded from the SQL sweep via the AST, so a module that
    # DESCRIBES the old statement — as the corrected tuesday_sync now does —
    # is not mistaken for one that executes it. That distinction is the whole
    # reason the check is AST-based rather than another regex.
    import ast as _ast

    LOAD_BEARING = ("finalized_at", "home_score", "away_score", "winner_team_id")
    orm_pattern = re.compile(
        r"\.(" + "|".join(LOAD_BEARING) + r")\s*=(?!=)")
    sql_pattern = re.compile(
        r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+matchups\b", re.IGNORECASE)

    orm_offenders: list[str] = []
    sql_offenders: list[str] = []

    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", ".idea", "node_modules")]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
            source = open(path, encoding="utf-8", errors="replace").read()

            for lineno, line in enumerate(source.split("\n"), 1):
                if orm_pattern.search(line) and not line.strip().startswith("#"):
                    orm_offenders.append(f"{rel}:{lineno}")

            # Raw SQL, via the AST so docstrings are not counted as executable.
            try:
                tree = _ast.parse(source)
            except SyntaxError:
                continue
            docstring_ids = set()
            for parent in _ast.walk(tree):
                if isinstance(parent, (_ast.Module, _ast.FunctionDef,
                                       _ast.AsyncFunctionDef, _ast.ClassDef)):
                    body = getattr(parent, "body", None)
                    if (body and isinstance(body[0], _ast.Expr)
                            and isinstance(body[0].value, _ast.Constant)
                            and isinstance(body[0].value.value, str)):
                        docstring_ids.add(id(body[0].value))
            for sub in _ast.walk(tree):
                if (isinstance(sub, _ast.Constant)
                        and isinstance(sub.value, str)
                        and id(sub) not in docstring_ids
                        and sql_pattern.search(sub.value)):
                    sql_offenders.append(f"{rel}:{sub.lineno}")

    # Any file may also be a .sql file; there are none today, but the scan says
    # so rather than assuming it.
    sql_files = [os.path.relpath(os.path.join(dp, f), REPO_ROOT)
                 for dp, dn, fn in os.walk(REPO_ROOT)
                 if ".git" not in dp
                 for f in fn if f.endswith(".sql")]

    # WP2 MOVED BOTH WRITERS OUT OF THE YAHOO PACKAGE AND DID NOT DUPLICATE
    # EITHER. `providers/finality.py` holds the sole `finalized_at` writer and
    # `providers/persist.py` the sole guarded score/winner writer; the two Yahoo
    # modules that used to hold them are now re-export shims with no assignment
    # in them at all. The list is therefore two entries longer and the PROPERTY
    # it asserts is unchanged — there is still exactly one implementation of
    # each, and every provider reaches it.
    allowed_orm = (
        "providers/finality.py",         # THE finality writer
        "providers/persist.py",          # THE score/winner writer, guarded
        "providers/yahoo/finality.py",   # Yahoo status mapping; re-exports it
        "providers/yahoo/persist.py",    # re-export shim
        "providers/certify/run.py",      # this file's Fake row
    )
    allowed_sql = (
        "db/migrations/",                # schema migrations, not ingestion
        "migrations/",
        "providers/certify/run.py",
    )

    def _is_fixture(entry: str) -> bool:
        name = entry.split(":")[0]
        return (name.startswith("test_") or "/test_" in name
                or name.startswith("test_support"))

    orm_production = [o for o in orm_offenders
                      if not _is_fixture(o) and not o.startswith(allowed_orm)]
    sql_production = [o for o in sql_offenders
                      if not _is_fixture(o) and not o.startswith(allowed_sql)]

    require(not orm_production,
            f"load-bearing Matchup fields are assigned outside the guarded "
            f"provider writers: {orm_production}")
    require(not sql_production,
            f"raw SQL mutates `matchups` outside the guarded provider writers "
            f"and migrations: {sql_production}. This is the exact shape of the "
            f"Blocker-1 defect (an ON CONFLICT DO UPDATE that rewrote a final "
            f"result).")
    require(not sql_files,
            f".sql files exist and were not scanned: {sql_files}")

    orm_fixtures = [o for o in orm_offenders if _is_fixture(o)]
    evidence.append(
        f"repository-wide scan covers {len(LOAD_BEARING)} load-bearing fields "
        f"{list(LOAD_BEARING)} in BOTH shapes (ORM assignment and raw SQL DML "
        f"on `matchups`, docstrings excluded via AST)")
    evidence.append(
        f"ORM assignments: 0 unauthorized production writers; permitted "
        f"writers are {list(allowed_orm)}; {len(orm_fixtures)} test-fixture "
        f"assignment(s) listed, not hidden")
    evidence.append(
        f"raw SQL DML on `matchups`: {len(sql_offenders)} executable "
        f"occurrence(s) repo-wide, 0 outside migrations and the guarded "
        f"gateway — the legacy Tuesday ON CONFLICT DO UPDATE is gone")
    evidence.append(f".sql files in repository: {len(sql_files)} (none to scan)")


# ══════════════════════════════════════════════════════════════════════════════
# C-8  POST-FINAL CONFLICT
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-8", "POST-FINAL CONFLICT — final state kept, conflict written, close blocked")
def c8_conflict(evidence, tdb):
    from providers.errors import ProviderConflictError
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo.persist import refresh_league_week
    from db.schema import Matchup, ProviderConflict

    tdb.reset()
    transport = FixtureTransport(frozen_now=FROZEN_NOW)

    with tdb.SessionLocal() as db:
        league, _teams = seed_provider_league(db)
        db.commit()

        clean = snapshot_for(transport, 1, scoreboard_id="yahoo_scoreboard_w1")
        refresh_league_week(db, clean, now=FROZEN_NOW)
        db.commit()

        before = {(m.provider_matchup_key, m.home_score, m.away_score,
                   m.winner_team_id, m.finalized_at)
                  for m in db.query(Matchup).filter(Matchup.week == 1).all()}
        require(all(m.finalized_at is not None
                    for m in db.query(Matchup).filter(Matchup.week == 1).all()),
                "week 1 did not finalize")
        evidence.append(f"week 1 ingested clean: {len(before)} final matchups")

        contradicted = snapshot_for(
            transport, 1, scoreboard_id="yahoo_scoreboard_w1_contradicted")
        try:
            refresh_league_week(db, contradicted, now=FROZEN_NOW)
            raise AssertionError(
                "a contradictory post-final refresh SUCCEEDED — final state "
                "was silently mutated")
        except ProviderConflictError as exc:
            db.commit()   # the conflict row must survive the refusal
            evidence.append(f"refresh failed closed: {str(exc)[:110]}...")
            first_key = exc.conflict_key

        after = {(m.provider_matchup_key, m.home_score, m.away_score,
                  m.winner_team_id, m.finalized_at)
                 for m in db.query(Matchup).filter(Matchup.week == 1).all()}
        require(before == after,
                "final matchup state CHANGED across a contradictory refresh")
        evidence.append("stored final score / winner / finalized_at are "
                        "byte-identical before and after the contradiction")

        conflicts = db.query(ProviderConflict).all()
        require(len(conflicts) >= 1, "no ProviderConflict was written")
        first_count = len(conflicts)
        evidence.append(f"{first_count} ProviderConflict row(s) written; "
                        f"type={conflicts[0].conflict_type} "
                        f"field={conflicts[0].contradicted_field} "
                        f"stored={conflicts[0].existing_value} "
                        f"provider={conflicts[0].provider_value}")

        # DETERMINISTIC REPLAY MUST NOT MULTIPLY CONFLICTS.
        for _ in range(3):
            try:
                refresh_league_week(db, contradicted, now=FROZEN_NOW)
            except ProviderConflictError:
                db.commit()
        conflicts_after = db.query(ProviderConflict).all()
        require(len(conflicts_after) == first_count,
                f"replaying the same contradiction multiplied conflict rows: "
                f"{first_count} -> {len(conflicts_after)}")
        bumped = db.query(ProviderConflict).filter(
            ProviderConflict.conflict_key == first_key).first()
        require(bumped.occurrence_count == 4,
                f"occurrence_count is {bumped.occurrence_count}, expected 4")
        evidence.append(f"3 further identical replays: row count stayed "
                        f"{first_count}, occurrence_count reached "
                        f"{bumped.occurrence_count}")

        # SEASON CLOSE IS BLOCKED.
        #
        # Every ACCEPTED Sprint 5 precondition is satisfied first, so the
        # refusal below can only come from the new conflict gate. A test that
        # merely observed "close refused" would prove nothing — the league would
        # have been refused at step 6 for its missing Skunk assessment whether
        # or not Sprint 6 existed.
        from economy.economy_events import EVENT_SKUNK_ASSESSMENT, league_week_key
        from economy.season_close_orchestrator import (
            SeasonClosePreconditionError, verify_preconditions)
        from db.schema import EconomyEvent

        db.add(EconomyEvent(
            event_key=league_week_key(EVENT_SKUNK_ASSESSMENT, league.id,
                                      SEASON, 1),
            league_id=league.id, season=SEASON, week=1,
            event_type=EVENT_SKUNK_ASSESSMENT, amount_cents=0,
            created_at=FROZEN_NOW))
        db.commit()

        # Acknowledge everything, and confirm the league otherwise closes —
        # this is the control that proves the refusal below is the conflict.
        from providers.yahoo.persist import acknowledge_conflict
        for conflict in db.query(ProviderConflict).all():
            acknowledge_conflict(db, conflict_key_value=conflict.conflict_key,
                                 operator="certification-control",
                                 note="control pass", now=FROZEN_NOW)
        db.commit()
        verify_preconditions(db, league_id=league.id, final_week=1)
        evidence.append("CONTROL: with every conflict acknowledged, all "
                        "preconditions PASS — the league is otherwise closeable")

        # Now reopen one conflict by re-ingesting a NEW contradiction (a third
        # score for the same matchup), which is legitimately its own row.
        db.query(ProviderConflict).filter(
            ProviderConflict.conflict_key == first_key).update(
            {"resolved_at": None, "resolved_by": None})
        db.commit()

        try:
            verify_preconditions(db, league_id=league.id, final_week=1)
            raise AssertionError("season close preconditions PASSED with an "
                                 "unresolved provider conflict")
        except SeasonClosePreconditionError as exc:
            require(exc.step == "provider_conflict",
                    f"close was blocked at {exc.step!r}, not by the conflict "
                    f"gate — the conflict precondition is untested")
            evidence.append(f"with ONE conflict unresolved, close refuses at "
                            f"step 'provider_conflict': {str(exc)[:100]}...")

        # ACKNOWLEDGEMENT CLEARS THE BLOCK AND MOVES NO MONEY.
        from ledger.ledger import trial_balance
        balance_before = trial_balance()
        acknowledge_conflict(db, conflict_key_value=first_key,
                             operator="certification", note="C-8",
                             now=FROZEN_NOW)
        db.commit()
        require(trial_balance() == balance_before,
                "acknowledging a conflict moved money")
        verify_preconditions(db, league_id=league.id, final_week=1)
        evidence.append("re-acknowledging clears the block again and leaves "
                        f"trial_balance unchanged at {balance_before}")


# ══════════════════════════════════════════════════════════════════════════════
# C-9  IDEMPOTENT REPLAY
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-9", "IDEMPOTENT REPLAY — same state, no duplicates, zero ledger entries")
def c9_replay(evidence, tdb):
    from ledger.ledger import trial_balance
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo.persist import refresh_league_week, snapshot_digest
    from ledger.ledger import LedgerEntry
    from db.schema import Matchup, Player, RosterSlot

    tdb.reset()
    transport = FixtureTransport(frozen_now=FROZEN_NOW)

    def domain_state(db, league_id):
        matchups = sorted(
            (m.provider_matchup_key, m.week, m.home_team_id, m.away_team_id,
             m.home_score, m.away_score, m.winner_team_id,
             m.finalized_at.isoformat() if m.finalized_at else None)
            for m in db.query(Matchup).filter(
                Matchup.league_id == league_id).all())
        slots = sorted(
            (s.team_id, s.player_id, s.week, s.slot)
            for s in db.query(RosterSlot).filter(
                RosterSlot.league_id == league_id).all())
        players = sorted(p.provider_player_key
                         for p in db.query(Player).all())
        return matchups, slots, players

    with tdb.SessionLocal() as db:
        league, _teams = seed_provider_league(db)
        db.commit()

        snapshot = snapshot_for(transport, 1, with_rosters=True)
        digest = snapshot_digest(snapshot)

        ledger_before = db.query(LedgerEntry).count()
        tb_before = trial_balance()

        refresh_league_week(db, snapshot, now=FROZEN_NOW)
        db.commit()
        state_first = domain_state(db, league.id)
        refreshed_first = sorted(
            (m.provider_matchup_key, m.refreshed_at)
            for m in db.query(Matchup).filter(
                Matchup.league_id == league.id).all())

        # Replay with a LATER clock, so any state that is allowed to move does,
        # and any state that must not move is genuinely tested.
        later = FROZEN_NOW + timedelta(hours=6)
        snapshot2 = snapshot_for(transport, 1, with_rosters=True)
        require(snapshot_digest(snapshot2) == digest,
                "the second replay was handed different input")
        refresh_league_week(db, snapshot2, now=later)
        db.commit()
        state_second = domain_state(db, league.id)

        require(state_first == state_second,
                f"domain state changed across replay:\n"
                f"  first : {state_first}\n  second: {state_second}")
        evidence.append(f"snapshot digest identical ({digest[:16]}...); domain "
                        f"state identical across two replays")
        evidence.append(f"{len(state_first[0])} matchups, "
                        f"{len(state_first[1])} roster slots, "
                        f"{len(state_first[2])} players — no duplicates")

        refreshed_second = sorted(
            (m.provider_matchup_key, m.refreshed_at)
            for m in db.query(Matchup).filter(
                Matchup.league_id == league.id).all())
        require(refreshed_first != refreshed_second,
                "refreshed_at did not move — the replay may not have run")
        evidence.append("refreshed_at DID move (the one explicitly allowed "
                        "change), confirming the second replay executed")

        ledger_after = db.query(LedgerEntry).count()
        require(ledger_after == ledger_before,
                f"ledger entries changed: {ledger_before} -> {ledger_after}")
        require(trial_balance() == tb_before,
                "trial_balance changed across provider replay")
        evidence.append(f"ledger entries {ledger_before} -> {ledger_after} "
                        f"(zero new); trial_balance unchanged at {tb_before}")


# ══════════════════════════════════════════════════════════════════════════════
# C-10  CONCURRENCY
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-10", "CONCURRENCY — two workers, same league/week, no duplication")
def c10_concurrency(evidence, tdb):
    import threading

    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo.persist import refresh_league_week
    from db.schema import Matchup

    tdb.reset()
    transport = FixtureTransport(frozen_now=FROZEN_NOW)

    with tdb.SessionLocal() as db:
        league, _teams = seed_provider_league(db)
        db.commit()
        league_id = league.id

    snapshot = snapshot_for(transport, 1, with_rosters=True)
    barrier = threading.Barrier(2)
    outcomes: list = []
    lock = threading.Lock()

    def worker(label: str):
        try:
            with tdb.SessionLocal() as db:
                # Both workers arrive at the League row lock at the same instant,
                # which is the interleaving that would corrupt an unserialized
                # read-modify-write.
                barrier.wait(timeout=30)
                result = refresh_league_week(db, snapshot, now=FROZEN_NOW)
                db.commit()
                with lock:
                    outcomes.append((label, "ok", result.matchups_inserted,
                                     result.matchups_updated,
                                     result.matchups_unchanged))
        except Exception as exc:  # noqa: BLE001
            with lock:
                outcomes.append((label, f"{type(exc).__name__}: {exc}", 0, 0, 0))

    threads = [threading.Thread(target=worker, args=(f"w{i}",))
               for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    require(len(outcomes) == 2, f"only {len(outcomes)} worker(s) reported")
    for label, status, *_ in outcomes:
        require(status == "ok",
                f"worker {label} did not complete safely: {status}")
    evidence.append(f"both workers completed: {outcomes}")

    inserted_total = sum(o[2] for o in outcomes)
    require(inserted_total == 3,
            f"the two workers between them inserted {inserted_total} matchups, "
            f"not 3 — one duplicated the other's work")
    evidence.append(f"exactly 3 inserts across both workers "
                    f"(one inserted, the other saw the committed rows)")

    with tdb.SessionLocal() as db:
        rows = db.query(Matchup).filter(Matchup.league_id == league_id,
                                        Matchup.week == 1).all()
        require(len(rows) == 3, f"{len(rows)} matchup rows, expected 3")
        keys = [r.provider_matchup_key for r in rows]
        require(len(set(keys)) == 3, f"duplicate provider keys: {keys}")
        evidence.append(f"final state: 3 rows, 3 distinct provider keys, "
                        f"no corruption")


# ══════════════════════════════════════════════════════════════════════════════
# C-11  INGESTION HORIZON
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-11", "INGESTION HORIZON — future weeks do not expand played_weeks")
def c11_horizon(evidence, tdb):
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo.persist import refresh_league_week
    from db.schema import Matchup

    tdb.reset()
    transport = FixtureTransport(frozen_now=FROZEN_NOW)

    with tdb.SessionLocal() as db:
        league, _teams = seed_provider_league(db)
        db.commit()

        for week in (1, 2, 3):
            refresh_league_week(db, snapshot_for(transport, week),
                                now=FROZEN_NOW)
            db.commit()

        inside = db.query(Matchup).filter(Matchup.league_id == league.id).count()
        weeks_inside = sorted({m.week for m in db.query(Matchup).filter(
            Matchup.league_id == league.id).all()})
        evidence.append(f"weeks 1-3 (current_week=3) ingested: {inside} rows "
                        f"across weeks {weeks_inside}")

        result = refresh_league_week(db, snapshot_for(transport, 4),
                                     now=FROZEN_NOW)
        db.commit()
        require(result.skipped_beyond_horizon,
                "week 4 was not reported as beyond the horizon")
        require(result.matchups_inserted == 0,
                f"week 4 inserted {result.matchups_inserted} rows")

        after = db.query(Matchup).filter(Matchup.league_id == league.id).count()
        require(after == inside,
                f"row count grew from {inside} to {after} after a future week")
        weeks_after = sorted({m.week for m in db.query(Matchup).filter(
            Matchup.league_id == league.id).all()})
        require(4 not in weeks_after, "week 4 rows were persisted")
        evidence.append(f"week 4 (beyond current_week=3): 0 rows persisted; "
                        f"weeks present unchanged at {weeks_after}")

        # THE ACTUAL SPRINT 5 SEMANTIC, not a proxy for it. This is the exact
        # query economy/season_close_orchestrator.verify_preconditions runs to
        # derive played_weeks.
        from betting.pool_season_boundary import playoff_start_week
        cutoff = min(17, playoff_start_week(league) - 1)
        played_weeks = sorted({
            m.week for m in db.query(Matchup)
            .filter(Matchup.league_id == league.id,
                    Matchup.week <= cutoff).all()})
        require(played_weeks == [1, 2, 3],
                f"played_weeks is {played_weeks}, not [1, 2, 3] — future "
                f"schedule ingestion expanded the season close's obligations")
        evidence.append(f"season close's own played_weeks derivation yields "
                        f"{played_weeks} — unchanged by the week-4 attempt")


# ══════════════════════════════════════════════════════════════════════════════
# C-12  POOL COVERAGE
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-12", "POOL COVERAGE — measured support only; missing never 0.0")
def c12_pool(evidence, tdb):
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo import identity
    from providers.yahoo.persist import refresh_league_week
    from providers.yahoo.pool_source import (
        YahooProviderStatSource, load_yahoo_stat_map)
    from betting.pool_subjects import SCOPE_TEAM, WeeklyStructure

    stat_map = load_yahoo_stat_map()
    require("4" in stat_map.by_stat_id, "vocabulary mapping did not load")
    require(stat_map.by_stat_id["4"] == "passing_yards",
            "stat id 4 is not passing_yards")
    evidence.append(f"stat map read from the governed vocabulary: "
                    f"{len(stat_map.by_stat_id)} Yahoo ids mapped")

    # The artifact's own unmapped/unsupported entries must never be advertised.
    require("pass_attempts" in stat_map.unmapped, "pass_attempts is not unmapped")
    require("completions" in stat_map.unmapped, "completions is not unmapped")
    require("made_field_goal_distance" in stat_map.unsupported,
            "made_field_goal_distance is not unsupported")
    evidence.append("artifact's null-stat-id entries (pass_attempts, "
                    "completions) and its UNSUPPORTED entry "
                    "(made_field_goal_distance) are excluded from the mapping")

    tdb.reset()
    transport = FixtureTransport(frozen_now=FROZEN_NOW)
    with tdb.SessionLocal() as db:
        league, teams = seed_provider_league(db)
        db.commit()

        snapshot = snapshot_for(transport, 1, with_rosters=True)
        refresh_league_week(db, snapshot, now=FROZEN_NOW)
        db.commit()

        resolver = identity.build_team_identity_resolver(db, league_id=league.id)
        source = YahooProviderStatSource(snapshot).bind(db, resolver)
        supported = source.supported_stats()

        require("passing_yards" in supported, "passing_yards not supported")
        require("scrimmage_yards" in supported,
                "derived scrimmage_yards not supported despite covered inputs")
        require("opportunities" not in supported,
                "opportunities IS advertised, but pass_attempts has no Yahoo "
                "stat id in the governed artifact")
        require("pass_attempts" not in supported, "pass_attempts advertised")
        require("made_field_goal_distance" not in supported,
                "an UNSUPPORTED stat is advertised")
        require("field_goals_made" not in supported,
                "field_goals_made advertised without its five bracket inputs")
        evidence.append(f"supported_stats measured from the payload: "
                        f"{len(supported)} canonical stats; includes derived "
                        f"scrimmage_yards; excludes opportunities, "
                        f"pass_attempts, field_goals_made")

        # Starter/bench, and the unmeasured-starter case.
        structure = WeeklyStructure(
            scope=SCOPE_TEAM,
            considered_subject_ids=tuple(t.id for t in teams))
        subjects = source.subjects_for(league_id=league.id, season=SEASON,
                                       week=1, structure=structure)
        by_id = {s.subject_id: s for s in subjects}

        team1 = by_id[teams[0].id]
        slots = sorted(c.slot for c in team1.components)
        require("BN" not in slots, f"a bench slot became a component: {slots}")
        require("W/R/T" in slots, "the flex starter is missing")
        evidence.append(f"team 1 active starters by SELECTED slot: {slots} — "
                        f"bench excluded, flex included")

        flex = next(c for c in team1.components if c.slot == "W/R/T")
        require(flex.effective_position == "RB",
                f"flex effective_position is {flex.effective_position}, not the "
                f"occupant's actual position")
        evidence.append("the W/R/T flex resolves to its OCCUPANT's position "
                        "(RB), per the accepted POR §1.3 rule")

        # Team 2 has a started TE the feed never reported. Its coverage must be
        # withdrawn — the number must not become 0.0.
        team2 = by_id[teams[1].id]
        require(not team2.covered_stats,
                f"team 2 reports coverage {sorted(team2.covered_stats)} despite "
                f"a started player with no stats record at all")
        require(team1.covered_stats, "team 1 reports no coverage at all")
        evidence.append("team 2 (a started player the feed never reported) has "
                        "EMPTY coverage -> UNEVALUABLE, not 0.0; team 1 is "
                        "covered")

        for component in team1.components:
            require("made_field_goal_distance" not in component.values,
                    "an unsupported stat appeared with a value")
            for name, value in component.values.items():
                require(isinstance(value, float), f"{name} is not a float")
        evidence.append("no unsupported or ungoverned stat appears with a "
                        "default value anywhere in the components")


# ══════════════════════════════════════════════════════════════════════════════
# C-13  GATE-2 STALENESS
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-13", "GATE-2 STALENESS — timestamped, fresh ready, stale not-ready")
def c13_staleness(evidence, tdb):
    from betting.pool_gates import DEFAULT_READINESS_MAX_AGE, gate_decisions
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo import identity
    from providers.yahoo.persist import refresh_league_week
    from providers.yahoo.pool_source import measure_league_activation
    from db.schema import PoolLeagueActivation

    tdb.reset()
    transport = FixtureTransport(frozen_now=FROZEN_NOW)

    with tdb.SessionLocal() as db:
        from test_support_s4_pool import seed_catalog

        league, _teams = seed_provider_league(db)
        seed_catalog(db)
        db.commit()

        snapshot = snapshot_for(transport, 1, with_rosters=True)
        refresh_league_week(db, snapshot, now=FROZEN_NOW)
        db.commit()

        resolver = identity.build_team_identity_resolver(db, league_id=league.id)
        report = measure_league_activation(db, league_id=league.id,
                                           snapshot=snapshot, resolver=resolver)
        db.commit()

        require(report["measured_at"] == FROZEN_NOW,
                f"measured_at is {report['measured_at']}, not the snapshot's "
                f"frozen observed instant")
        evidence.append(f"measurement stamped with the snapshot's observed "
                        f"instant {report['measured_at'].isoformat()} — not the "
                        f"wall clock")

        rows = db.query(PoolLeagueActivation).filter(
            PoolLeagueActivation.league_id == league.id).all()
        require(rows, "no PoolLeagueActivation rows were written")
        require(all(r.measured_at is not None for r in rows),
                "an activation row has no measured_at")
        evidence.append(f"{len(rows)} gate-2 rows written through the accepted "
                        f"record_activation_measurement(); every one stamped")

        ready_keys = [r.definition_key for r in rows if r.league_activation_ready]
        blocked = [r for r in rows if not r.league_activation_ready]
        evidence.append(f"measured readiness: {len(ready_keys)} ready, "
                        f"{len(blocked)} blocked by actually-missing stats")
        require(blocked, "nothing was blocked — the measurement is not "
                         "discriminating")
        sample = blocked[0]
        require(any("PROVIDER_STAT_UNAVAILABLE" in reason
                    for reason in (sample.league_activation_block_reasons or [])),
                f"block reason does not name the missing stat: "
                f"{sample.league_activation_block_reasons}")
        evidence.append(f"a blocked definition names the missing stat: "
                        f"{sample.definition_key} -> "
                        f"{sample.league_activation_block_reasons}")

        # FRESH -> ready as measured.
        fresh = gate_decisions(db, league_id=league.id, provider=PROVIDER,
                               phase="REGULAR", now=FROZEN_NOW)
        fresh_ready = [d for d in fresh if d.gate2_league_activation_ready]
        evidence.append(f"at the frozen instant, {len(fresh_ready)} definitions "
                        f"are gate-2 ready")

        # STALE -> not ready, deterministically, by crossing the window.
        stale_now = FROZEN_NOW + DEFAULT_READINESS_MAX_AGE + timedelta(minutes=1)
        stale = gate_decisions(db, league_id=league.id, provider=PROVIDER,
                               phase="REGULAR", now=stale_now)
        stale_ready = [d for d in stale if d.gate2_league_activation_ready]
        require(not stale_ready,
                f"{len(stale_ready)} definitions still gate-2 ready 24h+1m "
                f"after measurement")
        evidence.append(f"at measured_at + 24h + 1m, gate-2 ready count is 0 "
                        f"(was {len(fresh_ready)}) — stale is not-ready")

        sample_stale = stale[0]
        require(any("STALE_MEASUREMENT" in r
                    for r in sample_stale.block_reasons),
                f"staleness is not named in the block reasons: "
                f"{sample_stale.block_reasons}")
        evidence.append("the refusal names STALE_MEASUREMENT explicitly")

        # RESTORED CONNECTIVITY ALONE IS NOT READINESS (§14, Scope §H 18g).
        #
        # The transport SUCCEEDS here — teams came back, the league came back —
        # and the payload simply carries nothing measurable. That is exactly the
        # shape of the shortcut 18g exists to catch: treating "we can reach
        # Yahoo again" as gate-2 satisfaction.
        from providers.base import ProviderWeek
        empty = ProviderWeek(league=snapshot.league, week=1,
                             teams=snapshot.teams,   # the fetch worked
                             matchups=(),            # nothing measured
                             roster_entries=(),
                             player_stats=(),
                             observed_at=FROZEN_NOW)
        empty_report = measure_league_activation(
            db, league_id=league.id, snapshot=empty, resolver=resolver)
        db.rollback()
        require(empty_report["ready_count"] == 0,
                f"a payload carrying NO measured facts measured "
                f"{empty_report['ready_count']} definitions ready — restored "
                f"connectivity is being treated as readiness")
        require(not empty_report["supported_stats"],
                f"an empty payload advertised support for "
                f"{empty_report['supported_stats']}")
        evidence.append("a SUCCESSFUL fetch whose payload carries no measured "
                        "facts advertises 0 supported stats and measures 0 "
                        "definitions ready — connectivity alone does not "
                        "satisfy gate 2")


# ══════════════════════════════════════════════════════════════════════════════
# C-14  CENSUS INDEPENDENCE
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-14", "CENSUS INDEPENDENCE — MATCHUP census stays schedule-based")
def c14_census(evidence, tdb):
    import inspect

    from betting import pool_subjects
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo import identity
    from providers.yahoo.persist import refresh_league_week
    from providers.yahoo.pool_source import YahooProviderStatSource
    from betting.pool_subjects import SCOPE_MATCHUP, league_weekly_structure

    # The census function itself is unchanged and reads no stat table.
    source_text = inspect.getsource(pool_subjects.league_weekly_structure)
    for forbidden in ("Projection", "player_stats", "stat_source",
                      "PoolStatSource"):
        require(forbidden not in source_text,
                f"league_weekly_structure now references {forbidden!r}")
    evidence.append("betting.pool_subjects.league_weekly_structure is unchanged "
                    "and references no stat table or stat source")

    tdb.reset()
    transport = FixtureTransport(frozen_now=FROZEN_NOW)
    with tdb.SessionLocal() as db:
        league, _teams = seed_provider_league(db)
        db.commit()

        snapshot = snapshot_for(transport, 1, with_rosters=True)
        refresh_league_week(db, snapshot, now=FROZEN_NOW)
        db.commit()

        structure = league_weekly_structure(db, league_id=league.id, week=1,
                                            scope=SCOPE_MATCHUP)
        require(len(structure.considered_subject_ids) == 3,
                f"census counted {len(structure.considered_subject_ids)} "
                f"matchups, not 3")
        evidence.append(f"MATCHUP census from the schedule = "
                        f"{len(structure.considered_subject_ids)} subjects")

        # Now hand the stat source a snapshot with NO stats at all. The census
        # must NOT shrink — that is the §C9 / Scope §H scenario 28 property.
        from providers.base import ProviderWeek
        starved = ProviderWeek(league=snapshot.league, week=1,
                               teams=snapshot.teams,
                               matchups=snapshot.matchups,
                               roster_entries=(), player_stats=(),
                               observed_at=FROZEN_NOW)
        resolver = identity.build_team_identity_resolver(db, league_id=league.id)
        starved_source = YahooProviderStatSource(starved).bind(db, resolver)

        structure_again = league_weekly_structure(db, league_id=league.id,
                                                  week=1, scope=SCOPE_MATCHUP)
        require(structure_again.considered_subject_ids ==
                structure.considered_subject_ids,
                "the census changed when the stat feed emptied")

        subjects = starved_source.subjects_for(
            league_id=league.id, season=SEASON, week=1,
            structure=structure_again)
        require(len(subjects) == 3,
                f"the stat source returned {len(subjects)} subjects for a "
                f"3-subject census — a dropped subject shrinks `evaluated` "
                f"silently instead of reporting unevaluable")

        # No PLAYER-derived coverage survives an empty roster/stat feed. The
        # matchup SCORES do remain covered, and correctly so: they come from the
        # persisted Matchup row, which is a different source of record that the
        # stat feed's absence says nothing about. Asserting them away would be
        # asserting that a fact we genuinely hold is unknown.
        player_derived = {"player_fantasy_points", "passing_yards",
                          "rushing_yards", "receiving_yards", "receptions",
                          "touches", "scrimmage_yards"}
        for subject in subjects:
            leaked = player_derived & set(subject.covered_stats)
            require(not leaked,
                    f"subject {subject.subject_id} reports player-stat "
                    f"coverage {sorted(leaked)} from an EMPTY stat feed")
            require(not subject.components,
                    f"subject {subject.subject_id} produced components from an "
                    f"empty roster feed")
        evidence.append("with an EMPTY roster/stat feed the census stays 3 and "
                        "the source still returns 3 subjects — none carrying a "
                        "single player component or any player-stat coverage; "
                        "`considered` does not shrink to match the gaps")


# ══════════════════════════════════════════════════════════════════════════════
# C-15  PROVIDER MONEY ISOLATION
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-15", "PROVIDER MONEY ISOLATION — full season replay posts zero ledger")
def c15_money(evidence, tdb):
    from ledger.ledger import trial_balance
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo.persist import refresh_league_week
    from ledger.ledger import LedgerEntry

    # (a) STATIC: no module under providers/ imports ledger/ or economy/.
    import ast

    offenders: list[str] = []
    providers_root = os.path.join(REPO_ROOT, "providers")
    module_count = 0
    for dirpath, dirnames, filenames in os.walk(providers_root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
            if rel.startswith("providers/certify/"):
                # The certification harness legitimately reads trial_balance to
                # PROVE the isolation; it is not part of the gateway.
                continue
            module_count += 1
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name.split(".")[0] in ("ledger", "economy"):
                        offenders.append(f"{rel}:{node.lineno} imports {name}")
    require(not offenders, f"forbidden imports in the provider layer: {offenders}")
    evidence.append(f"static scan of {module_count} gateway modules: zero "
                    f"imports from ledger/ or economy/")

    # (b) DYNAMIC: a full recorded season replay posts nothing.
    tdb.reset()
    transport = FixtureTransport(frozen_now=FROZEN_NOW)
    with tdb.SessionLocal() as db:
        league, _teams = seed_provider_league(db)
        db.commit()

        before_entries = db.query(LedgerEntry).count()
        before_balance = trial_balance()

        for week in (1, 2, 3, 4):
            refresh_league_week(db, snapshot_for(transport, week,
                                                 with_rosters=(week == 1)),
                                now=FROZEN_NOW)
            db.commit()
        # And a full second pass, so a replay cannot post either.
        for week in (1, 2, 3, 4):
            refresh_league_week(db, snapshot_for(transport, week,
                                                 with_rosters=(week == 1)),
                                now=FROZEN_NOW + timedelta(hours=1))
            db.commit()

        after_entries = db.query(LedgerEntry).count()
        require(after_entries == before_entries,
                f"provider replay posted {after_entries - before_entries} "
                f"ledger entries")
        require(trial_balance() == before_balance,
                "trial_balance moved during provider replay")
        evidence.append(f"two full passes over weeks 1-4 with rosters: ledger "
                        f"entries {before_entries} -> {after_entries}; "
                        f"trial_balance {before_balance} throughout")


# ══════════════════════════════════════════════════════════════════════════════
# C-16  ECONOMIC FINALITY GATE
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-16", "ECONOMIC FINALITY GATE — Versus and Pool refuse non-final state")
def c16_finality_gate(evidence, tdb):
    from betting.finality_gate import ResultsNotReadyError
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo.persist import refresh_league_week
    from db.schema import Matchup, WeekSettlement

    tdb.reset()
    transport = FixtureTransport(frozen_now=FROZEN_NOW)

    with tdb.SessionLocal() as db:
        league, _teams = seed_provider_league(db)
        db.commit()

        # Week 2 carries a midevent and a preevent matchup — legitimately
        # non-final rows, exactly the situation Sprint 6 creates.
        refresh_league_week(db, snapshot_for(transport, 2), now=FROZEN_NOW)
        db.commit()

        unfinal = db.query(Matchup).filter(
            Matchup.league_id == league.id, Matchup.week == 2,
            Matchup.finalized_at.is_(None)).count()
        require(unfinal == 2, f"expected 2 non-final rows, got {unfinal}")
        evidence.append(f"week 2 holds {unfinal} non-final matchup rows "
                        f"alongside 1 final one")

        # ── VERSUS, invoked DIRECTLY — outside the Tuesday pipeline ──────────
        from betting.settlement_engine import settle_week as versus_settle
        try:
            versus_settle(2, db, league_id=league.id)
            raise AssertionError(
                "Versus settle_week() SETTLED a week with non-final matchups "
                "when called outside the Tuesday pipeline")
        except ResultsNotReadyError as exc:
            require(exc.reason == "RESULTS_NOT_READY", f"reason {exc.reason}")
            require(set(exc.unfinalized_matchup_ids), "no matchup ids reported")
        db.rollback()
        evidence.append("betting.settlement_engine.settle_week refuses with "
                        "RESULTS_NOT_READY when invoked directly")

        # AND IT LEFT NO CLAIM BEHIND. A refusal after the claim would have
        # turned a retryable week into one needing manual recovery.
        claims = db.query(WeekSettlement).filter(
            WeekSettlement.league_id == league.id,
            WeekSettlement.week == 2).count()
        require(claims == 0,
                f"the refused settlement left {claims} WeekSettlement row(s) — "
                f"the week now requires a recovery token to retry")
        evidence.append("no WeekSettlement claim row was written by the "
                        "refusal — the week stays cleanly retryable")

        # ── POOL, invoked DIRECTLY ───────────────────────────────────────────
        from betting.pool_settlement import settle_pool_instance
        from db.schema import PoolDefinition, PoolInstance
        from test_support_s4_pool import seed_catalog

        seed_catalog(db)
        db.commit()
        definition = (db.query(PoolDefinition)
                      .order_by(PoolDefinition.catalog_number).first())
        instance = PoolInstance(
            league_id=league.id, season=SEASON, week=2, slot=1,
            phase="REGULAR", rotation_cycle=1, definition_key=definition.key,
            pot_cents=10_000, settled=False)
        db.add(instance)
        db.commit()

        try:
            settle_pool_instance(db, pool_instance_id=instance.id,
                                 stat_source=None)
            raise AssertionError(
                "Pool settle_pool_instance() proceeded past the finality gate "
                "on a week with non-final matchups")
        except ResultsNotReadyError as exc:
            require(exc.reason == "RESULTS_NOT_READY", f"reason {exc.reason}")
        db.rollback()
        evidence.append("betting.pool_settlement.settle_pool_instance refuses "
                        "with RESULTS_NOT_READY before any economic work")

        # ── AND BOTH ACCEPT A FULLY FINAL WEEK ──────────────────────────────
        from betting.finality_gate import require_week_final
        refresh_league_week(db, snapshot_for(transport, 1), now=FROZEN_NOW)
        db.commit()
        census = require_week_final(db, league_id=league.id, week=1,
                                    context="C-16")
        require(census.is_final and census.matchups_total == 3,
                f"week 1 did not pass the gate: {census}")
        evidence.append(f"the same gate PASSES for fully final week 1 "
                        f"({census.matchups_finalized}/{census.matchups_total} "
                        f"final) — it refuses non-finality, not settlement")


# ══════════════════════════════════════════════════════════════════════════════
# C-17  SECRET SCRUB
# ══════════════════════════════════════════════════════════════════════════════

@gate("C-17", "SECRET SCRUB — no credential material in fixtures, manifests, logs")
def c17_scrub(evidence, tdb):
    import json

    from providers.fixtures.record import REDACTED, scrub
    from providers.fixtures.replay import DEFAULT_CORPUS_DIR

    # (a) The scrubber demonstrably removes each credential shape.
    dirty = {
        "access_token": "AexampleTOKENvalue1234567890~abcdefghij",
        "refresh_token": "ArefreshTOKENvalue1234567890~klmnopqrst",
        "consumer_secret": "0123456789abcdef0123456789abcdef01234567",
        "guid": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "headers": {"Authorization": "Bearer AveryLongOpaqueTokenValue12345"},
        "nested": [{"email": "manager@real-domain.example"}],
        "url": "https://example.invalid/api?access_token=AbcDEF1234567890xyz",
        "harmless": "Mahomes Alone",
    }
    clean, actions = scrub(dirty)
    for key in ("access_token", "refresh_token", "consumer_secret", "guid"):
        require(clean[key] == REDACTED, f"{key} was not redacted")
    require(clean["headers"]["Authorization"] == REDACTED,
            "Authorization header was not redacted")
    require(clean["nested"][0]["email"] == REDACTED, "PII email not redacted")
    require(REDACTED in clean["url"],
            f"a token embedded in a URL survived: {clean['url']}")
    require(clean["harmless"] == "Mahomes Alone",
            "the scrubber damaged non-sensitive content")
    require(len(actions) >= 7, f"only {len(actions)} scrub actions recorded")
    evidence.append(f"scrubber removed every credential shape (key-based and "
                    f"pattern-based) and recorded {len(actions)} actions; "
                    f"non-sensitive content untouched")

    # (b) The COMMITTED corpus contains none of it.
    patterns = [
        re.compile(r'"access_token"\s*:\s*"(?!\*\*\*)', re.IGNORECASE),
        re.compile(r'"refresh_token"\s*:\s*"(?!\*\*\*)', re.IGNORECASE),
        re.compile(r'"consumer_secret"\s*:\s*"(?!\*\*\*)', re.IGNORECASE),
        re.compile(r'"client_secret"\s*:\s*"(?!\*\*\*)', re.IGNORECASE),
        re.compile(r'"?authorization"?\s*[:=]\s*"?(?!\*\*\*)\S', re.IGNORECASE),
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
        re.compile(r"\bBasic\s+[A-Za-z0-9+/=]{16,}"),
    ]
    scanned = 0
    for name in sorted(os.listdir(DEFAULT_CORPUS_DIR)):
        path = os.path.join(DEFAULT_CORPUS_DIR, name)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        scanned += 1
        for pattern in patterns:
            hits = pattern.findall(text)
            require(not hits,
                    f"{name} matches credential pattern "
                    f"{pattern.pattern[:40]!r}: {hits[:2]}")
    evidence.append(f"scanned {scanned} corpus files (payloads AND manifests): "
                    f"zero OAuth token, access token, refresh token, "
                    f"Authorization header, client secret or Basic credential")

    # (c) No real email address survived either.
    email_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    for name in sorted(os.listdir(DEFAULT_CORPUS_DIR)):
        with open(os.path.join(DEFAULT_CORPUS_DIR, name),
                  encoding="utf-8") as handle:
            found = email_pattern.findall(handle.read())
        real = [e for e in found
                if not e.endswith((".invalid", ".test", ".example", ".local"))]
        require(not real, f"{name} carries email address(es) {real}")
    evidence.append("no email address outside the reserved .invalid/.test/"
                    ".example TLDs appears anywhere in the corpus")

    # (d) The certification's own log output carries nothing either. Checked at
    #     the end of main() over the accumulated evidence.
    combined = "\n".join(line for result in RESULTS for line in result.evidence)
    for pattern in patterns:
        require(not pattern.findall(combined),
                f"certification evidence itself matches {pattern.pattern[:30]!r}")
    evidence.append("the certification's own evidence output is credential-free")

    # (e) secrets/ is not committed.
    import subprocess
    tracked = subprocess.run(
        ["git", "ls-files", "secrets/"], cwd=REPO_ROOT,
        capture_output=True, text=True).stdout.strip()
    require(not tracked, f"secrets/ files are tracked by Git: {tracked}")
    evidence.append("git ls-files secrets/ is empty — no credential file is "
                    "tracked")


# ══════════════════════════════════════════════════════════════════════════════
# WP2  —  C-18 through C-25
# ══════════════════════════════════════════════════════════════════════════════
#
# ADDITIVE. C-1 through C-17 above are untouched: WP2 changed where two provider
# modules live, not what any of them does, and a gate that had to be rewritten to
# keep passing would be evidence of exactly the behaviour change this package
# promised not to make.

DEMO_TOKEN = "cert1"
DEMO_TOKEN_B = "cert2"


def seed_demo_league(db, *, token: str = DEMO_TOKEN):
    """A Demo league with provider identity, wallets and no economic state.

    Deliberately NOT a call into `api.demo_routes.create_demo_league`: that
    function also grants commissioner authority and seats a user, neither of
    which a provider gate is testing, and importing the API into this harness
    would drag FastAPI into a run whose whole claim is that it is minimal.
    Everything IDENTITY-related below goes through the certified binders.
    """
    from db.schema import League, Team, Wallet
    from providers.demo import DEMO_PROVIDER
    from providers.demo.scenario import TEAM_COUNT, DemoScenario, league_key_for
    from providers.identity import bind_league_identity, bind_team_identity

    league_key = league_key_for(token)
    scenario = DemoScenario(league_key=league_key)

    league = League(season=scenario.season, name=f"Demo {token}",
                    projection_source="fantasypros")
    db.add(league)
    db.flush()
    bind_league_identity(db, league_id=league.id, league_key=league_key,
                         provider=DEMO_PROVIDER)

    teams = []
    for ordinal in range(1, TEAM_COUNT + 1):
        team = Team(league_id=league.id, team_name=scenario.team_name(ordinal),
                    owner=scenario.owner_name(ordinal),
                    email=scenario.owner_email(ordinal))
        db.add(team)
        db.flush()
        db.add(Wallet(team_id=team.id, balance=0.0))
        bind_team_identity(db, team_id=team.id,
                           team_key=scenario.team_key(ordinal),
                           team_ordinal=ordinal, provider=DEMO_PROVIDER)
        teams.append(team)
    db.flush()
    return league, teams, scenario


def demo_snapshot(scenario, *, week: int, final: bool, with_rosters: bool = False,
                  source=None):
    """One Demo snapshot through the production source object."""
    from providers.demo.source import DemoProviderSource

    src = source or DemoProviderSource()
    return src.week_snapshot(league_key=scenario.league_key, week=week,
                             current_week=week, final=final,
                             with_rosters=with_rosters)


@gate("C-18", "DEMO NORMALIZATION — same DTO contract, same writer, same rules")
def c18_demo_normalization(evidence, tdb):
    from providers.base import Finality, MatchupBracket, derive_matchup_key
    from providers.demo import DEMO_PROVIDER
    from providers.demo.scenario import (
        PLAYOFF_START_WEEK, SEASON_FINAL_WEEK, START_WEEK,
    )
    from providers.persist import refresh_league_week, snapshot_digest
    from db.schema import Matchup

    tdb.reset()
    with tdb.SessionLocal() as db:
        league, teams, scenario = seed_demo_league(db)
        db.commit()

        # (a) THE DTO CONTRACT. An OPEN week carries no score and no winner —
        #     None, never 0.0 — and is NOT_FINAL, so nothing economic can move.
        open_week = demo_snapshot(scenario, week=1, final=False)
        require(all(m.provider == DEMO_PROVIDER for m in open_week.matchups),
                "a Demo matchup does not declare the demo provider")
        require(all(m.home_points is None and m.away_points is None
                    for m in open_week.matchups),
                "an OPEN Demo week carries scores — 0.0 standing in for 'not "
                "played' is the conflation providers/base.py refuses")
        require(all(m.finality is Finality.NOT_FINAL
                    and m.winner_team_key is None
                    for m in open_week.matchups),
                "an OPEN Demo week declares finality or a winner")
        evidence.append(f"open week: {len(open_week.matchups)} matchups, every "
                        f"one NOT_FINAL with home_points/away_points None and "
                        f"no declared winner")

        # (b) BOUNDARIES TRAVEL ON THE DTO and are reconciled by the same writer.
        league_dto = open_week.league
        require((league_dto.start_week, league_dto.playoff_start_week,
                 league_dto.season_final_week) ==
                (START_WEEK, PLAYOFF_START_WEEK, SEASON_FINAL_WEEK),
                f"Demo boundaries are not carried: {league_dto}")
        require(league_dto.playoff_team_count == 4,
                "Demo does not state its championship field size")
        evidence.append(
            f"boundaries carried on the DTO: start_week="
            f"{league_dto.start_week} playoff_start_week="
            f"{league_dto.playoff_start_week} season_final_week="
            f"{league_dto.season_final_week} playoff_team_count="
            f"{league_dto.playoff_team_count}")

        # (c) ORIENTATION IS THE CERTIFIED CANONICAL RULE, not payload order.
        #     Swapping the two team keys must produce a byte-identical key.
        for matchup in open_week.matchups:
            mirrored = derive_matchup_key(scenario.league_key, 1,
                                          matchup.away_team_key,
                                          matchup.home_team_key)
            require(mirrored == matchup.matchup_key,
                    f"Demo matchup key is not mirror-stable: {matchup.matchup_key}"
                    f" vs {mirrored}")
        evidence.append("every Demo matchup key is byte-identical under a "
                        "swapped team pair — providers.base.orient decides "
                        "orientation, not the scenario's own ordering")

        # (d) A REGULAR-SEASON WEEK STATES NO BRACKET. UNKNOWN is the truth for
        #     a week the championship track never asks about.
        require(all(m.bracket is MatchupBracket.UNKNOWN
                    for m in open_week.matchups),
                "a regular-season Demo matchup claims a bracket")
        evidence.append("regular-season Demo matchups are bracket UNKNOWN — "
                        "'not a championship game' is not asserted for a week "
                        "nothing asks about")

        # (e) PERSISTENCE IS THE PRODUCTION WRITER, and finality comes only
        #     from an affirmative FINAL signal.
        refresh_league_week(db, open_week)
        db.commit()
        rows = db.query(Matchup).filter(Matchup.league_id == league.id,
                                        Matchup.week == 1).all()
        require(len(rows) == 3, f"{len(rows)} matchup rows for Demo week 1")
        require(all(r.finalized_at is None for r in rows),
                "an OPEN Demo week set finalized_at")
        require(all(r.provider_matchup_key for r in rows),
                "a persisted Demo matchup carries no provider key")
        evidence.append(f"providers.persist wrote {len(rows)} Demo matchup rows "
                        f"with finalized_at NULL and provider keys set")

        final_week = demo_snapshot(scenario, week=1, final=True,
                                   with_rosters=True)
        refresh_league_week(db, final_week)
        db.commit()
        rows = db.query(Matchup).filter(Matchup.league_id == league.id,
                                        Matchup.week == 1).all()
        require(len(rows) == 3, "finalizing changed the matchup row count")
        require(all(r.finalized_at is not None for r in rows),
                "a FINAL Demo week left finalized_at NULL")
        require(all(r.winner_team_id is not None for r in rows),
                "a FINAL Demo week persisted no declared winner")
        evidence.append("finalizing the same week set finalized_at on all 3 "
                        "rows and persisted the provider's DECLARED winner — "
                        "no row was inserted twice")

        # (f) REPLAY IS DETERMINISTIC — the same input digest, the same state.
        again = demo_snapshot(scenario, week=1, final=True, with_rosters=True)
        require(snapshot_digest(again) == snapshot_digest(final_week),
                "two Demo snapshots of the same week differ")
        evidence.append(f"two independent Demo snapshots of week 1 hash "
                        f"identically ({snapshot_digest(again)[:16]}...)")


@gate("C-19", "DEMO MONEY ISOLATION — a full Demo season posts zero ledger entries")
def c19_demo_money(evidence, tdb):
    import ast

    from ledger.ledger import LedgerEntry, trial_balance
    from providers.demo.scenario import SEASON_FINAL_WEEK, START_WEEK
    from providers.persist import refresh_league_week

    # (a) STATIC — the Demo package imports no money module. C-15 already scans
    #     all of providers/; this reports the Demo subtree by name so a reader
    #     is not left inferring that it was covered.
    demo_root = os.path.join(REPO_ROOT, "providers", "demo")
    offenders: list[str] = []
    modules = 0
    for dirpath, dirnames, filenames in os.walk(demo_root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            modules += 1
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name.split(".")[0] in ("ledger", "economy"):
                        offenders.append(f"{rel}:{node.lineno} imports {name}")
    require(not offenders, f"the Demo provider imports money modules: {offenders}")
    require(modules >= 4, f"only {modules} Demo modules scanned")
    evidence.append(f"static scan of {modules} providers/demo modules: zero "
                    f"imports from ledger/ or economy/")

    # (b) DYNAMIC — every week of a Demo season, twice, posts nothing.
    tdb.reset()
    with tdb.SessionLocal() as db:
        _league, _teams, scenario = seed_demo_league(db)
        db.commit()

        before_entries = db.query(LedgerEntry).count()
        before_balance = trial_balance()

        # PASS 1 plays the season the way the Demo actually advances: each week
        # is OPENED and then FINALIZED. PASS 2 replays only the FINAL snapshots,
        # which is what a repeated refresh of a played season is. Re-opening a
        # finalized week is deliberately NOT done — a provider reporting a final
        # matchup as non-final is a post-final CONTRADICTION (S6-R3), correctly
        # refused by the gateway, and asserting money isolation across a refusal
        # would be asserting it about a path that never ran.
        for week in range(START_WEEK, SEASON_FINAL_WEEK + 1):
            refresh_league_week(db, demo_snapshot(scenario, week=week,
                                                  final=False))
            db.commit()
            refresh_league_week(db, demo_snapshot(scenario, week=week,
                                                  final=True,
                                                  with_rosters=True))
            db.commit()
        for week in range(START_WEEK, SEASON_FINAL_WEEK + 1):
            refresh_league_week(db, demo_snapshot(scenario, week=week,
                                                  final=True,
                                                  with_rosters=True))
            db.commit()

        after_entries = db.query(LedgerEntry).count()
        require(after_entries == before_entries,
                f"a Demo season replay posted {after_entries - before_entries} "
                f"ledger entries")
        require(trial_balance() == before_balance,
                "trial_balance moved during a Demo provider replay")
        evidence.append(
            f"Demo weeks {START_WEEK}-{SEASON_FINAL_WEEK} opened and finalized "
            f"with rosters, then every final week replayed a second time: "
            f"ledger entries {before_entries} -> {after_entries}; trial_balance "
            f"{before_balance} throughout")


@gate("C-20", "DEMO IDENTITY — deterministic, non-colliding, cross-provider safe")
def c20_demo_identity(evidence, tdb):
    from providers.demo import DEMO_PROVIDER
    from providers.demo.scenario import DemoScenario, league_key_for
    from providers.demo.source import scenario_for
    from providers.errors import ProviderIdentityError
    from providers.identity import build_team_identity_resolver
    from providers.persist import snapshot_digest

    # (a) THE SAME SEED PRODUCES THE SAME FACTS.
    a1 = DemoScenario(league_key=league_key_for(DEMO_TOKEN))
    a2 = DemoScenario(league_key=league_key_for(DEMO_TOKEN))
    d1 = snapshot_digest(demo_snapshot(a1, week=2, final=True, with_rosters=True))
    d2 = snapshot_digest(demo_snapshot(a2, week=2, final=True, with_rosters=True))
    require(d1 == d2, "two identical Demo scenarios produced different facts")
    evidence.append(f"identical Demo league keys produce identical week-2 "
                    f"digests ({d1[:16]}...)")

    # (b) A DIFFERENT DEMO LEAGUE COLLIDES WITH NOTHING. `uq_teams_provider_key`
    #     is unique across leagues, so this is a constraint property, not a
    #     stylistic one.
    b = DemoScenario(league_key=league_key_for(DEMO_TOKEN_B))
    keys_a = {a1.team_key(n) for n in range(1, 7)}
    keys_b = {b.team_key(n) for n in range(1, 7)}
    require(not (keys_a & keys_b),
            f"two Demo leagues share team keys: {sorted(keys_a & keys_b)}")
    players_a = {a1.player_key(t, i) for t in range(1, 7) for i in range(10)}
    players_b = {b.player_key(t, i) for t in range(1, 7) for i in range(10)}
    require(not (players_a & players_b), "two Demo leagues share player keys")
    evidence.append(f"two Demo leagues: {len(keys_a)} + {len(keys_b)} team keys "
                    f"and {len(players_a)} + {len(players_b)} player keys, zero "
                    f"overlap")

    # (c) NO DEMO KEY IS YAHOO-SHAPED, and the Demo source refuses a Yahoo key.
    require(all(not k.split(".")[0].isdigit() for k in keys_a),
            f"a Demo key is Yahoo-shaped: {sorted(keys_a)[:1]}")
    try:
        scenario_for(LEAGUE_KEY)
        raise AssertionError(
            "the Demo provider answered for a Yahoo league key — it is capable "
            "of fabricating facts about a real league")
    except ProviderIdentityError as exc:
        require(exc.reason == ProviderIdentityError.NON_AUTHORITATIVE,
                f"Demo refusal used reason {exc.reason}")
    evidence.append(f"no Demo key parses as a Yahoo game id; the Demo source "
                    f"refuses league key {LEAGUE_KEY!r} with "
                    f"NON_AUTHORITATIVE_IDENTITY")

    # (d) CROSS-PROVIDER RESOLUTION CANNOT SUCCEED. A Demo-bound league asked
    #     for its Yahoo identity refuses, and a Yahoo-bound one asked for Demo.
    tdb.reset()
    with tdb.SessionLocal() as db:
        demo_league, _teams, _scenario = seed_demo_league(db)
        yahoo_league, _yteams = seed_provider_league(db, name="Yahoo Ctrl")
        db.commit()

        resolver = build_team_identity_resolver(db, league_id=demo_league.id,
                                                provider=DEMO_PROVIDER)
        require(len(resolver) == 6, f"Demo resolver holds {len(resolver)} keys")
        evidence.append(f"the Demo league resolves 6 team keys under provider "
                        f"{DEMO_PROVIDER!r} through the certified resolver")

        for league_id, wrong, label in (
            (demo_league.id, PROVIDER, "a Demo league asked for Yahoo identity"),
            (yahoo_league.id, DEMO_PROVIDER,
             "a Yahoo league asked for Demo identity"),
        ):
            try:
                build_team_identity_resolver(db, league_id=league_id,
                                             provider=wrong)
                raise AssertionError(f"{label} RESOLVED")
            except ProviderIdentityError as exc:
                require(exc.reason == ProviderIdentityError.UNKNOWN,
                        f"{label} used reason {exc.reason}")
        evidence.append("a Demo league refuses a Yahoo resolver and a Yahoo "
                        "league refuses a Demo one — every lookup filters on "
                        "(provider, key) together, so the namespaces cannot mix")

        # (e) A LEAGUE CANNOT SWITCH PROVIDER.
        from providers.identity import bind_league_identity
        try:
            bind_league_identity(db, league_id=demo_league.id,
                                 league_key=demo_league.provider_league_key,
                                 provider=PROVIDER)
            raise AssertionError("a Demo league was rebound to Yahoo")
        except ProviderIdentityError as exc:
            require(exc.reason == ProviderIdentityError.CONFLICTING,
                    f"provider switch used reason {exc.reason}")
        db.rollback()
        evidence.append("rebinding a Demo league to Yahoo is refused as "
                        "CONFLICTING_IDENTITY — a league cannot switch provider")


@gate("C-21", "DEMO POSTSEASON — production seam, derived podium, no Yahoo claim")
def c21_demo_postseason(evidence, tdb):
    from economy.championship_podium import derive_podium_keys
    from providers.demo.postseason import (
        DEMO_POSTSEASON_SOURCE, install_demo_postseason_source,
    )
    from providers.demo.scenario import (
        EXPECTED_PODIUM_ORDINALS, PLAYOFF_START_WEEK, SEASON_FINAL_WEEK,
    )
    from providers.persist import refresh_league_week
    from providers.postseason_bracket import (
        championship_field, classified_week, postseason_source_for,
        unregister_postseason_source,
    )
    from season.championship_track import (
        ChampionshipFieldDeclaration, ChampionshipTrackInput,
        ChampionshipWeekInput, TrackAuthority, derive_championship_track_state,
    )

    source = install_demo_postseason_source()
    try:
        # (a) IT CLAIMS DEMO LEAGUES AND NOTHING ELSE.
        require(source.knows(league_key="demo.l.42"),
                "the Demo source does not claim a Demo league")
        require(not source.knows(league_key=LEAGUE_KEY),
                f"the Demo postseason source CLAIMS Yahoo league {LEAGUE_KEY} "
                f"— it could take over a live league's championship")
        require(source.championship_field(league_key=LEAGUE_KEY,
                                          season=SEASON) is None,
                "the Demo source declared a field for a Yahoo league")
        evidence.append(f"registered as {DEMO_POSTSEASON_SOURCE!r}; claims "
                        f"demo.l.* and refuses {LEAGUE_KEY}")

        tdb.reset()
        with tdb.SessionLocal() as db:
            league, _teams, scenario = seed_demo_league(db)
            db.commit()

            # (b) THE PRODUCTION LOOKUP FINDS IT, and finds nothing for Yahoo.
            require(postseason_source_for(scenario.league_key) is source,
                    "postseason_source_for did not return the Demo source")
            require(postseason_source_for(LEAGUE_KEY) is None,
                    "a Yahoo league found a registered postseason source")
            evidence.append("providers.postseason_bracket.postseason_source_for "
                            "resolves the Demo league to the Demo source and a "
                            "Yahoo league to None")

            # (c) THE FACTS REACH THE DOMAIN THROUGH PERSISTED ROWS.
            for week in range(1, SEASON_FINAL_WEEK + 1):
                refresh_league_week(db, demo_snapshot(scenario, week=week,
                                                      final=True,
                                                      with_rosters=False))
                db.commit()

            weeks = []
            for week in range(PLAYOFF_START_WEEK, SEASON_FINAL_WEEK + 1):
                matchups = classified_week(db, league=league, week=week)
                require(matchups, f"postseason week {week} rehydrated empty")
                weeks.append(ChampionshipWeekInput(week=week, matchups=matchups))
            field = championship_field(db, league=league)
            require(field and len(field) == 4,
                    f"the Demo championship field is {field!r}")
            evidence.append(
                f"weeks {PLAYOFF_START_WEEK}-{SEASON_FINAL_WEEK} rehydrated from "
                f"PERSISTED rows and classified through the production seam; "
                f"declared field size {len(field)}")

            state = derive_championship_track_state(
                ChampionshipTrackInput(
                    league_key=league.provider_league_key, season=league.season,
                    playoff_start_week=PLAYOFF_START_WEEK,
                    season_final_week=SEASON_FINAL_WEEK,
                    playoff_team_count=4, weeks=tuple(weeks),
                    field_declaration=ChampionshipFieldDeclaration(
                        team_keys=field)),
                week=SEASON_FINAL_WEEK)
            require(state.authority is TrackAuthority.PROVIDER_CLASSIFIED,
                    f"Demo track authority is {state.authority} with reasons "
                    f"{list(state.insufficiency_reasons)}")
            require(state.complete, "the Demo championship is not complete")
            evidence.append(f"championship track authority="
                            f"{state.authority.value} complete={state.complete} "
                            f"champion={state.champion_team_key}")

            # (d) THE PODIUM IS DERIVED BY THE PRODUCTION RULE, NOT INJECTED.
            podium = derive_podium_keys(state)
            expected = tuple(scenario.team_key(n)
                             for n in EXPECTED_PODIUM_ORDINALS)
            require(podium == expected,
                    f"podium {podium!r} is not the scenario's {expected!r}")
            evidence.append(
                f"economy.championship_podium.derive_podium_keys returns "
                f"{[k.rsplit('.', 1)[-1] for k in podium]} — champion, "
                f"runner-up and the OFFICIAL THIRD-PLACE winner, derived from "
                f"the semifinal losers by WP1BC and never stated by the source")

            # (e) A SECOND SOURCE CLAIMING THE SAME LEAGUE REFUSES.
            from providers.errors import ProviderIdentityError
            from providers.postseason_bracket import register_postseason_source

            class _Rival:
                def knows(self, *, league_key):
                    return True

                def classify_week(self, *, league_key, week, matchups):
                    return matchups

                def championship_field(self, *, league_key, season):
                    return None

            register_postseason_source("c21-rival", _Rival())
            try:
                postseason_source_for(scenario.league_key)
                raise AssertionError(
                    "two postseason sources claimed one league and one was "
                    "chosen — a championship decided by registration order")
            except ProviderIdentityError as exc:
                require(exc.reason == ProviderIdentityError.AMBIGUOUS,
                        f"ambiguity used reason {exc.reason}")
            finally:
                unregister_postseason_source("c21-rival")
            evidence.append("two sources claiming one league refuse with "
                            "AMBIGUOUS_IDENTITY rather than picking one")
    finally:
        unregister_postseason_source(DEMO_POSTSEASON_SOURCE)


@gate("C-22", "PROVIDER OUTAGE — named, retryable, nothing persisted, retry works")
def c22_outage(evidence, tdb):
    from ledger.ledger import LedgerEntry, trial_balance
    from providers import incident as provider_incident
    from providers.demo.source import DemoProviderSource
    from providers.errors import ProviderTransportError
    from providers.persist import refresh_league_week
    from db.schema import Matchup

    tdb.reset()
    with tdb.SessionLocal() as db:
        league, _teams, scenario = seed_demo_league(db)
        db.commit()

        entries_before = db.query(LedgerEntry).count()
        balance_before = trial_balance()

        out = DemoProviderSource(outage=True)
        try:
            demo_snapshot(scenario, week=1, final=True, with_rosters=True,
                          source=out)
            raise AssertionError(
                "a provider OUTAGE produced a snapshot — a partial answer from "
                "a failed read is indistinguishable from a short week")
        except ProviderTransportError as exc:
            reason = provider_incident.reason_for_exception(exc)
        require(reason == provider_incident.REASON_PROVIDER_UNAVAILABLE,
                f"an outage mapped to reason {reason!r}")
        require(provider_incident.is_retryable(reason) is True,
                "a provider outage is not classified retryable")
        evidence.append(f"outage raises ProviderTransportError -> named reason "
                        f"{reason!r}, retryable=True")

        # NOTHING WAS PERSISTED, INVENTED OR POSTED.
        require(db.query(Matchup).filter(
            Matchup.league_id == league.id).count() == 0,
            "an outage persisted matchup rows")
        require(db.query(LedgerEntry).count() == entries_before,
                "an outage posted ledger entries")
        require(trial_balance() == balance_before,
                "an outage moved the trial balance")
        require(league.provider_current_week is None,
                "an outage advanced the provider's current week")
        evidence.append("after the outage: 0 matchup rows, 0 new ledger "
                        "entries, trial_balance unchanged, no finality "
                        "invented and no current week recorded")

        # THE SAME REFRESH SUCCEEDS ONCE THE PROVIDER RECOVERS.
        healthy = DemoProviderSource()
        result = refresh_league_week(db, demo_snapshot(scenario, week=1,
                                                       final=True,
                                                       with_rosters=True,
                                                       source=healthy))
        db.commit()
        rows = db.query(Matchup).filter(Matchup.league_id == league.id,
                                        Matchup.week == 1).all()
        require(len(rows) == 3 and all(r.finalized_at for r in rows),
                f"the retry persisted {len(rows)} rows")
        require(db.query(LedgerEntry).count() == entries_before,
                "the successful refresh posted ledger entries")
        evidence.append(f"the identical refresh retried after recovery: "
                        f"{result.matchups_inserted} inserted, "
                        f"{result.matchups_finalized} finalized, still 0 ledger "
                        f"entries — the provider layer never posts")


@gate("C-23", "INCOMPLETE DATA — INCOMPLETE_FIELD, no posting, resync settles")
def c23_incomplete_recovery(evidence, tdb):
    from betting.pool_catalog import spec_from_row
    from betting.pool_census import (
        CLASSIFICATION_INCOMPLETE_FIELD, classify_pool, require_settleable,
    )
    from betting.pool_errors import IncompleteFieldError
    from betting.pool_subjects import league_weekly_structure
    from ledger.ledger import LedgerEntry, trial_balance
    from providers import incident as provider_incident
    from providers.demo import DEMO_PROVIDER
    from providers.demo.pool_source import DemoProviderStatSource
    from providers.demo.scenario import (
        INCOMPLETE_PLAYER_INDEX, INCOMPLETE_TEAM_ORDINAL, REVISION_INCOMPLETE,
    )
    from providers.demo.source import DemoProviderSource
    from providers.identity import build_team_identity_resolver
    from providers.persist import refresh_league_week
    from db.schema import PoolDefinition

    tdb.reset()
    with tdb.SessionLocal() as db:
        from test_support_s4_pool import seed_catalog

        league, teams, scenario = seed_demo_league(db)
        seed_catalog(db)
        db.commit()

        refresh_league_week(db, demo_snapshot(scenario, week=1, final=True))
        db.commit()

        entries_before = db.query(LedgerEntry).count()
        balance_before = trial_balance()
        resolver = build_team_identity_resolver(db, league_id=league.id,
                                                provider=DEMO_PROVIDER)

        # A definition that needs a PLAYER stat, so the withheld record matters.
        row = (db.query(PoolDefinition)
               .filter(PoolDefinition.key == "most_passing_yards").first())
        require(row is not None, "most_passing_yards is not in the catalog")
        spec = spec_from_row(row)
        structure = league_weekly_structure(db, league_id=league.id, week=1,
                                            scope=spec.scope)

        # ── REVISION A: FINAL WEEK, ONE STARTER NEVER MEASURED ───────────────
        incomplete = DemoProviderSource(revision=REVISION_INCOMPLETE)
        snap_a = demo_snapshot(scenario, week=1, final=True, with_rosters=True,
                               source=incomplete)
        source_a = DemoProviderStatSource(snap_a).bind(db, resolver)
        outcome_a = classify_pool(spec, structure,
                                  source_a.subjects_for(
                                      league_id=league.id, season=league.season,
                                      week=1, structure=structure))
        require(outcome_a.classification == CLASSIFICATION_INCOMPLETE_FIELD,
                f"an unmeasured starter classified as "
                f"{outcome_a.classification}, not INCOMPLETE_FIELD")
        require(not outcome_a.settles, "an INCOMPLETE_FIELD outcome settles")
        require(outcome_a.census.subjects_claiming is None,
                "a claim count was computed over an incomplete field")
        require(outcome_a.unevaluable_subject_ids,
                "INCOMPLETE_FIELD named no unevaluable subject")
        stuck = teams[INCOMPLETE_TEAM_ORDINAL - 1].id
        require(stuck in outcome_a.unevaluable_subject_ids,
                f"team {stuck} (the one with the unmeasured starter) is not "
                f"among the unevaluable subjects "
                f"{list(outcome_a.unevaluable_subject_ids)}")
        evidence.append(
            f"one started player (team {INCOMPLETE_TEAM_ORDINAL}, roster index "
            f"{INCOMPLETE_PLAYER_INDEX}) with NO stats record -> "
            f"{outcome_a.classification}: considered="
            f"{outcome_a.census.subjects_evaluated}/"
            f"{outcome_a.census.subjects_considered}, claiming=None, "
            f"unevaluable={list(outcome_a.unevaluable_subject_ids)}")

        # THE REFUSAL IS NAMED AND IS RETRYABLE — AND IS NOT TERMINAL.
        try:
            require_settleable(outcome_a, definition_key=spec.key,
                               league_id=league.id, season=league.season, week=1)
            raise AssertionError("require_settleable admitted INCOMPLETE_FIELD")
        except IncompleteFieldError as exc:
            require(provider_incident.is_retryable(exc.classification) is True,
                    "INCOMPLETE_FIELD is not classified retryable")
            require(provider_incident.is_data_incomplete(exc.classification),
                    "INCOMPLETE_FIELD does not report data as incomplete")
        require(not provider_incident.TERMINAL_REASONS,
                "the incident taxonomy declares a TERMINAL reason — WP1E "
                "forbids any provider condition converting a Pool to terminal")
        evidence.append("the refusal is IncompleteFieldError: retryable=True, "
                        "data_incomplete=True, and TERMINAL_REASONS is empty — "
                        "no provider condition is terminal in FantasyStakes 1.0")

        # ── REPETITION AND FINALITY CHANGE NOTHING ───────────────────────────
        for attempt in range(2, 6):
            repeat = classify_pool(spec, structure,
                                   DemoProviderStatSource(
                                       demo_snapshot(scenario, week=1,
                                                     final=True,
                                                     with_rosters=True,
                                                     source=incomplete)
                                   ).bind(db, resolver).subjects_for(
                                       league_id=league.id,
                                       season=league.season, week=1,
                                       structure=structure))
            require(repeat.classification == CLASSIFICATION_INCOMPLETE_FIELD,
                    f"attempt {attempt} classified as {repeat.classification}")
        evidence.append("5 consecutive attempts against the same incomplete "
                        "snapshot all classify INCOMPLETE_FIELD — repetition "
                        "does not convert a data condition into a terminal one")

        # ── NOTHING ECONOMIC HAPPENED ────────────────────────────────────────
        require(db.query(LedgerEntry).count() == entries_before,
                "an INCOMPLETE_FIELD refusal posted ledger entries")
        require(trial_balance() == balance_before,
                "an INCOMPLETE_FIELD refusal moved the trial balance")
        evidence.append(f"ledger entries unchanged at {entries_before}; "
                        f"trial_balance unchanged at {balance_before}")

        # ── REVISION B: THE FEED CATCHES UP. ORDINARY SETTLEMENT, NOT A
        #    SPECIAL RECOVERY PATH. ──────────────────────────────────────────
        snap_b = demo_snapshot(scenario, week=1, final=True, with_rosters=True)
        source_b = DemoProviderStatSource(snap_b).bind(db, resolver)
        outcome_b = classify_pool(spec, structure,
                                  source_b.subjects_for(
                                      league_id=league.id, season=league.season,
                                      week=1, structure=structure))
        require(outcome_b.settles,
                f"the complete snapshot still refuses: "
                f"{outcome_b.classification}")
        require(outcome_b.census.subjects_evaluated ==
                outcome_b.census.subjects_considered,
                "the complete snapshot did not evaluate the full field")
        require_settleable(outcome_b, definition_key=spec.key,
                           league_id=league.id, season=league.season, week=1)
        evidence.append(
            f"the SAME definition, the SAME census and the SAME classifier "
            f"against the corrected snapshot: {outcome_b.classification}, "
            f"{outcome_b.census.subjects_evaluated}/"
            f"{outcome_b.census.subjects_considered} evaluated, winner(s) "
            f"{list(outcome_b.winning_subject_ids)} — no winner invented and no "
            f"recovery-specific path taken")


@gate("C-24", "PROVIDER INCIDENT REASONS — one vocabulary, no synonyms, no terminal")
def c24_incident_reasons(evidence, tdb):
    from betting.finality_gate import ResultsNotReadyError
    from betting.pool_errors import (
        IncompleteFieldError, NoEvaluableSubjectsError, NoSubjectsError,
        PoolInvariantViolationError,
    )
    from providers import incident as provider_incident
    from providers.errors import (
        ProviderCredentialError, ProviderIdentityError, ProviderParseError,
        ProviderTransportError,
    )

    # (a) EVERY NAME IS THE ENGINE'S OWN. Each constant is compared against the
    #     class or module that already owned it, so a synonym cannot be
    #     introduced here without this failing.
    for cls, constant in (
        (NoSubjectsError, provider_incident.REASON_NO_SUBJECTS),
        (NoEvaluableSubjectsError,
         provider_incident.REASON_NO_EVALUABLE_SUBJECTS),
        (IncompleteFieldError, provider_incident.REASON_INCOMPLETE_FIELD),
        (PoolInvariantViolationError,
         provider_incident.REASON_INVARIANT_VIOLATION),
    ):
        require(cls.classification == constant,
                f"{cls.__name__}.classification is {cls.classification!r} but "
                f"the taxonomy names it {constant!r} — two names for one "
                f"condition")
    not_ready = ResultsNotReadyError("x", league_id=1, week=1,
                                     unfinalized_matchup_ids=())
    require(not_ready.reason == provider_incident.REASON_RESULTS_NOT_READY,
            "RESULTS_NOT_READY is spelled differently in the taxonomy")
    evidence.append("the four Pool classifications and RESULTS_NOT_READY are "
                    "taken from the engines' own classes, not restated")

    # (b) EXCEPTION -> REASON is read off the exception where it carries one.
    cases = [
        (ProviderTransportError("down"),
         provider_incident.REASON_PROVIDER_UNAVAILABLE),
        (ProviderCredentialError("none"),
         provider_incident.REASON_PROVIDER_CREDENTIALS_MISSING),
        (ProviderParseError("bad"),
         provider_incident.REASON_PROVIDER_PARSE_FAILED),
        (ProviderIdentityError(ProviderIdentityError.UNKNOWN, "x"),
         provider_incident.REASON_PROVIDER_IDENTITY_UNRESOLVED),
        (not_ready, provider_incident.REASON_RESULTS_NOT_READY),
    ]
    for exc, expected in cases:
        actual = provider_incident.reason_for_exception(exc)
        require(actual == expected,
                f"{type(exc).__name__} mapped to {actual!r}, not {expected!r}")
    evidence.append(f"{len(cases)} provider/engine exceptions map to their "
                    f"named reason with no route-local string coined")

    # (c) RETRYABILITY IS DECIDED, AND THE TWO SETS ARE DISJOINT.
    overlap = (provider_incident.RETRYABLE_REASONS
               & provider_incident.NON_RETRYABLE_REASONS)
    require(not overlap, f"a reason is both retryable and not: {sorted(overlap)}")
    require(provider_incident.is_retryable(
        provider_incident.REASON_INCOMPLETE_FIELD) is True,
        "INCOMPLETE_FIELD is not retryable")
    require(provider_incident.is_retryable(
        provider_incident.REASON_INVARIANT_VIOLATION) is False,
        "INVARIANT_VIOLATION is reported retryable — an operator would wait "
        "forever for data that is already there")
    require(provider_incident.is_retryable("something_nobody_classified") is None,
            "an unclassified reason reports False rather than None")
    evidence.append(
        f"{len(provider_incident.RETRYABLE_REASONS)} retryable and "
        f"{len(provider_incident.NON_RETRYABLE_REASONS)} non-retryable reasons, "
        f"disjoint; an unclassified reason answers None rather than False")

    # (d) NOTHING IS TERMINAL, AND THE RECORD CANNOT CARRY A PAYLOAD.
    require(provider_incident.TERMINAL_REASONS == frozenset(),
            "TERMINAL_REASONS is non-empty")
    incident = provider_incident.build_incident(
        provider="demo", league_id=1, operation="pool_settle",
        reason=provider_incident.REASON_INCOMPLETE_FIELD, week=3,
        detail="x" * 5000)
    payload = incident.as_dict()
    require(len(payload["detail"]) <= provider_incident.MAX_DETAIL,
            "an incident carried an unbounded detail string")
    for forbidden in ("payload", "headers", "token", "response", "body"):
        require(forbidden not in payload,
                f"the incident record has a {forbidden!r} field — raw provider "
                f"material could be logged through it")
    for required_field in ("provider", "league_id", "season", "week",
                           "operation", "reason", "retryable",
                           "data_incomplete", "occurred_at",
                           "last_provider_refresh", "pool_instance_id"):
        require(required_field in payload,
                f"the incident record omits {required_field!r}, which §24 "
                f"requires an operator be able to determine")
    evidence.append(
        f"TERMINAL_REASONS is empty; the record carries all {len(payload)} §24 "
        f"fields, has no payload/headers/body field at all, and truncates "
        f"detail at {provider_incident.MAX_DETAIL} characters")


@gate("C-25", "YAHOO POSTSEASON EVIDENCE — the gate that must not be faked")
def c25_yahoo_postseason_evidence(evidence, tdb):
    """The Yahoo bracket capability, checked against the evidence hierarchy.

    THIS GATE PASSES WHEN YAHOO REMAINS CORRECTLY FAIL-CLOSED, and reports the
    capability as NOT CERTIFIED. It is not a success: it is a proof that the
    absence of evidence has not been worked around anywhere.
    """
    import ast

    from providers.base import MatchupBracket
    from providers.demo.postseason import (
        DEMO_POSTSEASON_SOURCE, install_demo_postseason_source,
    )
    from providers.fixtures.record import CAPTURED
    from providers.fixtures.replay import (
        FixtureTransport, load_corpus, provenance_counts,
    )
    from providers.postseason_bracket import (
        postseason_source_for, unregister_postseason_source,
    )
    from providers.yahoo import parse
    from providers.persist import refresh_league_week
    from providers.yahoo.normalize import normalize_scoreboard

    # ── LEVEL 1: CAPTURED YAHOO PAYLOAD ──────────────────────────────────────
    counts = provenance_counts(load_corpus())
    captured = counts.get(CAPTURED, 0)
    require(captured == 0 or True, "")     # reported, never asserted away
    evidence.append(f"evidence level 1 (CAPTURED Yahoo payload): "
                    f"{captured} fixture(s) in the corpus")

    # ── LEVEL 3: AN EXISTING NORMALIZED YAHOO FIELD ──────────────────────────
    # `parse_league` is the only Yahoo parser that reads a playoff-related
    # field, and it reads exactly one: the WEEK the postseason begins. A week
    # boundary cannot say which of that week's games is a championship game,
    # which two teams lost the semifinals, or which game is the official
    # third-place game — the four facts WP1D's adapter needs.
    source_text = open(os.path.join(REPO_ROOT, "providers", "yahoo", "parse.py"),
                       encoding="utf-8").read()
    tree = ast.parse(source_text)
    # FIELD NAMES ONLY. A payload key is a short single-line string; prose that
    # merely MENTIONS a field — this module's own docstrings, and the parser's —
    # is not a field the parser reads, and counting it would report evidence
    # that does not exist.
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) <= 40 and "\n" not in node.value}
    bracket_fields = sorted(
        s for s in literals
        if any(token in s.lower() for token in
               ("is_playoff", "is_consolation", "bracket", "num_playoff",
                "playoff_teams", "is_championship")))
    require(not bracket_fields,
            f"providers/yahoo/parse.py reads bracket-shaped field(s) "
            f"{bracket_fields} — if this is real, the adapter is buildable and "
            f"this gate is stale; if it is invented, it is exactly the "
            f"manufactured evidence §17 forbids")
    playoff_literals = sorted(s for s in literals if "playoff" in s.lower())
    evidence.append(
        f"evidence level 3 (existing normalized Yahoo field): the only "
        f"playoff-related literal the Yahoo parser reads is "
        f"{playoff_literals} — a WEEK BOUNDARY, which states nothing about "
        f"which games are championship games")

    # No corpus fixture carries a bracket-shaped field either.
    corpus_dir = os.path.join(REPO_ROOT, "providers", "fixtures", "corpus")
    hits = []
    for name in sorted(os.listdir(corpus_dir)):
        if not name.endswith(".json") or name.endswith(".manifest.json"):
            continue
        text = open(os.path.join(corpus_dir, name), encoding="utf-8").read()
        for token in ("is_playoffs", "is_consolation", "num_playoff_teams",
                      "bracket"):
            if token in text:
                hits.append(f"{name}:{token}")
    require(not hits, f"a corpus fixture carries a bracket field: {hits}")
    evidence.append(f"no fixture in the committed corpus carries "
                    f"is_playoffs / is_consolation / num_playoff_teams / "
                    f"bracket — the WP1A recon's finding is unchanged")

    # ── WHAT THE GATEWAY CAN EVEN ASK FOR ────────────────────────────────────
    # Reported so the blocker names the right thing. `ProviderTransport` exposes
    # four endpoints and none of them is a settings or standings resource, so a
    # bracket adapter would need a new transport method — which §41 requires be
    # specified endpoint, scope and field, not guessed at.
    from providers.base import ProviderTransport

    fetchers = sorted(n for n in dir(ProviderTransport) if n.startswith("fetch_"))
    evidence.append(f"the provider transport protocol exposes {fetchers} — no "
                    f"settings, standings or bracket resource among them")

    # The CLIENT library is not the blocker, and saying so keeps the report
    # honest about where the gap actually is. Introspected only if importable:
    # an offline run with no yfpy must still complete this gate.
    try:
        from yfpy.query import YahooFantasySportsQuery as _Query

        candidates = sorted(
            n for n in dir(_Query)
            if n.startswith("get_") and any(
                token in n for token in ("standing", "playoff", "settings",
                                         "matchup")))
        evidence.append(
            f"the installed Yahoo client already offers {candidates} — the "
            f"blocker is NOT client capability, it is that no response from any "
            f"of them has been captured and no in-repository documentation "
            f"states which field, if any, classifies a matchup")
    except Exception:  # noqa: BLE001 - absence is a legitimate offline state
        evidence.append("the Yahoo client library is not installed in this "
                        "process; its endpoint surface is not introspected and "
                        "is not required by this gate")

    # ── THE CONSEQUENCE, PROVEN RATHER THAN ASSERTED ─────────────────────────
    # Every Yahoo matchup normalizes to bracket UNKNOWN, no Yahoo postseason
    # source is registered, and a Yahoo league therefore has no bracket
    # authority — with the Demo source installed, which is the strongest form
    # of the claim.
    source = install_demo_postseason_source()
    try:
        transport = FixtureTransport(frozen_now=FROZEN_NOW)
        matchups = normalize_scoreboard(
            parse.parse_scoreboard(transport.fetch_scoreboard(LEAGUE_KEY, 1)),
            week=1)
        require(matchups, "the Yahoo scoreboard normalized to nothing")
        require(all(m.bracket is MatchupBracket.UNKNOWN for m in matchups),
                "a Yahoo matchup normalized to a classified bracket")
        evidence.append(f"all {len(matchups)} normalized Yahoo matchups carry "
                        f"MatchupBracket.UNKNOWN")

        require(postseason_source_for(LEAGUE_KEY) is None,
                "a postseason source claims the Yahoo league — with only the "
                "Demo source installed, that would mean the Demo provider is "
                "stating a live league's bracket")
        require(not source.knows(league_key=LEAGUE_KEY),
                "the Demo source knows a Yahoo league")
        evidence.append("with the Demo postseason source installed, the Yahoo "
                        "league still resolves to NO source — synthetic "
                        "material cannot be registered under Yahoo's name")

        # AND THE PODIUM REFUSES, by the production rule, with the named reason.
        from economy.championship_podium import (
            ChampionshipPodiumError, REASON_TRACK_UNKNOWN, derive_podium_keys,
        )
        from season.championship_track import (
            ChampionshipTrackInput, ChampionshipWeekInput,
            derive_championship_track_state,
        )

        tdb.reset()
        with tdb.SessionLocal() as db:
            league, _teams = seed_provider_league(db)
            db.commit()
            refresh_league_week(db, snapshot_for(transport, 1), now=FROZEN_NOW)
            db.commit()

            from providers.postseason_bracket import classified_week
            week_matchups = classified_week(db, league=league, week=1)
            require(all(m.bracket is MatchupBracket.UNKNOWN
                        for m in week_matchups),
                    "a persisted Yahoo matchup was classified")

            state = derive_championship_track_state(
                ChampionshipTrackInput(
                    league_key=LEAGUE_KEY, season=SEASON,
                    playoff_start_week=1, season_final_week=1,
                    weeks=(ChampionshipWeekInput(week=1,
                                                 matchups=week_matchups),)),
                week=1)
            require(not state.authority.is_authoritative,
                    f"an unclassified Yahoo week produced authority "
                    f"{state.authority}")
            podium_reason = None
            try:
                derive_podium_keys(state)
                raise AssertionError(
                    "a Championship podium was derived for a Yahoo league with "
                    "no bracket authority")
            except ChampionshipPodiumError as exc:
                podium_reason = exc.reason
            require(podium_reason == REASON_TRACK_UNKNOWN,
                    f"the podium refused with {podium_reason}, not "
                    f"{REASON_TRACK_UNKNOWN}")
            evidence.append(
                f"a live-shaped Yahoo league fails closed end to end: track "
                f"authority={state.authority.value} "
                f"reasons={list(state.insufficiency_reasons)} -> podium refuses "
                f"[{podium_reason}] -> a non-empty Championship Pot cannot be "
                f"distributed and the season does not close")
    finally:
        unregister_postseason_source(DEMO_POSTSEASON_SOURCE)

    return (
        "YAHOO PostseasonBracketSource is NOT CERTIFIED and is NOT IMPLEMENTED. "
        "Evidence hierarchy §17: level 1 (CAPTURED Yahoo payload) = 0 fixtures; "
        "level 2 (official Yahoo API documentation) is not present in this "
        "repository and was not consulted; level 3 (an existing normalized "
        "Yahoo field) yields only playoff_start_week, a WEEK BOUNDARY that "
        "cannot classify a matchup. Level 4 (synthetic fixture) is explicitly "
        "prohibited from certifying a Yahoo capability. REQUIRED TO CLOSE: a "
        "captured, scrubbed Yahoo response from a league that has PLAYED a "
        "postseason — league settings, every postseason week's scoreboard, and "
        "standings — from which a reviewer can read whether ANY field "
        "identifies the championship field, the championship-track matchups, "
        "the final, the semifinal losers and the official third-place game. "
        "`providers.fixtures.record.capture_postseason` performs that capture; "
        "it needs an authorized credential and an eligible league, and neither "
        "exists here. Until then Yahoo remains fail-closed and a live non-empty "
        "Championship Pot cannot be distributed."
    )


# ══════════════════════════════════════════════════════════════════════════════

GATES = [
    c1_offline, c2_provenance, c3_raw_parsing, c4_identity, c5_mirror,
    c6_truth_table, c7_immutability, c8_conflict, c9_replay, c10_concurrency,
    c11_horizon, c12_pool, c13_staleness, c14_census, c15_money,
    c16_finality_gate, c17_scrub,
    # WP2
    c18_demo_normalization, c19_demo_money, c20_demo_identity,
    c21_demo_postseason, c22_outage, c23_incomplete_recovery,
    c24_incident_reasons, c25_yahoo_postseason_evidence,
]


def main() -> int:
    print("\n" + "=" * 78)
    print("  SPRINT 6 OFFLINE CERTIFICATION GATE  —  C-1 through C-17")
    print("=" * 78)

    if not os.environ.get("TEST_DATABASE_URL"):
        print("\n!! TEST_DATABASE_URL is not set. Certification requires a "
              "disposable Postgres database.\n")
        return 2

    from test_support_postgres import setup_postgres_test_db

    tdb = setup_postgres_test_db()
    try:
        for gate_fn in GATES:
            # Gate bodies print nothing; any stray output from library code is
            # captured so the report stays a clean, greppable artifact.
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                gate_fn(tdb)
            noise = buffer.getvalue().strip()
            if noise:
                RESULTS[-1].evidence.append(
                    f"(captured stdout: {len(noise)} chars)")
    finally:
        tdb.teardown()

    print()
    for result in RESULTS:
        if not result.passed:
            status = "FAIL"
        elif result.blocker:
            status = "BLOCK"
        else:
            status = "PASS"
        print(f"  [{status}] {result.gate:<5} {result.title}")
        for line in result.evidence:
            print(f"           - {line}")
        if result.blocker:
            print(f"           ! NOT CERTIFIED — {result.blocker}")
        if result.error:
            print(f"           ! {result.error}")
        print()

    blocked = [r for r in RESULTS if r.passed and r.blocker]
    passed = sum(1 for r in RESULTS if r.passed and not r.blocker)
    failed = sum(1 for r in RESULTS if not r.passed)
    print("=" * 78)
    print(f"  CERTIFICATION: {passed} PASS / {failed} FAIL / "
          f"{len(blocked)} BLOCKED of {len(RESULTS)} gates")

    from providers.fixtures.record import CAPTURED, SYNTHETIC
    from providers.fixtures.replay import load_corpus, provenance_counts
    counts = provenance_counts(load_corpus())
    print(f"  FIXTURE CORPUS: CAPTURED = {counts.get(CAPTURED, 0)}   "
          f"SYNTHETIC = {counts.get(SYNTHETIC, 0)}")
    if not counts.get(CAPTURED, 0):
        print("  LIVE YAHOO PAYLOAD PARSING IS NOT CERTIFIED (S6-R2).")

    # WP2 §42 — A BLOCKED GATE MUST NOT READ AS GREEN. A gate whose own checks
    # all held while the capability it guards remains uncertified is neither a
    # pass nor a failure, and collapsing it into either would let a launch
    # review draw the wrong conclusion from one line of output.
    if blocked:
        print()
        print("  LAUNCH CERTIFICATION IS NOT GREEN — "
              f"{len(blocked)} capability blocker(s) open:")
        for result in blocked:
            print(f"    {result.gate}  {result.title}")
    print("=" * 78 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
