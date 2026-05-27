"""
Tuesday Automation — master job at 12:01am UTC every Tuesday.

Execution order (each step is isolated — one failure never kills the run):
  1. settle_bets       — settle_week() for the completed week
  2. execute_rules     — execute_weekly_rules() for all active commissioner rules
  3. freeze_wallets    — check every team's bet wallet; freeze any <= $0
  4. apply_topups      — apply_pending_topups() for due waiver top-ups
  5. faab_report       — build waiver-budget table for Yahoo FAAB entry
  6. email_commissioner — send sync report + frozen wallet alerts to commissioner
  7. weekly_wrapup     — AI weekly wrap-up + Roast Beef, emails all GMs
  8. power_rankings    — compute & publish updated power rankings to feed
  9. email_gms         — send personal week summary to every GM

Environment variables:
  SMTP_HOST            — SMTP server (mock email if unset)
  SMTP_PORT            — default 587
  SMTP_USER            — SMTP login username
  SMTP_PASS            — SMTP login password
  EMAIL_FROM           — From address (default: fantasy-beefs@example.com)
  COMMISSIONER_EMAIL   — override commissioner email for reports
  CURRENT_WEEK         — fallback week number for scheduler auto-detect
  LEAGUE_IDS           — comma-separated league IDs for scheduler (default: 1)

Usage:
  # Manual run for a specific week
  python notifications/tuesday_sync.py --league 1 --week 5

  # Start APScheduler (runs every Tuesday 00:01 UTC)
  python notifications/tuesday_sync.py --schedule

  # Or trigger via API: POST /admin/tuesday-sync {"league_id": 1, "week": 5}
"""

from __future__ import annotations

import json
import os
import smtplib
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import (
    League,
    Matchup,
    Team,
    TuesdaySyncRun,
    User,
    Wallet,
    FaabWallet,
    SessionLocal,
)

# ── Email config ──────────────────────────────────────────────────────────────

MOCK_EMAIL_MODE = not bool(os.getenv("SMTP_HOST", ""))
SMTP_HOST       = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER       = os.getenv("SMTP_USER", "")
SMTP_PASS       = os.getenv("SMTP_PASS", "")
EMAIL_FROM      = os.getenv("EMAIL_FROM", "fantasy-beefs@example.com")
COMMISSIONER_EMAIL_OVERRIDE = os.getenv("COMMISSIONER_EMAIL", "")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    step:        str
    success:     bool
    message:     str
    data:        dict
    error:       Optional[str]
    duration_ms: int

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class TuesdayRunSummary:
    run_id:       str
    league_id:    int
    week:         int
    started_at:   str
    finished_at:  str
    mock_mode:    bool
    steps:        list[StepResult]
    emails_sent:  int
    error_count:  int
    status:       str


# ── Table formatting ──────────────────────────────────────────────────────────

def _col(value: str, width: int) -> str:
    return str(value)[:width].ljust(width)


def _ascii_table(headers: list[str], rows: list[list[str]], widths: list[int]) -> str:
    sep_top  = "┌" + "┬".join("─" * (w + 2) for w in widths) + "┐"
    sep_mid  = "├" + "┼".join("─" * (w + 2) for w in widths) + "┤"
    sep_bot  = "└" + "┴".join("─" * (w + 2) for w in widths) + "┘"

    def _row(cells: list[str]) -> str:
        parts = [f" {_col(c, widths[i])} " for i, c in enumerate(cells)]
        return "│" + "│".join(parts) + "│"

    lines = [sep_top, _row(headers), sep_mid]
    for row in rows:
        lines.append(_row(row))
    lines.append(sep_bot)
    return "\n".join(lines)


def _ok(success: bool) -> str:
    return "OK" if success else "FAILED"


# ── Email transport ───────────────────────────────────────────────────────────

def _send_email(to: str, subject: str, body: str, *, mock_mode: bool = MOCK_EMAIL_MODE) -> bool:
    if not to or "@" not in to:
        return False
    if mock_mode:
        print(f"\n{'='*72}")
        print(f"[MOCK EMAIL] To: {to}")
        print(f"[MOCK EMAIL] Subject: {subject}")
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
        print(f"[EMAIL ERROR] to={to}: {e}")
        return False


