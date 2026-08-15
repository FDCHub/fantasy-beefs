"""The Demo provider's access object — the counterpart of a Yahoo transport.

WHAT IT IS THE COUNTERPART OF, PRECISELY. `YahooLiveTransport` fetches bytes and
`providers/yahoo/{parse,normalize}.py` turn them into DTOs. A Demo league has no
bytes to fetch, so the parse/normalize pair would be ceremony over a payload
this repository invented for itself to read back — and inventing a raw envelope
would put a decoder in the tree that decodes nothing real. This class therefore
produces the NORMALIZED DTOs directly, which is where the two providers were
always going to meet anyway.

THE DTOs ARE THE CONTRACT, NOT THE TRANSPORT. `providers/base.py` says a
provider must produce `ProviderWeek`; it does not say how. Everything downstream
of that — identity, persistence, finality, the stat source, the bracket source —
is reached by both providers through the same functions, and C-18 asserts a Demo
snapshot satisfies the same shape rules a Yahoo one does.

── OUTAGE IS A FIRST-CLASS MODE, AND THAT IS THE POINT (WP2 §29) ────────────

`outage=True` makes every read raise `ProviderTransportError` — the SAME named
error a Yahoo network failure raises — before a single fact is produced. It
exists so the provider-recovery lifecycle can be certified end to end against a
provider that genuinely refuses, rather than against a mock of one:

    refresh attempted -> named retryable failure -> NOTHING persisted, no
    finality invented, no Pool classified, no Credit moved -> outage clears ->
    the same refresh succeeds -> ordinary settlement runs.

It is a construction-time property of this object and is reachable only from the
composition seam that builds it. There is no route parameter, no column and no
commissioner switch that turns it on, because it models a provider fault and not
a product decision.

── REVISIONS MODEL AN INCOMPLETE FEED, NOT AN EDITABLE ONE ──────────────────

`revision=INCOMPLETE` withholds one started player's stat record. It is the WP1E
operational case — a week that is FINAL while the stat feed has not caught up —
and it is the only thing a caller may vary about the facts. Nothing here lets
anyone set a score, name a winner or choose a Pool outcome; WP2 §35 forbids it
and the scenario is a pure function that could not honour it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from providers.base import ProviderWeek
from providers.demo import DEMO_LEAGUE_KEY_PREFIX, DEMO_PROVIDER
from providers.demo.scenario import (
    REVISION_COMPLETE,
    REVISION_INCOMPLETE,
    DemoScenario,
    week_snapshot,
)
from providers.errors import ProviderIdentityError, ProviderTransportError

#: The reason an outage names itself with. Reused by the incident taxonomy so
#: one condition has one operator-readable name across routes and logs.
OUTAGE_REASON = "provider_unavailable"


def scenario_for(league_key: str) -> DemoScenario:
    """The scenario a Demo league key denotes, or a named refusal.

    THE KEY IS THE WHOLE STATE. A Demo league's facts are a pure function of its
    key, so there is no registry to populate, nothing to keep in sync and no way
    for two processes to hold different opinions about what week 3 contained.

    A NON-DEMO KEY IS REFUSED, NOT SERVED. Answering for a Yahoo league key would
    make this source capable of fabricating facts about a real league, which is
    the one thing separating a demo from a forgery.
    """
    if not league_key or not league_key.startswith(DEMO_LEAGUE_KEY_PREFIX):
        raise ProviderIdentityError(
            ProviderIdentityError.NON_AUTHORITATIVE,
            f"league key {league_key!r} is not a Demo league key (it does not "
            f"begin with {DEMO_LEAGUE_KEY_PREFIX!r}). The Demo provider states "
            f"facts only about leagues it invented; refusing to answer for a "
            f"league belonging to another provider.")
    return DemoScenario(league_key=league_key)


class DemoProviderSource:
    """Deterministic Demo facts, with an injectable outage.

    `is_demo_source` is a class attribute rather than an isinstance check at the
    call site, mirroring `FixtureTransport.is_fixture_transport`, so a
    certification gate can assert which source served a refresh by reading an
    attribute.
    """

    provider = DEMO_PROVIDER
    is_demo_source = True

    def __init__(self, *, outage: bool = False,
                 revision: str = REVISION_COMPLETE,
                 frozen_now: datetime | None = None) -> None:
        if revision not in (REVISION_COMPLETE, REVISION_INCOMPLETE):
            raise ValueError(
                f"unknown Demo snapshot revision {revision!r}; the Demo feed "
                f"models a COMPLETE week and an INCOMPLETE one and nothing "
                f"else.")
        self._outage = bool(outage)
        self._revision = revision
        self._frozen_now = frozen_now
        #: Every read this source served, so a gate can prove it was used.
        self.read_log: list[tuple[str, int]] = []

    def __repr__(self) -> str:
        return (f"<DemoProviderSource revision={self._revision} "
                f"outage={self._outage}>")

    @property
    def revision(self) -> str:
        return self._revision

    def observed_at(self) -> datetime:
        """When this source's facts were observed — NOW, or a frozen instant.

        A LIVE PROVIDER STAMPS THE MOMENT IT ANSWERED, and the Demo provider is
        answering now: it invents its facts on demand, so the honest stamp is the
        current instant, exactly as `YahooLiveTransport.observed_at` returns the
        moment of the fetch. `providers/fixtures/replay.py` freezes its stamp
        because it is REPLAYING bytes recorded in the past.

        THIS MATTERS ECONOMICALLY. Gate-2 readiness is stamped with this value
        and expires 24 hours later, so a frozen stamp would leave every Demo
        league permanently stale, with zero selectable definitions and no Pool
        slate — a Demo that could not draw a Pool.

        `frozen_now` exists for a gate that needs the window crossed by
        arithmetic rather than by waiting, and is never set in production.
        """
        return self._frozen_now or datetime.now(timezone.utc)

    def _guard(self) -> None:
        if self._outage:
            raise ProviderTransportError(
                "the Demo provider is unavailable (simulated outage). No fact "
                "was read and nothing was persisted; this is a RETRYABLE "
                "transport failure, not a statement that the week has no data.")

    def week_snapshot(self, *, league_key: str, week: int, current_week: int,
                      final: bool, with_rosters: bool = False) -> ProviderWeek:
        """One Demo league-week, or a named refusal if the provider is out.

        THE GUARD RUNS FIRST, BEFORE ANY FACT IS BUILT. An outage that produced
        a partial snapshot would be worse than one that produced none: a short
        matchup list looks exactly like a week the provider says has fewer
        games, and the slate-completeness gate would compare a short list
        against a short list and pass.
        """
        self._guard()
        scenario = scenario_for(league_key)
        self.read_log.append((league_key, week))
        return week_snapshot(
            scenario, week=week, current_week=current_week, final=final,
            with_rosters=with_rosters, revision=self._revision,
            observed_at=self.observed_at())
