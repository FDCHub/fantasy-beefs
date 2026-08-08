"""
test_economy_config.py — Unit tests for payments/economy_config.py
(Session B1, Build Step 1: the Discrete-Stop Economy Table).

No database involved — this module is pure Python data + validation.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from economy.economy_config import (
    ECONOMY_STOPS,
    DEFAULT_STOP,
    EconomyStop,
    validate_stop,
    find_stop_by_buyin_cents,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


print("\nAll five stops individually satisfy all three exact invariants")
for stop in ECONOMY_STOPS:
    raised = False
    try:
        validate_stop(stop)
    except ValueError as e:
        raised = True
        print(f"    unexpected: {e}")
    _assert(f"stop weekly_min={stop.weekly_min_cents} validates clean", not raised)

_assert("exactly five stops defined", len(ECONOMY_STOPS) == 5, f"got {len(ECONOMY_STOPS)}")
_assert("DEFAULT_STOP is the $10/week ($22000 buy-in) stop", DEFAULT_STOP.weekly_min_cents == 1000, f"got {DEFAULT_STOP.weekly_min_cents}")


print("\nRule 1: wallet_cents + reserve_cents == buyin_cents, for every stop")
for stop in ECONOMY_STOPS:
    _assert(
        f"stop {stop.weekly_min_cents}: {stop.wallet_cents} + {stop.reserve_cents} == {stop.buyin_cents}",
        stop.wallet_cents + stop.reserve_cents == stop.buyin_cents,
    )

print("\nRule 2: wallet_cents == weekly_min_cents * 14, for every stop")
for stop in ECONOMY_STOPS:
    _assert(
        f"stop {stop.weekly_min_cents}: wallet_cents == weekly_min_cents * 14",
        stop.wallet_cents == stop.weekly_min_cents * 14,
    )

print("\nRule 3: reserve_cents * 11 == buyin_cents * 4, for every stop (tight ratio, not a 33-40% band)")
for stop in ECONOMY_STOPS:
    _assert(
        f"stop {stop.weekly_min_cents}: reserve_cents * 11 == buyin_cents * 4",
        stop.reserve_cents * 11 == stop.buyin_cents * 4,
    )

print("\nRule 4: selection must be exactly one of the five stops — no freeform, no interpolation")
for stop in ECONOMY_STOPS:
    _assert(f"stop {stop.weekly_min_cents} is a member of ECONOMY_STOPS", stop in ECONOMY_STOPS)

# A mistyped/freeform stop (interpolated halfway between stop 1 and stop 2)
# must fail validate_stop, and must not be findable via lookup.
_fake_stop = EconomyStop(weekly_min_cents=750, wallet_cents=10500, buyin_cents=16500, reserve_cents=6000)
raised_fake = False
try:
    validate_stop(_fake_stop)
except ValueError:
    raised_fake = True
_assert("an interpolated/freeform stop fails validate_stop (rule 4)", raised_fake)
_assert("find_stop_by_buyin_cents returns None for a freeform amount", find_stop_by_buyin_cents(16500) is None)

# A stop whose numbers satisfy rules 1/2 but violates the tight rule-3 ratio
# (this is the "not a 33-40% band check" case — reserve here is still inside
# a loose ~33-40% band of buyin but fails the EXACT 4:11 ratio).
_band_trap_stop = EconomyStop(weekly_min_cents=1000, wallet_cents=14000, buyin_cents=22500, reserve_cents=8500)
raised_band_trap = False
try:
    validate_stop(_band_trap_stop)
except ValueError:
    raised_band_trap = True
_assert("a stop that passes a loose 33-40% band but fails the exact 4:11 ratio is rejected", raised_band_trap)


print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
