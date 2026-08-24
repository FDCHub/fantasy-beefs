"""
test_wp3_season_close_pg.py — WP3 · the season-close production chain.

THE GAP WP3 CLOSES. `economy/season_close_orchestrator.close_season_economy` is
the certified sixteen-step close and `test_s5_p3_season_close_pg.py` certified
its economics. NOTHING CALLED IT. `economy/season_close.py` states the fact in
its own scope fence — "routes — nothing in this module is registered in
api/main.py" — so a league could finish its season with no way to close it:
the season-close orchestration had no production route. WP3 adds the
commissioner action and
proves the whole chain end to end:

    commissioner action -> POST /league/{id}/season/close
      -> require_league_commissioner
      -> verify_preconditions (steps 1-9b, pure reads)
      -> close_season_economy (steps 10-15)
      -> season_reconciliation, with era-gated retired steps
      -> ledger postings + League.season_closed_at
      -> returned product state

WHAT THIS SUITE DOES NOT RE-PROVE. S5-P3 already certified the orchestrator's
internal arithmetic in isolation. This suite proves the WIRING: that the route
reaches the orchestrator, that nothing about the prerequisite contract is
weakened by being reached over HTTP, and that the money and the refusals behave
identically through the production surface.

THE PREREQUISITE CONTRACT IS READ OUT OF THE CODE, NOT ASSUMED. §1 below drives
one league into each of NINE distinct unmet-prerequisite states and asserts WHICH
step refuses, by name. In particular the brief's open question — whether Pool
settlement is a hard prerequisite — is answered by construction rather than by
reading the docstring: an unsettled `PoolInstance` carrying a ZERO pot, with the
pool account already drained and every other check satisfiable, still refuses at
`pool_settled`. It is a hard prerequisite, and it is not merely a proxy for the
pool account being non-zero.

SYNTHETIC DATA ONLY. Six teams, two recorded weeks, deterministic scores. No
provider corpus is involved: season close reads matchup rows, ledger balances
and event rows, and a provider snapshot would add a dependency the close does
not have.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

import io
import os
import sys
import threading
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)
os.environ.setdefault("JWT_SECRET_KEY", "wp3-suite-secret")

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP3 suite cannot run:\n  {e}")
    sys.exit(2)

from datetime import datetime, timezone  # noqa: E402

from test_support_postseason import (  # noqa: E402
    SYNTHETIC_PROVIDER, record_synthetic_postseason,
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


PASSWORD = "wp3-password"
N_TEAMS = 6
PLAYOFF_START = 6
SEASON_FINAL_WEEK = 7
PLAYED_WEEKS = (3, 4)
#: WP1D — the league now plays an actual postseason, because the Championship
#: Pot's recipients are now derived from it. Weeks 6 and 7 are POSTSEASON
#: (>= PLAYOFF_START), so they are outside `verify_preconditions`' Weekly Minimum
#: and Skunk cutoff — `min(final_week, playoff_start_week - 1)` — and nothing
#: about the regular-season economics in this suite moves.
SEMIFINAL_WEEK = 6
CHAMPIONSHIP_WEEK = 7

#: The governed Pool weekly entry used to build a realistic Championship pot.
#: 175 x 6 = 1050, whose §6.1 indivisible remainder (1050 % 4 = 2) lands in
#: `championship:{league}` through the real division-remainder door, and whose
#: 262-cent share makes one swept occurrence a non-round contribution. Together
#: they give the Championship pot a value the 60/30/10 split cannot divide
#: evenly — which is the only way to prove first place absorbs the remainder.
POOL_ENTRY_CENTS = 175
POOL_TOTAL_CENTS = POOL_ENTRY_CENTS * N_TEAMS          # 1050
POOL_REMAINDER_CENTS = POOL_TOTAL_CENTS % 4            # 2
POOL_SHARE_CENTS = POOL_TOTAL_CENTS // 4               # 262

#: Recorded results. Deliberately arranged so the final standings order is
#: NEITHER ascending team id NOR the first three teams — an implementation that
#: paid by insertion order would produce a different, plausible-looking answer.
#:
#:   points for:  t1 280 > t2 270 > t4 231 > t3 223 > t5 219 > t0 190
#:   skunk loser: t0 in BOTH weeks (largest margin 60, then 50)
WEEK_RESULTS = {
    3: [(0, 1, 100.0, 160.0), (2, 3, 130.0, 105.0), (4, 5, 120.0, 118.0)],
    4: [(0, 2, 90.0, 140.0), (1, 3, 120.0, 118.0), (4, 5, 111.0, 101.0)],
}
#: The postseason, recorded as a provider would state it. Team INDEXES.
#:
#:   week 6 semifinals   t0 beat t3      t5 beat t4      (CHAMPIONSHIP)
#:   week 7 final        t0 beat t5                      (CHAMPIONSHIP)
#:   week 7 third place  t3 beat t4                      (NON_CHAMPIONSHIP)
#:
#: DELIBERATELY DISJOINT FROM THE POINTS-FOR ORDER, which is the whole WP1D
#: proof. By regular-season scoring the top three are t1, t2, t4 — and NONE of
#: them is on the podium. t0, the WORST scorer in the league and the Skunk loser
#: in both played weeks, is the champion. An implementation that still ranked the
#: Championship Pot by Points For would produce a fully plausible payout to three
#: teams that lost, and this suite would catch it on the first placement.
EXPECTED_PODIUM = (0, 5, 3)     # champion, runner-up, third — best first
THIRD_PLACE_LOSER = 4           # loses the semi-final AND the third-place game
EXPECTED_SKUNK_WINNER = 1       # highest regular-season points for


def main() -> None:
    from fastapi.testclient import TestClient

    import config
    from api.main import app
    from auth.jwt_auth import hash_password
    from db.schema import (
        Bet, EconomyEvent, League, LeagueCommissioner, Matchup, PoolDefinition,
        PoolInstance, ProviderConflict, SessionLocal, Team, User, Wallet,
    )
    from economy.economy_events import (
        championship_account, expired_min_account, min_account,
        min_reserve_account, points_championship_account, receivable_account,
        reserve_account, skunk_account, wallet_account,
    )
    from economy.season_allocation import activate_season_allocation
    from economy.skunk import assess_weekly_skunk
    from economy.weekly_minimum import expire_week, release_week, weekly_minimum_cents
    from ledger.ledger import balance_of, post as ledger_post, trial_balance

    import scripts.bootstrap_pool_catalog as bootstrap

    SEASON = config.ALLOCATION_SEASON

    def client() -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    def bearer(email: str) -> dict:
        r = client().post("/auth/login",
                          data={"username": email, "password": PASSWORD})
        assert r.status_code == 200, f"login failed: {r.text}"
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def now_naive():
        return datetime.now(timezone.utc).replace(tzinfo=None)

    # ── Fixture construction ────────────────────────────────────────────────

    def league_key_for(name: str) -> str:
        return f"synthetic.l.{name}"

    def make_league(db, name: str):
        league_key = league_key_for(name)
        league = League(season=SEASON, name=name,
                        projection_source="fantasypros",
                        season_final_week=SEASON_FINAL_WEEK,
                        playoff_start_week=PLAYOFF_START,
                        provider=SYNTHETIC_PROVIDER,
                        provider_league_key=league_key)
        db.add(league)
        db.flush()
        teams = []
        for i in range(N_TEAMS):
            # WP1D — PROVIDER IDENTITY, because the Championship Pot is now paid
            # to teams the postseason names in the provider's own vocabulary.
            # The certified resolver refuses a PARTIAL mapping, so every team is
            # bound or none is; a per-league key namespace keeps
            # uq_teams_provider_key satisfied across the many leagues this suite
            # builds.
            t = Team(league_id=league.id, team_name=f"{name}-t{i}",
                     owner=f"owner{i}", email=f"{name}-{i}@example.invalid",
                     provider=SYNTHETIC_PROVIDER,
                     provider_team_key=f"{league_key}.t.{i}",
                     provider_team_id=i)
            db.add(t)
            db.flush()
            db.add(Wallet(team_id=t.id, balance=0.0))
            teams.append(t)
        db.flush()
        return league, teams

    def record_postseason(db, league, teams):
        """The bracket, through the SHARED recorder every close-driving suite
        uses. One copy of the fixture, so WP3, WP6 and WP6B cannot drift into
        three subtly different postseasons while all reporting green."""
        record_synthetic_postseason(
            db, league, teams, semifinal_week=SEMIFINAL_WEEK,
            championship_week=CHAMPIONSHIP_WEEK,
            podium_indexes=EXPECTED_PODIUM + (THIRD_PLACE_LOSER,))

    def grant_commissioner(db, league_id: int, email: str):
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(email=email, hashed_password=hash_password(PASSWORD),
                        role="commissioner")
            db.add(user)
            db.flush()
        db.add(LeagueCommissioner(league_id=league_id, user_id=user.id,
                                  source="bootstrap"))
        db.flush()
        return user

    def record_results(db, lid: int, tids: list[int], *, finalized=True):
        for week, rows in WEEK_RESULTS.items():
            for home, away, hs, aws in rows:
                db.add(Matchup(league_id=lid, week=week,
                               home_team_id=tids[home], away_team_id=tids[away],
                               home_score=hs, away_score=aws,
                               refreshed_at=now_naive(),
                               finalized_at=now_naive() if finalized else None))
        db.flush()

    def run_pool_money_path(db, lid: int, tids: list[int], *, week: int,
                           settle: bool = True):
        """One week of governed Pool money, through the REAL ledger doors.

        The occurrences themselves are written directly rather than drawn — the
        governed draw and settlement are certified by WP2B-C, and re-running the
        provider chain here would make this suite depend on a corpus the season
        close never reads. What matters to the close is the STATE those steps
        leave behind: four `PoolInstance` rows, a drained `pool:{league}`, and a
        Championship credit that arrived through `pool_championship_sweep`.
        """
        keys = [k for (k,) in db.query(PoolDefinition.key)
                .order_by(PoolDefinition.catalog_number).limit(4).all()]

        # Collection: every GM's entry sourced from their released Weekly
        # Minimum, exactly as betting/pool_funding routes it through
        # economy.spend_sourcing.
        legs = [(min_account(tid, week), -POOL_ENTRY_CENTS) for tid in tids]
        legs.append((f"pool:{lid}", POOL_TOTAL_CENTS))
        ledger_post(legs, door="pool_weekly_collection", session=db)
        # Flush between postings: the ledger's funded-balance guard reads the
        # in-session balance, and an unflushed credit is invisible to it.
        db.flush()
        if POOL_REMAINDER_CENTS:
            ledger_post([(f"pool:{lid}", -POOL_REMAINDER_CENTS),
                         (championship_account(lid), POOL_REMAINDER_CENTS)],
                        door="pool_division_remainder", session=db)
            db.flush()

        instances = []
        for slot, key in enumerate(keys, start=1):
            inst = PoolInstance(league_id=lid, season=SEASON, week=week,
                                phase="REGULAR", rotation_cycle=1,
                                definition_key=key, slot=slot,
                                pot_cents=POOL_SHARE_CENTS, rollover_cents=0,
                                settled=False, distributed_cents=0)
            db.add(inst)
            instances.append(inst)
        db.flush()

        if not settle:
            return instances

        # Slot 1 sweeps to championship; slots 2-4 pay a winner. Between them
        # the four shares exactly drain the pool account.
        ledger_post([(f"pool:{lid}", -POOL_SHARE_CENTS),
                     (championship_account(lid), POOL_SHARE_CENTS)],
                    door="pool_championship_sweep", session=db)
        db.flush()
        instances[0].settled = True
        instances[0].settled_at = now_naive()
        instances[0].settlement_classification = "ZERO_ELIGIBLE_CLAIMS"

        for offset, inst in enumerate(instances[1:]):
            ledger_post([(f"pool:{lid}", -POOL_SHARE_CENTS),
                         (wallet_account(tids[offset]), POOL_SHARE_CENTS)],
                        door="pool_winner_distribution", session=db)
            db.flush()
            inst.settled = True
            inst.settled_at = now_naive()
            inst.settlement_classification = "CLAIMS_PRESENT"
            inst.distributed_cents = POOL_SHARE_CENTS
        db.flush()
        return instances

    def build(name: str, *, with_pool: bool = True, finalized: bool = True,
              assess: bool = True, expire: bool = True,
              with_postseason: bool = True):
        """A league driven to the brink of a legitimate close."""
        tdb.reset()
        if with_pool:
            with redirect_stdout(io.StringIO()):
                assert bootstrap.main([]) == 0
        with SessionLocal() as db:
            league, teams = make_league(db, name)
            lid = league.id
            tids = [t.id for t in teams]
            grant_commissioner(db, lid, f"{name}-comm@x.test")
            record_results(db, lid, tids, finalized=finalized)
            if with_postseason:
                record_postseason(db, league, teams)
            db.commit()

        with SessionLocal() as db:
            activate_season_allocation(lid, db)

        with SessionLocal() as db:
            for week in PLAYED_WEEKS:
                release_week(db, league_id=lid, week=week)
            if with_pool:
                run_pool_money_path(db, lid, tids, week=PLAYED_WEEKS[0])
            if expire:
                for week in PLAYED_WEEKS:
                    expire_week(db, league_id=lid, week=week)
            if assess and finalized:
                for week in PLAYED_WEEKS:
                    assess_weekly_skunk(db, league_id=lid, week=week)
            db.commit()

        return lid, tids, bearer(f"{name}-comm@x.test")

    def close(lid: int, hdr: dict):
        return client().post(f"/league/{lid}/season/close", headers=hdr)

    def ledger_state(lid: int, tids: list[int]) -> dict:
        state = {"trial": trial_balance(),
                 "pool": balance_of(f"pool:{lid}"),
                 "championship": balance_of(championship_account(lid)),
                 "skunk": balance_of(skunk_account(lid)),
                 "points_championship": balance_of(
                     points_championship_account(lid, SEASON))}
        for tid in tids:
            state[f"wallet:{tid}"] = balance_of(wallet_account(tid))
            state[f"reserve:{tid}"] = balance_of(reserve_account(tid))
            state[f"expired_min:{tid}"] = balance_of(expired_min_account(tid))
        return state

    def season_open(lid: int) -> bool:
        with SessionLocal() as db:
            row = db.query(League).filter(League.id == lid).first()
            open_ = row.season_closed_at is None
            db.rollback()
        return open_

    # ════ 0. THE ROUTE EXISTS AND IS COMMISSIONER-ONLY, LEAGUE-SCOPED ═══════
    _section("the close is a commissioner action, scoped to one league")

    lid, tids, hdr = build("auth")
    with SessionLocal() as db:
        gm = User(email="wp3-gm@x.test", hashed_password=hash_password(PASSWORD),
                  team_id=tids[1], role="gm")
        db.add(gm)
        db.commit()
    hdr_gm = bearer("wp3-gm@x.test")

    _assert("an unauthenticated close is refused",
            client().post(f"/league/{lid}/season/close").status_code == 401)
    _assert("a NON-COMMISSIONER close is refused",
            close(lid, hdr_gm).status_code == 403)
    _assert("both refusals left the season open", season_open(lid))
    _assert("both refusals moved nothing", trial_balance() == 0)

    # ════ 1. THE PREREQUISITE CONTRACT, READ OUT OF THE CODE ════════════════
    _section("premature close refuses, naming the FIRST unmet prerequisite")

    def refuses_at(label: str, expected_step: str, mutate, **build_kw):
        lid, tids, hdr = build(f"pre-{expected_step}", **build_kw)
        with SessionLocal() as db:
            mutate(db, lid, tids)
            db.commit()
        before = ledger_state(lid, tids)
        r = close(lid, hdr)
        detail = r.json().get("detail", {}) if r.content else {}
        detail = detail if isinstance(detail, dict) else {}
        _assert(label,
                r.status_code == 409
                and detail.get("reason_code") == expected_step,
                f"HTTP {r.status_code} reason={detail.get('reason_code')!r}")
        _assert(f"    ...{expected_step}: season stays OPEN and nothing moved",
                season_open(lid) and ledger_state(lid, tids) == before
                and trial_balance() == 0)
        return lid, tids, hdr

    # 1 — a pending Versus wager.
    def _pending_bet(db, lid, tids):
        m = db.query(Matchup).filter(Matchup.league_id == lid).first()
        w = db.query(Wallet).filter(Wallet.team_id == tids[0]).first()
        db.add(Bet(matchup_id=m.id, wallet_id=w.id, picked_team_id=tids[0],
                   bet_type="straight", amount=1.0, odds=1.909,
                   status="pending"))
    refuses_at("a pending Versus wager refuses the close",
               "versus_terminal", _pending_bet)

    # 2 — AN UNSETTLED POOL OCCURRENCE. The brief's open question, answered by
    #     construction: this instance carries a ZERO pot and the pool account is
    #     already drained, so nothing about the MONEY is outstanding. The close
    #     still refuses. Pool settlement is a HARD prerequisite in its own right,
    #     not a proxy for `pool:{league}` being non-zero.
    def _unsettled_zero_pot_pool(db, lid, tids):
        key = (db.query(PoolDefinition.key)
               .order_by(PoolDefinition.catalog_number.desc()).first())[0]
        db.add(PoolInstance(league_id=lid, season=SEASON, week=PLAYED_WEEKS[1],
                            phase="REGULAR", rotation_cycle=1,
                            definition_key=key, slot=1, pot_cents=0,
                            rollover_cents=0, settled=False,
                            distributed_cents=0))
    lid_p, tids_p, _ = refuses_at(
        "AN UNSETTLED POOL OCCURRENCE REFUSES THE CLOSE even with a zero pot "
        "and a drained pool account — settlement is a hard prerequisite",
        "pool_settled", _unsettled_zero_pot_pool)
    with SessionLocal() as db:
        drained = balance_of(f"pool:{lid_p}")
        offending_pots = [
            int(p or 0) for (p,) in
            db.query(PoolInstance.pot_cents)
            .filter(PoolInstance.league_id == lid_p,
                    PoolInstance.settled.is_(False)).all()]
        db.rollback()
    _assert("    ...and the discriminator holds: the offending occurrence's pot "
            "was 0 and pool:{league} was already 0, so only `settled` refused",
            drained == 0 and offending_pots == [0],
            f"pool={drained} pots={offending_pots}")

    # 3 — unresolved escrow.
    def _open_escrow(db, lid, tids):
        ledger_post([("world", -500), ("escrow:wp3probe", 500)],
                    door="wager_placed", session=db)
    refuses_at("unresolved escrow refuses the close",
               "escrow_resolved", _open_escrow)

    # 4/5 — Weekly Minimum expiry incomplete.
    def _unexpired_minimum(db, lid, tids):
        ledger_post([(min_reserve_account(tids[0]), -700),
                     (min_account(tids[0], PLAYED_WEEKS[1]), 700)],
                    door="weekly_minimum_release", session=db)
    refuses_at("an unexpired Weekly Minimum refuses the close",
               "weekly_minimum_expiry", _unexpired_minimum)

    # 6/7 — a week that is not economically final.
    def _unfinalize(db, lid, tids):
        db.query(EconomyEvent).filter(
            EconomyEvent.league_id == lid,
            EconomyEvent.event_type == "SKUNK_ASSESSMENT",
            EconomyEvent.week == PLAYED_WEEKS[1]).delete()
        for m in db.query(Matchup).filter(Matchup.league_id == lid,
                                          Matchup.week == PLAYED_WEEKS[1]).all():
            m.finalized_at = None
    refuses_at("a week with finalized_at IS NULL refuses the close",
               "results_not_ready", _unfinalize)

    def _unassess(db, lid, tids):
        db.query(EconomyEvent).filter(
            EconomyEvent.league_id == lid,
            EconomyEvent.event_type == "SKUNK_ASSESSMENT",
            EconomyEvent.week == PLAYED_WEEKS[1]).delete()
    refuses_at("an unassessed Skunk week refuses the close",
               "skunk_assessed", _unassess)

    # 8 — a live Pool rollover AT THE SEASON BOUNDARY.
    #
    # WP6F OWNER RULING SUPERSEDES THE ORIGINAL ASSERTION HERE, and the change is
    # stated rather than quietly dropped. Terminal rollover expiry is a
    # SEASON-BOUNDARY SETTLEMENT RULE (BAB-805, BAB-901, AP-166): at
    # `season_final_week` a carry with no later eligible occurrence transfers to
    # the Championship Pot. This route derives `final_week` from the league, so
    # every close taken through it is AT the boundary — which makes a live carry
    # WORK THE CLOSE PERFORMS, not a reason to refuse it.
    #
    # THE REFUSAL WAS NARROWED BY THE RULING, NOT REMOVED, so both halves are
    # proved: the boundary sweep here, and the sub-boundary refusal immediately
    # below. Asserting only the first would leave the product free to vacuum a
    # LIVE carry into Championship mid-season and this suite would not notice.
    def _live_rollover(db, lid, tids):
        inst = (db.query(PoolInstance)
                .filter(PoolInstance.league_id == lid)
                .order_by(PoolInstance.slot).first())
        inst.rollover_cents = 100
        ledger_post([(championship_account(lid), -100), (f"pool:{lid}", 100)],
                    door="pool_championship_sweep", session=db)
        return inst.id

    lid_rr, tids_rr, hdr_rr = build("pre-pool_rollover")
    with SessionLocal() as db:
        _carrier_id = _live_rollover(db, lid_rr, tids_rr)
        db.commit()
    _champ_before_rr = balance_of(championship_account(lid_rr))
    r_rr = close(lid_rr, hdr_rr)
    _body_rr = r_rr.json() if r_rr.content else {}
    _sweeps_rr = _body_rr.get("terminal_rollover_sweeps", [])

    _assert("a live Pool rollover AT the season boundary is SWEPT, not refused "
            "— the close completes (WP6F ruling supersedes the old refusal)",
            r_rr.status_code == 200
            and _body_rr.get("terminal_rollover_swept_cents") == 100,
            f"HTTP {r_rr.status_code} "
            f"swept={_body_rr.get('terminal_rollover_swept_cents')!r}")
    _assert("    ...and the disposal names the occurrence that CARRIED it",
            len(_sweeps_rr) == 1
            and _sweeps_rr[0]["pool_instance_id"] == _carrier_id
            and _sweeps_rr[0]["amount_cents"] == 100,
            str(_sweeps_rr))
    with SessionLocal() as db:
        _carry_after = (db.query(PoolInstance)
                        .filter(PoolInstance.id == _carrier_id).first()
                        .rollover_cents)
        db.rollback()
    _assert("    ...the carry is discharged and the Pool account drained",
            int(_carry_after or 0) == 0 and balance_of(f"pool:{lid_rr}") == 0,
            f"rollover={_carry_after} pool={balance_of(f'pool:{lid_rr}')}")
    _assert("    ...the season is CLOSED and the ledger still balances",
            not season_open(lid_rr) and trial_balance() == 0,
            f"open={season_open(lid_rr)} trial={trial_balance()}")

    # BELOW THE BOUNDARY IT STILL REFUSES. Asserted against
    # `verify_preconditions` directly because the route cannot reach this state:
    # it derives `final_week` from the league, so a route close is always AT the
    # boundary. The gate exists for every other caller, and this is where it is
    # proved.
    from economy.season_close_orchestrator import (  # noqa: E402
        SeasonClosePreconditionError, verify_preconditions,
    )

    lid_early, tids_early, _hdr_early = build("early-pool_rollover")
    with SessionLocal() as db:
        _live_rollover(db, lid_early, tids_early)
        db.commit()
    with SessionLocal() as db:
        try:
            verify_preconditions(db, league_id=lid_early,
                                 final_week=SEASON_FINAL_WEEK - 1)
            _early_step = None
        except SeasonClosePreconditionError as exc:
            _early_step = exc.step
        db.rollback()
    _assert("a live Pool rollover BELOW the boundary still refuses at "
            "`pool_rollover` — a close taken early cannot vacuum a live carry "
            "into Championship", _early_step == "pool_rollover",
            str(_early_step))
    _assert("    ...and that refusal moved nothing",
            balance_of(f"pool:{lid_early}") == 100 and trial_balance() == 0,
            f"pool={balance_of(f'pool:{lid_early}')}")

    # 9 — the Pool account still holds money with nothing to explain it.
    def _stranded_pool_money(db, lid, tids):
        ledger_post([(championship_account(lid), -50), (f"pool:{lid}", 50)],
                    door="pool_championship_sweep", session=db)
    refuses_at("a non-zero pool account refuses the close",
               "pool_zero", _stranded_pool_money)

    # 9b — an unresolved provider conflict. Written through the PRODUCTION
    #      writer, `providers.yahoo.persist.record_conflict`, so the row this
    #      precondition reads is the row the gateway would actually have left.
    def _provider_conflict(db, lid, tids):
        from providers.yahoo.persist import record_conflict

        record_conflict(db, league_id=lid,
                        external_identity="999.l.100001.m.1",
                        conflict_type="POST_FINAL_SCORE",
                        contradicted_field="home_score",
                        existing_value="120.5", provider_value="130.0",
                        now=datetime.now(timezone.utc))
    lid_c, tids_c, hdr_c = refuses_at(
        "an unresolved provider conflict refuses the close",
        "provider_conflict", _provider_conflict)

    # ...AND ACKNOWLEDGEMENT CLEARS IT. Without this control the gate above
    # would be indistinguishable from one that can never be satisfied, and a
    # permanently unclearable precondition is not a gate — it is a wall.
    from providers.yahoo.persist import acknowledge_conflict

    tb_before_ack = trial_balance()
    with SessionLocal() as db:
        for (key,) in db.query(ProviderConflict.conflict_key).filter(
                ProviderConflict.league_id == lid_c,
                ProviderConflict.resolved_at.is_(None)).all():
            acknowledge_conflict(db, conflict_key_value=key,
                                 operator="wp3-suite",
                                 note="reviewed for the WP3 control",
                                 now=datetime.now(timezone.utc))
        db.commit()
    _assert("acknowledging the conflict moved no money",
            trial_balance() == tb_before_ack)
    r_ack = close(lid_c, hdr_c)
    _assert("    ...and with it acknowledged the SAME league closes — the gate "
            "is clearable, not a wall", r_ack.status_code == 200,
            f"{r_ack.status_code} {r_ack.text[:200]}")

    # ════ 2. THE VALID CLOSE ════════════════════════════════════════════════
    _section("a fully prepared league closes through the production route")

    lid, tids, hdr = build("close")
    with SessionLocal() as db:
        weekly_min = weekly_minimum_cents(db, lid)
        db.rollback()

    before = ledger_state(lid, tids)
    reserve_each = before[f"reserve:{tids[0]}"]
    expired_each = before[f"expired_min:{tids[0]}"]
    pot_expected = reserve_each * N_TEAMS + POOL_REMAINDER_CENTS + POOL_SHARE_CENTS

    print(f"     weekly minimum = {weekly_min}  reserve/GM = {reserve_each}  "
          f"expired_min/GM = {expired_each}")
    _assert("the Final POR fixture has no retired per-GM reserve; its adapter "
            "pot contains only the Pool remainder and swept occurrence",
            before["championship"] == POOL_REMAINDER_CENTS + POOL_SHARE_CENTS
            and reserve_each == 0,
            f"championship={before['championship']} reserve={reserve_each}")
    _assert("Final POR week close leaves no expired-Minimum balance to return",
            all(before[f"expired_min:{t}"] == expired_each for t in tids)
            and expired_each == 0, str(expired_each))
    _assert("Skunk assessments fund the current Points Championship, not the "
            "retired Skunk account",
            before["skunk"] == 0
            and before["points_championship"] == 2 * 1000,
            f"legacy={before['skunk']} points={before['points_championship']}")
    _assert("the pool account is already drained", before["pool"] == 0)
    _assert("trial balance is zero before the close", before["trial"] == 0)

    r = close(lid, hdr)
    _assert("THE CLOSE RETURNS 200", r.status_code == 200,
            f"{r.status_code} {r.text[:300]}")
    body = r.json() if r.status_code == 200 else {}
    print(f"     closed_now={body.get('closed_now')} "
          f"replayed={body.get('replayed')} "
          f"pot={body.get('championship_pot_cents')} "
          f"swept={body.get('reserve_swept_cents')} "
          f"skunk={body.get('skunk_distributed_cents')} "
          f"expired_returned={body.get('expired_min_returned_cents')}")

    _assert("it reports THIS call as the one that closed the season",
            body.get("closed_now") is True and body.get("replayed") is False)
    _assert("the returned product state carries the persisted close stamp",
            bool(body.get("season_closed_at")), str(body.get("season_closed_at")))
    _assert("the operator echoed back is the AUTHENTICATED commissioner, not a "
            "constant", body.get("operator") == "close-comm@x.test",
            str(body.get("operator")))
    _assert("final_week was derived from the league, never accepted from the "
            "caller", body.get("final_week") == SEASON_FINAL_WEEK,
            str(body.get("final_week")))

    with SessionLocal() as db:
        stamp = db.query(League).filter(League.id == lid).first().season_closed_at
        db.rollback()
    _assert("League.season_closed_at is PERSISTED", stamp is not None)

    # ── Championship Reserve: swept, then 60/30/10 exactly ──────────────────
    _section("Championship Reserve sweep and the exact 60/30/10 distribution")

    _assert("every GM's reserve was swept into the league pot",
            body.get("reserve_swept_cents") == reserve_each * N_TEAMS,
            f"{body.get('reserve_swept_cents')} vs {reserve_each * N_TEAMS}")
    _assert("the distributed pot is the swept reserves PLUS the Pool money that "
            "had already arrived",
            body.get("championship_pot_cents") == pot_expected,
            f"{body.get('championship_pot_cents')} vs {pot_expected}")

    pot = pot_expected
    exp_amounts = [pot * 60 // 100, pot * 30 // 100, pot * 10 // 100]
    exp_amounts[0] += pot - sum(exp_amounts)     # first place absorbs it all
    expected_placements = [
        {"place": i + 1, "team_id": tids[EXPECTED_PODIUM[i]],
         "pct": [60, 30, 10][i], "cents": exp_amounts[i]}
        for i in range(3)
    ]
    print(f"     pot={pot} -> {exp_amounts} (remainder "
          f"{pot - (pot * 60 // 100 + pot * 30 // 100 + pot * 10 // 100)} to "
          f"first place)")
    _assert("THE PLACEMENTS ARE EXACTLY 60/30/10 WITH THE WHOLE REMAINDER TO "
            "FIRST PLACE",
            body.get("championship_placements") == expected_placements,
            f"{body.get('championship_placements')} vs {expected_placements}")
    _assert("the split is exhaustive — the three placements sum to the pot",
            sum(p["cents"] for p in body["championship_placements"]) == pot,
            str(sum(p["cents"] for p in body["championship_placements"])))
    # ── WP1D — THE RECIPIENT ORDER IS THE POSTSEASON PODIUM ──────────────────
    #
    # champion, championship-game runner-up, official third-place-game winner —
    # and NOT the top three by regular-season Points For, which this fixture
    # arranges to be a completely disjoint set of teams. The old assertion here
    # pinned the Points For order as product authority; that pin was the defect
    # WP1D removes, so it is replaced rather than relaxed. Both orders are still
    # named below, so the suite fails loudly if the two are ever swapped back.
    _pf_order = [tids[i] for i in (1, 2, 4)]
    _assert("the placed teams are the CHAMPION, the RUNNER-UP and the "
            "THIRD-PLACE-GAME WINNER — not the top three by Points For, not "
            "ascending team id, not the first three teams",
            [p["team_id"] for p in body["championship_placements"]]
            == [tids[i] for i in EXPECTED_PODIUM]
            != sorted(tids)[:3],
            str([p["team_id"] for p in body["championship_placements"]]))
    _assert("    ...and that order is DISJOINT from the regular-season Points "
            "For order, so a reversion to the old authority cannot pass",
            not set(tids[i] for i in EXPECTED_PODIUM) & set(_pf_order),
            f"podium={[tids[i] for i in EXPECTED_PODIUM]} pf={_pf_order}")

    after = ledger_state(lid, tids)
    for i, place_index in enumerate(EXPECTED_PODIUM):
        tid = tids[place_index]
        gained = after[f"wallet:{tid}"] - before[f"wallet:{tid}"]
        expected = exp_amounts[i] + expired_each
        if place_index == EXPECTED_SKUNK_WINNER:
            expected += before["skunk"]
        _assert(f"    place {i + 1} wallet moved by exactly its championship "
                f"share plus its own reconciled money",
                gained == expected, f"{gained} vs {expected}")

    # WP1D — THE TWO AUTHORITIES ARE PROVED APART HERE, not just asserted apart.
    # `EXPECTED_SKUNK_WINNER` is the highest regular-season scorer and is NOT on
    # the podium, so this loop states both halves at once: the Points For leader
    # takes the Skunk pot and receives NOT ONE CENT of the Championship Pot. An
    # implementation that reverted the Pot to Points For would pay them 60% here
    # and fail on the very first unplaced GM.
    unplaced = [(idx, t) for idx, t in enumerate(tids)
                if idx not in EXPECTED_PODIUM]
    points_awards = {
        tids[1]: before["points_championship"] * 60 // 100,
        tids[2]: before["points_championship"] * 30 // 100,
        tids[4]: before["points_championship"] * 10 // 100,
    }
    for idx, tid in unplaced:
        gained = after[f"wallet:{tid}"] - before[f"wallet:{tid}"]
        expected = points_awards.get(tid, 0)
        _assert(f"    an unplaced GM received NO championship money — only "
                f"their governed Points Championship award, if placed there",
                gained == expected, f"{gained} vs {expected}")

    # ── Weekly Minimum reconciliation ───────────────────────────────────────
    _section("expired Weekly Minimum is reconciled exactly once, to its owner")

    _assert("the whole league's expired minimum was returned",
            body.get("expired_min_returned_cents") == expired_each * N_TEAMS,
            f"{body.get('expired_min_returned_cents')} vs "
            f"{expired_each * N_TEAMS}")
    _assert("every expired_min account is now empty",
            all(after[f"expired_min:{t}"] == 0 for t in tids),
            str([after[f"expired_min:{t}"] for t in tids]))
    _assert("the return went to the SAME GM's own Wallet — no GM gained another "
            "GM's expired minimum",
            all(after[f"wallet:{t}"] - before[f"wallet:{t}"] >= expired_each
                for t in tids))

    with SessionLocal() as db:
        recon_events = (db.query(EconomyEvent)
                        .filter(EconomyEvent.league_id == lid,
                                EconomyEvent.event_type
                                == "EXPIRED_MINIMUM_RECONCILIATION").count())
        db.rollback()
    _assert("Final POR records no retired expired-Minimum reconciliation event",
            recon_events == 0,
            str(recon_events))

    # ── Final reconciliation ────────────────────────────────────────────────
    _section("final balances reconcile")

    _assert("every account the close must empty IS empty",
            all(v == 0 for v in body["zero_assertions"].values()),
            str({k: v for k, v in body["zero_assertions"].items() if v}))
    _assert("championship, skunk, pool and every reserve/expired_min are zero "
            "read straight from the ledger",
            after["championship"] == 0 and after["skunk"] == 0
            and after["pool"] == 0
            and all(after[f"reserve:{t}"] == 0 for t in tids),
            str({k: v for k, v in after.items() if v and "wallet" not in k}))
    # THE SKUNK POT IS STILL RANKED BY POINTS FOR, AND THAT IS CORRECT.
    # WP1D moved the CHAMPIONSHIP Pot off regular-season scoring; it did not
    # move the Skunk Pot, whose whole premise is season-long scoring. Both live
    # in this one suite deliberately, so a later change that collapses the two
    # authorities into one rule cannot pass.
    _assert("the Points Championship paid 60/30/10 by regular-season Points "
            "For, independently of the postseason podium",
            after[f"wallet:{tids[EXPECTED_SKUNK_WINNER]}"]
            - before[f"wallet:{tids[EXPECTED_SKUNK_WINNER]}"]
            == points_awards[tids[EXPECTED_SKUNK_WINNER]]
            and EXPECTED_SKUNK_WINNER not in EXPECTED_PODIUM,
            f"{after[f'wallet:{tids[EXPECTED_SKUNK_WINNER]}'] - before[f'wallet:{tids[EXPECTED_SKUNK_WINNER]}']} "
            f"vs {points_awards[tids[EXPECTED_SKUNK_WINNER]]}")
    _assert("the Skunk loser still carries their receivable — the close "
            "collects no receivable",
            balance_of(receivable_account(tids[0])) == -2000,
            str(balance_of(receivable_account(tids[0]))))
    _assert("min_reserve is untouched by the close",
            balance_of(min_reserve_account(tids[0]))
            == balance_of(min_reserve_account(tids[1])) > 0)
    _assert("TRIAL BALANCE IS ZERO after the close", trial_balance() == 0)
    _assert("the returned product state carries a Current Settle for every GM",
            len(body.get("current_settle") or {}) == N_TEAMS,
            str(len(body.get("current_settle") or {})))

    # ════ 3. NO DOUBLE CLOSE, NO DOUBLE DISTRIBUTION ════════════════════════
    _section("a repeated close moves nothing")

    settled_state = ledger_state(lid, tids)
    r2 = close(lid, hdr)
    _assert("a repeated close still returns 200", r2.status_code == 200,
            f"{r2.status_code} {r2.text[:200]}")
    body2 = r2.json() if r2.status_code == 200 else {}
    _assert("it reports REPLAYED, not a second close",
            body2.get("replayed") is True and body2.get("closed_now") is False,
            f"replayed={body2.get('replayed')} closed_now={body2.get('closed_now')}")
    _assert("it re-posts NOTHING — no sweep, no championship, no expired-min "
            "return",
            (body2.get("reserve_swept_cents"),
             body2.get("championship_pot_cents"),
             body2.get("skunk_distributed_cents"),
             body2.get("expired_min_returned_cents")) == (0, 0, 0, 0),
            str(body2))
    _assert("NOT ONE ACCOUNT MOVED on the repeat",
            ledger_state(lid, tids) == settled_state,
            str({k: (settled_state[k], ledger_state(lid, tids)[k])
                 for k in settled_state
                 if settled_state[k] != ledger_state(lid, tids)[k]}))
    _assert("the ORIGINAL close stamp is returned, not a new one",
            body2.get("season_closed_at") == body.get("season_closed_at"),
            f"{body2.get('season_closed_at')} vs {body.get('season_closed_at')}")

    with SessionLocal() as db:
        champ_events = (db.query(EconomyEvent)
                        .filter(EconomyEvent.league_id == lid,
                                EconomyEvent.event_type
                                == "CHAMPIONSHIP_DISTRIBUTION").count())
        db.rollback()
    _assert("exactly ONE championship distribution event exists for the league",
            champ_events == 1, str(champ_events))

    for _ in range(3):
        close(lid, hdr)
    _assert("three further closes still move nothing",
            ledger_state(lid, tids) == settled_state)
    _assert("trial balance is still zero", trial_balance() == 0)

    # ════ 4. ROLLBACK SAFETY ════════════════════════════════════════════════
    _section("a failure mid-close leaves NO partial durable state")

    import economy.season_close_orchestrator as orch

    lid, tids, hdr = build("rollback")
    before = ledger_state(lid, tids)
    real_reconcile = orch.reconcile_expired_minimum

    def _explode(*args, **kwargs):
        # Step 13 — AFTER the reserve sweep (10), Skunk (11) and the whole
        # Championship distribution (12) have already been written into the
        # transaction. If any of those could survive a later failure, this is
        # where it would show.
        raise RuntimeError("WP3 control: a fault during expired-min reconciliation")

    orch.reconcile_expired_minimum = _explode
    try:
        r_fail = close(lid, hdr)
    finally:
        orch.reconcile_expired_minimum = real_reconcile

    _assert("the failed close did not return success", r_fail.status_code != 200,
            str(r_fail.status_code))
    _assert("THE SEASON IS STILL OPEN — no close stamp survived",
            season_open(lid))
    _assert("the reserve sweep did NOT survive: every reserve still holds its "
            "own money",
            all(balance_of(reserve_account(t)) == reserve_each for t in tids),
            str([balance_of(reserve_account(t)) for t in tids]))
    _assert("the Championship distribution did NOT survive: the pot is exactly "
            "what it was and no wallet gained",
            ledger_state(lid, tids) == before,
            str({k: (before[k], ledger_state(lid, tids)[k])
                 for k in before if before[k] != ledger_state(lid, tids)[k]}))

    with SessionLocal() as db:
        leaked = (db.query(EconomyEvent)
                  .filter(EconomyEvent.league_id == lid,
                          EconomyEvent.event_type.in_(
                              ["RESERVE_SWEEP", "CHAMPIONSHIP_DISTRIBUTION",
                               "SKUNK_DISTRIBUTION"])).count())
        db.rollback()
    _assert("no economy event row survived either — the exactly-once claims "
            "were rolled back with their postings", leaked == 0, str(leaked))
    _assert("trial balance is zero after the failure", trial_balance() == 0)

    r_retry = close(lid, hdr)
    _assert("THE CLOSE IS SAFELY RETRYABLE — the same league closes cleanly "
            "once the fault is gone", r_retry.status_code == 200,
            f"{r_retry.status_code} {r_retry.text[:200]}")
    _assert("the retry distributed the full pot exactly once",
            r_retry.json().get("championship_pot_cents") == pot_expected,
            str(r_retry.json().get("championship_pot_cents")))
    _assert("trial balance is zero after the retry", trial_balance() == 0)

    # ════ 5. CROSS-LEAGUE ISOLATION ═════════════════════════════════════════
    _section("WP1D · a league whose bracket nobody can classify fails CLOSED "
             "through the production route")

    # THIS IS THE LIVE YAHOO CASE, REACHED THROUGH THE REAL ROUTE.
    # `with_postseason=False` records no games and registers no source for this
    # league, which is exactly the state a Yahoo-bound league is in today:
    # `providers/yahoo/normalize.py` never populates `bracket`, and no postseason
    # source claims a Yahoo league key. The league is otherwise driven to the
    # brink of a legitimate close — every one of the nine preconditions is met —
    # so what refuses is the podium and nothing else.
    lid_u, tids_u, hdr_u = build("wp1d-unclassified",
                                 with_postseason=False)
    _before_u = ledger_state(lid_u, tids_u)
    r_u = close(lid_u, hdr_u)
    _body_u = r_u.json() if r_u.content else {}
    _detail_u = _body_u.get("detail", {}) if isinstance(_body_u, dict) else {}

    _assert("an unclassifiable postseason refuses the close with 409, not 500 "
            "and not a silent success",
            r_u.status_code == 409, f"{r_u.status_code} {r_u.text[:200]}")
    _assert("    ...and the reason names the podium condition an operator must "
            "wait for, rather than a generic conflict",
            _detail_u.get("reason_code") == "PODIUM_STATE_UNKNOWN",
            str(_detail_u.get("reason_code")))
    _assert("    ...the season is STILL OPEN and no close stamp was written",
            season_open(lid_u))
    _assert("    ...NOT ONE cent moved — the reserve sweep, the Skunk "
            "distribution and the rollover sweep all rolled back with the "
            "refusal",
            ledger_state(lid_u, tids_u) == _before_u and trial_balance() == 0,
            str({k: v for k, v in ledger_state(lid_u, tids_u).items()
                 if _before_u.get(k) != v}))

    # AND IT IS THE PODIUM THAT REFUSED, NOT A PRECONDITION. The same fixture
    # WITH a recorded bracket closes, which is what makes the assertion above a
    # statement about WP1D rather than about some unrelated gap in the fixture.
    lid_k, tids_k, hdr_k = build("wp1d-classified")
    r_k = close(lid_k, hdr_k)
    _assert("    ...while the SAME fixture with a classified bracket closes "
            "normally — the refusal is the podium's, not the fixture's",
            r_k.status_code == 200, f"{r_k.status_code} {r_k.text[:200]}")


    _section("one league cannot close another")

    tdb.reset()
    with redirect_stdout(io.StringIO()):
        assert bootstrap.main([]) == 0
    with SessionLocal() as db:
        league_a, teams_a = make_league(db, "iso-a")
        league_b, teams_b = make_league(db, "iso-b")
        lid_a, lid_b = league_a.id, league_b.id
        tids_a = [t.id for t in teams_a]
        tids_b = [t.id for t in teams_b]
        grant_commissioner(db, lid_a, "iso-a-comm@x.test")
        grant_commissioner(db, lid_b, "iso-b-comm@x.test")
        record_results(db, lid_a, tids_a)
        record_results(db, lid_b, tids_b)
        # WP1D — each league gets its OWN postseason, recorded under its own
        # provider league key. A bracket source that leaked one league's games
        # into the other would pay league A's champion out of league B's pot,
        # which is exactly the isolation this section exists to prove.
        record_postseason(db, league_a, teams_a)
        record_postseason(db, league_b, teams_b)
        db.commit()
    for _lid in (lid_a, lid_b):
        with SessionLocal() as db:
            activate_season_allocation(_lid, db)
        with SessionLocal() as db:
            for week in PLAYED_WEEKS:
                release_week(db, league_id=_lid, week=week)
            run_pool_money_path(db, _lid,
                                tids_a if _lid == lid_a else tids_b,
                                week=PLAYED_WEEKS[0])
            for week in PLAYED_WEEKS:
                expire_week(db, league_id=_lid, week=week)
                assess_weekly_skunk(db, league_id=_lid, week=week)
            db.commit()

    hdr_a = bearer("iso-a-comm@x.test")
    hdr_b = bearer("iso-b-comm@x.test")

    b_before = ledger_state(lid_b, tids_b)
    _assert("league A's commissioner CANNOT close league B",
            close(lid_b, hdr_a).status_code == 403)
    _assert("league B's commissioner CANNOT close league A",
            close(lid_a, hdr_b).status_code == 403)

    r_a = close(lid_a, hdr_a)
    _assert("league A closes on its own authority", r_a.status_code == 200,
            f"{r_a.status_code} {r_a.text[:200]}")
    _assert("LEAGUE B IS UNTOUCHED — still open, every balance identical",
            season_open(lid_b) and ledger_state(lid_b, tids_b) == b_before,
            str({k: (b_before[k], ledger_state(lid_b, tids_b)[k])
                 for k in b_before
                 if b_before[k] != ledger_state(lid_b, tids_b)[k]}))
    _assert("league A's championship pot came only from league A's own "
            "reserves and Pool money",
            r_a.json().get("championship_pot_cents") == pot_expected,
            str(r_a.json().get("championship_pot_cents")))
    _assert("trial balance is zero across both leagues", trial_balance() == 0)

    r_b = close(lid_b, hdr_b)
    _assert("league B then closes independently", r_b.status_code == 200,
            f"{r_b.status_code} {r_b.text[:200]}")
    _assert("and gets its own identical pot",
            r_b.json().get("championship_pot_cents") == pot_expected)
    _assert("trial balance is zero after both closes", trial_balance() == 0)

    # ════ 6. POSTGRESQL SERIALIZATION — TWO CONCURRENT CLOSES ═══════════════
    _section("two concurrent closes: the League row lock admits exactly one")

    lid, tids, hdr = build("race")
    before = ledger_state(lid, tids)

    barrier = threading.Barrier(2, timeout=90)
    results: dict[str, object] = {}
    lock = threading.Lock()

    def racer(name: str):
        def run():
            try:
                barrier.wait()
                resp = close(lid, hdr)
                payload = resp.json() if resp.content else {}
                with lock:
                    results[name] = (resp.status_code, payload)
            except Exception as exc:                       # noqa: BLE001
                with lock:
                    results[name] = ("error", f"{type(exc).__name__}: {exc}")
        return run

    threads = [threading.Thread(target=racer(f"w{i}")) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)

    _assert("both racers reported", len(results) == 2, str(list(results)))
    closed_now = [
        payload.get("closed_now")
        for status, payload in results.values()
        if status == 200 and isinstance(payload, dict)
    ]
    def _outcome(status, payload):
        if status == 200 and isinstance(payload, dict):
            return f"200 closed_now={payload.get('closed_now')}"
        if isinstance(payload, dict) and isinstance(payload.get("detail"), dict):
            return f"{status} {payload['detail'].get('reason_code')}"
        return f"{status} {str(payload)[:60]}"

    print("     race outcomes = "
          + " | ".join(_outcome(s, p) for s, p in results.values()))
    _assert("EXACTLY ONE call closed the season; the other did not stamp it "
            "again", closed_now.count(True) == 1, str(closed_now))

    # THE LOSER FAILS SAFELY AND BY NAME. Whichever way the interleaving falls,
    # the second caller either observes the completed close and replays, or is
    # refused by a NAMED governed precondition — the account-level conservation
    # assertion is the usual one, because by the time it reads the balances the
    # winner has already drained the accounts it was about to distribute. What
    # it must never be is a 500 or a second stamp.
    loser = [(s, p) for s, p in results.values()
             if not (s == 200 and isinstance(p, dict) and p.get("closed_now"))]
    _assert("there is exactly one loser", len(loser) == 1, str(loser))
    l_status, l_payload = loser[0]
    l_reason = (l_payload.get("detail", {}).get("reason_code")
                if isinstance(l_payload, dict)
                and isinstance(l_payload.get("detail"), dict) else None)
    _assert("THE CONCURRENT LOSER COMPLETES SAFELY — it observes "
            "closed_now=false or a named governed precondition refusal, "
            "never a 500 and never a second stamp",
            (l_status == 200 and isinstance(l_payload, dict)
             and l_payload.get("closed_now") is False)
            or (l_status == 409 and bool(l_reason)),
            f"status={l_status} reason={l_reason!r}")

    with SessionLocal() as db:
        stamps = (db.query(League).filter(League.id == lid).first()
                  .season_closed_at)
        champ_events = (db.query(EconomyEvent)
                        .filter(EconomyEvent.league_id == lid,
                                EconomyEvent.event_type
                                == "CHAMPIONSHIP_DISTRIBUTION").count())
        sweep_events = (db.query(EconomyEvent)
                        .filter(EconomyEvent.league_id == lid,
                                EconomyEvent.event_type
                                == "RESERVE_SWEEP").count())
        db.rollback()
    _assert("the season carries exactly one close stamp", stamps is not None)
    _assert("the Championship was distributed exactly once under the race",
            champ_events == 1, str(champ_events))
    _assert("Final POR records no retired reserve-sweep event under the race",
            sweep_events == 0, str(sweep_events))

    after = ledger_state(lid, tids)
    winner_gain = (after[f"wallet:{tids[EXPECTED_PODIUM[0]]}"]
                   - before[f"wallet:{tids[EXPECTED_PODIUM[0]]}"])
    # THE SKUNK POT IS NOT IN THIS SUM, AND ITS ABSENCE IS THE WP1D FACT.
    # Before WP1D the Championship Pot and the Skunk Pot were both ranked by
    # regular-season Points For, so first place was necessarily the Skunk winner
    # and the two terms were added together here. The champion is now the team
    # that WON THE BRACKET — in this fixture the league's lowest scorer and the
    # Skunk loser in both played weeks — so their gain is the championship share
    # and their own expired minimum, and nothing else.
    _assert("NO DOUBLE CHAMPIONSHIP PAYOUT — first place gained its share "
            "exactly once",
            winner_gain == exp_amounts[0] + expired_each,
            f"{winner_gain} vs {exp_amounts[0] + expired_each}")
    _assert("    ...and the champion received NO Skunk money — they were the "
            "Skunk LOSER, which the close does not net against their payout",
            balance_of(receivable_account(tids[EXPECTED_PODIUM[0]])) < 0,
            str(balance_of(receivable_account(tids[EXPECTED_PODIUM[0]]))))
    _assert("every account the close must empty is empty after the race",
            after["championship"] == 0 and after["skunk"] == 0
            and all(after[f"reserve:{t}"] == 0 for t in tids)
            and all(after[f"expired_min:{t}"] == 0 for t in tids))
    _assert("TRIAL BALANCE IS ZERO after the race", trial_balance() == 0)


if __name__ == "__main__":
    print("\n=== WP3 season close wiring suite (PostgreSQL) ===")
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
