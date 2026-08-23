#!/usr/bin/env python3
"""FINAL POR · WP-5 certification — league-level minted championship pots.

    F1   the three pots exist, are season-scoped, and are distinct namespaces
    F2   the FantasyStakes Base Pot is Weekly Minimum x weeks, NOT x GM count
    F3   minting conserves, and creates no duplicate VC
    F4   NO per-GM championship liability is created by a minted pot
    F5   the Fantasy Football pot may be 0, and 0 is not the same as unminted
    F6   the Points pot is NEVER minted; it is the Skunk actually assessed
    F7   activation posts no `reserve:{team}` leg under the Final POR
    F8   terminal Prop Pool remainders reach the FantasyStakes pot
    F9   a Final POR season NEVER writes to a retired namespace
    F10  minting is exactly-once per pillar; replay mints nothing
    F11  a LEGACY season is completely unchanged, and the retired paths still run
    F12  the retirements refuse rather than silently no-op
    F13  the SQLite migration path applies, is idempotent, and admits 0/NULL

WHY F4 IS THE ONE THAT DECIDES WHETHER MODEL B IS REAL. Every other assertion
here would also hold of an architecture that simply renamed the accounts. F4
reads back every leg ever posted under the mint door and requires that not one
of them names a GM — which is the difference between "the league allocated the
pot" and "the GMs prepaid it under a new name".

WHY F2 IS SPELLED OUT AT TWO FIELD SIZES. The retired model charged each GM a
contribution, so the pot scaled with the field. The same fixture is built with
four GMs and with ten and the Base Pot must be IDENTICAL. A pot that changed
would be the old model wearing the new name.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import ledger.ledger as ledger_module
from db.schema import Base, League, LeagueSeasonEconomyConfig, Matchup, Team, Wallet
from economy.championship_pots import (
    ChampionshipPotError,
    MINTABLE_PILLARS,
    fantasystakes_base_pot_cents,
    mint_pot,
    mint_season_pots,
    no_gm_liability,
    pot_balances,
    terminal_pool_destination,
)
from economy.current_settle import current_settle
from economy.economy_events import (
    CHAMPIONSHIP_PILLARS,
    DOOR_CHAMPIONSHIP_POT_MINT,
    EVENT_CHAMPIONSHIP_POT_MINT,
    PILLAR_FANTASY_FOOTBALL,
    PILLAR_FANTASYSTAKES,
    PILLAR_POINTS,
    RETIRED_FOR_FINAL_POR_ACCOUNTS,
    RETIRED_FOR_FINAL_POR_PREFIXES,
    DuplicateEconomyEvent,
    championship_issuance_account,
    championship_pot_account,
)
from economy.season_reconciliation import (
    consolidate_legacy_championship, sweep_championship_reserves,
)
from economy.skunk import assess_weekly_skunk, skunk_pot_account
from ledger.ledger import CHAMPIONSHIP_POT_MINT_DOOR, post as ledger_post
from ruleset import RULESET_FINAL_POR, is_final_por, stamp_ruleset

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
WEEKLY = 1_000
FF_POT = 5_000


def _build(*, final_por: bool, team_count: int = 4, configured: bool = True,
           ff_pot_cents: int | None = FF_POT):
    """A league-season, optionally with a FROZEN economy configuration.

    The configuration is frozen directly rather than through activation, so this
    suite can vary the field size and the Fantasy Football amount independently
    of everything activation also does.
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=LEAGUE, name="L", season=SEASON, start_week=1,
                  playoff_start_week=15))
    for t in range(1, team_count + 1):
        db.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider_team_key=f"k{t}"))
        db.add(Wallet(team_id=t, balance=0.0))
    db.add(Matchup(id=1, league_id=LEAGUE, week=1, home_team_id=1,
                   away_team_id=2, home_score=100.0, away_score=98.0,
                   winner_team_id=1, finalized_at=NAIVE))
    if team_count >= 4:
        db.add(Matchup(id=2, league_id=LEAGUE, week=1, home_team_id=3,
                       away_team_id=4, home_score=60.0, away_score=120.0,
                       winner_team_id=4, finalized_at=NAIVE))
    if configured:
        db.add(LeagueSeasonEconomyConfig(
            league_id=LEAGUE, season=SEASON,
            weekly_bet_minimum_cents=WEEKLY,
            championship_contribution_cents=8_000,
            skunk_fee_cents=500,
            ff_championship_pot_cents=ff_pot_cents,
            regular_season_week_count=WEEKS,
            active_team_count=team_count,
            start_week_used=1, playoff_start_week_used=15,
            frozen_at=NAIVE))
    db.commit()

    if final_por:
        stamp_ruleset(db, league_id=LEAGUE, season=SEASON,
                      version=RULESET_FINAL_POR)
        db.commit()
    return db


