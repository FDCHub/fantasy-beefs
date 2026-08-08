#!/usr/bin/env python3
"""
migrate_spec1_proposal_lifecycle.py  —  SPEC 1 (Locked Challenge Proposal
Lifecycle, Rev 3) production schema migration.

Brings production Postgres up to db/schema.py's Spec 1 additions, which were
implemented ADDITIVELY (Ruling 1, 2026-07-23):

  1. Two new tables:
       beef_proposals            — immutable versioned proposal (§3.2)
       beef_proposal_starters    — proposal-scoped both-team snapshot (§3.3)
  2. Nine additive, NULLABLE container columns on beef_challenges (§3.1):
       league_id, challenge_mode, wager_type, response_status,
       active_proposal_id, accepted_proposal_id, active_response_expires_at,
       revived_from_challenge_id, updated_at
  3. Integrity constraints (§3.4):
       CHECKs   ck_beef_challenge_mode, ck_beef_wager_type,
                ck_beef_response_status (beef_challenges);
                ck_beef_proposal_version_kind (beef_proposals)
       UNIQUEs  uq_beef_proposal_version, uq_beef_proposal_id_challenge
                (beef_proposals); uq_beef_proposal_starter (starters)
       FKs      the two CYCLIC composite same-challenge FKs
                fk_beef_active_proposal_same_challenge,
                fk_beef_accepted_proposal_same_challenge — each binds a
                challenge's active/accepted pointer to a proposal OF THAT SAME
                challenge, via (pointer, id) -> beef_proposals(id, challenge_id).
                Because beef_challenges <-> beef_proposals form a pointer cycle,
                these MUST be ALTER-added after BOTH tables exist (they cannot be
                inline). Plus the two ordinary FKs on the new nullable columns
                (league_id -> leagues, revived_from_challenge_id -> beef_challenges).

WHY ADDITIVE / §11: every legacy beef_challenges column is retained and every
new column is nullable, so legacy-created rows take NULL and the unreleased
legacy flow (beefs/beef_engine.py, untouched) keeps working. This is NOT the
destructive drop/recreate that Spec 1 §11 gates on row counts — nothing is
dropped, nothing is backfilled, so legacy DATA presence is irrelevant to safety.
The gate here is STRUCTURAL (below), not a row count.

FAIL-CLOSED THREE-BRANCH STATE MACHINE (no other branch may apply):
  (a) NONE of the expected Spec 1 structures present
        -> apply the complete additive migration in one transaction.
  (b) ALL expected structures present AND structurally correct
        -> already applied; write nothing; exit 0.
  (c) PARTIAL presence OR any structural mismatch
        -> STOP: sys.exit(1), report the unexpected state, write nothing.
     A partial/mismatched state was NOT produced by a clean prior run of this
     script; finishing it blind could silently diverge from the intended schema.
     This migration REFUSES to "complete" such a state. Resolve it by hand.

SAFE:
  - Additive only. Never drops, renames, or alters an existing column.
  - Postgres-only. Refuses to run if DATABASE_URL is missing or non-Postgres.
  - Idempotent via the state machine: branch (b) is a clean no-op re-run.
  - All DDL runs inside ONE engine.begin() transaction — Postgres DDL is
    transactional, so any failure rolls the whole migration back; the cyclic
    composite FKs are added last, after both tables exist, still in-transaction.
  - Touches no table other than beef_challenges (additive) and the two new tables.

USAGE (never against production without sign-off):
  python db/migrations/migrate_spec1_proposal_lifecycle.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

print("\nmigrate_spec1_proposal_lifecycle.py  --  SPEC 1 Proposal Lifecycle schema migration\n")

from sqlalchemy import text
from db.schema import engine

# ── Postgres guard ────────────────────────────────────────────────────────────

db_url = str(engine.url)
if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
    print("!! ERROR: Postgres target not detected.")
    print("   DATABASE_URL is missing or does not point at a Postgres instance.")
    print("   This migration adds cyclic composite FKs that SQLite cannot ALTER-add;")
    print("   it is Postgres-only. Re-run with DATABASE_URL pointing at Postgres.")
    sys.exit(1)

# Never print credentials — only the host/db tail.
print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


# ── Expected-structure inventory (the §3 contract) ────────────────────────────

NEW_TABLES = ("beef_proposals", "beef_proposal_starters")

BEEF_CHALLENGES_NEW_COLS = {
    "league_id":                  ("integer", "YES"),
    "challenge_mode":             ("character varying", "YES"),
    "wager_type":                 ("character varying", "YES"),
    "response_status":            ("character varying", "YES"),
    "active_proposal_id":         ("integer", "YES"),
    "accepted_proposal_id":       ("integer", "YES"),
    "active_response_expires_at": ("timestamp without time zone", "YES"),
    "revived_from_challenge_id":  ("integer", "YES"),
    "updated_at":                 ("timestamp without time zone", "YES"),
}

BEEF_PROPOSALS_COLS = {
    "id":                          ("integer", "NO"),
    "challenge_id":                ("integer", "NO"),
    "version_number":              ("integer", "NO"),
    "version_kind":                ("character varying", "NO"),
    "proposing_team_id":           ("integer", "NO"),
    "created_at":                  ("timestamp without time zone", "NO"),
    "response_expires_at":         ("timestamp without time zone", "YES"),
    "proposal_lock_at":            ("timestamp without time zone", "YES"),
    "schedule_source_ref":         ("character varying", "YES"),
    "line":                        ("double precision", "YES"),
    "side":                        ("character varying", "YES"),
    "player_id":                   ("integer", "YES"),
    "anchor_stake_cents":          ("integer", "YES"),
    "quoted_derived_stake_cents":  ("integer", "YES"),
    "quoted_funded_pot_cents":     ("integer", "YES"),
    "quoted_anchor_payout_cents":  ("integer", "YES"),
    "quoted_derived_payout_cents": ("integer", "YES"),
    "anchor_team_id":              ("integer", "YES"),
    "derived_team_id":             ("integer", "YES"),
    "pricing_model_id":            ("character varying", "YES"),
    "pricing_calc_version":        ("character varying", "YES"),
    "projection_source_id":        ("character varying", "YES"),
    "projection_retrieved_at":     ("timestamp without time zone", "YES"),
    "projection_input_snapshot":   ("json", "YES"),
    "anchor_win_probability":      ("double precision", "YES"),
    "derived_win_probability":     ("double precision", "YES"),
    "anchor_odds":                 ("double precision", "YES"),
    "derived_odds":                ("double precision", "YES"),
    "anchor_moneyline":            ("integer", "YES"),
    "derived_moneyline":           ("integer", "YES"),
    "pricing_input_hash":          ("character varying", "YES"),
    "display_terms":               ("character varying", "YES"),
}

BEEF_PROPOSAL_STARTERS_COLS = {
    "id":          ("integer", "NO"),
    "proposal_id": ("integer", "NO"),
    "team_id":     ("integer", "NO"),
    "player_id":   ("integer", "NO"),
    "nfl_team":    ("character varying", "YES"),
}

# Named constraints that make up the Spec 1 contract (auto-named per-column FKs
# inside the two CREATE TABLEs are covered by table existence + column checks).
BEEF_CHALLENGES_CONSTRAINTS = (
    "ck_beef_challenge_mode",
    "ck_beef_wager_type",
    "ck_beef_response_status",
    "fk_beef_challenge_league",
    "fk_beef_challenge_revived_from",
    "fk_beef_active_proposal_same_challenge",
    "fk_beef_accepted_proposal_same_challenge",
)
BEEF_PROPOSALS_CONSTRAINTS = (
    "uq_beef_proposal_version",
    "uq_beef_proposal_id_challenge",
    "ck_beef_proposal_version_kind",
)
BEEF_PROPOSAL_STARTERS_CONSTRAINTS = (
    "uq_beef_proposal_starter",
)
ALL_NAMED_CONSTRAINTS = (
    BEEF_CHALLENGES_CONSTRAINTS + BEEF_PROPOSALS_CONSTRAINTS + BEEF_PROPOSAL_STARTERS_CONSTRAINTS
)

# Expected CHECK definitions (substring signatures, dialect-stable) and the
# composite-FK signatures — verified in branch (b) for structural correctness.
CHECK_SIGNATURES = {
    "ck_beef_challenge_mode":        ["challenge_mode", "'locked'", "'dynamic'"],
    "ck_beef_wager_type":            ["wager_type", "'straight'", "'spread'", "'over_under'"],
    "ck_beef_response_status":       ["response_status", "'offered'", "'countered'", "'accepted'",
                                      "'declined'", "'expired'", "'cancelled'"],
    "ck_beef_proposal_version_kind": ["version_kind", "'initial'", "'counter'"],
}
FK_SIGNATURES = {
    "fk_beef_active_proposal_same_challenge":
        ["active_proposal_id, id", "beef_proposals(id, challenge_id)"],
    "fk_beef_accepted_proposal_same_challenge":
        ["accepted_proposal_id, id", "beef_proposals(id, challenge_id)"],
}


# ── Introspection helpers ─────────────────────────────────────────────────────

def _table_exists(conn, table: str) -> bool:
    return conn.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
    ), {"t": table}).first() is not None


def _columns(conn, table: str) -> dict[str, tuple[str, str]]:
    rows = conn.execute(text(
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns WHERE table_name = :t"
    ), {"t": table}).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def _existing_constraints(conn) -> set[str]:
    rows = conn.execute(text("SELECT conname FROM pg_constraint")).fetchall()
    return {r[0] for r in rows}


def _constraint_def(conn, name: str) -> str | None:
    row = conn.execute(text(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"
    ), {"n": name}).first()
    return row[0] if row else None


# ── Presence inventory + branch decision ──────────────────────────────────────

with engine.connect() as conn:
    bc_cols = _columns(conn, "beef_challenges")
    con_names = _existing_constraints(conn)

    table_present = {t: _table_exists(conn, t) for t in NEW_TABLES}
    col_present = {c: (c in bc_cols) for c in BEEF_CHALLENGES_NEW_COLS}
    con_present = {c: (c in con_names) for c in ALL_NAMED_CONSTRAINTS}

    signals = list(table_present.values()) + list(col_present.values()) + list(con_present.values())
    present_count = sum(1 for s in signals if s)
    total = len(signals)

print("=" * 64)
print("STATE  -- Spec 1 structure inventory")
print("=" * 64)
print(f"\n  tables present      : "
      f"{ {t: p for t, p in table_present.items()} }")
print(f"  new columns present : {sum(col_present.values())}/{len(col_present)}")
print(f"  named constraints   : {sum(con_present.values())}/{len(con_present)}")
print(f"  TOTAL signals       : {present_count}/{total}")


def _verify_structure(conn) -> list[str]:
    """Branch (b) gate: every expected structure must be present AND correct.
    Returns a list of problems; empty list == structurally correct."""
    problems: list[str] = []

    # beef_challenges additive columns — exact type + nullability
    live_bc = _columns(conn, "beef_challenges")
    for name, expected in BEEF_CHALLENGES_NEW_COLS.items():
        got = live_bc.get(name)
        if got != expected:
            problems.append(f"beef_challenges.{name}: expected {expected}, got {got}")

    # new tables — exact column set + type + nullability
    for table, spec in (("beef_proposals", BEEF_PROPOSALS_COLS),
                        ("beef_proposal_starters", BEEF_PROPOSAL_STARTERS_COLS)):
        live = _columns(conn, table)
        for name, expected in spec.items():
            got = live.get(name)
            if got != expected:
                problems.append(f"{table}.{name}: expected {expected}, got {got}")
        extra = set(live) - set(spec)
        if extra:
            problems.append(f"{table}: unexpected extra columns {sorted(extra)}")

    # CHECK definitions
    for name, sigs in CHECK_SIGNATURES.items():
        cdef = _constraint_def(conn, name) or ""
        for sig in sigs:
            if sig not in cdef:
                problems.append(f"{name}: definition missing {sig!r} (got: {cdef!r})")

    # composite same-challenge FK definitions
    for name, sigs in FK_SIGNATURES.items():
        cdef = _constraint_def(conn, name) or ""
        for sig in sigs:
            if sig not in cdef:
                problems.append(f"{name}: definition missing {sig!r} (got: {cdef!r})")

    return problems


if present_count == 0:
    branch = "a"
elif present_count == total:
    with engine.connect() as conn:
        struct_problems = _verify_structure(conn)
    branch = "b" if not struct_problems else "c"
else:
    branch = "c"
    struct_problems = []

print(f"\n  BRANCH -> ({branch})")


# ── Branch (b): already applied and correct — no-op ───────────────────────────

if branch == "b":
    print("\n  All Spec 1 structures present and structurally correct.")
    print("  Nothing to do (idempotent no-op).")
    print("\n  MIGRATION COMPLETE (already applied).\n")
    sys.exit(0)


# ── Branch (c): partial / mismatch — FAIL CLOSED ──────────────────────────────

if branch == "c":
    print("\n!! ABORT: unexpected schema state — NOT a clean prior run of this script.")
    print("   This migration will NOT complete a partial or divergent state; doing so")
    print("   could silently diverge from the intended Spec 1 schema. Nothing written.")
    print("\n   Present signals:")
    for label, present in (list(table_present.items())
                           + list(col_present.items())
                           + list(con_present.items())):
        print(f"     [{'x' if present else ' '}] {label}")
    if present_count == total and struct_problems:
        print("\n   Structural mismatches (all signals present, but wrong):")
        for p in struct_problems:
            print(f"     - {p}")
    print("\n   Resolve by hand and re-run. sys.exit(1).")
    sys.exit(1)


# ── Branch (a): clean install — apply the complete additive migration ─────────

print()
print("=" * 64)
print("APPLY  -- branch (a): no Spec 1 structures present; applying in full")
print("=" * 64)

CREATE_BEEF_PROPOSALS = """
CREATE TABLE beef_proposals (
    id SERIAL NOT NULL,
    challenge_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    version_kind VARCHAR NOT NULL,
    proposing_team_id INTEGER NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    response_expires_at TIMESTAMP WITHOUT TIME ZONE,
    proposal_lock_at TIMESTAMP WITHOUT TIME ZONE,
    schedule_source_ref VARCHAR,
    line FLOAT,
    side VARCHAR,
    player_id INTEGER,
    anchor_stake_cents INTEGER,
    quoted_derived_stake_cents INTEGER,
    quoted_funded_pot_cents INTEGER,
    quoted_anchor_payout_cents INTEGER,
    quoted_derived_payout_cents INTEGER,
    anchor_team_id INTEGER,
    derived_team_id INTEGER,
    pricing_model_id VARCHAR,
    pricing_calc_version VARCHAR,
    projection_source_id VARCHAR,
    projection_retrieved_at TIMESTAMP WITHOUT TIME ZONE,
    projection_input_snapshot JSON,
    anchor_win_probability FLOAT,
    derived_win_probability FLOAT,
    anchor_odds FLOAT,
    derived_odds FLOAT,
    anchor_moneyline INTEGER,
    derived_moneyline INTEGER,
    pricing_input_hash VARCHAR,
    display_terms VARCHAR,
    PRIMARY KEY (id),
    CONSTRAINT uq_beef_proposal_version UNIQUE (challenge_id, version_number),
    CONSTRAINT uq_beef_proposal_id_challenge UNIQUE (id, challenge_id),
    CONSTRAINT ck_beef_proposal_version_kind CHECK (version_kind IN ('initial','counter')),
    FOREIGN KEY(challenge_id) REFERENCES beef_challenges (id),
    FOREIGN KEY(proposing_team_id) REFERENCES teams (id),
    FOREIGN KEY(player_id) REFERENCES players (id),
    FOREIGN KEY(anchor_team_id) REFERENCES teams (id),
    FOREIGN KEY(derived_team_id) REFERENCES teams (id)
)
"""

CREATE_BEEF_PROPOSAL_STARTERS = """
CREATE TABLE beef_proposal_starters (
    id SERIAL NOT NULL,
    proposal_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    nfl_team VARCHAR(4),
    PRIMARY KEY (id),
    CONSTRAINT uq_beef_proposal_starter UNIQUE (proposal_id, team_id, player_id),
    FOREIGN KEY(proposal_id) REFERENCES beef_proposals (id),
    FOREIGN KEY(team_id) REFERENCES teams (id),
    FOREIGN KEY(player_id) REFERENCES players (id)
)
"""

ADD_COLUMNS = [
    "ALTER TABLE beef_challenges ADD COLUMN league_id INTEGER",
    "ALTER TABLE beef_challenges ADD COLUMN challenge_mode VARCHAR",
    "ALTER TABLE beef_challenges ADD COLUMN wager_type VARCHAR",
    "ALTER TABLE beef_challenges ADD COLUMN response_status VARCHAR",
    "ALTER TABLE beef_challenges ADD COLUMN active_proposal_id INTEGER",
    "ALTER TABLE beef_challenges ADD COLUMN accepted_proposal_id INTEGER",
    "ALTER TABLE beef_challenges ADD COLUMN active_response_expires_at TIMESTAMP WITHOUT TIME ZONE",
    "ALTER TABLE beef_challenges ADD COLUMN revived_from_challenge_id INTEGER",
    "ALTER TABLE beef_challenges ADD COLUMN updated_at TIMESTAMP WITHOUT TIME ZONE",
]

ADD_CHALLENGE_CHECKS = [
    "ALTER TABLE beef_challenges ADD CONSTRAINT ck_beef_challenge_mode "
    "CHECK (challenge_mode IN ('locked','dynamic'))",
    "ALTER TABLE beef_challenges ADD CONSTRAINT ck_beef_wager_type "
    "CHECK (wager_type IN ('straight','spread','over_under'))",
    "ALTER TABLE beef_challenges ADD CONSTRAINT ck_beef_response_status "
    "CHECK (response_status IN ('offered','countered','accepted','declined','expired','cancelled'))",
]

# Ordinary FKs on the two new nullable columns (auto-named by the ORM; named
# here for reviewability and reliable idempotency detection).
ADD_CHALLENGE_SIMPLE_FKS = [
    "ALTER TABLE beef_challenges ADD CONSTRAINT fk_beef_challenge_league "
    "FOREIGN KEY (league_id) REFERENCES leagues (id)",
    "ALTER TABLE beef_challenges ADD CONSTRAINT fk_beef_challenge_revived_from "
    "FOREIGN KEY (revived_from_challenge_id) REFERENCES beef_challenges (id)",
]

# Cyclic composite same-challenge FKs — added AFTER beef_proposals exists (its
# uq_beef_proposal_id_challenge is the referenced unique key). These cannot be
# inline on either table because the two tables reference each other.
ADD_COMPOSITE_FKS = [
    "ALTER TABLE beef_challenges ADD CONSTRAINT fk_beef_active_proposal_same_challenge "
    "FOREIGN KEY (active_proposal_id, id) REFERENCES beef_proposals (id, challenge_id)",
    "ALTER TABLE beef_challenges ADD CONSTRAINT fk_beef_accepted_proposal_same_challenge "
    "FOREIGN KEY (accepted_proposal_id, id) REFERENCES beef_proposals (id, challenge_id)",
]

try:
    with engine.begin() as conn:
        # 1. additive nullable columns on beef_challenges
        for stmt in ADD_COLUMNS:
            conn.execute(text(stmt))
        print("  + 9 nullable container columns added to beef_challenges")

        # 2. CHECKs + ordinary FKs on the new columns
        for stmt in ADD_CHALLENGE_CHECKS:
            conn.execute(text(stmt))
        for stmt in ADD_CHALLENGE_SIMPLE_FKS:
            conn.execute(text(stmt))
        print("  + 3 CHECK constraints + 2 ordinary FKs added to beef_challenges")

        # 3. new tables (their inline PK/UNIQUE/CHECK/FKs come with them)
        conn.execute(text(CREATE_BEEF_PROPOSALS))
        print("  + beef_proposals created")
        conn.execute(text(CREATE_BEEF_PROPOSAL_STARTERS))
        print("  + beef_proposal_starters created")

        # 4. cyclic composite same-challenge FKs — last, both tables now exist
        for stmt in ADD_COMPOSITE_FKS:
            conn.execute(text(stmt))
        print("  + 2 cyclic composite same-challenge FKs added to beef_challenges")
except Exception as e:
    print(f"\n!! ERROR: migration failed; the entire transaction rolled back: {e}")
    print("   No columns, tables, or constraints were added.")
    sys.exit(1)


# ── Verification (after) ──────────────────────────────────────────────────────

print()
print("=" * 64)
print("VERIFY -- post-apply structural check")
print("=" * 64)

with engine.connect() as conn:
    problems = _verify_structure(conn)
    missing_tables = [t for t in NEW_TABLES if not _table_exists(conn, t)]
    con_names_after = _existing_constraints(conn)
    missing_cons = [c for c in ALL_NAMED_CONSTRAINTS if c not in con_names_after]

if missing_tables:
    print(f"\n!! ERROR: tables still missing after apply: {missing_tables}")
    sys.exit(1)
if missing_cons:
    print(f"\n!! ERROR: constraints still missing after apply: {missing_cons}")
    sys.exit(1)
if problems:
    print("\n!! ERROR: structural mismatch after apply:")
    for p in problems:
        print(f"     - {p}")
    sys.exit(1)

print("\n  All Spec 1 tables, columns, and constraints present and correct.")
print("\n  MIGRATION COMPLETE.\n")
