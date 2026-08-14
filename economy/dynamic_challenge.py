"""
economy/dynamic_challenge.py — P3-D2 / SIMULATION ENGINE Rev 9: the Dynamic
Handshake, the informational refresh, and the Final-Lock protocol.

WHAT THIS MODULE IS. The Dynamic half of the challenge money path. Locked
acceptance freezes everything at acceptance and is untouched by this file;
Dynamic acceptance IS the Handshake, which funds each side's MAXIMUM exposure
and freezes the model, then leaves lineups and odds live until Final Lock
re-prices exactly once.

    handshake  -> true up the Anchor, split into per-side escrow, fund the
                  opponent's full ceiling, freeze ceilings + model version
    refresh    -> read-only re-simulation under the FROZEN model. No money.
    final lock -> claim, then one simulation, one Adjustment, one Derived
                  refund, migrate to Bet escrow, freeze the result

THREE THINGS FREEZE AT THE HANDSHAKE (Rev 9 §0): the model version, each side's
maximum exposure, and the escrow ceiling. The final ODDS do not freeze — that is
the whole difference from Locked, and it is why the model must be pinned: at
Final Lock the engine re-derives the opponent's stake from NEW probabilities, and
the gap between that and the ceiling is refunded as real BAB. A model that drifted
in between would refund under rules nobody agreed to.

THE CEILING IS THE NO-INCREASE GUARD, NOT THE DERIVATION (MS-SIM-11). When the
issuer's probability worsens the derivation genuinely demands a LARGER opponent
stake; the immutable ceiling caps it back down. Remove the cap and the pot grows,
charging a GM above their commitment.

THE ISSUER NEVER REFUNDS AT FINAL LOCK (OVERSHOOT-B). Guards 2, 3 and 3a compose
to `issuer_escrow == recorded_ceiling == anchor == issuerFinal`, so the issuer
subtraction is identically zero. There is deliberately NO issuer-refund posting
branch in this file: such a branch could only ever execute on an invariant
violation that guard 3 has already refused, and paying it out would launder an
unexplained balance into a GM's wallet and destroy the evidence of whatever
produced it.

LOCK ORDER, ALWAYS: challenge row FOR UPDATE first, then Wallet rows ascending
by team_id through lock_funding_scopes(). The claim table sits OUTSIDE that
graph — Phase 1 commits before Phase 2 begins, so no claim row is ever held
while a challenge or Wallet row is locked, and no new edge is introduced.

MONEY IS INTEGER CENTS EVERYWHERE. Floats appear only as probabilities and as
the legacy Bet.amount mirror, always derived from authoritative cents.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import (
    BeefChallenge,
    BeefProposal,
    ChallengeFinalLock,
    ChallengeFinalLockClaim,
    Matchup,
    ProtocolEvent,
)
from ledger.ledger import (
    _balance_of_in_session,
    lock_funding_scopes,
    post as ledger_post,
)
from beefs import proposal_lifecycle as spec1
from beefs.proposal_lifecycle import _lock_challenge
from economy import challenge_funding as cf
from odds.dynamic_pricing import (
    DynamicPricingError,
    adjust_escrow,
    derive_stakes,
    p2o,
)
from odds.model_registry import (
    ACTIVE_MODEL_VERSION_ID,
    ModelConfigHashMismatchError,
    SimModelConfig,
    UnknownModelVersionError,
    model_config_hash,
    resolve_active_model_config,
    resolve_and_verify,
)

# ── Ledger doors ──────────────────────────────────────────────────────────────
DOOR_HS_TOPUP    = "dynamic_handshake_topup"      # issuer true-up, raise branch
DOOR_HS_RELEASE  = "dynamic_handshake_release"    # issuer true-up, lower branch
DOOR_HS_SPLIT    = "dynamic_handshake_split"      # pooled -> per-side Anchor
DOOR_HS_DERIVED  = "dynamic_handshake_derived"    # opponent ceiling funding
DOOR_FL_REFUND   = "dynamic_final_lock_refund"    # Derived-only refund
DOOR_FL_MIGRATE  = "dynamic_final_lock_migrate"   # per-side -> Bet escrow

EVENT_HANDSHAKE  = "challenge_accept"       # the Handshake IS the acceptance
EVENT_FINAL_LOCK = "challenge_final_lock"

# §5.4 — ruled at 15 minutes, as a named constant with that default. Deliberately
# NOT configurable: a staleness threshold settable to zero is a way to break the
# mutex from configuration.
FINAL_LOCK_CLAIM_TTL = timedelta(minutes=15)

RESULT_OK               = "ok"
RESULT_INTEGRITY_ERROR  = "model_integrity_error"
RESULT_GUARD_VIOLATION  = "final_lock_guard_violation"


# ── Errors ────────────────────────────────────────────────────────────────────

class DynamicChallengeError(ValueError):
    """Base for every refusal here. Subclasses are distinct TYPES so callers and
    tests branch on type, never on message text."""


class NotDynamicError(DynamicChallengeError):
    """The challenge is not in Dynamic mode. Locked never reaches this module."""


class HandshakeStateError(DynamicChallengeError):
    """The challenge is not in a state a Handshake may act on."""


class HandshakeExitViolation(DynamicChallengeError):
    """MS-SIM-8 — at Handshake exit a per-side escrow balance did not EXACTLY
    equal its recorded ceiling, read independently (ledger vs challenge row).

    Fails at the source rather than riding invisibly to Final Lock. Exact
    equality, no `>=`, no deployment-dependent relaxation."""


class FinalLockGuardViolation(DynamicChallengeError):
    """Rev 9 §2 guard 3 / 3a — OVERSHOOT-B.

    A per-side escrow balance did not equal its recorded ceiling at Final-Lock
    entry, or the recorded issuer ceiling is not the accepted Anchor. Handshake
    exit required equality and the Handshake->Final-Lock window contains no
    authorized escrow writer, so a discrepancy has NO legitimate cause. Post
    nothing; do not normalize; do not refund the difference."""


class ModelIntegrityError(DynamicChallengeError):
    """The Handshake-frozen model version cannot be resolved, or its content
    hash no longer matches. Never substituted with the active model."""


class FinalLockNotOwnedError(DynamicChallengeError):
    """Another worker holds a live, non-stale execution claim. Do not execute and
    do not report Final Lock as newly successful."""


# ── Accounts (Rev 9 §7.1 ESCROW-A) ────────────────────────────────────────────

def anchor_escrow_account(challenge_id: int) -> str:
    return f"escrow:challenge:{challenge_id}:anchor"


def derived_escrow_account(challenge_id: int) -> str:
    return f"escrow:challenge:{challenge_id}:derived"


# ── Results ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HandshakeResult:
    challenge_id:           int
    event_id:               uuid.UUID
    protocol_event_id:      int
    anchor_cents:           int
    issuer_ceiling_cents:   int
    opponent_ceiling_cents: int
    model_version_id:       str
    model_config_hash:      str
    replayed:               bool
    detail:                 str = ""


@dataclass(frozen=True)
class RefreshQuote:
    """A NONBINDING informational quote. Nothing here was written anywhere."""
    challenge_id:           int
    model_version_id:       str
    p_issuer:               float
    p_opponent:             float
    indicative_derived_cents: int
    opponent_ceiling_cents: int
    capped:                 bool
    binding:                bool = False


@dataclass(frozen=True)
class FinalLockInputs:
    """The FINAL lineup and projection data the one official simulation runs on.

    THIS TYPE CARRIES LIVE DATA ONLY. Nothing here is persisted identity, and
    that separation is the whole point.

    B-1 CORRECTION (probabilities). Final Lock once accepted `p_issuer_final` /
    `p_opponent_final` as floats, so any caller could drive the Derived refund
    with numbers no simulation produced. Rev 9 §5.1 requires the claimed
    execution to run the one official simulation itself, so the economic API
    takes inputs and derives the probabilities internally.

    B-3/B-4 CORRECTION (identity). The first version of this type still carried
    `home_team_id`, `away_team_id` and `matchup_id`. All three are now GONE,
    because all three could change the official probability and therefore real
    money:

      * team ids fed both the seed and the role-orientation branch. That branch
        was orientation, never membership — a non-participant `home_team_id`
        did not raise, it fell through to the `else` and assigned the AWAY
        probability to the issuer, inverting the price.
      * `matchup_id` fed `seed = matchup_id * 1_000 + week` directly, letting a
        caller choose the official Monte Carlo draw sequence for a wager whose
        model and terms are otherwise frozen.

    STARTERS ARE BOUND BY ROLE, NOT BY SIDE. The fields are named for the
    challenge roles the database already governs, so there is no home/away
    decision left for a caller to get wrong or to game; Phase 2 maps role to side
    using the persisted Matchup. A caller can still supply the wrong PLAYERS —
    that is live data and is supposed to be suppliable — but it can no longer
    change who the wager is between, which side is which, or which seed runs.

    Week is likewise absent: it comes from `challenge.week`.
    """
    challenger_starters: tuple
    challenged_starters: tuple
    # Provenance of the projection dataset actually read at Final Lock. Recorded
    # on the frozen result SEPARATELY from the model identity, because the model
    # is frozen while the projections are deliberately live.
    projection_source_id:       Optional[str] = None
    projection_dataset_version: Optional[str] = None


@dataclass(frozen=True)
class ClaimOutcome:
    challenge_id:  int
    owned:         bool
    status:        str
    claim_id:      Optional[int]
    attempt_count: int
    detail:        str = ""


@dataclass(frozen=True)
class FinalLockResult:
    challenge_id:          int
    final_lock_id:         int
    event_id:              uuid.UUID
    protocol_event_id:     int
    p_issuer_final:        float
    p_opponent_final:      float
    anchor_cents:          int
    derived_raw_cents:     int
    derived_final_cents:   int
    derived_refund_cents:  int
    ceiling_applied:       bool
    anchor_bet_id:         Optional[int]
    derived_bet_id:        Optional[int]
    replayed:              bool
    detail:                str = ""


# ── Shared helpers ────────────────────────────────────────────────────────────

def _require_dynamic(challenge: BeefChallenge) -> None:
    if challenge.challenge_mode != spec1.MODE_DYNAMIC:
        raise NotDynamicError(
            f"Challenge {challenge.id} is mode {challenge.challenge_mode!r}. "
            f"This module handles only {spec1.MODE_DYNAMIC!r}; Locked stays on "
            f"economy/challenge_funding.py.")


def _proposal_probabilities(proposal: BeefProposal) -> tuple[float, float]:
    """The frozen quote probabilities the Handshake derivation prices from."""
    p_iss = proposal.anchor_win_probability
    p_opp = proposal.derived_win_probability
    if p_iss is None or p_opp is None:
        raise HandshakeStateError(
            f"Proposal {proposal.id} carries no frozen win probabilities; the "
            f"opponent's Derived ceiling cannot be derived from it.")
    return float(p_iss), float(p_opp)


def _balance(db: Session, account: str) -> int:
    db.flush()
    return _balance_of_in_session(db, account)


# ── Odds representation (B-2) ─────────────────────────────────────────────────
#
# TWO REPRESENTATIONS, AND THEY ARE NOT INTERCHANGEABLE. The codebase already
# fixes both contracts, and this package must honour them rather than pick one:
#
#   ChallengeFinalLock.issuer_moneyline / opponent_moneyline
#       INTEGER, AMERICAN. The column names say moneyline and the type is
#       Integer. This is the audit record of the official final price.
#
#   Bet.odds
#       FLOAT, DECIMAL. Proven by three independent facts: the column default is
#       1.909 (decimal for -110), settlement computes `bet.amount * bet.odds`
#       (settlement_engine.py:691 — a multiplier, which only makes sense for
#       decimal), and `_ml_to_decimal()` exists as the canonical American->decimal
#       converter. Writing an American integer such as -110 into this field would
#       make settlement compute a NEGATIVE payout.
#
# So the Final-Lock chain is: probability -> American (P3-D1 `p2o`, the certified
# conversion Rev 9 §2 names) -> decimal (`_ml_to_decimal`) for the Bet row, with
# the American value retained on the immutable record for audit.


def _signed_american(p: float) -> int:
    """Probability -> signed American odds using the certified P3-D1 conversion.

    `p2o` returns (magnitude, is_negative) because the reference JS carries the
    sign separately; the sign is reattached here so the stored moneyline reads
    the way a GM would see it.
    """
    magnitude, is_negative = p2o(p)
    return -magnitude if is_negative else magnitude


def _ml_to_decimal(ml: int) -> float:
    """American -> decimal, the canonical conversion this codebase already uses.

    Byte-identical to `beef_engine._ml_to_decimal` and `bet_engine._ml_to_decimal`,
    duplicated here for the same reason bet_engine duplicates `_to_cents`: importing
    beef_engine would be a backwards dependency, and the P1-L4 fence forbids the
    economy layer taking that edge at all. Four decimal places, matching both
    existing copies exactly, so a Dynamic Bet's odds are indistinguishable in
    representation from a Locked one's.
    """
    if ml < 0:
        return round(1 + 100 / abs(ml), 4)
    return round(1 + ml / 100, 4)


def resolve_shared_matchup_for_challenge(
    db: Session, challenge: BeefChallenge
) -> Optional[Matchup]:
    """Do these two challenge participants share ONE persisted Yahoo Matchup?

    Returns that Matchup, or **None for a legitimate cross-matchup challenge**.

    CROSS-MATCHUP WAGERS ARE A PRODUCT FEATURE, NOT AN ERROR (CORE-007 / AP-304:
    "any eligible GM may challenge any other eligible GM in the same League
    regardless of Yahoo's scheduled matchup" — the legacy engine says the same at
    `beef_engine.issue_challenge`: "The two teams do NOT need to be scheduled
    against each other"). An earlier version of this helper required a shared
    matchup and refused without one, which would have let a perfectly valid
    cross-matchup Dynamic challenge Handshake successfully — taking both GMs'
    money into escrow — and then become permanently unfinalizable at Final Lock.
    Returning None is therefore a GOVERNED ANSWER, not a fallback.

    THE QUESTION HERE IS NOT `_find_matchup`'s QUESTION. That helper asks "which
    matchup is THIS ONE TEAM in?" and is called once per side when Bet rows are
    created; a cross-matchup challenge legitimately has two different answers.
    This asks "do these TWO teams share one matchup?", which has exactly one
    correct answer per challenge. The two coexist without conflict because they
    are different questions, so no lookup rule contradicts the other.

    IT STILL REFUSES REAL CORRUPTION, loudly, before any simulation or money:

      ambiguous — more than one persisted row claims these same two teams share a
                  matchup this league-week. The governed seed would then depend on
                  row order, so there is no deterministic official draw.
      malformed — the matched row's participants are not exactly the two challenge
                  teams (e.g. a self-matchup row). Unreachable by construction of
                  the query, and asserted anyway rather than assumed.

    Absence of a shared matchup is NOT corruption and is never refused.
    """
    ch, cd = challenge.challenger_team_id, challenge.challenged_team_id
    rows = (
        db.query(Matchup)
        .filter(
            Matchup.week == challenge.week,
            Matchup.league_id == challenge.league_id,
            or_(
                and_(Matchup.home_team_id == ch, Matchup.away_team_id == cd),
                and_(Matchup.home_team_id == cd, Matchup.away_team_id == ch),
            ),
        )
        .all()
    )
    if not rows:
        return None                     # legitimate cross-matchup challenge

    if len(rows) > 1:
        raise FinalLockGuardViolation(
            f"Challenge {challenge.id}: {len(rows)} persisted matchups claim "
            f"teams {ch} and {cd} play each other in league "
            f"{challenge.league_id} week {challenge.week} "
            f"({[m.id for m in rows]}). The governed seed would depend on row "
            f"order, so there is no deterministic official draw. Refusing before "
            f"simulation.")

    matchup = rows[0]
    if {matchup.home_team_id, matchup.away_team_id} != {ch, cd}:
        raise FinalLockGuardViolation(
            f"Challenge {challenge.id}: shared Matchup {matchup.id} has teams "
            f"{sorted({matchup.home_team_id, matchup.away_team_id})}, not the "
            f"challenge participants {sorted({ch, cd})}. Refusing.")
    return matchup


def _run_official_simulation(
    *,
    config: SimModelConfig,
    challenge: BeefChallenge,
    matchup: Matchup,
    inputs: FinalLockInputs,
) -> tuple[float, float]:
    """THE ONE official Final-Lock simulation. Internal; not an admission path.

    EVERY IDENTITY IT USES IS GOVERNED. Team ids come from the challenge row, the
    seed's matchup id from the persisted Matchup, and the week from
    `challenge.week`. The only caller-supplied values are the two starter lists,
    which are live projection data and are supposed to be suppliable. There is no
    argument through which a caller can change who is playing, which side they
    are on, or which draw sequence runs.

    It takes an ALREADY-RESOLVED, ALREADY-HASH-VERIFIED config rather than a
    version id, so it cannot resolve a model itself and cannot be mistaken for the
    authoritative entry point: on its own it verifies nothing and commits nothing.
    Phase 2 validates identity, resolves and verifies the model, then calls this
    exactly once and hands the result straight to `adjust_escrow`.

    TWO DELIBERATE SEED PATHS, BOTH GOVERNED. The simulator already supports two
    deterministic seed shapes, and which one applies is a property of persisted
    data rather than of the call:

      SAME-MATCHUP (`matchup` is not None) — the two teams are scheduled against
        each other, so the shared fixture is the natural identity. Seed is
        `Matchup.id * 1_000 + week`, and home/away orientation comes from that
        persisted row.

      CROSS-MATCHUP (`matchup` is None) — a legitimate wager between teams who
        are not playing each other (CORE-007 / AP-304). There is no shared Yahoo
        home/away to honour, so the engine's team-pair form is used INTENTIONALLY:
        `matchup_id=None` yields seed
        `challenger_team_id * 10_000 + challenged_team_id * 100 + week`, and the
        challenger is passed first so the first-side probability IS the
        challenger's. `matchup_id` is None by governed choice here, never because
        a caller omitted it — no caller can supply it at all.

    ORIENTATION IS DERIVED, NOT ASSUMED. On both paths the identities come from
    the challenge row and the side assignment from persisted data, so there is no
    fallback branch a bad input could fall through — the old `if ... else` on a
    caller-supplied id is gone.
    """
    from odds.odds_engine_headless import simulate_scores

    if matchup is not None:
        challenger_is_home = (matchup.home_team_id == challenge.challenger_team_id)
        if challenger_is_home:
            home_id,   away_id   = challenge.challenger_team_id, challenge.challenged_team_id
            home_line, away_line = inputs.challenger_starters, inputs.challenged_starters
        else:
            home_id,   away_id   = challenge.challenged_team_id, challenge.challenger_team_id
            home_line, away_line = inputs.challenged_starters, inputs.challenger_starters
        seed_matchup_id = matchup.id
    else:
        # Cross-matchup: the challenger takes the first position by construction,
        # so "home" here is the engine's ordering slot, not a Yahoo home fixture.
        challenger_is_home = True
        home_id,   away_id   = challenge.challenger_team_id, challenge.challenged_team_id
        home_line, away_line = inputs.challenger_starters, inputs.challenged_starters
        seed_matchup_id = None

    home_scores, away_scores = simulate_scores(
        home_id, away_id, list(home_line), list(away_line),
        challenge.week, model_config=config, matchup_id=seed_matchup_id,
    )
    # The configured tie rule: strict `>`, so a tied trial favours neither side.
    p_home = float((home_scores > away_scores).mean())
    p_away = 1.0 - p_home
    return (p_home, p_away) if challenger_is_home else (p_away, p_home)


# ── §5 Dynamic Handshake ──────────────────────────────────────────────────────

def handshake_dynamic_challenge(
    *,
    event_id: uuid.UUID,
    challenge_id: int,
    actor_team_id: int,
    db: Session,
    now: Optional[datetime] = None,
    postseason_state=None,
    resolver=None,
) -> HandshakeResult:
    """Dynamic acceptance. ONE transaction, ONE commit.

    ORDER, and every step's reason:
      1. Idempotency, then the challenge row lock, then BOTH Wallet scopes
         ascending (never inverted).
      2. Read the accepted proposal. The Anchor is the ORIGINAL ISSUER (A4).
      3. Pre-Handshake pooled reconciliation — this is still the pooled phase,
         so Spec 2's invariant applies unchanged.
      4. Derive the opponent's ceiling with the committed P3-D1 derivation, from
         the proposal's FROZEN probabilities.
      5. Revalidate BOTH capacities before any write.
      6. True up the issuer's pooled escrow to the accepted Anchor.
      7. FORWARD-MIGRATE pooled -> per-side Anchor account. No reverse leg.
      8. Fund the opponent's FULL ceiling into the per-side Derived account.
      9. Freeze ceilings + model identity on the challenge row.
     10. Spec 1's Dynamic accept transition.
     11. HANDSHAKE-EXIT ASSERTION, exact equality, independent reads.
     12. Commit once.

    Step 11 runs LAST and against re-read ledger balances, which is what makes it
    an independent check rather than a restatement of what step 7/8 intended.
    """
    existing = cf._find_event(db, event_id)
    if existing is not None:
        return _replayed_handshake(db, existing)

    # 1 — challenge first, then wallets ascending.
    challenge = _lock_challenge(db, challenge_id)
    _require_dynamic(challenge)
    if challenge.response_status not in spec1.OPEN_STATES:
        raise HandshakeStateError(
            f"Challenge {challenge_id} is {challenge.response_status!r}; only an "
            f"open challenge can be Handshaken.")
    prior     = challenge.response_status
    proposal  = cf._active_proposal(db, challenge)
    anchor    = cf.anchor_team_id(challenge, proposal)
    derived   = cf.derived_team_id(challenge, proposal)

    # WP1C — THE HANDSHAKE IS WHERE BOTH SIDES' MONEY IS COMMITTED, so the gate
    # belongs here rather than at Final Lock. Refusing later would mean an
    # ineligible pair had already had their escrow taken and then found the
    # wager unfinalizable — the same stranding failure
    # `resolve_shared_matchup_for_challenge` was written to prevent for
    # cross-matchup wagers. Placed after the replay check and after the
    # OPEN_STATES guard, before every write.
    cf._gate_postseason(db, league_id=challenge.league_id, week=challenge.week,
                        team_ids=(challenge.challenger_team_id,
                                  challenge.challenged_team_id),
                        postseason_state=postseason_state, resolver=resolver,
                        action="handshake")

    lock_funding_scopes(db, anchor, derived)

    anchor_target = cf._anchor_cents(proposal)

    # 3 — pooled reconciliation. Still pre-Handshake, so Spec 2 §11's invariant
    # governs unchanged; after the split below it deliberately no longer applies.
    pooled   = cf.challenge_escrow_balance(db, challenge_id)
    expected = cf.expected_challenge_escrow(db, challenge_id)
    if pooled != expected:
        raise cf.EscrowReconciliationError(
            f"Challenge {challenge_id}: pooled escrow holds {pooled} cents but "
            f"provenance says {expected}. Handshake refused; nothing posted.")

    # 4 — the opponent's maximum exposure, from the committed P3-D1 derivation.
    p_iss, p_opp = _proposal_probabilities(proposal)
    opponent_ceiling = derive_stakes(anchor_target, p_iss, p_opp).opponent_cents

    # 5 — REVALIDATE BOTH SIDES BEFORE ANY WRITE. Nothing above has written.
    required_top_up = max(0, anchor_target - pooled)
    if required_top_up > 0:
        issuer_capacity = cf.available_cents(db, anchor, challenge.week)
        if issuer_capacity < required_top_up:
            db.rollback()
            raise cf.AcceptanceCapacityError(
                f"Handshake refused: issuer team {anchor} needs a "
                f"{required_top_up}-cent Anchor top-up but has {issuer_capacity} "
                f"available. Nothing posted; challenge {challenge_id} remains "
                f"{prior!r}.")
    if opponent_ceiling > 0:
        opp_capacity = cf.available_cents(db, derived, challenge.week)
        if opp_capacity < opponent_ceiling:
            db.rollback()
            raise cf.AcceptanceCapacityError(
                f"Handshake refused: opponent team {derived} must fund its full "
                f"{opponent_ceiling}-cent Derived ceiling but has {opp_capacity} "
                f"available. Nothing posted; challenge {challenge_id} remains "
                f"{prior!r}.")

    event = cf._open_event(
        db, event_id=event_id, event_type=EVENT_HANDSHAKE, challenge=challenge,
        actor_identity=str(actor_team_id), proposal_id=proposal.id,
        prior_state=prior,
    )

    # 6 — true up the pooled escrow to the accepted Anchor.
    if required_top_up > 0:
        cf._fund(db, challenge=challenge, team_id=anchor,
                 required_cents=required_top_up,
                 destination=cf.challenge_escrow_account(challenge_id),
                 event=event, door=DOOR_HS_TOPUP)
    elif anchor_target < pooled:
        # Release before the split, so the split moves a settled balance —
        # the same release-before-migrate ordering the Locked path already uses.
        cf._reverse(db, challenge=challenge, amount_cents=pooled - anchor_target,
                    event=event, door=DOOR_HS_RELEASE)

    # 7 — FORWARD MIGRATION, pooled -> per-side Anchor (§7.2).
    #
    # NO REVERSE FUNDING LEG IS WRITTEN, and that is a correctness requirement
    # rather than an omission. A `reverse` leg means money returned to its
    # ORIGINAL FUNDING SOURCE; this money is not returned to anyone's wallet or
    # weekly-minimum account, it moves onward. Writing one would drive
    # remaining_reversible_cents to zero on the original fund legs, and any later
    # legitimate reversal would then fail closed against provenance that is
    # perfectly sound.
    ledger_post(
        [
            (cf.challenge_escrow_account(challenge_id), -anchor_target),
            (anchor_escrow_account(challenge_id),        anchor_target),
        ],
        door=DOOR_HS_SPLIT, session=db, protocol_event_id=event.id,
    )

    # 8 — the opponent funds its FULL ceiling, min-first, with ordered provenance.
    if opponent_ceiling > 0:
        cf._fund(db, challenge=challenge, team_id=derived,
                 required_cents=opponent_ceiling,
                 destination=derived_escrow_account(challenge_id),
                 event=event, door=DOOR_HS_DERIVED)

    # 9 — freeze. The issuer ceiling IS the accepted Anchor (§2 guard 3a).
    model_config = resolve_active_model_config()
    frozen_hash  = model_config_hash(model_config)
    challenge.dynamic_issuer_ceiling_cents   = anchor_target
    challenge.dynamic_opponent_ceiling_cents = opponent_ceiling
    challenge.dynamic_model_version_id       = model_config.model_version_id
    challenge.dynamic_model_config_hash      = frozen_hash
    challenge.dynamic_handshake_at           = datetime.now(timezone.utc)

    # 10 — Spec 1's Dynamic accept transition, inside this same transaction.
    spec1.accept_dynamic_proposal(
        challenge_id=challenge_id, actor_team_id=actor_team_id, db=db, now=now)

    # 11 — HANDSHAKE EXIT (MS-SIM-8), exact equality, two INDEPENDENT reads:
    # the balance from the ledger, the ceiling from the challenge row.
    anchor_balance  = _balance(db, anchor_escrow_account(challenge_id))
    derived_balance = _balance(db, derived_escrow_account(challenge_id))
    if anchor_balance != challenge.dynamic_issuer_ceiling_cents:
        raise HandshakeExitViolation(
            f"Handshake exit: anchor escrow {anchor_balance} != recorded issuer "
            f"ceiling {challenge.dynamic_issuer_ceiling_cents}. Nothing committed.")
    if derived_balance != challenge.dynamic_opponent_ceiling_cents:
        raise HandshakeExitViolation(
            f"Handshake exit: derived escrow {derived_balance} != recorded "
            f"opponent ceiling {challenge.dynamic_opponent_ceiling_cents}. "
            f"Nothing committed.")
    if challenge.dynamic_issuer_ceiling_cents != anchor_target:
        raise HandshakeExitViolation(
            f"Handshake exit: recorded issuer ceiling "
            f"{challenge.dynamic_issuer_ceiling_cents} is not the accepted "
            f"Anchor {anchor_target} (§2 guard 3a).")

    event.resulting_state = spec1.ACCEPTED
    event.result_code     = RESULT_OK
    db.flush()
    db.commit()

    return HandshakeResult(
        challenge_id           = challenge_id,
        event_id               = event_id,
        protocol_event_id      = event.id,
        anchor_cents           = anchor_target,
        issuer_ceiling_cents   = anchor_target,
        opponent_ceiling_cents = opponent_ceiling,
        model_version_id       = model_config.model_version_id,
        model_config_hash      = frozen_hash,
        replayed               = False,
        detail                 = "dynamic handshake: both ceilings funded",
    )


def _replayed_handshake(db: Session, event: ProtocolEvent) -> HandshakeResult:
    challenge = db.query(BeefChallenge).filter(
        BeefChallenge.id == event.challenge_id).first()
    return HandshakeResult(
        challenge_id           = event.challenge_id,
        event_id               = event.event_id,
        protocol_event_id      = event.id,
        anchor_cents           = challenge.dynamic_issuer_ceiling_cents or 0,
        issuer_ceiling_cents   = challenge.dynamic_issuer_ceiling_cents or 0,
        opponent_ceiling_cents = challenge.dynamic_opponent_ceiling_cents or 0,
        model_version_id       = challenge.dynamic_model_version_id or "",
        model_config_hash      = challenge.dynamic_model_config_hash or "",
        replayed               = True,
        detail                 = "replayed handshake",
    )


# ── §5 Informational refresh — NONBINDING, NO MONEY ───────────────────────────

def informational_refresh(
    *,
    challenge_id: int,
    p_issuer: float,
    p_opponent: float,
    db: Session,
) -> RefreshQuote:
    """A display-only re-quote between Handshake and Final Lock.

    WRITES NOTHING. No ledger posting, no escrow change, no ceiling change, no
    proposal mutation, no Bet, no ChallengeFinalLock, no claim, no state
    transition, no commit. Rev 9 §0: "informational refreshes are nonbinding —
    they move no money." The P3-D2 suite proves that by asserting the trial
    balance, both per-side escrow balances, the recorded ceilings and the ledger
    entry count are all byte-identical across a refresh.

    IT RESOLVES THE FROZEN MODEL, NEVER THE ACTIVE ONE. A refresh that quietly
    re-priced under a newly deployed model would show GMs a number their wager
    can never settle at, and would make the displayed line disagree with the one
    Final Lock will compute.

    Probabilities are passed IN rather than simulated here: the caller owns
    lineup/projection retrieval, which keeps this function pure enough to prove
    it writes nothing.
    """
    challenge = db.query(BeefChallenge).filter(
        BeefChallenge.id == challenge_id).one()
    _require_dynamic(challenge)
    if challenge.dynamic_model_version_id is None:
        raise HandshakeStateError(
            f"Challenge {challenge_id} has not Handshaken; there is no frozen "
            f"model to refresh under.")

    # Resolve the FROZEN version and prove the registry entry is unedited.
    config = resolve_and_verify(challenge.dynamic_model_version_id,
                                challenge.dynamic_model_config_hash)

    anchor_cents     = int(challenge.dynamic_issuer_ceiling_cents or 0)
    opponent_ceiling = int(challenge.dynamic_opponent_ceiling_cents or 0)
    indicative = derive_stakes(anchor_cents, p_issuer, p_opponent).opponent_cents
    capped     = indicative > opponent_ceiling

    return RefreshQuote(
        challenge_id             = challenge_id,
        model_version_id         = config.model_version_id,
        p_issuer                 = p_issuer,
        p_opponent               = p_opponent,
        indicative_derived_cents = min(indicative, opponent_ceiling),
        opponent_ceiling_cents   = opponent_ceiling,
        capped                   = capped,
    )


# ── §5.2 Phase 1 — the durable, challenge-scoped claim ────────────────────────

def acquire_final_lock_claim(
    *,
    challenge_id: int,
    worker_id: str,
    db: Session,
    now: Optional[datetime] = None,
) -> ClaimOutcome:
    """Phase 1. Commits BY ITSELF, before any simulation or money movement.

    ACQUISITION IS A SINGLE ATOMIC STATEMENT, NEVER `SELECT ... FOR UPDATE` ON A
    POSSIBLY-ABSENT ROW. P1-L7 established why: a `FOR UPDATE` matching zero rows
    locks nothing and raises nothing, which is exactly how a worker comes to
    believe it was serialized when it was not.

    `UNIQUE(challenge_id)` IS THE MUTEX. `ProtocolEvent.event_id` cannot serve:
    two workers presenting DIFFERENT event UUIDs for the SAME challenge both
    satisfy event-id uniqueness and, absent this claim, both would proceed.
    """
    moment  = now or datetime.now(timezone.utc)
    expires = moment + FINAL_LOCK_CLAIM_TTL

    # Fresh acquisition. Exactly one concurrent worker gets rowcount 1.
    row = db.execute(
        text("""
            INSERT INTO challenge_final_lock_claims
                   (challenge_id, status, claimed_by, claimed_at,
                    claim_expires_at, attempt_count, created_at)
            VALUES (:cid, 'claimed', :worker, :moment, :expires, 1, :moment)
            ON CONFLICT (challenge_id) DO NOTHING
            RETURNING id, attempt_count
        """),
        {"cid": challenge_id, "worker": worker_id,
         "moment": moment, "expires": expires},
    ).first()
    if row is not None:
        db.commit()
        return ClaimOutcome(challenge_id, True, "claimed", row[0], row[1],
                            "fresh acquisition")

    # Someone already holds a row. Read it and branch (§5.8).
    existing = (db.query(ChallengeFinalLockClaim)
                .filter(ChallengeFinalLockClaim.challenge_id == challenge_id)
                .one())
    if existing.status == "completed":
        db.rollback()
        return ClaimOutcome(challenge_id, False, "completed", existing.id,
                            existing.attempt_count,
                            "already completed — return the original result")

    # Reclaim, conditionally. THE PREDICATE IS THE MUTEX HERE: a unique index
    # does nothing on an UPDATE, so exclusion rides on the WHERE clause and the
    # rowcount. Two workers racing the same stale claim produce exactly one 1.
    reclaimed = db.execute(
        text("""
            UPDATE challenge_final_lock_claims
               SET claimed_by = :worker,
                   previous_claimed_by = claimed_by,
                   claimed_at = :moment,
                   last_reclaimed_at = :moment,
                   claim_expires_at = :expires,
                   attempt_count = attempt_count + 1,
                   status = 'claimed',
                   failure_reason = NULL,
                   updated_at = :moment
             WHERE challenge_id = :cid
               AND status <> 'completed'
               AND (status = 'failed' OR claim_expires_at < :moment)
            RETURNING id, attempt_count
        """),
        {"cid": challenge_id, "worker": worker_id,
         "moment": moment, "expires": expires},
    ).first()
    if reclaimed is not None:
        db.commit()
        return ClaimOutcome(challenge_id, True, "claimed", reclaimed[0],
                            reclaimed[1], "reclaimed in place")

    db.rollback()
    return ClaimOutcome(challenge_id, False, existing.status, existing.id,
                        existing.attempt_count,
                        "a live, non-stale claim is held by another worker")


def _fail_claim(db: Session, challenge_id: int, reason: str) -> None:
    """Release ownership deliberately (§5.3 `failed`).

    Committed on its own so the release survives the Phase-2 rollback that
    accompanies it — the whole point of `failed` is that a worker hitting a
    deterministic error does not force everyone else to wait out the full
    staleness window for a claim whose owner is already gone.
    """
    db.rollback()
    db.execute(
        text("""
            UPDATE challenge_final_lock_claims
               SET status = 'failed', failure_reason = :reason,
                   updated_at = :moment
             WHERE challenge_id = :cid AND status <> 'completed'
        """),
        {"cid": challenge_id, "reason": reason[:480],
         "moment": datetime.now(timezone.utc)},
    )
    db.commit()


# ── §5.1 Phase 2 — the single atomic economic transaction ─────────────────────

def run_final_lock(
    *,
    event_id: uuid.UUID,
    challenge_id: int,
    worker_id: str,
    final_inputs: FinalLockInputs,
    db: Session,
    now: Optional[datetime] = None,
) -> FinalLockResult:
    """Final Lock: Phase 1 claim (committed separately), then Phase 2 (one
    transaction, one commit).

    THE ECONOMIC API TAKES INPUTS, NOT PROBABILITIES (B-1). There is deliberately
    no `p_issuer_final` / `p_opponent_final` parameter anywhere on this path. The
    probabilities that price the Derived refund are produced INSIDE the claimed
    execution, by one official simulation run under the model resolved and
    hash-verified from the challenge row. A caller can choose the lineups — those
    are live inputs and are supposed to be chosen — but it cannot choose the
    numbers the Adjustment runs on.

    PHASE 2 IS NOT SPLIT, for convenience or for progress reporting. Everything
    from the guard through the claim flip commits together, so a failure anywhere
    rolls back all of it and leaves the durable claim recoverable with escrow
    exactly as the Handshake left it — which is precisely what lets the recovering
    worker's strict guard-3 equality still hold.
    """
    # ── Phase 1 ───────────────────────────────────────────────────────────
    claim = acquire_final_lock_claim(challenge_id=challenge_id,
                                     worker_id=worker_id, db=db, now=now)
    if not claim.owned:
        if claim.status == "completed":
            return _replayed_final_lock(db, challenge_id)
        raise FinalLockNotOwnedError(
            f"Challenge {challenge_id}: {claim.detail}. Not executing.")

    # ── Phase 2 ───────────────────────────────────────────────────────────
    try:
        return _final_lock_phase_2(
            db, event_id=event_id, challenge_id=challenge_id,
            worker_id=worker_id, final_inputs=final_inputs,
        )
    except (ModelIntegrityError, FinalLockGuardViolation,
            DynamicPricingError) as exc:
        # §5.3 — a DETERMINISTIC error ("bad projection data, a failed §2 guard
        # 3, an invariant violation") marks the claim `failed` and releases
        # ownership at once, instead of forcing every other worker to wait out
        # the full staleness window for a claim whose owner is already gone.
        # DynamicPricingError belongs here: a probability pair that does not sum
        # to 1, or a negative cent quantity, is bad input that will fail the same
        # way on every retry, not a transient fault.
        #
        # _fail_claim rolls Phase 2 back BEFORE writing the status, so the
        # release commits alone and no economic write survives with it.
        _fail_claim(db, challenge_id, f"{type(exc).__name__}: {exc}")
        raise
    except Exception:
        db.rollback()
        raise


def _final_lock_phase_2(
    db: Session,
    *,
    event_id: uuid.UUID,
    challenge_id: int,
    worker_id: str,
    final_inputs: FinalLockInputs,
) -> FinalLockResult:
    # 1 — revalidate ownership under this transaction.
    claim = (db.query(ChallengeFinalLockClaim)
             .filter(ChallengeFinalLockClaim.challenge_id == challenge_id).one())
    if claim.status == "completed":
        return _replayed_final_lock(db, challenge_id)
    if claim.claimed_by != worker_id:
        raise FinalLockNotOwnedError(
            f"Challenge {challenge_id}: claim is held by {claim.claimed_by!r}, "
            f"not {worker_id!r}.")

    # 2/3 — challenge row, then Wallet rows ascending by team_id.
    challenge = _lock_challenge(db, challenge_id)
    _require_dynamic(challenge)
    proposal = db.query(BeefProposal).filter(
        BeefProposal.id == challenge.accepted_proposal_id).first()
    if proposal is None:
        raise FinalLockGuardViolation(
            f"Challenge {challenge_id} has no accepted proposal; it has not "
            f"Handshaken.")
    anchor  = cf.anchor_team_id(challenge, proposal)
    derived = cf.derived_team_id(challenge, proposal)
    lock_funding_scopes(db, anchor, derived)

    # 4 — legitimate entry state.
    if challenge.response_status != spec1.ACCEPTED:
        raise FinalLockGuardViolation(
            f"Challenge {challenge_id} is {challenge.response_status!r}; only an "
            f"accepted Dynamic challenge may Final-Lock.")
    if challenge.dynamic_handshake_at is None:
        raise FinalLockGuardViolation(
            f"Challenge {challenge_id} has no Handshake record.")
    if db.query(ChallengeFinalLock).filter(
            ChallengeFinalLock.challenge_id == challenge_id).first() is not None:
        return _replayed_final_lock(db, challenge_id)

    anchor_cents     = int(challenge.dynamic_issuer_ceiling_cents or 0)
    opponent_ceiling = int(challenge.dynamic_opponent_ceiling_cents or 0)
    accepted_anchor  = cf._anchor_cents(proposal)

    # ── §2 GUARD 3 + 3a — OVERSHOOT-B. Before simulation, before any money. ──
    anchor_balance  = _balance(db, anchor_escrow_account(challenge_id))
    derived_balance = _balance(db, derived_escrow_account(challenge_id))
    if anchor_cents != accepted_anchor:
        raise FinalLockGuardViolation(
            f"§2 guard 3a: recorded issuer ceiling {anchor_cents} is not the "
            f"accepted Anchor {accepted_anchor}. Refusing; nothing posted.")
    if anchor_balance != anchor_cents:
        # STRICT EQUALITY, BOTH DIRECTIONS. An issuer balance ABOVE its ceiling
        # is not a fundable overshoot to be refunded — Handshake exit required
        # equality and the window contains no authorized escrow writer, so it
        # has no legitimate cause. Refunding it would move an unexplained balance
        # into a GM's wallet and erase the evidence of whatever produced it.
        raise FinalLockGuardViolation(
            f"§2 guard 3: anchor escrow {anchor_balance} != recorded issuer "
            f"ceiling {anchor_cents}. Invariant violation with no authorized "
            f"cause. Refusing; nothing posted, nothing normalized.")
    if derived_balance != opponent_ceiling:
        raise FinalLockGuardViolation(
            f"§2 guard 3: derived escrow {derived_balance} != recorded opponent "
            f"ceiling {opponent_ceiling}. Refusing; nothing posted.")

    # ── B-3 / B-4 — GOVERNED IDENTITY, BEFORE THE MODEL AND BEFORE THE SIM ──
    #
    # Returns the shared Matchup when the two participants are scheduled against
    # each other, or None for a legitimate CROSS-MATCHUP challenge (CORE-007 /
    # AP-304). Both are governed answers. Real corruption — several rows claiming
    # the same pair share a matchup, or a malformed row — raises here, while
    # nothing has been simulated and no money has moved.
    matchup = resolve_shared_matchup_for_challenge(db, challenge)

    # 5 — resolve the FROZEN model and prove it is unedited. Never substitute.
    try:
        config = resolve_and_verify(challenge.dynamic_model_version_id,
                                    challenge.dynamic_model_config_hash)
    except (UnknownModelVersionError, ModelConfigHashMismatchError) as exc:
        raise ModelIntegrityError(
            f"Challenge {challenge_id}: the Handshake-frozen model is not "
            f"reproducible — {exc}. Final Lock refuses: no substitution, no "
            f"simulation, no Adjustment, no refund, no migration, no frozen "
            f"result, no Pending transition."
        ) from exc

    # 6 — THE ONE OFFICIAL SIMULATION, under the config just resolved and
    # hash-verified. This is the only place Final-Lock probabilities come from.
    #
    # It runs AFTER the guards and AFTER the model verification, and BEFORE any
    # money moves, so the chain the audit record has to prove holds by
    # construction:
    #
    #   probabilities passed to adjust_escrow
    #     == probabilities returned by this call
    #     == a simulation run under `config`
    #     == resolve_and_verify(challenge.dynamic_model_version_id,
    #                           challenge.dynamic_model_config_hash)
    #
    # Resolving the model AFTER receiving probabilities — which is what the
    # previous implementation effectively did — proves none of that: it confirms
    # a model exists without establishing that it produced anything.
    p_issuer_final, p_opponent_final = _run_official_simulation(
        config=config, challenge=challenge, matchup=matchup,
        inputs=final_inputs)

    # 7 — the Adjustment, from the committed P3-D1 pure function, on exactly the
    # probabilities the simulation above produced.
    adj = adjust_escrow(
        anchor_cents                  = anchor_cents,
        p_issuer_final                = p_issuer_final,
        p_opponent_final              = p_opponent_final,
        issuer_ceiling_cents          = anchor_cents,
        opponent_ceiling_cents        = opponent_ceiling,
        issuer_escrow_balance_cents   = anchor_balance,
        opponent_escrow_balance_cents = derived_balance,
    )
    # Guards 3+3a make this identically zero; asserted, never paid.
    if adj.refund_issuer_cents != 0:
        raise FinalLockGuardViolation(
            f"Issuer refund computed as {adj.refund_issuer_cents}; the "
            f"legitimate path is identically zero. Refusing.")

    event = cf._open_event(
        db, event_id=event_id, event_type=EVENT_FINAL_LOCK, challenge=challenge,
        actor_identity="system", proposal_id=proposal.id,
        prior_state=spec1.ACCEPTED,
    )

    # 7 — REFUND BEFORE MIGRATION (§5.1, load-bearing). Derived side only.
    # Reuses Spec 2's strict reverse-leg machinery so the refund returns to the
    # opponent's ORIGINAL funding sources; with wallet-only funding that reduces
    # exactly to guard 5's named escrow->wallet pair.
    if adj.refund_opponent_cents > 0:
        cf._reverse(db, challenge=challenge,
                    amount_cents=adj.refund_opponent_cents,
                    event=event, door=DOOR_FL_REFUND,
                    account=derived_escrow_account(challenge_id))

    # 8 — verify per-side balances are exactly the final stakes before migrating.
    anchor_after  = _balance(db, anchor_escrow_account(challenge_id))
    derived_after = _balance(db, derived_escrow_account(challenge_id))
    if anchor_after != adj.issuer_final_cents or derived_after != adj.opponent_final_cents:
        raise FinalLockGuardViolation(
            f"Post-refund escrow {anchor_after}/{derived_after} does not equal "
            f"final exposure {adj.issuer_final_cents}/{adj.opponent_final_cents}.")

    # 9 — FINAL-LOCK ODDS (B-2). Derived from the official probabilities above,
    # NOT carried over from the accepted proposal.
    #
    # Dynamic freezes the model and the ceilings at Handshake but leaves the ODDS
    # live until here (Rev 9 §0). The Bet rows previously took
    # `proposal.anchor_odds` / `proposal.derived_odds`, which are the Handshake
    # prices — so a Dynamic wager settled and displayed at odds the Final-Lock
    # simulation had already superseded.
    issuer_ml   = _signed_american(p_issuer_final)
    opponent_ml = _signed_american(p_opponent_final)
    # Bet.odds is DECIMAL (see _ml_to_decimal). The immutable record keeps the
    # American integers; the Bet rows get the decimal form its settlement and
    # display contract expects.
    issuer_odds_dec   = _ml_to_decimal(issuer_ml)
    opponent_odds_dec = _ml_to_decimal(opponent_ml)

    # 10 — Bet rows: accepted frozen MARKET terms (P1-L4A's per-side resolver)
    # priced at the FINAL-LOCK odds.
    anchor_bet  = cf._create_bet(db, challenge=challenge, proposal=proposal,
                                 team_id=anchor, stake_cents=adj.issuer_final_cents,
                                 odds=issuer_odds_dec)
    derived_bet = cf._create_bet(db, challenge=challenge, proposal=proposal,
                                 team_id=derived, stake_cents=adj.opponent_final_cents,
                                 odds=opponent_odds_dec)

    # 10 — migrate each per-side account into ITS OWN Bet escrow. Forward
    # migrations, no reverse legs, per-side identity preserved end to end.
    ledger_post(
        [(anchor_escrow_account(challenge_id), -adj.issuer_final_cents),
         (f"escrow:{anchor_bet.id}",            adj.issuer_final_cents)],
        door=DOOR_FL_MIGRATE, session=db, protocol_event_id=event.id,
    )
    if adj.opponent_final_cents > 0:
        ledger_post(
            [(derived_escrow_account(challenge_id), -adj.opponent_final_cents),
             (f"escrow:{derived_bet.id}",            adj.opponent_final_cents)],
            door=DOOR_FL_MIGRATE, session=db, protocol_event_id=event.id,
        )

    # 11 — the immutable frozen result. Records WHAT EXECUTED, then asserts it
    # equals what was frozen — writing the promised id would record an intention
    # rather than an observation.
    executed_hash = model_config_hash(config)
    final_lock = ChallengeFinalLock(
        challenge_id               = challenge_id,
        final_locked_at            = datetime.now(timezone.utc),
        executed_model_version_id  = config.model_version_id,
        executed_model_config_hash = executed_hash,
        projection_source_id       = final_inputs.projection_source_id,
        projection_dataset_version = final_inputs.projection_dataset_version,
        projection_captured_at     = datetime.now(timezone.utc),
        simulations                = config.n_sims,
        p_issuer_final             = p_issuer_final,
        p_opponent_final           = p_opponent_final,
        # B-2 — the OFFICIAL final odds, frozen here for audit in American form
        # regardless of the decimal representation the Bet rows carry.
        issuer_moneyline           = issuer_ml,
        opponent_moneyline         = opponent_ml,
        anchor_cents               = adj.issuer_final_cents,
        derived_raw_cents          = adj.opponent_derived_raw_cents,
        derived_final_cents        = adj.opponent_final_cents,
        ceiling_applied            = adj.ceiling_applied,
        derived_refund_cents       = adj.refund_opponent_cents,
        final_funded_escrow_cents  = adj.final_funded_escrow_cents,
        wager_type                 = challenge.wager_type,
        line                       = proposal.line,
        side                       = proposal.side,
        anchor_bet_id              = anchor_bet.id,
        derived_bet_id             = derived_bet.id,
        protocol_event_id          = event.id,
    )
    db.add(final_lock)
    db.flush()
    if final_lock.executed_model_version_id != challenge.dynamic_model_version_id \
            or final_lock.executed_model_config_hash != challenge.dynamic_model_config_hash:
        raise ModelIntegrityError(
            f"Executed model {final_lock.executed_model_version_id}/"
            f"{final_lock.executed_model_config_hash} differs from the frozen "
            f"identity {challenge.dynamic_model_version_id}/"
            f"{challenge.dynamic_model_config_hash}.")

    # 12 — Pending semantics via the existing vocabulary: the Bet rows are
    # 'pending' and the challenge now points at them. No new response_status.
    challenge.challenger_bet_id = (anchor_bet.id if anchor == challenge.challenger_team_id
                                   else derived_bet.id)
    challenge.challenged_bet_id = (derived_bet.id if derived == challenge.challenged_team_id
                                   else anchor_bet.id)

    event.resulting_state = "final_locked"
    event.result_code     = RESULT_OK

    # 13 — flip the claim. The two biconditional CHECKs make half-completion
    # unrepresentable, so this cannot claim success without its result.
    claim.status            = "completed"
    claim.completed_at      = datetime.now(timezone.utc)
    claim.final_lock_id     = final_lock.id
    claim.protocol_event_id = event.id
    claim.updated_at        = claim.completed_at

    db.flush()
    db.commit()

    return FinalLockResult(
        challenge_id         = challenge_id,
        final_lock_id        = final_lock.id,
        event_id             = event_id,
        protocol_event_id    = event.id,
        p_issuer_final       = p_issuer_final,
        p_opponent_final     = p_opponent_final,
        anchor_cents         = adj.issuer_final_cents,
        derived_raw_cents    = adj.opponent_derived_raw_cents,
        derived_final_cents  = adj.opponent_final_cents,
        derived_refund_cents = adj.refund_opponent_cents,
        ceiling_applied      = adj.ceiling_applied,
        anchor_bet_id        = anchor_bet.id,
        derived_bet_id       = derived_bet.id,
        replayed             = False,
        detail               = "final locked",
    )


def _replayed_final_lock(db: Session, challenge_id: int) -> FinalLockResult:
    """§5.7 — return the ORIGINAL committed result. No simulation, no Adjustment,
    no posting, no second Bet, no second ChallengeFinalLock."""
    db.rollback()
    fl = (db.query(ChallengeFinalLock)
          .filter(ChallengeFinalLock.challenge_id == challenge_id).one())
    return FinalLockResult(
        challenge_id         = challenge_id,
        final_lock_id        = fl.id,
        event_id             = uuid.UUID(int=0),
        protocol_event_id    = fl.protocol_event_id,
        p_issuer_final       = fl.p_issuer_final,
        p_opponent_final     = fl.p_opponent_final,
        anchor_cents         = fl.anchor_cents,
        derived_raw_cents    = fl.derived_raw_cents,
        derived_final_cents  = fl.derived_final_cents,
        derived_refund_cents = fl.derived_refund_cents,
        ceiling_applied      = bool(fl.ceiling_applied),
        anchor_bet_id        = fl.anchor_bet_id,
        derived_bet_id       = fl.derived_bet_id,
        replayed             = True,
        detail               = "replayed — original committed result",
    )
