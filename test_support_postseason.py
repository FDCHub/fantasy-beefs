"""
test_support_postseason.py — shared postseason fixture construction.

INFRASTRUCTURE, NOT A TEST. No assertions live here, and nothing in this module
opens a database harness — importing it must never claim a `TEST_DATABASE_URL`,
because two suites import it and a module-level harness would make the second
import fail on a destination clash.

WHY THIS EXISTS. WP1B (Pools) and WP1C (Versus) certify against the SAME
synthetic championship league. Two private copies of the mirroring code would
drift the first time either package amended its fixture, and the two suites would
then quietly be testing different worlds while both reporting green. One copy,
imported by both, makes a divergence impossible rather than unlikely.

Everything is built through REAL production paths — the real ledger posting, the
real derived matchup keys, the certified identity columns — so a fixture cannot
pass by constructing a state production could never reach.
"""

from __future__ import annotations

from datetime import datetime, timezone

#: Every fixture matchup is economically final. These suites model weeks whose
#: games are OVER; a NULL here would assert the opposite and the finality gate
#: would refuse settlement for a reason unrelated to what is being tested.
FIXTURE_FINAL = datetime(2025, 12, 30, 12, 0, tzinfo=timezone.utc)


#: The provider a Demo/synthetic league binds its TEAM IDENTITY to.
SYNTHETIC_PROVIDER = "synthetic"

#: The name the synthetic POSTSEASON source registers under. It is a source
#: name, not a provider name, and the two are deliberately separate: a league's
#: teams can be identified by Yahoo while its bracket is stated by something
#: else, because no supported identity provider states brackets at all. See
#: `providers/postseason_bracket.register_postseason_source`.
SYNTHETIC_POSTSEASON_SOURCE = "synthetic-postseason"


class RecordedBracketSource:
    """A postseason bracket source that answers from RECORDED facts only.

    WP1D — this is what a Demo provider is, and what a Yahoo adapter would be
    once captured evidence settles what Yahoo reports: something that STATES
    which games are championship games rather than inferring it. It infers
    nothing. A matchup nobody recorded stays UNKNOWN and fails the determination
    closed, which is the behaviour a live league gets today.

    One instance serves every league in a suite, keyed by provider league key, so
    a harness that builds a dozen leagues cannot leak one league's bracket into
    another's.
    """

    def __init__(self) -> None:
        self._brackets: dict[tuple[str, int, str], object] = {}
        self._fields: dict[str, frozenset] = {}

    def knows(self, *, league_key: str) -> bool:
        """Only the leagues a fixture actually recorded. A source that claimed
        every league would silently take over any other suite's league and
        answer UNKNOWN for it, which is worse than not claiming it."""
        return league_key in self._fields

    def record(self, league_key: str, week: int, matchup_key: str, bracket):
        self._brackets[(league_key, week, matchup_key)] = bracket

    def declare_field(self, league_key: str, team_keys) -> None:
        self._fields[league_key] = frozenset(team_keys)

    def classify_week(self, *, league_key: str, week: int, matchups):
        from dataclasses import replace

        return tuple(
            replace(m, bracket=self._brackets.get(
                (league_key, week, m.matchup_key), m.bracket))
            for m in matchups)

    def championship_field(self, *, league_key: str, season: int):
        return self._fields.get(league_key)


#: Module-level so repeated installation is the SAME object — the production
#: registry refuses to rebind a provider to a DIFFERENT source, and two suites
#: importing this module must not trip that.
SYNTHETIC_BRACKET_SOURCE = RecordedBracketSource()


def install_synthetic_bracket_source() -> RecordedBracketSource:
    """Register the synthetic postseason source, as a Demo deployment would.

    THE REGISTRY IS PRODUCTION; ONLY THE SOURCE IS SYNTHETIC. A harness that
    calls this exercises the real extension point the season-close route reads
    through, so the state it produces reaches the podium by the production path
    rather than by injection into a test-only parameter.

    IT REGISTERS UNDER ITS OWN NAME AND CLAIMS ONLY THE LEAGUES A FIXTURE
    RECORDED. Nothing here asserts that Yahoo can classify a bracket — a league
    whose games this source never recorded is not claimed, gets no
    classification, and fails closed exactly as a live Yahoo league does.
    """
    from providers.postseason_bracket import register_postseason_source

    register_postseason_source(SYNTHETIC_POSTSEASON_SOURCE,
                               SYNTHETIC_BRACKET_SOURCE)
    return SYNTHETIC_BRACKET_SOURCE


