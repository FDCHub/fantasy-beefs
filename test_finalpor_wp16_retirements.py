#!/usr/bin/env python3
"""FINAL POR · WP-16 certification — the governed retirements are complete.

    F1  the retirement register is DATA, so nothing can be forgotten
    F2  a whole Final POR season, played end to end, touches NO retired account
    F3  every retired CALLABLE refuses or reports itself retired
    F4  every retirement is ERA-SCOPED — the legacy era still runs each one
    F5  no retirement was completed by DELETION
    F6  the same season conserves, and every posting is attributable

WHY A SWEEP AFTER TEN PACKAGES EACH RETIRED THEIR OWN PREDECESSOR. Each package
proved its own retirement in isolation, against a fixture built for it. That
leaves one thing unproven: that a season which actually PLAYS — activation,
release, spend, week close, Skunk, correction, Top-Off, void, three
championships — never reaches any of them. F2 plays that season and then reads
every account it touched back out of the ledger. An isolated refusal cannot show
that; only the whole run can.

WHY F5 EXISTS. The cheap way to pass F2 and F3 is to delete the retired code.
That would break every legacy season on every deployment, whose money really was
posted through those paths and is still read back through them. Retirement here
means UNREACHABLE FOR THIS ERA, never absent.
"""
from __future__ import annotations

import inspect
import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import economy.fantasystakes_championship_settlement  # noqa: F401
import ledger.ledger as ledger_module
from db.schema import (
    Base, Bet, League, LeagueSeasonEconomyConfig, Matchup, SeasonAllocation,
    Team, Wallet,
)
from economy.championship_pots import mint_season_pots
from economy.economy_events import (
    RETIRED_FOR_FINAL_POR_ACCOUNTS, RETIRED_FOR_FINAL_POR_PREFIXES,
)
from economy.fantasystakes_championship_final import settle as settle_fs
from economy.skunk import assess_weekly_skunk
from economy.skunk_correction import correct_weekly_skunk
from economy.weekly_minimum import expire_week, release_week
from ledger.ledger import (
    APPROVED_BAB_TOPOFF_DOOR, SEASON_ALLOCATION_DOOR, post as ledger_post,
)
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
WEEKS = 3                 # weeks 1-2 regular, 3 postseason
WEEKLY = 1_000
FEE = 500
TEAMS = (1, 2, 3, 4)


# ── F1 · the retirement register ────────────────────────────────────────────
#
# ENUMERATED AS DATA, not as a list of things a reader has to remember. Every
# row names what was retired, which package retired it, and how the retirement
# is expressed. Adding an eleventh retirement without adding a row here is a
# visible omission rather than a silent one.

RETIRED_ACCOUNTS = {
    "expired_min:":       "WP-4  unspent Minimum now forfeits to the FS Pot",
    "reserve:":           "WP-5  no per-GM Championship Reserve is advanced",
    "championship:":      "WP-5  replaced by three season-scoped pots",
    "championship":       "WP-5  the bare pre-league-scoping account",
    "skunk:":             "WP-5  replaced by points_championship:{L}:{S}",
}

RETIRED_CALLABLES = {
    "reconcile_expired_minimum":  "WP-4  returns retired=True, posts nothing",
    "sweep_shortfall_for_team":   "WP-5  returns retired=True, writes no record",
    "sweep_championship_reserves": "WP-5  returns retired=True, posts nothing",
    "consolidate_legacy_championship": "WP-5  returns 0, posts nothing",
    "stage_allocation":           "WP-5  raises FS_..._RETIRED_ERA",
    "freeze_fantasystakes_championship": "WP-8  raises FS_..._FREEZE_RETIRED",
    "require_championship_frozen_for_postseason":
        "WP-8  returns immediately; there is no boundary to gate",
}

