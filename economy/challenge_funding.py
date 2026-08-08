"""
economy/challenge_funding.py — P1-L4 / SPEC 2: challenge escrow and its complete
lifecycle.

WHAT THIS MODULE IS. The money half of the Locked challenge. Spec 1
(beefs/proposal_lifecycle.py) owns negotiation STATE and posts nothing; this owns
ESCROW, PROVENANCE and RECONCILIATION. Spec 1 §10 forbids committing one half
before the other, so this module is the integrated service: it calls Spec 1 for
the state transition, posts the money, writes the provenance, and issues THE
SINGLE COMMIT. Spec 1's transitions flush and never commit precisely so this can
be true.

    issue    → post real Anchor escrow to escrow:challenge:{id}
    counter  → capacity validation only, NO money (§10)
    accept   → true-up, migrate Anchor to Bet escrow, fund Derived, create Bets
    decline  → exact reverse-leg refund
    cancel   → exact reverse-leg refund
    expire   → fail-closed reconciliation, then exact reverse-leg refund

THE SOFT RESERVATION IS GONE FROM THIS PATH. `_challenge_reserved` is never
imported here and never consulted. Once issue posts real escrow, the wallet's
ledger balance ALREADY excludes the committed stake; subtracting a soft
reservation on top would double-count the same money (Foundation Correction Plan
§5 / Spec 2 §14). Availability on this path is real ledger balance and nothing
else.

FOUR PRIMITIVES THIS STANDS ON, ALL BUILT BEFORE IT:
  P1-L2   every balance change goes through the ledger
  P1-L3B  every funding gate reads integer ledger cents, never the float mirror
  P1-L6   ProtocolEvent is the single idempotency authority
  P1-L7   lock_funding_scopes() is the funding-scope mutex

LOCK ORDER, ALWAYS: challenge row FOR UPDATE first, then Wallet rows ascending
by team_id through lock_funding_scopes(). Spec 2 §8 fixes this rank and P1-L7
established it; a Wallet→Challenge path anywhere would create the inversion this
ordering exists to prevent.

MONEY IS INTEGER CENTS EVERYWHERE IN THIS FILE. No float authorizes, funds,
refunds, reconciles or compares. Floats appear only where a legacy compatibility
column must be written (Bet.amount), always derived from the authoritative cents.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import (
    BeefChallenge,
    BeefProposal,
    Bet,
    ChallengeFundingLeg,
    Matchup,
    ProtocolEvent,
    Wallet,
)
from ledger.ledger import (
    InsufficientFundsError,
    _balance_of_in_session,
    lock_funding_scopes,
    post as ledger_post,
)
from beefs import proposal_lifecycle as spec1
# Re-exported so callers have one name for the display read, while the read
# itself lives in a module that does NOT import the Spec 1 lifecycle — that
# import edge is what Package 2A's unreachability gate forbids. See
# economy/challenge_escrow_view.py.
from economy.challenge_escrow_view import team_open_challenge_escrow_cents

# Spec 1's challenge-row lock. A supported cross-module import, on the same
# footing as ledger._balance_of_in_session: the leading underscore marks it
# internal to Spec 1's own callers, and this module IS Spec 1's paired money
# half (§10). Re-locking a row this transaction already holds is a no-op, so the
# orchestrator taking it first and Spec 1's transition taking it again is safe
# and is what keeps "challenge before wallets" true from the very first
# statement.
from beefs.proposal_lifecycle import _lock_challenge


# ── Ledger doors ──────────────────────────────────────────────────────────────
#
# One door per economic act, so the ledger's audit trail distinguishes funding
# from refunding from migrating without anyone having to infer it from accounts.
DOOR_ISSUED   = "challenge_issued"       # §9 — Anchor escrow at issue
DOOR_TOPUP    = "challenge_topup"        # §12 — raise branch of the accept true-up
DOOR_RELEASED = "challenge_released"     # §12 — lower branch of the accept true-up
DOOR_REFUNDED = "challenge_refunded"     # §11 — decline / cancel / expire
DOOR_MIGRATED = "challenge_migrated"     # §12 — Anchor challenge escrow → Bet escrow
DOOR_DERIVED  = "challenge_derived_funded"   # §12 — recipient's Derived escrow

# Deterministic result codes recorded on the ProtocolEvent (§7).
RESULT_OK                    = "ok"
RESULT_RECONCILIATION_ERROR  = "reconciliation_error"
RESULT_INSUFFICIENT_CAPACITY = "insufficient_acceptance_capacity"


# ── Errors ────────────────────────────────────────────────────────────────────

class ChallengeFundingError(ValueError):
    """Base for every refusal this module raises. Subclasses are distinct TYPES
    so callers and tests branch on type, never on message text."""


class InsufficientFundingCapacityError(ChallengeFundingError):
    """The team cannot cover the required amount from min + wallet, read as
    authoritative ledger cents under the funding-scope lock. Nothing was posted."""


class EscrowReconciliationError(ChallengeFundingError):
    """§11's fail-closed guard: the actual escrow:challenge:{id} balance does not
    equal the amount the funding provenance says was funded.

    NOTHING IS REFUNDED AND NO TERMINAL STATE IS SET. A partial or missing escrow
    is not a smaller refund — it is an unexplained discrepancy, and refunding
    against it would either strand money or invent it. The challenge is left
    unresolved for recovery and a reconciliation_error event records why. "Balance
    > 0" is explicitly not sufficient."""


class AcceptanceCapacityError(ChallengeFundingError):
    """§12 — at acceptance, the issuer's required Anchor top-up or the recipient's
    full Derived stake could no longer be funded. Acceptance fails ATOMICALLY: no
    posting, no funding leg, no Bet row, no state transition. The challenge stays
    open in its existing state."""


