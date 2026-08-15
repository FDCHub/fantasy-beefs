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
#
# ECONCFG-WP1D — WHAT THESE THREE INVARIANTS NOW GOVERN, AND WHAT THEY DO NOT.
# They validate the five historical constants above and nothing else. A
# CONFIGURED league-season never reaches `validate_stop`: its terms come from
# `resolve_allocation_terms` below, which derives them from the frozen
# commissioner configuration. In particular:
#
#     min_reserve == weekly_min * 14      RETIRED as universal economics.
#                                         The governing identity is now
#                                         min_reserve = w * frozen week count.
#     reserve * 11 == buyin * 4           RETIRED as universal economics. The
#                                         championship contribution is an
#                                         INDEPENDENT commissioner input, so no
#                                         fraction of the allocation defines it.
#
# They are kept here because the five legacy stops genuinely satisfy them and a
# mistyped historical constant should still fail loudly. They are emphatically
# not a compatibility helper that re-imposes the old ratios on a configured
# league — no configured path calls this function.
for _stop in ECONOMY_STOPS:
    validate_stop(_stop)


# ── ECONCFG-WP1D — the one place issuance amounts are decided ────────────────

TERMS_SOURCE_LEGACY_STOP = "LEGACY_STOP"
TERMS_SOURCE_FROZEN_CONFIG = "FROZEN_CONFIG"


class InconsistentEconomyStateError(ValueError):
    """A league-season's issuance basis cannot be established honestly."""


@dataclass(frozen=True)
class ResolvedAllocationTerms:
    """The exact per-player amounts one league-season will issue.

    ONE OBJECT, TWO SOURCES, ONE FORMULA EACH — and no third place where the
    arithmetic is repeated. `economy/season_allocation.py` consumes this and
    never asks where the numbers came from, which is what keeps the configured
    and legacy paths from drifting into two implementations of the same posting.

    THE THREE MONEY FIELDS DELIBERATELY KEEP THE LEGACY NAMES. `buyin_cents`,
    `min_reserve_cents` and `reserve_cents` are the columns `SeasonAllocation`
    has always snapshotted and the values the three-leg posting has always used.
    Renaming them here would have rippled into a durable schema and an API for
    no economic gain; `season_opening_allocation_cents` is exposed alongside
    `buyin_cents` so the CANONICAL PRODUCT TERM is available to any reader
    without a database column changing its meaning.
    """

    #: LEGACY_STOP or FROZEN_CONFIG. Carried so a caller — or an operator
    #: reading a refusal — can tell which regime priced a season without
    #: inferring it from the numbers.
    source: str

    buyin_cents: int
    min_reserve_cents: int
    reserve_cents: int

    #: Present only on the configured path; None for a legacy stop, whose
    #: amounts are constants rather than a formula.
    weekly_bet_minimum_cents: int | None = None
    regular_season_week_count: int | None = None
    championship_contribution_cents: int | None = None

    @property
    def season_opening_allocation_cents(self) -> int:
        """The canonical product term for `buyin_cents` (ECON-CONFIG-R6)."""
        return self.buyin_cents

    @property
    def is_configured(self) -> bool:
        return self.source == TERMS_SOURCE_FROZEN_CONFIG


def terms_from_stop(stop: EconomyStop) -> ResolvedAllocationTerms:
    """Legacy fixed-stop terms, for an unconfigured league-season."""
    return ResolvedAllocationTerms(
        source=TERMS_SOURCE_LEGACY_STOP,
        buyin_cents=stop.buyin_cents,
        min_reserve_cents=stop.min_reserve_cents,
        reserve_cents=stop.reserve_cents,
    )


def terms_from_frozen_config(frozen) -> ResolvedAllocationTerms:
    """Configured terms, derived from ONE frozen league-season row.

        min_reserve = weekly_bet_minimum x regular_season_week_count
        reserve     = championship_contribution
        allocation  = min_reserve + reserve

    THE FORMULA LIVES HERE AND NOWHERE ELSE. Zero-sum is true by construction —
    the allocation IS the sum of its two parts — so the three-leg posting stays
    balanced without anything recomputing or rounding it, exactly as the legacy
    invariant guaranteed for the fixed stops.
    """
    weeks = frozen.regular_season_week_count
    weekly = frozen.weekly_bet_minimum_cents
    championship = frozen.championship_contribution_cents
    if weeks is None or weeks <= 0:
        raise InconsistentEconomyStateError(
            f"frozen economy configuration for league {frozen.league_id} "
            f"season {frozen.season} carries regular_season_week_count="
            f"{weeks!r}; a frozen row must have derived it.")
    min_reserve = weekly * weeks
    return ResolvedAllocationTerms(
        source=TERMS_SOURCE_FROZEN_CONFIG,
        buyin_cents=min_reserve + championship,
        min_reserve_cents=min_reserve,
        reserve_cents=championship,
        weekly_bet_minimum_cents=weekly,
        regular_season_week_count=weeks,
        championship_contribution_cents=championship,
    )


def resolve_allocation_terms(db: Session, *, league_id: int,
                             season: int) -> ResolvedAllocationTerms:
    """The issuance basis for one league-season. Reads only.

    A FROZEN configuration wins; otherwise the legacy fixed stop applies. A
    DRAFT is never consulted — `read_frozen` returns only stamped rows, so no
    Credit can be posted from a configuration a commissioner may still edit.

    Callers that intend to issue must have frozen the configuration first;
    `activate_season_allocation` does exactly that, immediately before calling
    this.
    """
    from economy.league_economy_config import read_frozen

    frozen = read_frozen(db, league_id=league_id, season=season)
    if frozen is not None:
        return terms_from_frozen_config(frozen)
    return terms_from_stop(get_league_economy_stop(league_id, db))


def assert_consistent_configured_state(db: Session, *, league_id: int,
                                       season: int) -> bool:
    """Whether this league-season was issued under a frozen configuration.

    FAIL CLOSED ON A VANISHED CONFIGURATION (ECONCFG-WP1D §38). A season whose
    `SeasonAllocation` amounts match no certified legacy stop can only have come
    from a configured freeze. If its frozen row is then missing, the durable
    state is inconsistent — a row was deleted from an insert-only table — and
    substituting the legacy default would silently price the rest of the season
    on a basis it was never issued under. Refusing names the corruption instead.

    Returns True when a frozen row governs, False for a genuine legacy season.
    """
    from db.schema import SeasonAllocation
    from economy.league_economy_config import read_frozen

    if read_frozen(db, league_id=league_id, season=season) is not None:
        return True

    row = (db.query(SeasonAllocation)
           .filter(SeasonAllocation.league_id == league_id,
                   SeasonAllocation.season == season)
           .first())
    if row is None:
        return False
    if find_stop_by_buyin_cents(row.buyin_cents) is None:
        raise InconsistentEconomyStateError(
            f"league {league_id} season {season} was issued "
            f"{row.buyin_cents} cents per team, which matches no certified "
            f"legacy stop, yet no frozen economy configuration exists for it. "
            f"The configuration that priced this season is missing; refusing "
            f"to substitute the legacy default.")
    return False
