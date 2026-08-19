"""The showcase demo's deterministic states, and the path between them.

    python -m demo.states                 report the current state
    python -m demo.states --to final      advance the showcase to FINAL
    python -m demo.reset                  back to canonical CURRENT

    CURRENT   week 11 live; ten weeks complete, four still to play
    FINAL     the season played out, closed, championship distributed

── FINAL IS PLAYED, NOT PAINTED ─────────────────────────────────────────────

The temptation with a "finished season" demo is to write the final table
straight into the database. That produces a screen nobody can trust: the
Championship Score would be whatever the fixture said, the podium would be
whatever the fixture said, and the demo would have stopped demonstrating the
product.

An earlier build of this module did something subtler and just as wrong: it
played the run-in by hand-posting `wager_settled` and the Pool doors. The ledger
totals were right and the league had still never played — no `BeefChallenge`, no
`Bet`, no `PoolInstance`, no `PoolClaim` — so the standings read model, which
counts ROWS rather than totals, showed the run-in as though it had not happened.

So the remaining weeks go through `demo.gameplay`, which is the same call
sequence a GM's clicks reach, and then the season is CLOSED through the real
orchestrator:

    per week 11..14   finalize the fixture result, then
                      release -> collect -> claim -> play -> settle -> expire -> skunk
    boundary          provider_current_week -> PLAYOFF_START_WEEK
    championship      activate stage -> freeze Championship Score -> 60/30/10
    close             verify_preconditions -> close_season_economy

This module supplies no economics. It chooses which week to play next and calls
production code in order; it computes no score, no podium, no payout, and it
declares no Grand Champion — every one of those is derived by certified code
from what the season actually produced.

── THE GUARD IS THE SAME GUARD ──────────────────────────────────────────────

Every mutation calls `demo.reset.assert_demo_league` first. A Yahoo league, an
unbound league, a league merely NAMED the demo league, and a demo league that is
not the showcase are all refused before a single row is touched.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from demo import showcase
from demo.reset import DemoSafetyError, assert_demo_league

STATE_CURRENT = "CURRENT"
STATE_FINAL = "FINAL"


def _now() -> datetime:
    """The showcase's fixed clock. See `demo.gameplay._now` — same instant."""
    return datetime(2026, 12, 30, 12, 0, 0, tzinfo=timezone.utc)


def _teams_by_ordinal(db, league_id: int) -> dict:
    from db.schema import Team

    by_name = {t.team_name: t.ordinal for t in showcase.TEAMS}
    out = {}
    for team in db.query(Team).filter(Team.league_id == league_id).all():
        ordinal = by_name.get(team.team_name)
        if ordinal is not None:
            out[ordinal] = team
    return out


def state_of(db, league) -> str:
    """Which deterministic state this showcase league is in, from persisted rows.

    FINAL MEANS CLOSED, NOT MERELY FROZEN. An earlier version read the
    Championship Score snapshot, and a transition that froze the score and then
    failed at the close reported FINAL on a season that had never been closed —
    the next attempt short-circuited and left it that way. `season_closed_at` is
    the season's own terminal marker and it is written by `close_season`, which
    is the last step, so a half-finished advance now correctly still reads
    CURRENT and can be driven forward.
    """
    return STATE_FINAL if league.season_closed_at is not None else STATE_CURRENT


# ── playing the remaining weeks ──────────────────────────────────────────────

def finalize_week(db, league, teams, week: int) -> int:
    """Post the fixture's result onto the week's existing matchup rows.

    THE ROWS ALREADY EXIST. The seeder creates every scheduled week, including
    the ones not yet played, so this posts a result onto a fixture rather than
    conjuring a game at transition time. That is also what makes the finality
    gate meaningful: the week was genuinely unfinalized until this ran.
    """
    from db.schema import Matchup

    rows = {(m.home_team_id, m.away_team_id): m
            for m in db.query(Matchup)
            .filter(Matchup.league_id == league.id,
                    Matchup.week == week).all()}
    written = 0
    for home, away, home_pts, away_pts in showcase.REGULAR_SCHEDULE[week]:
        row = rows.get((teams[home].id, teams[away].id))
        if row is None:
            raise DemoSafetyError(
                f"week {week} matchup {home} vs {away} is missing; the showcase "
                f"was not seeded with the full schedule.")
        row.home_score = home_pts
        row.away_score = away_pts
        row.winner_team_id = (teams[home].id if home_pts > away_pts
                              else teams[away].id if away_pts > home_pts
                              else None)
        row.finalized_at = _now()
        row.refreshed_at = _now()
        written += 1
    db.flush()
    return written