class MissingProposalError(ChallengeFundingError):
    """The challenge has no active/accepted proposal, or the proposal carries no
    anchor_stake_cents. Spec 1 leaves the stake columns nullable because Spec 2
    funds them; an unfunded proposal cannot be escrowed."""


# ── Results ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FundingResult:
    """What one funded lifecycle call produced.

    `replayed` is True when the call found its event_id already committed and
    returned the original outcome rather than acting again (§7 idempotency).
    """
    challenge_id:      int
    event_id:          uuid.UUID
    protocol_event_id: int
    response_status:   str
    result_code:       str
    escrow_cents:      int
    replayed:          bool
    detail:            str = ""
    anchor_bet_id:     Optional[int] = None
    derived_bet_id:    Optional[int] = None


# ── Accounts ──────────────────────────────────────────────────────────────────

def challenge_escrow_account(challenge_id: int) -> str:
    """§3 — the pre-acceptance obligation account. One per challenge."""
    return f"escrow:challenge:{challenge_id}"


def wallet_account(team_id: int) -> str:
    return f"wallet:{team_id}"


def min_account(team_id: int, week: int) -> str:
    """§3 — the weekly-minimum source account. Spec 2 owns the CONSUMPTION
    contract; Spec 5 owns creation, funding, release and sweep. Until Spec 5
    ships this account has no writer, so it reads zero everywhere and funding
    falls entirely to wallet — which is a legitimate state, not a missing
    dependency (§3: "an absent min account reads as zero")."""
    return f"min:{team_id}:{week}"


# ── Authoritative reads ───────────────────────────────────────────────────────

def available_cents(db: Session, team_id: int, week: int) -> int:
    """Total spendable capacity for one team-week, in authoritative ledger cents.

    min + wallet, and NOTHING ELSE. Specifically NOT minus _challenge_reserved:
    an issued challenge's stake has already left wallet:{team} as a real escrow
    debit, so the balance read here already excludes it. Subtracting the old soft
    reservation as well would count the same commitment twice (§14).
    """
    db.flush()          # make this transaction's own postings visible to the SUM
    return (
        max(0, _balance_of_in_session(db, min_account(team_id, week)))
        + _balance_of_in_session(db, wallet_account(team_id))
    )


def challenge_escrow_balance(db: Session, challenge_id: int) -> int:
    """The ACTUAL ledger balance of this challenge's escrow account."""
    db.flush()
    return _balance_of_in_session(db, challenge_escrow_account(challenge_id))


def expected_challenge_escrow(db: Session, challenge_id: int) -> int:
    """The amount the PROVENANCE says is funded: the signed sum of every funding
    leg pointing at this challenge's escrow account (§11).

    `fund` legs are positive and `reverse` legs negative (schema CHECK), so a
    plain SUM is the net unreversed total. Legs whose destination is a Bet escrow
    — the Derived funding written at acceptance — are excluded by the destination
    filter, because they are not challenge escrow and never were.

    §11 IS EMPHATIC THAT THIS IS THE REFUND TARGET, NOT THE ACTIVE PROPOSAL'S
    ANCHOR. A counter changes the PROPOSED Anchor but moves no money, so a
    pre-acceptance refund owes what was actually funded. Issue 1000, counter to
    800, expire → refund 1000. Reconciling against 800 would strand 200 of real
    money.
    """
    account = challenge_escrow_account(challenge_id)
    legs = (
        db.query(ChallengeFundingLeg)
        .filter(ChallengeFundingLeg.challenge_id == challenge_id,
                ChallengeFundingLeg.destination_account == account)
        .all()
    )
    return sum(leg.amount_cents for leg in legs)


def _next_sequence(db: Session, challenge_id: int) -> int:
    """The next monotonic position in this challenge's funding history (§5).
    UNIQUE(challenge_id, sequence_number) is the structural backstop; this is
    allocated under the challenge row lock every caller already holds."""
    existing = (
        db.query(ChallengeFundingLeg.sequence_number)
        .filter(ChallengeFundingLeg.challenge_id == challenge_id)
        .all()
    )
    return (max((s[0] for s in existing), default=0)) + 1


# ── Event identity (P1-L6) ────────────────────────────────────────────────────

def _find_event(db: Session, event_id: uuid.UUID) -> Optional[ProtocolEvent]:
    return (
        db.query(ProtocolEvent)
        .filter(ProtocolEvent.event_id == event_id)
        .first()
    )


def _open_event(
    db: Session,
    *,
    event_id: uuid.UUID,
    event_type: str,
    challenge: BeefChallenge,
    actor_identity: str,
    proposal_id: Optional[int] = None,
    prior_state: Optional[str] = None,
) -> ProtocolEvent:
    """Create this operation's governing ProtocolEvent and flush for its id.

    THE EVENT IS CREATED BEFORE THE MONEY, not after, because ledger.post() takes
    protocol_event_id and the batch's FK needs a persisted row. Flush is not
    commit — if anything below fails, the event rolls back with the postings it
    governs, so a failed operation leaves no orphan claiming to have happened.
    """
    event = ProtocolEvent(
        event_id       = event_id,
        event_type     = event_type,
        challenge_id   = challenge.id,
        proposal_id    = proposal_id,
        actor_identity = actor_identity,
        league_id      = challenge.league_id,
        week           = challenge.week,
        effective_at   = datetime.now(timezone.utc),
        prior_state    = prior_state,
        spec_version   = "SPEC-2-v2",
    )
    db.add(event)
    db.flush()
    return event


