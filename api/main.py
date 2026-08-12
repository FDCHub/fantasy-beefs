from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import (
    Bet,
    BeefChallenge,
    CommissionerRule,
    EscrowAccount,
    FaabTransaction,
    League,
    LeagueCommissioner,
    Matchup,
    Player,
    Projection,
    Roster,
    Team,
    Transaction,
    TuesdaySyncRun,
    User,
    Wallet,
    WeeklyWrapUp,
    SessionLocal,
)

from db.deps import get_db
# trial_balance is deliberately NOT imported here. S8-P3R keeps the global
# conservation invariant backend-only: it has no HTTP surface in the MVP,
# because the authority model has no platform-operator tier that could safely
# hold one. Importing it into the API layer would be the first step back
# towards exposing it by accident.
from ledger.ledger import balance_of, _balance_of_in_session, _to_cents
from odds.monte_carlo import OddsResult, run as mc_run
from betting.bet_engine import (
    BetResult,
    place_straight_bet,
    place_spread_bet,
    place_over_under,
    place_prop_bet,
)
from betting.exceptions import NotFoundError, BetValidationError
from betting.finality_gate import ResultsNotReadyError
from betting.settlement_engine import settle_week, SettlementReport
from reports.league_read_model import (
    LeagueReadError, league_context, season_record, week_matchups,
)
from reports.action_read_model import (
    SECTIONS as ACTION_SECTIONS, ActionReadError, gm_action_state,
)
from feed.league_feed import get_league_feed, get_week_feed, FeedPage, FeedEventOut
from wallet.wallet_manager import (
    deposit     as wm_deposit,
    balance_check_by_team,
    transaction_history as wm_history,
)
from auth.jwt_auth import (
    authenticate_user,
    assert_own_team,
    assert_wagering_team_owner,
    assert_own_wallet,
    create_access_token,
    get_current_gm,
    promote_user,
    register_user,
    require_commissioner,
)
from auth.allocation_gate import (
    assert_league_commissioner,
    get_allocation_enforcement_active,
    get_season_allocation_gate,
    is_league_commissioner,
    require_league_commissioner,
    set_allocation_enforcement_active,
)
from auth.session import (
    CSRF_HEADER,
    clear_browser_session,
    csrf_failure_reason,
    issue_browser_session,
    new_csrf_token,
)
from economy.top_off import (
    approve_top_off,
    cancel_top_off,
    create_top_off_request,
    reject_top_off,
    AttemptValidationAbort,
    AuthorizationAttemptAbort,
    CreationRefused,
    IntegrityAttemptAbort,
    RequestNotFoundError,
    SeasonClosedAbort,
    TOPUP_BET,
    REASON_CAP_EXHAUSTED,
    REASON_INVALID_AMOUNT,
    REASON_MULTIPLIER_ZERO,
    REASON_NO_ALLOCATION,
    REASON_OPEN_REQUEST,
    REASON_OVER_CAPACITY,
    REASON_SEASON_CLOSED,
    REASON_TEAM_NOT_IN_LEAGUE,
)

# Temporary B2 compatibility export for tests; remove during Group 5.
get_buyin_gate = get_season_allocation_gate