def _commissioner_email_address(league_id: int, db: Session) -> str:
    if COMMISSIONER_EMAIL_OVERRIDE:
        return COMMISSIONER_EMAIL_OVERRIDE
    user = db.query(User).filter(User.role == "commissioner").first()
    if user:
        return user.email
    team = db.query(Team).filter(Team.league_id == league_id).first()
    return team.email if team else ""


def _gm_email_address(team_id: int, db: Session) -> str:
    user = db.query(User).filter(User.team_id == team_id).first()
    if user:
        return user.email
    team = db.query(Team).filter(Team.id == team_id).first()
    return team.email if team else ""


# ── Step 1: Settle bets ───────────────────────────────────────────────────────

def _step_settle_bets(league_id: int, week: int, db: Session):
    from betting.settlement_engine import settle_week
    t0 = time.monotonic()
    try:
        report = settle_week(week, db)
        ms     = int((time.monotonic() - t0) * 1000)
        msg    = (f"Settled {report.total_bets} bets: "
                  f"{report.bets_won} won, {report.bets_lost} lost")
        data   = {
            "total_bets":   report.total_bets,
            "bets_won":     report.bets_won,
            "bets_lost":    report.bets_lost,
            "total_staked": round(report.total_staked, 2),
            "total_payout": round(report.total_payout, 2),
            "house_edge":   round(report.house_edge, 2),
        }
        return StepResult("settle_bets", True, msg, data, None, ms), report
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult("settle_bets", False, "settlement failed", {}, str(e), ms), None


# ── Step 2: Execute weekly commissioner rules ─────────────────────────────────

def _step_execute_rules(league_id: int, week: int, db: Session):
    from admin.commissioner_rules import execute_weekly_rules
    t0 = time.monotonic()
    try:
        execs = execute_weekly_rules(league_id, week, db)
        ms    = int((time.monotonic() - t0) * 1000)
        total_collected = round(sum(e.amount for e in execs if e.effect_type == "obligation"), 2)
        total_paid      = round(sum(e.amount for e in execs if e.effect_type == "payout"),     2)
        msg  = (f"{len(execs)} rule execution(s): "
                f"${total_collected:.2f} collected, ${total_paid:.2f} paid out")
        data = {
            "executions":        len(execs),
            "total_collected":   total_collected,
            "total_paid":        total_paid,
        }
        return StepResult("execute_rules", True, msg, data, None, ms), execs
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult("execute_rules", False, "rules execution failed", {}, str(e), ms), []


# ── Step 3: Freeze wallets with zero / negative balance ───────────────────────

def _step_freeze_wallets(league_id: int, db: Session):
    from wallet.faab_wallet import check_and_freeze
    t0 = time.monotonic()
    frozen_teams: list[dict] = []
    try:
        teams = db.query(Team).filter(Team.league_id == league_id).all()
        for team in teams:
            wallet = db.query(Wallet).filter(Wallet.team_id == team.id).first()
            if not wallet:
                continue
            faab_w = db.query(FaabWallet).filter(FaabWallet.team_id == team.id).first()
            if faab_w:
                is_frozen = check_and_freeze(team.id, db)
                if is_frozen:
                    frozen_teams.append({
                        "team_id":   team.id,
                        "team_name": team.team_name,
                        "owner":     team.owner,
                        "balance":   round(wallet.balance, 2),
                        "newly_frozen": bool(faab_w.bet_frozen),
                    })
            elif wallet.balance <= 0:
                # No FAAB system — just flag for alert
                frozen_teams.append({
                    "team_id":   team.id,
                    "team_name": team.team_name,
                    "owner":     team.owner,
                    "balance":   round(wallet.balance, 2),
                    "newly_frozen": False,
                })

        ms  = int((time.monotonic() - t0) * 1000)
        msg = (f"Checked {len(teams)} wallets — "
               f"{len(frozen_teams)} frozen or low-balance")
        data = {
            "teams_checked": len(teams),
            "frozen_count":  len(frozen_teams),
        }
        return StepResult("freeze_wallets", True, msg, data, None, ms), frozen_teams
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult("freeze_wallets", False, "freeze check failed", {}, str(e), ms), []