def _already_closed(db: Session, challenge: BeefChallenge,
                    event_id: uuid.UUID) -> Optional[FundingResult]:
    """§9's "first valid commit governs", checked BEFORE any reconciliation.

    WHY THIS RUNS AHEAD OF THE ESCROW RECONCILIATION. The provenance invariant
    `balance == SUM(unreversed legs)` is a PRE-ACCEPTANCE invariant, and it is
    deliberately not maintained past acceptance: acceptance migrates the Anchor
    out of escrow:challenge into escrow:{anchor_bet_id} as a plain balanced
    posting, not as a `reverse` leg, because a reverse leg means "returned to the
    original source" and this money did not go back to anyone's wallet — it moved
    on to the Bet. So an accepted challenge legitimately shows escrow 0 against
    fund legs of 1000, and a reconciliation check run against it would read that
    healthy end-state as a discrepancy and raise.

    A second caller on a closed challenge must therefore be answered from its
    state, not from its escrow arithmetic: "already accepted", "already
    declined". That is both what §9 specifies and what stops a correct, fully
    settled challenge from reporting a reconciliation_error forever after.
    """
    if challenge.response_status not in spec1.OPEN_STATES:
        return FundingResult(
            challenge_id      = challenge.id,
            event_id          = event_id,
            protocol_event_id = 0,
            response_status   = challenge.response_status,
            result_code       = RESULT_OK,
            escrow_cents      = challenge_escrow_balance(db, challenge.id),
            replayed          = True,
            detail            = f"already {challenge.response_status}",
        )
    return None


def _replayed(db: Session, event: ProtocolEvent) -> FundingResult:
    """§7 — a repeated delivery returns the ORIGINAL committed result and posts
    nothing new. The challenge is re-read so the caller sees the state the first
    delivery produced, not the state it would have produced now."""
    challenge = db.query(BeefChallenge).filter(
        BeefChallenge.id == event.challenge_id).first()
    return FundingResult(
        challenge_id      = event.challenge_id,
        event_id          = event.event_id,
        protocol_event_id = event.id,
        response_status   = challenge.response_status if challenge else "",
        result_code       = event.result_code or RESULT_OK,
        escrow_cents      = challenge_escrow_balance(db, event.challenge_id),
        replayed          = True,
        detail            = f"replayed {event.event_type}",
    )


# ── §4 Source-aware funding ───────────────────────────────────────────────────

def plan_source_split(db: Session, team_id: int, week: int,
                      required_cents: int) -> list[tuple[str, int]]:
    """§4 — split `required_cents` across this team's sources, MIN FIRST then
    wallet, and return the legs IN THE ORDER THEY WILL BE FUNDED.

        1. min_available = balance(min:{team}:{week})   (zero if absent)
        2. min_leg    = min(min_available, required)
        3. wallet_leg = required − min_leg

    Both legs are optional: min-only, wallet-only and mixed are all valid shapes,
    and a zero-amount leg is never recorded (the schema CHECK forbids it, and a
    leg that moved nothing is not history). The single escrow credit always
    equals the total, so the posting sums to zero by construction.

    ORDER IS THE PRODUCT, not just the amounts. §11 refunds by replaying this
    sequence backwards, so "min first" is recorded as position, not inferred
    later from which account happens to hold what.
    """
    if required_cents <= 0:
        return []
    min_available = max(0, _balance_of_in_session(db, min_account(team_id, week)))
    min_leg    = min(min_available, required_cents)
    wallet_leg = required_cents - min_leg

    legs: list[tuple[str, int]] = []
    if min_leg > 0:
        legs.append((min_account(team_id, week), min_leg))
    if wallet_leg > 0:
        legs.append((wallet_account(team_id), wallet_leg))
    return legs


def _fund(
    db: Session,
    *,
    challenge: BeefChallenge,
    team_id: int,
    required_cents: int,
    destination: str,
    event: ProtocolEvent,
    door: str,
) -> list[ChallengeFundingLeg]:
    """Post one balanced funding batch and record its ordered provenance.

    One ledger posting (all source debits + the single destination credit, summing
    to zero) and one ChallengeFundingLeg per source leg, in min-then-wallet order.
    The legs carry the posting_id and batch so the provenance and the ledger are
    the same event, not two stories about it.
    """
    if required_cents <= 0:
        return []

    splits = plan_source_split(db, team_id, challenge.week, required_cents)
    funded = sum(amount for _, amount in splits)
    if funded != required_cents:
        # Capacity was checked by the caller under the lock; reaching here means
        # the sources cannot cover it. Refuse rather than post a short escrow.
        raise InsufficientFundingCapacityError(
            f"Team {team_id} can fund only {funded} of {required_cents} cents "
            f"for {destination!r}. Nothing posted."
        )

    entries = [(account, -amount) for account, amount in splits]
    entries.append((destination, required_cents))
    posting_id = ledger_post(entries, door=door, session=db,
                             protocol_event_id=event.id)

    batch_id = _batch_id_for(db, posting_id)
    sequence = _next_sequence(db, challenge.id)
    legs: list[ChallengeFundingLeg] = []
    for account, amount in splits:
        leg = ChallengeFundingLeg(
            challenge_id        = challenge.id,
            team_id             = team_id,
            sequence_number     = sequence,
            source_account      = account,
            destination_account = destination,
            amount_cents        = amount,          # positive — a fund leg
            leg_kind            = "fund",
            posting_id          = posting_id,
            posting_batch_id    = batch_id,
            protocol_event_id   = event.id,
        )
        db.add(leg)
        legs.append(leg)
        sequence += 1
    db.flush()
    return legs


