"""Sprint 6 · a FantasyStakes-computed factual lineup score, and when it may settle.

WHERE THIS SITS. Yahoo says who started; BALLDONTLIE says what they did; CSPS
says what a league pays for it. This module is the join, and it is deliberately
the whole of the join — it computes a number and a readiness verdict, and it
posts nothing, settles nothing and knows nothing about money.

── WHY THIS IS NOT THE SETTLEMENT ENGINE ───────────────────────────────────

`betting/settlement_engine.py` grades markets and `ledger/ledger.py` moves
credits, both certified. Sprint 6 adds a factual score those existing engines
can consume; it does not add a second one. The boundary is the one the
repository already draws: FACTUAL GRADING answers "who won?", SETTLEMENT
answers "what happens economically?". Nothing here imports `ledger`, `economy`
or `betting`.

── FINALITY IS NOT THIS MODULE'S TO DECLARE ────────────────────────────────

`Matchup.finalized_at` has exactly one writer, `providers/finality.py`, and a
certification gate scans the tree to keep it that way. This module never writes
it and never infers it. What it produces is EVIDENCE READINESS — whether the
facts are complete enough to grade — which is a different question from whether
the week is economically final, and the settlement path requires both.

── INCOMPLETE EVIDENCE IS NOT A SMALL SCORE ────────────────────────────────

A lineup holding one subject whose evidence never arrived does not score that
subject as zero and carry on. It reports NOT READY and names the subject and
the reason. A missing kicker is worth between -3.14 and about 20 points in the
leagues this product actually serves, and a settled wager cannot be unsettled
because the evidence turned up later.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from scoring import csps as C

__all__ = ["StarterScore", "LineupScore", "score_factual_lineup",
           "lineup_fingerprint", "Readiness"]


class Readiness:
    """Whether the FACTS are complete enough to grade. Not whether money moves."""

    READY = "READY"
    NOT_READY = "NOT_READY"


@dataclass
class StarterScore:
    """One Yahoo starter, scored from BALLDONTLIE facts under one league's rules."""

    provider_player_key: str | None
    player_id: Any = None
    name: str | None = None
    position: str | None = None
    points: float = 0.0
    status: str = ""
    diagnostics: list = field(default_factory=list)
    contributions: list = field(default_factory=list)
    evidence_fingerprint: str | None = None

    @property
    def scoreable(self) -> bool:
        return not self.diagnostics and self.status in (
            C.ResultStatus.COMPLETE_DIRECT,
            C.ResultStatus.COMPLETE_WITH_MODELLED_COMPONENTS)

    def as_dict(self) -> dict:
        return {"provider_player_key": self.provider_player_key,
                "player_id": self.player_id, "name": self.name,
                "position": self.position, "points": self.points,
                "status": self.status, "diagnostics": list(self.diagnostics),
                "evidence_fingerprint": self.evidence_fingerprint}


@dataclass
class LineupScore:
    """A whole starting lineup, and whether its evidence supports grading."""

    team_id: Any
    team_name: str | None
    season: int
    week: int
    profile_id: str
    profile_version: str
    starters: list = field(default_factory=list)
    readiness: str = Readiness.NOT_READY
    diagnostics: list = field(default_factory=list)

    @property
    def points(self) -> float:
        return round(sum(s.points for s in self.starters), 6)

    @property
    def ready(self) -> bool:
        return self.readiness == Readiness.READY

    def as_dict(self) -> dict:
        return {"team_id": self.team_id, "team_name": self.team_name,
                "season": self.season, "week": self.week,
                "profile_id": self.profile_id,
                "profile_version": self.profile_version,
                "points": self.points, "readiness": self.readiness,
                "diagnostics": list(self.diagnostics),
                "starters": [s.as_dict() for s in self.starters]}


