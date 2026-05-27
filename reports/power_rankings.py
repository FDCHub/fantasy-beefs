"""
Power Rankings — three independent dimensions combined into a composite GM Rating.

Dimensions
  ON-FIELD  (50%) — record, points for/against, strength of schedule
  BETTING   (30%) — win rate, ROI, hot/cold streak
  WAIVER    (20%) — FAAB efficiency (pts added per dollar spent)

Status tags (by composite rank + playoff math):
  contender — in playoff position (top 4)
  bubble    — within 2 spots of playoff line (5th–6th)
  spoiler   — out of playoffs but not eliminated
  chaos     — mathematically eliminated (can't reach 4th place even winning all remaining)

Entry points
  compute_power_rankings(league_id, week, db)  → list[PowerRankingOut]  (compute & store)
  get_power_rankings(league_id, week, db)      → list[PowerRankingOut]  (read from DB)
  get_team_ranking_history(league_id, team_id, db, limit) → list[PowerRankingOut]
  get_league_arc(league_id, db)                → dict[int, list[PowerRankingOut]]
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import (
    Bet,
    FaabTransaction,
    FeedEvent,
    League,
    Matchup,
    PowerRanking,
    Team,
    Wallet,
)

# ── Constants ─────────────────────────────────────────────────────────────────

PLAYOFF_SPOTS    = 4    # top 4 of 10 make playoffs
REGULAR_SEASON   = 17   # total weeks; elimination math uses remaining games

# Dimension weights for composite score
W_ON_FIELD = 0.50
W_BETTING  = 0.30
W_WAIVER   = 0.20

# On-field sub-weights (must sum to 1)
W_WIN_RATE = 0.50
W_PF       = 0.35
W_SOS      = 0.15

# Betting sub-weights (must sum to 1)
W_BET_WR    = 0.45
W_BET_ROI   = 0.40
W_BET_STREAK = 0.15


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class PowerRankingOut:
    ranking_id:           int
    league_id:            int
    week:                 int
    team_id:              int
    team_name:            str
    owner:                str

    on_field_rank:        int
    on_field_score:       float
    wins:                 int
    losses:               int
    points_for:           float
    points_against:       float
    sos:                  float

    betting_rank:         int
    betting_score:        float
    bet_wins:             int
    bet_losses:           int
    roi:                  float
    best_win_amount:      float
    worst_loss_amount:    float
    bet_streak:           int

    waiver_rank:          int
    waiver_score:         float
    waiver_dollars_spent: float
    waiver_pts_added:     float
    pts_per_dollar:       float

    composite_rank:       int
    composite_score:      float
    rank_change:          Optional[int]   # None for first computed week; +n = moved up
    status_tag:           str
    created_at:           str


# ── Serialiser ────────────────────────────────────────────────────────────────

def _to_out(row: PowerRanking, team: Team) -> PowerRankingOut:
    return PowerRankingOut(
        ranking_id           = row.id,
        league_id            = row.league_id,
        week                 = row.week,
        team_id              = row.team_id,
        team_name            = team.team_name,
        owner                = team.owner,
        on_field_rank        = row.on_field_rank,
        on_field_score       = row.on_field_score,
        wins                 = row.wins,
        losses               = row.losses,
        points_for           = row.points_for,
        points_against       = row.points_against,
        sos                  = row.sos,
        betting_rank         = row.betting_rank,
        betting_score        = row.betting_score,
        bet_wins             = row.bet_wins,
        bet_losses           = row.bet_losses,
        roi                  = row.roi,
        best_win_amount      = row.best_win_amount,
        worst_loss_amount    = row.worst_loss_amount,
        bet_streak           = row.bet_streak,
        waiver_rank          = row.waiver_rank,
        waiver_score         = row.waiver_score,
        waiver_dollars_spent = row.waiver_dollars_spent,
        waiver_pts_added     = row.waiver_pts_added,
        pts_per_dollar       = row.pts_per_dollar,
        composite_rank       = row.composite_rank,
        composite_score      = row.composite_score,
        rank_change          = row.rank_change,
        status_tag           = row.status_tag,
        created_at           = row.created_at.isoformat() if row.created_at else "",
    )


# ── Math helpers ──────────────────────────────────────────────────────────────

def _normalize(values: list[float]) -> list[float]:
    """Min-max normalize to [0, 1]. Returns 0.5 for all if no variance."""
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5] * len(values)
    span = hi - lo
    return [(v - lo) / span for v in values]


def _rank_desc(values: list[float]) -> list[int]:
    """Rank 1 = highest value. Ties: earlier index wins (stable sort by -val)."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i], reverse=True)
    ranks = [0] * n
    for rank, idx in enumerate(order, 1):
        ranks[idx] = rank
    return ranks