def _batch_id_for(db: Session, posting_id: uuid.UUID) -> Optional[int]:
    from db.schema import LedgerPostingBatch
    batch = (
        db.query(LedgerPostingBatch)
        .filter(LedgerPostingBatch.posting_id == posting_id)
        .first()
    )
    return batch.id if batch else None


# ── §11 Strict reverse-order reversal ─────────────────────────────────────────

def _remaining_reversible(db: Session, leg: ChallengeFundingLeg) -> int:
    """§5's derived quantity — never stored, because the rows already determine
    it and a stored copy would be a second divergeable truth.

        remaining = fund_leg.amount_cents − Σ|reverse legs pointing at it|
    """
    reversals = (
        db.query(ChallengeFundingLeg)
        .filter(ChallengeFundingLeg.reverses_funding_leg_id == leg.id)
        .all()
    )
    return leg.amount_cents - sum(abs(r.amount_cents) for r in reversals)


def _reverse(
    db: Session,
    *,
    challenge: BeefChallenge,
    amount_cents: int,
    event: ProtocolEvent,
    door: str,
) -> list[ChallengeFundingLeg]:
    """§11 — return `amount_cents` from challenge escrow to its ORIGINAL sources
    by replaying the funding legs backwards.

    STRICT REVERSE SEQUENCE ORDER, NEVER PROPORTIONAL. Legs are consumed in
    descending sequence_number, each for at most its remaining_reversible_cents,
    and every reverse row names the exact fund row it draws from. Proportional
    division would invent rounding questions and describe movements that never
    happened; replaying history backwards reproduces the actual mix. On an
    unequal split the two answers differ, which is exactly why §11 rules it out.

    Only `fund` legs are candidates. A `reverse` row is not itself refundable —
    treating one as a funding source would refund the same money twice.
    """
    if amount_cents <= 0:
        return []

    account = challenge_escrow_account(challenge.id)
    fund_legs = (
        db.query(ChallengeFundingLeg)
        .filter(ChallengeFundingLeg.challenge_id == challenge.id,
                ChallengeFundingLeg.destination_account == account,
                ChallengeFundingLeg.leg_kind == "fund")
        .order_by(ChallengeFundingLeg.sequence_number.desc())
        .all()
    )

    outstanding = amount_cents
    plan: list[tuple[ChallengeFundingLeg, int]] = []
    for leg in fund_legs:
        if outstanding <= 0:
            break
        take = min(_remaining_reversible(db, leg), outstanding)
        if take <= 0:
            continue
        plan.append((leg, take))
        outstanding -= take

    if outstanding != 0:
        # The provenance cannot account for the amount being reversed. Fail
        # closed rather than refund an amount no recorded leg supports.
        raise EscrowReconciliationError(
            f"Challenge {challenge.id}: cannot reverse {amount_cents} cents — the "
            f"recorded funding legs account for only {amount_cents - outstanding}. "
            f"Nothing posted."
        )

    entries: list[tuple[str, int]] = [(account, -amount_cents)]
    for leg, take in plan:
        entries.append((leg.source_account, take))
    posting_id = ledger_post(entries, door=door, session=db,
                             protocol_event_id=event.id)

    batch_id = _batch_id_for(db, posting_id)
    sequence = _next_sequence(db, challenge.id)
    written: list[ChallengeFundingLeg] = []
    for leg, take in plan:
        row = ChallengeFundingLeg(
            challenge_id        = challenge.id,
            team_id             = leg.team_id,
            sequence_number     = sequence,
            source_account      = leg.source_account,
            destination_account = account,
            amount_cents        = -take,          # negative — a reverse leg
            leg_kind            = "reverse",
            reverses_funding_leg_id = leg.id,
            posting_id          = posting_id,
            posting_batch_id    = batch_id,
            protocol_event_id   = event.id,
        )
        db.add(row)
        written.append(row)
        sequence += 1
    db.flush()
    return written


# ── Proposal helpers ──────────────────────────────────────────────────────────

def _active_proposal(db: Session, challenge: BeefChallenge) -> BeefProposal:
    if challenge.active_proposal_id is None:
        raise MissingProposalError(
            f"Challenge {challenge.id} has no active proposal.")
    proposal = (
        db.query(BeefProposal)
        .filter(BeefProposal.id == challenge.active_proposal_id)
        .first()
    )
    if proposal is None:
        raise MissingProposalError(
            f"Challenge {challenge.id}'s active proposal "
            f"{challenge.active_proposal_id} does not exist.")
    return proposal


def _anchor_cents(proposal: BeefProposal) -> int:
    if proposal.anchor_stake_cents is None:
        raise MissingProposalError(
            f"Proposal {proposal.id} carries no anchor_stake_cents; there is "
            f"nothing to escrow.")
    return int(proposal.anchor_stake_cents)


def anchor_team_id(challenge: BeefChallenge, proposal: BeefProposal) -> int:
    """A4 / §12 — the Anchor is the ORIGINAL ISSUER, always.

    Proposal AUTHORSHIP never moves the Anchor role. A recipient-authored counter
    that raises the stake raises the ISSUER's obligation; the top-up debits the
    issuer's sources, never the countering recipient's. Spec 1 already stamps
    anchor_team_id on every proposal version as the challenger; this reads that
    stamp and falls back to the challenge's challenger, so the two can never
    disagree about who owes the Anchor.
    """
    return proposal.anchor_team_id or challenge.challenger_team_id


def derived_team_id(challenge: BeefChallenge, proposal: BeefProposal) -> int:
    return proposal.derived_team_id or challenge.challenged_team_id


