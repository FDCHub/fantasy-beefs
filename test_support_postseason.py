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
    from db.schema import League, Matchup, Team, Wallet
    from ledger.ledger import post as ledger_post

    league = League(season=synthetic.season, name=name,
                    projection_source="fantasypros",
                    season_final_week=synthetic.season_final_week,
                    playoff_start_week=synthetic.playoff_start_week)
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


def team_ordinals(team_ids, teams_by_key) -> list[int]:
    """Internal team ids rendered as their synthetic ordinals, for readable
    failure detail."""
    by_id = {t.id: int(k.rsplit(".", 1)[-1]) for k, t in teams_by_key.items()}
    return sorted(by_id[i] for i in team_ids if i in by_id)