"""
test_shortfall_reporting.py — B2, Section 6 "Also required": the reporting
layer built on top of the shortfall sweep.

Covers:
  1. reports/weekly_wrap.py's _sweep_explanation_for() reads an existing
     ShortfallSweepRecord (never triggers a new sweep) and produces the
     right text; falls back to a neutral message when the sweep hasn't
     run yet for that week.
  2. _template_gm_edition() (the deterministic, always-produces-output
     template fallback) includes the sweep explanation line.
  3. reports/my_account.py's get_my_account_summary() returns the skunk
     pot, championship pot, and this team's own open receivable — and
     ONLY this team's, not another team's.
  4. reports/settlement_report.py's championship_settlement_report()
     decomposes each winner's payout into collected vs. contingent,
     proportional to the pot's own collected/contingent ratio, and the
     invariant collected + contingent == pot_total always holds.
  5. API routes: GET /account/{team_id}/summary (own team OK, other
     team 403) and GET /reports/settlement/{league_id} (commissioner-only).

Uses a temp SQLite DB so prod is never touched.
"""

import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_shortfall_reporting.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ.pop("STRIPE_SECRET_KEY", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient

from db.schema import (
    Base, engine, SessionLocal,
    League, LeagueCommissioner, Team, User, Wallet, ShortfallSweepRecord, Matchup,
)
from auth.jwt_auth import get_current_gm, get_current_user, hash_password
from db.deps import get_db
from payments.economy_config import set_league_economy_stop
from ledger.ledger import post as ledger_post, create_ledger_table, balance_of
from reports.weekly_wrap import _sweep_explanation_for, _template_gm_edition, GmWeekData
from reports.my_account import get_my_account_summary
from reports.settlement_report import championship_settlement_report

import api.main as api_main
from api.main import app

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


Base.metadata.create_all(engine)
create_ledger_table()

client = TestClient(app)


def _override_get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


def _set_current_user(user_id: int) -> None:
    def _fake():
        with SessionLocal() as db:
            return db.query(User).filter(User.id == user_id).first()
    app.dependency_overrides[get_current_gm]   = _fake
    app.dependency_overrides[get_current_user] = _fake


# ── Fixture: one league, three teams (t1 winner, t2 with a receivable, t3 plain) ──

with SessionLocal() as db:
    league = League(season=2025, name="B2-6 Reporting Test League", projection_source="fantasypros")
    db.add(league)
    db.flush()
    set_league_economy_stop(league.id, 1000, db)

    t1 = Team(league_id=league.id, team_name="Winner Team", owner="Winner", email="winner@rpt.com")
    t2 = Team(league_id=league.id, team_name="Receivable Team", owner="Owes", email="owes@rpt.com")
    t3 = Team(league_id=league.id, team_name="Plain Team", owner="Plain", email="plain@rpt.com")
    db.add_all([t1, t2, t3])
    db.flush()

    db.add_all([Wallet(team_id=t1.id, balance=1000.0),
                Wallet(team_id=t2.id, balance=1000.0),
                Wallet(team_id=t3.id, balance=1000.0)])

    # Minimal regular-season matchup history so _compute_standings_order()
    # (the real, unmocked win/loss standings computation the API route
    # falls back to) actually returns these three teams in some order —
    # Item 4 above tests the decomposition math directly with an explicit
    # standings_order, so this fixture only needs to make the route's own
    # default-order fallback non-empty, not any particular ranking.
    db.add(Matchup(league_id=league.id, week=1, home_team_id=t1.id, away_team_id=t2.id,
                    home_score=120.0, away_score=100.0, winner_team_id=t1.id))
    db.add(Matchup(league_id=league.id, week=2, home_team_id=t2.id, away_team_id=t3.id,
                    home_score=110.0, away_score=90.0, winner_team_id=t2.id))

    gm1 = User(email="gm1@rpt.com", hashed_password=hash_password("x"), team_id=t1.id, role="gm", buy_in_paid=1)
    gm2 = User(email="gm2@rpt.com", hashed_password=hash_password("x"), team_id=t2.id, role="gm", buy_in_paid=1)
    comm = User(email="comm@rpt.com", hashed_password=hash_password("x"), team_id=None, role="commissioner", buy_in_paid=0)
    db.add_all([gm1, gm2, comm])

    # WP5 — LEAGUE-SCOPED COMMISSIONER AUTHORITY. This fixture granted the
    # GLOBAL role="commissioner" and nothing else, which was sufficient when the
    # route checked a role. S8-P2 replaced that with league-scoped authority:
    # the global is_commissioner role is NOT the same question, and conflating
    # them is the exact confusion S8-P2 exists to remove. The route now refuses
    # correctly, so the FIXTURE is what was stale — this suite's subject is
    # settlement reporting, not who may act.
    #
    # The grant is the real one the product uses, so the 403 branch above still
    # proves what it always did: authority is required, and it is league-scoped.
    db.flush()
    db.add(LeagueCommissioner(league_id=league.id, user_id=comm.id,
                              source="bootstrap"))

    db.commit()
    league_id = league.id
    t1_id, t2_id, t3_id = t1.id, t2.id, t3.id
    gm1_id, gm2_id, comm_id = gm1.id, gm2.id, comm.id


# ── ITEM 1 & 2: weekly-wrap sweep explanation wiring ──────────────────────────

print("\nItem 1: _sweep_explanation_for() reads an existing record, or falls back cleanly")

not_run_text = None
with SessionLocal() as db:
    not_run_text = _sweep_explanation_for(league_id, t1_id, 1, db)
_assert("no record yet -> neutral fallback message", "hasn't run yet" in not_run_text, f"got {not_run_text!r}")

with SessionLocal() as db:
    db.add(ShortfallSweepRecord(
        league_id=league_id, team_id=t1_id, week=1,
        weekly_min_cents=1000, wagered_cents=400, shortfall_cents=600,
        covered_cents=600, uncovered_cents=0, posting_id="test-posting-id",
    ))
    db.commit()

with SessionLocal() as db:
    run_text = _sweep_explanation_for(league_id, t1_id, 1, db)
_assert("existing record -> real explanation text, not the fallback", "hasn't run yet" not in run_text, f"got {run_text!r}")
_assert("real explanation mentions the swept amount", "$6.00" in run_text and "swept" in run_text, f"got {run_text!r}")

print("\nItem 2: _template_gm_edition() (deterministic fallback) includes the sweep line")

gm_data = GmWeekData(
    team_id=t1_id, team_name="Winner Team", owner="Winner", first_name="Winner",
    won=True, score=120.0, opp_score=100.0, opp_name="Someone", margin=20.0,
    starter_pts=120.0, bench_pts=10.0, best_possible=125.0, pts_left=5.0,
    lineup_grade="A", wins=5, losses=2, rank=1, total_teams=8,
    playoff_prob=0.8, playoff_prob_prev=0.75, prob_change=0.05,
    status_tag="contender", bet_won=1, bet_lost=0, bet_net=9.09,
    sweep_explanation=run_text,
)
template_output = _template_gm_edition(gm_data)
_assert("template output includes the sweep explanation verbatim", run_text in template_output)


# ── ITEM 3: My Account summary ────────────────────────────────────────────────

print("\nItem 3: get_my_account_summary() returns pot totals + only THIS team's own receivable")

ledger_post([("world", -5000), ("skunk", 5000)], door="fine")
ledger_post([("world", -30000), ("wallet:9999", 30000)], door="buy_in_paid")
ledger_post([(f"wallet:9999", -30000), ("championship", 30000)], door="shortfall_sweep")
# t2 owes a receivable; t1 owes nothing.
ledger_post([(f"receivable:{t2_id}", -1500), ("championship", 1500)], door="shortfall_sweep")

with SessionLocal() as db:
    summary_t1 = get_my_account_summary(t1_id, db)
    summary_t2 = get_my_account_summary(t2_id, db)

_assert("skunk pot reflects the fine posted", summary_t1.skunk_pot_cents == 5000, f"got {summary_t1.skunk_pot_cents}")
_assert("championship pot reflects both postings", summary_t1.championship_pot_cents == 31500, f"got {summary_t1.championship_pot_cents}")
_assert("t1 (no receivable) shows 0 open receivable", summary_t1.my_open_receivable_cents == 0, f"got {summary_t1.my_open_receivable_cents}")
_assert("t2 (owes $15.00) shows exactly its own open receivable, not t1's", summary_t2.my_open_receivable_cents == 1500, f"got {summary_t2.my_open_receivable_cents}")
_assert("both teams see the SAME shared pot totals", summary_t1.championship_pot_cents == summary_t2.championship_pot_cents)


# ── ITEM 4: settlement report decomposition ───────────────────────────────────

print("\nItem 4: championship_settlement_report() decomposes payouts, invariant always holds")

with SessionLocal() as db:
    report = championship_settlement_report(league_id, db, standings_order=[t1_id, t2_id, t3_id])

pot = balance_of("championship")
_assert("pot_total_cents matches balance_of('championship')", report.pot_total_cents == pot, f"got {report.pot_total_cents}")
_assert("contingent_cents matches t2's open receivable (only outstanding one)", report.contingent_cents == 1500, f"got {report.contingent_cents}")
_assert("collected + contingent == pot_total (invariant)", report.collected_cents + report.contingent_cents == report.pot_total_cents,
        f"collected={report.collected_cents} contingent={report.contingent_cents} pot={report.pot_total_cents}")
_assert("three payout rows produced (60/30/10)", len(report.rows) == 3, f"got {len(report.rows)}")
_assert("row 1 (60%) payout matches floor((pot*60)//100)", report.rows[0].payout_cents == (pot * 60) // 100, f"got {report.rows[0].payout_cents}")
for row in report.rows:
    _assert(f"row place={row.place}: collected + contingent == payout", row.collected_cents + row.contingent_cents == row.payout_cents,
            f"collected={row.collected_cents} contingent={row.contingent_cents} payout={row.payout_cents}")


# ── ITEM 5: API routes ─────────────────────────────────────────────────────────

print("\nItem 5: GET /account/{team_id}/summary and GET /reports/settlement/{league_id}")

_set_current_user(gm1_id)
resp_own = client.get(f"/account/{t1_id}/summary")
_assert("GM viewing own account summary succeeds (200)", resp_own.status_code == 200, f"got {resp_own.status_code}: {resp_own.text}")

resp_other = client.get(f"/account/{t2_id}/summary")
_assert("GM viewing ANOTHER team's account summary is blocked (403)", resp_other.status_code == 403, f"got {resp_other.status_code}: {resp_other.text}")

resp_settlement_gm = client.get(f"/reports/settlement/{league_id}")
_assert("non-commissioner blocked from settlement report (403)", resp_settlement_gm.status_code == 403, f"got {resp_settlement_gm.status_code}")

_set_current_user(comm_id)
resp_settlement_comm = client.get(f"/reports/settlement/{league_id}")
_assert("commissioner can view the settlement report (200)", resp_settlement_comm.status_code == 200, f"got {resp_settlement_comm.status_code}: {resp_settlement_comm.text}")
_assert("settlement report response has 3 rows", len(resp_settlement_comm.json()["rows"]) == 3, f"got {resp_settlement_comm.json()}")


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
