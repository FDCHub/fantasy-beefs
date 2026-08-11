from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DDL,
    DateTime,
    event,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from db.engine_factory import get_engine  # FR-VAL10-af: canonical engine control surface

# ── Engine / session ──────────────────────────────────────────────────────────

_ENV_URL = os.environ.get("DATABASE_URL", "")
if _ENV_URL:
    # Railway provides postgres:// (legacy Heroku format); SQLAlchemy 1.4+ requires postgresql://
    DB_URL = _ENV_URL.replace("postgres://", "postgresql://", 1)
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "fantasy.db")
    DB_URL  = f"sqlite:///{DB_PATH}"

engine       = get_engine(DB_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


# ── Base ──────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Tables ────────────────────────────────────────────────────────────────────

class League(Base):
    __tablename__ = "leagues"
    __table_args__ = (
        # B6 §2.1 — the editable pre-activation cap multiplier. Only the five
        # certified stops on the Discrete-Stop ladder are representable; the
        # CHECK is the outer of two guards, the inner being ck_lstc_multiplier_bps
        # on the frozen snapshot. Both are needed: this one stops a bad value
        # ever being set, that one stops a bad value ever being frozen.
        CheckConstraint(
            "topoff_cap_multiplier_bps IN (0, 5000, 10000, 15000, 20000)",
            name="ck_leagues_topoff_multiplier_bps",
        ),
        # S6-R1 — one provider league key maps to at most one internal League.
        # NULLs are distinct under both PostgreSQL and SQLite, so any number of
        # provider-less leagues coexist; two leagues claiming the same Yahoo
        # league key is the conflicting-identity case and is refused by the DB.
        UniqueConstraint("provider", "provider_league_key",
                         name="uq_leagues_provider_key"),
    )

    id                = Column(Integer, primary_key=True, autoincrement=True)
    season            = Column(Integer, nullable=False)
    name              = Column(String,  nullable=False)
    projection_source = Column(String,  nullable=False, default="fantasypros")
    # B1-12 — the league's own Discrete-Stop Economy Table selector,
    # independent of LeagueTreasury. Nullable: an unconfigured league falls
    # back to the default stop (weekly_min_cents=1000) rather than erroring —
    # this must never be a hard requirement the way LeagueTreasury was.
    economy_stop_weekly_min_cents = Column(Integer, nullable=True)
    # B2, Finding 5.3 — explicit, commissioner-set activation for the buy-in
    # gate, independent of LeagueTreasury. Default False matches the real
    # current behavior of every league in production today (the old gate
    # already went inactive under B1 once LeagueTreasury stopped being
    # written to) — this migration changes nothing for existing leagues.
    buyin_enforcement_active = Column(Boolean, nullable=False, default=False)
    # B6 §2.1 — BAB Top-Off cap multiplier in basis points, EDITABLE ONLY
    # BEFORE SEASON ACTIVATION. This is the commissioner's dial, never a
    # money-path read: activation copies it once into
    # league_season_topoff_config and every later approval reads THAT row
    # (§2.6, invariant 29). Changing this column after activation is inert by
    # design — it cannot retroactively move an activated season's cap, and an
    # activation replay against a changed value is a CONFLICT, not a replay
    # (§2.5). Default 10000 bps = 100% of the Wallet allocation.
    #
    # server_default, not just default: Column(default=…) is CLIENT-side, so
    # create_all would emit a bare NOT NULL while the Group F migration's DDL
    # emits DEFAULT 10000, giving one table two disagreeing schema sources.
    topoff_cap_multiplier_bps = Column(Integer, nullable=False,
                                       default=10000, server_default=text("10000"))
    # B6 §4.6 — the season-close boundary. NULL means the season is OPEN;
    # non-NULL means it closed AT THAT INSTANT. The timestamp is BOTH the flag
    # and the record, which is why there is deliberately no boolean, no enum and
    # no status string beside it: a second representation of "closed" could
    # disagree with this one.
    #
    # NEVER RETURNED TO NULL BY ANY PATH (invariant 33). Reopening is prohibited
    # outright — not by a route, not by an admin function, not by the writer
    # itself — so no reopen field exists to make it representable.
    #
    # economy/season_close.py holds the ONLY writer, which takes the League row
    # FOR UPDATE and writes this column once (§9.2). Every other B6 path READS
    # it and never writes it (§9.1).
    #
    # No CHECK, no index, no server_default: §4.6 specifies a bare nullable
    # DateTime, and NULL is already the default for one.
    season_closed_at = Column(DateTime, nullable=True)
    # Pool POR Rev1.3 §9 — the governing season boundary, Yahoo-derived, held on
    # League. Both are RULED and their READER IS UNBUILT (POR §12 item 5, Scope
    # §J blocker 5): the Yahoo settings reader that populates them is Sprint 6
    # work. Nullable is therefore the correct state today, and the governed
    # fallbacks — season_final_week 17, playoff_start_week 15 — live in
    # betting/pool_season_boundary.py rather than as column defaults, so a NULL
    # stays visibly unpopulated instead of masquerading as a measured value.
    #
    # These exist to kill the hardcoded 14. POR §9: "The hardcoded week 14 is
    # implementation debt and is not product authority." Rollover expiry fires
    # at season_final_week; the no-repeat regular-season rule applies below
    # playoff_start_week.
    season_final_week   = Column(Integer, nullable=True)
    playoff_start_week  = Column(Integer, nullable=True)
    # ── Sprint 8 P4C-3: the provider's own current week ───────────────────────
    #
    # WHY THIS COLUMN EXISTS. `ProviderLeague.current_week` has always been
    # parsed from the Yahoo payload and carried through the DTO, but it was used
    # for exactly one thing — the §6 ingestion horizon in providers/yahoo/
    # persist.py — and then dropped. Nothing persisted it, so no read route
    # could serve it, and every production surface that needed "which week is
    # it" fell back to a hard-coded 5.
    #
    # The source was never missing; only the storage was. This records the
    # provider's statement so the application can stop guessing.
    #
    # NULLABLE, and NULL is meaningful: it means no provider refresh has ever
    # stated a week for this league. Surfaces render that as unresolved rather
    # than substituting a number — a default here would be the hard-coded 5
    # again, wearing a column name.
    provider_current_week = Column(Integer, nullable=True)
    # ── Sprint 6 provider identity (S6-R1) ────────────────────────────────────
    #
    # The provider-native stable league identity. `provider` names the gateway
    # ("yahoo"); `provider_league_key` is that provider's own stable key for this
    # league — for Yahoo the full compound league key "461.l.488800", never the
    # bare "488800". The game segment is what scopes the key to a season, and a
    # bare league number would collide the moment the same league renews under a
    # new game_id.
    #
    # NULLABLE because a league may legitimately have no provider (fixtures,
    # local leagues). NULL means "no provider identity", which the resolver
    # treats as unresolvable and fails closed on — it is never a wildcard.
    provider            = Column(String, nullable=True)
    provider_league_key = Column(String, nullable=True)

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
    __table_args__ = (
        # S6-R1 — the provider-native stable team identity, and the ONLY
        # authoritative one. Unique per (provider, key): one Yahoo team is one
        # internal Team, forever, no matter how many times it is renamed.
        UniqueConstraint("provider", "provider_team_key",
                         name="uq_teams_provider_key"),
        # One provider team per league is a second, independent statement: it
        # stops the same league accumulating two rows for one provider team if
        # the compound key were ever assembled differently by two callers.
        UniqueConstraint("league_id", "provider_team_key",
                         name="uq_teams_league_provider_key"),
        # email is NOT identity (S6-R1). It keeps a plain non-unique index for
        # the lookups notifications/ does, and nothing more.
        Index("ix_teams_email", "email"),
    )

    id        = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    team_name = Column(String,  nullable=False)
    owner     = Column(String,  nullable=False)
    # ── NOT AN IDENTIFIER (S6-R1) ─────────────────────────────────────────────
    #
    # Was `unique=True` through Sprint 5, which encoded two mistakes at once.
    # First, the season seed smuggled Yahoo identity through this column as
    # 'yahoo-team-{id}@fantasy-beefs.local' and db/team_resolver.py parsed it
    # back out — making a MANAGER EMAIL the load-bearing provider identity, the
    # exact thing S6-R1 forbids. Second, global uniqueness made it impossible
    # for one manager to hold a team in two leagues, which is ordinary product
    # behavior and not something an incidental contact field may veto.
    #
    # The unique constraint is therefore gone. Provider identity lives on
    # provider_team_key below; this column is contact data.
    email     = Column(String,  nullable=False)
    # ── Sprint 6 provider identity (S6-R1) ────────────────────────────────────
    #
    # Yahoo's full compound team key, e.g. "461.l.488800.t.7". The compound form
    # is required, not cosmetic: Yahoo team_id is 1..N WITHIN a league, so the
    # bare "7" collides across every league and every season. The game and
    # league segments are what make it collision-safe across both.
    #
    # `provider_team_id` keeps the provider's own within-league ordinal so the
    # resolver can answer a scoreboard payload that quotes only the ordinal
    # without re-deriving it from a string on every lookup.
    provider          = Column(String,  nullable=True)
    provider_team_key = Column(String,  nullable=True)
    provider_team_id  = Column(Integer, nullable=True)

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
    __table_args__ = (
        # S6-R1 — the provider-native stable player identity. Unique per
        # (provider, key), and the key carries the GAME segment, so the same
        # Yahoo player_id under two different game_ids is two different rows
        # rather than a silent overwrite.
        UniqueConstraint("provider", "provider_player_key",
                         name="uq_players_provider_key"),
        # name is a display field. Indexed for lookup, never unique.
        Index("ix_players_name", "name"),
        # yahoo_id is retained for the legacy FR-7.30 paths but is NOT unique
        # any more — see the column comment.
        Index("ix_players_yahoo_id", "yahoo_id"),
    )

    id       = Column(Integer,    primary_key=True, autoincrement=True)
    # ── NOT AN IDENTIFIER (S6-R1, recon R-4) ──────────────────────────────────
    #
    # Was `unique=True` through Sprint 5. Two real NFL players share a name
    # often enough that this is a live defect, not a hypothetical: the second
    # "Josh Allen" to be rostered anywhere in the system could not be inserted
    # at all, so provider ingestion failed closed on a NAME COLLISION rather
    # than on anything to do with identity. A same-name player must ingest
    # cleanly, so the constraint is gone.
    name     = Column(String,     nullable=False)
    position = Column(String,     nullable=False)      # QB | RB | WR | TE | FLEX | K | DEF
    nfl_team = Column(String(4),  nullable=True)       # NFL team abbreviation, e.g. "KC", "BAL"
    # ── LEGACY, NO LONGER UNIQUE (recon R-5) ──────────────────────────────────
    #
    # Written by FR-7.30 as str(player.player_id) — the BARE Yahoo player id,
    # with no game segment. Yahoo scopes player_id to the GAME, so the same
    # integer denotes different players in different seasons. A global UNIQUE on
    # it was therefore a cross-season collision waiting to happen: the first
    # season to claim id 12345 would permanently block the next season's 12345.
    #
    # The column stays so the existing FR-7.30 roster paths keep working within
    # one season; its uniqueness does not. Authoritative identity is
    # provider_player_key below.
    yahoo_id = Column(String,     nullable=True)
    # ── Sprint 6 provider identity (S6-R1) ────────────────────────────────────
    #
    # Yahoo's full compound player key, e.g. "461.p.31883" — game segment first.
    # That segment is exactly what makes the key collision-safe across seasons,
    # which the bare yahoo_id above is not.
    provider            = Column(String, nullable=True)
    provider_player_key = Column(String, nullable=True)

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
    __table_args__ = (
        UniqueConstraint("league_id", "week", "home_team_id"),
        # S6 §5 — one real provider matchup is one internal row. The derived
        # key is canonical over the UNORDERED team pair (see the column comment),
        # so a mirrored payload produces the same key and conflicts here.
        UniqueConstraint("league_id", "provider_matchup_key",
                         name="uq_matchups_provider_key"),
    )

    id             = Column(Integer, primary_key=True, autoincrement=True)
    league_id      = Column(Integer, ForeignKey("leagues.id"),  nullable=False)
    week           = Column(Integer, nullable=False)
    home_team_id   = Column(Integer, ForeignKey("teams.id"),    nullable=False)
    away_team_id   = Column(Integer, ForeignKey("teams.id"),    nullable=False)
    home_score     = Column(Float,   nullable=False)
    away_score     = Column(Float,   nullable=False)
    winner_team_id = Column(Integer, ForeignKey("teams.id"),    nullable=True)
    refreshed_at   = Column(DateTime, nullable=True)
    # ── Economic finality (S5-P2 owner ruling) ────────────────────────────────
    #
    # NULL  = the result is NOT economically final
    # set   = an authoritative result has been declared final and MAY drive
    #         Skunk and other economic settlement
    #
    # DELIBERATELY NOT refreshed_at. That column means "data was ingested or
    # refreshed", which is not the same claim and must never become load-bearing
    # for a money path — a refresh that pulled an in-progress score would read as
    # final. Finality is its own fact and gets its own field.
    #
    # NO MONEY PATH MAY INFER FINALITY from a non-null score, from a 0-0 score,
    # from refreshed_at, or from the passage of time. home_score/away_score are
    # NOT NULL, so an unplayed game reads 0.0-0.0 and is indistinguishable from a
    # genuine tie by score alone — which is precisely the conflation this column
    # exists to prevent.
    #
    # Sprint 6's Yahoo provider will own the mapping from authoritative final-game
    # status to this field. Sprint 5 fixtures set it explicitly.
    finalized_at   = Column(DateTime, nullable=True)
    # ── Sprint 6 provider matchup identity (S6 §5) ────────────────────────────
    #
    # DERIVED, BECAUSE YAHOO SUPPLIES NO MATCHUP KEY. A Yahoo scoreboard matchup
    # carries no identifier of its own — only the two participating teams and
    # the week. The stable identity is therefore constructed from facts that ARE
    # provider-stable:
    #
    #     {league_key}.w.{week}.m.{lowTeamKey}~{highTeamKey}
    #
    # canonicalized by sorting the two PROVIDER TEAM KEYS. Sorting is what makes
    # the key immune to payload order: Yahoo listing (B, A) instead of (A, B)
    # produces byte-identical output, so the mirrored row conflicts on
    # uq_matchups_provider_key instead of inserting a duplicate. Nothing here
    # reads a team NAME, a manager, or a list position.
    #
    # Nullable: Sprint 1-5 rows and locally-seeded fixtures have no provider
    # matchup and stay NULL. NULLs are distinct under a UNIQUE constraint on
    # both backends, so any number of them coexist.
    provider_matchup_key = Column(String, nullable=True)

    league    = relationship("League", back_populates="matchups")
    home_team = relationship("Team", foreign_keys=[home_team_id],
                             back_populates="home_matchups")
    away_team = relationship("Team", foreign_keys=[away_team_id],
                             back_populates="away_matchups")
    winner    = relationship("Team", foreign_keys=[winner_team_id])
    bets      = relationship("Bet",  back_populates="matchup")


# ── S6 §5 — mirrored-pair backstop ────────────────────────────────────────────
#
# The DERIVED provider key above stops a mirror at the provider layer. This
# index stops one at the DATABASE layer, for every writer, including the ones
# that predate Sprint 6 and set provider_matchup_key to NULL.
#
# The existing UNIQUE (league_id, week, home_team_id) does NOT do this job. It
# constrains only the HOME side, so (week 3, home=A, away=B) and (week 3,
# home=B, away=A) have different home_team_id values and both insert happily —
# two rows for one real game, which then double-counts in every downstream
# census and settlement read. Constraining the UNORDERED pair is what closes it.
#
# Expressed as raw DDL rather than a SQLAlchemy Index because the two backends
# spell the pairwise extrema differently and there is no portable construct:
# PostgreSQL has LEAST/GREATEST, SQLite overloads MIN/MAX as scalar functions.
# Both predicates below are the SAME constraint; supplying only one would leave
# the other backend silently unprotected.
_MATCHUP_PAIR_IX_PG = DDL(
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_matchups_unordered_pair "
    "ON matchups (league_id, week, "
    "LEAST(home_team_id, away_team_id), GREATEST(home_team_id, away_team_id))"
)
_MATCHUP_PAIR_IX_SQLITE = DDL(
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_matchups_unordered_pair "
    "ON matchups (league_id, week, "
    "MIN(home_team_id, away_team_id), MAX(home_team_id, away_team_id))"
)
event.listen(Matchup.__table__, "after_create",
             _MATCHUP_PAIR_IX_PG.execute_if(dialect="postgresql"))
event.listen(Matchup.__table__, "after_create",
             _MATCHUP_PAIR_IX_SQLITE.execute_if(dialect="sqlite"))


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
            "bet_type IN ('straight','spread','over_under')",
            name="ck_beef_bet_type",
        ),
        # ── SPEC 1 (Proposal Lifecycle, Rev 3) — additive constraints ──
        # These constrain the new container columns only; NULL passes each CHECK
        # (legacy-created rows leave them NULL). Ruling 2: 'straight' is the
        # persisted value for Moneyline; "Moneyline" is a display label only.
        CheckConstraint(
            "challenge_mode IN ('locked','dynamic')",
            name="ck_beef_challenge_mode",
        ),
        CheckConstraint(
            "wager_type IN ('straight','spread','over_under')",
            name="ck_beef_wager_type",
        ),
        CheckConstraint(
            "response_status IN "
            "('offered','countered','accepted','declined','expired','cancelled')",
            name="ck_beef_response_status",
        ),
        # §3.4 — the active/accepted proposal must belong to THIS challenge.
        # Composite FK: (pointer, id) -> (beef_proposals.id, beef_proposals.
        # challenge_id) binds the referenced proposal's challenge_id to this
        # row's id. use_alter breaks the beef_challenges<->beef_proposals cycle;
        # under SQLite the ALTER-added FK is dropped (behaviour proven only on
        # Postgres), so this is declaration-authoritative there and metadata-only
        # under SQLite (mirrors challenger_bet_id/challenged_bet_id).
        ForeignKeyConstraint(
            ["active_proposal_id", "id"],
            ["beef_proposals.id", "beef_proposals.challenge_id"],
            use_alter=True,
            name="fk_beef_active_proposal_same_challenge",
        ),
        ForeignKeyConstraint(
            ["accepted_proposal_id", "id"],
            ["beef_proposals.id", "beef_proposals.challenge_id"],
            use_alter=True,
            name="fk_beef_accepted_proposal_same_challenge",
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

    # ── SPEC 1 (Proposal Lifecycle, Rev 3) — additive container fields ──
    # The legacy columns above stay in place for the unreleased legacy flow
    # (beef_engine.py is untouched); the new lifecycle is unreachable until
    # Spec 2 supplies escrow. Every new column is nullable so legacy-created
    # rows and flows continue unchanged (Ruling 1). The new-model integrity
    # constraints (CHECKs, composite same-challenge FKs, version UNIQUE) remain
    # fully enforced for rows that populate them.
    league_id                  = Column(Integer,  ForeignKey("leagues.id", name="fk_beef_challenge_league"), nullable=True)
    challenge_mode             = Column(String,   nullable=True)  # CHECK ('locked','dynamic'), immutable
    wager_type                 = Column(String,   nullable=True)  # CHECK ('straight','spread','over_under')
    response_status            = Column(String,   nullable=True)  # negotiation state only (§4)
    active_proposal_id         = Column(Integer,  nullable=True)  # composite same-challenge FK (§3.4)
    accepted_proposal_id       = Column(Integer,  nullable=True)  # composite same-challenge FK (§3.4)
    active_response_expires_at = Column(DateTime, nullable=True)  # cached copy of active proposal deadline
    revived_from_challenge_id  = Column(Integer,  ForeignKey("beef_challenges.id", name="fk_beef_challenge_revived_from"), nullable=True)  # audit lineage (§8)
    updated_at                 = Column(DateTime, nullable=True)

    # ── SIMULATION ENGINE Rev 9 §5 — Dynamic Handshake freeze ──
    # Written once, atomically, by the Dynamic Handshake; never by Locked, and
    # never updated afterwards. All nullable so every Locked and legacy row is
    # unaffected.
    #
    # THE CEILINGS LIVE ON THE CHALLENGE ROW BECAUSE THE HANDSHAKE-EXIT AND
    # FINAL-LOCK GUARDS REQUIRE TWO INDEPENDENT READS (§2 guards 2 and 3): the
    # escrow balance comes from the ledger, the ceiling from here. Deriving the
    # ceiling from the same provenance that produced the balance would make the
    # comparison circular and unable to catch an inconsistent true-up.
    #
    # `dynamic_issuer_ceiling_cents` IS the accepted Anchor (§2 guard 3a). It is
    # recorded rather than inferred so guard 3a can assert the equality instead
    # of assuming it — a challenge carrying issuer_ceiling 6000 against anchor
    # 5000 would otherwise satisfy strict equality at escrow 6000 and produce a
    # 1000-cent issuer refund, which is exactly the state OVERSHOOT-B outlaws.
    dynamic_issuer_ceiling_cents   = Column(Integer,  nullable=True)
    dynamic_opponent_ceiling_cents = Column(Integer,  nullable=True)
    # MODEL-A: the frozen model identity. The refresh and Final Lock both resolve
    # THIS id, never ACTIVE_MODEL_VERSION_ID. The hash detects an edited registry
    # entry; it is not a lookup key and never reconstructs configuration.
    dynamic_model_version_id       = Column(String,   nullable=True)
    dynamic_model_config_hash      = Column(String,   nullable=True)
    dynamic_handshake_at           = Column(DateTime, nullable=True)

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


class BeefProposal(Base):
    """SPEC 1 (Proposal Lifecycle, Rev 3) §3.2 — immutable versioned proposal.

    Insert-only; never updated after creation, even once inactive. Owns the
    frozen resolved quote, this proposal's own timing, the both-team covered
    snapshot (BeefProposalStarter, §3.3/§6), and full pricing provenance so each
    version is independently reproducible. The challenge owns the immutable wager
    class (BeefChallenge.wager_type); this proposal does NOT duplicate it (§5).

    Spec 1 owns structure and immutability; Spec 2 funds the stake fields, so the
    stake/pricing/timing columns are nullable here. All money is INTEGER CENTS.
    """
    __tablename__ = "beef_proposals"
    __table_args__ = (
        # §3.4/§9 — prevents two callers minting the same version under the lock.
        UniqueConstraint("challenge_id", "version_number",
                         name="uq_beef_proposal_version"),
        # Target for the challenge's composite same-challenge FK (§3.4). id is
        # already unique alone; this names the exact (id, challenge_id) pair the
        # FK references (Postgres requires a matching unique constraint).
        UniqueConstraint("id", "challenge_id",
                         name="uq_beef_proposal_id_challenge"),
        CheckConstraint(
            "version_kind IN ('initial','counter')",
            name="ck_beef_proposal_version_kind",
        ),
    )

    id                = Column(Integer, primary_key=True, autoincrement=True)
    challenge_id      = Column(Integer, ForeignKey("beef_challenges.id"), nullable=False)
    version_number    = Column(Integer, nullable=False)   # monotonic within challenge
    version_kind      = Column(String,  nullable=False)   # CHECK ('initial','counter')
    proposing_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    created_at        = Column(DateTime, nullable=False,
                               default=lambda: datetime.now(timezone.utc))

    # ── Timing — the proposal is authoritative for its own deadline (§3.2) ──
    # Effective deadline = min(created_at + 60 minutes, proposal_lock_at).
    response_expires_at = Column(DateTime, nullable=True)
    proposal_lock_at    = Column(DateTime, nullable=True)  # earliest covered kickoff for THIS proposal
    schedule_source_ref = Column(String,   nullable=True)  # schedule source/version used for the lock

    # ── Frozen resolved market terms (proposal owns these; challenge owns class) ──
    line      = Column(Float,   nullable=True)
    side      = Column(String,  nullable=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=True)

    # ── Money — INTEGER CENTS (Spec 2 funds these) ──
    anchor_stake_cents          = Column(Integer, nullable=True)  # proposed fixed Anchor
    quoted_derived_stake_cents  = Column(Integer, nullable=True)  # displayed Derived Stake
    quoted_funded_pot_cents     = Column(Integer, nullable=True)  # displayed funded pot
    quoted_anchor_payout_cents  = Column(Integer, nullable=True)  # optional displayed payout
    quoted_derived_payout_cents = Column(Integer, nullable=True)  # optional displayed payout
    anchor_team_id  = Column(Integer, ForeignKey("teams.id"), nullable=True)  # always the issuer (A4)
    derived_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)

    # ── Pricing provenance (reproducible quote) ──
    pricing_model_id          = Column(String,   nullable=True)
    pricing_calc_version      = Column(String,   nullable=True)
    projection_source_id      = Column(String,   nullable=True)
    projection_retrieved_at   = Column(DateTime, nullable=True)
    projection_input_snapshot = Column(JSON,     nullable=True)   # exact inputs, or a reference
    anchor_win_probability    = Column(Float,    nullable=True)
    derived_win_probability   = Column(Float,    nullable=True)
    anchor_odds               = Column(Float,    nullable=True)
    derived_odds              = Column(Float,    nullable=True)
    anchor_moneyline          = Column(Integer,  nullable=True)
    derived_moneyline         = Column(Integer,  nullable=True)
    pricing_input_hash        = Column(String,   nullable=True)   # integrity hash of pricing inputs

    # ── Display — explicitly NON-authoritative (§3.2); structured fields govern ──
    display_terms = Column(String, nullable=True)

    proposing_team = relationship("Team",   foreign_keys=[proposing_team_id])
    anchor_team    = relationship("Team",   foreign_keys=[anchor_team_id])
    derived_team   = relationship("Team",   foreign_keys=[derived_team_id])
    player         = relationship("Player", foreign_keys=[player_id])


