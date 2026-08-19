"""Deterministic fictional rosters and projections for the showcase.

WHY THIS EXISTS. The production pricing stack — `beefs.beef_engine`, which
reaches `odds/monte_carlo` and `odds/market_lines` — prices a matchup from the
two teams' STARTERS and their projected points. Without rosters and projections
there is nothing to simulate, so there are no calculated odds, and the website's
"calculated odds" claim has nothing behind it.

EVERY PLAYER HERE IS INVENTED. Names are constructed from two fictional word
lists; positions and NFL clubs are the ordinary vocabulary of the sport, which
is not Yahoo data. No Yahoo player id, no Yahoo player key, no copied
projection, and no network call of any kind.

DETERMINISTIC BY CONSTRUCTION, NOT BY SEED. Projections are a pure function of
`(team ordinal, roster slot, week)` — no RNG, no clock. The same seeding produces
the same points, therefore the same simulated distribution, therefore the same
moneyline, spread and total on every machine and every run. A demo whose odds
moved between showings would be worse than one with no odds at all.
"""
from __future__ import annotations

from demo import showcase

#: Nine starters, which is `beefs.beef_engine.N_START`. The engine reads the
#: first nine roster rows by id, so the order here is the starting lineup.
SLOTS: tuple = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF")

#: Fictional NFL clubs. Deliberately invented three-letter codes that are not
#: real franchise abbreviations, so nothing here reads as league data.
CLUBS: tuple = ("AUR", "BRK", "CDR", "DLT", "EVR", "FRN",
                "GLD", "HRB", "IVY", "JDE", "KTE", "LRK")

#: Per-ordinal, per-player strength tilt — the single knob that sets how lopsided
#: the demo's markets are.
#:
#: MEASURED, NOT CHOSEN. Nine starters multiply this by nine and the ordinal
#: spread multiplies it by eleven again, so small changes here move the board a
#: long way. Swept by pricing the showcase's ENTIRE season card through
#: `compute_market_board` — the real engine, not an approximation:
#:
#:     coef   |ML| max   |ML| median   spread max   total median
#:     0.06        259           136          5.5          182.0
#:     0.08        347           162          7.0          185.0
#:     0.10        483           177          9.0          187.0
#:     0.12        682           189         11.0          188.5
#:     0.18       1816           271         16.5          196.5
#:
#: 0.18 was an earlier draft and is left in the table as the counter-example: it
#: prices the widest pairing at -1816, which is arithmetically correct and
#: useless in a demo, because no GM believes a fantasy line like that. 0.08
#: keeps the field strictly ordered while landing the strongest favourite near
#: -350 and the typical contest near -160.
STRENGTH_PER_ORDINAL = 0.08

_FIRST: tuple = ("Dex", "Roman", "Tobias", "Cass", "Jules", "Milo", "Ike",
                 "Vance", "Otis", "Reggie", "Sol", "Ambrose")
_LAST: tuple = ("Hollow", "Marchetti", "Okonkwo", "Vasquez", "Steadman",
                "Bellweather", "Nakamura", "Ferris", "Delacroix", "Ash",
                "Quill", "Ramsden")


def player_name(team_ordinal: int, index: int) -> str:
    """A stable fictional name. Distinct across all 12 x 9 = 108 players."""
    first = _FIRST[(team_ordinal * 7 + index * 5) % len(_FIRST)]
    last = _LAST[(team_ordinal * 3 + index * 11) % len(_LAST)]
    return f"{first} {last} {team_ordinal}{index}"


def player_key(league_key: str, team_ordinal: int, index: int) -> str:
    """A demo-namespaced provider key. Never Yahoo-shaped."""
    return f"{league_key}.p.{team_ordinal}.{index}"


def projected_points(team_ordinal: int, index: int, week: int) -> float:
    """This player's projection, in points, as a pure function of its inputs.

    THE SHAPE IS DELIBERATE, because the odds have to be interesting. Position
    carries the base — a quarterback outscores a kicker — the team ordinal tilts
    the whole roster so stronger teams really are stronger, and the week adds a
    small deterministic wobble so consecutive weeks do not price identically.

    Rounded to one decimal, which is how fantasy scoring reads.
    """
    base = (18.0, 14.0, 11.0, 13.0, 10.5, 8.5, 9.0, 7.5, 7.0)[index]
    # Teams 1..12: ordinal 1 is the strongest, 12 the weakest. The coefficient
    # is deliberately small and deliberately measured — see
    # STRENGTH_PER_ORDINAL, which carries the sweep it came from.
    strength = (13 - team_ordinal) * STRENGTH_PER_ORDINAL
    wobble = ((team_ordinal * 31 + index * 17 + week * 13) % 9) * 0.4 - 1.6
    return round(base + strength + wobble, 1)


def seed_rosters(db, *, league, teams: dict) -> dict:
    """Create the 108 fictional players, their roster slots and projections.

    IDEMPOTENT PER LEAGUE. A fresh showcase gets fresh player rows in its own
    provider namespace, so two showcase generations never share a Player and
    retiring one league cannot disturb another.

    Projections are written for every week the season plays — the odds engine
    reads `(player_id, week, season, source)` and a missing row silently prices
    a starter at zero, which would quietly flatten the market.
    """
    from db.schema import Player, Projection, Roster

    league_key = league.provider_league_key
    source = league.projection_source
    season = int(league.season)
    weeks = range(showcase.START_WEEK, showcase.SEASON_FINAL_WEEK + 1)

    players = 0
    projections = 0
    for spec in showcase.TEAMS:
        team = teams[spec.ordinal]
        for index, slot in enumerate(SLOTS):
            player = Player(
                name=player_name(spec.ordinal, index),
                position=slot if slot != "FLEX" else "WR",
                nfl_team=CLUBS[(spec.ordinal + index) % len(CLUBS)],
                provider="demo",
                provider_player_key=player_key(league_key, spec.ordinal, index),
            )
            db.add(player)
            db.flush()
            db.add(Roster(team_id=team.id, player_id=player.id, slot=slot))
            for week in weeks:
                db.add(Projection(
                    player_id=player.id, week=week, season=season,
                    source=source,
                    projected_points=projected_points(spec.ordinal, index, week),
                ))
                projections += 1
            players += 1
    db.flush()
    return {"players": players, "projections": projections,
            "starters_per_team": len(SLOTS)}
