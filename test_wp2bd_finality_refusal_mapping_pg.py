"""
test_wp2bd_finality_refusal_mapping_pg.py — WP2B-D · the finality refusal's
client-visible shape.

WHAT WAS WRONG, AND WHAT WAS NOT. WP2B-C proved the economic behaviour was
already right: a governed Pool week whose `Matchup.finalized_at` is NULL refuses
before any economic work, moves not one cent, and leaves every occurrence
unsettled and cleanly retryable. What it also recorded was that the refusal
reached the client as an UNHANDLED HTTP 500 — `betting.finality_gate
.ResultsNotReadyError` is a plain ValueError and not a member of the
`PoolSettlementRefusedError` family the settle route maps to 409, so it fell
through to the bare `except Exception: raise`. A correct, governed, retryable
decision was being presented as a server fault.

WP2B-D CHANGES THE MAPPING AND NOTHING ELSE. No finality semantics, no change to
`finalized_at`'s authority, no settlement engine change, no ledger change, no
provider change. The gate still lives in the engine and the routes still do not
pre-check it — a second, weaker copy of that rule at the HTTP boundary is how two
definitions of "final" drift apart.

TWO ROUTES, BECAUSE IT WAS ONE LEAK IN TWO PLACES. The governed Pool settlement
route is the one WP2B-C observed. `POST /league/{id}/settle/{week}` — Versus —
leaked identically: its `_assert_slate_fresh` precondition reads `refreshed_at`
and NOTHING ELSE, so a week the provider has refreshed but not declared over
passes that gate and is then refused by the finality gate inside
`betting.settlement_engine.settle_week`. Mapping only one would have left a
single governed condition with two client-visible shapes, which is the outcome
the finality gate's own docstring argues against ("operators matching on two
strings").

THE SUITE IS BUILT TO FAIL IF THE FIX IS A BLANKET CATCH. Two discriminating
controls run alongside the positive proofs:

  * an UNRELATED governed refusal on the same route still returns its own reason
    code, so the new handler did not swallow the existing 409 vocabulary;
  * a genuinely UNEXPECTED exception from the settlement engine still surfaces
    as a 500, so the new clause is specific rather than an `except Exception`
    that would launder a real fault into a retryable-looking conflict.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)
os.environ.setdefault("JWT_SECRET_KEY", "wp2bd-suite-secret")

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP2B-D suite cannot run:\n  {e}")
    sys.exit(2)

from datetime import datetime, timedelta, timezone  # noqa: E402

# The WP2B-C corpus and its league definition are the fixture surface here too —
# rebuilding a second economic league would give the mapping proof a different
# data premise than the behaviour proof it is attached to.
from test_support_wp2bc_league import (  # noqa: E402
    FROZEN_NOW, LEAGUE_ID, LEAGUE_KEY, SEASON, TEAM_COUNT,
    seed_economic_league, snapshot_for,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n== {title} ==")


PASSWORD = "wp2bd-password"
WEEK = 2


def main() -> None:
    from fastapi.testclient import TestClient

    import api.main as main_mod
    import betting.pool_settlement as pool_settlement_mod
    from api.main import app
    from auth.jwt_auth import hash_password
    from db.schema import (
        League, LeagueCommissioner, Matchup, PoolInstance, SessionLocal, User,
    )
    from economy.season_allocation import activate_season_allocation
    from ledger.ledger import balance_of, trial_balance
    from providers.fixtures.replay import FixtureTransport
    from providers.yahoo.persist import refresh_league_week

    # THE SEAM TAKES THE LEAGUE NOW (YAHOO-LIVE-1-FIX). The production factory
    # resolves that league's own Yahoo credential owner instead of loading a
    # repository-level operator token, so it needs the session and the league
    # id. The fixture transport needs neither and ignores both — but the
    # substitution has to match the seam's signature or the route raises
    # TypeError and every refusal this suite certifies arrives as a 500.
    main_mod._pool_settlement_transport = (
        lambda db, league_id: FixtureTransport(frozen_now=FROZEN_NOW))

    def client() -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    def bearer(email: str) -> dict:
        r = client().post("/auth/login",
                          data={"username": email, "password": PASSWORD})
        assert r.status_code == 200, f"login failed: {r.text}"
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    tdb.reset()

    # ── Seed: the WP2B-C economic league, week 2 ingested NON-FINAL ─────────
    with SessionLocal() as db:
        league, teams = seed_economic_league(db)
        db.commit()
        team_ids = [t.id for t in teams]

        pw = hash_password(PASSWORD)
        comm = User(email="wp2bd-comm@x.test", hashed_password=pw,
                    team_id=team_ids[0], role="commissioner")
        db.add(comm)
        db.add(User(email="wp2bd-gm@x.test", hashed_password=pw,
                    team_id=team_ids[1], role="gm"))
        db.flush()
        db.add(LeagueCommissioner(league_id=league.id, user_id=comm.id,
                                  source="bootstrap"))
        db.commit()

    with SessionLocal() as db:
        refresh_league_week(db, snapshot_for(
            FixtureTransport(frozen_now=FROZEN_NOW), WEEK,
            scoreboard_id="yahoo_wp2bc_scoreboard_w2_pending"), now=FROZEN_NOW)
        db.commit()

    with SessionLocal() as db:
        activate_season_allocation(LEAGUE_ID, db)

    hdr = bearer("wp2bd-comm@x.test")

    import scripts.bootstrap_pool_catalog as bootstrap
    _assert("catalog bootstrap succeeds", bootstrap.main([]) == 0)

    from providers.yahoo.identity import build_team_identity_resolver
    from providers.yahoo.pool_source import measure_league_activation

    with SessionLocal() as db:
        measure_league_activation(
            db, league_id=LEAGUE_ID,
            snapshot=snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW), WEEK),
            resolver=build_team_identity_resolver(db, league_id=LEAGUE_ID),
            measured_at=datetime.now(timezone.utc))
        db.commit()

    # ════ 0. THE PRECONDITION THE PROOF DEPENDS ON ══════════════════════════
    _section("the week is genuinely funded, evaluable, and NOT final")

    with SessionLocal() as db:
        rows = (db.query(Matchup)
                .filter(Matchup.league_id == LEAGUE_ID, Matchup.week == WEEK)
                .all())
        _assert("three matchup rows carry real scores AND a refreshed_at",
                len(rows) == 3
                and all(r.home_score is not None and r.refreshed_at is not None
                        for r in rows),
                str([(r.home_score, r.away_score) for r in rows]))
        _assert("NOT ONE is economically final — finalized_at IS NULL "
                "throughout, which is the only fact the gate reads",
                all(r.finalized_at is None for r in rows))
        db.rollback()

    _assert("WP1 Week Open funds the week",
            client().post(f"/league/{LEAGUE_ID}/week/{WEEK}/open",
                          headers=hdr).status_code == 200)
    r_c = client().post(f"/league/{LEAGUE_ID}/pool/collect/{WEEK}", headers=hdr)
    _assert("governed collection succeeds, so the refusal below is about "
            "FINALITY and not about an unfunded or undrawn week",
            r_c.status_code == 200, f"{r_c.status_code} {r_c.text[:220]}")
    _assert("the week holds four funded occurrences",
            len(r_c.json().get("instance_ids", [])) == 4)

    # ════ 1. THE MAPPING — governed Pool settlement ═════════════════════════
    _section("PROOF — non-final governed Pool settlement is a 409, not a 500")

    def snapshot_ledger() -> dict:
        return {
            "pool": balance_of(f"pool:{LEAGUE_ID}"),
            "championship": balance_of(f"championship:{LEAGUE_ID}"),
            "trial": trial_balance(),
            **{f"wallet:{tid}": balance_of(f"wallet:{tid}") for tid in team_ids},
        }

    before = snapshot_ledger()
    r = client().post(f"/league/{LEAGUE_ID}/pool/settle/{WEEK}", headers=hdr)
    print(f"     HTTP {r.status_code}  body={r.text[:260]}")

    _assert("THE ROUTE RETURNS 409 CONFLICT, not 500", r.status_code == 409,
            str(r.status_code))
    detail = r.json().get("detail") if r.status_code == 409 else None
    _assert("the refusal body is the governed reason-code shape this API "
            "already uses, not a bare string",
            isinstance(detail, dict) and "reason_code" in detail
            and "message" in detail, str(detail)[:200])

    detail = detail if isinstance(detail, dict) else {}
    _assert("the reason code is the engine's OWN accepted vocabulary — "
            "RESULTS_NOT_READY, passed through from exc.reason rather than "
            "restated as a route-local string",
            detail.get("reason_code") == "RESULTS_NOT_READY",
            str(detail.get("reason_code")))

    from betting.finality_gate import REASON_RESULTS_NOT_READY

    _assert("the reason code is STABLE — it is the same constant "
            "economy/skunk.py and the season-close orchestrator name their "
            "refusal after, not a copy that can drift",
            detail.get("reason_code") == REASON_RESULTS_NOT_READY)
    _assert("the refusal is MEANINGFUL — it names the league, the week and the "
            "exact matchup rows that are not final",
            detail.get("league_id") == LEAGUE_ID
            and detail.get("week") == WEEK
            and len(detail.get("unfinalized_matchup_ids") or []) == 3,
            f"league={detail.get('league_id')} week={detail.get('week')} "
            f"ids={detail.get('unfinalized_matchup_ids')}")

    with SessionLocal() as db:
        db_unfinal = sorted(
            m.id for m in db.query(Matchup)
            .filter(Matchup.league_id == LEAGUE_ID, Matchup.week == WEEK,
                    Matchup.finalized_at.is_(None)).all())
        db.rollback()
    _assert("the reported matchup ids are the ACTUAL non-final rows, not a "
            "count or a placeholder",
            sorted(detail.get("unfinalized_matchup_ids") or []) == db_unfinal,
            f"{detail.get('unfinalized_matchup_ids')} vs {db_unfinal}")

    _assert("ZERO LEDGER MUTATION — every account and the trial balance are "
            "byte-identical across the refused call",
            snapshot_ledger() == before,
            str({k: (before[k], snapshot_ledger()[k]) for k in before
                 if before[k] != snapshot_ledger()[k]}))

    with SessionLocal() as db:
        unsettled = (db.query(PoolInstance)
                     .filter(PoolInstance.league_id == LEAGUE_ID,
                             PoolInstance.week == WEEK).all())
        _assert("EVERY PoolInstance REMAINS UNSETTLED, with no classification "
                "and no distribution recorded",
                len(unsettled) == 4
                and all(not i.settled and i.settlement_classification is None
                        and int(i.distributed_cents or 0) == 0
                        and int(i.rollover_cents or 0) == 0
                        for i in unsettled),
                str([(i.settled, i.settlement_classification,
                      i.distributed_cents, i.rollover_cents)
                     for i in unsettled]))
        db.rollback()

    _assert("the refusal is REPEATABLE and still a 409 — a governed conflict is "
            "retryable, not a one-shot error",
            client().post(f"/league/{LEAGUE_ID}/pool/settle/{WEEK}",
                          headers=hdr).status_code == 409)
    _assert("a second refusal moved nothing either", snapshot_ledger() == before)

    # ════ 2. THE SAME LEAK ON THE VERSUS ROUTE ══════════════════════════════
    _section("PROOF — the Versus settle route maps the identical refusal")

    # `_assert_slate_fresh` reads refreshed_at only, so this week passes the
    # freshness precondition and reaches the finality gate — which is exactly
    # why the leak existed here too.
    before_versus = snapshot_ledger()
    r_v = client().post(f"/league/{LEAGUE_ID}/settle/{WEEK}", headers=hdr)
    print(f"     HTTP {r_v.status_code}  body={r_v.text[:200]}")
    _assert("the Versus settle route also returns 409, not 500",
            r_v.status_code == 409, str(r_v.status_code))
    v_detail = r_v.json().get("detail") if r_v.status_code == 409 else {}
    v_detail = v_detail if isinstance(v_detail, dict) else {}
    _assert("it carries the SAME reason code — one condition, one client-"
            "visible name",
            v_detail.get("reason_code") == REASON_RESULTS_NOT_READY,
            str(v_detail.get("reason_code")))
    _assert("the Versus refusal moved no money either",
            snapshot_ledger() == before_versus)

    from db.schema import WeekSettlement

    with SessionLocal() as db:
        claims = (db.query(WeekSettlement)
                  .filter(WeekSettlement.league_id == LEAGUE_ID,
                          WeekSettlement.week == WEEK).count())
        db.rollback()
    _assert("the Versus refusal left NO WeekSettlement claim row — the week "
            "does not now need a recovery token to retry", claims == 0,
            str(claims))

    # ════ 3. DISCRIMINATING CONTROLS — the fix is not a blanket catch ═══════
    _section("CONTROLS — the new clause is specific, not an except-Exception")

    # (a) An UNRELATED governed refusal on the same route keeps its own shape.
    with SessionLocal() as db:
        other = League(season=SEASON, name="WP2BD Unbound",
                       projection_source="fantasypros")
        db.add(other)
        db.flush()
        other_id = other.id
        db.add(LeagueCommissioner(
            league_id=other_id,
            user_id=db.query(User).filter(
                User.email == "wp2bd-comm@x.test").first().id,
            source="bootstrap"))
        db.commit()

    r_other = client().post(f"/league/{other_id}/pool/settle/{WEEK}", headers=hdr)
    other_detail = r_other.json().get("detail", {}) if r_other.content else {}
    _assert("a league with no provider identity still refuses with ITS OWN "
            "reason code — the finality clause did not swallow the existing "
            "409 vocabulary",
            r_other.status_code == 409
            and isinstance(other_detail, dict)
            and other_detail.get("reason_code") == "no_provider_identity",
            f"{r_other.status_code} {str(other_detail)[:140]}")

    # (b) A genuinely UNEXPECTED failure must still be a 500. If the fix had
    #     been written as `except Exception -> 409` it would launder a real
    #     fault into a retryable-looking conflict, and this control is the only
    #     thing that can tell the two implementations apart.
    real_settle = pool_settlement_mod.settle_week

    def _explode(*args, **kwargs):
        raise RuntimeError("WP2B-D control: an unexpected engine fault")

    pool_settlement_mod.settle_week = _explode
    try:
        r_boom = client().post(f"/league/{LEAGUE_ID}/pool/settle/{WEEK}",
                               headers=hdr)
    finally:
        pool_settlement_mod.settle_week = real_settle
    _assert("an UNEXPECTED engine exception still surfaces as 500 — the "
            "mapping is specific to the governed finality refusal",
            r_boom.status_code == 500, str(r_boom.status_code))
    _assert("the restored engine is the real one again",
            pool_settlement_mod.settle_week is real_settle)
    _assert("the control fault moved no money", snapshot_ledger() == before)

    # ════ 4. THE POSITIVE HALF — same route, once finality is persisted ═════
    _section("PROOF — after finality is persisted the same route settles")

    with SessionLocal() as db:
        refresh_league_week(db, snapshot_for(
            FixtureTransport(frozen_now=FROZEN_NOW), WEEK,
            scoreboard_id="yahoo_wp2bc_scoreboard_w2"), now=FROZEN_NOW)
        db.commit()

    with SessionLocal() as db:
        rows = (db.query(Matchup)
                .filter(Matchup.league_id == LEAGUE_ID, Matchup.week == WEEK)
                .all())
        _assert("exactly one fact changed: the same three rows, the same "
                "scores, now final",
                len(rows) == 3
                and all(r.finalized_at is not None for r in rows))
        db.rollback()

    pool_pre = balance_of(f"pool:{LEAGUE_ID}")
    r_ok = client().post(f"/league/{LEAGUE_ID}/pool/settle/{WEEK}", headers=hdr)
    _assert("THE SAME ROUTE, THE SAME WEEK, NOW RETURNS 200",
            r_ok.status_code == 200, f"{r_ok.status_code} {r_ok.text[:300]}")
    settled = r_ok.json().get("settled", []) if r_ok.status_code == 200 else []
    for s in settled:
        print(f"     - {s['definition_key']}: {s['classification']} "
              f"pot={s['pot_cents']} dist={s['distributed_cents']} "
              f"roll={s['rolled_over_cents']} "
              f"sweep={s['swept_to_championship_cents']}")
    _assert("all four occurrences settled and none was refused — not a vacuous "
            "pass over settled=[]",
            len(settled) == 4 and not r_ok.json().get("refused"),
            f"{len(settled)} settled")
    _assert("money DID move once the gate was satisfied, so the 409 above was "
            "the gate and not an empty week",
            balance_of(f"pool:{LEAGUE_ID}") != pool_pre,
            f"{pool_pre} -> {balance_of(f'pool:{LEAGUE_ID}')}")
    _assert("trial balance is zero after the settlement", trial_balance() == 0)

    from betting.pool_settlement import assert_pool_conservation

    with SessionLocal() as db:
        held = assert_pool_conservation(db, league_id=LEAGUE_ID, season=SEASON)
        db.rollback()
    _assert("pool conservation holds against real ledger entries",
            held == balance_of(f"pool:{LEAGUE_ID}"), str(held))


if __name__ == "__main__":
    print("\n=== WP2B-D finality refusal mapping suite (PostgreSQL) ===")
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
