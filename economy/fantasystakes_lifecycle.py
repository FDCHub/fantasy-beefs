"""
economy/fantasystakes_lifecycle.py — LIVE → FINAL → PAID (WP-8, Final POR §18).

WHAT §18 RETIMES. Under RC2 the FantasyStakes Championship FROZE at the playoff
boundary: the first governed postseason action snapshotted the regular-season
score, and every postseason result was excluded from the championship by
construction. The Final POR removes that boundary. FantasyStakes scoring runs
through the postseason, so the championship is decided by the whole season and
the pot is not knowable until the last contest resolves.

── THE THREE STATES, AND WHY THERE ARE ONLY THREE ──────────────────────────

    LIVE    scoring is still moving and the pot is still growing
    FINAL   every eligible contest is resolved; the pot is authoritative
    PAID    the pot has been distributed

There is deliberately no FROZEN state between LIVE and FINAL. FROZEN existed to
answer "what was the score at the boundary?", and under §18 there is no boundary
— the question has no referent. Keeping a fourth state that nothing could ever
enter would leave the retired model reachable by a future edit.

── EVERY STATE IS DERIVED, NONE IS STORED ─────────────────────────────────

The state is a function of posted state and nothing else: whether a distribution
event exists, and whether any eligible contest is unresolved. A stored status
column would be a second truth that could disagree with the ledger, and it is
precisely the kind of thing the RC2 freeze marker was — a durable row asserting a
snapshot that the live read model could contradict.

── WHY FINAL SPANS THE WHOLE SEASON ───────────────────────────────────────

`reports.championship_corrections.unresolved_eligible_contests` takes a cutoff
and asks about weeks BELOW it, because under RC2 only regular-season contests
were eligible. Under §18 every week is eligible, so this module passes a cutoff
ABOVE the last week the league actually played. That is the whole retiming,
expressed once: the same certified predicate — `Matchup.finalized_at` plus the
wager actually being settled — applied to a season-wide window instead of a
regular-season one.

The cutoff is DERIVED FROM THE DATA, not a literal. A hardcoded 18 would be a
second, quieter assumption about season length of exactly the kind §18 exists to
remove.

── THE POT IS AUTHORITATIVE AT FINALITY, NOT BEFORE ───────────────────────

`authoritative_pot_cents` refuses while the championship is LIVE. The
FantasyStakes pot GROWS during the season — WP-4 sweeps unspent Weekly Minimums
into it at every week close, WP-6 adds to it on every approved Top-Off, and WP-5
routes terminal Prop Pool remainders into it — so a figure read while contests
are still open is a running total, not a pot. Publishing one as authoritative is
how a league gets told it is playing for an amount that later changes.

`pot_cents` reads the same balance without the gate, for the display that
legitimately wants the running total. The two are separate functions so a caller
has to choose, rather than getting whichever the argument defaulted to.

── ERA ────────────────────────────────────────────────────────────────────

`RULESET_FINAL_POR` only. A legacy season's championship really did freeze at
the boundary, really was scored on the regular season alone, and in some cases
has already been paid on that basis. Reporting a legacy season through this
lifecycle would describe a competition that did not happen.
"""

from __future__ import annotations

from dataclasses import dataclass

from economy.economy_events import fantasystakes_championship_account
from ledger.ledger import _balance_of_in_session
from ruleset import is_final_por

#: Scoring is still moving; the pot is still growing.
LIFECYCLE_LIVE = "LIVE"
#: Every eligible contest is resolved. The pot balance is now authoritative.
LIFECYCLE_FINAL = "FINAL"
#: The pot has been distributed.
LIFECYCLE_PAID = "PAID"

LIFECYCLE_STATES: tuple[str, ...] = (LIFECYCLE_LIVE, LIFECYCLE_FINAL,
                                     LIFECYCLE_PAID)


