"""
providers/yahoo/week_snapshot.py — WP2A · the ONE production assembly of a
ProviderWeek that carries roster entries and player stats.

THE GAP THIS CLOSES. `providers/yahoo/pool_source.py` implements the certified
`PoolStatSource` boundary over a `ProviderWeek`, indexing `snapshot.player_stats`
and `snapshot.roster_entries`. The only production ingestion path,
`notifications/tuesday_sync.py::_step_refresh_scores`, calls
`normalize.build_week()` with league, week, teams and matchups ONLY — and
`build_week` defaults `roster_entries=()` and `player_stats=()`. Every snapshot
produced in production therefore carried neither collection, so the Pool stat
source could not be constructed from anything the running product had. That, not
a missing route, is why governed Pool settlement was unreachable.

NOTHING NEW IS INVENTED HERE. Every step below already existed and is already
certified: `transport.fetch_team_roster()` is part of the `ProviderTransport`
protocol in `providers/base.py`; `parse.parse_roster()` and
`normalize.normalize_roster()` are the certified parser and normalizer; and
`normalize.build_week()` has always accepted both collections. This module is
the assembly that was missing, written once so ingestion and settlement cannot
drift into two different ideas of what a week's snapshot is.

RECONSTRUCTED AT USE TIME, NOT PERSISTED (architecture choice B). Roster
ENTRIES are already persisted by `persist._persist_roster` into `RosterSlot`,
but player STATS have no persistence model anywhere in the certified design —
there is no table, no ORM class and no writer for `ProviderPlayerStats`. Adding
one would be new persistence beyond what the existing design requires, and it
would introduce a second source of truth for a value the provider already owns.
So a settlement rebuilds the snapshot through this same gateway instead. That is
sound precisely because `parse` and `normalize` are pure functions of the
payload: the replay transport returns identical bytes, so the rebuilt snapshot
is byte-identical to the ingested one, which the determinism test asserts rather
than assumes.

IDENTITY COMES FROM THE PAYLOAD, NEVER FROM AN ORDINAL. Team keys are read from
the teams DTO the provider itself returned, so `provider_team_key` identity is
preserved end to end. The certification harness iterates `t.1 … t.6` because its
corpus is fixed; a production league has whatever teams Yahoo says it has, and
guessing an ordinal range would silently truncate a league of a different size.

ORDER INDEPENDENCE. Roster entries and player stats are accumulated per team and
returned in a deterministic order derived from the sorted team key, not from the
order the provider happened to answer in. Two runs that receive the same teams
in different orders produce equal snapshots.
"""

from __future__ import annotations

from providers.base import ProviderWeek
from providers.yahoo import normalize, parse


def fetch_week_snapshot(transport, *, league_key: str, week: int,
                        with_rosters: bool = False) -> ProviderWeek:
    """Assemble one `ProviderWeek` through the certified provider pipeline.

    `with_rosters=True` additionally fetches every team's roster for the week
    and normalizes it into the `roster_entries` and `player_stats` collections
    the Pool stat source consumes. It is off by default so existing callers that
    only need matchup finality do not pay for N roster fetches they never read.

    Raises whatever the transport and parser raise. Refusing loudly is the
    certified behaviour — a snapshot assembled from a partial fetch would be a
    week that silently lost a team's players, and every Pool subject scoped to
    that team would then evaluate against absent data rather than refusing.
    """
    league = normalize.normalize_league(
        parse.parse_league(transport.fetch_league(league_key)))
    teams = tuple(normalize.normalize_team(t)
                  for t in parse.parse_teams(transport.fetch_teams(league_key)))
    matchups = normalize.normalize_scoreboard(
        parse.parse_scoreboard(transport.fetch_scoreboard(league_key, week)),
        week=week)

    entries: tuple = ()
    stats: tuple = ()
    if with_rosters:
        all_entries: list = []
        all_stats: list = []
        # Sorted by the provider's own team key so the assembled collections do
        # not inherit the order the teams payload happened to arrive in.
        for team_key in sorted(t.team_key for t in teams):
            e, s = normalize.normalize_roster(
                parse.parse_roster(
                    transport.fetch_team_roster(league_key, team_key, week)),
                week=week)
            all_entries.extend(e)
            all_stats.extend(s)
        entries = tuple(all_entries)
        stats = tuple(all_stats)

    return normalize.build_week(
        league=league, week=week, teams=teams, matchups=matchups,
        roster_entries=entries, player_stats=stats,
        observed_at=transport.observed_at())


def bind_pool_stat_source(db, snapshot: ProviderWeek, *, league_id: int):
    """Bind the certified Yahoo Pool stat source to a session and resolver.

    Kept beside the snapshot assembly because the two are always used together
    and the binding has one non-obvious requirement: the identity resolver is
    mandatory, since mapping a provider team key to an internal team id is the
    one thing the adaptor cannot do alone. S6-R1 forbids the obvious shortcut of
    matching on the team name carried in the DTO.
    """
    from providers.yahoo.identity import build_team_identity_resolver
    from providers.yahoo.pool_source import YahooProviderStatSource

    resolver = build_team_identity_resolver(db, league_id=league_id)
    return YahooProviderStatSource(snapshot).bind(db, resolver)