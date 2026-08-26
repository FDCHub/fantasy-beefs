"""Sprint 6B · persist BALLDONTLIE FACTUAL components beside the projections.

WHERE FACTUAL EVIDENCE GOES, AND WHY IT IS NOT A NEW TABLE.
`ProviderComponentProjection` is dual-use by design and says so: its own
docstring explains that `source_kind` DECIDES WHAT AN ABSENT COMPONENT MEANS,
and the schema has carried `SOURCE_WEEKLY_STATS = "fantasy/weekly_stats"` beside
`SOURCE_PROJECTION` since Sprint 2B. Until now nothing wrote it. The class name
says "projection"; the docstring is about COMPONENTS — "the upstream material"
that has not been through any league's scoring rules — and a finished week's
receptions are exactly that.

So this module adds no schema, no migration and no persistence primitive. It
builds `ComponentProjection` DTOs with `source_kind=SOURCE_WEEKLY_STATS` and
hands them to the Sprint 2B writer, which already enforces WP1 identity,
append-only storage and idempotency by observation digest.

── WHAT SEPARATES A FACTUAL ROW FROM A PROJECTION ROW ──────────────────────

`source_kind`, and everything that follows from it. On a PROJECTION an absent
component may mean the provider forecasts nothing for that category — Sprint 2B
had to add rule 0F-20 because `receptions` is absent for everybody. On a
FACTUAL row an absent component is a measured ZERO: the game finished, the
player was on the field, and he did not do it. CSPS reads that distinction from
the mode it is called in, and the row records which kind of evidence it holds.

── IDEMPOTENCY IS INHERITED, NOT REIMPLEMENTED ─────────────────────────────

`observation_digest` covers the subject, the week, the vocabulary and the
components, and deliberately not the fetch time. Re-ingesting an unchanged
final week therefore writes nothing; a provider CORRECTION changes a component,
changes the digest, and lands a new row beside its predecessor with the old one
still readable. That is the same guarantee the projection path already has, and
it is the one a regrade depends on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from db.schema import ProviderComponentProjection
from providers.component_projections import ComponentProjection, persist_snapshots
from providers.cross_identity import BALLDONTLIE

__all__ = ["FactualIngestReport", "factual_projections", "ingest_factual_week"]


@dataclass
class FactualIngestReport:
    """What one factual ingest stored, skipped and refused."""

    season: int = 0
    week: int = 0
    subjects: int = 0
    eligible: int = 0
    stored: int = 0
    duplicate: int = 0
    refused: int = 0
    incomplete: list = field(default_factory=list)
    outcomes: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"season": self.season, "week": self.week,
                "subjects": self.subjects, "eligible": self.eligible,
                "stored": self.stored, "duplicate": self.duplicate,
                "refused": self.refused,
                "incomplete": list(self.incomplete),
                "outcomes": dict(self.outcomes)}


def factual_projections(week, *, only_complete: bool = True) -> list:
    """A `FactualWeek` -> `ComponentProjection` DTOs marked as factual evidence.

    INCOMPLETE SUBJECTS ARE NOT STORED BY DEFAULT. A kicker whose distances
    never arrived has components that are true as far as they go and misleading
    as a whole, and a stored row is read later by something that has forgotten
    the diagnostic. The caller may override, but the settlement path does not.
    """
    out: list = []
    for key, subject in sorted(week.subjects.items()):
        if only_complete and subject.diagnostics:
            continue
        out.append(ComponentProjection(
            provider=BALLDONTLIE,
            provider_player_key=key,
            season=int(week.season),
            week=int(week.week),
            components=dict(subject.components),
            components_present=tuple(subject.components_present),
            nfl_team=subject.nfl_team,
            position=subject.position,
            provider_game_id=(str(subject.provider_game_id)
                              if subject.provider_game_id is not None else None),
            source_kind=ProviderComponentProjection.SOURCE_WEEKLY_STATS,
        ))
    return out


def ingest_factual_week(db, week, *, resolutions: Mapping[str, Any],
                        captured_at: datetime | None = None,
                        provenance: str = ProviderComponentProjection.PROVENANCE_LIVE,
                        only_complete: bool = True) -> FactualIngestReport:
    """Store one finished NFL week's factual components.

    `resolutions` maps a provider player key to WP1's `CrossProviderResolution`.
    A subject with no resolution is REFUSED by the Sprint 2B writer rather than
    stored against a guess — there is no name fallback in a path that ends in
    settlement.
    """
    captured_at = captured_at or datetime.now(timezone.utc)
    report = FactualIngestReport(season=int(week.season), week=int(week.week),
                                 subjects=len(week.subjects))

    pairs = []
    for projection in factual_projections(week, only_complete=only_complete):
        key = projection.provider_player_key
        pairs.append((resolutions.get(key), projection))
    report.eligible = len(pairs)

    for key, subject in sorted(week.subjects.items()):
        if subject.diagnostics:
            report.incomplete.append(
                {"provider_player_key": key,
                 "diagnostics": list(subject.diagnostics)})

    result = persist_snapshots(db, pairs, captured_at=captured_at,
                               provenance=provenance)
    for item in getattr(result, "results", ()) or ():
        outcome = getattr(item, "outcome", None)
        name = getattr(outcome, "name", None) or str(outcome)
        report.outcomes[name] = report.outcomes.get(name, 0) + 1
        if name in ("STORED", "PERSISTED"):
            report.stored += 1
        elif name in ("DUPLICATE", "UNCHANGED"):
            report.duplicate += 1
        else:
            report.refused += 1
    return report
