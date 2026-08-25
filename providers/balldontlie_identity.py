"""BALLDONTLIE subjects -> the provider-neutral identity layer (WP1).

THIS IS NOT THE WP2 CLIENT AND MUST NOT GROW INTO ONE. There is no HTTP here, no
API key is read, no retry or rate-limit policy is expressed, and nothing in this
module can reach the network. It converts dictionaries that BALLDONTLIE shaped
into the `ProviderSubject` records `providers/cross_identity.py` compares — and
that is the entire job. WP2 will own the transport and will hand its decoded
payloads to `directory_from_rows` exactly as the committed fixture does.

Keeping the conversion here rather than inside the future client is what lets
every identity test in WP1 run offline and deterministically: the fixture and the
live payload become identical `ProviderSubject` objects, so certifying against
the fixture certifies the code that will run against the live feed.

── THE TWO SHAPES BALLDONTLIE SPEAKS ───────────────────────────────────────

A fantasy stat row carries a `player` object for a human being and `player: null`
for a team defense, with the team present in both cases. So:

    a PLAYER    is identified by `player.id`     -> "bdl.p.882"
    a DEFENSE   is identified by its TEAM        -> "bdl.dst.WSH"

The defense key is synthesized, and it has to be, because BALLDONTLIE issues no
identifier for a team defense at all. Synthesizing it from the canonical team
abbreviation rather than the numeric `team.id` is deliberate: there is exactly
one defense per franchise for as long as the franchise exists, the abbreviation
is stable across seasons, and a key a human can read is a key a human can audit.

── POSITION COMES FROM BOTH FIELDS, ON PURPOSE ─────────────────────────────

BALLDONTLIE contradicts itself inside a single row. Every kicker's fantasy row
says K while his player object says PK; twelve fullbacks are filed under RB while
labelled FB; and the Phase 0 capture contains a subject whose fantasy row says RB
and whose player object says WR. Taking either field alone would drop real
subjects, and taking one as truth would silently prefer whichever the sample
happened to agree on. Both are canonicalized and both are kept, so a subject
matches any position the provider actually stated for him and no position it
did not.
"""

from __future__ import annotations

import json
import os

from providers.cross_identity import BALLDONTLIE, ProviderSubject, SubjectDirectory
from providers.errors import ProviderIdentityError, ProviderParseError
from providers.nfl_teams import canonical_position, is_team_defense, to_canonical_team

__all__ = [
    "DEFAULT_FIXTURE",
    "defense_key",
    "directory_from_fixture",
    "directory_from_rows",
    "player_key",
    "subject_from_row",
]

#: The committed identity-only capture. See its own `note` field: it carries
#: names, ids, teams and position labels, and not one statistic.
DEFAULT_FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "wp1_identity", "bdl_subjects_2025_w17.json")


def player_key(balldontlie_player_id: int | str) -> str:
    """BALLDONTLIE player id -> namespaced provider key."""
    return f"bdl.p.{balldontlie_player_id}"


def defense_key(canonical_team: str) -> str:
    """Canonical NFL team abbreviation -> the team defense's provider key."""
    return f"bdl.dst.{canonical_team}"


def subject_from_row(row: dict) -> ProviderSubject:
    """One BALLDONTLIE subject record -> one `ProviderSubject`.

    Accepts both the fixture's flattened shape and a live fantasy stat row: the
    fields consulted (`player`, `team`, `position`) are the ones the live API
    returns, and the fixture is a projection of exactly those.
    """
    team_node = row.get("team") or {}
    raw_team = row.get("team_abbreviation") or team_node.get("abbreviation")
    try:
        team = to_canonical_team(raw_team, dialect=BALLDONTLIE)
    except ProviderIdentityError as exc:
        raise ProviderParseError(
            f"BALLDONTLIE subject carries NFL team {raw_team!r}, which is not "
            f"a team this product knows: {exc}") from exc

    player = row.get("player")
    raw_positions = list(row.get("provider_positions") or [])
    if not raw_positions:
        for value in (row.get("position"),
                      (player or {}).get("position_abbreviation"),
                      (player or {}).get("position")):
            if value and value not in raw_positions:
                raw_positions.append(value)

    kind = row.get("kind")
    defense = (kind == "TEAM_DEFENSE") if kind else (
        player is None or any(is_team_defense(p) for p in raw_positions))

    if defense:
        return ProviderSubject(
            provider=BALLDONTLIE,
            provider_player_key=defense_key(team),
            name=row.get("full_name") or team_node.get("full_name") or f"{team} DEF",
            positions=frozenset({"DEF"}),
            nfl_team=team,
            provider_player_id=None,
            provider_positions=tuple(raw_positions) or ("DST",),
            is_team_defense=True,
        )

    identifier = row.get("bdl_player_id")
    if identifier is None and player is not None:
        identifier = player.get("id")
    if identifier is None:
        raise ProviderParseError(
            "BALLDONTLIE subject carries neither a player id nor a team-defense "
            "marker. A subject with no identifier cannot be mapped durably, and "
            "falling back to its name is the one thing WP1 forbids.")

    first = row.get("first_name") or (player or {}).get("first_name") or ""
    last = row.get("last_name") or (player or {}).get("last_name") or ""
    name = (row.get("full_name") or f"{first} {last}").strip()
    if not name:
        raise ProviderParseError(
            f"BALLDONTLIE player {identifier} carries no name. Discovery has "
            f"nothing to start from.")

    positions = set()
    for label in raw_positions:
        try:
            positions.add(canonical_position(label))
        except ProviderIdentityError:
            # A label with no canonical fantasy equivalent (BALLDONTLIE files a
            # handful of defensive players who scored) is DROPPED, not guessed
            # at. The subject survives with whatever canonical positions it does
            # have; if it has none it cannot be discovered by position, which is
            # the correct outcome for a subject with no fantasy position.
            continue

    return ProviderSubject(
        provider=BALLDONTLIE,
        provider_player_key=player_key(identifier),
        name=name,
        positions=frozenset(positions),
        nfl_team=team,
        provider_player_id=int(identifier),
        provider_positions=tuple(raw_positions),
        is_team_defense=False,
    )


def directory_from_rows(rows: list[dict]) -> SubjectDirectory:
    """Decoded BALLDONTLIE subject rows -> the directory the resolver reads."""
    return SubjectDirectory(BALLDONTLIE, [subject_from_row(r) for r in rows])


def directory_from_fixture(path: str | None = None) -> SubjectDirectory:
    """The committed offline directory. No network, no key, no clock."""
    target = path or DEFAULT_FIXTURE
    with open(target, encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = payload["subjects"] if isinstance(payload, dict) else payload
    return directory_from_rows(rows)
