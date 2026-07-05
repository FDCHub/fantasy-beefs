#!/usr/bin/env python3
"""
seed_real_2025_season_LIVE.py  —  LIVE WRITE (step 2 of 2)

DESTRUCTIVE: wipes all rows from the tables seeded by the mock seed, then
reseeds from real 2025 Yahoo data for CULV Appreciation Society
(league_id=488800, game_id=461, season=2025).

REQUIRES --confirm-wipe flag:
    python seed_real_2025_season_LIVE.py --confirm-wipe

REQUIRES DATABASE_URL env var pointing at the real Postgres instance:
    If DATABASE_URL is unset or not a Postgres URL the script aborts — this
    guards against accidentally wiping the local SQLite development file.

Tables wiped (FK-safe deletion order, then reinsertion):
    projections → wallets → rosters → matchups → league_scoring
    → teams → players → leagues
    (Projection and Wallet are included even though not in the 6 named
    tables, because they have FKs into Player and Team respectively and
    would cause FK violations if deleted after their parents.)

Yahoo-pull and normalization logic is ported verbatim from the verified
dry run (seed_real_2025_season.py). Do not modify fetch/normalization
logic here — update the dry run and re-verify there first.
"""

from __future__ import annotations

# ── DATABASE_URL safety gate — MUST come before any db.schema import ──────────
# db/schema.py creates the engine at import time. Checking here first ensures
# we abort before a SQLite engine is created (and then written to by accident).

import os
import sys

_DB_URL_ENV = os.environ.get("DATABASE_URL", "")
if not _DB_URL_ENV or "postgres" not in _DB_URL_ENV.lower():
    print(
        "\n!! ABORT: DATABASE_URL must be a Postgres URL before running this script.\n"
        f"   Current value: {_DB_URL_ENV!r}\n"
        "   This guard prevents accidentally wiping the local SQLite dev file.\n"
        "   Export DATABASE_URL and re-run.\n"
    )
    sys.exit(1)

# ── Remaining imports (db.schema import now safe) ─────────────────────────────

import io
import json
import pathlib
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import inspect as sa_inspect, text
from yfpy.query import YahooFantasySportsQuery

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db.schema import (
    Bet, BeefChallenge, BuyInRecord,
    CommissionerRule, EscrowAccount, EscrowTransaction,
    FaabConfig, FaabTransaction, FaabWallet,
    FeedEvent,
    League, LeagueScoring, LeagueTreasury, Matchup,
    PayoutRecord, Player, PoolBetPick, PoolConfig, PoolPot, PoolPrediction,
    PowerRanking, Projection,
    Roster, RuleAuditLog, RuleExecution,
    SessionLocal, StripeAuditLog, Team, Transaction, TuesdaySyncRun,
    User, Wallet, WeeklyWrapUp, WrapUpGmEdition,
)
from yahoo_scoreboard import fetch_week_scoreboard

# ── Configuration (identical to dry run) ─────────────────────────────────────

LEAGUE_ID   = "488800"
GAME_CODE   = "nfl"
GAME_ID     = 461
SEASON      = 2025
MAX_WEEK    = 18
ROSTER_WEEK = 1   # week-1 snapshot confirmed as canonical (dry-run decision)

_YAHOO_STATUS_MAP: dict[str, Optional[str]] = {
    "":    None,
    "Q":   "questionable",
    "D":   "doubtful",
    "O":   "out",
    "IR":  "ir",
    "NA":  "out",
    "DNR": "out",
}

# Stat IDs corrected from raw dump — see dry run for full audit trail
_STAT_ID_MAP: dict[int, str] = {
    5:  "pass_td_points",   # 5.0 pts
    10: "rush_td_points",   # 6.0 pts
    11: "rec_points",       # 0.5 pts (half-PPR)
    13: "rec_td_points",    # 6.0 pts
    # 43/44 (bonus 100yd) absent from this league's config — confirmed 0.0
}

_SLOT_ORDER = [
    "QB", "RB", "WR", "TE",
    "W/R/T", "FLEX", "W-R-T",   # all mean FLEX slot
    "K", "DEF",
    "BN", "IR",
]


# ── Intermediate dataclasses (ported from dry run) ────────────────────────────

