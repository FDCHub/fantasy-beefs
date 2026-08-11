#!/usr/bin/env python3
"""
test_s8_p4c1_lifecycle_cutover.py — Sprint 8 P4C-1 · the proposal lifecycle cutover.

WHAT THIS PROVES. That the LIVE application — the HTTP routes a browser actually
calls — now runs the approved Spec-2 funded lifecycle, and that the legacy soft
reservation is gone rather than merely bypassed. Every claim below is made
through `POST /beef/...` on a real server, because a suite that called
`economy/challenge_funding.py` directly would prove the module works and prove
nothing at all about what the application does with it.

THE ONE CLAIM THAT MATTERS MOST is §7's: Held is now non-zero, and it is a
MEMO-ONLY SUBSET of In Play. Those are two different failures if got wrong —
a Held that stayed 0 would mean the cutover did not happen, and a Held that got
ADDED to assets would double-count every open challenge in Current Settle. The
suite asserts both directions, and asserts Current Settle's exact value on both
sides of an issue to show the money moved BETWEEN asset terms rather than into
one.

WHY THE ABSENCES ARE ASSERTED TOO. "We retired the soft reservation" and "the
legacy engine is no longer reachable from a route" are exactly the kind of claim
that decays the moment someone re-adds an import. They are checked structurally,
by parsing the module, not by reading it.

POSTGRESQL IS NOT REQUIRED AND IS NOT CLAIMED. `.with_for_update()` is a
documented no-op on SQLite, so the funded path is functionally exercisable here;
the locking and isolation properties it carries are concurrency claims and
concurrency is P5's. Nothing below asserts a locking property.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 's8p4c1.db')}"
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


# ══ §3 · the soft reservation is retired, checked structurally ═══════════════
#
# Run before anything boots, because it needs no database and because a failure
# here invalidates every runtime claim below it.

_section("§3 · the soft reservation is retired")

_engine_src = open(os.path.join(ROOT, "beefs", "beef_engine.py"),
                   encoding="utf-8").read()
_engine_ast = ast.parse(_engine_src)

# EXECUTABLE CODE ONLY. A substring scan would match this module's own prose
# about the retirement and pass for the wrong reason — the same false negative
# that had to be corrected in P4B.
_engine_names = {
    n.id for n in ast.walk(_engine_ast) if isinstance(n, ast.Name)
} | {
    n.attr for n in ast.walk(_engine_ast) if isinstance(n, ast.Attribute)
}
_engine_imports = {
    alias.name
    for node in ast.walk(_engine_ast) if isinstance(node, ast.ImportFrom)
    for alias in node.names
}

_assert("§3: beef_engine no longer IMPORTS _challenge_reserved",
        "_challenge_reserved" not in _engine_imports)
_assert("§3: beef_engine no longer CALLS _challenge_reserved",
        "_challenge_reserved" not in _engine_names,
        "zero references in executable code")

# The helper itself survives for display and for legacy rows — retiring the
# GATE is not the same as deleting the function, and wallet/faab_wallet.py still
# reports it. Asserted so a later cleanup cannot quietly take the display source
# with it.
from wallet.wallet_manager import _challenge_reserved  # noqa: E402

_assert("§3: the helper survives for display/legacy compatibility",
        callable(_challenge_reserved))

# ══ §10 · the legacy mutation path is unreachable from any route ═════════════

_section("§10 · legacy disposition — no live mutation path")

_api_ast = ast.parse(open(os.path.join(ROOT, "api", "main.py"),
                          encoding="utf-8").read())
_api_beef_imports = {
    alias.name
    for node in ast.walk(_api_ast) if isinstance(node, ast.ImportFrom)
    if node.module == "beefs.beef_engine"
    for alias in node.names
}
_LEGACY_MUTATORS = {"issue_challenge", "respond_to_challenge",
                    "counter_challenge", "get_pending_challenges"}

_assert("§10: api/main.py imports no legacy challenge mutator",
        not (_api_beef_imports & _LEGACY_MUTATORS),
        f"beef_engine imports = {sorted(_api_beef_imports) or 'none'}")

# What it MAY still import is pricing. Stated positively so the boundary is a
# recorded decision rather than an accident of what happened to be needed.
_assert("§10: pricing is still shared — _compute_odds is not a money path",
        _api_beef_imports <= {"_compute_odds"},
        "only the odds model crosses the boundary")

# ══ Seed a league, in process, on the authoritative fixture ═════════════════
#
# ONE PROCESS AND ONE DATABASE, deliberately. Every claim below pairs an HTTP
# call with a direct backend read of the state it produced, and a two-process
# harness could only compare two databases that were seeded to look alike. The
# route and the ledger have to be looking at the same rows for "the wallet
# really moved" to mean anything.

from db.schema import (  # noqa: E402
    Base, League, LeagueCommissioner, Matchup, Player, Projection, Roster,
    SessionLocal, Team, User, Wallet, engine,
)
from auth.jwt_auth import hash_password  # noqa: E402
from ledger.ledger import create_ledger_table  # noqa: E402
from test_support_rev42_fixture import _seed_accounting_fixture  # noqa: E402

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "sprint8-password"
GM_EMAIL, OPP_EMAIL = "gm@p4c1.test", "opp@p4c1.test"
COMM_EMAIL = "commissioner@p4c1.test"
SEASON, WEEK = 2026, 5

with SessionLocal() as db:
    league = League(name="Cutover League", season=SEASON)
    db.add(league); db.flush()

    gm_team = Team(team_name="Gravy Train", owner="A. Gm", email=GM_EMAIL,
                   league_id=league.id)
    opp_team = Team(team_name="The Braintrust", owner="A. Rival",
                    email=OPP_EMAIL, league_id=league.id)
    # A THIRD TEAM CARRIES THE COMMISSIONER. Both wagering teams have to be
    # ordinary GMs, because `assert_own_team` exempts commissioners from every
    # ownership check — a commissioner counterparty would pass §11's negatives
    # for the wrong reason and prove nothing about the protection.
    comm_team = Team(team_name="The Chair", owner="A. Commissioner",
                     email=COMM_EMAIL, league_id=league.id)
    db.add_all([gm_team, opp_team, comm_team]); db.flush()

    hashed = hash_password(PASSWORD)
    db.add_all([
        User(email=GM_EMAIL, hashed_password=hashed, team_id=gm_team.id,
             role="gm"),
        User(email=OPP_EMAIL, hashed_password=hashed, team_id=opp_team.id,
             role="gm"),
        User(email=COMM_EMAIL, hashed_password=hashed, team_id=comm_team.id,
             role="commissioner"),
    ])
    db.flush()
    db.add(LeagueCommissioner(
        league_id=league.id, source="bootstrap",
        user_id=db.query(User).filter(User.email == COMM_EMAIL).one().id))
    db.flush()

    _seed_accounting_fixture(db, league, gm_team, opp_team)

    # The opponent needs a Wallet row of their own: the funding path takes a
    # wallet-row mutex before it reads a balance and refuses outright when there
    # is none, so acceptance would fail for a reason that has nothing to do with
    # this package. The Rev 4.2 fixture creates one only for the GM.
    if not db.query(Wallet).filter(Wallet.team_id == opp_team.id).first():
        db.add(Wallet(team_id=opp_team.id, balance=0.0))

    # THE OPPONENT NEEDS SPENDABLE FUNDS. The Rev 4.2 fixture leaves them with
    # an allocation but an empty wallet — enough to have funded their side of
    # the settled wager it describes, not enough to counter or to fund a Derived
    # stake. Posted under the real approved-issuance door, in the shape the
    # Top-Off service emits, so it is an ordinary obligation rather than money
    # from nowhere.
    from economy.current_settle import DOOR_APPROVED_TOPOFF
    from economy.economy_events import wallet_account
    from ledger.ledger import post as ledger_post
    ledger_post([(wallet_account(opp_team.id), 10_000), ("world", -10_000)],
                door=DOOR_APPROVED_TOPOFF, session=db)
    db.flush()

    # A shared week-5 matchup. Acceptance creates Bet rows and refuses to create
    # one for a team with no matchup, on the grounds that the wager could never
    # settle — a real guard, not an artefact of the fixture.
    # ROSTERS AND PROJECTIONS, because the locked quote is a real Monte Carlo
    # price over real starters. The route computes it through the same
    # `_compute_odds` the legacy route used, so a fixture without starters would
    # fail at pricing — a genuine prerequisite of issuing a locked wager, not a
    # detail of this suite.
    for team, nfl in ((gm_team, "KC"), (opp_team, "PHI")):
        for i in range(9):
            player = Player(name=f"{team.team_name[:3]}-P{i}", position="WR",
                            nfl_team=nfl)
            db.add(player); db.flush()
            db.add(Roster(team_id=team.id, player_id=player.id))
            db.add(Projection(player_id=player.id, week=WEEK, season=SEASON,
                              projected_points=12.0 + i, source="fixture"))
    db.flush()

    if not (db.query(Matchup)
            .filter(Matchup.league_id == league.id, Matchup.week == WEEK)
            .first()):
        db.add(Matchup(league_id=league.id, week=WEEK,
                       home_team_id=gm_team.id, away_team_id=opp_team.id,
                       home_score=0.0, away_score=0.0))
    db.commit()
    LEAGUE, GM_TEAM, OPP_TEAM = league.id, gm_team.id, opp_team.id


from fastapi.testclient import TestClient  # noqa: E402
from api.main import app  # noqa: E402
from auth.session import CSRF_COOKIE, CSRF_HEADER  # noqa: E402


class Client:
    """One signed-in GM, driving the app exactly as the browser does.

    THE CSRF HEADER IS SENT THE WAY THE FRONTEND SENDS IT — read back out of the
    script-readable double-submit cookie. Hard-coding it, or exempting these
    routes, would quietly drop the protection P1 put on every state-changing
    request, and this package adds four new ones.
    """

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


def read(team_id: int, league_id: int) -> dict:
    """The GM's accounting position, read straight from the backend."""
    from economy.challenge_escrow_view import team_open_challenge_escrow_cents
    from economy.current_settle import current_settle, in_play_cents
    from ledger.ledger import trial_balance

    with SessionLocal() as db:
        cs = current_settle(db, team_id=team_id, league_id=league_id,
                            season=SEASON)
        return {
            "wallet": cs.wallet_cents,
            "weekly_min": cs.weekly_min_live_cents,
            # What a GM can actually commit — and the term the funded path
            # spends down, min-first.
            "available": cs.wallet_cents + cs.weekly_min_live_cents,
            "in_play": in_play_cents(db, team_id),
            "held": team_open_challenge_escrow_cents(db, team_id),
            "assets": cs.assets_cents,
            "current_settle": cs.current_settle_cents,
            "trial_balance": trial_balance(),
        }


