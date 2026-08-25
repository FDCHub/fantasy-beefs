"""
economy/points_championship.py — the Regular-Season Points Championship (WP-9).

WHAT §12 CHANGED. The legacy Skunk award paid the WHOLE pot to whoever led
regular-season Points For, split evenly if several led. The Final POR makes the
Points Championship a real three-place championship: the pot is 60/30/10 under
the one canonical split, the dead-heat rule applies to it exactly as it applies
to the other two pillars, and it settles when the regular season is final rather
than when the season closes.

── THE POT IS WHAT WAS ASSESSED, NEVER WHAT WAS PROJECTED ──────────────────

    authoritative   balance of points_championship:{league}:{season}
                    = the Skunk actually assessed this season
    projection      Weekly Skunk Fee x Regular-Season Weeks

THE PROJECTION IS A DISPLAY FIGURE AND IS NEVER POSTED. `projected_pot_cents`
exists so a settings screen can answer "what could this be worth?" in Week 1.
The two diverge for ordinary reasons: a week that ended with every matchup tied
assesses nothing (`CLASSIFICATION_NO_LOSER`), and a season may be settled before
its last week. Paying the projection would pay Credits nobody was ever charged;
posting it would let the pot disagree with the fees the league really paid, with
no way afterwards to tell which figure was right. That is why
`economy.championship_pots.mint_pot` REFUSES this pillar outright — the Points
pot is the one pot that cannot be minted.

── THE CHAMPIONSHIP EXISTS IF AND ONLY IF THE FEE IS ABOVE ZERO ────────────

§9D made Skunk Fees optional. A league that set the fee to 0 has no Points
Championship at all — not an empty one. `exists()` reads the FEE rather than the
pot balance, and the distinction is load-bearing in both directions: a league
with a real fee whose first weeks all tied has a championship whose pot happens
to be 0 so far, and a league with a 0 fee has no championship even in a week
where the pot would otherwise have grown. §20's Grand Championship then asks
about FUNDING separately, which is a third and different question.

── RANKING, AND THE ONE TIEBREAK THAT DOES NOT EXIST YET ───────────────────

Ranked on cumulative REGULAR-SEASON Points For, scaled to integer hundredths so
the comparison is exact — two GMs on 102.35 are equal here, and float equality
is never the thing deciding a championship.

§12 names a provider tiebreak between GMs level on Points For, and NO PROVIDER
STANDINGS SOURCE IS REGISTERED IN THIS BUILD. `provider_tiebreak_available()`
answers that question honestly and currently answers False. Nothing here
fabricates a provider ordering to break the tie, and nothing here refuses to
settle because of its absence: §17's dead heat is the STATED terminal outcome
for a true tie, it invents no winner, and it is what equal ranks already produce
through the canonical split. When a provider standings source is registered, it
is consulted at the seam below and a broken tie simply stops being a dead heat.

── WHEN IT SETTLES ─────────────────────────────────────────────────────────

Every regular-season week must be economically final — `finalized_at IS NOT
NULL` on every matchup, which is the one predicate §7 allows. That is what
"after regular-season provider corrections" means in a form that can be checked:
a provider correction lands as a re-finalised matchup, so a week still carrying
an unfinalised row is a week whose Points For can still move. Settling first
would award a championship on a standing that had not stopped changing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from betting.finality_gate import ResultsNotReadyError, require_week_final
from betting.pool_season_boundary import playoff_start_week
from economy.championship_distribution import distribute_championship
from economy.economy_events import (
    DOOR_SKUNK_DISTRIBUTION,
    EVENT_SKUNK_DISTRIBUTION,
    league_season_key,
    points_championship_account,
    record_event,
    wallet_account,
)
from ledger.ledger import _balance_of_in_session, post as ledger_post
from ruleset import is_final_por

#: Points For is a decimal fantasy score. Scaling by 100 and rounding to an int
#: makes the rank comparison EXACT, so a dead heat is a real equality rather
#: than an accident of float representation. The scale never leaves this module
#: and is never money.
POINTS_SCALE = 100


class PointsChampionshipError(ValueError):
    """A Points Championship operation was refused, with a stable reason."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_WRONG_ERA = "POINTS_WRONG_ERA"
REASON_NO_CHAMPIONSHIP = "POINTS_NO_CHAMPIONSHIP"
REASON_EMPTY_POT = "POINTS_EMPTY_POT"
REASON_NO_STANDINGS = "POINTS_NO_STANDINGS"
REASON_NOT_FINAL = "POINTS_REGULAR_SEASON_NOT_FINAL"
REASON_NO_WALLET = "POINTS_NO_WALLET"
REASON_LEAGUE_NOT_FOUND = "POINTS_LEAGUE_NOT_FOUND"


