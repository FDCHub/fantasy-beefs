"""FastAPI router for /pool Mode 3 weekly pool endpoints.

WP6C — THE POOL PICK SURFACE IS GOVERNED. `GET /pool/week/{week}` and
`POST /pool/pick` are the product's Pool pick pair, and both now speak the
Rev1.3 model: the read projects persisted `pool_instance` occurrences with the
subjects the census admits, and the write is a thin adapter into the certified
`betting.pool_claims.submit_claim`. Neither reads nor writes `PoolBetPick`.

WHY AN ADAPTER AND NOT A REIMPLEMENTATION. Every Pool claim rule — the valid
occurrence, league membership, subject validity, the shared weekly lock,
one-claim-per-GM, the settled-occurrence refusal — lives in `submit_claim` and
is certified there. What this route owns is IDENTITY (which GM is acting) and
the refusal to let a client assert anything about league or week that the
occurrence itself does not already say. Restating a claim rule here would create
a second definition of the rule, free to drift from the one settlement honours.
"""
from __future__ import annotations

import dataclasses

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.deps import get_db
# require_commissioner is no longer imported: S8-P2 moved every commissioner
# route in this module to league-scoped authority, so a global-role import
# would only be an invitation to reintroduce the gap.
from auth.jwt_auth import assert_wagering_team_owner, get_current_gm, User
from auth.allocation_gate import assert_league_commissioner, is_league_commissioner
from betting.exceptions import ScheduleNotReadyError
from ledger.ledger import _dollars_to_cents
from betting.pool_claims import PoolClaimError, submit_claim
from betting.pool_claim_view import week_claim_view
from betting.pool_legacy_guard import (
    LegacyPoolPathRefused,
    assert_legacy_pool_path_allowed,
)
from betting.pool_engine import (
    setup_pool_config,
    get_pool_config,
    collect_weekly_entries,
    submit_worst_beat_prediction,
    get_pool_predictions,
    settle_pool,
    PoolConfigOut,
    PoolEntryResult,
    PoolPredictionOut,
    PoolSettlementResult,
)

router = APIRouter(prefix="/pool", tags=["pool"])


# ── Request models ────────────────────────────────────────────────────────────

class PoolConfigRequest(BaseModel):
    league_id:           int
    weekly_entry:        float
    worst_beat_rollover: bool = True


class CollectEntriesRequest(BaseModel):
    league_id: int
    week:      int


class PredictionRequest(BaseModel):
    league_id:         int
    team_id:           int
    predicted_team_id: int
    week:              int


class SettleRequest(BaseModel):
    league_id: int
    week:      int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/config", response_model=PoolConfigOut)
