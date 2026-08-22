"""
ECONCFG-F1 — the commissioner's league-season economy configuration.

WHAT THIS MODULE IS. Validation, defaults, derivation and the activation freeze
for the three commissioner economy inputs, plus the pure arithmetic that turns
them into a Season-Opening Allocation. It reads the connected league's own
settings for the week count and it writes exactly one immutable row per
league-season.

WHAT THIS MODULE IS NOT, AND THE DISTINCTION IS THE WHOLE POINT OF STEP 1:

    IT ISSUES NOTHING. No ledger posting, no Credit, no wallet, no reserve. It
    can COMPUTE a Season-Opening Allocation and it is not the authority that
    funds one. `payments/economy_config.py`'s fixed five-stop table remains the
    live issuance source until a later, deliberate economic package switches it.

That separation is uncomfortable on purpose. A configuration row existing must
never be mistakable for live parameterized economics, so the two are kept apart
by construction — nothing in `economy/season_allocation.py`'s posting path reads
anything from this module — and a certification case asserts it directly.

── ONE ROW, TWO STATES ──────────────────────────────────────────────────────

    LeagueSeasonEconomyConfig, frozen_at NULL    the editable draft
    LeagueSeasonEconomyConfig, frozen_at set     the immutable record

A mutable draft on `leagues` plus an insert-only copy here — the
`topoff_cap_multiplier_bps` -> `LeagueSeasonTopoffConfig` shape — was built
first and withdrawn. Three extra columns on `leagues` pushed that table's
row-lock SELECT past `track_activity_query_size`, and that budget is spent by
the certified concurrency suites proving WHICH lock a blocked backend awaits.
Season-scoped configuration belongs on a season-scoped table regardless.

── ABSENCE IS A GOVERNED STATE ──────────────────────────────────────────────

A league-season with NO ROW is UNCONFIGURED. Activation writes nothing for it
and behaves exactly as it did before this package. Every season activated before
ECONCFG-F1 is in that state, and none is migrated, backfilled or reinterpreted —
which is what lets this foundation land without touching a single historical
Credit.

── THE WEEK COUNT IS DERIVED, NEVER ASSUMED ─────────────────────────────────

    regular_season_week_count = playoff_start_week - start_week

Both come from the connected league's own settings. `start_week` is NOT assumed
to be 1, no count is inferred from team count or from a matchup total, and 14 is
not written down anywhere in this file. A league missing either boundary cannot
freeze — a named refusal, not a default.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

#: One Credit, in the integer cents every money path in this repository uses.
#: Named rather than inlined so the whole-Credit rule below reads as the rule it
#: enforces instead of as an unexplained 100.
CENTS_PER_CREDIT = 100

# ── Governed commissioner ranges (ECON-CONFIG-R1/R2/R3) ──────────────────────
#
# Stated in Credits beside the cents so the governed figure and the stored unit
# can be checked against each other by eye. These are the RANGES a commissioner
# may choose within; they are emphatically not an economy.
MIN_WEEKLY_BET_MINIMUM_CENTS = 100          # $1
MAX_WEEKLY_BET_MINIMUM_CENTS = 10_000       # $100
MIN_CHAMPIONSHIP_CONTRIBUTION_CENTS = 100   # $1
MAX_CHAMPIONSHIP_CONTRIBUTION_CENTS = 100_000   # $1,000
# FINAL POR §9D — ZERO IS A GOVERNED CHOICE, NOT AN ABSENT SETTING.
#
# Skunk Fees are OPTIONAL. A commissioner who sets 0 has decided the league
# plays without them, and that decision must be expressible: with a $1 floor the
# only way to "turn Skunk off" was to leave the economy unconfigured, which
# turns off the whole configured economy with it.
#
# ZERO ALSO SWITCHES OFF THE POINTS CHAMPIONSHIP, because the Points pot is the
# Skunk actually assessed and a league that assesses none has no pot. That
# consequence is the POR's and is derived from this number rather than from a
# second flag that could disagree with it.
MIN_SKUNK_FEE_CENTS = 0                     # Skunk Fees are optional (§9D)
MAX_SKUNK_FEE_CENTS = 10_000                # $100

# ── Setup defaults ───────────────────────────────────────────────────────────
#
# SETUP DEFAULTS ONLY, NOT ECONOMIC CONSTANTS. These reproduce the product's
# historical shape for a fourteen-week regular season — 10 x 14 + 80 = 220 — but
# NONE of 220, 140 or 14 is encoded anywhere in this module. The 220 is an
# arithmetic consequence of a default meeting a derived week count, and a
# thirteen-week league reaches 210 through the same line of code.
DEFAULT_WEEKLY_BET_MINIMUM_CENTS = 1_000        # $10
DEFAULT_CHAMPIONSHIP_CONTRIBUTION_CENTS = 8_000  # $80
DEFAULT_SKUNK_FEE_CENTS = 1_000                  # $10

REASON_OUT_OF_RANGE = "ECONOMY_CONFIG_OUT_OF_RANGE"
REASON_NOT_WHOLE_CREDITS = "ECONOMY_CONFIG_NOT_WHOLE_CREDITS"
REASON_MISSING_INPUT = "ECONOMY_CONFIG_MISSING_INPUT"
REASON_BOUNDARY_UNAVAILABLE = "ECONOMY_CONFIG_BOUNDARY_UNAVAILABLE"
REASON_BOUNDARY_INVALID = "ECONOMY_CONFIG_BOUNDARY_INVALID"
REASON_NO_ACTIVE_TEAMS = "ECONOMY_CONFIG_NO_ACTIVE_TEAMS"
REASON_ALREADY_FROZEN = "ECONOMY_CONFIG_FROZEN"
REASON_FROZEN_CONFLICT = "ECONOMY_CONFIG_FROZEN_CONFLICT"


class EconomyConfigError(ValueError):
    """A league-season economy configuration was refused.

    A ValueError subclass so existing `except ValueError` handlers around
    activation still catch it, carrying `reason` for surfaces that render
    reason codes."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