def _close_live_week(db, league, teams) -> dict:
    """Finish week 11 — the week CURRENT left open.

    CURRENT deliberately leaves the live week funded, drawn, claimed and played
    but UNSETTLED, because that is what a week in progress is. Advancing to
    FINAL resolves it rather than abandoning it, and it resolves it the same way
    every other week resolved: post the result, then close.
    """
    from demo import gameplay

    week = showcase.CURRENT_WEEK
    finalize_week(db, league, teams, week)
    return gameplay.close_week(db, league=league, teams=teams, week=week)


def _play_run_in_week(db, league, teams, week: int) -> dict:
    """One whole unplayed week, start to finish, through the real product."""
    from demo import gameplay

    league.provider_current_week = week
    db.add(league)
    db.flush()

    gameplay.release_week_minimums(db, league=league, week=week)
    opened = gameplay.open_week_pools(db, league=league, week=week)
    claims = gameplay.claim_week_pools(db, league=league, teams=teams,
                                       week=week)
    versus = gameplay.play_week_versus(db, league=league, teams=teams,
                                       week=week)
    # THE RESULT IS POSTED ONLY NOW. Issuing a challenge on a week whose result
    # is already final would be backdating; the fixture's score lands after the
    # action is on the board, which is the order a real week has.
    finalize_week(db, league, teams, week)
    closed = gameplay.close_week(db, league=league, teams=teams, week=week)
    return {**closed, "pool_entries": opened["teams_charged"],
            "claims": claims, "versus_issued": len(versus["issued"])}


# ── the synthetic postseason, for the Championship Pot podium ────────────────

def championship_track_state(db, league):
    """Derive the demo's championship track from its synthetic bracket.

    THE DEMO REPORTS A BRACKET; CERTIFIED CODE READS IT. `derive_championship_track_state`
    decides who the champion, the finalists and the official third-place winner
    are, and `economy.championship_podium` turns that into the payout order.
    Nothing here names a recipient — if the bracket were incoherent the podium
    would refuse and the close would abort, which is the control WP1D added and
    which a demo must not be able to talk its way around.
    """
    from providers.base import Finality, MatchupBracket, ProviderMatchup
    from season.championship_track import (
        ChampionshipFieldDeclaration, ChampionshipTrackInput,
        ChampionshipWeekInput, derive_championship_track_state,
    )
    from demo.seed import team_key_for

    key = league.provider_league_key
    by_week: dict = {}
    for week, home, away, home_pts, away_pts, is_champ in showcase.POSTSEASON_BRACKET:
        by_week.setdefault(week, []).append(ProviderMatchup(
            provider=league.provider, league_key=key,
            matchup_key=f"{key}.ps.{week}.{home}.{away}", week=week,
            home_team_key=team_key_for(league.id, home),
            away_team_key=team_key_for(league.id, away),
            home_points=home_pts, away_points=away_pts,
            finality=Finality.FINAL,
            winner_team_key=team_key_for(
                league.id, home if home_pts > away_pts else away),
            bracket=(MatchupBracket.CHAMPIONSHIP if is_champ
                     else MatchupBracket.NON_CHAMPIONSHIP)))

    track_input = ChampionshipTrackInput(
        league_key=key, season=int(league.season),
        playoff_start_week=showcase.PLAYOFF_START_WEEK,
        season_final_week=showcase.SEASON_FINAL_WEEK,
        playoff_team_count=len(showcase.POSTSEASON_FIELD_ORDINALS),
        weeks=tuple(ChampionshipWeekInput(week=w, matchups=tuple(ms))
                    for w, ms in sorted(by_week.items())),
        # THE FIELD MUST BE DECLARED because two teams hold byes, and a bye team
        # appears in no round-one matchup — the module refuses to guess it.
        field_declaration=ChampionshipFieldDeclaration(
            team_keys=frozenset(team_key_for(league.id, o)
                                for o in showcase.POSTSEASON_FIELD_ORDINALS)),
        observed_at=showcase.OBSERVED_AT)

    return derive_championship_track_state(
        track_input, week=showcase.SEASON_FINAL_WEEK)


def _podium_source(db, league):
    """The zero-argument callable `close_season_economy` accepts."""
    from providers.identity import build_team_identity_resolver

    def source():
        return (championship_track_state(db, league),
                build_team_identity_resolver(db, league_id=league.id,
                                             provider=league.provider))
    return source


# ── the transition ───────────────────────────────────────────────────────────

