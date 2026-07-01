"""
Mode 3 weekly pool engine.

Three pots per week, each funded by (weekly_entry * num_teams) / 3:

  Biggest Winner     — team whose score beats the most other teams' scores
  Worst Beat         — loser with the largest point-differential loss;
                       GMs predict this one ahead of time (prediction window Thursday)
  Special Teams      — team with highest combined K + DEF actual points

Worst Beat pot rolls over when no GM predicts correctly (if worst_beat_rollover=True),
or is split evenly among all GMs (if False).

Usage:
  setup_pool_config(league_id, weekly_entry=10.0, worst_beat_rollover=True, db=db)
  collect_weekly_entries(league_id, week, db)
  submit_worst_beat_prediction(league_id, team_id, predicted_team_id, week, db)
  settle_pool(league_id, week, db)
"""

from __future__ import annotations

import logging
import os
import sys
import zoneinfo
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import (
    League,
    Matchup,
    NflSchedule,
    PoolBetPick,
    PoolConfig,
    PoolPot,
    PoolPrediction,
    Projection,
    Roster,
    SessionLocal,
    Team,
    Transaction,
    Wallet,
)

SEASON = 2024
SOURCE = "fantasypros"

# ── Pool bet-type registry ─────────────────────────────────────────────────────

_ET = zoneinfo.ZoneInfo("America/New_York")

# Thursday 8:20 PM ET for NFL 2024 week 1 (first SNF kickoff that opened the week)
_NFL_2024_W1_LOCK = datetime(2024, 9, 5, 20, 20, 0, tzinfo=_ET)

POOL_BET_TYPES: list[dict] = [
    {"key": "biggest_winner", "label": "Biggest Winner",        "self_pick_allowed": True},
    {"key": "worst_beat",     "label": "Worst Beat",            "self_pick_allowed": False},
    {"key": "special_teams",  "label": "Special Teams Supremacy","self_pick_allowed": False},
    {"key": "bench_burn",     "label": "Bench Burn",            "self_pick_allowed": False},
]
_VALID_BET_TYPES = {b["key"] for b in POOL_BET_TYPES}


_log = logging.getLogger(__name__)


def _nfl_lock_time(season: int, week: int) -> datetime:
    """
    Returns the kickoff time of the earliest game for the given NFL season/week.

    Primary path — NflSchedule populated: queries MIN(kickoff_utc) across all
    games for that season/week.  Handles any opener day automatically (Wednesday
    openers, Thursday international games, etc.).

    Fallback — NflSchedule not yet synced for that season/week: uses the
    hardcoded 2024 Thursday 8:20 PM ET formula (season 2024 only; raises
    ValueError for any other season).  Logs a WARNING so an unsynced week
    does not fail silently.
    """
    with SessionLocal() as _db:
        earliest = (
            _db.query(func.min(NflSchedule.kickoff_utc))
            .filter(NflSchedule.season == season, NflSchedule.week == week)
            .scalar()
        )

    if earliest is not None:
        # SQLite stores datetimes as naive strings; Postgres returns tz-aware.
        # Normalise to UTC-aware so callers can always compare against utcnow().
        if earliest.tzinfo is None:
            earliest = earliest.replace(tzinfo=timezone.utc)
        return earliest

    # ── Fallback: no NflSchedule rows for this season/week ────────────────────
    _log.warning(
        "_nfl_lock_time fallback: NflSchedule has no rows for season=%s week=%s. "
        "Run upsert_week_schedule() to populate schedule data. "
        "Using hardcoded 2024 Thursday formula.",
        season, week,
    )
    if season == 2024:
        return _NFL_2024_W1_LOCK + timedelta(weeks=week - 1)
    raise ValueError(f"No lock_time formula defined for season {season}")


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class PoolConfigOut:
    league_id:           int
    weekly_entry:        float
    worst_beat_rollover: bool


@dataclass
class PoolEntryResult:
    week:          int
    teams_charged: int
    total_pot:     float
    per_bet_share: float


@dataclass
class PoolPredictionOut:
    team_id:                      int
    team_name:                    str
    predicted_worst_beat_team_id: int | None
    predicted_worst_beat_name:    str | None
    submitted_at:                 str


@dataclass
class PoolSettlementResult:
    week:              int
    biggest_winner:    dict
    worst_beat:        dict
    special_teams:     dict
    total_distributed: float
    rolled_over_amount: float