print("\nWP16-F1 · the retirement register is data")
_assert("the account register is shared with the code, not restated here",
        set(RETIRED_FOR_FINAL_POR_PREFIXES) <= set(RETIRED_ACCOUNTS)
        and set(RETIRED_FOR_FINAL_POR_ACCOUNTS) <= set(RETIRED_ACCOUNTS),
        f"code says {RETIRED_FOR_FINAL_POR_PREFIXES} "
        f"+ {RETIRED_FOR_FINAL_POR_ACCOUNTS}")
_assert("  · every retired account names the package that retired it",
        all(v.startswith("WP-") for v in RETIRED_ACCOUNTS.values()))
_assert("  · every retired callable names how its retirement is expressed",
        all(v.startswith("WP-") for v in RETIRED_CALLABLES.values()))
_assert("  · and there are seven of them", len(RETIRED_CALLABLES) == 7,
        str(len(RETIRED_CALLABLES)))


def _build(*, final_por: bool = True):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=LEAGUE, name="L", season=SEASON, start_week=1,
                  playoff_start_week=WEEKS, provider="yahoo"))
    for t in TEAMS:
        db.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider="yahoo",
                    provider_team_key=f"k{t}"))
        db.add(Wallet(team_id=t, balance=0.0))
    mid = 0
    for week in range(1, WEEKS + 1):
        mid += 1
        db.add(Matchup(id=mid, league_id=LEAGUE, week=week, home_team_id=1,
                       away_team_id=2, home_score=100.0, away_score=98.0,
                       winner_team_id=1, finalized_at=NAIVE))
        mid += 1
        db.add(Matchup(id=mid, league_id=LEAGUE, week=week, home_team_id=3,
                       away_team_id=4, home_score=60.0, away_score=120.0,
                       winner_team_id=4, finalized_at=NAIVE))
    db.add(LeagueSeasonEconomyConfig(
        league_id=LEAGUE, season=SEASON,
        weekly_bet_minimum_cents=WEEKLY,
        championship_contribution_cents=8_000,
        skunk_fee_cents=FEE,
        ff_championship_pot_cents=2_000,
        regular_season_week_count=WEEKS - 1,
        active_team_count=len(TEAMS),
        start_week_used=1, playoff_start_week_used=WEEKS,
        frozen_at=NAIVE))
    db.commit()
    if final_por:
        stamp_ruleset(db, league_id=LEAGUE, season=SEASON,
                      version=RULESET_FINAL_POR)
    reserve_total = WEEKLY * (WEEKS - 1)
    for t in TEAMS:
        # THE FINAL POR OPENING ALLOCATION, in the shape WP-5 posts it.
        legs = [(f"season_issuance:{LEAGUE}:{SEASON}", -reserve_total),
                (f"min_reserve:{t}", reserve_total)]
        if not final_por:
            legs = [(f"season_issuance:{LEAGUE}:{SEASON}",
                     -(reserve_total + 8_000)),
                    (f"min_reserve:{t}", reserve_total),
                    (f"reserve:{t}", 8_000)]
        ledger_post(legs, door=SEASON_ALLOCATION_DOOR, session=db)
        db.add(SeasonAllocation(
            league_id=LEAGUE, team_id=t, season=SEASON,
            buyin_cents=reserve_total if final_por else reserve_total + 8_000,
            min_reserve_cents=reserve_total,
            reserve_cents=0 if final_por else 8_000))
    db.commit()
    return db


def _bal(db, account: str) -> int:
    return ledger_module._balance_of_in_session(db, account)


def _accounts_touched(db) -> set[str]:
    return {r[0] for r in db.execute(text(
        "SELECT DISTINCT account FROM ledger_entries")).fetchall()}


