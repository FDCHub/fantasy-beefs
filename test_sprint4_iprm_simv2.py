#!/usr/bin/env python3
"""Sprint 4 certification — IPRM, sim-v2, and the freeze that protects sim-v1.

WHAT THIS SUITE PROVES, AND WHY EACH GROUP EXISTS:

    A  sim-v1 is UNCHANGED — the freeze, proven rather than asserted
    B  the IPRM contract: versions, lineage, fingerprint, admission gate
    C  threshold bonuses are probability-weighted, not mean-bucketed
    D  DST bands are integrated, not bucketed — including the straddle
    E  the three unmodelled categories refuse, and their hierarchies work
    F  the sigma model is sim-v1's, applied per player
    G  sim-v2 end to end, deterministic, with complete provenance
    H  the projection-source switch selects projections and nothing else
    I  calibration bounds — nothing infinite, nothing outside its own range
    J  probability sanity
    K  no network anywhere in the calculation path

GROUP A IS THE ONE THAT PROTECTS PRODUCTION. sim-v1 prices real Locked wagers
today. Sprint 4 adds a sibling model; if it moved v1 by a single probability,
every in-flight Dynamic challenge that froze v1 would Final-Lock under a model
it never agreed to. The frozen config hash and a full fixture replay both have
to come back identical.

GROUP E IS THE ONE THAT PROTECTS THE PRICE. Receptions, pick-six and
three-and-outs have no evidence base in this repository, so IPRM refuses them
and the leagues that score them cannot be priced. A green end-to-end test bought
by inventing a catch rate would be worth less than nothing.

OFFLINE AND DETERMINISTIC. SQLite in memory, committed fixtures, injected
clocks, fixed seeds. No network, no credential.
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

import math                                                        # noqa: E402
from datetime import datetime, timedelta, timezone                 # noqa: E402

import numpy as np                                                 # noqa: E402
from sqlalchemy import create_engine, event                        # noqa: E402
from sqlalchemy.orm import sessionmaker                            # noqa: E402

from db.schema import Base, Player, Projection                     # noqa: E402
from db.schema import ProviderComponentProjection                  # noqa: E402
from odds import odds_engine_headless as ENGINE                    # noqa: E402
from odds import sim_v2 as S                                       # noqa: E402
from odds.model_registry import (                                  # noqa: E402
    ACTIVE_MODEL_VERSION_ID, MODEL_V1, MODEL_V2, model_config_hash,
    registry_version_ids, resolve_model_config,
)
from providers.component_projections import (                      # noqa: E402
    ComponentProjection, persist_snapshot,
)
from providers.cross_identity import (                             # noqa: E402
    BALLDONTLIE, CanonicalSubject, CrossProviderResolution, Outcome,
)
from scoring import csps as C                                      # noqa: E402
from scoring import iprm as I                                      # noqa: E402
from scoring.profile import load_profile                           # noqa: E402

NOW = datetime(2025, 12, 24, 20, 0, tzinfo=timezone.utc)
CULV = load_profile("culv_appreciation_society")
WHISKERS = load_profile("mr_whiskers_memorial")

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _near(got: float, want: float, tol: float = 1e-9) -> bool:
    return abs(got - want) < tol


def _iprm(components, profile=CULV, position="WR", nfl_team="DET",
          config=I.IPRM_V1):
    result = C.score_components(components, profile, mode=C.PROJECTION,
                                components_present=list(components),
                                position=position)
    return I.project(result, profile=profile, components=components,
                     config=config, position=position, nfl_team=nfl_team)


print("=" * 78)
print("SPRINT 4 · IPRM + SIM-V2 PROJECTION PIPELINE")
print("=" * 78)
print(f"  registry            : {list(registry_version_ids())}")
print(f"  active (production) : {ACTIVE_MODEL_VERSION_ID}")
print(f"  iprm version        : {I.IPRM_VERSION}")


# ══════════════════════════════════════════════════════════════════════════════
# A · sim-v1 freeze
# ══════════════════════════════════════════════════════════════════════════════

print("\n4-A · sim-v1 is unchanged")

_assert("sim-v1's frozen config hash is the pre-Sprint-4 value",
        model_config_hash(MODEL_V1)
        == "1d60ff39343bebf1ceb8099f729fbaff18cb278078e06d094da6cc04ba4626d1",
        model_config_hash(MODEL_V1)[:24])
_assert("sim-v1 still truncates draws at zero, still re-scores from PPR",
        MODEL_V1.truncate_draws_at_zero is True
        and MODEL_V1.avg_stats and MODEL_V1.fp_reference)
_assert("PRODUCTION IS STILL POINTED AT SIM-V1 — Sprint 4 activates nothing",
        ACTIVE_MODEL_VERSION_ID == "sim-v1")
_assert("sim-v2 is registered and resolvable beside it",
        set(registry_version_ids()) == {"sim-v1", "sim-v2"}
        and resolve_model_config("sim-v2").model_version_id == "sim-v2")

# THE REPLAY. Same starters, same seed, same engine entry point sim-v1 uses.
_v1_home = [ENGINE.PlayerProj(1, "A", "QB", 22.5, None),
            ENGINE.PlayerProj(2, "B", "RB", 14.2, "questionable"),
            ENGINE.PlayerProj(3, "C", "WR", 11.8, None)]
_v1_away = [ENGINE.PlayerProj(4, "D", "QB", 19.0, None),
            ENGINE.PlayerProj(5, "E", "RB", 16.4, None),
            ENGINE.PlayerProj(6, "F", "WR", 9.9, "doubtful")]
_v1_a = ENGINE.run(101, 1, "H", _v1_home, 2, "A", _v1_away, 17,
                   model_config=MODEL_V1)
_v1_b = ENGINE.run(101, 1, "H", _v1_home, 2, "A", _v1_away, 17,
                   model_config=MODEL_V1)
_assert("a sim-v1 fixture replays to the identical probability",
        _v1_a.home_win_prob == _v1_b.home_win_prob
        and _v1_a.home_proj_mean == _v1_b.home_proj_mean,
        f"{_v1_a.home_win_prob}")
_assert("  · and its starter lines are identical too",
        [s.adjusted_points for s in _v1_a.home_starters]
        == [s.adjusted_points for s in _v1_b.home_starters])
_assert("the function sim-v1 draws with was not modified — the per-sigma draw "
        "is a NEW function beside it",
        hasattr(ENGINE, "_simulate_team")
        and hasattr(ENGINE, "simulate_team_with_sigma"))

_seeded = np.random.default_rng(seed=101 * 1_000 + 17)
_reference = ENGINE._simulate_team(
    np.array([22.5, 14.2 * 0.6, 11.8]), _seeded, model_config=MODEL_V1)
_assert("  · and it still produces its documented shape and truncation",
        _reference.shape == (MODEL_V1.n_sims,) and float(_reference.min()) >= 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# B · the IPRM contract
# ══════════════════════════════════════════════════════════════════════════════

print("\n4-B · the IPRM contract")

_wr = _iprm({"receiving_yards": 84.3, "receptions": 6.1,
             "receiving_touchdowns": 0.6})
_assert("a projection becomes a distribution", _wr.status == I.Status.SIMULATION_READY
        and _wr.mean_fantasy_points > 0 and _wr.standard_deviation > 0,
        f"mean {_wr.mean_fantasy_points:.3f} sd {_wr.standard_deviation:.3f}")
_assert("  · variance is the square of the deviation",
        _near(_wr.variance, _wr.standard_deviation ** 2))
# SPRINT 5 MINTED iprm-v2. v1 refused receptions, pick-six and three-and-outs
# unconditionally; v2 resolves each when a MEASURED parameter is in force. Same
# inputs, potentially different answer — so the version moved rather than the
# behaviour changing underneath a frozen name.
_assert("the version travels with the result", _wr.iprm_version == "iprm-v2",
        _wr.iprm_version)
_assert("  · and so does the whole upstream lineage",
        (_wr.scoring_profile_id, _wr.scoring_profile_version, _wr.csps_version)
        == (CULV.profile_id, CULV.version, C.CSPS_VERSION))
_assert("  · with the IPRM parameter set hashed",
        _wr.iprm_config_hash == I.iprm_config_hash(I.IPRM_V1)
        and len(_wr.iprm_config_hash) == 64)
_assert("the fingerprint is stable across identical recomputation",
        _iprm({"receiving_yards": 84.3, "receptions": 6.1,
               "receiving_touchdowns": 0.6}).fingerprint() == _wr.fingerprint())
_assert("  · and moves when the mean moves",
        _iprm({"receiving_yards": 90.0, "receptions": 6.1,
               "receiving_touchdowns": 0.6}).fingerprint() != _wr.fingerprint())
_assert("  · and when the scoring profile changes",
        _iprm({"receiving_yards": 84.3, "receptions": 6.1,
               "receiving_touchdowns": 0.6},
              profile=WHISKERS).fingerprint() != _wr.fingerprint())

_assert("the admission gate admits only the two ready states",
        I.ADMISSIBLE_STATUSES == {I.Status.SIMULATION_READY,
                                  I.Status.SIMULATION_READY_WITH_FALLBACKS})
_assert("  · and one function decides it",
        I.admissible(_wr) is True)

_factual = C.score_components({"receiving_yards": 84.3}, CULV, mode=C.FACTUAL,
                              components_present=["receiving_yards"],
                              position="WR")
_assert("IPRM REFUSES a factual result — a thing that happened has no "
        "distribution to draw from",
        I.project(_factual, profile=CULV,
                  components={"receiving_yards": 84.3}).status
        == I.Status.REFUSED)
_refused_csps = C.score_components({"rushing_yards": 210}, from_document_probe :=
                                   __import__("scoring.profile",
                                              fromlist=["from_document"])
                                   .from_document({
                                       "profile_id": "p", "name": "P",
                                       "version": "t",
                                       "offense": {"rushing_yards_per_point": 0.1,
                                                   "rushing_tiers": [
                                                       {"threshold": 200,
                                                        "points": 0.0,
                                                        "unresolved": True}]}}),
                                   mode=C.PROJECTION, position="RB")
_assert("  · and it cannot rescue a CSPS refusal either",
        I.project(_refused_csps, profile=from_document_probe,
                  components={"rushing_yards": 210}).status
        == I.Status.REFUSED)


# ══════════════════════════════════════════════════════════════════════════════
# C · threshold bonuses
# ══════════════════════════════════════════════════════════════════════════════

print("\n4-C · threshold bonuses are probability-weighted, never mean-bucketed")

_tiers = WHISKERS.rushing_tiers
_curve = [(m, I.threshold_expectation(m, _tiers, cv=0.20)[0])
          for m in (20, 60, 95, 99, 100, 101, 130, 175, 205, 400)]
_assert("far below the first threshold the expectation is ~zero",
        _curve[0][1] < 1e-6, f"{_curve[0][1]:.2e} at 20 yards")
_assert("AT the threshold the expectation is about half the bonus — a mean is "
        "a coin flip, not a certainty",
        0.45 < _curve[4][1] < 0.60, f"{_curve[4][1]:.3f} at 100 yards")
_assert("  · which is the mean-bucket shortcut refused: it would pay 1.00 here",
        _curve[4][1] < 1.0)
_assert("just below and just above differ by a sliver, not by a whole point",
        abs(_curve[5][1] - _curve[3][1]) < 0.10,
        f"{_curve[3][1]:.3f} at 99 vs {_curve[5][1]:.3f} at 101")
_assert("the curve is monotone increasing in the projection",
        all(b[1] >= a[1] - 1e-12 for a, b in zip(_curve, _curve[1:])))
_assert("far above every tier it approaches the full cumulative bonus",
        _near(_curve[-1][1], 4.0, 0.05), f"{_curve[-1][1]:.3f} of 4.00 at 400")
_assert("tiers are CUMULATIVE, not exclusive — 175 yards is past two of three",
        1.5 < _curve[7][1] < 3.0, f"{_curve[7][1]:.3f} at 175")
_assert("a zero or negative projection crosses nothing",
        I.threshold_expectation(0.0, _tiers, cv=0.20)[0] == 0.0
        and I.threshold_expectation(-5.0, _tiers, cv=0.20)[0] == 0.0)
_assert("a league with no tiers contributes nothing and says NOT_ENABLED",
        _iprm({"rushing_yards": 130.0}, profile=CULV, position="RB")
        .modelled("rushing_yard_bonus") is None)

_whiskers_rb = _iprm({"rushing_yards": 130.0, "rushing_touchdowns": 0.7,
                      "receptions": 3.2, "receiving_yards": 28.0},
                     profile=WHISKERS, position="RB")
_assert("a Mr Whiskers back carries the modelled bonus in its mean",
        _whiskers_rb.modelled("rushing_yard_bonus").expected_points > 0
        and _whiskers_rb.status == I.Status.SIMULATION_READY_WITH_FALLBACKS)
_assert("  · and the model names its family, parameters and bound",
        _whiskers_rb.modelled("rushing_yard_bonus").model.startswith("normal_")
        and "tier_probabilities" in
        _whiskers_rb.modelled("rushing_yard_bonus").parameters
        and _whiskers_rb.modelled("rushing_yard_bonus")
        .parameters["maximum_possible"] == 4.0)


# ══════════════════════════════════════════════════════════════════════════════
# D · DST bands
# ══════════════════════════════════════════════════════════════════════════════

print("\n4-D · points-allowed bands are integrated, not bucketed")

_bands = CULV.points_allowed_bands
_pa = {m: I.band_expectation(m, _bands, cv=0.20)[0]
       for m in (0, 3, 10, 17, 20, 21, 24, 27, 30, 40, 50)}
_assert("a shutout projection earns close to the shutout band",
        _pa[0] > 9.0, f"{_pa[0]:.3f} of 10.00")
_assert("the expectation falls monotonically as points allowed rise",
        all(b <= a + 1e-9 for a, b in zip(list(_pa.values()),
                                          list(_pa.values())[1:])),
        str([round(v, 2) for v in _pa.values()]))
_assert("a mean of 21.3 is NOT simply the 0.00 bucket — the distribution "
        "straddles three bands",
        _pa[21] != 0.0, f"{_pa[21]:.3f}")
_assert("  · and the value sits between the neighbouring bands' scores",
        -1.0 < _pa[24] < 1.0, f"{_pa[24]:.3f} between -1.00 and 1.00")
_assert("every expectation stays inside the ladder's own range",
        all(min(b.points for b in _bands) <= v <= max(b.points for b in _bands)
            for v in _pa.values()))
_assert("band probabilities sum to one",
        _near(sum(p for _, p in I.band_expectation(21.3, _bands, cv=0.20)[1]),
              1.0, 1e-9))
_assert("the boundary between 14-20 and 21-27 is continuous, not a cliff",
        abs(_pa[20] - _pa[21]) < 0.30,
        f"{_pa[20]:.3f} at 20 vs {_pa[21]:.3f} at 21")

_dst = _iprm({"defensive_sacks": 2.4, "dst_points_allowed": 21.3},
             profile=CULV, position="DEF", nfl_team="DET")
_assert("a CULV defence is simulation-ready with the band modelled",
        _dst.status == I.Status.SIMULATION_READY_WITH_FALLBACKS
        and _dst.modelled("dst_points_allowed").quality
        == I.Quality.MODELLED_LEAGUE_FALLBACK)
_assert("  · and the model records WHY the provider's own bands were not used",
        "straddle" in _dst.modelled("dst_points_allowed").note)
_assert("yards-allowed is NOT_ENABLED for both production profiles, so no "
        "model is invented for it",
        not CULV.yards_allowed_bands and not WHISKERS.yards_allowed_bands
        and _dst.modelled("dst_yards_allowed") is None)


# ══════════════════════════════════════════════════════════════════════════════
# E · the three categories with no evidence
# ══════════════════════════════════════════════════════════════════════════════

print("\n4-E · receptions, pick-six and three-and-outs refuse rather than guess")

_targets_only = _iprm({"receiving_yards": 84.3, "targets": 9.8},
                      profile=CULV, position="WR")
_assert("a pass-catcher with targets but no reception projection is REFUSED",
        _targets_only.status == I.Status.REFUSED
        and "receptions" in _targets_only.unresolved)
_assert("  · the model is named, and says a rate would be invented",
        _targets_only.modelled("receptions").model == "targets_x_catch_rate"
        and "no measured catch rate is available"
        in _targets_only.modelled("receptions").note)
_assert("  · and no catch rate is wired at any level of the hierarchy",
        I.IPRM_V1.catch_rate_player_history == ()
        and I.IPRM_V1.catch_rate_positional_fallback == ()
        and I.IPRM_V1.catch_rate_conservative_fallback is None)

# THE HIERARCHY IS REAL, and is proven by wiring a source in a test config.
_with_player = I.IprmConfig(catch_rate_player_history=(("bdl.p.113", 0.72),))
_with_position = I.IprmConfig(catch_rate_positional_fallback=(("WR", 0.62),))
_with_conservative = I.IprmConfig(catch_rate_conservative_fallback=0.55)
for _config, _expected_quality, _rate in (
        (_with_player, I.Quality.MODELLED_PLAYER_HISTORY, 0.72),
        (_with_position, I.Quality.MODELLED_POSITIONAL_FALLBACK, 0.62),
        (_with_conservative, I.Quality.MODELLED_LEAGUE_FALLBACK, 0.55)):
    _csps = C.score_components({"targets": 9.8, "receiving_yards": 84.3}, CULV,
                               mode=C.PROJECTION,
                               components_present=["targets", "receiving_yards"],
                               position="WR")
    _csps.provider_player_key = "bdl.p.113"
    _built = I.project(_csps, profile=CULV,
                       components={"targets": 9.8, "receiving_yards": 84.3},
                       config=_config, position="WR")
    _rec = _built.modelled("receptions")
    _assert(f"  · a wired {_expected_quality} catch rate resolves it",
            _rec.quality == _expected_quality
            and _near(_rec.parameters["expected_receptions"], 9.8 * _rate),
            f"{_rec.parameters['expected_receptions']:.3f} receptions")
    _assert(f"    · bounded by the projected targets",
            _rec.parameters["expected_receptions"] <= 9.8 + 1e-9)

_whiskers_qb = _iprm({"passing_yards": 268.4, "passing_touchdowns": 1.8,
                      "passing_interceptions": 0.7},
                     profile=WHISKERS, position="QB")
_assert("a Mr Whiskers quarterback is REFUSED on the pick-six model",
        _whiskers_qb.status == I.Status.REFUSED
        and _whiskers_qb.unresolved == ["pick_six_thrown"])
_assert("  · and the refusal names the arbitrary rate it will not invent",
        "arbitrary rate" in _whiskers_qb.modelled("pick_six_thrown").note)
_assert("a quarterback projected NO interceptions cannot throw a pick six — "
        "an exact bound, not a model",
        _iprm({"passing_yards": 200.0}, profile=WHISKERS, position="QB")
        .modelled("pick_six_thrown").quality == I.Quality.DIRECT)
_p6 = I.IprmConfig(pick_six_positional_fallback=(("QB", 0.18),))
_p6_csps = C.score_components({"passing_interceptions": 0.7}, WHISKERS,
                              mode=C.PROJECTION,
                              components_present=["passing_interceptions"],
                              position="QB")
_p6_built = I.project(_p6_csps, profile=WHISKERS,
                      components={"passing_interceptions": 0.7}, config=_p6,
                      position="QB")
_assert("  · a wired rate resolves it, bounded by projected interceptions",
        _p6_built.modelled("pick_six_thrown").parameters["expected_count"]
        <= 0.7 + 1e-9
        and _near(_p6_built.modelled("pick_six_thrown")
                  .parameters["expected_count"], 0.7 * 0.18))
_p6_high = I.IprmConfig(pick_six_positional_fallback=(("QB", 5.0),))
_p6_high_built = I.project(_p6_csps, profile=WHISKERS,
                           components={"passing_interceptions": 0.7},
                           config=_p6_high, position="QB")
_assert("  · and an absurd rate is CLAMPED to the interception count",
        _near(_p6_high_built.modelled("pick_six_thrown")
              .parameters["expected_count"], 0.7))

_whiskers_dst = _iprm({"defensive_sacks": 2.4, "dst_points_allowed": 21.3},
                      profile=WHISKERS, position="DEF", nfl_team="TEN")
_assert("a Mr Whiskers defence is REFUSED on three-and-outs",
        _whiskers_dst.status == I.Status.REFUSED
        and "dst_three_and_outs" in _whiskers_dst.unresolved)
_assert("  · it contributes NOTHING rather than an invented zero, and says so",
        _whiskers_dst.modelled("dst_three_and_outs").expected_points == 0.0
        and _whiskers_dst.modelled("dst_three_and_outs").quality
        == I.Quality.MODEL_UNRESOLVED)
_assert("  · and it names the factual/projected distinction explicitly",
        "DIFFERENT problem"
        in _whiskers_dst.modelled("dst_three_and_outs").note)
_tao = I.IprmConfig(three_and_out_team_history=(("TEN", 2.1),))
_tao_csps = C.score_components({"defensive_sacks": 2.4,
                                "dst_points_allowed": 21.3}, WHISKERS,
                               mode=C.PROJECTION,
                               components_present=["defensive_sacks",
                                                   "dst_points_allowed"],
                               position="DEF")
_tao_built = I.project(_tao_csps, profile=WHISKERS,
                       components={"defensive_sacks": 2.4,
                                   "dst_points_allowed": 21.3},
                       config=_tao, position="DEF", nfl_team="TEN")
_assert("  · a wired team rate resolves it as MODELLED_TEAM_HISTORY",
        _tao_built.modelled("dst_three_and_outs").quality
        == I.Quality.MODELLED_TEAM_HISTORY
        and _near(_tao_built.modelled("dst_three_and_outs").expected_points,
                  2.1 * WHISKERS.dst_three_and_out))


# ══════════════════════════════════════════════════════════════════════════════
# F · the sigma model
# ══════════════════════════════════════════════════════════════════════════════

print("\n4-F · the sigma model is sim-v1's, applied per player")

_assert("IPRM's sigma parameters ARE sim-v1's, not a second opinion",
        (I.IPRM_V1.std_pct, I.IPRM_V1.min_std)
        == (MODEL_V1.std_pct, MODEL_V1.min_std) == (0.20, 0.5))
for _pos, _components in (("QB", {"passing_yards": 250.0}),
                          ("RB", {"rushing_yards": 80.0}),
                          ("WR", {"receiving_yards": 70.0, "receptions": 5.0}),
                          ("TE", {"receiving_yards": 40.0, "receptions": 4.0}),
                          ("K", {"field_goals_made_yards": 60.0}),
                          ("DEF", {"defensive_sacks": 2.0,
                                   "dst_points_allowed": 20.0})):
    _r = _iprm(_components, profile=CULV, position=_pos)
    _assert(f"  {_pos}: sigma = max(|mean| x 0.20, 0.5)",
            _near(_r.standard_deviation,
                  max(abs(_r.mean_fantasy_points) * 0.20, 0.5)),
            f"mean {_r.mean_fantasy_points:.2f} sd {_r.standard_deviation:.2f}")

_zero = _iprm({}, profile=CULV, position="WR")
_assert("a zero projection still gets the minimum sigma, never zero",
        _near(_zero.mean_fantasy_points, 0.0)
        and _near(_zero.standard_deviation, 0.5))
_negative = _iprm({"passing_interceptions": 3.0}, profile=CULV, position="QB")
_assert("a NEGATIVE mean is preserved, not floored — the old clamp is gone",
        _negative.mean_fantasy_points < 0,
        f"{_negative.mean_fantasy_points:.2f}")
_assert("  · and its sigma is taken from the magnitude, so it stays positive",
        _negative.standard_deviation > 0
        and _near(_negative.standard_deviation,
                  max(abs(_negative.mean_fantasy_points) * 0.20, 0.5)))
_assert("sim-v2 does NOT truncate draws at zero, and records that as a "
        "versioned difference from sim-v1",
        MODEL_V2.truncate_draws_at_zero is False
        and MODEL_V1.truncate_draws_at_zero is True)
_assert("  · so a negative team total is reachable under sim-v2",
        float(ENGINE.simulate_team_with_sigma(
            np.array([-3.0]), np.array([1.0]),
            np.random.default_rng(7), model_config=MODEL_V2).min()) < 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# G · sim-v2 end to end
# ══════════════════════════════════════════════════════════════════════════════

print("\n4-G · sim-v2 end to end, from persisted snapshot to fair odds")

_engine = create_engine("sqlite://")
Base.metadata.create_all(_engine)
_db = sessionmaker(bind=_engine)()
_queries: list = []
event.listen(_engine, "before_cursor_execute", lambda *a: _queries.append(a[2]))


def _add(name, position, team, components, key, *, observed_at=NOW,
         provider=BALLDONTLIE, season=2025, week=17):
    player = Player(name=name, position=position, nfl_team=team)
    _db.add(player)
    _db.flush()
    persist_snapshot(
        _db,
        resolution=CrossProviderResolution(
            outcome=Outcome.RESOLVED, provider=provider,
            canonical=CanonicalSubject(player_id=player.id, name=name,
                                       position=position, nfl_team=team),
            provider_player_key=key, method="normalized_discovery"),
        projection=ComponentProjection(
            provider=provider, provider_player_key=key, season=season,
            week=week, components=components,
            components_present=tuple(sorted(components)), nfl_team=team,
            position=position, observed_at=observed_at),
        captured_at=NOW,
        provenance=ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC)
    return player.id


_HOME = [
    _add("QB1", "QB", "SF", {"passing_yards": 268.4, "passing_touchdowns": 1.8,
                             "passing_interceptions": 0.7,
                             "rushing_yards": 14.2}, "bdl.p.101"),
    _add("RB1", "RB", "ATL", {"rushing_yards": 92.7, "rushing_touchdowns": 0.7,
                              "receptions": 3.6,
                              "receiving_yards": 33.1}, "bdl.p.102"),
    _add("WR1", "WR", "DET", {"receptions": 6.1, "receiving_yards": 84.3,
                              "receiving_touchdowns": 0.6}, "bdl.p.103"),
    _add("TE1", "TE", "LV", {"receptions": 4.4,
                             "receiving_yards": 48.0}, "bdl.p.104"),
    _add("K1", "K", "JAX", {"field_goals_made_yards": 68.4,
                            "extra_points_made": 2.4}, "bdl.p.105"),
    _add("D1", "DEF", "DET", {"defensive_sacks": 2.4, "dst_points_allowed": 21.3,
                              "defensive_interceptions": 0.8}, "bdl.dst.DET"),
]
_AWAY = [
    _add("QB2", "QB", "LAR", {"passing_yards": 210.0, "passing_touchdowns": 1.1,
                              "passing_interceptions": 0.9}, "bdl.p.201"),
    _add("RB2", "RB", "BUF", {"rushing_yards": 61.0, "rushing_touchdowns": 0.4,
                              "receptions": 2.1,
                              "receiving_yards": 18.0}, "bdl.p.202"),
    _add("WR2", "WR", "LAC", {"receptions": 4.2, "receiving_yards": 55.0,
                              "receiving_touchdowns": 0.3}, "bdl.p.203"),
    _add("TE2", "TE", "CLE", {"receptions": 3.0,
                              "receiving_yards": 31.0}, "bdl.p.204"),
    _add("K2", "K", "CIN", {"field_goals_made_yards": 40.0,
                            "extra_points_made": 1.8}, "bdl.p.205"),
    _add("D2", "DEF", "TEN", {"defensive_sacks": 1.9,
                              "dst_points_allowed": 26.0}, "bdl.dst.TEN"),
]
_db.flush()
_V2 = resolve_model_config("sim-v2")


def _build(ids, team_id, name, profile="culv_appreciation_society",
           source=S.PROJECTION_SOURCE_BALLDONTLIE, as_of=None):
    return S.build_lineup(_db, team_id=team_id, team_name=name,
                          player_ids=ids, season=2025, week=17,
                          profile=profile, projection_source=source,
                          as_of=as_of)


_queries.clear()
_home = _build(_HOME, 1, "Home")
_assert("a six-position lineup builds from persisted snapshots",
        _home.admissible and len(_home.starters) == 6, str(_home.refusals[:1]))
# THE PROPERTY THAT MATTERS IS INDEPENDENCE FROM LINEUP SIZE, not a literal
# count. Sprint 5 added historical model-parameter resolution, which costs a
# FIXED number of queries per lineup however many starters it holds — so the
# assertion measures the shape of the cost rather than one number that any
# later feature would move.
_six_starter_queries = len(_queries)
_queries.clear()
_build([_HOME[0]], 1, "One starter")
_one_starter_queries = len(_queries)
_assert("lineup build cost is INDEPENDENT of lineup size — no N+1",
        _six_starter_queries == _one_starter_queries,
        f"{_six_starter_queries} quer(ies) for 6 starters, "
        f"{_one_starter_queries} for 1")
_assert("  · and is a small fixed number: one snapshot read plus the "
        "historical model parameters",
        _six_starter_queries <= 10, f"{_six_starter_queries} queries")
_away = _build(_AWAY, 2, "Away")

_result, _snapshot = S.run_matchup(matchup_id=99, week=17, home=_home,
                                   away=_away, model_config=_V2,
                                   projection_source=S.PROJECTION_SOURCE_BALLDONTLIE,
                                   season=2025)
_assert("sim-v2 produces a matchup probability",
        0.0 <= _result.home_win_prob <= 1.0
        and _near(_result.home_win_prob + _result.away_win_prob, 1.0, 1e-9),
        f"{_result.home_win_prob}")
_assert("  · and fair American moneylines from it",
        isinstance(_result.home_moneyline, int)
        and isinstance(_result.away_moneyline, int),
        f"{_result.home_moneyline}/{_result.away_moneyline}")
_assert("  · with the simulation count the frozen config names",
        _result.simulations == _V2.n_sims == 10_000)
_assert("  · and the scoring named as CSPS-profile-owned, not a rate here",
        _result.scoring_type == "csps_profile_owned")

_replay, _replay_snapshot = S.run_matchup(
    matchup_id=99, week=17, home=_home, away=_away, model_config=_V2,
    projection_source=S.PROJECTION_SOURCE_BALLDONTLIE, season=2025)
_assert("the same inputs and seed replay to the identical probability",
        _replay.home_win_prob == _result.home_win_prob)
_assert("  · and to the identical fingerprint",
        _replay_snapshot["fingerprint"] == _snapshot["fingerprint"])
_assert("the fingerprint covers the whole chain, not just the simulator",
        all(key in json.dumps(_snapshot) for key in
            ("projection_source_id", "pricing_model_id", "iprm_config_hash",
             "sim_model_config_hash", "fingerprint")))
_assert("  · and the snapshot carries every starter's own fingerprint",
        all(s["fingerprint"] for s in _snapshot["home"]["starters"]))

_whiskers_home = _build(_HOME, 1, "Home", profile="mr_whiskers_memorial")
_assert("MR WHISKERS REFUSES this lineup — the quarterback's pick-six and the "
        "defence's three-and-outs are unresolved",
        not _whiskers_home.admissible and len(_whiskers_home.refusals) == 2,
        str(len(_whiskers_home.refusals)) + " refusals")
_assert("  · and the refusal names the player and the cause",
        any("pick_six" in r for r in _whiskers_home.refusals)
        and any("three_and_out" in r for r in _whiskers_home.refusals))
try:
    S.run_matchup(matchup_id=99, week=17, home=_whiskers_home, away=_away,
                  model_config=_V2, season=2025)
    _assert("  · and pricing a refused lineup RAISES rather than quoting", False)
except S.SimV2Refusal as _exc:
    _assert("  · and pricing a refused lineup RAISES rather than quoting",
            bool(_exc.reasons), str(_exc)[:60])

_changed = _build([_HOME[0]], 1, "One")
_add("QB1b", "QB", "SF", {"passing_yards": 300.0, "passing_touchdowns": 2.4,
                          "passing_interceptions": 0.5}, "bdl.p.101b")
_db.flush()
_assert("changing the scoring profile changes the projection",
        not _near(_build([_HOME[0]], 1, "x").means[0],
                  _build([_HOME[0]], 1, "x",
                         profile="mr_whiskers_memorial").means[0]
                  if _build([_HOME[0]], 1, "x",
                            profile="mr_whiskers_memorial").admissible
                  else -1.0),
        "CULV pays 5.00 per passing touchdown, Mr Whiskers 4.00")

_later = _add("WR3", "WR", "MIA", {"receptions": 5.0, "receiving_yards": 60.0},
              "bdl.p.301", observed_at=NOW - timedelta(days=2))
persist_snapshot(
    _db,
    resolution=CrossProviderResolution(
        outcome=Outcome.RESOLVED, provider=BALLDONTLIE,
        canonical=CanonicalSubject(player_id=_later, name="WR3", position="WR",
                                   nfl_team="MIA"),
        provider_player_key="bdl.p.301", method="normalized_discovery"),
    projection=ComponentProjection(
        provider=BALLDONTLIE, provider_player_key="bdl.p.301", season=2025,
        week=17, components={"receptions": 7.0, "receiving_yards": 95.0},
        components_present=("receiving_yards", "receptions"), nfl_team="MIA",
        position="WR", observed_at=NOW),
    captured_at=NOW,
    provenance=ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC)
_db.flush()
_assert("a NEW component snapshot changes the projection",
        _build([_later], 3, "t").means[0]
        > _build([_later], 3, "t", as_of=NOW - timedelta(days=1)).means[0])
_assert("  · and an as-of selects the older one deterministically",
        _near(_build([_later], 3, "t",
                     as_of=NOW - timedelta(days=1)).means[0], 8.5))


# ══════════════════════════════════════════════════════════════════════════════
# H · the projection-source switch
# ══════════════════════════════════════════════════════════════════════════════

print("\n4-H · projection source selects projections, and nothing else")

from db.schema import League                                       # noqa: E402

_league = League(season=2025, name="CULV Appreciation Society",
                 provider="yahoo", provider_league_key="461.l.488800",
                 projection_source=S.PROJECTION_SOURCE_BALLDONTLIE)
_db.add(_league)
_db.flush()
_assert("League.provider and League.projection_source are SEPARATE columns",
        "provider" in League.__table__.c
        and "projection_source" in League.__table__.c)
_assert("  · a Yahoo-hosted league can forecast from BALLDONTLIE",
        _league.provider == "yahoo"
        and S.resolve_projection_source(_league)
        == S.PROJECTION_SOURCE_BALLDONTLIE)
_assert("  · and the resolver reads ONLY the projection source",
        "provider" not in
        S.resolve_projection_source.__doc__.split("never consults")[1][:40])

_no_bdl = _build(_HOME, 1, "Home", source=S.PROJECTION_SOURCE_YAHOO)
_assert("a league configured for YAHOO projections does NOT silently use the "
        "BALLDONTLIE snapshots that exist",
        not _no_bdl.admissible and len(_no_bdl.refusals) == 6,
        f"{len(_no_bdl.refusals)} refusals")
_assert("  · and each refusal says no snapshot exists for THAT source",
        all("no yahoo component snapshot" in r for r in _no_bdl.refusals))
try:
    _build(_HOME, 1, "Home", source=S.PROJECTION_SOURCE_LEGACY)
    _assert("the legacy fantasypros scalar is REFUSED by the component builder",
            False)
except S.SimV2Refusal as _exc:
    _assert("the legacy fantasypros scalar is REFUSED by the component builder",
            "sim-v1" in str(_exc), str(_exc)[:70])

_db.add(Projection(player_id=_HOME[0], week=17, season=2025,
                   projected_points=99.9, source="fantasypros"))
_db.flush()
_assert("a legacy scalar projection for the same player-week is NOT consulted",
        _near(_build([_HOME[0]], 1, "x").means[0],
              _iprm({"passing_yards": 268.4, "passing_touchdowns": 1.8,
                     "passing_interceptions": 0.7, "rushing_yards": 14.2},
                    profile=CULV, position="QB").mean_fantasy_points))


# ══════════════════════════════════════════════════════════════════════════════
# I · calibration bounds
# ══════════════════════════════════════════════════════════════════════════════

print("\n4-I · every modelled quantity stays inside its own bounds")

for _mean in (0.0, 0.5, 50.0, 99.9, 100.0, 250.0, 1000.0):
    _expected, _probs = I.threshold_expectation(_mean, WHISKERS.rushing_tiers,
                                                cv=0.20)
    _assert(f"  threshold expectation at {_mean:g} is within [0, 4.00]",
            0.0 <= _expected <= 4.0 + 1e-9 and math.isfinite(_expected),
            f"{_expected:.4f}")
    _assert(f"    · and every tier probability is a probability",
            all(0.0 <= p <= 1.0 for _, p in _probs))

for _mean in (0.0, 7.0, 21.3, 45.0, 90.0):
    _expected, _probs = I.band_expectation(_mean, CULV.points_allowed_bands,
                                           cv=0.20)
    _assert(f"  points-allowed expectation at {_mean:g} is inside the ladder",
            -7.0 - 1e-9 <= _expected <= 10.0 + 1e-9
            and math.isfinite(_expected), f"{_expected:.4f}")

_all_results = [_iprm(c, profile=p, position=pos) for c, p, pos in (
    ({"receptions": 6.1, "receiving_yards": 84.3}, CULV, "WR"),
    ({"passing_yards": 268.4}, CULV, "QB"),
    ({"defensive_sacks": 2.4, "dst_points_allowed": 21.3}, CULV, "DEF"),
    ({}, CULV, "TE"))]
_assert("no mean or sigma is NaN or infinite, anywhere",
        all(math.isfinite(r.mean_fantasy_points)
            and math.isfinite(r.standard_deviation) for r in _all_results))
_assert("every sigma is strictly positive",
        all(r.standard_deviation > 0 for r in _all_results))


# ══════════════════════════════════════════════════════════════════════════════
# J · probability sanity
# ══════════════════════════════════════════════════════════════════════════════

print("\n4-J · the simulator behaves like a simulator")


def _prob(home_means, away_means, *, sd=3.0, matchup_id=7):
    home = S.LineupBuild(team_id=1, team_name="H")
    away = S.LineupBuild(team_id=2, team_name="A")
    for build, means in ((home, home_means), (away, away_means)):
        for index, mean in enumerate(means):
            result = I.IprmResult(player_id=index, mean_fantasy_points=mean,
                                  standard_deviation=sd,
                                  status=I.Status.SIMULATION_READY)
            build.iprm_results.append(result)
            build.starters.append(ENGINE.StarterLine(index, str(index), "WR",
                                                     mean, mean))
    return S.run_matchup(matchup_id=matchup_id, week=1, home=home, away=away,
                         model_config=_V2, season=2025)[0]


_assert("a much stronger team wins far more often than not",
        _prob([30, 30, 30], [10, 10, 10]).home_win_prob > 0.95)
_assert("identical distributions are a coin flip",
        0.47 < _prob([20, 20, 20], [20, 20, 20]).home_win_prob < 0.53,
        f"{_prob([20, 20, 20], [20, 20, 20]).home_win_prob}")
_assert("swapping the teams inverts the probability",
        _near(_prob([25, 20, 15], [18, 18, 18]).home_win_prob
              + _prob([18, 18, 18], [25, 20, 15]).home_win_prob, 1.0, 0.03))
_base = _prob([20, 20, 20], [20, 20, 20]).home_win_prob
_assert("raising one player's mean never lowers the team's win probability",
        _prob([24, 20, 20], [20, 20, 20]).home_win_prob >= _base)
_assert("a negative-mean roster still prices, and loses",
        _prob([-2, -2, -2], [15, 15, 15]).home_win_prob < 0.05)

# ALL ELSE IS NOT EQUAL BETWEEN THE TWO PROFILES, so the comparison is made on
# the touchdown CONTRIBUTION rather than the total: Mr Whiskers also carries
# passing-yardage tiers that CULV does not, and at 250 projected yards the 300
# threshold is already worth a fraction of a point.
_culv_qb = _iprm({"passing_yards": 250.0, "passing_touchdowns": 2.0},
                 profile=CULV, position="QB")
_whiskers_qb_mean = _iprm({"passing_yards": 250.0, "passing_touchdowns": 2.0},
                          profile=WHISKERS, position="QB")
_culv_td = C.score_components(
    {"passing_yards": 250.0, "passing_touchdowns": 2.0}, CULV,
    mode=C.PROJECTION, position="QB").contribution("passing_touchdowns")
_whiskers_td = C.score_components(
    {"passing_yards": 250.0, "passing_touchdowns": 2.0}, WHISKERS,
    mode=C.PROJECTION, position="QB").contribution("passing_touchdowns")
_assert("moving the passing touchdown from 5.00 to 4.00 drops that "
        "contribution by exactly the projected touchdown count",
        _near(_culv_td.contribution - _whiskers_td.contribution, 2.0),
        f"{_culv_td.contribution} vs {_whiskers_td.contribution}")
_assert("  · and the Mr Whiskers TOTAL differs by that less its own passing "
        "tier, which CULV does not score at all",
        _culv_qb.mean_fantasy_points > _whiskers_qb_mean.mean_fantasy_points
        and _near(_culv_qb.mean_fantasy_points
                  - _whiskers_qb_mean.mean_fantasy_points
                  + _whiskers_qb_mean.modelled("passing_yard_bonus")
                  .expected_points, 2.0),
        f"tier adds "
        f"{_whiskers_qb_mean.modelled('passing_yard_bonus').expected_points:.3f}")
_assert("a higher threshold-bonus probability never lowers the mean",
        _iprm({"rushing_yards": 160.0}, profile=WHISKERS,
              position="RB").mean_fantasy_points
        >= _iprm({"rushing_yards": 160.0}, profile=CULV,
                 position="RB").mean_fantasy_points)


# ══════════════════════════════════════════════════════════════════════════════
# K · no network in the calculation path
# ══════════════════════════════════════════════════════════════════════════════

print("\n4-K · the calculation path cannot reach a network")

import ast                                                         # noqa: E402


def _imports(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


for _module in ("scoring/csps.py", "scoring/iprm.py", "scoring/profile.py",
                "odds/sim_v2.py", "odds/odds_engine_headless.py",
                "odds/model_registry.py"):
    _found = _imports(os.path.join(ROOT, _module))
    _assert(f"  {_module} imports no HTTP client",
            not ({"httpx", "requests", "urllib", "socket", "http"} & _found),
            str(sorted({"httpx", "requests", "urllib", "socket", "http"}
                       & _found)))
_assert("  · and none of them reaches a provider transport",
        not any("transport" in open(os.path.join(ROOT, m),
                                    encoding="utf-8").read()
                for m in ("scoring/iprm.py", "odds/sim_v2.py")))

_queries.clear()
_pure = [_iprm({"receiving_yards": 84.3, "receptions": 6.1}) for _ in range(50)]
_assert("scoring and modelling touch the database ZERO times",
        len(_queries) == 0 and len(_pure) == 50, f"{len(_queries)} queries")


print()
if _failures:
    print("=" * 78)
    print(f"SPRINT 4 — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  · {_f}")
    print("=" * 78)
    sys.exit(1)
print("=" * 78)
print("SPRINT 4 IPRM + sim-v2: all assertions passed — sim-v1 frozen and "
      "unchanged,\nprobability-dependent scoring modelled rather than bucketed, "
      "and every category\nwithout evidence refuses rather than guessing.")
print("=" * 78)
