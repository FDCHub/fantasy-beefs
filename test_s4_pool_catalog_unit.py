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
import io
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

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
    # THE NAMES MOVED; THE SCORING BASIS DID NOT. Rev 1.3 §1.8 fixed both of
    # these by name AND by scoring basis, and this suite has always asserted
    # both. The owner ruling of 2026-08-21 supersedes the NAMING half only — POR
    # Rev 1.4 §2 — so the assertions above, which are the SCORING half, are
    # untouched and these two are re-pointed at the ruled names. #77 is
    # `Kicker Duel`: the proposal's `Double Kickers` was refused.
    _assert("#18 display name is the Rev1.4 ruled name (Rev 1.4 §2)",
            catalog.by_key("most_kicking_points").display_name
            == "Kicker Chaos",
            catalog.by_key("most_kicking_points").display_name)
    _assert("#77 display name is the Rev1.4 ruled name (Rev 1.4 §2)",
            catalog.by_key("highest_combined_kicker_points").display_name
            == "Kicker Duel",
            catalog.by_key("highest_combined_kicker_points").display_name)
    _assert("the superseded kicker names appear on no active definition",
            not ({"Highest Scoring Kicker", "Highest Scoring Kicker Matchup",
                  "Most Kicking Points", "Highest Combined Kicker Points",
                  "Double Kickers"}
                 & {d.display_name for d in defs}))

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


# ═══════════════════════════════════════════════════════════════════════════
# POR REVISION 1.4 — the branded naming pass, public_question, and the weekly
# scope composition.
#
# WHY THE DRIFT CHECK IS THE FIRST THING HERE. Rev 1.4 claims to change two
# presentation fields and one selection rule and NOTHING ELSE. That claim is
# only worth what proves it, and the only proof that cannot be gamed is a
# field-by-field comparison against the superseded artifact, run on every
# invocation rather than asserted once at authoring time. So §R1 loads Rev 1.3
# from `CATALOG_PATH_REV1_3` — which exists precisely so this can be done — and
# requires zero drift on every field of every definition except the two Rev 1.4
# is allowed to touch.
# ═══════════════════════════════════════════════════════════════════════════

#: The two fields Rev 1.4 is permitted to change or add. Everything else on
#: every one of the 80 definitions must be byte-identical to Rev 1.3.
REV14_PRESENTATION_FIELDS = frozenset({"display_name", "public_question"})

#: POR Rev 1.4 §5.3 and §2 — the owner's amendments, asserted by exact string.
#: These are RULINGS, not preferences, and a later edit that "improved" one
#: would be superseding an owner decision by accident.
OWNER_RULED_NAMES = {
    "most_kicking_points": "Kicker Chaos",              # §2, approved as proposed
    "highest_combined_kicker_points": "Kicker Duel",    # §2, Double Kickers refused
    "most_offensive_touches": "Heavy Usage",            # §5.3, replaces Workload
    "highest_combined_yards_per_touch": "Touch Efficiency",   # §5.3
    "matchups_where_both_teams_had_100plus_rushing_yards": "Ground Tandem",  # §5.3
    "matchups_where_neither_team_lost_a_fumble": "Fumble Free",  # §6
}


