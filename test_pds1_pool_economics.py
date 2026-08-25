"""PDS1 — the economic gate: derived-stat pools must pay the right GMs.

This is the suite that matters. The unit suite proves the operand reaches the
evaluator; this one drives REAL `settle_pool_instance` against a real ledger and
proves the money lands where the governed outcome says it should.

Four deterministic settlements, one per governed outcome:

    A · one subject genuinely highest      -> ONE winning GM takes the pot
    B · two subjects genuinely equal       -> EVEN_SPLIT across exactly those two
    C · a winner exists, nobody picked it  -> zero winning tickets, rollover
    D · no subject qualifies at all        -> zero eligible claims, rollover

THE REGRESSION BEING GUARDED. Before the fix a CLOSED_SUM over a derived operand
scored every subject 0.0, so every subject tied at the extremum, so EVERY claim
was a winning claim and the pot was split across the whole league. Case A is
built so that failure mode is loud: four GMs pick four different subjects with
four genuinely different `touches` totals. One winner leg is correct; four is
the defect.

Runs against DATABASE_URL, so the same assertions run on SQLite and PostgreSQL.
"""
from __future__ import annotations

import os
import sys
import uuid

_FAILURES: list[str] = []
_PASSES = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _PASSES
    if condition:
        _PASSES += 1
        print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))
    else:
        _FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


from sqlalchemy import text

from db.schema import (
    Base, League, Matchup, NflSchedule, PoolInstance, SessionLocal, Team,
    Wallet, engine,
)
from ledger.ledger import create_ledger_table, post as ledger_post, trial_balance
from betting.pool_catalog import seed_definitions
from betting.pool_claims import submit_claim
from betting.pool_settlement import settle_pool_instance
from providers.base import (
    ProviderLeague, ProviderMatchup, ProviderPlayerStats, ProviderRosterEntry,
    ProviderTeam, ProviderWeek,
)
from providers.identity import build_team_identity_resolver
from providers.week_stat_source import ProviderWeekStatSource
from datetime import datetime, timezone

DIALECT = engine.dialect.name
NOW = datetime(2026, 12, 30, 12, 0, 0, tzinfo=timezone.utc)
#: After NOW, so the pick window is open when the claims are made.
KICKOFF = datetime(2027, 1, 3, 18, 0, 0, tzinfo=timezone.utc)
PROVIDER = "pds1"
SEASON = 2026
WEEK = 3
ENTRY_CENTS = 500

print("=" * 78)
print(f"PDS1 — POOL ECONOMICS  ({DIALECT})")
print("=" * 78)

Base.metadata.create_all(engine)
create_ledger_table()

RAW_NAMES = frozenset({
    "rush_attempts", "receptions", "rushing_yards", "receiving_yards",
    "passing_yards", "pass_attempts", "passing_td", "rushing_td",
    "receiving_td", "targets",
    "field_goals_made_0_19", "field_goals_made_20_29",
    "field_goals_made_30_39", "field_goals_made_40_49",
    "field_goals_made_50_plus",
})


class _Map:
    def canonical_for(self, stat_id: str):
        return stat_id if stat_id in RAW_NAMES else None


def line(*, rush_att=0.0, rec=0.0, rush_yds=0.0, rec_yds=0.0, rtd=0.0,
         fg=(0.0, 0.0, 0.0, 0.0, 0.0)):
    """A raw box-score line. NO derived operand is ever supplied."""
    return {
        "rush_attempts": rush_att, "receptions": rec,
        "rushing_yards": rush_yds, "receiving_yards": rec_yds,
        "passing_yards": 0.0, "pass_attempts": 0.0, "passing_td": 0.0,
        "rushing_td": rtd, "receiving_td": 0.0, "targets": rec + 1.0,
        "field_goals_made_0_19": fg[0], "field_goals_made_20_29": fg[1],
        "field_goals_made_30_39": fg[2], "field_goals_made_40_49": fg[3],
        "field_goals_made_50_plus": fg[4],
    }


