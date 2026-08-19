"""Build the FantasyStakes showcase demo league, deterministically.

    python -m demo.seed             build it (rebuilding if one already exists)
    python -m demo.seed --status    report what exists, change nothing
    python -m demo.seed --force     rebuild even if a current one is present

WHAT IT DOES, AND WHAT IT REFUSES TO DO. It creates ONE league bound to the
Demo provider, gives it the real economy, activates the real Season-Opening
Allocation, and posts the showcase season's competitive results through the REAL
LEDGER. It never touches a league it did not create, and it proves that before
it writes anything — see `demo.reset.assert_demo_league`.

── EVERY FIGURE ON A DEMO SCREEN IS PRODUCED BY PRODUCTION CODE ─────────────

    Season-Opening Allocation   economy.season_allocation.activate_season_allocation
    Weekly Play Reserve         economy.league_economy_config (weekly min x weeks)
    wallet balances             ledger.ledger.balance_of
    Championship Score          reports.championship_read_model
    Grand Champion              reports.grand_champion

This module supplies FACTS — who played whom, who won, what was staked — and
lets the certified engines decide what those facts are worth. It computes no
standing, no score and no payout of its own.

── WHY THE COMPETITIVE POSTINGS ARE MADE DIRECTLY ──────────────────────────

A settled Versus contest and a settled Pool each move Credits through a named
DOOR, and the standings read model sums exactly those doors. The showcase posts
through `wager_settled` and the Pool doors so that the REAL read model produces
the Championship Score — rather than driving the full challenge-acceptance
lifecycle, which would add a great deal of machinery to a demo without changing
a single number the viewer sees. The doors, the balance rules and the
zero-sum invariant are the production ones; nothing here bypasses the ledger.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from demo import showcase

DEMO_LEAGUE_NAME = "FantasyStakes Demo League"

#: The account a Try Demo visitor is seated as. A PLAIN GM, seated on one
#: showcase team — never a commissioner. D2 proved why the seat matters: with
#: `users.team_id` NULL this account is not a league member, and the primary
#: Standings surface answered 403. A visitor who cannot see the standings has
#: not been given a demo.
DEMO_USER_EMAIL = "demo.gm@fantasystakes.invalid"

#: The league has to be created BY somebody, and `LeagueCommissioner` is how
#: that is recorded. That authority belongs to a separate account which no
#: public route ever seats anyone as, so the visitor gets a GM's view of the
#: product rather than a commissioner's.
DEMO_OWNER_EMAIL = "demo.owner@fantasystakes.invalid"

#: Which team the visitor plays. Pain Sanders — the comeback story: mid-table at
#: CURRENT with everything still to play for, and a podium finish at FINAL. A
#: seat at the top would show a GM who has already won; this one has stakes.
DEMO_SEAT_ORDINAL = 7


def _now() -> datetime:
    return datetime(2101, 11, 18, 17, 0, 0, tzinfo=timezone.utc)


# ── locating the showcase league ─────────────────────────────────────────────

def league_key_for(league_id: int) -> str:
    """This league's demo provider key. Namespaced per league id, as the
    certified demo path does, so two showcase leagues can never collide."""
    from providers.demo import DEMO_LEAGUE_KEY_PREFIX

    return f"{DEMO_LEAGUE_KEY_PREFIX}showcase.{league_id}"


def team_key_for(league_id: int, ordinal: int) -> str:
    return f"{league_key_for(league_id)}.t.{ordinal}"


def find_showcase(db):
    """The current showcase league, or None.

    IDENTIFIED BY PROVIDER BINDING, NEVER BY NAME. A league called
    "FantasyStakes Demo League" that is bound to Yahoo is a Yahoo league, and
    this must not find it. Same rule `api.demo_routes.is_demo_league` uses.
    """
    from db.schema import League
    from providers.demo import DEMO_LEAGUE_KEY_PREFIX

    rows = (db.query(League)
            .filter(League.season == showcase.SEASON,
                    League.provider == "demo")
            .order_by(League.id.desc()).all())
    for league in rows:
        key = league.provider_league_key or ""
        if key.startswith(f"{DEMO_LEAGUE_KEY_PREFIX}showcase."):
            return league
    return None


# ── building it ──────────────────────────────────────────────────────────────

def _account(db, email: str, role: str):
    """A demo account. The password hash is deliberately not a hash.

    `!demo-no-login` cannot validate under bcrypt, so neither account is
    reachable through any credential path — the only way in is the public demo
    route, which seats the GM account and nothing else.
    """
    from db.schema import User

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, hashed_password="!demo-no-login", role=role)
        db.add(user)
        db.flush()
    return user


def _demo_user(db):
    return _account(db, DEMO_USER_EMAIL, "gm")


def _demo_owner(db):
    return _account(db, DEMO_OWNER_EMAIL, "commissioner")


def _build_league(db):
    """League, teams, wallets and provider identity. Commits nothing."""
    from db.schema import League, LeagueCommissioner, Team, Wallet
    from providers.demo import DEMO_PROVIDER
    from providers.identity import bind_league_identity, bind_team_identity

    league = League(season=showcase.SEASON, name=DEMO_LEAGUE_NAME,
                    projection_source="fantasypros",
                    start_week=showcase.START_WEEK,
                    playoff_start_week=showcase.PLAYOFF_START_WEEK,
                    season_final_week=showcase.SEASON_FINAL_WEEK)
    db.add(league)
    db.flush()

    bind_league_identity(db, league_id=league.id,
                         league_key=league_key_for(league.id),
                         provider=DEMO_PROVIDER)
    league.provider_current_week = showcase.CURRENT_WEEK

    teams = {}
    for spec in showcase.TEAMS:
        team = Team(league_id=league.id, team_name=spec.team_name,
                    owner=spec.gm,
                    email=f"demo.t{spec.ordinal}@fantasystakes.invalid")
        db.add(team)
        db.flush()
        db.add(Wallet(team_id=team.id, balance=0.0))
        bind_team_identity(db, team_id=team.id,
                           team_key=team_key_for(league.id, spec.ordinal),
                           team_ordinal=spec.ordinal, provider=DEMO_PROVIDER)
        teams[spec.ordinal] = team
    db.flush()

    # COMMISSION GOES TO THE OWNER ACCOUNT, NOT THE VISITOR.
    owner = _demo_owner(db)
    db.add(LeagueCommissioner(league_id=league.id, user_id=owner.id,
                              source="local_grant",
                              assigned_by_user_id=owner.id))

    # SEAT THE VISITOR. `users.team_id` is globally unique, so the previous
    # showcase's seat is released first — otherwise a reseed would collide with
    # the retired league's team and the visitor would keep a seat in a league
    # nobody can reach any more.
    visitor = _demo_user(db)
    visitor.team_id = None
    db.flush()
    visitor.team_id = teams[DEMO_SEAT_ORDINAL].id
    db.add(visitor)
    db.flush()
    return league, teams


def _configure_economy(db, league):
    """The REAL economy config and freeze. No demo shortcut."""
    from economy.league_economy_config import freeze_economy_config, set_draft

    set_draft(db, league_id=league.id, season=showcase.SEASON,
              weekly_bet_minimum_cents=showcase.WEEKLY_BET_MINIMUM_CENTS,
              championship_contribution_cents=(
                  showcase.YAHOO_CHAMPIONSHIP_CONTRIBUTION_CENTS),
              skunk_fee_cents=showcase.SKUNK_FEE_CENTS)
    db.flush()
    freeze_economy_config(db, league_id=league.id, season=showcase.SEASON,
                          now=_now())
    db.flush()


def _seed_matchups(db, league, teams):
    """The Yahoo-style season, represented synthetically. Weeks 1-10 final."""
    from db.schema import Matchup

    written = 0
    for week, games in sorted(showcase.REGULAR_SCHEDULE.items()):
        for home, away, home_pts, away_pts in games:
            # FINALITY IS THE CLOCK'S, NOT THE FIXTURE'S. Every week now
            # carries a result, so "has a score" no longer means "has been
            # played" — CURRENT must seed weeks 11-14 as scheduled fixtures
            # with nothing posted, exactly as a live league holds them.
            final = week <= showcase.COMPLETED_THROUGH_WEEK
            winner = None
            # AN OPEN WEEK SCORES 0.0, NOT NULL. `matchups.home_score` is NOT
            # NULL, and the production writer never leaves it unset either:
            # `finalized_at` is the finality predicate, so a live week is
            # zero-scored and unfinalized, which is exactly what the lifecycle
            # and the finality gate read.
            home_pts = 0.0 if (home_pts is None or not final) else home_pts
            away_pts = 0.0 if (away_pts is None or not final) else away_pts
            if final:
                winner = (teams[home].id if home_pts > away_pts
                          else teams[away].id if away_pts > home_pts else None)
            db.add(Matchup(
                league_id=league.id, week=week,
                home_team_id=teams[home].id, away_team_id=teams[away].id,
                home_score=home_pts, away_score=away_pts,
                winner_team_id=winner,
                finalized_at=_now() if final else None,
                provider_matchup_key=(
                    f"{league_key_for(league.id)}.m.{week}.{home}.{away}"),
                refreshed_at=_now()))
            written += 1
    db.flush()
    return written


# ── the competitive economy, through the real ledger ─────────────────────────

# ── the entry point ──────────────────────────────────────────────────────────

def seed(*, force: bool = False) -> dict:
    """Build the showcase league. Returns a summary; raises on refusal."""
    from db.schema import SessionLocal
    from economy.season_allocation import activate_season_allocation
    from ledger.ledger import create_ledger_table, trial_balance

    create_ledger_table()

    with SessionLocal() as db:
        existing = find_showcase(db)
        if existing is not None and not force:
            from demo.reset import retire_showcase

            retire_showcase(db, existing)
            db.commit()

        league, teams = _build_league(db)
        _configure_economy(db, league)
        db.commit()
        league_id = league.id

    # THE REAL ALLOCATION, ON ITS OWN TRANSACTION. It issues the
    # Season-Opening Allocation to every team through the governed issuance
    # door; nothing here hand-posts a wallet.
    activate_result = None
    with SessionLocal() as db:
        activate_result = activate_season_allocation(league_id, db)
        db.commit()

    with SessionLocal() as db:
        from db.schema import League, Team

        league = db.query(League).filter(League.id == league_id).first()
        # RE-RESOLVED BY TEAM NAME, which is unique inside this fixture and is
        # the one attribute the seeder itself set. Re-querying rather than
        # carrying ORM objects across sessions keeps each transaction honest.
        by_name = {spec.team_name: spec.ordinal for spec in showcase.TEAMS}
        teams = {}
        for team in db.query(Team).filter(Team.league_id == league_id).all():
            ordinal = by_name.get(team.team_name)
            if ordinal is not None:
                teams[ordinal] = team
        matchups = _seed_matchups(db, league, teams)
        # ROSTERS AND PROJECTIONS FIRST. The production pricing stack prices a
        # matchup from the two teams' starters; without them there is nothing to
        # simulate and no calculated odds exist.
        from demo.rosters import seed_rosters

        roster_summary = seed_rosters(db, league=league, teams=teams)

        # ── THE SEASON IS PLAYED, NOT POSTED ─────────────────────────────────
        # Everything below this line used to be four hand-written posting
        # helpers that moved the right cents through the right doors and
        # produced a league that had never played: no BeefChallenge, no Bet, no
        # PoolInstance, no PoolClaim. The read model counts ROWS, not totals, so
        # every GM showed 0-0 with no pool wins while the ledger looked correct.
        # `demo.gameplay` replays the same season through the same calls a GM's
        # clicks reach, and the postings fall out of that as they should.
        from demo.gameplay import play_season

        owner = _demo_owner(db)
        season_play = play_season(
            db, league=league, teams=teams, owner_user_id=owner.id,
            completed_through=showcase.COMPLETED_THROUGH_WEEK,
            current_week=showcase.CURRENT_WEEK)
        db.commit()

    balance = trial_balance()
    return {
        "league_id": league_id,
        "season": showcase.SEASON,
        "teams": len(showcase.TEAMS),
        "matchups": matchups,
        "players": roster_summary["players"],
        "projections": roster_summary["projections"],
        "weeks_played": season_play["weeks_closed"],
        "versus_issued": sum(w["versus_issued"] for w in season_play["weeks"]),
        "pools_settled": sum(w["pools_settled"] for w in season_play["weeks"]),
        "pool_claims": sum(w["claims"] for w in season_play["weeks"]),
        "selectable_definitions": season_play["prepared"]["selectable"],
        "live_week": season_play["live_week"],
        "allocation_per_team_cents": getattr(
            activate_result, "per_player_cents", None),
        "trial_balance": balance,
        "current_week": showcase.CURRENT_WEEK,
    }


def status() -> dict:
    from db.schema import SessionLocal, Team

    with SessionLocal() as db:
        league = find_showcase(db)
        if league is None:
            return {"exists": False}
        teams = db.query(Team).filter(Team.league_id == league.id).count()
        return {"exists": True, "league_id": league.id, "name": league.name,
                "season": league.season, "provider": league.provider,
                "provider_league_key": league.provider_league_key,
                "teams": teams,
                "current_week": league.provider_current_week}


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if args.status:
        state = status()
        if not state["exists"]:
            print("no showcase demo league exists")
            return 1
        for k, v in state.items():
            print(f"  {k:22} {v}")
        return 0

    try:
        result = seed(force=args.force)
    except Exception as exc:
        print(f"DEMO SEED REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print("showcase demo league seeded")
    for k, v in result.items():
        print(f"  {k:26} {v}")
    if result["trial_balance"] != 0:
        print("  *** TRIAL BALANCE IS NOT ZERO ***", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
