"""
P1.2 Stripe Connect — league treasury, GM buy-ins, payouts.

Mode
  • Real mode : set STRIPE_SECRET_KEY env-var (sk_live_... or sk_test_...)
  • Mock mode : leave STRIPE_SECRET_KEY empty — all Stripe calls are simulated
                with deterministic fake IDs so the rest of the system works
                without credentials.

Stripe Connect Standard accounts
  • GMs link their own Stripe account to receive end-of-season payouts.
  • Buy-ins are collected via Stripe Payment Links on the platform account.
  • Payouts use stripe.Transfer to each winner's connected account.
  • Feature gating: get_buyin_gate() FastAPI dependency blocks betting/beefs
    until the GM's buy-in is confirmed (commissioner always bypasses).

All amounts are in cents (integer) internally.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import (
    BuyInRecord,
    League,
    LeagueTreasury,
    Matchup,
    PayoutRecord,
    StripeAuditLog,
    Team,
    User,
)
from db.deps import get_db
from auth.jwt_auth import get_current_gm
from payments.economy_config import get_league_economy_stop
from ledger.ledger import post as ledger_post

# ── Config ─────────────────────────────────────────────────────────────────────

STRIPE_SECRET_KEY     = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
MOCK_MODE             = not bool(STRIPE_SECRET_KEY)

DEFAULT_PAYOUT_SPLIT = [60, 30, 10]

if not MOCK_MODE:
    import stripe as _stripe
    _stripe.api_key = STRIPE_SECRET_KEY


# ── Internal helpers ──────────────────────────────────────────────────────────

def _mock_id(prefix: str) -> str:
    return f"{prefix}_mock_{uuid.uuid4().hex[:12]}"


def _log(
    db: Session,
    event_type: str,
    description: str,
    *,
    league_id: Optional[int]  = None,
    team_id:   Optional[int]  = None,
    stripe_object: Optional[str] = None,
    amount_cents:  Optional[int] = None,
    raw:           object        = None,
    performed_by:  Optional[int] = None,
) -> None:
    db.add(StripeAuditLog(
        league_id            = league_id,
        team_id              = team_id,
        event_type           = event_type,
        stripe_object        = stripe_object,
        amount_cents         = amount_cents,
        description          = description,
        raw_response         = json.dumps(raw) if raw is not None else None,
        performed_by_user_id = performed_by,
    ))


# ── Treasury ──────────────────────────────────────────────────────────────────

@dataclass
class TreasuryState:
    league_id:             int
    buy_in_amount_cents:   int
    payout_split:          list[int]
    total_collected_cents: int
    total_paid_out_cents:  int
    season_payout_done:    bool
    teams_paid_in:         int
    teams_total:           int
    mock_mode:             bool


def setup_league_treasury(
    league_id:    int,
    buy_in_cents: int,
    db:           Session,
    payout_split: Optional[list[int]] = None,
    performer_id: Optional[int]       = None,
) -> TreasuryState:
    """
    Create or update league treasury configuration.  Safe to call multiple times.

    payout_split: list of ints that must sum to 100, one entry per payout place
                  (default [60, 30, 10]).
    """
    if buy_in_cents < 0:
        raise ValueError("buy_in_cents must be >= 0")

    split = payout_split or DEFAULT_PAYOUT_SPLIT
    if sum(split) != 100:
        raise ValueError(f"payout_split must sum to 100; got {sum(split)}")

    treasury = (
        db.query(LeagueTreasury)
        .filter(LeagueTreasury.league_id == league_id)
        .first()
    )
    if treasury is None:
        treasury = LeagueTreasury(league_id=league_id)
        db.add(treasury)

    treasury.buy_in_amount_cents = buy_in_cents
    treasury.payout_split_json   = json.dumps(split)
    treasury.updated_at          = datetime.now(timezone.utc)
    db.flush()

    _log(db, "treasury_configured",
         f"Buy-in={buy_in_cents}¢  split={split}",
         league_id=league_id, amount_cents=buy_in_cents, performed_by=performer_id)

    db.commit()
    return _treasury_state(league_id, db)


def _treasury_state(league_id: int, db: Session) -> TreasuryState:
    treasury = (
        db.query(LeagueTreasury)
        .filter(LeagueTreasury.league_id == league_id)
        .first()
    )
    if not treasury:
        raise ValueError(f"Treasury not configured for league {league_id}")

    teams_total = db.query(Team).filter(Team.league_id == league_id).count()
    teams_paid  = (
        db.query(BuyInRecord)
        .filter(BuyInRecord.league_id == league_id, BuyInRecord.status == "paid")
        .count()
    )
    return TreasuryState(
        league_id             = league_id,
        buy_in_amount_cents   = treasury.buy_in_amount_cents,
        payout_split          = json.loads(treasury.payout_split_json),
        total_collected_cents = treasury.total_collected_cents,
        total_paid_out_cents  = treasury.total_paid_out_cents,
        season_payout_done    = bool(treasury.season_payout_done),
        teams_paid_in         = teams_paid,
        teams_total           = teams_total,
        mock_mode             = MOCK_MODE,
    )


def get_treasury_state(league_id: int, db: Session) -> TreasuryState:
    return _treasury_state(league_id, db)


# ── Buy-in ────────────────────────────────────────────────────────────────────

@dataclass
class BuyInLink:
    record_id:    int
    team_id:      int
    team_name:    str
    owner:        str
    amount_cents: int
    payment_url:  str
    status:       str
    mock_mode:    bool


def create_buyin_link(
    league_id:    int,
    team_id:      int,
    db:           Session,
    performer_id: Optional[int] = None,
) -> BuyInLink:
    """Generate (or return existing) Stripe Payment Link for a GM's buy-in."""
    # B1-12 — the Discrete-Stop Economy Table's selection now lives on the
    # league itself (League.economy_stop_weekly_min_cents), independent of
    # LeagueTreasury entirely. get_league_economy_stop() always returns a
    # valid stop (falls back to the default if unconfigured) — no
    # LeagueTreasury row is read, checked for existence, or required here.
    stop = get_league_economy_stop(league_id, db)

    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise ValueError(f"Team {team_id} not found")

    existing = (
        db.query(BuyInRecord)
        .filter(BuyInRecord.league_id == league_id, BuyInRecord.team_id == team_id)
        .first()
    )

    if existing and existing.status == "paid":
        return BuyInLink(
            record_id   = existing.id,
            team_id     = team_id,
            team_name   = team.team_name,
            owner       = team.owner,
            amount_cents = existing.amount_cents,
            payment_url  = existing.stripe_payment_link_url or "(already paid)",
            status       = "paid",
            mock_mode    = MOCK_MODE,
        )

    # Snapshot the full triple from the active stop NOW, atomically with
    # record creation — a later slider change can't split one buy-in
    # across two different stops between this and payment confirmation.
    record = existing or BuyInRecord(
        league_id     = league_id,
        team_id       = team_id,
        user_id       = team.user.id if team.user else None,
        amount_cents  = stop.buyin_cents,
        buyin_cents   = stop.buyin_cents,
        wallet_cents  = stop.wallet_cents,
        reserve_cents = stop.reserve_cents,
        status        = "pending",
    )
    if not existing:
        db.add(record)
        db.flush()

    # Create Stripe Payment Link
    if MOCK_MODE:
        link_id  = _mock_id("plink")
        link_url = f"https://buy.stripe.com/mock/{link_id}"
        raw      = {"id": link_id, "url": link_url, "mock": True}
    else:
        price = _stripe.Price.create(
            unit_amount  = stop.buyin_cents,
            currency     = "usd",
            product_data = {
                "name": f"Fantasy Beefs Buy-In — {team.team_name}",
            },
        )
        link_obj = _stripe.PaymentLink.create(
            line_items = [{"price": price.id, "quantity": 1}],
            metadata   = {
                "league_id": str(league_id),
                "team_id":   str(team_id),
                "record_id": str(record.id),
            },
            after_completion = {
                "type":     "redirect",
                "redirect": {"url": "https://fantasybeefs.com/buyin/done"},
            },
        )
        link_id  = link_obj.id
        link_url = link_obj.url
        raw      = {"id": link_id, "url": link_url}

    record.stripe_payment_link_id  = link_id
    record.stripe_payment_link_url = link_url

    _log(db, "payment_link_created",
         f"{team.team_name} buy-in {stop.buyin_cents}¢",
         league_id=league_id, team_id=team_id,
         stripe_object=link_id, amount_cents=stop.buyin_cents,
         raw=raw, performed_by=performer_id)

    db.commit()

    return BuyInLink(
        record_id   = record.id,
        team_id     = team_id,
        team_name   = team.team_name,
        owner       = team.owner,
        amount_cents = record.amount_cents,
        payment_url  = link_url,
        status       = record.status,
        mock_mode    = MOCK_MODE,
    )


