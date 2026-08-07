"""
db/migrations/migrate_b6_top_off.py — bring an ALREADY-DEPLOYED database up to
the accepted B6 model (§11, §15 item 20).

UPGRADE PATH ONLY. A clean install never calls this: db.schema.create_all() —
and the PostgreSQL test harness — build every B6 table, column, constraint and
index straight from the models. This module exists solely as catch-up for a
database that was deployed before B6, and it is the single migration for the
whole of Groups A-E: no migration was written during any of them, so the entire
B6 DDL delta lands here.

WHAT IT COVERS, by group of origin:

    A   ledger_entries — ix_ledger_entries_posting_id, ix_ledger_entries_door_account
    B   leagues.topoff_cap_multiplier_bps + its CHECK
        league_season_topoff_config (table, unique, CHECK, FK)
    C   faab_transactions — ten B6 columns, two FKs, two unique constraints,
        ck_faab_tx_decision, ck_faab_tx_topup_bet_lifecycle,
        ck_faab_tx_topup_bet_linkage, and the ck_faab_tx_status widening
        top_off_disclosure (table, two uniques, CHECK, five FKs)
    D   leagues.season_closed_at
    E   uq_faab_tx_one_open_topoff — the partial unique index

ADDITIVE, IDEMPOTENT, FORWARD-ONLY. Safe to run repeatedly; a second run reports
empty lists. There is no down migration — the house idiom has none, and neither
migrate_season_allocation.py nor migrate_league_commissioners.py provides one.

IT DROPS NOTHING, WITH EXACTLY ONE STATED EXCEPTION (see CK_FAAB_TX_STATUS
below). No table, column, row, foreign key, index or unrelated constraint is
ever dropped, and nothing is backfilled, classified, converted or quarantined.

IT NEVER TOUCHES DATA. Not one row is inserted, updated or deleted. The only
statement that reads rows is the census, and it counts.

SQLITE IS NOT A DEPLOYMENT TARGET FOR THIS PATH, and that is stated here rather
than discovered at runtime (§11.3). SQLite cannot ALTER TABLE ADD CONSTRAINT, so
an upgrade path there is not expressible — but it does not need one: production
is PostgreSQL, and SQLite is a test target rebuilt from the models on every run,
where the models already carry every constraint. On SQLite this function returns
a report saying exactly that and changes nothing.

THE CENSUS IS A PRECONDITION, NOT A STEP (§11.4). Before any DDL at all it counts

    SELECT COUNT(*) FROM faab_transactions
    WHERE type = 'topup_bet' AND status = 'applied'

Zero proceeds. NONZERO HALTS: LegacyCensusError is raised and nothing is created,
altered or repaired. There is no backfill, no guess, no partial classification
and no quarantine table. A legacy applied top-up predates every B6 control — it
has no requester, no approver, no posting and no disclosure — and the two
topup_bet-scoped CHECKs installed below would refuse it. Running the census
first turns that into one diagnosable refusal instead of a half-migrated schema.

A SECOND PRECONDITION IS REQUIRED, and §11.4 does not name it. The lifecycle
CHECK is `type <> 'topup_bet' OR (decision IS NOT NULL AND ...)`, so it refuses
ANY topup_bet row carrying a NULL decision — not only an applied one. Every
pre-B6 top-up row is exactly that: `decision` did not exist before B6, so a
deployed database holding even one dormant `pending` or `cancelled` topup_bet row
would make ADD CONSTRAINT fail. Counting only the applied ones would leave that
to surface as an opaque CheckViolation from the middle of the migration.

So the census counts undecided topup_bet rows too and HALTS on them, for the same
reasons and with the same discipline: no backfill, no invented decision, no
quarantine. Writing a decision onto dormant history would turn a legacy row into
something B6 believes it governs, and §11.5 is explicit that legacy rows never
become B6 requests.

TWO PHASES, AND THE SECOND IS ONE TRANSACTION.

    PHASE 1  read-only. Applicability, schema inspection, both censuses, and the
             ck_faab_tx_status classification. NOTHING is mutated. Every
             fail-closed refusal is raised here, so a refusal cannot leave a
             half-migrated schema — there is nothing to leave.

    PHASE 2  exactly one `with engine.begin() as conn:`. EVERY mutating
             statement runs on that one Connection: both CREATE TABLEs, every
             ALTER, every CREATE INDEX and the ck_faab_tx_status DROP/ADD pair.
             PostgreSQL is transactional for DDL, so an unexpected failure
             anywhere in Phase 2 rolls the whole thing back and the database is
             exactly as it was.

The two new tables are created with `Table.create(bind=conn)` and NOT
`Table.create(engine)`. That distinction is the whole point: given an Engine,
SQLAlchemy checks out its own connection and commits independently, so a later
failure would leave those two tables behind as a partial migration. Bound to the
open Connection they participate in the same transaction as everything else.
The migration suite asserts this directly by forcing a late failure and checking
that both tables are gone.

CK_FAAB_TX_STATUS — THE ONE AUTHORIZED REPLACEMENT, UNDER A FAIL-CLOSED RULE.
B6 widened this constraint to admit 'rejected', because §4.4's legal state matrix
requires (decision='rejected', status='rejected') to be committable and the prior
definition forbade it outright. A widening cannot be expressed additively: the
old CHECK must go. Note also that this item is ABSENT from §11.2's DDL list —
the constraint NAME did not change, only its body, so it does not appear in any
name-level comparison. Without this replacement every terminal rejection, the one
outcome that writes a state transition, is refused by the database.

The replacement is permitted ONLY when the deployed definition is recognised:

    known OLD    ('pending','applied','cancelled','failed')      -> DROP and ADD
    known TARGET ('pending','applied','rejected','cancelled','failed') -> no-op
    absent                                                       -> FAIL CLOSED
    anything else                                                -> FAIL CLOSED

An unrecognised definition is never replaced. Comparison is by the SET of quoted
literals in the deployed expression, not by its text: PostgreSQL rewrites
`status IN (...)` into an `= ANY (ARRAY[...])` form with casts, so a literal
string comparison would never match anything.

FAAB_TRANSACTIONS.STATUS KEEPS NO SERVER DEFAULT. §11.2 lists "status — default
changed to 'pending'" as DDL, but in this codebase that default is
Column(default="pending"), which is CLIENT-side and emits no server DEFAULT; the
column carries no server_default in db/schema.py. Adding one here would give the
deployed table a default the model does not have. This migration therefore adds
no default to that column, deliberately.

NOTHING HERE RUNS ON IMPORT. run_migration() is called explicitly, by an
operator, against a database they have chosen. Importing this module executes no
statement.
"""

