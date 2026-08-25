"""FINAL POR §23 — League Settings, as one derived read.

WHAT THIS IS. The seven-row **VC ALLOCATION** table a GM opens from the gear
menu, its four in-season read-only figures, and the five Season Rules statements
that sit beneath them. Everything here is READ. This module posts nothing,
writes nothing, and holds no state.

WHY IT IS A MODULE AND NOT A TEMPLATE. §16.2 forbids reimplementing the economic
formula in the browser, and the RATIO column is exactly that temptation: an
amount divided by the Weekly Minimum is one line of JavaScript, and it would be
a second definition of a relationship the server already owns. The ratio is
derived here, beside the amounts it relates, and the browser is handed a string.

THE SEVEN ROWS ARE THE POR'S, IN THE POR'S ORDER, AND THAT ORDER IS DATA. A
server that returned its keys in a different order must not reorder the page, so
`ALLOCATION_ROW_IDS` is the sequence and the builders below are looked up
through it. A row added without a place in that tuple does not silently appear
at the end; it fails to appear at all, which is visible.

**NULL AND ZERO ARE DIFFERENT, AND THIS IS WHERE THAT MATTERS.**
`ff_championship_pot_cents` is nullable precisely so that "no commissioner has
entered an amount" and "this league deliberately plays with no Fantasy Football
pot" can be told apart — the schema says so in as many words. Both leave the
pillar unfunded and both would render as `$0` if this module flattened them, and
the audit question *did the league decline the pot, or never see it?* would stop
having an answer. So a row carries `state`, and UNCONFIGURED is not CONFIGURED
with an amount of zero.

THE IN-SEASON FIGURES ARE LEDGER TRUTH, NOT COUNTERS. Each is summed from the
FantasyStakes Championship Pot's own credit legs, split by the door the money
came through — the sweep door, the top-off door, the two terminal Pool doors.
Nothing increments; there is no tally to drift from the ledger, because the
ledger IS the tally. It also means a correction or a void that reverses one of
those postings is reflected without this module knowing such things exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from economy.economy_events import (
    DOOR_WEEKLY_MINIMUM_SWEEP, fantasystakes_championship_account,
)
from ruleset import is_final_por


class LeagueSettingsError(Exception):
    """A settings view could not be derived. Carries a named reason."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


REASON_LEGACY_SEASON = "SETTINGS_LEGACY_SEASON"
REASON_NO_TERMS = "SETTINGS_NO_ALLOCATION_TERMS"


# -- Row states ----------------------------------------------------------------

#: A commissioner entered this amount.
STATE_CONFIGURED = "CONFIGURED"
#: A commissioner deliberately entered zero. The league plays without this.
STATE_DECLINED = "DECLINED"
#: No amount has been entered. NOT the same as zero -- see the module docstring.
STATE_UNCONFIGURED = "UNCONFIGURED"


#: The seven rows of §23's VC ALLOCATION table, in the POR's order.
ALLOCATION_ROW_IDS: tuple[str, ...] = (
    "weekly-minimum",
    "prop-pool-entry",
    "weekly-skunk-fee",
    "projected-points-pot",
    "fantasystakes-base-pot",
    "ff-championship-pot",
    "season-top-off-limit",
)

#: The four in-season read-only figures, in the POR's order.
IN_SEASON_ROW_IDS: tuple[str, ...] = (
    "unspent-minimum-sweeps",
    "topoffs-added-to-fs-pot",
    "terminal-pool-remainders",
    "current-fs-pot",
)

#: §23's five Season Rules, stated exactly. These are PRODUCT RULES and none is
#: commissioner-editable, which is why they are constants and not a read.
SEASON_RULES: tuple[tuple[str, str], ...] = (
    ("Weekly Minimum", "Regular season only"),
    ("Skunk Fees", "Regular season only"),
    ("Postseason play", "Wallet only"),
    ("Championship split", "60 / 30 / 10"),
    ("Wagers", "Public"),
)


@dataclass(frozen=True)
class AllocationRow:
    """One row of the VC ALLOCATION table."""

    id: str
    label: str
    #: None only when the amount is UNCONFIGURED. Zero is a real amount.
    amount_cents: int | None
    #: `CONFIGURED` / `DECLINED` / `UNCONFIGURED`.
    state: str
    #: The RATIO TO WEEKLY MINIMUM column, already rendered. None when there is
    #: no amount to relate.
    ratio: str | None
    #: Where the figure came from, shown so a reader can trace it.
    source: str


