#!/usr/bin/env python3
"""RC2 HIGH-1 certification — the FantasyStakes Championship field is immutable.

THE PROPERTY UNDER TEST. Season activation advances one contribution per GM into
the fixed FantasyStakes Championship Pot and records one
`FantasyStakesChampionshipAllocation` row per GM. That row set IS the
championship field. A later roster change must not silently redefine it.

Before the audit fix, the freeze derived its field from the CURRENT `teams`
table. A team added between activation and freeze produced a snapshot whose team
set differed from the funded allocation set, settlement then refused forever with
"allocation does not cover the frozen field", and the fixed pot was stranded with
no recovery path. Reading an already-valid snapshot was measured against the
current roster too, so an unrelated later team row could make a frozen
championship report itself PARTIAL.

Every assertion below is written so that the ONLY way to pass is to fail closed.
No case may be satisfied by growing, shrinking, minting into or refunding from
the pot: the pot balance and the ledger trial balance are asserted at every step.

SQLite is sufficient here — this is a state-machine and set-identity suite, not a
concurrency one.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

_TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'rc2-field.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.schema import (  # noqa: E402
    Base, League, LeagueSeasonEconomyConfig, SeasonAllocation, SessionLocal,
    Team, Wallet, engine,
)
from economy.fantasystakes_championship_allocation import (  # noqa: E402
    FantasyStakesChampionshipAllocation, pot_account,
)
from economy.fantasystakes_championship_settlement import (  # noqa: E402
    settle_fantasystakes_championship,
)
from economy.rc2_season_activation import (  # noqa: E402
    activate_fantasystakes_championship_stage,
)
from ledger.ledger import (  # noqa: E402
    SEASON_ALLOCATION_DOOR, balance_of, create_ledger_table, post as ledger_post,
    trial_balance,
)
from reports.championship_read_model import (  # noqa: E402
    FantasyStakesChampionshipError,
    FantasyStakesChampionshipFreeze,
    FantasyStakesChampionshipScore,
    REASON_FIELD_CHANGED,
    REASON_NOT_ACTIVATED,
    freeze_fantasystakes_championship,
    funded_championship_field,
    get_fantasystakes_championship,
)

FAIL: list[str] = []
SEASON = 2027
CONTRIBUTION = 8_000
BASE_BUYIN = 22_000


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


Base.metadata.create_all(engine)
create_ledger_table()


def build_activated_league(name: str, team_count: int = 4) -> tuple[int, list[int]]:
    """A league with a real base allocation and a completed RC2 championship stage."""
    with SessionLocal() as db:
        league = League(season=SEASON, name=name, projection_source="fantasypros",
                        start_week=1, playoff_start_week=15, season_final_week=17,
                        provider_current_week=15)
        db.add(league)
        db.flush()
        league_id = league.id
        team_ids: list[int] = []
        for i in range(team_count):
            t = Team(league_id=league_id, team_name=f"{name} Team {i + 1}",
                     owner=f"Owner {i + 1}", email=f"field-{league_id}-{i + 1}@example.test")
            db.add(t)
            db.flush()
            team_ids.append(t.id)
            db.add(Wallet(team_id=t.id, balance=0.0))
        db.add(LeagueSeasonEconomyConfig(
            league_id=league_id, season=SEASON, weekly_bet_minimum_cents=1000,
            championship_contribution_cents=CONTRIBUTION, skunk_fee_cents=1000,
            regular_season_week_count=14, active_team_count=team_count,
            start_week_used=1, playoff_start_week_used=15, frozen_at=None))
        # Real base Season-Opening Allocation: rows AND their three-leg postings.
        for tid in team_ids:
            db.add(SeasonAllocation(league_id=league_id, team_id=tid, season=SEASON,
                                    buyin_cents=BASE_BUYIN, min_reserve_cents=14_000,
                                    reserve_cents=8_000))
            ledger_post(
                [(f"season_issuance:{league_id}:{SEASON}", -BASE_BUYIN),
                 (f"min_reserve:{tid}", 14_000),
                 (f"reserve:{tid}", 8_000)],
                door=SEASON_ALLOCATION_DOOR, session=db)
        db.commit()

    with SessionLocal() as db:
        activate_fantasystakes_championship_stage(league_id, db)
    return league_id, team_ids


def add_team(league_id: int, label: str) -> int:
    with SessionLocal() as db:
        t = Team(league_id=league_id, team_name=label, owner=label,
                 email=f"late-{league_id}-{label}@example.test".replace(" ", "-"))
        db.add(t)
        db.flush()
        db.add(Wallet(team_id=t.id, balance=0.0))
        tid = t.id
        db.commit()
    return tid


def freeze_state(league_id: int) -> tuple[int, int]:
    """(freeze marker count, championship score row count) for this league-season."""
    with SessionLocal() as db:
        markers = (db.query(FantasyStakesChampionshipFreeze)
                   .filter(FantasyStakesChampionshipFreeze.league_id == league_id,
                           FantasyStakesChampionshipFreeze.season == SEASON).count())
        scores = (db.query(FantasyStakesChampionshipScore)
                  .filter(FantasyStakesChampionshipScore.league_id == league_id,
                          FantasyStakesChampionshipScore.season == SEASON).count())
    return markers, scores


def try_freeze(league_id: int, now=None):
    """Freeze in its own transaction. Returns (snapshot, reason_code)."""
    with SessionLocal() as db:
        try:
            snap = freeze_fantasystakes_championship(db, league_id=league_id, now=now)
            db.commit()
            return snap, None
        except FantasyStakesChampionshipError as exc:
            db.rollback()
            return None, exc.reason


# ── 0 · no activation, therefore no field ────────────────────────────────────
print("\nRC2-F-0 · pre-activation freeze is refused — a field must be funded first")

# A league that reached its boundary and completed its BASE economy, but never
# activated the FantasyStakes Championship. There is no contribution, no pot and
# no allocation row set, so there is no field. The freeze must refuse rather than
# fall back to the roster: a snapshot taken here could never be settled, because
# settlement requires an allocation set that does not exist.
with SessionLocal() as db:
    league0 = League(season=SEASON, name="Field Zero", projection_source="fantasypros",
                     start_week=1, playoff_start_week=15, season_final_week=17,
                     provider_current_week=15)
    db.add(league0)
    db.flush()
    lid_0 = league0.id
    teams_0 = []
    for i in range(4):
        t = Team(league_id=lid_0, team_name=f"Zero Team {i + 1}", owner=f"Owner {i + 1}",
                 email=f"zero-{lid_0}-{i + 1}@example.test")
        db.add(t)
        db.flush()
        teams_0.append(t.id)
        db.add(Wallet(team_id=t.id, balance=0.0))
    db.add(LeagueSeasonEconomyConfig(
        league_id=lid_0, season=SEASON, weekly_bet_minimum_cents=1000,
        championship_contribution_cents=CONTRIBUTION, skunk_fee_cents=1000,
        regular_season_week_count=14, active_team_count=4,
        start_week_used=1, playoff_start_week_used=15, frozen_at=None))
    for tid in teams_0:
        db.add(SeasonAllocation(league_id=lid_0, team_id=tid, season=SEASON,
                                buyin_cents=BASE_BUYIN, min_reserve_cents=14_000,
                                reserve_cents=8_000))
        ledger_post(
            [(f"season_issuance:{lid_0}:{SEASON}", -BASE_BUYIN),
             (f"min_reserve:{tid}", 14_000),
             (f"reserve:{tid}", 8_000)],
            door=SEASON_ALLOCATION_DOOR, session=db)
    db.commit()

trial_before_0 = trial_balance()
with SessionLocal() as db:
    funded_0 = funded_championship_field(db, league_id=lid_0, season=SEASON)
check("an unactivated league-season has no funded field",
      funded_0 is None, str(funded_0))

snap_0, reason_0 = try_freeze(lid_0)
check("pre-activation freeze is refused with the stable not-activated reason",
      snap_0 is None and reason_0 == REASON_NOT_ACTIVATED, str(reason_0))

markers_0, scores_0 = freeze_state(lid_0)
check("pre-activation refusal wrote no freeze marker",
      markers_0 == 0, str(markers_0))
check("pre-activation refusal wrote no championship score rows",
      scores_0 == 0, str(scores_0))
with SessionLocal() as db:
    read_0 = get_fantasystakes_championship(db, league_id=lid_0, season=SEASON)
check("no frozen championship is readable for an unactivated league-season",
      read_0 is None, str(read_0))
check("refusal created no FantasyStakes Championship Pot",
      balance_of(pot_account(lid_0, SEASON)) == 0,
      str(balance_of(pot_account(lid_0, SEASON))))
with SessionLocal() as db:
    alloc_0 = (db.query(FantasyStakesChampionshipAllocation)
               .filter(FantasyStakesChampionshipAllocation.league_id == lid_0,
                       FantasyStakesChampionshipAllocation.season == SEASON).count())
check("refusal did not auto-activate or auto-fund the championship",
      alloc_0 == 0, str(alloc_0))
check("trial balance remains zero",
      trial_balance() == 0 == trial_before_0, str(trial_balance()))


# ── A · the unchanged field ──────────────────────────────────────────────────
print("\nRC2-F-A · unchanged field freezes and remains settleable")

lid_a, teams_a = build_activated_league("Field A")
pot_a = pot_account(lid_a, SEASON)
pot_after_activation = balance_of(pot_a)
check("activation funded the fixed pot",
      pot_after_activation == CONTRIBUTION * len(teams_a), str(pot_after_activation))

with SessionLocal() as db:
    funded = funded_championship_field(db, league_id=lid_a, season=SEASON)
check("funded field is exactly the activated team set",
      funded == frozenset(teams_a), f"{sorted(funded or ())} vs {sorted(teams_a)}")

snap_a, reason_a = try_freeze(lid_a)
check("unchanged field freezes", snap_a is not None and reason_a is None, str(reason_a))
check("frozen field equals the funded field",
      snap_a is not None and {r.team_id for r in snap_a.rows} == set(teams_a),
      str(sorted(r.team_id for r in (snap_a.rows if snap_a else ()))))
check("freeze moved no money",
      balance_of(pot_a) == pot_after_activation and trial_balance() == 0,
      f"pot={balance_of(pot_a)} trial={trial_balance()}")

with SessionLocal() as db:
    settled = settle_fantasystakes_championship(db, league_id=lid_a)
check("settlement pays the funded field exactly once",
      not settled.replayed
      and settled.pot_cents == CONTRIBUTION * len(teams_a)
      and sum(a.amount_cents for a in settled.awards) == settled.pot_cents,
      str([(a.team_id, a.amount_cents) for a in settled.awards]))
check("pot drains to zero and the ledger still balances",
      balance_of(pot_a) == 0 and trial_balance() == 0,
      f"pot={balance_of(pot_a)} trial={trial_balance()}")


# ── B · team ADDED after activation, before freeze ───────────────────────────
print("\nRC2-F-B · team added after activation, before freeze — fails closed")

lid_b, teams_b = build_activated_league("Field B")
pot_b = pot_account(lid_b, SEASON)
pot_before_b = balance_of(pot_b)
trial_before_b = trial_balance()
late_b = add_team(lid_b, "Late Joiner B")

snap_b, reason_b = try_freeze(lid_b)
check("freeze refuses with the stable field-change reason",
      snap_b is None and reason_b == REASON_FIELD_CHANGED, str(reason_b))

markers_b, scores_b = freeze_state(lid_b)
check("no freeze marker was written", markers_b == 0, str(markers_b))
check("no championship score rows were written", scores_b == 0, str(scores_b))
with SessionLocal() as db:
    read_b = get_fantasystakes_championship(db, league_id=lid_b, season=SEASON)
check("get_fantasystakes_championship still reports no frozen championship",
      read_b is None, str(read_b))
check("FS Championship Pot is exactly unchanged",
      balance_of(pot_b) == pot_before_b == CONTRIBUTION * len(teams_b),
      f"{balance_of(pot_b)} vs {pot_before_b}")
check("trial balance remains zero",
      trial_balance() == 0 == trial_before_b, str(trial_balance()))

with SessionLocal() as db:
    alloc_b = {r.team_id for r in db.query(FantasyStakesChampionshipAllocation)
               .filter(FantasyStakesChampionshipAllocation.league_id == lid_b,
                       FantasyStakesChampionshipAllocation.season == SEASON).all()}
check("no contribution was auto-added for the late GM",
      alloc_b == set(teams_b) and late_b not in alloc_b, str(sorted(alloc_b)))

# The refusal is retryable, not terminal: once the divergence is corrected by a
# governed action the freeze proceeds on the original funded field. Removing the
# never-allocated late row is the correction here; nothing about the funded field
# or the pot changes.
with SessionLocal() as db:
    db.query(Wallet).filter(Wallet.team_id == late_b).delete()
    db.query(Team).filter(Team.id == late_b).delete()
    db.commit()
snap_b2, reason_b2 = try_freeze(lid_b)
check("freeze is retryable after a governed correction",
      snap_b2 is not None and reason_b2 is None
      and {r.team_id for r in snap_b2.rows} == set(teams_b), str(reason_b2))
check("the correction moved no money",
      balance_of(pot_b) == pot_before_b and trial_balance() == 0,
      f"pot={balance_of(pot_b)} trial={trial_balance()}")


# ── C · funded GM no longer in the league's current team set ─────────────────
print("\nRC2-F-C · funded GM missing from the current field — fails closed")

lid_c, teams_c = build_activated_league("Field C")
pot_c = pot_account(lid_c, SEASON)
pot_before_c = balance_of(pot_c)
dropped = teams_c[-1]

# PHYSICAL DELETION IS ATTEMPTED FIRST AND IS EXPECTED TO BE STRUCTURALLY
# FORBIDDEN. `fantasystakes_championship_allocation.team_id`,
# `season_allocation.team_id` and `wallets.team_id` all carry foreign keys to
# `teams.id`, so a funded GM's row cannot be deleted while its allocation exists
# — which is itself part of what protects the field. The representable divergent
# condition is therefore reassignment: the team row survives (so the FK holds and
# the frozen id stays resolvable for display) but it is no longer a member of
# THIS league, so the league's current team set no longer covers the funded field.
physical_delete_ok = False
with SessionLocal() as db:
    try:
        db.query(Team).filter(Team.id == dropped).delete()
        db.commit()
        physical_delete_ok = True
    except Exception:
        db.rollback()
print(f"    · physical deletion of a funded GM permitted: {physical_delete_ok}")

if not physical_delete_ok:
    with SessionLocal() as db:
        other = League(season=SEASON, name="Field C Elsewhere",
                       projection_source="fantasypros", start_week=1,
                       playoff_start_week=15, season_final_week=17)
        db.add(other)
        db.flush()
        db.query(Team).filter(Team.id == dropped).update({"league_id": other.id})
        db.commit()

with SessionLocal() as db:
    current_c = {t.id for t in db.query(Team).filter(Team.league_id == lid_c).all()}
check("the funded GM is no longer in the league's current team set",
      dropped not in current_c and current_c == set(teams_c[:-1]), str(sorted(current_c)))

snap_c, reason_c = try_freeze(lid_c)
check("freeze refuses with the stable field-change reason",
      snap_c is None and reason_c == REASON_FIELD_CHANGED, str(reason_c))

markers_c, scores_c = freeze_state(lid_c)
check("no freeze marker or score rows were written",
      markers_c == 0 and scores_c == 0, f"markers={markers_c} scores={scores_c}")
with SessionLocal() as db:
    funded_c = funded_championship_field(db, league_id=lid_c, season=SEASON)
check("the allocated GM was NOT silently removed from the funded field",
      funded_c == frozenset(teams_c), str(sorted(funded_c or ())))
check("FS Championship Pot is exactly unchanged",
      balance_of(pot_c) == pot_before_c == CONTRIBUTION * len(teams_c),
      f"{balance_of(pot_c)} vs {pot_before_c}")
check("trial balance remains zero", trial_balance() == 0, str(trial_balance()))


# ── D · team added AFTER a valid freeze ──────────────────────────────────────
print("\nRC2-F-D · team added after a valid freeze — snapshot stays readable")

lid_d, teams_d = build_activated_league("Field D")
pot_d = pot_account(lid_d, SEASON)
snap_d, reason_d = try_freeze(lid_d)
check("baseline freeze succeeds", snap_d is not None and reason_d is None, str(reason_d))
original_field = [(r.team_id, r.place, r.championship_score_cents) for r in snap_d.rows]
pot_before_d = balance_of(pot_d)

late_d = add_team(lid_d, "Late Joiner D")

with SessionLocal() as db:
    reread = get_fantasystakes_championship(db, league_id=lid_d, season=SEASON)
check("an already-frozen snapshot stays readable after a later team row",
      reread is not None, f"rows={len(reread.rows) if reread else None}")
check("frozen ranking and team set are unchanged",
      reread is not None
      and [(r.team_id, r.place, r.championship_score_cents) for r in reread.rows]
      == original_field,
      str([(r.team_id, r.place, r.championship_score_cents)
           for r in (reread.rows if reread else ())]))
check("the late team does not appear in the frozen championship",
      reread is not None and late_d not in {r.team_id for r in reread.rows},
      str(sorted(r.team_id for r in (reread.rows if reread else ()))))

with SessionLocal() as db:
    settled_d = settle_fantasystakes_championship(db, league_id=lid_d)
check("settlement still evaluates only the original funded/frozen field",
      {a.team_id for a in settled_d.awards} <= set(teams_d)
      and late_d not in {a.team_id for a in settled_d.awards}
      and settled_d.pot_cents == CONTRIBUTION * len(teams_d)
      and sum(a.amount_cents for a in settled_d.awards) == settled_d.pot_cents,
      str([(a.team_id, a.amount_cents) for a in settled_d.awards]))
check("pot paid exactly once and the ledger balances",
      balance_of(pot_d) == 0 and pot_before_d == CONTRIBUTION * len(teams_d)
      and trial_balance() == 0,
      f"pot={balance_of(pot_d)} trial={trial_balance()}")


# ── E · freeze replay ────────────────────────────────────────────────────────
print("\nRC2-F-E · freeze replay stays idempotent")

lid_e, teams_e = build_activated_league("Field E")
pot_e = pot_account(lid_e, SEASON)
# SQLite stores timezone-naive DateTime values, so a tz-aware `now` would not
# compare equal to the value read back on replay. The assertion is about replay
# immutability, not dialect timezone decoration — same rationale as
# test_rc2_championship.py. PostgreSQL timezone behavior is covered by PG certification.
freeze_at_e = datetime(2027, 12, 15, 12, 0)
snap_e1, _ = try_freeze(lid_e, now=freeze_at_e)
markers_1, scores_1 = freeze_state(lid_e)
snap_e2, reason_e2 = try_freeze(lid_e)
markers_2, scores_2 = freeze_state(lid_e)
check("replay returns the immutable original snapshot",
      snap_e2 is not None and reason_e2 is None
      and snap_e1 is not None
      and snap_e2.frozen_at == snap_e1.frozen_at == freeze_at_e
      and [r.team_id for r in snap_e2.rows] == [r.team_id for r in snap_e1.rows],
      str(reason_e2))
check("replay creates no duplicate marker or score rows",
      (markers_2, scores_2) == (markers_1, scores_1) == (1, len(teams_e)),
      f"{(markers_1, scores_1)} then {(markers_2, scores_2)}")

# Replay must also stay idempotent once the roster has moved on.
add_team(lid_e, "Late Joiner E")
snap_e3, reason_e3 = try_freeze(lid_e)
markers_3, scores_3 = freeze_state(lid_e)
check("replay after a later roster change still returns the frozen field",
      snap_e3 is not None and reason_e3 is None
      and [r.team_id for r in snap_e3.rows] == [r.team_id for r in snap_e1.rows],
      str(reason_e3))
check("no duplicate rows after the post-freeze roster change",
      (markers_3, scores_3) == (1, len(teams_e)), str((markers_3, scores_3)))


# ── F · nothing in this suite grew the pot ───────────────────────────────────
print("\nRC2-F-F · pot conservation across the whole suite")

expected_pots = {
    pot_account(lid_0, SEASON): 0,                              # never activated
    pot_account(lid_a, SEASON): 0,                              # settled
    pot_account(lid_b, SEASON): CONTRIBUTION * len(teams_b),    # refused, intact
    pot_account(lid_c, SEASON): CONTRIBUTION * len(teams_c),    # refused, intact
    pot_account(lid_d, SEASON): 0,                              # settled
    pot_account(lid_e, SEASON): CONTRIBUTION * len(teams_e),    # frozen, unsettled
}
for account, expected in expected_pots.items():
    check(f"pot {account} is exactly {expected}",
          balance_of(account) == expected, str(balance_of(account)))
check("global trial balance is exactly zero", trial_balance() == 0, str(trial_balance()))


print(f"\n{'=' * 64}")
if FAIL:
    print(f"FAILED: {len(FAIL)} assertion(s)")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("PASS: RC2 HIGH-1 championship field immutability certification")
