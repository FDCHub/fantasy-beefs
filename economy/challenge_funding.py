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
    revive   → a fresh funded issue of a terminal challenge (Spec 1 §8), through
               the SAME funding algorithm as issue

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
from economy.spend_sourcing import plan_spend_split
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
    """§4 — split `required_cents` MIN FIRST then wallet, in funding order.

    DELEGATES to economy.spend_sourcing.plan_spend_split, which is now the ONE
    implementation of this order (S5-P1 §3). The behaviour is unchanged and this
    name is retained because §11's refund replay and the P1-L4 provenance
    assertions are written against it; what changed is that the Pool weekly
    contribution now calls the same code instead of debiting wallet directly.
    """
    return plan_spend_split(db, team_id, week, required_cents)


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
    account: Optional[str] = None,
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

    # P3-D2: `account` selects WHICH escrow account is being reversed out of.
    # It defaults to the pooled pre-acceptance account, so every Locked and
    # pre-Handshake caller behaves exactly as before. The Dynamic Final-Lock
    # refund passes the per-side Derived account (Rev 9 §7.1), which is the only
    # reason the parameter exists — the algorithm itself is unchanged, because
    # source-faithful strict-reverse-order reversal is the same act whichever
    # escrow account holds the money.
    account = account or challenge_escrow_account(challenge.id)
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

# ── WP1C — postseason admission gate ──────────────────────────────────────────
#
# ONE HELPER, FIVE CALL SITES, NO RULE OF ITS OWN. Every entry point below that
# creates or materially advances a NEW commitment calls this and nothing else;
# the eligibility rule itself lives in season/championship_track.py and the
# comparison in beefs/postseason_versus.py. Nothing here decides who is
# eligible — it supplies the league row and forwards.
#
# PLACEMENT IS LOAD-BEARING AT EVERY CALL SITE (WP1C §13). The gate goes AFTER
# idempotency replay and after the already-closed / open-state guard, and BEFORE
# the first write. A committed action retried after the bracket advanced must
# return its committed result rather than being re-judged against a field that
# has since contracted — so a gate placed above those guards would retroactively
# invalidate a wager the protocol already accepted.
#
# REGULAR SEASON IS UNTOUCHED. `assert_admissible` short-circuits on the phase
# boundary before reading `postseason_state` or `resolver`, so a regular-season
# call with both absent does exactly what it did before WP1C.
#
# THE PARAMETER IS NAMED FOR THE QUESTION, NOT THE DTO. It carries a
# `ChampionshipTrackState`, but what this module needs from it is postseason
# ELIGIBILITY, and `challenge_funding` is fenced against Championship-Pot
# identifiers by test_p1_l4_challenge_escrow_pg's scope fence. `championship`
# there means the season-close pot, a different concept that happens to share
# a word; naming the parameter for what it is used for keeps that fence intact
# and is the clearer name besides.

def _gate_postseason(db: Session, *, league_id: Optional[int], week: int,
                     team_ids, postseason_state, resolver, action: str) -> None:
    """Refuse a postseason Versus action unless both teams are eligible."""
    from beefs.postseason_versus import assert_admissible
    from db.schema import League

    league = (db.query(League).filter(League.id == league_id).first()
              if league_id is not None else None)
    if league is None:
        # No league row means no governed boundary, which is the pre-WP1C
        # world: a legacy or unbound challenge. It is not a postseason week by
        # any authority available here, so the gate does not invent one.
        return
    assert_admissible(league=league, week=week, team_ids=team_ids,
                      state=postseason_state, resolver=resolver, action=action)


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
    postseason_state=None,
    resolver=None,
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

    # WP1C — postseason admission, after replay and before the first lock. No
    # challenge row exists yet, so replay is the only prior guard there is.
    _gate_postseason(db, league_id=league_id, week=week,
                     team_ids=(challenger_team_id, challenged_team_id),
                     postseason_state=postseason_state, resolver=resolver,
                     action="issue")

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
    return _fund_issued_challenge(
        db, event_id=event_id, transition=transition,
        issuer_team_id=challenger_team_id, anchor_cents=anchor_cents,
        detail="issued with escrow",
    )