@dataclass
class DryScoringSettings:
    league_name:      str
    season:           int
    scoring_type:     str
    rec_points:       float
    pass_td_points:   float
    rush_td_points:   float
    rec_td_points:    float
    bonus_100yd_rush: float
    bonus_100yd_rec:  float
    flags:            list[str] = field(default_factory=list)

@dataclass
class DryTeam:
    yahoo_team_id: int
    team_name:     str
    owner:         str
    email:         str

@dataclass
class DryPlayer:
    name:     str
    position: str

@dataclass
class DryRosterSlot:
    player:      DryPlayer
    slot:        str
    injury_raw:  str
    injury_norm: Optional[str]

@dataclass
class DryMatchup:
    week:         int
    home_team_id: int
    away_team_id: int
    home_score:   float
    away_score:   float
    winner_id:    Optional[int]

# ── Yahoo helpers (ported verbatim from dry run) ──────────────────────────────

def _s(v) -> str:
    if v is None:
        return ""
    return v.decode() if isinstance(v, bytes) else str(v)


def _build_query() -> YahooFantasySportsQuery:
    with open("secrets/private.json") as f:
        token = json.load(f)
    with open("secrets/yahoo_oauth.json") as f:
        creds = json.load(f)
    token["consumer_secret"] = creds["consumer_secret"]
    return YahooFantasySportsQuery(
        league_id=LEAGUE_ID,
        game_code=GAME_CODE,
        game_id=GAME_ID,
        yahoo_access_token_json=token,
        browser_callback=False,
    )


def _normalize_injury(raw_code: str) -> Optional[str]:
    key = raw_code.upper().strip()
    if key in _YAHOO_STATUS_MAP:
        return _YAHOO_STATUS_MAP[key]
    # Unknown code — do NOT write "UNKNOWN:..." to the DB; fail loudly instead
    raise ValueError(
        f"Unrecognized Yahoo injury code {raw_code!r}. "
        "Add it to _YAHOO_STATUS_MAP before proceeding."
    )


def _owner_name(team) -> str:
    try:
        managers = team.managers
        if managers:
            return _s(managers[0].nickname)
    except Exception:
        pass
    try:
        return _s(team.manager.nickname)
    except Exception:
        return "?"


def _slot_sort_key(slot: DryRosterSlot) -> tuple[int, str]:
    try:
        idx = _SLOT_ORDER.index(slot.slot)
    except ValueError:
        idx = len(_SLOT_ORDER)
    return (idx, slot.player.name)


# ── Yahoo fetch functions (ported verbatim from dry run) ──────────────────────

def _fetch_scoring(query: YahooFantasySportsQuery) -> DryScoringSettings:
    flags: list[str] = []
    league_name = "CULV Appreciation Society"
    scoring: dict[str, float] = {
        "rec_points": 0.5, "pass_td_points": 5.0, "rush_td_points": 6.0,
        "rec_td_points": 6.0, "bonus_100yd_rush": 0.0, "bonus_100yd_rec": 0.0,
    }

    for method_name in ("get_league_info", "get_league_metadata"):
        try:
            result = getattr(query, method_name)()
            name = _s(getattr(result, "name", None))
            if name:
                league_name = name
                break
        except Exception as e:
            flags.append(f"{method_name}() failed: {e}")

    raw_stats: dict[int, float] = {}
    try:
        settings   = query.get_league_settings()
        mods       = getattr(settings, "stat_modifiers", None)
        stats_list = None
        if mods is not None:
            stats_list = getattr(mods, "stats", None)
            if stats_list is None:
                try:
                    iter(mods)
                    stats_list = mods
                except TypeError:
                    pass
        if stats_list is None:
            stats_list = getattr(settings, "stats", None)

        for stat in (stats_list or []):
            try:
                sid   = int(_s(getattr(stat, "stat_id", "")))
                value = float(_s(getattr(stat, "value", "0")))
                raw_stats[sid] = value
            except (ValueError, TypeError):
                continue

        if raw_stats:
            for stat_id, field_name in _STAT_ID_MAP.items():
                if stat_id in raw_stats:
                    scoring[field_name] = raw_stats[stat_id]
                else:
                    flags.append(
                        f"Stat ID {stat_id} ({field_name}) missing from Yahoo "
                        f"stat_modifiers — using default {scoring[field_name]}"
                    )
        else:
            flags.append("No parseable stat_modifiers — all scoring values are defaults")
    except Exception as e:
        flags.append(f"get_league_settings() failed: {e} — all defaults used")

    rec = scoring["rec_points"]
    scoring_type = (
        "standard" if rec == 0.0 else
        "half_ppr" if rec == 0.5 else
        "ppr"      if rec == 1.0 else
        "custom"
    )
    if scoring_type == "custom":
        flags.append(f"rec_points={rec} → scoring_type='custom'")

    return DryScoringSettings(
        league_name=league_name, season=SEASON, scoring_type=scoring_type,
        rec_points=scoring["rec_points"], pass_td_points=scoring["pass_td_points"],
        rush_td_points=scoring["rush_td_points"], rec_td_points=scoring["rec_td_points"],
        bonus_100yd_rush=scoring["bonus_100yd_rush"], bonus_100yd_rec=scoring["bonus_100yd_rec"],
        flags=flags,
    )


