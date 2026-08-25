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

── THE TWO-TEAM PLAYOFF EXCEPTION — OWNER RULING ───────────────────────────

    official playoff field of 3+ teams   60 / 30 / 10, third place REQUIRED
    official playoff field of exactly 2  67 / 33, and there is no third place

A two-team format has one round, one game and no semifinal, so there is no
official third-place game to win and no third place to pay. It is not that the
third-place result is missing — it is that the structure does not contain one.

THE EXCEPTION KEYS ON THE STRUCTURE, NEVER ON THE ABSENCE OF DATA, and that
distinction is the entire ruling. A four-team format whose third-place game is
unplayed, unreported or ambiguously classified MUST NOT be paid 67/33: that
would convert a provider outage into a permanent 33% raise for the runner-up
and a GM who earned third would never be paid at all. Such a format stays
FAIL-CLOSED until the official third-place result can be determined, exactly as
before.

So the test is `official_field_size(state) == 2`, read from the provider's own
declared championship field — not "did we find a third-place game?", which is
the question that cannot tell the two situations apart. A state that cannot
state its field size is BLOCKED rather than assumed to be either shape.

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
    CHAMPIONSHIP_SPLIT, TWO_TEAM_PLAYOFF_SPLIT, distribute_championship,
    podium_standings,
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
REASON_FIELD_SIZE_UNKNOWN = "FF_FIELD_SIZE_UNKNOWN"

#: The two governed playoff structures, named so a result, a log line and a
#: settings screen can all say which one paid without re-deriving it.
STRUCTURE_STANDARD = "STANDARD_WITH_THIRD_PLACE"
STRUCTURE_TWO_TEAM = "TWO_TEAM_PLAYOFF"

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
    """The bracket's podium, in provider team keys, best first.

    THREE NAMES, OR EXACTLY TWO UNDER THE TWO-TEAM PLAYOFF RULING. `third_team_
    key` is None only when `structure` is `STRUCTURE_TWO_TEAM` — a format that
    HAS no third-place game — and never because a third-place result could not
    be read. `podium()` enforces that pairing; nothing downstream has to
    re-derive which situation it is in, and a podium object cannot represent
    "we could not find third place", which is the state that must fail closed
    rather than be paid."""

    champion_team_key: str
    runner_up_team_key: str
    third_team_key: str | None
    structure: str
    #: The official playoff field size the structure was decided from.
    field_size: int

    @property
    def ordered_keys(self) -> tuple[str, ...]:
        keys = [self.champion_team_key, self.runner_up_team_key]
        if self.third_team_key is not None:
            keys.append(self.third_team_key)
        return tuple(keys)

    @property
    def split(self) -> tuple[int, ...]:
        """The governed split for this structure. Never computed from a count.

        Chosen from `structure` rather than from `len(ordered_keys)` so a podium
        that somehow lost a name cannot silently promote itself into the
        two-team ruling."""
        return (TWO_TEAM_PLAYOFF_SPLIT
                if self.structure == STRUCTURE_TWO_TEAM
                else CHAMPIONSHIP_SPLIT)


@dataclass(frozen=True)
class FFSettlementResult:
    league_id: int
    season: int
    pot_cents: int
    paid_cents: int
    #: (team_id, place, award_cents)
    placements: tuple[tuple[int, int, int], ...]
    replayed: bool
    #: Which governed structure paid, and the split it used. Reported so a
    #: reader never has to infer 67/33 from the amounts.
    structure: str = STRUCTURE_STANDARD
    split: tuple = CHAMPIONSHIP_SPLIT
    field_size: int = 0


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


def official_field_size(state) -> int | None:
    """How many teams the provider says entered the official playoff.

    THE STRUCTURE'S OWN NUMBER, not a count of anything this module found.
    `championship_field_team_keys` is the provider's declaration of WHICH teams
    entered — the same field `season.championship_track` refuses to infer from
    round-one matchups, because a bye team appears in none of them. Counting
    matchups, or counting the names on a podium, would answer a different
    question and would make a two-team ruling reachable by data loss.

    None means the field cannot be stated. That is BLOCKED, not "assume two":
    a format whose size is unknown might be a four-team bracket whose
    third-place game simply has not been read yet.
    """
    keys = getattr(state, "championship_field_team_keys", None)
    if not keys:
        return None
    return len(keys)