from __future__ import annotations

import os
import re
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from db.schema import LeagueSeasonTopoffConfig, TopOffDisclosure, engine

# ── Table names ───────────────────────────────────────────────────────────────
T_LEAGUES        = "leagues"
T_FAAB_TX        = "faab_transactions"
T_LEDGER         = "ledger_entries"
T_LSTC           = "league_season_topoff_config"
T_DISCLOSURE     = "top_off_disclosure"

# ── Named constraints and indexes (every one a module constant, per §11.1) ────
CK_LEAGUES_MULTIPLIER = "ck_leagues_topoff_multiplier_bps"
CK_FAAB_TX_STATUS     = "ck_faab_tx_status"
CK_FAAB_TX_DECISION   = "ck_faab_tx_decision"
CK_FAAB_TX_LIFECYCLE  = "ck_faab_tx_topup_bet_lifecycle"
CK_FAAB_TX_LINKAGE    = "ck_faab_tx_topup_bet_linkage"
FK_FAAB_TX_REQUESTER  = "fk_faab_tx_requester_user"
FK_FAAB_TX_DECIDED_BY = "fk_faab_tx_decided_by_user"

# Unnamed `unique=True` on a Column yields PostgreSQL's own "<table>_<col>_key"
# on the clean-install path. These constants reproduce that EXACT name so an
# upgraded database and a freshly created one carry the same constraint under
# the same name — the migration must not invent a different uniqueness contract.
UQ_FAAB_TX_POSTING    = "faab_transactions_ledger_posting_id_key"
UQ_FAAB_TX_DISCLOSURE = "faab_transactions_disclosure_event_id_key"

IX_FAAB_TX_ONE_OPEN   = "uq_faab_tx_one_open_topoff"
IX_LEDGER_POSTING     = "ix_ledger_entries_posting_id"
IX_LEDGER_DOOR_ACCT   = "ix_ledger_entries_door_account"

# ── The two recognised ck_faab_tx_status definitions ──────────────────────────
OLD_STATUS_VALUES    = frozenset({"pending", "applied", "cancelled", "failed"})
TARGET_STATUS_VALUES = frozenset({"pending", "applied", "rejected", "cancelled",
                                  "failed"})
TARGET_STATUS_SQL    = ("status IN ('pending','applied','rejected','cancelled',"
                        "'failed')")