def _fund_issued_challenge(
    db: Session,
    *,
    event_id: uuid.UUID,
    transition: spec1.TransitionResult,
    issuer_team_id: int,
    anchor_cents: int,
    detail: str,
) -> FundingResult:
    """Steps 4-5 of §9, shared by EVERY funded issue.

    Both `issue_funded_challenge` and `revive_funded_challenge` land here, which
    is the point: a revive is a fresh issue (Spec 1 §8), so it must escrow
    through the SAME algorithm — one source split, one provenance shape, one
    event contract, one commit. A second funding path would be a second thing to
    keep correct.

    The caller owns everything above this line: the idempotency check, the lock
    order, the under-lock capacity decision and the Spec 1 transition. This owns
    the posting and the commit.
    """
    challenge = db.query(BeefChallenge).filter(
        BeefChallenge.id == transition.challenge_id).one()

    event = _open_event(
        db,
        event_id       = event_id,
        event_type     = "challenge_issue",
        challenge      = challenge,
        actor_identity = str(issuer_team_id),
        proposal_id    = transition.active_proposal_id,
        prior_state    = None,
    )

    # Real money into the challenge's own escrow account, min-first.
    _fund(db, challenge=challenge, team_id=issuer_team_id,
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
        detail            = detail,
    )


# ── §8/§9 Funded revive (Spec 1 §8 — a revive IS an issue) ────────────────────