def is_two_team_playoff(state) -> bool:
    """Whether the OFFICIAL format contains exactly two playoff teams.

    A two-team field is one round and one game, so it has no semifinal and
    therefore no official third-place game — which is the condition the owner
    ruling names. Derived from the declared field size and from nothing else,
    so an absent third-place game can never make this true on its own.
    """
    return official_field_size(state) == 2


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

    # ── THE STRUCTURE IS DECIDED FIRST, FROM THE FIELD SIZE ─────────────────
    #
    # Before asking anything about a third-place game, establish whether the
    # official format HAS one. Asking in the other order is exactly the mistake
    # the ruling forbids: "no third-place game found" would then mean both "the
    # format has none" and "we could not read it", and only the first may pay.
    field_size = official_field_size(state)
    if field_size is None:
        raise FFChampionshipError(
            REASON_FIELD_SIZE_UNKNOWN,
            "the provider states no championship field, so the official "
            "playoff size is unknown. The two-team ruling applies only to a "
            "format that HAS no third-place game, and an unknown size cannot "
            "be assumed to be one — a four-team bracket whose third-place "
            "result has simply not been read yet looks identical from here.")

    if field_size == 2:
        # THE ONE EXCEPTION. One round, one game, no semifinal, so §19's
        # third-place game cannot exist and 67/33 pays the whole pot.
        #
        # A THIRD-PLACE GAME IS NOT EVEN CONSULTED HERE, because a two-team
        # format that somehow reported one would be describing a structure it
        # does not have, and reading it would be treating that contradiction as
        # data.
        return FFPodium(champion_team_key=champion,
                        runner_up_team_key=runner_up,
                        third_team_key=None,
                        structure=STRUCTURE_TWO_TEAM,
                        field_size=field_size)

    # ── EVERY OTHER FORMAT REQUIRES A DECIDED THIRD PLACE ───────────────────
    #
    # Unchanged, and deliberately: this is the fail-closed path the ruling
    # explicitly preserves. Three or more playoff teams means the format has a
    # third-place game; a missing, unread or ambiguous result is a reason to
    # wait, never a reason to pay 67/33.
    game = getattr(state, "third_place_matchup", None)
    if game is None:
        raise FFChampionshipError(
            REASON_PROVIDER_BLOCKED,
            f"the official playoff field is {field_size} teams, so this format "
            f"HAS an official third-place game, and the bracket identifies "
            f"none (§19 admits only a game between exactly the two "
            f"championship semifinal losers, affirmatively classified "
            f"NON_CHAMPIONSHIP). Refusing rather than paying the two-team "
            f"67/33 split, which would convert a provider gap into a "
            f"permanent raise for the runner-up and would never pay the GM "
            f"who earned third.")
    if not getattr(game, "is_decided", False):
        raise FFChampionshipError(
            REASON_PROVIDER_BLOCKED,
            f"the official third-place game is identified but not decided "
            f"(final AND carrying a provider-declared winner). A tie is an "
            f"undecided game, not a dead heat. The {field_size}-team format "
            f"has a third place to pay and it stays fail-closed until the "
            f"provider declares it.")

    return FFPodium(champion_team_key=champion, runner_up_team_key=runner_up,
                    third_team_key=game.winner_team_key,
                    structure=STRUCTURE_STANDARD,
                    field_size=field_size)


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
    # correct: a bracket produces one champion, one runner-up and (unless the
    # format is two teams) one third.
    #
    # THE SPLIT COMES FROM THE PODIUM'S STRUCTURE, not from how many names it
    # happens to carry. Both splits sum to 100, so the canonical arithmetic
    # conserves the pot exactly either way — the flooring, the
    # remainder-to-first rule and the dead-heat pooling are unchanged and none
    # of them counts to three.
    placements = distribute_championship(pot, podium_standings(team_ids),
                                         split=board.split)

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
        replayed=False,
        structure=board.structure, split=board.split,
        field_size=board.field_size)
