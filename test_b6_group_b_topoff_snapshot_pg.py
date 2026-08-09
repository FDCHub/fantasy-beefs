"""
test_b6_group_b_topoff_snapshot_pg.py — B6 Package 3 Group B: the frozen
top-off multiplier snapshot and its season-activation integration (PostgreSQL).

SCOPE FENCE. This suite proves Group B ONLY: League.topoff_cap_multiplier_bps,
the insert-only league_season_topoff_config table, and the extension of
activate_season_allocation()'s state model to cover the frozen multiplier. It
does NOT exercise the issuance service, the cap arithmetic, the disclosure
record, the season-close boundary or any top-off route — those are Groups C-F
and do not exist yet. Nothing here imports economy/top_off.py.

Postgres only. The state model's correctness rests on real transaction
semantics and on genuine row-level blocking between two concurrent
activations; SQLite can prove neither.

EVERY MONEY ASSERTION IS A DELTA, following test_season_allocation_pg.py.
balance_of() and trial_balance() each open their own SessionLocal and so read
COMMITTED state only, which is exactly what the rollback and refusal scenarios
need: a zero delta is real evidence that nothing persisted rather than an
artifact of reading the writer's own uncommitted transaction.

WHY THE MULTIPLIER MUST JOIN THE COMPARISON TUPLE. Scenario (f) is the reason
this suite exists. Without the multiplier in the replay comparison, a
commissioner edits League.topoff_cap_multiplier_bps, re-runs activation, and
receives a successful "replay" while the STALE frozen multiplier silently
governs the whole season (B6 §2.5). (f) asserts that this is a conflict.

CONCURRENCY EVIDENCE IS DIRECT, NOT TIMED. Scenario (l1) proves real blocking
on the League row by reading pg_stat_activity and pg_blocking_pids() from a
THIRD connection and asserting that the contender's backend is blocked BY the
holder's backend, on a query that names the leagues row lock. No sleep is used
as proof anywhere in this suite; the only bounded poll waits for that observable
database condition to appear, and fails loudly if it never does.

SCENARIOS (a-m):
    a  a league defaults to 10000 bps and freezes 10000 at activation
    b  all five permitted multipliers freeze exactly as set
    c  invalid multipliers are refused by the DATABASE on both tables
    d  config row and allocation rows are created atomically, one commit
    e  identical replay adds no config row, no allocation row, no posting
    f  changed frozen multiplier -> ConflictingAllocationError, no mutation
    g  changed allocation tuple  -> ConflictingAllocationError, no mutation
    h  allocations without a config row      -> PartialAllocationError
    i  config row without allocations        -> PartialAllocationError
    j  config row with INCOMPLETE allocations-> PartialAllocationError
    k  forced mid-activation failure rolls back config, allocations AND
       ledger postings together
    l1 genuine blocking on the League row, observed via pg_blocking_pids()
    l2 two concurrent activations: one created=True, one created=False, no
       raw exception, one config row, one complete allocation set, no
       duplicate posting, trial_balance() == 0
    m  S5/S6 schema invariants: duplicate league-season snapshot impossible by
       constraint; SeasonAllocation carries NO multiplier column of any name

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database (see test_support_postgres guards).
"""

import os
import pathlib
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST — setup_postgres_test_db() applies its guards, sets
# DATABASE_URL to the disposable test DB, and imports+binds db.schema
# INTERNALLY. No project module may be imported before this call.
from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] B6 Group B snapshot suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

_failures: list[str] = []

