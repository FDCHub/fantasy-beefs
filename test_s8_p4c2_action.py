#!/usr/bin/env python3
"""
test_s8_p4c2_action.py — Sprint 8 P4C-2 · the authoritative Action tab.

WHAT THIS PROVES. That the Action tab's four rails are decided by the backend
from real proposal state, that all four commands go through the governed
lifecycle, that Dynamic is now reachable over HTTP through the existing Dynamic
implementation, and that every transition moves exactly the money it should.

THE CLASSIFICATION IS THE SUBJECT. A wager's rail is a protocol statement —
whose decision it is — and the case that separates a correct rule from a
plausible one is the COUNTER, where the decision inverts and direction stops
predicting anything. Every section claim below is therefore made from both
sides at once: the same challenge must be ACTION REQUIRED for one GM and
WAITING for the other, and it must swap when countered.

DYNAMIC IS EXERCISED, NOT DESCRIBED. §4 required exposing it through the
governing lifecycle without recreating its semantics, so the suite issues a real
Dynamic challenge over HTTP, handshakes it, and asserts the ceilings came from
the backend's own model rather than from anything this layer computed.

MONEY IS CHECKED ON EVERY TRANSITION, in exact cents, against fixture amounts —
never against Rev 4.2's $25, which belongs to one specific fixture and is not a
property of Action behaviour.
"""

from __future__ import annotations

import ast
import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 's8p4c2.db')}"
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


# ══ Seed three GMs in one league, plus a foreign league ══════════════════════

from db.schema import (  # noqa: E402
    Base, BeefChallenge, BeefProposal, League, LeagueCommissioner, Matchup,
    Player, Projection, Roster, SessionLocal, Team, User, Wallet, engine,
)
from auth.jwt_auth import hash_password  # noqa: E402
from ledger.ledger import create_ledger_table, post as ledger_post  # noqa: E402

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "sprint8-password"
A_EMAIL, B_EMAIL = "gm-a@p4c2.test", "gm-b@p4c2.test"
C_EMAIL, F_EMAIL = "comm-c@p4c2.test", "gm-f@p4c2.test"
EMPTY_EMAIL = "empty@p4c2.test"
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
    league = League(name="Action League", season=SEASON)
    foreign = League(name="Foreign League", season=SEASON)
    db.add_all([league, foreign]); db.flush()

    team_a = _seed_team(db, league, "Gravy Train", A_EMAIL, 100_000)
    team_b = _seed_team(db, league, "The Braintrust", B_EMAIL, 100_000)
    team_c = _seed_team(db, league, "The Chair", C_EMAIL, 100_000)
    team_empty = _seed_team(db, league, "Fresh Start", EMPTY_EMAIL, 100_000)
    team_f = _seed_team(db, foreign, "Foreign XI", F_EMAIL, 100_000)

    comm = db.query(User).filter(User.email == C_EMAIL).one()
    comm.role = "commissioner"
    db.add(LeagueCommissioner(league_id=league.id, user_id=comm.id,
                              source="bootstrap"))
    db.flush()

    for home, away in ((team_a, team_b), (team_c, team_a),
                       (team_empty, team_b)):
        db.add(Matchup(league_id=league.id, week=WEEK, home_team_id=home.id,
                       away_team_id=away.id, home_score=0.0, away_score=0.0))
    db.commit()
    LEAGUE, FOREIGN = league.id, foreign.id
    A, B, C, EMPTY, F = (team_a.id, team_b.id, team_c.id, team_empty.id,
                         team_f.id)


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

    def request(self, method: str, path: str, body=None, csrf: bool = True):
        headers = {}
        token = self.http.cookies.get(CSRF_COOKIE)
        if token and csrf:
            headers[CSRF_HEADER] = token
        r = self.http.request(method, path, json=body, headers=headers)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text


def action(client: Client, league_id: int = None):
    status, body = client.request("GET",
                                  f"/league/{league_id or LEAGUE}/action/me")
    return status, body


def counts(client: Client) -> dict:
    status, body = action(client)
    assert status == 200, body
    return body["counts"]


def card_for(client: Client, challenge_id: int):
    _, body = action(client)
    for cards in body["sections"].values():
        for card in cards:
            if card["challenge_id"] == challenge_id:
                return card
    return None


