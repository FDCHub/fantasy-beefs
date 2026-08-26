"""WP2 · BALLDONTLIE transport — HTTP, pacing, caching, pagination, limits.

RAW MATERIAL ONLY. Every method here returns the payload BALLDONTLIE sent,
decoded from JSON and otherwise untouched. Parsing is `parse.py`'s job and rules
are `normalize.py`'s, for the same reason the Yahoo transport draws the line in
the same place: a transport that normalized would make an L1 raw fixture
impossible to test (§16), and the value of fixture replay is that nothing
downstream can tell recorded from live.

── THE FOUR BEHAVIOURS THIS CLIENT EXISTS TO GET RIGHT ─────────────────────

They are not general HTTP hygiene. Each was MEASURED during the Phase 0
acceptance test, and each would silently corrupt a settlement if left to a naive
client.

1 · UNKNOWN QUERY PARAMETERS ARE IGNORED, NOT REJECTED. `position=K` returned a
    quarterback — a 200 with confidently wrong contents. A client that trusts
    HTTP status here will filter nothing and believe it filtered something. So
    every parameter name is validated against `ENDPOINTS` BEFORE the request is
    made, and an unknown name is refused rather than sent. This is the one place
    where being strict about our own spelling protects a stat line.

2 · RATE LIMITING IS HONOURED, NEVER WORKED AROUND. BALLDONTLIE's terms §7c
    forbid circumvention, and the key Phase 0 measured enforced 5 requests per
    minute — the documented free tier — while reaching GOAT-only endpoints.
    So: requests are PACED to a configured ceiling before they are sent, and a
    429 RAISES, carrying the server's own `Retry-After`. There is deliberately
    no automatic retry in this module. An automatic retry is the thing that
    turns into a workaround, one tuned constant at a time, and the caller that
    should decide whether to wait is a worker with a schedule — not a client
    library with a loop.

3 · PAGINATION IS CURSOR-BASED AND BOUNDED. `per_page` maxes at 100 and a week
    of `fantasy/weekly_stats` is seven pages. An unbounded `while next_cursor`
    against a paced client is an hour-long hang that looks like a network
    problem; `paginate` therefore refuses past `max_pages` and says how many
    rows it had when it stopped.

4 · RATE-LIMIT TELEMETRY IS RECORDED, NOT DISCARDED. `x-ratelimit-remaining` is
    the only way to see a throttle changing under you — the entitlement question
    Phase 0 left open (5/min enforced against GOAT's documented 600/min) is
    answered by watching this header in production, not by asking again.

── CACHING, AND WHAT IT IS FOR ─────────────────────────────────────────────

A per-instance response cache keyed by (path, exact parameters). It exists so a
composition that needs the same week twice inside one refresh spends one request
instead of two against a 5/minute budget — not as a durability mechanism. It
holds nothing across processes and expires on a TTL.

DURABLE RAW-PAYLOAD STORAGE IS WP5'S, AND THIS MODULE ONLY OFFERS IT A SEAM.
`raw_sink` is called with the path, the parameters, the payload and the instant
it was collected. Corrections are detectable only by re-fetch and diff (Phase 0F
— BALLDONTLIE publishes no revision number and no change feed), which makes
"what did we see, and when" a settlement-grade question. This module refuses to
answer it in memory and hands it to the layer that owns storage.

── WHY THIS DOES NOT IMPLEMENT `providers.base.ProviderTransport` ──────────

That protocol is FANTASY-LEAGUE SHAPED — `fetch_league`, `fetch_scoreboard`,
`fetch_teams`, `fetch_team_roster` — because every provider that has satisfied
it so far hosts leagues. BALLDONTLIE hosts football, not leagues. It has no
league key to fetch, no scoreboard of fantasy matchups, no fantasy teams and no
rosters, and there is no honest implementation of those four methods here: each
one would have to invent the thing it claims to return.

So this transport speaks BALLDONTLIE's own resources, and the seam where the two
providers meet is the composition layer (WP8), which already knows which feed
answers for which league. `observed_at` IS implemented, because it is the one
part of the protocol that means the same thing for any provider and §14's
staleness measurement reads it.

    key   BALLDONTLIE_API_KEY, or secrets/balldontlie.json {"api_key": "..."}
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Mapping

from providers.errors import (
    ProviderCredentialError,
    ProviderParseError,
    ProviderTransportError,
)

__all__ = [
    "BASE_URL",
    "ENDPOINTS",
    "PER_PAGE_MAX",
    "PROVIDER",
    "TRANSPORT_RULES",
    "BalldontlieFixtureTransport",
    "BalldontlieLiveTransport",
    "BalldontlieRateLimited",
    "RateLimit",
    "cache_key",
    "load_credentials",
]

PROVIDER = "balldontlie"
BASE_URL = "https://api.balldontlie.io/nfl/v1"

#: BALLDONTLIE's documented ceiling. A request for more is refused rather than
#: clamped: a caller who asked for 500 believes it got 500.
PER_PAGE_MAX = 100

#: Default page bound. A week of `fantasy/weekly_stats` is seven pages at 100;
#: twenty-five leaves headroom for a larger season without admitting a runaway.
DEFAULT_MAX_PAGES = 25

#: The measured free-tier throttle. Deliberately the DEFAULT, because a client
#: that defaults to the entitlement we hope for will hammer a 429 on the tier we
#: actually have. Raise it explicitly once the GOAT throttle is confirmed live.
DEFAULT_REQUESTS_PER_MINUTE = 5


# ── The endpoint registry ────────────────────────────────────────────────────
#
# EVERY PARAMETER NAME THIS CLIENT WILL SEND, PER ENDPOINT. Adding a name here
# is a deliberate act; sending one that is not here is refused. See behaviour 1
# in the module docstring — the API answers 200 to a misspelled filter and
# applies no filter at all, so this table is the only thing standing between a
# typo and a confidently wrong result set.
#
# `cursor` and `per_page` are the pagination pair on every collection endpoint.

_PAGING = frozenset({"cursor", "per_page"})

ENDPOINTS: Mapping[str, frozenset[str]] = {
    "fantasy/weekly_stats": _PAGING | frozenset({
        "season", "week", "player_ids[]", "team_ids[]", "position",
    }),
    "fantasy/projections": _PAGING | frozenset({
        "season", "week", "player_ids[]", "team_ids[]", "position",
    }),
    "fantasy/scoring_formats": _PAGING | frozenset(),
    "games": _PAGING | frozenset({
        "seasons[]", "weeks[]", "team_ids[]", "postseason", "dates[]",
    }),
    # `plays` IS THE ODD ONE OUT, AND IT IS NOT A TYPO. Every other collection
    # endpoint filters with a repeated array parameter (`game_ids[]`); `plays`
    # takes a SINGLE REQUIRED `game_id` and answers HTTP 400 —
    # {"param": "game_id", "error": "must be a valid integer"} — to anything
    # else, including a well-formed `game_ids[]` and including `player_id` on
    # its own. Sprint 5B measured this against the live API; WP2 had inferred
    # the plural by symmetry with its neighbours and no fixture could contradict
    # it, because a fixture answers whatever it was written to answer.
    "plays": _PAGING | frozenset({"game_id"}),
    # Season aggregates: one row per player per season, with `receiving_targets`
    # and `receptions` already summed. Verified live in Sprint 5B.
    "season_stats": _PAGING | frozenset({
        "season", "player_ids[]", "team_ids[]", "postseason",
    }),
    # `weeks[]` IS NOT HONOURED HERE AND IS DELIBERATELY ABSENT. Sprint 5B sent
    # `seasons[]=2025&weeks[]=1` and paginated: page 1 held week 1, page 72 held
    # week 8, page 145 held week 15. The season filter applied; the week filter
    # was IGNORED and the response walked the whole season, exactly the failure
    # mode behaviour 1 in the module docstring describes — a 200 with the filter
    # silently unapplied. Listing it here would let a caller believe a week had
    # been fetched when a season had. Filter by `game_ids[]`, or take the season
    # and bucket by `game.week` in memory.
    "stats": _PAGING | frozenset({
        "seasons[]", "player_ids[]", "team_ids[]", "game_ids[]", "postseason",
    }),
    "team_stats": _PAGING | frozenset({
        "seasons[]", "weeks[]", "team_ids[]", "game_ids[]", "postseason",
    }),
    "players": _PAGING | frozenset({
        "search", "team_ids[]", "player_ids[]", "first_name", "last_name",
    }),
    "teams": _PAGING | frozenset({"division", "conference"}),
}

#: Endpoints whose week numbering RESTARTS in the postseason (Phase 0F). A
#: week-filtered query against one of these returns January games alongside
#: September ones unless `postseason` is stated. `fantasy/*` is clean and is
#: deliberately absent.
POSTSEASON_AMBIGUOUS = frozenset({"games", "stats", "team_stats"})


# ── the transport-level Phase 0F behaviours ──────────────────────────────────
#
# `normalize.RULES` registers the rules about what the PAYLOAD means. These are
# the ones about how it must be ASKED FOR, and they are registered for the same
# reason: so a certification suite can assert that the Phase 0F list is covered
# in full rather than covered in the parts someone remembered.

TRANSPORT_RULES: tuple[tuple[str, str, str], ...] = (
    ("0F-T1", "unknown query parameters are ignored, not rejected — validate "
              "names client-side and never trust a 200", "_validate"),
    ("0F-T2", "pagination is cursor-based, per_page maxes at 100, and page "
              "walks are bounded", "BalldontlieLiveTransport.paginate"),
    ("0F-T3", "honour retry-after, record x-ratelimit-remaining, and never "
              "work around a 429", "BalldontlieRateLimited"),
    ("0F-T4", "corrections are detectable only by re-fetch and diff, so the "
              "raw payload and its collected_at are handed to storage",
     "BalldontlieLiveTransport"),
)


def load_credentials(*, environ: Mapping[str, str] | None = None,
                     secrets_dir: str | None = None) -> str:
    """The BALLDONTLIE API key, from exactly two supported sources.

      1. BALLDONTLIE_API_KEY (deployment);
      2. secrets/balldontlie.json {"api_key": "..."} (local dev).

    Raises ProviderCredentialError — never returns "" — for the reason
    `providers/errors.py` gives that class its own name: offline certification
    asserts that a LIVE transport cannot be built without credentials, and an
    empty key would instead produce a 401 much later, at the API boundary, where
    it looks like a provider outage rather than a missing secret.
    """
    environ = os.environ if environ is None else environ

    key = (environ.get("BALLDONTLIE_API_KEY") or "").strip()
    if key:
        return key

    root = secrets_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "secrets")
    path = os.path.join(root, "balldontlie.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                key = str(json.load(handle).get("api_key") or "").strip()
        except (OSError, ValueError, AttributeError) as exc:
            raise ProviderCredentialError(
                f"secrets/balldontlie.json is present but unreadable as "
                f"{{\"api_key\": ...}}: {exc}") from exc
        if key:
            return key

    raise ProviderCredentialError(
        "no BALLDONTLIE credentials available: neither BALLDONTLIE_API_KEY nor "
        "secrets/balldontlie.json {\"api_key\": ...} is present. Offline "
        "certification is expected to hit this — it must replay fixtures "
        "through BalldontlieFixtureTransport instead of a live client.")


@dataclass(frozen=True)
class RateLimit:
    """What the server said about the throttle on the last response.

    RECORDED FROM EVERY RESPONSE, INCLUDING SUCCESSFUL ONES. Phase 0 found the
    key's enforced limit (5/min) disagreeing with its entitlement (GOAT
    endpoints reachable), and the disagreement was visible only in these headers
    on 200s. A client that reads them only on a 429 cannot see a throttle
    changing until it has already been throttled.
    """

    limit: int | None = None
    remaining: int | None = None
    reset: int | None = None
    retry_after: float | None = None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> "RateLimit":
        def _int(name: str) -> int | None:
            raw = headers.get(name)
            try:
                return int(str(raw).strip())
            except (TypeError, ValueError):
                return None

        retry_after = headers.get("retry-after")
        try:
            retry = float(str(retry_after).strip())
        except (TypeError, ValueError):
            retry = None
        return cls(limit=_int("x-ratelimit-limit"),
                   remaining=_int("x-ratelimit-remaining"),
                   reset=_int("x-ratelimit-reset"),
                   retry_after=retry)


class BalldontlieRateLimited(ProviderTransportError):
    """HTTP 429. Carries the server's own Retry-After; never retried here.

    A SUBCLASS OF ProviderTransportError ON PURPOSE. `providers/incident.py`
    maps that class to the named reason `provider_unavailable`, which is
    retryable and already in the certified vocabulary — so a rate limit reaches
    an operator through the existing taxonomy rather than by minting a synonym
    for it (C-24: one vocabulary, no synonyms).
    """

    def __init__(self, message: str, *, rate_limit: RateLimit) -> None:
        super().__init__(message)
        self.rate_limit = rate_limit
        self.retry_after = rate_limit.retry_after


def cache_key(path: str, params: Mapping[str, Any]) -> tuple:
    """A stable key for (endpoint, exact parameters).

    Sorted, so two callers spelling the same query in a different order share a
    cache entry — and STRINGIFIED, so `week=1` and `week="1"` do too. They are
    the same request to the server, and a cache that disagreed with the server
    about that would spend a request from a five-per-minute budget to learn
    something it already knew.
    """
    return (path, tuple(sorted((str(k), str(v)) for k, v in params.items())))


def _validate(path: str, params: Mapping[str, Any]) -> None:
    """Refuse an unknown endpoint or an unknown parameter NAME. See behaviour 1."""
    allowed = ENDPOINTS.get(path)
    if allowed is None:
        raise ProviderTransportError(
            f"{path!r} is not a BALLDONTLIE endpoint this client knows. "
            f"Known: {sorted(ENDPOINTS)!r}. Adding one is a deliberate act — "
            f"the API answers 200 to a request it did not understand.")
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ProviderTransportError(
            f"{path!r} does not accept parameter(s) {unknown!r}. BALLDONTLIE "
            f"IGNORES an unknown parameter and returns 200 with the filter "
            f"UNAPPLIED — Phase 0 measured `position=K` returning a "
            f"quarterback — so this client refuses to send one. Accepted here: "
            f"{sorted(allowed)!r}.")
    per_page = params.get("per_page")
    if per_page is not None and int(per_page) > PER_PAGE_MAX:
        raise ProviderTransportError(
            f"per_page={per_page} exceeds BALLDONTLIE's maximum of "
            f"{PER_PAGE_MAX}. Refused rather than clamped: a caller that asked "
            f"for {per_page} rows and silently received {PER_PAGE_MAX} would "
            f"read a short page as a short season.")


class _Pacer:
    """Spends requests no faster than a stated ceiling. Clock and sleep injected.

    PACING IS NOT RETRYING. This delays a request that has not been made yet, to
    stay INSIDE the published limit. It never reacts to a 429, because reacting
    to a 429 is where honouring a limit turns into routing around one.
    """

    def __init__(self, requests_per_minute: int, *,
                 clock: Callable[[], float] | None = None,
                 sleeper: Callable[[float], None] | None = None) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self.interval = 60.0 / float(requests_per_minute)
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep
        self._last: float | None = None
        self.waits: list[float] = []

    def spend(self) -> None:
        now = self._clock()
        if self._last is not None:
            wait = self.interval - (now - self._last)
            if wait > 0:
                self.waits.append(wait)
                self._sleep(wait)
                now = self._clock()
        self._last = now


class BalldontlieLiveTransport:
    """The live client. Paced, cached, bounded, and loud about limits.

    NOT CONSTRUCTIBLE WITHOUT A KEY. `load_credentials` raises rather than
    returning empty, so an offline environment cannot accidentally hold a live
    client that fails later and elsewhere.
    """

    provider = PROVIDER

    def __init__(self, *, api_key: str | None = None,
                 base_url: str = BASE_URL,
                 requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE,
                 cache_ttl_seconds: float = 900.0,
                 timeout_seconds: float = 30.0,
                 raw_sink: Callable[..., None] | None = None,
                 client: Any | None = None,
                 clock: Callable[[], float] | None = None,
                 sleeper: Callable[[float], None] | None = None,
                 now: Callable[[], datetime] | None = None) -> None:
        self.api_key = api_key or load_credentials()
        self.base_url = base_url.rstrip("/")
        self.cache_ttl_seconds = float(cache_ttl_seconds)
        self.timeout_seconds = float(timeout_seconds)
        self._raw_sink = raw_sink
        self._client = client
        self._pacer = _Pacer(requests_per_minute, clock=clock, sleeper=sleeper)
        self._clock = clock or time.monotonic
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._observed_at: datetime = self._now()

        self.requests_made = 0
        self.cache_hits = 0
        self.last_rate_limit = RateLimit()

    # ── the one door ────────────────────────────────────────────────────────

    def get(self, path: str, **params: Any) -> Any:
        """One request (or one cache hit). Returns the decoded payload."""
        params = {k: v for k, v in params.items() if v is not None}
        _validate(path, params)

        key = cache_key(path, params)
        hit = self._cache.get(key)
        if hit is not None and (self._clock() - hit[0]) < self.cache_ttl_seconds:
            self.cache_hits += 1
            return hit[1]

        self._pacer.spend()
        payload = self._request(path, params)
        self._cache[key] = (self._clock(), payload)
        self._observed_at = self._now()
        if self._raw_sink is not None:
            self._raw_sink(path=path, params=dict(params), payload=payload,
                           collected_at=self._observed_at)
        return payload

    def _request(self, path: str, params: Mapping[str, Any]) -> Any:
        import httpx

        client = self._client
        url = f"{self.base_url}/{path}"
        headers = {"Authorization": self.api_key,
                   "Accept": "application/json"}
        try:
            if client is None:
                response = httpx.get(url, params=params, headers=headers,
                                     timeout=self.timeout_seconds)
            else:
                response = client.get(url, params=params, headers=headers,
                                      timeout=self.timeout_seconds)
        except Exception as exc:                              # noqa: BLE001
            raise ProviderTransportError(
                f"BALLDONTLIE {path} could not be reached: "
                f"{type(exc).__name__}: {exc}") from exc

        self.requests_made += 1
        self.last_rate_limit = RateLimit.from_headers(
            {str(k).lower(): v for k, v in dict(response.headers).items()})

        status = int(response.status_code)
        if status == 429:
            raise BalldontlieRateLimited(
                f"BALLDONTLIE rate limit reached on {path} "
                f"(limit {self.last_rate_limit.limit}, retry after "
                f"{self.last_rate_limit.retry_after}s). NOT retried here: "
                f"§7c forbids working around a rate limit, and the decision to "
                f"wait belongs to the scheduled caller, not to this client.",
                rate_limit=self.last_rate_limit)
        if status in (401, 403):
            raise ProviderCredentialError(
                f"BALLDONTLIE refused the key on {path} (HTTP {status}). The "
                f"key is missing, revoked, or not entitled to this endpoint.")
        if status >= 400:
            raise ProviderTransportError(
                f"BALLDONTLIE {path} returned HTTP {status}.")

        try:
            return response.json()
        except Exception as exc:                              # noqa: BLE001
            raise ProviderParseError(
                f"BALLDONTLIE {path} returned HTTP {status} with a body that "
                f"is not JSON: {type(exc).__name__}: {exc}") from exc

    # ── pagination ──────────────────────────────────────────────────────────

    def paginate(self, path: str, *, max_pages: int = DEFAULT_MAX_PAGES,
                 per_page: int = PER_PAGE_MAX, **params: Any) -> list[dict]:
        """Follow `meta.next_cursor` and return every row, or refuse.

        BOUNDED, AND THE BOUND IS AN ERROR RATHER THAN A TRUNCATION. A silently
        truncated page set is a short week — which is exactly the shape of a
        real provider outage, and would be read as one.
        """
        rows: list[dict] = []
        cursor: Any = None
        for page in range(1, max_pages + 1):
            payload = self.get(path, per_page=per_page, cursor=cursor, **params)
            batch, meta = _envelope(payload, path)
            rows.extend(batch)
            cursor = meta.get("next_cursor")
            if cursor in (None, "", 0):
                return rows
        raise ProviderTransportError(
            f"BALLDONTLIE {path} still had pages after {max_pages} "
            f"({len(rows)} rows read). Refusing to loop further: an unbounded "
            f"cursor walk against a paced client is an hour-long hang that "
            f"looks like a network fault. Raise max_pages deliberately if the "
            f"season really is this large.")

    def pages(self, path: str, *, max_pages: int = DEFAULT_MAX_PAGES,
              per_page: int = PER_PAGE_MAX, **params: Any) -> Iterator[Any]:
        """The same walk, yielding RAW payloads — what a fixture capture wants."""
        cursor: Any = None
        for _ in range(max_pages):
            payload = self.get(path, per_page=per_page, cursor=cursor, **params)
            yield payload
            _, meta = _envelope(payload, path)
            cursor = meta.get("next_cursor")
            if cursor in (None, "", 0):
                return
        raise ProviderTransportError(
            f"BALLDONTLIE {path} still had pages after {max_pages}.")

    # ── the resources, named ────────────────────────────────────────────────

    def fetch_weekly_stats(self, *, season: int, week: int,
                           **params: Any) -> list[dict]:
        """Finalized weekly fantasy rows — the settlement-grade summary source."""
        return self.paginate("fantasy/weekly_stats", season=season, week=week,
                             **params)

    def fetch_projections(self, *, season: int, week: int,
                          **params: Any) -> list[dict]:
        return self.paginate("fantasy/projections", season=season, week=week,
                             **params)

    def fetch_games(self, *, season: int, week: int, postseason: bool = False,
                    **params: Any) -> list[dict]:
        """Games for one week.

        `postseason` IS REQUIRED IN SPIRIT AND DEFAULTED TO FALSE. Phase 0F:
        week numbering restarts in January, so `weeks[]=1` returns 22 games —
        sixteen from September and six from the postseason — unless the query
        says which season half it means.
        """
        return self.paginate("games", **{"seasons[]": season, "weeks[]": week,
                                         "postseason": postseason}, **params)

    def fetch_plays(self, *, game_id: int, **params: Any) -> list[dict]:
        """Every play of ONE game. `game_id` is required by the API, not optional."""
        return self.paginate("plays", game_id=game_id, **params)

    def fetch_players(self, **params: Any) -> list[dict]:
        return self.paginate("players", **params)

    def fetch_nfl_teams(self, **params: Any) -> list[dict]:
        """The thirty-two NFL franchises.

        NOT `fetch_teams`, DELIBERATELY. `providers.base.ProviderTransport`
        already has a `fetch_teams(league_key)`, and it means the FANTASY teams
        in a league — a completely different set of objects. Two methods with
        one name, one taking a league key and one not, is a duck-typing
        accident waiting for the composition layer: the call would resolve,
        return thirty-two NFL franchises where a league's eight fantasy teams
        were expected, and only fail somewhere further down. The collision is
        removed rather than documented.
        """
        return self.paginate("teams", **params)

    def observed_at(self) -> datetime:
        """When this transport's data was observed — the last successful fetch."""
        return self._observed_at

    def cache_clear(self) -> None:
        self._cache.clear()

    def __repr__(self) -> str:                                # pragma: no cover
        return (f"<BalldontlieLiveTransport {self.base_url} "
                f"requests={self.requests_made} cache_hits={self.cache_hits} "
                f"limit={self.last_rate_limit.limit} "
                f"remaining={self.last_rate_limit.remaining}>")


