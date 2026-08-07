"""
test_b6_group_e_issuance_pg.py — B6 Package 3 Group E, §15 item 18: the BAB
Top-Off issuance service, single-session semantics (PostgreSQL).

SUITE SPLIT, AND WHY. Group E's assigned tests divide cleanly into two kinds:
those that assert what ONE session does, and those that can only be proved by
holding an uncommitted transaction and forcing a second session to block on a
real row lock. This file is the first kind. The second lives in
test_b6_group_e_authority_race_pg.py, which carries the whole blocking harness
(pg_blocking_pids, backend pinning, statement pauses) and nothing else. Keeping
them apart means neither file has to be read through the other's machinery.

    this file   A4-A11, P5, P6, P8, P9, P10, S3, S4, S10, S12, S15,
                SA1, SA2, SA4, SA5, plus the create/reject/cancel service
                behaviour §15 item 18 names
    race file   P1, P2, P3, P7, P11, S2, SA3, AR1-AR4, and item 17

SCOPE FENCE. This suite proves the Group E SERVICE. It exercises no route, no
Pydantic model and no HTTP status — those are Group F (§15 items 19-21) and are
deliberately absent. It imports nothing from api/. It creates no revoke writer.

WHAT "ZERO ECONOMIC PARTIAL STATE" MEANS HERE, and it is asserted literally on
every abort: no ledger entry, no change to the Wallet mirror, no disclosure row,
no linkage field, no state transition, and zero successful commits measured on
the very session handed to the service.

COMMIT COUNTS ARE MEASURED, NOT INFERRED. Every scenario that claims "exactly
one commit" or "zero commits" attaches an after_commit listener to the Session it
passes in and counts the events, following the accepted Group B/D technique. A
path that quietly committed would otherwise look identical to one that did not.

THE MIRROR ASSERTION IS THE CORRECTED ONE. A10 is asserted as

    Wallet.balance == _balance_of_in_session(db, "wallet:{team_id}") / 100.0

and the suite additionally asserts the mirror is NOT the raw integer cent
balance whenever the two differ. The ledger is authoritative and stores cents;
Wallet.balance is the pre-existing dollar-denominated compatibility mirror that
validate_bet_amount() and beef_engine read as dollars, so the conversion happens
exactly once, in the service, at step 16.

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database (see test_support_postgres guards).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST — setup_postgres_test_db() applies its guards, sets DATABASE_URL
# to the disposable test DB, and imports+binds db.schema INTERNALLY. No project
# module may be imported before this call.
from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] B6 Group E issuance suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

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
    """Post-setup work. Project imports live here so teardown protection begins
    the instant setup succeeds."""
    import io
    import re
    import tokenize
    import uuid
    from datetime import datetime, timezone
    from pathlib import Path

    from sqlalchemy import event, text
    from sqlalchemy.exc import IntegrityError

    import config
    from db.schema import (
        SessionLocal, FaabTransaction, League, LeagueCommissioner,
        LeagueSeasonTopoffConfig, SeasonAllocation, Team, TopOffDisclosure,
        User, Wallet,
    )
    from ledger.ledger import (
        APPROVED_BAB_TOPOFF_DOOR, _balance_of_in_session, balance_of,
        trial_balance,
    )
    from auth.jwt_auth import hash_password
    from economy.season_allocation import activate_season_allocation
    from economy.season_close import close_season
    from scripts.bootstrap_league_commissioner import bootstrap_first_commissioner

    import economy.top_off as topoff
    from economy.top_off import (
        approve_top_off, cancel_top_off, create_top_off_request, reject_top_off,
        compute_cap_cents,
        AttemptValidationAbort, AuthorizationAttemptAbort, CreationRefused,
        IntegrityAttemptAbort, SeasonClosedAbort,
        REASON_CAP_EXHAUSTED, REASON_INVALID_AMOUNT, REASON_MULTIPLIER_ZERO,
        REASON_NO_ALLOCATION, REASON_OPEN_REQUEST, REASON_OVER_CAPACITY,
        REASON_SEASON_CLOSED,
    )

    SEASON = config.ALLOCATION_SEASON
    REPO   = Path(os.path.dirname(os.path.abspath(__file__)))

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

    def _mk_user(email: str) -> int:
        with SessionLocal() as db:
            u = User(email=email, hashed_password=hash_password("x"),
                     team_id=None, role="gm", is_active=1)
            db.add(u); db.commit(); return u.id

    def _mk_wallet(team_id: int, dollars: float = 1000.0) -> int:
        with SessionLocal() as db:
            w = Wallet(team_id=team_id, balance=dollars)
            db.add(w); db.commit(); return w.id

    def _grant(league_id: int, user_id: int, by_user_id: int) -> None:
        """A second/third authority row, written directly. This suite is
        single-session; the grant ROUTE's own lock discipline is Group D's and
        is proven there."""
        with SessionLocal() as db:
            db.add(LeagueCommissioner(league_id=league_id, user_id=user_id,
                                      source="local_grant",
                                      assigned_by_user_id=by_user_id))
            db.commit()

    class Fixture:
        """One activated league: teams with wallets, a genesis commissioner, a
        frozen allocation and a frozen multiplier — the state approval reads."""

        def __init__(self, tag: str, n_teams: int = 1, multiplier_bps: int = 10000):
            self.tag = tag
            self.league_id = _mk_league(_uniq(f"{tag}-lg"), multiplier_bps)
            self.team_ids = [_mk_team(self.league_id, _uniq(f"{tag}T"))
                             for _ in range(n_teams)]
            for t in self.team_ids:
                _mk_wallet(t)
            self.commissioner_id = _mk_user(f"{_uniq(tag + '_comm')}@gg.test")
            self.gm_ids = [_mk_user(f"{_uniq(tag + '_gm')}@gg.test")
                           for _ in range(n_teams)]
            bootstrap_first_commissioner(self.league_id, self.commissioner_id)
            with SessionLocal() as db:
                activate_season_allocation(self.league_id, db)

        @property
        def team_id(self) -> int:
            return self.team_ids[0]

        @property
        def gm_id(self) -> int:
            return self.gm_ids[0]

    # ── measurement helpers ───────────────────────────────────────────────

    class Svc:
        """A Session handed to the service, with its commits counted.

        The count is taken on the VERY session the service uses, so "exactly one
        commit" and "zero commits" are measurements rather than inferences.
        """

        def __init__(self):
            self.db = SessionLocal()
            self.commits = 0
            event.listen(self.db, "after_commit", self._bump)

        def _bump(self, session):
            self.commits += 1

        def close(self):
            event.remove(self.db, "after_commit", self._bump)
            self.db.close()

    def _run(fn, *args, **kwargs):
        """Call a service entry point on a fresh counted session. Returns
        (result_or_None, exception_or_None, commit_count)."""
        svc = Svc()
        try:
            out = fn(*args, db=svc.db, **kwargs)
            return out, None, svc.commits
        except Exception as exc:                  # noqa: BLE001 — recording
            return None, exc, svc.commits
        finally:
            svc.close()

    def _row(request_id: int):
        with SessionLocal() as db:
            return db.query(FaabTransaction).filter(
                FaabTransaction.id == request_id).one_or_none()

    def _wallet_balance(team_id: int) -> float:
        with SessionLocal() as db:
            return db.query(Wallet).filter(Wallet.team_id == team_id).one().balance

    def _ledger_cents(account: str) -> int:
        with SessionLocal() as db:
            return _balance_of_in_session(db, account)

    def _all_balances() -> dict:
        with SessionLocal() as db:
            rows = db.execute(text(
                "SELECT account, COALESCE(SUM(amount_cents),0) "
                "FROM ledger_entries GROUP BY account")).fetchall()
        return {a: int(v) for a, v in rows}

    def _entry_count() -> int:
        with SessionLocal() as db:
            return db.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()

    def _disclosures(request_id: int = None):
        with SessionLocal() as db:
            q = db.query(TopOffDisclosure)
            if request_id is not None:
                q = q.filter(TopOffDisclosure.faab_transaction_id == request_id)
            return q.order_by(TopOffDisclosure.id).all()

    def _legs(posting_id):
        with SessionLocal() as db:
            rows = db.execute(text(
                "SELECT account, amount_cents, door FROM ledger_entries "
                "WHERE posting_id = :p ORDER BY amount_cents"),
                {"p": posting_id}).fetchall()
        return [(a, int(c), d) for a, c, d in rows]

    def _assert_full_issuance(tag: str, fx, result, amount_cents: int,
                              commits: int, expect_self: bool) -> None:
        """The complete success postcondition, asserted identically everywhere a
        top-off is issued: balanced two-leg posting, zero trial balance, exactly
        one disclosure, both linkage fields, the mirror derived from the ledger
        post-state, and exactly one commit."""
        row = _row(result.request_id)
        _assert(f"{tag} decision/status are approved/applied",
                (row.decision, row.status) == ("approved", "applied"),
                f"{row.decision}/{row.status}")
        _assert(f"{tag} exactly one commit on the service's own session",
                commits == 1, str(commits))

        legs = _legs(result.ledger_posting_id)
        _assert(f"{tag} the posting is EXACTLY two legs", len(legs) == 2, str(legs))
        _assert(f"{tag} the legs sum to zero",
                sum(c for _, c, _ in legs) == 0, str(legs))
        _assert(f"{tag} the issuance leg is -amount_cents",
                (f"bab_issuance:{fx.league_id}:{SEASON}", -amount_cents,
                 APPROVED_BAB_TOPOFF_DOOR) in legs, str(legs))
        _assert(f"{tag} the wallet leg is +amount_cents",
                (f"wallet:{row.team_id}", amount_cents,
                 APPROVED_BAB_TOPOFF_DOOR) in legs, str(legs))
        _assert(f"{tag} trial_balance() is exactly 0", trial_balance() == 0,
                str(trial_balance()))

        discl = _disclosures(result.request_id)
        _assert(f"{tag} exactly ONE disclosure row", len(discl) == 1, str(len(discl)))
        if discl:
            d = discl[0]
            _assert(f"{tag} the disclosure carries the posting id",
                    d.ledger_posting_id == result.ledger_posting_id)
            _assert(f"{tag} disclosure provenance is denormalised and correct",
                    (d.league_id, d.season, d.team_id, d.amount_cents,
                     d.requester_user_id, d.decided_by_user_id, d.self_approved)
                    == (fx.league_id, SEASON, row.team_id, amount_cents,
                        row.requester_user_id, row.decided_by_user_id, expect_self),
                    f"{(d.league_id, d.season, d.team_id, d.amount_cents, d.requester_user_id, d.decided_by_user_id, d.self_approved)}")
            _assert(f"{tag} disclosure_event_id stores the UUID event_id, not the PK",
                    row.disclosure_event_id == d.event_id
                    and row.disclosure_event_id != d.id,
                    f"{row.disclosure_event_id} vs event_id={d.event_id} id={d.id}")

        _assert(f"{tag} BOTH linkage fields are populated",
                row.ledger_posting_id is not None
                and row.disclosure_event_id is not None,
                f"{row.ledger_posting_id} / {row.disclosure_event_id}")
        _assert(f"{tag} self_approved recorded as {expect_self}",
                row.self_approved is expect_self, str(row.self_approved))

        cents = _ledger_cents(f"wallet:{row.team_id}")
        _assert(f"{tag} A10: the mirror equals the ledger post-state / 100.0",
                _wallet_balance(row.team_id) == cents / 100.0,
                f"mirror={_wallet_balance(row.team_id)} ledger_cents={cents}")
        _assert(f"{tag} A10: the mirror is NOT the raw integer cent balance",
                _wallet_balance(row.team_id) != cents, f"cents={cents}")

    def _assert_no_economic_effect(tag: str, fx, request_id: int, before: dict,
                                   commits: int, wallet_before: float,
                                   discl_before: int) -> None:
        """The complete abort postcondition: pending, no linkage, no ledger
        movement, no mirror change, no disclosure, zero commits."""
        row = _row(request_id)
        _assert(f"{tag} the request remains PENDING",
                (row.decision, row.status) == ("pending", "pending"),
                f"{row.decision}/{row.status}")
        _assert(f"{tag} both linkage fields remain NULL",
                row.ledger_posting_id is None and row.disclosure_event_id is None,
                f"{row.ledger_posting_id} / {row.disclosure_event_id}")
        _assert(f"{tag} ZERO successful commits", commits == 0, str(commits))
        _assert(f"{tag} no ledger movement on any account",
                _all_balances() == before, "ledger balances changed")
        _assert(f"{tag} the Wallet mirror is unchanged",
                _wallet_balance(fx.team_id) == wallet_before,
                f"{wallet_before} -> {_wallet_balance(fx.team_id)}")
        _assert(f"{tag} no disclosure row was created",
                len(_disclosures()) == discl_before,
                f"{discl_before} -> {len(_disclosures())}")

    def _open_request(fx, dollars: float, requester_id: int = None,
                      team_id: int = None):
        """A committed pending request, through the real creation path."""
        with SessionLocal() as db:
            return create_top_off_request(
                fx.league_id,
                fx.team_id if team_id is None else team_id,
                fx.gm_id if requester_id is None else requester_id,
                dollars, db=db,
            )

    # ══════════════════════════════════════════════════════════════════════
    # SA1 — self-approval, approver holds the only authority row
    # ══════════════════════════════════════════════════════════════════════
    print("\nSA1  self-approval succeeds when the approver holds the ONLY "
          "commissioner row (§5.2)")
    tdb.reset()
    fx = Fixture("sa1")
    # The commissioner IS the requester: authority and team ownership are
    # independent by design (§5.3), so a commissioner may request as a GM.
    req = _open_request(fx, 20.00, requester_id=fx.commissioner_id)
    res, exc, commits = _run(approve_top_off, fx.league_id, req.request_id,
                             fx.commissioner_id, "covering a bad week")

    _assert("SA1 the approval succeeded", exc is None and res is not None,
            f"{type(exc).__name__}: {exc}")
    if res is not None:
        _assert("SA1 the result reports it posted", res.posted is True)
        _assert_full_issuance("SA1", fx, res, 2000, commits, expect_self=True)
        _assert("SA1 the reason is persisted on the request",
                _row(req.request_id).decision_reason == "covering a bad week")
        _assert("SA1 the disclosure carries the reason",
                _disclosures(req.request_id)[0].decision_reason
                == "covering a bad week")
    with SessionLocal() as db:
        n_comms = db.query(LeagueCommissioner).filter(
            LeagueCommissioner.league_id == fx.league_id).count()
    _assert("SA1 precondition: the league had exactly ONE authority row",
            n_comms == 1, str(n_comms))

    # ══════════════════════════════════════════════════════════════════════
    # SA2 — identical outcome with other commissioners present
    # ══════════════════════════════════════════════════════════════════════
    print("\nSA2  self-approval succeeds identically when OTHER commissioners "
          "exist — no count is a permission input")
    tdb.reset()
    fx2 = Fixture("sa2")
    other1 = _mk_user(f"{_uniq('sa2_other')}@gg.test")
    other2 = _mk_user(f"{_uniq('sa2_other')}@gg.test")
    _grant(fx2.league_id, other1, fx2.commissioner_id)
    _grant(fx2.league_id, other2, fx2.commissioner_id)
    with SessionLocal() as db:
        n_comms2 = db.query(LeagueCommissioner).filter(
            LeagueCommissioner.league_id == fx2.league_id).count()
    _assert("SA2 precondition: the league has THREE authority rows",
            n_comms2 == 3, str(n_comms2))

    req2 = _open_request(fx2, 20.00, requester_id=fx2.commissioner_id)
    res2, exc2, commits2 = _run(approve_top_off, fx2.league_id, req2.request_id,
                                fx2.commissioner_id, "covering a bad week")
    _assert("SA2 the approval succeeded", exc2 is None and res2 is not None,
            f"{type(exc2).__name__}: {exc2}")
    if res2 is not None:
        _assert_full_issuance("SA2", fx2, res2, 2000, commits2, expect_self=True)
        _assert("SA2 the outcome is identical to SA1 in every material field",
                (res2.decision, res2.status, res2.self_approved, res2.amount_cents,
                 res2.cap_cents, res2.remaining_capacity_cents)
                == (res.decision, res.status, res.self_approved, res.amount_cents,
                    res.cap_cents, res.remaining_capacity_cents),
                f"SA1={(res.decision, res.status, res.self_approved, res.amount_cents, res.cap_cents, res.remaining_capacity_cents)} "
                f"SA2={(res2.decision, res2.status, res2.self_approved, res2.amount_cents, res2.cap_cents, res2.remaining_capacity_cents)}")

    # The rule is structural, not incidental: no EXECUTABLE line in the service
    # counts, aggregates or enumerates commissioners for a permission decision.
    #
    # SCANNING RAW SOURCE WOULD BE WRONG, and this suite learned it the hard way:
    # the service's own docstring states that it never constructs a LedgerEntry,
    # never calls post(session=None) and contains no Stripe path. A naive grep
    # cannot tell a written prohibition from a violation of it, and would fail on
    # the very prose that documents the rule. Every scan below therefore runs
    # against the module's executable tokens only, with comments and string
    # literals removed.
    def _code_only(src: str) -> str:
        skip = {tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE,
                tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
        for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
            tok_type = getattr(tokenize, name, None)
            if tok_type is not None:
                skip.add(tok_type)
        pieces = [t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
                  if t.type not in skip]
        return " ".join(pieces)

    svc_raw     = (REPO / "economy" / "top_off.py").read_text(encoding="utf-8")
    svc_src     = _code_only(svc_raw)
    svc_compact = re.sub(r"\s+", "", svc_src)

    _assert("SA2 the code-only scan is not vacuous — it still sees real code",
            "def approve_top_off" in re.sub(r"\s+", " ", svc_src)
            or "approve_top_off" in svc_src,
            svc_src[:80])
    counting = re.findall(
        r"(?:count|len)\s*\([^)]*LeagueCommissioner|LeagueCommissioner[^\n]*"
        r"\.\s*(?:count|all)\s*\(",
        svc_src)
    _assert("SA2 the service contains NO commissioner-count predicate",
            counting == [], str(counting))
    _assert("SA2 the service never imports the LeagueCommissioner model at all",
            "LeagueCommissioner" not in svc_src,
            "the authority question is asked only through is_league_commissioner")

    # ══════════════════════════════════════════════════════════════════════
    # SA4 — blank self-approval reason aborts
    # ══════════════════════════════════════════════════════════════════════
    print("\nSA4  self-approval with a blank reason ABORTS and stays pending "
          "(§5.3)")
    tdb.reset()
    fx4 = Fixture("sa4")
    for label, reason in (("missing", None), ("empty string", ""),
                          ("whitespace-only", "   \t\n  ")):
        req4 = _open_request(fx4, 10.00, requester_id=fx4.commissioner_id)
        before = _all_balances()
        wb     = _wallet_balance(fx4.team_id)
        db_n   = len(_disclosures())
        r4, e4, c4 = _run(approve_top_off, fx4.league_id, req4.request_id,
                          fx4.commissioner_id, reason)
        _assert(f"SA4 [{label}] raises AttemptValidationAbort (by TYPE)",
                isinstance(e4, AttemptValidationAbort),
                f"got {type(e4).__name__}: {e4}")
        _assert_no_economic_effect(f"SA4 [{label}]", fx4, req4.request_id,
                                   before, c4, wb, db_n)
        # Clear the open request so the next spelling can be created.
        with SessionLocal() as db:
            cancel_top_off(fx4.league_id, req4.request_id, fx4.commissioner_id, db=db)

    # ══════════════════════════════════════════════════════════════════════
    # SA5 — self and non-self approvals are identical but for two fields
    # ══════════════════════════════════════════════════════════════════════
    print("\nSA5  self-approval uses the SAME cap and posting shape as a "
          "non-self approval")
    tdb.reset()
    fx5 = Fixture("sa5", n_teams=2)
    # Team 0: the commissioner requests and approves himself.
    r_self = _open_request(fx5, 15.00, requester_id=fx5.commissioner_id,
                           team_id=fx5.team_ids[0])
    res_self, exc_self, c_self = _run(approve_top_off, fx5.league_id,
                                      r_self.request_id, fx5.commissioner_id,
                                      "self-approved, reason required")
    # Team 1: an ordinary GM requests, the commissioner approves.
    with SessionLocal() as db:
        r_other = create_top_off_request(fx5.league_id, fx5.team_ids[1],
                                         fx5.gm_ids[1], 15.00, db=db)
    res_other, exc_other, c_other = _run(approve_top_off, fx5.league_id,
                                         r_other.request_id, fx5.commissioner_id)

    _assert("SA5 both approvals succeeded",
            exc_self is None and exc_other is None,
            f"{exc_self} / {exc_other}")
    if res_self is not None and res_other is not None:
        _assert("SA5 identical cap_cents",
                res_self.cap_cents == res_other.cap_cents,
                f"{res_self.cap_cents} vs {res_other.cap_cents}")
        _assert("SA5 identical remaining-capacity arithmetic",
                res_self.remaining_capacity_cents
                == res_other.remaining_capacity_cents,
                f"{res_self.remaining_capacity_cents} vs "
                f"{res_other.remaining_capacity_cents}")
        legs_self  = [(a.split(":")[0], c) for a, c, _ in _legs(res_self.ledger_posting_id)]
        legs_other = [(a.split(":")[0], c) for a, c, _ in _legs(res_other.ledger_posting_id)]
        _assert("SA5 identical two-leg posting shape",
                sorted(legs_self) == sorted(legs_other),
                f"{sorted(legs_self)} vs {sorted(legs_other)}")
        _assert("SA5 the ONLY persisted differences are self_approved and "
                "decision_reason",
                (res_self.self_approved, res_other.self_approved) == (True, False)
                and res_self.decision_reason is not None
                and res_other.decision_reason is None,
                f"self={res_self.self_approved}/{res_self.decision_reason!r} "
                f"other={res_other.self_approved}/{res_other.decision_reason!r}")
        _assert("SA5 a non-self approval needs NO reason", c_other == 1, str(c_other))
        _assert("SA5 both committed exactly once", c_self == 1 and c_other == 1,
                f"{c_self} / {c_other}")

    # ══════════════════════════════════════════════════════════════════════
    # A8 — cap arithmetic, 5 stops x 5 multipliers
    # ══════════════════════════════════════════════════════════════════════
    print("\nA8  cap arithmetic is exact for all 5 stops x 5 multipliers (§2.8)")
    SPEC_TABLE = {
        7000:  {0: 0, 5000: 3500,  10000: 7000,  15000: 10500, 20000: 14000},
        14000: {0: 0, 5000: 7000,  10000: 14000, 15000: 21000, 20000: 28000},
        21000: {0: 0, 5000: 10500, 10000: 21000, 15000: 31500, 20000: 42000},
        28000: {0: 0, 5000: 14000, 10000: 28000, 15000: 42000, 20000: 56000},
        35000: {0: 0, 5000: 17500, 10000: 35000, 15000: 52500, 20000: 70000},
    }
    mismatches = []
    for wallet_cents, row_ in SPEC_TABLE.items():
        for bps, expected in row_.items():
            got = compute_cap_cents(wallet_cents, bps)
            if got != expected:
                mismatches.append((wallet_cents, bps, got, expected))
    _assert("A8 all 25 combinations match the specification table exactly",
            mismatches == [], str(mismatches))
    _assert("A8 every result is a plain integer number of cents",
            all(isinstance(compute_cap_cents(w, b), int)
                for w in SPEC_TABLE for b in SPEC_TABLE[w]))

    # ══════════════════════════════════════════════════════════════════════
    # S15 — divisibility fires on a corrupted pair
    # ══════════════════════════════════════════════════════════════════════
    print("\nS15  the divisibility assertion fires on corrupted frozen state — "
          "integrity abort, NEVER a floored cap (§2.7)")
    tdb.reset()
    # The multiplier must be one of the five certified values — both CHECK
    # constraints enforce that and a raw UPDATE cannot violate them — so the
    # corruption has to come from the anchor. 5000 bps is chosen deliberately:
    # under 10000 bps every anchor divides exactly (wallet_cents * 10000 is
    # always a multiple of 10000), so no corruption of wallet_cents alone could
    # ever produce a remainder and the assertion would be untestable.
    fx15 = Fixture("s15", multiplier_bps=5000)
    req15 = _open_request(fx15, 5.00)
    with SessionLocal() as db:
        db.execute(text("UPDATE season_allocation SET wallet_cents = 1 "
                        "WHERE league_id = :l AND team_id = :t AND season = :s"),
                   {"l": fx15.league_id, "t": fx15.team_id, "s": SEASON})
        db.commit()
    _assert("S15 precondition: the corrupted pair really is indivisible",
            (1 * 5000) % 10000 != 0, "1 * 5000 = 5000, remainder 5000")
    before15 = _all_balances(); wb15 = _wallet_balance(fx15.team_id)
    dn15 = len(_disclosures())
    r15, e15, c15 = _run(approve_top_off, fx15.league_id, req15.request_id,
                         fx15.commissioner_id)
    _assert("S15 raises IntegrityAttemptAbort (by TYPE)",
            isinstance(e15, IntegrityAttemptAbort), f"got {type(e15).__name__}: {e15}")
    _assert("S15 the refusal names the non-exact-cent product",
            e15 is not None and "not exact-cent" in str(e15), str(e15)[:90])
    _assert_no_economic_effect("S15", fx15, req15.request_id, before15, c15,
                               wb15, dn15)
    # 1 * 5000 // 10000 would floor to 0; a floored cap would have produced a
    # terminal REJECTION instead of an abort. It must not have.
    _assert("S15 the request was NOT rejected — a corrupt cap is never the "
            "requester's fault (invariant 32)",
            _row(req15.request_id).decision == "pending")

    # ══════════════════════════════════════════════════════════════════════
    # S3 — approval after close
    # ══════════════════════════════════════════════════════════════════════
    print("\nS3  approval after season close → abort, request stays pending "
          "(§7.5)")
    tdb.reset()
    fx3 = Fixture("s3")
    req3 = _open_request(fx3, 10.00)
    with SessionLocal() as db:
        close_season(fx3.league_id, "operator:test", db=db)
    before3 = _all_balances(); wb3 = _wallet_balance(fx3.team_id)
    dn3 = len(_disclosures())
    r3, e3, c3 = _run(approve_top_off, fx3.league_id, req3.request_id,
                      fx3.commissioner_id)
    _assert("S3 raises SeasonClosedAbort (by TYPE)",
            isinstance(e3, SeasonClosedAbort), f"got {type(e3).__name__}: {e3}")
    _assert_no_economic_effect("S3", fx3, req3.request_id, before3, c3, wb3, dn3)
    # And creation after close is refused too, with its own distinct cause.
    with SessionLocal() as db:
        try:
            create_top_off_request(fx3.league_id, fx3.team_id, fx3.gm_id, 5.00, db=db)
            e3c = None
        except Exception as exc:                  # noqa: BLE001 — recording
            e3c = exc
    _assert("S3 creation after close is refused with reason 'season_closed'",
            isinstance(e3c, CreationRefused) and e3c.reason_code == REASON_SEASON_CLOSED,
            f"got {type(e3c).__name__}: {getattr(e3c, 'reason_code', None)}")

    # ══════════════════════════════════════════════════════════════════════
    # S4 / S10 — missing frozen state
    # ══════════════════════════════════════════════════════════════════════
    print("\nS4   missing allocation snapshot → integrity abort, stays pending")
    tdb.reset()
    fx4b = Fixture("s4")
    req4b = _open_request(fx4b, 10.00)
    with SessionLocal() as db:
        db.execute(text("DELETE FROM season_allocation WHERE league_id = :l"),
                   {"l": fx4b.league_id})
        db.commit()
    before4 = _all_balances(); wb4 = _wallet_balance(fx4b.team_id)
    dn4 = len(_disclosures())
    r4b, e4b, c4b = _run(approve_top_off, fx4b.league_id, req4b.request_id,
                         fx4b.commissioner_id)
    _assert("S4 raises IntegrityAttemptAbort (by TYPE)",
            isinstance(e4b, IntegrityAttemptAbort), f"got {type(e4b).__name__}: {e4b}")
    _assert_no_economic_effect("S4", fx4b, req4b.request_id, before4, c4b, wb4, dn4)

    print("\nS10  missing config snapshot with the allocation PRESENT → "
          "integrity abort, stays pending")
    tdb.reset()
    fx10 = Fixture("s10")
    req10 = _open_request(fx10, 10.00)
    with SessionLocal() as db:
        db.execute(text("DELETE FROM league_season_topoff_config WHERE league_id = :l"),
                   {"l": fx10.league_id})
        db.commit()
    with SessionLocal() as db:
        alloc_still_there = db.query(SeasonAllocation).filter(
            SeasonAllocation.league_id == fx10.league_id).count()
    _assert("S10 precondition: the allocation row is still present",
            alloc_still_there == 1, str(alloc_still_there))
    before10 = _all_balances(); wb10 = _wallet_balance(fx10.team_id)
    dn10 = len(_disclosures())
    r10, e10, c10 = _run(approve_top_off, fx10.league_id, req10.request_id,
                         fx10.commissioner_id)
    _assert("S10 raises IntegrityAttemptAbort (by TYPE)",
            isinstance(e10, IntegrityAttemptAbort), f"got {type(e10).__name__}: {e10}")
    _assert("S10 the refusal names the missing frozen multiplier",
            e10 is not None and "league_season_topoff_config" in str(e10),
            str(e10)[:90])
    _assert_no_economic_effect("S10", fx10, req10.request_id, before10, c10,
                               wb10, dn10)

    # ══════════════════════════════════════════════════════════════════════
    # P5 — authority removed before approval begins
    # ══════════════════════════════════════════════════════════════════════
    print("\nP5   authority row deleted before approval begins → authorization "
          "abort, stays pending")
    tdb.reset()
    fx5b = Fixture("p5")
    req5b = _open_request(fx5b, 10.00)
    with SessionLocal() as db:
        db.execute(text("DELETE FROM league_commissioners WHERE league_id = :l"),
                   {"l": fx5b.league_id})
        db.commit()
    before5 = _all_balances(); wb5 = _wallet_balance(fx5b.team_id)
    dn5 = len(_disclosures())
    r5b, e5b, c5b = _run(approve_top_off, fx5b.league_id, req5b.request_id,
                         fx5b.commissioner_id)
    _assert("P5 raises AuthorizationAttemptAbort (by TYPE)",
            isinstance(e5b, AuthorizationAttemptAbort),
            f"got {type(e5b).__name__}: {e5b}")
    _assert_no_economic_effect("P5", fx5b, req5b.request_id, before5, c5b, wb5, dn5)
    _assert("P5 the request stays DECIDABLE — it was not rejected",
            _row(req5b.request_id).decision == "pending")

    # ══════════════════════════════════════════════════════════════════════
    # P6 — replay after simulated response loss
    # ══════════════════════════════════════════════════════════════════════
    print("\nP6   approval replay is idempotent — one posting, second call "
          "writes nothing (§8.5)")
    tdb.reset()
    fx6 = Fixture("p6")
    req6 = _open_request(fx6, 12.00)
    res6a, exc6a, c6a = _run(approve_top_off, fx6.league_id, req6.request_id,
                             fx6.commissioner_id)
    entries_after_first = _entry_count()
    bal_after_first     = _wallet_balance(fx6.team_id)
    # The caller never saw the response and retries the identical call.
    res6b, exc6b, c6b = _run(approve_top_off, fx6.league_id, req6.request_id,
                             fx6.commissioner_id)
    _assert("P6 the first approval posted", exc6a is None and res6a.posted is True)
    _assert("P6 the replay did not raise", exc6b is None,
            f"{type(exc6b).__name__}: {exc6b}")
    _assert("P6 the replay reports replayed=True and posted=False",
            res6b is not None and res6b.replayed is True and res6b.posted is False,
            f"replayed={getattr(res6b, 'replayed', None)}")
    _assert("P6 the replay returns the ORIGINAL posting id",
            res6b.ledger_posting_id == res6a.ledger_posting_id,
            f"{res6b.ledger_posting_id} vs {res6a.ledger_posting_id}")
    _assert("P6 ZERO commits on the replay", c6b == 0, str(c6b))
    _assert("P6 no second posting was written",
            _entry_count() == entries_after_first,
            f"{entries_after_first} -> {_entry_count()}")
    _assert("P6 exactly one disclosure exists for the request",
            len(_disclosures(req6.request_id)) == 1)
    _assert("P6 the mirror did not move again",
            _wallet_balance(fx6.team_id) == bal_after_first)
    _assert("P6 trial_balance() is still 0", trial_balance() == 0)

    # ══════════════════════════════════════════════════════════════════════
    # P8 — forced posting failure
    # ══════════════════════════════════════════════════════════════════════
    print("\nP8   a forced posting failure rolls the whole issuance back")
    tdb.reset()
    fx8 = Fixture("p8")
    req8 = _open_request(fx8, 10.00)
    before8 = _all_balances(); wb8 = _wallet_balance(fx8.team_id)
    dn8 = len(_disclosures())

    class _ForcedPostingFailure(RuntimeError):
        pass

    _real_post = topoff.ledger_post
    topoff.ledger_post = lambda *a, **k: (_ for _ in ()).throw(
        _ForcedPostingFailure("forced posting failure"))
    try:
        r8, e8, c8 = _run(approve_top_off, fx8.league_id, req8.request_id,
                          fx8.commissioner_id)
    finally:
        topoff.ledger_post = _real_post

    _assert("P8 the forced failure propagated (not swallowed)",
            isinstance(e8, _ForcedPostingFailure), f"got {type(e8).__name__}: {e8}")
    _assert_no_economic_effect("P8", fx8, req8.request_id, before8, c8, wb8, dn8)
    _assert("P8 no state write survived — decision is still pending",
            _row(req8.request_id).decided_by_user_id is None
            and _row(req8.request_id).decided_at is None,
            "decision metadata leaked")
    # The seam is restored and still works, so the failure was the injection and
    # not something this suite broke.
    r8b, e8b, c8b = _run(approve_top_off, fx8.league_id, req8.request_id,
                         fx8.commissioner_id)
    _assert("P8 with the seam restored the same request approves normally",
            e8b is None and r8b.posted is True, f"{type(e8b).__name__}: {e8b}")

    # ══════════════════════════════════════════════════════════════════════
    # P9 / S12 — forced disclosure-write failure
    # ══════════════════════════════════════════════════════════════════════
    print("\nP9/S12  a disclosure-write failure rolls the WHOLE issuance back — "
          "money never moves without its disclosure (§4.5)")
    tdb.reset()
    fx9 = Fixture("p9")
    req9 = _open_request(fx9, 10.00)
    # A genuine disclosure-write failure, with no patching: plant a disclosure
    # row already claiming this request. uq_topoff_disclosure_faab_tx then makes
    # the service's own insert fail at exactly step 17.
    with SessionLocal() as db:
        db.add(TopOffDisclosure(
            event_id=uuid.uuid4(), faab_transaction_id=req9.request_id,
            league_id=fx9.league_id, season=SEASON, team_id=fx9.team_id,
            amount_cents=1, requester_user_id=fx9.gm_id,
            decided_by_user_id=fx9.commissioner_id, self_approved=False,
            decision_reason=None, decided_at=datetime.now(timezone.utc),
            ledger_posting_id=uuid.uuid4()))
        db.commit()
    before9 = _all_balances(); wb9 = _wallet_balance(fx9.team_id)
    dn9 = len(_disclosures())
    r9, e9, c9 = _run(approve_top_off, fx9.league_id, req9.request_id,
                      fx9.commissioner_id)

    _assert("P9 the disclosure write failed with IntegrityError",
            isinstance(e9, IntegrityError), f"got {type(e9).__name__}: {e9}")
    _assert("P9 it was the disclosure uniqueness guard that fired",
            e9 is not None and "uq_topoff_disclosure_faab_tx" in str(e9),
            str(e9)[:120])
    _assert_no_economic_effect("P9", fx9, req9.request_id, before9, c9, wb9, dn9)
    _assert("S12 the ledger posting from step 15 was rolled back with it — "
            "no orphan entries",
            _ledger_cents(f"bab_issuance:{fx9.league_id}:{SEASON}") == 0,
            str(_ledger_cents(f"bab_issuance:{fx9.league_id}:{SEASON}")))
    _assert("S12 trial_balance() is still exactly 0", trial_balance() == 0)
    _assert("S12 no NEW disclosure row was committed",
            len(_disclosures()) == dn9 == 1, f"{len(_disclosures())}")

    # ══════════════════════════════════════════════════════════════════════
    # P10 — missing/mismatched multiplier snapshot
    # ══════════════════════════════════════════════════════════════════════
    print("\nP10  a mismatched multiplier snapshot is read from the FROZEN row, "
          "never from live League configuration (§2.6)")
    tdb.reset()
    fx11 = Fixture("p10", multiplier_bps=10000)
    # Move the league's live dial AFTER activation. The frozen row must still
    # govern: reading the live value would double this GM's cap.
    with SessionLocal() as db:
        db.execute(text("UPDATE leagues SET topoff_cap_multiplier_bps = 20000 "
                        "WHERE id = :l"), {"l": fx11.league_id})
        db.commit()
    req11 = _open_request(fx11, 140.00)      # exactly the FROZEN cap
    res11, exc11, c11 = _run(approve_top_off, fx11.league_id, req11.request_id,
                             fx11.commissioner_id)
    _assert("P10 the frozen cap (10000 bps) governs, not the live 20000 bps",
            res11 is not None and res11.cap_cents == 14000,
            f"cap_cents={getattr(res11, 'cap_cents', None)}")
    _assert("P10 the issuance at exactly the frozen cap succeeded",
            exc11 is None and res11.posted is True, f"{type(exc11).__name__}: {exc11}")
    # And a further request is now refused for exhausted capacity, proving the
    # live 20000 bps never widened the cap.
    with SessionLocal() as db:
        try:
            create_top_off_request(fx11.league_id, fx11.team_id, fx11.gm_id,
                                   1.00, db=db)
            e11b = None
        except Exception as exc:                  # noqa: BLE001 — recording
            e11b = exc
    _assert("P10 the cap is exhausted at the FROZEN value",
            isinstance(e11b, CreationRefused)
            and e11b.reason_code == REASON_CAP_EXHAUSTED,
            f"got {type(e11b).__name__}: {getattr(e11b, 'reason_code', None)}")

    # The snapshot's own absence is P10's other half, already asserted at S10.
    _assert("P10 (missing snapshot) is covered by S10 above",
            True, "integrity abort, request stays pending")

    # ══════════════════════════════════════════════════════════════════════
    # A4-A7, A9, A10 — the accounting gate
    # ══════════════════════════════════════════════════════════════════════
    print("\nA4-A10  accounting: conservation, both derivations, mirror, and "
          "the untouched accounts")
    tdb.reset()
    fxa = Fixture("acc", n_teams=3)
    protected_before = _all_balances()
    issued_per_team = {}
    for i, tid in enumerate(fxa.team_ids):
        total = 0
        for dollars in (10.00, 25.00):
            with SessionLocal() as db:
                rq = create_top_off_request(fxa.league_id, tid, fxa.gm_ids[i],
                                            dollars, db=db)
            rr, ee, cc = _run(approve_top_off, fxa.league_id, rq.request_id,
                              fxa.commissioner_id)
            _assert(f"A4 issuance for team {tid} at ${dollars} succeeded",
                    ee is None and rr.posted is True,
                    f"{type(ee).__name__}: {ee}")
            _assert(f"A4 that issuance committed exactly once", cc == 1, str(cc))
            total += rq.amount_cents
        issued_per_team[tid] = total

    _assert("A4 trial_balance() is EXACTLY 0 after 6 top-offs across 3 teams",
            trial_balance() == 0, str(trial_balance()))

    total_issued = sum(issued_per_team.values())
    _assert("A6 -balance_of(bab_issuance:{league}:{season}) equals the "
            "league-season issuance total",
            -balance_of(f"bab_issuance:{fxa.league_id}:{SEASON}") == total_issued,
            f"{-balance_of(f'bab_issuance:{fxa.league_id}:{SEASON}')} vs {total_issued}")

    for tid in fxa.team_ids:
        with SessionLocal() as db:
            led  = topoff._issued_from_ledger(db, fxa.league_id, tid, SEASON)
            reqd = topoff._issued_from_requests(db, tid, SEASON)
        _assert(f"A5 both cap derivations agree for team {tid}",
                led == reqd == issued_per_team[tid],
                f"ledger={led} requests={reqd} expected={issued_per_team[tid]}")

    after = _all_balances()
    for tid in fxa.team_ids:
        _assert(f"A2/A3 team {tid}: wallet rose by exactly the issued total",
                after[f"wallet:{tid}"] - protected_before.get(f"wallet:{tid}", 0)
                == issued_per_team[tid],
                f"{after[f'wallet:{tid}'] - protected_before.get(f'wallet:{tid}', 0)}")
    _assert("A7 across the whole league the issuance debit exactly offsets every "
            "wallet credit — Current Settle delta is zero at issuance",
            sum(issued_per_team.values())
            + (after[f"bab_issuance:{fxa.league_id}:{SEASON}"]
               - protected_before.get(f"bab_issuance:{fxa.league_id}:{SEASON}", 0)) == 0,
            f"issued={sum(issued_per_team.values())} "
            f"issuance_leg_delta={after[f'bab_issuance:{fxa.league_id}:{SEASON}'] - protected_before.get(f'bab_issuance:{fxa.league_id}:{SEASON}', 0)}")

    untouched_prefixes = ("reserve:", "championship", "skunk", "escrow:", "world")
    moved = []
    for account, value in after.items():
        if account.startswith(untouched_prefixes) or account in untouched_prefixes:
            if protected_before.get(account, 0) != value:
                moved.append((account, protected_before.get(account, 0), value))
    _assert("A9 reserve:, championship, skunk, escrow: and world are UNTOUCHED "
            "by every top-off posting", moved == [], str(moved))
    _assert("A9 precondition: those accounts really were populated before "
            "(so the check is not vacuous)",
            any(a.startswith("reserve:") for a in protected_before)
            and "world" in protected_before,
            str(sorted(protected_before)))

    for tid in fxa.team_ids:
        cents = _ledger_cents(f"wallet:{tid}")
        _assert(f"A10 team {tid}: mirror == ledger cents / 100.0",
                _wallet_balance(tid) == cents / 100.0,
                f"mirror={_wallet_balance(tid)} cents={cents}")
        _assert(f"A10 team {tid}: mirror is NOT the raw cent integer",
                _wallet_balance(tid) != cents, f"cents={cents}")

    # ══════════════════════════════════════════════════════════════════════
    # A11 — the cents contract
    # ══════════════════════════════════════════════════════════════════════
    print("\nA11  _dollars_to_cents rejects sub-cent; _to_cents is unreachable "
          "from this path (invariant 7)")
    tdb.reset()
    fxb = Fixture("a11")
    for label, dollars in (("sub-cent", 10.005), ("zero", 0.0),
                           ("negative", -5.00)):
        with SessionLocal() as db:
            try:
                create_top_off_request(fxb.league_id, fxb.team_id, fxb.gm_id,
                                       dollars, db=db)
                eA = None
            except Exception as exc:              # noqa: BLE001 — recording
                eA = exc
        _assert(f"A11 [{label}] refused with reason 'invalid_amount'",
                isinstance(eA, CreationRefused)
                and eA.reason_code == REASON_INVALID_AMOUNT,
                f"got {type(eA).__name__}: {getattr(eA, 'reason_code', None)}")
    with SessionLocal() as db:
        n_rows = db.query(FaabTransaction).count()
    _assert("A11 no row was created by any refused amount", n_rows == 0, str(n_rows))

    # `_dollars_to_cents` CONTAINS the substring `_to_cents`, so the scan is
    # anchored to reject only a standalone use.
    bare_to_cents = re.findall(r"(?<![A-Za-z_])_to_cents\b", svc_src)
    _assert("A11 the service never references _to_cents",
            bare_to_cents == [], str(bare_to_cents))
    _assert("A11 POSITIVE CONTROL: it does reference _dollars_to_cents",
            "_dollars_to_cents" in svc_src)
    _assert("A11 the service never calls post() with session=None",
            "session=None" not in svc_compact, "in executable code")
    _assert("A11 POSITIVE CONTROL: it does pass session=db to the posting seam",
            "session=db" in svc_compact)
    _assert("A11 the service never constructs a LedgerEntry directly",
            "LedgerEntry" not in svc_src)
    _assert("A11 the service never calls balance_of() through its own session",
            re.search(r"(?<![A-Za-z_])balance_of\s*\(", svc_src) is None,
            "only _balance_of_in_session is permitted inside the transaction")
    _assert("A11 POSITIVE CONTROL: it does call _balance_of_in_session",
            "_balance_of_in_session" in svc_src)
    _assert("A11 no Stripe symbol appears on this path",
            re.search(r"stripe", svc_src, re.I) is None)

    # ══════════════════════════════════════════════════════════════════════
    # Creation refusals — the three zero-headroom causes stay distinct
    # ══════════════════════════════════════════════════════════════════════
    print("\nE-create  creation-time refusals keep the three zero-headroom "
          "causes distinct (§2.10, §7.3 outcome 1)")
    tdb.reset()
    fxz = Fixture("zero", multiplier_bps=0)
    with SessionLocal() as db:
        try:
            create_top_off_request(fxz.league_id, fxz.team_id, fxz.gm_id, 5.00, db=db)
            ez = None
        except Exception as exc:                  # noqa: BLE001 — recording
            ez = exc
    _assert("E-create cause 1 — a frozen 0 bps multiplier reports "
            "'multiplier_zero'",
            isinstance(ez, CreationRefused) and ez.reason_code == REASON_MULTIPLIER_ZERO,
            f"got {getattr(ez, 'reason_code', None)}")

    tdb.reset()
    fxn = Fixture("noalloc")
    with SessionLocal() as db:
        db.execute(text("DELETE FROM season_allocation WHERE league_id = :l"),
                   {"l": fxn.league_id})
        db.commit()
    with SessionLocal() as db:
        try:
            create_top_off_request(fxn.league_id, fxn.team_id, fxn.gm_id, 5.00, db=db)
            en = None
        except Exception as exc:                  # noqa: BLE001 — recording
            en = exc
    _assert("E-create cause 2 — no allocation reports 'no_allocation'",
            isinstance(en, CreationRefused) and en.reason_code == REASON_NO_ALLOCATION,
            f"got {getattr(en, 'reason_code', None)}")

    tdb.reset()
    fxo = Fixture("overcap")
    with SessionLocal() as db:
        try:
            create_top_off_request(fxo.league_id, fxo.team_id, fxo.gm_id,
                                   500.00, db=db)   # cap is $140
            eo = None
        except Exception as exc:                  # noqa: BLE001 — recording
            eo = exc
    _assert("E-create over-capacity reports 'over_capacity' and states the "
            "remaining capacity",
            isinstance(eo, CreationRefused)
            and eo.reason_code == REASON_OVER_CAPACITY
            and eo.remaining_capacity_cents == 14000,
            f"got {getattr(eo, 'reason_code', None)} / "
            f"{getattr(eo, 'remaining_capacity_cents', None)}")
    _assert("E-create the three zero-headroom causes are three DISTINCT codes",
            len({REASON_MULTIPLIER_ZERO, REASON_NO_ALLOCATION,
                 REASON_CAP_EXHAUSTED}) == 3)

    # One open request at a time — the pre-check half; the index half is P7.
    ok = _open_request(fxo, 10.00)
    with SessionLocal() as db:
        try:
            create_top_off_request(fxo.league_id, fxo.team_id, fxo.gm_id,
                                   10.00, db=db)
            ed = None
        except Exception as exc:                  # noqa: BLE001 — recording
            ed = exc
    _assert("E-create a second OPEN request is refused with "
            "'open_request_exists'",
            isinstance(ed, CreationRefused) and ed.reason_code == REASON_OPEN_REQUEST,
            f"got {getattr(ed, 'reason_code', None)}")
    with SessionLocal() as db:
        n_open = db.query(FaabTransaction).filter(
            FaabTransaction.league_id == fxo.league_id,
            FaabTransaction.status == "pending").count()
    _assert("E-create exactly one open request exists", n_open == 1, str(n_open))

    # ══════════════════════════════════════════════════════════════════════
    # Terminal rejection at approval, and the explicit decline
    # ══════════════════════════════════════════════════════════════════════
    print("\nE-reject  over-capacity AT APPROVAL is a terminal rejection; an "
          "explicit decline is the other (§7.4)")
    tdb.reset()
    fxr = Fixture("rej")
    rq1 = _open_request(fxr, 100.00)           # cap $140, leaves $40
    r1, e1, c1 = _run(approve_top_off, fxr.league_id, rq1.request_id,
                      fxr.commissioner_id)
    _assert("E-reject the first issuance succeeded", e1 is None and r1.posted)
    # A second request that fitted at creation but no longer fits at approval.
    rq2 = _open_request(fxr, 40.00)
    _assert("E-reject the second request was creatable at $40",
            _row(rq2.request_id) is not None)
    r2, e2, c2 = _run(approve_top_off, fxr.league_id, rq2.request_id,
                      fxr.commissioner_id)
    _assert("E-reject the second issuance consumed the remaining cap",
            e2 is None and r2.posted and r2.remaining_capacity_cents == 0,
            f"remaining={getattr(r2, 'remaining_capacity_cents', None)}")
    # Now plant a pending request directly (creation would refuse it) so approval
    # itself must produce the terminal rejection.
    with SessionLocal() as db:
        planted = FaabTransaction(
            league_id=fxr.league_id, team_id=fxr.team_id, type="topup_bet",
            amount=5.0, amount_cents=500, season=SEASON, status="pending",
            decision="pending", requester_user_id=fxr.gm_id)
        db.add(planted); db.commit(); planted_id = planted.id
    entries_before = _entry_count()
    r3r, e3r, c3r = _run(approve_top_off, fxr.league_id, planted_id,
                         fxr.commissioner_id)
    _assert("E-reject an over-capacity request at approval is REJECTED, not "
            "aborted", e3r is None and r3r is not None and r3r.decision == "rejected",
            f"{type(e3r).__name__}: {e3r}")
    _assert("E-reject it committed exactly once", c3r == 1, str(c3r))
    _assert("E-reject no posting and no linkage on a rejected row",
            _row(planted_id).ledger_posting_id is None
            and _row(planted_id).disclosure_event_id is None
            and _entry_count() == entries_before)
    _assert("E-reject status and decision are both 'rejected'",
            (_row(planted_id).decision, _row(planted_id).status)
            == ("rejected", "rejected"))

    # Explicit commissioner decline.
    tdb.reset()
    fxd = Fixture("decline")
    rqd = _open_request(fxd, 10.00)
    eb = _entry_count()
    rd, ed2, cd = _run(reject_top_off, fxd.league_id, rqd.request_id,
                       fxd.commissioner_id, "not this week")
    _assert("E-reject an explicit decline moves pending -> rejected",
            ed2 is None and rd.decision == "rejected", f"{type(ed2).__name__}: {ed2}")
    _assert("E-reject the decline committed exactly once", cd == 1, str(cd))
    _assert("E-reject the decline wrote no ledger entry and no linkage",
            _entry_count() == eb
            and _row(rqd.request_id).ledger_posting_id is None
            and _row(rqd.request_id).disclosure_event_id is None)
    _assert("E-reject the wallet mirror did not move",
            _wallet_balance(fxd.team_id) == 1000.0, str(_wallet_balance(fxd.team_id)))
    # A decline by a non-commissioner is an authorization abort.
    rqd2 = _open_request(fxd, 10.00)
    rd2, ed3, cd2 = _run(reject_top_off, fxd.league_id, rqd2.request_id,
                         fxd.gm_id, "nope")
    _assert("E-reject a non-commissioner cannot decline",
            isinstance(ed3, AuthorizationAttemptAbort),
            f"got {type(ed3).__name__}")
    _assert("E-reject that refusal committed nothing", cd2 == 0, str(cd2))

    # ══════════════════════════════════════════════════════════════════════
    # Cancellation
    # ══════════════════════════════════════════════════════════════════════
    print("\nE-cancel  only the requester may withdraw, and never after close "
          "(§7.2, §7.5)")
    tdb.reset()
    fxc = Fixture("cancel")
    rqc = _open_request(fxc, 10.00)
    rc1, ec1, cc1 = _run(cancel_top_off, fxc.league_id, rqc.request_id,
                         fxc.commissioner_id)
    _assert("E-cancel a non-requester cannot cancel",
            isinstance(ec1, AuthorizationAttemptAbort), f"got {type(ec1).__name__}")
    _assert("E-cancel that refusal committed nothing", cc1 == 0, str(cc1))
    rc2, ec2, cc2 = _run(cancel_top_off, fxc.league_id, rqc.request_id, fxc.gm_id)
    _assert("E-cancel the requester may withdraw",
            ec2 is None and rc2.decision == "cancelled", f"{type(ec2).__name__}: {ec2}")
    _assert("E-cancel it committed exactly once", cc2 == 1, str(cc2))
    _assert("E-cancel no linkage on a cancelled row",
            _row(rqc.request_id).ledger_posting_id is None
            and _row(rqc.request_id).disclosure_event_id is None)
    # Cancellation after close is not decided.
    rqc2 = _open_request(fxc, 10.00)
    with SessionLocal() as db:
        close_season(fxc.league_id, "operator:test", db=db)
    rc3, ec3, cc3 = _run(cancel_top_off, fxc.league_id, rqc2.request_id, fxc.gm_id)
    _assert("E-cancel cancellation after close ABORTS",
            isinstance(ec3, SeasonClosedAbort), f"got {type(ec3).__name__}")
    _assert("E-cancel the pending record survives close intact",
            (_row(rqc2.request_id).decision, _row(rqc2.request_id).status)
            == ("pending", "pending"))
    _assert("E-cancel zero commits on that abort", cc3 == 0, str(cc3))
    # And rejection after close is likewise not decided.
    rr3, er3, cr3 = _run(reject_top_off, fxc.league_id, rqc2.request_id,
                         fxc.commissioner_id, "too late")
    _assert("E-reject rejection after close ABORTS",
            isinstance(er3, SeasonClosedAbort), f"got {type(er3).__name__}")
    _assert("E-reject the pending record still survives",
            _row(rqc2.request_id).decision == "pending")
    _assert("E-reject zero commits on that abort", cr3 == 0, str(cr3))

    # A terminal request re-decided is the outcome-7 no-op on every path.
    rc4, ec4, cc4 = _run(cancel_top_off, fxc.league_id, rqc.request_id, fxc.gm_id)
    _assert("E-cancel re-cancelling a cancelled request is a no-op replay",
            ec4 is None and rc4.replayed is True and rc4.decision == "cancelled",
            f"{type(ec4).__name__}: {ec4}")
    _assert("E-cancel that replay committed nothing", cc4 == 0, str(cc4))


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