# ── The B6 columns added to existing tables ───────────────────────────────────
LEAGUES_COLUMNS = (
    ("topoff_cap_multiplier_bps", "INTEGER NOT NULL DEFAULT 10000"),
    ("season_closed_at",          "TIMESTAMP WITHOUT TIME ZONE"),
)

FAAB_TX_COLUMNS = (
    ("requester_user_id",   "INTEGER"),
    ("decided_by_user_id",  "INTEGER"),
    ("decision",            "VARCHAR"),
    ("decision_reason",     "TEXT"),
    ("decided_at",          "TIMESTAMP WITHOUT TIME ZONE"),
    ("ledger_posting_id",   "UUID"),
    ("disclosure_event_id", "UUID"),
    ("amount_cents",        "INTEGER"),
    ("season",              "INTEGER"),
    ("self_approved",       "BOOLEAN"),
)


# ── Errors ────────────────────────────────────────────────────────────────────

class B6MigrationError(RuntimeError):
    """Base for every fail-closed refusal in this migration. Nothing is written
    on any path that raises."""


class LegacyCensusError(B6MigrationError):
    """§11.4 — the deployed database holds applied legacy top_up rows. HALT AND
    ESCALATE. No backfill, no guess, no partial classification, no quarantine.
    Nothing was created, altered or repaired before this was raised."""