def ensure_schedule():
    """One future kickoff for the week under test, COMMITTED.

    `submit_claim` closes the pick window at kickoff, and this is an ordinary
    provider league, so the D2.3 resolver correctly falls through to the real
    `_nfl_lock_time`. That helper reads through its OWN session, so an
    uncommitted row is invisible to it — this commits. The row is global
    (nfl_schedule carries no league id) and shared by every case below.
    """
    with SessionLocal() as db:
        existing = (db.query(NflSchedule)
                    .filter(NflSchedule.season == SEASON,
                            NflSchedule.week == WEEK).first())
        if existing is None:
            db.add(NflSchedule(season=SEASON, week=WEEK, home_team="PDSH",
                               away_team="PDSA", kickoff_utc=KICKOFF))
            db.commit()


ensure_schedule()


def build_league(db, tag: str, n_teams: int = 4):
    league = League(season=SEASON, name=f"PDS1 {tag}",
                    projection_source="pds1", provider=PROVIDER,
                    provider_league_key=f"pds1.l.{tag}",
                    start_week=1, playoff_start_week=15, season_final_week=17,
                    provider_current_week=WEEK)
    db.add(league)
    db.flush()
    teams = []
    for i in range(1, n_teams + 1):
        t = Team(league_id=league.id, team_name=f"{tag} Team {i}",
                 owner=f"GM {i}", email=f"gm{i}.{tag}@pds1.invalid",
                 provider=PROVIDER,
                 provider_team_key=f"pds1.l.{tag}.t.{i}",
                 provider_team_id=str(i))
        db.add(t)
        db.flush()
        db.add(Wallet(team_id=t.id, balance=0))
        teams.append(t)
    # Finalized matchups — the finality gate must pass before any economics.
    for a in range(0, n_teams, 2):
        db.add(Matchup(league_id=league.id, week=WEEK,
                       home_team_id=teams[a].id, away_team_id=teams[a + 1].id,
                       home_score=100.0, away_score=90.0,
                       winner_team_id=teams[a].id, finalized_at=NOW,
                       provider_matchup_key=f"pds1.l.{tag}.m.{WEEK}.{a}",
                       refreshed_at=NOW))
    db.flush()
    return league, teams


def snapshot(league, teams, lines_by_ordinal):
    p_teams, rosters, stats = [], [], []
    for i, t in enumerate(teams, start=1):
        p_teams.append(ProviderTeam(provider=PROVIDER,
                                    team_key=t.provider_team_key,
                                    team_id=str(i), name=t.team_name))
        for j, values in enumerate(lines_by_ordinal[i]):
            pk = f"{t.provider_team_key}.p{j}"
            rosters.append(ProviderRosterEntry(
                provider=PROVIDER, team_key=t.provider_team_key,
                player_key=pk, player_id=pk, week=WEEK, slot="RB", name=pk))
            stats.append(ProviderPlayerStats(
                provider=PROVIDER, player_key=pk, week=WEEK, values=values,
                stat_ids_present=frozenset(values), fantasy_points=10.0))
    return ProviderWeek(
        league=ProviderLeague(provider=PROVIDER,
                              league_key=league.provider_league_key,
                              name=league.name, season=SEASON,
                              current_week=WEEK),
        week=WEEK, teams=tuple(p_teams), matchups=(),
        roster_entries=tuple(rosters), player_stats=tuple(stats))


def fund_pot(db, league, cents):
    """Put real credits in the pool account, as collection would.

    Counterparty is `world`, the ledger's own exempt account — this suite is
    testing SETTLEMENT, and routing through the full weekly-minimum release and
    collection path would add a second subsystem to every failure diagnosis
    without changing what settlement sees: a funded `pool:{league}`.
    """
    ledger_post([("world", -cents), (f"pool:{league.id}", cents)],
                door="pool_weekly_collection", session=db)
    db.flush()


def make_instance(db, league, definition_key, pot_cents, slot=1):
    inst = PoolInstance(league_id=league.id, season=SEASON, week=WEEK, slot=slot,
                        phase="REGULAR", rotation_cycle=1,
                        definition_key=definition_key, pot_cents=pot_cents,
                        settled=False)
    db.add(inst)
    db.flush()
    return inst


