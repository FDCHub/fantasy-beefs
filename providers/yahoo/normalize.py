"""C — normalization. Parsed Yahoo dicts to provider-neutral DTOs.

THIS IS WHERE PAYLOAD ORDER DIES. parse.py preserves the order Yahoo listed the
two teams in, because a decoder should report what the bytes said. This module
throws that order away and derives orientation from the canonical sort in
providers/base.py (§5, S6-R1). After this line no downstream layer can tell
which team Yahoo listed first, which is exactly the guarantee C-5 tests.

NOTHING BELOW READS A NAME. Team names and manager nicknames pass through into
the DTOs as display data, and no branch in this file consults them.

THE WINNER IS THE PROVIDER'S, OR NOBODY'S. Sprint 1-5's yahoo_scoreboard.py
parsed `winner_team_key` only when the matchup was final and untied, and that
behavior is preserved exactly: a non-final matchup has no winner even if one
side is ahead, and a tie has no winner even though it is final. Deriving a
winner from a score comparison here would create a second, disagreeing source
of truth about who won.
"""

from __future__ import annotations

from datetime import datetime

from providers.base import (
    Finality,
    ProviderLeague,
    ProviderMatchup,
    ProviderPlayerStats,
    ProviderRosterEntry,
    ProviderTeam,
    ProviderWeek,
    derive_matchup_key,
    orient,
)
from providers.errors import ProviderParseError
from providers.yahoo.finality import finality_from_status

PROVIDER = "yahoo"


def normalize_league(parsed: dict) -> ProviderLeague:
    """Parsed league dict -> ProviderLeague.

    `season_final_week` comes from Yahoo's `end_week` and `playoff_start_week`
    from its own field. Both stay None when Yahoo did not report them: §12 makes
    these load-bearing once frozen, and a default substituted here would freeze
    as though it had been measured.
    """
    return ProviderLeague(
        provider=PROVIDER,
        league_key=parsed["league_key"],
        name=parsed.get("name") or "",
        season=parsed.get("season") or 0,
        current_week=parsed.get("current_week"),
        season_final_week=parsed.get("end_week"),
        playoff_start_week=parsed.get("playoff_start_week"),
    )


def normalize_team(parsed: dict) -> ProviderTeam:
    """Parsed team dict -> ProviderTeam.

    `team_id` is the provider's within-league ordinal, parsed from the compound
    key when the payload did not state it separately. The COMPOUND KEY remains
    the identity; the ordinal is a convenience for resolving scoreboard payloads
    that quote only the ordinal, and is never used alone across leagues.
    """
    team_key = parsed["team_key"]
    raw_id = str(parsed.get("team_id") or "").strip()
    if not raw_id:
        raw_id = team_key.rsplit(".", 1)[-1]
    try:
        team_id = int(raw_id)
    except ValueError as exc:
        raise ProviderParseError(
            f"team {team_key!r} has no parseable within-league ordinal "
            f"({raw_id!r}). Refusing to invent one.") from exc

    return ProviderTeam(
        provider=PROVIDER,
        team_key=team_key,
        team_id=team_id,
        name=parsed.get("name") or "",
        manager=parsed.get("manager"),
        manager_email=parsed.get("manager_email"),
    )


def normalize_matchup(parsed: dict, *, league_key: str,
                      week: int) -> ProviderMatchup:
    """One parsed matchup -> one canonically oriented ProviderMatchup."""
    teams = parsed["teams"]
    if len(teams) != 2:
        raise ProviderParseError(
            f"matchup in week {week} of {league_key} has {len(teams)} "
            f"participants, not 2.")

    by_key = {t["team_key"]: t for t in teams}
    if len(by_key) != 2:
        raise ProviderParseError(
            f"matchup in week {week} of {league_key} lists the same team key "
            f"twice ({[t['team_key'] for t in teams]!r}). A team cannot play "
            f"itself; this is a corrupt payload, not a playable game.")

    # ORIENTATION: canonical sort of the two PROVIDER KEYS. Payload order — the
    # order `teams` arrived in — is not consulted.
    home_key, away_key = orient(list(by_key))

    finality = finality_from_status(parsed.get("status"))

    winner_key = None
    if finality.is_affirmatively_final and not parsed.get("is_tied"):
        winner_key = parsed.get("winner_team_key") or None

    return ProviderMatchup(
        provider=PROVIDER,
        league_key=league_key,
        matchup_key=derive_matchup_key(league_key, week, home_key, away_key),
        week=week,
        home_team_key=home_key,
        away_team_key=away_key,
        home_points=by_key[home_key].get("points"),
        away_points=by_key[away_key].get("points"),
        finality=finality,
        winner_team_key=winner_key,
        is_tied=bool(parsed.get("is_tied")),
    )


