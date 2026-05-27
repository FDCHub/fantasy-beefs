"""
Beef engine — GM-to-GM direct bet challenges.

A beef is a head-to-head weekly score comparison between ANY two teams,
regardless of their scheduled opponents.  Odds are derived by simulating
both teams' starters for the given week and comparing the score distributions.

Flow:
  1. GM1 calls issue_challenge()
       • No shared-matchup required — any two GMs can beef any week.
       • Runs Monte Carlo on both teams → locks fair odds for both sides.
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
    Bet, BeefChallenge, Matchup, Player, Projection, Roster,
    Transaction, Wallet, Team,
)
from odds.monte_carlo import (
    N_START, SEASON, SOURCE,
    INJURY_MULTIPLIERS, MIN_HEALTHY_BENCH,
    bench_players, simulate_scores, simulate_bench_scores, simulate_player_scores,
    _prob_to_american,
)
from wallet.wallet_manager import MIN_BET
from feed.league_feed import (
    log_challenge_issued,
    log_challenge_accepted,
    log_challenge_declined,
    log_challenge_expired,
)

CHALLENGE_TTL_HOURS = 24


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


@dataclass
class AcceptResult:
    challenge_id:      int
    challenger_bet_id: int
    challenged_bet_id: int
    challenger_team:   str
    challenged_team:   str
    amount:            float
    description:       str
    staleness_warning: bool


# ── Odds helpers ──────────────────────────────────────────────────────────────

def _ml_to_decimal(ml: int) -> float:
    if ml < 0:
        return round(1 + 100 / abs(ml), 4)
    return round(1 + ml / 100, 4)


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
    """
    Simulate both teams and return (ch_dec, ch_ml, cd_dec, cd_ml).
    challenger_scores corresponds to challenger_team, regardless of matchup.
    """
    if bet_type == "bench_battle":
        ch_scores, cd_scores = simulate_bench_scores(challenger_team, challenged_team, week, db)
        p_ch = float((ch_scores > cd_scores).mean())

    elif bet_type in ("straight", "spread"):
        ch_scores, cd_scores = simulate_scores(challenger_team, challenged_team, week, db)
        if bet_type == "straight":
            p_ch = float((ch_scores > cd_scores).mean())
        else:
            p_ch = float(((ch_scores - cd_scores) > (line or 0.0)).mean())

    elif bet_type == "over_under":
        ch_scores, cd_scores = simulate_scores(challenger_team, challenged_team, week, db)
        combined = ch_scores + cd_scores
        if side == "over":
            p_ch = float((combined > (line or 0.0)).mean())
        else:
            p_ch = float((combined < (line or 0.0)).mean())

    elif bet_type == "prop":
        proj = (
            db.query(Projection)
            .filter_by(player_id=player_id, week=week, season=SEASON, source=SOURCE)
            .first()
        )
        projected = proj.projected_points if proj else 0.0
        scores    = simulate_player_scores(projected, player_id, week)
        if side == "over":
            p_ch = float((scores > (line or 0.0)).mean())
        else:
            p_ch = float((scores < (line or 0.0)).mean())

    else:
        raise ValueError(f"Unknown bet_type: {bet_type!r}")

    p_cd   = 1.0 - p_ch
    ml_ch  = _prob_to_american(p_ch)
    ml_cd  = _prob_to_american(p_cd)
    return _ml_to_decimal(ml_ch), ml_ch, _ml_to_decimal(ml_cd), ml_cd


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
    if bet_type == "bench_battle":
        return (
            f"{challenger_name} vs {challenged_name} — "
            f"bench battle (week {week})"
        )
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
    )


# ── Bench battle helpers ──────────────────────────────────────────────────────

def _validate_bench_battle(
    challenger_team: Team,
    challenged_team: Team,
    week: int,
    db: Session,
) -> None:
    """Raise ValueError if either team has fewer than MIN_HEALTHY_BENCH non-Out/IR bench players."""
    for team in (challenger_team, challenged_team):
        bench = bench_players(team, week, db)
        healthy = sum(
            1 for b in bench
            if b.injury_status not in ("out", "ir")
        )
        if healthy < MIN_HEALTHY_BENCH:
            raise ValueError(
                f"{team.team_name} has only {healthy} healthy bench player(s) "
                f"(minimum {MIN_HEALTHY_BENCH} required for bench_battle — "
                f"{len(bench) - healthy} player(s) are Out/IR)"
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

    elif bet_type == "bench_battle":
        for team_id in (challenger_team_id, challenged_team_id):
            team = db.query(Team).filter(Team.id == team_id).first()
            for b in bench_players(team, week, db):
                snapshot[str(b.player_id)] = b.raw_points

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


def _check_staleness(snapshot_json: str | None, week: int, db: Session) -> bool:
    """Return True if any snapshotted player's projection has shifted more than 10%."""
    if not snapshot_json:
        return False
    snapshot = json.loads(snapshot_json)
    for pid_str, old_pts in snapshot.items():
        proj = db.query(Projection).filter_by(
            player_id=int(pid_str), week=week, season=SEASON, source=SOURCE
        ).first()
        new_pts = proj.projected_points if proj else 0.0
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
    if wallet.balance < amount:
        raise ValueError(
            f"{wallet.team.team_name}'s wallet has insufficient funds: "
            f"${wallet.balance:.2f} < ${amount:.2f}"
        )
    wallet.balance = round(wallet.balance - amount, 2)

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

    db.add(Transaction(
        wallet_id  = wallet.id,
        amount     = -amount,
        type       = "bet",
        bet_id     = bet.id,
        created_at = datetime.now(timezone.utc),
    ))
    return bet


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
    """
    if challenger_team_id == challenged_team_id:
        raise ValueError("A team cannot challenge itself")
    if not 1 <= week <= 17:
        raise ValueError("week must be 1–17")

    challenger_team = db.query(Team).filter(Team.id == challenger_team_id).first()
    challenged_team = db.query(Team).filter(Team.id == challenged_team_id).first()
    if not challenger_team:
        raise ValueError(f"Team {challenger_team_id} not found")
    if not challenged_team:
        raise ValueError(f"Team {challenged_team_id} not found")

    if bet_type not in ("straight", "spread", "over_under", "prop", "bench_battle"):
        raise ValueError(f"Unknown bet_type {bet_type!r}")
    if bet_type == "spread" and line is None:
        raise ValueError("spread bets require line")
    if bet_type == "over_under" and (line is None or side not in ("over", "under")):
        raise ValueError("over_under bets require line and side ('over'/'under')")
    if bet_type == "prop" and (player_id is None or line is None or side not in ("over", "under")):
        raise ValueError("prop bets require player_id, line, and side")
    if amount < MIN_BET:
        raise ValueError(f"Amount ${amount:.2f} is below the minimum ${MIN_BET:.2f}")

    challenger_wallet = db.query(Wallet).filter(Wallet.team_id == challenger_team_id).first()
    if not challenger_wallet or challenger_wallet.balance < amount:
        bal = challenger_wallet.balance if challenger_wallet else 0.0
        raise ValueError(f"Challenger wallet has insufficient funds: ${bal:.2f} < ${amount:.2f}")

    if bet_type == "bench_battle":
        _validate_bench_battle(challenger_team, challenged_team, week, db)

    player = db.query(Player).filter(Player.id == player_id).first() if player_id else None

    dec_ch, ml_ch, dec_cd, ml_cd = _compute_odds(
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
    log_challenge_issued(challenge, db, trash_talk=trash_talk)
    return _to_out(challenge, direction="sent")


def respond_to_challenge(
    challenge_id: int,
    accept:       bool,
    db:           Session,
    trash_talk:   str | None = None,
) -> ChallengeOut | AcceptResult:
    """GM2 accepts or declines. Returns AcceptResult if accepted, ChallengeOut if declined."""
    now       = datetime.now(timezone.utc)
    challenge = db.query(BeefChallenge).filter(BeefChallenge.id == challenge_id).first()
    if not challenge:
        raise ValueError(f"Challenge {challenge_id} not found")
    if challenge.status != "pending":
        raise ValueError(f"Challenge is already {challenge.status}")
    if challenge.expires_at.replace(tzinfo=timezone.utc) < now:
        challenge.status = "expired"
        db.commit()
        raise ValueError("Challenge has expired")

    challenge.responded_at = now

    if not accept:
        challenge.status = "declined"
        db.commit()
        db.refresh(challenge)
        log_challenge_declined(challenge, db, trash_talk=trash_talk)
        return _to_out(challenge, direction="received")

    # ── Accept: check staleness, place both bets atomically ─────────────────
    week = challenge.week

    stale = _check_staleness(challenge.projection_snapshot, week, db)
    challenge.staleness_warning = 1 if stale else 0

    challenger_wallet = db.query(Wallet).filter(
        Wallet.team_id == challenge.challenger_team_id
    ).first()
    challenged_wallet = db.query(Wallet).filter(
        Wallet.team_id == challenge.challenged_team_id
    ).first()

    ch_matchup = _find_own_matchup(challenge.challenger_team_id, week, db)
    cd_matchup = _find_own_matchup(challenge.challenged_team_id, week, db)

    # Challenger bets FOR themselves; challenged bets FOR themselves
    ch_pick, ch_line, ch_side = _challenger_side_params(challenge)
    cd_pick, cd_line, cd_side = _challenged_side_params(challenge)

    challenger_bet = _place_beef_side(
        db, challenger_wallet, challenge.amount,
        challenge.bet_type, ch_matchup.id,
        ch_pick, challenge.player_id, ch_line, ch_side,
        challenge.description, challenge.challenger_odds,
        beef_challenge_id=challenge.id,
    )
    challenged_bet = _place_beef_side(
        db, challenged_wallet, challenge.amount,
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
        challenge_id      = challenge.id,
        challenger_bet_id = challenger_bet.id,
        challenged_bet_id = challenged_bet.id,
        challenger_team   = challenge.challenger_team.team_name,
        challenged_team   = challenge.challenged_team.team_name,
        amount            = challenge.amount,
        description       = challenge.description,
        staleness_warning = stale,
    )


def get_pending_challenges(team_id: int, db: Session) -> list[ChallengeOut]:
    """Return sent + received pending challenges; auto-expire stale ones."""
    now = datetime.now(timezone.utc)
    candidates = (
        db.query(BeefChallenge)
        .filter(
            BeefChallenge.status == "pending",
            (BeefChallenge.challenger_team_id == team_id) |
            (BeefChallenge.challenged_team_id == team_id),
        )
        .order_by(BeefChallenge.created_at.desc())
        .all()
    )
    results: list[ChallengeOut] = []
    for c in candidates:
        if c.expires_at.replace(tzinfo=timezone.utc) < now:
            c.status = "expired"
            log_challenge_expired(c, db)
            continue
        direction = "sent" if c.challenger_team_id == team_id else "received"
        results.append(_to_out(c, direction))
    db.commit()
    return results


# ── Side parameter helpers ────────────────────────────────────────────────────

def _challenger_side_params(
    c: BeefChallenge,
) -> tuple[int | None, float | None, str | None]:
    """(picked_team_id, line, side) for the challenger's Bet row."""
    if c.bet_type in ("straight", "bench_battle"):
        return c.challenger_team_id, None, None
    if c.bet_type == "spread":
        return c.challenger_team_id, c.line, None
    # over_under / prop
    return None, c.line, c.side


