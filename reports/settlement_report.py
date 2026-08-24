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
  pot_total        = pot_balances(league_id, current season).fantasystakes_cents
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

from db.schema import League, Team
from economy.championship_pots import pot_balances
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
    #: WP1D — True when `rows` name the actual postseason podium, False when
    #: they are the regular-season projection. Reported rather than inferred:
    #: "these are your winners" and "these would be your winners on current
    #: standings" are different claims, and a reader who cannot tell them apart
    #: will read the second as the first.
    podium_authoritative: bool = False


def championship_settlement_report(
    league_id:       int,
    db:              Session,
    standings_order: Optional[list[int]] = None,
    payout_split:    Optional[list[int]] = None,
    podium_order:    Optional[list[int]] = None,
) -> SettlementReport:
    """
    Decomposes the championship pot's payout across the configured split
    (default 60/30/10) into collected vs. contingent, per winner.

    The pot total is the current league-season FantasyStakes Championship Pot,
    read through the same authoritative helper as League Settings and Account
    Summary. Retired bare and league-only championship accounts are excluded.
    """
    # ── WP1D — WHO THIS REPORT NAMES ─────────────────────────────────────────
    #
    # `podium_order` is the actual postseason podium — champion, runner-up,
    # third-place-game winner — and it is the SAME order the season close pays.
    # Before WP1D this report projected the payout by regular-season record, and
    # so did the close; they agreed because they shared a defect. The close now
    # pays the bracket, so a report still ordered by record would tell a league
    # one set of winners and hand money to another.
    #
    # THE LEGACY ORDER SURVIVES ONLY WHERE THERE IS NO PODIUM. A league mid-
    # season, or one whose bracket its provider cannot classify, has no podium to
    # show; `_compute_standings_order` then gives the same projection it always
    # did, and `podium_authoritative` on the report says which of the two a
    # reader is looking at. NO ARITHMETIC CHANGES on either path — the split, the
    # collected/contingent decomposition and the rounding are untouched.
    order = standings_order or podium_order or _compute_standings_order(
        league_id, db)
    split = payout_split or DEFAULT_PAYOUT_SPLIT

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise ValueError(f"League {league_id} not found")
    pot_total_cents = pot_balances(
        db, league_id=league_id, season=league.season,
    ).fantasystakes_cents

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
        podium_authoritative=bool(podium_order) and not standings_order,
    )
