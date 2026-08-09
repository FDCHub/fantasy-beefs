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

    def __init__(self, league_id: int, week: int, instance_weeks) -> None:
        self.league_id = league_id
        self.week = week
        self.instance_weeks = tuple(instance_weeks)
        super().__init__(
            f"Refusing the legacy Pool economic path for league {league_id} "
            f"week {week}: this league is governed by the Rev1.3 common Pool "
            f"engine (pool_instance rows exist for week(s) "
            f"{list(self.instance_weeks)}). The legacy engine divides by three "
            f"and does not account for pool_instance, so running it here would "
            f"move cents no occurrence owns and permanently break "
            f"assert_pool_conservation for this league. Use "
            f"betting.pool_funding.collect_weekly_entries and "
            f"betting.pool_settlement.settle_week."
        )


def rev13_governed_weeks(db, league_id: int) -> tuple[int, ...]:
    """Weeks of `league_id` that carry Rev1.3 occurrences. READ-ONLY.

    Returns an empty tuple for a league that has never been drawn under Rev1.3,
    which is what makes the guard inert for legacy-only leagues."""
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
    any kind — which is exactly what the S4-P2-1 assertion measures.
    """
    weeks = rev13_governed_weeks(db, league_id)
    if weeks:
        raise LegacyPoolPathRefused(league_id, week, weeks)