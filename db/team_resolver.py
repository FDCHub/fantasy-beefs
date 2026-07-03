"""
db/team_resolver.py — canonical Yahoo-to-DB team ID resolver.

The only durable link between Yahoo's per-league team IDs (1-12) and the
database Team.id values is the teams.email field, written by the season seed
as 'yahoo-team-{yahoo_id}@fantasy-beefs.local'.

This module is the single door for any code that needs to cross that boundary.
Do not copy the email parser elsewhere.

Public API
----------
build_team_resolver(db, league_id) -> TeamResolver
    Queries the teams table once, builds both directions of the mapping, and
    raises TeamResolverError if any team's email is unparseable.  A partial
    resolver is never returned — every team must resolve or the build fails.

TeamResolver
    .yahoo_to_db(yahoo_id: int) -> int
    .db_to_yahoo(db_id:   int) -> int
    Both raise TeamResolverError for unrecognised IDs.

TeamResolverError(Exception)
    Raised on construction failure (bad email pattern) or on any lookup that
    references an ID not in the resolver's map.
"""

from __future__ import annotations

from sqlalchemy.orm import Session


class TeamResolverError(Exception):
    pass


class TeamResolver:
    """Two-way mapping between Yahoo fantasy team IDs and database Team.id values."""

    def __init__(
        self,
        yahoo_to_db: dict[int, int],
        db_to_yahoo: dict[int, int],
    ) -> None:
        self._y2d = yahoo_to_db
        self._d2y = db_to_yahoo

    def yahoo_to_db(self, yahoo_id: int) -> int:
        """Return the DB Team.id for the given Yahoo team ID."""
        try:
            return self._y2d[yahoo_id]
        except KeyError:
            raise TeamResolverError(
                f"Yahoo team ID {yahoo_id} not found in resolver "
                f"(known Yahoo IDs: {sorted(self._y2d)})"
            )

    def db_to_yahoo(self, db_id: int) -> int:
        """Return the Yahoo team ID for the given DB Team.id."""
        try:
            return self._d2y[db_id]
        except KeyError:
            raise TeamResolverError(
                f"DB team ID {db_id} not found in resolver "
                f"(known DB IDs: {sorted(self._d2y)})"
            )

    def __len__(self) -> int:
        return len(self._y2d)

    def __repr__(self) -> str:
        return f"TeamResolver({len(self)} teams, league mapping: {dict(sorted(self._y2d.items()))})"


def _parse_yahoo_id_from_email(email: str) -> int | None:
    """
    Parse the Yahoo team ID from 'yahoo-team-{id}@fantasy-beefs.local'.
    Returns None if the email does not match this pattern.
    """
    try:
        local = email.split("@")[0]
        if local.startswith("yahoo-team-"):
            return int(local[len("yahoo-team-"):])
    except (ValueError, IndexError):
        pass
    return None


def build_team_resolver(db: Session, league_id: int) -> TeamResolver:
    """
    Build a two-way Yahoo-ID <-> DB-ID mapping for all teams in the league.

    Reads teams.email for every team in the league and parses the Yahoo team
    ID embedded in the 'yahoo-team-{id}@fantasy-beefs.local' format.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.
    league_id : int
        Internal database league ID.

    Returns
    -------
    TeamResolver
        Populated with yahoo_id <-> db_id mappings for every team.

    Raises
    ------
    TeamResolverError
        If the league has no teams, or if any team's email fails to parse.
        A partial resolver is never returned.
    """
    from db.schema import Team  # local import — avoids circular at module load

    rows = (
        db.query(Team.id, Team.email)
        .filter(Team.league_id == league_id)
        .all()
    )

    if not rows:
        raise TeamResolverError(
            f"No teams found for league_id={league_id} — "
            f"cannot build team resolver"
        )

    yahoo_to_db: dict[int, int] = {}
    db_to_yahoo: dict[int, int] = {}
    bad: list[str] = []

    for db_id, email in rows:
        yahoo_id = _parse_yahoo_id_from_email(email)
        if yahoo_id is None:
            bad.append(f"team_id={db_id} email={email!r}")
        else:
            yahoo_to_db[yahoo_id] = db_id
            db_to_yahoo[db_id]    = yahoo_id

    if bad:
        raise TeamResolverError(
            f"Cannot parse Yahoo team ID from email for "
            f"{len(bad)} team(s): {'; '.join(bad)}"
        )

    return TeamResolver(yahoo_to_db, db_to_yahoo)
