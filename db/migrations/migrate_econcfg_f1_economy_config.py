#!/usr/bin/env python3
"""
migrate_econcfg_f1_economy_config.py — the league economy configuration
foundation.

ADDITIVE ONLY. One nullable column on `leagues` and one new table. No ALTER of
an existing column, no DROP, no UPDATE of existing data, no backfill.

    leagues.start_week             INTEGER NULL
    league_season_economy_config   (new table; draft when frozen_at IS NULL)

ONE COLUMN ON `leagues`, NOT FOUR. The commissioner's three inputs live on the
new season-scoped table rather than on the league. `leagues` is the most-locked
table in the system, SQLAlchemy emits every column of a locked entity in the
SELECT, and `pg_stat_activity.query` truncates at track_activity_query_size —
so columns here consume the budget the certified concurrency suites spend
proving which lock a blocked backend awaits. Three extra columns took that
SELECT from 761 to 1039 bytes and cut the lock clause off the observable text.
Season-scoped configuration belongs on a season-scoped table regardless.

WHAT IT MAKES POSSIBLE, AND WHAT IT DELIBERATELY DOES NOT DO.

It makes the season economy configurable and auditable: three commissioner
inputs, a week count derived from the connected league's own settings, and one
immutable row per league-season recording exactly what governed the season.

It does NOT change what any league is issued. `payments/economy_config.py`'s
fixed five-stop table remains the live issuance source. A row in
`league_season_economy_config` records what the economy IS; it does not decide
what is POSTED until a later, deliberate economic package moves that authority.
That separation is the whole design of this step, and it is certified rather
than promised.

── COMPATIBILITY (Mid-Season Maintainability POR) ───────────────────────────

    A league-season with NO ROW in the new table is UNCONFIGURED, and an
    unconfigured league behaves exactly as it did before this migration.

One rule, three populations:

  · every league and season activated BEFORE this migration — none is
    backfilled, none is migrated, none acquires a configuration it never chose;
  · a league that simply never configures one;
  · a league mid-setup that has not finished.

NO BACKFILL, AND THE REFUSAL IS DELIBERATE. A historical season's week count
could be reconstructed from today's provider boundaries. That reconstruction
would be TODAY'S answer wearing a historical timestamp, and it would be right
often enough to be trusted — so nothing is written for a season that did not
configure itself.

`leagues.start_week` gets no backfill. It is populated only by an actual
provider refresh through the same `_reconcile_boundary` discipline that governs
`playoff_start_week` and `season_final_week`: populate once, conflict on
contradiction, never silently overwrite. Inferring it — from 1, or from the
lowest matchup week on file — would freeze a guess as though it had been
measured, and the guess would decide how many Credits each GM is issued.

── ROLLBACK ─────────────────────────────────────────────────────────────────

Reverting the application leaves the new columns and table inert: pre-ECONCFG-F1
code never reads them, no money column depends on them, and the fixed-stop path
it does read is untouched. No Credits are stranded, because none was ever issued
from this configuration. That is what makes the change reversible in the
operational sense the POR asks for.

SAFE:
  - Additive only; idempotent (each object's existence is checked first);
  - one transaction — Postgres DDL is transactional, so a failure anywhere
    rolls the whole set back rather than leaving half a schema;
  - callable `upgrade(engine)` so a test drives the REAL migration rather than
    a copy of its DDL that could drift.

USAGE
    python db/migrations/migrate_econcfg_f1_economy_config.py
    # or, from a test:
    #   from db.migrations.migrate_econcfg_f1_economy_config import upgrade
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))

from sqlalchemy import inspect, text  # noqa: E402

TABLE = "league_season_economy_config"
LEAGUE_TABLE = "leagues"

#: The single additive nullable column on `leagues`. NULL is a governed state:
#: no start week means no derivable week count, so no economy may freeze.
LEAGUE_COLUMNS = (
    ("start_week", "INTEGER"),
)

# The DDL lives here ONCE and must stay in step with the ORM model in
# db/schema.py::LeagueSeasonEconomyConfig. A test asserts create_all() and this
# migration produce the same column set, so the two cannot drift silently.
_CREATE = f"""
CREATE TABLE {TABLE} (
    id                              SERIAL PRIMARY KEY,
    league_id                       INTEGER NOT NULL REFERENCES leagues(id),
    season                          INTEGER NOT NULL,
    weekly_bet_minimum_cents        INTEGER NOT NULL,
    championship_contribution_cents INTEGER NOT NULL,
    skunk_fee_cents                 INTEGER NOT NULL,
    regular_season_week_count       INTEGER,
    active_team_count               INTEGER,
    start_week_used                 INTEGER,
    playoff_start_week_used         INTEGER,
    frozen_at                       TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_lsec_league_season UNIQUE (league_id, season),
    CONSTRAINT ck_lsec_weekly_bet_minimum
        CHECK (weekly_bet_minimum_cents BETWEEN 100 AND 10000),
    CONSTRAINT ck_lsec_championship_contribution
        CHECK (championship_contribution_cents BETWEEN 100 AND 100000),
    CONSTRAINT ck_lsec_skunk_fee
        CHECK (skunk_fee_cents BETWEEN 100 AND 10000),
    CONSTRAINT ck_lsec_regular_season_week_count
        CHECK (regular_season_week_count IS NULL OR regular_season_week_count > 0),
    CONSTRAINT ck_lsec_active_team_count
        CHECK (active_team_count IS NULL OR active_team_count > 0)
)
"""


def table_exists(engine) -> bool:
    return TABLE in set(inspect(engine).get_table_names())


def missing_league_columns(engine) -> list[tuple[str, str]]:
    present = {c["name"] for c in inspect(engine).get_columns(LEAGUE_TABLE)}
    return [(n, t) for n, t in LEAGUE_COLUMNS if n not in present]


def upgrade(engine) -> str:
    """Add the columns and the table if absent. Idempotent."""
    missing = missing_league_columns(engine)
    need_table = not table_exists(engine)
    if not missing and not need_table:
        return "economy configuration foundation already present — nothing to do"

    with engine.begin() as conn:
        for name, sqltype in missing:
            conn.execute(text(
                f"ALTER TABLE {LEAGUE_TABLE} ADD COLUMN {name} {sqltype}"))
        if need_table:
            conn.execute(text(_CREATE))

    added = ", ".join(n for n, _ in missing) or "no columns"
    made = f" and created {TABLE}" if need_table else ""
    return f"added {added}{made} (additive, no backfill)"


def migrate() -> str:
    from db.schema import engine

    return upgrade(engine)


if __name__ == "__main__":
    print(migrate())