def advance_to_final() -> dict:
    """Play the season out, close it, and run the real championship lifecycle.

    FAILS CLOSED. `assert_demo_league` runs before any write, on every
    transaction, and a league that cannot prove it is the showcase is refused
    with nothing touched.
    """
    from db.schema import League, SessionLocal
    from economy.fantasystakes_championship_settlement import (
        settle_fantasystakes_championship,
    )
    from economy.rc2_season_activation import (
        activate_fantasystakes_championship_stage,
    )
    from economy.season_close_orchestrator import (
        close_season_economy, verify_preconditions,
    )
    from ledger.ledger import trial_balance
    from reports.championship_read_model import freeze_fantasystakes_championship

    from demo.seed import find_showcase

    summary: dict = {"weeks": []}

    # ── 1 · play out weeks 11 through 14 ─────────────────────────────────────
    with SessionLocal() as db:
        league = find_showcase(db)
        assert_demo_league(league)
        if state_of(db, league) == STATE_FINAL:
            return {"state": STATE_FINAL, "already_final": True,
                    "league_id": league.id}
        league_id = league.id
        teams = _teams_by_ordinal(db, league_id)

        summary["weeks"].append(_close_live_week(db, league, teams))
        for week in range(showcase.CURRENT_WEEK + 1,
                          showcase.REGULAR_SEASON_WEEKS + 1):
            summary["weeks"].append(_play_run_in_week(db, league, teams, week))

        # The postseason boundary. `economy.championship_scoring_gate` reads
        # this: a league that reaches the postseason without a frozen
        # Championship Score is refused, which is why the freeze below is not
        # optional decoration.
        league.provider_current_week = showcase.PLAYOFF_START_WEEK
        db.add(league)
        db.commit()

    # ── 2 · the FantasyStakes championship, each step its own transaction ────
    with SessionLocal() as db:
        assert_demo_league(db.query(League).filter(League.id == league_id).first())
        activation = activate_fantasystakes_championship_stage(league_id, db)
        db.commit()
        summary["championship_pot_cents"] = getattr(
            activation, "pot_cents", getattr(activation, "total_cents", None))

    with SessionLocal() as db:
        assert_demo_league(db.query(League).filter(League.id == league_id).first())
        snapshot = freeze_fantasystakes_championship(db, league_id=league_id,
                                                     now=_now())
        db.commit()
        summary["frozen_rows"] = len(snapshot.rows)

    with SessionLocal() as db:
        assert_demo_league(db.query(League).filter(League.id == league_id).first())
        settlement = settle_fantasystakes_championship(db, league_id=league_id,
                                                      now=_now())
        db.commit()
        summary["awards"] = [
            {"team_id": a.team_id, "place": a.place,
             "amount_cents": a.amount_cents, "tied": a.tied}
            for a in settlement.awards]

    # ── 3 · the real season close ────────────────────────────────────────────
    #
    # NOT BYPASSED AND NOT PRE-CHECKED BY HAND. `verify_preconditions` is run
    # explicitly first so a refusal names the unmet prerequisite here, where the
    # demo can report it, rather than surfacing from inside the close; then
    # `close_season_economy` runs the whole certified sequence — terminal pool
    # rollover sweep, reserve sweep, Skunk distribution, championship
    # distribution, expired Weekly Minimum reconciliation and the conservation
    # assertions — and nothing in this module substitutes for any of it.
    with SessionLocal() as db:
        league = db.query(League).filter(League.id == league_id).first()
        assert_demo_league(league)
        final_week = int(league.season_final_week or showcase.SEASON_FINAL_WEEK)
        verify_preconditions(db, league_id=league_id, final_week=final_week)
        report = close_season_economy(db, league_id=league_id,
                                      final_week=final_week,
                                      operator="demo-showcase", now=_now(),
                                      podium_source=_podium_source(db, league))
        db.commit()
        summary["close"] = {
            "terminal_rollover_swept_cents": getattr(
                report, "terminal_rollover_swept_cents", None),
            "reserve_swept_cents": getattr(report, "reserve_swept_cents", None),
            "skunk_distributed_cents": getattr(
                report, "skunk_distributed_cents", None),
            "expired_min_returned_cents": getattr(
                report, "expired_min_returned_cents", None),
        }

    summary.update(state=STATE_FINAL, league_id=league_id,
                   weeks_played=len(summary["weeks"]),
                   trial_balance=trial_balance())
    return summary


def status() -> dict:
    from db.schema import SessionLocal

    from demo.seed import find_showcase

    with SessionLocal() as db:
        league = find_showcase(db)
        if league is None:
            return {"exists": False}
        return {"exists": True, "league_id": league.id,
                "state": state_of(db, league),
                "current_week": league.provider_current_week}


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="showcase demo states")
    parser.add_argument("--to", choices=["final"],
                        help="advance the showcase to FINAL")
    args = parser.parse_args(argv)

    try:
        if args.to == "final":
            result = advance_to_final()
            print("showcase advanced")
        else:
            result = status()
    except DemoSafetyError as exc:
        print(f"DEMO STATE REFUSED: {exc}")
        return 2
    except Exception as exc:                       # pragma: no cover - CLI
        print(f"DEMO STATE FAILED: {type(exc).__name__}: {exc}")
        return 1

    for key, value in result.items():
        if key == "weeks":
            print(f"  {'weeks':<26} {len(value)}")
            continue
        print(f"  {key:<26} {value}")
    return 0


if __name__ == "__main__":                          # pragma: no cover - CLI
    raise SystemExit(main())
