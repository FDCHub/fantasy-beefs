#!/usr/bin/env python3
"""
migrate_wp1b_pool_subject_manifest.py — the frozen postseason subject universe.

ONE ADDITIVE TABLE: `pool_week_subject_manifest`. Nothing else is created,
altered, dropped, backfilled or rewritten.

WHAT IT MAKES TRUE (WP1B §3, owner ruling):

    The field a member sees and picks from must be the same field settlement
    later evaluates.

Before this table the Pool subject universe was recomputed on every read. In the
regular season that is harmless — it is "every team in the league", which does
not move between Tuesday and Sunday. In the postseason it is derived from
provider championship state, which does: a mid-week refresh that reclassified a
bracket would change the field a GM already picked from, change `considered`
underneath the census, and could flip a settleable Pool to INCOMPLETE_FIELD
after the fact.

── COMPATIBILITY IS THE POINT, NOT AN AFTERTHOUGHT (WP1B §4, §18) ────────────

This is the first package under the Mid-Season Maintainability POR, so the
compatibility rule is stated here rather than left to be inferred:

    A league-week with NO ROWS in this table is UNMANIFESTED, and an
    unmanifested week uses the derived universe — the exact pre-WP1B behaviour.

That single rule covers three populations at once, which is why it was chosen
over a version column or a backfill:

  · every REGULAR-season week, now and forever — the regular season is never
    manifested, so its behaviour is unchanged by construction rather than by a
    branch someone has to maintain;
  · every occurrence drawn BEFORE this migration ran, including settled ones —
    they keep resolving exactly as they did, and their historical claims keep
    validating against the same set that accepted them;
  · a postseason week drawn on an older application build.

ABSENCE THEREFORE MEANS "NO FREEZE APPLIES", NEVER "THE FIELD IS EMPTY". The
two would be indistinguishable if the writer could persist an empty universe,
so it cannot: `betting.pool_postseason.resolve_universe` refuses a zero-team or
zero-matchup field before anything is written.

NO BACKFILL, AND THE REFUSAL IS DELIBERATE. A historical postseason week could
in principle have its universe reconstructed from today's code and today's
provider state. That is precisely what WP1B §4 forbids — "do not recompute old
subject universes using current code/provider state" — because the
reconstruction would be TODAY'S answer wearing a historical timestamp, and it
would be right often enough to be trusted.

ROLLBACK. Dropping this table returns every league-week to the unmanifested
path, which is the derived universe; no other table references it and no money
column depends on it. An application rollback to a pre-WP1B build simply stops
reading it, and the rows sit inert rather than corrupting anything. That is what
makes the change reversible in the operational sense the POR asks for.

SAFE:
  - Additive only. One new table; no ALTER, no DROP, no UPDATE of existing data.
  - Idempotent. Existence is checked before CREATE, so a re-run is a clean
    no-op and a partially applied state can be completed.
  - One transaction (engine.begin()); Postgres DDL is transactional.
  - Callable entry point `upgrade(engine)` so a test drives the REAL migration
    rather than a copy of its DDL that could drift.

USAGE
    python db/migrations/migrate_wp1b_pool_subject_manifest.py
    # or, from a test:  from db.migrations.migrate_wp1b_pool_subject_manifest import upgrade
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))

from sqlalchemy import inspect, text  # noqa: E402

TABLE = "pool_week_subject_manifest"

# The DDL lives here ONCE and must stay in step with the ORM model in
# db/schema.py::PoolWeekSubjectManifest. A test asserts create_all() and this
# migration produce the same column set, so the two cannot drift silently.
_CREATE = f"""
CREATE TABLE {TABLE} (
    id             SERIAL PRIMARY KEY,
    league_id      INTEGER NOT NULL REFERENCES leagues(id),
    season         INTEGER NOT NULL,
    week           INTEGER NOT NULL,
    scope          VARCHAR NOT NULL,
    subject_id     INTEGER NOT NULL,
    rotation_cycle INTEGER,
    frozen_at      TIMESTAMPTZ,
    CONSTRAINT ck_pool_week_subject_manifest_scope
        CHECK (scope IN ('TEAM','MATCHUP')),
    CONSTRAINT uq_pool_week_subject_manifest_subject
        UNIQUE (league_id, season, week, scope, subject_id)
)
"""

_CREATE_INDEX = (
    f"CREATE INDEX IF NOT EXISTS ix_pool_week_subject_manifest_lookup "
    f"ON {TABLE} (league_id, season, week, scope)"
)


def table_exists(engine) -> bool:
    return TABLE in set(inspect(engine).get_table_names())


def upgrade(engine) -> str:
    """Create the manifest table if absent. Idempotent."""
    if table_exists(engine):
        return f"{TABLE} already present — nothing to do"
    with engine.begin() as conn:
        conn.execute(text(_CREATE))
        conn.execute(text(_CREATE_INDEX))
    return f"created {TABLE} (additive, no backfill)"


def migrate() -> str:
    from db.schema import engine

    return upgrade(engine)


if __name__ == "__main__":
    print(migrate())