# ── Validation ───────────────────────────────────────────────────────────────

def _validate_one(value, *, field: str, minimum: int, maximum: int) -> int:
    """One commissioner input: present, integral, in range, whole Credits.

    WHOLE CREDITS IS A PRODUCT RULE, NOT A ROUNDING CONVENIENCE. The UI shows
    these as `$10` and `$80`; admitting 1050 cents would render as a value the
    commissioner cannot type back in, and every derived figure — the reserve,
    the allocation, the league total — would inherit the fraction. Rejecting it
    at the input is the only place the rule costs nothing.
    """
    if value is None:
        raise EconomyConfigError(
            REASON_MISSING_INPUT,
            f"{field} is required; an economy configuration cannot be frozen "
            f"with an unstated input.")
    if isinstance(value, bool) or not isinstance(value, int):
        raise EconomyConfigError(
            REASON_OUT_OF_RANGE,
            f"{field} must be an integer number of cents; got {value!r}.")
    if not (minimum <= value <= maximum):
        raise EconomyConfigError(
            REASON_OUT_OF_RANGE,
            f"{field} is {value} cents (${value / CENTS_PER_CREDIT:g}); the "
            f"governed range is {minimum}-{maximum} cents "
            f"(${minimum // CENTS_PER_CREDIT}-${maximum // CENTS_PER_CREDIT}).")
    if value % CENTS_PER_CREDIT != 0:
        raise EconomyConfigError(
            REASON_NOT_WHOLE_CREDITS,
            f"{field} is {value} cents, which is not a whole number of "
            f"Credits. Amounts are configured in whole Credits.")
    return int(value)


