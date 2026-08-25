#!/usr/bin/env python3
"""FINAL POR · WP-6 certification — an approved Top-Off also grows the FS Pot.

    F1  the posting is the three legs, in the governed amounts
    F2  the GM's obligation is X, not 2X
    F3  the cap consumes X, not 2X
    F4  the FantasyStakes Score still moves by exactly 0
    F5  the pot leg creates no second GM liability of any kind
    F6  the posting conserves, and the issuance tally carries 2X
    F7  a LEGACY season still posts exactly two legs
    F8  two Top-Offs accumulate correctly on every derivation

WHY F2 AND F3 ARE SEPARATE ASSERTIONS OF WHAT LOOKS LIKE ONE FACT. They are two
independent derivations over the same posting, written in different modules for
different purposes — `economy.current_settle.topoff_issued_cents` decides what
the GM OWES, `economy.top_off._issued_from_ledger` decides how much CAP is left.
Either could have been written to sum the issuance leg instead of the wallet
leg, and only one of them failing would be invisible in the other's tests. Both
are checked against the same 2X posting.

THE FIXTURE POSTS THE REAL SHAPE RATHER THAN CALLING `approve_top_off`. That
function's approval path needs a commissioner, a locked League row, an open
request, a cap state and a Wallet mirror, and the B6 suites that exercise it
whole are PostgreSQL-only. What WP-6 changed is the posting, so the posting is
what this certifies — assembled by the same expression the production site uses,
which F1 reads out of the source to prove it has not drifted.
"""
from __future__ import annotations

import inspect
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import economy.top_off as top_off_module
import ledger.ledger as ledger_module
from db.schema import Base, League, Matchup, Team, Wallet
from economy.championship_pots import pot_balances
from economy.current_settle import current_settle, topoff_issued_cents
from economy.economy_events import fantasystakes_championship_account
from ledger.ledger import APPROVED_BAB_TOPOFF_DOOR, post as ledger_post
from reports.standings_read_model import league_standings
from ruleset import RULESET_FINAL_POR, is_final_por, stamp_ruleset

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
NAIVE = NOW.replace(tzinfo=None)

LEAGUE = 1
SEASON = 2026
TEAMS = (1, 2, 3, 4)
X = 2_000                      # a 20-Credit Top-Off
POT = fantasystakes_championship_account(LEAGUE, SEASON)
ISSUANCE = f"bab_issuance:{LEAGUE}:{SEASON}"


def _build(final_por: bool):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module.SessionLocal = sessionmaker(bind=engine)
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=LEAGUE, name="L", season=SEASON, start_week=1,
                  playoff_start_week=15))
    for t in TEAMS:
        db.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider_team_key=f"k{t}"))
        db.add(Wallet(team_id=t, balance=0.0))
    db.add(Matchup(id=1, league_id=LEAGUE, week=1, home_team_id=1,
                   away_team_id=2, home_score=100.0, away_score=98.0,
                   winner_team_id=1, finalized_at=NAIVE))
    db.add(Matchup(id=2, league_id=LEAGUE, week=1, home_team_id=3,
                   away_team_id=4, home_score=60.0, away_score=120.0,
                   winner_team_id=4, finalized_at=NAIVE))
    db.commit()
    if final_por:
        stamp_ruleset(db, league_id=LEAGUE, season=SEASON,
                      version=RULESET_FINAL_POR)
        db.commit()
    return db


def _top_off(db, team_id: int, amount_cents: int):
    """The production posting expression, run against this fixture.

    Kept deliberately identical in shape to the site in
    `economy/top_off.py::approve_top_off` step 15. F1 asserts the production
    site still says exactly this, so a divergence fails rather than hides.
    """
    legs = [
        (ISSUANCE, -amount_cents),
        (f"wallet:{team_id}", amount_cents),
    ]
    if is_final_por(db, league_id=LEAGUE, season=SEASON):
        legs[0] = (ISSUANCE, -amount_cents * 2)
        legs.append((fantasystakes_championship_account(LEAGUE, SEASON),
                     amount_cents))
    posting = ledger_post(legs, door=APPROVED_BAB_TOPOFF_DOOR, session=db)
    db.flush()
    return posting


def _bal(db, account: str) -> int:
    return ledger_module._balance_of_in_session(db, account)


def _legs(db, posting_id) -> dict[str, int]:
    rows = db.execute(text(
        "SELECT account, amount_cents FROM ledger_entries "
        "WHERE posting_id = :p"), {"p": str(posting_id).replace("-", "")}
    ).fetchall()
    if not rows:
        rows = db.execute(text(
            "SELECT account, amount_cents FROM ledger_entries "
            "WHERE door = :d"), {"d": APPROVED_BAB_TOPOFF_DOOR}).fetchall()
    return {r[0]: r[1] for r in rows}