class BeefProposalStarter(Base):
    """SPEC 1 §3.3 — proposal-scoped both-team starter snapshot. Replaces the
    challenge-scoped BeefStarter for the new model: every proposal (initial and
    each counter) captures its OWN frozen snapshot of BOTH teams (§6), so a
    counter is independently reproducible with no cross-proposal join. team_id
    stores the raw team id; role is derived by matching challenge participants."""
    __tablename__ = "beef_proposal_starters"
    __table_args__ = (
        UniqueConstraint("proposal_id", "team_id", "player_id",
                         name="uq_beef_proposal_starter"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    proposal_id = Column(Integer, ForeignKey("beef_proposals.id"), nullable=False)
    team_id     = Column(Integer, ForeignKey("teams.id"),          nullable=False)
    player_id   = Column(Integer, ForeignKey("players.id"),        nullable=False)
    nfl_team    = Column(String(4), nullable=True)

    proposal = relationship("BeefProposal", foreign_keys=[proposal_id])
    team     = relationship("Team",         foreign_keys=[team_id])
    player   = relationship("Player",       foreign_keys=[player_id])


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
    # B1 Discrete-Stop Economy Table snapshot — populated once, at link
    # creation, from whichever stop is active at that moment. Read at
    # confirmation time FROM THIS RECORD, never from live config, so a
    # later slider change can't split one buy-in across two different
    # stops between link creation and payment confirmation.
    buyin_cents              = Column(Integer,  nullable=False)
    wallet_cents             = Column(Integer,  nullable=False)
    reserve_cents            = Column(Integer,  nullable=False)
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
        # B6 §7.1 — the persisted states are pending, applied, rejected,
        # cancelled. 'rejected' is ADDED here because §4.4's legal state matrix
        # requires (decision='rejected', status='rejected') to be a committable
        # row and the prior constraint forbade it outright.
        #
        # 'failed' is TEMPORARILY RETAINED. §7.1 states there is no `failed`
        # state for a top-off, and the topup_bet-scoped lifecycle constraint
        # below makes it unrepresentable on a top-off row. It survives in this
        # GLOBAL constraint only because an unrelated legacy non-B6 writer still
        # sets it (wallet/faab_wallet.py). Retiring that writer and dropping
        # 'failed' from this list is Group F legacy closure, deliberately not
        # done here — narrowing it now would break a live path outside B6 scope.
        CheckConstraint(
            "status IN ('pending','applied','rejected','cancelled','failed')",
            name="ck_faab_tx_status",
        ),
        # B6 §4.1 — allowed decision values. NULL is permitted because the
        # column is nullable on LEGACY rows that predate B6 and carry no
        # lifecycle decision at all. For a topup_bet row a NULL decision is
        # refused by ck_faab_tx_topup_bet_lifecycle below, so this tolerance
        # never reaches a B6 top-off.
        CheckConstraint(
            "decision IS NULL "
            "OR decision IN ('pending','approved','rejected','cancelled')",
            name="ck_faab_tx_decision",
        ),
        # B6 §4.4 — the four legal decision/status pairs, scoped to topup_bet.
        #
        # `decision IS NOT NULL` is LOAD-BEARING and is not a null exception —
        # it is the opposite. A SQL CHECK rejects only on a definite FALSE and
        # passes on UNKNOWN. Without this conjunct a topup_bet row carrying
        # decision = NULL would evaluate every disjunct to NULL, make the OR
        # chain NULL, and SILENTLY PASS. Requiring the decision to be present
        # turns a missing lifecycle decision into a definite violation.
        #
        # Consequence: a topup_bet row can never carry status='failed', because
        # no legal pair admits it.
        CheckConstraint(
            "type <> 'topup_bet'"
            " OR (decision IS NOT NULL"
            "     AND ((decision = 'pending'   AND status = 'pending')"
            "       OR (decision = 'approved'  AND status = 'applied')"
            "       OR (decision = 'rejected'  AND status = 'rejected')"
            "       OR (decision = 'cancelled' AND status = 'cancelled')))",
            name="ck_faab_tx_topup_bet_lifecycle",
        ),
        # B6 §4.4 — the linkage biconditional, BOTH directions, scoped to
        # topup_bet. Applied requires both linkage fields; every non-applied
        # state forbids BOTH.
        #
        # The equality is applied PER FIELD, not once against the conjunction.
        # §4.4's one-line shorthand reads
        #     (decision='approved' AND status='applied')
        #       IFF (ledger_posting_id IS NOT NULL AND disclosure_event_id IS NOT NULL)
        # but implemented literally that lets a NON-APPLIED row carry exactly ONE
        # linkage field: the right-hand conjunction is then FALSE, the left side
        # is FALSE, and FALSE = FALSE passes. The authoritative reading is §4.4's
        # prose ("every non-applied state forbids both") and its legal state
        # matrix, which show BOTH fields absent on every non-applied row. Pairing
        # each field separately against applied-ness enforces exactly that, and
        # is what makes a stray half-linkage unrepresentable.
        CheckConstraint(
            "type <> 'topup_bet'"
            " OR (((decision = 'approved' AND status = 'applied')"
            "      = (ledger_posting_id IS NOT NULL))"
            "     AND ((decision = 'approved' AND status = 'applied')"
            "          = (disclosure_event_id IS NOT NULL)))",
            name="ck_faab_tx_topup_bet_linkage",
        ),
        Index("ix_faab_tx_team_created", "team_id", "created_at"),
        # B6 §8.5 — AT MOST ONE OPEN TOP-OFF REQUEST per (league, team, season).
        # This index IS the duplicate-creation mechanism: §8.5 assigns duplicate
        # creation to "a partial unique index", not to an application check, so a
        # concurrent pair of creates that both pass a pre-check still resolves to
        # one row. The Group E service pre-checks for a clean refusal and treats
        # a violation of THIS index — by name — as the same refusal; any other
        # IntegrityError propagates.
        #
        # PARTIAL, and both predicates are required. Scoped to
        # type='topup_bet' AND status='pending' so it constrains only OPEN B6
        # requests: a team may hold any number of applied, rejected or cancelled
        # rows for one season, and legacy topup_waiver history is untouched.
        # postgresql_where alone would emit a FULL unique index on SQLite —
        # api/main.py's create_all() builds the fallback SQLite database from
        # this same model — which would forbid a second terminal row for a team
        # and break the lifecycle outright. Both dialects therefore carry the
        # predicate explicitly.
        Index(
            "uq_faab_tx_one_open_topoff",
            "league_id", "team_id", "season",
            unique=True,
            postgresql_where=text("type = 'topup_bet' AND status = 'pending'"),
            sqlite_where=text("type = 'topup_bet' AND status = 'pending'"),
        ),
    )

    id               = Column(Integer,  primary_key=True, autoincrement=True)
    league_id        = Column(Integer,  ForeignKey("leagues.id"), nullable=False)
    team_id          = Column(Integer,  ForeignKey("teams.id"),   nullable=False)
    type             = Column(String,   nullable=False)
    amount           = Column(Float,    nullable=False, default=0.0)
    wallet_from      = Column(String,   nullable=True)   # "bet" | "waiver" | "stripe"
    wallet_to        = Column(String,   nullable=True)   # "bet" | "waiver"
    # B6 §4.3 — default flipped "applied" -> "pending". A row born `applied`
    # without linkage is an immediate violation of ck_faab_tx_topup_bet_linkage.
    # Inert for existing writers: wallet/faab_wallet.py's _log_tx() is the only
    # construction site and always passes status= explicitly.
    status           = Column(String,   nullable=False,  default="pending")
    note             = Column(String,   nullable=True)
    stripe_link_id   = Column(String,   nullable=True)
    stripe_link_url  = Column(String,   nullable=True)
    stripe_session_id = Column(String,  nullable=True)
    apply_on         = Column(DateTime, nullable=True)   # NULL = immediate; set for Tuesday queue
    applied_at       = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # ── B6 provenance (§4.1, §4.2) ────────────────────────────────────────
    #
    # NAMES ARE FIXED. §4.1: "load-bearing across VAL-10 R5, §5, §10, §12 and
    # the FR-VAL10 register." No rename without a proven technical reason
    # recorded as a finding.
    #
    # Every column is nullable. That is deliberate: legacy rows predating B6
    # carry none of this, and B6 never converts them (§11.5 — dormant history,
    # never a B6 request, never consumes cap). Completeness for a live top-off
    # is enforced by the two scoped CHECKs above, not by NOT NULL.
    #
    # Nothing in Group C WRITES these columns. Population at decision time is
    # the Group E issuance service.
    requester_user_id   = Column(Integer,  ForeignKey("users.id", name="fk_faab_tx_requester_user"),
                                 nullable=True)    # immutable after creation (Group E discipline)
    decided_by_user_id  = Column(Integer,  ForeignKey("users.id", name="fk_faab_tx_decided_by_user"),
                                 nullable=True)    # immutable after posting (Group E discipline)
    decision            = Column(String,   nullable=True)
    decision_reason     = Column(Text,     nullable=True)   # mandatory non-empty on self-approval (Group E)
    decided_at          = Column(DateTime, nullable=True)
    # UNIQUE WHEN NON-NULL. unique=True on a nullable column yields a unique
    # index that permits repeated NULLs on both PostgreSQL and SQLite, which is
    # exactly the required semantics — many undecided requests, at most one
    # claim on any given posting or disclosure.
    #
    # NO ForeignKey to ledger_entries (§4.7): LedgerEntry.posting_id is
    # deliberately NON-unique because every leg of a posting shares it, and the
    # ledger sits on a SEPARATE declarative base. Uniqueness is enforced on
    # this side only.
    ledger_posting_id   = Column(Uuid,     nullable=True, unique=True)
    disclosure_event_id = Column(Uuid,     nullable=True, unique=True)   # stores top_off_disclosure.event_id, NOT its integer PK
    amount_cents        = Column(Integer,  nullable=True)   # sole authoritative amount; float `amount` is display-only
    season              = Column(Integer,  nullable=True)   # config.ALLOCATION_SEASON
    # §4.2 — additive classification, immutable once written. It REPLACES
    # NOTHING: requester_user_id and decided_by_user_id remain mandatory and
    # separate. Records requester_user_id == decided_by_user_id as evaluated at
    # decision time (Group E).
    self_approved       = Column(Boolean,  nullable=True)

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
    __table_args__ = (
        # POR Rev1.3 §6.1 — the governed bound on the Rev1.3 league-level weekly
        # contribution. NULL passes: a league that has not yet been configured
        # for the Rev1.3 Pool carries NULL here and reads the governed default
        # (100) through betting/pool_funding.py, never a silent 0.
        CheckConstraint(
            "pool_weekly_entry_cents IS NULL OR "
            "(pool_weekly_entry_cents >= 100 AND pool_weekly_entry_cents <= 500)",
            name="ck_pool_config_weekly_entry_bounds",
        ),
    )

    id                      = Column(Integer, primary_key=True, autoincrement=True)
    league_id               = Column(Integer, ForeignKey("leagues.id"), unique=True)
    weekly_entry_cents      = Column(Integer, nullable=False, default=1000)
    worst_beat_rollover     = Column(Boolean, default=True)
    created_at              = Column(DateTime(timezone=True),
                                     default=lambda: datetime.now(timezone.utc))
    # ── Rev1.3 league-level weekly contribution (POR §6.1) ────────────────────
    #
    # WHY A SEPARATE COLUMN RATHER THAN A BOUND ON weekly_entry_cents. §6.1
    # bounds the Rev1.3 contribution to 100..500 cents with a default of 100.
    # weekly_entry_cents is the LEGACY three-pot engine's field and defaults to
    # 1000 — live rows carry 1000 today. Putting the §6.1 CHECK on that column
    # would reject every existing row at migration time, which §15's "preserve
    # valid historical/live values" forbids. This is an extension of the same
    # table, not a parallel subsystem: one row per league still holds the whole
    # Pool configuration.
    #
    # FROZEN, not merely bounded. POR §6.1 freezes the contribution at the
    # season freeze point. pool_weekly_entry_frozen_at is written once, by the
    # first Rev1.3 weekly collection for the league (the first accepted Pool
    # wager), and betting/pool_funding.py refuses any later change. The
    # timestamp is both the flag and the record — the same single-representation
    # rule League.season_closed_at follows.
    pool_weekly_entry_cents     = Column(Integer, nullable=True)
    pool_weekly_entry_frozen_at = Column(DateTime(timezone=True), nullable=True)

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
    worst_beat_rollover_cents  = Column(BigInteger, default=0)
    entries_collected          = Column(Boolean,  default=False)
    total_pot_cents            = Column(BigInteger, nullable=True)
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
    # FR-8.7 — explicit settlement lifecycle status ('CLAIMED' at claim
    # time) and crash-recovery token, enabling detection/resumption of a
    # payout loop that died after the claim committed but before payouts
    # finished. Additive; the run-once claim still keys off
    # uq_week_settlement_league_week, not off these columns.
    status         = Column(String, nullable=False, default="CLAIMED")
    recovery_token = Column(String, nullable=True)

    league = relationship("League")


class ShortfallSweepRecord(Base):
    """One row per team per week — records a shortfall sweep's computed
    amounts and its ledger posting_id (B2, Section 6). Idempotency guard,
    modeled on WeekSettlement/PoolPot's run-once pattern: calling the sweep
    twice for the same team/week must not double-drain a wallet. The
    ledger's own entries remain the source of truth for money movement —
    this table is metadata about what was posted, used for idempotency and
    reporting only."""
    __tablename__ = "shortfall_sweep_records"
    __table_args__ = (
        UniqueConstraint("league_id", "team_id", "week", name="uq_shortfall_sweep_team_week"),
    )

    id               = Column(Integer,  primary_key=True, autoincrement=True)
    league_id        = Column(Integer,  ForeignKey("leagues.id"), nullable=False)
    team_id          = Column(Integer,  ForeignKey("teams.id"),   nullable=False)
    week             = Column(Integer,  nullable=False)
    weekly_min_cents = Column(Integer,  nullable=False)
    wagered_cents    = Column(Integer,  nullable=False)
    shortfall_cents  = Column(Integer,  nullable=False)
    covered_cents    = Column(Integer,  nullable=False)
    uncovered_cents  = Column(Integer,  nullable=False)
    posting_id       = Column(String,   nullable=True)   # null when shortfall_cents == 0 (nothing posted)
    created_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    league = relationship("League")
    team   = relationship("Team")


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


# ── Pool rotation (SPEC_Pool_Rotation_Implementation_Scope_Rev1_1 §C1/§C2/§C3) ─
#
# Schema only. Nothing here is wired into collection or settlement, and no code
# in this commit writes pot_cents or rollover_cents — creating a money-bearing
# column is schema work; writing it is money-path work and is out of scope.

class PoolDefinition(Base):
    """One row per catalog definition — §C1. 80 active rows seeded from
    spec/pool_catalog_rev1_3.json by betting.pool_catalog.seed_definitions.

    metric_expression and threshold_condition are stored as opaque nullable
    strings. Storability is independent of executability: a null
    metric_expression on a non-CLOSED_* shape is correct and expected (POR
    §3.4), and the authoritative rule for those rows is governed_definition.

    CHECK domains are taken from §C1's own pipe-delimited declarations, not from
    the values that happen to appear in Rev1.0. `mechanic` therefore admits
    'RANK' even though all 94 current rows are 'PREDICTION' — §C1 declares the
    domain and a narrower CHECK would reject a row the spec permits. Fields §C1
    does not type as an enum (category, self_pick_rule, anti_tanking_review,
    data_dependency, tie_rule) carry no CHECK, so a new category or a non-default
    tie_rule is not refused by the database."""
    __tablename__ = "pool_definition"
    __table_args__ = (
        CheckConstraint("scope IN ('TEAM','MATCHUP')",
                        name="ck_pool_definition_scope"),
        CheckConstraint("mechanic IN ('PREDICTION','RANK')",
                        name="ck_pool_definition_mechanic"),
        CheckConstraint("evaluator_family IN ('RANK_EXTREMUM','QUALIFIER')",
                        name="ck_pool_definition_evaluator_family"),
        # Rev1.3 widened this domain. Rev1.0 admitted only SIMPLE_AGG, RATIO and
        # COMPOSITE; the Rev1.3 catalog additionally carries PLAYER_EXTREMUM,
        # POINTS_AGG, BALANCE_RATIO and CATEGORY_COUNT, and COMPOSITE no longer
        # appears on any active row (POR §3.1: "No formula is pending").
        # COMPOSITE is retained in the domain rather than dropped — narrowing it
        # would reject historical rows the earlier revision legitimately wrote.
        CheckConstraint(
            "metric_kind IN ('SIMPLE_AGG','RATIO','COMPOSITE','PLAYER_EXTREMUM',"
            "'POINTS_AGG','BALANCE_RATIO','CATEGORY_COUNT')",
            name="ck_pool_definition_metric_kind",
        ),
        # POR §3.4 / Scope §C8 — the eight governed executable shapes. This is
        # the axis that defines COMPUTATION; evaluator_family classifies
        # SETTLEMENT BEHAVIOR. Conflating them is the error §3.1 exists to
        # prevent, so both are stored and both are constrained.
        CheckConstraint(
            "evaluator_shape IN ('CLOSED_SUM','CLOSED_RATIO','QUALIFIER_PREDICATE',"
            "'PLAYER_EXTREMUM_WITHIN_SUBJECT','SLOT_FILTERED_POINTS_SUM',"
            "'BALANCE_RATIO','DISTINCT_CATEGORY_COUNT','MATCHUP_SCORE_SUM')",
            name="ck_pool_definition_evaluator_shape",
        ),
        CheckConstraint("direction IS NULL OR direction IN ('MAX','MIN')",
                        name="ck_pool_definition_direction"),
        CheckConstraint("dependency_state IN ('ENABLED','BLOCKED')",
                        name="ck_pool_definition_dependency_state"),
        CheckConstraint(
            "predicate_quantifier IS NULL OR predicate_quantifier IN "
            "('TEAM','MATCHUP_COMBINED','MATCHUP_EACH')",
            name="ck_pool_definition_predicate_quantifier",
        ),
        # POR §7.0 — "Every blocked definition carries a non-null blocked_reason"
        # and it "is null on all 77 non-blocked active definitions." Both halves
        # are enforced; a one-sided check would let a BLOCKED row ship with no
        # reason, which is the half that matters operationally.
        CheckConstraint(
            "(dependency_state = 'BLOCKED' AND blocked_reason IS NOT NULL) OR "
            "(dependency_state = 'ENABLED' AND blocked_reason IS NULL)",
            name="ck_pool_definition_blocked_reason",
        ),
        # POR §1.1 / conformance 34e, 40 — retired numbers are reserved
        # permanently and are never reused. #8-#12, #97 and #98 are refused at
        # the DATABASE, not only by the seeder, so no later code path (a fixture,
        # a manual insert, a future migration) can resurrect one.
        CheckConstraint(
            "catalog_number NOT IN (8, 9, 10, 11, 12, 44, 45, 47, 50, 51, 52, "
            "57, 81, 82, 88, 96, 97, 98)",
            name="ck_pool_definition_retired_numbers",
        ),
    )

    # Natural String PK, per §C1 "key PK". Precedent: PlayerIdMap.fantasypros_id.
    key                               = Column(String,  primary_key=True)
    catalog_number                    = Column(Integer, nullable=False)
    display_name                      = Column(String,  nullable=False)
    category                          = Column(String,  nullable=False)
    scope                             = Column(String,  nullable=False)
    mechanic                          = Column(String,  nullable=False)
    evaluator_family                  = Column(String,  nullable=False)
    metric_kind                       = Column(String,  nullable=False)
    direction                         = Column(String,  nullable=True)
    metric_expression                 = Column(String,  nullable=True)
    threshold_condition               = Column(String,  nullable=True)
    threshold_configurable            = Column(Boolean, nullable=False)
    self_pick_rule                    = Column(String,  nullable=False)
    anti_tanking_review               = Column(String,  nullable=False)
    data_dependency                   = Column(String,  nullable=False)
    dependency_state                  = Column(String,  nullable=False)
    # RENAMED from block_reason by the S4-P1 migration. POR §7.0: "blocked_reason
    # is the single canonical field." The migration uses ALTER TABLE ... RENAME
    # COLUMN, so any value already written is preserved byte-for-byte; nothing
    # is dropped and no second field is left behind to disagree with this one.
    blocked_reason                    = Column(String,  nullable=True)
    regular_season_eligible           = Column(Boolean, nullable=False)
    # Nullable and stays NULL until the approved postseason 32-subset is
    # supplied. §C1: a null means NOT YET ELIGIBLE — never false-by-default,
    # never true. Nothing in this commit reads it.
    postseason_eligible               = Column(Boolean, nullable=True)
    rollover_eligible                 = Column(Boolean, nullable=False)
    tie_rule                          = Column(String,  nullable=False)
    aggregate_over_aggregate_required = Column(Boolean, nullable=False)
    zero_denominator_guard            = Column(Boolean, nullable=False)

    # ── Revision 1.3 field set (Scope §C1) ────────────────────────────────────
    #
    # Every one of the 80 active definitions carries the identical field set.
    # The two rows that formerly lacked seven of these — #97 and #98 — are
    # retired and are not seedable (see ck_pool_definition_retired_numbers).
    #
    # NULLABLE ON PURPOSE, NOT BY OVERSIGHT. evaluator_shape and
    # starter_slot_rule are NOT NULL because every active row carries them.
    # metric_expression stays nullable because POR §3.4 rules that a null
    # expression on a non-CLOSED_* shape is "correct and expected, not a missing
    # formula" — the governed_definition is authoritative there.
    evaluator_shape                   = Column(String,  nullable=False)
    # Authoritative prose rule for the five non-closed shapes. Read by the
    # evaluator only as documentation — it is never parsed. The executable form
    # of each non-closed shape is a named Python evaluator selected by
    # evaluator_shape, exactly as §C8 requires.
    governed_definition               = Column(String,  nullable=True)
    # POR §1.5 / Scope §C5, binding: threshold_condition is human-readable prose
    # and is NEVER evaluated; `predicate` is the executable form. An evaluator
    # that parses threshold_condition is non-conformant. Both are stored so the
    # UI can show the prose without the engine ever reaching for it.
    predicate                         = Column(String,  nullable=True)
    predicate_quantifier              = Column(String,  nullable=True)
    threshold_default                 = Column(Integer, nullable=True)
    # Canonical stat-vocabulary keys ONLY — never source identifiers, aliases or
    # formulas (POR §1.4). JSON rather than a join table: this is catalog
    # metadata seeded from a governed artifact and read whole, never queried by
    # element. #46 (blocked) legitimately carries NULL.
    required_stats                    = Column(JSON,    nullable=True)
    required_stats_resolved           = Column(Boolean, nullable=False)
    required_stats_unresolved_reason  = Column(String,  nullable=True)
    source_mapping_complete           = Column(Boolean, nullable=False)
    unmapped_required_stats           = Column(JSON,    nullable=True)
    starter_slot_rule                 = Column(String,  nullable=False)
    slot_filter                       = Column(JSON,    nullable=True)
    slot_exclusions                   = Column(JSON,    nullable=True)
    # POR §1.7 — mathematically complete WITHOUT commissioner interpretation.
    product_complete                  = Column(Boolean, nullable=False)
    # ── GATE 1 (POR §1.2) — PERSISTENT definition metadata ────────────────────
    # True only when product-ENABLED, required_stats resolved, every required
    # stat authoritatively source-mapped, and product_complete. A definition
    # NEVER loses product approval because an environment is unavailable, which
    # is why transient provider state is not permitted anywhere on this table.
    #
    # GATE 2 (league_activation_ready) IS DELIBERATELY ABSENT HERE. §C1.1:
    # storing a provider outage inside catalog metadata would make a product
    # artifact carry an operational fact with no timestamp and no scope. Its
    # carrier is PoolLeagueActivation below.
    definition_runtime_eligible       = Column(Boolean, nullable=False)
    definition_block_reason           = Column(String,  nullable=True)


class PoolLeagueActivation(Base):
    """GATE 2 carrier — Scope §C1.1 option B. Transient environment readiness,
    keyed by league, provider and definition, carrying a measurement timestamp.

    NEVER A COLUMN ON pool_definition. The whole point of §C1.1 is that a
    provider refusal is an operational fact about an environment at a moment,
    not a property of a product-approved definition. Storing it on the catalog
    would leave a fact with no scope and no age.

    STALE IS NOT-READY, NOT READY (§C1.1, binding). measured_at is NOT NULL
    precisely so an un-aged measurement cannot exist; betting/pool_gates.py
    applies the staleness window and treats an expired measurement as false.
    The absence of a row is likewise not-ready — readiness must be affirmatively
    measured, never assumed from silence.
    """
    __tablename__ = "pool_league_activation"
    __table_args__ = (
        UniqueConstraint("league_id", "provider", "definition_key",
                         name="uq_pool_league_activation_scope"),
    )

    id             = Column(Integer, primary_key=True, autoincrement=True)
    league_id      = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    provider       = Column(String,  nullable=False)
    definition_key = Column(String,  ForeignKey("pool_definition.key"),
                            nullable=False)
    league_activation_ready       = Column(Boolean, nullable=False)
    league_activation_block_reasons = Column(JSON,  nullable=True)
    measured_at    = Column(DateTime(timezone=True), nullable=False)

    league     = relationship("League")
    definition = relationship("PoolDefinition")


class PoolInstance(Base):
    """One row per drawn pool occurrence — §C2. Four per league/season/week.

    origin_instance_id NULL means a fresh draw; set means a rollover
    continuation of the referenced instance, and is the lineage chain POR §5
    requires be auditable and UI-visible.

    The partial unique index is what PROVES the no-repeat invariant rather than
    asserting it. Its predicate compares `phase` to a string literal, so `phase`
    MUST stay String + CHECK (the repo has zero native Enum anywhere); index
    enforcement was verified under exactly this storage on SQLite 3.50.4 and
    PostgreSQL 16.14. Both dialect kwargs carry IDENTICAL predicate text —
    supplying only one degrades silently to a FULL unique index on the other
    backend, which would reject legitimate continuations."""
    __tablename__ = "pool_instance"
    __table_args__ = (
        CheckConstraint("phase IN ('REGULAR','POSTSEASON')",
                        name="ck_pool_instance_phase"),
        CheckConstraint("slot BETWEEN 1 AND 4",
                        name="ck_pool_instance_slot"),
        UniqueConstraint("league_id", "season", "week", "definition_key",
                         name="uq_pool_instance_week_definition"),
        UniqueConstraint("league_id", "season", "week", "slot",
                         name="uq_pool_instance_week_slot"),
        Index(
            "uq_pool_instance_cycle_fresh",
            "league_id", "season", "rotation_cycle", "definition_key",
            unique=True,
            sqlite_where=text("origin_instance_id IS NULL AND phase = 'REGULAR'"),
            postgresql_where=text("origin_instance_id IS NULL AND phase = 'REGULAR'"),
        ),
    )

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    league_id          = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    season             = Column(Integer, nullable=False)
    week               = Column(Integer, nullable=False)
    phase              = Column(String,  nullable=False)
    rotation_cycle     = Column(Integer, nullable=False)
    definition_key     = Column(String,  ForeignKey("pool_definition.key"),
                                nullable=False)
    slot               = Column(Integer, nullable=False)
    # Money-bearing. NOT NULL DEFAULT 0 deliberately: PoolPot.total_pot_cents is
    # nullable and every reader has to special-case it (settle_pool's explicit
    # NULL guard, and `pot.worst_beat_rollover_cents or 0`). An accumulator that
    # starts at zero is not an absent fact. Nothing in this commit writes these.
    #
    # server_default, not just default: Column(default=…) is CLIENT-side, so
    # create_all would emit a bare NOT NULL while the migration's DDL emits
    # DEFAULT 0. A raw INSERT omitting these would then succeed against the
    # migration's schema and fail against the ORM's — two schema sources for one
    # table, disagreeing. server_default makes both emit the same DDL.
    pot_cents          = Column(BigInteger, nullable=False,
                                default=0, server_default=text("0"))
    rollover_cents     = Column(BigInteger, nullable=False,
                                default=0, server_default=text("0"))
    # Self-FK, audit lineage. Named, following the single precedent
    # beef_challenges.revived_from_challenge_id. No ON DELETE: cascade would
    # destroy lineage POR §5 requires, and SET NULL would silently convert a
    # continuation into a fresh draw and change what the partial index means.
    origin_instance_id = Column(Integer,
                                ForeignKey("pool_instance.id",
                                           name="fk_pool_instance_origin"),
                                nullable=True)
    settled            = Column(Boolean, nullable=False,
                                default=False, server_default=text("false"))
    settled_at         = Column(DateTime(timezone=True), nullable=True)
    # ── S4-P1 settlement outcome ──────────────────────────────────────────────
    #
    # POR §6.2 requires that no surface report a fail-closed instance as
    # settled, completed or distributed. Recording the classification on the row
    # is what lets a reader distinguish "settled, distributed" from "settled,
    # swept" from "refused" WITHOUT re-deriving it, and it is written in the
    # same transaction as the posting it describes.
    #
    # NULL means never evaluated. A fail-closed classification is written ONLY
    # when the refusal is recorded for operator visibility, and `settled` stays
    # FALSE in that case — the two columns are independent facts and the
    # settlement code never writes `settled` on a refusal path.
    settlement_classification = Column(String, nullable=True)
    # Cents actually credited to winning GMs by a §6.3 distribution. 0 on a
    # sweep or a rollover; never NULL after settlement so that "distributed
    # nothing" and "not yet settled" stay distinguishable from settled_at alone.
    distributed_cents  = Column(BigInteger, nullable=False,
                                default=0, server_default=text("0"))
    # No created_at. §C2 gives an explicit field list and a creation timestamp
    # is not in it; neither spec contains any authority requiring one (searched:
    # created_at, creation, timestamp, drawn, recorded at, selection time). POR
    # §4 line 111 enumerates what a persisted draw carries — "week, slot, cycle
    # and lineage" — and a timestamp is not among them. "Other audit tables have
    # one" is convention, not authority to expand a governed schema.

    league = relationship("League")
    origin = relationship("PoolInstance", remote_side=[id])


class PoolRotationCycle(Base):
    """One row per cycle open — §C3 verbatim: league_id, season, rotation_cycle,
    opened_week, eligible_set_size, opened_at. Satisfies POR §4's auditable-reset
    requirement ("one row recording league, season, cycle, opening week, and
    eligible-set size at open").

    WRITTEN BY betting.pool_slate._open_cycle, which records both the opening of
    cycle 1 and every subsequent reset. The pure selector still only SIGNALS a
    reset — it returns reset_required with the audit context and never performs
    one — and pool_slate is the impure half that acts on that signal."""
    __tablename__ = "pool_rotation_cycle"
    __table_args__ = (
        UniqueConstraint("league_id", "season", "rotation_cycle",
                         name="uq_pool_rotation_cycle_open"),
    )

    id                = Column(Integer, primary_key=True, autoincrement=True)
    league_id         = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    season            = Column(Integer, nullable=False)
    rotation_cycle    = Column(Integer, nullable=False)
    opened_week       = Column(Integer, nullable=False)
    eligible_set_size = Column(Integer, nullable=False)
    opened_at         = Column(DateTime(timezone=True),
                               default=lambda: datetime.now(timezone.utc))

    league = relationship("League")


class PoolClaim(Base):
    """One GM's Prediction pick on one pool occurrence.

    A CLAIM, NOT A FUNDING TRANSACTION (Owner Ruling R3). Submitting a pick
    moves no money, and the absence of a pick creates no refund entitlement.
    Funding is league-level and weekly; a claim only decides who is eligible to
    be paid once the winning subject is known.

    ONE CLAIM PER GM PER OCCURRENCE, ENFORCED BY THE DATABASE. The unique
    constraint is the enforcement, not the application check that precedes it —
    two concurrent submissions both pass an application-level "does one exist?"
    read and only a constraint stops the second from landing.

    SUBJECT IDENTITY MIRRORS POR §6.2. selected_subject_type is TEAM or MATCHUP
    and matches the definition's scope; selected_subject_id is a team id or a
    matchup id accordingly. A matchup is one subject, never its two teams.
    """
    __tablename__ = "pool_claim"
    __table_args__ = (
        UniqueConstraint("pool_instance_id", "team_id",
                         name="uq_pool_claim_instance_gm"),
        CheckConstraint("selected_subject_type IN ('TEAM','MATCHUP')",
                        name="ck_pool_claim_subject_type"),
    )

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    pool_instance_id      = Column(Integer, ForeignKey("pool_instance.id"),
                                   nullable=False)
    league_id             = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    # The claiming GM. team_id IS the canonical GM identifier throughout the
    # Pool engine, including POR §6.3's ascending payout ordering — see
    # betting/pool_settlement.py for why an integer team id and not owner name.
    team_id               = Column(Integer, ForeignKey("teams.id"), nullable=False)
    selected_subject_type = Column(String,  nullable=False)
    selected_subject_id   = Column(Integer, nullable=False)
    submitted_at          = Column(DateTime(timezone=True), nullable=False)

    instance = relationship("PoolInstance")
    league   = relationship("League")
    team     = relationship("Team", foreign_keys=[team_id])


class PoolEconomicEvent(Base):
    """Event-keyed idempotency for every Pool economic effect — POR §6.4, §G1.

    THE UNIQUE CONSTRAINT IS THE IDEMPOTENCY, AND A ROW LOCK CANNOT REPLACE IT.
    A lock serializes concurrent attempts inside one process lifetime. It says
    nothing about a retry that arrives after the lock is released, and nothing
    about a crash between posting and response. This row is inserted in the SAME
    transaction as the ledger posting it describes, so a replay collides here
    and the whole retry is a harmless no-op.

    TWO KEY SHAPES, TWO PARTIAL INDEXES. §G1 gives the conceptual key as
    (pool_instance_id, economic_event_type). Weekly collection and the weekly
    division remainder are WEEK-level causes with no single owning instance, so
    they carry a NULL pool_instance_id and are keyed
    (league_id, season, week, event_type) instead. A single combined unique
    constraint would not work: NULLs are distinct in a UNIQUE index on both
    backends, so every replayed weekly collection would insert a fresh row and
    the guard would be silently inert. Two partial indexes, each covering
    exactly one shape, is what makes both enforceable.

    posting_id IS NULLABLE BY DESIGN. A rollover continuation generates no
    posting at all — the money never leaves pool:{league_id} — but it still
    needs an event row so a replayed rollover determination cannot create a
    second continuation. NULL here means "this cause moved no money", which is
    an outcome, not a missing value.
    """
    __tablename__ = "pool_economic_event"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'WEEKLY_COLLECTION',"
            "'WEEKLY_DIVISION_REMAINDER',"
            "'WINNER_DISTRIBUTION',"
            "'SUBJECT_ZERO_CLAIM_ROLLOVER',"
            "'SUBJECT_ZERO_CLAIM_CHAMPIONSHIP_SWEEP',"
            "'TICKET_ZERO_WINNER_ROLLOVER',"
            "'TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP',"
            "'ROLLOVER_EXPIRY_SWEEP')",
            name="ck_pool_economic_event_type",
        ),
        CheckConstraint("amount_cents >= 0",
                        name="ck_pool_economic_event_amount_nonneg"),
        Index(
            "uq_pool_economic_event_instance",
            "pool_instance_id", "event_type",
            unique=True,
            sqlite_where=text("pool_instance_id IS NOT NULL"),
            postgresql_where=text("pool_instance_id IS NOT NULL"),
        ),
        Index(
            "uq_pool_economic_event_week",
            "league_id", "season", "week", "event_type",
            unique=True,
            sqlite_where=text("pool_instance_id IS NULL"),
            postgresql_where=text("pool_instance_id IS NULL"),
        ),
    )

    id               = Column(Integer, primary_key=True, autoincrement=True)
    league_id        = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    season           = Column(Integer, nullable=False)
    week             = Column(Integer, nullable=False)
    pool_instance_id = Column(Integer, ForeignKey("pool_instance.id"),
                              nullable=True)
    event_type       = Column(String, nullable=False)
    # The ledger posting this event caused, or NULL when the cause legitimately
    # moved no money (a rollover continuation).
    posting_id       = Column(Uuid, nullable=True)
    amount_cents     = Column(BigInteger, nullable=False)
    created_at       = Column(DateTime(timezone=True), nullable=False)

    league   = relationship("League")
    instance = relationship("PoolInstance")


