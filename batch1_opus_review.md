# Batch 1 — Opus Review

Extracted for review purposes only. Full function bodies, no partial snippets. Nothing in this file has been modified from source — see the originating file/line ranges noted under each header.

---

## 1. `api/main.py` — `POST /bets/place`

### Request/response schemas

```python
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
```

### Route

```python
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
```

### Helper functions called directly for validation or settlement

None. This route does not call `validate_bet_amount()`, `_place_bet()`, `settle_week()`, or any other validation/settlement helper from another module — every step (matchup lookup, wallet lookup, balance check, `Bet`/`Transaction` construction, win/loss determination, payout) is inlined directly in the route body above.

---

## 2. `GET /settle/{week}` and `settle_week()`

### `api/main.py` — response schemas

```python
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
```

### `api/main.py` — route

```python
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
```

Note: this route has no freshness/staleness gate of its own — it calls `settle_week()` directly, with only a `require_commissioner` auth dependency and a `1 <= week <= 17` range check ahead of it.

### `betting/settlement_engine.py` — `settle_week()`

```python
def settle_week(week: int, db: Session) -> SettlementReport:
    """Settle all pending bets whose matchup is in the given week."""
    now = datetime.now(timezone.utc)

    pending = (
        db.query(Bet)
        .join(Matchup)
        .filter(Matchup.week == week, Bet.status == "pending")
        .order_by(Bet.id)
        .all()
    )

    if not pending:
        return SettlementReport(week=week, total_bets=0, bets_won=0, bets_lost=0,
                                total_staked=0.0, total_payout=0.0)

    # Snapshot wallet balances before settlement
    wallet_ids    = {b.wallet_id for b in pending}
    wallets       = {w.id: w for w in db.query(Wallet).filter(Wallet.id.in_(wallet_ids)).all()}
    balance_before = {wid: wallets[wid].balance for wid in wallet_ids}

    settlements: list[BetSettlement] = []

    for bet in pending:
        matchup = bet.matchup

        # Resolve outcome -------------------------------------------------
        if bet.bet_type == "the_lineup":
            result = _eval_the_lineup(bet, db)
            if result == "push":
                status = "push"
                payout = bet.amount          # return stake, no profit
                profit = 0.0
            else:
                status = "won" if result == "won" else "lost"
                payout = round(bet.amount * bet.odds, 2) if status == "won" else 0.0
                profit = round(payout - bet.amount, 2)
        elif bet.beef_challenge_id is not None:
            # Beef bets compare weekly scores across different matchups
            result = _eval_beef(bet, db)
            if result == "push":
                status = "push"
                payout = bet.amount
                profit = 0.0
            else:
                status = "won" if result == "won" else "lost"
                payout = round(bet.amount * bet.odds, 2) if status == "won" else 0.0
                profit = round(payout - bet.amount, 2)
        else:
            evaluator = _EVALUATORS.get(bet.bet_type)
            if evaluator is None:
                continue
            result = evaluator(bet, matchup, db)
            if isinstance(result, str):   # prop: returns "won" | "lost" | "push"
                if result == "push":
                    status = "push"
                    payout = bet.amount
                    profit = 0.0
                else:
                    status = result
                    payout = round(bet.amount * bet.odds, 2) if status == "won" else 0.0
                    profit = round(payout - bet.amount, 2)
            else:                          # straight / spread / over_under: returns bool
                status = "won" if result else "lost"
                payout = round(bet.amount * bet.odds, 2) if result else 0.0
                profit = round(payout - bet.amount, 2)
        # -----------------------------------------------------------------

        bet.status     = status
        bet.settled_at = now

        wallet = wallets[bet.wallet_id]
        if status in ("won", "push"):   # push returns stake; won returns stake+profit
            wallet.balance = round(wallet.balance + payout, 2)
            db.add(Transaction(
                wallet_id  = bet.wallet_id,
                amount     = payout,
                type       = "payout",
                bet_id     = bet.id,
                created_at = now,
            ))

        settlements.append(BetSettlement(
            bet_id      = bet.id,
            bet_type    = bet.bet_type,
            description = bet.description or "",
            wallet_id   = bet.wallet_id,
            owner       = wallet.team.owner,
            team_name   = wallet.team.team_name,
            amount      = bet.amount,
            odds_dec    = bet.odds,
            payout      = payout,
            profit      = profit,
            status      = status,
        ))

    db.commit()
    log_settlement_events(pending, db)

    # Build wallet movement rows
    db.expire_all()
    wallet_movements: list[WalletMovement] = []
    for wid in sorted(wallet_ids):
        w = db.query(Wallet).filter(Wallet.id == wid).first()
        w_bets = [s for s in settlements if s.wallet_id == wid]
        wallet_movements.append(WalletMovement(
            wallet_id      = wid,
            team_name      = w.team.team_name,
            owner          = w.team.owner,
            balance_before = balance_before[wid],
            bets_won       = sum(1 for s in w_bets if s.status == "won"),
            bets_lost      = sum(1 for s in w_bets if s.status == "lost"),
            total_staked   = round(sum(s.amount  for s in w_bets), 2),
            total_payout   = round(sum(s.payout  for s in w_bets), 2),
            balance_after  = w.balance,
        ))

    won_count  = sum(1 for s in settlements if s.status == "won")
    lost_count = len(settlements) - won_count

    return SettlementReport(
        week          = week,
        total_bets    = len(settlements),
        bets_won      = won_count,
        bets_lost     = lost_count,
        total_staked  = round(sum(s.amount for s in settlements), 2),
        total_payout  = round(sum(s.payout for s in settlements), 2),
        settlements   = settlements,
        wallet_movements = wallet_movements,
    )
```

