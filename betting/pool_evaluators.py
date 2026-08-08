"""
Pool evaluator framework — RANK_EXTREMUM. Step 5.

Product authority : spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_1.md
Implementation    : spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_1.md §C5

PURE. No Session, no ORM query, no DB write, no network call, no rollover logic,
and no branch on definition_key or display_name anywhere. The evaluator never
retrieves a stat: the caller hands it normalized facts keyed by canonical
identifier, and `sum(rushing_yards + receiving_yards)` means aggregate the
supplied values under those identifiers. Where they came from is not this
module's concern, which is what makes synthetic fixtures authoritative.

THE RATIFIED GRAMMAR — closed, and an implementation grammar for existing
declarative metadata, not permission to invent Pool semantics:

    expression   := aggregate | aggregate " / " aggregate
    aggregate    := "sum(" scope_prefix? operand_list ")"
    scope_prefix := "both teams "
    operand_list := identifier
                  | identifier " + " identifier
                  | identifier " + " identifier " + " identifier
    identifier   := [a-z0-9_]+

Whitespace is literal and strict: " + " and " / " with spaces, exactly as
ratified. Input is never normalized before parsing. All 65 regular canonical
expressions in spec/pool_catalog_rev1_1.json parse under this grammar with zero
failures, verified against the JSON rather than a hand-copied list.

No eval(). No ast evaluation. No attribute access. No function call other than
sum(...). No multiplication, subtraction, or nesting. Anything outside the
grammar fails closed with a named domain error.

SCOPE ENFORCEMENT, and why MATCHUP is enforced. A TEAM definition carrying
"both teams" fails closed — that rule is hard by ruling. For MATCHUP the ruling
describes "both teams" as what current expressions use without stating it as a
requirement, so it was checked empirically: of the 29 MATCHUP RANK_EXTREMUM
definitions with a non-null expression, 28 carry "both teams". The single
exception is #76 shootout_of_the_week, whose expression is not parseable under
this grammar at all (no sum(), table-qualified attributes) and which is
therefore rejected syntactically before scope is ever considered. Enforcing the
MATCHUP rule therefore rejects zero canonical rows the grammar would otherwise
accept, so it is enforced.

#76 IS REJECTED SYNTACTICALLY, NOT BY metric_kind. Its metric_kind is
SIMPLE_AGG, not COMPOSITE — a rejection keyed on metric_kind == COMPOSITE
catches the seven null-formula definitions and misses #76 entirely. Rejection
here is by grammar. #76 requires a catalog-expression correction before
production rotation activation; recorded, not acted on.

ONE ERROR FAMILY. PoolEvaluatorError covers a missing expression, unsupported
syntax, a malformed expression, a scope violation, a metric_kind mismatch, an
unknown operand, an empty subject set, and a fail-closed zero denominator. The
reason is carried as a field; behavior never branches on definition identity.

AN EMPTY SUBJECT SET RAISES. It is not a no-winner outcome. QUALIFIER and
RANK_EXTREMUM differ here and the distinction is the whole point: a QUALIFIER
can have subjects present and none satisfying the predicate, which is a
legitimate competitive result with a defined settlement path. RANK_EXTREMUM
given one or more subjects ALWAYS has an extremum, so zero subjects can only
mean the caller supplied nothing to rank — an upstream input failure. Returning
an empty winner set would let that failure masquerade as a real competitive
outcome and settle as one. Same principle as the null-expression rule: invalid
upstream state surfaces loudly rather than quietly resolving.

THE ADAPTOR INPUT CONTRACT — LOAD-BEARING, AND NOT YET BUILT. The requirement is
WEEKLY-GLOBAL, not per-component. Whatever eventually normalizes weekly stats
into SubjectFacts must ensure every canonical stat operand the evaluator may
need is REPRESENTED SOMEWHERE in that week's normalized fact input, even when
its true aggregate value is zero. An individual component may still omit a stat
that is structurally inapplicable to it — a kicker's row carries no
passing_yards, and that omission contributes 0.0 for that component under the
existing semantics, which is correct. What is forbidden is a sparse,
non-zero-only adaptor that lets a legitimate canonical operand disappear from
EVERY component merely because nobody happened to record that event all week.

The three cases, stated so they cannot be misread:

    component-level structural omission              -> PERMITTED, contributes 0.0
    weekly-global omission of a real operand
        whose true value was zero                    -> FORBIDDEN
    weekly-global omission because the operand
        is unknown or misspelled                     -> UNKNOWN_OPERAND

Total absence across every component of every subject remains UNKNOWN_OPERAND,
which is what preserves typo and input-contract detection. That is precisely why
the middle case must never occur: absence is the evaluator's only signal for a
bad operand name, so if a real all-zero week could also produce total absence,
the two would be indistinguishable and the pool would raise instead of settling.
Guaranteeing weekly-global representation removes the ambiguity at the source,
which is the only place it can be removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

# ── Error family ──────────────────────────────────────────────────────────────

REASON_MISSING_EXPRESSION = "MISSING_EXPRESSION"
REASON_UNSUPPORTED_EXPRESSION = "UNSUPPORTED_EXPRESSION"
REASON_MALFORMED_EXPRESSION = "MALFORMED_EXPRESSION"
REASON_SCOPE_MISMATCH = "SCOPE_MISMATCH"
REASON_METRIC_KIND_MISMATCH = "METRIC_KIND_MISMATCH"
REASON_UNKNOWN_OPERAND = "UNKNOWN_OPERAND"
REASON_ZERO_DENOMINATOR = "ZERO_DENOMINATOR"
REASON_MISSING_DIRECTION = "MISSING_DIRECTION"
REASON_EMPTY_SUBJECT_SET = "EMPTY_SUBJECT_SET"


class PoolEvaluatorError(ValueError):
    """The single evaluator-domain exception family. `reason` identifies which
    rule was violated; nothing downstream should branch on definition identity
    to interpret it."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


