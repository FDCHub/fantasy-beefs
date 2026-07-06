from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

# ── Engine / session ──────────────────────────────────────────────────────────

_ENV_URL = os.environ.get("DATABASE_URL", "")
if _ENV_URL:
    # Railway provides postgres:// (legacy Heroku format); SQLAlchemy 1.4+ requires postgresql://
    DB_URL = _ENV_URL.replace("postgres://", "postgresql://", 1)
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "fantasy.db")
    DB_URL  = f"sqlite:///{DB_PATH}"

engine       = create_engine(DB_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


# ── Base ──────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Tables ────────────────────────────────────────────────────────────────────

class League(Base):
    __tablename__ = "leagues"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    season            = Column(Integer, nullable=False)
    name              = Column(String,  nullable=False)
    projection_source = Column(String,  nullable=False, default="fantasypros")

    teams    = relationship("Team",         back_populates="league")
    matchups = relationship("Matchup",      back_populates="league")
    scoring  = relationship("LeagueScoring", back_populates="league", uselist=False)


class LeagueScoring(Base):
    __tablename__ = "league_scoring"
    __table_args__ = (
        CheckConstraint(
            "scoring_type IN ('standard','half_ppr','ppr','custom')",
            name="ck_scoring_type",
        ),
    )

    id               = Column(Integer, primary_key=True, autoincrement=True)
    league_id        = Column(Integer, ForeignKey("leagues.id"), nullable=False, unique=True)
    scoring_type     = Column(String,  nullable=False, default="half_ppr")
    rec_points       = Column(Float,   nullable=False, default=0.5)
    pass_td_points   = Column(Float,   nullable=False, default=5.0)
    rush_td_points   = Column(Float,   nullable=False, default=6.0)
    rec_td_points    = Column(Float,   nullable=False, default=6.0)
    bonus_100yd_rush = Column(Float,   nullable=False, default=0.0)
    bonus_100yd_rec  = Column(Float,   nullable=False, default=0.0)

    league = relationship("League", back_populates="scoring")


class Team(Base):
    __tablename__ = "teams"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    team_name = Column(String,  nullable=False)
    owner     = Column(String,  nullable=False)
    email     = Column(String,  nullable=False, unique=True)

    league         = relationship("League", back_populates="teams")
    roster         = relationship("Roster", back_populates="team")
    wallet         = relationship("Wallet", back_populates="team", uselist=False)
    user           = relationship("User",   back_populates="team", uselist=False)
    home_matchups  = relationship("Matchup", foreign_keys="Matchup.home_team_id",
                                  back_populates="home_team")
    away_matchups  = relationship("Matchup", foreign_keys="Matchup.away_team_id",
                                  back_populates="away_team")
    bets_placed    = relationship("Bet", foreign_keys="Bet.picked_team_id",
                                  back_populates="picked_team")


class Player(Base):
    __tablename__ = "players"

    id       = Column(Integer,    primary_key=True, autoincrement=True)
    name     = Column(String,     nullable=False, unique=True)
    position = Column(String,     nullable=False)      # QB | RB | WR | TE | FLEX | K | DEF
    nfl_team = Column(String(4),  nullable=True)       # NFL team abbreviation, e.g. "KC", "BAL"

    rosters      = relationship("Roster",     back_populates="player")
    projections  = relationship("Projection", back_populates="player")


class Roster(Base):
    """Static team–player association (one row per player slot per team)."""
    __tablename__ = "rosters"
    __table_args__ = (UniqueConstraint("team_id", "player_id"),)

    id        = Column(Integer, primary_key=True, autoincrement=True)
    team_id   = Column(Integer, ForeignKey("teams.id"),   nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    # Lineup slot (QB/RB/WR/TE/FLEX/K/DEF/BN/IR). NULL = unknown (pre-migration rows).
    # Use slot, not player.position, to determine starters — avoids the FLEX-bug.
    slot      = Column(String, nullable=True)

    team   = relationship("Team",   back_populates="roster")
    player = relationship("Player", back_populates="rosters")


class RosterSlot(Base):
    """One row per team, player, and week. Insert-only — never
    overwritten. Read by weekly_wrap.py and bet settlement to
    answer 'what was true that week.'"""
    __tablename__ = "roster_slots"
    __table_args__ = (UniqueConstraint("team_id", "player_id", "week"),)

    id         = Column(Integer, primary_key=True, autoincrement=True)
    league_id  = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    team_id    = Column(Integer, ForeignKey("teams.id"),   nullable=False)
    player_id  = Column(Integer, ForeignKey("players.id"), nullable=False)
    week       = Column(Integer, nullable=False)
    slot       = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    league = relationship("League")
    team   = relationship("Team")
    player = relationship("Player")


class Matchup(Base):
    __tablename__ = "matchups"
    __table_args__ = (UniqueConstraint("league_id", "week", "home_team_id"),)

    id             = Column(Integer, primary_key=True, autoincrement=True)
    league_id      = Column(Integer, ForeignKey("leagues.id"),  nullable=False)
    week           = Column(Integer, nullable=False)
    home_team_id   = Column(Integer, ForeignKey("teams.id"),    nullable=False)
    away_team_id   = Column(Integer, ForeignKey("teams.id"),    nullable=False)
    home_score     = Column(Float,   nullable=False)
    away_score     = Column(Float,   nullable=False)
    winner_team_id = Column(Integer, ForeignKey("teams.id"),    nullable=True)
    refreshed_at   = Column(DateTime, nullable=True)

    league    = relationship("League", back_populates="matchups")
    home_team = relationship("Team", foreign_keys=[home_team_id],
                             back_populates="home_matchups")
    away_team = relationship("Team", foreign_keys=[away_team_id],
                             back_populates="away_matchups")
    winner    = relationship("Team", foreign_keys=[winner_team_id])
    bets      = relationship("Bet",  back_populates="matchup")


class Wallet(Base):
    __tablename__ = "wallets"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    team_id    = Column(Integer, ForeignKey("teams.id"), nullable=False, unique=True)
    balance    = Column(Float,   nullable=False, default=1000.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    team         = relationship("Team",        back_populates="wallet")
    bets         = relationship("Bet",         back_populates="wallet")
    transactions = relationship("Transaction", back_populates="wallet")


class Bet(Base):
    __tablename__ = "bets"
    __table_args__ = (
        CheckConstraint("status IN ('pending','won','lost','push')", name="ck_bet_status"),
        CheckConstraint("amount > 0",                               name="ck_bet_amount"),
        CheckConstraint(
            "bet_type IN ('straight','spread','over_under','prop','the_lineup')",
            name="ck_bet_type",
        ),
    )

    id             = Column(Integer, primary_key=True, autoincrement=True)
    matchup_id     = Column(Integer, ForeignKey("matchups.id"), nullable=False)
    wallet_id      = Column(Integer, ForeignKey("wallets.id"),  nullable=False)
    picked_team_id = Column(Integer, ForeignKey("teams.id"),    nullable=True)   # null for o/u
    player_id      = Column(Integer, ForeignKey("players.id"),  nullable=True)   # prop: home top player
    bet_type       = Column(String,  nullable=False, default="straight")
    line           = Column(Float,   nullable=True)                               # spread / total / prop threshold
    description    = Column(String,  nullable=True)
    amount         = Column(Float,   nullable=False)
    odds           = Column(Float,   nullable=False, default=1.909)
    side           = Column(String,  nullable=True)                                # "over"|"under" for ou/prop; null for straight/spread
    status         = Column(String,  nullable=False, default="pending")
    placed_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    settled_at     = Column(DateTime, nullable=True)

    beef_challenge_id = Column(Integer, ForeignKey("beef_challenges.id", use_alter=True, name="fk_beef_challenge_id"), nullable=True)

    matchup        = relationship("Matchup", back_populates="bets")
    wallet         = relationship("Wallet",  back_populates="bets")
    picked_team    = relationship("Team",    foreign_keys=[picked_team_id],
                                  back_populates="bets_placed")
    player         = relationship("Player",  foreign_keys=[player_id])
    transactions   = relationship("Transaction", back_populates="bet")
    beef_challenge = relationship("BeefChallenge", foreign_keys=[beef_challenge_id])


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(
            "type IN ('deposit','withdrawal','bet','payout','pool_entry','pool_payout')",
            name="ck_tx_type",
        ),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    wallet_id  = Column(Integer, ForeignKey("wallets.id"), nullable=False)
    amount     = Column(Float,  nullable=False)   # positive = credit, negative = debit
    type       = Column(String, nullable=False)
    bet_id     = Column(Integer, ForeignKey("bets.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    wallet = relationship("Wallet", back_populates="transactions")
    bet    = relationship("Bet",    back_populates="transactions")


class Projection(Base):
    __tablename__ = "projections"
    __table_args__ = (UniqueConstraint("player_id", "week", "season", "source"),)

    id               = Column(Integer, primary_key=True, autoincrement=True)
    player_id        = Column(Integer, ForeignKey("players.id"), nullable=False)
    week             = Column(Integer, nullable=False)
    season           = Column(Integer, nullable=False)
    projected_points = Column(Float,   nullable=True)   # NULL = no pre-week projection available
    actual_points    = Column(Float,   nullable=True)   # NULL until the week settles
    source           = Column(String,  nullable=False)  # yahoo | espn | fantasypros
    injury_status    = Column(String,  nullable=True)   # None | out | ir | doubtful | questionable

    player = relationship("Player", back_populates="projections")


class BeefChallenge(Base):
    """
    A GM-to-GM bet challenge with a 24-hour acceptance window.
    Beefs compare weekly total scores regardless of scheduled opponents —
    no matchup_id needed; settlement looks up each team's score from their
    own game for that week.
    """
    __tablename__ = "beef_challenges"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','countered','accepted','declined','expired')",
            name="ck_beef_status",
        ),
        CheckConstraint(
            "bet_type IN ('straight','spread','over_under','prop')",
            name="ck_beef_bet_type",
        ),
    )

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    challenger_team_id   = Column(Integer, ForeignKey("teams.id"),  nullable=False)
    challenged_team_id   = Column(Integer, ForeignKey("teams.id"),  nullable=False)
    week                 = Column(Integer, nullable=False)
    bet_type             = Column(String,  nullable=False)
    amount               = Column(Float,   nullable=False)
    line                 = Column(Float,   nullable=True)   # spread / total / prop threshold
    side                 = Column(String,  nullable=True)   # "over"|"under" for ou/prop
    player_id            = Column(Integer, ForeignKey("players.id"), nullable=True)
    description          = Column(String,  nullable=True)
    # Odds locked at challenge creation
    challenger_odds      = Column(Float,   nullable=False)
    challenged_odds      = Column(Float,   nullable=False)
    challenger_moneyline = Column(Integer, nullable=False)
    challenged_moneyline = Column(Integer, nullable=False)
    status               = Column(String,  nullable=False, default="pending")
    expires_at           = Column(DateTime, nullable=False)
    created_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    responded_at         = Column(DateTime, nullable=True)
    # Populated on acceptance
    challenger_bet_id    = Column(Integer, ForeignKey("bets.id", use_alter=True, name="fk_challenger_bet_id"), nullable=True)
    challenged_bet_id    = Column(Integer, ForeignKey("bets.id", use_alter=True, name="fk_challenged_bet_id"), nullable=True)
    # Projection snapshot taken at challenge creation; used for staleness detection on accept
    projection_snapshot  = Column(String,  nullable=True)
    staleness_warning    = Column(Integer, nullable=False, default=0)  # 1 if any proj shifted >10%
    # Counter-offer fields (null until a counter is made)
    countered_amount     = Column(Float,    nullable=True)
    countered_at         = Column(DateTime, nullable=True)

    challenger_team  = relationship("Team", foreign_keys=[challenger_team_id])
    challenged_team  = relationship("Team", foreign_keys=[challenged_team_id])
    player           = relationship("Player", foreign_keys=[player_id])
    challenger_bet   = relationship("Bet",    foreign_keys=[challenger_bet_id])
    challenged_bet   = relationship("Bet",    foreign_keys=[challenged_bet_id])


class BeefStarter(Base):
    """Snapshot of both teams' staked players at challenge-issue time.
    Used by the per-bet kickoff lock to determine when each GM is locked."""
    __tablename__ = "beef_starters"
    # beef_challenge_id must lead the tuple — the read-side query at
    # beef_engine.py:758 filters on beef_challenge_id alone, so it needs
    # that column first to use this constraint's index for the lookup.
    __table_args__ = (UniqueConstraint("beef_challenge_id", "team_id", "player_id"),)

    id                = Column(Integer, primary_key=True, autoincrement=True)
    beef_challenge_id = Column(Integer, ForeignKey("beef_challenges.id"), nullable=False)
    team_id           = Column(Integer, ForeignKey("teams.id"),           nullable=False)
    player_id         = Column(Integer, ForeignKey("players.id"),         nullable=False)
    nfl_team          = Column(String(4), nullable=True)

    beef_challenge = relationship("BeefChallenge", foreign_keys=[beef_challenge_id])
    team           = relationship("Team",          foreign_keys=[team_id])
    player         = relationship("Player",        foreign_keys=[player_id])


class FeedEvent(Base):
    __tablename__ = "feed_events"
    __table_args__ = (
        Index("ix_feed_league_created", "league_id", "created_at"),
    )

    id             = Column(Integer,  primary_key=True, autoincrement=True)
    league_id      = Column(Integer,  ForeignKey("leagues.id"), nullable=False)
    week           = Column(Integer,  nullable=False)
    event_type     = Column(String,   nullable=False)
    actor_team_id  = Column(Integer,  ForeignKey("teams.id"), nullable=True)
    target_team_id = Column(Integer,  ForeignKey("teams.id"), nullable=True)
    challenge_id   = Column(Integer,  ForeignKey("beef_challenges.id"), nullable=True)
    bet_id         = Column(Integer,  ForeignKey("bets.id"), nullable=True)
    headline       = Column(String,   nullable=False)
    trash_talk     = Column(String,   nullable=True)
    created_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    actor_team  = relationship("Team", foreign_keys=[actor_team_id])
    target_team = relationship("Team", foreign_keys=[target_team_id])


class User(Base):
    """One account per GM, linked to their team by email. Commissioner has elevated access."""
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('gm','commissioner')", name="ck_user_role"),
    )

    id                = Column(Integer,  primary_key=True, autoincrement=True)
    email             = Column(String,   nullable=False, unique=True)
    hashed_password   = Column(String,   nullable=False)
    team_id           = Column(Integer,  ForeignKey("teams.id"), nullable=True, unique=True)
    role              = Column(String,   nullable=False, default="gm")
    is_active         = Column(Integer,  nullable=False, default=1)
    buy_in_paid       = Column(Integer,  nullable=False, default=0)   # 1 once Stripe buy-in confirmed
    stripe_account_id = Column(String,   nullable=True)               # Connect Standard acct for payouts
    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_login_at     = Column(DateTime, nullable=True)

    team = relationship("Team", back_populates="user")


# ── Stripe / Payments ─────────────────────────────────────────────────────────

class LeagueTreasury(Base):
    """One row per league — holds buy-in config and running totals."""
    __tablename__ = "league_treasury"

    id                    = Column(Integer,  primary_key=True, autoincrement=True)
    league_id             = Column(Integer,  ForeignKey("leagues.id"), nullable=False, unique=True)
    buy_in_amount_cents   = Column(Integer,  nullable=False, default=0)
    payout_split_json     = Column(String,   nullable=False, default="[60,30,10]")
    total_collected_cents = Column(Integer,  nullable=False, default=0)
    total_paid_out_cents  = Column(Integer,  nullable=False, default=0)
    season_payout_done    = Column(Integer,  nullable=False, default=0)
    created_at            = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at            = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    league = relationship("League")


class BuyInRecord(Base):
    """One row per team per season — tracks Stripe payment link + confirmation."""
    __tablename__ = "buy_in_records"
    __table_args__ = (
        CheckConstraint("status IN ('pending','paid','refunded')", name="ck_buyin_status"),
    )

    id                       = Column(Integer,  primary_key=True, autoincrement=True)
    league_id                = Column(Integer,  ForeignKey("leagues.id"), nullable=False)
    team_id                  = Column(Integer,  ForeignKey("teams.id"),   nullable=False)
    user_id                  = Column(Integer,  ForeignKey("users.id"),   nullable=True)
    amount_cents             = Column(Integer,  nullable=False)
    status                   = Column(String,   nullable=False, default="pending")
    stripe_payment_link_id   = Column(String,   nullable=True)
    stripe_payment_link_url  = Column(String,   nullable=True)
    stripe_session_id        = Column(String,   nullable=True)
    stripe_payment_intent_id = Column(String,   nullable=True)
    paid_at                  = Column(DateTime, nullable=True)
    created_at               = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    team = relationship("Team")
    user = relationship("User")


class PayoutRecord(Base):
    """One row per winner per season payout execution."""
    __tablename__ = "payout_records"
    __table_args__ = (
        CheckConstraint("status IN ('pending','sent','failed')", name="ck_payout_status"),
    )

    id                       = Column(Integer,  primary_key=True, autoincrement=True)
    league_id                = Column(Integer,  ForeignKey("leagues.id"), nullable=False)
    team_id                  = Column(Integer,  ForeignKey("teams.id"),   nullable=False)
    user_id                  = Column(Integer,  ForeignKey("users.id"),   nullable=True)
    place                    = Column(Integer,  nullable=False)           # 1, 2, 3
    amount_cents             = Column(Integer,  nullable=False)
    pct                      = Column(Integer,  nullable=False)           # e.g. 60
    status                   = Column(String,   nullable=False, default="pending")
    stripe_transfer_id       = Column(String,   nullable=True)
    stripe_connected_account = Column(String,   nullable=True)
    sent_at                  = Column(DateTime, nullable=True)
    created_at               = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    team = relationship("Team")
    user = relationship("User")


class StripeAuditLog(Base):
    """Append-only ledger of every Stripe API call and webhook event."""
    __tablename__ = "stripe_audit_log"
    __table_args__ = (
        Index("ix_stripe_audit_league_created", "league_id", "created_at"),
    )

    id                   = Column(Integer,  primary_key=True, autoincrement=True)
    league_id            = Column(Integer,  ForeignKey("leagues.id"), nullable=True)
    team_id              = Column(Integer,  ForeignKey("teams.id"),   nullable=True)
    event_type           = Column(String,   nullable=False)
    stripe_object        = Column(String,   nullable=True)
    amount_cents         = Column(Integer,  nullable=True)
    description          = Column(String,   nullable=True)
    raw_response         = Column(String,   nullable=True)
    created_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    performed_by_user_id = Column(Integer,  ForeignKey("users.id"), nullable=True)


# ── FAAB Wallet ───────────────────────────────────────────────────────────────

class FaabConfig(Base):
    """One row per league — commissioner configures opening balances and transfer rules."""
    __tablename__ = "faab_config"

    id                   = Column(Integer,  primary_key=True, autoincrement=True)
    league_id            = Column(Integer,  ForeignKey("leagues.id"), nullable=False, unique=True)
    opening_bet          = Column(Float,    nullable=False, default=50.00)
    opening_waiver       = Column(Float,    nullable=False, default=100.00)
    allow_bet_to_waiver  = Column(Integer,  nullable=False, default=1)   # 1 = allowed
    allow_waiver_to_bet  = Column(Integer,  nullable=False, default=1)   # 1 = allowed
    season_initialized   = Column(Integer,  nullable=False, default=0)   # 1 after init_season_wallets
    created_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    league = relationship("League")


class FaabWallet(Base):
    """Per-team FAAB wallet — waiver budget + bet-frozen flag."""
    __tablename__ = "faab_wallets"

    id                   = Column(Integer,  primary_key=True, autoincrement=True)
    team_id              = Column(Integer,  ForeignKey("teams.id"),    nullable=False, unique=True)
    league_id            = Column(Integer,  ForeignKey("leagues.id"),  nullable=False)
    waiver_balance       = Column(Float,    nullable=False, default=0.0)
    pending_waiver_topup = Column(Float,    nullable=False, default=0.0)  # queued for Tuesday
    bet_frozen           = Column(Integer,  nullable=False, default=0)    # 1 = frozen
    created_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    team   = relationship("Team")
    league = relationship("League")


class FaabTransaction(Base):
    """FAAB-specific audit trail — covers top-ups, transfers, bids, and alerts."""
    __tablename__ = "faab_transactions"
    __table_args__ = (
        CheckConstraint(
            "type IN ("
            "'opening_credit','topup_bet','topup_waiver',"
            "'transfer_bet_to_waiver','transfer_waiver_to_bet',"
            "'waiver_bid','waiver_refund','funding_alert')",
            name="ck_faab_tx_type",
        ),
        CheckConstraint(
            "status IN ('pending','applied','cancelled','failed')",
            name="ck_faab_tx_status",
        ),
        Index("ix_faab_tx_team_created", "team_id", "created_at"),
    )

    id               = Column(Integer,  primary_key=True, autoincrement=True)
    league_id        = Column(Integer,  ForeignKey("leagues.id"), nullable=False)
    team_id          = Column(Integer,  ForeignKey("teams.id"),   nullable=False)
    type             = Column(String,   nullable=False)
    amount           = Column(Float,    nullable=False, default=0.0)
    wallet_from      = Column(String,   nullable=True)   # "bet" | "waiver" | "stripe"
    wallet_to        = Column(String,   nullable=True)   # "bet" | "waiver"
    status           = Column(String,   nullable=False,  default="applied")
    note             = Column(String,   nullable=True)
    stripe_link_id   = Column(String,   nullable=True)
    stripe_link_url  = Column(String,   nullable=True)
    stripe_session_id = Column(String,  nullable=True)
    apply_on         = Column(DateTime, nullable=True)   # NULL = immediate; set for Tuesday queue
    applied_at       = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    team   = relationship("Team")
    league = relationship("League")


# ── Commissioner Rules ────────────────────────────────────────────────────────

class CommissionerRule(Base):
    """Natural-language rule parsed by AI into a structured spec."""
    __tablename__ = "commissioner_rules"
    __table_args__ = (
        CheckConstraint("rule_type IN ('weekly','end_of_season')",       name="ck_rule_type"),
        CheckConstraint("effect_type IN ('obligation','payout')",         name="ck_rule_effect"),
        CheckConstraint("status IN ('draft','active','paused','completed')", name="ck_rule_status"),
        CheckConstraint(
            "target IN ('biggest_loss_margin','missed_lineup','points_leader','commissioner_manual')",
            name="ck_rule_target",
        ),
        Index("ix_rule_league_status", "league_id", "status"),
    )

    id                     = Column(Integer,  primary_key=True, autoincrement=True)
    league_id              = Column(Integer,  ForeignKey("leagues.id"), nullable=False)
    created_by_user_id     = Column(Integer,  ForeignKey("users.id"),   nullable=True)
    raw_text               = Column(String,   nullable=False)
    rule_type              = Column(String,   nullable=False)
    effect_type            = Column(String,   nullable=False)
    target                 = Column(String,   nullable=False)
    amount                 = Column(Float,    nullable=False, default=0.0)
    has_escrow             = Column(Integer,  nullable=False, default=0)
    escrow_release_trigger = Column(String,   nullable=True)
    escrow_release_target  = Column(String,   nullable=True)
    ai_interpretation      = Column(String,   nullable=True)
    ai_raw_response        = Column(String,   nullable=True)
    ai_model_used          = Column(String,   nullable=True)
    status                 = Column(String,   nullable=False, default="draft")
    week_start             = Column(Integer,  nullable=True)
    week_end               = Column(Integer,  nullable=True)
    created_at             = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at             = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    activated_at           = Column(DateTime, nullable=True)

    league     = relationship("League")
    created_by = relationship("User", foreign_keys=[created_by_user_id])


class EscrowAccount(Base):
    """Mid-season holding bucket for rule-collected funds."""
    __tablename__ = "escrow_accounts"
    __table_args__ = (
        CheckConstraint("status IN ('open','released','refunded')",       name="ck_escrow_status"),
        CheckConstraint("release_trigger IN ('end_of_season','manual')",  name="ck_escrow_trigger"),
    )

    id               = Column(Integer,  primary_key=True, autoincrement=True)
    league_id        = Column(Integer,  ForeignKey("leagues.id"),            nullable=False)
    rule_id          = Column(Integer,  ForeignKey("commissioner_rules.id"), nullable=False, unique=True)
    name             = Column(String,   nullable=False)
    balance          = Column(Float,    nullable=False, default=0.0)
    status           = Column(String,   nullable=False, default="open")
    release_trigger  = Column(String,   nullable=False, default="manual")
    release_team_id  = Column(Integer,  ForeignKey("teams.id"), nullable=True)
    released_at      = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    league       = relationship("League")
    rule         = relationship("CommissionerRule")
    release_team = relationship("Team", foreign_keys=[release_team_id])


class EscrowTransaction(Base):
    """Append-only ledger of funds flowing in/out of each escrow account."""
    __tablename__ = "escrow_transactions"
    __table_args__ = (
        CheckConstraint("direction IN ('in','out')", name="ck_escrow_tx_dir"),
        Index("ix_escrow_tx_escrow_created", "escrow_id", "created_at"),
    )

    id          = Column(Integer,  primary_key=True, autoincrement=True)
    escrow_id   = Column(Integer,  ForeignKey("escrow_accounts.id"), nullable=False)
    league_id   = Column(Integer,  ForeignKey("leagues.id"),         nullable=False)
    team_id     = Column(Integer,  ForeignKey("teams.id"),           nullable=False)
    direction   = Column(String,   nullable=False)
    amount      = Column(Float,    nullable=False)
    description = Column(String,   nullable=True)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    escrow = relationship("EscrowAccount")
    team   = relationship("Team")


class RuleExecution(Base):
    """One row per team per rule trigger — tracks collection and payout."""
    __tablename__ = "rule_executions"
    __table_args__ = (
        CheckConstraint("effect_type IN ('obligation','payout')",         name="ck_ruleexec_effect"),
        CheckConstraint(
            "status IN ('pending','collected','held_in_escrow','paid_out','waived','failed')",
            name="ck_ruleexec_status",
        ),
        Index("ix_ruleexec_rule_week", "rule_id", "week"),
    )

    id          = Column(Integer,  primary_key=True, autoincrement=True)
    rule_id     = Column(Integer,  ForeignKey("commissioner_rules.id"), nullable=False)
    league_id   = Column(Integer,  ForeignKey("leagues.id"),            nullable=False)
    week        = Column(Integer,  nullable=True)
    team_id     = Column(Integer,  ForeignKey("teams.id"),              nullable=False)
    effect_type = Column(String,   nullable=False)
    amount      = Column(Float,    nullable=False)
    description = Column(String,   nullable=True)
    status      = Column(String,   nullable=False, default="pending")
    escrow_id   = Column(Integer,  ForeignKey("escrow_accounts.id"),    nullable=True)
    executed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    settled_at  = Column(DateTime, nullable=True)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    rule   = relationship("CommissionerRule")
    team   = relationship("Team")
    escrow = relationship("EscrowAccount")


class RuleAuditLog(Base):
    """Append-only log of every rule lifecycle event and AI call."""
    __tablename__ = "rule_audit_log"
    __table_args__ = (
        Index("ix_rule_audit_league_created", "league_id", "created_at"),
    )

    id                   = Column(Integer,  primary_key=True, autoincrement=True)
    rule_id              = Column(Integer,  ForeignKey("commissioner_rules.id"), nullable=True)
    league_id            = Column(Integer,  ForeignKey("leagues.id"),            nullable=True)
    performed_by_user_id = Column(Integer,  ForeignKey("users.id"),              nullable=True)
    event_type           = Column(String,   nullable=False)
    description          = Column(String,   nullable=True)
    ai_model             = Column(String,   nullable=True)
    ai_latency_ms        = Column(Integer,  nullable=True)
    raw_data             = Column(String,   nullable=True)
    created_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    rule         = relationship("CommissionerRule")
    performed_by = relationship("User", foreign_keys=[performed_by_user_id])


# ── Tuesday Sync ─────────────────────────────────────────────────────────────

class TuesdaySyncRun(Base):
    """One row per Tuesday automation run — full execution log."""
    __tablename__ = "tuesday_sync_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','completed','completed_with_errors','failed')",
            name="ck_sync_status",
        ),
        Index("ix_sync_league_started", "league_id", "started_at"),
    )

    id          = Column(Integer,  primary_key=True, autoincrement=True)
    run_id      = Column(String,   nullable=False, unique=True)
    league_id   = Column(Integer,  ForeignKey("leagues.id"), nullable=False)
    week        = Column(Integer,  nullable=False)
    status      = Column(String,   nullable=False, default="running")
    mock_mode   = Column(Integer,  nullable=False, default=0)
    steps_json  = Column(String,   nullable=True)   # JSON array of step results
    error_count = Column(Integer,  nullable=False, default=0)
    emails_sent = Column(Integer,  nullable=False, default=0)
    started_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime, nullable=True)

    league = relationship("League")