# ── §9 Issue ──────────────────────────────────────────────────────────────────

def issue_funded_challenge(
    *,
    event_id: uuid.UUID,
    league_id: int,
    week: int,
    challenger_team_id: int,
    challenged_team_id: int,
    wager_type: str,
    terms: spec1.ProposalTerms,
    db: Session,
    challenge_mode: str = spec1.MODE_LOCKED,
    proposal_lock_at: Optional[datetime] = None,
    schedule_source_ref: Optional[str] = None,
    now: Optional[datetime] = None,
) -> FundingResult:
    """§9 — create the challenge and post the issuer's real Anchor escrow.

    SEQUENCE (§8 Issue), one transaction, one commit:
      1. Lock the issuer's Wallet funding scope (P1-L7). No challenge row exists
         yet to lock ahead of it, so this is the first lock and the rank holds.
      2. Re-read authoritative capacity UNDER the lock.
      3. Create the challenge + version-1 proposal + both-sides starters (Spec 1),
         flushing for the challenge id — escrow:challenge:{id} cannot be spelled
         before the id exists, and flush is not commit.
      4. Post the Anchor min-first-then-wallet; write ordered provenance legs.
      5. Commit once.

    The capacity check at step 2 is what makes step 4 safe; the lock at step 1 is
    what makes step 2 meaningful. Without the lock two concurrent issues read the
    same balance and both pass.
    """
    existing = _find_event(db, event_id)
    if existing is not None:
        return _replayed(db, existing)

    anchor_cents = terms.anchor_stake_cents
    if anchor_cents is None or anchor_cents <= 0:
        raise MissingProposalError(
            "terms.anchor_stake_cents must be a positive integer number of cents.")

    # 1 — funding-scope mutex, before any balance read.
    lock_funding_scopes(db, challenger_team_id)

    # 2 — authoritative capacity under the lock. Real ledger cents only.
    capacity = available_cents(db, challenger_team_id, week)
    if capacity < anchor_cents:
        raise InsufficientFundingCapacityError(
            f"Team {challenger_team_id} cannot fund a {anchor_cents}-cent Anchor: "
            f"{capacity} cents available (min + wallet). Nothing was created or "
            f"posted."
        )

    # 3 — Spec 1 creates the negotiation state and flushes. It does not commit.
    transition = spec1.issue_proposal_challenge(
        league_id           = league_id,
        week                = week,
        challenger_team_id  = challenger_team_id,
        challenged_team_id  = challenged_team_id,
        challenge_mode      = challenge_mode,
        wager_type          = wager_type,
        terms               = terms,
        db                  = db,
        proposal_lock_at    = proposal_lock_at,
        schedule_source_ref = schedule_source_ref,
        now                 = now,
    )
    challenge = db.query(BeefChallenge).filter(
        BeefChallenge.id == transition.challenge_id).one()

    event = _open_event(
        db,
        event_id       = event_id,
        event_type     = "challenge_issue",
        challenge      = challenge,
        actor_identity = str(challenger_team_id),
        proposal_id    = transition.active_proposal_id,
        prior_state    = None,
    )

    # 4 — real money into the challenge's own escrow account.
    _fund(db, challenge=challenge, team_id=challenger_team_id,
          required_cents=anchor_cents,
          destination=challenge_escrow_account(challenge.id),
          event=event, door=DOOR_ISSUED)

    event.resulting_state = spec1.OFFERED
    event.result_code     = RESULT_OK
    db.flush()
    db.commit()

    return FundingResult(
        challenge_id      = challenge.id,
        event_id          = event_id,
        protocol_event_id = event.id,
        response_status   = spec1.OFFERED,
        result_code       = RESULT_OK,
        escrow_cents      = anchor_cents,
        replayed          = False,
        detail            = "issued with escrow",
    )


# ── §10 Counter — validation only, no money ───────────────────────────────────