def namespaced(synthetic, suffix: str):
    """A copy of a synthetic league whose provider keys are unique to `suffix`.

    `teams.uq_teams_provider_key` is unique on (provider, provider_team_key)
    ACROSS leagues — the compound Yahoo key is globally unique in reality, so
    the constraint is right and it is the fixtures that must not collide. Each
    scenario therefore gets its own synthetic league key, and every matchup key
    is RE-DERIVED through `providers.base.derive_matchup_key` rather than
    string-patched, so the keys stay the ones production would construct.
    """
    from dataclasses import replace

    from providers.fixtures.postseason_synthetic import matchup

    old = synthetic.league_key
    new = f"{old}-{suffix}"

    def rekey(key: str) -> str:
        return key.replace(old, new, 1)

    weeks = {}
    for week, matchups in synthetic.weeks.items():
        weeks[week] = tuple(
            matchup(new, week, rekey(m.home_team_key), rekey(m.away_team_key),
                    bracket=m.bracket, finality=m.finality,
                    winner=(rekey(m.winner_team_key) if m.winner_team_key
                            else None),
                    home_points=m.home_points, away_points=m.away_points,
                    is_tied=m.is_tied)
            for m in matchups)

    return replace(
        synthetic, league_key=new,
        championship_field=frozenset(rekey(k)
                                     for k in synthetic.championship_field),
        weeks=weeks)


