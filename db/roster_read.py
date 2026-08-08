"""
db/roster_read.py — week-aware roster read with a single, shared fallback.

The only place that decides "read the immutable weekly RosterSlot snapshot, or
fall back to the static Roster table" lives here. settlement_engine, weekly_wrap
and pool_engine all import _roster_for_week so the fallback is never duplicated.

Why a fallback exists
---------------------
RosterSlot is populated per week by the Tuesday sync capture step (FR-5.7).
When a week has RosterSlot rows they are authoritative for that week's lineup
slots. When it has none — capture never ran, failed, or the week predates the
feature — we fall back to the static Roster table so settlement still runs
(degraded to "current roster" rather than "no roster").

Return shape
------------
Raw ORM rows — RosterSlot rows for the week, or Roster rows on fallback. Both
models expose .player_id, .slot and a .player relationship, so callers use the
same attribute access on either without branching:

    RosterSlot path : slot is non-nullable (never None)
    Roster fallback : slot is nullable (may be None for pre-migration rows)

Callers that filter BN/IR must keep a `slot is not None` guard so a NULL slot
on the fallback path is treated as "unknown → include", never silently dropped.
On the RosterSlot path that guard is simply always-true (a no-op).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from db.schema import Roster, RosterSlot


def _roster_for_week(team_id: int, week: int, db: Session) -> list:
    """
    Return the roster for `team_id` in `week` as raw ORM rows.

    Primary source is RosterSlot filtered to (team_id, week). If that returns
    no rows, fall back to the static Roster for the team. This is the ONLY
    definition of that fallback — do not reimplement it in callers.
    """
    slot_rows = (
        db.query(RosterSlot)
        .filter(RosterSlot.team_id == team_id, RosterSlot.week == week)
        .order_by(RosterSlot.id)
        .all()
    )
    if slot_rows:
        return slot_rows

    return (
        db.query(Roster)
        .filter(Roster.team_id == team_id)
        .order_by(Roster.id)
        .all()
    )
