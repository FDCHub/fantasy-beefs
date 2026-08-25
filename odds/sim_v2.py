"""Sprint 4 · sim-v2 — the CSPS/IPRM projection path into the certified engine.

WHAT IS NEW HERE AND WHAT IS DELIBERATELY NOT.

    NEW        the INPUT BUILDER. Where sim-v1 reads a FantasyPros scalar out of
               `projections.projected_points` and re-scores it with position
               averages, sim-v2 reads a persisted component snapshot, scores it
               through CSPS under the league's own certified profile, and asks
               IPRM for a distribution.

    NOT NEW    the SIMULATION. The Monte Carlo draw, the win-probability count,
               the tie rule, the probability complement and the American-odds
               conversion are the certified functions in
               `odds/odds_engine_headless.py`, called rather than reimplemented.
               A second copy of that arithmetic is the last thing this product
               needs.

The only addition to the engine is `simulate_team_with_sigma`, which takes one
sigma per player because IPRM produces one per player. `_simulate_team` — the
function sim-v1 calls — is untouched.

── THE ADMISSION GATE IS ENFORCED HERE, ONCE ───────────────────────────────

A lineup is priced only if EVERY starter's IPRM result is admissible. One
refused player refuses the lineup, because a team total missing a starter is not
a smaller team total — it is a wrong one, and it would price a wager. The
failure is named: which player, and which model was unresolved.

── PROJECTION SOURCE IS NOT LEAGUE PROVIDER ────────────────────────────────

`League.provider` says who hosts the league — Yahoo — and stays authoritative
for identity, rosters, starters and schedule. `League.projection_source` says
who forecasts, and it is the only thing this module switches on. There is no
fallback between them in either direction: a league configured for BALLDONTLIE
projections whose snapshots are missing REFUSES, and never quietly prices off
Yahoo's scalar instead.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np

from odds.model_registry import SimModelConfig, model_config_hash
from odds.odds_engine_headless import (
    OddsResult,
    StarterLine,
    _prob_to_american,
    simulate_team_with_sigma,
)
from scoring import csps as C
from scoring import iprm as I
from scoring.profile import ScoringProfile, load_profile

__all__ = [
    "PROJECTION_SOURCE_BALLDONTLIE",
    "PROJECTION_SOURCE_YAHOO",
    "LineupBuild",
    "SimV2Refusal",
    "build_lineup",
    "resolve_projection_source",
    "run_matchup",
    "simulation_fingerprint",
]

#: The two projection sources this sprint wires. They name PROJECTIONS ONLY.
PROJECTION_SOURCE_BALLDONTLIE = "balldontlie"
PROJECTION_SOURCE_YAHOO = "yahoo"
#: The legacy default already in `League.projection_source` for every league.
PROJECTION_SOURCE_LEGACY = "fantasypros"


class SimV2Refusal(ValueError):
    """sim-v2 declined to price. Carries which subject and why."""

    def __init__(self, message: str, *, reasons: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.reasons = list(reasons)


@dataclass
class LineupBuild:
    """One team's simulation inputs, plus everything that produced them."""

    team_id: int
    team_name: str
    starters: list = field(default_factory=list)          # StarterLine
    iprm_results: list = field(default_factory=list)      # IprmResult
    refusals: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def admissible(self) -> bool:
        return bool(self.starters) and not self.refusals

    @property
    def means(self) -> np.ndarray:
        return np.array([r.mean_fantasy_points for r in self.iprm_results],
                        dtype=float)

    @property
    def sigmas(self) -> np.ndarray:
        return np.array([r.standard_deviation for r in self.iprm_results],
                        dtype=float)

    def as_dict(self) -> dict:
        return {"team_id": self.team_id, "team_name": self.team_name,
                "starters": [
                    {"player_id": r.player_id,
                     "provider_player_key": r.provider_player_key,
                     "position": r.position,
                     "mean": r.mean_fantasy_points,
                     "sd": r.standard_deviation,
                     "status": r.status,
                     "fingerprint": r.fingerprint()}
                    for r in self.iprm_results],
                "refusals": list(self.refusals),
                "warnings": list(self.warnings)}


def resolve_projection_source(league) -> str:
    """The league's configured PROJECTION source. Never its league provider.

    `League.provider` and `League.projection_source` are separate columns and
    have been since before this integration existed. This reads the second and
    never consults the first: a Yahoo-hosted league may forecast from
    BALLDONTLIE without any of its identity, roster, starter or schedule
    authority moving.
    """
    source = (getattr(league, "projection_source", None) or "").strip().lower()
    if not source:
        raise SimV2Refusal(
            "the league has no projection_source configured, and sim-v2 will "
            "not choose one for it")
    return source