def _bal(db, account: str) -> int:
    return ledger_module._balance_of_in_session(db, account)


def _accounts_touched(db) -> set[str]:
    return {r[0] for r in db.execute(text(
        "SELECT DISTINCT account FROM ledger_entries")).fetchall()}


# ── F1 · three season-scoped pots, three distinct namespaces ─────────────────

print("\nWP5-F1 · the three pots are season-scoped and distinct")
_assert("three pillars are enumerated",
        CHAMPIONSHIP_PILLARS
        == (PILLAR_FANTASYSTAKES, PILLAR_POINTS, PILLAR_FANTASY_FOOTBALL),
        str(CHAMPIONSHIP_PILLARS))
names = [championship_pot_account(p, LEAGUE, SEASON)
         for p in CHAMPIONSHIP_PILLARS]
_assert("  · every pot name carries the season",
        all(n.endswith(f":{LEAGUE}:{SEASON}") for n in names), str(names))
_assert("  · all three are distinct namespaces", len(set(names)) == 3, str(names))
_assert("  · and none of them IS the retired `championship:{league}`",
        f"championship:{LEAGUE}" not in names, str(names))
_assert("  · a second season resolves three different accounts",
        set(names).isdisjoint(
            championship_pot_account(p, LEAGUE, SEASON + 1)
            for p in CHAMPIONSHIP_PILLARS))


# ── F2 · the Base Pot does not scale with the field ─────────────────────────

print("\nWP5-F2 · Base Pot = Weekly Minimum x weeks, NOT x GM count")
four = _build(final_por=True, team_count=4)
ten = _build(final_por=True, team_count=10)
base_4 = fantasystakes_base_pot_cents(four, league_id=LEAGUE, season=SEASON)
base_10 = fantasystakes_base_pot_cents(ten, league_id=LEAGUE, season=SEASON)

_assert("the Base Pot is weekly x weeks", base_4 == WEEKLY * WEEKS,
        f"{base_4} vs {WEEKLY * WEEKS}")
_assert("  · a ten-GM league opens the SAME Base Pot as a four-GM league",
        base_4 == base_10, f"4 GMs: {base_4}, 10 GMs: {base_10}")
_assert("  · which it would not if the field were a factor",
        base_10 != WEEKLY * WEEKS * 10)

import inspect  # noqa: E402

import economy.championship_pots as cp  # noqa: E402

src = inspect.getsource(cp.fantasystakes_base_pot_cents)
_assert("  · and no team count is read in deriving it",
        "Team" not in src and "team_count" not in src
        and "active_team" not in src)


# ── F3/F4 · minting conserves and creates no GM liability ───────────────────

print("\nWP5-F3 · minting conserves and mints no duplicate VC")
db = _build(final_por=True, team_count=4)
results = mint_season_pots(db, league_id=LEAGUE, season=SEASON,
                           fantasy_football_cents=FF_POT, now=NOW)
db.commit()
pots = pot_balances(db, league_id=LEAGUE, season=SEASON)

_assert("the FantasyStakes pot holds its Base",
        pots.fantasystakes_cents == WEEKLY * WEEKS,
        str(pots.fantasystakes_cents))
_assert("  · the Fantasy Football pot holds the entered amount",
        pots.fantasy_football_cents == FF_POT,
        str(pots.fantasy_football_cents))
_assert("  · the Points pot is empty — it is never minted",
        pots.points_cents == 0, str(pots.points_cents))
_assert("  · the issuance tally equals exactly what was minted",
        pots.minted_cents == WEEKLY * WEEKS + FF_POT, str(pots.minted_cents))
_assert("  · the global trial balance is zero",
        ledger_module.trial_balance() == 0,
        str(ledger_module.trial_balance()))