class PoolLegacyRolloverMigration(Base):
    """Immutable record of one league's legacy Worst Beat carry being retired.

    OWNER RULING, 2026-08-08. Worst Beat is retired (POR Rev1.3 §1.1) and must
    NOT be revived or mapped onto any Rev1.3 definition. A live legacy carry is
    therefore moved in full to `championship:{league_id}` — it never attaches to
    an active Pool definition and never creates a successor occurrence.

    ONE ROW PER LEAGUE, EVER. `migration_key` is deterministic — derived from
    the league id alone, never a timestamp and never a random value — and its
    UNIQUE constraint is what makes a retry harmless. A second execution
    collides here inside the same transaction as the ledger posting, so the
    whole retry rolls back and Championship cannot be credited twice.

    IMMUTABLE BY INTENT. Nothing in the codebase updates a row after insert.
    The record exists to answer, permanently, where a specific legacy balance
    went: which league, which source field, how much, to which account, under
    which idempotency identity.
    """
    __tablename__ = "pool_legacy_rollover_migration"
    __table_args__ = (
        UniqueConstraint("migration_key",
                         name="uq_pool_legacy_rollover_migration_key"),
        CheckConstraint("amount_cents > 0",
                        name="ck_pool_legacy_rollover_amount_positive"),
    )

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    migration_key       = Column(String, nullable=False)
    league_id           = Column(Integer, ForeignKey("leagues.id"),
                                 nullable=False)
    # The legacy field drained, named in full so the record is readable without
    # knowing this migration's source.
    source_field        = Column(String, nullable=False)
    # Which pool_pots weeks contributed, so the sum is reconstructable.
    source_weeks        = Column(JSON, nullable=False)
    amount_cents        = Column(BigInteger, nullable=False)
    destination_account = Column(String, nullable=False)
    posting_id          = Column(Uuid, nullable=False)
    migrated_at         = Column(DateTime(timezone=True), nullable=False)

    league = relationship("League")


