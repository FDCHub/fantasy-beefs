"""A — transport and auth. The single Yahoo credential path (§3).

BEFORE SPRINT 6 THERE WERE THREE. `yahoo_auth.py` read secrets/yahoo_oauth.json
at MODULE IMPORT TIME, `notifications/tuesday_sync.py::_build_yahoo_query` read
the env vars with a secrets/ fallback, and each caller that wanted a query built
its own. Consolidating them is not tidiness: three credential paths are three
places a token can leak into a log, and §3 requires exactly one.

CREDENTIALS ARE NEVER RETURNED, LOGGED, REPR'D OR STORED ON THE DTO. The token
dict lives inside the query object this module hands to yfpy and nowhere else.
`YahooLiveTransport.__repr__` is overridden precisely because the default one
would print `self._token`.

NOTHING HERE IS IMPORTED AT MODULE LOAD. `yfpy` is imported inside the method
that needs it, so an environment with no yfpy installed — which is every offline
certification run — can still import this module to assert that constructing a
live transport refuses. That assertion is C-1's evidence.

OFFLINE RUNS MUST NOT REACH THIS CLASS AT ALL. providers/fixtures/replay.py
supplies a FixtureTransport satisfying the same ProviderTransport interface;
certification asserts the transport in use is that one (C-1).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

from providers.errors import ProviderCredentialError, ProviderTransportError

#: Yahoo's NFL game id. Kept here rather than at each call site because it is a
#: transport-level fact about which Yahoo game we speak to, and because it is
#: the segment that scopes every provider key to a season (recon R-5).
DEFAULT_GAME_ID = 461

#: Every key whose VALUE is credential material. Used by the scrubber in
#: providers/fixtures/record.py, and defined here — beside the code that reads
#: them — so a new credential field cannot be added to the loader without the
#: scrubber's list being right next to it.
CREDENTIAL_KEYS = frozenset({
    "access_token", "refresh_token", "consumer_key", "consumer_secret",
    "client_id", "client_secret", "token", "guid", "id_token",
    "yahoo_access_token_json", "authorization", "Authorization",
    "xoauth_yahoo_guid",
})


def load_credentials(*, environ: dict | None = None,
                     secrets_dir: str | None = None) -> dict:
    """Assemble the Yahoo token dict from exactly two supported sources.

    Priority, unchanged from the accepted Sprint 1-5 behavior so no deployment
    has to be reconfigured:

      1. YAHOO_PRIVATE_JSON + YAHOO_CONSUMER_SECRET env vars (Railway, where
         secrets/ is not deployed);
      2. secrets/private.json + secrets/yahoo_oauth.json (local dev).

    Raises ProviderCredentialError — not a generic error, and not a silent
    empty dict — when neither source is complete. An empty-dict return would
    let a live transport be constructed and fail much later at the API boundary,
    where the failure looks like a Yahoo outage rather than a missing secret.
    """
    environ = os.environ if environ is None else environ

    private_env = environ.get("YAHOO_PRIVATE_JSON", "")
    secret_env = environ.get("YAHOO_CONSUMER_SECRET", "")
    if private_env and secret_env:
        try:
            token = json.loads(private_env)
        except json.JSONDecodeError as exc:
            raise ProviderCredentialError(
                f"YAHOO_PRIVATE_JSON is set but is not valid JSON: {exc}"
            ) from exc
        token["consumer_secret"] = secret_env
        return token

    root = secrets_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "secrets")
    private_path = os.path.join(root, "private.json")
    oauth_path = os.path.join(root, "yahoo_oauth.json")
    if not (os.path.exists(private_path) and os.path.exists(oauth_path)):
        raise ProviderCredentialError(
            "no Yahoo credentials available: neither YAHOO_PRIVATE_JSON + "
            "YAHOO_CONSUMER_SECRET nor secrets/private.json + "
            "secrets/yahoo_oauth.json is present. Offline certification is "
            "expected to hit this — it must use providers.fixtures.replay "
            "instead of a live transport.")

    with open(private_path) as handle:
        token = json.load(handle)
    with open(oauth_path) as handle:
        token["consumer_secret"] = json.load(handle)["consumer_secret"]
    return token


class YahooLiveTransport:
    """Live Yahoo access via yfpy. Satisfies providers.base.ProviderTransport.

    Constructed lazily: the yfpy query is built on first use, so an offline
    process can hold a reference without a network stack or a credential ever
    being touched.

    ── YAHOO-LIVE-1-FIX · WHOSE CREDENTIAL THIS RUNS ON ─────────────────────

    A TOKEN PROVIDER IS REQUIRED, AND THERE IS NO DEFAULT. Until this change the
    transport loaded a repository-level operator credential itself, which meant
    every Yahoo read in the product ran on one person's Yahoo account regardless
    of which league was being read or who had authorized anything. Worse, it did
    so SILENTLY: a production league with no credential owner did not fail — it
    quietly succeeded on somebody else's grant.

    So the constructor now takes a `token_provider`, a zero-argument callable
    that returns a currently-valid bearer token, and REFUSES without one. The
    transport does not know, and must not know, which user that token belongs
    to; resolving that is `providers/yahoo/user_credentials.py`'s job, from the
    league's own `provider_credential_user_id`. A transport that could guess
    would eventually guess wrong in a way nobody noticed.

    IT DOES NOT REFRESH, AND MUST NOT. The canonical refresh path — expiry,
    rotation, concurrency, reconnect-required — lives in
    `auth/provider_grant.py`. The provider callable is invoked for every query
    this transport builds, so a token that expired between two reads is renewed
    by the store rather than by a second implementation drifting from the first.

    OPERATOR CREDENTIALS ARE STILL REACHABLE, BUT ONLY BY NAME. WP2B's live
    evidence tooling and the offline certification gate both legitimately test
    `load_credentials()`, so `for_operator_tooling()` exists — a separate,
    explicitly-named constructor that production code does not call and cannot
    reach by omission. Forgetting an argument now raises; it does not fall back.
    """

    provider = "yahoo"

    def __init__(self, *, token_provider: Callable[[], str] | None = None,
                 game_id: int = DEFAULT_GAME_ID,
                 environ: dict | None = None,
                 secrets_dir: str | None = None,
                 query_factory: Callable | None = None,
                 _operator_credentials: bool = False) -> None:
        if token_provider is None and not _operator_credentials:
            # FAIL CLOSED, AND SAY WHY. A missing token provider is a wiring
            # mistake in this repository, not a user condition, and the message
            # names the seam that supplies one rather than the credential that
            # used to be loaded here.
            raise ProviderCredentialError(
                "YahooLiveTransport requires a token_provider naming whose "
                "Yahoo authorization the read runs on. Production callers get "
                "one from providers.yahoo.user_credentials."
                "token_provider_for_league(db, league_id=...). There is no "
                "operator-credential fallback: a league with no credential "
                "owner must fail rather than read on somebody else's grant.")
        self._token_provider = token_provider
        self._operator_credentials = _operator_credentials
        self._game_id = game_id
        self._environ = environ
        self._secrets_dir = secrets_dir
        self._query_factory = query_factory
        self._queries: dict[str, Any] = {}
        self._observed_at = datetime.now(timezone.utc)

    @classmethod
    def for_operator_tooling(cls, **kwargs) -> "YahooLiveTransport":
        """A transport on the repository-level operator credential.

        FOR DEVELOPER AND CERTIFICATION TOOLING ONLY, and named so that it
        cannot be selected by accident. Nothing in the production request path
        calls this, and a test asserts that.

        It exists because WP2B's live probe and the offline certification gate
        both need the operator path to remain exercisable — the measured
        evidence that the credential refreshes while the Fantasy API refuses is
        the most useful fact the project holds about the external blocker, and
        deleting the code that produced it to satisfy a source scan would throw
        that away.
        """
        return cls(_operator_credentials=True, **kwargs)

    def __repr__(self) -> str:
        # Overridden ON PURPOSE. The default dataclass-free repr would render
        # self._queries, whose yfpy objects hold the access token; this class
        # exists on a code path that gets logged.
        mode = "operator" if self._operator_credentials else "per-user"
        return (f"<YahooLiveTransport game_id={self._game_id} mode={mode} "
                f"(credentials hidden)>")

    # ── Yahoo key handling ────────────────────────────────────────────────────

    @staticmethod
    def league_number(league_key: str) -> str:
        """The bare league number out of a compound key, for yfpy.

        yfpy takes the league NUMBER and the game id separately, so the compound
        key has to be taken apart exactly here — at the transport edge — and
        nowhere else. Everything above this line uses the compound key, which is
        what makes identity collision-safe across seasons.
        """
        parts = league_key.split(".")
        if len(parts) >= 3 and parts[-2] == "l":
            return parts[-1]
        return league_key

    def _token(self) -> dict:
        """The credential dict for one query, from whichever source applies.

        THE PER-USER PATH ASKS THE STORE EVERY TIME. `token_provider` resolves
        through `auth/provider_grant.py`, which refreshes if the hour is up — so
        a long-running worker gets a live token on its second read rather than a
        stale one it would have to notice and renew itself.

        NO REFRESH TOKEN IS HANDED DOWNSTREAM. yfpy is given a bearer and
        nothing else, deliberately: if it held a refresh token it could renew
        the grant on its own, outside the canonical store, and the rotated
        replacement Yahoo issues would be one this product never saw. Renewal is
        the store's job and the store's only.
        """
        if self._token_provider is not None:
            # THE FAILURE IS TRANSLATED INTO THE PROVIDER TAXONOMY, and that is
            # not cosmetic. Everything above this line — settlement, the weekly
            # refresh, the commissioner diagnostic — catches `ProviderError` to
            # decide whether a week is fresh, whether a Pool may settle, and
            # what to tell an operator. A credential failure that arrived as
            # some other exception type would sail past all of it: measured,
            # `/league/{id}/provider/status` returned 500 instead of reporting
            # the outage it exists to report, because its `except ProviderError`
            # did not match a grant error.
            #
            # The reason code survives the translation, so "nobody has connected
            # this league" is still distinguishable from "the grant was revoked"
            # at the other end.
            from auth.provider_grant import GrantError

            try:
                bearer = self._token_provider()
            except GrantError as exc:
                raise ProviderCredentialError(
                    f"[{exc.reason_code}] this league's Yahoo authorization is "
                    f"unavailable: {exc.detail or exc.reason_code}") from exc
            return {"access_token": bearer, "token_type": "bearer"}
        # OPERATOR TOOLING ONLY — the constructor refuses this combination for
        # anything else.
        return load_credentials(environ=self._environ,
                                secrets_dir=self._secrets_dir)

    def _query(self, league_key: str):
        # NOT CACHED ON THE PER-USER PATH. A cached yfpy query holds the bearer
        # it was built with, so reusing one across an hour boundary would send
        # an expired token and read the refreshed store for nothing. The
        # operator path keeps its cache, where the token file is yfpy's own.
        if self._operator_credentials and league_key in self._queries:
            return self._queries[league_key]

        token = self._token()

        factory = self._query_factory
        if factory is None:
            try:
                from yfpy.query import YahooFantasySportsQuery
            except ImportError as exc:
                raise ProviderTransportError(
                    f"yfpy is not installed; live Yahoo access is unavailable "
                    f"({exc}). Offline certification must use "
                    f"providers.fixtures.replay.FixtureTransport.") from exc
            factory = YahooFantasySportsQuery

        query = factory(
            league_id=self.league_number(league_key),
            game_code="nfl",
            game_id=self._game_id,
            yahoo_access_token_json=token,
            browser_callback=False,
        )
        if self._operator_credentials:
            self._queries[league_key] = query
        return query

    # ── ProviderTransport ─────────────────────────────────────────────────────

    def observed_at(self) -> datetime:
        return self._observed_at

    def fetch_league(self, league_key: str) -> Any:
        return self._query(league_key).get_league_info()

    def fetch_scoreboard(self, league_key: str, week: int) -> Any:
        return self._query(league_key).get_league_scoreboard_by_week(week)

    def fetch_teams(self, league_key: str) -> Any:
        return self._query(league_key).get_league_teams()

    def fetch_team_roster(self, league_key: str, team_key: str,
                          week: int) -> Any:
        # yfpy addresses a team by its within-league ordinal, so the ordinal is
        # taken off the compound key here, at the transport edge.
        ordinal = team_key.rsplit(".", 1)[-1]
        return self._query(league_key).get_team_roster_by_week(
            ordinal, chosen_week=week)