def _fetch_teams(query: YahooFantasySportsQuery) -> list[DryTeam]:
    teams_raw = query.get_league_teams()
    result = []
    for t in teams_raw:
        yahoo_id = int(_s(t.team_id))
        result.append(DryTeam(
            yahoo_team_id=yahoo_id,
            team_name=_s(t.name),
            owner=_owner_name(t),
            email=f"yahoo-team-{yahoo_id}@fantasy-beefs.local",
        ))
    return sorted(result, key=lambda t: t.yahoo_team_id)


def _fetch_matchups(query: YahooFantasySportsQuery) -> list[DryMatchup]:
    matchups: list[DryMatchup] = []
    for week in range(1, MAX_WEEK + 1):
        try:
            week_data = fetch_week_scoreboard(query, week)
            if week_data is None:
                print(f"    Week {week:>2}: no matchups — stopping.", flush=True)
                break
            if not week_data:
                print(f"    Week {week:>2}: empty — stopping.", flush=True)
                break

            for m in week_data:
                # winner_team_id is set by Yahoo when final and not tied;
                # fall back to score comparison for ties or if the key is absent.
                winner_id = m["winner_team_id"]
                if winner_id is None:
                    if m["home_score"] > m["away_score"]:
                        winner_id = m["home_team_id"]
                    elif m["away_score"] > m["home_score"]:
                        winner_id = m["away_team_id"]
                matchups.append(DryMatchup(
                    week=week,
                    home_team_id=m["home_team_id"],
                    away_team_id=m["away_team_id"],
                    home_score=m["home_score"],
                    away_score=m["away_score"],
                    winner_id=winner_id,
                ))
            print(f"    Week {week:>2}: {len(week_data)} matchup(s)", flush=True)

        except Exception as e:
            print(f"    Week {week:>2}: {e} — stopping.", flush=True)
            if week == 1:
                raise RuntimeError(f"Week 1 matchup fetch failed: {e}") from e
            break
    return matchups


def _fetch_rosters(
    query: YahooFantasySportsQuery,
    teams: list[DryTeam],
    week:  int,
) -> dict[int, list[DryRosterSlot]]:
    rosters: dict[int, list[DryRosterSlot]] = {}
    for team in teams:
        print(f"    Team {team.yahoo_team_id:>2} ({team.team_name:<28}) ...", end="", flush=True)
        try:
            raw_roster = query.get_team_roster_by_week(team.yahoo_team_id, week)
            players    = getattr(raw_roster, "players", []) or []
            slots: list[DryRosterSlot] = []
            for p in players:
                name      = _s(p.full_name)
                disp_pos  = _s(p.display_position)
                primary   = disp_pos.split(",")[0].strip() or "?"
                slot_val  = _s(p.selected_position_value)
                raw_code  = _s(getattr(p, "status", None))
                norm      = _normalize_injury(raw_code)   # raises on unknown codes
                slots.append(DryRosterSlot(
                    player=DryPlayer(name=name, position=primary),
                    slot=slot_val,
                    injury_raw=raw_code,
                    injury_norm=norm,
                ))
            slots.sort(key=_slot_sort_key)
            rosters[team.yahoo_team_id] = slots
            print(f" {len(slots)} players", flush=True)
        except Exception as e:
            print(f" FAILED: {e}", flush=True)
            raise RuntimeError(
                f"Roster fetch failed for team {team.yahoo_team_id} ({team.team_name}): {e}"
            ) from e
    return rosters


# ── Backup ────────────────────────────────────────────────────────────────────