print("=" * 74)
print("S8-P4C-1 — proposal lifecycle cutover")
print("=" * 74)

gm, opp, anon = Client(GM_EMAIL), Client(OPP_EMAIL), Client(None)

status, me = gm.request("GET", "/auth/me")
assert status == 200, me
_assert("the acting context is resolved authoritatively",
        me["capabilities"]["acting_team_id"] == GM_TEAM
        and me["capabilities"]["acting_league_id"] == LEAGUE)

# ══ §4 · one live path — issue posts real escrow ═════════════════════════

_section("§4 · issue posts real escrow through the live route")

before = read(GM_TEAM, LEAGUE)
status, issued = gm.request("POST", "/beef/challenge", {
    "challenger_team_id": GM_TEAM, "challenged_team_id": OPP_TEAM,
    "week": WEEK, "bet_type": "straight", "amount": 15.00,
})
_assert("§4: POST /beef/challenge succeeds", status == 201,
        f"status {status}: {issued}")
assert status == 201, issued
CH = issued["challenge_id"]

_assert("§4: the response carries the Spec-1 negotiation state",
        issued["response_status"] == "offered", issued["response_status"])
_assert("§4: issue escrowed the full Anchor stake",
        issued["escrow_cents"] == 1_500, f"{issued['escrow_cents']} cents")