def confirm_buyin_payment(
    record_id:               int,
    db:                      Session,
    stripe_session_id:       Optional[str] = None,
    stripe_payment_intent_id: Optional[str] = None,
) -> BuyInRecord:
    """
    Mark a buy-in as paid.  Called from the Stripe webhook or via the
    commissioner's manual-confirm endpoint.  Idempotent.
    """
    record = db.query(BuyInRecord).filter(BuyInRecord.id == record_id).first()
    if not record:
        raise ValueError(f"BuyInRecord {record_id} not found")
    if record.status == "paid":
        return record

    # Door 1 — post the buy-in through the ledger BEFORE flipping status to
    # "paid", inside this function's existing transaction (session=db, no
    # extra commit here). Reads buyin_cents/wallet_cents/reserve_cents from
    # THIS RECORD's own snapshot, never from live config. If post() raises
    # (LedgerImbalanceError or InsufficientFundsError), it propagates and
    # everything below — including the eventual db.commit() — never runs,
    # so status can never reach "paid" without a real, balanced posting
    # behind it.
    ledger_post(
        [
            ("world", -record.buyin_cents),
            (f"wallet:{record.team_id}",  record.wallet_cents),
            (f"reserve:{record.team_id}", record.reserve_cents),
        ],
        door="buy_in_paid",
        session=db,
    )

    record.status  = "paid"
    record.paid_at = datetime.now(timezone.utc)
    if stripe_session_id:
        record.stripe_session_id = stripe_session_id
    if stripe_payment_intent_id:
        record.stripe_payment_intent_id = stripe_payment_intent_id

    if record.user_id:
        user = db.query(User).filter(User.id == record.user_id).first()
        if user:
            user.buy_in_paid = 1

    # LeagueTreasury.total_collected_cents is retired from this call site —
    # the ledger's world account balance is now the source of truth for
    # total collected. See this session's report for other readers of this
    # field that were NOT touched and now see a stale value.

    _log(db, "buy_in_confirmed",
         f"Buy-in confirmed for team {record.team_id}",
         league_id=record.league_id, team_id=record.team_id,
         stripe_object=stripe_session_id or stripe_payment_intent_id,
         amount_cents=record.amount_cents)

    db.commit()
    db.refresh(record)
    return record