# Every table that participates in the wipe is backed up here — same set as
# _WIPE_ORDER — so the full pre-wipe state is recoverable from a single file.
# Order within _BACKUP_MODELS doesn't matter (reads only); it mirrors
# _WIPE_ORDER for easy cross-referencing.
_BACKUP_MODELS = [
    # ── Deepest children ───────────────────────────────────────────────────────
    ("transactions",        Transaction),
    ("rule_executions",     RuleExecution),
    ("escrow_transactions", EscrowTransaction),
    ("rule_audit_log",      RuleAuditLog),
    ("feed_events",         FeedEvent),
    ("wrap_up_gm_editions", WrapUpGmEdition),
    ("power_rankings",      PowerRanking),
    ("pool_predictions",    PoolPrediction),
    ("pool_bet_picks",      PoolBetPick),
    ("pool_pots",           PoolPot),
    ("faab_transactions",   FaabTransaction),
    ("buy_in_records",      BuyInRecord),
    ("payout_records",      PayoutRecord),
    ("stripe_audit_log",    StripeAuditLog),
    ("league_treasury",     LeagueTreasury),
    ("tuesday_sync_runs",   TuesdaySyncRun),
    # ── Circular-FK group (bets ↔ beef_challenges) ────────────────────────────
    ("bets",                Bet),
    ("beef_challenges",     BeefChallenge),
    # ── Mid-tier ──────────────────────────────────────────────────────────────
    ("escrow_accounts",     EscrowAccount),
    ("commissioner_rules",  CommissionerRule),
    ("users",               User),
    ("weekly_wrap_ups",     WeeklyWrapUp),
    # ── Core seed tables ──────────────────────────────────────────────────────
    ("projections",         Projection),
    ("faab_wallets",        FaabWallet),
    ("wallets",             Wallet),
    ("rosters",             Roster),
    ("matchups",            Matchup),
    ("faab_config",         FaabConfig),
    ("pool_config",         PoolConfig),
    ("league_scoring",      LeagueScoring),
    # ── Roots ─────────────────────────────────────────────────────────────────
    ("teams",               Team),
    ("players",             Player),
    ("leagues",             League),
]


def _serialize_row(row, cols: list[str]) -> dict:
    result = {}
    for col in cols:
        val = getattr(row, col, None)
        if isinstance(val, datetime):
            result[col] = val.isoformat()
        elif isinstance(val, bytes):
            result[col] = val.decode()
        else:
            result[col] = val
    return result


def _backup_current_db(session, backup_dir: str = "backups") -> str:
    """
    Dump every backed-up table to a timestamped JSON file.
    Returns the absolute file path.
    Raises on any error — caller must abort if this raises.
    """
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    path = pathlib.Path(backup_dir) / f"pre_yahoo_seed_{ts}.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "database_url": _DB_URL_ENV[:_DB_URL_ENV.index("@") + 1] + "***"  # redact password
                        if "@" in _DB_URL_ENV else "***",
        "tables": {},
    }

    for table_name, model in _BACKUP_MODELS:
        mapper = sa_inspect(model)
        cols   = [c.key for c in mapper.mapper.columns]
        rows   = session.query(model).all()
        payload["tables"][table_name] = [_serialize_row(r, cols) for r in rows]
        print(f"    {table_name:<20} {len(rows):>6} rows backed up")

    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return str(path.resolve())


# ── Wipe ──────────────────────────────────────────────────────────────────────

