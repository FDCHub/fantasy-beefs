#!/usr/bin/env python3
"""FINAL POR · WP-4 certification — unused Weekly Minimum → FS Championship Pot.

    F1   full Weekly Minimum consumed        -> sweep 0
    F2   partial Minimum consumed            -> exact remainder swept
    F3   zero-spend week                     -> whole Minimum swept
    F4   the sweep posting conserves
    F5   no Wallet is credited, by any leg, under any door
    F6   no Skunk and no receivable is created
    F7   the FantasyStakes Score moves by exactly 0
    F8   Current Settle loses the asset EXACTLY ONCE
    F9   replay is idempotent
    F10  a LEGACY season behaves exactly as it always did
    F11  the retired paths are retired, and only for the Final POR era

WHY F10 IS THE LOAD-BEARING ONE. Every legacy season on any deployment closed
its weeks to `expired_min:` and returned that money to Wallet at season close.
Those Wallets were real, the balances were reported, and some were paid out. If
the era gate ever admits the sweep there, historical money moves retroactively.
So F10 runs the SAME fixture through the SAME calls under the legacy ruleset and
requires the old destination, the old account, the old event type and the old
season-close return — not merely "something different happened".

WHY F8 IS NOT A RESTATEMENT OF F4. F4 says the posting balances, which any
balanced posting does. F8 says the GM's settlement position fell by the swept
amount and by no more — that the forfeiture is not ALSO charged as a receivable,
not ALSO deducted from Wallet, and not counted twice through two asset fields
that both read the same cents.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import ledger.ledger as ledger_module
from db.schema import Base, Bet, League, Matchup, Team, Wallet
from economy.current_settle import current_settle
from economy.economy_events import (
    DOOR_WEEKLY_MINIMUM_EXPIRY,
    DOOR_WEEKLY_MINIMUM_SWEEP,
    EVENT_WEEKLY_MINIMUM_EXPIRY,
    EVENT_WEEKLY_MINIMUM_SWEEP,
    fantasystakes_championship_account,
)
from economy.season_reconciliation import reconcile_expired_minimum
from economy.spend_sourcing import plan_spend_split
from economy.weekly_minimum import (
    DESTINATION_EXPIRED_MIN,
    DESTINATION_FS_CHAMPIONSHIP_POT,
    expire_week,
    release_week,
)
from ledger.ledger import SEASON_ALLOCATION_DOOR, post as ledger_post
from reports.standings_read_model import league_standings
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
WEEKS = 14                 # regular-season weeks; playoffs start at 15
WEEKLY = 1_000             # 10 VC per GM per week
TEAMS = (1, 2, 3, 4)
POT = fantasystakes_championship_account(LEAGUE, SEASON)


def _build(final_por: bool):
    """A four-GM league funded exactly as `season_allocation` funds one.

    `min_reserve:{team}` is advanced from `season_issuance:` under the canonical
    Season-Opening Allocation door — the same door and the same namespace
    production uses — so the funded-balance guard is exercised here exactly as
    it is in production rather than bypassed by a hand-written balance.
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module.SessionLocal = sessionmaker(bind=engine)
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=LEAGUE, name="L", season=SEASON, start_week=1,
                  playoff_start_week=15))
    for t in TEAMS:
        db.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider_team_key=f"k{t}"))
        db.add(Wallet(team_id=t, balance=0.0))
    db.add(Matchup(id=1, league_id=LEAGUE, week=1, home_team_id=1,
                   away_team_id=2, home_score=100.0, away_score=98.0,
                   winner_team_id=1, finalized_at=NAIVE))
    db.add(Matchup(id=2, league_id=LEAGUE, week=1, home_team_id=3,
                   away_team_id=4, home_score=60.0, away_score=120.0,
                   winner_team_id=4, finalized_at=NAIVE))
    db.commit()

    if final_por:
        stamp_ruleset(db, league_id=LEAGUE, season=SEASON,
                      version=RULESET_FINAL_POR)

    for t in TEAMS:
        ledger_post([(f"season_issuance:{LEAGUE}:{SEASON}", -WEEKLY * WEEKS),
                     (f"min_reserve:{t}", WEEKLY * WEEKS)],
                    door=SEASON_ALLOCATION_DOOR, session=db)
    db.commit()
    return db