class EconomyEvent(Base):
    """Exactly-once identity for every Sprint 5 weekly/season economic effect.

    Same pattern Sprint 4 proved on `pool_economic_event`: the row is inserted
    in the SAME transaction as the ledger posting it describes, so a replay
    collides at the constraint and the whole retry rolls back harmlessly. A row
    lock supplements this; it never replaces it.

    ONE DETERMINISTIC `event_key`, NOT A COMPOSITE OF NULLABLE COLUMNS. Sprint 4
    needed two partial unique indexes because its key had two shapes and NULLs
    are distinct in a PostgreSQL UNIQUE index — a combined constraint over a
    nullable column is silently inert. Sprint 5 has FOUR shapes:

        per-GM weekly     release, expiry, skunk obligation
        per-league weekly weekly skunk assessment marker
        per-GM season     opening allocation, expired-minimum reconciliation
        per-league season skunk distribution, championship distribution

    Four partial indexes, each having to name exactly the right IS NULL / IS NOT
    NULL combination, is four chances to write one that never fires. A single
    NOT NULL text key built by a pure function has none of that failure mode:
    uniqueness is total, and the shape is decided in Python where it can be
    unit-tested without a database. The descriptive columns are retained
    alongside for querying and audit, never for uniqueness.

    THE KEY IS RECOMPUTABLE FROM THE EVENT — never a timestamp, never a random
    value, never a retry counter. See economy/economy_events.py for the
    builders.
    """
    __tablename__ = "economy_event"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_economy_event_key"),
        CheckConstraint("amount_cents >= 0",
                        name="ck_economy_event_amount_nonneg"),
        Index("ix_economy_event_league_season", "league_id", "season"),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    event_key    = Column(String, nullable=False)
    league_id    = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    season       = Column(Integer, nullable=False)
    #: NULL for season-scoped events; a week number for weekly ones.
    week         = Column(Integer, nullable=True)
    #: NULL for league-scoped events; a team id for per-GM ones.
    team_id      = Column(Integer, ForeignKey("teams.id"), nullable=True)
    event_type   = Column(String, nullable=False)
    #: NULL when the event legitimately moved no money (a zero-assessment week).
    posting_id   = Column(Uuid, nullable=True)
    amount_cents = Column(BigInteger, nullable=False)
    created_at   = Column(DateTime(timezone=True), nullable=False)

    league = relationship("League")
    team   = relationship("Team")


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