# FK-safe deletion order: children before parents.
# Tables are deleted individually rather than using CASCADE so we have explicit
# control and can print counts. Do NOT alter schema or drop tables.
#
# Special handling: bets ↔ beef_challenges is a circular FK (both use use_alter=True
# nullable columns). _wipe_tables() nulls beef_challenges' bet-references first,
# then deletes bets (#17), then beef_challenges (#18).
_WIPE_ORDER = [
    # ── Deepest children (no table in this wipe set references these) ─────────
    ("transactions",        Transaction),        # FK → wallets, bets
    ("rule_executions",     RuleExecution),      # FK → commissioner_rules, leagues, teams, escrow_accounts
    ("escrow_transactions", EscrowTransaction),  # FK → escrow_accounts, leagues, teams
    ("rule_audit_log",      RuleAuditLog),       # FK → commissioner_rules, leagues, users
    ("feed_events",         FeedEvent),          # FK → leagues, teams, beef_challenges, bets
    ("wrap_up_gm_editions", WrapUpGmEdition),    # FK → weekly_wrap_ups, leagues, teams
    ("power_rankings",      PowerRanking),       # FK → leagues, teams
    ("pool_predictions",    PoolPrediction),     # FK → leagues, teams
    ("pool_bet_picks",      PoolBetPick),        # FK → leagues, teams
    ("pool_pots",           PoolPot),            # FK → leagues
    ("faab_transactions",   FaabTransaction),    # FK → leagues, teams
    ("buy_in_records",      BuyInRecord),        # FK → leagues, teams, users
    ("payout_records",      PayoutRecord),       # FK → leagues, teams, users
    ("stripe_audit_log",    StripeAuditLog),     # FK → leagues, teams, users
    ("league_treasury",     LeagueTreasury),     # FK → leagues
    ("tuesday_sync_runs",   TuesdaySyncRun),     # FK → leagues
    # ── Circular FK group — preprocessing NULL step runs before the loop ──────
    ("bets",                Bet),                # FK → matchups, wallets, teams, players, beef_challenges*
    ("beef_challenges",     BeefChallenge),      # FK → teams, players (*circular refs nulled by preprocessing)
    # ── Mid-tier: children of commissioner_rules / users / weekly_wrap_ups ────
    ("escrow_accounts",     EscrowAccount),      # FK → leagues, commissioner_rules, teams
    ("commissioner_rules",  CommissionerRule),   # FK → leagues, users
    ("users",               User),               # FK → teams
    ("weekly_wrap_ups",     WeeklyWrapUp),       # FK → leagues
    # ── Core seed tables ──────────────────────────────────────────────────────
    ("projections",         Projection),         # FK → players
    ("faab_wallets",        FaabWallet),         # FK → teams, leagues
    ("wallets",             Wallet),             # FK → teams
    ("rosters",             Roster),             # FK → teams, players
    ("matchups",            Matchup),            # FK → leagues, teams
    ("faab_config",         FaabConfig),         # FK → leagues
    ("pool_config",         PoolConfig),         # FK → leagues
    ("league_scoring",      LeagueScoring),      # FK → leagues
    # ── Roots ─────────────────────────────────────────────────────────────────
    ("teams",               Team),               # FK → leagues
    ("players",             Player),             # no FK to other wiped tables
    ("leagues",             League),             # root
]


def _wipe_tables(session) -> dict[str, int]:
    """Delete all rows in FK-safe order. Returns {table_name: rows_deleted}."""
    # Break the circular FK between bets ↔ beef_challenges before any deletes.
    # beef_challenges.challenger_bet_id and .challenged_bet_id reference bets.id,
    # blocking deletion of bets while beef_challenges rows point at them.
    # Nulling them first lets us delete bets (#17) before beef_challenges (#18).
    session.execute(text(
        "UPDATE beef_challenges SET challenger_bet_id = NULL, challenged_bet_id = NULL"
    ))

    counts: dict[str, int] = {}
    for table_name, model in _WIPE_ORDER:
        n = session.query(model).delete(synchronize_session=False)
        counts[table_name] = n
        print(f"    deleted {n:>6} row(s) from {table_name}")
    return counts


# ── Seed ──────────────────────────────────────────────────────────────────────

