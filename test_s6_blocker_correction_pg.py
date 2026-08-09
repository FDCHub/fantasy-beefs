#!/usr/bin/env python3
"""
test_s6_blocker_correction_pg.py — Opus blocker correction suite (PostgreSQL).

Covers the two blockers that held Sprint 6 out of acceptance:

  BLOCKER 1  notifications/tuesday_sync.py performed an unguarded
             ON CONFLICT DO UPDATE that could silently rewrite the score,
             winner and finality of an economically final Matchup (S6-R3).

  BLOCKER 2  the live Tuesday path resolved Yahoo team identity through the
             teams.email bridge, which S6-R1 forbids, while the Sprint 6
             gateway had no production caller at all.

EVERY TEST DRIVES THE REAL PRODUCTION FUNCTION. These scenarios call
`notifications.tuesday_sync._step_refresh_scores` — the exact function
`POST /admin/tuesday-sync` reaches — with a FixtureTransport injected. Injecting
the transport changes only where the bytes come from; the identity, finality,
conflict and persistence code exercised is the production code. A suite that
re-implemented the ingest and asserted on its own copy would prove nothing about
the reachable path, which is precisely the gap Opus found.

USAGE:
    export TEST_DATABASE_URL="postgresql://.../fantasy_test"
    python test_s6_blocker_correction_pg.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as exc:
    print(f"\n[HARNESS ERROR] blocker suite cannot run:\n  {exc}")
    sys.exit(2)

from db.schema import (  # noqa: E402
    League, Matchup, ProviderConflict, Team, Wallet,
)
from providers.fixtures.replay import FixtureTransport  # noqa: E402
from providers.yahoo.identity import (  # noqa: E402
    bind_league_identity, bind_team_identity,
)

LEAGUE_KEY = "461.l.488800"
SEASON = 2025
FROZEN_NOW = datetime(2025, 9, 23, 12, 0, 0, tzinfo=timezone.utc)

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def section(title: str) -> None:
    print(f"\n{title}")


def seed_league(db, *, bind: bool = True, n_teams: int = 6):
    """A league whose teams carry PROVIDER identity, with deliberately
    non-parseable emails so nothing can accidentally resolve from them."""
    league = League(season=SEASON, name="Blocker League",
                    projection_source="fantasypros")
    db.add(league)
    db.flush()

    teams = []
    for ordinal in range(1, n_teams + 1):
        team = Team(league_id=league.id, team_name=f"Team {ordinal}",
                    owner=f"Owner {ordinal}",
                    email=f"person{ordinal}@example.invalid")
        db.add(team)
        db.flush()
        db.add(Wallet(team_id=team.id, balance=0.0))
        teams.append(team)
    db.flush()

    if bind:
        bind_league_identity(db, league_id=league.id, league_key=LEAGUE_KEY)
        for ordinal, team in enumerate(teams, start=1):
            bind_team_identity(db, team_id=team.id,
                               team_key=f"{LEAGUE_KEY}.t.{ordinal}",
                               team_ordinal=ordinal)
    db.flush()
    return league, teams


class ScenarioTransport(FixtureTransport):
    """A FixtureTransport pinned to one scoreboard fixture id.

    Lets a scenario say "this refresh delivers the contradicted payload" without
    touching the production function's signature.
    """

    def __init__(self, scoreboard_id: str, **kwargs):
        super().__init__(**kwargs)
        self._scoreboard_id = scoreboard_id

    def fetch_scoreboard(self, league_key: str, week: int):
        self.fetch_log.append(("scoreboard", league_key, week))
        return self.corpus[self._scoreboard_id].payload


def matchup_state(db, league_id: int, week: int):
    """The load-bearing state of a week, as a comparable set."""
    return {
        (m.provider_matchup_key, m.home_team_id, m.away_team_id,
         m.home_score, m.away_score, m.winner_team_id,
         m.finalized_at.isoformat() if m.finalized_at else None)
        for m in db.query(Matchup).filter(Matchup.league_id == league_id,
                                          Matchup.week == week).all()
    }


def main(tdb) -> None:
    from notifications.tuesday_sync import _step_refresh_scores

    # ══════════════════════════════════════════════════════════════════════════
    section("B1-1: finalized row + IDENTICAL refresh — nothing changes, no "
            "conflict is invented")
    # ══════════════════════════════════════════════════════════════════════════
    tdb.reset()
    with tdb.SessionLocal() as db:
        league, teams = seed_league(db)
        db.commit()
        lid = league.id

        transport = ScenarioTransport("yahoo_scoreboard_w1",
                                      frozen_now=FROZEN_NOW)
        step, refresh = _step_refresh_scores(lid, 1, db, transport=transport)
        check("B1-1: first refresh succeeded", step.success, step.message[:90])
        check("B1-1: week 1 is settleable after a clean final refresh",
              refresh.settleable)

        after_first = matchup_state(db, lid, 1)
        check("B1-1: three matchups persisted", len(after_first) == 3,
              str(len(after_first)))
        finalized = db.query(Matchup).filter(
            Matchup.league_id == lid, Matchup.week == 1,
            Matchup.finalized_at.isnot(None)).count()
        check("B1-1: all three are economically final", finalized == 3,
              f"{finalized}/3")

        conflicts_before = db.query(ProviderConflict).count()

        # Identical delivery, later clock.
        transport2 = ScenarioTransport(
            "yahoo_scoreboard_w1",
            frozen_now=FROZEN_NOW.replace(hour=18))
        step2, refresh2 = _step_refresh_scores(lid, 1, db,
                                               transport=transport2)
        check("B1-1: identical re-refresh succeeded (not refused)",
              step2.success, step2.message[:90])

        after_second = matchup_state(db, lid, 1)
        check("B1-1: NO economic field changed across the identical refresh",
              after_first == after_second)
        conflicts_after = db.query(ProviderConflict).count()
        check("B1-1: NO ProviderConflict was invented for an identical refresh",
              conflicts_after == conflicts_before,
              f"{conflicts_before} -> {conflicts_after}")
        check("B1-1: the harmless refreshed_at update is permitted",
              step2.data.get("rows_unchanged") == 3,
              str(step2.data))

    # ══════════════════════════════════════════════════════════════════════════
    section("B1-2: finalized row + CHANGED SCORE — final state stands, one "
            "conflict, fails closed, retry does not duplicate")
    # ══════════════════════════════════════════════════════════════════════════
    tdb.reset()
    with tdb.SessionLocal() as db:
        league, teams = seed_league(db)
        db.commit()
        lid = league.id

        _step_refresh_scores(lid, 1, db, transport=ScenarioTransport(
            "yahoo_scoreboard_w1", frozen_now=FROZEN_NOW))
        before = matchup_state(db, lid, 1)

        step, refresh = _step_refresh_scores(
            lid, 1, db,
            transport=ScenarioTransport("yahoo_scoreboard_w1_contradicted",
                                        frozen_now=FROZEN_NOW))
        check("B1-2: the contradictory refresh FAILED CLOSED",
              not step.success and not refresh.settleable)
        check("B1-2: the refusal names the provider conflict",
              "PROVIDER CONFLICT" in step.message, step.message[:100])

        after = matchup_state(db, lid, 1)
        check("B1-2: stored final score/winner/finality are BYTE-IDENTICAL",
              before == after)

        conflicts = db.query(ProviderConflict).all()
        check("B1-2: exactly one ProviderConflict was written",
              len(conflicts) == 1, f"{len(conflicts)} row(s)")
        if conflicts:
            c = conflicts[0]
            check("B1-2: it is a POST_FINAL_SCORE conflict on home_score",
                  c.conflict_type == "POST_FINAL_SCORE"
                  and c.contradicted_field == "home_score",
                  f"{c.conflict_type}/{c.contradicted_field}")
            check("B1-2: it records both the stored and the claimed value",
                  c.existing_value == "112.5" and c.provider_value == "999.99",
                  f"stored={c.existing_value} claimed={c.provider_value}")

        # Retry the same contradiction three more times.
        for _ in range(3):
            _step_refresh_scores(
                lid, 1, db,
                transport=ScenarioTransport("yahoo_scoreboard_w1_contradicted",
                                            frozen_now=FROZEN_NOW))
        retried = db.query(ProviderConflict).all()
        check("B1-2: three retries did NOT multiply conflict rows",
              len(retried) == 1, f"{len(retried)} row(s)")
        check("B1-2: occurrence_count records the repeats instead",
              retried[0].occurrence_count == 4,
              f"occurrence_count={retried[0].occurrence_count}")
        check("B1-2: final state is STILL unchanged after four contradictions",
              matchup_state(db, lid, 1) == before)

    # ══════════════════════════════════════════════════════════════════════════
    section("B1-3: finalized row + CHANGED WINNER (identical scores) — same "
            "protection")
    # ══════════════════════════════════════════════════════════════════════════
    tdb.reset()
    with tdb.SessionLocal() as db:
        league, teams = seed_league(db)
        db.commit()
        lid = league.id

        _step_refresh_scores(lid, 1, db, transport=ScenarioTransport(
            "yahoo_scoreboard_w1", frozen_now=FROZEN_NOW))
        before = matchup_state(db, lid, 1)
        winner_before = db.query(Matchup).filter(
            Matchup.league_id == lid, Matchup.week == 1,
            Matchup.home_team_id == teams[0].id).first().winner_team_id

        step, refresh = _step_refresh_scores(
            lid, 1, db,
            transport=ScenarioTransport("yahoo_scoreboard_w1_winner_flipped",
                                        frozen_now=FROZEN_NOW))
        check("B1-3: the winner contradiction FAILED CLOSED",
              not step.success and not refresh.settleable, step.message[:90])
        check("B1-3: stored state is byte-identical",
              matchup_state(db, lid, 1) == before)

        winner_after = db.query(Matchup).filter(
            Matchup.league_id == lid, Matchup.week == 1,
            Matchup.home_team_id == teams[0].id).first().winner_team_id
        check("B1-3: winner_team_id was NOT rewritten",
              winner_after == winner_before,
              f"{winner_before} -> {winner_after}")

        conflicts = db.query(ProviderConflict).all()
        check("B1-3: a POST_FINAL_WINNER conflict was recorded",
              any(c.conflict_type == "POST_FINAL_WINNER" for c in conflicts),
              str([(c.conflict_type, c.contradicted_field) for c in conflicts]))
        check("B1-3: the SCORES were identical, so no score conflict was "
              "invented",
              not any(c.conflict_type == "POST_FINAL_SCORE" for c in conflicts),
              str([c.conflict_type for c in conflicts]))

    # ══════════════════════════════════════════════════════════════════════════
    section("B1-4: an unresolved conflict still blocks season close")
    # ══════════════════════════════════════════════════════════════════════════
    with tdb.SessionLocal() as db:
        from economy.economy_events import (
            EVENT_SKUNK_ASSESSMENT, league_week_key)
        from economy.season_close_orchestrator import (
            SeasonClosePreconditionError, verify_preconditions)
        from db.schema import EconomyEvent

        lid = db.query(League).first().id
        db.add(EconomyEvent(
            event_key=league_week_key(EVENT_SKUNK_ASSESSMENT, lid, SEASON, 1),
            league_id=lid, season=SEASON, week=1,
            event_type=EVENT_SKUNK_ASSESSMENT, amount_cents=0,
            created_at=FROZEN_NOW))
        db.commit()

        blocked_step = None
        try:
            verify_preconditions(db, league_id=lid, final_week=1)
        except SeasonClosePreconditionError as exc:
            blocked_step = exc.step
        check("B1-4: season close is refused while the conflict is unresolved",
              blocked_step == "provider_conflict", f"step={blocked_step!r}")

        # And clears once acknowledged — the only resolution S6-R3 permits.
        from providers.yahoo.persist import acknowledge_conflict
        for c in db.query(ProviderConflict).all():
            acknowledge_conflict(db, conflict_key_value=c.conflict_key,
                                 operator="blocker-suite", note="B1-4",
                                 now=FROZEN_NOW)
        db.commit()
        cleared = True
        try:
            verify_preconditions(db, league_id=lid, final_week=1)
        except SeasonClosePreconditionError as exc:
            cleared = exc.step != "provider_conflict"
        check("B1-4: acknowledging clears the conflict block", cleared)

    # ══════════════════════════════════════════════════════════════════════════
    section("B2-1: production Tuesday sync resolves by provider_team_key")
    # ══════════════════════════════════════════════════════════════════════════
    tdb.reset()
    with tdb.SessionLocal() as db:
        league, teams = seed_league(db)
        db.commit()
        lid = league.id

        step, refresh = _step_refresh_scores(lid, 1, db,
                                             transport=ScenarioTransport(
                                                 "yahoo_scoreboard_w1",
                                                 frozen_now=FROZEN_NOW))
        check("B2-1: the production refresh resolved and persisted",
              step.success, step.message[:90])

        rows = db.query(Matchup).filter(Matchup.league_id == lid,
                                        Matchup.week == 1).all()
        internal_ids = {t.id for t in teams}
        check("B2-1: every persisted team id came from the provider key map",
              all(m.home_team_id in internal_ids
                  and m.away_team_id in internal_ids for m in rows))
        check("B2-1: every row carries a derived provider matchup key",
              all(m.provider_matchup_key and m.provider_matchup_key.startswith(
                  LEAGUE_KEY) for m in rows),
              str([m.provider_matchup_key for m in rows][:1]))

    # ══════════════════════════════════════════════════════════════════════════
    section("B2-2: a RENAMED team still resolves to the same internal Team")
    # ══════════════════════════════════════════════════════════════════════════
    with tdb.SessionLocal() as db:
        lid = db.query(League).first().id
        team = db.query(Team).filter(Team.league_id == lid).order_by(
            Team.id).first()
        original_id = team.id
        before = matchup_state(db, lid, 1)

        team.team_name = "Renamed Beyond Recognition"
        team.owner = "A Completely Different Person"
        team.email = "totally-new-address@example.invalid"
        db.commit()

        step, refresh = _step_refresh_scores(lid, 1, db,
                                             transport=ScenarioTransport(
                                                 "yahoo_scoreboard_w1",
                                                 frozen_now=FROZEN_NOW))
        check("B2-2: refresh still succeeds after a full rename",
              step.success, step.message[:90])
        check("B2-2: the persisted matchup state is unchanged — the renamed "
              "team resolved to the SAME internal Team",
              matchup_state(db, lid, 1) == before)
        still_there = db.query(Matchup).filter(
            Matchup.league_id == lid, Matchup.week == 1,
            Matchup.home_team_id == original_id).count()
        check("B2-2: the renamed team is still the home side of its matchup",
              still_there == 1, f"{still_there} row(s)")

    # ══════════════════════════════════════════════════════════════════════════
    section("B2-3: email-only identity does NOT resolve")
    # ══════════════════════════════════════════════════════════════════════════
    tdb.reset()
    with tdb.SessionLocal() as db:
        # A league seeded the OLD way: legacy 'yahoo-team-{n}@...' emails, and
        # NO provider identity at all. Under Sprint 5 this resolved perfectly.
        league = League(season=SEASON, name="Legacy Email League")
        db.add(league)
        db.flush()
        for ordinal in range(1, 7):
            t = Team(league_id=league.id, team_name=f"Legacy {ordinal}",
                     owner=f"Owner {ordinal}",
                     email=f"yahoo-team-{ordinal}@fantasy-beefs.local")
            db.add(t)
            db.flush()
            db.add(Wallet(team_id=t.id, balance=0.0))
        bind_league_identity(db, league_id=league.id, league_key=LEAGUE_KEY)
        db.commit()
        lid = league.id

        step, refresh = _step_refresh_scores(lid, 1, db,
                                             transport=ScenarioTransport(
                                                 "yahoo_scoreboard_w1",
                                                 frozen_now=FROZEN_NOW))
        check("B2-3: a league identified ONLY by legacy emails is REFUSED",
              not step.success and not refresh.settleable, step.message[:100])
        persisted = db.query(Matchup).filter(Matchup.league_id == lid).count()
        check("B2-3: nothing was persisted from the email-only league",
              persisted == 0, f"{persisted} row(s)")

        from db.team_resolver import TeamResolverError, build_team_resolver
        refused = False
        try:
            build_team_resolver(db, lid)
        except TeamResolverError:
            refused = True
        check("B2-3: build_team_resolver itself refuses an email-only league",
              refused)

        from db.team_resolver import _parse_yahoo_id_from_email
        parser_refused = False
        try:
            _parse_yahoo_id_from_email("yahoo-team-4@fantasy-beefs.local")
        except TeamResolverError:
            parser_refused = True
        check("B2-3: the legacy email parser itself refuses, always",
              parser_refused)

    # ══════════════════════════════════════════════════════════════════════════
    section("B2-4: an UNKNOWN provider key fails closed")
    # ══════════════════════════════════════════════════════════════════════════
    tdb.reset()
    with tdb.SessionLocal() as db:
        # Bound, but to only FIVE of the six teams the payload names.
        league, teams = seed_league(db, bind=False, n_teams=6)
        bind_league_identity(db, league_id=league.id, league_key=LEAGUE_KEY)
        for ordinal, team in enumerate(teams[:5], start=1):
            bind_team_identity(db, team_id=team.id,
                               team_key=f"{LEAGUE_KEY}.t.{ordinal}",
                               team_ordinal=ordinal)
        db.commit()
        lid = league.id

        step, refresh = _step_refresh_scores(lid, 1, db,
                                             transport=ScenarioTransport(
                                                 "yahoo_scoreboard_w1",
                                                 frozen_now=FROZEN_NOW))
        check("B2-4: a partially-bound league is REFUSED, not partially "
              "ingested", not step.success and not refresh.settleable,
              step.message[:100])
        persisted = db.query(Matchup).filter(Matchup.league_id == lid).count()
        check("B2-4: NOTHING was persisted — no partial slate",
              persisted == 0, f"{persisted} row(s)")

    # A league with no provider key at all.
    tdb.reset()
    with tdb.SessionLocal() as db:
        league, teams = seed_league(db, bind=False)
        db.commit()
        step, refresh = _step_refresh_scores(league.id, 1, db,
                                             transport=ScenarioTransport(
                                                 "yahoo_scoreboard_w1",
                                                 frozen_now=FROZEN_NOW))
        check("B2-4: an unbound LEAGUE is refused before any fetch",
              not step.success and "provider_league_key" in step.message,
              step.message[:100])

    # ══════════════════════════════════════════════════════════════════════════
    section("B2-5: no production Yahoo ingest caller depends on the old email "
            "parser")
    # ══════════════════════════════════════════════════════════════════════════
    import ast
    import re as _re

    root = os.path.dirname(os.path.abspath(__file__))
    email_identity_users: list[str] = []
    legacy_pattern = _re.compile(
        r"_parse_yahoo_id_from_email|yahoo-team-\{|yahoo-team-%s")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", ".idea")]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, filename),
                                  root).replace("\\", "/")
            if rel.startswith("test_") or "/test_" in rel:
                continue
            src = open(os.path.join(dirpath, filename),
                       encoding="utf-8", errors="replace").read()
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            doc_ids = set()
            for parent in ast.walk(tree):
                # Only Module/Function/Class carry a docstring, and only those
                # have a LIST body — IfExp and Lambda have a single expression
                # under the same attribute name, which is not subscriptable.
                if not isinstance(parent, (ast.Module, ast.FunctionDef,
                                           ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                body = parent.body
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    doc_ids.add(id(body[0].value))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and id(node) not in doc_ids
                        and legacy_pattern.search(node.value)):
                    email_identity_users.append(f"{rel}:{node.lineno}")
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "_parse_yahoo_id_from_email"):
                    email_identity_users.append(f"{rel}:{node.lineno} (call)")

    # db/team_resolver.py legitimately DEFINES the refusal; the seeder writes
    # the email as contact data. Neither RESOLVES identity from it.
    permitted = ("db/team_resolver.py", "seed_real_2025_season_LIVE.py")
    offenders = [u for u in email_identity_users
                 if not u.startswith(permitted)]
    check("B2-5: no production module resolves identity from the legacy email "
          "pattern", not offenders, str(offenders))

    resolver_src = open(os.path.join(root, "db", "team_resolver.py"),
                        encoding="utf-8").read()
    check("B2-5: db/team_resolver.py delegates to the provider identity "
          "resolver", "build_team_identity_resolver" in resolver_src)
    check("B2-5: db/team_resolver.py no longer reads Team.email",
          "Team.email" not in resolver_src)

    sync_src = open(os.path.join(root, "notifications", "tuesday_sync.py"),
                    encoding="utf-8").read()
    tree = ast.parse(sync_src)
    doc_ids = set()
    for parent in ast.walk(tree):
        if not isinstance(parent, (ast.Module, ast.FunctionDef,
                                   ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = parent.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            doc_ids.add(id(body[0].value))
    executable_dml = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in doc_ids
        and _re.search(r"\b(INSERT\s+INTO|UPDATE)\s+matchups\b",
                       node.value, _re.IGNORECASE)
    ]
    check("B2-5: tuesday_sync contains NO executable SQL that writes matchups",
          not executable_dml, str(executable_dml))

    # ══════════════════════════════════════════════════════════════════════════
    section("B2-6: Tuesday ingestion sets finalized_at ONLY through the "
            "accepted finality mapping")
    # ══════════════════════════════════════════════════════════════════════════
    tdb.reset()
    with tdb.SessionLocal() as db:
        league, teams = seed_league(db)
        db.commit()
        lid = league.id

        # Week 2 carries the truth table: a final 0-0, a midevent with scores,
        # and a preevent.
        step, refresh = _step_refresh_scores(lid, 2, db,
                                             transport=ScenarioTransport(
                                                 "yahoo_scoreboard_w2",
                                                 frozen_now=FROZEN_NOW))
        rows = db.query(Matchup).filter(Matchup.league_id == lid,
                                        Matchup.week == 2).all()
        final_rows = [m for m in rows if m.finalized_at is not None]
        check("B2-6: exactly the one AFFIRMATIVELY FINAL matchup is final",
              len(final_rows) == 1, f"{len(final_rows)} of {len(rows)}")
        check("B2-6: the final one is the 0-0 — finality is not inferred from "
              "the score",
              final_rows and final_rows[0].home_score == 0.0
              and final_rows[0].away_score == 0.0,
              str([(m.home_score, m.away_score) for m in final_rows]))
        mid = [m for m in rows if m.home_score == 77.5]
        check("B2-6: the midevent matchup HAS scores but is NOT final",
              mid and mid[0].finalized_at is None,
              str([(m.home_score, m.finalized_at) for m in mid]))
        check("B2-6: a week that is not fully final is NOT settleable",
              not refresh.settleable, step.message[:90])
        check("B2-6: the refusal names finalized_at, not a status string",
              "finalized_at IS NULL" in step.message, step.message[:110])

        # An UNKNOWN finality signal must also leave it NULL.
        step_u, _ = _step_refresh_scores(lid, 2, db,
                                         transport=ScenarioTransport(
                                             "yahoo_scoreboard_w2_nostatus",
                                             frozen_now=FROZEN_NOW))
        unknown_row = db.query(Matchup).filter(
            Matchup.league_id == lid, Matchup.week == 2,
            Matchup.home_score == 88.0).first()
        check("B2-6: a matchup with scores but NO status stays non-final",
              unknown_row is None or unknown_row.finalized_at is None)

        # Nothing outside the finality module set it.
        finality_src = open(os.path.join(root, "providers", "yahoo",
                                         "finality.py"), encoding="utf-8").read()
        check("B2-6: apply_finality is the only assignment site in the mapping "
              "module", finality_src.count("matchup.finalized_at =") == 1,
              str(finality_src.count("matchup.finalized_at =")))


if __name__ == "__main__":
    print("\n=== S6 Opus blocker correction suite (PostgreSQL) ===")
    try:
        main(tdb)
    finally:
        tdb.teardown()
    print(f"\n  {len(_failures)} failure(s)")
    if _failures:
        for f in _failures:
            print(f"    FAILED: {f}")
        sys.exit(1)
    print("  ALL PASS")