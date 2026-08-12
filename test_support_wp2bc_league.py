"""
test_support_wp2bc_league.py — the WP2B-C economic-proof league, shared.

INFRASTRUCTURE, NOT A TEST. No assertions live here and NOTHING RUNS AT IMPORT —
in particular no `setup_postgres_test_db()`, which is the whole reason this
module exists. The WP2B-C suite performs its harness setup at import time, so a
second suite cannot import from it without triggering a second setup against an
already-populated database. One definition of the proof league, imported by
both, is the alternative to two copies that must be kept in step by hand.

WHAT THIS DESCRIBES. The synthetic economic-proof league of
`providers/fixtures/build_wp2bc_corpus.py`: publication-safe identity
999.l.100001, six teams t.1-t.6, players 999.p.*, weeks 1 and 2, and the three
governed stat ids (4 passing_yards / 6 interceptions_thrown / 18 fumbles_lost)
that decide which definitions are gate-2 ready.

WHY THE LEAGUE ID IS PINNED. The Rev1.3 rotation is a pure SHA-256 ranking over
(definition_key, league_id, season, rotation_cycle) — determinism is the
selector's whole contract. Pinning league_id 19 / season 2025 pins which four of
the twelve ready definitions a first-cycle week draws, so a suite can NAME the
definitions it must exercise instead of hoping for them. Nothing is overridden:
the slate is still drawn by the real selector from the real measured eligible
set, and the WP2B-C suite asserts the draw against a prediction from the pure
selector rather than describing whatever happened.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

#: The pinned identity of the economic-proof league.
LEAGUE_KEY = "999.l.100001"
SEASON = 2025
LEAGUE_ID = 19
TEAM_COUNT = 6

#: The corpus's frozen replay instant, shared with the Sprint 6 corpus so adding
#: this league changes nothing about `FixtureTransport.observed_at()` elsewhere.
FROZEN_NOW = datetime(2025, 9, 23, 12, 0, 0, tzinfo=timezone.utc)


def snapshot_for(transport, week: int, *, scoreboard_id: str | None = None):
    """One ProviderWeek from the corpus, through the real parser/normalizer.

    `scoreboard_id` selects a NAMED fixture instead of letting the transport
    pick by (endpoint, league, week). Week 2 carries two scoreboards — pending
    and final — and the finality proofs need to ingest a specific one.
    """
    from providers.yahoo import normalize, parse

    league = normalize.normalize_league(
        parse.parse_league(transport.fetch_league(LEAGUE_KEY)))
    teams = tuple(normalize.normalize_team(t)
                  for t in parse.parse_teams(transport.fetch_teams(LEAGUE_KEY)))

    raw = (transport.corpus[scoreboard_id].payload if scoreboard_id is not None
           else transport.fetch_scoreboard(LEAGUE_KEY, week))
    matchups = normalize.normalize_scoreboard(parse.parse_scoreboard(raw),
                                              week=week)

    entries: list = []
    stats: list = []
    for ordinal in range(1, TEAM_COUNT + 1):
        e, s = normalize.normalize_roster(
            parse.parse_roster(transport.fetch_team_roster(
                LEAGUE_KEY, f"{LEAGUE_KEY}.t.{ordinal}", week)), week=week)
        entries.extend(e)
        stats.extend(s)

    return normalize.build_week(
        league=league, week=week, teams=teams, matchups=matchups,
        roster_entries=tuple(entries), player_stats=tuple(stats),
        observed_at=transport.observed_at())


def seed_economic_league(db):
    """The proof league: pinned id, provider identity, wallets, kickoffs.

    IDENTITY IS THE PROVIDER'S COMPOUND KEY, never an email smuggle. Emails here
    sit in the reserved .invalid TLD and are deliberately not parseable as
    identity, so team resolution can only be coming from `bind_team_identity`.

    Season boundaries are stated to match the corpus payload (end_week 17,
    playoff_start_week 15), so `providers.yahoo.persist._reconcile_boundary`
    finds agreement rather than recording a conflict on first ingest.
    """
    from db.schema import League, NflSchedule, Team, Wallet
    from providers.yahoo.identity import bind_league_identity, bind_team_identity

    league = League(id=LEAGUE_ID, season=SEASON,
                    name="WP2B-C Economic Proof League",
                    projection_source="fantasypros",
                    season_final_week=17, playoff_start_week=15)
    db.add(league)
    db.flush()

    teams = []
    for ordinal in range(1, TEAM_COUNT + 1):
        team = Team(league_id=league.id, team_name=f"WP2BC Team {ordinal}",
                    owner=f"Owner {ordinal}",
                    email=f"wp2bc-team{ordinal}@example.invalid")
        db.add(team)
        db.flush()
        db.add(Wallet(team_id=team.id, balance=0.0))
        teams.append(team)
    db.flush()

    bind_league_identity(db, league_id=league.id, league_key=LEAGUE_KEY)
    for ordinal, team in enumerate(teams, start=1):
        bind_team_identity(db, team_id=team.id,
                           team_key=f"{LEAGUE_KEY}.t.{ordinal}",
                           team_ordinal=ordinal)

    # Kickoffs, so `pool_claims.pool_lock_time` resolves and the pick window is
    # open during the run. Two days out, at 17:00 UTC — inside the real NFL
    # kickoff band `_nfl_lock_time` validates against.
    for week in (1, 2):
        kickoff = (datetime.now(timezone.utc) + timedelta(days=2 + week)
                   ).replace(hour=17, minute=0, second=0, microsecond=0,
                             tzinfo=None)
        db.add(NflSchedule(season=SEASON, week=week,
                           home_team=f"WP2BC-H{week}", away_team=f"WP2BC-A{week}",
                           kickoff_utc=kickoff))
    db.flush()
    return league, teams
