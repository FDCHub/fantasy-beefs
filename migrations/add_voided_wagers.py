"""FINAL POR migration — the voided-wager record (WP-13).

Final POR §7 gives an ACCEPTED wager a void path: the stake returns to the GM's
Wallet, the accepted action goes on satisfying that week's Weekly Minimum, and
the Minimum itself is never restored. Nothing in the schema could record that a
void happened.

    CREATE TABLE voided_wagers (
        id, bet_id UNIQUE, challenge_id, team_id, league_id, season, week,
        refunded_cents, reason, posting_id, created_at
    )

── WHY A TABLE AND NOT A `Bet.status` VALUE ────────────────────────────────

`ck_bet_status` admits `pending / won / lost / push`, and a void is none of
them. It is emphatically NOT `push`: a push is a RESULT — the contest happened
and separated nobody — while a void says no contest occurred at all. §7 gives
the two different consequences, so collapsing them would make the difference
unrecoverable. Widening that CHECK would also have required rebuilding `bets` on
SQLite, which is a large blast radius for a fact that belongs beside the refund
it records rather than inside the wager it cancels.

── ADDITIVE, AND UNBACKFILLED BY CONSTRUCTION ──────────────────────────────

A new table. No existing row is read, rewritten or reinterpreted; no `Bet`, no
`ledger_entries` row and no `economy_event` row changes. An empty table is the
true statement about every league that has never voided a wager, which is all of
them at the moment this runs.

── ONE ROW PER BET, ENFORCED BY THE DATABASE ───────────────────────────────

`uq_voided_wager_bet` is what makes a second void of the same wager impossible
to record, which is in turn what makes the refund exactly-once at the storage
layer rather than only in the code path that writes it.

Idempotent: a schema already carrying the table is observed and left alone.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from db.schema import engine  # noqa: E402

TABLE = "voided_wagers"


def upgrade() -> list[str]:
    dialect = engine.dialect.name
    pk = ("SERIAL PRIMARY KEY" if dialect == "postgresql"
          else "INTEGER PRIMARY KEY AUTOINCREMENT")
    timestamp_type = ("TIMESTAMP WITH TIME ZONE" if dialect == "postgresql"
                      else "TIMESTAMP")
    uuid_type = "UUID" if dialect == "postgresql" else "CHAR(32)"

    with engine.begin() as connection:
        if TABLE in set(inspect(connection).get_table_names()):
            return [f"{TABLE} already exists"]
        connection.execute(text(f"""
            CREATE TABLE {TABLE} (
                id             {pk},
                bet_id         INTEGER NOT NULL REFERENCES bets (id),
                challenge_id   INTEGER,
                team_id        INTEGER NOT NULL REFERENCES teams (id),
                league_id      INTEGER NOT NULL,
                season         INTEGER NOT NULL,
                week           INTEGER,
                refunded_cents INTEGER NOT NULL,
                reason         VARCHAR NOT NULL,
                posting_id     {uuid_type},
                created_at     {timestamp_type} NOT NULL,
                CONSTRAINT uq_voided_wager_bet UNIQUE (bet_id),
                CONSTRAINT ck_voided_wager_refund CHECK (refunded_cents >= 0)
            )
        """))
    return [f"created {TABLE}"]


if __name__ == "__main__":
    for line in upgrade():
        print("  - " + line)
