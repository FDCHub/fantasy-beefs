"""
Weekly Wrap-Up + Roast Beef — AI-written reports triggered by Tuesday automation.

Two editions per week:
  League Edition  — same for all GMs; matchup recaps, Beef of the Week, standings snapshot
  My Edition      — personalized; their matchup, lineup grade, status tag, playoff prob

Status tags:
  contender — top of standings; play smart, protect the lead
  bubble    — on the playoff line; swing for the fences
  spoiler   — out of contention; ruin someone's season
  chaos     — nothing to lose; beef everyone, spend everything

AI writing chain: Ollama/Qwen → Anthropic Claude → template fallback (always produces output).

Usage (direct):
  python reports/weekly_wrap.py --league 1 --week 5

Via Tuesday sync (step 7):
  generate_weekly_wrap(league_id, week, db, mock_mode=True)
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import (
    Bet,
    BeefChallenge,
    FeedEvent,
    League,
    Matchup,
    Projection,
    Roster,
    ShortfallSweepRecord,
    Team,
    User,
    Wallet,
    WeeklyWrapUp,
    WrapUpGmEdition,
    SessionLocal,
)
from betting.shortfall_sweep import SweepResult, sweep_explanation_text

# ── AI config ─────────────────────────────────────────────────────────────────

OLLAMA_BASE     = os.getenv("OLLAMA_URL",   "http://10.0.0.11:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
_OLLAMA_TIMEOUT = 5

# ── Email config (mirrors tuesday_sync) ──────────────────────────────────────

MOCK_EMAIL_MODE = not bool(os.getenv("SMTP_HOST", ""))
SMTP_HOST       = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER       = os.getenv("SMTP_USER", "")
SMTP_PASS       = os.getenv("SMTP_PASS", "")
EMAIL_FROM      = os.getenv("EMAIL_FROM", "fantasy-beefs@example.com")

# ── Status tag constants ──────────────────────────────────────────────────────

STATUS_CONTENDER = "contender"
STATUS_BUBBLE    = "bubble"
STATUS_SPOILER   = "spoiler"
STATUS_CHAOS     = "chaos"

_STATUS_DISPLAY = {
    STATUS_CONTENDER: "🔥 Contender",
    STATUS_BUBBLE:    "👀 On the Bubble",
    STATUS_SPOILER:   "😤 Spoiler",
    STATUS_CHAOS:     "🍖 The Beef Is Strong Within You",
}

_STATUS_TONE = {
    STATUS_CONTENDER: "Confident, measured. Victory lap energy but don't get cocky.",
    STATUS_BUBBLE:    "Urgent. This is the week that matters. Swing for the fences.",
    STATUS_SPOILER:   "Chaotic neutral. No pressure — go ruin someone's season.",
    STATUS_CHAOS:     "Full send. Nothing to lose. Beef everyone. Control the chaos.",
}

# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class MatchupRecap:
    home_team:       str
    away_team:       str
    home_score:      float
    away_score:      float
    winner:          str
    loser:           str
    margin:          float
    home_bench_left: float
    away_bench_left: float
    home_team_id:    int
    away_team_id:    int
    winner_team_id:  int


@dataclass
class GmWeekData:
    team_id:           int
    team_name:         str
    owner:             str
    first_name:        str
    won:               bool
    score:             float
    opp_score:         float
    opp_name:          str
    margin:            float
    starter_pts:       float
    bench_pts:         float
    best_possible:     float
    pts_left:          float
    lineup_grade:      str
    wins:              int
    losses:            int
    rank:              int
    total_teams:       int
    playoff_prob:      float
    playoff_prob_prev: float
    prob_change:       float
    status_tag:        str
    bet_won:           int
    bet_lost:          int
    bet_net:           float
    sweep_explanation: str   # B2, Section 6 — plain-language shortfall-sweep summary


@dataclass
class BeefHighlight:
    team1:       str
    team2:       str
    description: str
    stakes:      float
    winner:      str
    loser:       str
    drama:       float


@dataclass
class WeekData:
    league_id:      int
    league_name:    str
    week:           int
    matchups:       list[MatchupRecap]
    gm_data:        list[GmWeekData]
    beef_highlight: Optional[BeefHighlight]
    standings:      list[dict]
    power_rankings: list[dict]
    biggest_choke:  Optional[GmWeekData]
    total_bets:     int
    total_staked:   float


@dataclass
class WrapUpOut:
    wrap_up_id:          int
    run_id:              str
    league_id:           int
    week:                int
    status:              str
    league_body:         Optional[str]
    roast_beef:          Optional[str]
    ai_model_used:       Optional[str]
    ai_latency_ms:       Optional[int]
    commissioner_edited: bool
    gm_count:            int
    created_at:          str
    sent_at:             Optional[str]


# ── Data gathering ────────────────────────────────────────────────────────────

def _player_actual(team_id: int, week: int, db: Session) -> tuple[float, float, float]:
    """Returns (starter_pts, bench_pts, best_possible) for a team/week."""
    roster = (
        db.query(Roster)
        .filter(Roster.team_id == team_id)
        .order_by(Roster.id)
        .all()
    )
    starter_ids = [r.player_id for r in roster[:9]]
    bench_ids   = [r.player_id for r in roster[9:]]
    all_ids     = starter_ids + bench_ids

    projs = (
        db.query(Projection)
        .filter(
            Projection.player_id.in_(all_ids),
            Projection.week   == week,
            Projection.source == "fantasypros",
        )
        .all()
    )
    pts = {p.player_id: p.actual_points for p in projs}

    starter_pts   = sum(pts.get(pid, 0.0) for pid in starter_ids)
    bench_pts     = sum(pts.get(pid, 0.0) for pid in bench_ids)
    best_possible = sum(sorted([pts.get(pid, 0.0) for pid in all_ids], reverse=True)[:9])
    return round(starter_pts, 2), round(bench_pts, 2), round(best_possible, 2)


def _lineup_grade(pts_left: float) -> str:
    if pts_left < 5:   return "A"
    if pts_left < 15:  return "B"
    if pts_left < 25:  return "C"
    return "D"


def _compute_record(team_id: int, through_week: int, db: Session) -> tuple[int, int]:
    matchups = (
        db.query(Matchup)
        .filter(
            Matchup.week <= through_week,
            (Matchup.home_team_id == team_id) | (Matchup.away_team_id == team_id),
        )
        .all()
    )
    wins = sum(1 for m in matchups if m.winner_team_id == team_id)
    return wins, len(matchups) - wins


def _compute_total_pf(team_id: int, through_week: int, db: Session) -> float:
    matchups = (
        db.query(Matchup)
        .filter(
            Matchup.week <= through_week,
            (Matchup.home_team_id == team_id) | (Matchup.away_team_id == team_id),
        )
        .all()
    )
    return round(sum(
        m.home_score if m.home_team_id == team_id else m.away_score
        for m in matchups
    ), 2)


def _playoff_prob(rank: int, total_teams: int, wins: int, losses: int, week: int) -> float:
    playoff_spots = max(1, total_teams // 2 - 1)
    remaining     = max(0, 14 - week)
    games_played  = wins + losses
    if games_played == 0:
        return round(playoff_spots / total_teams, 3)
    win_pct   = wins / games_played
    rank_prob = max(0.05, min(0.95, 1.0 - (rank - 1) / max(1, total_teams - 1)))
    weight    = max(0.0, min(1.0, 1.0 - remaining / 14.0))
    prob      = rank_prob * weight + (win_pct * 0.8) * (1.0 - weight)
    return round(min(0.99, max(0.01, prob)), 3)


def _pick_status_tag(rank: int, total_teams: int, wins: int, losses: int, week: int) -> str:
    playoff_spots = max(1, total_teams // 2 - 1)
    remaining     = max(0, 14 - week)
    games_played  = wins + losses

    if (rank >= total_teams - 2
            and games_played > 0
            and wins / games_played < 0.35
            and remaining <= 5):
        return STATUS_CHAOS
    if rank <= playoff_spots and games_played > 0 and wins / games_played >= 0.6:
        return STATUS_CONTENDER
    if rank <= playoff_spots + 2:
        return STATUS_BUBBLE
    return STATUS_SPOILER


def _week_bet_totals(matchup_ids: set[int], db: Session) -> tuple[int, float]:
    if not matchup_ids:
        return 0, 0.0
    bets = (
        db.query(Bet)
        .filter(Bet.matchup_id.in_(matchup_ids), Bet.status.in_(["won", "lost"]))
        .all()
    )
    return len(bets), round(sum(b.amount for b in bets), 2)


def _pick_beef_of_week(
    league_id: int,
    week:      int,
    recaps:    list[MatchupRecap],
    db:        Session,
) -> Optional[BeefHighlight]:
    beefs = (
        db.query(BeefChallenge)
        .filter(BeefChallenge.week == week, BeefChallenge.status == "accepted")
        .all()
    )
    best_drama = 0.0
    best: Optional[BeefHighlight] = None

    for b in beefs:
        ch = db.query(Bet).filter(Bet.id == b.challenger_bet_id).first()
        cd = db.query(Bet).filter(Bet.id == b.challenged_bet_id).first()
        if not ch or not cd:
            continue
        if ch.status == "won":
            winner, loser = b.challenger_team, b.challenged_team
            upset = 1.5 if b.challenger_moneyline > 0 else 1.0 + abs(b.challenger_moneyline) / 200.0
        elif cd.status == "won":
            winner, loser = b.challenged_team, b.challenger_team
            upset = 1.5 if b.challenged_moneyline > 0 else 1.0 + abs(b.challenged_moneyline) / 200.0
        else:
            continue
        drama = b.amount * upset
        if drama > best_drama:
            best_drama = drama
            best = BeefHighlight(
                team1=b.challenger_team.team_name,
                team2=b.challenged_team.team_name,
                description=b.description or "a straight-up battle",
                stakes=b.amount,
                winner=winner.team_name,
                loser=loser.team_name,
                drama=round(drama, 1),
            )

    if best is None and recaps:
        closest = min(recaps, key=lambda r: r.margin)
        best = BeefHighlight(
            team1=closest.home_team,
            team2=closest.away_team,
            description=f"closest matchup of the week — decided by {closest.margin:.1f} pts",
            stakes=0.0,
            winner=closest.winner,
            loser=closest.loser,
            drama=round(100.0 / (closest.margin + 1.0), 1),
        )
    return best


def _sweep_explanation_for(league_id: int, team_id: int, week: int, db: Session) -> str:
    """
    Reads an EXISTING ShortfallSweepRecord for this team/week, if the sweep
    has already run (B2, Section 6) — never triggers a new sweep as a side
    effect of generating a wrap. If the sweep hasn't run yet for this week,
    returns a neutral placeholder (template-fallback-safe, matching this
    file's own 'always produces output' convention)."""
    record = (
        db.query(ShortfallSweepRecord)
        .filter(
            ShortfallSweepRecord.league_id == league_id,
            ShortfallSweepRecord.team_id   == team_id,
            ShortfallSweepRecord.week      == week,
        )
        .first()
    )
    if not record:
        return "Shortfall sweep for this week hasn't run yet."
    return sweep_explanation_text(SweepResult(
        team_id=team_id, week=week,
        weekly_min_cents=record.weekly_min_cents,
        wagered_cents=record.wagered_cents,
        shortfall_cents=record.shortfall_cents,
        covered_cents=record.covered_cents,
        uncovered_cents=record.uncovered_cents,
        swept=record.shortfall_cents > 0,
        already_run=True,
    ))


def _gather_week_data(league_id: int, week: int, db: Session) -> WeekData:
    league = db.query(League).filter(League.id == league_id).first()
    teams  = db.query(Team).filter(Team.league_id == league_id).order_by(Team.id).all()

    week_matchups = (
        db.query(Matchup)
        .filter(Matchup.league_id == league_id, Matchup.week == week)
        .all()
    )

    # Standings through this week
    records = []
    for t in teams:
        w, l = _compute_record(t.id, week, db)
        pf   = _compute_total_pf(t.id, week, db)
        records.append({"team_id": t.id, "team_name": t.team_name,
                        "owner": t.owner, "wins": w, "losses": l, "pf": pf})
    records.sort(key=lambda r: (-r["wins"], -r["pf"]))
    for i, r in enumerate(records):
        r["rank"] = i + 1
    rank_map = {r["team_id"]: r for r in records}

    # Power rankings (avg pts last 3 weeks)
    pw_weeks  = list(range(max(1, week - 2), week + 1))
    pw_scores: dict[int, list[float]] = {t.id: [] for t in teams}
    for wk in pw_weeks:
        for m in db.query(Matchup).filter(Matchup.league_id == league_id, Matchup.week == wk).all():
            pw_scores[m.home_team_id].append(m.home_score)
            pw_scores[m.away_team_id].append(m.away_score)
    power = []
    for t in teams:
        sc  = pw_scores[t.id]
        avg = round(sum(sc) / len(sc), 1) if sc else 0.0
        power.append({"team_id": t.id, "team_name": t.team_name, "avg_pts": avg})
    power.sort(key=lambda r: -r["avg_pts"])
    for i, r in enumerate(power):
        r["power_rank"] = i + 1

    # Matchup recaps
    recaps: list[MatchupRecap] = []
    matchup_for_team: dict[int, Matchup] = {}
    for m in week_matchups:
        hs, hb, hbest = _player_actual(m.home_team_id, week, db)
        as_, ab, abest = _player_actual(m.away_team_id, week, db)
        hname = m.home_team.team_name
        aname = m.away_team.team_name
        wid   = m.winner_team_id or 0
        recaps.append(MatchupRecap(
            home_team=hname,      away_team=aname,
            home_score=m.home_score, away_score=m.away_score,
            winner=hname if wid == m.home_team_id else aname,
            loser=aname  if wid == m.home_team_id else hname,
            margin=round(abs(m.home_score - m.away_score), 2),
            home_bench_left=round(hbest - hs, 2),
            away_bench_left=round(abest - as_, 2),
            home_team_id=m.home_team_id,
            away_team_id=m.away_team_id,
            winner_team_id=wid,
        ))
        matchup_for_team[m.home_team_id] = m
        matchup_for_team[m.away_team_id] = m

    week_matchup_ids = {m.id for m in week_matchups}
    total_bets, total_staked = _week_bet_totals(week_matchup_ids, db)
    total_teams = len(teams)

    gm_list: list[GmWeekData] = []
    biggest_choke: Optional[GmWeekData] = None

    for t in teams:
        rec  = rank_map[t.id]
        wins, losses, rank = rec["wins"], rec["losses"], rec["rank"]

        m = matchup_for_team.get(t.id)
        if m:
            is_home  = m.home_team_id == t.id
            score    = m.home_score  if is_home else m.away_score
            opp_sc   = m.away_score  if is_home else m.home_score
            opp_id   = m.away_team_id if is_home else m.home_team_id
            opp_t    = db.query(Team).filter(Team.id == opp_id).first()
            opp_name = opp_t.team_name if opp_t else "Unknown"
            won      = m.winner_team_id == t.id
            margin   = round(score - opp_sc, 2)
        else:
            score = opp_sc = margin = 0.0
            opp_name = "Unknown"
            won = False

        sp, bp, best = _player_actual(t.id, week, db)
        pts_left     = round(best - sp, 2)

        wallet   = db.query(Wallet).filter(Wallet.team_id == t.id).first()
        bet_won  = bet_lost = 0
        bet_net  = 0.0
        if wallet and week_matchup_ids:
            for b in db.query(Bet).filter(
                Bet.wallet_id   == wallet.id,
                Bet.matchup_id.in_(week_matchup_ids),
                Bet.status.in_(["won", "lost"]),
            ).all():
                if b.status == "won":
                    bet_won += 1
                    bet_net += round(b.amount * b.odds - b.amount, 2)
                else:
                    bet_lost += 1
                    bet_net  -= b.amount

        prob      = _playoff_prob(rank, total_teams, wins, losses, week)
        prev_wins = max(0, wins - (1 if won else 0))
        prev_loss = max(0, losses - (0 if won else 1))
        prob_prev = _playoff_prob(rank, total_teams, prev_wins, prev_loss, max(1, week - 1))

        status = _pick_status_tag(rank, total_teams, wins, losses, week)
        first  = t.owner.split()[0] if t.owner else t.team_name

        gm = GmWeekData(
            team_id=t.id, team_name=t.team_name, owner=t.owner, first_name=first,
            won=won, score=score, opp_score=opp_sc, opp_name=opp_name, margin=margin,
            starter_pts=sp, bench_pts=bp, best_possible=best, pts_left=pts_left,
            lineup_grade=_lineup_grade(pts_left),
            wins=wins, losses=losses, rank=rank, total_teams=total_teams,
            playoff_prob=prob, playoff_prob_prev=prob_prev,
            prob_change=round(prob - prob_prev, 3),
            status_tag=status,
            bet_won=bet_won, bet_lost=bet_lost, bet_net=round(bet_net, 2),
            sweep_explanation=_sweep_explanation_for(league_id, t.id, week, db),
        )
        gm_list.append(gm)

        if not won and pts_left > 10:
            if biggest_choke is None or pts_left > biggest_choke.pts_left:
                biggest_choke = gm

    return WeekData(
        league_id=league_id,
        league_name=league.name if league else f"League {league_id}",
        week=week,
        matchups=recaps,
        gm_data=gm_list,
        beef_highlight=_pick_beef_of_week(league_id, week, recaps, db),
        standings=records,
        power_rankings=power,
        biggest_choke=biggest_choke,
        total_bets=total_bets,
        total_staked=total_staked,
    )


# ── AI prompts ────────────────────────────────────────────────────────────────

_LEAGUE_PROMPT = """\
You are the voice of Fantasy Beefs, a trash-talk-heavy fantasy football league newsletter.
Tone: confident, funny, irreverent. Jedi references encouraged ("The Force was not with him").
Brand voice: ESPN SportsCenter meets a group chat that's been beefing all season.

WEEK {week} DATA:

MATCHUP RESULTS:
{matchup_lines}

BETTING THIS WEEK:
  Total bets placed: {total_bets}   Total wagered: ${total_staked:.2f}

BEEF OF THE WEEK:
{beef_section}

STANDINGS (after week {week}):
{standings_lines}

POWER RANKINGS (last 3 weeks avg pts):
{power_lines}

BIGGEST CHOKE THIS WEEK:
{choke_section}

Write the Weekly Wrap-Up using these EXACT section headers:

=== MATCHUP RECAPS ===
[2-3 sentences per matchup. Winner gets a victory lap, loser gets roasted. Name teams and scores.]

=== BEEF OF THE WEEK ===
[2 paragraphs on the most compelling storyline. Playful ribbing. One Jedi reference required.]

=== ROAST BEEF ===
[1-2 sentences on the week's biggest choke or embarrassing loss. Name the GM. Don't hold back — but keep it playful.]

=== STANDINGS SNAPSHOT ===
[3-4 sentences on the standings. Who's a threat, who's on life support.]

Keep it tight — 400-550 words total. Output ONLY the wrap-up text with those four headers.
"""

_GM_PROMPT = """\
You are writing a personalized weekly update for {first_name}, GM of {team_name} in Fantasy Beefs.

THEIR WEEK {week}:
  Result: {result_line}
  Lineup grade: {lineup_grade} (left {pts_left:.1f} pts on bench; best possible was {best_possible:.1f})
  Betting: {bet_line}
  Weekly wagering minimum: {sweep_line}
  Record: {wins}-{losses}, Rank #{rank} of {total_teams}
  Status: {status_display}
  Playoff probability: {playoff_prob:.0%} ({prob_change:+.1%} from last week)

Write a personalized 3-paragraph update:
  Para 1: Their matchup — their score, opponent, what went right/wrong. Make it specific to them. Playful.
  Para 2: Lineup grade and betting. If grade C or D, gently roast the lineup decision. If bets went well, celebrate; if not, commiserate. If any shortfall swept, mention it plainly — no shaming, just the facts.
  Para 3: Status update with the energy of "{status_display}". Specific advice for next week based on their situation.

Tone: {tone}
Brand voice: confident, funny, trash-talk energy. Jedi references welcome.
Output only the 3 paragraphs. No headers. No intro/outro.
"""


def _league_prompt(data: WeekData) -> str:
    matchup_lines = "\n".join(
        f"  {r.winner} def {r.loser}  {r.home_score:.1f}-{r.away_score:.1f}  "
        f"(margin {r.margin:.1f} | {r.home_team} bench left: {r.home_bench_left:.1f} "
        f"| {r.away_team} bench left: {r.away_bench_left:.1f})"
        for r in data.matchups
    )
    b = data.beef_highlight
    if b:
        beef_section = (
            f"  {b.winner} beat {b.loser} — {b.description}"
            + (f"  (${b.stakes:.0f} on the line)" if b.stakes > 0 else "")
        )
    else:
        beef_section = "  No active beefs this week."

    standings_lines = "\n".join(
        f"  #{r['rank']}  {r['team_name']:<28}  {r['wins']}-{r['losses']}  PF: {r['pf']:.1f}"
        for r in data.standings
    )
    power_lines = "\n".join(
        f"  #{r['power_rank']}  {r['team_name']:<28}  {r['avg_pts']:.1f} avg"
        for r in data.power_rankings
    )
    if data.biggest_choke:
        c = data.biggest_choke
        choke_section = (
            f"  {c.team_name} ({c.first_name}) left {c.pts_left:.1f} pts on the bench "
            f"and lost by {abs(c.margin):.1f}. Lineup grade: {c.lineup_grade}."
        )
    else:
        choke_section = "  No notable lineup disasters."

    return _LEAGUE_PROMPT.format(
        week=data.week,
        matchup_lines=matchup_lines,
        total_bets=data.total_bets,
        total_staked=data.total_staked,
        beef_section=beef_section,
        standings_lines=standings_lines,
        power_lines=power_lines,
        choke_section=choke_section,
    )


def _gm_prompt(gm: GmWeekData, data: WeekData) -> str:
    result_line = (
        f"{'WON' if gm.won else 'LOST'}  {gm.score:.1f}-{gm.opp_score:.1f} "
        f"vs {gm.opp_name}  (margin {gm.margin:+.1f})"
    )
    if gm.bet_won + gm.bet_lost > 0:
        bet_line = f"{gm.bet_won}W / {gm.bet_lost}L  net: ${gm.bet_net:+.2f}"
    else:
        bet_line = "no bets placed this week"

    return _GM_PROMPT.format(
        first_name     = gm.first_name,
        team_name      = gm.team_name,
        week           = data.week,
        result_line    = result_line,
        lineup_grade   = gm.lineup_grade,
        pts_left       = gm.pts_left,
        best_possible  = gm.best_possible,
        bet_line       = bet_line,
        sweep_line     = gm.sweep_explanation,
        wins           = gm.wins,
        losses         = gm.losses,
        rank           = gm.rank,
        total_teams    = gm.total_teams,
        status_display = _STATUS_DISPLAY[gm.status_tag],
        playoff_prob   = gm.playoff_prob,
        prob_change    = gm.prob_change,
        tone           = _STATUS_TONE[gm.status_tag],
    )


# ── AI backends ───────────────────────────────────────────────────────────────

def _call_ollama(prompt: str) -> tuple[str, int]:
    import urllib.request
    payload = json.dumps({
        "model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=_OLLAMA_TIMEOUT) as resp:
        body = json.loads(resp.read())
    ms   = int((time.monotonic() - t0) * 1000)
    text = body.get("response", "").strip()
    if not text:
        raise ValueError("Empty response from Ollama")
    return text, ms


def _call_anthropic(prompt: str) -> tuple[str, int]:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    t0  = time.monotonic()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1400,
        messages=[{"role": "user", "content": prompt}],
    )
    ms   = int((time.monotonic() - t0) * 1000)
    text = msg.content[0].text.strip() if msg.content else ""
    if not text:
        raise ValueError("Empty response from Anthropic")
    return text, ms


def _call_ai(prompt: str) -> tuple[str, str, int]:
    """Try Ollama → Anthropic → fail silently. Returns (text, model, latency_ms)."""
    try:
        text, ms = _call_ollama(prompt)
        return text, f"ollama/{OLLAMA_MODEL}", ms
    except Exception:
        pass
    try:
        text, ms = _call_anthropic(prompt)
        return text, "claude-haiku-4-5-20251001", ms
    except Exception:
        pass
    return "", "none", 0


# ── Template fallbacks ────────────────────────────────────────────────────────

def _template_league_edition(data: WeekData) -> str:
    lines: list[str] = []

    lines.append("=== MATCHUP RECAPS ===")
    lines.append("")
    for r in data.matchups:
        lines.append(
            f"{r.winner} took down {r.loser}, {r.home_score:.1f}-{r.away_score:.1f}. "
            f"Margin: {r.margin:.1f} pts. "
            f"{'The Force was strong in ' + r.winner + ' this week.' if r.margin > 20 else r.winner + ' got it done.'} "
            f"{r.loser}: the Force was not with them."
        )
        lines.append("")

    lines.append("=== BEEF OF THE WEEK ===")
    lines.append("")
    if data.beef_highlight:
        b = data.beef_highlight
        if b.stakes > 0:
            lines.append(
                f"{b.winner} and {b.loser} settled their differences with ${b.stakes:.0f} on the line. "
                f"{b.winner} executed the classic Jedi mind trick and walked away richer. {b.description}."
            )
            lines.append("")
            lines.append(
                f"{b.loser} must now contemplate their choices from the Dark Side of the standings."
            )
        else:
            lines.append(
                f"The matchup everyone was watching: {b.winner} vs {b.loser}. {b.description}. "
                f"{b.winner} came out on top. {b.loser}: next week is a new disturbance in the Force."
            )
            lines.append("")
            lines.append(
                f"No money on the line, but respect? That costs extra."
            )
    else:
        lines.append("A quiet week on the beef front. Everyone conserving energy. For now.")
    lines.append("")

    lines.append("=== ROAST BEEF ===")
    lines.append("")
    if data.biggest_choke:
        c = data.biggest_choke
        lines.append(
            f"{c.team_name} ({c.first_name}) left {c.pts_left:.1f} fantasy points rotting on the bench "
            f"and still lost. Lineup grade: {c.lineup_grade}. "
            f"{'Do better.' if c.lineup_grade == 'D' else 'Close, but no cigar.'}"
        )
    else:
        lines.append("Everyone set a reasonable lineup this week. Unprecedented. Growth.")
    lines.append("")

    lines.append("=== STANDINGS SNAPSHOT ===")
    lines.append("")
    top = data.standings[:3]
    bot = data.standings[-3:]
    top_str = ", ".join(f"{r['team_name']} ({r['wins']}-{r['losses']})" for r in top)
    bot_str = ", ".join(f"{r['team_name']} ({r['wins']}-{r['losses']})" for r in bot)
    lines.append(
        f"At the top: {top_str}. These teams are building something. "
        f"At the bottom: {bot_str}. Time is running out — or the chaos begins. "
        f"Week {data.week} is in the books. See you Tuesday."
    )

    return "\n".join(lines)


def _template_gm_edition(gm: GmWeekData) -> str:
    lines: list[str] = []

    result_word  = "WON" if gm.won else "LOST"
    matchup_line = (
        f"{result_word} {gm.score:.1f}–{gm.opp_score:.1f} vs {gm.opp_name} "
        f"(margin {gm.margin:+.1f}). "
    )
    if gm.won:
        matchup_line += f"The Force was with {gm.first_name} this week. "
        if gm.margin > 30:
            matchup_line += "That wasn't a game — that was a statement."
        else:
            matchup_line += "Hard fought, well earned."
    else:
        matchup_line += f"The Force was not with {gm.first_name} this week. "
        if abs(gm.margin) < 10:
            matchup_line += "A heartbreaker — this one stings."
        else:
            matchup_line += f"Lost by {abs(gm.margin):.1f} — no sugarcoating it."
    lines.append(matchup_line)
    lines.append("")

    grade_msgs = {
        "A": f"Lineup was clean — only {gm.pts_left:.1f} pts left on the bench. Efficient.",
        "B": f"Left {gm.pts_left:.1f} pts on the bench. A few roster tweaks and you're cooking.",
        "C": f"Left {gm.pts_left:.1f} pts on the bench. Your bench was worth more than your starters this week. That's a C.",
        "D": f"Left {gm.pts_left:.1f} pts on the bench. Best possible lineup would have scored {gm.best_possible:.1f}. "
             f"That's a D, {gm.first_name}. The lineup fairy is weeping.",
    }
    lines.append(grade_msgs[gm.lineup_grade])
    if gm.bet_won + gm.bet_lost > 0:
        if gm.bet_net > 0:
            lines.append(f"Bets: {gm.bet_won}W / {gm.bet_lost}L — +${gm.bet_net:.2f}. The wallets are happy.")
        else:
            lines.append(f"Bets: {gm.bet_won}W / {gm.bet_lost}L — ${gm.bet_net:.2f}. Double down or sit out.")
    else:
        lines.append("No bets placed this week. Bold strategy.")
    lines.append(gm.sweep_explanation)
    lines.append("")

    status_advice = {
        STATUS_CONTENDER: (
            f"You're #{gm.rank} with a {gm.wins}-{gm.losses} record. "
            f"Playoff probability: {gm.playoff_prob:.0%} ({gm.prob_change:+.1%}). "
            f"Play smart. Protect the lead. Calculated beefs only. Don't blow it."
        ),
        STATUS_BUBBLE: (
            f"You're #{gm.rank} — right on the playoff bubble. {gm.wins}-{gm.losses}. "
            f"Playoff probability: {gm.playoff_prob:.0%} ({gm.prob_change:+.1%}). "
            f"This is the week to swing. Aggressive FAAB. Take the beef. Go get it."
        ),
        STATUS_SPOILER: (
            f"You're #{gm.rank} at {gm.wins}-{gm.losses}. The playoffs aren't coming — "
            f"but you can still ruin someone's season. "
            f"Pick a contender. Make it hurt. Spoiler energy only."
        ),
        STATUS_CHAOS: (
            f"#{gm.rank}, {gm.wins}-{gm.losses}. The math is grim. "
            f"But you control the chaos. Full send. Beef everyone. "
            f"Spend every dollar. You have nothing to lose — use that."
        ),
    }[gm.status_tag]
    lines.append(f"{_STATUS_DISPLAY[gm.status_tag]}")
    lines.append(status_advice)

    return "\n".join(lines)


# ── Section extraction ────────────────────────────────────────────────────────

def _extract_section(text: str, section_name: str) -> str:
    pattern = rf"===\s*{re.escape(section_name)}\s*===\s*(.*?)(?====|\Z)"
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


# ── Feed posting ──────────────────────────────────────────────────────────────

def _post_to_feed(league_id: int, week: int, body: str, db: Session) -> None:
    roast = _extract_section(body, "ROAST BEEF")
    # First non-empty line of matchup recaps as headline
    recaps = _extract_section(body, "MATCHUP RECAPS")
    headline = next((ln.strip() for ln in recaps.splitlines() if ln.strip()), "")
    if not headline:
        headline = f"Week {week} Wrap-Up — Fantasy Beefs"

    db.add(FeedEvent(
        league_id      = league_id,
        week           = week,
        event_type     = "weekly_wrapup",
        actor_team_id  = None,
        target_team_id = None,
        challenge_id   = None,
        bet_id         = None,
        headline       = headline[:200],
        trash_talk     = roast[:300] if roast else None,
        created_at     = datetime.now(timezone.utc),
    ))
    db.commit()


# ── Email transport ───────────────────────────────────────────────────────────

def _send_email(to: str, subject: str, body: str, *, mock_mode: bool = MOCK_EMAIL_MODE) -> bool:
    if not to or "@" not in to:
        return False
    if mock_mode:
        print(f"\n{'='*72}")
        print(f"[MOCK WRAP-UP] To: {to}")
        print(f"[MOCK WRAP-UP] Subject: {subject}")
        print(f"{'='*72}")
        print(body)
        print(f"{'='*72}\n")
        return True
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"]    = EMAIL_FROM
        msg["To"]      = to
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            if SMTP_PORT != 25:
                server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(EMAIL_FROM, [to], msg.as_string())
        return True
    except Exception as e:
        print(f"[WRAP-UP EMAIL ERROR] to={to}: {e}")
        return False


def _gm_email(team_id: int, db: Session) -> str:
    user = db.query(User).filter(User.team_id == team_id).first()
    if user:
        return user.email
    team = db.query(Team).filter(Team.id == team_id).first()
    return team.email if team else ""


def _build_gm_email_body(
    team_name:      str,
    owner:          str,
    week:           int,
    my_edition:     str,
    league_body:    str,
    status_display: str,
) -> str:
    first = owner.split()[0] if owner else team_name
    divider = "─" * 64
    return "\n".join([
        f"Hey {first},",
        "",
        f"Week {week} is in the books. Here's your Fantasy Beefs wrap-up.",
        "",
        f"YOUR STATUS: {status_display}",
        divider,
        my_edition,
        "",
        divider,
        "LEAGUE EDITION",
        divider,
        league_body,
        "",
        "—",
        "Fantasy Beefs Platform",
    ])


# ── Main generation ───────────────────────────────────────────────────────────

def generate_weekly_wrap(
    league_id: int,
    week:      int,
    db:        Session,
    *,
    mock_mode: bool = MOCK_EMAIL_MODE,
) -> WrapUpOut:
    """
    Generate the full weekly wrap-up for league/week.
    Stores draft in DB, posts to feed, and sends emails to all GMs.
    Returns WrapUpOut with the new record.
    """
    run_id = uuid.uuid4().hex[:8]

    data = _gather_week_data(league_id, week, db)

    # League edition
    ai_text, model_used, latency_ms = _call_ai(_league_prompt(data))
    if not ai_text:
        ai_text     = _template_league_edition(data)
        model_used  = "template"
        latency_ms  = 0

    roast_beef = _extract_section(ai_text, "ROAST BEEF")

    wu = WeeklyWrapUp(
        run_id              = run_id,
        league_id           = league_id,
        week                = week,
        status              = "draft",
        league_body         = ai_text,
        roast_beef          = roast_beef,
        ai_model_used       = model_used,
        ai_latency_ms       = latency_ms,
        commissioner_edited = 0,
        created_at          = datetime.now(timezone.utc),
        updated_at          = datetime.now(timezone.utc),
    )
    db.add(wu)
    db.flush()

    # Per-GM editions
    for gm in data.gm_data:
        gm_text, _, _ = _call_ai(_gm_prompt(gm, data))
        if not gm_text:
            gm_text = _template_gm_edition(gm)

        db.add(WrapUpGmEdition(
            wrap_up_id          = wu.id,
            league_id           = league_id,
            team_id             = gm.team_id,
            week                = week,
            body                = gm_text,
            status_tag          = gm.status_tag,
            playoff_prob_change = gm.prob_change,
            sent                = 0,
            created_at          = datetime.now(timezone.utc),
        ))

    db.commit()

    # Post to feed
    _post_to_feed(league_id, week, ai_text, db)

    # Send emails
    send_wrap_up(wu.id, db, mock_mode=mock_mode)

    gm_count = db.query(WrapUpGmEdition).filter(WrapUpGmEdition.wrap_up_id == wu.id).count()
    return _to_wrap_out(wu, gm_count)


def send_wrap_up(wrap_up_id: int, db: Session, *, mock_mode: bool = MOCK_EMAIL_MODE) -> int:
    """Send League Edition + My Edition emails to all GMs. Returns emails sent count."""
    wu = db.query(WeeklyWrapUp).filter(WeeklyWrapUp.id == wrap_up_id).first()
    if not wu:
        raise ValueError(f"Wrap-up {wrap_up_id} not found")

    editions = (
        db.query(WrapUpGmEdition)
        .filter(WrapUpGmEdition.wrap_up_id == wrap_up_id)
        .all()
    )
    sent = 0
    for ed in editions:
        team = db.query(Team).filter(Team.id == ed.team_id).first()
        if not team:
            continue
        email   = _gm_email(ed.team_id, db)
        status  = _STATUS_DISPLAY.get(ed.status_tag or "", "")
        body    = _build_gm_email_body(
            team_name=team.team_name, owner=team.owner,
            week=wu.week, my_edition=ed.body or "",
            league_body=wu.league_body or "", status_display=status,
        )
        subject = f"[Fantasy Beefs] Week {wu.week} Wrap-Up — {team.team_name}  {status}"
        ok = _send_email(email, subject, body, mock_mode=mock_mode)
        if ok:
            sent += 1
            ed.sent    = 1
            ed.sent_at = datetime.now(timezone.utc)

    wu.status  = "sent"
    wu.sent_at = datetime.now(timezone.utc)
    db.commit()
    return sent


# ── DB helpers ────────────────────────────────────────────────────────────────

def _to_wrap_out(wu: WeeklyWrapUp, gm_count: int) -> WrapUpOut:
    return WrapUpOut(
        wrap_up_id          = wu.id,
        run_id              = wu.run_id,
        league_id           = wu.league_id,
        week                = wu.week,
        status              = wu.status,
        league_body         = wu.league_body,
        roast_beef          = wu.roast_beef,
        ai_model_used       = wu.ai_model_used,
        ai_latency_ms       = wu.ai_latency_ms,
        commissioner_edited = bool(wu.commissioner_edited),
        gm_count            = gm_count,
        created_at          = wu.created_at.isoformat() if wu.created_at else "",
        sent_at             = wu.sent_at.isoformat()    if wu.sent_at    else None,
    )


def get_wrap_up(league_id: int, week: int, db: Session) -> Optional[WrapUpOut]:
    wu = (
        db.query(WeeklyWrapUp)
        .filter(WeeklyWrapUp.league_id == league_id, WeeklyWrapUp.week == week)
        .order_by(WeeklyWrapUp.created_at.desc())
        .first()
    )
    if not wu:
        return None
    gm_count = db.query(WrapUpGmEdition).filter(WrapUpGmEdition.wrap_up_id == wu.id).count()
    return _to_wrap_out(wu, gm_count)


def get_wrap_up_list(league_id: int, db: Session, *, limit: int = 20) -> list[WrapUpOut]:
    rows = (
        db.query(WeeklyWrapUp)
        .filter(WeeklyWrapUp.league_id == league_id)
        .order_by(WeeklyWrapUp.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for wu in rows:
        gc = db.query(WrapUpGmEdition).filter(WrapUpGmEdition.wrap_up_id == wu.id).count()
        result.append(_to_wrap_out(wu, gc))
    return result


def update_wrap_up(
    wrap_up_id:  int,
    league_body: Optional[str],
    roast_beef:  Optional[str],
    db:          Session,
) -> WrapUpOut:
    wu = db.query(WeeklyWrapUp).filter(WeeklyWrapUp.id == wrap_up_id).first()
    if not wu:
        raise ValueError(f"Wrap-up {wrap_up_id} not found")
    if league_body is not None:
        wu.league_body = league_body
    if roast_beef is not None:
        wu.roast_beef = roast_beef
    wu.commissioner_edited = 1
    wu.updated_at          = datetime.now(timezone.utc)
    db.commit()
    gc = db.query(WrapUpGmEdition).filter(WrapUpGmEdition.wrap_up_id == wu.id).count()
    return _to_wrap_out(wu, gc)


def get_gm_editions(wrap_up_id: int, db: Session) -> list[dict]:
    editions = (
        db.query(WrapUpGmEdition)
        .filter(WrapUpGmEdition.wrap_up_id == wrap_up_id)
        .all()
    )
    result = []
    for ed in editions:
        team = db.query(Team).filter(Team.id == ed.team_id).first()
        result.append({
            "edition_id":          ed.id,
            "team_id":             ed.team_id,
            "team_name":           team.team_name if team else f"team_{ed.team_id}",
            "status_tag":          ed.status_tag,
            "status_display":      _STATUS_DISPLAY.get(ed.status_tag or "", ""),
            "playoff_prob_change": ed.playoff_prob_change,
            "body":                ed.body,
            "sent":                bool(ed.sent),
            "sent_at":             ed.sent_at.isoformat() if ed.sent_at else None,
        })
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    parser = argparse.ArgumentParser(description="Fantasy Beefs Weekly Wrap-Up Generator")
    parser.add_argument("--league", type=int, default=1,    help="League ID")
    parser.add_argument("--week",   type=int, required=True, help="Week number")
    parser.add_argument("--live",   action="store_true",     help="Send real emails (not mock)")
    args = parser.parse_args()

    with SessionLocal() as db:
        print(f"[WeeklyWrap] Generating week {args.week} for league {args.league}...")
        out = generate_weekly_wrap(
            args.league, args.week, db,
            mock_mode=not args.live,
        )
        print(f"\n[WeeklyWrap] Done  run_id={out.run_id}  model={out.ai_model_used}"
              f"  gm_editions={out.gm_count}  status={out.status}")