# ── Step 4: Apply pending waiver top-ups ─────────────────────────────────────

def _step_apply_topups(db: Session):
    from wallet.faab_wallet import apply_pending_topups
    t0 = time.monotonic()
    try:
        applied = apply_pending_topups(db)
        ms  = int((time.monotonic() - t0) * 1000)
        total = round(sum(t.amount for t in applied), 2)
        msg  = f"Applied {len(applied)} waiver top-up(s) totalling ${total:.2f}"
        data = {"applied_count": len(applied), "total_applied": total}
        return StepResult("apply_topups", True, msg, data, None, ms), applied
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult("apply_topups", False, "top-up apply failed", {}, str(e), ms), []


# ── Step 5: Build FAAB sync report ───────────────────────────────────────────

def _step_build_faab_report(league_id: int, db: Session):
    from wallet.faab_wallet import get_league_faab
    t0 = time.monotonic()
    try:
        states = get_league_faab(league_id, db)
        ms = int((time.monotonic() - t0) * 1000)
        faab_rows = [
            {
                "team_id":              s.team_id,
                "team_name":            s.team_name,
                "owner":                s.owner,
                "waiver_balance":       round(s.waiver_balance, 2),
                "pending_waiver_topup": round(s.pending_waiver_topup, 2),
                "bet_balance":          round(s.bet_balance, 2),
                "bet_frozen":           s.bet_frozen,
            }
            for s in states
        ]
        faab_rows.sort(key=lambda r: r["waiver_balance"], reverse=True)
        msg  = f"FAAB report built for {len(faab_rows)} team(s)"
        data = {"teams": len(faab_rows)}
        return StepResult("faab_report", True, msg, data, None, ms), faab_rows
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult("faab_report", False, "FAAB report failed", {}, str(e), ms), []


# ── Step 7: Weekly wrap-up (AI-generated) ────────────────────────────────────

def _step_weekly_wrapup(
    league_id: int,
    week:      int,
    db:        Session,
    *,
    mock_mode: bool,
) -> tuple[StepResult, int]:
    """Generate AI Wrap-Up + Roast Beef and email all GMs. Returns (StepResult, emails_sent)."""
    from reports.weekly_wrap import generate_weekly_wrap
    t0 = time.monotonic()
    try:
        out  = generate_weekly_wrap(league_id, week, db, mock_mode=mock_mode)
        ms   = int((time.monotonic() - t0) * 1000)
        msg  = (f"Wrap-Up generated (model: {out.ai_model_used}) — "
                f"{out.gm_count} GM emails sent")
        return (StepResult(
            "weekly_wrapup", True, msg,
            {"wrap_up_id": out.wrap_up_id, "model": out.ai_model_used,
             "gm_count": out.gm_count},
            None, ms,
        ), out.gm_count)
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return (StepResult(
            "weekly_wrapup", False, "wrap-up generation failed", {}, str(e), ms,
        ), 0)


# ── Email builders ────────────────────────────────────────────────────────────

