#!/usr/bin/env python3
"""
test_wp3c2_versus_market_lines.py — WP3C.2 · authoritative Versus market lines.

THE CLAIM, AND WHY EACH PART NEEDS A DIFFERENT KIND OF PROOF.

  1. THE LINE IS THE RULING'S LINE. The owner ruled median-of-the-simulated-
     distribution, nearest half point, no hook. §1 proves that against
     DETERMINISTIC ARRAYS rather than against a live simulation: a test that
     only checked HTTP output could not tell a median from a mean when the two
     happen to be close, and could never exercise the rounding boundaries at
     all.

  2. ONE LINE, FIVE PLACES. §5–§7 prove that the line a GM is SHOWN is the line
     the quote PRICES, the line the write route PERSISTS, and the line
     SETTLEMENT grades. Not by comparing helper to helper — by reading the
     persisted `BeefProposal` and `Bet` rows a real HTTP-issued wager produced
     and grading them through `settlement_engine._eval_beef`, the function the
     real settlement path calls.

  3. THE SIGN SURVIVES THE ROUND TRIP. The canonical threshold and the
     sportsbook display are negations of one another, and getting that backwards
     would invert every spread wager silently. §4 walks the favourite side and
     the underdog side all the way to a graded outcome.

  4. A CLIENT CANNOT INVENT A MARKET. §8 posts fabricated spreads and totals at
     both the quote route and the write route.

  5. PUSH SURVIVED THE RULING. Because no half-point hook is applied, a whole
     number line is reachable — and §9 proves a push still grades as a push
     through the governed evaluator rather than asserting it from the source.

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
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'wp3c2.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import numpy as np                                                 # noqa: E402
from fastapi.testclient import TestClient                          # noqa: E402

from api.main import app                                           # noqa: E402
from auth.jwt_auth import hash_password                            # noqa: E402
from auth.session import CSRF_COOKIE, CSRF_HEADER                  # noqa: E402
from betting.settlement_engine import _eval_beef                   # noqa: E402
from config import CURRENT_SEASON                                  # noqa: E402
from db.schema import (                                            # noqa: E402
    Base, BeefChallenge, BeefProposal, Bet, League, Matchup, Player,
    Projection, Roster, SessionLocal, Team, User, Wallet, engine,
)
from economy.economy_events import wallet_account                  # noqa: E402
from ledger.ledger import (                                        # noqa: E402
    LedgerEntry, create_ledger_table, post as ledger_post, trial_balance,
)
from odds.market_lines import (                                    # noqa: E402
    lines_from_scores, median_margin, median_total, round_to_nearest_half,
    sportsbook_spread,
)
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


# ── 1 · The line-generation primitive, on arrays this suite controls ─────────
#
# NO SIMULATION HERE, DELIBERATELY. The ruling is a statement about a statistic
# and a rounding rule; both are testable exactly, and testing them through a
# Monte Carlo run would mean asserting on a number nobody chose. The engine's
# own arrays are exercised from §3 onward.

_section("1 · The median, measured on distributions this suite chose")

_assert("a symmetric positive margin takes the median it was given",
        median_margin([110.0, 120.0, 130.0], [100.0, 110.0, 120.0]) == 10.0)
_assert("a negative median margin is reported negative",
        median_margin([100.0, 100.0, 100.0], [107.0, 108.0, 109.0]) == -8.0)
_assert("an exactly level matchup medians at zero",
        median_margin([100.0, 110.0], [110.0, 100.0]) == 0.0)
_assert("the total is the median of the COMBINED score, not the sum of medians",
        median_total([100.0, 130.0], [140.0, 100.0]) == 235.0,
        str(median_total([100.0, 130.0], [140.0, 100.0])))

# THE MEDIAN IS NOT THE MEAN, and this fixture is built so they differ. A
# right-skewed margin distribution has a mean well above its median; a test
# whose arrays were symmetric would pass identically against either statistic
# and would therefore certify nothing about which one the ruling chose.
_skew_a = [100.0] * 9 + [400.0]
_skew_b = [100.0] * 10
_assert("the ruling's estimator is the MEDIAN — a skewed board proves which",
        median_margin(_skew_a, _skew_b) == 0.0
        and abs(float(np.mean(np.array(_skew_a) - np.array(_skew_b))) - 30.0) < 1e-9,
        f"median 0.0 vs mean {float(np.mean(np.array(_skew_a) - np.array(_skew_b)))}")

_section("2 · Nearest 0.5, half away from zero, and no hook anywhere")

# THE RULING'S OWN TABLE, VERBATIM.
for value, expected in [(3.24, 3.0), (3.25, 3.5), (3.49, 3.5),
                        (3.74, 3.5), (3.75, 4.0), (4.00, 4.0)]:
    got = round_to_nearest_half(value)
    _assert(f"{value} rounds to {expected}", got == expected, str(got))

# NEGATIVES, EXPLICITLY, because the ruling asks for them to be tested rather
# than assumed. Away-from-zero is "round the magnitude, reapply the sign", so
# every row below mirrors one above.
for value, expected in [(-3.24, -3.0), (-3.25, -3.5), (-3.74, -3.5),
                        (-3.75, -4.0)]:
    got = round_to_nearest_half(value)
    _assert(f"{value} rounds to {expected}", got == expected, str(got))

for value, expected in [(0.0, 0.0), (0.24, 0.0), (0.25, 0.5), (-0.24, 0.0),
                        (238.26, 238.5), (238.24, 238.0), (174.75, 175.0)]:
    got = round_to_nearest_half(value)
    _assert(f"{value} rounds to {expected}", got == expected, str(got))

_assert("a whole-number line is PERMITTED — no half-point hook is applied",
        round_to_nearest_half(4.0) == 4.0
        and round_to_nearest_half(238.0) == 238.0)
_assert("and a level matchup rounds to a true zero, never to −0.0",
        str(round_to_nearest_half(-0.1)) == "0.0",
        str(round_to_nearest_half(-0.1)))

_section("3 · The sportsbook sign is the negation, and nothing else is")

_assert("a favourite (positive threshold) DISPLAYS negative",
        sportsbook_spread(3.5) == -3.5)
_assert("an underdog (negative threshold) DISPLAYS positive",
        sportsbook_spread(-3.0) == 3.0)
_assert("a level market displays a true zero",
        sportsbook_spread(0.0) == 0.0 and str(sportsbook_spread(0.0)) == "0.0")
_assert("the translation is its own inverse — two flips return the original",
        sportsbook_spread(sportsbook_spread(4.5)) == 4.5)

# THE RULING'S WORKED EXAMPLES, END TO END.
_ex1 = lines_from_scores([103.4], [100.0])
_assert("expected to win by 3.4 → line 3.5, favourite shows −3.5, dog +3.5",
        _ex1.spread_line == 3.5
        and sportsbook_spread(_ex1.spread_line) == -3.5
        and sportsbook_spread(-_ex1.spread_line) == 3.5,
        f"{_ex1.spread_line}")
_ex2 = lines_from_scores([100.0], [102.8])
_assert("B expected to win by 2.8 → B shows −3.0 and A shows +3.0",
        _ex2.spread_line == -3.0
        and sportsbook_spread(_ex2.spread_line) == 3.0
        and sportsbook_spread(-_ex2.spread_line) == -3.0,
        f"{_ex2.spread_line}")
_assert("and the raw median is carried alongside what it rounded to",
        abs(_ex1.raw_margin - 3.4) < 1e-9 and _ex1.spread_line == 3.5)


# ── Fixture ──────────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "wp3c2-password"
SEASON = CURRENT_SEASON
WEEK = 3
N_START = 9
STRONG_POINTS = 12.4
WEAK_POINTS = 11.9
OPENING_CENTS = 500_00

with SessionLocal() as db:
    hashed = hash_password(PASSWORD)

    league = League(name="WP3C2 League", season=SEASON,
                    projection_source="fantasypros")
    other = League(name="WP3C2 Other", season=SEASON,
                   projection_source="fantasypros")
    db.add_all([league, other])
    db.flush()
    LEAGUE_ID, OTHER_LEAGUE_ID = league.id, other.id

    def _team(name: str, email: str, league_id: int, points: float) -> int:
        t = Team(team_name=name, owner=f"{name} Owner", email=email,
                 league_id=league_id)
        db.add(t)
        db.flush()
        db.add(Wallet(team_id=t.id, balance=0.0))
        db.add(User(email=email, hashed_password=hashed, team_id=t.id,
                    role="gm"))
        for slot in range(N_START):
            p = Player(name=f"{name} p{slot}", position="WR", nfl_team="KC")
            db.add(p)
            db.flush()
            db.add(Roster(team_id=t.id, player_id=p.id))
            db.add(Projection(player_id=p.id, week=WEEK, season=SEASON,
                              source="fantasypros", projected_points=points))
        return t.id

    ME = _team("Me", "me@wp3c2.test", LEAGUE_ID, STRONG_POINTS)
    OPP = _team("Opp", "opp@wp3c2.test", LEAGUE_ID, WEAK_POINTS)
    OUTSIDER = _team("Outsider", "outsider@wp3c2.test", OTHER_LEAGUE_ID,
                     STRONG_POINTS)

    # A LEAGUE MEMBER WITH NO STARTING LINEUP, so the unavailable row on the
    # board is reachable through the product rather than by breaking the server.
    bare = Team(team_name="Bare", owner="Bare Owner", email="bare@wp3c2.test",
                league_id=LEAGUE_ID)
    db.add(bare)
    db.flush()
    BARE = bare.id
    db.add(Wallet(team_id=BARE, balance=0.0))
    db.add(User(email="bare@wp3c2.test", hashed_password=hashed,
                team_id=BARE, role="gm"))

    # The shared matchup the settlement path reads scores from.
    db.add(Matchup(league_id=LEAGUE_ID, week=WEEK, home_team_id=ME,
                   away_team_id=OPP, home_score=0.0, away_score=0.0))

    for team_id in (ME, OPP):
        ledger_post([(wallet_account(team_id), OPENING_CENTS),
                     ("world", -OPENING_CENTS)],
                    door="APPROVED_TOPOFF", session=db)
    db.commit()


def _client() -> TestClient:
    return TestClient(app)


def _sign_in(client: TestClient, email: str) -> None:
    r = client.post("/auth/session", json={"email": email,
                                           "password": PASSWORD})
    assert r.status_code == 200, r.text


def _csrf(client: TestClient) -> dict:
    return {CSRF_HEADER: client.cookies.get(CSRF_COOKIE, "")}


def _board(client: TestClient, week: int = WEEK, league: int = LEAGUE_ID,
           **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    suffix = f"&{query}" if query else ""
    return client.get(f"/league/{league}/versus/board?week={week}{suffix}")


def _quote(client: TestClient, league: int = LEAGUE_ID, **body):
    return client.post(f"/league/{league}/versus/quote", json=body,
                       headers=_csrf(client))


def _issue(client: TestClient, **body):
    return client.post("/beef/challenge", json=body, headers=_csrf(client))


def _row_for(board_body: dict, team_id: int) -> dict:
    return next(m for m in board_body["markets"]
                if m["opponent_team_id"] == team_id)


# ── 4 · The board itself ─────────────────────────────────────────────────────

_section("4 · The market board is served, signed, and honest about gaps")

with _client() as client:
    _sign_in(client, "me@wp3c2.test")
    r = _board(client)
    _assert("the board serves", r.status_code == 200, r.text[:180])
    BOARD = r.json()
    _assert("it names the league, the week and the acting team",
            BOARD["league_id"] == LEAGUE_ID and BOARD["week"] == WEEK
            and BOARD["acting_team_id"] == ME)
    _assert("every league member except the acting GM has a row",
            {m["opponent_team_id"] for m in BOARD["markets"]} == {OPP, BARE},
            str([m["opponent_team_id"] for m in BOARD["markets"]]))

    PRICED = _row_for(BOARD, OPP)
    _assert("the priceable pairing is available", PRICED["available"] is True,
            str(PRICED))
    _assert("with a moneyline for each side, and they are not the same number",
            isinstance(PRICED["acting_moneyline"], int)
            and PRICED["acting_moneyline"] != PRICED["opponent_moneyline"],
            f"{PRICED['acting_moneyline']} / {PRICED['opponent_moneyline']}")
    _assert("a spread line on the half point",
            (PRICED["spread_line"] * 2) % 1 == 0,
            str(PRICED["spread_line"]))
    _assert("a total on the half point, and a real fantasy score",
            (PRICED["total_line"] * 2) % 1 == 0 and PRICED["total_line"] > 50,
            str(PRICED["total_line"]))
    _assert("the acting side's spread is the NEGATION of the canonical line",
            PRICED["acting_spread"] == -PRICED["spread_line"],
            f"canonical {PRICED['spread_line']}, shown {PRICED['acting_spread']}")
    _assert("and the two displayed spreads mirror each other",
            PRICED["acting_spread"] == -PRICED["opponent_spread"],
            f"{PRICED['acting_spread']} / {PRICED['opponent_spread']}")
    _assert("the stronger projected team is the FAVOURITE, shown negative",
            PRICED["acting_spread"] < 0 and PRICED["acting_moneyline"] < 0,
            f"{PRICED['acting_spread']} at {PRICED['acting_moneyline']}")

    UNPRICED = _row_for(BOARD, BARE)
    _assert("a team with no lineup is reported, not omitted",
            UNPRICED["available"] is False
            and UNPRICED["reason_code"] == "roster_unavailable")
    _assert("with a product sentence and no simulator text",
            "starting lineup" in (UNPRICED["unavailable_reason"] or "")
            and "home_starters" not in (UNPRICED["unavailable_reason"] or ""))
    _assert("and NO figure at all — not a zero, not a pick'em",
            all(UNPRICED[k] is None for k in
                ("acting_moneyline", "opponent_moneyline", "spread_line",
                 "acting_spread", "opponent_spread", "total_line")))

    single = _board(client, opponent_team_id=OPP)
    _assert("one pairing can be read on its own",
            single.status_code == 200
            and len(single.json()["markets"]) == 1
            and single.json()["markets"][0]["opponent_team_id"] == OPP)
    _assert("and it agrees with the same row from the full board",
            single.json()["markets"][0] == PRICED)
    _assert("a team in another league is refused, not priced",
            _board(client, opponent_team_id=OUTSIDER).status_code == 400)


# ── 5 · The board reads state; it does not touch it ──────────────────────────

_section("5 · Reading a market writes nothing")


def _wagering_snapshot() -> tuple:
    with SessionLocal() as db:
        return (
            db.query(BeefChallenge).count(),
            db.query(BeefProposal).count(),
            db.query(Bet).count(),
            db.query(LedgerEntry).count(),
            trial_balance(),
            sorted((w.team_id, float(w.balance))
                   for w in db.query(Wallet).all()),
        )


_before = _wagering_snapshot()
with _client() as client:
    _sign_in(client, "me@wp3c2.test")
    for _ in range(6):
        _board(client)
        _board(client, opponent_team_id=OPP)
_after = _wagering_snapshot()

_assert("twelve board reads created no challenge, proposal or bet",
        _before[:3] == _after[:3], f"{_before[:3]} → {_after[:3]}")
_assert("posted no ledger entry and moved no balance",
        _before[3:] == _after[3:], f"{_before[3:]} → {_after[3:]}")
_assert("and the ledger still balances", trial_balance() == 0)


# ── 6 · One simulation, one line — the board and the quote agree ─────────────

_section("6 · The board's line is the line the quote prices")

with _client() as client:
    _sign_in(client, "me@wp3c2.test")
    q_spread = _quote(client, opponent_team_id=OPP, week=WEEK,
                      bet_type="spread", amount=20.0)
    _assert("a spread quotes with NO client line at all — the server has one",
            q_spread.status_code == 200, q_spread.text[:200])
    SPREAD_Q = q_spread.json()
    _assert("and the line it priced is the board's line, to the point",
            SPREAD_Q["line"] == PRICED["spread_line"],
            f"quote {SPREAD_Q['line']} vs board {PRICED['spread_line']}")
    _assert("the display value it echoes is the board's sportsbook spread",
            SPREAD_Q["display_line"] == PRICED["acting_spread"],
            f"{SPREAD_Q['display_line']} vs {PRICED['acting_spread']}")

    q_over = _quote(client, opponent_team_id=OPP, week=WEEK,
                    bet_type="over_under", amount=20.0, side="over")
    _assert("a total quotes against the board's total",
            q_over.status_code == 200
            and q_over.json()["line"] == PRICED["total_line"],
            q_over.text[:200])
    OVER_Q = q_over.json()
    q_under = _quote(client, opponent_team_id=OPP, week=WEEK,
                     bet_type="over_under", amount=20.0, side="under")
    UNDER_Q = q_under.json()
    _assert("Over and Under are the SAME total priced two different ways",
            UNDER_Q["line"] == OVER_Q["line"]
            and UNDER_Q["anchor_moneyline"] != OVER_Q["anchor_moneyline"],
            f"{OVER_Q['anchor_moneyline']} vs {UNDER_Q['anchor_moneyline']}")
    _assert("and each side names the side it was priced for",
            OVER_Q["side"] == "over" and UNDER_Q["side"] == "under")

    # THE MEDIAN METHODOLOGY'S OWN SIGNATURE. A line at the median of the
    # distribution the price is counted from is, by construction, a line both
    # sides sit close to even money on. A mean-based or projection-difference
    # line would drift away from that as the distribution skewed, so this
    # assertion is what distinguishes the ruling's estimator from a plausible
    # substitute — and it fails loudly if the line and the price ever come from
    # different draws of the matchup.
    for label, body in (("spread", SPREAD_Q), ("over", OVER_Q),
                        ("under", UNDER_Q)):
        _assert(f"the {label} market prices near even money, as a median line must",
                abs(body["anchor_moneyline"]) < 150,
                f"{body['anchor_moneyline']}")

    ml = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="straight",
                amount=20.0)
    _assert("a Moneyline still quotes and carries NO line",
            ml.status_code == 200 and ml.json()["line"] is None
            and ml.json()["display_line"] is None, ml.text[:160])
    _assert("and its odds are the board's moneyline, unchanged by WP3C.2",
            ml.json()["anchor_moneyline"] == PRICED["acting_moneyline"],
            f"{ml.json()['anchor_moneyline']} vs {PRICED['acting_moneyline']}")

    _assert("the board is stable across reads — the seed makes it a fact",
            _row_for(_board(client).json(), OPP) == PRICED)


# ── 7 · A client cannot invent a market ──────────────────────────────────────

_section("7 · Fabricated lines are refused at the quote route")

with _client() as client:
    _sign_in(client, "me@wp3c2.test")

    ok = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="spread",
                amount=20.0, line=PRICED["spread_line"])
    _assert("asserting the line that WAS offered is accepted",
            ok.status_code == 200 and ok.json()["line"] == PRICED["spread_line"])

    for bad in (PRICED["spread_line"] + 1, PRICED["spread_line"] - 7,
                -PRICED["spread_line"], 0.0):
        if bad == PRICED["spread_line"]:
            continue
        r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="spread",
                   amount=20.0, line=bad)
        _assert(f"a spread asserted at {bad} is REFUSED, not priced",
                r.status_code == 409
                and (r.json().get("detail") or {}).get("reason_code")
                == "market_moved", f"{r.status_code} {r.text[:120]}")

    # THE SIGN TRAP. A client that sent the DISPLAY value where the canonical
    # value belongs would, on a favourite, be asserting the underdog's line —
    # a different wager at a different price. It must not be honoured.
    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="spread",
               amount=20.0, line=PRICED["acting_spread"])
    _assert("asserting the DISPLAYED sign where the canonical belongs is refused",
            r.status_code == 409, f"{r.status_code} {r.text[:120]}")

    for bad in (PRICED["total_line"] + 20, PRICED["total_line"] - 0.5, 0.0):
        r = _quote(client, opponent_team_id=OPP, week=WEEK,
                   bet_type="over_under", amount=20.0, side="over", line=bad)
        _assert(f"a total asserted at {bad} is REFUSED",
                r.status_code == 409
                and (r.json().get("detail") or {}).get("reason_code")
                == "market_moved", f"{r.status_code} {r.text[:120]}")

    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="over_under",
               amount=20.0)
    _assert("a total with no side is refused — nothing is chosen for the GM",
            r.status_code == 400
            and (r.json().get("detail") or {}).get("reason_code")
            == "side_required")
    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="over_under",
               amount=20.0, side="sideways")
    _assert("and an invented side is refused too", r.status_code == 400
            and (r.json().get("detail") or {}).get("reason_code")
            == "side_required")

    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="straight",
               amount=20.0, line=3.5)
    _assert("a line sent with a MONEYLINE is refused, not silently ignored",
            r.status_code == 400
            and (r.json().get("detail") or {}).get("reason_code")
            == "line_not_applicable", f"{r.status_code} {r.text[:120]}")

    r = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="spread",
               amount=20.0, spread_line=99.0)
    _assert("an unknown field is refused outright by the contract",
            r.status_code == 422, str(r.status_code))

    r = _quote(client, opponent_team_id=BARE, week=WEEK, bet_type="spread",
               amount=20.0)
    _assert("an unpriceable pairing refuses the spread in product language",
            r.status_code == 409
            and (r.json().get("detail") or {}).get("reason_code")
            == "roster_unavailable", f"{r.status_code} {r.text[:140]}")
    _assert("and no line is invented for it",
            "line" not in r.text or (r.json().get("detail") or {}).get("line")
            is None)


# ── 8 · Display == quote == submitted == persisted ───────────────────────────

_section("8 · The write path persists the market it was shown")

ISSUED: dict = {}

with _client() as client:
    _sign_in(client, "me@wp3c2.test")

    for label, body, expect_line in (
        ("spread", {"bet_type": "spread"}, PRICED["spread_line"]),
        ("over", {"bet_type": "over_under", "side": "over"},
         PRICED["total_line"]),
        ("under", {"bet_type": "over_under", "side": "under"},
         PRICED["total_line"]),
        ("moneyline", {"bet_type": "straight"}, None),
    ):
        quoted = _quote(client, opponent_team_id=OPP, week=WEEK, amount=20.0,
                        **body)
        assert quoted.status_code == 200, quoted.text
        q = quoted.json()

        issued = _issue(client, challenger_team_id=ME, challenged_team_id=OPP,
                        week=WEEK, amount=20.0, challenge_mode="locked",
                        line=q["line"], **body)
        _assert(f"{label}: the wager the quote described can be issued",
                issued.status_code == 201, issued.text[:200])
        if issued.status_code != 201:
            continue
        cid = issued.json()["challenge_id"]
        ISSUED[label] = (cid, q)

        with SessionLocal() as db:
            ch = db.query(BeefChallenge).filter(BeefChallenge.id == cid).one()
            prop = (db.query(BeefProposal)
                    .filter(BeefProposal.challenge_id == cid)
                    .order_by(BeefProposal.id.desc()).first())
            _assert(f"{label}: the PERSISTED proposal line is the offered line",
                    prop.line == expect_line,
                    f"persisted {prop.line}, offered {expect_line}")
            _assert(f"{label}: and the challenge row carries it too",
                    ch.line == expect_line, f"{ch.line}")
            _assert(f"{label}: the persisted side is the GM's own choice",
                    ch.side == body.get("side"), f"{ch.side}")
            # EXACT CENTS, against the persisted proposal — the WP3C.1
            # discipline, extended to the two markets it could not reach.
            _assert(f"{label}: your stake matches the quote to the cent",
                    prop.anchor_stake_cents == q["your_stake_cents"] == 2000)
            _assert(f"{label}: the opponent's stake matches to the cent",
                    prop.quoted_derived_stake_cents == q["opponent_stake_cents"],
                    f"{prop.quoted_derived_stake_cents} vs "
                    f"{q['opponent_stake_cents']}")
            _assert(f"{label}: the pot matches to the cent",
                    prop.quoted_funded_pot_cents == q["pot_cents"],
                    f"{prop.quoted_funded_pot_cents} vs {q['pot_cents']}")
            _assert(f"{label}: the win matches to the cent",
                    prop.quoted_derived_stake_cents == q["win_cents"])
            _assert(f"{label}: and the frozen odds are the quoted odds",
                    prop.anchor_moneyline == q["anchor_moneyline"]
                    and prop.derived_moneyline == q["derived_moneyline"],
                    f"{prop.anchor_moneyline} vs {q['anchor_moneyline']}")

    # A DYNAMIC SPREAD, because the ruling changes the line and must change
    # nothing about the mode. The proposal freezes no derived stake in Dynamic —
    # that is the governed model — but it must still freeze the LINE.
    dq = _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="spread",
                amount=20.0, challenge_mode="dynamic")
    _assert("a Dynamic spread quotes", dq.status_code == 200, dq.text[:180])
    if dq.status_code == 200:
        d = dq.json()
        _assert("its opponent figure is a CEILING, as Dynamic has always been",
                d["is_ceiling"] is True)
        _assert("and it is priced against the same authoritative line",
                d["line"] == PRICED["spread_line"])
        di = _issue(client, challenger_team_id=ME, challenged_team_id=OPP,
                    week=WEEK, bet_type="spread", amount=20.0,
                    challenge_mode="dynamic", line=d["line"])
        _assert("a Dynamic spread can be issued", di.status_code == 201,
                di.text[:200])
        if di.status_code == 201:
            with SessionLocal() as db:
                prop = (db.query(BeefProposal)
                        .filter(BeefProposal.challenge_id
                                == di.json()["challenge_id"])
                        .order_by(BeefProposal.id.desc()).first())
                _assert("Dynamic freezes the LINE at proposal time",
                        prop.line == PRICED["spread_line"], str(prop.line))
                _assert("and still quotes no derived stake — the model is intact",
                        prop.quoted_derived_stake_cents is None
                        and prop.quoted_funded_pot_cents is None)
                _assert("while freezing the probabilities the Handshake needs",
                        prop.anchor_win_probability is not None
                        and prop.derived_win_probability is not None)

    # TAMPERING AT THE WRITE ROUTE, not just at the quote.
    for bad_body, bad_line, label in (
        ({"bet_type": "spread"}, PRICED["spread_line"] + 2, "spread"),
        ({"bet_type": "spread"}, PRICED["acting_spread"], "spread (wrong sign)"),
        ({"bet_type": "over_under", "side": "over"},
         PRICED["total_line"] + 10, "total"),
    ):
        r = _issue(client, challenger_team_id=ME, challenged_team_id=OPP,
                   week=WEEK, amount=20.0, challenge_mode="locked",
                   line=bad_line, **bad_body)
        _assert(f"WRITE: a fabricated {label} is refused before any escrow",
                r.status_code == 409
                and (r.json().get("detail") or {}).get("reason_code")
                == "market_moved", f"{r.status_code} {r.text[:140]}")

    r = _issue(client, challenger_team_id=ME, challenged_team_id=OPP,
               week=WEEK, amount=20.0, challenge_mode="locked",
               bet_type="over_under")
    _assert("WRITE: a total with no side is refused",
            r.status_code == 400
            and (r.json().get("detail") or {}).get("reason_code")
            == "side_required", f"{r.status_code} {r.text[:140]}")

_assert("the ledger balances after every refusal", trial_balance() == 0,
        str(trial_balance()))


# ── 9 · Settlement grades the proposition the GM was shown ───────────────────
#
# THE GOVERNED EVALUATOR, NOT A RESTATEMENT. `_eval_beef` is the function
# `settlement_engine` calls for a Versus bet. The bets below are the real rows
# acceptance created, carrying the real persisted line, and the scores are
# written onto the real matchup. Nothing about settlement is simulated here.

_section("9 · The favourite side, the underdog side, and the push")


def _accept(challenge_id: int) -> tuple:
    """Accept through the governed funding path and return the two Bet rows."""
    import uuid as _uuid
    from economy.challenge_funding import accept_funded_challenge
    with SessionLocal() as db:
        out = accept_funded_challenge(event_id=_uuid.uuid4(),
                                      challenge_id=challenge_id,
                                      actor_team_id=OPP, db=db)
        db.commit()
        return out.anchor_bet_id, out.derived_bet_id


def _score(home: float, away: float) -> None:
    with SessionLocal() as db:
        m = (db.query(Matchup)
             .filter(Matchup.league_id == LEAGUE_ID, Matchup.week == WEEK)
             .one())
        m.home_score, m.away_score = home, away
        db.commit()


def _grade(bet_id: int) -> str:
    with SessionLocal() as db:
        return _eval_beef(db.query(Bet).filter(Bet.id == bet_id).one(), db)


if "spread" in ISSUED:
    SPREAD_CID, SPREAD_Q2 = ISSUED["spread"]
    anchor_bet, derived_bet = _accept(SPREAD_CID)
    CANON = PRICED["spread_line"]
    SHOWN = PRICED["acting_spread"]

    with SessionLocal() as db:
        a = db.query(Bet).filter(Bet.id == anchor_bet).one()
        d = db.query(Bet).filter(Bet.id == derived_bet).one()
        _assert("the acting GM's bet carries the canonical line, unnegated",
                a.picked_team_id == ME and a.line == CANON,
                f"picked {a.picked_team_id}, line {a.line}")
        _assert("and the opponent's carries its mirror",
                d.picked_team_id == OPP and d.line == -CANON,
                f"picked {d.picked_team_id}, line {d.line}")

    # THE FAVOURITE COVERS. Shown at −4.5 (say), the acting GM must win by more
    # than 4.5. A margin of CANON + 1 does that.
    _score(100.0 + CANON + 1.0, 100.0)
    _assert(f"favourite shown {SHOWN:+g}: winning by more than {abs(SHOWN):g} WINS",
            _grade(anchor_bet) == "won" and _grade(derived_bet) == "lost",
            f"{_grade(anchor_bet)} / {_grade(derived_bet)}")

    # THE FAVOURITE FAILS TO COVER, and the underdog side wins for it. A margin
    # of CANON − 1 is a win on the field and a loss on the spread — which is the
    # single most important thing a spread market has to get right.
    _score(100.0 + CANON - 1.0, 100.0)
    _assert(f"underdog shown {-SHOWN:+g}: losing by less than {abs(SHOWN):g} WINS",
            _grade(derived_bet) == "won" and _grade(anchor_bet) == "lost",
            f"anchor {_grade(anchor_bet)} / derived {_grade(derived_bet)}")

    _score(80.0, 130.0)
    _assert("and an outright loss by the favourite loses the favourite's side",
            _grade(anchor_bet) == "lost" and _grade(derived_bet) == "won")

    # THE PUSH. Reachable only because the ruling forbade the half-point hook.
    if float(CANON).is_integer():
        _score(100.0 + CANON, 100.0)
        _assert("PUSH: a whole-number spread hit exactly pushes BOTH sides",
                _grade(anchor_bet) == "push" and _grade(derived_bet) == "push",
                f"{_grade(anchor_bet)} / {_grade(derived_bet)}")
    else:
        # A half-point line cannot push, which is correct and is not the claim.
        # The claim is that the ROUNDING permits whole numbers at all, and that
        # a whole line pushes when it is hit; both are certified directly on the
        # evaluator below so the proof does not depend on which line the
        # simulation happened to produce for this fixture.
        _assert("this fixture's spread is a half point, so no push is possible "
                "on it — certified directly below instead",
                True, f"line {CANON}")
        with SessionLocal() as db:
            bet = db.query(Bet).filter(Bet.id == anchor_bet).one()
            original = bet.line
            bet.line = 7.0
            db.commit()
        _score(107.0, 100.0)
        _assert("PUSH: a whole-number spread hit exactly pushes",
                _grade(anchor_bet) == "push", _grade(anchor_bet))
        with SessionLocal() as db:
            bet = db.query(Bet).filter(Bet.id == anchor_bet).one()
            bet.line = original
            db.commit()

if "over" in ISSUED and "under" in ISSUED:
    TOTAL = PRICED["total_line"]
    over_anchor, over_derived = _accept(ISSUED["over"][0])
    under_anchor, under_derived = _accept(ISSUED["under"][0])

    with SessionLocal() as db:
        oa = db.query(Bet).filter(Bet.id == over_anchor).one()
        od = db.query(Bet).filter(Bet.id == over_derived).one()
        _assert("the Over bet is persisted as Over at the offered total",
                oa.side == "over" and oa.line == TOTAL, f"{oa.side} {oa.line}")
        _assert("and its counterparty is the Under at the SAME total",
                od.side == "under" and od.line == TOTAL,
                f"{od.side} {od.line}")

    _score(TOTAL / 2 + 20.0, TOTAL / 2 + 20.0)
    _assert("OVER: a combined score above the total wins the Over",
            _grade(over_anchor) == "won" and _grade(over_derived) == "lost")
    _assert("     and loses the Under wager placed on the same total",
            _grade(under_anchor) == "lost" and _grade(under_derived) == "won")

    _score(TOTAL / 2 - 20.0, TOTAL / 2 - 20.0)
    _assert("UNDER: a combined score below the total wins the Under",
            _grade(under_anchor) == "won" and _grade(under_derived) == "lost")

    if float(TOTAL).is_integer():
        _score(TOTAL / 2, TOTAL / 2)
        _assert("PUSH: a combined score exactly on a whole total pushes",
                _grade(over_anchor) == "push" and _grade(under_anchor) == "push",
                f"{_grade(over_anchor)} / {_grade(under_anchor)}")
    else:
        _assert("this fixture's total is a half point, so it cannot push — "
                "the whole-number case is certified directly below",
                True, f"total {TOTAL}")
        with SessionLocal() as db:
            bet = db.query(Bet).filter(Bet.id == over_anchor).one()
            original = bet.line
            bet.line = 200.0
            db.commit()
        _score(100.0, 100.0)
        _assert("PUSH: a whole-number total hit exactly pushes",
                _grade(over_anchor) == "push", _grade(over_anchor))
        with SessionLocal() as db:
            bet = db.query(Bet).filter(Bet.id == over_anchor).one()
            bet.line = original
            db.commit()

_score(0.0, 0.0)


# ── 10 · Authorization and the postseason ────────────────────────────────────

_section("10 · No market for anyone who may not be offered one")

with _client() as client:
    _sign_in(client, "outsider@wp3c2.test")
    _assert("a GM outside the league gets no board for it",
            _board(client).status_code == 403)
    _assert("and cannot quote a spread in it",
            _quote(client, opponent_team_id=OPP, week=WEEK, bet_type="spread",
                   amount=20.0).status_code == 403)

with _client() as client:
    r = _board(client)
    _assert("an unauthenticated caller gets no board",
            r.status_code in (401, 403), str(r.status_code))

with _client() as client:
    _sign_in(client, "me@wp3c2.test")
    _assert("no board row offers the acting GM their own team",
            all(m["opponent_team_id"] != ME
                for m in _board(client).json()["markets"]))


# ── 11 · No line mathematics survives in JavaScript ──────────────────────────

_section("11 · The browser formats lines and computes none")

WEB = os.path.join(ROOT, "web", "js")


def _read(name: str) -> str:
    with open(os.path.join(WEB, name), encoding="utf-8") as fh:
        return fh.read()


def _code_only(source: str) -> str:
    """Executable code with comments and string literals removed."""
    import re
    stripped = re.sub(r"/\*[\s\S]*?\*/", " ", source)
    stripped = re.sub(r"^\s*//.*$", " ", stripped, flags=re.M)
    return re.sub(r"'[^'\n]*'|\"[^\"\n]*\"|`[^`]*`", "''", stripped)


MARKET_MODEL = _code_only(_read("market-model.js"))
MARKET_CMD = _code_only(_read("versus-market-command.js"))

_assert("the served-board model contains no arithmetic at all",
        not any(op in MARKET_MODEL.replace("=>", "") for op in ("*", "/", "+", "-")),
        "pure holding")
_assert("the market command computes nothing either",
        not any(op in MARKET_CMD.replace("=>", "") for op in ("*", "/")),
        "pure request")

for name in ("market-model.js", "versus-market-command.js", "league.js",
             "composer.js"):
    body = _code_only(_read(name))
    _assert(f"{name} takes no median", "median" not in body.lower())
    _assert(f"{name} rounds no line to a half point",
            not any(t in body for t in ("0.5)", "* 2)", "Math.round(")))

COMPOSER = _code_only(_read("composer.js"))
LEAGUE = _code_only(_read("league.js"))
for name, body in (("composer.js", COMPOSER), ("league.js", LEAGUE)):
    _assert(f"{name} never negates a served spread to make a sign",
            "-served" not in body.replace(" ", "")
            and "-row.spread" not in body.replace(" ", "")
            and "-board.spread" not in body.replace(" ", ""))
    _assert(f"{name} reads acting_spread rather than deriving one",
            "acting_spread" in body)

_assert("the composer sends the served line as an assertion, not a choice",
        "marketLine(state)" in COMPOSER)
_assert("and there is no free-form line input anywhere in the composer",
        "data-composer-line" not in _read("composer.js")
        and "line-input" not in _read("composer.js"))


# ── 12 · The Matchup Preview stays analysis ──────────────────────────────────

_section("12 · The Preview did not become a second market")

PREVIEW = _read("preview.js")
# CODE ONLY. The module's comments explain AT LENGTH that Rev 4.2's SPORTSBOOK
# VIEW block was removed and why — a text scan finds that explanation and fails,
# which would be a test of the documentation rather than of the surface.
PREVIEW_CODE = _code_only(PREVIEW)
_assert("the preview renders no market cells",
        "fs-market" not in PREVIEW_CODE and "data-market=" not in PREVIEW_CODE)
_assert("and no sportsbook terms block",
        "SPORTSBOOK" not in PREVIEW_CODE.upper())
_assert("its locked section order is intact",
        all(t in PREVIEW for t in ("MATCHUP", "WHY THE LINE LOOKS THIS WAY",
                                   "THE READ", "LINEUPS")))


# ── 13 · One authority, and the API layer is not it ──────────────────────────

_section("13 · The line has exactly one definition")

def _py_code_only(path: str) -> str:
    """Python source with every comment and string literal removed.

    THE SAME LESSON THE JS SCANS LEARNED. This package's comments discuss the
    median at length, precisely because the reader needs to know where the
    median lives and where it must not. A scan that counted those sentences
    would fail on well-documented code and pass on undocumented code, which is
    exactly backwards.
    """
    import io
    import tokenize
    kept = []
    with open(path, encoding="utf-8") as fh:
        for tok in tokenize.generate_tokens(io.StringIO(fh.read()).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(tok.string)
    return " ".join(kept)


MAIN_CODE = _py_code_only(os.path.join(ROOT, "api", "main.py"))
ENGINE_CODE = _py_code_only(os.path.join(ROOT, "beefs", "beef_engine.py"))
LINES_CODE = _py_code_only(os.path.join(ROOT, "odds", "market_lines.py"))

_assert("api/main.py computes no median",
        "median" not in MAIN_CODE.lower())
_assert("api/main.py rounds no line",
        "round_to_nearest_half" not in MAIN_CODE)
_assert("api/main.py negates no spread to make a display sign",
        "sportsbook_spread" not in MAIN_CODE)
_assert("the engine derives the board from market_lines, not from its own copy",
        "lines_from_scores" in ENGINE_CODE and "median" not in ENGINE_CODE)
_assert("and the one negation lives in market_lines.sportsbook_spread",
        "sportsbook_spread" in ENGINE_CODE
        and LINES_CODE.count("- float ( canonical_line )") == 1,
        "one negation")

import ast                                                         # noqa: E402

_tree = ast.parse(open(os.path.join(ROOT, "odds", "market_lines.py"),
                       encoding="utf-8").read())
_assert("market_lines imports no database, session or model",
        not any(isinstance(n, (ast.Import, ast.ImportFrom))
                and any(w in ast.dump(n)
                        for w in ("db.", "sqlalchemy", "Session", "schema"))
                for n in ast.walk(_tree)),
        "pure")
_assert("it runs no simulation of its own",
        "simulate" not in LINES_CODE)
_assert("and it is the ONLY place a market line is rounded",
        "round_to_nearest_half" not in ENGINE_CODE.replace(
            "from odds . market_lines import lines_from_scores , "
            "sportsbook_spread", ""))


# ── 14 · The frontend tiers ──────────────────────────────────────────────────

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


_section("14 · The composer and the Play card, driven")

_run_node("wp3c2_component_tests.mjs", "WP3C.2 component suite (Node)")

with AppServer(seed_priceable_versus=True) as _server:
    _run_node("wp3c2_browser.mjs",
              "WP3C.2 browser suite (headless Chrome, live board)",
              {"FS_TEST_ORIGIN": _server.origin,
               "FS_TEST_AUTH_EMAIL": APP_GM_EMAIL,
               "FS_TEST_AUTH_PASSWORD": APP_PASSWORD})


print("\n" + "=" * 66)
if _failures:
    print(f"WP3C.2 VERSUS MARKET LINES — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("WP3C.2 VERSUS MARKET LINES — all assertions PASSED")
