"""Yahoo Pool integration — the Yahoo stat map over the neutral stat source.

WP2 MOVED THE ENGINE TO `providers/week_stat_source.py` AND LEFT THE YAHOO PART
HERE. The part that is genuinely Yahoo's is small and is all of it:

    load_yahoo_stat_map()    reads `yahoo_stat_id` out of the governed
                             vocabulary artifact
    YahooProviderStatSource  the neutral source with that map injected

Everything else — subject construction, the §13 starter rule, the §C7.3 coverage
withdrawal, the derived-operand expansion, the gate-2 measurement — was never
Yahoo-specific and now has exactly one implementation that Demo drives too.

THE VOCABULARY IS AUTHORITATIVE FOR STAT IDENTITY (§13).
`spec/pool_stat_vocabulary_rev1_0.json` already carries `yahoo_stat_id` for
every stat Yahoo sources, and this module reads THAT rather than hardcoding ids.
Three consequences follow directly from the artifact and are not choices made
here:

  * `pass_attempts` and `completions` carry yahoo_stat_id = null
    (UNMAPPED_PENDING_GAME_STAT_CATEGORIES). They can never be reported
    supported, which also makes the derived `opportunities` unavailable — and
    that is precisely why 13 catalog definitions are source-incomplete today.
  * `made_field_goal_distance` is UNSUPPORTED_BY_YAHOO_FANTASY_FEED and is
    never mapped at all.
  * The five field-goal bracket counters ARE mapped, so the derived
    `field_goals_made` becomes available whenever all five are present.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Mapping, Sequence

from betting.pool_catalog import VOCABULARY_PATH
from providers.base import ProviderWeek
from providers.week_stat_source import ProviderWeekStatSource, measure_activation

PROVIDER = "yahoo"

#: Source families that come from the weekly player stats feed. Only these carry
#: a yahoo_stat_id worth mapping; FANTASY_POINTS arrives on player_points and
#: LEAGUE_MATCHUP on the matchup row, both handled separately by the source.
_PLAYER_STAT_FAMILY = "YAHOO_WEEKLY_PLAYER_STATS"


@dataclass(frozen=True)
class YahooStatMap:
    """The governed Yahoo stat id -> canonical name mapping.

    `unmapped` records the canonical names the artifact declares Yahoo-sourced
    but leaves with a null stat id. Carried rather than dropped so a caller
    asking "why is opportunities unsupported?" gets an answer from the mapping
    itself instead of from a code comment.
    """

    by_stat_id: Mapping[str, str]
    unmapped: frozenset[str]
    unsupported: frozenset[str]

    def canonical_for(self, stat_id: str) -> str | None:
        return self.by_stat_id.get(str(stat_id))


@lru_cache(maxsize=1)
def load_yahoo_stat_map(path: str = VOCABULARY_PATH) -> YahooStatMap:
    """Read the authoritative vocabulary and extract the Yahoo id mapping.

    Deliberately a SEPARATE reader from betting.pool_catalog.load_vocabulary
    rather than an extension of it. `StatVocabulary` is accepted Sprint 4
    product surface consumed by the pure evaluator; adding a provider-specific
    field to it would push a Yahoo concern across a boundary Scope §C7 exists to
    keep clean. Both read the same file, so neither can drift from the artifact.
    """
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    by_stat_id: dict[str, str] = {}
    unmapped: set[str] = set()
    unsupported: set[str] = set()

    for entry in raw.get("stats", ()):
        name = entry["canonical_name"]
        family = entry.get("source_family")
        if family == "UNSUPPORTED":
            unsupported.add(name)
            continue
        if family != _PLAYER_STAT_FAMILY:
            continue
        stat_id = entry.get("yahoo_stat_id")
        if stat_id is None:
            # Declared Yahoo-sourced but with no id yet. NOT a defect here —
            # the artifact records it as pending game stat_categories access.
            unmapped.add(name)
            continue
        key = str(stat_id)
        if key in by_stat_id and by_stat_id[key] != name:
            raise ValueError(
                f"vocabulary maps Yahoo stat id {key} to both "
                f"{by_stat_id[key]!r} and {name!r}; one provider stat cannot be "
                f"two canonical operands.")
        by_stat_id[key] = name

    return YahooStatMap(by_stat_id=by_stat_id, unmapped=frozenset(unmapped),
                        unsupported=frozenset(unsupported))


class YahooProviderStatSource(ProviderWeekStatSource):
    """The neutral week stat source with the governed Yahoo stat map injected."""

    provider = PROVIDER

    def __init__(self, snapshot: ProviderWeek, *,
                 stat_map: YahooStatMap | None = None) -> None:
        super().__init__(snapshot, stat_map=stat_map or load_yahoo_stat_map())


def measure_league_activation(db, *, league_id: int, snapshot: ProviderWeek,
                              resolver,
                              definition_keys: Sequence[str] | None = None,
                              provider: str = PROVIDER,
                              measured_at: datetime | None = None) -> dict:
    """Gate-2 readiness for a Yahoo league-week. See week_stat_source."""
    source = YahooProviderStatSource(snapshot).bind(db, resolver)
    return measure_activation(
        db, league_id=league_id, source=source, provider=provider,
        observed_at=snapshot.observed_at, definition_keys=definition_keys,
        measured_at=measured_at)
