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

    #: WHY THIS MIGRATION NAMES NO OBJECT — required when `tables` and `columns`
    #: are both empty, and empty otherwise.
    #:
    #: NOT EVERY MIGRATION ADDS A DATABASE OBJECT. A data backfill and a widened
    #: CHECK both change the database and neither creates anything `verify` can
    #: look up, so the pair being empty is legitimate for them. It is ALSO what
    #: an author who simply forgot to fill them in leaves behind, and those two
    #: cases were indistinguishable: the readiness suite could only assert
    #: "every migration names an object", which the legitimate cases failed.
    #:
    #: Declaring the reason makes the distinction explicit and checkable. A
    #: migration that adds objects and forgets to name them still fails, which
    #: is the protection B1 exists to give; one that genuinely adds none says so
    #: once, here, in a sentence a reviewer can disagree with.
    adds_no_object: str = ""


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
        adds_no_object=(
            "a pure data backfill: it writes rows into a column 0008 already "
            "created and guarantees, and is ordered after it. There is no new "
            "object for `verify` to corroborate."),
    ),
    # FINAL POR · WP-1 — THE ERA GATE, AND IT RUNS BEFORE EVERY ECONOMY CHANGE.
    #
    # Ordered first among the Final POR migrations deliberately. Every later
    # economy migration is safe only because this table exists to distinguish a
    # season governed by the new rules from one that must keep its original
    # ones; applying any of them first would leave a window in which the two
    # eras were indistinguishable.
    #
    # ADDITIVE AND UNBACKFILLED. Absence of a row IS the legacy ruleset, so this
    # migration writes no data and changes no existing table.
    Migration(
        identifier="0010_season_ruleset",
        module="migrations.add_season_ruleset",
        summary="Final POR WP-1 — season-level ruleset era gate; absence means the legacy ruleset and nothing is backfilled",
        tables=("league_season_ruleset",),
    ),
    # FINAL POR §9D — Skunk Fees are optional, so 0 must be storable.
    #
    # NAMES NO `tables` OR `columns`, and that is not an omission: it adds no
    # database object. It only WIDENS an existing CHECK, and `verify` corroborates
    # the presence of objects rather than the shape of constraints. The widening
    # is asserted directly by test_finalpor_wp2_skunk_zero.py on both dialects.
    Migration(
        identifier="0011_skunk_fee_allows_zero",
        module="migrations.relax_skunk_fee_allows_zero",
        summary="Final POR §9D — league_season_economy_config.ck_lsec_skunk_fee widened to admit a 0 Weekly Skunk Fee",
        adds_no_object=(
            "it only WIDENS an existing CHECK. `verify` corroborates the "
            "presence of objects, not the shape of constraints, so there is "
            "nothing here for it to look up. The widening is asserted directly, "
            "on both dialects, by test_finalpor_wp2_skunk_zero.py."),
    ),
    # FINAL POR §14 / WP-5 — the Fantasy Football Championship Pot amount.
    #
    # ADDITIVE AND NULLABLE, and it names its column so `verify` can corroborate
    # it. A NEW column rather than a reinterpretation of
    # `championship_contribution_cents`: that integer means "each GM contributes
    # this" for every legacy season and would mean "the league's whole pot is
    # this" for a Final POR one, with only the ruleset row to tell a reader
    # which. §11 forbids silently repurposing a retired name, and a column is a
    # name. Every existing row becomes NULL, which is true of all of them.
    Migration(
        identifier="0012_ff_championship_pot",
        module="migrations.add_ff_championship_pot",
        summary="Final POR §14 — league_season_economy_config.ff_championship_pot_cents; one commissioner-entered league-level Fantasy Football Championship Pot, may be 0, NULL where unconfigured",
        columns=(("league_season_economy_config", "ff_championship_pot_cents"),),
    ),
    # FINAL POR §7 / WP-13 — the voided-wager record.
    #
    # A NEW TABLE rather than a widened `ck_bet_status`. A void is not a `push`:
    # a push is a RESULT, a void says no contest occurred, and §7 gives the two
    # different consequences for the Weekly Minimum. Widening that CHECK would
    # also have meant rebuilding `bets` on SQLite for a fact that belongs beside
    # the refund it records rather than inside the wager it cancels.
    Migration(
        identifier="0013_voided_wagers",
        module="migrations.add_voided_wagers",
        summary="Final POR §7 — voided_wagers; one row per voided accepted wager, unique on bet_id, recording the Wallet refund that never restores the Weekly Minimum",
        tables=("voided_wagers",),
    ),
    # WP1 · BALLDONTLIE INTEGRATION — the cross-provider player identity map.
    #
    # ORDERED LAST, AND IT COULD BE ORDERED ANYWHERE. Every migration before it
    # changes something an economic path reads; this one adds a table nothing
    # outside providers/cross_identity.py reads at all. It has no ordering
    # relationship with the Final POR sequence above because it shares no object
    # with any of it — the only table it references is `players`, which predates
    # every migration in this manifest.
    #
    # ADDITIVE AND UNBACKFILLED. `players.id` remains the canonical FantasyStakes
    # player identity; this table records only what a SECOND provider calls the
    # same subject. No `players` row is rewritten and no economic row is read, so
    # existing Yahoo, Demo and fixture-replay behaviour is unchanged by
    # construction rather than by test.
    Migration(
        identifier="0014_provider_player_alias",
        module="migrations.add_provider_player_alias",
        summary="WP1 — provider_player_alias; durable Yahoo/FantasyStakes <-> BALLDONTLIE player identity. A bijection per provider: a plain unique on the provider key (spanning retired rows, so an identifier can never be reused) and a partial unique on (provider, player_id) WHERE status='active' (so a superseded mapping is retired rather than deleted)",
        tables=("provider_player_alias",),
    ),
    # SPRINT 2B · COMPONENT PROJECTION STORAGE — where a BALLDONTLIE projection
    # can live without pretending to be a league's fantasy points.
    #
    # ADDITIVE, AND DELIBERATELY BESIDE `projections` RATHER THAN INSIDE IT.
    # `projections.projected_points` is a SCALAR that twelve modules read and
    # that `odds/monte_carlo.py` draws a distribution around — a number written
    # there moves a market line. A component projection is the upstream material
    # that has not been scored by any league's rule set yet, so it has no scalar
    # to be. Nothing in this migration reads, alters or reinterprets a
    # `projections` row.
    #
    # APPEND-ONLY BY CONSTRUCTION. A projection is a forecast that changes, and
    # BALLDONTLIE serves no point-in-time history, so this table is the only
    # place that can hold what was knowable before kickoff. The unique key
    # includes an observation digest that covers the payload but not the fetch
    # time, so an unchanged re-fetch collides and is skipped while a genuinely
    # moved projection lands beside its predecessor.
    Migration(
        identifier="0015_provider_component_projection",
        module="migrations.add_provider_component_projection",
        summary="Sprint 2B — provider_component_projection; append-only component projection snapshots keyed to the canonical player, unique on (provider, player_id, season, week, observation_digest) so an unchanged re-fetch is a no-op and a changed forecast is a new snapshot. `projections.projected_points` is untouched",
        tables=("provider_component_projection",),
    ),
    # SPRINT 5 · HISTORICAL MODEL PARAMETERS — the measured samples behind the
    # three projection models Sprint 4 deliberately left unresolved.
    #
    # DERIVED AGGREGATES, NOT RAW HISTORY. BALLDONTLIE's terms permit raw
    # retention outright, so this is an engineering choice: pricing reads a rate
    # and a sample size, and a table of raw plays would be rows nobody queries
    # in a database that has to carry them forever. Raw payloads stay in the
    # fixture corpus where certification needs them.
    #
    # APPEND-ONLY AND AS-OF AWARE. The unique key ends in a fingerprint over the
    # derivation, so an unchanged refresh writes nothing and a provider
    # correction lands beside its predecessor rather than overwriting it — which
    # is what lets a wager priced last week still replay against the parameters
    # that priced it. `as_of` is the historical cutoff the derivation respected,
    # so a projection can never be built from results nobody could have known.
    Migration(
        identifier="0016_provider_historical_rate",
        module="migrations.add_provider_historical_rate",
        summary="Sprint 5 — provider_historical_rate; derived historical model parameters (reception catch rate, pick-six conditional rate, three-and-out rate) with an as-of cutoff and an append-only fingerprint key so corrections never mutate the parameters a frozen wager was priced against",
        tables=("provider_historical_rate",),
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
