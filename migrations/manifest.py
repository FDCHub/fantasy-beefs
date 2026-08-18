"""
migrations/manifest.py — the one answer to "what runs before a release?"

PG-CERT-1 FOUND THERE WAS NO ANSWER. Twenty-eight scripts across two
directories, no ordering, no registry, and only nine exposing a callable
`upgrade()`. That report deliberately did not invent an order for the other
nineteen, because asserting a sequence nobody had verified would have been worse
than recording that none existed. This closes the gap without inventing history.

A fresh deployment is built from registered SQLAlchemy models. ACTIVE migrations
carry an existing database forward and run in deterministic order.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ACTIVE", "HISTORICAL", "Migration", "identifiers"]


@dataclass(frozen=True)
class Migration:
    identifier: str
    module: str
    summary: str


ACTIVE: tuple = (
    Migration(
        identifier="0001_yahoo_identity",
        module="migrations.add_yahoo_identity",
        summary="users.auth_provider / provider_subject, unique on the pair, hashed_password relaxed to nullable",
    ),
    Migration(
        identifier="0002_provider_grants",
        module="migrations.add_provider_grants",
        summary="provider_grants table; leagues.provider_credential_user_id and provider_credential_assigned_at",
    ),
    Migration(
        identifier="0003_rc2_championship_snapshot",
        module="migrations.add_rc2_championship_snapshot",
        summary="immutable FantasyStakes Championship freeze and per-team regular-season Championship Score snapshot",
    ),
    Migration(
        identifier="0004_rc2_fantasystakes_championship_economy",
        module="migrations.add_rc2_championship_economy",
        summary="independent FantasyStakes Championship contribution and fixed-pot allocation records",
    ),
)


HISTORICAL: tuple = (
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
    "db/migrations/migrate_pool_cents.py",
    "db/migrations/migrate_pool_pots_total_pot.py",
    "db/migrations/migrate_pool_rotation_tables.py",
    "db/migrations/migrate_s4_common_pool_engine.py",
    "db/migrations/migrate_s4_pool_rollover_money.py",
    "db/migrations/migrate_wp1b_pool_subject_manifest.py",
    "db/migrations/migrate_tx_type_pool_values.py",
)


def identifiers() -> tuple:
    return tuple(m.identifier for m in ACTIVE)