# ── Settlement recovery audit ─────────────────────────────────────────────────

class SettlementRecoveryAudit(Base):
    """Append-only audit of authorized week-settlement recoveries (FR-8.7 §5b).
    One immutable row per recover_week() authorization — code INSERTs, never
    updates or deletes. Records who authorized the recovery, the operator-
    supplied process-exit evidence, and the structured pre-recovery facts
    observed under the week_settlements row lock at authorization time.

    exit_evidence and observed_pre_state are JSON columns — JSONB on Postgres,
    degrading to SQLAlchemy's generic JSON (TEXT-backed, native dict round-trip)
    on the SQLite test path, via JSON().with_variant(JSONB(), "postgresql").
    Python dicts are stored and read back directly; no manual json.dumps."""
    __tablename__ = "settlement_recovery_audit"

    id                           = Column(Integer,  primary_key=True, autoincrement=True)
    league_id                    = Column(Integer,  ForeignKey("leagues.id"), nullable=False)
    week                         = Column(Integer,  nullable=False)
    actor                        = Column(String,   nullable=False)   # who authorized the recovery
    exit_evidence                = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)   # {category, detail}
    observed_pre_state           = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)   # structured locked facts
    recovered_at                 = Column(DateTime(timezone=True), nullable=False)
    recovery_token_fingerprint   = Column(String,   nullable=False)   # one-way SHA-256 hash; never the live recovery credential
    prior_recovery_token_present = Column(Boolean,  nullable=False, default=False)   # was a stale token already on the row (prior recovery crashed)

    league = relationship("League")