# ── Weekly Wrap-Up ────────────────────────────────────────────────────────────

class WeeklyWrapUp(Base):
    """One row per generated weekly wrap-up — stores league edition + AI metadata."""
    __tablename__ = "weekly_wrap_ups"
    __table_args__ = (
        CheckConstraint("status IN ('draft','ready','sent')", name="ck_wrapup_status"),
        Index("ix_wrapup_league_week", "league_id", "week"),
    )

    id                  = Column(Integer,  primary_key=True, autoincrement=True)
    run_id              = Column(String,   nullable=False, unique=True)
    league_id           = Column(Integer,  ForeignKey("leagues.id"), nullable=False)
    week                = Column(Integer,  nullable=False)
    status              = Column(String,   nullable=False, default="draft")
    league_body         = Column(String,   nullable=True)   # league edition text
    roast_beef          = Column(String,   nullable=True)   # extracted roast section
    ai_model_used       = Column(String,   nullable=True)
    ai_latency_ms       = Column(Integer,  nullable=True)
    commissioner_edited = Column(Integer,  nullable=False, default=0)
    created_at          = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at          = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    sent_at             = Column(DateTime, nullable=True)

    league    = relationship("League")
    gm_editions = relationship("WrapUpGmEdition", back_populates="wrap_up")


