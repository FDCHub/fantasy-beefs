"""
Legacy Pool economic path — fail-closed guard (S4-P2-1).

THE DEFECT THIS CLOSES. After S4-P1 the repository carried TWO live Pool
economic execution paths:

    legacy   POST /pool/collect  -> betting.pool_engine.collect_weekly_entries
             POST /pool/settle   -> betting.pool_engine.settle_pool
    Rev1.3   betting.pool_funding.collect_weekly_entries
             betting.pool_settlement.settle_week

Both debit and credit `pool:{league_id}`. The legacy engine divides by three,
absorbs its remainder into Special Teams, and knows nothing about
`pool_instance`, so a legacy run against a Rev1.3-governed league would move
real money that no instance accounts for. Every Rev1.3 conservation check —
`assert_pool_conservation`, which compares the ledger balance against the sum of
unsettled pots plus live carries — would then fail, correctly, forever, and the
league could never settle again.

WHY THE GUARD IS LEAGUE-SCOPED, NOT WEEK-SCOPED. The narrow reading would refuse
only a legacy attempt on a week that already has `pool_instance` rows. That is
not enough: `pool:{league_id}` is ONE account shared by every week, so a legacy
collection on week 9 of a league whose weeks 1-8 are Rev1.3-funded still injects
untracked cents into the same account and breaks the invariant for the weeks
that ARE governed. Governance is a property of the LEAGUE, and the presence of
any `pool_instance` row is what marks a league as having crossed over.

WHERE IT IS APPLIED, AND WHY BOTH PLACES. Called from the two legacy router
handlers (the mounted HTTP surface) AND from the top of the two legacy engine
functions themselves. The router is the smallest boundary for the reachable
path found today; the function entry point is what protects a future scheduler,
management command or direct caller that never goes through FastAPI. Neither
placement rewrites the legacy engine — each is two lines at an entry point, and
the legacy settlement logic below them is untouched.

A LEAGUE THAT NEVER CROSSED OVER IS UNAFFECTED. With no `pool_instance` rows the
guard is a no-op and the legacy engine behaves exactly as before, which is why
the existing legacy suites still pass unchanged. This is a fail-closed
interlock between two engines, not a retirement of the old one — retiring it is
not S4-P2 scope.
"""

from __future__ import annotations


class LegacyPoolPathRefused(ValueError):
    """A legacy Pool economic entry point was invoked for a Rev1.3 league.

    Subclasses ValueError deliberately: both legacy routers already map
    ValueError to HTTP 400, so the refusal surfaces as a clean client error
    rather than a 500, without either handler being restructured.
    """

    def __init__(self, league_id: int, week: int, markers) -> None:
        self.league_id = league_id
        self.week = week
        self.markers = tuple(markers)
        super().__init__(
            f"Refusing the legacy Pool economic path for league {league_id} "
            f"week {week}: this league is governed by the Rev1.3 common Pool "
            f"engine. Activation evidence: {'; '.join(self.markers)}. The "
            f"legacy engine divides by three and does not account for "
            f"pool_instance, so running it here would move cents no occurrence "
            f"owns and permanently break assert_pool_conservation for this "
            f"league. Use betting.pool_funding.collect_weekly_entries and "
            f"betting.pool_settlement.settle_week."
        )


