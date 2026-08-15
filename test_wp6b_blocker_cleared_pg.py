#!/usr/bin/env python3
"""
test_wp6b_blocker_cleared_pg.py — WP6B · the WP6 blocker, before and after.

THE QUESTION THIS SUITE ANSWERS:

    DOES THE PRODUCTION WORKER ACTUALLY CLEAR WP6'S `escrow_resolved` BLOCKER,
    THROUGH THE GOVERNED LIFECYCLE, WITHOUT CANCELLING OR REFUNDING THE WAGER?

WP6 recorded BLOCKER 1 like this: a Dynamic challenge issued and handshaken
through the product could never be priced, so "both sides' Credits stay in
`escrow:challenge:{id}:anchor` and `:derived` permanently, and
`POST /league/{id}/season/close` is refused at prerequisite `escrow_resolved`
forever." This suite recreates that scenario — the same challenge shape, the
same routes, the same league — and proves the refusal BEFORE the worker runs and
its absence AFTER, with the wager having gone all the way through settlement in
between.

THE ONE THING THIS SUITE MUST NOT DO is make the escrow go away by any route
other than the governed one. The challenge is not cancelled, not declined, not
voided, not refunded, and not deleted: it is PRICED at Final Lock, migrated into
per-Bet escrow, and then SETTLED by the same weekly automation that settles every
Locked wager. §6 asserts that positively — the Bet rows reach a terminal state
and the escrow drains through settlement — so "the blocker is gone" cannot be
satisfied by making the wager gone.

THE POOL IS DELIBERATELY NOT ACTIVATED. WP6's second, independent blocker lives
in the Pool claim path, and leaving it in the fixture would let `pool_rollover`
refuse the close for reasons that have nothing to do with this package — which
would make "the close is still refused" ambiguous exactly where this suite needs
it to be decisive. A league that never ran a Pool has nothing to refuse on, so
what remains at the close is the Versus/escrow question alone.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)
os.environ.setdefault("JWT_SECRET_KEY", "wp6b-cleared-secret")
os.environ.pop("ANTHROPIC_API_KEY", None)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP6B blocker suite cannot run:\n  {e}")
    sys.exit(2)

from datetime import timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import providers.yahoo.transport as yahoo_transport  # noqa: E402
from api.main import app  # noqa: E402
from db.schema import (  # noqa: E402
    Bet, BeefChallenge, ChallengeFinalLock, League, Matchup, SessionLocal,
)
from ledger.ledger import balance_of, trial_balance  # noqa: E402
from providers.fixtures.replay import FixtureTransport  # noqa: E402
from test_support_wp2bc_league import (  # noqa: E402
    FROZEN_NOW, LEAGUE_ID, TEAM_COUNT, seed_economic_league, snapshot_for,
)
from test_support_wp6b import (  # noqa: E402
    COMM_EMAIL, PASSWORD, gm_email, seed_wp6b_fixture, week_kickoff,
)

import workers.final_lock as flw  # noqa: E402


class _FixtureLiveTransport(FixtureTransport):
    league_number = yahoo_transport.YahooLiveTransport.league_number

    def __init__(self, *a, **kw) -> None:
        super().__init__(frozen_now=FROZEN_NOW)


yahoo_transport.YahooLiveTransport = _FixtureLiveTransport

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}{f' — {detail}' if detail else ''}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}\n" + "─" * min(len(title), 78))


#: WP6 §12's exact Dynamic shape: team 4 vs team 5, `straight`, anchor $1.00.
DYNAMIC_ANCHOR = 1.00
DYN_WEEK = 2

print("=" * 78)
print("WP6B — THE WP6 `escrow_resolved` BLOCKER, BEFORE AND AFTER")
print("=" * 78)


def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def bearer(email: str) -> dict:
    r = client().post("/auth/login",
                      data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, f"login failed for {email}: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def close_refusal() -> tuple[str | None, str]:
    """The FIRST unmet Season Close prerequisite, or (None, '') if all are met."""
    from betting.pool_season_boundary import season_final_week
    from economy.season_close_orchestrator import (
        SeasonClosePreconditionError, verify_preconditions,
    )
    with SessionLocal() as db:
        lg = db.query(League).filter(League.id == LEAGUE_ID).one()
        try:
            verify_preconditions(db, league_id=LEAGUE_ID,
                                 final_week=season_final_week(lg))
            return None, ""
        except SeasonClosePreconditionError as exc:
            return exc.step, str(exc)
        finally:
            db.rollback()


def open_escrow_accounts() -> list[tuple[str, int]]:
    with SessionLocal() as db:
        rows = db.execute(text(
            "SELECT account, SUM(amount_cents) FROM ledger_entries "
            "WHERE account LIKE 'escrow:%' GROUP BY account "
            "HAVING SUM(amount_cents) <> 0")).fetchall()
        db.rollback()
    return [(a, int(v)) for a, v in rows]


# ══════════════════════════════════════════════════════════════════════════════
# §1 · THE LEAGUE, TO THE POINT WHERE WP6 ISSUED ITS DYNAMIC CHALLENGE
# ══════════════════════════════════════════════════════════════════════════════

_section("§1 · the league, driven to WP6's week 2 through production routes")

tdb.reset()

with SessionLocal() as db:
    seed_economic_league(db, with_postseason=True)
    db.commit()
with SessionLocal() as db:
    team_ids, _ = seed_wp6b_fixture(db, team_count=TEAM_COUNT,
                                    league_id=LEAGUE_ID)
    db.commit()

T1, T2, T3, T4, T5, T6 = team_ids
hdr = bearer(COMM_EMAIL)
gm = {i: bearer(gm_email(i)) for i in range(2, TEAM_COUNT + 1)}

r = client().post(f"/league/{LEAGUE_ID}/season-allocation", headers=hdr)
_assert("§1: season allocation", r.status_code == 200, f"{r.status_code} "
        f"{r.text[:140]}")
r = client().post(f"/league/{LEAGUE_ID}/week/1/open", headers=hdr)
_assert("§1: week 1 opens", r.status_code == 200, f"{r.status_code} "
        f"{r.text[:140]}")

r = client().post("/admin/tuesday-sync", headers=hdr,
                  json={"league_id": LEAGUE_ID, "week": 1, "mock_mode": True})
_assert("§1: week 1's results ingest through the production weekly automation",
        r.status_code == 200, f"{r.status_code} {r.text[:140]}")

r = client().post(f"/league/{LEAGUE_ID}/week/1/close", headers=hdr)
_assert("§1: week 1 closes — Skunk assessed, minimum expired",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")

r = client().post(f"/league/{LEAGUE_ID}/week/2/open", headers=hdr)
_assert("§1: week 2 opens and releases its own minimum",
        r.status_code == 200, f"{r.status_code} {r.text[:140]}")

# FIXTURE-ONLY — the NOT_FINAL week-2 scoreboard, i.e. the state a live league is
# in while its GMs are still wagering. WP6 §11 does exactly this, for the same
# reason: the product has no action that produces "the games have not finished".
from providers.yahoo.persist import refresh_league_week  # noqa: E402

with SessionLocal() as db:
    refresh_league_week(
        db, snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW), DYN_WEEK,
                         scoreboard_id="yahoo_wp2bc_scoreboard_w2_pending"),
        now=FROZEN_NOW)
    db.commit()

_assert("§1: trial balance zero entering the Dynamic scenario",
        trial_balance() == 0, str(trial_balance()))


# ══════════════════════════════════════════════════════════════════════════════
# §2 · WP6's DYNAMIC CHALLENGE, RECREATED EXACTLY
# ══════════════════════════════════════════════════════════════════════════════

_section("§2 · WP6 §12's Dynamic challenge — team 4 vs team 5, straight, $1.00")

r = client().post("/beef/challenge", headers=gm[4], json={
    "challenger_team_id": T4, "challenged_team_id": T5, "week": DYN_WEEK,
    "bet_type": "straight", "amount": DYNAMIC_ANCHOR,
    "challenge_mode": "dynamic"})
_assert("§2: the Dynamic challenge is issued through POST /beef/challenge",
        r.status_code == 201, f"{r.status_code} {r.text[:200]}")
DYN = r.json()["challenge_id"]

r = client().post("/beef/respond", headers=gm[5],
                  json={"challenge_id": DYN, "accept": True})
_assert("§2: the Handshake completes through POST /beef/respond",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")
hs = r.json()

ANCHOR_ACCT = f"escrow:challenge:{DYN}:anchor"
DERIVED_ACCT = f"escrow:challenge:{DYN}:derived"


# ══════════════════════════════════════════════════════════════════════════════
# §3 · BEFORE THE WORKER — THE BLOCKER, EXACTLY AS WP6 REPORTED IT
# ══════════════════════════════════════════════════════════════════════════════

_section("§3 · BEFORE · unresolved Dynamic escrow, and the close refuses")

_anchor_before = balance_of(ANCHOR_ACCT)
_derived_before = balance_of(DERIVED_ACCT)
_stranded = _anchor_before + _derived_before

_assert("§3 BEFORE: both sides' maximum exposure sits in per-side Dynamic "
        "escrow", _anchor_before > 0 and _derived_before > 0,
        f"{ANCHOR_ACCT}={_anchor_before}, {DERIVED_ACCT}={_derived_before}")
with SessionLocal() as db:
    _n_bets = db.query(Bet).filter(Bet.beef_challenge_id == DYN).count()
    _n_fl = db.query(ChallengeFinalLock).filter(
        ChallengeFinalLock.challenge_id == DYN).count()
    db.rollback()
_assert("§3 BEFORE: no Bet rows and no frozen Final-Lock result exist",
        _n_bets == 0 and _n_fl == 0, f"{_n_bets} bets, {_n_fl} results")

_step_before, _msg_before = close_refusal()
_assert("§3 BEFORE: Season Close is refused at `escrow_resolved` — WP6's exact "
        "finding", _step_before == "escrow_resolved", f"{_step_before}: "
        f"{_msg_before[:160]}")
_assert("§3 BEFORE: and the refusal names THIS challenge's two escrow accounts",
        ANCHOR_ACCT in _msg_before and DERIVED_ACCT in _msg_before,
        _msg_before[:200])

r = client().post(f"/league/{LEAGUE_ID}/season/close", headers=hdr)
_assert("§3 BEFORE: the production close route refuses with 409 "
        "`escrow_resolved`",
        r.status_code == 409
        and r.json().get("detail", {}).get("reason_code") == "escrow_resolved",
        f"{r.status_code} {r.text[:200]}")


# ══════════════════════════════════════════════════════════════════════════════
# §4 · THE PRODUCTION WORKER RUNS
# ══════════════════════════════════════════════════════════════════════════════

_section("§4 · the production worker runs — no GM, no commissioner, no route")

KICKOFF = week_kickoff(DYN_WEEK)

# THE DEPLOYED ENTRY POINT, AT THE REAL CLOCK FIRST. Week 2's kickoff is still
# days away, so the timing gate is exercised exactly as it will be in production
# on every sweep before kickoff — and it declines.
_rc = flw.main(["--league", str(LEAGUE_ID), "--dry-run"])
_assert("§4: `python -m workers.final_lock --dry-run` runs at the real clock "
        "and exits 0", _rc == 0, str(_rc))
_assert("§4: before kickoff it locks nothing — escrow is untouched",
        (balance_of(ANCHOR_ACCT), balance_of(DERIVED_ACCT))
        == (_anchor_before, _derived_before))

_sweep = flw.run_once(worker_id="wp6b-blocker-worker", now=KICKOFF,
                      league_id=LEAGUE_ID)
_out = next(o for o in _sweep.outcomes if o.challenge_id == DYN)
_assert("§4: at the governed kickoff the worker LOCKS the Dynamic challenge",
        _out.status == flw.LOCKED, f"{_out.status} — {_out.detail}")
_assert("§4: the actor was the system worker, and there is still no HTTP route "
        "that could have done it",
        not [p for p in {getattr(rt, "path", "") for rt in app.routes}
             if any(k in p.lower() for k in ("final", "lock", "dynamic"))])


# ══════════════════════════════════════════════════════════════════════════════
# §5 · AFTER THE WORKER — BET ROWS EXIST, ESCROW MIGRATED
# ══════════════════════════════════════════════════════════════════════════════

_section("§5 · AFTER · the wager is priced: Bet rows exist, escrow migrated")

with SessionLocal() as db:
    _bets = db.query(Bet).filter(Bet.beef_challenge_id == DYN).all()
    _bet_ids = sorted(b.id for b in _bets)
    _fl = (db.query(ChallengeFinalLock)
           .filter(ChallengeFinalLock.challenge_id == DYN).one())
    _fl_anchor, _fl_derived = _fl.anchor_cents, _fl.derived_final_cents
    _fl_refund = _fl.derived_refund_cents
    db.rollback()

_assert("§5 AFTER: Dynamic Bet rows now EXIST — the thing WP6 proved could "
        "never happen", len(_bet_ids) == 2, str(_bet_ids))
_assert("§5 AFTER: the per-side Dynamic escrow accounts are drained",
        balance_of(ANCHOR_ACCT) == 0 and balance_of(DERIVED_ACCT) == 0,
        f"{balance_of(ANCHOR_ACCT)}/{balance_of(DERIVED_ACCT)}")
_assert("§5 AFTER: their Credits are in the two Bet escrow accounts, not "
        "refunded away",
        sum(balance_of(f"escrow:{b}") for b in _bet_ids)
        == _fl_anchor + _fl_derived > 0,
        f"{sum(balance_of(f'escrow:{b}') for b in _bet_ids)} vs "
        f"{_fl_anchor + _fl_derived}")
_assert("§5 AFTER: the wager was PRICED, not cancelled — the challenge is still "
        "accepted and every stranded cent is accounted for as stake or "
        "ceiling refund",
        _fl_anchor + _fl_derived + _fl_refund == _stranded,
        f"{_fl_anchor} + {_fl_derived} + {_fl_refund} vs {_stranded}")
_assert("§5 AFTER: trial balance zero", trial_balance() == 0,
        str(trial_balance()))

_step_mid, _msg_mid = close_refusal()
_assert("§5 AFTER: the close now refuses on the PENDING WAGER rather than on "
        "stranded escrow — the blocker has moved forward into the ordinary "
        "lifecycle", _step_mid == "versus_terminal", f"{_step_mid}: "
        f"{_msg_mid[:160]}")


# ══════════════════════════════════════════════════════════════════════════════
# §6 · NORMAL SETTLEMENT RESOLVES IT
# ══════════════════════════════════════════════════════════════════════════════

_section("§6 · the SAME weekly automation that settles Locked wagers settles "
         "this one")

r = client().post("/admin/tuesday-sync", headers=hdr,
                  json={"league_id": LEAGUE_ID, "week": DYN_WEEK,
                        "mock_mode": True})
_assert("§6: week 2's final results ingest and Versus settlement runs",
        r.status_code == 200, f"{r.status_code} {r.text[:140]}")

with SessionLocal() as db:
    _statuses = sorted(b.status for b in
                       db.query(Bet).filter(Bet.id.in_(_bet_ids)).all())
    _final = [m.finalized_at is not None for m in db.query(Matchup)
              .filter(Matchup.league_id == LEAGUE_ID,
                      Matchup.week == DYN_WEEK).all()]
    db.rollback()
_assert("§6: week 2 is economically final", _final and all(_final), str(_final))
_assert("§6: BOTH Dynamic Bet legs reached a TERMINAL state through ordinary "
        "settlement — no special Dynamic settlement path was needed",
        len(_statuses) == 2
        and all(s in ("won", "lost", "push") for s in _statuses),
        str(_statuses))
_assert("§6: and every Bet escrow account for the wager is drained",
        all(balance_of(f"escrow:{b}") == 0 for b in _bet_ids),
        str({b: balance_of(f"escrow:{b}") for b in _bet_ids}))
_assert("§6: no GM holds a negative balance",
        all(balance_of(f"wallet:{t}") >= 0 for t in team_ids),
        str({t: balance_of(f"wallet:{t}") for t in team_ids}))

r = client().post(f"/league/{LEAGUE_ID}/week/{DYN_WEEK}/close", headers=hdr)
_assert("§6: week 2 closes", r.status_code == 200,
        f"{r.status_code} {r.text[:200]}")
_assert("§6: trial balance zero after settlement and close",
        trial_balance() == 0, str(trial_balance()))


# ══════════════════════════════════════════════════════════════════════════════
# §7 · THE BLOCKER IS CLEARED
# ══════════════════════════════════════════════════════════════════════════════

_section("§7 · AFTER · `escrow_resolved` no longer refuses the close")

_open = open_escrow_accounts()
_assert("§7 CLEARED: NOT ONE escrow account holds a balance — the Dynamic "
        "challenge's are gone, and so is every other",
        _open == [], str(_open))

_step_after, _msg_after = close_refusal()
_assert("§7 CLEARED: Season Close is NO LONGER refused at `escrow_resolved`",
        _step_after != "escrow_resolved", f"{_step_after}: {_msg_after[:160]}")
_assert("§7 CLEARED: in fact every close prerequisite is now met",
        _step_after is None, f"{_step_after}: {_msg_after[:200]}")

r = client().post(f"/league/{LEAGUE_ID}/season/close", headers=hdr)
_assert("§7 CLEARED: the production route that refused with 409 in §3 now "
        "SUCCEEDS", r.status_code == 200, f"{r.status_code} {r.text[:240]}")
_assert("§7 CLEARED: trial balance zero after the season closes",
        trial_balance() == 0, str(trial_balance()))

with SessionLocal() as db:
    _ch = db.query(BeefChallenge).filter(BeefChallenge.id == DYN).one()
    _still_accepted = _ch.response_status
    db.rollback()
_assert("§7 CLEARED: and the challenge was never cancelled, declined or voided "
        "to get here — it is still an accepted, settled wager",
        _still_accepted == "accepted", str(_still_accepted))

print(f"\n     BEFORE: refused at {_step_before!r}, {_stranded} cents stranded "
      f"on challenge {DYN}")
print(f"     AFTER : refused at {_step_after!r}; bets {_bet_ids} terminal; "
      f"all escrow drained")


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 78)
if _failures:
    print(f"WP6B BLOCKER SUITE — {len(_failures)} FAILURE(S)")
    for f in _failures:
        print(f"  FAIL  {f}")
    print("=" * 78)
    tdb.teardown()
    sys.exit(1)
print("WP6B BLOCKER SUITE — ALL ASSERTIONS PASS")
print("WP6 BLOCKER 1 IS CLOSED: the Dynamic wager was priced by the system "
      "worker,")
print("settled by the ordinary weekly automation, and the season closed.")
print("=" * 78)
tdb.teardown()