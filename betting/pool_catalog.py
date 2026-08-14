"""
Pool catalog and stat vocabulary — the metadata that DRIVES the common engine.

Product authority : spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_3.md
Implementation    : spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_3.md §C1
Catalog data      : spec/pool_catalog_rev1_3.json
Stat vocabulary   : spec/pool_stat_vocabulary_rev1_0.json

THE CATALOG IS DATA, NOT CODE (POR §3.1 / AP-323). Eighty active definitions do
NOT imply eighty evaluator functions. This module loads the governed artifacts,
proves them internally consistent, and hands the engine declarative metadata.
Nothing downstream branches on a definition key, and nothing here knows what any
individual Pool means.

WHY VALIDATION LIVES HERE AND RUNS AT LOAD. Every rule below is a POR
conformance item that is cheap to check once and impossible to notice later. A
retired definition that reaches a slate, a required stat that is not a canonical
vocabulary key, a predicate carrying a free variable — each produces a wrong
winner or an unsettleable Pool weeks after the mistake was made. Loading is the
last moment at which the artifact can be rejected as a whole rather than
diagnosed one broken week at a time.

ALIAS RESOLUTION IS LOAD-BEARING AND EASY TO MISS. The catalog's
`metric_expression` strings are written in the SOURCE ARTIFACT's spelling, which
includes governed aliases: #13 carries `sum(total_touchdowns)` while its
`required_stats` carries the canonical `total_touchdown_credits`, and #31 carries
`sum(yards) / sum(touches)` against canonical `scrimmage_yards`. POR §1.4 rules
that aliases "resolve to canonical names and are not separate stats", and §C7.2
puts that resolution BEFORE the evaluator boundary — "the evaluator never sees an
alias". `canonical_operand()` is that resolution, and it is driven by the
vocabulary's own `aliases` lists rather than a hand-copied table, so a future
vocabulary revision cannot leave a second, stale mapping behind in this file.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping

_SPEC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "spec")

CATALOG_PATH = os.path.join(_SPEC_DIR, "pool_catalog_rev1_3.json")
VOCABULARY_PATH = os.path.join(_SPEC_DIR, "pool_stat_vocabulary_rev1_0.json")

# POR §1.1 — retired numbers and keys are reserved PERMANENTLY and never reused.
# The numbers are read from the artifact's own `retired` block (below) so the two
# cannot drift. These two KEYS are stated in POR §1.1 prose but carry no row in
# the artifact — #97 and #98 were authored and retired inside Revision 1.3 and
# never entered the active set, so there is no definition object to read them
# from. They are named here because "reserved" has to be enforceable.
RESERVED_RETIRED_KEYS = frozenset({
    "most_field_goal_yards",              # #97
    "highest_combined_field_goal_yards",  # #98
    "the_lineup",                         # legacy implementation name
    "bench_burn",                         # legacy implementation name
})

# POR §3.4 / Scope §C8 — the eight governed executable shapes.
CLOSED_SHAPES = frozenset({"CLOSED_SUM", "CLOSED_RATIO"})
EVALUATOR_SHAPES = frozenset({
    "CLOSED_SUM",
    "CLOSED_RATIO",
    "QUALIFIER_PREDICATE",
    "PLAYER_EXTREMUM_WITHIN_SUBJECT",
    "SLOT_FILTERED_POINTS_SUM",
    "BALANCE_RATIO",
    "DISTINCT_CATEGORY_COUNT",
    "MATCHUP_SCORE_SUM",
})

EVALUATOR_FAMILIES = frozenset({"RANK_EXTREMUM", "QUALIFIER"})
PREDICATE_QUANTIFIERS = frozenset({"TEAM", "MATCHUP_COMBINED", "MATCHUP_EACH"})

# The single free variable a configurable predicate is permitted to carry. It is
# bound from threshold_default (or a commissioner override within the governed
# bound); any OTHER bare identifier in a predicate that is neither a canonical
# stat nor a number is an unbound variable and is refused — POR conformance 34c.
THRESHOLD_TOKEN = "threshold_value"


class PoolCatalogError(ValueError):
    """Catalog- or vocabulary-domain failure. `reason` names the violated rule;
    nothing downstream branches on definition identity to interpret it."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_UNKNOWN_STAT = "UNKNOWN_STAT"