# ── Data gathering ────────────────────────────────────────────────────────────

def _gather_on_field(team_id: int, league_id: int, through_week: int, db: Session) -> dict:
    matchups = (
        db.query(Matchup)
        .filter(
            Matchup.league_id == league_id,
            Matchup.week <= through_week,
            or_(Matchup.home_team_id == team_id, Matchup.away_team_id == team_id),
            Matchup.winner_team_id.isnot(None),
        )
        .all()
    )

    wins = 0
    losses = 0
    pf = 0.0
    pa = 0.0
    opp_ids: list[int] = []

    for m in matchups:
        if m.home_team_id == team_id:
            pf += m.home_score
            pa += m.away_score
            opp_ids.append(m.away_team_id)
        else:
            pf += m.away_score
            pa += m.home_score
            opp_ids.append(m.home_team_id)
        if m.winner_team_id == team_id:
            wins += 1
        else:
            losses += 1

    # Strength of schedule: average each opponent's win rate through this week
    sos = 0.5  # default when no games played
    if opp_ids:
        opp_win_rates: list[float] = []
        for opp_id in opp_ids:
            opp_ms = (
                db.query(Matchup)
                .filter(
                    Matchup.league_id == league_id,
                    Matchup.week <= through_week,
                    or_(Matchup.home_team_id == opp_id, Matchup.away_team_id == opp_id),
                    Matchup.winner_team_id.isnot(None),
                )
                .all()
            )
            opp_games = len(opp_ms)
            opp_wins  = sum(1 for m in opp_ms if m.winner_team_id == opp_id)
            opp_win_rates.append(opp_wins / opp_games if opp_games > 0 else 0.5)
        sos = sum(opp_win_rates) / len(opp_win_rates)

    games    = wins + losses
    win_rate = wins / games if games > 0 else 0.5
    pf_per_game = pf / games if games > 0 else 0.0

    return {
        "wins": wins, "losses": losses, "pf": pf, "pa": pa,
        "sos": sos, "pf_per_game": pf_per_game, "win_rate": win_rate,
    }


def _gather_betting(team_id: int, db: Session) -> dict:
    wallet = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    if not wallet:
        return {
            "bet_wins": 0, "bet_losses": 0, "roi": 0.0,
            "best_win_amount": 0.0, "worst_loss_amount": 0.0, "bet_streak": 0,
        }

    settled = (
        db.query(Bet)
        .filter(Bet.wallet_id == wallet.id, Bet.status.in_(["won", "lost"]))
        .order_by(Bet.settled_at)
        .all()
    )

    bet_wins   = sum(1 for b in settled if b.status == "won")
    bet_losses = sum(1 for b in settled if b.status == "lost")

    total_staked = sum(b.amount for b in settled)
    total_payout = sum(b.amount * b.odds for b in settled if b.status == "won")
    roi = (total_payout - total_staked) / total_staked if total_staked > 0 else 0.0

    best_win_amount   = max(
        (b.amount * b.odds - b.amount for b in settled if b.status == "won"), default=0.0
    )
    worst_loss_amount = max(
        (b.amount for b in settled if b.status == "lost"), default=0.0
    )

    # Hot/cold streak: count consecutive same-result bets from most recent
    streak = 0
    if settled:
        last_status = settled[-1].status
        for b in reversed(settled):
            if b.status == last_status:
                streak += 1 if last_status == "won" else -1
            else:
                break

    return {
        "bet_wins": bet_wins, "bet_losses": bet_losses, "roi": roi,
        "best_win_amount": round(best_win_amount, 2),
        "worst_loss_amount": round(worst_loss_amount, 2),
        "bet_streak": streak,
    }


