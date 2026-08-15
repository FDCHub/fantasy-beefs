"""
WP1D — the Championship Pot's recipient order.

THE ONE THING THIS MODULE DOES: turn an authoritative postseason result into
three ordered internal team ids — champion, runner-up, official third-place
winner — or refuse.

── THE DEFECT IT REMOVES ────────────────────────────────────────────────────

Before WP1D the Championship Pot was distributed by `default_standings_order`,
which ranks teams by REGULAR-SEASON POINTS FOR. A twelve-team league whose
highest scorers all lost in the first playoff round paid 60/30/10 to three
eliminated teams while the actual champion received nothing. That is not a
rounding error or an edge case; it is the ordinary outcome whenever the
regular-season scoring leaders are not the teams that win the bracket.

Regular-season Points For remains the CORRECT authority for one thing — the
Skunk Pot, whose whole premise is season-long scoring — and it is now the wrong
authority for the Championship Pot. The two live side by side deliberately, and
`test_econcfg_wp1d_pg.py` asserts both in one suite so the distinction cannot
quietly collapse into one rule.

── WHAT THIS MODULE IS NOT ──────────────────────────────────────────────────

It contains no payout percentages, no ledger posting, no Yahoo import and no
score inference. `championship_distribution`'s 60/30/10 arithmetic and its
remainder rule are untouched and are called with exactly the ordered list this
produces. The third-place rule itself is not restated here either: WP1BC already
derives the official third-place game from the championship semifinal losers,
and this module consumes that state rather than re-deriving it.

── NO FALLBACK, EVER ────────────────────────────────────────────────────────

Every path that cannot establish all three recipients raises. There is no
regular-season ordering to fall back to, no seed, no ordinal, no commissioner
selection and no FantasyStakes-invented tiebreaker. A refusal here refuses the
whole season close, which is the intended behaviour: the Championship Pot is not
distributed and the season does not close until the podium is authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass

REASON_NO_TRACK_STATE = "PODIUM_STATE_NOT_SUPPLIED"
REASON_TRACK_UNKNOWN = "PODIUM_STATE_UNKNOWN"
REASON_NOT_COMPLETE = "PODIUM_CHAMPIONSHIP_INCOMPLETE"
REASON_NO_CHAMPION = "PODIUM_CHAMPION_MISSING"
REASON_FINALISTS_INVALID = "PODIUM_FINALISTS_INVALID"
REASON_CHAMPION_NOT_FINALIST = "PODIUM_CHAMPION_NOT_A_FINALIST"
REASON_NO_THIRD_PLACE_GAME = "PODIUM_THIRD_PLACE_GAME_MISSING"
REASON_THIRD_PLACE_UNDECIDED = "PODIUM_THIRD_PLACE_NOT_DECIDED"
REASON_THIRD_PLACE_NOT_PARTICIPANT = "PODIUM_THIRD_PLACE_WINNER_NOT_PARTICIPANT"
REASON_DUPLICATE_RECIPIENT = "PODIUM_DUPLICATE_RECIPIENT"
REASON_UNRESOLVED_TEAM = "PODIUM_TEAM_UNRESOLVED"


class ChampionshipPodiumError(ValueError):
    """The Championship podium could not be established.

    A ValueError subclass so the season close's existing handling still catches
    it, carrying `reason` for surfaces that render reason codes.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


@dataclass(frozen=True)
class Podium:
    """The three Championship Pot recipients, in payout order.

    `provider_keys` is carried beside the internal ids purely so a refusal or an
    audit line can name the teams in the provider's own vocabulary without a
    second lookup. Only `team_ids` is consumed by the payout.
    """

    team_ids: tuple[int, int, int]
    provider_keys: tuple[str, str, str]

    @property
    def champion_team_id(self) -> int:
        return self.team_ids[0]

    @property
    def runner_up_team_id(self) -> int:
        return self.team_ids[1]

    @property
    def third_place_team_id(self) -> int:
        return self.team_ids[2]