def money(team_id: int) -> dict:
    from economy.challenge_escrow_view import team_open_challenge_escrow_cents
    from economy.current_settle import current_settle, in_play_cents
    from ledger.ledger import trial_balance

    with SessionLocal() as db:
        cs = current_settle(db, team_id=team_id, league_id=LEAGUE,
                            season=SEASON)
        return {
            "spendable": cs.wallet_cents + cs.weekly_min_live_cents,
            "wallet": cs.wallet_cents,
            "in_play": in_play_cents(db, team_id),
            "held": team_open_challenge_escrow_cents(db, team_id),
            "current_settle": cs.current_settle_cents,
            "trial_balance": trial_balance(),
        }


print("=" * 74)
print("S8-P4C-2 — authoritative Action lifecycle")
print("=" * 74)

gm_a, gm_b, comm_c = Client(A_EMAIL), Client(B_EMAIL), Client(C_EMAIL)
gm_empty, gm_f = Client(EMPTY_EMAIL), Client(F_EMAIL)


# ══ §1 · the read contract ══════════════════════════════════════════════════

_section("§1 · the Action read contract")

status, body = action(gm_empty)
_assert("§1: the Action read serves", status == 200, str(body)[:160])
_assert("§1: it names all four sections",
        sorted(body["sections"]) == ["action", "completed", "live", "waiting"],
        str(sorted(body["sections"])))
_assert("§1: and carries counts for each",
        sorted(body["counts"]) == ["action", "completed", "live", "waiting"])
_assert("§1: a GM with no wagers gets four EMPTY sections, not an error",
        all(v == 0 for v in body["counts"].values()), str(body["counts"]))
_assert("§1: the team is resolved from the session, not requested",
        body["team_id"] == EMPTY, str(body["team_id"]))
_assert("§1: authoritative opponents are served for the composer",
        len(body["opponents"]) == 3
        and all(o["team_id"] != EMPTY for o in body["opponents"]),
        f"{len(body['opponents'])} opponents")

# CLASSIFICATION IS NOT DUPLICATED IN JAVASCRIPT. The frontend model must read
# the served section, never re-derive one — checked structurally because a
# re-derivation would agree with the server today and drift later.
_model_src = open(os.path.join(ROOT, "web", "js", "action-model.js"),
                  encoding="utf-8").read()
_assert("§1: the browser model does not re-derive sections in production",
        "SERVED.sections[section]" in _model_src
        and "SERVED.counts[section]" in _model_src,
        "sections and counts are read from the served body")


# ══ §2 · section semantics, from BOTH sides ═════════════════════════════════

_section("§2 · four-section classification")

status, locked = gm_a.request("POST", "/beef/challenge", {
    "challenger_team_id": A, "challenged_team_id": B, "week": WEEK,
    "bet_type": "straight", "amount": 20.00, "challenge_mode": "locked",
})
_assert("§2: GM A issues a Locked challenge", status == 201, str(locked)[:200])
assert status == 201, locked
CH = locked["challenge_id"]

_assert("§2: for the ISSUER it is WAITING",
        counts(gm_a)["waiting"] == 1 and counts(gm_a)["action"] == 0,
        str(counts(gm_a)))
_assert("§2: for the RECIPIENT the same challenge is ACTION REQUIRED",
        counts(gm_b)["action"] == 1 and counts(gm_b)["waiting"] == 0,
        str(counts(gm_b)))

a_card, b_card = card_for(gm_a, CH), card_for(gm_b, CH)
_assert("§2: the decision owner is the recipient",
        a_card["decision_team_id"] == B and b_card["decision_team_id"] == B)
_assert("§2: only the recipient is told they decide",
        b_card["viewer_decides"] is True and a_card["viewer_decides"] is False)
_assert("§2: and only the recipient is offered controls",
        b_card["controls"] == ["accept", "counter", "decline"]
        and a_card["controls"] == [],
        f"issuer {a_card['controls']}, recipient {b_card['controls']}")
_assert("§2: the user-facing status is the locked vocabulary",
        b_card["status"] == "Incoming", b_card["status"])

# THE CASE DIRECTION GETS WRONG.
status, countered = gm_b.request("POST", "/beef/counter",
                                 {"challenge_id": CH, "countered_amount": 26.00})
_assert("§2: GM B counters", status == 200, str(countered)[:160])