after = read(GM_TEAM, LEAGUE)
_assert("§4: the stake really left the issuer's spendable funds",
        after["available"] == before["available"] - 1_500,
        f"{before['available']} → {after['available']}")
# MIN-FIRST, which is why the wallet alone is the wrong place to look. The
# weekly minimum is use-it-or-lose-it, so the funded path spends it before it
# touches wallet money that carries no expiry — and an assertion watching only
# the wallet would have called a correct 1500-cent debit a 500-cent one.
_assert("§4: the weekly minimum was consumed FIRST",
        after["weekly_min"] == 0
        and after["wallet"] == before["wallet"] - (1_500 - before["weekly_min"]),
        f"min {before['weekly_min']} → {after['weekly_min']}, "
        f"wallet {before['wallet']} → {after['wallet']}")

from db.schema import ChallengeFundingLeg, SessionLocal  # noqa: E402
from economy.challenge_funding import challenge_escrow_account  # noqa: E402

with SessionLocal() as db:
    legs = (db.query(ChallengeFundingLeg)
            .filter(ChallengeFundingLeg.challenge_id == CH).all())
    _assert("§4: provenance was recorded as ChallengeFundingLeg rows",
            len(legs) >= 1, f"{len(legs)} leg(s)")
    _assert("§4: every leg attributes the money to the issuing team",
            all(leg.team_id == GM_TEAM for leg in legs))
    _assert("§4: every leg names the challenge escrow account",
            all(leg.destination_account == challenge_escrow_account(CH)
                for leg in legs))
    _assert("§4: the legs sum to the escrowed stake",
            sum(leg.amount_cents for leg in legs) == 1_500)

