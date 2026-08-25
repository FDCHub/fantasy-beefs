#!/usr/bin/env python3
"""
test_wp3b_standings_read_model.py — WP3B · the Rev 4.3 competitive standings.

WHAT IS ACTUALLY AT RISK HERE. Rev 4.3 §7.1 forbids ranking Overall by Wallet
balance, and the failure mode is not a crash — it is a standings table that
looks entirely reasonable while ordering the league by who was advanced the most
Credits. So the fixture is built specifically so that WALLET ORDER AND
COMPETITIVE ORDER DISAGREE: the team with the largest Wallet finishes last, and
the team with the smallest finishes first. A Wallet-ranked implementation passes
nothing here.

POSTED STATE, NOT MOCKS. Every figure is produced by posting real balanced
entries through `ledger.post()` under the real doors the protocol uses —
`season_allocation`, `weekly_minimum_release`, `approved_bab_topoff`,
`skunk_assessment`, `wager_placed`, `wager_settled`, `pool_weekly_collection`,
`pool_winner_distribution`. Asserting against a stubbed balance would prove this
suite can add up, not that the read model reads what the protocol writes.

THE FOUR CLAIMS:

  1. NONCOMPETITIVE MOVEMENT IS EXCLUDED. Allocation, Weekly Minimum release,
     Top-Off and Skunk all move a GM's spendable Credits and none of them is a
     competitive result. All four are posted, and none may appear in any NET.
  2. AN UNSETTLED WAGER IS NOT A LOSS. A GM with a live stake in escrow is level,
     not down by the stake.
  3. MIN-FUNDED SPEND IS COUNTED. `plan_spend_split` funds MIN FIRST, so the Pool
     entry is deliberately posted out of `min:` and never touches `wallet:`. A
     wallet-only sum reports it as never having been paid.
  4. NOTHING ABOUT ANYBODY'S ACCOUNTING LEAVES THE MODEL. Standings is read by
     every member about every other member.

DATABASE. A temp SQLite file per run. No locking, isolation or concurrency claim
is made or implied here.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'wp3b.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient                      # noqa: E402

from api.main import app                                       # noqa: E402
from auth.jwt_auth import hash_password                        # noqa: E402
from auth.session import CSRF_COOKIE, CSRF_HEADER              # noqa: E402
from db.schema import (                                        # noqa: E402
    Base, BeefChallenge, Bet, League, LeagueCommissioner, Matchup, SessionLocal,
    Team, User, Wallet, engine,
)
from economy.economy_events import (                           # noqa: E402
    min_account, min_reserve_account, receivable_account, wallet_account,
)
from ledger.ledger import (                                    # noqa: E402
    create_ledger_table, post as ledger_post, trial_balance,
)
from reports.standings_read_model import (                     # noqa: E402
    POOL_DOORS, VERSUS_DOORS, league_standings,
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

PASSWORD = "wp3b-password"
SEASON = 2026
WEEK = 5

# Odd cents throughout. A rounding fault anywhere between the ledger and the
# JSON body would round these and be caught; round figures survive it unnoticed.
OPENING_MIN_RESERVE = 14_000_33
OPENING_RESERVE = 8_000_11
WEEK_MIN_RELEASED = 3_000_07
VERSUS_STAKE = 1_000_29
OPEN_STAKE = 500_17
POOL_ENTRY = 100_03
TOPOFF_BIG = 50_000_00       # deliberately huge — see the Wallet-order claim

with SessionLocal() as db:
    hashed = hash_password(PASSWORD)

    league = League(name="WP3B League", season=SEASON)
    db.add(league)
    db.flush()
    LEAGUE_ID = league.id

    # A second league, to prove nothing crosses between them.
    other = League(name="WP3B Other", season=SEASON)
    db.add(other)
    db.flush()
    OTHER_LEAGUE_ID = other.id

    TEAMS: list[int] = []
    for i in range(4):
        t = Team(team_name=f"Team {i + 1}", owner=f"Owner {i + 1}",
                 email=f"gm{i + 1}@wp3b.test", league_id=LEAGUE_ID)
        db.add(t)
        db.flush()
        TEAMS.append(t.id)
        db.add(Wallet(team_id=t.id, balance=0.0))
        db.add(User(email=f"gm{i + 1}@wp3b.test", hashed_password=hashed,
                    team_id=t.id, role="gm"))

    other_team = Team(team_name="Other Team", owner="Other Owner",
                      email="other@wp3b.test", league_id=OTHER_LEAGUE_ID)
    db.add(other_team)
    db.flush()
    OTHER_TEAM = other_team.id
    db.add(Wallet(team_id=other_team.id, balance=0.0))

    comm_team = Team(team_name="WP3B Commissioners", owner="Comm",
                     email="comm@wp3b.test", league_id=LEAGUE_ID)
    db.add(comm_team)
    db.flush()
    COMM_TEAM = comm_team.id
    db.add(Wallet(team_id=COMM_TEAM, balance=0.0))
    comm = User(email="comm@wp3b.test", hashed_password=hashed,
                team_id=COMM_TEAM, role="commissioner")
    db.add(comm)
    db.flush()
    db.add(LeagueCommissioner(league_id=LEAGUE_ID, user_id=comm.id,
                              source="bootstrap"))

    # An outsider: a real signed-in user who owns no team in this league.
    db.add(User(email="outsider@wp3b.test", hashed_password=hashed,
                team_id=OTHER_TEAM, role="gm"))

    # One matchup per Versus pairing, so the Bet rows have a league-scoped home.
    m1 = Matchup(league_id=LEAGUE_ID, week=WEEK, home_team_id=TEAMS[0],
                 away_team_id=TEAMS[1], home_score=0.0, away_score=0.0)
    m2 = Matchup(league_id=LEAGUE_ID, week=WEEK, home_team_id=TEAMS[2],
                 away_team_id=TEAMS[3], home_score=0.0, away_score=0.0)
    db.add_all([m1, m2])
    db.flush()
    M1, M2 = m1.id, m2.id

    db.commit()

T1, T2, T3, T4 = TEAMS
ALL_TEAMS = TEAMS + [COMM_TEAM]

# ── Noncompetitive movement, for every team ──────────────────────────────────
#
# None of this may reach a competitive NET. It is posted for all five teams so
# that a model which failed to exclude it would be wrong for all five, not for
# one that could be mistaken for a fixture quirk.

for team_id in ALL_TEAMS:
    ledger_post([
        (min_reserve_account(team_id), OPENING_MIN_RESERVE),
        (f"reserve:{team_id}", OPENING_RESERVE),
        ("world", -(OPENING_MIN_RESERVE + OPENING_RESERVE)),
    ], door="season_allocation")
    ledger_post([
        (min_account(team_id, WEEK), WEEK_MIN_RELEASED),
        (min_reserve_account(team_id), -WEEK_MIN_RELEASED),
    ], door="weekly_minimum_release")

# T2 receives a large approved Top-Off. THIS IS THE DISCRIMINATOR: it makes T2
# the richest GM in the league by a wide margin while T2 is, competitively, last.
ledger_post([
    (f"bab_issuance:{LEAGUE_ID}:{SEASON}", -TOPOFF_BIG),
    (wallet_account(T2), TOPOFF_BIG),
], door="approved_bab_topoff")

# A Skunk assessment against T1 — an obligation, not a competitive result.
ledger_post([
    (receivable_account(T1), -50_00),
    (f"skunk:{LEAGUE_ID}", 50_00),
], door="skunk_assessment")


# ── Versus: one settled wager (T1 beats T2) ──────────────────────────────────

with SessionLocal() as db:
    expires = datetime.now(timezone.utc) + timedelta(days=1)
    challenge = BeefChallenge(
        challenger_team_id=T1, challenged_team_id=T2, week=WEEK,
        bet_type="straight", amount=VERSUS_STAKE / 100.0,
        challenger_odds=1.909, challenged_odds=1.909,
        challenger_moneyline=-110, challenged_moneyline=-110,
        status="accepted", expires_at=expires)
    db.add(challenge)
    db.flush()

    w1 = db.query(Wallet).filter(Wallet.team_id == T1).first()
    w2 = db.query(Wallet).filter(Wallet.team_id == T2).first()
    b1 = Bet(matchup_id=M1, wallet_id=w1.id, picked_team_id=T1,
             bet_type="straight", amount=VERSUS_STAKE / 100.0, odds=1.909,
             status="won", beef_challenge_id=challenge.id,
             settled_at=datetime.now(timezone.utc))
    b2 = Bet(matchup_id=M1, wallet_id=w2.id, picked_team_id=T2,
             bet_type="straight", amount=VERSUS_STAKE / 100.0, odds=1.909,
             status="lost", beef_challenge_id=challenge.id,
             settled_at=datetime.now(timezone.utc))
    db.add_all([b1, b2])
    db.flush()
    B1, B2 = b1.id, b2.id

    # An OPEN wager for T3 — placed, escrowed, never settled.
    open_challenge = BeefChallenge(
        challenger_team_id=T3, challenged_team_id=T4, week=WEEK,
        bet_type="straight", amount=OPEN_STAKE / 100.0,
        challenger_odds=1.909, challenged_odds=1.909,
        challenger_moneyline=-110, challenged_moneyline=-110,
        status="accepted", expires_at=expires)
    db.add(open_challenge)
    db.flush()
    w3 = db.query(Wallet).filter(Wallet.team_id == T3).first()
    b3 = Bet(matchup_id=M2, wallet_id=w3.id, picked_team_id=T3,
             bet_type="straight", amount=OPEN_STAKE / 100.0, odds=1.909,
             status="pending", beef_challenge_id=open_challenge.id)
    db.add(b3)
    db.flush()
    B3 = b3.id
    db.commit()

# Both sides stake out of their released Weekly Minimum, exactly as
# `plan_spend_split` funds MIN FIRST.
ledger_post([
    (min_account(T1, WEEK), -VERSUS_STAKE),
    (f"escrow:{B1}", VERSUS_STAKE),
], door="wager_placed")
ledger_post([
    (min_account(T2, WEEK), -VERSUS_STAKE),
    (f"escrow:{B2}", VERSUS_STAKE),
], door="wager_placed")
# Settlement: both escrows drain into the winner's wallet.
ledger_post([
    (f"escrow:{B1}", -VERSUS_STAKE),
    (f"escrow:{B2}", -VERSUS_STAKE),
    (wallet_account(T1), 2 * VERSUS_STAKE),
], door="wager_settled")

# T3's open stake. Posted, escrowed, unresolved.
ledger_post([
    (min_account(T3, WEEK), -OPEN_STAKE),
    (f"escrow:{B3}", OPEN_STAKE),
], door="wager_placed")


# ── Pools: everyone pays the weekly entry out of `min:`; T2 wins the pot ─────

POOL_POT = POOL_ENTRY * len(ALL_TEAMS)
ledger_post(
    [(min_account(t, WEEK), -POOL_ENTRY) for t in ALL_TEAMS]
    + [(f"pool:{LEAGUE_ID}", POOL_POT)],
    door="pool_weekly_collection")
ledger_post([
    (f"pool:{LEAGUE_ID}", -POOL_POT),
    (wallet_account(T2), POOL_POT),
], door="pool_winner_distribution")


# ── Expected competitive figures ─────────────────────────────────────────────

EXPECTED_VERSUS = {
    T1: -VERSUS_STAKE + 2 * VERSUS_STAKE,   # staked, then took both sides
    T2: -VERSUS_STAKE,                      # staked and lost it
    T3: 0,                                  # staked, still in escrow: level
    T4: 0,
    COMM_TEAM: 0,
}
EXPECTED_POOL = {
    T1: -POOL_ENTRY,
    T2: -POOL_ENTRY + POOL_POT,
    T3: -POOL_ENTRY,
    T4: -POOL_ENTRY,
    COMM_TEAM: -POOL_ENTRY,
}
EXPECTED_NET = {t: EXPECTED_VERSUS[t] + EXPECTED_POOL[t] for t in ALL_TEAMS}


# ── 1 · The derivation ───────────────────────────────────────────────────────

_section("1 · Competitive NET is derived from posted state, door by door")

with SessionLocal() as db:
    STANDINGS = league_standings(db, league_id=LEAGUE_ID, acting_team_id=T3)
    BY_ID = {r.team_id: r for r in STANDINGS.rows}

_assert("the ledger balances after the whole fixture",
        trial_balance() == 0, str(trial_balance()))
_assert("every team in the league has a row",
        sorted(BY_ID) == sorted(ALL_TEAMS))
_assert("no team from another league appears",
        OTHER_TEAM not in BY_ID)

for team_id in ALL_TEAMS:
    _assert(f"team {team_id}: Versus NET is exact",
            BY_ID[team_id].versus_net_cents == EXPECTED_VERSUS[team_id],
            f"{BY_ID[team_id].versus_net_cents} vs {EXPECTED_VERSUS[team_id]}")
    _assert(f"team {team_id}: Pool NET is exact",
            BY_ID[team_id].pool_net_cents == EXPECTED_POOL[team_id],
            f"{BY_ID[team_id].pool_net_cents} vs {EXPECTED_POOL[team_id]}")
    _assert(f"team {team_id}: combined NET is Versus + Pool",
            BY_ID[team_id].net_cents == EXPECTED_NET[team_id],
            f"{BY_ID[team_id].net_cents} vs {EXPECTED_NET[team_id]}")


_section("2 · Noncompetitive movement is excluded from every NET")

# Every one of these moved spendable Credits and none is a competitive result.
# The proof is arithmetic: T4 played no Versus and received allocation, weekly
# release and nothing else, so its Versus NET must be exactly zero — and T2's
# 50,000-cent Top-Off must be absent from a NET of −1,000.29 + 39,912.
_assert("season allocation does not enter a NET",
        BY_ID[T4].versus_net_cents == 0, str(BY_ID[T4].versus_net_cents))
_assert("Weekly Minimum release does not enter a NET",
        BY_ID[COMM_TEAM].versus_net_cents == 0,
        str(BY_ID[COMM_TEAM].versus_net_cents))
_assert("an approved Top-Off does not enter a NET",
        BY_ID[T2].versus_net_cents == -VERSUS_STAKE,
        str(BY_ID[T2].versus_net_cents))
_assert("a Skunk assessment does not enter a NET",
        BY_ID[T1].versus_net_cents == VERSUS_STAKE,
        str(BY_ID[T1].versus_net_cents))
_assert("the season_allocation door is in neither competitive set",
        "season_allocation" not in VERSUS_DOORS
        and "season_allocation" not in POOL_DOORS)
_assert("the approved_bab_topoff door is in neither competitive set",
        "approved_bab_topoff" not in VERSUS_DOORS
        and "approved_bab_topoff" not in POOL_DOORS)
for door in ("weekly_minimum_release", "weekly_minimum_expiry",
             "skunk_assessment", "skunk_distribution",
             "championship_distribution", "championship_reserve_sweep"):
    _assert(f"the {door} door is in neither competitive set",
            door not in VERSUS_DOORS and door not in POOL_DOORS)


_section("3 · An unsettled wager is not a loss")

_assert("T3's Versus NET is level, not down by the stake",
        BY_ID[T3].versus_net_cents == 0,
        f"{BY_ID[T3].versus_net_cents}, stake was −{OPEN_STAKE}")

with SessionLocal() as db:
    from sqlalchemy import text
    raw_t3 = db.execute(text(
        "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
        "WHERE door IN ('wager_placed','wager_settled') "
        "AND (account = :w OR account LIKE :m)"),
        {"w": wallet_account(T3), "m": f"min:{T3}:%"}).scalar()
_assert("so the add-back is doing the work, not an absent posting",
        int(raw_t3) == -OPEN_STAKE,
        f"raw door sum {raw_t3}, reported NET {BY_ID[T3].versus_net_cents}")


_section("4 · Spend funded from the Weekly Minimum is counted")

# The Pool entry never touched `wallet:` for any team — it was funded entirely
# out of `min:`. A wallet-only sum would report every Pool NET as if no entry
# had ever been paid.
with SessionLocal() as db:
    from sqlalchemy import text
    wallet_only = db.execute(text(
        "SELECT COALESCE(SUM(amount_cents),0) FROM ledger_entries "
        "WHERE door = 'pool_weekly_collection' AND account = :w"),
        {"w": wallet_account(T4)}).scalar()
_assert("the Pool entry touched no wallet account", int(wallet_only) == 0)
_assert("and it is still counted in the Pool NET",
        BY_ID[T4].pool_net_cents == -POOL_ENTRY,
        str(BY_ID[T4].pool_net_cents))


_section("5 · Records and wins are counted, not inferred from money")

_assert("T1 is 1-0", BY_ID[T1].versus_record == "1-0", BY_ID[T1].versus_record)
_assert("T2 is 0-1", BY_ID[T2].versus_record == "0-1", BY_ID[T2].versus_record)
_assert("T3's open wager is in no record yet",
        BY_ID[T3].versus_record == "0-0", BY_ID[T3].versus_record)
_assert("T4 played none", BY_ID[T4].versus_record == "0-0")
_assert("T2 won one Pool", BY_ID[T2].pool_wins == 1, str(BY_ID[T2].pool_wins))
_assert("nobody else won a Pool",
        all(BY_ID[t].pool_wins == 0 for t in ALL_TEAMS if t != T2))
_assert("a Pool win is counted even though T2's Pool NET is positive and its "
        "Versus NET is negative — the two are independent",
        BY_ID[T2].pool_wins == 1 and BY_ID[T2].versus_net_cents < 0
        and BY_ID[T2].pool_net_cents > 0)


_section("6 · Overall does NOT rank by Wallet")

with SessionLocal() as db:
    from ledger.ledger import _balance_of_in_session
    WALLETS = {t: _balance_of_in_session(db, wallet_account(t))
               for t in ALL_TEAMS}

wallet_order = sorted(ALL_TEAMS, key=lambda t: (-WALLETS[t], t))
overall_order = [r.team_id for r in STANDINGS.overall]

_assert("T2 holds the largest Wallet in the league",
        max(WALLETS, key=lambda t: WALLETS[t]) == T2,
        f"wallets {WALLETS}")
_assert("and T2 finishes LAST on Overall",
        overall_order[-1] == T2, f"overall {overall_order}")
_assert("the Overall order is not the Wallet order",
        overall_order != wallet_order,
        f"overall {overall_order} vs wallet {wallet_order}")
_assert("Overall is descending by combined competitive NET",
        overall_order == sorted(ALL_TEAMS,
                                key=lambda t: (-EXPECTED_NET[t], t)),
        f"{overall_order}")
_assert("Versus is descending by Versus NET",
        [r.team_id for r in STANDINGS.versus]
        == sorted(ALL_TEAMS, key=lambda t: (-EXPECTED_VERSUS[t], t)))
_assert("Pools is descending by Pool NET",
        [r.team_id for r in STANDINGS.pools]
        == sorted(ALL_TEAMS, key=lambda t: (-EXPECTED_POOL[t], t)))

# T3, T4 and the commissioner team are all on exactly −POOL_ENTRY for Pools.
tied = [t for t in ALL_TEAMS if EXPECTED_POOL[t] == -POOL_ENTRY]
_assert("the tie case is real — three teams share a Pool NET",
        len(tied) >= 3, str(tied))
_assert("ties are broken by ascending team id, deterministically",
        [r.team_id for r in STANDINGS.pools if r.pool_net_cents == -POOL_ENTRY]
        == sorted(tied))
_assert("the three orderings are three views of ONE row set",
        {id(r) for r in STANDINGS.overall} == {id(r) for r in STANDINGS.versus}
        == {id(r) for r in STANDINGS.pools})


_section("7 · No accounting state leaks into the competitive projection")

FORBIDDEN = ("wallet", "available", "current_settle", "settle", "obligation",
             "advance", "receivable", "topoff", "top_off", "reserve",
             "in_play", "held", "expired_min")
row_keys = set(BY_ID[T1].as_dict())
_assert("the row exposes no accounting field",
        not any(any(f in key for f in FORBIDDEN) for key in row_keys),
        " ".join(sorted(row_keys)))
# FINAL POR §8 — `skunk_fees_cents` JOINS THE PROJECTION, DELIBERATELY.
#
# The FORBIDDEN list above still governs and still passes: Skunk's ACCOUNTING
# face is `receivable:`, which is an obligation and stays out of this row. What
# is added here is its COMPETITIVE face — the third term of FantasyStakes Score
# and the SKUNK standings column — carried as a positive magnitude that
# `net_cents` has already subtracted.
#
# The pairing of the two assertions is the point: a competitive penalty is
# reported, an obligation is not, and the row still exposes nobody's balance.
_assert("the row exposes exactly the competitive projection",
        row_keys == {"team_id", "team_name", "owner", "versus_wins",
                     "versus_losses", "versus_pushes", "versus_record",
                     "pool_wins", "versus_net_cents", "pool_net_cents",
                     "skunk_fees_cents", "net_cents"},
        " ".join(sorted(row_keys)))
_assert("  · a legacy-ruleset season reports zero Skunk and a two-term Score",
        BY_ID[T1].skunk_fees_cents == 0
        and BY_ID[T1].net_cents == (BY_ID[T1].versus_net_cents
                                    + BY_ID[T1].pool_net_cents),
        f"skunk={BY_ID[T1].skunk_fees_cents} net={BY_ID[T1].net_cents}")
_assert("the acting team is named so the UI need not match on a name",
        STANDINGS.acting_team_id == T3, str(STANDINGS.acting_team_id))


# ── 8 · The route ────────────────────────────────────────────────────────────

_section("8 · GET /league/{id}/standings")


def _client() -> TestClient:
    return TestClient(app)


def _sign_in(client: TestClient, email: str) -> None:
    r = client.post("/auth/session", json={"email": email,
                                           "password": PASSWORD})
    assert r.status_code == 200, r.text


with _client() as client:
    _sign_in(client, "gm3@wp3b.test")
    resp = client.get(f"/league/{LEAGUE_ID}/standings")
    _assert("a signed-in member may read it", resp.status_code == 200,
            str(resp.status_code))
    body = resp.json() if resp.status_code == 200 else {}

    _assert("it names the acting team",
            body.get("acting_team_id") == T3, str(body.get("acting_team_id")))
    _assert("it carries three orderings",
            {"overall", "versus", "pools"} <= set(body),
            " ".join(sorted(body)))
    _assert("overall is ranked from 1",
            [r["rank"] for r in body.get("overall", [])]
            == list(range(1, len(ALL_TEAMS) + 1)),
            str([r["rank"] for r in body.get("overall", [])]))
    _assert("the served overall order matches the model",
            [r["team_id"] for r in body.get("overall", [])] == overall_order)
    _assert("cents are served exact, not rounded",
            all(isinstance(r["net_cents"], int)
                for r in body.get("overall", [])))
    _assert("the served figures are the model's figures",
            all(r["net_cents"] == EXPECTED_NET[r["team_id"]]
                for r in body.get("overall", [])))
    _assert("no accounting field is served",
            not any(any(f in k for f in FORBIDDEN)
                    for r in body.get("overall", []) for k in r),
            " ".join(sorted(body.get("overall", [{}])[0])))

with _client() as client:
    _sign_in(client, "outsider@wp3b.test")
    resp = client.get(f"/league/{LEAGUE_ID}/standings")
    _assert("a signed-in non-member is refused",
            resp.status_code == 403, str(resp.status_code))

with _client() as client:
    resp = client.get(f"/league/{LEAGUE_ID}/standings")
    _assert("an anonymous caller is refused",
            resp.status_code in (401, 403), str(resp.status_code))

with _client() as client:
    _sign_in(client, "gm1@wp3b.test")
    resp = client.get(f"/league/{OTHER_LEAGUE_ID}/standings")
    _assert("a member of one league cannot read another's standings",
            resp.status_code == 403, str(resp.status_code))


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 66)
if _failures:
    print(f"WP3B STANDINGS READ MODEL — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("WP3B STANDINGS READ MODEL — all assertions PASSED")
