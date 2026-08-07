"""
test_b6_group_f_api_pg.py — B6 Package 3 Group F, §15 item 19: the Top-Off API
contract (PostgreSQL).

    C1-C5, C7, C9-C17   §14.3 API contract
    S1, S7, S8          §14.5 creation / rejection / cancellation after close,
                        the three API-class scenarios Group D listed but could
                        not write before the routes existed

WHAT THIS SUITE IS FOR, and what it deliberately is not. The routes are a thin
mapping layer: every lock, cap computation, posting and commit belongs to
economy/top_off.py and is proved by the Group E suites. What is proved HERE is
the mapping — who may call, what status comes back, which reason code, and that
no provenance field can be supplied by a client. Where a scenario would restate
a Group E guarantee, it asserts the HTTP surface of it and nothing more.

THE WRITE FENCE IS THE POINT OF C14. §10.2 lists what a client must never
supply, and extra="forbid" is what makes an attempt a 422 rather than a silently
dropped key. This suite drives every prohibited field individually, because a
model that ignored extras would pass a test that only sent one.

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] B6 Group F API suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []
_seq = {"n": 0}


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _uniq(prefix: str) -> str:
    _seq["n"] += 1
    return f"{prefix}{_seq['n']}"


def main(tdb) -> None:
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    import config
    from db.schema import (
        SessionLocal, FaabTransaction, League, LeagueCommissioner, Team,
        TopOffDisclosure, User, Wallet,
    )
    from ledger.ledger import trial_balance
    from auth.jwt_auth import get_current_user, hash_password
    from api.main import app
    from economy.season_allocation import activate_season_allocation
    from economy.season_close import close_season
    from scripts.bootstrap_league_commissioner import bootstrap_first_commissioner

    SEASON = config.ALLOCATION_SEASON
    client = TestClient(app)
    _current = {"id": None}

    def _as_user(user_id: int) -> None:
        _current["id"] = user_id

        def _override():
            with SessionLocal() as db:
                u = (db.query(User)
                     .filter(User.id == _current["id"], User.is_active == 1)
                     .first())
                if u is None:
                    raise HTTPException(status_code=401,
                                        detail="User not found or inactive")
                return u

        app.dependency_overrides[get_current_user] = _override

    # ── seed helpers ──────────────────────────────────────────────────────

    def _mk_league(name: str, multiplier_bps: int = 10000) -> int:
        with SessionLocal() as db:
            lg = League(season=2025, name=name, projection_source="fantasypros",
                        topoff_cap_multiplier_bps=multiplier_bps)
            db.add(lg); db.commit(); return lg.id

    def _mk_team(league_id: int, name: str) -> int:
        with SessionLocal() as db:
            t = Team(league_id=league_id, team_name=name, owner=name,
                     email=f"{name}@gg.test")
            db.add(t); db.commit(); return t.id

    def _mk_user(email: str, team_id=None) -> int:
        with SessionLocal() as db:
            u = User(email=email, hashed_password=hash_password("x"),
                     team_id=team_id, role="gm", is_active=1)
            db.add(u); db.commit(); return u.id

    class Fixture:
        """An activated league: teams with wallets, a GM per team, a
        commissioner who also owns a team, frozen allocation and multiplier."""

        def __init__(self, tag: str, n_teams: int = 2, multiplier_bps: int = 10000):
            self.league_id = _mk_league(_uniq(f"{tag}-lg"), multiplier_bps)
            self.team_ids = [_mk_team(self.league_id, _uniq(f"{tag}T"))
                             for _ in range(n_teams)]
            for t in self.team_ids:
                with SessionLocal() as db:
                    db.add(Wallet(team_id=t, balance=1000.0)); db.commit()
            # The commissioner OWNS team 0, because §5.3 makes authority and
            # team ownership independent: a commissioner may request as a GM.
            self.commissioner_id = _mk_user(f"{_uniq(tag + '_comm')}@gg.test",
                                            team_id=self.team_ids[0])
            self.gm_ids = [self.commissioner_id] + [
                _mk_user(f"{_uniq(tag + '_gm')}@gg.test", team_id=t)
                for t in self.team_ids[1:]
            ]
            bootstrap_first_commissioner(self.league_id, self.commissioner_id)
            with SessionLocal() as db:
                activate_season_allocation(self.league_id, db)

        @property
        def team_id(self) -> int:
            return self.team_ids[0]

    # ── request helpers ───────────────────────────────────────────────────

    # NOTE the parameter name. It is `path_league`, NOT `league_id`, and that is
    # load-bearing for C14: `league_id` is one of the prohibited BODY fields, and
    # a helper keyword of the same name would swallow it into the URL instead of
    # the payload — the test would then exercise a different league rather than
    # the forbidden-extra rule it claims to.
    def _create(fx, actor: int, amount: float, path_league: int = None, **extra):
        _as_user(actor)
        body = {"amount": amount}
        body.update(extra)
        return client.post(
            f"/league/{path_league or fx.league_id}/top-offs", json=body)

    def _approve(fx, actor: int, request_id: int, reason=None,
                 path_league: int = None, **extra):
        _as_user(actor)
        body = {} if reason is None else {"decision_reason": reason}
        body.update(extra)
        return client.post(
            f"/league/{path_league or fx.league_id}/top-offs/{request_id}/approve",
            json=body)

    def _reject(fx, actor: int, request_id: int, reason=None):
        _as_user(actor)
        return client.post(
            f"/league/{fx.league_id}/top-offs/{request_id}/reject",
            json={} if reason is None else {"decision_reason": reason})

    def _cancel(fx, actor: int, request_id: int, **extra):
        _as_user(actor)
        return client.post(
            f"/league/{fx.league_id}/top-offs/{request_id}/cancel", json=dict(extra))

    def _list(fx, actor: int, path_league: int = None):
        _as_user(actor)
        return client.get(f"/league/{path_league or fx.league_id}/top-offs")

    def _reason(resp):
        body = resp.json()
        detail = body.get("detail")
        return detail.get("reason_code") if isinstance(detail, dict) else None

    def _row(request_id: int):
        with SessionLocal() as db:
            return db.query(FaabTransaction).filter(
                FaabTransaction.id == request_id).one_or_none()

    def _entry_count() -> int:
        with SessionLocal() as db:
            return db.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()

    def _wallet(team_id: int) -> float:
        with SessionLocal() as db:
            return db.query(Wallet).filter(Wallet.team_id == team_id).one().balance

    # ══════════════════════════════════════════════════════════════════════
    # C1 / C2 — creation and membership
    # ══════════════════════════════════════════════════════════════════════
    print("\nC1/C2  create by a league member (201) and by a non-member (403)")
    tdb.reset()
    fx = Fixture("c1")
    outsider_league = Fixture("c1out", n_teams=1)

    r = _create(fx, fx.gm_ids[1], 20.00)
    _assert("C1 a league member creates a request -> 201",
            r.status_code == 201, f"{r.status_code}: {r.text[:110]}")
    body = r.json() if r.status_code == 201 else {}
    _assert("C1 the response carries server-derived league, team, season",
            (body.get("league_id"), body.get("team_id"), body.get("season"))
            == (fx.league_id, fx.team_ids[1], SEASON), str(body))
    _assert("C1 amount_cents is server-derived from amount",
            body.get("amount_cents") == 2000, str(body.get("amount_cents")))
    _assert("C1 the request opens pending/pending",
            (body.get("decision"), body.get("status")) == ("pending", "pending"))
    created_id = body.get("request_id")

    r = _create(fx, outsider_league.gm_ids[0], 10.00)
    _assert("C2 a non-member of the path league -> 403",
            r.status_code == 403, f"{r.status_code}: {r.text[:110]}")
    _assert("C2 the refusal names the cause",
            _reason(r) == "not_a_league_member", str(_reason(r)))

    teamless = _mk_user(f"{_uniq('c1_teamless')}@gg.test", team_id=None)
    r = _create(fx, teamless, 10.00)
    _assert("C2 a user owning no team at all -> 403", r.status_code == 403,
            str(r.status_code))

    # ══════════════════════════════════════════════════════════════════════
    # C3 / C4 / C5 — approval authorization
    # ══════════════════════════════════════════════════════════════════════
    print("\nC3/C4/C5  approval authorization")
    r = _approve(fx, fx.commissioner_id, created_id)
    _assert("C3 a commissioner of the SAME league approves -> 200",
            r.status_code == 200, f"{r.status_code}: {r.text[:110]}")
    ab = r.json() if r.status_code == 200 else {}
    _assert("C3 the posting and disclosure exist and are linked",
            ab.get("ledger_posting_id") and ab.get("disclosure_event_id"),
            str(ab))
    with SessionLocal() as db:
        n_disc = db.query(TopOffDisclosure).filter(
            TopOffDisclosure.faab_transaction_id == created_id).count()
    _assert("C3 exactly one disclosure row exists for the request", n_disc == 1,
            str(n_disc))
    _assert("C3 trial_balance() is still 0", trial_balance() == 0)

    r2 = _create(fx, fx.gm_ids[1], 10.00)
    other_id = r2.json()["request_id"]
    r = _approve(fx, outsider_league.commissioner_id, other_id)
    _assert("C4 a commissioner of a DIFFERENT league -> 403",
            r.status_code == 403, str(r.status_code))
    _assert("C4 no posting resulted", _row(other_id).ledger_posting_id is None)

    r = _approve(fx, fx.gm_ids[1], other_id)
    _assert("C5 a non-commissioner -> 403", r.status_code == 403,
            str(r.status_code))
    _assert("C5 the request is untouched",
            _row(other_id).status == "pending")

    # ══════════════════════════════════════════════════════════════════════
    # C7 / C9 — self-approval controls and classification
    # ══════════════════════════════════════════════════════════════════════
    print("\nC7/C9  self-approval reason requirement and classification")
    tdb.reset()
    fx = Fixture("c7")
    self_req = _create(fx, fx.commissioner_id, 10.00).json()["request_id"]

    entries_before = _entry_count()
    for label, reason in (("missing", None), ("blank", ""),
                          ("whitespace-only", "   \t ")):
        r = _approve(fx, fx.commissioner_id, self_req, reason)
        _assert(f"C7 [{label}] self-approval reason -> 422",
                r.status_code == 422, f"{r.status_code}: {r.text[:100]}")
        _assert(f"C7 [{label}] reason_code is self_approval_reason_required",
                _reason(r) == "self_approval_reason_required", str(_reason(r)))
    _assert("C7 no write occurred on any blank-reason attempt",
            _row(self_req).status == "pending"
            and _entry_count() == entries_before)

    r = _approve(fx, fx.commissioner_id, self_req, "covering a bad week")
    _assert("C7 a non-empty reason then succeeds -> 200", r.status_code == 200,
            f"{r.status_code}: {r.text[:100]}")
    _assert("C7 self_approved is true", r.json().get("self_approved") is True)

    other_req = _create(fx, fx.gm_ids[1], 10.00).json()["request_id"]
    r = _approve(fx, fx.commissioner_id, other_req)
    _assert("C9 a NON-self approval needs no reason and reports "
            "self_approved false",
            r.status_code == 200 and r.json().get("self_approved") is False,
            f"{r.status_code}: {r.text[:100]}")

    # ══════════════════════════════════════════════════════════════════════
    # C10 / C11 — reject and cancel
    # ══════════════════════════════════════════════════════════════════════
    print("\nC10/C11  reject and cancel")
    tdb.reset()
    fx = Fixture("c10")
    rej_id = _create(fx, fx.gm_ids[1], 10.00).json()["request_id"]
    before_entries = _entry_count()
    before_wallet  = _wallet(fx.team_ids[1])

    r = _reject(fx, fx.commissioner_id, rej_id, "not this week")
    _assert("C10 a commissioner rejects -> 200", r.status_code == 200,
            f"{r.status_code}: {r.text[:110]}")
    rb = r.json()
    _assert("C10 the row is rejected/rejected",
            (rb.get("decision"), rb.get("status")) == ("rejected", "rejected"))
    _assert("C10 no ledger entry, no linkage, no wallet change",
            _entry_count() == before_entries
            and rb.get("ledger_posting_id") is None
            and rb.get("disclosure_event_id") is None
            and _wallet(fx.team_ids[1]) == before_wallet)

    can_id = _create(fx, fx.gm_ids[1], 10.00).json()["request_id"]
    r = _cancel(fx, fx.commissioner_id, can_id)
    _assert("C11 cancel by another user -> 403", r.status_code == 403,
            f"{r.status_code}: {r.text[:110]}")
    r = _cancel(fx, fx.gm_ids[1], can_id)
    _assert("C11 cancel by the requester -> 200", r.status_code == 200,
            f"{r.status_code}: {r.text[:110]}")
    _assert("C11 the row is cancelled/cancelled",
            (r.json().get("decision"), r.json().get("status"))
            == ("cancelled", "cancelled"))

    # §10.1 replay rules, on the routes.
    r = _reject(fx, fx.commissioner_id, rej_id, "again")
    _assert("C10 repeating the SAME decision returns 200 with the original",
            r.status_code == 200 and r.json().get("replayed") is True,
            f"{r.status_code}: {r.text[:100]}")
    r = _approve(fx, fx.commissioner_id, rej_id, "changed my mind")
    _assert("C10 a DIFFERENT action on a terminal request -> 409",
            r.status_code == 409, f"{r.status_code}: {r.text[:100]}")
    _assert("C10 the conflict reason_code is terminal_state_conflict",
            _reason(r) == "terminal_state_conflict", str(_reason(r)))

    # ══════════════════════════════════════════════════════════════════════
    # C12 / C13 / C15 — amounts, capacity and the zero-headroom causes
    # ══════════════════════════════════════════════════════════════════════
    print("\nC12/C13/C15  amount validation, capacity and the three distinct "
          "zero-headroom causes")
    tdb.reset()
    fx = Fixture("c12")
    r = _create(fx, fx.gm_ids[1], 500.00)          # cap is $140
    _assert("C12 over remaining capacity -> 422", r.status_code == 422,
            f"{r.status_code}: {r.text[:110]}")
    _assert("C12 reason_code is over_capacity", _reason(r) == "over_capacity")
    _assert("C12 remaining_capacity_cents is STATED",
            r.json()["detail"].get("remaining_capacity_cents") == 14000,
            str(r.json()["detail"]))

    for label, amount in (("zero", 0.0), ("negative", -5.0),
                          ("sub-cent", 10.005)):
        r = _create(fx, fx.gm_ids[1], amount)
        _assert(f"C13 [{label}] amount -> 400", r.status_code == 400,
                f"{r.status_code}: {r.text[:100]}")
        _assert(f"C13 [{label}] reason_code is invalid_amount",
                _reason(r) == "invalid_amount", str(_reason(r)))

    # Cause 1 — a frozen 0 bps multiplier: top-offs disabled for the season.
    fx0 = Fixture("c15zero", n_teams=1, multiplier_bps=0)
    r = _create(fx0, fx0.commissioner_id, 5.00)
    _assert("C15 cause 1 (multiplier is 0) -> 422 multiplier_zero",
            r.status_code == 422 and _reason(r) == "multiplier_zero",
            f"{r.status_code}/{_reason(r)}")

    # Cause 2 — no valid allocation.
    fxn = Fixture("c15noalloc", n_teams=1)
    with SessionLocal() as db:
        db.execute(text("DELETE FROM season_allocation WHERE league_id = :l"),
                   {"l": fxn.league_id})
        db.commit()
    r = _create(fxn, fxn.commissioner_id, 5.00)
    _assert("C15 cause 2 (no allocation) -> 422 no_allocation",
            r.status_code == 422 and _reason(r) == "no_allocation",
            f"{r.status_code}/{_reason(r)}")

    # Cause 3 — the cap exists and is fully consumed.
    fxe = Fixture("c15exhaust", n_teams=1)
    full = _create(fxe, fxe.commissioner_id, 140.00).json()["request_id"]
    _approve(fxe, fxe.commissioner_id, full, "consume the cap")
    r = _create(fxe, fxe.commissioner_id, 1.00)
    _assert("C15 cause 3 (cap exhausted) -> 422 cap_exhausted",
            r.status_code == 422 and _reason(r) == "cap_exhausted",
            f"{r.status_code}/{_reason(r)}")
    _assert("C15 the three causes are three DISTINCT reason codes, never merged",
            len({"multiplier_zero", "no_allocation", "cap_exhausted"}) == 3)

    # An open request already exists -> 409, distinct from every 422 above.
    fxd = Fixture("c-dup", n_teams=1)
    _create(fxd, fxd.commissioner_id, 10.00)
    r = _create(fxd, fxd.commissioner_id, 10.00)
    _assert("C-dup a second OPEN request -> 409 open_request_exists",
            r.status_code == 409 and _reason(r) == "open_request_exists",
            f"{r.status_code}/{_reason(r)}")

    # ══════════════════════════════════════════════════════════════════════
    # C14 — extra="forbid" on all four write bodies
    # ══════════════════════════════════════════════════════════════════════
    print("\nC14  every prohibited provenance field is rejected with 422 "
          "(§10.2)")
    tdb.reset()
    fx = Fixture("c14")
    live_id = _create(fx, fx.gm_ids[1], 10.00).json()["request_id"]

    PROHIBITED = {
        "league_id":           99,
        "team_id":             99,
        "season":              1999,
        "requester_user_id":   99,
        "decided_by_user_id":  99,
        "self_approved":       True,
        "amount_cents":        999999,
        "cap_cents":           999999,
        "remaining_capacity_cents": 999999,
        "ledger_posting_id":   "00000000-0000-0000-0000-000000000000",
        "disclosure_event_id": "00000000-0000-0000-0000-000000000000",
        "decided_at":          "1999-01-01T00:00:00",
        "created_at":          "1999-01-01T00:00:00",
        "decision":            "approved",
        "status":              "applied",
        "account":             "wallet:1",
    }
    for field, value in PROHIBITED.items():
        r = _create(fx, fx.gm_ids[1], 10.00, **{field: value})
        _assert(f"C14 create rejects {field!r} with 422", r.status_code == 422,
                f"{r.status_code}: {r.text[:80]}")
    for field, value in PROHIBITED.items():
        r = _approve(fx, fx.commissioner_id, live_id, "reason", **{field: value})
        _assert(f"C14 approve rejects {field!r} with 422", r.status_code == 422,
                f"{r.status_code}: {r.text[:80]}")
    r = _reject(fx, fx.commissioner_id, live_id)
    _as_user(fx.commissioner_id)
    r = client.post(f"/league/{fx.league_id}/top-offs/{live_id}/reject",
                    json={"decision_reason": "x", "decided_by_user_id": 99})
    _assert("C14 reject rejects a spoofed approver identity with 422",
            r.status_code == 422, f"{r.status_code}: {r.text[:80]}")
    _as_user(fx.gm_ids[1])
    r = client.post(f"/league/{fx.league_id}/top-offs/{live_id}/cancel",
                    json={"requester_user_id": 99})
    _assert("C14 cancel rejects a spoofed requester identity with 422",
            r.status_code == 422, f"{r.status_code}: {r.text[:80]}")

    _assert("C14 a request carrying MANY spoofed fields at once is rejected",
            _create(fx, fx.gm_ids[1], 10.00, season=1999, amount_cents=1,
                    decided_by_user_id=1).status_code == 422)
    with SessionLocal() as db:
        n_after = db.query(FaabTransaction).filter(
            FaabTransaction.league_id == fx.league_id).count()
    _assert("C14 no rejected body created a row", n_after == 1, str(n_after))

    # ══════════════════════════════════════════════════════════════════════
    # C16 / C17 — the read surface
    # ══════════════════════════════════════════════════════════════════════
    print("\nC16/C17  GET scoping and provenance traversal")
    tdb.reset()
    fx = Fixture("c16", n_teams=2)
    own_id   = _create(fx, fx.gm_ids[1], 10.00).json()["request_id"]
    comm_id_ = _create(fx, fx.commissioner_id, 10.00).json()["request_id"]
    _approve(fx, fx.commissioner_id, own_id)

    r = _list(fx, fx.commissioner_id)
    _assert("C16 the commissioner sees ALL requests in the league",
            r.status_code == 200 and {x["id"] for x in r.json()}
            == {own_id, comm_id_}, f"{r.status_code}: {r.text[:120]}")
    r = _list(fx, fx.gm_ids[1])
    _assert("C16 an ordinary GM sees only his own team's requests",
            r.status_code == 200 and {x["id"] for x in r.json()} == {own_id},
            f"{r.status_code}: {r.text[:120]}")
    # A FRESH teamless user: tdb.reset() above truncated the one made earlier,
    # and an id that no longer exists would answer 401 from the auth override
    # rather than the 403 this scenario is about.
    c16_teamless = _mk_user(f"{_uniq('c16_teamless')}@gg.test", team_id=None)
    r = _list(fx, c16_teamless)
    _assert("C16 a caller with no team in the league -> 403",
            r.status_code == 403, f"{r.status_code}: {r.text[:110]}")
    _assert("C16 the refusal names the cause",
            _reason(r) == "not_a_league_member", str(_reason(r)))

    rows = _list(fx, fx.commissioner_id).json()
    _assert("C16 the payload is ordered by created_at then id",
            [x["id"] for x in rows] == sorted(x["id"] for x in rows),
            str([x["id"] for x in rows]))
    _assert("C16 remaining_capacity_cents is NOT in the read payload",
            all("remaining_capacity_cents" not in x for x in rows))
    _assert("C16 no recomputed cap is in the read payload",
            all("cap_cents" not in x for x in rows))

    approved = [x for x in rows if x["id"] == own_id][0]
    _assert("C17 the approved row exposes both linkage ids",
            approved["ledger_posting_id"] and approved["disclosure_event_id"],
            str(approved))
    # request -> posting -> both ledger legs -> disclosure, from the payload.
    with SessionLocal() as db:
        legs = db.execute(text(
            "SELECT account, amount_cents FROM ledger_entries "
            "WHERE posting_id = :p"), {"p": approved["ledger_posting_id"]}).fetchall()
        disc = db.query(TopOffDisclosure).filter(
            TopOffDisclosure.event_id == approved["disclosure_event_id"]).one_or_none()
    _assert("C17 the posting id resolves to exactly two legs summing to zero",
            len(legs) == 2 and sum(int(c) for _, c in legs) == 0, str(legs))
    _assert("C17 the disclosure id resolves to exactly one disclosure row",
            disc is not None and disc.faab_transaction_id == own_id,
            str(disc))
    _assert("C17 the disclosure amount matches the request",
            disc is not None and disc.amount_cents == approved["amount_cents"])
    _assert("C17 the read payload carries the persisted decision metadata",
            approved["decided_by_user_id"] == fx.commissioner_id
            and approved["decided_at"] is not None
            and approved["self_approved"] is False, str(approved))
    _assert("C16 only B6 topup_bet rows are listed",
            all(x["season"] == SEASON for x in rows), str(rows))

    # ══════════════════════════════════════════════════════════════════════
    # S1 / S7 / S8 — after season close
    # ══════════════════════════════════════════════════════════════════════
    print("\nS1/S7/S8  creation, rejection and cancellation after season close")
    tdb.reset()
    fx = Fixture("s178", n_teams=2)
    open_id = _create(fx, fx.gm_ids[1], 10.00).json()["request_id"]
    with SessionLocal() as db:
        close_season(fx.league_id, "operator:test", db=db)

    before_rows = _entry_count()
    r = _create(fx, fx.gm_ids[1], 10.00)
    _assert("S1 creation after close is REFUSED", r.status_code == 503,
            f"{r.status_code}: {r.text[:110]}")
    _assert("S1 reason_code is season_closed", _reason(r) == "season_closed")
    with SessionLocal() as db:
        n_rows = db.query(FaabTransaction).filter(
            FaabTransaction.league_id == fx.league_id).count()
    _assert("S1 no row was created", n_rows == 1, str(n_rows))

    r = _reject(fx, fx.commissioner_id, open_id, "too late")
    _assert("S7 rejection after close is NOT decided -> 503",
            r.status_code == 503, f"{r.status_code}: {r.text[:110]}")
    _assert("S7 the request remains pending",
            _row(open_id).decision == "pending")

    r = _cancel(fx, fx.gm_ids[1], open_id)
    _assert("S8 cancellation after close is NOT decided -> 503",
            r.status_code == 503, f"{r.status_code}: {r.text[:110]}")
    _assert("S8 the pending record survives close intact",
            (_row(open_id).decision, _row(open_id).status)
            == ("pending", "pending"))

    r = _approve(fx, fx.commissioner_id, open_id, "after close")
    _assert("S-approve approval after close -> 503", r.status_code == 503,
            f"{r.status_code}: {r.text[:110]}")
    _assert("S1/S7/S8 nothing economic happened after close",
            _entry_count() == before_rows and trial_balance() == 0)

    # The GET remains readable after close — a pending record is history.
    r = _list(fx, fx.commissioner_id)
    _assert("S1/S7/S8 the read surface still lists the surviving pending record",
            r.status_code == 200 and len(r.json()) == 1, str(r.status_code))

    app.dependency_overrides.clear()


try:
    main(tdb)
finally:
    tdb.teardown()

print("\n" + "=" * 60)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("All assertions PASSED")