def counter_funded_challenge(
    *,
    event_id: uuid.UUID,
    challenge_id: int,
    actor_team_id: int,
    terms: spec1.ProposalTerms,
    db: Session,
    proposal_lock_at: Optional[datetime] = None,
    schedule_source_ref: Optional[str] = None,
    now: Optional[datetime] = None,
) -> FundingResult:
    """§10 — validate capacity for the proposed counter. NO MONEY MOVES.

    Two capacities are checked, and they are asymmetric because the two sides are
    in different positions:

      ISSUER  — already holds the original Anchor in challenge escrow, so only the
                DEFICIENCY is validated:
                    required_top_up = max(0, proposed_anchor − escrow_balance)
                A raise from 1000 to 1200 validates 200, not 1200.
      RECIPIENT — has nothing escrowed yet, so the FULL quoted Derived stake is
                validated.

    NEITHER IS RESERVED. Spec 2 §12 is explicit that counter-time validation does
    not reserve BAB; acceptance re-reads and revalidates both under lock and fails
    atomically on drift. That is the whole answer to the old soft-reservation
    model's counter-side gap: there is no counter-side commitment to track,
    because a counter commits nothing. `_challenge_reserved` never counted it
    either — the difference is that this is now the DESIGNED behaviour with
    acceptance revalidation as the control, rather than an unnoticed hole with
    nothing behind it.
    """
    existing = _find_event(db, event_id)
    if existing is not None:
        return _replayed(db, existing)

    # Lock order: challenge first, then wallets ascending.
    challenge = _lock_challenge(db, challenge_id)
    prior     = challenge.response_status
    issuer    = challenge.challenger_team_id
    recipient = challenge.challenged_team_id
    lock_funding_scopes(db, issuer, recipient)

    proposed_anchor = terms.anchor_stake_cents or 0
    derived_needed  = terms.quoted_derived_stake_cents or 0

    escrowed        = challenge_escrow_balance(db, challenge_id)
    required_top_up = max(0, proposed_anchor - escrowed)

    if required_top_up > 0:
        issuer_capacity = available_cents(db, issuer, challenge.week)
        if issuer_capacity < required_top_up:
            raise InsufficientFundingCapacityError(
                f"Issuer team {issuer} cannot cover the {required_top_up}-cent "
                f"top-up this counter would require ({issuer_capacity} available). "
                f"No proposal was created."
            )
    if derived_needed > 0:
        recipient_capacity = available_cents(db, recipient, challenge.week)
        if recipient_capacity < derived_needed:
            raise InsufficientFundingCapacityError(
                f"Countering team {recipient} cannot cover the {derived_needed}-cent "
                f"Derived stake it is proposing ({recipient_capacity} available). "
                f"No proposal was created."
            )

    transition = spec1.counter_challenge_proposal(
        challenge_id        = challenge_id,
        actor_team_id       = actor_team_id,
        terms               = terms,
        db                  = db,
        proposal_lock_at    = proposal_lock_at,
        schedule_source_ref = schedule_source_ref,
        now                 = now,
    )
    if not transition.changed:
        db.rollback()
        return FundingResult(
            challenge_id      = challenge_id,
            event_id          = event_id,
            protocol_event_id = 0,
            response_status   = transition.response_status,
            result_code       = RESULT_OK,
            escrow_cents      = escrowed,
            replayed          = True,
            detail            = transition.detail,
        )

    event = _open_event(
        db,
        event_id       = event_id,
        event_type     = "challenge_counter",
        challenge      = challenge,
        actor_identity = str(actor_team_id),
        proposal_id    = transition.active_proposal_id,
        prior_state    = prior,
    )
    event.resulting_state = spec1.COUNTERED
    event.result_code     = RESULT_OK
    db.flush()
    db.commit()

    return FundingResult(
        challenge_id      = challenge_id,
        event_id          = event_id,
        protocol_event_id = event.id,
        response_status   = spec1.COUNTERED,
        result_code       = RESULT_OK,
        escrow_cents      = escrowed,      # unchanged — a counter moves no money
        replayed          = False,
        detail            = "countered (validation only, no posting)",
    )


# ── §11 Terminal refunds ──────────────────────────────────────────────────────

def _terminal_refund(
    db: Session,
    *,
    event_id: uuid.UUID,
    challenge_id: int,
    actor_team_id: Optional[int],
    event_type: str,
    spec1_call,
    db_now: Optional[datetime],
) -> FundingResult:
    """The shared decline / cancel / expire body (§11).

    All three are the same accounting act — return the exact recorded funding to
    its exact recorded sources — so they share one implementation and differ only
    in who may trigger them and which terminal state results.

    FAIL-CLOSED RECONCILIATION APPLIES TO ALL THREE, not to expiry alone. §11:
    "decline or cancel could otherwise silently terminalize a challenge with
    stranded or missing escrow, which is the same money-correctness bug as a
    silent expiry." So the actual/expected comparison runs before any of them.
    """
    existing = _find_event(db, event_id)
    if existing is not None:
        return _replayed(db, existing)

    # 1 — challenge row first, then the issuer's wallet scope.
    challenge = _lock_challenge(db, challenge_id)
    closed = _already_closed(db, challenge, event_id)
    if closed is not None:
        db.rollback()
        return closed
    prior     = challenge.response_status
    proposal  = _active_proposal(db, challenge)
    anchor    = anchor_team_id(challenge, proposal)
    lock_funding_scopes(db, anchor)

    # 2/3 — reconcile BEFORE any state change or posting.
    actual   = challenge_escrow_balance(db, challenge_id)
    expected = expected_challenge_escrow(db, challenge_id)

    if actual != expected:
        # Fail closed. Record WHY, set no terminal state, refund nothing, and
        # leave the challenge open for recovery. A partial balance is invalid —
        # "> 0" is not sufficient.
        event = _open_event(
            db,
            event_id       = event_id,
            event_type     = event_type,
            challenge      = challenge,
            actor_identity = str(actor_team_id) if actor_team_id else "system",
            proposal_id    = proposal.id,
            prior_state    = prior,
        )
        event.resulting_state = prior              # unchanged, deliberately
        event.result_code     = RESULT_RECONCILIATION_ERROR
        db.flush()
        db.commit()                                # the audit record must survive
        raise EscrowReconciliationError(
            f"Challenge {challenge_id}: escrow:challenge:{challenge_id} holds "
            f"{actual} cents but the funding provenance says {expected}. Refusing "
            f"to refund or terminalize. A reconciliation_error event was recorded "
            f"and the challenge is left unresolved for recovery."
        )

    # 4 — the Spec 1 transition. Runs before the postings so an unauthorized or
    # already-closed request costs nothing; it flushes and does not commit.
    transition = spec1_call()
    if not transition.changed:
        db.rollback()
        return FundingResult(
            challenge_id      = challenge_id,
            event_id          = event_id,
            protocol_event_id = 0,
            response_status   = transition.response_status,
            result_code       = RESULT_OK,
            escrow_cents      = actual,
            replayed          = True,
            detail            = transition.detail,
        )

    event = _open_event(
        db,
        event_id       = event_id,
        event_type     = event_type,
        challenge      = challenge,
        actor_identity = str(actor_team_id) if actor_team_id else "system",
        proposal_id    = proposal.id,
        prior_state    = prior,
    )

    # 5 — exact reverse-leg refund of everything still funded.
    _reverse(db, challenge=challenge, amount_cents=actual,
             event=event, door=DOOR_REFUNDED)

    event.resulting_state = transition.response_status
    event.result_code     = RESULT_OK
    db.flush()
    db.commit()

    return FundingResult(
        challenge_id      = challenge_id,
        event_id          = event_id,
        protocol_event_id = event.id,
        response_status   = transition.response_status,
        result_code       = RESULT_OK,
        escrow_cents      = 0,
        replayed          = False,
        detail            = f"{transition.response_status} with exact refund",
    )