def build_league(db, synthetic, *, name: str, wallet_cents: int = 100_000):
    """A DB league mirroring one synthetic postseason league.

    Teams carry their provider identity so the CERTIFIED resolver can be built
    over them; matchups carry the derived `provider_matchup_key` so the
    championship join is the production join. Wallets are funded through a real
    ledger posting, never by writing the display mirror.
    """
    from db.schema import (
        League, LeagueSeasonEconomyConfig, Matchup, SeasonAllocation, Team,
        Wallet,
    )
    from ledger.ledger import post as ledger_post

    # ── THE PROVIDER CLOCK IS PART OF THE FIXTURE, NOT AN AFTERTHOUGHT ──────
    #
    # This helper builds a league mirroring a SYNTHETIC POSTSEASON fixture whose
    # weeks run through the championship, so the league it produces has by
    # construction reached — and played — its postseason. Leaving
    # `provider_current_week` unset said the opposite: that the provider had
    # reported nothing at all.
    #
    # That is not cosmetic. `economy/championship_scoring_gate.py` makes the
    # first governed postseason action freeze the regular-season Championship
    # Score, and `freeze_fantasystakes_championship` refuses to freeze a league
    # that has not reached its Yahoo postseason boundary:
    #
    #     [FS_CHAMPIONSHIP_TOO_EARLY] league 1 has not reached its Yahoo
    #     postseason boundary (provider_current_week=None,
    #     playoff_start_week=15). Refusing to freeze early.
    #
    # So every postseason case built here was refused before it began. The
    # refusal was PRODUCTION BEHAVING CORRECTLY — a regular-season score must
    # not be frozen while the provider still says the regular season is running
    # — and the fixture was simply not establishing the prerequisite a real
    # league establishes by being synced. Setting the clock to the last week the
    # provider actually reported is what a real league carries at that point;
    # the gate is left exactly as it is.
    reported_through = max(synthetic.weeks) if synthetic.weeks else None

    league = League(season=synthetic.season, name=name,
                    projection_source="fantasypros",
                    season_final_week=synthetic.season_final_week,
                    playoff_start_week=synthetic.playoff_start_week,
                    provider_current_week=reported_through)
    db.add(league)
    db.flush()

    teams: dict[str, object] = {}
    for ordinal in range(1, synthetic.team_count + 1):
        key = synthetic.team_key(ordinal)
        team = Team(league_id=league.id, team_name=f"{name}-t{ordinal}",
                    owner=f"owner-{ordinal}", email=f"{name}-{ordinal}@x.test",
                    provider="yahoo", provider_team_key=key,
                    provider_team_id=ordinal)
        db.add(team)
        db.flush()
        db.add(Wallet(team_id=team.id, balance=0.0))
        teams[key] = team
    db.flush()

    for team in teams.values():
        ledger_post([("world", -wallet_cents), (f"wallet:{team.id}", wallet_cents)],
                    door="buy_in_paid", session=db)

    # ── THE CERTIFIED CHAMPIONSHIP PREREQUISITE CHAIN ────────────────────────
    #
    # Postseason action is gated on the regular-season Championship Score being
    # frozen, and the freeze in turn refuses until the FantasyStakes
    # Championship has been ACTIVATED:
    #
    #     [FS_CHAMPIONSHIP_NOT_ACTIVATED] league N season S has no
    #     FantasyStakes Championship allocation, so no championship field has
    #     been funded. Complete championship activation before freezing.
    #
    # `test_rc2_championship.py` proves that refusal is intended, so the answer
    # is to perform the lifecycle rather than to weaken the gate. These are the
    # same base economy rows that suite establishes — an economy config and the
    # per-team Season-Opening Allocation — followed by the certified activation
    # call. Nothing here computes economics; `activate_fantasystakes_championship_stage`
    # funds the field.
    db.add(LeagueSeasonEconomyConfig(
        league_id=league.id, season=synthetic.season,
        weekly_bet_minimum_cents=1_000,
        championship_contribution_cents=8_000,
        skunk_fee_cents=1_000,
        regular_season_week_count=synthetic.playoff_start_week - 1,
        active_team_count=synthetic.team_count,
        start_week_used=1,
        playoff_start_week_used=synthetic.playoff_start_week,
        frozen_at=None,
    ))
    for team in teams.values():
        db.add(SeasonAllocation(
            league_id=league.id, team_id=team.id, season=synthetic.season,
            buyin_cents=22_000, min_reserve_cents=14_000, reserve_cents=8_000))
    db.flush()

    from economy.rc2_season_activation import (
        activate_fantasystakes_championship_stage,
    )

    activate_fantasystakes_championship_stage(league.id, db)

    for week, matchups in sorted(synthetic.weeks.items()):
        for m in matchups:
            db.add(Matchup(
                league_id=league.id, week=week,
                home_team_id=teams[m.home_team_key].id,
                away_team_id=teams[m.away_team_key].id,
                home_score=float(m.home_points or 0.0),
                away_score=float(m.away_points or 0.0),
                provider_matchup_key=m.matchup_key,
                finalized_at=FIXTURE_FINAL))
    db.flush()
    return league, teams


def track_state(synthetic, *, week: int, declare: bool = True,
                weeks_override: dict | None = None):
    """WP1A championship state for one synthetic league-week."""
    from season.championship_track import (
        ChampionshipFieldDeclaration, ChampionshipTrackInput,
        ChampionshipWeekInput, derive_championship_track_state,
    )

    source = weeks_override if weeks_override is not None \
        else synthetic.weeks_through(week)
    return derive_championship_track_state(
        ChampionshipTrackInput(
            league_key=synthetic.league_key, season=synthetic.season,
            playoff_start_week=synthetic.playoff_start_week,
            season_final_week=synthetic.season_final_week,
            playoff_team_count=synthetic.playoff_team_count,
            weeks=tuple(ChampionshipWeekInput(week=w, matchups=tuple(ms))
                        for w, ms in sorted(source.items())),
            field_declaration=(ChampionshipFieldDeclaration(
                team_keys=synthetic.championship_field) if declare else None)),
        week=week)


