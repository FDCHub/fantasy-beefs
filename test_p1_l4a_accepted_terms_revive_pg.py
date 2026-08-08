"""
test_p1_l4a_accepted_terms_revive_pg.py — P1-L4A targeted suite.

WHAT THIS PACKAGE FIXES, AND WHY EACH FIXTURE IS DISCRIMINATING.

B-1 — ACCEPTED BET ROWS MUST CARRY THE ACCEPTED PROPOSAL'S TERMS.
    BeefChallenge.line/.side are legacy NOT NULL mirror columns written once at
    issue from proposal version 1; proposal_lifecycle's own comment says "the new
    model never reads them". A Refresh & Relock counter freezes a NEW line on
    version 2 and never touches the container. accept_funded_challenge built its
    Bet rows from the container, so a countered Spread settled on version 1's
    stale line.

    EVERY FIXTURE HERE USES A DIFFERENT LINE ON THE COUNTER. The pre-fix
    implementation reads 3.5 where the parties accepted 10.5, so each assertion
    below fails against it. The old P1-L4 suite could not have caught this: every
    fixture in it is wager_type="straight", the one launch wager type for which
    line and side are unused.

    A SECOND DEFECT LIVES IN THE SAME PLACE. A proposal freezes ONE market
    position; the two Bet rows are the two sides of it, so the second must be
    MIRRORED (Spread negates the line, Over/Under flips the side). The pre-fix
    code gave both rows identical terms. Settlement evaluates whichever row it
    reaches first and infers the other as the complement, so unmirrored rows make
    the outcome depend on row order:

        accepted line 3.0, actual margin +1.0
          anchor row  :  1.0 > 3.0 → lost → winner = derived   ✔
          derived row : -1.0 > 3.0 → lost → winner = anchor    ✘ contradiction

SETTLEMENT INTEGRATION. SETTLE-* drives issue → counter → accept → settle_week
through the real settlement engine. The margin is chosen so the stale line and
the accepted line elect DIFFERENT WINNERS: margin +7.0 against accepted line
10.5 means the Anchor fails to cover and the Derived side wins, while the stale
3.5 would have handed it to the Anchor. Settling to the wrong team is the
failure mode, not merely a wrong stored column.

B-2 — A REVIVED CHALLENGE MUST NOT EXIST WITHOUT REAL ANCHOR ESCROW.
    spec1.revive_challenge() creates a new challenge and proposal but posts
    nothing and never commits. Before P1-L4A there was no funded wrapper, so the
    only way to commit a revived challenge was to commit Spec 1's half alone —
    an escrow-less challenge. REVIVE-* proves the new seam funds it through the
    same algorithm as any other issue.

Runs on real PostgreSQL: the lifecycle takes SELECT ... FOR UPDATE row locks.

    $env:TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5433/fantasy_test"
    python test_p1_l4a_accepted_terms_revive_pg.py
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# This suite's labels contain arrows and section rules. A Windows console
# defaults to cp1252, which cannot encode them, and the resulting
# UnicodeEncodeError would abort the run partway through and read as a test
# failure rather than a console limitation.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from test_support_postgres import setup_postgres_test_db

tdb = setup_postgres_test_db()

import atexit
atexit.register(lambda: tdb.teardown())

from db.schema import (
    BeefChallenge, BeefProposal, Bet, ChallengeFundingLeg, League, Matchup,
    ProtocolEvent, Team, Wallet,
)
from ledger.ledger import balance_of, post as ledger_post, trial_balance
from beefs import proposal_lifecycle as spec1
from economy import challenge_funding as cf
from economy.challenge_funding import InsufficientFundingCapacityError

REPO = Path(__file__).resolve().parent
WEEK = 1

_passes = 0
_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passes
    if condition:
        _passes += 1
        print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))
    else:
        _failures.append(label)
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{title}")


# ── Fixtures ──────────────────────────────────────────────────────────────────

def seed(wallet_cents: dict[str, int], min_cents: dict[str, int] | None = None) -> dict:
    """A league, its teams and wallets, one matchup, and seeded ledger balances.
    The float Wallet.balance mirror is set DELIBERATELY WRONG so nothing here can
    pass by consulting it."""
    min_cents = min_cents or {}
    ids: dict = {}
    with tdb.SessionLocal() as db:
        league = League(season=2025, name="P1-L4A League")
        db.add(league); db.flush()
        for name in wallet_cents:
            team = Team(league_id=league.id, team_name=name, owner=f"o-{name}",
                        email=f"{name}-{uuid.uuid4().hex[:8]}@p1l4a.test")
            db.add(team); db.flush()
            db.add(Wallet(team_id=team.id, balance=99_999.0))   # wrong on purpose
            ids[name] = team.id
        names = list(wallet_cents)
        db.add(Matchup(league_id=league.id, week=WEEK,
                       home_team_id=ids[names[0]], away_team_id=ids[names[1]],
                       home_score=0.0, away_score=0.0))
        for name, cents in wallet_cents.items():
            if cents:
                ledger_post([("world", -cents), (f"wallet:{ids[name]}", cents)],
                            door="buy_in_paid", session=db)
        for name, cents in min_cents.items():
            if cents:
                ledger_post([("world", -cents), (f"min:{ids[name]}:{WEEK}", cents)],
                            door="buy_in_paid", session=db)
        ids["_league"] = league.id
        db.commit()
    return ids


def terms(anchor_cents: int, derived_cents: int = 0, *,
          line: float | None = None, side: str | None = None,
          player_id: int | None = None) -> spec1.ProposalTerms:
    return spec1.ProposalTerms(
        line                       = line,
        side                       = side,
        player_id                  = player_id,
        anchor_stake_cents         = anchor_cents,
        quoted_derived_stake_cents = derived_cents,
        anchor_odds                = 1.909,
        derived_odds               = 1.909,
        anchor_moneyline           = -110,
        derived_moneyline          = -110,
    )


def issue(ids, challenger, challenged, anchor, derived=0, *,
          wager_type="straight", **tkw):
    with tdb.SessionLocal() as db:
        return cf.issue_funded_challenge(
            event_id=uuid.uuid4(), league_id=ids["_league"], week=WEEK,
            challenger_team_id=ids[challenger], challenged_team_id=ids[challenged],
            wager_type=wager_type, terms=terms(anchor, derived, **tkw), db=db)


def bets_for(challenge_id: int) -> dict[int, Bet]:
    """The challenge's Bet rows, keyed by picked/owning team id. Detached copies
    of the fields under test, read after commit."""
    with tdb.SessionLocal() as db:
        rows = db.query(Bet).filter(Bet.beef_challenge_id == challenge_id).all()
        out = {}
        for b in rows:
            wallet = db.query(Wallet).filter(Wallet.id == b.wallet_id).one()
            out[wallet.team_id] = {
                "id": b.id, "bet_type": b.bet_type, "line": b.line,
                "side": b.side, "picked_team_id": b.picked_team_id,
                "player_id": b.player_id, "amount": b.amount, "status": b.status,
            }
        return out


def challenge_row(challenge_id: int) -> dict:
    with tdb.SessionLocal() as db:
        c = db.query(BeefChallenge).filter(BeefChallenge.id == challenge_id).one()
        return {
            "response_status": c.response_status,
            "line": c.line, "side": c.side, "wager_type": c.wager_type,
            "active_proposal_id": c.active_proposal_id,
            "accepted_proposal_id": c.accepted_proposal_id,
            "revived_from_challenge_id": c.revived_from_challenge_id,
            "challenger_team_id": c.challenger_team_id,
            "challenged_team_id": c.challenged_team_id,
            "week": c.week, "league_id": c.league_id,
            "challenge_mode": c.challenge_mode,
        }


def proposal_row(proposal_id: int) -> dict:
    with tdb.SessionLocal() as db:
        p = db.query(BeefProposal).filter(BeefProposal.id == proposal_id).one()
        return {"line": p.line, "side": p.side, "player_id": p.player_id,
                "version_number": p.version_number,
                "anchor_stake_cents": p.anchor_stake_cents,
                "quoted_derived_stake_cents": p.quoted_derived_stake_cents}


def legs_for(challenge_id: int) -> list[dict]:
    with tdb.SessionLocal() as db:
        rows = (db.query(ChallengeFundingLeg)
                .filter(ChallengeFundingLeg.challenge_id == challenge_id)
                .order_by(ChallengeFundingLeg.sequence_number).all())
        return [{"seq": r.sequence_number, "source": r.source_account,
                 "dest": r.destination_account, "cents": r.amount_cents,
                 "kind": r.leg_kind, "team_id": r.team_id} for r in rows]


def escrow_of(challenge_id: int) -> int:
    return balance_of(f"escrow:challenge:{challenge_id}")


def conservation(label: str) -> None:
    check(f"{label}: trial balance closes to exactly zero", trial_balance() == 0,
          f"got {trial_balance()}")


def set_scores(league_id: int, home: float, away: float) -> None:
    with tdb.SessionLocal() as db:
        m = (db.query(Matchup)
             .filter(Matchup.league_id == league_id, Matchup.week == WEEK).one())
        m.home_score = home
        m.away_score = away
        db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# B-1 — SPREAD: accepted proposal terms, mirrored across the two sides
# ══════════════════════════════════════════════════════════════════════════════
section("TERMS-1: countered SPREAD accepts the COUNTER's line, not version 1's")

STALE_LINE    = 3.5      # frozen on version 1 and mirrored onto the container
ACCEPTED_LINE = 10.5     # frozen on version 2 — what the parties actually accepted

ids = seed({"alpha": 500_000, "beta": 500_000})
r = issue(ids, "alpha", "beta", 100_000, 75_000,
          wager_type="spread", line=STALE_LINE)
CH = r.challenge_id
v1 = challenge_row(CH)["active_proposal_id"]

with tdb.SessionLocal() as db:
    cf.counter_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=ids["beta"],
        terms=terms(100_000, 75_000, line=ACCEPTED_LINE), db=db)
v2 = challenge_row(CH)["active_proposal_id"]

with tdb.SessionLocal() as db:
    acc = cf.accept_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=ids["alpha"], db=db)

chal = challenge_row(CH)
bets = bets_for(CH)
anchor_bet  = bets[ids["alpha"]]
derived_bet = bets[ids["beta"]]

check("TERMS-1: the counter really did create a distinct version 2",
      v2 != v1 and proposal_row(v2)["version_number"] == 2,
      f"v1={v1} v2={v2}")
check("TERMS-1: FIXTURE CONTROL — the two versions carry DIFFERENT lines, so a "
      "wrong implementation cannot pass by accident",
      proposal_row(v1)["line"] == STALE_LINE
      and proposal_row(v2)["line"] == ACCEPTED_LINE,
      f"v1={proposal_row(v1)['line']} v2={proposal_row(v2)['line']}")
check("TERMS-1: FIXTURE CONTROL — the legacy container mirror still holds the "
      "STALE version-1 line, which is the value the defect used",
      chal["line"] == STALE_LINE, f"challenge.line={chal['line']}")
check("TERMS-1: the accepted proposal is version 2",
      chal["accepted_proposal_id"] == v2)

check("TERMS-1: the ANCHOR Bet uses the ACCEPTED line",
      anchor_bet["line"] == ACCEPTED_LINE, f"got {anchor_bet['line']}")
check("TERMS-1: the ANCHOR Bet does NOT use version 1's stale line",
      anchor_bet["line"] != STALE_LINE)
check("TERMS-1: the DERIVED Bet mirrors the ACCEPTED line (negated — the "
      "challenged side wins if the challenger fails to cover)",
      derived_bet["line"] == -ACCEPTED_LINE, f"got {derived_bet['line']}")
check("TERMS-1: the DERIVED Bet does NOT use version 1's stale line in either "
      "sign", derived_bet["line"] not in (STALE_LINE, -STALE_LINE))
check("TERMS-1: the two Spread sides are COMPLEMENTARY, not two copies of one "
      "position", anchor_bet["line"] == -derived_bet["line"] != 0)
check("TERMS-1: bet_type stays CHALLENGE-level (§5 — the wager class lives once, "
      "on the challenge)",
      anchor_bet["bet_type"] == derived_bet["bet_type"] == "spread"
      and chal["wager_type"] == "spread")
check("TERMS-1: Spread carries each team's own pick",
      anchor_bet["picked_team_id"] == ids["alpha"]
      and derived_bet["picked_team_id"] == ids["beta"])
check("TERMS-1: Spread carries no side", anchor_bet["side"] is None
      and derived_bet["side"] is None)
check("TERMS-1: asymmetric stakes land on the right sides",
      anchor_bet["amount"] == 1000.0 and derived_bet["amount"] == 750.0,
      f"anchor={anchor_bet['amount']} derived={derived_bet['amount']}")
check("TERMS-1: the container mirror was NOT rewritten to agree — the proposal "
      "remains the sole authority",
      chal["line"] == STALE_LINE and proposal_row(v2)["line"] == ACCEPTED_LINE)
conservation("TERMS-1")


# ══════════════════════════════════════════════════════════════════════════════
section("TERMS-2: countered OVER_UNDER accepts the counter's total and flips "
        "the side")

OU_STALE    = 200.5
OU_ACCEPTED = 240.5

ids = seed({"alpha": 500_000, "beta": 500_000})
r = issue(ids, "alpha", "beta", 100_000, 75_000,
          wager_type="over_under", line=OU_STALE, side="over")
CH = r.challenge_id
v1 = challenge_row(CH)["active_proposal_id"]

with tdb.SessionLocal() as db:
    cf.counter_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=ids["beta"],
        terms=terms(100_000, 75_000, line=OU_ACCEPTED, side="over"), db=db)
v2 = challenge_row(CH)["active_proposal_id"]

with tdb.SessionLocal() as db:
    cf.accept_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=ids["alpha"], db=db)

chal = challenge_row(CH)
bets = bets_for(CH)
anchor_bet  = bets[ids["alpha"]]
derived_bet = bets[ids["beta"]]

check("TERMS-2: FIXTURE CONTROL — the two versions carry DIFFERENT totals",
      proposal_row(v1)["line"] == OU_STALE
      and proposal_row(v2)["line"] == OU_ACCEPTED)
check("TERMS-2: FIXTURE CONTROL — the container still mirrors the stale total",
      chal["line"] == OU_STALE)
check("TERMS-2: the ANCHOR Bet uses the ACCEPTED total",
      anchor_bet["line"] == OU_ACCEPTED, f"got {anchor_bet['line']}")
check("TERMS-2: the DERIVED Bet uses the ACCEPTED total (same total, both sides "
      "of one number)", derived_bet["line"] == OU_ACCEPTED,
      f"got {derived_bet['line']}")
check("TERMS-2: neither Bet uses the stale total",
      OU_STALE not in (anchor_bet["line"], derived_bet["line"]))
check("TERMS-2: the ANCHOR keeps the accepted proposal's side",
      anchor_bet["side"] == "over", f"got {anchor_bet['side']}")
check("TERMS-2: the DERIVED side is FLIPPED — the two sides are complementary "
      "positions on one total", derived_bet["side"] == "under",
      f"got {derived_bet['side']}")
check("TERMS-2: over_under carries no pick on either side (schema: "
      "picked_team_id is null for o/u)",
      anchor_bet["picked_team_id"] is None
      and derived_bet["picked_team_id"] is None)
check("TERMS-2: bet_type stays challenge-level",
      anchor_bet["bet_type"] == derived_bet["bet_type"] == "over_under")
conservation("TERMS-2")


# ══════════════════════════════════════════════════════════════════════════════
section("TERMS-3: straight (Moneyline) is unchanged — no line, no side, own pick")

ids = seed({"alpha": 500_000, "beta": 500_000})
r = issue(ids, "alpha", "beta", 100_000, 75_000, wager_type="straight")
CH = r.challenge_id
with tdb.SessionLocal() as db:
    cf.accept_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=ids["beta"], db=db)

bets = bets_for(CH)
check("TERMS-3: neither straight Bet carries a line",
      bets[ids["alpha"]]["line"] is None and bets[ids["beta"]]["line"] is None)
check("TERMS-3: neither straight Bet carries a side",
      bets[ids["alpha"]]["side"] is None and bets[ids["beta"]]["side"] is None)
check("TERMS-3: each straight Bet picks its own team",
      bets[ids["alpha"]]["picked_team_id"] == ids["alpha"]
      and bets[ids["beta"]]["picked_team_id"] == ids["beta"])
check("TERMS-3: player_id follows the proposal and is null when unset",
      bets[ids["alpha"]]["player_id"] is None)
conservation("TERMS-3")


# ══════════════════════════════════════════════════════════════════════════════
# SETTLEMENT INTEGRATION — the corrected terms must survive to settlement
# ══════════════════════════════════════════════════════════════════════════════
section("SETTLE-4: issue → counter → accept → settle_week on the ACCEPTED line")

from betting.settlement_engine import settle_week

ids = seed({"alpha": 500_000, "beta": 500_000})
ANCHOR_CENTS, DERIVED_CENTS = 100_000, 75_000

r = issue(ids, "alpha", "beta", ANCHOR_CENTS, DERIVED_CENTS,
          wager_type="spread", line=STALE_LINE)
CH = r.challenge_id
with tdb.SessionLocal() as db:
    cf.counter_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=ids["beta"],
        terms=terms(ANCHOR_CENTS, DERIVED_CENTS, line=ACCEPTED_LINE), db=db)
with tdb.SessionLocal() as db:
    acc = cf.accept_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=ids["alpha"], db=db)

A_BET, D_BET = acc.anchor_bet_id, acc.derived_bet_id

check("SETTLE-4: real Anchor Bet escrow holds the accepted Anchor",
      balance_of(f"escrow:{A_BET}") == ANCHOR_CENTS,
      f"got {balance_of(f'escrow:{A_BET}')}")
check("SETTLE-4: real Derived Bet escrow holds the accepted Derived stake",
      balance_of(f"escrow:{D_BET}") == DERIVED_CENTS,
      f"got {balance_of(f'escrow:{D_BET}')}")
check("SETTLE-4: the two escrows are ASYMMETRIC, so a symmetric-pot shortcut "
      "cannot pass", ANCHOR_CENTS != DERIVED_CENTS)
check("SETTLE-4: challenge escrow is fully migrated out", escrow_of(CH) == 0)

alpha_before = balance_of(f"wallet:{ids['alpha']}")
beta_before  = balance_of(f"wallet:{ids['beta']}")

# alpha 107.0 vs beta 100.0 → margin +7.0.
#   accepted line 10.5 → 7.0 > 10.5 is FALSE → the Anchor fails to cover → BETA wins
#   stale line     3.5 → 7.0 >  3.5 is TRUE  → ALPHA would win
# The two answers name different teams, so this settles the question.
set_scores(ids["_league"], home=107.0, away=100.0)

with tdb.SessionLocal() as db:
    report = settle_week(WEEK, db, league_id=ids["_league"])

bets = bets_for(CH)
check("SETTLE-4: settlement ran and settled both sides of the beef",
      bets[ids["alpha"]]["status"] in ("won", "lost")
      and bets[ids["beta"]]["status"] in ("won", "lost"),
      f"alpha={bets[ids['alpha']]['status']} beta={bets[ids['beta']]['status']}")
check("SETTLE-4: THE ACCEPTED LINE DECIDED IT — margin +7.0 does not cover the "
      "accepted 10.5, so the DERIVED side wins",
      bets[ids["beta"]]["status"] == "won"
      and bets[ids["alpha"]]["status"] == "lost",
      f"alpha={bets[ids['alpha']]['status']} beta={bets[ids['beta']]['status']}")
check("SETTLE-4: the STALE 3.5 line would have elected the Anchor instead — the "
      "wrong-terms outcome is excluded, not merely unobserved",
      bets[ids["alpha"]]["status"] != "won")
alpha_after = balance_of("wallet:%d" % ids["alpha"])
beta_after  = balance_of("wallet:%d" % ids["beta"])
anchor_escrow_after  = balance_of("escrow:%d" % A_BET)
derived_escrow_after = balance_of("escrow:%d" % D_BET)

check("SETTLE-4: the winner is paid BOTH asymmetric escrows, not double its own "
      "stake",
      beta_after == beta_before + ANCHOR_CENTS + DERIVED_CENTS,
      f"before={beta_before} after={beta_after} "
      f"expected={beta_before + ANCHOR_CENTS + DERIVED_CENTS}")
check("SETTLE-4: the loser's wallet is untouched at settlement — its stake left "
      "at acceptance, not now",
      alpha_after == alpha_before, f"before={alpha_before} after={alpha_after}")
check("SETTLE-4: both Bet escrows close to exactly zero",
      anchor_escrow_after == 0 and derived_escrow_after == 0,
      f"anchor={anchor_escrow_after} derived={derived_escrow_after}")
check("SETTLE-4: no money was created or destroyed across the whole lifecycle",
      alpha_after + beta_after == 1_000_000,
      f"total={alpha_after + beta_after}")
conservation("SETTLE-4")


# ══════════════════════════════════════════════════════════════════════════════
# B-2 — FUNDED REVIVE
# ══════════════════════════════════════════════════════════════════════════════
section("REVIVE-5: a declined challenge revives as a NEW funded challenge")

ids = seed({"alpha": 500_000, "beta": 500_000})
r = issue(ids, "alpha", "beta", 100_000, 75_000)
OLD = r.challenge_id
with tdb.SessionLocal() as db:
    cf.decline_funded_challenge(event_id=uuid.uuid4(), challenge_id=OLD,
                                actor_team_id=ids["beta"], db=db)

old_before      = challenge_row(OLD)
old_legs_before = legs_for(OLD)
old_escrow_before = escrow_of(OLD)
alpha_after_refund = balance_of(f"wallet:{ids['alpha']}")

with tdb.SessionLocal() as db:
    rev = cf.revive_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=OLD, actor_team_id=ids["alpha"],
        terms=terms(120_000, 90_000), db=db)
NEW = rev.challenge_id
new_row = challenge_row(NEW)

check("REVIVE-5: revive produced a DISTINCT new challenge, not a mutation",
      NEW != OLD, f"old={OLD} new={NEW}")
check("REVIVE-5: the new challenge carries revived_from_challenge_id → original",
      new_row["revived_from_challenge_id"] == OLD,
      f"got {new_row['revived_from_challenge_id']}")
check("REVIVE-5: the new challenge is OPEN and offered",
      new_row["response_status"] == spec1.OFFERED)
check("REVIVE-5: the new challenge has real escrow:challenge:{new_id}",
      escrow_of(NEW) == 120_000, f"got {escrow_of(NEW)}")
check("REVIVE-5: escrow is booked against the NEW id, not the old one",
      escrow_of(OLD) == old_escrow_before == 0)
check("REVIVE-5: the issuer's wallet was actually debited for the new Anchor",
      balance_of(f"wallet:{ids['alpha']}") == alpha_after_refund - 120_000,
      f"before={alpha_after_refund} after={balance_of(f'wallet:{ids['alpha']}')}")
check("REVIVE-5: wager identity is carried across (mode, week, participants)",
      new_row["challenge_mode"] == old_before["challenge_mode"]
      and new_row["week"] == old_before["week"]
      and new_row["challenger_team_id"] == old_before["challenger_team_id"]
      and new_row["challenged_team_id"] == old_before["challenged_team_id"])
check("REVIVE-5: the new challenge has its OWN fresh version-1 proposal",
      new_row["active_proposal_id"] != old_before["active_proposal_id"]
      and proposal_row(new_row["active_proposal_id"])["version_number"] == 1
      and proposal_row(new_row["active_proposal_id"])["anchor_stake_cents"] == 120_000)
# NB-2: an assertion that the revive captured its own starter snapshot was
# removed rather than kept as a hardcoded True. This fixture seeds no rosters, so
# there is no snapshot to observe and nothing real to compare — the proposal-
# scoped ownership of BeefProposalStarter is structural (FK) and is already
# proven by the Spec 1 lifecycle suite. A check that cannot fail is worse than no
# check: it reports coverage the run does not have.

section("REVIVE-6: the ORIGINAL challenge's accounting is untouched by the revive")
check("REVIVE-6: the original stays terminal and unmodified",
      challenge_row(OLD) == old_before, "state, pointers and lineage all equal")
check("REVIVE-6: the original's funding legs are unchanged in count and content",
      legs_for(OLD) == old_legs_before,
      f"{len(old_legs_before)} legs before, {len(legs_for(OLD))} after")
check("REVIVE-6: the original's escrow remains closed at zero", escrow_of(OLD) == 0)

section("REVIVE-7: the revive's provenance is an ordinary issue's provenance")
new_legs = legs_for(NEW)
check("REVIVE-7: exactly one fund leg for a wallet-only revive",
      len(new_legs) == 1 and new_legs[0]["kind"] == "fund",
      str(new_legs))
check("REVIVE-7: the leg funds escrow:challenge:{new_id} from the issuer's wallet",
      new_legs[0]["source"] == f"wallet:{ids['alpha']}"
      and new_legs[0]["dest"] == f"escrow:challenge:{NEW}"
      and new_legs[0]["cents"] == 120_000
      and new_legs[0]["team_id"] == ids["alpha"])
check("REVIVE-7: sequence numbering restarts within the NEW challenge",
      new_legs[0]["seq"] == 1)
check("REVIVE-7: provenance equals the actual escrow (the reconciliation "
      "invariant holds on a revived challenge)",
      sum(l["cents"] for l in new_legs) == escrow_of(NEW))
conservation("REVIVE-7")

section("REVIVE-8: min-first source split works on a revive exactly as on issue")
ids = seed({"gamma": 40_000, "delta": 500_000}, min_cents={"gamma": 60_000})
r = issue(ids, "gamma", "delta", 30_000, 10_000)
OLD2 = r.challenge_id
with tdb.SessionLocal() as db:
    cf.decline_funded_challenge(event_id=uuid.uuid4(), challenge_id=OLD2,
                                actor_team_id=ids["delta"], db=db)
with tdb.SessionLocal() as db:
    rev2 = cf.revive_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=OLD2, actor_team_id=ids["gamma"],
        terms=terms(100_000, 10_000), db=db)
NEW2 = rev2.challenge_id
legs2 = legs_for(NEW2)
check("REVIVE-8: an UNEQUAL mixed split — min exhausted first, wallet second",
      [(l["source"], l["cents"]) for l in legs2]
      == [(f"min:{ids['gamma']}:{WEEK}", 60_000),
          (f"wallet:{ids['gamma']}", 40_000)],
      str([(l["source"], l["cents"]) for l in legs2]))
check("REVIVE-8: the legs are ordered min-then-wallet, not merely present",
      legs2[0]["seq"] < legs2[1]["seq"])
check("REVIVE-8: the single escrow credit equals the total",
      escrow_of(NEW2) == 100_000)
conservation("REVIVE-8")

section("REVIVE-9: insufficient funding creates NO revived challenge and posts "
        "nothing")
ids = seed({"eps": 50_000, "zeta": 500_000})
r = issue(ids, "eps", "zeta", 10_000, 5_000)
OLD3 = r.challenge_id
with tdb.SessionLocal() as db:
    cf.decline_funded_challenge(event_id=uuid.uuid4(), challenge_id=OLD3,
                                actor_team_id=ids["zeta"], db=db)

with tdb.SessionLocal() as db:
    before_count = db.query(BeefChallenge).count()
eps_before = balance_of(f"wallet:{ids['eps']}")

refused = False
try:
    with tdb.SessionLocal() as db:
        cf.revive_funded_challenge(
            event_id=uuid.uuid4(), challenge_id=OLD3, actor_team_id=ids["eps"],
            terms=terms(999_000), db=db)
except InsufficientFundingCapacityError:
    refused = True

with tdb.SessionLocal() as db:
    after_count = db.query(BeefChallenge).count()
    revived_rows = db.query(BeefChallenge).filter(
        BeefChallenge.revived_from_challenge_id == OLD3).count()

check("REVIVE-9: the revive was refused for capacity", refused)
check("REVIVE-9: NO new challenge row was created",
      after_count == before_count, f"{before_count} → {after_count}")
check("REVIVE-9: no challenge claims lineage from the original",
      revived_rows == 0)
check("REVIVE-9: the issuer's wallet is untouched",
      balance_of(f"wallet:{ids['eps']}") == eps_before)
conservation("REVIVE-9")

section("REVIVE-10: a duplicate revive event cannot duplicate the challenge or "
        "its money")
ids = seed({"eta": 500_000, "theta": 500_000})
r = issue(ids, "eta", "theta", 100_000, 75_000)
OLD4 = r.challenge_id
with tdb.SessionLocal() as db:
    cf.decline_funded_challenge(event_id=uuid.uuid4(), challenge_id=OLD4,
                                actor_team_id=ids["theta"], db=db)

DUP = uuid.uuid4()
with tdb.SessionLocal() as db:
    first = cf.revive_funded_challenge(
        event_id=DUP, challenge_id=OLD4, actor_team_id=ids["eta"],
        terms=terms(120_000, 90_000), db=db)
eta_after_first = balance_of(f"wallet:{ids['eta']}")
with tdb.SessionLocal() as db:
    second = cf.revive_funded_challenge(
        event_id=DUP, challenge_id=OLD4, actor_team_id=ids["eta"],
        terms=terms(120_000, 90_000), db=db)

with tdb.SessionLocal() as db:
    revived_count = db.query(BeefChallenge).filter(
        BeefChallenge.revived_from_challenge_id == OLD4).count()
    event_count = db.query(ProtocolEvent).filter(
        ProtocolEvent.event_id == DUP).count()

check("REVIVE-10: the replay is reported as a replay", second.replayed is True)
check("REVIVE-10: the replay returns the ORIGINAL revived challenge id",
      second.challenge_id == first.challenge_id,
      f"first={first.challenge_id} second={second.challenge_id}")
check("REVIVE-10: exactly ONE revived challenge exists", revived_count == 1,
      f"got {revived_count}")
check("REVIVE-10: exactly ONE protocol event exists for the event id",
      event_count == 1, f"got {event_count}")
check("REVIVE-10: the escrow was funded exactly once",
      escrow_of(first.challenge_id) == 120_000,
      f"got {escrow_of(first.challenge_id)}")
check("REVIVE-10: the wallet was debited exactly once",
      balance_of(f"wallet:{ids['eta']}") == eta_after_first)
check("REVIVE-10: the replay wrote no second funding leg",
      len(legs_for(first.challenge_id)) == 1,
      str(legs_for(first.challenge_id)))
conservation("REVIVE-10")


# ══════════════════════════════════════════════════════════════════════════════
# COUNTER — capacity refusals and idempotency (validation only, no money)
# ══════════════════════════════════════════════════════════════════════════════
section("COUNTER-11: counter-time ISSUER top-up capacity refusal")

ids = seed({"alpha": 150_000, "beta": 500_000})
r = issue(ids, "alpha", "beta", 100_000, 10_000)
CH = r.challenge_id
escrow_before = escrow_of(CH)
alpha_before  = balance_of(f"wallet:{ids['alpha']}")

refused = False
refusal_msg = ""
try:
    with tdb.SessionLocal() as db:
        # Raises the Anchor to 400_000: required_top_up = 300_000, but the
        # issuer has only 50_000 left after the original Anchor was escrowed.
        cf.counter_funded_challenge(
            event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=ids["beta"],
            terms=terms(400_000, 10_000), db=db)
except InsufficientFundingCapacityError as exc:
    refused = True
    refusal_msg = str(exc)

check("COUNTER-11: the counter was refused on the ISSUER's top-up capacity",
      refused)
check("COUNTER-11: no version 2 was created",
      challenge_row(CH)["active_proposal_id"] is not None
      and proposal_row(challenge_row(CH)["active_proposal_id"])["version_number"] == 1)
check("COUNTER-11: the challenge stays offered",
      challenge_row(CH)["response_status"] == spec1.OFFERED)
check("COUNTER-11: NO MONEY MOVED — escrow and wallet are exactly as before",
      escrow_of(CH) == escrow_before
      and balance_of(f"wallet:{ids['alpha']}") == alpha_before)
check("COUNTER-11: the refusal names the 300_000 DEFICIENCY (400_000 proposed − "
      "100_000 already escrowed), NOT the full proposed Anchor — validating the "
      "whole 400_000 would be the wrong rule and would say so here",
      "300000" in refusal_msg and "400000" not in refusal_msg,
      refusal_msg or "no refusal message captured")
conservation("COUNTER-11")

section("COUNTER-12: a counter the issuer CAN top up is accepted — the refusal "
        "above is not a blanket refusal")
ids = seed({"alpha": 150_000, "beta": 500_000})
r = issue(ids, "alpha", "beta", 100_000, 10_000)
CH = r.challenge_id
with tdb.SessionLocal() as db:
    ok = cf.counter_funded_challenge(
        event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=ids["beta"],
        terms=terms(140_000, 10_000), db=db)
check("COUNTER-12: a 40_000 top-up against 50_000 remaining is allowed — "
      "required_top_up is the DEFICIENCY (140_000 − 100_000 escrowed), not the "
      "full proposed Anchor",
      ok.response_status == spec1.COUNTERED)
check("COUNTER-12: version 2 exists",
      proposal_row(challenge_row(CH)["active_proposal_id"])["version_number"] == 2)
check("COUNTER-12: the counter still moved NO money",
      escrow_of(CH) == 100_000 and ok.escrow_cents == 100_000,
      f"escrow={escrow_of(CH)}")
conservation("COUNTER-12")

section("COUNTER-13: counter-time RECIPIENT Derived capacity refusal")
ids = seed({"alpha": 500_000, "beta": 20_000})
r = issue(ids, "alpha", "beta", 100_000, 10_000)
CH = r.challenge_id
escrow_before = escrow_of(CH)
beta_before   = balance_of(f"wallet:{ids['beta']}")

refused = False
try:
    with tdb.SessionLocal() as db:
        cf.counter_funded_challenge(
            event_id=uuid.uuid4(), challenge_id=CH, actor_team_id=ids["beta"],
            terms=terms(100_000, 300_000), db=db)
except InsufficientFundingCapacityError:
    refused = True

check("COUNTER-13: the counter was refused on the RECIPIENT's full Derived "
      "capacity — it has nothing escrowed, so the whole stake is validated",
      refused)
check("COUNTER-13: no version 2 was created",
      proposal_row(challenge_row(CH)["active_proposal_id"])["version_number"] == 1)
check("COUNTER-13: the challenge stays offered",
      challenge_row(CH)["response_status"] == spec1.OFFERED)
check("COUNTER-13: NO MONEY MOVED",
      escrow_of(CH) == escrow_before
      and balance_of(f"wallet:{ids['beta']}") == beta_before)
conservation("COUNTER-13")

section("COUNTER-14: a duplicate challenge_counter event returns the ORIGINAL "
        "proposal version and creates no second one")
ids = seed({"alpha": 500_000, "beta": 500_000})
r = issue(ids, "alpha", "beta", 100_000, 75_000)
CH = r.challenge_id

DUP = uuid.uuid4()
with tdb.SessionLocal() as db:
    first = cf.counter_funded_challenge(
        event_id=DUP, challenge_id=CH, actor_team_id=ids["beta"],
        terms=terms(100_000, 75_000), db=db)
v2_first = challenge_row(CH)["active_proposal_id"]
escrow_after_first = escrow_of(CH)

with tdb.SessionLocal() as db:
    second = cf.counter_funded_challenge(
        event_id=DUP, challenge_id=CH, actor_team_id=ids["beta"],
        terms=terms(100_000, 75_000), db=db)

with tdb.SessionLocal() as db:
    versions = [p.version_number for p in
                db.query(BeefProposal).filter(BeefProposal.challenge_id == CH)
                .order_by(BeefProposal.version_number).all()]
    event_count = db.query(ProtocolEvent).filter(
        ProtocolEvent.event_id == DUP).count()

check("COUNTER-14: the duplicate delivery is reported as a replay",
      second.replayed is True)
check("COUNTER-14: it returns the original result, not a new one",
      second.challenge_id == first.challenge_id
      and second.response_status == first.response_status == spec1.COUNTERED)
check("COUNTER-14: exactly TWO proposal versions exist — no third was minted",
      versions == [1, 2], str(versions))
check("COUNTER-14: the active pointer still names the original version 2",
      challenge_row(CH)["active_proposal_id"] == v2_first)
check("COUNTER-14: exactly one protocol event for the event id", event_count == 1)
check("COUNTER-14: still no money moved on either delivery",
      escrow_of(CH) == escrow_after_first == 100_000)
conservation("COUNTER-14")


# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURAL — the new seam inherits the established disciplines
# ══════════════════════════════════════════════════════════════════════════════
section("STRUCT-15: revive obeys the lock rank and reuses the one funding path")

import ast
import io
import tokenize

mod_src = (REPO / "economy" / "challenge_funding.py").read_text(encoding="utf-8")


def executable_source(src: str) -> str:
    skip = {tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE,
            tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
    for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        tok = getattr(tokenize, name, None)
        if tok is not None:
            skip.add(tok)
    return " ".join(
        t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
        if t.type not in skip)


code_only = executable_source(mod_src)
mod = ast.parse(mod_src)


def fn_node(name: str):
    return next(n for n in ast.walk(mod)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def calls(node, name: str) -> list[int]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            called = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if called == name:
                out.append(n.lineno)
    return sorted(out)


rev_node = fn_node("revive_funded_challenge")
ch_lock = calls(rev_node, "_lock_challenge")
w_lock  = calls(rev_node, "lock_funding_scopes")
check("STRUCT-15: revive locks the OLD CHALLENGE row before the Wallet scope "
      "(the rank P1-L7 established, never inverted)",
      ch_lock and w_lock and ch_lock[0] < w_lock[0],
      f"challenge@{ch_lock} wallet@{w_lock}")
check("STRUCT-15: revive takes the Wallet mutex before its capacity read",
      w_lock[0] < calls(rev_node, "available_cents")[0])
check("STRUCT-15: revive posts through the SHARED funded-issue body — it does "
      "not implement a second funding algorithm",
      calls(rev_node, "_fund_issued_challenge")
      and not calls(rev_node, "_fund")
      and not calls(rev_node, "ledger_post"))
check("STRUCT-15: revive checks event idempotency before doing anything",
      calls(rev_node, "_find_event")[0] < ch_lock[0])
check("STRUCT-15: both funded issue paths share one body",
      calls(fn_node("issue_funded_challenge"), "_fund_issued_challenge")
      and calls(fn_node("revive_funded_challenge"), "_fund_issued_challenge"))

shared = fn_node("_fund_issued_challenge")
check("STRUCT-15: the shared body commits exactly once",
      len(calls(shared, "commit")) == 1)
check("STRUCT-15: revive itself commits nothing directly",
      calls(rev_node, "commit") == [])

bet_node = fn_node("_create_bet")
check("STRUCT-15: _create_bet reads line/side from the PROPOSAL, never from the "
      "challenge container",
      "challenge.line" not in code_only and "challenge.side" not in code_only,
      "the container mirrors are unreferenced in executable code")
check("STRUCT-15: _create_bet takes the proposal as an explicit argument",
      "proposal" in [a.arg for a in bet_node.args.kwonlyargs + bet_node.args.args])
check("STRUCT-15: the fence holds — challenge_funding still never imports "
      "beef_engine", "beef_engine" not in code_only)
check("STRUCT-15: the fence holds — challenge_funding still never consults "
      "_challenge_reserved", "_challenge_reserved" not in code_only)
check("STRUCT-15: no route work was added", "APIRouter" not in code_only
      and "fastapi" not in code_only.lower())
conservation("STRUCT-15")


# ──────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
if _failures:
    print(f"{len(_failures)} FAILED assertion(s):")
    for f in _failures:
        print(f"  - {f}")
    print(f"\n{_passes} passed, {len(_failures)} FAILED")
    sys.exit(1)
print(f"All {_passes} assertions PASSED")