def validate_inputs(*, weekly_bet_minimum_cents, championship_contribution_cents,
                    skunk_fee_cents) -> tuple[int, int, int]:
    """The three commissioner inputs, validated together. Pure."""
    return (
        _validate_one(weekly_bet_minimum_cents,
                      field="weekly_bet_minimum_cents",
                      minimum=MIN_WEEKLY_BET_MINIMUM_CENTS,
                      maximum=MAX_WEEKLY_BET_MINIMUM_CENTS),
        _validate_one(championship_contribution_cents,
                      field="championship_contribution_cents",
                      minimum=MIN_CHAMPIONSHIP_CONTRIBUTION_CENTS,
                      maximum=MAX_CHAMPIONSHIP_CONTRIBUTION_CENTS),
        _validate_one(skunk_fee_cents, field="skunk_fee_cents",
                      minimum=MIN_SKUNK_FEE_CENTS,
                      maximum=MAX_SKUNK_FEE_CENTS),
    )


# ── Derivation ───────────────────────────────────────────────────────────────

def derive_regular_season_week_count(*, start_week, playoff_start_week) -> int:
    """`playoff_start_week - start_week`, or a named refusal.

    NEITHER BOUNDARY IS ASSUMED. `start_week` is not defaulted to 1, the count
    is not inferred from team count, and it is not counted from league matchup
    rows — a matchup total measures games played across the league, not the
    number of weeks in which each GM owes a Weekly Bet Minimum. A league whose
    provider stated neither boundary simply cannot freeze an economy.
    """
    if start_week is None or playoff_start_week is None:
        missing = [n for n, v in (("start_week", start_week),
                                  ("playoff_start_week", playoff_start_week))
                   if v is None]
        raise EconomyConfigError(
            REASON_BOUNDARY_UNAVAILABLE,
            f"the connected league has not stated {' and '.join(missing)}, so "
            f"the regular-season week count cannot be derived. Refusing to "
            f"assume one — the count decides how many Credits each GM is "
            f"issued.")
    start, playoff = int(start_week), int(playoff_start_week)
    if playoff <= start:
        raise EconomyConfigError(
            REASON_BOUNDARY_INVALID,
            f"playoff_start_week ({playoff}) is not after start_week "
            f"({start}); that describes a season with no regular-season weeks.")
    return playoff - start


@dataclass(frozen=True)
class EconomyCalculation:
    """What a configuration means, in Credits. Pure arithmetic, no ledger."""

    weekly_bet_minimum_cents: int
    championship_contribution_cents: int
    skunk_fee_cents: int
    regular_season_week_count: int
    active_team_count: int

    @property
    def weekly_minimum_reserve_per_player_cents(self) -> int:
        return self.weekly_bet_minimum_cents * self.regular_season_week_count

    @property
    def championship_reserve_per_player_cents(self) -> int:
        return self.championship_contribution_cents

    @property
    def season_opening_allocation_per_player_cents(self) -> int:
        """THE CANONICAL PER-PLAYER TOTAL (ECON-CONFIG-R6).

        Called the Season-Opening Allocation, never the League Buy-In:
        FantasyStakes processes no payment, and the product term must not imply
        one. Independent of league size by construction — team count appears
        only in the league totals below."""
        return (self.weekly_minimum_reserve_per_player_cents
                + self.championship_reserve_per_player_cents)

    @property
    def league_weekly_minimum_reserve_cents(self) -> int:
        return (self.weekly_minimum_reserve_per_player_cents
                * self.active_team_count)

    @property
    def league_championship_reserve_cents(self) -> int:
        return (self.championship_reserve_per_player_cents
                * self.active_team_count)

    @property
    def league_opening_allocation_cents(self) -> int:
        return (self.season_opening_allocation_per_player_cents
                * self.active_team_count)


# ── Draft (mutable, pre-activation) ──────────────────────────────────────────

