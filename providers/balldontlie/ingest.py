"""Sprint 2B · the BALLDONTLIE component projection ingestion operation.

ONE OPERATION, FIVE LAYERS, EACH ALREADY CERTIFIED SEPARATELY:

    transport (WP2)   -> a week of projections, by cursor pagination
    parse     (WP2)   -> rows, envelope read, nothing interpreted
    normalize (WP2)   -> components under the Phase 0F rules
    identity  (WP1)   -> which FantasyStakes player each subject IS
    store     (2B)    -> an append-only snapshot, or a named refusal

This module is the wiring and the accounting. It contains no rule of its own
about what a stat means, who a player is, or when a projection has changed —
each of those already has a home, and duplicating any of them here is how two
answers to one question get into a codebase.

── A WEEK IS FETCHED AS A WEEK ─────────────────────────────────────────────

`fantasy/projections?season=&week=` returns the whole slate by cursor, seven
pages at a hundred rows. The player-by-player alternative would be one request
per subject: at the five-per-minute throttle Phase 0 measured on this key, a
600-player slate is two hours of walking rather than ninety seconds, and it
would spend that budget to learn the same thing. `pages_fetched` and
`requests_made` are reported so this property is observable rather than
promised.

── WHY IDENTITY RUNS FROM OUR SIDE ─────────────────────────────────────────

The resolution direction is FantasyStakes player -> BALLDONTLIE subject, not the
reverse, and it is worth being explicit about why. Our roster is the set we care
about; BALLDONTLIE's slate is 742 subjects, most of whom no league here has ever
rostered. Walking our players and asking WP1 "who is this at BALLDONTLIE"
answers exactly the question that matters, uses the resolver in the direction it
was designed and certified for, and gets AMBIGUOUS, UNRESOLVED and CONFLICT for
free — each already meaning something precise.

── ABSENT FROM THE SLATE IS NOT AN IDENTITY FAILURE ────────────────────────

A player we have mapped who simply is not in this week's projections is
`absent_from_slate`, counted separately from `unresolved`. Conflating them would
report a quiet identity crisis every bye week. The reverse conflation is not
made either: an UNMAPPED player who is also not in the slate stays UNRESOLVED,
because from this payload alone the two really are indistinguishable, and WP1's
refusal text says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from providers.balldontlie import normalize as N
from providers.balldontlie import parse as P
from providers.balldontlie_identity import directory_from_rows
from providers.component_projections import (
    ComponentProjection,
    PersistOutcome,
    persist_snapshots,
)
from providers.cross_identity import BALLDONTLIE, Outcome, resolve_player

__all__ = ["IngestSummary", "ingest_week", "projections_for_week"]

PROJECTIONS_ENDPOINT = "fantasy/projections"


@dataclass
class IngestSummary:
    """Deterministic accounting for one ingestion run.

    EVERY SUBJECT IS IN EXACTLY ONE BUCKET. `resolved` is the number of our
    players WP1 identified AND who appear in this slate — the number that could
    have been stored — and `persisted + duplicate` must account for all of them.
    An assertion downstream can check that, which is only possible because
    nothing is dropped on the way through.
    """

    season: int = 0
    week: int = 0
    fetched: int = 0
    normalized: int = 0
    players_considered: int = 0
    resolved: int = 0
    absent_from_slate: int = 0
    persisted: int = 0
    duplicate: int = 0
    ambiguous: int = 0
    unresolved: int = 0
    conflict: int = 0
    failed: int = 0
    pages_fetched: int = 0
    requests_made: int = 0
    provenance: str = ""
    captured_at: datetime | None = None
    unresolved_players: list = field(default_factory=list)
    ambiguous_players: list = field(default_factory=list)
    conflict_players: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "season": self.season, "week": self.week,
            "fetched": self.fetched, "normalized": self.normalized,
            "players_considered": self.players_considered,
            "resolved": self.resolved,
            "absent_from_slate": self.absent_from_slate,
            "persisted": self.persisted, "duplicate": self.duplicate,
            "ambiguous": self.ambiguous, "unresolved": self.unresolved,
            "conflict": self.conflict, "failed": self.failed,
            "pages_fetched": self.pages_fetched,
            "requests_made": self.requests_made,
            "provenance": self.provenance,
            "unresolved_players": list(self.unresolved_players),
            "ambiguous_players": list(self.ambiguous_players),
            "conflict_players": list(self.conflict_players),
        }


def projections_for_week(transport, *, season: int, week: int,
                         max_pages: int = 25) -> tuple[list, int]:
    """The whole slate, by cursor. Returns (raw rows, pages fetched).

    Deliberately a thin wrapper: the pagination, the page bound and the refusal
    to walk past it all live in the certified transport, and re-implementing any
    of them here would put a second answer beside the certified one.
    """
    before = getattr(transport, "requests_made", 0)
    rows = transport.paginate(PROJECTIONS_ENDPOINT, season=season, week=week,
                              max_pages=max_pages)
    pages = getattr(transport, "requests_made", 0) - before
    return rows, pages


def ingest_week(db, transport, *, season: int, week: int,
                players: Sequence[Any] | None = None,
                provenance: str | None = None,
                captured_at: datetime | None = None,
                vocabulary_version: str | None = None,
                max_pages: int = 25) -> IngestSummary:
    """Fetch, normalize, identify and store one week of component projections.

    `provenance` is derived from the transport when not stated, and it is
    derived rather than defaulted for the same reason the fixture corpus carries
    a manifest: a snapshot replayed from synthetic material must never be
    indistinguishable from one fetched live. A fixture transport produces
    FIXTURE_SYNTHETIC rows and there is no argument that makes it produce LIVE.
    """
    from db.schema import Player, ProviderComponentProjection
    from providers.balldontlie.transport import BalldontlieFixtureTransport

    captured_at = captured_at or datetime.now(timezone.utc)
    if provenance is None:
        provenance = (
            ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC
            if isinstance(transport, BalldontlieFixtureTransport)
            else ProviderComponentProjection.PROVENANCE_LIVE)

    summary = IngestSummary(season=int(season), week=int(week),
                            provenance=provenance, captured_at=captured_at)

    requests_before = getattr(transport, "requests_made", 0)
    raw_rows, pages = projections_for_week(transport, season=season, week=week,
                                           max_pages=max_pages)
    summary.fetched = len(raw_rows)
    summary.pages_fetched = pages

    rows = P.parse_projections({"data": raw_rows, "meta": {}})
    stats = N.normalize_projections(rows, week=week)
    summary.normalized = len(stats)

    # The directory WP1 resolves against is built from THE SAME ROWS that
    # produced the components, so a subject cannot be identified from one slate
    # and scored from another.
    directory = directory_from_rows(raw_rows)

    by_key = {s.player_key: s for s in stats}
    row_by_key = {N.subject_key(row): row for row in rows}
    observed_by_key = {
        key: _observed_at(row, captured_at) for key, row in row_by_key.items()}

    if players is None:
        players = db.query(Player).all()
    summary.players_considered = len(players)

    pairs = []
    for player in players:
        resolution = resolve_player(db, player, directory, provider=BALLDONTLIE)

        if resolution.outcome != Outcome.RESOLVED:
            bucket = {
                Outcome.AMBIGUOUS: summary.ambiguous_players,
                Outcome.UNRESOLVED: summary.unresolved_players,
                Outcome.CONFLICT: summary.conflict_players,
            }.get(resolution.outcome)
            if bucket is not None:
                bucket.append(player.name)
            if resolution.outcome == Outcome.AMBIGUOUS:
                summary.ambiguous += 1
            elif resolution.outcome == Outcome.CONFLICT:
                summary.conflict += 1
            else:
                summary.unresolved += 1
            continue

        key = resolution.provider_player_key
        stat = by_key.get(key)
        if stat is None:
            # Mapped, and not in this week's slate. A bye, an inactive, a
            # provider that simply did not forecast him. Not an identity fault.
            summary.absent_from_slate += 1
            continue

        summary.resolved += 1
        row = row_by_key.get(key)
        pairs.append((resolution, ComponentProjection(
            provider=BALLDONTLIE,
            provider_player_key=key,
            season=int(season), week=int(week),
            components=stat.values,
            components_present=tuple(sorted(row.stats)) if row else (),
            nfl_team=_canonical_team(row),
            position=N.fantasy_position(row) if row else None,
            provider_game_id=_provider_game_id(row),
            provider_record_id=_provider_record_id(row),
            observed_at=observed_by_key.get(key, captured_at),
            source_kind=ProviderComponentProjection.SOURCE_PROJECTION,
        )))

    report = persist_snapshots(db, pairs, captured_at=captured_at,
                               provenance=provenance,
                               vocabulary_version=vocabulary_version)
    summary.persisted = report.persisted
    summary.duplicate = report.duplicate
    summary.failed = report.failed
    # A refusal raised inside the store counts on top of the identity refusals
    # already recorded above; both are real and neither replaces the other.
    summary.ambiguous += report.ambiguous
    summary.unresolved += report.unresolved
    summary.conflict += report.conflict
    summary.requests_made = (getattr(transport, "requests_made", 0)
                             - requests_before)
    return summary


def _observed_at(row, fallback: datetime) -> datetime:
    """The provider's own freshness stamp, or the capture instant.

    Phase 0 measured `collected_at` on the projection rows — the 2026 week-1
    projections carried `2026-08-24T23:15:00Z`, refreshed that day. It is the
    closest thing this provider offers to "when was this forecast made", and it
    is what snapshot selection orders on. Falling back to the capture instant is
    honest rather than convenient: without a provider stamp, the only thing we
    know is when WE saw it.
    """
    raw = row.raw.get("collected_at") or row.raw.get("observed_at")
    if not raw:
        return fallback
    try:
        text = str(raw).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return fallback
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _canonical_team(row) -> str | None:
    if row is None:
        return None
    from providers.nfl_teams import to_canonical_team
    try:
        return to_canonical_team(row.team_abbreviation, dialect=BALLDONTLIE)
    except Exception:                                          # noqa: BLE001
        return None


def _provider_game_id(row) -> str | None:
    if row is None:
        return None
    for key in ("game_id", "nfl_game_id"):
        value = row.raw.get(key)
        if value is not None:
            return str(value)
    game = row.raw.get("game")
    if isinstance(game, dict) and game.get("id") is not None:
        return str(game["id"])
    return None


def _provider_record_id(row) -> str | None:
    if row is None:
        return None
    value = row.raw.get("id")
    return None if value is None else str(value)