def revive_funded_challenge(
    *,
    event_id: uuid.UUID,
    challenge_id: int,
    actor_team_id: int,
    terms: spec1.ProposalTerms,
    db: Session,
    proposal_lock_at: Optional[datetime] = None,
    schedule_source_ref: Optional[str] = None,
    now: Optional[datetime] = None,
    postseason_state=None,
    resolver=None,
) -> FundingResult:
    """Revive a negotiation-terminal challenge as a NEW funded challenge.

    SPEC 1 §8 RULES THIS IS NOT A LIFECYCLE EDGE: "Revive is a fresh
    issue_challenge()." So it is not a new economic act needing new accounting —
    it is an issue, and it escrows exactly like one. That is why this posts
    through _fund_issued_challenge() and why the protocol event is
    `challenge_issue` rather than a seventh verb: the six-verb vocabulary
    (db.schema.CHALLENGE_EVENT_TYPES) stays closed, and the revive relationship
    is already recorded structurally on the new row's
    `revived_from_challenge_id`.

    WHAT THIS CLOSES. spec1.revive_challenge() creates a new challenge and
    proposal but posts nothing and never commits (Package 2A's G3 gate).
    Before P1-L4A there was no funded wrapper, so the only way to commit a
    revived challenge was for a caller to commit Spec 1's half alone — which is
    precisely the escrow-less challenge Spec 2 §14 and Spec 1 §10 forbid. A
    revived new-model challenge is now uncreatable without real Anchor escrow,
    because this is the only path that commits one.

    LOCK ORDER (§8). The OLD challenge row FIRST, then the issuer's Wallet
    scope. That rank is not optional: spec1.revive_challenge() takes the old
    challenge's row lock itself, so locking the Wallet first would build the
    Wallet→Challenge inversion P1-L7 exists to prevent. The NEW challenge needs
    no lock — it does not exist outside this uncommitted transaction.

    THE ANCHOR IS THE ORIGINAL ISSUER (A4), read from the OLD challenge's
    challenger, not from the actor. Spec 1 separately refuses any actor who is
    not that team, so the capacity checked here is always the team that will
    actually owe the Anchor.
    """
    existing = _find_event(db, event_id)
    if existing is not None:
        return _replayed(db, existing)

    anchor_cents = terms.anchor_stake_cents
    if anchor_cents is None or anchor_cents <= 0:
        raise MissingProposalError(
            "terms.anchor_stake_cents must be a positive integer number of cents.")

    # 1 — the OLD challenge row first, then wallets. Never inverted.
    old    = _lock_challenge(db, challenge_id)
    issuer = old.challenger_team_id

    # WP1C — A REVIVE IS A FRESH COMMITMENT, so it is admitted like one. Spec 1
    # rules it "a fresh issue_challenge()", and it posts a fresh Anchor escrow;
    # eligibility at the ORIGINAL issue does not carry forward to it. Gated after
    # the row lock, before the wallet lock and every write.
    _gate_postseason(db, league_id=old.league_id, week=old.week,
                     team_ids=(old.challenger_team_id, old.challenged_team_id),
                     postseason_state=postseason_state, resolver=resolver,
                     action="revive")

    lock_funding_scopes(db, issuer)

    # 2 — authoritative capacity under the lock, on the ORIGINAL issuer.
    capacity = available_cents(db, issuer, old.week)
    if capacity < anchor_cents:
        raise InsufficientFundingCapacityError(
            f"Team {issuer} cannot fund a {anchor_cents}-cent Anchor to revive "
            f"challenge {challenge_id}: {capacity} cents available (min + "
            f"wallet). No challenge was revived and nothing was posted."
        )

    # 3 — Spec 1 validates that the source is negotiation-terminal and that the
    # actor is the original issuer, then creates an entirely new challenge +
    # proposal + both-sides starters. The old row is read for identity only and
    # is never written.
    transition = spec1.revive_challenge(
        challenge_id        = challenge_id,
        actor_team_id       = actor_team_id,
        terms               = terms,
        db                  = db,
        proposal_lock_at    = proposal_lock_at,
        schedule_source_ref = schedule_source_ref,
        now                 = now,
    )

    # 4/5 — the SAME funding algorithm every other issue uses.
    return _fund_issued_challenge(
        db, event_id=event_id, transition=transition,
        issuer_team_id=issuer, anchor_cents=anchor_cents,
        detail=f"revived from challenge {challenge_id} with escrow",
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
    postseason_state=None,
    resolver=None,
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

    # WP1C — A COUNTER MOVES NO MONEY AND IS STILL GATED. It freezes a new
    # proposal version and hands the decision back, which is exactly what
    # "materially advances a commitment" means: the wager the other side may
    # then accept is the countered one. Admitting a counter between teams that
    # may no longer wager would leave a live offer nobody is allowed to take.
    _gate_postseason(db, league_id=challenge.league_id, week=challenge.week,
                     team_ids=(issuer, recipient),
                     postseason_state=postseason_state, resolver=resolver,
                     action="counter")

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


def _opposite_side(side: Optional[str]) -> Optional[str]:
    """The complementary Over/Under position. None stays None."""
    if side == "over":
        return "under"
    if side == "under":
        return "over"
    return side


def _accepted_side_terms(
    challenge: BeefChallenge,
    proposal: BeefProposal,
    team_id: int,
) -> tuple[Optional[int], Optional[float], Optional[str]]:
    """(picked_team_id, line, side) for ONE side's Bet row, resolved from the
    ACCEPTED FROZEN PROPOSAL.

    P1-L4A — TWO SEPARATE CORRECTIONS LIVE HERE, AND BOTH ARE LOAD-BEARING.

    (1) THE AUTHORITY IS THE PROPOSAL, NOT THE CHALLENGE CONTAINER. `line`,
        `side` and `player_id` are Spec 1 §3.2 "frozen resolved market terms" and
        are owned by the proposal VERSION. BeefChallenge.line/.side are legacy
        NOT NULL mirror columns written exactly once at issue from version 1
        (proposal_lifecycle.py, "the new model never reads them"), and a Refresh
        & Relock counter never updates them — a counter recomputes the
        lineup-derived quote, and for a Spread the line IS that quote. Reading
        the container after a counter therefore builds Bet rows on version 1's
        stale line while the parties accepted version 2's, and settlement
        (_eval_beef) evaluates `margin > bet.line` against terms nobody agreed
        to. The container keeps only what is genuinely challenge-immutable:
        `wager_type` (§5 — "the wager class lives once, on the challenge"), the
        participants and the week.

    (2) THE TWO SIDES ARE COMPLEMENTARY POSITIONS, NOT TWO COPIES OF ONE. A
        proposal freezes ONE market position; the two Bet rows are the two sides
        OF it, so the second row must be mirrored. Settlement evaluates whichever
        row it reaches first and infers the other as the complement
        (settlement_engine.py:551-593), so unmirrored rows make the outcome
        depend on iteration order:

            Spread, accepted line 3.0, actual margin +1.0
              anchor row   : 1.0 > 3.0  → lost   → winner = derived   ✔
              derived row  : -1.0 > 3.0 → lost   → winner = anchor    ✘ contradiction

        Negating the Derived side's line makes the second read -1.0 > -3.0 → won,
        which agrees with the first. Over/Under is the same shape with the side
        flipped instead of the line negated. This mirrors the legacy path's
        _challenger_side_params/_challenged_side_params semantics exactly, but
        sourced from the accepted proposal rather than the container — the
        legacy engine is deliberately NOT imported (the fence forbids that edge).

    Roles map through the CHALLENGE PARTICIPANTS, not through Anchor/Derived,
    because _eval_beef resolves the opponent by comparing picked_team_id against
    challenger_team_id/challenged_team_id. The Anchor is always the original
    issuer (A4), so the two happen to coincide; keying on the participant is what
    settlement actually reads.
    """
    wager_type   = challenge.wager_type or challenge.bet_type
    is_challenger = (team_id == challenge.challenger_team_id)

    if wager_type == "straight":
        # Moneyline. No line, no side — the pick alone carries the position.
        return team_id, None, None

    if wager_type == "spread":
        line = proposal.line or 0.0
        # The challenged party wins if the challenger fails to cover, so their
        # effective line is the negation.
        return team_id, (line if is_challenger else -line), None

    # over_under — no pick (the schema's picked_team_id is null for o/u); the
    # two sides differ by taking opposite ends of the SAME frozen total.
    return (None,
            proposal.line,
            proposal.side if is_challenger else _opposite_side(proposal.side))


def _create_bet(db: Session, *, challenge: BeefChallenge, proposal: BeefProposal,
                team_id: int, stake_cents: int, odds: Optional[float]) -> Bet:
    """One side's Bet row, built from the ACCEPTED FROZEN PROPOSAL.

    FIELD AUTHORITY, verified against Spec 1 rather than copied:
      bet_type        ← challenge.wager_type   (§3.1/§5 immutable wager class)
      matchup / week  ← challenge.week         (§3.1 immutable)
      picked_team_id  ← participant identity   (§3.1 fixed at creation)
      line, side      ← ACCEPTED PROPOSAL      (§3.2 frozen resolved terms)
      player_id       ← ACCEPTED PROPOSAL      (§3.2 frozen resolved terms)
      odds            ← ACCEPTED PROPOSAL      (§3.2 pricing provenance)
      amount          ← authoritative cents    (§6 legacy float mirror only)

    The challenge's own legacy line/side/player_id mirrors are NOT read here and
    are NOT written to match. §3.2 makes the proposal the authority; rewriting
    the container to agree would create a second, divergeable copy of a value
    that already has one home.
    """
    wallet  = db.query(Wallet).filter(Wallet.team_id == team_id).one()
    matchup = _find_matchup(db, team_id, challenge.week)
    picked_team_id, line, side = _accepted_side_terms(challenge, proposal, team_id)
    bet = Bet(
        matchup_id        = matchup.id,
        wallet_id         = wallet.id,
        picked_team_id    = picked_team_id,
        player_id         = proposal.player_id,
        bet_type          = challenge.wager_type or challenge.bet_type,
        line              = line,
        side              = side,
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
    postseason_state=None,
    resolver=None,
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

    # P3-D2 — MODE GUARD, AHEAD OF EVERY WRITE. Spec 1's accept_locked_proposal
    # already refuses a Dynamic challenge, but it runs at step 9, after the
    # true-up, the Bet rows and the escrow migration. Everything sits in one
    # transaction so nothing incorrect could ever commit, yet a caller that
    # pointed the Locked path at a Dynamic challenge would do a transaction's
    # worth of work and surface whichever constraint it tripped first rather
    # than the mode mismatch that actually caused it. Refusing here makes the
    # boundary between the two modes explicit and the error honest.
    if challenge.challenge_mode != spec1.MODE_LOCKED:
        raise spec1.UnsupportedModeError(
            f"Challenge {challenge_id} is mode {challenge.challenge_mode!r}. "
            f"Locked acceptance handles only {spec1.MODE_LOCKED!r}; the Dynamic "
            f"Handshake is economy/dynamic_challenge.py's."
        )

    anchor    = anchor_team_id(challenge, proposal)
    derived   = derived_team_id(challenge, proposal)

    # WP1C — ACCEPTANCE IS THE COMMITMENT, so it is gated here: after the replay
    # check, after `_already_closed`, after the mode guard, and before the
    # capacity revalidation at step 4 that the docstring calls "the last point at
    # which nothing has happened". An already-accepted challenge returned above
    # and is never re-judged.
    _gate_postseason(db, league_id=challenge.league_id, week=challenge.week,
                     team_ids=(challenge.challenger_team_id,
                               challenge.challenged_team_id),
                     postseason_state=postseason_state, resolver=resolver,
                     action="accept")

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

    # 6 — Bet rows, built from THIS proposal — the one being accepted, which
    # after a counter is version 2, not the version 1 the container mirrors.
    anchor_bet  = _create_bet(db, challenge=challenge, proposal=proposal,
                              team_id=anchor, stake_cents=anchor_target,
                              odds=proposal.anchor_odds)
    derived_bet = _create_bet(db, challenge=challenge, proposal=proposal,
                              team_id=derived, stake_cents=derived_needed,
                              odds=proposal.derived_odds)

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