_assert("§2: the counter INVERTS the sections — issuer now decides",
        counts(gm_a)["action"] == 1 and counts(gm_a)["waiting"] == 0,
        str(counts(gm_a)))
_assert("§2: and the counterer is now the one waiting",
        counts(gm_b)["waiting"] == 1 and counts(gm_b)["action"] == 0,
        str(counts(gm_b)))
a_card, b_card = card_for(gm_a, CH), card_for(gm_b, CH)
_assert("§2: the decision owner flipped to the original issuer",
        a_card["decision_team_id"] == A)
_assert("§2: controls moved with the decision, not with direction",
        a_card["controls"] and not b_card["controls"],
        f"issuer {a_card['controls']}, counterer {b_card['controls']}")
_assert("§2: direction did NOT change — A still sent it",
        a_card["direction"] == "sent" and b_card["direction"] == "received")
_assert("§2: the status word is Countered", a_card["status"] == "Countered")


# ══ §7 · counter creates an immutable new version ═══════════════════════════

_section("§7 · counter versioning")

with SessionLocal() as db:
    versions = (db.query(BeefProposal)
                .filter(BeefProposal.challenge_id == CH)
                .order_by(BeefProposal.version_number).all())
    challenge = db.query(BeefChallenge).filter(BeefChallenge.id == CH).one()
    _assert("§7: a NEW proposal version exists", len(versions) == 2,
            f"{len(versions)} versions")
    _assert("§7: the prior version is preserved unchanged",
            versions[0].anchor_stake_cents == 2_000,
            str(versions[0].anchor_stake_cents))
    _assert("§7: the new version carries the countered stake",
            versions[1].anchor_stake_cents == 2_600,
            str(versions[1].anchor_stake_cents))
    _assert("§7: the active pointer moved to the new version",
            challenge.active_proposal_id == versions[1].id)
    _assert("§7: a counter cannot change the mode",
            challenge.challenge_mode == "locked", challenge.challenge_mode)


# ══ §14 · exact money on every transition ═══════════════════════════════════

_section("§14 · exact money consequences")

before_issue = money(A)
_assert("§14: the counter moved NO money",
        before_issue["held"] == 2_000,
        f"held {before_issue['held']} — still the issued Anchor only")

before_accept_a, before_accept_b = money(A), money(B)
status, accepted = gm_a.request("POST", "/beef/respond",
                                {"challenge_id": CH, "accept": True})
_assert("§8: the original issuer accepts the counter", status == 200,
        str(accepted)[:200])
after_accept_a, after_accept_b = money(A), money(B)

_assert("§8: accepted Bet rows exist",
        accepted["anchor_bet_id"] and accepted["derived_bet_id"])
_assert("§14: Held drops by exactly the escrow that migrated",
        after_accept_a["held"] == before_accept_a["held"] - 2_000,
        f"{before_accept_a['held']} → {after_accept_a['held']}")
_assert("§14: the issuer topped up to the accepted Anchor",
        after_accept_a["spendable"] == before_accept_a["spendable"] - 600,
        f"{before_accept_a['spendable']} → {after_accept_a['spendable']} "
        f"(2000 escrowed, 2600 accepted)")
_assert("§14: the recipient funded their Derived stake",
        after_accept_b["spendable"] == before_accept_b["spendable"] - 2_600,
        f"{before_accept_b['spendable']} → {after_accept_b['spendable']}")
_assert("§14: In Play reflects the accepted wager",
        after_accept_a["in_play"] == 2_600,
        str(after_accept_a["in_play"]))
_assert("§14: the ledger balances", after_accept_a["trial_balance"] == 0)

_assert("§8: the accepted wager is LIVE for both GMs",
        counts(gm_a)["live"] == 1 and counts(gm_b)["live"] == 1,
        f"A {counts(gm_a)}, B {counts(gm_b)}")
live_card = card_for(gm_a, CH)
_assert("§8: and offers no controls — it is no longer a decision",
        live_card["controls"] == [] and live_card["status"] == "Accepted")


# ══ §9 · decline ════════════════════════════════════════════════════════════

_section("§9 · decline releases escrow and leaves the open sections")