def derive_podium_keys(state) -> tuple[str, str, str]:
    """Champion, runner-up and third-place winner as PROVIDER team keys.

    Pure — no session, no identity resolution, no ledger. Every requirement the
    POR states is checked explicitly rather than assumed, because each one is a
    way the podium could be wrong while still looking complete:

        · the track must be authoritative               (not UNKNOWN)
        · the championship must be complete              (every round decided)
        · there must be a champion
        · exactly two distinct finalists
        · the champion must be one of them               (else the "runner-up"
                                                          would be a third team)
        · exactly one runner-up therefore remains
        · an official third-place game must exist        (WP1BC identified it)
        · it must be DECIDED                             (final AND a declared
                                                          winner — never a score
                                                          comparison)
        · its winner must be one of its participants
        · the three must be distinct
    """
    if state is None:
        raise ChampionshipPodiumError(
            REASON_NO_TRACK_STATE,
            "no championship track state was supplied. The Championship Pot "
            "recipient order is not derivable from standings, seed or "
            "regular-season scoring.")

    if not state.authority.is_authoritative:
        raise ChampionshipPodiumError(
            REASON_TRACK_UNKNOWN,
            f"the championship track is not determinable "
            f"(authority={state.authority.value}, reasons="
            f"{list(state.insufficiency_reasons)}). Refusing to distribute the "
            f"Championship Pot — there is no fallback ordering.")

    if not state.complete:
        raise ChampionshipPodiumError(
            REASON_NOT_COMPLETE,
            "the championship is not complete; no champion has been decided.")

    champion = state.champion_team_key
    if not champion:
        raise ChampionshipPodiumError(
            REASON_NO_CHAMPION,
            "the championship reports complete but names no champion.")

    finalists = tuple(state.finalist_team_keys or ())
    if len(set(finalists)) != 2:
        raise ChampionshipPodiumError(
            REASON_FINALISTS_INVALID,
            f"the championship names {len(set(finalists))} distinct finalist(s) "
            f"({list(finalists)!r}); a runner-up is only derivable from exactly "
            f"two.")
    if champion not in finalists:
        raise ChampionshipPodiumError(
            REASON_CHAMPION_NOT_FINALIST,
            f"champion {champion!r} is not one of the finalists "
            f"{list(finalists)!r}; the remaining team would not be the "
            f"runner-up.")
    runner_up = next(k for k in finalists if k != champion)

    third_game = state.third_place_matchup
    if third_game is None:
        raise ChampionshipPodiumError(
            REASON_NO_THIRD_PLACE_GAME,
            "no official third-place game was identified for this season. The "
            "supported FantasyStakes postseason model always plays one, and no "
            "fallback recipient is permitted, so the Pot is not distributed.")
    if not third_game.is_decided:
        raise ChampionshipPodiumError(
            REASON_THIRD_PLACE_UNDECIDED,
            f"the official third-place game is not decided "
            f"(finality={third_game.finality.value}, winner="
            f"{third_game.winner_team_key!r}). The season does not close until "
            f"it is authoritative and final.")

    third = third_game.winner_team_key
    if third not in third_game.team_keys:
        raise ChampionshipPodiumError(
            REASON_THIRD_PLACE_NOT_PARTICIPANT,
            f"the third-place winner {third!r} is not a participant of that "
            f"game ({list(third_game.team_keys)!r}).")

    keys = (champion, runner_up, third)
    if len(set(keys)) != 3:
        raise ChampionshipPodiumError(
            REASON_DUPLICATE_RECIPIENT,
            f"the podium names a team twice: {list(keys)!r}.")
    return keys


def resolve_podium(state, resolver) -> Podium:
    """The podium as internal team ids, resolved through the certified seam.

    `resolver` is `providers.yahoo.identity.build_team_identity_resolver`'s
    league-scoped resolver, INJECTED — `economy/` imports nothing from
    `providers/`. It is league-scoped, so a provider key belonging to another
    league resolves to nothing and refuses here rather than paying a stranger.

    Refuses on any unresolvable key. A partially resolved podium would pay two
    of three recipients and silently drop the third's share into whatever the
    caller did next.
    """
    keys = derive_podium_keys(state)

    ids: list[int] = []
    unresolved: list[str] = []
    for key in keys:
        try:
            internal = resolver.to_internal(key)
        except Exception:                       # noqa: BLE001 - re-raised named
            internal = None
        if internal is None:
            unresolved.append(key)
            continue
        ids.append(int(internal))

    if unresolved:
        raise ChampionshipPodiumError(
            REASON_UNRESOLVED_TEAM,
            f"{len(unresolved)} podium team(s) have no internal identity in "
            f"this league ({unresolved!r}). S6-R1 forbids matching them by "
            f"name, and a cross-league key resolves to nothing here by design.")

    if len(set(ids)) != 3:
        raise ChampionshipPodiumError(
            REASON_DUPLICATE_RECIPIENT,
            f"the podium resolved to {sorted(set(ids))!r}; three distinct "
            f"internal teams are required.")

    return Podium(team_ids=(ids[0], ids[1], ids[2]), provider_keys=keys)
