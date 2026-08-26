"""Sprint 6B · a BALLDONTLIE-backed `PoolStatSource`, and nothing more.

THE POOL GRADER IS NOT TOUCHED. `betting/pool_settlement.py` takes a
`stat_source` parameter and never inspects its type; `PoolStatSource` is a
one-method protocol; and `providers/week_stat_source.py` already implements the
whole of it generically, needing only a map from provider stat names to the
governed vocabulary. Yahoo's adaptor is a ten-line subclass and Demo's is
another. This is the third, and it is the same ten lines.

── THE MAP IS A WHITELIST, NEVER A PASS-THROUGH ────────────────────────────

`canonical_for` returning its argument unconditionally would let any string
become a pool operand and defer the refusal to the catalog, where it surfaces
later and somewhere else. So the names BALLDONTLIE can answer for are declared
here and checked against the governed vocabulary at load time: a name this
provider advertises that the catalog has never heard of is a startup error, not
a settlement-time surprise.

── WHY A COMPOSED WEEK, AND NOT A BALLDONTLIE ONE ──────────────────────────

`normalize.build_week()` returns `teams=()`, `matchups=()` and
`roster_entries=()` on purpose: BALLDONTLIE hosts no leagues, no fantasy teams
and no rosters, and filling those with plausible-looking material would be a
lie the aggregate is trusted not to tell. But the Pool census needs to know who
STARTED, which is a Yahoo fact.

So the week handed to this source is COMPOSED — Yahoo's roster entries and
league identity, BALLDONTLIE's player stats — which is exactly the division of
authority the product already declares: Yahoo owns the league, the provider
owns the football. `factual_provider_week` does that composition in one place
and refuses to invent either half.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Sequence

from providers.base import ProviderLeague, ProviderPlayerStats, ProviderWeek
from providers.cross_identity import BALLDONTLIE
from providers.week_stat_source import ProviderWeekStatSource

__all__ = ["BalldontlieStatMap", "load_balldontlie_stat_map",
           "BalldontlieProviderStatSource", "factual_provider_week",
           "factual_week_from_components"]

#: FACTUAL COMPONENT NAME -> GOVERNED POOL OPERAND. Not identity, and finding
#: that out was the point of the load-time check: the pool catalog calls a
#: passing touchdown `passing_td` and a thrown interception
#: `interceptions_thrown`, while CSPS calls them `passing_touchdowns` and
#: `passing_interceptions`. Advertising the CSPS spelling would have put an
#: ungoverned operand across the boundary and surfaced as a catalog refusal
#: somewhere else entirely.
#:
#: The pool vocabulary also brackets field goals FINER than either league
#: profile does — five bands against three — which the factual path can satisfy
#: because it holds every attempt's exact distance.
FACTUAL_TO_POOL: dict = {
    "passing_yards": "passing_yards",
    "passing_touchdowns": "passing_td",
    "passing_interceptions": "interceptions_thrown",
    "rushing_yards": "rushing_yards",
    "rushing_touchdowns": "rushing_td",
    "receptions": "receptions",
    "receiving_yards": "receiving_yards",
    "receiving_touchdowns": "receiving_td",
    "fumbles_lost": "fumbles_lost",
    "field_goals_made": "field_goals_made",
    "field_goals_made_yards": "made_field_goal_distance",
    "field_goals_made_0_19": "field_goals_made_0_19",
    "field_goals_made_20_29": "field_goals_made_20_29",
    "field_goals_made_30_39": "field_goals_made_30_39",
    "field_goals_made_40_49": "field_goals_made_40_49",
    "field_goals_made_50_plus": "field_goals_made_50_plus",
    "extra_points_made": "extra_points_made",
}

#: The governed names this provider advertises.
BALLDONTLIE_STAT_NAMES: frozenset[str] = frozenset(FACTUAL_TO_POOL.values())


@dataclass(frozen=True)
class BalldontlieStatMap:
    """Identity over the factual names this provider declares. A whitelist."""

    names: frozenset[str]

    def canonical_for(self, stat_id: str) -> str | None:
        name = str(stat_id)
        return name if name in self.names else None


@lru_cache(maxsize=1)
def load_balldontlie_stat_map() -> BalldontlieStatMap:
    """Build the map, refusing any name the governed vocabulary does not know."""
    from betting.pool_catalog import load_vocabulary

    vocab = load_vocabulary()
    unknown = sorted(BALLDONTLIE_STAT_NAMES - set(vocab.canonical))
    if unknown:
        raise ValueError(
            f"BALLDONTLIE declares stat name(s) {unknown!r} that are not in the "
            f"governed vocabulary. A provider cannot advertise an operand the "
            f"catalog has never heard of; fix the name or add it to the "
            f"artifact.")
    return BalldontlieStatMap(names=BALLDONTLIE_STAT_NAMES)


class BalldontlieProviderStatSource(ProviderWeekStatSource):
    """The neutral week stat source with the BALLDONTLIE identity map injected."""

    provider = BALLDONTLIE

    def __init__(self, snapshot: ProviderWeek, *,
                 stat_map: BalldontlieStatMap | None = None) -> None:
        super().__init__(snapshot,
                         stat_map=stat_map or load_balldontlie_stat_map())


def factual_provider_week(*, league: ProviderLeague, week: int,
                          roster_entries: Sequence,
                          factual_week,
                          observed_at: datetime | None = None) -> ProviderWeek:
    """Yahoo's roster + BALLDONTLIE's facts -> one `ProviderWeek`.

    THE COMPOSITION BOUNDARY, MADE EXPLICIT. Each side supplies only what it
    owns: the league, its teams and who started come from the caller's Yahoo
    snapshot; the measured football comes from `factual_week`. Nothing is
    fabricated to fill a gap on either side, and `matchups` stays empty because
    BALLDONTLIE cannot finalize a fantasy matchup — that remains Yahoo's, and
    `providers/finality.py` remains its only writer.

    Only COMPLETE subjects cross: a kicker whose distances never arrived is
    absent rather than present-and-wrong, so the Pool census counts him as
    unmeasured and refuses instead of grading a hole as a zero.
    """
    stats = []
    for key, subject in sorted(factual_week.subjects.items()):
        if subject.diagnostics:
            continue
        values = {FACTUAL_TO_POOL[name]: float(value)
                  for name, value in subject.components.items()
                  if name in FACTUAL_TO_POOL}
        if not values:
            continue
        stats.append(ProviderPlayerStats(
            provider=BALLDONTLIE,
            player_key=key,
            week=int(week),
            values=values,
            stat_ids_present=frozenset(values),
            fantasy_points=None,
        ))

    return ProviderWeek(
        league=league, week=int(week),
        teams=(), matchups=(), roster_entries=tuple(roster_entries),
        player_stats=tuple(stats),
        observed_at=observed_at,
    )


def factual_week_from_components(db, *, league, week: int, season: int,
                                 roster_entries, observed_at=None):
    """A composed `ProviderWeek` built from PERSISTED factual components.

    THE SETTLEMENT PATH READS THE DATABASE, NEVER THE PROVIDER. `factual_
    provider_week` composes from a freshly-built `FactualWeek`, which is right
    for an ingest run; a Pool settling on Tuesday must not depend on
    BALLDONTLIE answering on Tuesday. This reads the rows an earlier refresh
    persisted under `source_kind="fantasy/weekly_stats"` and composes from
    those.

    IT REFUSES AN EMPTY WEEK RATHER THAN RETURNING ONE. A composed week with no
    player stats would let the Pool census conclude that nobody was measured,
    which is indistinguishable from a real week in which nobody played. The
    difference matters: one is a data gap and the other is a result.
    """
    from db.schema import ProviderComponentProjection as PCP
    from providers.base import ProviderPlayerStats, ProviderWeek
    from providers.cross_identity import BALLDONTLIE as _BDL

    rows = (db.query(PCP)
            .filter(PCP.provider == _BDL,
                    PCP.season == int(season),
                    PCP.week == int(week),
                    PCP.source_kind == PCP.SOURCE_WEEKLY_STATS)
            .order_by(PCP.id.asc())
            .all())
    if not rows:
        raise LookupError(
            f"league season {season} week {week} is configured for BALLDONTLIE "
            f"facts and no factual component snapshot has been persisted for "
            f"it. There is no fallback to another provider's numbers: a Pool "
            f"graded on evidence the operator did not choose is wrong even "
            f"when every subject resolves.")

    # The newest observation per subject wins, exactly as `select_week` does.
    latest: dict = {}
    for row in rows:
        latest[row.provider_player_key] = row

    stats = []
    for key, row in sorted(latest.items()):
        components = dict(row.components or {})
        values = {FACTUAL_TO_POOL[name]: float(value)
                  for name, value in components.items()
                  if name in FACTUAL_TO_POOL}
        if not values:
            continue
        stats.append(ProviderPlayerStats(
            provider=_BDL, player_key=key, week=int(week), values=values,
            stat_ids_present=frozenset(values), fantasy_points=None))

    return ProviderWeek(
        league=league, week=int(week), teams=(), matchups=(),
        roster_entries=tuple(roster_entries), player_stats=tuple(stats),
        observed_at=observed_at)
