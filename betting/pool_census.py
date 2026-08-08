"""
Subject census and classification gate — POR Rev1.3 §6.2, Scope §C6/§C9.

A BARE EMPTY RESULT SET NEVER DETERMINES AN OUTCOME. Classification is computed
from a CENSUS of the subject set, and behavior follows the classification. This
module is the gate every settlement path runs through before any economic work,
and it is deliberately the only place the six classifications are produced.

THE ORDERING IS THE RULE, NOT AN IMPLEMENTATION CHOICE:

    considered == 0                              -> NO_SUBJECTS
    evaluated  == 0                              -> NO_EVALUABLE_SUBJECTS
    evaluated  <  considered                     -> INCOMPLETE_FIELD
    evaluated  == considered, claims 0, RANK     -> INVARIANT_VIOLATION
    evaluated  == considered, claims 0           -> ZERO_ELIGIBLE_CLAIMS
    evaluated  == considered, claims >= 1        -> CLAIMS_PRESENT

`subjects_claiming` is NOT COMPUTED, NOT STORED AND NOT LOGGED unless
`evaluated == considered` (§6.2, binding). That is why SubjectCensus carries
None rather than 0 in the incomplete cases: a 0 there would be a claim count
over an incomplete field, which the POR forbids from existing at all.

ROW 6 TAKES PRECEDENCE OVER ROW 4. A complete, non-empty RANK_EXTREMUM field
always has an extremum, so zero claimants means the EVALUATOR is wrong, not that
the week produced a legitimate no-winner result. Checking ZERO_ELIGIBLE_CLAIMS
first would route an evaluator bug into the rollover lifecycle and quietly carry
a pot forward on the strength of a defect.

"CLAIMS" HERE ARE SUBJECTS, NOT TICKETS. This layer knows nothing about GMs.
`subjects_claiming` counts SUBJECTS that claim the win — those at the extremum,
or those satisfying the predicate. Whether any GM picked one of them is a
separate, later question answered in betting/pool_settlement.py under Owner
Ruling R2. Conflating the two layers is the specific defect R2 exists to
prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from betting.pool_catalog import PoolDefinitionSpec, StatVocabulary, load_vocabulary
from betting.pool_errors import REFUSAL_ERRORS, SubjectCensus
from betting.pool_shapes import UNEVALUABLE, subject_qualifies, subject_value
from betting.pool_subjects import Subject, WeeklyStructure

CLASSIFICATION_NO_SUBJECTS = "NO_SUBJECTS"
CLASSIFICATION_NO_EVALUABLE_SUBJECTS = "NO_EVALUABLE_SUBJECTS"
CLASSIFICATION_INCOMPLETE_FIELD = "INCOMPLETE_FIELD"
CLASSIFICATION_ZERO_ELIGIBLE_CLAIMS = "ZERO_ELIGIBLE_CLAIMS"
CLASSIFICATION_CLAIMS_PRESENT = "CLAIMS_PRESENT"
CLASSIFICATION_INVARIANT_VIOLATION = "INVARIANT_VIOLATION"

#: The four that refuse the settlement transaction outright (§C6).
FAIL_CLOSED_CLASSIFICATIONS = frozenset({
    CLASSIFICATION_NO_SUBJECTS,
    CLASSIFICATION_NO_EVALUABLE_SUBJECTS,
    CLASSIFICATION_INCOMPLETE_FIELD,
    CLASSIFICATION_INVARIANT_VIOLATION,
})


@dataclass(frozen=True)
class PoolOutcome:
    """The complete result of evaluating one pool occurrence's subject field.

    Carries the census ALONGSIDE the winners — §C6: "Each evaluator returns a
    census alongside its result: a bare list is not an acceptable return shape."
    """

    classification: str
    census: SubjectCensus
    winning_subject_ids: tuple[int, ...]
    values: Mapping[int, float]
    unevaluable_subject_ids: tuple[int, ...]

    @property
    def is_fail_closed(self) -> bool:
        return self.classification in FAIL_CLOSED_CLASSIFICATIONS

    @property
    def settles(self) -> bool:
        """POR §6.2 behaviour table — only these two classifications settle."""
        return self.classification in (CLASSIFICATION_ZERO_ELIGIBLE_CLAIMS,
                                       CLASSIFICATION_CLAIMS_PRESENT)


def classify_pool(spec: PoolDefinitionSpec,
                  structure: WeeklyStructure,
                  subjects: Sequence[Subject],
                  *,
                  vocab: StatVocabulary | None = None,
                  threshold_override: int | None = None) -> PoolOutcome:
    """Evaluate the full subject field and classify it.

    `structure.considered_subject_ids` is the census source and comes from the
    authoritative weekly league structure. `subjects` carries the FACTS. The two
    are separate parameters on purpose: a subject named by the structure but
    absent from `subjects` is UNEVALUABLE, not uncounted. That is the entire
    discriminating property of Scope §H scenario 28 — an implementation that
    derived `considered` from `subjects` would pass scenarios 23 through 27 and
    fail only there, because its census would shrink to match its own gaps.
    """
    vocab = vocab or load_vocabulary()

    considered_ids = tuple(structure.considered_subject_ids)
    considered = len(considered_ids)
    if considered == 0:
        return PoolOutcome(
            classification=CLASSIFICATION_NO_SUBJECTS,
            census=SubjectCensus(subjects_considered=0, subjects_evaluated=0),
            winning_subject_ids=(), values={}, unevaluable_subject_ids=(),
        )

    by_id = {s.subject_id: s for s in subjects}
    is_qualifier = spec.evaluator_family == "QUALIFIER"

    values: dict[int, float] = {}
    qualifiers: list[int] = []
    unevaluable: list[int] = []

    for subject_id in considered_ids:
        subject = by_id.get(subject_id)
        if subject is None:
            unevaluable.append(subject_id)
            continue
        if is_qualifier:
            result = subject_qualifies(spec, subject, vocab, threshold_override)
            if result is UNEVALUABLE:
                unevaluable.append(subject_id)
                continue
            # Recorded as 1.0/0.0 so `values` is a uniform audit surface across
            # both families; the winner set is driven by `qualifiers`, never by
            # ranking these.
            values[subject_id] = 1.0 if result else 0.0
            if result:
                qualifiers.append(subject_id)
        else:
            result = subject_value(spec, subject, vocab)
            if result is UNEVALUABLE:
                unevaluable.append(subject_id)
                continue
            values[subject_id] = float(result)

    evaluated = len(values)

    if evaluated == 0:
        return PoolOutcome(
            classification=CLASSIFICATION_NO_EVALUABLE_SUBJECTS,
            census=SubjectCensus(subjects_considered=considered,
                                 subjects_evaluated=0),
            winning_subject_ids=(), values={},
            unevaluable_subject_ids=tuple(unevaluable),
        )

    if evaluated < considered:
        # No claim count. Not computed, not stored, not logged (§6.2).
        return PoolOutcome(
            classification=CLASSIFICATION_INCOMPLETE_FIELD,
            census=SubjectCensus(subjects_considered=considered,
                                 subjects_evaluated=evaluated),
            winning_subject_ids=(), values=dict(values),
            unevaluable_subject_ids=tuple(unevaluable),
        )

    # ── Full field. Only now may claims be computed. ─────────────────────────
    if is_qualifier:
        winners = tuple(sorted(qualifiers))
    else:
        direction = spec.direction
        if direction not in ("MAX", "MIN"):
            # A RANK_EXTREMUM row with no direction cannot rank. This is an
            # evaluator/metadata fault, so it lands as INVARIANT_VIOLATION
            # rather than as a data condition an operator would wait out.
            return PoolOutcome(
                classification=CLASSIFICATION_INVARIANT_VIOLATION,
                census=SubjectCensus(subjects_considered=considered,
                                     subjects_evaluated=evaluated,
                                     subjects_claiming=0),
                winning_subject_ids=(), values=dict(values),
                unevaluable_subject_ids=tuple(unevaluable),
            )
        extremum = max(values.values()) if direction == "MAX" \
            else min(values.values())
        # ALL subjects tied at the extreme (POR §3 family table). A tie is a
        # settled outcome that splits per §6.3 — it never rolls.
        winners = tuple(sorted(sid for sid, v in values.items() if v == extremum))

    claiming = len(winners)
    census = SubjectCensus(subjects_considered=considered,
                           subjects_evaluated=evaluated,
                           subjects_claiming=claiming)

    if claiming == 0 and not is_qualifier:
        # Row 6, precedence over row 4.
        return PoolOutcome(
            classification=CLASSIFICATION_INVARIANT_VIOLATION,
            census=census, winning_subject_ids=(), values=dict(values),
            unevaluable_subject_ids=tuple(unevaluable),
        )
    if claiming == 0:
        return PoolOutcome(
            classification=CLASSIFICATION_ZERO_ELIGIBLE_CLAIMS,
            census=census, winning_subject_ids=(), values=dict(values),
            unevaluable_subject_ids=tuple(unevaluable),
        )
    return PoolOutcome(
        classification=CLASSIFICATION_CLAIMS_PRESENT,
        census=census, winning_subject_ids=winners, values=dict(values),
        unevaluable_subject_ids=tuple(unevaluable),
    )


def require_settleable(outcome: PoolOutcome, *, definition_key: str,
                       league_id: int, season: int, week: int) -> PoolOutcome:
    """Raise the named domain error for any fail-closed classification.

    Called BEFORE any economic work, never after. §C6: "Classification runs
    before any claim computation and before any economic work." A caller that
    posts first and classifies second has already violated the rule no matter
    what this function then raises.

    The error type is looked up from the classification rather than selected by
    a chain of ifs, so the mapping cannot drift from the table in
    betting/pool_errors.py."""
    if not outcome.is_fail_closed:
        return outcome
    error_cls = REFUSAL_ERRORS[outcome.classification]
    raise error_cls(
        definition_key=definition_key,
        league_id=league_id,
        season=season,
        week=week,
        census=outcome.census,
        # §6.2: INCOMPLETE_FIELD "additionally carries the identity of the
        # unevaluable subjects". Supplying them on every refusal is harmless and
        # strictly more useful; the requirement is a floor, not a ceiling.
        unevaluable_subject_ids=outcome.unevaluable_subject_ids,
    )