def _gather_waiver(team_id: int, league_id: int, db: Session) -> dict:
    """FAAB efficiency. Returns zero stats when no waiver bids exist (mock DB)."""
    bids = (
        db.query(FaabTransaction)
        .filter(
            FaabTransaction.team_id   == team_id,
            FaabTransaction.league_id == league_id,
            FaabTransaction.type      == "waiver_bid",
            FaabTransaction.status    == "applied",
        )
        .all()
    )

    dollars_spent = sum(b.amount for b in bids)
    # pts_added is zero until real waiver activity exists (P1 milestone: real data ingestion)
    pts_added     = 0.0
    pts_per_dollar = pts_added / dollars_spent if dollars_spent > 0 else 0.0

    return {
        "dollars_spent": round(dollars_spent, 2),
        "pts_added": round(pts_added, 2),
        "pts_per_dollar": round(pts_per_dollar, 4),
    }


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _betting_raw(d: dict) -> float:
    total_bets = d["bet_wins"] + d["bet_losses"]
    bet_wr = d["bet_wins"] / total_bets if total_bets > 0 else 0.5

    # ROI: clip to [-1, 3], normalize to [0, 1]
    roi_norm = max(0.0, min(1.0, (d["roi"] + 1.0) / 4.0))

    # Streak: -10…+10 mapped to 0…1 (clamped)
    streak_norm = max(0.0, min(1.0, (d["bet_streak"] + 10) / 20.0))

    return bet_wr * W_BET_WR + roi_norm * W_BET_ROI + streak_norm * W_BET_STREAK


def _pr_status(
    composite_rank: int,
    total_teams:    int,
    wins:           int,
    week:           int,
    fourth_place_wins: int,
) -> str:
    remaining        = max(0, REGULAR_SEASON - week)
    max_possible_wins = wins + remaining

    # Mathematically eliminated only relevant once enough games have been played
    if week >= 5 and max_possible_wins < fourth_place_wins:
        return "chaos"

    if composite_rank <= PLAYOFF_SPOTS:
        return "contender"

    if composite_rank <= PLAYOFF_SPOTS + 2:
        return "bubble"

    return "spoiler"


# ── Feed posting ──────────────────────────────────────────────────────────────

def _post_rankings_to_feed(
    league_id: int,
    week:      int,
    rankings:  list[PowerRankingOut],
    db:        Session,
) -> None:
    if not rankings:
        return

    sorted_r = sorted(rankings, key=lambda r: r.composite_rank)
    leader   = sorted_r[0]
    last_pl  = sorted_r[-1]

    top3 = " → ".join(
        f"{r.team_name} (#{r.composite_rank})" for r in sorted_r[:3]
    )
    bottom3 = ", ".join(
        f"{r.team_name} (#{r.composite_rank})" for r in sorted_r[-3:]
    )
    headline  = (f"Week {week} Power Rankings — Leader: {leader.team_name}  "
                 f"| Last: {last_pl.team_name}")[:500]
    trash_talk = (f"Top: {top3}  |  Bottom: {bottom3}")[:500]

    db.add(FeedEvent(
        league_id      = league_id,
        week           = week,
        event_type     = "power_rankings",
        actor_team_id  = leader.team_id,
        target_team_id = last_pl.team_id,
        headline       = headline,
        trash_talk     = trash_talk,
        created_at     = datetime.now(timezone.utc),
    ))
    db.commit()


# ── Core computation ──────────────────────────────────────────────────────────