def build_lineup(db, *, team_id: int, team_name: str,
                 player_ids: Sequence[int], season: int, week: int,
                 profile: ScoringProfile | str,
                 projection_source: str,
                 as_of: datetime | None = None,
                 iprm_config: I.IprmConfig = I.IPRM_V1) -> LineupBuild:
    """A roster -> simulation inputs, in ONE query plus pure arithmetic.

    Snapshots for the whole week are fetched in a single statement and scored
    in memory, so a twelve-team league week costs one query rather than one per
    starter. Every refusal is named and none is silent: a missing snapshot, an
    unresolved model and an inadmissible status each say which player and which
    cause.
    """
    from providers.component_projections import select_week

    if isinstance(profile, str):
        profile = load_profile(profile)

    if projection_source not in (PROJECTION_SOURCE_BALLDONTLIE,
                                 PROJECTION_SOURCE_YAHOO):
        raise SimV2Refusal(
            f"sim-v2 has no component path for projection_source "
            f"{projection_source!r}. The legacy "
            f"{PROJECTION_SOURCE_LEGACY!r} scalar path is sim-v1's, and it is "
            f"reached through the legacy engine rather than by this builder "
            f"pretending a scalar came through CSPS.")

    build = LineupBuild(team_id=team_id, team_name=team_name)

    snapshots = select_week(db, provider=projection_source, season=season,
                            week=week, player_ids=list(player_ids), as_of=as_of)

    # HISTORICAL MODEL PARAMETERS FOR THE WHOLE LINEUP, IN ONE PASS. The as-of
    # is the projection's own — parameters derived after the moment being priced
    # for are never in force, which is what stops a wager being priced on
    # results nobody could have known.
    from scoring.history import resolve_bundles

    parameter_as_of = as_of or max(
        [s.observed_at for s in snapshots.values() if s.observed_at]
        or [datetime.now(timezone.utc)])
    if parameter_as_of.tzinfo is None:
        parameter_as_of = parameter_as_of.replace(tzinfo=timezone.utc)
    bundles = resolve_bundles(
        db, provider=projection_source, as_of=parameter_as_of,
        subjects=[(s.provider_player_key, s.position, s.nfl_team)
                  for s in snapshots.values()],
        config=iprm_config)

    for player_id in player_ids:
        snapshot = snapshots.get(player_id)
        if snapshot is None:
            build.refusals.append(
                f"player {player_id}: no {projection_source} component "
                f"snapshot for season {season} week {week}"
                + (f" at or before {as_of.isoformat()}" if as_of else "")
                + ". sim-v2 does not substitute another provider.")
            continue

        csps_result = C.score_components(
            snapshot.components or {}, profile, mode=C.PROJECTION,
            components_present=snapshot.components_present or [],
            position=snapshot.position)
        csps_result.player_id = snapshot.player_id
        csps_result.provider = snapshot.provider
        csps_result.provider_player_key = snapshot.provider_player_key
        csps_result.season, csps_result.week = snapshot.season, snapshot.week
        csps_result.component_snapshot_id = snapshot.id
        csps_result.component_vocabulary_version = snapshot.vocabulary_version
        csps_result.observed_at = snapshot.observed_at

        result = I.project(csps_result, profile=profile,
                           components=snapshot.components or {},
                           config=iprm_config, position=snapshot.position,
                           nfl_team=snapshot.nfl_team,
                           rates=bundles.get(snapshot.provider_player_key))

        if not I.admissible(result):
            build.refusals.append(
                f"player {player_id} ({result.provider_player_key}): "
                f"{result.status} — {result.refusal or 'not admissible'}")
            continue

        build.iprm_results.append(result)
        build.starters.append(StarterLine(
            player_id=result.player_id,
            name=result.provider_player_key or str(result.player_id),
            position=result.position or "",
            projected_points=result.mean_fantasy_points,
            adjusted_points=result.mean_fantasy_points,
        ))
        build.warnings.extend(result.warnings)

    return build


