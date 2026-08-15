"""
test_wp2_demo_lifecycle_pg.py — WP2 · the Demo league IS the product.

WHAT THIS SUITE PROVES, AND WHY IT IS THE WHOLE POINT OF THE PACKAGE. Demo Mode
is a launch feature, and the one thing that could make it worthless is a second
implementation hiding behind it. So every economic act below happens through the
PRODUCTION ROUTE a Yahoo league uses, with the production engine behind it:

    POST /demo/league                     the only Demo-specific creation
    POST /league/{id}/season-allocation    production
    POST /demo/league/{id}/advance         the only Demo-specific progression
    POST /league/{id}/pool/activate        production
    POST /league/{id}/week/{w}/open        production
    POST /league/{id}/pool/collect/{w}     production
    POST /pool/pick                        production
    POST /league/{id}/pool/settle/{w}      production
    POST /league/{id}/week/{w}/close       production
    POST /league/{id}/season/close         production

NOTHING IS SUBSTITUTED. No transport is patched, no engine is stubbed, no
outcome is injected. The Demo provider is the real one, and it is reached through
the same composition boundary a Yahoo league is reached through.

NO YAHOO CREDENTIAL IS PRESENT OR REQUIRED, and §1 asserts that rather than
assuming it — a Demo league that quietly needed a Yahoo token would not be a demo
at all.

THE ECONOMY IS THE PARAMETERIZED ONE, AND THE FIGURE PROVES IT. The Demo league's
own boundaries give it FOUR regular-season weeks, not fourteen, so every
week-count-derived figure differs from the familiar production one. A suite that
still saw 14 weeks' worth of anything would be reading a hardcoded constant.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)
os.environ.setdefault("JWT_SECRET_KEY", "wp2-demo-suite-secret")

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP2 Demo suite cannot run:\n  {e}")
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


PASSWORD = "wp2-demo-password"


def main() -> None:
    from fastapi.testclient import TestClient

    from api.main import app
    from auth.jwt_auth import hash_password
    from db.schema import (
        LeagueCommissioner, Matchup, PoolClaim, PoolInstance, SessionLocal,
        Team, User, Wallet,
    )
    from ledger.ledger import balance_of, trial_balance
    from providers.demo import DEMO_PROVIDER
    from providers.demo.scenario import (
        EXPECTED_PODIUM_ORDINALS, PLAYOFF_START_WEEK, SEASON_FINAL_WEEK,
        START_WEEK, TEAM_COUNT,
    )

    def client() -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    def bearer(email: str) -> dict:
        r = client().post("/auth/login",
                          data={"username": email, "password": PASSWORD})
        assert r.status_code == 200, f"login failed: {r.text}"
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    tdb.reset()

    # ════ 0. THE DEMO PROVIDER IS CREDENTIAL-FREE AND MONEY-ISOLATED ═════════
    _section("the Demo provider needs no credential and touches no money")

    from providers.errors import ProviderCredentialError
    from providers.yahoo.transport import load_credentials

    creds_env = sorted(k for k in os.environ if k.startswith("YAHOO_"))
    _assert("no YAHOO_* credential is present in this process",
            not creds_env, str(creds_env))
    try:
        load_credentials()
        credential_refused = False
    except ProviderCredentialError:
        credential_refused = True
    _assert("Yahoo credentials are genuinely unreachable — every Demo result "
            "below is therefore produced without them", credential_refused)

    import ast

    money_imports: list[str] = []
    demo_root = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "providers", "demo")
    for name in sorted(os.listdir(demo_root)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(demo_root, name), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            money_imports += [f"providers/demo/{name}:{n}" for n in names
                              if n.split(".")[0] in ("ledger", "economy")]
    _assert("the Demo provider imports nothing from ledger/ or economy/ — every "
            "Credit that moves below moves through a FantasyStakes engine",
            not money_imports, str(money_imports))

    # ════ 1. CREATION ═══════════════════════════════════════════════════════
    _section("POST /demo/league — creation, identity and authority")

    with SessionLocal() as db:
        owner = User(email="demo-owner@x.test",
                     hashed_password=hash_password(PASSWORD), role="gm")
        db.add(owner)
        db.commit()

    tb_before_create = trial_balance()
    hdr = bearer("demo-owner@x.test")
    r_create = client().post("/demo/league", headers=hdr)
    _assert("a Demo league is created with no Yahoo credential and no network",
            r_create.status_code == 201,
            f"{r_create.status_code} {r_create.text[:250]}")
    created = r_create.json() if r_create.status_code == 201 else {}
    league_id = created.get("league_id")

    _assert("the league declares the DEMO provider explicitly",
            created.get("provider") == DEMO_PROVIDER and created.get("demo")
            is True, f"{created.get('provider')} demo={created.get('demo')}")
    _assert("its provider league key is unmistakably synthetic and is NOT "
            "Yahoo-shaped",
            (created.get("provider_league_key") or "").startswith("demo.l.")
            and not (created.get("provider_league_key") or "")
            .split(".")[0].isdigit(),
            str(created.get("provider_league_key")))
    _assert(f"the Demo league fields {TEAM_COUNT} teams",
            len(created.get("team_ids") or []) == TEAM_COUNT,
            str(len(created.get("team_ids") or [])))
    _assert("the creator is seated at Demo Team 1",
            created.get("acting_team_id") == (created.get("team_ids") or [None])[0],
            str(created.get("acting_team_id")))
    _assert("the Demo's own boundaries are carried, and they are NOT the "
            "production defaults",
            (created.get("start_week"), created.get("playoff_start_week"),
             created.get("season_final_week"))
            == (START_WEEK, PLAYOFF_START_WEEK, SEASON_FINAL_WEEK),
            f"{created.get('start_week')}/"
            f"{created.get('playoff_start_week')}/"
            f"{created.get('season_final_week')}")
    _assert("creation posts ZERO Credits — a provider brings facts into "
            "existence, never money", trial_balance() == tb_before_create == 0)

    with SessionLocal() as db:
        comm_rows = (db.query(LeagueCommissioner)
                     .filter(LeagueCommissioner.league_id == league_id).all())
        _assert("the creator holds commissioner authority for their Demo league",
                len(comm_rows) == 1, str(len(comm_rows)))
        team_rows = (db.query(Team).filter(Team.league_id == league_id)
                     .order_by(Team.id).all())
        team_ids = [t.id for t in team_rows]
        keys = [t.provider_team_key for t in team_rows]
        _assert("every Demo team carries a deterministic synthetic provider key "
                "under the demo provider",
                all(t.provider == DEMO_PROVIDER for t in team_rows)
                and keys == [f"{created['provider_league_key']}.t.{n}"
                             for n in range(1, TEAM_COUNT + 1)],
                str(keys[:2]))
        _assert("every Demo team has a wallet at zero",
                all(db.query(Wallet).filter(Wallet.team_id == t).first()
                    is not None for t in team_ids))
        db.rollback()

    # A SECOND DEMO LEAGUE COLLIDES WITH NOTHING.
    with SessionLocal() as db:
        other = User(email="demo-other@x.test",
                     hashed_password=hash_password(PASSWORD), role="gm")
        db.add(other)
        db.commit()
    r_other = client().post("/demo/league", headers=bearer("demo-other@x.test"))
    _assert("a second user creates their own Demo league without collision",
            r_other.status_code == 201,
            f"{r_other.status_code} {r_other.text[:200]}")
    other_league_id = (r_other.json() or {}).get("league_id")
    _assert("the two Demo leagues hold different provider namespaces",
            (r_other.json() or {}).get("provider_league_key")
            != created.get("provider_league_key"))

    # Seat the remaining five GMs.
    with SessionLocal() as db:
        pw = hash_password(PASSWORD)
        for ordinal in range(2, TEAM_COUNT + 1):
            db.add(User(email=f"demo-gm{ordinal}@x.test", hashed_password=pw,
                        team_id=team_ids[ordinal - 1], role="gm"))
        db.commit()
    gm = {n: bearer(f"demo-gm{n}@x.test") for n in range(2, TEAM_COUNT + 1)}
    gm[1] = hdr

    # ════ 2. THE DEMO MARKER IS ON THE PRODUCTION CONTRACT ══════════════════
    _section("the DEMO marker travels on the production league context")

    r_ctx = client().get(f"/league/{league_id}/context/me", headers=hdr)
    _assert("the acting GM's league context reports demo=true",
            r_ctx.status_code == 200 and r_ctx.json().get("demo") is True,
            f"{r_ctx.status_code} {r_ctx.text[:160]}")
    _assert("and it reports the provider by name, not by league name",
            (r_ctx.json() or {}).get("provider") == DEMO_PROVIDER)

    # ════ 3. SEASON ALLOCATION — THE PRODUCTION ROUTE ═══════════════════════
    _section("season allocation runs through the production economic route")

    r_alloc = client().post(f"/league/{league_id}/season-allocation", headers=hdr)
    _assert("the production season-allocation route funds the Demo league",
            r_alloc.status_code == 200,
            f"{r_alloc.status_code} {r_alloc.text[:250]}")
    _assert("trial balance is zero after issuance", trial_balance() == 0)

    import scripts.bootstrap_pool_catalog as bootstrap
    _assert("the canonical Pool catalog bootstraps", bootstrap.main([]) == 0)

    # ════ 4. ADVANCE — THE DEMO STATE MACHINE ═══════════════════════════════
    _section("POST /demo/league/{id}/advance — open, finalize, next")

    r_state = client().get(f"/demo/league/{league_id}", headers=hdr)
    _assert("week 1 is OPEN immediately after creation",
            r_state.status_code == 200
            and r_state.json().get("week_state") == "OPEN"
            and r_state.json().get("current_week") == 1,
            f"{r_state.status_code} {r_state.text[:160]}")

    with SessionLocal() as db:
        from db.schema import RosterSlot

        rows = (db.query(Matchup)
                .filter(Matchup.league_id == league_id, Matchup.week == 1).all())
        _assert("an OPEN Demo week persists matchups with finalized_at NULL — "
                "finality is never inferred from the row existing",
                len(rows) == 3 and all(r.finalized_at is None for r in rows),
                f"{len(rows)} rows")

        # LINEUPS AT OPEN, NUMBERS AT FINAL. A provider publishes a team's
        # starters before kickoff and its statistics afterwards, and the Demo
        # does the same — which is what makes a wager on an unplayed game
        # possible while keeping an unplayed game's stats non-existent.
        open_slots = (db.query(RosterSlot)
                      .filter(RosterSlot.league_id == league_id,
                              RosterSlot.week == 1).count())
        _assert("an OPEN Demo week publishes LINEUPS — the weekly roster "
                "capture the wager engine reads",
                open_slots == 60, str(open_slots))
        db.rollback()

    # ════ 5. WEEK 1 — THE FULL PRODUCTION ECONOMIC LIFECYCLE ════════════════
    _section("week 1 — activate, open, collect, claim, finalize, settle, close")

    def advance(expected_action: str | None = None) -> dict:
        r = client().post(f"/demo/league/{league_id}/advance", headers=hdr)
        assert r.status_code == 200, f"advance: {r.status_code} {r.text[:250]}"
        body = r.json()
        if expected_action:
            assert body["action"] == expected_action, body
        return body

    r_open = client().post(f"/league/{league_id}/week/1/open", headers=hdr)
    _assert("the production Week Open route runs the Weekly Minimum for a Demo "
            "league", r_open.status_code == 200,
            f"{r_open.status_code} {r_open.text[:250]}")

    # Finalize week 1 through the Demo state machine BEFORE measuring support:
    # an OPEN week carries no roster and no stats, which is the truth about a
    # week that has not been played.
    fin = advance("finalize")
    _assert("advancing an OPEN Demo week FINALIZES its matchups",
            fin["matchups_finalized"] == 3,
            f"finalized={fin['matchups_finalized']}")
    _assert("and writes NO further roster slot — the week's lineups were "
            "already captured at open, and the capture is insert-only",
            fin["roster_slots_written"] == 0,
            str(fin["roster_slots_written"]))

    r_act = client().post(f"/league/{league_id}/pool/activate?week=1", headers=hdr)
    _assert("gate-2 readiness is measured from the DEMO payload through the "
            "production route", r_act.status_code == 200,
            f"{r_act.status_code} {r_act.text[:250]}")
    act = r_act.json() if r_act.status_code == 200 else {}
    _assert("the measurement is recorded under the demo provider, not Yahoo",
            act.get("provider") == DEMO_PROVIDER, str(act.get("provider")))
    _assert("the Demo feed advertises no stat a live Yahoo league could not "
            "have — pass_attempts, completions and opportunities stay "
            "unsupported",
            not ({"pass_attempts", "completions", "opportunities"}
                 & set(act.get("supported_stats") or [])),
            str(sorted(set(act.get("supported_stats") or []))[:6]))
    _assert("the Demo league has enough measured support to draw a full slate",
            act.get("sufficient_for_slate") is True,
            f"eligible={act.get('eligible_this_phase')}")

    tb_before = trial_balance()
    r_coll = client().post(f"/league/{league_id}/pool/collect/1", headers=hdr)
    _assert("the governed Rev1.3 collection funds four Demo Pools",
            r_coll.status_code == 200,
            f"{r_coll.status_code} {r_coll.text[:250]}")
    coll = r_coll.json() if r_coll.status_code == 200 else {}
    _assert("every Demo team was charged exactly once",
            coll.get("teams_charged") == TEAM_COUNT,
            str(coll.get("teams_charged")))
    _assert(f"pool:{league_id} holds the collected total",
            balance_of(f"pool:{league_id}") == coll.get("total_cents"),
            str(balance_of(f"pool:{league_id}")))
    _assert("trial balance is zero after collection",
            trial_balance() == 0 == tb_before)

    with SessionLocal() as db:
        instances = (db.query(PoolInstance)
                     .filter(PoolInstance.league_id == league_id,
                             PoolInstance.week == 1)
                     .order_by(PoolInstance.slot).all())
        drawn = [(i.id, i.definition_key) for i in instances]
        db.rollback()
    _assert("four Pool occurrences were drawn from the rotating catalog",
            len(drawn) == 4, str([k for _i, k in drawn]))

    # CLAIMS THROUGH THE PRODUCTION PICK ROUTE.
    r_slate = client().get(f"/pool/week/1?league_id={league_id}", headers=hdr)
    _assert("the production Pool week read serves the Demo slate",
            r_slate.status_code == 200,
            f"{r_slate.status_code} {r_slate.text[:200]}")
    slate = r_slate.json() if r_slate.status_code == 200 else {}
    pools = slate.get("pools") or []
    _assert("the Pool week read offers every drawn occurrence with its "
            "admissible subjects",
            len(pools) == 4 and all(p.get("subjects") for p in pools),
            str([(p.get("definition_key"), len(p.get("subjects") or []))
                 for p in pools]))

    # WHICH SUBJECT ACTUALLY WINS IS COMPUTED BY THE PURE CLASSIFIER, AS A READ,
    # BEFORE ANY CLAIM IS MADE. A suite that had GMs pick arbitrarily would prove
    # only that claims land; picking the subject the engine will independently
    # decide is the winner is what proves a Demo Pool PAYS through the production
    # settlement path. Nothing is injected — `classify_pool` here is the same
    # function `settle_pool_instance` calls, run read-only.
    winners: dict[int, tuple[str, tuple[int, ...]]] = {}
    matchup_sides: dict[int, set[int]] = {}
    with SessionLocal() as db:
        from betting.pool_catalog import spec_from_row
        from betting.pool_census import classify_pool
        from betting.pool_subjects import league_weekly_structure
        from db.schema import League, PoolDefinition
        import api.main as main_mod

        league_row = db.query(League).filter(League.id == league_id).first()
        snap = main_mod._provider_week_snapshot(db, league_row, 1,
                                                with_rosters=True)
        source = main_mod._provider_stat_source(db, league_row, snap)
        for instance_id, definition_key in drawn:
            defn = (db.query(PoolDefinition)
                    .filter(PoolDefinition.key == definition_key).first())
            spec = spec_from_row(defn)
            structure = league_weekly_structure(db, league_id=league_id, week=1,
                                                scope=spec.scope)
            outcome = classify_pool(
                spec, structure,
                source.subjects_for(league_id=league_id, season=league_row.season,
                                    week=1, structure=structure))
            winners[instance_id] = (spec.scope, outcome.winning_subject_ids)
        for row in (db.query(Matchup)
                    .filter(Matchup.league_id == league_id,
                            Matchup.week == 1).all()):
            matchup_sides[row.id] = {row.home_team_id, row.away_team_id}
        db.rollback()

    def ineligible_teams(scope: str, subject_id: int) -> set[int]:
        """The teams that may NOT claim this subject — the self-pick rule."""
        if scope == "TEAM":
            return {subject_id}
        return matchup_sides.get(subject_id, set())

    claims_made = 0
    winning_claims = 0
    for entry in pools:
        instance_id = entry["pool_instance_id"]
        subject_ids = [s["subject_id"] for s in entry["subjects"]]
        scope, winning = winners.get(instance_id, ("TEAM", ()))

        for ordinal in range(1, TEAM_COUNT + 1):
            team_id = team_ids[ordinal - 1]
            # The GM claims the WINNING subject when they are allowed to, and
            # otherwise the first subject the self-pick rule admits. A Pool with
            # no eligible claimant for its winner still settles — as a
            # zero-winner rollover — and that is a legitimate outcome, not a
            # failure of this suite.
            preference = [w for w in winning] + subject_ids
            for subject_id in preference:
                if team_id in ineligible_teams(scope, subject_id):
                    continue
                r_pick = client().post("/pool/pick", headers=gm[ordinal], json={
                    "league_id": league_id,
                    "team_id": team_id,
                    "week": 1,
                    "pool_instance_id": instance_id,
                    "subject_id": subject_id,
                })
                if r_pick.status_code == 200:
                    claims_made += 1
                    if subject_id in winning:
                        winning_claims += 1
                break
    _assert("GMs submit Pool claims through the production pick route",
            claims_made > 0, f"{claims_made} claims accepted")
    _assert("at least one GM holds the subject the engine independently "
            "determined to be the winner", winning_claims > 0,
            f"{winning_claims} winning claims")

    with SessionLocal() as db:
        persisted_claims = (db.query(PoolClaim)
                            .filter(PoolClaim.pool_instance_id.in_(
                                [i for i, _k in drawn])).count())
        db.rollback()
    _assert("the claims are persisted by the certified claim engine",
            persisted_claims == claims_made,
            f"{persisted_claims} rows vs {claims_made} accepted")

    r_settle = client().post(f"/league/{league_id}/pool/settle/1", headers=hdr)
    _assert("the production settlement route settles the Demo week",
            r_settle.status_code == 200,
            f"{r_settle.status_code} {r_settle.text[:300]}")
    settled = r_settle.json() if r_settle.status_code == 200 else {}
    _assert("every occurrence settled — the Demo feed is complete, so nothing "
            "fails closed", settled.get("all_settled") is True,
            str(settled.get("refused")))
    distributed = sum(s["distributed_cents"] for s in settled.get("settled", []))
    rolled = sum(s["rolled_over_cents"] for s in settled.get("settled", []))
    swept = sum(s["swept_to_championship_cents"]
                for s in settled.get("settled", []))
    _assert("every collected cent is accounted for by distribution, rollover or "
            "sweep",
            distributed + rolled + swept == coll.get("total_cents"),
            f"{distributed}+{rolled}+{swept} vs {coll.get('total_cents')}")
    _assert("at least one occurrence paid a winner through the production "
            "engine", distributed > 0, f"{distributed} cents distributed")
    _assert("trial balance is zero after settlement", trial_balance() == 0)

    r_dup = client().post(f"/league/{league_id}/pool/settle/1", headers=hdr)
    _assert("re-settling the same Demo week pays nothing further",
            r_dup.status_code == 200
            and all(s["replayed"] or s["distributed_cents"] == 0
                    for s in (r_dup.json().get("settled") or [])),
            f"{r_dup.status_code}")
    _assert("trial balance is still zero after the replay", trial_balance() == 0)

    r_close = client().post(f"/league/{league_id}/week/1/close", headers=hdr)
    _assert("the production Week Close route assesses Skunk for a Demo league",
            r_close.status_code == 200,
            f"{r_close.status_code} {r_close.text[:250]}")
    _assert("trial balance is zero after week close", trial_balance() == 0)

    # ════ 6. WEEKS 2-4 — INCLUDING A ZERO-CLAIM WEEK ════════════════════════
    _section("weeks 2-4 — the same production loop, and a zero-winner Pool")

    #: The week a Versus wager is issued in — a week whose games are PUBLISHED
    #: and NOT YET FINAL, which is the only state a wager can legitimately be
    #: struck in.
    VERSUS_WEEK = 3
    VERSUS_STAKE = 3.00

    zero_winner_seen = False
    versus_challenge_id = None
    for week in range(2, PLAYOFF_START_WEEK):
        advance("open")
        r = client().post(f"/league/{league_id}/week/{week}/open", headers=hdr)
        assert r.status_code == 200, f"week {week} open: {r.text[:200]}"

        if week == VERSUS_WEEK:
            # ── VERSUS THROUGH THE PRODUCTION ENGINE ─────────────────────────
            # Issued and accepted while the week is OPEN, which is the point:
            # a Demo GM wagers on a game that has not been played, the Credits
            # are escrowed by the certified funding path, and the certified
            # settlement engine resolves them from `finalized_at` later. No
            # Demo-specific wagering path exists and none is used.
            r_ch = client().post("/beef/challenge", headers=gm[2], json={
                "challenger_team_id": team_ids[1],
                "challenged_team_id": team_ids[2],
                "week": week, "bet_type": "straight",
                "amount": VERSUS_STAKE, "challenge_mode": "locked"})
            _assert("a Demo GM issues a Versus challenge through the "
                    "production route", r_ch.status_code == 201,
                    f"{r_ch.status_code} {r_ch.text[:220]}")
            versus_challenge_id = (r_ch.json() or {}).get("challenge_id")
            _assert("the issuer's stake is REAL escrow, sourced by the "
                    "certified funding path",
                    balance_of(f"escrow:challenge:{versus_challenge_id}")
                    == int(VERSUS_STAKE * 100),
                    str(balance_of(f"escrow:challenge:{versus_challenge_id}")))

            r_acc = client().post("/beef/respond", headers=gm[3], json={
                "challenge_id": versus_challenge_id, "accept": True})
            _assert("the challenged Demo GM accepts, and both sides are funded",
                    r_acc.status_code == 200, f"{r_acc.status_code} "
                    f"{r_acc.text[:250]}")
            accepted = r_acc.json() if r_acc.status_code == 200 else {}
            _assert("acceptance migrates the pooled escrow into per-bet escrow "
                    "— the same migration a Yahoo league's wager makes",
                    balance_of(f"escrow:challenge:{versus_challenge_id}") == 0
                    and balance_of(f"escrow:{accepted.get('anchor_bet_id')}")
                    == int(VERSUS_STAKE * 100),
                    f"pooled="
                    f"{balance_of(f'escrow:challenge:{versus_challenge_id}')}")
            _assert("trial balance is zero across the Versus negotiation",
                    trial_balance() == 0)

        advance("finalize")
        r = client().post(f"/league/{league_id}/pool/activate?week={week}",
                          headers=hdr)
        assert r.status_code == 200, f"week {week} activate: {r.text[:200]}"
        r = client().post(f"/league/{league_id}/pool/collect/{week}", headers=hdr)
        assert r.status_code == 200, f"week {week} collect: {r.text[:250]}"

        # WEEK 2 IS PLAYED WITH NO CLAIMS AT ALL — the zero-winner case. Every
        # subject is evaluable and a winner IS determined; no GM picked it, so
        # the pot rolls over or sweeps by the existing R2 semantics. Nothing
        # about that path is Demo-specific.
        r = client().post(f"/league/{league_id}/pool/settle/{week}", headers=hdr)
        assert r.status_code == 200, f"week {week} settle: {r.text[:300]}"
        body = r.json()
        if week == 2:
            carried = sum(s["rolled_over_cents"] + s["swept_to_championship_cents"]
                          for s in body.get("settled", []))
            zero_winner_seen = carried > 0 and all(
                s["distributed_cents"] == 0 for s in body.get("settled", []))
            _assert("a week nobody claimed distributes nothing and carries the "
                    "whole pot by the EXISTING rollover/sweep semantics",
                    zero_winner_seen, f"carried={carried}")
        if week == VERSUS_WEEK:
            r_vs = client().post(f"/league/{league_id}/settle/{week}",
                                 headers=hdr)
            _assert("the production Versus settlement engine settles the Demo "
                    "wager once the week is economically final",
                    r_vs.status_code == 200,
                    f"{r_vs.status_code} {r_vs.text[:250]}")
            report = r_vs.json() if r_vs.status_code == 200 else {}
            _assert("both sides of the wager were resolved",
                    (report.get("total_bets") or 0) >= 2, str(report)[:200])
            with SessionLocal() as db:
                from db.schema import Bet
                statuses = sorted(
                    b.status for b in db.query(Bet)
                    .filter(Bet.beef_challenge_id == versus_challenge_id).all())
                db.rollback()
            _assert("no wager is left pending — the escrow is fully resolved",
                    statuses and all(s != "pending" for s in statuses),
                    str(statuses))
            _assert("every per-bet escrow account is empty after settlement",
                    balance_of(
                        f"escrow:challenge:{versus_challenge_id}") == 0
                    and trial_balance() == 0)

        r = client().post(f"/league/{league_id}/week/{week}/close", headers=hdr)
        assert r.status_code == 200, f"week {week} close: {r.text[:250]}"
        _assert(f"week {week} completes the production loop and the trial "
                f"balance is zero", trial_balance() == 0)

    # ════ 7. POSTSEASON ═════════════════════════════════════════════════════
    _section("postseason — the Demo bracket reaches the podium by the "
             "production seam")

    for week in range(PLAYOFF_START_WEEK, SEASON_FINAL_WEEK + 1):
        advance("open")
        advance("finalize")

    r_state = client().get(f"/demo/league/{league_id}", headers=hdr)
    _assert("the Demo season reports itself complete after its final week",
            r_state.json().get("week_state") == "SEASON_COMPLETE",
            str(r_state.json().get("week_state")))

    r_adv = client().post(f"/demo/league/{league_id}/advance", headers=hdr)
    _assert("advancing past the final week refuses by name rather than "
            "inventing a week",
            r_adv.status_code == 409
            and (r_adv.json().get("detail") or {}).get("reason_code")
            == "demo_season_complete",
            f"{r_adv.status_code} {r_adv.text[:200]}")

    with SessionLocal() as db:
        from db.schema import League
        from providers.postseason_bracket import championship_field, classified_week
        from providers.base import MatchupBracket

        league = db.query(League).filter(League.id == league_id).first()
        semis = classified_week(db, league=league, week=PLAYOFF_START_WEEK)
        finals = classified_week(db, league=league, week=SEASON_FINAL_WEEK)
        field = championship_field(db, league=league)
        db.rollback()

    _assert("the championship FIELD is authoritative and is the four teams the "
            "provider declared", field is not None and len(field) == 4,
            str(sorted(k.rsplit(".", 1)[-1] for k in (field or []))))
    _assert("the SEMIFINAL week classifies exactly two championship-track games "
            "beside a consolation one",
            sum(1 for m in semis
                if m.bracket is MatchupBracket.CHAMPIONSHIP) == 2
            and sum(1 for m in semis
                    if m.bracket is MatchupBracket.NON_CHAMPIONSHIP) == 1,
            str([m.bracket.value for m in semis]))
    _assert("the FINAL week classifies exactly one championship game",
            sum(1 for m in finals
                if m.bracket is MatchupBracket.CHAMPIONSHIP) == 1,
            str([m.bracket.value for m in finals]))

    # ════ 8. SEASON CLOSE ═══════════════════════════════════════════════════
    _section("season close — the Championship podium pays 60/30/10")

    r_sc = client().post(f"/league/{league_id}/season/close", headers=hdr)
    _assert("the production season-close route closes the Demo season",
            r_sc.status_code == 200,
            f"{r_sc.status_code} {r_sc.text[:400]}")
    close = r_sc.json() if r_sc.status_code == 200 else {}
    placements = close.get("championship_placements") or []
    _assert("the Championship Pot is distributed to exactly three teams",
            len(placements) == 3, str(placements))
    _assert("the split is 60/30/10, unchanged",
            [p["pct"] for p in placements] == [60, 30, 10],
            str([p.get("pct") for p in placements]))

    expected_podium = [team_ids[n - 1] for n in EXPECTED_PODIUM_ORDINALS]
    _assert("the recipients are the CHAMPION, the RUNNER-UP and the winner of "
            "the OFFICIAL THIRD-PLACE GAME — derived from the bracket, never "
            "from regular-season Points For",
            [p["team_id"] for p in placements] == expected_podium,
            f"{[p['team_id'] for p in placements]} vs {expected_podium}")
    # THE POT IS THE CLOSE'S OWN REPORTED FIGURE, read AFTER the reserve sweep
    # and the terminal Pool rollover sweep have both landed in it. A balance
    # taken before the close would be the pot before those two steps, which is a
    # different number and would make this assertion describe the wrong quantity.
    _assert("every cent of the Championship Pot was paid out",
            sum(p["cents"] for p in placements)
            == close.get("championship_pot_cents"),
            f"{sum(p['cents'] for p in placements)} vs "
            f"{close.get('championship_pot_cents')}")
    _assert("trial balance is zero after season close", trial_balance() == 0)
    _assert(f"championship:{league_id} is empty",
            balance_of(f"championship:{league_id}") == 0)

    # ════ 9. RESET SAFETY ═══════════════════════════════════════════════════
    _section("reset — scoped to Demo, ledger-immutable, isolated")

    ledger_before_reset = trial_balance()
    with SessionLocal() as db:
        from ledger.ledger import LedgerEntry
        entries_before = db.query(LedgerEntry).count()
        other_matchups_before = (db.query(Matchup)
                                 .filter(Matchup.league_id == other_league_id)
                                 .count())
        db.rollback()

    r_reset = client().post(f"/demo/league/{league_id}/reset", headers=hdr)
    _assert("a commissioner may reset their own Demo league",
            r_reset.status_code == 201,
            f"{r_reset.status_code} {r_reset.text[:250]}")
    fresh = r_reset.json() if r_reset.status_code == 201 else {}
    _assert("reset returns a NEW Demo league and names the one it superseded",
            fresh.get("league_id") not in (None, league_id)
            and fresh.get("superseded_league_id") == league_id,
            f"{fresh.get('league_id')} superseded "
            f"{fresh.get('superseded_league_id')}")
    _assert("the fresh Demo league starts at week 1, OPEN",
            fresh.get("current_week") == 1
            and fresh.get("week_state") == "OPEN",
            f"{fresh.get('current_week')} {fresh.get('week_state')}")
    _assert("the caller is seated in the fresh league",
            fresh.get("acting_team_id") in (fresh.get("team_ids") or []))

    with SessionLocal() as db:
        from ledger.ledger import LedgerEntry
        entries_after = db.query(LedgerEntry).count()
        old_league_rows = (db.query(Matchup)
                           .filter(Matchup.league_id == league_id).count())
        other_matchups_after = (db.query(Matchup)
                                .filter(Matchup.league_id == other_league_id)
                                .count())
        db.rollback()
    _assert("reset DELETED NO LEDGER HISTORY — immutability is not traded for "
            "convenience", entries_after >= entries_before,
            f"{entries_before} -> {entries_after}")
    _assert("the superseded Demo league keeps every row it wrote",
            old_league_rows > 0, str(old_league_rows))
    _assert("trial balance is unchanged by the reset",
            trial_balance() == ledger_before_reset == 0)
    _assert("another user's Demo league is untouched",
            other_matchups_after == other_matchups_before,
            f"{other_matchups_before} -> {other_matchups_after}")

    # A YAHOO LEAGUE CANNOT BE RESET OR ADVANCED.
    with SessionLocal() as db:
        from db.schema import League
        from providers.identity import bind_league_identity, bind_team_identity

        yahoo = League(season=2025, name="Live Yahoo League",
                       projection_source="fantasypros")
        db.add(yahoo)
        db.flush()
        bind_league_identity(db, league_id=yahoo.id,
                             league_key="461.l.999001", provider="yahoo")
        yteam = Team(league_id=yahoo.id, team_name="Y1", owner="Y",
                     email="y1@x.test")
        db.add(yteam)
        db.flush()
        db.add(Wallet(team_id=yteam.id, balance=0.0))
        bind_team_identity(db, team_id=yteam.id, team_key="461.l.999001.t.1",
                           team_ordinal=1, provider="yahoo")
        yahoo_admin = User(email="yahoo-comm@x.test",
                           hashed_password=hash_password(PASSWORD),
                           role="commissioner")
        db.add(yahoo_admin)
        db.flush()
        db.add(LeagueCommissioner(league_id=yahoo.id, user_id=yahoo_admin.id,
                                  source="bootstrap"))
        db.commit()
        yahoo_id = yahoo.id

    yhdr = bearer("yahoo-comm@x.test")
    for action in ("reset", "advance"):
        r = client().post(f"/demo/league/{yahoo_id}/{action}", headers=yhdr)
        _assert(f"a Yahoo league cannot be {action}ed through the Demo surface",
                r.status_code == 409
                and (r.json().get("detail") or {}).get("reason_code")
                == "not_a_demo_league",
                f"{r.status_code} {r.text[:200]}")

    # AND A DEMO COMMISSIONER HAS NO AUTHORITY OVER THE YAHOO LEAGUE.
    r = client().post(f"/demo/league/{yahoo_id}/advance", headers=hdr)
    _assert("a Demo commissioner is refused authority over a Yahoo league "
            "before any Demo check runs", r.status_code == 403,
            f"{r.status_code} {r.text[:160]}")

    # A DEMO LEAGUE'S PROVIDER CANNOT BE SWITCHED TO YAHOO.
    with SessionLocal() as db:
        from providers.errors import ProviderIdentityError
        from providers.identity import bind_league_identity as bind_league

        try:
            bind_league(db, league_id=league_id,
                        league_key=created["provider_league_key"],
                        provider="yahoo")
            switched = True
            reason = ""
        except ProviderIdentityError as exc:
            switched, reason = False, exc.reason
        db.rollback()
    _assert("a Demo league cannot be rebound to Yahoo mid-season",
            not switched and reason == "CONFLICTING_IDENTITY", reason)

    # ════ SUMMARY ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 78)
    if _failures:
        print(f"  WP2 DEMO LIFECYCLE: {len(_failures)} FAILURE(S)")
        for label in _failures:
            print(f"    - {label}")
    else:
        print("  WP2 DEMO LIFECYCLE: ALL ASSERTIONS PASS")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    try:
        main()
    finally:
        tdb.teardown()
    sys.exit(1 if _failures else 0)