class WrapUpGmEdition(Base):
    """Per-GM personalized edition of the weekly wrap-up."""
    __tablename__ = "wrap_up_gm_editions"
    __table_args__ = (
        Index("ix_gmedition_wrapup_team", "wrap_up_id", "team_id"),
    )

    id                  = Column(Integer,  primary_key=True, autoincrement=True)
    wrap_up_id          = Column(Integer,  ForeignKey("weekly_wrap_ups.id"), nullable=False)
    league_id           = Column(Integer,  ForeignKey("leagues.id"),         nullable=False)
    team_id             = Column(Integer,  ForeignKey("teams.id"),           nullable=False)
    week                = Column(Integer,  nullable=False)
    body                = Column(String,   nullable=True)
    status_tag          = Column(String,   nullable=True)   # contender|bubble|spoiler|chaos
    playoff_prob_change = Column(Float,    nullable=True)
    sent                = Column(Integer,  nullable=False, default=0)
    sent_at             = Column(DateTime, nullable=True)
    created_at          = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    wrap_up = relationship("WeeklyWrapUp", back_populates="gm_editions")
    team    = relationship("Team")
    league  = relationship("League")


# ── Power Rankings ────────────────────────────────────────────────────────────

class PowerRanking(Base):
    """Per-team per-week ranking snapshot across on-field, betting, and waiver dimensions."""
    __tablename__ = "power_rankings"
    __table_args__ = (
        CheckConstraint(
            "status_tag IN ('contender','bubble','spoiler','chaos')",
            name="ck_pr_status_tag",
        ),
        UniqueConstraint("league_id", "week", "team_id", name="uq_pr_league_week_team"),
        Index("ix_pr_league_week", "league_id", "week"),
    )

    id                   = Column(Integer,  primary_key=True, autoincrement=True)
    league_id            = Column(Integer,  ForeignKey("leagues.id"), nullable=False)
    week                 = Column(Integer,  nullable=False)
    team_id              = Column(Integer,  ForeignKey("teams.id"),   nullable=False)

    # On-field dimension
    on_field_rank        = Column(Integer,  nullable=False)
    on_field_score       = Column(Float,    nullable=False, default=0.0)   # normalized 0–1
    wins                 = Column(Integer,  nullable=False, default=0)
    losses               = Column(Integer,  nullable=False, default=0)
    points_for           = Column(Float,    nullable=False, default=0.0)
    points_against       = Column(Float,    nullable=False, default=0.0)
    sos                  = Column(Float,    nullable=False, default=0.0)   # avg opp win-rate

    # Betting dimension
    betting_rank         = Column(Integer,  nullable=False)
    betting_score        = Column(Float,    nullable=False, default=0.0)
    bet_wins             = Column(Integer,  nullable=False, default=0)
    bet_losses           = Column(Integer,  nullable=False, default=0)
    roi                  = Column(Float,    nullable=False, default=0.0)   # (payout-staked)/staked
    best_win_amount      = Column(Float,    nullable=False, default=0.0)
    worst_loss_amount    = Column(Float,    nullable=False, default=0.0)
    bet_streak           = Column(Integer,  nullable=False, default=0)     # +n win / -n lose streak

    # Waiver wire dimension
    waiver_rank          = Column(Integer,  nullable=False)
    waiver_score         = Column(Float,    nullable=False, default=0.0)
    waiver_dollars_spent = Column(Float,    nullable=False, default=0.0)
    waiver_pts_added     = Column(Float,    nullable=False, default=0.0)
    pts_per_dollar       = Column(Float,    nullable=False, default=0.0)

    # Composite GM Rating
    composite_rank       = Column(Integer,  nullable=False)
    composite_score      = Column(Float,    nullable=False, default=0.0)   # weighted avg 0–1
    rank_change          = Column(Integer,  nullable=True)                  # +n up / -n down vs prev week
    status_tag           = Column(String,   nullable=False, default="spoiler")

    created_at           = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    team   = relationship("Team")
    league = relationship("League")