def simulation_fingerprint(*, home: LineupBuild, away: LineupBuild,
                           model_config: SimModelConfig,
                           iprm_config: I.IprmConfig,
                           projection_source: str, season: int, week: int,
                           matchup_id: int) -> str:
    """A digest over everything that can move this matchup's probability.

    IT COVERS THE WHOLE CHAIN, not just the simulator: the projection source,
    every component snapshot id, the scoring profile and its version, the CSPS
    and IPRM versions, the IPRM parameter hash, the simulation model hash, the
    lineups, and every player's mean and sigma. Change any one and the digest
    changes; change nothing and a replay reproduces it exactly.

    WHAT IS EXCLUDED IS AS DELIBERATE AS WHAT IS IN. No wall-clock time, no
    calculation timestamp, no database row ordering — none of them is part of
    WHAT was computed, and including them would make an identical replay look
    like a different quote.
    """
    payload = {
        "matchup_id": matchup_id, "season": season, "week": week,
        "projection_source": projection_source,
        "sim_model_version": model_config.model_version_id,
        "sim_model_config_hash": model_config_hash(model_config),
        "iprm_version": iprm_config.iprm_version,
        "iprm_config_hash": I.iprm_config_hash(iprm_config),
        "home": [r.fingerprint() for r in home.iprm_results],
        "away": [r.fingerprint() for r in away.iprm_results],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_matchup(*, matchup_id: int, week: int,
                home: LineupBuild, away: LineupBuild,
                model_config: SimModelConfig,
                iprm_config: I.IprmConfig = I.IPRM_V1,
                projection_source: str = PROJECTION_SOURCE_BALLDONTLIE,
                season: int = 0) -> tuple:
    """Simulate one matchup from IPRM distributions. Returns (OddsResult, dict).

    THE SEED RULE IS SIM-V1'S, UNCHANGED — `matchup_id * 1000 + week`, the same
    derivation `seed_method` names in both frozen configs. Identical inputs and
    an identical seed therefore produce an identical probability, which is what
    makes a quote replayable.

    THE TIE RULE IS SIM-V1'S TOO: a strictly greater home total wins, and a tied
    trial favours neither. Both configs record it, and this counts it once.
    """
    if not home.admissible:
        raise SimV2Refusal(
            f"the home lineup is not priceable: {len(home.refusals)} "
            f"starter(s) refused", reasons=home.refusals)
    if not away.admissible:
        raise SimV2Refusal(
            f"the away lineup is not priceable: {len(away.refusals)} "
            f"starter(s) refused", reasons=away.refusals)

    rng = np.random.default_rng(seed=matchup_id * 1_000 + week)
    home_scores = simulate_team_with_sigma(home.means, home.sigmas, rng,
                                           model_config=model_config)
    away_scores = simulate_team_with_sigma(away.means, away.sigmas, rng,
                                           model_config=model_config)

    n_sims = model_config.n_sims
    home_win_prob = int((home_scores > away_scores).sum()) / n_sims
    away_win_prob = 1.0 - home_win_prob
    if abs(home_win_prob + away_win_prob - 1.0) > 1e-9:
        raise ValueError(
            f"Probability invariant violated: {home_win_prob} + "
            f"{away_win_prob} != 1.0")

    result = OddsResult(
        matchup_id=matchup_id, week=week, simulations=n_sims,
        scoring_type=model_config.scoring.scoring_type,
        home_team_id=home.team_id, home_team_name=home.team_name,
        away_team_id=away.team_id, away_team_name=away.team_name,
        home_win_prob=round(home_win_prob, 4),
        away_win_prob=round(away_win_prob, 4),
        home_moneyline=_prob_to_american(home_win_prob),
        away_moneyline=_prob_to_american(away_win_prob),
        home_proj_mean=round(float(home_scores.mean()), 2),
        away_proj_mean=round(float(away_scores.mean()), 2),
        home_proj_std=round(float(home_scores.std()), 2),
        away_proj_std=round(float(away_scores.std()), 2),
        home_starters=home.starters, away_starters=away.starters,
    )

    # THE SNAPSHOT A QUOTE WOULD FREEZE. `BeefProposal` already carries
    # `projection_input_snapshot` (JSON), `projection_source_id`,
    # `pricing_model_id` and `pricing_calc_version`, so Sprint 4 adds no table:
    # it produces the CONTENT those columns were built to hold, and Sprint 5
    # writes it at the point a price is shown.
    snapshot = {
        "projection_source_id": projection_source,
        "pricing_model_id": model_config.model_version_id,
        "pricing_calc_version": (
            f"csps={C.CSPS_VERSION};iprm={iprm_config.iprm_version}"),
        "sim_model_config_hash": model_config_hash(model_config),
        "iprm_config_hash": I.iprm_config_hash(iprm_config),
        "season": season, "week": week, "matchup_id": matchup_id,
        "home": home.as_dict(), "away": away.as_dict(),
        "fingerprint": simulation_fingerprint(
            home=home, away=away, model_config=model_config,
            iprm_config=iprm_config, projection_source=projection_source,
            season=season, week=week, matchup_id=matchup_id),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    return result, snapshot