_assert("  · every mint leg pair sums to zero",
        db.execute(text("SELECT COALESCE(SUM(amount_cents),0) FROM "
                        "ledger_entries WHERE door = :d"),
                   {"d": DOOR_CHAMPIONSHIP_POT_MINT}).scalar() == 0)
_assert("  · two funded pillars, named",
        pots.funded_pillars == (PILLAR_FANTASYSTAKES, PILLAR_FANTASY_FOOTBALL),
        str(pots.funded_pillars))

print("\nWP5-F4 · a minted pot creates NO per-GM championship liability")
_assert("no leg under the mint door names a GM account",
        no_gm_liability(db, league_id=LEAGUE, season=SEASON))
mint_accounts = {r[0] for r in db.execute(text(
    "SELECT DISTINCT account FROM ledger_entries WHERE door = :d"),
    {"d": DOOR_CHAMPIONSHIP_POT_MINT}).fetchall()}
_assert("  · and the leg set is exactly issuance + the two minted pots",
        mint_accounts == {championship_issuance_account(LEAGUE, SEASON),
                          championship_pot_account(PILLAR_FANTASYSTAKES,
                                                   LEAGUE, SEASON),
                          championship_pot_account(PILLAR_FANTASY_FOOTBALL,
                                                   LEAGUE, SEASON)},
        str(sorted(mint_accounts)))
for t in (1, 2, 3, 4):
    settle = current_settle(db, team_id=t, league_id=LEAGUE, season=SEASON)
    if t == 1:
        _assert("  · a GM's obligations are 0 after the whole league's pots "
                "were minted", settle.obligations_cents == 0,
                str(settle.as_dict()))
        _assert("  · their Current Settle is 0 — the pot cost them nothing",
                settle.current_settle_cents == 0,
                str(settle.current_settle_cents))
_assert("  · no receivable: was created by minting",
        all(_bal(db, f"receivable:{t}") == 0 for t in (1, 2, 3, 4)))
_assert("  · no reserve: was created by minting",
        all(_bal(db, f"reserve:{t}") == 0 for t in (1, 2, 3, 4)))
_assert("  · the issuance namespace is NOT one Current Settle counts",
        "championship_issuance" not in inspect.getsource(current_settle))


# ── F5 · zero is a governed amount ──────────────────────────────────────────

print("\nWP5-F5 · the Fantasy Football pot may be 0")
zero = _build(final_por=True, ff_pot_cents=0)
zr = mint_season_pots(zero, league_id=LEAGUE, season=SEASON,
                      fantasy_football_cents=0, now=NOW)
zero.commit()
zp = pot_balances(zero, league_id=LEAGUE, season=SEASON)
ff_result = [r for r in zr if r.pillar == PILLAR_FANTASY_FOOTBALL][0]

_assert("a 0 mint is accepted", ff_result.amount_cents == 0)
_assert("  · it recorded its event", zero.execute(text(
    "SELECT COUNT(*) FROM economy_event WHERE event_type = :t"),
    {"t": EVENT_CHAMPIONSHIP_POT_MINT}).scalar() == 2)
_assert("  · but posted NO ledger leg", ff_result.posted is False)
_assert("  · the pillar reads unfunded", zp.fantasy_football_cents == 0)
_assert("  · so only ONE pillar is funded",
        zp.funded_pillars == (PILLAR_FANTASYSTAKES,), str(zp.funded_pillars))
_assert("  · and §20's two-funded-pillar bar is therefore not met",
        len(zp.funded_pillars) < 2)
try:
    mint_pot(zero, league_id=LEAGUE, season=SEASON,
             pillar=PILLAR_FANTASY_FOOTBALL, amount_cents=-1, now=NOW)
    _assert("  · a NEGATIVE mint is refused", False, "accepted")
except ChampionshipPotError as exc:
    zero.rollback()
    _assert("  · a NEGATIVE mint is refused", exc.reason == "POT_NEGATIVE_AMOUNT",
            exc.reason)


# ── F6 · the Points pot is the Skunk actually assessed ──────────────────────

print("\nWP5-F6 · the Points pot is never minted; it IS the Skunk assessed")
try:
    mint_pot(db, league_id=LEAGUE, season=SEASON, pillar=PILLAR_POINTS,
             amount_cents=500, now=NOW)
    _assert("minting the Points pot is refused", False, "accepted")
