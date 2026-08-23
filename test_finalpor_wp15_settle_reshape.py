#!/usr/bin/env python3
"""FINAL POR · WP-15 certification — My Settle reshape + external mapping.

    F1  the six concepts stay separate, and FS Score is not among them
    F2  `expired_min:` leaves the Final POR asset set
    F3  the per-GM championship obligation is gone — activation settles to 0
    F4  Skunk derives through event provenance, and a WP-12 correction nets
    F5  the Top-Off pot leg does NOT double the individual obligation
    F6  a championship award enters the Wallet ONCE
    F7  the external mapping is notional — it posts nothing at all
    F8  dues are equal-share over the FROZEN field, exact cents, canonical
    F9  SUM(owed) == SUM(receivable), without double-counting awards
    F10 the legacy era keeps its own shape

WHY F5 AND F6 ARE BOTH HERE. They are the two ways the reshape could
double-count. WP-6 puts 2X into circulation for X of Wallet, so a settle that
read the issuance tally instead of the Wallet leg would double the GM's debt;
and a championship award is already a Wallet credit, so a mapping that added the
award again would pay it twice on paper. The suite drives both to real numbers.
"""
from __future__ import annotations

import inspect
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import ledger.ledger as ledger_module
from db.schema import (
    Base, League, LeagueSeasonEconomyConfig, Matchup, SeasonAllocation, Team,
    Wallet,
)
from economy.championship_pots import mint_season_pots
from economy.current_settle import current_settle
from economy.external_mapping import (
    ExternalMappingError, frozen_participant_field, minted_championship_cents,
    reconcile, split_equally,
)
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
WEEKS = 4
WEEKLY = 1_000
FEE = 500
TEAMS = (1, 2, 3, 4)
MIN_RESERVE = WEEKLY * WEEKS


def _build(*, final_por: bool = True, allocate: bool = True):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=LEAGUE, name="L", season=SEASON, start_week=1,
                  playoff_start_week=WEEKS + 1, provider="yahoo"))
    for t in TEAMS:
        db.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider="yahoo",
                    provider_team_key=f"k{t}"))
        db.add(Wallet(team_id=t, balance=0.0))
    db.add(Matchup(id=1, league_id=LEAGUE, week=1, home_team_id=1,
                   away_team_id=2, home_score=100.0, away_score=98.0,
                   winner_team_id=1, finalized_at=NAIVE))
    db.add(Matchup(id=2, league_id=LEAGUE, week=1, home_team_id=3,
                   away_team_id=4, home_score=60.0, away_score=120.0,
                   winner_team_id=4, finalized_at=NAIVE))
    db.add(LeagueSeasonEconomyConfig(
        league_id=LEAGUE, season=SEASON,
        weekly_bet_minimum_cents=WEEKLY,
        championship_contribution_cents=8_000,
        skunk_fee_cents=FEE,
        regular_season_week_count=WEEKS,
        active_team_count=len(TEAMS),
        start_week_used=1, playoff_start_week_used=WEEKS + 1,
        frozen_at=NAIVE))
    db.commit()
    if final_por:
        stamp_ruleset(db, league_id=LEAGUE, season=SEASON,
                      version=RULESET_FINAL_POR)

    if allocate:
        for t in TEAMS:
            # THE FINAL POR OPENING ALLOCATION: two legs, no reserve leg. Posted
            # in the shape WP-5's activation posts it, so the obligation this
            # suite measures is the one production creates.
            ledger_post([(f"season_issuance:{LEAGUE}:{SEASON}", -MIN_RESERVE),
                         (f"min_reserve:{t}", MIN_RESERVE)],
                        door=SEASON_ALLOCATION_DOOR, session=db)
            db.add(SeasonAllocation(
                league_id=LEAGUE, team_id=t, season=SEASON,
                buyin_cents=MIN_RESERVE, min_reserve_cents=MIN_RESERVE,
                reserve_cents=0))
    db.commit()
    return db


def _bal(db, account: str) -> int:
    return ledger_module._balance_of_in_session(db, account)


def _settle(db, team_id: int):
    return current_settle(db, team_id=team_id, league_id=LEAGUE, season=SEASON)


# ── F1 · the six concepts ───────────────────────────────────────────────────

print("\nWP15-F1 · the six concepts stay separate; FS Score is not among them")
db = _build()
row = _settle(db, 1)
keys = set(row.as_dict())

_assert("Wallet is its own field", "wallet" in keys)
_assert("  · Top-Off principal is its own field", "topoff_issued" in keys)
_assert("  · Skunk assessment is its own field", "skunk" in keys)
_assert("  · Current Settle is its own field", "current_settle" in keys)
_assert("  · and the era that shaped them is stated", "is_final_por" in keys)
_assert("the FantasyStakes SCORE is absent — accounting is not competition",
        not any("score" in k or "net_cents" in k for k in keys), str(sorted(keys)))
