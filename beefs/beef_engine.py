"""
Beef engine — GM-to-GM direct bet challenges.

A beef is a head-to-head weekly score comparison between ANY two teams,
regardless of their scheduled opponents.  Odds are derived by simulating
both teams' starters for the given week and comparing the score distributions.

Flow:
  1. GM1 calls issue_challenge()
       • No shared-matchup required — any two GMs can beef any week.
       • Runs Monte Carlo on both teams → preview odds only; real odds
         are recomputed at acceptance.
       • Writes BeefChallenge(status=pending, expires_at=now+24h).
  2. GM2 calls respond_to_challenge(accept=True/False)
       • Checks expiry and idempotency.
       • On accept: validates both wallets, places both Bet rows atomically
         (each referencing the team's own weekly matchup for tracking),
         debits both wallets, marks challenge accepted.
       • On decline: marks declined, no wallet changes.
  3. get_pending_challenges(team_id) returns sent + received pending challenges,
       auto-expiring any whose window has passed.

Settlement is handled by settlement_engine.settle_week(), which detects beef
bets via bet.beef_challenge_id and compares each team's actual weekly score
from their own game rather than a shared matchup.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json

from db.schema import (
    Bet, BeefChallenge, BeefStarter, Matchup, Player, Projection, Roster,
    Transaction, Wallet, Team,
)
from odds.odds_engine_headless import (
    PlayerProj,
    simulate_player_scores,
    simulate_scores,
    _prob_to_american,
)
# P3-D2 / MODEL-A — the legacy + Locked pricing path is explicitly pinned to the
# v1 model config, which is a verbatim capture of the constants this module was
# already pricing against (N_SIMS 10_000, STD_PCT 0.20, MIN_STD 0.5, HALF_PPR,
# the injury table). The engine no longer carries probability-affecting module
# constants, so the config must be passed; naming it here rather than resolving
# the ACTIVE version keeps this path pinned even if a later sim-v2 is minted.
#
# Locked does not need the registry indirection Dynamic depends on: Locked
# freezes its odds into the proposal at creation and never re-prices, so there
# is no second run that could drift. Dynamic is the mode that re-simulates at
# Final Lock, which is why it freezes a version id and resolves it later.
#
# N_SIMS, HALF_PPR and INJURY_MULTIPLIERS were imported here but never used —
# dropped rather than re-pointed.
from odds.model_registry import MODEL_V1 as LEGACY_MODEL_CONFIG

N_START           = 9
from config import CURRENT_SEASON as SEASON
from config import LOCK_SEASON
SOURCE            = "fantasypros"
from wallet.wallet_manager import MIN_BET
from betting.pool_engine import _nfl_lock_time
from betting.exceptions import ScheduleNotReadyError
from betting.per_bet_lock import is_bet_locked_for_gm
from feed.league_feed import (
    log_challenge_issued,
    log_challenge_accepted,
    log_challenge_countered,
    log_challenge_declined,
    log_challenge_expired,
)
from ledger.ledger import (
    post as ledger_post,
    _balance_of_in_session,
    _dollars_to_cents,
    lock_funding_scopes,
)

CHALLENGE_TTL_HOURS = 24


def _to_cents(amount: float) -> int:
    """Dollars → integer cents, for ledger.post() calls. Rounds first —
    never truncates raw float multiplication — per the L1 spec's integer-
    cents-only requirement."""
    return round(amount * 100)


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class ChallengeOut:
    challenge_id:         int
    direction:            str   # "sent" | "received" | "any"
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
    responded_at:         str | None
    challenger_bet_id:    int | None
    challenged_bet_id:    int | None
    countered_amount:     float | None = None
    schedule_not_ready:   bool = False


@dataclass
class AcceptResult:
    challenge_id:          int
    challenger_bet_id:     int
    challenged_bet_id:     int
    challenger_team:       str
    challenged_team:       str
    amount:                float
    description:           str
    staleness_warning:     bool
    final_challenger_odds: float
    final_challenged_odds: float


@dataclass
class OddsInputs:
    challenger_team_id: int
    challenged_team_id: int
    ch_starters:        list[PlayerProj] | None  # None for prop
    cd_starters:        list[PlayerProj] | None  # None for prop
    prop_projected:     float | None             # None for straight/spread/over_under
    prop_player_id:     int | None               # None for straight/spread/over_under
    points_snapshot:    dict[str, float]         # player_id str -> projected_points, for staleness
    shared_matchup_id:  int | None = None        # set when both teams are scheduled vs each other
    challenger_is_home: bool       = True        # only meaningful when shared_matchup_id is set


# ── Odds helpers ──────────────────────────────────────────────────────────────

def _ml_to_decimal(ml: int) -> float:
    if ml < 0:
        return round(1 + 100 / abs(ml), 4)
    return round(1 + ml / 100, 4)


def _fetch_starters_for_odds(
    bet_type:           str,
    challenger_team_id: int,
    challenged_team_id: int,
    player_id:          int | None,
    week:               int,
    db:                 Session,
) -> OddsInputs:
    """Query Roster + Projection and return a bundle for simulation and staleness checking.
    Does not run any Monte Carlo — that is _compute_odds_from_inputs()'s job.
    """
    points_snapshot: dict[str, float] = {}

    if bet_type == "prop":
        proj = db.query(Projection).filter_by(
            player_id=player_id, week=week, season=SEASON, source=SOURCE
        ).first()
        projected = proj.projected_points if proj else 0.0
        if player_id:
            points_snapshot[str(player_id)] = projected
        return OddsInputs(
            challenger_team_id = challenger_team_id,
            challenged_team_id = challenged_team_id,
            ch_starters        = None,
            cd_starters        = None,
            prop_projected     = projected,
            prop_player_id     = player_id,
            points_snapshot    = points_snapshot,
        )

    # straight | spread | over_under — all need the same starter lists
    ch_starters: list[PlayerProj] = []
    cd_starters: list[PlayerProj] = []
    for team_id, starters_list in (
        (challenger_team_id, ch_starters),
        (challenged_team_id, cd_starters),
    ):
        slots = (
            db.query(Roster)
            .filter(Roster.team_id == team_id)
            .order_by(Roster.id)
            .limit(N_START)
            .all()
        )
        for s in slots:
            p = db.query(Projection).filter_by(
                player_id=s.player_id, week=week, season=SEASON, source=SOURCE
            ).first()
            pts = p.projected_points if p else 0.0
            starters_list.append(PlayerProj(
                player_id        = s.player_id,
                name             = s.player.name,
                position         = s.player.position,
                projected_points = pts,
                injury_status    = p.injury_status if p else None,
            ))
            points_snapshot[str(s.player_id)] = pts

    shared     = _find_shared_matchup(challenger_team_id, challenged_team_id, week, db)
    shared_id  = shared.id if shared else None
    ch_is_home = (shared.home_team_id == challenger_team_id) if shared else True

    return OddsInputs(
        challenger_team_id = challenger_team_id,
        challenged_team_id = challenged_team_id,
        ch_starters        = ch_starters,
        cd_starters        = cd_starters,
        prop_projected     = None,
        prop_player_id     = None,
        points_snapshot    = points_snapshot,
        shared_matchup_id  = shared_id,
        challenger_is_home = ch_is_home,
    )


def _fetch_starters_for_odds_from_snapshot(
    bet_type:           str,
    challenger_team_id: int,
    challenged_team_id: int,
    player_id:          int | None,
    week:               int,
    db:                 Session,
    beef_challenge_id:  int,
) -> OddsInputs:
    """Same as _fetch_starters_for_odds, but reads the frozen BeefStarter
    snapshot instead of live Roster. Used by respond_to_challenge(), where
    the roster was already frozen into BeefStarter at issue time — unlike
    issue_challenge(), where nothing is frozen yet and live Roster is still
    correct.

    Projections are still fetched fresh: the roster is locked, but the
    projection is allowed to move — staleness_warning already exists to
    flag exactly that kind of shift.
    """
    if bet_type == "prop":
        # Prop bets never touch Roster or BeefStarter — nothing to freeze.
        return _fetch_starters_for_odds(
            bet_type, challenger_team_id, challenged_team_id, player_id, week, db
        )

    points_snapshot: dict[str, float] = {}

    # straight | spread | over_under — all need the same starter lists
    ch_starters: list[PlayerProj] = []
    cd_starters: list[PlayerProj] = []
    for team_id, starters_list in (
        (challenger_team_id, ch_starters),
        (challenged_team_id, cd_starters),
    ):
        slots = (
            db.query(BeefStarter)
            .filter(
                BeefStarter.beef_challenge_id == beef_challenge_id,
                BeefStarter.team_id           == team_id,
            )
            .all()
        )
        for s in slots:
            p = db.query(Projection).filter_by(
                player_id=s.player_id, week=week, season=SEASON, source=SOURCE
            ).first()
            pts = p.projected_points if p else 0.0
            starters_list.append(PlayerProj(
                player_id        = s.player_id,
                name             = s.player.name,
                position         = s.player.position,
                projected_points = pts,
                injury_status    = p.injury_status if p else None,
            ))
            points_snapshot[str(s.player_id)] = pts

    shared     = _find_shared_matchup(challenger_team_id, challenged_team_id, week, db)
    shared_id  = shared.id if shared else None
    ch_is_home = (shared.home_team_id == challenger_team_id) if shared else True

    return OddsInputs(
        challenger_team_id = challenger_team_id,
        challenged_team_id = challenged_team_id,
        ch_starters        = ch_starters,
        cd_starters        = cd_starters,
        prop_projected     = None,
        prop_player_id     = None,
        points_snapshot    = points_snapshot,
        shared_matchup_id  = shared_id,
        challenger_is_home = ch_is_home,
    )


def _compute_odds_from_inputs(
    bet_type: str,
    inputs:   OddsInputs,
    week:     int,
    line:     float | None = None,
    side:     str | None   = None,
) -> tuple[float, int, float, int, float, float]:
    """Pure Monte Carlo math — no database access.

    Returns (dec_ch, ml_ch, dec_cd, ml_cd, p_ch, p_cd).

    S8-P4C-2 ADDED THE TWO PROBABILITIES, and added nothing else. They were
    already computed here and then discarded at the return statement; a Dynamic
    proposal has to FREEZE them, because the Handshake derives the opponent's
    Derived ceiling from the proposal's frozen probabilities and refuses a
    proposal that carries none.

    THE ALTERNATIVE WOULD HAVE BEEN TO RECONSTRUCT THEM. Recovering p from the
    decimal odds is not an identity: the odds pass through
    `_prob_to_american`, which rounds to an integer moneyline, so inverting it
    yields a NEARBY probability rather than the one the simulation produced.
    Freezing a nearby probability would make the Handshake price a Dynamic wager
    off a number no model ever generated — pricing recreated in the adapter,
    which is exactly what the ruling forbids. Returning the real one is the
    thin adapter instead.
    """
    if bet_type in ("straight", "spread", "over_under"):
        if inputs.shared_matchup_id is not None:
            # Both teams are real scheduled opponents — orient starters to match the
            # canonical home/away order and use the same seed run() would produce.
            if inputs.challenger_is_home:
                sim_home_starters, sim_away_starters = inputs.ch_starters, inputs.cd_starters
                sim_home_id,       sim_away_id       = inputs.challenger_team_id, inputs.challenged_team_id
            else:
                sim_home_starters, sim_away_starters = inputs.cd_starters, inputs.ch_starters
                sim_home_id,       sim_away_id       = inputs.challenged_team_id, inputs.challenger_team_id
            raw_home, raw_away = simulate_scores(
                sim_home_id, sim_away_id,
                sim_home_starters, sim_away_starters,
                week, matchup_id=inputs.shared_matchup_id,
                model_config=LEGACY_MODEL_CONFIG,
            )
            # Map home/away back to challenger/challenged before computing p_ch
            ch_scores = raw_home if inputs.challenger_is_home else raw_away
            cd_scores = raw_away if inputs.challenger_is_home else raw_home
        else:
            ch_scores, cd_scores = simulate_scores(
                inputs.challenger_team_id, inputs.challenged_team_id,
                inputs.ch_starters, inputs.cd_starters, week,
                model_config=LEGACY_MODEL_CONFIG,
            )
        if bet_type == "straight":
            p_ch = float((ch_scores > cd_scores).mean())
        elif bet_type == "spread":
            p_ch = float(((ch_scores - cd_scores) > (line or 0.0)).mean())
        else:  # over_under
            combined = ch_scores + cd_scores
            if side == "over":
                p_ch = float((combined > (line or 0.0)).mean())
            else:
                p_ch = float((combined < (line or 0.0)).mean())

    elif bet_type == "prop":
        scores = simulate_player_scores(inputs.prop_projected, inputs.prop_player_id, week,
                                        model_config=LEGACY_MODEL_CONFIG)
        if side == "over":
            p_ch = float((scores > (line or 0.0)).mean())
        else:
            p_ch = float((scores < (line or 0.0)).mean())

    else:
        raise ValueError(f"Unknown bet_type: {bet_type!r}")

    p_cd  = 1.0 - p_ch
    ml_ch = _prob_to_american(p_ch)
    ml_cd = _prob_to_american(p_cd)
    return _ml_to_decimal(ml_ch), ml_ch, _ml_to_decimal(ml_cd), ml_cd, p_ch, p_cd


def _compute_odds(
    bet_type:           str,
    challenger_team:    Team,
    challenged_team:    Team,
    week:               int,
    db:                 Session,
    line:               float | None = None,
    side:               str | None   = None,
    player_id:          int | None   = None,
) -> tuple[float, int, float, int]:
    """Preview-odds wrapper used by issue_challenge(). Fetch then simulate."""
    inputs = _fetch_starters_for_odds(
        bet_type, challenger_team.id, challenged_team.id, player_id, week, db
    )
    return _compute_odds_from_inputs(bet_type, inputs, week, line, side)


# ── Description builder ───────────────────────────────────────────────────────

def _build_description(
    bet_type:        str,
    challenger_name: str,
    challenged_name: str,
    week:            int,
    line:            float | None,
    side:            str | None,
    player:          Player | None,
) -> str:
    if bet_type == "straight":
        return (
            f"{challenger_name} vs {challenged_name} — "
            f"who scores more in week {week}"
        )
    if bet_type == "spread":
        sign = f"+{line}" if (line or 0) >= 0 else str(line)
        return (
            f"{challenger_name} {sign} vs {challenged_name} — "
            f"weekly score spread (week {week})"
        )
    if bet_type == "over_under":
        return (
            f"{challenger_name} + {challenged_name} combined "
            f"{(side or 'over').upper()} {line} (week {week})"
        )
    if bet_type == "prop":
        pname = player.name if player else "player"
        return f"{pname} {(side or 'over').upper()} {line} pts (week {week})"
    return f"{bet_type} beef (week {week})"


# ── Serialiser ────────────────────────────────────────────────────────────────

def _to_out(c: BeefChallenge, direction: str = "any") -> ChallengeOut:
    return ChallengeOut(
        challenge_id         = c.id,
        direction            = direction,
        challenger_team_id   = c.challenger_team_id,
        challenger_name      = c.challenger_team.team_name,
        challenger_owner     = c.challenger_team.owner,
        challenged_team_id   = c.challenged_team_id,
        challenged_name      = c.challenged_team.team_name,
        challenged_owner     = c.challenged_team.owner,
        week                 = c.week,
        bet_type             = c.bet_type,
        amount               = c.amount,
        description          = c.description or "",
        challenger_moneyline = c.challenger_moneyline,
        challenged_moneyline = c.challenged_moneyline,
        status               = c.status,
        expires_at           = c.expires_at.isoformat(),
        created_at           = c.created_at.isoformat(),
        responded_at         = c.responded_at.isoformat() if c.responded_at else None,
        challenger_bet_id    = c.challenger_bet_id,
        challenged_bet_id    = c.challenged_bet_id,
        countered_amount     = c.countered_amount,
    )


def _snapshot_projections(
    bet_type:           str,
    challenger_team_id: int,
    challenged_team_id: int,
    player_id:          int | None,
    week:               int,
    db:                 Session,
) -> str:
    """Return JSON string mapping player_id → projected_points for all relevant players."""
    snapshot: dict[str, float] = {}

    if bet_type == "prop" and player_id:
        proj = db.query(Projection).filter_by(
            player_id=player_id, week=week, season=SEASON, source=SOURCE
        ).first()
        snapshot[str(player_id)] = proj.projected_points if proj else 0.0

    else:  # straight | spread | over_under — snapshot starters
        for team_id in (challenger_team_id, challenged_team_id):
            slots = (
                db.query(Roster)
                .filter(Roster.team_id == team_id)
                .order_by(Roster.id)
                .limit(N_START)
                .all()
            )
            for slot in slots:
                proj = db.query(Projection).filter_by(
                    player_id=slot.player_id, week=week, season=SEASON, source=SOURCE
                ).first()
                snapshot[str(slot.player_id)] = proj.projected_points if proj else 0.0

    return json.dumps(snapshot)


def _check_staleness(snapshot_json: str | None, live_snapshot: dict[str, float]) -> bool:
    """Return True if any snapshotted player's projection has shifted more than 10%.
    Pure comparison against live_snapshot — no database access.
    """
    if not snapshot_json:
        return False
    snapshot = json.loads(snapshot_json)
    for pid_str, old_pts in snapshot.items():
        new_pts = live_snapshot.get(pid_str, 0.0)
        if old_pts == 0.0:
            if new_pts > 0.0:
                return True   # player recovered / projection appeared
        else:
            if abs(new_pts - old_pts) / old_pts > 0.10:
                return True
    return False


# ── Internal bet placement ────────────────────────────────────────────────────

def _find_own_matchup(team_id: int, week: int, db: Session) -> Matchup:
    """Return the matchup a team is playing in for the given week."""
    m = (
        db.query(Matchup)
        .filter(
            Matchup.week == week,
            (Matchup.home_team_id == team_id) | (Matchup.away_team_id == team_id),
        )
        .first()
    )
    if not m:
        raise ValueError(f"Team {team_id} has no matchup in week {week}")
    return m


def _find_shared_matchup(team_a_id: int, team_b_id: int, week: int, db: Session) -> Matchup | None:
    """Return the Matchup row if team_a and team_b are scheduled against
    each other this week, else None. Beefs don't require this — most
    calls will return None."""
    return (
        db.query(Matchup)
        .filter(
            Matchup.week == week,
            (
                ((Matchup.home_team_id == team_a_id) & (Matchup.away_team_id == team_b_id))
                | ((Matchup.home_team_id == team_b_id) & (Matchup.away_team_id == team_a_id))
            ),
        )
        .first()
    )


def _capture_beef_starters(
    challenge_id:      int,
    challenger_team_id: int,
    challenged_team_id: int,
    db:                Session,
) -> None:
    """Snapshot both teams' first-9-by-id roster players into beef_starters.
    Called once after the BeefChallenge row has been committed and has an id.
    Fewer than 9 rows per team is fine — write whatever exists.
    Idempotent: a repeat call for the same challenge/team is a safe no-op —
    existing (beef_challenge_id, team_id, player_id) rows are skipped, not
    duplicated."""
    for team_id in (challenger_team_id, challenged_team_id):
        slots = (
            db.query(Roster)
            .filter(Roster.team_id == team_id)
            .order_by(Roster.id)
            .limit(N_START)
            .all()
        )
        existing_player_ids = {
            row.player_id
            for row in db.query(BeefStarter.player_id).filter(
                BeefStarter.beef_challenge_id == challenge_id,
                BeefStarter.team_id           == team_id,
            ).all()
        }
        for s in slots:
            if s.player_id in existing_player_ids:
                continue
            db.add(BeefStarter(
                beef_challenge_id = challenge_id,
                team_id           = team_id,
                player_id         = s.player_id,
                nfl_team          = s.player.nfl_team,
            ))
    db.commit()


def _place_beef_side(
    db:               Session,
    wallet:           Wallet,
    amount:           float,
    bet_type:         str,
    matchup_id:       int,       # the team's OWN matchup (for record-keeping)
    picked_team_id:   int | None,
    player_id:        int | None,
    line:             float | None,
    side:             str | None,
    description:      str,
    odds_dec:         float,
    beef_challenge_id: int,
) -> Bet:
    if amount < MIN_BET:
        raise ValueError(f"Bet amount ${amount:.2f} is below the minimum of ${MIN_BET:.2f}")
    # P1-L3B: this funding-capacity decision reads the AUTHORITATIVE integer-cent
    # ledger balance for wallet:{team_id}, in this same caller-owned session — never
    # the float Wallet.balance mirror, which is a display/compatibility column that
    # can legitimately disagree with the ledger. _to_cents() is deliberately the
    # SAME conversion the wager_placed posting below uses, so this gate and that
    # posting cannot disagree merely at a conversion boundary.
    #
    # This is a defensive re-check, not the only one: respond_to_challenge() already
    # runs _verify_wallet_available() (also ledger-cent) for both sides beforehand,
    # and ledger.post()'s funded-account guard remains the final transactional
    # defense below. Retiring this site belongs to the later Spec 2 legacy-path
    # retirement, not to P1-L3B — the legacy path is still reachable today.
    amount_cents  = _to_cents(amount)
    balance_cents = _balance_of_in_session(db, f"wallet:{wallet.team_id}")
    if balance_cents < amount_cents:
        raise ValueError(
            f"{wallet.team.team_name}'s wallet has insufficient funds: "
            f"${balance_cents / 100:.2f} < ${amount:.2f}"
        )

    bet = Bet(
        matchup_id        = matchup_id,
        wallet_id         = wallet.id,
        picked_team_id    = picked_team_id,
        player_id         = player_id,
        bet_type          = bet_type,
        line              = line,
        side              = side,
        description       = description,
        amount            = amount,
        odds              = odds_dec,
        status            = "pending",
        placed_at         = datetime.now(timezone.utc),
        beef_challenge_id = beef_challenge_id,
    )
    db.add(bet)
    db.flush()

    # Ledger posting — replaces the old direct wallet.balance mutation.
    # escrow:{bet.id} needs bet.id, hence this runs after the flush above.
    # Transition period (Finding 2 is a separate, later pass): the
    # Transaction row below stays alongside this for now — wallet.balance
    # is still what api/main.py's /faab/wallet/{team_id} route reads, so
    # both are written in parallel until that route is migrated too.
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
    return bet


def _verify_wallet_available(
    team_id:          int,
    effective_amount: float,
    db:               Session,
) -> Wallet:
    """
    Confirm team_id's bet wallet can cover effective_amount right now —
    balance minus pending bet exposure minus other pending/countered
    beef reservations. Raises ValueError with a breakdown if not.
    Returns the Wallet row on success.
    """
    # FR-7.12: funds check reads the LEDGER (source of truth), in this same
    # session/transaction, compared in integer cents. bet_exposure is dropped
    # entirely — pending bets' stakes have already left wallet:{team_id} in the
    # ledger via the wager_placed escrow debit, so the ledger balance already
    # reflects them; subtracting bet_exposure again would double-count.
    #
    # S8-P4C-1: ch_reserved is dropped for the SAME REASON, now that it is true
    # of challenges too. The soft reservation existed only because the legacy
    # issue stage posted nothing, so an open challenge's stake was invisible to
    # the ledger and had to be modelled alongside it. Under the funded lifecycle
    # the Anchor is posted to `escrow:challenge:{id}` at issue, so an open
    # challenge has ALREADY left this wallet — subtracting a reservation on top
    # would double-count exactly as bet_exposure did.
    #
    # The ledger balance is now the whole of available capacity. That is the
    # invariant `_challenge_reserved` was standing in for, and it is now enforced
    # by the money itself rather than by a parallel model of it.
    wallet          = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    available_cents = _balance_of_in_session(db, f"wallet:{team_id}")
    if available_cents < _to_cents(effective_amount):
        raise ValueError(
            f"Team {team_id}'s wallet has insufficient funds: "
            f"${effective_amount:.2f} needed, ${available_cents / 100:.2f} available "
            f"(${available_cents / 100:.2f} wallet balance, open challenge stakes "
            f"already escrowed)"
        )
    return wallet


# ── Public API ────────────────────────────────────────────────────────────────

def issue_challenge(
    challenger_team_id: int,
    challenged_team_id: int,
    week:               int,
    bet_type:           str,
    amount:             float,
    db:                 Session,
    line:            float | None = None,
    side:            str | None   = None,
    player_id:       int | None   = None,
    trash_talk:      str | None   = None,
) -> ChallengeOut:
    """
    GM1 issues a challenge to GM2 for any given week.
    The two teams do NOT need to be scheduled against each other.
    Odds computed here are a preview only — the live odds are recomputed
    at acceptance time and locked into the placed Bet rows.
    """
    if challenger_team_id == challenged_team_id:
        raise ValueError("A team cannot challenge itself")
    if not 1 <= week <= 17:
        raise ValueError("week must be 1–17")
    try:
        lock_dt = _nfl_lock_time(LOCK_SEASON, week)
    except ScheduleNotReadyError:
        raise ValueError(
            f"Week {week}'s schedule isn't ready yet — no new challenges can be issued for this week"
        )
    if datetime.now(timezone.utc) >= lock_dt:
        raise ValueError(
            f"Week {week} locked at kickoff — challenges can no longer be issued for this week"
        )

    challenger_team = db.query(Team).filter(Team.id == challenger_team_id).first()
    challenged_team = db.query(Team).filter(Team.id == challenged_team_id).first()
    if not challenger_team:
        raise ValueError(f"Team {challenger_team_id} not found")
    if not challenged_team:
        raise ValueError(f"Team {challenged_team_id} not found")

    # FR-5.12: both teams must actually be playing this week. Without a Matchup
    # row a team scores nothing, so the beef could never settle. Fail here at
    # issue time rather than deep inside _place_beef_side() during accept.
    for role, team_id in (("Challenger", challenger_team_id), ("Challenged", challenged_team_id)):
        try:
            _find_own_matchup(team_id, week, db)
        except ValueError:
            raise ValueError(
                f"{role} team {team_id} has no matchup in week {week} — "
                f"no challenge can be issued for a team that isn't playing this week"
            )

    if bet_type not in ("straight", "spread", "over_under"):
        raise ValueError(f"Unknown bet_type {bet_type!r}")
    if bet_type == "spread" and line is None:
        raise ValueError("spread bets require line")
    if bet_type == "over_under" and (line is None or side not in ("over", "under")):
        raise ValueError("over_under bets require line and side ('over'/'under')")
    # FR-7.50: reject a sub-cent stake before the MIN_BET check — malformed
    # input reports before a well-formed below-minimum request does. Return
    # value discarded (validation only); the ValueError is left to propagate.
    _dollars_to_cents(amount)
    if amount < MIN_BET:
        raise ValueError(f"Amount ${amount:.2f} is below the minimum ${MIN_BET:.2f}")

    # P1-L7: take the challenger's Wallet-row mutex before the capacity read
    # below, held to this function's db.commit(). The mutex outlived the reason
    # first given for it: S8-P4C-1 retired the soft reservation this comment used
    # to cite, but the read it gates is still balance-sensitive, so the mutex is
    # not merely retained — it is now the ONLY thing serialising it. Two
    # concurrent issues by one team would otherwise both see the same
    # not-yet-committed balance, both pass, and commit the team beyond it. This
    # is the "two racing issues by one team cannot both pass the funds check"
    # obligation in Foundation Correction Plan §4.
    #
    # Ordered ahead of the wallet lookup so the mutex is the first statement of
    # the money-sensitive section. The lookup below is retained: it feeds
    # challenger_wallet to the rest of the function, and its ValueError is the
    # pre-existing message for a missing row (lock_funding_scopes raises its own
    # WalletMutexMissingError, a ValueError subclass, first — same exception
    # family, so callers and routes are unaffected).
    lock_funding_scopes(db, challenger_team_id)
    challenger_wallet = db.query(Wallet).filter(Wallet.team_id == challenger_team_id).first()
    if not challenger_wallet:
        raise ValueError(f"No wallet found for team {challenger_team_id}")
    # FR-7.12 / S8-P4C-1: ledger-sourced, in-session, integer-cents funds check.
    # Both correction terms are now dropped — bet_exposure because placed stakes
    # already left the wallet via wager_placed, challenge_reserved because open
    # challenge stakes now do too, via the issue-stage Anchor escrow. The ledger
    # balance is the whole of available capacity.
    available_cents = _balance_of_in_session(db, f"wallet:{challenger_team_id}")
    if available_cents < _to_cents(amount):
        raise ValueError(
            f"Challenger wallet has insufficient available funds: "
            f"${available_cents / 100:.2f} available — open challenge stakes are "
            f"already escrowed and excluded from this balance"
        )

    player = db.query(Player).filter(Player.id == player_id).first() if player_id else None

    dec_ch, ml_ch, dec_cd, ml_cd, _p_ch, _p_cd = _compute_odds(
        bet_type, challenger_team, challenged_team, week, db, line, side, player_id
    )

    desc     = _build_description(
        bet_type, challenger_team.team_name, challenged_team.team_name,
        week, line, side, player,
    )
    snapshot = _snapshot_projections(
        bet_type, challenger_team_id, challenged_team_id, player_id, week, db
    )
    now = datetime.now(timezone.utc)

    challenge = BeefChallenge(
        challenger_team_id   = challenger_team_id,
        challenged_team_id   = challenged_team_id,
        week                 = week,
        bet_type             = bet_type,
        amount               = amount,
        line                 = line,
        side                 = side,
        player_id            = player_id,
        description          = desc,
        challenger_odds      = dec_ch,
        challenged_odds      = dec_cd,
        challenger_moneyline = ml_ch,
        challenged_moneyline = ml_cd,
        status               = "pending",
        expires_at           = now + timedelta(hours=CHALLENGE_TTL_HOURS),
        created_at           = now,
        projection_snapshot  = snapshot,
        staleness_warning    = 0,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    _capture_beef_starters(challenge.id, challenger_team_id, challenged_team_id, db)
    log_challenge_issued(challenge, db, trash_talk=trash_talk)
    return _to_out(challenge, direction="sent")


def respond_to_challenge(
    challenge_id: int,
    accept:       bool,
    db:           Session,
    trash_talk:   str | None = None,
) -> ChallengeOut | AcceptResult:
    """
    Accept or decline a challenge (pending) or a counter-offer (countered).

    Pending    → only the challenged team may respond (enforced in the API route).
    Countered  → only the original challenger may respond (enforced in the API route).
    """
    now       = datetime.now(timezone.utc)
    challenge = db.query(BeefChallenge).filter(BeefChallenge.id == challenge_id).first()
    if not challenge:
        raise ValueError(f"Challenge {challenge_id} not found")
    if challenge.status not in ("pending", "countered"):
        raise ValueError(f"Challenge is already {challenge.status}")
    if challenge.expires_at.replace(tzinfo=timezone.utc) < now:
        challenge.status = "expired"
        db.commit()
        raise ValueError("Challenge has expired")
    try:
        lock_dt = _nfl_lock_time(LOCK_SEASON, challenge.week)
    except ScheduleNotReadyError:
        raise ValueError(
            f"Week {challenge.week}'s schedule isn't ready yet — "
            f"this challenge can't be accepted or declined until it is"
        )
    except ValueError:
        lock_dt = None  # season not yet configured — skip kickoff check
    if lock_dt is not None and now >= lock_dt:
        challenge.status = "expired"
        db.commit()
        raise ValueError(
            f"Week {challenge.week} locked at kickoff — "
            f"this challenge can no longer be accepted or declined"
        )

    challenge.responded_at = now

    if not accept:
        challenge.status = "declined"
        db.commit()
        db.refresh(challenge)
        log_challenge_declined(challenge, db, trash_talk=trash_talk)
        return _to_out(challenge, direction="received")

    # ── Per-bet kickoff lock (versus bets only) ──────────────────────────────
    # Split beef_starters by frozen team_id — never re-queries live Roster.
    # Runs before wallet verification, staleness check, and odds recompute —
    # a locked challenge is rejected before any of that work runs, and before
    # anything on the challenge object is mutated.
    all_starters_raw = (
        db.query(BeefStarter)
        .filter(BeefStarter.beef_challenge_id == challenge.id)
        .all()
    )
    # Dedup on (team_id, player_id) at read time — independent of the DB
    # constraint; guards against any duplicate rows written before the
    # constraint existed.
    all_starters = list({(s.team_id, s.player_id): s for s in all_starters_raw}.values())
    # Every frozen starter is included, even with a missing nfl_team — an
    # empty string reaches is_bet_locked_for_gm's own fail-safe, which treats
    # an unrecognized/unmapped team code as locked (protect the money) rather
    # than silently dropping the player before the lock ever sees them.
    ch_nfl_teams = [s.nfl_team or "" for s in all_starters
                    if s.team_id == challenge.challenger_team_id]
    cd_nfl_teams = [s.nfl_team or "" for s in all_starters
                    if s.team_id == challenge.challenged_team_id]
    raw_conn = db.connection()
    ch_result = is_bet_locked_for_gm(raw_conn, ch_nfl_teams, challenge.week)
    cd_result = is_bet_locked_for_gm(raw_conn, cd_nfl_teams, challenge.week)
    if ch_result.locked or cd_result.locked:
        locked_result = ch_result if ch_result.locked else cd_result
        locked_side = challenge.challenger_team.team_name if ch_result.locked else challenge.challenged_team.team_name

        if locked_result.reason == "in_progress":
            raise ValueError(
                f"{locked_side}'s staked players are in a game that has already kicked off "
                f"for week {challenge.week} — this challenge can no longer be accepted"
            )
        elif locked_result.reason == "schedule_not_ready":
            raise ValueError(
                f"This challenge can't be accepted yet — the NFL hasn't posted an official "
                f"kickoff time for one of {locked_side}'s players in week {challenge.week}. "
                f"Try again once the schedule is confirmed."
            )
        else:  # "data_gap"
            raise ValueError(
                f"This challenge can't be accepted right now — we're missing schedule data "
                f"for one of {locked_side}'s players in week {challenge.week}. "
                f"Contact the commissioner to check."
            )

    # P1-L4 — THE REPEATABLE READ THAT USED TO SIT HERE IS REMOVED.
    #
    # It set `isolation_level: REPEATABLE READ` on a connection whose transaction
    # had already autobegun several statements earlier, which Spec 2 §2 and
    # Foundation Correction Plan §4 both record as "too late to be relied on".
    # P1-L7 then made the explicit Wallet mutex below the actual control, leaving
    # this line redundant — and worse than redundant: a REPEATABLE READ snapshot
    # would make the under-lock balance read below serve data from BEFORE the lock
    # was granted, which is the exact failure the lock exists to prevent, and on
    # Postgres it converts a clean lock-and-queue into a serialization failure the
    # caller must retry.
    #
    # Removing it is the smallest change that leaves one control in charge. The
    # authoritative read below now runs at the connection's ordinary isolation,
    # under the mutex, and sees the committed state of whoever went first.
    #
    # P1-L7: the two-Wallet mutex for this accept, held from here to the single
    # db.commit() at the end of the accept. THE LOCK IS THE CONTROL.
    #
    # Deliberately placed HERE and not at the top of the function: the expiry,
    # kickoff-lock and decline branches above each commit and return, and a lock
    # taken before them would be released by their commits — a mutex that ends
    # before the balance read it protects is not a mutex. Everything from this
    # line to the commit runs with no intervening commit or rollback.
    #
    # Both wallets, one call: the primitive sorts ascending team_id, so an accept
    # of A-challenges-B and a concurrent accept of B-challenges-A acquire in the
    # same order and queue instead of deadlocking. The challenger/challenged role
    # never reaches the ordering.
    lock_funding_scopes(db, challenge.challenger_team_id, challenge.challenged_team_id)

    # ── Accept: determine effective stake ────────────────────────────────────
    is_counter       = challenge.countered_amount is not None
    effective_amount = challenge.countered_amount if is_counter else challenge.amount

    week  = challenge.week
    # Single DB fetch — points_snapshot feeds the staleness check; full bundle
    # feeds the odds recompute below (no second fetch).
    live_inputs = _fetch_starters_for_odds_from_snapshot(
        challenge.bet_type, challenge.challenger_team_id, challenge.challenged_team_id,
        challenge.player_id, week, db, beef_challenge_id=challenge.id,
    )
    stale = _check_staleness(challenge.projection_snapshot, live_inputs.points_snapshot)
    challenge.staleness_warning = 1 if stale else 0

    ch_matchup = _find_own_matchup(challenge.challenger_team_id, week, db)
    cd_matchup = _find_own_matchup(challenge.challenged_team_id, week, db)
    ch_pick, ch_line, ch_side = _challenger_side_params(challenge)
    cd_pick, cd_line, cd_side = _challenged_side_params(challenge)

    if is_counter:
        # Countered accept: re-verify both wallets can cover countered_amount right now.
        # Challenger excludes the current challenge from its reservation (it's about to settle).
        challenger_wallet = _verify_wallet_available(
            challenge.challenger_team_id, effective_amount, db,
        )
        challenged_wallet = _verify_wallet_available(
            challenge.challenged_team_id, effective_amount, db,
        )
    else:
        # Plain accept: same wallet check — catches funds drained since the challenge was issued.
        # Challenger excludes the current challenge from its reservation (it's about to settle).
        challenger_wallet = _verify_wallet_available(
            challenge.challenger_team_id, effective_amount, db,
        )
        challenged_wallet = _verify_wallet_available(
            challenge.challenged_team_id, effective_amount, db,
        )

    # Recompute odds from live data on the shared path — overwrites the preview odds
    # stored at issue time so both Bet rows receive the final locked line.
    dec_ch, ml_ch, dec_cd, ml_cd, _p_ch, _p_cd = _compute_odds_from_inputs(
        challenge.bet_type, live_inputs, week, challenge.line, challenge.side
    )
    challenge.challenger_odds      = dec_ch
    challenge.challenged_odds      = dec_cd
    challenge.challenger_moneyline = ml_ch
    challenge.challenged_moneyline = ml_cd

    challenger_bet = _place_beef_side(
        db, challenger_wallet, effective_amount,
        challenge.bet_type, ch_matchup.id,
        ch_pick, challenge.player_id, ch_line, ch_side,
        challenge.description, challenge.challenger_odds,
        beef_challenge_id=challenge.id,
    )
    challenged_bet = _place_beef_side(
        db, challenged_wallet, effective_amount,
        challenge.bet_type, cd_matchup.id,
        cd_pick, challenge.player_id, cd_line, cd_side,
        _mirror_description(challenge.description), challenge.challenged_odds,
        beef_challenge_id=challenge.id,
    )

    challenge.status            = "accepted"
    challenge.challenger_bet_id = challenger_bet.id
    challenge.challenged_bet_id = challenged_bet.id
    db.commit()
    log_challenge_accepted(challenge, db, trash_talk=trash_talk)

    return AcceptResult(
        challenge_id          = challenge.id,
        challenger_bet_id     = challenger_bet.id,
        challenged_bet_id     = challenged_bet.id,
        challenger_team       = challenge.challenger_team.team_name,
        challenged_team       = challenge.challenged_team.team_name,
        amount                = effective_amount,
        description           = challenge.description,
        staleness_warning     = stale,
        final_challenger_odds = dec_ch,
        final_challenged_odds = dec_cd,
    )


def counter_challenge(
    challenge_id:     int,
    countered_amount: float,
    db:               Session,
    trash_talk:       str | None = None,
) -> ChallengeOut:
    """
    The challenged party proposes a different stake amount.
    Only valid when status == 'pending' (one counter max — already-countered is rejected).
    Bet type, week, and odds remain locked; only the stake changes.
    """
    now       = datetime.now(timezone.utc)
    challenge = db.query(BeefChallenge).filter(BeefChallenge.id == challenge_id).first()
    if not challenge:
        raise ValueError(f"Challenge {challenge_id} not found")
    if challenge.status != "pending":
        raise ValueError(
            f"Cannot counter: challenge is {challenge.status!r} — "
            f"only a pending challenge can be countered (one counter max)"
        )
    # FR-7.50: reject a sub-cent counter before the MIN_BET check (same
    # ordering and error posture as issue_challenge()).
    _dollars_to_cents(countered_amount)
    if countered_amount < MIN_BET:
        raise ValueError(
            f"Counter-offer amount ${countered_amount:.2f} is below the minimum ${MIN_BET:.2f}"
        )

    # Kickoff lock — same rule as issue_challenge
    try:
        lock_dt = _nfl_lock_time(LOCK_SEASON, challenge.week)
    except ScheduleNotReadyError:
        raise ValueError(
            f"Week {challenge.week}'s schedule isn't ready yet — this challenge can't be countered"
        )
    except ValueError:
        lock_dt = None
    if lock_dt is not None and now >= lock_dt:
        raise ValueError(
            f"Week {challenge.week} locked at kickoff — "
            f"this challenge can no longer be countered"
        )

    # P1-L7: the countering team's Wallet-row mutex, held to db.commit() below.
    # A counter posts no money and, since S8-P4C-1, reserves none either — but it
    # still DECIDES from a balance read, and that is what the mutex protects. Two
    # concurrent counters by one team, or a counter racing that team's own issue,
    # would otherwise both read the same balance and both pass. Single scope: the countering team is the only one committing capacity
    # here; the challenger's exposure is unchanged by a counter.
    lock_funding_scopes(db, challenge.challenged_team_id)
    # Check CHALLENGED team's available balance for countered_amount.
    # They're the ones proposing this stake — verify they can actually cover it.
    cd_wallet = db.query(Wallet).filter(Wallet.team_id == challenge.challenged_team_id).first()
    if not cd_wallet:
        raise ValueError(f"No wallet found for team {challenge.challenged_team_id}")
    # FR-7.12 / S8-P4C-1: ledger-sourced, in-session, integer-cents funds check,
    # with no reservation term — see _verify_wallet_available().
    cd_available_cents = _balance_of_in_session(db, f"wallet:{challenge.challenged_team_id}")
    if cd_available_cents < _to_cents(countered_amount):
        raise ValueError(
            f"Challenged wallet has insufficient funds to propose a ${countered_amount:.2f} counter: "
            f"${cd_available_cents / 100:.2f} available — open challenge stakes are "
            f"already escrowed and excluded from this balance"
        )

    challenge.countered_amount = countered_amount
    challenge.countered_at     = now
    challenge.status           = "countered"
    challenge.expires_at       = now + timedelta(hours=CHALLENGE_TTL_HOURS)

    db.commit()
    db.refresh(challenge)
    log_challenge_countered(challenge, db, trash_talk=trash_talk)
    return _to_out(challenge, direction="received")


def get_pending_challenges(team_id: int, db: Session) -> list[ChallengeOut]:
    """Return sent + received pending/countered challenges; auto-expire stale ones."""
    now = datetime.now(timezone.utc)
    candidates = (
        db.query(BeefChallenge)
        .filter(
            BeefChallenge.status.in_(["pending", "countered"]),
            (BeefChallenge.challenger_team_id == team_id) |
            (BeefChallenge.challenged_team_id == team_id),
        )
        .order_by(BeefChallenge.created_at.desc())
        .all()
    )
    results: list[ChallengeOut] = []
    for c in candidates:
        ttl_expired = c.expires_at.replace(tzinfo=timezone.utc) < now
        schedule_not_ready = False
        try:
            lock_expired = now >= _nfl_lock_time(LOCK_SEASON, c.week)
        except ScheduleNotReadyError:
            lock_expired = False
            schedule_not_ready = True
        except ValueError:
            lock_expired = False
            schedule_not_ready = True  # unconfigured season is the same uncertainty — flag it too
        if ttl_expired or lock_expired:
            c.status = "expired"
            log_challenge_expired(c, db)
            continue
        direction = "sent" if c.challenger_team_id == team_id else "received"
        out = _to_out(c, direction)
        out.schedule_not_ready = schedule_not_ready
        results.append(out)
    db.commit()
    return results


# ── Side parameter helpers ────────────────────────────────────────────────────

def _challenger_side_params(
    c: BeefChallenge,
) -> tuple[int | None, float | None, str | None]:
    """(picked_team_id, line, side) for the challenger's Bet row."""
    if c.bet_type == "straight":
        return c.challenger_team_id, None, None
    if c.bet_type == "spread":
        return c.challenger_team_id, c.line, None
    # over_under / prop
    return None, c.line, c.side


