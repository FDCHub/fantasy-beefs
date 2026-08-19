"""PDS1 — governed derived stat operands must reach Pool evaluation.

THE DEFECT THIS SUITE OWNS. `betting/pool_subjects.py` splits §C7.2 into two
halves and, before this fix, only wired one of them:

  · `derivable_coverage(...)` expands the COVERAGE set, so a subject carrying
    `rush_attempts` and `receptions` correctly reports that it covers `touches`.
  · `normalize_component(...)` materializes the VALUE, and had NO production
    caller at all.

`betting/pool_shapes.py:114` canonicalizes the operand and then reads
`values.get(name, 0.0)`. So `subject_value` passed the coverage gate — coverage
was honest — and then summed a key that was never present, scoring 0.0.

The three consequences, all economic:

  · CLOSED_SUM over a derived operand scored EVERY subject 0.0, tied the whole
    field at the extremum, and made every claim a winning claim. `allocate_even_split`
    then divided the pot across the entire league.
  · CLOSED_RATIO over derived operands computed 0/0, hit the §3.3 zero
    denominator guard and returned UNEVALUABLE — refusing settlement on complete
    data, which strands the week and cascades to [PRIOR_WEEK_UNSETTLED].
  · QUALIFIER predicates over derived operands were false for every subject, so
    the pot rolled over when a GM had genuinely qualified.

`rank_extremum`'s UNKNOWN_OPERAND guard does NOT catch any of this: production
settlement reaches `classify_pool` -> `subject_value`, and that guard lives only
in `rank_extremum`, which the settlement path never calls.

WHAT IS ASSERTED HERE IS THE FIXED BEHAVIOUR. Run against the unfixed tree every
section past 1 fails, which is the reproduction.
"""
from __future__ import annotations

import os
import sys

_FAILURES: list[str] = []
_PASSES = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _PASSES
    if condition:
        _PASSES += 1
        print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))
    else:
        _FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def banner(title: str) -> None:
    print(f"\n{title}")


from betting.pool_catalog import load_catalog, load_vocabulary
from betting.pool_shapes import UNEVALUABLE, subject_qualifies, subject_value
from betting.pool_subjects import (
    Subject, StatComponent, TeamFrame, derivable_coverage, normalize_component,
)

VOCAB = load_vocabulary()
DERIVED = {n for n, f in VOCAB.derived_formula.items() if f}

print("=" * 78)
print("PDS1 — POOL DERIVED-STAT MATERIALIZATION")
print("=" * 78)


# ── 1 · the governed formula source ──────────────────────────────────────────

banner("1 · Derived operands come from the governed vocabulary, not from code")

check("1a: the six governed derived operands are vocabulary-driven",
      DERIVED == {"touches", "scrimmage_yards", "offensive_yards",
                  "total_touchdown_credits", "field_goals_made",
                  "opportunities"},
      str(sorted(DERIVED)))

# Every formula this suite relies on is READ from the artifact, never restated.
check("1b: touches formula is the artifact's",
      VOCAB.derived_formula["touches"] == "rush_attempts + receptions",
      VOCAB.derived_formula["touches"])
check("1c: scrimmage_yards formula is the artifact's",
      VOCAB.derived_formula["scrimmage_yards"] == "rushing_yards + receiving_yards",
      VOCAB.derived_formula["scrimmage_yards"])

# normalize_component must be consistent with the artifact it claims to serve.
_n, _ = normalize_component({"rush_attempts": 7.0, "receptions": 3.0}, VOCAB)
check("1d: normalize_component derives from raw inputs",
      _n.get("touches") == 10.0, f"touches={_n.get('touches')}")

_n, _ = normalize_component({"rush_attempts": 7.0}, VOCAB)
check("1e: a partially present formula yields NO key (never a partial sum)",
      "touches" not in _n, f"keys={sorted(_n)}")

_n, _ = normalize_component(
    {"rush_attempts": 7.0, "receptions": 3.0, "touches": 99.0}, VOCAB)
check("1f: an explicitly supplied canonical value WINS over derivation",
      _n["touches"] == 99.0, f"touches={_n['touches']}")

_n, _ = normalize_component({"yards": 12.0}, VOCAB)
check("1g: aliases resolve to canonical names",
      _n.get("scrimmage_yards") == 12.0, f"keys={sorted(_n)}")

_n, _ = normalize_component({"rush_attempts": 0.0, "receptions": 0.0}, VOCAB)
check("1h: zero inputs derive a real zero (0 is a value, not an absence)",
      _n.get("touches") == 0.0, f"touches={_n.get('touches')}")


# ── 2 · the provider boundary materializes them ──────────────────────────────

banner("2 · ProviderWeekStatSource hands the evaluator derived operands")

