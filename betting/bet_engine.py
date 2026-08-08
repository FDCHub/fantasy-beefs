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
from betting.exceptions import NotFoundError, BetValidationError
from wallet.wallet_manager import validate_bet_amount
from odds.odds_engine_headless import (
    PlayerProj,
    simulate_scores,
)
# P3-D2 / MODEL-A — pinned to the v1 config, a verbatim capture of the constants
# this module already priced against. N_SIMS, ScoringSettings and HALF_PPR were
# imported but never used and are dropped; INJURY_MULTIPLIERS WAS used, by
# _inj_adjusted below, and is now read from the config so that every
# probability-affecting value in this module comes from one versioned source.
from odds.model_registry import MODEL_V1 as LEGACY_MODEL_CONFIG
from ledger.ledger import (
    post as ledger_post,
    _dollars_to_cents,
    _balance_of_in_session,
    lock_funding_scopes,
)

from config import CURRENT_SEASON as SEASON
SOURCE = "fantasypros"

_STARTER_SLOTS = 9   # first 9 roster rows are starters
_BENCH_START   = 9   # roster rows offset _BENCH_START+ are bench
_BENCH_STD     = 20.0  # aggregate bench score std for Full Beef simulation


def _to_cents(amount: float) -> int:
    """Dollars → integer cents, for ledger.post() calls. Rounds first —
    never truncates raw float multiplication — per the L1 spec's integer-
    cents-only requirement.

    Duplicated from beefs/beef_engine.py's own _to_cents() rather than
    imported from there: betting/ is the lower-level module (beefs/ already
    imports FROM betting/, never the reverse) — importing this one trivial
    line the other way round would be a backwards dependency for no benefit.
    Not centralized in ledger/ledger.py either, since that file stays
    untouched in this pass. Matches this file's own existing convention of
    small local helpers (_ml_to_decimal, _prob_to_american) rather than
    importing trivial utilities cross-package."""
    return round(amount * 100)


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
    # FR-7.50: reject a sub-cent stake before validate_bet_amount()'s
    # MIN_BET/MAX_BET_PCT guard. Single funnel for all four single-party
    # entry points (place_straight_bet/spread/over_under/prop). Return value
    # discarded (validation only); the ValueError propagates.
    _dollars_to_cents(amount)
    # P1-L7: take this funding scope's Wallet-row mutex BEFORE the capacity read
    # below. Single scope — this path debits exactly one wallet — so ordering is
    # trivially deterministic, but it goes through the shared primitive anyway so
    # there is one lock discipline in the tree rather than two.
    #
    # The lock is held from here to this function's own db.commit() below, which
    # is what closes the race: without it, two concurrent stakes each read the
    # pre-debit balance, each pass validate_bet_amount(), and both post. P1-L6
    # event identity does NOT cover this — these are two DISTINCT bets, not one
    # bet delivered twice, so there is no repeated event id to de-duplicate.
    lock_funding_scopes(db, wallet.team_id)
    # P1-L3B: the capacity input is the AUTHORITATIVE integer-cent ledger balance
    # for wallet:{team_id}, read inside this same session/transaction — never the
    # float Wallet.balance mirror. Plain wallet balance is the correct account
    # here: this legacy single-party path debits wallet:{team_id} and nothing
    # else, and Weekly Minimum accounts do not exist on it.
    validate_bet_amount(amount, _balance_of_in_session(db, f"wallet:{wallet.team_id}"))

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

    # Ledger posting — replaces the old direct wallet.balance mutation.
    # escrow:{bet.id} needs bet.id, hence this runs after the flush above.
    # session=db, NOT session=None: db.flush() above already opened an
    # uncommitted write transaction on `db`. On SQLite, a second connection
    # (what session=None would open) can't get a write lock while that's
    # open — it deadlocks with "database is locked" on every call, not just
    # under failure (confirmed by running this against the test suite before
    # settling on session=db). Passing session=db instead makes the ledger
    # write part of this SAME transaction, so it commits together with the
    # Bet/Transaction rows in this function's own db.commit() below — one
    # commit, no deadlock, and no orphaned-ledger-entry risk either.
    ledger_post(
        [
            (f"wallet:{wallet.team_id}", -_to_cents(amount)),
            (f"escrow:{bet.id}",          _to_cents(amount)),
        ],
        door="wager_placed",
        session=db,
    )

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
    """The injury STATUS is a live input; the multiplier TABLE is model config."""
    return s.projected_points * LEGACY_MODEL_CONFIG.injury_multiplier(s.injury_status)


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
        raise NotFoundError(f"Matchup {matchup_id} not found")
    if picked_team_id not in (matchup.home_team_id, matchup.away_team_id):
        raise BetValidationError("picked_team_id must be one of the two teams in this matchup")

    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise NotFoundError(f"Wallet {wallet_id} not found")

    _h_slots = db.query(Roster).filter(Roster.team_id == matchup.home_team_id).order_by(Roster.id).limit(_STARTER_SLOTS).all()
    _a_slots = db.query(Roster).filter(Roster.team_id == matchup.away_team_id).order_by(Roster.id).limit(_STARTER_SLOTS).all()
    home_starters, away_starters = [], []
    for _s in _h_slots:
        _p = db.query(Projection).filter_by(player_id=_s.player_id, week=week, season=SEASON, source=SOURCE).first()
        home_starters.append(PlayerProj(player_id=_s.player_id, name=_s.player.name, position=_s.player.position, projected_points=_p.projected_points if _p else 0.0, injury_status=_p.injury_status if _p else None))
    for _s in _a_slots:
        _p = db.query(Projection).filter_by(player_id=_s.player_id, week=week, season=SEASON, source=SOURCE).first()
        away_starters.append(PlayerProj(player_id=_s.player_id, name=_s.player.name, position=_s.player.position, projected_points=_p.projected_points if _p else 0.0, injury_status=_p.injury_status if _p else None))
    home_scores, away_scores = simulate_scores(matchup.home_team_id, matchup.away_team_id, home_starters, away_starters, week, model_config=LEGACY_MODEL_CONFIG)
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
        raise NotFoundError(f"Matchup {matchup_id} not found")
    if picked_team_id not in (matchup.home_team_id, matchup.away_team_id):
        raise BetValidationError("picked_team_id must be one of the two teams in this matchup")

    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise NotFoundError(f"Wallet {wallet_id} not found")

    _h_slots = db.query(Roster).filter(Roster.team_id == matchup.home_team_id).order_by(Roster.id).limit(_STARTER_SLOTS).all()
    _a_slots = db.query(Roster).filter(Roster.team_id == matchup.away_team_id).order_by(Roster.id).limit(_STARTER_SLOTS).all()
    home_starters, away_starters = [], []
    for _s in _h_slots:
        _p = db.query(Projection).filter_by(player_id=_s.player_id, week=week, season=SEASON, source=SOURCE).first()
        home_starters.append(PlayerProj(player_id=_s.player_id, name=_s.player.name, position=_s.player.position, projected_points=_p.projected_points if _p else 0.0, injury_status=_p.injury_status if _p else None))
    for _s in _a_slots:
        _p = db.query(Projection).filter_by(player_id=_s.player_id, week=week, season=SEASON, source=SOURCE).first()
        away_starters.append(PlayerProj(player_id=_s.player_id, name=_s.player.name, position=_s.player.position, projected_points=_p.projected_points if _p else 0.0, injury_status=_p.injury_status if _p else None))
    home_scores, away_scores = simulate_scores(matchup.home_team_id, matchup.away_team_id, home_starters, away_starters, week, model_config=LEGACY_MODEL_CONFIG)

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
        raise BetValidationError("pick must be 'over' or 'under'")

    matchup = db.query(Matchup).filter(Matchup.id == matchup_id).first()
    if not matchup:
        raise NotFoundError(f"Matchup {matchup_id} not found")

    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise NotFoundError(f"Wallet {wallet_id} not found")

    _h_slots = db.query(Roster).filter(Roster.team_id == matchup.home_team_id).order_by(Roster.id).limit(_STARTER_SLOTS).all()
    _a_slots = db.query(Roster).filter(Roster.team_id == matchup.away_team_id).order_by(Roster.id).limit(_STARTER_SLOTS).all()
    home_starters, away_starters = [], []
    for _s in _h_slots:
        _p = db.query(Projection).filter_by(player_id=_s.player_id, week=week, season=SEASON, source=SOURCE).first()
        home_starters.append(PlayerProj(player_id=_s.player_id, name=_s.player.name, position=_s.player.position, projected_points=_p.projected_points if _p else 0.0, injury_status=_p.injury_status if _p else None))
    for _s in _a_slots:
        _p = db.query(Projection).filter_by(player_id=_s.player_id, week=week, season=SEASON, source=SOURCE).first()
        away_starters.append(PlayerProj(player_id=_s.player_id, name=_s.player.name, position=_s.player.position, projected_points=_p.projected_points if _p else 0.0, injury_status=_p.injury_status if _p else None))
    home_scores, away_scores = simulate_scores(matchup.home_team_id, matchup.away_team_id, home_starters, away_starters, week, model_config=LEGACY_MODEL_CONFIG)
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
    """RETIRED — prop bets can no longer be placed. Kept as a callable stub
    (not deleted) so existing callers, including the /bets/prop route, get
    a clear rejection instead of an import error or a 404. Settlement
    (_eval_prop() in settlement_engine.py) and audit_deprecated_bet_types.py
    are untouched — historical prop rows, if any ever exist, still settle
    and audit correctly."""
    raise BetValidationError("Prop bets are retired and can no longer be placed.")


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
        results = [r1, r2, r3]

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