except ChampionshipPotError as exc:
    db.rollback()
    _assert("minting the Points pot is refused",
            exc.reason == "POT_NOT_MINTABLE", exc.reason)
_assert("  · POINTS is absent from the mintable set",
        PILLAR_POINTS not in MINTABLE_PILLARS, str(MINTABLE_PILLARS))

skunked = _build(final_por=True)
_assert("  · the era routes Skunk to the season-scoped Points pot",
        skunk_pot_account(skunked, league_id=LEAGUE, season=SEASON)
        == f"points_championship:{LEAGUE}:{SEASON}",
        skunk_pot_account(skunked, league_id=LEAGUE, season=SEASON))
assess_weekly_skunk(skunked, league_id=LEAGUE, week=1,
                    contribution_cents=500, now=NOW)
skunked.commit()
sp = pot_balances(skunked, league_id=LEAGUE, season=SEASON)
_assert("  · the assessed fee landed in it", sp.points_cents == 500,
        str(sp.points_cents))
_assert("  · and NOT in the season-less `skunk:{league}`",
        _bal(skunked, f"skunk:{LEAGUE}") == 0,
        str(_bal(skunked, f"skunk:{LEAGUE}")))
_assert("  · the pot equals the Skunk assessed, not a projection",
        sp.points_cents == 500 and sp.points_cents != 500 * WEEKS)
_assert("  · minting it would have been required to reach a projection",
        sp.minted_cents == 0, str(sp.minted_cents))
_assert("  · the GM's receivable is unchanged by the re-homing",
        _bal(skunked, "receivable:3") == -500,
        str(_bal(skunked, "receivable:3")))


# ── F7 · activation posts no reserve leg ────────────────────────────────────

print("\nWP5-F7 · a Final POR activation posts no `reserve:{team}` leg")
import economy.season_allocation as sa  # noqa: E402

alloc_src = inspect.getsource(sa.activate_season_allocation)
_assert("the reserve leg is conditional on the era",
        "if not final_por:" in alloc_src
        and "reserve_account(team_id), stop.reserve_cents" in alloc_src)
_assert("  · the advance is the Weekly Minimum Reserve under the Final POR",
        "advance_cents = (stop.min_reserve_cents if final_por" in alloc_src)
_assert("  · and the pots are minted in the same transaction",
        "mint_season_pots(" in alloc_src)
_assert("  · the result reports what was POSTED, not what was priced",
        "advance = stop.min_reserve_cents if final_por else stop.buyin_cents"
        in inspect.getsource(sa._result))


# ── F8 · terminal Pool remainders reach the FantasyStakes pot ───────────────

print("\nWP5-F8 · terminal Prop Pool remainders reach the FantasyStakes pot")
_assert("the Final POR destination is the FantasyStakes pot",
        terminal_pool_destination(db, league_id=LEAGUE, season=SEASON)
        == f"fantasystakes_championship:{LEAGUE}:{SEASON}",
        terminal_pool_destination(db, league_id=LEAGUE, season=SEASON))
legacy_db = _build(final_por=False)
_assert("  · and the legacy destination is unchanged",
        terminal_pool_destination(legacy_db, league_id=LEAGUE, season=SEASON)
        == f"championship:{LEAGUE}",
        terminal_pool_destination(legacy_db, league_id=LEAGUE, season=SEASON))

import betting.pool_funding as pf  # noqa: E402
import betting.pool_settlement as ps  # noqa: E402

for module, name in ((pf, "pool_funding"), (ps, "pool_settlement")):
    text_src = inspect.getsource(module)
    _assert(f"  · {name} routes every terminal leg through the resolver",
            'f"championship:{league_id}"' not in text_src
            and 'f"championship:{instance.league_id}"' not in text_src)
    _assert(f"  · {name} imports it", "terminal_pool_destination" in text_src)

# A real remainder posting, end to end.
fs_before = _bal(db, f"fantasystakes_championship:{LEAGUE}:{SEASON}")
ledger_post([(f"season_issuance:{LEAGUE}:{SEASON}", -700),
             (f"pool:{LEAGUE}", 700)],
            door="season_allocation", session=db)
ledger_post([(f"pool:{LEAGUE}", -700),
             (terminal_pool_destination(db, league_id=LEAGUE, season=SEASON),
              700)],
            door="pool_rollover_expiry", session=db)
