"""WP2 · capturing BALLDONTLIE payloads into the fixture corpus.

WHY THIS EXISTS UNRUN. WP2's output for the offline stream is a corpus of
recorded payloads, and this repository holds no BALLDONTLIE API key, so no such
payload has ever been captured into it. Writing the capture path anyway is the
difference between "we could not capture" and "we did not build the thing that
captures": when a key arrives, the corpus is one command away, and nobody has to
reconstruct what the recording format was under time pressure.

    python -m providers.balldontlie.capture --season 2025 --week 17

── THE ONE RULE THIS MODULE IS BUILT AROUND ────────────────────────────────

ONLY A LIVE FETCH MAY WRITE `CAPTURED`. `providers/fixtures/record.py` states it
for Yahoo — `capture_live()` is the only function in the repository able to
write CAPTURED provenance — and the reason is §17's evidence hierarchy: a
CAPTURED fixture is the ONLY thing that can certify that live payload parsing
works. A synthetic file wearing that label does not fail loudly; it silently
promotes a guess to evidence, and C-3 and C-25 both become tests of our own
imagination.

So `capture_week` REFUSES a fixture transport. The refusal is not politeness
about types: replaying the synthetic corpus and re-recording it as CAPTURED is
exactly the mistake that would be easiest to make here, and it would look like
a successful capture in every log.

── PACING AND THE TERMS ────────────────────────────────────────────────────

Capture runs through the ordinary `BalldontlieLiveTransport`, which means it is
paced by the same ceiling and refuses a 429 the same way. At the free tier Phase
0 measured — five requests a minute — a week of `fantasy/weekly_stats` is seven
pages and therefore roughly ninety seconds. A week of `/plays` across sixteen
games is not remotely feasible at that rate, and the honest response to that is
to capture what is affordable and record what was skipped, which
`capture_week` does rather than quietly recording a partial week as a whole one.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from providers.balldontlie.transport import (
    BalldontlieFixtureTransport,
    BalldontlieLiveTransport,
    BalldontlieRateLimited,
)

__all__ = ["CAPTURED", "SYNTHETIC", "capture_week", "default_directory"]

CAPTURED = "CAPTURED"
SYNTHETIC = "SYNTHETIC"


def default_directory() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "fixtures", "balldontlie")


def capture_week(transport: Any, directory: str | None = None, *,
                 season: int, week: int, game_ids: tuple = (),
                 now: Any = None) -> dict:
    """Record one week's payloads as CAPTURED fixtures. Live transports only.

    Returns a report naming every file written, every endpoint SKIPPED, and the
    rate-limit state the capture finished in — so a partial capture is a stated
    partial capture rather than a corpus that looks complete.
    """
    if isinstance(transport, BalldontlieFixtureTransport):
        raise ValueError(
            "refusing to capture from a FIXTURE transport. Only a live fetch "
            "may write CAPTURED provenance (§16/§17): re-recording the "
            "synthetic corpus under that label would promote a guess to the "
            "one evidence tier that certifies live payload parsing, and it "
            "would look like a successful capture in every log.")
    if not isinstance(transport, BalldontlieLiveTransport):
        raise ValueError(
            f"refusing to capture from {type(transport).__name__}. Capture "
            f"runs through the certified live client so that pacing, the 429 "
            f"refusal and rate-limit telemetry all apply to it too.")

    directory = directory or default_directory()
    os.makedirs(directory, exist_ok=True)
    stamp = (now or (lambda: datetime.now(timezone.utc)))()

    written: list[str] = []
    skipped: list[str] = []

    def _record(path: str, params: dict, pages: list) -> None:
        name = BalldontlieFixtureTransport.fixture_name(path, params)
        payload = {
            "provenance": CAPTURED,
            "captured_at": stamp.isoformat(),
            "endpoint": path,
            "params": params,
            "pages": pages,
        }
        with open(os.path.join(directory, name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        written.append(name)

    def _capture(path: str, params: dict) -> None:
        """One endpoint, page by page, stopping honestly at a rate limit."""
        try:
            pages = list(transport.pages(path, **params))
        except BalldontlieRateLimited as exc:
            skipped.append(
                f"{path} {params!r}: rate limited after "
                f"{transport.requests_made} request(s); retry after "
                f"{exc.retry_after}s. NOT recorded — a half-walked cursor is a "
                f"short week, and a short week reads as a provider outage.")
            return
        _record(path, params, pages)

    _capture("fantasy/weekly_stats", {"season": season, "week": week,
                                      "per_page": 100})
    _capture("games", {"seasons[]": season, "weeks[]": week, "per_page": 100})
    for game_id in game_ids:
        _capture("plays", {"game_id": game_id, "per_page": 100})
    if not game_ids:
        skipped.append(
            "plays: no game ids requested. At the free tier's five requests a "
            "minute a full week of play-by-play is over an hour of walking, so "
            "it is opt-in per game rather than implied by a week.")

    report = {
        "provenance": CAPTURED,
        "captured_at": stamp.isoformat(),
        "season": season,
        "week": week,
        "written": written,
        "skipped": skipped,
        "requests_made": transport.requests_made,
        "rate_limit": {
            "limit": transport.last_rate_limit.limit,
            "remaining": transport.last_rate_limit.remaining,
        },
    }
    with open(os.path.join(directory, f"CAPTURE_{season}_w{week}.json"),
              "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    return report


def main(argv: list | None = None) -> int:     # pragma: no cover - operator tool
    import argparse

    parser = argparse.ArgumentParser(description="Capture BALLDONTLIE fixtures")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--game-id", type=int, action="append", default=[])
    parser.add_argument("--directory", default=None)
    parser.add_argument("--requests-per-minute", type=int, default=5)
    args = parser.parse_args(argv)

    transport = BalldontlieLiveTransport(
        requests_per_minute=args.requests_per_minute)
    report = capture_week(transport, args.directory, season=args.season,
                          week=args.week, game_ids=tuple(args.game_id))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":                     # pragma: no cover
    raise SystemExit(main())