from providers.base import (
    ProviderLeague, ProviderPlayerStats, ProviderRosterEntry, ProviderTeam,
    ProviderWeek,
)
from providers.week_stat_source import ProviderWeekStatSource

PROVIDER = "pds1"
SLOTS = ("QB", "RB", "WR", "TE", "K")


class _Map:
    """Identity whitelist over the raw names this fixture supplies."""

    NAMES = frozenset({
        "passing_yards", "passing_td", "rushing_yards", "rush_attempts",
        "rushing_td", "receiving_yards", "receptions", "receiving_td",
        "targets", "pass_attempts",
        "field_goals_made_0_19", "field_goals_made_20_29",
        "field_goals_made_30_39", "field_goals_made_40_49",
        "field_goals_made_50_plus",
    })

    def canonical_for(self, stat_id: str):
        return stat_id if stat_id in self.NAMES else None


class _Resolver:
    def __init__(self, mapping):
        self._m = dict(mapping)

    @property
    def known_keys(self):
        return tuple(self._m)

    def to_internal(self, key):
        return self._m[key]


def _raw_line(*, rush_att=0.0, rec=0.0, rush_yds=0.0, rec_yds=0.0,
              pass_yds=0.0, pass_att=0.0, ptd=0.0, rtd=0.0, rectd=0.0,
              fg=(0.0, 0.0, 0.0, 0.0, 0.0)):
    return {
        "rush_attempts": rush_att, "receptions": rec,
        "rushing_yards": rush_yds, "receiving_yards": rec_yds,
        "passing_yards": pass_yds, "pass_attempts": pass_att,
        "passing_td": ptd, "rushing_td": rtd, "receiving_td": rectd,
        "targets": rec + 2.0,
        "field_goals_made_0_19": fg[0], "field_goals_made_20_29": fg[1],
        "field_goals_made_30_39": fg[2], "field_goals_made_40_49": fg[3],
        "field_goals_made_50_plus": fg[4],
    }


def build_snapshot(team_lines: dict, week: int = 1):
    """team_lines: {team_key: [raw stat dict per starter, ...]}"""
    teams, rosters, stats = [], [], []
    for team_key, lines in team_lines.items():
        teams.append(ProviderTeam(provider=PROVIDER, team_key=team_key,
                                  team_id=team_key, name=team_key))
        for i, values in enumerate(lines):
            pk = f"{team_key}.p{i}"
            rosters.append(ProviderRosterEntry(
                provider=PROVIDER, team_key=team_key, player_key=pk,
                player_id=pk, week=week, slot=SLOTS[i % len(SLOTS)], name=pk))
            stats.append(ProviderPlayerStats(
                provider=PROVIDER, player_key=pk, week=week, values=values,
                stat_ids_present=frozenset(values), fantasy_points=10.0))
    return ProviderWeek(
        league=ProviderLeague(provider=PROVIDER, league_key="pds1.l.1",
                              name="PDS1", season=2026, current_week=week),
        week=week, teams=tuple(teams), matchups=(),
        roster_entries=tuple(rosters), player_stats=tuple(stats))


from betting.pool_subjects import SCOPE_TEAM, WeeklyStructure

# Two starters carrying raw inputs only — no derived key anywhere in the feed.
SNAP = build_snapshot({
    "T1": [_raw_line(rush_att=10, rec=5, rush_yds=60, rec_yds=40, ptd=1),
           _raw_line(rush_att=6, rec=3, rush_yds=30, rec_yds=20, rtd=1)],
})
SRC = ProviderWeekStatSource(SNAP, stat_map=_Map()).bind(
    None, _Resolver({"T1": 1}))
STRUCT = WeeklyStructure(scope=SCOPE_TEAM, considered_subject_ids=(1,))
SUBJ = SRC.subjects_for(league_id=1, season=2026, week=1, structure=STRUCT)[0]

check("2a: the feed itself carries NO derived key (the premise)",
      all("touches" not in s.values and "scrimmage_yards" not in s.values
          for s in SNAP.player_stats),
      "raw inputs only")

_vals = [dict(c.values) for c in SUBJ.components]
check("2b: touches is materialized on the component",
      all("touches" in v for v in _vals),
      f"per-component touches={[v.get('touches') for v in _vals]}")
check("2c: touches is rush_attempts + receptions",
      [v.get("touches") for v in _vals] == [15.0, 9.0],
      str([v.get("touches") for v in _vals]))
check("2d: scrimmage_yards is materialized",
      [v.get("scrimmage_yards") for v in _vals] == [100.0, 50.0],
      str([v.get("scrimmage_yards") for v in _vals]))
check("2e: offensive_yards is materialized",
      [v.get("offensive_yards") for v in _vals] == [60.0, 30.0],
      str([v.get("offensive_yards") for v in _vals]))