def _seed_to_db(
    session,
    scoring:          DryScoringSettings,
    dry_teams:        list[DryTeam],
    dry_matchups:     list[DryMatchup],
    rosters:          dict[int, list[DryRosterSlot]],
    player_universe:  dict[str, DryPlayer],
) -> dict:
    """
    Insert all new rows. Everything runs inside the caller's session; the caller
    commits (or rolls back) after this returns.
    Returns a counts dict for the post-seed summary.
    """
    # ── League ────────────────────────────────────────────────────────────────
    league = League(
        season           = scoring.season,
        name             = scoring.league_name,
        projection_source= "fantasypros",
    )
    session.add(league)
    session.flush()

    # ── FaabConfig — commissioner-configurable opening balances ───────────────
    # opening_bet    = Cash wallet starting balance  (default $50, withdrawable)
    # opening_waiver = FAAB waiver wallet balance    (default $100, expires EOS)
    faab_config = FaabConfig(league_id=league.id)
    session.add(faab_config)
    session.flush()

    # ── LeagueScoring ─────────────────────────────────────────────────────────
    session.add(LeagueScoring(
        league_id        = league.id,
        scoring_type     = scoring.scoring_type,
        rec_points       = scoring.rec_points,
        pass_td_points   = scoring.pass_td_points,
        rush_td_points   = scoring.rush_td_points,
        rec_td_points    = scoring.rec_td_points,
        bonus_100yd_rush = scoring.bonus_100yd_rush,
        bonus_100yd_rec  = scoring.bonus_100yd_rec,
    ))

    # ── Teams — keyed by yahoo_team_id for matchup wiring ────────────────────
    team_map: dict[int, Team] = {}
    for dt in dry_teams:
        team = Team(
            league_id = league.id,
            team_name = dt.team_name,
            owner     = dt.owner,
            email     = dt.email,
        )
        session.add(team)
        session.flush()
        team_map[dt.yahoo_team_id] = team

    # ── Players (deduped by name, same pattern as mock seed) ─────────────────
    player_map: dict[str, Player] = {}
    for name, dp in player_universe.items():
        player = Player(name=dp.name, position=dp.position)
        session.add(player)
        session.flush()
        player_map[name] = player

    # ── Rosters (insertion order = starter order for _starters()) ────────────
    roster_count = 0
    seen_pairs: set[tuple[int, int]] = set()
    for dt in dry_teams:
        team = team_map[dt.yahoo_team_id]
        for slot in rosters.get(dt.yahoo_team_id, []):
            pid  = player_map[slot.player.name].id
            pair = (team.id, pid)
            if pair not in seen_pairs:
                session.add(Roster(team_id=team.id, player_id=pid))
                seen_pairs.add(pair)
                roster_count += 1

    # ── Matchups ──────────────────────────────────────────────────────────────
    matchup_count = 0
    for dm in dry_matchups:
        home_team = team_map.get(dm.home_team_id)
        away_team = team_map.get(dm.away_team_id)
        if home_team is None or away_team is None:
            print(
                f"    WARNING: matchup week={dm.week} references unknown yahoo_team_id "
                f"({dm.home_team_id} or {dm.away_team_id}) — skipping"
            )
            continue
        winner_team_id = (
            team_map[dm.winner_id].id if dm.winner_id is not None else None
        )
        session.add(Matchup(
            league_id      = league.id,
            week           = dm.week,
            home_team_id   = home_team.id,
            away_team_id   = away_team.id,
            home_score     = dm.home_score,
            away_score     = dm.away_score,
            winner_team_id = winner_team_id,
        ))
        matchup_count += 1

    # ── Wallets — opening balance read from FaabConfig (commissioner setting) ──
    for team in team_map.values():
        session.add(Wallet(team_id=team.id, balance=faab_config.opening_bet))

    # ── FAAB Wallets — waiver budget per team ─────────────────────────────────
    for team in team_map.values():
        session.add(FaabWallet(
            team_id        = team.id,
            league_id      = league.id,
            waiver_balance = faab_config.opening_waiver,
        ))

    return {
        "teams":        len(team_map),
        "players":      len(player_map),
        "rosters":      roster_count,
        "matchups":     matchup_count,
        "wallets":      len(team_map),
        "faab_wallets": len(team_map),
    }


# ── Post-write verification ───────────────────────────────────────────────────

