"""
test_b6_group_a_ledger_pg.py — B6 Package 3 Group A: ledger primitive and
issuance surface (PostgreSQL).

SCOPE FENCE. This suite proves Group A ONLY: the canonical door constant, the
door-bound funded-balance exemption for bab_issuance:*, and the two
ledger_entries indexes. It does NOT exercise the issuance service, the cap,
the disclosure record, the season-close boundary or any route — those are
Groups B-F and do not exist yet. Nothing here imports economy/top_off.py.

Postgres only. The guard change is on the money path, and the exemption must be
proven against the same engine, the same integer-cents arithmetic and the same
transaction semantics production uses. SQLite would prove the wrong thing.

WHY THE DOOR IS HALF THE CONDITION. The exemption is keyed on
(door == APPROVED_BAB_TOPOFF_DOOR AND account.startswith("bab_issuance:")).
Scenario (d) proves the positive case works; scenario (e) proves the SAME
account under four other doors still raises InsufficientFundsError and writes
nothing. If the exemption were ever loosened to the account prefix alone, (e)
fails — which is the entire point of asserting it directly rather than
inspecting the source.

EVERY MONEY ASSERTION IS A DELTA, following test_season_allocation_pg.py.
balance_of() and trial_balance() each open their own SessionLocal and therefore
read COMMITTED state only, so a zero delta after a refused posting is real
evidence that nothing persisted rather than an artifact of reading the writer's
own uncommitted transaction.

SCENARIOS (a-i):
    a  canonical two-leg posting balances exactly (T = 1, mid, large)
    b  issuance debit equals wallet credit in magnitude, opposite in sign
    c  trial_balance() is exactly 0 before and after N postings across M teams
    d  bab_issuance:* debits from ZERO under the canonical door and succeeds
    e  the SAME account under every other door raises InsufficientFundsError
       and writes nothing
    f  the exemption is prefix-exact: "bab_issuance" without the colon, and
       wallet:*, stay fully guarded under the canonical door
    g  world and receivable:* guard behaviour is unchanged
    h  existing non-B6 callers are unaffected: a real season_allocation
       activation still posts, and the wager_settled once-only guard still
       raises AlreadySettledError rather than InsufficientFundsError
    i  both required indexes exist on ledger_entries with the right columns
       and both are NON-unique
    j  CONTAINMENT: the exemption skips ONE leg, not the rest of the posting
       (fails if `continue` is ever changed to `break`)
    k  the guard behaves identically on the caller-owned session=db path

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database (see test_support_postgres guards).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST — setup_postgres_test_db() applies its guards, sets
# DATABASE_URL to the disposable test DB, and imports+binds db.schema
# INTERNALLY. No project module may be imported before this call.
from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] B6 Group A ledger suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    """Post-setup work. Project imports live here so teardown protection
    begins the instant setup succeeds."""
    from sqlalchemy import inspect, text

    from db.schema import SessionLocal, League, Team
    from ledger.ledger import (
        APPROVED_BAB_TOPOFF_DOOR,
        AlreadySettledError,
        InsufficientFundsError,
        LedgerEntry,
        balance_of,
        post as ledger_post,
        trial_balance,
    )
    import config

    # ── helpers ───────────────────────────────────────────────────────────

    def entry_count() -> int:
        """Committed ledger_entries row count."""
        with SessionLocal() as db:
            return int(db.execute(
                text("SELECT COUNT(*) FROM ledger_entries")
            ).scalar())

    def legs_of(posting_id) -> list[tuple[str, int]]:
        """The committed legs of one posting, ordered for stable comparison."""
        with SessionLocal() as db:
            rows = (
                db.query(LedgerEntry)
                .filter(LedgerEntry.posting_id == posting_id)
                .order_by(LedgerEntry.account)
                .all()
            )
            return [(r.account, int(r.amount_cents)) for r in rows]

    def doors_of(posting_id) -> set[str]:
        with SessionLocal() as db:
            rows = (
                db.query(LedgerEntry)
                .filter(LedgerEntry.posting_id == posting_id)
                .all()
            )
            return {r.door for r in rows}

    def issuance_account(league_id: int, season: int) -> str:
        return f"bab_issuance:{league_id}:{season}"

    def top_off(league_id: int, team_id: int, amount_cents: int, season: int):
        """The canonical two-leg B6 posting, exactly as §3.3 specifies it.
        Group A owns only the ledger primitive, so this local helper stands in
        for the issuance service that Group E will build."""
        return ledger_post(
            [
                (issuance_account(league_id, season), -amount_cents),
                (f"wallet:{team_id}",                  amount_cents),
            ],
            door = APPROVED_BAB_TOPOFF_DOOR,
        )

    def seed_league(team_count: int, name: str) -> tuple[int, list[int]]:
        """Real League + Team rows, needed only by scenario (h)'s activation."""
        with SessionLocal() as db:
            league = League(season=config.ALLOCATION_SEASON, name=name)
            db.add(league)
            db.flush()
            team_ids = []
            for i in range(team_count):
                t = Team(
                    league_id = league.id,
                    team_name = f"{name} Team {i}",
                    owner     = f"Owner {i}",
                    email     = f"owner{i}_{league.id}_{name}@example.test".replace(" ", ""),
                )
                db.add(t)
                db.flush()
                team_ids.append(t.id)
            db.commit()
            return league.id, team_ids

    SEASON = config.ALLOCATION_SEASON

    # ── (a) canonical two-leg posting balances exactly ────────────────────
    print("\n(a) canonical two-leg posting balances exactly")

    _assert("(a) trial_balance() is 0 on an empty ledger",
            trial_balance() == 0, f"got {trial_balance()}")

    # 1 cent, a mid-range amount, and a full-cap-sized amount. The frozen
    # default stop's min_reserve_cents is 14 000, so 14 000 is a realistic ceiling.
    for label, T, team_id in (("1 cent", 1, 901), ("mid", 5_000, 902), ("full cap", 14_000, 903)):
        league_id = 9001
        pid = top_off(league_id, team_id, T, SEASON)
        legs = legs_of(pid)
        total = sum(amt for _, amt in legs)

        _assert(f"(a) [{label}] posting has exactly two legs",
                len(legs) == 2, f"got {len(legs)}: {legs}")
        _assert(f"(a) [{label}] legs sum to exactly zero",
                total == 0, f"sum={total}, legs={legs}")
        _assert(f"(a) [{label}] both legs carry the canonical door",
                doors_of(pid) == {APPROVED_BAB_TOPOFF_DOOR},
                f"doors={doors_of(pid)}")
        _assert(f"(a) [{label}] every leg is an int, never a float",
                all(isinstance(amt, int) for _, amt in legs),
                f"types={[type(a).__name__ for _, a in legs]}")

    # ── (b) issuance debit equals wallet credit in magnitude ──────────────
    print("\n(b) issuance debit equals wallet credit in magnitude, opposite sign")

    league_id = 9002
    team_id   = 910
    T         = 7_350

    acct_iss = issuance_account(league_id, SEASON)
    acct_wal = f"wallet:{team_id}"

    before_iss, before_wal = balance_of(acct_iss), balance_of(acct_wal)
    pid = top_off(league_id, team_id, T, SEASON)
    d_iss = balance_of(acct_iss) - before_iss
    d_wal = balance_of(acct_wal) - before_wal

    _assert("(b) wallet credit delta equals +amount_cents exactly",
            d_wal == T, f"expected +{T}, got {d_wal}")
    _assert("(b) issuance debit delta equals -amount_cents exactly",
            d_iss == -T, f"expected -{T}, got {d_iss}")
    _assert("(b) debit magnitude equals credit magnitude",
            abs(d_iss) == abs(d_wal), f"|{d_iss}| vs |{d_wal}|")
    _assert("(b) the two deltas are opposite in sign",
            d_iss == -d_wal, f"{d_iss} vs {d_wal}")
    _assert("(b) the issuance account carries a NEGATIVE (debit) balance",
            balance_of(acct_iss) < 0, f"got {balance_of(acct_iss)}")

    # ── (c) trial_balance() stays exactly zero ────────────────────────────
    print("\n(c) trial_balance() is exactly 0 before and after N postings across M teams")

    tb_before = trial_balance()
    league_id = 9003
    N_TEAMS, N_EACH = 4, 3
    posted_total = 0
    for t in range(N_TEAMS):
        for k in range(N_EACH):
            amt = 100 * (k + 1)
            top_off(league_id, 920 + t, amt, SEASON)
            posted_total += amt

    _assert("(c) trial_balance() is exactly 0 after 12 postings across 4 teams",
            trial_balance() == 0, f"got {trial_balance()}")
    _assert("(c) trial_balance() is unchanged from before the batch",
            trial_balance() == tb_before, f"{tb_before} -> {trial_balance()}")
    _assert("(c) the league-season issuance account tallies the batch exactly",
            -balance_of(issuance_account(league_id, SEASON)) == posted_total,
            f"expected {posted_total}, got {-balance_of(issuance_account(league_id, SEASON))}")

    # ── (d) bab_issuance:* debits from ZERO under the canonical door ──────
    print("\n(d) bab_issuance:* debits from zero under the canonical door")

    league_id = 9004
    acct = issuance_account(league_id, SEASON)
    _assert("(d) the issuance account starts at exactly 0",
            balance_of(acct) == 0, f"got {balance_of(acct)}")

    try:
        pid = top_off(league_id, 930, 2_500, SEASON)
        ok, outcome = True, "accepted"
    except InsufficientFundsError:
        ok, outcome = False, "raised InsufficientFundsError"

    _assert("(d) the FIRST posting from a zero issuance balance SUCCEEDS",
            ok, f"outcome={outcome}")
    _assert("(d) the issuance account is now negative by the issued amount",
            balance_of(acct) == -2_500, f"got {balance_of(acct)}")

    # ── (e) the same account under every OTHER door stays guarded ─────────
    print("\n(e) bab_issuance:* under any other door raises InsufficientFundsError")

    league_id = 9005
    acct = issuance_account(league_id, SEASON)

    # Four other doors: two real production doors, one plausible-looking
    # near-miss, and one arbitrary string. None may be exempt.
    OTHER_DOORS = [
        "season_allocation",          # a real production door
        "wager_placed",               # a real production door
        "bab_topoff",                 # near-miss on the canonical name
        "approved_bab_topoff_v2",     # superstring of the canonical name
    ]

    for other_door in OTHER_DOORS:
        before_bal   = balance_of(acct)
        before_count = entry_count()
        raised = None
        try:
            ledger_post(
                [
                    (acct,           -1_000),
                    ("wallet:940",    1_000),
                ],
                door = other_door,
            )
        except InsufficientFundsError as e:
            raised = e

        _assert(f"(e) [{other_door}] raises InsufficientFundsError",
                raised is not None,
                f"outcome={type(raised).__name__ if raised else 'ACCEPTED (exemption leaked)'}")
        _assert(f"(e) [{other_door}] wrote nothing",
                entry_count() == before_count,
                f"{before_count} -> {entry_count()}")
        _assert(f"(e) [{other_door}] left the issuance balance unchanged",
                balance_of(acct) == before_bal,
                f"{before_bal} -> {balance_of(acct)}")

    _assert("(e) the canonical door still works on that same account afterwards",
            top_off(league_id, 941, 1_000, SEASON) is not None)

    # ── (f) the exemption is prefix-exact and account-scoped ──────────────
    print("\n(f) the exemption is prefix-exact: near-miss accounts stay guarded")

    # "bab_issuance" with no colon is NOT the issuance account namespace.
    before_count = entry_count()
    raised = None
    try:
        ledger_post(
            [("bab_issuance", -500), ("wallet:950", 500)],
            door = APPROVED_BAB_TOPOFF_DOOR,
        )
    except InsufficientFundsError as e:
        raised = e
    _assert("(f) 'bab_issuance' without the colon stays fully guarded",
            raised is not None,
            f"outcome={type(raised).__name__ if raised else 'ACCEPTED (prefix match too loose)'}")
    _assert("(f) that refusal wrote nothing",
            entry_count() == before_count, f"{before_count} -> {entry_count()}")

    # A wallet:* debit from zero is still guarded EVEN under the canonical
    # door — the exemption is scoped to the issuance account, not the door.
    before_count = entry_count()
    raised = None
    try:
        ledger_post(
            [("wallet:951", -500), (issuance_account(9006, SEASON), 500)],
            door = APPROVED_BAB_TOPOFF_DOOR,
        )
    except InsufficientFundsError as e:
        raised = e
    _assert("(f) wallet:* from zero stays guarded under the canonical door",
            raised is not None,
            f"outcome={type(raised).__name__ if raised else 'ACCEPTED (door exempted too much)'}")
    _assert("(f) that refusal wrote nothing",
            entry_count() == before_count, f"{before_count} -> {entry_count()}")

    # ── (g) world and receivable:* behaviour unchanged ────────────────────
    print("\n(g) world and receivable:* guard behaviour is unchanged")

    before_world = balance_of("world")
    ledger_post([("world", -11_000), ("wallet:960", 11_000)], door="buy_in_paid")
    _assert("(g) world still debits from any balance under a non-B6 door",
            balance_of("world") - before_world == -11_000,
            f"delta={balance_of('world') - before_world}")

    before_recv = balance_of("receivable:961")
    ledger_post([("receivable:961", -11_000), ("wallet:961", 11_000)], door="buy_in_tab")
    _assert("(g) receivable:* still debits from zero under a non-B6 door",
            balance_of("receivable:961") - before_recv == -11_000,
            f"delta={balance_of('receivable:961') - before_recv}")

    # world stays exempt under the canonical door too — B6 changed nothing
    # about it. (B6 must never USE world; that is a Group E rule, not a
    # ledger-primitive rule, so the primitive still permits it here.)
    before_world = balance_of("world")
    ledger_post([("world", -100), ("wallet:962", 100)], door=APPROVED_BAB_TOPOFF_DOOR)
    _assert("(g) world's exemption is unchanged by the new door",
            balance_of("world") - before_world == -100,
            f"delta={balance_of('world') - before_world}")

    # A guarded pool account is still guarded — the generic rule survives.
    before_count = entry_count()
    raised = None
    try:
        ledger_post([("reserve:963", -100), ("wallet:963", 100)], door="season_allocation")
    except InsufficientFundsError as e:
        raised = e
    _assert("(g) reserve:* from zero is still refused",
            raised is not None,
            f"outcome={type(raised).__name__ if raised else 'ACCEPTED (generic guard broken)'}")
    _assert("(g) that refusal wrote nothing",
            entry_count() == before_count, f"{before_count} -> {entry_count()}")

    # ── (h) existing non-B6 callers are unaffected ────────────────────────
    print("\n(h) existing non-B6 ledger callers are unaffected")

    # h1 — a REAL production caller: economy/season_allocation.py's activation
    # posts three legs per team through the same guard this change touched.
    from economy.season_allocation import activate_season_allocation
    from payments.economy_config import get_league_economy_stop

    alloc_league_id, alloc_team_ids = seed_league(3, "GroupA Alloc")
    tb_before = trial_balance()
    with SessionLocal() as db:
        stop = get_league_economy_stop(alloc_league_id, db)
    with SessionLocal() as db:
        result = activate_season_allocation(alloc_league_id, db)

    _assert("(h) season activation still succeeds through the modified guard",
            result.created is True, f"created={result.created}")
    _assert("(h) activation posted one three-leg posting per team",
            len(result.posting_ids) == len(alloc_team_ids),
            f"{len(result.posting_ids)} postings for {len(alloc_team_ids)} teams")
    _assert("(h) each activation posting still has exactly three legs",
            all(len(legs_of(p)) == 3 for p in result.posting_ids),
            f"leg counts={[len(legs_of(p)) for p in result.posting_ids]}")
    _assert("(h) each activation posting still balances to zero",
            all(sum(a for _, a in legs_of(p)) == 0 for p in result.posting_ids))
    # S5-R2 reshaped where activation puts the money: the 140 now credits
    # min_reserve: and Wallet receives nothing. Both halves are asserted, so the
    # superseded wallet-funded model cannot pass this check either.
    _assert("(h) activation min_reserve credit is unchanged by the guard edit",
            balance_of(f"min_reserve:{alloc_team_ids[0]}") == stop.min_reserve_cents,
            f"expected {stop.min_reserve_cents}, got "
            f"{balance_of(f'min_reserve:{alloc_team_ids[0]}')}")
    _assert("(h) activation credits no Wallet (S5-R2)",
            balance_of(f"wallet:{alloc_team_ids[0]}") == 0,
            f"got {balance_of(f'wallet:{alloc_team_ids[0]}')}")
    _assert("(h) trial_balance() still exactly 0 after a real activation",
            trial_balance() == 0, f"got {trial_balance()}")

    # h2 — check (c), the wager_settled once-only guard, is untouched. It is
    # evaluated BEFORE check (b) for that door; the new branch sits inside (b),
    # so this must still raise AlreadySettledError, not InsufficientFundsError.
    ledger_post([("wallet:970", 5_000), ("world", -5_000)], door="buy_in_paid")
    ledger_post([("wallet:970", -5_000), ("escrow:970", 5_000)], door="wager_placed")
    ledger_post([("escrow:970", -5_000), ("wallet:970", 5_000)], door="wager_settled")

    raised_type = None
    try:
        ledger_post([("escrow:970", -5_000), ("wallet:970", 5_000)], door="wager_settled")
    except AlreadySettledError:
        raised_type = "AlreadySettledError"
    except InsufficientFundsError:
        raised_type = "InsufficientFundsError"

    _assert("(h) wager_settled still raises AlreadySettledError, not the generic error",
            raised_type == "AlreadySettledError", f"raised {raised_type}")
    _assert("(h) trial_balance() still exactly 0 at the end of the suite",
            trial_balance() == 0, f"got {trial_balance()}")

    # ── (i) both required indexes exist ───────────────────────────────────
    print("\n(i) required ledger_entries indexes exist")

    from db.schema import engine
    indexes = {ix["name"]: [c for c in ix["column_names"]]
               for ix in inspect(engine).get_indexes("ledger_entries")}

    _assert("(i) ix_ledger_entries_posting_id exists",
            "ix_ledger_entries_posting_id" in indexes,
            f"found: {sorted(indexes)}")
    _assert("(i) ix_ledger_entries_posting_id covers posting_id",
            indexes.get("ix_ledger_entries_posting_id") == ["posting_id"],
            f"columns={indexes.get('ix_ledger_entries_posting_id')}")
    _assert("(i) ix_ledger_entries_door_account exists",
            "ix_ledger_entries_door_account" in indexes,
            f"found: {sorted(indexes)}")
    _assert("(i) ix_ledger_entries_door_account covers (door, account) in order",
            indexes.get("ix_ledger_entries_door_account") == ["door", "account"],
            f"columns={indexes.get('ix_ledger_entries_door_account')}")
    _assert("(i) posting_id index is NON-unique by design (legs share it)",
            not any(ix.get("unique") for ix in inspect(engine).get_indexes("ledger_entries")
                    if ix["name"] == "ix_ledger_entries_posting_id"))
    # (door, account) must also be non-unique: one door legitimately touches the
    # same account many times — every top-off for a team credits wallet:{team_id}
    # under the same door. A unique index here would refuse the second top-off.
    _assert("(i) (door, account) index is NON-unique by design (repeat postings)",
            not any(ix.get("unique") for ix in inspect(engine).get_indexes("ledger_entries")
                    if ix["name"] == "ix_ledger_entries_door_account"))

    # ── (j) CONTAINMENT: the exemption skips ONE leg, not the remainder ───
    print("\n(j) containment: the exemption skips one leg, not the rest of the posting")

    # THIS SCENARIO EXISTS TO KILL ONE SPECIFIC MUTATION. The production guard
    # exempts a leg with `continue`. Were it ever written as `break`, the loop
    # would abandon checking EVERY REMAINING LEG the moment it met an exempt
    # bab_issuance debit — and an unfunded debit sitting after it would be
    # silently accepted.
    #
    # LEG ORDER IS THE WHOLE POINT and is load-bearing:
    #   leg 1  bab_issuance:*  debit   -> exempt, takes the branch
    #   leg 2  reserve:*       debit   -> guarded, zero balance, MUST still fail
    #   leg 3  wallet:*        credit  -> balances the posting to zero
    #
    # Scenario (f) cannot catch this: there the guarded debit is the FIRST leg,
    # so the loop raises before the exempt branch is ever reached, and `break`
    # and `continue` are indistinguishable. Here the exempt leg comes first.
    #
    # The posting sums to zero deliberately, so it clears check (a) and really
    # does reach check (b) — otherwise it would fail for the wrong reason and
    # prove nothing about the guard.
    league_id  = 9007
    acct_iss   = issuance_account(league_id, SEASON)
    acct_guard = "reserve:980"          # guarded namespace, balance 0
    acct_wal   = "wallet:980"

    before = {
        "iss":   balance_of(acct_iss),
        "guard": balance_of(acct_guard),
        "wal":   balance_of(acct_wal),
        "count": entry_count(),
        "trial": trial_balance(),
    }
    _assert("(j) the guarded second-leg account starts at exactly 0",
            before["guard"] == 0, f"got {before['guard']}")

    legs = [
        (acct_iss,   -1_000),   # exempt   -- MUST be first
        (acct_guard,   -500),   # guarded  -- MUST still be checked
        (acct_wal,    1_500),   # balances to zero
    ]
    _assert("(j) the probe posting balances to zero (so it reaches check (b))",
            sum(a for _, a in legs) == 0, f"sum={sum(a for _, a in legs)}")

    raised = None
    try:
        ledger_post(legs, door=APPROVED_BAB_TOPOFF_DOOR)
    except InsufficientFundsError as e:
        raised = e

    _assert("(j) InsufficientFundsError is raised for the guarded SECOND leg",
            raised is not None,
            f"outcome={type(raised).__name__ if raised else 'ACCEPTED (continue became break)'}")
    _assert("(j) the error names the guarded account, not the exempt one",
            raised is not None and acct_guard in str(raised),
            f"message={str(raised)[:120] if raised else 'n/a'}")
    _assert("(j) no ledger rows were written",
            entry_count() == before["count"],
            f"{before['count']} -> {entry_count()}")
    _assert("(j) the exempt issuance balance is unchanged",
            balance_of(acct_iss) == before["iss"],
            f"{before['iss']} -> {balance_of(acct_iss)}")
    _assert("(j) the guarded account balance is unchanged",
            balance_of(acct_guard) == before["guard"],
            f"{before['guard']} -> {balance_of(acct_guard)}")
    _assert("(j) the credited wallet balance is unchanged",
            balance_of(acct_wal) == before["wal"],
            f"{before['wal']} -> {balance_of(acct_wal)}")
    _assert("(j) trial_balance() is unchanged",
            trial_balance() == before["trial"],
            f"{before['trial']} -> {trial_balance()}")

    # ── (k) the guard on the caller-owned session=db path ─────────────────
    print("\n(k) the guard behaves correctly on the caller-owned session=db path")

    # §3.3 makes session=db MANDATORY for this door, so the session-provided
    # path — not the session=None path used everywhere above — is the one B6
    # will actually take in Group E. post() runs identical checks there but
    # does NOT commit; the caller owns the transaction.
    league_id = 9008
    team_id   = 981
    T         = 3_300
    acct_iss  = issuance_account(league_id, SEASON)
    acct_wal  = f"wallet:{team_id}"

    before_iss, before_wal = balance_of(acct_iss), balance_of(acct_wal)

    with SessionLocal() as db:
        pid = ledger_post(
            [(acct_iss, -T), (acct_wal, T)],
            door    = APPROVED_BAB_TOPOFF_DOOR,
            session = db,
        )
        # Uncommitted: balance_of() opens its OWN session, so it reads
        # committed state only and must not see this posting yet.
        _assert("(k) the posting is INVISIBLE to a separate session before commit",
                balance_of(acct_wal) == before_wal,
                f"{before_wal} -> {balance_of(acct_wal)}")
        db.commit()

    _assert("(k) the exemption works on the session=db path (posting committed)",
            pid is not None)
    _assert("(k) wallet credit delta is exactly +amount_cents",
            balance_of(acct_wal) - before_wal == T,
            f"delta={balance_of(acct_wal) - before_wal}")
    _assert("(k) issuance debit delta is exactly -amount_cents",
            balance_of(acct_iss) - before_iss == -T,
            f"delta={balance_of(acct_iss) - before_iss}")
    _assert("(k) the committed posting has exactly two legs",
            len(legs_of(pid)) == 2, f"legs={legs_of(pid)}")
    _assert("(k) trial_balance() is exactly 0 after the session-path posting",
            trial_balance() == 0, f"got {trial_balance()}")

    # The guard still REFUSES on the session path, and the caller's rollback
    # leaves nothing behind.
    before_count = entry_count()
    raised = None
    with SessionLocal() as db:
        try:
            ledger_post(
                [(acct_iss, -1_000), ("reserve:981", -500), ("wallet:981", 1_500)],
                door    = APPROVED_BAB_TOPOFF_DOOR,
                session = db,
            )
        except InsufficientFundsError as e:
            raised = e
        db.rollback()

    _assert("(k) containment holds on the session=db path too",
            raised is not None,
            f"outcome={type(raised).__name__ if raised else 'ACCEPTED (continue became break)'}")
    _assert("(k) nothing persisted after the caller rolled back",
            entry_count() == before_count,
            f"{before_count} -> {entry_count()}")
    _assert("(k) trial_balance() still exactly 0",
            trial_balance() == 0, f"got {trial_balance()}")


try:
    main(tdb)
finally:
    tdb.teardown()


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*60}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