`settle_week()` has no internal freshness check of its own — it trusts the caller to have verified score/slate freshness before invoking it. `notifications/tuesday_sync.py`'s automated path enforces this via `_assert_slate_fresh()` (see below); `GET /settle/{week}` above does not.

---

## 3. `notifications/tuesday_sync.py` — `_assert_slate_fresh()` (for contrast)

```python
def _assert_slate_fresh(
    league_id: int,
    week: int,
    db: Session,
    *,
    yahoo_home_ids: set[int] | None = None,
    check_refreshed: bool = False,
) -> tuple[bool, str, int]:
    """
    Single source of truth for "is the matchup slate complete and refreshed?"

    Returns (is_fresh, reason, db_count).

    Always checks:
      - db_count > 0  (seed must have run)

    When yahoo_home_ids is provided (step 0 / _step_refresh_scores):
      - Checks exact set identity between DB home_team_ids and Yahoo's translated
        return, in both directions:
          missing = db_home_ids - yahoo_home_ids  (DB game Yahoo dropped)
          extra   = yahoo_home_ids - db_home_ids  (game Yahoo invented)
        Either non-empty set fails the gate.  Count equality alone does not
        pass — a duplicate plus a missing game has identical counts but fires
        both sets.
      - yahoo_home_ids contains DB IDs (after TeamResolver translation), so the
        comparison is in the same namespace as the DB query.

    When check_refreshed=True (step 1 self-guard / _step_settle_bets):
      - Checks that all matchup rows have refreshed_at IS NOT NULL.
      - NULL means _step_refresh_scores did not complete for that row.
      - Requires migration: migrations/add_matchup_refreshed_at.py.
      - Score values (0.0, etc.) are never used to infer freshness — only the
        timestamp is authoritative.  A genuine 0-0 final with a non-NULL
        refreshed_at is correctly treated as fresh.
    """
    from sqlalchemy import text

    rows = db.execute(
        text(
            "SELECT home_team_id, refreshed_at FROM matchups "
            "WHERE league_id = :lid AND week = :week"
        ),
        {"lid": league_id, "week": week},
    ).fetchall()

    db_count = len(rows)

    if db_count == 0:
        return (
            False,
            f"week {week}: no matchups in DB for league_id={league_id} — seed not run?",
            0,
        )

    if yahoo_home_ids is not None:
        db_home_ids = {row[0] for row in rows}
        missing     = db_home_ids - yahoo_home_ids  # DB games Yahoo dropped
        extra       = yahoo_home_ids - db_home_ids  # games Yahoo invented
        if missing or extra:
            parts: list[str] = []
            if missing:
                parts.append(f"missing from Yahoo: {sorted(missing)}")
            if extra:
                parts.append(f"invented by Yahoo (not in DB): {sorted(extra)}")
            return (
                False,
                f"week {week}: slate mismatch — {'; '.join(parts)}",
                db_count,
            )

    if check_refreshed:
        unrefreshed = [row[0] for row in rows if row[1] is None]
        if unrefreshed:
            return (
                False,
                (f"week {week}: {len(unrefreshed)} matchup(s) have NULL refreshed_at — "
                 f"refresh did not complete "
                 f"(home_team_ids: {sorted(unrefreshed)})"),
                db_count,
            )

    return (True, f"week {week}: {db_count} matchup(s) — slate complete and fresh",
            db_count)
```

This is the gate `_step_settle_bets()` calls (via `check_refreshed=True`) before letting `notifications/tuesday_sync.py`'s automated path reach `settle_week()`. `GET /settle/{week}` in `api/main.py` has no equivalent call anywhere in its own path.