def normalize_scoreboard(parsed: dict, *,
                         week: int | None = None) -> tuple[ProviderMatchup, ...]:
    """Parsed scoreboard -> the week's matchups, canonically oriented.

    Returns an empty tuple for a week past the end of the schedule — the case
    Sprint 1-5 signalled with a None return. An empty week is a legitimate
    answer, not a failure, and §6 relies on being able to distinguish it from a
    week that has matchups nobody should ingest yet.
    """
    league_key = parsed["league_key"]
    effective_week = week if week is not None else parsed.get("week")
    if effective_week is None:
        if not parsed.get("matchups"):
            return ()
        raise ProviderParseError(
            f"scoreboard for {league_key} carries matchups but no week number; "
            f"a matchup with no week cannot be placed in the schedule.")

    return tuple(
        normalize_matchup(m, league_key=league_key, week=int(effective_week))
        for m in parsed.get("matchups", ())
    )


def normalize_roster(parsed: dict, *, week: int | None = None
                     ) -> tuple[tuple[ProviderRosterEntry, ...],
                                tuple[ProviderPlayerStats, ...]]:
    """Parsed roster -> (weekly roster entries, weekly player stats).

    Two return values because they answer two different questions and §13 keeps
    them apart: the SLOT decides starter/bench, the STATS decide the metric. A
    player with a slot and no stats is a started player whose numbers are
    missing — which must read as UNEVALUABLE, and can only do so if the two
    facts travel separately.

    A player with no `selected_position` is SKIPPED from the roster entries.
    Fail-closed: an unknown slot cannot be asserted to be a starter, which is
    the same reading betting/pool_subjects.is_active_starter takes for a NULL
    slot.
    """
    team_key = parsed["team_key"]
    effective_week = week if week is not None else parsed.get("week")
    if effective_week is None:
        raise ProviderParseError(
            f"roster for {team_key} carries no week; a weekly roster slot "
            f"without a week cannot be attributed to a week.")
    effective_week = int(effective_week)

    entries: list[ProviderRosterEntry] = []
    stats: list[ProviderPlayerStats] = []

    for player in parsed.get("players", ()):
        slot = player.get("selected_position")
        if slot:
            entries.append(ProviderRosterEntry(
                provider=PROVIDER,
                team_key=team_key,
                player_key=player["player_key"],
                player_id=str(player.get("player_id") or ""),
                week=effective_week,
                slot=slot,
                name=player.get("name") or "",
                eligible_positions=tuple(player.get("eligible_positions") or ()),
                nfl_team=player.get("nfl_team"),
            ))

        raw_stats = player.get("stats")
        if raw_stats is None:
            # NO STATS RECORD IS NOT AN EMPTY ONE. The parser returns None only
            # when the payload carried no player_stats node at all, and no DTO
            # is emitted for that player — so a downstream lookup MISSES rather
            # than finding an empty record. `pool_source` reads that miss as
            # "this starter was never measured" and withdraws the team's
            # coverage; an empty-but-present DTO would instead have read as
            # "measured, scored nothing", which is a different and much more
            # dangerous claim (§13).
            continue
        stats.append(ProviderPlayerStats(
            provider=PROVIDER,
            player_key=player["player_key"],
            week=effective_week,
            values=dict(raw_stats),
            # AFFIRMATIVE COVERAGE. The set of stat ids the payload actually
            # carried — not the set the vocabulary says Yahoo could carry.
            # pool_source.py turns this into canonical coverage, and a stat
            # absent here becomes UNEVALUABLE rather than 0.0 (§13).
            stat_ids_present=frozenset(raw_stats),
            fantasy_points=player.get("points"),
        ))

    return tuple(entries), tuple(stats)


def build_week(*, league: ProviderLeague, week: int,
               teams: tuple[ProviderTeam, ...],
               matchups: tuple[ProviderMatchup, ...],
               roster_entries: tuple[ProviderRosterEntry, ...] = (),
               player_stats: tuple[ProviderPlayerStats, ...] = (),
               observed_at: datetime | None = None) -> ProviderWeek:
    """Assemble one consistent league-week snapshot."""
    return ProviderWeek(
        league=league, week=week, teams=teams, matchups=matchups,
        roster_entries=roster_entries, player_stats=player_stats,
        observed_at=observed_at,
    )