_assert("  · and no championship POT is a GM asset",
        not any("championship" in k or "pot" in k for k in keys),
        str(sorted(keys)))

import economy.current_settle as cs  # noqa: E402

cs_src = inspect.getsource(cs)
_assert("  · the module never reads a championship pot account",
        "fantasystakes_championship" not in cs_src
        and "ff_championship" not in cs_src
        and "points_championship" not in cs_src)
_assert("  · nor the minted-issuance tally",
        "championship_issuance" not in cs_src)


# ── F2/F3 · the asset set and the opening allocation ───────────────────────

print("\nWP15-F2 · `expired_min:` leaves the Final POR asset set")
_assert("the row reports the Final POR era", row.is_final_por is True)
# Force a balance into the account the Final POR never writes, and require the
# asset set to ignore it. This is what makes the omission deliberate rather
# than an accident of a season that happens to have none.
ledger_post([(f"season_issuance:{LEAGUE}:{SEASON}", -750),
             ("expired_min:1", 750)],
            door=SEASON_ALLOCATION_DOOR, session=db)
db.commit()
forced = _settle(db, 1)
_assert("  · the field still reports the balance for a reader",
        forced.expired_min_cents == 750, str(forced.expired_min_cents))
_assert("  · but assets EXCLUDE it under the Final POR",
        forced.assets_cents == forced.wallet_cents
        + forced.weekly_min_live_cents + forced.min_reserve_cents
        + forced.in_play_cents,
        str(forced.as_dict()))
_assert("  · so Current Settle is unmoved by 750 cents sitting there",
        forced.current_settle_cents == row.current_settle_cents,
        f"{row.current_settle_cents} -> {forced.current_settle_cents}")

print("\nWP15-F3 · the per-GM championship obligation is gone")
clean = _build()
opening = _settle(clean, 1)
_assert("the GM's obligation is the Weekly Minimum advance and nothing else",
        opening.season_advance_cents == MIN_RESERVE,
        str(opening.season_advance_cents))
_assert("  · no `reserve:{team}` was ever advanced",
        _bal(clean, "reserve:1") == 0)
_assert("  · so the opening allocation moves Current Settle by EXACTLY ZERO",
        opening.current_settle_cents == 0, str(opening.as_dict()))
_assert("  · which the retired model could not do — it was -8000 by design",
        opening.obligations_cents == opening.assets_cents,
        f"{opening.obligations_cents} vs {opening.assets_cents}")


# ── F4 · Skunk through provenance ──────────────────────────────────────────

print("\nWP15-F4 · Skunk derives through event provenance, and a correction nets")
assess_weekly_skunk(clean, league_id=LEAGUE, week=1, now=NOW)
clean.commit()
skunked = _settle(clean, 3)

_assert("the skunked GM carries the fee as an obligation",
        skunked.skunk_cents == FEE, str(skunked.skunk_cents))
_assert("  · their Current Settle is -500", skunked.current_settle_cents == -FEE,
        str(skunked.current_settle_cents))
_assert("  · and the raw receivable is NOT added on top of it",
        skunked.obligations_cents
        == skunked.season_advance_cents + skunked.topoff_issued_cents + FEE,
        str(skunked.as_dict()))

# WP-12 restates the week onto a different GM. The obligation must MOVE.
for m in clean.query(Matchup).filter(Matchup.week == 1).all():
    if m.id == 1:
        m.home_score, m.away_score, m.winner_team_id = 190.0, 100.0, 1
    else:
        m.home_score, m.away_score, m.winner_team_id = 118.0, 120.0, 4
clean.commit()
correct_weekly_skunk(clean, league_id=LEAGUE, week=1, now=NOW)
clean.commit()

_assert("  · after a WP-12 correction the cleared GM owes nothing",
        _settle(clean, 3).skunk_cents == 0,
        str(_settle(clean, 3).skunk_cents))
_assert("  · their Current Settle is back to 0",
        _settle(clean, 3).current_settle_cents == 0,
        str(_settle(clean, 3).current_settle_cents))
_assert("  · and the newly-charged GM now carries it",
        _settle(clean, 2).skunk_cents == FEE,
        str(_settle(clean, 2).skunk_cents))
_assert("  · which the raw `receivable:` balance also shows, having netted",
        _bal(clean, "receivable:3") == 0 and _bal(clean, "receivable:2") == -FEE,
        f"t3={_bal(clean, 'receivable:3')} t2={_bal(clean, 'receivable:2')}")


# ── F5/F6 · the two ways to double-count ───────────────────────────────────