def winner_legs(db, posting_id):
    return db.execute(text(
        "SELECT account, amount_cents FROM ledger_entries "
        "WHERE posting_id = :p AND amount_cents > 0 ORDER BY account"),
        {"p": str(posting_id)}).fetchall()


def distribution_postings(db, league_id):
    return db.execute(text(
        "SELECT DISTINCT posting_id FROM ledger_entries "
        "WHERE door = 'pool_winner_distribution' AND account = :acct"),
        {"acct": f"pool:{league_id}"}).fetchall()


# ══════════════════════════════════════════════════════════════════════════════
# CASE A — one genuine winner. The false-EVEN_SPLIT regression guard.
# ══════════════════════════════════════════════════════════════════════════════

print("\nA · One subject genuinely highest — exactly one GM is paid")

with SessionLocal() as db:
    seed_definitions(db)
    db.flush()
    league, teams = build_league(db, f"a{uuid.uuid4().hex[:6]}")
    # touches = rush_attempts + receptions, and NOTHING supplies `touches`.
    lines = {
        1: [line(rush_att=20, rec=10, rush_yds=140, rec_yds=110)],  # 30  <- max
        2: [line(rush_att=12, rec=6, rush_yds=80, rec_yds=60)],     # 18
        3: [line(rush_att=5, rec=2, rush_yds=20, rec_yds=15)],      # 7
        4: [line(rush_att=9, rec=4, rush_yds=50, rec_yds=40)],      # 13
    }
    pot = ENTRY_CENTS * len(teams)
    fund_pot(db, league, pot)
    inst = make_instance(db, league, "most_offensive_touches", pot)
    # Each GM picks a DIFFERENT subject, so a whole-field tie pays everyone.
    for i, t in enumerate(teams):
        submit_claim(db, pool_instance_id=inst.id, team_id=t.id,
                     subject_id=teams[i].id, now=NOW)
    db.flush()

    src = ProviderWeekStatSource(snapshot(league, teams, lines),
                                 stat_map=_Map()).bind(
        db, build_team_identity_resolver(db, league_id=league.id,
                                         provider=PROVIDER))
    result = settle_pool_instance(db, pool_instance_id=inst.id,
                                  stat_source=src, now=NOW)
    db.flush()

    check("A1: classification is CLAIMS_PRESENT",
          result.classification == "CLAIMS_PRESENT", result.classification)
    check("A2: exactly ONE winning subject (not the whole field)",
          len(result.winning_subject_ids) == 1,
          f"winning_subject_ids={result.winning_subject_ids}")
    check("A3: the winner is the genuinely highest team (30 touches)",
          result.winning_subject_ids == (teams[0].id,),
          f"expected ({teams[0].id},) got {result.winning_subject_ids}")
    check("A4: exactly ONE winning GM",
          result.winning_team_ids == (teams[0].id,),
          str(result.winning_team_ids))

    postings = distribution_postings(db, league.id)
    legs = winner_legs(db, postings[0][0])
    check("A5: the distribution posting has exactly ONE winner leg — "
          "the 4-way false split cannot occur",
          len(legs) == 1, f"legs={[(a, int(c)) for a, c in legs]}")
    check("A6: that leg credits the winner's wallet for the FULL pot",
          legs[0][0] == f"wallet:{teams[0].id}" and int(legs[0][1]) == pot,
          f"{legs[0][0]}={int(legs[0][1])} of {pot}")
    check("A7: distributed equals the pot; nothing rolled",
          result.distributed_cents == pot and result.rolled_over_cents == 0,
          f"distributed={result.distributed_cents} rolled={result.rolled_over_cents}")
    check("A8: the pool account is emptied — no stranded credits",
          db.execute(text("SELECT COALESCE(SUM(amount_cents),0) FROM "
                          "ledger_entries WHERE account = :a"),
                     {"a": f"pool:{league.id}"}).scalar() == 0,
          "pool balance 0")
    db.commit()

check("A9: trial balance is zero", trial_balance() == 0, str(trial_balance()))


# ══════════════════════════════════════════════════════════════════════════════
# CASE B — a GENUINE tie splits between exactly the tied GMs
# ══════════════════════════════════════════════════════════════════════════════