db.commit()
_assert("  · a terminal remainder really lands in the FantasyStakes pot",
        _bal(db, f"fantasystakes_championship:{LEAGUE}:{SEASON}")
        == fs_before + 700)
_assert("  · and `championship:{league}` never received it",
        _bal(db, f"championship:{LEAGUE}") == 0)


# ── F9 · no retired namespace is ever written by a Final POR season ─────────

print("\nWP5-F9 · a Final POR season writes to no retired namespace")
touched = _accounts_touched(db) | _accounts_touched(skunked)
retired_hits = sorted(
    a for a in touched
    if a in RETIRED_FOR_FINAL_POR_ACCOUNTS
    or any(a.startswith(p) for p in RETIRED_FOR_FINAL_POR_PREFIXES)
    or any(a.startswith(p) for p in RETIRED_FOR_FINAL_POR_ACCOUNTS
           if p.endswith(":")))
_assert("no ledger entry touches a retired account",
        retired_hits == [], str(retired_hits))
_assert("  · specifically not `reserve:{team}`",
        not any(a.startswith("reserve:") for a in touched))
_assert("  · not `championship:{league}`",
        not any(a.startswith("championship:") for a in touched),
        str(sorted(a for a in touched if a.startswith("championship"))))
_assert("  · not the bare `championship`", "championship" not in touched)
_assert("  · and not the season-less `skunk:{league}`",
        not any(a.startswith("skunk:") for a in touched))

import betting.pool_legacy_guard as plg  # noqa: E402

_assert("  · and the legacy Pool path refuses a Final POR season outright",
        any("ruleset_version" in m
            for m in plg.rev13_activation_markers(db, LEAGUE)),
        str(plg.rev13_activation_markers(db, LEAGUE)))
_assert("  · while a legacy season is still permitted onto it",
        plg.rev13_activation_markers(legacy_db, LEAGUE) == (),
        str(plg.rev13_activation_markers(legacy_db, LEAGUE)))


# ── F10 · exactly-once per pillar ───────────────────────────────────────────

print("\nWP5-F10 · minting is exactly-once per pillar")
before = pot_balances(db, league_id=LEAGUE, season=SEASON)
replay = mint_season_pots(db, league_id=LEAGUE, season=SEASON,
                          fantasy_football_cents=FF_POT, now=NOW)
db.commit()
after = pot_balances(db, league_id=LEAGUE, season=SEASON)

_assert("every pillar reports replayed", all(r.replayed for r in replay))
_assert("  · no pot grew",
        (before.fantasystakes_cents, before.fantasy_football_cents)
        == (after.fantasystakes_cents, after.fantasy_football_cents),
        f"{before.as_dict()} -> {after.as_dict()}")
_assert("  · the issuance tally did not grow",
        before.minted_cents == after.minted_cents)
_assert("  · exactly two mint events exist",
        db.execute(text("SELECT COUNT(*) FROM economy_event "
                        "WHERE event_type = :t"),
                   {"t": EVENT_CHAMPIONSHIP_POT_MINT}).scalar() == 2)
_assert("  · the two pillars did not collide on one key",
        db.execute(text("SELECT COUNT(DISTINCT event_key) FROM economy_event "
                        "WHERE event_type = :t"),
                   {"t": EVENT_CHAMPIONSHIP_POT_MINT}).scalar() == 2)
_assert("  · and the trial balance is still zero",
        ledger_module.trial_balance() == 0)


# ── F11/F12 · the legacy era, and the refusals ──────────────────────────────

print("\nWP5-F11 · a LEGACY season is unchanged and its retired paths still run")
old = _build(final_por=False)
_assert("Skunk still lands in `skunk:{league}`",
        skunk_pot_account(old, league_id=LEAGUE, season=SEASON)
        == f"skunk:{LEAGUE}")
assess_weekly_skunk(old, league_id=LEAGUE, week=1, contribution_cents=500,
                    now=NOW)
old.commit()
_assert("  · and really does", _bal(old, f"skunk:{LEAGUE}") == 500,
        str(_bal(old, f"skunk:{LEAGUE}")))
_assert("  · the season-scoped Points pot was never created",
        _bal(old, f"points_championship:{LEAGUE}:{SEASON}") == 0)

