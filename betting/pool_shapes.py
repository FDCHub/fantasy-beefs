"""
The eight governed evaluator shapes — POR Rev1.3 §3.4, Scope §C8.

ONE COMMON ENGINE, EIGHT SHAPES, ZERO DEFINITION-SPECIFIC BRANCHES. Nothing in
this module reads a definition key or a display name. Every behavioural
difference is driven by declarative metadata: `evaluator_shape` selects the
computation, `scope` selects the subject frame, `slot_filter`/`slot_exclusions`
select the starters, `direction` selects the extreme, `predicate` and
`predicate_quantifier` carry the qualifier logic. That is AP-323 made
executable: "a catalog entry SHALL not create an exception to the common
outcome, self-pick, tie, rollover, settlement, or Ledger protocols."

FAMILY AND SHAPE ARE DIFFERENT AXES (POR §3.1, and the error §3.1 exists to
prevent). `evaluator_family` — RANK_EXTREMUM or QUALIFIER — classifies
SETTLEMENT BEHAVIOR: it decides rollover eligibility and how a zero-claim
outcome is interpreted. `evaluator_shape` defines COMPUTATION. Two definitions
can share a family and compute nothing alike.

UNEVALUABLE IS A VALUE, NOT AN EXCEPTION. Every per-subject computation returns
either a number (or, for qualifiers, a bool) or the `UNEVALUABLE` sentinel. It
does not raise, because a single unevaluable subject is NOT a failure of the
week — it is one input to the census, and POR §6.2 decides what the census
means. Raising here would collapse "one team's kicker never reported" into the
same surface as "the evaluator is broken", and §6.2 requires those be
distinguishable. The only things that DO raise are contract violations: a
blocked definition reaching execution, an ungoverned shape, a malformed
expression.

ZERO DENOMINATOR MAKES ONE SUBJECT UNEVALUABLE — IT DOES NOT ABORT THE WEEK.
POR §6.2: "For a ratio, a present denominator of zero produces an undefined
metric and the subject is unevaluable under the zero-denominator rule (§3.3)."
The end state is still fail-closed, because an unevaluable subject drops
`subjects_evaluated` below `subjects_considered` and §6.2 classifies the week
INCOMPLETE_FIELD. The difference is that the refusal now carries a census and
names the subject, instead of surfacing as an opaque divide-by-zero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from betting.pool_catalog import PoolDefinitionSpec, StatVocabulary, load_vocabulary
from betting.pool_evaluators import (
    Aggregate,
    MetricSpec,
    PoolEvaluatorError,
    REASON_MISSING_DIRECTION,
    REASON_UNSUPPORTED_EXPRESSION,
    parse_metric_expression,
    validate_against_spec,
)
from betting.pool_subjects import (
    SCOPE_MATCHUP,
    SCOPE_TEAM,
    StatComponent,
    Subject,
    filtered_components,
)

REASON_BLOCKED_DEFINITION = "BLOCKED_DEFINITION"
REASON_UNGOVERNED_SHAPE = "UNGOVERNED_SHAPE"
REASON_MALFORMED_PREDICATE = "MALFORMED_PREDICATE"


class _Unevaluable:
    """Sentinel. Singleton so callers compare with `is`, never by value — a
    float comparison against a sentinel is exactly the confusion this avoids."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:      # pragma: no cover - debug aid
        return "UNEVALUABLE"

    def __bool__(self) -> bool:
        # Deliberately falsy-proof: an unevaluable subject must never be
        # mistaken for a qualifier that returned False.
        raise TypeError(
            "UNEVALUABLE has no truth value; test it with `is UNEVALUABLE` "
            "before using a qualifier result."
        )


UNEVALUABLE = _Unevaluable()


# ── Closed grammar aggregation, alias-aware ───────────────────────────────────