def compute_power_rankings(
    league_id: int,
    week:      int,
    db:        Session,
) -> list[PowerRankingOut]:
    """
    Compute and persist power rankings for league_id at the end of `week`.
    Overwrites any existing rows for the same (league_id, week).
    Returns list sorted by composite_rank ascending (1 = best).
    """
    teams = db.query(Team).filter(Team.league_id == league_id).all()
    if not teams:
        return []

    team_ids   = [t.id for t in teams]
    team_by_id = {t.id: t for t in teams}

    # ── Gather raw stats ──────────────────────────────────────────────────────
    on_field_data = {tid: _gather_on_field(tid, league_id, week, db) for tid in team_ids}
    betting_data  = {tid: _gather_betting(tid, db)                   for tid in team_ids}
    waiver_data   = {tid: _gather_waiver(tid, league_id, db)         for tid in team_ids}

    # ── On-field raw scores ───────────────────────────────────────────────────
    max_pf = max(od["pf"] for od in on_field_data.values()) or 1.0
    on_field_raw = [
        (on_field_data[tid]["win_rate"] * W_WIN_RATE
         + (on_field_data[tid]["pf"] / max_pf) * W_PF
         + on_field_data[tid]["sos"] * W_SOS)
        for tid in team_ids
    ]

    # ── Betting raw scores ────────────────────────────────────────────────────
    betting_raw = [_betting_raw(betting_data[tid]) for tid in team_ids]

    # ── Waiver raw scores (normalize pts_per_dollar within league) ────────────
    all_ppd = [waiver_data[tid]["pts_per_dollar"] for tid in team_ids]
    max_ppd = max(all_ppd)
    if max_ppd > 0:
        waiver_raw = [waiver_data[tid]["pts_per_dollar"] / max_ppd for tid in team_ids]
    else:
        waiver_raw = [0.5] * len(team_ids)  # no waiver activity — equal rating

    # ── Normalize each dimension to 0–1 ──────────────────────────────────────
    on_field_scores = _normalize(on_field_raw)
    betting_scores  = _normalize(betting_raw)
    waiver_scores   = _normalize(waiver_raw)

    # ── Rank each dimension (1 = best) ────────────────────────────────────────
    on_field_ranks = _rank_desc(on_field_scores)
    betting_ranks  = _rank_desc(betting_scores)
    waiver_ranks   = _rank_desc(waiver_scores)

    # ── Composite score & rank ────────────────────────────────────────────────
    composite_raw = [
        on_field_scores[i] * W_ON_FIELD
        + betting_scores[i] * W_BETTING
        + waiver_scores[i]  * W_WAIVER
        for i in range(len(team_ids))
    ]
    composite_ranks = _rank_desc(composite_raw)

    # ── Rank change vs previous week ─────────────────────────────────────────
    prev_ranks: dict[int, int] = {}
    if week > 1:
        prev_rows = (
            db.query(PowerRanking)
            .filter(PowerRanking.league_id == league_id, PowerRanking.week == week - 1)
            .all()
        )
        prev_ranks = {row.team_id: row.composite_rank for row in prev_rows}

    # ── 4th-place win count (for elimination math) ────────────────────────────
    wins_list = sorted(
        [on_field_data[tid]["wins"] for tid in team_ids], reverse=True
    )
    fourth_place_wins = wins_list[PLAYOFF_SPOTS - 1] if len(wins_list) >= PLAYOFF_SPOTS else 0
    total_teams = len(team_ids)

    # ── Upsert rows ───────────────────────────────────────────────────────────
    # Delete any existing entries for this league+week so compute is idempotent
    db.query(PowerRanking).filter(
        PowerRanking.league_id == league_id,
        PowerRanking.week      == week,
    ).delete(synchronize_session=False)
    db.flush()

    inserted: list[PowerRanking] = []
    for i, tid in enumerate(team_ids):
        od = on_field_data[tid]
        bd = betting_data[tid]
        wd = waiver_data[tid]

        rank_change = None
        if tid in prev_ranks:
            rank_change = prev_ranks[tid] - composite_ranks[i]  # +n = moved up

        status = _pr_status(
            composite_ranks[i], total_teams,
            od["wins"], week, fourth_place_wins,
        )

        row = PowerRanking(
            league_id            = league_id,
            week                 = week,
            team_id              = tid,
            on_field_rank        = on_field_ranks[i],
            on_field_score       = round(on_field_scores[i], 4),
            wins                 = od["wins"],
            losses               = od["losses"],
            points_for           = round(od["pf"], 2),
            points_against       = round(od["pa"], 2),
            sos                  = round(od["sos"], 4),
            betting_rank         = betting_ranks[i],
            betting_score        = round(betting_scores[i], 4),
            bet_wins             = bd["bet_wins"],
            bet_losses           = bd["bet_losses"],
            roi                  = round(bd["roi"], 4),
            best_win_amount      = bd["best_win_amount"],
            worst_loss_amount    = bd["worst_loss_amount"],
            bet_streak           = bd["bet_streak"],
            waiver_rank          = waiver_ranks[i],
            waiver_score         = round(waiver_scores[i], 4),
            waiver_dollars_spent = wd["dollars_spent"],
            waiver_pts_added     = wd["pts_added"],
            pts_per_dollar       = wd["pts_per_dollar"],
            composite_rank       = composite_ranks[i],
            composite_score      = round(composite_raw[i], 4),
            rank_change          = rank_change,
            status_tag           = status,
        )
        db.add(row)
        inserted.append(row)

    db.commit()
    for row in inserted:
        db.refresh(row)

    out = sorted(
        [_to_out(row, team_by_id[row.team_id]) for row in inserted],
        key=lambda r: r.composite_rank,
    )

    _post_rankings_to_feed(league_id, week, out, db)
    return out


# ── Read functions ────────────────────────────────────────────────────────────