def _build_commissioner_report(
    league_id:    int,
    week:         int,
    run_id:       str,
    mock_mode:    bool,
    steps:        list[StepResult],
    settlement,              # SettlementReport | None
    rule_execs:   list,
    frozen_teams: list[dict],
    applied_topups: list,
    faab_rows:    list[dict],
    started_at:   datetime,
    db:           Session,
) -> str:
    league = db.query(League).filter(League.id == league_id).first()
    league_name = league.name if league else f"League {league_id}"
    ts = started_at.strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = []
    w = 68

    def section(title: str) -> None:
        lines.append("")
        lines.append(title)
        lines.append("=" * w)

    lines.append(f"{league_name} — Tuesday Sync Report")
    lines.append(f"Week {week}  |  {ts}  |  Run: {run_id}")
    lines.append("MOCK MODE" if mock_mode else "LIVE MODE")

    # Step results overview
    section("EXECUTION SUMMARY")
    step_ok    = sum(1 for s in steps if s.success)
    step_fail  = sum(1 for s in steps if not s.success)
    lines.append(f"  {step_ok}/{len(steps)} steps succeeded   "
                 f"{'CLEAN RUN' if step_fail == 0 else f'{step_fail} STEP(S) FAILED'}")
    for s in steps:
        icon = "OK " if s.success else "ERR"
        lines.append(f"  [{icon}] {s.step:<22} {s.message}")
        if not s.success and s.error:
            lines.append(f"         Error: {s.error}")

    # Step 1 — Settlement detail
    section("STEP 1: BET SETTLEMENT")
    if settlement:
        d = next((s.data for s in steps if s.step == "settle_bets"), {})
        lines.append(f"  Bets: {d.get('total_bets',0)} total  |  "
                     f"{d.get('bets_won',0)} won  |  {d.get('bets_lost',0)} lost")
        lines.append(f"  Staked: ${d.get('total_staked',0):.2f}  |  "
                     f"Paid out: ${d.get('total_payout',0):.2f}  |  "
                     f"House edge: ${d.get('house_edge',0):.2f}")
        if settlement.wallet_movements:
            lines.append("")
            rows = [
                [mv.team_name[:26], f"${mv.balance_before:>9,.2f}",
                 f"${mv.balance_after:>9,.2f}", f"{mv.net:>+10.2f}"]
                for mv in sorted(settlement.wallet_movements, key=lambda m: -m.net)
            ]
            lines.append(_ascii_table(
                ["Team", "Before", "After", "Net P&L"],
                rows, [26, 11, 11, 12],
            ))
    else:
        lines.append("  (settlement step failed or no pending bets)")

    # Step 2 — Rules detail
    section("STEP 2: COMMISSIONER RULES")
    if rule_execs:
        for e in rule_execs:
            icon = "debit " if e.effect_type == "obligation" else "credit"
            lines.append(f"  [{icon}] {e.team_name[:26]:<26}  ${e.amount:.2f}  "
                         f"[{e.status}]  {e.description[:50]}")
    else:
        lines.append("  No rules executed this week.")

    # Step 3 — Frozen wallets
    section("STEP 3: WALLET FREEZE CHECK")
    if frozen_teams:
        lines.append(f"  *** {len(frozen_teams)} TEAM(S) FROZEN — FOLLOW UP REQUIRED ***")
        lines.append("")
        for t in frozen_teams:
            lines.append(f"  - {t['team_name']:<28} ({t['owner']})  "
                         f"balance: ${t['balance']:.2f}  BETTING FROZEN")
    else:
        lines.append("  All wallets funded — no freezes.")

    # Step 4 — Waiver top-ups
    section("STEP 4: WAIVER TOP-UPS APPLIED")
    if applied_topups:
        for tx in applied_topups:
            team = db.query(Team).filter(Team.id == tx.team_id).first()
            tname = team.team_name if team else f"team_{tx.team_id}"
            lines.append(f"  + {tname:<28}  +${tx.amount:.2f} waiver")
    else:
        lines.append("  No pending top-ups were due.")

    # Step 5 — FAAB sync table
    section("STEP 5: FAAB WAIVER BUDGETS — ENTER IN YAHOO")
    if faab_rows:
        lines.append("  Yahoo Fantasy: League Settings > Waiver Wire > FAAB Balances")
        lines.append("")
        rows = [
            [r["team_name"][:26], r["owner"][:22],
             f"${r['waiver_balance']:>7.2f}",
             f"+${r['pending_waiver_topup']:>6.2f}" if r["pending_waiver_topup"] else "  --  "]
            for r in faab_rows
        ]
        lines.append(_ascii_table(
            ["Team", "Owner", "Waiver $", "Pending"],
            rows, [26, 22, 9, 8],
        ))
    else:
        lines.append("  FAAB not initialized for this league.")

    # Step 7 — Wrap-up note (generated after this report sends)
    section("STEP 7: WEEKLY WRAP-UP")
    lines.append("  AI Wrap-Up + Roast Beef generating now — GM emails will follow separately.")

    lines.append("")
    return "\n".join(lines)


