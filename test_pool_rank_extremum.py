"""
test_pool_rank_extremum.py — step 5, the pure RANK_EXTREMUM evaluator.

No database. No Session. No network. Synthetic fixtures are authoritative, per
R2 — the evaluator never retrieves a stat, so there is nothing to integrate
against.

The canonical corpus is driven FROM spec/pool_catalog_rev1_1.json, never from a
hand-copied list: a hand-copied list drifts from the catalog silently and would
keep passing after the catalog changed.

Runs as: python test_pool_rank_extremum.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from betting.pool_evaluators import (  # noqa: E402
    MetricSpec, PoolEvaluatorError, RankExtremumResult, SubjectFacts,
    parse_metric_expression, rank_extremum,
    REASON_MALFORMED_EXPRESSION, REASON_METRIC_KIND_MISMATCH,
    REASON_MISSING_DIRECTION, REASON_MISSING_EXPRESSION,
    REASON_SCOPE_MISMATCH, REASON_UNKNOWN_OPERAND,
    REASON_UNSUPPORTED_EXPRESSION, REASON_ZERO_DENOMINATOR,
    REASON_EMPTY_SUBJECT_SET,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


_CATALOG = json.load(open(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "spec", "pool_catalog_rev1_1.json"), encoding="utf-8"))
_DEFS = _CATALOG["definitions"]


def _subject(sid, *components):
    return SubjectFacts(subject_id=sid, components=tuple(components))


def _raises(fn, reason):
    try:
        fn()
    except PoolEvaluatorError as exc:
        return exc.reason == reason, f"{exc.reason}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"wrong exception type {type(exc).__name__}: {exc}"
    return False, "did not raise"


def main() -> None:
    # ================================================================
    # CANONICAL CORPUS — every regular expression parses, driven from JSON.
    # ================================================================
    print("\n-- canonical corpus (driven from spec/pool_catalog_rev1_1.json) --")

    rank_defs = [d for d in _DEFS if d["evaluator_family"] == "RANK_EXTREMUM"]
    non_null = [d for d in rank_defs if d["metric_expression"] is not None]
    regular = [d for d in non_null if d["catalog_number"] != 76]
    null_expr = [d for d in rank_defs if d["metric_expression"] is None]

    parse_failures = []
    for d in regular:
        try:
            parse_metric_expression(d["metric_expression"])
        except PoolEvaluatorError as exc:
            parse_failures.append((d["catalog_number"], d["key"],
                                   d["metric_expression"], str(exc)))
    _assert("0: all 65 regular canonical expressions parse under STRICT whitespace",
            len(regular) == 65 and not parse_failures,
            detail=f"regular={len(regular)} failures={len(parse_failures)}"
                   + (f" {parse_failures}" if parse_failures else ""))

    # Scope validation over the whole corpus, so a MATCHUP/TEAM mismatch in the
    # catalog surfaces here rather than at settlement.
    scope_failures = []
    for d in regular:
        spec = MetricSpec(metric_expression=d["metric_expression"],
                          metric_kind=d["metric_kind"], direction=d["direction"],
                          scope=d["scope"],
                          zero_denominator_guard=d["zero_denominator_guard"],
                          aggregate_over_aggregate_required=d["aggregate_over_aggregate_required"],
                          tie_rule=d["tie_rule"])
        try:
            from betting.pool_evaluators import validate_against_spec
            validate_against_spec(parse_metric_expression(d["metric_expression"]), spec)
        except PoolEvaluatorError as exc:
            scope_failures.append((d["catalog_number"], d["key"], str(exc)))
    _assert("1: all 65 regular expressions also pass metric_kind + scope validation",
            not scope_failures,
            detail=f"failures={scope_failures}" if scope_failures else "0 failures")

    # ================================================================
    # NEGATIVE CORPUS — unsupported forms fail closed.
    # ================================================================
    print("\n-- negative corpus --")

    NEGATIVES = [
        ("multiplication",            "sum(rushing_yards * 2)"),
        ("subtraction",               "sum(rushing_yards - fumbles_lost)"),
        ("nested sum",                "sum(sum(rushing_yards))"),
        ("attribute access",          "Matchup.home_score + Matchup.away_score"),
        ("bare identifier, no sum()", "rushing_yards"),
        ("unclosed paren",            "sum(rushing_yards"),
        ("empty operand list",        "sum()"),
        ("uppercase identifier",      "sum(Rushing_Yards)"),
        ("four operands",             "sum(a + b + c + d)"),
        ("unspaced plus",             "sum(rushing_yards+receiving_yards)"),
        ("unspaced slash",            "sum(a)/sum(b)"),
        ("leading whitespace",        " sum(a)"),
        ("trailing whitespace",       "sum(a) "),
        ("both teams on ratio rhs only, malformed prefix", "sum(a) / sum(both teamsb)"),
        ("eval injection attempt",    "__import__('os').system('echo x')"),
    ]
    neg_results = []
    for name, expr in NEGATIVES:
        ok, detail = _raises(lambda e=expr: parse_metric_expression(e),
                             REASON_UNSUPPORTED_EXPRESSION)
        neg_results.append((name, ok, detail))
    _assert("2: every unsupported form is rejected with UNSUPPORTED_EXPRESSION",
            all(ok for _, ok, _ in neg_results),
            detail="; ".join(f"{n}: {d}" for n, ok, d in neg_results if not ok)
                   or f"all {len(NEGATIVES)} rejected")

    # ================================================================
    # SHAPES — each grammar form computes.
    # ================================================================
    print("\n-- grammar shapes --")

    team_simple = MetricSpec("sum(total_touchdowns)", "SIMPLE_AGG", "MAX", "TEAM")
    r = rank_extremum([_subject("A", {"total_touchdowns": 2}, {"total_touchdowns": 1}),
                       _subject("B", {"total_touchdowns": 1})], team_simple)
    _assert("3: TEAM sum(field) sums across components and ranks",
            r.winners == ("A",) and r.values == {"A": 3.0, "B": 1.0},
            detail=f"values={r.values} winners={r.winners}")

    team_multi = MetricSpec("sum(rushing_yards + receiving_yards)",
                            "SIMPLE_AGG", "MAX", "TEAM")
    r = rank_extremum([_subject("A", {"rushing_yards": 10, "receiving_yards": 5}),
                       _subject("B", {"rushing_yards": 20})], team_multi)
    _assert("4: TEAM sum(a + b) sums both operands across components",
            r.winners == ("B",) and r.values == {"A": 15.0, "B": 20.0},
            detail=f"values={r.values}")

    m_simple = MetricSpec("sum(both teams passing_yards)", "SIMPLE_AGG", "MAX", "MATCHUP")
    r = rank_extremum([_subject("M1", {"passing_yards": 300}, {"passing_yards": 250}),
                       _subject("M2", {"passing_yards": 100})], m_simple)
    _assert("5: MATCHUP 'both teams' simple form computes",
            r.winners == ("M1",) and r.values == {"M1": 550.0, "M2": 100.0},
            detail=f"values={r.values}")

    m_multi = MetricSpec("sum(both teams interceptions_thrown + fumbles_lost)",
                         "SIMPLE_AGG", "MIN", "MATCHUP")
    r = rank_extremum([_subject("M1", {"interceptions_thrown": 1, "fumbles_lost": 1}),
                       _subject("M2", {"interceptions_thrown": 0, "fumbles_lost": 0})],
                      m_multi)
    _assert("6: MATCHUP 'both teams' a + b form computes",
            r.winners == ("M2",) and r.values == {"M1": 2.0, "M2": 0.0},
            detail=f"values={r.values}")

    ratio = MetricSpec("sum(passing_yards) / sum(pass_attempts)",
                       "RATIO", "MAX", "TEAM", zero_denominator_guard=True,
                       aggregate_over_aggregate_required=True)
    r = rank_extremum([_subject("A", {"passing_yards": 300, "pass_attempts": 30}),
                       _subject("B", {"passing_yards": 200, "pass_attempts": 40})], ratio)
    _assert("7: RATIO divides once, aggregate over aggregate",
            r.winners == ("A",) and r.values == {"A": 10.0, "B": 5.0},
            detail=f"values={r.values}")

    # ================================================================
    # THE DISCRIMINATING RATIO FIXTURE — POR §3.2.
    # Built so ratio-of-aggregates and average-of-per-component-ratios pick
    # DIFFERENT winners. A fixture where they agree proves nothing.
    #   A: (90/10) and (10/90)  -> agg 100/100 = 1.00 ; avg-of-ratios = 4.5556
    #   B: (60/40) and (60/40)  -> agg 120/80  = 1.50 ; avg-of-ratios = 1.5
    # ratio-of-aggregates winner = B. average-of-ratios winner = A.
    # ================================================================
    print("\n-- aggregate-over-aggregate discriminating fixture --")

    aoa_subjects = [
        _subject("A", {"yards": 90, "touches": 10}, {"yards": 10, "touches": 90}),
        _subject("B", {"yards": 60, "touches": 40}, {"yards": 60, "touches": 40}),
    ]
    aoa_spec = MetricSpec("sum(yards) / sum(touches)", "RATIO", "MAX", "TEAM",
                          zero_denominator_guard=True,
                          aggregate_over_aggregate_required=True)
    r = rank_extremum(aoa_subjects, aoa_spec)

    def _avg_of_ratios(s):
        return sum(c["yards"] / c["touches"] for c in s.components) / len(s.components)
    avg_vals = {s.subject_id: _avg_of_ratios(s) for s in aoa_subjects}
    avg_winner = max(avg_vals, key=avg_vals.get)

    _assert("8: fixture is discriminating — the two methods pick DIFFERENT winners",
            avg_winner != "B" and avg_winner == "A",
            detail=f"average-of-ratios={{'A': {avg_vals['A']:.4f}, "
                   f"'B': {avg_vals['B']:.4f}}} -> winner {avg_winner}")
    _assert("9: evaluator returns the RATIO-OF-AGGREGATES winner, not average-of-ratios",
            r.winners == ("B",) and r.values == {"A": 1.0, "B": 1.5},
            detail=f"values={r.values} winners={r.winners} "
                   f"(average-of-ratios would have chosen {avg_winner!r})")

    # ================================================================
    # DIRECTION, TIES, DEGENERATE INPUTS.
    # ================================================================
    print("\n-- direction, ties, degenerate inputs --")

    subs = [_subject("A", {"x": 5}), _subject("B", {"x": 9}), _subject("C", {"x": 1})]
    r_max = rank_extremum(subs, MetricSpec("sum(x)", "SIMPLE_AGG", "MAX", "TEAM"))
    _assert("10: direction MAX picks the maximum",
            r_max.winners == ("B",) and r_max.extremum == 9.0,
            detail=f"winners={r_max.winners} extremum={r_max.extremum}")
    r_min = rank_extremum(subs, MetricSpec("sum(x)", "SIMPLE_AGG", "MIN", "TEAM"))
    _assert("11: direction MIN picks the minimum",
            r_min.winners == ("C",) and r_min.extremum == 1.0,
            detail=f"winners={r_min.winners} extremum={r_min.extremum}")

    tied = [_subject("A", {"x": 7}), _subject("B", {"x": 7}), _subject("C", {"x": 3})]
    r = rank_extremum(tied, MetricSpec("sum(x)", "SIMPLE_AGG", "MAX", "TEAM"))
    _assert("12: a tie returns ALL subjects at the extremum, not one",
            set(r.winners) == {"A", "B"} and len(r.winners) == 2,
            detail=f"winners={r.winners}")

    r = rank_extremum([_subject("solo", {"x": 4})],
                      MetricSpec("sum(x)", "SIMPLE_AGG", "MAX", "TEAM"))
    _assert("13: a single subject is its own extremum",
            r.winners == ("solo",) and r.extremum == 4.0,
            detail=f"winners={r.winners}")

    # RULED: an empty subject set RAISES. A RANK_EXTREMUM with any subject has
    # an extremum, so zero subjects is an upstream input failure, not a
    # no-winner outcome. Asserting the SPECIFIC reason code, not merely that
    # something was raised — "some error occurred" would also pass if the call
    # blew up for an unrelated reason.
    ok, detail = _raises(
        lambda: rank_extremum([], MetricSpec("sum(x)", "SIMPLE_AGG", "MAX", "TEAM")),
        REASON_EMPTY_SUBJECT_SET)
    _assert("14: an empty subject set raises EMPTY_SUBJECT_SET specifically",
            ok, detail=detail)

    # PROOF THAT ASSERTION 14 DISCRIMINATES. A test-only stub reproducing the
    # OLD return-empty behavior is run through the IDENTICAL check. If the check
    # accepted the old behavior it would be worthless. No source is mutated —
    # the stub lives here and production code is untouched.
    def _old_return_empty_stub(subjects, spec):
        if not subjects:
            return RankExtremumResult(winners=(), values={}, extremum=None)
        return rank_extremum(subjects, spec)

    stub_ok, stub_detail = _raises(
        lambda: _old_return_empty_stub([], MetricSpec("sum(x)", "SIMPLE_AGG",
                                                      "MAX", "TEAM")),
        REASON_EMPTY_SUBJECT_SET)
    _assert("15: assertion 14 FAILS against the old return-empty behavior "
            "(test-only stub, source untouched) — the check discriminates",
            stub_ok is False,
            detail=f"old behavior under the same check -> {stub_detail}")

    # ================================================================
    # FAIL-CLOSED PATHS.
    # ================================================================
    print("\n-- fail-closed paths --")

    ok, detail = _raises(
        lambda: rank_extremum(
            [_subject("A", {"completions": 0, "pass_attempts": 0})],
            MetricSpec("sum(completions) / sum(pass_attempts)", "RATIO", "MAX",
                       "TEAM", zero_denominator_guard=True)),
        REASON_ZERO_DENOMINATOR)
    _assert("16: guarded zero denominator fails closed — never divides, never awards",
            ok, detail=detail)

    ok, detail = _raises(
        lambda: rank_extremum(
            [_subject("A", {"a": 1, "b": 0})],
            MetricSpec("sum(a) / sum(b)", "RATIO", "MAX", "TEAM",
                       zero_denominator_guard=False)),
        REASON_ZERO_DENOMINATOR)
    _assert("17: UNGUARDED zero denominator also refuses (guard read as a flag, "
            "never inferred from metric_kind)", ok, detail=detail)

    # Null expression, driven from the seven ACTUAL COMPOSITE definitions.
    null_reasons = []
    for d in null_expr:
        ok, detail = _raises(
            lambda dd=d: rank_extremum(
                [_subject("A", {"x": 1})],
                MetricSpec(dd["metric_expression"], dd["metric_kind"],
                           dd["direction"], dd["scope"])),
            REASON_MISSING_EXPRESSION)
        null_reasons.append((d["catalog_number"], ok, detail))
    _assert("18: all seven null-formula COMPOSITE definitions raise MISSING_EXPRESSION",
            len(null_expr) == 7 and all(ok for _, ok, _ in null_reasons),
            detail=f"catalog_numbers={[n for n, _, _ in null_reasons]} "
                   f"failures={[(n, d) for n, ok, d in null_reasons if not ok]}")

    # #76 — rejected SYNTACTICALLY, and its metric_kind is SIMPLE_AGG.
    d76 = next(d for d in _DEFS if d["catalog_number"] == 76)
    ok, detail = _raises(
        lambda: rank_extremum(
            [_subject("M", {"home_score": 1})],
            MetricSpec(d76["metric_expression"], d76["metric_kind"],
                       d76["direction"], d76["scope"])),
        REASON_UNSUPPORTED_EXPRESSION)
    _assert("19: #76 is rejected SYNTACTICALLY even though metric_kind is SIMPLE_AGG",
            ok and d76["metric_kind"] == "SIMPLE_AGG",
            detail=f"metric_kind={d76['metric_kind']} expr={d76['metric_expression']!r} "
                   f"-> {detail}")

    # A metric_kind-keyed rejection would MISS #76. Prove the trap is real.
    _assert("20: a metric_kind == COMPOSITE rejection would MISS #76 entirely",
            d76["metric_kind"] != "COMPOSITE",
            detail=f"#76 metric_kind={d76['metric_kind']!r} — keying rejection on "
                   f"COMPOSITE catches the 7 null rows and not this one")

    ok, detail = _raises(
        lambda: parse_metric_expression("sum(a"), REASON_UNSUPPORTED_EXPRESSION)
    _assert("21: malformed expression is rejected", ok, detail=detail)

    ok, detail = _raises(
        lambda: rank_extremum([_subject("A", {"x": 1})],
                              MetricSpec("sum(both teams x)", "SIMPLE_AGG",
                                         "MAX", "TEAM")),
        REASON_SCOPE_MISMATCH)
    _assert("22: TEAM definition carrying 'both teams' fails closed", ok, detail=detail)

    ok, detail = _raises(
        lambda: rank_extremum([_subject("M", {"x": 1})],
                              MetricSpec("sum(x)", "SIMPLE_AGG", "MAX", "MATCHUP")),
        REASON_SCOPE_MISMATCH)
    _assert("23: MATCHUP definition without 'both teams' fails closed "
            "(enforced: 28 of 29 canonical MATCHUP rows carry it; #76 is "
            "rejected syntactically first)", ok, detail=detail)

    ok, detail = _raises(
        lambda: rank_extremum([_subject("A", {"x": 1})],
                              MetricSpec("sum(x) / sum(y)", "SIMPLE_AGG",
                                         "MAX", "TEAM")),
        REASON_METRIC_KIND_MISMATCH)
    _assert("24: SIMPLE_AGG carrying a ratio fails closed", ok, detail=detail)

    ok, detail = _raises(
        lambda: rank_extremum([_subject("A", {"x": 1})],
                              MetricSpec("sum(x)", "RATIO", "MAX", "TEAM")),
        REASON_METRIC_KIND_MISMATCH)
    _assert("25: RATIO carrying a single aggregate fails closed", ok, detail=detail)

    ok, detail = _raises(
        lambda: rank_extremum([_subject("A", {"x": 1})],
                              MetricSpec("sum(typo_stat)", "SIMPLE_AGG",
                                         "MAX", "TEAM")),
        REASON_UNKNOWN_OPERAND)
    _assert("26: an operand supplied by no component fails closed "
            "(catches a typo'd stat name rather than silently scoring 0)",
            ok, detail=detail)

    ok, detail = _raises(
        lambda: rank_extremum([_subject("A", {"x": 1})],
                              MetricSpec("sum(x)", "SIMPLE_AGG", None, "TEAM")),
        REASON_MISSING_DIRECTION)
    _assert("27: a missing direction fails closed", ok, detail=detail)

    ok, detail = _raises(
        lambda: rank_extremum([_subject("A", {"x": 1})],
                              MetricSpec("sum(x)", "COMPOSITE", "MAX", "TEAM")),
        REASON_UNSUPPORTED_EXPRESSION)
    _assert("28: COMPOSITE metric_kind is not executable under the grammar",
            ok, detail=detail)

    # ================================================================
    # PURITY — no branch on definition identity anywhere in the module.
    # ================================================================
    print("\n-- purity --")

    # Scan CODE ONLY. A raw substring scan over the file matches the module's
    # own docstring, which states these prohibitions in prose — that is a false
    # positive, not a violation. Comments and string literals are stripped via
    # tokenize so only executable tokens are examined.
    import io
    import tokenize

    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "betting", "pool_evaluators.py")
    with open(src_path, encoding="utf-8") as fh:
        raw = fh.read()
    code_tokens = []
    for tok in tokenize.generate_tokens(io.StringIO(raw).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        code_tokens.append(tok.string)
    code = " ".join(code_tokens)

    banned = ["definition_key", "display_name", "eval", "exec", "ast",
              "Session", "query", "requests", "urllib", "sqlalchemy", "random"]
    hits = [b for b in banned if b in code.split()]
    _assert("29: evaluator CODE contains no definition-identity branch, no eval/exec, "
            "no Session/ORM, no network, no randomness (comments and docstrings "
            "stripped via tokenize — a raw file scan matches the docstring's own "
            "prohibition text and is a false positive)",
            not hits, detail=f"banned identifiers in code: {hits}" if hits
                             else f"none present across {len(code_tokens)} code tokens")


if __name__ == "__main__":
    main()
    print()
    if _failures:
        print(f"RESULT: {len(_failures)} assertion(s) FAILED")
        for label in _failures:
            print(f"  - {label}")
        sys.exit(1)
    print("RESULT: all RANK_EXTREMUM assertions PASSED")