class UnexpectedConstraintError(B6MigrationError):
    """ck_faab_tx_status is absent, or carries a definition this migration does
    not recognise. Refused rather than replaced: dropping a constraint whose
    meaning is unknown could silently widen what the database accepts."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _census(conn, has_decision_column: bool) -> dict:
    """§11.4's precondition, plus the undecided count the lifecycle CHECK needs.

    `undecided` is what would defeat ck_faab_tx_topup_bet_lifecycle. On a genuine
    pre-B6 schema the `decision` column does not exist yet, and no legacy row can
    possibly carry one — so every topup_bet row is undecided by construction and
    the total IS the undecided count.
    """
    applied = conn.execute(text(
        f"SELECT COUNT(*) FROM {T_FAAB_TX} "
        f"WHERE type = 'topup_bet' AND status = 'applied'"
    )).scalar()
    total = conn.execute(text(
        f"SELECT COUNT(*) FROM {T_FAAB_TX} WHERE type = 'topup_bet'"
    )).scalar()
    if has_decision_column:
        undecided = conn.execute(text(
            f"SELECT COUNT(*) FROM {T_FAAB_TX} "
            f"WHERE type = 'topup_bet' AND decision IS NULL"
        )).scalar()
    else:
        undecided = total
    return {"applied":   int(applied or 0),
            "total":     int(total or 0),
            "undecided": int(undecided or 0)}


def _check_constraints(inspector, table: str) -> dict:
    try:
        return {c["name"]: (c.get("sqltext") or "")
                for c in inspector.get_check_constraints(table)}
    except NotImplementedError:          # dialect without check introspection
        return {}


def _status_check_action(inspector) -> str:
    """'replace', 'noop', or raise. See CK_FAAB_TX_STATUS in the module docstring.

    The deployed expression is compared by the SET of quoted literals it
    contains, because PostgreSQL rewrites `status IN (...)` into
    `(status)::text = ANY ((ARRAY['pending'::character varying, ...])::text[])`
    and no literal text comparison would ever match.
    """
    checks = _check_constraints(inspector, T_FAAB_TX)
    if CK_FAAB_TX_STATUS not in checks:
        raise UnexpectedConstraintError(
            f"{CK_FAAB_TX_STATUS} is ABSENT from {T_FAAB_TX}. This migration "
            f"expects either the pre-B6 definition {sorted(OLD_STATUS_VALUES)} "
            f"or the B6 target {sorted(TARGET_STATUS_VALUES)}. Refusing to "
            f"invent a status constraint on a table whose current rules are "
            f"unknown. Nothing was changed."
        )
    values = frozenset(re.findall(r"'([^']*)'", checks[CK_FAAB_TX_STATUS]))
    if values == TARGET_STATUS_VALUES:
        return "noop"
    if values == OLD_STATUS_VALUES:
        return "replace"
    raise UnexpectedConstraintError(
        f"{CK_FAAB_TX_STATUS} carries an UNRECOGNISED definition: permitted "
        f"values {sorted(values)}. This migration replaces that constraint only "
        f"when it is exactly the known pre-B6 set {sorted(OLD_STATUS_VALUES)}, "
        f"and does nothing when it is already the target "
        f"{sorted(TARGET_STATUS_VALUES)}. Dropping a third definition could "
        f"silently widen what the database accepts. Nothing was changed."
    )


# ── The migration ─────────────────────────────────────────────────────────────

def run_migration() -> dict:
    """Bring a deployed database up to the B6 model. Returns what this run did:

        {
          "applicable":               bool,
          "dialect":                  str,
          "legacy_applied_topup_bet": int,
          "legacy_topup_bet_total":   int,
          "tables_created":           [...],
          "columns_added":            [...],
          "constraints_added":        [...],
          "constraints_replaced":     [...],
          "indexes_created":          [...],
          "status_check_action":      "replace" | "noop",
        }

    A second run reports empty lists and status_check_action 'noop'.

    Raises LegacyCensusError or UnexpectedConstraintError, having changed
    nothing, on either fail-closed condition.
    """
    dialect = engine.dialect.name
    if dialect == "sqlite":
        # Stated, not discovered (§11.3). SQLite cannot ALTER TABLE ADD
        # CONSTRAINT, so no upgrade path is expressible — and none is needed,
        # because SQLite is only ever built fresh from the models, which already
        # carry every constraint.
        return {
            "applicable": False,
            "dialect":    dialect,
            "reason": ("SQLite is rebuilt from the models on every run and "
                       "cannot ALTER TABLE ADD CONSTRAINT; there is no upgrade "
                       "path to express and none is needed. Nothing changed."),
            "tables_created": [], "columns_added": [], "constraints_added": [],
            "constraints_replaced": [], "indexes_created": [],
        }

    report: dict = {
        "applicable": True, "dialect": dialect,
        "tables_created": [], "columns_added": [], "constraints_added": [],
        "constraints_replaced": [], "indexes_created": [],
    }

    # ══════════════════════════════════════════════════════════════════════
    # PHASE 1 — READ-ONLY. Every fail-closed refusal is raised from here, so a
    # refusal performs zero DDL: no table, no column, no constraint, no index.
    # ══════════════════════════════════════════════════════════════════════

    # ── PRECONDITION 1 — the legacy census (§11.4). ──
    inspector = inspect(engine)
    has_decision = "decision" in {c["name"]
                                  for c in inspector.get_columns(T_FAAB_TX)}
    # A READ-ONLY connection, named apart from the Phase 2 repair connection so
    # the two can never be confused at a glance. It executes SELECTs only.
    with engine.connect() as ro_conn:
        census = _census(ro_conn, has_decision)
    report["legacy_applied_topup_bet"]   = census["applied"]
    report["legacy_topup_bet_total"]     = census["total"]
    report["legacy_undecided_topup_bet"] = census["undecided"]

    if census["applied"] > 0:
        raise LegacyCensusError(
            f"{census['applied']} legacy row(s) in {T_FAAB_TX} have "
            f"type='topup_bet' AND status='applied'. A pre-B6 applied top-up "
            f"carries no requester, no approver, no ledger posting and no "
            f"disclosure, so it cannot satisfy the B6 lifecycle and linkage "
            f"constraints this migration installs. HALTING before any schema "
            f"change: no backfill, no classification, no quarantine, no partial "
            f"migration. Escalate and decide what these rows are."
        )

    if census["undecided"] > 0:
        raise LegacyCensusError(
            f"{census['undecided']} legacy row(s) in {T_FAAB_TX} have "
            f"type='topup_bet' with NO decision. {CK_FAAB_TX_LIFECYCLE} requires "
            f"every topup_bet row to carry one, so it cannot be installed over "
            f"them. Writing a decision onto dormant history is refused outright: "
            f"§11.5 is explicit that a legacy row never becomes a B6 request, and "
            f"inventing one would make B6 believe it governs a row it never "
            f"issued. HALTING before any schema change. Escalate and decide what "
            f"these rows are — retiring or archiving them is a data decision, not "
            f"a migration one."
        )

    # ── PRECONDITION 2 — recognise ck_faab_tx_status before touching it. ──
    status_action = _status_check_action(inspector)
    report["status_check_action"] = status_action

    # ── The rest of PHASE 1: read the current shape. Still nothing mutated. ──
    existing_tables = set(inspector.get_table_names())
    leagues_cols = {c["name"] for c in inspector.get_columns(T_LEAGUES)}
    faab_cols    = {c["name"] for c in inspector.get_columns(T_FAAB_TX)}
    faab_checks  = set(_check_constraints(inspector, T_FAAB_TX))
    leagues_chk  = set(_check_constraints(inspector, T_LEAGUES))
    faab_uqs     = {u["name"] for u in inspector.get_unique_constraints(T_FAAB_TX)}
    faab_fks     = {f["name"] for f in inspector.get_foreign_keys(T_FAAB_TX)}
    faab_idx     = {i["name"] for i in inspector.get_indexes(T_FAAB_TX)}
    ledger_idx   = {i["name"] for i in inspector.get_indexes(T_LEDGER)}

    # ══════════════════════════════════════════════════════════════════════
    # PHASE 2 — every mutating statement, on ONE transactional Connection.
    # ══════════════════════════════════════════════════════════════════════
    with engine.begin() as conn:
        # ── New tables, straight from the models (Groups B and C). ──
        # bind=conn, NOT the Engine. Given an Engine, Table.create() checks out
        # its own connection and COMMITS independently, so these two tables
        # would survive a failure later in this block as a partial migration.
        # Bound to the open Connection they roll back with everything else.
        #
        # checkfirst=True creates each table WITH its FKs, unique constraints
        # and CHECK constraints exactly as the model declares them, and is a
        # no-op when the table already exists.
        for model, name in ((LeagueSeasonTopoffConfig, T_LSTC),
                            (TopOffDisclosure,         T_DISCLOSURE)):
            model.__table__.create(bind=conn, checkfirst=True)
            if name not in existing_tables:
                report["tables_created"].append(name)

        # ── leagues (Groups B and D) ──
        for col, ddl in LEAGUES_COLUMNS:
            if col not in leagues_cols:
                conn.execute(text(f"ALTER TABLE {T_LEAGUES} ADD COLUMN {col} {ddl}"))
                report["columns_added"].append(f"{T_LEAGUES}.{col}")
        if CK_LEAGUES_MULTIPLIER not in leagues_chk:
            conn.execute(text(
                f"ALTER TABLE {T_LEAGUES} ADD CONSTRAINT {CK_LEAGUES_MULTIPLIER} "
                f"CHECK (topoff_cap_multiplier_bps IN (0, 5000, 10000, 15000, 20000))"
            ))
            report["constraints_added"].append(CK_LEAGUES_MULTIPLIER)

        # ── faab_transactions columns (Group C) ──
        for col, ddl in FAAB_TX_COLUMNS:
            if col not in faab_cols:
                conn.execute(text(f"ALTER TABLE {T_FAAB_TX} ADD COLUMN {col} {ddl}"))
                report["columns_added"].append(f"{T_FAAB_TX}.{col}")

        # ── faab_transactions foreign keys (Group C) ──
        for fk_name, col in ((FK_FAAB_TX_REQUESTER,  "requester_user_id"),
                             (FK_FAAB_TX_DECIDED_BY, "decided_by_user_id")):
            if fk_name not in faab_fks:
                conn.execute(text(
                    f"ALTER TABLE {T_FAAB_TX} ADD CONSTRAINT {fk_name} "
                    f"FOREIGN KEY ({col}) REFERENCES users(id)"
                ))
                report["constraints_added"].append(fk_name)

        # ── faab_transactions uniqueness (Group C) ──
        # Unique WHEN NON-NULL: PostgreSQL permits repeated NULLs in a unique
        # constraint, which is exactly the required semantics — many undecided
        # requests, at most one claim on any posting or disclosure.
        for uq_name, col in ((UQ_FAAB_TX_POSTING,    "ledger_posting_id"),
                             (UQ_FAAB_TX_DISCLOSURE, "disclosure_event_id")):
            if uq_name not in faab_uqs:
                conn.execute(text(
                    f"ALTER TABLE {T_FAAB_TX} ADD CONSTRAINT {uq_name} "
                    f"UNIQUE ({col})"
                ))
                report["constraints_added"].append(uq_name)

        # ── ck_faab_tx_status — the one authorized replacement. ──
        if status_action == "replace":
            conn.execute(text(
                f"ALTER TABLE {T_FAAB_TX} DROP CONSTRAINT {CK_FAAB_TX_STATUS}"))
            conn.execute(text(
                f"ALTER TABLE {T_FAAB_TX} ADD CONSTRAINT {CK_FAAB_TX_STATUS} "
                f"CHECK ({TARGET_STATUS_SQL})"))
            report["constraints_replaced"].append(CK_FAAB_TX_STATUS)

        # ── faab_transactions CHECKs (Group C) ──
        if CK_FAAB_TX_DECISION not in faab_checks:
            conn.execute(text(
                f"ALTER TABLE {T_FAAB_TX} ADD CONSTRAINT {CK_FAAB_TX_DECISION} "
                f"CHECK (decision IS NULL OR decision IN "
                f"('pending','approved','rejected','cancelled'))"
            ))
            report["constraints_added"].append(CK_FAAB_TX_DECISION)

        # The two topup_bet-scoped CHECKs. Reachable only because the census
        # above passed: PostgreSQL validates existing rows when a CHECK is
        # added, so a legacy applied top-up would make these fail outright.
        if CK_FAAB_TX_LIFECYCLE not in faab_checks:
            conn.execute(text(
                f"ALTER TABLE {T_FAAB_TX} ADD CONSTRAINT {CK_FAAB_TX_LIFECYCLE} "
                f"CHECK (type <> 'topup_bet'"
                f" OR (decision IS NOT NULL"
                f"     AND ((decision = 'pending'   AND status = 'pending')"
                f"       OR (decision = 'approved'  AND status = 'applied')"
                f"       OR (decision = 'rejected'  AND status = 'rejected')"
                f"       OR (decision = 'cancelled' AND status = 'cancelled'))))"
            ))
            report["constraints_added"].append(CK_FAAB_TX_LIFECYCLE)

        if CK_FAAB_TX_LINKAGE not in faab_checks:
            conn.execute(text(
                f"ALTER TABLE {T_FAAB_TX} ADD CONSTRAINT {CK_FAAB_TX_LINKAGE} "
                f"CHECK (type <> 'topup_bet'"
                f" OR (((decision = 'approved' AND status = 'applied')"
                f"      = (ledger_posting_id IS NOT NULL))"
                f"     AND ((decision = 'approved' AND status = 'applied')"
                f"          = (disclosure_event_id IS NOT NULL))))"
            ))
            report["constraints_added"].append(CK_FAAB_TX_LINKAGE)

        # ── NB-E5 — the partial unique index (Group E). ──
        # LOAD-BEARING. §8.5 assigns duplicate-creation prevention to THIS index
        # rather than to an application check: two concurrent creates can both
        # pass the service's fast-path pre-check, and only the index makes
        # exactly one of them survive. It exists in the model and therefore in
        # every model-built test schema, but nowhere in a deployed database until
        # this statement runs. It must come after the `season` column above.
        if IX_FAAB_TX_ONE_OPEN not in faab_idx:
            conn.execute(text(
                f"CREATE UNIQUE INDEX {IX_FAAB_TX_ONE_OPEN} "
                f"ON {T_FAAB_TX} (league_id, team_id, season) "
                f"WHERE type = 'topup_bet' AND status = 'pending'"
            ))
            report["indexes_created"].append(IX_FAAB_TX_ONE_OPEN)

        # ── ledger_entries indexes (Group A). ──
        # Without these every approval table-scans the ledger, and the scan grows
        # with every posting the platform ever makes.
        if IX_LEDGER_POSTING not in ledger_idx:
            conn.execute(text(
                f"CREATE INDEX {IX_LEDGER_POSTING} ON {T_LEDGER} (posting_id)"))
            report["indexes_created"].append(IX_LEDGER_POSTING)
        if IX_LEDGER_DOOR_ACCT not in ledger_idx:
            conn.execute(text(
                f"CREATE INDEX {IX_LEDGER_DOOR_ACCT} ON {T_LEDGER} (door, account)"))
            report["indexes_created"].append(IX_LEDGER_DOOR_ACCT)

    return report


if __name__ == "__main__":
    result = run_migration()
    if not result.get("applicable", True):
        print(f"not applicable on {result['dialect']}: {result['reason']}")
        raise SystemExit(0)

    print(f"dialect                  : {result['dialect']}")
    print(f"legacy topup_bet rows    : {result['legacy_topup_bet_total']} "
          f"({result['legacy_applied_topup_bet']} applied, "
          f"{result['legacy_undecided_topup_bet']} undecided)")
    print(f"tables created           : {result['tables_created'] or 'none'}")
    print(f"columns added            : {result['columns_added'] or 'none'}")
    print(f"constraints added        : {result['constraints_added'] or 'none'}")
    print(f"constraints replaced     : {result['constraints_replaced'] or 'none'}")
    print(f"indexes created          : {result['indexes_created'] or 'none'}")
    print(f"ck_faab_tx_status        : {result['status_check_action']}")
    print("nothing was dropped except the stated ck_faab_tx_status replacement; "
          "no row was inserted, updated, deleted or backfilled")