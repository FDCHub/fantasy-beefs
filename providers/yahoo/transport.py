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
from typing import Any

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
    """

    provider = "yahoo"

    def __init__(self, *, game_id: int = DEFAULT_GAME_ID,
                 environ: dict | None = None,
                 secrets_dir: str | None = None) -> None:
        self._game_id = game_id
        self._environ = environ
        self._secrets_dir = secrets_dir
        self._queries: dict[str, Any] = {}
        self._observed_at = datetime.now(timezone.utc)

    def __repr__(self) -> str:
        # Overridden ON PURPOSE. The default dataclass-free repr would render
        # self._queries, whose yfpy objects hold the access token; this class
        # exists on a code path that gets logged.
        return f"<YahooLiveTransport game_id={self._game_id} (credentials hidden)>"

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

    def _query(self, league_key: str):
        if league_key in self._queries:
            return self._queries[league_key]
        try:
            from yfpy.query import YahooFantasySportsQuery
        except ImportError as exc:
            raise ProviderTransportError(
                f"yfpy is not installed; live Yahoo access is unavailable "
                f"({exc}). Offline certification must use "
                f"providers.fixtures.replay.FixtureTransport.") from exc

        token = load_credentials(environ=self._environ,
                                 secrets_dir=self._secrets_dir)
        query = YahooFantasySportsQuery(
            league_id=self.league_number(league_key),
            game_code="nfl",
            game_id=self._game_id,
            yahoo_access_token_json=token,
            browser_callback=False,
        )
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