# ── Season allocation (B2) ────────────────────────────────────────────────────

class SeasonAllocation(Base):
    """One row per team per league per season — the GM's season buy-in
    allocation, replacing the Stripe-mediated buy-in path.

    ROW EXISTENCE IS THE STATE. There is deliberately no status column
    (owner-ruled): an allocation for (league_id, team_id, season) either
    exists or it does not, and activate_season_allocation() derives every
    decision from that fact alone. No stripe_* column of any kind belongs
    here — this table is the replacement for that path, not a mirror of it.
    """
    __tablename__ = "season_allocation"
    __table_args__ = (
        UniqueConstraint("league_id", "team_id", "season",
                         name="uq_season_allocation_league_team_season"),
    )

    id            = Column(Integer,  primary_key=True, autoincrement=True)
    league_id     = Column(Integer,  ForeignKey("leagues.id", name="fk_season_allocation_league"), nullable=False)
    team_id       = Column(Integer,  ForeignKey("teams.id",   name="fk_season_allocation_team"),   nullable=False)
    season        = Column(Integer,  nullable=False)
    # B1 Discrete-Stop Economy Table SNAPSHOT — written once, at activation,
    # from whichever stop is active at that moment, and never updated
    # afterwards. Read back FROM THIS ROW, never from live config, so a
    # later economy-stop change cannot split one season's allocation across
    # two different stops. Same rationale as BuyInRecord's identical trio.
    buyin_cents   = Column(Integer,  nullable=False)
    # RENAMED from wallet_cents by S5-P1. Under owner ruling S5-R2 this
    # allocation goes to min_reserve:{team}, NOT to the Wallet, and the old
    # label would have gone on silently meaning Weekly Minimum Reserve. The
    # ARITHMETIC is unchanged (140 + 80 = 220) and so is the Top-Off cap
    # basis that reads this column; only the name now says what it holds.
    min_reserve_cents = Column(Integer,  nullable=False)
    reserve_cents = Column(Integer,  nullable=False)
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    league = relationship("League")
    team   = relationship("Team")


# ── Frozen top-off multiplier snapshot (B6 Group B) ───────────────────────────

class LeagueSeasonTopoffConfig(Base):
    """One row per league per season — the BAB Top-Off cap multiplier frozen
    at season activation (B6 §2.2).

    INSERT-ONLY. No application route, admin function or governed migration
    updates or deletes a row. Correcting a post-activation mistake requires a
    separately governed season-reset protocol, which is out of B6 scope. There
    is deliberately no updated_at, no version column and no status column: a
    row's existence and its single frozen value are the whole record.

    WHY ONE ROW PER LEAGUE-SEASON, NOT ONE PER TEAM. The multiplier could have
    been repeated on every SeasonAllocation row. Storing it exactly once is
    what makes divergence STRUCTURALLY IMPOSSIBLE (§2.3): with one row there is
    no pair of rows that can disagree, so no reconciliation code is needed and
    no drift is representable. SeasonAllocation carries no multiplier column of
    any name, and test S6 asserts that it never acquires one.

    UNIQUENESS IS DATABASE-ENFORCED. uq_lstc_league_season makes a duplicate
    league-season snapshot impossible by construction rather than by
    application check. Like uq_season_allocation_league_team_season, it is a
    FINAL DEFENSE-IN-DEPTH GUARD ONLY — activation serializes on the League
    row, so two concurrent activations never reach it, and its violation is
    never used as the idempotency path.

    SEASON is config.ALLOCATION_SEASON (2026), deliberately distinct from
    config.CURRENT_SEASON (2025, the projection-data year). A money event is
    stamped with the allocation season.

    THE COLUMN IS topoff_cap_multiplier_bps, matching League's column name
    exactly. The two are compared directly on every activation replay (§2.5),
    and an asymmetric name would invite a comparison against the wrong field.
    """
    __tablename__ = "league_season_topoff_config"
    __table_args__ = (
        UniqueConstraint("league_id", "season", name="uq_lstc_league_season"),
        CheckConstraint(
            "topoff_cap_multiplier_bps IN (0, 5000, 10000, 15000, 20000)",
            name="ck_lstc_multiplier_bps",
        ),
    )

    id                        = Column(Integer, primary_key=True, autoincrement=True)
    league_id                 = Column(Integer,
                                       ForeignKey("leagues.id", name="fk_lstc_league"),
                                       nullable=False)
    season                    = Column(Integer,  nullable=False)
    topoff_cap_multiplier_bps = Column(Integer,  nullable=False)
    created_at                = Column(DateTime, nullable=False,
                                       default=lambda: datetime.now(timezone.utc))

    league = relationship("League")


# ── Durable top-off disclosure (B6 Group C) ───────────────────────────────────

class TopOffDisclosure(Base):
    """One row per approved BAB Top-Off issuance — the durable, league-visible
    disclosure that the issuance happened (B6 §4.5).

    INSERT-ONLY. No update path, no delete path. Following the accepted
    LeagueSeasonTopoffConfig precedent, this is an APPLICATION CONTRACT enforced
    by write discipline and by the absence of any update/delete code path — not
    by a trigger, rule, or revoked grant. Group C adds no trigger and no event
    listener; the specification requires none.

    SELF-CONTAINED BY DESIGN. Every field needed to reconstruct the disclosure
    is denormalised into the row: league, season, team, amount, both identities,
    the classification, the reason, the decision time and the posting id.
    Reading this row years later requires NO join against mutable live state —
    which is the whole point, since teams are renamed, users change, and league
    configuration moves on. A normalised design would make an old disclosure
    mean something different later.

    event_id IS THE DURABLE IDENTITY, not the integer primary key.
    FaabTransaction.disclosure_event_id stores THIS UUID. The integer `id` is a
    storage detail and is never the linkage value — test S13 asserts exactly
    that distinction, because storing the PK there would look correct in every
    single-row test and silently break the provenance chain (§4.7) in practice.

    faab_transaction_id is UNIQUE, so one request yields at most one disclosure.

    Nothing in Group C WRITES this table. §4.5 requires the row to be written
    INSIDE the approval transaction, so that a failed disclosure write rolls the
    entire issuance back and money never moves without its disclosure. That is
    the Group E issuance service.
    """
    __tablename__ = "top_off_disclosure"
    __table_args__ = (
        UniqueConstraint("event_id",            name="uq_topoff_disclosure_event_id"),
        UniqueConstraint("faab_transaction_id", name="uq_topoff_disclosure_faab_tx"),
        # §5.3 — a self-approved issuance REQUIRES a non-empty reason. Enforced
        # at the database because it is one of the structural compensating
        # controls that stand in for independent review (§5.4), not a UI nicety.
        # A non-self-approved row needs no reason, and none is required
        # elsewhere by the controlling text.
        #
        # §4.5 writes this as length(trim(decision_reason)) > 0. Implemented
        # literally that is INSUFFICIENT: on both PostgreSQL 16 and SQLite,
        # trim() with no character set strips SPACES ONLY, so a reason of tabs
        # and newlines survives with a non-zero length and a whitespace-only
        # justification would satisfy the control. The tab/newline/carriage
        # return are therefore folded to spaces before trimming.
        #
        # replace()+trim() rather than btrim()/regex: btrim is PostgreSQL-only
        # and raises "no such function" when SQLAlchemy emits this same CHECK
        # into SQLite's CREATE TABLE, which api/main.py's create_all() does on
        # the default fallback database. Verified equivalent on PostgreSQL 16
        # and SQLite: NULL, empty and whitespace-only all rejected.
        CheckConstraint(
            "NOT self_approved OR (decision_reason IS NOT NULL AND length(trim("
            "replace(replace(replace(decision_reason, '\t', ' '), '\n', ' '), '\r', ' ')"
            ")) > 0)",
            name="ck_topoff_disclosure_selfapproval_reason",
        ),
    )

    id                  = Column(Integer,  primary_key=True, autoincrement=True)
    event_id            = Column(Uuid,     nullable=False)
    faab_transaction_id = Column(Integer,
                                 ForeignKey("faab_transactions.id",
                                            name="fk_topoff_disclosure_faab_tx"),
                                 nullable=False)
    league_id           = Column(Integer,
                                 ForeignKey("leagues.id", name="fk_topoff_disclosure_league"),
                                 nullable=False)
    season              = Column(Integer,  nullable=False)
    team_id             = Column(Integer,
                                 ForeignKey("teams.id", name="fk_topoff_disclosure_team"),
                                 nullable=False)
    amount_cents        = Column(Integer,  nullable=False)
    requester_user_id   = Column(Integer,
                                 ForeignKey("users.id", name="fk_topoff_disclosure_requester"),
                                 nullable=False)
    decided_by_user_id  = Column(Integer,
                                 ForeignKey("users.id", name="fk_topoff_disclosure_decided_by"),
                                 nullable=False)
    self_approved       = Column(Boolean,  nullable=False)
    decision_reason     = Column(Text,     nullable=True)
    decided_at          = Column(DateTime, nullable=False)
    # Uuid, NOT NULL — a disclosure only exists for a posted issuance. No
    # ForeignKey, for the same §4.7 reason as FaabTransaction.ledger_posting_id.
    ledger_posting_id   = Column(Uuid,     nullable=False)
    created_at          = Column(DateTime, nullable=False,
                                 default=lambda: datetime.now(timezone.utc))

    # No User relationships: two FKs to users.id would make an unqualified
    # relationship ambiguous, and Group C needs none.
    faab_transaction = relationship("FaabTransaction")
    league           = relationship("League")
    team             = relationship("Team")


# ── Commissioner authority ────────────────────────────────────────────────────

class LeagueCommissioner(Base):
    """Local, enforceable record that a user may administer a league.

    THE AUTHORIZATION KEYS ARE LOCAL IDS. Authorization is decided by the
    presence of a (league_id, user_id) row here — never by User.role alone,
    never by team ownership, and never by any Yahoo identifier. Commissioner
    authority is deliberately INDEPENDENT of User.team_id: a commissioner need
    not own a team in the league they administer.

    CARDINALITY IS MANY-TO-MANY. One user may hold rows for several leagues,
    and one league may have several commissioners or co-commissioners. The
    unique constraint prevents only a duplicate of the SAME pair.

    `source` records where the authority came from:
      yahoo_sync   — reconciled from Yahoo's commissioner designation.
                     Yahoo reconciliation is NOT built; no row carries this
                     value yet.
      local_grant  — granted inside FantasyStakes by an existing authority,
                     recorded in assigned_by_user_id.
      bootstrap    — temporary authority recorded at a first trusted import.
                     NOT built: it requires a per-user Yahoo credential
                     binding that does not exist. See the addendum.

    `assigned_by_user_id` is nullable because bootstrap and Yahoo-derived rows
    have no granting user. It is not an audit log — this package deliberately
    implements no revocation history.

    Yahoo reconciliation identifiers belong on User and League, not here: this
    table's job is local authorization, and substituting a remote identifier
    for a local FK would make authorization depend on an unreconciled system.
    """
    __tablename__ = "league_commissioners"
    __table_args__ = (
        UniqueConstraint("league_id", "user_id",
                         name="uq_league_commissioner_league_user"),
        CheckConstraint("source IN ('yahoo_sync','local_grant','bootstrap')",
                        name="ck_league_commissioner_source"),
    )

    id                  = Column(Integer,  primary_key=True, autoincrement=True)
    league_id           = Column(Integer,  ForeignKey("leagues.id", name="fk_league_commissioner_league"),
                                 nullable=False)
    user_id             = Column(Integer,  ForeignKey("users.id",   name="fk_league_commissioner_user"),
                                 nullable=False)
    source              = Column(String,   nullable=False)
    assigned_by_user_id = Column(Integer,  ForeignKey("users.id",   name="fk_league_commissioner_assigned_by"),
                                 nullable=True)
    created_at          = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                                 nullable=False)

    league      = relationship("League")
    user        = relationship("User", foreign_keys=[user_id])
    assigned_by = relationship("User", foreign_keys=[assigned_by_user_id])


