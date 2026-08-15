"""Identity resolution — provider-stable keys to internal rows (S6-R1).

WP2 — THIS MODULE MOVED HERE FROM `providers/yahoo/identity.py` AND NOTHING IN
IT CHANGED EXCEPT WHERE THE PROVIDER NAME COMES FROM. Every rule below is the
Sprint 6 rule, certified by C-4, and the move is the whole point: not one line of
it was ever Yahoo-specific. It read `teams.provider_team_key`, refused name and
email matching, and refused partial resolvers — for whichever provider it was
handed. Living under `providers/yahoo/` made that invisible, and a second
provider could only reuse it by importing the Yahoo package, which is the
dependency a provider-neutral product must not have.

`provider` IS A REQUIRED KEYWORD HERE AND HAS NO DEFAULT. That is the one
substantive difference from the module this replaces. A default of "yahoo" in a
provider-neutral module is a trap: a Demo caller that forgot the argument would
silently ask for Yahoo identity, get UNKNOWN_IDENTITY, and read as a Demo bug.
`providers/yahoo/identity.py` supplies the Yahoo default for the callers that
have always relied on it, so nothing that worked before has to change.

WHAT THIS REPLACES (unchanged from Sprint 6). Through Sprint 5 the only durable
provider-to-DB team link was `teams.email`, written by the season seed as
'yahoo-team-{n}@fantasy-beefs.local' and parsed back out by db/team_resolver.py.
That made a MANAGER EMAIL the load-bearing provider identity — the exact practice
S6-R1 forbids — and its global UNIQUE additionally stopped one manager holding
teams in two leagues. Resolution now reads `teams.provider_team_key` and nothing
else.

THREE WAYS TO FAIL, ALL CLOSED, ALL NAMED:

    UNKNOWN      the key resolves to no row. Not "create it silently", not
                 "fall back to name" — the caller is told the mapping is absent.
    AMBIGUOUS    the key resolves to more than one row. The DB uniqueness makes
                 this nearly unreachable, and it is still checked: a constraint
                 that was dropped or a migration that half-ran must surface as
                 a refusal, not as an arbitrary .first().
    CONFLICTING  the row found by key disagrees with the row found by another
                 supplied identifier — e.g. a caller passes both a key and an
                 internal id and they name different rows.

A RENAMED TEAM STILL RESOLVES, because nothing here reads the name. That is not
a special case in the code; it is the absence of one, and C-4 proves it.

NAME AND EMAIL MATCHING IS NOT DEGRADED, IT IS ABSENT. There is no fallback path
to try when a key misses. `resolve_team_by_name` exists solely to REFUSE — it is
importable so a future caller reaching for it finds a loud, documented refusal
instead of writing their own lookup.

CROSS-PROVIDER COLLISION CANNOT RESOLVE, and it is the `provider` column that
makes that true rather than a convention. Every query below filters on
(provider, key) together, so a Demo league key that happened to spell a Yahoo one
resolves to nothing in a Yahoo-bound league — and `uq_teams_provider_key` is
unique on the same pair, so the two namespaces cannot even be written into each
other.
"""

from __future__ import annotations

from dataclasses import dataclass

from providers.errors import ProviderIdentityError


@dataclass(frozen=True)
class ResolvedLeague:
    """A provider league key bound to an internal League row."""

    league_id: int
    league_key: str
    season: int


class TeamIdentityResolver:
    """Provider team key <-> internal Team.id, for ONE league.

    Built once per ingest and handed around, so a refresh does one query rather
    than one per matchup. Scoped to a league because a provider team ordinal is
    only meaningful inside its league (recon R-5's collision-safety point,
    applied to teams).
    """

    def __init__(self, *, league_id: int, by_key: dict[str, int],
                 by_ordinal: dict[int, int]) -> None:
        self.league_id = league_id
        self._by_key = by_key
        self._by_ordinal = by_ordinal

    def __len__(self) -> int:
        return len(self._by_key)

    def __repr__(self) -> str:
        return (f"TeamIdentityResolver(league_id={self.league_id}, "
                f"{len(self._by_key)} provider keys)")

    @property
    def known_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_key))

    def to_internal(self, team_key: str) -> int:
        """Provider team key -> internal Team.id. Fails closed on unknown."""
        try:
            return self._by_key[team_key]
        except KeyError:
            raise ProviderIdentityError(
                ProviderIdentityError.UNKNOWN,
                f"provider team key {team_key!r} maps to no team in league "
                f"{self.league_id}. Known keys: {list(self.known_keys)!r}. "
                f"Refusing to fall back to a name or email match (S6-R1) and "
                f"refusing to create a team from a scoreboard payload."
            ) from None

    def ordinal_to_internal(self, ordinal: int) -> int:
        """Within-league provider ordinal -> internal Team.id.

        For payloads that quote only the ordinal. Safe ONLY because the resolver
        is league-scoped; the same ordinal in another league is another team,
        which is why this method does not exist at module level.
        """
        try:
            return self._by_ordinal[ordinal]
        except KeyError:
            raise ProviderIdentityError(
                ProviderIdentityError.UNKNOWN,
                f"provider team ordinal {ordinal} maps to no team in league "
                f"{self.league_id}. Known ordinals: "
                f"{sorted(self._by_ordinal)!r}."
            ) from None


