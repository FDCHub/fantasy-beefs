#!/usr/bin/env python3
"""
test_econcfg_f1_foundation_pg.py — ECONCFG-F1 · economy configuration foundation.

THE TWO QUESTIONS THIS SUITE ANSWERS, and the second matters more than the first:

    1. Can a commissioner configure a league-season economy, and does it freeze
       correctly and auditably at activation?

    2. Does absolutely nothing about live economics change as a result?

The second is the harder property and the whole reason Step 1 exists separately.
A foundation that quietly began funding from the new configuration — or worse,
mixed a new weekly minimum with an old championship reserve — would be a hybrid
economy nobody specified. So §7 below asserts the discriminating case directly:
a league that HAS configured a different economy is issued exactly the same
Credits as one that has not.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.

Runs as: python test_econcfg_f1_foundation_pg.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] ECONCFG-F1 suite cannot run:\n  {e}")
    sys.exit(2)

import config  # noqa: E402
from economy.league_economy_config import (  # noqa: E402
    DEFAULT_CHAMPIONSHIP_CONTRIBUTION_CENTS, DEFAULT_SKUNK_FEE_CENTS,
    DEFAULT_WEEKLY_BET_MINIMUM_CENTS, EconomyCalculation, EconomyConfigError,
    derive_regular_season_week_count, freeze_economy_config, read_draft,
    read_frozen, set_draft, validate_inputs,
)
from ledger.ledger import trial_balance  # noqa: E402

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


SEASON = config.ALLOCATION_SEASON


def make_league(db, *, name: str, teams: int = 12, start_week=1,
                playoff_start_week=15):
    """A league with provider boundaries stated, and `teams` active teams."""
    from db.schema import League, Team, Wallet

    league = League(season=SEASON, name=name, projection_source="fantasypros",
                    start_week=start_week, playoff_start_week=playoff_start_week,
                    season_final_week=17)
    db.add(league)
    db.flush()
    for i in range(teams):
        team = Team(league_id=league.id, team_name=f"{name}-t{i}",
                    owner=f"owner-{i}", email=f"{name}-{i}@x.test")
        db.add(team)
        db.flush()
        db.add(Wallet(team_id=team.id, balance=0.0))
    db.flush()
    return league


def _refusal(fn, *args, **kw):
    try:
        fn(*args, **kw)
        return None
    except EconomyConfigError as exc:
        return exc.reason


# ── 1 · Provider start_week ──────────────────────────────────────────────────

def case_provider_start_week(db) -> None:
    _section("F1-1 · Yahoo start_week reaches the domain and persists")
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo import normalize, parse

    transport = FixtureTransport()
    league_dto = normalize.normalize_league(
        parse.parse_league(transport.fetch_league("461.l.488800")))

    _assert("1a: the parsed Yahoo start_week reaches ProviderLeague",
            league_dto.start_week == 1, detail=str(league_dto.start_week))
    _assert("1b: alongside the two boundaries that already travelled",
            (league_dto.playoff_start_week, league_dto.season_final_week)
            == (15, 17),
            detail=f"{league_dto.playoff_start_week}/{league_dto.season_final_week}")

    # A provider that states NO start_week stays None — never defaulted to 1.
    silent = normalize.normalize_league({"league_key": "X.l.1", "name": "n",
                                         "season": SEASON})
    _assert("1c: a provider that states no start_week yields None, not 1",
            silent.start_week is None, detail=str(silent.start_week))

    from db.schema import League
    lg = make_league(db, name="f1-persist", start_week=None,
                     playoff_start_week=None)
    db.flush()
    _assert("1d: League.start_week exists and is nullable",
            lg.start_week is None)
    lg.start_week = 1
    db.flush()
    reread = db.query(League).filter(League.id == lg.id).one()
    _assert("1e: and persists", reread.start_week == 1)


def case_boundary_reconcile(db) -> None:
    _section("F1-2 · start_week follows the frozen-boundary discipline")
    from providers.yahoo.persist import _reconcile_boundary

    class _Result:
        def __init__(self):
            self.notes = []
            self.conflicts_recorded = 0
            self.conflict_keys = ()

    from datetime import datetime, timezone
    now = datetime(2025, 9, 1, tzinfo=timezone.utc)

    lg = make_league(db, name="f1-boundary", start_week=None)
    db.flush()

    r = _Result()
    _reconcile_boundary(db, lg, field_name="start_week", provider_value=1,
                        league_key="K", now=now, result=r)
    _assert("2a: the first authoritative value populates the boundary",
            lg.start_week == 1 and r.conflicts_recorded == 0,
            detail=str(lg.start_week))

    r2 = _Result()
    _reconcile_boundary(db, lg, field_name="start_week", provider_value=1,
                        league_key="K", now=now, result=r2)
    _assert("2b: the same value replays as a no-op",
            lg.start_week == 1 and r2.conflicts_recorded == 0)

    r3 = _Result()
    _reconcile_boundary(db, lg, field_name="start_week", provider_value=3,
                        league_key="K", now=now, result=r3)
    _assert("2c: a CONTRADICTING value is recorded as a conflict and the "
            "stored value is KEPT — never silently overwritten",
            lg.start_week == 1 and r3.conflicts_recorded == 1,
            detail=f"stored={lg.start_week} conflicts={r3.conflicts_recorded}")


# ── 3 · Validation and defaults ──────────────────────────────────────────────

def case_validation(db) -> None:
    _section("F1-3 · governed ranges, whole Credits, defaults")
    lg = make_league(db, name="f1-valid")
    db.flush()

    draft = read_draft(db, league_id=lg.id)
    _assert("3a: an unconfigured league reports the setup defaults "
            "$10 / $80 / $10",
            (draft.weekly_bet_minimum_cents,
             draft.championship_contribution_cents,
             draft.skunk_fee_cents) == (1000, 8000, 1000)
            and (DEFAULT_WEEKLY_BET_MINIMUM_CENTS,
                 DEFAULT_CHAMPIONSHIP_CONTRIBUTION_CENTS,
                 DEFAULT_SKUNK_FEE_CENTS) == (1000, 8000, 1000))
    _assert("3b: and reports itself UNCONFIGURED — defaults are a suggestion, "
            "not a configuration",
            draft.configured is False)

    ok = [
        ("weekly $1", 100, 8000, 1000), ("weekly $100", 10_000, 8000, 1000),
        ("championship $1", 1000, 100, 1000),
        ("championship $1,000", 1000, 100_000, 1000),
        ("skunk $1", 1000, 8000, 100), ("skunk $100", 1000, 8000, 10_000),
    ]
    for label, w, c, s in ok:
        _assert(f"3c: {label} accepted",
                validate_inputs(weekly_bet_minimum_cents=w,
                                championship_contribution_cents=c,
                                skunk_fee_cents=s) == (w, c, s))

    bad = [
        ("weekly below $1", 99, 8000, 1000, "ECONOMY_CONFIG_OUT_OF_RANGE"),
        ("weekly above $100", 10_100, 8000, 1000, "ECONOMY_CONFIG_OUT_OF_RANGE"),
        ("weekly zero", 0, 8000, 1000, "ECONOMY_CONFIG_OUT_OF_RANGE"),
        ("weekly negative", -100, 8000, 1000, "ECONOMY_CONFIG_OUT_OF_RANGE"),
        ("weekly fractional Credit", 1050, 8000, 1000,
         "ECONOMY_CONFIG_NOT_WHOLE_CREDITS"),
        ("championship below $1", 1000, 99, 1000, "ECONOMY_CONFIG_OUT_OF_RANGE"),
        ("championship above $1,000", 1000, 100_100, 1000,
         "ECONOMY_CONFIG_OUT_OF_RANGE"),
        ("championship fractional", 1000, 8050, 1000,
         "ECONOMY_CONFIG_NOT_WHOLE_CREDITS"),
        ("skunk below $1", 1000, 8000, 99, "ECONOMY_CONFIG_OUT_OF_RANGE"),
        ("skunk above $100", 1000, 8000, 10_100, "ECONOMY_CONFIG_OUT_OF_RANGE"),
        ("skunk fractional", 1000, 8000, 1050,
         "ECONOMY_CONFIG_NOT_WHOLE_CREDITS"),
        ("weekly null", None, 8000, 1000, "ECONOMY_CONFIG_MISSING_INPUT"),
    ]
    for label, w, c, s, reason in bad:
        _assert(f"3d: {label} refused ({reason})",
                _refusal(validate_inputs, weekly_bet_minimum_cents=w,
                         championship_contribution_cents=c,
                         skunk_fee_cents=s) == reason)


# ── 4 · Week-count derivation ────────────────────────────────────────────────

def case_derivation(db) -> None:
    _section("F1-4 · the regular-season week count is derived, never assumed")
    _assert("4a: start 1, playoff 15 -> 14 weeks",
            derive_regular_season_week_count(start_week=1,
                                             playoff_start_week=15) == 14)
    _assert("4b: start 1, playoff 14 -> 13 weeks",
            derive_regular_season_week_count(start_week=1,
                                             playoff_start_week=14) == 13)
    _assert("4c: start 2, playoff 15 -> 13 weeks — start_week is NOT assumed 1",
            derive_regular_season_week_count(start_week=2,
                                             playoff_start_week=15) == 13)
    _assert("4d: a missing start_week refuses",
            _refusal(derive_regular_season_week_count, start_week=None,
                     playoff_start_week=15)
            == "ECONOMY_CONFIG_BOUNDARY_UNAVAILABLE")
    _assert("4e: a missing playoff_start_week refuses",
            _refusal(derive_regular_season_week_count, start_week=1,
                     playoff_start_week=None)
            == "ECONOMY_CONFIG_BOUNDARY_UNAVAILABLE")
    _assert("4f: playoff_start_week <= start_week refuses",
            _refusal(derive_regular_season_week_count, start_week=15,
                     playoff_start_week=15)
            == "ECONOMY_CONFIG_BOUNDARY_INVALID")

    # NO HARDCODED 14 anywhere in the derivation module's executable code.
    import io
    import tokenize

    src = open("economy/league_economy_config.py", encoding="utf-8").read()
    numbers = [t.string for t in
               tokenize.generate_tokens(io.StringIO(src).readline)
               if t.type == tokenize.NUMBER]
    banned = sorted({n for n in numbers
                     if n in {"14", "220", "22000", "14000", "140"}})
    _assert("4g: no 14 / 140 / 220 constant in the configuration module's "
            "executable code (comments and docstrings excluded)",
            not banned, detail=str(banned))


# ── 5 · Computed values, league size ─────────────────────────────────────────

def case_calculations(db) -> None:
    _section("F1-5 · Season-Opening Allocation arithmetic and league size")
    def calc(weekly, champ, weeks, teams):
        return EconomyCalculation(weekly_bet_minimum_cents=weekly,
                                  championship_contribution_cents=champ,
                                  skunk_fee_cents=1000,
                                  regular_season_week_count=weeks,
                                  active_team_count=teams)

    a = calc(1000, 8000, 14, 12)
    _assert("5a: $10 x 14 + $80 = $220 per player",
            a.season_opening_allocation_per_player_cents == 22_000,
            detail=str(a.season_opening_allocation_per_player_cents))
    _assert("5b: of which $140 is the Weekly Minimum Reserve",
            a.weekly_minimum_reserve_per_player_cents == 14_000)
    _assert("5c: and $80 the Championship Reserve",
            a.championship_reserve_per_player_cents == 8_000)

    b = calc(1000, 8000, 13, 12)
    _assert("5d: $10 x 13 + $80 = $210 — a shorter season allocates less",
            b.season_opening_allocation_per_player_cents == 21_000,
            detail=str(b.season_opening_allocation_per_player_cents))

    for teams, total in ((8, 176_000), (10, 220_000), (12, 264_000)):
        c = calc(1000, 8000, 14, teams)
        _assert(f"5e: {teams} teams -> league total ${total // 100:,}",
                c.league_opening_allocation_cents == total,
                detail=str(c.league_opening_allocation_cents))
        _assert(f"5f: and the PER-PLAYER total is still $220 at {teams} teams",
                c.season_opening_allocation_per_player_cents == 22_000)

    _assert("5g: an odd team count is ordinary",
            calc(1000, 8000, 14, 11).league_opening_allocation_cents == 242_000)


# ── 6 · Draft, freeze, immutability ──────────────────────────────────────────

def case_freeze(db) -> None:
    _section("F1-6 · draft edits freely, freezes once, then refuses")
    lg = make_league(db, name="f1-freeze", teams=10)
    db.flush()

    set_draft(db, league_id=lg.id, weekly_bet_minimum_cents=1500,
              championship_contribution_cents=9000, skunk_fee_cents=500)
    d1 = read_draft(db, league_id=lg.id)
    _assert("6a: the commissioner may set a draft before activation",
            (d1.weekly_bet_minimum_cents, d1.championship_contribution_cents,
             d1.skunk_fee_cents) == (1500, 9000, 500) and d1.configured)

    set_draft(db, league_id=lg.id, weekly_bet_minimum_cents=2000,
              championship_contribution_cents=10_000, skunk_fee_cents=1000)
    d2 = read_draft(db, league_id=lg.id)
    _assert("6b: and may edit it again",
            (d2.weekly_bet_minimum_cents, d2.championship_contribution_cents)
            == (2000, 10_000))

    frozen = freeze_economy_config(db, league_id=lg.id, season=SEASON)
    db.flush()
    _assert("6c: the freeze records the exact commissioner inputs",
            (frozen.weekly_bet_minimum_cents,
             frozen.championship_contribution_cents,
             frozen.skunk_fee_cents) == (2000, 10_000, 1000))
    _assert("6d: and the derived week count",
            frozen.regular_season_week_count == 14,
            detail=str(frozen.regular_season_week_count))
    _assert("6e: and the active team count",
            frozen.active_team_count == 10,
            detail=str(frozen.active_team_count))
    _assert("6f: and the two boundaries it was derived FROM, so the count can "
            "be checked without re-reading live provider state",
            (frozen.start_week_used, frozen.playoff_start_week_used) == (1, 15))
    _assert("6g: the Season-Opening Allocation can be reconstructed exactly "
            "from the frozen row",
            EconomyCalculation(
                weekly_bet_minimum_cents=frozen.weekly_bet_minimum_cents,
                championship_contribution_cents=frozen.championship_contribution_cents,
                skunk_fee_cents=frozen.skunk_fee_cents,
                regular_season_week_count=frozen.regular_season_week_count,
                active_team_count=frozen.active_team_count
            ).season_opening_allocation_per_player_cents == 38_000)

    _assert("6h: an identical re-freeze is idempotent — the same row",
            freeze_economy_config(db, league_id=lg.id, season=SEASON).id
            == frozen.id)

    _assert("6i: the draft cannot be edited after the freeze",
            _refusal(set_draft, db, league_id=lg.id,
                     weekly_bet_minimum_cents=1000,
                     championship_contribution_cents=8000,
                     skunk_fee_cents=1000) == "ECONOMY_CONFIG_FROZEN")

    # A CONFLICTING re-freeze refuses. Reached by mutating the League row
    # directly — the route path is already closed by 6i, so this proves the
    # domain refuses even a caller that bypassed it.
    # A PROVIDER SETTINGS CHANGE AFTER THE FREEZE. The league's playoff start
    # moves, so a fresh derivation would give thirteen weeks where the stamped
    # row says fourteen. The freeze refuses rather than quietly restating the
    # season's economy on a basis Credits were not issued under — which is the
    # whole of the mid-season maintainability rule for this table.
    #
    # THE COMMISSIONER'S THREE INPUTS CANNOT DRIFT AT ALL. With one row there is
    # no second copy to disagree with, so the only conflict representable is a
    # DERIVED one. That is a property of the single-row design, not an omission.
    lg.playoff_start_week = 14
    db.flush()
    _assert("6j: a re-freeze whose DERIVED week count disagrees with the "
            "stamped row is refused",
            _refusal(freeze_economy_config, db, league_id=lg.id, season=SEASON)
            == "ECONOMY_CONFIG_FROZEN_CONFLICT")
    frozen_now = read_frozen(db, league_id=lg.id, season=SEASON)
    _assert("6j2: and the stamped row is UNCHANGED — the provider moved, the "
            "season's economy did not",
            (frozen_now.regular_season_week_count,
             frozen_now.playoff_start_week_used) == (14, 15),
            detail=f"{frozen_now.regular_season_week_count}/"
                   f"{frozen_now.playoff_start_week_used}")
    lg.playoff_start_week = 15
    db.flush()

    from db.schema import LeagueSeasonEconomyConfig
    _assert("6k: exactly ONE frozen row exists for the league-season",
            db.query(LeagueSeasonEconomyConfig).filter(
                LeagueSeasonEconomyConfig.league_id == lg.id,
                LeagueSeasonEconomyConfig.season == SEASON).count() == 1)

    # A configured league whose boundaries are unavailable cannot freeze.
    lg2 = make_league(db, name="f1-noboundary", start_week=None)
    set_draft(db, league_id=lg2.id, weekly_bet_minimum_cents=1000,
              championship_contribution_cents=8000, skunk_fee_cents=1000)
    db.flush()
    _assert("6l: a configured league with no start_week REFUSES to freeze",
            _refusal(freeze_economy_config, db, league_id=lg2.id, season=SEASON)
            == "ECONOMY_CONFIG_BOUNDARY_UNAVAILABLE")

    # An UNCONFIGURED league freezes nothing and refuses nothing.
    lg3 = make_league(db, name="f1-unconfigured")
    db.flush()
    _assert("6m: an UNCONFIGURED league writes no row and raises nothing — "
            "absence is a governed state, not a gap",
            freeze_economy_config(db, league_id=lg3.id, season=SEASON) is None)
    _assert("6n: and reads back as unconfigured",
            read_frozen(db, league_id=lg3.id, season=SEASON) is None)


# ── 7 · THE ECONOMIC AUTHORITY FENCE
#
# THIS SECTION WAS INVERTED BY THE COMBINED ECONOMY PARAMETERIZATION PACKAGE,
# AND THE INVERSION IS THE POINT. Under ECONCFG-F1 it asserted the OPPOSITE of
# everything below: that a configured league was issued the fixed-stop amounts
# and that its frozen row was an audit record with no authority. That was true
# and deliberate — F1 built the configuration and refused to wire it, so the
# schema, the freeze discipline and the derivation could be certified before a
# single Credit depended on them.
#
# The wiring package moves the authority, so an unchanged §7 would now be
# asserting that the wiring did not happen. Each assertion is therefore restated
# as its opposite rather than deleted, so the two economies stay pinned against
# each other in one place and neither can quietly become the other. ────────────────────────────────────────

def case_configured_economy_is_authoritative(db) -> None:
    _section("F1-7 · FENCE — the frozen configuration IS the live economy")
    from db.schema import LeagueSeasonEconomyConfig, SeasonAllocation
    from economy.season_allocation import activate_season_allocation
    from payments.economy_config import DEFAULT_STOP

    # Two identical leagues. One configures a DELIBERATELY DIFFERENT economy;
    # the other configures nothing. Their allocations must now DIFFER, and the
    # unconfigured one must be issued exactly what it was issued before this
    # package existed — the two halves of "no hybrid economics".
    configured = make_league(db, name="f1-fence-cfg", teams=4)
    plain = make_league(db, name="f1-fence-plain", teams=4)
    set_draft(db, league_id=configured.id, weekly_bet_minimum_cents=2500,
              championship_contribution_cents=100_000, skunk_fee_cents=10_000)
    db.commit()

    activate_season_allocation(configured.id, db)
    activate_season_allocation(plain.id, db)

    rows_cfg = (db.query(SeasonAllocation)
                .filter(SeasonAllocation.league_id == configured.id).all())
    rows_plain = (db.query(SeasonAllocation)
                  .filter(SeasonAllocation.league_id == plain.id).all())

    _assert("7a: both leagues activated",
            len(rows_cfg) == 4 and len(rows_plain) == 4,
            detail=f"{len(rows_cfg)}/{len(rows_plain)}")

    cfg_amounts = {(r.buyin_cents, r.min_reserve_cents, r.reserve_cents)
                   for r in rows_cfg}
    plain_amounts = {(r.buyin_cents, r.min_reserve_cents, r.reserve_cents)
                     for r in rows_plain}
    expected = {(DEFAULT_STOP.buyin_cents, DEFAULT_STOP.min_reserve_cents,
                 DEFAULT_STOP.reserve_cents)}

    # $25/week x 14 regular-season weeks = $350 of Weekly Minimum, plus the
    # $1,000 Championship contribution, is a $1,350 Season-Opening Allocation.
    # Every number is derived from the three commissioner inputs and the
    # league's own boundaries; none is written here twice.
    _assert("7b: THE CONFIGURED LEAGUE IS ISSUED ITS OWN ECONOMY — $1,350 "
            "Season-Opening Allocation, $350 Weekly Minimum reserve, $1,000 "
            "Championship contribution",
            cfg_amounts == {(135_000, 35_000, 100_000)}, detail=str(cfg_amounts))
    _assert("7c: and is issued something DIFFERENT from the unconfigured "
            "league — the configuration is authority, not decoration",
            cfg_amounts != plain_amounts,
            detail=f"{cfg_amounts} vs {plain_amounts}")
    _assert("7d: while the UNCONFIGURED league is still issued 22000 / 14000 / "
            "8000 — the certified legacy stop, unchanged for every league "
            "that configured nothing",
            plain_amounts == expected == {(22_000, 14_000, 8_000)},
            detail=str(plain_amounts))

    _assert("7e: the configured league DID freeze an audit row",
            db.query(LeagueSeasonEconomyConfig).filter(
                LeagueSeasonEconomyConfig.league_id == configured.id).count() == 1)
    _assert("7f: the unconfigured league froze NOTHING",
            db.query(LeagueSeasonEconomyConfig).filter(
                LeagueSeasonEconomyConfig.league_id == plain.id).count() == 0)

    frozen = read_frozen(db, league_id=configured.id, season=SEASON)
    _assert("7g: and what was ISSUED equals what the frozen row DERIVES — the "
            "row is the authority the ledger was funded from, not a record "
            "kept beside it",
            EconomyCalculation(
                weekly_bet_minimum_cents=frozen.weekly_bet_minimum_cents,
                championship_contribution_cents=frozen.championship_contribution_cents,
                skunk_fee_cents=frozen.skunk_fee_cents,
                regular_season_week_count=frozen.regular_season_week_count,
                active_team_count=frozen.active_team_count
            ).season_opening_allocation_per_player_cents
            == next(iter(cfg_amounts))[0] == 135_000)

    _assert("7h: the ledger is balanced", trial_balance() == 0,
            detail=str(trial_balance()))

    # Skunk now charges the CONFIGURED fee, and an unconfigured league still
    # charges the certified default. Read through the production resolver rather
    # than by inspecting source, so the assertion is about behaviour.
    from economy.skunk import (
        DEFAULT_SKUNK_CONTRIBUTION_CENTS, resolve_skunk_fee_cents,
    )

    _cfg_fee = resolve_skunk_fee_cents(db, league_id=configured.id, season=SEASON)
    _plain_fee = resolve_skunk_fee_cents(db, league_id=plain.id, season=SEASON)
    _assert("7i: the weekly Skunk fee follows the configuration — $100 for "
            "the configured league, the certified $10 default for the one that "
            "configured nothing",
            _cfg_fee == 10_000
            and _plain_fee == DEFAULT_SKUNK_CONTRIBUTION_CENTS == 1000,
            detail=f"cfg={_cfg_fee} plain={_plain_fee}")

    # The Championship Pot's recipient authority moved in the SAME package, and
    # the two are asserted together deliberately: they are the two live money
    # authorities this program changed, and a later edit that reverted either
    # one would leave the other's assertion passing on its own.
    import inspect as _inspect

    import economy.season_reconciliation as _recon
    _assert("7j: the Championship Pot is paid by the POSTSEASON PODIUM, and "
            "the regular-season ordering that used to pay it is gone from the "
            "module",
            "resolve_podium" in _inspect.getsource(_recon.distribute_championship)
            and getattr(_recon, "default_standings_order", None) is None)


# ── 8 · Migration, compatibility, structural ─────────────────────────────────

def case_migration(db) -> None:
    _section("F1-8 · migration, compatibility, storage boundary")
    from sqlalchemy import inspect as sa_inspect, text as sa_text

    from db.migrations.migrate_econcfg_f1_economy_config import (
        LEAGUE_COLUMNS, TABLE, missing_league_columns, table_exists, upgrade,
    )
    from db.schema import LeagueSeasonEconomyConfig, engine

    db.commit()
    with engine.begin() as conn:
        conn.execute(sa_text(f"DROP TABLE IF EXISTS {TABLE}"))
    _assert("8a: the table is genuinely absent before the migration runs",
            not table_exists(engine))

    created = upgrade(engine)
    _assert("8b: the production migration creates it",
            table_exists(engine) and "created" in created, detail=created)
    _assert("8c: re-running is a clean no-op",
            "nothing to do" in upgrade(engine))

    orm_cols = {c.name for c in LeagueSeasonEconomyConfig.__table__.columns}
    db_cols = {c["name"] for c in sa_inspect(engine).get_columns(TABLE)}
    _assert("8d: the migration's DDL and the ORM model agree on every column",
            orm_cols == db_cols,
            detail=str(orm_cols.symmetric_difference(db_cols)))
    _assert("8e: and the additive league column is present",
            missing_league_columns(engine) == [],
            detail=str(missing_league_columns(engine)))
    _assert("8f: exactly ONE league column was added — `leagues` is the "
            "most-locked table and every column there costs lock-observability "
            "budget",
            len(LEAGUE_COLUMNS) == 1, detail=str([n for n, _ in LEAGUE_COLUMNS]))

    # STORAGE BOUNDARY: no raw provider payload is persisted anywhere here.
    _assert("8g: the frozen row stores only integers and one timestamp — no "
            "provider payload, no settings blob, no league-name copy",
            orm_cols == {"id", "league_id", "season",
                         "weekly_bet_minimum_cents",
                         "championship_contribution_cents", "skunk_fee_cents",
                         "regular_season_week_count", "active_team_count",
                         "start_week_used", "playoff_start_week_used",
                         "frozen_at", "created_at"},
            detail=str(sorted(orm_cols)))


def case_structural(db) -> None:
    _section("F1-9 · structural — the config module posts nothing")
    import ast
    import inspect

    from economy import league_economy_config as lec

    src = inspect.getsource(lec)
    tree = ast.parse(src)
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    _assert("9a: it imports no ledger and no provider implementation",
            not (roots & {"ledger", "providers", "yfpy", "requests"}),
            detail=str(sorted(roots)))
    for banned in ("ledger_post", "post(", "trial_balance", "SeasonAllocation"):
        _assert(f"9b: it never references {banned!r} — it computes, it never "
                f"issues", banned not in src)


def main() -> None:
    with tdb.SessionLocal() as db:
        case_provider_start_week(db)
        db.rollback()
    with tdb.SessionLocal() as db:
        case_boundary_reconcile(db)
        db.rollback()
    with tdb.SessionLocal() as db:
        case_validation(db)
        db.rollback()
    with tdb.SessionLocal() as db:
        case_derivation(db)
        db.rollback()
    with tdb.SessionLocal() as db:
        case_calculations(db)
        db.rollback()
    with tdb.SessionLocal() as db:
        case_freeze(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_configured_economy_is_authoritative(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_migration(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_structural(db)
        db.rollback()


if __name__ == "__main__":
    print("  ECONCFG-F1 — ECONOMY CONFIGURATION FOUNDATION")
    tdb.reset()
    main()
    print()
    if _failures:
        print(f"RESULT: {len(_failures)} assertion(s) FAILED")
        for label in _failures:
            print(f"  - {label}")
        sys.exit(1)
    print("RESULT: all ECONCFG-F1 foundation assertions PASSED")
