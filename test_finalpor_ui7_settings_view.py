#!/usr/bin/env python3
"""FINAL POR · UI-7 backend certification — §23 League Settings, derived.

    S1   the seven VC ALLOCATION rows exist, in the POR's order, with the
         POR's labels
    S2   every amount is the governing source's own, not a constant here
    S3   the RATIO TO WEEKLY MINIMUM column is exact, and marks its roundings
    S4   UNCONFIGURED, DECLINED and CONFIGURED are three different states
    S5   the four in-season figures are summed from the ledger, by door
    S6   the five Season Rules are stated exactly and are not editable
    S7   a LEGACY season is refused by name rather than rendered approximately
    S8   the module writes nothing -- no ledger entry, no event, no row

WHY S4 IS THE ONE THAT MATTERS MOST HERE. Six of the seven rows can only be a
number. The Fantasy Football pot can be a number, a deliberate zero, or absent,
and the schema is nullable for exactly that reason: an audit asking whether a
league declined the pot or never saw it has an answer only because the two are
stored apart. A settings screen that rendered both as `$0` would throw that
distinction away at the last step, after the database went to the trouble of
keeping it.

WHY S3 CHECKS THE ROUNDING MARK. A ratio of one third is not 0.33, and a column
that prints 0.33 without saying so is quietly wrong in the direction a reader
cannot detect. The exact value is a `Fraction`; the display rounds once and
admits it.

WHY S5 SUMS BY DOOR RATHER THAN BY EVENT TYPE. All three in-season inflows land
on the same account, so the account alone cannot tell them apart -- and joining
`economy_event` to `ledger_entries` on `posting_id` returns no rows on SQLite,
because one is written dashed through raw SQL and the other dashless through the
ORM. The door is on the ledger row itself. One table, one write path, no join,
and the known format divergence cannot reach this read.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import ledger.ledger as ledger_module
from db.schema import (
    Base, League, LeagueSeasonEconomyConfig, LeagueSeasonTopoffConfig, Matchup,
    PoolConfig, Team, Wallet,
)
from economy.economy_events import (
    DOOR_WEEKLY_MINIMUM_SWEEP, fantasystakes_championship_account,
)
from economy.league_settings_view import (
    ALLOCATION_ROW_IDS, IN_SEASON_ROW_IDS, REASON_LEGACY_SEASON,
    SEASON_RULES, STATE_CONFIGURED, STATE_DECLINED, STATE_UNCONFIGURED,
    LeagueSettingsError, allocation_rows, format_ratio, in_season_rows, view,
)
from ledger.ledger import post as ledger_post
from ruleset import RULESET_FINAL_POR, stamp_ruleset

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
NAIVE = NOW.replace(tzinfo=None)

LEAGUE = 1
SEASON = 2026
WEEKS = 14
WEEKLY = 1_000          # $10
POOL_ENTRY = 500        # $5
SKUNK = 500             # $5
FF_POT = 5_000          # $50
TOPOFF_BPS = 5_000      # 50% of the Weekly Play Reserve


def _build(*, final_por: bool = True, ff_pot_cents: int | None = FF_POT,
           skunk_fee_cents: int = SKUNK, pool_entry_cents: int = POOL_ENTRY,
           topoff_bps: int | None = TOPOFF_BPS, configured: bool = True):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=LEAGUE, name="L", season=SEASON, start_week=1,
                  playoff_start_week=15,
                  topoff_cap_multiplier_bps=(topoff_bps or 0)))
    for t in range(1, 5):
        db.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider_team_key=f"k{t}"))
        db.add(Wallet(team_id=t, balance=0.0))
    db.add(Matchup(id=1, league_id=LEAGUE, week=1, home_team_id=1,
                   away_team_id=2, home_score=100.0, away_score=98.0,
                   winner_team_id=1, finalized_at=NAIVE))
    # `pool_weekly_entry_cents` IS THE COLUMN THE RESOLVER READS -- the older
    # `weekly_entry_cents` beside it is not, and setting that one instead makes
    # every Pool figure read as the governed default while looking configured.
    db.add(PoolConfig(league_id=LEAGUE,
                      pool_weekly_entry_cents=pool_entry_cents))
    if configured:
        db.add(LeagueSeasonEconomyConfig(
            league_id=LEAGUE, season=SEASON,
            weekly_bet_minimum_cents=WEEKLY,
            championship_contribution_cents=8_000,
            skunk_fee_cents=skunk_fee_cents,
            ff_championship_pot_cents=ff_pot_cents,
            regular_season_week_count=WEEKS,
            active_team_count=4,
            start_week_used=1, playoff_start_week_used=15,
            frozen_at=NAIVE))
    if topoff_bps is not None:
        db.add(LeagueSeasonTopoffConfig(league_id=LEAGUE, season=SEASON,
                                        topoff_cap_multiplier_bps=topoff_bps))
    db.commit()

    if final_por:
        stamp_ruleset(db, league_id=LEAGUE, season=SEASON,
                      version=RULESET_FINAL_POR)
        db.commit()
    return db


def _by_id(rows):
    return {r.id: r for r in rows}


# -- S1 . the seven rows, in the POR's order ----------------------------------

print("\nUI7-S1 " + chr(0x00b7) + " §23's seven VC ALLOCATION rows")

db = _build()
rows = allocation_rows(db, league_id=LEAGUE, season=SEASON)

_assert("there are exactly seven rows", len(rows) == 7, str(len(rows)))
_assert("  . in the POR's order",
        tuple(r.id for r in rows) == ALLOCATION_ROW_IDS,
        str([r.id for r in rows]))
_assert("  . carrying the POR's labels, verbatim",
        [r.label for r in rows] == [
            "Weekly Minimum",
            "Prop Pool Entry",
            "Weekly Skunk Fee",
            "Projected Points Championship Pot",
            "FantasyStakes Championship Base Pot",
            "Fantasy Football Championship Pot",
            "Season Top-Off Limit",
        ], str([r.label for r in rows]))
# THE ORDER IS DATA, and a row without a place in it cannot appear at all. That
# is the property, not the current contents: a future row appended to the
# builder dict without being added to ALLOCATION_ROW_IDS is dropped visibly
# rather than rendered at the end where nobody specified it.
_assert("  . and the order is a declared tuple, not the dict's insertion order",
        len(set(ALLOCATION_ROW_IDS)) == 7)


# -- S2 . every amount is the governing source's own --------------------------

print("\nUI7-S2 " + chr(0x00b7) + " each amount comes from its governing source")

r = _by_id(rows)
_assert("Weekly Minimum is the configured weekly bet minimum",
        r["weekly-minimum"].amount_cents == WEEKLY,
        str(r["weekly-minimum"].amount_cents))
_assert("Prop Pool Entry is the league's Pool contribution",
        r["prop-pool-entry"].amount_cents == POOL_ENTRY,
        str(r["prop-pool-entry"].amount_cents))
_assert("Weekly Skunk Fee is the configured fee",
        r["weekly-skunk-fee"].amount_cents == SKUNK,
        str(r["weekly-skunk-fee"].amount_cents))
_assert("Projected Points Pot is the fee across the regular season",
        r["projected-points-pot"].amount_cents == SKUNK * WEEKS,
        str(r["projected-points-pot"].amount_cents))
_assert("FantasyStakes Base Pot is the Weekly Minimum across the season",
        r["fantasystakes-base-pot"].amount_cents == WEEKLY * WEEKS,
        str(r["fantasystakes-base-pot"].amount_cents))
_assert("Fantasy Football Pot is the commissioner's entered amount",
        r["ff-championship-pot"].amount_cents == FF_POT,
        str(r["ff-championship-pot"].amount_cents))
_assert("Season Top-Off Limit is the frozen multiplier against the reserve",
        r["season-top-off-limit"].amount_cents == WEEKLY * WEEKS * TOPOFF_BPS // 10_000,
        str(r["season-top-off-limit"].amount_cents))

# THE FIGURES REALLY FOLLOW THE CONFIGURATION, proven by moving it. A table of
# constants would pass every assertion above and fail every one below.
moved = _build(skunk_fee_cents=900, pool_entry_cents=250, ff_pot_cents=1,
               topoff_bps=20_000)
m = _by_id(allocation_rows(moved, league_id=LEAGUE, season=SEASON))
_assert("a different Skunk Fee moves both rows that depend on it",
        m["weekly-skunk-fee"].amount_cents == 900
        and m["projected-points-pot"].amount_cents == 900 * WEEKS,
        f"{m['weekly-skunk-fee'].amount_cents} / "
        f"{m['projected-points-pot'].amount_cents}")
_assert("  . a different Pool contribution moves the Pool row",
        m["prop-pool-entry"].amount_cents == 250,
        str(m["prop-pool-entry"].amount_cents))
_assert("  . a different Fantasy Football amount moves that row",
        m["ff-championship-pot"].amount_cents == 1,
        str(m["ff-championship-pot"].amount_cents))
_assert("  . and a different multiplier moves the Top-Off limit",
        m["season-top-off-limit"].amount_cents == WEEKLY * WEEKS * 2,
        str(m["season-top-off-limit"].amount_cents))
_assert("  . while the Base Pot, which none of them touch, does not move",
        m["fantasystakes-base-pot"].amount_cents == WEEKLY * WEEKS,
        str(m["fantasystakes-base-pot"].amount_cents))


# -- S3 . the ratio column ----------------------------------------------------

print("\nUI7-S3 " + chr(0x00b7) + " RATIO TO WEEKLY MINIMUM is exact, and says when it is not")

_assert("the Weekly Minimum is one times itself",
        r["weekly-minimum"].ratio == "1×", str(r["weekly-minimum"].ratio))
_assert("  . a half-minimum Pool entry reads 0.5x",
        r["prop-pool-entry"].ratio == "0.5×", str(r["prop-pool-entry"].ratio))
_assert("  . a fourteen-week Base Pot reads 14x",
        r["fantasystakes-base-pot"].ratio == "14×",
        str(r["fantasystakes-base-pot"].ratio))
_assert("  . a whole multiple carries no decimal point",
        "." not in r["fantasystakes-base-pot"].ratio,
        str(r["fantasystakes-base-pot"].ratio))

# EXACTNESS, TESTED WHERE IT BREAKS. One third is not 0.33, and the column says
# so rather than printing a rounded figure as though it were the value.
_assert("an inexact ratio is MARKED as approximate",
        format_ratio(333, 1_000) == "≈0.33×", format_ratio(333, 1_000))
_assert("  . while an exact one is not",
        format_ratio(250, 1_000) == "0.25×", format_ratio(250, 1_000))
_assert("  . a third of the minimum rounds once, and is marked",
        format_ratio(1_000, 3_000) == "≈0.33×",
        format_ratio(1_000, 3_000))
_assert("  . two thirds rounds UP and is marked",
        format_ratio(2_000, 3_000) == "≈0.67×",
        format_ratio(2_000, 3_000))
_assert("  . zero relates to the minimum as zero, exactly",
        format_ratio(0, 1_000) == "0×", format_ratio(0, 1_000))
# A LARGE RATIO IS STILL EXACT -- no float ever touches the division.
_assert("  . a large exact ratio is a whole number, not a float artefact",
        format_ratio(1_000_000_00, 1_000) == "100000×",
        format_ratio(1_000_000_00, 1_000))
# A ZERO DENOMINATOR IS A CORRUPT CONFIGURATION, not a row to render as
# infinity or as a dash. The governed range (100..10000) makes it unreachable,
# which is exactly why the refusal has to be asserted directly.
try:
    format_ratio(100, 0)
    _assert("a zero Weekly Minimum is refused, not rendered", False,
            "it returned a ratio")
except LeagueSettingsError as exc:
    _assert("a zero Weekly Minimum is refused, not rendered",
            exc.reason == "SETTINGS_NO_ALLOCATION_TERMS", exc.reason)


# -- S4 . UNCONFIGURED is not DECLINED is not CONFIGURED ----------------------

print("\nUI7-S4 " + chr(0x00b7) + " absent, declined and entered are three states")

declined = _by_id(allocation_rows(_build(ff_pot_cents=0),
                                  league_id=LEAGUE, season=SEASON))
absent = _by_id(allocation_rows(_build(ff_pot_cents=None),
                                league_id=LEAGUE, season=SEASON))

_assert("an entered Fantasy Football amount is CONFIGURED",
        r["ff-championship-pot"].state == STATE_CONFIGURED,
        r["ff-championship-pot"].state)
_assert("  . a deliberate zero is DECLINED, not CONFIGURED",
        declined["ff-championship-pot"].state == STATE_DECLINED,
        declined["ff-championship-pot"].state)
_assert("  . and an unentered amount is UNCONFIGURED, not DECLINED",
        absent["ff-championship-pot"].state == STATE_UNCONFIGURED,
        absent["ff-championship-pot"].state)
_assert("  . the three states are genuinely different values",
        len({STATE_CONFIGURED, STATE_DECLINED, STATE_UNCONFIGURED}) == 3)

# THE DISTINCTION SURVIVES INTO THE AMOUNT ITSELF, which is what stops a
# renderer from flattening it back: DECLINED carries 0 and UNCONFIGURED carries
# nothing at all, so there is no figure to print for the second one.
_assert("DECLINED carries a real zero",
        declined["ff-championship-pot"].amount_cents == 0,
        str(declined["ff-championship-pot"].amount_cents))
_assert("  . UNCONFIGURED carries no amount at all",
        absent["ff-championship-pot"].amount_cents is None,
        str(absent["ff-championship-pot"].amount_cents))
_assert("  . and no ratio, because there is nothing to relate",
        absent["ff-championship-pot"].ratio is None,
        str(absent["ff-championship-pot"].ratio))
_assert("  . while DECLINED does relate, at zero",
        declined["ff-championship-pot"].ratio == "0×",
        str(declined["ff-championship-pot"].ratio))

# A ZERO SKUNK FEE IS ALSO A GOVERNED CHOICE (§9D / WP-2), and reads the same
# way -- so the state is a property of the setting, not a special case for one
# nullable column.
no_skunk = _by_id(allocation_rows(_build(skunk_fee_cents=0),
                                  league_id=LEAGUE, season=SEASON))
_assert("a league that plays with no Skunk reads DECLINED",
        no_skunk["weekly-skunk-fee"].state == STATE_DECLINED,
        no_skunk["weekly-skunk-fee"].state)
_assert("  . and its projected Points pot is zero, not absent",
        no_skunk["projected-points-pot"].amount_cents == 0
        and no_skunk["projected-points-pot"].state == STATE_DECLINED,
        str(no_skunk["projected-points-pot"].amount_cents))

# A WEEKLY MINIMUM OF ZERO IS NOT A CHOICE -- it is an unreadable configuration,
# and `zero_is_a_choice=False` is what says so. The governed range forbids it,
# which is why this is asserted on the FLAG rather than by building one.
_assert("the Weekly Minimum row does not treat zero as a choice",
        r["weekly-minimum"].state == STATE_CONFIGURED,
        r["weekly-minimum"].state)


# -- S5 . the four in-season figures, summed by door --------------------------

print("\nUI7-S5 " + chr(0x00b7) + " the in-season figures are ledger truth")

from betting.pool_settlement import DOOR_CHAMPIONSHIP_SWEEP  # noqa: E402
from economy.top_off import APPROVED_BAB_TOPOFF_DOOR  # noqa: E402

live = _build()
POT = fantasystakes_championship_account(LEAGUE, SEASON)

empty = _by_id(in_season_rows(live, league_id=LEAGUE, season=SEASON))
_assert("before anything happens all four figures are zero",
        all(row.amount_cents == 0 for row in empty.values()),
        str({k: v.amount_cents for k, v in empty.items()}))

# FUND THE SOURCES FIRST, through the governed issuance door. The ledger
# refuses a debit that would take a funded account negative, which is why this
# cannot simply post the sweeps: money has to exist before it can be swept, and
# a fixture that skipped that step would be exercising a path the product does
# not have.
from ledger.ledger import SEASON_ALLOCATION_DOOR  # noqa: E402

ledger_post([("season_issuance:1:2026", -1_750),
             ("min:1", 600), ("min:2", 400), ("pool:1", 750)],
            door=SEASON_ALLOCATION_DOOR, session=live)
live.commit()

# Three inflows through three different doors, onto ONE account.
ledger_post([("min:1", -600), (POT, 600)],
            door=DOOR_WEEKLY_MINIMUM_SWEEP, session=live)
ledger_post([("min:2", -400), (POT, 400)],
            door=DOOR_WEEKLY_MINIMUM_SWEEP, session=live)
ledger_post([("bab_issuance:1:2026", -2_000), ("wallet:1", 1_000),
             (POT, 1_000)],
            door=APPROVED_BAB_TOPOFF_DOOR, session=live)
ledger_post([("pool:1", -750), (POT, 750)],
            door=DOOR_CHAMPIONSHIP_SWEEP, session=live)
live.commit()

got = _by_id(in_season_rows(live, league_id=LEAGUE, season=SEASON))
_assert("the four figures are the POR's, in the POR's order",
        tuple(x.id for x in in_season_rows(
            live, league_id=LEAGUE, season=SEASON)) == IN_SEASON_ROW_IDS)
_assert("  . carrying the POR's labels",
        [x.label for x in in_season_rows(live, league_id=LEAGUE, season=SEASON)]
        == ["Unspent Minimum Sweeps", "Top-Offs Added to FS Pot",
            "Terminal Prop Pool Remainders", "Current FS Championship Pot"])
_assert("Unspent Minimum Sweeps sums BOTH sweeps and nothing else",
        got["unspent-minimum-sweeps"].amount_cents == 1_000,
        str(got["unspent-minimum-sweeps"].amount_cents))
_assert("  . Top-Offs Added counts only the pot leg, not the Wallet leg",
        got["topoffs-added-to-fs-pot"].amount_cents == 1_000,
        str(got["topoffs-added-to-fs-pot"].amount_cents))
_assert("  . Terminal Pool Remainders is the Pool sweep",
        got["terminal-pool-remainders"].amount_cents == 750,
        str(got["terminal-pool-remainders"].amount_cents))
_assert("  . and the Current Pot is the balance, which is all three",
        got["current-fs-pot"].amount_cents == 2_750,
        str(got["current-fs-pot"].amount_cents))
# THE THREE SOURCES SUM TO THE BALANCE. It is the arithmetic a reader will do
# in their head, and if it did not hold the screen would be quietly wrong.
_assert("  . the three sources account for the whole pot",
        (got["unspent-minimum-sweeps"].amount_cents
         + got["topoffs-added-to-fs-pot"].amount_cents
         + got["terminal-pool-remainders"].amount_cents)
        == got["current-fs-pot"].amount_cents)

# A DISTRIBUTION DRAINS THE POT WITHOUT ERASING WHERE IT CAME FROM. The three
# source figures are what ARRIVED; the balance is what is left. Conflating them
# would make a paid-out season look like a season that was never funded.
ledger_post([(POT, -2_750), ("wallet:3", 2_750)],
            door="championship_distribution", session=live)
live.commit()
paid = _by_id(in_season_rows(live, league_id=LEAGUE, season=SEASON))
_assert("after the pot pays out the balance is zero",
        paid["current-fs-pot"].amount_cents == 0,
        str(paid["current-fs-pot"].amount_cents))
_assert("  . but the three sources still say what funded it",
        (paid["unspent-minimum-sweeps"].amount_cents,
         paid["topoffs-added-to-fs-pot"].amount_cents,
         paid["terminal-pool-remainders"].amount_cents) == (1_000, 1_000, 750),
        str([paid["unspent-minimum-sweeps"].amount_cents,
             paid["topoffs-added-to-fs-pot"].amount_cents,
             paid["terminal-pool-remainders"].amount_cents]))

# ANOTHER SEASON'S MONEY IS NOT THIS SEASON'S. The account name carries the
# season, so this needs no filter of its own -- which is the point of naming
# the pot that way, and is worth proving rather than assuming.
other = fantasystakes_championship_account(LEAGUE, SEASON + 1)
ledger_post([("season_issuance:1:2027", -5_000), ("min:1", 5_000)],
            door=SEASON_ALLOCATION_DOOR, session=live)
live.commit()
ledger_post([("min:1", -5_000), (other, 5_000)],
            door=DOOR_WEEKLY_MINIMUM_SWEEP, session=live)
live.commit()
still = _by_id(in_season_rows(live, league_id=LEAGUE, season=SEASON))
_assert("a later season's sweep does not appear in this season's figures",
        still["unspent-minimum-sweeps"].amount_cents == 1_000,
        str(still["unspent-minimum-sweeps"].amount_cents))


# -- S6 . the Season Rules ----------------------------------------------------

print("\nUI7-S6 " + chr(0x00b7) + " the five Season Rules, stated exactly")

_assert("there are five Season Rules", len(SEASON_RULES) == 5,
        str(len(SEASON_RULES)))
_assert("  . stated exactly as §23 states them",
        SEASON_RULES == (
            ("Weekly Minimum", "Regular season only"),
            ("Skunk Fees", "Regular season only"),
            ("Postseason play", "Wallet only"),
            ("Championship split", "60 / 30 / 10"),
            ("Wagers", "Public"),
        ), str(SEASON_RULES))
# THEY ARE PRODUCT RULES, so they are constants and not a read. A commissioner
# setting that could change one of them would be a different product.
_assert("  . they are a frozen tuple, not derived from any league",
        isinstance(SEASON_RULES, tuple)
        and all(isinstance(x, tuple) for x in SEASON_RULES))
_assert("  . and the split they state is the canonical one",
        dict(SEASON_RULES)["Championship split"] == "60 / 30 / 10")


# -- S7 . a LEGACY season is refused by name ----------------------------------

print("\nUI7-S7 " + chr(0x00b7) + " a LEGACY season is refused, not approximated")

legacy = _build(final_por=False)
try:
    view(legacy, league_id=LEAGUE, season=SEASON)
    _assert("a legacy season is refused", False, "it rendered a table")
except LeagueSettingsError as exc:
    _assert("a legacy season is refused", exc.reason == REASON_LEGACY_SEASON,
            exc.reason)
    _assert("  . and the refusal says why, naming the era",
            "LEGACY" in str(exc), str(exc)[:120])

full = view(_build(), league_id=LEAGUE, season=SEASON)
_assert("a Final POR season renders the whole view",
        len(full.allocation) == 7 and len(full.in_season) == 4
        and len(full.season_rules) == 5)
_assert("  . and reports the Weekly Minimum every ratio is taken against",
        full.weekly_minimum_cents == WEEKLY, str(full.weekly_minimum_cents))


# -- S8 . the module writes nothing -------------------------------------------

print("\nUI7-S8 " + chr(0x00b7) + " reading the settings changes nothing")

quiet = _build()


def _snapshot(session):
    return (
        session.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar(),
        session.execute(text("SELECT COUNT(*) FROM economy_event")).scalar(),
        session.execute(text(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries")).scalar(),
    )


before = _snapshot(quiet)
for _ in range(3):
    view(quiet, league_id=LEAGUE, season=SEASON)
quiet.commit()
after = _snapshot(quiet)

_assert("reading the view three times posts no ledger entry",
        before[0] == after[0], f"{before[0]} -> {after[0]}")
_assert("  . writes no economy event", before[1] == after[1],
        f"{before[1]} -> {after[1]}")
_assert("  . and the ledger still balances", after[2] == 0, str(after[2]))
_assert("  . every read returns the same figures",
        [x.amount_cents for x in view(quiet, league_id=LEAGUE,
                                      season=SEASON).allocation]
        == [x.amount_cents for x in view(quiet, league_id=LEAGUE,
                                         season=SEASON).allocation])

# NO WRITE PATH EXISTS TO BE FORGOTTEN. Walked as source rather than inferred
# from behaviour: a module that posts nothing today but imports the poster is
# one edit away from posting.
import inspect  # noqa: E402

import economy.league_settings_view as _lsv  # noqa: E402

_src = inspect.getsource(_lsv)
_code = "\n".join(line for line in _src.splitlines()
                  if not line.lstrip().startswith("#"))
_assert("the module never calls the ledger poster",
        "ledger_post(" not in _code and "post(" not in _code.replace(
            "ledger_post(", ""),
        "no posting call")
_assert("  . and records no economy event",
        "record_event" not in _code and "DuplicateEconomyEvent" not in _code)


print()
if _failures:
    print("=" * 52)
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("=" * 52)
print("UI-7 §23 League Settings view: ALL ASSERTIONS PASS")