def _play_a_season(db):
    """Activation is already done. Play the rest of it, for real."""
    mint_season_pots(db, league_id=LEAGUE, season=SEASON,
                     fantasy_football_cents=2_000, now=NOW)
    db.commit()

    for week in (1, 2):
        release_week(db, league_id=LEAGUE, week=week, now=NOW)
        db.commit()
        # A partial spend, so the week close has a real remainder to sweep.
        ledger_post([(f"min:1:{week}", -400), (f"pool:{LEAGUE}", 400)],
                    door="pool_weekly_collection", session=db)
        db.commit()
        assess_weekly_skunk(db, league_id=LEAGUE, week=week, now=NOW)
        db.commit()
        expire_week(db, league_id=LEAGUE, week=week, now=NOW)
        db.commit()

    # A WP-12 correction on week 1.
    for m in db.query(Matchup).filter(Matchup.week == 1).all():
        if m.home_team_id == 1:
            m.home_score, m.away_score, m.winner_team_id = 190.0, 100.0, 1
        else:
            m.home_score, m.away_score, m.winner_team_id = 118.0, 120.0, 4
    db.commit()
    correct_weekly_skunk(db, league_id=LEAGUE, week=1, now=NOW)
    db.commit()

    # A WP-6 approved Top-Off, three legs.
    ledger_post([(f"bab_issuance:{LEAGUE}:{SEASON}", -4_000),
                 ("wallet:1", 2_000),
                 (f"fantasystakes_championship:{LEAGUE}:{SEASON}", 2_000)],
                door=APPROVED_BAB_TOPOFF_DOOR, session=db)
    db.commit()

    # A terminal Prop Pool remainder, routed by WP-5's resolver.
    from economy.championship_pots import terminal_pool_destination

    ledger_post([(f"pool:{LEAGUE}", -800),
                 (terminal_pool_destination(db, league_id=LEAGUE,
                                            season=SEASON), 800)],
                door="pool_rollover_expiry", session=db)
    db.commit()

    # And the FantasyStakes Championship pays.
    settle_fs(db, league_id=LEAGUE, season=SEASON, now=NOW)
    db.commit()


# ── F2 · a whole season touches no retired account ──────────────────────────

print("\nWP16-F2 · a whole Final POR season touches NO retired account")
db = _build()
_play_a_season(db)
touched = sorted(_accounts_touched(db))

_assert("the season really was played — many accounts were touched",
        len(touched) >= 12, f"{len(touched)}: {touched}")
for prefix, why in sorted(RETIRED_ACCOUNTS.items()):
    if prefix.endswith(":"):
        hits = [a for a in touched if a.startswith(prefix)]
    else:
        hits = [a for a in touched if a == prefix]
    _assert(f"  · nothing touched `{prefix}` — {why}", not hits, str(hits))

_assert("  · and the accounts it DID touch are all governed ones",
        all(a.split(":")[0] in {
            "season_issuance", "min_reserve", "min", "wallet", "pool",
            "receivable", "escrow", "bab_issuance", "championship_issuance",
            "fantasystakes_championship", "points_championship",
            "ff_championship"} for a in touched),
        str(touched))
_assert("  · the FantasyStakes pot really was funded and paid",
        _bal(db, f"fantasystakes_championship:{LEAGUE}:{SEASON}") == 0
        and sum(_bal(db, f"wallet:{t}") for t in TEAMS) > 0)
_assert("  · the Points pot holds the Skunk actually assessed",
        _bal(db, f"points_championship:{LEAGUE}:{SEASON}") == FEE * 2,
        str(_bal(db, f"points_championship:{LEAGUE}:{SEASON}")))


# ── F3 · every retired callable refuses or reports itself retired ───────────

print("\nWP16-F3 · every retired callable refuses or reports itself retired")
from betting.shortfall_sweep import sweep_shortfall_for_team  # noqa: E402
from economy.championship_scoring_gate import (  # noqa: E402
    require_championship_frozen_for_postseason,
)
from economy.fantasystakes_championship_allocation import (  # noqa: E402
    stage_allocation,
)
from economy.season_reconciliation import (  # noqa: E402
    consolidate_legacy_championship, reconcile_expired_minimum,
    sweep_championship_reserves,
)
from reports.championship_read_model import (  # noqa: E402
    FantasyStakesChampionshipError, freeze_fantasystakes_championship,
)

