"""
economy/grand_championship.py — the Grand Championship (WP-14, Final POR §20).

WHAT §20 REPLACES. The RC2 recognition awarded 3/2/1 points for finishing 1st,
2nd or 3rd in each of two component championships and named whoever accumulated
most. The Final POR makes the Grand Championship a VIRTUAL-CREDIT TOTAL: a GM's
Grand Total is the championship Credits they actually won, summed across every
FUNDED pillar.

    Grand Total(GM) = Σ championship VC awarded to that GM, over funded pillars

── WHY VC AND NOT POINTS ──────────────────────────────────────────────────

Points made every pillar worth the same regardless of what it was worth. A
league with a $10 Fantasy Football pot and a $200 FantasyStakes pot gave 3
points for winning either, so the Grand Champion could be the GM who won the
small one twice. Under §20 the pillars are weighted by what the league actually
put into them, which is the thing the league itself decided.

It also means the Grand Championship needs no arithmetic of its own. There is no
scale, no normalisation and no exchange rate: it sums awards that other packages
already posted, in the same unit they were posted in.

── AT LEAST TWO FUNDED PILLARS ────────────────────────────────────────────

§20 requires two. With one, the Grand Champion is by definition whoever won that
pillar, and naming them again as a second, grander title is a distinction with
no content. `funded_pillars` counts pillars that EVER held money — not pillars
that hold money now — because a distributed pot holds zero and that is precisely
when the Grand Championship needs to count it.

FUNDED IS NOT THE SAME AS CONFIGURED. A Points Championship exists whenever the
Skunk Fee is above 0 (§12) but is funded only once a Skunk is actually assessed;
a Fantasy Football pot set to 0 is configured and unfunded. Both correctly fail
to count.

── THE THREE LIFECYCLE STATES §20 ASKS FOR ────────────────────────────────

    PLACEHOLDER  regular season — no rows at all
    LIVE         postseason, built from whatever components are FINALIZED
    FINAL        every funded pillar has paid; the totals cannot move again

PLACEHOLDER RETURNS NO ROWS, NOT ZEROED ONES. A table of GMs on 0 invites a
reader to compare them, and during the regular season there is nothing to
compare: no pillar has finalized and no championship Credit has been awarded.
A row asserting a GM is level with every other is a claim, and it would be false.

LIVE IS BUILT FROM FINALIZED COMPONENTS ONLY. A pillar that has not paid
contributes nothing — not a projection, not its pot, not a provisional podium.
That is what "live using finalized components" means: the total is real at every
moment, and it only ever grows as pillars land.

── A TIED TOTAL IS A DEAD HEAT, AND NOTHING BREAKS IT ─────────────────────

§20: co-Grand Champions, no tiebreak. The RC2 model broke ties on the
FantasyStakes Championship Score; that is retired with the rest of it. Two GMs
who won the same number of Credits have achieved the same thing, and inventing a
separator would decide a title on a rule the product does not have.

── NOTHING HERE POSTS ─────────────────────────────────────────────────────

The Grand Championship is a RECOGNITION. Every Credit it counts was already
awarded by the pillar that awarded it and is already in a Wallet; paying again
would double it. This module reads and returns, and writes nothing at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from economy.economy_events import CHAMPIONSHIP_PILLARS
from ruleset import is_final_por

#: Regular season: the Grand Championship exists as a concept and has no rows.
GRAND_PLACEHOLDER = "PLACEHOLDER"
#: Postseason: totals built from the pillars that have finalized so far.
GRAND_LIVE = "LIVE"
#: Every funded pillar has paid. The totals cannot move again.
GRAND_FINAL = "FINAL"

GRAND_STATES: tuple[str, ...] = (GRAND_PLACEHOLDER, GRAND_LIVE, GRAND_FINAL)

#: §20's bar. Named rather than written as a literal at the comparison, so the
#: rule is greppable and cannot be changed by editing a `2` in a condition.
MINIMUM_FUNDED_PILLARS = 2


class GrandChampionshipError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_WRONG_ERA = "GRAND_WRONG_ERA"
REASON_LEAGUE_NOT_FOUND = "GRAND_LEAGUE_NOT_FOUND"


@dataclass(frozen=True)
class GrandRow:
    team_id: int
    #: Championship Credits won, per pillar. Absent pillars are simply 0.
    by_pillar: dict[str, int]
    total_cents: int


@dataclass(frozen=True)
class GrandChampionshipView:
    league_id: int
    season: int
    state: str
    #: Pillars that ever held money. §20 requires at least two.
    funded_pillars: tuple[str, ...]
    #: Funded pillars that have actually paid out.
    finalized_pillars: tuple[str, ...]
    #: Empty in PLACEHOLDER. Ordered by total descending, then team id.
    rows: tuple[GrandRow, ...]
    #: Every GM on the top total. More than one is a dead heat.
    champion_team_ids: tuple[int, ...]

    @property
    def meets_pillar_minimum(self) -> bool:
        return len(self.funded_pillars) >= MINIMUM_FUNDED_PILLARS

    @property
    def co_champions(self) -> bool:
        """A tied TOTAL, decided by nothing. §20: no tiebreak."""
        return len(self.champion_team_ids) > 1

    def as_dict(self) -> dict:
        return {
            "league_id": self.league_id,
            "season": self.season,
            "state": self.state,
            "funded_pillars": list(self.funded_pillars),
            "finalized_pillars": list(self.finalized_pillars),
            "meets_pillar_minimum": self.meets_pillar_minimum,
            "rows": [{"team_id": r.team_id, "by_pillar": dict(r.by_pillar),
                      "total_cents": r.total_cents} for r in self.rows],
            "champion_team_ids": list(self.champion_team_ids),
            "co_champions": self.co_champions,
        }


def _league(db, league_id: int):
    from db.schema import League

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise GrandChampionshipError(REASON_LEAGUE_NOT_FOUND,
                                     f"league {league_id} not found")
    return league


def funded_pillars(db, *, league_id: int, season: int) -> tuple[str, ...]:
    """Pillars that EVER held money, in canonical order.

    NOT A BALANCE TEST. A distributed pot holds zero, and that is exactly when
    the Grand Championship needs to count it — see the module docstring.
    """
    from economy.championship_pots import pillar_funded_cents

    return tuple(p for p in CHAMPIONSHIP_PILLARS
                 if pillar_funded_cents(db, pillar=p, league_id=league_id,
                                        season=season) > 0)


def finalized_pillars(db, *, league_id: int, season: int) -> tuple[str, ...]:
    """Funded pillars that have actually paid a GM.

    A PILLAR IS FINALIZED WHEN IT HAS AWARDED CREDITS, which is the only
    condition under which it can contribute to a Grand Total at all. Derived
    from the awards themselves rather than from a status somewhere, so the
    two can never disagree.
    """
    from economy.championship_pots import pillar_awards

    return tuple(p for p in funded_pillars(db, league_id=league_id,
                                           season=season)
                 if pillar_awards(db, pillar=p, league_id=league_id,
                                  season=season))


def is_postseason(db, *, league_id: int) -> bool:
    """Whether this league has begun its postseason.

    Read from the provider-stated boundary through the same accessor the Pool
    engine and the Weekly Minimum use, so all three agree on one boundary."""
    from betting.pool_season_boundary import playoff_start_week
    from db.schema import Matchup
    from sqlalchemy import func

    league = _league(db, league_id)
    db.flush()
    latest = (db.query(func.max(Matchup.week))
              .filter(Matchup.league_id == league_id,
                      Matchup.finalized_at.isnot(None)).scalar())
    return latest is not None and int(latest) >= playoff_start_week(league)


def view(db, *, league_id: int,
         season: int | None = None) -> GrandChampionshipView:
    """The Grand Championship, derived. Writes nothing.

    PLACEHOLDER during the regular season returns NO ROWS. See the module
    docstring: a table of GMs on zero is a claim that they are level, and during
    the regular season there is nothing to be level about.
    """
    from economy.championship_pots import pillar_awards

    league = _league(db, league_id)
    season = league.season if season is None else season
    if not is_final_por(db, league_id=league_id, season=season):
        raise GrandChampionshipError(
            REASON_WRONG_ERA,
            f"league {league_id} season {season} is governed by the legacy "
            f"ruleset, whose Grand Champion is the retired 3/2/1 recognition "
            f"in `reports.grand_champion`. Reporting it as a Credit total "
            f"would describe a competition it did not run.")

    funded = funded_pillars(db, league_id=league_id, season=season)
    finalized = finalized_pillars(db, league_id=league_id, season=season)

    if not is_postseason(db, league_id=league_id):
        return GrandChampionshipView(
            league_id=league_id, season=season, state=GRAND_PLACEHOLDER,
            funded_pillars=funded, finalized_pillars=finalized,
            rows=(), champion_team_ids=())

    totals: dict[int, dict[str, int]] = {}
    for pillar in finalized:
        for team_id, cents in pillar_awards(db, pillar=pillar,
                                            league_id=league_id,
                                            season=season).items():
            totals.setdefault(team_id, {})[pillar] = cents

    rows = tuple(sorted(
        (GrandRow(team_id=team_id, by_pillar=dict(by_pillar),
                  total_cents=sum(by_pillar.values()))
         for team_id, by_pillar in totals.items()),
        key=lambda r: (-r.total_cents, r.team_id)))

    # A TIED TOTAL IS A DEAD HEAT AND NOTHING BREAKS IT (§20). Every GM on the
    # top total is named; there is no second sort key and no fallback.
    champions: tuple[int, ...] = ()
    if rows:
        best = rows[0].total_cents
        if best > 0:
            champions = tuple(r.team_id for r in rows
                              if r.total_cents == best)

    state = (GRAND_FINAL if funded and set(finalized) == set(funded)
             else GRAND_LIVE)
    return GrandChampionshipView(
        league_id=league_id, season=season, state=state,
        funded_pillars=funded, finalized_pillars=finalized,
        rows=rows, champion_team_ids=champions)