def record_synthetic_postseason(db, league, teams, *, semifinal_week: int,
                                championship_week: int, podium_indexes):
    """Play a four-team postseason for `league` and STATE its brackets.

    WHY SUITES THAT CERTIFY SOMETHING ELSE NEED THIS. WP1D made the Championship
    Pot's recipients a fact about the postseason, so a season close is no longer
    reachable for a league that never played one. Every route-level suite that
    drives a league to its close therefore needs a bracket — not because it is
    testing the bracket, but because a season without one cannot legitimately
    close. This is that fixture, written once.

    `podium_indexes` is (champion, runner-up, third, fourth) as indexes into
    `teams`, and the games follow from it:

        semifinal_week      champion beats third      (CHAMPIONSHIP)
                            runner-up beats fourth    (CHAMPIONSHIP)
        championship_week   champion beats runner-up  (CHAMPIONSHIP)
                            third beats fourth        (NON_CHAMPIONSHIP)

    TWO FACTS IN TWO PLACES, DELIBERATELY. The games are ordinary `Matchup`
    rows, with `finalized_at` as the only finality the close will read. WHICH
    BRACKET each belongs to is answered by the provider's registered capability,
    because no bracket column exists and inventing one would have manufactured
    the Yahoo evidence the WP1A recon reported as missing.

    BOTH WEEKS MUST BE POSTSEASON WEEKS for the league — at or after its
    `playoff_start_week`. A championship game recorded in a regular-season week
    would also be a Skunk week and a Weekly Minimum week, which is a different
    fixture with different economics.
    """
    from db.schema import Matchup
    from providers.base import MatchupBracket, derive_matchup_key, orient

    if len(podium_indexes) < 4:
        raise ValueError("a four-team bracket needs four team indexes")
    champion, runner_up, third, fourth = podium_indexes[:4]

    league_key = league.provider_league_key
    keys = [t.provider_team_key for t in teams]
    if not league_key or not all(keys):
        raise ValueError(
            f"league {league.id} or its teams carry no provider identity; the "
            f"podium is named in provider keys and cannot be recorded without "
            f"them.")

    source = install_synthetic_bracket_source()
    source.declare_field(league_key,
                         [keys[i] for i in (champion, runner_up, third, fourth)])

    games = (
        (semifinal_week, champion, third, champion, MatchupBracket.CHAMPIONSHIP),
        (semifinal_week, runner_up, fourth, runner_up, MatchupBracket.CHAMPIONSHIP),
        (championship_week, champion, runner_up, champion,
         MatchupBracket.CHAMPIONSHIP),
        (championship_week, third, fourth, third,
         MatchupBracket.NON_CHAMPIONSHIP),
    )

    for week, a, b, winner, bracket in games:
        home_key, away_key = orient([keys[a], keys[b]])
        matchup_key = derive_matchup_key(league_key, week, home_key, away_key)
        home = keys.index(home_key)
        away = keys.index(away_key)
        db.add(Matchup(
            league_id=league.id, week=week,
            home_team_id=teams[home].id, away_team_id=teams[away].id,
            # Scores are supplied and are NOT the basis of anything: the winner
            # is stated separately and the determination reads only the
            # statement.
            home_score=120.0 if home == winner else 100.0,
            away_score=100.0 if home == winner else 120.0,
            winner_team_id=teams[winner].id,
            provider_matchup_key=matchup_key,
            refreshed_at=FIXTURE_FINAL, finalized_at=FIXTURE_FINAL))
        source.record(league_key, week, matchup_key, bracket)
    db.flush()


def bind_synthetic_identity(db, league, teams, *, name: str | None = None):
    """Give a league and its teams synthetic provider identity, in place.

    FOR SUITES WHOSE LEAGUE BUILDER PREDATES PROVIDER IDENTITY. The Championship
    podium is named in provider keys and resolved through the certified
    league-scoped resolver, so a league with unbound teams cannot be paid — and
    binding them one suite at a time would put four slightly different key
    conventions in four files, which is how `uq_teams_provider_key` collisions
    start.
    """
    league_key = f"synthetic.l.{name or league.name}"
    league.provider = SYNTHETIC_PROVIDER
    league.provider_league_key = league_key
    for i, team in enumerate(teams):
        team.provider = SYNTHETIC_PROVIDER
        team.provider_team_key = f"{league_key}.t.{i}"
        team.provider_team_id = i
    db.flush()
    return league_key