def resolve_league(db, *, league_key: str, provider: str) -> ResolvedLeague:
    """Provider league key -> internal League. Fails closed on unknown/ambiguous."""
    from db.schema import League

    rows = (db.query(League)
            .filter(League.provider == provider,
                    League.provider_league_key == league_key)
            .all())
    if not rows:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN,
            f"provider league key {league_key!r} maps to no {provider} League "
            f"row. A league must be bound to its provider identity before it "
            f"can be ingested; refusing to guess from the league name.")
    if len(rows) > 1:
        raise ProviderIdentityError(
            ProviderIdentityError.AMBIGUOUS,
            f"provider league key {league_key!r} maps to {len(rows)} League "
            f"rows ({[r.id for r in rows]!r}). uq_leagues_provider_key should "
            f"make this unreachable; that it happened means the constraint is "
            f"absent. Refusing to pick one.")
    row = rows[0]
    return ResolvedLeague(league_id=row.id, league_key=league_key,
                          season=row.season)


def build_team_identity_resolver(db, *, league_id: int,
                                 provider: str) -> TeamIdentityResolver:
    """Build the per-league team resolver from persisted provider identity.

    Refuses a PARTIAL resolver, matching the all-or-nothing discipline
    db/team_resolver.py already had: a resolver missing one team silently drops
    that team's matchup from a slate, and the Sprint 1-5 freshness gate would
    then compare a short list against a short list and pass.

    A MIXED-PROVIDER ROSTER REFUSES HERE, and that is the same check. A league
    whose teams are half Yahoo and half Demo has some team carrying a provider
    other than the one asked for, so it lands in `unbound` and the resolver
    refuses rather than returning the subset that agrees.
    """
    from db.schema import Team

    rows = (db.query(Team.id, Team.provider, Team.provider_team_key,
                     Team.provider_team_id)
            .filter(Team.league_id == league_id)
            .all())
    if not rows:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN,
            f"league {league_id} has no teams; cannot build a team resolver.")

    unbound = [r.id for r in rows
               if not r.provider_team_key or r.provider != provider]
    if unbound:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN,
            f"{len(unbound)} team(s) in league {league_id} carry no {provider} "
            f"provider identity (team ids {unbound!r}). A partial resolver is "
            f"never returned — it would silently drop those teams' matchups "
            f"from the slate. Bind them with "
            f"providers.identity.bind_team_identity first.")

    by_key: dict[str, int] = {}
    by_ordinal: dict[int, int] = {}
    for row in rows:
        if row.provider_team_key in by_key:
            raise ProviderIdentityError(
                ProviderIdentityError.AMBIGUOUS,
                f"provider team key {row.provider_team_key!r} appears on two "
                f"teams in league {league_id} "
                f"({by_key[row.provider_team_key]} and {row.id}).")
        by_key[row.provider_team_key] = row.id
        if row.provider_team_id is not None:
            if row.provider_team_id in by_ordinal:
                raise ProviderIdentityError(
                    ProviderIdentityError.AMBIGUOUS,
                    f"provider team ordinal {row.provider_team_id} appears on "
                    f"two teams in league {league_id}.")
            by_ordinal[row.provider_team_id] = row.id

    return TeamIdentityResolver(league_id=league_id, by_key=by_key,
                                by_ordinal=by_ordinal)


# ── Binding (the write side) ──────────────────────────────────────────────────

def bind_league_identity(db, *, league_id: int, league_key: str,
                         provider: str) -> None:
    """Bind an internal League to its provider key, once.

    REBINDING TO A DIFFERENT KEY IS A CONFLICT, NOT AN UPDATE. A league already
    bound to 461.l.488800 that is asked to become 461.l.999999 is either a typo
    or two leagues being merged; either way, silently repointing it would make
    every historical row's provider identity retroactively wrong.

    WP2 — REBINDING TO A DIFFERENT PROVIDER IS THE SAME CONFLICT, and it is now
    checked as well. A league bound to Demo cannot become a Yahoo league by
    being re-bound: every Credit already issued was issued against the Demo
    league's own boundaries, and a mid-season provider switch would reinterpret
    them. §9 of the WP2 POR states the rule; this is where it is enforced.
    """
    from db.schema import League

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN, f"league {league_id} not found")

    if league.provider_league_key and league.provider_league_key != league_key:
        raise ProviderIdentityError(
            ProviderIdentityError.CONFLICTING,
            f"league {league_id} is already bound to provider key "
            f"{league.provider_league_key!r}; refusing to rebind it to "
            f"{league_key!r}. Rebinding would make every row already ingested "
            f"under the old key belong to a league it never came from.")

    if league.provider and league.provider != provider:
        raise ProviderIdentityError(
            ProviderIdentityError.CONFLICTING,
            f"league {league_id} is bound to provider {league.provider!r}; "
            f"refusing to rebind it to {provider!r}. A league cannot change "
            f"provider — its frozen season boundaries, its issued Credits and "
            f"every persisted provider key were established under the first "
            f"one.")

    league.provider = provider
    league.provider_league_key = league_key
    db.flush()