def get_power_rankings(league_id: int, week: int, db: Session) -> list[PowerRankingOut]:
    """Retrieve stored rankings for a specific week, sorted by composite_rank."""
    rows = (
        db.query(PowerRanking)
        .filter(PowerRanking.league_id == league_id, PowerRanking.week == week)
        .all()
    )
    if not rows:
        return []

    team_ids = [r.team_id for r in rows]
    teams = {t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()}

    out = [_to_out(r, teams[r.team_id]) for r in rows if r.team_id in teams]
    return sorted(out, key=lambda r: r.composite_rank)


def get_team_ranking_history(
    league_id: int,
    team_id:   int,
    db:        Session,
    limit:     int = 17,
) -> list[PowerRankingOut]:
    """Return all weekly ranking snapshots for one team, ordered by week ascending."""
    rows = (
        db.query(PowerRanking)
        .filter(PowerRanking.league_id == league_id, PowerRanking.team_id == team_id)
        .order_by(PowerRanking.week)
        .limit(limit)
        .all()
    )
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        return []
    return [_to_out(r, team) for r in rows]


def get_league_arc(league_id: int, db: Session) -> dict[int, list[PowerRankingOut]]:
    """
    Return all computed weekly rankings keyed by week.
    Useful for visualising the season-long arc.
    """
    rows = (
        db.query(PowerRanking)
        .filter(PowerRanking.league_id == league_id)
        .order_by(PowerRanking.week, PowerRanking.composite_rank)
        .all()
    )

    team_ids = list({r.team_id for r in rows})
    teams = {t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()} if team_ids else {}

    arc: dict[int, list[PowerRankingOut]] = {}
    for row in rows:
        team = teams.get(row.team_id)
        if not team:
            continue
        arc.setdefault(row.week, []).append(_to_out(row, team))

    return arc


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    parser = argparse.ArgumentParser(description="Power Rankings smoke test")
    parser.add_argument("--league", type=int, default=1)
    parser.add_argument("--week",   type=int, required=True)
    args = parser.parse_args()

    from db.schema import SessionLocal

    with SessionLocal() as db:
        print(f"Computing power rankings for league={args.league} week={args.week} …")
        rankings = compute_power_rankings(args.league, args.week, db)

        print(f"\n{'═'*80}")
        print(f"  Week {args.week} Power Rankings — Fantasy Beefs")
        print(f"{'═'*80}\n")

        headers = ["#", "Team", "Status", "On-Field", "Betting", "Waiver", "Composite", "Δ"]
        widths  = [2, 26, 10, 9, 9, 9, 10, 5]

        def _col(v: str, w: int) -> str:
            return str(v)[:w].ljust(w)

        sep_top = "┌" + "┬".join("─" * (w + 2) for w in widths) + "┐"
        sep_mid = "├" + "┼".join("─" * (w + 2) for w in widths) + "┤"
        sep_bot = "└" + "┴".join("─" * (w + 2) for w in widths) + "┘"

        def _row(cells: list[str]) -> str:
            parts = [f" {_col(c, widths[i])} " for i, c in enumerate(cells)]
            return "│" + "│".join(parts) + "│"

        print(sep_top)
        print(_row(headers))
        print(sep_mid)
        for r in rankings:
            delta = (f"+{r.rank_change}" if r.rank_change and r.rank_change > 0
                     else str(r.rank_change) if r.rank_change is not None else "—")
            tag = {"contender": "🔥", "bubble": "👀", "spoiler": "😤", "chaos": "🍖"}.get(r.status_tag, "?")
            row_cells = [
                str(r.composite_rank),
                r.team_name,
                f"{tag} {r.status_tag}"[:10],
                f"#{r.on_field_rank} {r.on_field_score:.3f}",
                f"#{r.betting_rank} {r.betting_score:.3f}",
                f"#{r.waiver_rank} {r.waiver_score:.3f}",
                f"{r.composite_score:.4f}",
                delta,
            ]
            print(_row(row_cells))
        print(sep_bot)

        print(f"\n  {len(rankings)} teams ranked  |  feed event posted")
        print()
        for r in rankings:
            change_str = (f"  (↑{r.rank_change})" if r.rank_change and r.rank_change > 0
                          else f"  (↓{abs(r.rank_change)})" if r.rank_change and r.rank_change < 0
                          else "  (new)")
            print(f"  #{r.composite_rank:2}  {r.team_name:<26}  W{r.wins}-L{r.losses}  "
                  f"PF:{r.points_for:>7.1f}  SOS:{r.sos:.3f}  "
                  f"Bet:{r.bet_wins}W/{r.bet_losses}L  ROI:{r.roi:+.2%}  "
                  f"Streak:{r.bet_streak:+d}{change_str}")
