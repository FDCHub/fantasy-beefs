"""
Commissioner Rules Engine — natural language rules with AI parsing.

Rule types:
  weekly      — executes at Tuesday 12:01am for the just-completed week
  end_of_season — executes at final settlement

Effect types:
  obligation — GM owes X (debit bet wallet)
  payout     — GM receives X (credit bet wallet)

Escrow: optional mid-season holding bucket; releases on trigger (end_of_season or manual).

AI parsing order: Ollama/Qwen (10.0.0.11:11434) → Anthropic Claude → heuristic fallback.

Workflow:
  1.  POST /rules/parse           → returns ParsePreview for commissioner review
  2.  POST /rules/create          → saves as draft CommissionerRule
  3.  POST /rules/activate/{id}   → draft → active
  4a. POST /rules/execute-weekly  → Tuesday automation calls this
  4b. POST /rules/execute-end-of-season → final settlement calls this
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import (
    CommissionerRule,
    EscrowAccount,
    EscrowTransaction,
    Matchup,
    RuleAuditLog,
    RuleExecution,
    Team,
    Transaction,
    Wallet,
)

# ── AI client config ──────────────────────────────────────────────────────────

OLLAMA_BASE  = os.getenv("OLLAMA_URL",   "http://10.0.0.11:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
_OLLAMA_TIMEOUT = 15  # seconds

_VALID_RULE_TYPES   = {"weekly", "end_of_season"}
_VALID_EFFECT_TYPES = {"obligation", "payout"}
_VALID_TARGETS      = {"biggest_loss_margin", "missed_lineup", "points_leader", "commissioner_manual"}
_VALID_TRIGGERS     = {"end_of_season", "manual"}

# ── Pydantic-compatible result dataclasses ────────────────────────────────────

@dataclass
class ParsePreview:
    rule_type:              str
    effect_type:            str
    target:                 str
    amount:                 float
    has_escrow:             bool
    escrow_release_trigger: Optional[str]
    escrow_release_target:  Optional[str]
    week_start:             Optional[int]
    week_end:               Optional[int]
    ai_interpretation:      str
    ai_model_used:          str
    ai_latency_ms:          int
    raw_text:               str


@dataclass
class EscrowOut:
    escrow_id:       int
    name:            str
    balance:         float
    status:          str
    release_trigger: str
    released_at:     Optional[str]


@dataclass
class RuleOut:
    rule_id:                int
    league_id:              int
    raw_text:               str
    rule_type:              str
    effect_type:            str
    target:                 str
    amount:                 float
    has_escrow:             bool
    escrow_release_trigger: Optional[str]
    escrow_release_target:  Optional[str]
    ai_interpretation:      Optional[str]
    ai_model_used:          Optional[str]
    status:                 str
    week_start:             Optional[int]
    week_end:               Optional[int]
    created_at:             str
    activated_at:           Optional[str]
    escrow:                 Optional[EscrowOut]


@dataclass
class RuleExecutionOut:
    execution_id: int
    rule_id:      int
    week:         Optional[int]
    team_id:      int
    team_name:    str
    effect_type:  str
    amount:       float
    description:  str
    status:       str
    executed_at:  str


# ── Parsing prompt ────────────────────────────────────────────────────────────

_PARSE_PROMPT = """\
Parse the following fantasy football commissioner rule into structured JSON.

Rule: {raw_text}

Output ONLY a JSON object with exactly these fields:
{{
  "rule_type": "weekly" or "end_of_season",
  "effect_type": "obligation" or "payout",
  "target": "biggest_loss_margin" | "missed_lineup" | "points_leader" | "commissioner_manual",
  "amount": <dollars as float, e.g. 10.0>,
  "has_escrow": <true if funds are collected mid-season and held before final payout>,
  "escrow_release_trigger": "end_of_season" | "manual" | null,
  "escrow_release_target": "points_leader" | "commissioner_manual" | null,
  "week_start": <integer week number or null>,
  "week_end": <integer week number or null>,
  "ai_interpretation": "<one sentence plain-English summary>"
}}