def _verify_db(session) -> None:
    """Run sanity queries against the DB and print results."""
    sep = "─" * 60

    league = session.query(League).first()
    scoring = session.query(LeagueScoring).first()
    n_teams    = session.query(Team).count()
    n_players  = session.query(Player).count()
    n_rosters  = session.query(Roster).count()
    n_matchups = session.query(Matchup).count()
    n_wallets  = session.query(Wallet).count()
    weeks      = sorted(
        r[0] for r in session.query(Matchup.week).distinct().all()
    )
    matchups_per_week = {
        r[0]: r[1]
        for r in session.query(
            Matchup.week, session.query(Matchup).filter(Matchup.week == Matchup.week)
            .correlate(None).count()
        ).all()
    }
    # simpler approach for per-week counts
    from collections import Counter
    week_counts = Counter(
        r[0] for r in session.query(Matchup.week).all()
    )

    print(f"\n  {sep}")
    print(f"  LEAGUE")
    print(f"  {sep}")
    print(f"  name             : {getattr(league, 'name', '???')}")
    print(f"  season           : {getattr(league, 'season', '???')}")
    print(f"  projection_source: {getattr(league, 'projection_source', '???')}")

    print(f"\n  {sep}")
    print(f"  LEAGUE SCORING")
    print(f"  {sep}")
    if scoring:
        print(f"  scoring_type     : {scoring.scoring_type}")
        print(f"  rec_points       : {scoring.rec_points}")
        print(f"  pass_td_points   : {scoring.pass_td_points}  {'✓' if scoring.pass_td_points == 5.0 else '!! EXPECTED 5.0'}")
        print(f"  rush_td_points   : {scoring.rush_td_points}  {'✓' if scoring.rush_td_points == 6.0 else '!! EXPECTED 6.0'}")
        print(f"  rec_td_points    : {scoring.rec_td_points}  {'✓' if scoring.rec_td_points == 6.0 else '!! EXPECTED 6.0'}")
        print(f"  bonus_100yd_rush : {scoring.bonus_100yd_rush}  {'✓' if scoring.bonus_100yd_rush == 0.0 else '!! EXPECTED 0.0'}")
        print(f"  bonus_100yd_rec  : {scoring.bonus_100yd_rec}  {'✓' if scoring.bonus_100yd_rec == 0.0 else '!! EXPECTED 0.0'}")

    print(f"\n  {sep}")
    print(f"  ROW COUNTS")
    print(f"  {sep}")
    def _check(label: str, actual: int, expected: int) -> str:
        mark = "✓" if actual == expected else f"!! EXPECTED {expected}"
        return f"  {label:<16}: {actual:>5}  {mark}"
    print(_check("teams",    n_teams,    12))
    print(_check("players",  n_players,  180))
    print(_check("rosters",  n_rosters,  180))
    print(_check("matchups", n_matchups, 98))
    print(_check("wallets",  n_wallets,  12))

    print(f"\n  {sep}")
    print(f"  MATCHUPS PER WEEK")
    print(f"  {sep}")
    print(f"  weeks with data: {weeks}")
    for wk in sorted(week_counts):
        print(f"    week {wk:>2}: {week_counts[wk]} matchup(s)")

    print(f"\n  {sep}")
    print(f"  WEEK-1 MATCHUP SAMPLE (first 5)")
    print(f"  {sep}")
    wk1 = (
        session.query(Matchup)
        .filter(Matchup.week == 1)
        .order_by(Matchup.id)
        .limit(5)
        .all()
    )
    for m in wk1:
        h = m.home_team.team_name if m.home_team else f"id={m.home_team_id}"
        a = m.away_team.team_name if m.away_team else f"id={m.away_team_id}"
        w = m.winner.team_name    if m.winner    else "TIE"
        print(f"  {h:<30} {m.home_score:>7.2f}  vs  {m.away_score:>7.2f}  {a:<30}  → {w}")

    print(f"\n  {sep}")
    print(f"  TEAM 1 STARTERS (first 9 roster rows)")
    print(f"  {sep}")
    team1 = session.query(Team).filter(Team.email == "yahoo-team-1@fantasy-beefs.local").first()
    if team1:
        starters = (
            session.query(Roster)
            .filter(Roster.team_id == team1.id)
            .order_by(Roster.id)
            .limit(9)
            .all()
        )
        print(f"  {team1.team_name} ({team1.owner})")
        for i, r in enumerate(starters, 1):
            p = r.player
            print(f"    {i}. {p.position:<5} {p.name}")

    # Flag any unexpected values
    all_ok = (
        n_teams    == 12  and
        n_players  == 180 and
        n_rosters  == 180 and
        n_matchups == 98  and
        n_wallets  == 12  and
        scoring and scoring.pass_td_points == 5.0 and
        scoring.rush_td_points == 6.0 and
        scoring.rec_td_points  == 6.0
    )
    print(f"\n  {'✓ ALL SANITY CHECKS PASSED' if all_ok else '!! ONE OR MORE CHECKS FAILED — review output above'}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── Safety gate 1: explicit confirmation flag ─────────────────────────────
    if "--confirm-wipe" not in sys.argv:
        print(
            "\n" + "!" * 70 + "\n"
            "  SAFETY GATE — no changes made.\n\n"
            "  This script will:\n"
            "    1. Back up the current DB state to backups/pre_yahoo_seed_<timestamp>.json\n"
            "    2. DELETE ALL ROWS from projections, wallets, rosters, matchups,\n"
            "       league_scoring, teams, players, leagues\n"
            "    3. Reseed those tables from real 2025 Yahoo data (league_id=488800)\n"
            "    4. Run sanity queries and print the results\n\n"
            "  To proceed:  python seed_real_2025_season_LIVE.py --confirm-wipe\n"
            + "!" * 70 + "\n"
        )
        sys.exit(0)

    print("\n" + "#" * 70)
    print("  FANTASY BEEFS — REAL 2025 SEASON SEED  (LIVE WRITE)")
    print(f"  league_id={LEAGUE_ID}  game_id={GAME_ID}  season={SEASON}")
    print(f"  DATABASE: {_DB_URL_ENV[:_DB_URL_ENV.index('@')+1]}***"
          if "@" in _DB_URL_ENV else f"  DATABASE: {_DB_URL_ENV[:30]}...")
    print("#" * 70 + "\n")

    # ── Step 1: fetch Yahoo data (outside any DB transaction) ─────────────────
    print("[1/5] Authenticating and fetching Yahoo data ...")
    query = _build_query()

    print("  Scoring settings ...", flush=True)
    scoring = _fetch_scoring(query)
    if scoring.flags:
        for f in scoring.flags:
            print(f"  FLAG: {f}")
    print(
        f"  → scoring_type={scoring.scoring_type!r}  "
        f"pass_td={scoring.pass_td_points}  rush_td={scoring.rush_td_points}  "
        f"rec={scoring.rec_points}  rec_td={scoring.rec_td_points}"
    )

    print("  Teams ...", flush=True)
    dry_teams = _fetch_teams(query)
    print(f"  → {len(dry_teams)} teams")

    print(f"  Matchup scoreboard (weeks 1–{MAX_WEEK}) ...", flush=True)
    dry_matchups = _fetch_matchups(query)
    weeks = sorted({m.week for m in dry_matchups})
    print(f"  → {len(dry_matchups)} matchups across {len(weeks)} weeks: {weeks}")

    print(f"  Rosters (week {ROSTER_WEEK}) ...", flush=True)
    rosters = _fetch_rosters(query, dry_teams, ROSTER_WEEK)

    # Build player universe (deduped by name, starters-first insertion order)
    player_universe: dict[str, DryPlayer] = {}
    for dt in dry_teams:
        for slot in rosters.get(dt.yahoo_team_id, []):
            if slot.player.name not in player_universe:
                player_universe[slot.player.name] = slot.player
    print(f"  → {len(player_universe)} unique players")

    # ── Step 2: backup ────────────────────────────────────────────────────────
    print("\n[2/5] Backing up current DB state ...")
    with SessionLocal() as backup_session:
        try:
            backup_path = _backup_current_db(backup_session)
        except Exception as e:
            print(f"\n!! BACKUP FAILED: {e}")
            print("!! Aborting — database was NOT modified.")
            traceback.print_exc()
            sys.exit(1)
    print(f"  → Backup written to: {backup_path}")

    # ── Steps 3 + 4: wipe then seed — single atomic transaction ───────────────
    # If the seed fails halfway through, rollback leaves the DB in pre-wipe state.
    print("\n[3/5] Wiping existing rows (FK-safe order) ...")
    print("[4/5] Seeding from Yahoo data ...")

    with SessionLocal() as session:
        try:
            wipe_counts = _wipe_tables(session)

            print(f"\n  Inserting new rows ...")
            seed_counts = _seed_to_db(
                session, scoring, dry_teams, dry_matchups, rosters, player_universe
            )

            print(f"\n  Committing transaction ...")
            session.commit()
            print("  → Committed successfully.")

        except Exception as e:
            session.rollback()
            print(f"\n!! ERROR during wipe/seed — transaction rolled back: {e}")
            print(f"!! Database is in pre-wipe state. Backup available at: {backup_path}")
            traceback.print_exc()
            sys.exit(1)

    print(f"\n  Rows inserted:")
    for k, v in seed_counts.items():
        print(f"    {k:<12}: {v}")

    # ── Step 5: verify ────────────────────────────────────────────────────────
    print("\n[5/5] Verifying inserted data ...")
    with SessionLocal() as verify_session:
        _verify_db(verify_session)

    print("\n" + "#" * 70)
    print("  SEED COMPLETE.")
    print(f"  Backup: {backup_path}")
    print("#" * 70 + "\n")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    main()
