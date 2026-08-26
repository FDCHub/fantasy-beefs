"""Sprint 7 · which provider and which model answer for one league-season.

ONE PLACE ASKS THE QUESTION. Before this module the answer was compiled in;
after it, the answer is a row, and every caller reads it through here. That
matters more than it sounds: a second place that decides which provider answers
is a second place that can disagree, and a league whose odds come from one
provider while its screen shows another is worse than a league on the old path.

── ABSENCE IS THE DEFAULT, AND THE DEFAULT IS TODAY'S BEHAVIOUR ────────────

`resolve()` on a league-season with no configuration row returns `legacy`
projections, `legacy` facts and sim-v1 — what the product does now, byte for
byte. `legacy` is a real value, not a placeholder: for projections it means
"keep reading `leagues.projection_source` and the scalar `projections` table",
which is the selector that already exists. Nothing auto-detects, nothing infers
from the presence of a BALLDONTLIE credential, and nothing upgrades a league
because its snapshots happen to exist. A league moves when an operator moves it.

── NO SILENT FALLBACK. THIS IS THE WHOLE POINT OF THE MODULE. ──────────────

A league configured for BALLDONTLIE projections that cannot get them does NOT
quietly get Yahoo's. `require_projection_source` and `require_factual_source`
raise `ProviderSelectionError` naming the provider that was asked for and the
one that was offered. A price built from a provider the operator did not choose
is wrong even when the arithmetic is right, and it is wrong in the worst
possible way: invisibly, and with a confident number attached.

The inverse is equally forbidden. A legacy-configured league must not be handed
BALLDONTLIE values because a snapshot happened to be available.

── ROLLBACK CHANGES A SELECTION, NOT A HISTORY ─────────────────────────────

Moving a league back rewrites one row. Component snapshots, factual evidence,
derived parameters and graded results all stay exactly where they are and stay
replayable. Nothing here deletes anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["ProviderSelection", "ProviderSelectionError", "resolve",
           "require_projection_source", "require_factual_source",
           "require_scoring_profile", "resolve_model_version",
           "set_selection", "LEGACY"]


class ProviderSelectionError(RuntimeError):
    """A caller asked for one provider and was offered another. Never recovered from."""


@dataclass(frozen=True)
class ProviderSelection:
    """What answers for one league-season, and whether anyone said so."""

    league_id: Any
    season: int
    projection_source: str
    factual_source: str
    simulation_model: str
    #: False when no configuration row exists — the league is on the defaults.
    configured: bool = False
    note: str | None = None
    #: Sprint 7B — the CSPS profile this league is scored by. None on the legacy
    #: path, where sim-v1 uses its own frozen scoring tables and no profile is
    #: consulted. None on the BALLDONTLIE path is a REFUSAL, never a default:
    #: see `require_scoring_profile`.
    scoring_profile_id: str | None = None

    @property
    def uses_legacy_projections(self) -> bool:
        return self.projection_source == "legacy"

    @property
    def uses_balldontlie_projections(self) -> bool:
        return self.projection_source == "balldontlie"

    @property
    def uses_balldontlie_facts(self) -> bool:
        return self.factual_source == "balldontlie"

    @property
    def uses_sim_v2(self) -> bool:
        return self.simulation_model == "sim-v2"

    def as_dict(self) -> dict:
        return {"league_id": self.league_id, "season": self.season,
                "projection_source": self.projection_source,
                "factual_source": self.factual_source,
                "simulation_model": self.simulation_model,
                "configured": self.configured, "note": self.note,
                "scoring_profile_id": self.scoring_profile_id}


def _defaults(league_id, season) -> ProviderSelection:
    from db.schema import LeagueProviderConfig as C

    return ProviderSelection(
        league_id=league_id, season=int(season),
        projection_source=C.DEFAULT_PROJECTION_SOURCE,
        factual_source=C.DEFAULT_FACTUAL_SOURCE,
        simulation_model=C.DEFAULT_SIMULATION_MODEL,
        configured=False)


#: What every unconfigured league-season gets. Exported so a caller can state
#: the default explicitly rather than reconstructing it.
def LEGACY(league_id=None, season=0) -> ProviderSelection:      # noqa: N802
    return _defaults(league_id, season)


def resolve(db, *, league_id, season: int) -> ProviderSelection:
    """The configured selection, or today's behaviour if nobody configured one.

    NEVER RAISES FOR AN UNCONFIGURED LEAGUE. Absence is a governed state, not an
    error: the overwhelming majority of leagues have no row and must keep
    working exactly as they do.
    """
    from db.schema import LeagueProviderConfig as C

    row = (db.query(C)
           .filter(C.league_id == league_id, C.season == int(season))
           .one_or_none())
    if row is None:
        return _defaults(league_id, season)
    return ProviderSelection(
        league_id=league_id, season=int(season),
        projection_source=row.projection_source,
        factual_source=row.factual_source,
        simulation_model=row.simulation_model,
        configured=True, note=row.note,
        scoring_profile_id=getattr(row, "scoring_profile_id", None))


def set_selection(db, *, league_id, season: int,
                  projection_source: str | None = None,
                  factual_source: str | None = None,
                  simulation_model: str | None = None,
                  scoring_profile_id: str | None = None,
                  note: str | None = None,
                  updated_by: str | None = None) -> ProviderSelection:
    """Create or update one league-season's selection. The activation act.

    ROLLBACK USES THIS SAME FUNCTION. Moving a league back to legacy behaviour
    is a write of `legacy`/`legacy`/`sim-v1` here — it deletes no snapshot, no
    factual evidence and no graded result, so a league can be moved back and
    forward without losing anything either direction produced.
    """
    from db.schema import LeagueProviderConfig as C

    row = (db.query(C)
           .filter(C.league_id == league_id, C.season == int(season))
           .one_or_none())
    if row is None:
        row = C(league_id=league_id, season=int(season),
                projection_source=C.DEFAULT_PROJECTION_SOURCE,
                factual_source=C.DEFAULT_FACTUAL_SOURCE,
                simulation_model=C.DEFAULT_SIMULATION_MODEL)
        db.add(row)
    if projection_source is not None:
        row.projection_source = projection_source
    if factual_source is not None:
        row.factual_source = factual_source
    if simulation_model is not None:
        row.simulation_model = simulation_model
    if scoring_profile_id is not None:
        row.scoring_profile_id = scoring_profile_id
    if note is not None:
        row.note = note
    if updated_by is not None:
        row.updated_by = updated_by
    db.flush()
    return resolve(db, league_id=league_id, season=season)


def require_projection_source(selection: ProviderSelection, offered: str,
                              *, context: str = "projection") -> None:
    """Refuse a value produced by a provider this league did not choose.

    Called at the moment a value is about to be USED, not merely fetched, so
    the check sits between the data and the price rather than beside it.
    """
    if offered != selection.projection_source:
        raise ProviderSelectionError(
            f"league {selection.league_id} season {selection.season} is "
            f"configured for {selection.projection_source!r} {context}s and was "
            f"offered {offered!r}. There is no fallback between providers: a "
            f"projection from a source the operator did not choose is not a "
            f"substitute for one they did.")


def require_factual_source(selection: ProviderSelection, offered: str,
                           *, context: str = "factual") -> None:
    """The same refusal for results. A settled wager cannot be un-settled."""
    if offered != selection.factual_source:
        raise ProviderSelectionError(
            f"league {selection.league_id} season {selection.season} is "
            f"configured for {selection.factual_source!r} {context} evidence "
            f"and was offered {offered!r}. Results are not interchangeable "
            f"between providers, and a wager settled on the wrong one cannot be "
            f"un-settled.")


def require_scoring_profile(selection: ProviderSelection):
    """The league's CSPS profile, loaded — or a refusal naming the league.

    THERE IS NO HOUSE PROFILE AND THERE MUST NOT BE. CSPS converts components
    into points under one league's certified rule set, and the two profiles
    this repository ships disagree on real subjects: a Titans defence holding an
    opponent to a given band scores -1.00 under one and something else under the
    other. Choosing one on a league's behalf would produce a confident price
    under rules nobody adopted, which is the same class of error as reading the
    wrong provider — and equally invisible.

    So an unconfigured profile refuses, by name, at the point a price is asked
    for rather than at the point a row is written: activation is allowed to
    proceed in stages, and a league with projections switched on but no profile
    yet is a coherent intermediate state that must simply not price.
    """
    from scoring.profile import ProfileError, load_profile

    profile_id = (selection.scoring_profile_id or "").strip()
    if not profile_id:
        raise ProviderSelectionError(
            f"league {selection.league_id} season {selection.season} is "
            f"configured for {selection.projection_source!r} projections but "
            f"names no scoring profile. CSPS scores components under a "
            f"league's own certified rules and there is no default set to "
            f"fall back on — set scoring_profile_id on its "
            f"league_provider_config row.")
    try:
        return load_profile(profile_id)
    except ProfileError as exc:
        raise ProviderSelectionError(
            f"league {selection.league_id} season {selection.season} names "
            f"scoring profile {profile_id!r}, which could not be loaded: "
            f"{exc}") from exc


def resolve_model_version(selection: ProviderSelection):
    """The frozen model configuration this league prices with.

    LEAGUE-SCOPED, NOT GLOBAL. `ACTIVE_MODEL_VERSION_ID` stays exactly where it
    is and keeps meaning "what an unconfigured caller gets"; this reads the
    league's own choice and resolves it through the same frozen registry, so
    sim-v1's hash is verified on every use and two leagues on two models cannot
    contaminate each other — there is no shared mutable state to contaminate.
    """
    from odds.model_registry import resolve_model_config

    return resolve_model_config(selection.simulation_model)
