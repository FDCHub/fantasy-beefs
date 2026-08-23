"""RC2 FantasyStakes Championship API surface."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.jwt_auth import User, get_current_gm
from auth.allocation_gate import require_league_commissioner
from db.deps import get_db
from db.schema import League, Team
from economy.fantasystakes_championship_allocation import (
    read_config, set_contribution,
)
from economy.rc2_season_activation import (
    RC2SeasonActivationError,
    activate_fantasystakes_championship_stage,
)
from economy.fantasystakes_championship_settlement import (
    FantasyStakesChampionshipDistributionRun,
    settle_fantasystakes_championship,
)
from economy.championship_result_correction import (
    CorrectedPoolResult, CorrectedVersusResult, apply_result_correction,
)
from reports.championship_corrections import (
    ChampionshipCorrectionError, corrections_for, record_authoritative_result,
    unresolved_eligible_contests,
)
from reports.championship_read_model import (
    FantasyStakesChampionshipError,
    freeze_fantasystakes_championship,
    get_fantasystakes_championship,
)
from reports.standings_read_model import league_standings

router = APIRouter(prefix="/league/{league_id}/championship", tags=["championship"])


class ContributionRequest(BaseModel):
    contribution_cents: int = Field(..., ge=100, le=100_000)


def _require_member(db: Session, *, league_id: int, user: User) -> int:
    """Return the caller's team id only when it belongs to this league.

    Championship reads expose league-wide standings, so they use the same
    membership boundary as the certified RC1 standings surface. Refuse before
    reading league state; an authenticated GM from another league gets 403.
    """
    team_id = getattr(user, "team_id", None)
    if team_id is None:
        raise HTTPException(status_code=403, detail={
            "reason_code": "not_a_league_member",
            "message": "Authenticated user owns no team in this league.",
        })
    team = (db.query(Team.id)
            .filter(Team.id == int(team_id), Team.league_id == league_id)
            .first())
    if team is None:
        raise HTTPException(status_code=403, detail={
            "reason_code": "not_a_league_member",
            "message": "Authenticated user owns no team in this league.",
        })
    return int(team_id)


def _row_dict(row) -> dict:
    return {
        "team_id": row.team_id,
        "team_name": row.team_name,
        "owner": row.owner,
        "matchup_net_cents": row.matchup_net_cents,
        "prop_pool_net_cents": row.prop_pool_net_cents,
        "championship_score_cents": row.championship_score_cents,
        "place": row.place,
        "tied": row.tied,
    }


@router.get("/config")
def championship_config(
    league_id: int,
    db: Session = Depends(get_db),
    gm: User = Depends(get_current_gm),
):
    _require_member(db, league_id=league_id, user=gm)
    view = read_config(db, league_id=league_id)
    return {
        "league_id": view.league_id,
        "season": view.season,
        "yahoo_championship_contribution_cents": view.yahoo_championship_contribution_cents,
        "fantasystakes_championship_contribution_cents": view.fantasystakes_championship_contribution_cents,
        "defaults_match": view.contributions_match,
        "configured": view.configured,
        "frozen": view.frozen,
    }


@router.put("/config")
def update_championship_config(
    league_id: int,
    req: ContributionRequest,
    db: Session = Depends(get_db),
    _comm: User = Depends(require_league_commissioner),
):
    try:
        view = set_contribution(
            db, league_id=league_id, contribution_cents=req.contribution_cents)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "league_id": view.league_id,
        "season": view.season,
        "yahoo_championship_contribution_cents": view.yahoo_championship_contribution_cents,
        "fantasystakes_championship_contribution_cents": view.fantasystakes_championship_contribution_cents,
        "defaults_match": view.contributions_match,
        "configured": view.configured,
        "frozen": view.frozen,
    }


@router.post("/activate")
def activate_championship_economy(
    league_id: int,
    db: Session = Depends(get_db),
    _comm: User = Depends(require_league_commissioner),
):
    try:
        result = activate_fantasystakes_championship_stage(league_id, db)
    except RC2SeasonActivationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "league_id": result.league_id,
        "season": result.season,
        "team_ids": list(result.team_ids),
        "weekly_plus_yahoo_per_gm_cents": result.weekly_plus_yahoo_per_gm_cents,
        "fantasystakes_championship_per_gm_cents": result.fantasystakes_championship_per_gm_cents,
        "season_opening_allocation_per_gm_cents": result.season_opening_allocation_per_gm_cents,
        "fantasystakes_championship_pot_cents": result.fantasystakes_championship_pot_cents,
        "created": result.created,
    }


@router.get("")
def championship_chase(
    league_id: int,
    db: Session = Depends(get_db),
    gm: User = Depends(get_current_gm),
):
    acting_team_id = _require_member(db, league_id=league_id, user=gm)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail="league not found")
    frozen = get_fantasystakes_championship(db, league_id=league_id)
    if frozen is not None:
        return {
            "status": "FINAL",
            "league_id": league_id,
            "season": frozen.season,
            "acting_team_id": acting_team_id,
            "scoring_through_week": frozen.scoring_through_week,
            "frozen_at": frozen.frozen_at.isoformat(),
            "rows": [_row_dict(r) for r in frozen.rows],
        }

    live = league_standings(db, league_id=league_id, acting_team_id=acting_team_id)
    rows = []
    ordered = live.overall
    last_score = None
    last_place = 0
    for index, row in enumerate(ordered, start=1):
        score = int(row.net_cents)
        if score != last_score:
            last_place = index
            last_score = score
        rows.append({
            "team_id": row.team_id,
            "team_name": row.team_name,
            "owner": row.owner,
            "matchup_net_cents": row.versus_net_cents,
            "prop_pool_net_cents": row.pool_net_cents,
            "championship_score_cents": row.net_cents,
            "place": last_place,
            "tied": sum(1 for r in ordered if r.net_cents == row.net_cents) > 1,
        })
    return {
        "status": "LIVE",
        "league_id": league_id,
        "season": league.season,
        "acting_team_id": acting_team_id,
        "scoring_through_week": None,
        "playoff_start_week": league.playoff_start_week,
        "rows": rows,
    }


@router.post("/freeze")
def freeze_championship(
    league_id: int,
    db: Session = Depends(get_db),
    _comm: User = Depends(require_league_commissioner),
):
    try:
        result = freeze_fantasystakes_championship(db, league_id=league_id)
        db.commit()
    except FantasyStakesChampionshipError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "status": "FINAL",
        "league_id": league_id,
        "season": result.season,
        "scoring_through_week": result.scoring_through_week,
        "frozen_at": result.frozen_at.isoformat(),
        "rows": [_row_dict(r) for r in result.rows],
    }


class ResultCorrectionRequest(BaseModel):
    """Names the CONTEST and its corrected authoritative RESULT. Never an amount.

    There is deliberately no cents field, no score field, and no generic
    championship edit endpoint. The commissioner states what the result actually
    was; the Credits are derived from posted ledger state and, for prop pools,
    from the same certified even-split allocator ordinary settlement uses.

    `admit_late_settlement` is the other half of the lifecycle: an eligible
    contest whose ORDINARY settlement landed after the freeze already has correct
    economics, so it is admitted to the Championship without any corrective
    posting. That path takes no corrected result because nothing is being
    restated.
    """

    competition_type: str = Field(..., pattern="^(versus|prop_pool)$")
    contest_ref: int = Field(..., ge=1)
    reason: str = Field(..., min_length=3, max_length=500)
    correction_key: str = Field(..., min_length=3, max_length=200)
    #: True  -> admit an eligible contest that settled normally after the freeze.
    #: False -> restate a settled contest to `corrected_result`.
    admit_late_settlement: bool = False
    #: Versus: {"outcome": "winner", "winner_team_id": N} or {"outcome": "push"}
    #: Prop pool: {"winner_team_ids": [N, ...]}
    corrected_result: dict | None = None


@router.post("/corrections")
def record_championship_correction(
    league_id: int,
    req: ResultCorrectionRequest,
    db: Session = Depends(get_db),
    comm: User = Depends(require_league_commissioner),
):
    """Admit or restate an eligible regular-season result after the freeze."""
    source = f"commissioner:{comm.id}"
    try:
        if req.admit_late_settlement:
            result = record_authoritative_result(
                db, league_id=league_id, competition_type=req.competition_type,
                contest_ref=req.contest_ref, reason=req.reason, source=source,
                correction_key=req.correction_key)
        else:
            if not req.corrected_result:
                raise HTTPException(
                    status_code=422,
                    detail="corrected_result is required unless "
                           "admit_late_settlement is true")
            if req.competition_type == "versus":
                payload = CorrectedVersusResult(
                    outcome=str(req.corrected_result.get("outcome", "")),
                    winner_team_id=(
                        int(req.corrected_result["winner_team_id"])
                        if req.corrected_result.get("winner_team_id") is not None
                        else None),
                )
            else:
                payload = CorrectedPoolResult(
                    winner_team_ids=tuple(
                        int(t) for t in
                        req.corrected_result.get("winner_team_ids", ())),
                )
            result = apply_result_correction(
                db, league_id=league_id, competition_type=req.competition_type,
                contest_ref=req.contest_ref, corrected_result=payload,
                reason=req.reason, source=source,
                correction_key=req.correction_key)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except ChampionshipCorrectionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "league_id": result.league_id,
        "season": result.season,
        "competition_type": result.competition_type,
        "contest_ref": result.contest_ref,
        "scoring_week": result.scoring_week,
        "replayed": result.replayed,
        "total_delta_cents": result.total_delta_cents,
        "rows": [
            {"team_id": r.team_id, "revision": r.revision,
             "previous_net_cents": r.previous_net_cents,
             "corrected_net_cents": r.corrected_net_cents,
             "delta_cents": r.delta_cents}
            for r in result.rows
        ],
    }


@router.get("/corrections")
def list_championship_corrections(
    league_id: int,
    db: Session = Depends(get_db),
    gm: User = Depends(get_current_gm),
):
    _require_member(db, league_id=league_id, user=gm)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail="league not found")
    rows = corrections_for(db, league_id=league_id, season=int(league.season))
    return {
        "league_id": league_id,
        "season": int(league.season),
        "corrections": [
            {"team_id": r.team_id, "competition_type": r.competition_type,
             "contest_ref": r.contest_ref, "scoring_week": r.scoring_week,
             "revision": r.revision, "previous_net_cents": r.previous_net_cents,
             "corrected_net_cents": r.corrected_net_cents,
             "delta_cents": r.delta_cents, "reason": r.reason,
             "source": r.source}
            for r in rows
        ],
    }


@router.post("/settle")
def settle_championship(
    league_id: int,
    db: Session = Depends(get_db),
    _comm: User = Depends(require_league_commissioner),
):
    try:
        result = settle_fantasystakes_championship(db, league_id=league_id)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "league_id": result.league_id,
        "season": result.season,
        "pot_cents": result.pot_cents,
        "replayed": result.replayed,
        "awards": [
            {"team_id": a.team_id, "place": a.place,
             "championship_score_cents": a.championship_score_cents,
             "amount_cents": a.amount_cents, "tied": a.tied}
            for a in result.awards
        ],
    }


def _season_opening_allocation(db, league) -> dict | None:
    """The FULL RC2 Season-Opening Allocation, and the parts that explain it.

    WHY THIS EXISTS SEPARATELY FROM `/settings`. The certified base-stage figure
    `EconomyCalculation.season_opening_allocation_per_player_cents` is Weekly
    Play Reserve + Yahoo Championship Contribution, and it is correct for what
    it names: the RC1 allocation stage. RC2 advances a SECOND, independently
    configured FantasyStakes Championship Contribution in its own activation
    stage, so a GM's actual season advance — the number `rc2_season_activation`
    reports and Current Settle charges — is that base plus the FantasyStakes
    contribution. Redefining the base field to mean the new total would change a
    certified value to fix a presentation problem, so the total is DERIVED here
    instead and the base field is left alone.

    NOTHING IS FIXED. The Weekly Play Reserve is the commissioner's weekly
    minimum multiplied by the league's own Yahoo regular-season week count, so a
    13-week league and a 14-week league get different answers from the same
    code. 140 and 300 are one league's arithmetic, not constants.

    PURE READ. No ledger movement, no write, no freeze. Returns None when the
    week count is not yet derivable, which is an ordinary pre-activation state
    rather than an error.
    """
    from economy.league_economy_config import (
        EconomyConfigError, derive_regular_season_week_count, read_draft,
    )
    from economy.fantasystakes_championship_allocation import read_config

    season = int(league.season)
    try:
        weeks = derive_regular_season_week_count(
            start_week=league.start_week,
            playoff_start_week=league.playoff_start_week)
    except EconomyConfigError:
        return None
    if not weeks:
        return None

    draft = read_draft(db, league_id=league.id, season=season)
    weekly_minimum = int(draft.weekly_bet_minimum_cents)
    yahoo = int(draft.championship_contribution_cents)

    # The FantasyStakes contribution comes from the governed championship
    # configuration RC2 already owns — the same row activation freezes — not
    # from a second copy of the number kept anywhere else.
    fs_view = read_config(db, league_id=league.id, season=season)
    fantasystakes = int(fs_view.fantasystakes_championship_contribution_cents)

    reserve = weekly_minimum * weeks
    return {
        "weekly_minimum_cents": weekly_minimum,
        "regular_season_week_count": int(weeks),
        "weekly_play_reserve_cents": reserve,
        "yahoo_championship_contribution_cents": yahoo,
        "fantasystakes_championship_contribution_cents": fantasystakes,
        "season_opening_allocation_cents": reserve + yahoo + fantasystakes,
        "fantasystakes_contribution_frozen": bool(fs_view.frozen),
    }


@router.get("/results")
def championship_results(
    league_id: int,
    db: Session = Depends(get_db),
    gm: User = Depends(get_current_gm),
):
    """Everything the season-results surface needs, in one member-scoped read.

    PURE READ. It settles nothing, freezes nothing, corrects nothing and posts
    nothing — every figure here was decided by a certified path and is only
    being reported. The 60/30/10 awards come out of the recorded distribution
    run rather than being recomputed, so this surface can never disagree with
    what was actually paid.

    THE LIFECYCLE IS DERIVED, NOT STORED. Four states, each read from the state
    that already defines it:

        LIVE    no freeze marker — the chase is still running
        FROZEN  frozen, but an eligible regular-season contest is unresolved
        FINAL   every eligible result is authoritative; the pot may be paid
        PAID    the distribution run exists

    THE YAHOO PODIUM IS BORROWED, NOT REBUILT. `_settlement_podium_order` is the
    existing read-surface helper: it derives the podium from the same provider
    track state the settlement report uses and collapses every legitimate "there
    is no podium yet" to None instead of raising. Nothing new is fetched, stored
    or retained about Yahoo here — this endpoint reads what that helper returns
    and nothing else. Imported inside the function because `api.main_rc2`
    registers this router before importing `api.main`.
    """
    _require_member(db, league_id=league_id, user=gm)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail="league not found")
    season = int(league.season)

    frozen = get_fantasystakes_championship(db, league_id=league_id, season=season)
    run = (db.query(FantasyStakesChampionshipDistributionRun)
           .filter(FantasyStakesChampionshipDistributionRun.league_id == league_id,
                   FantasyStakesChampionshipDistributionRun.season == season)
           .one_or_none())

    blockers: list[str] = []
    if frozen is not None and run is None:
        blockers = list(unresolved_eligible_contests(
            db, league_id=league_id, season=season,
            playoff_start_week=int(frozen.playoff_start_week)))

    if frozen is None:
        lifecycle = "LIVE"
    elif run is not None:
        lifecycle = "PAID"
    elif blockers:
        lifecycle = "FROZEN"
    else:
        lifecycle = "FINAL"

    awards = []
    if run is not None:
        awards = [
            {"team_id": int(a["team_id"]), "place": int(a["place"]),
             "championship_score_cents": int(a["championship_score_cents"]),
             "amount_cents": int(a["amount_cents"]), "tied": bool(a["tied"])}
            for a in run.awards_json
        ]

    # The Yahoo podium, if the bracket is authoritative. None is an ordinary
    # answer for most of the season and is not an error.
    yahoo_podium = None
    try:
        from api.main import _settlement_podium_order

        order = _settlement_podium_order(db, league_id)
        if order:
            yahoo_podium = [int(t) for t in order]
    except Exception:
        yahoo_podium = None

    # ── GRAND CHAMPION, COMPUTED BY THE CERTIFIED CALCULATOR ─────────────────
    #
    # `reports.grand_champion` already owns the whole rule: 3/2/1 per component,
    # tied component finishes pooling the occupied point values, exact Fraction
    # arithmetic, then — for GMs level on the highest combined total — the
    # higher FantasyStakes Championship Score taking the title, and only a tie
    # that survives THAT producing co-Grand Champions.
    # It is called here rather than reimplemented in the browser, because
    # fractional pooled points are exactly the kind of arithmetic that drifts
    # when it lives in two places.
    #
    # THE YAHOO PODIUM CANNOT TIE, AND THAT IS STRUCTURAL. `economy.
    # championship_podium.Podium.team_ids` is a tuple of THREE DISTINCT ids and
    # `derive_podium_keys` refuses anything else — a knockout bracket produces
    # one champion, one runner-up and one third. So Yahoo finishes are always
    # places 1, 2, 3. The FantasyStakes podium is where real ties occur, and its
    # frozen rows already carry competition-style places (1, 1, 3), which is the
    # shape the calculator expects.
    # ── WP-14 · THE FINAL POR GRAND CHAMPIONSHIP, WHERE THAT ERA GOVERNS ─────
    #
    # Everything below this block is the RETIRED model and it is deliberately
    # left standing: it still governs every legacy season, exactly as
    # `reserve:{team}` still does in `current_settle.py`. What was wrong is that
    # it governed BOTH, so a Final POR league read its Grand Championship as
    # 3/2/1 recognition points -- a competition that season did not run.
    #
    # §20 replaced it: the Grand Championship is won on the finalized
    # championship CREDITS a GM holds across the pillars their league actually
    # funded, it needs at least two funded pillars to exist at all, and an exact
    # tie on the total makes co-champions with NO tiebreak. The three states are
    # PLACEHOLDER, LIVE and FINAL, and PLACEHOLDER returns no rows rather than
    # rows of zeros -- a table of GMs on nothing is a claim they are level, and
    # during the regular season there is nothing to be level about.
    #
    # THE SHAPE IS DELIBERATELY NOT THE OLD ONE. The retired payload's
    # `yahoo_points` / `fantasystakes_points` / `combined_points` describe
    # pooled Fractions that no longer exist; emitting them with credit figures
    # inside would let a client keep reading the old rule and get plausible
    # numbers. A Final POR season carries `by_pillar` credits and its state
    # instead, and `model` says which rule produced the payload so no client has
    # to infer it.
    grand_champion = None
    grand_final_por = None
    try:
        from ruleset import is_final_por as _is_final_por

        _final_por_season = _is_final_por(db, league_id=league_id, season=season)
    except Exception:
        _final_por_season = False

    if _final_por_season:
        from economy.grand_championship import (
            GrandChampionshipError, view as _grand_view,
        )

        try:
            _g = _grand_view(db, league_id=league_id, season=season)
            grand_final_por = {
                "model": "FINAL_POR",
                "state": _g.state,
                "funded_pillars": list(_g.funded_pillars),
                "finalized_pillars": list(_g.finalized_pillars),
                "meets_pillar_minimum": _g.meets_pillar_minimum,
                "champion_team_ids": list(_g.champion_team_ids),
                "co_champions": _g.co_champions,
                # NO TIEBREAK EXISTS UNDER §20, and the field is reported as
                # false rather than omitted so a client that still reads it
                # cannot mistake its absence for "we did not check".
                "tiebreak_used": False,
                "rows": [
                    {"team_id": row.team_id,
                     "by_pillar": dict(row.by_pillar),
                     "total_cents": row.total_cents}
                    for row in _g.rows
                ],
            }
        except GrandChampionshipError as _refusal:
            # A NAMED REFUSAL TRAVELS, rather than the whole response failing.
            # The podiums beside it are still readable and still correct.
            grand_final_por = {"model": "FINAL_POR", "state": None,
                               "unavailable_reason": _refusal.reason,
                               "rows": [], "champion_team_ids": []}

    elif frozen is not None and yahoo_podium:
        from reports.grand_champion import (
            ChampionshipFinish, calculate_grand_champion,
        )

        fs_finishes = tuple(
            ChampionshipFinish(team_id=int(r.team_id), place=int(r.place))
            for r in frozen.rows if int(r.place) <= 3)
        yahoo_finishes = tuple(
            ChampionshipFinish(team_id=int(t), place=i + 1)
            for i, t in enumerate(yahoo_podium[:3]))
        # STEP 2 of the locked rule needs each candidate's authoritative
        # FantasyStakes Championship Score — the frozen realized-net figure the
        # snapshot already carries. It is passed in rather than looked up inside
        # the calculator, which stays pure.
        fs_scores = {int(r.team_id): int(r.championship_score_cents)
                     for r in frozen.rows}
        try:
            result = calculate_grand_champion(
                yahoo_finishes=yahoo_finishes,
                fantasystakes_finishes=fs_finishes,
                fantasystakes_scores=fs_scores)
        except ValueError:
            # A malformed component podium is reported as "not decided" rather
            # than guessed at. Nothing here invents an ordering.
            result = None
        if result is not None:
            grand_champion = {
                # STATED, NOT INFERRED. A client must be able to tell which
                # rule produced the payload it is holding.
                "model": "LEGACY_3_2_1",
                "champion_team_ids": list(result.champion_team_ids),
                "co_champions": result.co_champions,
                # True only when the Championship Score actually decided it, so
                # a surface never shows a tiebreak line for a tie that did not
                # happen or one the tiebreak did not resolve.
                "tiebreak_used": result.tiebreak_used,
                "rows": [
                    {"team_id": row.team_id,
                     # Exact, as the calculator produced it: "5/2" stays "5/2".
                     "yahoo_points": str(row.yahoo_points),
                     "fantasystakes_points": str(row.fantasystakes_points),
                     "combined_points": str(row.combined_points),
                     # A display convenience only; the exact strings above are
                     # authoritative.
                     "combined_display": (
                         f"{float(row.combined_points):g}"),
                     "fantasystakes_score_cents": row.fantasystakes_score_cents}
                    for row in result.rows
                ],
            }

    return {
        "league_id": league_id,
        "season": season,
        "lifecycle": lifecycle,
        "scoring_through_week": (frozen.scoring_through_week
                                 if frozen is not None else None),
        "playoff_start_week": league.playoff_start_week,
        "frozen_at": (frozen.frozen_at.isoformat() if frozen is not None else None),
        "unresolved": blockers,
        "fantasystakes_podium": (
            [_row_dict(r) for r in frozen.rows if r.place <= 3]
            if frozen is not None else []),
        "pot_cents": (int(run.pot_cents) if run is not None else None),
        "paid": run is not None,
        "distributed_at": (run.distributed_at.isoformat()
                           if run is not None else None),
        "awards": awards,
        "yahoo_podium": yahoo_podium,
        # BOTH KEYS, AND ONLY ONE IS EVER POPULATED. A Final POR season fills
        # `grand_championship` and leaves `grand_champion` null; a legacy season
        # does the reverse. Keeping the retired key rather than overloading it
        # means an existing client reading `grand_champion` gets null on a
        # season the retired rule never ran -- which is correct -- instead of a
        # payload whose fields it recognises and whose meaning has changed.
        "grand_champion": grand_champion,
        "grand_championship": grand_final_por,
        "allocation": _season_opening_allocation(db, league),
    }