def _aggregate(agg: Aggregate, components: Sequence[StatComponent],
               vocab: StatVocabulary) -> float:
    """Σ over components of Σ over operands — POR §3.2's aggregate-over-aggregate.

    THE ALIAS RESOLUTION HERE IS THE WHOLE REASON THIS IS NOT
    pool_evaluators._aggregate_value. Catalog expressions are written in the
    source artifact's spelling: #31 reads `sum(yards) / sum(touches)` while the
    boundary supplies canonical `scrimmage_yards` and `touches`. Looking up the
    raw operand would find nothing, contribute 0.0 for every subject, and hand
    back a perfectly plausible all-zero ranking. POR §1.4 makes the canonical
    name the identity; this is where that ruling is applied.

    A component missing a canonical operand contributes 0.0, which is correct
    and is NOT the missing-data path — subject-level coverage decided that
    already, before this function was reached (§C7.3)."""
    total = 0.0
    for component in components:
        values = component.values
        for operand in agg.operands:
            total += float(values.get(vocab.canonical_operand(operand), 0.0))
    return total


def _closed_value(spec: PoolDefinitionSpec, subject: Subject,
                  vocab: StatVocabulary) -> float | _Unevaluable:
    parsed = parse_metric_expression(spec.metric_expression)
    validate_against_spec(parsed, MetricSpec(
        metric_expression=spec.metric_expression,
        metric_kind=spec.metric_kind,
        direction=spec.direction,
        scope=spec.scope,
        zero_denominator_guard=spec.zero_denominator_guard,
        aggregate_over_aggregate_required=spec.aggregate_over_aggregate_required,
        tie_rule=spec.tie_rule,
    ))

    components = filtered_components(subject, spec.slot_filter,
                                     spec.slot_exclusions)
    numerator = _aggregate(parsed.numerator, components, vocab)
    if parsed.denominator is None:
        return numerator

    denominator = _aggregate(parsed.denominator, components, vocab)
    if denominator == 0:
        # POR §3.3 — never divide, never coerce to zero, never award. The
        # subject is unevaluable; §6.2 turns that into INCOMPLETE_FIELD for the
        # week. zero_denominator_guard is metadata describing which rows can
        # reach this in a real week; it is NOT a switch, because dividing by
        # zero is not an available behavior on an unflagged row either.
        return UNEVALUABLE
    # ONE division, over two independent sums. Never a mean of per-component
    # ratios — POR §3.2, binding: the two produce different winners on the same
    # data, and it is a wrong-winner defect that does not announce itself.
    return numerator / denominator


# ── Non-closed shapes ─────────────────────────────────────────────────────────

def _player_extremum(spec: PoolDefinitionSpec, subject: Subject,
                     vocab: StatVocabulary) -> float | _Unevaluable:
    """#17 — the subject stays the TEAM; the metric is the maximum INDIVIDUAL
    value among active starters in the declared slots (§C8).

    NOT A SUM. A team whose two starting quarterbacks each gained 150 dual-threat
    yards scores 150, not 300.

    "A subject with no qualifying starter is unevaluable, never zero" (§C8) —
    a team that started nobody in a QB-eligible slot has no individual maximum,
    and zero would rank it as a genuine last place."""
    components = filtered_components(subject, spec.slot_filter,
                                     spec.slot_exclusions)
    if not components:
        return UNEVALUABLE
    best: float | None = None
    for component in components:
        total = sum(
            float(component.values.get(vocab.canonical_operand(stat), 0.0))
            for stat in spec.required_stats
        )
        if best is None or total > best:
            best = total
    return best if best is not None else UNEVALUABLE


def _slot_filtered_points_sum(spec: PoolDefinitionSpec, subject: Subject,
                              vocab: StatVocabulary) -> float | _Unevaluable:
    """#42 — sum actual fantasy points over the declared starter slots (§C8).

    Source basis is SCORED FANTASY POINTS under the league's governing scoring
    settings, not raw statistics."""
    components = filtered_components(subject, spec.slot_filter,
                                     spec.slot_exclusions)
    if not components:
        return UNEVALUABLE
    return sum(float(c.values.get("player_fantasy_points", 0.0))
               for c in components)


# Effective positions that make up each side of #43's balance. Read from the
# governed_definition prose, pinned here as data so the computation carries no
# per-definition branch: "run = active starting RBs; pass game = active starting
# WRs and TEs".
_BALANCE_RUN_POSITIONS = frozenset({"RB"})
_BALANCE_PASS_POSITIONS = frozenset({"WR", "TE"})


