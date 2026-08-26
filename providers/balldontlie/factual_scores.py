"""Sprint 7B · FantasyStakes-computed weekly scores, into the existing writer.

THE GAP THIS CLOSES. Sprint 6 computes a factual lineup score
(`scoring/factual.score_factual_lineup`) and Sprint 6B reduces a pair of them
to the two floats settlement reads (`scoring/factual_grading.settlement_scores`).
Sprint 7 then proved, by scanning the tree, that no new writer of
`Matchup.home_score` had appeared — which was true, and which also meant those
two floats reached nothing. A league configured for BALLDONTLIE facts still
settled against whatever scores Yahoo had last written.

This module is the join, and it is deliberately the whole of the join: it reads
persisted factual components, scores each team's Yahoo-declared starting lineup
under the league's own CSPS profile, and rewrites the POINTS on the provider
matchup DTOs the existing refresh already carries.

── IT ADDS NO WRITER, AND THAT IS THE DESIGN CONSTRAINT ────────────────────

`providers/persist.py` and `demo/states.py` are the only two writers of
`Matchup.home_score` / `away_score`, and a certification gate scans the tree to
keep it that way. So this module writes nothing. It returns a `ProviderWeek`
whose matchups carry different NUMBERS, and the caller hands that to
`persist.refresh_league_week` — the same function, the same row-finding rule,
the same orientation, the same conflict handling. `Matchup.finalized_at` keeps
its single writer in `providers/finality.py` and is not touched here either.

── WHO OWNS WHAT, RESTATED WHERE IT IS EASIEST TO GET WRONG ────────────────

    YAHOO           the league, its teams, the schedule, which matchup is
                    which, and — crucially — WHO STARTED. The starting lineup
                    is read from the snapshot's roster entries and never
                    second-guessed.

    BALLDONTLIE     what each of those starters actually did.

    FANTASYSTAKES   what a league PAYS for it. That is CSPS under the league's
                    own certified profile, and it is why these scores are not
                    Yahoo's own and should not be: a Mr Whiskers league pays
                    -3.14 for a subject another profile pays nothing for.

So the score written here is a FantasyStakes score computed from BALLDONTLIE
evidence over a Yahoo lineup. Yahoo's own reported result is not overwritten in
any sense that matters to Yahoo — it remains what Yahoo's standings show — but
FantasyStakes markets grade on FantasyStakes scoring, which is the arrangement
`scoring/factual.py` was built to serve.

── INCOMPLETE EVIDENCE REFUSES THE WHOLE MATCHUP ───────────────────────────

A lineup holding one starter whose evidence never arrived is NOT READY, and a
matchup with one unready side is left with the points it already had rather
than half-rewritten. A settled wager cannot be unsettled because a kicker's
distances turned up on Wednesday, so the refusal is the safe direction and the
diagnostics name the subject.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

from betting.pool_subjects import NON_STARTER_SLOTS
from providers.balldontlie.factual_week import SubjectFacts
from providers.cross_identity import BALLDONTLIE
from scoring import factual as F

__all__ = ["persisted_subject_facts", "score_team_lineups",
           "rescore_snapshot", "ScoredWeek"]


class ScoredWeek:
    """One league-week's FantasyStakes scores, and everything that refused.

    Returned rather than logged: an operator asking why a matchup did not
    settle needs the subject and the cause, and a settlement path that swallows
    them leaves nobody able to answer.
    """

    def __init__(self) -> None:
        #: team_key -> `LineupScore`
        self.lineups: dict = {}
        #: matchup_key -> (home_points, away_points), only where BOTH sides
        #: are READY. A matchup absent from here was not rewritten.
        self.matchup_points: dict = {}
        #: Human-readable causes, one per unready lineup.
        self.refusals: list = []
        self.subjects_read = 0

    @property
    def ready_matchups(self) -> int:
        return len(self.matchup_points)

    def as_dict(self) -> dict:
        return {"lineups": sorted(self.lineups),
                "matchups_scored": sorted(self.matchup_points),
                "refusals": list(self.refusals),
                "subjects_read": self.subjects_read}


def persisted_subject_facts(db, *, season: int, week: int) -> dict:
    """`{provider_player_key: SubjectFacts}` from the persisted factual rows.

    NO NETWORK. These are the `provider_component_projection` rows a factual
    refresh already wrote under `source_kind="fantasy/weekly_stats"`; a Tuesday
    settlement must not depend on BALLDONTLIE answering on Tuesday, and a
    replay of a settled week must reproduce it from evidence rather than from a
    fresh fetch that may no longer agree.

    THE NEWEST OBSERVATION PER SUBJECT WINS, which is `select_week`'s rule and
    `factual_week_from_components`'s rule. Three readers of one corpus applying
    three selection rules would be three answers.
    """
    from db.schema import ProviderComponentProjection as PCP

    rows = (db.query(PCP)
            .filter(PCP.provider == BALLDONTLIE,
                    PCP.season == int(season),
                    PCP.week == int(week),
                    PCP.source_kind == PCP.SOURCE_WEEKLY_STATS)
            .order_by(PCP.observed_at.asc(), PCP.id.asc())
            .all())

    facts: dict = {}
    for row in rows:
        facts[row.provider_player_key] = SubjectFacts(
            provider_player_key=row.provider_player_key,
            position=row.position, nfl_team=row.nfl_team,
            provider_game_id=row.provider_game_id,
            components=dict(row.components or {}),
            components_present=tuple(row.components_present or ()),
            # NO DIAGNOSTIC IS INVENTED HERE. A row only exists because the
            # factual ingest judged the subject complete enough to store; a
            # subject that refused at ingest has no row, and a starter pointing
            # at a missing row is refused by `score_factual_lineup` as
            # MISSING_FINAL_STATS. The absence carries the meaning.
            diagnostics=[])
    return facts


def _starters_by_team(roster_entries: Sequence) -> dict:
    """Yahoo's starting lineups, by team key. Bench and IR never cross.

    `slot` is the provider's SELECTED position for the week, which is the only
    field permitted to decide started-or-benched. `NON_STARTER_SLOTS` is the
    governed set the Pool census already uses, reused here so a starter is the
    same thing in both places.
    """
    by_team: dict = {}
    for entry in roster_entries:
        slot = (getattr(entry, "slot", None) or "").strip().upper()
        if slot in NON_STARTER_SLOTS:
            continue
        by_team.setdefault(entry.team_key, []).append(entry)
    return by_team


def score_team_lineups(db, *, snapshot, season: int, week: int, profile,
                       facts: Mapping[str, Any] | None = None) -> ScoredWeek:
    """Score every team's Yahoo starting lineup from persisted BALLDONTLIE facts.

    ONE READ OF THE EVIDENCE FOR THE WHOLE LEAGUE. The facts are fetched once
    and scored in memory, so a twelve-team week costs one query rather than one
    per team — the same shape `sim_v2.build_lineup` uses on the pricing side,
    and for the same reason.
    """
    out = ScoredWeek()
    subject_facts = (dict(facts) if facts is not None
                     else persisted_subject_facts(db, season=season, week=week))
    out.subjects_read = len(subject_facts)

    for team_key, entries in sorted(_starters_by_team(
            snapshot.roster_entries).items()):
        starters = [{"provider_player_key": e.player_key,
                     "position": (getattr(e, "slot", None) or ""),
                     "name": getattr(e, "name", None),
                     "player_id": getattr(e, "player_id", None)}
                    for e in entries]
        score = F.score_factual_lineup(
            starters=starters, facts=subject_facts, profile=profile,
            season=int(season), week=int(week), team_name=team_key)
        out.lineups[team_key] = score
        if score.readiness != F.Readiness.READY:
            out.refusals.append(
                f"{team_key}: {'; '.join(score.diagnostics) or 'NOT_READY'}")
    return out


def rescore_snapshot(db, *, snapshot, season: int, week: int, profile,
                     facts: Mapping[str, Any] | None = None):
    """The snapshot, with FantasyStakes points on every fully-evidenced matchup.

    RETURNS A SNAPSHOT; WRITES NOTHING. The caller passes the result to
    `providers.persist.refresh_league_week`, which is the certified writer of
    `Matchup.home_score`. Keeping the composition and the write apart is what
    lets the C-7 scan keep finding exactly two score writers in this tree.

    A MATCHUP WHOSE EVIDENCE IS INCOMPLETE IS CARRIED THROUGH UNCHANGED, not
    zeroed and not dropped. Dropping it would delete a scheduled fixture from
    the refresh; zeroing it would state a result. Leaving it is the only option
    that says nothing, and `ScoredWeek.refusals` says why out loud.

    :returns: `(ProviderWeek, ScoredWeek)`
    """
    scored = score_team_lineups(db, snapshot=snapshot, season=season,
                                week=week, profile=profile, facts=facts)

    rewritten = []
    for matchup in snapshot.matchups:
        home = scored.lineups.get(matchup.home_team_key)
        away = scored.lineups.get(matchup.away_team_key)
        if (home is None or away is None
                or home.readiness != F.Readiness.READY
                or away.readiness != F.Readiness.READY):
            rewritten.append(matchup)
            continue
        home_points, away_points = _settlement_scores(home, away)
        scored.matchup_points[matchup.matchup_key] = (home_points, away_points)
        # `replace` keeps the identity, the week, the orientation, the finality
        # and the declared winner exactly as the provider stated them. Only the
        # two point values move, which is the whole of this module's authority.
        rewritten.append(replace(matchup, home_points=home_points,
                                 away_points=away_points))

    return replace(snapshot, matchups=tuple(rewritten)), scored


def _settlement_scores(home, away):
    """Sprint 6B's reduction, called rather than repeated."""
    from scoring.factual_grading import settlement_scores

    return settlement_scores(home, away)
