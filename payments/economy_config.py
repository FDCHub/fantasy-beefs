"""
payments/economy_config.py — B1 Discrete-Stop Economy Table.

Five certified buy-in tiers. Every figure is a fixed integer number of
cents — never derived from a percentage or fraction at runtime. A
league's buy-in must be exactly one of these five stops; no freeform
amount, no interpolation between stops.

Each stop satisfies three exact invariants (checked by validate_stop(),
and enforced against every stop below at import time — a mistyped
constant fails loudly at process startup, not silently at request time):

  1. min_reserve_cents + reserve_cents == buyin_cents
  2. min_reserve_cents == weekly_min_cents * 14
  3. reserve_cents * 11 == buyin_cents * 4
     (the tight ratio invariant — not a 33-40% band check, which
     would pass a mistyped stop this exact check catches)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import League


@dataclass(frozen=True)
class EconomyStop:
    weekly_min_cents: int
    min_reserve_cents:     int
    buyin_cents:      int
    reserve_cents:    int


ECONOMY_STOPS: tuple[EconomyStop, ...] = (
    EconomyStop(weekly_min_cents=500,  min_reserve_cents=7000,  buyin_cents=11000, reserve_cents=4000),
    EconomyStop(weekly_min_cents=1000, min_reserve_cents=14000, buyin_cents=22000, reserve_cents=8000),
    EconomyStop(weekly_min_cents=1500, min_reserve_cents=21000, buyin_cents=33000, reserve_cents=12000),
    EconomyStop(weekly_min_cents=2000, min_reserve_cents=28000, buyin_cents=44000, reserve_cents=16000),
    EconomyStop(weekly_min_cents=2500, min_reserve_cents=35000, buyin_cents=55000, reserve_cents=20000),
)

DEFAULT_STOP = ECONOMY_STOPS[1]  # weekly_min_cents=1000 ($10/week, $220 buy-in)


def validate_stop(stop: EconomyStop) -> None:
    """Raises ValueError if `stop` violates any of the three exact invariants,
    or isn't one of the five certified stops at all (no freeform stop, no
    interpolation between stops)."""
    if stop.min_reserve_cents + stop.reserve_cents != stop.buyin_cents:
        raise ValueError(
            f"Stop {stop!r}: min_reserve_cents + reserve_cents "
            f"({stop.min_reserve_cents} + {stop.reserve_cents}) != buyin_cents ({stop.buyin_cents})"
        )
    if stop.min_reserve_cents != stop.weekly_min_cents * 14:
        raise ValueError(
            f"Stop {stop!r}: min_reserve_cents ({stop.min_reserve_cents}) != "
            f"weekly_min_cents * 14 ({stop.weekly_min_cents * 14})"
        )
    if stop.reserve_cents * 11 != stop.buyin_cents * 4:
        raise ValueError(
            f"Stop {stop!r}: reserve_cents * 11 ({stop.reserve_cents * 11}) != "
            f"buyin_cents * 4 ({stop.buyin_cents * 4})"
        )
    if stop not in ECONOMY_STOPS:
        raise ValueError(f"Stop {stop!r} is not one of the five certified stops")


def find_stop_by_buyin_cents(buyin_cents: int) -> EconomyStop | None:
    """Exact-match lookup only — returns None if buyin_cents doesn't match
    one of the five stops exactly (no nearest-stop fallback, no rounding)."""
    for stop in ECONOMY_STOPS:
        if stop.buyin_cents == buyin_cents:
            return stop
    return None


def find_stop_by_weekly_min_cents(weekly_min_cents: int) -> EconomyStop | None:
    """Exact-match lookup only — symmetric to find_stop_by_buyin_cents(),
    same guarantee: returns None if weekly_min_cents doesn't match one of
    the five stops exactly (no nearest-stop fallback, no rounding)."""
    for stop in ECONOMY_STOPS:
        if stop.weekly_min_cents == weekly_min_cents:
            return stop
    return None


# ── B1-12: League's own economy-stop selector, independent of LeagueTreasury ──

def set_league_economy_stop(league_id: int, weekly_min_cents: int, db: Session) -> EconomyStop:
    """
    Commissioner-facing setter. Validates weekly_min_cents matches one of
    the five stops exactly — same "no freeform entry" rule as Build Step 1
    of the original B1 spec — and writes it to
    League.economy_stop_weekly_min_cents. Raises ValueError (no partial
    write) if it doesn't match a stop. Returns the matched stop.
    """
    stop = find_stop_by_weekly_min_cents(weekly_min_cents)
    if stop is None:
        raise ValueError(
            f"{weekly_min_cents} is not one of the five certified economy "
            f"stops (must be one of "
            f"{[s.weekly_min_cents for s in ECONOMY_STOPS]})"
        )

    league = db.query(League).filter(League.id == league_id).first()
    if not league:
        raise ValueError(f"League {league_id} not found")

    league.economy_stop_weekly_min_cents = weekly_min_cents
    db.commit()
    return stop


def get_league_economy_stop(league_id: int, db: Session) -> EconomyStop:
    """
    Reads League.economy_stop_weekly_min_cents; if null (unconfigured),
    returns DEFAULT_STOP. Always returns a valid Stop, never None — this
    function cannot fail on an unconfigured league, unlike the old
    LeagueTreasury-backed path it replaces.
    """
    league = db.query(League).filter(League.id == league_id).first()
    if not league or league.economy_stop_weekly_min_cents is None:
        return DEFAULT_STOP

    stop = find_stop_by_weekly_min_cents(league.economy_stop_weekly_min_cents)
    if stop is None:
        # Stored value no longer matches any certified stop (e.g. the table
        # itself changed) — fail loudly rather than silently substitute a
        # different stop's numbers into a real charge.
        raise ValueError(
            f"League {league_id}'s stored economy_stop_weekly_min_cents "
            f"({league.economy_stop_weekly_min_cents}) does not match any "
            f"certified stop"
        )
    return stop


# Fail loudly at import time if a stop was ever mistyped, rather than at
# whatever moment in production first happens to touch the bad row.
for _stop in ECONOMY_STOPS:
    validate_stop(_stop)