@dataclass(frozen=True)
class InSeasonRow:
    """One in-season read-only figure. Always an amount; zero is meaningful."""

    id: str
    label: str
    amount_cents: int
    source: str


@dataclass(frozen=True)
class LeagueSettingsView:
    league_id: int
    season: int
    weekly_minimum_cents: int
    allocation: tuple[AllocationRow, ...]
    in_season: tuple[InSeasonRow, ...]
    season_rules: tuple[tuple[str, str], ...] = SEASON_RULES


# -- The ratio column ----------------------------------------------------------

#: The multiplication sign and the "approximately" sign, named so the rendering
#: below reads as arithmetic rather than as escape sequences.
TIMES = "×"
APPROX = "≈"


def format_ratio(amount_cents: int, weekly_minimum_cents: int) -> str:
    """`amount / weekly minimum`, as the RATIO TO WEEKLY MINIMUM column shows it.

    EXACT, THEN ROUNDED ONCE FOR DISPLAY -- never floating-point arithmetic on
    money. `Fraction` divides the two integers exactly; only the final rendering
    approximates, and it says so by rendering the approximation sign when it
    had to.

    A whole multiple prints without a decimal point, because "14x" is what a
    reader means by fourteen times and "14.00x" reads like a measurement.
    """
    if weekly_minimum_cents <= 0:
        # Unreachable through the governed range (100..10000), and stated
        # rather than assumed: a zero denominator here would be a corrupt
        # configuration, not a row to render as infinity.
        raise LeagueSettingsError(
            REASON_NO_TERMS,
            f"weekly minimum is {weekly_minimum_cents} cents; no ratio to it "
            f"can be stated.")

    exact = Fraction(int(amount_cents), int(weekly_minimum_cents))
    if exact.denominator == 1:
        return f"{exact.numerator}{TIMES}"

    # Two decimals is the most this column can carry at 320px. The approximation
    # sign marks the rows where that is a rounding and not the value.
    rounded = Fraction(round(exact * 100), 100)
    text = f"{float(rounded):.2f}".rstrip("0").rstrip(".")
    mark = "" if rounded == exact else APPROX
    return f"{mark}{text}{TIMES}"


# -- The seven rows ------------------------------------------------------------

def _pool_entry_cents(db, *, league_id: int, season: int) -> int:  # noqa: ARG001
    from betting.pool_funding import resolve_weekly_entry_cents

    # NO SEASON. The Pool contribution is one league-level column, not a
    # season-scoped one, so passing a season here would be inventing a
    # granularity the setting does not have.
    return int(resolve_weekly_entry_cents(db, league_id=league_id))


def _top_off_limit_cents(db, *, league_id: int, season: int,
                         min_reserve_cents: int) -> int | None:
    """The per-GM season Top-Off limit, from the FROZEN multiplier when there is
    one and the league's editable dial before activation.

    THE PRE-ACTIVATION FIGURE IS A PROJECTION AND THE FROZEN ONE IS THE RULE.
    A commissioner reading this before activation is reading what they have
    dialled in, which may still change; reading it afterwards is reading what
    their season is actually bound to. Both are the same number when nobody has
    moved the dial, which is the ordinary case.
    """
    from db.schema import League, LeagueSeasonTopoffConfig
    from economy.top_off import compute_cap_cents

    frozen = (db.query(LeagueSeasonTopoffConfig)
              .filter(LeagueSeasonTopoffConfig.league_id == league_id,
                      LeagueSeasonTopoffConfig.season == season)
              .one_or_none())
    if frozen is not None:
        return compute_cap_cents(min_reserve_cents,
                                 int(frozen.topoff_cap_multiplier_bps))

    league = db.query(League).filter(League.id == league_id).one_or_none()
    if league is None or league.topoff_cap_multiplier_bps is None:
        return None
    return compute_cap_cents(min_reserve_cents,
                             int(league.topoff_cap_multiplier_bps))


