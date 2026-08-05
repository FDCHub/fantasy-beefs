"""
economy/championship.py — championship-pot total.

B2 Group 1 relocation. _championship_total was moved here verbatim from
payments/stripe_connect.py, docstring included. It is retained economy /
ledger-domain logic, not reporting presentation: reports/ consumes the
calculation, it does not own it. Behavior is unchanged.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Team
from ledger.ledger import balance_of


def _championship_total(league_id: int, db: Session) -> int:
    """
    Finding 5.2 — the corrected championship-payout source of truth.

    Under BAB, each GM's buy-in splits into wallet:{team_id} (wagerable)
    and reserve:{team_id} (their committed share of the championship pot)
    at confirmation (Door 1, confirm_buyin_payment() — confirmed this
    session as the SOLE writer to reserve:{team_id} anywhere in the
    codebase; see 5.2-1 and this module's test suite's regression guard).
    reserve:{team_id} IS that GM's contribution to the pot already — it
    never moves anywhere else, never gets refunded, and is summed here,
    not relocated.

    The B2 shortfall sweep separately credits the shared "championship"
    account for money that isn't any one GM's own contribution (unmet
    weekly minimums swept from the league at large). Two funding sources,
    same pot, tracked separately because their provenance differs —
    summed only here, at payout-computation time.

    LeagueTreasury.total_collected_cents is NOT read here — it went stale
    the moment Session B1 moved buy-in confirmation onto the ledger and
    stopped writing that field. Retired from this path, not deleted from
    the schema (a column removal is separate, lower-priority cleanup).

    FR-5.5 interim bridge (SC-1/SC-2, Opus-reviewed): pool_engine.py's
    settle_pool() now sweeps to the league-scoped championship:{league_id}
    key (pool_rollover_expiry, pool_no_predictors_sweep), while
    shortfall_sweep.py still writes the bare, global "championship"
    account. Until shortfall_sweep.py is converted to scoped keys (the
    full FR-5.5 resolution — separate scope, not done in this pass), this
    function reads BOTH keys and sums them. Single-league-only interim
    measure: summing championship:{league_id} across every league would
    double-count once a second league starts sweeping there, but today
    there is exactly one league in production, so this is safe as written.
    """
    team_ids = [t.id for t in db.query(Team).filter(Team.league_id == league_id).all()]
    reserve_total = sum(balance_of(f"reserve:{tid}") for tid in team_ids)
    return reserve_total + balance_of("championship") + balance_of(f"championship:{league_id}")