def _balance_ratio(spec: PoolDefinitionSpec, subject: Subject,
                   vocab: StatVocabulary) -> float | _Unevaluable:
    """#43 — POR §3.4 rules this one in full, including both edge cases.

        run_points  = max(0, fantasy points of active starting RBs)
        pass_points = max(0, fantasy points of active starting WRs and TEs)
        both zero   -> balance_score 0      (DEFINED, not unevaluable)
        otherwise   -> min(run, pass) / max(run, pass)

    THE CLAMP REMOVES THE DIVIDE-BY-ZERO PATH, which is why §C8 states that no
    zero-denominator guard applies here. After clamping, max(run, pass) is zero
    only when both are zero, and that case is answered by ruling with a defined
    score of 0 rather than by division.

    Negative fantasy points are real (a fumble-heavy RB day), which is why the
    clamp exists at all: an unclamped negative would invert the ratio's sense."""
    components = filtered_components(subject, spec.slot_filter,
                                     spec.slot_exclusions)
    if not components:
        return UNEVALUABLE

    raw_run = raw_pass = 0.0
    for component in components:
        points = float(component.values.get("player_fantasy_points", 0.0))
        position = (component.effective_position or "").upper()
        if position in _BALANCE_RUN_POSITIONS:
            raw_run += points
        elif position in _BALANCE_PASS_POSITIONS:
            raw_pass += points

    run = max(0.0, raw_run)
    passing = max(0.0, raw_pass)
    if run == 0.0 and passing == 0.0:
        return 0.0
    return min(run, passing) / max(run, passing)


def _matchup_score_sum(spec: PoolDefinitionSpec, subject: Subject,
                       vocab: StatVocabulary) -> float | _Unevaluable:
    """#76 — sum the two matchup scores from the LEAGUE MATCHUP RECORD (§C8).

    Team-level totals, not per-player stats, which is why this shape exists at
    all: it is not expressible under the ratified SUM/RATIO grammar and its
    `metric_expression` is correctly null.

    A missing score on either participant makes the matchup unevaluable — POR
    §6.2's "no partial matchup"."""
    if subject.subject_type != SCOPE_MATCHUP or len(subject.frames) != 2:
        raise PoolEvaluatorError(
            REASON_UNSUPPORTED_EXPRESSION,
            f"MATCHUP_SCORE_SUM requires a MATCHUP subject with two frames; "
            f"got {subject.subject_type!r} with {len(subject.frames)}.",
        )
    if any(f.score is None for f in subject.frames):
        return UNEVALUABLE
    return float(sum(f.score for f in subject.frames))


def _distinct_category_count(spec: PoolDefinitionSpec, subject: Subject,
                             vocab: StatVocabulary) -> float | _Unevaluable:
    """#46 — BLOCKED, and reaching it is a contract violation.

    POR §7.0: the source collapses touchdown categories, so the approved
    category list cannot be represented. The definition is product-APPROVED and
    source-blocked; `dependency_state = BLOCKED` keeps it out of every slate.

    This raises rather than returning UNEVALUABLE on purpose. UNEVALUABLE is a
    statement about one week's DATA. A blocked definition executing is a
    statement about the SELECTOR — something drew a definition it must never
    draw — and POR conformance 19 requires that never happen. Inventing a
    category count from the collapsed source would be exactly the §41 violation
    "no definition is redefined to fit an available source"."""
    raise PoolEvaluatorError(
        REASON_BLOCKED_DEFINITION,
        f"definition {spec.key!r} (#{spec.catalog_number}) is "
        f"dependency_state=BLOCKED and must never enter a slate "
        f"(POR conformance 19). Reaching its evaluator means the two-gate "
        f"selector was bypassed. blocked_reason: {spec.blocked_reason}",
    )


# ── Qualifier predicates ──────────────────────────────────────────────────────

_COMPARATORS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}
# Longest-first so ">=" is never mis-split as ">".
_COMPARATOR_RE = re.compile(r"(>=|<=|==|!=|>|<)")

