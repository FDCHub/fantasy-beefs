"""Provider-neutral contract — the DTOs and the transport interface.

TWO THINGS LIVE HERE AND NOTHING ELSE: the normalized shapes every provider must
produce, and the transport interface every provider access path must satisfy.
No Yahoo field name appears below this line, which is the property that lets
providers/yahoo/ be swapped without touching persistence, identity or finality.

FINALITY IS A TRISTATE, NOT A BOOLEAN (§7). A boolean has no room for "the
provider did not say", and the whole Sprint 5 ruling turns on that third state
being represented rather than collapsed into False-with-a-shrug. It is spelled
as an explicit enum so an absent signal is a VALUE the code carries, not a
default it forgets to check.

SCORES ARE OPTIONAL; FINALITY IS NOT DERIVED FROM THEM. `home_points` is
`float | None` deliberately — a pre-event matchup has no score, and Sprint 5's
schema comment records exactly why a 0.0 standing in for "no score" is the
conflation that makes an unplayed game look like a final tie. The DTO refuses to
launder that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence


class Finality(str, Enum):
    """The provider's affirmative statement about whether a result is over.

    FINAL         the provider explicitly says the event is complete
    NOT_FINAL     the provider explicitly says it is not complete
    UNKNOWN       the provider said nothing usable about finality

    UNKNOWN AND NOT_FINAL ARE BOTH NON-FINAL, and are still kept apart. They
    map to the same economic outcome (finalized_at stays NULL) but describe
    different operational situations — "the game is in progress" versus "we
    could not tell" — and collapsing them would erase the second, which is the
    one that means somebody should look at the feed.
    """

    FINAL = "FINAL"
    NOT_FINAL = "NOT_FINAL"
    UNKNOWN = "UNKNOWN"

    @property
    def is_affirmatively_final(self) -> bool:
        """The ONLY predicate any money path may consult on this enum.

        Named for what it asserts. `finality == Finality.FINAL` says the same
        thing, but `if not finality.is_affirmatively_final` reads as the rule it
        enforces, and there is no truthiness accident available: every member of
        a str-Enum is truthy, so a bare `if finality:` would pass for UNKNOWN.
        """
        return self is Finality.FINAL


class MatchupBracket(str, Enum):
    """WP1A — the provider's statement about which BRACKET a matchup belongs to.

    CHAMPIONSHIP        the provider says this matchup is on the championship
                        track — the only postseason track FantasyStakes supports
    NON_CHAMPIONSHIP    the provider says it is not: consolation, placement,
                        third-place, toilet bowl, or anything else that is not
                        the championship track
    UNKNOWN             the provider said nothing usable about the bracket

    A TRISTATE FOR THE SAME REASON `Finality` IS ONE, and the reason is worth
    restating because the failure it prevents is the expensive one. A boolean
    `is_championship` has no room for "the provider did not say", so an absent
    signal collapses into False-with-a-shrug — or, worse, into a default that
    reads as True for every matchup in a postseason week. Both readings are
    wrong, and they are wrong in opposite directions.

    UNKNOWN IS NOT NON_CHAMPIONSHIP AND IS EMPHATICALLY NOT CHAMPIONSHIP.
    They are kept apart because they describe different situations: "this is a
    consolation game" is a provider fact that can be acted on, while "we could
    not tell" is a gap that must stop the determination entirely. Owner ruling
    (WP1A §2) makes the second fail closed — an unclassified postseason week
    yields NO championship-alive set at all, never a fallback to every team that
    happens to have a matchup.

    NOTHING HERE IS DERIVED FROM A SCORE, A WEEK NUMBER, OR TEAM SURVIVAL. A
    matchup is on the championship track because a provider said so, or its
    bracket is UNKNOWN. `providers/yahoo/` does not populate this field today —
    see season/championship_track.py for what that costs and why it is correct.
    """

    CHAMPIONSHIP = "CHAMPIONSHIP"
    NON_CHAMPIONSHIP = "NON_CHAMPIONSHIP"
    UNKNOWN = "UNKNOWN"

    @property
    def is_affirmatively_championship(self) -> bool:
        """The ONLY predicate a championship-track path may consult.

        Named for what it asserts, exactly as `is_affirmatively_final` is. A
        bare `if bracket:` would pass for UNKNOWN — every member of a str-Enum
        is truthy — and `bracket != NON_CHAMPIONSHIP` would admit UNKNOWN, which
        is the specific mistake the owner ruling forbids.
        """
        return self is MatchupBracket.CHAMPIONSHIP


@dataclass(frozen=True)
class ProviderLeague:
    """One league's provider-stable identity and season boundaries."""

    provider: str
    league_key: str
    name: str
    season: int
    #: The provider's current week. The ingestion horizon (§6) is derived from
    #: this and nothing else — never from wall-clock time.
    current_week: int | None = None
    #: Season boundary facts. FantasyBeefs owns their economic meaning (§12);
    #: the provider merely reports them, and a contradiction of an already
    #: frozen value is a conflict rather than an update.
    season_final_week: int | None = None
    playoff_start_week: int | None = None
    #: WP1A — how many teams enter the CHAMPIONSHIP playoff track. None where
    #: the provider did not state it, which is the current state for every
    #: provider in this repository: no transport method fetches it and no parser
    #: reads it. APPENDED, WITH A DEFAULT, so every existing construction site
    #: keeps working unchanged.
    #:
    #: THIS IS A FIELD SIZE, NOT A BRACKET SHAPE. It is the only input from
    #: which season/championship_track.py derives a round count, and it derives
    #: it arithmetically — no league size, no round count and no week number is
    #: written down anywhere. None means the round count stays None; it never
    #: means "assume the usual".
    playoff_team_count: int | None = None


