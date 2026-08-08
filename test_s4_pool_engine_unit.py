"""
test_s4_pool_engine_unit.py — common evaluator, census gate and §6.3 payout.

PURE. No database, no session, no clock. Every fixture is synthetic, which is
exactly what makes it authoritative: the evaluator layer is provider-neutral by
construction (Scope §C7), so a fixture built at the boundary exercises the same
code production data would.

Covers Scope §H scenarios 12a, 12b, 12c, 12d, 14, 15, 16, 17, 19c, 23, 24, 25,
26, 27 and 28.

THE DISCRIMINATING FIXTURES ARE THE POINT. Four assertions below are constructed
so that a plausible WRONG implementation passes everything else and fails only
there:

  15   aggregate-over-aggregate vs mean-of-per-player-ratios — the two pick
       DIFFERENT winners on this fixture. A fixture where they agree proves
       nothing, so this one is built so they disagree.
  12b  insertion order and display-name order both disagree with canonical GM
       ID order. An implementation ordering by query result passes 12a and 12c.
  19c  3xFG + 1xXP and the league's bracket scoring pick DIFFERENT kickers.
  28   the census is read from the league structure, not the stat feed. An
       implementation deriving `considered` from the supplied subjects reports
       a complete field here and settles a broken week.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from betting.pool_catalog import load_catalog  # noqa: E402
from betting.pool_census import (  # noqa: E402
    CLASSIFICATION_CLAIMS_PRESENT,
    CLASSIFICATION_INCOMPLETE_FIELD,
    CLASSIFICATION_INVARIANT_VIOLATION,
    CLASSIFICATION_NO_EVALUABLE_SUBJECTS,
    CLASSIFICATION_NO_SUBJECTS,
    CLASSIFICATION_ZERO_ELIGIBLE_CLAIMS,
    classify_pool,
    require_settleable,
)
from betting.pool_errors import (  # noqa: E402
    IncompleteFieldError,
    NoEvaluableSubjectsError,
    NoSubjectsError,
    PoolDataConditionError,
    PoolInvariantViolationError,
    PoolSettlementRefusedError,
)
from betting.pool_evaluators import PoolEvaluatorError  # noqa: E402
from betting.pool_settlement import allocate_even_split  # noqa: E402
from betting.pool_shapes import UNEVALUABLE, subject_value  # noqa: E402
from betting.pool_subjects import (  # noqa: E402
    StatComponent,
    Subject,
    TeamFrame,
    WeeklyStructure,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


CATALOG = load_catalog()


def frame(team_id, rows, covered, score=None):
    """rows: list of (values dict, slot, position)."""
    return TeamFrame(
        team_id=team_id,
        components=tuple(StatComponent(values=v, slot=s, position=p)
                         for v, s, p in rows),
        covered_stats=frozenset(covered),
        score=score,
    )


def team_subject(subject_id, rows, covered):
    return Subject(subject_id=subject_id, subject_type="TEAM",
                   frames=(frame(subject_id, rows, covered),))


def matchup_subject(subject_id, home, away, covered, scores=(None, None)):
    return Subject(subject_id=subject_id, subject_type="MATCHUP",
                   frames=(frame(subject_id * 100 + 1, home, covered,
                                 scores[0]),
                           frame(subject_id * 100 + 2, away, covered,
                                 scores[1])))


def structure(scope, ids):
    return WeeklyStructure(scope=scope, considered_subject_ids=tuple(ids))


# ── shapes ────────────────────────────────────────────────────────────────────

def test_closed_sum_alias_resolution():
    print("\n-- CLOSED_SUM with alias resolution (POR §1.4, §C7.2) --")
    spec = CATALOG.by_key("most_total_touchdowns")   # sum(total_touchdowns)
    cov = {"total_touchdown_credits"}
    subs = [team_subject(1, [({"total_touchdown_credits": 3.0}, "QB", "QB")], cov),
            team_subject(2, [({"total_touchdown_credits": 5.0}, "QB", "QB")], cov),
            team_subject(3, [({"total_touchdown_credits": 5.0}, "QB", "QB")], cov)]
    out = classify_pool(spec, structure("TEAM", (1, 2, 3)), subs)
    _assert("expression alias total_touchdowns resolves to the canonical stat",
            out.values[2] == 5.0 and out.classification
            == CLASSIFICATION_CLAIMS_PRESENT)
    _assert("all subjects tied at the extreme are returned (POR §3)",
            out.winning_subject_ids == (2, 3), str(out.winning_subject_ids))


def test_rank_extremum_min():
    print("\n-- 14: RANK_EXTREMUM MIN --")
    spec = CATALOG.by_key("fewest_interceptions_thrown")
    cov = {"interceptions_thrown"}
    subs = [team_subject(i, [({"interceptions_thrown": v}, "QB", "QB")], cov)
            for i, v in ((1, 3.0), (2, 0.0), (3, 2.0))]
    out = classify_pool(spec, structure("TEAM", (1, 2, 3)), subs)
    _assert("MIN direction picks the minimum, not the maximum",
            out.winning_subject_ids == (2,), str(out.winning_subject_ids))
    _assert("an explicit zero is a real value, not missing data",
            out.values[2] == 0.0 and out.census.subjects_evaluated == 3)


def test_aggregate_over_aggregate_discriminating():
    print("\n-- 15: aggregate-over-aggregate vs mean of per-player ratios --")
    spec = CATALOG.by_key("highest_yards_per_touch")   # sum(yards)/sum(touches)
    cov = {"scrimmage_yards", "touches"}
    # Subject 1: 100/1 and 10/9  -> Σ110 / Σ10  = 11.0   mean-of-ratios 50.56
    # Subject 2:  60/5 and 60/5  -> Σ120 / Σ10  = 12.0   mean-of-ratios 12.00
    a = team_subject(1, [({"scrimmage_yards": 100.0, "touches": 1.0}, "RB", "RB"),
                         ({"scrimmage_yards": 10.0, "touches": 9.0}, "WR", "WR")],
                     cov)
    b = team_subject(2, [({"scrimmage_yards": 60.0, "touches": 5.0}, "RB", "RB"),
                         ({"scrimmage_yards": 60.0, "touches": 5.0}, "WR", "WR")],
                     cov)
    out = classify_pool(spec, structure("TEAM", (1, 2)), [a, b])
    mean_of_ratios = {1: (100 / 1 + 10 / 9) / 2, 2: (60 / 5 + 60 / 5) / 2}
    _assert("the two methods disagree on this fixture (control is valid)",
            max(mean_of_ratios, key=mean_of_ratios.get) != 2)
    _assert("aggregate-over-aggregate picks subject 2",
            out.winning_subject_ids == (2,), str(out.winning_subject_ids))
    _assert("computed values are Σnum/Σden",
            out.values[1] == 11.0 and out.values[2] == 12.0,
            str(out.values))


def test_zero_denominator_fails_closed():
    print("\n-- 16: zero-denominator guard fails closed (POR §3.3) --")
    spec = CATALOG.by_key("best_roster_completion_percentage")
    cov = set(spec.required_stats)
    good = team_subject(1, [({s: 5.0 for s in cov}, "QB", "QB")], cov)
    zero_den = team_subject(2, [({s: 0.0 for s in cov}, "QB", "QB")], cov)
    value = subject_value(spec, zero_den)
    _assert("a present denominator of zero makes the SUBJECT unevaluable",
            value is UNEVALUABLE)
    out = classify_pool(spec, structure("TEAM", (1, 2)), [good, zero_den])
    _assert("the week then fails closed as INCOMPLETE_FIELD",
            out.classification == CLASSIFICATION_INCOMPLETE_FIELD)
    _assert("never divides, never coerces to zero, never awards",
            out.winning_subject_ids == () and 2 not in out.values)


def test_bench_and_slot_rules():
    print("\n-- bench/IR exclusion and slot rules (POR §1.3) --")
    spec = CATALOG.by_key("most_complete_offensive_production")   # #42
    cov = {"player_fantasy_points"}
    starters_only = team_subject(1, [
        ({"player_fantasy_points": 20.0}, "QB", "QB"),
        ({"player_fantasy_points": 99.0}, "BN", "RB"),    # bench, must not count
        ({"player_fantasy_points": 50.0}, "IR", "WR"),    # IR, must not count
        ({"player_fantasy_points": 10.0}, "DEF", "DEF"),  # slot_exclusions
    ], cov)
    _assert("bench, IR and excluded slots contribute nothing",
            subject_value(spec, starters_only) == 20.0,
            str(subject_value(spec, starters_only)))
    flex = team_subject(2, [
        ({"player_fantasy_points": 7.0}, "FLEX", "RB"),
    ], cov)
    _assert("a FLEX slot counts by the actual occupying player",
            subject_value(spec, flex) == 7.0)


def test_player_extremum_within_subject():
    print("\n-- #17 PLAYER_EXTREMUM_WITHIN_SUBJECT --")
    spec = CATALOG.by_key("most_dual_threat_yards")
    cov = {"passing_yards", "rushing_yards"}
    two_qbs = team_subject(1, [
        ({"passing_yards": 100.0, "rushing_yards": 50.0}, "QB", "QB"),
        ({"passing_yards": 140.0, "rushing_yards": 10.0}, "SUPERFLEX", "QB"),
    ], cov)
    _assert("the metric is the individual maximum, never a sum",
            subject_value(spec, two_qbs) == 150.0,
            str(subject_value(spec, two_qbs)))
    no_qb = team_subject(2, [({"passing_yards": 0.0, "rushing_yards": 0.0},
                              "RB", "RB")], cov)
    _assert("no qualifying starter is UNEVALUABLE, never zero (§C8)",
            subject_value(spec, no_qb) is UNEVALUABLE)


def test_balance_ratio():
    print("\n-- #43 BALANCE_RATIO (POR §3.4, ruled in full) --")
    spec = CATALOG.by_key("best_run_pass_balance")
    cov = {"player_fantasy_points"}
    even = team_subject(1, [({"player_fantasy_points": 10.0}, "RB", "RB"),
                            ({"player_fantasy_points": 10.0}, "WR", "WR")], cov)
    skewed = team_subject(2, [({"player_fantasy_points": 20.0}, "RB", "RB"),
                              ({"player_fantasy_points": 5.0}, "TE", "TE")], cov)
    clamped = team_subject(3, [({"player_fantasy_points": -4.0}, "RB", "RB"),
                               ({"player_fantasy_points": 0.0}, "WR", "WR")], cov)
    _assert("perfect balance scores 1.0", subject_value(spec, even) == 1.0)
    _assert("min/max ratio, not a difference",
            subject_value(spec, skewed) == 0.25)
    _assert("negative components clamp and both-zero is a DEFINED 0, "
            "not unevaluable", subject_value(spec, clamped) == 0.0)


def test_matchup_score_sum_and_single_subject():
    print("\n-- 26: #76 MATCHUP_SCORE_SUM, a matchup is ONE subject --")
    spec = CATALOG.by_key("shootout_of_the_week")
    cov = {"matchup_home_score", "matchup_away_score"}
    hi = matchup_subject(1, [], [], cov, scores=(100.0, 90.0))
    lo = matchup_subject(2, [], [], cov, scores=(80.0, 80.0))
    out = classify_pool(spec, structure("MATCHUP", (1, 2)), [hi, lo])
    _assert("two matchups are two subjects, not four teams",
            out.census.subjects_considered == 2
            and out.census.subjects_evaluated == 2)
    _assert("the metric sums both participants' scores",
            out.values[1] == 190.0 and out.values[2] == 160.0)
    half = matchup_subject(3, [], [], cov, scores=(70.0, None))
    out2 = classify_pool(spec, structure("MATCHUP", (1, 3)), [hi, half])
    _assert("one unevaluable participant makes the whole matchup unevaluable",
            out2.classification == CLASSIFICATION_INCOMPLETE_FIELD
            and out2.unevaluable_subject_ids == (3,))


def test_matchup_coverage_is_intersection():
    print("\n-- a matchup is evaluable only when BOTH participants are --")
    spec = CATALOG.by_key("highest_combined_rushing_yards")
    subject = Subject(subject_id=1, subject_type="MATCHUP", frames=(
        frame(11, [({"rushing_yards": 100.0}, "RB", "RB")], {"rushing_yards"}),
        frame(12, [({"rushing_yards": 80.0}, "RB", "RB")], set()),
    ))
    _assert("coverage is the INTERSECTION across frames, never the union",
            subject_value(spec, subject) is UNEVALUABLE)


def test_qualifier_quantifiers():
    print("\n-- QUALIFIER quantifiers: MATCHUP_EACH is not MATCHUP_COMBINED --")
    cov = {"rushing_yards"}
    balanced = matchup_subject(1, [({"rushing_yards": 100.0}, "RB", "RB")],
                               [({"rushing_yards": 100.0}, "RB", "RB")], cov)
    lopsided = matchup_subject(2, [({"rushing_yards": 250.0}, "RB", "RB")],
                               [({"rushing_yards": 30.0}, "RB", "RB")], cov)
    each = CATALOG.by_key("matchups_where_both_teams_had_100plus_rushing_yards")
    out = classify_pool(each, structure("MATCHUP", (1, 2)),
                        [balanced, lopsided])
    _assert("EACH_TEAM(>=100) accepts 100/100 and REJECTS 250/30",
            out.winning_subject_ids == (1,), str(out.winning_subject_ids))
    combined = CATALOG.by_key("matchups_with_500plus_combined_rushing_yards")
    out2 = classify_pool(combined, structure("MATCHUP", (1, 2)),
                         [balanced, lopsided])
    _assert("SUM_BOTH_TEAMS(>=500) rejects both (200 and 280)",
            out2.classification == CLASSIFICATION_ZERO_ELIGIBLE_CLAIMS)


def test_qualifier_threshold_override():
    print("\n-- configurable threshold reads the governed default (§1.5) --")
    spec = CATALOG.by_key("matchups_with_10plus_combined_tds")
    cov = {"total_touchdown_credits"}
    m = matchup_subject(1, [({"total_touchdown_credits": 6.0}, "QB", "QB")],
                        [({"total_touchdown_credits": 5.0}, "QB", "QB")], cov)
    default_out = classify_pool(spec, structure("MATCHUP", (1,)), [m])
    _assert("11 combined TDs meets the default threshold of 10",
            default_out.winning_subject_ids == (1,))
    raised = classify_pool(spec, structure("MATCHUP", (1,)), [m],
                           threshold_override=12)
    _assert("an override binds threshold_value, and 11 then fails",
            raised.classification == CLASSIFICATION_ZERO_ELIGIBLE_CLAIMS)


def test_blocked_definition_raises():
    print("\n-- 18/conformance 19: a BLOCKED definition cannot execute --")
    spec = CATALOG.by_key("most_diverse_touchdown_production")   # #46
    subject = team_subject(1, [({"player_fantasy_points": 1.0}, "QB", "QB")],
                           {"player_fantasy_points"})
    try:
        subject_value(spec, subject)
        _assert("a blocked definition reaching the evaluator raises", False,
                "did not raise")
    except PoolEvaluatorError as exc:
        _assert("a blocked definition reaching the evaluator raises "
                "BLOCKED_DEFINITION", exc.reason == "BLOCKED_DEFINITION",
                exc.reason)


def test_kicker_discriminating():
    print("\n-- 19c: kicker settles on bracket-scored fantasy points --")
    spec = CATALOG.by_key("most_kicking_points")
    cov = {"kicking_points"}
    # Team A: three 20-29yd FGs, no XP.  count-based 3*3 + 0   = 9
    #                                    bracket-scored        = 9.0
    # Team B: two 50+ FGs plus one XP.   count-based 3*2 + 1   = 7
    #                                    bracket-scored 5+5+1  = 11.0
    a = team_subject(1, [({"kicking_points": 9.0}, "K", "K")], cov)
    b = team_subject(2, [({"kicking_points": 11.0}, "K", "K")], cov)
    count_based = {1: 3 * 3 + 0, 2: 3 * 2 + 1}
    _assert("the two bases disagree on this fixture (control is valid)",
            max(count_based, key=count_based.get) == 1)
    out = classify_pool(spec, structure("TEAM", (1, 2)), [a, b])
    _assert("the bracket-scored kicker wins, not the FG-count kicker",
            out.winning_subject_ids == (2,), str(out.winning_subject_ids))


# ── census classifications ────────────────────────────────────────────────────

def test_classifications():
    print("\n-- 23/24/25/27: the four fail-closed classifications --")
    spec = CATALOG.by_key("most_total_touchdowns")
    cov = {"total_touchdown_credits"}

    out = classify_pool(spec, structure("TEAM", ()), [])
    _assert("23 NO_SUBJECTS when considered == 0",
            out.classification == CLASSIFICATION_NO_SUBJECTS)

    uncovered = team_subject(1, [({"total_touchdown_credits": 1.0}, "QB", "QB")],
                             set())
    out = classify_pool(spec, structure("TEAM", (1,)), [uncovered])
    _assert("24 NO_EVALUABLE_SUBJECTS when subjects exist but none evaluable",
            out.classification == CLASSIFICATION_NO_EVALUABLE_SUBJECTS)

    ok = team_subject(1, [({"total_touchdown_credits": 2.0}, "QB", "QB")], cov)
    out = classify_pool(spec, structure("TEAM", (1, 2)), [ok])
    _assert("25 INCOMPLETE_FIELD on one unevaluable subject out of a full field",
            out.classification == CLASSIFICATION_INCOMPLETE_FIELD)
    _assert("25 no completeness threshold settles it",
            out.winning_subject_ids == ())
    _assert("25 subjects_claiming is NOT computed over an incomplete field",
            out.census.subjects_claiming is None)
    _assert("25 the unevaluable subject is identified",
            out.unevaluable_subject_ids == (2,))

    print("\n-- 17: QUALIFIER with zero qualifiers over a COMPLETE field --")
    qual = CATALOG.by_key("the_grand_slam")
    qcov = set(qual.required_stats)
    none_qualify = [team_subject(i, [({s: 0.0 for s in qcov}, "QB", "QB")], qcov)
                    for i in (1, 2)]
    out = classify_pool(qual, structure("TEAM", (1, 2)), none_qualify)
    _assert("17 zero qualifiers over a full field is ZERO_ELIGIBLE_CLAIMS",
            out.classification == CLASSIFICATION_ZERO_ELIGIBLE_CLAIMS)
    _assert("17 the census records a real zero, not an absent count",
            out.census.subjects_claiming == 0
            and out.census.subjects_evaluated == 2)


def test_invariant_violation_precedence():
    print("\n-- 27: complete RANK_EXTREMUM field, zero claimants --")
    # Constructed by removing `direction`, which is the only way a complete
    # RANK_EXTREMUM field can produce no extremum. A ranked field with any
    # subject ALWAYS has one, which is precisely why zero claimants means the
    # evaluator is wrong rather than the data being late.
    spec = CATALOG.by_key("most_total_touchdowns")
    import dataclasses
    broken = dataclasses.replace(spec, direction=None)
    cov = {"total_touchdown_credits"}
    subs = [team_subject(i, [({"total_touchdown_credits": 1.0}, "QB", "QB")], cov)
            for i in (1, 2)]
    out = classify_pool(broken, structure("TEAM", (1, 2)), subs)
    _assert("27 classification is INVARIANT_VIOLATION",
            out.classification == CLASSIFICATION_INVARIANT_VIOLATION)
    try:
        require_settleable(out, definition_key=spec.key, league_id=1,
                           season=2026, week=3)
        _assert("27 refusal raises", False, "did not raise")
    except PoolInvariantViolationError as exc:
        _assert("27 the error type is DISTINCT from the data conditions",
                not isinstance(exc, PoolDataConditionError))
        _assert("27 the refusal carries key, league, week and census",
                exc.as_dict()["definition_key"] == spec.key
                and exc.as_dict()["subjects_considered"] == 2)


def test_error_taxonomy():
    print("\n-- refusal taxonomy: data conditions retry, invariants do not --")
    for cls in (NoSubjectsError, NoEvaluableSubjectsError, IncompleteFieldError):
        _assert(f"{cls.__name__} is a retryable data condition",
                issubclass(cls, PoolDataConditionError)
                and issubclass(cls, PoolSettlementRefusedError))
    _assert("PoolInvariantViolationError is NOT a data condition",
            issubclass(PoolInvariantViolationError, PoolSettlementRefusedError)
            and not issubclass(PoolInvariantViolationError,
                               PoolDataConditionError))


def test_census_source_independence():
    print("\n-- 28: the census comes from the league structure, not the feed --")
    spec = CATALOG.by_key("most_total_touchdowns")
    cov = {"total_touchdown_credits"}
    # The league has three teams. The stat feed returned only two.
    supplied = [team_subject(1, [({"total_touchdown_credits": 3.0}, "QB", "QB")],
                             cov),
                team_subject(2, [({"total_touchdown_credits": 1.0}, "QB", "QB")],
                             cov)]
    out = classify_pool(spec, structure("TEAM", (1, 2, 3)), supplied)
    _assert("28 considered is 3 even though the feed supplied 2",
            out.census.subjects_considered == 3
            and out.census.subjects_evaluated == 2)
    _assert("28 the week fails closed rather than settling on a partial field",
            out.classification == CLASSIFICATION_INCOMPLETE_FIELD)
    # The discriminating half: a census derived from the feed would have read
    # considered == 2 == evaluated and declared a complete field with a winner.
    feed_derived = classify_pool(spec, structure("TEAM", (1, 2)), supplied)
    _assert("28 a feed-derived census WOULD have settled — control is valid",
            feed_derived.classification == CLASSIFICATION_CLAIMS_PRESENT,
            "the implementation must not behave this way, and does not")


# ── POR §6.3 payout ───────────────────────────────────────────────────────────

def test_even_split():
    print("\n-- 12a/12b/12c/12d: POR §6.3 tied payout --")
    alloc = allocate_even_split(1000, [4, 9, 21])
    _assert("12a the POR worked example pays 334/333/333",
            alloc == {4: 334, 9: 333, 21: 333}, str(alloc))
    _assert("12a the extra cent lands on the LOWEST canonical GM ID",
            alloc[4] == 334)

    # 12b — insertion order reversed AND display names sorting differently.
    reversed_order = allocate_even_split(1000, [21, 9, 4])
    names = {4: "Zeke", 9: "Alice", 21: "Bob"}
    by_name = allocate_even_split(
        1000, sorted([4, 9, 21], key=lambda gm: names[gm]))
    _assert("12b reversed insertion order produces the identical allocation",
            reversed_order == alloc, str(reversed_order))
    _assert("12b display-name order produces the identical allocation",
            by_name == alloc,
            "an implementation ordering by display name would pay Alice the "
            "extra cent")

    # 12c — conservation across a sweep of pots and winner counts.
    conserved = True
    for pot in range(0, 5000, 7):
        for n in range(1, 13):
            winners = list(range(1000, 1000 + n))
            a = allocate_even_split(pot, winners)
            if sum(a.values()) != pot:
                conserved = False
            base = pot // n
            if any(v not in (base, base + 1) for v in a.values()):
                conserved = False
    _assert("12c sum(payouts) == pot_cents exactly across the sweep, and every "
            "share is base or base+1", conserved)

    # 12d — determinism under retry.
    _assert("12d a retry reproduces the identical per-GM allocation",
            allocate_even_split(9997, [7, 3, 11, 2])
            == allocate_even_split(9997, [2, 11, 3, 7]))
    _assert("12c no cent is swept to championship by §6.3",
            sum(allocate_even_split(1001, [1, 2, 3]).values()) == 1001)


def main() -> None:
    test_closed_sum_alias_resolution()
    test_rank_extremum_min()
    test_aggregate_over_aggregate_discriminating()
    test_zero_denominator_fails_closed()
    test_bench_and_slot_rules()
    test_player_extremum_within_subject()
    test_balance_ratio()
    test_matchup_score_sum_and_single_subject()
    test_matchup_coverage_is_intersection()
    test_qualifier_quantifiers()
    test_qualifier_threshold_override()
    test_blocked_definition_raises()
    test_kicker_discriminating()
    test_classifications()
    test_invariant_violation_precedence()
    test_error_taxonomy()
    test_census_source_independence()
    test_even_split()


if __name__ == "__main__":
    print("\n=== S4-P1 common engine unit suite ===")
    main()
    print(f"\n  {len(_failures)} failure(s)")
    if _failures:
        for f in _failures:
            print(f"    FAILED: {f}")
        sys.exit(1)
    print("  ALL PASS")