_assert("§4: the ledger still balances", after["trial_balance"] == 0,
        f"trial balance {after['trial_balance']}")

# ══ §7 · Held is non-zero, and is a memo-only subset of In Play ══════════

_section("§7 · Held becomes real, and stays a memo")

_assert("§7: Held is no longer structurally zero",
        after["held"] == before["held"] + 1_500 and after["held"] > 0,
        f"{before['held']} → {after['held']} cents")
_assert("§7: Held is a SUBSET of In Play — not a term beside it",
        after["held"] <= after["in_play"],
        f"held {after['held']} ⊆ in_play {after['in_play']}")
_assert("§7: In Play grew by exactly the challenge escrow",
        after["in_play"] == before["in_play"] + 1_500,
        f"{before['in_play']} → {after['in_play']}")

# THE DOUBLE-COUNT TEST. If Held were added to assets alongside In Play, the
# issue would have INCREASED assets by 1500 out of nowhere. It is a memo, so
# assets are unchanged and Current Settle does not move: the money went from
# one asset term (wallet) to another (in_play).
_assert("§7: Held is memo-only — assets did not grow",
        after["assets"] == before["assets"],
        f"{before['assets']} → {after['assets']}")
_assert("§7: issuing a funded challenge does not move Current Settle",
        after["current_settle"] == before["current_settle"],
        f"{before['current_settle']} → {after['current_settle']} "
        f"(a transfer between asset terms, not a gain or a loss)")

# ══ §5 · the inbox classifies from response_status ═══════════════════════

_section("§5 · the pending read is repointed to response_status")

status, inbox = opp.request("GET", f"/beef/pending/{OPP_TEAM}")
_assert("§5: the recipient's inbox reads", status == 200, str(inbox))
mine = [row for row in inbox if row["challenge_id"] == CH]
_assert("§5: the funded challenge is VISIBLE to the inbox", len(mine) == 1,
        f"{len(inbox)} row(s) returned")
if mine:
    row = mine[0]
    _assert("§5: it is classified by its Spec-1 negotiation state",
            row["response_status"] == "offered", row["response_status"])
    _assert("§5: direction is resolved from the acting team",
            row["direction"] == "received", row["direction"])
    _assert("§5: the row reports the REAL escrow behind it",
            row["escrow_cents"] == 1_500, f"{row['escrow_cents']} cents")
    _assert("§5: the row carries the active proposal's stake",
            row["anchor_stake_cents"] == 1_500,
            str(row["anchor_stake_cents"]))

status, sent = gm.request("GET", f"/beef/pending/{GM_TEAM}")
_assert("§5: the issuer sees the same challenge as SENT",
        any(r["challenge_id"] == CH and r["direction"] == "sent"
            for r in sent))

# ══ §11 · authorization re-proof on the new entry points ════════════════

_section("§11 · authorization survives the cutover")

status, _ = gm.request("POST", "/beef/challenge", {
    "challenger_team_id": OPP_TEAM, "challenged_team_id": GM_TEAM,
    "week": WEEK, "bet_type": "straight", "amount": 5.00,
})
_assert("§11: a GM cannot issue a challenge AS another team",
        status == 403, f"status {status}")

