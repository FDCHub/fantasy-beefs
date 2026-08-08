#!/usr/bin/env python3
"""
migrate_s4_pool_rollover_money.py — legacy Worst Beat carry, MONEY PATH.

Product authority : spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_3.md §1.1, §5
Implementation    : spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_3.md §D
Owner ruling      : 2026-08-08, legacy Worst Beat rollover disposition

THE AMBIGUITY THIS RESOLVES. Scope §D specifies "migration of live
worst_beat_rollover_cents into pool_instance.rollover_cents", written when Worst
Beat was still a Pool. Revision 1.3 RETIRED it, and `pool_instance.rollover_cents`
is a per-definition carry that POR §5 requires stay tied to its own definition —
so there was no Rev1.3 definition the balance could legally attach to, and no
ruling on where it went instead.

THE OWNER RULING, 2026-08-08, applied verbatim below:

    Worst Beat is retired and MUST NOT be revived or mapped to another Rev1.3
    Pool definition. A live legacy balance migrates in full to
    championship:{league_id}.

Each numbered rule and where it is enforced:

  1. never attached to an active definition — this migration writes no
     pool_instance row and touches no definition_key. The only tables it writes
     are pool_pots (zeroing the legacy column) and the audit carrier.
  2. exact integer cents, debit legacy / credit championship — ONE balanced
     two-leg posting per league, amounts read as integers and never converted
     through a float.
  3. the column is zeroed in the SAME committed transaction as the transfer —
     one `engine.begin()` block per league covering posting, zeroing and audit
     row together.
  4. deterministic idempotency key under a database constraint —
     `s4p1-legacy-worst-beat:{league_id}`, derived from the league id alone.
     Never a timestamp, never a random value, never a retry counter.
  5. a retry cannot double-credit — the second execution collides on
     `uq_pool_legacy_rollover_migration_key` inside that same transaction, so
     the posting rolls back with it.
  6. failure before commit leaves both sides unchanged — nothing is committed
     piecewise, and the ledger's own funded-balance guard rejects the posting
     before any leg is written if the pool account cannot cover it.
  7. an immutable audit record — pool_legacy_rollover_migration carries league,
     source field, contributing weeks, amount, destination account, posting id
     and the idempotency identity. Nothing updates a row after insert.
  8. a zero balance is a verified no-op — no posting, no audit row, no writes.
  9. no successor Worst Beat occurrence is created — see rule 1.
 10. no other definition or rollover lineage is altered — no pool_instance,
     pool_definition or pool_rotation_cycle row is read for write or modified.

WHY THE DEBIT COMES FROM pool:{league_id}. The legacy engine never moved the
carry out of that account; `worst_beat_rollover_cents` is a COLUMN recording how
much of the league's pool balance is spoken for, not a separate account. So the
balance being retired is already sitting in `pool:{league_id}`, and debiting it
there is what makes the transfer a real movement rather than an invented credit.

A SIDE EFFECT WORTH NAMING: this RESTORES the Rev1.3 conservation invariant.
`betting.pool_settlement.assert_pool_conservation` expects
`balance_of(pool:{league_id})` to equal the sum of unsettled pots plus live
carries. Legacy cents sitting in that account belong to no pool_instance, so
before this migration the invariant is short by exactly the legacy carry. After
it, the account reconciles.

RUN THIS BEFORE THE FIRST Rev1.3 WEEKLY COLLECTION for an affected league.
Collecting first would mix Rev1.3 pots into the same account, which does not
corrupt anything — the debit amount is read from the legacy column, not from the
balance — but it makes the intermediate conservation reading harder to explain.

USAGE:
  python db/migrations/migrate_s4_pool_rollover_money.py            # migrate
  python db/migrations/migrate_s4_pool_rollover_money.py --measure  # read-only
  # or, from a test:  from db.migrations.migrate_s4_pool_rollover_money import upgrade
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import bindparam, text

#: The legacy field being retired, recorded verbatim on every audit row.
SOURCE_FIELD = "pool_pots.worst_beat_rollover_cents"

#: The ledger door for this one-time movement. Distinct from every Pool door so
#: the entries are separable in the ledger forever.
DOOR_LEGACY_WORST_BEAT_MIGRATION = "pool_legacy_worst_beat_migration"

#: Deterministic idempotency key prefix. Rule 4: derived from the event itself.
MIGRATION_KEY_PREFIX = "s4p1-legacy-worst-beat"


def migration_key_for(league_id: int) -> str:
    """The key for one league's migration. A pure function of the league id.

    One league can be migrated at most ONCE, ever. Not per week and not per run
    — the whole legacy carry moves in a single event, so a single key covers it.
    """
    return f"{MIGRATION_KEY_PREFIX}:{league_id}"


class LegacyRolloverMigrationError(RuntimeError):
    """The migration refused. Nothing was moved."""


# Introspection goes through SQLAlchemy's inspector rather than a raw
# information_schema query. Both answer the same question on Postgres, but the
# inspector also answers it on SQLite, which keeps this file's guards and its
# UPDATE statement exercisable outside a Postgres session. The DDL-heavy
# companion migration stays information_schema-based because its ALTERs are
# Postgres-only anyway.
def _column_exists(engine, table: str, column: str) -> bool:
    from sqlalchemy import inspect

    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _table_exists(engine, table: str) -> bool:
    from sqlalchemy import inspect

    return table in inspect(engine).get_table_names()


def measure(engine) -> dict[int, dict]:
    """Every live legacy carry, aggregated per league. READ-ONLY.

    Returns {league_id: {"amount_cents": int, "weeks": [int, ...]}}. Safe to run
    against production at any time; opens no write transaction."""
    if not _column_exists(engine, "pool_pots", "worst_beat_rollover_cents"):
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT league_id, week, worst_beat_rollover_cents
              FROM pool_pots
             WHERE worst_beat_rollover_cents IS NOT NULL
               AND worst_beat_rollover_cents > 0
             ORDER BY league_id, week
        """)).fetchall()

    out: dict[int, dict] = {}
    for league_id, week, cents in rows:
        entry = out.setdefault(int(league_id),
                               {"amount_cents": 0, "weeks": []})
        entry["amount_cents"] += int(cents)
        entry["weeks"].append(int(week))
    return out


