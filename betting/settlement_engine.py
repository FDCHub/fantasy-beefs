"""
Settlement engine — resolves all pending bets for a given week.

For each pending bet whose matchup falls in the requested week:
  - straight   : won if picked_team_id == matchup.winner_team_id
  - spread     : won if picked team's actual margin > line
  - over_under : won if (home+away) > line (side="over") or < line (side="under")
  - prop       : won if picked team's top starter outscores opponent's top starter
  - full_beef  : win 2 of 3 legs (DEF vs DEF, K vs K, Bench vs Bench)

On settlement:
  - Won  → status="won", settled_at=now, credit wallet (payout tx)
  - Lost → status="lost", settled_at=now, no wallet change (stake already deducted)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Bet, BeefChallenge, Matchup, Projection, Roster, Transaction, Wallet
from feed.league_feed import log_settlement_events

SEASON       = 2024
SOURCE       = "fantasypros"
_BENCH_START = 9   # roster slots 10+ are bench


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class BetSettlement:
    bet_id:      int
    bet_type:    str
    description: str
    wallet_id:   int
    owner:       str
    team_name:   str
    amount:      float
    odds_dec:    float
    payout:      float   # total returned (stake + profit); 0 if lost
    profit:      float   # payout - amount; negative = -amount if lost
    status:      str     # won | lost


@dataclass
class WalletMovement:
    wallet_id:        int
    team_name:        str
    owner:            str
    balance_before:   float
    bets_won:         int
    bets_lost:        int
    total_staked:     float
    total_payout:     float
    balance_after:    float

    @property
    def net(self) -> float:
        return round(self.balance_after - self.balance_before, 2)


@dataclass
class SettlementReport:
    week:            int
    total_bets:      int
    bets_won:        int
    bets_lost:       int
    total_staked:    float
    total_payout:    float
    settlements:     list[BetSettlement]  = field(default_factory=list)
    wallet_movements: list[WalletMovement] = field(default_factory=list)

    @property
    def house_edge(self) -> float:
        """Net house profit this settlement (positive = house won)."""
        return round(self.total_staked - self.total_payout, 2)


# ── Outcome evaluators ────────────────────────────────────────────────────────

def _eval_straight(bet: Bet, matchup: Matchup) -> bool:
    return bet.picked_team_id == matchup.winner_team_id


def _eval_spread(bet: Bet, matchup: Matchup) -> bool:
    if bet.picked_team_id == matchup.home_team_id:
        margin = matchup.home_score - matchup.away_score
    else:
        margin = matchup.away_score - matchup.home_score
    return margin > (bet.line or 0.0)


def _eval_over_under(bet: Bet, matchup: Matchup) -> bool:
    combined = matchup.home_score + matchup.away_score
    if bet.side == "over":
        return combined > (bet.line or 0.0)
    return combined < (bet.line or 0.0)


def _eval_prop(bet: Bet, db: Session) -> bool:
    """Compare actual points of home top starter (player_id) vs away top starter (int(side))."""
    week = bet.matchup.week
    home_proj = db.query(Projection).filter_by(
        player_id=bet.player_id, week=week, season=SEASON, source=SOURCE,
    ).first()
    away_proj = db.query(Projection).filter_by(
        player_id=int(bet.side), week=week, season=SEASON, source=SOURCE,
    ).first()
    home_actual = home_proj.actual_points if home_proj else 0.0
    away_actual = away_proj.actual_points if away_proj else 0.0
    if bet.picked_team_id == bet.matchup.home_team_id:
        return home_actual > away_actual
    return away_actual > home_actual


def _position_actual(team_id: int, position: str, week: int, db: Session) -> float:
    """Actual points for the first rostered player at `position` in `week`."""
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
            return proj.actual_points if proj else 0.0
    return 0.0


def _eval_full_beef_bet(bet: Bet, db: Session) -> bool:
    """Win 2 of 3 legs (DEF, K, Bench) to win The Full Beef."""
    matchup = bet.matchup
    week    = matchup.week
    h_id    = matchup.home_team_id
    a_id    = matchup.away_team_id

    h_def   = _position_actual(h_id, "DEF", week, db)
    a_def   = _position_actual(a_id, "DEF", week, db)
    h_k     = _position_actual(h_id, "K",   week, db)
    a_k     = _position_actual(a_id, "K",   week, db)
    h_bench = _bench_actual_score(h_id, week, db)
    a_bench = _bench_actual_score(a_id, week, db)

    h_legs = sum([h_def > a_def, h_k > a_k, h_bench > a_bench])
    return (h_legs >= 2) if bet.picked_team_id == h_id else (h_legs <= 1)


def _team_score_for_week(team_id: int, week: int, db: Session) -> float:
    """Actual weekly score for a team from their own scheduled matchup."""
    m = (
        db.query(Matchup)
        .filter(
            Matchup.week == week,
            (Matchup.home_team_id == team_id) | (Matchup.away_team_id == team_id),
        )
        .first()
    )
    if not m:
        return 0.0
    return m.home_score if m.home_team_id == team_id else m.away_score


def _bench_actual_score(team_id: int, week: int, db: Session) -> float:
    """Sum actual_points for bench players (slots _BENCH_START+1 onwards) from Projection."""
    slots = (
        db.query(Roster)
        .filter(Roster.team_id == team_id)
        .order_by(Roster.id)
        .offset(_BENCH_START)
        .all()
    )
    total = 0.0
    for slot in slots:
        proj = db.query(Projection).filter_by(
            player_id=slot.player_id, week=week, season=SEASON, source=SOURCE
        ).first()
        total += (proj.actual_points if proj else 0.0)
    return total


def _eval_beef(bet: Bet, db: Session) -> bool:
    """
    Settle a beef bet by comparing each team's actual weekly score from
    their own matchup — not from a shared matchup.
    """
    c    = bet.beef_challenge
    week = c.week

    if bet.bet_type == "straight":
        my_score  = _team_score_for_week(bet.picked_team_id, week, db)
        opp_id    = (c.challenged_team_id if bet.picked_team_id == c.challenger_team_id
                     else c.challenger_team_id)
        opp_score = _team_score_for_week(opp_id, week, db)
        return my_score > opp_score

    if bet.bet_type == "spread":
        my_score  = _team_score_for_week(bet.picked_team_id, week, db)
        opp_id    = (c.challenged_team_id if bet.picked_team_id == c.challenger_team_id
                     else c.challenger_team_id)
        opp_score = _team_score_for_week(opp_id, week, db)
        return (my_score - opp_score) > (bet.line or 0.0)

    if bet.bet_type == "over_under":
        s1       = _team_score_for_week(c.challenger_team_id, week, db)
        s2       = _team_score_for_week(c.challenged_team_id, week, db)
        combined = s1 + s2
        return (combined > (bet.line or 0.0)) if bet.side == "over" \
               else (combined < (bet.line or 0.0))

    if bet.bet_type == "bench_battle":
        my_score  = _bench_actual_score(bet.picked_team_id, week, db)
        opp_id    = (c.challenged_team_id if bet.picked_team_id == c.challenger_team_id
                     else c.challenger_team_id)
        opp_score = _bench_actual_score(opp_id, week, db)
        return my_score > opp_score

    if bet.bet_type == "prop":
        return _eval_prop(bet, db)

    if bet.bet_type == "full_beef":
        return _eval_full_beef_bet(bet, db)

    return False


_EVALUATORS = {
    "straight":   lambda bet, matchup, db: _eval_straight(bet, matchup),
    "spread":     lambda bet, matchup, db: _eval_spread(bet, matchup),
    "over_under": lambda bet, matchup, db: _eval_over_under(bet, matchup),
    "prop":       lambda bet, matchup, db: _eval_prop(bet, db),
    "full_beef":  lambda bet, matchup, db: _eval_full_beef_bet(bet, db),
}


# ── Public API ────────────────────────────────────────────────────────────────

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
        # Beef bets compare weekly scores across different matchups
        if bet.beef_challenge_id is not None:
            won = _eval_beef(bet, db)
        else:
            evaluator = _EVALUATORS.get(bet.bet_type)
            if evaluator is None:
                continue
            won = evaluator(bet, matchup, db)
        status = "won" if won else "lost"
        payout = round(bet.amount * bet.odds, 2) if won else 0.0
        profit = round(payout - bet.amount, 2)

        bet.status     = status
        bet.settled_at = now

        wallet = wallets[bet.wallet_id]
        if won:
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


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    from db.schema import SessionLocal

    week = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    with SessionLocal() as db:
        report = settle_week(week, db)

    if report.total_bets == 0:
        print(f"\nNo pending bets found for week {week}.")
        sys.exit(0)

    print(f"\nSettlement Report — Week {report.week}")
    print(f"  {report.total_bets} bets settled  "
          f"({report.bets_won} won / {report.bets_lost} lost)  "
          f"staked ${report.total_staked:.2f}  "
          f"paid out ${report.total_payout:.2f}  "
          f"house edge ${report.house_edge:.2f}\n")

    # Per-bet results
    print("┌────────┬────────────┬──────────────────────────────────────────────┬──────────┬────────────┬──────────┬─────────┐")
    print("│ Bet ID │ Type       │ Description                                  │   Stake  │   Payout   │  Profit  │ Status  │")
    print("├────────┼────────────┼──────────────────────────────────────────────┼──────────┼────────────┼──────────┼─────────┤")
    for s in report.settlements:
        print(f"│ {s.bet_id:<6} │ {s.bet_type:<10} │ {s.description:<44} │ "
              f"${s.amount:>7.2f} │ ${s.payout:>9.2f} │ {s.profit:>+8.2f} │ {s.status:<7} │")
    print("└────────┴────────────┴──────────────────────────────────────────────┴──────────┴────────────┴──────────┴─────────┘")

    # Wallet movement report
    print("\nWallet Movement Report\n")
    print("┌────┬────────────────────────────┬──────────────────────┬──────────────┬──────┬──────┬──────────────┬──────────────┬──────────────┐")
    print("│ ID │ Team                       │ Owner                │ Before       │  Won │ Lost │ Staked       │ Payout       │ After        │")
    print("├────┼────────────────────────────┼──────────────────────┼──────────────┼──────┼──────┼──────────────┼──────────────┼──────────────┤")
    for mv in report.wallet_movements:
        net_str = f"({mv.net:>+.2f})"
        print(f"│ {mv.wallet_id:<2} │ {mv.team_name:<26} │ {mv.owner:<20} │ "
              f"${mv.balance_before:>11,.2f} │ {mv.bets_won:>4} │ {mv.bets_lost:>4} │ "
              f"${mv.total_staked:>11,.2f} │ ${mv.total_payout:>11,.2f} │ "
              f"${mv.balance_after:>8,.2f} {net_str:<8} │")
    print("└────┴────────────────────────────┴──────────────────────┴──────────────┴──────┴──────┴──────────────┴──────────────┴──────────────┘")
