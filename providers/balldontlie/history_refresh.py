"""Sprint 5 · refreshing historical model parameters from BALLDONTLIE facts.

    python -m providers.balldontlie.history_refresh --season 2024 --season 2025

WHAT THIS IS, AND THE ONE THING IT IS NOT. It is the only place in the
projection pipeline permitted to touch the network, and it runs OFFLINE from
pricing: it reads finished games, derives rates, and stores them. Nothing it
produces is consulted at quote time except as rows already in the database.
CSPS, IPRM and sim-v2 never call it and never call the transport.

── THE CADENCE, AND WHY IT IS NOT A SCHEDULER ──────────────────────────────

A callable command, run after a week's games finish. No job framework, no cron
entry, no daemon — this repository already has `workers/` for anything that
needs a schedule, and a parameter refresh that runs weekly does not need one
built for it. An operator or a later worker calls `refresh()`.

── IDEMPOTENCY IS THE WHOLE OPERATIONAL CONTRACT ───────────────────────────

Run it twice on the same history and the second run writes nothing: every
derived parameter fingerprints identically and collides with the row already
stored. That is what makes it safe to run on a timer, safe to re-run after a
failure, and safe to run when nobody is sure whether it already ran.

── CORRECTIONS ARRIVE AS NEW ROWS ──────────────────────────────────────────

BALLDONTLIE publishes no revision feed, so a corrected stat is only visible by
re-deriving. When a count changes, the fingerprint changes and the new parameter
lands BESIDE its predecessor rather than over it. A wager priced last week
resolves the parameter that was in force at ITS as-of and still reprices
identically; new quotes pick up the correction. Nothing frozen is mutated.

── THE AS-OF IS THE CUTOFF, NOT THE CLOCK ──────────────────────────────────

`as_of` is stamped from the LAST GAME INCLUDED, not from wall-clock time. A
derivation over 2024-2025 carries the instant after the final 2025 game, so a
2026 week-1 projection can resolve it and a 2025 week-3 projection cannot. Using
"now" would silently make every historical parameter eligible for every past
projection, which is precisely the leakage the as-of exists to stop.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from providers.balldontlie import parse as P
from providers.cross_identity import BALLDONTLIE
from scoring import history as H

__all__ = ["RefreshReport", "derive_from_payloads", "refresh"]


@dataclass
class RefreshReport:
    """What a refresh looked at, derived and stored."""

    provider: str = BALLDONTLIE
    seasons: list = field(default_factory=list)
    season_window: str = ""
    as_of: datetime | None = None
    weekly_stat_rows: int = 0
    games_with_plays: int = 0
    play_rows: int = 0
    rates_derived: int = 0
    rates_persisted: int = 0
    rates_duplicate: int = 0
    requests_made: int = 0
    skipped: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"provider": self.provider, "seasons": list(self.seasons),
                "season_window": self.season_window,
                "as_of": self.as_of.isoformat() if self.as_of else None,
                "weekly_stat_rows": self.weekly_stat_rows,
                "games_with_plays": self.games_with_plays,
                "play_rows": self.play_rows,
                "rates_derived": self.rates_derived,
                "rates_persisted": self.rates_persisted,
                "rates_duplicate": self.rates_duplicate,
                "requests_made": self.requests_made,
                "skipped": list(self.skipped)}


def derive_from_payloads(db, *, weekly_stat_payloads: Sequence = (),
                         play_games: Sequence = (),
                         season_window: str, as_of: datetime,
                         provider: str = BALLDONTLIE,
                         generated_at: datetime | None = None
                         ) -> RefreshReport:
    """Derive and store every model parameter from ALREADY-FETCHED payloads.

    SEPARATED FROM THE FETCH ON PURPOSE. This function takes payloads and a
    database and does no I/O of its own, so the whole derivation — the part with
    the football reasoning in it — is unit-testable against committed fixtures
    with no credential, no network and no rate limit. `refresh()` is the thin
    shell that goes and gets the payloads.

    `play_games` is a sequence of `(payload, home, visitor)`.
    """
    report = RefreshReport(provider=provider, season_window=season_window,
                           as_of=as_of)

    rows = []
    for payload in weekly_stat_payloads:
        rows.extend(P.parse_weekly_stats(payload))
    report.weekly_stat_rows = len(rows)

    games = []
    for payload, home, visitor in play_games:
        plays = P.parse_plays(payload)
        report.play_rows += len(plays)
        games.append((plays, home, visitor))
    report.games_with_plays = len(games)

    rates: list = []
    if rows:
        rates.extend(H.derive_reception_rates(
            rows, provider=provider, season_window=season_window, as_of=as_of))
    if games:
        rates.extend(H.derive_pick_six_rates(
            [plays for plays, _, _ in games], provider=provider,
            season_window=season_window, as_of=as_of))
        rates.extend(H.derive_three_and_out_rates(
            games, provider=provider, season_window=season_window,
            as_of=as_of))
    report.rates_derived = len(rates)

    stored = H.persist_rates(db, rates, generated_at=generated_at)
    report.rates_persisted = stored["persisted"]
    report.rates_duplicate = stored["duplicate"]
    return report


def refresh(db, transport, *, seasons: Sequence[int], weeks: Sequence[int],
            game_ids: Sequence = (), generated_at: datetime | None = None
            ) -> RefreshReport:
    """Fetch the history these models need, then derive from it.

    THE ONLY NETWORK IN THE PIPELINE, and it is paced by the certified WP2
    transport: the same request budget, the same 429 discipline, the same
    bounded pagination. Nothing here works around a rate limit, and a run that
    is throttled reports what it skipped rather than retrying around it.

    PLAY-BY-PLAY IS OPT-IN PER GAME. A full season of `/plays` is hundreds of
    requests; the pick-six and three-and-out models need it and the reception
    model does not, so a caller can refresh catch rates cheaply and add drive
    history deliberately.
    """
    from providers.balldontlie.transport import BalldontlieRateLimited

    before = getattr(transport, "requests_made", 0)
    report_skips: list = []

    weekly_payloads: list = []
    latest_season = max(seasons) if seasons else 0
    latest_week = max(weeks) if weeks else 0
    for season in sorted(seasons):
        for week in sorted(weeks):
            try:
                rows = transport.paginate("fantasy/weekly_stats",
                                          season=season, week=week)
            except BalldontlieRateLimited as exc:
                report_skips.append(
                    f"fantasy/weekly_stats season={season} week={week}: rate "
                    f"limited, retry after {exc.retry_after}s")
                continue
            except Exception as exc:                           # noqa: BLE001
                report_skips.append(
                    f"fantasy/weekly_stats season={season} week={week}: "
                    f"{type(exc).__name__}")
                continue
            weekly_payloads.append({"data": rows, "meta": {}})

    play_games: list = []
    for entry in game_ids:
        game_id, home, visitor = entry
        try:
            plays = transport.paginate("plays", game_id=game_id)
        except BalldontlieRateLimited as exc:
            report_skips.append(
                f"plays game={game_id}: rate limited, retry after "
                f"{exc.retry_after}s")
            continue
        except Exception as exc:                               # noqa: BLE001
            report_skips.append(f"plays game={game_id}: {type(exc).__name__}")
            continue
        play_games.append(({"data": plays, "meta": {}}, home, visitor))

    # THE CUTOFF IS THE LAST GAME INCLUDED, not the clock. See the module note.
    as_of = _season_cutoff(latest_season, latest_week)
    season_window = (f"{min(seasons)}-{max(seasons)}" if len(set(seasons)) > 1
                     else str(latest_season))

    report = derive_from_payloads(
        db, weekly_stat_payloads=weekly_payloads, play_games=play_games,
        season_window=season_window, as_of=as_of, generated_at=generated_at)
    report.seasons = sorted(seasons)
    report.skipped = report_skips
    report.requests_made = getattr(transport, "requests_made", 0) - before
    return report


def _season_cutoff(season: int, week: int) -> datetime:
    """A conservative instant AFTER the last included week.

    Deliberately coarse: the NFL regular season ends in the calendar year after
    it starts, so a season's history is treated as complete at the start of the
    following March. That is later than the last game and earlier than the next
    season's week one, which is exactly the window an as-of has to land in for a
    next-season projection to resolve it and a same-season one not to.
    """
    return datetime(season + 1, 3, 1, tzinfo=timezone.utc)


def main(argv: list | None = None) -> int:     # pragma: no cover - operator tool
    import argparse

    parser = argparse.ArgumentParser(
        description="Refresh BALLDONTLIE historical model parameters")
    parser.add_argument("--season", type=int, action="append", required=True)
    parser.add_argument("--week", type=int, action="append", default=None)
    parser.add_argument("--game", action="append", default=[],
                        help="game_id:HOME:VISITOR, for drive/pick-six history")
    args = parser.parse_args(argv)

    from db.schema import SessionLocal
    from providers.balldontlie.transport import BalldontlieLiveTransport

    games = []
    for entry in args.game:
        game_id, home, visitor = entry.split(":")
        games.append((int(game_id), home, visitor))

    db = SessionLocal()
    try:
        report = refresh(db, BalldontlieLiveTransport(),
                         seasons=args.season,
                         weeks=args.week or list(range(1, 19)),
                         game_ids=games)
        db.commit()
    finally:
        db.close()
    print(json.dumps(report.as_dict(), indent=2))
    return 0


if __name__ == "__main__":                     # pragma: no cover
    raise SystemExit(main())
