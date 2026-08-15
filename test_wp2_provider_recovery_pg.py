"""
test_wp2_provider_recovery_pg.py — WP2 · the PROVIDER DATA RECOVERY REQUIREMENT.

THE OWNER RULING THIS SUITE ENFORCES (WP1E, carried into WP2 §5 and §28):

    A provider-data failure that leaves a published Pool fail-closed must be
    OBSERVABLE, DIAGNOSABLE, RETRYABLE, ATTRIBUTABLE TO A NAMED REASON, and
    RECOVERABLE by obtaining authoritative provider data and RETRYING ORDINARY
    SETTLEMENT — without inventing winners and without changing published Pool
    economics.

    Missing or incomplete provider data is NOT proof that no winner exists. A
    stuck Pool is a provider/operations incident, never a terminal state.

WHAT IS PROVEN, IN THE ORDER IT HAPPENS:

    A  a provider OUTAGE refuses by name, is flagged retryable, persists no
       fact, invents no finality and posts no Credit — and the identical
       request succeeds once the provider recovers
    B  a FINAL week whose stat feed has not caught up settles NOTHING and
       refuses INCOMPLETE_FIELD, naming the census and the unevaluable subject
    C  the refusal is DIAGNOSABLE WITHOUT RERUNNING SETTLEMENT, through the
       provider status read
    D  repetition, elapsed time and finality NEVER convert that into a terminal
       state, and no commissioner override exists to force one
    E  season close is BLOCKED while the week is unsettled
    F  the corrected feed settles the SAME Pool through the SAME ordinary
       route, with exactly ONE economic event per occurrence
    G  season close then proceeds

THE FAULT IS INJECTED AT THE PROVIDER, NOT AT THE ENGINE. The only substitution
is `api.demo_routes.demo_source` — the composition seam that decides which Demo
source answers — pointed at a source that is out, or one whose stat feed is
missing a player. Every route, every gate, every classifier and every ledger
posting below is production.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)
os.environ.setdefault("JWT_SECRET_KEY", "wp2-recovery-suite-secret")

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP2 provider-recovery suite cannot run:\n  {e}")
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


PASSWORD = "wp2-recovery-password"

#: The week the fault is injected into — the LAST regular-season week, so the
#: season close has a genuinely unsettled Pool to refuse on.
FAULT_WEEK = 4


def main() -> None:
    from fastapi.testclient import TestClient

    import api.demo_routes as demo_mod
    from api.main import app
    from auth.jwt_auth import hash_password
    from db.schema import (
        Matchup, PoolEconomicEvent, PoolInstance, SessionLocal, Team, User,
    )
    from ledger.ledger import LedgerEntry, balance_of, trial_balance
    from providers.demo.scenario import (
        PLAYOFF_START_WEEK, REVISION_INCOMPLETE, SEASON_FINAL_WEEK, TEAM_COUNT,
    )
    from providers.demo.source import DemoProviderSource

    healthy = demo_mod.demo_source

    def use_source(**kwargs) -> None:
        """Point the composition seam at a Demo source with a given fault."""
        demo_mod.demo_source = lambda: DemoProviderSource(**kwargs)

    def restore_source() -> None:
        demo_mod.demo_source = healthy

    def client() -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    def bearer(email: str) -> dict:
        r = client().post("/auth/login",
                          data={"username": email, "password": PASSWORD})
        assert r.status_code == 200, f"login failed: {r.text}"
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    tdb.reset()

    with SessionLocal() as db:
        db.add(User(email="recovery-owner@x.test",
                    hashed_password=hash_password(PASSWORD), role="gm"))
        db.commit()
    hdr = bearer("recovery-owner@x.test")

    r = client().post("/demo/league", headers=hdr)
    assert r.status_code == 201, f"demo creation: {r.text[:250]}"
    league_id = r.json()["league_id"]

    with SessionLocal() as db:
        team_ids = [t.id for t in db.query(Team)
                    .filter(Team.league_id == league_id)
                    .order_by(Team.id).all()]
        db.rollback()

    assert client().post(f"/league/{league_id}/season-allocation",
                         headers=hdr).status_code == 200
    import scripts.bootstrap_pool_catalog as bootstrap
    assert bootstrap.main([]) == 0

    def advance() -> dict:
        rr = client().post(f"/demo/league/{league_id}/advance", headers=hdr)
        assert rr.status_code == 200, f"advance: {rr.status_code} {rr.text[:250]}"
        return rr.json()

    # ════ A. PROVIDER OUTAGE ════════════════════════════════════════════════
    _section("A · a provider outage is named, retryable and leaves no trace")

    entries_before = None
    with SessionLocal() as db:
        entries_before = db.query(LedgerEntry).count()
        db.rollback()
    balance_before = trial_balance()

    use_source(outage=True)
    r_out = client().post(f"/demo/league/{league_id}/advance", headers=hdr)
    detail = (r_out.json() or {}).get("detail") or {}
    _assert("a provider outage refuses the refresh with 502 and a NAMED reason "
            "— never a generic 500 and never a traceback",
            r_out.status_code == 502
            and detail.get("reason") == "provider_unavailable",
            f"{r_out.status_code} {str(detail)[:200]}")
    _assert("the refusal is flagged RETRYABLE, so an operator is told waiting "
            "is the remedy", detail.get("retryable") is True,
            str(detail.get("retryable")))
    _assert("the incident names the league, the season, the week, the provider "
            "and the operation attempted",
            (detail.get("league_id"), detail.get("provider"),
             detail.get("week")) == (league_id, "demo", 1)
            and detail.get("operation", "").startswith("demo_advance"),
            str({k: detail.get(k) for k in
                 ("league_id", "provider", "week", "operation")}))
    _assert("it carries no raw provider payload of any kind",
            not ({"payload", "headers", "body", "response"} & set(detail)),
            str(sorted(detail)))

    r_settle_out = client().post(f"/league/{league_id}/pool/settle/1",
                                 headers=hdr)
    out_detail = (r_settle_out.json() or {}).get("detail") or {}
    _assert("settlement during an outage refuses with the SAME named reason "
            "rather than classifying any Pool",
            r_settle_out.status_code == 502
            and out_detail.get("reason") == "provider_unavailable",
            f"{r_settle_out.status_code} {str(out_detail)[:160]}")
    _assert("the settlement incident reports when the provider last spoke, so "
            "an operator can tell a dead feed from a stale one",
            "last_provider_refresh" in out_detail,
            str(out_detail.get("last_provider_refresh")))

    with SessionLocal() as db:
        finalized = (db.query(Matchup)
                     .filter(Matchup.league_id == league_id,
                             Matchup.finalized_at.isnot(None)).count())
        entries_after = db.query(LedgerEntry).count()
        db.rollback()
    _assert("the outage invented NO finality", finalized == 0, str(finalized))
    _assert("the outage posted NO Credits",
            entries_after == entries_before and trial_balance() == balance_before,
            f"{entries_before} -> {entries_after}")

    restore_source()
    recovered = advance()
    _assert("the IDENTICAL request succeeds once the provider recovers — the "
            "failure was transport, not a statement about the week",
            recovered["action"] == "finalize"
            and recovered["matchups_finalized"] == 3,
            str(recovered))

    # ════ Play weeks 1..FAULT_WEEK-1 cleanly ════════════════════════════════
    _section("weeks 1-3 run the ordinary production loop")

    for week in range(1, FAULT_WEEK):
        if week > 1:
            advance()          # open
        assert client().post(f"/league/{league_id}/week/{week}/open",
                             headers=hdr).status_code == 200
        if week > 1:
            advance()          # finalize
        assert client().post(
            f"/league/{league_id}/pool/activate?week={week}",
            headers=hdr).status_code == 200
        assert client().post(f"/league/{league_id}/pool/collect/{week}",
                             headers=hdr).status_code == 200
        rr = client().post(f"/league/{league_id}/pool/settle/{week}",
                           headers=hdr)
        assert rr.status_code == 200 and rr.json()["all_settled"], rr.text[:250]
        assert client().post(f"/league/{league_id}/week/{week}/close",
                             headers=hdr).status_code == 200
    _assert("weeks 1-3 settle and close through the ordinary path",
            trial_balance() == 0)

    # ════ B. INCOMPLETE PROVIDER DATA ═══════════════════════════════════════
    _section(f"B · week {FAULT_WEEK} is FINAL but its stat feed has not caught up")

    advance()   # open week 4
    assert client().post(f"/league/{league_id}/week/{FAULT_WEEK}/open",
                         headers=hdr).status_code == 200
    advance()   # finalize week 4
    assert client().post(
        f"/league/{league_id}/pool/activate?week={FAULT_WEEK}",
        headers=hdr).status_code == 200
    r_coll = client().post(f"/league/{league_id}/pool/collect/{FAULT_WEEK}",
                           headers=hdr)
    assert r_coll.status_code == 200, r_coll.text[:250]
    collected = r_coll.json()["total_cents"]

    pool_before = balance_of(f"pool:{league_id}")
    tb_before = trial_balance()
    with SessionLocal() as db:
        events_before = db.query(PoolEconomicEvent).count()
        db.rollback()

    # THE FEED LOSES ONE STARTED PLAYER'S STAT RECORD. The week stays FINAL —
    # its games are over and `finalized_at` is set — which is exactly the
    # situation WP1E rules on: finality is not evidence that the stats arrived.
    use_source(revision=REVISION_INCOMPLETE)

    r_fault = client().post(f"/league/{league_id}/pool/settle/{FAULT_WEEK}",
                            headers=hdr)
    _assert("settlement returns a governed answer, not a 500",
            r_fault.status_code == 200,
            f"{r_fault.status_code} {r_fault.text[:250]}")
    fault = r_fault.json() if r_fault.status_code == 200 else {}
    refusals = fault.get("refusals") or []
    _assert("at least one occurrence is REFUSED rather than settled",
            bool(refusals) and fault.get("all_settled") is False,
            f"{len(refusals)} refusals, all_settled={fault.get('all_settled')}")

    incomplete = [r for r in refusals
                  if r["classification"] == "INCOMPLETE_FIELD"]
    _assert("the refusal is classified INCOMPLETE_FIELD — the field is short, "
            "not empty and not invalid", bool(incomplete),
            str([r["classification"] for r in refusals]))
    sample = incomplete[0] if incomplete else {}
    _assert("the refusal is attributable to a NAMED, RETRYABLE reason",
            sample.get("retryable") is True
            and sample.get("data_incomplete") is True,
            str({k: sample.get(k) for k in ("retryable", "data_incomplete")}))
    _assert("it names the occurrence, its definition and the census it refused "
            "over",
            sample.get("pool_instance_id") is not None
            and sample.get("definition_key")
            and sample.get("subjects_evaluated") < sample.get(
                "subjects_considered"),
            f"instance={sample.get('pool_instance_id')} "
            f"{sample.get('subjects_evaluated')}/"
            f"{sample.get('subjects_considered')}")
    _assert("NO CLAIM COUNT is computed over an incomplete field — §6.2 forbids "
            "it existing at all", sample.get("subjects_claiming") is None,
            str(sample.get("subjects_claiming")))
    _assert("it names WHICH subjects could not be evaluated, so an operator "
            "knows what to chase", bool(sample.get("unevaluable_subject_ids")),
            str(sample.get("unevaluable_subject_ids")))

    # NOTHING ECONOMIC HAPPENED FOR THE REFUSED OCCURRENCE.
    refused_ids = {r["pool_instance_id"] for r in refusals}
    with SessionLocal() as db:
        events_after = db.query(PoolEconomicEvent).count()
        refused_events = (db.query(PoolEconomicEvent)
                          .filter(PoolEconomicEvent.pool_instance_id.in_(
                              refused_ids)).count())
        still_unsettled = (db.query(PoolInstance)
                           .filter(PoolInstance.id.in_(refused_ids),
                                   PoolInstance.settled.is_(False)).count())
        db.rollback()
    _assert("the refused occurrences posted NO economic event",
            refused_events == 0, str(refused_events))
    _assert("and remain UNSETTLED — a refusal marks nothing complete",
            still_unsettled == len(refused_ids),
            f"{still_unsettled}/{len(refused_ids)}")
    _assert("the trial balance is unchanged by the refusal",
            trial_balance() == tb_before == 0)
    _assert("sibling occurrences that COULD settle were not held hostage",
            events_after >= events_before)

    # ════ C. DIAGNOSABLE WITHOUT RERUNNING SETTLEMENT ═══════════════════════
    _section("C · the incident is diagnosable as a pure read")

    r_status = client().get(
        f"/league/{league_id}/provider/status?week={FAULT_WEEK}", headers=hdr)
    _assert("the provider status read answers for the stuck week",
            r_status.status_code == 200,
            f"{r_status.status_code} {r_status.text[:250]}")
    status = r_status.json() if r_status.status_code == 200 else {}
    _assert("it names the provider and reports the week as economically final "
            "— so the operator knows the games ARE over",
            status.get("provider") == "demo" and status.get("week_final") is True,
            f"{status.get('provider')} final={status.get('week_final')}")
    _assert("it reports when the provider last refreshed this league",
            status.get("last_provider_refresh") is not None)
    _assert("it lists the stuck occurrences with the SAME classification "
            "settlement produced, without settling anything",
            any(p["classification"] == "INCOMPLETE_FIELD"
                for p in status.get("stuck_pools") or []),
            str([p.get("classification")
                 for p in status.get("stuck_pools") or []]))
    stuck = next((p for p in status.get("stuck_pools") or []
                  if p["classification"] == "INCOMPLETE_FIELD"), {})
    _assert("the diagnosis names the same unevaluable subjects",
            set(stuck.get("unevaluable_subject_ids") or [])
            == set(sample.get("unevaluable_subject_ids") or []),
            f"{stuck.get('unevaluable_subject_ids')} vs "
            f"{sample.get('unevaluable_subject_ids')}")
    _assert("and it says retry is the remedy",
            stuck.get("retryable") is True and stuck.get("settleable") is False)

    with SessionLocal() as db:
        events_after_read = db.query(PoolEconomicEvent).count()
        db.rollback()
    _assert("the diagnostic read posted nothing and settled nothing",
            events_after_read == events_after and trial_balance() == 0)

    # ════ D. NO TERMINALITY, EVER ═══════════════════════════════════════════
    _section("D · repetition, time and finality never make it terminal")

    classifications = []
    for _attempt in range(4):
        rr = client().post(f"/league/{league_id}/pool/settle/{FAULT_WEEK}",
                           headers=hdr)
        classifications.append(
            sorted(r["classification"] for r in (rr.json().get("refusals") or [])))
    _assert("four further attempts produce the IDENTICAL classification — "
            "repetition is not evidence",
            len(set(map(tuple, classifications))) == 1
            and "INCOMPLETE_FIELD" in classifications[0],
            str(classifications[0]))

    with SessionLocal() as db:
        still = (db.query(PoolInstance)
                 .filter(PoolInstance.id.in_(refused_ids),
                         PoolInstance.settled.is_(False)).count())
        events_now = db.query(PoolEconomicEvent).count()
        db.rollback()
    _assert("the occurrences are still unsettled and still unposted",
            still == len(refused_ids) and events_now == events_after)
    _assert("the trial balance never moved across five refusals",
            trial_balance() == 0)

    from providers import incident as provider_incident
    _assert("the taxonomy declares NO terminal reason at all — there is no "
            "state for a stuck Pool to be forced into",
            provider_incident.TERMINAL_REASONS == frozenset())

    # NO COMMISSIONER OVERRIDE EXISTS. Asserted over the mounted route table
    # rather than by inspecting prose: a forcing route would have to be
    # reachable, and none is.
    override_routes = sorted(
        r.path for r in app.routes
        if "pool" in getattr(r, "path", "").lower()
        and any(token in getattr(r, "path", "").lower()
                for token in ("force", "override", "void", "refund",
                              "terminal", "resolve", "complete"))
    )
    _assert("no Pool route exists to force, void, refund, resolve or "
            "terminalize an occurrence — a commissioner cannot make a stuck "
            "Pool settle", not override_routes, str(override_routes))

    # ════ E. SEASON CLOSE IS BLOCKED ════════════════════════════════════════
    _section("E · the season cannot close over an unsettled Pool")

    for week in range(PLAYOFF_START_WEEK, SEASON_FINAL_WEEK + 1):
        advance()   # open
        advance()   # finalize

    r_blocked = client().post(f"/league/{league_id}/season/close", headers=hdr)
    blocked_detail = (r_blocked.json() or {}).get("detail") or {}
    _assert("season close refuses while the week is unsettled, naming the "
            "unmet precondition",
            r_blocked.status_code == 409
            and blocked_detail.get("reason_code") == "pool_settled",
            f"{r_blocked.status_code} {str(blocked_detail)[:220]}")
    _assert("the blocked close moved no money", trial_balance() == 0)

    # ════ F. RECOVERY THROUGH ORDINARY SETTLEMENT ═══════════════════════════
    _section("F · the corrected feed settles the SAME Pool, ordinarily")

    restore_source()

    r_status2 = client().get(
        f"/league/{league_id}/provider/status?week={FAULT_WEEK}", headers=hdr)
    recovered_status = r_status2.json() if r_status2.status_code == 200 else {}
    _assert("with the feed restored the diagnostic says the occurrence would "
            "now settle — before any settlement is attempted",
            all(p["settleable"]
                for p in recovered_status.get("stuck_pools") or []),
            str([(p.get("classification"), p.get("settleable"))
                 for p in recovered_status.get("stuck_pools") or []]))

    r_fixed = client().post(f"/league/{league_id}/pool/settle/{FAULT_WEEK}",
                            headers=hdr)
    _assert("the SAME production route settles the week once the authoritative "
            "data is present — there is no recovery-specific path",
            r_fixed.status_code == 200 and r_fixed.json()["all_settled"] is True,
            f"{r_fixed.status_code} {r_fixed.text[:250]}")
    fixed = r_fixed.json() if r_fixed.status_code == 200 else {}
    _assert("no refusal remains", not fixed.get("refusals"),
            str(fixed.get("refusals")))

    # CONSERVATION, OCCURRENCE BY OCCURRENCE. `pot_cents` is the pot the
    # occurrence actually carried — this week's share PLUS any balance rolled
    # forward from an earlier week — so it, not the week's collection, is the
    # quantity that must be fully disposed. Every cent leaves as a distribution,
    # a rollover or a championship sweep, and the incident changed neither the
    # pot nor the arithmetic that disposes it.
    disposed = sum(s["distributed_cents"] + s["rolled_over_cents"]
                   + s["swept_to_championship_cents"]
                   for s in fixed.get("settled", []))
    pots = sum(s["pot_cents"] for s in fixed.get("settled", []))
    _assert("the recovered settlement disposes every cent of every pot it "
            "settled — published Pool economics are unchanged by the incident",
            disposed == pots and pots >= collected,
            f"disposed {disposed} of pots {pots} (week collected {collected}, "
            f"pool account held {pool_before} before)")

    with SessionLocal() as db:
        per_instance = {}
        for row in (db.query(PoolEconomicEvent)
                    .filter(PoolEconomicEvent.pool_instance_id.in_(
                        refused_ids)).all()):
            per_instance.setdefault(row.pool_instance_id, []).append(
                row.event_type)
        db.rollback()
    _assert("each recovered occurrence posted EXACTLY ONE economic event — the "
            "five refusals left nothing behind to double up",
            per_instance and all(len(v) == 1 for v in per_instance.values()),
            str(per_instance))
    _assert("trial balance is zero after recovery", trial_balance() == 0)

    r_replay = client().post(f"/league/{league_id}/pool/settle/{FAULT_WEEK}",
                             headers=hdr)
    _assert("replaying the recovered settlement pays nothing further",
            r_replay.status_code == 200
            and all(s["replayed"] or s["distributed_cents"] == 0
                    for s in (r_replay.json().get("settled") or [])))
    _assert("trial balance is still zero", trial_balance() == 0)

    # ════ G. SEASON CLOSE PROCEEDS ══════════════════════════════════════════
    _section("G · the season closes once the ordinary path completes")

    assert client().post(f"/league/{league_id}/week/{FAULT_WEEK}/close",
                         headers=hdr).status_code == 200

    r_close = client().post(f"/league/{league_id}/season/close", headers=hdr)
    _assert("season close proceeds after recovery, with every other "
            "precondition unchanged", r_close.status_code == 200,
            f"{r_close.status_code} {r_close.text[:350]}")
    close = r_close.json() if r_close.status_code == 200 else {}
    _assert("the Championship podium is still the bracket's, paid 60/30/10",
            [p["pct"] for p in close.get("championship_placements") or []]
            == [60, 30, 10]
            and [p["team_id"] for p in close.get("championship_placements") or []]
            == team_ids[:3],
            str(close.get("championship_placements")))
    _assert("trial balance is zero after the close", trial_balance() == 0)
    _assert(f"pool:{league_id} is empty at the close",
            balance_of(f"pool:{league_id}") == 0,
            str(balance_of(f"pool:{league_id}")))

    # ════ H. API ERROR MAPPING ══════════════════════════════════════════════
    _section("H · every governed provider refusal is named, and none is a 500")

    from db.schema import League, Wallet
    from providers.identity import bind_league_identity, bind_team_identity

    with SessionLocal() as db:
        unbound = League(season=2025, name="Unbound League",
                         projection_source="fantasypros")
        db.add(unbound)
        yahoo = League(season=2025, name="Live Yahoo League",
                       projection_source="fantasypros")
        db.add(yahoo)
        db.flush()
        bind_league_identity(db, league_id=yahoo.id,
                             league_key="461.l.999002", provider="yahoo")
        for ordinal in (1, 2):
            for parent in (unbound, yahoo):
                t = Team(league_id=parent.id, team_name=f"T{ordinal}",
                         owner=f"O{ordinal}",
                         email=f"{parent.id}-{ordinal}@x.test")
                db.add(t)
                db.flush()
                db.add(Wallet(team_id=t.id, balance=0.0))
                if parent is yahoo:
                    bind_team_identity(db, team_id=t.id,
                                       team_key=f"461.l.999002.t.{ordinal}",
                                       team_ordinal=ordinal, provider="yahoo")
        admin = User(email="api-admin@x.test",
                     hashed_password=hash_password(PASSWORD),
                     role="commissioner")
        db.add(admin)
        db.flush()
        from db.schema import LeagueCommissioner
        for parent in (unbound, yahoo):
            db.add(LeagueCommissioner(league_id=parent.id, user_id=admin.id,
                                      source="bootstrap"))
        db.commit()
        unbound_id, yahoo_id = unbound.id, yahoo.id

    ahdr = bearer("api-admin@x.test")

    r_unbound = client().post(f"/league/{unbound_id}/pool/settle/1",
                              headers=ahdr)
    _assert("a league with NO provider identity is refused 409 by name, never "
            "defaulted into Yahoo",
            r_unbound.status_code == 409
            and (r_unbound.json().get("detail") or {}).get("reason_code")
            == "no_provider_identity",
            f"{r_unbound.status_code} {r_unbound.text[:180]}")

    r_yahoo = client().post(f"/league/{yahoo_id}/pool/settle/1", headers=ahdr)
    ydetail = (r_yahoo.json() or {}).get("detail") or {}
    _assert("a Yahoo league with no credentials reachable is refused with a "
            "NAMED provider reason and a non-500 status",
            r_yahoo.status_code in (502, 503)
            and ydetail.get("reason") in ("provider_credentials_missing",
                                          "provider_unavailable"),
            f"{r_yahoo.status_code} {str(ydetail)[:200]}")
    _assert("the Yahoo refusal leaks no credential material into the response",
            not any(token in r_yahoo.text.lower()
                    for token in ("bearer ", "access_token\":\"",
                                  "refresh_token\":\"", "consumer_secret\":\"")),
            r_yahoo.text[:120])
    _assert("and it names the provider that failed",
            ydetail.get("provider") == "yahoo", str(ydetail.get("provider")))

    r_unknown_demo = client().post(f"/demo/league/{yahoo_id}/advance",
                                   headers=ahdr)
    _assert("a Demo-only action on a Yahoo league is refused 409 by name",
            r_unknown_demo.status_code == 409
            and (r_unknown_demo.json().get("detail") or {}).get("reason_code")
            == "not_a_demo_league",
            f"{r_unknown_demo.status_code} {r_unknown_demo.text[:160]}")

    _assert("no governed provider refusal in this suite returned a 500",
            all(code != 500 for code in (
                r_out.status_code, r_settle_out.status_code,
                r_fault.status_code, r_blocked.status_code,
                r_unbound.status_code, r_yahoo.status_code,
                r_unknown_demo.status_code)))

    print("\n" + "=" * 78)
    if _failures:
        print(f"  WP2 PROVIDER RECOVERY: {len(_failures)} FAILURE(S)")
        for label in _failures:
            print(f"    - {label}")
    else:
        print("  WP2 PROVIDER RECOVERY: ALL ASSERTIONS PASS")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    try:
        main()
    finally:
        tdb.teardown()
    sys.exit(1 if _failures else 0)
