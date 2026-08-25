"""FastAPI router for Demo Mode — creation, progression and reset.

WP2 §10, §34, §35, §37. Demo Mode is a launch FEATURE, and the whole design goal
of this module is that it adds almost nothing. A Demo league is an ordinary
`League` row with `provider = "demo"`; its facts arrive through
`providers/persist.py`, its Pools through the governed collection and settlement
routes, its postseason through the registered bracket source, and its season
close through `POST /league/{id}/season/close`. THERE IS NO DEMO ECONOMY, NO DEMO
LEDGER, NO DEMO POOL ENGINE AND NO DEMO SETTLEMENT PATH.

WHAT THIS ROUTER OWNS IS EXACTLY THREE THINGS:

    create     bring a Demo league, its teams, its wallets and its provider
               identity into existence, and open its first week
    advance    move the Demo's own truth forward one step
    reset      hand the caller a FRESH Demo league

and one read that reports where a Demo league is.

── ADVANCE IS A TWO-BEAT STATE MACHINE, DRIVEN BY PERSISTED STATE ───────────

    week not yet opened   ->  OPEN it      (matchups exist, no scores, NOT final)
    week open             ->  FINALIZE it  (scores, declared winners, rosters,
                                            stats, finalized_at set)
    week final            ->  OPEN the next week, or report the season complete

The state is read from `Matchup.finalized_at` and `League.provider_current_week`
— no new column, no demo cursor table, and nothing a client can assert. WP2 §35
forbids exposing score or winner editing, and the shape above makes it
inexpressible: the caller says "advance" and the scenario says what happens.

── RESET CREATES, IT DOES NOT DELETE (WP2 §37) ──────────────────────────────

Ledger history is immutable. A reset that deleted a Demo league's postings would
have to violate that, so it does not: it creates a NEW Demo league with a new
provider namespace and returns its id. The superseded league keeps every row it
ever wrote, its trial balance stays balanced, and no wallet is repaired by hand.
`superseded_league_id` is reported so the caller knows which league it left.

── AUTHORIZATION, AND WHY THE CREATOR IS A COMMISSIONER BUT MAYBE NOT A GM ──

`LeagueCommissioner` is many-to-many and independent of team ownership, so the
creator always becomes a commissioner of their Demo league. `User.team_id`, by
contrast, is GLOBALLY UNIQUE — one account owns at most one team anywhere — so a
user who already holds a team in a real league is NOT moved into the Demo. They
administer it; they do not play it. Only an account with no team is seated at
Demo Team 1, which is the account a first-time visitor actually has.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.allocation_gate import require_league_commissioner
from auth.jwt_auth import User, get_current_gm
from db.deps import get_db
from providers import incident as provider_incident
from providers.demo import DEMO_LEAGUE_KEY_PREFIX, DEMO_PROVIDER
from providers.demo.postseason import install_demo_postseason_source
from providers.demo.scenario import (
    PLAYOFF_START_WEEK,
    SEASON_FINAL_WEEK,
    START_WEEK,
    TEAM_COUNT,
    DemoScenario,
    league_key_for,
)
from providers.demo.source import DemoProviderSource
from providers.identity import bind_league_identity, bind_team_identity
from providers.persist import refresh_league_week

router = APIRouter(prefix="/demo", tags=["demo"])

#: The Demo's season number.
#:
#: DELIBERATELY A SEASON NO REAL SCHEDULE OCCUPIES. `nfl_schedule` is keyed on
#: (season, week) and carries no league id — it is raw NFL data shared by every
#: league — and `betting.pool_engine._nfl_lock_time` takes MIN(kickoff_utc)
#: across it. A Demo league sharing a real season's rows would therefore inherit
#: that season's kickoffs, and a season already played would leave every Demo
#: Pool locked before the user could pick. Giving Demo its own season keeps its
#: schedule rows entirely its own, and is the same reasoning §11 applies to
#: provider keys: synthetic data lives in a namespace nothing real can occupy.
DEMO_SEASON = 2100

#: The Demo season's week-1 kickoff. Every later week is a day after it.
#:
#: FIXED, NOT RELATIVE TO NOW, AND THAT IS A DELIBERATE TRADE. `pool_lock_time`
#: reads MIN(kickoff_utc) for the season/week, and `nfl_schedule` rows are
#: written once per Demo season and shared by every Demo league. A kickoff
#: computed from the creation clock would therefore be fixed by whoever created
#: the FIRST Demo league, and every Demo league created after that week had
#: passed would open with its pick window already closed — a demo where nobody
#: can pick.
#:
#: A fixed far-future instant makes the window open for every Demo league
#: forever and makes the Demo's lock time deterministic, which is what §12
#: requires. WHAT IT COSTS, STATED PLAINLY: a Demo league never crosses its own
#: lock, so Demo Mode does not currently demonstrate a LOCKED pick window. The
#: lock rule itself is untouched and is certified where it lives; showing it in
#: the Demo is a UI Launch Polish item.
#:
#: 17:00 sits inside the real NFL kickoff band `_nfl_lock_time` validates
#: against (09:00-02:00 UTC), so the schedule reads as announced rather than as
#: placeholder times.
DEMO_WEEK1_KICKOFF = datetime(DEMO_SEASON, 9, 7, 17, 0)

STATE_NOT_OPENED = "NOT_OPENED"
STATE_OPEN = "OPEN"
STATE_FINAL = "FINAL"
STATE_SEASON_COMPLETE = "SEASON_COMPLETE"


# ── The provider seam ─────────────────────────────────────────────────────────
#
# A MODULE-LEVEL FACTORY, NOT AN INLINE CONSTRUCTION, and for the same reason
# `api.main._pool_settlement_transport` is one: certification substitutes a
# source that is out, or one whose stat feed has not caught up, and drives THIS
# EXACT PRODUCTION CODE against it. Injecting the source changes where the facts
# come from and nothing else.

def demo_source() -> DemoProviderSource:
    """The Demo provider source production uses. A healthy, complete feed."""
    return DemoProviderSource()


def is_demo_league(league) -> bool:
    """Whether a league is a Demo league, from its PROVIDER BINDING.

    NOT FROM ITS NAME. WP2 §14 is explicit that a league called "Demo League" is
    not a Demo league, and the binding is the only thing that decides which feed
    answers for it, which economy rows it accumulates and which reset it may be
    given.
    """
    return (getattr(league, "provider", None) == DEMO_PROVIDER
            and (getattr(league, "provider_league_key", "") or "")
            .startswith(DEMO_LEAGUE_KEY_PREFIX))


def require_demo_league(league) -> None:
    """Refuse, by name, any Demo-only action aimed at a non-Demo league."""
    if not is_demo_league(league):
        raise HTTPException(status_code=409, detail={
            "reason_code": provider_incident.REASON_NOT_A_DEMO_LEAGUE,
            "message": (
                f"league {league.id} is bound to provider "
                f"{getattr(league, 'provider', None)!r}, not to the Demo "
                f"provider. Demo lifecycle actions — advance and reset — exist "
                f"only for leagues the Demo provider invented, and are refused "
                f"for every other league."),
            "league_id": league.id,
            "provider": getattr(league, "provider", None),
        })


# ── Demo state, read from persisted rows ──────────────────────────────────────

@dataclass(frozen=True)
class DemoState:
    league_id: int
    league_key: str
    season: int
    current_week: int
    week_state: str
    season_final_week: int
    playoff_start_week: int
    matchups_this_week: int
    finalized_this_week: int


def demo_state(db, league) -> DemoState:
    """Where this Demo league stands. Pure read."""
    from db.schema import Matchup

    week = league.provider_current_week or START_WEEK
    rows = (db.query(Matchup)
            .filter(Matchup.league_id == league.id, Matchup.week == week)
            .all())
    finalized = sum(1 for r in rows if r.finalized_at is not None)

    if not rows:
        state = STATE_NOT_OPENED
    elif finalized == len(rows):
        state = (STATE_SEASON_COMPLETE if week >= SEASON_FINAL_WEEK
                 else STATE_FINAL)
    else:
        state = STATE_OPEN

    return DemoState(
        league_id=league.id,
        league_key=league.provider_league_key or "",
        season=league.season,
        current_week=week,
        week_state=state,
        season_final_week=league.season_final_week or SEASON_FINAL_WEEK,
        playoff_start_week=league.playoff_start_week or PLAYOFF_START_WEEK,
        matchups_this_week=len(rows),
        finalized_this_week=finalized,
    )


def week_is_final(db, league, week: int) -> bool:
    """Whether every persisted matchup of a Demo week carries finalized_at."""
    from db.schema import Matchup

    rows = (db.query(Matchup)
            .filter(Matchup.league_id == league.id, Matchup.week == week)
            .all())
    return bool(rows) and all(r.finalized_at is not None for r in rows)


# ── Snapshot and stat source, for the composition layer ───────────────────────

def demo_week_snapshot(db, league, week: int, *, with_rosters: bool = False,
                       final: bool | None = None, source=None):
    """One Demo league-week snapshot, matching the league's persisted state.

    `final` DEFAULTS TO WHAT THE DATABASE SAYS, not to what the caller wants. A
    settlement path asking for week 3 gets week 3 as it actually stands, so a
    snapshot can never be more final than the rows it will be compared against.
    The advance action passes it explicitly, which is the one place the Demo's
    own truth is allowed to move forward.
    """
    resolved = week_is_final(db, league, week) if final is None else final
    src = source or demo_source()
    return src.week_snapshot(
        league_key=league.provider_league_key,
        week=week,
        current_week=max(league.provider_current_week or START_WEEK, week),
        final=resolved,
        with_rosters=with_rosters)


def demo_stat_source(db, snapshot, *, league_id: int):
    """Bind the Demo stat source to a session and the certified resolver."""
    from providers.demo.pool_source import DemoProviderStatSource
    from providers.identity import build_team_identity_resolver

    resolver = build_team_identity_resolver(db, league_id=league_id,
                                            provider=DEMO_PROVIDER)
    return DemoProviderStatSource(snapshot).bind(db, resolver)


# ── Creation ──────────────────────────────────────────────────────────────────

def _seed_demo_schedule(db, *, season: int) -> None:
    """Kickoff rows for the Demo season, if they are not already there.

    IDEMPOTENT AND ADDITIVE. Two Demo leagues share the Demo season's schedule,
    which is correct — `nfl_schedule` is raw NFL data with no league id, and one
    week has one kickoff for everybody.
    """
    from db.schema import NflSchedule

    existing = {w for (w,) in db.query(NflSchedule.week)
                .filter(NflSchedule.season == season).distinct().all()}
    for week in range(START_WEEK, SEASON_FINAL_WEEK + 1):
        if week in existing:
            continue
        db.add(NflSchedule(
            season=season, week=week,
            home_team=f"DEMO-H{week}", away_team=f"DEMO-A{week}",
            kickoff_utc=DEMO_WEEK1_KICKOFF + timedelta(days=week - 1)))
    db.flush()


def seed_demo_projections(db, *, league, scenario) -> int:
    """Give the Demo league the static roster and projections Versus reads.

    WHY THIS IS COMPOSITION AND NOT THE PROVIDER. `providers/demo/` emits the
    normalized DTOs every provider emits, and `ProviderWeek` carries no
    projection: a projection is a FORECAST, not an observed provider fact, and
    the product sources it separately (`League.projection_source`). Writing one
    from inside the provider package would smuggle a second kind of claim
    through a boundary built for measured facts.

    WHY IT IS NEEDED AT ALL. `beefs/beef_engine._fetch_starters_for_odds` prices
    a Versus wager from the STATIC `Roster` table joined to `Projection` — not
    from the weekly `RosterSlot` capture the provider gateway writes. Without
    both, the odds engine has no starters and a Demo GM cannot strike a wager,
    which would leave Demo Mode missing an entire product surface.

    THE LEGACY COUPLING IS HONOURED, NOT CHANGED. That lookup is keyed on
    `config.CURRENT_SEASON` and the source string "fantasypros" — both module
    constants, neither read from the league — so the rows are written under
    exactly those keys. Rewiring the odds path to read the league's own season
    is a real cleanup and is emphatically not a provider package's work; it is
    carried forward. Demo player ids are unique to the Demo league, so these
    rows collide with nothing a real league holds.

    Insert-only and deterministic: the projection is the scenario's own number
    for that player and week, the same one the finalized snapshot reports.
    """
    from config import CURRENT_SEASON
    from db.schema import Projection, Roster, RosterSlot, Team
    from providers.demo.scenario import ROSTER_SHAPE, SEASON_FINAL_WEEK, START_WEEK

    ordinals = {t.provider_team_key: t.id for t in
                db.query(Team).filter(Team.league_id == league.id).all()}
    by_team_id = {team_id: int(key.rsplit(".", 1)[-1])
                  for key, team_id in ordinals.items() if key}

    slots = (db.query(RosterSlot)
             .filter(RosterSlot.league_id == league.id,
                     RosterSlot.week == START_WEEK)
             .order_by(RosterSlot.id).all())

    existing_roster = {(r.team_id, r.player_id) for r in
                       db.query(Roster.team_id, Roster.player_id).all()}
    written = 0
    for row in slots:
        if (row.team_id, row.player_id) not in existing_roster:
            db.add(Roster(team_id=row.team_id, player_id=row.player_id,
                          slot=row.slot))
            existing_roster.add((row.team_id, row.player_id))

        ordinal = by_team_id.get(row.team_id)
        if ordinal is None:
            continue
        # The player's index within the deterministic roster shape, recovered
        # from the slot's insertion order within its team.
        index = sum(1 for s in slots
                    if s.team_id == row.team_id and s.id < row.id)
        if index >= len(ROSTER_SHAPE):
            continue
        for week in range(START_WEEK, SEASON_FINAL_WEEK + 1):
            db.add(Projection(
                player_id=row.player_id, week=week, season=CURRENT_SEASON,
                projected_points=scenario.player_points(ordinal, index, week),
                source="fantasypros"))
            written += 1
    db.flush()
    return written


def create_demo_league(db, *, user, name: str | None = None):
    """Build one Demo league end to end. Does NOT commit.

    ORDER IS LOAD-BEARING. The League row is created first because its id is the
    token the provider league key is derived from — which is what makes two Demo
    leagues' provider namespaces disjoint without a counter, a random suffix or
    a clock. Identity is bound before any team, because `bind_team_identity`
    enforces one-provider-team-one-internal-team globally and must be able to
    see the league it belongs to.

    THE FIRST WEEK IS OPENED THROUGH THE PRODUCTION GATEWAY. `refresh_league_week`
    reconciles the season boundaries, records the provider's current week and
    persists week 1's matchups with `finalized_at` NULL — the same code path a
    Yahoo refresh takes, so a Demo league's very first row is written by the
    certified writer rather than by this function.
    """
    from db.schema import League, LeagueCommissioner, Team, Wallet

    league = League(season=DEMO_SEASON,
                    name=name or "FantasyStakes Demo League",
                    projection_source="fantasypros")
    db.add(league)
    db.flush()

    league_key = league_key_for(str(league.id))
    scenario = DemoScenario(league_key=league_key, season=DEMO_SEASON)
    bind_league_identity(db, league_id=league.id, league_key=league_key,
                         provider=DEMO_PROVIDER)

    teams = []
    for ordinal in range(1, TEAM_COUNT + 1):
        team = Team(league_id=league.id,
                    team_name=scenario.team_name(ordinal),
                    owner=scenario.owner_name(ordinal),
                    email=scenario.owner_email(ordinal))
        db.add(team)
        db.flush()
        db.add(Wallet(team_id=team.id, balance=0.0))
        bind_team_identity(db, team_id=team.id,
                           team_key=scenario.team_key(ordinal),
                           team_ordinal=ordinal, provider=DEMO_PROVIDER)
        teams.append(team)
    db.flush()

    _seed_demo_schedule(db, season=DEMO_SEASON)

    db.add(LeagueCommissioner(league_id=league.id, user_id=user.id,
                              source="local_grant",
                              assigned_by_user_id=user.id))

    # SEATED ONLY IF THE ACCOUNT HOLDS NO TEAM ANYWHERE. `users.team_id` is
    # globally unique, so moving a user who already plays a real league into the
    # Demo would silently remove them from it.
    if user.team_id is None:
        user.team_id = teams[0].id
        db.add(user)

    db.flush()
    return league, teams


# ── Response models ───────────────────────────────────────────────────────────

class DemoLeagueOut(BaseModel):
    league_id:            int
    league_name:          str
    season:               int
    provider:             str
    provider_league_key:  str
    demo:                 bool
    team_ids:             list[int]
    acting_team_id:       int | None
    current_week:         int
    week_state:           str
    start_week:           int
    playoff_start_week:   int
    season_final_week:    int
    superseded_league_id: int | None = None


class DemoStateOut(BaseModel):
    league_id:          int
    provider:           str
    demo:               bool
    season:             int
    current_week:       int
    week_state:         str
    matchups_this_week: int
    finalized_this_week: int
    playoff_start_week: int
    season_final_week:  int


class DemoAdvanceOut(BaseModel):
    league_id:            int
    action:               str
    week:                 int
    week_state:           str
    matchups_persisted:   int
    matchups_finalized:   int
    roster_slots_written: int
    season_complete:      bool


def _league_out(db, league, teams, *, user,
                superseded: int | None = None) -> DemoLeagueOut:
    state = demo_state(db, league)
    acting = user.team_id if user.team_id in {t.id for t in teams} else None
    return DemoLeagueOut(
        league_id=league.id,
        league_name=league.name,
        season=league.season,
        provider=league.provider,
        provider_league_key=league.provider_league_key,
        demo=True,
        team_ids=[t.id for t in teams],
        acting_team_id=acting,
        current_week=state.current_week,
        week_state=state.week_state,
        start_week=league.start_week or START_WEEK,
        playoff_start_week=state.playoff_start_week,
        season_final_week=state.season_final_week,
        superseded_league_id=superseded,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/league", response_model=DemoLeagueOut, status_code=201)
def create_demo(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """Create a Demo league for the authenticated caller.

    NO YAHOO CREDENTIAL IS READ, NO SOCKET IS OPENED, NO EXTERNAL CALL IS MADE.
    The Demo provider's facts are arithmetic, so this route works in an
    environment with no `secrets/`, no `YAHOO_*` variable and no network — which
    is precisely the environment a first-time visitor's deployment may be in.

    A YAHOO LEAGUE CANNOT BE CREATED THROUGH HERE. The provider is a constant in
    this module and is never taken from the request, so there is no parameter to
    smuggle "yahoo" through and no way to mint a league that claims Yahoo
    identity it never had.
    """
    install_demo_postseason_source()

    league, teams = create_demo_league(db, user=current_user)
    snapshot = demo_week_snapshot(db, league, START_WEEK, final=False,
                                  with_rosters=True)
    refresh_league_week(db, snapshot)
    # AFTER the refresh, not before: the Player rows these reference are created
    # by the gateway's own `resolve_or_create_player` as it persists week 1's
    # roster, so there is nothing to point a Roster or Projection row at until
    # that has run.
    seed_demo_projections(db, league=league,
                          scenario=DemoScenario(
                              league_key=league.provider_league_key,
                              season=DEMO_SEASON))
    db.commit()
    db.refresh(league)

    return _league_out(db, league, teams, user=current_user)


@router.get("/league/{league_id}", response_model=DemoStateOut)
def read_demo_state(
    league_id: int,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """Where this Demo league stands. Pure read; writes nothing."""
    from db.schema import League

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail={
            "reason_code": "league_not_found",
            "message": f"League {league_id} not found."})
    require_demo_league(league)

    state = demo_state(db, league)
    return DemoStateOut(
        league_id=league.id, provider=league.provider, demo=True,
        season=league.season, current_week=state.current_week,
        week_state=state.week_state,
        matchups_this_week=state.matchups_this_week,
        finalized_this_week=state.finalized_this_week,
        playoff_start_week=state.playoff_start_week,
        season_final_week=state.season_final_week)


@router.post("/league/{league_id}/advance", response_model=DemoAdvanceOut)
def advance_demo(
    league_id: int,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """Move the Demo's own truth forward one beat.

    THE SCENARIO DECIDES WHAT HAPPENS, NOT THE CALLER. There is no score, winner,
    stat or outcome parameter, and there is nowhere to put one: the facts are a
    pure function of the league key and the week (WP2 §35).

    EVERY FACT IS WRITTEN BY `providers/persist.py`. This route builds a snapshot
    and hands it over; finality is applied by the sole writer, identity by the
    certified resolver, and the ingestion horizon by the same check a Yahoo
    refresh passes. Nothing here assigns `finalized_at`, a score or a winner.

    A PROVIDER FAILURE PERSISTS NOTHING AND IS NAMED. If the Demo source is out,
    the refusal is a 502 carrying `provider_unavailable` and a retryable flag,
    and the transaction is rolled back — no matchup, no finality, no economic
    state and no partial week.
    """
    from db.schema import League
    from providers.errors import ProviderError

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail={
            "reason_code": "league_not_found",
            "message": f"League {league_id} not found."})
    require_demo_league(league)

    state = demo_state(db, league)
    if state.week_state == STATE_SEASON_COMPLETE:
        raise HTTPException(status_code=409, detail={
            "reason_code": "demo_season_complete",
            "message": (
                f"Demo league {league_id} has played every week through its "
                f"season_final_week {state.season_final_week}. Close the season "
                f"through POST /league/{league_id}/season/close, or reset the "
                f"Demo for a fresh one."),
            "league_id": league_id,
            "week": state.current_week})

    # OPENING A WEEK PUBLISHES ITS LINEUPS, and finalizing it publishes the
    # numbers. `with_rosters` is True on both beats because a real provider
    # reports a team's starters before kickoff — that is what a fantasy league
    # spends the week doing — and `week_snapshot` withholds the STATS until the
    # week is final. Without the lineups at open, a Demo GM could not strike a
    # Versus wager on an unplayed game: the wager engine reads the week's
    # starters, and there would be none.
    if state.week_state == STATE_NOT_OPENED:
        action, week, final = "open", state.current_week, False
    elif state.week_state == STATE_OPEN:
        action, week, final = "finalize", state.current_week, True
    else:
        action, week, final = "open", state.current_week + 1, False
    with_rosters = True

    try:
        snapshot = demo_week_snapshot(db, league, week, final=final,
                                      with_rosters=with_rosters)
        result = refresh_league_week(db, snapshot)
        db.commit()
    except ProviderError as exc:
        db.rollback()
        reason = provider_incident.reason_for_exception(exc)
        payload = provider_incident.record(
            provider=DEMO_PROVIDER, league_id=league_id, season=league.season,
            week=week, operation=f"demo_advance:{action}", reason=reason,
            detail=f"{type(exc).__name__}: {exc}",
            last_provider_refresh=provider_incident.last_provider_refresh(
                db, league_id=league_id),
            provider_current_week=league.provider_current_week)
        raise HTTPException(status_code=502, detail=payload)

    db.refresh(league)
    after = demo_state(db, league)
    return DemoAdvanceOut(
        league_id=league_id, action=action, week=week,
        week_state=after.week_state,
        matchups_persisted=(result.matchups_inserted + result.matchups_updated
                            + result.matchups_unchanged),
        matchups_finalized=result.matchups_finalized,
        roster_slots_written=result.roster_slots_written,
        season_complete=after.week_state == STATE_SEASON_COMPLETE)


@router.post("/league/{league_id}/reset", response_model=DemoLeagueOut,
             status_code=201)
def reset_demo(
    league_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(require_league_commissioner),
):
    """Hand the caller a FRESH Demo league. Deletes nothing.

    WP2 §37 — LEDGER IMMUTABILITY IS NOT NEGOTIABLE FOR CONVENIENCE. A Demo
    league that has played weeks holds real Ledger entries, real Pool pots and
    real economy events. Deleting them to "start over" would mean deleting
    immutable history, and repairing wallets by hand afterwards; both are
    forbidden. So a reset CREATES: a new league, a new provider namespace, new
    teams, new wallets, and week 1 opened.

    THE SUPERSEDED LEAGUE IS LEFT INTACT AND VALID. Its rows still balance, its
    trial balance is unchanged, and nothing is orphaned — there is simply a
    newer Demo league beside it, whose id is returned.

    ONLY A DEMO LEAGUE MAY BE RESET, and only by a commissioner of that league.
    A Yahoo league is refused by name before any row is written, so this route
    can never be used to duplicate or disturb a live league.

    THE CALLER'S SEAT MOVES ONLY IF IT WAS IN THE LEAGUE BEING RESET. A user
    seated in a real league keeps that seat; a user seated in the superseded
    Demo is seated in the new one, so a reset never strands an account.
    """
    from db.schema import League, Team

    old = db.query(League).filter(League.id == league_id).first()
    if old is None:
        raise HTTPException(status_code=404, detail={
            "reason_code": "league_not_found",
            "message": f"League {league_id} not found."})
    require_demo_league(old)

    seated_here = False
    if current_user.team_id is not None:
        seat = db.query(Team).filter(Team.id == current_user.team_id).first()
        seated_here = seat is not None and seat.league_id == old.id
    if seated_here:
        # Released BEFORE the new league is built: `users.team_id` is unique, so
        # the new seat cannot be taken while the old one is held.
        current_user.team_id = None
        db.add(current_user)
        db.flush()

    install_demo_postseason_source()
    league, teams = create_demo_league(db, user=current_user, name=old.name)
    snapshot = demo_week_snapshot(db, league, START_WEEK, final=False,
                                  with_rosters=True)
    refresh_league_week(db, snapshot)
    # AFTER the refresh, not before: the Player rows these reference are created
    # by the gateway's own `resolve_or_create_player` as it persists week 1's
    # roster, so there is nothing to point a Roster or Projection row at until
    # that has run.
    seed_demo_projections(db, league=league,
                          scenario=DemoScenario(
                              league_key=league.provider_league_key,
                              season=DEMO_SEASON))
    db.commit()
    db.refresh(league)

    return _league_out(db, league, teams, user=current_user,
                       superseded=old.id)


# ── D1.1 · PUBLIC ENTRY — the signed-out visitor's way in ────────────────────

@router.post("/enter", status_code=200)
def enter_showcase_demo(response: Response, db: Session = Depends(get_db)):
    """Seat a signed-out visitor in the showcase demo league. NO AUTH REQUIRED.

    ── WHY THIS ROUTE EXISTS ────────────────────────────────────────────────

    Every other demo route requires `get_current_gm`, and the signed-out gate
    offers exactly one control: Sign in with Yahoo. So a prospective user,
    commissioner or reviewer could not see the product at all without first
    handing over a Yahoo account — which is the opposite of what a demo is for.
    This is the smallest affordance that fixes it: one public POST that issues a
    session for the DEMO GM and nothing else.

    ── WHAT IT CANNOT DO, WHICH IS THE ONLY REASON IT IS SAFE ───────────────

    It seats the caller as the demo GM — an account the seeder creates with the
    hashed password `!demo-no-login`, which is not a bcrypt hash and can never
    validate, so the account is unreachable through any credential path. That
    account commissions ONLY demo leagues; `test_d1_demo_environment.py` drives
    that against real Yahoo, unbound and impostor leagues in the same database
    and asserts it holds authority over none of them.

    It takes NO parameters. There is no league id, no user id and no team id a
    caller could supply, so there is nothing to point at a real league.

    IT CREATES NO LEAGUE. If the showcase has not been seeded, it answers 404
    and says so, rather than seeding on demand — a public route that writes a
    league is a public route that can be made to write leagues repeatedly.

    It DOES restore an already-seeded showcase to canonical state before seating
    (see below), which is a bounded undo of the previous visitor's own actions
    against a league that already exists. Those are different powers and only
    the second one is public.
    """
    from auth.jwt_auth import create_access_token
    from auth.session import issue_browser_session, new_csrf_token

    from demo.reset import ensure_canonical
    from demo.seed import DEMO_USER_EMAIL, find_showcase

    # ── RESTORE CANONICAL STATE BEFORE SEATING ───────────────────────────────
    #
    # The showcase is genuinely mutable now: the seated GM can strike a real
    # Versus challenge and enter a real Pool. Without this, the second visitor
    # would inherit the first visitor's league and no two demonstrations would
    # agree.
    #
    # IT REBUILDS ONLY WHEN THE LEAGUE HAS DRIFTED. `ensure_canonical` compares
    # a cheap fingerprint against what the fixture says CURRENT looks like and
    # returns immediately when they match, so an ordinary visit stays a read.
    # That keeps the original property this route was written for — a public
    # POST must not be a way to make the deployment replay a season on demand.
    #
    # It still takes NO parameters and still cannot name a league, so there is
    # nothing here to point at a real one, and `reset()` runs
    # `assert_demo_league` before it touches a row.
    # SERIALIZED. Concurrent visitors queue on one advisory lock inside
    # `ensure_canonical`; whoever waits finds the league already canonical and
    # takes the cheap path, so every simultaneous request is seated rather than
    # three of four racing into a 500 (D2.5 blocker 1).
    restored = ensure_canonical()

    if restored.get("action") == "absent":
        # NOT SEEDED, AND NOT THIS ROUTE'S JOB TO SEED. Controlled 404 rather
        # than a public 22-second league build.
        raise HTTPException(status_code=404, detail={
            "reason_code": "demo_not_seeded",
            "message": ("The showcase demo league has not been created on this "
                        "deployment. Run `python -m demo.seed`.")})

    # `ensure_canonical` committed on its own session; drop anything this
    # request already read so the league below is the restored one.
    db.expire_all()
    league = find_showcase(db)
    if league is None:                     # pragma: no cover - raced teardown
        raise HTTPException(status_code=404, detail={
            "reason_code": "demo_not_seeded",
            "message": ("The showcase demo league has not been created on this "
                        "deployment. Run `python -m demo.seed`.")})

    user = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
    if user is None:                       # pragma: no cover - seeded together
        raise HTTPException(status_code=404, detail={
            "reason_code": "demo_not_seeded",
            "message": "The demo account does not exist on this deployment."})

    csrf = new_csrf_token()
    token = create_access_token(user, csrf=csrf)
    issue_browser_session(response, token, csrf)
    return {
        "league_id": league.id,
        "league_name": league.name,
        "demo": True,
        "restored": restored.get("action"),
        "provider": league.provider,
        "message": ("You are in the FantasyStakes Demo League. Every team, "
                    "result and Credit here is sample data."),
    }