# A legacy reserve, swept exactly as it always was.
ledger_post([(f"season_issuance:{LEAGUE}:{SEASON}", -8_000),
             ("reserve:1", 8_000)],
            door="season_allocation", session=old)
old.commit()
sweep = sweep_championship_reserves(old, league_id=LEAGUE, now=NOW)
old.commit()
_assert("  · the reserve sweep still runs and still reports NOT retired",
        sweep.retired is False and sweep.total_cents == 8_000,
        f"retired={sweep.retired} total={sweep.total_cents}")
_assert("  · into `championship:{league}`, exactly as before",
        _bal(old, f"championship:{LEAGUE}") == 8_000,
        str(_bal(old, f"championship:{LEAGUE}")))

print("\nWP5-F12 · the retirements refuse or report, never silently no-op")
retired_sweep = sweep_championship_reserves(db, league_id=LEAGUE, now=NOW)
db.commit()
_assert("the reserve sweep reports itself retired",
        retired_sweep.retired is True and retired_sweep.total_cents == 0)
_assert("  · and recorded no RESERVE_SWEEP event",
        db.execute(text("SELECT COUNT(*) FROM economy_event "
                        "WHERE event_type = 'RESERVE_SWEEP'")).scalar() == 0)
_assert("  · legacy consolidation is retired too",
        consolidate_legacy_championship(db, league_id=LEAGUE, now=NOW) == 0)
_assert("  · and wrote nothing to `championship:{league}`",
        _bal(db, f"championship:{LEAGUE}") == 0)

from economy.fantasystakes_championship_allocation import (  # noqa: E402
    REASON_RETIRED_ERA, stage_allocation,
)

try:
    stage_allocation(db, league_id=LEAGUE, season=SEASON,
                     team_ids=(1, 2, 3, 4), contribution_cents=8_000)
    _assert("the per-GM FS contribution model refuses", False, "accepted")
except ValueError as exc:
    db.rollback()
    _assert("the per-GM FS contribution model refuses",
            REASON_RETIRED_ERA in str(exc), str(exc)[:90])

try:
    mint_pot(old, league_id=LEAGUE, season=SEASON,
             pillar=PILLAR_FANTASYSTAKES, amount_cents=1_000, now=NOW)
    _assert("  · and minting into a LEGACY season refuses", False, "accepted")
except ChampionshipPotError as exc:
    old.rollback()
    _assert("  · and minting into a LEGACY season refuses",
            exc.reason == "POT_WRONG_ERA", exc.reason)

from betting.shortfall_sweep import sweep_shortfall_for_team  # noqa: E402

sw = sweep_shortfall_for_team(1, LEAGUE, 1, db)
_assert("  · the dormant shortfall consequence is retired",
        sw.retired is True and sw.swept is False, f"retired={sw.retired}")
_assert("  · it wrote no ShortfallSweepRecord",
        db.execute(text("SELECT COUNT(*) FROM shortfall_sweep_records"))
        .scalar() == 0)
_assert("  · and opened no receivable",
        _bal(db, "receivable:1") == 0, str(_bal(db, "receivable:1")))


# ── F13 · the migration ─────────────────────────────────────────────────────

print("\nWP5-F13 · the SQLite migration path")
import migrations.add_ff_championship_pot as mig  # noqa: E402
from migrations.manifest import ACTIVE  # noqa: E402

entry = [m for m in ACTIVE if m.identifier == "0012_ff_championship_pot"]
_assert("the migration is registered in ACTIVE", len(entry) == 1)
_assert("  · and names the column it adds so `verify` can corroborate it",
        entry and entry[0].columns
        == (("league_season_economy_config", "ff_championship_pot_cents"),),
        str(entry[0].columns if entry else None))

