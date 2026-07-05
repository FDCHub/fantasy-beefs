"""
League activity feed — logs challenge and settlement events with optional trash talk.

Event types:
  challenge_issued    — GM1 issues a challenge to GM2
  challenge_accepted  — GM2 accepts (includes staleness flag)
  challenge_declined  — GM2 declines
  challenge_expired   — window elapsed, no response
  challenge_settled   — one event per settled beef challenge
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Bet, BeefChallenge, FeedEvent


# ── Output dataclasses ────────────────────────────────────────────────────────

@dataclass
class FeedEventOut:
    event_id:     int
    league_id:    int
    week:         int
    event_type:   str
    actor_name:   str | None
    target_name:  str | None
    challenge_id: int | None
    bet_id:       int | None
    headline:     str
    trash_talk:   str | None
    created_at:   str


@dataclass
class FeedPage:
    league_id: int
    total:     int
    limit:     int
    offset:    int
    events:    list[FeedEventOut] = field(default_factory=list)


# ── Headline builders ─────────────────────────────────────────────────────────

def _hl_issued(actor: str, target: str, desc: str, amount: float,
               ml_ch: int, ml_cd: int) -> str:
    return (
        f"{actor} challenged {target} — {desc}  "
        f"(${amount:.0f} | {actor}: {ml_ch:+,} / {target}: {ml_cd:+,})"
    )


def _hl_accepted(acceptor: str, issuer: str, stale: bool) -> str:
    flag = "  ⚠ ODDS STALE" if stale else ""
    return f"{acceptor} accepted {issuer}'s challenge{flag}"


def _hl_declined(decliner: str, issuer: str) -> str:
    return f"{decliner} declined {issuer}'s challenge"


def _hl_expired(issuer: str, target: str) -> str:
    return f"{issuer}'s challenge to {target} expired unanswered"


def _hl_countered(counterofferer: str, issuer: str, new_amount: float) -> str:
    return (
        f"{counterofferer} countered {issuer}'s challenge — "
        f"new stake ${new_amount:.0f}"
    )


def _hl_settled(winner: str, loser: str, desc: str, stake: float, payout: float) -> str:
    profit = round(payout - stake, 2)
    return (
        f"{winner} beat {loser} — {desc}  "
        f"(won ${payout:.2f}, +${profit:.2f})"
    )


# ── Serialiser ────────────────────────────────────────────────────────────────

def _to_out(ev: FeedEvent) -> FeedEventOut:
    return FeedEventOut(
        event_id    = ev.id,
        league_id   = ev.league_id,
        week        = ev.week,
        event_type  = ev.event_type,
        actor_name  = ev.actor_team.team_name  if ev.actor_team  else None,
        target_name = ev.target_team.team_name if ev.target_team else None,
        challenge_id = ev.challenge_id,
        bet_id      = ev.bet_id,
        headline    = ev.headline,
        trash_talk  = ev.trash_talk,
        created_at  = ev.created_at.isoformat() if ev.created_at else "",
    )


# ── Log functions ─────────────────────────────────────────────────────────────

def log_challenge_issued(
    challenge:  BeefChallenge,
    db:         Session,
    trash_talk: str | None = None,
) -> None:
    headline = _hl_issued(
        challenge.challenger_team.team_name,
        challenge.challenged_team.team_name,
        challenge.description or "",
        challenge.amount,
        challenge.challenger_moneyline,
        challenge.challenged_moneyline,
    )
    db.add(FeedEvent(
        league_id      = challenge.challenger_team.league_id,
        week           = challenge.week,
        event_type     = "challenge_issued",
        actor_team_id  = challenge.challenger_team_id,
        target_team_id = challenge.challenged_team_id,
        challenge_id   = challenge.id,
        bet_id         = None,
        headline       = headline,
        trash_talk     = trash_talk,
        created_at     = datetime.now(timezone.utc),
    ))
    db.commit()


def log_challenge_accepted(
    challenge:  BeefChallenge,
    db:         Session,
    trash_talk: str | None = None,
) -> None:
    stale    = bool(challenge.staleness_warning)
    headline = _hl_accepted(
        challenge.challenged_team.team_name,
        challenge.challenger_team.team_name,
        stale,
    )
    db.add(FeedEvent(
        league_id      = challenge.challenger_team.league_id,
        week           = challenge.week,
        event_type     = "challenge_accepted",
        actor_team_id  = challenge.challenged_team_id,
        target_team_id = challenge.challenger_team_id,
        challenge_id   = challenge.id,
        bet_id         = None,
        headline       = headline,
        trash_talk     = trash_talk,
        created_at     = datetime.now(timezone.utc),
    ))
    db.commit()


def log_challenge_declined(
    challenge:  BeefChallenge,
    db:         Session,
    trash_talk: str | None = None,
) -> None:
    headline = _hl_declined(
        challenge.challenged_team.team_name,
        challenge.challenger_team.team_name,
    )
    db.add(FeedEvent(
        league_id      = challenge.challenger_team.league_id,
        week           = challenge.week,
        event_type     = "challenge_declined",
        actor_team_id  = challenge.challenged_team_id,
        target_team_id = challenge.challenger_team_id,
        challenge_id   = challenge.id,
        bet_id         = None,
        headline       = headline,
        trash_talk     = trash_talk,
        created_at     = datetime.now(timezone.utc),
    ))
    db.commit()


def log_challenge_expired(
    challenge: BeefChallenge,
    db:        Session,
) -> None:
    """Add expiry event to session. Caller is responsible for committing."""
    headline = _hl_expired(
        challenge.challenger_team.team_name,
        challenge.challenged_team.team_name,
    )
    db.add(FeedEvent(
        league_id      = challenge.challenger_team.league_id,
        week           = challenge.week,
        event_type     = "challenge_expired",
        actor_team_id  = challenge.challenger_team_id,
        target_team_id = challenge.challenged_team_id,
        challenge_id   = challenge.id,
        bet_id         = None,
        headline       = headline,
        trash_talk     = None,
        created_at     = datetime.now(timezone.utc),
    ))


def log_challenge_countered(
    challenge:  BeefChallenge,
    db:         Session,
    trash_talk: str | None = None,
) -> None:
    headline = _hl_countered(
        challenge.challenged_team.team_name,
        challenge.challenger_team.team_name,
        challenge.countered_amount or 0.0,
    )
    db.add(FeedEvent(
        league_id      = challenge.challenger_team.league_id,
        week           = challenge.week,
        event_type     = "challenge_countered",
        actor_team_id  = challenge.challenged_team_id,
        target_team_id = challenge.challenger_team_id,
        challenge_id   = challenge.id,
        bet_id         = None,
        headline       = headline,
        trash_talk     = trash_talk,
        created_at     = datetime.now(timezone.utc),
    ))
    db.commit()


def log_settlement_events(
    settled_bets: list,
    db:           Session,
) -> None:
    """
    Log one feed event per settled beef challenge.
    Called between db.commit() and db.expire_all() in settle_week,
    so attributes are reloadable via lazy loading.
    """
    seen: set[int] = set()

    for bet in settled_bets:
        cid = bet.beef_challenge_id
        if cid is None or cid in seen:
            continue
        seen.add(cid)

        challenge = db.query(BeefChallenge).filter(BeefChallenge.id == cid).first()
        if not challenge:
            continue

        ch_bet = db.query(Bet).filter(Bet.id == challenge.challenger_bet_id).first()
        cd_bet = db.query(Bet).filter(Bet.id == challenge.challenged_bet_id).first()
        if not ch_bet or not cd_bet:
            continue

        if ch_bet.status == "won":
            winner_team = challenge.challenger_team
            loser_team  = challenge.challenged_team
            win_bet_id  = ch_bet.id
            payout      = round(ch_bet.amount * ch_bet.odds, 2)
            stake       = ch_bet.amount
        elif cd_bet.status == "won":
            winner_team = challenge.challenged_team
            loser_team  = challenge.challenger_team
            win_bet_id  = cd_bet.id
            payout      = round(cd_bet.amount * cd_bet.odds, 2)
            stake       = cd_bet.amount
        else:
            continue  # both lost (tie) — skip

        headline = _hl_settled(
            winner_team.team_name,
            loser_team.team_name,
            challenge.description or "",
            stake,
            payout,
        )
        db.add(FeedEvent(
            league_id      = winner_team.league_id,
            week           = challenge.week,
            event_type     = "challenge_settled",
            actor_team_id  = winner_team.id,
            target_team_id = loser_team.id,
            challenge_id   = cid,
            bet_id         = win_bet_id,
            headline       = headline,
            trash_talk     = None,
            created_at     = datetime.now(timezone.utc),
        ))

    db.commit()


# ── Query functions ───────────────────────────────────────────────────────────

def get_league_feed(
    league_id: int,
    db:        Session,
    limit:     int = 50,
    offset:    int = 0,
) -> FeedPage:
    total = db.query(FeedEvent).filter(FeedEvent.league_id == league_id).count()
    rows  = (
        db.query(FeedEvent)
        .filter(FeedEvent.league_id == league_id)
        .order_by(FeedEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return FeedPage(
        league_id = league_id,
        total     = total,
        limit     = limit,
        offset    = offset,
        events    = [_to_out(ev) for ev in rows],
    )


def get_week_feed(
    league_id: int,
    week:      int,
    db:        Session,
) -> list[FeedEventOut]:
    rows = (
        db.query(FeedEvent)
        .filter(FeedEvent.league_id == league_id, FeedEvent.week == week)
        .order_by(FeedEvent.created_at.desc())
        .all()
    )
    return [_to_out(ev) for ev in rows]


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    from db.schema import (
        Projection, SessionLocal, Team, Wallet,
        create_all, drop_all, seed_from_mock,
    )
    from beefs.beef_engine import issue_challenge, respond_to_challenge
    from betting.settlement_engine import settle_week
    from odds.monte_carlo import SEASON, SOURCE

    WEEK       = 3
    LEAGUE_ID  = 1

    # ── Fresh DB ──────────────────────────────────────────────────────────────
    print("Resetting DB for feed test...")
    drop_all()
    create_all()
    seed_from_mock()
    print("Done.\n")

    with SessionLocal() as db:
        teams = {t.id: t for t in db.query(Team).all()}

        def tname(tid: int) -> str:
            return teams[tid].team_name if tid in teams else f"Team{tid}"

        # ── Issue 4 challenges ────────────────────────────────────────────────
        print(f"{'─'*70}")
        print(f"Issuing 4 challenges for week {WEEK}...\n")

        # A: team 1 vs team 3 — straight
        c_a = issue_challenge(
            1, 3, WEEK, "straight", 50.0, db=db,
            trash_talk="I'll crush you this week, enjoy your bench!",
        )
        print(f"  A #{c_a.challenge_id}: {tname(1)} vs {tname(3)}  "
              f"straight  ${c_a.amount:.0f}  "
              f"{c_a.challenger_moneyline:+,}/{c_a.challenged_moneyline:+,}")

        # B: team 2 vs team 4 — spread
        c_b = issue_challenge(
            2, 4, WEEK, "spread", 75.0, db=db, line=10.0,
            trash_talk="Give me the points and I'll still bury you.",
        )
        print(f"  B #{c_b.challenge_id}: {tname(2)} vs {tname(4)}  "
              f"spread +10  ${c_b.amount:.0f}  "
              f"{c_b.challenger_moneyline:+,}/{c_b.challenged_moneyline:+,}")

        # C: team 5 vs team 7 — over_under
        c_c = issue_challenge(
            5, 7, WEEK, "over_under", 60.0, db=db, line=230.0, side="over",
        )
        print(f"  C #{c_c.challenge_id}: {tname(5)} vs {tname(7)}  "
              f"over_under OVER 230  ${c_c.amount:.0f}  "
              f"{c_c.challenger_moneyline:+,}/{c_c.challenged_moneyline:+,}")

        # D: team 6 vs team 8 — straight
        c_d = issue_challenge(
            6, 8, WEEK, "straight", 45.0, db=db,
            trash_talk="Step up if you're not scared.",
        )
        print(f"  D #{c_d.challenge_id}: {tname(6)} vs {tname(8)}  "
              f"straight  ${c_d.amount:.0f}  "
              f"{c_d.challenger_moneyline:+,}/{c_d.challenged_moneyline:+,}")

        # ── Inject staleness on challenge B before acceptance ─────────────────
        print(f"\n{'─'*70}")
        print("Injecting 22% projection shift on challenge B (spread) to trigger staleness warning...")
        from db.schema import Roster
        starter_slots = (
            db.query(Roster)
            .filter(Roster.team_id == 4)
            .order_by(Roster.id)
            .limit(1)
            .all()
        )
        if starter_slots:
            proj = db.query(Projection).filter_by(
                player_id=starter_slots[0].player_id,
                week=WEEK, season=SEASON, source=SOURCE,
            ).first()
            if proj:
                old_pts = proj.projected_points
                proj.projected_points = round(old_pts * 1.22, 2)
                db.commit()
                print(f"  {starter_slots[0].player.name}: "
                      f"{old_pts:.2f} → {proj.projected_points:.2f}  (+22%)")

        # ── Accept A and B, accept C, decline D ───────────────────────────────
        print(f"\n{'─'*70}")
        print("Accepting A (straight)...")
        r_a = respond_to_challenge(
            c_a.challenge_id, accept=True, db=db,
            trash_talk="Challenge accepted. Don't cry when you lose.",
        )
        print(f"  challenger_bet=#{r_a.challenger_bet_id}  "
              f"challenged_bet=#{r_a.challenged_bet_id}  "
              f"stale={r_a.staleness_warning}")

        print("Accepting B (spread — expect staleness warning)...")
        r_b = respond_to_challenge(
            c_b.challenge_id, accept=True, db=db,
            trash_talk="I'll take that bet, bring it.",
        )
        print(f"  challenger_bet=#{r_b.challenger_bet_id}  "
              f"challenged_bet=#{r_b.challenged_bet_id}  "
              f"stale={r_b.staleness_warning}  "
              f"{'← WARN: odds may be stale' if r_b.staleness_warning else '← projections stable'}")

        print("Accepting C (over_under)...")
        r_c = respond_to_challenge(c_c.challenge_id, accept=True, db=db)
        print(f"  challenger_bet=#{r_c.challenger_bet_id}  "
              f"challenged_bet=#{r_c.challenged_bet_id}  "
              f"stale={r_c.staleness_warning}")

        print(f"Declining D (straight)...")
        respond_to_challenge(
            c_d.challenge_id, accept=False, db=db,
            trash_talk="Not interested — pick someone your own size.",
        )
        print("  Declined.")

        # ── Wallet snapshot pre-settle ────────────────────────────────────────
        print(f"\n{'─'*70}")
        print("Wallet balances before settlement:\n")
        wallets_pre = {w.team_id: w.balance for w in db.query(Wallet).all()}
        for tid in sorted(wallets_pre):
            print(f"  {tname(tid):<30} ${wallets_pre[tid]:>9,.2f}")

        # ── Settle week 3 ─────────────────────────────────────────────────────
        print(f"\n{'─'*70}")
        print(f"Settling week {WEEK}...\n")
        report = settle_week(WEEK, db, league_id=1)  # demo script — kept working as-is, not a design decision
        if report.total_bets == 0:
            print(f"  No pending bets for week {WEEK}.")
        else:
            print(f"  {report.total_bets} bets settled  "
                  f"({report.bets_won} won / {report.bets_lost} lost)  "
                  f"staked ${report.total_staked:.2f}  "
                  f"paid out ${report.total_payout:.2f}")

        # ── Feed display ──────────────────────────────────────────────────────
        print(f"\n{'═'*70}")
        print(f"  Week {WEEK} Activity Feed — Fantasy Beefs")
        print(f"{'═'*70}\n")

        feed = get_week_feed(LEAGUE_ID, WEEK, db)

        if not feed:
            print("  (no feed events)\n")
        else:
            W_HEADLINE = 56
            W_TALK     = 30

            print("┌────┬─────────────────────┬──────────────────────────────────────────────────────────┬────────────────────────────────┐")
            print("│ ID │ Type                │ Headline                                                 │ Trash Talk                     │")
            print("├────┼─────────────────────┼──────────────────────────────────────────────────────────┼────────────────────────────────┤")
            for ev in reversed(feed):   # oldest first
                etype = ev.event_type.replace("challenge_", "")[:19]
                hl    = ev.headline[:W_HEADLINE]
                talk  = (ev.trash_talk or "")[:W_TALK]
                print(f"│ {ev.event_id:<2} │ {etype:<19} │ {hl:<{W_HEADLINE}} │ {talk:<{W_TALK}} │")
            print("└────┴─────────────────────┴──────────────────────────────────────────────────────────┴────────────────────────────────┘")
            print(f"\n  {len(feed)} events total\n")

        # ── Full feed (all events newest first via get_league_feed) ───────────
        print(f"\nAll-time feed (paginated, limit=20):\n")
        page = get_league_feed(LEAGUE_ID, db, limit=20, offset=0)
        print(f"  total={page.total}  limit={page.limit}  offset={page.offset}")
        for ev in page.events:
            ts = ev.created_at[:19].replace("T", " ")
            print(f"  [{ts}]  {ev.event_type:<22}  {ev.headline[:60]}")