# ── Pool (Mode 3) ─────────────────────────────────────────────────────────────

class PoolConfig(Base):
    """Commissioner configures the weekly pool for a league."""
    __tablename__ = "pool_config"

    id                      = Column(Integer, primary_key=True, autoincrement=True)
    league_id               = Column(Integer, ForeignKey("leagues.id"), unique=True)
    weekly_entry            = Column(Float,   default=10.0)
    worst_beat_rollover     = Column(Boolean, default=True)
    created_at              = Column(DateTime(timezone=True),
                                     default=lambda: datetime.now(timezone.utc))

    league = relationship("League")


class PoolPrediction(Base):
    """Per-GM worst-beat prediction for a week (one per team per week)."""
    __tablename__ = "pool_predictions"
    __table_args__ = (
        UniqueConstraint("league_id", "team_id", "week", name="uq_pool_pred_team_week"),
    )

    id                           = Column(Integer, primary_key=True, autoincrement=True)
    league_id                    = Column(Integer, ForeignKey("leagues.id"))
    team_id                      = Column(Integer, ForeignKey("teams.id"))
    week                         = Column(Integer)
    predicted_worst_beat_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    submitted_at                 = Column(DateTime(timezone=True))

    team             = relationship("Team", foreign_keys=[team_id])
    predicted_team   = relationship("Team", foreign_keys=[predicted_worst_beat_team_id])
    league           = relationship("League")