def _migrate_one_league(engine, league_id: int, amount_cents: int,
                        weeks: list[int]) -> bool:
    """Move one league's legacy carry. Returns True if this run performed it.

    ONE TRANSACTION covering all three effects — the balanced posting, the
    zeroing of the legacy column, and the immutable audit row. Rule 3 and rule 6
    are the same property viewed from either side of a crash: nothing here is
    committed piecewise, so a failure at any point leaves the legacy balance
    intact and Championship untouched.
    """
    from ledger.ledger import post as ledger_post
    from db.schema import SessionLocal

    key = migration_key_for(league_id)
    destination = f"championship:{league_id}"

    with SessionLocal() as db:
        # Rule 2 — exact integer cents, one balanced two-leg posting. The
        # ledger's funded-balance guard refuses this outright if
        # pool:{league_id} cannot cover the debit, which satisfies rule 6
        # without this function testing the balance itself.
        posting_id = ledger_post(
            [(f"pool:{league_id}", -amount_cents),
             (destination, amount_cents)],
            door=DOOR_LEGACY_WORST_BEAT_MIGRATION, session=db,
        )

        # Rules 4, 5, 7 — the audit row is INSERT-ONLY and carries the real
        # posting id, so it never describes a movement that did not happen and
        # nothing ever updates it afterwards.
        #
        # ON CONFLICT DO NOTHING is the idempotency claim. Posting before
        # claiming is safe precisely because both are in ONE transaction: a
        # replay or a concurrent run gets no RETURNING row, rolls back, and its
        # posting is discarded with it. Championship cannot be credited twice.
        claimed = db.execute(text("""
            INSERT INTO pool_legacy_rollover_migration
                (migration_key, league_id, source_field, source_weeks,
                 amount_cents, destination_account, posting_id, migrated_at)
            VALUES (:key, :league_id, :source_field, :weeks, :amount,
                    :destination, :posting_id, :migrated_at)
            ON CONFLICT (migration_key) DO NOTHING
            RETURNING id
        """), {
            "key": key, "league_id": league_id, "source_field": SOURCE_FIELD,
            "weeks": json.dumps(weeks), "amount": amount_cents,
            "destination": destination, "posting_id": str(posting_id),
            "migrated_at": datetime.now(timezone.utc),
        }).fetchone()

        if claimed is None:
            db.rollback()
            return False

        # Rule 3 — zeroed in the SAME transaction as the transfer. Scoped to the
        # weeks that contributed, so a row that gained a carry after `measure`
        # ran is not silently wiped along with them.
        #
        # An expanding bindparam rather than Postgres' `= ANY(:weeks)`: it
        # renders correctly on both backends, which keeps this statement
        # exercisable outside a Postgres session without a dialect branch.
        db.execute(
            text("""
                UPDATE pool_pots
                   SET worst_beat_rollover_cents = 0
                 WHERE league_id = :league_id
                   AND week IN :weeks
            """).bindparams(bindparam("weeks", expanding=True)),
            {"league_id": league_id, "weeks": weeks},
        )

        db.commit()
    return True


