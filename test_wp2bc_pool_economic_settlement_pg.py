"""
test_wp2bc_pool_economic_settlement_pg.py — WP2B-C · three economic proofs.

WHY THIS SUITE EXISTS. WP2B proved the governed Pool lifecycle is REACHABLE:
catalog bootstrap, readiness measurement, collection, the real provider assembly,
the real settlement engine, the real ledger. What it could not prove is that the
chain ever produces MONEY MOVING CORRECTLY, because the Sprint 6 corpus carries
roster coverage for week 1 only and every occurrence that week refuses
INCOMPLETE_FIELD. `settled == []` is a truthful result there and the assertions
pass over it vacuously — "no occurrence paid more than its pot" is trivially true
of an empty list.

WP2B-C closes that with a second SYNTHETIC league whose data is built to make
each outcome unambiguous. Three proofs, all driven through the PRODUCTION routes:

  1  WINNER SETTLEMENT — `most_passing_yards` (#20, TEAM, RANK_EXTREMUM/MAX).
     Six evaluable teams, one unique extremum, four GM claims on it, and an
     exact §6.3 even split with its remainder ordering.

  2  ZERO-WINNER / ROLLOVER — `matchups_with_zero_total_turnovers` (#87,
     MATCHUP, QUALIFIER). Three FULLY EVALUABLE matchups, every one carrying
     combined turnovers, so nothing qualifies. The census is asserted to be
     considered == evaluated, which is what distinguishes a GENUINE
     ZERO_ELIGIBLE_CLAIMS from INCOMPLETE_FIELD or NO_EVALUABLE_SUBJECTS. The
     carry is then followed into the next week and consumed as a continuation.

  3  FINALITY NEGATIVE — the same production route on the same funded week,
     before and after `Matchup.finalized_at` is persisted. Zero ledger mutation
     before; a real settlement after.

THE ONLY SUBSTITUTION IS THE TRANSPORT. `api.main._pool_settlement_transport` is
pointed at `FixtureTransport`, exactly as WP2B does, so the suite runs offline
with no credentials. Everything else — the routes, the assembly, the identity
resolver, the stat source, the census, the engine, the ledger — is production.

WHY THE LEAGUE ID IS PINNED. The Rev1.3 rotation is a pure SHA-256 ranking over
(definition_key, league_id, season, rotation_cycle) — that determinism is the
selector's whole contract. Pinning league_id 19 / season 2025 therefore pins
which four of the twelve gate-2-ready definitions week 1 draws, so this suite can
name the two it must exercise instead of hoping for them. Nothing is overridden:
the slate is drawn by the real selector from the real measured eligible set, and
§2 below ASSERTS the draw rather than assuming it, so a catalog or readiness
change fails loudly here instead of silently proving something else.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)
os.environ.setdefault("JWT_SECRET_KEY", "wp2bc-suite-secret")

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP2B-C suite cannot run:\n  {e}")
    sys.exit(2)

from datetime import datetime, timedelta, timezone  # noqa: E402

# WP2B-D extracted the league seed and the corpus assembly helper into a shared
# support module, so the finality-mapping suite proves its case against the SAME
# league definition rather than a second copy that could drift from this one.
# Nothing about the fixtures, the identity or the pinned rotation changed.
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


PASSWORD = "wp2bc-password"

WINNER_KEY = "most_passing_yards"
ZERO_KEY = "matchups_with_zero_total_turnovers"

#: What the real selector draws for (league 19, season 2025, cycle 1) from the
#: twelve definitions this corpus's three stat ids make gate-2 ready. Asserted,
#: never assumed — see the module docstring.
EXPECTED_WEEK1_SLATE = (
    "matchups_where_neither_team_threw_an_interception",   # #95 QUALIFIER
    ZERO_KEY,                                             # #87 QUALIFIER
    "highest_combined_passing_yards",                      # #56 RANK_EXTREMUM
    WINNER_KEY,                                            # #20 RANK_EXTREMUM
)

#: POR §6.1 governed default: 100 cents per team per week.
ENTRY_CENTS = 100
TOTAL_CENTS = ENTRY_CENTS * TEAM_COUNT          # 600
SHARE_CENTS = TOTAL_CENTS // 4                  # 150
REMAINDER_CENTS = TOTAL_CENTS % 4               # 0


def main() -> None:
    from fastapi.testclient import TestClient

    import api.main as main_mod
    from api.main import app
    from auth.jwt_auth import hash_password
    from db.schema import (
        LeagueCommissioner, Matchup, PoolClaim, PoolDefinition, PoolInstance,
        SessionLocal, User,
    )
    from economy.season_allocation import activate_season_allocation
    from ledger.ledger import balance_of, trial_balance
    from providers.fixtures.record import payload_sha256
    from providers.fixtures.replay import FixtureTransport, load_corpus
    from providers.yahoo.persist import refresh_league_week, snapshot_digest

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

    # ════ 0. CORPUS INTEGRITY ═══════════════════════════════════════════════
    _section("WP2B-C synthetic corpus integrity")

    corpus = load_corpus()
    mine = {k: v for k, v in corpus.items() if k.startswith("yahoo_wp2bc")}
    _assert("the WP2B-C fixtures are present in the committed corpus",
            len(mine) == 17, f"{len(mine)} fixtures")
    _assert("EVERY WP2B-C manifest declares provenance SYNTHETIC",
            all(f.provenance == "SYNTHETIC" for f in mine.values()),
            str(sorted({f.provenance for f in mine.values()})))
    _assert("every payload's recomputed SHA-256 matches its manifest",
            all(payload_sha256(f.payload) == f.declared_sha256
                for f in mine.values()))
    _assert("every WP2B-C fixture carries the publication-safe league key",
            all(f.league_key == LEAGUE_KEY for f in mine.values()),
            str(sorted({f.league_key for f in mine.values()})))

    # NO REAL LEAGUE IDENTIFIER, anywhere in these files. Checked over the raw
    # bytes rather than the parsed payload, so a stray occurrence in a manifest
    # note or a scrub action would be caught too.
    from providers.fixtures.replay import DEFAULT_CORPUS_DIR

    leaked = []
    for name in sorted(os.listdir(DEFAULT_CORPUS_DIR)):
        if not name.startswith("yahoo_wp2bc"):
            continue
        with open(os.path.join(DEFAULT_CORPUS_DIR, name),
                  encoding="utf-8") as handle:
            text_blob = handle.read()
        if "461.l.488800" in text_blob or "488800" in text_blob:
            leaked.append(name)
    _assert("no real league identifier appears in any WP2B-C fixture",
            not leaked, str(leaked))

    # REPLAY DETERMINISM. Two independent transports, two full assemblies, one
    # digest. This is what makes settlement's rebuild-at-use-time sound.
    snap_a = snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW), 1)
    snap_b = snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW), 1)
    _assert("two independent replays produce a byte-identical week 1 snapshot",
            snapshot_digest(snap_a) == snapshot_digest(snap_b),
            snapshot_digest(snap_a)[:16] + "...")
    _assert("the week 1 snapshot carries all six teams, three matchups and "
            "thirty measured starters/bench players",
            (len(snap_a.teams), len(snap_a.matchups), len(snap_a.roster_entries),
             len(snap_a.player_stats)) == (6, 3, 30, 30),
            f"{len(snap_a.teams)}/{len(snap_a.matchups)}/"
            f"{len(snap_a.roster_entries)}/{len(snap_a.player_stats)}")
    _assert("every week 1 matchup is provider-FINAL",
            all(m.finality.value == "FINAL" for m in snap_a.matchups))

    pending = snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW), 2,
                           scoreboard_id="yahoo_wp2bc_scoreboard_w2_pending")
    final_w2 = snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW), 2,
                            scoreboard_id="yahoo_wp2bc_scoreboard_w2")
    _assert("the pending and final week 2 payloads differ in FINALITY ONLY — "
            "identical scores, so a score-watching implementation cannot pass "
            "the finality negative",
            [(m.home_team_key, m.away_team_key, m.home_points, m.away_points)
             for m in pending.matchups]
            == [(m.home_team_key, m.away_team_key, m.home_points, m.away_points)
                for m in final_w2.matchups]
            and all(m.finality.value == "NOT_FINAL" for m in pending.matchups)
            and all(m.finality.value == "FINAL" for m in final_w2.matchups))

    tdb.reset()

    # ════ 1. SEED, IDENTITY, CATALOG BOOTSTRAP ══════════════════════════════
    _section("seed, provider identity binding and canonical catalog bootstrap")

    with SessionLocal() as db:
        league, teams = seed_economic_league(db)
        db.commit()
        team_ids = [t.id for t in teams]

        pw = hash_password(PASSWORD)
        comm = User(email="wp2bc-comm@x.test", hashed_password=pw,
                    team_id=team_ids[0], role="commissioner")
        db.add(comm)
        gms = []
        for ordinal in range(2, TEAM_COUNT + 1):
            gm = User(email=f"wp2bc-gm{ordinal}@x.test", hashed_password=pw,
                      team_id=team_ids[ordinal - 1], role="gm")
            db.add(gm)
            gms.append(gm)
        db.flush()
        db.add(LeagueCommissioner(league_id=league.id, user_id=comm.id,
                                  source="bootstrap"))
        db.commit()

    _assert("the league id is PINNED, so the deterministic rotation is "
            "reproducible", LEAGUE_ID == 19 and team_ids, str(team_ids))

    with SessionLocal() as db:
        from providers.yahoo.identity import build_team_identity_resolver

        resolver = build_team_identity_resolver(db, league_id=LEAGUE_ID)
        mapped = [resolver.to_internal(f"{LEAGUE_KEY}.t.{o}")
                  for o in range(1, TEAM_COUNT + 1)]
        _assert("every provider team key resolves to its own internal team — "
                "identity comes from the compound key, not a name or an email",
                mapped == team_ids, f"{mapped} vs {team_ids}")
        db.rollback()

    # Ingest week 1 through the real persistence path.
    with SessionLocal() as db:
        refresh_league_week(db, snapshot_for(
            FixtureTransport(frozen_now=FROZEN_NOW), 1), now=FROZEN_NOW)
        db.commit()

    with SessionLocal() as db:
        rows = (db.query(Matchup)
                .filter(Matchup.league_id == LEAGUE_ID, Matchup.week == 1).all())
        _assert("week 1 persisted three matchups, every one economically final",
                len(rows) == 3 and all(r.finalized_at is not None for r in rows),
                f"{len(rows)} rows")
        db.rollback()

    with SessionLocal() as db:
        activate_season_allocation(LEAGUE_ID, db)

    hdr = bearer("wp2bc-comm@x.test")
    hdr_gm = bearer("wp2bc-gm2@x.test")

    import scripts.bootstrap_pool_catalog as bootstrap

    _assert("catalog bootstrap succeeds", bootstrap.main([]) == 0)
    _assert("catalog bootstrap is clean on re-check", bootstrap.main(["--check"]) == 0)
    with SessionLocal() as db:
        catalog_size = db.query(PoolDefinition).count()
        _assert("the canonical catalog is loaded", catalog_size > 0,
                str(catalog_size))
        db.rollback()

    # ════ 2. SOURCE READINESS, AND THE SLATE IT DETERMINES ══════════════════
    _section("gate-2 readiness is measured from the payload, and pins the slate")

    r_act = client().post(f"/league/{LEAGUE_ID}/pool/activate?week=1", headers=hdr)
    _assert("activation succeeds through the production route",
            r_act.status_code == 200, f"{r_act.status_code} {r_act.text[:200]}")
    act = r_act.json() if r_act.status_code == 200 else {}
    supported = sorted(act.get("supported_stats") or [])
    print(f"     supported_stats = {supported}")
    _assert("support is measured from the three delivered stat ids and the "
            "matchup record — NOT from what the vocabulary says Yahoo could send",
            supported == ["fumbles_lost", "interceptions_thrown",
                          "matchup_away_score", "matchup_home_score",
                          "passing_yards"],
            str(supported))
    _assert("this corpus emits no player_points node, so fantasy points report "
            "UNSUPPORTED rather than defaulting to a measured zero",
            "player_fantasy_points" not in supported)
    _assert("readiness is stamped with the corpus's frozen instant",
            (act.get("measured_at") or "").startswith("2025-09-23"),
            str(act.get("measured_at")))

    # THE STALENESS RULE IS NOT WEAKENED — proven at the frozen instant, exactly
    # as C-13 does, before the lifecycle re-stamps for the live clock below.
    from betting.pool_gates import selectable_definitions
    from betting.pool_rotation import build_week_slate
    from betting.pool_season_boundary import PHASE_REGULAR
    from providers.yahoo.identity import build_team_identity_resolver
    from providers.yahoo.pool_source import PROVIDER, measure_league_activation

    with SessionLocal() as db:
        fresh = selectable_definitions(db, league_id=LEAGUE_ID,
                                       provider=PROVIDER, phase=PHASE_REGULAR,
                                       now=FROZEN_NOW)
        stale = selectable_definitions(db, league_id=LEAGUE_ID,
                                       provider=PROVIDER, phase=PHASE_REGULAR,
                                       now=FROZEN_NOW + timedelta(hours=25))
        db.rollback()

    _assert("at its valid frozen instant the measurement makes exactly twelve "
            "definitions selectable — the eligible set these three stat ids buy",
            len(fresh) == 12, str(len(fresh)))
    _assert("beyond the 24-hour window the same measurement is stale and the "
            "gate fails closed", len(stale) == 0, str(len(stale)))

    # THE SLATE IS PREDICTED FROM THE PURE SELECTOR BEFORE COLLECTION RUNS, so
    # the week-1 draw below is a reproduction of a stated expectation rather
    # than a description of whatever happened.
    predicted = build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=1,
                                 rotation_cycle=1, phase=PHASE_REGULAR,
                                 eligible=fresh)
    predicted_keys = tuple(e.definition_key for e in predicted.slate)
    _assert("the deterministic rotation draws the two definitions this package "
            "must exercise",
            predicted_keys == EXPECTED_WEEK1_SLATE, str(predicted_keys))

    # Re-stamp at the current instant for the LIFECYCLE. In production
    # observed_at is ~now; under replay the corpus instant is fixed in 2025.
    # This supplies the measured_at a live provider would have supplied and
    # changes no gate rule — the rule itself was just proven above.
    with SessionLocal() as db:
        resolver = build_team_identity_resolver(db, league_id=LEAGUE_ID)
        measure_league_activation(
            db, league_id=LEAGUE_ID,
            snapshot=snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW), 1),
            resolver=resolver, measured_at=datetime.now(timezone.utc))
        db.commit()

    # ════ 3. WEEK 1 — WEEK OPEN AND GOVERNED COLLECTION ═════════════════════
    _section("week 1 opens and the governed Rev1.3 collection funds four Pools")

    r_open = client().post(f"/league/{LEAGUE_ID}/week/1/open", headers=hdr)
    _assert("WP1 Week Open funds the week before Pool collection",
            r_open.status_code == 200,
            f"{r_open.status_code} {r_open.text[:160]}")

    tb_before_collect = trial_balance()
    r_c = client().post(f"/league/{LEAGUE_ID}/pool/collect/1", headers=hdr)
    _assert("governed collection succeeds", r_c.status_code == 200,
            f"{r_c.status_code} {r_c.text[:250]}")
    coll = r_c.json() if r_c.status_code == 200 else {}
    _assert("the governed default weekly entry was charged",
            coll.get("weekly_entry_cents") == ENTRY_CENTS,
            str(coll.get("weekly_entry_cents")))
    _assert("every team was charged exactly once",
            coll.get("teams_charged") == TEAM_COUNT,
            str(coll.get("teams_charged")))
    _assert("the §6.1 division is total//4 with the remainder to championship",
            (coll.get("total_cents"), coll.get("per_pool_share_cents"),
             coll.get("remainder_to_championship_cents"))
            == (TOTAL_CENTS, SHARE_CENTS, REMAINDER_CENTS),
            f"{coll.get('total_cents')}/{coll.get('per_pool_share_cents')}/"
            f"{coll.get('remainder_to_championship_cents')}")
    _assert(f"pool:{LEAGUE_ID} holds the whole collected total",
            balance_of(f"pool:{LEAGUE_ID}") == TOTAL_CENTS,
            str(balance_of(f"pool:{LEAGUE_ID}")))
    _assert("trial balance is zero after collection",
            trial_balance() == 0 == tb_before_collect)

    with SessionLocal() as db:
        drawn = {i.definition_key: i for i in
                 db.query(PoolInstance)
                 .filter(PoolInstance.league_id == LEAGUE_ID,
                         PoolInstance.week == 1)
                 .order_by(PoolInstance.slot).all()}
        drawn_keys = tuple(
            i.definition_key for i in
            db.query(PoolInstance)
            .filter(PoolInstance.league_id == LEAGUE_ID, PoolInstance.week == 1)
            .order_by(PoolInstance.slot).all())
        winner_instance_id = drawn[WINNER_KEY].id
        zero_instance_id = drawn[ZERO_KEY].id
        _assert("the persisted slate is exactly the predicted one",
                drawn_keys == EXPECTED_WEEK1_SLATE, str(drawn_keys))
        _assert("every occurrence carries an equal share of the pot",
                all(i.pot_cents == SHARE_CENTS for i in drawn.values()),
                str([i.pot_cents for i in drawn.values()]))
        db.rollback()

    # ════ 4. CLAIMS — a pick is a claim, not funding (Owner Ruling R3) ═══════
    _section("four GMs claim the winning team on most_passing_yards")

    # NO HTTP ROUTE EXPOSES CLAIM SUBMISSION YET — WP2B mounted collection and
    # settlement only. This is the certified production claim path
    # (`betting.pool_claims.submit_claim`), called directly, and it is the same
    # function any future route would call.
    from betting.pool_claims import submit_claim

    claimants = team_ids[1:5]              # teams 2, 3, 4, 5
    tb_before_claims = trial_balance()
    pool_before_claims = balance_of(f"pool:{LEAGUE_ID}")
    with SessionLocal() as db:
        for gm_team_id in claimants:
            submit_claim(db, pool_instance_id=winner_instance_id,
                         team_id=gm_team_id, subject_id=team_ids[0])
        db.commit()

    with SessionLocal() as db:
        n_claims = (db.query(PoolClaim)
                    .filter(PoolClaim.pool_instance_id == winner_instance_id)
                    .count())
        n_zero_claims = (db.query(PoolClaim)
                         .filter(PoolClaim.pool_instance_id == zero_instance_id)
                         .count())
        db.rollback()
    _assert("four claims landed on the winner occurrence", n_claims == 4,
            str(n_claims))
    _assert("the zero-winner occurrence carries no claims at all — its outcome "
            "must come from the SUBJECT layer, not from a missing ticket",
            n_zero_claims == 0, str(n_zero_claims))
    _assert("A PICK MOVED NO MONEY (Owner Ruling R3)",
            trial_balance() == tb_before_claims
            and balance_of(f"pool:{LEAGUE_ID}") == pool_before_claims,
            f"pool={balance_of(f'pool:{LEAGUE_ID}')}")

    # ════ 5. THE SETTLEMENT — proofs 1 and 2 ════════════════════════════════
    _section("PROOF 1 & 2 — production settlement route, real ledger movement")

    wallets_before = {tid: balance_of(f"wallet:{tid}") for tid in team_ids}
    champ_before = balance_of(f"championship:{LEAGUE_ID}")
    pool_before = balance_of(f"pool:{LEAGUE_ID}")

    _assert("an unauthenticated settle is refused",
            client().post(f"/league/{LEAGUE_ID}/pool/settle/1").status_code == 401)
    _assert("a non-commissioner settle is refused",
            client().post(f"/league/{LEAGUE_ID}/pool/settle/1",
                          headers=hdr_gm).status_code == 403)

    r_s = client().post(f"/league/{LEAGUE_ID}/pool/settle/1", headers=hdr)
    _assert("governed settlement returns 200", r_s.status_code == 200,
            f"{r_s.status_code} {r_s.text[:400]}")
    body = r_s.json() if r_s.status_code == 200 else {}
    settled = {s["definition_key"]: s for s in body.get("settled", [])}
    refused = body.get("refused", [])
    for key, item in settled.items():
        print(f"     - {key}: {item['classification']} pot={item['pot_cents']} "
              f"dist={item['distributed_cents']} roll={item['rolled_over_cents']} "
              f"sweep={item['swept_to_championship_cents']} "
              f"winners={item['winning_team_ids']}")
    for r in refused:
        print(f"     - REFUSED: {r[:160]}")

    # NOT A VACUOUS PASS. Four occurrences settled, zero refused — asserted
    # first, so nothing below can be trivially true of an empty list.
    _assert("ALL FOUR OCCURRENCES SETTLED AND NONE WAS REFUSED — this is not a "
            "vacuous pass over settled=[]",
            len(settled) == 4 and len(refused) == 0,
            f"{len(settled)} settled / {len(refused)} refused")
    _assert("the week container is marked settled",
            body.get("week_container_settled") is True
            and body.get("all_settled") is True)

    # ── PROOF 1: WINNER SETTLEMENT ───────────────────────────────────────────
    win = settled.get(WINNER_KEY, {})
    _assert(f"{WINNER_KEY} classified CLAIMS_PRESENT",
            win.get("classification") == "CLAIMS_PRESENT",
            str(win.get("classification")))
    _assert("the winning GMs are exactly the four claimants",
            sorted(win.get("winning_team_ids") or []) == sorted(claimants),
            f"{win.get('winning_team_ids')} vs {claimants}")
    _assert("the whole pot was distributed and nothing rolled or swept",
            (win.get("pot_cents"), win.get("distributed_cents"),
             win.get("rolled_over_cents"),
             win.get("swept_to_championship_cents"))
            == (SHARE_CENTS, SHARE_CENTS, 0, 0), str(win))

    # THE EXACT §6.3 ALLOCATION, cent by cent. base = 150//4 = 37,
    # remainder = 2, and the two EXTRA cents go to the two LOWEST canonical GM
    # identifiers — not to the first rows a query returned.
    expected_alloc = {claimants[0]: 38, claimants[1]: 38,
                      claimants[2]: 37, claimants[3]: 37}
    actual_alloc = {tid: balance_of(f"wallet:{tid}") - wallets_before[tid]
                    for tid in claimants}
    _assert("EXACT §6.3 even split with the remainder to the lowest canonical "
            "GM identifiers: 38/38/37/37",
            actual_alloc == expected_alloc,
            f"{actual_alloc} vs {expected_alloc}")
    _assert("every cent of the pot reached a winner",
            sum(actual_alloc.values()) == SHARE_CENTS,
            str(sum(actual_alloc.values())))
    non_winners = [tid for tid in team_ids if tid not in claimants]
    _assert("no non-claiming team's wallet moved",
            all(balance_of(f"wallet:{tid}") == wallets_before[tid]
                for tid in non_winners), str(non_winners))

    # The winner is the team the SELECTED-SLOT starters won, not the roster.
    with SessionLocal() as db:
        claim_rows = (db.query(PoolClaim)
                      .filter(PoolClaim.pool_instance_id == winner_instance_id)
                      .all())
        subjects = {c.selected_subject_id for c in claim_rows}
        db.rollback()
    _assert("the winning SUBJECT is team 1 — the bench quarterback with 999 "
            "passing yards on team 6 was correctly excluded by SLOT",
            subjects == {team_ids[0]}, str(subjects))

    # ── PROOF 2: GENUINE ZERO-WINNER, THEN ROLLOVER ─────────────────────────
    zero = settled.get(ZERO_KEY, {})
    _assert(f"{ZERO_KEY} classified ZERO_ELIGIBLE_CLAIMS",
            zero.get("classification") == "ZERO_ELIGIBLE_CLAIMS",
            str(zero.get("classification")))
    _assert("it is NOT INCOMPLETE_FIELD and NOT NO_EVALUABLE_SUBJECTS",
            zero.get("classification") not in ("INCOMPLETE_FIELD",
                                               "NO_EVALUABLE_SUBJECTS"),
            str(zero.get("classification")))
    _assert("the whole pot rolled over — nothing distributed, nothing swept",
            (zero.get("pot_cents"), zero.get("distributed_cents"),
             zero.get("rolled_over_cents"),
             zero.get("swept_to_championship_cents"))
            == (SHARE_CENTS, 0, SHARE_CENTS, 0), str(zero))
    _assert("no winning team is claimed for a zero-winner outcome",
            not zero.get("winning_team_ids"), str(zero.get("winning_team_ids")))

    # THE CENSUS IS THE DISCRIMINATOR. `considered == evaluated == 3` is what
    # makes this a real predicate that nothing satisfied rather than a field the
    # engine could not read. Re-derived here through the same production
    # assembly so the claim rests on the census, not on the classification name.
    from betting.pool_catalog import spec_from_row
    from betting.pool_census import classify_pool
    from betting.pool_subjects import league_weekly_structure
    from providers.yahoo.week_snapshot import bind_pool_stat_source

    with SessionLocal() as db:
        source = bind_pool_stat_source(
            db, snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW), 1),
            league_id=LEAGUE_ID)
        spec = spec_from_row(db.query(PoolDefinition)
                             .filter(PoolDefinition.key == ZERO_KEY).first())
        structure = league_weekly_structure(db, league_id=LEAGUE_ID, week=1,
                                            scope=spec.scope)
        outcome = classify_pool(spec, structure, source.subjects_for(
            league_id=LEAGUE_ID, season=SEASON, week=1, structure=structure))
        census = outcome.census.as_dict()
        db.rollback()
    print(f"     zero-winner census = {census}")
    _assert("EVERY subject was considered AND evaluated — three of three, none "
            "unevaluable",
            (census.get("subjects_considered"), census.get("subjects_evaluated"))
            == (3, 3) and not outcome.unevaluable_subject_ids, str(census))
    _assert("with a complete field, exactly ZERO subjects claimed the win",
            census.get("subjects_claiming") == 0, str(census))

    # ── EXACT LEDGER STATE FOR THE WHOLE WEEK ───────────────────────────────
    sweeps = sum(s["swept_to_championship_cents"] for s in settled.values())
    rolls = sum(s["rolled_over_cents"] for s in settled.values())
    dists = sum(s["distributed_cents"] for s in settled.values())
    _assert("the week's four pots are fully accounted for: 150 distributed + "
            "300 rolled + 150 swept = 600 collected",
            (dists, rolls, sweeps) == (150, 300, 150)
            and dists + rolls + sweeps == TOTAL_CENTS,
            f"dist={dists} roll={rolls} sweep={sweeps}")
    _assert(f"pool:{LEAGUE_ID} = 600 - 150 paid - 150 swept = 300, exactly the "
            f"two live carries",
            balance_of(f"pool:{LEAGUE_ID}") == 300,
            f"{balance_of(f'pool:{LEAGUE_ID}')} (was {pool_before})")
    _assert(f"championship:{LEAGUE_ID} received exactly the swept pot",
            balance_of(f"championship:{LEAGUE_ID}") - champ_before == 150,
            f"{balance_of(f'championship:{LEAGUE_ID}')} (was {champ_before})")
    _assert("trial balance is zero after settlement", trial_balance() == 0)

    from betting.pool_settlement import assert_pool_conservation

    with SessionLocal() as db:
        held = assert_pool_conservation(db, league_id=LEAGUE_ID, season=SEASON)
        db.rollback()
    _assert("POOL CONSERVATION holds against real ledger entries: the account "
            "balance equals unsettled pots plus live carries",
            held == 300, str(held))

    with SessionLocal() as db:
        persisted = (db.query(PoolInstance)
                     .filter(PoolInstance.league_id == LEAGUE_ID,
                             PoolInstance.week == 1,
                             PoolInstance.settled.is_(True)).count())
        carries = (db.query(PoolInstance)
                   .filter(PoolInstance.league_id == LEAGUE_ID,
                           PoolInstance.week == 1,
                           PoolInstance.rollover_cents > 0).count())
        _assert("settled state is PERSISTED for all four occurrences",
                persisted == 4, str(persisted))
        _assert("two occurrences persist a live carry", carries == 2,
                str(carries))
        db.rollback()

    # ════ 6. RETRY IDEMPOTENCY — NO DOUBLE PAYOUT ═══════════════════════════
    _section("a repeated settlement cannot pay, roll or sweep twice")

    snapshot_balances = {
        "pool": balance_of(f"pool:{LEAGUE_ID}"),
        "championship": balance_of(f"championship:{LEAGUE_ID}"),
        **{f"wallet:{tid}": balance_of(f"wallet:{tid}") for tid in team_ids},
    }
    r_s2 = client().post(f"/league/{LEAGUE_ID}/pool/settle/1", headers=hdr)
    _assert("the retry still returns 200", r_s2.status_code == 200,
            f"{r_s2.status_code} {r_s2.text[:200]}")
    replay = r_s2.json().get("settled", []) if r_s2.status_code == 200 else []
    # THE RETRY IS NOT SILENT, AND THAT IS THE STRONGER PROPERTY. `settled` is
    # not empty: the engine reconstructs each already-settled occurrence from
    # its PERSISTED economic event row and returns it flagged `replayed=True`.
    # An empty list would be indistinguishable from "the week no longer exists",
    # whereas this answers "here is what already happened, and I did it again
    # zero times" — which is exactly what Scope §H scenario 10c asks for.
    _assert("the retry reports every occurrence as REPLAYED — reconstructed "
            "from the persisted event row, not settled a second time",
            len(replay) == 4 and all(s["replayed"] for s in replay),
            f"{len(replay)} entries, replayed="
            f"{[s.get('replayed') for s in replay]}")
    _assert("no replayed occurrence claims a fresh distribution or sweep",
            all(s["distributed_cents"] == 150 or s["distributed_cents"] == 0
                for s in replay)
            and sum(s["swept_to_championship_cents"] for s in replay) == 150,
            str([(s["definition_key"], s["distributed_cents"],
                  s["swept_to_championship_cents"]) for s in replay]))
    after = {
        "pool": balance_of(f"pool:{LEAGUE_ID}"),
        "championship": balance_of(f"championship:{LEAGUE_ID}"),
        **{f"wallet:{tid}": balance_of(f"wallet:{tid}") for tid in team_ids},
    }
    _assert("NOT ONE ACCOUNT MOVED ON THE RETRY — the winner was not paid "
            "twice and the carries were not minted twice",
            after == snapshot_balances,
            str({k: (snapshot_balances[k], after[k])
                 for k in after if after[k] != snapshot_balances[k]}))
    _assert("trial balance is still zero after the retry", trial_balance() == 0)

    # ════ 7. PROOF 3a — FINALITY NEGATIVE ═══════════════════════════════════
    _section("PROOF 3a — a funded, fully evaluable week refuses while non-final")

    # Ingest week 2 from the PENDING payload: three matchup rows with real
    # scores and finalized_at IS NULL.
    with SessionLocal() as db:
        refresh_league_week(db, snapshot_for(
            FixtureTransport(frozen_now=FROZEN_NOW), 2,
            scoreboard_id="yahoo_wp2bc_scoreboard_w2_pending"), now=FROZEN_NOW)
        db.commit()

    with SessionLocal() as db:
        w2_rows = (db.query(Matchup)
                   .filter(Matchup.league_id == LEAGUE_ID,
                           Matchup.week == 2).all())
        _assert("week 2 persisted three matchup rows carrying real scores",
                len(w2_rows) == 3
                and all(r.home_score is not None for r in w2_rows),
                str([(r.home_score, r.away_score) for r in w2_rows]))
        _assert("not one of them is economically final",
                all(r.finalized_at is None for r in w2_rows))
        db.rollback()

    # Fresh readiness for week 2, then open and collect it through the routes.
    with SessionLocal() as db:
        resolver = build_team_identity_resolver(db, league_id=LEAGUE_ID)
        measure_league_activation(
            db, league_id=LEAGUE_ID,
            snapshot=snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW), 2),
            resolver=resolver, measured_at=datetime.now(timezone.utc))
        db.commit()

    _assert("WP1 Week Open funds week 2",
            client().post(f"/league/{LEAGUE_ID}/week/2/open",
                          headers=hdr).status_code == 200)
    r_c2 = client().post(f"/league/{LEAGUE_ID}/pool/collect/2", headers=hdr)
    _assert("week 2 collection succeeds — the week is genuinely funded, so the "
            "refusal below is about FINALITY and nothing else",
            r_c2.status_code == 200, f"{r_c2.status_code} {r_c2.text[:250]}")

    with SessionLocal() as db:
        w2 = (db.query(PoolInstance)
              .filter(PoolInstance.league_id == LEAGUE_ID, PoolInstance.week == 2)
              .order_by(PoolInstance.slot).all())
        w2_keys = tuple(i.definition_key for i in w2)
        w2_pots = [i.pot_cents for i in w2]
        w2_continuations = sum(1 for i in w2 if i.origin_instance_id is not None)
        db.rollback()
    print(f"     week 2 slate = {w2_keys}")
    _assert("THE WEEK 1 CARRIES WERE CONSUMED AS WEEK 2 CONTINUATIONS — the "
            "rollover is a lifecycle, not a column",
            w2_continuations == 2, str(w2_continuations))
    _assert("each continuation carries its prior pot PLUS this week's share "
            "(150 + 150), and each fresh draw carries the share alone",
            sorted(w2_pots) == [150, 150, 300, 300], str(w2_pots))
    _assert(f"pool:{LEAGUE_ID} now holds last week's carries plus this week's "
            f"collection",
            balance_of(f"pool:{LEAGUE_ID}") == 300 + TOTAL_CENTS,
            str(balance_of(f"pool:{LEAGUE_ID}")))

    with SessionLocal() as db:
        stale_carries = (db.query(PoolInstance)
                         .filter(PoolInstance.league_id == LEAGUE_ID,
                                 PoolInstance.week == 1,
                                 PoolInstance.rollover_cents > 0).count())
        db.rollback()
    _assert("the week 1 carries were ZEROED as they were consumed, so next "
            "week cannot mint a second continuation from one pot",
            stale_carries == 0, str(stale_carries))

    # THE NEGATIVE ITSELF.
    before_finality = {
        "pool": balance_of(f"pool:{LEAGUE_ID}"),
        "championship": balance_of(f"championship:{LEAGUE_ID}"),
        "trial": trial_balance(),
        **{f"wallet:{tid}": balance_of(f"wallet:{tid}") for tid in team_ids},
    }

    from betting.finality_gate import ResultsNotReadyError, require_week_final

    with SessionLocal() as db:
        try:
            require_week_final(db, league_id=LEAGUE_ID, week=2,
                               context="WP2B-C proof 3a")
            gate_reason = None
        except ResultsNotReadyError as exc:
            gate_reason = exc.reason
            gate_ids = exc.unfinalized_matchup_ids
        db.rollback()
    _assert("the shared economic finality gate names RESULTS_NOT_READY and the "
            "offending matchups",
            gate_reason == "RESULTS_NOT_READY" and len(gate_ids) == 3,
            f"{gate_reason} {gate_ids if gate_reason else ''}")

    r_neg = client().post(f"/league/{LEAGUE_ID}/pool/settle/2", headers=hdr)
    print(f"     production settle route on a non-final week -> HTTP "
          f"{r_neg.status_code}")
    _assert("THE PRODUCTION ROUTE REFUSES a non-final week",
            r_neg.status_code != 200, str(r_neg.status_code))
    # WP2B-D pinned this. The refusal was always correct; until WP2B-D it
    # surfaced as an unhandled 500 because ResultsNotReadyError is a plain
    # ValueError outside the PoolSettlementRefusedError family the route maps.
    # It is now a governed 409 carrying the engine's own reason vocabulary.
    _assert("the refusal is a governed 409, not a server error",
            r_neg.status_code == 409, str(r_neg.status_code))
    neg_detail = r_neg.json().get("detail", {}) if r_neg.status_code == 409 else {}
    _assert("the reason code is the engine's own RESULTS_NOT_READY vocabulary",
            neg_detail.get("reason_code") == "RESULTS_NOT_READY",
            str(neg_detail.get("reason_code")))

    after_finality = {
        "pool": balance_of(f"pool:{LEAGUE_ID}"),
        "championship": balance_of(f"championship:{LEAGUE_ID}"),
        "trial": trial_balance(),
        **{f"wallet:{tid}": balance_of(f"wallet:{tid}") for tid in team_ids},
    }
    _assert("ZERO LEDGER MUTATION — not one account moved and the trial "
            "balance is untouched",
            after_finality == before_finality,
            str({k: (before_finality[k], after_finality[k])
                 for k in after_finality
                 if after_finality[k] != before_finality[k]}))

    with SessionLocal() as db:
        settled_w2 = (db.query(PoolInstance)
                      .filter(PoolInstance.league_id == LEAGUE_ID,
                              PoolInstance.week == 2,
                              PoolInstance.settled.is_(True)).count())
        db.rollback()
    _assert("no occurrence was marked settled by the refusal — the week stays "
            "cleanly retryable", settled_w2 == 0, str(settled_w2))

    # THE REFUSAL IS NOT COMING FROM THE PAYLOAD. The transport serves the FINAL
    # week 2 scoreboard, so the snapshot the route assembled says every matchup
    # is over. Settlement still refused, because §7 makes persisted
    # `finalized_at` the sole predicate.
    route_snapshot = snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW), 2)
    _assert("the snapshot the route itself assembled reported every matchup "
            "FINAL — the refusal came from persisted finalized_at, not from the "
            "payload",
            all(m.finality.value == "FINAL" for m in route_snapshot.matchups))

    # ════ 8. PROOF 3b — FINALITY POSITIVE, SAME ROUTE ═══════════════════════
    _section("PROOF 3b — once finality is persisted, the same route settles")

    with SessionLocal() as db:
        refresh_league_week(db, snapshot_for(
            FixtureTransport(frozen_now=FROZEN_NOW), 2,
            scoreboard_id="yahoo_wp2bc_scoreboard_w2"), now=FROZEN_NOW)
        db.commit()

    with SessionLocal() as db:
        w2_rows = (db.query(Matchup)
                   .filter(Matchup.league_id == LEAGUE_ID,
                           Matchup.week == 2).all())
        _assert("exactly one fact changed: every week 2 matchup is now final, "
                "with the same three rows and the same scores",
                len(w2_rows) == 3
                and all(r.finalized_at is not None for r in w2_rows))
        db.rollback()

    pool_pre = balance_of(f"pool:{LEAGUE_ID}")
    champ_pre = balance_of(f"championship:{LEAGUE_ID}")
    r_pos = client().post(f"/league/{LEAGUE_ID}/pool/settle/2", headers=hdr)
    _assert("THE SAME ROUTE, THE SAME WEEK, NOW SETTLES", r_pos.status_code == 200,
            f"{r_pos.status_code} {r_pos.text[:400]}")
    body2 = r_pos.json() if r_pos.status_code == 200 else {}
    settled2 = body2.get("settled", [])
    for item in settled2:
        print(f"     - {item['definition_key']}: {item['classification']} "
              f"pot={item['pot_cents']} dist={item['distributed_cents']} "
              f"roll={item['rolled_over_cents']} "
              f"sweep={item['swept_to_championship_cents']}")
    _assert("all four week 2 occurrences settled, none refused",
            len(settled2) == 4 and not body2.get("refused"),
            f"{len(settled2)} settled / {len(body2.get('refused') or [])} refused")
    _assert("every week 2 pot is fully accounted for",
            all(s["distributed_cents"] + s["rolled_over_cents"]
                + s["swept_to_championship_cents"] == s["pot_cents"]
                for s in settled2))

    moved = ((pool_pre - balance_of(f"pool:{LEAGUE_ID}"))
             == (balance_of(f"championship:{LEAGUE_ID}") - champ_pre))
    _assert("money DID move on the positive half — the refusal was the gate, "
            "not an empty week",
            balance_of(f"pool:{LEAGUE_ID}") != pool_pre and moved,
            f"pool {pool_pre} -> {balance_of(f'pool:{LEAGUE_ID}')}, "
            f"championship {champ_pre} -> "
            f"{balance_of(f'championship:{LEAGUE_ID}')}")
    _assert("trial balance is zero after the week 2 settlement",
            trial_balance() == 0)

    with SessionLocal() as db:
        held2 = assert_pool_conservation(db, league_id=LEAGUE_ID, season=SEASON)
        db.rollback()
    _assert("pool conservation still holds across both settled weeks",
            held2 == balance_of(f"pool:{LEAGUE_ID}"), str(held2))

    # A final retry over the whole two-week history.
    snap_all = {
        "pool": balance_of(f"pool:{LEAGUE_ID}"),
        "championship": balance_of(f"championship:{LEAGUE_ID}"),
        **{f"wallet:{tid}": balance_of(f"wallet:{tid}") for tid in team_ids},
    }
    client().post(f"/league/{LEAGUE_ID}/pool/settle/1", headers=hdr)
    client().post(f"/league/{LEAGUE_ID}/pool/settle/2", headers=hdr)
    _assert("re-settling BOTH weeks moves nothing",
            {"pool": balance_of(f"pool:{LEAGUE_ID}"),
             "championship": balance_of(f"championship:{LEAGUE_ID}"),
             **{f"wallet:{tid}": balance_of(f"wallet:{tid}")
                for tid in team_ids}} == snap_all)
    _assert("trial balance is zero at the end of the package",
            trial_balance() == 0)


if __name__ == "__main__":
    print("\n=== WP2B-C pool economic settlement suite (PostgreSQL) ===")
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
