"""UIRECON Rev 1.4 migration — the shared Dynamic informational odds refresh.

Creates one additive table:

    challenge_odds_refresh

WHY THIS IS SAFE TO RUN ON A LIVE ECONOMY. It creates a table and nothing else.
No existing column is retyped, no governed column is touched, no money-bearing
table is altered, nothing is backfilled and nothing is reinterpreted. A
challenge that has never been refreshed simply has no rows, which is exactly
what the read model treats as "never refreshed". Rolling back to a build without
the feature leaves the table sitting unread; it is not on any settlement,
Handshake or Final-Lock path.

WHY IT CANNOT AFFECT MONEY EVEN IN PRINCIPLE. Every row here is the record of a
NONBINDING informational re-simulation (Rev 9 §5: "informational refreshes are
nonbinding — they move no money"). Nothing in the ledger, the escrow topology,
`ChallengeFinalLock` or `Bet` reads this table, and the FK points one way — at
`beef_challenges` — so no existing row acquires a new obligation by its
existence.

Fresh databases get the same table from SQLAlchemy metadata via
`db.schema.create_all()`; this migration is the catch-up path for an EXISTING
database and is registered as ACTIVE migration 0007.

BOTH DIALECTS, DELIBERATELY. Unlike the P3-D2 Final-Lock migration — whose whole
point was PostgreSQL-only claim-mutex constraints that SQLite cannot express —
everything here is a plain table with CHECKs and an index, which SQLite creates
faithfully at CREATE TABLE time. The SQLite test path and the PostgreSQL
certification path therefore get the same shape, and the suite runs against the
schema the certification target will have.

Idempotent: running it again observes the table and makes no change.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from db.schema import engine

TABLE = "challenge_odds_refresh"


def upgrade() -> list[str]:
    dialect = engine.dialect.name
    pk = ("SERIAL PRIMARY KEY" if dialect == "postgresql"
          else "INTEGER PRIMARY KEY AUTOINCREMENT")
    # `TIMESTAMP WITHOUT TIME ZONE`, matching `DateTime` on the model and the
    # P3-D2 columns beside it. A refresh timestamp that arrived tz-aware on
    # PostgreSQL and naive on SQLite would make one comparison in the read model
    # behave differently per dialect, which is exactly the class of divergence
    # the certification path exists to catch.
    ts = "TIMESTAMP WITHOUT TIME ZONE" if dialect == "postgresql" else "TIMESTAMP"
    boolean = "BOOLEAN" if dialect == "postgresql" else "BOOLEAN"

    with engine.begin() as c:
        if TABLE in set(inspect(c).get_table_names()):
            return [f"{TABLE} already exists"]
        c.execute(text(f"""
            CREATE TABLE {TABLE} (
                id {pk},
                challenge_id INTEGER NOT NULL
                    REFERENCES beef_challenges(id),
                refreshed_at {ts} NOT NULL,
                requested_by_team_id INTEGER REFERENCES teams(id),
                model_version_id VARCHAR NOT NULL,
                model_config_hash VARCHAR NOT NULL,
                simulations INTEGER NOT NULL DEFAULT 0,
                projection_source_id VARCHAR,
                projection_dataset_version VARCHAR,
                issuer_probability DOUBLE PRECISION NOT NULL,
                opponent_probability DOUBLE PRECISION NOT NULL,
                issuer_moneyline INTEGER NOT NULL,
                opponent_moneyline INTEGER NOT NULL,
                issuer_decimal_odds DOUBLE PRECISION NOT NULL,
                opponent_decimal_odds DOUBLE PRECISION NOT NULL,
                anchor_cents INTEGER NOT NULL,
                indicative_derived_cents INTEGER NOT NULL,
                opponent_ceiling_cents INTEGER NOT NULL,
                ceiling_applied {boolean} NOT NULL DEFAULT FALSE,
                created_at {ts} NOT NULL,
                CONSTRAINT ck_challenge_odds_refresh_probabilities
                    CHECK (issuer_probability > 0 AND issuer_probability < 1
                           AND opponent_probability > 0
                           AND opponent_probability < 1),
                CONSTRAINT ck_challenge_odds_refresh_ceiling
                    CHECK (indicative_derived_cents >= 0
                           AND opponent_ceiling_cents >= 0
                           AND indicative_derived_cents <= opponent_ceiling_cents)
            )
        """))
        c.execute(text(
            f"CREATE INDEX ix_challenge_odds_refresh_challenge "
            f"ON {TABLE} (challenge_id, refreshed_at)"))
    return [f"created {TABLE}", "created ix_challenge_odds_refresh_challenge"]


if __name__ == "__main__":
    for line in upgrade():
        print(f"  · {line}")
