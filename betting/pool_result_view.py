"""
betting/pool_result_view.py — what a settled Prop Pool looks like, per GM.

READ-ONLY. Nothing here settles, evaluates, distributes, posts or re-derives a
winner. It answers one question — "what happened in this Pool, and what did it
do to my Credits" — from rows the settlement engine already wrote.

── WHY THE WINNING SUBJECT HAS TO BE DERIVED (UIRECON Wave 4B) ──────────────

`betting/pool_settlement` computes `winning_subject_ids` and returns them on an
in-memory `SettlementResult`. It does not persist them: `pool_instance` carries
`settled`, `settled_at`, `settlement_classification`, `distributed_cents` and
`rollover_cents`, and nothing else about the outcome.

TWO WAYS TO GET IT BACK, AND ONLY ONE OF THEM IS ALLOWED. Re-running the
evaluator would reproduce the answer and would be a second settlement engine
living in a read path — the exact duplication Wave 4 §15 forbids, and the kind
that agrees with the first one until the day somebody fixes a bug in only one.

So it is read out of what settlement WROTE. A winner distribution posts through
`PoolEconomicEvent(pool_instance_id, WINNER_DISTRIBUTION, posting_id)`, and that
posting credits the winning GMs' wallets. Those GMs' own claims name the subject
they picked — and a GM is paid only for picking a winning subject, so the set of
subjects on the paid claims IS the set that won. Every step is a row lookup.

── WHERE IT HONESTLY CANNOT ANSWER ─────────────────────────────────────────

When nobody picked the winner the pot rolls over or is swept, no wallet is
credited, and there is no paid claim to read a subject off. The winning subject
is then genuinely unavailable to this read, and it is reported as unavailable
rather than guessed. `classification` still says what happened, which is what
the surface actually needs in that case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

#: The economic event a paid Pool writes. Mirrors
#: `betting.pool_settlement.EVENT_WINNER_DISTRIBUTION`; imported lazily below so
#: this module never pulls the settlement engine into a read path at import time.
_WINNER_DISTRIBUTION = "WINNER_DISTRIBUTION"

#: The ledger account family a GM's Credits live in.
_WALLET_PREFIX = "wallet:"


@dataclass
class PoolResultView:
    """One settled occurrence, from the viewing GM's side."""

    pool_instance_id: int
    week: int
    settled: bool
    #: The engine's own classification string, verbatim. Never reworded here.
    classification: Optional[str]
    #: Cents the distribution actually paid out, as settlement recorded them.
    distributed_cents: int
    rollover_cents: int
    #: How many GMs claimed this occurrence. A count, not a roster.
    entrants: int
    #: The subjects that won, derived from the paid claims. EMPTY when nobody
    #: picked a winner — the pot rolled over or was swept — which is a real
    #: outcome and not a missing value.
    winning_subject_ids: tuple[int, ...] = ()
    #: The viewing GM's own claim, and what it did to their Credits.
    my_subject_id: Optional[int] = None
    my_return_cents: int = 0
    my_result: Optional[str] = None      # won | lost | no_result | not_entered


def _paid_teams(db: Session, *, pool_instance_id: int) -> dict[int, int]:
    """`{team_id: cents credited}` from this occurrence's winner distribution.

    THE POSTING IS THE AUTHORITY. Reading the ledger rather than recomputing a
    share is what keeps this a report: whatever settlement actually paid is what
    is shown, including a remainder or an uneven split it decided on.
    """
    from db.schema import PoolEconomicEvent

    events = (db.query(PoolEconomicEvent)
              .filter(PoolEconomicEvent.pool_instance_id == pool_instance_id,
                      PoolEconomicEvent.event_type == _WINNER_DISTRIBUTION)
              .all())
    paid: dict[int, int] = {}
    for event in events:
        if event.posting_id is None:
            continue
        rows = db.execute(
            text("SELECT account, amount_cents FROM ledger_entries "
                 "WHERE posting_id = :posting AND amount_cents > 0"),
            {"posting": str(event.posting_id)},
        ).fetchall()
        for account, cents in rows:
            if not str(account).startswith(_WALLET_PREFIX):
                continue
            try:
                team_id = int(str(account).split(":")[1])
            except (IndexError, ValueError):
                continue
            paid[team_id] = paid.get(team_id, 0) + int(cents)
    return paid


def pool_result(db: Session, *, instance, viewer_team_id: Optional[int]
                ) -> PoolResultView:
    """The settled view of one occurrence for one GM.

    :param instance: a `PoolInstance` row
    :param viewer_team_id: the acting GM's team, or None for no viewer
    """
    from db.schema import PoolClaim

    claims = (db.query(PoolClaim)
              .filter(PoolClaim.pool_instance_id == instance.id).all())
    mine = next((c for c in claims if c.team_id == viewer_team_id), None)

    view = PoolResultView(
        pool_instance_id=instance.id,
        week=instance.week,
        settled=bool(instance.settled),
        classification=instance.settlement_classification,
        distributed_cents=int(instance.distributed_cents or 0),
        rollover_cents=int(instance.rollover_cents or 0),
        entrants=len(claims),
        my_subject_id=mine.selected_subject_id if mine else None,
    )

    if not instance.settled:
        return view

    paid = _paid_teams(db, pool_instance_id=instance.id)
    winners = {c.selected_subject_id for c in claims if c.team_id in paid}
    view.winning_subject_ids = tuple(sorted(winners))
    view.my_return_cents = int(paid.get(viewer_team_id, 0))

    if mine is None:
        view.my_result = "not_entered"
    elif viewer_team_id in paid:
        view.my_result = "won"
    elif not paid:
        # NOBODY WON. The pot rolled over or was swept, so this GM did not lose
        # to another GM's pick — there was no winning ticket at all, and saying
        # "lost" would describe a contest that did not happen.
        view.my_result = "no_result"
    else:
        view.my_result = "lost"

    return view