@dataclass(frozen=True)
class PointsChampionshipView:
    """Everything a reader needs about one league-season's Points pillar."""

    league_id: int
    season: int
    exists: bool
    skunk_fee_cents: int
    regular_season_weeks: int
    pot_cents: int
    projected_pot_cents: int
    provider_tiebreak_available: bool

    @property
    def funded(self) -> bool:
        """Whether the pillar holds money. A DIFFERENT QUESTION FROM `exists`.

        A league with a real fee whose weeks have all tied has a championship
        with nothing in it yet; §20 counts funded pillars, not configured ones.
        """
        return self.pot_cents > 0

    def as_dict(self) -> dict:
        return {
            "league_id": self.league_id,
            "season": self.season,
            "exists": self.exists,
            "funded": self.funded,
            "skunk_fee_cents": self.skunk_fee_cents,
            "regular_season_weeks": self.regular_season_weeks,
            "pot_cents": self.pot_cents,
            "projected_pot_cents": self.projected_pot_cents,
            "provider_tiebreak_available": self.provider_tiebreak_available,
        }


@dataclass(frozen=True)
class PointsChampionshipResult:
    league_id: int
    season: int
    pot_cents: int
    #: (team_id, place, award_cents, points_for), by place then canonical id.
    placements: tuple[tuple[int, int, int, float], ...]
    dead_heat: bool


def _league(db, league_id: int):
    from db.schema import League

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise PointsChampionshipError(REASON_LEAGUE_NOT_FOUND,
                                      f"league {league_id} not found")
    return league


def regular_season_week_count(db, *, league_id: int) -> int:
    """How many regular-season weeks this league plays.

    Derived from the SAME boundary the Pool engine and the Weekly Minimum use,
    so the projection below cannot be computed over a different season length
    than the one the fees are actually assessed across."""
    league = _league(db, league_id)
    return max(0, playoff_start_week(league) - int(league.start_week or 1))


def exists(db, *, league_id: int, season: int) -> bool:
    """Whether this league-season HAS a Points Championship at all (§12).

    READS THE FEE, NOT THE POT. §9D makes Skunk optional, and a league that set
    the fee to 0 has no Points Championship — not an empty one. A league with a
    real fee whose weeks have so far all tied has a championship whose pot is
    still 0, and those two must not be reported the same way.
    """
    from economy.skunk import resolve_skunk_fee_cents

    return int(resolve_skunk_fee_cents(db, league_id=league_id,
                                       season=season)) > 0


def pot_cents(db, *, league_id: int, season: int) -> int:
    """THE AUTHORITATIVE POT — the Skunk actually assessed this season."""
    db.flush()
    return _balance_of_in_session(
        db, points_championship_account(league_id, season))


def projected_pot_cents(db, *, league_id: int, season: int) -> int:
    """Weekly Skunk Fee x Regular-Season Weeks. A DISPLAY FIGURE, NEVER POSTED.

    What the pillar could be worth if every remaining week assesses a Skunk. It
    is not the pot, it is not paid, and no ledger entry is ever derived from it
    — see the module docstring for why the distinction is not cosmetic.
    """
    from economy.skunk import resolve_skunk_fee_cents

    fee = int(resolve_skunk_fee_cents(db, league_id=league_id, season=season))
    return fee * regular_season_week_count(db, league_id=league_id)


def provider_tiebreak_available(db, *, league_id: int) -> bool:
    """Whether a provider standings ordering can break a Points For tie.

    ALWAYS FALSE IN THIS BUILD, AND SAID SO PLAINLY. §12 names a provider
    tiebreak; no provider standings source is registered, no schema column
    carries a provider-stated rank, and no ingest writes one. Returning False is
    the honest answer, and it is the only one available without fabricating a
    provider ordering.

    ITS ABSENCE IS NOT A REFUSAL. §17's dead heat is the stated terminal outcome
    for a true tie and invents no winner, so an unbreakable tie is paid as a
    dead heat rather than blocking the championship. This is a SEAM: when a
    provider standings source exists, it is consulted here and in
    `_ranked_standings`, and a broken tie stops being a dead heat with no other
    code changing.
    """
    return False


def view(db, *, league_id: int, season: int) -> PointsChampionshipView:
    """Everything a reader needs, derived. Writes nothing."""
    from economy.skunk import resolve_skunk_fee_cents

    fee = int(resolve_skunk_fee_cents(db, league_id=league_id, season=season))
    weeks = regular_season_week_count(db, league_id=league_id)
    return PointsChampionshipView(
        league_id=league_id, season=season,
        exists=fee > 0,
        skunk_fee_cents=fee,
        regular_season_weeks=weeks,
        pot_cents=pot_cents(db, league_id=league_id, season=season),
        projected_pot_cents=fee * weeks,
        provider_tiebreak_available=provider_tiebreak_available(
            db, league_id=league_id),
    )


