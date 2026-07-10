"""
reports/my_account.py — B2, Section 6 "Also required": My Account summaries.

Skunk pot summary, championship pot summary, and (B2-6.5) an open-
receivable line showing any unpaid shortfall a GM personally carries —
displayed as "amount you still owe the pot," not hidden, so the honor
system this league runs on has the information it needs to work.

No collected-vs-committed distinction on the pot totals themselves
(B2-6.5): since no account in this system holds custody of real money
in the first place (B2-6.7), the full championship total is simply
shown as-is. The per-GM receivable is what's shown separately.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Team
from ledger.ledger import balance_of


@dataclass
class MyAccountSummary:
    team_id:                int
    skunk_pot_cents:         int   # league-wide skunk pot total
    championship_pot_cents:  int   # league-wide championship pot total
    my_open_receivable_cents: int  # THIS team's own outstanding receivable (0 if none owed)


def get_my_account_summary(team_id: int, db: Session) -> MyAccountSummary:
    """
    Returns the skunk pot and championship pot totals (league-wide, shared
    accounts) plus this specific team's own open receivable balance.
    Raises ValueError if the team doesn't exist.
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise ValueError(f"Team {team_id} not found")

    skunk_pot_cents        = balance_of("skunk")
    championship_pot_cents = balance_of("championship")

    # receivable:{team_id} is debited (negative) when money is owed; 0 or
    # positive means nothing outstanding. "Amount you still owe" is the
    # magnitude of however negative it currently sits.
    receivable_balance = balance_of(f"receivable:{team_id}")
    my_open_receivable_cents = abs(min(0, receivable_balance))

    return MyAccountSummary(
        team_id=team_id,
        skunk_pot_cents=skunk_pot_cents,
        championship_pot_cents=championship_pot_cents,
        my_open_receivable_cents=my_open_receivable_cents,
    )