class PoolPot(Base):
    """One row per league per week — tracks collection and settlement state."""
    __tablename__ = "pool_pots"
    __table_args__ = (
        UniqueConstraint("league_id", "week", name="uq_pool_pot_league_week"),
    )

    id                         = Column(Integer,  primary_key=True, autoincrement=True)
    league_id                  = Column(Integer,  ForeignKey("leagues.id"))
    week                       = Column(Integer)
    worst_beat_rollover_amount = Column(Float,   default=0.0)
    entries_collected          = Column(Boolean,  default=False)
    total_pot                  = Column(Float,   nullable=True)
    settled                    = Column(Boolean,  default=False)
    settled_at                 = Column(DateTime(timezone=True), nullable=True)
    lock_time                  = Column(DateTime(timezone=True), nullable=True)

    league = relationship("League")


class WeekSettlement(Base):
    """One row per league per week — tracks whether settle_week() has already
    run for that week. Independent of Bet.status; this is the run-once guard
    for bet settlement, modeled on PoolPot's collection/settlement pattern."""
    __tablename__ = "week_settlements"
    __table_args__ = (
        UniqueConstraint("league_id", "week", name="uq_week_settlement_league_week"),
    )

    id         = Column(Integer,  primary_key=True, autoincrement=True)
    league_id  = Column(Integer,  ForeignKey("leagues.id"))
    week       = Column(Integer)
    settled    = Column(Boolean,  default=False)
    settled_at = Column(DateTime(timezone=True), nullable=True)

    league = relationship("League")