print("\nWP15-F5 · the Top-Off pot leg does NOT double the obligation")
topped = _build()
X = 2_000
before = _settle(topped, 1).current_settle_cents
ledger_post([(f"bab_issuance:{LEAGUE}:{SEASON}", -X * 2),
             ("wallet:1", X),
             (f"fantasystakes_championship:{LEAGUE}:{SEASON}", X)],
            door=APPROVED_BAB_TOPOFF_DOOR, session=topped)
topped.commit()
after = _settle(topped, 1)

_assert("2X entered circulation for X of Wallet",
        -_bal(topped, f"bab_issuance:{LEAGUE}:{SEASON}") == 2 * X
        and _bal(topped, "wallet:1") == X,
        f"issuance={-_bal(topped, f'bab_issuance:{LEAGUE}:{SEASON}')}")
_assert("  · but the GM's Top-Off obligation is X, not 2X",
        after.topoff_issued_cents == X, str(after.topoff_issued_cents))
_assert("  · so Current Settle moved by exactly 0",
        after.current_settle_cents == before,
        f"{before} -> {after.current_settle_cents}")
_assert("  · and the pot's X is nobody's obligation",
        _bal(topped, f"fantasystakes_championship:{LEAGUE}:{SEASON}") == X
        and sum(_settle(topped, t).obligations_cents for t in TEAMS)
        == MIN_RESERVE * len(TEAMS) + X,
        str(sum(_settle(topped, t).obligations_cents for t in TEAMS)))

print("\nWP15-F6 · a championship award enters the Wallet ONCE")
awarded = _build()
mint_season_pots(awarded, league_id=LEAGUE, season=SEASON,
                 fantasy_football_cents=4_000, now=NOW)
awarded.commit()
pre = _settle(awarded, 1)
ledger_post([(f"ff_championship:{LEAGUE}:{SEASON}", -4_000),
             ("wallet:1", 4_000)],
            door="championship_distribution", session=awarded)
awarded.commit()
post = _settle(awarded, 1)

_assert("the award reached the GM's Wallet",
        post.wallet_cents - pre.wallet_cents == 4_000,
        f"{pre.wallet_cents} -> {post.wallet_cents}")
_assert("  · Current Settle rose by exactly the award, not twice it",
        post.current_settle_cents - pre.current_settle_cents == 4_000,
        f"{pre.current_settle_cents} -> {post.current_settle_cents}")
_assert("  · no obligation was created by receiving it",
        post.obligations_cents == pre.obligations_cents,
        f"{pre.obligations_cents} -> {post.obligations_cents}")


# ── F7/F8/F9 · the external mapping ────────────────────────────────────────

print("\nWP15-F7 · the external mapping is notional — it posts nothing")
import economy.external_mapping as em  # noqa: E402

em_src = inspect.getsource(em)
_assert("no ledger posting is made",
        "ledger_post" not in em_src and "post as" not in em_src)
_assert("  · nothing is added to the session or committed",
        "db.add(" not in em_src and "db.commit()" not in em_src)
_assert("  · no economy event is recorded", "record_event" not in em_src)
_assert("  · and no FantasyStakes Score is read",
        "standings" not in em_src and "net_cents" not in em_src)

mapped = _build()
mint_season_pots(mapped, league_id=LEAGUE, season=SEASON,
                 fantasy_football_cents=4_000, now=NOW)
mapped.commit()
entries_before = mapped.execute(text(
    "SELECT COUNT(*) FROM ledger_entries")).scalar()
statement = reconcile(mapped, league_id=LEAGUE, season=SEASON)
_assert("  · reconciling wrote no ledger entry",
        mapped.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()
        == entries_before)

print("\nWP15-F8 · equal-share dues over the FROZEN field, exact cents")
minted = minted_championship_cents(mapped, league_id=LEAGUE, season=SEASON)
_assert("the minted total is the Base Pot plus the FF pot",
        minted == MIN_RESERVE + 4_000, str(minted))
_assert("  · the frozen field is the four allocated GMs",
        frozen_participant_field(mapped, league_id=LEAGUE, season=SEASON)
        == TEAMS, str(frozen_participant_field(mapped, league_id=LEAGUE,
                                               season=SEASON)))
_assert("  · dues are equal shares",
        len({r.notional_dues_cents for r in statement.rows}) == 1,
        str([r.notional_dues_cents for r in statement.rows]))
_assert("  · summing to exactly the minted total",
        statement.total_dues_cents == minted,
        f"{statement.total_dues_cents} vs {minted}")

_assert("  · an indivisible total assigns the remainder by ascending id",
        split_equally(1_001, (3, 1, 2)) == {1: 334, 2: 334, 3: 333},
        str(split_equally(1_001, (3, 1, 2))))
_assert("  · and still conserves exactly",
        sum(split_equally(1_001, (3, 1, 2)).values()) == 1_001)

# A GM who left mid-season stays in the field; a late joiner does not.
mapped.add(Team(id=9, league_id=LEAGUE, team_name="T9", owner="O9",
                email="t9@example.test", provider="yahoo",
                provider_team_key="k9"))
