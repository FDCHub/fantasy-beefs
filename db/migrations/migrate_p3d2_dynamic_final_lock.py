"""
db/migrations/migrate_p3d2_dynamic_final_lock.py — P3-D2 / SIMULATION ENGINE
Rev 9: the Dynamic Handshake freeze columns and the Final-Lock tables.

UPGRADE PATH ONLY. A clean install never calls this — `db.schema.create_all()`
and the PostgreSQL test harness build everything below straight from the models.
This exists solely as catch-up for an already-deployed database.

SCOPE, AND NOTHING BEYOND IT:

    beef_challenges.dynamic_issuer_ceiling_cents     Rev 9 §5 Handshake freeze
    beef_challenges.dynamic_opponent_ceiling_cents
    beef_challenges.dynamic_model_version_id         MODEL-A frozen identity
    beef_challenges.dynamic_model_config_hash
    beef_challenges.dynamic_handshake_at
    challenge_final_locks                            §7.3 FINALSTATE-A
    challenge_final_lock_claims                      §5.2 the execution mutex

It moves NO money, creates NO escrow account, and converts NO existing row.

ADDITIVE AND NON-DESTRUCTIVE. Every new column is nullable, so every Locked and
legacy `beef_challenges` row remains valid exactly as it stands — there is no
backfill, no default rewrite and no reinterpretation of accepted data. Nothing
already committed changes meaning.

TWO PHASES, AND THE SECOND IS ONE TRANSACTION — the discipline the B6 and
Group 1 migrations established and review accepted:

    PHASE 1  read-only. Applicability and schema inspection. Nothing is mutated,
             so a fail-closed refusal leaves nothing behind.
    PHASE 2  exactly one `with engine.begin() as conn:`. Every ALTER and CREATE
             runs on that one Connection. PostgreSQL is transactional for DDL,
             so a failure anywhere rolls all of it back.

Tables are created with `Table.create(bind=conn)` and NOT `Table.create(engine)`.
Given an Engine, SQLAlchemy checks out its own connection and commits
independently, so a later failure would strand them as a partial migration.

POSTGRES ONLY. The uniqueness and biconditional CHECK constraints carrying the
claim mutex are the whole point of the tables; proving them on SQLite would
prove nothing about production, and SQLite silently drops several ALTER forms.

    python db/migrations/migrate_p3d2_dynamic_final_lock.py            # dry run
    python db/migrations/migrate_p3d2_dynamic_final_lock.py --confirm  # apply
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlalchemy import inspect

from db.schema import (
    Base,
    ChallengeFinalLock,
    ChallengeFinalLockClaim,
    engine,
)

T_CHALLENGE = "beef_challenges"
T_FINALLOCK = "challenge_final_locks"
T_CLAIM     = "challenge_final_lock_claims"

NEW_COLUMNS = {
    "dynamic_issuer_ceiling_cents":   "INTEGER",
    "dynamic_opponent_ceiling_cents": "INTEGER",
    "dynamic_model_version_id":       "VARCHAR",
    "dynamic_model_config_hash":      "VARCHAR",
    "dynamic_handshake_at":           "TIMESTAMP WITHOUT TIME ZONE",
}


class MigrationRefused(RuntimeError):
    """Phase 1 refused. Nothing was mutated."""


# ── Phase 1 — read-only ───────────────────────────────────────────────────────

def inspect_state() -> dict:
    if engine.dialect.name != "postgresql":
        raise MigrationRefused(
            f"This migration targets PostgreSQL; the bound engine is "
            f"{engine.dialect.name!r}. The claim mutex and the biconditional "
            f"CHECKs are the deliverable, and SQLite cannot prove either.")

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if T_CHALLENGE not in tables:
        raise MigrationRefused(
            f"{T_CHALLENGE} is absent — this database predates Spec 1. Run the "
            f"proposal-lifecycle migration first.")

    existing_cols = {c["name"] for c in insp.get_columns(T_CHALLENGE)}
    return {
        "dialect":          engine.dialect.name,
        "columns_present":  sorted(c for c in NEW_COLUMNS if c in existing_cols),
        "columns_missing":  sorted(c for c in NEW_COLUMNS if c not in existing_cols),
        "final_locks_present": T_FINALLOCK in tables,
        "claims_present":      T_CLAIM in tables,
    }


# ── Phase 2 — one transaction ─────────────────────────────────────────────────

def run_migration(confirm: bool = False) -> dict:
    state = inspect_state()
    plan = {
        "add_columns":       state["columns_missing"],
        "create_final_locks": not state["final_locks_present"],
        "create_claims":      not state["claims_present"],
    }
    if not confirm:
        return {"applied": False, "state": state, "plan": plan}

    if not (plan["add_columns"] or plan["create_final_locks"]
            or plan["create_claims"]):
        return {"applied": False, "state": state, "plan": plan,
                "note": "already up to date — nothing to do"}

    with engine.begin() as conn:
        for col in plan["add_columns"]:
            # Nullable, no default: additive and non-destructive by construction.
            conn.exec_driver_sql(
                f"ALTER TABLE {T_CHALLENGE} ADD COLUMN {col} {NEW_COLUMNS[col]}")
        if plan["create_final_locks"]:
            ChallengeFinalLock.__table__.create(bind=conn)
        if plan["create_claims"]:
            ChallengeFinalLockClaim.__table__.create(bind=conn)

    return {"applied": True, "state": state, "plan": plan,
            "verified": inspect_state()}


if __name__ == "__main__":
    confirm = "--confirm" in sys.argv
    try:
        result = run_migration(confirm=confirm)
    except MigrationRefused as exc:
        print(f"[REFUSED] {exc}")
        sys.exit(2)

    print(f"dialect            : {result['state']['dialect']}")
    print(f"columns present    : {result['state']['columns_present']}")
    print(f"columns missing    : {result['state']['columns_missing']}")
    print(f"final-lock table   : {'present' if result['state']['final_locks_present'] else 'MISSING'}")
    print(f"claim table        : {'present' if result['state']['claims_present'] else 'MISSING'}")
    print(f"plan               : {result['plan']}")
    if result["applied"]:
        print(f"APPLIED. verified  : {result['verified']}")
    else:
        print(result.get("note", "DRY RUN — pass --confirm to apply."))