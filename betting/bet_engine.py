"""
Bet engine — six bet types backed by Monte Carlo simulation.

All place_* functions:
  1. Validate wallet balance
  2. Derive fair odds from simulated score distributions
  3. Deduct stake, write Bet (status=pending) + debit Transaction
  4. Return BetResult with status="pending"

Settlement is handled separately by settlement_engine.settle_week().
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Bet, Matchup, Player, Projection, Roster, Transaction, Wallet
from wallet.wallet_manager import validate_bet_amount
from odds.odds_engine_headless import (
    N_SIMS,
    PlayerProj,
    ScoringSettings,
    HALF_PPR,
    INJURY_MULTIPLIERS,
    simulate_player_scores,
    simulate_scores,
)

from config import CURRENT_SEASON as SEASON
SOURCE = "fantasypros"

_STARTER_SLOTS = 9   # first 9 roster rows are starters
_BENCH_START   = 9   # roster rows offset _BENCH_START+ are bench
_BENCH_STD     = 20.0  # aggregate bench score std for Full Beef simulation


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class BetResult:
    bet_id:      int
    bet_type:    str
    description: str
    amount:      float
    odds_dec:    float
    moneyline:   int
    win_prob:    float
    to_win:      float
    status:      str
    legs:        list | None = field(default=None)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ml_to_decimal(ml: int) -> float:
    if ml < 0:
        return round(1 + 100 / abs(ml), 4)
    return round(1 + ml / 100, 4)


def _prob_to_american(prob: float) -> int:
    prob = max(0.001, min(0.999, prob))
    if prob > 0.5:
        return -round(100 * prob / (1 - prob))
    if prob < 0.5:
        return round(100 * (1 - prob) / prob)
    return 100


def _place_bet(
    db: Session,
    wallet: Wallet,
    amount: float,
    bet_type: str,
    matchup_id: int,
    picked_team_id: int | None,
    player_id: int | None,
    line: float | None,
    side: str | None,
    description: str,
    odds_dec: float,
) -> Bet:
    """Deduct stake and write a pending bet + debit transaction."""
    validate_bet_amount(amount, wallet.balance)
    wallet.balance = round(wallet.balance - amount, 2)

    bet = Bet(
        matchup_id     = matchup_id,
        wallet_id      = wallet.id,
        picked_team_id = picked_team_id,
        player_id      = player_id,
        bet_type       = bet_type,
        line           = line,
        side           = side,
        description    = description,
        amount         = amount,
        odds           = odds_dec,
        status         = "pending",
        placed_at      = datetime.now(timezone.utc),
    )
    db.add(bet)
    db.flush()

    db.add(Transaction(
        wallet_id  = wallet.id,
        amount     = -amount,
        type       = "bet",
        bet_id     = bet.id,
        created_at = datetime.now(timezone.utc),
    ))

    db.commit()
    db.refresh(bet)
    return bet


def _top_starter(team_id: int, week: int, db: Session) -> tuple[Player, float]:
    """Return the starter (slots 1–9) with the highest projected points."""
    slots = (
        db.query(Roster)
        .filter(Roster.team_id == team_id)
        .order_by(Roster.id)
        .limit(_STARTER_SLOTS)
        .all()
    )
    best_player: Player | None = None
    best_proj = -1.0
    for slot in slots:
        proj = db.query(Projection).filter_by(
            player_id=slot.player_id, week=week, season=SEASON, source=SOURCE
        ).first()
        pts = proj.projected_points if proj else 0.0
        if pts > best_proj:
            best_proj  = pts
            best_player = slot.player
    if best_player is None:
        raise ValueError(f"No starters found for team {team_id}")
    return best_player, best_proj


def _position_player(team_id: int, position: str, week: int, db: Session) -> tuple[Player, float]:
    """Return the first rostered player at `position` and their projected points."""
    slots = (
        db.query(Roster)
        .filter(Roster.team_id == team_id)
        .order_by(Roster.id)
        .all()
    )
    for slot in slots:
        if slot.player.position == position:
            proj = db.query(Projection).filter_by(
                player_id=slot.player_id, week=week, season=SEASON, source=SOURCE
            ).first()
            return slot.player, (proj.projected_points if proj else 0.0)
    raise ValueError(f"No {position} player found for team {team_id}")


def _inj_adjusted(s: PlayerProj) -> float:
    return s.projected_points * INJURY_MULTIPLIERS.get(s.injury_status or "", 1.0)


# ── Bet type functions ────────────────────────────────────────────────────────

def place_straight_bet(
    matchup_id:     int,
    wallet_id:      int,
    picked_team_id: int,
    amount:         float,
    week:           int,
    db:             Session,
) -> BetResult:
    """Pick a team to win outright."""
    matchup = db.query(Matchup).filter(Matchup.id == matchup_id).first()
    if not matchup:
        raise ValueError(f"Matchup {matchup_id} not found")
    if picked_team_id not in (matchup.home_team_id, matchup.away_team_id):
        raise ValueError("picked_team_id must be one of the two teams in this matchup")

    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise ValueError(f"Wallet {wallet_id} not found")
    if wallet.balance < amount:
        raise ValueError(f"Insufficient balance: ${wallet.balance:.2f} < ${amount:.2f}")

    _h_slots = db.query(Roster).filter(Roster.team_id == matchup.home_team_id).order_by(Roster.id).limit(_STARTER_SLOTS).all()
    _a_slots = db.query(Roster).filter(Roster.team_id == matchup.away_team_id).order_by(Roster.id).limit(_STARTER_SLOTS).all()
    home_starters, away_starters = [], []
    for _s in _h_slots:
        _p = db.query(Projection).filter_by(player_id=_s.player_id, week=week, season=SEASON, source=SOURCE).first()
        home_starters.append(PlayerProj(player_id=_s.player_id, name=_s.player.name, position=_s.player.position, projected_points=_p.projected_points if _p else 0.0, injury_status=_p.injury_status if _p else None))
    for _s in _a_slots:
        _p = db.query(Projection).filter_by(player_id=_s.player_id, week=week, season=SEASON, source=SOURCE).first()
        away_starters.append(PlayerProj(player_id=_s.player_id, name=_s.player.name, position=_s.player.position, projected_points=_p.projected_points if _p else 0.0, injury_status=_p.injury_status if _p else None))
    home_scores, away_scores = simulate_scores(matchup.home_team_id, matchup.away_team_id, home_starters, away_starters, week)
    home_win_prob = float((home_scores > away_scores).mean())
    win_prob = home_win_prob if picked_team_id == matchup.home_team_id else 1 - home_win_prob

    ml     = _prob_to_american(win_prob)
    dec    = _ml_to_decimal(ml)
    picked = matchup.home_team if picked_team_id == matchup.home_team_id else matchup.away_team
    desc   = f"{picked.team_name} to win outright (week {week})"

    bet = _place_bet(db, wallet, amount, "straight", matchup_id,
                     picked_team_id, None, None, None, desc, dec)

    return BetResult(
        bet_id=bet.id, bet_type="straight", description=desc,
        amount=amount, odds_dec=dec, moneyline=ml,
        win_prob=round(win_prob, 4), to_win=round(amount * dec - amount, 2),
        status="pending",
    )


def place_spread_bet(
    matchup_id:     int,
    wallet_id:      int,
    picked_team_id: int,
    spread:         float,
    amount:         float,
    week:           int,
    db:             Session,
) -> BetResult:
    """
    Bet that picked_team covers the spread.
    spread > 0: picked team must win by more than `spread` points.
    spread < 0: picked team may lose by up to abs(spread) points.
    """
    matchup = db.query(Matchup).filter(Matchup.id == matchup_id).first()
    if not matchup:
        raise ValueError(f"Matchup {matchup_id} not found")
    if picked_team_id not in (matchup.home_team_id, matchup.away_team_id):
        raise ValueError("picked_team_id must be one of the two teams in this matchup")

    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise ValueError(f"Wallet {wallet_id} not found")
    if wallet.balance < amount:
        raise ValueError(f"Insufficient balance: ${wallet.balance:.2f} < ${amount:.2f}")

    _h_slots = db.query(Roster).filter(Roster.team_id == matchup.home_team_id).order_by(Roster.id).limit(_STARTER_SLOTS).all()
    _a_slots = db.query(Roster).filter(Roster.team_id == matchup.away_team_id).order_by(Roster.id).limit(_STARTER_SLOTS).all()
    home_starters, away_starters = [], []
    for _s in _h_slots:
        _p = db.query(Projection).filter_by(player_id=_s.player_id, week=week, season=SEASON, source=SOURCE).first()
        home_starters.append(PlayerProj(player_id=_s.player_id, name=_s.player.name, position=_s.player.position, projected_points=_p.projected_points if _p else 0.0, injury_status=_p.injury_status if _p else None))
    for _s in _a_slots:
        _p = db.query(Projection).filter_by(player_id=_s.player_id, week=week, season=SEASON, source=SOURCE).first()
        away_starters.append(PlayerProj(player_id=_s.player_id, name=_s.player.name, position=_s.player.position, projected_points=_p.projected_points if _p else 0.0, injury_status=_p.injury_status if _p else None))
    home_scores, away_scores = simulate_scores(matchup.home_team_id, matchup.away_team_id, home_starters, away_starters, week)

    if picked_team_id == matchup.home_team_id:
        covers = home_scores - away_scores > spread
        picked = matchup.home_team
    else:
        covers = away_scores - home_scores > spread
        picked = matchup.away_team

    win_prob = float(covers.mean())
    ml       = _prob_to_american(win_prob)
    dec      = _ml_to_decimal(ml)
    sign     = f"+{spread}" if spread >= 0 else str(spread)
    desc     = f"{picked.team_name} {sign} spread (week {week})"

    bet = _place_bet(db, wallet, amount, "spread", matchup_id,
                     picked_team_id, None, spread, None, desc, dec)

    return BetResult(
        bet_id=bet.id, bet_type="spread", description=desc,
        amount=amount, odds_dec=dec, moneyline=ml,
        win_prob=round(win_prob, 4), to_win=round(amount * dec - amount, 2),
        status="pending",
    )


def place_over_under(
    matchup_id: int,
    wallet_id:  int,
    total_line: float,
    pick:       str,
    amount:     float,
    week:       int,
    db:         Session,
) -> BetResult:
    """Bet the combined score is over/under a total line."""
    if pick not in ("over", "under"):
        raise ValueError("pick must be 'over' or 'under'")

    matchup = db.query(Matchup).filter(Matchup.id == matchup_id).first()
    if not matchup:
        raise ValueError(f"Matchup {matchup_id} not found")

    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise ValueError(f"Wallet {wallet_id} not found")
    if wallet.balance < amount:
        raise ValueError(f"Insufficient balance: ${wallet.balance:.2f} < ${amount:.2f}")

    _h_slots = db.query(Roster).filter(Roster.team_id == matchup.home_team_id).order_by(Roster.id).limit(_STARTER_SLOTS).all()
    _a_slots = db.query(Roster).filter(Roster.team_id == matchup.away_team_id).order_by(Roster.id).limit(_STARTER_SLOTS).all()
    home_starters, away_starters = [], []
    for _s in _h_slots:
        _p = db.query(Projection).filter_by(player_id=_s.player_id, week=week, season=SEASON, source=SOURCE).first()
        home_starters.append(PlayerProj(player_id=_s.player_id, name=_s.player.name, position=_s.player.position, projected_points=_p.projected_points if _p else 0.0, injury_status=_p.injury_status if _p else None))
    for _s in _a_slots:
        _p = db.query(Projection).filter_by(player_id=_s.player_id, week=week, season=SEASON, source=SOURCE).first()
        away_starters.append(PlayerProj(player_id=_s.player_id, name=_s.player.name, position=_s.player.position, projected_points=_p.projected_points if _p else 0.0, injury_status=_p.injury_status if _p else None))
    home_scores, away_scores = simulate_scores(matchup.home_team_id, matchup.away_team_id, home_starters, away_starters, week)
    combined = home_scores + away_scores

    win_prob = float((combined > total_line).mean()) if pick == "over" \
               else float((combined < total_line).mean())
    ml   = _prob_to_american(win_prob)
    dec  = _ml_to_decimal(ml)
    desc = (f"{matchup.home_team.team_name} vs {matchup.away_team.team_name} "
            f"{pick.upper()} {total_line} (week {week})")

    bet = _place_bet(db, wallet, amount, "over_under", matchup_id,
                     None, None, total_line, pick, desc, dec)

    return BetResult(
        bet_id=bet.id, bet_type="over_under", description=desc,
        amount=amount, odds_dec=dec, moneyline=ml,
        win_prob=round(win_prob, 4), to_win=round(amount * dec - amount, 2),
        status="pending",
    )


def place_prop_bet(
    matchup_id:     int,
    wallet_id:      int,
    picked_team_id: int,
    amount:         float,
    week:           int,
    db:             Session,
) -> BetResult:
    """Top projected starter vs top projected starter — pick which team's player scores more."""
    matchup = db.query(Matchup).filter(Matchup.id == matchup_id).first()
    if not matchup:
        raise ValueError(f"Matchup {matchup_id} not found")
    if picked_team_id not in (matchup.home_team_id, matchup.away_team_id):
        raise ValueError("picked_team_id must be one of the two teams in this matchup")

    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise ValueError(f"Wallet {wallet_id} not found")
    if wallet.balance < amount:
        raise ValueError(f"Insufficient balance: ${wallet.balance:.2f} < ${amount:.2f}")

    home_player, home_proj = _top_starter(matchup.home_team_id, week, db)
    away_player, away_proj = _top_starter(matchup.away_team_id, week, db)

    home_scores = simulate_player_scores(home_proj, home_player.id, week)
    away_scores = simulate_player_scores(away_proj, away_player.id, week)

    home_win_prob = float((home_scores > away_scores).mean())
    win_prob = home_win_prob if picked_team_id == matchup.home_team_id else 1 - home_win_prob

    ml  = _prob_to_american(win_prob)
    dec = _ml_to_decimal(ml)

    if picked_team_id == matchup.home_team_id:
        picked_player, opp_player, picked_proj = home_player, away_player, home_proj
    else:
        picked_player, opp_player, picked_proj = away_player, home_player, away_proj

    desc = (f"Prop: {picked_player.name} ({picked_proj:.1f}pt) "
            f"vs {opp_player.name} (week {week})")

    # player_id = home top player; side = str(away top player id) for settlement
    bet = _place_bet(db, wallet, amount, "prop", matchup_id,
                     picked_team_id, home_player.id, None, str(away_player.id), desc, dec)

    return BetResult(
        bet_id=bet.id, bet_type="prop", description=desc,
        amount=amount, odds_dec=dec, moneyline=ml,
        win_prob=round(win_prob, 4), to_win=round(amount * dec - amount, 2),
        status="pending",
    )


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    from db.schema import SessionLocal

    MATCHUP_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    WEEK       = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    WALLET_ID  = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    with SessionLocal() as db:
        matchup = db.query(Matchup).filter(Matchup.id == MATCHUP_ID).first()
        wallet  = db.query(Wallet).filter(Wallet.id == WALLET_ID).first()
        if not matchup or not wallet:
            print("Matchup or wallet not found.")
            sys.exit(1)

        home = matchup.home_team
        away = matchup.away_team
        print(f"\nPlacing pending bets — matchup {MATCHUP_ID}  week {WEEK}")
        print(f"  {home.team_name}  vs  {away.team_name}")
        print(f"  Wallet #{WALLET_ID}: ${wallet.balance:.2f}\n")

        r1 = place_straight_bet(MATCHUP_ID, WALLET_ID, home.id, 10.0, WEEK, db)
        r2 = place_spread_bet(MATCHUP_ID, WALLET_ID, home.id, 5.0, 10.0, WEEK, db)
        r3 = place_over_under(MATCHUP_ID, WALLET_ID, 240.0, "over", 10.0, WEEK, db)
        r4 = place_prop_bet(MATCHUP_ID, WALLET_ID, home.id, 10.0, WEEK, db)
        results = [r1, r2, r3, r4]

        print("┌────────┬────────────┬──────────────────────────────────────────────┬────────┬──────────┬────────┬─────────┐")
        print("│ Bet ID │ Type       │ Description                                  │  Stake │ Moneyline│ Prob   │ Status  │")
        print("├────────┼────────────┼──────────────────────────────────────────────┼────────┼──────────┼────────┼─────────┤")
        for r in results:
            print(f"│ {r.bet_id:<6} │ {r.bet_type:<10} │ {r.description:<44} │ "
                  f"${r.amount:>5.2f} │ {r.moneyline:>+8,} │ {r.win_prob:>5.1%} │ {r.status:<7} │")
        print("└────────┴────────────┴──────────────────────────────────────────────┴────────┴──────────┴────────┴─────────┘")

        db.expire_all()
        w = db.query(Wallet).filter(Wallet.id == WALLET_ID).first()
        print(f"\n  Wallet #{WALLET_ID} balance after placement: ${w.balance:.2f}")
        print("  Run settlement_engine.py to settle these bets.\n")
