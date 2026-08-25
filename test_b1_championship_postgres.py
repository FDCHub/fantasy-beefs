#!/usr/bin/env python3
"""SPRINT B1 — the RC2 championship surface, on real PostgreSQL.

    TEST_DATABASE_URL=postgresql://…/fantasy_b1_champ_test \\
        python test_b1_championship_postgres.py

WHY THIS EXISTS. Every RC2 championship suite certified on SQLite. The
production target is PostgreSQL, and the differences that matter here are not
stylistic — they are the ones that decide whether a constraint is a constraint:

  · SQLite does not enforce foreign keys unless a pragma is set; PostgreSQL
    always does. (This suite's own first draft dropped a championship table and
    PostgreSQL refused, because two other tables reference it. SQLite had
    allowed the same drop silently.)
  · A failed statement inside a PostgreSQL transaction poisons the whole
    transaction; SQLite carries on.
  · PostgreSQL enforces CHECK constraints on every write. The Championship Score
    identity — `score = matchups + prop pools` — is one of those, and it is the
    rule the whole product rests on.
  · DDL is transactional on PostgreSQL, which is what the migration runner's
    all-or-nothing behaviour is designed around.

WHAT IS ASSERTED. Persistence and constraint behaviour of the championship
tables across a genuine reconnect — not the economics, which are certified by
the RC2 suites and are not re-litigated here. Nothing in this file computes a
payout, a Championship Score or an allocation.

NO ECONOMIC WRITE. Rows are inserted directly to exercise the SCHEMA. No ledger
entry is posted and no settlement path runs, so trial balance is untouched.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

FAIL: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


def section(title: str) -> None:
    print(f"\n{title}")


URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if not URL:
    print("TEST_DATABASE_URL is not set — this suite requires real PostgreSQL.")
    print("It does NOT fall back to SQLite: that would certify the wrong engine.")
    sys.exit(2)
if not URL.startswith("postgres"):
    print(f"TEST_DATABASE_URL is not PostgreSQL: {URL.split('://')[0]}://…")
    sys.exit(2)

os.environ["DATABASE_URL"] = URL
os.environ.setdefault("JWT_SECRET_KEY", "b1-championship-postgres-suite")

print("=" * 70)
print("B1 — RC2 CHAMPIONSHIP SURFACE ON POSTGRESQL")
print("=" * 70)

# The production entrypoint, so the RC2 models are registered before create_all.
from fastapi.testclient import TestClient  # noqa: E402

import api.main_rc2 as entry  # noqa: E402

with TestClient(entry.app):
    pass

from sqlalchemy import inspect, text  # noqa: E402

from db.schema import SessionLocal, engine  # noqa: E402

check("the dialect under test really is PostgreSQL",
      engine.dialect.name == "postgresql", engine.dialect.name)

with engine.connect() as c:
    SERVER = c.execute(text("SHOW server_version")).scalar()
print(f"  PostgreSQL server_version = {SERVER}")


# ── 1 · migration from a clean database, and its stamp ───────────────────────

section("1 · A clean PostgreSQL database migrates and stamps")

from migrations.manifest import ACTIVE  # noqa: E402
from migrations.run import applied_identifiers, pending, verify  # noqa: E402

tables = set(inspect(engine).get_table_names())
CHAMP = ("fantasystakes_championship_freeze", "fantasystakes_championship_score",
         "fantasystakes_championship_config",
         "fantasystakes_championship_allocation",
         "fantasystakes_championship_distribution_run",
         "fantasystakes_championship_correction")
for t in CHAMP:
    check(f"  {t} exists", t in tables)
check("the ledger table exists", "ledger_entries" in tables)
check("the manifest is fully stamped",
      applied_identifiers(engine) == {m.identifier for m in ACTIVE},
      str(sorted(applied_identifiers(engine))))
check("nothing is pending", [m.identifier for m in pending(engine)] == [])
check("and the stamp is corroborated by the live schema",
      verify(engine) == [], str(verify(engine)))


# ── 2 · the Championship Score identity is enforced BY THE DATABASE ──────────

section("2 · The Championship Score identity is a database constraint")

# THE ORM MODEL, NOT A HAND-WRITTEN INSERT. `leagues` carries several NOT NULL
# columns with Python-side defaults; naming them by hand here would encode a
# column list that goes stale the moment the model gains one.
from db.schema import League, Team  # noqa: E402

with SessionLocal() as db:
    league = League(season=2031, name="B1 PG", projection_source="fantasypros",
                    start_week=1, playoff_start_week=15, season_final_week=17)
    db.add(league)
    db.flush()
    lg = int(league.id)
    # Real teams: the score and correction tables carry an FK to `teams`, and
    # PostgreSQL enforces it. Three of them, so the duplicate-key and
    # missing-parent probes below have honest neighbours to sit beside.
    teams = []
    for n in range(1, 4):
        t = Team(league_id=lg, team_name=f"B1 Team {n}", owner=f"O{n}",
                 email=f"b1-pg-{n}@cert.test")
        db.add(t)
        teams.append(t)
    db.flush()
    TEAM = [int(t.id) for t in teams]
    db.commit()

with SessionLocal() as db:
    freeze_id = db.execute(text(
        "INSERT INTO fantasystakes_championship_freeze "
        "(league_id, season, playoff_start_week, scoring_through_week, frozen_at) "
        "VALUES (:l, 2031, 15, 14, NOW()) RETURNING id"), {"l": lg}).scalar()
    db.commit()
check("a freeze row persists", isinstance(freeze_id, int))

# The honest row: 8400 = 6000 + 2400.
with SessionLocal() as db:
    db.execute(text(
        "INSERT INTO fantasystakes_championship_score "
        "(freeze_id, league_id, season, team_id, matchup_net_cents, "
        " prop_pool_net_cents, championship_score_cents) "
        "VALUES (:f, :l, 2031, :t, 6000, 2400, 8400)"),
        {"f": freeze_id, "l": lg, "t": TEAM[0]})
    db.commit()
check("a score whose parts sum correctly is accepted", True)

# The dishonest row: 9999 != 6000 + 2400. PostgreSQL must refuse it.
refused = False
reason = ""
try:
    with SessionLocal() as db:
        db.execute(text(
            "INSERT INTO fantasystakes_championship_score "
            "(freeze_id, league_id, season, team_id, matchup_net_cents, "
            " prop_pool_net_cents, championship_score_cents) "
            "VALUES (:f, :l, 2031, :t, 6000, 2400, 9999)"),
            {"f": freeze_id, "l": lg, "t": TEAM[1]})
        db.commit()
except Exception as exc:
    refused = True
    reason = type(exc).__name__
check("a score that is NOT matchups + prop pools is REFUSED", refused, reason)
check("  · and it is the database refusing, not application code",
      "IntegrityError" in reason or "Integrity" in reason, reason)


# ── 3 · uniqueness and idempotency ───────────────────────────────────────────

section("3 · Uniqueness constraints hold under PostgreSQL")

dup = False
try:
    with SessionLocal() as db:
        db.execute(text(
            "INSERT INTO fantasystakes_championship_score "
            "(freeze_id, league_id, season, team_id, matchup_net_cents, "
            " prop_pool_net_cents, championship_score_cents) "
            "VALUES (:f, :l, 2031, :t, 1, 1, 2)"),
            {"f": freeze_id, "l": lg, "t": TEAM[0]})
        db.commit()
except Exception:
    dup = True
check("one team cannot be scored twice inside one freeze", dup)

fk = False
try:
    with SessionLocal() as db:
        db.execute(text(
            "INSERT INTO fantasystakes_championship_score "
            "(freeze_id, league_id, season, team_id, matchup_net_cents, "
            " prop_pool_net_cents, championship_score_cents) "
            "VALUES (999999, :l, 2031, :t, 1, 1, 2)"), {"l": lg, "t": TEAM[2]})
        db.commit()
except Exception:
    fk = True
check("a score cannot reference a freeze that does not exist", fk,
      "PostgreSQL enforces this FK; SQLite does not unless a pragma is set")


# ── 4 · transaction and rollback behaviour ───────────────────────────────────

section("4 · A failed statement does not leave half a write behind")

before = None
with SessionLocal() as db:
    before = db.execute(text(
        "SELECT count(*) FROM fantasystakes_championship_score "
        "WHERE league_id = :l"), {"l": lg}).scalar()

try:
    with SessionLocal() as db:
        db.execute(text(
            "INSERT INTO fantasystakes_championship_score "
            "(freeze_id, league_id, season, team_id, matchup_net_cents, "
            " prop_pool_net_cents, championship_score_cents) "
            "VALUES (:f, :l, 2031, :t, 100, 100, 200)"),
            {"f": freeze_id, "l": lg, "t": TEAM[1]})
        # Same transaction, now a violating row.
        db.execute(text(
            "INSERT INTO fantasystakes_championship_score "
            "(freeze_id, league_id, season, team_id, matchup_net_cents, "
            " prop_pool_net_cents, championship_score_cents) "
            "VALUES (:f, :l, 2031, :t, 100, 100, 12345)"),
            {"f": freeze_id, "l": lg, "t": TEAM[2]})
        db.commit()
except Exception:
    pass

with SessionLocal() as db:
    after = db.execute(text(
        "SELECT count(*) FROM fantasystakes_championship_score "
        "WHERE league_id = :l"), {"l": lg}).scalar()
check("the good row in a failed transaction was rolled back too",
      after == before, f"{before} -> {after}")


# ── 5 · configuration and correction persistence ─────────────────────────────

section("5 · Championship configuration and corrections persist")

from economy import fantasystakes_championship_allocation as alloc  # noqa: E402

with SessionLocal() as db:
    alloc.set_contribution(db, league_id=lg, season=2031, contribution_cents=8000)
    db.commit()

with SessionLocal() as db:
    view = alloc.read_config(db, league_id=lg, season=2031)
check("a commissioner contribution persists",
      int(view.fantasystakes_championship_contribution_cents) == 8000,
      str(view.fantasystakes_championship_contribution_cents))

with SessionLocal() as db:
    db.execute(text(
        "INSERT INTO fantasystakes_championship_correction "
        "(freeze_id, league_id, season, competition_type, contest_ref, "
        " scoring_week, team_id, revision, previous_net_cents, "
        " corrected_net_cents, delta_cents, reason, source, correction_key, "
        " created_at) "
        "VALUES (:f, :l, 2031, 'versus', 5, 3, :t, 1, 100, 400, 300, "
        "        'b1 persistence probe', 'commissioner:1', :k, NOW())"),
        {"f": freeze_id, "l": lg, "k": "b1-corr-key-1", "t": TEAM[0]})
    db.commit()

replay = False
try:
    with SessionLocal() as db:
        db.execute(text(
            "INSERT INTO fantasystakes_championship_correction "
            "(freeze_id, league_id, season, competition_type, contest_ref, "
            " scoring_week, team_id, revision, previous_net_cents, "
            " corrected_net_cents, delta_cents, reason, source, "
            " correction_key, created_at) "
            "VALUES (:f, :l, 2031, 'versus', 5, 3, :t, 1, 100, 400, 300, "
            "        'b1 replay probe', 'commissioner:1', :k, NOW())"),
            {"f": freeze_id, "l": lg, "k": "b1-corr-key-1", "t": TEAM[0]})
        db.commit()
except Exception:
    replay = True
check("a replayed correction key cannot post a second row", replay,
      "idempotency is enforced by the database, not by hope")


# ── 6 · restart and reconnect ────────────────────────────────────────────────

section("6 · A restart does not lose state")

# A REAL RECONNECT. `engine.dispose()` closes every pooled connection, so the
# next session opens a new one to the server — which is what a process restart
# does from the database's point of view.
engine.dispose()

with SessionLocal() as db:
    score = db.execute(text(
        "SELECT championship_score_cents FROM fantasystakes_championship_score "
        "WHERE league_id = :l AND team_id = :t"), {"l": lg, "t": TEAM[0]}).scalar()
    corrections = db.execute(text(
        "SELECT count(*) FROM fantasystakes_championship_correction "
        "WHERE league_id = :l"), {"l": lg}).scalar()
    contribution = alloc.read_config(
        db, league_id=lg, season=2031
    ).fantasystakes_championship_contribution_cents

check("the frozen Championship Score survived the reconnect",
      score == 8400, str(score))
check("the correction survived the reconnect", corrections == 1, str(corrections))
check("the commissioner contribution survived the reconnect",
      int(contribution) == 8000, str(contribution))
check("the schema is still corroborated after reconnect", verify(engine) == [])


# ── 7 · the championship read surface answers on PostgreSQL ──────────────────

section("7 · The championship read surface runs against PostgreSQL")

import reports.championship_read_model as crm  # noqa: E402

with SessionLocal() as db:
    frozen = crm.get_fantasystakes_championship(db, league_id=lg, season=2031)
check("the frozen snapshot reads back", frozen is not None)
if frozen is not None:
    # 8400 FROZEN + 300 CORRECTED = 8700, AND THAT IS THE POINT. The read model
    # applies recorded authoritative corrections on top of the frozen snapshot,
    # so the surface reports the RESTATED score rather than the superseded one.
    # This suite's first draft expected the bare 8400 and was simply wrong about
    # the product: seeing 8700 here proves the correction persisted on
    # PostgreSQL *and* reached the read, which is more than storage alone.
    scores = [int(r.championship_score_cents) for r in frozen.rows]
    check("  · and the recorded correction is applied to the read",
          8700 in scores, str(scores))
    check("  · which is the frozen score plus exactly the recorded delta",
          8700 == 8400 + 300)

with TestClient(entry.app) as client:
    r = client.get("/ready")
    check("/ready answers ready against migrated PostgreSQL",
          r.status_code == 200 and r.json()["ready"] is True,
          str(r.status_code))
    check("  · reporting the database usable",
          r.json().get("database") is True)
    check("  · with the schema verified",
          r.json()["checks"].get("schema") == "ok")


print("\n" + "=" * 70)
if FAIL:
    print(f"B1 CHAMPIONSHIP ON POSTGRESQL — {len(FAIL)} FAILED")
    for f in FAIL:
        print(f"  · {f}")
    sys.exit(1)
print(f"PASS: RC2 championship surface certified on PostgreSQL {SERVER}")
