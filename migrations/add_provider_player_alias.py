"""WP1 migration — the cross-provider player identity map.

Yahoo supplies the roster. BALLDONTLIE is about to supply projections and
factual stat lines. Neither provider has ever heard of the other's identifiers,
and nothing in the schema could say that Yahoo's `461.p.31883` and
BALLDONTLIE's player 882 are one man.

    CREATE TABLE provider_player_alias (
        id, provider, provider_player_key, player_id -> players.id,
        provider_position, provider_nfl_team, status, method,
        manual_override, created_at, updated_at
    )

── WHY AN ALIAS TABLE AND NOT A SECOND `players` ROW ───────────────────────

`rosters`, `projections`, `bets`, `beef_starters`, `beef_proposal_starters` and
`pool_bet_picks` all carry a foreign key to `players.id`. That column already is
the canonical FantasyStakes player identity in the only sense that matters — it
is what the economic record was written against. Inserting a BALLDONTLIE player
as its own `players` row would create a SECOND identity for one human being, and
every projection hung off it would describe a subject no wager has ever
referenced.

So `players.id` stays canonical and untouched, and this table records what a
second provider calls the same subject.

── ADDITIVE, AND UNBACKFILLED BY CONSTRUCTION ──────────────────────────────

A new table. No existing row is read, rewritten or reinterpreted: not one
`players` row, not one `rosters` row, and nothing economic. No Yahoo behaviour,
Demo behaviour or fixture-replay behaviour reads this table, because nothing
outside `providers/cross_identity.py` reads it at all yet. An empty table is the
true statement about every deployment that has not yet ingested BALLDONTLIE,
which is all of them at the moment this runs.

── TWO CONSTRAINTS, BECAUSE THE MAPPING IS A BIJECTION ─────────────────────

`uq_provider_player_alias_key` stops one provider subject being claimed by two
canonical players. `uq_provider_player_alias_active_player` stops one canonical
player claiming two subjects at the same provider. Either constraint alone leaves
the other direction open, and the open direction is the one that settles a wager
against the wrong man's stat line.

THEY ARE DELIBERATELY NOT THE SAME KIND OF CONSTRAINT:

    the KEY side is a PLAIN UNIQUE, spanning retired rows too. That is what
    makes PROVIDER ID REUSE unrepresentable rather than merely discouraged — a
    retired mapping occupies its provider key forever, so a reissued identifier
    cannot be picked up by discovery and cannot silently repoint an existing
    mapping.

    the PLAYER side is a PARTIAL UNIQUE INDEX on `status = 'active'`. A full
    unique there would make retirement impossible to record: a superseded
    mapping and its replacement are two rows for one player, and the only
    alternative would be DELETING the old one — which frees its key and destroys
    the reuse guard the other constraint exists to give.

PARTIAL UNIQUE INDEXES ARE SUPPORTED BY BOTH DIALECTS this product runs on
(PostgreSQL since 7.2, SQLite since 3.8.0), so the invariant is enforced by the
database on each rather than only by the code that writes the rows.

── WHY RETIRED ROWS ARE KEPT ───────────────────────────────────────────────

`ck_provider_player_alias_status` admits `active` and `retired`. A retired
mapping is not deleted, because deleting it frees its provider key for automatic
rebinding — and quiet rebinding is the exact failure these constraints exist to
prevent. The retired row keeps the key occupied, so only an explicit, recorded
manual override can move it.

Idempotent: a schema already carrying the table is observed and left alone.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from db.schema import engine  # noqa: E402

TABLE = "provider_player_alias"


def upgrade() -> list[str]:
    dialect = engine.dialect.name
    pk = ("SERIAL PRIMARY KEY" if dialect == "postgresql"
          else "INTEGER PRIMARY KEY AUTOINCREMENT")
    timestamp_type = ("TIMESTAMP WITH TIME ZONE" if dialect == "postgresql"
                      else "TIMESTAMP")
    boolean_default_false = ("BOOLEAN NOT NULL DEFAULT FALSE"
                             if dialect == "postgresql"
                             else "BOOLEAN NOT NULL DEFAULT 0")

    with engine.begin() as connection:
        if TABLE in set(inspect(connection).get_table_names()):
            return [f"{TABLE} already exists"]
        connection.execute(text(f"""
            CREATE TABLE {TABLE} (
                id                  {pk},
                provider            VARCHAR NOT NULL,
                provider_player_key VARCHAR NOT NULL,
                player_id           INTEGER NOT NULL REFERENCES players (id),
                provider_position   VARCHAR,
                provider_nfl_team   VARCHAR(4),
                status              VARCHAR NOT NULL,
                method              VARCHAR NOT NULL,
                manual_override     {boolean_default_false},
                created_at          {timestamp_type} NOT NULL,
                updated_at          {timestamp_type} NOT NULL,
                CONSTRAINT uq_provider_player_alias_key
                    UNIQUE (provider, provider_player_key),
                CONSTRAINT ck_provider_player_alias_status
                    CHECK (status IN ('active', 'retired'))
            )
        """))
        connection.execute(text(
            f"CREATE UNIQUE INDEX uq_provider_player_alias_active_player "
            f"ON {TABLE} (provider, player_id) WHERE status = 'active'"))
        connection.execute(text(
            f"CREATE INDEX ix_provider_player_alias_player "
            f"ON {TABLE} (player_id)"))
    return [f"created {TABLE}",
            "created uq_provider_player_alias_active_player (partial unique)",
            "created ix_provider_player_alias_player"]


if __name__ == "__main__":
    for line in upgrade():
        print("  - " + line)