# payments.stripe_connect is intentionally NOT imported. Stripe is out of the
# MVP: there is no payment-processing, connected-account, payout or webhook
# surface in the registered API. Season allocation plus the internal Credits
# ledger is the sole funding and accounting model. See
# spec/SPEC_B2_Stripe_Removal_Addendum_v1.md.
from economy.season_allocation import (
    ConflictingAllocationError,
    NoTeamsError,
    PartialAllocationError,
    activate_season_allocation,
)
from notifications.tuesday_sync import (
    TuesdayRunSummary,
    get_run_detail,
    get_run_history,
    run_tuesday_sync,
    _assert_slate_fresh,
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
from reports.my_account import get_my_account_summary
from reports.settlement_report import championship_settlement_report
from reports.ledger_read_model import (
    REASON_LEAGUE_NOT_FOUND,
    REASON_TEAM_NOT_IN_LEAGUE,
    LedgerReadModelError,
    gm_ledger,
    league_positions,
    league_reconciliation,
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
    check_and_freeze,
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

# ── CORS (S8-P1) ──────────────────────────────────────────────────────────────
#
# WAS allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]. That is
# incompatible with a cookie credential in two ways. Practically: a browser
# refuses a wildcard origin on a credentialed request, so the setting could not
# work as written. Substantively: it advertised that any site could read every
# API response, and now that the browser attaches a session automatically, a
# permissive CORS policy is what would turn "any site can call the API" into
# "any site can call the API AS THE SIGNED-IN GM".
#
# The Rev 4.2 app is served by THIS process at /app, so the browser app needs
# no CORS at all — a same-origin request never consults this policy. The
# default is therefore the empty list: cross-origin browser access is off
# unless an operator names the origins.
#
# FS_ALLOWED_ORIGINS is a comma-separated list of EXACT origins. No wildcard
# and no regex: a deployment that needs a partner origin should have to name it.
_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("FS_ALLOWED_ORIGINS", "").split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", CSRF_HEADER],
)


# ── CSRF gate (S8-P1) ─────────────────────────────────────────────────────────

@app.middleware("http")
async def _csrf_gate(request: Request, call_next):
    """Refuse any unsafe request that presents a session cookie without a
    matching CSRF token.

    MIDDLEWARE, NOT A DEPENDENCY, AND THAT IS THE POINT. A dependency protects
    the routes that remember to declare it. This app has over a hundred routes
    and Sprint 8 adds more; one added later without the dependency would be
    silently unprotected, and the failure would be invisible because the route
    would work perfectly. Here the default is protected and a bypass has to be
    written deliberately.

    It runs BEFORE routing, so an unknown path, a wrong method and a validation
    error are covered on the same terms as a real route.

    The decision itself lives in auth/session.py — this is the enforcement
    point, not the policy.
    """
    reason = csrf_failure_reason(request)
    if reason is not None:
        return JSONResponse(status_code=403, content={"detail": reason})
    return await call_next(request)


app.mount("/tools", StaticFiles(directory="tools"), name="tools")

# UI/UX Rev 4.2 application shell (Sprint 7). Static assets only: HTML, CSS and
# ES modules. Serving them reads and writes no protocol state. The directory is
# resolved from this file's location rather than the process working directory,
# so the shell is served identically however the app is launched.
_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
app.mount("/app", StaticFiles(directory=_WEB_DIR, html=True), name="app")


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


def _league_of(model, entity_id, db: Session, label: str) -> int:
    """The league a governed entity belongs to (S8-P2).

    Rules, escrow accounts, sync runs and wrap-ups all carry `league_id`
    directly, so this is a lookup and never a traversal — there is no chain of
    joins whose middle link could go missing and silently widen authority.

    ORDER OF DISCLOSURE, stated because it is a security decision. A caller
    must be told 404 for an entity that does not exist and 403 for one they may
    not touch, which means existence is observable BEFORE authority is checked
    on these routes. That is unavoidable when the league can only be learned
    from the entity itself, and it is strictly better than what it replaces:
    before P2, any globally-roled commissioner could not merely observe these
    rows but read and mutate every one of them, in every league.

    Routes whose league is in the PATH do not have this property and do not use
    this helper — `require_league_commissioner` refuses them before any lookup.
    """
    row = db.query(model).filter(model.id == entity_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return row.league_id


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


# ── Browser session (S8-P1) ───────────────────────────────────────────────────

class SessionLoginRequest(BaseModel):
    """JSON, not form-encoded.

    /auth/login keeps the OAuth2 form shape because that is the contract API
    clients and /docs already use. A browser fetch sends JSON, and a form POST
    is exactly the shape a cross-site CSRF attempt takes, so the browser path
    does not accept one.
    """
    email:    str
    password: str


class CapabilitiesOut(BaseModel):
    """What the acting user may do, decided HERE.

    THE FRONTEND MAY NOT COMPUTE THIS. It exists so presentation can follow
    authority instead of guessing at it — a disabled button is a courtesy, not
    a control. Every one of these flags is re-derived server-side by the
    route's own dependency before anything is written, so a client that lies to
    itself about them gets a 403, not an effect.
    """
    authenticated:            bool
    is_commissioner:          bool
    commissioner_league_ids:  list[int]
    has_team:                 bool

    # ── Acting context (S8-P4B) ──────────────────────────────────────────────
    #
    # THE LEAGUE THE SESSION ACTS IN, DERIVED SERVER-SIDE. Added because the
    # browser had no authoritative way to answer "which league am I in?" — it
    # knew only `has_team` — and the first binding attempt papered over that
    # with a hard-coded League 1. P2's rule is that the real league being acted
    # upon must be identified authoritatively, and that applies to reads as
    # much as to writes: a client-supplied league is not authority, and an
    # inferred one is a guess wearing authority's clothes.
    #
    # Resolved from the user's own team row, so it cannot be influenced by the
    # caller. `null` is a real answer — an account with no team has no acting
    # league — and the loader treats it as "no context", not as League 1.
    acting_team_id:           Optional[int]
    acting_league_id:         Optional[int]
    acting_team_name:         Optional[str]
    acting_league_name:       Optional[str]

    #: True when the account's acting context cannot be resolved to exactly one
    #: league. MVP has no multi-league GM product, so this is reported rather
    #: than guessed at — a surface that picked one would be showing somebody
    #: else's money.
    acting_context_ambiguous: bool


class IdentityOut(UserOut):
    """/auth/me — the authoritative browser identity read.

    Subclasses UserOut rather than replacing it, so every field the Sprint 7
    contract exposed is still present and the addition breaks no caller.
    """
    capabilities: CapabilitiesOut


def _identity_out(u: User, db: Session) -> IdentityOut:
    league_ids = [
        row.league_id
        for row in db.query(LeagueCommissioner)
                     .filter(LeagueCommissioner.user_id == u.id)
                     .order_by(LeagueCommissioner.league_id)
                     .all()
    ]
    # The acting team is the user's own team row; the acting league is that
    # team's league. One hop, no inference, and nothing the caller can supply.
    team = (db.query(Team).filter(Team.id == u.team_id).first()
            if u.team_id is not None else None)
    acting_league_id = team.league_id if team is not None else None

    league_name = None
    if acting_league_id is not None:
        league_row = (db.query(League)
                      .filter(League.id == acting_league_id).first())
        league_name = league_row.name if league_row is not None else None

    # A commissioner with no team still has an unambiguous context when they
    # commission exactly one league. Ambiguity is: no team AND not exactly one
    # commissioned league — which no MVP account should have, and which is
    # reported rather than resolved by picking.
    if acting_league_id is None and len(league_ids) == 1:
        acting_league_id = league_ids[0]
        league_row = (db.query(League)
                      .filter(League.id == acting_league_id).first())
        league_name = league_row.name if league_row is not None else None

    ambiguous = acting_league_id is None and len(league_ids) != 1

    return IdentityOut(
        **_user_out(u).model_dump(),
        capabilities=CapabilitiesOut(
            authenticated            = True,
            is_commissioner          = u.role == "commissioner",
            commissioner_league_ids  = league_ids,
            has_team                 = u.team_id is not None,
            acting_team_id           = team.id if team is not None else None,
            acting_league_id         = acting_league_id,
            acting_team_name         = team.team_name if team is not None else None,
            acting_league_name       = league_name,
            acting_context_ambiguous = ambiguous,
        ),
    )


@app.post("/auth/session", response_model=IdentityOut)
def auth_session_create(
    req:      SessionLoginRequest,
    response: Response,
    db:       Session = Depends(get_db),
):
    """Browser login. The token goes in a cookie and NOWHERE else.

    Deliberately NOT returning the JWT. /auth/login returns one because an API
    client has to hold it; a browser must not, and the surest way to keep a
    token out of script-readable storage is to never hand it to script. The
    response body is identity only.
    """
    user = authenticate_user(req.email, req.password, db)

    csrf  = new_csrf_token()
    token = create_access_token(user, csrf=csrf)
    issue_browser_session(response, token, csrf)

    return _identity_out(user, db)


@app.delete("/auth/session", status_code=204)
def auth_session_delete(_current: User = Depends(get_current_gm)) -> Response:
    """Browser logout — expire both cookies.

    Authentication is required so that logout is an action the session takes on
    itself. It is also an unsafe method presenting the session cookie, so the
    CSRF gate applies: a cross-site page cannot log a GM out to bait them into
    re-entering credentials somewhere else.

    Note what this does NOT claim. The JWT stays valid until it expires; there
    is no server-side revocation list, so a token captured before logout is not
    killed by it. Clearing the cookie ends the BROWSER's possession of the
    credential, which is what a logout control means to a GM sharing a device.
    Real revocation needs a token store and is not P1 scope.
    """
    response = Response(status_code=204)
    clear_browser_session(response)
    return response


@app.get("/auth/me", response_model=IdentityOut)
def auth_me(
    current_user: User = Depends(get_current_gm),
    db:           Session = Depends(get_db),
):
    """The authoritative identity and capability read for the browser app.

    Answers for whichever credential was presented, so an API client sees the
    same identity the browser does.
    """
    return _identity_out(current_user, db)


@app.post("/auth/promote", response_model=UserOut)
def auth_promote(
    req:  PromoteRequest,
    db:   Session = Depends(get_db),
    _comm: User = Depends(require_commissioner),
):
    """Change a user's PLATFORM role.

    DELIBERATELY STILL GLOBAL — the one route S8-P2 examined and left alone.
    `User.role` is a property of the account, not of a membership: it is not
    scoped to a league, no league_id can be derived from the request, and there
    is no league whose commissioner would be the right authority. Narrowing it
    to `require_league_commissioner` would mean inventing a league context that
    the operation does not have.

    Note what this route can and cannot do. It sets the global role string —
    which, after P2, no longer grants authority over any league's governed
    operations. League authority is a LeagueCommissioner row, granted through
    POST /league/{league_id}/commissioners, which IS league-scoped. So this
    route can no longer be used to reach into a league.
    """
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
        wallet_balance=(balance_of(f"wallet:{team_id}") / 100) if wallet else 0.0,  # FR-7.12: ledger, not stale column
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
def place_bet(
    req:          BetRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_season_allocation_gate),
):
    assert_own_wallet(req.wallet_id, current_user, db)

    matchup = db.query(Matchup).filter(Matchup.id == req.matchup_id).first()
    if not matchup:
        raise HTTPException(status_code=404, detail="Matchup not found")

    wallet = db.query(Wallet).filter(Wallet.id == req.wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    # FR-7.12: funds check reads the ledger (source of truth) in this same
    # request transaction, compared in integer cents — not the stale column.
    _bal_cents = _balance_of_in_session(db, f"wallet:{wallet.team_id}")
    if _bal_cents < _to_cents(req.amount):
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance: ${_bal_cents / 100:.2f} < ${req.amount:.2f}",
        )

    if req.picked_team_id not in (matchup.home_team_id, matchup.away_team_id):
        raise HTTPException(
            status_code=400,
            detail="picked_team_id must be one of the two teams in this matchup",
        )

    # Odds are computed server-side by place_straight_bet() (Monte Carlo, same
    # engine every other /bets/* route uses) — req.odds is never read here.
    # Stake deduction, Bet-row creation (status="pending"), and the debit
    # Transaction all happen inside place_straight_bet()/_place_bet(). This
    # route never reads matchup.winner_team_id and never pays out — settle_week()
    # is the only path that resolves a bet.
    try:
        result = place_straight_bet(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.amount, matchup.week, db,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except BetValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    bet    = db.query(Bet).filter(Bet.id == result.bet_id).first()
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
        balance       = balance_of(f"wallet:{team_id}") / 100,  # FR-7.12: ledger, not stale column
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
    current_user: User    = Depends(get_season_allocation_gate),
):
    assert_own_wallet(req.wallet_id, current_user, db)
    try:
        result = place_straight_bet(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.amount, req.week, db,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except BetValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _bet_out(result)


@app.post("/bets/spread", response_model=BetEngineOut, status_code=201)
def bet_spread(
    req:          SpreadBetRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_season_allocation_gate),
):
    assert_own_wallet(req.wallet_id, current_user, db)
    try:
        result = place_spread_bet(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.spread, req.amount, req.week, db,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except BetValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _bet_out(result)


@app.post("/bets/over_under", response_model=BetEngineOut, status_code=201)
def bet_over_under(
    req:          OverUnderRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_season_allocation_gate),
):
    assert_own_wallet(req.wallet_id, current_user, db)
    try:
        result = place_over_under(
            req.matchup_id, req.wallet_id, req.total_line,
            req.pick, req.amount, req.week, db,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except BetValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _bet_out(result)


@app.post("/bets/prop", response_model=BetEngineOut, status_code=201)
def bet_prop(
    req:          PropBetRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_season_allocation_gate),
):
    assert_own_wallet(req.wallet_id, current_user, db)
    try:
        result = place_prop_bet(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.amount, req.week, db,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except BetValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
    already_settled:  bool = False


@app.post("/league/{league_id}/settle/{week}", response_model=SettlementOut)
def settle(
    league_id: int,
    week:      int,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """Settle a week for one named league.

    VERB CORRECTED IN S8-P2. This was a GET that called `settle_week()` —
    settlement posts bet outcomes and moves wallet balances, so the method
    misdescribed the route to every intermediary that trusts it: caches,
    prefetchers, link scanners, and crucially the browser's own cross-site
    rules. P1 had to carry an explicit exception list so its CSRF gate would
    cover a mutation spelled as a read; that list is now empty and the
    mechanism is gone, because the contract itself is right.

    LEAGUE IDENTIFIED IN S8-P2R, and this is the more important half. The
    route previously hard-coded `league_id = 1` and authorized against that
    constant. Every caller therefore got the same answer to "which league may
    you settle?" regardless of which league they actually held authority for —
    so the P2 rule that authorization must be checked against the real league
    being acted on was satisfied only by the accident of there being one
    league. FantasyStakes is not a permanently single-league product, and a
    route that settles league state must say which league it means.

    THE LEAGUE IS NOW A PATH PARAMETER, which lets this use the dependency
    rather than the imperative check. That is deliberately the stronger of the
    two: `require_league_commissioner` binds `league_id` from the path and
    refuses BEFORE any route work, so an unauthorized caller cannot use this
    route to learn whether a league exists, let alone touch its slate.

    ONE league_id FLOWS THROUGH EVERYTHING. The value authorized above is the
    same value passed to the freshness precondition and to `settle_week()`.
    There is no second source and no default anywhere on the path, so the
    league that was authorized is necessarily the league that gets settled.

    NO COMPATIBILITY ROUTE, in either direction. The old GET and the unscoped
    POST are both gone: the GET because a mutation must not be spelled as a
    read, the unscoped POST because retaining it would leave a live settlement
    path whose league authority is ambiguous — the exact defect this corrects.
    Nothing in the repository called either one.

    RESPONSE CONTRACT UNCHANGED — same `SettlementOut`, same fields, same
    values, same idempotent `already_settled` behaviour.
    """
    if not 1 <= week <= 17:
        raise HTTPException(status_code=400, detail="week must be 1–17")

    is_fresh, reason, _ = _assert_slate_fresh(league_id, week, db, check_refreshed=True)
    if not is_fresh:
        raise HTTPException(status_code=400, detail=reason)

    # WP2B-D — THE SAME MAPPING, BECAUSE IT IS THE SAME LEAK.
    #
    # The freshness gate above reads `refreshed_at` and NOTHING ELSE; the
    # economic finality gate inside `settle_week` reads `finalized_at` and
    # nothing else. Those are two different facts on purpose (see
    # betting/finality_gate.py), and a week the provider has refreshed but not
    # declared over passes the first and is refused by the second. So this
    # route leaked the identical governed refusal as an unhandled 500 for the
    # identical reason. Mapping only the Pool route would have left one
    # condition with two client-visible shapes.
    #
    # The engine refuses BEFORE writing its WeekSettlement claim row (S6 §8),
    # so the rollback below discards nothing and the week stays cleanly
    # retryable once results are final.
    try:
        report = settle_week(week, db, league_id=league_id)
    except ResultsNotReadyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "reason_code": exc.reason,
            "message": str(exc),
            "league_id": exc.league_id,
            "week": exc.week,
            "unfinalized_matchup_ids": list(exc.unfinalized_matchup_ids),
        })
    return SettlementOut(
        week             = report.week,
        total_bets       = report.total_bets,
        bets_won         = report.bets_won,
        bets_lost        = report.bets_lost,
        total_staked     = report.total_staked,
        total_payout     = report.total_payout,
        house_edge       = report.house_edge,
        already_settled  = report.already_settled,
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
        owner=s.owner, balance=s.balance, max_single_bet=s.max_single_bet,  # FR-7.12: stays on the stale column until FR-7.28 posts wm_deposit() to the ledger; converting now would race/omit the just-made deposit (spec Rev4 §3, MS-7.12-D-3)
        open_bets=s.open_bets, pending_exposure=s.pending_exposure,
        total_deposited=s.total_deposited, total_withdrawn=s.total_withdrawn,
        total_wagered=s.total_wagered, total_payout=s.total_payout,
        net_pnl=s.net_pnl,
    )

@app.post("/wallet/deposit", status_code=410, deprecated=True)
def wallet_deposit():
    raise HTTPException(
        status_code=410,
        detail=(
            "Direct wallet deposits are retired. BAB wallet credits "
            "require a confirmed top-up event."
        ),
    )

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
        balance     = balance_of(f"wallet:{team_id}") / 100,  # FR-7.12: ledger, not stale column
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
    # S8-P4C-2: THE GOVERNED MODE, using the proposal lifecycle's own enum
    # values rather than a parallel vocabulary. Defaulted to Locked so every
    # caller written before Dynamic was exposed keeps its exact behaviour —
    # P4C-1R certified that those requests produce Locked challenges, and a
    # required field would have changed that silently.
    challenge_mode:     str   = Field(default="locked",
                                      description="locked | dynamic")
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


class CounterRequest(BaseModel):
    challenge_id:     int
    countered_amount: float
    trash_talk:       Optional[str] = None


# ── Funded proposal lifecycle (S8-P4C-1) ─────────────────────────────────────
#
# THE CUTOVER. These four routes were the last live entry into
# `beefs/beef_engine.py`'s legacy challenge path — the one that posted no escrow
# at issue and held a SOFT RESERVATION instead. They now enter the approved
# Spec-2 lifecycle: `beefs/proposal_lifecycle.py` owns negotiation STATE and
# `economy/challenge_funding.py` owns the money, exactly as Spec 1 §1 and
# Spec 2 §8 assign them.
#
# WHY NOW, AND ON WHAT AUTHORITY. Spec 1 Rev 3 §1 fenced the new model — "New
# model issuance/response flows stay unreachable ... UNTIL SPEC 2 SUPPLIES
# ESCROW." Spec 2 supplies it, and has since P1-L4. The fence was conditional
# and its condition is met, so leaving the live path on the superseded model was
# no longer a deferral; it was a divergence.
#
# THIN ADAPTATION, NOT NEW BUSINESS LOGIC. Every route below resolves authority,
# converts the request into the lifecycle's own vocabulary, calls exactly one
# governed entry point, and shapes its result. No capacity rule, no pricing, no
# state transition and no posting is written here — all of that stays in the two
# governing modules, which are the only places it can be reviewed as a whole.
#
# ONE PATH, NOT A HYBRID. There is no legacy fallback and no feature flag. A
# mutation either goes through the funded lifecycle or it does not happen.

class FundedChallengeOut(BaseModel):
    """The result of one funded lifecycle call.

    A DIFFERENT SHAPE FROM THE LEGACY `ChallengeOut`, deliberately. The funded
    lifecycle produces facts the legacy path had no concept of — how much real
    escrow is now committed, which negotiation state the challenge is in, and
    whether this call was a replay of an event already committed. Flattening
    those back into the old shape would have hidden exactly the information the
    cutover exists to produce.
    """
    challenge_id:    int
    event_id:        str
    response_status: str
    result_code:     str
    escrow_cents:    int
    replayed:        bool
    detail:          str = ""
    anchor_bet_id:   Optional[int] = None
    derived_bet_id:  Optional[int] = None
    # DYNAMIC ONLY, and absent on every Locked response rather than zeroed. A
    # Locked wager has no ceiling because nothing about it can move; reporting
    # `0` would read as "the Derived side may not move at all", which is a
    # different and false claim.
    issuer_ceiling_cents:   Optional[int] = None
    opponent_ceiling_cents: Optional[int] = None
    model_version_id:       Optional[str] = None


def _funded_out(result) -> FundedChallengeOut:
    return FundedChallengeOut(
        challenge_id=result.challenge_id,
        event_id=str(result.event_id),
        response_status=result.response_status,
        result_code=result.result_code,
        escrow_cents=result.escrow_cents,
        replayed=result.replayed,
        detail=result.detail,
        anchor_bet_id=result.anchor_bet_id,
        derived_bet_id=result.derived_bet_id,
    )


def _handshake_out(db: Session, handshake) -> "FundedChallengeOut":
    """Shape a Dynamic Handshake into the shared response.

    THE CEILINGS ARE THE POINT OF THE RESPONSE. A Dynamic acceptance commits the
    Anchor and establishes how far the Derived side may move at Final Lock; the
    caller needs those bounds to render honest terms, and they are the only
    numbers that distinguish this from a Locked accept.

    `escrow_cents` reports the Anchor the Handshake fixed. Bet ids stay None
    because no Bet exists yet — Final Lock creates them once the Derived price
    is known, and reporting a placeholder would imply a wager that is not there.
    """
    challenge = db.query(BeefChallenge).filter(
        BeefChallenge.id == handshake.challenge_id).first()
    return FundedChallengeOut(
        challenge_id=handshake.challenge_id,
        event_id=str(handshake.event_id),
        response_status=(challenge.response_status if challenge else "accepted"),
        result_code="ok",
        escrow_cents=handshake.anchor_cents,
        replayed=handshake.replayed,
        detail=handshake.detail or "dynamic handshake complete",
        issuer_ceiling_cents=handshake.issuer_ceiling_cents,
        opponent_ceiling_cents=handshake.opponent_ceiling_cents,
        model_version_id=handshake.model_version_id,
    )


def _funding_refusal(e: Exception) -> HTTPException:
    """Map a governed funding refusal to a status code.

    NARROW BY DESIGN. Capacity and reconciliation failures are 409 — the request
    is well-formed and authorized, and the league's state is what refuses it.
    Everything else that is a `ValueError` subclass is a 400. Nothing broader is
    caught: `LedgerImbalanceError` and friends must surface as 500s, because a
    conservation failure is the loudest event this system can produce and a tidy
    4xx would stop it paging.
    """
    from economy.challenge_funding import (
        AcceptanceCapacityError, EscrowReconciliationError,
        InsufficientFundingCapacityError, MissingProposalError,
    )
    if isinstance(e, (InsufficientFundingCapacityError, AcceptanceCapacityError,
                      EscrowReconciliationError)):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, MissingProposalError):
        return HTTPException(status_code=404, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


def _team_league_id(db: Session, team_id: int) -> int:
    """The league a team belongs to.

    Resolved server-side from the team row. The league is never taken from the
    request — P2's rule that the real league being acted upon must be identified
    authoritatively applies to a wager exactly as it does to a settlement.
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if team is None:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found")
    return team.league_id


@app.post("/beef/challenge", response_model=FundedChallengeOut, status_code=201)
def beef_challenge(
    req:          ChallengeRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_season_allocation_gate),
):
    """Issue a funded challenge — real Anchor escrow posts immediately.

    THE STAKE LEAVES THE WALLET NOW. Under the legacy path a challenge held a
    soft reservation and the money stayed put until acceptance; under Spec 2 the
    issuer's Anchor is posted to `escrow:challenge:{id}` in the same transaction
    that creates the challenge. That is what makes an open challenge visible to
    `in_play_cents` and to `team_open_challenge_escrow_cents` — Held stops being
    a latent property and becomes a real one.
    """
    import uuid as _uuid
    from beefs import proposal_lifecycle as spec1
    from beefs.beef_engine import _compute_odds
    from economy.challenge_funding import ChallengeFundingError, issue_funded_challenge

    assert_wagering_team_owner(req.challenger_team_id, current_user)

    league_id = _team_league_id(db, req.challenger_team_id)
    if _team_league_id(db, req.challenged_team_id) != league_id:
        # Cross-league wagering is not a thing the protocol defines, and the
        # funding path would happily post escrow for it. Refused here, before
        # any money moves.
        raise HTTPException(status_code=400, detail={
            "reason_code": "cross_league_challenge",
            "message": "Both teams must belong to the same league.",
        })

    challenger = db.query(Team).filter(Team.id == req.challenger_team_id).one()
    challenged = db.query(Team).filter(Team.id == req.challenged_team_id).one()

    # THE LOCKED QUOTE, from the pricing model that already governs locked mode.
    # `_compute_odds` is the Monte Carlo pricing the legacy route used, and it is
    # PRICING, not the legacy money path — what P4C-1 retires is the soft
    # reservation and the unfunded issue, not the odds model. Reimplementing it
    # here to avoid the import would be the "new business logic" §2 forbids, and
    # would silently reprice every locked wager in the product.
    try:
        (anchor_dec, anchor_ml, derived_dec, derived_ml,
         anchor_p, derived_p) = _compute_odds(
            req.bet_type, challenger, challenged, req.week, db,
            req.line, req.side, req.player_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if req.challenge_mode not in spec1.VALID_MODES:
        raise HTTPException(status_code=400, detail={
            "reason_code": "unknown_challenge_mode",
            "message": f"challenge_mode must be one of {list(spec1.VALID_MODES)}.",
        })

    stake_cents = _to_cents(req.amount)
    dynamic = req.challenge_mode == spec1.MODE_DYNAMIC

    # THE DERIVED STAKE IS QUOTED ONLY IN LOCKED, at issue exactly as at
    # counter. In Dynamic the opponent's side is priced at Final Lock, so a
    # quote here would assert a number the protocol never fixes — and it would
    # be the number the card showed the opponent while they decided.
    terms = spec1.ProposalTerms(
        line=req.line,
        side=req.side,
        player_id=req.player_id,
        anchor_stake_cents=stake_cents,
        # FROZEN WIN PROBABILITIES. A Dynamic challenge cannot be handshaken
        # without them — the opponent's Derived ceiling is derived from the
        # proposal's frozen probabilities, and the lifecycle refuses a proposal
        # that carries none. They are frozen for Locked too: the same simulation
        # produced them, and recording what a quote was based on costs nothing
        # and makes the two modes' provenance identical.
        anchor_win_probability=anchor_p,
        derived_win_probability=derived_p,
        # BOTH SIDES STAKE THE SAME AMOUNT in locked mode — the single `amount`
        # on the request is each side's stake, exactly as the legacy path placed
        # both sides at `effective_amount`. This is a translation of the existing
        # product rule into the proposal's vocabulary, not a new one.
        quoted_derived_stake_cents=None if dynamic else stake_cents,
        quoted_funded_pot_cents=None if dynamic else stake_cents * 2,
        quoted_anchor_payout_cents=round(stake_cents * anchor_dec),
        quoted_derived_payout_cents=(None if dynamic
                                     else round(stake_cents * derived_dec)),
        anchor_odds=anchor_dec,
        derived_odds=derived_dec,
        anchor_moneyline=anchor_ml,
        derived_moneyline=derived_ml,
        pricing_model_id=req.challenge_mode,
    )

    try:
        result = issue_funded_challenge(
            event_id=_uuid.uuid4(),
            league_id=league_id,
            week=req.week,
            challenger_team_id=req.challenger_team_id,
            challenged_team_id=req.challenged_team_id,
            wager_type=req.bet_type,
            terms=terms,
            db=db,
            # THE MODE GOES STRAIGHT THROUGH. `issue_funded_challenge` already
            # forwards it to `spec1.issue_proposal_challenge`, which is what
            # makes Dynamic issuance a routing question rather than a new
            # capability — the lifecycle has always been able to create one.
            challenge_mode=req.challenge_mode,
        )
    except ChallengeFundingError as e:
        raise _funding_refusal(e)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _funded_out(result)


@app.post("/beef/respond", response_model=FundedChallengeOut, status_code=200)
def beef_respond(
    req:          RespondRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """Accept or decline a funded challenge.

    WHO MAY RESPOND depends on the negotiation state, and the state is read from
    `response_status` — the Spec-1 field — rather than the legacy `status`
    column. On an offered proposal the recipient responds; on a countered one the
    original issuer does, because a counter hands the decision back.
    """
    import uuid as _uuid
    from beefs.proposal_lifecycle import (
        COUNTERED, MODE_DYNAMIC as spec1_MODE_DYNAMIC, OPEN_STATES,
    )
    from economy.challenge_funding import (
        ChallengeFundingError, accept_funded_challenge, decline_funded_challenge,
    )
    from economy.dynamic_challenge import (
        DynamicChallengeError, handshake_dynamic_challenge,
    )

    challenge = db.query(BeefChallenge).filter(
        BeefChallenge.id == req.challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    parties = (challenge.challenger_team_id, challenge.challenged_team_id)
    if challenge.response_status in OPEN_STATES:
        # While the negotiation is open exactly one side holds the decision, and
        # a counter hands it back to the issuer.
        responder = (challenge.challenger_team_id
                     if challenge.response_status == COUNTERED
                     else challenge.challenged_team_id)
        assert_wagering_team_owner(responder, current_user)
    else:
        # ALREADY CLOSED. Asking "whose turn is it" of a settled negotiation has
        # no answer, and deriving one anyway produced a 403 that blamed the
        # caller's identity for what is really a terminal-state condition. Both
        # teams are parties to their own challenge, so authorize on THAT and let
        # the protocol give the honest answer — "already accepted" — which is
        # also what makes a retried request idempotent rather than forbidden.
        # PARTICIPANT IDENTITY, STILL REQUIRED — and commissioner status is not
        # a way of being a participant. S8-P4C-1R: this branch briefly carried a
        # commissioner exemption, which would have let a commissioner drive
        # another GM's terminal-state retries; the idempotency it protects is
        # the participating GM's, not an administrator's.
        if current_user.team_id not in parties:
            raise HTTPException(
                status_code=403,
                detail="Access denied: this challenge is not yours")
        responder = current_user.team_id

    try:
        if not req.accept:
            # DECLINE IS MODE-BLIND. Both modes escrow only the issuer's Anchor
            # while a proposal is open, so the reverse-leg refund is the same act
            # either way and the funded decline owns it for both.
            result = decline_funded_challenge(
                event_id=_uuid.uuid4(), challenge_id=req.challenge_id,
                actor_team_id=responder, db=db)
        elif challenge.challenge_mode == spec1_MODE_DYNAMIC:
            # DYNAMIC ACCEPTANCE IS THE HANDSHAKE, and it is a different act from
            # Locked acceptance rather than a variant of it — which is why the
            # lifecycle keeps them in separate functions and why this dispatches
            # rather than passing a flag. `accept_funded_challenge` refuses a
            # Dynamic challenge outright, so routing it there would surface a
            # mode error instead of doing the governed thing.
            #
            # WHAT THE HANDSHAKE DOES NOT DO is create the Bet rows. It fixes the
            # Anchor and computes both ceilings; the Derived side is priced at
            # Final Lock, which is the whole point of the mode. So the response
            # carries no bet ids, and that absence is accurate rather than a gap.
            handshake = handshake_dynamic_challenge(
                event_id=_uuid.uuid4(), challenge_id=req.challenge_id,
                actor_team_id=responder, db=db)
            return _handshake_out(db, handshake)
        else:
            result = accept_funded_challenge(
                event_id=_uuid.uuid4(), challenge_id=req.challenge_id,
                actor_team_id=responder, db=db)
    except DynamicChallengeError as e:
        raise _funding_refusal(e)
    except ChallengeFundingError as e:
        raise _funding_refusal(e)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _funded_out(result)


@app.post("/beef/counter", response_model=FundedChallengeOut, status_code=200)
def beef_counter(
    req:          CounterRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """Counter a funded challenge — Refresh & Relock.

    NO MONEY MOVES ON A COUNTER (Spec 2 §10). A counter freezes a NEW proposal
    version and validates that both sides could fund it; it reserves nothing and
    posts nothing. The issuer's original Anchor stays exactly where it is, which
    is why only the DEFICIENCY is validated against them rather than the whole
    new stake.
    """
    import uuid as _uuid
    from beefs import proposal_lifecycle as spec1
    from beefs.beef_engine import _compute_odds
    from economy.challenge_funding import ChallengeFundingError, counter_funded_challenge

    challenge = db.query(BeefChallenge).filter(
        BeefChallenge.id == req.challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    assert_wagering_team_owner(challenge.challenged_team_id, current_user)

    challenger = db.query(Team).filter(
        Team.id == challenge.challenger_team_id).one()
    challenged = db.query(Team).filter(
        Team.id == challenge.challenged_team_id).one()

    # RELOCK MEANS REPRICE. A counter freezes a new proposal version, and a
    # version that carried the FIRST version's odds at a different stake would
    # quote a payout the pricing model never produced. The subject of the wager
    # is unchanged, so the non-price terms come from the challenge itself — a
    # counter negotiates the stake, not the bet.
    try:
        (anchor_dec, anchor_ml, derived_dec, derived_ml,
         anchor_p, derived_p) = _compute_odds(
            challenge.wager_type or challenge.bet_type, challenger, challenged,
            challenge.week, db, challenge.line, challenge.side,
            challenge.player_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    stake_cents = _to_cents(req.countered_amount)
    dynamic = challenge.challenge_mode == spec1.MODE_DYNAMIC

    # THE DERIVED STAKE IS QUOTED ONLY IN LOCKED. A counter cannot change the
    # mode (Spec 1 §5), so a countered Dynamic challenge is still Dynamic — and
    # in Dynamic the Derived side is priced at Final Lock, not now. Quoting one
    # here would assert a price the protocol never fixes, and would make the
    # funded counter validate the countering team against a stake that will not
    # be the stake. The Handshake reads the frozen PROBABILITIES and the Anchor;
    # it never reads a quoted Derived stake, so leaving it unquoted is following
    # the protocol rather than omitting something.
    #
    # The opponent's real exposure in Dynamic is bounded by the ceiling the
    # Handshake computes, which is where that check belongs.
    terms = spec1.ProposalTerms(
        line=challenge.line,
        side=challenge.side,
        player_id=challenge.player_id,
        anchor_stake_cents=stake_cents,
        quoted_derived_stake_cents=None if dynamic else stake_cents,
        quoted_funded_pot_cents=None if dynamic else stake_cents * 2,
        quoted_anchor_payout_cents=round(stake_cents * anchor_dec),
        quoted_derived_payout_cents=(None if dynamic
                                     else round(stake_cents * derived_dec)),
        # Re-frozen on the new version, because the Handshake derives the
        # opponent's ceiling from THIS version's probabilities and a counter
        # creates a new one.
        anchor_win_probability=anchor_p,
        derived_win_probability=derived_p,
        anchor_odds=anchor_dec,
        derived_odds=derived_dec,
        anchor_moneyline=anchor_ml,
        derived_moneyline=derived_ml,
        pricing_model_id=challenge.challenge_mode,
    )

    try:
        result = counter_funded_challenge(
            event_id=_uuid.uuid4(),
            challenge_id=req.challenge_id,
            actor_team_id=challenge.challenged_team_id,
            terms=terms,
            db=db,
        )
    except ChallengeFundingError as e:
        raise _funding_refusal(e)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _funded_out(result)


class ProposalOut(BaseModel):
    """One challenge in the Spec-1 negotiation vocabulary."""
    challenge_id:       int
    direction:          str     # "sent" | "received"
    response_status:    str     # offered | countered | accepted | declined | …
    challenge_mode:     str
    challenger_team_id: int
    challenged_team_id: int
    week:               int
    wager_type:         Optional[str]
    anchor_stake_cents: Optional[int]
    escrow_cents:       int
    created_at:         Optional[str]


@app.get("/beef/pending/{team_id}", response_model=list[ProposalOut])
def beef_pending(
    team_id:      int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """Open proposals involving this team, classified by `response_status`.

    READ REPOINTED WITH THE WRITES. The legacy reader classified from the
    `status` column, which the new model writes only for NOT NULL compatibility
    — a funded proposal would have been either invisible or mislabelled by it.
    `response_status` is the Spec-1 negotiation state and is what the four
    Response Card states are derived from.

    OPEN ONLY. Terminal states are history and belong to a different surface;
    this is the inbox.
    """
    from beefs.proposal_lifecycle import OPEN_STATES
    from economy.challenge_funding import challenge_escrow_balance
    from db.schema import BeefProposal

    # A GM'S OWN INBOX. Strict, because no governing read authority grants a
    # commissioner another GM's personal negotiation queue — and the queue
    # discloses open positions and stakes that are the GM's to hold. League
    # oversight reads the League Reconciliation surface, which is authorized on
    # its own terms rather than by borrowing this one.
    assert_wagering_team_owner(team_id, current_user)
    if db.query(Team).filter(Team.id == team_id).first() is None:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found")

    rows = (db.query(BeefChallenge)
            .filter(BeefChallenge.response_status.in_(OPEN_STATES),
                    or_(BeefChallenge.challenger_team_id == team_id,
                        BeefChallenge.challenged_team_id == team_id))
            .order_by(BeefChallenge.id)
            .all())

    out: list[ProposalOut] = []
    for c in rows:
        # THE ACTIVE VERSION, NOT THE LATEST ROW. Proposals are immutable and
        # versioned, so "latest" and "in force" are different questions — a
        # counter that failed validation can leave a higher version_number
        # behind. `active_proposal_id` is the pointer the lifecycle maintains,
        # and it is the one the negotiation is actually about.
        proposal = (db.query(BeefProposal)
                    .filter(BeefProposal.id == c.active_proposal_id).first()
                    if c.active_proposal_id else None)
        out.append(ProposalOut(
            challenge_id=c.id,
            direction="sent" if c.challenger_team_id == team_id else "received",
            response_status=c.response_status,
            challenge_mode=c.challenge_mode,
            challenger_team_id=c.challenger_team_id,
            challenged_team_id=c.challenged_team_id,
            week=c.week,
            wager_type=c.wager_type,
            anchor_stake_cents=proposal.anchor_stake_cents if proposal else None,
            escrow_cents=challenge_escrow_balance(db, c.id),
            created_at=c.created_at.isoformat() if c.created_at else None,
        ))
    return out


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


class BuyinEnforcementRequest(BaseModel):
    league_id: int
    active:    bool


class BuyinEnforcementOut(BaseModel):
    league_id: int
    active:    bool


def _cents_to_dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


# ── Payment endpoints ─────────────────────────────────────────────────────────


@app.post("/payments/buyin-enforcement", response_model=BuyinEnforcementOut, status_code=200)
def payments_set_buyin_enforcement(
    req:   BuyinEnforcementRequest,
    db:    Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
):
    """Commissioner turns season-allocation enforcement on/off for a league.

    The route path and the League.buyin_enforcement_active column keep their
    historical names; the flag governs the season-allocation gate and has no
    Stripe or payment meaning. Renaming both is deferred to a controlled
    post-MVP migration.
    """
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

    try:
        active = set_allocation_enforcement_active(
            req.league_id, req.active, db, performer_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return BuyinEnforcementOut(league_id=req.league_id, active=active)


@app.get("/payments/buyin-enforcement/{league_id}", response_model=BuyinEnforcementOut)
def payments_get_buyin_enforcement(league_id: int, db: Session = Depends(get_db)):
    """Read current buy-in enforcement status for a league (open endpoint)."""
    active = get_allocation_enforcement_active(league_id, db)
    return BuyinEnforcementOut(league_id=league_id, active=active)


# ── Season allocation (B2) ────────────────────────────────────────────────────

class SeasonAllocationOut(BaseModel):
    league_id:         int
    season:            int
    team_ids:          list[int]
    buyin_cents:       int
    min_reserve_cents:      int
    reserve_cents:     int
    total_buyin_cents: int
    created:           bool


class CommissionerGrantRequest(BaseModel):
    """Grant request. `user_id` is the ONLY accepted field.

    extra="forbid" (Pydantic 2) makes any additional key a 422 validation
    error rather than a silently dropped one. Provenance fields — source,
    assigned_by_user_id, league_id, created_at — are server-set, and a caller
    that tries to supply them is told so instead of being quietly ignored.
    """
    model_config = ConfigDict(extra="forbid")

    user_id: int


class CommissionerGrantOut(BaseModel):
    authority_row_id:    int
    league_id:           int
    user_id:             int
    source:              str
    assigned_by_user_id: Optional[int]
    created_at:          str


@app.post("/league/{league_id}/commissioners", response_model=CommissionerGrantOut,
          status_code=201)
def league_grant_commissioner(
    league_id: int,
    req:       CommissionerGrantRequest,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """
    An existing commissioner of THIS league grants another user commissioner
    authority for the same league.

    AUTHORIZATION. require_league_commissioner demands a LeagueCommissioner row
    for (league_id, caller). The global User.role is not consulted: a caller
    whose role is "gm" but who holds an authority row succeeds, and a global
    commissioner with no row is refused 403. Team ownership grants nothing. A
    commissioner of another league cannot grant here, because league_id comes
    from the path and the authority check is against that same path league.

    PROVENANCE IS SERVER-SET AND UNSPOOFABLE. The request body carries ONLY the
    target user_id. league_id comes from the path, source is fixed to
    "local_grant", and assigned_by_user_id is the authenticated caller.

    A client that submits source, assigned_by_user_id, created_at or a
    different league_id is REJECTED WITH 422 by model validation —
    CommissionerGrantRequest sets extra="forbid". An earlier version of this
    docstring claimed FastAPI rejected unknown keys while the model in fact
    ignored them silently; that mismatch was R-G2 and the model now matches the
    documented contract.

    DUPLICATE CONTRACT: 409, never overwrite. If the target already holds
    authority for this league the request is refused with 409 and the existing
    row is left exactly as it was. Provenance exists only at grant time; a
    second call must not rewrite who granted it, when, or under what source.
    Idempotent-success was the alternative and was rejected for that reason —
    it would have to either return stale provenance as if fresh, or rewrite it.

    TARGET VALIDATION. The target must exist and be active. It need NOT own a
    team, need NOT hold the global commissioner role, and MAY already administer
    other leagues.

    SERIALIZATION (B6 §6.4, item 15). The League row is the serialization point
    for every authority writer. This handler takes it FOR UPDATE as the first
    database statement of its body, before the target lookup, before the
    duplicate pre-check and before the insert, so concurrent authority writes on
    one league order themselves there. Plain FOR UPDATE is required — the same
    mode genesis (scripts/bootstrap_league_commissioner.py) and close_season()
    take — so all three serialize against one another; key_share=True is
    deliberately not passed, an authority writer being no FK-child inserter.

    The authorization dependency's preliminary UNLOCKED read of
    league_commissioners has already happened on this session by the time the
    handler runs. That is permitted and unchanged: it decides authorization
    only, and every read this handler acts on is taken after the lock.

    Each refusal reached after the lock rolls back before raising, so the League
    row is released immediately rather than at request teardown.

    This route performs no money, wallet, ledger, allocation or top-off write.
    """
    # THE SERIALIZATION POINT — see SERIALIZATION above. FIRST database
    # statement of the handler body.
    locked_league = (
        db.query(League)
        .filter(League.id == league_id)
        .with_for_update()
        .first()
    )
    if locked_league is None:
        # Defence in depth, not a routine path: require_league_commissioner has
        # already 403'd any caller without an authority row, and such a row
        # cannot exist for an absent league (FK to leagues.id). Reaching here
        # means the league vanished between that check and this lock. Roll back
        # first so the transaction opened by the lock attempt holds nothing.
        db.rollback()
        raise HTTPException(status_code=404,
                            detail=f"League {league_id} not found")

    target = db.query(User).filter(User.id == req.user_id).first()
    if target is None:
        db.rollback()          # release the League row before refusing
        raise HTTPException(status_code=404, detail=f"User {req.user_id} not found")
    if not target.is_active:
        db.rollback()
        raise HTTPException(status_code=400,
                            detail=f"User {req.user_id} is inactive")

    # Read under the lock. A duplicate pre-check taken before it could be stale
    # by the time the lock was granted — which is exactly the window a
    # concurrent grant of the same pair would use.
    existing = (
        db.query(LeagueCommissioner)
        .filter(LeagueCommissioner.league_id == league_id,
                LeagueCommissioner.user_id == req.user_id)
        .first()
    )
    if existing is not None:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(f"User {req.user_id} is already a commissioner of league "
                    f"{league_id}; existing grant is unchanged"),
        )

    row = LeagueCommissioner(
        league_id           = league_id,
        user_id             = req.user_id,
        source              = "local_grant",
        assigned_by_user_id = _comm.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as e:
        # Roll back FIRST — the session is unusable until we do, and every exit
        # from here (domain 409 or re-raise) must leave a clean transaction.
        db.rollback()

        # RETAINED UNDER THE LOCK. The League lock above makes the duplicate
        # pre-check authoritative for concurrent grants, so this branch should
        # no longer be reachable that way — it is kept because the unique
        # constraint, not the lock, is what actually guarantees one row per
        # pair, and because a write arriving from any future path that does not
        # take the lock must still be refused correctly rather than 500.
        #
        # NARROW CLASSIFICATION (R-G1). Only the named duplicate-pair
        # constraint becomes a 409. Catching every IntegrityError would
        # misreport a foreign-key violation (e.g. a league or user deleted
        # concurrently) or a NOT NULL failure as "already a commissioner",
        # hiding a real defect behind a benign-looking conflict.
        #
        # psycopg2 exposes the violated constraint on the DBAPI error's
        # diagnostics. Verified against PostgreSQL 16: a unique violation
        # reports constraint_name='uq_league_commissioner_league_user'
        # (SQLSTATE 23505) while a foreign-key violation reports its own FK
        # name (23503), so the two are cleanly distinguishable. getattr is used
        # defensively so a driver without .diag re-raises rather than crashing
        # inside the handler.
        constraint = getattr(getattr(e.orig, "diag", None), "constraint_name", None)
        if constraint != "uq_league_commissioner_league_user":
            raise            # not a duplicate pair — surface the real failure

        raise HTTPException(
            status_code=409,
            detail=(f"User {req.user_id} is already a commissioner of league "
                    f"{league_id}; existing grant is unchanged"),
        )
    db.refresh(row)

    return CommissionerGrantOut(
        authority_row_id    = row.id,
        league_id           = row.league_id,
        user_id             = row.user_id,
        source              = row.source,
        assigned_by_user_id = row.assigned_by_user_id,
        created_at          = row.created_at.isoformat(),
    )


@app.post("/league/{league_id}/season-allocation", response_model=SeasonAllocationOut, status_code=200)
def league_activate_season_allocation(
    league_id: int,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """
    A commissioner AUTHORIZED FOR THIS LEAGUE activates its season allocation.

    LEAGUE-SCOPED AUTHORIZATION. This route requires a LeagueCommissioner row
    for (league_id, current_user.id). The global User.role == "commissioner" is
    NOT sufficient: a commissioner of another league, or a global commissioner
    with no authority row here, receives 403. Team ownership grants nothing.

    Response ordering is deliberate: league-scoped authorization runs BEFORE any
    downstream route work, so an unauthorized caller cannot use this route to
    distinguish league existence.

    R-C1 correction: an earlier version of this docstring claimed a 404 was
    reachable after successful authorization for an absent league. That is
    false. Authority is a LeagueCommissioner row whose league_id is a foreign
    key to leagues.id, so no one can hold authority for a league that does not
    exist, and this route establishes no such 404 path.

    This is the ONLY route narrowed in this package; the other commissioner
    routes still use the global require_commissioner and remain open findings.

    Whole-league operation — the per-team rows and their ledger postings are
    written inside activate_season_allocation(), in one transaction. The
    season is NOT accepted from the request; it comes from config.

    Idempotent: re-activating a league whose allocation is already complete
    and matching returns the existing result with created=false and posts
    nothing. An inconsistent league (partial or conflicting) is refused with
    409 and nothing is mutated.

    TRANSACTION OWNERSHIP: activate_season_allocation() takes ownership of the
    request session's transaction — it commits on the create path and rolls
    back on every other terminal path. This route must therefore not hold
    uncommitted work on `db` across the call, and does not.

    ERROR MAPPING is deliberately NARROW (R-1). Only the three named domain
    refusals are converted to 4xx. There is no `except ValueError` here: the
    ledger's LedgerImbalanceError, InsufficientFundsError and
    AlreadySettledError all subclass ValueError, and a broad clause would
    convert a conservation failure — the loudest event this system can
    produce — into a quiet 400 carrying an internal message, so it would
    never page as a 5xx. Ledger errors, configuration errors and anything
    unexpected propagate and surface as 500. SeasonAllocationError, the
    shared parent, is deliberately NOT caught: catching it would reintroduce
    the same over-broad swallow one level down.
    """
    try:
        result = activate_season_allocation(league_id, db)
    except (PartialAllocationError, ConflictingAllocationError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except NoTeamsError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SeasonAllocationOut(
        league_id         = result.league_id,
        season            = result.season,
        team_ids          = list(result.team_ids),
        buyin_cents       = result.buyin_cents,
        min_reserve_cents      = result.min_reserve_cents,
        reserve_cents     = result.reserve_cents,
        total_buyin_cents = result.total_buyin_cents,
        created           = result.created,
    )


# ── BAB Top-Off (B6 §10) ──────────────────────────────────────────────────────
#
# Five routes, `league_id` always in the path. They are a THIN MAPPING LAYER over
# economy/top_off.py and nothing else: every lock, every cap computation, every
# ledger posting, the disclosure write and the single commit live in the service.
# No route here computes a cap, derives a reason code, writes a ledger entry or
# commits — a route that did would be a second issuance implementation.
#
# TRANSACTION OWNERSHIP. Each route hands the request-scoped Session straight to
# the service, which owns the transaction on it: it commits on its one writing
# path and rolls back on every abort. These routes therefore hold no uncommitted
# work across a service call and issue no commit or rollback of their own.
#
# PROVENANCE IS SERVER-SET AND UNSPOOFABLE (§10.2). The client supplies `amount`
# at creation and `decision_reason` where applicable. Everything else — league,
# team, season, both identities, the classification, the cap, both linkage ids,
# every timestamp, decision and status — is derived server-side, and every write
# body sets extra="forbid" so an attempt to supply one is a 422 rather than a
# silently dropped key.


class TopOffCreateRequest(BaseModel):
    """Create body. `amount` in DOLLARS is the ONLY accepted field (§10.2).

    extra="forbid" makes any additional key a 422 rather than a silently dropped
    one — the same contract CommissionerGrantRequest already carries. A client
    that tries to supply amount_cents, season, league_id, team_id, requester
    identity or any cap figure is told so.
    """
    model_config = ConfigDict(extra="forbid")

    amount: float


class TopOffDecisionRequest(BaseModel):
    """Approve/reject body. `decision_reason` is the only accepted field.

    OPTIONAL BY CONTRACT, not by oversight: §5.3 requires a non-empty reason on a
    SELF-approval and imposes no such requirement otherwise. The service decides
    which case applies — the route never classifies self-approval itself.
    """
    model_config = ConfigDict(extra="forbid")

    decision_reason: Optional[str] = None


class TopOffCancelRequest(BaseModel):
    """Cancel body. Deliberately EMPTY.

    The requester is the authenticated caller and the request is identified by
    the path, so there is nothing left for a client to supply. It still exists,
    and still carries extra="forbid", because §10.2 governs all four write
    bodies: an empty model that forbids extras rejects a spoofed field, whereas
    accepting no body at all would let one be ignored.
    """
    model_config = ConfigDict(extra="forbid")


class TopOffCreateOut(BaseModel):
    request_id:               int
    league_id:                int
    team_id:                  int
    season:                   int
    requester_user_id:        int
    amount_cents:             int
    decision:                 str
    status:                   str
    cap_cents:                int
    remaining_capacity_cents: int


class TopOffDecisionOut(BaseModel):
    request_id:               int
    league_id:                int
    team_id:                  int
    season:                   int
    requester_user_id:        Optional[int]
    amount_cents:             Optional[int]
    decision:                 str
    status:                   str
    decided_by_user_id:       Optional[int]
    decided_at:               Optional[str]
    self_approved:            Optional[bool]
    decision_reason:          Optional[str]
    ledger_posting_id:        Optional[str]
    disclosure_event_id:      Optional[str]
    cap_cents:                Optional[int]
    remaining_capacity_cents: Optional[int]
    posted:                   bool
    replayed:                 bool


class TopOffRequestOut(BaseModel):
    """One persisted top-off request, as stored.

    EVERY FIELD IS READ FROM THE ROW. Nothing here is recomputed — not the cap,
    not remaining capacity, not a balance, not current authority. A read that
    recomputed a cap would report a number taken under no lock, which approval
    would then be free to contradict.

    ledger_posting_id and disclosure_event_id are present because they are the
    provenance chain: request -> posting -> both ledger legs -> disclosure
    (§4.7). They are the whole reason a caller can traverse it from this payload.
    """
    id:                  int
    league_id:           int
    team_id:             int
    season:              Optional[int]
    requester_user_id:   Optional[int]
    amount_cents:        Optional[int]
    decision:            Optional[str]
    status:              str
    decided_by_user_id:  Optional[int]
    decided_at:          Optional[str]
    self_approved:       Optional[bool]
    decision_reason:     Optional[str]
    ledger_posting_id:   Optional[str]
    disclosure_event_id: Optional[str]
    created_at:          Optional[str]


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _uuid_str(value) -> Optional[str]:
    return str(value) if value is not None else None


def _member_team_id(user: User, league_id: int, db: Session) -> Optional[int]:
    """The id of `user`'s team IF that team belongs to `league_id`, else None.

    PURE READ. One SELECT, no write of any kind — no add, flush, commit, delete,
    merge or ORM mutation. That is not stylistic: the service that runs next owns
    the transaction on this same session and rolls it back on every abort, so a
    dependency-side write here would be silently discarded.

    Membership is TEAM-BASED because that is what the league roster is. Holding a
    commissioner authority row is a separate question, asked separately.
    """
    if user.team_id is None:
        return None
    team = db.query(Team).filter(Team.id == user.team_id).first()
    if team is None or team.league_id != league_id:
        return None
    return team.id


def _topoff_http(exc: Exception) -> HTTPException:
    """Map ONE service exception to its HTTP answer (§10.1).

    The reason codes are the SERVICE's — read off the exception, never
    re-derived here. §2.10 keeps the three zero-headroom causes distinct
    (multiplier is 0, no valid allocation, cap exhausted) and merging them in the
    mapping layer would undo that at the last step.

    503 for an integrity or season-close abort is deliberate and is what §10.1
    assigns: neither is the caller's fault, neither changed the request, and both
    are retryable once the underlying condition is fixed. Answering 4xx would
    tell the caller to change something about the request, which is false.
    """
    if isinstance(exc, CreationRefused):
        code = {
            REASON_INVALID_AMOUNT:     400,
            REASON_TEAM_NOT_IN_LEAGUE: 403,
            REASON_SEASON_CLOSED:      503,
            REASON_OPEN_REQUEST:       409,
            REASON_OVER_CAPACITY:      422,
            REASON_MULTIPLIER_ZERO:    422,
            REASON_NO_ALLOCATION:      422,
            REASON_CAP_EXHAUSTED:      422,
        }.get(exc.reason_code, 422)
        detail = {"reason_code": exc.reason_code, "message": str(exc)}
        # §10.1 requires remaining capacity to be STATED on the over-capacity
        # answer. It is carried on the exception by the service, which computed
        # it; the route reports it and does not recompute it.
        if exc.remaining_capacity_cents is not None:
            detail["remaining_capacity_cents"] = exc.remaining_capacity_cents
        return HTTPException(status_code=code, detail=detail)

    if isinstance(exc, RequestNotFoundError):
        return HTTPException(status_code=404, detail={
            "reason_code": "request_not_found", "message": str(exc)})
    if isinstance(exc, AuthorizationAttemptAbort):
        return HTTPException(status_code=403, detail={
            "reason_code": "not_authorized", "message": str(exc)})
    if isinstance(exc, AttemptValidationAbort):
        return HTTPException(status_code=422, detail={
            "reason_code": "self_approval_reason_required", "message": str(exc)})
    if isinstance(exc, SeasonClosedAbort):
        return HTTPException(status_code=503, detail={
            "reason_code": "season_closed", "message": str(exc)})
    if isinstance(exc, IntegrityAttemptAbort):
        return HTTPException(status_code=503, detail={
            "reason_code": "integrity_abort", "message": str(exc)})
    raise exc                      # not a top-off domain refusal — surface it


def _decision_out(result) -> TopOffDecisionOut:
    return TopOffDecisionOut(
        request_id               = result.request_id,
        league_id                = result.league_id,
        team_id                  = result.team_id,
        season                   = result.season,
        requester_user_id        = result.requester_user_id,
        amount_cents             = result.amount_cents,
        decision                 = result.decision,
        status                   = result.status,
        decided_by_user_id       = result.decided_by_user_id,
        decided_at               = _iso(result.decided_at),
        self_approved            = result.self_approved,
        decision_reason          = result.decision_reason,
        ledger_posting_id        = _uuid_str(result.ledger_posting_id),
        disclosure_event_id      = _uuid_str(result.disclosure_event_id),
        cap_cents                = result.cap_cents,
        remaining_capacity_cents = result.remaining_capacity_cents,
        posted                   = result.posted,
        replayed                 = result.replayed,
    )


def _settle_replay(result, expected_decision: str) -> TopOffDecisionOut:
    """§10.1's replay rule, applied identically on all three decision routes.

    A repeat of the SAME decision returns 200 with the original payload — the
    caller's first request did land, and saying so is the truthful answer to a
    retry after a lost response. A DIFFERENT action against a terminal request is
    409: the request is decided, and this caller asked for something else.
    """
    if not result.replayed or result.decision == expected_decision:
        return _decision_out(result)
    raise HTTPException(status_code=409, detail={
        "reason_code": "terminal_state_conflict",
        "message": (f"Top-off request {result.request_id} is already "
                    f"{result.decision!r} (status {result.status!r}); it cannot "
                    f"now be {expected_decision!r}."),
        "decision": result.decision,
        "status":   result.status,
    })


@app.post("/league/{league_id}/top-offs", response_model=TopOffCreateOut,
          status_code=201)
def league_create_top_off(
    league_id:    int,
    req:          TopOffCreateRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """A GM of THIS league asks for more Credits (§10).

    MEMBERSHIP, NOT AUTHORITY. The caller must own a team in the path league;
    holding a commissioner row is neither required nor sufficient. A commissioner
    who owns a team here may request as a GM — §5.3 makes authority and team
    ownership independent by design.

    team_id and requester identity are taken from the AUTHENTICATED USER and the
    persisted Team row, never from the body. The body carries `amount` alone.
    """
    team_id = _member_team_id(current_user, league_id, db)
    if team_id is None:
        raise HTTPException(status_code=403, detail={
            "reason_code": "not_a_league_member",
            "message": (f"User {current_user.id} owns no team in league "
                        f"{league_id}."),
        })
    try:
        result = create_top_off_request(
            league_id, team_id, current_user.id, req.amount, db=db,
        )
    except Exception as exc:                       # noqa: BLE001 — mapped below
        raise _topoff_http(exc)
    return TopOffCreateOut(
        request_id               = result.request_id,
        league_id                = result.league_id,
        team_id                  = result.team_id,
        season                   = result.season,
        requester_user_id        = result.requester_user_id,
        amount_cents             = result.amount_cents,
        decision                 = result.decision,
        status                   = result.status,
        cap_cents                = result.cap_cents,
        remaining_capacity_cents = result.remaining_capacity_cents,
    )


@app.post("/league/{league_id}/top-offs/{request_id}/approve",
          response_model=TopOffDecisionOut, status_code=200)
def league_approve_top_off(
    league_id:  int,
    request_id: int,
    req:        TopOffDecisionRequest,
    db:         Session = Depends(get_db),
    _comm:      User    = Depends(require_league_commissioner),
):
    """A commissioner of THIS league approves a top-off and issues the Credits.

    §5.1 assigns this route Depends(require_league_commissioner): authority is a
    LeagueCommissioner row for (league_id, caller). The dependency's read is
    preliminary — the service revalidates it under the League row lock at step 14
    and holds that lock through commit, so a revocation cannot land between the
    check and the issuance.

    SELF-APPROVAL IS PERMITTED (§5.2) and needs a non-empty decision_reason. The
    route neither classifies it nor counts commissioners; the service does the
    one comparison that decides it.
    """
    try:
        result = approve_top_off(league_id, request_id, _comm.id,
                                 req.decision_reason, db=db)
    except Exception as exc:                       # noqa: BLE001 — mapped below
        raise _topoff_http(exc)
    return _settle_replay(result, "approved")


@app.post("/league/{league_id}/top-offs/{request_id}/reject",
          response_model=TopOffDecisionOut, status_code=200)
def league_reject_top_off(
    league_id:  int,
    request_id: int,
    req:        TopOffDecisionRequest,
    db:         Session = Depends(get_db),
    _comm:      User    = Depends(require_league_commissioner),
):
    """A commissioner of THIS league explicitly declines an open request.

    One of the three things §7.4 reserves terminal rejection for. No posting, no
    wallet movement, no disclosure, no linkage — and after close it is not
    decided at all (§7.5), which the service enforces under the League lock.
    """
    try:
        result = reject_top_off(league_id, request_id, _comm.id,
                                req.decision_reason, db=db)
    except Exception as exc:                       # noqa: BLE001 — mapped below
        raise _topoff_http(exc)
    return _settle_replay(result, "rejected")


@app.post("/league/{league_id}/top-offs/{request_id}/cancel",
          response_model=TopOffDecisionOut, status_code=200)
def league_cancel_top_off(
    league_id:    int,
    request_id:   int,
    req:          TopOffCancelRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """The requester withdraws his own open request (§7.2).

    IDENTITY IS ENFORCED BY THE SERVICE, from persisted state, under the request
    row lock — not here. The route cannot know who opened the request without
    reading it, and reading it outside the lock would be exactly the stale read
    the lock exists to prevent. A caller who is not the requester receives 403
    from the service's own refusal.
    """
    try:
        result = cancel_top_off(league_id, request_id, current_user.id, db=db)
    except Exception as exc:                       # noqa: BLE001 — mapped below
        raise _topoff_http(exc)
    return _settle_replay(result, "cancelled")


@app.get("/league/{league_id}/top-offs", response_model=list[TopOffRequestOut])
def league_list_top_offs(
    league_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """Top-off request history for this league (§10).

    SCOPE. A commissioner of the path league sees every B6 top-off request in it.
    Any other caller must own a team in the league and sees only that team's
    requests. Everyone else receives 403 — league membership is checked before
    any row is returned, so this route cannot be used to probe another league.

    ONLY B6 ROWS. Filtered to type='topup_bet'. Legacy topup_waiver history is
    dormant (§11.5) and is not a top-off request.

    PERSISTED STATE ONLY. Every field is read from the row. Nothing is
    recomputed — no cap, no remaining capacity, no balance, no current authority.
    remaining_capacity_cents is deliberately ABSENT: it is not stored, it would
    have to be derived outside any lock, and approval's re-check under lock 2 is
    the only authoritative answer (§2.10).

    Ordering is created_at then id, ascending. That is implementation
    determinism so a caller gets a stable page, not a product rule.

    applied_at is deliberately NOT read. It is a legacy column the B6 issuance
    path does not write; `decision`, `status` and `decided_at` are the B6 record.
    """
    if not is_league_commissioner(current_user.id, league_id, db):
        team_id = _member_team_id(current_user, league_id, db)
        if team_id is None:
            raise HTTPException(status_code=403, detail={
                "reason_code": "not_a_league_member",
                "message": (f"User {current_user.id} is neither a commissioner "
                            f"of league {league_id} nor an owner of a team in "
                            f"it."),
            })
    else:
        team_id = None             # commissioner: the whole league

    q = (db.query(FaabTransaction)
         .filter(FaabTransaction.league_id == league_id,
                 FaabTransaction.type == TOPUP_BET))
    if team_id is not None:
        q = q.filter(FaabTransaction.team_id == team_id)

    rows = q.order_by(FaabTransaction.created_at, FaabTransaction.id).all()
    return [
        TopOffRequestOut(
            id                  = r.id,
            league_id           = r.league_id,
            team_id             = r.team_id,
            season              = r.season,
            requester_user_id   = r.requester_user_id,
            amount_cents        = r.amount_cents,
            decision            = r.decision,
            status              = r.status,
            decided_by_user_id  = r.decided_by_user_id,
            decided_at          = _iso(r.decided_at),
            self_approved       = r.self_approved,
            decision_reason     = r.decision_reason,
            ledger_posting_id   = _uuid_str(r.ledger_posting_id),
            disclosure_event_id = _uuid_str(r.disclosure_event_id),
            created_at          = _iso(r.created_at),
        )
        for r in rows
    ]


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
    payment_url: Optional[str]  # always None; the MVP has no payment rail


class TopupConfirmRequest(BaseModel):
    faab_tx_id: int


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
    current_user: User = Depends(get_current_gm),
):
    """Commissioner configures opening balances and transfer rules for the season."""
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

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
    current_user: User = Depends(get_current_gm),
):
    """
    Credit opening balances to all teams in the league.
    Idempotent — skips teams that already have FAAB wallets.
    """
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, league_id, db)

    try:
        states = init_season_wallets(league_id, db, performer_id=current_user.id)
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


# ── FAAB top-up surface — PERMANENTLY REPLACED BY B6 ─────────────────────────
#
# POST /faab/topup-bet, /faab/topup-waiver, /faab/topup-confirm and
# /faab/apply-pending are NOT registered, and are NOT restored (§10.3). The five
# Top-Off routes above replace them.
#
# Stripe is out of the MVP, so the payment rail these routes were built on no
# longer exists. The temporary request-and-confirm flow that replaced it was
# NOT an acceptable permanent Credits issuance model: it minted wallet balance
# with no counterparty and no ledger posting behind it.
#
# B6 SUPPLIES WHAT WAS MISSING, and it lives in economy/top_off.py:
#   - a balanced two-leg ledger posting under the canonical top-off door;
#   - an issuance counterparty account, bab_issuance:{league_id}:{season} — a
#     top-off never debits `world`, which is reserved for real external capital;
#   - approver identity, revalidated under the League row lock before posting;
#   - request-to-credit provenance, request -> posting -> disclosure.
# See FantasyBeefs_BAB_TopOff_UIUX_Spec_2026-07-21.md item B6 and
# spec/SPEC_B2_Stripe_Removal_Addendum_v1.md.
#
# The legacy implementation in wallet/faab_wallet.py is intentionally NOT
# deleted — its historical models hold real rows. Its three writers now REFUSE
# structurally (§11.5), so economy/top_off.py is the one production issuance
# path and no legacy route or writer can bypass it.
#
# REMAINING NON-ROUTE REACHABILITY, recorded rather than assumed away:
# notifications/tuesday_sync.py::_step_apply_topups still calls
# apply_pending_topups(), and that pipeline is reachable via
# POST /admin/tuesday-sync. With the request routes gone no route can create
# an eligible pending record, but that is a database precondition, not a
# structural guarantee. Neutralising the Tuesday step is tracked as REQUIRED
# and is deliberately out of scope for this closure package.

@app.post("/faab/transfer", status_code=410, deprecated=True)
def faab_do_transfer():
    raise HTTPException(
        status_code=410,
        detail=(
            "BAB-to-waiver transfers are retired under the four-bucket "
            "economy and are no longer supported."
        ),
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
    req:          FreezeRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """Commissioner manually freezes or unfreezes a team's bet wallet."""
    # S8-P2: the request names a TEAM, and a team belongs to exactly one
    # league, so authority is checked against that team's league. Freezing a
    # wallet is a real restraint on a GM's ability to act, and before P2 any
    # globally-roled commissioner could impose it on any team in any league.
    assert_league_commissioner(
        current_user, _league_of(Team, req.team_id, db, "Team"), db)

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
    db:           Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
):
    """
    Parse a natural language rule using AI (Ollama → Anthropic → heuristic).
    Does NOT save anything — commissioner reviews the preview before creating.
    """
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role. This route saves nothing,
    # but it spends an AI call and reflects league context back to the caller,
    # so it is gated like the rest — a preview is still an action.
    # `db` is new here: the route had no database dependency because it never
    # touched one, and the authority lookup does.
    assert_league_commissioner(current_user, req.league_id, db)

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
    current_user: User = Depends(get_current_gm),
):
    """
    Save a parsed rule as a draft.
    Pass the spec dict from /rules/parse, optionally edited before saving.
    """
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

    try:
        rule = create_rule_draft(
            req.league_id, req.raw_text, req.spec, db,
            performer_id = current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _rule_model_out(rule)


@app.get("/rules/league/{league_id}", response_model=list[RuleOutModel])
def rules_list(
    league_id: int,
    status:    Optional[str] = Query(default=None, description="draft|active|paused|completed"),
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """List all rules for a league (commissioner-only)."""
    return [_rule_model_out(r) for r in list_rules(league_id, db, status=status)]


@app.get("/rules/{rule_id}", response_model=RuleOutModel)
def rules_get(
    rule_id: int,
    db:      Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
):
    """Get a specific rule by ID."""
    # S8-P2: the league is reachable only through the entity, so it is
    # resolved first and authority is checked against it.
    assert_league_commissioner(
        current_user, _league_of(CommissionerRule, rule_id, db, "Rule"), db)

    try:
        return _rule_model_out(get_rule(rule_id, db))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/rules/activate/{rule_id}", response_model=RuleOutModel, status_code=200)
def rules_activate(
    rule_id: int,
    db:      Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
):
    """Activate a draft rule so it will be executed on Tuesday runs."""
    # S8-P2: the league is reachable only through the entity, so it is
    # resolved first and authority is checked against it.
    assert_league_commissioner(
        current_user, _league_of(CommissionerRule, rule_id, db, "Rule"), db)

    try:
        return _rule_model_out(activate_rule(rule_id, db, performer_id=current_user.id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/rules/pause/{rule_id}", response_model=RuleOutModel, status_code=200)
def rules_pause(
    rule_id: int,
    db:      Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
):
    """Pause an active rule without deleting it."""
    # S8-P2: the league is reachable only through the entity, so it is
    # resolved first and authority is checked against it.
    assert_league_commissioner(
        current_user, _league_of(CommissionerRule, rule_id, db, "Rule"), db)

    try:
        return _rule_model_out(pause_rule(rule_id, db, performer_id=current_user.id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/rules/draft/{rule_id}", status_code=204)
def rules_delete_draft(
    rule_id: int,
    db:      Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
):
    """Delete a draft rule (cannot delete active/paused/completed rules)."""
    # S8-P2: the league is reachable only through the entity, so it is
    # resolved first and authority is checked against it.
    assert_league_commissioner(
        current_user, _league_of(CommissionerRule, rule_id, db, "Rule"), db)

    try:
        delete_draft(rule_id, db, performer_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/rules/execute-weekly", response_model=list[RuleExecutionOutModel], status_code=200)
def rules_execute_weekly(
    req:   WeeklyExecuteRequest,
    db:    Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
):
    """
    Execute all active weekly rules for the given week.
    Called by Tuesday automation (P1.5). Idempotent.
    """
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

    try:
        execs = execute_weekly_rules(req.league_id, req.week, db, performer_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [_exec_model_out(e) for e in execs]


@app.post("/rules/execute-end-of-season", response_model=list[RuleExecutionOutModel], status_code=200)
def rules_execute_eos(
    req:   EosExecuteRequest,
    db:    Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
):
    """
    Execute all active end-of-season rules and release qualifying escrow accounts.
    Called during final settlement (P1.5). Idempotent.
    """
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

    try:
        execs = execute_end_of_season_rules(req.league_id, db, performer_id=current_user.id)
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
    _comm:     User    = Depends(require_league_commissioner),
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
    current_user: User = Depends(get_current_gm),
):
    """
    Manually release an open escrow to a target team's bet wallet.
    If target_team_id is omitted, uses the escrow's stored release target.
    """
    # S8-P2: the league is reachable only through the entity, so it is
    # resolved first and authority is checked against it.
    assert_league_commissioner(
        current_user, _league_of(EscrowAccount, escrow_id, db, "Escrow account"), db)

    try:
        esc = release_escrow(escrow_id, db, performer_id=current_user.id,
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
    _comm:  User    = Depends(require_league_commissioner),
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
    current_user: User = Depends(get_current_gm),
):
    """
    Manually trigger the Tuesday automation for a specific week.
    Set mock_mode=false only when SMTP is configured and you want real emails.
    """
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

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
    _comm:     User    = Depends(require_league_commissioner),
):
    """List recent Tuesday sync runs for a league. Commissioner-only."""
    return get_run_history(league_id, db, limit=limit)


@app.get("/admin/tuesday-sync/run/{run_id}")
def admin_sync_run_detail(
    run_id:       str,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """Get full detail for a specific Tuesday sync run, including all step logs."""
    # S8-P2: `run_id` is the run's own opaque identifier, NOT the primary key,
    # so this cannot use _league_of() and looks the row up by the column the
    # route actually keys on. Getting that wrong would authorize against some
    # other league's run that happened to share an integer id.
    run = db.query(TuesdaySyncRun).filter(TuesdaySyncRun.run_id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    assert_league_commissioner(current_user, run.league_id, db)

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
    current_user: User = Depends(get_current_gm),
):
    """
    Generate AI Weekly Wrap-Up + Roast Beef for the given week.
    Stores as draft, posts to feed, and emails all GMs.
    Commissioner can regenerate with updated content.
    """
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

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
    _comm:     User    = Depends(require_league_commissioner),
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
    _comm:     User    = Depends(require_league_commissioner),
):
    """List all wrap-ups for a league, newest first."""
    return [_wrapup_out(w) for w in get_wrap_up_list(league_id, db, limit=limit)]


@app.put("/reports/wrap-up/{wrap_up_id}", status_code=200)
def reports_wrap_up_edit(
    wrap_up_id: int,
    req:        WrapUpEditRequest,
    db:         Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
):
    """Commissioner edits the league body and/or roast beef section before send."""
    # S8-P2: the league is reachable only through the entity, so it is
    # resolved first and authority is checked against it.
    assert_league_commissioner(
        current_user, _league_of(WeeklyWrapUp, wrap_up_id, db, "Wrap-up"), db)

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
    current_user: User = Depends(get_current_gm),
):
    """
    Re-send (or first-send) wrap-up emails to all GMs.
    Use after commissioner has reviewed/edited the draft.
    """
    # S8-P2: the league is reachable only through the entity, so it is
    # resolved first and authority is checked against it.
    assert_league_commissioner(
        current_user, _league_of(WeeklyWrapUp, wrap_up_id, db, "Wrap-up"), db)

    try:
        sent = send_wrap_up(wrap_up_id, db, mock_mode=req.mock_mode)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"wrap_up_id": wrap_up_id, "emails_sent": sent}


@app.get("/reports/wrap-up/{wrap_up_id}/editions", status_code=200)
def reports_wrap_up_editions(
    wrap_up_id: int,
    db:         Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
):
    """List all per-GM editions for a wrap-up (status tags, playoff prob, sent status)."""
    # S8-P2: the league is reachable only through the entity, so it is
    # resolved first and authority is checked against it.
    assert_league_commissioner(
        current_user, _league_of(WeeklyWrapUp, wrap_up_id, db, "Wrap-up"), db)

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
    current_user: User = Depends(get_current_gm),
):
    """Compute (or recompute) power rankings for the given league and week, post to feed."""
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

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


# ── My Account (B2, Section 6) ────────────────────────────────────────────────

class MyAccountOut(BaseModel):
    team_id:                  int
    skunk_pot_cents:          int
    skunk_pot_dollars:        str
    championship_pot_cents:   int
    championship_pot_dollars: str
    my_open_receivable_cents: int
    my_open_receivable_dollars: str


@app.get("/account/{team_id}/summary", response_model=MyAccountOut)
def account_summary(
    team_id:      int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """Skunk pot, championship pot, and this team's own open receivable (B2-6.5)."""
    assert_own_team(team_id, current_user)
    try:
        summary = get_my_account_summary(team_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return MyAccountOut(
        team_id=summary.team_id,
        skunk_pot_cents=summary.skunk_pot_cents,
        skunk_pot_dollars=_cents_to_dollars(summary.skunk_pot_cents),
        championship_pot_cents=summary.championship_pot_cents,
        championship_pot_dollars=_cents_to_dollars(summary.championship_pot_cents),
        my_open_receivable_cents=summary.my_open_receivable_cents,
        my_open_receivable_dollars=_cents_to_dollars(summary.my_open_receivable_cents),
    )


# ── Season-end settlement report decomposition (B2-6.3-R) ────────────────────

class SettlementRowOut(BaseModel):
    place:                    int
    team_id:                  int
    team_name:                str
    pct:                      int
    payout_cents:             int
    payout_dollars:           str
    collected_cents:          int
    collected_dollars:        str
    contingent_cents:         int
    contingent_dollars:       str


class SettlementReportOut(BaseModel):
    league_id:               int
    pot_total_cents:         int
    pot_total_dollars:       str
    collected_cents:         int
    collected_dollars:       str
    contingent_cents:        int
    contingent_dollars:      str
    rows:                    list[SettlementRowOut]


@app.get("/reports/settlement/{league_id}", response_model=SettlementReportOut)
def reports_settlement(
    league_id: int,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """Season-end settlement report: each winner's payout decomposed into
    collected vs. contingent-on-outstanding-receivables (B2-6.3-R)."""
    report = championship_settlement_report(league_id, db)
    return SettlementReportOut(
        league_id=report.league_id,
        pot_total_cents=report.pot_total_cents,
        pot_total_dollars=_cents_to_dollars(report.pot_total_cents),
        collected_cents=report.collected_cents,
        collected_dollars=_cents_to_dollars(report.collected_cents),
        contingent_cents=report.contingent_cents,
        contingent_dollars=_cents_to_dollars(report.contingent_cents),
        rows=[
            SettlementRowOut(
                place=r.place, team_id=r.team_id, team_name=r.team_name, pct=r.pct,
                payout_cents=r.payout_cents, payout_dollars=_cents_to_dollars(r.payout_cents),
                collected_cents=r.collected_cents, collected_dollars=_cents_to_dollars(r.collected_cents),
                contingent_cents=r.contingent_cents, contingent_dollars=_cents_to_dollars(r.contingent_cents),
            )
            for r in report.rows
        ],
    )


# ── Accounting read models (S8-P3) ───────────────────────────────────────────
#
# THREE SURFACES, ONE CALCULATION. The GM Ledger, the commissioner's GM cards
# and the League Reconciliation are all served from
# `reports/ledger_read_model.py`, which calls `economy.current_settle` exactly
# once. These routes shape and authorize; they compute nothing. A figure
# assembled here would be a second accounting system with a nicer name.
#
# EXACT INTEGER CENTS ARE THE CONTRACT. Every monetary field below is an `int`
# and is named `*_cents`. Unlike the older settlement report, which carries
# `*_dollars` strings beside its cents for compatibility, these models publish
# no formatted value at all: whole-dollar display is a Rev 4.2 presentation
# decision that happens once, in `credits.js`, over the exact cents.

class GmLedgerOut(BaseModel):
    """One GM's authoritative position. Every monetary field is exact cents."""
    team_id:   int
    team_name: str
    owner:     str

    # Assets
    wallet_cents:          int
    weekly_min_live_cents: int
    min_reserve_cents:     int
    expired_min_cents:     int
    in_play_cents:         int
    assets_cents:          int

    # Obligations
    season_advance_cents: int
    topoff_issued_cents:  int
    receivable_cents:     int
    obligations_cents:    int

    # Result
    current_settle_cents: int

    # Reported beside the position, never inside a total
    held_open_challenges_cents: int

    # Groupings of the authoritative terms above
    available_cents:            int
    total_virtual_stakes_cents: int


class ExceptionRowOut(BaseModel):
    count:                int
    cents:                int
    settlement_liability: bool
    note:                 str


class LeagueReconciliationOut(BaseModel):
    league_id:      int
    season:         int
    position_count: int

    aggregate_assets_cents:               int
    aggregate_obligations_cents:          int
    aggregate_current_settle_cents:       int
    aggregate_total_virtual_stakes_cents: int
    sum_of_gm_settles_cents:              int
    reconciles:                           bool

    exceptions: dict[str, ExceptionRowOut]


def _read_model_error(e: LedgerReadModelError) -> HTTPException:
    """Domain refusals mapped NARROWLY.

    Only the two named reasons become 4xx. `CurrentSettleError` — which is what
    an unattributable escrow raises — is deliberately NOT caught: it means
    posted state cannot be explained, which is the loudest thing this system can
    say, and converting it into a tidy 400 would hide it from the alerting that
    a 500 reaches.
    """
    if e.reason == REASON_LEAGUE_NOT_FOUND:
        return HTTPException(status_code=404, detail=str(e))
    if e.reason == REASON_TEAM_NOT_IN_LEAGUE:
        return HTTPException(status_code=403, detail=str(e))
    raise e


@app.get("/league/{league_id}/ledger/me", response_model=GmLedgerOut)
def ledger_me(
    league_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """The acting GM's own position in this league.

    THE TEAM IS NOT A PARAMETER, and that is the security property. It is
    resolved from the authenticated user's own team and checked to belong to
    the path league, so there is no id for a caller to substitute — a GM cannot
    read another GM's Ledger through this route because there is nowhere to ask
    for one. The commissioner surface below is the governed way to see other
    GMs, and it requires commissioner authority for the league.

    A caller with no team in this league receives 403 rather than an empty
    position: "you are not in this league" and "you are in it with nothing" are
    different answers and must not look alike.
    """
    team_id = _member_team_id(current_user, league_id, db)
    if team_id is None:
        raise HTTPException(status_code=403, detail={
            "reason_code": "not_a_league_member",
            "message": (f"User {current_user.id} owns no team in league "
                        f"{league_id}."),
        })
    try:
        return GmLedgerOut(**gm_ledger(db, team_id=team_id,
                                       league_id=league_id).as_dict())
    except LedgerReadModelError as e:
        raise _read_model_error(e)


# ── League and Week read models (S8-P4C-3) ───────────────────────────────────

class LeagueContextOut(BaseModel):
    league_id:   int
    league_name: str
    season:      int

    #: The provider's own current week, or null. NULL IS AN ANSWER — no refresh
    #: has stated one — and the surfaces render it as unresolved rather than
    #: substituting a number.
    current_week:   Optional[int]
    week_resolved:  bool

    provider:            Optional[str]
    provider_league_key: Optional[str]
    provider_state:      str

    acting_team_id:           int
    acting_team_name:         str
    acting_team_owner:        str
    acting_provider_team_key: Optional[str]

    season_final_week:  Optional[int]
    playoff_start_week: Optional[int]

    #: The acting GM's season W/L, from decided matchups only.
    record_resolved: bool
    wins:            Optional[int]
    losses:          Optional[int]
    ties:            Optional[int]
    decided:         int
    record_label:    Optional[str]


class MatchupSideOut(BaseModel):
    team_id:           int
    team_name:         str
    owner:             str
    provider_team_key: Optional[str]
    points:            Optional[float]
    is_acting_team:    bool


class WeekMatchupOut(BaseModel):
    matchup_id:           int
    week:                 int
    provider_matchup_key: Optional[str]
    home:                 MatchupSideOut
    away:                 MatchupSideOut
    final:                bool
    finalized_at:         Optional[str]
    winner_team_id:       Optional[int]
    refreshed_at:         Optional[str]
    involves_acting_team: bool
    acting_side:          Optional[str]


class WeekStateOut(BaseModel):
    league_id: int
    week:      int
    empty:     bool
    matchups:  list[WeekMatchupOut]


@app.get("/league/{league_id}/context/me", response_model=LeagueContextOut)
def league_context_me(
    league_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """The acting GM's league identity, current week and season record.

    THE ONE PLACE THE APPLICATION LEARNS WHAT WEEK IT IS. Before this, the
    production shell imported `CURRENT_WEEK` from an illustrative fixture and
    used it for the Pool slate request, the Action header and every week-scoped
    figure — so a real league in week 9 was served week 5. The provider has
    always stated its current week; nothing persisted it until S8-P4C-3.

    The team is resolved from the session, never from a parameter.
    """
    team_id = _member_team_id(current_user, league_id, db)
    if team_id is None:
        raise HTTPException(status_code=403, detail={
            "reason_code": "not_a_league_member",
            "message": (f"User {current_user.id} owns no team in league "
                        f"{league_id}."),
        })
    try:
        context = league_context(db, team_id=team_id, league_id=league_id)
        record = season_record(db, team_id=team_id, league_id=league_id)
    except LeagueReadError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return LeagueContextOut(
        league_id=context.league_id,
        league_name=context.league_name,
        season=context.season,
        current_week=context.current_week,
        week_resolved=context.week_resolved,
        provider=context.provider,
        provider_league_key=context.provider_league_key,
        provider_state=context.provider_state,
        acting_team_id=context.acting_team_id,
        acting_team_name=context.acting_team_name,
        acting_team_owner=context.acting_team_owner,
        acting_provider_team_key=context.acting_provider_team_key,
        season_final_week=context.season_final_week,
        playoff_start_week=context.playoff_start_week,
        record_resolved=record.resolved,
        wins=record.wins,
        losses=record.losses,
        ties=record.ties,
        decided=record.decided,
        record_label=record.label,
    )


@app.get("/league/{league_id}/week/{week}/matchups",
         response_model=WeekStateOut)
def league_week_matchups(
    league_id:    int,
    week:         int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """The provider-backed matchups for one league-week.

    LEAGUE-SCOPED, unlike the legacy `/league/matchups/{week}`, which queries
    every matchup in the database regardless of league and would disclose
    another league's scores to anyone who asked.

    AN EMPTY WEEK IS A SUCCESSFUL READ. `empty: true` means the provider has
    published nothing for this week yet — an ordinary state, and a different
    one from a read that failed.
    """
    if not 1 <= week <= 22:
        raise HTTPException(status_code=400, detail="week must be 1-22")
    team_id = _member_team_id(current_user, league_id, db)
    if team_id is None:
        raise HTTPException(status_code=403, detail={
            "reason_code": "not_a_league_member",
            "message": (f"User {current_user.id} owns no team in league "
                        f"{league_id}."),
        })
    try:
        state = week_matchups(db, league_id=league_id, week=week,
                              acting_team_id=team_id)
    except LeagueReadError as e:
        raise HTTPException(status_code=409, detail=str(e))

    def side(s) -> MatchupSideOut:
        return MatchupSideOut(**{f: getattr(s, f)
                                 for f in MatchupSideOut.model_fields})

    return WeekStateOut(
        league_id=state.league_id,
        week=state.week,
        empty=state.empty,
        matchups=[
            WeekMatchupOut(
                matchup_id=m.matchup_id, week=m.week,
                provider_matchup_key=m.provider_matchup_key,
                home=side(m.home), away=side(m.away),
                final=m.final, finalized_at=m.finalized_at,
                winner_team_id=m.winner_team_id, refreshed_at=m.refreshed_at,
                involves_acting_team=m.involves_acting_team,
                acting_side=m.acting_side,
            )
            for m in state.matchups
        ],
    )


# ── Action read model (S8-P4C-2) ─────────────────────────────────────────────

class ActionCardOut(BaseModel):
    challenge_id:   int
    section:        str
    status:         str
    protocol_state: str
    mode:           str
    week:           int

    opponent_team_id: int
    opponent_name:    str
    direction:        str

    decision_team_id: Optional[int]
    viewer_decides:   bool
    controls:         list[str]

    wager_type:        Optional[str]
    line:              Optional[float]
    side:              Optional[str]
    player_id:         Optional[int]
    your_stake_cents:  int
    their_stake_cents: Optional[int]
    pot_cents:         Optional[int]
    your_odds:         Optional[float]
    their_odds:        Optional[float]
    your_moneyline:    Optional[int]
    their_moneyline:   Optional[int]

    escrow_cents:          int
    derived_ceiling_cents: Optional[int] = None
    derived_repriced:      bool = False

    settled:   bool = False
    net_cents: Optional[int] = None

    created_at:     Optional[str] = None
    expires_at:     Optional[str] = None
    version_number: Optional[int] = None


class ActionOpponentOut(BaseModel):
    team_id:   int
    team_name: str
    owner:     str


class ActionStateOut(BaseModel):
    """The whole Action tab, sections already decided by the backend."""
    team_id:   int
    league_id: int
    counts:    dict[str, int]
    sections:  dict[str, list[ActionCardOut]]
    opponents: list[ActionOpponentOut]


@app.get("/league/{league_id}/action/me", response_model=ActionStateOut)
def action_me(
    league_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """The acting GM's own Action tab.

    THE TEAM IS NOT A PARAMETER, exactly as on the Ledger route, and for the
    same reason: this discloses a GM's open negotiating positions and stakes, so
    there must be no id for a caller to substitute. A commissioner reads their
    own Action here and nobody else's — P4C-1R settled that holding the role is
    not a way of being a participant.

    SECTIONS ARE SERVED, NOT SUGGESTED. The response carries the four rails
    already populated and the counts already taken, because the classification
    is a protocol statement and the browser is not the place to re-derive one.
    """
    team_id = _member_team_id(current_user, league_id, db)
    if team_id is None:
        raise HTTPException(status_code=403, detail={
            "reason_code": "not_a_league_member",
            "message": (f"User {current_user.id} owns no team in league "
                        f"{league_id}."),
        })
    try:
        state = gm_action_state(db, team_id=team_id, league_id=league_id)
    except ActionReadError as e:
        raise HTTPException(status_code=409, detail=str(e))

    def out(card) -> ActionCardOut:
        payload = {f: getattr(card, f) for f in ActionCardOut.model_fields
                   if f != "controls"}
        return ActionCardOut(**payload, controls=list(card.controls))

    return ActionStateOut(
        team_id=state.team_id,
        league_id=state.league_id,
        counts=state.counts,
        sections={name: [out(c) for c in state.section(name)]
                  for name in ACTION_SECTIONS},
        opponents=[ActionOpponentOut(team_id=o.team_id, team_name=o.team_name,
                                     owner=o.owner)
                   for o in state.opponents],
    )


@app.get("/league/{league_id}/ledger/positions", response_model=list[GmLedgerOut])
def ledger_positions(
    league_id: int,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """Every GM's position in this league — the commissioner's GM Ledger cards.

    League-scoped authority, checked before any position is read, so this route
    cannot be used to probe another league's roster size or existence.

    One entry per team actually in the league. The Rev 4.2 surface shows twelve
    cards because the illustrative league has twelve teams; nothing here assumes
    that number.
    """
    try:
        return [GmLedgerOut(**p.as_dict())
                for p in league_positions(db, league_id=league_id)]
    except LedgerReadModelError as e:
        raise _read_model_error(e)


@app.get("/league/{league_id}/ledger/reconciliation",
         response_model=LeagueReconciliationOut)
def ledger_reconciliation(
    league_id: int,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """Whether this league's GM positions reconcile.

    LEAGUE-SCOPED, AND NOT THE TRIAL BALANCE. This aggregates the same GM
    positions the route above returns and reports whether the league's own
    arithmetic closes. It is a different question from the ledger's global
    conservation invariant, which remains global and — per S8-P3R — has NO HTTP
    surface at all: the authority model has no platform-operator tier above
    league commissioner, so there is nobody who could hold such a route safely.
    `ledger.trial_balance()` stays a backend/operator invariant, exercised in
    certification rather than served.

    THIS IS THE COMMISSIONER-FACING ACCOUNTING SURFACE. A commissioner asking
    "does the money add up?" is asking about THEIR league, and this answers
    exactly that, from the same positions their GM cards are drawn from.
    """
    try:
        report = league_reconciliation(db, league_id=league_id)
    except LedgerReadModelError as e:
        raise _read_model_error(e)
    return LeagueReconciliationOut(**report.as_dict())


# ── League settings: authoritative read + the one governed command (S8-P4) ───
#
# READ IS FOR EVERY LEAGUE MEMBER; WRITE IS COMMISSIONER-ONLY, and only one
# value is writable. The B2 ruling fixed that: Economy Stop, Skunk Fee and
# Championship split are READ-ONLY for MVP, because changing any of them
# mid-season re-prices obligations GMs have already funded. Standard Pool Bet
# is the one setting the POR says a commissioner sets, and it carries its own
# freeze so it cannot change after the season has started spending it.

class SettingsPoolEntryOut(BaseModel):
    cents:         int
    min_cents:     int
    max_cents:     int
    default_cents: int
    frozen:        bool
    frozen_at:     Optional[str]
    editable:      bool


class SettingsEconomyStopOut(BaseModel):
    weekly_min_cents:  int
    min_reserve_cents: int
    reserve_cents:     int
    buyin_cents:       int
    editable:          bool


class SettingsSkunkOut(BaseModel):
    weekly_cents:         int
    season_maximum_cents: int
    editable:             bool


class SettingsChampionshipSplitOut(BaseModel):
    split:    list[int]
    editable: bool


class LeagueSettingsOut(BaseModel):
    """The four governed settings, read from their real sources.

    `editable` is reported per setting so the UI does not have to encode the B2
    ruling in JavaScript. It is presentation guidance only: a write to a
    read-only setting is refused because no command exists for it, not because
    this flag said so.
    """
    league_id:          int
    season:             int
    economy_stop:       SettingsEconomyStopOut
    pool_entry:         SettingsPoolEntryOut
    skunk:              SettingsSkunkOut
    championship_split: SettingsChampionshipSplitOut


def _assert_league_member(current_user: User, league_id: int, db: Session) -> None:
    """Membership OR league commissioner authority. Raises 403 otherwise.

    A commissioner who owns no team in the league is still a member for the
    purpose of reading the league's own rules.
    """
    if (_member_team_id(current_user, league_id, db) is None
            and not is_league_commissioner(current_user.id, league_id, db)):
        raise HTTPException(status_code=403, detail={
            "reason_code": "not_a_league_member",
            "message": f"User {current_user.id} is not a member of league {league_id}.",
        })


def _league_settings(db: Session, league_id: int) -> LeagueSettingsOut:
    from betting.pool_funding import (
        GOVERNED_DEFAULT_WEEKLY_ENTRY_CENTS,
        GOVERNED_MAX_WEEKLY_ENTRY_CENTS,
        GOVERNED_MIN_WEEKLY_ENTRY_CENTS,
        resolve_weekly_entry_cents,
    )
    from db.schema import LeagueTreasury, PoolConfig
    from economy.skunk import (
        DEFAULT_SKUNK_CONTRIBUTION_CENTS, DEFAULT_SKUNK_SEASON_MAXIMUM_CENTS,
    )
    from payments.economy_config import get_league_economy_stop

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail=f"League {league_id} not found")

    stop = get_league_economy_stop(league_id, db)

    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == league_id).first()
    frozen_at = getattr(cfg, "pool_weekly_entry_frozen_at", None) if cfg else None

    # The treasury row carries the league's OWN split; the module default is a
    # fallback, not the answer, so a configured league reports what it configured.
    treasury = (db.query(LeagueTreasury)
                .filter(LeagueTreasury.league_id == league_id).first())
    split = json.loads(treasury.payout_split_json) if treasury else [60, 30, 10]

    return LeagueSettingsOut(
        league_id=league_id,
        season=league.season,
        economy_stop=SettingsEconomyStopOut(
            weekly_min_cents=stop.weekly_min_cents,
            min_reserve_cents=stop.min_reserve_cents,
            reserve_cents=stop.reserve_cents,
            buyin_cents=stop.buyin_cents,
            editable=False,
        ),
        pool_entry=SettingsPoolEntryOut(
            cents=resolve_weekly_entry_cents(db, league_id=league_id),
            min_cents=GOVERNED_MIN_WEEKLY_ENTRY_CENTS,
            max_cents=GOVERNED_MAX_WEEKLY_ENTRY_CENTS,
            default_cents=GOVERNED_DEFAULT_WEEKLY_ENTRY_CENTS,
            frozen=frozen_at is not None,
            frozen_at=frozen_at.isoformat() if frozen_at else None,
            editable=frozen_at is None,
        ),
        skunk=SettingsSkunkOut(
            weekly_cents=DEFAULT_SKUNK_CONTRIBUTION_CENTS,
            season_maximum_cents=DEFAULT_SKUNK_SEASON_MAXIMUM_CENTS,
            editable=False,
        ),
        championship_split=SettingsChampionshipSplitOut(split=split, editable=False),
    )


@app.get("/league/{league_id}/settings", response_model=LeagueSettingsOut)
def league_settings_read(
    league_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """The league's governed settings, read from their authoritative sources.

    Readable by any member of the league — these are the rules everyone plays
    under, not commissioner-private state.
    """
    _assert_league_member(current_user, league_id, db)
    return _league_settings(db, league_id)


class PoolEntryUpdateRequest(BaseModel):
    cents: int


@app.put("/league/{league_id}/settings/pool-entry", response_model=LeagueSettingsOut)
def league_set_pool_entry(
    league_id: int,
    req:       PoolEntryUpdateRequest,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """Set the Standard Pool Bet — the ONE governed settings mutation in MVP.

    IT WRITES `pool_weekly_entry_cents`, NOT `weekly_entry_cents`, and that
    distinction is why this route exists at all. The legacy POST /pool/config
    writes `PoolConfig.weekly_entry_cents`, which belongs to the retired
    three-pot engine and defaults to 1000. The Rev 4.2 Standard Pool Bet is
    `pool_weekly_entry_cents` — bounded $1–$5 by a schema CHECK and frozen at
    the season's first collection. Binding the Rev 4.2 control to the legacy
    route would have written a column nothing reads and displayed a figure
    nothing honours.

    NO SECOND IMPLEMENTATION. The governed bounds, the freeze refusal and the
    validation all live in `betting/pool_funding.configure_pool_weekly_entry`
    and stay there. This route resolves authority, calls it, and commits.
    """
    from betting.pool_funding import PoolFundingError, configure_pool_weekly_entry

    try:
        configure_pool_weekly_entry(db, league_id=league_id, cents=req.cents)
    except PoolFundingError as e:
        # 409 for the freeze: the request is well-formed and the caller is
        # authorized, but the season has moved past the point where this may
        # change. 400 for an out-of-bounds value, which is a bad request.
        status_code = 409 if e.reason == "ENTRY_FROZEN" else 400
        raise HTTPException(status_code=status_code,
                            detail={"reason_code": e.reason, "message": str(e)})
    db.commit()
    return _league_settings(db, league_id)


# ── The authoritative weekly Pool slate (S8-P4) ──────────────────────────────

class PoolSlotOut(BaseModel):
    slot:            int
    definition_key:  str
    catalog_number:  Optional[int]
    display_name:    Optional[str]
    category:        Optional[str]
    scope:           Optional[str]
    #: The definition's own settle condition, for the Pool detail surface.
    #: Carried from the catalog rather than restated, so a card and the
    #: definition it names cannot describe different rules.
    metric_expression: Optional[str]
    is_continuation: bool
    pot_cents:       int
    rollover_cents:  int
    settled:         bool


class PoolSlateOut(BaseModel):
    """One week's governed slate.

    `slots` is empty when no slate has been drawn. That is a real and currently
    ordinary state: the Rev1.3 selector requires four definitions passing BOTH
    gates, and gate 2 is a per-league, per-provider source measurement that is
    unsatisfied without provider access. An empty slate is reported as empty and
    the UI draws it unresolved, rather than four Pools being invented to fill
    the row.
    """
    league_id:        int
    season:           int
    week:             int
    slot_count:       int
    slots:            list[PoolSlotOut]
    drawn:            bool


@app.get("/league/{league_id}/pool/slate/{week}", response_model=PoolSlateOut)
def league_pool_slate(
    league_id:    int,
    week:         int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """The governed Pool occurrences for one week, from persisted state.

    READS, NEVER DRAWS. Drawing a slate is an economic act — it opens pots and
    consumes definitions from the rotation cycle — and belongs to the weekly
    collection path inside its own transaction. A read route that drew on
    demand would let any GM refreshing a tab advance the league's rotation.

    THE SLATE IS THE AUTHORITY ON WHICH POOLS A WEEK HAS. It is drawn from the
    Rev1.3 rotating catalog by `betting/pool_slate.build_and_persist_slate`;
    this returns what that persisted, joined to the catalog for display names.
    Continuations occupy slots and are flagged — a carried pot is a slot state,
    never a fifth Pool and never a second category.
    """
    from betting.pool_rotation import DEFAULT_SLOT_COUNT
    from db.schema import PoolDefinition, PoolInstance

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail=f"League {league_id} not found")

    _assert_league_member(current_user, league_id, db)

    rows = (db.query(PoolInstance)
            .filter(PoolInstance.league_id == league_id,
                    PoolInstance.season == league.season,
                    PoolInstance.week == week)
            .order_by(PoolInstance.slot)
            .all())

    definitions = {
        d.key: d for d in db.query(PoolDefinition).filter(
            PoolDefinition.key.in_([r.definition_key for r in rows])).all()
    } if rows else {}

    return PoolSlateOut(
        league_id=league_id,
        season=league.season,
        week=week,
        slot_count=DEFAULT_SLOT_COUNT,
        drawn=bool(rows),
        slots=[
            PoolSlotOut(
                slot=r.slot,
                definition_key=r.definition_key,
                catalog_number=getattr(definitions.get(r.definition_key),
                                       "catalog_number", None),
                display_name=getattr(definitions.get(r.definition_key),
                                     "display_name", None),
                category=getattr(definitions.get(r.definition_key),
                                 "category", None),
                scope=getattr(definitions.get(r.definition_key), "scope", None),
                metric_expression=getattr(definitions.get(r.definition_key),
                                          "metric_expression", None),
                # A continuation is recorded by origin, not by a flag: a carried
                # instance points at the pot it came from.
                is_continuation=r.origin_instance_id is not None,
                pot_cents=int(r.pot_cents or 0),
                rollover_cents=int(r.rollover_cents or 0),
                settled=bool(r.settled),
            )
            for r in rows
        ],
    )


# ── Week lifecycle — Weekly Minimum release and expiry ────────────────────────
#
# WHY THESE ROUTES EXIST. `economy/weekly_minimum.py` was certified at S5-P1 and
# has carried the whole release/expiry lifecycle since, but nothing outside the
# test suites ever called it. The consequence was not cosmetic. Season
# allocation posts a GM's opening 220 Credits to `min_reserve:{team}` (140) and
# `reserve:{team}` (80) and leaves `wallet:{team}` at zero, and every spend path
# — challenge funding and Pool entry alike — sources min-first through
# `economy.spend_sourcing`. With no release, `min:{team}:{week}` is always zero,
# the spend falls through to an empty Wallet, and a GM cannot fund anything at
# all. The engine was complete; only the trigger was missing.
#
# EXPLICIT COMMISSIONER TRIGGER, NOT A SCHEDULER. The certified design describes
# release at week open and expiry at week close. No scheduler, job runner or
# cron surface exists anywhere in this baseline, and inventing one here would be
# infrastructure work smuggled into a wiring change. These are therefore
# explicit commissioner actions on the existing authority model. If a scheduler
# is added later it calls these same service functions; nothing here forecloses
# that.
#
# THE SERVICE FUNCTIONS ARE UNCHANGED. `release_week` and `expire_week` already
# hold per-team savepoints, deterministic lock ordering and duplicate-event
# keys, so idempotency, league scoping and no-double-issuance are properties of
# the certified engine rather than of these routes. The routes add exactly two
# things the engine deliberately leaves to its caller: authorization and the
# commit.

class WeeklyMinimumTeamOut(BaseModel):
    team_id:  int
    cents:    int
    replayed: bool = Field(..., description="True when this team was already processed for this week.")


class WeekOpenOut(BaseModel):
    league_id:            int
    week:                 int
    teams:                list[WeeklyMinimumTeamOut]
    total_released_cents: int
    already_open:         bool = Field(..., description="True when every team replayed — the week was already open.")


class SkunkEntryOut(BaseModel):
    """One skunked GM and the matchup that skunked them."""
    team_id:            int
    team_name:          str
    score:              float
    opponent_team_id:   int
    opponent_team_name: str
    opponent_score:     float
    margin:             float
    cents:              int


class WeeklySkunkOut(BaseModel):
    """One league-week's Skunk outcome, as the product reports it.

    `assessed=False` means Week Close has not run for this week — NOT that
    nobody was skunked. The two are different facts and a surface that showed
    "no Skunk" for an unassessed week would be stating a result nobody measured.
    """
    league_id:      int
    season:         int
    week:           int
    assessed:       bool
    classification: Optional[str]
    amount_cents:   int
    assessed_at:    Optional[str]
    entries:        list[SkunkEntryOut]
    #: True when this Week Close found the assessment already recorded. The
    #: money did not move again; the outcome reported is the original one.
    replayed:       bool = False


class WeekCloseOut(BaseModel):
    league_id:           int
    week:                int
    teams:               list[WeeklyMinimumTeamOut]
    total_expired_cents: int
    already_closed:      bool = Field(..., description="True when every team replayed — the week was already closed.")
    #: WP6A — the week's Skunk outcome, assessed as part of this close. Null for
    #: a week that carries no Skunk obligation at all: a postseason week, or a
    #: week with no matchups scheduled. Both exclusions are the season-close
    #: orchestrator's own, not new rules — see the route.
    skunk:               Optional[WeeklySkunkOut] = None


@app.post("/league/{league_id}/week/{week}/open", response_model=WeekOpenOut)
def open_week(
    league_id: int,
    week:      int,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """Release every team's Weekly Minimum for one week of one league.

    Idempotent by construction: each team's release carries a deterministic
    event key, so a repeated call returns `replayed=True` for teams already
    released and posts nothing. A partially-completed earlier run resumes
    cleanly — the teams that succeeded replay, the teams that did not are
    released now.

    Refuses a postseason week rather than releasing into it. The Weekly Minimum
    is a regular-season obligation; releasing in week 15+ would hand a GM
    spendable Credits the season model never allocated.
    """
    from db.schema import League
    from economy.weekly_minimum import (
        WeeklyMinimumError, is_release_week, release_week,
    )

    if not 1 <= week <= 17:
        raise HTTPException(status_code=400, detail="week must be 1–17")

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail={
            "reason_code": "league_not_found",
            "message": f"League {league_id} not found."})

    if not is_release_week(league, week):
        raise HTTPException(status_code=400, detail={
            "reason_code": "not_applicable_week",
            "message": (f"Week {week} is not a governed regular-season week for "
                        f"league {league_id}; no Weekly Minimum is released.")})

    try:
        results = release_week(db, league_id=league_id, week=week)
    except WeeklyMinimumError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "reason_code": exc.reason, "message": str(exc)})

    db.commit()
    return WeekOpenOut(
        league_id=league_id, week=week,
        teams=[WeeklyMinimumTeamOut(team_id=r.team_id, cents=r.released_cents,
                                    replayed=r.replayed) for r in results],
        total_released_cents=sum(r.released_cents for r in results),
        already_open=bool(results) and all(r.replayed for r in results),
    )


@app.get("/league/{league_id}/week/{week}/skunk", response_model=WeeklySkunkOut)
def league_week_skunk(
    league_id:    int,
    week:         int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
):
    """One league-week's Skunk outcome — the read behind SKUNK OF THE WEEK.

    READABLE BY ANY MEMBER, not just the commissioner. The Skunk is the week's
    headline result and every GM in the league sees it; what a GM cannot do is
    CAUSE one, and that is enforced on Week Close rather than here.

    IT DECIDES NOTHING. The economic decision is the persisted assessment event;
    this names the teams and scores behind it, from the same finalized matchup
    rows the engine read. The browser is therefore never in a position to work
    out who was skunked — it is told.
    """
    from reports.weekly_skunk import weekly_skunk_result

    _assert_league_member(current_user, league_id, db)

    if not 1 <= week <= 17:
        raise HTTPException(status_code=400, detail="week must be 1–17")

    return _skunk_out(weekly_skunk_result(db, league_id=league_id, week=week),
                      replayed=False)


# PLACED IMMEDIATELY ABOVE WEEK CLOSE, and the position is load-bearing for a
# control rather than for taste. S8-P2 asserts that no GET route changes state
# by slicing each route decorator to the NEXT one and scanning that slice for
# mutation verbs. A GET sitting last before a long stretch of module-level code
# swallows all of it, and the Pool-lifecycle prose further down names several of
# those verbs while describing them — which reported this pure read as a
# state-changing GET. Sitting above the close route bounds the slice to this
# function, which is what the control is actually asking about.
#
# The verbs are not repeated here for the same reason.
@app.post("/league/{league_id}/week/{week}/close", response_model=WeekCloseOut)
def close_week(
    league_id: int,
    week:      int,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """End-of-week reconciliation — assess the Skunk, then expire the minimum.

    WP6A MADE THIS THE SKUNK'S HOME, AND IT HAS NO OTHER ONE. WP5 proved that
    `economy.skunk.assess_weekly_skunk` was certified and called by nothing, so a
    league that actually played a week could never satisfy the season-close
    precondition `skunk_assessed` — Week Close succeeded, left the week
    unassessed, and the season was then unclosable with no product path to fix
    it. The owner ruling is that Skunk is not a separate commissioner chore but
    part of end-of-week reconciliation, so it is assessed HERE and there is
    deliberately no ordinary "assess Skunk" button anywhere.

    THE ORDER, AND WHY IT IS THIS ORDER:

        authorization              `require_league_commissioner`, before any work
        week bounds                a malformed week never reaches an engine
        SKUNK ASSESSMENT           finality-gated; raises before it writes
        weekly minimum expiry      the existing close work
        ONE commit                 both effects, or neither

    SKUNK GOES FIRST BECAUSE IT IS THE ONE THAT CAN REFUSE. `determine_skunk_losers`
    raises RESULTS_NOT_READY on any matchup whose `finalized_at` is NULL, before
    a single posting. Running expiry first would mean a refused close had already
    moved every team's unspent minimum out of circulation — the partially closed
    week the brief forbids. Assessed first, a refusal costs nothing.

    FINALITY IS NOT RE-IMPLEMENTED HERE. The gate is the engine's own, on its own
    predicate (`finalized_at IS NOT NULL`). This route adds no second opinion
    about what "final" means, for the same reason the Pool settlement route
    refuses to: two definitions of final drift apart.

    WHICH WEEKS CARRY A SKUNK AT ALL — MIRRORED FROM THE ORCHESTRATOR, NOT
    INVENTED. `verify_preconditions` derives its `played_weeks` as the weeks that
    HAVE matchup rows, at or below `min(final_week, playoff_start_week - 1)`, and
    demands an assessment for exactly those. So this route assesses exactly
    those:

        · a POSTSEASON week carries no Skunk — the engine says so itself
          (NOT_REGULAR_SEASON) and the orchestrator never asks for one;
        · a week with NO MATCHUPS is not a played week — nothing was scheduled,
          the orchestrator does not list it, and refusing to close it would
          strand a league whose provider published no fixtures.

      Both exclusions come from the governed rule that already existed. Widening
      or narrowing either here would put this route and season close into
      disagreement about which weeks need assessing, which is precisely the class
      of defect WP5 found.

    A REPEATED CLOSE MOVES NOTHING TWICE. The assessment carries a deterministic
    league-week event key, so a second call collides on it. The collision is
    caught on a SAVEPOINT — the same isolation `release_week` uses per team — so
    the duplicate posting made inside that savepoint is discarded while the
    expiry work that follows still proceeds. Reporting the original outcome then
    costs one read and tells the commissioner what actually stands.
    """
    from economy.economy_events import DuplicateEconomyEvent
    from economy.skunk import SkunkError, assess_weekly_skunk
    from economy.weekly_minimum import WeeklyMinimumError, expire_week
    from reports.weekly_skunk import weekly_skunk_result

    if not 1 <= week <= 17:
        raise HTTPException(status_code=400, detail="week must be 1–17")

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail={
            "reason_code": "league_not_found",
            "message": f"League {league_id} not found."})

    skunk_out: Optional[WeeklySkunkOut] = None
    if _week_carries_skunk(db, league=league, league_id=league_id, week=week):
        replayed = False
        savepoint = db.begin_nested()
        try:
            assess_weekly_skunk(db, league_id=league_id, week=week)
            savepoint.commit()
        except DuplicateEconomyEvent:
            # Already assessed. The savepoint discards this call's posting; the
            # original stands and the close continues.
            savepoint.rollback()
            replayed = True
        except SkunkError as exc:
            # NOTHING IS PARTIALLY CLOSED. The refusal happens before expiry has
            # run at all, and the outer rollback discards the whole attempt.
            savepoint.rollback()
            db.rollback()
            raise HTTPException(status_code=409, detail={
                "reason_code": exc.reason,
                "message": str(exc),
                "league_id": league_id,
                "week": week})

        db.flush()
        skunk_out = _skunk_out(weekly_skunk_result(db, league_id=league_id,
                                                   week=week),
                               replayed=replayed)

    try:
        results = expire_week(db, league_id=league_id, week=week)
    except WeeklyMinimumError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "reason_code": exc.reason, "message": str(exc)})

    db.commit()
    return WeekCloseOut(
        league_id=league_id, week=week,
        teams=[WeeklyMinimumTeamOut(team_id=r.team_id, cents=r.expired_cents,
                                    replayed=r.replayed) for r in results],
        total_expired_cents=sum(r.expired_cents for r in results),
        already_closed=bool(results) and all(r.replayed for r in results),
        skunk=skunk_out,
    )


def _week_carries_skunk(db: Session, *, league, league_id: int,
                        week: int) -> bool:
    """Whether this league-week is one the season close will demand a Skunk for.

    Read from the same two facts `verify_preconditions` uses — the week is
    regular season, and matchups exist for it — so the two can never disagree
    about which weeks need assessing.
    """
    from betting.pool_season_boundary import playoff_start_week
    from db.schema import Matchup

    if week >= playoff_start_week(league):
        return False
    return (db.query(Matchup)
            .filter(Matchup.league_id == league_id,
                    Matchup.week == week).count()) > 0


def _skunk_out(result, *, replayed: bool) -> WeeklySkunkOut:
    """Map the read model to the wire shape. No decision, no arithmetic."""
    return WeeklySkunkOut(
        league_id=result.league_id, season=result.season, week=result.week,
        assessed=result.assessed, classification=result.classification,
        amount_cents=result.amount_cents, assessed_at=result.assessed_at,
        entries=[SkunkEntryOut(
            team_id=e.team_id, team_name=e.team_name, score=e.score,
            opponent_team_id=e.opponent_team_id,
            opponent_team_name=e.opponent_team_name,
            opponent_score=e.opponent_score, margin=e.margin, cents=e.cents,
        ) for e in result.entries],
        replayed=replayed,
    )


# ── Governed Rev1.3 Pool lifecycle — collection and settlement ────────────────
#
# WHY BOTH ROUTES. The governed Pool path had NO production entry point at
# either end. `betting/pool_funding.collect_weekly_entries` and
# `betting/pool_settlement.settle_week` are certified and tested, and neither
# had a non-test caller. The only mounted Pool economic routes were the LEGACY
# `/pool/collect` and `/pool/settle`, which `betting/pool_legacy_guard.py`
# refuses the moment a league holds any `pool_instance` row. So a league on the
# governed rotation could neither open a week's Pools nor settle them: the
# legacy routes fail closed and the governed engine was unreachable. Settlement
# alone would have been useless — there would be nothing to settle.
#
# THE LEGACY ENGINE IS NOT USED HERE, and is not retired here either. These
# routes call the Rev1.3 chain directly. The legacy interlock is untouched and
# keeps doing its job for leagues that never crossed over.
#
# THE STAT SOURCE IS THE REAL ONE. Settlement reconstructs the week's provider
# snapshot through the WP2A assembly — transport, parse, normalize, roster
# fetch — binds the certified identity resolver, and hands
# `YahooProviderStatSource` to the certified settlement engine. No mock, no
# synthetic stat object, no direct Yahoo call from settlement code.

#: Transport factory for the settlement path. A seam, not a configuration
#: surface: production gets the live transport, and the certification suites
#: substitute FixtureTransport so settlement is provable offline with no
#: credentials. Same shape tuesday_sync uses for the same reason.
def _pool_settlement_transport():
    from providers.yahoo.transport import YahooLiveTransport

    return YahooLiveTransport()


class PoolActivationOut(BaseModel):
    league_id:              int
    provider:               str
    week_measured:          int
    definitions_measured:   int
    definitions_ready:      int
    supported_stats:        list[str]
    eligible_this_phase:    int
    sufficient_for_slate:   bool
    measured_at:            Optional[str]


@app.post("/league/{league_id}/pool/activate", response_model=PoolActivationOut)
def activate_league_pool_support(
    league_id: int,
    week:      int = Query(..., ge=1, le=17,
                           description="Provider week to measure support from."),
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """Measure and persist this league's Pool source readiness — gate 2.

    LEAGUE SETUP, NOT WEEKLY PLAY. Which governed Pools a league can run depends
    on what its provider actually reports for it, and that is a property of the
    league's provider binding rather than of any one week's gameplay. It sits
    with the other Rules & Settings league configuration.

    IT IS COMMISSIONER-TRIGGERED BECAUSE NOTHING ELSE COULD TRIGGER IT. There is
    no onboarding pipeline and no scheduler in this baseline. Rather than invent
    one, this exposes the certified measurement as an explicit action. A future
    scheduler calls the same function.

    MEASURED SUPPORT ONLY. `measure_league_activation` reads what the snapshot
    ACTUALLY carried, not what the vocabulary says Yahoo can carry. A payload
    that arrived with no stat categories measures nothing and produces
    `ready=False` with the missing stats named — reaching the provider is not
    readiness. Nothing here weakens that: this route reports the gate's answer
    and never overrides it.
    """
    from betting.pool_gates import selectable_definitions
    from betting.pool_season_boundary import PHASE_REGULAR
    from providers.errors import ProviderError
    from providers.yahoo.identity import build_team_identity_resolver
    from providers.yahoo.pool_source import PROVIDER, measure_league_activation
    from providers.yahoo.week_snapshot import fetch_week_snapshot

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail={
            "reason_code": "league_not_found",
            "message": f"League {league_id} not found."})
    if not league.provider_league_key:
        raise HTTPException(status_code=409, detail={
            "reason_code": "no_provider_identity",
            "message": (f"League {league_id} carries no provider league key, so "
                        f"its Pool support cannot be measured.")})

    try:
        snapshot = fetch_week_snapshot(
            _pool_settlement_transport(),
            league_key=league.provider_league_key, week=week,
            with_rosters=True)
        resolver = build_team_identity_resolver(db, league_id=league_id)
    except ProviderError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail={
            "reason_code": "provider_unavailable",
            "message": f"{type(exc).__name__}: {exc}"})

    report = measure_league_activation(db, league_id=league_id,
                                       snapshot=snapshot, resolver=resolver)
    db.commit()

    # THE RETURN CONTRACT, READ FROM THE IMPLEMENTATION, NOT INFERRED.
    # measure_league_activation returns a SUMMARY of exactly four keys:
    #
    #   measured_at      the instant the measurement is stamped with
    #   supported_stats  sorted canonical stats this payload actually carried
    #   definitions      {definition_key: (ready: bool, block_reasons: tuple)}
    #   ready_count      count of ready definitions
    #
    # An earlier draft used len(report) as the definition count and got 4 — the
    # number of SUMMARY KEYS — and derived readiness by walking the wrong level,
    # reporting a confident 0. Subscripting the documented keys means a future
    # change to the contract raises KeyError here instead of quietly producing a
    # plausible wrong number.
    definitions = report["definitions"]
    ready_count = report["ready_count"]
    measured_at = report["measured_at"]

    eligible = selectable_definitions(db, league_id=league_id,
                                      provider=PROVIDER, phase=PHASE_REGULAR)

    return PoolActivationOut(
        league_id=league_id, provider=PROVIDER, week_measured=week,
        definitions_measured=len(definitions),
        definitions_ready=ready_count,
        supported_stats=list(report["supported_stats"]),
        eligible_this_phase=len(eligible),
        # POR §4.1: a week's slate needs four fully supported definitions.
        sufficient_for_slate=len(eligible) >= 4,
        measured_at=measured_at.isoformat() if measured_at else None,
    )


class PoolCollectionOut(BaseModel):
    league_id:                       int
    season:                          int
    week:                            int
    weekly_entry_cents:              int
    teams_charged:                   int
    total_cents:                     int
    per_pool_share_cents:            int
    remainder_to_championship_cents: int
    rotation_cycle:                  int
    instance_ids:                    list[int]


class PoolInstanceSettlementOut(BaseModel):
    """Mirrors `betting.pool_settlement.SettlementResult` field for field.

    Read straight off the dataclass rather than through defaulted getattr:
    a tolerant mapping would have reported a confident 0 for any field whose
    name drifted, which is the one failure mode a settlement response must not
    have.
    """
    pool_instance_id:            int
    definition_key:              str
    classification:              str
    winning_team_ids:            list[int]
    pot_cents:                   int
    distributed_cents:           int
    rolled_over_cents:           int
    swept_to_championship_cents: int
    replayed:                    bool


class PoolWeekSettlementOut(BaseModel):
    league_id:              int
    week:                   int
    settled:                list[PoolInstanceSettlementOut]
    refused:                list[str]
    week_container_settled: bool
    all_settled:            bool


@app.post("/league/{league_id}/pool/collect/{week}", response_model=PoolCollectionOut)
def collect_governed_pool_week(
    league_id: int,
    week:      int,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """Open and fund one week's governed Pools — the Rev1.3 collection path.

    Draws the four-occurrence slate from the rotating catalog, debits every
    wallet once, credits `pool:{league_id}`, moves the indivisible remainder to
    championship and divides the share across the occurrences — all in one
    transaction, in the order Scope §E fixes.

    The week claim is atomic, so a repeated call is refused rather than
    double-charging. Collection also refuses while ANY earlier week is
    unsettled, which is the engine's own guard against stale money sitting in
    the shared pool account and polluting later conservation checks.
    """
    from betting.pool_funding import PoolFundingError, collect_weekly_entries

    if not 1 <= week <= 17:
        raise HTTPException(status_code=400, detail="week must be 1–17")

    try:
        result = collect_weekly_entries(db, league_id=league_id, week=week)
        db.commit()
    except PoolFundingError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "reason_code": getattr(exc, "reason", "pool_funding_refused"),
            "message": str(exc)})

    return PoolCollectionOut(
        league_id=result.league_id, season=result.season, week=result.week,
        weekly_entry_cents=result.weekly_entry_cents,
        teams_charged=result.teams_charged, total_cents=result.total_cents,
        per_pool_share_cents=result.per_pool_share_cents,
        remainder_to_championship_cents=result.remainder_to_championship_cents,
        rotation_cycle=result.rotation_cycle,
        instance_ids=list(result.instance_ids),
    )


@app.post("/league/{league_id}/pool/settle/{week}",
          response_model=PoolWeekSettlementOut)
def settle_governed_pool_week(
    league_id: int,
    week:      int,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """Settle every governed Pool occurrence of one week.

    THE CHAIN, END TO END: this route -> provider snapshot reconstruction
    (`fetch_week_snapshot`, with rosters) -> identity binding
    (`bind_pool_stat_source`) -> `YahooProviderStatSource` ->
    `betting.pool_settlement.settle_week` -> ledger postings -> persisted
    `settled` state the slate route already reads.

    FINALITY IS THE ENGINE'S, NOT THIS ROUTE'S. `settle_week` consults
    `betting/finality_gate.require_week_final`, whose one predicate is
    `Matchup.finalized_at IS NOT NULL`. This route deliberately does not
    pre-check finality: a second, weaker copy of that rule here is exactly how
    two definitions of "final" drift apart.

    IDEMPOTENT BECAUSE THE ENGINE READS PERSISTED STATE. `settle_week` skips
    instances whose `settled` column is already true and re-marks the week
    container from the remaining count, so a repeated call settles nothing
    further and cannot pay twice. Per-instance savepoints mean one governed
    refusal cannot roll back a sibling that already posted.
    """
    from betting.pool_settlement import PoolSettlementError
    from providers.errors import ProviderError
    from providers.yahoo.week_snapshot import (
        bind_pool_stat_source, fetch_week_snapshot,
    )

    if not 1 <= week <= 17:
        raise HTTPException(status_code=400, detail="week must be 1–17")

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail={
            "reason_code": "league_not_found",
            "message": f"League {league_id} not found."})
    if not league.provider_league_key:
        raise HTTPException(status_code=409, detail={
            "reason_code": "no_provider_identity",
            "message": (f"League {league_id} carries no provider league key; "
                        f"its Pools cannot be settled from provider data.")})

    try:
        snapshot = fetch_week_snapshot(
            _pool_settlement_transport(),
            league_key=league.provider_league_key, week=week,
            with_rosters=True)
        stat_source = bind_pool_stat_source(db, snapshot, league_id=league_id)
    except ProviderError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail={
            "reason_code": "provider_unavailable",
            "message": f"{type(exc).__name__}: {exc}"})

    try:
        from betting.pool_settlement import settle_week as settle_governed_week

        result = settle_governed_week(db, league_id=league_id, week=week,
                                      stat_source=stat_source)
        db.commit()
    except ResultsNotReadyError as exc:
        # WP2B-D — THE REFUSAL WAS ALWAYS CORRECT; ITS HTTP SHAPE WAS NOT.
        #
        # `betting.finality_gate.require_week_final` refuses inside the engine
        # before any economic work, so a non-final week already moved no money
        # and left every occurrence unsettled. What it did NOT have was a
        # client-visible shape: ResultsNotReadyError is a plain ValueError and
        # not a member of the `PoolSettlementRefusedError` family, so it fell
        # through to the bare `except Exception: raise` below and surfaced as an
        # unhandled 500. An operator saw a server error where the server had in
        # fact made a correct, governed, retryable decision.
        #
        # 409 CONFLICT, AND THE REASON CODE IS THE ENGINE'S OWN. `exc.reason` is
        # the accepted `RESULTS_NOT_READY` vocabulary that economy/skunk.py and
        # economy/season_close_orchestrator.py already name their refusal after,
        # and it is passed through rather than restated — exactly as the Week
        # Open / Week Close and governed collection routes pass through
        # `exc.reason`. Coining a route-local string here would leave operators
        # matching on two names for one condition, which is the specific thing
        # the finality gate's own docstring argues against.
        #
        # NOTHING ABOUT FINALITY CHANGES HERE. `finalized_at` remains the sole
        # predicate, the gate still lives in the engine, and this route still
        # does not pre-check it — a second, weaker copy of that rule at the
        # boundary is how two definitions of "final" drift apart.
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "reason_code": exc.reason,
            "message": str(exc),
            "league_id": exc.league_id,
            "week": exc.week,
            # The offending rows, so the answer to "why can I not settle?" is
            # WHICH GAME rather than a generic refusal. The exception already
            # carries them for exactly this purpose.
            "unfinalized_matchup_ids": list(exc.unfinalized_matchup_ids),
        })
    except PoolSettlementError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "reason_code": "pool_settlement_refused", "message": str(exc)})
    except Exception:
        db.rollback()
        raise

    return PoolWeekSettlementOut(
        league_id=result.league_id, week=result.week,
        settled=[
            PoolInstanceSettlementOut(
                pool_instance_id=s.pool_instance_id,
                definition_key=s.definition_key,
                classification=s.classification,
                winning_team_ids=list(s.winning_team_ids),
                pot_cents=s.pot_cents,
                distributed_cents=s.distributed_cents,
                rolled_over_cents=s.rolled_over_cents,
                swept_to_championship_cents=s.swept_to_championship_cents,
                replayed=s.replayed,
            ) for s in result.settled
        ],
        refused=[str(r) for r in result.refused],
        week_container_settled=result.week_container_settled,
        all_settled=result.all_settled,
    )


# ══════════════════════════════════════════════════════════════════════════════
# WP3 — SEASON CLOSE
# ══════════════════════════════════════════════════════════════════════════════
#
# THE GAP THIS CLOSES. `economy/season_close_orchestrator.close_season_economy`
# is the certified sixteen-step close: nine pure-read preconditions, then the
# reserve sweep, Skunk, the 60/30/10 Championship distribution, the expired
# Weekly Minimum reconciliation, the derived Current Settle, the account-level
# zero assertions, the global trial balance and finally the irreversible
# `close_season()` stamp. Every step was certified by test_s5_p3_season_close_pg
# — and NOTHING CALLED IT. `economy/season_close.py` says so in its own scope
# fence: "routes — nothing in this module is registered in api/main.py". So a
# league could reach the end of its season and had no way to close it: the money
# in `championship:{league_id}` was unreachable and the expired Weekly Minimum
# sat in `expired_min:{team}` forever.
#
# WP3 ADDS THE COMMISSIONER ACTION AND NOTHING ELSE. No step is added, removed,
# reordered or weakened; no precondition is relaxed; no arithmetic is
# reimplemented. This route is a caller.
#
# TWO INPUTS ARE DELIBERATELY NOT ACCEPTED FROM THE CLIENT, and each would be a
# real money defect if they were:
#
#   final_week       decides `cutoff` inside verify_preconditions, which decides
#                    WHICH WEEKS are checked for Weekly Minimum expiry and Skunk
#                    assessment. A commissioner who passed final_week=1 would
#                    skip every later week's checks and close over unsettled
#                    money. It is read from the league's own
#                    `season_final_week`.
#
#   standings_order  decides who receives 60% of the Championship pot. Accepting
#                    it from the caller would let a commissioner name themselves
#                    first. It is left None so the orchestrator derives it from
#                    posted results via `default_standings_order`.
#
# THE OPERATOR IS THE AUTHENTICATED COMMISSIONER. §9.2 requires the close writer
# to report operator identity in its return value and defines no audit table for
# it; the identity passed here is the caller's own, never a constant.


class SeasonCloseChampionshipPlacementOut(BaseModel):
    place:   int
    team_id: int
    pct:     int
    cents:   int


class SeasonCloseOut(BaseModel):
    """Mirrors `SeasonCloseReport` field for field, plus the close stamp.

    `closed_now` and `replayed` are BOTH reported and they are different facts:
    `closed_now` means this call wrote the timestamp, `replayed` means the season
    was already closed when the call arrived and the orchestrator returned
    without re-posting. A single boolean could not distinguish them.
    """
    league_id:                  int
    season:                     int
    closed_now:                 bool
    replayed:                   bool
    season_closed_at:           Optional[str]
    operator:                   str
    final_week:                 int
    reserve_swept_cents:        int
    legacy_consolidated_cents:  int
    skunk_distributed_cents:    int
    championship_pot_cents:     int
    championship_placements:    list[SeasonCloseChampionshipPlacementOut]
    expired_min_returned_cents: int
    zero_assertions:            dict[str, int]
    current_settle:             dict[str, dict]


@app.post("/league/{league_id}/season/close", response_model=SeasonCloseOut)
def close_league_season(
    league_id: int,
    db:        Session = Depends(get_db),
    comm:      User    = Depends(require_league_commissioner),
):
    """Close one league's season — the terminal commissioner economic action.

    LEAGUE-SCOPED AUTHORIZATION, exactly as the Pool and Week routes use it.
    `require_league_commissioner` binds `league_id` from the path and refuses
    before any route work, so a commissioner of another league gets 403 and
    cannot use this route to learn whether a league exists, let alone close it.

    IT CANNOT CLOSE PREMATURELY, AND THIS ROUTE IS NOT WHAT STOPS IT.
    `verify_preconditions` runs all nine checks as pure reads before a single
    posting, and refuses naming the FIRST unmet one. Restating any of them here
    would put a second, weaker opinion about readiness in front of the real one.

    IDEMPOTENT BY THE STAMP, NOT BY A FLAG THIS ROUTE KEEPS.
    `close_season_economy` returns early when `is_season_closed` is already true,
    so a repeated close re-posts nothing and re-derives the per-GM position from
    posted state. `close_season()` additionally takes the League row FOR UPDATE
    as its first statement, so two concurrent closes cannot both stamp.

    TRANSACTION OWNERSHIP FOLLOWS THE ORCHESTRATOR'S CONTRACT. Steps 10-15 are
    written into this session and `close_season()` — called last — commits them
    together with the stamp. This route therefore does not commit on success; it
    rolls back on every refusal, which is safe because every refusal happens
    either before any posting (steps 1-9) or inside a step that raised before
    completing.
    """
    from betting.pool_season_boundary import season_final_week
    from economy.season_close import (
        LeagueNotFoundError, SeasonCloseConflictError,
    )
    from economy.season_close_orchestrator import (
        SeasonClosePreconditionError, close_season_economy,
    )
    from economy.season_reconciliation import SeasonReconciliationError
    from economy.skunk import SkunkError

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        # Not reachable through a granted authority — LeagueCommissioner.league_id
        # is a foreign key, so nobody holds authority for a league that is not
        # there. Named anyway rather than left to surface as an AttributeError.
        raise HTTPException(status_code=404, detail={
            "reason_code": "league_not_found",
            "message": f"League {league_id} not found."})

    final_week = season_final_week(league)
    operator = comm.email

    try:
        report = close_season_economy(db, league_id=league_id,
                                      final_week=final_week, operator=operator)
    except SeasonClosePreconditionError as exc:
        # THE STEP NAME IS THE REASON CODE, passed through rather than restated.
        # `exc.step` is already the orchestrator's own vocabulary — versus_terminal,
        # pool_settled, escrow_resolved, weekly_minimum_expiry, results_not_ready,
        # skunk_assessed, pool_rollover, pool_zero, provider_conflict,
        # conservation, trial_balance — and it exists precisely so an operator is
        # told WHAT TO FINISH. Collapsing eleven distinct causes into one route-
        # local string would throw that away.
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "reason_code": exc.step,
            "message": str(exc),
            "league_id": league_id,
            "final_week": final_week})
    except SeasonCloseConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "reason_code": "season_close_conflict", "message": str(exc)})
    except LeagueNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail={
            "reason_code": "league_not_found", "message": str(exc)})
    except (SeasonReconciliationError, SkunkError) as exc:
        # A reconciliation refusal that the orchestrator did not absorb — an
        # ambiguous legacy pot, an incomplete ranking, a placed team with no
        # wallet. Governed and named, so it maps like the rest rather than
        # falling through to the bare re-raise below.
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "reason_code": exc.reason, "message": str(exc)})
    except Exception:
        db.rollback()
        raise

    # Read the committed stamp back rather than reporting the instant this
    # process generated: on the replay path the authoritative timestamp is the
    # ORIGINAL close's, which this call never held.
    db.expire_all()
    closed_at = (db.query(League).filter(League.id == league_id).first()
                 .season_closed_at)

    return SeasonCloseOut(
        league_id=report.league_id,
        season=report.season,
        closed_now=report.closed_now,
        replayed=report.replayed,
        season_closed_at=closed_at.isoformat() if closed_at else None,
        operator=operator,
        final_week=final_week,
        reserve_swept_cents=report.reserve_swept_cents,
        legacy_consolidated_cents=report.legacy_consolidated_cents,
        skunk_distributed_cents=report.skunk_distributed_cents,
        championship_pot_cents=report.championship_pot_cents,
        championship_placements=[
            SeasonCloseChampionshipPlacementOut(
                place=place, team_id=team_id, pct=pct, cents=cents)
            for place, team_id, pct, cents in report.championship_placements
        ],
        expired_min_returned_cents=report.expired_min_returned_cents,
        zero_assertions={k: int(v) for k, v in report.zero_assertions.items()},
        current_settle={str(k): v for k, v in report.current_settle.items()},
    )