expired = reconcile_expired_minimum(db, league_id=LEAGUE, now=NOW)
_assert("reconcile_expired_minimum reports retired and returns 0",
        expired.retired is True and expired.total_cents == 0)
_assert("  · and found nothing stranded", expired.stranded == ())

reserve_sweep = sweep_championship_reserves(db, league_id=LEAGUE, now=NOW)
_assert("sweep_championship_reserves reports retired",
        reserve_sweep.retired is True and reserve_sweep.total_cents == 0)

_assert("consolidate_legacy_championship returns 0 and posts nothing",
        consolidate_legacy_championship(db, league_id=LEAGUE, now=NOW) == 0)

sweep = sweep_shortfall_for_team(1, LEAGUE, 1, db)
_assert("sweep_shortfall_for_team reports retired and sweeps nothing",
        sweep.retired is True and sweep.swept is False)
_assert("  · and wrote no ShortfallSweepRecord",
        db.execute(text("SELECT COUNT(*) FROM shortfall_sweep_records"))
        .scalar() == 0)

try:
    stage_allocation(db, league_id=LEAGUE, season=SEASON, team_ids=TEAMS,
                     contribution_cents=8_000)
    _assert("stage_allocation refuses the per-GM contribution", False,
            "accepted")
except ValueError as exc:
    db.rollback()
    _assert("stage_allocation refuses the per-GM contribution",
            "RETIRED_ERA" in str(exc), str(exc)[:70])

try:
    freeze_fantasystakes_championship(db, league_id=LEAGUE, now=NOW)
    _assert("  · the boundary freeze refuses", False, "accepted")
except FantasyStakesChampionshipError as exc:
    db.rollback()
    _assert("  · the boundary freeze refuses",
            exc.reason == "FS_CHAMPIONSHIP_FREEZE_RETIRED", exc.reason)

_assert("  · the postseason scoring gate passes with no freeze",
        require_championship_frozen_for_postseason(
            db, league_id=LEAGUE, week=WEEKS) is None)
_assert("  · and still no freeze marker exists",
        db.execute(text("SELECT COUNT(*) FROM "
                        "fantasystakes_championship_freeze")).scalar() == 0)

after = sorted(_accounts_touched(db))
_assert("  · calling every retired path moved NOTHING",
        after == touched, str(set(after) ^ set(touched)))


# ── F4 · era-scoped, not global ────────────────────────────────────────────

print("\nWP16-F4 · every retirement is ERA-SCOPED — the legacy era still runs")
old = _build(final_por=False)
release_week(old, league_id=LEAGUE, week=1, now=NOW)
old.commit()
expire_week(old, league_id=LEAGUE, week=1, now=NOW)
old.commit()
assess_weekly_skunk(old, league_id=LEAGUE, week=1, now=NOW)
old.commit()

_assert("a legacy week close still writes `expired_min:`",
        _bal(old, "expired_min:1") == WEEKLY, str(_bal(old, "expired_min:1")))
_assert("  · legacy Skunk still lands in `skunk:{league}`",
        _bal(old, f"skunk:{LEAGUE}") == FEE, str(_bal(old, f"skunk:{LEAGUE}")))
_assert("  · a legacy activation still advanced `reserve:{team}`",
        _bal(old, "reserve:1") == 8_000, str(_bal(old, "reserve:1")))

legacy_sweep = sweep_championship_reserves(old, league_id=LEAGUE, now=NOW)
old.commit()
_assert("  · the reserve sweep still runs and reports NOT retired",
        legacy_sweep.retired is False
        and legacy_sweep.total_cents == 8_000 * len(TEAMS),
        f"retired={legacy_sweep.retired} total={legacy_sweep.total_cents}")
_assert("  · into `championship:{league}`",
        _bal(old, f"championship:{LEAGUE}") == 8_000 * len(TEAMS),
        str(_bal(old, f"championship:{LEAGUE}")))