before_decline = money(A)
status, second = gm_a.request("POST", "/beef/challenge", {
    "challenger_team_id": A, "challenged_team_id": B, "week": WEEK,
    "bet_type": "straight", "amount": 12.00,
})
assert status == 201, second
CH2 = second["challenge_id"]
mid = money(A)
_assert("§14: issuing escrowed exactly the stake",
        mid["held"] == before_decline["held"] + 1_200
        and mid["spendable"] == before_decline["spendable"] - 1_200,
        f"held +{mid['held'] - before_decline['held']}, "
        f"spendable {before_decline['spendable']} → {mid['spendable']}")

status, declined = gm_b.request("POST", "/beef/respond",
                                {"challenge_id": CH2, "accept": False})
_assert("§9: the recipient declines", status == 200, str(declined)[:160])
after_decline = money(A)

_assert("§14: Held falls back by exactly the declined stake",
        after_decline["held"] == before_decline["held"],
        f"{mid['held']} → {after_decline['held']}")
_assert("§14: and spendable is exactly restored",
        after_decline["spendable"] == before_decline["spendable"],
        f"{mid['spendable']} → {after_decline['spendable']}")
_assert("§14: Current Settle is unchanged across issue→decline",
        after_decline["current_settle"] == before_decline["current_settle"])
_assert("§14: the ledger balances", after_decline["trial_balance"] == 0)

declined_card = card_for(gm_a, CH2)
_assert("§9: the declined wager left the open sections",
        declined_card["section"] == "completed", declined_card["section"])
_assert("§9: it reads as Declined", declined_card["status"] == "Declined")
_assert("§9: and offers no controls", declined_card["controls"] == [])

status, again = gm_b.request("POST", "/beef/respond",
                             {"challenge_id": CH2, "accept": True})
_assert("§9: a declined wager cannot subsequently be accepted",
        status in (400, 409) or (status == 200 and again.get("replayed")),
        f"status {status}: {again}")
_assert("§9: and nothing moved when it was refused",
        money(A)["held"] == after_decline["held"])


# ══ §4 · Dynamic over HTTP ══════════════════════════════════════════════════

_section("§4 · Dynamic exposed through the governing lifecycle")

before_dyn = money(A)
status, dynamic = gm_a.request("POST", "/beef/challenge", {
    "challenger_team_id": A, "challenged_team_id": B, "week": WEEK,
    "bet_type": "straight", "amount": 30.00, "challenge_mode": "dynamic",
})
_assert("§4: a DYNAMIC challenge can be issued over HTTP", status == 201,
        str(dynamic)[:200])
assert status == 201, dynamic
DYN = dynamic["challenge_id"]

with SessionLocal() as db:
    ch = db.query(BeefChallenge).filter(BeefChallenge.id == DYN).one()
    proposal = (db.query(BeefProposal)
                .filter(BeefProposal.id == ch.active_proposal_id).one())
    _assert("§4: it is stored as Dynamic", ch.challenge_mode == "dynamic",
            ch.challenge_mode)
    _assert("§4: the proposal froze real win probabilities",
            proposal.anchor_win_probability is not None
            and proposal.derived_win_probability is not None,
            f"{proposal.anchor_win_probability}, "
            f"{proposal.derived_win_probability}")
    _assert("§4: the two probabilities are complementary — one simulation",
            abs((proposal.anchor_win_probability
                 + proposal.derived_win_probability) - 1.0) < 1e-9)
    _assert("§4: the Derived stake is NOT quoted — it prices at Final Lock",
            proposal.quoted_derived_stake_cents is None,
            str(proposal.quoted_derived_stake_cents))

dyn_card = card_for(gm_b, DYN)
_assert("§4: the card reports the mode from the backend",
        dyn_card["mode"] == "dynamic", dyn_card["mode"])
_assert("§4: and no Derived stake before the Handshake",
        dyn_card["their_stake_cents"] is None
        or dyn_card["your_stake_cents"] == 0,
        f"your {dyn_card['your_stake_cents']}, "
        f"their {dyn_card['their_stake_cents']}")

after_dyn_issue = money(A)
_assert("§14: the Dynamic Anchor escrowed exactly like a Locked one",
        after_dyn_issue["held"] == before_dyn["held"] + 3_000,
        f"{before_dyn['held']} → {after_dyn_issue['held']}")

status, handshake = gm_b.request("POST", "/beef/respond",
                                 {"challenge_id": DYN, "accept": True})
_assert("§4: accepting a Dynamic challenge runs the HANDSHAKE", status == 200,
        str(handshake)[:220])