# ── Input contract ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SubjectFacts:
    """Normalized weekly facts for ONE ranked subject.

    `subject_id` is whatever the caller ranks — a team id for TEAM scope, a
    matchup id for MATCHUP scope. The evaluator treats it as an opaque label.

    `components` is the subject's constituent stat rows (per-player rows for a
    roster, or the combined per-player rows of both teams for a matchup). It is
    a SEQUENCE rather than one flat mapping precisely so that POR §3.2 is
    representable and testable: aggregate-over-aggregate sums each operand
    across components and divides once, and average-of-per-component-ratios is
    a different number that this module must never produce. A caller that
    pre-flattens to a single component still works; it simply cannot exhibit
    the distinction.

    Missing identifiers inside a component contribute 0.0 — a kicker's row has
    no passing_yards. An operand absent from EVERY component of EVERY subject
    is a contract violation, not a zero, and raises UNKNOWN_OPERAND; that is
    what catches a typo'd or unsupplied stat name."""

    subject_id: object
    components: tuple[Mapping[str, float], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MetricSpec:
    """The definition metadata the evaluator reads. §C5 names the signature
    RANK_EXTREMUM(subjects, metric_expression, metric_kind, direction); scope
    and zero_denominator_guard are additionally required to enforce POR §3.2
    and §3.3, so the four are carried here alongside them rather than as a
    growing positional list.

    zero_denominator_guard is read AS A FLAG. It is not inferred from
    metric_kind, even though the two coincide on all 19 current RATIO rows."""

    metric_expression: str | None
    metric_kind: str
    direction: str | None
    scope: str
    zero_denominator_guard: bool = False
    aggregate_over_aggregate_required: bool = False
    tie_rule: str = "EVEN_SPLIT"


@dataclass(frozen=True)
class RankExtremumResult:
    """Winner SET plus the computed values. The evaluator computes no money —
    EVEN_SPLIT is a payout concern and is out of scope here."""

    winners: tuple[object, ...]
    values: Mapping[object, float]
    extremum: float | None


# ── Grammar ───────────────────────────────────────────────────────────────────

_IDENT = r"[a-z0-9_]+"
_OPERAND_LIST = rf"{_IDENT}(?: \+ {_IDENT}){{0,2}}"
_AGGREGATE = rf"sum\((?:both teams )?{_OPERAND_LIST}\)"

_EXPRESSION_RE = re.compile(
    rf"\A(?P<numerator>{_AGGREGATE})(?: / (?P<denominator>{_AGGREGATE}))?\Z"
)
_AGGREGATE_RE = re.compile(
    rf"\Asum\((?P<prefix>both teams )?(?P<operands>{_OPERAND_LIST})\)\Z"
)

_SCOPE_TEAM = "TEAM"
_SCOPE_MATCHUP = "MATCHUP"


@dataclass(frozen=True)
class Aggregate:
    both_teams: bool
    operands: tuple[str, ...]


@dataclass(frozen=True)
class ParsedExpression:
    numerator: Aggregate
    denominator: Aggregate | None

    @property
    def is_ratio(self) -> bool:
        return self.denominator is not None

    @property
    def aggregates(self) -> tuple[Aggregate, ...]:
        return (self.numerator,) if self.denominator is None \
            else (self.numerator, self.denominator)


def _parse_aggregate(raw: str) -> Aggregate:
    m = _AGGREGATE_RE.match(raw)
    if m is None:                                    # unreachable via parse()
        raise PoolEvaluatorError(
            REASON_MALFORMED_EXPRESSION,
            f"aggregate {raw!r} does not match sum(<operand_list>)",
        )
    return Aggregate(
        both_teams=m.group("prefix") is not None,
        operands=tuple(m.group("operands").split(" + ")),
    )


def parse_metric_expression(expression: str | None) -> ParsedExpression:
    """Parse one metric_expression under the ratified grammar. Strict literal
    whitespace; the input is never normalized first."""
    if expression is None:
        raise PoolEvaluatorError(
            REASON_MISSING_EXPRESSION,
            "metric_expression is NULL. Blocked definitions are excluded "
            "upstream, so a null formula reaching the evaluator is an "
            "invariant violation, not a legitimate zero-winner result.",
        )
    if not isinstance(expression, str):
        raise PoolEvaluatorError(
            REASON_MALFORMED_EXPRESSION,
            f"metric_expression must be a string, got {type(expression).__name__}",
        )
    m = _EXPRESSION_RE.match(expression)
    if m is None:
        raise PoolEvaluatorError(
            REASON_UNSUPPORTED_EXPRESSION,
            f"{expression!r} is not expressible in the ratified grammar "
            f"(expression := aggregate | aggregate ' / ' aggregate; "
            f"aggregate := 'sum(' 'both teams '? operand_list ')').",
        )
    denominator = m.group("denominator")
    return ParsedExpression(
        numerator=_parse_aggregate(m.group("numerator")),
        denominator=_parse_aggregate(denominator) if denominator else None,
    )


def validate_against_spec(parsed: ParsedExpression, spec: MetricSpec) -> None:
    """Semantic validation: metric_kind arity and scope consistency."""
    kind = spec.metric_kind
    if kind == "COMPOSITE":
        raise PoolEvaluatorError(
            REASON_UNSUPPORTED_EXPRESSION,
            "COMPOSITE definitions are not executable under the ratified "
            "grammar; their formulas are recorded as undefined and must not "
            "be invented.",
        )
    if kind == "SIMPLE_AGG" and parsed.is_ratio:
        raise PoolEvaluatorError(
            REASON_METRIC_KIND_MISMATCH,
            "metric_kind SIMPLE_AGG requires exactly one aggregate and no "
            "'/' operator, but a ratio was supplied.",
        )
    if kind == "RATIO" and not parsed.is_ratio:
        raise PoolEvaluatorError(
            REASON_METRIC_KIND_MISMATCH,
            "metric_kind RATIO requires aggregate ' / ' aggregate, but a "
            "single aggregate was supplied.",
        )
    if kind not in ("SIMPLE_AGG", "RATIO"):
        raise PoolEvaluatorError(
            REASON_METRIC_KIND_MISMATCH, f"unknown metric_kind {kind!r}"
        )

    for agg in parsed.aggregates:
        if spec.scope == _SCOPE_TEAM and agg.both_teams:
            raise PoolEvaluatorError(
                REASON_SCOPE_MISMATCH,
                "a TEAM definition must not carry the 'both teams' scope "
                "prefix.",
            )
        if spec.scope == _SCOPE_MATCHUP and not agg.both_teams:
            raise PoolEvaluatorError(
                REASON_SCOPE_MISMATCH,
                "a MATCHUP definition must carry the 'both teams' scope "
                "prefix on every aggregate.",
            )
        if spec.scope not in (_SCOPE_TEAM, _SCOPE_MATCHUP):
            raise PoolEvaluatorError(
                REASON_SCOPE_MISMATCH, f"unknown scope {spec.scope!r}"
            )


# ── Aggregation and ranking ───────────────────────────────────────────────────

def _aggregate_value(agg: Aggregate, subject: SubjectFacts) -> float:
    """Σ over components of Σ over operands. This is the ONLY aggregation
    performed — POR §3.2's sum(numerator) across the roster or matchup."""
    total = 0.0
    for component in subject.components:
        for operand in agg.operands:
            total += float(component.get(operand, 0.0))
    return total


def _assert_operands_known(parsed: ParsedExpression,
                           subjects: Sequence[SubjectFacts]) -> None:
    supplied: set[str] = set()
    for s in subjects:
        for component in s.components:
            supplied.update(component.keys())
    for agg in parsed.aggregates:
        for operand in agg.operands:
            if operand not in supplied:
                raise PoolEvaluatorError(
                    REASON_UNKNOWN_OPERAND,
                    f"operand {operand!r} appears in no supplied component of "
                    f"any subject; the input contract does not carry it.",
                )


def rank_extremum(subjects: Sequence[SubjectFacts],
                  spec: MetricSpec) -> RankExtremumResult:
    """Compute one value per subject, rank, and return ALL subjects tied at the
    extreme — POR §3 line 78.

    RATIO is aggregate-over-aggregate ONLY: Σnumerator / Σdenominator, one
    division, never a mean of per-component ratios (POR §3.2, binding).

    Zero denominator fails closed and never divides, never coerces to zero and
    never awards (POR §3.3). zero_denominator_guard is read as a flag and
    distinguishes a GOVERNED fail-closed from an unguarded one; both refuse,
    because dividing by zero is not an available behavior either way.

    An empty subject set RAISES — it is an upstream input failure, not a
    no-winner outcome (see module notes)."""
    parsed = parse_metric_expression(spec.metric_expression)
    validate_against_spec(parsed, spec)

    if spec.direction not in ("MAX", "MIN"):
        raise PoolEvaluatorError(
            REASON_MISSING_DIRECTION,
            f"RANK_EXTREMUM requires direction MAX or MIN, got "
            f"{spec.direction!r}",
        )

    subjects = tuple(subjects)
    if not subjects:
        # Ruled: this raises. A RANK_EXTREMUM with any subject at all has an
        # extremum, so zero subjects means the caller supplied nothing to rank.
        # That is an upstream input failure, and returning an empty winner set
        # would let it settle as though it were a real competitive no-winner
        # result. Not a branch on definition identity — it inspects only the
        # length of the input.
        raise PoolEvaluatorError(
            REASON_EMPTY_SUBJECT_SET,
            "no subjects were supplied to rank. RANK_EXTREMUM with one or more "
            "subjects always has an extremum, so an empty subject set is an "
            "upstream input failure, not a no-winner outcome.",
        )

    _assert_operands_known(parsed, subjects)

    values: dict[object, float] = {}
    for subject in subjects:
        numerator = _aggregate_value(parsed.numerator, subject)
        if parsed.denominator is None:
            values[subject.subject_id] = numerator
            continue
        denominator = _aggregate_value(parsed.denominator, subject)
        if denominator == 0:
            raise PoolEvaluatorError(
                REASON_ZERO_DENOMINATOR,
                f"denominator aggregate is zero for subject "
                f"{subject.subject_id!r}; failing closed without dividing, "
                f"coercing or awarding "
                f"(zero_denominator_guard={spec.zero_denominator_guard}).",
            )
        values[subject.subject_id] = numerator / denominator

    extremum = max(values.values()) if spec.direction == "MAX" \
        else min(values.values())
    winners = tuple(sid for sid, v in values.items() if v == extremum)
    return RankExtremumResult(winners=winners, values=values, extremum=extremum)