REASON_RETIRED_DEFINITION = "RETIRED_DEFINITION"
REASON_MALFORMED_CATALOG = "MALFORMED_CATALOG"
REASON_UNBOUND_PREDICATE_VARIABLE = "UNBOUND_PREDICATE_VARIABLE"
REASON_BLOCKED_REASON_MISMATCH = "BLOCKED_REASON_MISMATCH"
REASON_SHAPE_MISMATCH = "SHAPE_MISMATCH"
#: WP1B §10 — a postseason-eligible matchup-vs-matchup Pool.
REASON_PROHIBITED_POSTSEASON_STRUCTURE = "PROHIBITED_POSTSEASON_STRUCTURE"


# ── Stat vocabulary ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StatVocabulary:
    """POR §1.4 — the single authority for stat identity.

    `canonical` is the set of canonical names. `alias_to_canonical` maps every
    governed alias onto its canonical name AND maps each canonical name onto
    itself, so `canonical_operand()` is a total function over valid input and
    callers never need a two-step lookup with a fallback.
    """

    canonical: frozenset[str]
    alias_to_canonical: Mapping[str, str]
    derived_formula: Mapping[str, str | None]
    explicit_zero_is_valid: Mapping[str, bool]
    missing_value_behavior: Mapping[str, str]

    def canonical_operand(self, operand: str) -> str:
        """Resolve one expression operand to its canonical vocabulary name.

        Raises rather than passing an unknown operand through. An unrecognised
        operand is a typo or an ungoverned stat, and letting it reach the
        evaluator would surface as a silent zero contribution — a wrong-winner
        defect that never announces itself."""
        try:
            return self.alias_to_canonical[operand]
        except KeyError:
            raise PoolCatalogError(
                REASON_UNKNOWN_STAT,
                f"{operand!r} is neither a canonical stat nor a governed alias "
                f"in the Rev1.0 stat vocabulary. POR §1.4 makes the vocabulary "
                f"the single authority for stat identity; an ungoverned operand "
                f"is refused rather than resolved to zero.",
            ) from None


@lru_cache(maxsize=1)
def load_vocabulary(path: str = VOCABULARY_PATH) -> StatVocabulary:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    stats = raw.get("stats")
    if not isinstance(stats, list) or not stats:
        raise PoolCatalogError(
            REASON_MALFORMED_CATALOG,
            f"{path} carries no 'stats' list.",
        )

    canonical: set[str] = set()
    alias_map: dict[str, str] = {}
    derived: dict[str, str | None] = {}
    zero_ok: dict[str, bool] = {}
    missing: dict[str, str] = {}

    for entry in stats:
        name = entry["canonical_name"]
        if name in canonical:
            raise PoolCatalogError(
                REASON_MALFORMED_CATALOG,
                f"canonical stat {name!r} is declared twice.",
            )
        canonical.add(name)
        alias_map[name] = name
        derived[name] = entry.get("derived_formula")
        zero_ok[name] = bool(entry.get("explicit_zero_is_valid"))
        missing[name] = entry.get("missing_value_behavior") or ""
        for alias in entry.get("aliases") or ():
            prior = alias_map.get(alias)
            if prior is not None and prior != name:
                raise PoolCatalogError(
                    REASON_MALFORMED_CATALOG,
                    f"alias {alias!r} resolves to both {prior!r} and {name!r}.",
                )
            alias_map[alias] = name

    return StatVocabulary(
        canonical=frozenset(canonical),
        alias_to_canonical=alias_map,
        derived_formula=derived,
        explicit_zero_is_valid=zero_ok,
        missing_value_behavior=missing,
    )