def _ranked_standings(db, *, league_id: int):
    """`(team_id, rank_value)` pairs for the canonical split, best-is-highest.

    Points For, scaled to integer hundredths. A provider tiebreak would refine
    equal values here; none is registered, so equal Points For stays equal and
    the canonical split records a dead heat.
    """
    from economy.skunk import season_points_for

    league = _league(db, league_id)
    totals = season_points_for(db, league_id=league_id, league=league)
    return (totals,
            tuple((team_id, int(round(value * POINTS_SCALE)))
                  for team_id, value in sorted(totals.items())))


def require_regular_season_final(db, *, league_id: int) -> None:
    """Refuse unless every regular-season week is economically final (§12).

    A provider correction lands as a re-finalised matchup, so a week still
    holding an unfinalised row is a week whose Points For can still move.
    `allow_empty=True` per week: a week with no matchups has nothing to
    correct, and `distribute` separately refuses a league with no finalised
    regular-season result at all.
    """
    league = _league(db, league_id)
    start = int(league.start_week or 1)
    for week in range(start, playoff_start_week(league)):
        try:
            require_week_final(
                db, league_id=league_id, week=week,
                context="Points Championship settlement", allow_empty=True)
        except ResultsNotReadyError as exc:
            raise PointsChampionshipError(REASON_NOT_FINAL, str(exc)) from exc


def distribute(db, *, league_id: int, season: int | None = None,
               now: datetime | None = None) -> PointsChampionshipResult:
    """Pay the Points Championship 60/30/10. Does NOT commit.

    Exactly-once on the league-season key it shares with the legacy Skunk
    distribution, deliberately: a league-season pays its Points pillar once,
    whichever era's arithmetic did it, and two keys would let a season that
    somehow reached both pay twice.
    """
    from db.schema import Wallet

    now = now or datetime.now(timezone.utc)
    league = _league(db, league_id)
    season = league.season if season is None else season

    if not is_final_por(db, league_id=league_id, season=season):
        raise PointsChampionshipError(
            REASON_WRONG_ERA,
            f"league {league_id} season {season} is governed by the legacy "
            f"ruleset, whose Skunk pot pays whole to the Points For leader. "
            f"Use `economy.skunk.distribute_season_skunk`.")

    if not exists(db, league_id=league_id, season=season):
        raise PointsChampionshipError(
            REASON_NO_CHAMPIONSHIP,
            f"league {league_id} season {season} sets a Weekly Skunk Fee of 0, "
            f"so it has no Points Championship to settle (§9D/§12).")

    require_regular_season_final(db, league_id=league_id)

    account = points_championship_account(league_id, season)
    db.flush()
    pot = _balance_of_in_session(db, account)
    if pot <= 0:
        raise PointsChampionshipError(
            REASON_EMPTY_POT,
            f"{account} holds {pot} cents. The Points Championship pot is the "
            f"Skunk ACTUALLY assessed; nothing was, so there is nothing to "
            f"pay. The projection is not a pot and is never distributed.")

    totals, standings = _ranked_standings(db, league_id=league_id)
    if not standings:
        raise PointsChampionshipError(
            REASON_NO_STANDINGS, f"league {league_id} has no teams to rank")
    if all(value == 0 for _, value in standings):
        raise PointsChampionshipError(
            REASON_NO_STANDINGS,
            f"league {league_id} has no finalised regular-season Points For; "
            f"refusing to award a championship on an empty standing.")

    placements = distribute_championship(pot, standings)

    # EVERY PAID GM MUST HAVE A WALLET, CHECKED BEFORE ANYTHING IS POSTED.
    # Paying a subset would leave the pot partly drained and one place unpaid,
    # with no state saying which.
    for placement in placements:
        if placement.amount_cents <= 0:
            continue
        if (db.query(Wallet)
                .filter(Wallet.team_id == placement.team_id).first()) is None:
            raise PointsChampionshipError(
                REASON_NO_WALLET,
                f"Points Championship place {placement.place} is team "
                f"{placement.team_id}, which has no wallet; refusing to pay a "
                f"subset of the podium.")

    legs = [(account, -pot)]
    legs.extend((wallet_account(p.team_id), p.amount_cents)
                for p in placements if p.amount_cents > 0)
    posting_id = ledger_post(legs, door=DOOR_SKUNK_DISTRIBUTION, session=db)

    record_event(db, event_key=league_season_key(EVENT_SKUNK_DISTRIBUTION,
                                                 league_id, season),
                 league_id=league_id, season=season,
                 event_type=EVENT_SKUNK_DISTRIBUTION, amount_cents=pot,
                 posting_id=posting_id, now=now)

    places = [p.place for p in placements]
    return PointsChampionshipResult(
        league_id=league_id, season=season, pot_cents=pot,
        placements=tuple(
            (p.team_id, p.place, p.amount_cents, totals.get(p.team_id, 0.0))
            for p in placements),
        dead_heat=len(places) != len(set(places)),
    )