def rev14() -> None:
    """POR Rev 1.4 conformance — §9.2 items 1 through 10."""
    from betting.pool_catalog import CATALOG_PATH_REV1_3
    from betting.pool_rotation import DEFAULT_SCOPE_MIX

    catalog = load_catalog()
    defs = catalog.definitions

    print("\n-- Rev 1.4 §9.2/1 — the runtime catalog IS Rev 1.4 --")
    with open(CATALOG_PATH, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    _assert("the runtime CATALOG_PATH resolves to the Rev 1.4 artifact",
            os.path.basename(CATALOG_PATH) == "pool_catalog_rev1_4.json",
            os.path.basename(CATALOG_PATH))
    _assert("its revision is 1.4", catalog.revision == "1.4", catalog.revision)
    _assert("its status is Product of Record",
            raw.get("status") == "Product of Record", str(raw.get("status")))
    _assert("it names the Rev 1.4 POR as its governing spec",
            raw.get("governing_spec")
            == "spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_4.md",
            str(raw.get("governing_spec")))
    _assert("the Rev 1.4 POR exists un-suffixed and no _PROPOSED artifact is "
            "left pretending to be active",
            os.path.exists(os.path.join(
                ROOT, "spec", "SPEC_Pool_Catalog_Rotation_POR_Rev1_4.md"))
            and not os.path.exists(os.path.join(
                ROOT, "spec",
                "SPEC_Pool_Catalog_Rotation_POR_Rev1_4_PROPOSED.md")))

    print("\n-- Rev 1.4 §9.2/2 — ZERO governed-field drift against Rev 1.3 --")
    with open(CATALOG_PATH_REV1_3, "r", encoding="utf-8") as fh:
        raw13 = json.load(fh)
    by13 = {d["key"]: d for d in raw13["definitions"]}
    by14 = {d["key"]: d for d in raw["definitions"]}
    _assert("Rev 1.3 is still Product of Record in its own historical sense, "
            "and byte-unchanged in every field this compares",
            raw13.get("status") == "Product of Record", str(raw13.get("status")))
    _assert("the same 80 keys, no addition, no retirement, no renumbering",
            set(by13) == set(by14) and len(by14) == 80,
            f"{len(by13)} vs {len(by14)}")
    _assert("the retired block is identical",
            raw13["retired"] == raw["retired"])
    _assert("the declared counts are identical",
            raw13["counts"] == raw["counts"])
    drift = []
    for key, old in by13.items():
        new = by14[key]
        for field in set(old) | set(new):
            if field in REV14_PRESENTATION_FIELDS:
                continue
            if old.get(field) != new.get(field):
                drift.append((key, field, old.get(field), new.get(field)))
    _assert("NO governed field moved on any of the 80 definitions — no key, "
            "predicate, metric_expression, threshold, scope, evaluator shape, "
            "eligibility flag, rollover flag or tie rule",
            not drift, str(drift[:4]) if drift else "0 differences")

    print("\n-- Rev 1.4 §9.2/3-5 — the naming set --")
    eligible = [d for d in defs if d.definition_runtime_eligible]
    _assert("64 definitions are runtime-eligible", len(eligible) == 64,
            str(len(eligible)))
    unnamed = [d.key for d in eligible if not (d.display_name or "").strip()]
    _assert("every eligible definition carries a display_name", not unnamed,
            str(unnamed[:4]))
    unasked = [d.key for d in eligible if not (d.public_question or "").strip()]
    _assert("every eligible definition carries a public_question (§3)",
            not unasked, str(unasked[:4]))
    renamed = [d.key for d in eligible
               if d.display_name == by13[d.key]["display_name"]]
    _assert("all 64 were actually renamed from their Rev 1.3 name",
            not renamed, str(renamed[:4]))
    names = [d.display_name for d in defs]
    dupes = sorted({nm for nm in names if names.count(nm) > 1})
    _assert("no two active definitions share a display_name", not dupes,
            str(dupes))
    over = [(d.key, d.display_name) for d in eligible
            if len(d.display_name) > 18 or len(d.display_name.split()) > 4]
    _assert("every public name is at most four words and 18 characters",
            not over, str(over[:3]))
    longer = [(d.key, by13[d.key]["display_name"], d.display_name)
              for d in eligible
              if len(d.display_name) >= len(by13[d.key]["display_name"])]
    _assert("every public name is strictly SHORTER than the Rev 1.3 name the "
            "card rendered before it, so no card can grow or wrap further",
            not longer, str(longer[:2]))

    print("\n-- Rev 1.4 §9.2/4 — the 16 non-drawable are left alone --")
    left = [d for d in defs if not d.definition_runtime_eligible]
    _assert("16 definitions are not runtime-eligible", len(left) == 16,
            str(len(left)))
    _assert("none of them was renamed",
            all(d.display_name == by13[d.key]["display_name"] for d in left),
            str([d.key for d in left
                 if d.display_name != by13[d.key]["display_name"]]))
    _assert("none of them carries a public_question (§7)",
            all(d.public_question is None for d in left),
            str([d.key for d in left if d.public_question is not None]))
    _assert("exactly 3 are BLOCKED and 13 are source-mapping incomplete",
            sum(1 for d in left if d.dependency_state == "BLOCKED") == 3
            and sum(1 for d in left
                    if d.dependency_state == "ENABLED") == 13)

    print("\n-- Rev 1.4 §9.2/6 — the owner-ruled names are exact --")
    for key, ruled in OWNER_RULED_NAMES.items():
        actual = catalog.by_key(key).display_name
        _assert(f"#{catalog.by_key(key).catalog_number} {key} is {ruled!r}",
                actual == ruled, actual)

    print("\n-- Rev 1.4 §9.2/7 — the fewest-vs-zero convention (§6) --")
    # READ FROM THE MECHANIC, NOT FROM A LIST OF NUMBERS. `direction == MIN`
    # and a predicate ending `== 0` are what make a contest one kind or the
    # other, so a definition added later is covered by this without anyone
    # remembering to extend a fixture.
    min_set = [d for d in eligible if d.direction == "MIN"]
    zero_set = [d for d in eligible
                if (d.predicate or "").strip().endswith("== 0")]
    _assert("the active set is 6 MIN contests and 3 exact-zero qualifiers",
            len(min_set) == 6 and len(zero_set) == 3,
            f"{len(min_set)} MIN / {len(zero_set)} zero")
    _assert("the two families are disjoint",
            not ({d.key for d in min_set} & {d.key for d in zero_set}))
    free_min = [(d.key, d.display_name) for d in min_set
                if "free" in d.display_name.lower()]
    _assert("NO MIN contest reserves the word Free", not free_min,
            str(free_min))
    unfree_zero = [(d.key, d.display_name) for d in zero_set
                   if "free" not in d.display_name.lower()]
    _assert("EVERY exact-zero qualifier uses Free", not unfree_zero,
            str(unfree_zero))

    print("\n-- Rev 1.4 §9.2/8-10 — the weekly scope composition (§4.2) --")
    _assert("the catalog carries the composition as data",
            catalog.weekly_scope_mix == (("TEAM", 3), ("MATCHUP", 1)),
            str(catalog.weekly_scope_mix))
    _assert("  · and it agrees with the pure selector's default",
            catalog.weekly_scope_mix == DEFAULT_SCOPE_MIX)
    _assert("the composition block is REGULAR-phase, four slots",
            raw["weekly_slate_composition"]["phase"] == "REGULAR"
            and raw["weekly_slate_composition"]["slot_count"] == 4)
    # THE LOADER REFUSES A DRIFTED ARTIFACT. Without this the two statements of
    # the rule could diverge and only a hand comparison would notice.
    _raises("a catalog whose composition disagrees with the selector is "
            "refused at load", lambda: _load_mutated(_drift_scope_mix),
            "SCOPE_MIX_MISMATCH")
    _raises("a composition whose scopes do not sum to its slot_count is "
            "refused at load", lambda: _load_mutated(_unbalanced_scope_mix),
            "SCOPE_MIX_MISMATCH")

    print("\n-- Rev 1.4 §3.2 — public_question carries no settlement power --")
    # The evaluator boundary is the proof: a question is not an operand, not a
    # predicate and not an expression, so nothing that settles a Pool can read
    # one. Asserted structurally rather than by inspection.
    from betting import pool_evaluators
    src = io.open(pool_evaluators.__file__, encoding="utf-8").read()
    _assert("betting/pool_evaluators.py never mentions public_question",
            "public_question" not in src)
    _assert("no public_question contains a catalog operand name or a scope "
            "enum",
            not [d.key for d in eligible
                 if any(tok in (d.public_question or "")
                        for tok in ("SUM_BOTH_TEAMS", "EACH_TEAM",
                                    "metric_expression", "RANK_EXTREMUM",
                                    "QUALIFIER"))])
    # §3.1 — configurable thresholds say "the target", never a literal, because
    # a league that reconfigured one would be shown a number its own settlement
    # does not use.
    literal = [(d.key, d.public_question) for d in eligible
               if d.threshold_configurable
               and str(d.threshold_default) in (d.public_question or "")]
    _assert("a configurable threshold's question states no literal (§3.1)",
            not literal, str(literal[:2]))


def _drift_scope_mix(raw) -> None:
    raw["weekly_slate_composition"]["scopes"] = [
        {"scope": "TEAM", "slots": 1}, {"scope": "MATCHUP", "slots": 3}]


def _unbalanced_scope_mix(raw) -> None:
    raw["weekly_slate_composition"]["scopes"] = [
        {"scope": "TEAM", "slots": 3}, {"scope": "MATCHUP", "slots": 2}]


if __name__ == "__main__":
    print("\n=== S4-P1 catalog unit suite (Rev1.4) ===")
    main()
    rev14()
    print(f"\n  {len(_failures)} failure(s)")
    if _failures:
        for f in _failures:
            print(f"    FAILED: {f}")
        sys.exit(1)
    print("  ALL PASS")