@dataclass
class BuyInStatus:
    team_id:     int
    team_name:   str
    owner:       str
    email:       str
    status:      str   # "pending" | "paid" | "no_link"
    amount_cents: int
    paid_at:     Optional[str]
    payment_url: Optional[str]


def get_buyin_status(league_id: int, db: Session) -> list[BuyInStatus]:
    """Return buy-in status for every team in the league."""
    treasury = (
        db.query(LeagueTreasury)
        .filter(LeagueTreasury.league_id == league_id)
        .first()
    )
    buy_in_cents = treasury.buy_in_amount_cents if treasury else 0

    teams   = db.query(Team).filter(Team.league_id == league_id).order_by(Team.id).all()
    records = {
        r.team_id: r
        for r in db.query(BuyInRecord).filter(BuyInRecord.league_id == league_id).all()
    }

    result = []
    for team in teams:
        rec = records.get(team.id)
        result.append(BuyInStatus(
            team_id     = team.id,
            team_name   = team.team_name,
            owner       = team.owner,
            email       = team.email,
            status      = rec.status if rec else "no_link",
            amount_cents = rec.amount_cents if rec else buy_in_cents,
            paid_at     = rec.paid_at.isoformat() if rec and rec.paid_at else None,
            payment_url = rec.stripe_payment_link_url if rec else None,
        ))
    return result


# ── GM Stripe Connect account ─────────────────────────────────────────────────