# ══════════════════════════════════════════════════════════════════════════════
# WP4 — THE LIFECYCLE READ MODEL
# ══════════════════════════════════════════════════════════════════════════════
#
# WHY A READ EXISTS AT ALL, WHEN WP4 IS A UI PACKAGE. Every lifecycle COMMAND was
# already mounted — activate, week open, collect, settle, week close, season
# close. What none of them had was a way to ask what the league's lifecycle state
# IS without performing the action. That gap is not cosmetic:
#
#   · "Pool support: Not measured / Insufficient / Ready" cannot be answered by
#     POST /pool/activate, because that route CALLS YAHOO and re-measures. Using
#     it as a read would make merely opening Rules & Settings a provider request
#     and a database write.
#   · "disable actions that are clearly already complete" needs to know whether
#     the week was opened, collected, settled or closed. Nothing published that.
#   · Season Close must stay unavailable until its governed prerequisites are
#     satisfied, and the browser must NOT be the thing that decides that. The
#     only way to have both is for the SERVER to answer the readiness question.
#
# NOTHING HERE IS A SECOND OPINION. Pool support is `selectable_definitions` —
# the same gate the slate builder draws from. Season readiness is
# `verify_preconditions` — the same nine pure-read checks `close_season_economy`
# runs, called by the same name, reporting the same `exc.step` vocabulary the
# close route already passes through. Week state is counted from the
# `EconomyEvent` rows the weekly-minimum services write and the `PoolInstance`
# rows the governed collection writes. No rule is restated, and no threshold is
# invented: if the engine's answer changes, this changes with it.
#
# IT WRITES NOTHING. `verify_preconditions` flushes as it reads, so the session
# is rolled back before returning — a readiness question must not leave a
# transaction behind it.
#
# COMMISSIONER-SCOPED, like every route it describes. A GM has no lifecycle
# controls, so there is nothing for them to read here, and refusing keeps the
# authority story identical across the read and the six commands.