# ── SPEC 2 · Package 2B Group 1 — event / batch / provenance foundation ───────
#
# THE TOPOLOGY IS RULING 1's, NOT SPEC 2 §7's. The Foundation Correction Plan
# (spec/FantasyBeefs_Foundation_Correction_Plan_2026-07-21.md, Ruling 1)
# SUPERSEDES Spec 2 §7's ledger-linkage recommendation, and Spec 2 records that
# supersession inline as binding. Three durable tiers, each owning exactly one
# identity concern:
#
#     ProtocolEvent  1 → many  LedgerPostingBatch  1 → many  LedgerEntry
#
#   ProtocolEvent       the SINGLE idempotency authority, UNIQUE(event_id),
#                       generalized across every governed money operation.
#   LedgerPostingBatch  the balanced accounting-transaction identity. The
#                       existing posting_id is retained as this batch identity
#                       and is durably associated with its governing event.
#   LedgerEntry         stays a simple accounting leg (it lives on the ledger's
#                       own declarative base, in ledger/ledger.py).
#
# Idempotency asks "does this ProtocolEvent exist", never "is this ledger row
# unique". There is NO LedgerEntry-level uniqueness authority for event_id, and
# Group 1 introduces none.
#
# GROUP 1 DEFINES DURABLE REPRESENTATION ONLY. No funding behaviour, no escrow,
# no orchestrator, no route. Those are later Package 2B groups.


class ProtocolEvent(Base):
    """The single authoritative idempotency identity for a governed operation.

    RULING 1: "a generalized, persistent domain-event record … the single
    idempotency authority, with a database-enforced UNIQUE(event_id). It must
    support challenge, Beef, pool, buy-in, settlement, shortfall, and any other
    governed money operation — not challenges only."

    GENERALIZATION IS WHY event_type CARRIES NO RESTRICTIVE CHECK. Spec 2 §7
    described a challenge-scoped table whose event_type was CHECKed against six
    challenge verbs; Ruling 1 supersedes that section and requires the table to
    serve every domain. A six-value CHECK would make the generalization
    unimplementable, so the vocabulary is owned by the calling domain. The six
    challenge verbs are named as constants below for the later groups.

    ONE EVENT MAY OWN SEVERAL BATCHES. "One event may produce several balanced
    posting batches during a complex atomic operation" — Locked acceptance is
    exactly that: true-up, Anchor migration and Derived funding are three
    balanced batches under one challenge_accept event.

    SPEC 2 §7's `ledger_posting_ids` COLUMN IS DELIBERATELY ABSENT. Under
    Ruling 1 the batch points UP to its event, so an array of posting ids on the
    event would be a second, divergeable home for the same relationship.

    challenge_id and proposal_id are NULLABLE because a settlement, pool or
    buy-in event has neither. They are the challenge domain's convenience
    linkage, not a constraint on what this table may record.
    """
    __tablename__ = "protocol_events"
    __table_args__ = (
        # THE idempotency authority. Database-enforced, per Ruling 1.
        UniqueConstraint("event_id", name="uq_protocol_event_event_id"),
        Index("ix_protocol_event_type_created", "event_type", "created_at"),
        Index("ix_protocol_event_challenge", "challenge_id"),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    # Caller-visible, caller-supplied. A repeated delivery of the same event_id
    # must return the ORIGINAL committed result and post nothing new.
    event_id   = Column(Uuid,    nullable=False)
    event_type = Column(String,  nullable=False)

    # Challenge-domain linkage — nullable by generalization (see docstring).
    challenge_id = Column(Integer, ForeignKey("beef_challenges.id",
                                              name="fk_protocol_event_challenge"),
                          nullable=True)
    proposal_id  = Column(Integer, ForeignKey("beef_proposals.id",
                                              name="fk_protocol_event_proposal"),
                          nullable=True)

    # Who acted: a team id rendered as text, or the literal 'system' for
    # system-owned transitions such as expiry. Text because the actor is not
    # always a team, and a FK would forbid 'system'.
    actor_identity = Column(String, nullable=True)

    league_id = Column(Integer, ForeignKey("leagues.id",
                                           name="fk_protocol_event_league"),
                       nullable=True)
    season    = Column(Integer, nullable=True)
    week      = Column(Integer, nullable=True)

    effective_at    = Column(DateTime, nullable=True)
    prior_state     = Column(String,   nullable=True)
    resulting_state = Column(String,   nullable=True)
    # Success, or a deterministic failure code such as 'reconciliation_error'
    # or 'insufficient_acceptance_capacity' (Spec 2 §11, §12).
    result_code     = Column(String,   nullable=True)
    spec_version    = Column(String,   nullable=True)
    created_at      = Column(DateTime, nullable=False,
                             default=lambda: datetime.now(timezone.utc))

    challenge = relationship("BeefChallenge", foreign_keys=[challenge_id])
    proposal  = relationship("BeefProposal",  foreign_keys=[proposal_id])
    league    = relationship("League",        foreign_keys=[league_id])
    batches   = relationship("LedgerPostingBatch", back_populates="protocol_event")


# The six challenge protocol-event verbs (Spec 2 §7). Named here so later
# groups share one spelling; deliberately NOT a database CHECK — see the
# ProtocolEvent docstring on why generalization forbids constraining the column.
CHALLENGE_EVENT_TYPES = (
    "challenge_issue",
    "challenge_counter",
    "challenge_accept",
    "challenge_decline",
    "challenge_cancel",
    "challenge_expire",
)


class LedgerPostingBatch(Base):
    """One balanced accounting transaction, owned by one ProtocolEvent.

    RULING 1: "the balanced accounting-transaction identity. The existing
    posting_id is retained as this batch identity, but it must be durably
    associated with its governing ProtocolEvent. One batch contains multiple
    ledger legs and sums to zero."

    posting_id IS THE SAME UUID ledger.post() already mints and stamps on every
    LedgerEntry of the posting. It is not a new identifier — it is the existing
    one, given a durable home and an owner. UNIQUE here because one posting_id
    is exactly one batch; that is a structural fact about the ledger, not an
    idempotency rule, and it must not be mistaken for one: idempotency lives on
    ProtocolEvent.event_id and nowhere else.

    NO FOREIGN KEY POINTS AT ledger_entries, in either direction. LedgerEntry
    sits on the ledger's own declarative base (ledger/ledger.py's _LedgerBase),
    a separate metadata from this one — the same reason B6 §4.7 gave for
    FaabTransaction.ledger_posting_id carrying no FK. The link is by value:
    LedgerEntry.batch_id equals this row's id.
    """
    __tablename__ = "ledger_posting_batches"
    __table_args__ = (
        # One posting_id is one batch. A structural fact, NOT an idempotency
        # authority — that is ProtocolEvent.event_id's alone.
        UniqueConstraint("posting_id", name="uq_ledger_posting_batch_posting_id"),
        Index("ix_ledger_posting_batch_event", "protocol_event_id"),
    )

    id                = Column(Integer, primary_key=True, autoincrement=True)
    posting_id        = Column(Uuid,    nullable=False)
    protocol_event_id = Column(Integer,
                               ForeignKey("protocol_events.id",
                                          name="fk_ledger_posting_batch_event"),
                               nullable=False)
    # Denormalised from the entries this batch owns, which all share one door by
    # construction — post() takes exactly one. Descriptive only; the entries'
    # own `door` remains what the funded-balance guard reads.
    door       = Column(String,   nullable=False)
    created_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.now(timezone.utc))

    protocol_event = relationship("ProtocolEvent", back_populates="batches")


class ChallengeFundingLeg(Base):
    """Spec 2 §5 — ordered, append-only source-funding provenance.

    WHY ORDERED LEGS AND NOT RUNNING TOTALS. §5: "Cumulative totals are
    insufficient. Strict reverse-order refund (§11) needs the exact leg
    sequence, which two running totals cannot reconstruct." A refund replays
    actual history backwards; it never divides proportionally, because
    proportional division invents rounding questions and describes movements
    that never happened.

    NEVER MUTATED. A reversal is a NEW row, not an edit. `fund` legs carry a
    positive amount_cents, `reverse` legs a negative one, and every `reverse`
    row names the exact `fund` row it draws from through
    reverses_funding_leg_id.

    remaining_reversible_cents IS DERIVED, NOT STORED, and that is §5's explicit
    design:

        remaining_reversible_cents(fund_leg) =
            fund_leg.amount_cents
            − SUM(abs(r.amount_cents) for r where r.reverses_funding_leg_id == fund_leg.id)

    Storing it would create a second, divergeable truth for something the rows
    already determine. The linkage plus this formula is what makes each partial
    reversal provably exact — sequence_number alone cannot tell how much of a
    partially-consumed leg remains, so repeated partial reductions could
    otherwise double-reverse one leg or skip another.

    GROUP 1 DEFINES THE REPRESENTATION ONLY. No funding, splitting, reversing or
    reconciling behaviour exists yet; that is a later Package 2B group. What is
    enforced here is structural: ordering uniqueness, the fund/reverse linkage
    biconditional, and the sign contract.
    """
    __tablename__ = "challenge_funding_legs"
    __table_args__ = (
        # §5 — sequence_number is monotonic WITHIN a challenge and is the order
        # a refund replays backwards. Uniqueness is what stops two writers
        # minting the same position.
        UniqueConstraint("challenge_id", "sequence_number",
                         name="uq_challenge_funding_leg_sequence"),
        CheckConstraint(
            "leg_kind IN ('fund','reverse')",
            name="ck_challenge_funding_leg_kind",
        ),
        # §5 — "null for `fund` legs, required for `reverse` legs". Stated as a
        # biconditional so neither half can drift: a fund leg carrying a
        # reversal target, and a reverse leg without one, are both
        # unrepresentable.
        CheckConstraint(
            "(leg_kind = 'fund'    AND reverses_funding_leg_id IS NULL) "
            "OR (leg_kind = 'reverse' AND reverses_funding_leg_id IS NOT NULL)",
            name="ck_challenge_funding_leg_reversal_linkage",
        ),
        # §5 — "positive = funded, negative = reversed". A zero-amount leg is
        # meaningless in either direction and is excluded by both branches.
        CheckConstraint(
            "(leg_kind = 'fund'    AND amount_cents > 0) "
            "OR (leg_kind = 'reverse' AND amount_cents < 0)",
            name="ck_challenge_funding_leg_amount_sign",
        ),
        Index("ix_challenge_funding_leg_challenge_seq",
              "challenge_id", "sequence_number"),
        Index("ix_challenge_funding_leg_reverses", "reverses_funding_leg_id"),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    challenge_id = Column(Integer,
                          ForeignKey("beef_challenges.id",
                                     name="fk_challenge_funding_leg_challenge"),
                          nullable=False)
    # The funding side. Whose sources this leg drew from — always the Anchor
    # team for issue and true-up legs, the Derived team for Derived funding.
    team_id      = Column(Integer,
                          ForeignKey("teams.id",
                                     name="fk_challenge_funding_leg_team"),
                          nullable=False)

    # Strict order within the challenge's funding history (§5).
    sequence_number = Column(Integer, nullable=False)

    # Ledger account strings, recorded verbatim so the leg reproduces the exact
    # historical movement: 'min:{team}:{week}' or 'wallet:{team}' as the source,
    # 'escrow:challenge:{id}' or an escrow:{bet_id} as the destination.
    source_account      = Column(String, nullable=False)
    destination_account = Column(String, nullable=False)

    # INTEGER CENTS — authoritative (§6). Positive funds, negative reverses.
    amount_cents = Column(Integer, nullable=False)
    leg_kind     = Column(String,  nullable=False)   # CHECK ('fund','reverse')

    # The exact original `fund` leg a `reverse` leg draws from (§5).
    reverses_funding_leg_id = Column(
        Integer,
        ForeignKey("challenge_funding_legs.id",
                   name="fk_challenge_funding_leg_reverses"),
        nullable=True,
    )

    # Provenance linkage into the event/batch topology.
    posting_id        = Column(Uuid, nullable=False)   # the batch's posting_id
    posting_batch_id  = Column(Integer,
                               ForeignKey("ledger_posting_batches.id",
                                          name="fk_challenge_funding_leg_batch"),
                               nullable=True)
    protocol_event_id = Column(Integer,
                               ForeignKey("protocol_events.id",
                                          name="fk_challenge_funding_leg_event"),
                               nullable=False)

    created_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.now(timezone.utc))

    challenge      = relationship("BeefChallenge", foreign_keys=[challenge_id])
    team           = relationship("Team",          foreign_keys=[team_id])
    reverses       = relationship("ChallengeFundingLeg", remote_side=[id])
    posting_batch  = relationship("LedgerPostingBatch",
                                  foreign_keys=[posting_batch_id])
    protocol_event = relationship("ProtocolEvent",
                                  foreign_keys=[protocol_event_id])


