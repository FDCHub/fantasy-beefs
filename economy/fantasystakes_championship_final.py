"""
economy/fantasystakes_championship_final.py — paying the FS Championship (WP-8).

WHY THIS EXISTS. WP-8 retimed the FantasyStakes Championship to run through the
postseason and retired the boundary freeze. RC2's
`economy.fantasystakes_championship_settlement.settle_fantasystakes_championship`
pays the FROZEN SNAPSHOT and refuses without one — so retiring the freeze left a
Final POR season able to reach FINAL with no way to be PAID. A retimed lifecycle
whose terminal state is unreachable is a half-retired architecture, which is
exactly what must not be left behind.

── WHAT IS DIFFERENT FROM THE RC2 SETTLEMENT, AND WHY ──────────────────────

    RC2                                  Final POR
    ----------------------------------   ----------------------------------
    pays a frozen snapshot                pays the LIVE FantasyStakes Score
    scored on the regular season alone    scored on the whole season
    pot fixed at activation               pot authoritative at finality
    gated on FROZEN + unresolved-contest  gated on lifecycle FINAL

The score is read from `reports.standings_read_model.league_standings`, which is
the same read model the Standings screen shows all season and which already
applies no week cutoff. There is no second scoring path here and no snapshot: at
FINAL the live score IS the final score, because FINAL means nothing can still
move it.

── THE POT IS READ THROUGH THE LIFECYCLE, NOT DIRECTLY ─────────────────────

`authoritative_pot_cents` refuses while LIVE. Reading the balance directly would
work and would silently pay a running total if this were ever called a week
early — the pot grows on every week close, every approved Top-Off and every
terminal Pool remainder.

── EXACTLY-ONCE THROUGH THE SAME ROW RC2 USES ──────────────────────────────

`FantasyStakesChampionshipDistributionRun` is unique on (league, season) and is
what `economy.fantasystakes_lifecycle.is_paid` already reads. Writing the same
row means PAID is one fact with one definition across both eras, and a season
cannot be paid twice by paying it through the other era's path.

── ERA ─────────────────────────────────────────────────────────────────────

`RULESET_FINAL_POR` only. A legacy season pays through the RC2 settlement, off
its frozen snapshot, and nothing here touches that path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from economy.championship_distribution import distribute_championship
from economy.economy_events import (
    EVENT_CHAMPIONSHIP_DISTRIBUTION,
    PILLAR_FANTASYSTAKES,
    fantasystakes_championship_account,
    pillar_season_key,
    record_event,
    wallet_account,
)
from economy.fantasystakes_lifecycle import (
    LIFECYCLE_PAID, authoritative_pot_cents, lifecycle_state,
)
from ledger.ledger import post as ledger_post
from ruleset import is_final_por

#: The door under which a Final POR FantasyStakes Championship pays.
#:
#: DISTINCT FROM RC2's `fantasystakes_championship_distribution`, deliberately.
#: The two pay different competitions — one the regular season, one the whole
#: season — and a ledger that cannot tell them apart cannot answer which rules
#: a historical payout was made under.
#:
#: NOT A MEMBER OF `VERSUS_DOORS` OR `POOL_DOORS`. A championship award is a
#: PRIZE, not competition: counting it in the FantasyStakes Score would let the
#: award the score earned then change the score, which is circular.
DOOR_FS_CHAMPIONSHIP_FINAL = "fantasystakes_championship_final"


class FantasyStakesChampionshipFinalError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_WRONG_ERA = "FS_FINAL_WRONG_ERA"
REASON_NOT_FINAL = "FS_FINAL_NOT_FINAL"
REASON_ALREADY_PAID = "FS_FINAL_ALREADY_PAID"
REASON_EMPTY_POT = "FS_FINAL_EMPTY_POT"
REASON_NO_FIELD = "FS_FINAL_NO_FIELD"
REASON_NO_WALLET = "FS_FINAL_NO_WALLET"
REASON_LEAGUE_NOT_FOUND = "FS_FINAL_LEAGUE_NOT_FOUND"


@dataclass(frozen=True)
class FinalChampionshipResult:
    league_id: int
    season: int
    pot_cents: int
    #: (team_id, place, award_cents, score_cents), by place then canonical id.
    placements: tuple[tuple[int, int, int, int], ...]
    dead_heat: bool


def settle(db, *, league_id: int, season: int | None = None,
           now: datetime | None = None) -> FinalChampionshipResult:
    """Pay the FantasyStakes Championship 60/30/10. Does NOT commit."""
    from db.schema import League, Wallet
    from economy.fantasystakes_championship_settlement import (
        FantasyStakesChampionshipDistributionRun as Run,
    )
    from reports.standings_read_model import league_standings

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise FantasyStakesChampionshipFinalError(
            REASON_LEAGUE_NOT_FOUND, f"league {league_id} not found")
    season = league.season if season is None else season

    if not is_final_por(db, league_id=league_id, season=season):
        raise FantasyStakesChampionshipFinalError(
            REASON_WRONG_ERA,
            f"league {league_id} season {season} is governed by the legacy "
            f"ruleset and pays through the RC2 settlement, off its frozen "
            f"regular-season snapshot.")

    state = lifecycle_state(db, league_id=league_id, season=season)
    if state == LIFECYCLE_PAID:
        raise FantasyStakesChampionshipFinalError(
            REASON_ALREADY_PAID,
            f"league {league_id} season {season} has already distributed its "
            f"FantasyStakes Championship. The pot pays exactly once.")

    # RAISES `FS_LIFECYCLE_NOT_FINAL` WHILE LIVE, naming what is still open.
    # Read through the lifecycle rather than off the balance: the pot grows on
    # every week close, Top-Off and terminal Pool remainder, so a direct read a
    # week early would quietly pay a running total.
    try:
        pot = authoritative_pot_cents(db, league_id=league_id, season=season)
    except Exception as exc:
        raise FantasyStakesChampionshipFinalError(
            REASON_NOT_FINAL, str(exc)) from exc

    if pot <= 0:
        raise FantasyStakesChampionshipFinalError(
            REASON_EMPTY_POT,
            f"{fantasystakes_championship_account(league_id, season)} holds "
            f"{pot} cents; there is nothing to distribute.")

    # THE LIVE SCORE IS THE FINAL SCORE AT FINAL, which is what FINAL means.
    # Same read model the Standings screen shows all season, which already
    # applies no week cutoff — so postseason results are in it by construction.
    rows = league_standings(db, league_id=league_id).rows
    if not rows:
        raise FantasyStakesChampionshipFinalError(
            REASON_NO_FIELD,
            f"league {league_id} has no competitive rows to rank.")

    standings = tuple((int(r.team_id), int(r.net_cents)) for r in rows)
    placements = distribute_championship(pot, standings)

    for placement in placements:
        if placement.amount_cents <= 0:
            continue
        if (db.query(Wallet)
                .filter(Wallet.team_id == placement.team_id).first()) is None:
            raise FantasyStakesChampionshipFinalError(
                REASON_NO_WALLET,
                f"FantasyStakes Championship place {placement.place} is team "
                f"{placement.team_id}, which has no wallet; refusing to pay a "
                f"subset of the podium.")

    account = fantasystakes_championship_account(league_id, season)
    legs = [(account, -pot)]
    legs.extend((wallet_account(p.team_id), p.amount_cents)
                for p in placements if p.amount_cents > 0)
    posting_id = ledger_post(legs, door=DOOR_FS_CHAMPIONSHIP_FINAL, session=db)

    # THE SAME ROW RC2 WRITES, so PAID has one definition across both eras and
    # `fantasystakes_lifecycle.is_paid` needs no branch.
    db.add(Run(league_id=league_id, season=season, pot_cents=pot,
               posting_id=posting_id,
               awards_json=[{"team_id": p.team_id, "place": p.place,
                             "amount_cents": p.amount_cents}
                            for p in placements],
               distributed_at=now))
    record_event(db, event_key=pillar_season_key(
                     EVENT_CHAMPIONSHIP_DISTRIBUTION, PILLAR_FANTASYSTAKES,
                     league_id, season),
                 league_id=league_id, season=season,
                 event_type=EVENT_CHAMPIONSHIP_DISTRIBUTION,
                 amount_cents=pot, posting_id=posting_id, now=now)
    db.flush()

    places = [p.place for p in placements]
    return FinalChampionshipResult(
        league_id=league_id, season=season, pot_cents=pot,
        placements=tuple((p.team_id, p.place, p.amount_cents, p.rank_value)
                         for p in placements),
        dead_heat=len(places) != len(set(places)))