# ── Catalog ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PoolDefinitionSpec:
    """One catalog definition, as the engine reads it.

    A frozen snapshot of the governed metadata — deliberately NOT the ORM row,
    so the pure evaluator and selector layers can be exercised with no database
    at all and a fixture is as authoritative as production data.
    """

    key: str
    catalog_number: int
    display_name: str
    category: str
    scope: str
    mechanic: str
    evaluator_family: str
    evaluator_shape: str
    metric_kind: str
    direction: str | None
    metric_expression: str | None
    governed_definition: str | None
    threshold_condition: str | None
    predicate: str | None
    predicate_quantifier: str | None
    threshold_configurable: bool
    threshold_default: int | None
    required_stats: tuple[str, ...]
    required_stats_resolved: bool
    required_stats_unresolved_reason: str | None
    source_mapping_complete: bool
    unmapped_required_stats: tuple[str, ...]
    starter_slot_rule: str
    slot_filter: tuple[str, ...]
    slot_exclusions: tuple[str, ...]
    self_pick_rule: str
    anti_tanking_review: str
    data_dependency: str
    dependency_state: str
    blocked_reason: str | None
    product_complete: bool
    definition_runtime_eligible: bool
    definition_block_reason: str | None
    regular_season_eligible: bool
    postseason_eligible: bool | None
    rollover_eligible: bool
    tie_rule: str
    aggregate_over_aggregate_required: bool
    zero_denominator_guard: bool

    @property
    def is_closed_grammar(self) -> bool:
        return self.evaluator_shape in CLOSED_SHAPES


@dataclass(frozen=True)
class PoolCatalog:
    definitions: tuple[PoolDefinitionSpec, ...]
    retired_numbers: frozenset[int]
    revision: str

    def by_key(self, key: str) -> PoolDefinitionSpec:
        for d in self.definitions:
            if d.key == key:
                return d
        raise PoolCatalogError(
            REASON_MALFORMED_CATALOG, f"no active definition with key {key!r}"
        )

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(d.key for d in self.definitions)


