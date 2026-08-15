"""Demo Pool integration — the identity stat map over the neutral stat source.

THE DEMO PROVIDER'S OWN STAT VOCABULARY IS THE GOVERNED ONE. A Yahoo payload
names passing yards "4" and `YahooStatMap` translates it; a Demo snapshot names
it "passing_yards" and `DemoStatMap` translates it to itself. That is a
legitimate provider mapping and not a bypass — the translation step still runs,
an ungoverned name is still dropped, and support is still MEASURED from the
facts the snapshot actually carried rather than from this list.

THE LIST IS VALIDATED AGAINST THE ARTIFACT, WHICH IS WHY IT IS SAFE TO WRITE ONE
DOWN. `load_demo_stat_map()` refuses at load time if any name below is absent
from `spec/pool_stat_vocabulary_rev1_0.json`, so a typo is a loud failure rather
than a stat that silently never covers anything.

WHY DEMO DELIBERATELY REPORTS NO MORE THAN YAHOO CAN. `pass_attempts` and
`completions` carry no Yahoo stat id in the governed artifact, so no live league
can have them, and the derived `opportunities` is unavailable in consequence.
A Demo feed could trivially supply all three — it invents its own numbers — and
does not. A demo whose Pool catalog is richer than the real product's is a demo
of a product that does not exist, and the first live league would lose Pools the
demo promised.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Sequence

from providers.base import ProviderWeek
from providers.demo import DEMO_PROVIDER
from providers.week_stat_source import ProviderWeekStatSource, measure_activation

PROVIDER = DEMO_PROVIDER

#: Exactly the canonical stats the Demo scenario emits. Kept beside the map that
#: validates them rather than inside the scenario, so the scenario stays pure
#: arithmetic and this stays the single statement of what the feed can measure.
DEMO_STAT_NAMES: frozenset[str] = frozenset({
    "passing_yards",
    "passing_td",
    "interceptions_thrown",
    "rush_attempts",
    "rushing_yards",
    "rushing_td",
    "receptions",
    "receiving_yards",
    "receiving_td",
    "targets",
    "two_point_conversions",
    "fumbles_lost",
    "extra_points_made",
    "field_goals_made_0_19",
    "field_goals_made_20_29",
    "field_goals_made_30_39",
    "field_goals_made_40_49",
    "field_goals_made_50_plus",
})


@dataclass(frozen=True)
class DemoStatMap:
    """Identity over the Demo feed's declared canonical stats.

    A name the Demo feed does not declare returns None and its value is dropped,
    exactly as an ungoverned Yahoo stat id is dropped. The map is a whitelist and
    not a pass-through: `canonical_for` returning its argument unconditionally
    would let any string become an operand and defer the refusal to the catalog.
    """

    names: frozenset[str]

    def canonical_for(self, stat_id: str) -> str | None:
        name = str(stat_id)
        return name if name in self.names else None


@lru_cache(maxsize=1)
def load_demo_stat_map() -> DemoStatMap:
    """Build the Demo stat map, refusing any name the vocabulary does not know."""
    from betting.pool_catalog import load_vocabulary

    vocab = load_vocabulary()
    unknown = sorted(DEMO_STAT_NAMES - set(vocab.canonical))
    if unknown:
        raise ValueError(
            f"the Demo feed declares stat name(s) {unknown!r} that are not in "
            f"the governed vocabulary. A provider cannot advertise an operand "
            f"the catalog has never heard of; fix the name or add it to the "
            f"artifact.")
    return DemoStatMap(names=DEMO_STAT_NAMES)


class DemoProviderStatSource(ProviderWeekStatSource):
    """The neutral week stat source with the Demo identity map injected."""

    provider = PROVIDER

    def __init__(self, snapshot: ProviderWeek, *,
                 stat_map: DemoStatMap | None = None) -> None:
        super().__init__(snapshot, stat_map=stat_map or load_demo_stat_map())


def measure_league_activation(db, *, league_id: int, snapshot: ProviderWeek,
                              resolver,
                              definition_keys: Sequence[str] | None = None,
                              provider: str = PROVIDER,
                              measured_at: datetime | None = None) -> dict:
    """Gate-2 readiness for a Demo league-week. See week_stat_source.

    IT IS THE SAME MEASUREMENT, RECORDED UNDER THE DEMO PROVIDER. Gate-2 rows
    are keyed (league, provider, definition), so a Demo league's readiness can
    never be read as a Yahoo league's — and a Demo league gets no free pass: a
    definition whose required stats this snapshot did not carry is blocked with
    the missing stats named, exactly as it would be for Yahoo.
    """
    source = DemoProviderStatSource(snapshot).bind(db, resolver)
    return measure_activation(
        db, league_id=league_id, source=source, provider=provider,
        observed_at=snapshot.observed_at, definition_keys=definition_keys,
        measured_at=measured_at)
