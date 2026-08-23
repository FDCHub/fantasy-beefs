"""FINAL POR migration — the Fantasy Football Championship Pot amount (WP-5).

Final POR §14 makes the Fantasy Football Championship Pot ONE COMMISSIONER-
ENTERED LEAGUE AMOUNT which MAY BE ZERO, minted once at activation and frozen
there. Nothing in the schema could record that amount: the only championship
figure on `league_season_economy_config` is `championship_contribution_cents`,
which is a PER-GM contribution under the retired architecture and is still the
governing input for every legacy season on every deployment.

    ALTER TABLE league_season_economy_config
        ADD COLUMN ff_championship_pot_cents INTEGER
            CHECK (ff_championship_pot_cents IS NULL
                   OR ff_championship_pot_cents BETWEEN 0 AND 1000000)

── WHY A NEW COLUMN AND NOT A REINTERPRETATION ─────────────────────────────

Reading the Final POR's league-level pot out of `championship_contribution_cents`
would have needed no migration at all, and that is exactly the trap. The same
stored integer would mean "each GM contributes this" for a 2025 season and "the
league's whole pot is this" for a 2026 one, with only the ruleset row to tell
them apart. Every reader — the settings screen, the reconciliation mapping, an
auditor with a SQL client — would have to know the era before it could read the
number. Final POR §11 forbids silently repurposing a retired name; a column is a
name. A separate column means the two facts are separately stored, separately
frozen and separately readable, and a legacy row is untouched.

── NULL IS THE GOVERNED ABSENCE, AND IS NOT THE SAME AS 0 ──────────────────

NULL means no commissioner has entered an amount: the pillar is unconfigured,
and activation mints it at zero. 0 means a commissioner deliberately chose to
play with no Fantasy Football pot. Both leave the pillar unfunded and both are
correct; they are stored differently because a settings screen must show an
empty field in one case and an entered `0` in the other, and because a future
audit asking "did this league decline the pot or never see it?" has an answer.
Every row that exists when this migration runs becomes NULL, which is the true
statement about all of them.

── ADDITIVE, NULLABLE, UNBACKFILLED ────────────────────────────────────────

No existing row is read, rewritten or reinterpreted. No frozen configuration
changes. A legacy season keeps `championship_contribution_cents` as its per-GM
Championship Reserve contribution and this column stays NULL forever.

── ONE STATEMENT ON BOTH DIALECTS ──────────────────────────────────────────

`ADD COLUMN` with an inline column CHECK is accepted by SQLite and PostgreSQL
alike, so unlike migration 0011 this needs no table rebuild — verified on SQLite
directly (NULL admitted, 0 admitted, negative refused). Avoiding a second full
rebuild of this table matters: 0011 already rebuilds it, and chaining two
rebuilds multiplies the copy risk for a constraint that is also enforced by the
validator.

Idempotent: a schema already carrying the column is observed and left alone.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from db.schema import engine  # noqa: E402

TABLE = "league_season_economy_config"
COLUMN = "ff_championship_pot_cents"

#: The governed range. 0 is admissible by §14; the ceiling is the same
#: $10,000 ceiling every other pot-scale figure in the economy carries.
MIN_FF_CHAMPIONSHIP_POT_CENTS = 0
MAX_FF_CHAMPIONSHIP_POT_CENTS = 1_000_000

_ADD = (
    f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} INTEGER "
    f"CHECK ({COLUMN} IS NULL OR {COLUMN} BETWEEN "
    f"{MIN_FF_CHAMPIONSHIP_POT_CENTS} AND {MAX_FF_CHAMPIONSHIP_POT_CENTS})"
)


def upgrade() -> list[str]:
    """Add the column. Idempotent. Returns what it observed and what it did."""
    with engine.begin() as connection:
        names = set(inspect(connection).get_table_names())
        if TABLE not in names:
            # The table has not been created on this deployment yet. Nothing to
            # alter, and creating it here would duplicate the DDL that
            # ECONCFG-F1's own migration owns.
            return [f"{TABLE} does not exist; nothing to alter"]
        columns = {c["name"] for c in inspect(connection).get_columns(TABLE)}
        if COLUMN in columns:
            return [f"{TABLE}.{COLUMN} already exists"]
        connection.execute(text(_ADD))
    return [f"added {TABLE}.{COLUMN} (nullable, CHECK "
            f"{MIN_FF_CHAMPIONSHIP_POT_CENTS}..{MAX_FF_CHAMPIONSHIP_POT_CENTS})"]


if __name__ == "__main__":
    for line in upgrade():
        print(f"  · {line}")