def _challenged_side_params(
    c: BeefChallenge,
) -> tuple[int | None, float | None, str | None]:
    """(picked_team_id, line, side) for the challenged party's Bet row."""
    if c.bet_type in ("straight", "bench_battle"):
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

        # ── Inject injuries for testing ──────────────────────────────────────
        print(f"\nBench Battle — week {WEEK}:  {t1.team_name}  vs  {t2.team_name}")
        print("─" * 60)

        # Team 3 bench: slots 10-15 (Jahmyr Gibbs, DJ Moore, David Njoku,
        #   Tua Tagovailoa, Jonathan Taylor, Mike Evans)
        # Set Jahmyr Gibbs → 'out' and DJ Moore → 'questionable'
        bench_t1 = bench_players(t1, WEEK, db)
        bench_t2 = bench_players(t2, WEEK, db)

        if bench_t1:
            # Mark first bench player as 'out'
            p0 = db.query(Projection).filter_by(
                player_id=bench_t1[0].player_id, week=WEEK, season=SEASON, source=SOURCE
            ).first()
            if p0:
                p0.injury_status = "out"
            # Mark second bench player as 'questionable'
            p1 = db.query(Projection).filter_by(
                player_id=bench_t1[1].player_id, week=WEEK, season=SEASON, source=SOURCE
            ).first()
            if p1:
                p1.injury_status = "questionable"
            db.commit()
            print(f"\nInjuries injected on {t1.team_name}:")
            print(f"  {bench_t1[0].name} → OUT")
            print(f"  {bench_t1[1].name} → QUESTIONABLE")

        # ── Show bench rosters with injury status ────────────────────────────
        def _print_bench(team_name: str, bench: list) -> None:
            print(f"\n{team_name} bench (week {WEEK})\n")
            print("  ┌────────────────────────────┬──────┬──────────────┬──────────┬──────────┐")
            print("  │ Player                     │ Pos  │ Injury       │ FP (PPR) │ Eff. Pts │")
            print("  ├────────────────────────────┼──────┼──────────────┼──────────┼──────────┤")
            for b in bench:
                inj  = b.injury_status or "healthy"
                flag = " ⚠" if b.injury_status in ("out", "ir") else (
                       " ~" if b.injury_status in ("doubtful", "questionable") else "  ")
                print(f"  │ {b.name:<26} │ {b.position:<4} │ {inj:<10}{flag} │ "
                      f"{b.raw_points:>8.2f} │ {b.adjusted_points:>8.2f} │")
            healthy = sum(1 for b in bench if b.injury_status not in ("out", "ir"))
            print("  ├────────────────────────────┼──────┼──────────────┼──────────┼──────────┤")
            print(f"  │ {'Healthy / total':26} │ {healthy}/{len(bench):<3}  │              │          │          │")
            print("  └────────────────────────────┴──────┴──────────────┴──────────┴──────────┘")

        # Re-fetch with updated injury statuses
        bench_t1_fresh = bench_players(t1, WEEK, db)
        bench_t2_fresh = bench_players(t2, WEEK, db)
        _print_bench(t1.team_name, bench_t1_fresh)
        _print_bench(t2.team_name, bench_t2_fresh)

        # ── Attempt 1: should BLOCK (Out player reduces healthy count to 5) ──
        print(f"\n{'─'*60}")
        print(f"Attempt 1: issue bench_battle (expect BLOCKED — "
              f"{bench_t1[0].name} is Out)")
        try:
            issue_challenge(T1, T2, WEEK, "bench_battle", 75.0, db=db)
            print("  ERROR: should have been blocked!")
        except ValueError as e:
            print(f"  Blocked as expected: {e}")

        # ── Change Out → 'doubtful' so healthy count is 6 again ─────────────
        if bench_t1:
            p0 = db.query(Projection).filter_by(
                player_id=bench_t1[0].player_id, week=WEEK, season=SEASON, source=SOURCE
            ).first()
            if p0:
                p0.injury_status = "doubtful"
                db.commit()
            print(f"\n  {bench_t1[0].name} status updated: OUT → DOUBTFUL")
            print(f"  (doubtful counts as healthy for roster purposes, projects 0.25×)")

        # ── Attempt 2: should SUCCEED (all 6 bench players available) ────────
        print(f"\n{'─'*60}")
        print(f"Attempt 2: issue bench_battle (expect SUCCESS)")
        c = issue_challenge(T1, T2, WEEK, "bench_battle", 75.0, db=db)
        print(f"  Challenge #{c.challenge_id} issued  status={c.status}")
        print(f"  {c.description}")
        print(f"  {c.challenger_name}: {c.challenger_moneyline:+,}   "
              f"{c.challenged_name}: {c.challenged_moneyline:+,}")

        # ── Simulate a projection shift AFTER challenge was issued ───────────
        # Bump one bench player's projection by 20% → triggers staleness
        proj_row = db.query(Projection).filter_by(
            player_id=bench_t2_fresh[0].player_id, week=WEEK, season=SEASON, source=SOURCE
        ).first()
        old_pts = proj_row.projected_points if proj_row else 0.0
        new_pts = round(old_pts * 1.22, 2)  # +22% shift
        if proj_row:
            proj_row.projected_points = new_pts
            db.commit()
        print(f"\n  Projection shift injected on {bench_t2_fresh[0].name}: "
              f"{old_pts:.2f} → {new_pts:.2f}  (+22%, triggers staleness)")

        # ── Respond: accept and check staleness_warning ───────────────────────
        print(f"\n{'─'*60}")
        print(f"Respond: accept challenge #{c.challenge_id}")
        result = respond_to_challenge(c.challenge_id, accept=True, db=db)
        print(f"  status         : accepted")
        print(f"  challenger_bet : #{result.challenger_bet_id}")
        print(f"  challenged_bet : #{result.challenged_bet_id}")
        print(f"  staleness_warning: {result.staleness_warning}  "
              f"{'← WARN: odds may be stale' if result.staleness_warning else '← projections stable'}")

        # ── Wallet balances post-accept ───────────────────────────────────────
        print()
        for tid, name in [(T1, t1.team_name), (T2, t2.team_name)]:
            w = db.query(Wallet).filter(Wallet.team_id == tid).first()
            print(f"  {name:<28} wallet: ${w.balance:,.2f}")
