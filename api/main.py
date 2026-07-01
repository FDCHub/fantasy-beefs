from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import (
    Bet,
    BeefChallenge,
    League,
    Matchup,
    Player,
    Projection,
    Roster,
    Team,
    Transaction,
    User,
    Wallet,
    SessionLocal,
)

from db.deps import get_db
from odds.monte_carlo import OddsResult, run as mc_run
from betting.bet_engine import (
    BetResult,
    place_straight_bet,
    place_spread_bet,
    place_over_under,
    place_prop_bet,
)
from betting.settlement_engine import settle_week, SettlementReport
from beefs.beef_engine import (
    issue_challenge, respond_to_challenge, get_pending_challenges,
    AcceptResult, ChallengeOut,
)
from feed.league_feed import get_league_feed, get_week_feed, FeedPage, FeedEventOut
from wallet.wallet_manager import (
    deposit     as wm_deposit,
    withdraw    as wm_withdraw,
    balance_check_by_team,
    transaction_history as wm_history,
)
from auth.jwt_auth import (
    authenticate_user,
    assert_own_team,
    assert_own_wallet,
    create_access_token,
    get_current_gm,
    promote_user,
    register_user,
    require_commissioner,
)
from payments.stripe_connect import (
    AuditEntry,
    BuyInLink,
    BuyInStatus,
    PayoutPreview,
    TreasuryState,
    confirm_buyin_payment,
    create_buyin_link,
    create_connect_onboarding_link,
    execute_payouts,
    get_audit_log,
    get_buyin_gate,
    get_buyin_status,
    get_treasury_state,
    handle_stripe_webhook,
    preview_payouts,
    setup_league_treasury,
)
from notifications.tuesday_sync import (
    TuesdayRunSummary,
    get_run_detail,
    get_run_history,
    run_tuesday_sync,
)
from reports.weekly_wrap import (
    WrapUpOut,
    generate_weekly_wrap,
    get_gm_editions,
    get_wrap_up,
    get_wrap_up_list,
    send_wrap_up,
    update_wrap_up,
)
from admin.commissioner_rules import (
    EscrowOut,
    ParsePreview,
    RuleExecutionOut,
    RuleOut,
    activate_rule,
    create_rule_draft,
    delete_draft,
    execute_end_of_season_rules,
    execute_weekly_rules,
    get_rule,
    get_rule_audit_log,
    get_rule_executions,
    list_rules,
    parse_rule_text,
    pause_rule,
    release_escrow,
)
from wallet.faab_wallet import (
    FaabConfigState,
    FaabTxRecord,
    FaabWalletState,
    TopupResult,
    TransferResult,
    apply_pending_topups,
    check_and_freeze,
    confirm_topup,
    create_bet_topup,
    create_waiver_topup,
    get_bet_funded,
    get_faab_config,
    get_faab_transactions,
    get_faab_wallet,
    get_league_faab,
    init_season_wallets,
    set_freeze,
    setup_faab_config,
    transfer as faab_transfer,
)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Fantasy Beefs API",
    description="Fantasy football league data, projections, and betting.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/tools", StaticFiles(directory="tools"), name="tools")


@app.on_event("startup")
def _create_tables() -> None:
    from db.schema import Base, engine
    Base.metadata.create_all(engine)


# ── Auth schemas & endpoints ──────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email:    str
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user_id:      int
    email:        str
    team_id:      Optional[int]
    team_name:    Optional[str]
    role:         str


class UserOut(BaseModel):
    user_id:    int
    email:      str
    team_id:    Optional[int]
    team_name:  Optional[str]
    role:       str
    is_active:  bool
    last_login: Optional[str]


class PromoteRequest(BaseModel):
    email: str
    role:  str   # "gm" | "commissioner"


def _user_out(u: User) -> UserOut:
    return UserOut(
        user_id    = u.id,
        email      = u.email,
        team_id    = u.team_id,
        team_name  = u.team.team_name if u.team else None,
        role       = u.role,
        is_active  = bool(u.is_active),
        last_login = u.last_login_at.isoformat() if u.last_login_at else None,
    )


@app.post("/auth/register", response_model=UserOut, status_code=201)
def auth_register(req: RegisterRequest, db: Session = Depends(get_db)):
    try:
        user = register_user(req.email, req.password, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _user_out(user)


@app.post("/auth/login", response_model=LoginOut)
def auth_login(
    form: OAuth2PasswordRequestForm = Depends(),
    db:   Session = Depends(get_db),
):
    """OAuth2 password flow. Pass email as `username`."""
    user  = authenticate_user(form.username, form.password, db)
    token = create_access_token(user)
    return LoginOut(
        access_token = token,
        user_id      = user.id,
        email        = user.email,
        team_id      = user.team_id,
        team_name    = user.team.team_name if user.team else None,
        role         = user.role,
    )


@app.get("/auth/me", response_model=UserOut)
def auth_me(current_user: User = Depends(get_current_gm)):
    return _user_out(current_user)


@app.post("/auth/promote", response_model=UserOut)
def auth_promote(
    req:  PromoteRequest,
    db:   Session = Depends(get_db),
    _comm: User = Depends(require_commissioner),
):
    try:
        user = promote_user(req.email, req.role, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _user_out(user)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class StandingRow(BaseModel):
    rank:      int
    team_id:   int
    team_name: str
    owner:     str
    email:     str
    wins:      int
    losses:    int
    pf:        float
    pa:        float


class MatchupOut(BaseModel):
    matchup_id:     int
    week:           int
    home_team_id:   int
    home_team_name: str
    home_score:     float
    away_team_id:   int
    away_team_name: str
    away_score:     float
    winner_team_id: Optional[int]
    winner_name:    Optional[str]
    margin:         float


class PlayerSlot(BaseModel):
    name:     str
    position: str


class RosterOut(BaseModel):
    team_id:   int
    team_name: str
    owner:     str
    email:     str
    wallet_balance: float
    players:   list[PlayerSlot]


class ProjectionRow(BaseModel):
    player_id:        int
    player_name:      str
    position:         str
    source:           str
    projected_points: float
    actual_points:    float


class BetRequest(BaseModel):
    matchup_id:     int
    wallet_id:      int
    picked_team_id: int
    amount:         float = Field(..., gt=0, description="Must be positive")
    odds:           float = Field(default=1.909, description="-110 American standard")


class BetOut(BaseModel):
    bet_id:         int
    matchup_id:     int
    wallet_id:      int
    picked_team_id: int
    picked_team:    str
    amount:         float
    odds:           float
    status:         str
    placed_at:      str
    to_win:         float


class WalletOut(BaseModel):
    wallet_id:    int
    team_id:      int
    team_name:    str
    balance:      float
    open_bets:    int
    total_wagered: float
    transactions: list[dict]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_standings(db: Session) -> list[dict]:
    matchups = db.query(Matchup).filter(Matchup.week <= 14).all()
    records: dict[int, dict] = {}

    for m in matchups:
        for team_id, pf, pa in (
            (m.home_team_id, m.home_score, m.away_score),
            (m.away_team_id, m.away_score, m.home_score),
        ):
            if team_id not in records:
                records[team_id] = {"w": 0, "l": 0, "pf": 0.0, "pa": 0.0}
            records[team_id]["pf"] += round(pf, 2)
            records[team_id]["pa"] += round(pa, 2)
            if team_id == m.winner_team_id:
                records[team_id]["w"] += 1
            else:
                records[team_id]["l"] += 1

    teams = {t.id: t for t in db.query(Team).all()}
    rows = []
    for team_id, rec in records.items():
        t = teams[team_id]
        rows.append({"team": t, **rec})

    return sorted(rows, key=lambda r: (-r["w"], -r["pf"]))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health(db: Session = Depends(get_db)):
    league = db.query(League).first()
    teams  = db.query(Team).count()
    return {
        "status":  "ok",
        "league":  league.name if league else None,
        "season":  league.season if league else None,
        "teams":   teams,
        "db_path": os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "db", "fantasy.db")
        ),
    }


@app.get("/league/standings", response_model=list[StandingRow])
def standings(db: Session = Depends(get_db)):
    rows = _compute_standings(db)
    return [
        StandingRow(
            rank=rank,
            team_id=r["team"].id,
            team_name=r["team"].team_name,
            owner=r["team"].owner,
            email=r["team"].email,
            wins=r["w"],
            losses=r["l"],
            pf=round(r["pf"], 1),
            pa=round(r["pa"], 1),
        )
        for rank, r in enumerate(rows, 1)
    ]


