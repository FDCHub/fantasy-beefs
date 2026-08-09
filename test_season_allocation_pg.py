"""
test_season_allocation_pg.py — B2 Group 2 season allocation (PostgreSQL).

Focused suite for economy/season_allocation.py. Postgres only: the
concurrency scenario needs two real connections racing a real unique index,
and the rollback scenarios need real transaction semantics. SQLite cannot
prove either.

EVERY MONEY ASSERTION IS A DELTA. Balances are captured before and after
each scenario and only the difference is asserted. Absolute balances depend
on whatever earlier scenarios left behind, so an absolute assertion would
pass or fail for reasons unrelated to the code under test.

WHY balance_of()/trial_balance() ARE THE RIGHT PROBE. Both open their own
SessionLocal, so they read COMMITTED state only. That is exactly what the
rollback and rejection scenarios need to prove: work that was rolled back is
invisible to them, so a zero delta is real evidence of nothing persisting,
not an artifact of reading the writer's own uncommitted transaction.

Scenario (j) — forced mid-activation failure — is modelled on
test_ledger.py's session-provided rollback proof (post(..., session=caller_db)
followed by the caller rolling back writes nothing). Here the failure is
injected INSIDE activate_season_allocation by monkeypatching the ledger post
symbol that module imported, so the failure lands after some rows and some
postings already exist in the session — the genuinely dangerous case.

SEASON AUTHORITY. Allocation rows are stamped with config.ALLOCATION_SEASON
(2026), NOT config.CURRENT_SEASON (2025, the projection-data year). The two
are deliberately separate settings; scenario (n) asserts they stay separate
and (o) proves the gate's season-qualification is load-bearing.

SCENARIOS (a-p):
    a  three legs sum to zero in integer cents
    b  min_reserve delta == stop.min_reserve_cents, wallet delta == 0 (S5-R2)
    c  reserve delta == stop.reserve_cents
    d  world delta == -(stop.buyin_cents * team_count)
    e  trial_balance() == 0 before and after
    f  no rows -> complete atomic activation
    g  complete matching -> returns existing, posts nothing, all deltas zero
    h  partial -> rejected, no mutation, all deltas zero
    i  conflicting -> rejected, no mutation, all deltas zero
    j  forced mid-activation failure -> zero rows, zero entries, zero deltas
    k  post() receives session=db; no independent commit inside activation
    l  uq_season_allocation_league_team_season present and enforced
    m  concurrency: two overlapping activations, exactly one succeeds
    n  created rows carry season == config.ALLOCATION_SEASON (2026)
    o  a 2025-ONLY allocation does NOT satisfy the gate (blocked, 402)
    p  a 2026 allocation DOES satisfy the gate (passes)
    q  route-level: NoTeamsError -> HTTP 400
    r  route-level: an injected LedgerImbalanceError is NOT converted to 400
       (R-1 regression guard — without it the over-broad except returns)
    s  replay leaves NO active transaction on the caller's session

CONCURRENCY EVIDENCE (R-9, SUPERSEDED BY B6 GROUP B). This note formerly
recorded that scenario (m2)'s race loser had always taken the
UNIQUE-CONSTRAINT path and that the concurrent replay-loser path had never
been observed. B6 Group B added a League row lock, taken FOR NO KEY UPDATE as
the first statement of activation, which makes the replay-loser path
DETERMINISTIC: the loser blocks on the League row and, once the winner
commits, re-reads committed state under READ COMMITTED and returns
created=False. (m2)'s tally therefore now reads {'created': N, 'replayed': N,
'raced': 0}, and its assertions — which accept either loser outcome by design
— are unchanged and still pass.

Scenario (m1) is UNAFFECTED and still proves the unique index is a live
guard, because its holder INSERTs an allocation row directly and so never
takes the League lock. A raw write that bypasses the activation seam is
corruption, not a concurrent activation. Sequential replay remains proven
separately by scenario (g). See the comment above (m1) for detail.

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database (see test_support_postgres guards).
"""

