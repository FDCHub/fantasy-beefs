"""Sprint 4 · IPRM — projection uncertainty, and the scoring it makes possible.

THE THREE LAYERS, AND WHY THE BOUNDARY IS EXACTLY HERE.

    CSPS      components + a league's rules -> deterministic points.
              It owns every SCORING RULE and is the only source of rule truth.

    IPRM      the uncertainty AROUND a projection, and therefore the EXPECTED
              value of the rules whose outcome is probabilistic. It owns no
              scoring rule: it reads the profile CSPS already validated and asks
              "with what probability does that rule pay?"

    sim-v2    draws from the distribution IPRM describes and turns team totals
              into matchup probabilities.

CSPS deliberately refused six categories in Sprint 3 because converting them
needs a probability, not a rate. This module is where those probabilities live —
and where, when the evidence for one does not exist, the refusal is made
permanent rather than papered over.

── WHAT IS MODELLED HERE, AND ON WHAT EVIDENCE ─────────────────────────────

THRESHOLD BONUSES and DST BANDS are modelled. Both are functions of a single
projected quantity whose uncertainty this repository already has an approved
description of: sim-v1 prices every player as Normal(mean, max(|mean| x 0.20,
0.5)). That coefficient of variation is not this sprint's invention — it is the
constant `std_pct` in the frozen sim-v1 model config, applied to real money
today. Re-using it at COMPONENT level is an approximation, and it is labelled as
one: the family is stated, the parameters are stated, and the result carries
MODELLED_LEAGUE_FALLBACK rather than DIRECT.

RECEPTIONS FROM TARGETS, PICK-SIX and THREE-AND-OUTS are NOT modelled, and that
is the honest answer rather than a gap. Each needs history this repository does
not hold:

    receptions      needs a catch rate. Per-player history, or failing that a
                    positional rate measured over a real sample. There is no
                    reception/target history in this repository at all — the
                    identity fixture is identity-only and the stat corpus is one
                    synthetic week — so any rate would be a number chosen to
                    make a test pass.

    pick six        needs a per-quarterback or positional pick-six-per-
                    interception rate. Same absence.

    three-and-outs  needs a defensive team rate and a drive-count projection.
                    Same absence. AND IT IS A DIFFERENT PROBLEM FROM THE FACTUAL
                    DERIVATION: WP2 can count three-and-outs that HAPPENED from
                    play-by-play, under a threshold rule that is itself fitted
                    to one observation. Reusing that count as a projection would
                    be using last week's answer as next week's forecast.

The fallback hierarchy for all three IS implemented and tested — player history,
then positional, then a named conservative rate — so that wiring a real source
later is a data change rather than a code change. With no source wired, every
one of them resolves to MODEL_UNRESOLVED, and a league that scores the category
cannot be priced. That is the intended outcome.

── THE ADMISSION GATE ──────────────────────────────────────────────────────

Only SIMULATION_READY and SIMULATION_READY_WITH_FALLBACKS may enter sim-v2.
PARTIAL and REFUSED may not, and `admissible()` is the single place that decides
— so "this projection is missing a material input" cannot become "this line
looked fine" by travelling one function further.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from scoring import csps as C
from scoring.profile import ScoringProfile

__all__ = [
    "ADMISSIBLE_STATUSES",
    "IPRM_V1",
    "IPRM_VERSION",
    "IprmConfig",
    "IprmResult",
    "ModelledContribution",
    "Quality",
    "Status",
    "admissible",
    "band_expectation",
    "iprm_config_hash",
    "project",
    "threshold_expectation",
]

IPRM_VERSION = "iprm-v1"


class Quality:
    """How a modelled contribution was arrived at. Ordered weakest last."""

    DIRECT = "DIRECT"
    MODELLED_PLAYER_HISTORY = "MODELLED_PLAYER_HISTORY"
    MODELLED_TEAM_HISTORY = "MODELLED_TEAM_HISTORY"
    MODELLED_POSITIONAL_FALLBACK = "MODELLED_POSITIONAL_FALLBACK"
    MODELLED_LEAGUE_FALLBACK = "MODELLED_LEAGUE_FALLBACK"
    MODEL_UNRESOLVED = "MODEL_UNRESOLVED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_ENABLED = "NOT_ENABLED"


class Status:
    """Whether a projection may be simulated, and on what terms."""

    SIMULATION_READY = "SIMULATION_READY"
    SIMULATION_READY_WITH_FALLBACKS = "SIMULATION_READY_WITH_FALLBACKS"
    PARTIAL = "PARTIAL"
    REFUSED = "REFUSED"


#: THE ADMISSION GATE, IN ONE PLACE. A status not in this set never reaches a
#: simulator, and therefore never reaches a price.
ADMISSIBLE_STATUSES = frozenset({Status.SIMULATION_READY,
                                 Status.SIMULATION_READY_WITH_FALLBACKS})

#: Which fallback qualities are still good enough to simulate. A model built on
#: a real history is; an unresolved one is not.
_FALLBACK_QUALITIES = frozenset({Quality.MODELLED_PLAYER_HISTORY,
                                 Quality.MODELLED_TEAM_HISTORY,
                                 Quality.MODELLED_POSITIONAL_FALLBACK,
                                 Quality.MODELLED_LEAGUE_FALLBACK})


@dataclass(frozen=True)
class IprmConfig:
    """Every parameter that can move an expected value or a sigma.

    FROZEN AND HASHED for the same reason `SimModelConfig` is: a Dynamic wager
    that froze a model must be re-priceable under exactly that model, and a
    parameter edited afterwards has to be detectable rather than silent.

    `component_cv` and the sigma pair are DELIBERATELY the sim-v1 numbers. This
    sprint is integration, not a research rewrite, and inventing a second
    volatility opinion would put two answers in the codebase for one question.
    """

    iprm_version: str = IPRM_VERSION

    # ── the uncertainty model ────────────────────────────────────────────────
    distribution: str = "normal"
    #: Coefficient of variation applied to a projected COMPONENT (yards, points
    #: allowed) when estimating the probability a threshold or band is crossed.
    #: The value is sim-v1's `std_pct`, re-used rather than re-derived.
    component_cv: float = 0.20
    #: Player fantasy-point sigma: max(|mean| x std_pct, min_std). Verbatim
    #: sim-v1, so a sim-v2 player carries the volatility production already uses.
    std_pct: float = 0.20
    min_std: float = 0.5
    #: Bands are integer-valued, so a continuity correction of half a point is
    #: applied at each edge when integrating a continuous density over them.
    band_continuity_correction: float = 0.5
    #: A component projected at or below zero has no distribution worth
    #: integrating; its threshold probability is zero rather than a division.
    minimum_modelled_mean: float = 1e-9

    # ── the models that have no evidence in this repository ──────────────────
    #: Catch rate sources, strongest first. Empty tuples mean "no source wired",
    #: which is what makes receptions MODEL_UNRESOLVED rather than a guess.
    catch_rate_player_history: tuple = ()
    catch_rate_positional_fallback: tuple = ()
    #: Named conservative fallback. None, deliberately: a number here would be
    #: chosen to make a test pass, and would silently price every PPR league.
    catch_rate_conservative_fallback: float | None = None

    pick_six_player_history: tuple = ()
    pick_six_positional_fallback: tuple = ()
    pick_six_conservative_fallback: float | None = None

    three_and_out_team_history: tuple = ()
    three_and_out_league_fallback: float | None = None

    def catch_rate(self, player_key: str | None, position: str | None):
        return _hierarchy(self.catch_rate_player_history, player_key,
                          self.catch_rate_positional_fallback, position,
                          self.catch_rate_conservative_fallback)

    def pick_six_rate(self, player_key: str | None, position: str | None):
        return _hierarchy(self.pick_six_player_history, player_key,
                          self.pick_six_positional_fallback, position,
                          self.pick_six_conservative_fallback)

    def three_and_out_rate(self, team: str | None):
        table = dict(self.three_and_out_team_history)
        if team and team in table:
            return table[team], Quality.MODELLED_TEAM_HISTORY, "team history"
        if self.three_and_out_league_fallback is not None:
            return (self.three_and_out_league_fallback,
                    Quality.MODELLED_LEAGUE_FALLBACK, "league fallback")
        return None, Quality.MODEL_UNRESOLVED, "no source wired"


def _hierarchy(player_table: tuple, player_key: str | None,
               positional_table: tuple, position: str | None,
               conservative: float | None):
    """Player history -> positional fallback -> named conservative -> nothing."""
    table = dict(player_table)
    if player_key and player_key in table:
        return table[player_key], Quality.MODELLED_PLAYER_HISTORY, "player history"
    table = dict(positional_table)
    if position and position in table:
        return (table[position], Quality.MODELLED_POSITIONAL_FALLBACK,
                "positional fallback")
    if conservative is not None:
        return conservative, Quality.MODELLED_LEAGUE_FALLBACK, "conservative fallback"
    return None, Quality.MODEL_UNRESOLVED, "no source wired"


IPRM_V1 = IprmConfig()


def iprm_config_hash(config: IprmConfig) -> str:
    """Content hash over the full parameter set. Detection only."""
    canonical = json.dumps(asdict(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── the two distribution models ──────────────────────────────────────────────

def _phi(z: float) -> float:
    """Standard normal CDF. `math.erf` so nothing here needs SciPy."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def threshold_expectation(mean: float, tiers: Sequence, *,
                          cv: float, floor: float = 1e-9) -> tuple:
    """Expected value of a set of CUMULATIVE yardage bonuses.

    THE PROBLEM, PLAINLY. Yahoo pays +1 at 100 rushing yards. A player projected
    for 99.4 yards has very nearly a coin-flip at that bonus; one projected for
    101 has very nearly the same coin-flip. Awarding the full bonus above the
    line and nothing below it makes the projection jump by a whole point across
    a yard, which is the discontinuity that would misprice every player near a
    threshold — and most useful players sit near one.

    THE MODEL. The underlying yardage is treated as Normal(mean, cv x mean),
    with cv the sim-v1 coefficient of variation. Each tier contributes
    P(X >= threshold) x points, and because Yahoo's tiers are CUMULATIVE — 195
    rushing yards earned both the 100 and the 150 in the reconciliation — the
    expectations are SUMMED rather than treated as mutually exclusive.

    THE APPROXIMATION, STATED. A Normal has mass below zero and real yardage
    does not. At the means where bonuses matter (100+ yards, cv 0.20) that mass
    is around 1 in 10 million and is left in rather than renormalised, because
    renormalising would make the model harder to reason about for no measurable
    gain. Below `floor` the distribution is not integrated at all.

    Returns (expected_points, per-tier probabilities).
    """
    if not tiers:
        return 0.0, ()
    if mean is None or mean <= floor:
        return 0.0, tuple((t.threshold, 0.0) for t in tiers)
    sigma = max(abs(mean) * cv, floor)
    out = []
    total = 0.0
    for tier in tiers:
        probability = 1.0 - _phi((tier.threshold - mean) / sigma)
        probability = min(1.0, max(0.0, probability))
        out.append((tier.threshold, probability))
        total += probability * tier.points
    return total, tuple(out)