@app.get("/league/matchups/{week}", response_model=list[MatchupOut])
def matchups(week: int, db: Session = Depends(get_db)):
    if not 1 <= week <= 17:
        raise HTTPException(status_code=400, detail="week must be 1–17")

    rows = (
        db.query(Matchup)
        .filter(Matchup.week == week)
        .order_by(Matchup.id)
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"No matchups found for week {week}")

    return [
        MatchupOut(
            matchup_id=m.id,
            week=m.week,
            home_team_id=m.home_team_id,
            home_team_name=m.home_team.team_name,
            home_score=m.home_score,
            away_team_id=m.away_team_id,
            away_team_name=m.away_team.team_name,
            away_score=m.away_score,
            winner_team_id=m.winner_team_id,
            winner_name=m.winner.team_name if m.winner else None,
            margin=round(abs(m.home_score - m.away_score), 2),
        )
        for m in rows
    ]


@app.get("/league/roster/{team_id}", response_model=RosterOut)
def roster(team_id: int, db: Session = Depends(get_db)):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found")

    wallet  = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    players = [
        PlayerSlot(name=r.player.name, position=r.player.position)
        for r in team.roster
    ]

    return RosterOut(
        team_id=team.id,
        team_name=team.team_name,
        owner=team.owner,
        email=team.email,
        wallet_balance=wallet.balance if wallet else 0.0,
        players=players,
    )


@app.get("/projections/{week}", response_model=list[ProjectionRow])
def projections(
    week: int,
    source: str = Query(default="fantasypros", description="yahoo | espn | fantasypros"),
    position: Optional[str] = Query(default=None, description="Filter by position"),
    db: Session = Depends(get_db),
):
    if not 1 <= week <= 17:
        raise HTTPException(status_code=400, detail="week must be 1–17")

    q = (
        db.query(Projection)
        .join(Player)
        .filter(Projection.week == week, Projection.season == 2024,
                Projection.source == source)
    )
    if position:
        q = q.filter(Player.position == position.upper())

    rows = q.order_by(Projection.projected_points.desc()).all()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No projections found for week {week} source={source}",
        )

    return [
        ProjectionRow(
            player_id=pr.player_id,
            player_name=pr.player.name,
            position=pr.player.position,
            source=pr.source,
            projected_points=pr.projected_points,
            actual_points=pr.actual_points,
        )
        for pr in rows
    ]


@app.post("/bets/place", response_model=BetOut, status_code=201)
def place_bet(req: BetRequest, db: Session = Depends(get_db)):
    matchup = db.query(Matchup).filter(Matchup.id == req.matchup_id).first()
    if not matchup:
        raise HTTPException(status_code=404, detail="Matchup not found")

    wallet = db.query(Wallet).filter(Wallet.id == req.wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    if wallet.balance < req.amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance: ${wallet.balance:.2f} < ${req.amount:.2f}",
        )

    if req.picked_team_id not in (matchup.home_team_id, matchup.away_team_id):
        raise HTTPException(
            status_code=400,
            detail="picked_team_id must be one of the two teams in this matchup",
        )

    # Deduct balance
    wallet.balance = round(wallet.balance - req.amount, 2)

    # Create bet
    bet = Bet(
        matchup_id     = req.matchup_id,
        wallet_id      = req.wallet_id,
        picked_team_id = req.picked_team_id,
        amount         = req.amount,
        odds           = req.odds,
        status         = "won" if req.picked_team_id == matchup.winner_team_id else "lost",
        placed_at      = datetime.now(timezone.utc),
        settled_at     = datetime.now(timezone.utc),
    )
    db.add(bet)
    db.flush()

    # Record transaction
    db.add(Transaction(
        wallet_id  = req.wallet_id,
        amount     = -req.amount,
        type       = "bet",
        bet_id     = bet.id,
        created_at = datetime.now(timezone.utc),
    ))

    # Pay out immediately if won
    if bet.status == "won":
        payout = round(req.amount * req.odds, 2)
        wallet.balance = round(wallet.balance + payout, 2)
        db.add(Transaction(
            wallet_id  = req.wallet_id,
            amount     = payout,
            type       = "payout",
            bet_id     = bet.id,
            created_at = datetime.now(timezone.utc),
        ))

    db.commit()
    db.refresh(bet)

    picked = db.query(Team).filter(Team.id == req.picked_team_id).first()
    return BetOut(
        bet_id         = bet.id,
        matchup_id     = bet.matchup_id,
        wallet_id      = bet.wallet_id,
        picked_team_id = bet.picked_team_id,
        picked_team    = picked.team_name,
        amount         = bet.amount,
        odds           = bet.odds,
        status         = bet.status,
        placed_at      = bet.placed_at.isoformat(),
        to_win         = round(bet.amount * bet.odds, 2),
    )


@app.get("/bets/{matchup_id}", response_model=list[BetOut])
def bets_for_matchup(matchup_id: int, db: Session = Depends(get_db)):
    matchup = db.query(Matchup).filter(Matchup.id == matchup_id).first()
    if not matchup:
        raise HTTPException(status_code=404, detail="Matchup not found")

    bets = (
        db.query(Bet)
        .filter(Bet.matchup_id == matchup_id)
        .order_by(Bet.placed_at)
        .all()
    )

    return [
        BetOut(
            bet_id         = b.id,
            matchup_id     = b.matchup_id,
            wallet_id      = b.wallet_id,
            picked_team_id = b.picked_team_id,
            picked_team    = b.picked_team.team_name,
            amount         = b.amount,
            odds           = b.odds,
            status         = b.status,
            placed_at      = b.placed_at.isoformat(),
            to_win         = round(b.amount * b.odds, 2),
        )
        for b in bets
    ]


