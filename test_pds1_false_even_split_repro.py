"""PDS1 — the false EVEN_SPLIT, reproduced and then shown fixed, in the ledger.

ONE SCENARIO, SETTLED TWICE. Four GMs pick four different teams whose `touches`
totals are genuinely 30 / 18 / 13 / 7. There is one right answer.

  BEFORE — the boundary is restored to its pre-fix behaviour by replacing
           `normalize_component` at the provider source with a pass-through, so
           components carry raw operands only. That is exactly what the unfixed
           tree did; no file is edited to produce it.
  AFTER  — the shipped boundary.

The assertion is economic, not cosmetic: BEFORE must pay all four GMs, AFTER
must pay exactly one, and both must leave the ledger balanced. A fix that merely
changed a number somewhere would not move these legs.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

import providers.week_stat_source as wss
from db.schema import (
    Base, League, Matchup, NflSchedule, PoolInstance, SessionLocal, Team,
    Wallet, engine,
)
from betting.pool_catalog import seed_definitions
from betting.pool_claims import submit_claim
from betting.pool_settlement import settle_pool_instance
from ledger.ledger import create_ledger_table, post as ledger_post, trial_balance
from providers.base import (
    ProviderLeague, ProviderPlayerStats, ProviderRosterEntry, ProviderTeam,
    ProviderWeek,
)
from providers.identity import build_team_identity_resolver

DIALECT = engine.dialect.name
NOW = datetime(2026, 12, 30, 12, 0, 0, tzinfo=timezone.utc)
KICKOFF = datetime(2027, 1, 3, 18, 0, 0, tzinfo=timezone.utc)
PROVIDER = "pds1r"
SEASON = 2026
WEEK = 4
ENTRY = 500

RAW = frozenset({"rush_attempts", "receptions", "rushing_yards",
                 "receiving_yards"})

#: touches = rush_attempts + receptions -> 30, 18, 13, 7. Team 1 must win.
TOUCH_LINES = {
    1: {"rush_attempts": 20.0, "receptions": 10.0,
        "rushing_yards": 140.0, "receiving_yards": 110.0},
    2: {"rush_attempts": 12.0, "receptions": 6.0,
        "rushing_yards": 80.0, "receiving_yards": 60.0},
    3: {"rush_attempts": 9.0, "receptions": 4.0,
        "rushing_yards": 50.0, "receiving_yards": 40.0},
    4: {"rush_attempts": 5.0, "receptions": 2.0,
        "rushing_yards": 20.0, "receiving_yards": 15.0},
}


class _Map:
    def canonical_for(self, stat_id):
        return stat_id if stat_id in RAW else None


def _passthrough(values, vocab=None):
    """The pre-fix boundary: canonical names in, nothing derived."""
    return dict(values), frozenset(values)


print("=" * 78)
print(f"PDS1 — FALSE EVEN_SPLIT REPRODUCTION  ({DIALECT})")
print("=" * 78)

Base.metadata.create_all(engine)
create_ledger_table()

with SessionLocal() as db:
    if not (db.query(NflSchedule)
            .filter(NflSchedule.season == SEASON,
                    NflSchedule.week == WEEK).first()):
        db.add(NflSchedule(season=SEASON, week=WEEK, home_team="RPRH",
                           away_team="RPRA", kickoff_utc=KICKOFF))
        db.commit()
    seed_definitions(db)
    db.commit()


def run_once(tag: str) -> tuple:
    """Build a fresh league, settle most_offensive_touches, return the legs."""
    with SessionLocal() as db:
        league = League(season=SEASON, name=f"repro {tag}",
                        projection_source="pds1r", provider=PROVIDER,
                        provider_league_key=f"pds1r.l.{tag}", start_week=1,
                        playoff_start_week=15, season_final_week=17,
                        provider_current_week=WEEK)
        db.add(league)
        db.flush()
        teams = []
        for i in range(1, 5):
            t = Team(league_id=league.id, team_name=f"{tag} T{i}",
                     owner=f"GM{i}", email=f"gm{i}.{tag}@pds1r.invalid",
                     provider=PROVIDER, provider_team_key=f"pds1r.l.{tag}.t.{i}",
                     provider_team_id=str(i))
            db.add(t)
            db.flush()
            db.add(Wallet(team_id=t.id, balance=0))
            teams.append(t)
        for a in (0, 2):
            db.add(Matchup(league_id=league.id, week=WEEK,
                           home_team_id=teams[a].id,
                           away_team_id=teams[a + 1].id,
                           home_score=100.0, away_score=90.0,
                           winner_team_id=teams[a].id, finalized_at=NOW,
                           provider_matchup_key=f"pds1r.{tag}.m{a}",
                           refreshed_at=NOW))
        db.flush()

        pot = ENTRY * 4
        ledger_post([("world", -pot), (f"pool:{league.id}", pot)],
                    door="pool_weekly_collection", session=db)
        inst = PoolInstance(league_id=league.id, season=SEASON, week=WEEK,
                            slot=1, phase="REGULAR", rotation_cycle=1,
                            definition_key="most_offensive_touches",
                            pot_cents=pot, settled=False)
        db.add(inst)
        db.flush()
        for i, t in enumerate(teams):
            submit_claim(db, pool_instance_id=inst.id, team_id=t.id,
                         subject_id=teams[i].id, now=NOW)
        db.flush()

        p_teams, rosters, stats = [], [], []
        for i, t in enumerate(teams, start=1):
            p_teams.append(ProviderTeam(provider=PROVIDER,
                                        team_key=t.provider_team_key,
                                        team_id=str(i), name=t.team_name))
            pk = f"{t.provider_team_key}.p0"
            rosters.append(ProviderRosterEntry(
                provider=PROVIDER, team_key=t.provider_team_key, player_key=pk,
                player_id=pk, week=WEEK, slot="RB", name=pk))
            stats.append(ProviderPlayerStats(
                provider=PROVIDER, player_key=pk, week=WEEK,
                values=TOUCH_LINES[i],
                stat_ids_present=frozenset(TOUCH_LINES[i]),
                fantasy_points=10.0))
        snap = ProviderWeek(
            league=ProviderLeague(provider=PROVIDER,
                                  league_key=league.provider_league_key,
                                  name=league.name, season=SEASON,
                                  current_week=WEEK),
            week=WEEK, teams=tuple(p_teams), matchups=(),
            roster_entries=tuple(rosters), player_stats=tuple(stats))

        src = wss.ProviderWeekStatSource(snap, stat_map=_Map()).bind(
            db, build_team_identity_resolver(db, league_id=league.id,
                                             provider=PROVIDER))
        result = settle_pool_instance(db, pool_instance_id=inst.id,
                                      stat_source=src, now=NOW)
        db.flush()
        legs = db.execute(text(
            "SELECT account, amount_cents FROM ledger_entries WHERE door = "
            "'pool_winner_distribution' AND amount_cents > 0 AND posting_id IN "
            "(SELECT posting_id FROM ledger_entries WHERE account = :a) "
            "ORDER BY account"), {"a": f"pool:{league.id}"}).fetchall()
        db.commit()
        return result, [(a, int(c)) for a, c in legs], teams[0].id


failures = []

# ── BEFORE ────────────────────────────────────────────────────────────────────
_real = wss.normalize_component
wss.normalize_component = _passthrough
try:
    before, before_legs, _ = run_once(f"before{uuid.uuid4().hex[:5]}")
finally:
    wss.normalize_component = _real

print("\nBEFORE — provider boundary does not materialize derived operands")
print(f"  winning subjects : {len(before.winning_subject_ids)}")
print(f"  winner legs      : {before_legs}")
if len(before_legs) == 4 and {c for _, c in before_legs} == {500}:
    print("  [REPRODUCED] the pot was split 4 ways across the ENTIRE league, "
          "on a field with one genuine winner")
else:
    failures.append("BEFORE did not reproduce the false 4-way EVEN_SPLIT")
    print(f"  [UNEXPECTED] {before_legs}")

# ── AFTER ─────────────────────────────────────────────────────────────────────
after, after_legs, winner_team_id = run_once(f"after{uuid.uuid4().hex[:5]}")

print("\nAFTER — shipped boundary")
print(f"  winning subjects : {len(after.winning_subject_ids)}")
print(f"  winner legs      : {after_legs}")
if (len(after_legs) == 1 and after_legs[0][0] == f"wallet:{winner_team_id}"
        and after_legs[0][1] == 2000):
    print("  [FIXED] the single genuine winner takes the whole pot")
else:
    failures.append("AFTER did not pay exactly the one genuine winner")

if trial_balance() != 0:
    failures.append(f"trial balance {trial_balance()} != 0")
print(f"\n  trial balance across BOTH settlements: {trial_balance()}")

print("\n" + "=" * 78)
if failures:
    for f in failures:
        print(f"   FAILED: {f}")
    print(f"PDS1 FALSE-SPLIT REPRO ({DIALECT}): FAILED")
    sys.exit(1)
print(f"PDS1 FALSE-SPLIT REPRO ({DIALECT}): reproduced before, correct after")