legacy_return = reconcile_expired_minimum(old, league_id=LEAGUE, now=NOW)
old.commit()
_assert("  · the expired-Minimum return still runs and reports NOT retired",
        legacy_return.retired is False and legacy_return.total_cents > 0,
        f"retired={legacy_return.retired} total={legacy_return.total_cents}")
_assert("  · crediting the GM's own Wallet",
        _bal(old, "wallet:1") == WEEKLY, str(_bal(old, "wallet:1")))
_assert("  · and the legacy shortfall sweep is NOT retired",
        sweep_shortfall_for_team(1, LEAGUE, 2, old).retired is False)


# ── F5 · nothing was retired by deletion ───────────────────────────────────

print("\nWP16-F5 · no retirement was completed by DELETION")
for name, fn in (("reconcile_expired_minimum", reconcile_expired_minimum),
                 ("sweep_championship_reserves", sweep_championship_reserves),
                 ("consolidate_legacy_championship",
                  consolidate_legacy_championship),
                 ("sweep_shortfall_for_team", sweep_shortfall_for_team),
                 ("stage_allocation", stage_allocation),
                 ("freeze_fantasystakes_championship",
                  freeze_fantasystakes_championship),
                 ("require_championship_frozen_for_postseason",
                  require_championship_frozen_for_postseason)):
    _assert(f"  · `{name}` still exists and is callable", callable(fn))
    _assert(f"  · `{name}` consults the era gate",
            "is_final_por" in inspect.getsource(
                sys.modules[fn.__module__]),
            f"{fn.__module__} has no era gate")

from economy.economy_events import expired_min_account  # noqa: E402
from reports.championship_read_model import (  # noqa: E402
    REASON_POSTSEASON_CONTAMINATED,
)
from reports.grand_champion import POINTS_BY_PLACE  # noqa: E402

_assert("  · `expired_min_account` still resolves for a legacy reader",
        expired_min_account(7) == "expired_min:7")
_assert("  · REASON_POSTSEASON_CONTAMINATED still exists, now unreachable",
        REASON_POSTSEASON_CONTAMINATED
        == "FS_CHAMPIONSHIP_POSTSEASON_ALREADY_ACTIVE")
_assert("  · and the retired 3/2/1 table survives for legacy seasons",
        POINTS_BY_PLACE == {1: 3, 2: 2, 3: 1}, str(POINTS_BY_PLACE))


# ── F6 · the played season conserves ───────────────────────────────────────

print("\nWP16-F6 · the played season conserves, and every posting is attributable")
ledger_module.engine = db.get_bind()
_assert("the global trial balance is zero",
        ledger_module.trial_balance() == 0,
        str(ledger_module.trial_balance()))

doors = {r[0] for r in db.execute(text(
    "SELECT DISTINCT door FROM ledger_entries")).fetchall()}
_assert("  · every door used is a named, governed one",
        all(d in {
            SEASON_ALLOCATION_DOOR, APPROVED_BAB_TOPOFF_DOOR,
            "championship_pot_mint", "weekly_minimum_release",
            "weekly_minimum_sweep", "skunk_assessment",
            "skunk_correction_reversal", "skunk_correction_repost",
            "pool_weekly_collection", "pool_rollover_expiry",
            "fantasystakes_championship_final"} for d in doors),
        str(sorted(doors)))
_assert("  · no posting was made under the retired expiry door",
        "weekly_minimum_expiry" not in doors, str(sorted(doors)))
_assert("  · nor the retired shortfall-sweep door",
        "shortfall_sweep" not in doors)
_assert("  · nor the retired reserve sweep",
        "championship_reserve_sweep" not in doors)

unbalanced = db.execute(text(
    "SELECT posting_id, SUM(amount_cents) FROM ledger_entries "
    "GROUP BY posting_id HAVING SUM(amount_cents) != 0")).fetchall()
_assert("  · and every individual posting balances", not unbalanced,
        str(unbalanced))


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-16 governed retirements: all assertions passed")
