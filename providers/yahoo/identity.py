"""D — Yahoo identity. The Yahoo DEFAULT over the provider-neutral resolver.

WP2 MOVED THE IMPLEMENTATION TO `providers/identity.py` AND LEFT THIS BEHIND ON
PURPOSE. Nothing in the resolver was ever Yahoo-specific — it read
`teams.provider_team_key`, refused name and email matching, and refused partial
resolvers, for whichever provider it was given. What WAS Yahoo-specific is the
single line `PROVIDER = "yahoo"` and the fact that every function defaulted to
it, which is exactly what this module still is.

WHY A SHIM RATHER THAN A REWRITE OF EVERY CALL SITE. Twenty-six modules import
these names, several of them certified Sprint 6 and WP1 suites whose whole value
is that they have not changed. Re-pointing all of them would have made a
provider-package refactor look like a change to identity behaviour, and the
diff would have buried the one thing that did change. Every function below is
the neutral one with `provider` pre-filled; there is no second implementation
and there is nothing here that can drift from `providers/identity.py`.

A NON-YAHOO CALLER MUST NOT COME THROUGH THIS MODULE. `providers/demo/` imports
`providers.identity` directly and passes its own provider name. Importing the
Yahoo package to resolve a Demo team would be a dependency from one provider
adapter to another, which is the fence WP2 exists to draw.
"""

from __future__ import annotations

from providers.identity import (  # noqa: F401  (re-exported by design)
    ResolvedLeague,
    TeamIdentityResolver,
    resolve_team_by_email,
    resolve_team_by_name,
)
from providers.identity import (
    bind_league_identity as _bind_league_identity,
    bind_team_identity as _bind_team_identity,
    build_team_identity_resolver as _build_team_identity_resolver,
    resolve_league as _resolve_league,
    resolve_or_create_player as _resolve_or_create_player,
)

PROVIDER = "yahoo"


def resolve_league(db, *, league_key: str, provider: str = PROVIDER):
    """Yahoo league key -> internal League. See providers.identity."""
    return _resolve_league(db, league_key=league_key, provider=provider)


def build_team_identity_resolver(db, *, league_id: int,
                                 provider: str = PROVIDER):
    """The league-scoped Yahoo team resolver. See providers.identity."""
    return _build_team_identity_resolver(db, league_id=league_id,
                                         provider=provider)


def bind_league_identity(db, *, league_id: int, league_key: str,
                         provider: str = PROVIDER) -> None:
    """Bind a League to its Yahoo key, once. See providers.identity."""
    _bind_league_identity(db, league_id=league_id, league_key=league_key,
                          provider=provider)


def bind_team_identity(db, *, team_id: int, team_key: str,
                       team_ordinal: int | None = None,
                       provider: str = PROVIDER) -> None:
    """Bind a Team to its Yahoo key, once. See providers.identity."""
    _bind_team_identity(db, team_id=team_id, team_key=team_key,
                        team_ordinal=team_ordinal, provider=provider)


def resolve_or_create_player(db, *, player_key: str, name: str,
                             position: str | None, nfl_team: str | None,
                             provider: str = PROVIDER):
    """Yahoo player key -> Player row. See providers.identity."""
    return _resolve_or_create_player(db, player_key=player_key, name=name,
                                     position=position, nfl_team=nfl_team,
                                     provider=provider)