def decline_funded_challenge(*, event_id: uuid.UUID, challenge_id: int,
                             actor_team_id: int, db: Session,
                             now: Optional[datetime] = None) -> FundingResult:
    """§11 — decline, refunding the exact recorded funding to its exact sources."""
    return _terminal_refund(
        db, event_id=event_id, challenge_id=challenge_id,
        actor_team_id=actor_team_id, event_type="challenge_decline",
        spec1_call=lambda: spec1.decline_challenge(
            challenge_id=challenge_id, actor_team_id=actor_team_id, db=db, now=now),
        db_now=now,
    )


def cancel_funded_challenge(*, event_id: uuid.UUID, challenge_id: int,
                            actor_team_id: int, db: Session,
                            now: Optional[datetime] = None) -> FundingResult:
    """§11 — issuer withdrawal. Same accounting rule as decline."""
    return _terminal_refund(
        db, event_id=event_id, challenge_id=challenge_id,
        actor_team_id=actor_team_id, event_type="challenge_cancel",
        spec1_call=lambda: spec1.cancel_challenge(
            challenge_id=challenge_id, actor_team_id=actor_team_id, db=db, now=now),
        db_now=now,
    )


def expire_funded_challenge(*, event_id: uuid.UUID, challenge_id: int,
                            db: Session,
                            now: Optional[datetime] = None) -> FundingResult:
    """§11 / A6 — the dedicated fail-closed expiry transaction.

    System-owned: no actor, because expiry is not something a team does. The
    fail-closed reconciliation is shared with decline and cancel (see
    _terminal_refund) rather than being expiry-specific, which is what §11
    requires."""
    return _terminal_refund(
        db, event_id=event_id, challenge_id=challenge_id,
        actor_team_id=None, event_type="challenge_expire",
        spec1_call=lambda: spec1.expire_challenge(
            challenge_id=challenge_id, db=db, now=now),
        db_now=now,
    )


# ── §12 Atomic Locked acceptance ──────────────────────────────────────────────

def _find_matchup(db: Session, team_id: int, week: int) -> Matchup:
    matchup = (
        db.query(Matchup)
        .filter(Matchup.week == week,
                ((Matchup.home_team_id == team_id) | (Matchup.away_team_id == team_id)))
        .first()
    )
    if matchup is None:
        raise ChallengeFundingError(
            f"Team {team_id} has no matchup in week {week}; the wager could never "
            f"settle, so no Bet may be created for it.")
    return matchup


def _create_bet(db: Session, *, challenge: BeefChallenge, team_id: int,
                stake_cents: int, odds: Optional[float]) -> Bet:
    """One side's Bet row. Bet.amount is the LEGACY FLOAT MIRROR, written from
    the authoritative cents (§6) and never the other way round."""
    wallet = db.query(Wallet).filter(Wallet.team_id == team_id).one()
    matchup = _find_matchup(db, team_id, challenge.week)
    bet = Bet(
        matchup_id        = matchup.id,
        wallet_id         = wallet.id,
        picked_team_id    = team_id,
        bet_type          = challenge.wager_type or challenge.bet_type,
        line              = challenge.line,
        side              = challenge.side,
        description       = f"Beef challenge {challenge.id}",
        amount            = stake_cents / 100.0,
        odds              = odds or 1.909,
        status            = "pending",
        placed_at         = datetime.now(timezone.utc),
        beef_challenge_id = challenge.id,
    )
    db.add(bet)
    db.flush()                 # escrow:{bet.id} cannot be spelled before the id
    return bet


