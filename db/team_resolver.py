"""
db/team_resolver.py — Yahoo-to-DB team ID resolver.

THE EMAIL BRIDGE IS GONE (S6-R1, Opus blocker 2).

Through Sprint 5 this module was the canonical resolver and it worked by parsing
a Yahoo team ordinal back out of `teams.email`, which the season seed wrote as
'yahoo-team-{id}@fantasy-beefs.local'. That made a MANAGER EMAIL the load-bearing
provider identity — precisely what S6-R1 forbids — and its global UNIQUE
additionally stopped one manager holding teams in two leagues.

Sprint 6 added `teams.provider_team_key` and
`providers/yahoo/identity.py::build_team_identity_resolver` as the authoritative
replacement, but left THIS module intact. Opus correctly found that the gap was
not dormant debt: `POST /admin/tuesday-sync` reaches
`notifications/tuesday_sync.py`, which called `build_team_resolver` on three
separate steps. The legacy email path was live in production while the gateway
had no production caller at all.

WHAT THIS MODULE IS NOW. A thin, compatibility-preserving ADAPTER over the
Sprint 6 provider identity resolver. `build_team_resolver` keeps its name and
its two-way `yahoo_to_db` / `db_to_yahoo` surface — so every existing caller
keeps working with no ripple — but every lookup it answers is backed by
`teams.provider_team_key` and NOTHING ELSE. There is no email fallback, because
a fallback is exactly how an abolished identity path stays alive.

`_parse_yahoo_id_from_email` is retained ONLY as a loud refusal. It is
importable so that anything reaching for the old behaviour finds a documented
error instead of quietly reimplementing the parser somewhere else in the tree.

FAIL CLOSED, UNCHANGED IN SPIRIT. The old module already refused to return a
partial resolver, and that discipline is preserved: unknown, ambiguous and
conflicting identity all raise. The difference is only WHICH fact is consulted.

Public API
----------
build_team_resolver(db, league_id) -> TeamResolver
    Builds both directions from persisted provider identity. Raises
    TeamResolverError if any team in the league carries no provider identity —
    a partial resolver is never returned.

TeamResolver
    .yahoo_to_db(yahoo_id: int) -> int      Yahoo within-league ordinal -> Team.id
    .db_to_yahoo(db_id:   int) -> int       Team.id -> Yahoo within-league ordinal
    .provider_key_to_db(key: str) -> int    Full compound key -> Team.id
    .db_to_provider_key(db_id: int) -> str  Team.id -> full compound key

TeamResolverError(Exception)
    Raised on construction failure or on any unrecognised lookup. Also the class
    raised for a refused email/name lookup, so a caller catching it already
    handles the refusal.
"""

from __future__ import annotations

from sqlalchemy.orm import Session


class TeamResolverError(Exception):
    pass


class TeamResolver:
    """Two-way mapping between Yahoo team identity and database Team.id values.

    Backed by `teams.provider_team_key`. The `yahoo_to_db` direction takes the
    provider's WITHIN-LEAGUE ordinal, which is safe only because a resolver
    instance is scoped to one league — the same ordinal in another league is a
    different team. That scoping is why no module-level ordinal lookup exists.
    """

    def __init__(
        self,
        yahoo_to_db: dict[int, int],
        db_to_yahoo: dict[int, int],
        key_to_db: dict[str, int] | None = None,
        db_to_key: dict[int, str] | None = None,
        league_id: int | None = None,
    ) -> None:
        self._y2d = yahoo_to_db
        self._d2y = db_to_yahoo
        self._k2d = key_to_db or {}
        self._d2k = db_to_key or {}
        self.league_id = league_id

    def yahoo_to_db(self, yahoo_id: int) -> int:
        """Return the DB Team.id for the given Yahoo within-league team ordinal."""
        try:
            return self._y2d[int(yahoo_id)]
        except (KeyError, TypeError, ValueError):
            raise TeamResolverError(
                f"Yahoo team ordinal {yahoo_id!r} is not bound to any team in "
                f"league {self.league_id} (known ordinals: {sorted(self._y2d)}). "
                f"Resolution is by persisted provider identity only — there is "
                f"no email or name fallback (S6-R1)."
            ) from None

    def db_to_yahoo(self, db_id: int) -> int:
        """Return the Yahoo within-league team ordinal for the given Team.id."""
        try:
            return self._d2y[db_id]
        except KeyError:
            raise TeamResolverError(
                f"DB team ID {db_id} not found in resolver "
                f"(known DB IDs: {sorted(self._d2y)})"
            ) from None

    def provider_key_to_db(self, provider_team_key: str) -> int:
        """Return the DB Team.id for a full compound provider team key.

        The preferred lookup. The compound key ('461.l.488800.t.7') is
        collision-safe across leagues and seasons; the bare ordinal is not, and
        is only usable here because this resolver is league-scoped.
        """
        try:
            return self._k2d[provider_team_key]
        except KeyError:
            raise TeamResolverError(
                f"provider team key {provider_team_key!r} maps to no team in "
                f"league {self.league_id} (known keys: {sorted(self._k2d)})"
            ) from None

    def db_to_provider_key(self, db_id: int) -> str:
        try:
            return self._d2k[db_id]
        except KeyError:
            raise TeamResolverError(
                f"DB team ID {db_id} has no provider team key")

    def __len__(self) -> int:
        return len(self._y2d)

    def __repr__(self) -> str:
        return (f"TeamResolver(league_id={self.league_id}, {len(self)} teams, "
                f"provider-identity-backed)")


