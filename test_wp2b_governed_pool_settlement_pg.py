"""
test_wp2b_governed_pool_settlement_pg.py — WP2B · governed Pool lifecycle.

WHAT THIS PROVES, AND WHY IT IS NOT A MOCK TEST. The whole point of WP2B is that
the REAL production assembly feeds the REAL certified settlement engine, so
nothing here substitutes a synthetic stat object. The chain exercised is:

    HTTP POST (commissioner)
      -> betting.pool_funding.collect_weekly_entries      (governed collection)
    HTTP POST (commissioner)
      -> providers.yahoo.week_snapshot.fetch_week_snapshot(with_rosters=True)
      -> providers.yahoo.identity.build_team_identity_resolver
      -> providers.yahoo.pool_source.YahooProviderStatSource
      -> betting.pool_settlement.settle_week
      -> ledger postings + persisted `settled` state

The ONLY substitution is the transport: `api.main._pool_settlement_transport` is
pointed at `FixtureTransport` so the suite runs offline with no credentials.
That seam exists precisely so the rest of the chain can be the real thing.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)
os.environ.setdefault("JWT_SECRET_KEY", "wp2b-suite-secret")

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP2B suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n== {title} ==")


PASSWORD = "wp2b-password"
WEEK = 1


def main() -> None:
    from fastapi.testclient import TestClient

    import api.main as main_mod
    from api.main import app
    from auth.jwt_auth import hash_password
    from db.schema import (
        LeagueCommissioner, PoolInstance, PoolPot, SessionLocal, User,
    )
    from economy.season_allocation import activate_season_allocation
    from ledger.ledger import balance_of, trial_balance
    from providers.certify.run import (
        FROZEN_NOW, LEAGUE_KEY, seed_provider_league,
    )
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo.persist import refresh_league_week
    from providers.yahoo.week_snapshot import fetch_week_snapshot

    # THE ONLY SUBSTITUTION: offline transport, real everything else.
    main_mod._pool_settlement_transport = lambda: FixtureTransport(
        frozen_now=FROZEN_NOW)

    def client() -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    def bearer(email: str) -> dict:
        r = client().post("/auth/login",
                          data={"username": email, "password": PASSWORD})
        assert r.status_code == 200, f"login failed: {r.text}"
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    tdb.reset()

    # ── Seed: provider-bound league, commissioner, allocation, refreshed week ──
    with SessionLocal() as db:
        league, teams = seed_provider_league(db, name="WP2B League")
        db.commit()
        league_id = league.id
        team_ids = [t.id for t in teams]

        pw = hash_password(PASSWORD)
        comm = User(email="wp2b-comm@x.test", hashed_password=pw,
                    team_id=team_ids[0], role="commissioner")
        gm = User(email="wp2b-gm@x.test", hashed_password=pw,
                  team_id=team_ids[1], role="gm")
        db.add_all([comm, gm])
        db.flush()
        db.add(LeagueCommissioner(league_id=league_id, user_id=comm.id,
                                  source="bootstrap"))
        db.commit()

        snapshot = fetch_week_snapshot(
            FixtureTransport(frozen_now=FROZEN_NOW),
            league_key=LEAGUE_KEY, week=WEEK, with_rosters=True)
        refresh_league_week(db, snapshot, now=FROZEN_NOW)
        db.commit()

    with SessionLocal() as db:
        activate_season_allocation(league_id, db)

    hdr = bearer("wp2b-comm@x.test")
    hdr_gm = bearer("wp2b-gm@x.test")

    # ════ 0a. CANONICAL CATALOG BOOTSTRAP (WP2B-pre1) ═══════════════════════
    _section("canonical Pool catalog bootstrap is a deployment operation")

    from db.schema import PoolDefinition
    import scripts.bootstrap_pool_catalog as bootstrap

    with SessionLocal() as db:
        _assert("before bootstrap the database carries no Pool definitions",
                db.query(PoolDefinition).count() == 0)
        db.rollback()

    _assert("--check reports drift before bootstrap and exits non-zero",
            bootstrap.main(["--check"]) == 1)
    _assert("bootstrap succeeds", bootstrap.main([]) == 0)

    with SessionLocal() as db:
        after_first = db.query(PoolDefinition).count()
        _assert("bootstrap created the canonical definitions",
                after_first > 0, str(after_first))
        db.rollback()

    _assert("bootstrap is IDEMPOTENT — a second run succeeds",
            bootstrap.main([]) == 0)
    with SessionLocal() as db:
        after_second = db.query(PoolDefinition).count()
        _assert("a second bootstrap inserted no duplicates",
                after_second == after_first, f"{after_second} vs {after_first}")
        db.rollback()
    _assert("--check is clean after bootstrap", bootstrap.main(["--check"]) == 0)

    # ════ 0b. LEAGUE POOL SOURCE ACTIVATION (WP2B-pre2) ═════════════════════
    _section("league Pool source readiness is measured, not assumed")

    _assert("an unauthenticated activation is refused",
            client().post(f"/league/{league_id}/pool/activate?week={WEEK}"
                          ).status_code == 401)
    _assert("a non-commissioner activation is refused",
            client().post(f"/league/{league_id}/pool/activate?week={WEEK}",
                          headers=hdr_gm).status_code == 403)

    r_act = client().post(f"/league/{league_id}/pool/activate?week={WEEK}",
                          headers=hdr)
    _assert("activation succeeds", r_act.status_code == 200,
            f"{r_act.status_code} {r_act.text[:200]}")
    act = r_act.json() if r_act.status_code == 200 else {}
    print(f"     measured={act.get('definitions_measured')} "
          f"ready={act.get('definitions_ready')} "
          f"eligible_now={act.get('eligible_this_phase')} "
          f"stats={len(act.get('supported_stats') or [])}")

    # ── CONTRACT REGRESSION GUARD (Fix 1) ────────────────────────────────────
    # measure_league_activation returns a FOUR-KEY SUMMARY. An earlier draft
    # used len(report) and reported "4". These assertions fail loudly if the
    # summary is ever misread that way again.
    _assert("definitions_measured is the CATALOG size, not the summary key "
            "count (fails if the return contract is misread again)",
            act.get("definitions_measured") == after_first,
            f"{act.get('definitions_measured')} vs catalog {after_first}")
    _assert("definitions_measured is not the summary-key count 4",
            act.get("definitions_measured") != 4,
            str(act.get("definitions_measured")))
    _assert("supported_stats is reported and non-empty",
            len(act.get("supported_stats") or []) > 0,
            str(len(act.get("supported_stats") or [])))
    _assert("definitions_ready is a real count taken from ready_count",
            isinstance(act.get("definitions_ready"), int)
            and 0 < act["definitions_ready"] <= after_first,
            str(act.get("definitions_ready")))
    _assert("the measurement is stamped with the corpus's frozen instant",
            (act.get("measured_at") or "").startswith("2025-09-23"),
            str(act.get("measured_at")))

    # ── FROZEN-INSTANT vs STALE (Fix 2) ──────────────────────────────────────
    # The governed 24-hour window is NOT widened. The corpus is stamped
    # 2025-09-23 and the wall clock is far past it, so the harness evaluates the
    # gate at the frozen instant exactly as providers/certify/run.py C-13 does.
    from datetime import datetime, timedelta, timezone

    from betting.pool_gates import selectable_definitions
    from betting.pool_season_boundary import PHASE_REGULAR
    from providers.yahoo.identity import build_team_identity_resolver
    from providers.yahoo.pool_source import PROVIDER, measure_league_activation

    with SessionLocal() as db:
        fresh = selectable_definitions(db, league_id=league_id,
                                       provider=PROVIDER, phase=PHASE_REGULAR,
                                       now=FROZEN_NOW)
        stale = selectable_definitions(db, league_id=league_id,
                                       provider=PROVIDER, phase=PHASE_REGULAR,
                                       now=FROZEN_NOW + timedelta(hours=25))
        db.rollback()

    print(f"     eligible@frozen={len(fresh)} eligible@+25h={len(stale)}")
    _assert("AT ITS VALID FROZEN INSTANT the measurement yields at least four "
            "eligible definitions, so a slate can be drawn",
            len(fresh) >= 4, str(len(fresh)))
    _assert("BEYOND THE 24-HOUR WINDOW the same measurement is stale and fails "
            "closed — the gate is not weakened",
            len(stale) == 0, str(len(stale)))

    _assert("a repeated activation is safe",
            client().post(f"/league/{league_id}/pool/activate?week={WEEK}",
                          headers=hdr).status_code == 200)
    _assert("one league cannot activate another",
            client().post(f"/league/{league_id}/pool/activate?week={WEEK}",
                          headers=hdr_gm).status_code == 403)

    # ── Re-stamp at the current instant for the LIFECYCLE proof ──────────────
    # In production observed_at is ~now, so the gate is naturally fresh. Under
    # replay the corpus instant is fixed in 2025, so the lifecycle sections
    # below re-measure with a current stamp. This changes NO gate rule and no
    # production code path — it supplies the measured_at a live provider would
    # have supplied. The staleness rule itself was just proven above.
    with SessionLocal() as db:
        snap_now = fetch_week_snapshot(
            FixtureTransport(frozen_now=FROZEN_NOW),
            league_key=LEAGUE_KEY, week=WEEK, with_rosters=True)
        resolver = build_team_identity_resolver(db, league_id=league_id)
        measure_league_activation(db, league_id=league_id, snapshot=snap_now,
                                  resolver=resolver,
                                  measured_at=datetime.now(timezone.utc))
        db.commit()
        live_eligible = selectable_definitions(db, league_id=league_id,
                                               provider=PROVIDER,
                                               phase=PHASE_REGULAR)
        db.rollback()
    _assert("with a current measurement the gate is satisfied against the real "
            "clock, exactly as in production",
            len(live_eligible) >= 4, str(len(live_eligible)))

    # Week Open (WP1) funds the min accounts the Pool entry is sourced from.
    r_open = client().post(f"/league/{league_id}/week/{WEEK}/open", headers=hdr)
    _assert("WP1 Week Open funds the week before Pool collection",
            r_open.status_code == 200, f"{r_open.status_code} {r_open.text[:140]}")

    # ════ 1. GOVERNED COLLECTION ════════════════════════════════════════════
    _section("governed Rev1.3 collection opens and funds the week's Pools")

    _assert("an unauthenticated collect is refused",
            client().post(f"/league/{league_id}/pool/collect/{WEEK}").status_code == 401)
    _assert("a non-commissioner collect is refused",
            client().post(f"/league/{league_id}/pool/collect/{WEEK}",
                          headers=hdr_gm).status_code == 403)

    r_c = client().post(f"/league/{league_id}/pool/collect/{WEEK}", headers=hdr)
    _assert("governed collection succeeds", r_c.status_code == 200,
            f"{r_c.status_code} {r_c.text[:200]}")
    coll = r_c.json() if r_c.status_code == 200 else {}
    _assert("the slate drew four occurrences",
            len(coll.get("instance_ids", [])) == 4,
            str(coll.get("instance_ids")))
    _assert("every team was charged",
            coll.get("teams_charged") == len(team_ids),
            str(coll.get("teams_charged")))
    _assert("the pool account holds the collected total",
            balance_of(f"pool:{league_id}") > 0,
            str(balance_of(f"pool:{league_id}")))
    _assert("trial balance is zero after collection", trial_balance() == 0)

    r_c2 = client().post(f"/league/{league_id}/pool/collect/{WEEK}", headers=hdr)
    _assert("a repeated collection is refused, not double-charged",
            r_c2.status_code == 409, f"{r_c2.status_code} {r_c2.text[:140]}")

    pool_after_collect = balance_of(f"pool:{league_id}")

    # ════ 2. THE REAL PRODUCTION CHAIN ══════════════════════════════════════
    _section("settlement runs the real provider assembly into the real engine")

    _assert("an unauthenticated settle is refused",
            client().post(f"/league/{league_id}/pool/settle/{WEEK}").status_code == 401)
    _assert("a non-commissioner settle is refused",
            client().post(f"/league/{league_id}/pool/settle/{WEEK}",
                          headers=hdr_gm).status_code == 403)

    r_s = client().post(f"/league/{league_id}/pool/settle/{WEEK}", headers=hdr)
    _assert("governed settlement returns 200", r_s.status_code == 200,
            f"{r_s.status_code} {r_s.text[:300]}")
    body = r_s.json() if r_s.status_code == 200 else {}
    settled = body.get("settled", [])
    refused = body.get("refused", [])
    print(f"     settled={len(settled)} refused={len(refused)} "
          f"container={body.get('week_container_settled')}")
    for item in settled:
        print(f"     - {item['definition_key']}: {item['classification']} "
              f"pot={item['pot_cents']} dist={item['distributed_cents']} "
              f"roll={item['rolled_over_cents']} "
              f"sweep={item['swept_to_championship_cents']} "
              f"winners={item['winning_team_ids']}")
    for r in refused:
        print(f"     - REFUSED: {r[:150]}")

    _assert("the engine reported an outcome for every occurrence",
            len(settled) + len(refused) == 4,
            f"{len(settled)} settled + {len(refused)} refused")
    _assert("every settled occurrence carries a governed classification",
            all(s["classification"] for s in settled), str(settled[:1]))
    _assert("no occurrence paid out more than its pot",
            all(s["distributed_cents"] <= s["pot_cents"] for s in settled))
    _assert("every settled pot is fully accounted for — distributed + rolled "
            "over + swept equals the pot",
            all(s["distributed_cents"] + s["rolled_over_cents"]
                + s["swept_to_championship_cents"] == s["pot_cents"]
                for s in settled),
            str([(s["pot_cents"], s["distributed_cents"], s["rolled_over_cents"],
                  s["swept_to_championship_cents"]) for s in settled]))
    _assert("ZERO-WINNER OCCURRENCES ROLL OVER RATHER THAN PAY",
            all(s["distributed_cents"] == 0
                for s in settled if not s["winning_team_ids"]),
            str([s["definition_key"] for s in settled
                 if not s["winning_team_ids"]]))
    _assert("trial balance is zero after settlement", trial_balance() == 0)

    with SessionLocal() as db:
        n_settled = (db.query(PoolInstance)
                     .filter(PoolInstance.league_id == league_id,
                             PoolInstance.week == WEEK,
                             PoolInstance.settled.is_(True)).count())
        _assert("settled state is PERSISTED, observable by the slate route",
                n_settled == len(settled), f"{n_settled} persisted")
        db.rollback()

    # ════ 3. IDEMPOTENCY / NO DOUBLE PAYOUT ═════════════════════════════════
    _section("repeated settlement cannot pay twice")

    pool_after_settle = balance_of(f"pool:{league_id}")
    r_s2 = client().post(f"/league/{league_id}/pool/settle/{WEEK}", headers=hdr)
    _assert("a repeated settlement still returns 200", r_s2.status_code == 200,
            f"{r_s2.status_code} {r_s2.text[:200]}")
    _assert("a repeated settlement settles nothing further",
            len(r_s2.json().get("settled", [])) == 0,
            str(len(r_s2.json().get("settled", []))))
    _assert("the pool account did not move on the repeat",
            balance_of(f"pool:{league_id}") == pool_after_settle,
            f"{balance_of(f"pool:{league_id}")} vs {pool_after_settle}")
    _assert("trial balance is zero after the repeat", trial_balance() == 0)
    _assert("collection actually moved money before settlement did",
            pool_after_collect > 0, str(pool_after_collect))

    # ════ 4. CROSS-LEAGUE ISOLATION ═════════════════════════════════════════
    _section("cross-league isolation")

    with SessionLocal() as db:
        other, _ = seed_provider_league(db, name="WP2B Other",
                                        bind_identity=False)
        db.commit()
        other_id = other.id

    _assert("league A's commissioner cannot collect for another league",
            client().post(f"/league/{other_id}/pool/collect/{WEEK}",
                          headers=hdr).status_code == 403)
    _assert("league A's commissioner cannot settle another league",
            client().post(f"/league/{other_id}/pool/settle/{WEEK}",
                          headers=hdr).status_code == 403)

    with SessionLocal() as db:
        leaked = (db.query(PoolInstance)
                  .filter(PoolInstance.league_id == other_id).count())
        _assert("the unrelated league has no pool instances at all",
                leaked == 0, str(leaked))
        pots = (db.query(PoolPot)
                .filter(PoolPot.league_id == other_id).count())
        _assert("the unrelated league has no pool pots", pots == 0, str(pots))
        db.rollback()

    # ════ 5. INVALID WEEK ═══════════════════════════════════════════════════
    _section("invalid input refused")

    _assert("week 0 collect refused",
            client().post(f"/league/{league_id}/pool/collect/0",
                          headers=hdr).status_code == 400)
    _assert("week 18 settle refused",
            client().post(f"/league/{league_id}/pool/settle/18",
                          headers=hdr).status_code == 400)


if __name__ == "__main__":
    print("\n=== WP2B governed pool settlement suite (PostgreSQL) ===")
    try:
        main()
    finally:
        tdb.teardown()
    print(f"\n  {len(_failures)} failure(s)")
    if _failures:
        for f in _failures:
            print(f"    FAILED: {f}")
        sys.exit(1)
    print("  ALL PASS")