@dataclass(frozen=True)
class ProviderTeam:
    """One team's provider-stable identity.

    `name` and `manager` are carried for DISPLAY ONLY and are never consulted by
    providers/yahoo/identity.py. They are present so a persisted row can show a
    current team name, and their presence in this DTO must not be read as
    permission to match on them — S6-R1 forbids it, and C-4 proves the resolver
    refuses a name-only or email-only match.
    """

    provider: str
    team_key: str
    team_id: int
    name: str
    manager: str | None = None
    manager_email: str | None = None


@dataclass(frozen=True)
class ProviderMatchup:
    """One scheduled or played matchup, canonically oriented.

    `matchup_key` is derived — see db.schema.Matchup.provider_matchup_key — and
    is stable under mirroring because it sorts the two team keys.

    ORIENTATION IS CANONICAL AND DETERMINISTIC (§5). `home_team_key` is the
    LOWER of the two team keys under the provider's own ordinal ordering, which
    is the convention yahoo_scoreboard.py already used through Sprint 5 (recon
    R-2 confirmed it never trusted payload order). Preserving it means existing
    home_team_id / away_team_id readers keep their meaning.
    """

    provider: str
    league_key: str
    matchup_key: str
    week: int
    home_team_key: str
    away_team_key: str
    home_points: float | None
    away_points: float | None
    finality: Finality
    #: The provider's own declared winner, when it declares one. NEVER inferred
    #: from a score comparison here — a provider that declares a winner is
    #: authoritative, and one that does not has not made the statement.
    winner_team_key: str | None = None
    is_tied: bool = False
    #: WP1A — which bracket this matchup belongs to, per the provider.
    #:
    #: DEFAULTS TO UNKNOWN, AND THE DEFAULT IS THE POINT. Every existing
    #: producer — providers/yahoo/normalize.py included — constructs this DTO
    #: without the field and therefore states nothing about the bracket, which
    #: is exactly the truth: nothing in this repository can classify a Yahoo
    #: matchup as championship or consolation today. A default of CHAMPIONSHIP
    #: would have silently admitted every consolation game into the
    #: championship track, and a default of NON_CHAMPIONSHIP would have silently
    #: excluded every real one. Only UNKNOWN is honest, and it fails closed.
    bracket: MatchupBracket = MatchupBracket.UNKNOWN


@dataclass(frozen=True)
class ProviderRosterEntry:
    """One player's WEEKLY roster assignment on one team.

    `slot` is the provider's SELECTED position for that week — Yahoo's
    `selected_position.position` — and is the only thing Pool starter/bench
    classification may read (§13). `eligible_positions` carries display
    eligibility separately so nothing can quietly substitute one for the other.
    """

    provider: str
    team_key: str
    player_key: str
    player_id: str
    week: int
    slot: str
    name: str
    eligible_positions: tuple[str, ...] = ()
    nfl_team: str | None = None


@dataclass(frozen=True)
class ProviderPlayerStats:
    """One player's weekly statistics, keyed by PROVIDER stat id.

    RAW, NOT CANONICAL. Translation to the governed vocabulary happens in
    providers/yahoo/pool_source.py against
    spec/pool_stat_vocabulary_rev1_0.json, so the mapping lives in one place
    that is checkable against the authoritative artifact rather than being
    spread over the parser.

    `stat_ids_present` is a separate affirmative signal from `values` for the
    same reason betting/pool_subjects.py keeps coverage separate from numbers: a
    stat the provider did not report must become UNEVALUABLE, never 0.0, and a
    dict lookup that returns a default cannot carry that distinction.
    """

    provider: str
    player_key: str
    week: int
    values: Mapping[str, float] = field(default_factory=dict)
    stat_ids_present: frozenset[str] = frozenset()
    #: Present and non-None only where the provider reports fantasy points.
    fantasy_points: float | None = None