def lineup_fingerprint(lineup: LineupScore) -> str:
    """Deterministic identity of the EVIDENCE behind one lineup score.

    Covers each starter's evidence digest and the rules version applied, so a
    replay from the same stored rows reproduces it and a provider correction to
    any single starter changes it. It does not cover when anything was fetched.
    """
    payload = {
        "season": lineup.season, "week": lineup.week,
        "profile_id": lineup.profile_id,
        "profile_version": lineup.profile_version,
        "csps_version": C.CSPS_VERSION,
        "starters": sorted(
            (s.provider_player_key or "", s.evidence_fingerprint or "",
             repr(round(s.points, 6)))
            for s in lineup.starters),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def score_factual_lineup(*, starters: Sequence, facts: Mapping[str, Any],
                         profile, season: int, week: int,
                         team_id: Any = None, team_name: str | None = None,
                         evidence_fingerprints: Mapping[str, str] | None = None
                         ) -> LineupScore:
    """Yahoo starters + BALLDONTLIE facts -> one league-specific lineup score.

    `starters` is a sequence of objects or mappings carrying at least
    `provider_player_key` and `position`; `facts` maps that key to a
    `SubjectFacts`. A starter with no key, no facts, or incomplete facts makes
    the LINEUP not ready — it does not quietly score zero.

    ONLY STARTERS COUNT. The caller supplies the starting lineup Yahoo
    recorded; a bench player never reaches this function, because Yahoo's slot
    is the authority on who was started and this module does not second-guess
    it.
    """
    fingerprints = dict(evidence_fingerprints or {})
    out = LineupScore(team_id=team_id, team_name=team_name, season=season,
                      week=week, profile_id=profile.profile_id,
                      profile_version=profile.version)

    for starter in starters:
        get = (starter.get if isinstance(starter, Mapping)
               else lambda k, d=None: getattr(starter, k, d))
        key = get("provider_player_key")
        position = get("position")
        name = get("name")
        player_id = get("player_id")

        line = StarterScore(provider_player_key=key, player_id=player_id,
                            name=name, position=position)

        if not key:
            line.diagnostics.append("MISSING_PLAYER_IDENTITY")
            line.status = C.ResultStatus.REFUSED
            out.starters.append(line)
            continue

        subject = facts.get(key)
        if subject is None:
            line.diagnostics.append("MISSING_FINAL_STATS")
            line.status = C.ResultStatus.REFUSED
            out.starters.append(line)
            continue

        subject_diagnostics = list(getattr(subject, "diagnostics", ()) or ())
        if subject_diagnostics:
            line.diagnostics.extend(subject_diagnostics)
            line.status = C.ResultStatus.REFUSED
            line.evidence_fingerprint = fingerprints.get(key)
            out.starters.append(line)
            continue

        result = C.score_components(
            getattr(subject, "components", {}) or {}, profile,
            mode=C.FACTUAL,
            components_present=list(getattr(subject, "components_present", ())
                                    or ()),
            position=position)
        line.points = float(result.points)
        line.status = result.status
        line.contributions = list(result.contributions)
        line.evidence_fingerprint = fingerprints.get(key)
        if result.status == C.ResultStatus.REFUSED:
            line.diagnostics.append("UNRESOLVED_SCORING_RULE")
        out.starters.append(line)

    unready = [s for s in out.starters if not s.scoreable]
    if unready:
        out.readiness = Readiness.NOT_READY
        for s in unready:
            out.diagnostics.append(
                f"{s.name or s.provider_player_key or '?'}: "
                f"{','.join(s.diagnostics) or s.status}")
    else:
        out.readiness = Readiness.READY
    return out


def settlement_eligible(lineups: Sequence[LineupScore], *,
                        week_is_final: bool) -> tuple[bool, list]:
    """May a FantasyStakes factual market built on these lineups be settled?

    TWO INDEPENDENT CONDITIONS, AND BOTH ARE REQUIRED. The week must be
    economically final — which only `providers/finality.py` may declare, and
    which this function takes as an argument rather than deciding — AND every
    lineup's factual evidence must be complete. A final week with a missing
    kicker is not settleable, and a complete set of facts about a game still in
    progress is not either.
    """
    reasons: list = []
    if not week_is_final:
        reasons.append("PROVIDER_NOT_FINAL: the week is not economically "
                       "final; only the finality writer may say that it is")
    for lineup in lineups:
        if not lineup.ready:
            reasons.append(
                f"EVIDENCE_INCOMPLETE: {lineup.team_name or lineup.team_id}: "
                + "; ".join(lineup.diagnostics[:3]))
    return (not reasons), reasons
