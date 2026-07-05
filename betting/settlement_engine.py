"""
Settlement engine — resolves all pending bets for a given week.

For each pending bet whose matchup falls in the requested week:
  - straight   : won if picked_team_id == matchup.winner_team_id
  - spread     : won if picked team's actual margin > line
  - over_under : won if (home+away) > line (side="over") or < line (side="under")
  - prop       : won if picked team's top starter outscores opponent's top starter

On settlement:
  - Won  → status="won", settled_at=now, credit wallet (payout tx)
  - Lost → status="lost", settled_at=now, no wallet change (stake already deducted)
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Bet, BeefChallenge, Matchup, Projection, Roster, Transaction, Wallet
from feed.league_feed import log_settlement_events

from config import CURRENT_SEASON as SEASON
SOURCE = "fantasypros"

# The Lineup uses a separate season/source — Yahoo actual scores vs pre-week projection
_LINEUP_SEASON = 2025
_LINEUP_SOURCE = "yahoo"


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
    already_settled: bool = False
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


def _eval_prop(bet: Bet, db: Session) -> str:
    """Compare actual points of home top starter (player_id) vs away top starter (int(side)).
    Returns "won", "lost", or "push".
    """
    week = bet.matchup.week
    home_proj = db.query(Projection).filter_by(
        player_id=bet.player_id, week=week, season=SEASON, source=SOURCE,
    ).first()
    away_proj = db.query(Projection).filter_by(
        player_id=int(bet.side), week=week, season=SEASON, source=SOURCE,
    ).first()
    home_actual = home_proj.actual_points if home_proj else 0.0
    away_actual = away_proj.actual_points if away_proj else 0.0
    if home_actual == away_actual:
        return "push"
    if bet.picked_team_id == bet.matchup.home_team_id:
        return "won" if home_actual > away_actual else "lost"
    return "won" if away_actual > home_actual else "lost"


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


def _eval_beef(bet: Bet, db: Session) -> str:
    """
    Settle a beef bet by comparing each team's actual weekly score from
    their own matchup — not from a shared matchup.
    Returns "won", "lost", or "push".
    """
    c    = bet.beef_challenge
    week = c.week

    if bet.bet_type == "straight":
        my_score  = _team_score_for_week(bet.picked_team_id, week, db)
        opp_id    = (c.challenged_team_id if bet.picked_team_id == c.challenger_team_id
                     else c.challenger_team_id)
        opp_score = _team_score_for_week(opp_id, week, db)
        if my_score == opp_score:
            return "push"
        return "won" if my_score > opp_score else "lost"

    if bet.bet_type == "spread":
        my_score  = _team_score_for_week(bet.picked_team_id, week, db)
        opp_id    = (c.challenged_team_id if bet.picked_team_id == c.challenger_team_id
                     else c.challenger_team_id)
        opp_score = _team_score_for_week(opp_id, week, db)
        margin = my_score - opp_score
        line   = bet.line or 0.0
        if margin == line:
            return "push"
        return "won" if margin > line else "lost"

    if bet.bet_type == "over_under":
        s1       = _team_score_for_week(c.challenger_team_id, week, db)
        s2       = _team_score_for_week(c.challenged_team_id, week, db)
        combined = s1 + s2
        line     = bet.line or 0.0
        if combined == line:
            return "push"
        if bet.side == "over":
            return "won" if combined > line else "lost"
        return "won" if combined < line else "lost"

    if bet.bet_type == "prop":
        return _eval_prop(bet, db)

    raise ValueError(f"No settlement handler for beef bet_type {bet.bet_type!r}")


# ── The Lineup settlement ─────────────────────────────────────────────────────

@dataclass
class LineupPlayer:
    player_id:        int
    player_name:      str
    actual_points:    float | None   # None = week not yet settled
    projected_points: float | None   # None = no pre-week projection available


def _starters_for_team(team_id: int, week: int, db: Session) -> list[LineupPlayer]:
    """
    Return LineupPlayer records for every starter on this team this week.
    Filters on Roster.slot to exclude BN/IR (never on player.position —
    that misidentifies FLEX players). If slot is NULL (pre-migration rows),
    includes the player rather than silently dropping them.
    """
    roster_rows = (
        db.query(Roster)
        .filter(Roster.team_id == team_id)
        .order_by(Roster.id)
        .all()
    )
    players: list[LineupPlayer] = []
    for r in roster_rows:
        if r.slot is not None and r.slot in ("BN", "IR"):
            continue
        proj = db.query(Projection).filter_by(
            player_id=r.player_id,
            week=week,
            season=_LINEUP_SEASON,
            source=_LINEUP_SOURCE,
        ).first()
        players.append(LineupPlayer(
            player_id        = r.player_id,
            player_name      = r.player.name,
            actual_points    = proj.actual_points    if proj else None,
            projected_points = proj.projected_points if proj else None,
        ))
    return players


def _lineup_winner(
    team_a: list[LineupPlayer],
    team_b: list[LineupPlayer],
    week: int,
) -> str:
    """
    Pure logic — no DB calls. Returns 'a', 'b', or 'push'.

    Rules:
      1. Exclude any starter whose projected_points is None from both the
         beat-count and the differential sum for their side. Log a warning.
      2. Count per side: starters with actual_points > projected_points (strict).
      3. Higher count wins.
      4. Tie on count: tiebreaker is sum(actual - projected) across included starters.
      5. Tie on both: push.
    """
    def _process(players: list[LineupPlayer], side_label: str) -> tuple[int, float]:
        count = 0
        total_diff = 0.0
        for p in players:
            if p.projected_points is None:
                print(
                    f"  [WARN] the_lineup week {week}: {p.player_name} "
                    f"(team {side_label}) has no projection — excluded from settlement"
                )
                continue
            actual = p.actual_points if p.actual_points is not None else 0.0
            diff   = actual - p.projected_points
            if diff > 0:
                count += 1
            total_diff += diff
        return count, total_diff

    a_count, a_diff = _process(team_a, "A")
    b_count, b_diff = _process(team_b, "B")

    if a_count != b_count:
        return "a" if a_count > b_count else "b"
    if a_diff != b_diff:
        return "a" if a_diff > b_diff else "b"
    return "push"


def _eval_the_lineup(bet: Bet, db: Session) -> str:
    """
    Settle a The Lineup bet. Returns 'won', 'lost', or 'push'.
    Compares how many starters on each team beat their Yahoo projection.
    """
    matchup = bet.matchup
    week    = matchup.week

    a_players = _starters_for_team(matchup.home_team_id, week, db)
    b_players = _starters_for_team(matchup.away_team_id, week, db)

    winner_side = _lineup_winner(a_players, b_players, week)

    if winner_side == "push":
        return "push"

    winner_team_id = (
        matchup.home_team_id if winner_side == "a" else matchup.away_team_id
    )
    return "won" if winner_team_id == bet.picked_team_id else "lost"


_EVALUATORS = {
    "straight":   lambda bet, matchup, db: _eval_straight(bet, matchup),
    "spread":     lambda bet, matchup, db: _eval_spread(bet, matchup),
    "over_under": lambda bet, matchup, db: _eval_over_under(bet, matchup),
    "prop":       lambda bet, matchup, db: _eval_prop(bet, db),
}


# ── Public API ────────────────────────────────────────────────────────────────

def settle_week(week: int, db: Session, league_id: int) -> SettlementReport:
    """Settle all pending bets whose matchup is in the given week.

    Guarded by WeekSettlement(league_id, week) — independent of Bet.status.
    Claimed atomically via a single INSERT ... ON CONFLICT DO NOTHING,
    committed on its own before the payout loop runs. There is no pre-flight
    SELECT: the INSERT's RETURNING clause is itself the check. If a row for
    (league_id, week) already exists — no matter how close the timing —
    this call's INSERT is a no-op, RETURNING yields nothing, and this call
    returns immediately without touching a single bet or wallet.

    Known, accepted tradeoff (not an oversight): if the payout loop below
    crashes partway through after the claim commits, the week will show as
    settled even though not every bet was actually paid. There is no
    automated crash-recovery for this today — if it happens, the
    commissioner must manually check settlement completeness for the week
    and finish payouts by hand. Tracked as a deferred item.
    """
    now = datetime.now(timezone.utc)

    claimed = db.execute(
        text("""
            INSERT INTO week_settlements (league_id, week, settled, settled_at)
            VALUES (:league_id, :week, :settled, :settled_at)
            ON CONFLICT (league_id, week) DO NOTHING
            RETURNING id
        """),
        {"league_id": league_id, "week": week, "settled": True, "settled_at": now},
    ).fetchone()
    db.commit()

    if claimed is None:
        logging.info(
            "[settle_week] week=%s league_id=%s already claimed by another caller — skipping",
            week, league_id,
        )
        return SettlementReport(week=week, total_bets=0, bets_won=0, bets_lost=0,
                                total_staked=0.0, total_payout=0.0, already_settled=True)

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


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    from db.schema import SessionLocal

    week = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    with SessionLocal() as db:
        report = settle_week(week, db, league_id=1)  # dev CLI script — kept working as-is, not a design decision

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