def upgrade(engine, *, dry_run: bool = False) -> dict:
    """Retire every live legacy Worst Beat carry to championship:{league_id}.

    Rule 8 — with no live balance this is a verified no-op: no posting, no audit
    row, no writes of any kind.
    """
    if not _table_exists(engine, "pool_legacy_rollover_migration"):
        raise LegacyRolloverMigrationError(
            "pool_legacy_rollover_migration is absent — run "
            "db/migrations/migrate_s4_common_pool_engine.py first. The audit "
            "carrier and the idempotency constraint are that migration's "
            "schema work, and rule 7 has nowhere to write without them."
        )

    carries = measure(engine)
    if not carries:
        print("  live worst_beat_rollover_cents rows : 0")
        print("  nothing to migrate. Every cent preserved; none moved.")
        print("\n  MIGRATION COMPLETE (verified no-op).")
        return {"leagues": 0, "migrated_cents": 0, "skipped": 0}

    total = sum(c["amount_cents"] for c in carries.values())
    print(f"  leagues with a live legacy carry : {len(carries)}")
    for league_id, entry in sorted(carries.items()):
        print(f"       league {league_id:<6} {entry['amount_cents']:>10} cents "
              f"from weeks {entry['weeks']}")
    print(f"  total : {total} cents -> championship:{{league_id}}")

    if dry_run:
        print("\n  --measure only. Nothing was moved.")
        return {"leagues": len(carries), "migrated_cents": total, "skipped": 0}

    migrated = skipped = moved_cents = 0
    for league_id, entry in sorted(carries.items()):
        if _migrate_one_league(engine, league_id, entry["amount_cents"],
                               entry["weeks"]):
            migrated += 1
            moved_cents += entry["amount_cents"]
            print(f"  league {league_id}: {entry['amount_cents']} cents "
                  f"-> championship:{league_id}")
        else:
            skipped += 1
            print(f"  league {league_id}: already migrated under "
                  f"{migration_key_for(league_id)!r} — no second credit")

    print(f"\n  MIGRATION COMPLETE. {migrated} migrated, {skipped} already "
          f"done, {moved_cents} cents moved.")
    return {"leagues": len(carries), "migrated_cents": moved_cents,
            "skipped": skipped}


if __name__ == "__main__":
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    print("\nmigrate_s4_pool_rollover_money.py  --  legacy Worst Beat carry\n")

    from db.schema import engine  # noqa: E402  (deferred: __main__ only)

    db_url = str(engine.url)
    print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")
    try:
        upgrade(engine, dry_run="--measure" in sys.argv)
    except Exception as exc:  # noqa: BLE001
        print(f"\n!! ERROR: {exc}")
        sys.exit(1)