_EACH_TEAM_RE = re.compile(r"\AEACH_TEAM\((?P<inner>.+)\)\Z")
_SUM_BOTH_RE = re.compile(r"\ASUM_BOTH_TEAMS\((?P<operands>[^()]+)\)\Z")

THRESHOLD_TOKEN = "threshold_value"


@dataclass(frozen=True)
class _Comparison:
    operands: tuple[str, ...]
    comparator: str
    rhs: float | None          # None means "read threshold_value"


def _parse_comparison(raw: str) -> _Comparison:
    parts = _COMPARATOR_RE.split(raw.strip(), maxsplit=1)
    if len(parts) != 3:
        raise PoolEvaluatorError(
            REASON_MALFORMED_PREDICATE,
            f"predicate clause {raw!r} carries no single governed comparator "
            f"({sorted(_COMPARATORS)}).",
        )
    left, comparator, right = (p.strip() for p in parts)

    sum_both = _SUM_BOTH_RE.match(left)
    operand_text = sum_both.group("operands") if sum_both else left
    operands = tuple(t.strip() for t in operand_text.split("+"))

    right = right.strip()
    if right == THRESHOLD_TOKEN:
        rhs: float | None = None
    else:
        try:
            rhs = float(right)
        except ValueError:
            raise PoolEvaluatorError(
                REASON_MALFORMED_PREDICATE,
                f"predicate clause {raw!r} compares against {right!r}, which is "
                f"neither a literal nor {THRESHOLD_TOKEN!r}.",
            ) from None
    return _Comparison(operands=operands, comparator=comparator, rhs=rhs)


def _evaluate_clause(clause: _Comparison, components: Sequence[StatComponent],
                     vocab: StatVocabulary, threshold_value: float | None) -> bool:
    total = 0.0
    for component in components:
        for operand in clause.operands:
            total += float(
                component.values.get(vocab.canonical_operand(operand), 0.0))
    rhs = clause.rhs
    if rhs is None:
        if threshold_value is None:
            raise PoolEvaluatorError(
                REASON_MALFORMED_PREDICATE,
                f"clause uses {THRESHOLD_TOKEN!r} but no threshold was bound; "
                f"the catalog loader refuses an unbound threshold, so reaching "
                f"this means the definition was constructed outside it.",
            )
        rhs = threshold_value
    return _COMPARATORS[clause.comparator](total, rhs)


def evaluate_predicate(spec: PoolDefinitionSpec, subject: Subject,
                       vocab: StatVocabulary,
                       threshold_override: int | None = None,
                       ) -> bool | _Unevaluable:
    """QUALIFIER_PREDICATE — evaluate the STRUCTURED predicate (§C5, §C8).

    `threshold_condition` PROSE IS NEVER READ HERE. Scope §C5, binding: "An
    evaluator that parses threshold_condition is non-conformant." The executable
    form is `predicate`; the prose exists for humans.

    `predicate_quantifier` selects the evaluation frame and nothing else:

        TEAM              one team's totals
        MATCHUP_COMBINED  both participants summed
        MATCHUP_EACH      the condition must hold for EACH participant

    MATCHUP_EACH IS NOT THE COMBINED SUM. #94 ("both teams had 100+ rushing
    yards") is satisfied by 100 and 100 but NOT by 250 and 30, whereas
    MATCHUP_COMBINED #90 would accept the latter. Collapsing the two would
    change the winner set on real data.
    """
    if not spec.predicate:
        raise PoolEvaluatorError(
            REASON_MALFORMED_PREDICATE,
            f"{spec.key!r} is QUALIFIER_PREDICATE with no predicate.",
        )

    threshold = threshold_override
    if threshold is None:
        threshold = spec.threshold_default

    predicate = spec.predicate.strip()
    quantifier = spec.predicate_quantifier

    each = _EACH_TEAM_RE.match(predicate)
    if each:
        if quantifier != "MATCHUP_EACH":
            raise PoolEvaluatorError(
                REASON_MALFORMED_PREDICATE,
                f"{spec.key!r} uses EACH_TEAM(...) with predicate_quantifier "
                f"{quantifier!r}.",
            )
        clauses = [_parse_comparison(c) for c in each.group("inner").split(" AND ")]
        for frame in subject.frames:
            components = filtered_components(
                Subject(subject_id=subject.subject_id,
                        subject_type=SCOPE_TEAM, frames=(frame,)),
                spec.slot_filter, spec.slot_exclusions)
            if not all(_evaluate_clause(c, components, vocab, threshold)
                       for c in clauses):
                return False
        return True

    clauses = [_parse_comparison(c) for c in predicate.split(" AND ")]
    components = filtered_components(subject, spec.slot_filter,
                                     spec.slot_exclusions)
    return all(_evaluate_clause(c, components, vocab, threshold)
               for c in clauses)