def _envelope(payload: Any, path: str) -> tuple[list[dict], dict]:
    """`{"data": [...], "meta": {...}}` -> (rows, meta). Fails closed.

    Duplicated in `parse.py` in spirit and kept here deliberately: pagination is
    a TRANSPORT concern — it needs `next_cursor` and nothing else — and making
    the transport import the parser would put a rules layer underneath the layer
    whose whole purpose is to have no rules.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        keys = sorted(payload) if isinstance(payload, dict) else "n/a"
        raise ProviderParseError(
            f"BALLDONTLIE {path} payload is not the documented envelope "
            f"{{\"data\": [...], \"meta\": {{...}}}} — got "
            f"{type(payload).__name__} with keys {keys!r}.")
    meta = payload.get("meta")
    return payload["data"], meta if isinstance(meta, dict) else {}


class BalldontlieFixtureTransport:
    """Replays committed BALLDONTLIE payloads. Same surface as the live client.

    WHY IT SATISFIES THE SAME SURFACE. §3's property — nothing downstream can
    tell recorded from live — is what makes offline certification meaningful.
    The fixture directory holds one JSON file per (endpoint, parameters) key,
    named by `fixture_name`, and the pages of a paginated endpoint are the
    `pages` list inside that file.

    IT HOLDS NO KEY AND OPENS NO SOCKET. Constructing one in an environment with
    no credentials is exactly what C-1 requires to be possible.
    """

    provider = PROVIDER

    def __init__(self, directory: str, *,
                 frozen_now: datetime | None = None) -> None:
        self.directory = directory
        self._frozen_now = frozen_now or datetime(2026, 1, 5, 12, 0,
                                                  tzinfo=timezone.utc)
        self.requests_made = 0
        self.cache_hits = 0
        self.last_rate_limit = RateLimit()
        self._loaded: dict[str, Any] = {}

    @staticmethod
    def fixture_name(path: str, params: Mapping[str, Any]) -> str:
        """A filesystem-safe name for (endpoint, parameters)."""
        stem = path.replace("/", "_")
        parts = [f"{k}-{v}" for k, v in sorted(
            (str(k).replace("[]", ""), str(v)) for k, v in params.items())]
        return "__".join([stem, *parts]) + ".json" if parts else stem + ".json"

    def _load(self, name: str, path: str) -> Any:
        if name in self._loaded:
            self.cache_hits += 1
            return self._loaded[name]
        target = os.path.join(self.directory, name)
        if not os.path.exists(target):
            raise ProviderTransportError(
                f"no BALLDONTLIE fixture {name!r} for endpoint {path!r} in "
                f"{self.directory}. A fixture transport that invented an empty "
                f"page here would certify a week that was never recorded.")
        with open(target, encoding="utf-8") as handle:
            payload = json.load(handle)
        self._loaded[name] = payload
        return payload

    def get(self, path: str, **params: Any) -> Any:
        """One recorded page. Validated exactly as the live client validates."""
        params = {k: v for k, v in params.items() if v is not None}
        _validate(path, params)
        cursor = params.pop("cursor", None)
        payload = self._load(self.fixture_name(path, params), path)
        self.requests_made += 1
        pages = payload.get("pages")
        if not isinstance(pages, list) or not pages:
            return payload
        index = 0 if cursor in (None, "", 0) else int(cursor)
        if index >= len(pages):
            raise ProviderTransportError(
                f"BALLDONTLIE fixture {path!r} has {len(pages)} page(s); "
                f"cursor {cursor!r} points past the end.")
        return pages[index]

    def paginate(self, path: str, *, max_pages: int = DEFAULT_MAX_PAGES,
                 per_page: int = PER_PAGE_MAX, **params: Any) -> list[dict]:
        return BalldontlieLiveTransport.paginate(
            self, path, max_pages=max_pages, per_page=per_page, **params)

    def pages(self, path: str, *, max_pages: int = DEFAULT_MAX_PAGES,
              per_page: int = PER_PAGE_MAX, **params: Any) -> Iterator[Any]:
        return BalldontlieLiveTransport.pages(
            self, path, max_pages=max_pages, per_page=per_page, **params)

    fetch_weekly_stats = BalldontlieLiveTransport.fetch_weekly_stats
    fetch_projections = BalldontlieLiveTransport.fetch_projections
    fetch_games = BalldontlieLiveTransport.fetch_games
    fetch_plays = BalldontlieLiveTransport.fetch_plays
    fetch_players = BalldontlieLiveTransport.fetch_players
    fetch_nfl_teams = BalldontlieLiveTransport.fetch_nfl_teams

    def observed_at(self) -> datetime:
        """The RECORDED instant, never the wall clock — §14 determinism."""
        return self._frozen_now

    def cache_clear(self) -> None:
        self._loaded.clear()

    def __repr__(self) -> str:                                # pragma: no cover
        return (f"<BalldontlieFixtureTransport {self.directory} "
                f"requests={self.requests_made}>")