def band_expectation(mean: float, bands: Sequence, *, cv: float,
                     continuity: float = 0.5, floor: float = 1e-9) -> tuple:
    """Expected value of a DISCRETE band ladder over a continuous projection.

    THE PROBLEM. A defence projected to allow 21.3 points is not a defence that
    WILL allow 21-27. It is a distribution whose mass sits across the 14-20, the
    21-27 and the 28-34 bands, each paying differently. Dropping the mean into
    one bucket pays 0.00 with certainty where the honest answer is a blend —
    and the blend is worth roughly a point, which is the width of most of this
    ladder.

    WHY NOT THE PROVIDER'S OWN BANDS. BALLDONTLIE publishes band probabilities,
    but its bands (14-17, 18-21, 22-27) STRADDLE Yahoo's (14-20, 21-27): a
    single BDL bucket spans a Yahoo boundary, so its mass cannot be assigned to
    one Yahoo band without inventing a split. Phase 0 named exactly this. The
    published buckets are also partial — they do not cover the line — so they
    cannot be renormalised into a distribution either. They are therefore not
    read, and the same Normal model used for thresholds is integrated over
    Yahoo's OWN edges instead.

    THE CONTINUITY CORRECTION. Points allowed is an integer. A band [14, 20]
    covers the real interval [13.5, 20.5), so each edge is widened by half a
    point; without it the bands leave gaps at every boundary and the
    probabilities do not sum to one.

    Returns (expected_points, per-band probabilities).
    """
    if not bands:
        return 0.0, ()
    if mean is None:
        return 0.0, ()
    sigma = max(abs(mean) * cv, floor)
    weights = []
    for band in bands:
        low = _phi((band.low - continuity - mean) / sigma)
        high = _phi((band.high + continuity - mean) / sigma)
        weights.append(max(0.0, high - low))
    mass = sum(weights)
    if mass <= 0.0:
        return 0.0, ()
    # Renormalised over the CONFIGURED ladder. Yahoo's ladder is exhaustive in
    # practice (its last band runs to 999), so this only removes the sliver of
    # density below zero.
    out = []
    total = 0.0
    for band, weight in zip(bands, weights):
        probability = weight / mass
        out.append(((band.low, band.high), probability))
        total += probability * band.points
    return total, tuple(out)