# ── F1 · the three legs ──────────────────────────────────────────────────────

print("\nWP6-F1 · the posting is three legs, in the governed amounts")
src = inspect.getsource(top_off_module.approve_top_off)
_assert("the production site doubles the issuance leg under the Final POR",
        "-amount_cents * 2" in src)
_assert("  · and appends the FantasyStakes pot leg",
        "fantasystakes_championship_account(" in src
        and "legs.append(" in src)
_assert("  · gated on the one era predicate, not a literal",
        "is_final_por(db, league_id=request.league_id, season=season)" in src)
_assert("  · and no ruleset version is named in the module",
        "RULESET_FINAL_POR" not in inspect.getsource(top_off_module))

db = _build(final_por=True)
posting = _top_off(db, 1, X)
db.commit()
legs = _legs(db, posting)

_assert("the issuance leg is -2X", legs.get(ISSUANCE) == -2 * X,
        str(legs.get(ISSUANCE)))
_assert("  · the Wallet leg is +X", legs.get("wallet:1") == X,
        str(legs.get("wallet:1")))
_assert("  · the pot leg is +X", legs.get(POT) == X, str(legs.get(POT)))
_assert("  · exactly three legs, no more", len(legs) == 3, str(legs))
_assert("  · and no other GM's account appears",
        not any(a.startswith(("wallet:2", "wallet:3", "wallet:4"))
                for a in legs), str(sorted(legs)))


# ── F2 · the GM owes X, not 2X ───────────────────────────────────────────────

print("\nWP6-F2 · the GM's obligation is X, not 2X")
owed = topoff_issued_cents(db, 1)
_assert("the obligation derivation reports exactly X", owed == X,
        f"{owed} (X={X}, 2X={2 * X})")
_assert("  · which is NOT what the issuance leg carries",
        owed != abs(legs[ISSUANCE]), f"owed={owed} issuance={legs[ISSUANCE]}")

settle = current_settle(db, team_id=1, league_id=LEAGUE, season=SEASON)
_assert("  · Current Settle counts X as the Top-Off obligation",
        settle.topoff_issued_cents == X, str(settle.topoff_issued_cents))
_assert("  · the GM's Wallet really holds X", settle.wallet_cents == X,
        str(settle.wallet_cents))
_assert("  · so the Top-Off moves their Current Settle by exactly 0",
        settle.current_settle_cents == 0, str(settle.as_dict()))
_assert("  · the pot's X is NOT counted against them",
        settle.obligations_cents == X, str(settle.obligations_cents))


# ── F3 · the cap consumes X, not 2X ─────────────────────────────────────────

print("\nWP6-F3 · the cap consumes X, not 2X")
consumed = top_off_module._issued_from_ledger(db, LEAGUE, 1, SEASON)
_assert("the ledger-proven cap derivation reports exactly X", consumed == X,
        f"{consumed} (X={X}, 2X={2 * X})")
_assert("  · a GM granted a 2X cap could still draw the second X",
        2 * X - consumed == X, str(2 * X - consumed))
cap_src = inspect.getsource(top_off_module._issued_from_ledger)
_assert("  · because it sums the WALLET leg, with the issuance leg as a sibling",
        "w.account = :wallet_account" in cap_src
        and "s.account    = :issuance_account" in cap_src)
_assert("  · the pot leg is a third sibling and is never summed",
        "fantasystakes" not in cap_src)


# ── F4 · the FantasyStakes Score is untouched ───────────────────────────────

print("\nWP6-F4 · the FantasyStakes Score still moves by exactly 0")
scores = {r.team_id: r.net_cents for r in league_standings(db, league_id=LEAGUE).rows}
_assert("the topped-up GM's Score is 0", scores[1] == 0, str(scores[1]))
_assert("  · and no GM's Score differs from any other's",
        len(set(scores.values())) == 1, str(scores))
_assert("  · the Top-Off door is in neither scoring door group",
        APPROVED_BAB_TOPOFF_DOOR not in
        __import__("reports.standings_read_model", fromlist=["x"]).VERSUS_DOORS
        and APPROVED_BAB_TOPOFF_DOOR not in
        __import__("reports.standings_read_model", fromlist=["x"]).POOL_DOORS)


# ── F5 · no second liability ────────────────────────────────────────────────

