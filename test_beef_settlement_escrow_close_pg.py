"""
test_beef_settlement_escrow_close_pg.py — Finding 5.9 / 5.10: settle_week()'s
beef branch closes both sides' escrow through the ledger (door="wager_settled")
instead of the old direct wallet.balance mutation + amount*odds payout.

Four scenarios, per FR-5.9 Rev4 Section 7 / FR-5.10 Rev3 Section 6:

  1. Unequal-escrow win — the load-bearing case. A normal accepted beef always
     produces EQUAL escrow balances (both sides stake the same amount today),
     so a fixture using only equal stakes cannot distinguish the escrow-sourced
     fix from the 2x-amount shortcut it replaces — both produce the identical
     number on equal-stakes data. This case deliberately inflates the winner's
     escrow balance directly at the ledger level (posted from "world", after
     normal acceptance) so the two escrows hold genuinely different amounts,
     then asserts the credit equals the ACTUAL sum of both current escrow
     balances, not 2x either individual value.
  2. Equal-stakes win with heavily skewed odds, where the actual game result
     goes the OPPOSITE way the odds predicted — proves payout is the stake
     sum, never scaled by bet.odds.
  3. Pushed pair (exact tie) — two independent postings, each side gets back
     exactly its own escrow balance, no cross-crediting.
  4. Plain win at roughly even odds — baseline sanity check.

Every case asserts: both Bet rows flip status correctly, both escrow:{bet.id}
accounts drain to 0, wallet:{team_id} balances land on the exact expected
cents, the Transaction-row shape (winner: full combined credit; loser: only
its own debit, no credit — FR-5.9 Section 4) is as specified, and
trial_balance() closes to 0 throughout.

Runs on a disposable Postgres test database via test_support_postgres.py
(setup_postgres_test_db). Postgres is REQUIRED because settle_week's Phase-2
issues SELECT ... FOR UPDATE, which SQLite cannot parse. Export
TEST_DATABASE_URL (a dedicated, empty, "_test"-named database) before running.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST. setup_postgres_test_db() applies its safety guards, sets
# DATABASE_URL to the disposable test DB, and imports+binds db.schema INTERNALLY.
# No project module (db.schema, beef_engine, settlement_engine, per_bet_lock,
# ledger.ledger) may be imported before this call, or the engine would bind to
# the wrong database. Only test_support_postgres is safe at module top — it
# defers its own db.schema import.
from test_support_postgres import setup_postgres_test_db

import datetime as _dt
#: S6 §8 — the instant this suite's fixture weeks are declared economically
#: final at. Fixed rather than now(): a fixture's finality must not drift with
#: the wall clock, and Matchup.finalized_at is the ONLY signal the shared
#: settlement gate reads. Stating it makes the completed-week premise these
#: scenarios always relied on explicit instead of implicit.
_FIXTURE_FINAL_AT = _dt.datetime(2025, 12, 1, 12, 0, 0, tzinfo=_dt.timezone.utc)


# The exit-2 harness/config error path stays BEFORE main()/teardown: if setup
# fails (e.g. missing/unsafe TEST_DATABASE_URL) NOTHING was created, so there is
# nothing to tear down here.
try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] Postgres settlement suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    """All post-setup work lives here so the teardown-protected scope begins the
    instant setup succeeds. Crucially, the project imports are INSIDE this
    function: setup_postgres_test_db() already CREATED the schema, so if any of
    these imports raised (circular import, upstream error), teardown must still
    run — and it will, because main() is called inside the try whose finally
    tears down. Helpers and scenarios are nested here too, closing over the
    names imported below. _failures stays module-level (mutated via _assert,
    read by the summary)."""
    from datetime import datetime

    from db.schema import (
        Base, engine, SessionLocal,
        Bet, League, Matchup, NflSchedule, Player, Projection, Roster, Team,
        Transaction, Wallet,
    )
    from beefs.beef_engine import issue_challenge, respond_to_challenge
    from betting.settlement_engine import settle_week
    from betting.per_bet_lock import LOCK_SEASON
    from config import CURRENT_SEASON as SEASON
    from ledger.ledger import balance_of, trial_balance, post as ledger_post

    # ── DB bootstrap ──────────────────────────────────────────────────────────────

    with SessionLocal() as _db:
        league = League(season=SEASON, name="Beef Settlement Escrow Test League", projection_source="fantasypros")
        _db.add(league)
        _db.commit()
        LEAGUE_ID = league.id

    # Real wall-clock during this session is well before September 2026 — kickoffs
    # below are set far enough in the future that neither the week-level nor
    # per-bet lock in respond_to_challenge ever fires, matching
    # test_ledger_beef_conversion.py's own reasoning.
    FUTURE_KO = datetime(2026, 9, 14, 18, 0, 0)

    _FUND_CENTS = 100_000_00

    def _make_team(name: str, nfl_team: str, projected_pts: float | None = None, proj_week: int = 1) -> int:
        """Create a team with a wallet, 9 WR starters (all sharing nfl_team), and
        real ledger funding. projected_pts, if given, seeds a Projection row for
        every starter at proj_week (must match the week the beef is actually
        placed in) — used only to skew pre-settlement odds in Scenario 2;
        irrelevant to settlement itself, which reads actual Matchup scores, not
        projections."""
        with SessionLocal() as db:
            team = Team(league_id=LEAGUE_ID, team_name=f"Beef {name}", owner=name, email=f"{name}@beefsettle.com")
            db.add(team)
            db.flush()
            for i in range(9):
                p = Player(name=f"{name}-P{i}", position="WR", nfl_team=nfl_team)
                db.add(p)
                db.flush()
                db.add(Roster(team_id=team.id, player_id=p.id))
                if projected_pts is not None:
                    db.add(Projection(
                        player_id=p.id, week=proj_week, season=SEASON, source="fantasypros",
                        projected_points=projected_pts,
                    ))
            db.add(Wallet(team_id=team.id, balance=1000.0))
            db.commit()
            team_id = team.id
        ledger_post([("world", -_FUND_CENTS), (f"wallet:{team_id}", _FUND_CENTS)], door="buy_in_paid")
        return team_id

    def _seed_matchup_and_schedule(week: int, team_a: int, team_b: int, score_a: float, score_b: float,
                                    nfl_a: str, nfl_b: str) -> None:
        """One shared Matchup row satisfies _find_own_matchup() for BOTH beef
        participants (home OR away match) — this is the same shape
        test_ledger_beef_conversion.py already uses."""
        with SessionLocal() as db:
            db.add(Matchup(league_id=LEAGUE_ID, week=week, home_team_id=team_a, away_team_id=team_b,
                            home_score=score_a, away_score=score_b,
                            # S6 §8 — a COMPLETED week, stated explicitly.
                            finalized_at=_FIXTURE_FINAL_AT))
            db.add(NflSchedule(season=LOCK_SEASON, week=week, home_team=nfl_a, away_team=nfl_b,
                                kickoff_utc=FUTURE_KO))
            db.commit()

    def _accept_beef(challenger: int, challenged: int, week: int, amount: float) -> tuple[int, int]:
        """Issue + accept a straight beef. Returns (challenger_bet_id, challenged_bet_id)."""
        with SessionLocal() as db:
            out = issue_challenge(challenger, challenged, week=week, bet_type="straight", amount=amount, db=db)
            challenge_id = out.challenge_id
            result = respond_to_challenge(challenge_id, accept=True, db=db)
        return result.challenger_bet_id, result.challenged_bet_id

    # ── SCENARIO 1: unequal-escrow win — the load-bearing case ──────────────────

    print("\nScenario 1: unequal-escrow win — proves escrow-sourcing, not the 2x-amount shortcut")

    A1 = _make_team("A1", "KC")
    B1 = _make_team("B1", "PHI")
    _seed_matchup_and_schedule(week=1, team_a=A1, team_b=B1, score_a=150.0, score_b=90.0, nfl_a="KC", nfl_b="PHI")

    a1_bet_id, b1_bet_id = _accept_beef(A1, B1, week=1, amount=10.0)

    _assert("S1 fixture: both escrows start equal at $10.00", balance_of(f"escrow:{a1_bet_id}") == 1000 and balance_of(f"escrow:{b1_bet_id}") == 1000,
            f"got {balance_of(f'escrow:{a1_bet_id}')}/{balance_of(f'escrow:{b1_bet_id}')}")

    # Deliberately inflate the (soon-to-be) winner's escrow — A1 will win this
    # beef (150 > 90) — so the two escrows genuinely differ before settlement.
    ledger_post([("world", -500), (f"escrow:{a1_bet_id}", 500)], door="test_unequal_escrow_seed")
    _assert("S1 fixture: escrows now genuinely unequal ($15.00 vs $10.00)",
            balance_of(f"escrow:{a1_bet_id}") == 1500 and balance_of(f"escrow:{b1_bet_id}") == 1000,
            f"got {balance_of(f'escrow:{a1_bet_id}')}/{balance_of(f'escrow:{b1_bet_id}')}")

    wallet_a1_before = balance_of(f"wallet:{A1}")
    tb_before_s1 = trial_balance()

    with SessionLocal() as db:
        report1 = settle_week(1, db, league_id=LEAGUE_ID)

    _assert("S1: winner (A1) credited exactly $25.00 (1500+1000), NOT 2x1000 ($20) or 2x1500 ($30)",
            balance_of(f"wallet:{A1}") - wallet_a1_before == 2500,
            f"got delta {balance_of(f'wallet:{A1}') - wallet_a1_before}")
    _assert("S1: both escrow accounts drained to 0",
            balance_of(f"escrow:{a1_bet_id}") == 0 and balance_of(f"escrow:{b1_bet_id}") == 0,
            f"got {balance_of(f'escrow:{a1_bet_id}')}/{balance_of(f'escrow:{b1_bet_id}')}")
    _assert("S1: trial_balance still closes to 0 after settlement", trial_balance() == tb_before_s1, f"before={tb_before_s1} after={trial_balance()}")

    with SessionLocal() as db:
        a1_bet = db.query(Bet).filter(Bet.id == a1_bet_id).first()
        b1_bet = db.query(Bet).filter(Bet.id == b1_bet_id).first()
        _assert("S1: winner bet status == 'won'", a1_bet.status == "won", f"got {a1_bet.status}")
        _assert("S1: loser bet status == 'lost'", b1_bet.status == "lost", f"got {b1_bet.status}")

        # Each bet now has TWO Transaction rows (placement debit, type="bet",
        # plus this settlement row) — filter by type to get the settlement one,
        # not whichever .first() happens to return.
        winner_tx = db.query(Transaction).filter(Transaction.bet_id == a1_bet_id, Transaction.type.in_(("payout", "withdrawal"))).first()
        loser_tx  = db.query(Transaction).filter(Transaction.bet_id == b1_bet_id, Transaction.type.in_(("payout", "withdrawal"))).first()
        _assert("S1: winner's Transaction carries the FULL combined credit ($25.00), type='payout'",
                winner_tx is not None and winner_tx.amount == 25.00 and winner_tx.type == "payout",
                f"got amount={winner_tx.amount if winner_tx else None} type={winner_tx.type if winner_tx else None}")
        _assert("S1: loser's Transaction carries only its OWN stake ($10.00, not the inflated $15.00), negative, type='withdrawal'",
                loser_tx is not None and loser_tx.amount == -10.00 and loser_tx.type == "withdrawal",
                f"got amount={loser_tx.amount if loser_tx else None} type={loser_tx.type if loser_tx else None}")

    # ── SCENARIO 2: skewed odds, underdog wins — proves odds don't drive payout ──

    print("\nScenario 2: heavily skewed odds, but the odds-underdog wins the real game — payout is the stake sum, never odds-scaled")

    C2 = _make_team("C2", "SF", projected_pts=30.0, proj_week=2)   # heavy odds favorite (high projections)
    D2 = _make_team("D2", "DAL", projected_pts=1.0, proj_week=2)   # heavy odds underdog (near-zero projections)
    # Real game result is the OPPOSITE of what the skewed odds predict.
    _seed_matchup_and_schedule(week=2, team_a=C2, team_b=D2, score_a=60.0, score_b=150.0, nfl_a="SF", nfl_b="DAL")

    c2_bet_id, d2_bet_id = _accept_beef(C2, D2, week=2, amount=10.0)

    with SessionLocal() as db:
        c2_bet_check = db.query(Bet).filter(Bet.id == c2_bet_id).first()
        d2_bet_check = db.query(Bet).filter(Bet.id == d2_bet_id).first()
        _assert("S2 fixture: odds are meaningfully skewed (not both ~evens)",
                abs(c2_bet_check.odds - d2_bet_check.odds) > 0.1,
                f"got challenger_odds={c2_bet_check.odds} challenged_odds={d2_bet_check.odds}")

    wallet_d2_before = balance_of(f"wallet:{D2}")
    tb_before_s2 = trial_balance()

    with SessionLocal() as db:
        report2 = settle_week(2, db, league_id=LEAGUE_ID)

    _assert("S2: real-game winner (D2, the odds-underdog) credited exactly $20.00 (1000+1000), not scaled by its own odds",
            balance_of(f"wallet:{D2}") - wallet_d2_before == 2000,
            f"got delta {balance_of(f'wallet:{D2}') - wallet_d2_before}")
    _assert("S2: both escrow accounts drained to 0",
            balance_of(f"escrow:{c2_bet_id}") == 0 and balance_of(f"escrow:{d2_bet_id}") == 0,
            f"got {balance_of(f'escrow:{c2_bet_id}')}/{balance_of(f'escrow:{d2_bet_id}')}")
    _assert("S2: trial_balance still closes to 0", trial_balance() == tb_before_s2, f"before={tb_before_s2} after={trial_balance()}")

    with SessionLocal() as db:
        c2_bet = db.query(Bet).filter(Bet.id == c2_bet_id).first()
        d2_bet = db.query(Bet).filter(Bet.id == d2_bet_id).first()
        _assert("S2: real-game loser (C2, the odds-favorite) status == 'lost'", c2_bet.status == "lost", f"got {c2_bet.status}")
        _assert("S2: real-game winner (D2) status == 'won'", d2_bet.status == "won", f"got {d2_bet.status}")

        loser_tx2 = db.query(Transaction).filter(Transaction.bet_id == c2_bet_id, Transaction.type.in_(("payout", "withdrawal"))).first()
        _assert("S2: loser's Transaction is exactly -$10.00 (its own stake), type='withdrawal' — not scaled by its (favorable) odds",
                loser_tx2 is not None and loser_tx2.amount == -10.00 and loser_tx2.type == "withdrawal",
                f"got amount={loser_tx2.amount if loser_tx2 else None}")

    # ── SCENARIO 3: pushed pair (exact tie) ──────────────────────────────────────

    print("\nScenario 3: pushed pair — each side gets back exactly its own stake, no cross-crediting")

    E3 = _make_team("E3", "BUF")
    F3 = _make_team("F3", "MIA")
    _seed_matchup_and_schedule(week=3, team_a=E3, team_b=F3, score_a=100.0, score_b=100.0, nfl_a="BUF", nfl_b="MIA")

    e3_bet_id, f3_bet_id = _accept_beef(E3, F3, week=3, amount=10.0)

    wallet_e3_before = balance_of(f"wallet:{E3}")
    wallet_f3_before = balance_of(f"wallet:{F3}")
    tb_before_s3 = trial_balance()

    with SessionLocal() as db:
        report3 = settle_week(3, db, league_id=LEAGUE_ID)

    _assert("S3: E3 credited back exactly its own $10.00 stake", balance_of(f"wallet:{E3}") - wallet_e3_before == 1000, f"got delta {balance_of(f'wallet:{E3}') - wallet_e3_before}")
    _assert("S3: F3 credited back exactly its own $10.00 stake", balance_of(f"wallet:{F3}") - wallet_f3_before == 1000, f"got delta {balance_of(f'wallet:{F3}') - wallet_f3_before}")
    _assert("S3: both escrow accounts drained to 0",
            balance_of(f"escrow:{e3_bet_id}") == 0 and balance_of(f"escrow:{f3_bet_id}") == 0,
            f"got {balance_of(f'escrow:{e3_bet_id}')}/{balance_of(f'escrow:{f3_bet_id}')}")
    _assert("S3: trial_balance still closes to 0", trial_balance() == tb_before_s3, f"before={tb_before_s3} after={trial_balance()}")

    with SessionLocal() as db:
        e3_bet = db.query(Bet).filter(Bet.id == e3_bet_id).first()
        f3_bet = db.query(Bet).filter(Bet.id == f3_bet_id).first()
        _assert("S3: both bets status == 'push'", e3_bet.status == "push" and f3_bet.status == "push", f"got {e3_bet.status}/{f3_bet.status}")

        e3_tx = db.query(Transaction).filter(Transaction.bet_id == e3_bet_id, Transaction.type.in_(("payout", "withdrawal"))).first()
        f3_tx = db.query(Transaction).filter(Transaction.bet_id == f3_bet_id, Transaction.type.in_(("payout", "withdrawal"))).first()
        _assert("S3: both Transaction rows are +$10.00, type='payout' (no debit-only row on a push)",
                e3_tx is not None and e3_tx.amount == 10.00 and e3_tx.type == "payout"
                and f3_tx is not None and f3_tx.amount == 10.00 and f3_tx.type == "payout",
                f"got e3={e3_tx.amount if e3_tx else None}/{e3_tx.type if e3_tx else None} "
                f"f3={f3_tx.amount if f3_tx else None}/{f3_tx.type if f3_tx else None}")

    # ── SCENARIO 4: plain win at roughly even odds — baseline sanity check ──────

    print("\nScenario 4: plain win, roughly even odds — baseline sanity check")

    G4 = _make_team("G4", "GB")
    H4 = _make_team("H4", "CHI")
    _seed_matchup_and_schedule(week=4, team_a=G4, team_b=H4, score_a=130.0, score_b=80.0, nfl_a="GB", nfl_b="CHI")

    g4_bet_id, h4_bet_id = _accept_beef(G4, H4, week=4, amount=10.0)

    wallet_g4_before = balance_of(f"wallet:{G4}")
    tb_before_s4 = trial_balance()

    with SessionLocal() as db:
        report4 = settle_week(4, db, league_id=LEAGUE_ID)

    _assert("S4: winner (G4) credited exactly $20.00 (1000+1000)", balance_of(f"wallet:{G4}") - wallet_g4_before == 2000, f"got delta {balance_of(f'wallet:{G4}') - wallet_g4_before}")
    _assert("S4: both escrow accounts drained to 0",
            balance_of(f"escrow:{g4_bet_id}") == 0 and balance_of(f"escrow:{h4_bet_id}") == 0,
            f"got {balance_of(f'escrow:{g4_bet_id}')}/{balance_of(f'escrow:{h4_bet_id}')}")
    _assert("S4: trial_balance still closes to 0", trial_balance() == tb_before_s4, f"before={tb_before_s4} after={trial_balance()}")

    with SessionLocal() as db:
        g4_bet = db.query(Bet).filter(Bet.id == g4_bet_id).first()
        h4_bet = db.query(Bet).filter(Bet.id == h4_bet_id).first()
        _assert("S4: winner status == 'won', loser status == 'lost'", g4_bet.status == "won" and h4_bet.status == "lost", f"got {g4_bet.status}/{h4_bet.status}")

        loser_tx4 = db.query(Transaction).filter(Transaction.bet_id == h4_bet_id, Transaction.type.in_(("payout", "withdrawal"))).first()
        _assert("S4: loser's Transaction is exactly -$10.00, type='withdrawal'",
                loser_tx4 is not None and loser_tx4.amount == -10.00 and loser_tx4.type == "withdrawal",
                f"got amount={loser_tx4.amount if loser_tx4 else None}")

    # ── Summary ───────────────────────────────────────────────────────────────────

    print(f"\n{'='*52}")
    if _failures:
        print(f"FAILED: {len(_failures)} assertion(s)")
        for f in _failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All assertions PASSED")


# main() runs inside the teardown-protected scope: because setup already CREATED
# the schema, teardown must fire even if a post-setup project import (inside
# main) raises. The finally preserves the primary exception — including the
# SystemExit(1) from an assertion failure — and only re-raises a teardown
# failure when nothing else is already propagating.
try:
    main(tdb)
finally:
    primary_active = sys.exc_info()[0] is not None
    try:
        tdb.teardown()
    except Exception as teardown_exc:
        print(f"\n[HARNESS ERROR] teardown failed:\n  {teardown_exc}")
        if not primary_active:
            raise