def rev13_activation_markers(db, league_id: int) -> tuple[str, ...]:
    """Durable, league-scoped evidence that `league_id` is Rev1.3-governed.

    READ-ONLY. Returns an empty tuple for a league carrying no Rev1.3 state at
    all, which is what keeps the guard inert for legacy-only leagues.

    THE FIRST-USE GAP THIS CLOSES. Keying only on `pool_instance` left a real
    hole, measured rather than reasoned about: a league configured for Rev1.3
    whose first collection had not yet run carried ZERO instances, so the
    legacy path was permitted. Observed on PostgreSQL before this fix — legacy
    collect charged four teams 1000 cents each (the LEGACY default, not the
    league's configured Rev1.3 250), moved 4000 cents into `pool:{league_id}`
    that no occurrence owned, and claimed the week's `PoolPot`, which would in
    turn have blocked the real Rev1.3 collection for that week. The markers
    below are checked as a UNION precisely because the earliest one has to fire
    before any Rev1.3 row exists.

    ORDERED FROM EARLIEST TO LATEST in a league's Rev1.3 lifetime:

      1. `pool_config.pool_weekly_entry_cents` — written by
         `configure_pool_weekly_entry`, the existing commissioner action that
         activates the league for the Rev1.3 contribution. This is the ONLY
         marker that exists BEFORE the first collection, and it is therefore
         the one that actually closes the gap. No new workflow is introduced:
         the function, the column and the CHECK all shipped in S4-P1.
      2. `pool_config.pool_weekly_entry_frozen_at` — stamped inside the first
         successful collection. Independent of (1) because a league that never
         configured still freezes at the governed default.
      3. `pool_rotation_cycle` — the rotation audit row, written when the first
         slate is drawn. Survives even if instances were ever purged.
      4. `pool_instance` — an actual drawn occurrence. The original marker.

    TRANSIENT PROVIDER READINESS IS DELIBERATELY NOT A MARKER.
    `pool_league_activation` records whether a provider is answering right now;
    it goes stale, it flips with an outage, and POR §C1.1 is explicit that it is
    environment state rather than governance. A guard keyed on it would open the
    legacy path again the moment Yahoo went down, which is precisely backwards.

    KNOWN BOUNDARY, STATED RATHER THAN PAPERED OVER. A league that has never
    been configured for Rev1.3 AND has never collected carries no durable Rev1.3
    state of any kind, so nothing here can fire for it — it is indistinguishable
    from a legacy league at the schema level, because no Rev1.3 intent was ever
    recorded. Activating such a league is exactly what
    `configure_pool_weekly_entry` is for, and marker (1) fires from that moment
    on.
    """
    from db.schema import PoolConfig, PoolInstance, PoolRotationCycle

    markers: list[str] = []

    cfg = (db.query(PoolConfig)
           .filter(PoolConfig.league_id == league_id).first())
    if cfg is not None:
        if cfg.pool_weekly_entry_cents is not None:
            markers.append(
                f"pool_config.pool_weekly_entry_cents="
                f"{cfg.pool_weekly_entry_cents}")
        if cfg.pool_weekly_entry_frozen_at is not None:
            markers.append(
                f"pool_config.pool_weekly_entry_frozen_at="
                f"{cfg.pool_weekly_entry_frozen_at.isoformat()}")

    cycles = (db.query(PoolRotationCycle)
              .filter(PoolRotationCycle.league_id == league_id).count())
    if cycles:
        markers.append(f"pool_rotation_cycle rows={cycles}")

    weeks = [r[0] for r in db.query(PoolInstance.week)
             .filter(PoolInstance.league_id == league_id)
             .distinct().order_by(PoolInstance.week).all()]
    if weeks:
        markers.append(f"pool_instance weeks={weeks}")

    return tuple(markers)


def rev13_governed_weeks(db, league_id: int) -> tuple[int, ...]:
    """Weeks of `league_id` that carry Rev1.3 occurrences. READ-ONLY."""
    from db.schema import PoolInstance

    rows = (db.query(PoolInstance.week)
            .filter(PoolInstance.league_id == league_id)
            .distinct()
            .order_by(PoolInstance.week)
            .all())
    return tuple(r[0] for r in rows)


def assert_legacy_pool_path_allowed(db, league_id: int, week: int) -> None:
    """Refuse the legacy Pool economic path for a Rev1.3-governed league.

    Raises BEFORE any read of configuration, any wallet lock, any ledger
    posting and any `pool_pots` write, so a refused attempt leaves no trace of
    any kind — which is exactly what the S4-P2-1 assertions measure.
    """
    markers = rev13_activation_markers(db, league_id)
    if markers:
        raise LegacyPoolPathRefused(league_id, week, markers)