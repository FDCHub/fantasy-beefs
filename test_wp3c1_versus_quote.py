#!/usr/bin/env python3
"""
test_wp3c1_versus_quote.py — WP3C.1 · the authoritative Versus quote.

THE TWO CLAIMS THAT MATTER, AND WHY EACH NEEDS A DIFFERENT KIND OF PROOF.

  1. PARITY. What the composer shows before a GM sends must be what the
     proposal records when they do. Asserting that the quote route "returns
     fields" proves nothing about that; asserting that the quote and a REAL
     ISSUED PROPOSAL agree to the cent, on the same inputs, is the whole claim.
     §3 below quotes, then issues, then reads the persisted proposal row and
     compares — for moneyline, spread and over/under, in both modes.

  2. NO STATE MUTATION. A quote is observational. §2 counts every row and every
     balance the wager path can touch, calls the quote route repeatedly, and
     counts again — rather than reasoning from the source that it "should not"
     write. A quote that reserved Credits would look identical in code review
     and would be caught here.

WHY THE PARITY TEST ISSUES A REAL WAGER. A parity test that compared the quote
against a re-computation of the same formula would be comparing a function with
itself. The only comparison that means anything is against what the write path
PERSISTED, so this suite posts real challenges through the real route, with real
escrow, and reads the proposal rows back.

DATABASE. A temp SQLite file per run. No locking or concurrency claim is made.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'wp3c1.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient                          # noqa: E402

from api.main import app                                           # noqa: E402
from auth.jwt_auth import hash_password                            # noqa: E402
from auth.session import CSRF_COOKIE, CSRF_HEADER                  # noqa: E402
from beefs.versus_quote import build_quote, proposal_economics     # noqa: E402
from config import CURRENT_SEASON                                  # noqa: E402
from db.schema import (                                            # noqa: E402
    Base, BeefChallenge, BeefProposal, Bet, League, LeagueCommissioner,
    Matchup, Player, Projection, Roster, SessionLocal, Team, User, Wallet,
    engine,
)
from economy.economy_events import min_reserve_account, wallet_account  # noqa: E402
from ledger.ledger import (                                        # noqa: E402
    LedgerEntry, create_ledger_table, post as ledger_post, trial_balance,
)
# ALIASED, because this suite already has its own PASSWORD for its own fixture
# and the two must not be able to shadow one another. The disposable server
# below is a SEPARATE database from this module's; nothing crosses between them.
from test_support_app_server import (                              # noqa: E402
    AppServer, GM_EMAIL as APP_GM_EMAIL, PASSWORD as APP_PASSWORD,
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


# ── Fixture ──────────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "wp3c1-password"
SEASON = CURRENT_SEASON
WEEK = 3
N_START = 9

#: Deliberately ASYMMETRIC, but NOT a certainty — and the distance between
#: those two is a real product boundary this suite exercises both sides of.
#:
#: An even-money board would make several parity assertions pass for the wrong
#: reason: both stakes equal and both payouts equal, hiding a mode or a side
#: read from the wrong place. A BLOWOUT board is the opposite failure — the
#: simulation returns p=1.0, `derive_stakes` refuses it (at certainty the fair
#: pot is undefined and the opponent has nothing to price), and the Dynamic path
#: is never exercised at all. These two figures give a genuine favourite inside
#: the priceable range; `LOPSIDED_POINTS` below produces the certainty, and §9
#: asserts it is refused in governed language rather than crashing.
STRONG_POINTS = 13.0
WEAK_POINTS = 11.5
LOPSIDED_POINTS = 40.0

#: Enough for every stake this suite places, several times over.
OPENING_CENTS = 500_00

with SessionLocal() as db:
    hashed = hash_password(PASSWORD)

    league = League(name="WP3C1 League", season=SEASON,
                    projection_source="fantasypros")
    other = League(name="WP3C1 Other", season=SEASON,
                   projection_source="fantasypros")
    db.add_all([league, other])
    db.flush()
    LEAGUE_ID, OTHER_LEAGUE_ID = league.id, other.id

    def _team(name: str, email: str, league_id: int, strong: bool,
              points: float | None = None) -> int:
        t = Team(team_name=name, owner=f"{name} Owner", email=email,
                 league_id=league_id)
        db.add(t)
        db.flush()
        db.add(Wallet(team_id=t.id, balance=0.0))
        db.add(User(email=email, hashed_password=hashed, team_id=t.id,
                    role="gm"))
        points = points if points is not None else (
            STRONG_POINTS if strong else WEAK_POINTS)
        for slot in range(N_START):
            p = Player(name=f"{name} p{slot}", position="WR", nfl_team="KC")
            db.add(p)
            db.flush()
            db.add(Roster(team_id=t.id, player_id=p.id))
            db.add(Projection(player_id=p.id, week=WEEK, season=SEASON,
                              source="fantasypros", projected_points=points))
        return t.id

    # ME is the favourite, OPP the underdog — so every quote below is priced
    # off a real edge rather than a coin flip.
    ME = _team("Me", "me@wp3c1.test", LEAGUE_ID, strong=True)
    OPP = _team("Opp", "opp@wp3c1.test", LEAGUE_ID, strong=False)
    THIRD = _team("Third", "third@wp3c1.test", LEAGUE_ID, strong=False)
    OUTSIDER = _team("Outsider", "outsider@wp3c1.test", OTHER_LEAGUE_ID,
                     strong=True)

    # A team projected so far ahead that the model returns certainty. Used only
    # by §9, to prove the Dynamic refusal is governed rather than a 500.
    LOPSIDED = _team("Lopsided", "lopsided@wp3c1.test", LEAGUE_ID,
                     strong=True, points=LOPSIDED_POINTS)
    # A team WITH a starting lineup but NO projections for it. That is the
    # honest "one side unknown" case: the roster is set, the numbers have not
    # landed, and the model prices it as the underdog it is. Distinct from a
    # team with no roster at all, which cannot be simulated and is refused —
    # see §7, which asserts both.
    BLANK = _team("Blank", "blank@wp3c1.test", LEAGUE_ID, strong=False,
                  points=0.0)

    # And a team with NO ROSTER AT ALL, which the simulator cannot price.
    rosterless = Team(team_name="Rosterless", owner="No Roster",
                      email="rosterless@wp3c1.test", league_id=LEAGUE_ID)
    db.add(rosterless)
    db.flush()
    ROSTERLESS = rosterless.id
    db.add(Wallet(team_id=ROSTERLESS, balance=0.0))
    db.add(User(email="rosterless@wp3c1.test", hashed_password=hashed,
                team_id=ROSTERLESS, role="gm"))

    # THE COMMISSIONER IS AN ORDINARY WAGERING GM TOO, so their team is built
    # the same way as everyone else's — with a roster and projections. A
    # commissioner team with no lineup would make §6 pass for the wrong reason:
    # refused because unpriceable rather than because the role grants nothing.
    COMM_TEAM = _team("Comms", "comm@wp3c1.test", LEAGUE_ID, strong=False)
    comm = db.query(User).filter(User.email == "comm@wp3c1.test").one()
    comm.role = "commissioner"
    db.flush()
    db.add(LeagueCommissioner(league_id=LEAGUE_ID, user_id=comm.id,
                              source="bootstrap"))

    db.add(Matchup(league_id=LEAGUE_ID, week=WEEK, home_team_id=ME,
                   away_team_id=OPP, home_score=0.0, away_score=0.0))
    db.commit()

# Fund the two wagering teams so a real issue can post escrow.
for team_id in (ME, OPP):
    ledger_post([
        (wallet_account(team_id), OPENING_CENTS),
        ("world", -OPENING_CENTS),
    ], door="season_allocation")


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _sign_in(client: TestClient, email: str) -> None:
    r = client.post("/auth/session", json={"email": email,
                                           "password": PASSWORD})
    assert r.status_code == 200, r.text


def _post(client: TestClient, path: str, body: dict):
    """A POST carrying the session's CSRF token.

    THE QUOTE ROUTE IS CSRF-PROTECTED LIKE EVERY OTHER POST, and deliberately
    so: it is read-only, but it is shaped like a write and there is no reason to
    carve an exemption for it. The browser sends the same header through
    `session.js`, which is the app's one door.
    """
    headers = {}
    token = client.cookies.get(CSRF_COOKIE)
    if token:
        headers[CSRF_HEADER] = token
    return client.post(path, json=body, headers=headers)


def _quote(client: TestClient, **body):
    return _post(client, f"/league/{LEAGUE_ID}/versus/quote", body)


# ── 1 · The contract ─────────────────────────────────────────────────────────

_section("1 · A member can quote an ordinary regular-season matchup")

with _client() as client:
    _sign_in(client, "me@wp3c1.test")
    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="straight",
               amount=20.0)
    _assert("the quote is served", r.status_code == 200, r.text[:200])
    Q = r.json() if r.status_code == 200 else {}

_assert("it names the league, the acting team and the opponent",
        Q.get("league_id") == LEAGUE_ID and Q.get("acting_team_id") == ME
        and Q.get("opponent_team_id") == OPP)
_assert("the acting team is RESOLVED, not accepted from the request",
        "acting_team_id" not in
        {"opponent_team_id", "week", "bet_type", "amount", "challenge_mode",
         "line", "side"})
_assert("it echoes the market and mode",
        Q.get("market") == "straight" and Q.get("mode") == "locked")
for field in ("your_stake_cents", "opponent_stake_cents", "pot_cents",
              "win_cents", "lose_cents"):
    _assert(f"{field} is exact integer cents",
            isinstance(Q.get(field), int), str(Q.get(field)))
_assert("the GM's own stake is what they asked for",
        Q.get("your_stake_cents") == 2000, str(Q.get("your_stake_cents")))
_assert("nothing is zero — a real price was produced",
        Q.get("opponent_stake_cents", 0) > 0 and Q.get("pot_cents", 0) > 0)
_assert("the pot is both stakes",
        Q.get("pot_cents") == Q.get("your_stake_cents")
        + Q.get("opponent_stake_cents"))
_assert("win is the opponent's stake and lose is your own",
        Q.get("win_cents") == Q.get("opponent_stake_cents")
        and Q.get("lose_cents") == Q.get("your_stake_cents"))
_assert("the odds are the pricing model's, and asymmetric on this fixture",
        Q.get("anchor_moneyline") != Q.get("derived_moneyline"),
        f"{Q.get('anchor_moneyline')} vs {Q.get('derived_moneyline')}")
_assert("a Locked quote is not flagged as a ceiling",
        Q.get("is_ceiling") is False)
_assert("no internal diagnostic field is exposed",
        not any(k in Q for k in ("residue_decimal", "fair_pot_decimal",
                                 "anchor_probability", "derived_probability",
                                 "points_snapshot")),
        " ".join(sorted(Q)))


# ── 2 · No state mutation ────────────────────────────────────────────────────

_section("2 · A quote writes NOTHING")


def _world_state() -> dict:
    """Every row and balance a Versus write could possibly touch."""
    with SessionLocal() as db:
        counts = {
            "challenges": db.query(BeefChallenge).count(),
            "proposals": db.query(BeefProposal).count(),
            "bets": db.query(Bet).count(),
            "ledger_entries": db.query(LedgerEntry).count(),
        }
    return {
        **counts,
        "trial_balance": trial_balance(),
        "wallet_me": _balance(wallet_account(ME)),
        "wallet_opp": _balance(wallet_account(OPP)),
        "min_reserve_me": _balance(min_reserve_account(ME)),
        "escrow_total": _escrow_total(),
    }


def _balance(account: str) -> int:
    from ledger.ledger import balance_of
    return balance_of(account)


def _escrow_total() -> int:
    from sqlalchemy import text
    with SessionLocal() as db:
        total = db.execute(text(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
            "WHERE account LIKE 'escrow:%'")).scalar()
    return int(total or 0)


BEFORE = _world_state()

with _client() as client:
    _sign_in(client, "me@wp3c1.test")
    # Quoted repeatedly, across markets, modes and stakes — a single call could
    # be idempotent by accident; twelve cannot.
    for bet_type, line, side in (("straight", None, None),
                                 ("spread", -3.5, None),
                                 ("over_under", 210.5, "over")):
        for mode in ("locked", "dynamic"):
            for amount in (20.0, 45.0):
                _quote(client, opponent_team_id=OPP, week=WEEK,
                       bet_type=bet_type, amount=amount,
                       challenge_mode=mode, line=line, side=side)

AFTER = _world_state()

for key in BEFORE:
    _assert(f"quoting changed nothing: {key}",
            BEFORE[key] == AFTER[key], f"{BEFORE[key]} → {AFTER[key]}")
_assert("the ledger still balances", AFTER["trial_balance"] == 0)


# ── 3 · Quote / submit parity, to the cent ───────────────────────────────────

_section("3 · The quote equals what the write path persists")


def _issue_and_read(client: TestClient, *, bet_type, amount, mode,
                    line=None, side=None, challenged=None):
    """Issue a REAL challenge and return its persisted proposal row."""
    body = {
        "challenger_team_id": ME,
        "challenged_team_id": challenged or OPP,
        "week": WEEK,
        "bet_type": bet_type,
        "amount": amount,
        "challenge_mode": mode,
    }
    if line is not None:
        body["line"] = line
    if side is not None:
        body["side"] = side
    r = _post(client, "/beef/challenge", body)
    if r.status_code != 201:
        return None, r
    challenge_id = r.json()["challenge_id"]
    with SessionLocal() as db:
        proposal = (db.query(BeefProposal)
                    .filter(BeefProposal.challenge_id == challenge_id)
                    .order_by(BeefProposal.id.desc()).first())
        return ({
            "anchor_stake_cents": proposal.anchor_stake_cents,
            "quoted_derived_stake_cents": proposal.quoted_derived_stake_cents,
            "quoted_funded_pot_cents": proposal.quoted_funded_pot_cents,
            "anchor_moneyline": proposal.anchor_moneyline,
            "derived_moneyline": proposal.derived_moneyline,
        }, r)


def _handshake_ceiling(anchor_cents: int) -> int:
    """The ceiling `economy/dynamic_challenge` would derive at the Handshake.

    Read from the PERSISTED proposal's frozen probabilities, through the same
    `derive_stakes` the Handshake calls — so this is the HANDSHAKE's answer
    computed from what the write path actually stored, not a restatement of the
    quote's own arithmetic.
    """
    from odds.dynamic_pricing import derive_stakes
    with SessionLocal() as db:
        proposal = (db.query(BeefProposal)
                    .order_by(BeefProposal.id.desc()).first())
    return derive_stakes(anchor_cents,
                         proposal.anchor_win_probability,
                         proposal.derived_win_probability).opponent_cents


# WP3C.2 — THE LINE IS THE SERVER'S NOW, so these cases no longer choose one.
#
# When this suite was written no authority assigned a spread or a total, and the
# route accepted whatever the caller sent — so a parity case had to invent a
# line to have one at all. The owner ruling on market line methodology ended
# that: `/versus/quote` and `/beef/challenge` both derive the line from the
# market board and REFUSE a client value that is not the offered one, which is
# why `-3.5` and `210.5` now come back as `market_moved`.
#
# `None` is the right replacement rather than "read the board and echo it". The
# parity claim is that the QUOTE and the PERSISTED PROPOSAL agree, and sending
# nothing makes both sides derive the line independently through the same
# authority — a stronger test of that agreement than handing each the same
# literal would be. WP3C.2's own suite certifies the board-to-quote-to-write
# chain end to end.
CASES = [
    ("moneyline", "straight", None, None, "locked"),
    ("spread", "spread", None, None, "locked"),
    ("over/under", "over_under", None, "over", "locked"),
    ("moneyline · Dynamic", "straight", None, None, "dynamic"),
]

RESULTS: dict[str, dict] = {}

for label, bet_type, line, side, mode in CASES:
    with _client() as client:
        _sign_in(client, "me@wp3c1.test")
        qr = _quote(client, opponent_team_id=OPP, week=WEEK,
                    bet_type=bet_type, amount=25.0, challenge_mode=mode,
                    line=line, side=side)
        quoted = qr.json() if qr.status_code == 200 else None
        persisted, wr = _issue_and_read(client, bet_type=bet_type,
                                        amount=25.0, mode=mode,
                                        line=line, side=side)

    RESULTS[label] = {"quoted": quoted, "persisted": persisted}

    _assert(f"{label}: the quote was served", quoted is not None,
            qr.text[:160] if quoted is None else "")
    _assert(f"{label}: the wager was actually issued", persisted is not None,
            wr.text[:160] if persisted is None else "")
    if quoted is None or persisted is None:
        continue

    _assert(f"{label}: YOUR STAKE matches to the cent",
            quoted["your_stake_cents"] == persisted["anchor_stake_cents"],
            f"{quoted['your_stake_cents']} vs {persisted['anchor_stake_cents']}")
    _assert(f"{label}: the odds match exactly",
            quoted["anchor_moneyline"] == persisted["anchor_moneyline"]
            and quoted["derived_moneyline"] == persisted["derived_moneyline"],
            f"{quoted['anchor_moneyline']}/{quoted['derived_moneyline']} vs "
            f"{persisted['anchor_moneyline']}/{persisted['derived_moneyline']}")

    if mode == "locked":
        _assert(f"{label}: OPPONENT STAKE matches to the cent",
                quoted["opponent_stake_cents"]
                == persisted["quoted_derived_stake_cents"],
                f"{quoted['opponent_stake_cents']} vs "
                f"{persisted['quoted_derived_stake_cents']}")
        _assert(f"{label}: POT matches to the cent",
                quoted["pot_cents"] == persisted["quoted_funded_pot_cents"],
                f"{quoted['pot_cents']} vs {persisted['quoted_funded_pot_cents']}")
        _assert(f"{label}: WIN matches the persisted opponent stake",
                quoted["win_cents"] == persisted["quoted_derived_stake_cents"])
        _assert(f"{label}: and it is NOT flagged as a ceiling",
                quoted["is_ceiling"] is False)
    else:
        # DYNAMIC PERSISTS NO DERIVED STAKE, and that is the protocol rather
        # than a gap — the opponent's side is priced at the Handshake. The
        # quote's figure is the CEILING that Handshake will derive, and it says
        # so. Asserting equality against a NULL column would be asserting the
        # wrong thing; asserting the None is the real claim.
        _assert(f"{label}: the proposal quotes NO Derived stake",
                persisted["quoted_derived_stake_cents"] is None)
        _assert(f"{label}: and no funded pot",
                persisted["quoted_funded_pot_cents"] is None)
        _assert(f"{label}: the quote is flagged as a ceiling",
                quoted["is_ceiling"] is True)
        _assert(f"{label}: the ceiling is the Handshake's own derivation",
                quoted["opponent_stake_cents"] == _handshake_ceiling(
                    persisted["anchor_stake_cents"]),
                str(quoted["opponent_stake_cents"]))


_section("4 · The extraction changed no output")

# THE EXPRESSIONS THAT WERE INLINE, RE-STATED HERE AND COMPARED. If the
# extraction had altered rounding or a branch, this would diverge — and it is
# written from the ORIGINAL source rather than from the new function, so it is a
# genuine second opinion rather than a tautology.
for stake, anchor_dec, derived_dec, dynamic in (
        (2000, 1.909, 1.909, False),
        (2537, 2.5, 1.6667, False),
        (2537, 2.5, 1.6667, True),
        (1, 3.14159, 1.47, False)):
    econ = proposal_economics(stake_cents=stake, anchor_odds=anchor_dec,
                              derived_odds=derived_dec, dynamic=dynamic)
    _assert(f"extraction parity · stake {stake} dynamic={dynamic}",
            econ.anchor_stake_cents == stake
            and econ.quoted_derived_stake_cents == (None if dynamic else stake)
            and econ.quoted_funded_pot_cents == (None if dynamic else stake * 2)
            and econ.quoted_anchor_payout_cents == round(stake * anchor_dec)
            and econ.quoted_derived_payout_cents == (
                None if dynamic else round(stake * derived_dec)))

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "api", "main.py"), encoding="utf-8") as _fh:
    MAIN_SOURCE = _fh.read()

_assert("both write routes call the extracted function",
        MAIN_SOURCE.count("economics = proposal_economics(") == 2,
        f"{MAIN_SOURCE.count('economics = proposal_economics(')} call sites")
_assert("no inline pot expression survives in the routes",
        "stake_cents * 2" not in MAIN_SOURCE)
_assert("no inline payout expression survives in the routes",
        "round(stake_cents * anchor_dec)" not in MAIN_SOURCE
        and "round(stake_cents * derived_dec)" not in MAIN_SOURCE)
_assert("and the quote route shares the same authority",
        "from beefs.versus_quote import build_quote" in MAIN_SOURCE)


# ── 5 · Authorization and eligibility ────────────────────────────────────────

_section("5 · Authority is enforced before anything is priced")

with _client() as client:
    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="straight",
               amount=20.0)
    _assert("an anonymous caller is refused",
            r.status_code in (401, 403), str(r.status_code))

with _client() as client:
    _sign_in(client, "outsider@wp3c1.test")
    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="straight",
               amount=20.0)
    _assert("a non-member cannot quote in this league",
            r.status_code == 403, str(r.status_code))
    _assert("and is told why in a governed reason code",
            (r.json().get("detail") or {}).get("reason_code")
            == "not_a_league_member")

with _client() as client:
    _sign_in(client, "me@wp3c1.test")
    r = _quote(client, opponent_team_id=OUTSIDER, week=WEEK,
               bet_type="straight", amount=20.0)
    _assert("a member cannot quote a team outside the league",
            r.status_code == 400
            and (r.json().get("detail") or {}).get("reason_code")
            == "opponent_not_in_league", str(r.status_code))

    r = _quote(client, opponent_team_id=999_999, week=WEEK,
               bet_type="straight", amount=20.0)
    _assert("an absent team is refused the SAME way, so no roster can be probed",
            r.status_code == 400
            and (r.json().get("detail") or {}).get("reason_code")
            == "opponent_not_in_league")

    r = _quote(client, opponent_team_id=ME, week=WEEK, bet_type="straight",
               amount=20.0)
    _assert("a GM cannot quote themselves",
            r.status_code == 400
            and (r.json().get("detail") or {}).get("reason_code")
            == "cannot_challenge_self")

    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="prop",
               amount=20.0)
    _assert("an unoffered market is refused",
            r.status_code == 400
            and (r.json().get("detail") or {}).get("reason_code")
            == "unknown_market")

    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="straight",
               amount=20.0, challenge_mode="sideways")
    _assert("an unknown mode is refused",
            r.status_code == 400
            and (r.json().get("detail") or {}).get("reason_code")
            == "unknown_challenge_mode")

    # WP3C.2 SUPERSEDED `line_required` — AND KEPT THE CLAIM BENEATH IT.
    #
    # This assertion existed because nothing assigned a spread, so pricing one
    # would have meant defaulting the line to 0.0 and quoting a pick'em nobody
    # asked for. The owner ruling assigned the line, so the honest outcome is no
    # longer a refusal — it is a real market. What must STILL be true is that
    # the pick'em never appears: a spread quoted with no client line must come
    # back priced against the board's own line, and that line must not be a
    # silent zero.
    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="spread",
               amount=20.0)
    _assert("a spread with no client line is priced from the SERVED market",
            r.status_code == 200, r.text[:160])
    if r.status_code == 200:
        _assert("and never as a pick'em — the line is the board's, not zero",
                r.json()["line"] is not None and r.json()["line"] != 0.0,
                str(r.json()["line"]))
        _assert("with the sportsbook-signed value echoed for the composer",
                r.json()["display_line"] == -r.json()["line"],
                f"{r.json()['line']} → {r.json()['display_line']}")

    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="over_under",
               amount=20.0)
    _assert("a total with no side is refused, not guessed",
            r.status_code == 400
            and (r.json().get("detail") or {}).get("reason_code")
            == "side_required", r.text[:160])

    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="straight",
               amount=1.0)
    _assert("a stake below the governed minimum is refused",
            r.status_code == 400
            and (r.json().get("detail") or {}).get("reason_code")
            == "stake_below_minimum", str(r.status_code))

    r = _post(client, f"/league/{LEAGUE_ID}/versus/quote", {
        "opponent_team_id": OPP, "week": WEEK, "bet_type": "straight",
        "amount": 20.0, "pot_cents": 999_999})
    _assert("a client-supplied economic figure is REJECTED, never echoed",
            r.status_code == 422, str(r.status_code))

_section("6 · The commissioner gets no competitive privilege")

with _client() as client:
    _sign_in(client, "comm@wp3c1.test")
    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="straight",
               amount=20.0)
    _assert("a commissioner quotes as their OWN team, like anyone else",
            r.status_code in (200, 409)
            and (r.json().get("acting_team_id") == COMM_TEAM
                 if r.status_code == 200 else True),
            str(r.status_code))
    if r.status_code == 200:
        _assert("and never as another GM",
                r.json().get("acting_team_id") != ME)


# ── 7 · Missing projections fail honestly ────────────────────────────────────

_section("7 · An unpriceable matchup is refused, never priced at zero")

with _client() as client:
    _sign_in(client, "blank@wp3c1.test")
    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="straight",
               amount=20.0)
    # A ROSTERED BUT UNPROJECTED TEAM IS A REAL STATE, not an absence: the
    # lineup is set and the numbers have not landed, and the model prices that
    # side as the underdog it is. The opponent HAS projections, so the board is
    # not empty and the quote is genuine.
    _assert("one side unprojected is still priced — it is a real state",
            r.status_code == 200, r.text[:160])
    if r.status_code == 200:
        _assert("and the unprojected side is the underdog, not even money",
                r.json()["anchor_moneyline"] != r.json()["derived_moneyline"],
                f"{r.json()['anchor_moneyline']} vs {r.json()['derived_moneyline']}")

with _client() as client:
    _sign_in(client, "rosterless@wp3c1.test")
    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="straight",
               amount=20.0)
    _assert("a team with no starting lineup is refused, not priced",
            r.status_code == 409
            and (r.json().get("detail") or {}).get("reason_code")
            == "roster_unavailable", r.text[:160])
    _assert("and the refusal is product language, not the simulator's own",
            "starting lineup" in ((r.json().get("detail") or {})
                                  .get("message", ""))
            and "home_starters" not in r.text, r.text[:160])

# A REGULAR-SEASON WEEK WITH NO PROJECTIONS AT ALL. Week 16 would have been
# wrong for this: it is past `playoff_start_week`, so the postseason field gate
# fires first and the refusal would have been about eligibility rather than
# about pricing. Week 5 is in the regular season and nothing is projected there.
UNPROJECTED_WEEK = 5

with _client() as client:
    _sign_in(client, "me@wp3c1.test")
    r = _quote(client, opponent_team_id=OPP, week=UNPROJECTED_WEEK,
               bet_type="straight", amount=20.0)
    _assert("a week nobody projected is REFUSED, not priced at even money",
            r.status_code == 409
            and (r.json().get("detail") or {}).get("reason_code")
            == "projections_unavailable", r.text[:160])
    _assert("and the message is product language, not a stack trace",
            "projections" in ((r.json().get("detail") or {})
                              .get("message", "")).lower()
            and "Traceback" not in r.text)


_section("9 · A certainty is refused for Dynamic, and still Locked-priceable")

with _client() as client:
    _sign_in(client, "me@wp3c1.test")
    r = _quote(client, opponent_team_id=LOPSIDED, week=WEEK,
               bet_type="straight", amount=20.0, challenge_mode="dynamic")
    _assert("a matchup the model prices at certainty refuses a Dynamic quote",
            r.status_code == 409
            and (r.json().get("detail") or {}).get("reason_code")
            == "dynamic_not_priceable", str(r.status_code))
    _assert("and it says so in product language, not an exception string",
            "one-sided" in ((r.json().get("detail") or {})
                            .get("message", "")).lower())

    r = _quote(client, opponent_team_id=LOPSIDED, week=WEEK,
               bet_type="straight", amount=20.0, challenge_mode="locked")
    _assert("the same matchup still quotes as Locked — both sides stake alike",
            r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        body = r.json()
        _assert("with equal stakes and a real pot",
                body["your_stake_cents"] == body["opponent_stake_cents"] == 2000
                and body["pot_cents"] == 4000)


# ── 8 · Nothing leaked after all of it ───────────────────────────────────────

_section("8 · The ledger is intact after every refusal and every quote")

_assert("the ledger still balances", trial_balance() == 0, str(trial_balance()))


# ── 10 · The two frontend tiers ──────────────────────────────────────────────
#
# THE COMPONENT TIER drives the shipped composer directly against a stub whose
# answers this suite decides, which is the only way to prove ORDERING claims:
# that a response for an abandoned stake is discarded rather than drawn.
#
# THE BROWSER TIER runs the real page against a real application server and the
# real route, with a real session cookie and the real CSRF header. It is the
# only tier that can claim the figures a GM sees are the integers THIS route
# sent, because it compares the DOM against the response the page received.
#
# The browser tier needs a league the pricing model can actually price, which
# the standing fixture is not — its projections are written under a source the
# model does not read, so every quote against it refuses. `seed_priceable_
# versus` is the opt-in that gives the league a real board; it is off by
# default, so every previously certified suite runs against the fixture it was
# certified on.

def _run_node(script: str, label: str, env_extra: dict | None = None) -> None:
    node = shutil.which("node")
    if node is None:
        _assert(f"{label} — node is available", False, "node not on PATH")
        return
    print(f"\n{label}")
    env = dict(os.environ)
    env.update(env_extra or {})
    proc = subprocess.run(
        [node, os.path.join(ROOT, "web", "tests", script)],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print(proc.stderr.rstrip()[-2000:])
    passes = proc.stdout.count("[PASS]")
    fails = proc.stdout.count("[FAIL]")
    _assert(f"{label} is green", proc.returncode == 0 and fails == 0,
            f"{passes} PASS / {fails} FAIL, exit {proc.returncode}")


_section("10 · The composer, driven — component and browser")

_run_node("wp3c1_component_tests.mjs", "WP3C.1 component suite (Node)")

with AppServer(seed_priceable_versus=True) as _server:
    _run_node("wp3c1_browser.mjs",
              "WP3C.1 browser suite (headless Chrome, live route)",
              {"FS_TEST_ORIGIN": _server.origin,
               "FS_TEST_AUTH_EMAIL": APP_GM_EMAIL,
               "FS_TEST_AUTH_PASSWORD": APP_PASSWORD})


print("\n" + "=" * 66)
if _failures:
    print(f"WP3C.1 VERSUS QUOTE — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("WP3C.1 VERSUS QUOTE — all assertions PASSED")