_assert("§4: the response carries the governed ceilings",
        isinstance(handshake.get("opponent_ceiling_cents"), int)
        and isinstance(handshake.get("issuer_ceiling_cents"), int),
        f"issuer {handshake.get('issuer_ceiling_cents')}, "
        f"opponent {handshake.get('opponent_ceiling_cents')}")
_assert("§4: and the backend's model version, not a client string",
        bool(handshake.get("model_version_id")),
        str(handshake.get("model_version_id")))
_assert("§4: the issuer's Anchor is FIXED at what they staked",
        handshake["issuer_ceiling_cents"] == 3_000,
        str(handshake["issuer_ceiling_cents"]))
_assert("§4: the Derived side is the one that may move",
        handshake["opponent_ceiling_cents"] != handshake["issuer_ceiling_cents"],
        f"opponent ceiling {handshake['opponent_ceiling_cents']}")
_assert("§4: NO Bet rows yet — Final Lock creates them",
        handshake.get("anchor_bet_id") is None
        and handshake.get("derived_bet_id") is None)

with SessionLocal() as db:
    ch = db.query(BeefChallenge).filter(BeefChallenge.id == DYN).one()
    _assert("§4: the handshake was recorded on the challenge",
            ch.dynamic_handshake_at is not None)
    _assert("§4: the ceilings were persisted by the lifecycle",
            ch.dynamic_opponent_ceiling_cents
            == handshake["opponent_ceiling_cents"])

dyn_card = card_for(gm_a, DYN)
_assert("§4: the Dynamic wager is now LIVE", dyn_card["section"] == "live",
        dyn_card["section"])
_assert("§4: the card reports the ceiling the BACKEND wrote",
        dyn_card["derived_ceiling_cents"]
        == handshake["opponent_ceiling_cents"],
        str(dyn_card["derived_ceiling_cents"]))
_assert("§4: and marks it as repriced-at-lock",
        dyn_card["derived_repriced"] is True)

# NO DYNAMIC FORMULA IN THE API OR THE UI. Named internals rather than a vague
# word scan: these are the symbols that WOULD have to appear if any layer were
# reproducing the pricing, and the ceiling itself is already proven to arrive
# byte-equal from the backend above.
_api_src = open(os.path.join(ROOT, "api", "main.py"), encoding="utf-8").read()
_cmd_src = open(os.path.join(ROOT, "web", "js", "action-command.js"),
                encoding="utf-8").read()
_ui_src = open(os.path.join(ROOT, "web", "js", "action.js"),
               encoding="utf-8").read()
PRICING_INTERNALS = ("_run_official_simulation", "RefreshQuote", "p_issuer",
                     "p_opponent", "derived_raw_cents", "_signed_american",
                     "simulate_scores")
for name, src in (("api/main.py", _api_src),
                  ("action-command.js", _cmd_src),
                  ("action-model.js", _model_src),
                  ("action.js", _ui_src)):
    leaked = [sym for sym in PRICING_INTERNALS if sym in src]
    _assert(f"§4: {name} reproduces no Dynamic pricing internals",
            not leaked, f"leaked: {leaked}" if leaked else "carried, not computed")

_assert("§14: the ledger balances after the Handshake",
        money(A)["trial_balance"] == 0)


# ══ §3 · counts come from bound state ═══════════════════════════════════════

_section("§3 · authoritative counts")

a_counts = counts(gm_a)
_, a_body = action(gm_a)
_assert("§3: every count equals the number of cards served for it",
        all(a_counts[name] == len(a_body["sections"][name])
            for name in a_counts), str(a_counts))
_assert("§3: the illustrative 2 / 2 / 4 is not what production reports",
        (a_counts["action"], a_counts["waiting"], a_counts["live"])
        != (2, 2, 4), str(a_counts))
_assert("§3: A now holds two LIVE wagers", a_counts["live"] == 2,
        str(a_counts))


# ══ §13 · authorization on the command paths ════════════════════════════════

_section("§13 · authorization")

status, _ = comm_c.request("POST", "/beef/challenge", {
    "challenger_team_id": A, "challenged_team_id": B, "week": WEEK,
    "bet_type": "straight", "amount": 5.00,
})
_assert("§13: a commissioner cannot issue as another GM", status == 403,
        f"status {status}")

