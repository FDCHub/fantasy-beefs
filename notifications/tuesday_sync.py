"""
Tuesday Automation — master job at 12:01am UTC every Tuesday.

Execution order (each step is isolated — one failure never kills the run):
  0. refresh_scores    — pull live Yahoo scoreboard; upsert matchup scores (GATE source)
  1. settle_bets       — settle_week() for the completed week
  2. execute_rules     — execute_weekly_rules() for all active commissioner rules
  3. freeze_wallets    — check every team's bet wallet; freeze any <= $0
  4. apply_topups      — apply_pending_topups() for due waiver top-ups
  5. faab_report       — build waiver-budget table for Yahoo FAAB entry
  6. email_commissioner — send sync report + frozen wallet alerts to commissioner
  7. weekly_wrapup     — AI weekly wrap-up + Roast Beef, emails all GMs
  8. power_rankings    — compute & publish updated power rankings to feed
  9. email_gms         — send personal week summary to every GM

Environment variables (Yahoo OAuth — required on Railway where secrets/ is absent):
  YAHOO_PRIVATE_JSON   — full JSON string from secrets/private.json
  YAHOO_CONSUMER_SECRET — consumer_secret value from secrets/yahoo_oauth.json
  YAHOO_LEAGUE_ID      — Yahoo league ID string (default: 488800)

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


@dataclass
class RefreshResult:
    """
    Result from _step_refresh_scores.  Consumed by the settlement gate in
    run_tuesday_sync (STEP D).

    settleable is True ONLY when:
      - Yahoo returned a list (not None, not an exception)
      - Every matchup has status == "final"
      - Every team ID resolved through TeamResolver
      - The upsert committed without error

    Every other path sets settleable=False and populates reason with a
    human-readable explanation for logging and the commissioner alert.
    """
    settleable: bool
    week:       int
    reason:     str


# ── Table formatting ──────────────────────────────────────────────────────────

def _col(value: str, width: int) -> str:
    return str(value)[:width].ljust(width)


def _ascii_table(headers: list[str], rows: list[list[str]], widths: list[int]) -> str:
    sep_top  = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    sep_mid  = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    sep_bot  = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def _row(cells: list[str]) -> str:
        parts = [f" {_col(c, widths[i])} " for i, c in enumerate(cells)]
        return "|" + "|".join(parts) + "|"

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


# ── Slate freshness gate ───────────────────────────────────────────────────────

def _assert_slate_fresh(
    league_id: int,
    week: int,
    db: Session,
    *,
    yahoo_home_ids: set[int] | None = None,
    check_refreshed: bool = False,
) -> tuple[bool, str, int]:
    """
    Single source of truth for "is the matchup slate complete and refreshed?"

    Returns (is_fresh, reason, db_count).

    Always checks:
      - db_count > 0  (seed must have run)

    When yahoo_home_ids is provided (step 0 / _step_refresh_scores):
      - Checks exact set identity between DB home_team_ids and Yahoo's translated
        return, in both directions:
          missing = db_home_ids - yahoo_home_ids  (DB game Yahoo dropped)
          extra   = yahoo_home_ids - db_home_ids  (game Yahoo invented)
        Either non-empty set fails the gate.  Count equality alone does not
        pass — a duplicate plus a missing game has identical counts but fires
        both sets.
      - yahoo_home_ids contains DB IDs (after TeamResolver translation), so the
        comparison is in the same namespace as the DB query.

    When check_refreshed=True (step 1 self-guard / _step_settle_bets):
      - Checks that all matchup rows have refreshed_at IS NOT NULL.
      - NULL means _step_refresh_scores did not complete for that row.
      - Requires migration: migrations/add_matchup_refreshed_at.py.
      - Score values (0.0, etc.) are never used to infer freshness — only the
        timestamp is authoritative.  A genuine 0-0 final with a non-NULL
        refreshed_at is correctly treated as fresh.
    """
    from sqlalchemy import text

    rows = db.execute(
        text(
            "SELECT home_team_id, refreshed_at FROM matchups "
            "WHERE league_id = :lid AND week = :week"
        ),
        {"lid": league_id, "week": week},
    ).fetchall()

    db_count = len(rows)

    if db_count == 0:
        return (
            False,
            f"week {week}: no matchups in DB for league_id={league_id} — seed not run?",
            0,
        )

    if yahoo_home_ids is not None:
        db_home_ids = {row[0] for row in rows}
        missing     = db_home_ids - yahoo_home_ids  # DB games Yahoo dropped
        extra       = yahoo_home_ids - db_home_ids  # games Yahoo invented
        if missing or extra:
            parts: list[str] = []
            if missing:
                parts.append(f"missing from Yahoo: {sorted(missing)}")
            if extra:
                parts.append(f"invented by Yahoo (not in DB): {sorted(extra)}")
            return (
                False,
                f"week {week}: slate mismatch — {'; '.join(parts)}",
                db_count,
            )

    if check_refreshed:
        unrefreshed = [row[0] for row in rows if row[1] is None]
        if unrefreshed:
            return (
                False,
                (f"week {week}: {len(unrefreshed)} matchup(s) have NULL refreshed_at — "
                 f"refresh did not complete "
                 f"(home_team_ids: {sorted(unrefreshed)})"),
                db_count,
            )

    return (True, f"week {week}: {db_count} matchup(s) — slate complete and fresh",
            db_count)


# ── Step 0: Refresh matchup scores from Yahoo ────────────────────────────────

def _build_yahoo_query(yahoo_league_id: str):
    """
    Build an authenticated yfpy YahooFantasySportsQuery.

    Credential loading (in priority order):
      1. YAHOO_PRIVATE_JSON env var (full JSON string) + YAHOO_CONSUMER_SECRET
         env var — the expected path on Railway where secrets/ is not deployed.
      2. secrets/private.json + secrets/yahoo_oauth.json — local dev fallback.

    yfpy gotchas preserved:
      - game_id=461 passed into the constructor (not just game_code).
      - consumer_secret merged into the token dict before the constructor call.
    """
    from yfpy.query import YahooFantasySportsQuery

    private_env = os.getenv("YAHOO_PRIVATE_JSON", "")
    secret_env  = os.getenv("YAHOO_CONSUMER_SECRET", "")

    if private_env and secret_env:
        token = json.loads(private_env)
        token["consumer_secret"] = secret_env
    else:
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, "secrets", "private.json")) as f:
            token = json.load(f)
        with open(os.path.join(root, "secrets", "yahoo_oauth.json")) as f:
            creds = json.load(f)
        token["consumer_secret"] = creds["consumer_secret"]

    return YahooFantasySportsQuery(
        league_id=yahoo_league_id,
        game_code="nfl",
        game_id=461,
        yahoo_access_token_json=token,
        browser_callback=False,
    )


def _step_refresh_scores(
    league_id: int,
    week: int,
    db: Session,
) -> tuple[StepResult, RefreshResult]:
    """
    Step 0 — pull the live Yahoo scoreboard for the given week and upsert
    matchup scores into the matchups table.

    Returns (StepResult, RefreshResult).  RefreshResult.settleable is True only
    when all matchups are final, the Yahoo return covers the full DB slate with
    set-exact identity (not just count equality), every team ID resolved, and
    the upsert committed — including refreshed_at = NOW() on every row.

    Translation precedes the slate check because set containment requires
    DB IDs, and those only exist after the TeamResolver runs.
    """
    from db.team_resolver import build_team_resolver, TeamResolverError
    from sqlalchemy import text
    from yahoo_scoreboard import fetch_week_scoreboard

    yahoo_league_id = os.getenv("YAHOO_LEAGUE_ID", "488800")
    t0 = time.monotonic()

    def _not_fresh(
        reason: str, error: str | None = None
    ) -> tuple[StepResult, RefreshResult]:
        ms = int((time.monotonic() - t0) * 1000)
        return (
            StepResult("refresh_scores", False, reason, {"settleable": False}, error, ms),
            RefreshResult(settleable=False, week=week, reason=reason),
        )

    # ── Build team resolver (one DB round-trip) ───────────────────────────────
    try:
        resolver = build_team_resolver(db, league_id)
    except TeamResolverError as exc:
        return _not_fresh(f"week {week}: team resolver failed — {exc}", str(exc))
    except Exception as exc:
        return _not_fresh(f"week {week}: unexpected resolver error — {exc}", str(exc))

    # ── Fetch live scoreboard from Yahoo ─────────────────────────────────────
    try:
        query      = _build_yahoo_query(yahoo_league_id)
        scoreboard = fetch_week_scoreboard(query, week)
    except Exception as exc:
        return _not_fresh(
            f"week {week}: Yahoo fetch failed — {type(exc).__name__}: {exc}",
            str(exc),
        )

    if scoreboard is None:
        return _not_fresh(f"week {week}: season-over anomaly — Yahoo returned None")

    # ── All returned matchups must be final ───────────────────────────────────
    # Early exit before translation — status check is cheap.
    not_final = [m for m in scoreboard if m["status"] != "final"]
    if not_final:
        pairs    = [(m["home_team_id"], m["away_team_id"]) for m in not_final]
        statuses = [m["status"] for m in not_final]
        return _not_fresh(
            f"week {week} not settled: matchup(s) {pairs} not final (statuses: {statuses})"
        )

    # ── Translate Yahoo IDs → DB IDs (all-or-nothing) ────────────────────────
    # Translation must precede the slate check — set containment compares
    # DB home_team_id values, which only exist after resolver runs.
    translated: list[dict] = []
    unresolved: list[str]  = []

    for m in scoreboard:
        try:
            db_home   = resolver.yahoo_to_db(m["home_team_id"])
            db_away   = resolver.yahoo_to_db(m["away_team_id"])
            db_winner = (
                resolver.yahoo_to_db(m["winner_team_id"])
                if m["winner_team_id"] is not None
                else None
            )
        except TeamResolverError as exc:
            unresolved.append(str(exc))
            continue

        translated.append({
            "league_id":      league_id,
            "week":           week,
            "home_team_id":   db_home,
            "away_team_id":   db_away,
            "home_score":     m["home_score"],
            "away_score":     m["away_score"],
            "winner_team_id": db_winner,
        })

    if unresolved:
        return _not_fresh(
            f"week {week}: unresolved team IDs — {'; '.join(unresolved)}"
        )

    # ── Slate completeness — set containment, not count equality ─────────────
    # Six matchups back / six in DB / gate clears — even if one is a duplicate
    # and one real game is missing.  The missing game keeps its stale score and
    # settles anyway.  Set containment closes this: every DB home_team_id must
    # appear in Yahoo's translated return.
    yahoo_home_ids = {row["home_team_id"] for row in translated}
    slate_ok, slate_reason, _ = _assert_slate_fresh(
        league_id, week, db, yahoo_home_ids=yahoo_home_ids
    )
    if not slate_ok:
        return _not_fresh(slate_reason)

    # ── Upsert all rows in one transaction ───────────────────────────────────
    # refreshed_at = NOW() written on both INSERT and UPDATE.
    # _assert_slate_fresh with check_refreshed=True reads this column in step 1
    # to confirm the refresh completed; NULL = never touched by a live refresh.
    upsert_sql = text("""
        INSERT INTO matchups
            (league_id, week, home_team_id, away_team_id,
             home_score, away_score, winner_team_id, refreshed_at)
        VALUES
            (:league_id, :week, :home_team_id, :away_team_id,
             :home_score, :away_score, :winner_team_id, NOW())
        ON CONFLICT (league_id, week, home_team_id)
        DO UPDATE SET
            home_score     = EXCLUDED.home_score,
            away_score     = EXCLUDED.away_score,
            winner_team_id = EXCLUDED.winner_team_id,
            refreshed_at   = NOW()
    """)
    try:
        for row in translated:
            db.execute(upsert_sql, row)
        db.commit()
    except Exception as exc:
        db.rollback()
        return _not_fresh(
            f"week {week}: upsert failed — {type(exc).__name__}: {exc}",
            str(exc),
        )

    ms  = int((time.monotonic() - t0) * 1000)
    msg = (f"week {week}: {len(translated)} matchup score(s) upserted — "
           f"all final, full slate, all IDs resolved")
    return (
        StepResult(
            "refresh_scores", True, msg,
            {"rows_upserted": len(translated), "settleable": True},
            None, ms,
        ),
        RefreshResult(settleable=True, week=week, reason=msg),
    )


# ── Step 0.25: Sync players from live rosters (FR-7.30) ───────────────────────

def _step_sync_players(
    league_id: int, week: int, db: Session
) -> tuple[StepResult, list | None]:
    """
    Grow the players table from the live Yahoo rosters (FR-7.30).

    The players table is otherwise seeder-only — a mid-season call-up exists on
    no DB row, is invisible everywhere, and (pre-FR-7.30) broke the all-or-
    nothing roster-slot capture indefinitely. This step inserts any rostered
    Yahoo player we don't already have, keyed on the stable Yahoo player_id
    (players.yahoo_id, backfilled in FR-7.30 step 3) — never name matching.

    Insert-only and idempotent: a player already present by yahoo_id is skipped,
    so a re-run inserts nothing. Yahoo team IDs bridge to DB team IDs through
    TeamResolver (never +10 arithmetic).

    Returns (StepResult, rosters) where rosters is the list of fetched Yahoo
    Roster objects, handed forward so the capture step (0.5) can reuse them
    instead of re-fetching. On ANY failure returns (StepResult(success=False),
    None) — the sequence continues and capture falls back to its own fetch.

    position comes from display_position (eligibility), NOT selected_position —
    standing rule. editorial_team_abbr is upper-cased ("Bal" -> "BAL") to match
    the DB column's convention.
    """
    from db.team_resolver import build_team_resolver, TeamResolverError
    from db.schema import Player, Team

    yahoo_league_id = os.getenv("YAHOO_LEAGUE_ID", "488800")
    t0 = time.monotonic()

    def _fail(reason: str, error: str | None = None) -> tuple[StepResult, None]:
        ms = int((time.monotonic() - t0) * 1000)
        return (
            StepResult("sync_players", False, reason, {"inserted": 0}, error, ms),
            None,
        )

    def _s(v) -> str:
        return v.decode() if isinstance(v, bytes) else str(v)

    # ── Resolvers (one DB round-trip each) ────────────────────────────────────
    try:
        resolver = build_team_resolver(db, league_id)
    except TeamResolverError as exc:
        return _fail(f"week {week}: team resolver failed — {exc}", str(exc))
    except Exception as exc:
        return _fail(f"week {week}: unexpected resolver error — {exc}", str(exc))

    teams = db.query(Team).filter(Team.league_id == league_id).all()
    if not teams:
        return _fail(f"week {week}: no teams found for league {league_id}")

    # ── Build the authenticated Yahoo query (existing credential path) ───────
    try:
        query = _build_yahoo_query(yahoo_league_id)
    except Exception as exc:
        return _fail(
            f"week {week}: Yahoo query build failed — {type(exc).__name__}: {exc}",
            str(exc),
        )

    # ── Fetch every team's roster; keep the Roster objects to hand forward ───
    rosters: list = []
    for team in teams:
        try:
            yahoo_id = resolver.db_to_yahoo(team.id)
        except TeamResolverError as exc:
            return _fail(f"week {week}: {exc}", str(exc))
        try:
            roster = query.get_team_roster_by_week(yahoo_id, chosen_week=week)
        except Exception as exc:
            return _fail(
                f"week {week}: Yahoo roster fetch failed for team {team.id} "
                f"(yahoo {yahoo_id}) — {type(exc).__name__}: {exc}",
                str(exc),
            )
        rosters.append(roster)

    # ── Insert players we don't already have (keyed on yahoo_id) ─────────────
    existing = {
        yid: pid
        for pid, yid in db.query(Player.id, Player.yahoo_id)
        .filter(Player.yahoo_id.isnot(None))
        .all()
    }
    seen: set[str] = set()          # dedupe within this run
    new_players: list = []
    inserted_log: list[tuple[str, str, str | None, str]] = []
    for roster in rosters:
        for p in roster.players:
            yid = str(p.player_id)
            if yid in existing or yid in seen:
                continue
            seen.add(yid)
            name      = _s(p.full_name)
            position  = p.display_position                              # eligibility, not slot
            nfl_team  = (p.editorial_team_abbr or "").upper() or None   # "Bal" -> "BAL"
            new_players.append(Player(
                name=name, position=position, nfl_team=nfl_team, yahoo_id=yid,
            ))
            inserted_log.append((name, position, nfl_team, yid))

    # ── Insert-only, single transaction ──────────────────────────────────────
    try:
        db.add_all(new_players)
        db.commit()
    except Exception as exc:
        db.rollback()
        return _fail(
            f"week {week}: players insert failed — {type(exc).__name__}: {exc}",
            str(exc),
        )

    for name, position, nfl_team, yid in inserted_log:
        print(f"    [sync_players] inserted {name} ({position}, {nfl_team}) yahoo_id={yid}")

    ms  = int((time.monotonic() - t0) * 1000)
    msg = (f"week {week}: inserted {len(new_players)} new player(s) across "
           f"{len(teams)} team(s)")
    return (
        StepResult(
            "sync_players", True, msg,
            {"inserted": len(new_players), "teams": len(teams)},
            None, ms,
        ),
        rosters,
    )


# ── Step 0.5: Capture weekly roster slots (FR-5.7) ────────────────────────────

def _step_capture_roster_slots(league_id: int, week: int, db: Session) -> StepResult:
    """
    Snapshot each team's per-week lineup into roster_slots (FR-5.7).

    Insert-only and idempotent. If roster_slots already holds rows for this
    (league_id, week) the step is a no-op success — it never overwrites a
    captured week and never relies on catching per-row IntegrityError.

    A failed capture NEVER blocks settlement: the sequence continues and the
    settlement path falls back to the static Roster table when no slots exist
    for the week. Failure is surfaced loudly in the commissioner email via the
    standard step summary.

    Slot label comes from Yahoo's per-week selected_position.position
    (QB/RB/WR/TE/W/R/T/BN/IR) — the lineup slot, NOT display_position, which is
    eligibility and would erase bench identity. Yahoo team IDs bridge to DB team
    IDs through TeamResolver (never +10 arithmetic); Yahoo players bridge to DB
    players by name (lowercased), the same mapping the projection seed uses.

    Capture is all-or-nothing: if any player on any roster fails to resolve, the
    step writes nothing and fails, so settlement cleanly falls back to Roster
    rather than reading a half-populated week.
    """
    from db.team_resolver import build_team_resolver, TeamResolverError
    from db.schema import Player, RosterSlot, Team

    yahoo_league_id = os.getenv("YAHOO_LEAGUE_ID", "488800")
    t0 = time.monotonic()

    def _fail(reason: str, error: str | None = None) -> StepResult:
        ms = int((time.monotonic() - t0) * 1000)
        return StepResult(
            "capture_roster_slots", False, reason, {"captured": False}, error, ms
        )

    def _s(v) -> str:
        return v.decode() if isinstance(v, bytes) else str(v)

    # ── Idempotency: any rows for this week → no-op success ───────────────────
    existing = (
        db.query(RosterSlot)
        .filter(RosterSlot.league_id == league_id, RosterSlot.week == week)
        .count()
    )
    if existing:
        ms  = int((time.monotonic() - t0) * 1000)
        msg = f"week {week}: already captured ({existing} slot row(s)) — no-op"
        return StepResult(
            "capture_roster_slots", True, msg,
            {"captured": False, "existing_rows": existing, "idempotent_noop": True},
            None, ms,
        )

    # ── Resolvers (one DB round-trip each) ────────────────────────────────────
    try:
        resolver = build_team_resolver(db, league_id)
    except TeamResolverError as exc:
        return _fail(f"week {week}: team resolver failed — {exc}", str(exc))
    except Exception as exc:
        return _fail(f"week {week}: unexpected resolver error — {exc}", str(exc))

    teams = db.query(Team).filter(Team.league_id == league_id).all()
    if not teams:
        return _fail(f"week {week}: no teams found for league {league_id}")

    player_map = {
        name.lower(): pid for pid, name in db.query(Player.id, Player.name).all()
    }

    # ── Build the authenticated Yahoo query (existing credential path) ───────
    try:
        query = _build_yahoo_query(yahoo_league_id)
    except Exception as exc:
        return _fail(
            f"week {week}: Yahoo query build failed — {type(exc).__name__}: {exc}",
            str(exc),
        )

    # ── Fetch + resolve every team's roster before writing anything ──────────
    rows: list[dict] = []
    unresolved: list[str] = []
    for team in teams:
        try:
            yahoo_id = resolver.db_to_yahoo(team.id)
        except TeamResolverError as exc:
            return _fail(f"week {week}: {exc}", str(exc))
        try:
            roster = query.get_team_roster_by_week(yahoo_id, chosen_week=week)
        except Exception as exc:
            return _fail(
                f"week {week}: Yahoo roster fetch failed for team {team.id} "
                f"(yahoo {yahoo_id}) — {type(exc).__name__}: {exc}",
                str(exc),
            )
        for p in roster.players:
            slot = p.selected_position.position  # per-week lineup slot
            name = _s(p.full_name)
            if not slot:
                unresolved.append(f"{name} (team {team.id}: no selected_position)")
                continue
            pid = player_map.get(name.lower())
            if pid is None:
                unresolved.append(f"{name} (team {team.id}: unmatched player)")
                continue
            rows.append({
                "league_id": league_id,
                "team_id":   team.id,
                "player_id": pid,
                "week":      week,
                "slot":      slot,
            })

    if unresolved:
        return _fail(
            f"week {week}: {len(unresolved)} unresolved player(s), nothing written "
            f"— {'; '.join(unresolved[:10])}"
            f"{' …' if len(unresolved) > 10 else ''}",
            f"unresolved players: {unresolved}",
        )

    # ── Insert-only, single transaction ──────────────────────────────────────
    try:
        db.add_all([RosterSlot(**row) for row in rows])
        db.commit()
    except Exception as exc:
        db.rollback()
        return _fail(
            f"week {week}: roster_slots insert failed — {type(exc).__name__}: {exc}",
            str(exc),
        )

    ms  = int((time.monotonic() - t0) * 1000)
    msg = (f"week {week}: captured {len(rows)} roster slot(s) across "
           f"{len(teams)} team(s)")
    return StepResult(
        "capture_roster_slots", True, msg,
        {"captured": True, "rows_written": len(rows), "teams": len(teams)},
        None, ms,
    )


# ── Step 1: Settle bets ───────────────────────────────────────────────────────

def _step_settle_bets(
    league_id: int,
    week: int,
    db: Session,
    *,
    mock_mode: bool = MOCK_EMAIL_MODE,
):
    # DB self-guard — re-derive freshness from the DB before touching any wallet.
    # Reads refreshed_at IS NOT NULL (written by step 0's upsert).
    # This is independent of the gate in run_tuesday_sync and catches direct calls
    # (tests, scripts, future gate bugs) that bypass it.
    fresh_ok, fresh_reason, _ = _assert_slate_fresh(
        league_id, week, db, check_refreshed=True
    )
    if not fresh_ok:
        # The alert itself must never crash the abort path — if the commissioner
        # address is bad or SMTP is down, log and continue to the safe return.
        try:
            _alert_settlement_skipped(league_id, week, fresh_reason, mock_mode, db)
        except Exception as alert_exc:
            import logging
            logging.error(
                "[TuesdaySync] Settlement skip alert failed (guard still active): %s",
                alert_exc,
            )
        return (
            StepResult(
                "settle_bets", False,
                f"ABORTED — DB slate not fresh: {fresh_reason}",
                {"settleable": False, "db_guard_triggered": True, "reason": fresh_reason},
                None, 0,
            ),
            None,
        )

    from betting.settlement_engine import settle_week
    t0 = time.monotonic()
    try:
        report = settle_week(week, db, league_id=league_id)
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


def _alert_settlement_skipped(
    league_id: int,
    week: int,
    reason: str,
    mock_mode: bool,
    db: Session,
) -> None:
    """
    Log at ERROR and fire an immediate out-of-band commissioner alert when
    settlement is skipped because the matchup slate is incomplete or scores
    are not confirmed final.

    Called from two places:
      1. The gate in run_tuesday_sync when refresh_result.settleable is False.
      2. The DB self-guard inside _step_settle_bets if called with a stale slate.

    Both use the confirmed utilities _send_email and _commissioner_email_address.
    This is not the scheduled Tuesday report; it fires immediately.
    """
    import logging
    logging.error(
        "[TuesdaySync] SETTLEMENT SKIPPED week=%d league_id=%d — %s",
        week, league_id, reason,
    )
    to      = _commissioner_email_address(league_id, db)
    subject = f"SETTLEMENT SKIPPED — week {week} — scores not fresh"
    body    = "\n".join([
        "SETTLEMENT SKIPPED — Fantasy Beefs",
        "=" * 50,
        "",
        f"Week:    {week}",
        f"League:  {league_id}",
        f"Reason:  {reason}",
        "",
        "No wallets moved.  No bets settled.",
        "Settlement will run automatically on the next Tuesday sync",
        "once Yahoo returns confirmed final scores for all matchups.",
        "",
        "This is an immediate alert — not the scheduled Tuesday report.",
        "The rest of the Tuesday sync (rules, wallets, FAAB, emails) ran normally.",
    ])
    _send_email(to, subject, body, mock_mode=mock_mode)


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
    *,
    settlement_skip_reason: str | None = None,
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
    elif settlement_skip_reason:
        lines.append(f"  SKIPPED — {settlement_skip_reason}")
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
    *,
    settlement_skip_reason: str | None = None,
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
    lines.append("--- YOUR BETS ---------------------------------------------------")
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
    elif settlement_skip_reason:
        lines.append(f"  SKIPPED — {settlement_skip_reason}")
    else:
        lines.append("  (settlement data unavailable)")

    # Rules applied to this team
    my_rules = [e for e in rule_execs if e.team_id == team_id]
    lines.append("")
    lines.append("--- COMMISSIONER RULES APPLIED TO YOU --------------------------")
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
    lines.append("--- YOUR WALLETS ------------------------------------------------")
    if wallet:
        frozen_tag = "  *** FROZEN — TOP UP TO RESUME BETTING ***" if (faab and faab["bet_frozen"]) else ""
        lines.append(f"  Bet wallet:     ${wallet.balance:>9,.2f}{frozen_tag}")
    if faab:
        pending_tag = (f"  (+${faab['pending_waiver_topup']:.2f} pending)"
                       if faab["pending_waiver_topup"] > 0 else "")
        lines.append(f"  Waiver budget:  ${faab['waiver_balance']:>9,.2f}{pending_tag}")

    lines.append("")
    lines.append("--- COMING UP: WEEK " + str(week + 1) + " -------------------------------------")
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
    *,
    settlement_skip_reason: str | None = None,
) -> StepResult:
    t0 = time.monotonic()
    try:
        body    = _build_commissioner_report(
            league_id, week, run_id, mock_mode, steps_so_far,
            settlement, rule_execs, frozen_teams, applied_topups, faab_rows,
            started_at, db,
            settlement_skip_reason=settlement_skip_reason,
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
    settlement_skip_reason: str | None = None,
) -> tuple[StepResult, int]:
    t0 = time.monotonic()
    sent  = 0
    errors: list[str] = []
    try:
        teams = db.query(Team).filter(Team.league_id == league_id).all()
        for team in teams:
            body = _build_gm_email(
                team.id, week, settlement, rule_execs, faab_rows, db,
                settlement_skip_reason=settlement_skip_reason,
            )
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
    settlement_skip_reason = None
    rule_execs   = []
    frozen_teams = []
    applied_topups = []
    faab_rows    = []

    print(f"[TuesdaySync] Starting run {run_id}  league={league_id}  week={week}  "
          f"mock_email={'yes' if mock_mode else 'no'}")

    # Step 0 — refresh live scores from Yahoo before settlement
    r, refresh_result = _step_refresh_scores(league_id, week, db)
    steps.append(r)
    print(f"  [0] refresh_scores  — {'OK' if r.success else 'FAILED'}: {r.message}")

    # Step 0.25 — grow the players table from live rosters (FR-7.30), and
    # hand the fetched rosters forward so capture doesn't re-fetch.
    r, rosters = _step_sync_players(league_id, week, db)
    steps.append(r)
    print(f"  [0.25] sync_players  — {'OK' if r.success else 'FAILED'}: {r.message}")

    # Step 0.5 — capture this week's roster slots (FR-5.7). Independent of the
    # settlement gate: a failed capture must NOT block settlement — settlement
    # falls back to the static Roster when no slots exist for the week.
    r = _step_capture_roster_slots(league_id, week, db)
    steps.append(r)
    print(f"  [0.5] capture_slots — {'OK' if r.success else 'FAILED'}: {r.message}")

    # Step 1 — GATE: settlement runs only when step 0 confirmed a full, final slate.
    # This is the only step that breaks log-and-continue isolation — skipping
    # settlement on a stale slate is a deliberate hard stop, not a soft failure.
    if not refresh_result.settleable:
        try:
            _alert_settlement_skipped(
                league_id, week, refresh_result.reason, mock_mode, db
            )
        except Exception as alert_exc:
            import logging
            logging.error(
                "[TuesdaySync] Gate alert failed (settlement still skipped): %s",
                alert_exc,
            )
        r = StepResult(
            "settle_bets", False,
            f"SKIPPED — scores not fresh: {refresh_result.reason}",
            {"settleable": False, "skipped": True},
            None, 0,
        )
        settlement = None
        settlement_skip_reason = refresh_result.reason
        steps.append(r)
        print(f"  [1] settle_bets     — SKIPPED: {refresh_result.reason}")
    else:
        r, settlement = _step_settle_bets(league_id, week, db, mock_mode=mock_mode)
        if r.data.get("db_guard_triggered"):
            settlement_skip_reason = r.data.get("reason")
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
        settlement_skip_reason=settlement_skip_reason,
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
        settlement_skip_reason=settlement_skip_reason,
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