@dataclass(frozen=True)
class ModelledContribution:
    """One probability-dependent category, and exactly how it was valued."""

    category: str
    expected_points: float
    quality: str
    model: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    note: str = ""

    def as_dict(self) -> dict:
        return {"category": self.category,
                "expected_points": self.expected_points,
                "quality": self.quality, "model": self.model,
                "parameters": dict(self.parameters), "note": self.note}


@dataclass
class IprmResult:
    """A simulation-ready distribution, with its whole lineage attached."""

    # ── lineage, carried from CSPS and the component snapshot ────────────────
    player_id: int | None = None
    provider: str | None = None
    provider_player_key: str | None = None
    season: int | None = None
    week: int | None = None
    position: str | None = None
    nfl_team: str | None = None
    component_snapshot_id: int | None = None
    component_vocabulary_version: str | None = None
    scoring_profile_id: str | None = None
    scoring_profile_version: str | None = None
    csps_version: str | None = None
    iprm_version: str = IPRM_VERSION
    iprm_config_hash: str = ""
    observed_at: datetime | None = None
    calculated_at: datetime | None = None

    # ── the distribution ─────────────────────────────────────────────────────
    direct_points: float = 0.0
    modelled_points: float = 0.0
    mean_fantasy_points: float = 0.0
    standard_deviation: float = 0.0
    distribution: str = "normal"

    # ── the audit trail ──────────────────────────────────────────────────────
    direct_contributions: list = field(default_factory=list)
    modelled_contributions: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    status: str = Status.REFUSED
    refusal: str = ""

    @property
    def variance(self) -> float:
        return self.standard_deviation ** 2

    @property
    def admissible(self) -> bool:
        return self.status in ADMISSIBLE_STATUSES

    def modelled(self, category: str):
        for item in self.modelled_contributions:
            if item.category == category:
                return item
        return None

    def fingerprint(self) -> str:
        """A digest over everything that can move this player's distribution.

        Changing the provider, the snapshot, the scoring profile, any engine
        version, the mean or the sigma changes this string. `calculated_at` is
        excluded — WHEN it was computed is not part of WHAT was computed, and
        including it would make every replay of an identical input look
        different.
        """
        payload = {
            "player_id": self.player_id, "provider": self.provider,
            "provider_player_key": self.provider_player_key,
            "season": self.season, "week": self.week,
            "component_snapshot_id": self.component_snapshot_id,
            "component_vocabulary_version": self.component_vocabulary_version,
            "scoring_profile_id": self.scoring_profile_id,
            "scoring_profile_version": self.scoring_profile_version,
            "csps_version": self.csps_version,
            "iprm_version": self.iprm_version,
            "iprm_config_hash": self.iprm_config_hash,
            "mean": repr(float(self.mean_fantasy_points)),
            "sd": repr(float(self.standard_deviation)),
            "distribution": self.distribution,
            "status": self.status,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict:
        return {
            "player_id": self.player_id, "provider": self.provider,
            "provider_player_key": self.provider_player_key,
            "season": self.season, "week": self.week,
            "position": self.position, "nfl_team": self.nfl_team,
            "component_snapshot_id": self.component_snapshot_id,
            "scoring_profile_id": self.scoring_profile_id,
            "scoring_profile_version": self.scoring_profile_version,
            "csps_version": self.csps_version,
            "iprm_version": self.iprm_version,
            "iprm_config_hash": self.iprm_config_hash,
            "direct_points": self.direct_points,
            "modelled_points": self.modelled_points,
            "mean_fantasy_points": self.mean_fantasy_points,
            "standard_deviation": self.standard_deviation,
            "variance": self.variance,
            "distribution": self.distribution,
            "direct_contributions": [c.as_dict()
                                     for c in self.direct_contributions],
            "modelled_contributions": [c.as_dict()
                                       for c in self.modelled_contributions],
            "unresolved": list(self.unresolved),
            "warnings": list(self.warnings),
            "status": self.status,
            "refusal": self.refusal,
            "fingerprint": self.fingerprint(),
            "calculated_at": (self.calculated_at.isoformat()
                              if self.calculated_at else None),
        }


def admissible(result: IprmResult) -> bool:
    """THE gate. Nothing else decides whether a projection may be priced."""
    return result.status in ADMISSIBLE_STATUSES


def project(csps_result: C.CspsResult, *, profile: ScoringProfile,
            components: Mapping[str, float],
            config: IprmConfig = IPRM_V1,
            position: str | None = None,
            nfl_team: str | None = None) -> IprmResult:
    """A CSPS projection -> a simulation-ready distribution, or a refusal.

    CSPS has already scored everything deterministic and listed what it could
    not. This walks that list, values what can be valued, and refuses what
    cannot — it never re-reads a scoring rate, because the profile is the single
    source of rule truth and duplicating a rate here is how two answers to one
    question appear.
    """
    result = IprmResult(
        player_id=csps_result.player_id, provider=csps_result.provider,
        provider_player_key=csps_result.provider_player_key,
        season=csps_result.season, week=csps_result.week,
        position=position, nfl_team=nfl_team,
        component_snapshot_id=csps_result.component_snapshot_id,
        component_vocabulary_version=csps_result.component_vocabulary_version,
        scoring_profile_id=csps_result.profile_id,
        scoring_profile_version=csps_result.profile_version,
        csps_version=csps_result.csps_version,
        iprm_config_hash=iprm_config_hash(config),
        observed_at=csps_result.observed_at,
        calculated_at=datetime.now(timezone.utc),
        distribution=config.distribution,
        direct_contributions=list(csps_result.contributions))

    if csps_result.status == C.ResultStatus.REFUSED:
        result.status = Status.REFUSED
        result.refusal = (
            f"CSPS refused this subject and IPRM cannot rescue it: "
            f"{csps_result.refusal or 'no reason recorded'}")
        return result

    # CSPS IN PROJECTION MODE IS THE ONLY SUPPORTED INPUT. A factual line has no
    # uncertainty to model, and scoring one here would silently convert a result
    # into a forecast.
    if csps_result.mode != C.PROJECTION:
        result.status = Status.REFUSED
        result.refusal = (
            f"IPRM models the uncertainty around a PROJECTION; it was handed a "
            f"{csps_result.mode} result, which describes something that already "
            f"happened and has no distribution to draw from.")
        return result

    result.direct_points = float(csps_result.points)
    modelled: list[ModelledContribution] = []

    for category in csps_result.model_required:
        modelled.append(_value(category, profile=profile,
                               components=components, config=config,
                               position=position, nfl_team=nfl_team,
                               provider_player_key=result.provider_player_key))

    for category in csps_result.unavailable:
        modelled.append(ModelledContribution(
            category=category, expected_points=0.0,
            quality=Quality.UNAVAILABLE, model="none",
            note="this league scores the category and the projection carries "
                 "no input for it"))

    result.modelled_contributions = modelled
    result.modelled_points = sum(m.expected_points for m in modelled)
    result.mean_fantasy_points = result.direct_points + result.modelled_points

    # SIGMA IS SIM-V1'S RULE, UNCHANGED. max(|mean| x std_pct, min_std) is the
    # volatility production prices with today; sim-v2 changes what the mean is
    # built from, not how much it is trusted to vary.
    result.standard_deviation = max(
        abs(result.mean_fantasy_points) * config.std_pct, config.min_std)

    unresolved = [m.category for m in modelled
                  if m.quality in (Quality.MODEL_UNRESOLVED, Quality.UNAVAILABLE)]
    fallbacks = [m.category for m in modelled if m.quality in _FALLBACK_QUALITIES]
    result.unresolved = unresolved

    if unresolved:
        result.status = Status.REFUSED
        result.refusal = (
            f"{unresolved} require a model this repository has no evidence for. "
            f"A price built on a guessed rate is a wrong price with a "
            f"confident face, so this projection is not admissible to "
            f"simulation.")
    elif fallbacks:
        result.status = Status.SIMULATION_READY_WITH_FALLBACKS
        result.warnings.append(
            f"{len(fallbacks)} categor(ies) valued by a model rather than read "
            f"directly: {fallbacks}")
    else:
        result.status = Status.SIMULATION_READY

    if result.standard_deviation <= 0 or not math.isfinite(
            result.standard_deviation):
        result.status = Status.REFUSED
        result.refusal = "the modelled standard deviation is not a usable number"
    if not math.isfinite(result.mean_fantasy_points):
        result.status = Status.REFUSED
        result.refusal = "the modelled mean is not a usable number"
    return result


def _value(category: str, *, profile: ScoringProfile,
           components: Mapping[str, float], config: IprmConfig,
           position: str | None, nfl_team: str | None,
           provider_player_key: str | None) -> ModelledContribution:
    """Value one category CSPS deferred, or record why it cannot be valued."""
    cv = config.component_cv

    if category == "rushing_yard_bonus":
        return _tier(category, components.get("rushing_yards"),
                     profile.rushing_tiers, cv, "rushing_yards")
    if category == "receiving_yard_bonus":
        return _tier(category, components.get("receiving_yards"),
                     profile.receiving_tiers, cv, "receiving_yards")
    if category == "passing_yard_bonus":
        return _tier(category, components.get("passing_yards"),
                     profile.passing_tiers, cv, "passing_yards")

    if category == "dst_points_allowed":
        return _band(category, components.get("dst_points_allowed"),
                     profile.points_allowed_bands, config, "dst_points_allowed")
    if category == "dst_yards_allowed":
        return _band(category, components.get("dst_yards_allowed"),
                     profile.yards_allowed_bands, config, "dst_yards_allowed")

    if category == "receptions":
        return _receptions(components, profile, config, position,
                           provider_player_key)
    if category == "pick_six_thrown":
        return _pick_six(components, profile, config, position,
                         provider_player_key)
    if category == "dst_three_and_outs":
        return _three_and_outs(profile, config, nfl_team)

    return ModelledContribution(
        category=category, expected_points=0.0,
        quality=Quality.MODEL_UNRESOLVED, model="none",
        note=f"no IPRM model is registered for {category!r}")


def _tier(category: str, mean, tiers, cv: float, component: str
          ) -> ModelledContribution:
    if not tiers:
        return ModelledContribution(category, 0.0, Quality.NOT_ENABLED, "none")

    # AN UNRESOLVED TIER VALUE POISONS THE WHOLE LADDER. CSPS raises
    # UNRESOLVED_RULE only on a FACTUAL line, because only a factual line can be
    # compared against a threshold; on a projection the ladder arrives here
    # intact, and a tier whose points are an unresolved 0.0 would contribute
    # P(cross) x 0.0 = nothing at all. That is the same silent under-scoring the
    # factual path refuses, one layer later and harder to see.
    unresolved = [t for t in tiers if t.unresolved]
    if unresolved:
        return ModelledContribution(
            category, 0.0, Quality.MODEL_UNRESOLVED,
            "normal_threshold_crossing",
            parameters={"component": component,
                        "unresolved_thresholds": [t.threshold
                                                  for t in unresolved]},
            note=f"the tier(s) at "
                 f"{', '.join(f'{t.threshold:g}' for t in unresolved)} have no "
                 f"established point value, so the expected bonus cannot be "
                 f"computed. Treating them as worth zero would under-price "
                 f"every projection that might cross one.")
    if mean is None:
        # NOT PROJECTED TO ACCUMULATE THIS YARDAGE AT ALL — a running back has
        # no passing line. The probability of crossing a passing threshold is
        # zero, which is a value, not a gap.
        return ModelledContribution(
            category, 0.0, Quality.DIRECT, "none",
            note=f"{component} is not projected for this subject, so no "
                 f"threshold can be crossed")
    expected, probabilities = threshold_expectation(float(mean), tiers, cv=cv)
    ceiling = sum(t.points for t in tiers)
    return ModelledContribution(
        category=category, expected_points=expected,
        quality=Quality.MODELLED_LEAGUE_FALLBACK,
        model=f"normal_threshold_crossing_cv{cv:g}",
        parameters={"component": component, "mean": float(mean),
                    "cv": cv, "sigma": max(abs(float(mean)) * cv, 1e-9),
                    "tier_probabilities": [
                        {"threshold": t, "probability": p}
                        for t, p in probabilities],
                    "maximum_possible": ceiling},
        note=f"cumulative tiers valued at P(cross) x points; bounded by "
             f"[0, {ceiling:g}]")


def _band(category: str, mean, bands, config: IprmConfig, component: str
          ) -> ModelledContribution:
    if not bands:
        return ModelledContribution(category, 0.0, Quality.NOT_ENABLED, "none")
    if mean is None:
        # A league that scores this band and a projection that carries no such
        # figure IS a material gap — unlike the offensive cases above, there is
        # no reading of the absence that makes the contribution obviously zero.
        return ModelledContribution(
            category, 0.0, Quality.UNAVAILABLE, "none",
            note=f"{component} is not projected, and this league scores it")
    expected, probabilities = band_expectation(
        float(mean), bands, cv=config.component_cv,
        continuity=config.band_continuity_correction)
    return ModelledContribution(
        category=category, expected_points=expected,
        quality=Quality.MODELLED_LEAGUE_FALLBACK,
        model=f"normal_band_integration_cv{config.component_cv:g}",
        parameters={"component": component, "mean": float(mean),
                    "cv": config.component_cv,
                    "continuity_correction": config.band_continuity_correction,
                    "band_probabilities": [
                        {"band": list(b), "probability": p}
                        for b, p in probabilities],
                    "minimum_possible": min(b.points for b in bands),
                    "maximum_possible": max(b.points for b in bands)},
        note="the provider's own bands straddle this league's, so they are not "
             "read; the distribution is integrated over THIS league's edges")


def _receptions(components: Mapping[str, float], profile: ScoringProfile,
                config: IprmConfig, position: str | None,
                player_key: str | None) -> ModelledContribution:
    targets = components.get("targets")
    if targets is None:
        return ModelledContribution(
            "receptions", 0.0, Quality.UNAVAILABLE, "none",
            note="neither receptions nor targets are projected")
    rate, quality, source = config.catch_rate(player_key, position)
    if rate is None:
        return ModelledContribution(
            "receptions", 0.0, Quality.MODEL_UNRESOLVED,
            "targets_x_catch_rate",
            parameters={"targets": float(targets)},
            note="a reception projection is targets x catch rate, and this "
                 "repository holds no reception/target history from which to "
                 "measure one — not per player, not per position. A rate "
                 "chosen here would be a number picked to make a projection "
                 "appear complete.")
    expected_receptions = max(0.0, min(float(targets), float(targets) * rate))
    return ModelledContribution(
        category="receptions",
        expected_points=expected_receptions * profile.reception,
        quality=quality, model="targets_x_catch_rate",
        parameters={"targets": float(targets), "catch_rate": rate,
                    "source": source,
                    "expected_receptions": expected_receptions},
        note="bounded by the projected target count")


def _pick_six(components: Mapping[str, float], profile: ScoringProfile,
              config: IprmConfig, position: str | None,
              player_key: str | None) -> ModelledContribution:
    interceptions = components.get("passing_interceptions")
    if interceptions is None:
        # He is not projected to throw. A player who throws no interceptions
        # cannot throw a pick six, and that bound is exact rather than modelled.
        return ModelledContribution(
            "pick_six_thrown", 0.0, Quality.DIRECT, "none",
            note="no interceptions are projected for this subject, so the "
                 "expected pick-six count is exactly zero")
    rate, quality, source = config.pick_six_rate(player_key, position)
    if rate is None:
        return ModelledContribution(
            "pick_six_thrown", 0.0, Quality.MODEL_UNRESOLVED,
            "interceptions_x_pick_six_rate",
            parameters={"passing_interceptions": float(interceptions)},
            note="this needs a pick-six-per-interception rate measured over a "
                 "real sample, per quarterback or at least per position. There "
                 "is none here, and a constant multiplied by interceptions is "
                 "exactly the arbitrary rate Sprint 4 was told not to invent.")
    expected = max(0.0, min(float(interceptions), float(interceptions) * rate))
    return ModelledContribution(
        category="pick_six_thrown",
        expected_points=expected * profile.pick_six_thrown,
        quality=quality, model="interceptions_x_pick_six_rate",
        parameters={"passing_interceptions": float(interceptions),
                    "rate": rate, "source": source, "expected_count": expected},
        note="the expected pick-six count can never exceed projected "
             "interceptions")


def _three_and_outs(profile: ScoringProfile, config: IprmConfig,
                    nfl_team: str | None) -> ModelledContribution:
    rate, quality, source = config.three_and_out_rate(nfl_team)
    if rate is None:
        return ModelledContribution(
            "dst_three_and_outs", 0.0, Quality.MODEL_UNRESOLVED,
            "team_rate_x_projected_drives",
            note="the provider publishes no three-and-out statistic and no "
                 "projection of one. A projection would need a defensive team "
                 "rate and a drive-count expectation, neither of which exists "
                 "here. NOTE this is a DIFFERENT problem from WP2's factual "
                 "derivation: that counts three-and-outs which happened, under "
                 "a threshold itself fitted to a single observation, and "
                 "reusing last week's count as next week's forecast would be "
                 "neither.")
    return ModelledContribution(
        category="dst_three_and_outs",
        expected_points=max(0.0, rate) * profile.dst_three_and_out,
        quality=quality, model="team_rate_x_projected_drives",
        parameters={"rate": rate, "source": source},
        note="expected count is non-negative by construction")