# ── Config ────────────────────────────────────────────────────────────────────

def setup_pool_config(
    league_id:           int,
    weekly_entry:        float,
    worst_beat_rollover: bool,
    db:                  Session,
) -> PoolConfigOut:
    """Create or update PoolConfig for a league. Safe to call multiple times."""
    if weekly_entry <= 0:
        raise ValueError("weekly_entry must be positive")

    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == league_id).first()
    if cfg is None:
        cfg = PoolConfig(league_id=league_id)
        db.add(cfg)

    cfg.weekly_entry        = round(weekly_entry, 2)
    cfg.worst_beat_rollover = worst_beat_rollover
    db.commit()
    return _cfg_out(cfg)


def get_pool_config(league_id: int, db: Session) -> PoolConfigOut:
    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == league_id).first()
    if not cfg:
        raise ValueError(f"Pool not configured for league {league_id}. Call setup_pool_config first.")
    return _cfg_out(cfg)


def _cfg_out(cfg: PoolConfig) -> PoolConfigOut:
    return PoolConfigOut(
        league_id           = cfg.league_id,
        weekly_entry        = cfg.weekly_entry,
        worst_beat_rollover = bool(cfg.worst_beat_rollover),
    )


# ── Collection ────────────────────────────────────────────────────────────────

def collect_weekly_entries(league_id: int, week: int, db: Session) -> PoolEntryResult:
    """
    Debit weekly_entry from every team's bet wallet.
    Idempotent guard: raises ValueError if already collected for this week.
    Carries forward any worst-beat rollover from prior settled pots.
    """
    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == league_id).first()
    if not cfg:
        raise ValueError(f"Pool not configured for league {league_id}")

    # Idempotent guard
    existing = db.query(PoolPot).filter(
        PoolPot.league_id == league_id,
        PoolPot.week      == week,
    ).first()
    if existing and existing.entries_collected:
        raise ValueError(f"Pool entries already collected for league {league_id} week {week}")

    teams = db.query(Team).filter(Team.league_id == league_id).order_by(Team.id).all()
    if not teams:
        raise ValueError(f"No teams found in league {league_id}")

    now = datetime.now(timezone.utc)

    # Carry forward rollover from prior settled pots that still hold an amount
    prior_pots = (
        db.query(PoolPot)
        .filter(
            PoolPot.league_id                  == league_id,
            PoolPot.week                       <  week,
            PoolPot.settled                    == True,
            PoolPot.worst_beat_rollover_amount >  0,
        )
        .all()
    )
    accumulated_rollover = round(sum(p.worst_beat_rollover_amount for p in prior_pots), 2)
    for p in prior_pots:
        p.worst_beat_rollover_amount = 0.0  # consume into new pot

    # Debit each team
    charged = 0
    for team in teams:
        wallet = db.query(Wallet).filter(Wallet.team_id == team.id).first()
        if not wallet:
            continue
        wallet.balance = round(wallet.balance - cfg.weekly_entry, 2)
        db.add(Transaction(
            wallet_id  = wallet.id,
            amount     = -cfg.weekly_entry,
            type       = "pool_entry",
            created_at = now,
        ))
        charged += 1

    total_pot     = round(cfg.weekly_entry * charged, 2)
    per_bet_share = round(total_pot / 3, 2)

    # Create or update PoolPot
    pot = existing or PoolPot(league_id=league_id, week=week)
    pot.worst_beat_rollover_amount = accumulated_rollover
    pot.entries_collected          = True
    pot.settled                    = False
    if pot.id is None:
        db.add(pot)

    db.commit()

    return PoolEntryResult(
        week          = week,
        teams_charged = charged,
        total_pot     = total_pot,
        per_bet_share = per_bet_share,
    )


# ── Predictions ───────────────────────────────────────────────────────────────