def _spend(db, team_id: int, week: int, cents: int) -> int:
    """Spend through the real min-first splitter into a real wager escrow.

    A REAL `Bet` ROW, NOT A BARE `escrow:N` STRING. `current_settle` refuses
    escrow it cannot attribute to an owner from posted state, and F8 asks it for
    a settle figure — so the fixture has to give the escrow the same provenance
    production gives it, or F8 would be measuring a fixture shortcut."""
    wallet = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    bet = Bet(matchup_id=1, wallet_id=wallet.id, amount=cents / 100.0,
              picked_team_id=team_id, status="pending", placed_at=NAIVE)
    db.add(bet)
    db.flush()

    legs = plan_spend_split(db, team_id, week, cents)
    ledger_post([(acct, -amt) for acct, amt in legs]
                + [(f"escrow:{bet.id}", cents)],
                door="wager_placed", session=db)
    db.flush()
    return bet.id


def _bal(db, account: str) -> int:
    return ledger_module._balance_of_in_session(db, account)


def _events(db, event_type: str) -> list[tuple]:
    return list(db.execute(text(
        "SELECT team_id, week, amount_cents FROM economy_event "
        "WHERE event_type = :t ORDER BY week, team_id"),
        {"t": event_type}).fetchall())


def _legs_under(db, door: str) -> list[tuple]:
    return list(db.execute(text(
        "SELECT account, amount_cents FROM ledger_entries "
        "WHERE door = :d ORDER BY account"), {"d": door}).fetchall())


# ── F1-F3 · the three consumption shapes ─────────────────────────────────────

print("\nWP4-F1/F2/F3 · what is swept is exactly what was left")
db = _build(final_por=True)
release_week(db, league_id=LEAGUE, week=1, now=NOW)
db.commit()

_assert("each GM starts week 1 holding the whole Weekly Minimum",
        all(_bal(db, f"min:{t}:1") == WEEKLY for t in TEAMS),
        str({t: _bal(db, f"min:{t}:1") for t in TEAMS}))

bet1 = _spend(db, 1, 1, WEEKLY)   # F1 — consumed in full
bet2 = _spend(db, 2, 1, 400)      # F2 — partial, 600 left
_spend(db, 3, 1, 999)             # F2 — partial, 1 cent left
#      team 4 spends nothing      # F3 — whole Minimum unspent
db.commit()

pot_before = _bal(db, POT)
results = expire_week(db, league_id=LEAGUE, week=1, now=NOW)
db.commit()
swept = {r.team_id: r.expired_cents for r in results}

_assert("F1  a fully consumed Minimum sweeps 0", swept[1] == 0, str(swept[1]))
_assert("F2  a 400-spent Minimum sweeps exactly 600",
        swept[2] == 600, str(swept[2]))
_assert("F2  a 999-spent Minimum sweeps exactly 1",
        swept[3] == 1, str(swept[3]))
_assert("F3  a zero-spend week sweeps the whole Minimum",
        swept[4] == WEEKLY, str(swept[4]))
_assert("  · every result names the pot as the destination",
        all(r.destination == DESTINATION_FS_CHAMPIONSHIP_POT for r in results))
_assert("  · and `swept_to_championship` agrees",
        all(r.swept_to_championship for r in results))

expected_pot = 0 + 600 + 1 + WEEKLY
_assert("the pot grew by exactly the sum of the four remainders",
        _bal(db, POT) - pot_before == expected_pot,
        f"{pot_before} -> {_bal(db, POT)}, expected +{expected_pot}")
_assert("  · and every `min:{team}:1` is now empty",
        all(_bal(db, f"min:{t}:1") == 0 for t in TEAMS),
        str({t: _bal(db, f"min:{t}:1") for t in TEAMS}))
_assert("  · escrow was untouched by the sweep — committed money was already gone",
        _bal(db, f"escrow:{bet1}") == WEEKLY
        and _bal(db, f"escrow:{bet2}") == 400,
        f"{_bal(db, f'escrow:{bet1}')} / {_bal(db, f'escrow:{bet2}')}")