@dataclass(frozen=True)
class EconomyDraft:
    """One league-season's configuration as a reader sees it.

    `configured` is False when no row exists at all — such a league keeps the
    existing fixed economy-stop behaviour and freezes nothing. `frozen` marks a
    row the activation has already stamped, which no further write may touch.
    """

    league_id: int
    season: int
    weekly_bet_minimum_cents: int
    championship_contribution_cents: int
    skunk_fee_cents: int
    configured: bool
    frozen: bool


def read_frozen(db, *, league_id: int, season: int,
                include_draft: bool = False):
    """One league-season's configuration row, or None.

    By default this returns only a FROZEN row, so a caller asking "is this
    season's economy settled?" cannot be answered with a draft. `include_draft`
    opts into the row whatever its state, which only the editing path needs.
    """
    from db.schema import LeagueSeasonEconomyConfig

    row = (db.query(LeagueSeasonEconomyConfig)
           .filter(LeagueSeasonEconomyConfig.league_id == league_id,
                   LeagueSeasonEconomyConfig.season == season)
           .first())
    if row is None:
        return None
    if include_draft or row.frozen_at is not None:
        return row
    return None


def read_draft(db, *, league_id: int, season: int | None = None
               ) -> EconomyDraft:
    """The league-season's configuration, falling back to the setup defaults.

    `configured` is False when no row exists — the state every pre-ECONCFG-F1
    season is in, and the state a league that never configures one stays in.
    The defaults returned alongside it are a SUGGESTION for the setup screen,
    never a configuration: an unconfigured league freezes nothing.
    """
    from db.schema import League

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise EconomyConfigError(REASON_MISSING_INPUT,
                                 f"league {league_id} not found")
    effective = season if season is not None else league.season
    row = read_frozen(db, league_id=league_id, season=effective,
                      include_draft=True)
    if row is None:
        return EconomyDraft(
            league_id=league_id, season=effective,
            weekly_bet_minimum_cents=DEFAULT_WEEKLY_BET_MINIMUM_CENTS,
            championship_contribution_cents=(
                DEFAULT_CHAMPIONSHIP_CONTRIBUTION_CENTS),
            skunk_fee_cents=DEFAULT_SKUNK_FEE_CENTS,
            configured=False, frozen=False)
    return EconomyDraft(
        league_id=league_id, season=effective,
        weekly_bet_minimum_cents=row.weekly_bet_minimum_cents,
        championship_contribution_cents=row.championship_contribution_cents,
        skunk_fee_cents=row.skunk_fee_cents,
        configured=True, frozen=row.frozen_at is not None)


def set_draft(db, *, league_id: int, weekly_bet_minimum_cents,
              championship_contribution_cents, skunk_fee_cents,
              season: int | None = None) -> EconomyDraft:
    """Validate and store the commissioner's configuration. Does NOT commit.

    REFUSES ONCE FROZEN (ECON-CONFIG-R4). After activation the configuration
    governs Credits that have already been issued, and rewriting it would leave
    the record disagreeing with the season it is supposed to explain. There is
    no reset protocol in FantasyStakes 1.0, so the refusal is the whole
    mechanism.
    """
    from db.schema import League, LeagueSeasonEconomyConfig

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise EconomyConfigError(REASON_MISSING_INPUT,
                                 f"league {league_id} not found")
    effective = season if season is not None else league.season

    row = read_frozen(db, league_id=league_id, season=effective,
                      include_draft=True)
    if row is not None and row.frozen_at is not None:
        raise EconomyConfigError(
            REASON_ALREADY_FROZEN,
            f"league {league_id} season {effective} froze its economy "
            f"configuration at {row.frozen_at}; it governs Credits already "
            f"issued and cannot be edited.")

    weekly, championship, skunk = validate_inputs(
        weekly_bet_minimum_cents=weekly_bet_minimum_cents,
        championship_contribution_cents=championship_contribution_cents,
        skunk_fee_cents=skunk_fee_cents)

    if row is None:
        row = LeagueSeasonEconomyConfig(league_id=league_id, season=effective)
        db.add(row)
    row.weekly_bet_minimum_cents = weekly
    row.championship_contribution_cents = championship
    row.skunk_fee_cents = skunk
    db.flush()
    return read_draft(db, league_id=league_id, season=effective)


