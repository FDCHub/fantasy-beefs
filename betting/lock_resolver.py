"""Which clock governs a league's weekly lock — the real NFL one, or a demo's.

── WHY THIS SEAM EXISTS (DEMO D2.3, approved architecture change) ───────────

Versus and Pool play are gated on kickoff: a challenge cannot be issued once the
week has started. `betting.pool_engine._nfl_lock_time` answers that from
`nfl_schedule`, which is RAW NFL DATA WITH NO LEAGUE ID — one week has one
kickoff for everybody.

That is correct for real leagues and fatal for a demo. A deterministic showcase
has to replay ten completed fictional weeks through the real gameplay APIs, and
those APIs refuse any week whose kickoff has passed. The only ways to reach them
were to fabricate rows in the global `nfl_schedule` — which would move the lock
for every real league in the same database and make the demo drift with the
calendar — or to monkeypatch production at runtime. Both were refused.

So the lock gets a resolver, and the resolver is the ONLY thing that knows there
is more than one kind of clock.

── THE PRODUCTION PATH IS UNTOUCHED ─────────────────────────────────────────

For every league that is not a showcase demo league, this returns exactly
`_nfl_lock_time(league.season, week)` — the same call, the same season, the same
`ScheduleNotReadyError`. No flag admits a historical challenge, no semantics
change, and nothing here can widen what a real league may do. The discrimination
suite drives a Yahoo league through this module and asserts it is byte-identical
to calling `_nfl_lock_time` directly.

── THE DEMO CLOCK IS THE DEMO'S OWN CURRENT WEEK ────────────────────────────

A synthetic schedule anchored to real time would drift: a demo seeded in August
would stop being playable in November. So the showcase's clock is not a
timestamp at all — it is the league's own `provider_current_week`:

    week <  provider_current_week   ->  LOCKED   (already played)
    week >= provider_current_week   ->  OPEN     (live or still to come)

That is wall-clock independent, needs no stored schedule, and cannot touch a
global row because there is no row. It also makes the seeder replay the season
the way a season actually happens: open week N, play it, finalize it, advance
the current week, and week N locks behind you.

NOTHING HERE IS PRESENTED AS AN NFL KICKOFF. The sentinel datetimes are
deliberately absurd (year 1901 / 2999) so no surface could mistake one for a
real fixture time, and no demo surface displays them.
"""
from __future__ import annotations

from datetime import datetime, timezone

__all__ = ["bet_lock_for_teams", "is_demo_scheduled_league",
           "lock_time_for_league", "lock_time_for_teams"]

#: A demo week that has already been played. Far enough in the past that every
#: `now >= lock` comparison in the gameplay modules reads LOCKED.
DEMO_LOCKED = datetime(1901, 1, 1, tzinfo=timezone.utc)

#: A demo week still open for play. Far enough ahead that no calendar drift can
#: close it, which is what makes the showcase replayable on any date.
DEMO_OPEN = datetime(2999, 1, 1, tzinfo=timezone.utc)


def is_demo_scheduled_league(league) -> bool:
    """Whether this league's lock comes from the demo clock.

    THE SAME THREE-PART BINDING THE REST OF THE DEMO USES, and deliberately not
    a new one: provider `demo`, a key inside the demo namespace, and `showcase`
    in that key. A Yahoo league named "FantasyStakes Demo League" fails it, a
    demo league that is not the showcase fails it, and a league whose key was
    hand-edited to contain "showcase" without the demo namespace fails it.

    NO NAME IS CONSULTED, and there is no flag column — the binding is the only
    thing that decides, exactly as `api.demo_routes.is_demo_league` and
    `demo.reset.assert_demo_league` already require.
    """
    if league is None:
        return False
    try:
        from providers.demo import DEMO_LEAGUE_KEY_PREFIX, DEMO_PROVIDER
    except Exception:                     # pragma: no cover - defensive
        return False

    key = getattr(league, "provider_league_key", "") or ""
    return (getattr(league, "provider", None) == DEMO_PROVIDER
            and key.startswith(DEMO_LEAGUE_KEY_PREFIX)
            and "showcase" in key)


def lock_time_for_league(league, week: int, *, season: int | None = None
                        ) -> datetime:
    """The moment week `week` locks for this league.

    ── `season` IS NOT COSMETIC, AND GETTING IT WRONG IS A REAL REGRESSION ──

    The two production callers deliberately look up DIFFERENT seasons:

      · `beefs.beef_engine` passes `LOCK_SEASON`, which `config.py` documents as
        "NFL schedule season for kickoff-lock checks; independent of
        CURRENT_SEASON (projection data year)"
      · `betting.pool_claims.pool_lock_time` passes nothing and uses
        `league.season`

    The first draft of this module ignored that and always used
    `league.season`. `test_beef_starters.py` — whose league is season 2025 while
    LOCK_SEASON is 2026 — went from green to `ScheduleNotReadyError`, because
    the lock was suddenly looked up in the wrong season. That is exactly the
    "production behaviour must remain equivalent" rule, caught by the suite that
    owns it.

    So the caller's season wins when it supplies one, and `league.season` is
    used only when it does not.

    `ScheduleNotReadyError` still propagates untouched for production leagues.
    """
    from betting.pool_engine import _nfl_lock_time

    if not is_demo_scheduled_league(league):
        return _nfl_lock_time(
            league.season if season is None else season, week)

    current = getattr(league, "provider_current_week", None)
    if current is None:
        # A showcase with no current week has not opened yet; nothing is
        # playable, which is the conservative answer rather than the convenient
        # one.
        return DEMO_LOCKED
    return DEMO_LOCKED if int(week) < int(current) else DEMO_OPEN


