"""
migrations/manifest.py — the one answer to "what runs before a release?"

A fresh deployment is built from registered SQLAlchemy models. ACTIVE migrations
carry an existing database forward and run in deterministic order.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ACTIVE", "HISTORICAL", "Migration", "identifiers"]


@dataclass(frozen=True)
class Migration:
    """One ordered, recorded schema change — and what proves it really landed.

    ── B1 · WHY `tables` AND `columns` EXIST ────────────────────────────────

    A row in `schema_migrations` is a CLAIM, not evidence. Before B1 the whole
    readiness story rested on that claim: if the record said 0003-0006 were
    applied, `/ready` answered healthy without ever looking at the schema.

    That is not hypothetical. Booting `api.main` instead of `api.main_rc2`
    against a fresh database registers no RC2 model, so `create_all` builds none
    of the six championship tables while `stamp_all` still records all six
    migrations as applied. Measured on this branch: `/ready` returned 200,
    `ready: true`, `migrations: "ok"` — against a database that cannot run a
    championship. The entrypoint was corrected for RC2, but the READINESS
    WEAKNESS survived it, and any other stamp/schema divergence — a restored
    older dump, a half-applied migration on a dialect without transactional
    DDL, a hand-edited record — lands in the same silent hole.

    So each migration names the database objects that MUST be present once it is
    applied. `migrations.run.verify` checks the claim against the live schema and
    readiness fails closed when they disagree. This adds no second migration
    system and changes no migration's behaviour: it is the manifest describing
    itself well enough to be checked.

    `tables` are table names. `columns` are `("table", "column")` pairs, for the
    migrations that add columns to tables which already existed.
    """

    identifier: str
    module: str
    summary: str
    tables: tuple = ()
    columns: tuple = ()


ACTIVE: tuple = (
    Migration(
        identifier="0001_yahoo_identity",
        module="migrations.add_yahoo_identity",
        summary="users.auth_provider / provider_subject, unique on the pair, hashed_password relaxed to nullable",
        columns=(("users", "auth_provider"), ("users", "provider_subject")),
    ),
    Migration(
        identifier="0002_provider_grants",
        module="migrations.add_provider_grants",
        summary="provider_grants table; leagues.provider_credential_user_id and provider_credential_assigned_at",
        tables=("provider_grants",),
        columns=(("leagues", "provider_credential_user_id"),
                 ("leagues", "provider_credential_assigned_at")),
    ),
    Migration(
        identifier="0003_rc2_championship_snapshot",
        module="migrations.add_rc2_championship_snapshot",
        summary="immutable FantasyStakes Championship freeze and per-team regular-season Championship Score snapshot",
        tables=("fantasystakes_championship_freeze",
                "fantasystakes_championship_score"),
    ),
    Migration(
        identifier="0004_rc2_fantasystakes_championship_economy",
        module="migrations.add_rc2_championship_economy",
        summary="independent FantasyStakes Championship contribution and fixed-pot allocation records",
        tables=("fantasystakes_championship_config",
                "fantasystakes_championship_allocation"),
    ),
    Migration(
        identifier="0005_rc2_championship_distribution",
        module="migrations.add_rc2_championship_distribution",
        summary="durable exactly-once FantasyStakes Championship 60/30/10 distribution record",
        tables=("fantasystakes_championship_distribution_run",),
    ),
    Migration(
        identifier="0006_rc2_championship_correction",
        module="migrations.add_rc2_championship_correction",
        summary="append-only authoritative corrections to eligible regular-season championship results",
        tables=("fantasystakes_championship_correction",),
    ),
    Migration(
        identifier="0007_dynamic_odds_refresh",
        module="migrations.add_dynamic_odds_refresh",
        summary="append-only shared record of nonbinding Dynamic informational odds refreshes (Rev 9 §5)",
        tables=("challenge_odds_refresh",),
    ),
    Migration(
        identifier="0008_pool_definition_public_question",
        module="migrations.add_pool_definition_public_question",
        summary="Pool Catalog Rev 1.4 §3 — nullable public_question on pool_definition, seeded from the governed catalog",
        columns=(("pool_definition", "public_question"),),
    ),
    # RC4 MOBILE RECONCILIATION — 0008 ADDED THE COLUMN AND BACKFILLED NOTHING.
    #
    # Its own docstring is explicit that the 64 questions "arrive with the
    # ordinary Rev 1.4 re-seed". Every path that re-seeds the catalog does
    # deliver them; a RELEASE does not — `preDeployCommand` runs this manifest
    # and nothing in it calls `seed_definitions`. A deployed database whose
    # `pool_definition` rows predate Rev 1.4 therefore kept eighty NULLs and
    # Play drew `Question unavailable` on live drawable Pools.
    #
    # NO SCHEMA OBJECT IS ADDED, so this migration names no `tables` and no
    # `columns`: it asserts nothing new about the shape of the database and
    # `verify` has nothing further to corroborate. 0008 already guarantees the
    # column it writes to, and is ordered before it.
    Migration(
        identifier="0009_pool_definition_public_question_backfill",
        module="migrations.backfill_pool_definition_public_question",
        summary="Pool Catalog Rev 1.4 §3 — carry the governed public_question onto pool_definition rows written before the revision",
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