def _build_gm_email(
    team_id:    int,
    week:       int,
    settlement, # SettlementReport | None
    rule_execs: list,
    faab_rows:  list[dict],
    db:         Session,
) -> str:
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        return ""
    owner = team.owner.split()[0] if team.owner else "GM"

    lines: list[str] = []
    lines.append(f"Hey {owner},")
    lines.append("")
    lines.append(f"Here's your Fantasy Beefs recap for Week {week}.")
    lines.append("")

    # Bets section
    lines.append("─── YOUR BETS ───────────────────────────────────────────────────")
    if settlement:
        mv = next((m for m in settlement.wallet_movements
                   if m.team_name == team.team_name), None)
        if mv:
            lines.append(f"  Won: {mv.bets_won}  |  Lost: {mv.bets_lost}  |  "
                         f"Net: ${mv.net:+.2f}")
            lines.append(f"  Staked: ${mv.total_staked:.2f}  →  "
                         f"Returned: ${mv.total_payout:.2f}")
            lines.append(f"  Bet wallet after settlement: ${mv.balance_after:,.2f}")
        else:
            lines.append("  No bets placed this week.")
    else:
        lines.append("  (settlement data unavailable)")

    # Rules applied to this team
    my_rules = [e for e in rule_execs if e.team_id == team_id]
    lines.append("")
    lines.append("─── COMMISSIONER RULES APPLIED TO YOU ──────────────────────────")
    if my_rules:
        for e in my_rules:
            sign = "-" if e.effect_type == "obligation" else "+"
            lines.append(f"  {sign}${e.amount:.2f}  {e.description[:60]}")
            lines.append(f"           Status: {e.status}")
    else:
        lines.append("  No rules applied to you this week.")

    # Wallet state
    faab = next((r for r in faab_rows if r["team_id"] == team_id), None)
    wallet = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    lines.append("")
    lines.append("─── YOUR WALLETS ────────────────────────────────────────────────")
    if wallet:
        frozen_tag = "  *** FROZEN — TOP UP TO RESUME BETTING ***" if (faab and faab["bet_frozen"]) else ""
        lines.append(f"  Bet wallet:     ${wallet.balance:>9,.2f}{frozen_tag}")
    if faab:
        pending_tag = (f"  (+${faab['pending_waiver_topup']:.2f} pending)"
                       if faab["pending_waiver_topup"] > 0 else "")
        lines.append(f"  Waiver budget:  ${faab['waiver_balance']:>9,.2f}{pending_tag}")

    lines.append("")
    lines.append("─── COMING UP: WEEK " + str(week + 1) + " ─────────────────────────────────────")
    lines.append("  Matchups are live — go place your bets!")
    lines.append("")
    lines.append("—")
    lines.append("Fantasy Beefs Platform")
    return "\n".join(lines)


# ── Step 6: Email commissioner ────────────────────────────────────────────────

def _step_email_commissioner(
    league_id:    int,
    week:         int,
    run_id:       str,
    mock_mode:    bool,
    steps_so_far: list[StepResult],
    settlement,
    rule_execs:   list,
    frozen_teams: list[dict],
    applied_topups: list,
    faab_rows:    list[dict],
    started_at:   datetime,
    db:           Session,
) -> StepResult:
    t0 = time.monotonic()
    try:
        body    = _build_commissioner_report(
            league_id, week, run_id, mock_mode, steps_so_far,
            settlement, rule_execs, frozen_teams, applied_topups, faab_rows,
            started_at, db,
        )
        errors  = sum(1 for s in steps_so_far if not s.success)
        frozen  = len(frozen_teams)
        emoji   = "OK" if (errors == 0 and frozen == 0) else "!!"
        subject = (f"[Fantasy Beefs] [{emoji}] Tuesday Sync — Week {week} "
                   f"({'ERRORS' if errors else ''}"
                   f"{' + ' if errors and frozen else ''}"
                   f"{'FROZEN WALLETS' if frozen else ''}"
                   f"{'CLEAN' if not errors and not frozen else ''})")
        to      = _commissioner_email_address(league_id, db)
        ok      = _send_email(to, subject, body, mock_mode=mock_mode)
        ms      = int((time.monotonic() - t0) * 1000)
        return StepResult(
            "email_commissioner", ok,
            f"Report emailed to {to}" if ok else f"Email failed to {to}",
            {"to": to, "subject": subject}, None if ok else "email send failed", ms,
        )
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult("email_commissioner", False, "commissioner email failed",
                          {}, str(e), ms)


