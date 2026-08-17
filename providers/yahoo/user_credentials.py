"""
providers/yahoo/user_credentials.py — whose Yahoo authorization a read runs on.

WHAT THIS OWNS. Answering one question for the provider layer: given a league,
which user's Yahoo grant authorizes reads for it, and what is the current bearer
token for that grant. It owns no HTTP, no parsing and no schema — it is the join
between `auth/provider_grant.py`, which holds credentials, and
`providers/yahoo/transport.py`, which makes requests.

── WHAT IT REPLACES, AND WHY THAT MATTERS ──────────────────────────────────

Before this module every Yahoo read in the product used ONE credential, loaded
by `transport.load_credentials()` from `YAHOO_PRIVATE_JSON` or
`secrets/private.json`. That credential belongs to whoever set up the
repository. It is the same credential for every league, it is not connected to
any user's consent, and it cannot represent a commissioner who leaves, a league
that changes hands, or a user who revokes access.

It is also, measurably, not the thing standing between this product and the
Yahoo Fantasy API. WP2B established that the credential refreshes successfully
and that every Fantasy resource still returns 403 — including `game/nfl`, which
needs no league access at all. That is an application-registration condition,
not a credential one, and nothing in this module changes it. What this module
changes is the ARCHITECTURE: when the application is approved, reads will run on
the authorization the league's commissioner actually gave, which is the only
model that can be operated in production.

── THE CREDENTIAL OWNER ────────────────────────────────────────────────────

`League.provider_credential_user_id` names the user whose grant speaks for a
league. It is set when a commissioner connects the league, and it is durable —
which is what lets a background job run at 3am with nobody signed in.

NULL IS A REAL ANSWER AND IT FAILS CLOSED. A league with no credential owner has
nobody who has authorized Yahoo reads for it, and this module raises rather than
falling back to the operator credential. Falling back is precisely the behaviour
being removed: it would mean the product silently kept working on one person's
personal Yahoo account and nobody would notice until that account changed.

── WHAT IT WILL NOT DO ─────────────────────────────────────────────────────

IT WILL NOT LEND A TOKEN. There is no argument to any function here that lets a
caller name a user other than the league's own credential owner, and no
commissioner or operator path that widens it. A commissioner administers a
league; that is not the same as holding another member's Yahoo credential, and
the code offers no way to conflate them.

IT WILL NOT LOG A TOKEN. The bearer value is returned to exactly one caller and
put in one header. Nothing here formats it, stores it, or puts it in an object
that could be repr'd into a log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from auth.provider_grant import (
    PROVIDER_YAHOO, GrantError, GrantUnavailable, access_token_for, snapshot,
)
from db.schema import League

__all__ = [
    "CredentialOwnerMissing",
    "LeagueCredential",
    "bearer_for_league",
    "credential_owner_id",
    "league_credential_state",
    "set_credential_owner",
]


class CredentialOwnerMissing(GrantUnavailable):
    """This league has nobody whose Yahoo authorization it can read on.

    A SUBTYPE OF `GrantUnavailable` because a caller should treat it the same
    way: it is not retryable, and the remedy is a person authorizing, not a
    later attempt. It is distinct so a diagnostic can tell "no commissioner has
    connected this league" from "the commissioner's grant was revoked".
    """


@dataclass(frozen=True)
class LeagueCredential:
    """Who a league's Yahoo reads run on, with nothing secret in it."""

    league_id: int
    owner_user_id: int | None
    connected: bool
    status: str | None
    reason_code: str | None = None


def credential_owner_id(db: Session, *, league_id: int) -> int | None:
    """The user whose Yahoo grant authorizes this league's reads, if any."""
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        return None
    return league.provider_credential_user_id


def set_credential_owner(db: Session, *, league_id: int, user_id: int) -> None:
    """Record whose authorization this league's Yahoo reads run on.

    CALLED WHEN A COMMISSIONER CONNECTS THE LEAGUE, and it records a fact rather
    than granting a permission: whether that user MAY connect the league is
    decided by the existing commissioner guards before this is reached, and this
    function deliberately checks nothing about authority so that it cannot
    become a second, weaker place where that decision is made.
    """
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise CredentialOwnerMissing("league_not_found",
                                     f"league {league_id} does not exist")
    league.provider_credential_user_id = user_id
    db.commit()


def league_credential_state(db: Session, *, league_id: int) -> LeagueCredential:
    """The safe view: whether this league can read Yahoo, and why not.

    FOR A COMMISSIONER DIAGNOSTIC, never for a player surface and never carrying
    bearer material. It reports the grant's STATUS, which is a product fact, and
    nothing about the credential itself.
    """
    owner = credential_owner_id(db, league_id=league_id)
    if owner is None:
        return LeagueCredential(league_id=league_id, owner_user_id=None,
                                connected=False, status=None,
                                reason_code="no_credential_owner")
    state = snapshot(db, user_id=owner, provider=PROVIDER_YAHOO)
    if not state.exists:
        return LeagueCredential(league_id=league_id, owner_user_id=owner,
                                connected=False, status=None,
                                reason_code="not_connected")
    return LeagueCredential(
        league_id=league_id, owner_user_id=owner,
        connected=state.status == "active",
        status=state.status,
        reason_code=(None if state.status == "active"
                     else (state.last_error_code or state.status)))


def bearer_for_league(db: Session, *, league_id: int,
                      refresher: Callable | None = None,
                      environ: dict | None = None) -> str:
    """A usable Yahoo bearer token for this league's reads.

    THE ONLY FUNCTION IN THE PROVIDER LAYER THAT PRODUCES BEARER MATERIAL, and
    it produces it for the league's own credential owner or not at all.

    :raises CredentialOwnerMissing: nobody has connected Yahoo for this league.
    :raises GrantUnavailable: the owner's grant is disconnected or was rejected
        by Yahoo — a person must authorize again.
    :raises GrantError: something else went wrong; retrying may help.
    """
    owner = credential_owner_id(db, league_id=league_id)
    if owner is None:
        raise CredentialOwnerMissing(
            "no_credential_owner",
            f"league {league_id} has no Yahoo credential owner; a commissioner "
            f"must connect the league before its reads can be authorized")
    return access_token_for(db, user_id=owner, provider=PROVIDER_YAHOO,
                            refresher=refresher, environ=environ)


def _unused() -> None:                    # pragma: no cover - import anchor
    """Keeps `GrantError` in this module's namespace for callers importing it.

    Callers catch `GrantError` from here rather than reaching past this module
    into `auth.provider_grant`, so the provider layer has one import surface for
    credential failure.
    """
    raise GrantError("unused", "not called")
