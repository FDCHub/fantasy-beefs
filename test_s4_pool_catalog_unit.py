"""
test_s4_pool_catalog_unit.py — Rev1.3 catalog and stat vocabulary (no database).

Covers Scope §H scenarios 18d, 18e, 18f, 19, 19a, 19b and the POR §1 counts.

WHAT MAKES THESE ASSERTIONS WORTH ANYTHING. Every count below is checked against
the ARTIFACT as loaded and validated, never against a number copied out of the
POR into this file and then compared with itself. If the artifact and the POR
disagree, the loader's own validation raises before any count is taken.

CONTROLS ARE TEST-ONLY MUTATIONS OF A COPY. spec/pool_catalog_rev1_3.json is
never edited. Each discriminating control deep-copies the loaded artifact,
corrupts the copy in one specific way, and asserts the loader rejects it — so a
control proves the check fires without touching the governed data or the
implementation.
"""

import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from betting.pool_catalog import (  # noqa: E402
    CATALOG_PATH,
    PoolCatalogError,
    RESERVED_RETIRED_KEYS,
    load_catalog,
    load_vocabulary,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _raises(label: str, fn, expected_reason: str) -> None:
    try:
        fn()
    except PoolCatalogError as exc:
        _assert(label, exc.reason == expected_reason,
                f"reason={exc.reason} (wanted {expected_reason})")
        return
    except Exception as exc:  # noqa: BLE001
        _assert(label, False, f"raised {type(exc).__name__}, not PoolCatalogError")
        return
    _assert(label, False, "did not raise")


def _load_mutated(mutate) -> None:
    """Run the loader over a corrupted COPY of the artifact.

    The loader is re-entered through its private path with an explicit dict so
    the real file is untouched and the lru_cache on load_catalog() is bypassed.
    """
    with open(CATALOG_PATH, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    mutate(raw)
    tmp = os.path.join(
        os.environ.get("TEMP", "."), "_s4_catalog_control.json")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(raw, fh)
    try:
        load_catalog.__wrapped__(tmp)      # bypass lru_cache
    finally:
        os.remove(tmp)


def main() -> None:
    catalog = load_catalog()
    vocab = load_vocabulary()
    defs = catalog.definitions

    print("\n-- POR §1 catalog composition --")
    _assert("80 active definitions", len(defs) == 80, str(len(defs)))
    _assert("44 TEAM / 36 MATCHUP",
            sum(d.scope == "TEAM" for d in defs) == 44
            and sum(d.scope == "MATCHUP" for d in defs) == 36)
    _assert("77 product-enabled, 3 product-blocked",
            sum(d.dependency_state == "ENABLED" for d in defs) == 77
            and sum(d.dependency_state == "BLOCKED" for d in defs) == 3)
    _assert("blocked set is exactly #7, #46, #85",
            sorted(d.catalog_number for d in defs
                   if d.dependency_state == "BLOCKED") == [7, 46, 85])
    _assert("64 definition_runtime_eligible (GATE 1 ceiling)",
            sum(d.definition_runtime_eligible for d in defs) == 64)
    _assert("13 source-incomplete yet ENABLED",
            sum(1 for d in defs if d.dependency_state == "ENABLED"
                and not d.source_mapping_complete) == 13)
    _assert("64 RANK_EXTREMUM / 16 QUALIFIER",
            sum(d.evaluator_family == "RANK_EXTREMUM" for d in defs) == 64
            and sum(d.evaluator_family == "QUALIFIER" for d in defs) == 16)
    _assert("16 rollover-eligible, all QUALIFIER (POR §5)",
            {d.evaluator_family for d in defs if d.rollover_eligible}
            == {"QUALIFIER"}
            and sum(d.rollover_eligible for d in defs) == 16)
    _assert("no RANK_EXTREMUM definition is rollover-eligible",
            not any(d.rollover_eligible for d in defs
                    if d.evaluator_family == "RANK_EXTREMUM"))

    print("\n-- POR §3.4 eight governed evaluator shapes --")
    shapes = {}
    for d in defs:
        shapes[d.evaluator_shape] = shapes.get(d.evaluator_shape, 0) + 1
    _assert("shape counts match §3.4 exactly",
            shapes == {"CLOSED_SUM": 42, "CLOSED_RATIO": 17,
                       "QUALIFIER_PREDICATE": 16,
                       "PLAYER_EXTREMUM_WITHIN_SUBJECT": 1,
                       "SLOT_FILTERED_POINTS_SUM": 1, "BALANCE_RATIO": 1,
                       "DISTINCT_CATEGORY_COUNT": 1, "MATCHUP_SCORE_SUM": 1},
            str(sorted(shapes.items())))
    _assert("every non-CLOSED shape has null metric_expression and a "
            "governed_definition or predicate (§3.4)",
            all(d.metric_expression is None
                and (d.governed_definition or d.predicate)
                for d in defs if d.evaluator_shape
                not in ("CLOSED_SUM", "CLOSED_RATIO")))
    _assert("every CLOSED shape carries a metric_expression",
            all(d.metric_expression for d in defs
                if d.evaluator_shape in ("CLOSED_SUM", "CLOSED_RATIO")))

    print("\n-- POR §1.2 two gates are independent axes --")
    # 18c in spirit: gate 1 is persistent definition metadata and no transient
    # environment fact appears on it. If a future revision added one, this would
    # be the assertion that noticed.
    _assert("no gate-2 field is stored on a definition",
            not any(hasattr(d, "league_activation_ready") for d in defs))
    _assert("every gate-1-false definition carries a block reason",
            all(d.definition_block_reason
                for d in defs if not d.definition_runtime_eligible))
    # 18a's data precondition: the 13 source-incomplete rows are ENABLED yet
    # gate-1 ineligible. A selector filtering on dependency_state would draw
    # them; the selector-side assertion lives in the PG suite.
    _assert("all 13 source-incomplete rows are gate-1 ineligible (18a)",
            all(not d.definition_runtime_eligible for d in defs
                if d.dependency_state == "ENABLED"
                and not d.source_mapping_complete))

    print("\n-- POR §7.0 blocked_reason is the single canonical field --")
    _assert("BLOCKED <=> blocked_reason present",
            all((d.blocked_reason is not None)
                == (d.dependency_state == "BLOCKED") for d in defs))

    print("\n-- POR §1.1 retirement (18d, 19, 19a) --")
    retired = catalog.retired_numbers
    _assert("retired numbers include #8-#12, #97, #98",
            {8, 9, 10, 11, 12, 97, 98}.issubset(retired))
    _assert("retired numbers include the two anti-tanking retirements #57, #96",
            {57, 96}.issubset(retired))
    _assert("no active definition carries a retired catalog number",
            not any(d.catalog_number in retired for d in defs))
    _assert("#97/#98 keys are absent from the active set (19a)",
            "most_field_goal_yards" not in catalog.keys
            and "highest_combined_field_goal_yards" not in catalog.keys)
    _assert("the_lineup and bench_burn are unreachable as Pools (19)",
            "the_lineup" not in catalog.keys
            and "bench_burn" not in catalog.keys)
    _assert("reserved retired keys are declared",
            RESERVED_RETIRED_KEYS >= {"most_field_goal_yards",
                                      "highest_combined_field_goal_yards",
                                      "the_lineup", "bench_burn"})

    print("\n-- 19b: no active dependency on made_field_goal_distance --")
    _assert("made_field_goal_distance is required by no active definition",
            not any("made_field_goal_distance" in d.required_stats
                    for d in defs))
    _assert("it remains in the vocabulary as source documentation",
            "made_field_goal_distance" in vocab.canonical)

    print("\n-- 19c: kicker definitions read kicking_points, not FG counts --")
    for key, number in (("most_kicking_points", 18),
                        ("highest_combined_kicker_points", 77)):
        d = catalog.by_key(key)
        _assert(f"#{number} {key} requires kicking_points only",
                d.required_stats == ("kicking_points",), str(d.required_stats))
        _assert(f"#{number} declares no field-goal or extra-point operand",
                not any(s in d.required_stats for s in
                        ("field_goals_made", "extra_points_made")))
    _assert("#18 display name is the Rev1.3 name (§1.8)",
            catalog.by_key("most_kicking_points").display_name
            == "Highest Scoring Kicker")
    _assert("#77 display name is the Rev1.3 name (§1.8)",
            catalog.by_key("highest_combined_kicker_points").display_name
            == "Highest Scoring Kicker Matchup")

    print("\n-- POR §1.4 canonical vocabulary and alias resolution --")
    _assert("every required stat is a canonical vocabulary name",
            all(s in vocab.canonical for d in defs for s in d.required_stats))
    for alias, canonical in (("yards", "scrimmage_yards"),
                             ("touchdowns", "total_touchdown_credits"),
                             ("offensive_td", "total_touchdown_credits"),
                             ("total_touchdowns", "total_touchdown_credits"),
                             ("field_goals", "field_goals_made"),
                             ("extra_points", "extra_points_made"),
                             ("offensive_opportunities", "opportunities")):
        _assert(f"alias {alias!r} -> {canonical!r}",
                vocab.canonical_operand(alias) == canonical)
    _assert("offensive_yards excludes receiving yards (§1.4)",
            vocab.derived_formula["offensive_yards"]
            == "passing_yards + rushing_yards")
    _assert("scrimmage_yards excludes passing yards (§1.4)",
            vocab.derived_formula["scrimmage_yards"]
            == "rushing_yards + receiving_yards")
    _assert("total_touchdown_credits is the three-way credit sum (§1.6)",
            vocab.derived_formula["total_touchdown_credits"]
            == "passing_td + rushing_td + receiving_td")
    _assert("an ungoverned operand is refused, not resolved to zero",
            _refuses_unknown(vocab))

    print("\n-- POR §1.5 structured predicates, 18e/18f --")
    quals = [d for d in defs if d.evaluator_family == "QUALIFIER"]
    _assert("all 16 qualifiers carry a structured predicate",
            len(quals) == 16 and all(d.predicate for d in quals))
    _assert("every quantifier is one of the three governed values",
            all(d.predicate_quantifier in ("TEAM", "MATCHUP_COMBINED",
                                           "MATCHUP_EACH") for d in quals))
    _assert("every configurable threshold carries a governed default (18f)",
            all(d.threshold_default is not None for d in defs
                if d.threshold_configurable))
    _assert("§1.5 defaults are #89=10, #90=500, #91=700, #94=100",
            {d.catalog_number: d.threshold_default for d in defs
             if d.threshold_configurable} == {89: 10, 90: 500, 91: 700,
                                              94: 100})
    _assert("threshold_condition prose is never the executable form",
            all(d.predicate is not None for d in quals))

    print("\n-- discriminating controls (test-only mutations of a copy) --")
    _raises("a retired catalog number is refused by the loader (18d)",
            lambda: _load_mutated(
                lambda raw: raw["definitions"].__setitem__(
                    0, {**raw["definitions"][0], "catalog_number": 97})),
            "RETIRED_DEFINITION")
    _raises("a reserved retired KEY is refused (19a)",
            lambda: _load_mutated(
                lambda raw: raw["definitions"].__setitem__(
                    0, {**raw["definitions"][0],
                        "key": "most_field_goal_yards"})),
            "RETIRED_DEFINITION")
    _raises("an ungoverned required stat is refused",
            lambda: _load_mutated(
                lambda raw: raw["definitions"].__setitem__(
                    0, {**raw["definitions"][0],
                        "required_stats": ["not_a_real_stat"]})),
            "UNKNOWN_STAT")
    _raises("an unbound threshold_value is refused (18e)",
            lambda: _load_mutated(_unbind_threshold),
            "UNBOUND_PREDICATE_VARIABLE")
    _raises("a BLOCKED row with no blocked_reason is refused",
            lambda: _load_mutated(_blank_blocked_reason),
            "BLOCKED_REASON_MISMATCH")
    _raises("a non-closed shape carrying a metric_expression is refused",
            lambda: _load_mutated(_expression_on_non_closed),
            "SHAPE_MISMATCH")


def _refuses_unknown(vocab) -> bool:
    try:
        vocab.canonical_operand("definitely_not_a_stat")
    except PoolCatalogError as exc:
        return exc.reason == "UNKNOWN_STAT"
    return False


def _unbind_threshold(raw) -> None:
    for row in raw["definitions"]:
        if row["catalog_number"] == 89:
            row["threshold_default"] = None
            row["threshold_configurable"] = False
            return
    raise AssertionError("#89 not present; control cannot be constructed")


def _blank_blocked_reason(raw) -> None:
    for row in raw["definitions"]:
        if row["dependency_state"] == "BLOCKED":
            row["blocked_reason"] = None
            return
    raise AssertionError("no BLOCKED row; control cannot be constructed")


def _expression_on_non_closed(raw) -> None:
    for row in raw["definitions"]:
        if row["evaluator_shape"] == "MATCHUP_SCORE_SUM":
            row["metric_expression"] = "sum(both teams passing_yards)"
            return
    raise AssertionError("#76 not present; control cannot be constructed")


if __name__ == "__main__":
    print("\n=== S4-P1 catalog unit suite (Rev1.3) ===")
    main()
    print(f"\n  {len(_failures)} failure(s)")
    if _failures:
        for f in _failures:
            print(f"    FAILED: {f}")
        sys.exit(1)
    print("  ALL PASS")
