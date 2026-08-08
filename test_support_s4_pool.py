"""
test_support_s4_pool.py — shared S4-P1 Pool fixtures.

INFRASTRUCTURE, NOT A TEST. No assertions live here; the Postgres suites import
it. Everything is built through the REAL production paths — the real catalog
loader, the real seeder, the real ledger — so a fixture cannot pass by
constructing a state production could never reach.

WHY GATE-2 READINESS IS SET EXPLICITLY AND NARROWLY. POR §1.2 records the true
environment as 0 league-activation-ready, so with no readiness rows NOTHING is
selectable and no slate can be built. That is correct production behavior and
the suites assert it. To exercise the engine, a fixture measures readiness for
an EXPLICIT, NAMED set of definitions — which additionally pins which four the
selector draws, so a test knows each drawn definition's scope and required
stats without depending on the digest ordering.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

PROVIDER = "test-recorded-fixtures"

#: Four TEAM-scope CLOSED_SUM definitions, all gate-1 eligible, each requiring a
#: single canonical stat. Chosen so a fixture supplies one number per team.
FOUR_TEAM_KEYS = (
    "most_passing_yards",       # #20  passing_yards
    "most_rushing_yards",       # #21  rushing_yards
    "most_receiving_yards",     # #22  receiving_yards
    "most_passing_touchdowns",  # #23  passing_td
)

REQUIRED_STAT = {
    "most_passing_yards": "passing_yards",
    "most_rushing_yards": "rushing_yards",
    "most_receiving_yards": "receiving_yards",
    "most_passing_touchdowns": "passing_td",
}

# Four TEAM QUALIFIER definitions, all gate-1 eligible and all rollover-eligible
# (POR §5: the 16 QUALIFIER definitions roll; the 64 RANK_EXTREMUM ones do not).
# Marking exactly these four ready makes the whole slate rollover-capable, so the
# carry lifecycle can be exercised at the production slate width of four rather
# than by narrowing it.
FOUR_QUALIFIER_KEYS = (
    "the_grand_slam",                              # #1  needs a field goal
    "passing_rushing_receiving_td_trifecta",       # #2  three TD types
    "recorded_both_a_rushing_and_receiving_td",    # #3  two TD types
    "recorded_a_passing_and_rushing_td",           # #4  two TD types
)

#: The union of every stat those four require, so one fixture covers all four.
QUALIFIER_ALL_STATS = ("passing_td", "rushing_td", "receiving_td",
                       "field_goals_made", "total_touchdown_credits")


def make_league(db, *, name: str, season: int, n_teams: int = 4,
                wallet_cents: int = 100_000, week: int = 3,
                season_final_week: int = 17, playoff_start_week: int = 15):
    """Create a league with funded teams, wallets, matchups and a schedule.

    Wallets are funded through a REAL ledger posting from `world`, never by
    writing a balance column — `Wallet.balance` is a display mirror and is not
    authoritative for anything (P1-L2/P1-L3B). A fixture that set it would fund
    nothing the funded-balance guard can see.
    """
    from db.schema import League, Matchup, NflSchedule, Team, Wallet
    from ledger.ledger import post as ledger_post

    league = League(season=season, name=name, projection_source="fantasypros",
                    season_final_week=season_final_week,
                    playoff_start_week=playoff_start_week)
    db.add(league)
    db.flush()

    teams = []
    for i in range(n_teams):
        team = Team(league_id=league.id, team_name=f"{name}-team-{i}",
                    owner=f"owner-{i}", email=f"{name}-{i}@example.test")
        db.add(team)
        db.flush()
        db.add(Wallet(team_id=team.id, balance=0.0))
        teams.append(team)
    db.flush()

    for team in teams:
        ledger_post([("world", -wallet_cents), (f"wallet:{team.id}", wallet_cents)],
                    door="buy_in_paid", session=db)

    for i in range(0, len(teams) - 1, 2):
        db.add(Matchup(league_id=league.id, week=week,
                       home_team_id=teams[i].id, away_team_id=teams[i + 1].id,
                       home_score=0.0, away_score=0.0))

    # Lock time: one kickoff well in the future, inside the real NFL window the
    # 9..26-hour band check accepts, so claims are open during the test.
    kickoff = datetime.now(timezone.utc) + timedelta(days=2)
    kickoff = kickoff.replace(hour=17, minute=0, second=0, microsecond=0,
                              tzinfo=None)
    # The team codes carry the league name because NflSchedule is UNIQUE on
    # (season, week, home_team, away_team) and is NOT league-scoped — two
    # fixtures built in one reset window would otherwise collide on a row
    # neither of them cares about.
    db.add(NflSchedule(season=season, week=week,
                       home_team=_code(name, week, "H"),
                       away_team=_code(name, week, "A"),
                       kickoff_utc=kickoff))
    db.flush()
    return league, teams


def _code(name: str, week: int, side: str) -> str:
    """A NflSchedule team code unique to one fixture league and week.

    Deterministic — no builtin hash(), which is salted per process and would
    make the same fixture produce different rows on different runs."""
    return f"{side}{week}-{name}"


def add_week_schedule(db, *, season: int, week: int,
                      name: str = "fixture") -> None:
    """A kickoff row for a further week, so its lock time resolves."""
    from db.schema import NflSchedule

    kickoff = datetime.now(timezone.utc) + timedelta(days=2 + week)
    kickoff = kickoff.replace(hour=17, minute=0, second=0, microsecond=0,
                              tzinfo=None)
    db.add(NflSchedule(season=season, week=week,
                       home_team=_code(name, week, "H"),
                       away_team=_code(name, week, "A"),
                       kickoff_utc=kickoff))
    db.flush()


def add_week_matchups(db, *, league_id: int, week: int, teams) -> None:
    from db.schema import Matchup

    for i in range(0, len(teams) - 1, 2):
        db.add(Matchup(league_id=league_id, week=week,
                       home_team_id=teams[i].id, away_team_id=teams[i + 1].id,
                       home_score=0.0, away_score=0.0))
    db.flush()


def seed_catalog(db):
    """Seed all 80 Rev1.3 definitions through the real seeder."""
    from betting.pool_catalog import seed_definitions

    return seed_definitions(db)


def mark_ready(db, *, league_id: int, keys, provider: str = PROVIDER,
               ready: bool = True, measured_at: datetime | None = None) -> None:
    """Record gate-2 readiness for an explicit set of definitions."""
    from betting.pool_gates import record_activation_measurement

    for key in keys:
        record_activation_measurement(
            db, league_id=league_id, provider=provider, definition_key=key,
            ready=ready, block_reasons=() if ready else ("FIXTURE_NOT_READY",),
            measured_at=measured_at)


def team_subjects(teams, *, stat: str, values, covered=None):
    """One TEAM Subject per team carrying a single canonical stat.

    `values` maps team_id -> float. A team omitted from `values` is supplied
    with NO coverage, which is how a fixture makes exactly one subject
    unevaluable without deleting it from the league structure."""
    from betting.pool_subjects import StatComponent, Subject, TeamFrame

    covered = covered if covered is not None else {stat}
    subjects = []
    for team in teams:
        if team.id in values:
            frame = TeamFrame(
                team_id=team.id,
                components=(StatComponent(values={stat: float(values[team.id])},
                                          slot="QB", position="QB"),),
                covered_stats=frozenset(covered))
        else:
            frame = TeamFrame(team_id=team.id, components=(),
                              covered_stats=frozenset())
        subjects.append(Subject(subject_id=team.id, subject_type="TEAM",
                                frames=(frame,)))
    return subjects


def multi_stat_team_subjects(teams, *, per_team, covered):
    """One TEAM Subject per team carrying several canonical stats."""
    from betting.pool_subjects import StatComponent, Subject, TeamFrame

    subjects = []
    for team in teams:
        values = per_team.get(team.id)
        if values is None:
            frame = TeamFrame(team_id=team.id, components=(),
                              covered_stats=frozenset())
        else:
            frame = TeamFrame(
                team_id=team.id,
                components=(StatComponent(
                    values={k: float(v) for k, v in values.items()},
                    slot="QB", position="QB"),),
                covered_stats=frozenset(covered))
        subjects.append(Subject(subject_id=team.id, subject_type="TEAM",
                                frames=(frame,)))
    return subjects


class DefinitionStatSource:
    """A recorded-fixture stat source that answers per definition key.

    `settle_week` walks four occurrences with different definitions, so one
    flat subject list cannot serve them. This maps definition_key -> subjects
    and is bound to the instance being settled by the caller."""

    def __init__(self, by_definition: dict):
        self._by_definition = by_definition
        self._current_key = None

    def for_definition(self, key: str) -> "DefinitionStatSource":
        self._current_key = key
        return self

    def subjects_for(self, *, league_id, season, week, structure):
        subjects = self._by_definition.get(self._current_key, ())
        wanted = set(structure.considered_subject_ids)
        return tuple(s for s in subjects if s.subject_id in wanted)


def settle_each(db, *, league_id: int, week: int, source: DefinitionStatSource):
    """Settle every instance of a week, binding the source per definition.

    Deliberately does what betting.pool_settlement.settle_week does, one
    instance at a time, so the fixture can point the recorded source at the
    right definition before each call."""
    from datetime import datetime, timezone

    from betting.pool_settlement import settle_pool_instance
    from db.schema import PoolInstance, PoolPot

    instances = (db.query(PoolInstance)
                 .filter(PoolInstance.league_id == league_id,
                         PoolInstance.week == week)
                 .order_by(PoolInstance.slot).all())
    results = []
    for instance in instances:
        results.append(settle_pool_instance(
            db, pool_instance_id=instance.id,
            stat_source=source.for_definition(instance.definition_key)))

    # Mirrors betting.pool_settlement.settle_week's tail: the week container is
    # marked settled only when every instance actually settled. The next week's
    # collection refuses to run while any earlier week is unsettled, so a
    # fixture that skipped this would block the following week for the wrong
    # reason.
    if instances and all(i.settled for i in instances):
        pot = (db.query(PoolPot)
               .filter(PoolPot.league_id == league_id, PoolPot.week == week)
               .first())
        if pot is not None:
            pot.settled = True
            pot.settled_at = datetime.now(timezone.utc)
    db.flush()
    return results


def trial_balance_zero() -> bool:
    """The ledger's global invariant: every posting balances, so the sum of
    every entry ever written is exactly zero."""
    from ledger.ledger import trial_balance

    return trial_balance() == 0
