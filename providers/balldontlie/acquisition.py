"""Sprint 5B · bulk historical acquisition with a resumable on-disk raw cache.

WHY THIS EXISTS SEPARATELY FROM `history_refresh`. `history_refresh.refresh()`
fetches and derives in one pass, which is right for a weekly top-up of a few
dozen requests. A first calibration is a different animal: it is thousands of
requests against a five-per-minute budget, so it runs for hours, and anything
that runs for hours will be interrupted. This module makes the fetch RESUMABLE
and the derivation REPEATABLE from what was already fetched.

── THE CACHE IS THE UNIT OF RESUMPTION ─────────────────────────────────────

Every page is written to its own file, named by a hash of (path, params). A
re-run reads the file instead of spending a request. So an interrupted run
resumes at the first page it never got, a derivation can be re-run any number
of times at zero request cost, and a bug found in the derivation does not cost
another five hours of fetching.

── THE CACHE LIVES OUTSIDE THE REPOSITORY, DELIBERATELY ────────────────────

Raw play-by-play for two seasons is hundreds of megabytes of provider payload.
`root` is an explicit path the caller must pass; nothing here defaults to a
location inside the working tree, so a large raw capture cannot be committed by
accident. Certification fixtures are a separate, deliberate, minimal act.

── PACING IS THE TRANSPORT'S JOB, NOT THIS MODULE'S ────────────────────────

Requests go through the certified WP2 transport, which enforces the request
budget and refuses to work around a 429. This module never sleeps around a
rate limit and never retries a refusal into submission; it records the gap and
moves on, so a throttled run reports a short season rather than pretending to
a complete one.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

__all__ = ["RawCache", "AcquisitionLog", "fetch_pages", "acquire_games",
           "acquire_season_stats", "acquire_season_player_games",
           "acquire_plays"]


def _key(path: str, params: dict) -> str:
    blob = json.dumps([path, sorted((str(k), str(v)) for k, v in params.items())],
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


@dataclass
class RawCache:
    """One JSON file per fetched page, addressed by (path, params)."""

    root: str

    def __post_init__(self) -> None:
        os.makedirs(self.root, exist_ok=True)

    def path_for(self, path: str, params: dict) -> str:
        safe = path.replace("/", "_")
        return os.path.join(self.root, safe + "." + _key(path, params) + ".json")

    def get(self, path: str, params: dict):
        f = self.path_for(path, params)
        if not os.path.exists(f):
            return None
        try:
            with open(f, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None          # a truncated file from a killed run: refetch

    def put(self, path: str, params: dict, payload) -> None:
        f = self.path_for(path, params)
        tmp = f + ".part"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        os.replace(tmp, f)       # atomic: a killed run leaves no half file

    def bytes_used(self) -> int:
        return sum(os.path.getsize(os.path.join(self.root, n))
                   for n in os.listdir(self.root) if n.endswith(".json"))

    def file_count(self) -> int:
        return sum(1 for n in os.listdir(self.root) if n.endswith(".json"))


@dataclass
class AcquisitionLog:
    """What the run actually spent and hit."""

    requests: int = 0
    cache_hits: int = 0
    pages: int = 0
    rows: int = 0
    rate_limited: int = 0
    server_errors: int = 0
    other_errors: int = 0
    started_at: float = field(default_factory=time.time)
    notes: list = field(default_factory=list)

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at

    def as_dict(self) -> dict:
        return {"requests": self.requests, "cache_hits": self.cache_hits,
                "pages": self.pages, "rows": self.rows,
                "rate_limited": self.rate_limited,
                "server_errors": self.server_errors,
                "other_errors": self.other_errors,
                "elapsed_seconds": round(self.elapsed, 1),
                "notes": list(self.notes)}


def fetch_pages(transport, cache: RawCache, log: AcquisitionLog, path: str,
                *, per_page: int = 100, max_pages: int = 400,
                max_rate_limit_waits: int = 6,
                on_page: Callable[[int, int], None] | None = None,
                **params: Any) -> list:
    """Every row of `path`, following cursors, cached page by page.

    Returns the rows it managed to get. A transport failure stops this path and
    is recorded, so a short set is reported as short rather than passed off as
    a complete season.

    ── A 429 IS WAITED OUT HERE, NOT WORKED AROUND ─────────────────────────

    The transport refuses to retry a rate limit itself, deliberately: it says
    the decision to wait belongs to the scheduled caller. For a multi-hour
    acquisition this IS that caller, and sleeping until the provider's own
    window reopens is the respectful reading of the limit — as against
    retrying immediately, widening concurrency, or rotating keys, none of
    which happen anywhere in this module. The wait is bounded; after
    `max_rate_limit_waits` consecutive refusals the path gives up.
    """
    from providers.balldontlie.transport import BalldontlieRateLimited
    from providers.errors import ProviderTransportError

    rows: list = []
    cursor: Any = None
    for page_number in range(1, max_pages + 1):
        q = dict(params)
        q["per_page"] = per_page
        if cursor is not None:
            q["cursor"] = cursor

        payload = cache.get(path, q)
        if payload is None:
            for attempt in range(max_rate_limit_waits + 1):
                try:
                    payload = transport.get(path, **q)
                    log.requests += 1
                    break
                except BalldontlieRateLimited as exc:
                    log.rate_limited += 1
                    if attempt >= max_rate_limit_waits:
                        log.notes.append(
                            path + " " + repr(params) + ": rate limited " +
                            str(attempt + 1) + "x, gave up on this path")
                        return rows
                    time.sleep(min((float(exc.retry_after or 0) or 20.0) + 2.0, 90.0))
                except ProviderTransportError as exc:
                    log.server_errors += 1
                    log.notes.append(path + " " + repr(params) + ": " +
                                     type(exc).__name__ + ": " + str(exc)[:120])
                    return rows
                except Exception as exc:                      # noqa: BLE001
                    log.other_errors += 1
                    log.notes.append(path + " " + repr(params) + ": " +
                                     type(exc).__name__ + ": " + str(exc)[:120])
                    return rows
            if payload is None:
                return rows
            cache.put(path, q, payload)
        else:
            log.cache_hits += 1

        batch = payload.get("data", []) if isinstance(payload, dict) else []
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        rows.extend(batch)
        log.pages += 1
        log.rows += len(batch)
        if on_page is not None:
            on_page(page_number, len(batch))

        cursor = meta.get("next_cursor")
        if cursor in (None, "", 0):
            return rows

    log.notes.append(path + " " + repr(params) + ": still had pages after " +
                     str(max_pages))
    return rows


def acquire_games(transport, cache, log, *, season: int,
                  postseason: bool = False) -> list:
    """Every regular-season game of one season."""
    return fetch_pages(transport, cache, log, "games",
                       **{"seasons[]": season, "postseason": postseason})


def acquire_season_stats(transport, cache, log, *, season: int) -> list:
    """One row per player per season — targets and receptions already summed."""
    return fetch_pages(transport, cache, log, "season_stats", season=season)


def acquire_season_player_games(transport, cache, log, *, season: int,
                                postseason: bool = False) -> list:
    """Per-player per-game box scores for a WHOLE SEASON.

    NOT PER WEEK, AND THAT IS THE PROVIDER'S DOING. `/stats` accepts `weeks[]`,
    answers 200, and ignores it: Sprint 5B sent `seasons[]=2025&weeks[]=1` and
    paginated into week 8 by page 72 and week 15 by page 145. A per-week helper
    would therefore have fetched the entire season once per week — eighteen
    identical passes — while reporting each as one week. The season is fetched
    once and bucketed by `game.week` in memory instead.
    """
    return fetch_pages(transport, cache, log, "stats",
                       **{"seasons[]": season, "postseason": postseason})


def acquire_plays(transport, cache, log, *, game_id: int) -> list:
    """Every play of one game. `game_id` is singular and required (Sprint 5B)."""
    return fetch_pages(transport, cache, log, "plays", game_id=game_id)