class LifecyclePoolSupportOut(BaseModel):
    """Whether the provider's data supports this league's weekly Pool slate.

    `state` is the three-valued product answer, derived rather than stored:
    NOT_MEASURED means no measurement exists for this league at all, READY means
    the gate currently yields at least a full slate's worth of definitions, and
    INSUFFICIENT is a measurement that did not reach that bar — including one
    that has since gone STALE, which the gate fails closed on by design.
    """
    state:              str
    measured_at:        Optional[str]
    definitions_ready:  int
    eligible_for_slate: int
    required_for_slate: int
    provider:           str


class LifecycleWeekOut(BaseModel):
    week:            Optional[int]
    week_resolved:   bool
    is_release_week: bool
    teams:           int
    released_teams:  int
    expired_teams:   int
    opened:          bool
    closed:          bool
    pool_instances:  int
    pool_settled:    int
    collected:       bool
    settled:         bool
    #: WP6A — whether this week carries a Skunk obligation at all, and whether
    #: it has been discharged. Derived from the assessment EVENT, never from a
    #: guess about whether close "probably" ran: `skunk_required` mirrors the
    #: season-close orchestrator's own scoping, and `skunk_assessed` is the
    #: presence of the governed event. The browser decides neither.
    skunk_required:  bool
    skunk_assessed:  bool