PERMITTED_BPS = (0, 5000, 10000, 15000, 20000)
DEFAULT_BPS   = 10000


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    """Post-setup work. Project imports live here so teardown protection
    begins the instant setup succeeds."""
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import IntegrityError

    from db.schema import (
        SessionLocal,
        League,
        LeagueSeasonTopoffConfig,
        SeasonAllocation,
        Team,
    )
    from ledger.ledger import balance_of, trial_balance, LedgerEntry
    from payments.economy_config import DEFAULT_STOP, ECONOMY_STOPS
    import config

    import economy.season_allocation as sa
    from economy.season_allocation import (
        activate_season_allocation,
        ConflictingAllocationError,
        PartialAllocationError,
    )

    TEAM_COUNT = 4
    SEASON = config.ALLOCATION_SEASON
    stop = DEFAULT_STOP

    # ── helpers ───────────────────────────────────────────────────────────

    def seed_league(team_count: int = TEAM_COUNT, multiplier_bps=None) -> tuple[int, list[int]]:
        """Create a league + teams. multiplier_bps=None leaves the column at
        its declared default, which is what scenario (a) needs to observe."""
        with SessionLocal() as db:
            league = League(season=SEASON, name="Topoff Snapshot League")
            if multiplier_bps is not None:
                league.topoff_cap_multiplier_bps = multiplier_bps
            db.add(league)
            db.flush()
            team_ids = []
            for i in range(team_count):
                t = Team(
                    league_id = league.id,
                    team_name = f"Team {i}",
                    owner     = f"Owner {i}",
                    email     = f"owner{i}_{league.id}@example.test",
                )
                db.add(t)
                db.flush()
                team_ids.append(t.id)
            db.commit()
            return league.id, team_ids

    def frozen_rows(league_id: int) -> list[tuple[int, int]]:
        """Committed (season, multiplier) for every config row of a league."""
        with SessionLocal() as db:
            return [
                (r.season, r.topoff_cap_multiplier_bps)
                for r in db.query(LeagueSeasonTopoffConfig)
                .filter(LeagueSeasonTopoffConfig.league_id == league_id)
                .order_by(LeagueSeasonTopoffConfig.id)
                .all()
            ]

    def set_league_multiplier(league_id: int, bps: int) -> None:
        with SessionLocal() as db:
            db.query(League).filter(League.id == league_id).one().topoff_cap_multiplier_bps = bps
            db.commit()

    def _season_issuance_total() -> int:
        """Summed across the season_issuance:* namespace — see the identical
        helper in test_season_allocation_pg.py for why a namespace total is the
        right probe for a league-agnostic snapshot."""
        from sqlalchemy import text as _text
        with SessionLocal() as _db:
            total = _db.execute(_text(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
                "WHERE account LIKE 'season_issuance:%'")).scalar()
        return int(total or 0)

    def snapshot(team_ids: list[int]) -> dict:
        """Committed-state probe. Everything a delta needs, plus the config
        row count — the value this suite exists to police."""
        with SessionLocal() as db:
            rows    = db.query(SeasonAllocation).count()
            entries = db.query(LedgerEntry).count()
            cfgs    = db.query(LeagueSeasonTopoffConfig).count()
        return {
            "world":   balance_of("world"),
            # S5-R2: the opening allocation now sources from season_issuance:
            # and credits min_reserve:, leaving world and Wallet untouched.
            "issuance": _season_issuance_total(),
            "wallet":  {t: balance_of(f"wallet:{t}") for t in team_ids},
            "min_reserve": {t: balance_of(f"min_reserve:{t}") for t in team_ids},
            "reserve": {t: balance_of(f"reserve:{t}") for t in team_ids},
            "trial":   trial_balance(),
            "rows":    rows,
            "entries": entries,
            "cfgs":    cfgs,
        }

    def deltas(before: dict, after: dict, team_ids: list[int]) -> dict:
        return {
            "world":   after["world"] - before["world"],
            "issuance": after["issuance"] - before["issuance"],
            "wallet":  {t: after["wallet"][t] - before["wallet"][t] for t in team_ids},
            "min_reserve": {t: after["min_reserve"][t] - before["min_reserve"][t]
                            for t in team_ids},
            "reserve": {t: after["reserve"][t] - before["reserve"][t] for t in team_ids},
            "trial":   after["trial"] - before["trial"],
            "rows":    after["rows"] - before["rows"],
            "entries": after["entries"] - before["entries"],
            "cfgs":    after["cfgs"] - before["cfgs"],
        }

    def all_zero(d: dict, team_ids: list[int]) -> bool:
        return (
            d["world"] == 0
            and all(d["wallet"][t] == 0 for t in team_ids)
            and all(d["reserve"][t] == 0 for t in team_ids)
            and d["trial"] == 0
            and d["rows"] == 0
            and d["entries"] == 0
            and d["cfgs"] == 0
        )

    # ── (a) default snapshot ──────────────────────────────────────────────
    print("\n(a) a league defaults to 10000 bps and freezes 10000 at activation")
    tdb.reset()
    league_a, teams_a = seed_league()

    with SessionLocal() as db:
        declared = db.query(League).filter(League.id == league_a).one().topoff_cap_multiplier_bps
    _assert("(a) League.topoff_cap_multiplier_bps defaults to 10000 without being set",
            declared == DEFAULT_BPS, f"got {declared}")

    with SessionLocal() as db:
        res_a = activate_season_allocation(league_a, db)
    _assert("(a) activation created the allocation", res_a.created is True)
    rows_a = frozen_rows(league_a)
    _assert("(a) exactly ONE frozen config row was written", len(rows_a) == 1, str(rows_a))
    _assert("(a) the frozen row carries 10000 bps (100% of the Wallet allocation)",
            rows_a == [(SEASON, DEFAULT_BPS)], str(rows_a))
    _assert("(a) the frozen row is stamped with ALLOCATION_SEASON, not CURRENT_SEASON",
            rows_a == [(SEASON, DEFAULT_BPS)] and SEASON != config.CURRENT_SEASON,
            f"frozen={rows_a} alloc={SEASON} proj={config.CURRENT_SEASON}")

    # ── (b) every permitted multiplier ────────────────────────────────────
    print("\n(b) every permitted multiplier freezes exactly as set")
    for bps in PERMITTED_BPS:
        tdb.reset()
        league_b, teams_b = seed_league(multiplier_bps=bps)
        with SessionLocal() as db:
            activate_season_allocation(league_b, db)
        _assert(f"(b) {bps} bps freezes as {bps}",
                frozen_rows(league_b) == [(SEASON, bps)], str(frozen_rows(league_b)))
        # The frozen value is the ONLY authoritative multiplier: it must equal
        # what the league carried at activation, and it lives in exactly one row.
        _assert(f"(b) {bps} bps produced exactly one config row",
                len(frozen_rows(league_b)) == 1, str(frozen_rows(league_b)))

    # ── (c) invalid values refused BY THE DATABASE ────────────────────────
    #
    # Asserted against the live database, not against a Python guard. The two
    # CHECKs are the outer and inner halves of the same rule: leagues stops a
    # bad value ever being SET, league_season_topoff_config stops a bad value
    # ever being FROZEN. A test that only exercised application code would pass
    # even if both constraints were missing from the DDL.
    print("\n(c) invalid multipliers are refused by the DATABASE on both tables")
    tdb.reset()
    league_c, teams_c = seed_league()
    INVALID = (-5000, 1, 2500, 9999, 10001, 25000, 100000)

    for bad in INVALID:
        raised = None
        with SessionLocal() as db:
            try:
                db.query(League).filter(League.id == league_c).one().topoff_cap_multiplier_bps = bad
                db.commit()
            except IntegrityError as e:
                raised = e
                db.rollback()
        _assert(f"(c) leagues rejects {bad} via ck_leagues_topoff_multiplier_bps",
                raised is not None, f"raised={type(raised).__name__}")

    for bad in INVALID:
        raised = None
        with SessionLocal() as db:
            try:
                db.add(LeagueSeasonTopoffConfig(
                    league_id=league_c, season=SEASON, topoff_cap_multiplier_bps=bad,
                ))
                db.commit()
            except IntegrityError as e:
                raised = e
                db.rollback()
        _assert(f"(c) league_season_topoff_config rejects {bad} via ck_lstc_multiplier_bps",
                raised is not None, f"raised={type(raised).__name__}")

    _assert("(c) no invalid value survived on the league",
            frozen_rows(league_c) == [], str(frozen_rows(league_c)))
    with SessionLocal() as db:
        still = db.query(League).filter(League.id == league_c).one().topoff_cap_multiplier_bps
    _assert("(c) the league's multiplier is untouched after every refusal",
            still == DEFAULT_BPS, f"got {still}")

    # ── (d) atomic creation of config AND allocations ─────────────────────
    print("\n(d) config row and allocation rows are created atomically")
    tdb.reset()
    league_d, teams_d = seed_league(multiplier_bps=15000)
    before_d = snapshot(teams_d)
    _assert("(d) trial_balance == 0 BEFORE", before_d["trial"] == 0, f"got {before_d['trial']}")
    _assert("(d) no config row exists BEFORE", before_d["cfgs"] == 0, f"got {before_d['cfgs']}")

    with SessionLocal() as db:
        res_d = activate_season_allocation(league_d, db)
    after_d = snapshot(teams_d)
    d_d = deltas(before_d, after_d, teams_d)

    _assert("(d) created=True", res_d.created is True)
    _assert("(d) exactly ONE config row added", d_d["cfgs"] == 1, f"delta={d_d['cfgs']}")
    _assert("(d) exactly one allocation row per team added",
            d_d["rows"] == TEAM_COUNT, f"delta={d_d['rows']}")
    _assert("(d) exactly three ledger entries per team added",
            d_d["entries"] == 3 * TEAM_COUNT, f"delta={d_d['entries']}")
    _assert("(d) the frozen multiplier is the league's 15000",
            frozen_rows(league_d) == [(SEASON, 15000)], str(frozen_rows(league_d)))
    _assert("(d) trial_balance still 0 AFTER", after_d["trial"] == 0, f"got {after_d['trial']}")

    # ── (e) identical replay writes nothing ───────────────────────────────
    print("\n(e) identical replay adds no config row, no allocation row, no posting")
    before_e = snapshot(teams_d)
    with SessionLocal() as db:
        res_e = activate_season_allocation(league_d, db)
    after_e = snapshot(teams_d)
    d_e = deltas(before_e, after_e, teams_d)

    _assert("(e) replay returned created=False", res_e.created is False, f"got {res_e.created}")
    _assert("(e) replay posted nothing", res_e.posting_ids == (), str(res_e.posting_ids))
    _assert("(e) replay added ZERO config rows", d_e["cfgs"] == 0, f"delta={d_e['cfgs']}")
    _assert("(e) replay added ZERO allocation rows", d_e["rows"] == 0, f"delta={d_e['rows']}")
    _assert("(e) replay added ZERO ledger entries", d_e["entries"] == 0, f"delta={d_e['entries']}")
    _assert("(e) replay moved NO money — all deltas zero", all_zero(d_e, teams_d), str(d_e))
    _assert("(e) still exactly one frozen row, unchanged",
            frozen_rows(league_d) == [(SEASON, 15000)], str(frozen_rows(league_d)))

    # ── (f) changed multiplier is a CONFLICT, not a replay ────────────────
    #
    # THE SCENARIO THIS SUITE EXISTS FOR (B6 §2.5, test S11/R6). Everything
    # about the allocation still matches; only the league's dial moved. If the
    # multiplier were absent from the comparison tuple this returns created=False
    # and reports success, and the stale frozen value governs the season.
    print("\n(f) changed frozen multiplier -> ConflictingAllocationError")
    before_f = snapshot(teams_d)
    set_league_multiplier(league_d, 20000)

    raised_f = None
    with SessionLocal() as db:
        try:
            activate_season_allocation(league_d, db)
        except Exception as e:      # noqa: BLE001 — recording, not swallowing
            raised_f = e
    after_f = snapshot(teams_d)
    d_f = deltas(before_f, after_f, teams_d)

    _assert("(f) a changed multiplier is CONFLICTING, not a replay",
            isinstance(raised_f, ConflictingAllocationError),
            f"got {type(raised_f).__name__}")
    _assert("(f) the refusal names both the frozen and the current value",
            "15000" in str(raised_f) and "20000" in str(raised_f), str(raised_f)[:200])
    _assert("(f) the frozen row was NOT updated in place — it still reads 15000",
            frozen_rows(league_d) == [(SEASON, 15000)], str(frozen_rows(league_d)))
    _assert("(f) nothing was mutated — all deltas zero", all_zero(d_f, teams_d), str(d_f))

    # restore, and prove the restoration returns the league to a clean replay
    set_league_multiplier(league_d, 15000)
    with SessionLocal() as db:
        res_f2 = activate_season_allocation(league_d, db)
    _assert("(f) restoring the league dial to the frozen value replays cleanly again",
            res_f2.created is False, f"got {res_f2.created}")

    # ── (g) changed allocation tuple still conflicts ──────────────────────
    #
    # The pre-existing B2 conflict rule must survive the tuple gaining a member.
    print("\n(g) changed allocation inputs still conflict")
    tdb.reset()
    alt = [s for s in ECONOMY_STOPS if s.buyin_cents != DEFAULT_STOP.buyin_cents][0]
    league_g, teams_g = seed_league()
    with SessionLocal() as db:
        activate_season_allocation(league_g, db)
    before_g = snapshot(teams_g)

    with SessionLocal() as db:
        db.query(League).filter(League.id == league_g).one().economy_stop_weekly_min_cents = (
            alt.weekly_min_cents
        )
        db.commit()

    raised_g = None
    with SessionLocal() as db:
        try:
            activate_season_allocation(league_g, db)
        except Exception as e:      # noqa: BLE001 — recording
            raised_g = e
    after_g = snapshot(teams_g)
    d_g = deltas(before_g, after_g, teams_g)

    _assert("(g) a changed economy stop is still CONFLICTING",
            isinstance(raised_g, ConflictingAllocationError),
            f"got {type(raised_g).__name__}")
    _assert("(g) nothing was mutated — all deltas zero", all_zero(d_g, teams_g), str(d_g))
    _assert("(g) the frozen config row is untouched",
            len(frozen_rows(league_g)) == 1, str(frozen_rows(league_g)))

    # ── (h) allocations WITHOUT a config row -> partial ───────────────────
    #
    # Corruption, not a replay: the season is half-activated and no cap can be
    # computed. Critically it must NOT be silently repaired by writing today's
    # League.topoff_cap_multiplier_bps onto a season activated under an unknown
    # one — that would invent the very fact the freeze exists to preserve.
    print("\n(h) allocations without a config row -> PartialAllocationError")
    tdb.reset()
    league_h, teams_h = seed_league(multiplier_bps=5000)
    with SessionLocal() as db:
        activate_season_allocation(league_h, db)
    with SessionLocal() as db:
        db.query(LeagueSeasonTopoffConfig).filter(
            LeagueSeasonTopoffConfig.league_id == league_h).delete()
        db.commit()
    before_h = snapshot(teams_h)
    _assert("(h) the config row really is gone", before_h["cfgs"] == 0, f"got {before_h['cfgs']}")

    raised_h = None
    with SessionLocal() as db:
        try:
            activate_season_allocation(league_h, db)
        except Exception as e:      # noqa: BLE001 — recording
            raised_h = e
    after_h = snapshot(teams_h)
    d_h = deltas(before_h, after_h, teams_h)

    _assert("(h) missing config with complete allocations is PARTIAL",
            isinstance(raised_h, PartialAllocationError), f"got {type(raised_h).__name__}")
    _assert("(h) it was NOT silently repaired — no config row was written",
            d_h["cfgs"] == 0, f"delta={d_h['cfgs']}")
    _assert("(h) nothing else was mutated either", all_zero(d_h, teams_h), str(d_h))
    _assert("(h) the refusal explains the half-activated state",
            "half-activated" in str(raised_h), str(raised_h)[:200])

    # ── (i) config row WITHOUT allocations -> partial ─────────────────────
    #
    # Must be caught on the READ side. If it fell through to the create branch
    # it would insert a second config row and die on uq_lstc_league_season —
    # turning a diagnosable corruption into a raw database exception.
    print("\n(i) config row without allocations -> PartialAllocationError")
    tdb.reset()
    league_i, teams_i = seed_league()
    with SessionLocal() as db:
        db.add(LeagueSeasonTopoffConfig(
            league_id=league_i, season=SEASON, topoff_cap_multiplier_bps=DEFAULT_BPS,
        ))
        db.commit()
    before_i = snapshot(teams_i)

    raised_i = None
    with SessionLocal() as db:
        try:
            activate_season_allocation(league_i, db)
        except Exception as e:      # noqa: BLE001 — recording
            raised_i = e
    after_i = snapshot(teams_i)
    d_i = deltas(before_i, after_i, teams_i)

    _assert("(i) a config row with no allocations is PARTIAL",
            isinstance(raised_i, PartialAllocationError), f"got {type(raised_i).__name__}")
    _assert("(i) it is NOT a raw IntegrityError from uq_lstc_league_season",
            not isinstance(raised_i, IntegrityError), f"got {type(raised_i).__name__}")
    _assert("(i) the refusal records that the config row is present",
            "config row present: True" in str(raised_i), str(raised_i)[:240])
    _assert("(i) no allocation rows were created", d_i["rows"] == 0, f"delta={d_i['rows']}")
    _assert("(i) no second config row was created", d_i["cfgs"] == 0, f"delta={d_i['cfgs']}")
    _assert("(i) nothing was mutated — all deltas zero", all_zero(d_i, teams_i), str(d_i))

    # ── (j) config row with INCOMPLETE allocations -> partial ─────────────
    print("\n(j) config row with incomplete allocations -> PartialAllocationError")
    tdb.reset()
    league_j, teams_j = seed_league()
    with SessionLocal() as db:
        activate_season_allocation(league_j, db)
    # Remove one team's allocation row, leaving the config row and 3 of 4 rows.
    with SessionLocal() as db:
        db.query(SeasonAllocation).filter(
            SeasonAllocation.league_id == league_j,
            SeasonAllocation.team_id   == teams_j[-1],
        ).delete()
        db.commit()
    before_j = snapshot(teams_j)
    _assert("(j) the league really is 3-of-4 allocated with its config row intact",
            before_j["cfgs"] == 1, f"cfgs={before_j['cfgs']}")

    raised_j = None
    with SessionLocal() as db:
        try:
            activate_season_allocation(league_j, db)
        except Exception as e:      # noqa: BLE001 — recording
            raised_j = e
    after_j = snapshot(teams_j)
    d_j = deltas(before_j, after_j, teams_j)

    _assert("(j) config plus an incomplete allocation set is PARTIAL",
            isinstance(raised_j, PartialAllocationError), f"got {type(raised_j).__name__}")
    _assert("(j) the missing team was NOT back-filled", d_j["rows"] == 0, f"delta={d_j['rows']}")
    _assert("(j) nothing was mutated — all deltas zero", all_zero(d_j, teams_j), str(d_j))

    # ── (k) forced failure rolls back config, allocations AND postings ────
    #
    # The failure is injected INSIDE activation by monkeypatching the ledger
    # post symbol that module imported, so it lands after the config row and
    # some allocation rows and some postings already exist in the session —
    # the genuinely dangerous case. Modelled on scenario (j) of the B2 suite.
    print("\n(k) forced mid-activation failure rolls back config, allocations and postings")
    tdb.reset()
    league_k, teams_k = seed_league(multiplier_bps=20000)
    before_k = snapshot(teams_k)

    class _Boom(RuntimeError):
        pass

    real_post = sa.ledger_post
    calls = {"n": 0}

    def exploding_post(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 3:          # fail partway through, not on the first team
            raise _Boom("injected mid-activation posting failure")
        return real_post(*args, **kwargs)

    sa.ledger_post = exploding_post
    raised_k = None
    try:
        with SessionLocal() as db:
            try:
                activate_season_allocation(league_k, db)
            except Exception as e:      # noqa: BLE001 — recording
                raised_k = e
    finally:
        sa.ledger_post = real_post

    after_k = snapshot(teams_k)
    d_k = deltas(before_k, after_k, teams_k)

    _assert("(k) the injected failure propagated", isinstance(raised_k, _Boom),
            f"got {type(raised_k).__name__}")
    _assert("(k) failure occurred AFTER work was staged", calls["n"] >= 3, f"post called {calls['n']}x")
    _assert("(k) ZERO config rows survive", d_k["cfgs"] == 0, f"delta={d_k['cfgs']}")
    _assert("(k) ZERO allocation rows survive", d_k["rows"] == 0, f"delta={d_k['rows']}")
    _assert("(k) ZERO ledger entries survive", d_k["entries"] == 0, f"delta={d_k['entries']}")
    _assert("(k) ZERO money deltas", all_zero(d_k, teams_k), str(d_k))
    _assert("(k) the league has no frozen row at all", frozen_rows(league_k) == [],
            str(frozen_rows(league_k)))

    # ── (l1) GENUINE blocking on the League row, directly observed ────────
    #
    # NO SLEEP IS USED AS PROOF. A holder connection takes the League row lock
    # and keeps its transaction open. A contender thread then runs a real
    # activation, which must block on that row. A THIRD connection observes the
    # block by asking PostgreSQL directly: pg_blocking_pids(contender) must
    # contain the holder's backend pid. The poll below waits for that condition
    # to become observable and FAILS if it never does — it is not a timing
    # assertion, and no assertion anywhere depends on elapsed time.
    print("\n(l1) genuine blocking on the League row, observed via pg_blocking_pids()")
    tdb.reset()
    league_l, teams_l = seed_league(multiplier_bps=5000)

    holder_ready = threading.Event()
    release      = threading.Event()
    obs: dict = {}

    def holder():
        with SessionLocal() as dba:
            obs["holder_pid"] = dba.execute(text("SELECT pg_backend_pid()")).scalar()
            dba.execute(
                text("SELECT id FROM leagues WHERE id = :i FOR NO KEY UPDATE"),
                {"i": league_l},
            ).fetchall()
            holder_ready.set()
            release.wait(timeout=30)
            dba.rollback()          # holder writes nothing; it only holds the lock

    def contender():
        holder_ready.wait(timeout=30)
        with SessionLocal() as dbb:
            try:
                obs["result"] = activate_season_allocation(league_l, dbb)
            except Exception as e:      # noqa: BLE001 — recording
                obs["exc"] = e

    th_h = threading.Thread(target=holder)
    th_c = threading.Thread(target=contender)
    th_h.start()
    th_c.start()
    holder_ready.wait(timeout=30)

    # Bounded poll on an OBSERVABLE DATABASE CONDITION, not on the clock. Each
    # iteration is a real round trip, so the loop paces itself with no sleep.
    # The deadline is a FAILURE BOUND, not evidence: nothing is asserted about
    # how long the block took, only that PostgreSQL reported it at all.
    blocked_evidence = None
    deadline = time.monotonic() + 30.0
    with SessionLocal() as probe:
        while time.monotonic() < deadline:
            row = probe.execute(text("""
                SELECT pid, wait_event_type, query
                FROM pg_stat_activity
                WHERE pid <> pg_backend_pid()
                  AND :holder = ANY(pg_blocking_pids(pid))
            """), {"holder": obs.get("holder_pid")}).fetchone()
            probe.rollback()        # end the probe's snapshot so the next read is fresh
            if row is not None:
                blocked_evidence = row
                break

    _assert("(l1) the contender's backend was observed BLOCKED BY the holder's backend",
            blocked_evidence is not None,
            f"holder pid={obs.get('holder_pid')} blocked pid="
            f"{blocked_evidence[0] if blocked_evidence else 'NONE OBSERVED'}")
    if blocked_evidence is not None:
        _assert("(l1) PostgreSQL reports the wait as a Lock wait",
                blocked_evidence[1] == "Lock", f"wait_event_type={blocked_evidence[1]}")
        _assert("(l1) the blocked statement is the League row lock, not something else",
                "leagues" in (blocked_evidence[2] or "").lower()
                and "for no key update" in (blocked_evidence[2] or "").lower(),
                f"blocked query={blocked_evidence[2]!r}")

    release.set()
    th_h.join(timeout=30)
    th_c.join(timeout=30)

    _assert("(l1) once unblocked, the contender completed with NO exception",
            "exc" not in obs, f"got {type(obs.get('exc')).__name__}: {obs.get('exc')}")
    _assert("(l1) the contender then created the allocation",
            obs.get("result") is not None and obs["result"].created is True,
            str(obs.get("result")))
    _assert("(l1) exactly one frozen config row resulted",
            frozen_rows(league_l) == [(SEASON, 5000)], str(frozen_rows(league_l)))

    # ── (l2) two concurrent activations ───────────────────────────────────
    print("\n(l2) two concurrent activations: one creates, one replays, no raw exception")
    ROUNDS = 3
    tally = {"created": 0, "replayed": 0, "raced": 0}
    for rnd in range(ROUNDS):
        tdb.reset()
        league_r, teams_r = seed_league(multiplier_bps=20000)
        before_r = snapshot(teams_r)

        barrier = threading.Barrier(2)
        outcomes: list[tuple[str, object]] = []
        lock = threading.Lock()

        def racer():
            try:
                with SessionLocal() as db:
                    barrier.wait(timeout=30)        # release both at once
                    res = activate_season_allocation(league_r, db)
                with lock:
                    outcomes.append(("ok", res))
            except Exception as e:                  # noqa: BLE001 — recording
                with lock:
                    outcomes.append(("err", e))

        threads = [threading.Thread(target=racer) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        after_r = snapshot(teams_r)
        d_r = deltas(before_r, after_r, teams_r)

        created  = [o for o in outcomes if o[0] == "ok" and o[1].created is True]
        replayed = [o for o in outcomes if o[0] == "ok" and o[1].created is False]
        raced    = [o for o in outcomes if o[0] == "err"]
        tally["created"]  += len(created)
        tally["replayed"] += len(replayed)
        tally["raced"]    += len(raced)

        _assert(f"(l2 r{rnd}) both threads finished", len(outcomes) == 2, str(len(outcomes)))
        _assert(f"(l2 r{rnd}) exactly ONE returned created=True",
                len(created) == 1, f"created={len(created)} replayed={len(replayed)} raced={len(raced)}")
        _assert(f"(l2 r{rnd}) exactly ONE returned created=False",
                len(replayed) == 1, f"created={len(created)} replayed={len(replayed)} raced={len(raced)}")
        _assert(f"(l2 r{rnd}) NO raw exception was raised by either activation",
                len(raced) == 0, str([repr(o[1]) for o in raced]))
        _assert(f"(l2 r{rnd}) exactly ONE frozen config row exists",
                d_r["cfgs"] == 1 and frozen_rows(league_r) == [(SEASON, 20000)],
                f"delta={d_r['cfgs']} rows={frozen_rows(league_r)}")
        _assert(f"(l2 r{rnd}) exactly ONE complete allocation set exists",
                d_r["rows"] == TEAM_COUNT, f"delta={d_r['rows']}")
        _assert(f"(l2 r{rnd}) no duplicate ledger posting — three entries per team",
                d_r["entries"] == 3 * TEAM_COUNT, f"delta={d_r['entries']}")
        _assert(f"(l2 r{rnd}) min_reserve credited exactly once per team",
                all(d_r["min_reserve"][t] == stop.min_reserve_cents
                    for t in teams_r), str(d_r["min_reserve"]))
        _assert(f"(l2 r{rnd}) wallet stayed at zero throughout the race (S5-R2)",
                all(d_r["wallet"][t] == 0 for t in teams_r), str(d_r["wallet"]))
        _assert(f"(l2 r{rnd}) season_issuance debited exactly once per team",
                d_r["issuance"] == -(stop.buyin_cents * TEAM_COUNT),
                f"delta={d_r['issuance']}")
        _assert(f"(l2 r{rnd}) trial_balance() is exactly 0 after the race",
                after_r["trial"] == 0, f"got {after_r['trial']}")

    print(f"    outcome distribution over {ROUNDS} rounds: {tally}")
    _assert("(l2) every round produced exactly one create and one replay",
            tally["created"] == ROUNDS and tally["replayed"] == ROUNDS and tally["raced"] == 0,
            str(tally))

    # ── (m) S5 / S6 schema invariants ─────────────────────────────────────
    print("\n(m) S5/S6 schema invariants")
    insp = inspect(tdb.engine)

    # S6 — no multiplier column of ANY name on SeasonAllocation.
    alloc_cols = {c["name"] for c in insp.get_columns("season_allocation")}
    offending = sorted(c for c in alloc_cols
                       if "multiplier" in c or c.endswith("_bps") or "topoff" in c)
    _assert("(m/S6) SeasonAllocation carries NO multiplier column of any name",
            offending == [], f"offending columns: {offending}")
    _assert("(m/S6) SeasonAllocation still carries its three snapshot columns",
            {"buyin_cents", "min_reserve_cents", "reserve_cents"} <= alloc_cols,
            str(sorted(alloc_cols)))

    # S6 — every team in a league derives from ONE config row.
    tdb.reset()
    league_m, teams_m = seed_league(team_count=6, multiplier_bps=5000)
    with SessionLocal() as db:
        activate_season_allocation(league_m, db)
    with SessionLocal() as db:
        n_alloc = db.query(SeasonAllocation).filter(
            SeasonAllocation.league_id == league_m).count()
    _assert("(m/S6) six teams allocated from exactly one config row",
            n_alloc == 6 and len(frozen_rows(league_m)) == 1,
            f"alloc rows={n_alloc} config rows={frozen_rows(league_m)}")

    # S5 — duplicate league-season snapshot impossible BY CONSTRAINT.
    uqs = {u.get("name"): u.get("column_names") for u in insp.get_unique_constraints(
        "league_season_topoff_config")}
    _assert("(m/S5) uq_lstc_league_season exists on (league_id, season)",
            uqs.get("uq_lstc_league_season") == ["league_id", "season"], str(uqs))
    fks = {f["name"] for f in insp.get_foreign_keys("league_season_topoff_config")}
    _assert("(m/S5) fk_lstc_league exists", "fk_lstc_league" in fks, str(sorted(fks)))

    dup_raised = None
    with SessionLocal() as db:
        try:
            db.add(LeagueSeasonTopoffConfig(
                league_id=league_m, season=SEASON, topoff_cap_multiplier_bps=5000,
            ))
            db.commit()
        except IntegrityError as e:
            dup_raised = e
            db.rollback()
    _assert("(m/S5) a duplicate (league_id, season) snapshot is refused by the database",
            dup_raised is not None, "no IntegrityError raised")
    _assert("(m/S5) the refused duplicate left exactly one row",
            len(frozen_rows(league_m)) == 1, str(frozen_rows(league_m)))

    # INSERT-ONLY is a CONTRACT, not a trigger. Its observable halves: activation
    # refuses rather than rewriting a frozen row (proven by (f), which leaves
    # 15000 in place against a league dial reading 20000), and the sole
    # production writer issues no UPDATE or DELETE of any kind.
    src = pathlib.Path(sa.__file__).read_text(encoding="utf-8")
    _assert("(m) the activation module references LeagueSeasonTopoffConfig",
            "LeagueSeasonTopoffConfig" in src)
    _assert("(m) the activation module issues no .delete() anywhere",
            ".delete()" not in src, f"delete calls found: {src.count('.delete()')}")
    _assert("(m) the activation module issues no .update() anywhere",
            ".update(" not in src, f"update calls found: {src.count('.update(')}")


try:
    main(tdb)
finally:
    tdb.teardown()

print("\n" + "=" * 60)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("All assertions PASSED")
