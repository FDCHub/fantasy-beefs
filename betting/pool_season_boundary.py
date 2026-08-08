"""
Season boundary — POR Rev1.3 §9.

"The hardcoded week 14 is implementation debt and is not product authority."

The governing boundary is Yahoo-derived and held on `League`:

    season_final_week   fallback 17   final-week rollover expiry sweep (§5)
    playoff_start_week  fallback 15   postseason phase begins

BOTH FIELDS ARE RULED AND THEIR READER IS UNBUILT. POR §12 item 5 and Scope §J
blocker 5 both record that the reader populating them from Yahoo does not yet
exist; it is Sprint 6 gateway work. So the columns are nullable and the
governed fallback is applied HERE, at every read, rather than as a column
default. The difference matters: a column default would write 17 into the row
and make an unmeasured value indistinguishable from a measured one, and the
first thing the Sprint 6 reader would have to do is work out which rows it may
overwrite.

THE FALLBACKS ARE THE POR'S OWN, NOT A GUESS. §9's table states them, so using
them invents no product behavior. What would invent behavior is picking a
number the POR does not state — which is exactly what the legacy `week == 14`
branch in betting/pool_engine.py does today.
"""

from __future__ import annotations

#: POR §9 table. Applied on read when the League column is NULL.
DEFAULT_SEASON_FINAL_WEEK = 17
DEFAULT_PLAYOFF_START_WEEK = 15

PHASE_REGULAR = "REGULAR"
PHASE_POSTSEASON = "POSTSEASON"


def season_final_week(league) -> int:
    """The week at which an unresolved rollover expires and sweeps (§5).

    NEVER 14. The legacy engine's `if week == 14` is the debt this replaces."""
    value = getattr(league, "season_final_week", None)
    return int(value) if value is not None else DEFAULT_SEASON_FINAL_WEEK


def playoff_start_week(league) -> int:
    """The first postseason week (§9)."""
    value = getattr(league, "playoff_start_week", None)
    return int(value) if value is not None else DEFAULT_PLAYOFF_START_WEEK


def phase_for_week(league, week: int) -> str:
    """REGULAR below `playoff_start_week`, POSTSEASON from it onward (§9).

    The regular-season no-repeat rule and the partial unique index apply only to
    the REGULAR phase; §8's postseason subset governs from `playoff_start_week`.
    """
    return PHASE_REGULAR if week < playoff_start_week(league) else PHASE_POSTSEASON


def is_final_week(league, week: int) -> bool:
    """Whether `week` is the terminal week for rollover expiry (§5, §9)."""
    return week >= season_final_week(league)