def _parse_yahoo_id_from_email(email: str):
    """REFUSES, ALWAYS. The Sprint 1-5 email identity bridge, closed by name.

    Retained as an importable refusal rather than deleted so that any caller
    reaching for the old behaviour — or any reviewer grepping for it — lands on
    this explanation instead of a working parser somewhere else.
    """
    raise TeamResolverError(
        "parsing a Yahoo team ordinal out of teams.email is no longer "
        "supported. S6-R1: manager email is never authoritative provider "
        "identity, and Sprint 6 additionally dropped the global UNIQUE that "
        "made one manager unable to hold teams in two leagues. Use "
        "build_team_resolver, which reads teams.provider_team_key."
    )


def build_team_resolver(db: Session, league_id: int) -> TeamResolver:
    """
    Build a two-way Yahoo-identity <-> DB-ID mapping for all teams in the league.

    Reads `teams.provider_team_key` (and `teams.provider_team_id`) — never
    `teams.email`, never `teams.team_name`, never `teams.owner`.

    Delegates to `providers.yahoo.identity.build_team_identity_resolver` so
    there is exactly ONE implementation of provider team resolution in the
    repository. This function is an adapter that preserves the legacy call
    surface; it is not a second resolver, and it applies no rule of its own.

    Raises
    ------
    TeamResolverError
        If the league has no teams, if ANY team carries no provider identity,
        or if two teams claim the same provider identity. A partial resolver is
        never returned — one missing team silently drops that team's matchup
        from a slate, and the freshness gate would then compare a short list
        against a short list and pass.
    """
    from providers.errors import ProviderIdentityError
    from providers.yahoo.identity import build_team_identity_resolver

    try:
        provider_resolver = build_team_identity_resolver(db, league_id=league_id)
    except ProviderIdentityError as exc:
        # Translated, not swallowed. Legacy callers catch TeamResolverError;
        # re-raising the provider error unchanged would slip past them and
        # surface as an unhandled exception two frames up. `__cause__` keeps the
        # original reason (UNKNOWN / AMBIGUOUS / CONFLICTING) attached.
        raise TeamResolverError(
            f"cannot build a provider-identity resolver for league "
            f"{league_id}: {exc}"
        ) from exc

    from db.schema import Team

    rows = (db.query(Team.id, Team.provider_team_key, Team.provider_team_id)
            .filter(Team.league_id == league_id)
            .all())

    yahoo_to_db: dict[int, int] = {}
    db_to_yahoo: dict[int, int] = {}
    key_to_db: dict[str, int] = {}
    db_to_key: dict[int, str] = {}
    missing_ordinal: list[int] = []

    for row in rows:
        key_to_db[row.provider_team_key] = row.id
        db_to_key[row.id] = row.provider_team_key
        ordinal = row.provider_team_id
        if ordinal is None:
            # Derive from the compound key's tail rather than refusing: the key
            # is authoritative and the ordinal is a convenience column that
            # older bindings may not have populated. An unparseable tail is a
            # real failure and is reported.
            tail = str(row.provider_team_key).rsplit(".", 1)[-1]
            try:
                ordinal = int(tail)
            except ValueError:
                missing_ordinal.append(row.id)
                continue
        if ordinal in yahoo_to_db:
            raise TeamResolverError(
                f"Yahoo team ordinal {ordinal} is claimed by two teams in "
                f"league {league_id} ({yahoo_to_db[ordinal]} and {row.id}); "
                f"refusing to pick one.")
        yahoo_to_db[ordinal] = row.id
        db_to_yahoo[row.id] = ordinal

    if missing_ordinal:
        raise TeamResolverError(
            f"{len(missing_ordinal)} team(s) in league {league_id} carry a "
            f"provider team key with no parseable within-league ordinal "
            f"(team ids {missing_ordinal}). A partial resolver is never "
            f"returned.")

    # Cross-check against the provider resolver rather than trusting this
    # module's own read. If the two disagree there are two sources of truth,
    # which is the condition this adapter exists to prevent.
    if len(provider_resolver) != len(key_to_db):
        raise TeamResolverError(
            f"provider resolver sees {len(provider_resolver)} teams but this "
            f"adapter mapped {len(key_to_db)} for league {league_id}; refusing "
            f"to serve a resolver built on a disagreement.")

    return TeamResolver(yahoo_to_db, db_to_yahoo, key_to_db, db_to_key,
                        league_id=league_id)