# ── F4 · conservation ────────────────────────────────────────────────────────

print("\nWP4-F4 · the sweep posting conserves")
sweep_legs = _legs_under(db, DOOR_WEEKLY_MINIMUM_SWEEP)
_assert("the sweep door's legs sum to zero",
        sum(a for _, a in sweep_legs) == 0, str(sum(a for _, a in sweep_legs)))
_assert("  · the global trial balance is zero",
        ledger_module.trial_balance() == 0,
        str(ledger_module.trial_balance()))
_assert("  · the only accounts the door touched are min: and the pot",
        {acct.split(":")[0] for acct, _ in sweep_legs}
        == {"min", "fantasystakes_championship"},
        str(sorted({a for a, _ in sweep_legs})))
_assert("  · a zero remainder posted NO leg at all (team 1 is absent)",
        not any(acct == "min:1:1" for acct, _ in sweep_legs),
        str(sorted(a for a, _ in sweep_legs)))
_assert("  · but team 1's week still recorded an event, so a retry is a no-op",
        (1, 1, 0) in [tuple(r) for r in _events(db, EVENT_WEEKLY_MINIMUM_SWEEP)],
        str(_events(db, EVENT_WEEKLY_MINIMUM_SWEEP)))
_assert("  · the pot is season-scoped, not league-scoped",
        POT.endswith(f":{SEASON}") and _bal(db, f"championship:{LEAGUE}") == 0,
        POT)


# ── F5/F6 · what the sweep must NOT do ───────────────────────────────────────

print("\nWP4-F5 · no Wallet is credited")
_assert("no wallet: leg exists under the sweep door",
        not any(acct.startswith("wallet:") for acct, _ in sweep_legs),
        str(sorted(a for a, _ in sweep_legs)))
_assert("  · and every GM's Wallet is still exactly 0",
        all(_bal(db, f"wallet:{t}") == 0 for t in TEAMS),
        str({t: _bal(db, f"wallet:{t}") for t in TEAMS}))

print("\nWP4-F6 · no expired_min:, no receivable, no second penalty")
_assert("nothing was written to expired_min: for any GM",
        all(_bal(db, f"expired_min:{t}") == 0 for t in TEAMS),
        str({t: _bal(db, f"expired_min:{t}") for t in TEAMS}))
_assert("  · no EXPIRY event was recorded at all",
        _events(db, EVENT_WEEKLY_MINIMUM_EXPIRY) == [],
        str(_events(db, EVENT_WEEKLY_MINIMUM_EXPIRY)))
_assert("  · no leg was posted under the legacy expiry door",
        _legs_under(db, DOOR_WEEKLY_MINIMUM_EXPIRY) == [])
_assert("  · no receivable: was created by the sweep",
        all(_bal(db, f"receivable:{t}") == 0 for t in TEAMS),
        str({t: _bal(db, f"receivable:{t}") for t in TEAMS}))
_assert("  · and no Skunk was assessed by closing the week",
        _bal(db, f"skunk:{LEAGUE}") == 0, str(_bal(db, f"skunk:{LEAGUE}")))


# ── F7 · the FantasyStakes Score is untouched ────────────────────────────────

print("\nWP4-F7 · the FantasyStakes Score moves by exactly 0")
scores = {r.team_id: r.net_cents for r in league_standings(db, league_id=LEAGUE).rows}
_assert("team 4 forfeited the whole Minimum and its Score is still 0",
        scores[4] == 0, str(scores[4]))
_assert("  · no GM's Score differs from any other's",
        len(set(scores.values())) == 1, str(scores))
_assert("  · and no GM carries a Skunk figure from the sweep",
        all(r.skunk_fees_cents == 0
            for r in league_standings(db, league_id=LEAGUE).rows))

from reports.standings_read_model import POOL_DOORS, VERSUS_DOORS  # noqa: E402

_assert("the sweep door is in NEITHER scoring door group, by name",
        DOOR_WEEKLY_MINIMUM_SWEEP not in VERSUS_DOORS
        and DOOR_WEEKLY_MINIMUM_SWEEP not in POOL_DOORS)

