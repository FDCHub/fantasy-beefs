"""
economy/championship.py — championship-pot total and distribution arithmetic.

B2 Group 1 relocation. _championship_total was moved here verbatim from
payments/stripe_connect.py. It is retained economy / ledger-domain logic, not
reporting presentation: reports/ consumes the calculation, it does not own it.

B2 closure (B-2). championship_distribution() preserves the accepted
championship distribution arithmetic and remainder rule as a PURE,
provider-neutral function. That rule was previously reachable only through
payout code deleted with the Stripe surface, and would otherwise have been lost.

WHAT THIS MODULE IS NOT. Nothing here settles a season, credits a winner, or
posts to the ledger. championship_distribution() computes amounts and returns
them; it touches no database, no session, and no ledger. Internal Credits
championship settlement is NOT built and is not part of this package.
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

    Under BAB, each GM's season buy-in splits into wallet:{team_id}
    (wagerable) and reserve:{team_id} (their committed share of the
    championship pot). reserve:{team_id} IS that GM's contribution to the
    pot already — it never moves anywhere else, never gets refunded, and is
    summed here, not relocated.

    SOLE WRITER — CORRECTED. This docstring previously named Door 1,
    confirm_buyin_payment(), as the sole writer to reserve:{team_id}. That
    statement is stale: Stripe is out of the MVP, and both that function and
    payments/stripe_connect.py were deleted.

    activate_season_allocation() is now the sole production writer of the
    season-opening wallet and championship-reserve funding posting. The
    governing record is spec/SPEC_B2_Stripe_Removal_Addendum_v1.md.

    PRESERVED INVARIANT: at most one season-opening funding posting per
    (team, season).

    HOW IT IS ENFORCED, STATED PRECISELY: by removal of every alternative
    production writer, plus the SeasonAllocation unique constraint on
    (league_id, team_id, season). There is NO cross-writer runtime exclusion
    check, because after the Stripe removal there is no second writer to
    exclude. If a second funding writer is ever reintroduced, this invariant
    stops being structural and needs a real runtime guard — the AST guard in
    test_stripe_removal_regression.py and test_championship_payout.py exists
    to make that reintroduction impossible to land silently.

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


# ── Championship distribution arithmetic (B-2) ───────────────────────────────


def _reject_non_int(value: object, label: str) -> int:
    """bool is a subclass of int; a True/False here is a caller mistake, not a
    number. Reject it explicitly rather than letting it arithmetic as 1/0."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an int, got {type(value).__name__}: {value!r}")
    return value


def championship_distribution(
    total_cents: int,
    split:       list[int],
    order:       list[int],
) -> list[tuple[int, int, int, int]]:
    """
    Finding 5.2-3, Option A — the accepted championship distribution rule.

    Returns one (place, team_id, pct, amount_cents) tuple per place, in the
    order given by `order`, with place numbering starting at 1.

    RANK-ORDER CONTRACT. `order` must already be in FINAL RANK ORDER, best team
    first. This function assigns place 1 to order[0] and does not compute,
    verify or re-sort standings — ranking is the caller's responsibility (see
    reports/standings.py::_compute_standings_order). Passing an unranked list
    silently pays the wrong teams, and no validation here can detect it.

    THE RULE:
      1. Each ordinary amount is floor(total_cents * pct / 100).
      2. Whatever remains after flooring EVERY place is added, in full, to
         first place.
      3. Therefore sum(amount_cents) == total_cents for every valid input.

    First place absorbs the entire remainder — the leftover is not spread, not
    rounded to nearest, and not dropped. That is the accepted rule; do not
    substitute another rounding scheme.

    Integer cents only. No floats participate: `total_cents * pct // 100` is
    exact integer arithmetic, so no representation error can enter the pot.

    PURE. No database, no SQLAlchemy session, no ledger posting, no payment or
    provider dependency. It computes and returns; it settles nothing.

    Raises ValueError on any invalid input. Invalid input is never silently
    normalised — a bad split is a caller bug and must surface as one.

    MISMATCHED split/order IS REJECTED, DELIBERATELY. The deleted payout
    implementation zipped the two lists and silently truncated to the shorter
    one, which could under-distribute the pot while still looking successful.
    Raising here preserves the accepted invariant that exactly `total_cents` is
    distributed: a caller that cannot say how many places there are cannot be
    given a correct answer.

    ZERO-PERCENT FIRST PLACE STILL TAKES THE REMAINDER. With a split such as
    [0, 100], place 1 floors to 0 but still receives the entire flooring
    remainder. That is faithful to Option A, which sends the whole remainder to
    first place unconditionally — it is not special-cased on pct > 0, and the
    sum identity holds either way.
    """
    _reject_non_int(total_cents, "total_cents")
    if total_cents < 0:
        raise ValueError(f"total_cents must be non-negative, got {total_cents}")

    if not isinstance(split, (list, tuple)) or len(split) == 0:
        raise ValueError(f"split must be a non-empty list, got {split!r}")
    if not isinstance(order, (list, tuple)) or len(order) == 0:
        raise ValueError(f"order must be a non-empty list, got {order!r}")
    if len(split) != len(order):
        raise ValueError(
            f"split and order must be the same length: "
            f"len(split)={len(split)} len(order)={len(order)}"
        )

    for i, pct in enumerate(split):
        _reject_non_int(pct, f"split[{i}]")
        if pct < 0:
            raise ValueError(f"split[{i}] must be non-negative, got {pct}")
    if sum(split) != 100:
        raise ValueError(f"split must sum to 100, got {sum(split)} from {list(split)!r}")

    for i, team_id in enumerate(order):
        _reject_non_int(team_id, f"order[{i}]")
    if len(set(order)) != len(order):
        dupes = sorted({t for t in order if list(order).count(t) > 1})
        raise ValueError(f"order contains duplicate team ids: {dupes}")

    amounts = [total_cents * pct // 100 for pct in split]
    remainder = total_cents - sum(amounts)
    amounts[0] += remainder          # rule 2 — first place absorbs it all

    return [
        (place, team_id, pct, amount)
        for place, (team_id, pct, amount) in enumerate(zip(order, split, amounts), start=1)
    ]