# DISCLOSED, NOT ASSERTED AS DESIRABLE. `assert_own_team` has always let a
# commissioner act as any team in their league, and this package did not change
# that rule — but it changed what the rule COSTS. Before the cutover, a
# commissioner issuing "as" another GM created an unfunded pending row; now the
# same call debits that GM's real wallet and escrows their money. Recorded here
# so the consequence lives in a suite rather than only in a report, and so a
# later decision to narrow the rule has a test to change.
from auth.jwt_auth import assert_own_team as _assert_own_team  # noqa: E402
from fastapi import HTTPException as _HTTPException  # noqa: E402


class _FakeCommissioner:
    role, team_id = "commissioner", OPP_TEAM


_commissioner_may_act_as_any_team = True
try:
    _assert_own_team(GM_TEAM, _FakeCommissioner())
except _HTTPException:
    _commissioner_may_act_as_any_team = False
_assert("§11: DISCLOSED — a commissioner may still act as any team, and that "
        "now moves real money",
        _commissioner_may_act_as_any_team,
        "pre-existing rule; the cutover raises its consequence — narrowing it "
        "is a POR decision, not a P4C-1 change")

status, _ = gm.request("POST", "/beef/respond",
                       {"challenge_id": CH, "accept": True})
_assert("§11: the ISSUER cannot accept their own offered challenge",
        status == 403, f"status {status}")

status, _ = gm.request("GET", f"/beef/pending/{OPP_TEAM}")
_assert("§11: a GM cannot read another team's inbox", status == 403,
        f"status {status}")

status, _ = anon.request("POST", "/beef/challenge", {
    "challenger_team_id": GM_TEAM, "challenged_team_id": OPP_TEAM,
    "week": WEEK, "bet_type": "straight", "amount": 5.00,
})
_assert("§11: an unauthenticated caller is refused", status in (401, 403),
        f"status {status}")

held_after_refusals = read(GM_TEAM, LEAGUE)
_assert("§11: no refusal moved any money",
        held_after_refusals["held"] == after["held"]
        and held_after_refusals["wallet"] == after["wallet"])

# ══ §6 · Locked semantics unregressed ═══════════════════════════════════

_section("§6 · locked-mode semantics")

with SessionLocal() as db:
    from db.schema import BeefChallenge, BeefProposal
    ch = db.query(BeefChallenge).filter(BeefChallenge.id == CH).one()
    _assert("§6: the challenge was issued in LOCKED mode",
            ch.challenge_mode == "locked", ch.challenge_mode)
    _assert("§6: no dynamic handshake was performed",
            ch.dynamic_handshake_at is None)
    proposal = (db.query(BeefProposal)
                .filter(BeefProposal.id == ch.active_proposal_id).one())
    _assert("§6: the proposal froze a real quote, not a placeholder",
            proposal.anchor_odds is not None
            and proposal.derived_odds is not None
            and proposal.anchor_moneyline is not None,
            f"anchor {proposal.anchor_odds}, derived {proposal.derived_odds}")
    _assert("§6: both sides' stakes are frozen on the proposal",
            proposal.anchor_stake_cents == 1_500
            and proposal.quoted_derived_stake_cents == 1_500)
    FIRST_VERSION = proposal.version_number

# ══ §4 (cont.) · counter is funded, and moves no money ══════════════════

_section("§4 · counter validates capacity and posts nothing")

pre_counter = read(GM_TEAM, LEAGUE)
status, countered = opp.request("POST", "/beef/counter", {
    "challenge_id": CH, "countered_amount": 22.00,
})
_assert("§4: POST /beef/counter succeeds", status == 200,
        f"status {status}: {countered}")
if status == 200:
    _assert("§4: the challenge is now COUNTERED",
            countered["response_status"] == "countered",
            countered["response_status"])
post_counter = read(GM_TEAM, LEAGUE)
_assert("§4: a counter moved NO money (Spec 2 §10)",
        post_counter["wallet"] == pre_counter["wallet"]
        and post_counter["held"] == pre_counter["held"],
        f"wallet {post_counter['wallet']}, held {post_counter['held']}")

