"""
test_spec2_2b_foundation_pg.py — SPEC 2 · Package 2B **Group 1**: the event /
batch / provenance foundation (PostgreSQL).

    F1  ProtocolEvent.event_id is THE unique idempotency authority
    F2  one ProtocolEvent may own several LedgerPostingBatch rows
    F3  one batch may own several LedgerEntry rows
    F4  LedgerEntry batch linkage is correct
    F5  LedgerEntry carries NO competing event-id uniqueness authority
    F6  ChallengeFundingLeg carries the exact §5 provenance fields
    F7  funding-leg ordering uniqueness is enforced
    F8  reversal linkage cannot be violated structurally
    F9  every cents field is an integer type
    F10 legacy post() is behaviourally unchanged
    F11 post(protocol_event_id=…) links every entry to the intended batch
    F12 a linked batch still sums to exactly zero
    F13 the funded-account guard remains active
    F14 no new B6-style funded-guard exemption was introduced
    F15 trial_balance() stays zero after linked postings
    F16 the real production callers still execute unchanged
    F17 a duplicate event_id fails structurally at the database
    F18 no Stripe or real-money concept was introduced

WHAT GROUP 1 IS. Durable representation only. There is no funding, no escrow, no
orchestrator and no route yet, so this suite writes provenance rows by hand to
prove the SHAPE holds — the behaviour that will produce them is a later group.

THE CENTRAL CLAIM IS F5 + F17 TOGETHER. Ruling 1 puts idempotency on
ProtocolEvent.event_id and forbids LedgerEntry becoming a second event home.
Proving the authority exists is only half of it; proving no competing authority
exists is the other half, and it is the half a future edit is most likely to
break.

Requires TEST_DATABASE_URL pointing at a dedicated, empty, _test-named,
non-Railway PostgreSQL database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] Package 2B Group 1 foundation suite cannot run:\n  {e}")
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
    import io
    import re
    import tokenize
    import uuid
    from pathlib import Path

    from sqlalchemy import inspect, text
    from sqlalchemy.exc import IntegrityError

    from db.schema import (
        SessionLocal, ChallengeFundingLeg, LedgerPostingBatch, ProtocolEvent,
        BeefChallenge, League, Player, Roster, Team,
        CHALLENGE_EVENT_TYPES,
    )
    from ledger.ledger import (
        APPROVED_BAB_TOPOFF_DOOR, AlreadySettledError, LedgerEntry,
        InsufficientFundsError, LedgerImbalanceError, balance_of,
        post as ledger_post, trial_balance,
    )

    REPO   = Path(os.path.dirname(os.path.abspath(__file__)))
    engine = tdb.engine

    # ── helpers ───────────────────────────────────────────────────────────

    def _mk_event(event_type: str = "challenge_issue", **kw) -> int:
        with SessionLocal() as db:
            ev = ProtocolEvent(event_id=uuid.uuid4(), event_type=event_type, **kw)
            db.add(ev); db.commit(); return ev.id

    def _mk_league_team() -> tuple:
        with SessionLocal() as db:
            lg = League(season=2025, name=_uniq("lg"), projection_source="fantasypros")
            db.add(lg); db.flush()
            t = Team(league_id=lg.id, team_name=_uniq("T"), owner="o",
                     email=f"{_uniq('e')}@gg.test")
            db.add(t); db.commit()
            return lg.id, t.id

    def _mk_challenge(league_id: int, team_a: int, team_b: int) -> int:
        from datetime import datetime
        with SessionLocal() as db:
            ch = BeefChallenge(
                league_id=league_id, challenger_team_id=team_a,
                challenged_team_id=team_b, week=1, bet_type="straight",
                amount=10.0, challenger_odds=1.9, challenged_odds=1.9,
                challenger_moneyline=-110, challenged_moneyline=-110,
                status="pending", expires_at=datetime(2026, 9, 13, 12, 0, 0),
                response_status="offered", challenge_mode="locked",
                wager_type="straight")
            db.add(ch); db.commit(); return ch.id

    def _entries_for(posting_id) -> list:
        with SessionLocal() as db:
            return (db.query(LedgerEntry)
                    .filter(LedgerEntry.posting_id == posting_id)
                    .order_by(LedgerEntry.id).all())

    def _code_only(src: str) -> str:
        skip = {tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE,
                tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
        for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
            tok = getattr(tokenize, name, None)
            if tok is not None:
                skip.add(tok)
        return " ".join(
            t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type not in skip)

    # ══════════════════════════════════════════════════════════════════════
    # F1 / F17 — the idempotency authority
    # ══════════════════════════════════════════════════════════════════════
    print("\nF1/F17  ProtocolEvent.event_id is THE idempotency authority "
          "(Ruling 1)")
    tdb.reset()
    insp = inspect(engine)
    ev_uniques = {u["name"] for u in insp.get_unique_constraints("protocol_events")}
    _assert("F1 protocol_events carries uq_protocol_event_event_id",
            "uq_protocol_event_event_id" in ev_uniques, str(sorted(ev_uniques)))

    shared = uuid.uuid4()
    with SessionLocal() as db:
        db.add(ProtocolEvent(event_id=shared, event_type="challenge_issue"))
        db.commit()
    dup_exc = None
    try:
        with SessionLocal() as db:
            db.add(ProtocolEvent(event_id=shared, event_type="challenge_accept"))
            db.commit()
    except Exception as exc:                      # noqa: BLE001 — recording
        dup_exc = exc
    _assert("F17 a duplicate event_id is refused BY THE DATABASE",
            isinstance(dup_exc, IntegrityError), f"got {type(dup_exc).__name__}")
    _assert("F17 the violated constraint is the event-id uniqueness",
            dup_exc is not None and "uq_protocol_event_event_id" in str(dup_exc),
            str(dup_exc)[:100])
    _assert("F17 a DIFFERENT event_id of the same type is accepted — the "
            "authority is the id, not the type",
            _mk_event("challenge_issue") is not None)

    _assert("F1 event_type carries NO restrictive CHECK — Ruling 1 generalizes "
            "the table beyond challenges",
            not any("event_type" in (c.get("sqltext") or "")
                    for c in insp.get_check_constraints("protocol_events")),
            str(insp.get_check_constraints("protocol_events")))
    _assert("F1 CONTROL: a non-challenge event type is therefore insertable",
            _mk_event("settlement_payout") is not None)
    _assert("F1 the six challenge verbs are named for later groups",
            len(CHALLENGE_EVENT_TYPES) == 6
            and "challenge_accept" in CHALLENGE_EVENT_TYPES,
            str(CHALLENGE_EVENT_TYPES))

    # ══════════════════════════════════════════════════════════════════════
    # F2 / F3 / F4 / F11 / F12 / F15 — the three tiers
    # ══════════════════════════════════════════════════════════════════════
    print("\nF2-F4/F11-F15  ProtocolEvent 1→many LedgerPostingBatch 1→many "
          "LedgerEntry")
    tdb.reset()
    event_id_pk = _mk_event("challenge_accept")

    # Seed spendable balances so the guarded debits below are legal.
    with SessionLocal() as db:
        ledger_post([("world", -5000), ("wallet:1", 5000)],
                    door="test_seed", session=db)
        ledger_post([("world", -5000), ("wallet:2", 5000)],
                    door="test_seed", session=db)
        db.commit()

    # Locked acceptance is exactly the "one event, several batches" case:
    # true-up, Anchor migration and Derived funding under one accept event.
    posting_ids = []
    with SessionLocal() as db:
        posting_ids.append(ledger_post(
            [("wallet:1", -1000), ("escrow:challenge:1", 1000)],
            door="challenge_issued", session=db, protocol_event_id=event_id_pk))
        posting_ids.append(ledger_post(
            [("escrow:challenge:1", -1000), ("escrow:101", 1000)],
            door="challenge_accepted", session=db, protocol_event_id=event_id_pk))
        posting_ids.append(ledger_post(
            [("wallet:2", -750), ("escrow:102", 750)],
            door="challenge_accepted", session=db, protocol_event_id=event_id_pk))
        db.commit()

    with SessionLocal() as db:
        batches = (db.query(LedgerPostingBatch)
                   .filter(LedgerPostingBatch.protocol_event_id == event_id_pk)
                   .order_by(LedgerPostingBatch.id).all())
    _assert("F2 ONE ProtocolEvent owns THREE LedgerPostingBatch rows",
            len(batches) == 3, str(len(batches)))
    _assert("F2 each batch carries its own posting_id",
            sorted(str(b.posting_id) for b in batches)
            == sorted(str(p) for p in posting_ids), "batch posting ids diverged")
    _assert("F2 each batch records its door",
            [b.door for b in batches]
            == ["challenge_issued", "challenge_accepted", "challenge_accepted"],
            str([b.door for b in batches]))

    for b, pid in zip(batches, posting_ids):
        legs = _entries_for(pid)
        _assert(f"F3 batch {b.id} owns MULTIPLE ledger entries", len(legs) == 2,
                str(len(legs)))
        _assert(f"F4 every entry of posting {str(pid)[:8]} links to batch {b.id}",
                {l.batch_id for l in legs} == {b.id},
                str({l.batch_id for l in legs}))
        _assert(f"F12 batch {b.id} sums to exactly zero",
                sum(l.amount_cents for l in legs) == 0,
                str(sum(l.amount_cents for l in legs)))
    _assert("F11 every entry written under an event is linked — none left NULL",
            all(l.batch_id is not None for pid in posting_ids
                for l in _entries_for(pid)))
    _assert("F15 trial_balance() is exactly 0 after the linked postings",
            trial_balance() == 0, str(trial_balance()))
    _assert("F11 the escrow account holds nothing after the migration batch",
            balance_of("escrow:challenge:1") == 0,
            str(balance_of("escrow:challenge:1")))

    # ══════════════════════════════════════════════════════════════════════
    # F5 — no competing uniqueness authority on LedgerEntry
    # ══════════════════════════════════════════════════════════════════════
    print("\nF5   LedgerEntry carries NO competing event-id uniqueness "
          "authority (Ruling 1)")
    insp = inspect(engine)
    entry_cols    = {c["name"] for c in insp.get_columns("ledger_entries")}
    entry_uniques = {u["name"] for u in insp.get_unique_constraints("ledger_entries")}
    entry_indexes = {i["name"]: i for i in insp.get_indexes("ledger_entries")}

    _assert("F5 ledger_entries has NO event_id column at all — the denormalised "
            "traceability column Ruling 1 merely PERMITS was not taken",
            "event_id" not in entry_cols, str(sorted(entry_cols)))
    _assert("F5 ledger_entries carries NO unique constraint of any kind",
            entry_uniques == set(), str(entry_uniques))
    _assert("F5 no ledger_entries index is unique — batch_id included",
            not any(i.get("unique") for i in entry_indexes.values()),
            str({k: v.get("unique") for k, v in entry_indexes.items()}))
    _assert("F5 batch_id is NULLABLE — legacy postings stay unlinked",
            next(c for c in insp.get_columns("ledger_entries")
                 if c["name"] == "batch_id")["nullable"] is True)
    _assert("F5 many entries legitimately share one batch_id, which a "
            "uniqueness rule would forbid",
            len(_entries_for(posting_ids[0])) == 2)

    # ══════════════════════════════════════════════════════════════════════
    # F6 / F7 / F8 / F9 — ChallengeFundingLeg provenance shape
    # ══════════════════════════════════════════════════════════════════════
    print("\nF6-F9  ChallengeFundingLeg is the §5 ordered provenance shape")
    tdb.reset()
    lg_id, team_a = _mk_league_team()
    _, team_b = _mk_league_team()
    ch_id = _mk_challenge(lg_id, team_a, team_b)
    ev_pk = _mk_event("challenge_issue", challenge_id=ch_id)

    insp = inspect(engine)
    leg_cols = {c["name"] for c in insp.get_columns("challenge_funding_legs")}
    REQUIRED = {"id", "challenge_id", "team_id", "sequence_number",
                "source_account", "destination_account", "amount_cents",
                "leg_kind", "reverses_funding_leg_id", "posting_id",
                "posting_batch_id", "protocol_event_id", "created_at"}
    _assert("F6 every required §5 provenance field is present",
            REQUIRED <= leg_cols, str(sorted(REQUIRED - leg_cols)))

    def _leg(seq: int, kind: str, cents: int, reverses=None, src="wallet:1",
             dst="escrow:challenge:1"):
        with SessionLocal() as db:
            leg = ChallengeFundingLeg(
                challenge_id=ch_id, team_id=team_a, sequence_number=seq,
                source_account=src, destination_account=dst,
                amount_cents=cents, leg_kind=kind,
                reverses_funding_leg_id=reverses,
                posting_id=uuid.uuid4(), protocol_event_id=ev_pk)
            db.add(leg); db.commit(); return leg.id

    leg1 = _leg(1, "fund", 600, src="min:1:1")
    leg2 = _leg(2, "fund", 400, src="wallet:1")
    _assert("F6 ordered fund legs are insertable", leg1 and leg2)

    # F7 — ordering uniqueness within the challenge.
    dup = None
    try:
        _leg(2, "fund", 100)
    except Exception as exc:                      # noqa: BLE001 — recording
        dup = exc
    _assert("F7 a duplicate sequence_number within one challenge is refused",
            isinstance(dup, IntegrityError), f"got {type(dup).__name__}")
    _assert("F7 the violated constraint is the sequence uniqueness",
            dup is not None and "uq_challenge_funding_leg_sequence" in str(dup),
            str(dup)[:100])

    # F8 — the reversal linkage biconditional, both halves.
    bad_fund = None
    try:
        _leg(3, "fund", 100, reverses=leg1)
    except Exception as exc:                      # noqa: BLE001 — recording
        bad_fund = exc
    _assert("F8 a FUND leg naming a reversal target is unrepresentable",
            isinstance(bad_fund, IntegrityError), f"got {type(bad_fund).__name__}")

    bad_rev = None
    try:
        _leg(4, "reverse", -100, reverses=None)
    except Exception as exc:                      # noqa: BLE001 — recording
        bad_rev = exc
    _assert("F8 a REVERSE leg without a reversal target is unrepresentable",
            isinstance(bad_rev, IntegrityError), f"got {type(bad_rev).__name__}")

    bad_sign = None
    try:
        _leg(5, "fund", -100)
    except Exception as exc:                      # noqa: BLE001 — recording
        bad_sign = exc
    _assert("F8 a NEGATIVE fund leg is unrepresentable — §5 fixes the sign "
            "contract", isinstance(bad_sign, IntegrityError),
            f"got {type(bad_sign).__name__}")

    bad_sign2 = None
    try:
        _leg(6, "reverse", 100, reverses=leg2)
    except Exception as exc:                      # noqa: BLE001 — recording
        bad_sign2 = exc
    _assert("F8 a POSITIVE reverse leg is unrepresentable",
            isinstance(bad_sign2, IntegrityError), f"got {type(bad_sign2).__name__}")

    bad_kind = None
    try:
        _leg(7, "adjust", 100)
    except Exception as exc:                      # noqa: BLE001 — recording
        bad_kind = exc
    _assert("F8 an unknown leg_kind is unrepresentable",
            isinstance(bad_kind, IntegrityError), f"got {type(bad_kind).__name__}")

    # A lawful reverse leg, linked to the exact fund leg it draws from.
    rev = _leg(3, "reverse", -400, reverses=leg2)
    _assert("F8 a lawful reverse leg linked to its fund leg IS accepted",
            rev is not None)
    with SessionLocal() as db:
        legs = (db.query(ChallengeFundingLeg)
                .filter(ChallengeFundingLeg.challenge_id == ch_id)
                .order_by(ChallengeFundingLeg.sequence_number).all())
        by_id = {l.id: l for l in legs}
        drawn = sum(abs(l.amount_cents) for l in legs
                    if l.reverses_funding_leg_id == leg2)
    _assert("F8 remaining_reversible_cents is DERIVABLE from the rows, exactly "
            "as §5 requires — and is not stored",
            by_id[leg2].amount_cents - drawn == 0
            and "remaining_reversible_cents" not in leg_cols,
            f"leg2={by_id[leg2].amount_cents} drawn={drawn}")

    # F9 — cents are integers, everywhere.
    cents_cols = [c for c in insp.get_columns("challenge_funding_legs")
                  if c["name"].endswith("_cents")]
    _assert("F9 every *_cents column on the funding leg is an INTEGER type",
            cents_cols and all("INT" in str(c["type"]).upper() for c in cents_cols),
            str([(c["name"], str(c["type"])) for c in cents_cols]))
    ledger_amount = next(c for c in insp.get_columns("ledger_entries")
                         if c["name"] == "amount_cents")
    _assert("F9 LedgerEntry.amount_cents remains an integer type",
            "INT" in str(ledger_amount["type"]).upper(),
            str(ledger_amount["type"]))
    _assert("F9 no float/numeric money column was introduced on the new tables",
            not any("FLOAT" in str(c["type"]).upper()
                    or "NUMERIC" in str(c["type"]).upper()
                    or "DOUBLE" in str(c["type"]).upper()
                    for c in insp.get_columns("challenge_funding_legs")))

    # ══════════════════════════════════════════════════════════════════════
    # F10 / F16 — legacy post() is unchanged
    # ══════════════════════════════════════════════════════════════════════
    print("\nF10/F16  legacy post() behaviour is untouched")
    tdb.reset()
    with SessionLocal() as db:
        legacy_pid = ledger_post([("world", -1000), ("wallet:7", 1000)],
                                 door="buy_in_paid", session=db)
        db.commit()
    legacy_legs = _entries_for(legacy_pid)
    _assert("F10 a session-path posting with no event still writes its entries",
            len(legacy_legs) == 2, str(len(legacy_legs)))
    _assert("F10 and leaves batch_id NULL on every one of them",
            all(l.batch_id is None for l in legacy_legs),
            str([l.batch_id for l in legacy_legs]))
    with SessionLocal() as db:
        n_batches = db.query(LedgerPostingBatch).count()
    _assert("F10 no batch row was created by an unlinked posting",
            n_batches == 0, str(n_batches))
    _assert("F10 balances and trial balance behave exactly as before",
            balance_of("wallet:7") == 1000 and trial_balance() == 0)

    # The session=None path — the original L2 behaviour, committed internally.
    own_pid = ledger_post([("world", -500), ("wallet:8", 500)], door="buy_in_paid")
    _assert("F10 the session=None path still commits on its own",
            balance_of("wallet:8") == 500, str(balance_of("wallet:8")))
    _assert("F10 and still leaves batch_id NULL",
            all(l.batch_id is None for l in _entries_for(own_pid)))

    # A protocol_event_id without a session is refused rather than silently
    # written into a separate transaction.
    no_sess = None
    try:
        ledger_post([("world", -100), ("wallet:9", 100)],
                    door="buy_in_paid", protocol_event_id=1)
    except Exception as exc:                      # noqa: BLE001 — recording
        no_sess = exc
    _assert("F10 protocol_event_id without a session is REFUSED",
            isinstance(no_sess, ValueError)
            and "requires an explicit session" in str(no_sess),
            f"got {type(no_sess).__name__}")

    # F16 — real production callers still execute unchanged.
    with SessionLocal() as db:
        from economy.season_allocation import activate_season_allocation
        lg2 = League(season=2025, name=_uniq("f16"), projection_source="fantasypros")
        db.add(lg2); db.flush()
        t1 = Team(league_id=lg2.id, team_name=_uniq("F16T"), owner="o",
                  email=f"{_uniq('f16e')}@gg.test")
        db.add(t1); db.commit()
        lg2_id = lg2.id
    with SessionLocal() as db:
        result = activate_season_allocation(lg2_id, db)
    _assert("F16 a real production caller (season allocation) still posts",
            result.created is True and len(result.posting_ids) == 1,
            str(result.created))
    with SessionLocal() as db:
        alloc_legs = (db.query(LedgerEntry)
                      .filter(LedgerEntry.posting_id == result.posting_ids[0]).all())
    _assert("F16 its posting is three legs, unlinked, summing to zero",
            len(alloc_legs) == 3 and sum(l.amount_cents for l in alloc_legs) == 0
            and all(l.batch_id is None for l in alloc_legs),
            str(len(alloc_legs)))
    _assert("F16 trial_balance() is still 0", trial_balance() == 0)

    # ══════════════════════════════════════════════════════════════════════
    # F13 / F14 — the funded guard
    # ══════════════════════════════════════════════════════════════════════
    print("\nF13/F14  the funded-account guard is untouched")
    tdb.reset()
    ev2 = _mk_event("challenge_issue")
    guarded = None
    try:
        with SessionLocal() as db:
            ledger_post([("wallet:42", -100), ("escrow:challenge:9", 100)],
                        door="challenge_issued", session=db,
                        protocol_event_id=ev2)
            db.commit()
    except Exception as exc:                      # noqa: BLE001 — recording
        guarded = exc
    _assert("F13 debiting an unfunded wallet is REFUSED even on the linked path",
            isinstance(guarded, InsufficientFundsError),
            f"got {type(guarded).__name__}")
    _assert("F13 nothing was written by the refused posting",
            trial_balance() == 0 and balance_of("escrow:challenge:9") == 0)

    imbalance = None
    try:
        with SessionLocal() as db:
            ledger_post([("world", -100), ("wallet:43", 99)],
                        door="challenge_issued", session=db,
                        protocol_event_id=ev2)
    except Exception as exc:                      # noqa: BLE001 — recording
        imbalance = exc
    _assert("F13 an unbalanced linked posting is REFUSED before any write",
            isinstance(imbalance, LedgerImbalanceError),
            f"got {type(imbalance).__name__}")

    # F14 is asserted BEHAVIOURALLY, not by scanning. The exemption prefixes are
    # string literals, which a tokenised code-only view strips by design — and a
    # raw-text grep cannot tell an exemption from a comment describing one. What
    # the guard actually DOES is the claim worth making, so each member and
    # non-member of the exemption set is exercised against a zero balance.
    def _debit_from_zero(account: str, door: str) -> Exception | None:
        try:
            with SessionLocal() as db:
                ledger_post([(account, -100), ("wallet:99", 100)],
                            door=door, session=db)
                db.rollback()          # never keep the effect; only the verdict
            return None
        except Exception as exc:                  # noqa: BLE001 — recording
            return exc

    _assert("F14 'world' is STILL exempt — unchanged",
            _debit_from_zero("world", "buy_in_paid") is None)
    _assert("F14 'receivable:*' is STILL exempt — unchanged",
            _debit_from_zero("receivable:7", "buy_in_tab") is None)
    _assert("F14 'bab_issuance:*' is STILL exempt under its own door only",
            _debit_from_zero("bab_issuance:1:2026", APPROVED_BAB_TOPOFF_DOOR) is None)
    _assert("F14 'bab_issuance:*' under ANY OTHER door is still guarded",
            isinstance(_debit_from_zero("bab_issuance:1:2026", "challenge_issued"),
                       InsufficientFundsError))
    _assert("F14 NO NEW EXEMPTION: 'escrow:challenge:*' is fully guarded",
            isinstance(_debit_from_zero("escrow:challenge:1", "challenge_refunded"),
                       InsufficientFundsError))
    _assert("F14 NO NEW EXEMPTION: 'min:*' is fully guarded",
            isinstance(_debit_from_zero("min:1:1", "challenge_issued"),
                       InsufficientFundsError))
    # The tuple names the two refusals this debit may legitimately produce and
    # nothing wider. Under the wager_settled door the once-only settlement guard
    # is checked BEFORE the funded-balance guard, so an escrow account already at
    # zero raises AlreadySettledError; under any other door the same debit would
    # raise InsufficientFundsError. Either proves the account is guarded — but
    # `Exception` would have proved only that something went wrong.
    _assert("F14 NO NEW EXEMPTION: 'escrow:{bet_id}' is fully guarded",
            isinstance(_debit_from_zero("escrow:101", "wager_settled"),
                       (InsufficientFundsError, AlreadySettledError)))

    # ══════════════════════════════════════════════════════════════════════
    # F18 — no Stripe / real-money concept
    # ══════════════════════════════════════════════════════════════════════
    print("\nF18  no Stripe or real-money concept was introduced")
    for rel in ("ledger/ledger.py",
                "db/migrations/migrate_spec2_challenge_escrow.py"):
        code = _code_only((REPO / rel).read_text(encoding="utf-8"))
        _assert(f"F18 {rel} contains no stripe symbol in executable code",
                re.search(r"stripe", code, re.I) is None)
    schema_new  = (REPO / "db" / "schema.py").read_text(encoding="utf-8")
    new_section = schema_new[schema_new.index("SPEC 2 · Package 2B Group 1"):]
    _assert("F18 the Group 1 schema section introduces no stripe concept",
            "stripe" not in new_section.lower(),
            "the section is stripe-free")
    _assert("F18 no payment/payout/card concept in the new tables",
            not any(re.search(r"payment|payout|card|charge", c["name"], re.I)
                    for tbl in ("protocol_events", "ledger_posting_batches",
                                "challenge_funding_legs")
                    for c in inspect(engine).get_columns(tbl)))


def _batch_count(session_factory, model) -> int:
    with session_factory() as db:
        return db.query(model).count()


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
