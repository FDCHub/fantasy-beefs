#!/usr/bin/env python3
"""
test_wp6a_skunk_week_close_pg.py — WP6A: weekly Skunk inside Week Close.

THE FOURTEEN ECONOMIC PROOFS the package requires, against real PostgreSQL and
through the production HTTP route — not against the engine directly, because the
engine was already certified and what WP6A adds is the CALLER.

  1  a non-final week cannot close                    §2
  2  a finalized week finds the right Skunk           §3
  3  the losing team and opponent are reported        §3
  4  exact final scores are preserved                 §3
  5  the point differential is exact, in decimals     §3
  6  the $10 effect posts correctly                   §4
  7  non-skunked teams are untouched                  §4
  8  SKUNK_ASSESSMENT persists exactly once           §5
  9  a repeated Week Close moves nothing twice        §5
 10  the season maximum stays governed                §6
 11  a refused close leaves NO partial state          §2
 12  league isolation holds                           §7
 13  trial balance is zero throughout                 every section
 14  season close no longer blocks on that week       §8

DECIMAL SCORING IS THE POINT. The fixture scores are the ruling's own worked
example — 132.47 to 101.83, a margin of 30.64 — because the margin is the
product's headline number and a suite that used round numbers would not notice a
float being truncated somewhere between the matchup row and the wire.

Requires TEST_DATABASE_URL -> a disposable, empty, _test-named database.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP6A Week Close suite cannot run:\n  {e}")
    sys.exit(2)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from datetime import datetime, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from auth.jwt_auth import hash_password  # noqa: E402
from auth.session import CSRF_COOKIE, CSRF_HEADER  # noqa: E402
from db.schema import (  # noqa: E402
    EconomyEvent, League, LeagueCommissioner, Matchup, Team, User, Wallet,
)
from economy.current_settle import DOOR_SEASON_ALLOCATION  # noqa: E402
from economy.economy_events import (  # noqa: E402
    EVENT_SKUNK_ASSESSMENT, min_reserve_account, receivable_account,
    skunk_account,
)
from economy.skunk import (  # noqa: E402
    DEFAULT_SKUNK_CONTRIBUTION_CENTS, DEFAULT_SKUNK_SEASON_MAXIMUM_CENTS,
)
from economy.weekly_minimum import release_week  # noqa: E402
from ledger.ledger import (  # noqa: E402
    balance_of, post as ledger_post, trial_balance,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


print("=" * 78)
print("WP6A — weekly Skunk integrated into Week Close")
print("=" * 78)

SEASON = 2026
PASSWORD = "wp6a-password"

#: The ruling's worked example. 132.47 − 101.83 = 30.64 exactly.
WINNER_SCORE, LOSER_SCORE, MARGIN = 132.47, 101.83, 30.64
#: The other matchup, a much narrower loss, so the worst is unambiguous.
NEAR_WIN, NEAR_LOSS = 110.50, 106.40

ctx: dict = {}


def _build(week_scores, *, name: str, playoff_start: int = 15,
           finalize: bool = True, matchups: bool = True):
    """One league with `week_scores` = {week: [(home, away, finalized?)]}."""
    with tdb.SessionLocal() as db:
        league = League(name=name, season=SEASON, provider="yahoo",
                        provider_league_key=f"461.l.{name.replace(' ', '')}",
                        provider_current_week=max(week_scores) if week_scores else 1,
                        playoff_start_week=playoff_start)
        db.add(league); db.flush()

        teams = []
        for i in range(4):
            t = Team(league_id=league.id, team_name=f"{name} T{i}",
                     owner=f"O{i}", email=f"{name.replace(' ', '')}{i}@wp6a.test")
            db.add(t); db.flush()
            db.add(Wallet(team_id=t.id, balance=0.0))
            teams.append(t)
        db.flush()

        comm = User(email=f"{name.replace(' ', '')}-comm@wp6a.test",
                    hashed_password=hash_password(PASSWORD),
                    team_id=teams[0].id, role="commissioner")
        db.add(comm); db.flush()
        db.add(LeagueCommissioner(league_id=league.id, user_id=comm.id,
                                  source="bootstrap"))

        for t in teams:
            ledger_post([(min_reserve_account(t.id), 140_000),
                         ("world", -140_000)],
                        door=DOOR_SEASON_ALLOCATION, session=db)
            db.flush()

        now = datetime.now(timezone.utc)
        if matchups:
            for wk, pairs in week_scores.items():
                for idx, (home_score, away_score, final) in enumerate(pairs):
                    a, b = teams[idx * 2], teams[idx * 2 + 1]
                    db.add(Matchup(league_id=league.id, week=wk,
                                   home_team_id=a.id, away_team_id=b.id,
                                   home_score=home_score, away_score=away_score,
                                   finalized_at=now if (final and finalize) else None))
        db.flush()

        for wk in week_scores:
            release_week(db, league_id=league.id, week=wk)
        db.commit()

        return {"league_id": league.id, "teams": [t.id for t in teams],
                "comm": comm.email}


def _client(email: str) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/auth/session", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def _close(client: TestClient, league_id: int, week: int):
    return client.post(f"/league/{league_id}/week/{week}/close",
                       headers={CSRF_HEADER: client.cookies.get(CSRF_COOKIE)})


# ══ §1 · a league that played one finalized week ════════════════════════════

tdb.reset()
A = _build({4: [(LOSER_SCORE, WINNER_SCORE, True), (NEAR_WIN, NEAR_LOSS, True)]},
           name="WP6A Alpha")
# LOSER is teams[0] (home, lower score); WINNER is teams[1].
LOSER, WINNER, T2, T3 = A["teams"]
comm_a = _client(A["comm"])

_section("§1 · the integration point is Week Close, and nothing else")

routes = {r.path for r in app.routes}
_assert("§1: no ordinary 'assess Skunk' route was added",
        not any("skunk" in p and p.endswith("/assess") for p in routes)
        and "/league/{league_id}/week/{week}/skunk/assess" not in routes,
        "Skunk is end-of-week reconciliation, not a commissioner chore")
_assert("§1: a READ route exists for the weekly result",
        "/league/{league_id}/week/{week}/skunk" in routes)
_assert("§1: the ledger balances before any close", trial_balance() == 0)


# ══ §2 · a non-final week cannot close, and leaves nothing behind ═══════════

_section("§2 · non-final week: refused, with NO partial close (proofs 1, 11)")

B = _build({4: [(LOSER_SCORE, WINNER_SCORE, False), (NEAR_WIN, NEAR_LOSS, True)]},
           name="WP6A Beta")
comm_b = _client(B["comm"])
b_loser = B["teams"][0]

before_expired = balance_of(f"expired_min:{b_loser}")
before_min = balance_of(f"min:{b_loser}:4")
before_tb = trial_balance()

refused = _close(comm_b, B["league_id"], 4)

_assert("§2: Week Close is REFUSED while a matchup is not final",
        refused.status_code == 409, f"{refused.status_code} {refused.text[:120]}")
_assert("§2: and the governed reason code is RESULTS_NOT_READY",
        refused.json().get("detail", {}).get("reason_code") == "RESULTS_NOT_READY",
        str(refused.json())[:150])

with tdb.SessionLocal() as db:
    b_events = (db.query(EconomyEvent)
                .filter(EconomyEvent.league_id == B["league_id"],
                        EconomyEvent.event_type == EVENT_SKUNK_ASSESSMENT)
                .count())

_assert("§2: no Skunk assessment was recorded", b_events == 0, str(b_events))
_assert("§2: NO weekly minimum was expired — the week is not partly closed",
        balance_of(f"expired_min:{b_loser}") == before_expired
        and balance_of(f"min:{b_loser}:4") == before_min,
        f"expired {before_expired}->{balance_of(f'expired_min:{b_loser}')}, "
        f"min {before_min}->{balance_of(f'min:{b_loser}:4')}")
_assert("§2: no receivable was opened against anyone",
        all(balance_of(receivable_account(t)) == 0 for t in B["teams"]))
_assert("§2: the trial balance is untouched",
        trial_balance() == before_tb == 0, str(trial_balance()))


# ══ §3 · the finalized week finds the right Skunk ═══════════════════════════

_section("§3 · selection, teams, scores and differential (proofs 2, 3, 4, 5)")

closed = _close(comm_a, A["league_id"], 4)
_assert("§3: Week Close succeeds on the finalized week",
        closed.status_code == 200, f"{closed.status_code} {closed.text[:140]}")

body = closed.json()
skunk = body.get("skunk")
_assert("§3: the close response carries the week's Skunk outcome",
        skunk is not None and skunk.get("assessed") is True, str(skunk)[:140])
_assert("§3: classified ASSESSED, not NO_LOSER",
        skunk.get("classification") == "ASSESSED", str(skunk.get("classification")))
_assert("§3: exactly ONE Skunk outcome for the week",
        len(skunk.get("entries", [])) == 1, str(len(skunk.get("entries", []))))

entry = skunk["entries"][0]
_assert("§3 (proof 2/3): the SKUNKED team is the worst loss, not the near one",
        entry["team_id"] == LOSER, f"team {entry['team_id']}, expected {LOSER}")
_assert("§3 (proof 3): the OPPONENT is the team that beat them",
        entry["opponent_team_id"] == WINNER,
        f"opponent {entry['opponent_team_id']}, expected {WINNER}")
_assert("§3: both teams are named, not just numbered",
        entry["team_name"] and entry["opponent_team_name"],
        f"{entry['team_name']} vs {entry['opponent_team_name']}")
_assert("§3 (proof 4): the skunked team's exact final score is preserved",
        entry["score"] == LOSER_SCORE, f"{entry['score']} vs {LOSER_SCORE}")
_assert("§3 (proof 4): the opponent's exact final score is preserved",
        entry["opponent_score"] == WINNER_SCORE,
        f"{entry['opponent_score']} vs {WINNER_SCORE}")
_assert("§3 (proof 5): the point differential is exact to the cent of a point",
        round(entry["margin"], 2) == MARGIN,
        f"{entry['margin']} vs {MARGIN}")
_assert("§3 (proof 5): and it equals the two scores it is printed beside",
        round(entry["opponent_score"] - entry["score"], 2) == round(entry["margin"], 2),
        f"{entry['opponent_score']} - {entry['score']} = {entry['margin']}")
_assert("§3: the fractional part survived — this is not integer scoring",
        entry["margin"] % 1 != 0, str(entry["margin"]))


# ══ §4 · the money ══════════════════════════════════════════════════════════

_section("§4 · the $10 effect, and everyone else untouched (proofs 6, 7)")

_assert("§4 (proof 6): the reported amount is the governed $10",
        skunk["amount_cents"] == DEFAULT_SKUNK_CONTRIBUTION_CENTS == 1000,
        str(skunk["amount_cents"]))
_assert("§4 (proof 6): the skunked GM's share is the whole $10",
        entry["cents"] == 1000, str(entry["cents"]))
_assert("§4 (proof 6): the obligation is on the skunked GM's receivable",
        balance_of(receivable_account(LOSER)) == -1000,
        str(balance_of(receivable_account(LOSER))))
_assert("§4 (proof 6): and the league's Skunk pot received exactly $10",
        balance_of(skunk_account(A["league_id"])) == 1000,
        str(balance_of(skunk_account(A["league_id"]))))

_assert("§4 (proof 7): the WINNER carries no Skunk obligation",
        balance_of(receivable_account(WINNER)) == 0)
_assert("§4 (proof 7): nor do the two GMs in the other matchup",
        balance_of(receivable_account(T2)) == 0
        and balance_of(receivable_account(T3)) == 0)
# SKUNK IS LEDGER-ONLY — it never touches a wallet or the weekly minimum.
_assert("§4 (proof 7): no wallet was debited by the Skunk",
        all(balance_of(f"wallet:{t}") == 0 for t in A["teams"]))
_assert("§4 (proof 13): trial balance is zero after the assessment",
        trial_balance() == 0, str(trial_balance()))

# THE CLOSE STILL DID ITS ORIGINAL JOB. Skunk was added to Week Close, not
# substituted for it.
_assert("§4: the weekly minimum was still expired by the same close",
        body["total_expired_cents"] > 0, str(body["total_expired_cents"]))


# ══ §5 · exactly once, and a repeat moves nothing ═══════════════════════════

_section("§5 · exactly-once and retry safety (proofs 8, 9)")

with tdb.SessionLocal() as db:
    count_one = (db.query(EconomyEvent)
                 .filter(EconomyEvent.league_id == A["league_id"],
                         EconomyEvent.event_type == EVENT_SKUNK_ASSESSMENT)
                 .count())
_assert("§5 (proof 8): exactly ONE assessment event exists",
        count_one == 1, str(count_one))

receivable_before = balance_of(receivable_account(LOSER))
pot_before = balance_of(skunk_account(A["league_id"]))

again = _close(comm_a, A["league_id"], 4)
_assert("§5: a repeated Week Close still succeeds",
        again.status_code == 200, f"{again.status_code} {again.text[:120]}")
_assert("§5: and reports the week already closed",
        again.json().get("already_closed") is True)
_assert("§5: the repeat reports the Skunk as replayed",
        again.json().get("skunk", {}).get("replayed") is True,
        str(again.json().get("skunk"))[:140])
_assert("§5: and replays the ORIGINAL outcome, not a blank one",
        again.json()["skunk"]["entries"][0]["team_id"] == LOSER
        and round(again.json()["skunk"]["entries"][0]["margin"], 2) == MARGIN)

with tdb.SessionLocal() as db:
    count_two = (db.query(EconomyEvent)
                 .filter(EconomyEvent.league_id == A["league_id"],
                         EconomyEvent.event_type == EVENT_SKUNK_ASSESSMENT)
                 .count())
_assert("§5 (proof 8): still exactly ONE assessment event",
        count_two == 1, str(count_two))
_assert("§5 (proof 9): the receivable did not double",
        balance_of(receivable_account(LOSER)) == receivable_before == -1000,
        str(balance_of(receivable_account(LOSER))))
_assert("§5 (proof 9): the pot did not double",
        balance_of(skunk_account(A["league_id"])) == pot_before == 1000,
        str(balance_of(skunk_account(A["league_id"]))))
_assert("§5 (proof 13): trial balance still zero", trial_balance() == 0)


# ══ §6 · the season maximum stays governed ══════════════════════════════════

_section("§6 · the season cap is unchanged (proof 10)")

_assert("§6: the governed weekly contribution is still $10",
        DEFAULT_SKUNK_CONTRIBUTION_CENTS == 1000)
_assert("§6: the governed season maximum is still $140",
        DEFAULT_SKUNK_SEASON_MAXIMUM_CENTS == 14000)
_assert("§6: and $140 is exactly fourteen governed weeks",
        DEFAULT_SKUNK_SEASON_MAXIMUM_CENTS
        == DEFAULT_SKUNK_CONTRIBUTION_CENTS * 14)

# FOURTEEN CLOSES, ONE LEAGUE. Every regular-season week assessed through the
# ROUTE, so the cap claim is about what the product can actually accumulate.
C = _build({wk: [(LOSER_SCORE, WINNER_SCORE, True), (NEAR_WIN, NEAR_LOSS, True)]
            for wk in range(1, 15)}, name="WP6A Cap")
comm_c = _client(C["comm"])
for wk in range(1, 15):
    r = _close(comm_c, C["league_id"], wk)
    assert r.status_code == 200, f"week {wk}: {r.status_code} {r.text[:160]}"

_assert("§6 (proof 10): fourteen closes accumulate exactly the $140 maximum",
        balance_of(skunk_account(C["league_id"]))
        == DEFAULT_SKUNK_SEASON_MAXIMUM_CENTS == 14000,
        str(balance_of(skunk_account(C["league_id"]))))
_assert("§6: and the same GM's obligation is $140, not more",
        balance_of(receivable_account(C["teams"][0])) == -14000,
        str(balance_of(receivable_account(C["teams"][0]))))
# A POSTSEASON WEEK ADDS NOTHING, which is what keeps fourteen weeks the ceiling.
post = _close(comm_c, C["league_id"], 15)
_assert("§6: a postseason Week Close succeeds and assesses no Skunk",
        post.status_code == 200 and post.json().get("skunk") is None,
        f"{post.status_code}, skunk={post.json().get('skunk')}")
_assert("§6: so the pot is still exactly $140 after a postseason close",
        balance_of(skunk_account(C["league_id"])) == 14000,
        str(balance_of(skunk_account(C["league_id"]))))
_assert("§6 (proof 13): trial balance zero across fourteen closes",
        trial_balance() == 0, str(trial_balance()))


# ══ §7 · league isolation ═══════════════════════════════════════════════════

_section("§7 · league isolation (proof 12)")

_assert("§7: league A's pot holds only its own week",
        balance_of(skunk_account(A["league_id"])) == 1000,
        str(balance_of(skunk_account(A["league_id"]))))
_assert("§7: league B — whose close was refused — has an empty pot",
        balance_of(skunk_account(B["league_id"])) == 0,
        str(balance_of(skunk_account(B["league_id"]))))
_assert("§7: and B's GMs carry no obligation from A's or C's assessments",
        all(balance_of(receivable_account(t)) == 0 for t in B["teams"]))

with tdb.SessionLocal() as db:
    a_events = (db.query(EconomyEvent)
                .filter(EconomyEvent.league_id == A["league_id"],
                        EconomyEvent.event_type == EVENT_SKUNK_ASSESSMENT).count())
    c_events = (db.query(EconomyEvent)
                .filter(EconomyEvent.league_id == C["league_id"],
                        EconomyEvent.event_type == EVENT_SKUNK_ASSESSMENT).count())
_assert("§7: each league's events are its own",
        a_events == 1 and c_events == 14, f"A={a_events}, C={c_events}")

# A COMMISSIONER OF ANOTHER LEAGUE CANNOT CLOSE THIS ONE.
foreign = _close(comm_b, A["league_id"], 4)
_assert("§7: a foreign commissioner cannot close league A's week",
        foreign.status_code == 403, str(foreign.status_code))


# ══ §8 · the season-close blocker is cleared ════════════════════════════════

_section("§8 · season close no longer blocks on that week (proof 14)")

with tdb.SessionLocal() as db:
    from betting.pool_season_boundary import season_final_week
    from economy.season_close_orchestrator import (
        SeasonClosePreconditionError, verify_preconditions,
    )
    lg = db.query(League).filter(League.id == A["league_id"]).one()
    step = None
    try:
        verify_preconditions(db, league_id=A["league_id"],
                             final_week=season_final_week(lg))
    except SeasonClosePreconditionError as exc:
        step = exc.step
    db.rollback()

_assert("§8 (proof 14): season close no longer refuses for skunk_assessed",
        step != "skunk_assessed",
        f"first unmet step is now {step!r}" if step else "no unmet step at all")

# THE READ ROUTE SERVES THE SAME RESULT, to any member.
gm_client = TestClient(app, raise_server_exceptions=False)
with tdb.SessionLocal() as db:
    gm_email = "wp6aalpha-gm@wp6a.test"
    gm_team = db.query(Team).filter(Team.id == T2).one()
    db.add(User(email=gm_email, hashed_password=hash_password(PASSWORD),
                team_id=gm_team.id, role="gm"))
    db.commit()
r = gm_client.post("/auth/session", json={"email": gm_email, "password": PASSWORD})
assert r.status_code == 200, r.text

read = gm_client.get(f"/league/{A['league_id']}/week/4/skunk")
_assert("§8: an ordinary GM may READ the week's Skunk result",
        read.status_code == 200, f"{read.status_code} {read.text[:120]}")
_assert("§8: and it is the same outcome the close reported",
        read.json()["entries"][0]["team_id"] == LOSER
        and round(read.json()["entries"][0]["margin"], 2) == MARGIN
        and read.json()["amount_cents"] == 1000,
        str(read.json())[:160])

# BUT A GM CANNOT CAUSE ONE.
gm_close = gm_client.post(f"/league/{A['league_id']}/week/4/close",
                          headers={CSRF_HEADER: gm_client.cookies.get(CSRF_COOKIE)})
_assert("§8: an ordinary GM cannot run Week Close",
        gm_close.status_code == 403, str(gm_close.status_code))

# AN UNASSESSED WEEK READS AS UNASSESSED, not as "nobody was skunked".
unassessed = gm_client.get(f"/league/{A['league_id']}/week/5/skunk")
_assert("§8: an unclosed week reports assessed=false, not an empty result",
        unassessed.status_code == 200
        and unassessed.json()["assessed"] is False
        and unassessed.json()["entries"] == [],
        str(unassessed.json())[:140])

# THE LIFECYCLE READ MODEL AGREES with the event, for the commissioner.
lifecycle = comm_a.get(f"/league/{A['league_id']}/lifecycle")
_assert("§8: the lifecycle read reports the week's Skunk as assessed",
        lifecycle.status_code == 200
        and lifecycle.json()["week"]["skunk_required"] is True
        and lifecycle.json()["week"]["skunk_assessed"] is True,
        str(lifecycle.json().get("week"))[:160])

_assert("§8 (proof 13): trial balance zero at the end", trial_balance() == 0)

tdb.teardown()

print("\n" + "=" * 78)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("WP6A WEEK CLOSE SKUNK — all assertions PASSED")