def _challenged_side_params(
    c: BeefChallenge,
) -> tuple[int | None, float | None, str | None]:
    """(picked_team_id, line, side) for the challenged party's Bet row."""
    if c.bet_type == "straight":
        return c.challenged_team_id, None, None
    if c.bet_type == "spread":
        # Challenged wins if challenger fails to cover, so their effective line is negated
        return c.challenged_team_id, -(c.line or 0.0), None
    # over_under / prop — opposite side
    return None, c.line, ("under" if c.side == "over" else "over")


def _mirror_description(desc: str) -> str:
    if " OVER " in desc:
        return desc.replace(" OVER ", " UNDER ")
    if " UNDER " in desc:
        return desc.replace(" UNDER ", " OVER ")
    return desc + " (other side)"


# ── CLI smoke test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    from db.schema import SessionLocal

    WEEK = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    T1   = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    T2   = int(sys.argv[3]) if len(sys.argv) > 3 else 7

    with SessionLocal() as db:
        t1 = db.query(Team).filter(Team.id == T1).first()
        t2 = db.query(Team).filter(Team.id == T2).first()

        print(f"\nStraight challenge — week {WEEK}: {t1.team_name} vs {t2.team_name}")
        print("─" * 60)

        c = issue_challenge(T1, T2, WEEK, "straight", 50.0, db=db)
        print(f"  Challenge #{c.challenge_id} issued  status={c.status}")
        print(f"  {c.description}")
        print(f"  {c.challenger_name}: {c.challenger_moneyline:+,}   "
              f"{c.challenged_name}: {c.challenged_moneyline:+,}")

        result = respond_to_challenge(c.challenge_id, accept=True, db=db)
        print(f"\nAccepted: challenger_bet=#{result.challenger_bet_id}  "
              f"challenged_bet=#{result.challenged_bet_id}  "
              f"staleness={result.staleness_warning}")

        print()
        for tid, name in [(T1, t1.team_name), (T2, t2.team_name)]:
            w = db.query(Wallet).filter(Wallet.team_id == tid).first()
            print(f"  {name:<28} wallet: ${w.balance:,.2f}")
