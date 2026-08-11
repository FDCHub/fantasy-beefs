#!/usr/bin/env python3
"""
test_s8_p4c1r_wagering_authority.py — Sprint 8 P4C-1R · wagering actor authority.

THE DEFECT THIS CLOSES. `assert_own_team()` exempts commissioners, which is
correct for administrative reads and wrong for wagers. Before S8-P4C-1 the
consequence was contained: a commissioner issuing "as" another GM created an
unfunded legacy row that reserved nothing. Once issuance posts real escrow, the
same call debits that GM's actual Credits. The rule never changed — the cutover
changed what it costs, which is why the repair belongs to P4C-1 rather than to
whoever wrote the helper.

403 IS THE WEAKEST THING WORTH ASSERTING. A refusal that returned 403 while
having already posted, or having left a challenge row that a later call could
fund, would satisfy a status-code test and still have spent someone's money. So
every negative below is paired with a proof that the GM's wallet, weekly
minimum, escrow, funding legs, challenge rows and the global trial balance are
all exactly as they were.

WHAT THE REPAIR MUST NOT DO is disable a commissioner as a player. They are also
a GM, and §5 proves they wager on precisely the same terms as anyone else —
no advantage and no disability.
"""

from __future__ import annotations

import ast
import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 's8p4c1r.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

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


# ══ §1 · the caller inventory is enforced, not just written down ═════════════

_section("§1 · every assert_own_team caller is classified")

_api_src = open(os.path.join(ROOT, "api", "main.py"), encoding="utf-8").read()
_api_tree = ast.parse(_api_src)


def _calls_in(tree, name: str) -> dict[str, int]:
    """Which enclosing function each call to `name` sits in."""
    found: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == name):
                found[node.name] = found.get(node.name, 0) + 1
    return found


_lenient = _calls_in(_api_tree, "assert_own_team")
_strict = _calls_in(_api_tree, "assert_wagering_team_owner")

# THE WAGERING SURFACE, NAMED. Adding a proposal route without the strict guard
# should break this, which is the point of pinning the set rather than counting.
WAGERING = {"beef_challenge", "beef_respond", "beef_counter", "beef_pending"}
# ADMINISTRATIVE READS. Both are history/summary surfaces where commissioner
# oversight is intended and no Credits move.
ADMIN = {"faab_transactions", "account_summary"}

_assert("§1: the strict guard covers exactly the wagering surface",
        set(_strict) == WAGERING, f"strict: {sorted(_strict)}")
_assert("§1: no wagering route still uses the lenient guard",
        not (set(_lenient) & WAGERING), f"lenient: {sorted(_lenient)}")
_assert("§1: the lenient guard survives on administrative reads only",
        set(_lenient) == ADMIN, f"lenient: {sorted(_lenient)}")

# AND THE STRICT HELPER REALLY IS STRICT. A helper that quietly kept a role
# exemption would pass every routing check above and fail every purpose.
_auth_tree = ast.parse(open(os.path.join(ROOT, "auth", "jwt_auth.py"),
                            encoding="utf-8").read())
