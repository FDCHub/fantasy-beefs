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
  setup_pool_config(league_id, weekly_entry_cents=1000, worst_beat_rollover=True, db=db)
  collect_weekly_entries(league_id, week, db)
  submit_worst_beat_prediction(league_id, team_id, predicted_team_id, week, db)
  settle_pool(league_id, week, db)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from betting.exceptions import ScheduleNotReadyError
from betting.pool_legacy_guard import assert_legacy_pool_path_allowed
from db.schema import (
    League,
    Matchup,
    NflSchedule,
    PoolBetPick,
    PoolConfig,
    PoolPot,
    PoolPrediction,
    Projection,
    SessionLocal,
    Team,
    Transaction,
    Wallet,
)
from db.roster_read import _roster_for_week
from ledger.ledger import post as ledger_post, balance_of

from config import CURRENT_SEASON as SEASON
SOURCE = "fantasypros"

# ── Pool bet-type registry ─────────────────────────────────────────────────────

# bench_burn was retired from Pool scope by SPEC_Pool_Catalog_Rotation_POR_Rev1_0
# §1.1: a legacy implementation name, never one of the 96 classified catalog
# definitions, carried here with no evaluator and no settlement branch. It was
# selectable through submit_pool_pick and nothing could ever settle the pick.
# POR §11.5 requires it be unreachable as a Pool.
#
# Removing the row is the whole retirement. PoolBetPick.bet_type is a plain
# String column with no CHECK constraint (db/schema.py:1114), so historical rows
# carrying 'bench_burn' remain readable by direct query; they simply no longer
# appear in get_pool_week's per-type output and no new ones can be written.
# No replacement definition is added here — the catalog is a separate step.
POOL_BET_TYPES: list[dict] = [
    {"key": "biggest_winner", "label": "Biggest Winner",        "self_pick_allowed": True},
    {"key": "worst_beat",     "label": "Worst Beat",            "self_pick_allowed": False},
    {"key": "special_teams",  "label": "Special Teams Supremacy","self_pick_allowed": False},
]
_VALID_BET_TYPES = {b["key"] for b in POOL_BET_TYPES}


def _assert_league_exists(league_id: int, db: Session) -> League:
    league = db.query(League).filter(League.id == league_id).first()
    if not league:
        raise ValueError(f"League {league_id} not found")
    return league