class PoolBetPick(Base):
    """One pick per team per bet_type per week (all 4 pool bets)."""
    __tablename__ = "pool_bet_picks"
    __table_args__ = (
        UniqueConstraint("league_id", "team_id", "bet_type", "week",
                         name="uq_pool_bet_pick_team_type_week"),
    )

    id             = Column(Integer,  primary_key=True, autoincrement=True)
    league_id      = Column(Integer,  ForeignKey("leagues.id"), nullable=False)
    team_id        = Column(Integer,  ForeignKey("teams.id"),   nullable=False)
    bet_type       = Column(String,   nullable=False)
    picked_team_id = Column(Integer,  ForeignKey("teams.id"),   nullable=True)
    week           = Column(Integer,  nullable=False)
    submitted_at   = Column(DateTime(timezone=True), nullable=True)

    team        = relationship("Team", foreign_keys=[team_id])
    picked_team = relationship("Team", foreign_keys=[picked_team_id])
    league      = relationship("League")


# ── NFL Schedule ──────────────────────────────────────────────────────────────

class NflSchedule(Base):
    """One row per NFL game — season/week/matchup + kickoff time.  Populated by
    the ESPN schedule connector; keyed on (season, week, home_team, away_team).
    No foreign keys into league/team tables — this is raw NFL data, not fantasy
    league data.
    """
    __tablename__ = "nfl_schedule"
    __table_args__ = (
        UniqueConstraint("season", "week", "home_team", "away_team",
                         name="uq_nfl_schedule_game"),
    )

    id             = Column(Integer,  primary_key=True, autoincrement=True)
    season         = Column(Integer,  nullable=False)
    week           = Column(Integer,  nullable=False)
    home_team      = Column(String,   nullable=False)   # ESPN team abbreviation, e.g. "KC"
    away_team      = Column(String,   nullable=False)   # ESPN team abbreviation, e.g. "DET"
    kickoff_utc    = Column(DateTime, nullable=False)
    last_synced_at = Column(DateTime, nullable=False,
                            default=lambda: datetime.now(timezone.utc))