def create_pool_config(
    req:   PoolConfigRequest,
    db:    Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
) -> PoolConfigOut:
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

    try:
        weekly_entry_cents = _dollars_to_cents(req.weekly_entry)
        return setup_pool_config(
            league_id           = req.league_id,
            weekly_entry_cents  = weekly_entry_cents,
            worst_beat_rollover = req.worst_beat_rollover,
            db                  = db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/config/{league_id}", response_model=PoolConfigOut)
def read_pool_config(league_id: int, db: Session = Depends(get_db)) -> PoolConfigOut:
    try:
        return get_pool_config(league_id=league_id, db=db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/collect", response_model=PoolEntryResult)
def collect_entries(
    req:   CollectEntriesRequest,
    db:    Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
) -> PoolEntryResult:
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

    # S4-P2-1 — the mounted legacy economic surface. The guard also sits at the
    # engine function's own entry point; it is repeated here so the refusal
    # happens before the request ever reaches the legacy engine, and so the
    # reachable HTTP path is closed at the boundary the route owns.
    try:
        assert_legacy_pool_path_allowed(db, req.league_id, req.week)
        return collect_weekly_entries(league_id=req.league_id, week=req.week, db=db)
    except LegacyPoolPathRefused as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/predict", response_model=PoolPredictionOut)
def submit_prediction(
    req:         PredictionRequest,
    db:          Session = Depends(get_db),
    current_gm:  User    = Depends(get_current_gm),
) -> PoolPredictionOut:
    # S8-P4C-4: STRICT OWNERSHIP, AND IT HAD NONE AT ALL.
    #
    # Found by this package's mutation inventory, not previously reported. The
    # route took `req.team_id` and wrote a prediction row for it with no
    # ownership check whatsoever — any authenticated GM could submit a Worst
    # Beat prediction as any team in any league. That is weaker than the
    # commissioner-permissive defect the checklist already carried.
    #
    # Worst Beat is retired (0 active, never Gate-1 eligible, never in a
    # slate), so this surface predicts a Pool that cannot be drawn — but the
    # route is mounted and reachable, and "the feature is retired" is not a
    # reason to leave an unauthenticated-in-effect write on it.
    #
    # WP6C — AND IT IS NOW FAIL-CLOSED FOR A GOVERNED LEAGUE. This is the OTHER
    # legacy Pool pick write. With `/pool/pick` cut over to `submit_claim`,
    # leaving this one writing `pool_prediction` for a Rev1.3 league would keep
    # exactly the condition WP6C exists to remove: two live surfaces for "a Pool
    # pick", one governed and one not. The guard is the same league-scoped one
    # `/pool/collect` and `/pool/settle` already carry, and it stays inert for a
    # league that never crossed over — the retired Worst Beat suites are
    # unaffected.
    assert_wagering_team_owner(req.team_id, current_gm,
                               "submit its predictions")
    try:
        assert_legacy_pool_path_allowed(db, req.league_id, req.week)
        return submit_worst_beat_prediction(
            league_id         = req.league_id,
            team_id           = req.team_id,
            predicted_team_id = req.predicted_team_id,
            week              = req.week,
            db                = db,
        )
    except LegacyPoolPathRefused as e:
        # 409, matching `/pool/collect` and `/pool/settle`. A governed league is
        # not a malformed request; it is a conflicting one.
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/predictions/{league_id}/{week}", response_model=list[PoolPredictionOut])
def read_predictions(
    league_id: int, week: int, db: Session = Depends(get_db)
) -> list[PoolPredictionOut]:
    try:
        return get_pool_predictions(league_id=league_id, week=week, db=db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/settle", response_model=PoolSettlementResult)
def settle_weekly_pool(
    req:   SettleRequest,
    db:    Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
) -> PoolSettlementResult:
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

    # S4-P2-1 — see collect_entries above.
    try:
        assert_legacy_pool_path_allowed(db, req.league_id, req.week)
        return settle_pool(league_id=req.league_id, week=req.week, db=db)
    except LegacyPoolPathRefused as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── The governed Pool pick pair (WP6C) ────────────────────────────────────────

class PoolPickRequest(BaseModel):
    """What the product's Pool pick control posts.

    `pool_instance_id` NAMES THE OCCURRENCE, and it replaced `bet_type`. The
    legacy field selected one of three hardcoded pot names; the governed model
    has four rotating occurrences per week drawn from an 80-definition catalog,
    and there is no total function from a pot name to one of them. A client that
    could only say "biggest_winner" could not address a governed Pool at all.

    `league_id` AND `week` ARE ASSERTIONS, NOT AUTHORITY. The occurrence already
    carries both. They are still required, and are checked against it, so a
    client that believes it is picking in league 7 week 3 cannot silently claim
    an occurrence belonging to league 9 week 11 — a stale tab is the ordinary
    way that happens, and a mismatch is a refusal rather than a surprise.
    """

    league_id:        int
    team_id:          int
    week:             int
    pool_instance_id: int
    subject_id:       int


def _occurrence_payload(view) -> dict:
    return {
        "pool_instance_id": view.pool_instance_id,
        "slot": view.slot,
        "definition_key": view.definition_key,
        "scope": view.scope,
        "settled": view.settled,
        "claim_count": view.claim_count,
        "my_subject_id": view.my_subject_id,
        "open_for_claims": view.open_for_claims,
        "subjects": [dataclasses.asdict(s) for s in view.subjects],
    }


def _week_payload(db, *, league, week: int, viewer_team_id: int | None) -> dict:
    views = week_claim_view(db, league_id=league.id, season=league.season,
                            week=week, viewer_team_id=viewer_team_id)
    first = views[0] if views else None
    return {
        "league_id": league.id,
        "season": league.season,
        "week": week,
        "drawn": bool(views),
        # The week's ONE lock moment (POR §11), reported from the same
        # server-side source `submit_claim` enforces. A client that computed its
        # own would eventually disagree with the engine, and the GM would learn
        # about it as a refused pick.
        "lock_time": first.lock_time.isoformat() if first and first.lock_time else None,
        "locked": bool(first.locked) if first else True,
        "lock_unavailable_reason": first.lock_unavailable_reason if first else None,
        "pools": [_occurrence_payload(v) for v in views],
    }


@router.get("/week/{week}")
def get_week_pool(
    week:       int,
    league_id:  int     = Query(..., description="League ID"),
    db:         Session = Depends(get_db),
    current_gm: User    = Depends(get_current_gm),
) -> dict:
    """The week's GOVERNED Pool occurrences, with the subjects each admits.

    WHAT THIS RETURNED BEFORE WP6C, and why it could not stay. It returned the
    legacy `POOL_BET_TYPES` roster — three hardcoded pots — joined to
    `PoolBetPick`. The settlement engine reads neither. A GM shown that list and
    picking from it was choosing among Pools their league was not running, and
    the pick landed somewhere nothing would ever settle.

    AUTHENTICATED, WHICH IT WAS NOT BEFORE. The body now carries the viewer's
    OWN claim, so it has to know who is asking. `my_subject_id` is never
    populated for anyone else: a Pool is a blind prediction until it settles,
    and publishing the field pre-lock would let a GM copy the room.
    """
    from db.schema import League

    if not 1 <= week <= 17:
        raise HTTPException(status_code=400, detail="week must be 1–17")

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404,
                            detail=f"League {league_id} not found")

    # MEMBERSHIP OR LEAGUE COMMISSIONER AUTHORITY — the same rule the governed
    # slate read applies, deliberately, so the two Pool reads of one week cannot
    # disagree about who may see it. A commissioner holding no team is a member
    # for the purpose of reading the league's own week, and reads it with no
    # claim of their own, which is correct: they have none.
    #
    # The viewer's team is resolved from the SESSION and never from a parameter.
    # `my_subject_id` would otherwise be answerable for any team whose id a
    # caller could guess.
    viewer_team_id = _acting_team_in_league(current_gm, league_id, db)
    if (viewer_team_id is None
            and not is_league_commissioner(current_gm.id, league_id, db)):
        raise HTTPException(status_code=403, detail={
            "reason_code": "not_a_league_member",
            "message": f"User {current_gm.id} is not a member of league "
                       f"{league_id}."})

    return _week_payload(db, league=league, week=week,
                         viewer_team_id=viewer_team_id)


def _acting_team_in_league(current_gm: User, league_id: int, db: Session):
    """The authenticated user's team in THIS league, or None.

    Resolved from the user's own team row rather than from the request, which is
    what makes `my_subject_id` undisclosable to anyone but its owner.

    The same rule as `api.main._member_team_id`, restated rather than imported:
    `api.main` imports this router, so importing back would be circular. PURE
    READ, one SELECT, for the same reason that one is.
    """
    from db.schema import Team

    if current_gm.team_id is None:
        return None
    team = db.query(Team).filter(Team.id == current_gm.team_id).first()
    if team is None or team.league_id != league_id:
        return None
    return team.id


@router.post("/pick")
def submit_pick(
    req:        PoolPickRequest,
    db:         Session = Depends(get_db),
    current_gm: User    = Depends(get_current_gm),
) -> dict:
    """Record the acting GM's governed Pool claim for one occurrence.

    WP6C — THIS IS AN ADAPTER INTO `betting.pool_claims.submit_claim`, and it
    deliberately contains no Pool claim rule of its own. Before WP6C it called
    `betting.pool_engine.submit_pool_pick`, which wrote a `PoolBetPick` row: the
    route answered 200, the GM saw their selection, and the Rev1.3 settlement
    engine — which resolves winners from `pool_claim` — saw nothing. Every GM's
    ticket was invisible to the only thing that pays.

    `replace=True`, AND THAT IS THE PRODUCT BEHAVIOUR, NOT A LOOSENING. A GM
    changing their mind before the lock is ordinary, the legacy control already
    allowed it, and `submit_claim` implements it by UPDATING the single existing
    row. The one-claim-per-GM-per-occurrence invariant is unaffected: it is held
    by `uq_pool_claim_instance_gm`, which neither branch of `submit_claim` can
    write around. Resubmitting the same subject is therefore idempotent in the
    only sense that matters — one row, one claim, one ticket.

    NOTHING HERE MOVES CREDITS, because nothing in `submit_claim` can. Owner
    Ruling R3: a pick creates a claim, not funding. The route takes no wallet
    lock and posts no ledger legs, and the trial balance is untouched by a
    submission, a refusal and a replacement alike.
    """
    from db.schema import PoolInstance

    # S8-P4C-4: STRICT POOL-PICK OWNERSHIP, PRESERVED VERBATIM.
    #
    # `assert_wagering_team_owner` has no commissioner exemption, and that is
    # the point. A Pool pick is a COMPETITIVE CHOICE: it decides who a GM is
    # backing, and one submitted on their behalf changes their position in the
    # league without their consent. A commissioner still picks for their OWN
    # team, because they are that team's GM; what they lose is only the ability
    # to pick for someone else. WP6C changes what the pick WRITES, never who may
    # write it.
    #
    # FIRST, before the occurrence is even read, so an unauthorized caller
    # learns nothing about which instances exist.
    assert_wagering_team_owner(req.team_id, current_gm,
                               "submit its Pool picks")

    instance = (db.query(PoolInstance)
                .filter(PoolInstance.id == req.pool_instance_id).first())
    if instance is None:
        raise HTTPException(status_code=404, detail={
            "reason_code": "INSTANCE_NOT_FOUND",
            "message": f"Pool occurrence {req.pool_instance_id} does not exist."})

    # THE CLIENT'S OWN CLAIM ABOUT WHERE IT IS PICKING, CHECKED. The occurrence
    # is the authority on league and week; these two comparisons only refuse a
    # request whose own description of itself is wrong. A stale tab holding last
    # week's instance ids is the ordinary cause, and it must not silently claim
    # a live occurrence the GM never looked at.
    if instance.league_id != req.league_id or instance.week != req.week:
        raise HTTPException(status_code=409, detail={
            "reason_code": "OCCURRENCE_MISMATCH",
            "message": (
                f"Pool occurrence {instance.id} belongs to league "
                f"{instance.league_id} week {instance.week}; the request named "
                f"league {req.league_id} week {req.week}. Reload the week and "
                f"pick again.")})

    try:
        result = submit_claim(db, pool_instance_id=req.pool_instance_id,
                              team_id=req.team_id, subject_id=req.subject_id,
                              replace=True)
        # COMMITTED ONLY ON SUCCESS, and only after the engine has accepted.
        # Every refusal below leaves the transaction rolled back, which is what
        # makes "refused with zero mutation" a property of the code rather than
        # of the order the checks happen to run in.
        db.commit()
    except PoolClaimError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "reason_code": e.reason, "message": str(e)})
    except ScheduleNotReadyError as e:
        # The week's lock is DERIVED from the earliest kickoff. Without an
        # announced schedule there is no governed window to be inside, so the
        # claim is refused rather than admitted against a guessed boundary.
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "reason_code": "SCHEDULE_NOT_READY", "message": str(e)})
    except Exception:
        db.rollback()
        raise

    # THE CONFIRMATION IS A RE-READ, NOT AN ECHO. What comes back is the
    # persisted governed state, so a client cannot display a selection that only
    # its own request believed in.
    league = instance.league
    return {
        "claim_id": result.claim_id,
        "pool_instance_id": result.pool_instance_id,
        "team_id": result.team_id,
        "selected_subject_type": result.selected_subject_type,
        "selected_subject_id": result.selected_subject_id,
        "replaced": result.replaced,
        "week": _week_payload(db, league=league, week=instance.week,
                              viewer_team_id=req.team_id),
    }
