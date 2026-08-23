"""
economy/ff_championship_settlement.py — the Fantasy Football Championship (WP-11).

WHAT THIS PILLAR IS. The one championship FantasyStakes does not decide. Its
podium is the underlying fantasy league's own playoff bracket, stated by the
provider, and its pot is the single commissioner-entered amount WP-5 minted into
`ff_championship:{league}:{season}` at activation. This module does exactly two
things: turn a provider-stated bracket into a podium, and pay that podium
60/30/10 through the one canonical split.

── THE PART THAT IS BLOCKED, AND WHY IT STAYS BLOCKED ──────────────────────

NO YAHOO POSTSEASON BRACKET CLASSIFICATION IS AVAILABLE IN THIS BUILD. No
postseason payload is captured, no bracket-classifying field is documented, and
no Yahoo postseason source is registered. §33 and the POR are explicit that
UNKNOWN fails closed and that nothing may invent a playoff, consolation,
championship or third-place classification.

So this module is built to the seam and NOT past it. `settle` takes a
`ChampionshipTrackState` — the same object `betting.pool_postseason` and
`beefs.postseason_versus` already take — and refuses unless that state
AFFIRMATIVELY says the bracket is complete and decided. It never reads a
provider payload, never classifies a matchup and never infers a winner from a
score. `provider_finality` reports what is missing so an operator sees BLOCKED
rather than a silent zero payout.

WHAT IS THEREFORE ALREADY TRUE AND CERTIFIABLE TODAY: the pot, the podium
arithmetic, the dead-heat rule, exactly-once payment, conservation, the era
gate, and every refusal. What is NOT: an end-to-end settlement against real
Yahoo bracket data, which requires PROV-1/PROV-2.

── THE PODIUM COMES FROM THE BRACKET, NOT FROM A SCORE ─────────────────────

    1st  `champion_team_key`
    2nd  the finalist who is not the champion
    3rd  the winner of the official third-place game

Third place is the strictest of the three. §19's rule — already implemented and
certified in `season.championship_track._identify_third_place` — admits only a
game between exactly the two championship semifinal losers, affirmatively
classified NON_CHAMPIONSHIP, and refuses ambiguity rather than picking.

A BRACKET WITH NO DECIDED THIRD PLACE REFUSES, AND DOES NOT PARTIALLY PAY.
That is not a preference; it is what the surrounding rules leave available.
§17 fixes the split at 60/30/10 and requires the pot to be conserved exactly —
`distribute_championship` asserts it and raises on a shortfall — so a two-name
podium cannot be paid through the canonical splitter at all. The alternatives
were to redistribute the 10% or to leave it stranded in the pot, and the POR
states neither: §19's whole posture is fail-closed, and the POR's instruction
for this pillar is to keep settlement fail-closed and mark provider finality
BLOCKED rather than invent. Inventing a redistribution rule here would be
deciding a product question in code.

SO A LEAGUE THAT PLAYS NO THIRD-PLACE GAME CANNOT SETTLE THIS PILLAR YET, and
that is reported as `FINALITY_NOT_COMPLETE` with the exact reason rather than as
a silent zero. It is a flagged open product question, not a defect to be papered
over: the governed answer for a two-place bracket has not been stated.

── A KNOCKOUT PRODUCES NO DEAD HEAT, AND THAT IS ASSERTED RATHER THAN ASSUMED ─

`podium_standings` gives each finisher a distinct descending ordinal, so the
canonical split reports no tie. A provider-declared TIE in a bracket game is not
a dead heat either — it is an undecided game, and `ChampionshipMatchup.is_decided`
is already False for one. The refusal is the correct outcome: a tied final has
no champion yet.

── ERA ─────────────────────────────────────────────────────────────────────

`RULESET_FINAL_POR` only. A legacy season's Fantasy Football contribution was
a per-GM reserve swept into `championship:{league}`, paid by
`economy.season_reconciliation.distribute_championship`; this pot does not exist
for one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from economy.championship_distribution import (
    distribute_championship, podium_standings,
)
from economy.economy_events import (
    DOOR_CHAMPIONSHIP_DISTRIBUTION,
    EVENT_CHAMPIONSHIP_DISTRIBUTION,
    ff_championship_account,
    pillar_season_key,
    PILLAR_FANTASY_FOOTBALL,
    record_event,
    wallet_account,
)
from ledger.ledger import _balance_of_in_session, post as ledger_post
from ruleset import is_final_por


class FFChampionshipError(ValueError):
    """A Fantasy Football Championship operation was refused."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_WRONG_ERA = "FF_WRONG_ERA"
REASON_PROVIDER_BLOCKED = "FF_PROVIDER_FINALITY_BLOCKED"
REASON_EMPTY_POT = "FF_EMPTY_POT"
REASON_UNRESOLVED_TEAM = "FF_UNRESOLVED_TEAM"
REASON_NO_WALLET = "FF_NO_WALLET"
REASON_LEAGUE_NOT_FOUND = "FF_LEAGUE_NOT_FOUND"