def submit_worst_beat_prediction(
    league_id:         int,
    team_id:           int,
    predicted_team_id: int,
    week:              int,
    db:                Session,
) -> PoolPredictionOut:
    """Upsert a GM's worst-beat prediction for the week. No self-picks."""
    if predicted_team_id == team_id:
        raise ValueError("A GM cannot predict their own team as Worst Beat")

    # Validate predicted team exists in this league
    predicted_team = db.query(Team).filter(
        Team.id        == predicted_team_id,
        Team.league_id == league_id,
    ).first()
    if not predicted_team:
        raise ValueError(f"Team {predicted_team_id} not found in league {league_id}")

    submitting_team = db.query(Team).filter(Team.id == team_id).first()
    if not submitting_team:
        raise ValueError(f"Team {team_id} not found")

    now = datetime.now(timezone.utc)

    # Upsert: delete existing prediction for this team/week then insert fresh
    existing = db.query(PoolPrediction).filter(
        PoolPrediction.league_id == league_id,
        PoolPrediction.team_id   == team_id,
        PoolPrediction.week      == week,
    ).first()
    if existing:
        existing.predicted_worst_beat_team_id = predicted_team_id
        existing.submitted_at                 = now
        pred = existing
    else:
        pred = PoolPrediction(
            league_id                    = league_id,
            team_id                      = team_id,
            week                         = week,
            predicted_worst_beat_team_id = predicted_team_id,
            submitted_at                 = now,
        )
        db.add(pred)

    db.commit()

    return PoolPredictionOut(
        team_id                      = team_id,
        team_name                    = submitting_team.team_name,
        predicted_worst_beat_team_id = predicted_team_id,
        predicted_worst_beat_name    = predicted_team.team_name,
        submitted_at                 = now.isoformat(),
    )


def get_pool_predictions(league_id: int, week: int, db: Session) -> list[PoolPredictionOut]:
    """Return all predictions submitted for the week (public from Thursday)."""
    preds = (
        db.query(PoolPrediction)
        .filter(PoolPrediction.league_id == league_id, PoolPrediction.week == week)
        .order_by(PoolPrediction.submitted_at)
        .all()
    )
    results = []
    for p in preds:
        team           = db.query(Team).filter(Team.id == p.team_id).first()
        predicted_team = (
            db.query(Team).filter(Team.id == p.predicted_worst_beat_team_id).first()
            if p.predicted_worst_beat_team_id else None
        )
        results.append(PoolPredictionOut(
            team_id                      = p.team_id,
            team_name                    = team.team_name if team else f"team_{p.team_id}",
            predicted_worst_beat_team_id = p.predicted_worst_beat_team_id,
            predicted_worst_beat_name    = predicted_team.team_name if predicted_team else None,
            submitted_at                 = p.submitted_at.isoformat() if p.submitted_at else "",
        ))
    return results


# ── Simulation helpers ────────────────────────────────────────────────────────

def _biggest_winner(league_id: int, week: int, db: Session) -> list[tuple[int, float]]:
    """
    For each team, count how many other teams' actual scores they beat this week.
    Returns list of (team_id, wins_vs_field) for all tied leaders.
    """
    matchups = db.query(Matchup).filter(
        Matchup.league_id == league_id,
        Matchup.week      == week,
    ).all()
    if not matchups:
        return []

    score_map: dict[int, float] = {}
    for m in matchups:
        score_map[m.home_team_id] = m.home_score
        score_map[m.away_team_id] = m.away_score

    wins_map: dict[int, int] = {}
    for team_id, my_score in score_map.items():
        wins_map[team_id] = sum(
            1 for tid, sc in score_map.items() if tid != team_id and my_score > sc
        )

    if not wins_map:
        return []

    max_wins = max(wins_map.values())
    return [(tid, float(w)) for tid, w in wins_map.items() if w == max_wins]


def _worst_beat(league_id: int, week: int, db: Session) -> int:
    """
    Return team_id of the LOSER with the largest point-differential loss.
    Tie-break: team with the lower actual score.
    """
    matchups = db.query(Matchup).filter(
        Matchup.league_id == league_id,
        Matchup.week      == week,
    ).all()
    if not matchups:
        raise ValueError(f"No matchups found for league {league_id} week {week}")

    worst_team_id: int | None = None
    worst_margin  = -1.0
    worst_score   = float("inf")

    for m in matchups:
        margin = abs(m.home_score - m.away_score)
        if m.home_score < m.away_score:
            loser_id, loser_score = m.home_team_id, m.home_score
        else:
            loser_id, loser_score = m.away_team_id, m.away_score

        if margin > worst_margin or (margin == worst_margin and loser_score < worst_score):
            worst_margin  = margin
            worst_team_id = loser_id
            worst_score   = loser_score

    if worst_team_id is None:
        raise ValueError(f"Could not determine worst beat for league {league_id} week {week}")
    return worst_team_id