def _nfl_lock_time(season: int, week: int) -> datetime:
    """
    Returns the kickoff time of the earliest game for the given NFL season/week.

    Primary path — NflSchedule populated: queries MIN(kickoff_utc) across all
    games for that season/week.  Handles any opener day automatically (Wednesday
    openers, Thursday international games, etc.).

    Raises ScheduleNotReadyError if:
      - the week has no NflSchedule rows at all (not loaded — run
        upsert_week_schedule() first), or
      - the week is loaded but its earliest kickoff falls outside the real
        NFL kickoff window (placeholder timestamps ESPN hasn't replaced yet
        with announced times).
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

        # A real NFL kickoff sits between 09:00 UTC and 02:00 UTC the next
        # day. Fold hours below 9 up by 24 so that window is one contiguous
        # band, [9, 26], instead of wrapping past midnight. A kickoff outside
        # that band means the week is loaded but ESPN hasn't announced real
        # times yet — only placeholder timestamps are present.
        hour = earliest.hour
        if hour < 9:
            hour += 24
        if not (9 <= hour <= 26):
            raise ScheduleNotReadyError(
                f"season={season} week={week}: schedule is loaded but only has "
                f"placeholder kickoff times (earliest={earliest.isoformat()}) — "
                f"ESPN has not announced real times yet. The next refresh will "
                f"pick them up once ESPN sets them."
            )

        return earliest

    raise ScheduleNotReadyError(
        f"season={season} week={week}: NFL schedule not loaded — "
        f"run upsert_week_schedule() first."
    )


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class PoolConfigOut:
    league_id:           int
    weekly_entry:        float
    weekly_entry_cents:  int
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
    weekly_entry_cents:  int,
    worst_beat_rollover: bool,
    db:                  Session,
) -> PoolConfigOut:
    """Create or update PoolConfig for a league. Safe to call multiple times."""
    if weekly_entry_cents <= 0:
        raise ValueError("weekly_entry_cents must be positive")

    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == league_id).first()
    if cfg is None:
        cfg = PoolConfig(league_id=league_id)
        db.add(cfg)

    cfg.weekly_entry_cents  = weekly_entry_cents
    cfg.worst_beat_rollover = worst_beat_rollover
    db.commit()
    return _cfg_out(cfg)


def get_pool_config(league_id: int, db: Session) -> PoolConfigOut:
    _assert_league_exists(league_id, db)
    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == league_id).first()
    if not cfg:
        raise ValueError(f"Pool not configured for league {league_id}. Call setup_pool_config first.")
    return _cfg_out(cfg)


def _cfg_out(cfg: PoolConfig) -> PoolConfigOut:
    return PoolConfigOut(
        league_id           = cfg.league_id,
        weekly_entry        = cfg.weekly_entry_cents / 100,
        weekly_entry_cents  = cfg.weekly_entry_cents,
        worst_beat_rollover = bool(cfg.worst_beat_rollover),
    )


# ── Collection ────────────────────────────────────────────────────────────────

def collect_weekly_entries(league_id: int, week: int, db: Session) -> PoolEntryResult:
    """
    Debit weekly_entry from every team's bet wallet.
    Idempotent guard: raises ValueError if already collected for this week.
    Carries forward any worst-beat rollover from prior settled pots.
    """
    # S4-P2-1 — fail closed if this league is governed by the Rev1.3 common
    # Pool engine. Runs BEFORE the week claim, the wallet debits and every
    # ledger posting below, so a refused attempt writes nothing at all. See
    # betting/pool_legacy_guard.py for why the guard is league-scoped.
    assert_legacy_pool_path_allowed(db, league_id, week)

    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == league_id).first()
    if not cfg:
        raise ValueError(f"Pool not configured for league {league_id}")

    # ── Atomic week claim ─────────────────────────────────────────────────────
    # Replaces a read-then-write guard that was unsound under contention: two
    # concurrent callers both read `existing = None`, both ran the debit loop
    # below, and one lost at commit on uq_pool_pot_league_week — surfacing as
    # IntegrityError rather than the domain ValueError this function documents.
    #
    # Modeled on WeekSettlement's claim (settlement_engine.py:353-362) with one
    # deliberate difference: that one commits immediately at :362. THIS ONE MUST
    # NOT, and the difference is a money-path property, not a style choice.
    # entries_collected is read OUTSIDE this transaction as evidence that every
    # team was actually charged — settle_pool at :538, and
    # shortfall_sweep._compute_wagered_cents at :90, which credits each team a
    # weekly entry toward its wagering minimum purely on the strength of this
    # flag. Committing the claim early would publish that evidence before a
    # single cent moved, and would strand the flag TRUE so no later attempt
    # could re-claim the week.
    #
    # Staying inside this function's single transaction means a losing caller
    # BLOCKS on the conflicting row instead of racing it, and then resolves
    # correctly either way: the winner commits and the loser's WHERE finds
    # entries_collected already TRUE (zero rows -> the ValueError below), or the
    # winner rolls back and the loser claims the week itself. So the flag still
    # means COMPLETED to every reader outside; only inside this transaction does
    # it additionally mean CLAIMED, and nothing inside reads it.
    #
    # All five values are supplied explicitly: SQLAlchemy's Column(default=...)
    # is client-side, so the create_all DDL carries no server DEFAULT.
    #
    # IS NOT TRUE, not `= FALSE`. entries_collected is a NULLABLE column
    # (db/schema.py:1040), and the guard this replaced tested Python truthiness —
    # `if existing and existing.entries_collected` — under which BOTH False and
    # None fell through and the week was re-collectable. `= FALSE` would evaluate
    # to NULL against a NULL column and refuse the claim, silently narrowing that
    # retry path and stranding any legacy row carrying NULL. The truth table
    # required, and verified on both backends, is:
    #     TRUE  -> refuse    FALSE -> claim    NULL -> claim
    # Verified 2026-07-31 on SQLite 3.50.4 (the legacy pool suite's backend) and
    # PostgreSQL 16.14, upsert-rehearsed against pre-existing TRUE/FALSE/NULL
    # rows. One statement, no dialect branch.
    claimed = db.execute(
        text("""
            INSERT INTO pool_pots
                (league_id, week, entries_collected, worst_beat_rollover_cents, settled)
            VALUES (:league_id, :week, TRUE, 0, FALSE)
            ON CONFLICT (league_id, week) DO UPDATE
               SET entries_collected = TRUE
             WHERE pool_pots.entries_collected IS NOT TRUE
            RETURNING id
        """),
        {"league_id": league_id, "week": week},
    ).fetchone()
    if claimed is None:
        raise ValueError(f"Pool entries already collected for league {league_id} week {week}")

    # FC-6b (Opus): refuse to collect a new week's entries while ANY earlier
    # week for this league is still unsettled — not just the immediately
    # preceding one. A preceding-week-only check would miss week W-2 sitting
    # unsettled while W-1 got settled, and that stale W-2 money would still
    # be in pool:{league_id}, polluting the balance the FC-2 guard in
    # settle_pool() checks. Must run before any posting below.
    unsettled_prior = db.query(PoolPot).filter(
        PoolPot.league_id == league_id,
        PoolPot.week      <  week,
        PoolPot.settled   == False,
    ).first()
    if unsettled_prior:
        raise ValueError(
            f"Cannot collect week {week} entries for league {league_id} — "
            f"week {unsettled_prior.week} is not yet settled. Settle all "
            f"prior weeks before collecting a new one."
        )

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
            PoolPot.worst_beat_rollover_cents  >  0,
        )
        .all()
    )
    accumulated_rollover_cents = sum(p.worst_beat_rollover_cents for p in prior_pots)
    for p in prior_pots:
        p.worst_beat_rollover_cents = 0  # consume into new pot

    # Door 1 (pool_entry_collected) — per PCM-4's single-deploy migration,
    # PoolConfig.weekly_entry is dropped and weekly_entry_cents is always
    # populated by the time this runs. A null here is a bug, not a state
    # to paper over with a fallback.
    if cfg.weekly_entry_cents is None:
        raise ValueError(
            f"League {league_id} PoolConfig has no weekly_entry_cents — "
            f"migration should guarantee this is populated."
        )
    entry_cents = cfg.weekly_entry_cents
    if entry_cents <= 0:
        raise ValueError(
            f"League {league_id} weekly_entry_cents is {entry_cents} — "
            f"must be positive."
        )

    # Debit each team
    charged = 0
    for team in teams:
        wallet = db.query(Wallet).filter(Wallet.team_id == team.id).first()
        if not wallet:
            raise ValueError(
                f"Team {team.id} in league {league_id} has no wallet — "
                f"cannot collect pool entry. Every team must have a wallet."
            )
        # Ledger posting replaces the old direct wallet.balance mutation.
        # session=db: this function commits once at the end (below), and
        # the ledger write needs to land in that same transaction — see
        # this session's earlier L3 findings on session=None deadlocking
        # against an already-open write transaction on the same
        # connection (db.flush()/db.add() above already opened one).
        ledger_post(
            [
                (f"wallet:{team.id}",     -entry_cents),
                (f"pool:{league_id}",      entry_cents),
            ],
            door="pool_entry_collected",
            session=db,
        )
        db.add(Transaction(
            wallet_id  = wallet.id,
            amount     = -entry_cents / 100,
            type       = "pool_entry",
            created_at = now,
        ))
        charged += 1

    # total_pot (dollars) is derived here only for PoolEntryResult's return
    # value — the persisted fact is total_pot_cents; there's no float
    # column to keep in sync anymore.
    total_pot_cents = entry_cents * charged
    total_pot       = round(total_pot_cents / 100, 2)
    per_bet_share   = round(total_pot / 3, 2)

    # Update the PoolPot claimed above. The claim already inserted-or-updated
    # this week's row inside this same (uncommitted) transaction, so the row is
    # guaranteed to exist and .one() cannot miss it. No db.add() — the row is
    # not new to the transaction, only to the ORM identity map.
    pot = db.query(PoolPot).filter(
        PoolPot.league_id == league_id,
        PoolPot.week      == week,
    ).one()
    pot.worst_beat_rollover_cents = accumulated_rollover_cents
    pot.entries_collected          = True
    pot.settled                    = False
    pot.total_pot_cents             = total_pot_cents

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
    """Upsert a GM's worst-beat prediction for the week. No self-picks.

    WP6C — FAIL-CLOSED FOR A GOVERNED LEAGUE, for the same reason
    `submit_pool_pick` is. This is the other legacy Pool pick write, and Worst
    Beat is itself retired from Pool scope. Leaving it open for a Rev1.3 league
    would preserve exactly the condition WP6C removes: two live meanings for "a
    Pool pick", only one of which settlement can see.
    """
    assert_legacy_pool_path_allowed(db, league_id, week)

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
    """Return sum of K actual_points + DEF actual_points (first rostered at each position).

    Reads the week's roster (RosterSlot snapshot, falling back to static Roster)
    so a settled week scores the K/DEF that were rostered THAT week, not whoever
    is rostered now. The K/DEF match on slot.player.position is a separate
    pre-existing bug and is intentionally left unchanged here.
    """
    slots = _roster_for_week(team_id, week, db)
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
    """Return (k_pts, def_pts) for a team, from the week's roster (RosterSlot
    snapshot, falling back to static Roster). Position matching left as-is."""
    slots = _roster_for_week(team_id, week, db)
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
    # S4-P2-1 — see collect_weekly_entries above. Raises before the
    # reconciliation guard, before _credit() and before any ledger posting.
    assert_legacy_pool_path_allowed(db, league_id, week)

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

    # Read the integer-cents total collection actually persisted — do not
    # recompute weekly_entry_cents * num_teams here. That recompute would pay
    # out for every team in the league, including any that were never
    # debited at collection (walletless, or added after collection ran).
    # total_pot_cents is the frozen fact from collect_weekly_entries().
    if pot.total_pot_cents is None:
        raise ValueError(
            f"Pool pot for league {league_id} week {week} has no "
            f"total_pot_cents — collection never ran or predates conversion."
        )
    total_cents             = pot.total_pot_cents
    existing_rollover_cents = pot.worst_beat_rollover_cents or 0

    # Reconciliation guard — belt-and-suspenders for a single-league
    # honor-system deployment, but the one thing that catches a pot
    # populated by a seed script or manual DB edit rather than a real
    # collect_weekly_entries() run. The ledger balance is ground truth
    # nothing else can fake. Runs before any _credit()/ledger_post() call
    # below, so a mismatch aborts before any money moves.
    #
    # ASSUMPTION: expected_balance accounts for Worst Beat rollover
    # (worst_beat_rollover_cents) as the ONLY mechanism that retains
    # money in pool:{league_id} beyond this week's collection. This
    # is correct today because Worst Beat is the only pool bet type
    # that rolls over. If Bench Burn (or any other pool bet type)
    # ever gains its own rollover/retention mechanism, this formula
    # MUST be updated to sum ALL currently-retained amounts, or this
    # guard will false-positive and block every settlement once that
    # second mechanism retains anything. Flagged per FC-6 (Opus
    # review) — this is a required update when Bench Burn's rollover
    # gets built, not an oversight to catch later.
    pool_balance     = balance_of(f"pool:{league_id}")
    expected_balance = total_cents + existing_rollover_cents
    if pool_balance != expected_balance:
        raise ValueError(
            f"Pool balance mismatch for league {league_id} week {week}: "
            f"ledger holds {pool_balance} cents, but total_pot_cents "
            f"({total_cents}) + existing rollover ({existing_rollover_cents}) "
            f"expects {expected_balance}. This pot may have been populated "
            f"by something other than collect_weekly_entries() — refusing "
            f"to settle against an unreconciled value. (If this league uses "
            f"the standard collection flow, this should not be reachable — "
            f"check for a collection that ran out of order or a direct DB "
            f"edit.)"
        )

    now = datetime.now(timezone.utc)

    def _credit(team_id: int, amount_cents: int, note: str) -> None:
        wallet = db.query(Wallet).filter(Wallet.team_id == team_id).first()
        if not wallet:
            raise ValueError(
                f"Team {team_id} in league {league_id} has no wallet — "
                f"cannot pay pool payout. Every team must have a wallet."
            )
        if amount_cents <= 0:
            raise ValueError(
                f"Team {team_id} credit amount must be positive, got {amount_cents}"
            )
        # Ledger posting replaces the old direct wallet.balance mutation.
        # session=db — same reasoning as collect_weekly_entries(): this
        # function commits once at the end, and the write must land in
        # that same transaction (session=None would deadlock against the
        # already-open write transaction on this connection).
        ledger_post(
            [
                (f"pool:{league_id}",      -amount_cents),
                (f"wallet:{team_id}",       amount_cents),
            ],
            door="pool_payout",
            session=db,
        )
        db.add(Transaction(
            wallet_id  = wallet.id,
            amount     = amount_cents / 100,   # display-only, never fed back into a posting
            type       = "pool_payout",
            created_at = now,
        ))

    def _split_even(team_ids: list[int], total_cents: int) -> dict[int, int]:
        """
        Split `total_cents` evenly among team_ids; each gets
        total_cents // n, and the first team_id (ascending) absorbs the
        floor-division remainder so the amounts sum exactly to
        `total_cents` — no leaked or invented cent. Pool-specific
        remainder rule (first team absorbs) — deliberately NOT Design B's
        championship-sweep rule; these are different contexts (PCM-5).
        """
        ordered = sorted(team_ids)
        n = len(ordered)
        if n == 0:
            return {}
        share = total_cents // n
        amounts = {tid: share for tid in ordered}
        amounts[ordered[0]] = total_cents - share * (n - 1)
        return amounts

    # Penny-exact three-way pot split, in integer cents — floor each share,
    # Special Teams (last pot in settlement order) absorbs the exact
    # remainder so the three shares sum to total_cents exactly.
    share_cents    = total_cents // 3
    bw_share_cents = share_cents
    wb_share_cents = share_cents
    st_share_cents = total_cents - bw_share_cents - wb_share_cents

    # ── Pot 1: Biggest Winner ─────────────────────────────────────────────────
    bw_results   = _biggest_winner(league_id, week, db)
    num_bw       = len(bw_results)
    bw_winner_id = bw_results[0][0] if bw_results else None
    bw_wins      = bw_results[0][1] if bw_results else 0.0

    bw_amounts = _split_even([tid for tid, _ in bw_results], bw_share_cents)
    for tid, amt in bw_amounts.items():
        _credit(tid, amt, f"Biggest Winner pool payout week {week}")

    bw_winner_team = db.query(Team).filter(Team.id == bw_winner_id).first() if bw_winner_id else None
    biggest_winner_info = {
        "winner_team_id":  bw_winner_id,
        "winner_name":     bw_winner_team.team_name if bw_winner_team else None,
        "record_vs_field": bw_wins,
        "payout":          bw_share_cents / 100,
    }

    # ── Pot 2: Worst Beat ─────────────────────────────────────────────────────
    actual_worst_id = _worst_beat(league_id, week, db)

    correct_preds = db.query(PoolPrediction).filter(
        PoolPrediction.league_id                    == league_id,
        PoolPrediction.week                         == week,
        PoolPrediction.predicted_worst_beat_team_id == actual_worst_id,
    ).all()
    num_correct = len(correct_preds)

    # existing_rollover_cents already computed above (before the
    # reconciliation guard) — reused here, not recomputed.
    wb_total_pool_cents = wb_share_cents + existing_rollover_cents
    wb_payout_each          = 0.0
    wb_rolled_over_cents    = 0
    wb_distributed_cents    = 0   # tracked explicitly per-branch below, not reconstructed after the fact

    if num_correct > 0:
        wb_payout_each_cents = wb_total_pool_cents // num_correct
        wb_amounts = _split_even([pred.team_id for pred in correct_preds], wb_total_pool_cents)
        for tid, amt in wb_amounts.items():
            _credit(tid, amt, f"Worst Beat prediction payout week {week}")
        wb_payout_each       = wb_payout_each_cents / 100
        wb_distributed_cents = wb_total_pool_cents
        pot.worst_beat_rollover_cents = 0
    elif bool(cfg.worst_beat_rollover):
        # Week-14 expiry (SP-9): unclaimed after the last regular-season
        # week sweeps to championship instead of rolling forward again.
        # Every other week with no correct predictor just keeps rolling —
        # no posting at all, since pool:{league_id} is a continuous
        # account and never actually lost the money in the first place.
        if week == 14 and num_correct == 0:
            ledger_post(
                [
                    (f"pool:{league_id}",          -wb_total_pool_cents),
                    (f"championship:{league_id}",   wb_total_pool_cents),
                ],
                door="pool_rollover_expiry",
                session=db,
            )
            pot.worst_beat_rollover_cents = 0
        else:
            pot.worst_beat_rollover_cents = wb_total_pool_cents
            wb_rolled_over_cents = wb_total_pool_cents
    else:
        # Predictor-only split (not "pay every team" — that was the old,
        # incorrect behavior). Two distinct sub-cases:
        this_week_preds = db.query(PoolPrediction).filter(
            PoolPrediction.league_id == league_id,
            PoolPrediction.week      == week,
        ).all()
        if len(this_week_preds) == 0:
            # No-predictors sweep: nobody to pay, sweep immediately rather
            # than waiting for week 14 — there's no predictor pool to roll
            # forward for.
            ledger_post(
                [
                    (f"pool:{league_id}",          -wb_total_pool_cents),
                    (f"championship:{league_id}",   wb_total_pool_cents),
                ],
                door="pool_no_predictors_sweep",
                session=db,
            )
        else:
            wb_split_amounts = _split_even(
                [pred.team_id for pred in this_week_preds], wb_total_pool_cents
            )
            for tid, amt in wb_split_amounts.items():
                _credit(tid, amt, f"Worst Beat no-winner predictor split week {week}")
            wb_distributed_cents = wb_total_pool_cents
        pot.worst_beat_rollover_cents = 0

    worst_beat_info = {
        "actual_worst_team_id": actual_worst_id,
        "correct_predictors":   num_correct,
        "payout_each":          wb_payout_each,
        "rolled_over":          wb_rolled_over_cents > 0,
    }

    # ── Pot 3: Special Teams Supremacy ────────────────────────────────────────
    st_scores: list[tuple[int, float]] = [
        (team.id, _special_teams_score(team.id, week, db)) for team in teams
    ]
    max_st     = max(sc for _, sc in st_scores)
    st_winners = [(tid, sc) for tid, sc in st_scores if sc == max_st]

    st_amounts = _split_even([tid for tid, _ in st_winners], st_share_cents)
    for tid, amt in st_amounts.items():
        _credit(tid, amt, f"Special Teams Supremacy payout week {week}")

    st_winner_id   = st_winners[0][0] if st_winners else None
    st_winner_team = db.query(Team).filter(Team.id == st_winner_id).first() if st_winner_id else None
    st_k, st_def   = _st_breakdown(st_winner_id, week, db) if st_winner_id else (0.0, 0.0)

    special_teams_info = {
        "winner_team_id": st_winner_id,
        "winner_name":    st_winner_team.team_name if st_winner_team else None,
        "k_pts":          st_k,
        "def_pts":        st_def,
        "total_pts":      round(max_st, 2),
        "payout":         st_share_cents / 100,
    }

    # ── Mark settled ──────────────────────────────────────────────────────────
    pot.settled    = True
    pot.settled_at = now
    db.commit()

    total_distributed_cents = bw_share_cents + wb_distributed_cents + st_share_cents

    return PoolSettlementResult(
        week               = week,
        biggest_winner     = biggest_winner_info,
        worst_beat         = worst_beat_info,
        special_teams      = special_teams_info,
        total_distributed  = round(total_distributed_cents / 100, 2),
        rolled_over_amount = wb_rolled_over_cents / 100,
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
    league = _assert_league_exists(league_id, db)

    teams = db.query(Team).filter(Team.league_id == league_id).order_by(Team.id).all()
    if not teams:
        raise ValueError(f"No teams found in league {league_id}")

    pot = db.query(PoolPot).filter(
        PoolPot.league_id == league_id,
        PoolPot.week      == week,
    ).first()

    try:
        lock_dt = (pot.lock_time if pot and pot.lock_time else _nfl_lock_time(league.season, week))
    except ScheduleNotReadyError:
        raise ValueError(
            f"Week {week}'s schedule isn't ready yet — pool bets can't be viewed until it is"
        )
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

    RETIRED FROM THE PRODUCT PATH BY WP6C, AND FAIL-CLOSED FOR A GOVERNED
    LEAGUE. `POST /pool/pick` no longer calls this; it adapts into
    `betting.pool_claims.submit_claim` and writes a `PoolClaim`. What this
    writes — a `PoolBetPick` against one of three hardcoded pot names — is read
    by nothing in the Rev1.3 settlement path, so for a league that has crossed
    over to Rev1.3 a row here is a pick that can never be settled and never be
    paid. The guard below refuses to create one.

    THE FUNCTION AND ITS TABLE STAY. Historical `pool_bet_pick` rows remain
    readable and no migration drops anything; a legacy-only league — one
    carrying no Rev1.3 marker at all — is unaffected, exactly as it is for
    `collect_weekly_entries` and `settle_pool`, whose guard this is.
    """
    assert_legacy_pool_path_allowed(db, league_id, week)

    if bet_type not in _VALID_BET_TYPES:
        raise ValueError(f"Invalid bet_type {bet_type!r}. Must be one of: {sorted(_VALID_BET_TYPES)}")

    league = _assert_league_exists(league_id, db)

    pot = db.query(PoolPot).filter(
        PoolPot.league_id == league_id, PoolPot.week == week,
    ).first()
    try:
        lock_dt = (pot.lock_time if pot and pot.lock_time else _nfl_lock_time(league.season, week))
    except ScheduleNotReadyError:
        raise ValueError(
            f"Week {week}'s schedule isn't ready yet — pool picks can't be submitted until it is"
        )
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