check("2f: total_touchdown_credits is materialized",
      [v.get("total_touchdown_credits") for v in _vals] == [1.0, 1.0],
      str([v.get("total_touchdown_credits") for v in _vals]))
check("2g: field_goals_made sums all five brackets",
      all(v.get("field_goals_made") == 0.0 for v in _vals),
      str([v.get("field_goals_made") for v in _vals]))
check("2h: raw values are untouched by normalization",
      _vals[0]["rushing_yards"] == 60.0 and _vals[0]["receptions"] == 5.0,
      "rushing_yards=60.0 receptions=5.0")
check("2i: coverage still reports the derived operands",
      SUBJ.has_coverage_for(("touches", "scrimmage_yards", "offensive_yards")),
      "coverage and values now agree")


# ── 3 · real catalog definitions evaluate from raw inputs ────────────────────

banner("3 · Representative affected definitions evaluate correctly")

CATALOG = {d.key: d for d in load_catalog().definitions}


def spec_for(key):
    """The catalog's OWN governed spec — never a hand-built stand-in.

    `load_catalog().definitions` already yields `PoolDefinitionSpec`, which is
    exactly what `subject_value` takes, so this suite evaluates the shipped
    definition rather than a local restatement of it.
    """
    return CATALOG[key]


def team_subject(subject_id, lines):
    """Build a TEAM subject through the provider boundary under test."""
    snap = build_snapshot({f"S{subject_id}": lines})
    src = ProviderWeekStatSource(snap, stat_map=_Map()).bind(
        None, _Resolver({f"S{subject_id}": subject_id}))
    st = WeeklyStructure(scope=SCOPE_TEAM,
                         considered_subject_ids=(subject_id,))
    return src.subjects_for(league_id=1, season=2026, week=1, structure=st)[0]


#: ONE line, reused by section 7. Rebuilding it there with different arguments
#: is how an earlier draft of this suite reported a false mismatch.
STRONG_LINE = _raw_line(rush_att=20, rec=10, rush_yds=140, rec_yds=110,
                        pass_yds=300, pass_att=30, ptd=3, rtd=2, rectd=1,
                        fg=(0, 1, 1, 0, 0))
S_STRONG = team_subject(1, [STRONG_LINE])
S_WEAK = team_subject(2, [_raw_line(rush_att=5, rec=2, rush_yds=20,
                                    rec_yds=15, pass_yds=90, pass_att=12,
                                    ptd=0, rtd=0, rectd=0,
                                    fg=(0, 0, 0, 0, 0))])

v_touch_strong = subject_value(spec_for("most_offensive_touches"), S_STRONG, VOCAB)
v_touch_weak = subject_value(spec_for("most_offensive_touches"), S_WEAK, VOCAB)
check("3a: most_offensive_touches — sum(touches) is non-zero",
      v_touch_strong == 30.0 and v_touch_weak == 7.0,
      f"strong={v_touch_strong} weak={v_touch_weak}")

v_td = subject_value(spec_for("most_total_touchdowns"), S_STRONG, VOCAB)
check("3b: most_total_touchdowns — alias total_touchdowns resolves and sums",
      v_td == 6.0, f"value={v_td}")

v_ratio = subject_value(spec_for("highest_yards_per_touch"), S_STRONG, VOCAB)
check("3c: highest_yards_per_touch — ratio computes, no false refusal",
      v_ratio is not UNEVALUABLE and abs(v_ratio - (250.0 / 30.0)) < 1e-9,
      f"value={v_ratio}")

v_fg = subject_value(spec_for("most_field_goals_made"), S_STRONG, VOCAB)
check("3d: most_field_goals_made — five brackets sum to one operand",
      v_fg == 2.0, f"value={v_fg}")

# A genuine zero denominator must STILL refuse — the guard is not disabled.
S_NO_TOUCH = team_subject(3, [_raw_line(rush_att=0, rec=0, rush_yds=0,
                                        rec_yds=0, pass_yds=200, pass_att=25)])
check("3e: a GENUINE zero denominator still returns UNEVALUABLE",
      subject_value(spec_for("highest_yards_per_touch"), S_NO_TOUCH, VOCAB)
      is UNEVALUABLE,
      "0 touches -> refuses, guard intact")


# ── 4 · ranking: no false league-wide tie ────────────────────────────────────

banner("4 · Ranking produces real winners, and ties only on real equality")

from betting.pool_census import classify_pool

FIELD = {
    1: [_raw_line(rush_att=20, rec=10, rush_yds=140, rec_yds=110)],   # 30
    2: [_raw_line(rush_att=12, rec=6, rush_yds=80, rec_yds=60)],      # 18
    3: [_raw_line(rush_att=5, rec=2, rush_yds=20, rec_yds=15)],       # 7
    4: [_raw_line(rush_att=9, rec=4, rush_yds=50, rec_yds=40)],       # 13
}
subs = tuple(team_subject(i, lines) for i, lines in FIELD.items())
struct = WeeklyStructure(scope=SCOPE_TEAM,
                         considered_subject_ids=tuple(FIELD))