def _tuple_or_empty(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(value)


@lru_cache(maxsize=1)
def load_catalog(path: str = CATALOG_PATH) -> PoolCatalog:
    """Load, validate and freeze the Rev1.3 catalog.

    Validation is total: every rule below is checked against EVERY row, and the
    first violation raises. A partially valid catalog is not returned, because a
    caller holding one cannot tell which rows it may trust."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    vocab = load_vocabulary()

    retired_numbers = frozenset(
        r["catalog_number"] for r in raw.get("retired", ())
        if r.get("catalog_number") is not None
    )

    seen_keys: set[str] = set()
    seen_numbers: set[int] = set()
    specs: list[PoolDefinitionSpec] = []

    for row in raw["definitions"]:
        key = row["key"]
        number = row["catalog_number"]

        # ── retirement, both axes ────────────────────────────────────────────
        if number in retired_numbers or key in RESERVED_RETIRED_KEYS:
            raise PoolCatalogError(
                REASON_RETIRED_DEFINITION,
                f"definition #{number} {key!r} is retired; POR §1.1 reserves "
                f"retired numbers and keys permanently and they are never "
                f"reused or re-seeded.",
            )
        if key in seen_keys:
            raise PoolCatalogError(
                REASON_MALFORMED_CATALOG, f"duplicate definition key {key!r}")
        if number in seen_numbers:
            raise PoolCatalogError(
                REASON_MALFORMED_CATALOG, f"duplicate catalog number {number}")
        seen_keys.add(key)
        seen_numbers.add(number)

        shape = row["evaluator_shape"]
        if shape not in EVALUATOR_SHAPES:
            raise PoolCatalogError(
                REASON_SHAPE_MISMATCH,
                f"#{number} {key!r} carries ungoverned evaluator_shape "
                f"{shape!r}; POR §3.4 governs exactly eight.",
            )
        if row["evaluator_family"] not in EVALUATOR_FAMILIES:
            raise PoolCatalogError(
                REASON_SHAPE_MISMATCH,
                f"#{number} {key!r} carries unknown evaluator_family "
                f"{row['evaluator_family']!r}.",
            )

        # POR §3.4, binding: "A null metric_expression on a non-CLOSED_* shape is
        # correct and expected, not a missing formula." The converse is the real
        # check — a CLOSED_* shape MUST carry an expression, and a non-closed
        # shape must NOT, or the engine would have two candidate authorities for
        # the same computation and no rule for which wins.
        expression = row["metric_expression"]
        if shape in CLOSED_SHAPES and not expression:
            raise PoolCatalogError(
                REASON_SHAPE_MISMATCH,
                f"#{number} {key!r} is {shape} but carries no metric_expression.",
            )
        if shape not in CLOSED_SHAPES and expression:
            raise PoolCatalogError(
                REASON_SHAPE_MISMATCH,
                f"#{number} {key!r} is {shape}, whose governed_definition is "
                f"authoritative, yet also carries metric_expression "
                f"{expression!r}. Two authorities for one computation.",
            )
        if shape not in CLOSED_SHAPES and shape != "QUALIFIER_PREDICATE" \
                and not row.get("governed_definition"):
            raise PoolCatalogError(
                REASON_SHAPE_MISMATCH,
                f"#{number} {key!r} is {shape} and carries no "
                f"governed_definition; POR §3.4 makes that prose the "
                f"authoritative rule for a non-closed shape.",
            )

        # ── POR §7.0 — blocked_reason is the single canonical block field ────
        state = row["dependency_state"]
        blocked_reason = row.get("blocked_reason")
        if state == "BLOCKED" and not blocked_reason:
            raise PoolCatalogError(
                REASON_BLOCKED_REASON_MISMATCH,
                f"#{number} {key!r} is BLOCKED with no blocked_reason.",
            )
        if state == "ENABLED" and blocked_reason:
            raise PoolCatalogError(
                REASON_BLOCKED_REASON_MISMATCH,
                f"#{number} {key!r} is ENABLED yet carries a blocked_reason.",
            )

        # ── WP1B §10 — MATCHUP-VS-MATCHUP IS PROHIBITED IN THE POSTSEASON ────
        #
        # A MATCHUP-scoped RANK_EXTREMUM definition makes whole matchups the
        # COMPETING OPTIONS: the GM picks one matchup and wins if it out-scores
        # the others. In the postseason that is exactly the structure the POR
        # forbids — "which two-team fantasy matchup scores more than another".
        #
        # MATCHUP + QUALIFIER is a different shape and stays permitted: each
        # matchup independently satisfies a predicate, so a threshold
        # proposition on one championship game is a legal card. The distinction
        # is structural rather than editorial, which is what makes it checkable
        # here instead of relying on a reviewer noticing.
        #
        # ENFORCED AS CATALOG VALIDATION, NOT AS A SELECTOR FILTER. The selector
        # could drop such a row at draw time, but then a future catalog edit
        # would sit in the artifact looking approved and only fail silently at
        # runtime. Refusing to LOAD the catalog makes the prohibition
        # unfalsifiable and makes the bad edit impossible to land.
        if (row["scope"] == "MATCHUP"
                and row["evaluator_family"] == "RANK_EXTREMUM"
                and row.get("postseason_eligible") is True):
            raise PoolCatalogError(
                REASON_PROHIBITED_POSTSEASON_STRUCTURE,
                f"#{number} {key!r} is MATCHUP/RANK_EXTREMUM and marked "
                f"postseason_eligible. A postseason Pool may not pit one full "
                f"championship matchup against another (WP1B §5). MATCHUP "
                f"definitions may be postseason-eligible only in the QUALIFIER "
                f"family, where each matchup qualifies independently.",
            )

        # ── POR §1.4 — required_stats are canonical vocabulary keys ONLY ─────
        required = _tuple_or_empty(row.get("required_stats"))
        for stat in required:
            if stat not in vocab.canonical:
                raise PoolCatalogError(
                    REASON_UNKNOWN_STAT,
                    f"#{number} {key!r} declares required stat {stat!r}, which "
                    f"is not a canonical name in the stat vocabulary. POR §1.4: "
                    f"the catalog stores canonical keys only — never source "
                    f"identifiers, aliases or formulas.",
                )

        # ── expression operands resolve to canonical names ───────────────────
        if expression:
            for operand in _expression_operands(expression):
                vocab.canonical_operand(operand)   # raises UNKNOWN_STAT

        # ── POR §1.5 / conformance 34c — no unbound predicate variable ───────
        predicate = row.get("predicate")
        quantifier = row.get("predicate_quantifier")
        if row["evaluator_family"] == "QUALIFIER":
            if not predicate:
                raise PoolCatalogError(
                    REASON_MALFORMED_CATALOG,
                    f"#{number} {key!r} is family QUALIFIER with no structured "
                    f"predicate; POR §1.5 requires all 16 to carry one.",
                )
            if quantifier not in PREDICATE_QUANTIFIERS:
                raise PoolCatalogError(
                    REASON_MALFORMED_CATALOG,
                    f"#{number} {key!r} carries predicate_quantifier "
                    f"{quantifier!r}; §1.5 admits exactly three values.",
                )
        if predicate:
            _assert_predicate_bound(
                number, key, predicate, vocab,
                threshold_configurable=bool(row["threshold_configurable"]),
                threshold_default=row.get("threshold_default"),
            )

        specs.append(PoolDefinitionSpec(
            key=key,
            catalog_number=number,
            display_name=row["display_name"],
            category=row["category"],
            scope=row["scope"],
            mechanic=row["mechanic"],
            evaluator_family=row["evaluator_family"],
            evaluator_shape=shape,
            metric_kind=row["metric_kind"],
            direction=row["direction"],
            metric_expression=expression,
            governed_definition=row.get("governed_definition"),
            threshold_condition=row.get("threshold_condition"),
            predicate=predicate,
            predicate_quantifier=quantifier,
            threshold_configurable=bool(row["threshold_configurable"]),
            threshold_default=row.get("threshold_default"),
            required_stats=required,
            required_stats_resolved=bool(row["required_stats_resolved"]),
            required_stats_unresolved_reason=row.get(
                "required_stats_unresolved_reason"),
            source_mapping_complete=bool(row["source_mapping_complete"]),
            unmapped_required_stats=_tuple_or_empty(
                row.get("unmapped_required_stats")),
            starter_slot_rule=row["starter_slot_rule"],
            slot_filter=_tuple_or_empty(row.get("slot_filter")),
            slot_exclusions=_tuple_or_empty(row.get("slot_exclusions")),
            self_pick_rule=row["self_pick_rule"],
            anti_tanking_review=row["anti_tanking_review"],
            data_dependency=row["data_dependency"],
            dependency_state=state,
            blocked_reason=blocked_reason,
            product_complete=bool(row["product_complete"]),
            definition_runtime_eligible=bool(row["definition_runtime_eligible"]),
            definition_block_reason=row.get("definition_block_reason"),
            regular_season_eligible=bool(row["regular_season_eligible"]),
            postseason_eligible=row.get("postseason_eligible"),
            rollover_eligible=bool(row["rollover_eligible"]),
            tie_rule=row["tie_rule"],
            aggregate_over_aggregate_required=bool(
                row["aggregate_over_aggregate_required"]),
            zero_denominator_guard=bool(row["zero_denominator_guard"]),
        ))

    return PoolCatalog(
        definitions=tuple(specs),
        retired_numbers=retired_numbers,
        revision=str(raw.get("revision", "1.3")),
    )


# ONE identifier pattern for both expressions and predicates. It deliberately
# spans the full identifier — letters, digits and underscores — rather than
# lowercase only. A lowercase-anchored pattern splits `SUM_BOTH_TEAMS` into the
# fragment `_`, which then fails vocabulary lookup for a reason that has nothing
# to do with the actual text. Classify AFTER tokenizing, never during.
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Grammar noise words that are never operands: the aggregate function and the
# 'both teams' scope prefix.
_NON_OPERAND_TOKENS = frozenset({"sum", "both", "teams"})


def _expression_operands(expression: str) -> tuple[str, ...]:
    return tuple(
        t for t in _IDENTIFIER.findall(expression)
        if t not in _NON_OPERAND_TOKENS
    )


# Predicate keywords that are syntax, not operands.
_PREDICATE_KEYWORDS = frozenset({
    "AND", "OR", "SUM_BOTH_TEAMS", "EACH_TEAM",
})


def _assert_predicate_bound(number: int, key: str, predicate: str,
                            vocab: StatVocabulary, *,
                            threshold_configurable: bool,
                            threshold_default: int | None) -> None:
    """POR conformance 34c — every active predicate resolves with NO free
    variable.

    `threshold_value` is the ONE permitted placeholder, and it is permitted only
    when the row declares itself configurable AND supplies a governed default.
    A configurable threshold with no default would be exactly the §1.7 defect —
    a definition that needs commissioner interpretation to become mathematically
    complete — and §1.7 makes such a definition ineligible for the catalog."""
    for token in _IDENTIFIER.findall(predicate):
        if token in _PREDICATE_KEYWORDS:
            continue
        if token == THRESHOLD_TOKEN:
            if not threshold_configurable or threshold_default is None:
                raise PoolCatalogError(
                    REASON_UNBOUND_PREDICATE_VARIABLE,
                    f"#{number} {key!r} uses {THRESHOLD_TOKEN!r} but is "
                    f"threshold_configurable={threshold_configurable} with "
                    f"threshold_default={threshold_default!r}. An unbound "
                    f"threshold makes the definition commissioner-interpreted, "
                    f"which POR §1.7 refuses.",
                )
            continue
        if token.upper() == token and any(c.isalpha() for c in token):
            # An ALL-CAPS identifier is grammar, not data. One the parser does
            # not recognise would be a silent no-op at evaluation time — the
            # predicate would still evaluate, just not to what it reads as — so
            # it is refused here rather than ignored.
            raise PoolCatalogError(
                REASON_UNBOUND_PREDICATE_VARIABLE,
                f"#{number} {key!r} predicate carries unknown keyword "
                f"{token!r}; the governed grammar is "
                f"{sorted(_PREDICATE_KEYWORDS)}.",
            )
        # Anything else must be a governed stat. Raises UNKNOWN_STAT otherwise,
        # which is the same failure a typo in a metric_expression produces.
        vocab.canonical_operand(token)


# ── Seeding ───────────────────────────────────────────────────────────────────

def seed_definitions(db, catalog: PoolCatalog | None = None) -> dict[str, int]:
    """Upsert every active definition into `pool_definition` — Scope §I step 8.

    IDEMPOTENT. Re-running updates the governed columns in place rather than
    inserting duplicates, so a catalog revision ships as a re-seed and existing
    `pool_instance` rows keep their foreign key. The key is the identity and is
    never rewritten — POR §1.8: "A key is an immutable identifier and does not
    track a display name."

    THE SEEDER IS NOT THE ONLY GUARD. `ck_pool_definition_retired_numbers` on
    the table refuses a retired number independently, so a fixture or a manual
    INSERT that bypasses this function still cannot resurrect one. Two
    independent enforcement points, because a seeder can be bypassed and a CHECK
    cannot.

    Does NOT commit — the caller owns the transaction.
    """
    from db.schema import PoolDefinition

    catalog = catalog or load_catalog()
    inserted = updated = 0

    existing = {row.key: row for row in db.query(PoolDefinition).all()}

    for spec in catalog.definitions:
        row = existing.get(spec.key)
        if row is None:
            row = PoolDefinition(key=spec.key)
            db.add(row)
            inserted += 1
        else:
            updated += 1

        row.catalog_number = spec.catalog_number
        row.display_name = spec.display_name
        row.category = spec.category
        row.scope = spec.scope
        row.mechanic = spec.mechanic
        row.evaluator_family = spec.evaluator_family
        row.evaluator_shape = spec.evaluator_shape
        row.metric_kind = spec.metric_kind
        row.direction = spec.direction
        row.metric_expression = spec.metric_expression
        row.governed_definition = spec.governed_definition
        row.threshold_condition = spec.threshold_condition
        row.predicate = spec.predicate
        row.predicate_quantifier = spec.predicate_quantifier
        row.threshold_configurable = spec.threshold_configurable
        row.threshold_default = spec.threshold_default
        row.required_stats = list(spec.required_stats) or None
        row.required_stats_resolved = spec.required_stats_resolved
        row.required_stats_unresolved_reason = spec.required_stats_unresolved_reason
        row.source_mapping_complete = spec.source_mapping_complete
        row.unmapped_required_stats = list(spec.unmapped_required_stats) or None
        row.starter_slot_rule = spec.starter_slot_rule
        row.slot_filter = list(spec.slot_filter) or None
        row.slot_exclusions = list(spec.slot_exclusions) or None
        row.self_pick_rule = spec.self_pick_rule
        row.anti_tanking_review = spec.anti_tanking_review
        row.data_dependency = spec.data_dependency
        row.dependency_state = spec.dependency_state
        row.blocked_reason = spec.blocked_reason
        row.product_complete = spec.product_complete
        row.definition_runtime_eligible = spec.definition_runtime_eligible
        row.definition_block_reason = spec.definition_block_reason
        row.regular_season_eligible = spec.regular_season_eligible
        row.postseason_eligible = spec.postseason_eligible
        row.rollover_eligible = spec.rollover_eligible
        row.tie_rule = spec.tie_rule
        row.aggregate_over_aggregate_required = spec.aggregate_over_aggregate_required
        row.zero_denominator_guard = spec.zero_denominator_guard

    db.flush()
    return {"inserted": inserted, "updated": updated,
            "total": len(catalog.definitions)}


def spec_from_row(row) -> PoolDefinitionSpec:
    """Rebuild the frozen spec from a persisted `pool_definition` row.

    The engine reads definitions through this one function whether they came
    from the artifact or the database, so a seeded row and a fixture spec are
    interchangeable and no evaluator ever holds an ORM object."""
    return PoolDefinitionSpec(
        key=row.key,
        catalog_number=row.catalog_number,
        display_name=row.display_name,
        category=row.category,
        scope=row.scope,
        mechanic=row.mechanic,
        evaluator_family=row.evaluator_family,
        evaluator_shape=row.evaluator_shape,
        metric_kind=row.metric_kind,
        direction=row.direction,
        metric_expression=row.metric_expression,
        governed_definition=row.governed_definition,
        threshold_condition=row.threshold_condition,
        predicate=row.predicate,
        predicate_quantifier=row.predicate_quantifier,
        threshold_configurable=bool(row.threshold_configurable),
        threshold_default=row.threshold_default,
        required_stats=_tuple_or_empty(row.required_stats),
        required_stats_resolved=bool(row.required_stats_resolved),
        required_stats_unresolved_reason=row.required_stats_unresolved_reason,
        source_mapping_complete=bool(row.source_mapping_complete),
        unmapped_required_stats=_tuple_or_empty(row.unmapped_required_stats),
        starter_slot_rule=row.starter_slot_rule,
        slot_filter=_tuple_or_empty(row.slot_filter),
        slot_exclusions=_tuple_or_empty(row.slot_exclusions),
        self_pick_rule=row.self_pick_rule,
        anti_tanking_review=row.anti_tanking_review,
        data_dependency=row.data_dependency,
        dependency_state=row.dependency_state,
        blocked_reason=row.blocked_reason,
        product_complete=bool(row.product_complete),
        definition_runtime_eligible=bool(row.definition_runtime_eligible),
        definition_block_reason=row.definition_block_reason,
        regular_season_eligible=bool(row.regular_season_eligible),
        postseason_eligible=row.postseason_eligible,
        rollover_eligible=bool(row.rollover_eligible),
        tie_rule=row.tie_rule,
        aggregate_over_aggregate_required=bool(row.aggregate_over_aggregate_required),
        zero_denominator_guard=bool(row.zero_denominator_guard),
    )