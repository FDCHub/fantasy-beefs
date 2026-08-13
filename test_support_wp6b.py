"""
test_support_wp6b.py — shared fixture for the WP6B Final-Lock worker suites.

INFRASTRUCTURE, NOT A TEST. No assertions live here. Two suites import it:
`test_wp6b_final_lock_worker_pg.py` (the worker's own certification) and
`test_wp6b_blocker_cleared_pg.py` (the WP6 blocker-clearing proof), and they must
run against the SAME league shape or the second would not be recreating what the
first exercised.

It layers on `test_support_wp2bc_league.seed_economic_league` — the same proof
league WP6 drove — and adds only what a Final-Lock run additionally needs:

  ROSTERS AND PROJECTIONS. The odds model reads `Roster` joined to `Projection`,
  and Final Lock's one official simulation reads the same pair LIVE at kickoff.
  No production route ingests projections, so this is fixture-only exactly as it
  is in WP6.

  A LOCK-SEASON KICKOFF SCHEDULE. `seed_economic_league` seeds `NflSchedule` for
  `CURRENT_SEASON`, which is what `pool_claims.pool_lock_time` reads. The
  challenge domain's kickoff-lock — and therefore `workers.final_lock`, which
  uses the same helper — reads `LOCK_SEASON`, a deliberately different year
  (`config`: "NFL schedule season for kickoff-lock checks; independent of
  CURRENT_SEASON (projection data year)"). Both years are seeded so each reader
  finds its own, and neither is bent to suit the other.

  A KICKOFF THE SUITES CAN REASON ABOUT. `week_kickoff()` returns exactly what
  `_nfl_lock_time` will return for a week, so a suite can construct a frozen
  `now` on either side of the governed instant instead of sleeping or guessing.
  The times are real NFL kickoff hours (17:00 UTC), because `_nfl_lock_time`
  refuses timestamps outside the announced-kickoff band as placeholders.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

PASSWORD = "wp6b-password"
COMM_EMAIL = "wp6b-comm@x.test"

#: Weeks the fixture prepares kickoffs and projections for.
WEEKS = (1, 2)

#: $10 — one governed week's Weekly Minimum release per GM, which is the real
#: ceiling on how large a fixture wager may be.
WEEKLY_MIN_CENTS = 14_000 // 14


def gm_email(ordinal: int) -> str:
    return f"wp6b-gm{ordinal}@x.test"


def week_kickoff(week: int) -> datetime:
    """The earliest covered kickoff this fixture will seed for `week`.

    EXACTLY WHAT `_nfl_lock_time` WILL RETURN, computed the same way from the
    same base, so a suite can build `kickoff - 1h` and `kickoff + 7d` and know
    it is standing on either side of the governed instant rather than near it.

    Anchored a few days out from the run so the whole fixture sits in the same
    neighbourhood of real time as `seed_economic_league`'s own kickoffs — the
    suites always pass an explicit `now` to the worker, but the surrounding
    lifecycle routes read the wall clock.
    """
    return (datetime.now(timezone.utc) + timedelta(days=2 + week)).replace(
        hour=17, minute=0, second=0, microsecond=0)


def seed_wp6b_fixture(db, *, team_count: int, league_id: int):
    """Rosters, projections, lock-season kickoffs, users and the commissioner.

    Returns `(team_ids, comm_user_id)`. The caller commits.
    """
    import config
    from auth.jwt_auth import hash_password
    from db.schema import (
        LeagueCommissioner, NflSchedule, Player, Projection, Roster, Team, User,
    )

    team_ids = [t.id for t in db.query(Team)
                .filter(Team.league_id == league_id).order_by(Team.id).all()]

    for idx, team_id in enumerate(team_ids):
        for j in range(9):
            player = Player(name=f"WP6B-T{idx + 1}-P{j}", position="WR",
                            nfl_team="KC")
            db.add(player)
            db.flush()
            db.add(Roster(team_id=team_id, player_id=player.id))
            for wk in WEEKS:
                db.add(Projection(
                    player_id=player.id, week=wk, season=config.CURRENT_SEASON,
                    source="fantasypros",
                    # A DELIBERATELY NARROW SPREAD between teams. WP6's fixture
                    # steps 1.5 points per team, which over nine starters makes
                    # every adjacent pairing a ~95% favourite — and a Derived
                    # ceiling of a few cents, too small for a Final-Lock refund
                    # to be visible in. 0.3 keeps the ordering strict (so
                    # settlement still has a determinate winner) while leaving
                    # the matchups close enough that the Adjustment has real
                    # cents to move.
                    projected_points=10.0 + idx * 0.3 + j * 0.5,
                    actual_points=9.0 + idx * 1.4 + j * 0.4))

    # The kickoff-lock schedule the GOVERNED timing helper reads. Stored naive-UTC
    # to match how every other fixture writes this column; `_nfl_lock_time`
    # normalises it back to tz-aware UTC on read.
    for wk in WEEKS:
        db.add(NflSchedule(
            season=config.LOCK_SEASON, week=wk,
            home_team=f"WP6B-H{wk}", away_team=f"WP6B-A{wk}",
            kickoff_utc=week_kickoff(wk).replace(tzinfo=None)))

    pw = hash_password(PASSWORD)
    comm = User(email=COMM_EMAIL, hashed_password=pw, team_id=team_ids[0],
                role="commissioner")
    db.add(comm)
    for ordinal in range(2, team_count + 1):
        db.add(User(email=gm_email(ordinal), hashed_password=pw,
                    team_id=team_ids[ordinal - 1], role="gm"))
    db.flush()
    db.add(LeagueCommissioner(league_id=league_id, user_id=comm.id,
                              source="bootstrap"))
    db.flush()
    return team_ids, comm.id