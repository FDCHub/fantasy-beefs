"""The deterministic Demo scenario — one league's whole season, as arithmetic.

EVERYTHING HERE IS A PURE FUNCTION OF (league_key, week, team, player index).
There is no randomness, no clock and no stored state, which is what makes a
Demo league REPLAYABLE: refreshing week 3 twice produces byte-identical DTOs, two
Demo leagues created a month apart hold the same facts, and a certification run
can assert an exact winner rather than "somebody won". WP2 §12 requires exactly
this and forbids the alternative.

TWO DEMO LEAGUES NEVER COLLIDE, because every identifier below is derived from
the league key and the league key carries a per-league token. `uq_teams_
provider_key` is unique on (provider, provider_team_key) ACROSS leagues — one
provider team is one internal team, everywhere — so a fixed "demo.t.1" would
have made the second Demo league unbindable.

── THE SEASON'S SHAPE, AND WHY IT IS SHORT ──────────────────────────────────

    start_week          1
    playoff_start_week  5      regular season weeks 1-4
    season_final_week   6      postseason weeks 5 (semifinals) and 6 (final)
    teams               6
    playoff_team_count  4      no byes: round one IS the field

NOTHING DOWNSTREAM IS TOLD ANY OF THAT AS A CONSTANT. The boundaries travel on
`ProviderLeague` and are reconciled by `providers/persist.py` exactly as Yahoo's
are, so the Demo league's economy derives `playoff_start_week - start_week = 4`
regular-season weeks through the ECONCFG-F1 formula rather than through a
hardcoded 14. A Demo season therefore issues 10 x 4 + 80 = 120 Credits, and the
fact that this is NOT the familiar 220 is the point: WP1D's parameterization is
exercised rather than asserted.

FOUR REGULAR WEEKS IS ENOUGH TO BE THE PRODUCT and short enough to play through.
Every state WP2 §12 lists — an open week, a finalized week, a Pool slate, claims,
a zero-winner Pool, a Skunk assessment, semifinals, a championship game, an
official third-place game, a season close — occurs inside it.

── WHAT THE FEED CAN AND CANNOT MEASURE ─────────────────────────────────────

The Demo feed reports the SAME canonical stats a live Yahoo feed can report, and
deliberately not one more. `pass_attempts` and `completions` carry no Yahoo stat
id in the governed vocabulary, so Yahoo cannot supply them and neither does this
— which keeps `opportunities` unavailable and keeps the Demo league's set of
gate-2-ready definitions an honest preview of a live one. A Demo that advertised
stats the product cannot actually get would be a demo of a different product.

── THE POSTSEASON IS SCRIPTED, NOT SCORED ───────────────────────────────────

Bracket membership and the winner of every postseason game are STATED by this
scenario, and `season/championship_track.py` reads only the statement. The
scores are then arranged so the declared winner holds the larger one — a
presentational courtesy for a synthetic feed, and never an input: swapping the
two numbers would not change who advances.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from providers.base import (
    Finality,
    MatchupBracket,
    ProviderLeague,
    ProviderMatchup,
    ProviderPlayerStats,
    ProviderRosterEntry,
    ProviderTeam,
    ProviderWeek,
    derive_matchup_key,
    orient,
)
from providers.demo import DEMO_LEAGUE_KEY_PREFIX, DEMO_PROVIDER

# ── Season shape ──────────────────────────────────────────────────────────────

TEAM_COUNT = 6
START_WEEK = 1
PLAYOFF_START_WEEK = 5
SEASON_FINAL_WEEK = 6
PLAYOFF_TEAM_COUNT = 4

#: Regular-season pairings, by week. Each week pairs all six teams once, so the
#: MATCHUP census is three subjects every week and no team is ever idle.
REGULAR_SCHEDULE: dict[int, tuple[tuple[int, int], ...]] = {
    1: ((1, 2), (3, 4), (5, 6)),
    2: ((1, 3), (2, 5), (4, 6)),
    3: ((1, 4), (2, 6), (3, 5)),
    4: ((1, 5), (2, 4), (3, 6)),
}

#: The postseason, as (week, home_ordinal, away_ordinal, winner_ordinal,
#: bracket). Seeds 1-4 are the championship field; 5 and 6 play a consolation
#: game alongside it in both weeks, which is the case that must never leak into
#: the championship track.
#:
#: Week 6's t3-vs-t4 game is the OFFICIAL THIRD-PLACE GAME: its participants are
#: exactly the two teams that lost week 5's championship semifinals. WP1BC
#: derives that from the semifinal losers; nothing here labels it as such, and
#: nothing needs to.
POSTSEASON_SCHEDULE: tuple[tuple[int, int, int, int, MatchupBracket], ...] = (
    (5, 1, 4, 1, MatchupBracket.CHAMPIONSHIP),
    (5, 2, 3, 2, MatchupBracket.CHAMPIONSHIP),
    (5, 5, 6, 5, MatchupBracket.NON_CHAMPIONSHIP),
    (6, 1, 2, 1, MatchupBracket.CHAMPIONSHIP),
    (6, 3, 4, 3, MatchupBracket.NON_CHAMPIONSHIP),
    (6, 5, 6, 6, MatchupBracket.NON_CHAMPIONSHIP),
)

#: The championship field, by ordinal. Stated rather than derived because a
#: provider that can classify brackets should also be able to name its field —
#: `ChampionshipFieldDeclaration` exists for the bye case, and a Demo that could
#: not answer it would exercise a weaker path than a real adapter must.
CHAMPIONSHIP_FIELD_ORDINALS = (1, 2, 3, 4)

#: The podium this scenario produces, as ordinals, for readers and for
#: certification to assert against. It is DERIVED by the production
#: determination from the games above — it is written here as documentation of
#: what those games mean, and nothing consumes it as an input.
EXPECTED_PODIUM_ORDINALS = (1, 2, 3)

# ── Roster shape ──────────────────────────────────────────────────────────────
#
# Ten players per team: eight active starters and two bench. The flex is a
# W/R/T occupied by a running back, which is the POR §1.3 case where the
# OCCUPANT's position governs; the two bench players are BN and must never
# contribute a component.

#: (slot, position) per player index.
ROSTER_SHAPE: tuple[tuple[str, str], ...] = (
    ("QB", "QB"),
    ("RB", "RB"),
    ("RB", "RB"),
    ("WR", "WR"),
    ("WR", "WR"),
    ("TE", "TE"),
    ("W/R/T", "RB"),
    ("K", "K"),
    ("BN", "WR"),
    ("BN", "QB"),
)

#: The one starter whose stats the "incomplete" revision withholds. Index 5 is a
#: TIGHT END — a started player, never the bench — so withholding it withdraws
#: the whole team frame's coverage rather than being invisible.
INCOMPLETE_TEAM_ORDINAL = 2
INCOMPLETE_PLAYER_INDEX = 5

#: Snapshot revisions. `COMPLETE` is what a healthy feed returns; `INCOMPLETE`
#: is a FINAL week whose stat feed has not caught up for one team — the WP1E
#: operational case, and the one thing about it that matters is that it is a
#: GAP, not a zero.
REVISION_COMPLETE = "complete"
REVISION_INCOMPLETE = "incomplete"

#: The fallback observation instant for a snapshot built without one.
#:
#: THE DEMO IS A LIVE PROVIDER, NOT A REPLAY, AND ITS CLOCK REFLECTS THAT.
#: `providers/fixtures/replay.py` freezes `observed_at` because it replays bytes
#: recorded in the past, and a frozen instant is what makes the 24-hour gate-2
#: staleness window crossable by arithmetic. The Demo provider is answering NOW:
#: it invents the facts at the moment it is asked, so it stamps the moment it was
#: asked, exactly as `YahooLiveTransport` does. Freezing it would have made every
#: Demo measurement permanently stale the day after this constant was written,
#: and a Demo league would have had zero gate-2-eligible definitions and drawn no
#: Pool slate at all.
#:
#: NOTHING ABOUT DETERMINISM IS LOST. The FACTS — matchups, winners, rosters,
#: stats — are a pure function of (league key, week) and do not move with the
#: clock; `snapshot_digest` covers exactly those and is stable across runs. Only
#: the measurement stamp advances, which is what a stamp is for.
DEMO_OBSERVED_AT = datetime(2025, 12, 30, 12, 0, 0, tzinfo=timezone.utc)


def league_key_for(token: str) -> str:
    """The provider league key for one Demo league.

    `token` is whatever the creating route allocated — in production the
    internal league id, which is unique by construction. Deliberately NOT
    Yahoo-shaped: nothing here can be mistaken for a real Yahoo league key, and
    the Yahoo identity namespace is untouched.
    """
    return f"{DEMO_LEAGUE_KEY_PREFIX}{token}"


@dataclass(frozen=True)
class DemoScenario:
    """One Demo league's complete, deterministic season.

    Constructed from the league key alone: every identifier, every stat and
    every result below is a pure function of it plus the week.
    """

    league_key: str
    season: int = 2025
    name: str = "FantasyStakes Demo League"

    # ── Identity ─────────────────────────────────────────────────────────────

    def team_key(self, ordinal: int) -> str:
        return f"{self.league_key}.t.{ordinal}"

    def player_key(self, ordinal: int, index: int) -> str:
        return f"{self.league_key}.p.{ordinal}{index:02d}"

    def team_name(self, ordinal: int) -> str:
        return f"Demo Team {ordinal}"

    def owner_name(self, ordinal: int) -> str:
        return f"Demo GM {ordinal}"

    def owner_email(self, ordinal: int) -> str:
        """A reserved-TLD address. It is contact data and NEVER identity —
        S6-R1 forbids resolving a team by it, and nothing does."""
        token = self.league_key.replace(".", "-")
        return f"{token}-gm{ordinal}@demo.invalid"

    @property
    def championship_field(self) -> frozenset[str]:
        return frozenset(self.team_key(n) for n in CHAMPIONSHIP_FIELD_ORDINALS)

    def ordinal_of(self, team_key: str) -> int | None:
        for ordinal in range(1, TEAM_COUNT + 1):
            if self.team_key(ordinal) == team_key:
                return ordinal
        return None

    # ── Weeks ────────────────────────────────────────────────────────────────

    @property
    def weeks(self) -> tuple[int, ...]:
        return tuple(range(START_WEEK, SEASON_FINAL_WEEK + 1))

    def pairings(self, week: int) -> tuple[tuple[int, int], ...]:
        """The (home_ordinal, away_ordinal) pairs the provider reports for a week.

        Orientation here is the SCENARIO's ordering and is not authoritative:
        `providers.base.orient` re-derives the canonical home/away from the two
        provider keys, so shuffling a pair changes nothing downstream.
        """
        if week in REGULAR_SCHEDULE:
            return REGULAR_SCHEDULE[week]
        return tuple((a, b) for w, a, b, _win, _bracket in POSTSEASON_SCHEDULE
                     if w == week)

    def bracket_of(self, week: int, a: int, b: int) -> MatchupBracket:
        """The provider's bracket statement for one game.

        A REGULAR-SEASON GAME IS NOT NON_CHAMPIONSHIP; it is UNKNOWN. The
        championship track is only asked about postseason weeks, and claiming
        "not a championship game" for week 2 would be stating something this
        provider was never asked and the domain never reads.
        """
        pair = {a, b}
        for w, home, away, _winner, bracket in POSTSEASON_SCHEDULE:
            if w == week and {home, away} == pair:
                return bracket
        return MatchupBracket.UNKNOWN

    def scripted_winner(self, week: int, a: int, b: int) -> int | None:
        pair = {a, b}
        for w, home, away, winner, _bracket in POSTSEASON_SCHEDULE:
            if w == week and {home, away} == pair:
                return winner
        return None

    # ── Statistics ───────────────────────────────────────────────────────────

    def player_stat_values(self, ordinal: int, index: int,
                           week: int) -> dict[str, float]:
        """One starter's canonical weekly stat line. Pure arithmetic.

        KEYED BY CANONICAL NAME, NOT BY A PROVIDER STAT ID. The Demo provider's
        own stat vocabulary IS the governed one, so `DemoStatMap` is the
        identity — which is a legitimate provider mapping, not a bypass:
        `providers/week_stat_source.py` still translates through a map, still
        drops anything ungoverned, and still measures support from what this
        function actually returned.
        """
        _slot, position = ROSTER_SHAPE[index]
        t, w, i = ordinal, week, index

        if position == "QB":
            return {
                "passing_yards": float(180 + ((t * 23 + w * 31) % 150)),
                "passing_td": float((t + w) % 4),
                "interceptions_thrown": float((t * 3 + w) % 3),
                "rush_attempts": float((t + w) % 5),
                "rushing_yards": float((t * 5 + w * 3) % 30),
                "rushing_td": float(1 if (t + w) % 5 == 0 else 0),
                "fumbles_lost": float((t + w) % 2),
                "two_point_conversions": float(1 if (t * w) % 7 == 0 else 0),
            }

        if position == "RB":
            receptions = float((t + w + i) % 6)
            return {
                "rush_attempts": float(8 + ((t * 3 + w * 5 + i) % 14)),
                "rushing_yards": float(30 + ((t * 17 + w * 29 + i * 11) % 90)),
                "rushing_td": float((t + w + i) % 3),
                "receptions": receptions,
                "receiving_yards": float((t * 7 + w * 13 + i * 5) % 55),
                "receiving_td": float(1 if (t + w + i) % 8 == 0 else 0),
                "targets": receptions + float((t + i) % 3),
                "fumbles_lost": float(1 if (t * w + i) % 11 == 0 else 0),
            }

        if position in ("WR", "TE"):
            receptions = float(2 + ((t * 3 + w * 7 + i) % 8))
            return {
                "receptions": receptions,
                "receiving_yards": float(20 + ((t * 19 + w * 23 + i * 13) % 95)),
                "receiving_td": float((t + w + i) % 3),
                "targets": receptions + 1.0 + float((t + i) % 4),
                "rush_attempts": 0.0,
                "rushing_yards": 0.0,
                "fumbles_lost": 0.0,
            }

        # Kicker. The five bracket counters are what make the DERIVED
        # `field_goals_made` available — coverage of the inputs is coverage of
        # the derived operand, which is the accepted Sprint 4 rule.
        return {
            "field_goals_made_0_19": float((t + w) % 2),
            "field_goals_made_20_29": float((t + w + 1) % 2),
            "field_goals_made_30_39": float((t * 2 + w) % 3),
            "field_goals_made_40_49": float((t + w * 2) % 2),
            "field_goals_made_50_plus": float(1 if (t + w) % 5 == 0 else 0),
            "extra_points_made": float(1 + ((t + w) % 4)),
        }

    def player_points(self, ordinal: int, index: int, week: int) -> float:
        """The provider's own reported fantasy points for one starter.

        A PROVIDER STATEMENT, NOT A RECOMPUTATION OF LEAGUE SCORING. Yahoo
        reports `player_points` and FantasyStakes consumes it as a fact; this
        does the same. It is derived from the stat line so the two agree, which
        is what a real feed's numbers do.
        """
        values = self.player_stat_values(ordinal, index, week)
        points = (
            values.get("passing_yards", 0.0) / 25.0
            + values.get("passing_td", 0.0) * 4.0
            - values.get("interceptions_thrown", 0.0) * 2.0
            + values.get("rushing_yards", 0.0) / 10.0
            + values.get("rushing_td", 0.0) * 6.0
            + values.get("receiving_yards", 0.0) / 10.0
            + values.get("receiving_td", 0.0) * 6.0
            + values.get("receptions", 0.0) * 0.5
            + values.get("two_point_conversions", 0.0) * 2.0
            - values.get("fumbles_lost", 0.0) * 2.0
            + values.get("extra_points_made", 0.0)
            + (values.get("field_goals_made_0_19", 0.0)
               + values.get("field_goals_made_20_29", 0.0)) * 3.0
            + values.get("field_goals_made_30_39", 0.0) * 3.0
            + values.get("field_goals_made_40_49", 0.0) * 4.0
            + values.get("field_goals_made_50_plus", 0.0) * 5.0
        )
        return round(points, 2)

    def team_points(self, ordinal: int, week: int) -> float:
        """A team's reported total — the sum of its ACTIVE STARTERS' points.

        Bench players are excluded, which is what makes this number agree with
        the roster the Pool engine reads. It is the provider's statement of the
        matchup score and is never used to decide who won.
        """
        total = sum(self.player_points(ordinal, index, week)
                    for index, (slot, _pos) in enumerate(ROSTER_SHAPE)
                    if slot != "BN")
        return round(total, 2)


# ── DTO construction ──────────────────────────────────────────────────────────

def league_dto(scenario: DemoScenario, *, current_week: int) -> ProviderLeague:
    """The Demo league's normalized identity and boundaries.

    `current_week` is the DEMO'S OWN PROGRESS and is supplied by the caller from
    persisted state (`League.provider_current_week`), never from the clock. It
    governs the §6 ingestion horizon exactly as Yahoo's does, which is what
    stops a Demo league pre-creating its whole schedule and silently expanding
    the set of weeks its season close demands a Skunk assessment for.

    `playoff_team_count` IS STATED, and Yahoo's is not. That difference is real
    and is not papered over: a provider that knows its field size lets
    `season/championship_track.py` cross-check a reconstructed field against it,
    and a provider that does not leaves the count None.
    """
    return ProviderLeague(
        provider=DEMO_PROVIDER,
        league_key=scenario.league_key,
        name=scenario.name,
        season=scenario.season,
        current_week=current_week,
        season_final_week=SEASON_FINAL_WEEK,
        playoff_start_week=PLAYOFF_START_WEEK,
        start_week=START_WEEK,
        playoff_team_count=PLAYOFF_TEAM_COUNT,
    )


def team_dtos(scenario: DemoScenario) -> tuple[ProviderTeam, ...]:
    return tuple(
        ProviderTeam(
            provider=DEMO_PROVIDER,
            team_key=scenario.team_key(n),
            team_id=n,
            name=scenario.team_name(n),
            manager=scenario.owner_name(n),
            manager_email=scenario.owner_email(n),
        )
        for n in range(1, TEAM_COUNT + 1)
    )


def matchup_dtos(scenario: DemoScenario, *, week: int,
                 final: bool) -> tuple[ProviderMatchup, ...]:
    """One week's matchups, oriented and keyed by the certified canonical rule.

    AN OPEN WEEK CARRIES NO SCORE AND NO WINNER. `home_points` stays None rather
    than 0.0 — the DTO refuses that conflation and so does this — and finality
    is NOT_FINAL, so `finalized_at` stays NULL and no money can move.

    A FINAL WEEK CARRIES A DECLARED WINNER. It is the scenario's statement, and
    for a postseason game it is the SCRIPTED one: the scores are then ordered so
    the declared winner holds the larger, which is cosmetic. Nothing downstream
    compares them.
    """
    out: list[ProviderMatchup] = []
    for a, b in scenario.pairings(week):
        home_key, away_key = orient([scenario.team_key(a), scenario.team_key(b)])
        home_ord = scenario.ordinal_of(home_key)
        away_ord = scenario.ordinal_of(away_key)
        bracket = scenario.bracket_of(week, a, b)
        key = derive_matchup_key(scenario.league_key, week, home_key, away_key)

        if not final:
            out.append(ProviderMatchup(
                provider=DEMO_PROVIDER, league_key=scenario.league_key,
                matchup_key=key, week=week,
                home_team_key=home_key, away_team_key=away_key,
                home_points=None, away_points=None,
                finality=Finality.NOT_FINAL, winner_team_key=None,
                bracket=bracket))
            continue

        home_points = scenario.team_points(home_ord, week)
        away_points = scenario.team_points(away_ord, week)

        scripted = scenario.scripted_winner(week, a, b)
        if scripted is not None:
            winner_ord = scripted
        else:
            winner_ord = home_ord if home_points >= away_points else away_ord

        # Order the totals so the declared winner holds the larger one, and
        # break an exact tie deterministically. A tie is a legitimate provider
        # fact but not one this scenario intends to produce, and leaving it to
        # arithmetic accident would make the demo's own results unstable under
        # an unrelated stat-formula edit.
        high, low = max(home_points, away_points), min(home_points, away_points)
        if high == low:
            high = round(high + 0.5, 2)
        if winner_ord == home_ord:
            home_points, away_points = high, low
        else:
            home_points, away_points = low, high

        out.append(ProviderMatchup(
            provider=DEMO_PROVIDER, league_key=scenario.league_key,
            matchup_key=key, week=week,
            home_team_key=home_key, away_team_key=away_key,
            home_points=home_points, away_points=away_points,
            finality=Finality.FINAL,
            winner_team_key=scenario.team_key(winner_ord),
            bracket=bracket))
    return tuple(out)


def roster_dtos(scenario: DemoScenario, *, week: int, revision: str,
                with_stats: bool = True
                ) -> tuple[tuple[ProviderRosterEntry, ...],
                           tuple[ProviderPlayerStats, ...]]:
    """The week's roster entries and player stats, in deterministic key order.

    TWO COLLECTIONS, NEVER ONE, AND THEY ARE PUBLISHED AT DIFFERENT TIMES. The
    SLOT decides starter/bench and the STATS decide the metric; §13 keeps them
    apart so a started player whose numbers are missing reads as UNEVALUABLE
    rather than as a measured zero.

    `with_stats=False` IS AN OPEN WEEK, AND IT IS THE FAITHFUL SHAPE. A real
    provider publishes LINEUPS before kickoff — that is what a fantasy league
    does all week — and publishes NUMBERS only once the games are played. The
    Demo does the same: an open week carries every roster entry and not one stat
    record. Withholding the lineups too would have been simpler and wrong, and
    it would have made a Versus wager on an unplayed game impossible, since the
    wager engine reads the week's starters.

    `revision` is the WHOLE incomplete-data control. Under `INCOMPLETE` one
    started player on one team gets NO STATS DTO AT ALL — the collection simply
    does not contain a record for that player key, which is exactly how a real
    feed reports a player it has not measured, and is what
    `providers/week_stat_source.py` reads as a withdrawal of that team's
    coverage. It is emphatically not a record of zeroes.
    """
    entries: list[ProviderRosterEntry] = []
    stats: list[ProviderPlayerStats] = []

    for ordinal in range(1, TEAM_COUNT + 1):
        team_key = scenario.team_key(ordinal)
        for index, (slot, position) in enumerate(ROSTER_SHAPE):
            player_key = scenario.player_key(ordinal, index)
            entries.append(ProviderRosterEntry(
                provider=DEMO_PROVIDER, team_key=team_key,
                player_key=player_key,
                player_id=f"{ordinal}{index:02d}",
                week=week, slot=slot,
                name=f"Demo {position} {ordinal}-{index}",
                eligible_positions=(position,),
                nfl_team="DMO"))

            withheld = (revision == REVISION_INCOMPLETE
                        and ordinal == INCOMPLETE_TEAM_ORDINAL
                        and index == INCOMPLETE_PLAYER_INDEX)
            if withheld or not with_stats:
                continue

            values = scenario.player_stat_values(ordinal, index, week)
            stats.append(ProviderPlayerStats(
                provider=DEMO_PROVIDER, player_key=player_key, week=week,
                values=values,
                # AFFIRMATIVE COVERAGE — the stats this record actually carries,
                # not the ones the vocabulary says a provider could carry.
                stat_ids_present=frozenset(values),
                fantasy_points=scenario.player_points(ordinal, index, week)))

    return tuple(entries), tuple(stats)


def week_snapshot(scenario: DemoScenario, *, week: int, current_week: int,
                  final: bool, with_rosters: bool = False,
                  revision: str = REVISION_COMPLETE,
                  observed_at: datetime | None = None) -> ProviderWeek:
    """One consistent Demo league-week snapshot.

    Assembled as ONE aggregate for the same reason Yahoo's is: persistence must
    not be able to receive matchups from one observation alongside rosters from
    another.

    LINEUPS ACCOMPANY ANY WEEK; STATS ACCOMPANY ONLY A FINAL ONE. A team's
    starters are set before kickoff and a real provider publishes them then —
    which is what makes a Versus wager on an unplayed game possible at all. The
    NUMBERS are a different fact and do not exist until the games are played;
    reporting a stat line for an unplayed game would be the one thing a demo
    must never do, because it would be inventing a result.
    """
    entries: tuple = ()
    stats: tuple = ()
    if with_rosters:
        entries, stats = roster_dtos(scenario, week=week, revision=revision,
                                     with_stats=final)

    return ProviderWeek(
        league=league_dto(scenario, current_week=current_week),
        week=week,
        teams=team_dtos(scenario),
        matchups=matchup_dtos(scenario, week=week, final=final),
        roster_entries=entries,
        player_stats=stats,
        observed_at=observed_at or DEMO_OBSERVED_AT,
    )
