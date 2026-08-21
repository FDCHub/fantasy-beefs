"""
beefs/versus_refresh.py — UIRECON Rev 1.4: the SHARED informational odds
refresh for a Dynamic FantasyStakes Matchup.

WHAT THIS MODULE IS. The one place that turns Rev 9 §5's permission —
"between Handshake and Final Lock, a display-only re-sim may show GMs where the
line sits" — into something a card can actually draw, and into something BOTH
GMs draw identically. It decides eligibility, runs the re-simulation through the
same governed path Final Lock will use, and appends one row to
`challenge_odds_refresh`.

WHAT IT DELIBERATELY DOES NOT DO, AND WHY EACH ABSENCE IS LOAD-BEARING:

  · IT MOVES NO CREDITS AND POSTS NO LEDGER ENTRY. Rev 9 §5 is unambiguous —
    "informational refreshes are nonbinding — they move no money" — and the
    Locked-vs-Dynamic ruling §3 says the same. There is no import of
    `ledger.ledger` in this file and no call that could reach one.

  · IT TOUCHES NO ESCROW. Not the pooled account, not the per-side Anchor or
    Derived accounts, not a balance read that could be mistaken for a write. The
    Handshake→Final-Lock window is documented (MS-SIM-6) as having NO authorized
    escrow writer, and that closed window is the factual basis for OVERSHOOT-B:
    §2 guard 3 refuses an issuer overshoot precisely because nothing legitimate
    could have produced one. A refresh that touched escrow would not merely be
    wrong, it would demolish the reasoning another guard depends on.

  · IT MUTATES NO OFFICIAL TERM. The stake, the line, the odds of record, the
    frozen ceilings, the model identity, the response status and the proposal
    are all read and none is assigned. The only write this module performs is an
    INSERT into its own append-only table.

  · IT PERFORMS NO FINAL LOCK AND TAKES NO CLAIM. It never touches
    `challenge_final_lock_claims`, so it cannot consume, refresh or contend for
    the execution right, and it never writes `ChallengeFinalLock`. Rev 9 §5.1's
    two-phase protocol is untouched and unweakened.

  · IT MINTS NO `ProtocolEvent`. See `ChallengeOddsRefresh` in `db/schema.py`:
    that table is documented as the idempotency identity for a governed MONEY
    operation, and filing a nonbinding read there would corrupt the record
    operators read to reconstruct where Credits went.

  · IT WEAKENS NO HANDSHAKE OR FINALITY RULE. It is admissible ONLY inside the
    window those rules already define, and it asks the Final-Lock worker's own
    entry predicates rather than restating them (see `refresh_eligibility`).

HOW TWO GMs COME TO SEE ONE NUMBER. Three separate mechanisms, all needed:

  1. THE FIGURES ARE ANCHORED ON THE CHALLENGE, NEVER ON THE CALLER. Probability
     is computed for the ISSUER and stored that way. The simulator's seed is
     derived from team identity and week, so `(A, B)` and `(B, A)` are genuinely
     different draws; a caller-anchored refresh would hand the two GMs two
     different lines for one wager and both would be correct.
  2. THE MODEL IS THE HANDSHAKE-FROZEN ONE (MODEL-A). `resolve_and_verify`
     resolves `challenge.dynamic_model_version_id` and proves the registry entry
     is unedited. A refresh under a newly deployed model would show a number the
     wager can never settle at.
  3. THE RESULT IS PERSISTED AND READ BACK. Projections move between two
     requests, so even a perfectly deterministic computation run twice can
     legitimately produce two answers. `latest_refresh` is what the second GM
     reads, so they see the refresh that happened rather than one of their own.

WHY IT REUSES `economy.dynamic_challenge` RATHER THAN RE-DERIVING ANYTHING. The
whole product claim of a refresh is "this is where the line sits" — i.e. a
preview of what Final Lock would compute. A second implementation of the
simulation call or of the derived-stake cap would make that claim true only by
coincidence, and would drift the first time either side was touched. So the
official simulation entry (`_run_official_simulation`), the nonbinding quote
(`informational_refresh`) and the odds representation chain (`_signed_american`
/ `_ml_to_decimal`) are all imported from the module that owns them.

THE IMPORTS OF `economy` ARE FUNCTION-LOCAL, DELIBERATELY. `economy.dynamic_
challenge` imports `beefs.proposal_lifecycle` at module scope, so a module-scope
edge back from `beefs` would be an import cycle. Deferring the import is the
idiom the API layer already uses throughout, and it keeps this module importable
by anything that only wants the refusal vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from db.schema import BeefChallenge, ChallengeFinalLock, ChallengeOddsRefresh

__all__ = [
    "REASON_AFTER_FINAL_LOCK",
    "REASON_CANNOT_PRICE",
    "REASON_MODEL_INTEGRITY",
    "REASON_NOT_DYNAMIC",
    "REASON_NOT_HANDSHAKEN",
    "REASON_NOT_A_PARTICIPANT",
    "REASON_NOT_FOUND",
    "REASON_ROSTER_UNAVAILABLE",
    "RefreshRefused",
    "latest_refresh",
    "refresh_eligibility",
    "refresh_dynamic_odds",
]


# ── The refusal vocabulary ────────────────────────────────────────────────────
#
# ONE NAME PER FACT, in the shape every other governed refusal in this codebase
# already uses: `{"reason_code": ..., "message": ...}` with a product sentence.
# Three different explanations for one fact is how a product stops being trusted
# (`_MarketUnavailable`, api/main.py, says the same thing about market lines).

#: The challenge id names nothing this GM's league contains.
REASON_NOT_FOUND = "challenge_not_found"

#: The caller is a league member but not one of the two GMs in this wager.
REASON_NOT_A_PARTICIPANT = "not_a_participant"

#: A LOCKED wager. There is no refresh behaviour for one, and this is not a
#: temporary state that will later permit it — the Locked model freezes odds at
#: proposal creation and acceptance merely SELECTS a frozen proposal
#: (Locked-vs-Dynamic ruling §§1–2). "Refresh & Relock" is the Locked answer and
#: it is a COUNTER: it creates a new frozen proposal and puts new terms on the
#: table. Nothing in this module touches that protocol.
REASON_NOT_DYNAMIC = "refresh_not_dynamic"

#: Dynamic, but not yet inside the window. Before the Handshake there are no
#: frozen ceilings, no frozen model and no funded exposure, so there is nothing
#: an indicative derived stake could be derived from or capped against.
REASON_NOT_HANDSHAKEN = "refresh_not_handshaken"

#: The window has closed. Rev 9 §7.3 makes authoritative completion the
#: EXISTENCE of the `ChallengeFinalLock` row, so that row is the primary test;
#: the governed kickoff moment is checked as well, because between the trigger
#: instant and the worker's sweep the wager is already past the point where a
#: displayed line means anything. Both are the same fact — Final Lock has
#: arrived — and so they share one name rather than inviting a caller to branch
#: on which of two codes it got.
REASON_AFTER_FINAL_LOCK = "refresh_after_final_lock"

#: The Handshake-frozen model no longer resolves, or its registry entry was
#: edited since freezing. Final Lock refuses outright in this state and never
#: substitutes the active model; a refresh that quietly substituted would show a
#: number under rules nobody froze.
REASON_MODEL_INTEGRITY = "refresh_model_integrity"

#: The two refusals `_market_board_or_refuse` already owns, reused verbatim so a
#: GM meets one sentence for one condition wherever they meet it.
REASON_ROSTER_UNAVAILABLE = "roster_unavailable"
REASON_CANNOT_PRICE = "cannot_price"


class RefreshRefused(Exception):
    """A governed refusal, carrying the HTTP status the API layer should use.

    THE STATUS TRAVELS WITH THE REASON rather than being decided at the route,
    because the route is not the only conceivable caller and a second caller
    mapping the same condition to a different status is how one refusal becomes
    two. Modelled on `_MarketUnavailable` in `api/main.py`, which solved exactly
    this for market lines.
    """

    def __init__(self, status: int, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.reason_code = reason_code
        self.message = message


@dataclass(frozen=True)
class RefreshEligibility:
    """Why a Matchup may or may not be refreshed, as data.

    Returned rather than raised by `refresh_eligibility` so a READ surface can
    ask the question without handling an exception — the card needs to know
    whether to draw the control at all, and "not eligible" is an ordinary answer
    to that, not an error.
    """

    challenge_id: int
    eligible: bool
    reason_code: Optional[str] = None
    message: str = ""


def _refusal_for(reason_code: str, message: str) -> RefreshRefused:
    status = {
        REASON_NOT_FOUND: 404,
        REASON_NOT_A_PARTICIPANT: 403,
        REASON_ROSTER_UNAVAILABLE: 409,
        REASON_CANNOT_PRICE: 400,
    }.get(reason_code, 409)
    return RefreshRefused(status, reason_code, message)


# ── Eligibility ───────────────────────────────────────────────────────────────

def refresh_eligibility(db: Session, challenge: BeefChallenge, *,
                        now: Optional[datetime] = None) -> RefreshEligibility:
    """Is this wager inside the governed refresh window?

    THE PREDICATES ARE THE FINAL-LOCK WORKER'S OWN, ASKED IN THE SAME ORDER.
    `workers.final_lock.eligible_challenges` defines the set of challenges that
    have Handshaken and have not yet Final-Locked, and documents each of its four
    predicates against Rev 9. The refresh window is precisely that set — "between
    Handshake and Final Lock" — so restating the conditions here in different
    words would create a second definition of one window, and the two would
    eventually disagree about a wager sitting on the boundary.

    THE CLOCK IS CONSULTED SECOND, NOT FIRST. The durable `ChallengeFinalLock`
    row is the authoritative completion fact (§7.3); the kickoff moment is a
    supplementary close, and it can legitimately be UNANSWERABLE — a week with no
    announced NFL kickoff raises `ScheduleNotReadyError`, and the Final-Lock
    worker treats that as "not due, retry next sweep" rather than as "now". This
    function takes the same reading: no announced kickoff means the window has
    not closed, because there is no governed instant for it to have closed at.
    Inventing one here would be inventing a lock time, which is exactly the
    behaviour the worker refuses to invent.
    """
    from beefs import proposal_lifecycle as spec1

    def no(reason: str, message: str) -> RefreshEligibility:
        return RefreshEligibility(challenge.id, False, reason, message)

    if challenge.challenge_mode != spec1.MODE_DYNAMIC:
        return no(REASON_NOT_DYNAMIC,
                  "This Matchup is Locked. Its terms were frozen when it was "
                  "offered, so there are no odds to refresh.")

    if (challenge.response_status != spec1.ACCEPTED
            or challenge.dynamic_handshake_at is None):
        return no(REASON_NOT_HANDSHAKEN,
                  "This Matchup has not been agreed yet, so there is nothing "
                  "live to refresh.")

    locked = (db.query(ChallengeFinalLock)
              .filter(ChallengeFinalLock.challenge_id == challenge.id).first())
    if locked is not None:
        return no(REASON_AFTER_FINAL_LOCK,
                  "This Matchup has reached Final Lock. Its terms are set.")

    from betting.exceptions import ScheduleNotReadyError
    from workers.final_lock import final_lock_due_at

    try:
        due_at = final_lock_due_at(challenge)
    except ScheduleNotReadyError:
        # No governed kickoff, so no instant the window could have closed at.
        return RefreshEligibility(challenge.id, True)

    moment = now or datetime.now(timezone.utc)
    # The worker computes `due_at` from `nfl_schedule`, whose timestamps are
    # naive on both dialects. Comparing a tz-aware "now" against it would raise,
    # so the reading is normalised to the stored convention rather than the
    # stored value being reinterpreted.
    if moment.tzinfo is not None and due_at.tzinfo is None:
        moment = moment.replace(tzinfo=None)
    elif moment.tzinfo is None and due_at.tzinfo is not None:
        moment = moment.replace(tzinfo=timezone.utc)

    if moment >= due_at:
        return no(REASON_AFTER_FINAL_LOCK,
                  "This Matchup has reached Final Lock. Its terms are set.")
    return RefreshEligibility(challenge.id, True)


def participant_team_ids(challenge: BeefChallenge) -> tuple[int, int]:
    """The two teams the wager is between, from the challenge row itself.

    NOT FROM THE PROPOSAL, and not from either Bet. The challenge row is the one
    record that exists in every state this module can be reached in, and the
    Anchor role never moves off the original issuer (A4 / `anchor_team_id`), so
    the pair is the same however the negotiation went.
    """
    return (challenge.challenger_team_id, challenge.challenged_team_id)


# ── The refresh ───────────────────────────────────────────────────────────────

def latest_refresh(db: Session, challenge_id: int
                   ) -> Optional[ChallengeOddsRefresh]:
    """The shared refresh both GMs read, or None if there has never been one.

    ORDERED BY `refreshed_at` THEN `id`. The timestamp is the meaningful order
    and `id` is the tie-break, because two refreshes landing inside the same
    stored timestamp resolution must still have one answer, and "whichever the
    database felt like" is not one.
    """
    return (db.query(ChallengeOddsRefresh)
            .filter(ChallengeOddsRefresh.challenge_id == challenge_id)
            .order_by(ChallengeOddsRefresh.refreshed_at.desc(),
                      ChallengeOddsRefresh.id.desc())
            .first())


def refresh_dynamic_odds(db: Session, *, challenge_id: int,
                         actor_team_id: Optional[int],
                         now: Optional[datetime] = None
                         ) -> ChallengeOddsRefresh:
    """Re-simulate one Dynamic wager and record the SHARED result.

    ORDER, and every step's reason:

      1. Read the challenge. No row lock is taken — this writes nothing that
         another writer could race, and taking `FOR UPDATE` on a challenge row
         for a read would put a nonbinding surface into the Handshake/Final-Lock
         lock graph, where it has no business being.
      2. Participation. A league member who is not in this wager gets the same
         answer as a stranger.
      3. The governed window, from `refresh_eligibility`.
      4. Resolve and VERIFY the Handshake-frozen model. Before the simulation,
         because a simulation run under a model that turns out to be
         unresolvable proves nothing and would still have cost the numpy.
      5. Read the LIVE lineups and projections. This is the thing that moved and
         the whole reason a refresh exists.
      6. Run the simulation through the Final-Lock entry point, so the number
         shown is a genuine preview of the number Final Lock will compute.
      7. Derive the indicative stake through the governed NONBINDING function,
         which applies the ceiling cap.
      8. Append one row and commit it. The commit is what makes the result
         SHARED; without it the other GM would read nothing.

    `actor_team_id` reaches step 8 and nothing else. It is recorded, never
    consulted: every figure in the row must be identical whichever GM asked.
    """
    from economy.dynamic_challenge import (
        HandshakeStateError,
        NotDynamicError,
        _ml_to_decimal,
        _run_official_simulation,
        _signed_american,
        informational_refresh,
        resolve_shared_matchup_for_challenge,
    )
    from odds.model_registry import (
        ModelConfigHashMismatchError,
        UnknownModelVersionError,
        resolve_and_verify,
    )

    challenge = (db.query(BeefChallenge)
                 .filter(BeefChallenge.id == challenge_id).first())
    if challenge is None:
        raise _refusal_for(REASON_NOT_FOUND, "That Matchup does not exist.")

    if actor_team_id is not None and actor_team_id not in participant_team_ids(challenge):
        raise _refusal_for(
            REASON_NOT_A_PARTICIPANT,
            "This Matchup is between two other GMs.")

    verdict = refresh_eligibility(db, challenge, now=now)
    if not verdict.eligible:
        raise _refusal_for(verdict.reason_code, verdict.message)

    # ── 4 · MODEL-A: the FROZEN version, proven unedited. Never the active one.
    try:
        config = resolve_and_verify(challenge.dynamic_model_version_id,
                                    challenge.dynamic_model_config_hash)
    except (UnknownModelVersionError, ModelConfigHashMismatchError) as exc:
        raise _refusal_for(
            REASON_MODEL_INTEGRITY,
            "The pricing model this Matchup was agreed under is not available, "
            "so its odds cannot be re-read.") from exc

    # ── 5 · the LIVE inputs, built exactly as the Final-Lock worker builds them
    from workers.final_lock import build_final_lock_inputs

    try:
        inputs = build_final_lock_inputs(db, challenge)
    except ValueError as exc:
        raise _refusal_for(REASON_CANNOT_PRICE,
                           "This Matchup cannot be re-priced with the inputs "
                           "available.") from exc

    if not inputs.challenger_starters or not inputs.challenged_starters:
        # The simulator refuses an empty starter list outright. Asked here, one
        # step early, so a GM is told the actionable thing rather than shown a
        # generic failure — the same courtesy `/versus/quote` extends.
        raise _refusal_for(
            REASON_ROSTER_UNAVAILABLE,
            "One of these teams has no starting lineup for this week yet, so "
            "the odds cannot be re-read.")

    # ── 6 · the simulation, through the governed identity path ───────────────
    matchup = resolve_shared_matchup_for_challenge(db, challenge)
    p_issuer, p_opponent = _run_official_simulation(
        config=config, challenge=challenge, matchup=matchup, inputs=inputs)

    # ── 7 · the NONBINDING derivation, ceiling cap included ──────────────────
    try:
        quote = informational_refresh(
            challenge_id=challenge_id, p_issuer=p_issuer,
            p_opponent=p_opponent, db=db)
    except (NotDynamicError, HandshakeStateError) as exc:
        # Unreachable behind step 3, which asks the same two questions against
        # the same row. Mapped rather than left to escape as a 500, because an
        # invariant that is merely believed unreachable should still fail as a
        # governed refusal if it ever is not.
        raise _refusal_for(REASON_NOT_HANDSHAKEN, str(exc)) from exc
    except ValueError as exc:
        # `derive_stakes` refuses a probability of exactly 0 or 1: a certainty
        # has no fair pot and no opponent stake to indicate. Locked-mode wagers
        # never reach here, and the wager itself is unaffected — only the
        # display is refused.
        raise _refusal_for(
            REASON_CANNOT_PRICE,
            "This Matchup is too one-sided to re-price right now. Its agreed "
            "terms are unchanged.") from exc

    issuer_ml = _signed_american(p_issuer)
    opponent_ml = _signed_american(p_opponent)

    row = ChallengeOddsRefresh(
        challenge_id=challenge_id,
        refreshed_at=(now or datetime.now(timezone.utc)).replace(tzinfo=None),
        requested_by_team_id=actor_team_id,
        model_version_id=config.model_version_id,
        model_config_hash=challenge.dynamic_model_config_hash,
        simulations=int(config.n_sims),
        projection_source_id=inputs.projection_source_id,
        projection_dataset_version=inputs.projection_dataset_version,
        issuer_probability=float(p_issuer),
        opponent_probability=float(p_opponent),
        issuer_moneyline=issuer_ml,
        opponent_moneyline=opponent_ml,
        issuer_decimal_odds=_ml_to_decimal(issuer_ml),
        opponent_decimal_odds=_ml_to_decimal(opponent_ml),
        anchor_cents=int(challenge.dynamic_issuer_ceiling_cents or 0),
        indicative_derived_cents=int(quote.indicative_derived_cents),
        opponent_ceiling_cents=int(quote.opponent_ceiling_cents),
        ceiling_applied=bool(quote.capped),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