def _league_for_teams(db, team_ids):
    """The single league those teams belong to, or None.

    None is the DELIBERATE answer for every ambiguous case — no ids, a mixed
    pair, a missing row. Both callers below turn None into the production path,
    so a resolution failure can never be a way to obtain a demo clock.
    """
    from db.schema import League, Team

    ids = [int(t) for t in team_ids if t is not None]
    if not ids:
        return None
    league_ids = {row[0] for row in
                  db.query(Team.league_id).filter(Team.id.in_(ids)).all()}
    if len(league_ids) != 1:
        return None
    return db.query(League).filter(League.id == league_ids.pop()).first()


def lock_time_for_teams(db, *, team_ids, season: int, week: int) -> datetime:
    """The lock for the league those teams belong to.

    `beefs.beef_engine` reaches the lock holding team ids rather than a league,
    so this resolves the league once and defers to `lock_time_for_league`.

    FAILS TO THE PRODUCTION PATH. If the teams cannot be resolved to a single
    league — a mixed pair, a missing row — this answers with the real NFL lock
    for the season the caller already used. A resolution failure must never be
    a way to obtain a demo clock.
    """
    from betting.pool_engine import _nfl_lock_time

    league = _league_for_teams(db, team_ids)
    if league is None:
        return _nfl_lock_time(season, week)
    # THE CALLER'S SEASON IS CARRIED THROUGH. `beef_engine` asks about
    # LOCK_SEASON, never about the league's own season.
    return lock_time_for_league(league, week, season=season)


def bet_lock_for_teams(db, conn, *, team_ids, player_nfl_teams, week: int,
                       season: int, nfl_lock_check):
    """The PER-BET lock: has this GM's staked roster already kicked off?

    ── WHY THERE IS A SECOND SEAM HERE ──────────────────────────────────────

    `lock_time_for_league` above governs the WEEK. This governs the PLAYERS,
    and it is a genuinely separate gate: `betting.per_bet_lock` looks each
    staked player's NFL club up in `nfl_schedule` and, if it cannot confirm a
    real kickoff for that club anywhere in the season, fail-safes to
    `LockCheck(True, "data_gap")` — locked, to protect the money.

    That fail-safe is exactly right for production and unreachable for the
    showcase. The demo's clubs are DELIBERATELY INVENTED three-letter codes
    (`demo.rosters.CLUBS`) so nothing in the fixture reads as real league data,
    and an invented club is by construction absent from `nfl_schedule`. So
    every demo accept returned `data_gap` and no challenge could ever be
    accepted. The three ways out were to write the demo's clubs into the global
    `nfl_schedule` (refused — it moves the lock for every real league in the
    database), to give the fixture real NFL abbreviations and lean on the real
    2026 slate (refused — it reintroduces exactly the calendar drift this
    module exists to remove, and would start failing the day week 1 kicks off),
    or to seam this site the same way the week lock is already seamed.

    ── THE TWO SEAMS CANNOT DISAGREE ────────────────────────────────────────

    The demo answer below is derived from the SAME rule as
    `lock_time_for_league`: locked exactly while the week is behind the
    league's own `provider_current_week`. One clock, consulted twice.

    ── THE PRODUCTION PATH IS THE CALLER'S OWN FUNCTION ─────────────────────

    `nfl_lock_check` is passed in rather than imported here, and
    `beefs.beef_engine` passes its own module-global `is_bet_locked_for_gm`.
    That keeps the production path byte-identical BY CONSTRUCTION — there is no
    second copy of it to drift — and it preserves the monkeypatch point that
    `test_beef_starters.py` installs on that global to drive its locked/unlocked
    cases. A non-demo league reaches the same function with the same arguments
    it reached before this module existed.
    """
    from betting.per_bet_lock import LockCheck

    league = _league_for_teams(db, team_ids)
    if not is_demo_scheduled_league(league):
        return nfl_lock_check(conn, player_nfl_teams, week, season=season)

    current = getattr(league, "provider_current_week", None)
    if current is None:
        # Same conservative answer as `lock_time_for_league`, in this call's
        # own vocabulary: nothing is playable in a showcase that has not opened.
        return LockCheck(True, "data_gap")
    if int(week) < int(current):
        return LockCheck(True, "in_progress")
    return LockCheck(False, None)
