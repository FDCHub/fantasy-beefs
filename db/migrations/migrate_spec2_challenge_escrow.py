"""
db/migrations/migrate_spec2_challenge_escrow.py — SPEC 2 (Challenge Escrow &
Atomic Acceptance) · Package 2B **Group 1** — the event / batch / provenance
foundation.

UPGRADE PATH ONLY. A clean install never calls this: db.schema.create_all() and
the PostgreSQL test harness build every table below straight from the models.
This exists solely as catch-up for an already-deployed database.

GROUP 1 SCOPE, AND NOTHING BEYOND IT. This migration creates the durable
representation Ruling 1 and Spec 2 §5 require, and stops there:

    protocol_events          the single idempotency authority (Ruling 1)
    ledger_posting_batches   the balanced-transaction tier between event and leg
    challenge_funding_legs   ordered append-only source-funding provenance (§5)
    ledger_entries.batch_id  the leg's link up to its batch, nullable

It creates NO escrow account, moves NO money, converts NO legacy row, and
implements NO funding behaviour. Challenge escrow state and data belong to later
Package 2B groups; none of their DDL is inseparable from the four objects above,
so none of it is here.

TWO PHASES, AND THE SECOND IS ONE TRANSACTION — the discipline the B6 migration
established and review accepted:

    PHASE 1  read-only. Applicability, schema inspection, the legacy beef
             census, and unexpected-schema classification. NOTHING is mutated,
             so every fail-closed refusal leaves nothing behind.
    PHASE 2  exactly one `with engine.begin() as conn:`. Every CREATE TABLE,
             ALTER and CREATE INDEX runs on that one Connection. PostgreSQL is
             transactional for DDL, so a failure anywhere rolls all of it back.

Tables are created with `Table.create(bind=conn)` and NOT `Table.create(engine)`.
Given an Engine, SQLAlchemy checks out its own connection and COMMITS
independently, so a later failure would strand them as a partial migration.

THE LEGACY BEEF CENSUS IS A PRECONDITION, NOT A STEP. Spec 2 §14: "Existence
gate (same discipline as Spec 1): count existing beef rows before any migration;
clean transition only if zero, else stop for reviewed plan." Spec 1 §11 names
the three counts and states plainly that "the remembered FR-5.13 zero-row
invariant is NOT sufficient authority to skip the count" — so the count is
executed here, every run, and never assumed.

    1. BeefChallenge rows
    2. BeefStarter rows
    3. Bet rows linked to a beef challenge

All zero  → proceed.
ANY nonzero → HALT. No backfill, no classification, no quarantine, no partial
migration, and nothing dropped or rewritten. Legacy rows lack versioned proposal
ownership, counter-specific starter snapshots and immutable proposal pricing
history; provenance that describes a funding history which never existed would
be worse than none.

IT DROPS NOTHING AND TOUCHES NO DATA. No table, column, row, constraint or index
is ever dropped, and not one row is inserted, updated or deleted. The only
statements that read rows are the census, and they count.

SQLITE IS NOT A DEPLOYMENT TARGET FOR THIS PATH, stated here rather than
discovered at runtime: SQLite cannot ALTER TABLE ADD CONSTRAINT and is rebuilt
from the models on every run, where the models already carry everything. On
SQLite this returns a report saying exactly that and changes nothing.

NOTHING RUNS ON IMPORT. run_migration() is called explicitly, by an operator,
against a database they have chosen.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from db.schema import (
    ChallengeFundingLeg,
    LedgerPostingBatch,
    ProtocolEvent,
    engine,
)

# ── Table names ───────────────────────────────────────────────────────────────
T_PROTOCOL_EVENT = "protocol_events"
T_POSTING_BATCH  = "ledger_posting_batches"
T_FUNDING_LEG    = "challenge_funding_legs"
T_LEDGER         = "ledger_entries"
T_CHALLENGE      = "beef_challenges"
T_STARTER        = "beef_starters"
T_BET            = "bets"

# ── Named constraints and indexes (every one a module constant) ───────────────
UQ_EVENT_ID        = "uq_protocol_event_event_id"
UQ_BATCH_POSTING   = "uq_ledger_posting_batch_posting_id"
UQ_LEG_SEQUENCE    = "uq_challenge_funding_leg_sequence"
CK_LEG_KIND        = "ck_challenge_funding_leg_kind"
CK_LEG_LINKAGE     = "ck_challenge_funding_leg_reversal_linkage"
CK_LEG_AMOUNT_SIGN = "ck_challenge_funding_leg_amount_sign"

COL_LEDGER_BATCH_ID = "batch_id"
IX_LEDGER_BATCH_ID  = "ix_ledger_entries_batch_id"

# The CHECKs challenge_funding_legs must carry once present.
LEG_CHECKS = (CK_LEG_KIND, CK_LEG_LINKAGE, CK_LEG_AMOUNT_SIGN)


# ── Errors ────────────────────────────────────────────────────────────────────

class Spec2MigrationError(RuntimeError):
    """Base for every fail-closed refusal here. Nothing is written on any path
    that raises."""


class LegacyBeefCensusError(Spec2MigrationError):
    """Spec 2 §14 / Spec 1 §11 — the deployed database holds legacy beef rows.
    HALT AND ESCALATE. No backfill, no classification, no quarantine, no partial
    migration. Nothing was created or altered before this was raised."""


class UnexpectedSchemaError(Spec2MigrationError):
    """The database is in a shape this migration does not recognise — a
    half-created table, a missing authority constraint, or a batch_id column of
    the wrong type. Refused rather than repaired: completing a structure whose
    provenance is unknown could silently produce a second, weaker idempotency
    home."""


# ── Phase 1 helpers (read-only) ───────────────────────────────────────────────

def _census(conn, inspector) -> dict:
    """Spec 1 §11's three counts, executed — never assumed.

    A table that does not exist yet contributes zero, which is the truthful
    answer: a database without beef_starters holds no legacy starters.
    """
    tables = set(inspector.get_table_names())

    def _count(sql: str, table: str) -> int:
        if table not in tables:
            return 0
        return int(conn.execute(text(sql)).scalar() or 0)

    challenges = _count(f"SELECT COUNT(*) FROM {T_CHALLENGE}", T_CHALLENGE)
    starters   = _count(f"SELECT COUNT(*) FROM {T_STARTER}",   T_STARTER)
    # Only beef-linked bets — an unrelated straight bet is not legacy beef state.
    beef_bets  = _count(
        f"SELECT COUNT(*) FROM {T_BET} WHERE beef_challenge_id IS NOT NULL", T_BET)

    return {"challenges": challenges, "starters": starters, "beef_bets": beef_bets,
            "total": challenges + starters + beef_bets}


def _uniques(inspector, table: str) -> set:
    return {u["name"] for u in inspector.get_unique_constraints(table)}


def _checks(inspector, table: str) -> set:
    try:
        return {c["name"] for c in inspector.get_check_constraints(table)}
    except NotImplementedError:
        return set()


def _classify_schema(inspector) -> list:
    """Fail-closed inspection. Returns the list of objects that still need
    creating; raises if anything present is unrecognisable.

    A table that exists WITHOUT its authority constraint is the dangerous case:
    protocol_events without UNIQUE(event_id) is not a partially-built table, it
    is a table that cannot do the one job it exists for.
    """
    tables = set(inspector.get_table_names())

    if T_LEDGER not in tables:
        raise UnexpectedSchemaError(
            f"{T_LEDGER} does not exist. This migration adds a batch reference "
            f"to the ledger; it cannot run against a database with no ledger. "
            f"Create the ledger first (ledger.create_ledger_table())."
        )

    if T_PROTOCOL_EVENT in tables and UQ_EVENT_ID not in _uniques(inspector, T_PROTOCOL_EVENT):
        raise UnexpectedSchemaError(
            f"{T_PROTOCOL_EVENT} exists but carries no {UQ_EVENT_ID}. Ruling 1 "
            f"makes UNIQUE(event_id) the single idempotency authority, so a "
            f"table without it would accept duplicate events silently. Refusing "
            f"to adopt it. Investigate its provenance."
        )

    if T_POSTING_BATCH in tables and UQ_BATCH_POSTING not in _uniques(inspector, T_POSTING_BATCH):
        raise UnexpectedSchemaError(
            f"{T_POSTING_BATCH} exists but carries no {UQ_BATCH_POSTING}. One "
            f"posting_id must be exactly one batch. Refusing to adopt it."
        )

    if T_FUNDING_LEG in tables:
        missing_ck = [c for c in LEG_CHECKS if c not in _checks(inspector, T_FUNDING_LEG)]
        missing_uq = UQ_LEG_SEQUENCE not in _uniques(inspector, T_FUNDING_LEG)
        if missing_ck or missing_uq:
            raise UnexpectedSchemaError(
                f"{T_FUNDING_LEG} exists but is missing "
                f"{missing_ck + ([UQ_LEG_SEQUENCE] if missing_uq else [])}. The "
                f"ordering uniqueness and the fund/reverse linkage biconditional "
                f"are what make strict reverse-order refunds provably exact "
                f"(§5); a table without them cannot carry provenance safely. "
                f"Refusing to adopt it."
            )

    ledger_cols = {c["name"]: c for c in inspector.get_columns(T_LEDGER)}
    if COL_LEDGER_BATCH_ID in ledger_cols:
        col_type = str(ledger_cols[COL_LEDGER_BATCH_ID]["type"]).upper()
        if "INT" not in col_type:
            raise UnexpectedSchemaError(
                f"{T_LEDGER}.{COL_LEDGER_BATCH_ID} exists with type {col_type!r}, "
                f"which is not an integer batch reference. Refusing to reinterpret "
                f"an existing column of unknown meaning."
            )

    return [t for t in (T_PROTOCOL_EVENT, T_POSTING_BATCH, T_FUNDING_LEG)
            if t not in tables]


# ── The migration ─────────────────────────────────────────────────────────────

def run_migration() -> dict:
    """Bring a deployed database up to the Group 1 foundation. Returns what this
    run did:

        {
          "applicable":       bool,
          "dialect":          str,
          "census":           {challenges, starters, beef_bets, total},
          "tables_created":   [...],
          "columns_added":    [...],
          "indexes_created":  [...],
        }

    A second run reports empty lists. Raises LegacyBeefCensusError or
    UnexpectedSchemaError, having changed nothing, on either fail-closed
    condition.
    """
    dialect = engine.dialect.name
    if dialect == "sqlite":
        return {
            "applicable": False,
            "dialect":    dialect,
            "reason": ("SQLite is rebuilt from the models on every run and "
                       "cannot ALTER TABLE ADD CONSTRAINT; there is no upgrade "
                       "path to express and none is needed. Nothing changed."),
            "census": None,
            "tables_created": [], "columns_added": [], "indexes_created": [],
        }

    report: dict = {
        "applicable": True, "dialect": dialect,
        "tables_created": [], "columns_added": [], "indexes_created": [],
    }

    # ══════════════════════════════════════════════════════════════════════
    # PHASE 1 — READ-ONLY. Every refusal is raised from here, so a refusal
    # performs zero DDL.
    # ══════════════════════════════════════════════════════════════════════
    inspector = inspect(engine)

    with engine.connect() as ro_conn:
        census = _census(ro_conn, inspector)
    report["census"] = census

    if census["total"] > 0:
        raise LegacyBeefCensusError(
            f"The database holds legacy beef state: {census['challenges']} "
            f"challenge(s), {census['starters']} starter row(s), "
            f"{census['beef_bets']} beef-linked bet(s). Spec 2 §14 and Spec 1 "
            f"§11 permit a clean transition only when all are zero. Legacy rows "
            f"carry no versioned proposal ownership, no counter-specific starter "
            f"snapshot and no immutable pricing history, so no funding provenance "
            f"can be reconstructed for them. HALTING before any schema change: "
            f"no backfill, no classification, no quarantine, nothing dropped. "
            f"Escalate for a reviewed plan."
        )

    to_create = _classify_schema(inspector)

    ledger_cols = {c["name"] for c in inspector.get_columns(T_LEDGER)}
    need_batch_col = COL_LEDGER_BATCH_ID not in ledger_cols
    need_batch_idx = IX_LEDGER_BATCH_ID not in {
        i["name"] for i in inspector.get_indexes(T_LEDGER)}

    # ══════════════════════════════════════════════════════════════════════
    # PHASE 2 — every mutating statement, on ONE transactional Connection.
    # ══════════════════════════════════════════════════════════════════════
    with engine.begin() as conn:
        # bind=conn, NOT the Engine — see the module docstring.
        # Order matters: batches reference events, legs reference both.
        for model, name in ((ProtocolEvent,      T_PROTOCOL_EVENT),
                            (LedgerPostingBatch, T_POSTING_BATCH),
                            (ChallengeFundingLeg, T_FUNDING_LEG)):
            model.__table__.create(bind=conn, checkfirst=True)
            if name in to_create:
                report["tables_created"].append(name)

        # The ledger leg's link up to its batch. NULLABLE — that is the
        # compatibility contract: every posting made without an explicit
        # protocol event leaves it NULL and behaves exactly as before. No FK:
        # ledger_entries lives on a separate declarative base (see the model).
        if need_batch_col:
            conn.execute(text(
                f"ALTER TABLE {T_LEDGER} ADD COLUMN {COL_LEDGER_BATCH_ID} INTEGER"))
            report["columns_added"].append(f"{T_LEDGER}.{COL_LEDGER_BATCH_ID}")

        # Last, so a late failure here proves the whole phase rolls back.
        if need_batch_idx:
            conn.execute(text(
                f"CREATE INDEX {IX_LEDGER_BATCH_ID} "
                f"ON {T_LEDGER} ({COL_LEDGER_BATCH_ID})"))
            report["indexes_created"].append(IX_LEDGER_BATCH_ID)

    return report


if __name__ == "__main__":
    result = run_migration()
    if not result.get("applicable", True):
        print(f"not applicable on {result['dialect']}: {result['reason']}")
        raise SystemExit(0)

    c = result["census"]
    print(f"dialect            : {result['dialect']}")
    print(f"legacy beef census : {c['challenges']} challenges, {c['starters']} "
          f"starters, {c['beef_bets']} beef-linked bets")
    print(f"tables created     : {result['tables_created'] or 'none'}")
    print(f"columns added      : {result['columns_added'] or 'none'}")
    print(f"indexes created    : {result['indexes_created'] or 'none'}")
    print("nothing was dropped; no row was inserted, updated, deleted or "
          "backfilled")
