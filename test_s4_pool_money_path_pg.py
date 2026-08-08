"""
test_s4_pool_money_path_pg.py — S4-P1 money path on real PostgreSQL.

Covers Scope §H scenarios 1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 18, 18a, 18b, 18g,
18h, 22 and the Owner Ruling R2 and R3 behaviors.

WHY POSTGRES AND NOT SQLITE. `SELECT ... FOR UPDATE` is a documented no-op on
SQLite, partial unique indexes behave differently, and the concurrency this
package depends on cannot be observed at all on a single-writer file database.
SQLite-only or mocked persistence does NOT close money-path coverage.

EVERY MONEY SCENARIO ASSERTS CONSERVATION, and asserts it from REAL LEDGER
ENTRIES rather than from a status column. `trial_balance()` sums every entry
ever written and must be exactly 0; `assert_pool_conservation` proves the pool
account balance equals the sum of unsettled pots plus live carries. A settlement
that says `settled = true` proves nothing about where the money went.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST — applies its guards, binds DATABASE_URL, imports db.schema.
from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] S4-P1 money-path suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    from betting.pool_claims import PoolClaimError, submit_claim
    from betting.pool_funding import (
        ACTIVE_POOLS_PER_WEEK,
        GOVERNED_DEFAULT_WEEKLY_ENTRY_CENTS,
        PoolFundingError,
        collect_weekly_entries,
        configure_pool_weekly_entry,
    )
    from betting.pool_settlement import (
        EVENT_TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP,
        EVENT_TICKET_ZERO_WINNER_ROLLOVER,
        assert_pool_conservation,
    )
    from db.schema import (
        PoolClaim, PoolDefinition, PoolEconomicEvent, PoolInstance,
        SessionLocal,
    )
    from ledger.ledger import balance_of, trial_balance
    from test_support_s4_pool import (
        FOUR_TEAM_KEYS, PROVIDER, REQUIRED_STAT, DefinitionStatSource,
        make_league, mark_ready, seed_catalog, settle_each, team_subjects,
    )

    SEASON = 2026

    # ── 1. seeding ───────────────────────────────────────────────────────────
    print("\n-- seeding the Rev1.3 catalog (Scope §I step 8) --")
    tdb.reset()
    with SessionLocal() as db:
        stats = seed_catalog(db)
        db.commit()
    with SessionLocal() as db:
        rows = db.query(PoolDefinition).all()
        _assert("80 active definitions seeded", len(rows) == 80, str(len(rows)))
        _assert("seeding is idempotent (re-seed inserts nothing new)",
                _reseed_count(db) == (0, 80))
        db.rollback()
        numbers = {r.catalog_number for r in rows}
        _assert("18d no retired number is seeded",
                not (numbers & {8, 9, 10, 11, 12, 44, 45, 47, 50, 51, 52, 57,
                                81, 82, 88, 96, 97, 98}))
        _assert("18 the 3 product-blocked definitions are seeded as BLOCKED "
                "and remain undrawable",
                sorted(r.catalog_number for r in rows
                       if r.dependency_state == "BLOCKED") == [7, 46, 85])

    # ── 2. the two gates ─────────────────────────────────────────────────────
    print("\n-- 18a/18b/18g: the selector requires BOTH gates --")
    tdb.reset()
    with SessionLocal() as db:
        seed_catalog(db)
        league, teams = make_league(db, name="gates", season=SEASON)
        db.commit()
        league_id, season = league.id, league.season
    with SessionLocal() as db:
        from betting.pool_gates import gate_decisions, selectable_definitions

        # 18b — every gate-1 definition is eligible, but nothing is measured
        # ready. A selector honouring only gate 1 would draw 64 here.
        sel = selectable_definitions(db, league_id=league_id,
                                     provider=PROVIDER, phase="REGULAR")
        decisions = gate_decisions(db, league_id=league_id, provider=PROVIDER,
                                   phase="REGULAR")
        gate1_count = sum(d.gate1_definition_runtime_eligible
                          for d in decisions)
        _assert("18b gate 1 alone passes 64 definitions", gate1_count == 64,
                str(gate1_count))
        _assert("18b with gate 2 unmeasured the selector draws ZERO",
                len(sel) == 0, str(len(sel)))
        _assert("18b every refusal names a gate-2 reason",
                all("NO_READINESS_MEASUREMENT" in d.block_reasons
                    for d in decisions if d.gate1_definition_runtime_eligible))

        # 18g — provider access restored but source population unverified:
        # readiness measured and explicitly NOT ready. Still zero.
        mark_ready(db, league_id=league_id, keys=FOUR_TEAM_KEYS, ready=False)
        db.flush()
        sel = selectable_definitions(db, league_id=league_id,
                                     provider=PROVIDER, phase="REGULAR")
        _assert("18g a measured-but-not-ready gate 2 still draws ZERO",
                len(sel) == 0, str(len(sel)))

        # 18a — the 13 source-incomplete rows are ENABLED; mark them ready and
        # confirm gate 1 still keeps them out.
        incomplete = [r.key for r in db.query(PoolDefinition)
                      .filter(PoolDefinition.dependency_state == "ENABLED",
                              PoolDefinition.source_mapping_complete.is_(False))
                      .all()]
        _assert("18a there are 13 source-incomplete ENABLED definitions",
                len(incomplete) == 13, str(len(incomplete)))
        mark_ready(db, league_id=league_id, keys=incomplete, ready=True)
        db.flush()
        sel_keys = {d.definition_key for d in selectable_definitions(
            db, league_id=league_id, provider=PROVIDER, phase="REGULAR")}
        _assert("18a a definition ENABLED but gate-1 ineligible is never drawn",
                not (sel_keys & set(incomplete)), str(sel_keys & set(incomplete)))

        # Stale measurement is not-ready.
        from datetime import datetime, timedelta, timezone
        mark_ready(db, league_id=league_id, keys=FOUR_TEAM_KEYS, ready=True,
                   measured_at=datetime.now(timezone.utc) - timedelta(days=3))
        db.flush()
        sel_keys = {d.definition_key for d in selectable_definitions(
            db, league_id=league_id, provider=PROVIDER, phase="REGULAR")}
        _assert("a STALE readiness measurement is treated as not-ready",
                not (sel_keys & set(FOUR_TEAM_KEYS)))

        # Now measure them fresh.
        mark_ready(db, league_id=league_id, keys=FOUR_TEAM_KEYS, ready=True)
        db.flush()
        sel_keys = {d.definition_key for d in selectable_definitions(
            db, league_id=league_id, provider=PROVIDER, phase="REGULAR")}
        _assert("both gates true makes exactly the measured set selectable",
                sel_keys == set(FOUR_TEAM_KEYS), str(sorted(sel_keys)))
        _assert("18h the selectable count is the MEASURED set, never 64",
                len(sel_keys) == 4)
        db.rollback()

    # ── 3. collection and division (1, 22) ──────────────────────────────────
    print("\n-- 1/22: fresh week, four occurrences, remainder to championship --")
    tdb.reset()
    league_id, season, team_ids = _fresh_league(SessionLocal, seed_catalog,
                                                make_league, mark_ready,
                                                SEASON, "collect", n_teams=5)
    with SessionLocal() as db:
        # 5 teams x 100 cents = 500; 500 // 4 = 125, remainder 0. Configure 101
        # so the remainder is non-zero: 5 x 101 = 505, 505 // 4 = 126 r 1.
        configure_pool_weekly_entry(db, league_id=league_id, cents=101)
        result = collect_weekly_entries(db, league_id=league_id, week=3,
                                        provider=PROVIDER)
        db.commit()
        _assert("1 exactly four occurrences are created",
                len(result.instance_ids) == ACTIVE_POOLS_PER_WEEK,
                str(len(result.instance_ids)))
        _assert("22 total is one league-level debit per team",
                result.total_cents == 505 and result.teams_charged == 5,
                str(result.total_cents))
        _assert("22 the contribution splits across FOUR, never three",
                result.per_pool_share_cents == 126,
                str(result.per_pool_share_cents))
        _assert("22 the indivisible remainder is 1 cent",
                result.remainder_to_championship_cents == 1)

    with SessionLocal() as db:
        instances = _instances(db, PoolInstance, league_id, 3)
        _assert("1 slots are 1..4 with distinct definitions",
                sorted(i.slot for i in instances) == [1, 2, 3, 4]
                and len({i.definition_key for i in instances}) == 4)
        _assert("1 every drawn definition passed BOTH gates",
                {i.definition_key for i in instances} == set(FOUR_TEAM_KEYS))
        _assert("22 each occurrence holds the equal share",
                {i.pot_cents for i in instances} == {126})
        _assert("22 championship received the remainder exactly once",
                balance_of(f"championship:{league_id}") == 1,
                str(balance_of(f"championship:{league_id}")))
        _assert("22 pool account holds exactly the four shares",
                balance_of(f"pool:{league_id}") == 504,
                str(balance_of(f"pool:{league_id}")))
        events = db.query(PoolEconomicEvent).filter(
            PoolEconomicEvent.league_id == league_id).all()
        _assert("collection and the division remainder are DISTINCT causes",
                sorted(e.event_type for e in events)
                == ["WEEKLY_COLLECTION", "WEEKLY_DIVISION_REMAINDER"])
        _assert("trial balance is zero after collection", trial_balance() == 0)
        _assert("conservation: pool balance == sum of unsettled pots",
                assert_pool_conservation(db, league_id=league_id,
                                         season=season) == 504)
        db.rollback()

    print("\n-- R3: a pick moves no money; a duplicate collection is refused --")
    with SessionLocal() as db:
        before = balance_of(f"pool:{league_id}")
        instance = _instances(db, PoolInstance, league_id, 3)[0]
        submit_claim(db, pool_instance_id=instance.id, team_id=team_ids[0],
                     subject_id=team_ids[1])
        db.commit()
        _assert("R3 submitting a claim moves no money",
                balance_of(f"pool:{league_id}") == before)
        _assert("R3 the claim exists as a claim, not a transaction",
                db.query(PoolClaim).filter(
                    PoolClaim.pool_instance_id == instance.id).count() == 1)

    with SessionLocal() as db:
        try:
            collect_weekly_entries(db, league_id=league_id, week=3,
                                   provider=PROVIDER)
            _assert("a second collection of the same week is refused", False,
                    "did not raise")
        except PoolFundingError as exc:
            _assert("a second collection of the same week is refused",
                    exc.reason == "ALREADY_COLLECTED", exc.reason)
        db.rollback()
    _assert("the refused re-collection moved nothing",
            balance_of(f"pool:{league_id}") == 504)

    print("\n-- one claim per GM per occurrence --")
    with SessionLocal() as db:
        instance = _instances(db, PoolInstance, league_id, 3)[0]
        try:
            submit_claim(db, pool_instance_id=instance.id, team_id=team_ids[0],
                         subject_id=team_ids[2])
            _assert("a duplicate claim is refused", False, "did not raise")
        except PoolClaimError as exc:
            _assert("a duplicate claim is refused",
                    exc.reason == "DUPLICATE_CLAIM", exc.reason)
        db.rollback()
    with SessionLocal() as db:
        instance = _instances(db, PoolInstance, league_id, 3)[0]
        submit_claim(db, pool_instance_id=instance.id, team_id=team_ids[0],
                     subject_id=team_ids[2], replace=True)
        db.commit()
        _assert("replace=True keeps exactly one claim row",
                db.query(PoolClaim).filter(
                    PoolClaim.pool_instance_id == instance.id,
                    PoolClaim.team_id == team_ids[0]).count() == 1)

    # ── 4. governed bound and freeze ─────────────────────────────────────────
    print("\n-- POR §6.1 governed bound and freeze --")
    tdb.reset()
    league_id, season, team_ids = _fresh_league(SessionLocal, seed_catalog,
                                                make_league, mark_ready,
                                                SEASON, "bounds")
    with SessionLocal() as db:
        for bad in (99, 501, 0, -1):
            try:
                configure_pool_weekly_entry(db, league_id=league_id, cents=bad)
                _assert(f"weekly entry {bad} is refused", False, "accepted")
            except PoolFundingError as exc:
                _assert(f"weekly entry {bad} is refused by the §6.1 bound",
                        exc.reason == "ENTRY_OUT_OF_BOUNDS", exc.reason)
        db.rollback()
    with SessionLocal() as db:
        result = collect_weekly_entries(db, league_id=league_id, week=3,
                                        provider=PROVIDER)
        _assert("an unconfigured league uses the governed default of 100",
                result.weekly_entry_cents
                == GOVERNED_DEFAULT_WEEKLY_ENTRY_CENTS)
        db.commit()

    # ── 5. settlement: single winner, tie, zero tickets ──────────────────────
    print("\n-- 12/R2: settlement outcomes --")
    tdb.reset()
    league_id, season, team_ids = _fresh_league(SessionLocal, seed_catalog,
                                                make_league, mark_ready,
                                                SEASON, "settle", n_teams=4)
    with SessionLocal() as db:
        collect_weekly_entries(db, league_id=league_id, week=3,
                               provider=PROVIDER)
        db.commit()

    with SessionLocal() as db:
        instances = _instances(db, PoolInstance, league_id, 3)
        pot = instances[0].pot_cents
        _assert("each of the four pots is funded",
                pot > 0 and all(i.pot_cents == pot for i in instances),
                str([i.pot_cents for i in instances]))

        # Instance 0: single winning subject, exactly one GM picked it.
        # Instance 1: tie between two subjects; three GMs hold winning claims.
        # Instance 2: a winner exists, nobody picked it  -> R2 zero tickets.
        # Instance 3: a winner exists, one GM picked it.
        by_definition = {}
        winners_by_instance = {}
        for idx, instance in enumerate(instances):
            stat = REQUIRED_STAT[instance.definition_key]
            if idx == 1:
                values = {team_ids[0]: 50.0, team_ids[1]: 50.0,
                          team_ids[2]: 10.0, team_ids[3]: 1.0}
                winners_by_instance[instance.id] = [team_ids[0], team_ids[1]]
            else:
                values = {team_ids[0]: 99.0, team_ids[1]: 10.0,
                          team_ids[2]: 5.0, team_ids[3]: 1.0}
                winners_by_instance[instance.id] = [team_ids[0]]
            by_definition[instance.definition_key] = team_subjects(
                _teams(db, league_id), stat=stat, values=values)

        # Claims. Canonical GM ids ascend with team_ids, and the claims are
        # deliberately submitted in DESCENDING order so insertion order and
        # canonical order disagree.
        submit_claim(db, pool_instance_id=instances[0].id,
                     team_id=team_ids[3], subject_id=team_ids[0])
        for team_id in reversed(team_ids[:3]):
            submit_claim(db, pool_instance_id=instances[1].id,
                         team_id=team_id,
                         subject_id=team_ids[0] if team_id != team_ids[2]
                         else team_ids[1])
        # instances[2]: every claim picks a LOSING subject.
        for team_id in team_ids:
            submit_claim(db, pool_instance_id=instances[2].id,
                         team_id=team_id, subject_id=team_ids[3])
        submit_claim(db, pool_instance_id=instances[3].id,
                     team_id=team_ids[1], subject_id=team_ids[0])
        db.commit()

    source = DefinitionStatSource(by_definition)
    with SessionLocal() as db:
        wallets_before = {t: balance_of(f"wallet:{t}") for t in team_ids}
        champ_before = balance_of(f"championship:{league_id}")
        results = settle_each(db, league_id=league_id, week=3, source=source)
        db.commit()

    with SessionLocal() as db:
        instances = _instances(db, PoolInstance, league_id, 3)
        r_by_id = {r.pool_instance_id: r for r in results}

        single = r_by_id[instances[0].id]
        _assert("single winner takes the whole pot",
                single.distributed_cents == pot
                and single.winning_team_ids == (team_ids[3],),
                f"{single.distributed_cents} to {single.winning_team_ids}")
        _assert("12 the single-winner instance did not roll",
                instances[0].rollover_cents == 0)

        tie = r_by_id[instances[1].id]
        _assert("12 a tie settles and NEVER rolls",
                tie.distributed_cents == pot
                and instances[1].rollover_cents == 0)
        _assert("12 every winning claim is paid",
                len(tie.winning_team_ids) == 3, str(tie.winning_team_ids))
        base, rem = divmod(pot, 3)
        # MEASURED FROM THE TIE INSTANCE'S OWN POSTING, not from wallet deltas.
        # A wallet delta over the whole week is not this instance's allocation:
        # a GM who also won a DIFFERENT occurrence in the same settlement run
        # carries both payouts in one balance change, and the §6.3 shares would
        # then read wrong for a reason that has nothing to do with §6.3. The
        # posting legs are the exact per-GM allocation this instance produced.
        paid = _distribution_legs(db, tie.pool_instance_id)
        _assert("12a the §6.3 split is base with base+1 to the lowest ids",
                sorted(paid.values()) == sorted(
                    [base + 1] * rem + [base] * (3 - rem)),
                str(paid))
        _assert("12a the extra cent lands on the LOWEST canonical GM ids",
                all(paid[gm] == base + 1 for gm in sorted(paid)[:rem]),
                str(paid))
        _assert("12c the tie distributed every cent",
                sum(paid.values()) == pot, f"{sum(paid.values())} of {pot}")
        _assert("12b the recipients are exactly the winning GMs, nobody else",
                set(paid) == set(tie.winning_team_ids), str(sorted(paid)))

        zero_ticket = r_by_id[instances[2].id]
        _assert("R2 zero winning tickets is not a winner distribution",
                zero_ticket.distributed_cents == 0
                and zero_ticket.event_type
                in (EVENT_TICKET_ZERO_WINNER_ROLLOVER,
                    EVENT_TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP),
                str(zero_ticket.event_type))
        _assert("R2 a RANK_EXTREMUM definition is not rollover-eligible, so "
                "the complete pot sweeps to championship",
                zero_ticket.swept_to_championship_cents == pot,
                str(zero_ticket.swept_to_championship_cents))
        _assert("R2 the classification stays CLAIMS_PRESENT — a subject DID "
                "win; the zero is at the ticket layer",
                zero_ticket.classification == "CLAIMS_PRESENT")
        _assert("R2 championship received exactly the swept pot",
                balance_of(f"championship:{league_id}") - champ_before == pot)

        _assert("every instance is marked settled in the same transaction as "
                "its posting", all(i.settled for i in instances))
        _assert("conservation: nothing unresolved remains after the week",
                assert_pool_conservation(db, league_id=league_id,
                                         season=season) == 0)
        _assert("the pool account is fully drained",
                balance_of(f"pool:{league_id}") == 0)
        _assert("trial balance is zero after settlement", trial_balance() == 0)
        db.rollback()

    # ── 6. rollover lifecycle (2, 6, 13) ────────────────────────────────────
    print("\n-- 2/6/13: rollover continuation, lineage and final-week expiry --")
    tdb.reset()
    _rollover_scenario(SessionLocal, tdb, SEASON, _assert)

    # ── 7. no-repeat and cycle reset (5, 7, 9) ──────────────────────────────
    print("\n-- 5/7/9: no-repeat, cycle reset and the partial index --")
    tdb.reset()
    _rotation_scenario(SessionLocal, tdb, SEASON, _assert)


# ── helpers ───────────────────────────────────────────────────────────────────

def _distribution_legs(db, pool_instance_id: int) -> dict[int, int]:
    """The per-GM credit legs of one instance's WINNER_DISTRIBUTION posting.

    Resolved through the instance's own economic-event row to its posting_id,
    then to the ledger entries carrying it. That chain is what makes the
    measurement specific to THIS occurrence rather than to the week."""
    from db.schema import PoolEconomicEvent
    from ledger.ledger import LedgerEntry

    event = (db.query(PoolEconomicEvent)
             .filter(PoolEconomicEvent.pool_instance_id == pool_instance_id,
                     PoolEconomicEvent.event_type == "WINNER_DISTRIBUTION")
             .one())
    entries = (db.query(LedgerEntry)
               .filter(LedgerEntry.posting_id == event.posting_id).all())
    return {int(e.account.split(":", 1)[1]): int(e.amount_cents)
            for e in entries if e.account.startswith("wallet:")}


def _reseed_count(db):
    from betting.pool_catalog import seed_definitions
    stats = seed_definitions(db)
    return stats["inserted"], stats["updated"]


def _instances(db, PoolInstance, league_id, week):
    return (db.query(PoolInstance)
            .filter(PoolInstance.league_id == league_id,
                    PoolInstance.week == week)
            .order_by(PoolInstance.slot).all())


def _teams(db, league_id):
    from db.schema import Team
    return (db.query(Team).filter(Team.league_id == league_id)
            .order_by(Team.id).all())


def _fresh_league(SessionLocal, seed_catalog, make_league, mark_ready, season,
                  name, n_teams=4):
    from test_support_s4_pool import FOUR_TEAM_KEYS
    with SessionLocal() as db:
        seed_catalog(db)
        league, teams = make_league(db, name=name, season=season,
                                    n_teams=n_teams)
        mark_ready(db, league_id=league.id, keys=FOUR_TEAM_KEYS)
        db.commit()
        return league.id, league.season, [t.id for t in teams]


def _rollover_scenario(SessionLocal, tdb, season, _assert):
    """The full carry lifecycle at the PRODUCTION slate width of four.

    Covers scenarios 2 (one rollover), 4 (four rollovers, zero fresh draws),
    6 (a continuation is not a repeat), 7 (cycle reset) and 13 (final-week
    expiry).

    THE SLATE IS NEVER NARROWED. Marking exactly four TEAM QUALIFIER
    definitions ready makes every occurrence rollover-capable, so the carry
    lifecycle is observable without changing the four-per-week rule the POR
    fixes. A test that shrank the slate would be exercising a configuration
    production never runs.

    THE FIXTURE STATS ARE CHOSEN SO EACH DEFINITION'S OUTCOME IS DETERMINED BY
    ITS OWN PREDICATE. Every team records one passing, one rushing and one
    receiving touchdown and NO field goal:

        #1 the_grand_slam        needs a field goal -> ZERO qualifiers -> ROLLS
        #2 trifecta              pass+rush+recv     -> every team qualifies
        #3 rush+recv                                -> every team qualifies
        #4 pass+rush                                -> every team qualifies
    """
    from betting.pool_funding import collect_weekly_entries
    from betting.pool_settlement import (
        EVENT_ROLLOVER_EXPIRY_SWEEP, EVENT_SUBJECT_ZERO_CLAIM_ROLLOVER,
        assert_pool_conservation, settle_pool_instance,
    )
    from betting.pool_claims import submit_claim
    from db.schema import PoolInstance, PoolRotationCycle
    from ledger.ledger import balance_of, trial_balance
    from test_support_s4_pool import (
        FOUR_QUALIFIER_KEYS, PROVIDER, QUALIFIER_ALL_STATS,
        DefinitionStatSource, add_week_matchups, add_week_schedule, make_league,
        mark_ready, multi_stat_team_subjects, seed_catalog, settle_each,
    )

    with SessionLocal() as db:
        seed_catalog(db)
        league, teams = make_league(db, name="rollover", season=season,
                                    n_teams=4, season_final_week=5,
                                    playoff_start_week=6)
        mark_ready(db, league_id=league.id, keys=FOUR_QUALIFIER_KEYS)
        for week in (4, 5):
            add_week_schedule(db, season=season, week=week,
                              name="rollover")
            add_week_matchups(db, league_id=league.id, week=week, teams=teams)
        db.commit()
        league_id = league.id
        team_ids = [t.id for t in teams]

    def source_for(per_team_values):
        with SessionLocal() as db:
            rows = _teams(db, league_id)
            subjects = multi_stat_team_subjects(
                rows, per_team={t.id: per_team_values for t in rows},
                covered=QUALIFIER_ALL_STATS)
            db.rollback()
        return DefinitionStatSource({k: subjects for k in FOUR_QUALIFIER_KEYS})

    TD_NO_FG = {"passing_td": 1.0, "rushing_td": 1.0, "receiving_td": 1.0,
                "field_goals_made": 0.0, "total_touchdown_credits": 3.0}
    NOTHING = {s: 0.0 for s in QUALIFIER_ALL_STATS}

    # ── week 3 ──────────────────────────────────────────────────────────────
    with SessionLocal() as db:
        collect_weekly_entries(db, league_id=league_id, week=3,
                               provider=PROVIDER)
        db.commit()
    with SessionLocal() as db:
        inst = _instances(db, PoolInstance, league_id, 3)
        share = inst[0].pot_cents
        _assert("the rollover scenario runs at the full width of four",
                len(inst) == 4 and {i.definition_key for i in inst}
                == set(FOUR_QUALIFIER_KEYS))
        for i in inst:
            submit_claim(db, pool_instance_id=i.id, team_id=team_ids[0],
                         subject_id=team_ids[0])
        db.commit()

    with SessionLocal() as db:
        results = settle_each(db, league_id=league_id, week=3,
                              source=source_for(TD_NO_FG))
        db.commit()
    rolled = [r for r in results
              if r.event_type == EVENT_SUBJECT_ZERO_CLAIM_ROLLOVER]
    distributed = [r for r in results if r.distributed_cents > 0]
    _assert("2 exactly one occurrence rolls (the one needing a field goal)",
            len(rolled) == 1 and rolled[0].definition_key == "the_grand_slam",
            str([(r.definition_key, r.event_type) for r in results]))
    _assert("17 the roll is classified ZERO_ELIGIBLE_CLAIMS at the SUBJECT "
            "layer", rolled[0].classification == "ZERO_ELIGIBLE_CLAIMS")
    _assert("a rollover generates NO posting",
            rolled[0].swept_to_championship_cents == 0
            and rolled[0].distributed_cents == 0)
    _assert("2 the other three settle and distribute", len(distributed) == 3)
    with SessionLocal() as db:
        _assert("conservation: only the live carry remains unresolved",
                assert_pool_conservation(db, league_id=league_id,
                                         season=season) == share,
                str(share))
        _assert("trial balance is zero after week 3", trial_balance() == 0)
        db.rollback()

    # ── week 4: the carry occupies a slot; three fresh draws fill the rest ──
    with SessionLocal() as db:
        collect_weekly_entries(db, league_id=league_id, week=4,
                               provider=PROVIDER)
        db.commit()
    with SessionLocal() as db:
        w3 = _instances(db, PoolInstance, league_id, 3)
        w4 = _instances(db, PoolInstance, league_id, 4)
        carry = [i for i in w4 if i.origin_instance_id is not None]
        origin = {i.id: i for i in w3}
        _assert("2 the continuation occupies slot 1, ahead of fresh draws",
                len(carry) == 1 and carry[0].slot == 1)
        _assert("2 lineage points at the originating instance",
                carry[0].origin_instance_id in origin
                and origin[carry[0].origin_instance_id].definition_key
                == carry[0].definition_key)
        _assert("2 the carried cents are intact PLUS this week's share",
                carry[0].pot_cents == share * 2, str(carry[0].pot_cents))
        _assert("10g the origin's carry is consumed exactly once",
                origin[carry[0].origin_instance_id].rollover_cents == 0)
        _assert("1 the week is still exactly four occurrences", len(w4) == 4)
        _assert("6 the carried key is NOT also drawn fresh in the same week",
                sum(1 for i in w4
                    if i.definition_key == carry[0].definition_key) == 1)
        _assert("7 the cycle reset fired and was audited",
                {i.rotation_cycle for i in w4} == {2}
                and db.query(PoolRotationCycle).filter(
                    PoolRotationCycle.league_id == league_id).count() == 2)
        _assert("8 the carry survived the cycle increment",
                carry[0].rotation_cycle == 2)
        db.rollback()

    # ── week 4 settles with nothing qualifying: all four roll ───────────────
    with SessionLocal() as db:
        settle_each(db, league_id=league_id, week=4, source=source_for(NOTHING))
        db.commit()
    with SessionLocal() as db:
        w4 = _instances(db, PoolInstance, league_id, 4)
        _assert("all four rollover-eligible occurrences carry forward",
                all(i.rollover_cents > 0 for i in w4))
        _assert("conservation: the pool holds exactly the four carries",
                assert_pool_conservation(db, league_id=league_id,
                                         season=season)
                == sum(i.rollover_cents for i in w4))
        db.rollback()

    # ── week 5: four continuations, zero fresh draws ────────────────────────
    with SessionLocal() as db:
        collect_weekly_entries(db, league_id=league_id, week=5,
                               provider=PROVIDER)
        db.commit()
    with SessionLocal() as db:
        w5 = _instances(db, PoolInstance, league_id, 5)
        _assert("4 four rollovers is a valid slate with ZERO fresh draws",
                len(w5) == 4
                and all(i.origin_instance_id is not None for i in w5))
        _assert("4 there is no fifth slot",
                sorted(i.slot for i in w5) == [1, 2, 3, 4])
        expected_pot = sum(i.pot_cents for i in w5)
        db.rollback()

    champ_before = balance_of(f"championship:{league_id}")
    with SessionLocal() as db:
        results = settle_each(db, league_id=league_id, week=5,
                              source=source_for(NOTHING))
        db.commit()
    _assert("13 expiry fires at season_final_week, never a hardcoded 14",
            all(r.event_type == EVENT_ROLLOVER_EXPIRY_SWEEP for r in results),
            str([r.event_type for r in results]))
    _assert("13 the complete accumulated carry sweeps to championship once",
            balance_of(f"championship:{league_id}") - champ_before
            == expected_pot, str(expected_pot))
    _assert("13 no carry survives the expiry",
            all(r.rolled_over_cents == 0 for r in results))
    with SessionLocal() as db:
        _assert("13 nothing unresolved remains for the season",
                assert_pool_conservation(db, league_id=league_id,
                                         season=season) == 0)
        _assert("13 the pool account is fully drained",
                balance_of(f"pool:{league_id}") == 0)
        _assert("13 trial balance is zero", trial_balance() == 0)
        db.rollback()


def _rotation_scenario(SessionLocal, tdb, season, _assert):
    """No-repeat within a cycle, and the reset that fires only when the
    remaining eligible set cannot fill the fresh slots."""
    from betting.pool_slate import build_and_persist_slate
    from db.schema import PoolInstance, PoolRotationCycle
    from sqlalchemy.exc import IntegrityError
    from test_support_s4_pool import (
        FOUR_TEAM_KEYS, PROVIDER, add_week_matchups, add_week_schedule,
        make_league, mark_ready, seed_catalog,
    )

    with SessionLocal() as db:
        seed_catalog(db)
        league, teams = make_league(db, name="rotation", season=season)
        # Exactly two definitions are ready, and the slate is two wide, so the
        # cycle is exhausted after ONE week and week 2 must reset.
        mark_ready(db, league_id=league.id, keys=FOUR_TEAM_KEYS[:2])
        for week in (4, 5):
            add_week_schedule(db, season=season, week=week,
                              name="rotation")
            add_week_matchups(db, league_id=league.id, week=week, teams=teams)
        db.commit()
        league_id = league.id

    with SessionLocal() as db:
        league = db.query(type(league)).filter_by(id=league_id).first()
        first = build_and_persist_slate(db, league=league, season=season,
                                        week=3, phase="REGULAR",
                                        provider=PROVIDER, slot_count=2)
        db.commit()
        _assert("7 cycle 1 is opened and audited",
                db.query(PoolRotationCycle).filter(
                    PoolRotationCycle.league_id == league_id).count() == 1)
        _assert("a two-wide slate draws two distinct fresh definitions",
                first.fresh_count == 2 and not first.reset_performed)

    with SessionLocal() as db:
        league = db.query(type(league)).filter_by(id=league_id).first()
        second = build_and_persist_slate(db, league=league, season=season,
                                         week=4, phase="REGULAR",
                                         provider=PROVIDER, slot_count=2)
        db.commit()
        _assert("7 the reset fires at the draw that cannot be satisfied",
                second.reset_performed and second.rotation_cycle == 2)
        cycles = db.query(PoolRotationCycle).filter(
            PoolRotationCycle.league_id == league_id).all()
        _assert("7 the reset is audited with exactly one new row",
                len(cycles) == 2
                and {c.rotation_cycle for c in cycles} == {1, 2})
        _assert("7 the audit row records the opening week and eligible size",
                any(c.rotation_cycle == 2 and c.opened_week == 4
                    and c.eligible_set_size == 2 for c in cycles))

    with SessionLocal() as db:
        w3 = {i.definition_key for i in _instances(db, PoolInstance,
                                                   league_id, 3)}
        w4 = {i.definition_key for i in _instances(db, PoolInstance,
                                                   league_id, 4)}
        _assert("no regular-season repeat occurred WITHIN cycle 1",
                len(w3) == 2)
        _assert("the new cycle may legitimately redraw the same keys",
                w4 == w3)
        cycles = {i.rotation_cycle for i in _instances(db, PoolInstance,
                                                       league_id, 4)}
        _assert("week 4's instances carry the incremented cycle",
                cycles == {2})
        db.rollback()

    print("  -- 5: the partial unique index REFUSES a repeat fresh draw --")
    with SessionLocal() as db:
        row = _instances(db, PoolInstance, league_id, 3)[0]
        clash = PoolInstance(
            league_id=league_id, season=season, week=9, phase="REGULAR",
            rotation_cycle=row.rotation_cycle,
            definition_key=row.definition_key, slot=1, pot_cents=0,
            rollover_cents=0, origin_instance_id=None, settled=False,
            distributed_cents=0)
        db.add(clash)
        try:
            db.flush()
            _assert("5 a second FRESH draw of a used key in one cycle is "
                    "refused by the database", False, "the insert succeeded")
        except IntegrityError:
            _assert("5 a second FRESH draw of a used key in one cycle is "
                    "refused by the database", True,
                    "uq_pool_instance_cycle_fresh")
        db.rollback()

    with SessionLocal() as db:
        row = _instances(db, PoolInstance, league_id, 3)[0]
        continuation = PoolInstance(
            league_id=league_id, season=season, week=9, phase="REGULAR",
            rotation_cycle=row.rotation_cycle,
            definition_key=row.definition_key, slot=1, pot_cents=0,
            rollover_cents=0, origin_instance_id=row.id, settled=False,
            distributed_cents=0)
        db.add(continuation)
        try:
            db.flush()
            _assert("6 a CONTINUATION of the same key in the same cycle is "
                    "accepted", True)
        except IntegrityError as exc:
            _assert("6 a CONTINUATION of the same key in the same cycle is "
                    "accepted", False, str(exc)[:120])
        db.rollback()


if __name__ == "__main__":
    print("\n=== S4-P1 Pool money-path suite (PostgreSQL) ===")
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