def bind_team_identity(db, *, team_id: int, team_key: str,
                       provider: str, team_ordinal: int | None = None) -> None:
    """Bind an internal Team to its provider key, once. Rebinding is a conflict."""
    from db.schema import Team

    team = db.query(Team).filter(Team.id == team_id).first()
    if team is None:
        raise ProviderIdentityError(
            ProviderIdentityError.UNKNOWN, f"team {team_id} not found")

    if team.provider_team_key and team.provider_team_key != team_key:
        raise ProviderIdentityError(
            ProviderIdentityError.CONFLICTING,
            f"team {team_id} is already bound to provider key "
            f"{team.provider_team_key!r}; refusing to rebind it to "
            f"{team_key!r}.")

    clash = (db.query(Team)
             .filter(Team.provider == provider,
                     Team.provider_team_key == team_key,
                     Team.id != team_id)
             .first())
    if clash is not None:
        raise ProviderIdentityError(
            ProviderIdentityError.CONFLICTING,
            f"provider team key {team_key!r} is already bound to team "
            f"{clash.id}; refusing to bind it to team {team_id} as well. One "
            f"provider team is one internal team.")

    team.provider = provider
    team.provider_team_key = team_key
    if team_ordinal is not None:
        team.provider_team_id = team_ordinal
    db.flush()


def resolve_or_create_player(db, *, player_key: str, name: str,
                             position: str | None, nfl_team: str | None,
                             provider: str):
    """Provider player key -> Player row, creating one if the key is new.

    CREATION IS ALLOWED HERE AND NOWHERE ELSE IN THE GATEWAY. A mid-season
    call-up genuinely does not exist on any row yet, and FR-7.30 already
    established that the roster path may insert one. What has changed is the
    KEY: insertion is now keyed on the compound provider_player_key, so
    (a) a same-name player inserts cleanly, since the name is no longer unique
        and is never matched on (recon R-4), and
    (b) the same bare Yahoo player_id under a different game_id is a DIFFERENT
        player rather than a silent collision (recon R-5).

    A team is never created this way — a scoreboard naming an unknown team is a
    slate mismatch and fails closed in TeamIdentityResolver.
    """
    from db.schema import Player

    rows = (db.query(Player)
            .filter(Player.provider == provider,
                    Player.provider_player_key == player_key)
            .all())
    if len(rows) > 1:
        raise ProviderIdentityError(
            ProviderIdentityError.AMBIGUOUS,
            f"provider player key {player_key!r} maps to {len(rows)} Player "
            f"rows {[r.id for r in rows]!r}.")
    if rows:
        return rows[0]

    player = Player(
        name=name,
        position=position or "UNKNOWN",
        nfl_team=nfl_team,
        # The legacy bare id is still written so FR-7.30's existing readers keep
        # working within a season. It is no longer unique and no longer
        # identity; the compound key below is.
        yahoo_id=player_key.rsplit(".", 1)[-1] or None,
        provider=provider,
        provider_player_key=player_key,
    )
    db.add(player)
    db.flush()
    return player


def resolve_team_by_name(*_args, **_kwargs):
    """REFUSES, ALWAYS. Present so the refusal is discoverable.

    S6-R1 lists team display name, manager display name, manager email, payload
    order and inferred arithmetic as never-authoritative. A future caller who
    reaches for a name-based lookup finds this and is told why, rather than
    quietly writing a working one somewhere else in the tree.
    """
    raise ProviderIdentityError(
        ProviderIdentityError.NON_AUTHORITATIVE,
        "team resolution by NAME is not available. S6-R1: team display name, "
        "manager display name and manager email are never authoritative "
        "identity. Use provider_team_key via build_team_identity_resolver.")


def resolve_team_by_email(*_args, **_kwargs):
    """REFUSES, ALWAYS — the Sprint 1-5 email smuggle, closed off by name."""
    raise ProviderIdentityError(
        ProviderIdentityError.NON_AUTHORITATIVE,
        "team resolution by EMAIL is not available. Sprint 1-5 encoded Yahoo "
        "team ordinals into teams.email and parsed them back out; S6-R1 ends "
        "that. Use provider_team_key via build_team_identity_resolver.")
