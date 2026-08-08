"""
beefs/proposal_lifecycle.py — SPEC 1 (Locked Challenge Proposal Lifecycle, Rev 3):
the deterministic proposal lifecycle service. Sprint 2, Package 2A.

WHAT THIS MODULE IS. The container + immutable-versioned-proposal lifecycle:
issue, one counter, accept (Locked), decline, cancel, expire, and revive-as-a-new-
challenge. It owns proposal version allocation, proposal-scoped both-team starter
snapshots, the §8 actor-authorization matrix, and first-valid-commit serialization
on the challenge row.

WHAT THIS MODULE IS NOT, and cannot become by accident:

  * IT MOVES NO MONEY. No escrow, no refund, no Bet row, no Wallet mutation, no
    ledger posting. §1: "No money movement. Issue/accept/refund/expiry
    postings are Spec 2. Spec 1 leaves named integration seams; it posts nothing."
    It imports neither the ledger, nor wallet_manager, nor beef_engine — not for
    tidiness, but because an import is the first step of a reachable path.

  * IT NEVER COMMITS. Not once, on any path. See TRANSACTION OWNERSHIP below.

  * IT IS UNREACHABLE FROM PRODUCTION. No route imports it and none registers it.
    §1: "New-model issuance/response flows stay unreachable … until Spec 2
    supplies escrow." §12 requires that be "proven by unreachability, not throwing
    stubs" — so there are no stubs here that raise; there is simply no path in.

TRANSACTION OWNERSHIP — INVERTED FROM THE B6 SERVICES, DELIBERATELY.

    Every function takes a caller-supplied Session, does its reads, locks and
    writes on it, and RETURNS WITHOUT COMMITTING. There is no commit() in this
    file and no rollback(); this module owns no transaction and opens none.

Spec 1 §10 is the reason: "Spec 1 must not commit a lifecycle state and then call
Spec 2. When enabled, each integrated transition is one atomic unit" — issue with
escrow-at-issue, accept with Bet rows and escrow migration, decline/cancel/expire
with refunds. Package 2B owns that transaction and issues its single commit. A
module with no commit in it cannot produce committed lifecycle state on its own,
which is what makes "no economically live wager without escrow" structural rather
than promised.

flush() IS USED AND IS NOT A COMMIT. Ids are needed mid-transaction — the
challenge before its proposal, the proposal before its starters and before the
active pointer can reference it (the composite same-challenge FK, §3.4). flush()
writes inside the caller's transaction and is discarded by the caller's rollback.

SERIALIZATION (§9). Every state-changing operation takes the challenge row
SELECT … FOR UPDATE first, reloads response_status under it, validates the active
proposal, and allocates the next version_number under that same lock.
UNIQUE(challenge_id, version_number) is the structural backstop, not the primary
mechanism. FIRST VALID COMMIT GOVERNS: a later conflicting or repeated caller
reloads the committed result and returns deterministically ("already countered",
"already accepted", "already expired") instead of raising or double-writing.

populate_existing() on the locking query is load-bearing for the same reason it
was in B6: SQLAlchemy's identity map returns an already-loaded instance without
refreshing it, so a re-read "under the lock" would otherwise re-read a snapshot
taken before the lock was granted.

IMMUTABILITY (§3.2). BeefProposal is INSERT-ONLY. Nothing in this module updates
a proposal row after creation — not the initial one when a counter supersedes it,
not the accepted one at acceptance. A counter creates version 2 and repoints the
challenge; version 1 is untouched, which is what makes the historical deadline
and quote reproducible after the pointer moves.

WHAT THE CALLER SUPPLIES, AND WHY. Frozen market terms, stake figures, pricing
provenance and proposal_lock_at arrive as parameters. Spec 1 owns their FREEZING
and IMMUTABILITY (§3 ownership boundary); it does not own their computation —
pricing belongs to the quote engine and the kickoff timestamp to the schedule
source, and reaching into either from here would drag the legacy import graph in
behind it. This module validates what it is given, freezes it, and never lets it
change afterwards.

TIME IS NAIVE UTC THROUGHOUT. Every DateTime column in this schema is a bare
DateTime, so a value read back is naive. Mixing an aware value into a comparison
with one is False in Python rather than an error — a silent wrong answer, and
exactly the defect B6's season-close writer had to normalise away. Every
timestamp entering or leaving this module goes through _naive_utc() first.

LEGACY COLUMNS. BeefChallenge still carries the legacy NOT NULL columns of the
old mutable model (bet_type, amount, odds, moneylines, expires_at, status). A
new-model challenge populates them once, at issue, so the row is insertable, and
then never consults them: `response_status` is the negotiation authority (§4).
Note that legacy `status` has no 'cancelled' value in its CHECK, which is another
reason the two vocabularies stay separate rather than being mirrored.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import (
    BeefChallenge,
    BeefProposal,
    BeefProposalStarter,
    Roster,
)

# ── Vocabulary (§3.1, §4) ─────────────────────────────────────────────────────

MODE_LOCKED  = "locked"
MODE_DYNAMIC = "dynamic"
VALID_MODES  = (MODE_LOCKED, MODE_DYNAMIC)

# Matches ck_beef_wager_type / ck_beef_bet_type. Ruling 2: 'straight' is the
# persisted value for Moneyline; "Moneyline" is a display label only.
VALID_WAGER_TYPES = ("straight", "spread", "over_under")

OFFERED   = "offered"
COUNTERED = "countered"
ACCEPTED  = "accepted"
DECLINED  = "declined"
EXPIRED   = "expired"
CANCELLED = "cancelled"

# §4 — terminal WITHIN NEGOTIATION SCOPE. `accepted` is deliberately absent:
# it is action-closed for negotiation but NOT a terminal wager outcome, and
# terminal-protection logic keyed on it would block an accepted wager from
# settlement.
NEGOTIATION_TERMINAL = (DECLINED, EXPIRED, CANCELLED)

# Open states — a transition may still be requested from these.
OPEN_STATES = (OFFERED, COUNTERED)

VERSION_INITIAL = "initial"
VERSION_COUNTER = "counter"

# §3.2 — effective response deadline = min(created_at + 60 minutes,
# proposal_lock_at). Deliberately NOT the legacy 24-hour CHALLENGE_TTL_HOURS:
# the new model's window is its own, and beef_engine's constant is untouched.
RESPONSE_TTL_MINUTES = 60

# First-N roster players per team, mirroring the legacy capture's shape.
N_START = 9

# MVP ceiling: one initial plus at most one counter (§8, "no re-counter").
MAX_VERSION_NUMBER = 2


# ── Errors ────────────────────────────────────────────────────────────────────

class ProposalLifecycleError(ValueError):
    """Base for every lifecycle refusal. Subclasses are distinct TYPES so callers
    and tests branch on type, never on message text."""


class ChallengeNotFoundError(ProposalLifecycleError):
    """No BeefChallenge with that id."""


class NotANewModelChallengeError(ProposalLifecycleError):
    """The row exists but carries no response_status, so it is a legacy mutable
    challenge. Refused rather than adopted: a legacy row has no versioned
    proposal, no both-team proposal snapshot and no frozen pricing history, and
    §11 authorises no automatic migration of one into the new model."""


class ActorNotAuthorizedError(ProposalLifecycleError):
    """§8 — this actor may not perform this transition from this state. A
    deterministic refusal, never a silent no-op: the caller asked for something
    the matrix does not permit."""


class InvalidTransitionError(ProposalLifecycleError):
    """The requested transition is not legal from the current state for reasons
    other than actor identity — a second counter attempt on a fresh challenge, an
    unsupported mode, a malformed argument."""


class DeadlinePassedError(ProposalLifecycleError):
    """The active proposal's effective deadline has passed, so the requested
    response can no longer be made. The challenge is NOT expired by this call:
    expiry is a system transition with its own writer (§7.4)."""


class DeadlineNotReachedError(ProposalLifecycleError):
    """expire_challenge() was called before the effective deadline. Refused —
    expiring early would destroy a live negotiation."""


class UnsupportedModeError(ProposalLifecycleError):
    """Locked is implemented; Dynamic is a DEFINED BOUNDARY handed to Spec 3
    (§7.3), reachable only through a Dynamic-mode challenge, which Package 2A
    never issues an accept path for."""


# ── Frozen inputs ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProposalTerms:
    """Everything a proposal freezes, supplied by the caller.

    Spec 1 owns the freezing and the immutability of these values, not their
    computation (§3 ownership boundary). All money is INTEGER CENTS.

    `display_terms` is explicitly NON-AUTHORITATIVE (§3.2): the structured fields
    govern and display may never disagree with them.
    """
    line:      Optional[float] = None
    side:      Optional[str]   = None
    player_id: Optional[int]   = None

    anchor_stake_cents:          Optional[int] = None
    quoted_derived_stake_cents:  Optional[int] = None
    quoted_funded_pot_cents:     Optional[int] = None
    quoted_anchor_payout_cents:  Optional[int] = None
    quoted_derived_payout_cents: Optional[int] = None

    pricing_model_id:          Optional[str]      = None
    pricing_calc_version:      Optional[str]      = None
    projection_source_id:      Optional[str]      = None
    projection_retrieved_at:   Optional[datetime] = None
    projection_input_snapshot: Optional[dict]     = None
    anchor_win_probability:    Optional[float]    = None
    derived_win_probability:   Optional[float]    = None
    anchor_odds:               Optional[float]    = None
    derived_odds:              Optional[float]    = None
    anchor_moneyline:          Optional[int]      = None
    derived_moneyline:         Optional[int]      = None
    pricing_input_hash:        Optional[str]      = None

    display_terms: Optional[str] = None


@dataclass(frozen=True)
class TransitionResult:
    """What one lifecycle call produced.

    `changed` is False on every non-writing path. `replayed` is True when the
    call found the challenge already in a state that closes the request — §9's
    "already countered / already accepted / already expired". The two together
    let a caller distinguish "I did this" from "someone else already did".
    """
    challenge_id:         int
    response_status:      str
    active_proposal_id:   Optional[int]
    accepted_proposal_id: Optional[int]
    version_number:       Optional[int]
    changed:              bool
    replayed:             bool
    detail:               str = ""


# ── Time ──────────────────────────────────────────────────────────────────────

def _naive_utc(moment: datetime) -> datetime:
    """A datetime as these bare DateTime columns store it: naive, in UTC.

    An AWARE input is converted to UTC and stripped; a NAIVE input is taken to be
    UTC already, the codebase-wide convention for these columns. Applied to every
    generated timestamp, every caller-supplied one and every value read back, so
    all three are directly comparable.
    """
    if moment.tzinfo is not None:
        return moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def _now(now: Optional[datetime] = None) -> datetime:
    """The call's single authoritative timestamp. Injectable so a test can place
    itself either side of a deadline without sleeping."""
    return _naive_utc(now) if now is not None else _naive_utc(datetime.now(timezone.utc))


def effective_deadline(created_at: datetime,
                       proposal_lock_at: Optional[datetime]) -> datetime:
    """§3.2 — min(created_at + 60 minutes, proposal_lock_at).

    The TTL alone is not the deadline: a proposal whose covered starters kick off
    in twenty minutes cannot be answerable for sixty. When no lock timestamp is
    known the TTL governs on its own.
    """
    ttl_deadline = _naive_utc(created_at) + timedelta(minutes=RESPONSE_TTL_MINUTES)
    if proposal_lock_at is None:
        return ttl_deadline
    return min(ttl_deadline, _naive_utc(proposal_lock_at))


# ── Internal helpers ──────────────────────────────────────────────────────────

def _lock_challenge(db: Session, challenge_id: int) -> BeefChallenge:
    """§9 step 1 — the serialization point, and the FIRST database statement of
    every state-changing call.

    populate_existing() is load-bearing: without it a caller that had already
    loaded this row would keep its cached response_status, and the reload "under
    the lock" at step 2 would re-read a pre-lock snapshot.
    """
    challenge = (
        db.query(BeefChallenge)
        .filter(BeefChallenge.id == challenge_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if challenge is None:
        raise ChallengeNotFoundError(f"No challenge {challenge_id} exists.")
    if challenge.response_status is None:
        raise NotANewModelChallengeError(
            f"Challenge {challenge_id} carries no response_status: it is a legacy "
            f"mutable challenge, not a new-model one. §11 authorises no automatic "
            f"migration of legacy rows into the proposal lifecycle."
        )
    return challenge


def _active_proposal(db: Session, challenge: BeefChallenge) -> Optional[BeefProposal]:
    if challenge.active_proposal_id is None:
        return None
    return (
        db.query(BeefProposal)
        .filter(BeefProposal.id == challenge.active_proposal_id)
        .first()
    )


def _closed(challenge: BeefChallenge, detail: str) -> TransitionResult:
    """§9's deterministic answer for a caller that arrived second. Writes
    nothing; reports the committed state the first valid caller produced."""
    return TransitionResult(
        challenge_id         = challenge.id,
        response_status      = challenge.response_status,
        active_proposal_id   = challenge.active_proposal_id,
        accepted_proposal_id = challenge.accepted_proposal_id,
        version_number       = None,
        changed              = False,
        replayed             = True,
        detail               = detail,
    )


def _require_actor(actual_team_id: int, permitted_team_id: int,
                   action: str, state: str) -> None:
    if actual_team_id != permitted_team_id:
        raise ActorNotAuthorizedError(
            f"Team {actual_team_id} may not {action} a challenge in state "
            f"{state!r}; §8 permits only team {permitted_team_id}."
        )


def _capture_proposal_starters(
    db: Session,
    proposal_id: int,
    challenger_team_id: int,
    challenged_team_id: int,
) -> int:
    """§3.3/§6 — freeze BOTH teams' covered starters onto THIS proposal version.

    Every proposal captures its own snapshot of both sides. A counter re-captures
    both, even when only one team changed their lineup, so that each version is
    INDEPENDENTLY REPRODUCIBLE and no cross-proposal join is ever needed to
    reconstruct one. Nothing here reads the challenge-scoped BeefStarter rows of
    the legacy model.

    The first-N-by-roster-id shape mirrors the legacy capture deliberately, so
    the two models describe the same covered set for the same lineup. It is
    duplicated rather than shared because extracting a helper would mean editing
    beef_engine.py, which is the live economic path; the legacy helper is retired
    when Package 2B enables this one.

    Returns the number of starter rows written.
    """
    written = 0
    for team_id in (challenger_team_id, challenged_team_id):
        slots = (
            db.query(Roster)
            .filter(Roster.team_id == team_id)
            .order_by(Roster.id)
            .limit(N_START)
            .all()
        )
        seen: set[int] = set()
        for slot in slots:
            if slot.player_id in seen:
                continue
            seen.add(slot.player_id)
            db.add(BeefProposalStarter(
                proposal_id = proposal_id,
                team_id     = team_id,
                player_id   = slot.player_id,
                nfl_team    = slot.player.nfl_team if slot.player else None,
            ))
            written += 1
    return written


def _insert_proposal(
    db: Session,
    challenge: BeefChallenge,
    version_number: int,
    version_kind: str,
    proposing_team_id: int,
    terms: ProposalTerms,
    created_at: datetime,
    proposal_lock_at: Optional[datetime],
    schedule_source_ref: Optional[str],
) -> BeefProposal:
    """Insert ONE immutable proposal version and its both-team snapshot.

    anchor_team_id is ALWAYS the challenge's challenger — the original issuer —
    even on a recipient-authored counter (§3.2, A4: role is bound to identity,
    not authorship). Getting this backwards would hand the Anchor role to
    whoever spoke last.
    """
    deadline = effective_deadline(created_at, proposal_lock_at)

    proposal = BeefProposal(
        challenge_id      = challenge.id,
        version_number    = version_number,
        version_kind      = version_kind,
        proposing_team_id = proposing_team_id,
        created_at        = created_at,

        response_expires_at = deadline,
        proposal_lock_at    = _naive_utc(proposal_lock_at) if proposal_lock_at else None,
        schedule_source_ref = schedule_source_ref,

        line      = terms.line,
        side      = terms.side,
        player_id = terms.player_id,

        anchor_stake_cents          = terms.anchor_stake_cents,
        quoted_derived_stake_cents  = terms.quoted_derived_stake_cents,
        quoted_funded_pot_cents     = terms.quoted_funded_pot_cents,
        quoted_anchor_payout_cents  = terms.quoted_anchor_payout_cents,
        quoted_derived_payout_cents = terms.quoted_derived_payout_cents,
        # A4 — the issuer is the Anchor across every version of this challenge.
        anchor_team_id  = challenge.challenger_team_id,
        derived_team_id = challenge.challenged_team_id,

        pricing_model_id          = terms.pricing_model_id,
        pricing_calc_version      = terms.pricing_calc_version,
        projection_source_id      = terms.projection_source_id,
        projection_retrieved_at   = (_naive_utc(terms.projection_retrieved_at)
                                     if terms.projection_retrieved_at else None),
        projection_input_snapshot = terms.projection_input_snapshot,
        anchor_win_probability    = terms.anchor_win_probability,
        derived_win_probability   = terms.derived_win_probability,
        anchor_odds               = terms.anchor_odds,
        derived_odds              = terms.derived_odds,
        anchor_moneyline          = terms.anchor_moneyline,
        derived_moneyline         = terms.derived_moneyline,
        pricing_input_hash        = terms.pricing_input_hash,

        display_terms = terms.display_terms,
    )
    db.add(proposal)
    # flush, not commit: the starters and the active pointer both need this id,
    # and the composite same-challenge FK (§3.4) requires the row to exist.
    db.flush()

    _capture_proposal_starters(
        db, proposal.id, challenge.challenger_team_id, challenge.challenged_team_id,
    )
    db.flush()
    return proposal


# ── §7.1 Initial offer ────────────────────────────────────────────────────────

def issue_proposal_challenge(
    *,
    league_id: int,
    week: int,
    challenger_team_id: int,
    challenged_team_id: int,
    challenge_mode: str,
    wager_type: str,
    terms: ProposalTerms,
    db: Session,
    proposal_lock_at: Optional[datetime] = None,
    schedule_source_ref: Optional[str] = None,
    now: Optional[datetime] = None,
    revived_from_challenge_id: Optional[int] = None,
) -> TransitionResult:
    """§7.1 — create the challenge container and its version-1 proposal.

    Writes, in one caller-owned transaction and with NO commit: the
    BeefChallenge (immutable mode, wager class, participants, week,
    response_status='offered'), BeefProposal version 1 ('initial', proposing team
    = challenger), both teams' proposal-scoped starters, the active pointer and
    the cached deadline.

    SEAM TO PACKAGE 2B (A1): escrow-at-issue. The challenge, proposal, starters
    and the issuer's escrow posting commit TOGETHER — 2B wraps this call and
    issues the single commit (§10). This function deliberately leaves the
    transaction open.
    """
    if challenge_mode not in VALID_MODES:
        raise InvalidTransitionError(
            f"challenge_mode must be one of {VALID_MODES}; got {challenge_mode!r}.")
    if wager_type not in VALID_WAGER_TYPES:
        raise InvalidTransitionError(
            f"wager_type must be one of {VALID_WAGER_TYPES}; got {wager_type!r}.")
    if challenger_team_id == challenged_team_id:
        raise InvalidTransitionError(
            "A team cannot challenge itself; the participants must differ.")

    created_at = _now(now)
    deadline   = effective_deadline(created_at, proposal_lock_at)

    challenge = BeefChallenge(
        # ── New-model container (§3.1). response_status is the authority. ──
        league_id                  = league_id,
        week                       = week,
        challenger_team_id         = challenger_team_id,
        challenged_team_id         = challenged_team_id,
        challenge_mode             = challenge_mode,
        wager_type                 = wager_type,
        response_status            = OFFERED,
        active_proposal_id         = None,      # set after the proposal exists
        accepted_proposal_id       = None,
        active_response_expires_at = deadline,
        revived_from_challenge_id  = revived_from_challenge_id,
        created_at                 = created_at,
        updated_at                 = created_at,

        # ── Legacy NOT NULL columns, populated once so the row is insertable.
        # The new model never reads them; `status` has no 'cancelled' value in
        # its CHECK, which is one more reason the vocabularies stay separate. ──
        bet_type             = wager_type,
        amount               = ((terms.anchor_stake_cents or 0) / 100.0),
        line                 = terms.line,
        side                 = terms.side,
        player_id            = terms.player_id,
        challenger_odds      = terms.anchor_odds or 0.0,
        challenged_odds      = terms.derived_odds or 0.0,
        challenger_moneyline = terms.anchor_moneyline or 0,
        challenged_moneyline = terms.derived_moneyline or 0,
        status               = "pending",
        expires_at           = deadline,
    )
    db.add(challenge)
    db.flush()                     # the proposal's FK needs challenge.id

    proposal = _insert_proposal(
        db, challenge,
        version_number      = 1,
        version_kind        = VERSION_INITIAL,
        proposing_team_id   = challenger_team_id,
        terms               = terms,
        created_at          = created_at,
        proposal_lock_at    = proposal_lock_at,
        schedule_source_ref = schedule_source_ref,
    )

    challenge.active_proposal_id = proposal.id
    db.flush()

    return TransitionResult(
        challenge_id         = challenge.id,
        response_status      = OFFERED,
        active_proposal_id   = proposal.id,
        accepted_proposal_id = None,
        version_number       = 1,
        changed              = True,
        replayed             = False,
        detail               = "offered",
    )


# ── §7.2 Refresh & Relock (counter) ───────────────────────────────────────────

def counter_challenge_proposal(
    *,
    challenge_id: int,
    actor_team_id: int,
    terms: ProposalTerms,
    db: Session,
    proposal_lock_at: Optional[datetime] = None,
    schedule_source_ref: Optional[str] = None,
    now: Optional[datetime] = None,
) -> TransitionResult:
    """§7.2 — the recipient refreshes their lineup and proposes a new Anchor.

    Creates version 2 with its OWN both-team starters and its own recomputed
    timing, repoints the active pointer, and sets response_status='countered'.
    VERSION 1 IS NOT TOUCHED — that immutability is what keeps the initial
    proposal's historical deadline and quote reproducible after the pointer
    moves.

    A counter may change the Anchor Stake and the lineup-derived quote; it may
    NOT change the wager class, the mode, the participants or the week (§5), and
    the Anchor role stays with the original issuer (A4).

    ONE COUNTER ONLY. A second attempt returns deterministically rather than
    raising: §9's "already countered" is the specified answer for the caller who
    arrived second, and two concurrent counters must resolve that way.

    SEAM TO PACKAGE 2B (A7): counter-time capacity validation is READ-ONLY and
    posts nothing. 2B performs it inside the same transaction as this call.
    """
    challenge = _lock_challenge(db, challenge_id)

    if challenge.response_status in NEGOTIATION_TERMINAL:
        return _closed(challenge, f"already {challenge.response_status}")
    if challenge.response_status == ACCEPTED:
        return _closed(challenge, "already accepted")
    if challenge.response_status == COUNTERED:
        # §8: "countered | anyone | no re-counter". Deterministic, not an
        # exception: the loser of a two-counter race must be told what happened.
        return _closed(challenge, "already countered")

    # Only the recipient may counter, and only from `offered`.
    _require_actor(actor_team_id, challenge.challenged_team_id, "counter", OFFERED)

    active = _active_proposal(db, challenge)
    if active is None:
        raise InvalidTransitionError(
            f"Challenge {challenge_id} has no active proposal to counter.")

    moment = _now(now)
    if moment >= effective_deadline(active.created_at, active.proposal_lock_at):
        raise DeadlinePassedError(
            f"The active proposal's response deadline has passed; challenge "
            f"{challenge_id} can no longer be countered. It remains "
            f"{challenge.response_status!r} until the expiry writer runs."
        )

    next_version = (challenge_active_version(db, challenge) or 1) + 1
    if next_version > MAX_VERSION_NUMBER:
        raise InvalidTransitionError(
            f"Version {next_version} exceeds the one-counter ceiling; a challenge "
            f"holds at most an initial proposal and one counter.")

    proposal = _insert_proposal(
        db, challenge,
        version_number      = next_version,
        version_kind        = VERSION_COUNTER,
        proposing_team_id   = actor_team_id,
        terms               = terms,
        created_at          = moment,
        proposal_lock_at    = proposal_lock_at,
        schedule_source_ref = schedule_source_ref,
    )

    challenge.active_proposal_id         = proposal.id
    challenge.response_status            = COUNTERED
    challenge.active_response_expires_at = proposal.response_expires_at
    challenge.updated_at                 = moment
    db.flush()

    return TransitionResult(
        challenge_id         = challenge.id,
        response_status      = COUNTERED,
        active_proposal_id   = proposal.id,
        accepted_proposal_id = None,
        version_number       = next_version,
        changed              = True,
        replayed             = False,
        detail               = "countered",
    )


def accept_dynamic_proposal(
    *,
    challenge_id: int,
    actor_team_id: int,
    db: Session,
    now: Optional[datetime] = None,
) -> TransitionResult:
    """§7.3's Dynamic branch — the Handshake's negotiation half.

    THIS FILLS THE SEAM §7.3 NAMED AND LEFT OPEN: "if challenge_mode ==
    'dynamic': <Handshake — Spec 3 boundary>". Until now the boundary was a
    refusal in accept_locked_proposal; this is the branch that boundary was
    reserved for, and it is deliberately a separate function rather than a mode
    flag on the Locked one, so no Locked caller can reach Dynamic behaviour by
    passing an argument.

    IDENTICAL TO THE LOCKED TRANSITION IN EVERYTHING THAT IS NEGOTIATION. Same
    actor rules (§8 — the recipient accepts from `offered`, the original issuer
    from `countered`), same deadline enforcement, same first-valid-commit
    semantics, same immutable-proposal selection with NO reprice. What differs is
    downstream and belongs to Spec 3's money half: a Locked acceptance yields
    Pending Bet rows immediately, while a Dynamic acceptance funds both ceilings
    and leaves the wager awaiting Final Lock (§4).

    NOTHING ECONOMIC HAPPENS HERE, and this function still never commits (the
    Package 2A G3 gate). The ceilings, the model freeze, the per-side escrow and
    the Handshake-exit assertion are all economy/dynamic_challenge.py's, inside
    the single transaction that wraps this call.
    """
    challenge = _lock_challenge(db, challenge_id)

    if challenge.response_status in NEGOTIATION_TERMINAL:
        return _closed(challenge, f"already {challenge.response_status}")
    if challenge.response_status == ACCEPTED:
        return _closed(challenge, "already accepted")

    if challenge.challenge_mode != MODE_DYNAMIC:
        raise UnsupportedModeError(
            f"Challenge {challenge_id} is mode {challenge.challenge_mode!r}; "
            f"accept_dynamic_proposal handles only {MODE_DYNAMIC!r}. Locked "
            f"acceptance is accept_locked_proposal()."
        )

    if challenge.response_status == OFFERED:
        _require_actor(actor_team_id, challenge.challenged_team_id, "accept", OFFERED)
    else:                                    # COUNTERED
        _require_actor(actor_team_id, challenge.challenger_team_id, "accept", COUNTERED)

    active = _active_proposal(db, challenge)
    if active is None:
        raise InvalidTransitionError(
            f"Challenge {challenge_id} has no active proposal to accept.")

    moment = _now(now)
    if moment >= effective_deadline(active.created_at, active.proposal_lock_at):
        raise DeadlinePassedError(
            f"The active proposal's deadline has passed; challenge {challenge_id} "
            f"can no longer be accepted."
        )

    challenge.accepted_proposal_id = active.id
    challenge.response_status      = ACCEPTED
    challenge.updated_at           = moment
    db.flush()

    return TransitionResult(
        challenge_id         = challenge.id,
        response_status      = ACCEPTED,
        active_proposal_id   = active.id,
        accepted_proposal_id = active.id,
        version_number       = active.version_number,
        changed              = True,
        replayed             = False,
        detail               = "accepted (dynamic handshake)",
    )


def challenge_active_version(db: Session, challenge: BeefChallenge) -> Optional[int]:
    """The version_number of the challenge's active proposal, read under
    whatever lock the caller already holds (§9 step 4)."""
    active = _active_proposal(db, challenge)
    return active.version_number if active is not None else None


# ── §7.3 Locked acceptance ────────────────────────────────────────────────────

def accept_locked_proposal(
    *,
    challenge_id: int,
    actor_team_id: int,
    db: Session,
    now: Optional[datetime] = None,
) -> TransitionResult:
    """§7.3 — accept the active proposal exactly as frozen.

    NO REPRICE (the Locked half of A9). The accepted terms are read from the
    frozen proposal; nothing is recomputed, no live inputs are fetched, and no
    odds may drift between offer and acceptance. That is the whole point of
    Locked mode.

    NOTHING ECONOMIC HAPPENS HERE. No Bet row, no escrow, no wallet write, no
    ledger posting. §7.3's seam to Package 2B (A8) is that the selected proposal,
    Bet-row creation, Anchor→Bet-escrow migration, the recipient's Derived escrow
    and the audit record all commit TOGETHER in one transaction — 2B's.

    `accepted` is action-closed for negotiation but is NOT a terminal wager
    outcome (§4): the accepted wager continues through Offered → Accepted →
    Pending → Final|Push|Void, governed by Bet rows and settlement. Nothing here
    may be read as settlement state.
    """
    challenge = _lock_challenge(db, challenge_id)

    if challenge.response_status in NEGOTIATION_TERMINAL:
        return _closed(challenge, f"already {challenge.response_status}")
    if challenge.response_status == ACCEPTED:
        return _closed(challenge, "already accepted")

    # §7.3 — accept branches on mode. Dynamic is a DEFINED BOUNDARY for Spec 3,
    # not a throwing stub on a reachable path: no Package 2A caller can issue a
    # Dynamic accept because no route reaches any of this.
    if challenge.challenge_mode != MODE_LOCKED:
        raise UnsupportedModeError(
            f"Challenge {challenge_id} is mode {challenge.challenge_mode!r}. Only "
            f"Locked acceptance exists; the Dynamic Handshake is Spec 3's."
        )

    # §8 — who may accept depends on the state, because a counter hands the
    # decision back to the original issuer.
    if challenge.response_status == OFFERED:
        _require_actor(actor_team_id, challenge.challenged_team_id, "accept", OFFERED)
    else:                                    # COUNTERED
        _require_actor(actor_team_id, challenge.challenger_team_id, "accept", COUNTERED)

    active = _active_proposal(db, challenge)
    if active is None:
        raise InvalidTransitionError(
            f"Challenge {challenge_id} has no active proposal to accept.")

    moment = _now(now)
    if moment >= effective_deadline(active.created_at, active.proposal_lock_at):
        raise DeadlinePassedError(
            f"The active proposal's deadline has passed; challenge {challenge_id} "
            f"can no longer be accepted."
        )

    challenge.accepted_proposal_id = active.id
    challenge.response_status      = ACCEPTED
    challenge.updated_at           = moment
    db.flush()

    return TransitionResult(
        challenge_id         = challenge.id,
        response_status      = ACCEPTED,
        active_proposal_id   = active.id,
        accepted_proposal_id = active.id,
        version_number       = active.version_number,
        changed              = True,
        replayed             = False,
        detail               = "accepted",
    )


# ── §7.4 Terminal transitions ─────────────────────────────────────────────────

def decline_challenge(
    *,
    challenge_id: int,
    actor_team_id: int,
    db: Session,
    now: Optional[datetime] = None,
) -> TransitionResult:
    """§7.4 — an explicit decline. Recipient from `offered`; the ORIGINAL ISSUER
    from `countered`, because a counter hands the decision back to them (§8).

    SEAM TO PACKAGE 2B (A5/A6): the refund, this state transition and the audit
    record commit together. Package 2A performs no refund.
    """
    challenge = _lock_challenge(db, challenge_id)

    if challenge.response_status in NEGOTIATION_TERMINAL:
        return _closed(challenge, f"already {challenge.response_status}")
    if challenge.response_status == ACCEPTED:
        return _closed(challenge, "already accepted")

    if challenge.response_status == OFFERED:
        _require_actor(actor_team_id, challenge.challenged_team_id, "decline", OFFERED)
    else:                                    # COUNTERED
        _require_actor(actor_team_id, challenge.challenger_team_id, "decline", COUNTERED)

    moment = _now(now)
    challenge.response_status = DECLINED
    challenge.updated_at      = moment
    db.flush()

    return TransitionResult(
        challenge_id         = challenge.id,
        response_status      = DECLINED,
        active_proposal_id   = challenge.active_proposal_id,
        accepted_proposal_id = None,
        version_number       = None,
        changed              = True,
        replayed             = False,
        detail               = "declined",
    )


def cancel_challenge(
    *,
    challenge_id: int,
    actor_team_id: int,
    db: Session,
    now: Optional[datetime] = None,
) -> TransitionResult:
    """§7.4 — issuer withdrawal. Canonical `cancelled`, not a new "withdrawn".

    ISSUER ONLY, AND ONLY FROM `offered` (§8). Once a counter is on the table the
    negotiation belongs to the recipient's offer, and §8 grants cancel at no
    other state — so a countered challenge cannot be cancelled by anyone.

    SEAM TO PACKAGE 2B (A5/A6): refund + transition + audit commit together.
    """
    challenge = _lock_challenge(db, challenge_id)

    if challenge.response_status in NEGOTIATION_TERMINAL:
        return _closed(challenge, f"already {challenge.response_status}")
    if challenge.response_status == ACCEPTED:
        return _closed(challenge, "already accepted")
    if challenge.response_status == COUNTERED:
        raise InvalidTransitionError(
            f"Challenge {challenge_id} has been countered; §8 grants cancel only "
            f"from 'offered'. The issuer may accept or decline the counter."
        )

    _require_actor(actor_team_id, challenge.challenger_team_id, "cancel", OFFERED)

    moment = _now(now)
    challenge.response_status = CANCELLED
    challenge.updated_at      = moment
    db.flush()

    return TransitionResult(
        challenge_id         = challenge.id,
        response_status      = CANCELLED,
        active_proposal_id   = challenge.active_proposal_id,
        accepted_proposal_id = None,
        version_number       = None,
        changed              = True,
        replayed             = False,
        detail               = "cancelled",
    )


def expire_challenge(
    *,
    challenge_id: int,
    db: Session,
    now: Optional[datetime] = None,
) -> TransitionResult:
    """§7.4 — the system expiry transition. TTL or kickoff lapse.

    SYSTEM-OWNED: there is no actor argument, because expiry is not something a
    team does. §7.4 requires it be "driven by a scheduled job + response-path
    invocation, NEVER by list reads" — so this module contains no read path that
    mutates state, and this is the only writer of `expired`.

    Refuses BEFORE the effective deadline. Expiring early would destroy a live
    negotiation, so an early call is a refusal rather than a no-op.

    SEAM TO PACKAGE 2B (A5/A6): the refund, the reconciliation of actual
    challenge escrow against the expected funded Anchor — fail-closed on
    missing/partial — and this transition commit together. That reconciliation
    body is 2B's; Package 2A defines the resulting state.
    """
    challenge = _lock_challenge(db, challenge_id)

    if challenge.response_status in NEGOTIATION_TERMINAL:
        return _closed(challenge, f"already {challenge.response_status}")
    if challenge.response_status == ACCEPTED:
        # An accepted wager is never expired by the negotiation clock (§4).
        return _closed(challenge, "already accepted")

    active = _active_proposal(db, challenge)
    if active is None:
        raise InvalidTransitionError(
            f"Challenge {challenge_id} has no active proposal, so it has no "
            f"deadline to have passed.")

    moment   = _now(now)
    deadline = effective_deadline(active.created_at, active.proposal_lock_at)
    if moment < deadline:
        raise DeadlineNotReachedError(
            f"Challenge {challenge_id}'s effective deadline is {deadline.isoformat()} "
            f"and it is {moment.isoformat()}. Refusing to expire a live negotiation."
        )

    challenge.response_status = EXPIRED
    challenge.updated_at      = moment
    db.flush()

    return TransitionResult(
        challenge_id         = challenge.id,
        response_status      = EXPIRED,
        active_proposal_id   = challenge.active_proposal_id,
        accepted_proposal_id = None,
        version_number       = None,
        changed              = True,
        replayed             = False,
        detail               = "expired",
    )


# ── §8 Revive ─────────────────────────────────────────────────────────────────

def revive_challenge(
    *,
    challenge_id: int,
    actor_team_id: int,
    terms: ProposalTerms,
    db: Session,
    proposal_lock_at: Optional[datetime] = None,
    schedule_source_ref: Optional[str] = None,
    now: Optional[datetime] = None,
) -> TransitionResult:
    """§8 — revive produces an entirely NEW challenge. It is not a lifecycle edge.

    "Original issuer only; produces a new challenge ID, new proposal ID, fresh
    timestamps/odds/stakes/starters/escrow; no relationship reopening the old
    record." The old challenge stays terminal and is NOT modified by this call —
    not its status, not its pointers, not its proposals. The only link is the
    optional `revived_from_challenge_id` audit lineage on the new row.

    Mode, wager class, participants and week are carried across because they are
    the wager identity being re-offered; everything else is freshly frozen.
    """
    old = _lock_challenge(db, challenge_id)

    if old.response_status not in NEGOTIATION_TERMINAL:
        raise InvalidTransitionError(
            f"Challenge {challenge_id} is {old.response_status!r}; only a challenge "
            f"terminal for negotiation ({', '.join(NEGOTIATION_TERMINAL)}) may be "
            f"revived. An accepted challenge is a live wager, not a dead one."
        )
    _require_actor(actor_team_id, old.challenger_team_id, "revive", old.response_status)

    # A fresh issue in every respect. The old row is read for identity only and
    # is never written to.
    return issue_proposal_challenge(
        league_id                 = old.league_id,
        week                      = old.week,
        challenger_team_id        = old.challenger_team_id,
        challenged_team_id        = old.challenged_team_id,
        challenge_mode            = old.challenge_mode,
        wager_type                = old.wager_type,
        terms                     = terms,
        db                        = db,
        proposal_lock_at          = proposal_lock_at,
        schedule_source_ref       = schedule_source_ref,
        now                       = now,
        revived_from_challenge_id = old.id,
    )