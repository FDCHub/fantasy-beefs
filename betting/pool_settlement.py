"""
Common Pool settlement — POR Rev1.3 §5/§6, Owner Rulings R1-R3, Scope §E/§G1.

TWO LAYERS, KEPT SEPARATE. Owner Ruling R2 is explicit that subject evaluation
and ticket resolution are different questions, and collapsing them is the defect
the ruling exists to prevent:

    LAYER 1  which SUBJECT won?      betting/pool_census.py, POR §6.2
    LAYER 2  did any GM pick it?     this module, Owner Ruling R2

`ZERO_ELIGIBLE_CLAIMS` at layer 1 means NO SUBJECT qualified — a QUALIFIER
predicate that nothing satisfied. Zero winning TICKETS at layer 2 means a winner
was determined and no eligible GM selected it. Both end in rollover-or-sweep,
but they are distinct causes with distinct event types, distinct audit meaning,
and distinct preconditions. A single "no winner" branch would report a
predicate that nobody could satisfy identically to a week where twelve GMs all
guessed wrong.

THE §6.3 ALLOCATION IS AN ALGORITHM, NOT A POLICY DIRECTION (POR §6.3, binding):

    base_share_cents = pot_cents // winner_count
    remainder_count  = pot_cents %  winner_count
    order winners by CANONICAL GM IDENTIFIER, ASCENDING
    every winner gets base_share_cents
    the first remainder_count winners each get ONE additional cent

The ordering key is the canonical GM identifier and nothing else — never a
display name, never claim order, never database return order. An allocation
whose TOTALS are right but whose ORDER came from a query is non-conformant even
though it balances, which is why Scope §H scenario 12b exists as the
discriminating control.

THE §6.3 REMAINDER NEVER GOES TO CHAMPIONSHIP. That is §6.1's remainder, a
different quantity in a different direction. The stale GE-1045 / LED-332
remainder-to-championship behavior is not implemented and must not be.

ATOMICITY AND EVENT-KEYED IDEMPOTENCY GOVERN TOGETHER; NEITHER SUBSTITUTES FOR
THE OTHER (POR §6.4, §G1). Every posting and its `settled` transition happen in
ONE transaction, AND every economic effect inserts a row into
`pool_economic_event` under a uniqueness constraint. The row lock taken below is
a THIRD, supplementary measure: it serializes concurrent attempts within one
process lifetime, and §6.4 is explicit that it "may supplement this protocol. It
cannot replace it."
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from betting.finality_gate import require_week_final
from betting.pool_catalog import spec_from_row
from betting.pool_census import (
    CLASSIFICATION_CLAIMS_PRESENT,
    CLASSIFICATION_ZERO_ELIGIBLE_CLAIMS,
    PoolOutcome,
    classify_pool,
    require_settleable,
)
from betting.pool_errors import PoolSettlementRefusedError
from betting.pool_season_boundary import is_final_week
from betting.pool_subjects import league_weekly_structure
from economy.championship_pots import terminal_pool_destination
from ledger.ledger import (_balance_of_in_session, balance_of,
                           lock_funding_scopes, post as ledger_post)

# ── Economic event types (§G1, extended for the two R2 causes) ────────────────
EVENT_WINNER_DISTRIBUTION = "WINNER_DISTRIBUTION"
EVENT_SUBJECT_ZERO_CLAIM_ROLLOVER = "SUBJECT_ZERO_CLAIM_ROLLOVER"
EVENT_SUBJECT_ZERO_CLAIM_CHAMPIONSHIP_SWEEP = "SUBJECT_ZERO_CLAIM_CHAMPIONSHIP_SWEEP"
EVENT_TICKET_ZERO_WINNER_ROLLOVER = "TICKET_ZERO_WINNER_ROLLOVER"
EVENT_TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP = "TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP"
EVENT_ROLLOVER_EXPIRY_SWEEP = "ROLLOVER_EXPIRY_SWEEP"

DOOR_WINNER_DISTRIBUTION = "pool_winner_distribution"
DOOR_CHAMPIONSHIP_SWEEP = "pool_championship_sweep"
DOOR_ROLLOVER_EXPIRY = "pool_rollover_expiry"


class PoolSettlementError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_INSTANCE_NOT_FOUND = "INSTANCE_NOT_FOUND"
REASON_NOT_FUNDED = "NOT_FUNDED"
REASON_NO_WALLET = "NO_WALLET"
REASON_CONSERVATION = "CONSERVATION_VIOLATION"


@dataclass(frozen=True)
class SettlementResult:
    pool_instance_id: int
    definition_key: str
    classification: str
    census: Mapping[str, object]
    winning_subject_ids: tuple[int, ...]
    winning_team_ids: tuple[int, ...]
    pot_cents: int
    distributed_cents: int
    rolled_over_cents: int
    swept_to_championship_cents: int
    event_type: str | None
    replayed: bool


# ── POR §6.3 ──────────────────────────────────────────────────────────────────

def allocate_even_split(pot_cents: int,
                        winner_gm_ids: Sequence[int]) -> dict[int, int]:
    """The §6.3 algorithm, exactly. PURE — no session, no clock, no randomness.

    Returns {canonical_gm_id: cents}. Properties this guarantees, each of which
    §6.3 states as binding:

      * conservation  base * n + remainder == pot_cents; every cent distributed
      * ordering      by canonical GM identifier ASCENDING, nothing else
      * determinism   a pure function of (pot_cents, ordered winner set), so a
                      retry reproduces the identical per-GM allocation cent for
                      cent

    `sorted()` on integer GM ids is the whole ordering rule. It is separated out
    as its own function precisely so a test can assert against it with fixtures
    whose insertion order and display names deliberately disagree with the
    canonical order — Scope §H scenario 12b. An implementation that splits
    correctly but orders by query result passes 12a and 12c and fails 12b.
    """
    ordered = sorted(winner_gm_ids)
    n = len(ordered)
    if n == 0:
        # Never reachable from settle(): the zero-winner path is decided before
        # allocation is called. Guarding anyway, because a divide-by-zero here
        # is exactly what Owner Ruling R2 forbids ("never divide by zero").
        raise PoolSettlementError(
            "EMPTY_WINNER_SET",
            "allocate_even_split called with no winners; the zero-winning-ticket "
            "path must be taken before allocation (Owner Ruling R2).",
        )
    base = pot_cents // n
    remainder = pot_cents % n
    allocation = {gm_id: base for gm_id in ordered}
    for gm_id in ordered[:remainder]:
        allocation[gm_id] += 1
    return allocation


# ── Conservation ──────────────────────────────────────────────────────────────

def unresolved_pool_cents(db, *, league_id: int, season: int) -> int:
    """Cents this league's Pools still hold, derived from instance state.

    THE INVARIANT this pairs with:

        balance_of(f"pool:{league_id}")
            == Σ pot_cents      over UNSETTLED instances
             + Σ rollover_cents over SETTLED   instances

    An unsettled instance holds its whole pot. A settled instance holds only its
    live carry: a distributed pot drained to zero, a swept pot left the account
    entirely, and a rolled pot is carried in `rollover_cents` while `pot_cents`
    remains as the historical record of what the pot was. Reading both columns
    on both states would double-count a rollover.
    """
    from db.schema import PoolInstance

    rows = (db.query(PoolInstance)
            .filter(PoolInstance.league_id == league_id,
                    PoolInstance.season == season)
            .all())
    total = 0
    for row in rows:
        if row.settled:
            total += int(row.rollover_cents or 0)
        else:
            total += int(row.pot_cents or 0)
    return total


def assert_pool_conservation(db, *, league_id: int, season: int,
                             in_session: bool = False) -> int:
    """Prove the ledger and the instance state agree. Returns the balance.

    Called after settlement so a divergence surfaces at the transaction that
    caused it rather than weeks later. This is arithmetic against REAL ledger
    entries, never an inference from a status column — POR §13's "Do not infer
    conservation merely because status is settled".

    `in_session` SELECTS WHICH TRANSACTION THE LEDGER SIDE IS READ FROM, and it
    exists because the two sides of this comparison were never read from the
    same place. `unresolved_pool_cents` has always used the caller's `db`, so it
    sees uncommitted instance state; `balance_of` opens its OWN session and sees
    only COMMITTED entries. For a caller that commits before asserting, the two
    agree and the default is correct. For a caller that asserts INSIDE its own
    open transaction — Season Close, which by design does not commit until the
    whole close is written — the ledger side is stale by exactly the amount that
    caller just posted, and the assertion would refuse the very transaction it
    was meant to certify. Passing `in_session=True` reads both sides from `db`,
    which is what makes this a real comparison rather than one across two
    different points in time.

    The default is False so every existing caller keeps its exact behaviour.
    """
    balance = (_balance_of_in_session(db, f"pool:{league_id}") if in_session
               else balance_of(f"pool:{league_id}"))
    expected = unresolved_pool_cents(db, league_id=league_id, season=season)
    if balance != expected:
        raise PoolSettlementError(
            REASON_CONSERVATION,
            f"pool:{league_id} holds {balance} cents but unsettled pots plus "
            f"live carries total {expected}. Refusing to proceed against an "
            f"unreconciled pool account.",
        )
    return balance


# ── Settlement ────────────────────────────────────────────────────────────────

def _record_event(db, *, instance, event_type: str, posting_id,
                  amount_cents: int, now: datetime):
    from db.schema import PoolEconomicEvent

    event = PoolEconomicEvent(
        league_id=instance.league_id, season=instance.season,
        week=instance.week, pool_instance_id=instance.id,
        event_type=event_type, posting_id=posting_id,
        amount_cents=amount_cents, created_at=now,
    )
    db.add(event)
    # Flush INSIDE the settlement transaction so a replay collides at the
    # uniqueness constraint here, before any further work, rather than at
    # commit time where the failure is harder to attribute.
    db.flush()
    return event


def _replay_result(db, instance) -> SettlementResult:
    """Reconstruct a committed settlement without reposting anything.

    Scope §H scenario 10c: "Replaying the identical settlement request produces
    no second posting and no second settled transition." The reconstruction
    reads the persisted event row, so the answer comes from what actually
    happened rather than from re-deriving what should have happened."""
    from db.schema import PoolEconomicEvent

    event = (db.query(PoolEconomicEvent)
             .filter(PoolEconomicEvent.pool_instance_id == instance.id)
             .order_by(PoolEconomicEvent.id.desc())
             .first())
    event_type = event.event_type if event else None
    amount = int(event.amount_cents) if event else 0

    swept = amount if event_type in (
        EVENT_SUBJECT_ZERO_CLAIM_CHAMPIONSHIP_SWEEP,
        EVENT_TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP,
        EVENT_ROLLOVER_EXPIRY_SWEEP) else 0

    return SettlementResult(
        pool_instance_id=instance.id,
        definition_key=instance.definition_key,
        classification=instance.settlement_classification or "",
        census={}, winning_subject_ids=(), winning_team_ids=(),
        pot_cents=int(instance.pot_cents or 0),
        distributed_cents=int(instance.distributed_cents or 0),
        rolled_over_cents=int(instance.rollover_cents or 0),
        swept_to_championship_cents=swept,
        event_type=event_type, replayed=True,
    )


def settle_pool_instance(db, *, pool_instance_id: int, stat_source,
                         threshold_override: int | None = None,
                         now: datetime | None = None) -> SettlementResult:
    """Settle one pool occurrence. Does NOT commit — the caller owns the
    transaction, and that is what makes posting-plus-`settled` atomic.

    A caller that commits between the posting and the flag has already violated
    POR §6.4 requirement 1 regardless of what this function does, which is why
    the commit is deliberately not taken here.
    """
    from db.schema import League, PoolDefinition, PoolInstance, Wallet

    now = now or datetime.now(timezone.utc)

    # Row lock FIRST. A SUPPLEMENT to event-keyed idempotency, never a
    # substitute (§6.4). It serializes concurrent settlements of this instance
    # inside one process lifetime; the uniqueness constraint is what survives a
    # crash, a released lock, and a retry from a different process.
    instance = (db.query(PoolInstance)
                .filter(PoolInstance.id == pool_instance_id)
                .with_for_update()
                .first())
    if instance is None:
        raise PoolSettlementError(
            REASON_INSTANCE_NOT_FOUND,
            f"pool instance {pool_instance_id} not found")

    if instance.settled:
        return _replay_result(db, instance)

    # ── S6 §8 — ECONOMIC FINALITY PRECONDITION ───────────────────────────────
    #
    # After the replay check and before any economic work, so an ALREADY
    # SETTLED instance still replays idempotently — a settled Pool's history
    # must not become unreadable because the finality gate was added later.
    #
    # Placed here rather than only in the week-level loop so a direct
    # settle_pool_instance() call is no less safe than a settle_week() one.
    # §8 requires exactly that: "A manual/API settlement path must be no less
    # safe than the Tuesday pipeline."
    #
    # Note this is a STRICTER gate than the census alone. The census asks "is
    # every subject evaluable"; a pre-kickoff week where the provider has
    # written matchup rows and the stat feed reports zeros would answer yes.
    # Finality asks the different question the money actually depends on.
    require_week_final(db, league_id=instance.league_id, week=instance.week,
                       context=f"settle_pool_instance({pool_instance_id})")

    league = db.query(League).filter(League.id == instance.league_id).first()
    row = (db.query(PoolDefinition)
           .filter(PoolDefinition.key == instance.definition_key).first())
    spec = spec_from_row(row)

    # ── LAYER 1: subject census and classification, BEFORE any economic work ─
    structure = league_weekly_structure(db, league_id=instance.league_id,
                                        week=instance.week, scope=spec.scope)
    subjects = stat_source.subjects_for(
        league_id=instance.league_id, season=instance.season,
        week=instance.week, structure=structure)
    outcome = classify_pool(spec, structure, subjects,
                            threshold_override=threshold_override)
    # Raises a named domain error on any fail-closed classification. Nothing has
    # been posted, `settled` is untouched, and the instance stays unsettled.
    require_settleable(outcome, definition_key=spec.key,
                       league_id=instance.league_id, season=instance.season,
                       week=instance.week)

    pot_cents = int(instance.pot_cents or 0)
    if pot_cents <= 0:
        raise PoolSettlementError(
            REASON_NOT_FUNDED,
            f"pool instance {pool_instance_id} carries {pot_cents} cents; "
            f"collection never ran for week {instance.week}.")

    final_week = is_final_week(league, instance.week)

    # ── LAYER 1 outcome: no SUBJECT qualified ────────────────────────────────
    if outcome.classification == CLASSIFICATION_ZERO_ELIGIBLE_CLAIMS:
        return _resolve_zero_claim(
            db, instance=instance, spec=spec, outcome=outcome,
            pot_cents=pot_cents, final_week=final_week, now=now,
            rollover_event=EVENT_SUBJECT_ZERO_CLAIM_ROLLOVER,
            sweep_event=EVENT_SUBJECT_ZERO_CLAIM_CHAMPIONSHIP_SWEEP)

    assert outcome.classification == CLASSIFICATION_CLAIMS_PRESENT

    # ── LAYER 2: Owner Ruling R2 — resolve GM claims against the winner ──────
    winning_subjects = set(outcome.winning_subject_ids)
    from betting.pool_claims import claims_for_instance

    winning_gm_ids = sorted(
        claim.team_id for claim in claims_for_instance(
            db, pool_instance_id=instance.id)
        if claim.selected_subject_id in winning_subjects
    )

    if not winning_gm_ids:
        # ZERO WINNING TICKETS. A winner exists; nobody picked it. Never divide
        # by zero, never report the instance as distributed to winners.
        return _resolve_zero_claim(
            db, instance=instance, spec=spec, outcome=outcome,
            pot_cents=pot_cents, final_week=final_week, now=now,
            rollover_event=EVENT_TICKET_ZERO_WINNER_ROLLOVER,
            sweep_event=EVENT_TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP)

    # ── Normal §6.3 distribution ─────────────────────────────────────────────
    for gm_id in winning_gm_ids:
        if db.query(Wallet).filter(Wallet.team_id == gm_id).first() is None:
            raise PoolSettlementError(
                REASON_NO_WALLET,
                f"winning GM {gm_id} has no wallet; refusing to settle rather "
                f"than paying a subset of the winners.")
    lock_funding_scopes(db, *winning_gm_ids)

    allocation = allocate_even_split(pot_cents, winning_gm_ids)

    # Conservation asserted on the allocation itself, before it is posted. The
    # ledger would reject an unbalanced posting anyway; this states WHICH
    # invariant failed instead of surfacing a generic imbalance.
    if sum(allocation.values()) != pot_cents:
        raise PoolSettlementError(
            REASON_CONSERVATION,
            f"§6.3 allocation sums to {sum(allocation.values())} for a pot of "
            f"{pot_cents}; every cent must be distributed.")

    legs = [(f"pool:{instance.league_id}", -pot_cents)]
    legs.extend((f"wallet:{gm_id}", cents)
                for gm_id, cents in sorted(allocation.items()))
    posting = ledger_post(legs, door=DOOR_WINNER_DISTRIBUTION, session=db)
    _record_event(db, instance=instance,
                  event_type=EVENT_WINNER_DISTRIBUTION, posting_id=posting,
                  amount_cents=pot_cents, now=now)

    # SAME TRANSACTION as the posting above (§6.4 requirement 1).
    instance.settled = True
    instance.settled_at = now
    instance.settlement_classification = outcome.classification
    instance.distributed_cents = pot_cents
    instance.rollover_cents = 0
    db.flush()

    return SettlementResult(
        pool_instance_id=instance.id, definition_key=spec.key,
        classification=outcome.classification, census=outcome.census.as_dict(),
        winning_subject_ids=outcome.winning_subject_ids,
        winning_team_ids=tuple(winning_gm_ids),
        pot_cents=pot_cents, distributed_cents=pot_cents,
        rolled_over_cents=0, swept_to_championship_cents=0,
        event_type=EVENT_WINNER_DISTRIBUTION, replayed=False,
    )


def _resolve_zero_claim(db, *, instance, spec, outcome: PoolOutcome,
                        pot_cents: int, final_week: bool, now: datetime,
                        rollover_event: str, sweep_event: str,
                        ) -> SettlementResult:
    """The shared rollover-or-sweep tail for BOTH zero paths.

    Shared because the ARITHMETIC is identical — the complete distributable pot
    moves, never a share of it. The CAUSE is not identical, which is why the
    event type is a parameter: a subject-level rollover and a bettor-level
    zero-winning-ticket rollover are separate causes with separate audit
    meaning, and §12's requirement that distinct causes stay distinct is
    satisfied by the event row, not by the branch that led here.

    ROLLOVER IS NOT A POSTING. The money never leaves `pool:{league_id}` — a
    continuation carries the pot forward inside the same account. The event row
    is still written, with a NULL posting_id, because a replayed rollover
    determination must not be able to mint a second continuation (§H 10g).
    """
    rollover_eligible = bool(spec.rollover_eligible)

    if rollover_eligible and not final_week:
        # Carry forward. `rollover_cents` is the LIVE carry that
        # pending_continuations() reads next week; `pot_cents` stays as the
        # historical record of what this occurrence held.
        instance.rollover_cents = pot_cents
        instance.distributed_cents = 0
        instance.settled = True
        instance.settled_at = now
        instance.settlement_classification = outcome.classification
        _record_event(db, instance=instance, event_type=rollover_event,
                      posting_id=None, amount_cents=pot_cents, now=now)
        db.flush()
        return SettlementResult(
            pool_instance_id=instance.id, definition_key=spec.key,
            classification=outcome.classification,
            census=outcome.census.as_dict(),
            winning_subject_ids=outcome.winning_subject_ids,
            winning_team_ids=(), pot_cents=pot_cents, distributed_cents=0,
            rolled_over_cents=pot_cents, swept_to_championship_cents=0,
            event_type=rollover_event, replayed=False,
        )

    # Sweep. Two distinct terminal causes share one posting shape:
    #   - not rollover-eligible          -> the definition can never carry
    #   - rollover-eligible, final week  -> POR §5 expiry at season_final_week,
    #                                       NEVER a hardcoded week 14
    event_type = EVENT_ROLLOVER_EXPIRY_SWEEP if (rollover_eligible and final_week) \
        else sweep_event
    door = DOOR_ROLLOVER_EXPIRY if event_type == EVENT_ROLLOVER_EXPIRY_SWEEP \
        else DOOR_CHAMPIONSHIP_SWEEP

    # WP-5 — one resolution for every terminal Pool destination. Under the
    # Final POR this money is a FantasyStakes Championship Pot addition (§13);
    # under the legacy era it is `championship:{league}`, exactly as before.
    posting = ledger_post(
        [(f"pool:{instance.league_id}", -pot_cents),
         (terminal_pool_destination(db, league_id=instance.league_id,
                                    season=instance.season), pot_cents)],
        door=door, session=db,
    )
    _record_event(db, instance=instance, event_type=event_type,
                  posting_id=posting, amount_cents=pot_cents, now=now)

    instance.settled = True
    instance.settled_at = now
    instance.settlement_classification = outcome.classification
    instance.distributed_cents = 0
    instance.rollover_cents = 0
    db.flush()

    return SettlementResult(
        pool_instance_id=instance.id, definition_key=spec.key,
        classification=outcome.classification, census=outcome.census.as_dict(),
        winning_subject_ids=outcome.winning_subject_ids, winning_team_ids=(),
        pot_cents=pot_cents, distributed_cents=0, rolled_over_cents=0,
        swept_to_championship_cents=pot_cents, event_type=event_type,
        replayed=False,
    )


@dataclass(frozen=True)
class WeekSettlementResult:
    """One week's settlement outcome, settled and refused reported separately.

    A bare list of successes would hide the refusals, and POR §6.2 requires a
    refusal be surfaced with its classification and census rather than being
    absent from the result."""

    league_id: int
    week: int
    settled: tuple[SettlementResult, ...]
    refused: tuple[PoolSettlementRefusedError, ...]
    week_container_settled: bool

    @property
    def all_settled(self) -> bool:
        return not self.refused


def settle_week(db, *, league_id: int, week: int, stat_source,
                ) -> WeekSettlementResult:
    """Settle every occurrence of one week, then mark the week container.

    PER-INSTANCE ISOLATION BY SAVEPOINT (S4-P2-2). Each instance settles inside
    its own `SAVEPOINT`. A governed fail-closed refusal rolls back ONLY that
    savepoint, so a sibling that already posted keeps its posting and its
    `settled` flag, and the refused instance leaves nothing behind.

    WITHOUT THE SAVEPOINT THIS IS A REAL DEFECT, not a theoretical one. The
    refusal is an exception; it propagates out of the loop; the caller's
    `db.rollback()` — or an outer `with` block — discards the ENTIRE
    transaction, including three siblings that settled correctly. Their ledger
    postings vanish and their `settled` flags revert, so one team's missing
    kicker stat would un-settle three unrelated Pools. POR §6.2 makes
    fail-closed states a property of ONE instance's subject field; nothing in it
    licenses holding three settleable Pools hostage to a fourth's data gap.

    ONLY GOVERNED FAIL-CLOSED CLASSIFICATIONS ARE ISOLATED. The except clause
    names `PoolSettlementRefusedError`, whose entire subtree is the four §6.2
    classifications and nothing else. An IntegrityError, a programming error, a
    lost connection or any other exception propagates untouched and aborts the
    whole week — a blanket `except Exception` here would swallow the very
    conditions the event-key constraint exists to raise, and would turn a
    duplicate-payout attempt into a silent skip.

    THE WEEK CONTAINER IS MARKED ONLY WHEN EVERY INSTANCE IS SETTLED, and the
    check reads the persisted `settled` column rather than the length of the
    results list — so a LATER retry of a previously refused instance completes
    the week correctly (S4-P2-3), whether or not this call settled anything.
    """
    from db.schema import PoolInstance, PoolPot

    instances = (db.query(PoolInstance)
                 .filter(PoolInstance.league_id == league_id,
                         PoolInstance.week == week)
                 .order_by(PoolInstance.slot)
                 .all())

    settled: list[SettlementResult] = []
    refused: list[PoolSettlementRefusedError] = []

    for instance in instances:
        savepoint = db.begin_nested()
        try:
            result = settle_pool_instance(db, pool_instance_id=instance.id,
                                          stat_source=stat_source)
            savepoint.commit()
            settled.append(result)
        except PoolSettlementRefusedError as refusal:
            # Releases every write this instance made — there are none by
            # construction, because require_settleable() raises before any
            # posting — and leaves the siblings' work intact.
            savepoint.rollback()
            refused.append(refusal)

    # Re-read from the database rather than trusting the loop: an instance
    # settled by an EARLIER call is already true here, which is what lets a
    # retry close the week.
    db.flush()
    remaining = (db.query(PoolInstance)
                 .filter(PoolInstance.league_id == league_id,
                         PoolInstance.week == week,
                         PoolInstance.settled.is_(False))
                 .count())

    container_settled = False
    if instances and remaining == 0:
        pot = (db.query(PoolPot)
               .filter(PoolPot.league_id == league_id, PoolPot.week == week)
               .first())
        if pot is not None:
            pot.settled = True
            pot.settled_at = datetime.now(timezone.utc)
            container_settled = True
    db.flush()

    return WeekSettlementResult(
        league_id=league_id, week=week, settled=tuple(settled),
        refused=tuple(refused), week_container_settled=container_settled,
    )


# ── Terminal rollover expiry at the season boundary ───────────────────────────
#
# WP6F OWNER RULING — FINAL-WEEK ROLLOVER EXPIRY IS A SEASON-BOUNDARY SETTLEMENT
# RULE, NOT AN OCCURRENCE-HOSTED ONE.
#
#     BAB-805  If no later eligible occurrence exists, remaining rollover
#              transfers to the Championship Pot.
#     BAB-901  Season Close resolves all Pool rollovers and season-end sweeps
#              before Championship distribution.
#     AP-166   Any unresolved rollover after the final eligible occurrence of the
#              season transfers to the Championship Pot.
#
# WHY THIS FUNCTION HAD TO EXIST, stated plainly because the gap it closes was a
# real one. `_resolve_zero_claim` above already implements POR §5's final-week
# sweep, but it can only be reached by SETTLING AN OCCURRENCE at a week >=
# season_final_week. Creating that occurrence means drawing a slate, and under
# POR §9's own default boundaries the final week (17) is >= playoff_start_week
# (15), so the draw is governed by POR §8 — whose approved 32-Pool postseason
# subset does not exist, leaving every `postseason_eligible` NULL and the
# postseason candidate set empty. A league with fewer live carries than slots
# therefore could never build the occurrence, never settle it, and never sweep:
# the carry was undischargeable and `pool_rollover` refused the close forever.
#
# THE RULING SEPARATES DISPOSAL FROM EVALUATION, AND THAT IS WHY NO OCCURRENCE IS
# NEEDED. A carry's CLASSIFICATION was already determined, at its own week, by
# the full census/claim machinery — the money is carried precisely BECAUSE that
# determination completed. Expiry asks a different and much smaller question:
# is there any later occurrence left to host it? At the season boundary there is
# not, and the answer needs no subjects, no stat source, no finality gate and no
# catalog eligibility. Fabricating a PoolInstance to host the disposal would
# invent an occurrence that never drew, never funded and never had a claim
# phase — a fiction in the audit record, and one the postseason blocker makes
# undrawable anyway.
#
# NOTHING BELOW REIMPLEMENTS A SETTLEMENT RULE. The event type, the ledger door,
# the two-leg posting shape, the `rollover_cents -> 0` transition and the
# `pot_cents` historical record are all the SAME ones `_resolve_zero_claim` uses
# for its final-week branch. That is deliberate: one disposal semantic with two
# entry points beats two semantics that must be kept in step by hand.

REASON_ROLLOVER_NOT_SETTLED = "ROLLOVER_INSTANCE_NOT_SETTLED"
REASON_ROLLOVER_HAS_SUCCESSOR = "ROLLOVER_HAS_LATER_OCCURRENCE"
REASON_ROLLOVER_UNDERFUNDED = "ROLLOVER_ACCOUNT_UNDERFUNDED"


@dataclass(frozen=True)
class TerminalRolloverSweep:
    """One carried pot disposed at the boundary. `pool_instance_id` IS the
    lineage: the event row hangs off the occurrence that carried the balance, so
    the audit trail runs unbroken from the week the pot was drawn, through the
    week it rolled, to the boundary that disposed of it."""

    pool_instance_id: int
    definition_key: str
    week: int
    slot: int
    classification: str
    amount_cents: int
    replayed: bool


@dataclass(frozen=True)
class TerminalRolloverResult:
    league_id: int
    season: int
    final_week: int
    season_final_week: int
    boundary_reached: bool
    swept: tuple[TerminalRolloverSweep, ...]

    @property
    def total_cents(self) -> int:
        """Cents this call moved. A replayed sweep contributes ZERO — the money
        moved once, on the call that posted it."""
        return sum(s.amount_cents for s in self.swept if not s.replayed)

    @property
    def disposed_cents(self) -> int:
        """Cents disposed across all time, replays included. Distinct from
        `total_cents` on purpose: one answers "what did this call move", the
        other "what is no longer carried", and conflating them would make a
        retry look like a second sweep."""
        return sum(s.amount_cents for s in self.swept)


def _already_swept(db, instance_id: int):
    from db.schema import PoolEconomicEvent

    return (db.query(PoolEconomicEvent)
            .filter(PoolEconomicEvent.pool_instance_id == instance_id,
                    PoolEconomicEvent.event_type == EVENT_ROLLOVER_EXPIRY_SWEEP)
            .first())


def expire_terminal_rollovers(db, *, league_id: int, final_week: int,
                              now: datetime | None = None,
                              ) -> TerminalRolloverResult:
    """Dispose every unresolved rollover at the governed season boundary.

    Does NOT commit — the caller owns the transaction, so the postings, the
    event rows and the `rollover_cents -> 0` transitions land atomically with
    the close that authorized them.

    EXACT-ONCE IS A CONSTRAINT, NOT A CHECK. `uq_pool_economic_event_instance`
    is unique on (pool_instance_id, event_type), so a second
    ROLLOVER_EXPIRY_SWEEP for the same occurrence cannot be inserted by any
    caller, in any process, after any crash. The pre-read below turns that
    collision into a clean `replayed=True` for the ordinary retry; the
    constraint is what makes the guarantee true when the pre-read races.

    THE BOUNDARY GATE IS LOAD-BEARING. Below `season_final_week` this function
    writes NOTHING and reports `boundary_reached=False`, so a caller that closes
    a league early cannot use it to vacuum live carries into Championship — the
    ruling disposes of a rollover that has no later eligible occurrence, and
    before the final week a later occurrence is exactly what still exists.
    """
    from db.schema import League, PoolInstance
    from betting.pool_season_boundary import season_final_week

    now = now or datetime.now(timezone.utc)

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise PoolSettlementError(REASON_INSTANCE_NOT_FOUND,
                                  f"league {league_id} not found")
    season = league.season
    boundary = season_final_week(league)
    boundary_reached = int(final_week) >= int(boundary)

    if not boundary_reached:
        return TerminalRolloverResult(
            league_id=league_id, season=season, final_week=int(final_week),
            season_final_week=boundary, boundary_reached=False, swept=())

    # Row locks FIRST, in a deterministic order, exactly as settlement does.
    carriers = (db.query(PoolInstance)
                .filter(PoolInstance.league_id == league_id,
                        PoolInstance.rollover_cents > 0)
                .order_by(PoolInstance.week, PoolInstance.slot)
                .with_for_update()
                .all())

    if not carriers:
        return TerminalRolloverResult(
            league_id=league_id, season=season, final_week=int(final_week),
            season_final_week=boundary, boundary_reached=True, swept=())

    # "No later eligible occurrence exists" — proved, not assumed. An unsettled
    # occurrence anywhere in the league IS a later eligible occurrence in the
    # only sense that matters: it can still resolve, and resolving it could
    # consume or add to a carry. Re-checked here rather than trusted from the
    # orchestrator so a direct call is no less safe than the close's, which is
    # the same rule `settle_pool_instance` follows for the finality gate.
    unsettled = (db.query(PoolInstance)
                 .filter(PoolInstance.league_id == league_id,
                         PoolInstance.settled.is_(False))
                 .count())
    if unsettled:
        raise PoolSettlementError(
            REASON_ROLLOVER_NOT_SETTLED,
            f"league {league_id} has {unsettled} unsettled Pool occurrence(s); "
            f"a rollover cannot be terminal while a later eligible occurrence "
            f"can still resolve. Settle the week first.")

    swept: list[TerminalRolloverSweep] = []
    for instance in carriers:
        amount = int(instance.rollover_cents or 0)

        if not instance.settled:
            raise PoolSettlementError(
                REASON_ROLLOVER_NOT_SETTLED,
                f"pool instance {instance.id} carries {amount} cents but is "
                f"not settled; its rollover was never determined.")

        # A carry already consumed into a continuation must have been zeroed by
        # `build_and_persist_slate`. Finding both a successor AND a live carry
        # means one pot is claimed twice (Scope §H 10g), so it is refused rather
        # than swept — sweeping would move money that a continuation also holds.
        successor = (db.query(PoolInstance)
                     .filter(PoolInstance.origin_instance_id == instance.id)
                     .first())
        if successor is not None:
            raise PoolSettlementError(
                REASON_ROLLOVER_HAS_SUCCESSOR,
                f"pool instance {instance.id} carries {amount} cents but "
                f"instance {successor.id} (week {successor.week}) already "
                f"continues it; the carry has a later occurrence and must not "
                f"also be swept.")

        existing = _already_swept(db, instance.id)
        if existing is not None:
            # Belt and braces: the money moved on the earlier call, and the
            # carry should already be zero. Report it as replayed and move on.
            instance.rollover_cents = 0
            swept.append(TerminalRolloverSweep(
                pool_instance_id=instance.id,
                definition_key=instance.definition_key, week=instance.week,
                slot=instance.slot,
                classification=instance.settlement_classification or "",
                amount_cents=int(existing.amount_cents or 0), replayed=True))
            continue

        # NO NEGATIVE BALANCE. The pool account must actually hold what the
        # instance state says it carries; POR §13 forbids inferring conservation
        # from a status column, so this is read off real ledger entries.
        #
        # READ IN THIS TRANSACTION, because the loop posts as it goes. The
        # committed balance still shows every earlier carry in this same sweep
        # as present, so a cross-session read would clear the LAST instance
        # against money the FIRST one already took — the guard would pass at
        # exactly the moment it needed to refuse.
        available = _balance_of_in_session(db, f"pool:{league_id}")
        if available < amount:
            raise PoolSettlementError(
                REASON_ROLLOVER_UNDERFUNDED,
                f"pool:{league_id} holds {available} cents but instance "
                f"{instance.id} carries {amount}. Refusing to post a sweep that "
                f"would drive the Pool account negative.")

        posting = ledger_post(
            [(f"pool:{league_id}", -amount),
             (terminal_pool_destination(db, league_id=league_id,
                                        season=instance.season), amount)],
            door=DOOR_ROLLOVER_EXPIRY, session=db,
        )
        _record_event(db, instance=instance,
                      event_type=EVENT_ROLLOVER_EXPIRY_SWEEP,
                      posting_id=posting, amount_cents=amount, now=now)

        # `pot_cents` is deliberately NOT touched. It is the historical record of
        # what the occurrence held; `rollover_cents` is the live carry, and only
        # the live carry is discharged.
        instance.rollover_cents = 0

        swept.append(TerminalRolloverSweep(
            pool_instance_id=instance.id,
            definition_key=instance.definition_key, week=instance.week,
            slot=instance.slot,
            classification=instance.settlement_classification or "",
            amount_cents=amount, replayed=False))

    db.flush()
    # The same invariant settlement is held to, asserted at the transaction that
    # changed it rather than discovered later. `in_session=True` because the
    # close owns this transaction and has not committed: both sides must be read
    # from `db` or the ledger side lags the instance side by the swept amount.
    assert_pool_conservation(db, league_id=league_id, season=season,
                             in_session=True)

    return TerminalRolloverResult(
        league_id=league_id, season=season, final_week=int(final_week),
        season_final_week=boundary, boundary_reached=True,
        swept=tuple(swept))