print("\nWP6-F5 · the pot leg creates no second GM liability")
_assert("no receivable: was opened",
        all(_bal(db, f"receivable:{t}") == 0 for t in TEAMS),
        str({t: _bal(db, f"receivable:{t}") for t in TEAMS}))
_assert("  · no reserve: was created",
        all(_bal(db, f"reserve:{t}") == 0 for t in TEAMS))
_assert("  · no other GM's Wallet moved",
        all(_bal(db, f"wallet:{t}") == 0 for t in (2, 3, 4)),
        str({t: _bal(db, f"wallet:{t}") for t in (2, 3, 4)}))
_assert("  · no other GM acquired a Top-Off obligation",
        all(topoff_issued_cents(db, t) == 0 for t in (2, 3, 4)))
_assert("  · and their Current Settle is still 0",
        all(current_settle(db, team_id=t, league_id=LEAGUE,
                           season=SEASON).current_settle_cents == 0
            for t in (2, 3, 4)))


# ── F6 · conservation ───────────────────────────────────────────────────────

print("\nWP6-F6 · the posting conserves and the tally carries 2X")
_assert("the three legs sum to zero", sum(legs.values()) == 0,
        str(sum(legs.values())))
_assert("  · the global trial balance is zero",
        ledger_module.trial_balance() == 0,
        str(ledger_module.trial_balance()))
_assert("  · the issuance tally records 2X put into circulation",
        -_bal(db, ISSUANCE) == 2 * X, str(-_bal(db, ISSUANCE)))
_assert("  · X of it is spendable by the GM", _bal(db, "wallet:1") == X)
_assert("  · and X of it is in the pot", _bal(db, POT) == X)
_assert("  · which `pot_balances` reports as FantasyStakes funding",
        pot_balances(db, league_id=LEAGUE, season=SEASON).fantasystakes_cents
        == X)


# ── F7 · the legacy era still posts two legs ────────────────────────────────

print("\nWP6-F7 · a LEGACY season still posts exactly two legs")
old = _build(final_por=False)
old_posting = _top_off(old, 1, X)
old.commit()
old_legs = _legs(old, old_posting)

_assert("exactly two legs", len(old_legs) == 2, str(old_legs))
_assert("  · the issuance leg is -X, not -2X", old_legs.get(ISSUANCE) == -X,
        str(old_legs.get(ISSUANCE)))
_assert("  · the Wallet leg is +X", old_legs.get("wallet:1") == X)
_assert("  · NO pot leg was posted", POT not in old_legs, str(sorted(old_legs)))
_assert("  · the FantasyStakes pot was never created",
        _bal(old, POT) == 0, str(_bal(old, POT)))
_assert("  · the obligation is still X", topoff_issued_cents(old, 1) == X,
        str(topoff_issued_cents(old, 1)))
_assert("  · the cap still consumes X",
        top_off_module._issued_from_ledger(old, LEAGUE, 1, SEASON) == X)
_assert("  · and Current Settle still moves by exactly 0",
        current_settle(old, team_id=1, league_id=LEAGUE,
                       season=SEASON).current_settle_cents == 0)


# ── F8 · accumulation ───────────────────────────────────────────────────────

print("\nWP6-F8 · two Top-Offs accumulate correctly on every derivation")
_top_off(db, 1, 500)
db.commit()

_assert("the obligation is the sum of the Wallet legs",
        topoff_issued_cents(db, 1) == X + 500,
        str(topoff_issued_cents(db, 1)))
_assert("  · the cap consumption agrees with it",
        top_off_module._issued_from_ledger(db, LEAGUE, 1, SEASON) == X + 500,
        str(top_off_module._issued_from_ledger(db, LEAGUE, 1, SEASON)))
_assert("  · the pot grew by the second amount too",
        _bal(db, POT) == X + 500, str(_bal(db, POT)))
_assert("  · the issuance tally carries double the pair",
        -_bal(db, ISSUANCE) == 2 * (X + 500), str(-_bal(db, ISSUANCE)))
_assert("  · the GM's Wallet holds the pair, once",
        _bal(db, "wallet:1") == X + 500, str(_bal(db, "wallet:1")))
_assert("  · Current Settle is still exactly 0",
        current_settle(db, team_id=1, league_id=LEAGUE,
                       season=SEASON).current_settle_cents == 0,
        str(current_settle(db, team_id=1, league_id=LEAGUE,
                           season=SEASON).as_dict()))
_assert("  · the Score is still 0",
        league_standings(db, league_id=LEAGUE).rows[0].net_cents == 0)
_assert("  · and the trial balance is still zero",
        ledger_module.trial_balance() == 0)


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-6 approved Top-Off grows the FantasyStakes Pot: all assertions passed")