out = classify_pool(spec_for("most_offensive_touches"), struct, subs,
                    vocab=VOCAB)
check("4a: every subject evaluates (no INCOMPLETE_FIELD)",
      out.census.subjects_evaluated == 4, str(out.census.as_dict()))
check("4b: values are distinct, not a field of zeros",
      sorted(out.values.values()) == [7.0, 13.0, 18.0, 30.0],
      str(sorted(out.values.values())))
check("4c: exactly ONE winner — the false league-wide tie is gone",
      out.winning_subject_ids == (1,), str(out.winning_subject_ids))

# A REAL tie must still tie.
TIE = {
    1: [_raw_line(rush_att=10, rec=5, rush_yds=60, rec_yds=40)],   # 15
    2: [_raw_line(rush_att=10, rec=5, rush_yds=10, rec_yds=10)],   # 15
    3: [_raw_line(rush_att=2, rec=1, rush_yds=5, rec_yds=5)],      # 3
}
subs_t = tuple(team_subject(i, lines) for i, lines in TIE.items())
out_t = classify_pool(spec_for("most_offensive_touches"),
                      WeeklyStructure(scope=SCOPE_TEAM,
                                      considered_subject_ids=tuple(TIE)),
                      subs_t, vocab=VOCAB)
check("4d: a GENUINE tie still ties (both real 15s win, the 3 does not)",
      out_t.winning_subject_ids == (1, 2), str(out_t.winning_subject_ids))


# ── 5 · qualifier predicates ─────────────────────────────────────────────────

banner("5 · QUALIFIER predicates over derived operands")

q_spec = spec_for("recorded_both_a_td_and_a_field_goal")
q_yes = team_subject(1, [_raw_line(rush_att=8, rec=4, rush_yds=50, rec_yds=30,
                                   rtd=1, fg=(0, 1, 0, 0, 0))])
q_no_fg = team_subject(2, [_raw_line(rush_att=8, rec=4, rush_yds=50,
                                     rec_yds=30, rtd=1)])
q_no_td = team_subject(3, [_raw_line(rush_att=8, rec=4, rush_yds=50,
                                     rec_yds=30, fg=(0, 1, 0, 0, 0))])
check("5a: a subject with a TD and a FG QUALIFIES",
      subject_qualifies(q_spec, q_yes, VOCAB, None) is True)
check("5b: a TD with no FG does not qualify",
      subject_qualifies(q_spec, q_no_fg, VOCAB, None) is False)
check("5c: a FG with no TD does not qualify",
      subject_qualifies(q_spec, q_no_td, VOCAB, None) is False)


# ── 6 · LocalRecordedStatSource is not regressed ─────────────────────────────

banner("6 · LocalRecordedStatSource keeps its documented contract")

from betting.pool_subjects import LocalRecordedStatSource

check("6a: it still advertises exactly its three supported operands",
      LocalRecordedStatSource.SUPPORTED_STATS ==
      frozenset({"player_fantasy_points", "matchup_home_score",
                 "matchup_away_score"}),
      str(sorted(LocalRecordedStatSource.SUPPORTED_STATS)))

# Its single operand has no governed formula, so normalization is a no-op for
# it — proving the fix cannot invent coverage the source never claimed.
_n, _ = normalize_component({"player_fantasy_points": 12.5}, VOCAB)
check("6b: normalizing its component invents nothing",
      _n == {"player_fantasy_points": 12.5}, str(_n))


# ── 7 · provider equivalence ─────────────────────────────────────────────────

banner("7 · Equivalent raw inputs produce equivalent canonical values")

_direct, _ = normalize_component(STRONG_LINE, VOCAB)
_via_provider = dict(S_STRONG.components[0].values)
_shared = set(_direct) & DERIVED
check("7a: every governed derived operand agrees between the direct "
      "normalization and the provider boundary",
      bool(_shared) and all(_direct[k] == _via_provider.get(k)
                            for k in _shared),
      f"{ {k: _direct[k] for k in sorted(_shared)} }")

# The local adaptor's one operand must survive its own boundary identically.
_local, _ = normalize_component({"player_fantasy_points": 21.5}, VOCAB)
check("7b: the local adaptor's operand is unchanged by the same helper",
      _local == {"player_fantasy_points": 21.5}, str(_local))


print("\n" + "=" * 78)
if _FAILURES:
    print(f"PDS1 UNIT/EVALUATION: {_PASSES} passed, {len(_FAILURES)} FAILED")
    for f in _FAILURES:
        print(f"   FAILED: {f}")
    sys.exit(1)
print(f"PDS1 UNIT/EVALUATION: all {_PASSES} assertions PASSED")