# ── Step 8: Power Rankings ───────────────────────────────────────────────────

def _step_power_rankings(league_id: int, week: int, db: Session) -> StepResult:
    """Compute power rankings and post to feed. Read-only for email purposes."""
    from reports.power_rankings import compute_power_rankings
    t0 = time.monotonic()
    try:
        rankings = compute_power_rankings(league_id, week, db)
        ms       = int((time.monotonic() - t0) * 1000)
        leader   = rankings[0].team_name if rankings else "?"
        last_pl  = rankings[-1].team_name if rankings else "?"
        msg      = f"{len(rankings)} teams ranked — leader: {leader} | last: {last_pl}"
        return StepResult(
            "power_rankings", True, msg,
            {"leader": leader, "last": last_pl, "teams": len(rankings)},
            None, ms,
        )
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult("power_rankings", False, "power rankings failed", {}, str(e), ms)


# ── Step 9: Email all GMs ─────────────────────────────────────────────────────

def _step_email_gms(
    league_id:  int,
    week:       int,
    settlement,
    rule_execs: list,
    faab_rows:  list[dict],
    db:         Session,
    *,
    mock_mode:  bool,
) -> tuple[StepResult, int]:
    t0 = time.monotonic()
    sent  = 0
    errors: list[str] = []
    try:
        teams = db.query(Team).filter(Team.league_id == league_id).all()
        for team in teams:
            body = _build_gm_email(team.id, week, settlement, rule_execs, faab_rows, db)
            if not body:
                continue
            subject = f"[Fantasy Beefs] Week {week} Summary — {team.team_name}"
            to      = _gm_email_address(team.id, db)
            ok      = _send_email(to, subject, body, mock_mode=mock_mode)
            if ok:
                sent += 1
            else:
                errors.append(f"team {team.id}")

        ms  = int((time.monotonic() - t0) * 1000)
        msg = f"Sent {sent}/{len(teams)} GM emails"
        if errors:
            msg += f" (failed: {', '.join(errors)})"
        return (
            StepResult("email_gms", len(errors) == 0, msg,
                       {"sent": sent, "failed": len(errors)},
                       "; ".join(errors) if errors else None, ms),
            sent,
        )
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return (StepResult("email_gms", False, "GM email step failed",
                           {}, str(e), ms), sent)


# ── Persistence ───────────────────────────────────────────────────────────────

def _save_run(
    run_id:      str,
    league_id:   int,
    week:        int,
    status:      str,
    started_at:  datetime,
    finished_at: datetime,
    steps:       list[StepResult],
    error_count: int,
    emails_sent: int,
    mock_mode:   bool,
    db:          Session,
) -> None:
    try:
        run = TuesdaySyncRun(
            run_id      = run_id,
            league_id   = league_id,
            week        = week,
            status      = status,
            mock_mode   = int(mock_mode),
            steps_json  = json.dumps([s.as_dict() for s in steps]),
            error_count = error_count,
            emails_sent = emails_sent,
            started_at  = started_at,
            finished_at = finished_at,
        )
        db.add(run)
        db.commit()
    except Exception as e:
        print(f"[TuesdaySync] WARNING: could not save run record: {e}")


# ── Main orchestrator ─────────────────────────────────────────────────────────