def _special_teams_score(team_id: int, week: int, db: Session) -> float:
    """Return sum of K actual_points + DEF actual_points (first rostered at each position)."""
    slots = db.query(Roster).filter(Roster.team_id == team_id).order_by(Roster.id).all()
    total = 0.0
    for pos in ("K", "DEF"):
        for slot in slots:
            if slot.player.position == pos:
                proj = db.query(Projection).filter_by(
                    player_id=slot.player_id, week=week, season=SEASON, source=SOURCE
                ).first()
                total += (proj.actual_points if proj else 0.0)
                break
    return round(total, 2)


def _st_breakdown(team_id: int, week: int, db: Session) -> tuple[float, float]:
    """Return (k_pts, def_pts) for a team."""
    slots = db.query(Roster).filter(Roster.team_id == team_id).order_by(Roster.id).all()
    k_pts = def_pts = 0.0
    for pos in ("K", "DEF"):
        for slot in slots:
            if slot.player.position == pos:
                proj = db.query(Projection).filter_by(
                    player_id=slot.player_id, week=week, season=SEASON, source=SOURCE
                ).first()
                val = proj.actual_points if proj else 0.0
                if pos == "K":
                    k_pts = val
                else:
                    def_pts = val
                break
    return round(k_pts, 2), round(def_pts, 2)


# ── Settlement ────────────────────────────────────────────────────────────────

def settle_pool(league_id: int, week: int, db: Session) -> PoolSettlementResult:
    """
    Settle all three pool pots for the week.
    Raises ValueError if entries not yet collected or already settled.
    """
    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == league_id).first()
    if not cfg:
        raise ValueError(f"Pool not configured for league {league_id}")

    pot = db.query(PoolPot).filter(
        PoolPot.league_id == league_id,
        PoolPot.week      == week,
    ).first()
    if not pot or not pot.entries_collected:
        raise ValueError(
            f"Entries not yet collected for league {league_id} week {week}. "
            "Run collect_weekly_entries first."
        )
    if pot.settled:
        raise ValueError(f"Pool already settled for week {week}")

    teams     = db.query(Team).filter(Team.league_id == league_id).order_by(Team.id).all()
    num_teams = len(teams)
    if num_teams == 0:
        raise ValueError(f"No teams found in league {league_id}")

    total_pot     = round(cfg.weekly_entry * num_teams, 2)
    per_bet_share = round(total_pot / 3, 2)
    now           = datetime.now(timezone.utc)

    def _credit(team_id: int, amount: float, note: str) -> None:
        wallet = db.query(Wallet).filter(Wallet.team_id == team_id).first()
        if not wallet:
            return
        wallet.balance = round(wallet.balance + amount, 2)
        db.add(Transaction(
            wallet_id  = wallet.id,
            amount     = amount,
            type       = "pool_payout",
            created_at = now,
        ))

    # ── Pot 1: Biggest Winner ─────────────────────────────────────────────────
    bw_results    = _biggest_winner(league_id, week, db)
    num_bw        = len(bw_results)
    bw_each       = round(per_bet_share / num_bw, 2) if num_bw else 0.0
    bw_winner_id  = bw_results[0][0] if bw_results else None
    bw_wins       = bw_results[0][1] if bw_results else 0.0

    for tid, _ in bw_results:
        _credit(tid, bw_each, f"Biggest Winner pool payout week {week}")

    bw_winner_team = db.query(Team).filter(Team.id == bw_winner_id).first() if bw_winner_id else None
    biggest_winner_info = {
        "winner_team_id":  bw_winner_id,
        "winner_name":     bw_winner_team.team_name if bw_winner_team else None,
        "record_vs_field": bw_wins,
        "payout":          round(bw_each * num_bw, 2),
    }

    # ── Pot 2: Worst Beat ─────────────────────────────────────────────────────
    actual_worst_id = _worst_beat(league_id, week, db)

    correct_preds = db.query(PoolPrediction).filter(
        PoolPrediction.league_id                    == league_id,
        PoolPrediction.week                         == week,
        PoolPrediction.predicted_worst_beat_team_id == actual_worst_id,
    ).all()
    num_correct = len(correct_preds)

    existing_rollover   = round(pot.worst_beat_rollover_amount, 2)
    wb_total_pool       = round(per_bet_share + existing_rollover, 2)
    wb_payout_each      = 0.0
    wb_rolled_over      = 0.0

    if num_correct > 0:
        wb_payout_each = round(wb_total_pool / num_correct, 2)
        for pred in correct_preds:
            _credit(pred.team_id, wb_payout_each, f"Worst Beat prediction payout week {week}")
        pot.worst_beat_rollover_amount = 0.0
    elif bool(cfg.worst_beat_rollover):
        pot.worst_beat_rollover_amount = wb_total_pool
        wb_rolled_over = wb_total_pool
    else:
        split_each = round(wb_total_pool / num_teams, 2)
        for team in teams:
            _credit(team.id, split_each, f"Worst Beat no-winner split week {week}")
        pot.worst_beat_rollover_amount = 0.0

    worst_beat_info = {
        "actual_worst_team_id": actual_worst_id,
        "correct_predictors":   num_correct,
        "payout_each":          wb_payout_each,
        "rolled_over":          wb_rolled_over > 0,
    }

    # ── Pot 3: Special Teams Supremacy ────────────────────────────────────────
    st_scores: list[tuple[int, float]] = [
        (team.id, _special_teams_score(team.id, week, db)) for team in teams
    ]
    max_st     = max(sc for _, sc in st_scores)
    st_winners = [(tid, sc) for tid, sc in st_scores if sc == max_st]
    num_st     = len(st_winners)
    st_each    = round(per_bet_share / num_st, 2) if num_st else 0.0

    for tid, _ in st_winners:
        _credit(tid, st_each, f"Special Teams Supremacy payout week {week}")

    st_winner_id   = st_winners[0][0] if st_winners else None
    st_winner_team = db.query(Team).filter(Team.id == st_winner_id).first() if st_winner_id else None
    st_k, st_def   = _st_breakdown(st_winner_id, week, db) if st_winner_id else (0.0, 0.0)

    special_teams_info = {
        "winner_team_id": st_winner_id,
        "winner_name":    st_winner_team.team_name if st_winner_team else None,
        "k_pts":          st_k,
        "def_pts":        st_def,
        "total_pts":      round(max_st, 2),
        "payout":         round(st_each * num_st, 2),
    }

    # ── Mark settled ──────────────────────────────────────────────────────────
    pot.settled    = True
    pot.settled_at = now
    db.commit()

    wb_distributed = 0.0
    if num_correct > 0:
        wb_distributed = round(wb_payout_each * num_correct, 2)
    elif not bool(cfg.worst_beat_rollover):
        wb_distributed = wb_total_pool

    total_distributed = round(
        round(bw_each * num_bw, 2) + wb_distributed + round(st_each * num_st, 2),
        2,
    )

    return PoolSettlementResult(
        week               = week,
        biggest_winner     = biggest_winner_info,
        worst_beat         = worst_beat_info,
        special_teams      = special_teams_info,
        total_distributed  = total_distributed,
        rolled_over_amount = wb_rolled_over,
    )


