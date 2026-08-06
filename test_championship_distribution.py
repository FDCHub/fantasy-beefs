"""
test_championship_distribution.py — Finding 5.2-3 Option A, the accepted
championship distribution rule.

THE RULE UNDER TEST
  1. Each ordinary amount is floor(total_cents * pct / 100).
  2. The entire remainder after flooring every place goes to FIRST PLACE.
  3. sum(amount_cents) == total_cents for every valid input.

This is a PURE-FUNCTION suite. No database, no session, no ledger, no network,
no temp files. championship_distribution() computes and returns; it settles
nothing, and this file asserts nothing about settlement.

A NOTE ON THE TEST MATRIX, STATED ACCURATELY
  ECONOMY_STOPS DOES NOT DEFINE PAYOUT SPLITS. Each EconomyStop carries only
  weekly_min_cents, wallet_cents, buyin_cents and reserve_cents — there is no
  split field on it. The only payout splits present in the codebase are
  DEFAULT_PAYOUT_SPLIT = [60, 30, 10] in reports/standings.py and the
  LeagueTreasury.payout_split_json column, whose schema default is the same
  [60,30,10].

  So the stop-derived matrix below is built honestly: each stop's reserve_cents
  is used as a per-team championship contribution, scaled to realistic league
  sizes to produce pot totals, and each pot is distributed with the accepted
  [60,30,10] split. The stops supply TOTALS, not splits.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from economy.championship import championship_distribution
from payments.economy_config import ECONOMY_STOPS
from reports.standings import DEFAULT_PAYOUT_SPLIT

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        _failures.append(label)


def _assert_raises(label: str, fn, *args) -> None:
    try:
        fn(*args)
    except ValueError as e:
        _assert(label, True, f"ValueError: {str(e)[:70]}")
        return
    except Exception as e:                      # wrong exception type is a failure
        _assert(label, False, f"raised {type(e).__name__}, expected ValueError")
        return
    _assert(label, False, "no exception raised")


def _check_valid(label: str, total: int, split: list[int], order: list[int]) -> None:
    """Every universal property the ruling requires, asserted on one case."""
    rows = championship_distribution(total, split, order)

    _assert(f"{label}: one row per place", len(rows) == len(split), f"got {len(rows)}")
    _assert(f"{label}: places are 1..n in order",
            [p for p, _, _, _ in rows] == list(range(1, len(split) + 1)),
            f"got {[p for p, _, _, _ in rows]}")
    _assert(f"{label}: team ids follow `order` exactly",
            [t for _, t, _, _ in rows] == list(order),
            f"got {[t for _, t, _, _ in rows]}")
    _assert(f"{label}: percentages match `split` exactly",
            [pc for _, _, pc, _ in rows] == list(split),
            f"got {[pc for _, _, pc, _ in rows]}")

    amounts = [a for _, _, _, a in rows]
    _assert(f"{label}: every amount is an int (not bool/float)",
            all(isinstance(a, int) and not isinstance(a, bool) for a in amounts))
    _assert(f"{label}: every amount is non-negative", all(a >= 0 for a in amounts),
            f"got {amounts}")
    _assert(f"{label}: distributed total == total_cents exactly",
            sum(amounts) == total, f"sum={sum(amounts)} total={total}")

    base = [total * pc // 100 for pc in split]
    remainder = total - sum(base)
    _assert(f"{label}: first place == floor share + ENTIRE remainder",
            amounts[0] == base[0] + remainder,
            f"got {amounts[0]}, expected {base[0]}+{remainder}")
    _assert(f"{label}: no non-first place received any remainder",
            amounts[1:] == base[1:], f"got {amounts[1:]}, expected {base[1:]}")


# ── VALID CASES ──────────────────────────────────────────────────────────────

print("\nItem 1: evenly divisible total, three-place [60, 30, 10]")
_check_valid("even/3-place", 100000, [60, 30, 10], [11, 22, 33])
rows = championship_distribution(100000, [60, 30, 10], [11, 22, 33])
_assert("even split leaves zero remainder — first place is exactly its floor share",
        rows[0][3] == 60000, f"got {rows[0][3]}")

print("\nItem 2: one leftover cent")
_check_valid("one-cent-remainder", 100001, [60, 30, 10], [11, 22, 33])
rows = championship_distribution(100001, [60, 30, 10], [11, 22, 33])
_assert("the single leftover cent went to first place",
        (rows[0][3], rows[1][3], rows[2][3]) == (60001, 30000, 10000),
        f"got {(rows[0][3], rows[1][3], rows[2][3])}")

print("\nItem 3: multiple leftover cents")
# 100 * 1/3 style: 34/33/33 of 100 -> floors 34,33,33 = 100 (no remainder), so
# use a total that genuinely strands several cents across three places.
_check_valid("multi-cent-remainder", 99998, [60, 30, 10], [11, 22, 33])
rows = championship_distribution(99998, [60, 30, 10], [11, 22, 33])
base = [99998 * p // 100 for p in (60, 30, 10)]
_assert("multiple stranded cents all landed on first place",
        rows[0][3] - base[0] == 99998 - sum(base) and 99998 - sum(base) >= 2,
        f"remainder={99998 - sum(base)} firstDelta={rows[0][3] - base[0]}")

print("\nItem 4: one-cent total")
_check_valid("one-cent-total", 1, [60, 30, 10], [11, 22, 33])
rows = championship_distribution(1, [60, 30, 10], [11, 22, 33])
_assert("the only cent goes to first place, others zero",
        (rows[0][3], rows[1][3], rows[2][3]) == (1, 0, 0),
        f"got {(rows[0][3], rows[1][3], rows[2][3])}")

print("\nItem 5: zero total")
_check_valid("zero-total", 0, [60, 30, 10], [11, 22, 33])
rows = championship_distribution(0, [60, 30, 10], [11, 22, 33])
_assert("an empty pot distributes all zeros, not an error",
        [a for *_, a in rows] == [0, 0, 0], f"got {[a for *_, a in rows]}")

print("\nItem 6: single place, [100]")
_check_valid("single-place", 123457, [100], [99])
rows = championship_distribution(123457, [100], [99])
_assert("sole winner takes the entire pot including any remainder",
        rows == [(1, 99, 100, 123457)], f"got {rows}")

print("\nItem 7: large integer total (no float precision loss)")
_LARGE = 10**12 + 7          # far beyond float's exact-integer range for cents math
_check_valid("large-total", _LARGE, [60, 30, 10], [11, 22, 33])
rows = championship_distribution(_LARGE, [60, 30, 10], [11, 22, 33])
_assert("large-total distribution is exact to the cent",
        sum(a for *_, a in rows) == _LARGE, f"sum={sum(a for *_, a in rows)}")

print("\nItem 8: the accepted split is the one in configuration")
_assert("DEFAULT_PAYOUT_SPLIT is [60, 30, 10]", DEFAULT_PAYOUT_SPLIT == [60, 30, 10],
        f"got {DEFAULT_PAYOUT_SPLIT}")
_assert("DEFAULT_PAYOUT_SPLIT sums to 100", sum(DEFAULT_PAYOUT_SPLIT) == 100)

print("\nItem 9: ECONOMY_STOPS supplies TOTALS, not splits")
_stop_fields = set(vars(ECONOMY_STOPS[0]).keys())
_assert("no EconomyStop carries a payout split field",
        not any("split" in f.lower() or "payout" in f.lower() for f in _stop_fields),
        f"fields={sorted(_stop_fields)}")
_assert("there are five economy stops", len(ECONOMY_STOPS) == 5, f"got {len(ECONOMY_STOPS)}")

print("\nItem 10: every economy stop's reserve total x the accepted [60,30,10] split")
for stop in ECONOMY_STOPS:
    for team_count in (1, 3, 10, 12):
        pot = stop.reserve_cents * team_count
        _check_valid(
            f"stop wm={stop.weekly_min_cents} x{team_count} teams (pot={pot})",
            pot, DEFAULT_PAYOUT_SPLIT, [101, 102, 103],
        )

print("\nItem 11: exhaustive sweep — sum always equals the pot")
_sweep_ok = True
_sweep_first_only = True
for total in range(0, 2000):
    for sp in ([60, 30, 10], [100], [50, 50], [34, 33, 33], [70, 20, 10]):
        rs = championship_distribution(total, sp, list(range(1, len(sp) + 1)))
        amts = [a for *_, a in rs]
        if sum(amts) != total:
            _sweep_ok = False
        b = [total * p // 100 for p in sp]
        if amts[1:] != b[1:]:
            _sweep_first_only = False
_assert("sum == total for 2000 totals x 5 splits (10,000 cases)", _sweep_ok)
_assert("remainder never touched a non-first place across all 10,000 cases", _sweep_first_only)


# ── INVALID INPUT ────────────────────────────────────────────────────────────

print("\nItem 12: invalid input is rejected, never silently normalised")

_assert_raises("split does not sum to 100 (sums to 90)",
               championship_distribution, 1000, [60, 30], [1, 2])
_assert_raises("split does not sum to 100 (sums to 110)",
               championship_distribution, 1000, [60, 30, 20], [1, 2, 3])
_assert_raises("empty split", championship_distribution, 1000, [], [])
_assert_raises("empty order", championship_distribution, 1000, [100], [])
_assert_raises("length mismatch: 3 pcts, 2 teams",
               championship_distribution, 1000, [60, 30, 10], [1, 2])
_assert_raises("length mismatch: 2 pcts, 3 teams",
               championship_distribution, 1000, [50, 50], [1, 2, 3])
_assert_raises("duplicate team ids", championship_distribution, 1000, [60, 30, 10], [7, 7, 9])
_assert_raises("negative total", championship_distribution, -1, [100], [1])
_assert_raises("negative split entry",
               championship_distribution, 1000, [120, -20], [1, 2])
_assert_raises("non-integer total (float)", championship_distribution, 100.5, [100], [1])
_assert_raises("non-integer total (str)", championship_distribution, "1000", [100], [1])
_assert_raises("non-integer split entry (float)",
               championship_distribution, 1000, [60.0, 30, 10], [1, 2, 3])
_assert_raises("non-integer team id (str)",
               championship_distribution, 1000, [100], ["7"])
_assert_raises("non-integer team id (float)",
               championship_distribution, 1000, [100], [7.0])

print("\nItem 13: bool is rejected as an integer (bool is an int subclass)")
_assert_raises("bool total rejected", championship_distribution, True, [100], [1])
_assert_raises("bool split entry rejected",
               championship_distribution, 1000, [True, 99], [1, 2])
_assert_raises("bool team id rejected", championship_distribution, 1000, [100], [True])

print("\nItem 14: the function is pure — no db/session/ledger imports reachable")
import inspect
_src = inspect.getsource(championship_distribution)
for _bad in ("db.", "Session", "query(", "ledger_post", "balance_of", "stripe", "commit("):
    _assert(f"function body contains no {_bad!r}", _bad not in _src)


# ── Summary ──────────────────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
