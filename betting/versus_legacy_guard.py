"""
Legacy single-GM wager path — fail-closed guard (RC2 NEW-1).

THE DEFECT THIS CLOSES. The repository carries two live paths that create a
`Bet` row and post under the `wager_placed` door:

    legacy   POST /bets/place -> betting.bet_engine._place_bet
             (a plain single-GM wager: `beef_challenge_id IS NULL`)
    governed beefs.beef_engine / economy.challenge_funding
             (a FantasyStakes matchup: `beef_challenge_id` set, two GMs)

FANTASYSTAKES HAS NO HOUSE. The product is GM-versus-GM matchups and GM-entered
prop pools; there is no GM-versus-house wagering product. A plain single-GM
wager is therefore not FantasyStakes competition, and a governed FantasyStakes
league must not be able to create one.

WHY A GUARD RATHER THAN DELETING THE ROUTE. The legacy path predates the
FantasyStakes economy and is still exercised by certified RC1 suites against
leagues that carry no FantasyStakes governance state at all. Retiring it
outright is not this change's scope, and would rewrite history those suites
assert. This is a fail-closed interlock between two products, exactly as
`betting/pool_legacy_guard.py` is between two Pool engines.

WHY THE GUARD IS LEAGUE-SCOPED. Governance is a property of the LEAGUE, not of a
week or a wallet. A league running the FantasyStakes economy runs it for the
whole season; permitting a plain wager on one week of it would put credits into
`escrow:{bet_id}` that no FantasyStakes matchup owns.

WHERE IT IS APPLIED, AND WHY BOTH PLACES. Called from the mounted HTTP handler
(`POST /bets/place`) AND from the top of `_place_bet`, which is the single funnel
every one of the four single-party entry points passes through. The router is the
smallest boundary for the reachable path today; the funnel is what protects a
future scheduler, management command or direct caller that never goes through
FastAPI. Neither placement rewrites the legacy engine.

A LEAGUE WITH NO FANTASYSTAKES GOVERNANCE IS UNAFFECTED. With none of the
markers below the guard is a no-op and the legacy engine behaves exactly as
before, which is why the existing legacy suites still pass unchanged.
"""

from __future__ import annotations


class LegacyVersusPathRefused(ValueError):
    """A legacy single-GM wager entry point was invoked for a governed league.

    Subclasses ValueError deliberately: `POST /bets/place` already maps
    ValueError to HTTP 400, so the refusal surfaces as a clean client error
    rather than a 500, without the handler being restructured.
    """

    def __init__(self, league_id: int, markers) -> None:
        self.league_id = league_id
        self.markers = tuple(markers)
        super().__init__(
            f"Refusing the legacy single-GM wager path for league {league_id}: "
            f"this league is governed by FantasyStakes. Governance evidence: "
            f"{'; '.join(self.markers)}. FantasyStakes competition is GM-versus-GM "
            f"matchups and prop pools; there is no house and no single-GM wagering "
            f"product, so a plain wager here would move Credits that no "
            f"FantasyStakes matchup owns and that no Championship Score counts. "
            f"Use a FantasyStakes matchup challenge instead."
        )