# ── Pool week view (all 4 bets + pick states) ─────────────────────────────────

@dataclass
class PoolTeamOut:
    team_id:   int
    team_name: str
    owner:     str


@dataclass
class PoolPickStateOut:
    team_id:          int
    team_name:        str
    picked_team_id:   Optional[int]
    picked_team_name: Optional[str]


@dataclass
class PoolBetTypeOut:
    bet_type:          str
    label:             str
    self_pick_allowed: bool
    picks:             list  # list[PoolPickStateOut]


@dataclass
class PoolWeekOut:
    week:      int
    league_id: int
    lock_time: str   # ISO-8601 with tz
    locked:    bool
    bets:      list  # list[PoolBetTypeOut]
    teams:     list  # list[PoolTeamOut]


def get_pool_week(league_id: int, week: int, db: Session) -> PoolWeekOut:
    """
    Return all 4 pool bets for the week with every GM's current pick state.
    lock_time is read from PoolPot.lock_time if set, else computed from the
    NFL 2024 schedule formula (Thursday 8:20 PM ET).
    """
    league = db.query(League).filter(League.id == league_id).first()
    if not league:
        raise ValueError(f"League {league_id} not found")

    teams = db.query(Team).filter(Team.league_id == league_id).order_by(Team.id).all()
    if not teams:
        raise ValueError(f"No teams found in league {league_id}")

    pot = db.query(PoolPot).filter(
        PoolPot.league_id == league_id,
        PoolPot.week      == week,
    ).first()

    lock_dt = (pot.lock_time if pot and pot.lock_time else _nfl_lock_time(league.season, week))
    now     = datetime.now(timezone.utc)
    locked  = now >= lock_dt.astimezone(timezone.utc)

    team_map = {t.id: t for t in teams}

    all_picks = (
        db.query(PoolBetPick)
        .filter(PoolBetPick.league_id == league_id, PoolBetPick.week == week)
        .all()
    )
    pick_index: dict[tuple[int, str], PoolBetPick] = {
        (p.team_id, p.bet_type): p for p in all_picks
    }

    bet_type_outs = []
    for bt in POOL_BET_TYPES:
        pick_states = []
        for team in teams:
            pick            = pick_index.get((team.id, bt["key"]))
            picked_team_id  = pick.picked_team_id if pick else None
            picked_team_name = (
                team_map[picked_team_id].team_name
                if picked_team_id and picked_team_id in team_map
                else None
            )
            pick_states.append(PoolPickStateOut(
                team_id          = team.id,
                team_name        = team.team_name,
                picked_team_id   = picked_team_id,
                picked_team_name = picked_team_name,
            ))
        bet_type_outs.append(PoolBetTypeOut(
            bet_type          = bt["key"],
            label             = bt["label"],
            self_pick_allowed = bt["self_pick_allowed"],
            picks             = pick_states,
        ))

    team_outs = [
        PoolTeamOut(team_id=t.id, team_name=t.team_name, owner=t.owner)
        for t in teams
    ]

    return PoolWeekOut(
        week      = week,
        league_id = league_id,
        lock_time = lock_dt.isoformat(),
        locked    = locked,
        bets      = bet_type_outs,
        teams     = team_outs,
    )