from economy.skunk import SKUNK_SCORING_EVENT_TYPES  # noqa: E402

_assert("  · and the sweep event is not a Skunk-scoring event",
        EVENT_WEEKLY_MINIMUM_SWEEP not in SKUNK_SCORING_EVENT_TYPES)


# ── F8 · Current Settle loses it exactly once ────────────────────────────────

print("\nWP4-F8 · Current Settle reflects the lost asset exactly once")
db2 = _build(final_por=True)
release_week(db2, league_id=LEAGUE, week=1, now=NOW)
db2.commit()
_spend(db2, 2, 1, 400)
db2.commit()

before = current_settle(db2, team_id=2, league_id=LEAGUE, season=SEASON)
expire_week(db2, league_id=LEAGUE, week=1, now=NOW)
db2.commit()
after = current_settle(db2, team_id=2, league_id=LEAGUE, season=SEASON)

_assert("the GM's settle position falls by exactly the 600 swept",
        before.current_settle_cents - after.current_settle_cents == 600,
        f"{before.current_settle_cents} -> {after.current_settle_cents}")
_assert("  · the fall is entirely in the live Weekly Minimum asset",
        before.weekly_min_live_cents - after.weekly_min_live_cents == 600,
        f"{before.weekly_min_live_cents} -> {after.weekly_min_live_cents}")
_assert("  · expired_min: did NOT absorb it (that would be a second home)",
        after.expired_min_cents == 0, str(after.expired_min_cents))
_assert("  · Wallet did not change", before.wallet_cents == after.wallet_cents)
_assert("  · the obligation side did not change — no new debt was created",
        before.obligations_cents == after.obligations_cents,
        f"{before.obligations_cents} -> {after.obligations_cents}")
_assert("  · assets fell by 600 and by no more",
        before.assets_cents - after.assets_cents == 600,
        f"{before.assets_cents} -> {after.assets_cents}")
_assert("  · a GM who spent nothing loses their whole Minimum, once",
        (current_settle(db2, team_id=4, league_id=LEAGUE,
                        season=SEASON).weekly_min_live_cents == 0))


# ── F9 · replay ──────────────────────────────────────────────────────────────

print("\nWP4-F9 · replay is idempotent")
pot_after_first = _bal(db2, POT)
settle_after_first = current_settle(db2, team_id=2, league_id=LEAGUE,
                                    season=SEASON).current_settle_cents
replay = expire_week(db2, league_id=LEAGUE, week=1, now=NOW)
db2.commit()

_assert("every team reports replayed", all(r.replayed for r in replay))
_assert("  · the replay still names the pot as the destination",
        all(r.destination == DESTINATION_FS_CHAMPIONSHIP_POT for r in replay))
_assert("  · the pot did not grow",
        _bal(db2, POT) == pot_after_first,
        f"{pot_after_first} -> {_bal(db2, POT)}")
_assert("  · Current Settle did not fall a second time",
        current_settle(db2, team_id=2, league_id=LEAGUE,
                       season=SEASON).current_settle_cents == settle_after_first)
_assert("  · exactly one sweep event exists per team",
        len(_events(db2, EVENT_WEEKLY_MINIMUM_SWEEP)) == len(TEAMS),
        str(len(_events(db2, EVENT_WEEKLY_MINIMUM_SWEEP))))
_assert("  · and the trial balance is still zero",
        ledger_module.trial_balance() == 0)


# ── F10 · the legacy era is byte-for-byte unchanged ──────────────────────────

print("\nWP4-F10 · a LEGACY season behaves exactly as it always did")
old = _build(final_por=False)
release_week(old, league_id=LEAGUE, week=1, now=NOW)
old.commit()
_spend(old, 2, 1, 400)
old.commit()

legacy_before = current_settle(old, team_id=2, league_id=LEAGUE, season=SEASON)
legacy_results = expire_week(old, league_id=LEAGUE, week=1, now=NOW)
old.commit()
legacy_after = current_settle(old, team_id=2, league_id=LEAGUE, season=SEASON)

_assert("the remainder went to expired_min:, not the pot",
        _bal(old, "expired_min:2") == 600 and _bal(old, POT) == 0,
        f"expired_min={_bal(old, 'expired_min:2')} pot={_bal(old, POT)}")
