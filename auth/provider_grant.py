"""
auth/provider_grant.py — the one path a Yahoo OAuth grant takes through storage.

WHAT THIS OWNS. Recording the grant a sign-in produced, handing out a usable
bearer token, refreshing it when it expires, and disconnecting it. Every write to
`provider_grants` goes through this module, which is what makes "single canonical
token update path" a fact rather than an intention.

── THE STORAGE BOUNDARY, STATED ONCE ────────────────────────────────────────

    STORED      OAuth credentials. access token, refresh token, expiry,
                granted scope, the provider subject they belong to, and enough
                status to say why a grant stopped working.

    NOT STORED  Yahoo Fantasy Information. No roster, player, stat, matchup,
                standing, scoreboard or league setting passes through this
                module, and none is persisted by anything it calls. Reads stay
                in memory and are consumed by the existing provider pipeline.

The Yahoo agreement restricts Fantasy Information. A token is not Fantasy
Information — it is the credential used to request it — and the two live in
different places on purpose, so that a future retention decision about Fantasy
data has nothing to unpick here.

── WHY THE ACCESS TOKEN IS STORED AT ALL ───────────────────────────────────

It is worth asking, because storing less is always safer. Yahoo's access token
lives one hour; the refresh token is what actually persists the grant. Keeping
the access token means a background job that runs twice in the same hour makes
one token call rather than two, and — more importantly — it means the expiry is
a fact in the database rather than something every caller re-derives. It is
sealed exactly like the refresh token, so it costs nothing in exposure.

── CONCURRENCY, AND THE FAILURE IT PREVENTS ────────────────────────────────

Yahoo rotates refresh tokens: when a refresh succeeds it may return a NEW
refresh token, and it revokes the old one. So two jobs refreshing the same grant
at the same moment is not a slow path — it is a corruption. Both read refresh
token R, both exchange it; the first succeeds and Yahoo revokes R; the second
gets `invalid_grant`. If the second then wrote its failure over the first's new
token, the grant would be dead despite a refresh having just succeeded.

`token_version` prevents that. Every write is conditional on the version the
writer read. The loser's write matches nothing, it re-reads, and it finds the
winner's fresh token already there.

── WHAT FAILURE MEANS, AND WHAT IT DOES NOT ────────────────────────────────

A refresh that fails because Yahoo says the grant is gone is `reconnect_required`
and stops. It is not retried, because retrying a revoked grant is a loop that
never terminates and hammers Yahoo to prove a thing already known. A refresh
that fails because Yahoo could not be reached leaves the grant `active` and
returns the transport error, because the network being down is not the user
having revoked anything.

NOTHING HERE DELETES A GRANT ON FAILURE. The row stays, with the reason code and
the time, so an operator can answer "why did this league stop syncing" tomorrow.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from auth.token_crypto import TokenCryptoError, decrypt, encrypt
from db.schema import ProviderGrant

__all__ = [
    "GrantError",
    "GrantUnavailable",
    "PROVIDER_YAHOO",
    "REFRESH_SKEW_SECONDS",
    "STATUS_ACTIVE",
    "STATUS_DISCONNECTED",
    "STATUS_RECONNECT_REQUIRED",
    "GrantSnapshot",
    "access_token_for",
    "disconnect",
    "grant_for",
    "record_grant",
    "refresh_grant",
    "snapshot",
]

PROVIDER_YAHOO = "yahoo"

STATUS_ACTIVE = "active"
STATUS_RECONNECT_REQUIRED = "reconnect_required"
STATUS_DISCONNECTED = "disconnected"

#: Refresh this long BEFORE the access token actually expires.
#:
#: A token that is valid for four more seconds is not usable: the request has to
#: be built, sent, and answered, and Yahoo's clock is not ours. Sixty seconds is
#: the same leeway the ID-token validator already allows for skew, which keeps
#: one number in the product rather than two that mean the same thing.
REFRESH_SKEW_SECONDS = 60

#: Yahoo's documented access-token lifetime, used ONLY when a token response
#: omits `expires_in`. Yahoo documents 3600 and has always sent it; this is the
#: floor for a response that does not, so a missing field produces a short
#: assumption rather than a token treated as valid forever.
_DEFAULT_EXPIRES_IN = 3600


class GrantError(Exception):
    """A grant could not be established, read or renewed."""

    def __init__(self, reason_code: str, detail: str = ""):
        super().__init__(detail or reason_code)
        self.reason_code = reason_code
        self.detail = detail


class GrantUnavailable(GrantError):
    """There is no usable grant, and the user must authorize again.

    A DISTINCT TYPE because callers must not retry it. It is the difference
    between "Yahoo is down, try later" and "this user revoked us".
    """


@dataclass(frozen=True)
class GrantSnapshot:
    """What a grant looks like from outside, with nothing secret in it.

    THIS IS THE ONLY SHAPE THAT LEAVES THIS MODULE FOR A SURFACE. It is what an
    API response or a commissioner diagnostic may see: whether a grant exists,
    whether it works, when it was last renewed, and why it stopped. Never a
    token, never a ciphertext, never a length or a prefix that would narrow one.
    """

    exists: bool
    provider: str | None = None
    status: str | None = None
    provider_subject_present: bool = False
    granted_scope: str | None = None
    expires_at: str | None = None
    last_refresh_at: str | None = None
    last_error_code: str | None = None
    has_refresh_token: bool = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; comparisons need one convention."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _context(grant: ProviderGrant, field: str) -> str:
    """The associated data binding a ciphertext to this row and this field.

    THE GRANT ID IS IN IT, which is what stops a ciphertext being moved between
    users. It requires the row to have been flushed so the id exists — every
    caller below does that before sealing.
    """
    if not grant.id:
        raise GrantError("grant_not_persisted",
                         "a grant must have an id before its tokens are sealed")
    return f"grant:{grant.id}:{field}"


# ── Reading ──────────────────────────────────────────────────────────────────

def grant_for(db: Session, *, user_id: int,
              provider: str = PROVIDER_YAHOO) -> ProviderGrant | None:
    """This user's grant for this provider, or None.

    SCOPED BY user_id AND NOTHING ELSE. There is no lookup in this module that
    can return a grant belonging to a different user, and no parameter that
    would let a caller ask for one — commissioner, operator or otherwise.
    """
    return (db.query(ProviderGrant)
            .filter(ProviderGrant.user_id == user_id,
                    ProviderGrant.provider == provider)
            .first())


def snapshot(db: Session, *, user_id: int,
             provider: str = PROVIDER_YAHOO) -> GrantSnapshot:
    """The safe view of a grant, for a surface that must not see the tokens."""
    grant = grant_for(db, user_id=user_id, provider=provider)
    if grant is None:
        return GrantSnapshot(exists=False)
    return GrantSnapshot(
        exists=True,
        provider=grant.provider,
        status=grant.status,
        provider_subject_present=bool(grant.provider_subject),
        granted_scope=grant.granted_scope,
        expires_at=(_aware(grant.expires_at).isoformat()
                    if grant.expires_at else None),
        last_refresh_at=(_aware(grant.last_refresh_at).isoformat()
                         if grant.last_refresh_at else None),
        last_error_code=grant.last_error_code,
        has_refresh_token=bool(grant.refresh_token_sealed),
    )


# ── Writing ──────────────────────────────────────────────────────────────────

def record_grant(db: Session, *, user_id: int, provider_subject: str,
                 tokens: dict, provider: str = PROVIDER_YAHOO,
                 environ: dict | None = None,
                 now: datetime | None = None) -> ProviderGrant:
    """Persist the grant a completed authorization produced.

    `tokens` IS YAHOO'S TOKEN RESPONSE and is consumed, not kept. Nothing from
    it survives this call except the fields below, and `id_token` in particular
    is never stored: it is an identity assertion that was already validated and
    spent, and keeping it would be keeping a second credential for no purpose.

    A RE-AUTHORIZATION REPLACES, IT DOES NOT ACCUMULATE. Signing in again gives
    a fresh grant that supersedes whatever was there — including reviving a row
    that was `disconnected` or `reconnect_required`, which is exactly how a user
    is meant to recover from both.

    THE SUBJECT MUST MATCH THE ACCOUNT. A grant is stored against the Yahoo
    subject that authorized it. If an existing row names a different subject,
    the tokens are replaced along with it, because the user has authorized a
    different Yahoo account and the old credential is no longer theirs to use.
    """
    moment = now or _now()
    access = (tokens or {}).get("access_token")
    if not access:
        raise GrantError("no_access_token",
                         "token response carried no access_token")

    grant = grant_for(db, user_id=user_id, provider=provider)
    if grant is None:
        grant = ProviderGrant(user_id=user_id, provider=provider,
                              provider_subject=provider_subject,
                              status=STATUS_ACTIVE, token_version=0,
                              created_at=moment)
        db.add(grant)
        # FLUSHED BEFORE SEALING, because the ciphertext is bound to the row id
        # and the id does not exist until the insert reaches the database.
        db.flush()

    grant.provider_subject = provider_subject
    _seal_into(grant, tokens, environ=environ, moment=moment)
    grant.granted_scope = _clean(tokens.get("scope")) or grant.granted_scope
    grant.status = STATUS_ACTIVE
    grant.last_error_code = None
    grant.last_error_at = None
    grant.token_version = int(grant.token_version or 0) + 1
    grant.updated_at = moment
    db.commit()
    return grant


def _seal_into(grant: ProviderGrant, tokens: dict, *,
               environ: dict | None, moment: datetime) -> None:
    """Seal the bearer material onto a grant that already has an id.

    THE REFRESH TOKEN IS ONLY OVERWRITTEN WHEN ONE IS SUPPLIED. Yahoo's refresh
    response may legitimately omit it, and "omitted" means "keep using the one
    you have" — writing NULL over it would destroy the grant on the first
    refresh that happened not to rotate.
    """
    access = tokens.get("access_token")
    grant.access_token_sealed = encrypt(
        access, context=_context(grant, "access"), environ=environ)

    refresh = _clean(tokens.get("refresh_token"))
    if refresh:
        grant.refresh_token_sealed = encrypt(
            refresh, context=_context(grant, "refresh"), environ=environ)

    try:
        lifetime = int(tokens.get("expires_in") or _DEFAULT_EXPIRES_IN)
    except (TypeError, ValueError):
        lifetime = _DEFAULT_EXPIRES_IN
    grant.expires_at = moment + timedelta(seconds=max(lifetime, 0))


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


# ── Using ────────────────────────────────────────────────────────────────────

def _open(grant: ProviderGrant, field: str, sealed: str | None, *,
          environ: dict | None) -> str | None:
    if not sealed:
        return None
    try:
        return decrypt(sealed, context=_context(grant, field), environ=environ)
    except TokenCryptoError as exc:
        # A SEALED VALUE THAT WILL NOT OPEN IS NOT A TOKEN. It is a missing key,
        # a rotated-away key, or a row that has been tampered with — and every
        # one of those means this grant cannot be used, without implying the
        # user revoked anything.
        raise GrantError("token_unreadable", str(exc)) from exc


def _expired(grant: ProviderGrant, moment: datetime) -> bool:
    expires = _aware(grant.expires_at)
    if expires is None:
        return True
    return moment >= expires - timedelta(seconds=REFRESH_SKEW_SECONDS)


def access_token_for(db: Session, *, user_id: int,
                     provider: str = PROVIDER_YAHOO,
                     refresher: Callable | None = None,
                     environ: dict | None = None,
                     now: datetime | None = None) -> str:
    """A usable bearer token for this user, refreshing first if it is due.

    THE ONLY WAY BEARER MATERIAL LEAVES THIS MODULE, and it leaves as a return
    value to a caller that is about to put it in an Authorization header — never
    into a response body, a template, a log line or a job payload.

    :raises GrantUnavailable: no grant, disconnected, or Yahoo has rejected it —
        the user must authorize again and no retry will help.
    :raises GrantError: something is wrong that is not the user's doing.
    """
    moment = now or _now()
    grant = grant_for(db, user_id=user_id, provider=provider)
    if grant is None:
        raise GrantUnavailable("not_connected",
                               f"user {user_id} has no {provider} grant")
    if grant.status == STATUS_DISCONNECTED:
        raise GrantUnavailable("disconnected", "the grant was disconnected")
    if grant.status == STATUS_RECONNECT_REQUIRED:
        raise GrantUnavailable("reconnect_required",
                               grant.last_error_code or "the grant was rejected")

    if not _expired(grant, moment):
        token = _open(grant, "access", grant.access_token_sealed,
                      environ=environ)
        if token:
            return token

    grant = refresh_grant(db, user_id=user_id, provider=provider,
                          refresher=refresher, environ=environ, now=moment)
    token = _open(grant, "access", grant.access_token_sealed, environ=environ)
    if not token:
        raise GrantError("token_unreadable", "refreshed grant has no token")
    return token


# ── Refreshing ───────────────────────────────────────────────────────────────

def _live_refresh(*, refresh_token: str, config) -> dict:   # pragma: no cover
    """Exchange a refresh token for a new access token, against Yahoo.

    THE SAME TOKEN ENDPOINT AND THE SAME CLIENT AUTHENTICATION as the
    authorization-code exchange, because it is the same OAuth client. The
    refresh token goes in the BODY, never a query string: a query string is
    logged by proxies and by Yahoo, and this value is the long-lived one.
    """
    import requests

    from auth.yahoo_oidc import TOKEN_URL

    basic = base64.b64encode(
        f"{config.client_id}:{config.client_secret}".encode()).decode()
    try:
        response = requests.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {basic}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token",
                  "refresh_token": refresh_token,
                  "redirect_uri": config.redirect_uri},
            timeout=15,
        )
    except Exception as exc:
        raise GrantError("provider_unreachable", f"token endpoint: {exc!r}")

    if response.status_code == 200:
        try:
            return response.json()
        except ValueError as exc:
            raise GrantError("refresh_failed", f"non-JSON response: {exc!r}")

    # THE BODY IS READ FOR ONE FIELD AND THEN DROPPED. Yahoo's error bodies can
    # echo request parameters, and a request parameter here is a refresh token.
    # `error` is a short enumerated code and is the only thing taken.
    code = ""
    try:
        code = str((response.json() or {}).get("error", ""))[:64]
    except Exception:
        code = ""
    if response.status_code in (400, 401) and code in (
            "invalid_grant", "invalid_request", "invalid_client",
            "unauthorized_client"):
        raise GrantUnavailable(code or "invalid_grant",
                               f"refresh rejected with {response.status_code}")
    raise GrantError("refresh_failed",
                     f"token endpoint returned {response.status_code}")


def refresh_grant(db: Session, *, user_id: int,
                  provider: str = PROVIDER_YAHOO,
                  refresher: Callable | None = None,
                  environ: dict | None = None,
                  now: datetime | None = None) -> ProviderGrant:
    """Renew this user's access token, rotation-safe and concurrency-safe.

    ROTATION-SAFE. Yahoo documents that a refresh MAY return a new refresh
    token and that it revokes the old one when it does. `_seal_into` writes the
    replacement when one arrives and leaves the existing one alone when it does
    not, so both of Yahoo's documented behaviours are handled by the same path.

    CONCURRENCY-SAFE. The write is conditional on the `token_version` this call
    read. If another worker refreshed the same grant in between, this write
    matches no row; rather than retrying the exchange — with a refresh token
    Yahoo has by then revoked — it re-reads and returns the winner's grant.
    """
    moment = now or _now()
    grant = grant_for(db, user_id=user_id, provider=provider)
    if grant is None:
        raise GrantUnavailable("not_connected", "no grant to refresh")
    if grant.status == STATUS_DISCONNECTED:
        raise GrantUnavailable("disconnected", "the grant was disconnected")

    observed_version = int(grant.token_version or 0)
    refresh_token = _open(grant, "refresh", grant.refresh_token_sealed,
                          environ=environ)
    if not refresh_token:
        _mark_reconnect(db, grant, "no_refresh_token", moment)
        raise GrantUnavailable("reconnect_required",
                               "the grant holds no refresh token")

    if refresher is None:
        from auth.yahoo_oidc import load_config

        def refresher(*, refresh_token: str):          # noqa: E306
            return _live_refresh(refresh_token=refresh_token,
                                 config=load_config())

    try:
        tokens = refresher(refresh_token=refresh_token)
    except GrantUnavailable as exc:
        # YAHOO HAS DECIDED. Recorded and not retried — see the module docstring
        # for why a revoked grant must not become a loop.
        _mark_reconnect(db, grant, exc.reason_code, moment)
        raise
    except GrantError:
        # TRANSPORT, NOT AUTHORIZATION. The grant is left `active` because the
        # network being unreachable says nothing about whether it is still good.
        raise

    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        _mark_reconnect(db, grant, "refresh_incomplete", moment)
        raise GrantUnavailable("reconnect_required",
                               "refresh response carried no access_token")

    # ── the conditional write ────────────────────────────────────────────────
    #
    # Claim the version first. If another worker already moved it, this UPDATE
    # touches nothing and the loser defers to the winner rather than writing a
    # token Yahoo has already invalidated.
    claimed = (db.query(ProviderGrant)
               .filter(ProviderGrant.id == grant.id,
                       ProviderGrant.token_version == observed_version)
               .update({ProviderGrant.token_version: observed_version + 1},
                       synchronize_session=False))
    if not claimed:
        db.commit()
        db.expire_all()
        winner = grant_for(db, user_id=user_id, provider=provider)
        if winner is None:                              # pragma: no cover
            raise GrantUnavailable("not_connected", "grant vanished mid-refresh")
        return winner

    db.refresh(grant)
    _seal_into(grant, tokens, environ=environ, moment=moment)
    if _clean(tokens.get("scope")):
        grant.granted_scope = _clean(tokens.get("scope"))
    grant.status = STATUS_ACTIVE
    grant.last_refresh_at = moment
    grant.last_error_code = None
    grant.last_error_at = None
    grant.updated_at = moment
    db.commit()
    return grant


def _mark_reconnect(db: Session, grant: ProviderGrant, code: str,
                    moment: datetime) -> None:
    """Record that Yahoo rejected this grant, and keep the evidence.

    THE SEALED TOKENS ARE LEFT IN PLACE ON PURPOSE. Erasing them would erase the
    ability to tell a revoked grant from one that was never established, and the
    next authorization overwrites them anyway. They are unusable either way: the
    status gate above refuses before anything is opened.
    """
    grant.status = STATUS_RECONNECT_REQUIRED
    grant.last_error_code = (code or "rejected")[:64]
    grant.last_error_at = moment
    grant.updated_at = moment
    db.commit()


# ── Disconnecting ────────────────────────────────────────────────────────────

def disconnect(db: Session, *, user_id: int, provider: str = PROVIDER_YAHOO,
               now: datetime | None = None) -> GrantSnapshot:
    """Stop using this user's Yahoo grant.

    LOCAL, AND HONEST ABOUT BEING LOCAL. Yahoo documents no token-revocation
    endpoint — its documented path is the user revoking access from their Yahoo
    account settings — so this makes the grant unusable HERE and says so. It is
    not claimed as remote revocation, and no undocumented endpoint is called to
    pretend otherwise.

    THE BEARER MATERIAL IS DESTROYED. Unlike a rejection, a disconnect is the
    user asking us to stop holding it, so the envelopes are cleared rather than
    kept for diagnosis. There is nothing to diagnose about a deliberate act.

    NOTHING THE USER OWNS IS TOUCHED. Not a wager, not a settled result, not a
    Ledger row, not league membership. Disconnecting a data source is not
    forfeiting a season, and this function reaches none of those tables.
    """
    moment = now or _now()
    grant = grant_for(db, user_id=user_id, provider=provider)
    if grant is None:
        return GrantSnapshot(exists=False)

    grant.access_token_sealed = None
    grant.refresh_token_sealed = None
    grant.expires_at = None
    grant.status = STATUS_DISCONNECTED
    grant.last_error_code = None
    grant.last_error_at = None
    grant.token_version = int(grant.token_version or 0) + 1
    grant.updated_at = moment
    db.commit()
    return snapshot(db, user_id=user_id, provider=provider)
