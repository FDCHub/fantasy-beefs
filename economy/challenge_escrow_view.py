"""
economy/challenge_escrow_view.py — READ-ONLY views over challenge funding
provenance, for display models.

WHY THIS IS A SEPARATE MODULE FROM challenge_funding.py, AND WHY THAT MATTERS.
Spec 1 §13 requires the new proposal lifecycle to stay UNREACHABLE from the live
application until it is deliberately enabled, and Package 2A's gate suite proves
it by asserting that nothing reachable from `api.main` imports
`beefs.proposal_lifecycle`. Its docstring calls that the most important assertion
in the package: "a throwing stub is a path that exists and fails; unreachability
is the absence of a path."

economy/challenge_funding.py is the ORCHESTRATOR — it imports the Spec 1
lifecycle in order to drive it. So any module that imports the orchestrator drags
the whole new lifecycle into the application's import graph and destroys that
unreachability, even if it only wanted to read a number.

The wallet display models need exactly one number: how much real challenge escrow
a team currently has committed. That is a two-table read with no lifecycle
behaviour behind it. Putting it here — importing db.schema and nothing else —
lets the display models report real escrow while the money path stays unreachable
until it is switched on.

READ-ONLY. Nothing in this module writes, posts, locks or commits.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import BeefChallenge, ChallengeFundingLeg

# The negotiation states in which a challenge still HOLDS its escrow.
#
# beefs.proposal_lifecycle.OPEN_STATES is the vocabulary authority; this is a
# deliberate literal copy, because importing that module here would reintroduce
# exactly the import edge this module exists to avoid (see the docstring). The
# two are pinned equal by an assertion in the P1-L4 suite, so a future change to
# one cannot silently diverge from the other. The same strings are also the
# 'offered'/'countered' members of the ck_beef_response_status CHECK.
OPEN_RESPONSE_STATES = ("offered", "countered")


def challenge_escrow_account(challenge_id: int) -> str:
    return f"escrow:challenge:{challenge_id}"


def team_open_challenge_escrow_cents(db: Session, team_id: int) -> int:
    """Real challenge escrow this team currently has funded across OPEN
    challenges, in integer cents, derived from the funding provenance (Spec 2 §5).

    THIS IS WHAT REPLACES `_challenge_reserved` FOR DISPLAY. The old value was a
    soft reservation computed from proposed stake amounts on rows with no money
    behind them. This is the actual committed money, net of reversals,
    reconstructed from the legs that moved it.

    OPEN CHALLENGES ONLY. Once a challenge is accepted its Anchor escrow has
    migrated into Bet escrow, where it already shows up as ordinary pending wager
    exposure; continuing to count it here would report the same money twice under
    two names. Terminal challenges have had their legs reversed and net to zero
    anyway — the state filter makes that explicit rather than incidental.

    `fund` legs are positive and `reverse` legs negative (schema CHECK), so the
    plain sum is the net. Legs whose destination is a Bet escrow — the Derived
    funding written at acceptance — are excluded by the destination filter,
    because they are not challenge escrow and never were.
    """
    rows = (
        db.query(ChallengeFundingLeg, BeefChallenge.response_status)
        .join(BeefChallenge, ChallengeFundingLeg.challenge_id == BeefChallenge.id)
        .filter(ChallengeFundingLeg.team_id == team_id)
        .all()
    )
    total = 0
    for leg, response_status in rows:
        if response_status not in OPEN_RESPONSE_STATES:
            continue
        if leg.destination_account != challenge_escrow_account(leg.challenge_id):
            continue
        total += leg.amount_cents
    return total