@app.get("/wallet/{team_id}", response_model=WalletOut)
def wallet(team_id: int, db: Session = Depends(get_db)):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found")

    w = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    if not w:
        raise HTTPException(status_code=404, detail="Wallet not found")

    open_bets = (
        db.query(Bet).filter(Bet.wallet_id == w.id, Bet.status == "pending").count()
    )
    total_wagered = (
        db.query(Transaction)
        .filter(Transaction.wallet_id == w.id, Transaction.type == "bet")
        .all()
    )
    wagered_sum = sum(abs(t.amount) for t in total_wagered)

    txns = (
        db.query(Transaction)
        .filter(Transaction.wallet_id == w.id)
        .order_by(Transaction.created_at.desc())
        .limit(20)
        .all()
    )

    return WalletOut(
        wallet_id     = w.id,
        team_id       = team_id,
        team_name     = team.team_name,
        balance       = w.balance,
        open_bets     = open_bets,
        total_wagered = round(wagered_sum, 2),
        transactions  = [
            {
                "tx_id":      t.id,
                "amount":     t.amount,
                "type":       t.type,
                "bet_id":     t.bet_id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in txns
        ],
    )


# ── Odds ──────────────────────────────────────────────────────────────────────

class StarterLineOut(BaseModel):
    player_id:        int
    name:             str
    position:         str
    projected_points: float
    adjusted_points:  float


class OddsOut(BaseModel):
    matchup_id:     int
    week:           int
    simulations:    int
    scoring_type:   str
    home_team_id:   int
    home_team_name: str
    away_team_id:   int
    away_team_name: str
    home_win_prob:  float
    away_win_prob:  float
    home_moneyline: int
    away_moneyline: int
    home_proj_mean: float
    away_proj_mean: float
    home_proj_std:  float
    away_proj_std:  float
    home_starters:  list[StarterLineOut]
    away_starters:  list[StarterLineOut]


@app.get("/odds/{matchup_id}/{week}", response_model=OddsOut)
def odds(matchup_id: int, week: int, db: Session = Depends(get_db)):
    if not 1 <= week <= 17:
        raise HTTPException(status_code=400, detail="week must be 1–17")

    matchup = db.query(Matchup).filter(Matchup.id == matchup_id).first()
    if not matchup:
        raise HTTPException(status_code=404, detail=f"Matchup {matchup_id} not found")

    result: OddsResult = mc_run(
        matchup_id = matchup.id,
        home_team  = matchup.home_team,
        away_team  = matchup.away_team,
        week       = week,
        db         = db,
    )

    return OddsOut(
        matchup_id     = result.matchup_id,
        week           = result.week,
        simulations    = result.simulations,
        scoring_type   = result.scoring_type,
        home_team_id   = result.home_team_id,
        home_team_name = result.home_team_name,
        away_team_id   = result.away_team_id,
        away_team_name = result.away_team_name,
        home_win_prob  = result.home_win_prob,
        away_win_prob  = result.away_win_prob,
        home_moneyline = result.home_moneyline,
        away_moneyline = result.away_moneyline,
        home_proj_mean = result.home_proj_mean,
        away_proj_mean = result.away_proj_mean,
        home_proj_std  = result.home_proj_std,
        away_proj_std  = result.away_proj_std,
        home_starters  = [StarterLineOut(**vars(s)) for s in result.home_starters],
        away_starters  = [StarterLineOut(**vars(s)) for s in result.away_starters],
    )


# ── Bet engine endpoints ───────────────────────────────────────────────────────

class BetEngineOut(BaseModel):
    bet_id:      int
    bet_type:    str
    description: str
    amount:      float
    odds_dec:    float
    moneyline:   int
    win_prob:    float
    to_win:      float
    status:      str
    legs:        list | None = None


def _bet_out(r: BetResult) -> BetEngineOut:
    return BetEngineOut(
        bet_id=r.bet_id, bet_type=r.bet_type, description=r.description,
        amount=r.amount, odds_dec=r.odds_dec, moneyline=r.moneyline,
        win_prob=r.win_prob, to_win=r.to_win, status=r.status,
        legs=r.legs,
    )


class StraightBetRequest(BaseModel):
    matchup_id:     int
    wallet_id:      int
    picked_team_id: int
    amount:         float = Field(..., gt=0)
    week:           int   = Field(..., ge=1, le=17)


class SpreadBetRequest(BaseModel):
    matchup_id:     int
    wallet_id:      int
    picked_team_id: int
    spread:         float = Field(..., description="Points the picked team must win by")
    amount:         float = Field(..., gt=0)
    week:           int   = Field(..., ge=1, le=17)


class OverUnderRequest(BaseModel):
    matchup_id:  int
    wallet_id:   int
    total_line:  float = Field(..., gt=0)
    pick:        str   = Field(..., description="over | under")
    amount:      float = Field(..., gt=0)
    week:        int   = Field(..., ge=1, le=17)


class PropBetRequest(BaseModel):
    matchup_id:     int
    wallet_id:      int
    picked_team_id: int = Field(..., description="Team whose top starter you back")
    amount:         float = Field(..., gt=0)
    week:           int   = Field(..., ge=1, le=17)


@app.post("/bets/straight", response_model=BetEngineOut, status_code=201)
def bet_straight(
    req:          StraightBetRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_bet_funded),
):
    assert_own_wallet(req.wallet_id, current_user, db)
    try:
        result = place_straight_bet(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.amount, req.week, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _bet_out(result)


@app.post("/bets/spread", response_model=BetEngineOut, status_code=201)
def bet_spread(
    req:          SpreadBetRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_bet_funded),
):
    assert_own_wallet(req.wallet_id, current_user, db)
    try:
        result = place_spread_bet(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.spread, req.amount, req.week, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _bet_out(result)


@app.post("/bets/over_under", response_model=BetEngineOut, status_code=201)
def bet_over_under(
    req:          OverUnderRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_bet_funded),
):
    assert_own_wallet(req.wallet_id, current_user, db)
    try:
        result = place_over_under(
            req.matchup_id, req.wallet_id, req.total_line,
            req.pick, req.amount, req.week, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _bet_out(result)


@app.post("/bets/prop", response_model=BetEngineOut, status_code=201)
def bet_prop(
    req:          PropBetRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_bet_funded),
):
    assert_own_wallet(req.wallet_id, current_user, db)
    try:
        result = place_prop_bet(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.amount, req.week, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _bet_out(result)


# ── Settlement ─────────────────────────────────────────────────────────────────

class BetSettlementOut(BaseModel):
    bet_id:      int
    bet_type:    str
    description: str
    wallet_id:   int
    owner:       str
    team_name:   str
    amount:      float
    odds_dec:    float
    payout:      float
    profit:      float
    status:      str


class WalletMovementOut(BaseModel):
    wallet_id:      int
    team_name:      str
    owner:          str
    balance_before: float
    bets_won:       int
    bets_lost:      int
    total_staked:   float
    total_payout:   float
    balance_after:  float
    net:            float


class SettlementOut(BaseModel):
    week:             int
    total_bets:       int
    bets_won:         int
    bets_lost:        int
    total_staked:     float
    total_payout:     float
    house_edge:       float
    settlements:      list[BetSettlementOut]
    wallet_movements: list[WalletMovementOut]


@app.get("/settle/{week}", response_model=SettlementOut)
def settle(
    week:  int,
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    if not 1 <= week <= 17:
        raise HTTPException(status_code=400, detail="week must be 1–17")
    report = settle_week(week, db)
    return SettlementOut(
        week             = report.week,
        total_bets       = report.total_bets,
        bets_won         = report.bets_won,
        bets_lost        = report.bets_lost,
        total_staked     = report.total_staked,
        total_payout     = report.total_payout,
        house_edge       = report.house_edge,
        settlements      = [
            BetSettlementOut(
                bet_id=s.bet_id, bet_type=s.bet_type, description=s.description,
                wallet_id=s.wallet_id, owner=s.owner, team_name=s.team_name,
                amount=s.amount, odds_dec=s.odds_dec, payout=s.payout,
                profit=s.profit, status=s.status,
            ) for s in report.settlements
        ],
        wallet_movements = [
            WalletMovementOut(
                wallet_id=mv.wallet_id, team_name=mv.team_name, owner=mv.owner,
                balance_before=mv.balance_before, bets_won=mv.bets_won,
                bets_lost=mv.bets_lost, total_staked=mv.total_staked,
                total_payout=mv.total_payout, balance_after=mv.balance_after,
                net=mv.net,
            ) for mv in report.wallet_movements
        ],
    )


# ── Wallet management ─────────────────────────────────────────────────────────

class DepositRequest(BaseModel):
    wallet_id: int
    amount:    float = Field(..., gt=0, description="Amount to deposit")


class WithdrawRequest(BaseModel):
    wallet_id: int
    amount:    float = Field(..., gt=0, description="Amount to withdraw")


class WalletStateOut(BaseModel):
    wallet_id:        int
    team_id:          int
    team_name:        str
    owner:            str
    balance:          float
    max_single_bet:   float
    open_bets:        int
    pending_exposure: float
    total_deposited:  float
    total_withdrawn:  float
    total_wagered:    float
    total_payout:     float
    net_pnl:          float


class TxRecordOut(BaseModel):
    tx_id:      int
    wallet_id:  int
    amount:     float
    type:       str
    created_at: str
    bet_id:     Optional[int]
    bet_type:   Optional[str]
    bet_desc:   Optional[str]
    bet_status: Optional[str]


class TransactionHistoryOut(BaseModel):
    wallet_id:   int
    team_name:   str
    owner:       str
    balance:     float
    total:       int
    page_size:   int
    page_offset: int
    records:     list[TxRecordOut]


def _state_out(s) -> WalletStateOut:
    return WalletStateOut(
        wallet_id=s.wallet_id, team_id=s.team_id, team_name=s.team_name,
        owner=s.owner, balance=s.balance, max_single_bet=s.max_single_bet,
        open_bets=s.open_bets, pending_exposure=s.pending_exposure,
        total_deposited=s.total_deposited, total_withdrawn=s.total_withdrawn,
        total_wagered=s.total_wagered, total_payout=s.total_payout,
        net_pnl=s.net_pnl,
    )


@app.post("/wallet/deposit", response_model=WalletStateOut, status_code=200)
def wallet_deposit(
    req:          DepositRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    assert_own_wallet(req.wallet_id, current_user, db)
    try:
        state = wm_deposit(req.wallet_id, req.amount, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _state_out(state)


@app.post("/wallet/withdraw", response_model=WalletStateOut, status_code=200)
def wallet_withdraw(
    req:          WithdrawRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    assert_own_wallet(req.wallet_id, current_user, db)
    try:
        state = wm_withdraw(req.wallet_id, req.amount, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _state_out(state)


@app.get("/wallet/{team_id}/history", response_model=TransactionHistoryOut)
def wallet_history(
    team_id: int,
    limit:  int = Query(default=50,  ge=1, le=200),
    offset: int = Query(default=0,   ge=0),
    db: Session = Depends(get_db),
):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found")
    w = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    if not w:
        raise HTTPException(status_code=404, detail="Wallet not found")
    try:
        hist = wm_history(w.id, db, limit=limit, offset=offset)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TransactionHistoryOut(
        wallet_id   = hist.wallet_id,
        team_name   = hist.team_name,
        owner       = hist.owner,
        balance     = hist.balance,
        total       = hist.total,
        page_size   = hist.page_size,
        page_offset = hist.page_offset,
        records     = [
            TxRecordOut(
                tx_id=r.tx_id, wallet_id=r.wallet_id, amount=r.amount,
                type=r.type, created_at=r.created_at, bet_id=r.bet_id,
                bet_type=r.bet_type, bet_desc=r.bet_desc, bet_status=r.bet_status,
            ) for r in hist.records
        ],
    )


# ── Beef endpoints ────────────────────────────────────────────────────────────

class ChallengeRequest(BaseModel):
    challenger_team_id: int
    challenged_team_id: int
    week:               int   = Field(..., ge=1, le=17)
    bet_type:           str   = Field(..., description="straight | spread | over_under | prop")
    amount:             float = Field(..., gt=0)
    # type-specific (pass only what's needed for your bet_type)
    line:               Optional[float] = None
    side:               Optional[str]   = None   # "over" | "under"
    player_id:          Optional[int]   = None
    trash_talk:         Optional[str]   = None


class RespondRequest(BaseModel):
    challenge_id: int
    accept:       bool
    trash_talk:   Optional[str] = None


class ChallengeOut_API(BaseModel):
    challenge_id:         int
    direction:            str
    challenger_team_id:   int
    challenger_name:      str
    challenger_owner:     str
    challenged_team_id:   int
    challenged_name:      str
    challenged_owner:     str
    week:                 int
    bet_type:             str
    amount:               float
    description:          str
    challenger_moneyline: int
    challenged_moneyline: int
    status:               str
    expires_at:           str
    created_at:           str
    responded_at:         Optional[str]
    challenger_bet_id:    Optional[int]
    challenged_bet_id:    Optional[int]


class AcceptResultOut(BaseModel):
    challenge_id:      int
    challenger_bet_id: int
    challenged_bet_id: int
    challenger_team:   str
    challenged_team:   str
    amount:            float
    description:       str
    staleness_warning: bool
    accepted:          bool = True


def _challenge_out(c: ChallengeOut) -> ChallengeOut_API:
    return ChallengeOut_API(**vars(c))


@app.post("/beef/challenge", response_model=ChallengeOut_API, status_code=201)
def beef_challenge(
    req:          ChallengeRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_bet_funded),
):
    assert_own_team(req.challenger_team_id, current_user)
    try:
        result = issue_challenge(
            challenger_team_id = req.challenger_team_id,
            challenged_team_id = req.challenged_team_id,
            week               = req.week,
            bet_type           = req.bet_type,
            amount             = req.amount,
            db                 = db,
            line               = req.line,
            side               = req.side,
            player_id          = req.player_id,
            trash_talk         = req.trash_talk,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _challenge_out(result)


@app.post("/beef/respond", status_code=200)
def beef_respond(
    req:          RespondRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    challenge = db.query(BeefChallenge).filter(BeefChallenge.id == req.challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    assert_own_team(challenge.challenged_team_id, current_user)
    try:
        result = respond_to_challenge(req.challenge_id, req.accept, db,
                                      trash_talk=req.trash_talk)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if isinstance(result, AcceptResult):
        return AcceptResultOut(
            challenge_id      = result.challenge_id,
            challenger_bet_id = result.challenger_bet_id,
            challenged_bet_id = result.challenged_bet_id,
            challenger_team   = result.challenger_team,
            challenged_team   = result.challenged_team,
            amount            = result.amount,
            description       = result.description,
            staleness_warning = result.staleness_warning,
            accepted          = True,
        )
    return _challenge_out(result)


@app.get("/beef/pending/{team_id}", response_model=list[ChallengeOut_API])
def beef_pending(
    team_id:      int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    assert_own_team(team_id, current_user)
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found")
    challenges = get_pending_challenges(team_id, db)
    return [_challenge_out(c) for c in challenges]


# ── Feed endpoints ────────────────────────────────────────────────────────────

class FeedEventOut_API(BaseModel):
    event_id:     int
    league_id:    int
    week:         int
    event_type:   str
    actor_name:   Optional[str]
    target_name:  Optional[str]
    challenge_id: Optional[int]
    bet_id:       Optional[int]
    headline:     str
    trash_talk:   Optional[str]
    created_at:   str


class FeedPageOut(BaseModel):
    league_id: int
    total:     int
    limit:     int
    offset:    int
    events:    list[FeedEventOut_API]


def _feed_event_out(ev: FeedEventOut) -> FeedEventOut_API:
    return FeedEventOut_API(**vars(ev))


@app.get("/feed/league/{league_id}", response_model=FeedPageOut)
def league_feed(
    league_id: int,
    limit:  int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0,  ge=0),
    db: Session = Depends(get_db),
):
    league = db.query(League).filter(League.id == league_id).first()
    if not league:
        raise HTTPException(status_code=404, detail=f"League {league_id} not found")
    page = get_league_feed(league_id, db, limit=limit, offset=offset)
    return FeedPageOut(
        league_id = page.league_id,
        total     = page.total,
        limit     = page.limit,
        offset    = page.offset,
        events    = [_feed_event_out(ev) for ev in page.events],
    )


@app.get("/feed/league/{league_id}/week/{week}", response_model=list[FeedEventOut_API])
def league_week_feed(
    league_id: int,
    week:      int,
    db: Session = Depends(get_db),
):
    if not 1 <= week <= 17:
        raise HTTPException(status_code=400, detail="week must be 1–17")
    league = db.query(League).filter(League.id == league_id).first()
    if not league:
        raise HTTPException(status_code=404, detail=f"League {league_id} not found")
    events = get_week_feed(league_id, week, db)
    return [_feed_event_out(ev) for ev in events]


# ── Payment schemas ───────────────────────────────────────────────────────────

class TreasurySetupRequest(BaseModel):
    league_id:    int
    buy_in_cents: int   = Field(..., ge=0, description="Buy-in amount in cents (e.g. 5000 = $50)")
    payout_split: Optional[list[int]] = Field(
        default=None,
        description="Payout percentages summing to 100 (default [60,30,10])"
    )


class TreasuryOut(BaseModel):
    league_id:             int
    buy_in_amount_cents:   int
    buy_in_dollars:        str
    payout_split:          list[int]
    total_collected_cents: int
    total_paid_out_cents:  int
    season_payout_done:    bool
    teams_paid_in:         int
    teams_total:           int
    mock_mode:             bool


class BuyInLinkOut(BaseModel):
    record_id:    int
    team_id:      int
    team_name:    str
    owner:        str
    amount_cents: int
    amount_dollars: str
    payment_url:  str
    status:       str
    mock_mode:    bool


class BuyInStatusOut(BaseModel):
    team_id:      int
    team_name:    str
    owner:        str
    email:        str
    status:       str
    amount_cents: int
    paid_at:      Optional[str]
    payment_url:  Optional[str]


class BuyInConfirmRequest(BaseModel):
    record_id:               int
    stripe_session_id:       Optional[str] = None
    stripe_payment_intent_id: Optional[str] = None


class PayoutPreviewRowOut(BaseModel):
    place:             int
    team_id:           int
    team_name:         str
    owner:             str
    pct:               int
    amount_cents:      int
    amount_dollars:    str
    stripe_account_id: Optional[str]
    can_receive:       bool


class PayoutPreviewOut(BaseModel):
    league_id:       int
    treasury_cents:  int
    treasury_dollars: str
    payout_split:    list[int]
    rows:            list[PayoutPreviewRowOut]
    mock_mode:       bool
    blocking_issues: list[str]


class PayoutExecuteRequest(BaseModel):
    league_id:       int
    standings_order: Optional[list[int]] = Field(
        default=None,
        description="Team IDs in rank order. If omitted, computed from regular-season record."
    )


class PayoutRecordOut(BaseModel):
    id:                      int
    place:                   int
    team_id:                 int
    team_name:               str
    pct:                     int
    amount_cents:            int
    amount_dollars:          str
    status:                  str
    stripe_transfer_id:      Optional[str]
    stripe_connected_account: Optional[str]
    sent_at:                 Optional[str]


class ConnectLinkOut(BaseModel):
    team_id:        int
    onboarding_url: str
    mock_mode:      bool


class AuditEntryOut(BaseModel):
    id:            int
    event_type:    str
    description:   str
    league_id:     Optional[int]
    team_id:       Optional[int]
    stripe_object: Optional[str]
    amount_cents:  Optional[int]
    created_at:    str


def _cents_to_dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _treasury_out(s: TreasuryState) -> TreasuryOut:
    return TreasuryOut(
        league_id             = s.league_id,
        buy_in_amount_cents   = s.buy_in_amount_cents,
        buy_in_dollars        = _cents_to_dollars(s.buy_in_amount_cents),
        payout_split          = s.payout_split,
        total_collected_cents = s.total_collected_cents,
        total_paid_out_cents  = s.total_paid_out_cents,
        season_payout_done    = s.season_payout_done,
        teams_paid_in         = s.teams_paid_in,
        teams_total           = s.teams_total,
        mock_mode             = s.mock_mode,
    )


def _buyin_link_out(b: BuyInLink) -> BuyInLinkOut:
    return BuyInLinkOut(
        record_id      = b.record_id,
        team_id        = b.team_id,
        team_name      = b.team_name,
        owner          = b.owner,
        amount_cents   = b.amount_cents,
        amount_dollars = _cents_to_dollars(b.amount_cents),
        payment_url    = b.payment_url,
        status         = b.status,
        mock_mode      = b.mock_mode,
    )


# ── Payment endpoints ─────────────────────────────────────────────────────────

@app.post("/payments/setup-treasury", response_model=TreasuryOut, status_code=200)
def payments_setup_treasury(
    req:   TreasurySetupRequest,
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    """Commissioner sets the season buy-in amount and payout split."""
    try:
        state = setup_league_treasury(
            req.league_id, req.buy_in_cents, db,
            payout_split = req.payout_split,
            performer_id = _comm.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _treasury_out(state)


@app.get("/payments/treasury/{league_id}", response_model=TreasuryOut)
def payments_get_treasury(league_id: int, db: Session = Depends(get_db)):
    """Get current treasury state (open endpoint — GMs can see the pot)."""
    try:
        state = get_treasury_state(league_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _treasury_out(state)


@app.get("/payments/buyin-status/{league_id}", response_model=list[BuyInStatusOut])
def payments_buyin_status(
    league_id:    int,
    db:           Session = Depends(get_db),
    _user:        User    = Depends(get_current_gm),
):
    """List buy-in status for all teams (any authenticated user)."""
    league = db.query(League).filter(League.id == league_id).first()
    if not league:
        raise HTTPException(status_code=404, detail=f"League {league_id} not found")
    statuses = get_buyin_status(league_id, db)
    return [
        BuyInStatusOut(
            team_id      = s.team_id,
            team_name    = s.team_name,
            owner        = s.owner,
            email        = s.email,
            status       = s.status,
            amount_cents = s.amount_cents,
            paid_at      = s.paid_at,
            payment_url  = s.payment_url,
        )
        for s in statuses
    ]


@app.post("/payments/buyin-link/{team_id}", response_model=BuyInLinkOut, status_code=200)
def payments_buyin_link(
    team_id:      int,
    league_id:    int = Query(..., description="League ID"),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """
    Generate (or return existing) Stripe Payment Link for a GM's buy-in.
    GMs can request their own link; commissioner can request any team's link.
    """
    assert_own_team(team_id, current_user)
    try:
        link = create_buyin_link(league_id, team_id, db, performer_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _buyin_link_out(link)


@app.post("/payments/buyin-confirm", response_model=BuyInStatusOut, status_code=200)
def payments_buyin_confirm(
    req:   BuyInConfirmRequest,
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    """Commissioner manually confirms a buy-in payment (or called via webhook)."""
    try:
        record = confirm_buyin_payment(
            req.record_id, db,
            stripe_session_id        = req.stripe_session_id,
            stripe_payment_intent_id = req.stripe_payment_intent_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    team = db.query(Team).filter(Team.id == record.team_id).first()
    return BuyInStatusOut(
        team_id      = record.team_id,
        team_name    = team.team_name if team else str(record.team_id),
        owner        = team.owner if team else "",
        email        = team.email if team else "",
        status       = record.status,
        amount_cents = record.amount_cents,
        paid_at      = record.paid_at.isoformat() if record.paid_at else None,
        payment_url  = record.stripe_payment_link_url,
    )


@app.get("/payments/connect-link/{team_id}", response_model=ConnectLinkOut)
def payments_connect_link(
    team_id:      int,
    return_url:   str = Query(default="", description="URL to redirect after Stripe onboarding"),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """
    Get a Stripe Connect onboarding URL so a GM can link their account for payouts.
    GMs can request their own link; commissioner can request any team's link.
    """
    assert_own_team(team_id, current_user)
    try:
        url = create_connect_onboarding_link(team_id, db, return_url=return_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ConnectLinkOut(
        team_id        = team_id,
        onboarding_url = url,
        mock_mode      = not bool(
            db.query(User).filter(User.team_id == team_id).first().stripe_account_id or ""
        ),
    )


@app.get("/payments/payout-preview/{league_id}", response_model=PayoutPreviewOut)
def payments_payout_preview(
    league_id:       int,
    db:              Session = Depends(get_db),
    _comm:           User    = Depends(require_commissioner),
):
    """Preview season-end payout amounts before executing."""
    try:
        preview = preview_payouts(league_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PayoutPreviewOut(
        league_id        = preview.league_id,
        treasury_cents   = preview.treasury_cents,
        treasury_dollars = _cents_to_dollars(preview.treasury_cents),
        payout_split     = preview.payout_split,
        rows             = [
            PayoutPreviewRowOut(
                place             = r.place,
                team_id           = r.team_id,
                team_name         = r.team_name,
                owner             = r.owner,
                pct               = r.pct,
                amount_cents      = r.amount_cents,
                amount_dollars    = _cents_to_dollars(r.amount_cents),
                stripe_account_id = r.stripe_account_id,
                can_receive       = r.can_receive,
            )
            for r in preview.rows
        ],
        mock_mode        = preview.mock_mode,
        blocking_issues  = preview.blocking_issues,
    )


@app.post("/payments/payout-execute", response_model=list[PayoutRecordOut], status_code=200)
def payments_payout_execute(
    req:   PayoutExecuteRequest,
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    """Execute season-end payouts. Commissioner-only. Idempotent per record."""
    try:
        records = execute_payouts(
            req.league_id, db,
            standings_order = req.standings_order,
            performer_id    = _comm.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = []
    for r in records:
        team = db.query(Team).filter(Team.id == r.team_id).first()
        result.append(PayoutRecordOut(
            id                       = r.id,
            place                    = r.place,
            team_id                  = r.team_id,
            team_name                = team.team_name if team else str(r.team_id),
            pct                      = r.pct,
            amount_cents             = r.amount_cents,
            amount_dollars           = _cents_to_dollars(r.amount_cents),
            status                   = r.status,
            stripe_transfer_id       = r.stripe_transfer_id,
            stripe_connected_account = r.stripe_connected_account,
            sent_at                  = r.sent_at.isoformat() if r.sent_at else None,
        ))
    return result


@app.get("/payments/audit-log/{league_id}", response_model=list[AuditEntryOut])
def payments_audit_log(
    league_id: int,
    limit:  int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0,   ge=0),
    db:     Session = Depends(get_db),
    _comm:  User    = Depends(require_commissioner),
):
    """Full Stripe audit trail for the league. Commissioner-only."""
    entries = get_audit_log(league_id, db, limit=limit, offset=offset)
    return [
        AuditEntryOut(
            id            = e.id,
            event_type    = e.event_type,
            description   = e.description,
            league_id     = e.league_id,
            team_id       = e.team_id,
            stripe_object = e.stripe_object,
            amount_cents  = e.amount_cents,
            created_at    = e.created_at,
        )
        for e in entries
    ]


@app.post("/payments/webhook", status_code=200)
async def payments_webhook(
    request: Request,
    db:      Session = Depends(get_db),
):
    """Stripe webhook receiver. Configure in Stripe Dashboard to point here."""
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        result = handle_stripe_webhook(payload, sig_header, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


# ── FAAB schemas ──────────────────────────────────────────────────────────────

class FaabSetupRequest(BaseModel):
    league_id:           int
    opening_bet:         float = Field(default=50.0,  ge=0, description="Opening bet balance in dollars")
    opening_waiver:      float = Field(default=50.0,  ge=0, description="Opening waiver balance in dollars")
    allow_bet_to_waiver: bool  = True
    allow_waiver_to_bet: bool  = True


class FaabConfigOut(BaseModel):
    league_id:           int
    opening_bet:         float
    opening_waiver:      float
    allow_bet_to_waiver: bool
    allow_waiver_to_bet: bool
    season_initialized:  bool


class FaabWalletOut(BaseModel):
    faab_wallet_id:       int
    team_id:              int
    team_name:            str
    owner:                str
    bet_balance:          float
    bet_open_bets:        int
    bet_pending_exposure: float
    bet_max_single_bet:   float
    bet_frozen:           bool
    waiver_balance:       float
    pending_waiver_topup: float
    total_available:      float


class TopupRequest(BaseModel):
    team_id: int
    amount:  float = Field(..., gt=0)


class TopupOut(BaseModel):
    faab_tx_id:  int
    team_id:     int
    wallet_type: str
    amount:      float
    status:      str
    apply_on:    Optional[str]
    payment_url: Optional[str]
    mock_mode:   bool


class TopupConfirmRequest(BaseModel):
    faab_tx_id:        int
    stripe_session_id: Optional[str] = None


class TransferRequest(BaseModel):
    team_id:     int
    from_wallet: str = Field(..., description='"bet" or "waiver"')
    to_wallet:   str = Field(..., description='"bet" or "waiver"')
    amount:      float = Field(..., gt=0)


class TransferOut(BaseModel):
    team_id:              int
    from_wallet:          str
    to_wallet:            str
    amount:               float
    bet_balance_after:    float
    waiver_balance_after: float


class FaabTxOut(BaseModel):
    id:          int
    team_id:     int
    tx_type:     str
    amount:      float
    wallet_from: Optional[str]
    wallet_to:   Optional[str]
    status:      str
    note:        Optional[str]
    apply_on:    Optional[str]
    applied_at:  Optional[str]
    created_at:  str


class FreezeRequest(BaseModel):
    team_id: int
    frozen:  bool


def _cfg_out(c: FaabConfigState) -> FaabConfigOut:
    return FaabConfigOut(
        league_id           = c.league_id,
        opening_bet         = c.opening_bet,
        opening_waiver      = c.opening_waiver,
        allow_bet_to_waiver = c.allow_bet_to_waiver,
        allow_waiver_to_bet = c.allow_waiver_to_bet,
        season_initialized  = c.season_initialized,
    )


def _fw_out(s: FaabWalletState) -> FaabWalletOut:
    return FaabWalletOut(
        faab_wallet_id       = s.faab_wallet_id,
        team_id              = s.team_id,
        team_name            = s.team_name,
        owner                = s.owner,
        bet_balance          = s.bet_balance,
        bet_open_bets        = s.bet_open_bets,
        bet_pending_exposure = s.bet_pending_exposure,
        bet_max_single_bet   = s.bet_max_single_bet,
        bet_frozen           = s.bet_frozen,
        waiver_balance       = s.waiver_balance,
        pending_waiver_topup = s.pending_waiver_topup,
        total_available      = s.total_available,
    )


def _topup_out(t: TopupResult) -> TopupOut:
    return TopupOut(
        faab_tx_id  = t.faab_tx_id,
        team_id     = t.team_id,
        wallet_type = t.wallet_type,
        amount      = t.amount,
        status      = t.status,
        apply_on    = t.apply_on,
        payment_url = t.payment_url,
        mock_mode   = t.mock_mode,
    )


def _tx_out(t: FaabTxRecord) -> FaabTxOut:
    return FaabTxOut(
        id          = t.id,
        team_id     = t.team_id,
        tx_type     = t.tx_type,
        amount      = t.amount,
        wallet_from = t.wallet_from,
        wallet_to   = t.wallet_to,
        status      = t.status,
        note        = t.note,
        apply_on    = t.apply_on,
        applied_at  = t.applied_at,
        created_at  = t.created_at,
    )


# ── FAAB endpoints ────────────────────────────────────────────────────────────

@app.post("/faab/setup", response_model=FaabConfigOut, status_code=200)
def faab_setup(
    req:   FaabSetupRequest,
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    """Commissioner configures opening balances and transfer rules for the season."""
    try:
        cfg = setup_faab_config(
            req.league_id, db,
            opening_bet         = req.opening_bet,
            opening_waiver      = req.opening_waiver,
            allow_bet_to_waiver = req.allow_bet_to_waiver,
            allow_waiver_to_bet = req.allow_waiver_to_bet,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _cfg_out(cfg)


@app.get("/faab/config/{league_id}", response_model=FaabConfigOut)
def faab_get_config(
    league_id: int,
    db:        Session = Depends(get_db),
    _user:     User    = Depends(get_current_gm),
):
    """Get FAAB configuration for the league."""
    try:
        cfg = get_faab_config(league_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _cfg_out(cfg)


@app.post("/faab/init-season", response_model=list[FaabWalletOut], status_code=200)
def faab_init_season(
    league_id: int = Query(..., description="League ID"),
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_commissioner),
):
    """
    Credit opening balances to all teams in the league.
    Idempotent — skips teams that already have FAAB wallets.
    """
    try:
        states = init_season_wallets(league_id, db, performer_id=_comm.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [_fw_out(s) for s in states]


@app.get("/faab/wallet/{team_id}", response_model=FaabWalletOut)
def faab_get_wallet(
    team_id: int,
    db:      Session = Depends(get_db),
):
    """Get combined bet + waiver wallet state for a team."""
    try:
        state = get_faab_wallet(team_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _fw_out(state)


@app.get("/faab/league/{league_id}", response_model=list[FaabWalletOut])
def faab_league_wallets(
    league_id: int,
    db:        Session = Depends(get_db),
    _user:     User    = Depends(get_current_gm),
):
    """All teams' FAAB wallet states (any authenticated user)."""
    league = db.query(League).filter(League.id == league_id).first()
    if not league:
        raise HTTPException(status_code=404, detail=f"League {league_id} not found")
    return [_fw_out(s) for s in get_league_faab(league_id, db)]


@app.post("/faab/topup-bet", response_model=TopupOut, status_code=200)
def faab_topup_bet(
    req:          TopupRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """
    Top up the bet wallet via Stripe.
    Mock mode: applied immediately. Real mode: returns Payment Link URL.
    """
    assert_own_team(req.team_id, current_user)
    try:
        result = create_bet_topup(req.team_id, req.amount, db, performer_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _topup_out(result)


@app.post("/faab/topup-waiver", response_model=TopupOut, status_code=200)
def faab_topup_waiver(
    req:          TopupRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """
    Queue a waiver wallet top-up for the next Tuesday.
    Funds are reserved (pending_waiver_topup) but not yet available for bids.
    """
    assert_own_team(req.team_id, current_user)
    try:
        result = create_waiver_topup(req.team_id, req.amount, db, performer_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _topup_out(result)


@app.post("/faab/topup-confirm", response_model=TopupOut, status_code=200)
def faab_topup_confirm(
    req:   TopupConfirmRequest,
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    """
    Manually confirm a pending top-up (commissioner or webhook dispatch).
    Bet top-ups apply immediately; waiver top-ups remain queued for Tuesday.
    """
    try:
        result = confirm_topup(req.faab_tx_id, db, stripe_session_id=req.stripe_session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _topup_out(result)


@app.post("/faab/apply-pending", response_model=list[FaabTxOut], status_code=200)
def faab_apply_pending(
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    """
    Apply all waiver top-ups whose apply_on date has passed.
    Commissioner-only. Intended for Tuesday automation.
    """
    applied = apply_pending_topups(db)
    return [_tx_out(t) for t in applied]


@app.post("/faab/transfer", response_model=TransferOut, status_code=200)
def faab_do_transfer(
    req:          TransferRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """
    Move funds between bet and waiver wallets.
    Subject to commissioner-configured transfer direction rules.
    Bet→waiver transfers respect pending bet exposure (can't move locked funds).
    """
    assert_own_team(req.team_id, current_user)
    try:
        result = faab_transfer(
            req.team_id, req.from_wallet, req.to_wallet, req.amount, db,
            performer_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TransferOut(
        team_id              = result.team_id,
        from_wallet          = result.from_wallet,
        to_wallet            = result.to_wallet,
        amount               = result.amount,
        bet_balance_after    = result.bet_balance_after,
        waiver_balance_after = result.waiver_balance_after,
    )


@app.get("/faab/transactions/{team_id}", response_model=list[FaabTxOut])
def faab_transactions(
    team_id:      int,
    limit:        int = Query(default=50, ge=1, le=200),
    offset:       int = Query(default=0,  ge=0),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """Paginated FAAB transaction history for a team."""
    assert_own_team(team_id, current_user)
    txns = get_faab_transactions(team_id, db, limit=limit, offset=offset)
    return [_tx_out(t) for t in txns]


@app.post("/faab/freeze", response_model=FaabWalletOut, status_code=200)
def faab_set_freeze(
    req:   FreezeRequest,
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    """Commissioner manually freezes or unfreezes a team's bet wallet."""
    try:
        state = set_freeze(req.team_id, req.frozen, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _fw_out(state)


# ── Rules schemas ─────────────────────────────────────────────────────────────

class ParseRuleRequest(BaseModel):
    league_id: int
    raw_text:  str


class ParsePreviewOut(BaseModel):
    rule_type:              str
    effect_type:            str
    target:                 str
    amount:                 float
    has_escrow:             bool
    escrow_release_trigger: Optional[str]
    escrow_release_target:  Optional[str]
    week_start:             Optional[int]
    week_end:               Optional[int]
    ai_interpretation:      str
    ai_model_used:          str
    ai_latency_ms:          int
    raw_text:               str


class CreateRuleRequest(BaseModel):
    league_id: int
    raw_text:  str
    spec:      dict   # the ParsePreviewOut fields minus display-only fields


class EscrowOutModel(BaseModel):
    escrow_id:       int
    name:            str
    balance:         float
    status:          str
    release_trigger: str
    released_at:     Optional[str]


class RuleOutModel(BaseModel):
    rule_id:                int
    league_id:              int
    raw_text:               str
    rule_type:              str
    effect_type:            str
    target:                 str
    amount:                 float
    has_escrow:             bool
    escrow_release_trigger: Optional[str]
    escrow_release_target:  Optional[str]
    ai_interpretation:      Optional[str]
    ai_model_used:          Optional[str]
    status:                 str
    week_start:             Optional[int]
    week_end:               Optional[int]
    created_at:             str
    activated_at:           Optional[str]
    escrow:                 Optional[EscrowOutModel]


class RuleExecutionOutModel(BaseModel):
    execution_id: int
    rule_id:      int
    week:         Optional[int]
    team_id:      int
    team_name:    str
    effect_type:  str
    amount:       float
    description:  str
    status:       str
    executed_at:  str


class WeeklyExecuteRequest(BaseModel):
    league_id: int
    week:      int = Field(..., ge=1, le=17)


class EosExecuteRequest(BaseModel):
    league_id: int


class ReleaseEscrowRequest(BaseModel):
    target_team_id: Optional[int] = None


def _preview_out(p: ParsePreview) -> ParsePreviewOut:
    return ParsePreviewOut(
        rule_type              = p.rule_type,
        effect_type            = p.effect_type,
        target                 = p.target,
        amount                 = p.amount,
        has_escrow             = p.has_escrow,
        escrow_release_trigger = p.escrow_release_trigger,
        escrow_release_target  = p.escrow_release_target,
        week_start             = p.week_start,
        week_end               = p.week_end,
        ai_interpretation      = p.ai_interpretation,
        ai_model_used          = p.ai_model_used,
        ai_latency_ms          = p.ai_latency_ms,
        raw_text               = p.raw_text,
    )


def _rule_model_out(r: RuleOut) -> RuleOutModel:
    return RuleOutModel(
        rule_id                = r.rule_id,
        league_id              = r.league_id,
        raw_text               = r.raw_text,
        rule_type              = r.rule_type,
        effect_type            = r.effect_type,
        target                 = r.target,
        amount                 = r.amount,
        has_escrow             = r.has_escrow,
        escrow_release_trigger = r.escrow_release_trigger,
        escrow_release_target  = r.escrow_release_target,
        ai_interpretation      = r.ai_interpretation,
        ai_model_used          = r.ai_model_used,
        status                 = r.status,
        week_start             = r.week_start,
        week_end               = r.week_end,
        created_at             = r.created_at,
        activated_at           = r.activated_at,
        escrow                 = EscrowOutModel(
            escrow_id       = r.escrow.escrow_id,
            name            = r.escrow.name,
            balance         = r.escrow.balance,
            status          = r.escrow.status,
            release_trigger = r.escrow.release_trigger,
            released_at     = r.escrow.released_at,
        ) if r.escrow else None,
    )


def _exec_model_out(e: RuleExecutionOut) -> RuleExecutionOutModel:
    return RuleExecutionOutModel(
        execution_id = e.execution_id,
        rule_id      = e.rule_id,
        week         = e.week,
        team_id      = e.team_id,
        team_name    = e.team_name,
        effect_type  = e.effect_type,
        amount       = e.amount,
        description  = e.description,
        status       = e.status,
        executed_at  = e.executed_at,
    )


# ── Rules endpoints ───────────────────────────────────────────────────────────

@app.post("/rules/parse", response_model=ParsePreviewOut, status_code=200)
def rules_parse(
    req:   ParseRuleRequest,
    _comm: User    = Depends(require_commissioner),
):
    """
    Parse a natural language rule using AI (Ollama → Anthropic → heuristic).
    Does NOT save anything — commissioner reviews the preview before creating.
    """
    try:
        spec, model, latency = parse_rule_text(req.raw_text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ParsePreviewOut(
        rule_type              = spec["rule_type"],
        effect_type            = spec["effect_type"],
        target                 = spec["target"],
        amount                 = spec["amount"],
        has_escrow             = spec["has_escrow"],
        escrow_release_trigger = spec.get("escrow_release_trigger"),
        escrow_release_target  = spec.get("escrow_release_target"),
        week_start             = spec.get("week_start"),
        week_end               = spec.get("week_end"),
        ai_interpretation      = spec.get("ai_interpretation", ""),
        ai_model_used          = model,
        ai_latency_ms          = latency,
        raw_text               = req.raw_text,
    )


@app.post("/rules/create", response_model=RuleOutModel, status_code=201)
def rules_create(
    req:   CreateRuleRequest,
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    """
    Save a parsed rule as a draft.
    Pass the spec dict from /rules/parse, optionally edited before saving.
    """
    try:
        rule = create_rule_draft(
            req.league_id, req.raw_text, req.spec, db,
            performer_id = _comm.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _rule_model_out(rule)


@app.get("/rules/league/{league_id}", response_model=list[RuleOutModel])
def rules_list(
    league_id: int,
    status:    Optional[str] = Query(default=None, description="draft|active|paused|completed"),
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_commissioner),
):
    """List all rules for a league (commissioner-only)."""
    return [_rule_model_out(r) for r in list_rules(league_id, db, status=status)]


@app.get("/rules/{rule_id}", response_model=RuleOutModel)
def rules_get(
    rule_id: int,
    db:      Session = Depends(get_db),
    _comm:   User    = Depends(require_commissioner),
):
    """Get a specific rule by ID."""
    try:
        return _rule_model_out(get_rule(rule_id, db))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/rules/activate/{rule_id}", response_model=RuleOutModel, status_code=200)
def rules_activate(
    rule_id: int,
    db:      Session = Depends(get_db),
    _comm:   User    = Depends(require_commissioner),
):
    """Activate a draft rule so it will be executed on Tuesday runs."""
    try:
        return _rule_model_out(activate_rule(rule_id, db, performer_id=_comm.id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/rules/pause/{rule_id}", response_model=RuleOutModel, status_code=200)
def rules_pause(
    rule_id: int,
    db:      Session = Depends(get_db),
    _comm:   User    = Depends(require_commissioner),
):
    """Pause an active rule without deleting it."""
    try:
        return _rule_model_out(pause_rule(rule_id, db, performer_id=_comm.id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/rules/draft/{rule_id}", status_code=204)
def rules_delete_draft(
    rule_id: int,
    db:      Session = Depends(get_db),
    _comm:   User    = Depends(require_commissioner),
):
    """Delete a draft rule (cannot delete active/paused/completed rules)."""
    try:
        delete_draft(rule_id, db, performer_id=_comm.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/rules/execute-weekly", response_model=list[RuleExecutionOutModel], status_code=200)
def rules_execute_weekly(
    req:   WeeklyExecuteRequest,
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    """
    Execute all active weekly rules for the given week.
    Called by Tuesday automation (P1.5). Idempotent.
    """
    try:
        execs = execute_weekly_rules(req.league_id, req.week, db, performer_id=_comm.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [_exec_model_out(e) for e in execs]


@app.post("/rules/execute-end-of-season", response_model=list[RuleExecutionOutModel], status_code=200)
def rules_execute_eos(
    req:   EosExecuteRequest,
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    """
    Execute all active end-of-season rules and release qualifying escrow accounts.
    Called during final settlement (P1.5). Idempotent.
    """
    try:
        execs = execute_end_of_season_rules(req.league_id, db, performer_id=_comm.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [_exec_model_out(e) for e in execs]


@app.get("/rules/executions/{league_id}", response_model=list[RuleExecutionOutModel])
def rules_executions(
    league_id: int,
    rule_id:   Optional[int] = Query(default=None),
    week:      Optional[int] = Query(default=None, ge=1, le=17),
    limit:     int = Query(default=100, ge=1, le=500),
    offset:    int = Query(default=0,   ge=0),
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_commissioner),
):
    """Paginated rule execution history. Filter by rule_id and/or week."""
    return [
        _exec_model_out(e)
        for e in get_rule_executions(league_id, db, rule_id=rule_id, week=week,
                                     limit=limit, offset=offset)
    ]


@app.post("/rules/release-escrow/{escrow_id}", response_model=EscrowOutModel, status_code=200)
def rules_release_escrow(
    escrow_id:    int,
    req:          ReleaseEscrowRequest,
    db:           Session = Depends(get_db),
    _comm:        User    = Depends(require_commissioner),
):
    """
    Manually release an open escrow to a target team's bet wallet.
    If target_team_id is omitted, uses the escrow's stored release target.
    """
    try:
        esc = release_escrow(escrow_id, db, performer_id=_comm.id,
                             target_team_id=req.target_team_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return EscrowOutModel(
        escrow_id       = esc.escrow_id,
        name            = esc.name,
        balance         = esc.balance,
        status          = esc.status,
        release_trigger = esc.release_trigger,
        released_at     = esc.released_at,
    )


@app.get("/rules/audit/{league_id}")
def rules_audit(
    league_id: int,
    limit:  int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0,   ge=0),
    db:     Session = Depends(get_db),
    _comm:  User    = Depends(require_commissioner),
):
    """Full rule audit trail for the league. Commissioner-only."""
    return get_rule_audit_log(league_id, db, limit=limit, offset=offset)


# ── Tuesday Sync schemas ──────────────────────────────────────────────────────

class TuesdaySyncRequest(BaseModel):
    league_id: int
    week:      int = Field(..., ge=1, le=17)
    mock_mode: bool = True   # default True for safety — set False for real emails


class TuesdaySyncStepOut(BaseModel):
    step:        str
    success:     bool
    message:     str
    data:        dict
    error:       Optional[str]
    duration_ms: int


class TuesdaySyncOut(BaseModel):
    run_id:      str
    league_id:   int
    week:        int
    started_at:  str
    finished_at: str
    mock_mode:   bool
    steps:       list[TuesdaySyncStepOut]
    emails_sent: int
    error_count: int
    status:      str


def _sync_out(s: TuesdayRunSummary) -> TuesdaySyncOut:
    return TuesdaySyncOut(
        run_id      = s.run_id,
        league_id   = s.league_id,
        week        = s.week,
        started_at  = s.started_at,
        finished_at = s.finished_at,
        mock_mode   = s.mock_mode,
        steps       = [TuesdaySyncStepOut(**vars(step)) for step in s.steps],
        emails_sent = s.emails_sent,
        error_count = s.error_count,
        status      = s.status,
    )


# ── Tuesday Sync endpoints ────────────────────────────────────────────────────

@app.post("/admin/tuesday-sync", response_model=TuesdaySyncOut, status_code=200)
def admin_tuesday_sync(
    req:   TuesdaySyncRequest,
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    """
    Manually trigger the Tuesday automation for a specific week.
    Set mock_mode=false only when SMTP is configured and you want real emails.
    """
    try:
        summary = run_tuesday_sync(
            req.league_id, req.week, db, mock_mode=req.mock_mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _sync_out(summary)


@app.get("/admin/tuesday-sync/runs/{league_id}")
def admin_sync_runs(
    league_id: int,
    limit:     int = Query(default=20, ge=1, le=100),
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_commissioner),
):
    """List recent Tuesday sync runs for a league. Commissioner-only."""
    return get_run_history(league_id, db, limit=limit)


@app.get("/admin/tuesday-sync/run/{run_id}")
def admin_sync_run_detail(
    run_id: str,
    db:     Session = Depends(get_db),
    _comm:  User    = Depends(require_commissioner),
):
    """Get full detail for a specific Tuesday sync run, including all step logs."""
    result = get_run_detail(run_id, db)
    if not result:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    return result


# ── Weekly Wrap-Up schemas ────────────────────────────────────────────────────

class WrapUpGenerateRequest(BaseModel):
    league_id: int
    week:      int = Field(..., ge=1, le=17)
    mock_mode: bool = True


class WrapUpEditRequest(BaseModel):
    league_body: Optional[str] = None
    roast_beef:  Optional[str] = None


class WrapUpSendRequest(BaseModel):
    mock_mode: bool = True


def _wrapup_out(w: WrapUpOut) -> dict:
    return {
        "wrap_up_id":          w.wrap_up_id,
        "run_id":              w.run_id,
        "league_id":           w.league_id,
        "week":                w.week,
        "status":              w.status,
        "league_body":         w.league_body,
        "roast_beef":          w.roast_beef,
        "ai_model_used":       w.ai_model_used,
        "ai_latency_ms":       w.ai_latency_ms,
        "commissioner_edited": w.commissioner_edited,
        "gm_count":            w.gm_count,
        "created_at":          w.created_at,
        "sent_at":             w.sent_at,
    }


# ── Weekly Wrap-Up endpoints ──────────────────────────────────────────────────

@app.post("/reports/wrap-up/generate", status_code=201)
def reports_wrap_up_generate(
    req:   WrapUpGenerateRequest,
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    """
    Generate AI Weekly Wrap-Up + Roast Beef for the given week.
    Stores as draft, posts to feed, and emails all GMs.
    Commissioner can regenerate with updated content.
    """
    try:
        out = generate_weekly_wrap(req.league_id, req.week, db, mock_mode=req.mock_mode)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return _wrapup_out(out)


@app.get("/reports/wrap-up/{league_id}/{week}")
def reports_wrap_up_get(
    league_id: int,
    week:      int,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_commissioner),
):
    """Get the most recent wrap-up for a specific week."""
    out = get_wrap_up(league_id, week, db)
    if not out:
        raise HTTPException(status_code=404, detail=f"No wrap-up found for week {week}")
    return _wrapup_out(out)


@app.get("/reports/wrap-up/{league_id}")
def reports_wrap_up_list(
    league_id: int,
    limit:     int = Query(default=20, ge=1, le=100),
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_commissioner),
):
    """List all wrap-ups for a league, newest first."""
    return [_wrapup_out(w) for w in get_wrap_up_list(league_id, db, limit=limit)]


@app.put("/reports/wrap-up/{wrap_up_id}", status_code=200)
def reports_wrap_up_edit(
    wrap_up_id: int,
    req:        WrapUpEditRequest,
    db:         Session = Depends(get_db),
    _comm:      User    = Depends(require_commissioner),
):
    """Commissioner edits the league body and/or roast beef section before send."""
    try:
        out = update_wrap_up(wrap_up_id, req.league_body, req.roast_beef, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _wrapup_out(out)


@app.post("/reports/wrap-up/{wrap_up_id}/send", status_code=200)
def reports_wrap_up_send(
    wrap_up_id: int,
    req:        WrapUpSendRequest,
    db:         Session = Depends(get_db),
    _comm:      User    = Depends(require_commissioner),
):
    """
    Re-send (or first-send) wrap-up emails to all GMs.
    Use after commissioner has reviewed/edited the draft.
    """
    try:
        sent = send_wrap_up(wrap_up_id, db, mock_mode=req.mock_mode)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"wrap_up_id": wrap_up_id, "emails_sent": sent}


@app.get("/reports/wrap-up/{wrap_up_id}/editions", status_code=200)
def reports_wrap_up_editions(
    wrap_up_id: int,
    db:         Session = Depends(get_db),
    _comm:      User    = Depends(require_commissioner),
):
    """List all per-GM editions for a wrap-up (status tags, playoff prob, sent status)."""
    return get_gm_editions(wrap_up_id, db)


# ── Power Rankings endpoints ───────────────────────────────────────────────────

from reports.power_rankings import (
    PowerRankingOut,
    compute_power_rankings as _compute_rankings,
    get_league_arc,
    get_power_rankings as _get_rankings,
    get_team_ranking_history,
)


class RankingsComputeRequest(BaseModel):
    league_id: int
    week:      int = Field(..., ge=1, le=17)


@app.post("/reports/rankings/compute", status_code=201)
def reports_rankings_compute(
    req:   RankingsComputeRequest,
    db:    Session = Depends(get_db),
    _comm: User    = Depends(require_commissioner),
):
    """Compute (or recompute) power rankings for the given league and week, post to feed."""
    rankings = _compute_rankings(req.league_id, req.week, db)
    if not rankings:
        raise HTTPException(404, "No teams found for this league")
    return rankings


@app.get("/reports/rankings/{league_id}/{week}")
def reports_rankings_get_week(
    league_id: int,
    week:      int,
    db:        Session = Depends(get_db),
):
    """Retrieve stored power rankings for a specific week, sorted by composite rank."""
    out = _get_rankings(league_id, week, db)
    if not out:
        raise HTTPException(404, f"No rankings found for league {league_id} week {week}")
    return out


@app.get("/reports/rankings/{league_id}/arc")
def reports_rankings_arc(
    league_id: int,
    db:        Session = Depends(get_db),
):
    """Return all computed weekly rankings keyed by week — full season arc."""
    arc = get_league_arc(league_id, db)
    if not arc:
        raise HTTPException(404, f"No rankings found for league {league_id}")
    return arc


@app.get("/reports/rankings/{league_id}/team/{team_id}")
def reports_rankings_team_history(
    league_id: int,
    team_id:   int,
    limit:     int = Query(default=17, ge=1, le=17),
    db:        Session = Depends(get_db),
):
    """Return one team's ranking history across all computed weeks."""
    out = get_team_ranking_history(league_id, team_id, db, limit=limit)
    if not out:
        raise HTTPException(404, f"No rankings found for team {team_id} in league {league_id}")
    return out


# ── Decision Engine health routes ─────────────────────────────────────────────

from api.health_routes import router as health_router  # noqa: E402
app.include_router(health_router)

from api.war_room_routes import router as war_room_router  # noqa: E402
app.include_router(war_room_router)
from api.pool_routes import router as pool_router  # noqa: E402
app.include_router(pool_router)
