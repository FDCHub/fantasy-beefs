"""
payments/economy_config.py — B1 Discrete-Stop Economy Table.

Five certified buy-in tiers. Every figure is a fixed integer number of
cents — never derived from a percentage or fraction at runtime. A
league's buy-in must be exactly one of these five stops; no freeform
amount, no interpolation between stops.

Each stop satisfies three exact invariants (checked by validate_stop(),
and enforced against every stop below at import time — a mistyped
constant fails loudly at process startup, not silently at request time):

  1. wallet_cents + reserve_cents == buyin_cents
  2. wallet_cents == weekly_min_cents * 14
  3. reserve_cents * 11 == buyin_cents * 4
     (the tight ratio invariant — not a 33-40% band check, which
     would pass a mistyped stop this exact check catches)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EconomyStop:
    weekly_min_cents: int
    wallet_cents:     int
    buyin_cents:      int
    reserve_cents:    int


ECONOMY_STOPS: tuple[EconomyStop, ...] = (
    EconomyStop(weekly_min_cents=500,  wallet_cents=7000,  buyin_cents=11000, reserve_cents=4000),
    EconomyStop(weekly_min_cents=1000, wallet_cents=14000, buyin_cents=22000, reserve_cents=8000),
    EconomyStop(weekly_min_cents=1500, wallet_cents=21000, buyin_cents=33000, reserve_cents=12000),
    EconomyStop(weekly_min_cents=2000, wallet_cents=28000, buyin_cents=44000, reserve_cents=16000),
    EconomyStop(weekly_min_cents=2500, wallet_cents=35000, buyin_cents=55000, reserve_cents=20000),
)

DEFAULT_STOP = ECONOMY_STOPS[1]  # weekly_min_cents=1000 ($10/week, $220 buy-in)


def validate_stop(stop: EconomyStop) -> None:
    """Raises ValueError if `stop` violates any of the three exact invariants,
    or isn't one of the five certified stops at all (no freeform stop, no
    interpolation between stops)."""
    if stop.wallet_cents + stop.reserve_cents != stop.buyin_cents:
        raise ValueError(
            f"Stop {stop!r}: wallet_cents + reserve_cents "
            f"({stop.wallet_cents} + {stop.reserve_cents}) != buyin_cents ({stop.buyin_cents})"
        )
    if stop.wallet_cents != stop.weekly_min_cents * 14:
        raise ValueError(
            f"Stop {stop!r}: wallet_cents ({stop.wallet_cents}) != "
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


# Fail loudly at import time if a stop was ever mistyped, rather than at
# whatever moment in production first happens to touch the bad row.
for _stop in ECONOMY_STOPS:
    validate_stop(_stop)
