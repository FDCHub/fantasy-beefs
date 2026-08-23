"""
economy/top_off.py — B6 §15 Group E item 18: the BAB Top-Off issuance service.

THE PRODUCT FLOW, WHOLE. A GM asks his league for more Credits. An authorized
commissioner of that league approves. In ONE transaction the system posts two
balanced ledger legs, credits the GM's Wallet mirror from the ledger's own
post-state, writes a durable disclosure record, records who asked and who
decided, and commits once. No real money is involved anywhere in this file; no
Stripe path exists on it.

SCOPE FENCE. This module provides EXACTLY FOUR service entry points and nothing
else:

    create_top_off_request()   §7.3 outcome 1 — creation-time refusals
    approve_top_off()          §8.2 — the twenty-step sequence
    reject_top_off()           §7.2 — pending -> rejected
    cancel_top_off()           §7.2 — pending -> cancelled

It implements NONE of the following, and no future edit may quietly add them
here — they are Group F (§15 item 19-21):

    - routes: nothing here is registered in api/main.py;
    - Pydantic request/response models or `extra="forbid"` bodies;
    - HTTP status mapping (the caller maps the exception TYPES below);
    - the migration;
    - legacy closure of confirm_topup / create_bet_topup / create_waiver_topup;
    - step 20's asynchronous feed publication.

ONE ISSUANCE IMPLEMENTATION. The ledger posting is delegated to the accepted
Group A seam, ledger.post(), with session=db. This module never constructs a
LedgerEntry, never calls post(session=None), and never re-derives a balance
outside the caller's transaction.

TRANSACTION OWNERSHIP (decided, following the Group B/D precedent). Every entry
point TAKES OWNERSHIP of the supplied session's transaction: it commits on its
one writing path and rolls back on every other terminal path, including every
abort and every unexpected error. No caller may pass a session carrying
uncommitted work it expects to survive the call. Locked rows are re-populated
from the database (see THE STALE-ATTRIBUTE HAZARD), so a caller must also not
expect its own pending edits to those rows to survive.

COMMIT COUNT (§8.3, decided). Approve-and-post: exactly 1. Terminal rejection:
exactly 1. Cancel: exactly 1. Every abort (§7.3 outcomes 3-7): exactly 0.

ISOLATION (§8.4). READ COMMITTED, inherited from the caller. Never elevated by
this module. Correctness rests on the three explicit row locks below, not on the
isolation level — and elevating would convert benign replays into IntegrityError
exactly as it would in season_allocation.py.

LOCK ORDER IS FIXED AND GLOBAL (§8.1, invariant 35)

    1. FaabTransaction request row   FOR UPDATE   serializes approval of the SAME request
    2. SeasonAllocation row          FOR UPDATE   serializes approvals against ONE team-season cap
    3. League row                    FOR UPDATE   season-close predicate AND authority-removal race

Every path that takes any SUBSET takes it in that order: approve takes 1-2-3,
reject and cancel take 1 then 3, create takes none. No reverse-order cycle is
constructible, so no deadlock is either. activate_season_allocation() takes only
the League row and takes it FIRST, and it can only INSERT allocation rows where
none exist while approval can only LOCK an allocation row that does exist — the
two write sets are mutually exclusive on the same key, which is why the apparent
inversion is not constructible (the same reasoning recorded at
economy/season_allocation.py's lock site).

LOCK 3 IS HELD THROUGH COMMIT (§15 item 17, §6.2, invariants 22-23). Approval
acquires the League row at step 14 and does not release it until the commit at
step 19. Releasing earlier would reopen the exact window the lock exists to
close: a revocation landing between revalidation and commit would leave a
committed issuance whose approver was already revoked. Every refusal at or after
step 14 rolls back immediately, so the row is released at the refusal rather
than at request teardown.

THE STALE-ATTRIBUTE HAZARD (load-bearing, not tidiness). SQLAlchemy's identity
map returns an ALREADY-LOADED instance without refreshing its attributes, even
when the SELECT that produced it was re-executed FOR UPDATE. Step 5 reads the
League row unlocked; step 14 locks it. Without populate_existing() on the step-14
query, step 14 would revalidate against the attribute values step 5 loaded — and
a season closed in between would be invisible. The season-close revalidation, the
whole point of taking the lock, would silently pass. Every locking query in this
module therefore calls populate_existing(), so what is validated under a lock is
what the database holds under that lock.

THE SEVEN OUTCOMES (§7.3) — only ONE writes a state transition

    1 creation-time refusal      CreationRefused        no row created
    2 terminal rejection         (returns a result)     pending -> rejected, ONE commit
    3 authorization-attempt      AuthorizationAttemptAbort   stays pending, 0 commits
    4 integrity-attempt          IntegrityAttemptAbort       stays pending, 0 commits
    5 attempt-validation         AttemptValidationAbort      stays pending, 0 commits
    6 season-close abort         SeasonClosedAbort           stays pending, 0 commits
    7 terminal-state no-op       (returns the original)      unchanged, 0 commits

The dividing line, every time (§7.3): did the REQUEST become independently
invalid, or did a particular ATTEMPT fail for a reason extrinsic to the request?
Only the first writes `rejected`. A corrupt snapshot, a revoked approver, a
closed season and a missing config row are all ABORTS — never a rejection of the
GM's request (invariant 32).

SELF-APPROVAL (§5.2, invariants 18-21). Any authorized commissioner of the
league may approve their own top-off. NO CODE PATH IN THIS MODULE COUNTS,
QUERIES OR COMPARES OTHER COMMISSIONERS for the purpose of deciding whether an
approval is permitted — there is no independent-commissioner predicate here, and
adding one would reintroduce the rule §0.1 superseded. Classification is one
comparison, requester_user_id == decided_by_user_id, written once. The only
additional control is a mandatory non-empty decision_reason, and the frozen cap,
posting shape and disclosure obligation are identical either way.

THE CAP IS FROZEN, AND READ FROM FROZEN ROWS ONLY (§2.6, invariant 29). Approval
reads SeasonAllocation.min_reserve_cents from the row-locked allocation record and
league_season_topoff_config.topoff_cap_multiplier_bps from the single
league-season row. Never from payments/economy_config.py. Never from
League.topoff_cap_multiplier_bps, which is the editable pre-activation dial and
may have moved since activation.

THE WALLET MIRROR IS A COMPATIBILITY VIEW, NOT THE MONEY (§3.6, invariant 12).
The ledger is authoritative and stores INTEGER CENTS. Wallet.balance is the
pre-existing DOLLAR-denominated Float mirror, and the funding gates that read it
— validate_bet_amount() and beef_engine's balance check — interpret it as
dollars. The conversion from ledger cents happens EXACTLY ONCE, here, at step 16.
Writing raw cents into that column would multiply every reader's view of the
GM's balance by one hundred and let him stake a hundred times what he holds. The
mirror is recomputed from the ledger post-state, never incremented, never
derived from the legacy float FaabTransaction.amount, and never derived from its
own prior value.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from auth.allocation_gate import is_league_commissioner
from db.schema import (
    FaabTransaction,
    League,
    LeagueSeasonTopoffConfig,
    SeasonAllocation,
    Team,
    TopOffDisclosure,
    User,
    Wallet,
)
from economy.economy_events import fantasystakes_championship_account
from economy.season_close import is_season_closed
from ledger.ledger import (
    APPROVED_BAB_TOPOFF_DOOR,
    _balance_of_in_session,
    _dollars_to_cents,
    post as ledger_post,
)
from ruleset import is_final_por

# The one request type B6 governs. Legacy topup_waiver rows are dormant history
# (§11.5) and are never reachable from any function here.
TOPUP_BET = "topup_bet"

# The partial unique index from db/schema.py, named here so the create path can
# classify ONE IntegrityError narrowly and re-raise every other. Named as a
# module constant rather than spelled at the call site so the two cannot drift.
PENDING_REQUEST_INDEX = "uq_faab_tx_one_open_topoff"

# Distinct machine-readable causes for a creation-time refusal (§7.3 outcome 1).
# §2.10 requires the THREE zero-headroom causes to stay distinct and never be
# merged, and §10.1 maps them to three separate reason codes; they are separated
# HERE, at the only place that can tell them apart, so the Group F route layer
# reports them without re-deriving anything.
REASON_INVALID_AMOUNT     = "invalid_amount"       # sub-cent, zero or negative
REASON_TEAM_NOT_IN_LEAGUE = "team_not_in_league"
REASON_SEASON_CLOSED      = "season_closed"
REASON_NO_ALLOCATION      = "no_allocation"        # zero-headroom cause 2
REASON_MULTIPLIER_ZERO    = "multiplier_zero"      # zero-headroom cause 1
REASON_CAP_EXHAUSTED      = "cap_exhausted"        # zero-headroom cause 3
REASON_OVER_CAPACITY      = "over_capacity"
REASON_OPEN_REQUEST       = "open_request_exists"


# ── Errors ────────────────────────────────────────────────────────────────────

class TopOffError(ValueError):
    """Base for every top-off domain refusal. Subclasses are distinct TYPES so
    callers and tests branch on type, never on message text."""


class RequestNotFoundError(TopOffError):
    """No FaabTransaction top-off request with that id. Distinct from an
    authorization failure so the route layer can answer 404 rather than 403
    (§10.1) without inspecting a message."""


class CreationRefused(TopOffError):
    """§7.3 outcome 1 — a creation-time refusal. NO ROW IS CREATED.

    `reason_code` is one of the REASON_* constants and `remaining_capacity_cents`
    is populated on the capacity-related causes, so the route layer can state
    remaining capacity on a 422 (§10.1) without recomputing the cap.
    """

    def __init__(self, message: str, reason_code: str,
                 remaining_capacity_cents: int | None = None):
        super().__init__(message)
        self.reason_code = reason_code
        self.remaining_capacity_cents = remaining_capacity_cents


class AuthorizationAttemptAbort(TopOffError):
    """§7.3 outcome 3 — the approver no longer holds a league_commissioners row
    for this league, the path league and the persisted request league disagree,
    or another genuine league-scoped authority failure. The ATTEMPT failed; the
    request did not become invalid, so it stays `pending` and remains decidable
    by anyone who still holds authority. Nothing is written."""


class IntegrityAttemptAbort(TopOffError):
    """§7.3 outcome 4 — frozen state is missing, mismatched or corrupt: no
    allocation row, no config snapshot, a cap that is not exact-cent, or two cap
    derivations that disagree. Refused without mutation and WITHOUT rejecting
    the GM's request (invariant 32): corrupt state is not his fault and rewriting
    his request to `rejected` would assert a decision nobody made."""


class AttemptValidationAbort(TopOffError):
    """§7.3 outcome 5 — a self-approval arrived with a missing, blank or
    whitespace-only decision_reason. The mandatory reason is one of the
    structural compensating controls that stand in for independent review
    (§5.4), so this is a refusal, not a warning."""


class SeasonClosedAbort(TopOffError):
    """§7.3 outcome 6 — League.season_closed_at was non-NULL at the preliminary
    check (step 5) or at the authoritative revalidation under the League lock
    (step 14). The request stays `pending`: a request never decided before close
    is a true statement about what happened, and rewriting it would not be
    (§7.5)."""


# ── Results ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CapState:
    """The frozen cap and its consumption for one (league, team, season), as
    computed under the allocation-row lock. Every field is integer cents except
    the multiplier, which is basis points."""
    min_reserve_cents:       int
    multiplier_bps:     int
    cap_cents:          int
    prior_issued_cents: int
    remaining_cents:    int


@dataclass(frozen=True)
class TopOffRequestResult:
    """What one creation produced. `remaining_capacity_cents` is the headroom
    AFTER this request would be issued in full — reported, never stored, because
    only issued Credits consume cap (§2.10) and a pending request consumes none."""
    request_id:               int
    league_id:                int
    team_id:                  int
    season:                   int
    requester_user_id:        int
    amount_cents:             int
    decision:                 str
    status:                   str
    cap_cents:                int
    remaining_capacity_cents: int


@dataclass(frozen=True)
class TopOffDecisionResult:
    """What one decision (or one terminal-state replay) produced.

    `posted` is True only on the approve-and-post path. `replayed` is True only
    on §7.3 outcome 7, where the caller re-decided an already-terminal request:
    the ORIGINAL outcome is returned, reconstructed from the persisted row, and
    nothing at all is written.
    """
    request_id:               int
    league_id:                int
    team_id:                  int
    season:                   int
    amount_cents:             int
    requester_user_id:        int
    decision:                 str
    status:                   str
    decided_by_user_id:       int | None
    decided_at:               datetime | None
    self_approved:            bool | None
    decision_reason:          str | None
    ledger_posting_id:        uuid.UUID | None
    disclosure_event_id:      uuid.UUID | None
    cap_cents:                int | None
    prior_issued_cents:       int | None
    remaining_capacity_cents: int | None
    posted:                   bool
    replayed:                 bool


# ── Cap arithmetic (§2.7) ─────────────────────────────────────────────────────

def compute_cap_cents(min_reserve_cents: int, multiplier_bps: int) -> int:
    """The frozen per-GM season cap, in integer cents (§2.7).

    THE ANCHOR IS THE WALLET ALLOCATION — not the buy-in, not the championship
    reserve.

    The divisibility check runs BEFORE the floor division, every time, without
    exception. A remainder is NEVER a rounding opportunity: it is proof that the
    frozen state which produced it is corrupt, because every certified anchor is
    a multiple of 100 cents and every permitted multiplier a multiple of 100 bps,
    so all 25 lawful combinations divide exactly. Flooring an inexact cap would
    silently invent a cap nobody certified.
    """
    product = min_reserve_cents * multiplier_bps
    if product % 10000 != 0:
        raise IntegrityAttemptAbort(
            f"Cap arithmetic is not exact-cent: min_reserve_cents={min_reserve_cents} * "
            f"multiplier_bps={multiplier_bps} = {product}, which is not divisible "
            f"by 10000 (remainder {product % 10000}). Refusing to floor, truncate "
            f"or round — a remainder here means the frozen snapshot is corrupt, "
            f"not that a cap needs rounding."
        )
    return product // 10000


def _issued_from_ledger(db: Session, league_id: int, team_id: int, season: int) -> int:
    """PRIMARY cap-consumption derivation (§2.9), ledger-proven.

    Sums the WALLET legs of postings made under the canonical top-off door whose
    sibling leg is this league-season's issuance account. Both conditions are
    required: the door alone would also match a top-off issued for this team in
    another league-season, and the account alone would match the season
    allocation's own wallet credit.

    Read through the CALLER's session so it sees the caller's own uncommitted
    work and is covered by the allocation-row lock held around it.
    """
    result = db.execute(
        text(
            "SELECT COALESCE(SUM(w.amount_cents), 0) "
            "FROM ledger_entries w "
            "WHERE w.account = :wallet_account "
            "  AND w.door    = :door "
            "  AND EXISTS (SELECT 1 FROM ledger_entries s "
            "              WHERE s.posting_id = w.posting_id "
            "                AND s.account    = :issuance_account)"
        ),
        {
            "wallet_account":   f"wallet:{team_id}",
            "door":             APPROVED_BAB_TOPOFF_DOOR,
            "issuance_account": f"bab_issuance:{league_id}:{season}",
        },
    ).scalar()
    return int(result or 0)


def _issued_from_requests(db: Session, team_id: int, season: int) -> int:
    """SECONDARY cap-consumption derivation (§2.9), request-proven.

    Sums amount_cents over this team's APPLIED top-off requests for the season
    that carry a posting claim. §2.9 states these exact predicates and does not
    qualify by league — it does not need to, because a Team belongs to exactly
    one League, so team_id already determines it.

    The linkage biconditional (§4.4) is what makes this 1:1 with the ledger
    derivation: an applied row cannot exist without its posting, and a posting
    cannot be claimed twice (ledger_posting_id is unique when non-null).
    """
    result = db.query(func.coalesce(func.sum(FaabTransaction.amount_cents), 0)).filter(
        FaabTransaction.team_id           == team_id,
        FaabTransaction.season            == season,
        FaabTransaction.type              == TOPUP_BET,
        FaabTransaction.status            == "applied",
        FaabTransaction.ledger_posting_id.isnot(None),
    ).scalar()
    return int(result or 0)


def _read_cap_state(
    db: Session,
    league_id: int,
    team_id: int,
    season: int,
    allocation: SeasonAllocation,
) -> CapState:
    """Steps 8-12: the frozen cap and its consumption.

    `allocation` is passed in already locked on the approval path; the creation
    path passes an unlocked read, because creation's capacity check is a courtesy
    that approval re-runs authoritatively under lock (§2.10, "Re-check at
    approval: mandatory").

    NEITHER DERIVATION IS A CACHED COUNTER. Both are recomputed from
    authoritative state on every call, and they must AGREE — a disagreement means
    the ledger and the request table describe different histories, which is an
    integrity-attempt abort and never a silent choice of one over the other.
    """
    # Step 8 — the frozen anchor, from the allocation row.
    min_reserve_cents = allocation.min_reserve_cents
    if min_reserve_cents is None or min_reserve_cents <= 0:
        raise IntegrityAttemptAbort(
            f"SeasonAllocation for league {league_id}, team {team_id}, season "
            f"{season} carries min_reserve_cents={min_reserve_cents!r}, which cannot anchor "
            f"a cap. Refusing to compute one."
        )

    # Step 9 — the frozen multiplier, from the single league-season row.
    # one_or_none(): uq_lstc_league_season makes a second row impossible, so if
    # one ever appears it is exactly the corruption this module refuses to paper
    # over and MultipleResultsFound must propagate rather than be narrowed away.
    frozen = (
        db.query(LeagueSeasonTopoffConfig)
        .filter(
            LeagueSeasonTopoffConfig.league_id == league_id,
            LeagueSeasonTopoffConfig.season    == season,
        )
        .one_or_none()
    )
    if frozen is None:
        raise IntegrityAttemptAbort(
            f"League {league_id} has NO frozen top-off multiplier row in "
            f"league_season_topoff_config for season {season}. The season is "
            f"half-activated and no cap can be computed. The request is untouched "
            f"and remains pending — a missing snapshot is not the requester's "
            f"fault and never rejects his request."
        )

    # Steps 10-11 — divisibility, then the cap.
    cap_cents = compute_cap_cents(min_reserve_cents, frozen.topoff_cap_multiplier_bps)

    # Step 12 — both derivations, under whatever lock the caller holds.
    from_ledger   = _issued_from_ledger(db, league_id, team_id, season)
    from_requests = _issued_from_requests(db, team_id, season)
    if from_ledger != from_requests:
        raise IntegrityAttemptAbort(
            f"The two cap-consumption derivations DISAGREE for league "
            f"{league_id}, team {team_id}, season {season}: ledger-proven "
            f"{from_ledger} cents, request-proven {from_requests} cents. The "
            f"linkage biconditional makes these 1:1 by construction, so a "
            f"difference is unresolved historical indeterminacy. Refusing to "
            f"pick one."
        )

    remaining = cap_cents - from_ledger
    if remaining < 0:
        raise IntegrityAttemptAbort(
            f"League {league_id}, team {team_id}, season {season} has already "
            f"been issued {from_ledger} cents against a frozen cap of "
            f"{cap_cents} cents. Historical over-issuance is corruption, not a "
            f"headroom calculation. Refusing to proceed."
        )

    return CapState(
        min_reserve_cents       = min_reserve_cents,
        multiplier_bps     = frozen.topoff_cap_multiplier_bps,
        cap_cents          = cap_cents,
        prior_issued_cents = from_ledger,
        remaining_cents    = remaining,
    )


# ── Shared helpers ────────────────────────────────────────────────────────────

def _lock_request(db: Session, request_id: int) -> FaabTransaction:
    """LOCK 1. The FIRST database statement of every decision path.

    populate_existing() is load-bearing — see THE STALE-ATTRIBUTE HAZARD in the
    module docstring. Without it a caller who had already loaded this row would
    have its cached `decision`/`status` re-used, and the step-3 re-read "under
    the lock" would be a re-read of nothing.
    """
    return (
        db.query(FaabTransaction)
        .filter(FaabTransaction.id == request_id)
        .with_for_update()
        .populate_existing()
        .first()
    )


def _lock_league(db: Session, league_id: int) -> League:
    """LOCK 3 (§15 item 17). PLAIN FOR UPDATE — key_share=True is deliberately
    NOT passed.

    §6.4 assigns every authority writer and the season-close writer this exact
    mode, so approval conflicts with all of them in both directions. The weaker
    FOR NO KEY UPDATE that activation takes would still conflict with those, but
    taking it here would be a downgrade with nothing to gain: this path inserts
    no row referencing the league, so it has no FK-child reason to want it.

    populate_existing() again: step 5 already loaded this row unlocked, and
    without a refresh step 14 would revalidate the step-5 snapshot.
    """
    return (
        db.query(League)
        .filter(League.id == league_id)
        .with_for_update()
        .populate_existing()
        .first()
    )


def _require_open_topoff(
    request: FaabTransaction | None,
    request_id: int,
    league_id: int,
) -> None:
    """Existence and identity checks common to every decision path.

    The path league versus persisted league comparison is §8.2 step 6's, and it
    is an AUTHORIZATION failure, not a not-found: the caller proved authority for
    the league in the path, and that authority says nothing about the league the
    request actually belongs to. Answering 404 here would also let a commissioner
    of one league probe request ids in another.
    """
    if request is None:
        raise RequestNotFoundError(
            f"No top-off request {request_id} exists."
        )
    if request.type != TOPUP_BET:
        raise RequestNotFoundError(
            f"FaabTransaction {request_id} is a {request.type!r} row, not a B6 "
            f"top-off request. Legacy rows are dormant history and are never "
            f"decidable through this service."
        )
    if request.league_id != league_id:
        raise AuthorizationAttemptAbort(
            f"Top-off request {request_id} belongs to league "
            f"{request.league_id}, not to league {league_id} from the path. "
            f"Authority is league-scoped and grants nothing here."
        )


def _replay_result(request: FaabTransaction) -> TopOffDecisionResult:
    """§7.3 outcome 7 — the terminal-state no-op. Returns the ORIGINAL outcome,
    reconstructed from the persisted row. Nothing is written and nothing is
    committed; a second approve of an applied request must post nothing (§8.5)."""
    return TopOffDecisionResult(
        request_id               = request.id,
        league_id                = request.league_id,
        team_id                  = request.team_id,
        season                   = request.season,
        amount_cents             = request.amount_cents,
        requester_user_id        = request.requester_user_id,
        decision                 = request.decision,
        status                   = request.status,
        decided_by_user_id       = request.decided_by_user_id,
        decided_at               = request.decided_at,
        self_approved            = request.self_approved,
        decision_reason          = request.decision_reason,
        ledger_posting_id        = request.ledger_posting_id,
        disclosure_event_id      = request.disclosure_event_id,
        cap_cents                = None,
        prior_issued_cents       = None,
        remaining_capacity_cents = None,
        posted                   = False,
        replayed                 = True,
    )


def _reason_is_present(decision_reason: str | None) -> bool:
    """A decision_reason that satisfies §5.3's non-empty requirement.

    str.strip() removes every kind of whitespace, so this is at least as strict
    as ck_topoff_disclosure_selfapproval_reason, which folds tab/newline/carriage
    return to spaces before trimming. Being the stricter of the two is
    deliberate: the database CHECK is the last line of defence and must never be
    the thing that reports this to a user.
    """
    return decision_reason is not None and decision_reason.strip() != ""


# ── Creation (§7.3 outcome 1) ─────────────────────────────────────────────────

def create_top_off_request(
    league_id: int,
    team_id: int,
    requester_user_id: int,
    amount_dollars: float,
    db: Session,
) -> TopOffRequestResult:
    """Create one `pending` top-off request. ONE commit on success, zero on every
    refusal.

    §7.3 outcome 1 lists the creation-time refusals: season closed; no
    SeasonAllocation row; sub-cent, zero or negative amount; over remaining
    capacity at creation; an open request already exists. Each raises
    CreationRefused carrying a distinct reason_code and NO ROW IS CREATED.

    CONVERSION IS `_dollars_to_cents` ONLY (invariant 7). `_to_cents` rounds and
    is prohibited on this path; it is not imported into this module at all.
    amount_cents is the sole authoritative amount, and the legacy float `amount`
    is written FROM it for display, never the reverse (§4.3).

    NO LOCK IS TAKEN. §8.5 assigns duplicate-creation prevention to the partial
    unique index rather than to a lock, and the capacity check here is a courtesy
    that approval re-runs authoritatively under lock 2 (§2.10). Taking a lock
    here would add an ordering obligation for no correctness gain.
    """
    try:
        # Amount first, in memory, so a malformed request costs no database work.
        try:
            amount_cents = _dollars_to_cents(amount_dollars)
        except ValueError as exc:
            raise CreationRefused(str(exc), REASON_INVALID_AMOUNT) from exc
        if amount_cents <= 0:
            raise CreationRefused(
                f"A top-off must be a positive amount; got {amount_dollars!r} "
                f"({amount_cents} cents).",
                REASON_INVALID_AMOUNT,
            )

        season = config.ALLOCATION_SEASON

        team = db.query(Team).filter(Team.id == team_id).first()
        if team is None or team.league_id != league_id:
            raise CreationRefused(
                f"Team {team_id} is not a team of league {league_id}.",
                REASON_TEAM_NOT_IN_LEAGUE,
            )

        league = db.query(League).filter(League.id == league_id).first()
        if league is None:
            raise CreationRefused(
                f"League {league_id} does not exist.",
                REASON_TEAM_NOT_IN_LEAGUE,
            )
        if is_season_closed(league):
            raise CreationRefused(
                f"League {league_id}'s season {season} closed at "
                f"{league.season_closed_at}. No top-off request may be created "
                f"after close.",
                REASON_SEASON_CLOSED,
            )

        if db.query(User).filter(User.id == requester_user_id).first() is None:
            raise CreationRefused(
                f"User {requester_user_id} does not exist.",
                REASON_TEAM_NOT_IN_LEAGUE,
            )

        allocation = (
            db.query(SeasonAllocation)
            .filter(
                SeasonAllocation.league_id == league_id,
                SeasonAllocation.team_id   == team_id,
                SeasonAllocation.season    == season,
            )
            .one_or_none()
        )
        if allocation is None:
            # Zero-headroom cause 2, kept distinct from an exhausted cap and from
            # a zero multiplier (§2.10): "no valid allocation" is an unactivated
            # season, which the commissioner fixes differently.
            raise CreationRefused(
                f"League {league_id}, team {team_id} has no season-{season} "
                f"allocation, so no top-off cap exists to draw against.",
                REASON_NO_ALLOCATION,
            )

        cap = _read_cap_state(db, league_id, team_id, season, allocation)

        if cap.cap_cents == 0:
            # Zero-headroom cause 1 — the league froze a 0 bps multiplier, which
            # is a lawful choice meaning "no top-offs this season".
            raise CreationRefused(
                f"League {league_id} froze a top-off multiplier of 0 bps for "
                f"season {season}, so the cap is 0 cents and no top-off can be "
                f"issued.",
                REASON_MULTIPLIER_ZERO,
                remaining_capacity_cents=0,
            )
        if cap.remaining_cents == 0:
            # Zero-headroom cause 3 — the cap exists and is fully consumed.
            raise CreationRefused(
                f"Team {team_id} has already been issued the full season-{season} "
                f"cap of {cap.cap_cents} cents. No capacity remains.",
                REASON_CAP_EXHAUSTED,
                remaining_capacity_cents=0,
            )
        if amount_cents > cap.remaining_cents:
            # Rejected in FULL. No partial approval and no auto-reduction ever
            # (§2.10) — silently shrinking a request would answer a question the
            # GM did not ask.
            raise CreationRefused(
                f"Requested {amount_cents} cents exceeds the remaining "
                f"season-{season} capacity of {cap.remaining_cents} cents "
                f"(frozen cap {cap.cap_cents}, already issued "
                f"{cap.prior_issued_cents}). Rejected in full; top-offs are never "
                f"partially approved.",
                REASON_OVER_CAPACITY,
                remaining_capacity_cents=cap.remaining_cents,
            )

        # Fast-path duplicate check, for a clean refusal in the ordinary
        # sequential case. It is NOT the guarantee — two concurrent creates can
        # both pass it, and the partial unique index below is what makes exactly
        # one of them survive.
        open_existing = (
            db.query(FaabTransaction)
            .filter(
                FaabTransaction.league_id == league_id,
                FaabTransaction.team_id   == team_id,
                FaabTransaction.season    == season,
                FaabTransaction.type      == TOPUP_BET,
                FaabTransaction.status    == "pending",
            )
            .first()
        )
        if open_existing is not None:
            raise CreationRefused(
                f"Team {team_id} already has an open top-off request "
                f"({open_existing.id}) for season {season}. Decide or cancel it "
                f"before opening another.",
                REASON_OPEN_REQUEST,
            )

        row = FaabTransaction(
            league_id         = league_id,
            team_id           = team_id,
            type              = TOPUP_BET,
            amount            = amount_cents / 100.0,   # display only (§4.3)
            amount_cents      = amount_cents,           # sole authoritative amount
            season            = season,
            status            = "pending",
            decision          = "pending",
            requester_user_id = requester_user_id,
        )
        db.add(row)

        try:
            # Force the INSERT — and therefore the partial unique index — to be
            # evaluated inside this transaction rather than at commit time, so
            # the classification below runs while the session is still ours.
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            # NARROW CLASSIFICATION. Only the named open-request index becomes a
            # duplicate refusal. Converting every IntegrityError would report a
            # foreign-key violation or a CHECK failure as "you already have an
            # open request", hiding a real defect behind a benign refusal.
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint != PENDING_REQUEST_INDEX:
                raise
            raise CreationRefused(
                f"Team {team_id} already has an open top-off request for season "
                f"{season}; a concurrent create won the race.",
                REASON_OPEN_REQUEST,
            ) from exc

        db.commit()      # the one and only commit on this path

        return TopOffRequestResult(
            request_id               = row.id,
            league_id                = league_id,
            team_id                  = team_id,
            season                   = season,
            requester_user_id        = requester_user_id,
            amount_cents             = amount_cents,
            decision                 = "pending",
            status                   = "pending",
            cap_cents                = cap.cap_cents,
            remaining_capacity_cents = cap.remaining_cents - amount_cents,
        )

    except Exception:
        db.rollback()
        raise


# ── Approval — the twenty steps (§8.2) ────────────────────────────────────────

def approve_top_off(
    league_id: int,
    request_id: int,
    decided_by_user_id: int,
    decision_reason: str | None = None,
    db: Session = None,
) -> TopOffDecisionResult:
    """Approve one top-off request and issue the Credits, or refuse.

    THE TWENTY-STEP SEQUENCE OF §8.2, in order, with the three locks of §8.1
    taken in the fixed global order. Exactly one commit on the approve-and-post
    path and exactly one on the terminal-rejection path; ZERO on every abort.

    Returns a TopOffDecisionResult. Raises AuthorizationAttemptAbort,
    IntegrityAttemptAbort, AttemptValidationAbort or SeasonClosedAbort — each
    having written nothing and committed nothing, leaving the request `pending`
    and decidable.

    Step 20 — asynchronous publication of the committed disclosure to the
    activity feed — is deliberately NOT here. It sits outside the single
    transaction by definition, and §16 defers the disclosure outbox.
    """
    try:
        # ── 1. LOCK 1 — the request row. FIRST database statement. ──
        request = _lock_request(db, request_id)
        _require_open_topoff(request, request_id, league_id)

        team_id = request.team_id
        season  = request.season
        if season != config.ALLOCATION_SEASON:
            raise IntegrityAttemptAbort(
                f"Top-off request {request_id} is stamped season {season!r}, not "
                f"the allocation season {config.ALLOCATION_SEASON}. A money event "
                f"belongs to exactly one season and this one cannot be issued now."
            )

        # ── 2. LOCK 2 — the allocation row. Held through commit. ──
        # Taken BEFORE the state re-read below so the whole cap computation, and
        # the decision that rests on it, happen under one continuous lock.
        allocation = (
            db.query(SeasonAllocation)
            .filter(
                SeasonAllocation.league_id == request.league_id,
                SeasonAllocation.team_id   == team_id,
                SeasonAllocation.season    == season,
            )
            .with_for_update()
            .populate_existing()
            .first()
        )
        if allocation is None:
            raise IntegrityAttemptAbort(
                f"League {request.league_id}, team {team_id} has no season-{season} "
                f"allocation row. The frozen anchor for the cap is missing, so no "
                f"cap can be computed. Request {request_id} is untouched."
            )

        # ── 3. Re-read decision and status UNDER lock 1. ──
        # This is the idempotency mechanism (§8.5): a second approve of a request
        # the winner already applied lands here and posts nothing.
        if request.decision != "pending" or request.status != "pending":
            result = _replay_result(request)
            db.rollback()          # outcome 7 writes nothing and commits nothing
            return result

        # ── 4. The requester identity, from the locked row. ──
        requester_user_id = request.requester_user_id
        if requester_user_id is None:
            raise IntegrityAttemptAbort(
                f"Top-off request {request_id} carries no requester_user_id. A B6 "
                f"request always records who asked; a row without one is legacy or "
                f"corrupt and is not decidable."
            )

        # ── 5. Preliminary season-close check. Fail fast; re-verified at 14. ──
        league = db.query(League).filter(League.id == request.league_id).first()
        if league is None:
            raise IntegrityAttemptAbort(
                f"League {request.league_id} does not exist, yet request "
                f"{request_id} references it."
            )
        if is_season_closed(league):
            raise SeasonClosedAbort(
                f"League {request.league_id}'s season closed at "
                f"{league.season_closed_at}. Approval is an attempt abort: request "
                f"{request_id} remains pending and is never rewritten to rejected."
            )

        # ── 6. Preliminary authority check. ──
        # UNLOCKED and therefore not authoritative — a row-level read is not a
        # serialization point (§6.2). It fails fast so an unauthorized attempt
        # costs no cap computation and never touches the League row; step 14
        # repeats it under the lock, and THAT is the one that governs.
        if not is_league_commissioner(decided_by_user_id, request.league_id, db):
            raise AuthorizationAttemptAbort(
                f"User {decided_by_user_id} holds no commissioner authority for "
                f"league {request.league_id}. Request {request_id} remains pending "
                f"and is still decidable by anyone who does."
            )

        # ── 7. Self-approval classification and controls (§5.2, §5.3). ──
        # ONE comparison. No other commissioner's existence, count, appearance or
        # removal is consulted here or anywhere else in this module — that is the
        # accepted rule, and a count would reintroduce exactly what it replaced.
        self_approved = (requester_user_id == decided_by_user_id)
        if self_approved and not _reason_is_present(decision_reason):
            raise AttemptValidationAbort(
                f"Self-approval of request {request_id} requires a non-empty "
                f"decision_reason; got {decision_reason!r}. The mandatory reason is "
                f"a structural compensating control (§5.4), not a formality. "
                f"Nothing was written and the request remains pending."
            )

        # ── 8-12. The frozen cap and its consumption, under lock 2. ──
        cap = _read_cap_state(db, request.league_id, team_id, season, allocation)

        amount_cents = request.amount_cents
        decided_at   = datetime.now(timezone.utc)

        # ── 13. Capacity decision — the ONE path that writes a transition. ──
        # A corrupted persisted amount and an over-capacity request are BOTH
        # §7.4 terminal rejections: in each case the REQUEST itself is
        # independently invalid, which is what separates outcome 2 from the
        # aborts above.
        if amount_cents is None or amount_cents <= 0:
            return _write_terminal_rejection(
                db, request, decided_by_user_id, decided_at, self_approved,
                decision_reason, cap,
                note=(f"persisted amount_cents={amount_cents!r} fails the cents "
                      f"contract"),
            )
        if amount_cents > cap.remaining_cents:
            return _write_terminal_rejection(
                db, request, decided_by_user_id, decided_at, self_approved,
                decision_reason, cap,
                note=(f"requested {amount_cents} cents exceeds the remaining "
                      f"capacity of {cap.remaining_cents} cents (frozen cap "
                      f"{cap.cap_cents}, already issued {cap.prior_issued_cents})"),
            )

        # ── 14. LOCK 3 — the League row (§15 item 17). HELD THROUGH COMMIT. ──
        # Revalidate EXACTLY TWO THINGS. No commissioner count is computed here
        # or anywhere: a concurrent grant must never invalidate a lawful
        # self-approval (invariant 24), and only the acting approver's own
        # authority matters.
        locked_league = _lock_league(db, request.league_id)
        if locked_league is None:
            raise IntegrityAttemptAbort(
                f"League {request.league_id} vanished between step 5 and the "
                f"step-14 lock."
            )
        if is_season_closed(locked_league):
            raise SeasonClosedAbort(
                f"League {request.league_id}'s season closed at "
                f"{locked_league.season_closed_at}, observed under the League lock "
                f"at step 14. Nothing is posted and request {request_id} remains "
                f"pending."
            )
        if not is_league_commissioner(decided_by_user_id, request.league_id, db):
            raise AuthorizationAttemptAbort(
                f"User {decided_by_user_id}'s commissioner authority for league "
                f"{request.league_id} was revoked before this issuance could "
                f"commit, observed under the League lock at step 14. Nothing is "
                f"posted; request {request_id} remains pending and is decidable by "
                f"any commissioner who still holds authority."
            )

        # ── 15. The canonical posting (§3.2, §3.3) — TWO LEGS, OR THREE. ──
        #
        # session=db is MANDATORY: on the session=None path post() opens its own
        # SessionLocal, elevates to REPEATABLE READ and commits internally, which
        # would put the posting outside this transaction and destroy the single
        # commit boundary. Every account is derived server-side from the
        # persisted row; no caller-supplied account text exists on this path.
        #
        # ── FINAL POR · WP-6 — AN APPROVED TOP-OFF ALSO GROWS THE POT ────────
        #
        #     bab_issuance:{L}:{S}                -2X
        #     wallet:{team}                        +X
        #     fantasystakes_championship:{L}:{S}   +X
        #
        # §15: an approved Top-Off grows the FantasyStakes Championship Pot by
        # the same amount it credits the Wallet. The issuance tally therefore
        # carries 2X, because 2X really was put into circulation by this
        # approval — X spendable by the GM and X added to what the league is
        # playing for.
        #
        # THE GM'S OBLIGATION IS X, NOT 2X, AND THAT IS STRUCTURAL RATHER THAN
        # A SUBTRACTION SOMEWHERE. Both derivations that turn this posting into
        # a number read the WALLET LEG ONLY:
        #
        #   · `_issued_from_ledger` (the cap) sums `wallet:{team}` legs under
        #     this door whose sibling leg is this league-season's issuance
        #     account — the pot leg is a third sibling and is not summed;
        #   · `economy.current_settle.topoff_issued_cents` (the obligation)
        #     sums `wallet:{team}` legs under this door.
        #
        # So a 20-Credit Top-Off consumes 20 of the cap and adds 20 to what the
        # GM owes, exactly as before, while 20 more reaches the pot that nobody
        # owes. WP-7 F6 certified in advance that these two derivations are
        # wallet-leg-only, which is what made this leg safe to add.
        #
        # THE POT LEG IS OMITTED ENTIRELY FOR A LEGACY SEASON, not posted as
        # zero: under RULESET_LEGACY the FantasyStakes Championship Pot is a
        # closed per-GM-contribution pot and a Top-Off has nothing to do with
        # it. A zero leg would claim it participated.
        legs = [
            (f"bab_issuance:{request.league_id}:{season}", -amount_cents),
            (f"wallet:{team_id}",                           amount_cents),
        ]
        if is_final_por(db, league_id=request.league_id, season=season):
            legs[0] = (f"bab_issuance:{request.league_id}:{season}",
                       -amount_cents * 2)
            legs.append((fantasystakes_championship_account(
                request.league_id, season), amount_cents))
        posting_id = ledger_post(
            legs,
            door    = APPROVED_BAB_TOPOFF_DOOR,
            session = db,
        )

        # ── 16. The Wallet compatibility mirror (§3.6). ──
        wallet = db.query(Wallet).filter(Wallet.team_id == team_id).first()
        if wallet is None:
            # No B6 path creates a Wallet row, and inventing one here would be
            # inventing compatibility state whose prior value nobody can vouch
            # for. Integrity-attempt abort: the whole issuance rolls back.
            raise IntegrityAttemptAbort(
                f"Team {team_id} has no Wallet row, so the ledger's post-state has "
                f"nowhere to mirror to. Refusing to create compatibility state "
                f"as a side effect of an issuance."
            )
        # Flush so the ledger entries just written are visible to the balance read
        # below, and so any database-level failure surfaces HERE, under the locks,
        # rather than from inside commit().
        db.flush()
        ledger_min_reserve_cents = _balance_of_in_session(db, f"wallet:{team_id}")
        # THE ONE CONVERSION. The ledger is authoritative and integer cents;
        # Wallet.balance is the pre-existing dollar-denominated Float mirror that
        # validate_bet_amount() and beef_engine read as dollars. Recomputed from
        # the post-state — never incremented, never from the legacy float
        # `amount`, never from this column's own prior value.
        wallet.balance = ledger_min_reserve_cents / 100.0

        # ── 17. The durable disclosure (§4.5). ──
        # event_id is the durable identity; the integer primary key is a storage
        # detail and is never the linkage value. A failure here rolls back the
        # entire issuance — money never moves without its disclosure.
        event_id = uuid.uuid4()
        db.add(TopOffDisclosure(
            event_id            = event_id,
            faab_transaction_id = request.id,
            league_id           = request.league_id,
            season              = season,
            team_id             = team_id,
            amount_cents        = amount_cents,
            requester_user_id   = requester_user_id,
            decided_by_user_id  = decided_by_user_id,
            self_approved       = self_approved,
            decision_reason     = decision_reason,
            decided_at          = decided_at,
            ledger_posting_id   = posting_id,
        ))

        # ── 18. Terminal state and BOTH linkage fields together (§4.4). ──
        request.decision            = "approved"
        request.status              = "applied"
        request.decided_by_user_id  = decided_by_user_id
        request.decided_at          = decided_at
        request.self_approved       = self_approved
        request.decision_reason     = decision_reason
        request.ledger_posting_id   = posting_id
        request.disclosure_event_id = event_id

        # Evaluate the biconditional CHECK and both unique linkage indexes inside
        # this transaction rather than at commit time.
        db.flush()

        # ── 19. COMMIT ONCE. All three locks release here, not before. ──
        db.commit()

        return TopOffDecisionResult(
            request_id               = request.id,
            league_id                = request.league_id,
            team_id                  = team_id,
            season                   = season,
            amount_cents             = amount_cents,
            requester_user_id        = requester_user_id,
            decision                 = "approved",
            status                   = "applied",
            decided_by_user_id       = decided_by_user_id,
            decided_at               = decided_at,
            self_approved            = self_approved,
            decision_reason          = decision_reason,
            ledger_posting_id        = posting_id,
            disclosure_event_id      = event_id,
            cap_cents                = cap.cap_cents,
            prior_issued_cents       = cap.prior_issued_cents,
            remaining_capacity_cents = cap.remaining_cents - amount_cents,
            posted                   = True,
            replayed                 = False,
        )

    except Exception:
        # Every abort, every domain refusal and every unexpected error lands
        # here. The rollback is IMMEDIATE — no work stands between the raise and
        # this handler — so a refusal at or after step 14 releases the League row
        # at the refusal rather than at request teardown. Any ledger entry,
        # mirror write, disclosure row and state change staged by this call is
        # discarded together: there is no partial issuance.
        db.rollback()
        raise


def _write_terminal_rejection(
    db: Session,
    request: FaabTransaction,
    decided_by_user_id: int,
    decided_at: datetime,
    self_approved: bool,
    decision_reason: str | None,
    cap: CapState,
    note: str,
) -> TopOffDecisionResult:
    """§7.3 outcome 2 — the ONLY outcome that writes a state transition from
    inside approval. Exactly one commit; NO posting and NO linkage fields, which
    the biconditional CHECK requires of every non-applied row.

    Reached BEFORE the League lock, exactly where §8.2 places it at step 13. The
    request became independently invalid on its own terms — it asks for more than
    the frozen cap allows, or its persisted amount is corrupt — and that is true
    regardless of who is holding which lock.
    """
    request.decision           = "rejected"
    request.status             = "rejected"
    request.decided_by_user_id = decided_by_user_id
    request.decided_at         = decided_at
    request.self_approved      = self_approved
    request.decision_reason    = decision_reason
    db.flush()
    db.commit()
    return TopOffDecisionResult(
        request_id               = request.id,
        league_id                = request.league_id,
        team_id                  = request.team_id,
        season                   = request.season,
        amount_cents             = request.amount_cents,
        requester_user_id        = request.requester_user_id,
        decision                 = "rejected",
        status                   = "rejected",
        decided_by_user_id       = decided_by_user_id,
        decided_at               = decided_at,
        self_approved            = self_approved,
        decision_reason          = decision_reason,
        ledger_posting_id        = None,
        disclosure_event_id      = None,
        cap_cents                = cap.cap_cents,
        prior_issued_cents       = cap.prior_issued_cents,
        remaining_capacity_cents = cap.remaining_cents,
        posted                   = False,
        replayed                 = False,
    )


# ── Explicit decline and withdrawal (§7.2) ────────────────────────────────────

def reject_top_off(
    league_id: int,
    request_id: int,
    decided_by_user_id: int,
    decision_reason: str | None = None,
    db: Session = None,
) -> TopOffDecisionResult:
    """A commissioner explicitly declines an open request while the season is
    open: `pending -> rejected`, exactly one commit.

    One of the three things §7.4 reserves terminal rejection for. No posting, no
    mirror change, no disclosure, no linkage — the biconditional CHECK makes a
    rejected row carrying either linkage field unrepresentable.

    LOCKS 1 and 3, in the global order (§8.1: "identical on every path that takes
    any subset"). Lock 2 is not taken because no cap arithmetic happens here.
    Rejection after close is NOT decided (§7.5): it aborts and the request
    survives close intact, which is why the League lock is taken at all.
    """
    try:
        request = _lock_request(db, request_id)
        _require_open_topoff(request, request_id, league_id)

        if request.decision != "pending" or request.status != "pending":
            result = _replay_result(request)
            db.rollback()
            return result

        league = db.query(League).filter(League.id == request.league_id).first()
        if league is None:
            raise IntegrityAttemptAbort(
                f"League {request.league_id} does not exist."
            )
        if is_season_closed(league):
            raise SeasonClosedAbort(
                f"League {request.league_id}'s season is closed. A rejection is "
                f"not decided after close; request {request_id} remains pending."
            )
        if not is_league_commissioner(decided_by_user_id, request.league_id, db):
            raise AuthorizationAttemptAbort(
                f"User {decided_by_user_id} holds no commissioner authority for "
                f"league {request.league_id}."
            )

        locked_league = _lock_league(db, request.league_id)
        if locked_league is None:
            raise IntegrityAttemptAbort(
                f"League {request.league_id} vanished before the League lock."
            )
        if is_season_closed(locked_league):
            raise SeasonClosedAbort(
                f"League {request.league_id}'s season closed before this rejection "
                f"could commit. Request {request_id} remains pending."
            )
        if not is_league_commissioner(decided_by_user_id, request.league_id, db):
            raise AuthorizationAttemptAbort(
                f"User {decided_by_user_id}'s authority for league "
                f"{request.league_id} was revoked before this rejection could "
                f"commit. Request {request_id} remains pending."
            )

        decided_at = datetime.now(timezone.utc)
        request.decision           = "rejected"
        request.status             = "rejected"
        request.decided_by_user_id = decided_by_user_id
        request.decided_at         = decided_at
        request.self_approved      = (request.requester_user_id == decided_by_user_id)
        request.decision_reason    = decision_reason
        db.flush()
        db.commit()

        return TopOffDecisionResult(
            request_id               = request.id,
            league_id                = request.league_id,
            team_id                  = request.team_id,
            season                   = request.season,
            amount_cents             = request.amount_cents,
            requester_user_id        = request.requester_user_id,
            decision                 = "rejected",
            status                   = "rejected",
            decided_by_user_id       = decided_by_user_id,
            decided_at               = decided_at,
            self_approved            = request.self_approved,
            decision_reason          = decision_reason,
            ledger_posting_id        = None,
            disclosure_event_id      = None,
            cap_cents                = None,
            prior_issued_cents       = None,
            remaining_capacity_cents = None,
            posted                   = False,
            replayed                 = False,
        )

    except Exception:
        db.rollback()
        raise


def cancel_top_off(
    league_id: int,
    request_id: int,
    requester_user_id: int,
    db: Session = None,
) -> TopOffDecisionResult:
    """The requester withdraws his own open request while the season is open:
    `pending -> cancelled`, exactly one commit.

    ONLY the requester may cancel. Commissioner authority grants nothing here —
    a commissioner who wants an open request closed declines it, which is a
    different, recorded act.

    LOCKS 1 and 3, in the global order. Cancellation after close is not decided
    (§7.5), so the close predicate is revalidated under the League lock exactly
    as the other decision paths do.
    """
    try:
        request = _lock_request(db, request_id)
        _require_open_topoff(request, request_id, league_id)

        if request.decision != "pending" or request.status != "pending":
            result = _replay_result(request)
            db.rollback()
            return result

        if request.requester_user_id != requester_user_id:
            raise AuthorizationAttemptAbort(
                f"Top-off request {request_id} was opened by user "
                f"{request.requester_user_id}; only its requester may cancel it."
            )

        league = db.query(League).filter(League.id == request.league_id).first()
        if league is None:
            raise IntegrityAttemptAbort(f"League {request.league_id} does not exist.")
        if is_season_closed(league):
            raise SeasonClosedAbort(
                f"League {request.league_id}'s season is closed. A cancellation is "
                f"not decided after close; request {request_id} remains pending."
            )

        locked_league = _lock_league(db, request.league_id)
        if locked_league is None:
            raise IntegrityAttemptAbort(
                f"League {request.league_id} vanished before the League lock."
            )
        if is_season_closed(locked_league):
            raise SeasonClosedAbort(
                f"League {request.league_id}'s season closed before this "
                f"cancellation could commit. Request {request_id} remains pending."
            )

        decided_at = datetime.now(timezone.utc)
        request.decision           = "cancelled"
        request.status             = "cancelled"
        request.decided_by_user_id = requester_user_id
        request.decided_at         = decided_at
        request.self_approved      = (request.requester_user_id == requester_user_id)
        db.flush()
        db.commit()

        return TopOffDecisionResult(
            request_id               = request.id,
            league_id                = request.league_id,
            team_id                  = request.team_id,
            season                   = request.season,
            amount_cents             = request.amount_cents,
            requester_user_id        = request.requester_user_id,
            decision                 = "cancelled",
            status                   = "cancelled",
            decided_by_user_id       = requester_user_id,
            decided_at               = decided_at,
            self_approved            = request.self_approved,
            decision_reason          = request.decision_reason,
            ledger_posting_id        = None,
            disclosure_event_id      = None,
            cap_cents                = None,
            prior_issued_cents       = None,
            remaining_capacity_cents = None,
            posted                   = False,
            replayed                 = False,
        )

    except Exception:
        db.rollback()
        raise
