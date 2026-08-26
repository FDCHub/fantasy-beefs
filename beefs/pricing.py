"""Sprint 7B · which projections and which simulator price one league's week.

THE PROBLEM THIS MODULE EXISTS TO SOLVE. Six sprints built a certified pricing
chain — persisted BALLDONTLIE components, CSPS under a league's own rules,
IPRM-v2 uncertainty, sim-v2 — and nothing in the running product could reach
it. `beefs/beef_engine` read a FantasyPros scalar out of `projections` and
priced it with sim-v1, for every league, unconditionally. Sprint 7 made the
CHOICE representable; this module makes the choice REACHABLE.

── IT IS A SEAM, NOT A SECOND ENGINE ───────────────────────────────────────

There is one market board builder, one American-odds conversion, one spread
construction, one total construction, one quote lifecycle. This module produces
the two SCORE DISTRIBUTIONS and the starter lines that go into them, and hands
them to the machinery that already exists. Everything downstream of
`matchup_scores` — `odds/market_lines`, `_prob_to_american`, the board, the
quote, Dynamic, Final Lock — is untouched and shared by both paths.

Concretely, two functions in `beef_engine` change and no others:

    _fetch_starters_for_odds    WHERE the per-starter numbers come from
    simulate_matchup_scores     WHICH simulator turns them into distributions

Both were already the single place their concern was answered, which is why the
adapter is this small.

── THE DISPLAY AND THE PRICE COME FROM ONE READ ────────────────────────────

`reports/matchup_preview_read_model` builds the lineup a GM SEES from
`_fetch_starters_for_odds`, and `compute_market_board` prices from the same
call. Routing both through this module is what makes a mixed-provider board
unrepresentable rather than merely discouraged: there is no second read that
could answer differently, so a BALLDONTLIE league cannot show Yahoo's
projections beside BALLDONTLIE's odds. That is Sprint 7B §13, enforced by
construction.

── THE FOUR COMBINATIONS, AND WHY TWO OF THEM REFUSE ───────────────────────

    legacy      + sim-v1    supported. Byte-for-byte the existing behaviour:
                            this module resolves, sees the defaults, and gets
                            out of the way.

    balldontlie + sim-v2    supported. The certified chain.

    balldontlie + sim-v1    REFUSED. sim-v1's `_adjust_for_scoring` converts a
                            FantasyPros PPR scalar into the model's scoring
                            system using position-average tables. A CSPS mean
                            has ALREADY been scored under the league's rules,
                            so running it through that conversion would score it
                            twice — the double-conversion hazard `MODEL_V2`'s
                            own commentary names. The result would not error; it
                            would be quietly, plausibly wrong.

    legacy      + sim-v2    REFUSED. sim-v2 reads component snapshots. There are
                            none for `fantasypros`, and `build_lineup` already
                            says so. Naming the refusal here means an operator
                            meets it when they set the combination, not as an
                            unexplained empty board later.

Both refusals are `PricingRefusal`, which is a `ValueError`, so the routes'
existing governed refusal vocabulary carries them to a GM as a product sentence
rather than a stack trace.

── NO NETWORK, EVER, ON THIS PATH ──────────────────────────────────────────

A market board is drawn on page load. This module reads
`provider_component_projection` rows a refresh already persisted and never
reaches BALLDONTLIE; a UI request cannot trigger acquisition, and a hundred
leagues looking at their boards cost the provider nothing. Sprint 7B §§21, 27,
28.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["PricingPlan", "PricingRefusal", "resolve_plan",
           "component_starters", "matchup_scores", "REASON_CODES"]


class PricingRefusal(ValueError):
    """This league-season cannot be priced as configured. Never recovered from.

    A `ValueError` deliberately: `_market_board_or_refuse` and the quote route
    already map that to a governed product refusal, so a refusal here reaches a
    GM through the vocabulary they already meet rather than through a new one.
    `reason_code` lets the route name it precisely instead of falling back to
    the generic `cannot_price`.
    """

    def __init__(self, message: str, *, reason_code: str = "cannot_price",
                 detail: Any = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.detail = detail


#: The refusal vocabulary this module can produce. Closed, and named so an
#: operator diagnostic can enumerate the causes rather than string-match them.
REASON_CODES = (
    "unsupported_model_combination",
    "scoring_profile_unconfigured",
    "projection_snapshot_unavailable",
    "projection_not_admissible",
)


@dataclass
class PricingPlan:
    """What answers for one league-season's pricing, resolved once.

    RESOLVED ONCE PER BOARD, NOT ONCE PER TEAM. Both sides of a Versus pairing
    are members of one league by the time anything is priced, so one plan
    governs both — which is also what makes it impossible for a pairing to be
    priced with one side's projections and the other side's model.
    """

    selection: Any
    league_id: Any = None
    season: int = 0
    #: The frozen `SimModelConfig` this league prices under, resolved through
    #: the registry so sim-v1's content hash is verified on every use.
    model_config: Any = None
    #: The CSPS profile, loaded. None on the legacy path, where no profile is
    #: consulted at all.
    profile: Any = None
    #: The IPRM configuration. The certified default; this sprint calibrates
    #: nothing and introduces no parameter of its own.
    iprm_config: Any = None
    #: Per-team `LineupBuild`s, filled in by `component_starters` and read by
    #: `matchup_scores`. The build carries the IPRM sigmas, and a sigma per
    #: player is the entire reason sim-v2 exists — passing only the means would
    #: silently reduce it to sim-v1 with different inputs.
    builds: dict = field(default_factory=dict)

    @property
    def uses_components(self) -> bool:
        """Whether this league prices from the BALLDONTLIE component chain."""
        return bool(self.selection and
                    self.selection.uses_balldontlie_projections)

    def provenance(self) -> dict:
        """What produced this board, for a response or an operator read.

        NO SECRET IS REPRESENTABLE HERE. Every value is a vocabulary string, a
        version id or a content hash of a frozen config — there is no
        credential, no header and no provider payload on this path to leak.
        """
        from odds.model_registry import model_config_hash

        return {
            "projection_source": self.selection.projection_source,
            "factual_source": self.selection.factual_source,
            "simulation_model": self.selection.simulation_model,
            "selection_configured": self.selection.configured,
            "scoring_profile_id": (self.profile.profile_id
                                   if self.profile else None),
            "scoring_profile_version": (self.profile.version
                                        if self.profile else None),
            "iprm_version": (self.iprm_config.iprm_version
                             if self.iprm_config else None),
            "model_config_hash": (model_config_hash(self.model_config)
                                  if self.model_config else None),
        }


def resolve_plan(db, *, team_id, week: int) -> PricingPlan:
    """The pricing plan governing this team's league. Resolved from a ROW.

    ONE QUERY, AND IT NEVER RAISES FOR AN UNCONFIGURED LEAGUE. Absence is the
    governed default — legacy projections, sim-v1 — so the overwhelming
    majority of leagues take this function's cheapest path and come out with
    exactly the behaviour they had before Sprint 7 existed.

    THE REFUSALS FIRE HERE, AT RESOLUTION, and not deeper in. An unsupported
    combination is a configuration error, not a data error, and meeting it at
    the moment the plan is built means the operator sees it on the first board
    they open rather than after a page of arithmetic.
    """
    from db.schema import Team

    from beefs.beef_engine import projection_context_for_team
    from providers.selection import (
        require_scoring_profile,
        resolve as resolve_selection,
        resolve_model_version,
    )

    ctx = projection_context_for_team(db, team_id)
    league_id = None
    if team_id is not None:
        team = db.query(Team).filter(Team.id == team_id).one_or_none()
        league_id = getattr(team, "league_id", None) if team else None

    selection = resolve_selection(db, league_id=league_id, season=ctx.season)
    plan = PricingPlan(selection=selection, league_id=league_id,
                       season=ctx.season)

    uses_components = selection.uses_balldontlie_projections
    if uses_components != selection.uses_sim_v2:
        raise PricingRefusal(
            f"league {league_id} season {ctx.season} is configured for "
            f"{selection.projection_source!r} projections with "
            f"{selection.simulation_model!r}. That combination has no defined "
            f"semantics: sim-v1 re-scores a FantasyPros scalar with its own "
            f"frozen tables and would score a CSPS total a second time, while "
            f"sim-v2 reads component snapshots that the legacy scalar path "
            f"does not produce. Configure legacy/sim-v1 or "
            f"balldontlie/sim-v2.",
            reason_code="unsupported_model_combination")

    plan.model_config = resolve_model_version(selection)
    if uses_components:
        # RAISES `ProviderSelectionError` WHEN NO PROFILE IS NAMED. Re-raised as
        # a PricingRefusal so every failure a board can meet on this path is one
        # exception type with one reason vocabulary.
        from providers.selection import ProviderSelectionError
        from scoring import iprm as I

        try:
            plan.profile = require_scoring_profile(selection)
        except ProviderSelectionError as exc:
            raise PricingRefusal(
                str(exc),
                reason_code="scoring_profile_unconfigured") from exc
        plan.iprm_config = I.IPRM_V1
    return plan


def component_starters(db, plan: PricingPlan, *, team_id: int,
                       player_ids, team_name: str = "", week: int):
    """One team's starters, priced through CSPS and IPRM-v2. One query of rows.

    THE ROSTER IS THE LEGACY PATH'S ROSTER, deliberately. `player_ids` is
    whatever `_fetch_starters_for_odds` selected — the first `N_START` `Roster`
    slots by id — so switching a league's PROJECTION source does not silently
    also change WHO is considered a starter. Yahoo remains authoritative for
    that, exactly as the responsibility split says.

    EVERY REFUSAL IS THE LINEUP'S. `build_lineup` refuses a starter with no
    snapshot and a starter whose IPRM result is inadmissible, and one refused
    starter refuses the team: a total missing a starter is not a smaller total,
    it is a wrong one, and it would price a wager. This function converts that
    into the product's refusal vocabulary and adds no leniency of its own.

    :returns: `(starters, points_snapshot)` — `PlayerProj` rows for display and
              staleness, with the build itself parked on the plan for the draw.
    """
    from odds import sim_v2
    from odds.odds_engine_headless import PlayerProj

    build = sim_v2.build_lineup(
        db, team_id=team_id, team_name=team_name or str(team_id),
        player_ids=list(player_ids), season=plan.season, week=week,
        profile=plan.profile,
        projection_source=sim_v2.PROJECTION_SOURCE_BALLDONTLIE,
        iprm_config=plan.iprm_config)

    if build.refusals:
        missing = [r for r in build.refusals if "component snapshot" in r]
        raise PricingRefusal(
            f"team {team_id} cannot be priced for week {week}: "
            f"{len(build.refusals)} starter(s) refused. "
            + " | ".join(build.refusals[:4]),
            reason_code=("projection_snapshot_unavailable" if missing
                         else "projection_not_admissible"),
            detail=list(build.refusals))

    plan.builds[team_id] = build

    # THE DISPLAYED NUMBER IS THE PRICED NUMBER. `projected_points` here is the
    # IPRM mean in the league's own scoring units — the very value
    # `matchup_scores` centres this player's distribution on. It is NOT a
    # FantasyPros scalar and is never fed to `_adjust_for_scoring`; the v2 draw
    # takes means and sigmas directly, which is what keeps the conversion from
    # happening twice.
    starters, snapshot = [], {}
    for result in build.iprm_results:
        starters.append(PlayerProj(
            player_id=result.player_id,
            name=result.provider_player_key or str(result.player_id),
            position=result.position or "",
            projected_points=round(float(result.mean_fantasy_points), 4),
            # INJURY STATUS IS DELIBERATELY None ON THIS PATH. sim-v1 applies a
            # multiplier from its frozen table before re-scoring; sim-v2 does
            # not, because IPRM already produced the distribution and applying a
            # second haircut here would be an unversioned probability change.
            injury_status=None))
        snapshot[str(result.player_id)] = round(
            float(result.mean_fantasy_points), 4)
    return starters, snapshot


def matchup_scores(plan: PricingPlan, inputs, week: int):
    """The pairing's two score distributions, from the configured simulator.

    ORIENTATION IS HANDLED THE SAME WAY ON BOTH PATHS, and it has to be: the
    seed is derived from identity, so `(A, B)` and `(B, A)` are different draws
    of one matchup. A scheduled pairing is oriented to canonical home/away and
    seeded from the matchup id; an unscheduled one is seeded from the team pair.
    Those are `matchup_seed`'s two branches — the rule both frozen configs name
    — and sim-v2 obeys it rather than inventing a second convention.

    :returns: `(challenger_scores, challenged_scores)`
    """
    from odds import sim_v2

    ch_build = plan.builds.get(inputs.challenger_team_id)
    cd_build = plan.builds.get(inputs.challenged_team_id)
    if ch_build is None or cd_build is None:
        raise PricingRefusal(
            f"no component build for one side of "
            f"{inputs.challenger_team_id} vs {inputs.challenged_team_id}. A "
            f"sim-v2 draw needs the IPRM sigmas the build carries, and pricing "
            f"from the means alone would be sim-v1 wearing sim-v2's name.",
            reason_code="projection_snapshot_unavailable")

    if inputs.shared_matchup_id is not None:
        if inputs.challenger_is_home:
            home, away = ch_build, cd_build
        else:
            home, away = cd_build, ch_build
        raw_home, raw_away = sim_v2.matchup_score_arrays(
            home=home, away=away, model_config=plan.model_config, week=week,
            matchup_id=inputs.shared_matchup_id)
        return ((raw_home, raw_away) if inputs.challenger_is_home
                else (raw_away, raw_home))

    return sim_v2.matchup_score_arrays(
        home=ch_build, away=cd_build, model_config=plan.model_config,
        week=week, home_team_id=inputs.challenger_team_id,
        away_team_id=inputs.challenged_team_id)