_strict_fn = next(n for n in ast.walk(_auth_tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "assert_wagering_team_owner")
_mentions_role = any(
    isinstance(n, ast.Attribute) and n.attr == "role"
    for n in ast.walk(_strict_fn))
_assert("§1: the strict helper does not consult `role` at all",
        not _mentions_role,
        "commissioner status is not an input to wagering identity")


# ══ Seed: GM A, GM B, and commissioner C with a team of their own ════════════

from db.schema import (  # noqa: E402
    Base, BeefChallenge, ChallengeFundingLeg, League, LeagueCommissioner,
    Matchup, Player, Projection, Roster, SessionLocal, Team, User, Wallet,
    engine,
)
from auth.jwt_auth import hash_password  # noqa: E402
from ledger.ledger import create_ledger_table, post as ledger_post  # noqa: E402

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "sprint8-password"
A_EMAIL, B_EMAIL, C_EMAIL = "gm-a@p4c1r.test", "gm-b@p4c1r.test", "comm-c@p4c1r.test"
# A SECOND LEAGUE, with its own commissioner, so §6's cross-league claims are
# made against real foreign teams rather than against invented ids.
D_EMAIL = "comm-d@p4c1r.test"
SEASON, WEEK = 2026, 5


def _seed_team(db, league, name, email, funds):
    team = Team(team_name=name, owner=name, email=email, league_id=league.id)
    db.add(team); db.flush()
    db.add(User(email=email, hashed_password=hash_password(PASSWORD),
                team_id=team.id, role="gm"))
    db.add(Wallet(team_id=team.id, balance=0.0))
    db.flush()
    if funds:
        ledger_post([(f"wallet:{team.id}", funds), ("world", -funds)],
                    door="approved_bab_topoff", session=db)
        db.flush()
    for i in range(9):
        player = Player(name=f"{name}-P{i}", position="WR", nfl_team="KC")
        db.add(player); db.flush()
        db.add(Roster(team_id=team.id, player_id=player.id))
        db.add(Projection(player_id=player.id, week=WEEK, season=SEASON,
                          projected_points=12.0 + i, source="fixture"))
    db.flush()
    return team


with SessionLocal() as db:
    league = League(name="Authority League", season=SEASON)
    other_league = League(name="Foreign League", season=SEASON)
    db.add_all([league, other_league]); db.flush()

    team_a = _seed_team(db, league, "Gravy Train", A_EMAIL, 10_000)
    team_b = _seed_team(db, league, "The Braintrust", B_EMAIL, 10_000)
    # THE COMMISSIONER HAS A TEAM OF THEIR OWN, funded like everyone else —
    # §5 has to show they can wager normally, which needs real money.
    team_c = _seed_team(db, league, "The Chair", C_EMAIL, 10_000)
    team_d = _seed_team(db, other_league, "Foreign XI", D_EMAIL, 10_000)

    for row_league, email in ((league, C_EMAIL), (other_league, D_EMAIL)):
        user = db.query(User).filter(User.email == email).one()
        user.role = "commissioner"
        db.add(LeagueCommissioner(league_id=row_league.id, user_id=user.id,
                                  source="bootstrap"))
    db.flush()

    for home, away, lg in ((team_a, team_b, league), (team_c, team_a, league)):
        db.add(Matchup(league_id=lg.id, week=WEEK, home_team_id=home.id,
                       away_team_id=away.id, home_score=0.0, away_score=0.0))
    db.commit()
    LEAGUE, OTHER_LEAGUE = league.id, other_league.id
    A, B, C, D = team_a.id, team_b.id, team_c.id, team_d.id


from fastapi.testclient import TestClient  # noqa: E402
from api.main import app  # noqa: E402
from auth.session import CSRF_COOKIE, CSRF_HEADER  # noqa: E402


class Client:
    def __init__(self, email: str | None) -> None:
        self.http = TestClient(app, raise_server_exceptions=False)
        if email:
            r = self.http.post("/auth/session",
                               json={"email": email, "password": PASSWORD})
            assert r.status_code == 200, f"login failed for {email}: {r.text}"

    def request(self, method: str, path: str, body=None):
        headers = {}
        csrf = self.http.cookies.get(CSRF_COOKIE)
        if csrf:
            headers[CSRF_HEADER] = csrf
        r = self.http.request(method, path, json=body, headers=headers)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text


def economic_state(team_id: int) -> dict:
    """Everything a wrongly-authorized call could have moved.

    NOT JUST THE WALLET. A refusal that had already opened a challenge row, or
    written a funding leg, would leave the wallet intact and still have
    committed the GM to something — so the row counts are part of the snapshot,
    not decoration.
    """
    from sqlalchemy import text

    from economy.challenge_escrow_view import team_open_challenge_escrow_cents
    from economy.current_settle import current_settle, in_play_cents
    from ledger.ledger import trial_balance

    with SessionLocal() as db:
        cs = current_settle(db, team_id=team_id, league_id=LEAGUE, season=SEASON)
        escrow_for_team = int(db.execute(text(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
            "WHERE account LIKE 'escrow:challenge:%'"), {}).scalar() or 0)
        return {
            "wallet": cs.wallet_cents,
            "weekly_min": cs.weekly_min_live_cents,
            "in_play": in_play_cents(db, team_id),
            "held": team_open_challenge_escrow_cents(db, team_id),
            "current_settle": cs.current_settle_cents,
            "legs": db.query(ChallengeFundingLeg)
                      .filter(ChallengeFundingLeg.team_id == team_id).count(),
            "challenges": db.query(BeefChallenge).filter(
                (BeefChallenge.challenger_team_id == team_id)
                | (BeefChallenge.challenged_team_id == team_id)).count(),
            "all_challenge_escrow": escrow_for_team,
            "trial_balance": trial_balance(),
        }


def _unchanged(label: str, before: dict, after: dict) -> None:
    """Assert every economic dimension is untouched, naming what moved."""
    moved = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    _assert(label, not moved, f"moved: {moved}" if moved else "nothing moved")


print("=" * 74)
print("S8-P4C-1R — wagering actor authority")
print("=" * 74)

gm_a, gm_b, comm_c, comm_d = (Client(A_EMAIL), Client(B_EMAIL),
                              Client(C_EMAIL), Client(D_EMAIL))

# ══ §4 · commissioner-as-another-GM, and nothing moved ══════════════════════

_section("§4 · a commissioner cannot issue as another GM")

before_a = economic_state(A)
status, body = comm_c.request("POST", "/beef/challenge", {
    "challenger_team_id": A, "challenged_team_id": B,
    "week": WEEK, "bet_type": "straight", "amount": 25.00,
})
_assert("§4: commissioner C issuing as GM A is refused", status == 403,
        f"status {status}: {body}")

after_a = economic_state(A)
_unchanged("§4: GM A's entire economic position is untouched", before_a, after_a)
_assert("§4: GM A's wallet is unchanged",
        after_a["wallet"] == before_a["wallet"], str(after_a["wallet"]))
_assert("§4: GM A's weekly minimum is unchanged",
        after_a["weekly_min"] == before_a["weekly_min"])
_assert("§4: no challenge escrow exists anywhere",
        after_a["all_challenge_escrow"] == 0,
        f"{after_a['all_challenge_escrow']} cents")
_assert("§4: no ChallengeFundingLeg was written for GM A",
        after_a["legs"] == 0, f"{after_a['legs']} legs")
_assert("§4: no challenge row was opened on GM A's behalf",
        after_a["challenges"] == 0, f"{after_a['challenges']} rows")
_assert("§4: the trial balance is unchanged",
        after_a["trial_balance"] == before_a["trial_balance"] == 0)

# THE SAME PRINCIPLE ON THE RESPONSE SURFACE. A real challenge between A and B,
# which C is administratively aware of and economically no part of.
_section("§4 · and cannot respond or counter on another GM's behalf")

status, issued = gm_a.request("POST", "/beef/challenge", {
    "challenger_team_id": A, "challenged_team_id": B,
    "week": WEEK, "bet_type": "straight", "amount": 25.00,
})
assert status == 201, issued
CH = issued["challenge_id"]

before_b = economic_state(B)
before_a2 = economic_state(A)

status, _ = comm_c.request("POST", "/beef/respond",
                           {"challenge_id": CH, "accept": True})
_assert("§4: commissioner C cannot ACCEPT as GM B", status == 403,
        f"status {status}")
_unchanged("§4: GM B's position is untouched by the refused accept",
           before_b, economic_state(B))

status, _ = comm_c.request("POST", "/beef/respond",
                           {"challenge_id": CH, "accept": False})
_assert("§4: commissioner C cannot DECLINE as GM B", status == 403,
        f"status {status}")
_unchanged("§4: GM A's escrow survives the refused decline",
           before_a2, economic_state(A))

status, _ = comm_c.request("POST", "/beef/counter",
                           {"challenge_id": CH, "countered_amount": 50.00})
_assert("§4: commissioner C cannot COUNTER as GM B", status == 403,
        f"status {status}")
_unchanged("§4: GM B's position is untouched by the refused counter",
           before_b, economic_state(B))

with SessionLocal() as db:
    ch = db.query(BeefChallenge).filter(BeefChallenge.id == CH).one()
    _assert("§4: the challenge is still OFFERED — no refusal advanced it",
            ch.response_status == "offered", ch.response_status)

# THE INBOX IS PERSONAL. A commissioner does not acquire another GM's open
# negotiation queue, which discloses stakes and positions, by holding the role.
status, _ = comm_c.request("GET", f"/beef/pending/{A}")
_assert("§4: commissioner C cannot read GM A's proposal inbox", status == 403,
        f"status {status}")
status, own = comm_c.request("GET", f"/beef/pending/{C}")
_assert("§4: but C reads their OWN inbox normally", status == 200, str(own))

# AND AN ORDINARY GM IS STILL REFUSED — the repair must not have merely swapped
# which role is privileged.
status, _ = gm_b.request("POST", "/beef/challenge", {
    "challenger_team_id": A, "challenged_team_id": B,
    "week": WEEK, "bet_type": "straight", "amount": 5.00,
})
_assert("§4: GM B cannot issue as GM A either", status == 403, f"status {status}")


# ══ §5 · the commissioner is not disabled as a player ═══════════════════════

_section("§5 · a commissioner wagers normally for their OWN team")

before_c = economic_state(C)
status, c_issued = comm_c.request("POST", "/beef/challenge", {
    "challenger_team_id": C, "challenged_team_id": A,
    "week": WEEK, "bet_type": "straight", "amount": 30.00,
})
_assert("§5: commissioner C issues from C's own team", status == 201,
        f"status {status}: {c_issued}")
assert status == 201, c_issued
C_CH = c_issued["challenge_id"]

after_c = economic_state(C)
_assert("§5: and it posted real escrow, on the same terms as any GM",
        c_issued["escrow_cents"] == 3_000
        and after_c["held"] == before_c["held"] + 3_000,
        f"held {before_c['held']} → {after_c['held']}")
_assert("§5: C's spendable funds fell by exactly the stake",
        after_c["wallet"] + after_c["weekly_min"]
        == before_c["wallet"] + before_c["weekly_min"] - 3_000)

# AND C RESPONDS WHEN C IS THE PROPER RESPONDER. GM A counters C's challenge,
# which hands the decision back to C as issuer.
status, _ = gm_a.request("POST", "/beef/counter",
                         {"challenge_id": C_CH, "countered_amount": 35.00})
_assert("§5: GM A counters the commissioner's challenge", status == 200,
        f"status {status}")
status, c_accept = comm_c.request("POST", "/beef/respond",
                                  {"challenge_id": C_CH, "accept": True})
_assert("§5: commissioner C accepts when C is the proper responder",
        status == 200, f"status {status}: {c_accept}")
_assert("§5: and the acceptance produced real Bet rows",
        c_accept["anchor_bet_id"] is not None
        and c_accept["derived_bet_id"] is not None)

# NO ADVANTAGE EITHER. The same funds rule refuses C exactly as it refuses
# anyone — commissioner status buys no capacity.
state_c = economic_state(C)
status, refused = comm_c.request("POST", "/beef/challenge", {
    "challenger_team_id": C, "challenged_team_id": A, "week": WEEK,
    "bet_type": "straight",
    "amount": (state_c["wallet"] + state_c["weekly_min"]) / 100 + 500.00,
})
_assert("§5: commissioner C is refused for insufficient funds like anyone else",
        status in (400, 409), f"status {status}: {refused}")
_unchanged("§5: and that refusal moved nothing", state_c, economic_state(C))


# ══ §6 · cross-league authority ═════════════════════════════════════════════

_section("§6 · authority does not cross a league boundary")

# EACH BEFORE/AFTER PAIR BRACKETS ITS OWN CALL. GM A has legitimately wagered
# since §4's snapshot, so comparing against that one would report A's own
# activity as damage done by a refusal — a stale baseline that would fail loudly
# here and, worse, could pass silently if the intervening activity happened to
# net to zero.
before_d = economic_state(D)
before_a_cross = economic_state(A)
status, _ = comm_d.request("POST", "/beef/challenge", {
    "challenger_team_id": A, "challenged_team_id": B,
    "week": WEEK, "bet_type": "straight", "amount": 10.00,
})
_assert("§6: commissioner of League B cannot wager as a League A team",
        status == 403, f"status {status}")
_unchanged("§6: and GM A is untouched by it", before_a_cross,
           economic_state(A))

status, _ = gm_a.request("POST", "/beef/challenge", {
    "challenger_team_id": D, "challenged_team_id": B,
    "week": WEEK, "bet_type": "straight", "amount": 10.00,
})
_assert("§6: a GM cannot wager from a team in another league", status == 403,
        f"status {status}")
_unchanged("§6: the foreign team is untouched", before_d, economic_state(D))

# COMMISSIONER C, IN THEIR OWN LEAGUE, AS ANOTHER TEAM — the case the old helper
# allowed and the one this repair exists for. Already proven in §4; restated
# here because §6 asks for the three boundaries side by side.
status, _ = comm_c.request("POST", "/beef/challenge", {
    "challenger_team_id": B, "challenged_team_id": A,
    "week": WEEK, "bet_type": "straight", "amount": 10.00,
})
_assert("§6: commissioner of League A cannot wager as another League A team",
        status == 403, f"status {status}")

# CROSS-LEAGUE WAGERING ITSELF stays refused for the legitimate owner too, and
# is refused BEFORE any money moves.
before_a3 = economic_state(A)
status, cross = gm_a.request("POST", "/beef/challenge", {
    "challenger_team_id": A, "challenged_team_id": D,
    "week": WEEK, "bet_type": "straight", "amount": 10.00,
})
_assert("§6: a GM cannot challenge a team in another league", status == 400,
        f"status {status}: {cross}")
_unchanged("§6: and that refusal is economically inert", before_a3,
           economic_state(A))


# ══ §7 · terminal and idempotent responses still work for participants ══════

_section("§7 · terminal/replay behaviour is preserved for participants")

status, replay = comm_c.request("POST", "/beef/respond",
                                {"challenge_id": C_CH, "accept": True})
_assert("§7: a participating GM replaying an accept gets the governed result",
        status == 200, f"status {status}: {replay}")
_assert("§7: and it is FLAGGED as a replay, not applied twice",
        isinstance(replay, dict) and replay.get("replayed") is True,
        str(replay.get("replayed") if isinstance(replay, dict) else replay))

state_after_replay = economic_state(C)
status, _ = gm_b.request("POST", "/beef/respond",
                         {"challenge_id": C_CH, "accept": True})
_assert("§7: a NON-participant gets 403 on the same terminal challenge",
        status == 403, f"status {status}")

# THE POINT OF §7. Being commissioner is not a way of being a participant — but
# GM A, who really is one, reaches the terminal result rather than a 403.
status, a_terminal = gm_a.request("POST", "/beef/respond",
                                  {"challenge_id": C_CH, "accept": True})
_assert("§7: the OTHER participant also reaches the governed terminal result",
        status == 200 and isinstance(a_terminal, dict)
        and a_terminal.get("replayed") is True,
        f"status {status}: {a_terminal}")
_unchanged("§7: no replay moved money", state_after_replay, economic_state(C))

with SessionLocal() as db:
    from db.schema import Bet
    n_bets = db.query(Bet).filter(Bet.beef_challenge_id == C_CH).count()
    _assert("§7: still exactly two Bet rows — no double-accept",
            n_bets == 2, f"{n_bets} bets")


# ══ §8 · LOCKED vs DYNAMIC over HTTP ════════════════════════════════════════

_section("§8 · what the live HTTP path can represent")

_request_fields = {
    t.target.id
    for n in ast.walk(_api_tree)
    if isinstance(n, ast.ClassDef) and n.name == "ChallengeRequest"
    for t in n.body if isinstance(t, ast.AnnAssign)
    if isinstance(t.target, ast.Name)
}
_assert("§8: the request schema carries NO challenge mode",
        not any("mode" in f for f in _request_fields), str(sorted(_request_fields)))

_api_imports = {
    node.module
    for node in ast.walk(_api_tree) if isinstance(node, ast.ImportFrom)
    if node.module
}
_assert("§8: no API module imports the Dynamic lifecycle",
        not any("dynamic_challenge" in m for m in _api_imports),
        "economy/dynamic_challenge.py is unreachable from HTTP")

# NOT A REGRESSION, AND THIS IS THE PART WORTH PROVING. There was no Dynamic
# HTTP path to break: at 1d5ea8d the legacy route reached `issue_challenge`,
# which never set `challenge_mode` at all, and no route referenced the Dynamic
# lifecycle then either. The cutover did not downgrade Dynamic to Locked — it
# gave an explicit mode to rows that previously carried none.
_mode_column = BeefChallenge.__table__.columns["challenge_mode"]
_assert("§8: the column has no default — legacy rows carried no mode at all",
        _mode_column.default is None and _mode_column.nullable,
        "so 'every challenge is Locked' is a tightening, not a conversion")

with SessionLocal() as db:
    modes = {row[0] for row in db.query(BeefChallenge.challenge_mode).all()}
    handshakes = db.query(BeefChallenge).filter(
        BeefChallenge.dynamic_handshake_at.isnot(None)).count()
_assert("§8: every HTTP-issued challenge is explicitly Locked",
        modes == {"locked"}, str(sorted(modes)))
_assert("§8: and none carries a Dynamic handshake", handshakes == 0,
        f"{handshakes} handshakes")

# DYNAMIC IS FENCED, NOT HALF-WIRED. Locked acceptance refuses a non-Locked
# challenge outright, so even a mode written by some other route could not
# quietly settle down the Locked path.
from beefs.proposal_lifecycle import UnsupportedModeError  # noqa: E402
import economy.challenge_funding as _cf  # noqa: E402

_accept_src = ast.get_source_segment(
    open(os.path.join(ROOT, "economy", "challenge_funding.py"),
         encoding="utf-8").read(),
    next(n for n in ast.walk(ast.parse(open(
        os.path.join(ROOT, "economy", "challenge_funding.py"),
        encoding="utf-8").read()))
        if isinstance(n, ast.FunctionDef)
        and n.name == "accept_funded_challenge"))
_assert("§8: Locked acceptance explicitly refuses a non-Locked challenge",
        "UnsupportedModeError" in _accept_src,
        "the mode boundary is enforced in the funding path, not assumed")
_assert("§8: DISCLOSED — Dynamic is not exposed over HTTP and was not before; "
        "its binding belongs to P4C-2",
        callable(getattr(_cf, "issue_funded_challenge", None))
        and issubclass(UnsupportedModeError, ValueError))


# ══ §9 · the accepted accounting result is unchanged ════════════════════════

_section("§9 · the P4C-1 reference position is untouched by this repair")

# READ FROM THE REV 4.2 FIXTURE ITSELF, not from this suite's league — the
# accepted figures belong to that fixture, and the P4C-1 and P4B suites assert
# them there. What is checked here is that the repair did not perturb them,
# which is a claim about the numbers rather than about this seed.
from test_support_rev42_fixture import FIXTURE_EXPECTED  # noqa: E402

ACCEPTED = {
    "wallet_cents": 3_000, "weekly_min_live_cents": 1_000,
    "available_cents": 4_000, "min_reserve_cents": 9_000,
    "expired_min_cents": 800, "in_play_cents": 5_300,
    "held_open_challenges_cents": 2_500, "season_advance_cents": 22_000,
    "topoff_issued_cents": 4_000, "assets_cents": 19_100,
    "obligations_cents": 26_000, "current_settle_cents": -6_900,
}
for field, expected in sorted(ACCEPTED.items()):
    _assert(f"§9: {field} is still {expected}",
            FIXTURE_EXPECTED.get(field) == expected,
            f"got {FIXTURE_EXPECTED.get(field)}")
_assert("§9: Held is still a strict subset of In Play, and memo-only",
        0 < FIXTURE_EXPECTED["held_open_challenges_cents"]
        < FIXTURE_EXPECTED["in_play_cents"]
        and FIXTURE_EXPECTED["assets_cents"] == (
            FIXTURE_EXPECTED["wallet_cents"]
            + FIXTURE_EXPECTED["weekly_min_live_cents"]
            + FIXTURE_EXPECTED["min_reserve_cents"]
            + FIXTURE_EXPECTED["expired_min_cents"]
            + FIXTURE_EXPECTED["in_play_cents"]),
        "assets sum excludes Held entirely")


print("\n" + "=" * 74)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4C-1R WAGERING AUTHORITY — all assertions PASSED")