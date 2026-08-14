#!/usr/bin/env python3
"""
scripts/bootstrap_pool_catalog.py

DEPLOYMENT / DATABASE INITIALIZATION. Ensures the canonical Rev1.3 Pool catalog
exists as `pool_definition` rows. This is application configuration, not league
gameplay: a commissioner should never have to install FantasyStakes' own Pool
definitions, and nothing here is league-scoped or league-aware.

WHY A SCRIPT RATHER THAN STARTUP SEEDING. `api/main.py`'s startup hook does
exactly one thing — `Base.metadata.create_all(engine)` — and every other data-
bearing operation in this repository is an explicit out-of-band script
(`db/migrations/*`, `scripts/bootstrap_league_commissioner.py`, `seed_*.py`).
Hidden startup mutation would also mean every web dyno racing to upsert 90-odd
governed rows on boot. The established convention is an explicit operation, so
this follows it.

NOTHING IS REIMPLEMENTED. The upsert is `betting.pool_catalog.seed_definitions`,
the certified Scope §I step 8 seeder, called unchanged. This module supplies a
transaction, a commit and an audit line. It defines no Pool, changes no rotation
rule and alters no catalog semantics.

IDEMPOTENT BY THE SEEDER'S OWN DESIGN. `seed_definitions` upserts on the
immutable `key`, so re-running updates governed columns in place rather than
inserting duplicates, and existing `pool_instance` rows keep their foreign key.
A catalog revision ships as a re-run of this script. Running it twice in a row
is a no-op apart from the reported `updated` count.

WHAT IT WILL NOT DO. It never deletes a definition and never touches league
runtime state — no pots, no instances, no claims, no ledger rows. A retired
catalog number is refused independently by `ck_pool_definition_retired_numbers`
on the table itself, so a bypass of this script still cannot resurrect one.

USAGE
    python scripts/bootstrap_pool_catalog.py            # seed / re-seed
    python scripts/bootstrap_pool_catalog.py --check    # report drift, write nothing

`--check` exits 1 when the database is missing definitions the catalog carries
OR when a seeded row's governed eligibility values disagree with the artifact,
so a deploy pipeline can gate on it without granting the step write access.

WP1B EXTENDED `--check` FROM PRESENCE TO CURRENCY. It previously compared only
the set of KEYS, which answers "has this ever been seeded" — a question that
stops being interesting after the first deploy. A catalog revision that changes
VALUES on rows which all already exist would have reported OK. WP1B is exactly
that shape of revision: it resolves `postseason_eligible` on all 80 existing
rows and adds none, so under the old check a stale database would have passed
the gate and then drawn an empty postseason candidate set.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


#: Governed columns `--check` compares by VALUE. Deliberately the decision-
#: bearing ones — what a definition is eligible for and whether it may run —
#: rather than every column: display text drifting is cosmetic, while an
#: eligibility flag drifting silently changes which Pools a league can draw.
_DRIFT_FIELDS = (
    "regular_season_eligible",
    "postseason_eligible",
    "rollover_eligible",
    "definition_runtime_eligible",
    "dependency_state",
    "scope",
    "evaluator_family",
)


def _value_drift(db, catalog) -> list[tuple[str, str, object, object]]:
    """(key, field, catalog_value, db_value) for every governed mismatch.

    A pure read — it reports, it never repairs, so a deploy pipeline can gate on
    `--check` without holding write access."""
    from db.schema import PoolDefinition

    rows = {r.key: r for r in db.query(PoolDefinition).all()}
    out: list[tuple[str, str, object, object]] = []
    for spec in catalog.definitions:
        row = rows.get(spec.key)
        if row is None:
            continue                      # already reported as missing
        for field in _DRIFT_FIELDS:
            want = getattr(spec, field)
            got = getattr(row, field, None)
            if want != got:
                out.append((spec.key, field, want, got))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap the canonical governed Pool catalog.")
    parser.add_argument("--check", action="store_true",
                        help="Report drift and exit non-zero; write nothing.")
    args = parser.parse_args(argv)

    from betting.pool_catalog import (
        CATALOG_PATH, VOCABULARY_PATH, load_catalog, seed_definitions,
    )
    from db.schema import PoolDefinition, SessionLocal

    catalog = load_catalog()

    print("Governed Pool catalog bootstrap")
    print(f"  catalog    : {CATALOG_PATH}")
    print(f"  vocabulary : {VOCABULARY_PATH}")
    print(f"  definitions: {len(catalog.definitions)}")

    with SessionLocal() as db:
        present = {row.key for row in db.query(PoolDefinition.key).all()}
        missing = [s.key for s in catalog.definitions if s.key not in present]

        if args.check:
            # VALUE DRIFT IS DRIFT TOO, and it is the kind a launch actually
            # hits. `--check` originally reported only MISSING keys, which
            # answers "has the catalog ever been seeded" — a question that stops
            # being interesting after the first deploy. A catalog REVISION
            # changes values on rows that are all already present, so a
            # key-only check reports OK on a database that is materially stale.
            #
            # WP1B is the first revision to prove that: it flips
            # `postseason_eligible` from null to an explicit boolean on all 80
            # rows and adds no row at all. Under the old check every one of
            # those databases would have reported OK while drawing an empty
            # postseason candidate set.
            stale = _value_drift(db, catalog)

            print(f"  in database: {len(present)}")
            print(f"  missing    : {len(missing)}")
            print(f"  stale      : {len(stale)}")
            if missing or stale:
                for key in missing[:10]:
                    print(f"    - missing {key}")
                for key, field, want, got in stale[:10]:
                    print(f"    ~ {key}.{field}: db={got!r} catalog={want!r}")
                extra = max(0, len(missing) - 10) + max(0, len(stale) - 10)
                if extra:
                    print(f"    ... and {extra} more")
                print("\nDRIFT — run without --check to seed.")
                return 1
            print("\nOK — every catalog definition is present and current.")
            return 0

        result = seed_definitions(db, catalog)
        db.commit()

    print(f"  inserted   : {result['inserted']}")
    print(f"  updated    : {result['updated']}")
    print(f"  total      : {result['total']}")
    print("\nOK — canonical Pool catalog is present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