with SessionLocal() as db:
    from db.schema import BeefChallenge, BeefProposal
    ch = db.query(BeefChallenge).filter(BeefChallenge.id == CH).one()
    active = (db.query(BeefProposal)
              .filter(BeefProposal.id == ch.active_proposal_id).one())
    _assert("§4: the counter froze a NEW immutable version",
            active.version_number > FIRST_VERSION,
            f"v{FIRST_VERSION} → v{active.version_number}")
    _assert("§4: the new version carries the countered stake",
            active.anchor_stake_cents == 2_200,
            str(active.anchor_stake_cents))
    _assert("§6: relock repriced — the new version has its own quote",
            active.anchor_odds is not None)
    versions = (db.query(BeefProposal)
                .filter(BeefProposal.challenge_id == CH).count())
    _assert("§4: the earlier version was preserved, not mutated",
            versions >= 2, f"{versions} versions")

# ══ §11 (cont.) · a counter hands the decision back ═════════════════════

status, _ = opp.request("POST", "/beef/respond",
                        {"challenge_id": CH, "accept": True})
_assert("§11: the COUNTERING team cannot also accept its own counter",
        status == 403, f"status {status}")

# ══ §12 · idempotency ═══════════════════════════════════════════════════

_section("§12 · accept, and its replay")

pre_accept_gm = read(GM_TEAM, LEAGUE)
status, accepted = gm.request("POST", "/beef/respond",
                              {"challenge_id": CH, "accept": True})
_assert("§4: POST /beef/respond accepts through the funded path",
        status == 200, f"status {status}: {accepted}")
assert status == 200, accepted

_assert("§4: acceptance produced BOTH Bet rows",
        accepted["anchor_bet_id"] is not None
        and accepted["derived_bet_id"] is not None,
        f"anchor {accepted['anchor_bet_id']}, "
        f"derived {accepted['derived_bet_id']}")
_assert("§4: the challenge is ACCEPTED",
        accepted["response_status"] == "accepted",
        accepted["response_status"])

post_accept_gm = read(GM_TEAM, LEAGUE)
_assert("§4: the issuer topped up to the countered Anchor",
        post_accept_gm["wallet"] == pre_accept_gm["wallet"] - 700,
        f"{pre_accept_gm['wallet']} → {post_accept_gm['wallet']} "
        f"(1500 already escrowed, 2200 accepted)")

with SessionLocal() as db:
    from ledger.ledger import _balance_of_in_session
    _assert("§4: the challenge escrow account was fully migrated",
            _balance_of_in_session(db, challenge_escrow_account(CH)) == 0,
            "escrow:challenge:{id} nets to zero after acceptance")
    _assert("§4: the Anchor Bet now holds the escrow",
            _balance_of_in_session(
                db, f"escrow:{accepted['anchor_bet_id']}") == 2_200)
    _assert("§4: the Derived Bet holds the recipient's stake",
            _balance_of_in_session(
                db, f"escrow:{accepted['derived_bet_id']}") == 2_200)

# ACCEPTANCE TAKES THE CHALLENGE OUT OF HELD ENTIRELY. Its escrow migrated into
# Bet escrow, where it is ordinary wager exposure; counting it under Held as
# well would report the same money twice under two names.
# AND IT DROPS BY 1500, NOT BY THE 2200 THAT WAS ACCEPTED. Held only ever
# contained money actually escrowed, and the counter raised the stake without
# posting anything — the extra 700 was topped up and migrated within the same
# acceptance, so it never spent a moment in challenge escrow. A drop of 2200
# here would mean Held had been tracking proposed amounts again, which is
# precisely the soft reservation this package retired.
_assert("§7: the accepted challenge drops out of Held completely",
        post_accept_gm["held"] == pre_accept_gm["held"] - 1_500,
        f"{pre_accept_gm['held']} → {post_accept_gm['held']} cents "
        f"(the escrowed 1500, not the accepted 2200)")
_assert("§7: In Play retains the money — it moved, it did not vanish",
        post_accept_gm["in_play"] == pre_accept_gm["in_play"] + 700,
        f"{pre_accept_gm['in_play']} → {post_accept_gm['in_play']}")
