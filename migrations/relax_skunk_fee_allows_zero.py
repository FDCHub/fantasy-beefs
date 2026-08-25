"""FINAL POR migration — a Weekly Skunk Fee of 0 becomes admissible.

Final POR §9D makes Skunk Fees OPTIONAL. `ck_lsec_skunk_fee` on
`league_season_economy_config` forbade anything below $1, so the only way to
play without Skunk was to leave the economy unconfigured — which switches off
the whole configured economy, not just the Skunk.

    before   CHECK (skunk_fee_cents BETWEEN 100 AND 10000)
    after    CHECK (skunk_fee_cents BETWEEN 0   AND 10000)

── THIS ONLY EVER WIDENS ───────────────────────────────────────────────────

Every value the old constraint admitted, the new one admits. No existing row can
violate it, so there is no data to inspect, migrate or quarantine, and nothing
here reads or writes a single row. A frozen configuration keeps the fee it
froze; an unconfigured season stays unconfigured.

NO `NOT VALID` IS NEEDED, and that is a consequence of the ruleset gate rather
than luck: historical seasons are protected by `ruleset_version`, not by
constraint exemptions, so this constraint can be fully validated on every row on
both dialects. PostgreSQL's `NOT VALID` has no SQLite equivalent and would have
been a real parity gap had grandfathering depended on it.

── WHY THE TWO DIALECTS DIVERGE HERE ───────────────────────────────────────

PostgreSQL can DROP and ADD a named CHECK in place, transactionally.

SQLite cannot drop a table-level CHECK at all — `ALTER TABLE` offers no such
form — so the only way to change one is the documented rebuild: create the
replacement, copy every row, drop the original, rename. That is done inside one
transaction with foreign keys deferred, so a failure leaves the original table
untouched rather than half-copied.

Idempotent on both: a schema already carrying the widened constraint is observed
and left alone.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from db.schema import engine  # noqa: E402

TABLE = "league_season_economy_config"
CONSTRAINT = "ck_lsec_skunk_fee"
WIDENED = "skunk_fee_cents BETWEEN 0 AND 10000"

#: The replacement table, identical to the original in every respect except the
#: Skunk bound. Kept beside the original DDL in
#: `db/migrations/migrate_econcfg_f1_economy_config.py`, which a certification
#: case already holds in step with `db/schema.py`'s ORM model.
_SQLITE_REBUILD = f"""
CREATE TABLE {TABLE}__finalpor (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    league_id                       INTEGER NOT NULL REFERENCES leagues(id),
    season                          INTEGER NOT NULL,
    weekly_bet_minimum_cents        INTEGER NOT NULL,
    championship_contribution_cents INTEGER NOT NULL,
    skunk_fee_cents                 INTEGER NOT NULL,
    regular_season_week_count       INTEGER,
    active_team_count               INTEGER,
    start_week_used                 INTEGER,
    playoff_start_week_used         INTEGER,
    frozen_at                       TIMESTAMP,
    created_at                      TIMESTAMP NOT NULL,
    CONSTRAINT uq_lsec_league_season UNIQUE (league_id, season),
    CONSTRAINT ck_lsec_weekly_bet_minimum
        CHECK (weekly_bet_minimum_cents BETWEEN 100 AND 10000),
    CONSTRAINT ck_lsec_championship_contribution
        CHECK (championship_contribution_cents BETWEEN 100 AND 100000),
    CONSTRAINT {CONSTRAINT}
        CHECK ({WIDENED}),
    CONSTRAINT ck_lsec_regular_season_week_count
        CHECK (regular_season_week_count IS NULL OR regular_season_week_count > 0),
    CONSTRAINT ck_lsec_active_team_count
        CHECK (active_team_count IS NULL OR active_team_count > 0)
)
"""

_COLUMNS = (
    "id, league_id, season, weekly_bet_minimum_cents, "
    "championship_contribution_cents, skunk_fee_cents, "
    "regular_season_week_count, active_team_count, start_week_used, "
    "playoff_start_week_used, frozen_at, created_at"
)


def _already_widened(connection) -> bool:
    """Whether the live constraint already admits 0.

    ASKED OF THE SCHEMA, NOT OF A MIGRATION RECORD. A record is a claim; the
    point of checking here is to be idempotent against a database whose record
    and shape disagree — exactly the divergence `migrations.run.verify` exists
    to catch.
    """
    dialect = connection.dialect.name
    if dialect == "postgresql":
        found = connection.execute(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = :name"), {"name": CONSTRAINT}).scalar()
        return bool(found) and " 0 " in found.replace("(", " ").replace(")", " ")
    sql = connection.execute(text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": TABLE}).scalar() or ""
    return "BETWEEN 0 AND 10000" in sql


def upgrade() -> list[str]:
    dialect = engine.dialect.name

    with engine.begin() as connection:
        if TABLE not in set(inspect(connection).get_table_names()):
            # A database that never ran ECONCFG-F1 will build the widened
            # constraint from the ORM model when the table is first created.
            return [f"{TABLE} absent; nothing to relax"]

        if _already_widened(connection):
            return [f"{CONSTRAINT} already admits 0"]

        if dialect == "postgresql":
            connection.execute(text(
                f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CONSTRAINT}"))
            connection.execute(text(
                f"ALTER TABLE {TABLE} ADD CONSTRAINT {CONSTRAINT} "
                f"CHECK ({WIDENED})"))
            return [f"{CONSTRAINT} widened in place (PostgreSQL)"]

        # SQLite: rebuild-and-copy. One transaction; a failure rolls the whole
        # thing back and leaves the original table exactly as it was.
        connection.execute(text(f"DROP TABLE IF EXISTS {TABLE}__finalpor"))
        connection.execute(text(_SQLITE_REBUILD))
        connection.execute(text(
            f"INSERT INTO {TABLE}__finalpor ({_COLUMNS}) "
            f"SELECT {_COLUMNS} FROM {TABLE}"))
        connection.execute(text(f"DROP TABLE {TABLE}"))
        connection.execute(text(
            f"ALTER TABLE {TABLE}__finalpor RENAME TO {TABLE}"))
        return [f"{CONSTRAINT} widened by table rebuild (SQLite)"]


if __name__ == "__main__":
    for line in upgrade():
        print(f"  · {line}")