_assert("  · every result names the legacy destination",
        all(r.destination == DESTINATION_EXPIRED_MIN for r in legacy_results))
_assert("  · the legacy EXPIRY event type was recorded, not the sweep",
        len(_events(old, EVENT_WEEKLY_MINIMUM_EXPIRY)) == len(TEAMS)
        and _events(old, EVENT_WEEKLY_MINIMUM_SWEEP) == [])
_assert("  · the legacy expiry door was used, not the sweep door",
        _legs_under(old, DOOR_WEEKLY_MINIMUM_EXPIRY) != []
        and _legs_under(old, DOOR_WEEKLY_MINIMUM_SWEEP) == [])
_assert("  · Current Settle moved by EXACTLY ZERO, as it always did",
        legacy_before.current_settle_cents == legacy_after.current_settle_cents,
        f"{legacy_before.current_settle_cents} -> {legacy_after.current_settle_cents}")
_assert("  · the FantasyStakes Championship Pot was never created",
        _bal(old, POT) == 0)

legacy_return = reconcile_expired_minimum(old, league_id=LEAGUE, now=NOW)
old.commit()
# Only team 2 spent in this fixture, so three GMs expire a whole Minimum each.
_assert("  · season close still returns the expired Minimum to Wallet",
        _bal(old, "wallet:2") == 600
        and legacy_return.total_cents == 600 + WEEKLY * 3,
        f"wallet={_bal(old, 'wallet:2')} total={legacy_return.total_cents}")
_assert("  · every legacy GM's Wallet was credited their own remainder",
        all(_bal(old, f"wallet:{t}") == WEEKLY for t in (1, 3, 4)),
        str({t: _bal(old, f"wallet:{t}") for t in (1, 3, 4)}))
_assert("  · and that step reports itself as NOT retired",
        legacy_return.retired is False)


# ── F11 · the retirements are real, and era-scoped ───────────────────────────

print("\nWP4-F11 · the retired paths are retired for the Final POR era only")
retired = reconcile_expired_minimum(db2, league_id=LEAGUE, now=NOW)
db2.commit()
_assert("the season-close return reports itself retired",
        retired.retired is True)
_assert("  · it returned nothing and named nobody",
        retired.total_cents == 0 and retired.returned == ())
_assert("  · it found no stranded expired_min: balance",
        retired.stranded == (), str(retired.stranded))
_assert("  · it credited no Wallet",
        all(_bal(db2, f"wallet:{t}") == 0 for t in TEAMS),
        str({t: _bal(db2, f"wallet:{t}") for t in TEAMS}))
_assert("  · it recorded no reconciliation event",
        db.execute(text(
            "SELECT COUNT(*) FROM economy_event "
            "WHERE event_type = 'EXPIRED_MINIMUM_RECONCILIATION'")).scalar()
        == 0)
_assert("  · the pot is untouched by the retired step",
        _bal(db2, POT) == pot_after_first)

import ast  # noqa: E402
import inspect  # noqa: E402

import economy.weekly_minimum as wm  # noqa: E402

_assert("week close reads the era from the one gate, not a literal",
        "is_final_por" in inspect.getsource(wm.expire_weekly_minimum))

# The module names the two eras in PROSE, which is the point of the docstring.
# What it must never do is BRANCH on a version literal: a second site comparing
# raw integers is a second era gate, and two era gates can drift apart. Walked
# as an AST rather than grepped, so a comment or a docstring cannot fail it and
# a real reference cannot hide from it.
_tree = ast.parse(inspect.getsource(wm))
_named = sorted({n.id for n in ast.walk(_tree)
                 if isinstance(n, ast.Name) and n.id.startswith("RULESET_")})
_assert("  · no executable line names a ruleset version constant",
        _named == [], str(_named))
_assert("  · and the module exposes no version constant of its own",
        [n for n in dir(wm) if n.startswith("RULESET_")] == [],
        str([n for n in dir(wm) if n.startswith("RULESET_")]))


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-4 unused Weekly Minimum -> FantasyStakes Championship Pot: "
      "all assertions passed")
