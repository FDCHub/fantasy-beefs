"""
reports/weekly_skunk.py — the weekly Skunk result, for reading (WP6A).

WHY A READ MODEL EXISTS AT ALL. `economy/skunk.py` DECIDES the Skunk and records
the money; it returns a `SkunkAssessment` to its caller and persists an
`EconomyEvent` plus a ledger posting. What it does not carry is the material a
surface needs to say WHAT HAPPENED: who was skunked, by whom, at what scores and
by what margin. Those live in the finalized `Matchup` rows the engine read.

THIS MODULE DECIDES NOTHING. The economic decision is the `EconomyEvent` — it
exists or it does not, and it carries the amount. This module reads that event
and, only when it exists, names the teams and scores behind it. The selection is
`determine_skunk_losers` — the ENGINE'S OWN selector, called rather than
reimplemented — so there is exactly one definition of "who was skunked" in the
product and a surface cannot drift from the money.

WHY NOT PERSIST A SEPARATE SKUNK RESULT ROW. Every field below is already stored:
the decision in `economy_event`, the teams and scores in `matchups`. A second
copy would be a second source of truth for the same fact, and the day the two
disagreed there would be no way to tell which was right. The brief asks for no
redundant state unless necessary, and none is necessary here.

SCORES ARE PASSED THROUGH, NOT ROUNDED. FantasyStakes scores are fractional and
the margin is the product's headline number, so the float the provider stated is
what is reported. Presentation decides decimal places; this does not.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkunkEntry:
    """One skunked GM, with the matchup that skunked them."""
    team_id:            int
    team_name:          str
    score:              float
    opponent_team_id:   int
    opponent_team_name: str
    opponent_score:     float
    margin:             float
    cents:              int


@dataclass(frozen=True)
class WeeklySkunkResult:
    league_id:      int
    season:         int
    week:           int
    #: True when this league-week has been assessed at all. False means Week
    #: Close has not run for it — NOT that nobody was skunked.
    assessed:       bool
    #: ASSESSED, NO_LOSER, or None when `assessed` is False.
    classification: str | None
    amount_cents:   int
    assessed_at:    str | None
    entries:        tuple[SkunkEntry, ...]


def weekly_skunk_result(db, *, league_id: int, week: int) -> WeeklySkunkResult:
    """The persisted Skunk outcome for one league-week.

    Returns `assessed=False` when no assessment event exists. That is a real and
    ordinary state — the week has not been closed yet — and is reported as such
    rather than as an empty result, because "nobody was skunked" and "nobody has
    looked yet" are different facts and a surface must not conflate them.
    """
    from db.schema import EconomyEvent, League, Matchup, Team
    from economy.economy_events import EVENT_SKUNK_ASSESSMENT, league_week_key
    from economy.skunk import (
        CLASSIFICATION_ASSESSED, CLASSIFICATION_NO_LOSER, SkunkError,
        determine_skunk_losers, split_by_canonical_id,
    )

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise ValueError(f"league {league_id} not found")
    season = league.season

    event = (db.query(EconomyEvent)
             .filter(EconomyEvent.event_key
                     == league_week_key(EVENT_SKUNK_ASSESSMENT, league_id,
                                        season, week))
             .first())

    if event is None:
        return WeeklySkunkResult(
            league_id=league_id, season=season, week=week, assessed=False,
            classification=None, amount_cents=0, assessed_at=None, entries=())

    amount = int(event.amount_cents or 0)
    assessed_at = event.created_at.isoformat() if event.created_at else None

    # A ZERO-AMOUNT EVENT IS THE NO_LOSER OUTCOME — every matchup tied. The
    # event exists so the week is closed and a retry is a no-op; no money moved.
    if amount == 0:
        return WeeklySkunkResult(
            league_id=league_id, season=season, week=week, assessed=True,
            classification=CLASSIFICATION_NO_LOSER, amount_cents=0,
            assessed_at=assessed_at, entries=())

    # THE ENGINE'S OWN SELECTOR. Re-running it over the same finalized rows
    # reproduces the selection the assessment was made from; it is not a second
    # opinion, because it is the same function. If the rows have somehow ceased
    # to be final since, the money still stands and the presentation degrades to
    # the event alone rather than guessing.
    try:
        loser_ids, margin = determine_skunk_losers(db, league_id=league_id,
                                                   week=week)
    except SkunkError:
        return WeeklySkunkResult(
            league_id=league_id, season=season, week=week, assessed=True,
            classification=CLASSIFICATION_ASSESSED, amount_cents=amount,
            assessed_at=assessed_at, entries=())

    if not loser_ids or margin is None:
        return WeeklySkunkResult(
            league_id=league_id, season=season, week=week, assessed=True,
            classification=CLASSIFICATION_ASSESSED, amount_cents=amount,
            assessed_at=assessed_at, entries=())

    # The same canonical split the engine applied, so a tie reports each GM's
    # actual share rather than the whole contribution against each of them.
    allocation = split_by_canonical_id(amount, loser_ids)

    matchups = (db.query(Matchup)
                .filter(Matchup.league_id == league_id, Matchup.week == week)
                .order_by(Matchup.id).all())
    names = {t.id: t.team_name for t in
             db.query(Team).filter(Team.league_id == league_id).all()}

    entries: list[SkunkEntry] = []
    for team_id in loser_ids:
        found = next((m for m in matchups
                      if team_id in (m.home_team_id, m.away_team_id)), None)
        if found is None:
            continue
        is_home = found.home_team_id == team_id
        score = found.home_score if is_home else found.away_score
        opponent_id = found.away_team_id if is_home else found.home_team_id
        opponent_score = found.away_score if is_home else found.home_score
        entries.append(SkunkEntry(
            team_id=team_id,
            team_name=names.get(team_id, f"Team {team_id}"),
            score=score,
            opponent_team_id=opponent_id,
            opponent_team_name=names.get(opponent_id, f"Team {opponent_id}"),
            opponent_score=opponent_score,
            # THE MARGIN IS THIS MATCHUP'S OWN, not the week's headline figure
            # copied onto every tied row. They are equal by construction — the
            # losers ARE the teams whose margin equals the largest — and
            # computing it from the pair keeps each row internally consistent
            # with the two scores printed beside it.
            margin=abs(found.home_score - found.away_score),
            cents=allocation.get(team_id, 0),
        ))

    return WeeklySkunkResult(
        league_id=league_id, season=season, week=week, assessed=True,
        classification=CLASSIFICATION_ASSESSED, amount_cents=amount,
        assessed_at=assessed_at, entries=tuple(entries))