def create_connect_onboarding_link(
    team_id:    int,
    db:         Session,
    return_url: str = "",
) -> str:
    """
    Generate a Stripe Connect Standard onboarding URL so a GM can link their
    Stripe account for receiving season-end payouts.

    In mock mode: assigns a fake account ID and returns a fake URL.
    In real mode: creates a Stripe Standard account (if new) + AccountLink.
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise ValueError(f"Team {team_id} not found")
    user = team.user
    if not user:
        raise ValueError(f"Team {team_id} has no linked user account")

    if MOCK_MODE:
        if not user.stripe_account_id:
            user.stripe_account_id = _mock_id("acct")
            _log(db, "connect_account_created",
                 f"Mock Stripe account for {team.team_name}",
                 team_id=team_id, stripe_object=user.stripe_account_id)
            db.commit()
        onboarding_url = (
            f"https://connect.stripe.com/setup/mock/{user.stripe_account_id}"
        )
        _log(db, "connect_onboarding_created",
             f"Mock onboarding link for {team.team_name}",
             team_id=team_id, stripe_object=user.stripe_account_id)
        db.commit()
        return onboarding_url

    if not user.stripe_account_id:
        account = _stripe.Account.create(
            type     = "standard",
            email    = user.email,
            metadata = {"team_id": str(team_id), "team_name": team.team_name},
        )
        user.stripe_account_id = account.id
        _log(db, "connect_account_created",
             f"Stripe account {account.id} for {team.team_name}",
             team_id=team_id, stripe_object=account.id)
        db.commit()

    link = _stripe.AccountLink.create(
        account     = user.stripe_account_id,
        refresh_url = return_url or "https://fantasybeefs.com/connect/refresh",
        return_url  = return_url or "https://fantasybeefs.com/connect/done",
        type        = "account_onboarding",
    )
    _log(db, "connect_onboarding_created",
         f"Onboarding link for {team.team_name}",
         team_id=team_id, stripe_object=user.stripe_account_id)
    db.commit()
    return link.url


# ── Payouts ───────────────────────────────────────────────────────────────────

@dataclass
class PayoutPreviewRow:
    place:             int
    team_id:           int
    team_name:         str
    owner:             str
    pct:               int
    amount_cents:      int
    stripe_account_id: Optional[str]
    can_receive:       bool


@dataclass
class PayoutPreview:
    league_id:       int
    treasury_cents:  int
    payout_split:    list[int]
    rows:            list[PayoutPreviewRow]
    mock_mode:       bool
    blocking_issues: list[str]


def preview_payouts(
    league_id:       int,
    db:              Session,
    standings_order: Optional[list[int]] = None,
) -> PayoutPreview:
    """
    Return a season payout preview.

    standings_order: list of team_ids in rank order [1st, 2nd, 3rd, ...]
                     If None, derived from regular-season standings (weeks 1-14).
    """
    treasury = (
        db.query(LeagueTreasury)
        .filter(LeagueTreasury.league_id == league_id)
        .first()
    )
    if not treasury:
        raise ValueError(f"Treasury not configured for league {league_id}")
    if treasury.season_payout_done:
        raise ValueError("Season payouts already completed for this league")

    split = json.loads(treasury.payout_split_json)
    order = standings_order or _compute_standings_order(league_id, db)

    issues: list[str] = []
    rows:   list[PayoutPreviewRow] = []

    for i, pct in enumerate(split):
        if i >= len(order):
            break
        team_id = order[i]
        team    = db.query(Team).filter(Team.id == team_id).first()
        user    = team.user if team else None
        amount  = (treasury.total_collected_cents * pct) // 100

        stripe_acct = user.stripe_account_id if user else None
        can_receive = bool(stripe_acct)
        if not can_receive:
            issues.append(
                f"{team.team_name if team else team_id} (place {i+1}): "
                "no connected Stripe account"
            )

        rows.append(PayoutPreviewRow(
            place             = i + 1,
            team_id           = team_id,
            team_name         = team.team_name if team else str(team_id),
            owner             = team.owner if team else "",
            pct               = pct,
            amount_cents      = amount,
            stripe_account_id = stripe_acct,
            can_receive       = can_receive,
        ))

    return PayoutPreview(
        league_id       = league_id,
        treasury_cents  = treasury.total_collected_cents,
        payout_split    = split,
        rows            = rows,
        mock_mode       = MOCK_MODE,
        blocking_issues = issues,
    )


def execute_payouts(
    league_id:       int,
    db:              Session,
    standings_order: Optional[list[int]] = None,
    performer_id:    Optional[int]       = None,
) -> list[PayoutRecord]:
    """
    Send season-end transfers to top finishers via Stripe.
    Commissioner-only.  Idempotent per record (skips already-sent ones).
    In mock mode: creates mock transfer IDs; no real Stripe calls.
    In real mode with no connected accounts: raises ValueError.
    """
    treasury = (
        db.query(LeagueTreasury)
        .filter(LeagueTreasury.league_id == league_id)
        .first()
    )
    if not treasury:
        raise ValueError(f"Treasury not configured for league {league_id}")
    if treasury.season_payout_done:
        raise ValueError("Season payouts already completed")
    if treasury.total_collected_cents <= 0:
        raise ValueError("No funds in treasury to pay out")

    preview = preview_payouts(league_id, db, standings_order)

    if not MOCK_MODE and preview.blocking_issues:
        raise ValueError(
            "Cannot execute — winners missing connected Stripe accounts:\n"
            + "\n".join(preview.blocking_issues)
        )

    records: list[PayoutRecord] = []
    total_sent = 0

    for row in preview.rows:
        existing = (
            db.query(PayoutRecord)
            .filter(
                PayoutRecord.league_id == league_id,
                PayoutRecord.team_id   == row.team_id,
                PayoutRecord.place     == row.place,
            )
            .first()
        )
        if existing and existing.status == "sent":
            records.append(existing)
            total_sent += existing.amount_cents
            continue

        team = db.query(Team).filter(Team.id == row.team_id).first()
        rec  = existing or PayoutRecord(
            league_id                = league_id,
            team_id                  = row.team_id,
            user_id                  = team.user.id if team and team.user else None,
            place                    = row.place,
            amount_cents             = row.amount_cents,
            pct                      = row.pct,
            status                   = "pending",
            stripe_connected_account = row.stripe_account_id,
        )
        if not existing:
            db.add(rec)
            db.flush()

        if MOCK_MODE:
            transfer_id = _mock_id("tr")
            rec.stripe_transfer_id = transfer_id
            rec.status  = "sent"
            rec.sent_at = datetime.now(timezone.utc)
            _log(db, "payout_sent_mock",
                 f"Mock transfer {row.amount_cents}¢ → {row.team_name} (place {row.place})",
                 league_id=league_id, team_id=row.team_id,
                 stripe_object=transfer_id, amount_cents=row.amount_cents,
                 performed_by=performer_id)
        else:
            try:
                transfer = _stripe.Transfer.create(
                    amount      = row.amount_cents,
                    currency    = "usd",
                    destination = row.stripe_account_id,
                    description = f"Fantasy Beefs season payout — place {row.place}",
                    metadata    = {
                        "league_id": str(league_id),
                        "team_id":   str(row.team_id),
                        "place":     str(row.place),
                        "pct":       str(row.pct),
                    },
                )
                rec.stripe_transfer_id = transfer.id
                rec.status  = "sent"
                rec.sent_at = datetime.now(timezone.utc)
                _log(db, "payout_sent",
                     f"Transfer {row.amount_cents}¢ → {row.team_name} (place {row.place})",
                     league_id=league_id, team_id=row.team_id,
                     stripe_object=transfer.id, amount_cents=row.amount_cents,
                     raw={"id": transfer.id}, performed_by=performer_id)
            except Exception as exc:
                rec.status = "failed"
                _log(db, "payout_failed",
                     f"Transfer failed for {row.team_name}: {exc}",
                     league_id=league_id, team_id=row.team_id,
                     amount_cents=row.amount_cents, performed_by=performer_id)

        total_sent += rec.amount_cents
        records.append(rec)

    treasury.total_paid_out_cents += total_sent
    treasury.season_payout_done    = 1
    treasury.updated_at            = datetime.now(timezone.utc)

    db.commit()
    for r in records:
        db.refresh(r)

    return records


def _compute_standings_order(league_id: int, db: Session) -> list[int]:
    """Return team IDs sorted by regular-season record (desc wins, desc PF)."""
    matchups = (
        db.query(Matchup)
        .filter(Matchup.league_id == league_id, Matchup.week <= 14)
        .all()
    )
    stats: dict[int, dict] = {}
    for m in matchups:
        for team_id, pf, pa in (
            (m.home_team_id, m.home_score, m.away_score),
            (m.away_team_id, m.away_score, m.home_score),
        ):
            if team_id not in stats:
                stats[team_id] = {"w": 0, "pf": 0.0}
            stats[team_id]["pf"] += pf
            if team_id == m.winner_team_id:
                stats[team_id]["w"] += 1
    return sorted(stats, key=lambda t: (-stats[t]["w"], -stats[t]["pf"]))


# ── Webhook handler ───────────────────────────────────────────────────────────

def handle_stripe_webhook(payload: bytes, sig_header: str, db: Session) -> dict:
    """
    Verify signature and dispatch Stripe webhook events.

    Supported:
      • checkout.session.completed  → confirm_buyin_payment
      • payment_intent.succeeded    → audit log only (fallback)
    """
    if MOCK_MODE:
        return {"status": "mock_mode_no_webhooks"}

    try:
        event = _stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except _stripe.error.SignatureVerificationError as exc:
        raise ValueError(f"Invalid webhook signature: {exc}")

    if event["type"] == "checkout.session.completed":
        session   = event["data"]["object"]
        metadata  = session.get("metadata", {})
        record_id = metadata.get("record_id")
        if record_id:
            confirm_buyin_payment(
                int(record_id), db,
                stripe_session_id        = session["id"],
                stripe_payment_intent_id = session.get("payment_intent"),
            )
        return {"status": "buy_in_confirmed", "session_id": session["id"]}

    if event["type"] == "payment_intent.succeeded":
        pi = event["data"]["object"]
        _log(db, "payment_intent_succeeded",
             f"PaymentIntent {pi['id']} succeeded",
             stripe_object=pi["id"], amount_cents=pi.get("amount"))
        db.commit()
        return {"status": "logged", "payment_intent": pi["id"]}

    return {"status": "unhandled", "event_type": event["type"]}


# ── Audit log query ───────────────────────────────────────────────────────────

@dataclass
class AuditEntry:
    id:            int
    event_type:    str
    description:   str
    league_id:     Optional[int]
    team_id:       Optional[int]
    stripe_object: Optional[str]
    amount_cents:  Optional[int]
    created_at:    str


def get_audit_log(
    league_id: int,
    db:        Session,
    limit:     int = 100,
    offset:    int = 0,
) -> list[AuditEntry]:
    rows = (
        db.query(StripeAuditLog)
        .filter(StripeAuditLog.league_id == league_id)
        .order_by(StripeAuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        AuditEntry(
            id            = r.id,
            event_type    = r.event_type,
            description   = r.description or "",
            league_id     = r.league_id,
            team_id       = r.team_id,
            stripe_object = r.stripe_object,
            amount_cents  = r.amount_cents,
            created_at    = r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


# ── B2, Finding 5.3 — explicit buy-in enforcement activation ──────────────────

def set_buyin_enforcement_active(
    league_id:    int,
    active:       bool,
    db:           Session,
    performer_id: Optional[int] = None,
) -> bool:
    """
    Commissioner-facing setter. Flips League.buyin_enforcement_active.
    Independent of LeagueTreasury entirely — no row there is read or
    required. Takes effect on the very next request (get_buyin_gate reads
    this column fresh every call; nothing caches it).
    """
    league = db.query(League).filter(League.id == league_id).first()
    if not league:
        raise ValueError(f"League {league_id} not found")

    league.buyin_enforcement_active = active
    _log(db, "buyin_enforcement_toggled",
         f"Buy-in enforcement {'activated' if active else 'deactivated'} for league {league_id}",
         league_id=league_id, performed_by=performer_id)
    db.commit()
    return league.buyin_enforcement_active


def get_buyin_enforcement_active(league_id: int, db: Session) -> bool:
    """Reads League.buyin_enforcement_active. False (inactive) if the
    league doesn't exist — same fail-open posture as an unconfigured stop."""
    league = db.query(League).filter(League.id == league_id).first()
    return bool(league.buyin_enforcement_active) if league else False


# ── FastAPI dependency — buy-in gate ─────────────────────────────────────────

def get_buyin_gate(
    current_user: User    = Depends(get_current_gm),
    db:           Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency — blocks GMs from betting/beefs until their buy-in is paid.
    Commissioner always bypasses.
    Gate is inactive unless the league's commissioner has explicitly turned
    on League.buyin_enforcement_active (B2, Finding 5.3) — independent of
    LeagueTreasury entirely.
    """
    if current_user.role == "commissioner":
        return current_user

    # Find the team's league via the team's league_id
    if current_user.team_id is None:
        return current_user

    team = db.query(Team).filter(Team.id == current_user.team_id).first()
    if not team:
        return current_user

    league = db.query(League).filter(League.id == team.league_id).first()
    if not league or not league.buyin_enforcement_active:
        return current_user  # enforcement off — gate inactive by explicit choice

    if not current_user.buy_in_paid:
        raise HTTPException(
            status_code = status.HTTP_402_PAYMENT_REQUIRED,
            detail      = "Buy-in payment required before placing bets or issuing challenges",
        )

    return current_user