class LifecycleSeasonOut(BaseModel):
    final_week:           Optional[int]
    closed:               bool
    closed_at:            Optional[str]
    ready:                bool
    blocking_reason_code: Optional[str]
    blocking_message:     Optional[str]


class LeagueLifecycleOut(BaseModel):
    league_id:    int
    season:       int
    pool_support: LifecyclePoolSupportOut
    week:         LifecycleWeekOut
    season_close: LifecycleSeasonOut


#: The product's three-valued Pool support answer.
POOL_SUPPORT_NOT_MEASURED = "not_measured"
POOL_SUPPORT_INSUFFICIENT = "insufficient"
POOL_SUPPORT_READY = "ready"


@app.get("/league/{league_id}/lifecycle", response_model=LeagueLifecycleOut)
def league_lifecycle_state(
    league_id: int,
    db:        Session = Depends(get_db),
    _comm:     User    = Depends(require_league_commissioner),
):
    """This league's lifecycle state — a pure read, written by nothing."""
    from betting.pool_gates import selectable_definitions
    from betting.pool_rotation import DEFAULT_SLOT_COUNT
    from betting.pool_season_boundary import PHASE_REGULAR, season_final_week
    from db.schema import EconomyEvent, PoolInstance, PoolLeagueActivation
    from economy.economy_events import (
        EVENT_WEEKLY_MINIMUM_EXPIRY, EVENT_WEEKLY_MINIMUM_RELEASE,
    )
    from economy.season_close import is_season_closed
    from economy.season_close_orchestrator import (
        SeasonClosePreconditionError, verify_preconditions,
    )
    from economy.season_reconciliation import SeasonReconciliationError
    from economy.skunk import SkunkError
    from economy.weekly_minimum import is_release_week
    from providers.yahoo.pool_source import PROVIDER

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail={
            "reason_code": "league_not_found",
            "message": f"League {league_id} not found."})

    # EVERY SCALAR IS READ OFF THE ROW BEFORE THE ROLLBACK BELOW, which would
    # otherwise expire the instance and make each later attribute a fresh query
    # against a session that has just been unwound.
    season = league.season
    final_week = season_final_week(league)
    season_closed = is_season_closed(league)
    season_closed_at = league.season_closed_at
    current_week = league.provider_current_week

    # ── Pool support ────────────────────────────────────────────────────────
    measurements = (db.query(PoolLeagueActivation)
                    .filter(PoolLeagueActivation.league_id == league_id,
                            PoolLeagueActivation.provider == PROVIDER).all())
    ready_rows = [m for m in measurements if m.league_activation_ready]
    stamps = [m.measured_at for m in measurements if m.measured_at]

    # THE GATE'S OWN ANSWER, not a recount of the rows above. `ready` on a row
    # is one input; `selectable_definitions` additionally applies Gate 1 and the
    # staleness window, and it is what the slate builder actually draws from.
    eligible = selectable_definitions(db, league_id=league_id,
                                      provider=PROVIDER, phase=PHASE_REGULAR)

    if not measurements:
        support_state = POOL_SUPPORT_NOT_MEASURED
    elif len(eligible) >= DEFAULT_SLOT_COUNT:
        support_state = POOL_SUPPORT_READY
    else:
        support_state = POOL_SUPPORT_INSUFFICIENT

    # ── The week ────────────────────────────────────────────────────────────
    teams = db.query(Team).filter(Team.league_id == league_id).count()

    def _event_teams(event_type: str) -> int:
        if current_week is None:
            return 0
        return (db.query(EconomyEvent)
                .filter(EconomyEvent.league_id == league_id,
                        EconomyEvent.season == season,
                        EconomyEvent.week == current_week,
                        EconomyEvent.event_type == event_type).count())

    released = _event_teams(EVENT_WEEKLY_MINIMUM_RELEASE)
    expired = _event_teams(EVENT_WEEKLY_MINIMUM_EXPIRY)

    instances = ([] if current_week is None else
                 db.query(PoolInstance)
                 .filter(PoolInstance.league_id == league_id,
                         PoolInstance.season == season,
                         PoolInstance.week == current_week).all())
    settled_instances = [i for i in instances if i.settled]

    # WP6A — the week's Skunk state, from the governed event and the same
    # scoping season close applies. `skunk_required=False` on a postseason or
    # unplayed week is an answer, not an omission: the orchestrator will not ask
    # for an assessment there either.
    skunk_required = (current_week is not None
                      and _week_carries_skunk(db, league=league,
                                              league_id=league_id,
                                              week=current_week))
    skunk_assessed = False
    if current_week is not None:
        from economy.economy_events import (
            EVENT_SKUNK_ASSESSMENT as _EV_SKUNK, league_week_key as _lw_key,
        )
        skunk_assessed = (db.query(EconomyEvent)
                          .filter(EconomyEvent.event_key
                                  == _lw_key(_EV_SKUNK, league_id, season,
                                             current_week))
                          .count()) > 0

    week_out = LifecycleWeekOut(
        week=current_week,
        week_resolved=current_week is not None,
        is_release_week=(current_week is not None
                         and is_release_week(league, current_week)),
        teams=teams,
        released_teams=released,
        expired_teams=expired,
        # "Opened" means EVERY team was released, which is exactly what
        # `already_open` reports on the command's own return value. A partially
        # completed run is not open, and reporting it as open would disable the
        # control that would finish it.
        opened=teams > 0 and released >= teams,
        closed=teams > 0 and expired >= teams,
        pool_instances=len(instances),
        pool_settled=len(settled_instances),
        collected=len(instances) > 0,
        settled=len(instances) > 0 and len(settled_instances) == len(instances),
        skunk_required=skunk_required,
        skunk_assessed=skunk_assessed,
    )

    # ── Season close readiness ──────────────────────────────────────────────
    #
    # THE ORCHESTRATOR'S OWN PRECONDITIONS, called rather than described. A
    # closed season is not "ready" — it is done, which `closed` says and `ready`
    # must not, or the UI would offer to close it again as though it might.
    ready = False
    blocking_code: Optional[str] = None
    blocking_message: Optional[str] = None

    if not season_closed:
        try:
            verify_preconditions(db, league_id=league_id, final_week=final_week)
            ready = True
        except SeasonClosePreconditionError as exc:
            blocking_code, blocking_message = exc.step, str(exc)
        except (SeasonReconciliationError, SkunkError) as exc:
            blocking_code, blocking_message = exc.reason, str(exc)
        finally:
            # A READ LEAVES NO TRANSACTION. verify_preconditions flushes as it
            # walks, and an un-rolled-back flush would ride out on the next
            # commit this session happens to make.
            db.rollback()

    return LeagueLifecycleOut(
        league_id=league_id,
        season=season,
        pool_support=LifecyclePoolSupportOut(
            state=support_state,
            measured_at=(max(stamps).isoformat() if stamps else None),
            definitions_ready=len(ready_rows),
            eligible_for_slate=len(eligible),
            required_for_slate=DEFAULT_SLOT_COUNT,
            provider=PROVIDER,
        ),
        week=week_out,
        season_close=LifecycleSeasonOut(
            final_week=final_week,
            closed=season_closed,
            closed_at=season_closed_at.isoformat() if season_closed_at else None,
            ready=ready,
            blocking_reason_code=blocking_code,
            blocking_message=blocking_message,
        ),
    )


# ── Decision Engine health routes ─────────────────────────────────────────────

from api.health_routes import router as health_router  # noqa: E402
app.include_router(health_router)

from api.war_room_routes import router as war_room_router  # noqa: E402
app.include_router(war_room_router)
from api.pool_routes import router as pool_router  # noqa: E402
app.include_router(pool_router)