def submit_pool_pick(
    league_id:    int,
    team_id:      int,
    bet_type:     str,
    pick_team_id: Optional[int],
    week:         int,
    db:           Session,
) -> PoolPickStateOut:
    """
    Upsert a GM's pick for one of the 4 pool bet types.
    pick_team_id=None resets the pick to unpicked.
    Raises ValueError if: window closed, self-pick blocked, invalid team, invalid bet_type.
    """
    if bet_type not in _VALID_BET_TYPES:
        raise ValueError(f"Invalid bet_type {bet_type!r}. Must be one of: {sorted(_VALID_BET_TYPES)}")

    league = db.query(League).filter(League.id == league_id).first()
    if not league:
        raise ValueError(f"League {league_id} not found")

    pot = db.query(PoolPot).filter(
        PoolPot.league_id == league_id, PoolPot.week == week,
    ).first()
    lock_dt = (pot.lock_time if pot and pot.lock_time else _nfl_lock_time(league.season, week))
    if datetime.now(timezone.utc) >= lock_dt.astimezone(timezone.utc):
        raise ValueError(f"Pick window is closed for week {week} (locked at {lock_dt.isoformat()})")

    submitting_team = db.query(Team).filter(
        Team.id == team_id, Team.league_id == league_id,
    ).first()
    if not submitting_team:
        raise ValueError(f"Team {team_id} not found in league {league_id}")

    picked_team: Optional[Team] = None
    if pick_team_id is not None:
        bt_cfg = next(b for b in POOL_BET_TYPES if b["key"] == bet_type)
        if not bt_cfg["self_pick_allowed"] and pick_team_id == team_id:
            raise ValueError(f"Self-pick not allowed for {bet_type}")
        picked_team = db.query(Team).filter(
            Team.id == pick_team_id, Team.league_id == league_id,
        ).first()
        if not picked_team:
            raise ValueError(f"Pick team {pick_team_id} not found in league {league_id}")

    now      = datetime.now(timezone.utc)
    existing = db.query(PoolBetPick).filter(
        PoolBetPick.league_id == league_id,
        PoolBetPick.team_id   == team_id,
        PoolBetPick.bet_type  == bet_type,
        PoolBetPick.week      == week,
    ).first()

    if existing:
        existing.picked_team_id = pick_team_id
        existing.submitted_at   = now
    else:
        db.add(PoolBetPick(
            league_id      = league_id,
            team_id        = team_id,
            bet_type       = bet_type,
            picked_team_id = pick_team_id,
            week           = week,
            submitted_at   = now,
        ))

    db.commit()

    return PoolPickStateOut(
        team_id          = team_id,
        team_name        = submitting_team.team_name,
        picked_team_id   = pick_team_id,
        picked_team_name = picked_team.team_name if picked_team else None,
    )
