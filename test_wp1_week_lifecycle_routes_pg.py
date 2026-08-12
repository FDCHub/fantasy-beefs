"""
test_wp1_week_lifecycle_routes_pg.py — WP1 · Weekly Minimum route wiring.

WHAT THIS SUITE IS FOR. `economy/weekly_minimum.py` was certified at S5-P1 and
is already proved correct by `test_s5_p1_weekly_economy_pg.py`, which drives the
service functions directly. This suite does NOT re-prove the engine. It proves
the two things the engine deliberately leaves to its caller and that nothing
previously exercised, because no caller existed:

    POST /league/{league_id}/week/{week}/open   -> release_week
    POST /league/{league_id}/week/{week}/close  -> expire_week

THE CLAIM THAT MATTERS MOST is the first one below. Season allocation posts the
opening 220 Credits to min_reserve (140) and reserve (80) and leaves Wallet at
zero, and every spend sources min-first. Before this wiring existed there was no
production path that could ever move a cent out of min_reserve, so a GM had
nothing spendable and the product could not be played. "A GM can fund something
after Week Open, and could not before" is therefore the acceptance test for the
whole work package, not a detail of it.

REAL POSTGRESQL, because the route commits and the idempotency guarantee is a
unique-constraint collision on the economy-event key. Both are properties of the
database, not of the ORM.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)
os.environ.setdefault("JWT_SECRET_KEY", "wp1-suite-secret")

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP1 suite cannot run:\n  {e}")
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


PASSWORD = "wp1-password"


def main() -> None:
    import config
    from fastapi.testclient import TestClient

    from api.main import app
    from auth.jwt_auth import hash_password
    from db.schema import (
        League, LeagueCommissioner, SessionLocal, Team, User, Wallet,
    )
    from economy.economy_events import (
        expired_min_account, min_account, min_reserve_account, wallet_account,
    )
    from economy.season_allocation import activate_season_allocation
    from economy.spend_sourcing import plan_spend_split
    from ledger.ledger import balance_of, trial_balance
    from payments.economy_config import DEFAULT_STOP

    SEASON = config.ALLOCATION_SEASON
    WEEKLY_MIN = DEFAULT_STOP.weekly_min_cents          # 1000 cents = 10 Credits
    MIN_RESERVE = DEFAULT_STOP.min_reserve_cents        # 14000 cents = 140 Credits

    def build_league(name: str, playoff_start: int = 15):
        """One league, two teams, a commissioner and a plain GM. Allocation live."""
        with SessionLocal() as db:
            league = League(season=SEASON, name=name,
                            projection_source="fantasypros",
                            season_final_week=17,
                            playoff_start_week=playoff_start)
            db.add(league)
            db.flush()

            teams = []
            for i in range(2):
                t = Team(league_id=league.id, team_name=f"{name}-t{i}",
                         owner=f"owner{i}", email=f"{name}-t{i}@x.test")
                db.add(t)
                db.flush()
                db.add(Wallet(team_id=t.id, balance=0.0))
                teams.append(t)

            pw = hash_password(PASSWORD)
            comm = User(email=f"{name}-comm@x.test", hashed_password=pw,
                        team_id=teams[0].id, role="commissioner")
            gm = User(email=f"{name}-gm@x.test", hashed_password=pw,
                      team_id=teams[1].id, role="gm")
            db.add_all([comm, gm])
            db.flush()
            db.add(LeagueCommissioner(league_id=league.id, user_id=comm.id,
                                      source="bootstrap"))
            db.commit()

            ids = (league.id, [t.id for t in teams],
                   comm.email, gm.email)

        with SessionLocal() as db:
            activate_season_allocation(ids[0], db)
        return ids

    def bearer(email: str) -> dict:
        r = TestClient(app, raise_server_exceptions=False).post(
            "/auth/login", data={"username": email, "password": PASSWORD})
        assert r.status_code == 200, f"login failed for {email}: {r.text}"
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def call(headers, verb, path):
        return TestClient(app, raise_server_exceptions=False).request(
            verb, path, headers=headers)

    tdb.reset()
    a_league, a_teams, a_comm, a_gm = build_league("wp1a")
    b_league, b_teams, b_comm, b_gm = build_league("wp1b")
    hdr_a, hdr_b, hdr_a_gm = bearer(a_comm), bearer(b_comm), bearer(a_gm)

    # ════ 1. THE ACCEPTANCE CLAIM ═══════════════════════════════════════════
    _section("before Week Open a GM has nothing spendable; after it, he does")

    team = a_teams[0]
    _assert("opening Wallet is 0",
            balance_of(wallet_account(team)) == 0,
            str(balance_of(wallet_account(team))))
    _assert("opening min_reserve is the governed 140 Credits",
            balance_of(min_reserve_account(team)) == MIN_RESERVE,
            str(balance_of(min_reserve_account(team))))

    with SessionLocal() as db:
        before = plan_spend_split(db, team, 4, WEEKLY_MIN)
    _assert("before Week Open the min account is empty",
            balance_of(min_account(team, 4)) == 0)
    _assert("before Week Open a spend can only reach an empty Wallet",
            all(acct.startswith("wallet:") for acct, _ in before), str(before))

    r = call(hdr_a, "POST", f"/league/{a_league}/week/4/open")
    _assert("Week Open succeeds for the league's commissioner",
            r.status_code == 200, f"{r.status_code} {r.text[:160]}")
    body = r.json() if r.status_code == 200 else {}
    _assert("Week Open released one weekly minimum per team",
            body.get("total_released_cents") == WEEKLY_MIN * len(a_teams),
            str(body.get("total_released_cents")))
    _assert("Week Open reports the week was not already open",
            body.get("already_open") is False)

    # ════ 2. CORRECT RESERVE MOVEMENT ═══════════════════════════════════════
    _section("reserve movement is exactly min_reserve -> min, nothing else")

    _assert("min:{team}:4 now holds one weekly minimum",
            balance_of(min_account(team, 4)) == WEEKLY_MIN,
            str(balance_of(min_account(team, 4))))
    _assert("min_reserve fell by exactly one weekly minimum",
            balance_of(min_reserve_account(team)) == MIN_RESERVE - WEEKLY_MIN,
            str(balance_of(min_reserve_account(team))))
    _assert("Wallet was not credited by Week Open",
            balance_of(wallet_account(team)) == 0,
            str(balance_of(wallet_account(team))))
    _assert("trial balance is zero after Week Open", trial_balance() == 0)

    with SessionLocal() as db:
        after = plan_spend_split(db, team, 4, WEEKLY_MIN)
    _assert("after Week Open the same spend sources min-first",
            after and after[0][0] == min_account(team, 4), str(after))

    # ════ 3. IDEMPOTENCY / REPEATED REQUEST ═════════════════════════════════
    _section("repeated Week Open cannot double-issue")

    r2 = call(hdr_a, "POST", f"/league/{a_league}/week/4/open")
    _assert("a repeated Week Open still returns 200", r2.status_code == 200,
            str(r2.status_code))
    _assert("a repeated Week Open reports already_open",
            r2.json().get("already_open") is True)
    _assert("a repeated Week Open released nothing",
            r2.json().get("total_released_cents") == 0,
            str(r2.json().get("total_released_cents")))
    _assert("the min account did not move on the repeat",
            balance_of(min_account(team, 4)) == WEEKLY_MIN,
            str(balance_of(min_account(team, 4))))
    _assert("min_reserve did not move on the repeat",
            balance_of(min_reserve_account(team)) == MIN_RESERVE - WEEKLY_MIN,
            str(balance_of(min_reserve_account(team))))
    _assert("trial balance is zero after the repeat", trial_balance() == 0)

    # ════ 4. AUTHORIZATION ══════════════════════════════════════════════════
    _section("authorization")

    _assert("an unauthenticated caller is refused",
            call({}, "POST", f"/league/{a_league}/week/5/open").status_code == 401,
            str(call({}, "POST", f"/league/{a_league}/week/5/open").status_code))
    _assert("a team owner who is not a commissioner is refused",
            call(hdr_a_gm, "POST", f"/league/{a_league}/week/5/open").status_code == 403,
            str(call(hdr_a_gm, "POST", f"/league/{a_league}/week/5/open").status_code))
    _assert("an unauthenticated Week Close is refused",
            call({}, "POST", f"/league/{a_league}/week/4/close").status_code == 401)
    _assert("a non-commissioner Week Close is refused",
            call(hdr_a_gm, "POST", f"/league/{a_league}/week/4/close").status_code == 403)

    # ════ 5. LEAGUE ISOLATION ═══════════════════════════════════════════════
    _section("league isolation")

    _assert("league B's commissioner cannot open league A's week",
            call(hdr_b, "POST", f"/league/{a_league}/week/5/open").status_code == 403,
            str(call(hdr_b, "POST", f"/league/{a_league}/week/5/open").status_code))
    _assert("league A's commissioner cannot open league B's week",
            call(hdr_a, "POST", f"/league/{b_league}/week/5/open").status_code == 403)

    b_team = b_teams[0]
    _assert("league B's min account was never touched by league A's Week Open",
            balance_of(min_account(b_team, 4)) == 0,
            str(balance_of(min_account(b_team, 4))))
    _assert("league B's min_reserve is still its full opening allocation",
            balance_of(min_reserve_account(b_team)) == MIN_RESERVE,
            str(balance_of(min_reserve_account(b_team))))

    r_b = call(hdr_b, "POST", f"/league/{b_league}/week/4/open")
    _assert("league B opens its own week independently", r_b.status_code == 200)
    _assert("league A's balances are unchanged by league B's Week Open",
            balance_of(min_account(team, 4)) == WEEKLY_MIN)

    # ════ 6. INVALID STATE ══════════════════════════════════════════════════
    _section("invalid state is refused, not absorbed")

    r_pw = call(hdr_a, "POST", f"/league/{a_league}/week/15/open")
    _assert("a postseason week is refused", r_pw.status_code == 400,
            str(r_pw.status_code))
    _assert("the refusal names not_applicable_week",
            "not_applicable_week" in r_pw.text, r_pw.text[:160])
    _assert("week 0 is refused",
            call(hdr_a, "POST", f"/league/{a_league}/week/0/open").status_code == 400)
    _assert("week 18 is refused",
            call(hdr_a, "POST", f"/league/{a_league}/week/18/open").status_code == 400)

    _assert("a postseason week released nothing",
            balance_of(min_account(team, 15)) == 0)

    # ════ 7. WEEK CLOSE ═════════════════════════════════════════════════════
    _section("Week Close expires the unspent minimum, once")

    r_c = call(hdr_a, "POST", f"/league/{a_league}/week/4/close")
    _assert("Week Close succeeds for the league's commissioner",
            r_c.status_code == 200, f"{r_c.status_code} {r_c.text[:160]}")
    _assert("Week Close expired one weekly minimum per team",
            r_c.json().get("total_expired_cents") == WEEKLY_MIN * len(a_teams),
            str(r_c.json().get("total_expired_cents")))
    _assert("the week's min account is now empty",
            balance_of(min_account(team, 4)) == 0,
            str(balance_of(min_account(team, 4))))
    _assert("the unspent minimum landed in expired_min, not championship",
            balance_of(expired_min_account(team)) == WEEKLY_MIN,
            str(balance_of(expired_min_account(team))))
    _assert("trial balance is zero after Week Close", trial_balance() == 0)

    r_c2 = call(hdr_a, "POST", f"/league/{a_league}/week/4/close")
    _assert("a repeated Week Close still returns 200", r_c2.status_code == 200)
    _assert("a repeated Week Close reports already_closed",
            r_c2.json().get("already_closed") is True)
    _assert("a repeated Week Close expired nothing",
            r_c2.json().get("total_expired_cents") == 0,
            str(r_c2.json().get("total_expired_cents")))
    _assert("expired_min did not double",
            balance_of(expired_min_account(team)) == WEEKLY_MIN,
            str(balance_of(expired_min_account(team))))
    _assert("trial balance is zero at the end", trial_balance() == 0)


if __name__ == "__main__":
    print("\n=== WP1 week-lifecycle route suite (PostgreSQL) ===")
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