probe = create_engine("sqlite://")
mig_prev_engine = mig.engine
try:
    # Build the table WITHOUT the new column, as a pre-WP-5 deployment has it.
    with probe.begin() as conn:
        conn.execute(text("""
            CREATE TABLE league_season_economy_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                league_id INTEGER NOT NULL,
                season INTEGER NOT NULL,
                weekly_bet_minimum_cents INTEGER NOT NULL,
                championship_contribution_cents INTEGER NOT NULL,
                skunk_fee_cents INTEGER NOT NULL,
                regular_season_week_count INTEGER,
                active_team_count INTEGER,
                start_week_used INTEGER,
                playoff_start_week_used INTEGER,
                frozen_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL
            )"""))
        conn.execute(text(
            "INSERT INTO league_season_economy_config "
            "(league_id, season, weekly_bet_minimum_cents, "
            " championship_contribution_cents, skunk_fee_cents, created_at) "
            "VALUES (9, 2025, 1000, 8000, 500, '2025-09-01')"))
    mig.engine = probe

    first = mig.upgrade()
    _assert("  · applies", any("added" in line for line in first), str(first))
    second = mig.upgrade()
    _assert("  · is idempotent",
            any("already exists" in line for line in second), str(second))

    with probe.begin() as conn:
        legacy_row = conn.execute(text(
            "SELECT championship_contribution_cents, ff_championship_pot_cents "
            "FROM league_season_economy_config WHERE league_id = 9")).fetchone()
        _assert("  · the pre-existing row keeps its per-GM contribution",
                legacy_row[0] == 8_000, str(legacy_row[0]))
        _assert("  · and its new column is NULL — unconfigured, not 0",
                legacy_row[1] is None, str(legacy_row[1]))

        conn.execute(text(
            "INSERT INTO league_season_economy_config "
            "(league_id, season, weekly_bet_minimum_cents, "
            " championship_contribution_cents, skunk_fee_cents, "
            " ff_championship_pot_cents, created_at) "
            "VALUES (10, 2026, 1000, 8000, 500, 0, '2026-09-01')"))
        _assert("  · 0 is storable", conn.execute(text(
            "SELECT ff_championship_pot_cents FROM "
            "league_season_economy_config WHERE league_id = 10")).scalar() == 0)
        try:
            conn.execute(text(
                "INSERT INTO league_season_economy_config "
                "(league_id, season, weekly_bet_minimum_cents, "
                " championship_contribution_cents, skunk_fee_cents, "
                " ff_championship_pot_cents, created_at) "
                "VALUES (11, 2026, 1000, 8000, 500, -100, '2026-09-01')"))
            _assert("  · a negative amount is refused by the DB", False,
                    "accepted")
        except Exception as exc:
            _assert("  · a negative amount is refused by the DB",
                    "CHECK" in str(exc).upper(), str(exc)[:70])
finally:
    mig.engine = mig_prev_engine

from economy.league_economy_config import (  # noqa: E402
    EconomyConfigError, MAX_FF_CHAMPIONSHIP_POT_CENTS,
    MIN_FF_CHAMPIONSHIP_POT_CENTS,
)

_assert("  · the validator admits 0 as the floor",
        MIN_FF_CHAMPIONSHIP_POT_CENTS == 0)
_assert("  · and caps it", MAX_FF_CHAMPIONSHIP_POT_CENTS == 1_000_000)


# -- F14 . the real activation, end to end -----------------------------------

print(chr(10) + "WP5-F14 " + chr(0x00b7) + " a REAL activation, end to end, on SQLite")
#
# THE PG SUITES THAT NORMALLY COVER `activate_season_allocation` CANNOT RUN HERE
# (no TEST_DATABASE_URL), and WP-5 changed that function's posting shape. F7
# reads the source; this runs it. A source assertion cannot tell you the ledger
# balanced, that the snapshot matches the posting, or that the pots really
# exist afterwards.
import config as _config  # noqa: E402
import db.schema as _dbs  # noqa: E402
from economy.season_allocation import activate_season_allocation  # noqa: E402

ACT_SEASON = _config.ALLOCATION_SEASON