def run_tuesday_sync(
    league_id: int,
    week:      int,
    db:        Session,
    *,
    mock_mode: bool = MOCK_EMAIL_MODE,
) -> TuesdayRunSummary:
    """
    Run the full Tuesday sync for the given league and week.
    Each step is isolated — failures are logged and the run continues.
    """
    if not 1 <= week <= 17:
        raise ValueError(f"week must be 1–17, got {week}")

    run_id     = uuid.uuid4().hex[:8]
    started_at = datetime.now(timezone.utc)
    steps: list[StepResult] = []

    # Accumulated data to pass between steps
    settlement   = None
    rule_execs   = []
    frozen_teams = []
    applied_topups = []
    faab_rows    = []

    print(f"[TuesdaySync] Starting run {run_id}  league={league_id}  week={week}  "
          f"mock_email={'yes' if mock_mode else 'no'}")

    # Step 1
    r, settlement = _step_settle_bets(league_id, week, db)
    steps.append(r)
    print(f"  [1] settle_bets     — {'OK' if r.success else 'FAILED'}: {r.message}")

    # Step 2
    r, rule_execs = _step_execute_rules(league_id, week, db)
    steps.append(r)
    print(f"  [2] execute_rules   — {'OK' if r.success else 'FAILED'}: {r.message}")

    # Step 3
    r, frozen_teams = _step_freeze_wallets(league_id, db)
    steps.append(r)
    print(f"  [3] freeze_wallets  — {'OK' if r.success else 'FAILED'}: {r.message}")

    # Step 4
    r, applied_topups = _step_apply_topups(db)
    steps.append(r)
    print(f"  [4] apply_topups    — {'OK' if r.success else 'FAILED'}: {r.message}")

    # Step 5
    r, faab_rows = _step_build_faab_report(league_id, db)
    steps.append(r)
    print(f"  [5] faab_report     — {'OK' if r.success else 'FAILED'}: {r.message}")

    # Step 6
    r = _step_email_commissioner(
        league_id, week, run_id, mock_mode,
        steps, settlement, rule_execs, frozen_teams, applied_topups,
        faab_rows, started_at, db,
    )
    steps.append(r)
    emails_sent = 1 if r.success else 0
    print(f"  [6] email_comm      — {'OK' if r.success else 'FAILED'}: {r.message}")

    # Step 7 — AI Wrap-Up + Roast Beef
    r, n_wrap = _step_weekly_wrapup(league_id, week, db, mock_mode=mock_mode)
    steps.append(r)
    emails_sent += n_wrap
    print(f"  [7] weekly_wrapup   — {'OK' if r.success else 'FAILED'}: {r.message}")

    # Step 8 — Power Rankings
    r = _step_power_rankings(league_id, week, db)
    steps.append(r)
    print(f"  [8] power_rankings  — {'OK' if r.success else 'FAILED'}: {r.message}")

    # Step 9 — Email GMs
    r, n_gm = _step_email_gms(
        league_id, week, settlement, rule_execs, faab_rows, db,
        mock_mode=mock_mode,
    )
    steps.append(r)
    emails_sent += n_gm
    print(f"  [9] email_gms       — {'OK' if r.success else 'FAILED'}: {r.message}")

    # Finalise
    finished_at  = datetime.now(timezone.utc)
    error_count  = sum(1 for s in steps if not s.success)
    status       = "completed" if error_count == 0 else "completed_with_errors"
    duration_s   = round((finished_at - started_at).total_seconds(), 1)

    print(f"[TuesdaySync] Finished run {run_id} — {status}  "
          f"errors={error_count}  emails={emails_sent}  {duration_s}s")

    _save_run(run_id, league_id, week, status, started_at, finished_at,
              steps, error_count, emails_sent, mock_mode, db)

    return TuesdayRunSummary(
        run_id      = run_id,
        league_id   = league_id,
        week        = week,
        started_at  = started_at.isoformat(),
        finished_at = finished_at.isoformat(),
        mock_mode   = mock_mode,
        steps       = steps,
        emails_sent = emails_sent,
        error_count = error_count,
        status      = status,
    )


# ── Week auto-detection ───────────────────────────────────────────────────────