# ── Player ID Crosswalk ───────────────────────────────────────────────────────

class PlayerIdMap(Base):
    """Cross-platform player ID crosswalk sourced from DynastyProcess db_playerids.csv.
    Keyed on fantasypros_id (only rows with a real FP ID are upserted).
    Used to resolve a fantasy player's current NFL team for per-game kickoff locking.
    """
    __tablename__ = "player_id_map"

    fantasypros_id = Column(String,   primary_key=True)
    yahoo_id       = Column(String,   nullable=True)
    name           = Column(String,   nullable=False)
    position       = Column(String,   nullable=True)
    team           = Column(String,   nullable=True)   # NFL team abbreviation, e.g. "KC"; "FA" = free agent
    last_updated   = Column(DateTime, nullable=False,
                            default=lambda: datetime.now(timezone.utc))


# ── Public API ────────────────────────────────────────────────────────────────

def create_all() -> None:
    Base.metadata.create_all(engine)


def drop_all() -> None:
    Base.metadata.drop_all(engine)


# Position scoring parameters (PPR, 2024 season)
_POS_PARAMS: dict[str, dict] = {
    "QB":   {"mu": 22.0, "sigma": 7.0, "lo":  5.0, "hi": 48.0},
    "RB":   {"mu": 12.5, "sigma": 6.0, "lo":  1.0, "hi": 40.0},
    "WR":   {"mu": 11.5, "sigma": 6.0, "lo":  0.5, "hi": 40.0},
    "TE":   {"mu":  8.5, "sigma": 5.0, "lo":  0.5, "hi": 28.0},
    "FLEX": {"mu": 11.0, "sigma": 6.0, "lo":  0.5, "hi": 38.0},
    "K":    {"mu":  8.5, "sigma": 3.0, "lo":  2.0, "hi": 19.0},
    "DEF":  {"mu":  7.5, "sigma": 4.0, "lo":  0.0, "hi": 23.0},
}
_SOURCES = ("yahoo", "espn", "fantasypros")


def _pos_actual(pos: str, rng) -> float:
    p = _POS_PARAMS[pos]
    raw = rng.gauss(p["mu"], p["sigma"])
    return round(max(p["lo"], min(p["hi"], raw)), 2)