_assert("§4: the ledger still balances after acceptance",
        post_accept_gm["trial_balance"] == 0)

# REPLAY. The same accept again must be closed by the protocol, not applied
# twice — the failure it guards against is a duplicate Bet pair and a second
# escrow migration.
status, replay = gm.request("POST", "/beef/respond",
                            {"challenge_id": CH, "accept": True})
_assert("§12: replaying an accept is refused or reported as a replay",
        status in (200, 409), f"status {status}: {replay}")
if status == 200:
    _assert("§12: the replay is FLAGGED as one", replay.get("replayed") is True,
            str(replay.get("replayed")))
replayed_state = read(GM_TEAM, LEAGUE)
_assert("§12: the replay moved no money",
        replayed_state["wallet"] == post_accept_gm["wallet"]
        and replayed_state["in_play"] == post_accept_gm["in_play"],
        f"wallet {replayed_state['wallet']}, "
        f"in_play {replayed_state['in_play']}")
with SessionLocal() as db:
    from db.schema import Bet
    n_bets = db.query(Bet).filter(Bet.beef_challenge_id == CH).count()
    _assert("§12: exactly two Bet rows exist for the challenge",
            n_bets == 2, f"{n_bets} bets")
_assert("§12: the ledger still balances after the replay",
        replayed_state["trial_balance"] == 0)

# ══ §4 · decline reverses the escrow exactly ════════════════════════════

_section("§4 · decline returns the stake by reverse legs")

pre_decline = read(GM_TEAM, LEAGUE)
status, second = gm.request("POST", "/beef/challenge", {
    "challenger_team_id": GM_TEAM, "challenged_team_id": OPP_TEAM,
    "week": WEEK, "bet_type": "straight", "amount": 9.00,
})
assert status == 201, second
CH2 = second["challenge_id"]
mid_decline = read(GM_TEAM, LEAGUE)
_assert("§4: the second issue escrowed its stake",
        mid_decline["held"] == pre_decline["held"] + 900,
        f"{pre_decline['held']} → {mid_decline['held']} cents")

status, declined = opp.request("POST", "/beef/respond",
                               {"challenge_id": CH2, "accept": False})
_assert("§4: POST /beef/respond declines through the funded path",
        status == 200, f"status {status}: {declined}")
post_decline = read(GM_TEAM, LEAGUE)

_assert("§4: the declined stake was returned to the wallet EXACTLY",
        post_decline["wallet"] == pre_decline["wallet"],
        f"{pre_decline['wallet']} → {post_decline['wallet']}")
_assert("§7: the declined stake leaves Held exactly",
        post_decline["held"] == pre_decline["held"],
        f"{mid_decline['held']} → {post_decline['held']} cents")
_assert("§4: Current Settle is exactly where it started",
        post_decline["current_settle"] == pre_decline["current_settle"],
        f"{pre_decline['current_settle']} → "
        f"{post_decline['current_settle']}")
_assert("§4: the ledger balances after the reversal",
        post_decline["trial_balance"] == 0)

with SessionLocal() as db:
    legs = (db.query(ChallengeFundingLeg)
            .filter(ChallengeFundingLeg.challenge_id == CH2).all())
    _assert("§4: the reversal was recorded as legs, not a deletion",
            any(leg.amount_cents < 0 for leg in legs)
            and sum(leg.amount_cents for leg in legs) == 0,
            f"{len(legs)} legs summing to "
            f"{sum(leg.amount_cents for leg in legs)}")

# ══ Capacity refusal is a refusal, not an overdraft ═════════════════════

_section("§4 · capacity is enforced by real money now")

over = read(GM_TEAM, LEAGUE)
status, refused = gm.request("POST", "/beef/challenge", {
    "challenger_team_id": GM_TEAM, "challenged_team_id": OPP_TEAM,
    "week": WEEK, "bet_type": "straight",
    "amount": (over["wallet"] / 100) + 500.00,
})
_assert("§4: a challenge beyond capacity is refused",
        status in (400, 409), f"status {status}: {refused}")
final = read(GM_TEAM, LEAGUE)
_assert("§4: the refusal posted nothing",
        final["wallet"] == over["wallet"] and final["held"] == over["held"])
_assert("§4: the ledger balances at the end of the run",
        final["trial_balance"] == 0)