class FantasyStakesLifecycleError(ValueError):
    """A lifecycle operation was refused, carrying a stable reason code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_WRONG_ERA = "FS_LIFECYCLE_WRONG_ERA"
REASON_NOT_FINAL = "FS_LIFECYCLE_NOT_FINAL"
REASON_LEAGUE_NOT_FOUND = "FS_LIFECYCLE_LEAGUE_NOT_FOUND"


@dataclass(frozen=True)
class LifecycleView:
    league_id: int
    season: int
    state: str
    #: The live balance. Authoritative only in FINAL and PAID.
    pot_cents: int
    #: Human-readable descriptions of what is still open. Empty in FINAL/PAID.
    blockers: tuple[str, ...]
    #: The season-wide window the finality question was asked over.
    weeks_considered: int

    @property
    def is_live(self) -> bool:
        return self.state == LIFECYCLE_LIVE

    @property
    def pot_is_authoritative(self) -> bool:
        return self.state in (LIFECYCLE_FINAL, LIFECYCLE_PAID)

    def as_dict(self) -> dict:
        return {
            "league_id": self.league_id,
            "season": self.season,
            "state": self.state,
            "pot_cents": self.pot_cents,
            "pot_is_authoritative": self.pot_is_authoritative,
            "blockers": list(self.blockers),
            "weeks_considered": self.weeks_considered,
        }


def _league(db, league_id: int):
    from db.schema import League

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise FantasyStakesLifecycleError(REASON_LEAGUE_NOT_FOUND,
                                          f"league {league_id} not found")
    return league


def _require_era(db, *, league_id: int, season: int) -> None:
    if not is_final_por(db, league_id=league_id, season=season):
        raise FantasyStakesLifecycleError(
            REASON_WRONG_ERA,
            f"league {league_id} season {season} is governed by the legacy "
            f"ruleset, whose FantasyStakes Championship froze at the playoff "
            f"boundary and was scored on the regular season alone. Reporting "
            f"it through the Final POR lifecycle would describe a competition "
            f"that did not happen.")


def season_wide_cutoff(db, *, league_id: int, season: int) -> int:
    """One past the last week this league actually played (WP-8).

    DERIVED, NOT A LITERAL. `unresolved_eligible_contests` asks about weeks
    BELOW a cutoff because RC2 only counted regular-season contests; §18 counts
    every week, so the cutoff has to sit above the last one. Hardcoding 18 would
    put a second, quieter assumption about season length into the code — which
    is the same class of assumption §18 exists to remove.

    Never below `playoff_start_week`: a league whose postseason has not been
    scheduled yet still has a postseason, and a cutoff under the boundary would
    silently re-impose the retired regular-season window.
    """
    from sqlalchemy import func

    from betting.pool_season_boundary import playoff_start_week
    from db.schema import BeefChallenge, Matchup, PoolInstance

    league = _league(db, league_id)
    db.flush()
    weeks = [
        db.query(func.max(Matchup.week))
        .filter(Matchup.league_id == league_id).scalar(),
        db.query(func.max(BeefChallenge.week))
        .filter(BeefChallenge.league_id == league_id).scalar(),
        db.query(func.max(PoolInstance.week))
        .filter(PoolInstance.league_id == league_id,
                PoolInstance.season == season).scalar(),
    ]
    played = max([int(w) for w in weeks if w is not None], default=0)
    return max(played + 1, int(playoff_start_week(league)))


def blockers(db, *, league_id: int, season: int | None = None) -> tuple[str, ...]:
    """What is still open, season-wide. Empty means FINAL is reachable."""
    from reports.championship_corrections import unresolved_eligible_contests

    league = _league(db, league_id)
    season = league.season if season is None else season
    return tuple(unresolved_eligible_contests(
        db, league_id=league_id, season=season,
        playoff_start_week=season_wide_cutoff(db, league_id=league_id,
                                              season=season)))


def is_paid(db, *, league_id: int, season: int) -> bool:
    """Whether the FantasyStakes pot has been distributed.

    Read from the RC2 distribution run row, which is the one durable record
    that a payment happened. WP-8 retimes WHEN the championship may pay; it does
    not introduce a second way of recording that it did.
    """
    from economy.fantasystakes_championship_settlement import (
        FantasyStakesChampionshipDistributionRun as Run,
    )

    return (db.query(Run)
            .filter(Run.league_id == league_id, Run.season == season)
            .count()) > 0


def pot_cents(db, *, league_id: int, season: int) -> int:
    """The live FantasyStakes Championship Pot balance. A RUNNING TOTAL.

    Correct for display at any time and NOT authoritative before FINAL — see
    `authoritative_pot_cents`, which is a separate function precisely so a
    caller has to choose which of the two it means.
    """
    db.flush()
    return _balance_of_in_session(
        db, fantasystakes_championship_account(league_id, season))


def lifecycle_state(db, *, league_id: int, season: int | None = None) -> str:
    """PAID, FINAL or LIVE — derived from posted state, never stored."""
    league = _league(db, league_id)
    season = league.season if season is None else season
    _require_era(db, league_id=league_id, season=season)

    if is_paid(db, league_id=league_id, season=season):
        return LIFECYCLE_PAID
    if blockers(db, league_id=league_id, season=season):
        return LIFECYCLE_LIVE
    return LIFECYCLE_FINAL


def view(db, *, league_id: int, season: int | None = None) -> LifecycleView:
    """Everything a reader needs about the lifecycle. Writes nothing."""
    league = _league(db, league_id)
    season = league.season if season is None else season
    _require_era(db, league_id=league_id, season=season)

    paid = is_paid(db, league_id=league_id, season=season)
    open_contests = () if paid else blockers(db, league_id=league_id,
                                             season=season)
    state = (LIFECYCLE_PAID if paid
             else LIFECYCLE_LIVE if open_contests
             else LIFECYCLE_FINAL)
    return LifecycleView(
        league_id=league_id, season=season, state=state,
        pot_cents=pot_cents(db, league_id=league_id, season=season),
        blockers=open_contests,
        weeks_considered=season_wide_cutoff(db, league_id=league_id,
                                            season=season) - 1)


def authoritative_pot_cents(db, *, league_id: int,
                            season: int | None = None) -> int:
    """The pot, refused while the championship is LIVE.

    The FantasyStakes pot GROWS all season — WP-4's week-close sweeps, WP-6's
    Top-Off additions, WP-5's terminal Pool remainders — so a figure read while
    contests are still open is a running total. Publishing one as authoritative
    is how a league gets told it is playing for an amount that later changes.
    """
    league = _league(db, league_id)
    season = league.season if season is None else season
    state = lifecycle_state(db, league_id=league_id, season=season)
    if state == LIFECYCLE_LIVE:
        raise FantasyStakesLifecycleError(
            REASON_NOT_FINAL,
            f"league {league_id} season {season} is {state}: "
            + "; ".join(blockers(db, league_id=league_id, season=season))
            + ". The FantasyStakes pot grows until the last contest resolves, "
              "so its balance is a running total and is not authoritative yet.")
    return pot_cents(db, league_id=league_id, season=season)