def _row(row_id: str, label: str, amount_cents: int | None, *,
         weekly_minimum_cents: int, source: str,
         zero_is_a_choice: bool = True) -> AllocationRow:
    """Assemble one row, deciding its state from the amount alone.

    `zero_is_a_choice` is False for the rows where zero cannot be a deliberate
    setting -- a Weekly Minimum of zero is not a league playing without one, it
    is a configuration that could not be read.
    """
    if amount_cents is None:
        state = STATE_UNCONFIGURED
    elif amount_cents == 0 and zero_is_a_choice:
        state = STATE_DECLINED
    else:
        state = STATE_CONFIGURED

    return AllocationRow(
        id=row_id, label=label, amount_cents=amount_cents, state=state,
        ratio=(None if amount_cents is None
               else format_ratio(amount_cents, weekly_minimum_cents)),
        source=source)


def allocation_rows(db, *, league_id: int, season: int) -> tuple[AllocationRow, ...]:
    """§23's seven rows, derived. Reads only."""
    from economy.points_championship import projected_pot_cents
    from economy.skunk import resolve_skunk_fee_cents
    from payments.economy_config import resolve_allocation_terms

    # ONE RESOLUTION FOR EVERY FIGURE THAT HAS ONE. `resolve_allocation_terms`
    # is what priced the season, and it already carries the Weekly Minimum and
    # the Fantasy Football amount; reading them from anywhere else would be a
    # second source that could disagree with the money actually issued.
    terms = resolve_allocation_terms(db, league_id=league_id, season=season)

    # A LEGACY STOP CARRIES NO WEEKLY MINIMUM -- its amounts are constants, not
    # a formula, so `weekly_bet_minimum_cents` is None by design. Every ratio in
    # this table is taken against that figure, so without it there is no table
    # to render and saying so is the only honest answer. This is reachable: a
    # Final POR season whose economy was never frozen resolves the legacy stop.
    weekly = terms.weekly_bet_minimum_cents
    if not weekly:
        raise LeagueSettingsError(
            REASON_NO_TERMS,
            f"league {league_id} season {season} resolved no Weekly Minimum "
            f"(terms source {terms.source!r}); §23's ratio column is taken "
            f"against it, so the VC allocation table cannot be stated.")
    weekly = int(weekly)

    min_reserve = terms.min_reserve_cents
    top_off = (None if min_reserve is None
               else _top_off_limit_cents(db, league_id=league_id, season=season,
                                         min_reserve_cents=int(min_reserve)))

    built = {
        "weekly-minimum": _row(
            "weekly-minimum", "Weekly Minimum", weekly,
            weekly_minimum_cents=weekly, zero_is_a_choice=False,
            source="League economy configuration"),
        "prop-pool-entry": _row(
            "prop-pool-entry", "Prop Pool Entry",
            _pool_entry_cents(db, league_id=league_id, season=season),
            weekly_minimum_cents=weekly, zero_is_a_choice=False,
            source="League Pool settings"),
        # ZERO IS A GOVERNED CHOICE HERE (§9D, WP-2). A league may play with no
        # Skunk, and DECLINED says that rather than reading as a missing figure.
        "weekly-skunk-fee": _row(
            "weekly-skunk-fee", "Weekly Skunk Fee",
            int(resolve_skunk_fee_cents(db, league_id=league_id, season=season)),
            weekly_minimum_cents=weekly, source="Skunk rules"),
        # A PROJECTION, AND LABELLED ONE. §12 makes this display-only: it is the
        # fee times the regular-season week count, it is never posted, and no
        # ledger entry is ever derived from it.
        "projected-points-pot": _row(
            "projected-points-pot", "Projected Points Championship Pot",
            int(projected_pot_cents(db, league_id=league_id, season=season)),
            weekly_minimum_cents=weekly,
            source="Projected -- Skunk Fee across the regular season"),
        "fantasystakes-base-pot": _row(
            "fantasystakes-base-pot", "FantasyStakes Championship Base Pot",
            (None if min_reserve is None else int(min_reserve)),
            weekly_minimum_cents=weekly, zero_is_a_choice=False,
            source="Weekly Minimum across the regular season"),
        "ff-championship-pot": _row(
            "ff-championship-pot", "Fantasy Football Championship Pot",
            terms.ff_championship_pot_cents,
            weekly_minimum_cents=weekly,
            source="League economy configuration"),
        "season-top-off-limit": _row(
            "season-top-off-limit", "Season Top-Off Limit", top_off,
            weekly_minimum_cents=weekly,
            source="Frozen top-off multiplier"),
    }
    return tuple(built[row_id] for row_id in ALLOCATION_ROW_IDS)