#: The provider-finality verdict. Deliberately three-valued rather than a bool:
#: "the bracket says nobody won yet" and "we cannot see the bracket at all" are
#: different operational situations, and only the second is a PROV-1/PROV-2
#: problem for someone to act on.
FINALITY_AVAILABLE = "AVAILABLE"
FINALITY_BLOCKED = "BLOCKED"
FINALITY_NOT_COMPLETE = "NOT_COMPLETE"


@dataclass(frozen=True)
class ProviderFinality:
    status: str
    reasons: tuple[str, ...]

    @property
    def is_available(self) -> bool:
        return self.status == FINALITY_AVAILABLE

    def as_dict(self) -> dict:
        return {"status": self.status, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class FFPodium:
    """The bracket's podium, in provider team keys. Always exactly three.

    THREE, NEVER TWO. §17's split must conserve the pot exactly, so a podium
    that cannot name a third place cannot be paid at all — `podium()` refuses
    before constructing one. Making the field non-optional is what stops a
    partial podium from reaching the splitter and failing there instead."""

    champion_team_key: str
    runner_up_team_key: str
    third_team_key: str

    @property
    def ordered_keys(self) -> tuple[str, str, str]:
        return (self.champion_team_key, self.runner_up_team_key,
                self.third_team_key)


@dataclass(frozen=True)
class FFSettlementResult:
    league_id: int
    season: int
    pot_cents: int
    paid_cents: int
    #: (team_id, place, award_cents)
    placements: tuple[tuple[int, int, int], ...]
    replayed: bool


def pot_cents(db, *, league_id: int, season: int) -> int:
    db.flush()
    return _balance_of_in_session(db, ff_championship_account(league_id, season))


def provider_finality(state) -> ProviderFinality:
    """Whether the provider has stated a bracket this pillar can be paid on.

    READS THE SUPPLIED TRACK STATE AND NOTHING ELSE. It opens no provider
    session, refreshes no token and reads no payload — §33's UNKNOWN-fails-closed
    rule is honoured by having nothing here that could guess.
    """
    if state is None:
        return ProviderFinality(FINALITY_BLOCKED, (
            "no championship track state was supplied; the Fantasy Football "
            "bracket is UNKNOWN and UNKNOWN fails closed.",))

    reasons: list[str] = []
    authority = getattr(state, "authority", None)
    if authority is not None and str(getattr(authority, "value", authority)) \
            .upper().endswith("UNKNOWN"):
        reasons.append(
            "the championship track authority is UNKNOWN: "
            + "; ".join(getattr(state, "insufficiency_reasons", ()) or
                        ("no reason recorded",)))
    if reasons:
        return ProviderFinality(FINALITY_BLOCKED, tuple(reasons))

    if not getattr(state, "complete", False):
        return ProviderFinality(FINALITY_NOT_COMPLETE, (
            "the provider bracket is readable but the championship is not "
            "complete; no champion has been declared.",))
    if not getattr(state, "champion_team_key", None):
        return ProviderFinality(FINALITY_NOT_COMPLETE, (
            "the bracket reports complete but names no champion; a tied final "
            "is an undecided game, not a dead heat.",))
    if len(getattr(state, "finalist_team_keys", ()) or ()) != 2:
        return ProviderFinality(FINALITY_NOT_COMPLETE, (
            "the bracket names "
            f"{len(getattr(state, 'finalist_team_keys', ()) or ())} finalist(s);"
            " a runner-up cannot be identified.",))
    return ProviderFinality(FINALITY_AVAILABLE, ())


def podium(state) -> FFPodium:
    """The bracket podium, or a named refusal. Reads only the track state.

    THIRD PLACE MAY LEGITIMATELY BE ABSENT. §19 admits only a game between
    exactly the two championship semifinal losers, affirmatively classified
    NON_CHAMPIONSHIP; a league that plays no such game, or whose game is not
    decided, has no third-place finisher. `third_team_key` is None and the 10%
    is left in the pot rather than redistributed — see the module docstring.
    """
    finality = provider_finality(state)
    if not finality.is_available:
        raise FFChampionshipError(
            REASON_PROVIDER_BLOCKED,
            f"Fantasy Football Championship finality is {finality.status}: "
            + "; ".join(finality.reasons))

    champion = state.champion_team_key
    runner_up = next((k for k in state.finalist_team_keys if k != champion),
                     None)
    if runner_up is None:
        raise FFChampionshipError(
            REASON_PROVIDER_BLOCKED,
            "the bracket's finalists do not include a team other than the "
            "champion; a runner-up cannot be identified without guessing.")

    game = getattr(state, "third_place_matchup", None)
    if game is None:
        raise FFChampionshipError(
            REASON_PROVIDER_BLOCKED,
            "the bracket identifies no official third-place game (§19 admits "
            "only a game between exactly the two championship semifinal "
            "losers, affirmatively classified NON_CHAMPIONSHIP). §17's split "
            "must conserve the pot exactly, so a two-name podium cannot be "
            "paid; refusing rather than inventing a third finisher or a "
            "redistribution rule the POR does not state.")
    if not getattr(game, "is_decided", False):
        raise FFChampionshipError(
            REASON_PROVIDER_BLOCKED,
            "the official third-place game is identified but not decided "
            "(final AND carrying a provider-declared winner). A tie is an "
            "undecided game, not a dead heat.")

    return FFPodium(champion_team_key=champion, runner_up_team_key=runner_up,
                    third_team_key=game.winner_team_key)


def settle(db, *, league_id: int, state, season: int | None = None,
           now: datetime | None = None) -> FFSettlementResult:
    """Pay the Fantasy Football Championship 60/30/10. Does NOT commit."""
    from db.schema import League, Wallet
    from providers.identity import build_team_identity_resolver

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise FFChampionshipError(REASON_LEAGUE_NOT_FOUND,
                                  f"league {league_id} not found")
    season = league.season if season is None else season

    if not is_final_por(db, league_id=league_id, season=season):
        raise FFChampionshipError(
            REASON_WRONG_ERA,
            f"league {league_id} season {season} is governed by the legacy "
            f"ruleset, whose Fantasy Football contribution was a per-GM "
            f"reserve swept into `championship:{league_id}`. This pot does not "
            f"exist for it.")

    # THE PROVIDER GATE COMES FIRST, before the pot is even read. A blocked
    # bracket must refuse identically whether the pot is funded or empty, so an
    # operator sees BLOCKED rather than a misleading EMPTY_POT.
    board = podium(state)

    account = ff_championship_account(league_id, season)
    db.flush()
    pot = _balance_of_in_session(db, account)
    if pot <= 0:
        raise FFChampionshipError(
            REASON_EMPTY_POT,
            f"{account} holds {pot} cents. §14 lets a commissioner set the "
            f"Fantasy Football Championship Pot to 0, and a pillar with no "
            f"money is not settled — it is simply unfunded.")

    resolver = build_team_identity_resolver(
        db, league_id=league_id, provider=league.provider or "yahoo")
    # `to_internal` IS THE RESOLUTION, and it already fails closed on an
    # unknown key with S6-R1's own reasoning. Re-implementing the lookup against
    # the resolver's internals would be a second, weaker copy of a refusal that
    # is already certified; this only restates it in this pillar's vocabulary.
    from providers.identity import ProviderIdentityError

    team_ids: list[int] = []
    for key in board.ordered_keys:
        try:
            team_ids.append(resolver.to_internal(key))
        except ProviderIdentityError as exc:
            raise FFChampionshipError(
                REASON_UNRESOLVED_TEAM,
                f"provider team key {key!r} is on the Fantasy Football podium "
                f"but resolves to no internal team: {exc}. S6-R1 forbids "
                f"matching by name, and paying a guessed GM is worse than not "
                f"paying.") from exc

    # A KNOCKOUT HAS NO DEAD HEAT. Descending ordinals give each finisher a
    # distinct rank value, so the canonical split reports no tie — which is
    # correct: a bracket produces one champion, one runner-up and one third.
    placements = distribute_championship(pot, podium_standings(team_ids))

    for placement in placements:
        if placement.amount_cents <= 0:
            continue
        if (db.query(Wallet)
                .filter(Wallet.team_id == placement.team_id).first()) is None:
            raise FFChampionshipError(
                REASON_NO_WALLET,
                f"Fantasy Football place {placement.place} is team "
                f"{placement.team_id}, which has no wallet; refusing to pay a "
                f"subset of the podium.")

    paid = sum(p.amount_cents for p in placements)
    legs = [(account, -paid)]
    legs.extend((wallet_account(p.team_id), p.amount_cents)
                for p in placements if p.amount_cents > 0)
    posting_id = ledger_post(legs, door=DOOR_CHAMPIONSHIP_DISTRIBUTION,
                             session=db)

    record_event(db, event_key=pillar_season_key(
                     EVENT_CHAMPIONSHIP_DISTRIBUTION, PILLAR_FANTASY_FOOTBALL,
                     league_id, season),
                 league_id=league_id, season=season,
                 event_type=EVENT_CHAMPIONSHIP_DISTRIBUTION,
                 amount_cents=paid, posting_id=posting_id, now=now)
    db.flush()

    return FFSettlementResult(
        league_id=league_id, season=season, pot_cents=pot, paid_cents=paid,
        placements=tuple((p.team_id, p.place, p.amount_cents)
                         for p in placements),
        replayed=False)
