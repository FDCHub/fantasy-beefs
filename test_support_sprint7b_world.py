"""Sprint 7B · the staging world both proof suites are built on.

ONE DEFINITION, TWO SUITES. The offline pricing suite and the PostgreSQL
settlement suite must prove their cases against the SAME league, the same
subjects and the same evidence — otherwise "the board priced correctly" and
"the wager settled correctly" are statements about two different worlds that
merely share a sprint number. This module is that world, and it is built
entirely from production creation paths.

── EVERY NUMBER IN HERE WAS MEASURED, NONE WAS CHOSEN ──────────────────────

The component projections come from the committed BALLDONTLIE capture for
season 2025 week 17. The pick-six, three-and-out and drive parameters are
derived by the certified Sprint 5/5B derivers from the real captured TEN-at-CHI
play-by-play. The reception parameters come from the real 2024 season totals
Sprint 5B transcribed and certified. Sprint 7B calibrates nothing, invents no
rate and adjusts no model: it is an integration sprint, and a constant chosen
here to make a lineup admissible would be exactly the failure the whole IPRM
admission gate exists to prevent.

── THE AS-OF IS THE PRODUCTION ONE, AND IT MATTERS ─────────────────────────

`history_refresh._season_cutoff(2024, ...)` is 2025-03-01: after the 2024 season
ended and before the 2025 season began. Parameters derived from 2024 evidence
carry that instant, and the week-17 2025 projections carry the provider's own
observation stamp of 2025-12-24. So the parameters are in force for the moment
being priced, and a parameter derived LATER would not be — which is the leakage
guard working, not a detail to route around. An earlier draft of this world
stamped the parameters 2026-03-01 and every lineup correctly refused.

── SIX SUBJECTS, THREE STARTERS A SIDE ─────────────────────────────────────

The committed week-17 capture carries one subject per fantasy position — a
quarterback, a back, a receiver, a tight end, a kicker and a team defence. That
is six, so two teams field three starters each. `_fetch_starters_for_odds` takes
the first `N_START` roster slots and a team with three has three; the lineup
size is not what any assertion here turns on, and inventing subjects to reach
nine would mean pricing a board off material no provider ever sent.

── BOTH LEAGUES ROSTER THE SAME PLAYERS, DELIBERATELY ──────────────────────

The control league's teams hold the very same `Player` rows as the staging
league's. That makes the isolation proof as strong as it can be: if a
BALLDONTLIE component snapshot could leak into a legacy board, these two
leagues are where it would happen, because there is no player-level difference
between them to hide behind. Only the configuration row differs.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Mapping

#: The staging league that is moved to BALLDONTLIE, and the control that is not.
STAGING_LEAGUE_ID = 901
CONTROL_LEAGUE_ID = 902
SEASON = 2025
WEEK = 17

#: The league's certified CSPS profile. Named, never defaulted — see
#: `providers.selection.require_scoring_profile` on why there is no house one.
PROFILE_ID = "mr_whiskers_memorial"

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "providers", "fixtures", "balldontlie")

#: The real captured game the Sprint 5/5B parameter derivations run over.
PLAYS_FIXTURE = "plays__game_id-7005__per_page-100__CAPTURED.json"
WEEKLY_FIXTURE = "fantasy_weekly_stats__per_page-100__season-2025__week-17.json"
PLAYS_HOME, PLAYS_VISITOR = "CHI", "TEN"

#: The six subjects the committed week-17 capture forecasts, and the local
#: `Player` rows they are bound to. Position strings are the product's, not the
#: provider's — BALLDONTLIE says `PK`, this repository says `K`.
SUBJECTS = (
    ("bdl.p.27",     "QB",  "Staging QB"),
    ("bdl.p.475",    "RB",  "Staging RB"),
    ("bdl.p.113",    "WR",  "Staging WR"),
    ("bdl.p.277679", "TE",  "Staging TE"),
    ("bdl.p.278371", "K",   "Staging K"),
    ("bdl.dst.DET",  "DEF", "Detroit DST"),
)

#: THE REAL 2024 SEASON TOTALS SPRINT 5B CERTIFIED, carried verbatim. They are
#: the evidence `reception-model-v2` is measured from; the model resolves
#: POSITION then LEAGUE, so these three positions cover every subject above and
#: a position with no row of its own falls back to the league rate rather than
#: to a number somebody picked.
RECEPTION_SEASON_TOTALS = (
    {"season": 2024, "postseason": False,
     "player": {"id": 760, "position_abbreviation": "WR"},
     "receiving_targets": 79, "receptions": 42},
    {"season": 2024, "postseason": False,
     "player": {"id": 761, "position_abbreviation": "TE"},
     "receiving_targets": 60, "receptions": 44},
    {"season": 2024, "postseason": False,
     "player": {"id": 762, "position_abbreviation": "RB"},
     "receiving_targets": 55, "receptions": 44},
)

#: When the derivation itself ran. Distinct from the as-of: one says which
#: evidence was in force, the other says when somebody computed over it.
GENERATED_AT = datetime(2026, 3, 15, tzinfo=timezone.utc)

#: The scalar projection the CONTROL league is priced from. A plain FantasyPros
#: number per starter, which is what every league in production has today.
LEGACY_POINTS = {"QB": 18.4, "RB": 12.1, "WR": 14.7,
                 "TE": 8.3, "K": 7.9, "DEF": 6.5}
LEGACY_SOURCE = "fantasypros"


def fixture_payload(name: str):
    """One committed capture, read from disk. No network, ever."""
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as handle:
        return json.load(handle)


def season_cutoff() -> datetime:
    """The as-of 2024-derived parameters carry, from the production helper."""
    from providers.balldontlie.history_refresh import _season_cutoff

    return _season_cutoff(2024, 18)


def fixture_transport():
    """The certified fixture transport, pointed at the committed corpus."""
    from providers.balldontlie.transport import BalldontlieFixtureTransport

    return BalldontlieFixtureTransport(FIXTURE_DIR)


def derive_model_parameters(db):
    """Persist every historical parameter the IPRM admission gate demands.

    ALL FOUR MODELS, ALL FROM REAL EVIDENCE, THROUGH THE CERTIFIED DERIVERS.
    `derive_from_payloads` is the production refresh's own derivation half — the
    part with the football reasoning in it, separated from the fetch precisely so
    it can be driven from committed captures with no credential and no network.

    :returns: the number of parameter rows persisted.
    """
    from providers.balldontlie import history_refresh as HR
    from providers.balldontlie import parse as P
    from scoring import history as H

    as_of = season_cutoff()
    plays_payload = fixture_payload(PLAYS_FIXTURE)
    weekly_pages = fixture_payload(WEEKLY_FIXTURE)["pages"]

    report = HR.derive_from_payloads(
        db, weekly_stat_payloads=weekly_pages,
        play_games=[(plays_payload, PLAYS_HOME, PLAYS_VISITOR)],
        season_window="2024", as_of=as_of, generated_at=GENERATED_AT)

    # Drives and receptions have their own derivers and are not part of
    # `derive_from_payloads`'s set; both are Sprint 5B's certified functions.
    extra = list(H.derive_drive_rates(
        [(P.parse_plays(plays_payload), PLAYS_HOME, PLAYS_VISITOR)],
        provider="balldontlie", season_window="2024", as_of=as_of))
    extra += list(H.derive_reception_rates_from_season_totals(
        list(RECEPTION_SEASON_TOTALS), provider="balldontlie",
        season_window="2024", as_of=as_of))
    stored = H.persist_rates(db, extra, generated_at=GENERATED_AT)
    db.flush()
    return report.rates_persisted + stored["persisted"]


def seed_world(db, *, with_control: bool = True):
    """The two leagues, their teams, the shared players and both feeds.

    NOTHING HERE IS A MOCK. `Player`, `Team`, `League`, `Roster`,
    `ProviderPlayerAlias` and `Projection` are the production models; the
    component snapshots are written by `providers.balldontlie.ingest.ingest_week`,
    the production ingest, running against the fixture transport — which stamps
    them FIXTURE_SYNTHETIC rather than LIVE, because a replayed snapshot must
    never be indistinguishable from a fetched one.

    :returns: a dict of the rows every suite needs to make assertions about.
    """
    from db.schema import (
        League, Player, Projection, ProviderPlayerAlias, Roster, Team,
    )
    from providers.balldontlie.ingest import BALLDONTLIE, ingest_week

    derive_model_parameters(db)

    staging = League(id=STAGING_LEAGUE_ID, season=SEASON,
                     name="Sprint 7B Staging", projection_source=LEGACY_SOURCE)
    db.add(staging)
    leagues = {"staging": staging}
    if with_control:
        control = League(id=CONTROL_LEAGUE_ID, season=SEASON,
                         name="Sprint 7B Control",
                         projection_source=LEGACY_SOURCE)
        db.add(control)
        leagues["control"] = control
    db.flush()

    players = []
    for key, position, name in SUBJECTS:
        player = Player(name=name, position=position, nfl_team="DET")
        db.add(player)
        players.append(player)
    db.flush()

    for player, (key, position, _name) in zip(players, SUBJECTS):
        db.add(ProviderPlayerAlias(
            provider=BALLDONTLIE, player_id=player.id,
            provider_player_key=key, provider_position=position,
            provider_nfl_team="DET",
            status=ProviderPlayerAlias.STATUS_ACTIVE,
            # MANUAL, AND LABELLED MANUAL. This is a suite binding an identity
            # it already knows, not a discovery run; recording it as a discovery
            # would assert the matcher had proved something it never saw.
            method=ProviderPlayerAlias.METHOD_MANUAL, manual_override=True))
    db.flush()

    teams: dict = {}
    for handle, league in leagues.items():
        made = []
        for ordinal in (1, 2):
            team = Team(league_id=league.id,
                        team_name=f"{handle.title()} {ordinal}",
                        owner=f"{handle}-gm-{ordinal}",
                        email=f"{handle}.gm{ordinal}@example.invalid")
            db.add(team)
            made.append(team)
        teams[handle] = made
    db.flush()

    # THE SAME SIX PLAYERS ON BOTH LEAGUES' ROSTERS. See the module docstring:
    # this is what makes the isolation proof airtight rather than incidental.
    for made in teams.values():
        for index, player in enumerate(players):
            db.add(Roster(team_id=made[index % 2].id, player_id=player.id))
    db.flush()

    # The legacy scalar feed, for the control league and for any assertion that
    # needs to show the BALLDONTLIE league did NOT read it.
    for player in players:
        db.add(Projection(player_id=player.id, week=WEEK, season=SEASON,
                          source=LEGACY_SOURCE,
                          projected_points=LEGACY_POINTS[player.position],
                          injury_status=None))
    db.flush()

    summary = ingest_week(db, fixture_transport(), season=SEASON, week=WEEK,
                          players=players)
    db.flush()

    return {"leagues": leagues, "teams": teams, "players": players,
            "ingest": summary}


def activate_balldontlie(db, *, league_id: int = STAGING_LEAGUE_ID,
                         projection_source: str = "balldontlie",
                         factual_source: str = "balldontlie",
                         simulation_model: str = "sim-v2",
                         scoring_profile_id: str | None = PROFILE_ID,
                         note: str = "Sprint 7B staging activation"):
    """The activation act, through the production writer. One row, one league."""
    from providers.selection import set_selection

    selection = set_selection(
        db, league_id=league_id, season=SEASON,
        projection_source=projection_source, factual_source=factual_source,
        simulation_model=simulation_model,
        scoring_profile_id=scoring_profile_id,
        note=note, updated_by="sprint7b")
    db.flush()
    return selection


# ══════════════════════════════════════════════════════════════════════════════
# THE SETTLEMENT WORLD — a real economic league, on PostgreSQL
# ══════════════════════════════════════════════════════════════════════════════
#
# WHY IT IS SEPARATE FROM THE PRICING WORLD ABOVE. The pricing proof needs one
# subject per fantasy position and no money; the settlement proof needs funded
# wallets, a real pot, a real wager and the ledger, and it needs every team to
# carry the SAME measured stat so a Pool census can evaluate all of them. Those
# are different shapes, and forcing one fixture to be both would make each
# assertion harder to read rather than the world more honest.
#
# WHAT IS MEASURED AND WHAT IS STATED, EXACTLY. The two quarterbacks' factual
# figures are the committed `/fantasy/weekly_stats` corpus's own, for the same
# real BALLDONTLIE subject ids. The play evidence is the real captured game.
# One thing is STATED by this module and labelled as such: a projection block
# for `bdl.p.63`, who appears in the factual corpus and not the projection one.
# It is shaped exactly like the committed quarterback projection and carries
# different numbers, and it exists so ONE league can be priced and then settled
# — which is what Sprint 7B section 38 asks for. The repository has the
# precedent: `providers/fixtures/build_wp2bc_corpus.py` exists because the
# shipped corpus could not demonstrate money moving either.

SETTLEMENT_WEEK = 17
SETTLEMENT_SEASON = 2025

#: The captured game the factual week is assembled around. Its plays are real;
#: the two quarterbacks are attached to it so the week has a final game to
#: belong to.
CAPTURED_GAME_ID = 7005

#: One starter per team. Both are quarterbacks so a TEAM-scope Pool definition
#: over passing yards finds EVERY subject evaluable — a census with an
#: uncovered team refuses INCOMPLETE_FIELD, which is correct behaviour and
#: would prove nothing about money.
SETTLEMENT_STARTERS = (
    ("bdl.p.27", "QB", "Settlement QB One", "SF"),
    ("bdl.p.63", "QB", "Settlement QB Two", "LAR"),
)

#: The committed corpus's own figures for these two subjects, re-expressed in
#: the shape `build_factual_week` consumes. Nothing here was chosen: read them
#: beside the `fantasy_weekly_stats` fixture and they agree.
SETTLEMENT_STATS = (
    {"player": {"id": 27, "position_abbreviation": "QB"},
     "team": {"abbreviation": "SF"}, "game": {"id": CAPTURED_GAME_ID},
     "passing_yards": 320, "passing_touchdowns": 3, "rushing_yards": 12},
    {"player": {"id": 63, "position_abbreviation": "QB"},
     "team": {"abbreviation": "LAR"}, "game": {"id": CAPTURED_GAME_ID},
     "passing_yards": 269, "passing_touchdowns": 2,
     "passing_interceptions": 3},
)

#: STATED, NOT MEASURED — see the section note. The projection block for the
#: second quarterback, in the committed fixture's own vocabulary.
STATED_PROJECTION_BDL_63 = {
    "passing_yards": 251.0, "passing_touchdowns": 1.5,
    "passing_interceptions": 0.9, "rushing_yards": 9.0,
    "rushing_touchdowns": 0.1,
}


def settlement_game_row(*, final: bool = True) -> dict:
    """The game these subjects played in. Final unless a suite says otherwise.

    `final=False` is how the outage-before-finality case is expressed: a
    provider that has not declared the game over yields subjects carrying
    PROVIDER_NOT_FINAL, every lineup is NOT READY, and nothing settles.
    """
    return {"id": CAPTURED_GAME_ID,
            "status": "Final" if final else "In Progress",
            "status_state": "final" if final else "in_progress",
            "home_team": {"abbreviation": PLAYS_HOME},
            "visitor_team": {"abbreviation": PLAYS_VISITOR},
            "home_team_score": 24 if final else None,
            "visitor_team_score": 17 if final else None,
            "week": SETTLEMENT_WEEK, "season": SETTLEMENT_SEASON}


def build_settlement_factual_week(*, final: bool = True, stats=None):
    """The certified factual assembly, over the real captured play stream."""
    from providers.balldontlie import factual_week as FW
    from providers.balldontlie import parse as P

    plays = P.parse_plays(fixture_payload(PLAYS_FIXTURE))
    return FW.build_factual_week(
        season=SETTLEMENT_SEASON, week=SETTLEMENT_WEEK,
        games=[{"game": settlement_game_row(final=final), "plays": plays,
                "stats": list(stats if stats is not None
                              else SETTLEMENT_STATS)}])


def ingest_settlement_facts(db, players_by_key, *, final: bool = True,
                            stats=None, captured_at=None):
    """Persist one NFL week's facts through the PRODUCTION factual writer.

    `factual_ingest.ingest_factual_week` is the certified path: it refuses a
    subject with no cross-provider resolution rather than storing it against a
    guess, and it stores only complete subjects. Nothing here writes a
    component row directly.
    """
    from providers.balldontlie import factual_ingest as FI
    from providers.cross_identity import (
        BALLDONTLIE as _BDL, CanonicalSubject, CrossProviderResolution,
        Outcome as IdOutcome,
    )

    week = build_settlement_factual_week(final=final, stats=stats)
    resolutions = {}
    for key, subject in week.subjects.items():
        player = players_by_key.get(key)
        if player is None:
            continue
        # PLAIN VALUES, NOT AN ATTACHED ROW. Callers cross session boundaries
        # between the ingest and the settlement — that is the point of the
        # restart proof — so an identity that only exists as a live ORM
        # instance cannot be the thing this fixture carries.
        player_id = (player["id"] if isinstance(player, Mapping)
                     else player.id)
        player_name = (player.get("name") if isinstance(player, Mapping)
                       else player.name)
        resolutions[key] = CrossProviderResolution(
            outcome=IdOutcome.RESOLVED, provider=_BDL,
            canonical=CanonicalSubject(player_id=player_id, name=player_name,
                                       position=subject.position,
                                       nfl_team=subject.nfl_team),
            provider_player_key=key, method="manual")

    report = FI.ingest_factual_week(
        db, week, resolutions=resolutions,
        captured_at=captured_at or datetime(2026, 1, 5, tzinfo=timezone.utc),
        provenance="FIXTURE_SYNTHETIC")
    db.flush()
    return week, report


def yahoo_snapshot(*, league_key: str, league_name: str, team_keys,
                   starters_by_team_key, week: int = SETTLEMENT_WEEK,
                   season: int = SETTLEMENT_SEASON, finality=None,
                   season_final_week: int = 17,
                   playoff_start_week: int = 18):
    """The Yahoo half of the composition: identity, schedule, who started.

    A `ProviderWeek` carrying teams, one matchup and the weekly roster
    assignments — exactly the shape `providers/yahoo/normalize.py` produces and
    `providers/persist.refresh_league_week` consumes. It carries NO player
    stats: on this league BALLDONTLIE supplies those, and a Yahoo snapshot that
    also carried them would make the composition ambiguous.
    """
    from providers.base import (
        Finality, ProviderLeague, ProviderMatchup, ProviderRosterEntry,
        ProviderTeam, ProviderWeek,
    )

    finality = finality if finality is not None else Finality.FINAL
    league = ProviderLeague(provider="yahoo", league_key=league_key,
                            name=league_name, season=season,
                            current_week=week,
                            season_final_week=season_final_week,
                            playoff_start_week=playoff_start_week)
    teams = tuple(ProviderTeam(provider="yahoo", team_key=key, team_id=index,
                               name=f"Team {index}")
                  for index, key in enumerate(team_keys, start=1))

    matchups = []
    for index in range(0, len(team_keys) - 1, 2):
        home, away = sorted(team_keys[index:index + 2])
        matchups.append(ProviderMatchup(
            provider="yahoo", league_key=league_key,
            matchup_key=f"{league_key}.w{week}.{home}-{away}",
            week=week, home_team_key=home, away_team_key=away,
            # NO POINTS FROM YAHOO ON THIS LEAGUE. The scores are computed by
            # FantasyStakes from BALLDONTLIE evidence and written by
            # `factual_scores.rescore_snapshot`; a Yahoo figure here would be
            # overwritten and would only obscure where the number came from.
            home_points=None, away_points=None, finality=finality))

    entries = []
    for team_key, starters in starters_by_team_key.items():
        for key, position, name, nfl_team in starters:
            entries.append(ProviderRosterEntry(
                provider="yahoo", team_key=team_key, player_key=key,
                player_id=key, week=week, slot=position, name=name,
                eligible_positions=(position,), nfl_team=nfl_team))

    return ProviderWeek(league=league, week=week, teams=teams,
                        matchups=tuple(matchups),
                        roster_entries=tuple(entries), player_stats=(),
                        observed_at=datetime(2026, 1, 5, 12, 0,
                                             tzinfo=timezone.utc))