def fantasystakes_governance_markers(db, league_id: int) -> tuple[str, ...]:
    """Durable, league-scoped evidence that `league_id` is FantasyStakes-governed.

    READ-ONLY. Returns an empty tuple for a league carrying no FantasyStakes
    state at all, which is what keeps the guard inert for legacy-only leagues.

    ORDERED FROM EARLIEST TO LATEST in a league's FantasyStakes lifetime:

      1. `league_season_economy_config` — the commissioner configured the
         FantasyStakes weekly economy (weekly minimum, championship
         contribution, skunk fee) for a season of this league. This is the
         earliest durable statement of intent and the one that actually closes
         the gap, because it exists before any Credit has moved.
      2. `fantasystakes_championship_config` — the RC2 FantasyStakes
         Championship contribution was configured or frozen.
      3. `fantasystakes_championship_allocation` — the fixed FantasyStakes
         Championship Pot was funded at activation.
      4. `fantasystakes_championship_freeze` — the Championship Score was
         frozen at the regular-season boundary.

    `SeasonAllocation` IS DELIBERATELY NOT A MARKER. It is written by the
    pre-FantasyStakes buy-in gate as well, so keying on it would refuse leagues
    that never adopted the FantasyStakes economy — and would break certified RC1
    suites that grant an allocation row purely to satisfy that gate. Intent to
    run FantasyStakes is recorded by (1), not by the presence of an advance.

    KNOWN BOUNDARY, STATED RATHER THAN PAPERED OVER. A league that has never
    been configured for the FantasyStakes economy and has never activated a
    championship carries no durable FantasyStakes state, so nothing here can
    fire for it — it is indistinguishable from a legacy league at the schema
    level, because no FantasyStakes intent was ever recorded. Such a league has
    no Championship Score to corrupt: it has no pot, no contribution and no
    frozen field.
    """
    from sqlalchemy import inspect as sa_inspect

    from db.schema import LeagueSeasonEconomyConfig

    markers: list[str] = []

    # Marker 1 lives on an RC1 table, so it is always readable. It is also the
    # marker that carries the guard: a league running the FantasyStakes economy
    # is refused even on a database that predates every RC2 table below.
    seasons = [r[0] for r in
               db.query(LeagueSeasonEconomyConfig.season)
               .filter(LeagueSeasonEconomyConfig.league_id == league_id)
               .distinct().order_by(LeagueSeasonEconomyConfig.season).all()]
    if seasons:
        markers.append(f"league_season_economy_config seasons={seasons}")

    # Imported inside the function: these are additive RC2 models whose
    # registration order `api.main_rc2` owns explicitly, and `betting` must not
    # take a module-import-time dependency on them.
    from economy.fantasystakes_championship_allocation import (
        FantasyStakesChampionshipAllocation, FantasyStakesChampionshipConfig,
    )
    from reports.championship_read_model import FantasyStakesChampionshipFreeze

    # A DATABASE WITHOUT AN RC2 TABLE HAS NO ROWS IN IT — that is a correct
    # reading of absence, not a suppressed error, and it is checked explicitly
    # rather than by catching whatever the driver raises. RC1-era databases
    # (including the certified RC1 suites' fixtures) build only `db.schema.Base`
    # and never register the RC2 models, so these tables genuinely do not exist
    # there. Marker 1 above still fires for such a database if the league runs
    # the FantasyStakes economy, so this cannot open the guard on a governed
    # league — it only stops the guard from crashing on a pre-RC2 schema.
    inspector = sa_inspect(db.get_bind())
    for model, label in ((FantasyStakesChampionshipConfig,
                          "fantasystakes_championship_config"),
                         (FantasyStakesChampionshipAllocation,
                          "fantasystakes_championship_allocation"),
                         (FantasyStakesChampionshipFreeze,
                          "fantasystakes_championship_freeze")):
        if not inspector.has_table(model.__tablename__):
            continue
        rows = db.query(model).filter(model.league_id == league_id).count()
        if rows:
            markers.append(f"{label} rows={rows}")

    return tuple(markers)


def assert_legacy_wager_path_allowed(db, league_id: int | None) -> None:
    """Refuse the legacy single-GM wager path for a FantasyStakes league.

    Raises BEFORE any validation, any wallet lock, any `Bet` row and any ledger
    posting, so a refused attempt leaves no trace of any kind.

    A `league_id` of None means the caller could not resolve a league for this
    wager. That is not a governed league by definition, so the guard stays inert
    rather than inventing a refusal; the legacy engine's own validation owns
    that case.
    """
    if league_id is None:
        return
    markers = fantasystakes_governance_markers(db, int(league_id))
    if markers:
        raise LegacyVersusPathRefused(int(league_id), markers)