# ── Dispatch ──────────────────────────────────────────────────────────────────

_VALUE_SHAPES = {
    "CLOSED_SUM": _closed_value,
    "CLOSED_RATIO": _closed_value,
    "PLAYER_EXTREMUM_WITHIN_SUBJECT": _player_extremum,
    "SLOT_FILTERED_POINTS_SUM": _slot_filtered_points_sum,
    "BALANCE_RATIO": _balance_ratio,
    "MATCHUP_SCORE_SUM": _matchup_score_sum,
    "DISTINCT_CATEGORY_COUNT": _distinct_category_count,
}


def subject_value(spec: PoolDefinitionSpec, subject: Subject,
                  vocab: StatVocabulary | None = None) -> float | _Unevaluable:
    """One subject's metric value under `spec`, or UNEVALUABLE.

    COVERAGE IS CHECKED FIRST, BEFORE ANY ARITHMETIC (§C7.3). A subject whose
    required stats were not affirmatively ingested is unevaluable no matter what
    its component dictionaries happen to contain — component-key presence alone
    cannot carry a subject-level claim, because a kicker's row legitimately
    lacks passing yards."""
    vocab = vocab or load_vocabulary()
    if spec.evaluator_shape == "QUALIFIER_PREDICATE":
        raise PoolEvaluatorError(
            REASON_UNGOVERNED_SHAPE,
            f"{spec.key!r} is QUALIFIER_PREDICATE; call evaluate_predicate(). "
            f"A qualifier has no rankable metric value.",
        )
    try:
        fn = _VALUE_SHAPES[spec.evaluator_shape]
    except KeyError:
        raise PoolEvaluatorError(
            REASON_UNGOVERNED_SHAPE,
            f"{spec.key!r} carries evaluator_shape {spec.evaluator_shape!r}; "
            f"POR §3.4 governs exactly eight.",
        ) from None

    # A blocked definition must raise even when uncovered — the selector fault it
    # reports is more serious than the data gap, and reporting the data gap
    # would let the selector fault go unnoticed.
    if spec.dependency_state == "BLOCKED":
        return fn(spec, subject, vocab)

    if not subject.has_coverage_for(spec.required_stats):
        return UNEVALUABLE
    return fn(spec, subject, vocab)


def subject_qualifies(spec: PoolDefinitionSpec, subject: Subject,
                      vocab: StatVocabulary | None = None,
                      threshold_override: int | None = None,
                      ) -> bool | _Unevaluable:
    """Whether one subject satisfies a QUALIFIER definition, or UNEVALUABLE."""
    vocab = vocab or load_vocabulary()
    if spec.dependency_state == "BLOCKED":
        raise PoolEvaluatorError(
            REASON_BLOCKED_DEFINITION,
            f"definition {spec.key!r} (#{spec.catalog_number}) is BLOCKED and "
            f"must never enter a slate (POR conformance 19). "
            f"blocked_reason: {spec.blocked_reason}",
        )
    if not subject.has_coverage_for(spec.required_stats):
        return UNEVALUABLE
    return evaluate_predicate(spec, subject, vocab, threshold_override)


def assert_direction(spec: PoolDefinitionSpec) -> str:
    if spec.direction not in ("MAX", "MIN"):
        raise PoolEvaluatorError(
            REASON_MISSING_DIRECTION,
            f"RANK_EXTREMUM definition {spec.key!r} requires direction MAX or "
            f"MIN, got {spec.direction!r}",
        )
    return spec.direction