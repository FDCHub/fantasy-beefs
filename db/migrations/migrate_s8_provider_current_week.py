#!/usr/bin/env python3
"""
migrate_s8_provider_current_week.py — record the provider's current week.

ONE ADDITIVE, NULLABLE COLUMN: `leagues.provider_current_week`.

WHAT IT FIXES. `ProviderLeague.current_week` has been parsed out of the Yahoo
payload since Sprint 6 and carried through the DTO, but it was consumed for
exactly one purpose — the §6 ingestion horizon in providers/yahoo/persist.py —
and then discarded. Because nothing stored it, no read route could serve it, and
every production surface that needed "which fantasy week is it" fell back to a
hard-coded 5 in JavaScript.

The source was never missing. Only the storage was.

NULLABLE, AND NULL MEANS SOMETHING. A league with no provider refresh has no
stated current week, and the read models render that as unresolved. A default
here — 1, or 5, or anything — would reintroduce the hard-coded week wearing a
column name, and would be indistinguishable from a real measurement.

NOT A BOUNDARY FIELD. `season_final_week` and `playoff_start_week` go through
`_reconcile_boundary`, which treats a provider contradiction as a CONFLICT
because economic decisions have been frozen against them. The current week is
the opposite kind of fact: it is SUPPOSED to advance, and a later value is the
normal case rather than a disagreement. It is therefore written last-writer-wins
and raises no conflict.

NO BACKFILL. Nothing here infers a current week from persisted matchups. The
maximum ingested week is bounded by the horizon and would often equal the real
current week, which is exactly what makes inferring it dangerous: it would be
right often enough to be trusted and silently stale otherwise. The column is
populated only by an actual provider refresh, which is where the provider states
it.

Idempotent: re-running is a no-op.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))

from sqlalchemy import inspect, text  # noqa: E402

from db.schema import engine  # noqa: E402

COLUMN = "provider_current_week"
TABLE = "leagues"


def column_exists() -> bool:
    return COLUMN in {c["name"] for c in inspect(engine).get_columns(TABLE)}


def migrate() -> str:
    if column_exists():
        return f"{TABLE}.{COLUMN} already present — nothing to do"
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} INTEGER"))
    return f"added {TABLE}.{COLUMN} (nullable, no backfill)"


if __name__ == "__main__":
    print(migrate())