def accept_funded_challenge(
    *,
    event_id: uuid.UUID,
    challenge_id: int,
    actor_team_id: int,
    db: Session,
    now: Optional[datetime] = None,
) -> FundingResult:
    """§12 (A8) — the atomic Locked acceptance. ONE transaction, ONE commit.

    ORDER, and every step's reason:
      1. Lock the challenge row, then BOTH Wallet scopes ascending (§8).
      2. Read the accepted proposal; the Anchor team is the ORIGINAL ISSUER (A4),
         never the proposal's author.
      3. Reconcile actual challenge escrow against the funding provenance —
         fail closed on a mismatch, exactly as the terminals do.
      4. REVALIDATE BOTH CAPACITIES BEFORE ANY WRITE (OPR-8). Counter-time
         validation reserved nothing, so either party may have spent since. If
         either cannot be funded now, nothing is written at all.
      5. Lower branch: RELEASE the excess FIRST, then migrate (OPR-3 — migrating
         first would read a stale escrow balance).
         Raise branch: TOP UP the issuer's sources min-first.
      6. Create both Bet rows.
      7. Migrate the reconciled Anchor escrow into the Anchor Bet's escrow.
      8. Fund the recipient's Derived stake into the Derived Bet's escrow.
      9. Spec 1's accept transition.
     10. Commit once.

    Steps 5-9 all write; step 4 is the last point at which nothing has happened.
    That ordering is the no-write-before-revalidation obligation, stated as code
    rather than as a comment on top of an interleaved implementation.
    """
    existing = _find_event(db, event_id)
    if existing is not None:
        return _replayed(db, existing)

    # 1 — challenge first, then wallets ascending (never inverted).
    challenge = _lock_challenge(db, challenge_id)
    closed = _already_closed(db, challenge, event_id)
    if closed is not None:
        db.rollback()
        return closed
    prior     = challenge.response_status
    proposal  = _active_proposal(db, challenge)
    anchor    = anchor_team_id(challenge, proposal)
    derived   = derived_team_id(challenge, proposal)
    lock_funding_scopes(db, anchor, derived)

    # 2 — the accepted amounts, from the FROZEN proposal. No reprice (Locked).
    anchor_target  = _anchor_cents(proposal)
    derived_needed = int(proposal.quoted_derived_stake_cents or 0)

    # 3 — fail-closed reconciliation, same rule as the terminals.
    actual   = challenge_escrow_balance(db, challenge_id)
    expected = expected_challenge_escrow(db, challenge_id)
    if actual != expected:
        event = _open_event(
            db, event_id=event_id, event_type="challenge_accept",
            challenge=challenge, actor_identity=str(actor_team_id),
            proposal_id=proposal.id, prior_state=prior,
        )
        event.resulting_state = prior
        event.result_code     = RESULT_RECONCILIATION_ERROR
        db.flush()
        db.commit()
        raise EscrowReconciliationError(
            f"Challenge {challenge_id}: escrow holds {actual} cents but provenance "
            f"says {expected}. Acceptance refused; nothing posted."
        )

    # 4 — REVALIDATE BOTH SIDES BEFORE ANY WRITE. Nothing above this line has
    # written money or state; nothing below it is conditional.
    required_top_up = max(0, anchor_target - actual)
    if required_top_up > 0:
        issuer_capacity = available_cents(db, anchor, challenge.week)
        if issuer_capacity < required_top_up:
            db.rollback()
            raise AcceptanceCapacityError(
                f"Acceptance refused: issuer team {anchor} needs a "
                f"{required_top_up}-cent Anchor top-up but has {issuer_capacity} "
                f"available. No posting, no Bet, no state change; challenge "
                f"{challenge_id} remains {prior!r}."
            )
    if derived_needed > 0:
        recipient_capacity = available_cents(db, derived, challenge.week)
        if recipient_capacity < derived_needed:
            db.rollback()
            raise AcceptanceCapacityError(
                f"Acceptance refused: recipient team {derived} needs "
                f"{derived_needed} cents for the Derived stake but has "
                f"{recipient_capacity} available. No posting, no Bet, no state "
                f"change; challenge {challenge_id} remains {prior!r}."
            )

    event = _open_event(
        db, event_id=event_id, event_type="challenge_accept",
        challenge=challenge, actor_identity=str(actor_team_id),
        proposal_id=proposal.id, prior_state=prior,
    )

    # 5 — true up the issuer's escrow to the accepted Anchor.
    if required_top_up > 0:
        # RAISE: the ISSUER funds it, min-first — even when the recipient authored
        # the counter that raised it (A4 / §12).
        _fund(db, challenge=challenge, team_id=anchor,
              required_cents=required_top_up,
              destination=challenge_escrow_account(challenge_id),
              event=event, door=DOOR_TOPUP)
    elif anchor_target < actual:
        # LOWER: release the excess to its original sources FIRST, in strict
        # reverse-leg order, so the migration below reads a settled balance
        # (OPR-3: release before migrate).
        _reverse(db, challenge=challenge, amount_cents=actual - anchor_target,
                 event=event, door=DOOR_RELEASED)

    # 6 — Bet rows.
    anchor_bet  = _create_bet(db, challenge=challenge, team_id=anchor,
                              stake_cents=anchor_target, odds=proposal.anchor_odds)
    derived_bet = _create_bet(db, challenge=challenge, team_id=derived,
                              stake_cents=derived_needed, odds=proposal.derived_odds)

    # 7 — migrate the reconciled Anchor escrow into the Anchor Bet's escrow.
    ledger_post(
        [
            (challenge_escrow_account(challenge_id), -anchor_target),
            (f"escrow:{anchor_bet.id}",               anchor_target),
        ],
        door=DOOR_MIGRATED, session=db, protocol_event_id=event.id,
    )

    # 8 — the recipient funds their Derived stake independently, min-first.
    if derived_needed > 0:
        _fund(db, challenge=challenge, team_id=derived,
              required_cents=derived_needed,
              destination=f"escrow:{derived_bet.id}",
              event=event, door=DOOR_DERIVED)

    # 9 — Spec 1's state transition, last, inside the same transaction.
    transition = spec1.accept_locked_proposal(
        challenge_id=challenge_id, actor_team_id=actor_team_id, db=db, now=now)

    challenge.challenger_bet_id = (anchor_bet.id if anchor == challenge.challenger_team_id
                                   else derived_bet.id)
    challenge.challenged_bet_id = (derived_bet.id if derived == challenge.challenged_team_id
                                   else anchor_bet.id)

    event.resulting_state = spec1.ACCEPTED
    event.result_code     = RESULT_OK
    db.flush()
    db.commit()

    return FundingResult(
        challenge_id      = challenge_id,
        event_id          = event_id,
        protocol_event_id = event.id,
        response_status   = spec1.ACCEPTED,
        result_code       = RESULT_OK,
        escrow_cents      = 0,          # challenge escrow is fully migrated out
        replayed          = False,
        detail            = "accepted, escrow migrated, Derived funded",
        anchor_bet_id     = anchor_bet.id,
        derived_bet_id    = derived_bet.id,
    )