import os
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
    print(f"\n[HARNESS ERROR] Season-allocation suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    """Post-setup work. Project imports live here so teardown protection
    begins the instant setup succeeds."""
    from fastapi import HTTPException
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import IntegrityError

    from db.schema import SessionLocal, League, Team, User, SeasonAllocation
    from ledger.ledger import balance_of, trial_balance, LedgerEntry
    from payments.economy_config import DEFAULT_STOP, ECONOMY_STOPS
    from auth.allocation_gate import get_season_allocation_gate
    import config

    import economy.season_allocation as sa
    from economy.season_allocation import (
        activate_season_allocation,
        ConflictingAllocationError,
        PartialAllocationError,
        NoTeamsError,
    )

    TEAM_COUNT = 4

    # ── helpers ───────────────────────────────────────────────────────────

    def seed_league(team_count: int = TEAM_COUNT, weekly_min_cents=None) -> tuple[int, list[int]]:
        """Create a league + teams. Returns (league_id, [team_id, ...])."""
        with SessionLocal() as db:
            league = League(season=config.ALLOCATION_SEASON, name="Alloc Test League")
            if weekly_min_cents is not None:
                league.economy_stop_weekly_min_cents = weekly_min_cents
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

    def _season_issuance_total() -> int:
        """Summed across the whole season_issuance:* namespace.

        The snapshot is league-agnostic — it is taken before a league id is
        known — and every scenario in this file runs against a freshly reset
        database, so a namespace total is exactly the per-league figure without
        the helper having to be told which league."""
        with SessionLocal() as db:
            total = db.execute(text(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
                "WHERE account LIKE 'season_issuance:%'")).scalar()
        return int(total or 0)

    def snapshot(team_ids: list[int]) -> dict:
        """Committed-state probe: world/wallet/reserve balances, trial
        balance, and the two row counts. Everything a delta needs."""
        with SessionLocal() as db:
            rows = db.query(SeasonAllocation).count()
            entries = db.query(LedgerEntry).count()
        return {
            "world":   balance_of("world"),
            # S5-R2 reshaped the opening allocation: the source is now the
            # league-season issuance account and the 140 lands in min_reserve,
            # not Wallet. Both the OLD accounts and the NEW ones are probed, so
            # the assertions below can state positively that world and wallet
            # are now UNTOUCHED rather than merely not checking them.
            "issuance": _season_issuance_total(),
            "wallet":  {t: balance_of(f"wallet:{t}") for t in team_ids},
            "min_reserve": {t: balance_of(f"min_reserve:{t}") for t in team_ids},
            "reserve": {t: balance_of(f"reserve:{t}") for t in team_ids},
            "trial":   trial_balance(),
            "rows":    rows,
            "entries": entries,
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
        }

    def all_zero(d: dict, team_ids: list[int]) -> bool:
        return (
            d["world"] == 0
            and all(d["wallet"][t] == 0 for t in team_ids)
            and all(d["reserve"][t] == 0 for t in team_ids)
            and d["trial"] == 0
            and d["rows"] == 0
            and d["entries"] == 0
        )

    stop = DEFAULT_STOP

    # ── (a) conservation: three legs sum to zero ──────────────────────────
    print("\n(a) three legs sum to zero in integer cents")
    legs = [
        ("world", -stop.buyin_cents),
        ("wallet:X", stop.min_reserve_cents),
        ("reserve:X", stop.reserve_cents),
    ]
    _assert("posting has exactly three legs", len(legs) == 3)
    _assert("legs sum to exactly zero", sum(a for _, a in legs) == 0,
            f"sum={sum(a for _, a in legs)}")
    _assert("every leg is an int (no float cents)",
            all(isinstance(a, int) for _, a in legs))
    _assert("wallet+reserve == buyin (economy_config invariant)",
            stop.min_reserve_cents + stop.reserve_cents == stop.buyin_cents,
            f"{stop.min_reserve_cents}+{stop.reserve_cents} vs {stop.buyin_cents}")

    # ── (f)(b)(c)(d)(e) fresh activation ──────────────────────────────────
    print("\n(f) no rows -> complete atomic activation; (b)(c)(d)(e) deltas")
    tdb.reset()
    league_id, team_ids = seed_league()
    before = snapshot(team_ids)
    _assert("(e) trial_balance == 0 BEFORE", before["trial"] == 0, f"got {before['trial']}")

    with SessionLocal() as db:
        result = activate_season_allocation(league_id, db)

    after = snapshot(team_ids)
    d = deltas(before, after, team_ids)

    _assert("(f) created=True", result.created is True)
    _assert("(f) one row per league team", d["rows"] == TEAM_COUNT, f"delta={d['rows']}")
    _assert("(f) three ledger entries per team", d["entries"] == 3 * TEAM_COUNT,
            f"delta={d['entries']}")
    _assert("(f) one posting_id per team", len(result.posting_ids) == TEAM_COUNT)
    _assert("(f) posting_ids all distinct", len(set(result.posting_ids)) == TEAM_COUNT)
    # S5-R2: the 140 goes to min_reserve, and Wallet receives NOTHING. Both
    # halves are asserted — the second is what makes the superseded model
    # unable to pass.
    _assert("(b) min_reserve delta == stop.min_reserve_cents for every team",
            all(d["min_reserve"][t] == stop.min_reserve_cents for t in team_ids),
            f"{d['min_reserve']} vs {stop.min_reserve_cents}")
    _assert("(b) wallet delta == 0 for every team (S5-R2)",
            all(d["wallet"][t] == 0 for t in team_ids), f"{d['wallet']}")
    _assert("(c) reserve delta == stop.reserve_cents for every team",
            all(d["reserve"][t] == stop.reserve_cents for t in team_ids),
            f"{d['reserve']} vs {stop.reserve_cents}")
    _assert("(d) season_issuance delta == -(buyin * team_count)",
            d["issuance"] == -(stop.buyin_cents * TEAM_COUNT),
            f"{d['issuance']} vs {-(stop.buyin_cents * TEAM_COUNT)}")
    _assert("(d) world delta == 0 — the opening allocation no longer mints "
            "from world (S5-R2)", d["world"] == 0, f"{d['world']}")
    _assert("(e) trial_balance == 0 AFTER", after["trial"] == 0, f"got {after['trial']}")
    _assert("(e) trial_balance delta == 0", d["trial"] == 0)
    _assert("result total_buyin_cents == buyin * team_count",
            result.total_buyin_cents == stop.buyin_cents * TEAM_COUNT)
    _assert("snapshot written to every row matches the stop",
            _rows_match_stop(SessionLocal, SeasonAllocation, league_id, config.ALLOCATION_SEASON, stop))

    # ── (g) idempotent replay ─────────────────────────────────────────────
    print("\n(g) complete matching -> returns existing, posts nothing, all deltas zero")
    before_g = snapshot(team_ids)
    with SessionLocal() as db:
        result_g = activate_season_allocation(league_id, db)
    after_g = snapshot(team_ids)
    d_g = deltas(before_g, after_g, team_ids)

    _assert("(g) created=False on replay", result_g.created is False)
    _assert("(g) no posting_ids returned (nothing posted)", result_g.posting_ids == ())
    _assert("(g) row count unchanged", d_g["rows"] == 0, f"delta={d_g['rows']}")
    _assert("(g) ledger entry count unchanged", d_g["entries"] == 0, f"delta={d_g['entries']}")
    _assert("(g) ALL DELTAS ZERO", all_zero(d_g, team_ids), str(d_g))
    _assert("(g) replay reports the same team set", set(result_g.team_ids) == set(team_ids))

    # ── (h) partial rejection ─────────────────────────────────────────────
    print("\n(h) partial -> rejected, no mutation, all deltas zero")
    tdb.reset()
    league_h, teams_h = seed_league()
    # Allocate, then delete ONE row to manufacture a genuinely partial state.
    with SessionLocal() as db:
        activate_season_allocation(league_h, db)
    with SessionLocal() as db:
        victim = (
            db.query(SeasonAllocation)
            .filter(SeasonAllocation.league_id == league_h,
                    SeasonAllocation.team_id == teams_h[-1])
            .one()
        )
        db.delete(victim)
        db.commit()

    before_h = snapshot(teams_h)
    raised_h = None
    with SessionLocal() as db:
        try:
            activate_season_allocation(league_h, db)
        except Exception as e:
            raised_h = e
    after_h = snapshot(teams_h)
    d_h = deltas(before_h, after_h, teams_h)

    _assert("(h) raises PartialAllocationError (type, not message)",
            isinstance(raised_h, PartialAllocationError), f"got {type(raised_h).__name__}")
    _assert("(h) ALL DELTAS ZERO — no mutation", all_zero(d_h, teams_h), str(d_h))

    # ── (i) conflicting rejection ─────────────────────────────────────────
    print("\n(i) conflicting -> rejected, no mutation, all deltas zero")
    tdb.reset()
    league_i, teams_i = seed_league()
    with SessionLocal() as db:
        activate_season_allocation(league_i, db)
    # Mutate one row's snapshot so it disagrees with the current stop.
    other = next(s for s in ECONOMY_STOPS if s.buyin_cents != stop.buyin_cents)
    with SessionLocal() as db:
        row = (
            db.query(SeasonAllocation)
            .filter(SeasonAllocation.league_id == league_i,
                    SeasonAllocation.team_id == teams_i[0])
            .one()
        )
        row.buyin_cents   = other.buyin_cents
        row.min_reserve_cents  = other.min_reserve_cents
        row.reserve_cents = other.reserve_cents
        db.commit()

    before_i = snapshot(teams_i)
    raised_i = None
    with SessionLocal() as db:
        try:
            activate_season_allocation(league_i, db)
        except Exception as e:
            raised_i = e
    after_i = snapshot(teams_i)
    d_i = deltas(before_i, after_i, teams_i)

    _assert("(i) raises ConflictingAllocationError (type, not message)",
            isinstance(raised_i, ConflictingAllocationError), f"got {type(raised_i).__name__}")
    _assert("(i) ALL DELTAS ZERO — no mutation", all_zero(d_i, teams_i), str(d_i))

    # ── (j) forced mid-activation failure ─────────────────────────────────
    print("\n(j) forced mid-activation failure -> zero rows, zero entries, zero deltas")
    tdb.reset()
    league_j, teams_j = seed_league()
    before_j = snapshot(teams_j)

    class _Boom(RuntimeError):
        pass

    real_post = sa.ledger_post
    calls = {"n": 0}

    def exploding_post(entries, door, session=None):
        # Let the first two teams post normally, then fail — so rows AND
        # ledger entries already exist in the session when the error hits.
        calls["n"] += 1
        if calls["n"] > 2:
            raise _Boom("injected mid-activation failure")
        return real_post(entries, door, session=session)

    sa.ledger_post = exploding_post
    raised_j = None
    try:
        with SessionLocal() as db:
            try:
                activate_season_allocation(league_j, db)
            except Exception as e:
                raised_j = e
    finally:
        sa.ledger_post = real_post

    after_j = snapshot(teams_j)
    d_j = deltas(before_j, after_j, teams_j)

    _assert("(j) the injected failure propagated", isinstance(raised_j, _Boom),
            f"got {type(raised_j).__name__}")
    _assert("(j) failure occurred AFTER some work was staged", calls["n"] > 2,
            f"post called {calls['n']}x")
    _assert("(j) ZERO SeasonAllocation rows persist", d_j["rows"] == 0, f"delta={d_j['rows']}")
    _assert("(j) ZERO ledger entries persist", d_j["entries"] == 0, f"delta={d_j['entries']}")
    _assert("(j) ALL DELTAS ZERO", all_zero(d_j, teams_j), str(d_j))
    with SessionLocal() as db:
        left = db.query(SeasonAllocation).filter(
            SeasonAllocation.league_id == league_j).count()
    _assert("(j) no allocation row for the failed league at all", left == 0, f"got {left}")

    # ── (k) session=db passed; no independent commit ──────────────────────
    print("\n(k) post() receives session=db; no independent commit inside activation")
    tdb.reset()
    league_k, teams_k = seed_league()
    before_k = snapshot(teams_k)

    seen = {"sessions": [], "commits": 0}
    real_post_k = sa.ledger_post

    def recording_post(entries, door, session=None):
        seen["sessions"].append(session)
        return real_post_k(entries, door, session=session)

    sa.ledger_post = recording_post
    try:
        with SessionLocal() as db:
            original_commit = db.commit

            def counting_commit():
                seen["commits"] += 1
                return original_commit()

            db.commit = counting_commit
            # Do NOT commit here — activate owns the commit. If any helper
            # committed independently, the rollback below could not erase it.
            activate_season_allocation(league_k, db)
            caller_session = db
    finally:
        sa.ledger_post = real_post_k

    after_k = snapshot(teams_k)
    d_k = deltas(before_k, after_k, teams_k)

    _assert("(k) post() called once per team", len(seen["sessions"]) == TEAM_COUNT,
            f"got {len(seen['sessions'])}")
    _assert("(k) EVERY post() received session= explicitly (never None)",
            all(s is not None for s in seen["sessions"]))
    _assert("(k) every post() received THE SAME session the caller supplied",
            all(s is caller_session for s in seen["sessions"]))
    _assert("(k) exactly ONE commit on that session for the whole activation",
            seen["commits"] == 1, f"got {seen['commits']}")
    _assert("(k) the single commit persisted the work",
            d_k["rows"] == TEAM_COUNT and d_k["entries"] == 3 * TEAM_COUNT,
            f"rows={d_k['rows']} entries={d_k['entries']}")

    # Rollback proof: post() must not have committed internally. Re-run the
    # ledger's own session-provided proof through our door.
    print("    rollback proof — post(session=caller) writes nothing if caller rolls back")
    tb_before_rb = trial_balance()
    w_before_rb = balance_of("wallet:rb_probe")
    with SessionLocal() as rb:
        real_post_k(
            [("world", -stop.buyin_cents),
             ("wallet:rb_probe", stop.min_reserve_cents),
             ("reserve:rb_probe", stop.reserve_cents)],
            door="season_allocation",
            session=rb,
        )
        rb.rollback()
    _assert("(k) rolled-back posting left wallet:rb_probe untouched",
            balance_of("wallet:rb_probe") - w_before_rb == 0)
    _assert("(k) rolled-back posting left trial_balance unchanged",
            trial_balance() - tb_before_rb == 0)

    # ── (l) unique constraint present and enforced ────────────────────────
    print("\n(l) uq_season_allocation_league_team_season present and enforced")
    insp = inspect(tdb.engine)
    uq_names = {c.get("name") for c in insp.get_unique_constraints("season_allocation")}
    fk_names = {c.get("name") for c in insp.get_foreign_keys("season_allocation")}
    _assert("(l) uq_season_allocation_league_team_season exists in the DB",
            "uq_season_allocation_league_team_season" in uq_names, str(sorted(uq_names)))
    _assert("(l) fk_season_allocation_league exists", "fk_season_allocation_league" in fk_names,
            str(sorted(fk_names)))
    _assert("(l) fk_season_allocation_team exists", "fk_season_allocation_team" in fk_names,
            str(sorted(fk_names)))
    _assert("(l) no status column (row existence IS the state)",
            "status" not in {c["name"] for c in insp.get_columns("season_allocation")})
    _assert("(l) no stripe_* column of any kind",
            not [c["name"] for c in insp.get_columns("season_allocation")
                 if c["name"].startswith("stripe_")])

    before_l = snapshot(teams_k)
    dup_raised = None
    with SessionLocal() as db:
        try:
            db.add(SeasonAllocation(
                league_id=league_k, team_id=teams_k[0], season=config.ALLOCATION_SEASON,
                buyin_cents=stop.buyin_cents, min_reserve_cents=stop.min_reserve_cents,
                reserve_cents=stop.reserve_cents,
            ))
            db.commit()
        except IntegrityError as e:
            dup_raised = e
            db.rollback()
    after_l = snapshot(teams_k)
    _assert("(l) duplicate (league, team, season) rejected by the constraint",
            dup_raised is not None)
    _assert("(l) rejected duplicate left row count unchanged",
            after_l["rows"] - before_l["rows"] == 0)

    # ── (m) concurrency race ──────────────────────────────────────────────
    #
    # TWO PARTS, because a barrier alone cannot guarantee contention.
    #
    # m1 is DETERMINISTIC and forces the dangerous interleaving: a holder
    # session INSERTs one (league, team, season) row and leaves it
    # UNCOMMITTED, so a concurrent activation's existence check sees nothing
    # committed, takes the create path, and then BLOCKS on the unique index.
    # Releasing the holder makes the contender's flush fail. This is the only
    # arrangement that actually exercises uq_... as the final race guard, and
    # it proves the loser leaves no partial state.
    #
    # m2 is the barrier race over several rounds. Its outcome was formerly
    # timing-dependent: a loser that read AFTER the winner committed took the
    # idempotent replay path (created=False, nothing posted), while a loser
    # that read BEFORE hit the uq guard and rolled back. Both are correct
    # outcomes and the assertions below still accept either.
    #
    # EVIDENCE (R-9, UPDATED BY B6 GROUP B). Runs recorded before Group B
    # tallied {'created': N, 'replayed': 0, 'raced': N} — the loser ALWAYS
    # took the unique-constraint path, and the concurrent replay-loser path
    # was never observed. Group B's League row lock removed that
    # indeterminacy: both racers now serialize on the League row, so the
    # loser reads the winner's committed state and the tally reads
    # {'created': N, 'replayed': N, 'raced': 0}. The assertions are unchanged
    # and the printed tally remains the honest record of what occurred.
    #
    # What must hold every round is the money invariant: exactly one thread
    # reports created=True and exactly one activation's worth of money moves.
    print("\n(m1) deterministic contention: uncommitted row blocks a concurrent activation")
    tdb.reset()
    league_m1, teams_m1 = seed_league()
    before_m1 = snapshot(teams_m1)

    hold_started = threading.Event()
    release_a    = threading.Event()
    m1: dict = {}
    HOLD_S = 1.5      # how long the holder keeps its row uncommitted

    def holder():
        with SessionLocal() as dba:
            dba.add(SeasonAllocation(
                league_id=league_m1, team_id=teams_m1[0], season=config.ALLOCATION_SEASON,
                buyin_cents=stop.buyin_cents, min_reserve_cents=stop.min_reserve_cents,
                reserve_cents=stop.reserve_cents,
            ))
            dba.flush()            # row exists in A's transaction, uncommitted
            hold_started.set()
            release_a.wait(timeout=20)
            dba.commit()

    def contender():
        hold_started.wait(timeout=20)
        m1["start"] = time.monotonic()
        with SessionLocal() as dbb:
            try:
                activate_season_allocation(league_m1, dbb)
                m1["outcome"] = "ok"
            except Exception as e:      # noqa: BLE001 — recording, not swallowing
                m1["outcome"] = "err"
                m1["exc"] = e
        m1["end"] = time.monotonic()

    th_a = threading.Thread(target=holder)
    th_b = threading.Thread(target=contender)
    th_a.start()
    th_b.start()
    hold_started.wait(timeout=20)
    time.sleep(HOLD_S)                  # let B reach the unique-index block
    m1["released"] = time.monotonic()
    release_a.set()
    th_a.join(timeout=30)
    th_b.join(timeout=30)

    after_m1 = snapshot(teams_m1)
    d_m1 = deltas(before_m1, after_m1, teams_m1)

    # Blocking is asserted on DURATION, not on a strict end>released compare.
    # The holder is held for HOLD_S; a contender that truly blocks on the
    # unique index cannot return until the holder commits, so its own elapsed
    # time is ~HOLD_S. A contender that never blocked returns in tens of
    # milliseconds and fails this decisively. The strict end>released form was
    # flaky: time.monotonic() has ~15.6ms granularity on Windows and the
    # unblock->raise->exit sequence can complete inside a single tick, so
    # end==released is observable even when blocking genuinely occurred.
    m1_elapsed = m1.get("end", 0) - m1.get("start", 0)
    _assert("(m1) contender was genuinely BLOCKED on the holder for ~the hold duration",
            m1_elapsed >= HOLD_S * 0.66,
            f"contender elapsed {m1_elapsed:.2f}s vs hold {HOLD_S:.2f}s "
            f"(released at +{m1.get('released', 0) - m1.get('start', 0):.2f}s)")
    _assert("(m1) contender lost — activation raised rather than double-allocating",
            m1.get("outcome") == "err", f"outcome={m1.get('outcome')}")
    _assert("(m1) the loser hit the unique race guard",
            isinstance(m1.get("exc"), IntegrityError),
            f"got {type(m1.get('exc')).__name__}")
    _assert("(m1) loser left ZERO ledger entries — no partial state",
            d_m1["entries"] == 0, f"delta={d_m1['entries']}")
    _assert("(m1) only the holder's single row exists — loser's rows all rolled back",
            d_m1["rows"] == 1, f"delta={d_m1['rows']}")
    _assert("(m1) ZERO money deltas from the loser",
            d_m1["world"] == 0
            and all(d_m1["wallet"][t] == 0 for t in teams_m1)
            and all(d_m1["reserve"][t] == 0 for t in teams_m1),
            str(d_m1))
    _assert("(m1) trial_balance still 0", after_m1["trial"] == 0, f"got {after_m1['trial']}")

    print("\n(m2) barrier race x3: exactly one activation's worth of money moves each round")
    ROUNDS = 3
    tally = {"created": 0, "replayed": 0, "raced": 0, "overlapped": 0}
    for rnd in range(ROUNDS):
        tdb.reset()
        league_m, teams_m = seed_league()
        before_m = snapshot(teams_m)

        barrier = threading.Barrier(2)
        outcomes: list[tuple[str, object]] = []
        windows: list[tuple[float, float]] = []
        lock = threading.Lock()

        def racer():
            t0 = t1 = 0.0
            try:
                with SessionLocal() as db:
                    barrier.wait(timeout=10)       # release both at once
                    t0 = time.monotonic()
                    res = activate_season_allocation(league_m, db)
                    t1 = time.monotonic()
                with lock:
                    outcomes.append(("ok", res))
            except Exception as e:                  # noqa: BLE001 — recording
                t1 = time.monotonic()
                with lock:
                    outcomes.append(("err", e))
            with lock:
                windows.append((t0, t1))

        threads = [threading.Thread(target=racer) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        after_m = snapshot(teams_m)
        d_m = deltas(before_m, after_m, teams_m)

        created = [o for o in outcomes if o[0] == "ok" and o[1].created is True]
        replayed = [o for o in outcomes if o[0] == "ok" and o[1].created is False]
        raced = [o for o in outcomes if o[0] == "err"]
        tally["created"] += len(created)
        tally["replayed"] += len(replayed)
        tally["raced"] += len(raced)
        if len(windows) == 2 and min(w[1] for w in windows) > max(w[0] for w in windows):
            tally["overlapped"] += 1

        loser = "replay" if replayed else ("uq-race" if raced else "NONE")
        _assert(f"(m2 r{rnd}) both threads finished", len(outcomes) == 2, str(len(outcomes)))
        _assert(f"(m2 r{rnd}) exactly ONE thread activated (created=True)",
                len(created) == 1, f"created={len(created)} replayed={len(replayed)} raced={len(raced)}")
        _assert(f"(m2 r{rnd}) the other left no partial state (loser={loser})",
                len(replayed) + len(raced) == 1, str(outcomes))
        _assert(f"(m2 r{rnd}) exactly one row per team — no doubles",
                d_m["rows"] == TEAM_COUNT, f"delta={d_m['rows']}")
        _assert(f"(m2 r{rnd}) exactly three ledger entries per team — money moved once",
                d_m["entries"] == 3 * TEAM_COUNT, f"delta={d_m['entries']}")
        _assert(f"(m2 r{rnd}) min_reserve credited exactly once per team",
                all(d_m["min_reserve"][t] == stop.min_reserve_cents for t in teams_m),
                str(d_m["min_reserve"]))
        _assert(f"(m2 r{rnd}) wallet stayed at zero throughout the race",
                all(d_m["wallet"][t] == 0 for t in teams_m), str(d_m["wallet"]))
        _assert(f"(m2 r{rnd}) reserve credited exactly once per team",
                all(d_m["reserve"][t] == stop.reserve_cents for t in teams_m), str(d_m["reserve"]))
        _assert(f"(m2 r{rnd}) season_issuance debited exactly once per team",
                d_m["issuance"] == -(stop.buyin_cents * TEAM_COUNT),
                f"delta={d_m['issuance']}")
        _assert(f"(m2 r{rnd}) trial_balance still 0 after the race",
                after_m["trial"] == 0, f"got {after_m['trial']}")

    print(f"    outcome distribution over {ROUNDS} rounds: {tally}")
    _assert("(m2) exactly one activation per round across all rounds",
            tally["created"] == ROUNDS, str(tally))
    _assert("(m2) every round's loser was a replay or a uq-race, never a second activation",
            tally["replayed"] + tally["raced"] == ROUNDS, str(tally))

    # ── guard: empty league refused ───────────────────────────────────────
    print("\n(extra) empty league refused rather than vacuously 'complete'")
    tdb.reset()
    with SessionLocal() as db:
        empty = League(season=config.ALLOCATION_SEASON, name="Empty League")
        db.add(empty)
        db.commit()
        empty_id = empty.id
    raised_e = None
    with SessionLocal() as db:
        try:
            activate_season_allocation(empty_id, db)
        except Exception as e:
            raised_e = e
    _assert("empty league raises NoTeamsError", isinstance(raised_e, NoTeamsError),
            f"got {type(raised_e).__name__}")

    # ── (n) rows carry the ALLOCATION season, not the projection season ───
    print("\n(n) created rows carry season == config.ALLOCATION_SEASON")
    tdb.reset()
    league_n, teams_n = seed_league()
    with SessionLocal() as db:
        res_n = activate_season_allocation(league_n, db)
    with SessionLocal() as db:
        seasons_n = {
            r.season for r in db.query(SeasonAllocation)
            .filter(SeasonAllocation.league_id == league_n).all()
        }
    _assert("(n) config.ALLOCATION_SEASON == 2026",
            config.ALLOCATION_SEASON == 2026, f"got {config.ALLOCATION_SEASON}")
    _assert("(n) ALLOCATION_SEASON is a SEPARATE setting from CURRENT_SEASON",
            config.ALLOCATION_SEASON != config.CURRENT_SEASON,
            f"allocation={config.ALLOCATION_SEASON} projection={config.CURRENT_SEASON}")
    _assert("(n) every created row carries season == ALLOCATION_SEASON",
            seasons_n == {config.ALLOCATION_SEASON}, f"got {seasons_n}")
    _assert("(n) result.season == ALLOCATION_SEASON",
            res_n.season == config.ALLOCATION_SEASON, f"got {res_n.season}")
    _assert("(n) NO row was stamped with the projection year CURRENT_SEASON",
            config.CURRENT_SEASON not in seasons_n, f"got {seasons_n}")

    # ── (o)(p) gate season-qualification ──────────────────────────────────
    #
    # The gate must key on (league, team, ALLOCATION_SEASON). An unqualified
    # existence check would let a prior season's row open this season's gate,
    # so (o) gives the GM a CURRENT_SEASON-only row and requires a block.
    # (o) also sets the legacy buy_in_paid flag to 1: if the gate were still
    # reading it (the Group 1 behavior), the GM would wrongly pass.
    def _make_gm(league_id: int, team_id: int, tag: str, buy_in_paid: int = 0) -> int:
        with SessionLocal() as db:
            lg = db.query(League).filter(League.id == league_id).one()
            lg.buyin_enforcement_active = True          # enforcement ON
            u = User(
                email           = f"gm_{tag}_{league_id}@example.test",
                hashed_password = "not-a-real-hash",
                team_id         = team_id,
                role            = "gm",
                buy_in_paid     = buy_in_paid,
            )
            db.add(u)
            db.commit()
            return u.id

    def _run_gate(user_id: int):
        """Returns ('pass', user) or ('block', status_code)."""
        with SessionLocal() as db:
            user = db.query(User).filter(User.id == user_id).one()
            try:
                returned = get_season_allocation_gate(current_user=user, db=db)
                return ("pass", returned)
            except HTTPException as e:
                return ("block", e.status_code)

    print("\n(o) a 2025-ONLY allocation does NOT satisfy the gate")
    tdb.reset()
    league_o, teams_o = seed_league()
    user_o = _make_gm(league_o, teams_o[0], "o", buy_in_paid=1)
    with SessionLocal() as db:
        db.add(SeasonAllocation(
            league_id=league_o, team_id=teams_o[0],
            season=config.CURRENT_SEASON,               # prior season ONLY
            buyin_cents=stop.buyin_cents, min_reserve_cents=stop.min_reserve_cents,
            reserve_cents=stop.reserve_cents,
        ))
        db.commit()
    outcome_o = _run_gate(user_o)

    _assert("(o) enforcement ON + prior-season-only allocation -> BLOCKED",
            outcome_o[0] == "block", f"got {outcome_o[0]}")
    _assert("(o) blocked with HTTP 402", outcome_o[1] == 402, f"got {outcome_o[1]}")
    _assert("(o) legacy buy_in_paid=1 did NOT open the gate "
            "(proves the retarget off User.buy_in_paid)",
            outcome_o[0] == "block")

    print("\n(p) a 2026 allocation DOES satisfy the gate")
    tdb.reset()
    league_p, teams_p = seed_league()
    user_p = _make_gm(league_p, teams_p[0], "p", buy_in_paid=0)
    with SessionLocal() as db:
        activate_season_allocation(league_p, db)
    outcome_p = _run_gate(user_p)

    _assert("(p) enforcement ON + ALLOCATION_SEASON allocation -> PASSES",
            outcome_p[0] == "pass", f"got {outcome_p}")
    _assert("(p) gate returned the same user object",
            outcome_p[0] == "pass" and outcome_p[1].id == user_p)
    _assert("(p) passed with buy_in_paid=0 "
            "(allocation existence alone is what satisfies the gate)",
            outcome_p[0] == "pass")

    print("\n(o/p control) enforcement OFF -> gate inactive regardless of season")
    tdb.reset()
    league_q, teams_q = seed_league()
    user_q = _make_gm(league_q, teams_q[0], "q", buy_in_paid=0)
    with SessionLocal() as db:                      # turn enforcement back OFF
        lg = db.query(League).filter(League.id == league_q).one()
        lg.buyin_enforcement_active = False
        db.commit()
    outcome_q = _run_gate(user_q)
    _assert("(control) enforcement OFF + no allocation at all -> PASSES "
            "(early-return branch preserved)",
            outcome_q[0] == "pass", f"got {outcome_q}")

    # ── (s) replay leaves NO active transaction ───────────────────────────
    print("\n(s) replay leaves no active transaction on the caller's session")
    tdb.reset()
    league_s, teams_s = seed_league()
    with SessionLocal() as db:
        activate_season_allocation(league_s, db)          # create
    before_s = snapshot(teams_s)
    with SessionLocal() as db:
        res_s = activate_season_allocation(league_s, db)  # replay
        in_tx_after_replay = db.in_transaction()
    after_s = snapshot(teams_s)
    d_s = deltas(before_s, after_s, teams_s)

    _assert("(s) replay left NO active transaction (single terminal posture)",
            in_tx_after_replay is False, f"in_transaction()={in_tx_after_replay}")
    _assert("(s) replay created=False", res_s.created is False)
    _assert("(s) replay posting_ids == ()", res_s.posting_ids == ())
    _assert("(s) replay posted nothing — ALL DELTAS ZERO", all_zero(d_s, teams_s), str(d_s))

    # ── (q)(r) ROUTE-LEVEL error mapping ──────────────────────────────────
    #
    # (r) is the R-1 regression guard. ledger.py's LedgerImbalanceError,
    # InsufficientFundsError and AlreadySettledError all subclass ValueError.
    # An `except ValueError` in the route would turn a conservation failure
    # into a quiet HTTP 400 carrying an internal message, so it would never
    # page as a 5xx. This asserts such an error is NOT 400 and surfaces as a
    # server error instead.
    print("\n(q)(r) route-level error mapping")
    from fastapi.testclient import TestClient
    import api.main as api_main
    from ledger.ledger import LedgerImbalanceError

    tdb.reset()
    league_r, teams_r = seed_league()
    with SessionLocal() as db:
        comm = User(email=f"comm_r_{league_r}@example.test",
                    hashed_password="not-a-real-hash", team_id=None,
                    role="commissioner", buy_in_paid=0)
        db.add(comm)
        db.commit()

    def _override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def _override_comm():
        with SessionLocal() as db:
            return db.query(User).filter(User.role == "commissioner").first()

    api_main.app.dependency_overrides[api_main.get_db] = _override_db
    # The season-allocation route is now league-scoped: it depends on
    # require_league_commissioner, not the global require_commissioner. These
    # scenarios exercise the route's ERROR MAPPING, not its authorization —
    # authorization is proven exhaustively in
    # test_league_commissioner_authority_pg.py — so the league-scoped
    # dependency is overridden here to stand in for an authorized caller.
    # Both names are overridden so the block stays correct if either is used.
    api_main.app.dependency_overrides[api_main.require_commissioner] = _override_comm
    api_main.app.dependency_overrides[api_main.require_league_commissioner] = _override_comm
    client = TestClient(api_main.app, raise_server_exceptions=False)

    try:
        # (q) NoTeamsError -> 400
        with SessionLocal() as db:
            empty_q = League(season=config.ALLOCATION_SEASON, name="Empty For Route")
            db.add(empty_q)
            db.commit()
            empty_q_id = empty_q.id
        resp_q = client.post(f"/league/{empty_q_id}/season-allocation")
        _assert("(q) NoTeamsError -> HTTP 400", resp_q.status_code == 400,
                f"got {resp_q.status_code}")

        # sanity: the happy path still works through the route
        resp_ok = client.post(f"/league/{league_r}/season-allocation")
        _assert("(q) happy path -> HTTP 200 created=true",
                resp_ok.status_code == 200 and resp_ok.json()["created"] is True,
                f"got {resp_ok.status_code} {resp_ok.text[:120]}")

        # (q) conflicting/partial -> 409, still mapped
        with SessionLocal() as db:
            victim = (db.query(SeasonAllocation)
                      .filter(SeasonAllocation.league_id == league_r,
                              SeasonAllocation.team_id == teams_r[-1]).one())
            db.delete(victim)
            db.commit()
        resp_409 = client.post(f"/league/{league_r}/season-allocation")
        _assert("(q) PartialAllocationError -> HTTP 409", resp_409.status_code == 409,
                f"got {resp_409.status_code}")

        # (r) injected ledger conservation failure must NOT become a 400
        real_activate = api_main.activate_season_allocation

        def imbalanced(_league_id, _db):
            raise LedgerImbalanceError(
                "injected: posting does not balance — entries sum to 1 cent, not zero"
            )

        api_main.activate_season_allocation = imbalanced
        try:
            before_r = snapshot(teams_r)
            resp_r = client.post(f"/league/{league_r}/season-allocation")
            after_r = snapshot(teams_r)
        finally:
            api_main.activate_season_allocation = real_activate

        _assert("(r) LedgerImbalanceError is NOT converted to HTTP 400",
                resp_r.status_code != 400, f"got {resp_r.status_code}")
        _assert("(r) LedgerImbalanceError is NOT converted to HTTP 409",
                resp_r.status_code != 409, f"got {resp_r.status_code}")
        _assert("(r) it surfaces as a 5xx server error (pages, not swallowed)",
                500 <= resp_r.status_code < 600, f"got {resp_r.status_code}")
        _assert("(r) the internal message did NOT leak into a 4xx body",
                "does not balance" not in resp_r.text or resp_r.status_code >= 500,
                f"status={resp_r.status_code}")
        _assert("(r) nothing was mutated by the failed request",
                all_zero(deltas(before_r, after_r, teams_r), teams_r))
    finally:
        api_main.app.dependency_overrides.clear()

    # ── (t) PERSISTED LEDGER-DOOR INVARIANT ───────────────────────────────────
    #
    # The AST guard in test_stripe_removal_regression.py proves, from SOURCE,
    # that only activate_season_allocation() constructs a reserve:{...} leg.
    # This assertion is the runtime counterpart: it reads the PERSISTED
    # LedgerEntry rows back out of PostgreSQL and proves every reserve:% row
    # actually carries door="season_allocation".
    #
    # SCOPE, STATED EXACTLY. These are the rows produced by THIS suite's setup
    # in the disposable _test database created by setup_postgres_test_db().
    # No production database is inspected and NO claim is made about historical
    # production rows — none are visible here and none were read.
    #
    # Other SQLite suites (test_ledger.py, test_championship_payout.py)
    # deliberately post reserve legs with door="buy_in_paid"/"buy_in_tab" as
    # HISTORICAL fixtures for the pre-B2 funding model. They are a different
    # database and a different scope; this assertion does not reach them and
    # was not weakened to accommodate them.
    print("\n(t) persisted reserve entries all carry door='season_allocation'")

    with SessionLocal() as db:
        reserve_rows = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.account.like("reserve:%"))
            .all()
        )
        doors = sorted({r.door for r in reserve_rows})
        offenders = [(r.account, r.door, r.amount_cents)
                     for r in reserve_rows if r.door != "season_allocation"]

    _assert("(t) the suite actually persisted reserve rows to inspect",
            len(reserve_rows) > 0, f"got {len(reserve_rows)} rows")
    _assert("(t) EVERY persisted reserve:% row has door='season_allocation'",
            offenders == [], f"offending rows: {offenders}")
    _assert("(t) exactly one distinct door across all reserve rows",
            doors == ["season_allocation"], f"distinct doors: {doors}")
    _assert("(t) reserve row count equals one per allocated team",
            len(reserve_rows) == len({r.account for r in reserve_rows}),
            f"{len(reserve_rows)} rows over "
            f"{len({r.account for r in reserve_rows})} distinct accounts")



def _rows_match_stop(SessionLocal, SeasonAllocation, league_id, season, stop) -> bool:
    with SessionLocal() as db:
        rows = (
            db.query(SeasonAllocation)
            .filter(SeasonAllocation.league_id == league_id,
                    SeasonAllocation.season == season)
            .all()
        )
        return bool(rows) and all(
            (r.buyin_cents, r.min_reserve_cents, r.reserve_cents)
            == (stop.buyin_cents, stop.min_reserve_cents, stop.reserve_cents)
            for r in rows
        )


try:
    main(tdb)
finally:
    tdb.teardown()


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*60}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