class _KeyResolver:
    """The identity half of a podium source: provider key -> internal team id.

    A resolver is exactly this mapping in production too — `TeamIdentityResolver`
    reads it off persisted `provider_team_key` columns — so supplying it directly
    fakes nothing about the podium. The BRACKET half is not faked either: it is
    derived below by the real production determination.
    """

    def __init__(self, by_key: dict) -> None:
        self._by_key = dict(by_key)

    def to_internal(self, team_key: str):
        return self._by_key.get(team_key)


def authoritative_podium_source(team_ids, *, league_key: str = "syn.l.podium",
                                season: int = 2025,
                                playoff_start_week: int = 15):
    """A `podium_source` callable whose podium is `team_ids[0:3]`, in order.

    FOR SUITES THAT CERTIFY SOMETHING OTHER THAN WP1D and need a season to reach
    its close — the Sprint-5 arithmetic and concurrency proofs, which pin exact
    cents against fixed teams and must not be rewritten into postseason suites to
    keep doing so.

    IT DOES NOT NAME A PODIUM; IT PLAYS ONE. Four teams, two semifinals, a final
    and an official third-place game are constructed and handed to the real
    `derive_championship_track_state`, so the order comes out of the same
    determination production uses. A change that broke third-place derivation
    would break this too, which is the property a hand-written podium object
    would have thrown away.

    `team_ids` needs four entries — champion, runner-up, third, fourth. The
    fourth is the third-place game's loser and receives nothing.
    """
    from providers.base import MatchupBracket
    from providers.fixtures.postseason_synthetic import _final
    from season.championship_track import (
        ChampionshipFieldDeclaration, ChampionshipTrackInput,
        ChampionshipWeekInput, derive_championship_track_state,
    )

    ids = list(team_ids)
    if len(ids) < 4:
        raise ValueError(
            f"a podium needs four teams — champion, runner-up, third and the "
            f"third-place game's loser — got {len(ids)}.")
    champion, runner_up, third, fourth = ids[:4]
    keys = {tid: f"{league_key}.t.{tid}" for tid in (champion, runner_up,
                                                     third, fourth)}
    final_week = playoff_start_week + 1

    semis = (
        _final(league_key, playoff_start_week, keys[champion], keys[third],
               bracket=MatchupBracket.CHAMPIONSHIP, winner=keys[champion]),
        _final(league_key, playoff_start_week, keys[runner_up], keys[fourth],
               bracket=MatchupBracket.CHAMPIONSHIP, winner=keys[runner_up]),
    )
    finals = (
        _final(league_key, final_week, keys[champion], keys[runner_up],
               bracket=MatchupBracket.CHAMPIONSHIP, winner=keys[champion]),
        _final(league_key, final_week, keys[third], keys[fourth],
               bracket=MatchupBracket.NON_CHAMPIONSHIP, winner=keys[third]),
    )

    state = derive_championship_track_state(
        ChampionshipTrackInput(
            league_key=league_key, season=season,
            playoff_start_week=playoff_start_week,
            season_final_week=final_week,
            weeks=(ChampionshipWeekInput(week=playoff_start_week, matchups=semis),
                   ChampionshipWeekInput(week=final_week, matchups=finals)),
            field_declaration=ChampionshipFieldDeclaration(
                team_keys=frozenset(keys.values()))),
        week=final_week)

    resolver = _KeyResolver({k: tid for tid, k in keys.items()})
    return lambda: (state, resolver)


def team_ordinals(team_ids, teams_by_key) -> list[int]:
    """Internal team ids rendered as their synthetic ordinals, for readable
    failure detail."""
    by_id = {t.id: int(k.rsplit(".", 1)[-1]) for k, t in teams_by_key.items()}
    return sorted(by_id[i] for i in team_ids if i in by_id)