class ChallengeFinalLock(Base):
    """Rev 9 §7.3 FINALSTATE-A — the immutable frozen Final-Lock result.

    ONE PER CHALLENGE, STRUCTURALLY. `UNIQUE(challenge_id)` makes that a
    constraint rather than a convention, so a second Final Lock for one challenge
    is unrepresentable even if every application guard were bypassed.

    THIS IS THE *RESULT*; ChallengeFinalLockClaim IS THE *EXECUTION RIGHT*.
    Separate records with separate lifetimes: a claim may be reclaimed and
    retried several times, but at most one result is ever written.

    NO NEW `BeefChallenge.response_status` VALUE ACCOMPANIES THIS (§7.3).
    `ck_beef_response_status` is a closed six-value CHECK that Spec 1 §4
    partitions into open / negotiation-terminal / accepted, and every lifecycle
    path branches on that partition; a seventh member forces a partition question
    with no good answer. Authoritative completion is exactly two facts: this row
    exists, and the governing claim is 'completed'. A status value would be a
    third representation of the same thing.

    Insert-only. Never updated after creation.
    """
    __tablename__ = "challenge_final_locks"
    __table_args__ = (
        UniqueConstraint("challenge_id", name="uq_challenge_final_lock_challenge"),
        # Exposure never grows (§0): each side's final is bounded by its ceiling,
        # and the derived side additionally never exceeds its raw derivation.
        CheckConstraint(
            "anchor_cents >= 0 AND derived_final_cents >= 0 "
            "AND derived_raw_cents >= 0 AND derived_final_cents <= derived_raw_cents",
            name="ck_challenge_final_lock_amounts",
        ),
        Index("ix_challenge_final_lock_challenge", "challenge_id"),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    challenge_id = Column(Integer,
                          ForeignKey("beef_challenges.id",
                                     name="fk_challenge_final_lock_challenge"),
                          nullable=False)
    final_locked_at = Column(DateTime, nullable=False,
                             default=lambda: datetime.now(timezone.utc))

    # ── Model provenance — WHAT ACTUALLY EXECUTED ──
    # Written from the config the Final-Lock run actually resolved and used, then
    # asserted equal to the challenge's Handshake-frozen identity. Copying the
    # promised id across would record an intention rather than an observation,
    # and the whole point of the hash is to catch the case where those differ.
    executed_model_version_id  = Column(String, nullable=False)
    executed_model_config_hash = Column(String, nullable=False)
    # The simulation count the executed config actually used. Recorded because
    # "one official simulation under the frozen model" is a claim the audit
    # record should be able to evidence, not merely assert — this is the
    # executed config's n_sims, so a record whose count disagrees with the
    # resolved version's is self-evidently inconsistent.
    simulations                = Column(Integer, nullable=False, default=0)
    # The projection dataset actually read AT FINAL LOCK. Deliberately separate
    # from the model identity: the model is frozen, the projections are live, and
    # recording both is what makes the run reproducible after the fact.
    projection_source_id       = Column(String,   nullable=True)
    projection_dataset_version = Column(String,   nullable=True)
    projection_captured_at     = Column(DateTime, nullable=True)

    # ── Frozen official probabilities and odds ──
    p_issuer_final    = Column(Float,   nullable=False)
    p_opponent_final  = Column(Float,   nullable=False)
    issuer_moneyline  = Column(Integer, nullable=True)
    opponent_moneyline = Column(Integer, nullable=True)

    # ── Frozen money, INTEGER CENTS (§6) ──
    anchor_cents        = Column(Integer, nullable=False)  # issuer final == Anchor
    derived_raw_cents   = Column(Integer, nullable=False)  # pre-cap, for audit
    derived_final_cents = Column(Integer, nullable=False)  # post-cap
    ceiling_applied     = Column(Boolean, nullable=False, default=False)
    derived_refund_cents      = Column(Integer, nullable=False, default=0)
    final_funded_escrow_cents = Column(Integer, nullable=False)

    # ── Frozen market terms / covered entities ──
    wager_type   = Column(String, nullable=True)
    line         = Column(Float,  nullable=True)
    side         = Column(String, nullable=True)
    # PLAIN FKs, NOT use_alter. The beef_challenges<->bets pair needs use_alter
    # because it is a genuine cycle; this table only points AT bets and nothing
    # points back, so there is no cycle to break. That matters for more than
    # tidiness: `Table.create(bind=conn)` does not emit use_alter constraints —
    # they are added by create_all()'s separate ALTER pass — so a use_alter FK
    # here would exist on a clean install and be silently absent on the migration
    # upgrade path, leaving the two schemas subtly different.
    anchor_bet_id  = Column(Integer, ForeignKey("bets.id",
                                                name="fk_final_lock_anchor_bet"),
                            nullable=True)
    derived_bet_id = Column(Integer, ForeignKey("bets.id",
                                                name="fk_final_lock_derived_bet"),
                            nullable=True)

    # ── Governing event linkage ──
    protocol_event_id = Column(Integer,
                               ForeignKey("protocol_events.id",
                                          name="fk_challenge_final_lock_event"),
                               nullable=False)

    created_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.now(timezone.utc))

    challenge      = relationship("BeefChallenge", foreign_keys=[challenge_id])
    protocol_event = relationship("ProtocolEvent", foreign_keys=[protocol_event_id])


class ChallengeFinalLockClaim(Base):
    """Rev 9 §5.2 — the durable Final-Lock EXECUTION RIGHT.

    `UNIQUE(challenge_id)` IS THE MUTEX, and it is the whole reason this table
    exists. `ProtocolEvent.UNIQUE(event_id)` cannot serve: two workers presenting
    DIFFERENT event UUIDs for the SAME challenge both satisfy event-id
    uniqueness, and absent a challenge-scoped claim both would proceed to
    simulate, adjust and refund (§5.8). The key is `challenge_id` ALONE on a
    dedicated table rather than `(challenge_id, kind)` on a shared one: a kind
    column would weaken the statement from "one Final-Lock execution per
    challenge, forever" to "one per kind", and would silently admit a second row
    the day a second kind appeared.

    THREE STATES, NOT FOUR (§5.3). `in_progress` is deliberately absent because
    it is unobservable under a two-phase commit: to be read it must be committed,
    but Phase 2 is one transaction, so writing it at the start rolls back with
    everything else on failure and is overwritten by 'completed' on success.
    Retaining an unreachable member in a money-path CHECK invites a branch that
    can never execute.

    HALF-COMPLETION IS UNREPRESENTABLE. The two biconditional CHECKs bind
    'completed' to both `completed_at` and `final_lock_id` in the database, not
    in application convention, so a claim cannot claim success without pointing
    at the result that justifies it.
    """
    __tablename__ = "challenge_final_lock_claims"
    __table_args__ = (
        # THE MUTEX (§5.2). Named exactly as the accepted review specifies.
        UniqueConstraint("challenge_id",
                         name="uq_challenge_final_lock_claim_challenge"),
        CheckConstraint(
            "status IN ('claimed','completed','failed')",
            name="ck_challenge_final_lock_claim_status",
        ),
        # §5.3 — biconditionals, so neither half can drift from the other.
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="ck_challenge_final_lock_claim_completed_at",
        ),
        CheckConstraint(
            "(status = 'completed') = (final_lock_id IS NOT NULL)",
            name="ck_challenge_final_lock_claim_final_lock",
        ),
        CheckConstraint("attempt_count >= 1",
                        name="ck_challenge_final_lock_claim_attempts"),
        Index("ix_challenge_final_lock_claim_status", "status"),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    challenge_id = Column(Integer,
                          ForeignKey("beef_challenges.id",
                                     name="fk_challenge_final_lock_claim_challenge"),
                          nullable=False)
    status       = Column(String, nullable=False, default="claimed")

    # Ownership. `claimed_by` is the worker identity currently holding execution.
    claimed_by   = Column(String,   nullable=False)
    claimed_at   = Column(DateTime, nullable=False)
    # Staleness is DATA, not a hardcoded guess evaluated at read time (§5.4).
    # MUST be refreshed on reclaim — a reclaim inheriting an expired timestamp
    # hands the new owner an already-stale claim, and a third worker could take
    # it out from underneath them while they run (§5.2).
    claim_expires_at = Column(DateTime, nullable=False)

    attempt_count       = Column(Integer,  nullable=False, default=1)
    previous_claimed_by = Column(String,   nullable=True)
    last_reclaimed_at   = Column(DateTime, nullable=True)
    # Set with status='failed'; cleared on reclaim. `failed` is an ATTEMPT
    # outcome, not a challenge outcome (§5.3).
    failure_reason      = Column(String,   nullable=True)

    completed_at  = Column(DateTime, nullable=True)
    final_lock_id = Column(Integer,
                           ForeignKey("challenge_final_locks.id",
                                      name="fk_challenge_final_lock_claim_result"),
                           nullable=True)
    # Written by Phase 2 completion ONLY — never at acquisition or reclaim
    # (§5.2). It records which DELIVERY performed the execution; it is not the
    # mutex.
    protocol_event_id = Column(Integer,
                               ForeignKey("protocol_events.id",
                                          name="fk_challenge_final_lock_claim_event"),
                               nullable=True)

    created_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=True)

    challenge      = relationship("BeefChallenge",      foreign_keys=[challenge_id])
    final_lock     = relationship("ChallengeFinalLock", foreign_keys=[final_lock_id])
    protocol_event = relationship("ProtocolEvent",      foreign_keys=[protocol_event_id])


# ── Sprint 6 · provider conflict (S6-R3, §10) ─────────────────────────────────

class ProviderConflict(Base):
    """A provider assertion that CONTRADICTS already-final, load-bearing state.

    S6-R3: once provider state is economically final or load-bearing, a later
    provider refresh that disagrees must NOT silently mutate it. The refresh
    fails closed, the stored final value stands unchanged, and the disagreement
    is recorded here as a durable, named fact.

    NOT A WORKFLOW ENGINE. There is exactly one lifecycle transition —
    unresolved to acknowledged — and it carries who did it and why. Sprint 6
    deliberately builds NO automatic economic reversal: acknowledging a conflict
    records that a human looked at it, and never moves a cent.

    THE CONFLICT KEY IS THE IDEMPOTENCY UNIT. `conflict_key` is derived
    deterministically from (provider, external identity, conflict type, the
    existing value, the contradicting value), so re-ingesting the SAME
    contradiction a hundred times finds the same row a hundred times.
    `occurrence_count` and `last_seen_at` record the repeats; the UNIQUE
    constraint is what stops them becoming a hundred rows. A DIFFERENT
    contradiction — a third value for the same fact — has a different key and is
    legitimately its own row, because it is genuinely new information.

    UNRESOLVED BLOCKS SEASON CLOSE (§11). economy/season_close_orchestrator.py
    reads this table as an additive precondition. That is the whole reason the
    record is persistent rather than a log line: a season must not be able to
    close over a contradiction nobody ever looked at.
    """
    __tablename__ = "provider_conflict"
    __table_args__ = (
        UniqueConstraint("conflict_key", name="uq_provider_conflict_key"),
        CheckConstraint(
            "conflict_type IN ('POST_FINAL_SCORE','POST_FINAL_WINNER',"
            "'POST_FINAL_FINALITY_RETRACTION','FROZEN_SEASON_BOUNDARY',"
            "'IDENTITY_CONFLICT')",
            name="ck_provider_conflict_type",
        ),
        # Acknowledgement is all-or-nothing: a row is either unresolved with no
        # acknowledgement metadata, or acknowledged with both stamps present.
        # Biconditionals rather than two independent nullables, so a half-filled
        # acknowledgement cannot exist to be misread as resolved.
        CheckConstraint(
            "(resolved_at IS NOT NULL) = (resolved_by IS NOT NULL)",
            name="ck_provider_conflict_resolution_pair",
        ),
        CheckConstraint("occurrence_count >= 1",
                        name="ck_provider_conflict_occurrences"),
        Index("ix_provider_conflict_open", "league_id", "resolved_at"),
    )

    id        = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    provider  = Column(String, nullable=False)

    #: The provider's own stable key for the contradicted thing — a matchup key,
    #: a league key. Never a name, never an internal id alone.
    external_identity = Column(String, nullable=False)
    conflict_type     = Column(String, nullable=False)

    #: What the system already holds and refuses to overwrite, and what the
    #: provider claimed instead. Text, because the contradicted fact may be a
    #: score, a team id, a week number or a timestamp, and rendering all of them
    #: through one column keeps the conflict record readable without a join.
    existing_value      = Column(Text, nullable=False)
    provider_value      = Column(Text, nullable=False)
    contradicted_field  = Column(String, nullable=False)

    #: Deterministic idempotency key — see the class docstring.
    conflict_key = Column(String, nullable=False)

    detected_at      = Column(DateTime(timezone=True), nullable=False)
    last_seen_at     = Column(DateTime(timezone=True), nullable=False)
    occurrence_count = Column(Integer, nullable=False, default=1,
                              server_default=text("1"))

    resolved_at   = Column(DateTime(timezone=True), nullable=True)
    resolved_by   = Column(String, nullable=True)
    resolution_note = Column(Text, nullable=True)

    #: Free-form audit payload — season, week, fixture id, whatever the
    #: detecting path knew. Never read for a decision; present so an operator
    #: can reconstruct the ingestion that produced the contradiction.
    audit_metadata = Column(JSON, nullable=True)

    league = relationship("League")

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None


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