# ── Frozen (immutable, at activation) ────────────────────────────────────────

def active_team_count(db, *, league_id: int) -> int:
    """Teams actually participating in this league-season.

    Counted, never assumed. Eight, ten, twelve and odd counts are all ordinary;
    nothing here requires an even field, and this number does not enter the
    per-player formula — only the league totals.
    """
    from db.schema import Team

    return db.query(Team).filter(Team.league_id == league_id).count()


def freeze_economy_config(db, *, league_id: int, season: int,
                          now: datetime | None = None):
    """Stamp the draft immutable. Does NOT commit.

    Returns the frozen row, or None when the league-season is UNCONFIGURED —
    which is not an error and is the state every pre-ECONCFG-F1 season is in.

    IDEMPOTENT, AND A CONTRADICTION IS A CONFLICT RATHER THAN AN UPDATE. A
    second freeze over an already-stamped row returns it when the derived
    facts still agree, and raises when they do not: the stamped row is
    authoritative for the season, and treating a disagreement as a replay would
    report success while a stale configuration silently governed the economy.
    That is the same rule `activate_season_allocation` already applies to the
    frozen top-off multiplier.

    NOTHING HERE POSTS A CREDIT. The row records what the economy IS; the fixed
    economy-stop table still decides what is ISSUED until a later package moves
    that authority deliberately.
    """
    from db.schema import League

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise EconomyConfigError(REASON_MISSING_INPUT,
                                 f"league {league_id} not found")

    row = read_frozen(db, league_id=league_id, season=season,
                      include_draft=True)
    if row is None:
        # UNCONFIGURED: nothing was ever configured, so there is nothing to
        # freeze and nothing to refuse. Existing behaviour stands.
        return None

    weekly, championship, skunk = validate_inputs(
        weekly_bet_minimum_cents=row.weekly_bet_minimum_cents,
        championship_contribution_cents=row.championship_contribution_cents,
        skunk_fee_cents=row.skunk_fee_cents)

    weeks = derive_regular_season_week_count(
        start_week=league.start_week,
        playoff_start_week=league.playoff_start_week)

    teams = active_team_count(db, league_id=league_id)
    if teams <= 0:
        raise EconomyConfigError(
            REASON_NO_ACTIVE_TEAMS,
            f"league {league_id} has no active teams; an economy configuration "
            f"describes a season nobody is playing.")

    if row.frozen_at is not None:
        proposed = (weekly, championship, skunk, weeks, teams)
        current = (row.weekly_bet_minimum_cents,
                   row.championship_contribution_cents,
                   row.skunk_fee_cents,
                   row.regular_season_week_count,
                   row.active_team_count)
        if proposed != current:
            raise EconomyConfigError(
                REASON_FROZEN_CONFLICT,
                f"league {league_id} season {season} is already frozen at "
                f"{current} and this freeze derives {proposed}. The frozen "
                f"configuration is authoritative for the season and is never "
                f"updated in place.")
        return row

    row.regular_season_week_count = weeks
    row.active_team_count = teams
    row.start_week_used = int(league.start_week)
    row.playoff_start_week_used = int(league.playoff_start_week)
    row.frozen_at = now
    db.flush()
    return row


def calculation_for(config) -> EconomyCalculation:
    """The Credit arithmetic for a frozen row or a draft-shaped object."""
    return EconomyCalculation(
        weekly_bet_minimum_cents=config.weekly_bet_minimum_cents,
        championship_contribution_cents=config.championship_contribution_cents,
        skunk_fee_cents=config.skunk_fee_cents,
        regular_season_week_count=config.regular_season_week_count,
        active_team_count=config.active_team_count,
    )
