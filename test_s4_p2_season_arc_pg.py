"""
test_s4_p2_season_arc_pg.py — whole-season conservation exit test (S4-P2 §4).

ONE COMPACT REGULAR SEASON, EVERY ECONOMIC PATH, ONE ARITHMETIC PROOF.

The slate is pinned to four definitions chosen so that a SINGLE week exercises
all four settlement outcomes simultaneously, driven only by each definition's
own governed rule against one shared set of recorded facts:

    #1  the_grand_slam      QUALIFIER, rollover-eligible, needs a field goal
                            -> no team qualifies      -> SUBJECT rollover
    #2  trifecta            QUALIFIER, rollover-eligible, three TD types
                            -> every team qualifies, a GM claimed one
                                                      -> WINNER distribution
    #20 most_passing_yards  RANK_EXTREMUM, NOT rollover-eligible
                            -> a winner exists, a GM claimed it
                                                      -> WINNER distribution
    #21 most_rushing_yards  RANK_EXTREMUM, NOT rollover-eligible
                            -> a winner exists, every claim picked a LOSER
                                                      -> TICKET-ZERO sweep

Nothing is special-cased to produce those outcomes: every team is given one
passing, one rushing and one receiving touchdown and NO field goal, and the
yardage differs per team. The engine's own metadata decides the rest.

Across weeks the #1 carry accumulates as a continuation, and at
`season_final_week` it expires and sweeps — closing the season with an empty
pool account.

THE CONSERVATION CLAIM IS ARITHMETIC, NOT A STATUS CHECK. At every material
step `trial_balance()` must be exactly 0 and `assert_pool_conservation` must
equal the live carry. At season close the pool account must be exactly 0 and
every cent collected must be accounted for as distributed-to-GMs plus
swept-to-championship.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] S4-P2 season-arc suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


ARC_KEYS = (
    "the_grand_slam",                          # #1  QUALIFIER, rolls
    "passing_rushing_receiving_td_trifecta",   # #2  QUALIFIER, winner
    "most_passing_yards",                      # #20 RANK, winner
    "most_rushing_yards",                      # #21 RANK, ticket-zero sweep
)
ARC_STATS = ("passing_td", "rushing_td", "receiving_td", "field_goals_made",
             "total_touchdown_credits", "passing_yards", "rushing_yards")

FIRST_WEEK = 3
FINAL_WEEK = 6


def main(tdb) -> None:
    from betting.pool_funding import collect_weekly_entries
    from betting.pool_claims import submit_claim
    from betting.pool_settlement import (
        EVENT_ROLLOVER_EXPIRY_SWEEP, EVENT_SUBJECT_ZERO_CLAIM_ROLLOVER,
        EVENT_TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP, EVENT_WINNER_DISTRIBUTION,
        assert_pool_conservation,
    )
    from db.schema import PoolEconomicEvent, PoolInstance, SessionLocal, Team
    from ledger.ledger import balance_of, trial_balance
    from test_support_s4_pool import (
        PROVIDER, DefinitionStatSource, add_week_matchups, add_week_schedule,
        make_league, mark_ready, multi_stat_team_subjects, seed_catalog,
        settle_each_isolated,
    )

    SEASON = 2026
    tdb.reset()

    with SessionLocal() as db:
        seed_catalog(db)
        league, teams = make_league(db, name="arc", season=SEASON, n_teams=4,
                                    wallet_cents=500_000, week=FIRST_WEEK,
                                    season_final_week=FINAL_WEEK,
                                    playoff_start_week=FINAL_WEEK + 1)
        mark_ready(db, league_id=league.id, keys=ARC_KEYS)
        for week in range(FIRST_WEEK + 1, FINAL_WEEK + 1):
            add_week_schedule(db, season=SEASON, week=week, name="arc")
            add_week_matchups(db, league_id=league.id, week=week, teams=teams)
        db.commit()
        league_id = league.id
        team_ids = [t.id for t in teams]

    # One passing/rushing/receiving TD each and NO field goal, with yardage
    # that makes team_ids[0] the unique extremum on both RANK definitions.
    per_team = {}
    for index, team_id in enumerate(team_ids):
        per_team[team_id] = {
            "passing_td": 1.0, "rushing_td": 1.0, "receiving_td": 1.0,
            "field_goals_made": 0.0, "total_touchdown_credits": 3.0,
            "passing_yards": 300.0 if index == 0 else float(100 + index),
            "rushing_yards": 200.0 if index == 0 else float(50 + index),
        }

    def source_for(db):
        rows = (db.query(Team).filter(Team.league_id == league_id)
                .order_by(Team.id).all())
        subjects = multi_stat_team_subjects(rows, per_team=per_team,
                                            covered=ARC_STATS)
        return DefinitionStatSource({k: subjects for k in ARC_KEYS})

    collected_total = 0
    weekly = {}

    for week in range(FIRST_WEEK, FINAL_WEEK + 1):
        print(f"\n-- week {week} --")
        with SessionLocal() as db:
            result = collect_weekly_entries(db, league_id=league_id, week=week,
                                            provider=PROVIDER)
            db.commit()
            collected_total += result.total_cents
            weekly[week] = result
        _assert(f"w{week} collection charges the league once and splits by 4",
                result.teams_charged == 4
                and result.per_pool_share_cents * 4
                + result.remainder_to_championship_cents
                == result.total_cents,
                f"{result.total_cents} = {result.per_pool_share_cents}x4 + "
                f"{result.remainder_to_championship_cents}")
        _assert(f"w{week} trial balance is zero after collection",
                trial_balance() == 0)

        with SessionLocal() as db:
            rows = (db.query(PoolInstance)
                    .filter(PoolInstance.league_id == league_id,
                            PoolInstance.week == week)
                    .order_by(PoolInstance.slot).all())
            _assert(f"w{week} exactly four occurrences", len(rows) == 4,
                    str(len(rows)))
            _assert(f"w{week} the slate is the four pinned definitions",
                    {r.definition_key for r in rows} == set(ARC_KEYS))

            # Claims: a winning pick on #2 and #20; a deliberately LOSING pick
            # on #21 so its winner goes unclaimed; #1 needs none (no subject
            # will qualify).
            for row in rows:
                if row.definition_key == "most_rushing_yards":
                    submit_claim(db, pool_instance_id=row.id,
                                 team_id=team_ids[1],
                                 subject_id=team_ids[3])       # a loser
                elif row.definition_key != "the_grand_slam":
                    submit_claim(db, pool_instance_id=row.id,
                                 team_id=team_ids[1],
                                 subject_id=team_ids[0])       # the winner
            db.commit()
            expected_conservation = assert_pool_conservation(
                db, league_id=league_id, season=SEASON)

        _assert(f"w{week} a claim moved no money",
                assert_conservation_unchanged(SessionLocal, league_id, SEASON,
                                              expected_conservation))

        with SessionLocal() as db:
            settled, refused, container = settle_each_isolated(
                db, league_id=league_id, week=week, source=source_for(db))
            db.commit()

        by_event = {}
        for r in settled:
            by_event.setdefault(r.event_type, []).append(r.definition_key)
        _assert(f"w{week} nothing refuses on a complete field",
                len(refused) == 0, str([x.classification for x in refused]))
        _assert(f"w{week} the week container settles", container is True)
        _assert(f"w{week} two winner distributions",
                sorted(by_event.get(EVENT_WINNER_DISTRIBUTION, [])) ==
                ["most_passing_yards",
                 "passing_rushing_receiving_td_trifecta"],
                str(by_event))

        if week < FINAL_WEEK:
            _assert(f"w{week} subject-level rollover on the qualifier that "
                    "nobody satisfied",
                    by_event.get(EVENT_SUBJECT_ZERO_CLAIM_ROLLOVER)
                    == ["the_grand_slam"], str(by_event))
        else:
            _assert(f"w{week} terminal rollover expiry at season_final_week",
                    by_event.get(EVENT_ROLLOVER_EXPIRY_SWEEP)
                    == ["the_grand_slam"], str(by_event))
        _assert(f"w{week} bettor-level zero-winning-ticket sweep on the "
                "unclaimed RANK winner",
                by_event.get(EVENT_TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP)
                == ["most_rushing_yards"], str(by_event))

        with SessionLocal() as db:
            live_carry = assert_pool_conservation(db, league_id=league_id,
                                                  season=SEASON)
            _assert(f"w{week} conservation holds after settlement",
                    live_carry == balance_of(f"pool:{league_id}"),
                    f"{live_carry} vs {balance_of(f'pool:{league_id}')}")
            db.rollback()
        _assert(f"w{week} trial balance is zero after settlement",
                trial_balance() == 0)

        # Idempotency inside the arc: replay the whole week.
        with SessionLocal() as db:
            replayed, refused2, _ = settle_each_isolated(
                db, league_id=league_id, week=week, source=source_for(db))
            db.commit()
        _assert(f"w{week} a replay of the settled week reposts nothing",
                len(refused2) == 0 and all(r.replayed for r in replayed),
                str([(r.definition_key, r.replayed) for r in replayed]))
        _assert(f"w{week} trial balance is zero after the replay",
                trial_balance() == 0)

    # ── continuation lineage ────────────────────────────────────────────────
    print("\n-- continuation lineage --")
    with SessionLocal() as db:
        carries = (db.query(PoolInstance)
                   .filter(PoolInstance.league_id == league_id,
                           PoolInstance.definition_key == "the_grand_slam")
                   .order_by(PoolInstance.week).all())
        _assert("the rolling definition appears once per week",
                len(carries) == FINAL_WEEK - FIRST_WEEK + 1, str(len(carries)))
        _assert("every week after the first is a continuation with lineage",
                all(c.origin_instance_id is not None for c in carries[1:])
                and carries[0].origin_instance_id is None,
                str([(c.week, c.origin_instance_id) for c in carries]))
        _assert("the carry accumulates monotonically",
                all(carries[i].pot_cents < carries[i + 1].pot_cents
                    for i in range(len(carries) - 1)),
                str([(c.week, c.pot_cents) for c in carries]))
        _assert("the final-week carry is fully released",
                carries[-1].rollover_cents == 0)
        db.rollback()

    # ── season close ────────────────────────────────────────────────────────
    print("\n-- season close --")
    pool_final = balance_of(f"pool:{league_id}")
    champ_final = balance_of(f"championship:{league_id}")
    wallets_final = sum(balance_of(f"wallet:{t}") for t in team_ids)

    with SessionLocal() as db:
        distributed = sum(
            int(e.amount_cents) for e in db.query(PoolEconomicEvent).filter(
                PoolEconomicEvent.league_id == league_id,
                PoolEconomicEvent.event_type == EVENT_WINNER_DISTRIBUTION))
        swept = sum(
            int(e.amount_cents) for e in db.query(PoolEconomicEvent).filter(
                PoolEconomicEvent.league_id == league_id,
                PoolEconomicEvent.event_type.in_((
                    EVENT_TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP,
                    EVENT_ROLLOVER_EXPIRY_SWEEP))))
        remainder = sum(
            int(e.amount_cents) for e in db.query(PoolEconomicEvent).filter(
                PoolEconomicEvent.league_id == league_id,
                PoolEconomicEvent.event_type == "WEEKLY_DIVISION_REMAINDER"))
        unresolved = assert_pool_conservation(db, league_id=league_id,
                                              season=SEASON)
        db.rollback()

    _assert("season close: the pool account is EXACTLY zero",
            pool_final == 0, str(pool_final))
    _assert("season close: zero unresolved Pool economic balance",
            unresolved == 0, str(unresolved))
    _assert("season close: every collected cent is accounted for",
            distributed + swept + remainder == collected_total,
            f"distributed {distributed} + swept {swept} + remainder "
            f"{remainder} = {distributed + swept + remainder}, collected "
            f"{collected_total}")
    _assert("season close: championship holds the swept cents plus remainders",
            champ_final == swept + remainder,
            f"{champ_final} vs {swept + remainder}")
    _assert("season close: trial balance is exactly zero", trial_balance() == 0)
    print(f"\n    collected   {collected_total:>8} cents")
    print(f"    distributed {distributed:>8}")
    print(f"    swept       {swept:>8}")
    print(f"    remainder   {remainder:>8}")
    print(f"    pool        {pool_final:>8}")
    print(f"    championship{champ_final:>8}")
    print(f"    wallets     {wallets_final:>8}")


def assert_conservation_unchanged(SessionLocal, league_id, season,
                                  expected) -> bool:
    from betting.pool_settlement import assert_pool_conservation
    with SessionLocal() as db:
        value = assert_pool_conservation(db, league_id=league_id, season=season)
        db.rollback()
    return value == expected


if __name__ == "__main__":
    print("\n=== S4-P2 whole-season conservation arc (PostgreSQL) ===")
    try:
        main(tdb)
    finally:
        tdb.teardown()
    print(f"\n  {len(_failures)} failure(s)")
    if _failures:
        for f in _failures:
            print(f"    FAILED: {f}")
        sys.exit(1)
    print("  ALL PASS")