@dataclass(frozen=True)
class ProviderWeek:
    """Everything one provider refresh knows about one league-week.

    A single aggregate rather than four loose lists so persistence receives ONE
    consistent snapshot: a caller cannot accidentally persist matchups from one
    fetch alongside rosters from another.
    """

    league: ProviderLeague
    week: int
    teams: tuple[ProviderTeam, ...] = ()
    matchups: tuple[ProviderMatchup, ...] = ()
    roster_entries: tuple[ProviderRosterEntry, ...] = ()
    player_stats: tuple[ProviderPlayerStats, ...] = ()
    #: When the underlying data was observed. Supplied by the transport — the
    #: live one stamps the fetch, the fixture one replays the recorded value —
    #: so a frozen clock makes readiness staleness tests deterministic (§14).
    observed_at: datetime | None = None


# ── Transport ─────────────────────────────────────────────────────────────────

class ProviderTransport(Protocol):
    """The single door to provider data. §3: fixture replay satisfies exactly
    this interface, so nothing downstream can tell live from recorded — which is
    the property that makes offline certification meaningful rather than a test
    of a parallel code path.

    Every method returns RAW provider payload material. Parsing is the next
    layer's job; a transport that normalized would make the L1 raw fixture
    (§16) untestable.
    """

    #: "yahoo" — the provider this transport speaks for.
    provider: str

    def fetch_league(self, league_key: str) -> Any:
        ...

    def fetch_scoreboard(self, league_key: str, week: int) -> Any:
        ...

    def fetch_teams(self, league_key: str) -> Any:
        ...

    def fetch_team_roster(self, league_key: str, team_key: str,
                          week: int) -> Any:
        ...

    def observed_at(self) -> datetime:
        """When this transport's data was observed.

        On a live transport, now. On a fixture transport, the recorded capture
        instant. Readiness measurement (§14) stamps THIS rather than wall-clock
        time, so replaying a fixture twice produces the same measurement age and
        the 24-hour staleness tests are deterministic.
        """
        ...


class ProviderStatCoverage(Protocol):
    """What a provider can actually MEASURE, as opposed to what it documents.

    §13: "Only advertise SUPPORTED_STATS that are actually available in the
    payload/provider data." A provider adaptor answers this from the payload in
    front of it, never from the vocabulary's documented mapping — the vocabulary
    says which Yahoo stat id CARRIES passing yards, not whether this particular
    response contained it.
    """

    def supported_stats(self) -> frozenset[str]:
        ...


def sorted_team_pair(a: str, b: str) -> tuple[str, str]:
    """The canonical orientation of an unordered provider team pair (§5).

    Sorting is what makes a mirrored payload produce a byte-identical matchup
    key. It sorts on the provider's own ordinal where both keys expose one, so
    the resulting home/away assignment matches the "home = lower team id"
    convention yahoo_scoreboard.py has used since before Sprint 6 and existing
    home_team_id readers keep their meaning. Where an ordinal cannot be parsed
    it falls back to a plain string sort, which is still deterministic and still
    mirror-stable — it just may not agree with the legacy convention, and a key
    that cannot be parsed is not one the legacy convention ever covered.
    """
    def ordinal(key: str) -> tuple[int, str]:
        tail = key.rsplit(".", 1)[-1]
        try:
            return (int(tail), key)
        except ValueError:
            # Sorts every unparseable key after every parseable one, so the two
            # groups never interleave differently between calls.
            return (2 ** 31, key)

    return tuple(sorted((a, b), key=ordinal))  # type: ignore[return-value]


def derive_matchup_key(league_key: str, week: int,
                       team_key_a: str, team_key_b: str) -> str:
    """The canonical, mirror-stable provider matchup key (§5).

    Yahoo supplies no matchup identifier, so identity is CONSTRUCTED from facts
    that are provider-stable: the league key, the week, and the two team keys in
    canonical order. Swapping the two arguments returns the same string, which
    is what makes a mirrored payload collide on uq_matchups_provider_key instead
    of inserting a second row.
    """
    low, high = sorted_team_pair(team_key_a, team_key_b)
    return f"{league_key}.w.{week}.m.{low}~{high}"


def orient(matchup_teams: Sequence[str]) -> tuple[str, str]:
    """(home_team_key, away_team_key) for an unordered provider pair."""
    if len(matchup_teams) != 2:
        raise ValueError(
            f"a matchup has exactly two participants; got {len(matchup_teams)}. "
            f"Refusing to guess which of {list(matchup_teams)!r} are playing.")
    return sorted_team_pair(matchup_teams[0], matchup_teams[1])