status, _ = gm_b.request("POST", "/beef/challenge", {
    "challenger_team_id": A, "challenged_team_id": B, "week": WEEK,
    "bet_type": "straight", "amount": 5.00,
})
_assert("§13: a GM cannot issue as another GM", status == 403, f"status {status}")

status, c_own = comm_c.request("POST", "/beef/challenge", {
    "challenger_team_id": C, "challenged_team_id": A, "week": WEEK,
    "bet_type": "straight", "amount": 15.00,
})
_assert("§13: a commissioner CAN wager for their own team", status == 201,
        f"status {status}: {str(c_own)[:140]}")
C_CH = c_own["challenge_id"] if status == 201 else None

status, _ = gm_b.request("POST", "/beef/respond",
                         {"challenge_id": C_CH, "accept": True})
_assert("§13: the wrong recipient cannot respond", status == 403,
        f"status {status}")

status, _ = gm_f.request("GET", f"/league/{LEAGUE}/action/me")
_assert("§13: a GM outside the league gets no Action state", status == 403,
        f"status {status}")

status, _ = gm_a.request("POST", "/beef/challenge", {
    "challenger_team_id": A, "challenged_team_id": F, "week": WEEK,
    "bet_type": "straight", "amount": 5.00,
})
_assert("§13: cross-league action is denied", status == 400, f"status {status}")

status, _ = gm_a.request("GET", f"/beef/pending/{B}")
_assert("§13: another GM's personal queue is refused", status == 403,
        f"status {status}")

# CSRF, on a cookie-authenticated command.
status, _ = gm_a.request("POST", "/beef/challenge", {
    "challenger_team_id": A, "challenged_team_id": B, "week": WEEK,
    "bet_type": "straight", "amount": 5.00,
}, csrf=False)
_assert("§13: a cookie command without CSRF is refused", status == 403,
        f"status {status}")

anon = Client(None)
status, _ = anon.request("GET", f"/league/{LEAGUE}/action/me")
_assert("§13: an unauthenticated read is refused", status in (401, 403),
        f"status {status}")

_assert("§13: no refused command moved money",
        money(A)["trial_balance"] == 0)


# ══ §15 · production-vs-demo audit ══════════════════════════════════════════

_section("§15 · Action production-vs-demo audit")

_shell_src = open(os.path.join(ROOT, "web", "js", "shell.js"),
                  encoding="utf-8").read()
_action_src = open(os.path.join(ROOT, "web", "js", "action.js"),
                   encoding="utf-8").read()

# The illustrative fixture may still be IMPORTED — the component suites are its
# only consumer and they are legitimate. What it may not do is reach a bound
# surface, which is what `sectionCards` short-circuits.
_assert("§15: action.js draws rails from the MODEL, not the fixture",
        "railBody(rail)" in _action_src and "sectionCards" in _action_src,
        "cardsFor is no longer the rail source")
_assert("§15: the model returns [] rather than demo cards when unavailable",
        "if (MODE !== ACTION_MODE_AUTHORITATIVE || !SERVED) return [];"
        in _model_src)
_assert("§15: a failed read marks unavailable, never demo",
        "markActionUnavailable()" in _shell_src
        and "unbindAction" in _shell_src,
        "unbind is sign-out only")
_assert("§15: the commands are installed only when the read bound",
        "setIssueHook(null)" in _shell_src
        and "setRespondHook(null)" in _shell_src)


# ══ §12 · loading / empty / error are distinct ══════════════════════════════

_section("§12 · empty, unavailable and demo are three different things")

_assert("§12: the model names three modes",
        all(m in _model_src for m in
            ("ACTION_MODE_DEMO", "ACTION_MODE_AUTHORITATIVE",
             "ACTION_MODE_UNAVAILABLE")))
_assert("§12: an empty bound state is reported as empty, not unavailable",
        "export function actionIsEmpty()" in _model_src)
_assert("§12: the rail draws distinct states",
        'data-rail-state="unavailable"' in _action_src
        and 'data-rail-state="empty"' in _action_src)

status, empty_body = action(gm_empty)
_assert("§12: the empty GM still reads successfully", status == 200)
_assert("§12: and genuinely has nothing",
        all(v == 0 for v in empty_body["counts"].values()),
        str(empty_body["counts"]))

# ══ P4C-2R · the illustrative authority seams ═══════════════════════════════