mapped.commit()
_assert("  · a GM who joined after allocation is NOT in the frozen field",
        9 not in frozen_participant_field(mapped, league_id=LEAGUE,
                                          season=SEASON),
        str(frozen_participant_field(mapped, league_id=LEAGUE, season=SEASON)))

print("\nWP15-F9 · SUM(owed) == SUM(receivable), awards counted once")
_assert("the statement balances", statement.balances is True)
_assert("  · SUM(owed) equals SUM(receivable) exactly",
        statement.total_owed_cents == statement.total_receivable_cents,
        f"{statement.total_owed_cents} vs {statement.total_receivable_cents}")
_assert("  · and equals dues minus the field's total Current Settle",
        statement.total_owed_cents
        == statement.total_dues_cents
        - sum(r.current_settle_cents for r in statement.rows),
        str(statement.as_dict()))

# Now pay a championship award and re-reconcile. The award is in a Wallet and
# must be counted ONCE — through Current Settle — and never added again.
ledger_post([(f"ff_championship:{LEAGUE}:{SEASON}", -4_000),
             ("wallet:1", 4_000)],
            door="championship_distribution", session=mapped)
mapped.commit()
paid = reconcile(mapped, league_id=LEAGUE, season=SEASON)
by_team = {r.team_id: r for r in paid.rows}

_assert("the winner's Current Settle rose by the award",
        by_team[1].current_settle_cents == 4_000,
        str(by_team[1].current_settle_cents))
_assert("  · so their `owed` FELL by exactly the award",
        by_team[1].owed_cents
        == by_team[1].notional_dues_cents - 4_000,
        f"{by_team[1].owed_cents} vs {by_team[1].notional_dues_cents - 4_000}")
_assert("  · nobody else's owed changed",
        all(by_team[t].owed_cents == by_team[t].notional_dues_cents
            for t in (2, 3, 4)),
        str({t: by_team[t].owed_cents for t in (2, 3, 4)}))
_assert("  · dues did NOT change — paying a pot does not un-mint it",
        paid.total_dues_cents == statement.total_dues_cents,
        f"{statement.total_dues_cents} -> {paid.total_dues_cents}")
_assert("  · and the statement still balances", paid.balances is True)
_assert("  · the whole field owes the minted total less what it has been paid",
        paid.total_owed_cents == paid.total_dues_cents - 4_000,
        f"{paid.total_owed_cents} vs {paid.total_dues_cents - 4_000}")


# ── F10 · the legacy era ───────────────────────────────────────────────────

print("\nWP15-F10 · the legacy era keeps its own shape")
old = _build(final_por=False)
ledger_post([(f"season_issuance:{LEAGUE}:{SEASON}", -750),
             ("expired_min:1", 750)],
            door=SEASON_ALLOCATION_DOOR, session=old)
old.commit()
legacy = current_settle(old, team_id=1, league_id=LEAGUE, season=SEASON)

_assert("the row reports the legacy era", legacy.is_final_por is False)
_assert("  · `expired_min:` is STILL a legacy asset",
        legacy.assets_cents
        == legacy.wallet_cents + legacy.weekly_min_live_cents
        + legacy.min_reserve_cents + legacy.expired_min_cents
        + legacy.in_play_cents,
        str(legacy.as_dict()))
_assert("  · and it really moved the figure",
        legacy.assets_cents - legacy.expired_min_cents
        != legacy.assets_cents)
assess_weekly_skunk(old, league_id=LEAGUE, week=1, now=NOW)
old.commit()
legacy_skunk = current_settle(old, team_id=3, league_id=LEAGUE, season=SEASON)
_assert("  · Skunk is still the raw `receivable:` obligation",
        legacy_skunk.receivable_cents == FEE
        and legacy_skunk.skunk_cents == 0,
        str(legacy_skunk.as_dict()))
_assert("  · counted once, not twice",
        legacy_skunk.obligations_cents
        == legacy_skunk.season_advance_cents
        + legacy_skunk.topoff_issued_cents + FEE)

try:
    reconcile(old, league_id=LEAGUE, season=SEASON)
    _assert("  · and the external mapping refuses a legacy season", False,
            "accepted")
except ExternalMappingError as exc:
    _assert("  · and the external mapping refuses a legacy season",
            exc.reason == "MAPPING_WRONG_ERA", exc.reason)

no_field = _build(allocate=False)
try:
    reconcile(no_field, league_id=LEAGUE, season=SEASON)
    _assert("  · a season with no frozen field refuses", False, "accepted")
except ExternalMappingError as exc:
    _assert("  · a season with no frozen field refuses",
            exc.reason == "MAPPING_NO_PARTICIPANT_FIELD", exc.reason)


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-15 My Settle reshape + optional external mapping: all assertions passed")