# -- The four in-season figures ------------------------------------------------

def _credited_through(db, *, account: str, doors: tuple[str, ...]) -> int:
    """Positive legs on `account` that arrived through one of `doors`.

    ONE TABLE, ONE WRITE PATH. This reads `ledger_entries` alone and joins
    nothing, so the `posting_id` format divergence between raw-SQL and ORM
    writers -- dashed against dashless, which returns no rows on SQLite --
    cannot reach it. That defect is worked around in exactly one place already
    and this is deliberately not a second.
    """
    from sqlalchemy import text

    if not doors:
        return 0
    db.flush()
    placeholders = ", ".join(f":d{i}" for i in range(len(doors)))
    params: dict[str, object] = {"a": account}
    params.update({f"d{i}": door for i, door in enumerate(doors)})
    total = db.execute(text(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
        f"WHERE account = :a AND amount_cents > 0 AND door IN ({placeholders})"),
        params).scalar()
    return int(total or 0)


def in_season_rows(db, *, league_id: int, season: int) -> tuple[InSeasonRow, ...]:
    """§23's four in-season read-only figures, summed from the ledger."""
    from betting.pool_settlement import DOOR_CHAMPIONSHIP_SWEEP, DOOR_ROLLOVER_EXPIRY
    from economy.championship_pots import pot_balances
    from economy.top_off import APPROVED_BAB_TOPOFF_DOOR

    account = fantasystakes_championship_account(league_id, season)

    built = {
        "unspent-minimum-sweeps": InSeasonRow(
            "unspent-minimum-sweeps", "Unspent Minimum Sweeps",
            _credited_through(db, account=account,
                              doors=(DOOR_WEEKLY_MINIMUM_SWEEP,)),
            "Swept at week close"),
        "topoffs-added-to-fs-pot": InSeasonRow(
            "topoffs-added-to-fs-pot", "Top-Offs Added to FS Pot",
            _credited_through(db, account=account,
                              doors=(APPROVED_BAB_TOPOFF_DOOR,)),
            "Added when a Top-Off is approved"),
        # TWO DOORS, ONE FIGURE. A Pool reaches its terminus either because its
        # definition can never carry, or because a rollover-eligible Pool ran
        # out of season. Both are terminal remainders to a reader, and §23 asks
        # for the remainders rather than for the two causes.
        "terminal-pool-remainders": InSeasonRow(
            "terminal-pool-remainders", "Terminal Prop Pool Remainders",
            _credited_through(db, account=account,
                              doors=(DOOR_CHAMPIONSHIP_SWEEP, DOOR_ROLLOVER_EXPIRY)),
            "Swept when a Pool cannot carry"),
        "current-fs-pot": InSeasonRow(
            "current-fs-pot", "Current FS Championship Pot",
            int(pot_balances(db, league_id=league_id,
                             season=season).fantasystakes_cents),
            "Ledger balance"),
    }
    return tuple(built[row_id] for row_id in IN_SEASON_ROW_IDS)


# -- The view ------------------------------------------------------------------

def view(db, *, league_id: int, season: int) -> LeagueSettingsView:
    """§23's League Settings for one league-season. FINAL POR only.

    A LEGACY SEASON IS REFUSED BY NAME rather than rendered approximately. Four
    of the seven rows describe pots the retired architecture does not have, and
    a table that quietly dropped them would tell a reader their league has a
    settings screen with four blank rows instead of telling them the season
    predates the model the screen describes.
    """
    if not is_final_por(db, league_id=league_id, season=season):
        raise LeagueSettingsError(
            REASON_LEGACY_SEASON,
            f"league {league_id} season {season} is a LEGACY season. §23's VC "
            f"allocation table describes the Final POR economy and does not "
            f"describe this season's.")

    rows = allocation_rows(db, league_id=league_id, season=season)
    weekly = next(r for r in rows if r.id == "weekly-minimum")
    return LeagueSettingsView(
        league_id=league_id, season=season,
        weekly_minimum_cents=int(weekly.amount_cents or 0),
        allocation=rows,
        in_season=in_season_rows(db, league_id=league_id, season=season))
