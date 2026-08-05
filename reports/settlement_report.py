"""
reports/settlement_report.py — B2-6.3-R: season-end settlement report
decomposition.

The atomic shortfall-sweep posting itself is unchanged (B2-6.3, Option A —
championship is credited the full shortfall immediately, in one posting,
covered + uncovered together). What this module adds is purely a
reporting-layer view: each winner's payout figure broken into collected
(backed by real wallet draws) vs. contingent (still backed only by an
outstanding receivable, not yet cleared) — e.g. "$180 total, of which
$170 settled / $10 contingent on GM B's outstanding receivable."

Computed entirely from the ledger's own entries:
  pot_total        = balance_of("championship")
  contingent_total = sum of every team's CURRENT open receivable balance
                     in the league (still owed right now — this reads live,
                     so it reflects any clearing that may have happened
                     since a shortfall was originally swept)
  collected_total  = pot_total - contingent_total

Every winner's share is decomposed in that same collected/contingent
ratio. No new posting type; no change to the atomic sweep posting.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Team
from reports.standings import _compute_standings_order, DEFAULT_PAYOUT_SPLIT
from ledger.ledger import balance_of


@dataclass
class SettlementRow:
    place:           int
    team_id:         int
    team_name:       str
    pct:             int
    payout_cents:    int
    collected_cents: int
    contingent_cents: int


@dataclass
class SettlementReport:
    league_id:         int
    pot_total_cents:   int
    collected_cents:   int
    contingent_cents:  int
    rows:              list[SettlementRow]


def championship_settlement_report(
    league_id:       int,
    db:              Session,
    standings_order: Optional[list[int]] = None,
    payout_split:    Optional[list[int]] = None,
) -> SettlementReport:
    """
    Decomposes the championship pot's payout across the configured split
    (default 60/30/10) into collected vs. contingent, per winner.

    FR-5.5 interim bridge (SC-1/SC-2, Opus-reviewed): pot_total_cents sums
    the bare "championship" account (still written by shortfall_sweep.py)
    and the league-scoped "championship:{league_id}" account (written by
    pool_engine.py's settle_pool()). Interim measure until
    shortfall_sweep.py is converted to scoped keys (full FR-5.5
    resolution, separate scope) — see payments/stripe_connect.py's
    _championship_total() for the same bridge and its single-league-only
    caveat.
    """
    order = standings_order or _compute_standings_order(league_id, db)
    split = payout_split or DEFAULT_PAYOUT_SPLIT

    pot_total_cents = balance_of("championship") + balance_of(f"championship:{league_id}")

    teams = db.query(Team).filter(Team.league_id == league_id).all()
    contingent_cents = sum(
        abs(min(0, balance_of(f"receivable:{t.id}")))
        for t in teams
    )
    # Never let a rounding/timing edge case (e.g. contingent computed after
    # a payout already partially drained the pot) push collected negative.
    collected_cents = max(0, pot_total_cents - contingent_cents)

    rows: list[SettlementRow] = []
    for i, pct in enumerate(split):
        if i >= len(order):
            break
        team_id = order[i]
        team = db.query(Team).filter(Team.id == team_id).first()

        payout_cents = (pot_total_cents * pct) // 100
        if pot_total_cents > 0:
            row_collected_cents = (payout_cents * collected_cents) // pot_total_cents
        else:
            row_collected_cents = 0
        row_contingent_cents = payout_cents - row_collected_cents

        rows.append(SettlementRow(
            place=i + 1,
            team_id=team_id,
            team_name=team.team_name if team else str(team_id),
            pct=pct,
            payout_cents=payout_cents,
            collected_cents=row_collected_cents,
            contingent_cents=row_contingent_cents,
        ))

    return SettlementReport(
        league_id=league_id,
        pot_total_cents=pot_total_cents,
        collected_cents=collected_cents,
        contingent_cents=contingent_cents,
        rows=rows,
    )
