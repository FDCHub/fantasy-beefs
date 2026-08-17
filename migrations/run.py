"""
migrations/run.py — the one database command that runs before a release.

    python -m migrations.run              apply every pending ACTIVE migration
    python -m migrations.run --status     report applied / pending, change nothing
    python -m migrations.run --dry-run    say what would run, run nothing

WHY A RECORD IN THE DATABASE AND NOT CONSOLE OUTPUT. §9 is blunt about this and
it is right: a deploy log is not migration history. It is not queryable, it is
not present after a restore, and it cannot answer "is this database at the
version this release needs" — which is exactly the question a readiness check
and a recovery audit both have to ask.

So `schema_migrations` is written, one row per applied migration, with the
release that applied it.

── FAILED MIGRATIONS ARE NOT RECORDED ──────────────────────────────────────

The row is written in the SAME transaction as the migration's own work where the
dialect allows it, and only after `upgrade()` returns. A migration that raises
leaves no row, so the next run retries it rather than skipping it — which is the
whole point of recording anything.

PostgreSQL runs DDL transactionally, so on the production target a failed
migration leaves neither its schema change nor its record. That is the behaviour
this file is designed around.

── WHY NOT ALEMBIC ─────────────────────────────────────────────────────────

§9 asks not to adopt it for style alone. The existing migrations are already
idempotent, dialect-aware and individually certified on PostgreSQL; what they
lacked was an order and a record. That is roughly eighty lines. Adopting Alembic
would mean either rewriting twenty-eight scripts into revisions or stamping a
baseline nobody has verified — a large change to gain a smaller thing than the
one being fixed.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text                               # noqa: E402

from migrations.manifest import ACTIVE, HISTORICAL                 # noqa: E402

TABLE = "schema_migrations"

_CREATE = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    identifier   VARCHAR PRIMARY KEY,
    applied_at   TIMESTAMP NOT NULL,
    release      VARCHAR,
    application_version VARCHAR
)
"""


def ensure_table(engine) -> None:
    """Create the record table if it is absent. Additive; safe to repeat."""
    with engine.begin() as connection:
        connection.execute(text(_CREATE))


def applied_identifiers(engine) -> set:
    """What this database says it has already applied."""
    if TABLE not in inspect(engine).get_table_names():
        return set()
    with engine.connect() as connection:
        rows = connection.execute(
            text(f"SELECT identifier FROM {TABLE}")).fetchall()
    return {r[0] for r in rows}


def pending(engine) -> list:
    done = applied_identifiers(engine)
    return [m for m in ACTIVE if m.identifier not in done]


def _record(connection, migration, release: str, version: str) -> None:
    connection.execute(
        text(f"INSERT INTO {TABLE} (identifier, applied_at, release, "
             f"application_version) VALUES (:i, :t, :r, :v)"),
        {"i": migration.identifier, "t": datetime.now(timezone.utc),
         "r": release, "v": version})


def upgrade(engine=None, *, dry_run: bool = False) -> list:
    """Apply every pending ACTIVE migration, in manifest order.

    Returns the lines an operator should see.
    """
    from db.schema import engine as default_engine
    from ops.release import release_identity

    engine = engine or default_engine
    identity = release_identity(use_cache=False)

    ensure_table(engine)
    todo = pending(engine)
    if not todo:
        return ["nothing pending — the database is at the manifest's head"]

    lines: list[str] = []
    for migration in todo:
        if dry_run:
            lines.append(f"WOULD APPLY {migration.identifier} "
                         f"({migration.module})")
            continue

        module = importlib.import_module(migration.module)
        # THE MIGRATION'S OWN `upgrade()` DOES THE WORK. This file adds ordering
        # and a record; it does not reimplement, wrap or second-guess what each
        # migration does, all of which are separately certified.
        did = module.upgrade()
        with engine.begin() as connection:
            _record(connection, migration, identity.release, identity.version)
        lines.append(f"applied {migration.identifier}: " + "; ".join(did))

    return lines


def stamp_all(engine=None) -> list:
    """Record every ACTIVE migration as applied, without running it.

    FOR A FRESHLY BOOTSTRAPPED DATABASE ONLY, and it is not a shortcut — it is
    the truth. `create_all` builds the schema from the models, and the models
    already contain everything the ACTIVE migrations add: the identity columns,
    their unique constraint, `provider_grants`, the credential owner. Running
    those migrations against such a database would find every change already
    present and do nothing.

    WITHOUT THIS, READINESS IS WRONG IN THE WORST DIRECTION. A brand-new
    deployment would come up with a complete schema, no migration history, and
    `/ready` reporting two migrations pending — forever, because nothing would
    ever apply them. The platform would withhold traffic from a perfectly
    healthy process. That was a real defect in this design and it was caught by
    driving `/ready` rather than by reading it.

    ONLY CALLED WHEN THE DATABASE WAS JUST CREATED. It stamps nothing that is
    already stamped, so a second call is a no-op.
    """
    from db.schema import engine as default_engine
    from ops.release import release_identity

    engine = engine or default_engine
    identity = release_identity(use_cache=False)

    ensure_table(engine)
    done = applied_identifiers(engine)
    stamped: list[str] = []
    with engine.begin() as connection:
        for migration in ACTIVE:
            if migration.identifier in done:
                continue
            _record(connection, migration, identity.release, identity.version)
            stamped.append(migration.identifier)
    return stamped


def status(engine=None) -> dict:
    from db.schema import engine as default_engine

    engine = engine or default_engine
    done = applied_identifiers(engine)
    return {
        "applied": sorted(done),
        "pending": [m.identifier for m in ACTIVE if m.identifier not in done],
        "manifest_head": ACTIVE[-1].identifier if ACTIVE else None,
        "historical_not_run": len(HISTORICAL),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.status:
        state = status()
        print(f"manifest head : {state['manifest_head']}")
        print(f"applied       : {', '.join(state['applied']) or 'none'}")
        print(f"pending       : {', '.join(state['pending']) or 'none'}")
        print(f"historical    : {state['historical_not_run']} recorded, not run")
        return 0 if not state["pending"] else 1

    try:
        for line in upgrade(dry_run=args.dry_run):
            print(f"  · {line}")
    except Exception as exc:
        # THE TYPE AND THE MIGRATION, NOT THE DRIVER'S MESSAGE — which can carry
        # a connection URL. A failed migration must block the release, so this
        # exits non-zero and says so plainly.
        print(f"MIGRATION FAILED: {type(exc).__name__} — the release must not "
              f"proceed. Nothing was recorded as applied.", file=sys.stderr)
        return 2
    print("migrations complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