Target field meanings:
- biggest_loss_margin: the team that loses by the most points that week
- missed_lineup: teams that did not properly set their lineup (lowest scorer as proxy)
- points_leader: team with most total regular-season points scored
- commissioner_manual: commissioner manually selects the affected team

Examples:
Rule: "Team with biggest loss margin each week owes $10, collect Tuesday, hold in escrow, pay to regular season points leader at end of season"
Output: {{"rule_type":"weekly","effect_type":"obligation","target":"biggest_loss_margin","amount":10.0,"has_escrow":true,"escrow_release_trigger":"end_of_season","escrow_release_target":"points_leader","week_start":null,"week_end":null,"ai_interpretation":"Each week the GM with the biggest loss margin pays $10 into escrow; at season end the escrow pays out to the points leader."}}

Rule: "GM who misses a lineup owes $5 to the bet pool"
Output: {{"rule_type":"weekly","effect_type":"obligation","target":"missed_lineup","amount":5.0,"has_escrow":false,"escrow_release_trigger":null,"escrow_release_target":null,"week_start":null,"week_end":null,"ai_interpretation":"Each week, GMs who miss their lineup owe $5 to the bet pool."}}
"""


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"No valid JSON in AI response: {text[:300]!r}")


def _validate_spec(spec: dict) -> dict:
    """Normalise and validate parsed spec fields. Raises ValueError on bad data."""
    rule_type   = str(spec.get("rule_type", "")).strip().lower()
    effect_type = str(spec.get("effect_type", "")).strip().lower()
    target      = str(spec.get("target", "commissioner_manual")).strip().lower()

    if rule_type not in _VALID_RULE_TYPES:
        raise ValueError(f"rule_type must be one of {_VALID_RULE_TYPES}, got {rule_type!r}")
    if effect_type not in _VALID_EFFECT_TYPES:
        raise ValueError(f"effect_type must be one of {_VALID_EFFECT_TYPES}, got {effect_type!r}")
    if target not in _VALID_TARGETS:
        target = "commissioner_manual"

    amount = float(spec.get("amount", 0.0))
    if amount <= 0:
        raise ValueError(f"amount must be > 0, got {amount}")

    has_escrow = bool(spec.get("has_escrow", False))
    trigger    = spec.get("escrow_release_trigger") or None
    rel_target = spec.get("escrow_release_target") or None
    if trigger and trigger not in _VALID_TRIGGERS:
        trigger = "manual"

    return {
        "rule_type":              rule_type,
        "effect_type":            effect_type,
        "target":                 target,
        "amount":                 amount,
        "has_escrow":             has_escrow,
        "escrow_release_trigger": trigger,
        "escrow_release_target":  rel_target,
        "week_start":             spec.get("week_start") or None,
        "week_end":               spec.get("week_end") or None,
        "ai_interpretation":      str(spec.get("ai_interpretation", "")).strip(),
    }


# ── AI parsing backends ───────────────────────────────────────────────────────

def _ollama_parse(raw_text: str) -> tuple[dict, int]:
    """Try Ollama/Qwen. Returns (spec_dict, latency_ms). Raises on failure."""
    try:
        import urllib.request
    except ImportError:
        raise RuntimeError("urllib not available")

    prompt = _PARSE_PROMPT.format(raw_text=raw_text)
    payload = json.dumps({
        "model":  OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=_OLLAMA_TIMEOUT) as resp:
        body = json.loads(resp.read())
    latency_ms = int((time.monotonic() - t0) * 1000)

    response_text = body.get("response", "")
    spec = _extract_json(response_text)
    return _validate_spec(spec), latency_ms


def _anthropic_parse(raw_text: str) -> tuple[dict, int]:
    """Try Anthropic Claude. Returns (spec_dict, latency_ms). Raises on failure."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    prompt = _PARSE_PROMPT.format(raw_text=raw_text)
    client = anthropic.Anthropic(api_key=api_key)

    t0 = time.monotonic()
    msg = client.messages.create(
        model      = "claude-haiku-4-5-20251001",
        max_tokens = 512,
        messages   = [{"role": "user", "content": prompt}],
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    text = msg.content[0].text if msg.content else ""
    spec = _extract_json(text)
    return _validate_spec(spec), latency_ms


def _heuristic_parse(raw_text: str) -> tuple[dict, int]:
    """
    Keyword-based fallback when all AI backends are unavailable.
    Covers the two documented test rules reliably.
    """
    t0   = time.monotonic()
    text = raw_text.lower()

    rule_type   = "end_of_season" if "end of season" in text and "weekly" not in text and "each week" not in text else "weekly"
    effect_type = "payout" if "receive" in text or "earn" in text or "win" in text else "obligation"

    # Target detection
    if "loss margin" in text or "biggest loss" in text:
        target = "biggest_loss_margin"
    elif "miss" in text and "lineup" in text:
        target = "missed_lineup"
    elif "points leader" in text or "most points" in text:
        target = "points_leader"
    else:
        target = "commissioner_manual"

    # Amount: first dollar amount in text
    m = re.search(r"\$(\d+(?:\.\d+)?)", text)
    amount = float(m.group(1)) if m else 5.0

    # Escrow detection
    has_escrow = "escrow" in text or "hold" in text or ("collect" in text and "end of season" in text)
    trigger    = "end_of_season" if "end of season" in text else ("manual" if has_escrow else None)
    rel_target = "points_leader" if "points leader" in text else ("commissioner_manual" if has_escrow else None)

    spec = {
        "rule_type":              rule_type,
        "effect_type":            effect_type,
        "target":                 target,
        "amount":                 amount,
        "has_escrow":             has_escrow,
        "escrow_release_trigger": trigger,
        "escrow_release_target":  rel_target,
        "week_start":             None,
        "week_end":               None,
        "ai_interpretation":      f"Heuristic parse: {raw_text[:120]}",
    }
    return _validate_spec(spec), int((time.monotonic() - t0) * 1000)


def parse_rule_text(raw_text: str) -> tuple[dict, str, int]:
    """
    Parse raw commissioner rule text using AI or heuristics.
    Returns (spec_dict, model_name, latency_ms).
    Tries: Ollama → Anthropic → heuristic.
    """
    raw_text = raw_text.strip()
    if not raw_text:
        raise ValueError("rule text cannot be empty")

    errors = []

    try:
        spec, ms = _ollama_parse(raw_text)
        return spec, f"ollama/{OLLAMA_MODEL}", ms
    except Exception as e:
        errors.append(f"ollama: {e}")

    try:
        spec, ms = _anthropic_parse(raw_text)
        return spec, "anthropic/claude-haiku-4-5-20251001", ms
    except Exception as e:
        errors.append(f"anthropic: {e}")

    # Heuristic fallback — always succeeds
    spec, ms = _heuristic_parse(raw_text)
    return spec, f"heuristic (ai unavailable: {'; '.join(errors)})", ms


# ── Audit helper ──────────────────────────────────────────────────────────────

def _log(
    db:           Session,
    event_type:   str,
    description:  str,
    *,
    league_id:    Optional[int] = None,
    rule_id:      Optional[int] = None,
    performer_id: Optional[int] = None,
    ai_model:     Optional[str] = None,
    ai_latency_ms: Optional[int] = None,
    raw_data:     Optional[str] = None,
) -> None:
    db.add(RuleAuditLog(
        rule_id              = rule_id,
        league_id            = league_id,
        performed_by_user_id = performer_id,
        event_type           = event_type,
        description          = description,
        ai_model             = ai_model,
        ai_latency_ms        = ai_latency_ms,
        raw_data             = raw_data,
    ))


# ── Rule serialisation ────────────────────────────────────────────────────────

def _escrow_for_rule(rule: CommissionerRule, db: Session) -> Optional[EscrowAccount]:
    if not rule.has_escrow:
        return None
    return db.query(EscrowAccount).filter(EscrowAccount.rule_id == rule.id).first()


def _rule_out(rule: CommissionerRule, db: Session) -> RuleOut:
    esc = _escrow_for_rule(rule, db)
    return RuleOut(
        rule_id                = rule.id,
        league_id              = rule.league_id,
        raw_text               = rule.raw_text,
        rule_type              = rule.rule_type,
        effect_type            = rule.effect_type,
        target                 = rule.target,
        amount                 = rule.amount,
        has_escrow             = bool(rule.has_escrow),
        escrow_release_trigger = rule.escrow_release_trigger,
        escrow_release_target  = rule.escrow_release_target,
        ai_interpretation      = rule.ai_interpretation,
        ai_model_used          = rule.ai_model_used,
        status                 = rule.status,
        week_start             = rule.week_start,
        week_end               = rule.week_end,
        created_at             = rule.created_at.isoformat() if rule.created_at else "",
        activated_at           = rule.activated_at.isoformat() if rule.activated_at else None,
        escrow                 = EscrowOut(
            escrow_id       = esc.id,
            name            = esc.name,
            balance         = esc.balance,
            status          = esc.status,
            release_trigger = esc.release_trigger,
            released_at     = esc.released_at.isoformat() if esc.released_at else None,
        ) if esc else None,
    )


# ── Rule CRUD ─────────────────────────────────────────────────────────────────

def create_rule_draft(
    league_id: int,
    raw_text:  str,
    spec:      dict,
    db:        Session,
    *,
    performer_id: Optional[int] = None,
    ai_model:     str = "unknown",
    ai_latency_ms: int = 0,
    ai_raw_response: str = "",
) -> RuleOut:
    """Save a parsed spec as a draft CommissionerRule."""
    rule = CommissionerRule(
        league_id              = league_id,
        created_by_user_id     = performer_id,
        raw_text               = raw_text,
        rule_type              = spec["rule_type"],
        effect_type            = spec["effect_type"],
        target                 = spec["target"],
        amount                 = spec["amount"],
        has_escrow             = int(spec["has_escrow"]),
        escrow_release_trigger = spec.get("escrow_release_trigger"),
        escrow_release_target  = spec.get("escrow_release_target"),
        ai_interpretation      = spec.get("ai_interpretation", ""),
        ai_raw_response        = ai_raw_response,
        ai_model_used          = ai_model,
        status                 = "draft",
        week_start             = spec.get("week_start"),
        week_end               = spec.get("week_end"),
    )
    db.add(rule)
    db.flush()

    _log(db, "rule_created", f"Draft rule #{rule.id} created",
         league_id=league_id, rule_id=rule.id, performer_id=performer_id,
         ai_model=ai_model, ai_latency_ms=ai_latency_ms, raw_data=ai_raw_response[:500] if ai_raw_response else None)

    db.commit()
    db.refresh(rule)
    return _rule_out(rule, db)


def activate_rule(rule_id: int, db: Session, *, performer_id: Optional[int] = None) -> RuleOut:
    """Move a draft rule to active. Creates escrow account if needed."""
    rule = db.query(CommissionerRule).filter(CommissionerRule.id == rule_id).first()
    if not rule:
        raise ValueError(f"Rule {rule_id} not found")
    if rule.status != "draft":
        raise ValueError(f"Only draft rules can be activated (current status: {rule.status!r})")

    rule.status       = "active"
    rule.activated_at = datetime.now(timezone.utc)
    rule.updated_at   = datetime.now(timezone.utc)

    if rule.has_escrow:
        _get_or_create_escrow(rule, db)

    _log(db, "rule_activated", f"Rule #{rule.id} activated: {rule.ai_interpretation}",
         league_id=rule.league_id, rule_id=rule.id, performer_id=performer_id)

    db.commit()
    db.refresh(rule)
    return _rule_out(rule, db)


def pause_rule(rule_id: int, db: Session, *, performer_id: Optional[int] = None) -> RuleOut:
    rule = db.query(CommissionerRule).filter(CommissionerRule.id == rule_id).first()
    if not rule:
        raise ValueError(f"Rule {rule_id} not found")
    if rule.status != "active":
        raise ValueError(f"Only active rules can be paused (current status: {rule.status!r})")
    rule.status     = "paused"
    rule.updated_at = datetime.now(timezone.utc)
    _log(db, "rule_paused", f"Rule #{rule.id} paused", league_id=rule.league_id,
         rule_id=rule.id, performer_id=performer_id)
    db.commit()
    db.refresh(rule)
    return _rule_out(rule, db)


def delete_draft(rule_id: int, db: Session, *, performer_id: Optional[int] = None) -> None:
    rule = db.query(CommissionerRule).filter(CommissionerRule.id == rule_id).first()
    if not rule:
        raise ValueError(f"Rule {rule_id} not found")
    if rule.status != "draft":
        raise ValueError(f"Only draft rules can be deleted (current status: {rule.status!r})")
    _log(db, "rule_deleted", f"Draft rule #{rule.id} deleted",
         league_id=rule.league_id, rule_id=rule.id, performer_id=performer_id)
    db.delete(rule)
    db.commit()


def get_rule(rule_id: int, db: Session) -> RuleOut:
    rule = db.query(CommissionerRule).filter(CommissionerRule.id == rule_id).first()
    if not rule:
        raise ValueError(f"Rule {rule_id} not found")
    return _rule_out(rule, db)


def list_rules(
    league_id: int,
    db:        Session,
    *,
    status:    Optional[str] = None,
) -> list[RuleOut]:
    q = db.query(CommissionerRule).filter(CommissionerRule.league_id == league_id)
    if status:
        q = q.filter(CommissionerRule.status == status)
    return [_rule_out(r, db) for r in q.order_by(CommissionerRule.created_at.desc()).all()]


# ── Escrow helpers ────────────────────────────────────────────────────────────

def _get_or_create_escrow(rule: CommissionerRule, db: Session) -> EscrowAccount:
    esc = db.query(EscrowAccount).filter(EscrowAccount.rule_id == rule.id).first()
    if esc:
        return esc
    name = f"Rule #{rule.id}: {(rule.ai_interpretation or rule.raw_text)[:60]}"
    esc = EscrowAccount(
        league_id        = rule.league_id,
        rule_id          = rule.id,
        name             = name,
        balance          = 0.0,
        status           = "open",
        release_trigger  = rule.escrow_release_trigger or "manual",
    )
    db.add(esc)
    db.flush()
    return esc


def release_escrow(
    escrow_id:    int,
    db:           Session,
    *,
    performer_id: Optional[int] = None,
    target_team_id: Optional[int] = None,
) -> EscrowOut:
    """
    Manually release an open escrow to a target team's bet wallet.
    If target_team_id is None, uses the escrow's stored release_team_id
    (set by end-of-season executor) or raises if neither is set.
    """
    esc = db.query(EscrowAccount).filter(EscrowAccount.id == escrow_id).first()
    if not esc:
        raise ValueError(f"Escrow {escrow_id} not found")
    if esc.status != "open":
        raise ValueError(f"Escrow {escrow_id} is already {esc.status!r}")
    if esc.balance <= 0:
        raise ValueError(f"Escrow {escrow_id} has no balance to release")

    team_id = target_team_id or esc.release_team_id
    if not team_id:
        raise ValueError("No target team — provide target_team_id or set it first")

    wallet = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    if not wallet:
        raise ValueError(f"No bet wallet for team {team_id}")

    payout = round(esc.balance, 2)
    wallet.balance = round(wallet.balance + payout, 2)
    db.add(Transaction(
        wallet_id  = wallet.id,
        amount     = payout,
        type       = "deposit",
        created_at = datetime.now(timezone.utc),
    ))

    db.add(EscrowTransaction(
        escrow_id   = esc.id,
        league_id   = esc.league_id,
        team_id     = team_id,
        direction   = "out",
        amount      = payout,
        description = f"Escrow release to team {team_id}",
    ))

    esc.balance         = 0.0
    esc.status          = "released"
    esc.release_team_id = team_id
    esc.released_at     = datetime.now(timezone.utc)
    esc.updated_at      = datetime.now(timezone.utc)

    # Mark held rule executions as paid_out
    db.query(RuleExecution).filter(
        RuleExecution.escrow_id == esc.id,
        RuleExecution.status    == "held_in_escrow",
    ).update({"status": "paid_out", "settled_at": datetime.now(timezone.utc)})

    rule = db.query(CommissionerRule).filter(CommissionerRule.id == esc.rule_id).first()
    _log(db, "escrow_released",
         f"Escrow #{esc.id} released ${payout:.2f} to team {team_id}",
         league_id=esc.league_id, rule_id=esc.rule_id, performer_id=performer_id)

    db.commit()
    db.refresh(esc)
    return EscrowOut(
        escrow_id       = esc.id,
        name            = esc.name,
        balance         = esc.balance,
        status          = esc.status,
        release_trigger = esc.release_trigger,
        released_at     = esc.released_at.isoformat() if esc.released_at else None,
    )


# ── Execution targets ─────────────────────────────────────────────────────────

def _biggest_loss_margin_team(league_id: int, week: int, db: Session) -> tuple[Optional[int], float]:
    """Return (loser_team_id, margin) for the team that lost by the most that week."""
    matchups = db.query(Matchup).filter(
        Matchup.league_id == league_id, Matchup.week == week,
    ).all()
    best_team_id: Optional[int] = None
    best_margin = -1.0
    for m in matchups:
        margin = round(abs(m.home_score - m.away_score), 2)
        if m.winner_team_id == m.home_team_id:
            loser_id = m.away_team_id
        else:
            loser_id = m.home_team_id
        if margin > best_margin:
            best_margin  = margin
            best_team_id = loser_id
    return best_team_id, best_margin


def _missed_lineup_teams(league_id: int, week: int, db: Session) -> list[tuple[int, float]]:
    """
    Proxy for lineup misses: the single lowest-scoring team league-wide that week.
    Real implementation would check lineup management system.
    """
    matchups = db.query(Matchup).filter(
        Matchup.league_id == league_id, Matchup.week == week,
    ).all()
    candidates: list[tuple[int, float]] = []
    for m in matchups:
        if m.home_score <= m.away_score:
            candidates.append((m.home_team_id, m.home_score))
        else:
            candidates.append((m.away_team_id, m.away_score))
    if not candidates:
        return []
    candidates.sort(key=lambda x: x[1])
    return [candidates[0]]  # single lowest scorer per week


def _points_leader_team(league_id: int, db: Session) -> Optional[int]:
    """Team with the highest total points through week 14 (regular season)."""
    matchups = db.query(Matchup).filter(
        Matchup.league_id == league_id, Matchup.week <= 14,
    ).all()
    totals: dict[int, float] = {}
    for m in matchups:
        totals[m.home_team_id] = round(totals.get(m.home_team_id, 0.0) + m.home_score, 2)
        totals[m.away_team_id] = round(totals.get(m.away_team_id, 0.0) + m.away_score, 2)
    if not totals:
        return None
    return max(totals, key=lambda t: totals[t])


# ── Obligation / payout application ──────────────────────────────────────────

def _apply_obligation(
    team_id:      int,
    amount:       float,
    rule:         CommissionerRule,
    week:         Optional[int],
    db:           Session,
    note:         str = "",
) -> RuleExecution:
    """
    Debit team's bet wallet by amount.
    If insufficient free balance: record as 'pending' (team owes it).
    If escrow: credit escrow account and log EscrowTransaction.
    """
    wallet = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    exec_status = "pending"

    if wallet:
        # Check free balance (balance minus pending bet exposure)
        from db.schema import Bet
        pending = db.query(Bet).filter(
            Bet.wallet_id == wallet.id, Bet.status == "pending"
        ).all()
        exposure = sum(b.amount for b in pending)
        free     = round(wallet.balance - exposure, 2)

        if free >= amount:
            wallet.balance = round(wallet.balance - amount, 2)
            db.add(Transaction(
                wallet_id  = wallet.id,
                amount     = -amount,
                type       = "withdrawal",
                created_at = datetime.now(timezone.utc),
            ))
            exec_status = "held_in_escrow" if rule.has_escrow else "collected"

    exe = RuleExecution(
        rule_id     = rule.id,
        league_id   = rule.league_id,
        week        = week,
        team_id     = team_id,
        effect_type = "obligation",
        amount      = amount,
        description = note or rule.ai_interpretation or "",
        status      = exec_status,
    )
    db.add(exe)
    db.flush()

    if rule.has_escrow and exec_status == "held_in_escrow":
        escrow = _get_or_create_escrow(rule, db)
        escrow.balance  = round(escrow.balance + amount, 2)
        escrow.updated_at = datetime.now(timezone.utc)
        db.add(EscrowTransaction(
            escrow_id   = escrow.id,
            league_id   = rule.league_id,
            team_id     = team_id,
            direction   = "in",
            amount      = amount,
            description = note or rule.ai_interpretation or "",
        ))
        exe.escrow_id = escrow.id

    return exe


def _apply_payout(
    team_id:  int,
    amount:   float,
    rule:     CommissionerRule,
    week:     Optional[int],
    db:       Session,
    note:     str = "",
) -> RuleExecution:
    """Credit team's bet wallet by amount."""
    wallet = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    if wallet:
        wallet.balance = round(wallet.balance + amount, 2)
        db.add(Transaction(
            wallet_id  = wallet.id,
            amount     = amount,
            type       = "deposit",
            created_at = datetime.now(timezone.utc),
        ))

    exe = RuleExecution(
        rule_id     = rule.id,
        league_id   = rule.league_id,
        week        = week,
        team_id     = team_id,
        effect_type = "payout",
        amount      = amount,
        description = note or rule.ai_interpretation or "",
        status      = "paid_out",
        settled_at  = datetime.now(timezone.utc),
    )
    db.add(exe)
    return exe


def _execution_out(exe: RuleExecution, db: Session) -> RuleExecutionOut:
    team = db.query(Team).filter(Team.id == exe.team_id).first()
    return RuleExecutionOut(
        execution_id = exe.id,
        rule_id      = exe.rule_id,
        week         = exe.week,
        team_id      = exe.team_id,
        team_name    = team.team_name if team else str(exe.team_id),
        effect_type  = exe.effect_type,
        amount       = exe.amount,
        description  = exe.description or "",
        status       = exe.status,
        executed_at  = exe.executed_at.isoformat() if exe.executed_at else "",
    )


# ── Main executors ────────────────────────────────────────────────────────────

def execute_weekly_rules(
    league_id: int,
    week:      int,
    db:        Session,
    *,
    performer_id: Optional[int] = None,
) -> list[RuleExecutionOut]:
    """
    Run all active weekly rules for the given week.
    Idempotent: skips rules that already have executions for this week.
    """
    if not 1 <= week <= 17:
        raise ValueError("week must be 1–17")

    rules = db.query(CommissionerRule).filter(
        CommissionerRule.league_id == league_id,
        CommissionerRule.status    == "active",
        CommissionerRule.rule_type == "weekly",
    ).all()

    results: list[RuleExecutionOut] = []

    for rule in rules:
        # Idempotency check
        existing = db.query(RuleExecution).filter(
            RuleExecution.rule_id == rule.id,
            RuleExecution.week    == week,
        ).first()
        if existing:
            continue

        # Respect optional week range
        if rule.week_start and week < rule.week_start:
            continue
        if rule.week_end and week > rule.week_end:
            continue

        execs: list[RuleExecution] = []

        if rule.target == "biggest_loss_margin":
            team_id, margin = _biggest_loss_margin_team(league_id, week, db)
            if team_id:
                team = db.query(Team).filter(Team.id == team_id).first()
                note = (f"Week {week} biggest loss margin: "
                        f"{team.team_name if team else team_id} lost by {margin:.1f} pts")
                execs.append(_apply_obligation(team_id, rule.amount, rule, week, db, note=note))

        elif rule.target == "missed_lineup":
            for team_id, score in _missed_lineup_teams(league_id, week, db):
                team = db.query(Team).filter(Team.id == team_id).first()
                note = (f"Week {week} lineup miss: "
                        f"{team.team_name if team else team_id} scored {score:.1f} pts")
                execs.append(_apply_obligation(team_id, rule.amount, rule, week, db, note=note))

        elif rule.target == "commissioner_manual":
            # No automatic target — create a pending flag for commissioner action
            pass

        _log(db, "weekly_execution",
             f"Rule #{rule.id} week {week}: {len(execs)} obligation(s) applied",
             league_id=league_id, rule_id=rule.id, performer_id=performer_id)

        db.flush()
        results.extend([_execution_out(e, db) for e in execs])

    db.commit()
    return results


def execute_end_of_season_rules(
    league_id: int,
    db:        Session,
    *,
    performer_id: Optional[int] = None,
) -> list[RuleExecutionOut]:
    """
    Run all active end_of_season rules and release qualifying escrow accounts.
    Idempotent: skips rules already marked completed.
    """
    rules = db.query(CommissionerRule).filter(
        CommissionerRule.league_id == league_id,
        CommissionerRule.status.in_(["active", "paused"]),
        CommissionerRule.rule_type == "end_of_season",
    ).all()

    results: list[RuleExecutionOut] = []

    # Auto-release weekly-rule escrows triggered by end_of_season
    escrows = db.query(EscrowAccount).filter(
        EscrowAccount.league_id      == league_id,
        EscrowAccount.status         == "open",
        EscrowAccount.release_trigger == "end_of_season",
    ).all()

    for esc in escrows:
        rule = db.query(CommissionerRule).filter(CommissionerRule.id == esc.rule_id).first()
        if not rule or esc.balance <= 0:
            continue

        # Resolve target
        target_team_id: Optional[int] = None
        rel_target = rule.escrow_release_target
        if rel_target == "points_leader":
            target_team_id = _points_leader_team(league_id, db)
        elif rel_target == "commissioner_manual":
            pass  # skip — commissioner must manually release

        if target_team_id:
            _log(db, "escrow_auto_release",
                 f"End-of-season: releasing escrow #{esc.id} (${esc.balance:.2f}) to team {target_team_id}",
                 league_id=league_id, rule_id=rule.id, performer_id=performer_id)
            try:
                release_escrow(esc.id, db, performer_id=performer_id, target_team_id=target_team_id)
            except Exception:
                pass  # already released or no wallet; log was written

    # Run explicit end_of_season rules
    for rule in rules:
        existing = db.query(RuleExecution).filter(
            RuleExecution.rule_id == rule.id,
            RuleExecution.week    == None,
        ).first()
        if existing:
            continue

        execs: list[RuleExecution] = []

        if rule.target == "points_leader":
            team_id = _points_leader_team(league_id, db)
            if team_id:
                team = db.query(Team).filter(Team.id == team_id).first()
                note = f"End-of-season: points leader {team.team_name if team else team_id}"
                if rule.effect_type == "obligation":
                    execs.append(_apply_obligation(team_id, rule.amount, rule, None, db, note=note))
                else:
                    execs.append(_apply_payout(team_id, rule.amount, rule, None, db, note=note))

        elif rule.target == "commissioner_manual":
            pass

        rule.status     = "completed"
        rule.updated_at = datetime.now(timezone.utc)

        _log(db, "end_of_season_execution",
             f"Rule #{rule.id} end-of-season: {len(execs)} execution(s)",
             league_id=league_id, rule_id=rule.id, performer_id=performer_id)

        db.flush()
        results.extend([_execution_out(e, db) for e in execs])

    db.commit()
    return results


def get_rule_executions(
    league_id: int,
    db:        Session,
    *,
    rule_id: Optional[int] = None,
    week:    Optional[int] = None,
    limit:   int = 100,
    offset:  int = 0,
) -> list[RuleExecutionOut]:
    q = db.query(RuleExecution).filter(RuleExecution.league_id == league_id)
    if rule_id is not None:
        q = q.filter(RuleExecution.rule_id == rule_id)
    if week is not None:
        q = q.filter(RuleExecution.week == week)
    rows = q.order_by(RuleExecution.created_at.desc()).offset(offset).limit(limit).all()
    return [_execution_out(e, db) for e in rows]


def get_rule_audit_log(
    league_id: int,
    db:        Session,
    *,
    limit:  int = 100,
    offset: int = 0,
) -> list[dict]:
    rows = (
        db.query(RuleAuditLog)
        .filter(RuleAuditLog.league_id == league_id)
        .order_by(RuleAuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id":            r.id,
            "rule_id":       r.rule_id,
            "event_type":    r.event_type,
            "description":   r.description,
            "ai_model":      r.ai_model,
            "ai_latency_ms": r.ai_latency_ms,
            "created_at":    r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]