def _determine_week(league_id: int, db: Session) -> Optional[int]:
    """
    Auto-detect which week to process.
    Priority: CURRENT_WEEK env var → lowest week with pending bets → None (skip).
    """
    env = os.getenv("CURRENT_WEEK", "")
    if env.isdigit():
        return int(env)
    from db.schema import Bet, Matchup
    pending = db.query(Bet).filter(Bet.status == "pending").limit(1).first()
    if pending:
        m = db.query(Matchup).filter(Matchup.id == pending.matchup_id).first()
        if m:
            return m.week
    return None


# ── APScheduler setup ─────────────────────────────────────────────────────────

def setup_scheduler(
    league_ids: list[int],
    *,
    week_override: Optional[int] = None,
    mock_mode:     bool = MOCK_EMAIL_MODE,
):
    """
    Return a configured BlockingScheduler that fires every Tuesday at 00:01 UTC.
    Requires: pip install apscheduler
    """
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron       import CronTrigger
    except ImportError:
        raise RuntimeError(
            "APScheduler not installed. Run: pip install apscheduler"
        )

    def _job():
        with SessionLocal() as db:
            for lid in league_ids:
                week = week_override or _determine_week(lid, db)
                if week is None:
                    print(f"[TuesdaySync] No pending work for league {lid} — skipping")
                    continue
                try:
                    run_tuesday_sync(lid, week, db, mock_mode=mock_mode)
                except Exception as e:
                    print(f"[TuesdaySync] ERROR league {lid} week {week}: {e}")

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(_job, CronTrigger(day_of_week="tue", hour=0, minute=1))
    print(f"[TuesdaySync] Scheduler configured — fires every Tuesday 00:01 UTC")
    print(f"  Leagues: {league_ids}  mock_email={'yes' if mock_mode else 'no'}")
    return scheduler


def get_run_history(league_id: int, db: Session, *, limit: int = 20) -> list[dict]:
    runs = (
        db.query(TuesdaySyncRun)
        .filter(TuesdaySyncRun.league_id == league_id)
        .order_by(TuesdaySyncRun.started_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "run_id":      r.run_id,
            "week":        r.week,
            "status":      r.status,
            "mock_mode":   bool(r.mock_mode),
            "error_count": r.error_count,
            "emails_sent": r.emails_sent,
            "started_at":  r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "duration_s":  round(
                (r.finished_at - r.started_at).total_seconds(), 1
            ) if (r.finished_at and r.started_at) else None,
        }
        for r in runs
    ]


def get_run_detail(run_id: str, db: Session) -> Optional[dict]:
    r = db.query(TuesdaySyncRun).filter(TuesdaySyncRun.run_id == run_id).first()
    if not r:
        return None
    return {
        "run_id":      r.run_id,
        "league_id":   r.league_id,
        "week":        r.week,
        "status":      r.status,
        "mock_mode":   bool(r.mock_mode),
        "error_count": r.error_count,
        "emails_sent": r.emails_sent,
        "started_at":  r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "steps":       json.loads(r.steps_json) if r.steps_json else [],
    }


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    parser = argparse.ArgumentParser(description="Fantasy Beefs Tuesday Automation")
    parser.add_argument("--league",   type=int, default=1,   help="League ID")
    parser.add_argument("--week",     type=int, default=None, help="Week number (1-17)")
    parser.add_argument("--schedule", action="store_true",    help="Start APScheduler")
    parser.add_argument("--mock",     action="store_true",    default=MOCK_EMAIL_MODE,
                        help="Mock email (default: True when SMTP_HOST not set)")
    args = parser.parse_args()

    if args.schedule:
        leagues = [int(x) for x in os.getenv("LEAGUE_IDS", str(args.league)).split(",")]
        sched   = setup_scheduler(leagues, week_override=args.week, mock_mode=args.mock)
        sched.start()
    else:
        with SessionLocal() as db:
            week = args.week
            if week is None:
                week = _determine_week(args.league, db)
            if week is None:
                print("No pending bets found and CURRENT_WEEK not set. Pass --week N.")
                sys.exit(1)
            summary = run_tuesday_sync(
                args.league, week, db, mock_mode=args.mock
            )
            print(f"\nRun complete: {summary.status}  "
                  f"errors={summary.error_count}  emails={summary.emails_sent}")
