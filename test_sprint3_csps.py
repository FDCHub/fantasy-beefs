#!/usr/bin/env python3
"""Sprint 3 certification — CSPS: components + league rules -> league points.

WHAT THIS SUITE PROVES, AND WHY EACH GROUP EXISTS:

    A  a scoring profile is data, is versioned, and refuses what it cannot trust
    B  the GOLDEN MASTER — the engine reproduces Yahoo's own scoreboard exactly
    C  every scoring rule, exercised one at a time
    D  probability-dependent rules are DEFERRED, not guessed
    E  the quality contract — an incomplete projection never looks complete
    F  the Sprint 2B seam, end to end, with no fallbacks
    G  NO DOUBLE SCORING — executable, not documented
    H  determinism, versioning and cost

GROUP B IS THE SPRINT. Forty real records from two real Yahoo leagues, week 17
of 2025, transcribed from the Phase 0 reconciliation. If this engine's arithmetic
differs from Yahoo's by one hundredth of a point on any of them, the scoring
rules are wrong and everything built on top of them prices wagers incorrectly.

GROUP D IS THE CONCEPTUAL ONE. A projection of 195 rushing yards is not 195
rushing yards; it is the mean of a distribution. Awarding the 150-yard bonus in
full because a MEAN crossed the threshold would over-price every player near
one. This repository holds no approved uncertainty model — there is no CSPS or
IPRM specification — so CSPS refuses those categories rather than inventing a
policy, and this group asserts the refusal.

OFFLINE AND DETERMINISTIC. SQLite in memory, committed fixtures, no network, no
credential, no clock dependency in any asserted value.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from datetime import datetime, timedelta, timezone                 # noqa: E402

from sqlalchemy import create_engine                               # noqa: E402
from sqlalchemy.orm import sessionmaker                            # noqa: E402

from db.schema import (                                            # noqa: E402
    Base, Player, Projection, ProviderComponentProjection,
)
from providers.component_projections import (                      # noqa: E402
    ComponentProjection, persist_snapshot,
)
from providers.cross_identity import (                             # noqa: E402
    BALLDONTLIE, CanonicalSubject, CrossProviderResolution, Outcome,
)
from scoring import csps as C                                      # noqa: E402
from scoring.profile import (                                      # noqa: E402
    ProfileError, ScoringProfile, available_profiles, from_document, load_profile,
)

GOLDEN = os.path.join(ROOT, "providers", "fixtures", "golden")
NOW = datetime(2025, 12, 24, 20, 0, tzinfo=timezone.utc)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _refuses(label: str, call, expected=ProfileError) -> None:
    try:
        call()
    except expected as exc:
        _assert(label, True, str(exc).splitlines()[0][:70])
    except Exception as exc:                                       # noqa: BLE001
        _assert(label, False,
                f"raised {type(exc).__name__}, not {expected.__name__}")
    else:
        _assert(label, False, "returned instead of refusing")


CULV = load_profile("culv_appreciation_society")
WHISKERS = load_profile("mr_whiskers_memorial")


def _near(got: float, want: float, tolerance: float = 1e-9) -> bool:
    """Compare scores the way money is compared, not the way floats are.

    87 rushing yards at 0.1/yd is 8.700000000000001 in IEEE 754. Asserting
    exact equality there tests binary floating point rather than the rule, and
    the golden master already pins every real figure to the cent.
    """
    return abs(got - want) < tolerance


def _score(components, profile=CULV, mode=C.FACTUAL, position=None,
           present=None, derived=()):
    return C.score_components(
        components, profile, mode=mode,
        components_present=present if present is not None else list(components),
        derived_components=derived, position=position)


print("=" * 78)
print("SPRINT 3 · CSPS — COMPONENT PROJECTIONS TO LEAGUE FANTASY POINTS")
print("=" * 78)
print(f"  profiles available  : {list(available_profiles())}")
print(f"  csps version        : {C.CSPS_VERSION}")


# ══════════════════════════════════════════════════════════════════════════════
# A · the scoring profile
# ══════════════════════════════════════════════════════════════════════════════

print("\n3-A · a scoring profile is versioned data, and refuses what it cannot trust")

_assert("both validated leagues load", CULV.profile_id and WHISKERS.profile_id,
        f"{CULV.name} / {WHISKERS.name}")
_assert("each carries a version a result can cite",
        CULV.version == "2025.1" and WHISKERS.version == "2025.1")
_assert("CULV scores 5.00 per passing touchdown, Mr Whiskers 4.00 — the "
        "difference the reconciliation pinned",
        (CULV.passing_touchdown, WHISKERS.passing_touchdown) == (5.0, 4.0))
_assert("CULV scores made field goals by TOTAL YARDAGE; Mr Whiskers by BAND",
        CULV.field_goal_yards_per_point == 0.1 and not CULV.field_goals_made
        and WHISKERS.field_goals_made and not WHISKERS.field_goal_yards_per_point)
_assert("CULV has no yardage bonuses at all — proven absent, not assumed",
        not CULV.rushing_tiers and not CULV.receiving_tiers
        and not CULV.passing_tiers)
_assert("Mr Whiskers' rushing tiers are cumulative at 100 and 150",
        [(t.threshold, t.points) for t in WHISKERS.rushing_tiers][:2]
        == [(100.0, 1.0), (150.0, 1.0)])
_assert("its passing tiers are DECLARED but UNRESOLVED — the league scores "
        "them and no evidence fixes their value",
        all(t.unresolved for t in WHISKERS.passing_tiers)
        and len(WHISKERS.passing_tiers) == 3,
        str(WHISKERS.unresolved_rules))
_assert("  · and CULV carries no unresolved rule at all",
        WHISKERS.unresolved_rules and not CULV.unresolved_rules)

_refuses("a profile with no version is refused — a result could not cite it",
         lambda: from_document({"profile_id": "x", "name": "X"}))
_refuses("a profile whose filename and declared id disagree is refused",
         lambda: from_document({"profile_id": "a", "name": "A",
                                "version": "1"}, profile_id="b"))
_refuses("a profile scoring field goals BOTH by yardage and by band is refused "
         "— one kick would be paid twice",
         lambda: from_document({
             "profile_id": "x", "name": "X", "version": "1",
             "kicker": {"field_goal_yards_per_point": 0.1,
                        "field_goals_made": {"field_goals_made_0_to_39": 3}}}))
_refuses("overlapping points-allowed bands are refused — the score would "
         "depend on which band was checked first",
         lambda: from_document({
             "profile_id": "x", "name": "X", "version": "1",
             "dst": {"points_allowed_bands": [
                 {"low": 0, "high": 10, "points": 5},
                 {"low": 7, "high": 20, "points": 1}]}}))
_refuses("an unknown profile id is refused, not defaulted",
         lambda: load_profile("no_such_league"))


# ══════════════════════════════════════════════════════════════════════════════
# B · the golden master
# ══════════════════════════════════════════════════════════════════════════════

print("\n3-B · GOLDEN MASTER — the engine reproduces Yahoo's own scoreboard")

_totals = {"records": 0, "exact": 0, "error": 0.0, "lineups": 0,
           "lineups_exact": 0}

for _file in ("culv_week17_2025.json", "mr_whiskers_week17_2025.json"):
    _doc = json.load(open(os.path.join(GOLDEN, _file), encoding="utf-8"))
    _profile = load_profile(_doc["profile_id"])
    print(f"\n  {_doc['league']} — Yahoo league {_doc['yahoo_league_id']}, "
          f"{_doc['season']} week {_doc['week']}")

    _assert("    the corpus declares TRANSCRIBED provenance, never CAPTURED",
            _doc["provenance"] == "TRANSCRIBED"
            and "NOT a captured Yahoo payload" in _doc["provenance_note"])

    for _lineup in _doc["lineups"]:
        _team_total = 0.0
        _mismatched = []
        for _r in _lineup["records"]:
            _result = _score(_r["components"], _profile, mode=C.FACTUAL,
                             position=_r["position"],
                             derived=_r["derived_components"])
            _team_total += _result.points
            _diff = abs(_result.points_display - _r["yahoo_points"])
            _totals["records"] += 1
            _totals["error"] += _diff
            if _diff < 0.005:
                _totals["exact"] += 1
            else:
                _mismatched.append(
                    f"{_r['name']} got {_result.points_display} "
                    f"want {_r['yahoo_points']}")
        _assert(f"    {_lineup['team']}: every starter matches Yahoo exactly",
                not _mismatched, "; ".join(_mismatched[:2])
                or f"{len(_lineup['records'])} records")
        _totals["lineups"] += 1
        _exact = abs(round(_team_total, 2) - _lineup["yahoo_total"]) < 0.005
        if _exact:
            _totals["lineups_exact"] += 1
        _assert(f"    {_lineup['team']}: lineup total is exact",
                _exact, f"{round(_team_total, 2)} vs {_lineup['yahoo_total']}")

    _bench_bad = []
    for _r in _doc["bench"]:
        _result = _score(_r["components"], _profile, mode=C.FACTUAL,
                         position=_r["position"],
                         derived=_r["derived_components"])
        _diff = abs(_result.points_display - _r["yahoo_points"])
        _totals["records"] += 1
        _totals["error"] += _diff
        if _diff < 0.005:
            _totals["exact"] += 1
        else:
            _bench_bad.append(f"{_r['name']} got {_result.points_display}")
    _assert(f"    bench records match exactly", not _bench_bad,
            "; ".join(_bench_bad) or f"{len(_doc['bench'])} records")
    _assert("    records the report could not fully publish are EXCLUDED, with "
            "the reason, rather than back-solved from the answer",
            all(item.get("why") for item in _doc["unverifiable"]),
            f"{len(_doc['unverifiable'])} excluded")

print()
_assert("GOLDEN MASTER: every record matches Yahoo to the cent",
        _totals["exact"] == _totals["records"],
        f"{_totals['exact']}/{_totals['records']} exact")
_assert("GOLDEN MASTER: every lineup total matches Yahoo to the cent",
        _totals["lineups_exact"] == _totals["lineups"],
        f"{_totals['lineups_exact']}/{_totals['lineups']} lineups")
_assert("GOLDEN MASTER: total absolute error is ZERO",
        _totals["error"] < 0.005, f"{_totals['error']:.4f}")

# THE CASES THE PHASE 0 REPORT SINGLED OUT, ASSERTED BY NAME. A total that
# happens to land is weaker evidence than the specific mechanic landing.
_whiskers_doc = json.load(open(os.path.join(GOLDEN, "mr_whiskers_week17_2025.json"),
                               encoding="utf-8"))
_by_name = {r["name"]: r for lineup in _whiskers_doc["lineups"]
            for r in lineup["records"]}
_by_name.update({r["name"]: r for r in _whiskers_doc["bench"]})

_bijan = _score(_by_name["Bijan Robinson"]["components"], WHISKERS,
                mode=C.FACTUAL, position="RB")
_assert("  · Bijan Robinson's 195 rushing yards earn the 100 AND 150 tiers, "
        "not just the highest",
        _bijan.contribution("rushing_yard_bonus").contribution == 2.0
        and _bijan.points_display == 39.40)
_stafford = _score(_by_name["Matthew Stafford"]["components"], WHISKERS,
                   mode=C.FACTUAL, position="QB",
                   derived=("pick_six_thrown",))
_assert("  · Matthew Stafford's pick six costs a SECOND -2.00 on top of the "
        "interception itself",
        _stafford.contribution("pick_six_thrown").contribution == -2.0
        and _stafford.points_display == 10.76)
_mcpherson = _score(_by_name["Evan McPherson"]["components"], WHISKERS,
                    mode=C.FACTUAL, position="K")
_assert("  · Evan McPherson's missed extra point costs exactly -3.14",
        _mcpherson.contribution("extra_points_missed").contribution == -3.14
        and _mcpherson.points_display == 5.86)
_titans = _score(_by_name["Titans"]["components"], WHISKERS, mode=C.FACTUAL,
                 position="DEF", derived=("dst_three_and_outs",))
_assert("  · the Titans' 28 points allowed lands in the -1.00 band, and three "
        "three-and-outs pay 3.00",
        _titans.contribution("dst_points_allowed").contribution == -1.0
        and _titans.contribution("dst_three_and_outs").contribution == 3.0
        and _titans.points_display == 6.00)
_assert("  · and a DST total carrying a play-derived count is reported "
        "COMPLETE_WITH_MODELLED_COMPONENTS, never COMPLETE_DIRECT",
        _titans.status == C.ResultStatus.COMPLETE_WITH_MODELLED_COMPONENTS,
        _titans.status)
_bowers = _score({}, WHISKERS, mode=C.FACTUAL, position="TE")
_assert("  · an EMPTY component set is a real zero, not a refusal",
        _bowers.points_display == 0.00
        and _bowers.status != C.ResultStatus.REFUSED, _bowers.status)

_culv_doc = json.load(open(os.path.join(GOLDEN, "culv_week17_2025.json"),
                           encoding="utf-8"))
_culv_by_name = {r["name"]: r for lineup in _culv_doc["lineups"]
                 for r in lineup["records"]}
_culv_by_name.update({r["name"]: r for r in _culv_doc["bench"]})
_tracy = _score(_culv_by_name["Tyrone Tracy Jr."]["components"], CULV,
                mode=C.FACTUAL, position="RB")
_assert("  · CULV: -5 receiving yards score -0.50 — negative yardage is not "
        "floored at zero",
        _tracy.contribution("receiving_yards").contribution == -0.5
        and _tracy.points_display == 6.20)
_lutz = _score(_culv_by_name["Wil Lutz"]["components"], CULV, mode=C.FACTUAL,
               position="K")
_assert("  · CULV: 57 TOTAL made-field-goal yards score 5.70 — the rule "
        "Yahoo's own API cannot serve",
        _lutz.contribution("field_goal_yards").contribution == 5.7
        and _lutz.points_display == 7.70)
_culv_mcpherson = _score(_culv_by_name["Evan McPherson"]["components"], CULV,
                         mode=C.FACTUAL, position="K")
_assert("  · THE SAME missed extra point costs -3.14 in Mr Whiskers and "
        "NOTHING in CULV",
        _culv_mcpherson.contribution("extra_points_missed").contribution == 0.0
        and _culv_mcpherson.points_display == 9.70)


# ══════════════════════════════════════════════════════════════════════════════
# C · every rule, one at a time
# ══════════════════════════════════════════════════════════════════════════════

print("\n3-C · every scoring rule, exercised on its own")

_assert("passing yards at 0.04/yd", _score({"passing_yards": 250}).points == 10.0)
_assert("passing touchdowns", _score({"passing_touchdowns": 3}).points == 15.0)
_assert("interceptions are negative",
        _score({"passing_interceptions": 2}).points == -4.0)
_assert("rushing yards at 0.1/yd",
        _near(_score({"rushing_yards": 87}).points, 8.7))
_assert("rushing touchdowns", _score({"rushing_touchdowns": 2}).points == 12.0)
_assert("receptions at half PPR", _score({"receptions": 7}).points == 3.5)
_assert("receiving yards",
        _near(_score({"receiving_yards": 112}).points, 11.2))
_assert("receiving touchdowns", _score({"receiving_touchdowns": 1}).points == 6.0)
_assert("return touchdowns", _score({"kick_return_touchdowns": 1}).points == 6.0)
_assert("two-point conversions sum across all three structured fields",
        _score({"passing_two_point_conversions": 1,
                "rushing_two_point_conversions": 1}).points == 4.0)
_assert("fumbles lost are negative", _score({"fumbles_lost": 1}).points == -2.0)
_assert("offensive fumble recovery touchdowns",
        _score({"offensive_fumble_recovery_touchdowns": 1}).points == 6.0)

_assert("threshold bonuses are cumulative on a FACTUAL line",
        _score({"rushing_yards": 210}, WHISKERS, position="RB")
        .contribution("rushing_yard_bonus").quality == C.Quality.UNRESOLVED_RULE,
        "210 crosses the unresolved 200 tier")
_assert("  · a line crossing an UNRESOLVED tier REFUSES rather than guessing",
        _score({"rushing_yards": 210}, WHISKERS, position="RB").status
        == C.ResultStatus.REFUSED)
_assert("  · and a line below it scores normally",
        _score({"rushing_yards": 160}, WHISKERS, position="RB")
        .contribution("rushing_yard_bonus").contribution == 2.0)

_assert("kicker: distance bands", _score(
    {"field_goals_made_0_to_39": 2, "field_goals_made_40_to_49": 1,
     "field_goals_made_50_plus": 1}, WHISKERS, position="K").points == 15.0)
_assert("kicker: total made-yardage rule",
        _score({"field_goals_made_yards": 129}, CULV, position="K").points == 12.9)
_assert("kicker: missed field goals by band",
        _score({"field_goals_missed_0_to_39": 1}, WHISKERS,
               position="K").points == -1.0)
_assert("kicker: extra points made and missed",
        _near(_score({"extra_points_made": 3, "extra_points_missed": 1},
                     WHISKERS, position="K").points, -0.14))
_assert("kicker: FRACTIONAL projected attempts score without rounding",
        abs(_score({"field_goals_made_40_to_49": 1.7}, WHISKERS,
                   position="K").points - 6.8) < 1e-9)

_dst = {"defensive_sacks": 3, "defensive_interceptions": 1,
        "opponent_fumble_recoveries": 2, "interception_return_touchdowns": 1,
        "defensive_safeties": 1, "kicks_blocked": 1, "two_point_returns": 1,
        "dst_points_allowed": 10}
_assert("DST: sacks, interceptions, recoveries, touchdown, safety, block, "
        "extra-point return and the points-allowed band",
        _score(_dst, CULV, position="DEF").points == 3 + 2 + 4 + 6 + 2 + 2 + 2 + 4,
        str(_score(_dst, CULV, position="DEF").points))
_assert("DST: the pre-summed turnover_return_touchdowns is NEVER added on top "
        "of its own two components",
        _near(_score({"interception_return_touchdowns": 1,
                      "turnover_return_touchdowns": 1,
                      "dst_points_allowed": 24}, CULV,
                     position="DEF").points, 6.0))
_assert("  · and a defence with NO points-allowed key pitched a shutout — "
        "absent means zero on a factual line, so the 10.00 band applies",
        _near(_score({"defensive_sacks": 1}, CULV, position="DEF").points,
              11.0))
_assert("DST categories do not apply to a non-defence — a quarterback is not "
        "paid the shutout band",
        _score({"passing_yards": 250}, CULV, position="QB").points == 10.0
        and _score({"passing_yards": 250}, CULV, position="QB")
        .contribution("dst_points_allowed").quality == C.Quality.NOT_ENABLED)


# ══════════════════════════════════════════════════════════════════════════════
# D · probability-dependent rules are deferred, not guessed
# ══════════════════════════════════════════════════════════════════════════════

print("\n3-D · uncertainty is IPRM's, and CSPS refuses to guess it")

_proj = _score({"rushing_yards": 195.0, "rushing_touchdowns": 0.8},
               WHISKERS, mode=C.PROJECTION, position="RB")
_assert("a PROJECTED mean above a threshold does NOT collect the bonus",
        _proj.contribution("rushing_yard_bonus").quality
        == C.Quality.MODEL_REQUIRED
        and _proj.contribution("rushing_yard_bonus").contribution == 0.0)
_assert("  · while the same number as a FACTUAL line does",
        _score({"rushing_yards": 195.0}, WHISKERS, mode=C.FACTUAL,
               position="RB").contribution("rushing_yard_bonus").contribution
        == 2.0)
_assert("  · and the projected result is PARTIAL, so it cannot be mistaken "
        "for a complete one",
        _proj.status == C.ResultStatus.PARTIAL)

_proj_dst = _score({"defensive_sacks": 2.4, "dst_points_allowed": 21.3},
                   WHISKERS, mode=C.PROJECTION, position="DEF")
_assert("a PROJECTED points-allowed mean is not dropped into a band",
        _proj_dst.contribution("dst_points_allowed").quality
        == C.Quality.MODEL_REQUIRED)
_assert("  · the sacks beside it still score directly",
        _proj_dst.contribution("dst_sacks").contribution == 2.4)
_assert("three-and-outs are MODEL_REQUIRED in a projection — the provider "
        "publishes none, and Mr Whiskers pays for them",
        _proj_dst.contribution("dst_three_and_outs").quality
        == C.Quality.MODEL_REQUIRED)
_assert("  · and NOT_ENABLED under CULV, which does not score them",
        _score({"defensive_sacks": 2.4}, CULV, mode=C.PROJECTION,
               position="DEF").contribution("dst_three_and_outs").quality
        == C.Quality.NOT_ENABLED)

_proj_qb = _score({"passing_yards": 268.4, "passing_interceptions": 0.7},
                  WHISKERS, mode=C.PROJECTION, position="QB")
_assert("a pick six is MODEL_REQUIRED in a projection — never inferred from "
        "projected interceptions by an assumed rate",
        _proj_qb.contribution("pick_six_thrown").quality
        == C.Quality.MODEL_REQUIRED)

_proj_wr = _score({"targets": 9.8, "receiving_yards": 84.3}, WHISKERS,
                  mode=C.PROJECTION, position="WR")
_assert("receptions are MODEL_REQUIRED when only targets are forecast",
        _proj_wr.contribution("receptions").quality == C.Quality.MODEL_REQUIRED
        and "catch rate" in _proj_wr.contribution("receptions").note)
_assert("  · and are NOT silently scored as zero",
        _proj_wr.contribution("receptions").contribution == 0.0
        and "receptions" in _proj_wr.model_required)


# ══════════════════════════════════════════════════════════════════════════════
# E · the quality contract
# ══════════════════════════════════════════════════════════════════════════════

print("\n3-E · an incomplete projection never looks like a complete one")

_assert("a fully direct factual line is COMPLETE_DIRECT",
        _score({"receptions": 4, "receiving_yards": 78}, CULV,
               position="WR").status == C.ResultStatus.COMPLETE_DIRECT)
_assert("a line carrying a play-derived component is "
        "COMPLETE_WITH_MODELLED_COMPONENTS",
        _titans.status == C.ResultStatus.COMPLETE_WITH_MODELLED_COMPONENTS)
_assert("a projection missing a scored category is PARTIAL",
        _proj_wr.status == C.ResultStatus.PARTIAL)
_assert("a line whose rule value is unresolved is REFUSED, and scores nothing",
        _score({"passing_yards": 320}, WHISKERS, position="QB").status
        == C.ResultStatus.REFUSED
        and _score({"passing_yards": 320}, WHISKERS, position="QB").points == 0.0)
_assert("  · and the refusal says why",
        "no evidence" in _score({"passing_yards": 320}, WHISKERS,
                                position="QB").refusal)
_assert("a PARTIAL result warns that it is a FLOOR, not a total",
        any("FLOOR" in w for w in _proj_wr.warnings), str(_proj_wr.warnings[:1]))
_assert("every category appears in the breakdown, including the ones this "
        "league does not score",
        _score({"receptions": 4}, CULV, position="WR")
        .contribution("dst_sacks").quality == C.Quality.NOT_ENABLED)

_explain = _score({"passing_yards": 287.4, "passing_touchdowns": 2.1}, CULV,
                  mode=C.PROJECTION, position="QB")
_yards = _explain.contribution("passing_yards")
_assert("the breakdown answers 'why is it this number?' without re-running "
        "anything",
        _yards.component == 287.4 and "0.04 per passing yard" in _yards.rule
        and abs(_yards.contribution - 11.496) < 1e-9,
        f"{_yards.component} x rule -> {_yards.contribution}")
_assert("  · components are NOT rounded before scoring",
        abs(_explain.contribution("passing_touchdowns").contribution - 10.5)
        < 1e-9)
_assert("  · and rounding happens once, at the display boundary",
        _explain.points != _explain.points_display
        and _explain.points_display == round(_explain.points, 2))


# ══════════════════════════════════════════════════════════════════════════════
# F · the Sprint 2B seam
# ══════════════════════════════════════════════════════════════════════════════

print("\n3-F · the component seam, end to end, with no fallbacks")

_engine = create_engine("sqlite://")
Base.metadata.create_all(_engine)
_db = sessionmaker(bind=_engine)()
_player = Player(name="Amon-Ra St. Brown", position="WR", nfl_team="DET")
_db.add(_player)
_db.flush()


def _store(components, *, observed_at=NOW, position="WR", season=2025, week=17,
           provider=BALLDONTLIE, key="bdl.p.113"):
    resolution = CrossProviderResolution(
        outcome=Outcome.RESOLVED, provider=provider,
        canonical=CanonicalSubject(player_id=_player.id, name=_player.name,
                                   position="WR", nfl_team="DET"),
        provider_player_key=key, method="normalized_discovery")
    return persist_snapshot(
        _db, resolution=resolution,
        projection=ComponentProjection(
            provider=provider, provider_player_key=key, season=season,
            week=week, components=components,
            components_present=tuple(sorted(components)), nfl_team="DET",
            position=position, observed_at=observed_at),
        captured_at=NOW,
        provenance=ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC)


_early = _store({"receiving_yards": 70.0, "receptions": 5.0},
                observed_at=NOW - timedelta(days=1))
_late = _store({"receiving_yards": 90.0, "receptions": 6.0})

_result = C.score_snapshot(_db, provider=BALLDONTLIE, player_id=_player.id,
                           season=2025, week=17, profile=CULV,
                           mode=C.PROJECTION)
_assert("a stored snapshot scores through the Sprint 2B selector",
        abs(_result.points - (9.0 + 3.0)) < 1e-9, str(_result.points))
_assert("  · and the result carries the snapshot it was scored from",
        _result.component_snapshot_id == _late.snapshot_id)
_assert("  · with the provider, subject, season and week it came from",
        (_result.provider, _result.provider_player_key, _result.season,
         _result.week) == (BALLDONTLIE, "bdl.p.113", 2025, 17))
_assert("  · and the profile and engine versions that produced it",
        (_result.profile_id, _result.profile_version, _result.csps_version)
        == ("culv_appreciation_society", "2025.1", C.CSPS_VERSION))

_as_of = C.score_snapshot(_db, provider=BALLDONTLIE, player_id=_player.id,
                          season=2025, week=17, profile=CULV,
                          as_of=NOW - timedelta(hours=6))
_assert("an as-of scores what was knowable THEN",
        _as_of.component_snapshot_id == _early.snapshot_id
        and abs(_as_of.points - (7.0 + 2.5)) < 1e-9)

_no_provider = C.score_snapshot(_db, provider="some_other_provider",
                                player_id=_player.id, season=2025, week=17,
                                profile=CULV)
_assert("another provider's absence REFUSES — no cross-provider fallback",
        _no_provider.status == C.ResultStatus.REFUSED
        and _no_provider.points == 0.0)

_db.add(Projection(player_id=_player.id, week=9, season=2025,
                   projected_points=18.4, source="fantasypros"))
_db.flush()
_no_week = C.score_snapshot(_db, provider=BALLDONTLIE, player_id=_player.id,
                            season=2025, week=9, profile=CULV)
_assert("a week with a legacy scalar projection but NO component snapshot "
        "still refuses",
        _no_week.status == C.ResultStatus.REFUSED
        and "double-converted" in _no_week.refusal)

_week = C.score_week(_db, provider=BALLDONTLIE, season=2025, week=17,
                     profile=CULV)
_assert("a whole league-week scores in one query, agreeing with the single "
        "read subject by subject",
        _week[_player.id].points == _result.points
        and _week[_player.id].component_snapshot_id
        == _result.component_snapshot_id)

_qb = Player(name="Brock Purdy", position="QB", nfl_team="SF")
_db.add(_qb)
_db.flush()
persist_snapshot(
    _db,
    resolution=CrossProviderResolution(
        outcome=Outcome.RESOLVED, provider=BALLDONTLIE,
        canonical=CanonicalSubject(player_id=_qb.id, name=_qb.name,
                                   position="QB", nfl_team="SF"),
        provider_player_key="bdl.p.27", method="normalized_discovery"),
    projection=ComponentProjection(
        provider=BALLDONTLIE, provider_player_key="bdl.p.27", season=2025,
        week=17, components={"passing_yards": 268.4, "passing_touchdowns": 2.0},
        components_present=("passing_touchdowns", "passing_yards"),
        nfl_team="SF", position="QB", observed_at=NOW),
    captured_at=NOW,
    provenance=ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC)
_db.flush()

_culv_proj = C.score_snapshot(_db, provider=BALLDONTLIE, player_id=_qb.id,
                              season=2025, week=17, profile=CULV)
_whiskers_proj = C.score_snapshot(_db, provider=BALLDONTLIE,
                                  player_id=_qb.id, season=2025, week=17,
                                  profile=WHISKERS)
_assert("THE SAME component snapshot scores differently under the two leagues",
        _culv_proj.component_snapshot_id == _whiskers_proj.component_snapshot_id
        and _near(_culv_proj.points - _whiskers_proj.points, 2.0),
        f"CULV {_culv_proj.points_display} vs "
        f"Whiskers {_whiskers_proj.points_display} — two passing touchdowns "
        f"at 5.00 against 4.00")


# ══════════════════════════════════════════════════════════════════════════════
# G · no double scoring
# ══════════════════════════════════════════════════════════════════════════════

print("\n3-G · a component projection is scored exactly ONCE")

_source = open(os.path.join(ROOT, "scoring", "csps.py"), encoding="utf-8").read()
_profile_source = open(os.path.join(ROOT, "scoring", "profile.py"),
                       encoding="utf-8").read()
import re                                                          # noqa: E402

_assert("CSPS never constructs or queries the legacy scalar Projection model",
        not re.search(r"\bProjection\b(?!Error)", _source.replace(
            "projections.projected_points", "").replace(
            "CspsResult", "").replace("ComponentProjection", ""))
        and "projected_points" not in _profile_source,
        "scoring/ contains no reference to the scalar model")
_assert("  · and it never reads the provider's OWN fantasy point total",
        not re.search(r"""(get|\[)\s*\(?\s*["']fantasy_points["']""", _source)
        and not re.search(r"""(get|\[)\s*\(?\s*["']points["']""", _source),
        "no lookup of a provider-scored total anywhere in the engine")

_provider_scored = {"fantasy_points": 22.74, "points": 22.74}
_fed_back = _score(_provider_scored, CULV, position="WR")
_assert("feeding a provider's own POINT TOTAL in as components scores ZERO — "
        "there is no rule that reads it",
        _fed_back.points == 0.0, str(_fed_back.points))

_once = _score({"receptions": 4, "receiving_yards": 78}, CULV, position="WR")
_twice = _score({"receptions": 4, "receiving_yards": 78}, CULV, position="WR")
_assert("scoring the same components twice does not compound",
        _once.points == _twice.points == 9.8)
_reapplied = _score({"receiving_yards": _once.points}, CULV, position="WR")
_assert("  · and a SCORED total fed back as a component cannot reproduce "
        "itself — the units are different",
        _reapplied.points != _once.points,
        f"{_reapplied.points} vs {_once.points}")
# THE SCAN MUST READ CODE, NOT PROSE. Both modules EXPLAIN at length why the
# legacy scalar is never touched, so a substring search over the raw file finds
# the explanation and reports it as the offence. Docstrings are stripped first,
# using the parser rather than a regex.
import ast                                                        # noqa: E402


def _executable_source(path: str) -> str:
    """A module's source with every docstring removed."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and ast.get_docstring(node):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


_code = _executable_source(os.path.join(ROOT, "scoring", "csps.py"))
_assert("the snapshot seam reads `components`, never a scored figure",
        "snapshot.components" in _code
        and not re.search(r"\.projected_points", _code),
        "no attribute access to projected_points in executable code")
_assert("  · and the same holds for the profile model",
        "projected_points" not in _executable_source(
            os.path.join(ROOT, "scoring", "profile.py")))


# ══════════════════════════════════════════════════════════════════════════════
# H · determinism, versioning and cost
# ══════════════════════════════════════════════════════════════════════════════

print("\n3-H · deterministic, versioned and cheap")

_runs = [_score({"receptions": 4.4, "receiving_yards": 78.3,
                 "receiving_touchdowns": 0.6}, CULV, mode=C.PROJECTION,
                position="WR").points for _ in range(25)]
_assert("the same components and profile give the same answer every time",
        len(set(_runs)) == 1, f"{len(set(_runs))} distinct result(s)")
_assert("the engine version is frozen and travels with the result",
        C.CSPS_VERSION == "csps-v1"
        and _score({"receptions": 1}).csps_version == "csps-v1")
_assert("a profile version change is visible in the result",
        _score({"receptions": 1}, CULV).profile_version == CULV.version)
_assert("the result serialises whole, for storage or audit",
        set(_score({"receptions": 1}, CULV).as_dict())
        >= {"player_id", "provider", "component_snapshot_id", "profile_id",
            "profile_version", "csps_version", "points", "status",
            "contributions", "model_required", "calculated_at"})
_assert("scoring makes no network call and touches no database",
        "httpx" not in _source and "requests" not in _source
        and "def score_components" in _source
        and "db" not in _source.split("def score_components")[1].split(
            "def _pick_six")[0])


# ══════════════════════════════════════════════════════════════════════════════
# I · the synthetic projection corpus, end to end
# ══════════════════════════════════════════════════════════════════════════════

print("\n3-I · every position, through the real Sprint 2B pipeline, both leagues")

from providers.balldontlie.ingest import ingest_week                # noqa: E402
from providers.balldontlie.transport import (                       # noqa: E402
    BalldontlieFixtureTransport,
)

_engine2 = create_engine("sqlite://")
Base.metadata.create_all(_engine2)
_db2 = sessionmaker(bind=_engine2)()
_roster = {}
for _name, _pos, _team in (("Brock Purdy", "QB", "SF"),
                           ("Bijan Robinson", "RB", "ATL"),
                           ("Amon-Ra St. Brown", "WR", "DET"),
                           ("Brock Bowers", "TE", "LV"),
                           ("Cam Little", "K", "JAX"),
                           ("Detroit Lions", "DEF", "DET")):
    _p = Player(name=_name, position=_pos, nfl_team=_team)
    _db2.add(_p)
    _db2.flush()
    _roster[_pos] = _p

_ingest = ingest_week(
    _db2, BalldontlieFixtureTransport(
        os.path.join(ROOT, "providers", "fixtures", "balldontlie")),
    season=2025, week=17, players=list(_roster.values()), captured_at=NOW)
_db2.flush()
_assert("the SYNTHETIC projection week ingests through Sprint 2B unchanged",
        _ingest.persisted == 6 and _ingest.resolved == 6,
        f"{_ingest.persisted} persisted")

_scored = {}
for _pos, _p in _roster.items():
    _scored[_pos] = {
        "culv": C.score_snapshot(_db2, provider=BALLDONTLIE, player_id=_p.id,
                                 season=2025, week=17, profile=CULV,
                                 mode=C.PROJECTION),
        "whiskers": C.score_snapshot(_db2, provider=BALLDONTLIE,
                                     player_id=_p.id, season=2025, week=17,
                                     profile=WHISKERS, mode=C.PROJECTION),
    }

for _pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
    _r = _scored[_pos]["culv"]
    _assert(f"  {_pos}: scores from its own component snapshot",
            _r.component_snapshot_id is not None
            and _r.status != C.ResultStatus.REFUSED,
            f"{_r.points_display} pts, {_r.status}")

_assert("every scored position keeps its provider provenance",
        all(r["culv"].provider == BALLDONTLIE
            and r["culv"].provider_player_key.startswith("bdl.")
            for r in _scored.values()))
_assert("  · and cites the component vocabulary it was scored under",
        all(r["culv"].component_vocabulary_version == "bdl.fantasy.v1"
            for r in _scored.values()))

_qb_culv = _scored["QB"]["culv"]
_qb_whiskers = _scored["QB"]["whiskers"]
_assert("THE SAME QB projection scores differently in the two leagues",
        _near(_qb_culv.points - _qb_whiskers.points,
              1.8 * (5.0 - 4.0)),
        f"CULV {_qb_culv.points_display} vs Whiskers "
        f"{_qb_whiskers.points_display} on 1.8 projected passing touchdowns")

_k_culv = _scored["K"]["culv"]
_k_whiskers = _scored["K"]["whiskers"]
_assert("THE SAME kicker projection scores differently — total yardage against "
        "distance bands",
        not _near(_k_culv.points, _k_whiskers.points)
        and _k_culv.contribution("field_goal_yards").quality
        == C.Quality.DIRECT
        and _k_whiskers.contribution("field_goal_yards").quality
        == C.Quality.NOT_ENABLED,
        f"CULV {_k_culv.points_display} vs Whiskers {_k_whiskers.points_display}")

_wr = _scored["WR"]["culv"]
_assert("a projected WR is PARTIAL — receptions are not forecast, and this "
        "league pays for them",
        _wr.status == C.ResultStatus.PARTIAL
        and "receptions" in _wr.model_required)
_assert("  · and every contribution carries its own arithmetic",
        all(c.rule for c in _wr.contributions)
        and _wr.contribution("receiving_yards").component == 84.3
        and _near(_wr.contribution("receiving_yards").contribution, 8.43))

_def_whiskers = _scored["DEF"]["whiskers"]
_def_culv = _scored["DEF"]["culv"]
_assert("a projected Mr Whiskers defence flags BOTH the points-allowed band "
        "and three-and-outs as model-required",
        {"dst_points_allowed", "dst_three_and_outs"}
        <= set(_def_whiskers.model_required),
        str(sorted(_def_whiskers.model_required)))
_assert("  · while CULV's defence flags only the band, because CULV does not "
        "score three-and-outs",
        "dst_points_allowed" in _def_culv.model_required
        and "dst_three_and_outs" not in _def_culv.model_required)
_assert("  · and the sacks under both are scored directly from the same figure",
        _near(_def_culv.contribution("dst_sacks").component, 2.4)
        and _near(_def_whiskers.contribution("dst_sacks").component, 2.4))

_rerun = C.score_snapshot(_db2, provider=BALLDONTLIE,
                          player_id=_roster["RB"].id, season=2025, week=17,
                          profile=WHISKERS, mode=C.PROJECTION)
_assert("re-scoring the same snapshot gives the identical figure",
        _rerun.points == _scored["RB"]["whiskers"].points
        and _rerun.component_snapshot_id
        == _scored["RB"]["whiskers"].component_snapshot_id)

_batch = C.score_week(_db2, provider=BALLDONTLIE, season=2025, week=17,
                      profile=WHISKERS, mode=C.PROJECTION)
_assert("a whole league-week batch agrees with every single read",
        all(_near(_batch[p.id].points, _scored[pos]["whiskers"].points)
            for pos, p in _roster.items()),
        f"{len(_batch)} subjects")


print()
if _failures:
    print("=" * 78)
    print(f"SPRINT 3 — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  · {_f}")
    print("=" * 78)
    sys.exit(1)
print("=" * 78)
print(f"SPRINT 3 CSPS: all assertions passed — {_totals['exact']}/"
      f"{_totals['records']} historical records and {_totals['lineups_exact']}/"
      f"{_totals['lineups']} lineup totals\nreproduce Yahoo exactly (absolute "
      f"error {_totals['error']:.4f}), and every probability-dependent rule is "
      f"deferred rather than guessed.")
print("=" * 78)