def seed_from_mock(session: Session | None = None) -> None:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from mock_league import TEAMS as MOCK_TEAMS, SCHEDULE

    close_after = session is None
    if session is None:
        session = SessionLocal()

    try:
        # ── League ────────────────────────────────────────────────────────────
        league = League(season=2024, name="Fantasy Beefs", projection_source="fantasypros")
        session.add(league)
        session.flush()

        session.add(LeagueScoring(
            league_id        = league.id,
            scoring_type     = "half_ppr",
            rec_points       = 0.5,
            pass_td_points   = 5.0,
            rush_td_points   = 6.0,
            rec_td_points    = 6.0,
            bonus_100yd_rush = 0.0,
            bonus_100yd_rec  = 0.0,
        ))

        # ── Teams ─────────────────────────────────────────────────────────────
        # team_map: mock team id (1-10) → Team ORM row
        team_map: dict[int, Team] = {}
        for mt in MOCK_TEAMS:
            team = Team(
                league_id=league.id,
                team_name=mt["name"],
                owner=mt["owner"],
                email=mt["email"],
            )
            session.add(team)
            session.flush()
            team_map[mt["id"]] = team

        # ── Players (deduplicated by name) ────────────────────────────────────
        player_map: dict[str, Player] = {}
        for mt in MOCK_TEAMS:
            for p in mt["roster"]:
                if p["name"] not in player_map:
                    player = Player(name=p["name"], position=p["pos"])
                    session.add(player)
                    session.flush()
                    player_map[p["name"]] = player

        # ── Rosters ───────────────────────────────────────────────────────────
        seen_roster_pairs: set[tuple[int, int]] = set()
        for mt in MOCK_TEAMS:
            team = team_map[mt["id"]]
            for p in mt["roster"]:
                pid = player_map[p["name"]].id
                pair = (team.id, pid)
                if pair not in seen_roster_pairs:
                    session.add(Roster(team_id=team.id, player_id=pid))
                    seen_roster_pairs.add(pair)

        # ── Matchups (all 17 weeks) ───────────────────────────────────────────
        matchup_count = 0
        for week_idx, week_pairs in enumerate(SCHEDULE):
            week = week_idx + 1
            for home_idx, away_idx in week_pairs:
                home_mt   = MOCK_TEAMS[home_idx]
                away_mt   = MOCK_TEAMS[away_idx]
                home_team = team_map[home_mt["id"]]
                away_team = team_map[away_mt["id"]]
                h_score   = home_mt["scores"][week_idx]
                a_score   = away_mt["scores"][week_idx]
                winner    = home_team if h_score > a_score else away_team

                session.add(Matchup(
                    league_id      = league.id,
                    week           = week,
                    home_team_id   = home_team.id,
                    away_team_id   = away_team.id,
                    home_score     = h_score,
                    away_score     = a_score,
                    winner_team_id = winner.id,
                ))
                matchup_count += 1

        # ── Wallets ($1 000 starting balance per team) ────────────────────────
        for team in team_map.values():
            session.add(Wallet(team_id=team.id, balance=1000.0))

        # ── Projections (all players × 17 weeks × 3 sources) ─────────────────
        # Each player has a stable skill modifier derived from their id so
        # the same player is consistently above/below the positional mean.
        import random

        projection_count = 0
        for player in player_map.values():
            skill_rng = random.Random(player.id)          # seeded by player id
            skill     = skill_rng.uniform(0.75, 1.25)    # 0.75–1.25× position mean

            for week in range(1, 18):
                # actual points: position distribution scaled by player skill
                actual_rng   = random.Random(player.id * 1_000 + week)
                actual_pts   = _pos_actual(player.position, actual_rng)
                actual_pts   = round(actual_pts * skill, 2)
                actual_pts   = max(0.0, actual_pts)

                for src_idx, source in enumerate(_SOURCES):
                    proj_rng   = random.Random(player.id * 100_000 + week * 100 + src_idx)
                    variance   = proj_rng.uniform(0.85, 1.15)
                    proj_pts   = round(actual_pts * variance, 2)

                    session.add(Projection(
                        player_id        = player.id,
                        week             = week,
                        season           = 2024,
                        projected_points = proj_pts,
                        actual_points    = actual_pts,
                        source           = source,
                    ))
                    projection_count += 1

        session.commit()

        print(
            f"Seeded  league={league.name!r} season={league.season}\n"
            f"        {len(team_map)} teams  "
            f"{len(player_map)} unique players  "
            f"{len(seen_roster_pairs)} roster slots  "
            f"{matchup_count} matchups  "
            f"{len(team_map)} wallets  "
            f"{projection_count} projections"
        )

    except Exception:
        session.rollback()
        raise
    finally:
        if close_after:
            session.close()


# ── Demo ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    # Fresh DB every run
    drop_all()
    create_all()
    seed_from_mock()

    # Query week 1 matchups back out to verify
    with SessionLocal() as s:
        rows = (
            s.query(Matchup)
             .filter(Matchup.week == 1)
             .order_by(Matchup.id)
             .all()
        )

        print("\nWeek 1 matchups (read back from DB)\n")
        print("┌────┬────────────────────────────┬────────────────────────────┬────────┬────────┬────────────────────────────┐")
        print("│ id │ Home                       │ Away                       │  Home  │  Away  │ Winner                     │")
        print("├────┼────────────────────────────┼────────────────────────────┼────────┼────────┼────────────────────────────┤")
        for m in rows:
            print(
                f"│ {m.id:<2} │ {m.home_team.team_name:<26} │ {m.away_team.team_name:<26} │"
                f" {m.home_score:>6.1f} │ {m.away_score:>6.1f} │ {m.winner.team_name:<26} │"
            )
        print("└────┴────────────────────────────┴────────────────────────────┴────────┴────────┴────────────────────────────┘")

        # Wallet balances
        wallets = s.query(Wallet).join(Team).order_by(Team.id).all()
        print("\nWallets\n")
        print("┌────────────────────────────┬──────────────────────┬──────────────┐")
        print("│ Team                       │ Owner                │ Balance      │")
        print("├────────────────────────────┼──────────────────────┼──────────────┤")
        for w in wallets:
            print(f"│ {w.team.team_name:<26} │ {w.team.owner:<20} │ ${w.balance:>11,.2f} │")
        print("└────────────────────────────┴──────────────────────┴──────────────┘")

        # Projection sample — week 1 starters for Mahomes Alone
        team = s.query(Team).filter_by(team_name="Mahomes Alone").first()
        starters = [r.player for r in team.roster[:9]]
        projs = (
            s.query(Projection)
             .filter(
                 Projection.player_id.in_([p.id for p in starters]),
                 Projection.week   == 1,
                 Projection.season == 2024,
             )
             .order_by(Projection.player_id, Projection.source)
             .all()
        )
        print("\nProjections — Mahomes Alone starters, week 1\n")
        print("┌────────────────────────┬──────┬─────────────┬──────────┬──────────┬────────────┐")
        print("│ Player                 │ Pos  │ Source      │  Actual  │  Proj'd  │   Delta    │")
        print("├────────────────────────┼──────┼─────────────┼──────────┼──────────┼────────────┤")
        for pr in projs:
            delta = pr.projected_points - pr.actual_points
            print(
                f"│ {pr.player.name:<22} │ {pr.player.position:<4} │ {pr.source:<11} │"
                f" {pr.actual_points:>8.2f} │ {pr.projected_points:>8.2f} │ {delta:>+10.2f} │"
            )
        print("└────────────────────────┴──────┴─────────────┴──────────┴──────────┴────────────┘")