_section("P4C-2R · no illustrative value carries authority")

_composer_src = open(os.path.join(ROOT, "web", "js", "composer.js"),
                     encoding="utf-8").read()
_components_src = open(os.path.join(ROOT, "web", "js", "components.js"),
                       encoding="utf-8").read()
_action_ui = open(os.path.join(ROOT, "web", "js", "action.js"),
                  encoding="utf-8").read()


def _code_only(js: str) -> str:
    """A JS source with its comments removed.

    BECAUSE THE PROSE EXPLAINS WHAT WAS REMOVED. Both repairs below are
    documented at their sites, and those comments quote the exact strings the
    assertions look for — so a plain substring scan reports the fix as absent
    and fails for the reason it was written to catch. This is the same false
    negative P4B corrected by moving its Python scans onto the AST; there is no
    JS parser here, so comments are stripped instead.

    Deliberately conservative: block comments go, and so do lines whose first
    non-space characters begin a line comment. An inline `//` after code is left
    alone rather than risk cutting a string that contains one.
    """
    out, i, n = [], 0, len(js)
    while i < n:
        if js.startswith("/*", i):
            end = js.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        line_end = js.find(chr(10), i)
        if line_end == -1:
            line_end = n
        line = js[i:line_end]
        if not line.lstrip().startswith(("//", "*")):
            out.append(line)
        i = line_end + 1
    return chr(10).join(out)


_action_code = _code_only(_action_ui)
_components_code = _code_only(_components_src)

# §1 — THE NAME BRIDGE IS GONE, structurally. A repair that only removed the
# call site would leave the helper behind for the next caller to find.
_assert("P4C-2R: no module resolves an opponent from display text",
        "team_name ===" not in _shell_src
        and "resolveOpponentTeamId" not in _shell_src
        and "team_name ===" not in _composer_src,
        "no name-based authority bridge remains")

# §2 — AND THE ONLY WAY IN IS BY SERVED ID. `selectOpponent` refuses an id that
# is not in the served list, which makes the property structural rather than a
# matter of every caller behaving.
_assert("P4C-2R: the composer accepts a target only from the served list",
        "is not an authoritative opponent" in _composer_src
        and "session.opponents.find((o) => o.team_id === teamId)"
        in _composer_src)
_assert("P4C-2R: and a handed-in id is validated against that list too",
        "opponents.some((o) => o.team_id === spec.opponentTeamId)"
        in _composer_src,
        "an unlisted id is treated as absent, never trusted")

# §4 — the season record. Both halves: gone in production, kept in demo.
_assert("P4C-2R: the COMPLETED heading drops the record outside demo",
        "actionMode() === 'demo'" in _action_ui and "'COMPLETED'" in _action_ui)
_assert("P4C-2R: and the locked Rev 4.2 heading survives IN demo",
        "COMPLETED \u00b7 ${seasonRecordLabel()} SEASON" in _action_ui)

# §5 — the strip. The leak was never only 14-7: all four cells were computed
# from the illustrative CARDS and shown to signed-in GMs as their own money.
_assert("P4C-2R: every Action strip cell is unresolved outside demo",
        _action_ui.count("pending: unresolved") >= 4,
        f"{_action_ui.count('pending: unresolved')} cells marked")

# AND `pending` NOW MEANS ONE THING. Season Bet Record was the first pending
# cell carrying `text`, and the shared component printed it — struck through as
# unresolved while still showing the number.
_assert("P4C-2R: a pending strip cell draws the unresolved figure, never its text",
        "valueHtml = PENDING_FIGURE;" in _components_code
        and "cell.text || PENDING_FIGURE" not in _components_code)

# §5 — the tab header asserted a week it could not know.
_assert("P4C-2R: the Action header asserts no week outside demo",
        "'REGULAR SEASON ACTION'" in _action_ui
        and "export function actionHeader()" in _action_ui)

# §6 — the Final Lock wording.
_assert("P4C-2R: Action's Dynamic copy no longer says 'at kickoff'",
        "re-priced at kickoff" not in _action_code)
_assert("P4C-2R: and names the earliest covered kickoff in plain words",
        "first of your players takes the field" in _action_ui,
        "GE-901: Final Lock precedes the EARLIEST covered kickoff")



print("\n" + "=" * 74)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4C-2 ACTION — all assertions PASSED")
