"""
migrations/manifest.py — the one answer to "what runs before a release?"

PG-CERT-1 FOUND THERE WAS NO ANSWER. Twenty-eight scripts across two
directories, no ordering, no registry, and only nine exposing a callable
`upgrade()`. That report deliberately did not invent an order for the other
nineteen, because asserting a sequence nobody had verified would have been worse
than recording that none existed. This closes the gap without inventing history.

── THE CENTRAL FACT, AND IT IS WHAT MAKES THIS SMALL ───────────────────────

A FRESH DEPLOYMENT RUNS NO MIGRATIONS AT ALL. `api/main.py`'s startup builds the
complete schema from the registered SQLAlchemy models in one step — certified on
PostgreSQL by PG-CERT-1 — so the migrations exist to carry an EXISTING database
forward, not to construct a new one. There is therefore no need to replay
historical scripts against a database that never lacked what they add.

That is why the registry below has two kinds of entry rather than one long list.

    ACTIVE       runs, in this order, against an existing database. Each is
                 idempotent, each is certified on PostgreSQL, and each is
                 additive.

    HISTORICAL   recorded, NOT run. These built the schema as it grew and their
                 effects are already represented by the registered SQLAlchemy
                 models used for fresh-database bootstrap. Several are one-shot
                 data conversions or predate columns that no longer exist;
                 running them against a modern database ranges from a no-op to
                 an error. They are named here so the inventory is complete.

── WHAT AN OPERATOR RUNS ───────────────────────────────────────────────────

    python -m migrations.run            # apply ACTIVE, in order, idempotently
    python -m migrations.run --status   # what is applied, what is pending

One command, one order, recorded in `schema_migrations`. See `migrations/run.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ACTIVE", "HISTORICAL", "Migration", "identifiers"]


@dataclass(frozen=True)
class Migration:
    """One migration, with a stable identity that never changes.

    `identifier` is what lands in `schema_migrations` and is therefore
    PERMANENT: renaming one would make an applied migration look pending and
    run it again.
    """

    identifier: str
    module: str
    summary: str


#: THE PRODUCTION UPGRADE SEQUENCE. Order matters and is deterministic.
#:
#: `add_yahoo_identity` is first because `add_provider_grants` builds a foreign
#: key to `users` and adds a constraint alongside the identity columns; running
#: them the other way round would attempt to reference a shape that is not there
#: yet. RC2's championship tables depend only on long-standing leagues/teams and
#: therefore follow those two launch migrations without changing their order.
ACTIVE: tuple = (
    Migration(
        identifier="0001_yahoo_identity",
        module="migrations.add_yahoo_identity",
        summary="users.auth_provider / provider_subject, unique on the pair, "
                "hashed_password relaxed to nullable",
    ),
    Migration(
        identifier="0002_provider_grants",
        module="migrations.add_provider_grants",
        summary="provider_grants table; leagues.provider_credential_user_id "
                "and provider_credential_assigned_at",
    ),
    Migration(
        identifier="0003_rc2_championship_snapshot",
        module="migrations.add_rc2_championship_snapshot",
        summary="immutable FantasyStakes Championship freeze and per-team "
                "regular-season Championship Score snapshot",
    ),
    Migration(
        identifier="0004_rc2_fantasystakes_championship_economy",
        module="migrations.add_rc2_fantasystakes_championship_economy",
        summary="independent commissioner-editable FantasyStakes Championship "
                "contribution and per-team fixed-pot allocation records",
    ),
)

#: RECORDED, NOT RUN — see the module docstring. Grouped by why.
HISTORICAL: tuple = (
    # Schema growth now expressed in the registered SQLAlchemy models, which a
    # fresh database is built from directly.
    "migrations/add_matchup_refreshed_at.py",
    "db/migrations/migrate_league_commissioners.py",
    "db/migrations/migrate_leagues_economy_columns.py",
    "db/migrations/migrate_ledger_entries.py",
    "db/migrations/migrate_players_yahoo_id.py",
    "db/migrations/migrate_roster_slots.py",
    "db/migrations/migrate_week_settlements.py",
    "db/migrations/migrate_week_settlements_status_token.py",
    "db/migrations/migrate_settlement_recovery_audit.py",
    "db/migrations/migrate_s6_provider_gateway.py",
    "db/migrations/migrate_s8_provider_current_week.py",
    "db/migrations/migrate_season_allocation.py",
    "db/migrations/migrate_s5_weekly_economy.py",
    "db/migrations/migrate_econcfg_f1_economy_config.py",
    "db/migrations/migrate_b6_top_off.py",
    "db/migrations/migrate_spec1_proposal_lifecycle.py",
    "db/migrations/migrate_spec2_challenge_escrow.py",
    "db/migrations/migrate_p3d2_dynamic_final_lock.py",
    "db/migrations/migrate_beef_starters_constraint.py",
    # Pool engine growth, likewise.
    "db/migrations/migrate_pool_cents.py",
    "db/migrations/migrate_pool_pots_total_pot.py",
    "db/migrations/migrate_pool_rotation_tables.py",
    "db/migrations/migrate_s4_common_pool_engine.py",
    "db/migrations/migrate_s4_pool_rollover_money.py",
    "db/migrations/migrate_wp1b_pool_subject_manifest.py",
    # One-shot DATA conversions. These rewrote existing rows into a new
    # representation. They are not idempotent in the "safe to re-run forever"
    # sense and must never be run speculatively.
    "db/migrations/migrate_tx_type_pool_values.py",
)


def identifiers() -> tuple:
    return tuple(m.identifier for m in ACTIVE)