print("\nB · Two subjects genuinely equal — EVEN_SPLIT across exactly those two")

with SessionLocal() as db:
    league, teams = build_league(db, f"b{uuid.uuid4().hex[:6]}")
    lines = {
        1: [line(rush_att=10, rec=5, rush_yds=60, rec_yds=40)],   # 15  tie
        2: [line(rush_att=12, rec=3, rush_yds=10, rec_yds=10)],   # 15  tie
        3: [line(rush_att=2, rec=1, rush_yds=5, rec_yds=5)],      # 3
        4: [line(rush_att=4, rec=1, rush_yds=9, rec_yds=9)],      # 5
    }
    pot = ENTRY_CENTS * len(teams)
    fund_pot(db, league, pot)
    inst = make_instance(db, league, "most_offensive_touches", pot)
    for i, t in enumerate(teams):
        submit_claim(db, pool_instance_id=inst.id, team_id=t.id,
                     subject_id=teams[i].id, now=NOW)
    db.flush()
    src = ProviderWeekStatSource(snapshot(league, teams, lines),
                                 stat_map=_Map()).bind(
        db, build_team_identity_resolver(db, league_id=league.id,
                                         provider=PROVIDER))
    result = settle_pool_instance(db, pool_instance_id=inst.id,
                                  stat_source=src, now=NOW)
    db.flush()

    check("B1: exactly the two genuinely tied subjects win",
          set(result.winning_subject_ids) == {teams[0].id, teams[1].id},
          str(result.winning_subject_ids))
    legs = winner_legs(db, distribution_postings(db, league.id)[0][0])
    check("B2: exactly TWO winner legs", len(legs) == 2,
          f"legs={[(a, int(c)) for a, c in legs]}")
    check("B3: the pot splits evenly and completely",
          sum(int(c) for _, c in legs) == pot
          and {int(c) for _, c in legs} == {pot // 2},
          f"{[int(c) for _, c in legs]} sum={sum(int(c) for _, c in legs)}")
    check("B4: the losing GMs receive nothing",
          all(a not in (f"wallet:{teams[2].id}", f"wallet:{teams[3].id}")
              for a, _ in legs), "no leg for the 3-touch or 5-touch teams")
    db.commit()

check("B5: trial balance is zero", trial_balance() == 0, str(trial_balance()))


# ══════════════════════════════════════════════════════════════════════════════
# CASE C — a winner exists but nobody picked it: zero winning tickets
# ══════════════════════════════════════════════════════════════════════════════

print("\nC · A winner exists, nobody claimed it — rollover, no distribution")

with SessionLocal() as db:
    league, teams = build_league(db, f"c{uuid.uuid4().hex[:6]}")
    lines = {
        1: [line(rush_att=20, rec=10, rush_yds=140, rec_yds=110)],  # 30 <- wins
        2: [line(rush_att=12, rec=6, rush_yds=80, rec_yds=60)],     # 18
        3: [line(rush_att=5, rec=2, rush_yds=20, rec_yds=15)],      # 7
        4: [line(rush_att=9, rec=4, rush_yds=50, rec_yds=40)],      # 13
    }
    pot = ENTRY_CENTS * len(teams)
    fund_pot(db, league, pot)
    inst = make_instance(db, league, "most_offensive_touches", pot)
    # EVERY GM picks team 3 — the genuine winner (team 1) goes unclaimed.
    for t in teams:
        submit_claim(db, pool_instance_id=inst.id, team_id=t.id,
                     subject_id=teams[2].id, now=NOW)
    db.flush()
    src = ProviderWeekStatSource(snapshot(league, teams, lines),
                                 stat_map=_Map()).bind(
        db, build_team_identity_resolver(db, league_id=league.id,
                                         provider=PROVIDER))
    result = settle_pool_instance(db, pool_instance_id=inst.id,
                                  stat_source=src, now=NOW)
    db.flush()

    check("C1: the genuine winner is still identified",
          result.winning_subject_ids == (teams[0].id,),
          str(result.winning_subject_ids))
    check("C2: no GM is paid", result.distributed_cents == 0,
          f"distributed={result.distributed_cents}")
    check("C3: the pot rolls or sweeps in full",
          result.rolled_over_cents + result.swept_to_championship_cents == pot,
          f"rolled={result.rolled_over_cents} "
          f"swept={result.swept_to_championship_cents}")
    check("C4: no winner-distribution posting exists at all",
          len(distribution_postings(db, league.id)) == 0,
          f"{len(distribution_postings(db, league.id))} postings")
    db.commit()

check("C5: trial balance is zero", trial_balance() == 0, str(trial_balance()))


# ══════════════════════════════════════════════════════════════════════════════
# CASE D — a QUALIFIER nobody satisfies, and one everybody does
# ══════════════════════════════════════════════════════════════════════════════

print("\nD · QUALIFIER over derived operands — qualifies only on real data")

with SessionLocal() as db:
    league, teams = build_league(db, f"d{uuid.uuid4().hex[:6]}")
    # No touchdown and no field goal anywhere: nobody can qualify.
    none_qualify = {i: [line(rush_att=6, rec=3, rush_yds=40, rec_yds=25)]
                    for i in range(1, 5)}
    pot = ENTRY_CENTS * len(teams)
    fund_pot(db, league, pot)
    inst = make_instance(db, league, "recorded_both_a_td_and_a_field_goal", pot)
    for i, t in enumerate(teams):
        submit_claim(db, pool_instance_id=inst.id, team_id=t.id,
                     subject_id=teams[i].id, now=NOW)
    db.flush()
    src = ProviderWeekStatSource(snapshot(league, teams, none_qualify),
                                 stat_map=_Map()).bind(
        db, build_team_identity_resolver(db, league_id=league.id,
                                         provider=PROVIDER))
    result = settle_pool_instance(db, pool_instance_id=inst.id,
                                  stat_source=src, now=NOW)
    db.flush()
    check("D1: nobody qualifies -> ZERO_ELIGIBLE_CLAIMS",
          result.classification == "ZERO_ELIGIBLE_CLAIMS",
          result.classification)
    check("D2: nothing is distributed; the pot rolls or sweeps",
          result.distributed_cents == 0
          and result.rolled_over_cents + result.swept_to_championship_cents == pot,
          f"distributed={result.distributed_cents}")
    db.commit()

with SessionLocal() as db:
    league, teams = build_league(db, f"e{uuid.uuid4().hex[:6]}")
    # Only team 2 has BOTH a rushing TD and a made field goal.
    qualify = {
        1: [line(rush_att=6, rec=3, rush_yds=40, rec_yds=25, rtd=1)],
        2: [line(rush_att=6, rec=3, rush_yds=40, rec_yds=25, rtd=1,
                 fg=(0, 1, 0, 0, 0))],
        3: [line(rush_att=6, rec=3, rush_yds=40, rec_yds=25,
                 fg=(0, 1, 0, 0, 0))],
        4: [line(rush_att=6, rec=3, rush_yds=40, rec_yds=25)],
    }
    pot = ENTRY_CENTS * len(teams)
    fund_pot(db, league, pot)
    inst = make_instance(db, league, "recorded_both_a_td_and_a_field_goal", pot)
    for i, t in enumerate(teams):
        submit_claim(db, pool_instance_id=inst.id, team_id=t.id,
                     subject_id=teams[i].id, now=NOW)
    db.flush()
    src = ProviderWeekStatSource(snapshot(league, teams, qualify),
                                 stat_map=_Map()).bind(
        db, build_team_identity_resolver(db, league_id=league.id,
                                         provider=PROVIDER))
    result = settle_pool_instance(db, pool_instance_id=inst.id,
                                  stat_source=src, now=NOW)
    db.flush()
    check("D3: exactly the one genuinely qualifying subject wins",
          result.winning_subject_ids == (teams[1].id,),
          str(result.winning_subject_ids))
    legs = winner_legs(db, distribution_postings(db, league.id)[0][0])
    check("D4: one winner leg, full pot, to that GM",
          len(legs) == 1 and legs[0][0] == f"wallet:{teams[1].id}"
          and int(legs[0][1]) == pot,
          f"legs={[(a, int(c)) for a, c in legs]}")
    db.commit()

check("D5: trial balance is zero", trial_balance() == 0, str(trial_balance()))


# ══════════════════════════════════════════════════════════════════════════════
# E — PROVIDER INDEPENDENCE: both sources normalize through the same helper
# ══════════════════════════════════════════════════════════════════════════════

print("\nE · Both stat sources agree on canonical values for equivalent inputs")

with SessionLocal() as db:
    from db.schema import Player, Projection, Roster
    from betting.pool_subjects import (
        LocalRecordedStatSource, SCOPE_TEAM, WeeklyStructure,
    )

    league, teams = build_league(db, f"eq{uuid.uuid4().hex[:6]}", n_teams=2)
    team = teams[0]
    # ONE recorded fact, expressed the way each source expresses it. Their raw
    # inputs are only equivalent for this operand — the local adaptor has no
    # box score to offer — so this is the whole of the overlap, and it is where
    # the two must agree exactly.
    POINTS = 17.5
    player = Player(name="Equiv One", position="RB", nfl_team="EQV",
                    provider=PROVIDER,
                    provider_player_key=f"{team.provider_team_key}.p0")
    db.add(player)
    db.flush()
    db.add(Roster(team_id=team.id, player_id=player.id, slot="RB"))
    db.add(Projection(player_id=player.id, week=WEEK, season=SEASON,
                      source=league.projection_source, projected_points=0.0,
                      actual_points=POINTS))
    db.flush()

    struct = WeeklyStructure(scope=SCOPE_TEAM,
                             considered_subject_ids=(team.id,))
    local = LocalRecordedStatSource(source=league.projection_source,
                                    season=SEASON).bind(db)
    local_subj = local.subjects_for(league_id=league.id, season=SEASON,
                                    week=WEEK, structure=struct)[0]

    prov_snap = ProviderWeek(
        league=ProviderLeague(provider=PROVIDER,
                              league_key=league.provider_league_key,
                              name=league.name, season=SEASON,
                              current_week=WEEK),
        week=WEEK,
        teams=(ProviderTeam(provider=PROVIDER,
                            team_key=team.provider_team_key,
                            team_id="1", name=team.team_name),),
        matchups=(),
        roster_entries=(ProviderRosterEntry(
            provider=PROVIDER, team_key=team.provider_team_key,
            player_key=f"{team.provider_team_key}.p0",
            player_id="p0", week=WEEK, slot="RB", name="Equiv One"),),
        player_stats=(ProviderPlayerStats(
            provider=PROVIDER, player_key=f"{team.provider_team_key}.p0",
            week=WEEK, values={}, stat_ids_present=frozenset(),
            fantasy_points=POINTS),))
    prov = ProviderWeekStatSource(prov_snap, stat_map=_Map()).bind(
        db, build_team_identity_resolver(db, league_id=league.id,
                                         provider=PROVIDER))
    prov_subj = prov.subjects_for(league_id=league.id, season=SEASON,
                                  week=WEEK, structure=struct)[0]

    lv = dict(local_subj.components[0].values)
    pv = dict(prov_subj.components[0].values)
    check("E1: both sources report the same player_fantasy_points",
          lv.get("player_fantasy_points") == pv.get("player_fantasy_points")
          == POINTS,
          f"local={lv.get('player_fantasy_points')} "
          f"provider={pv.get('player_fantasy_points')}")
    check("E2: NEITHER source invents a derived operand from inputs it never "
          "received",
          not ({"touches", "scrimmage_yards", "offensive_yards"} & set(lv))
          and not ({"touches", "scrimmage_yards", "offensive_yards"} & set(pv)),
          f"local={sorted(lv)} provider={sorted(pv)}")
    db.commit()


print("\n" + "=" * 78)
if _FAILURES:
    print(f"PDS1 ECONOMICS ({DIALECT}): {_PASSES} passed, {len(_FAILURES)} FAILED")
    for f in _FAILURES:
        print(f"   FAILED: {f}")
    sys.exit(1)
print(f"PDS1 ECONOMICS ({DIALECT}): all {_PASSES} assertions PASSED")