# ══ §9 · Current Settle, recomputed from first principles ═══════════════════
#
# NOT A RE-READ OF THE READ MODEL. Every term below is summed straight off the
# ledger by account, and the total is compared with what `current_settle()`
# returns. If the read model had quietly started counting Held as an asset, the
# two would disagree by exactly the open challenge — which is the point of doing
# the arithmetic a second way rather than asserting the same call twice.

_section("§9 · Current Settle recomputed independently, with real Held")

from sqlalchemy import text  # noqa: E402

from economy.challenge_escrow_view import (  # noqa: E402
    team_open_challenge_escrow_cents,
)
from economy.current_settle import (  # noqa: E402
    DOOR_APPROVED_TOPOFF, DOOR_SEASON_ALLOCATION, current_settle, in_play_cents,
)

with SessionLocal() as db:
    def account_sum(pattern: str, door: str | None = None) -> int:
        sql = ("SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
               "WHERE account LIKE :pattern")
        params = {"pattern": pattern}
        if door:
            sql += " AND door = :door"
            params["door"] = door
        return int(db.execute(text(sql), params).scalar() or 0)

    wallet      = account_sum(f"wallet:{GM_TEAM}")
    weekly_min  = account_sum(f"min:{GM_TEAM}:%")
    min_reserve = account_sum(f"min_reserve:{GM_TEAM}")
    expired_min = account_sum(f"expired_min:{GM_TEAM}")
    receivable  = -account_sum(f"receivable:{GM_TEAM}")

    # In Play is the one term that cannot be summed by account name alone: an
    # escrow account says how much it holds, never whose it is. Attribution is
    # the read model's job, and it is proven separately above.
    in_play = in_play_cents(db, GM_TEAM)
    held    = team_open_challenge_escrow_cents(db, GM_TEAM)

    season_advance = (
        account_sum(f"min_reserve:{GM_TEAM}", DOOR_SEASON_ALLOCATION)
        + account_sum(f"reserve:{GM_TEAM}", DOOR_SEASON_ALLOCATION))
    topoff = account_sum(f"wallet:{GM_TEAM}", DOOR_APPROVED_TOPOFF)

    served = current_settle(db, team_id=GM_TEAM, league_id=LEAGUE, season=SEASON)

assets      = wallet + weekly_min + min_reserve + expired_min + in_play
obligations = season_advance + topoff + receivable
settle      = assets - obligations

_assert("§9: the recomputed assets match the read model",
        assets == served.assets_cents,
        f"recomputed {assets} vs served {served.assets_cents}")
_assert("§9: the recomputed obligations match the read model",
        obligations == served.obligations_cents,
        f"recomputed {obligations} vs served {served.obligations_cents}")
_assert("§9: the recomputed Current Settle matches the read model",
        settle == served.current_settle_cents,
        f"recomputed {settle} vs served {served.current_settle_cents}")

# THE ASSERTION THIS SECTION EXISTS FOR. Held is real and non-zero here, and it
# appears in NEITHER total — it is already inside In Play, and adding it would
# overstate the GM's position by the whole of their open challenge exposure.
_assert("§9: Held is non-zero at the point of this recomputation",
        held > 0, f"{held} cents")
_assert("§9: and Held sits INSIDE In Play, not beside it",
        held <= in_play, f"held {held} ⊆ in_play {in_play}")
_assert("§9: counting Held as its own asset would overstate the position",
        assets + held != served.assets_cents,
        f"would have reported {assets + held} instead of {assets}")

print()
for label, value in (("wallet", wallet), ("weekly min live", weekly_min),
                     ("min reserve", min_reserve), ("expired min", expired_min),
                     ("in play", in_play)):
    print(f"    {label:<18}{value:>8}")
print(f"    {'ASSETS':<18}{assets:>8}   (of which Held, memo only: {held})")
for label, value in (("season advance", season_advance),
                     ("top-off issued", topoff), ("receivable", receivable)):
    print(f"    {label:<18}{value:>8}")
print(f"    {'OBLIGATIONS':<18}{obligations:>8}")
print(f"    {'CURRENT SETTLE':<18}{settle:>8}")



print("\n" + "=" * 74)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4C-1 LIFECYCLE CUTOVER — all assertions PASSED")