act_engine = create_engine("sqlite://")
Base.metadata.create_all(act_engine)
ledger_module.engine = act_engine
ledger_module._LedgerBase.metadata.create_all(act_engine)
_dbs_prev_engine = _dbs.engine
_dbs.engine = act_engine
act = sessionmaker(bind=act_engine)()
try:
    act.add(League(id=LEAGUE, name="L", season=ACT_SEASON, start_week=1,
                   playoff_start_week=15))
    for t in (1, 2, 3, 4):
        act.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                     email=f"t{t}@example.test", provider_team_key=f"k{t}"))
        act.add(Wallet(team_id=t, balance=0.0))
    act.commit()

    result = activate_season_allocation(LEAGUE, act)

    _assert("activation stamps the season as Final POR",
            is_final_por(act, league_id=LEAGUE, season=ACT_SEASON))
    _assert("  " + chr(0x00b7) + " the advance is the Weekly Minimum Reserve alone",
            result.buyin_cents == result.min_reserve_cents,
            f"buyin={result.buyin_cents} min_reserve={result.min_reserve_cents}")
    _assert("  " + chr(0x00b7) + " and the per-GM Championship Reserve is 0",
            result.reserve_cents == 0, str(result.reserve_cents))
    _assert("  " + chr(0x00b7) + " NO `reserve:{team}` account was created at all",
            all(_bal(act, f"reserve:{t}") == 0 for t in (1, 2, 3, 4)),
            str({t: _bal(act, f"reserve:{t}") for t in (1, 2, 3, 4)}))
    _assert("  " + chr(0x00b7) + " every GM really holds their Weekly Minimum Reserve",
            all(_bal(act, f"min_reserve:{t}") == result.min_reserve_cents
                for t in (1, 2, 3, 4)),
            str({t: _bal(act, f"min_reserve:{t}") for t in (1, 2, 3, 4)}))

    from db.schema import SeasonAllocation  # noqa: E402

    snapshots = act.query(SeasonAllocation).filter(
        SeasonAllocation.league_id == LEAGUE).all()
    _assert("  " + chr(0x00b7) + " the snapshot agrees with the posting for every GM",
            all(r.reserve_cents == 0
                and r.buyin_cents == r.min_reserve_cents for r in snapshots),
            str([(r.team_id, r.buyin_cents, r.min_reserve_cents,
                  r.reserve_cents) for r in snapshots]))
    _assert("  " + chr(0x00b7) + " the documented invariant buyin == min_reserve + reserve holds",
            all(r.buyin_cents == r.min_reserve_cents + r.reserve_cents
                for r in snapshots))

    act_pots = pot_balances(act, league_id=LEAGUE, season=ACT_SEASON)
    _assert("  " + chr(0x00b7) + " the FantasyStakes Base Pot was minted by activation",
            act_pots.fantasystakes_cents == result.min_reserve_cents,
            f"pot={act_pots.fantasystakes_cents} base={result.min_reserve_cents}")
    _assert("  " + chr(0x00b7) + " which is one GM's Weekly Minimum Reserve, not the field's",
            act_pots.fantasystakes_cents * 4 != result.min_reserve_cents * 4 * 4
            and act_pots.fantasystakes_cents
            != result.min_reserve_cents * len(snapshots))
    _assert("  " + chr(0x00b7) + " the Fantasy Football pot minted at 0 (unconfigured)",
            act_pots.fantasy_football_cents == 0,
            str(act_pots.fantasy_football_cents))
    _assert("  " + chr(0x00b7) + " minting created no GM liability",
            no_gm_liability(act, league_id=LEAGUE, season=ACT_SEASON))
    _assert("  " + chr(0x00b7) + " the whole activation conserves",
            ledger_module.trial_balance() == 0,
            str(ledger_module.trial_balance()))

    settle = current_settle(act, team_id=1, league_id=LEAGUE, season=ACT_SEASON)
    _assert("  " + chr(0x00b7) + " a GM owes ONLY their Weekly Minimum advance",
            settle.obligations_cents == result.min_reserve_cents,
            f"{settle.obligations_cents} vs {result.min_reserve_cents}")
    _assert("  " + chr(0x00b7) + " and their Current Settle is exactly 0 at activation",
            settle.current_settle_cents == 0, str(settle.as_dict()))

    replay_result = activate_season_allocation(LEAGUE, act)
    _assert("  " + chr(0x00b7) + " a replay creates nothing", replay_result.created is False)
    _assert("  " + chr(0x00b7) + " and reports the SAME Model B shape",
            replay_result.reserve_cents == 0
            and replay_result.buyin_cents == result.buyin_cents,
            str(replay_result))
    _assert("  " + chr(0x00b7) + " the pots did not grow on replay",
            pot_balances(act, league_id=LEAGUE,
                         season=ACT_SEASON).minted_cents
            == act_pots.minted_cents)
finally:
    _dbs.engine = _dbs_prev_engine


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-5 league-level minted championship pots: all assertions passed")
