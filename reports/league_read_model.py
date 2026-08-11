"""
reports/league_read_model.py — authoritative League and Week read models (S8-P4C-3).

READ-ONLY. Nothing here fetches from a provider, posts, locks or settles. It
reports what the provider gateway has already persisted, and says so plainly
when the gateway has persisted nothing.

THE ONE RULE THIS MODULE ENFORCES: a field is either sourced or it is
unresolved. There is no third state in which a plausible number is produced from
adjacent data. That rule is why several fields below return `None` rather than a
figure that could easily have been computed — see `season_record` and the
`ml`/`spread`/`over_under` note in `week_matchups`.

WHERE AUTHORITY COMES FROM, precisely:

  league identity      `leagues.name`, and `provider` / `provider_league_key`
                       say whether that name is the provider's or a local one.
  current week         `leagues.provider_current_week` — the provider's own
                       statement, persisted by providers/yahoo/persist.py.
                       NULL when no refresh has ever run.
  team identity        `teams.provider_team_key` (S6-R1). Never the name, never
                       the email — those are display, and the resolver refuses
                       to match on them.
  matchup + orientation `matchups.home_team_id` / `away_team_id`, written from
                       the canonically-oriented ProviderMatchup. Orientation is
                       derived from sorted team KEYS, so a provider that mirrors
                       a payload cannot reverse it.
  finality             `matchups.finalized_at`. A score is not final because it
                       stopped changing.
  season record        finalized matchups carrying a provider-declared winner,
                       and nothing else.

WHAT IS NOT HERE, AND WHY. There is no ML, spread or over/under. The gateway
captures no betting lines of any kind — the audit found only `player_points/
total`, which is a player's fantasy points — and the illustrative fixture
manufactured all three from projections (`spread = opponentFigure -
subjectFigure`). Deriving them here would launder a prototype trick into the
production read model.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import or_
from sqlalchemy.orm import Session

from db.schema import League, Matchup, Team

# ── Provider state ────────────────────────────────────────────────────────────

#: The league is bound to a provider AND that provider has stated a week.
PROVIDER_BOUND = "bound"
#: The league is bound to a provider but no refresh has stated anything yet.
PROVIDER_PENDING = "pending"
#: The league has no provider identity at all — a local or fixture league.
PROVIDER_ABSENT = "absent"


class LeagueReadError(RuntimeError):
    """The League state cannot be derived. Never a fallback to illustrative data."""


@dataclass(frozen=True)
class LeagueContext:
    """Who the acting GM is, where, and when — all from persisted state."""

    league_id: int
    league_name: str
    season: int

    #: The provider's own current week, or None. NONE IS AN ANSWER: it means no
    #: refresh has stated one, and every surface renders that as unresolved
    #: rather than substituting a number.
    current_week: Optional[int]

    provider: Optional[str]
    provider_league_key: Optional[str]
    provider_state: str

    acting_team_id: int
    acting_team_name: str
    acting_team_owner: str
    #: S6-R1 identity. None for a team the provider has never named.
    acting_provider_team_key: Optional[str]

    season_final_week: Optional[int]
    playoff_start_week: Optional[int]

    @property
    def week_resolved(self) -> bool:
        return self.current_week is not None


@dataclass(frozen=True)
class SeasonRecord:
    """A team's W/L over matchups the provider actually decided.

    `resolved` is False when no finalized, winner-declared matchup exists — and
    then the counts are None rather than 0-0. "No games decided yet" and "played
    and won none" are different statements and must not render alike.
    """

    team_id: int
    wins: Optional[int]
    losses: Optional[int]
    ties: Optional[int]
    decided: int
    resolved: bool

    @property
    def label(self) -> Optional[str]:
        if not self.resolved:
            return None
        return f"{self.wins}–{self.losses}"


@dataclass(frozen=True)
class MatchupSide:
    team_id: int
    team_name: str
    owner: str
    provider_team_key: Optional[str]
    #: The provider's reported points. None where it reported none — never 0.0.
    points: Optional[float]
    is_acting_team: bool


@dataclass(frozen=True)
class WeekMatchup:
    """One provider-backed matchup, canonically oriented."""

    matchup_id: int
    week: int
    provider_matchup_key: Optional[str]
    home: MatchupSide
    away: MatchupSide

    #: FINALITY IS A TIMESTAMP, NOT AN INFERENCE. A matchup is final because the
    #: provider said so and `finalized_at` recorded when, not because its score
    #: stopped moving or its week is in the past.
    final: bool
    finalized_at: Optional[str]
    winner_team_id: Optional[int]
    refreshed_at: Optional[str]

    #: Whether the acting GM is in this matchup at all.
    involves_acting_team: bool

    @property
    def acting_side(self) -> Optional[str]:
        if self.home.is_acting_team:
            return "home"
        if self.away.is_acting_team:
            return "away"
        return None


@dataclass(frozen=True)
class WeekState:
    """Everything the Week tab may say about one league-week."""

    league_id: int
    week: int
    matchups: tuple[WeekMatchup, ...] = field(default_factory=tuple)
    #: True when the week has no persisted matchups. AN AUTHORITATIVE EMPTY —
    #: distinct from a failed read, which never reaches this type at all.
    empty: bool = True


# ── League context ────────────────────────────────────────────────────────────

def _provider_state(league: League) -> str:
    if not league.provider or not league.provider_league_key:
        return PROVIDER_ABSENT
    return (PROVIDER_BOUND if league.provider_current_week is not None
            else PROVIDER_PENDING)


def league_context(db: Session, *, team_id: int, league_id: int
                   ) -> LeagueContext:
    """The acting GM's league context.

    LEAGUE-SCOPED AND OWNERSHIP-CHECKED. A team outside the league is refused
    rather than reported on, for the same reason P2 closed that boundary
    everywhere else.
    """
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise LeagueReadError(f"League {league_id} does not exist.")

    team = db.query(Team).filter(Team.id == team_id).first()
    if team is None:
        raise LeagueReadError(f"Team {team_id} does not exist.")
    if team.league_id != league_id:
        raise LeagueReadError(
            f"Team {team_id} is not in league {league_id}; refusing to report "
            f"league context across a boundary.")

    return LeagueContext(
        league_id=league.id,
        league_name=league.name,
        season=league.season,
        current_week=league.provider_current_week,
        provider=league.provider,
        provider_league_key=league.provider_league_key,
        provider_state=_provider_state(league),
        acting_team_id=team.id,
        acting_team_name=team.team_name,
        acting_team_owner=team.owner,
        acting_provider_team_key=team.provider_team_key,
        season_final_week=league.season_final_week,
        playoff_start_week=league.playoff_start_week,
    )


# ── Season record ─────────────────────────────────────────────────────────────

def season_record(db: Session, *, team_id: int, league_id: int) -> SeasonRecord:
    """A team's W/L from DECIDED matchups only.

    TWO CONDITIONS, BOTH REQUIRED, and each rules out a different mistake:

      `finalized_at IS NOT NULL` — the provider declared the week over. Without
      it, a live Sunday matchup counts as a result the moment its score is
      ahead.

      `winner_team_id IS NOT NULL` — the provider declared a winner.
      `ProviderMatchup.winner_team_key` is explicitly "NEVER inferred from a
      score comparison", and this read model must not do at the far end what the
      gateway refused to do at the near one.

    THE EXISTING `_compute_standings` DOES NEITHER. It walks every matchup row
    and counts a LOSS whenever the team is not `winner_team_id` — so an unplayed
    week, where the winner is NULL, scores as a loss for both teams. It is also
    unscoped across leagues. That is exactly the "inferred wins/losses from
    incomplete local rows" this package was told not to bind, which is why this
    is a separate function rather than a reuse.
    """
    rows = (db.query(Matchup)
            .filter(Matchup.league_id == league_id,
                    Matchup.finalized_at.isnot(None),
                    Matchup.winner_team_id.isnot(None),
                    or_(Matchup.home_team_id == team_id,
                        Matchup.away_team_id == team_id))
            .all())

    if not rows:
        return SeasonRecord(team_id=team_id, wins=None, losses=None, ties=None,
                            decided=0, resolved=False)

    wins = sum(1 for m in rows if m.winner_team_id == team_id)
    # A TIE IS NOT A LOSS. The provider signals one by declaring a winner that
    # is neither side; counting those as losses would understate the team.
    ties = sum(1 for m in rows
               if m.winner_team_id not in (m.home_team_id, m.away_team_id))
    losses = len(rows) - wins - ties

    return SeasonRecord(team_id=team_id, wins=wins, losses=losses, ties=ties,
                        decided=len(rows), resolved=True)


# ── Week matchups ─────────────────────────────────────────────────────────────

def _side(team: Optional[Team], points, acting_team_id: int) -> MatchupSide:
    return MatchupSide(
        team_id=(team.id if team else 0),
        team_name=(team.team_name if team else "Unknown"),
        owner=(team.owner if team else ""),
        provider_team_key=(team.provider_team_key if team else None),
        # NONE, NOT 0.0. A provider that reported no score has not said the team
        # scored nothing, and `float(None or 0)` would turn silence into a fact.
        points=(float(points) if points is not None else None),
        is_acting_team=(bool(team) and team.id == acting_team_id),
    )


def week_matchups(db: Session, *, league_id: int, week: int,
                  acting_team_id: int) -> WeekState:
    """Every persisted matchup for one league-week.

    ORIENTATION IS READ, NEVER RECOMPUTED. `home_team_id` / `away_team_id` were
    written from a canonically-oriented `ProviderMatchup`, whose home side is
    the LOWER of the two provider team keys under the provider's own ordering —
    a rule that makes orientation a property of identity rather than of payload
    order. Re-deriving it here from anything else, including which side the
    acting GM is on, would reintroduce exactly the mirroring bug S6 §5 closed.
    """
    rows = (db.query(Matchup)
            .filter(Matchup.league_id == league_id, Matchup.week == week)
            .order_by(Matchup.id)
            .all())

    teams = {t.id: t for t in db.query(Team)
             .filter(Team.league_id == league_id).all()}

    matchups = tuple(
        WeekMatchup(
            matchup_id=m.id,
            week=m.week,
            provider_matchup_key=m.provider_matchup_key,
            home=_side(teams.get(m.home_team_id), m.home_score, acting_team_id),
            away=_side(teams.get(m.away_team_id), m.away_score, acting_team_id),
            final=m.finalized_at is not None,
            finalized_at=(m.finalized_at.isoformat() if m.finalized_at
                          else None),
            winner_team_id=m.winner_team_id,
            refreshed_at=(m.refreshed_at.isoformat() if m.refreshed_at
                          else None),
            involves_acting_team=acting_team_id in (m.home_team_id,
                                                    m.away_team_id),
        )
        for m in rows
    )

    return WeekState(league_id=league_id, week=week, matchups=matchups,
                     empty=not matchups)


def acting_matchup(state: WeekState) -> Optional[WeekMatchup]:
    """The acting GM's own matchup this week, if they have one.

    None is ordinary: a bye week, or a week the provider has not yet published.
    """
    for m in state.matchups:
        if m.involves_acting_team:
            return m
    return None
