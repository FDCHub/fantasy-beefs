"""The showcase's weekly box score, and the provider snapshot that carries it.

WHY THIS EXISTS. The Prop Pool engine does not read the ledger or the fixture —
it settles from a PROVIDER STAT SOURCE, and it refuses a week it cannot fully
support. `betting.pool_subjects.LocalRecordedStatSource` covers exactly three
canonical operands (`player_fantasy_points` and the two matchup scores), which
supports three catalog definitions; POR §4.1 requires FOUR fully supported
definitions to fill one week's slate, so the showcase's first attempt at a real
pool week was refused:

    PoolSlateError [INSUFFICIENT_ELIGIBLE_DEFINITIONS] — 3 definitions pass
    BOTH gates, which cannot fill 4 fresh slots even after a cycle reset.

That refusal is the product working. The answer is not to lower the bar but to
supply the stats: the showcase is a `demo`-provider league, `providers/demo`
already has a certified stat source and a certified gate-2 measurement, and this
module gives them a week to read.

── EVERY NUMBER HERE IS INVENTED ────────────────────────────────────────────

No Yahoo stat id, no Yahoo player, no recorded real performance. The raw lines
are built from `demo.rosters`' fictional players against the DEMO PROVIDER'S OWN
declared vocabulary (`providers.demo.pool_source.DEMO_STAT_NAMES`), which is
itself checked against the governed stat artifact — so a name invented here that
the catalog has never heard of is refused at load, not quietly dropped.

── FANTASY POINTS ARE REPORTED, NOT RECOMPUTED ──────────────────────────────

`ProviderPlayerStats` carries `fantasy_points` as a field SEPARATE from `values`,
because a provider reports the scoring result its own league settings produced —
it is not a function of the raw line that any consumer could re-derive. The
showcase uses that separation deliberately: the raw line is the box score, and
`fantasy_points` is scaled so a team's nine starters sum EXACTLY to that team's
score in `demo.showcase.REGULAR_SCHEDULE`.

That keeps the fixture authoritative. The season's storylines — the 8-2 leader,
the comeback — live in the schedule, and the box score is made to agree with them
rather than the standings being whatever a stat generator happened to produce.

DETERMINISTIC BY CONSTRUCTION. Pure functions of `(team ordinal, roster slot,
week)`, no RNG and no clock, for the same reason `demo.rosters` is: a demo whose
pool winners moved between showings would be worse than one with no pools.
"""
from __future__ import annotations

from demo import rosters, showcase

#: How much of each stat family a slot produces, as (pass, rush, receive, kick)
#: weights. A weight of 0 does not mean the stat is absent — see `stat_line`.
_SLOT_SHAPE: dict = {
    "QB":   (1.00, 0.25, 0.00, 0.0),
    "RB":   (0.00, 1.00, 0.30, 0.0),
    "WR":   (0.00, 0.05, 1.00, 0.0),
    "TE":   (0.00, 0.00, 1.00, 0.0),
    "FLEX": (0.00, 0.55, 0.55, 0.0),
    "K":    (0.00, 0.00, 0.00, 1.0),
    "DEF":  (0.00, 0.00, 0.00, 0.0),
}


def _spread(team_ordinal: int, index: int, week: int) -> float:
    """The player's share weight for the week, before scaling to the team score.

    DELIBERATELY NOT THE PROJECTION. `rosters.projected_points` is the FORECAST
    the odds were priced from; if actuals equalled it, every favourite would win
    and the demo's markets would be decorative. This carries the same positional
    shape with a different phase, so results diverge from the line the way real
    weeks do — while staying a pure function of the same three inputs.
    """
    base = rosters.projected_points(team_ordinal, index, week)
    swing = ((team_ordinal * 19 + index * 23 + week * 29) % 11) * 0.9 - 4.5
    return max(1.0, base + swing)


def actual_points_for_team(team_ordinal: int, week: int) -> tuple:
    """Each starter's reported fantasy points, summing EXACTLY to the team score.

    The residual from rounding is given to the week's top scorer rather than
    spread, so the sum is exact and the adjustment lands where a tenth of a point
    is least visible. Returns () for a week the fixture has not played.
    """
    total = showcase.team_score(team_ordinal, week)
    if total is None:
        return ()

    weights = [_spread(team_ordinal, i, week) for i in range(len(rosters.SLOTS))]
    scale = total / sum(weights)
    points = [round(w * scale, 1) for w in weights]

    residual = round(total - sum(points), 1)
    if residual:
        top = max(range(len(points)), key=lambda i: points[i])
        points[top] = round(points[top] + residual, 1)
    return tuple(points)


def stat_line(team_ordinal: int, index: int, week: int, points: float) -> dict:
    """A raw box-score line for one starter — EVERY governed stat, every week.

    ── WHY A KICKER REPORTS ZERO RUSHING YARDS ──────────────────────────────

    A first version reported only the stats a slot specialises in and left the
    rest out. Pool settlement then refused two of week 6's four occurrences:

        [NO_EVALUABLE_SUBJECTS] definition='highest_yards_per_touch'
        considered=12 evaluated=0 unevaluable=[1..12]

    `yards_per_touch` needs the governed derived operand `touches`, and
    `betting.pool_subjects.normalize_component` produces a derived stat ONLY
    when every input is present — deliberately, so a partial formula can never
    yield a plausible-looking partial sum. A kicker with no `rush_attempts` key
    therefore made its whole TEAM unevaluable.

    Absence and zero are different claims, and here zero is the true one: a
    kicker really did have zero rush attempts, and a real provider's box score
    says so. So every line carries every stat in the demo provider's declared
    vocabulary, with the slot's shape deciding the magnitudes and honest zeros
    everywhere else.

    A DEF reports zeros across the board. The demo vocabulary carries no
    defensive operand, so there is nothing truthful to put there; its
    contribution to the demo is `player_fantasy_points`, which it does report.
    """
    from providers.demo.pool_source import DEMO_STAT_NAMES

    pass_w, rush_w, rec_w, kick_w = _SLOT_SHAPE[rosters.SLOTS[index]]

    # A small deterministic tilt so two players on equal points do not produce
    # identical lines — the evaluators rank on these, and exact ties across a
    # slate would make the winner set an artifact of row order.
    tilt = ((team_ordinal * 13 + index * 7 + week * 5) % 7) - 3

    values = {name: 0.0 for name in DEMO_STAT_NAMES}
    if pass_w:
        values["passing_yards"] = float(round(points * 11.0 * pass_w + tilt * 4))
        values["passing_td"] = float(max(0, int(points * pass_w // 5)))
        values["interceptions_thrown"] = float(max(0, (int(points) + tilt) % 3 - 1))
    if rush_w:
        values["rush_attempts"] = float(max(1, int(points * rush_w // 2)))
        values["rushing_yards"] = float(round(points * 3.4 * rush_w + tilt * 2))
        values["rushing_td"] = float(max(0, int(points * rush_w // 7)))
    if rec_w:
        values["receptions"] = float(max(1, int(points * rec_w // 2.5)))
        values["receiving_yards"] = float(round(points * 6.2 * rec_w + tilt * 3))
        values["receiving_td"] = float(max(0, int(points * rec_w // 8)))
        values["targets"] = float(max(1, int(points * rec_w // 2.5) + 2))
    if kick_w:
        values["extra_points_made"] = float(max(0, int(points // 4)))
        # ── HOW MANY FIELD GOALS, THEN WHICH BRACKETS ────────────────────────
        #
        # A first version asked each bracket independently whether it held the
        # week's one kick, so every kicker in the league made EXACTLY one field
        # goal. `most_field_goals_made` then ranked twelve teams tied at 1.0 —
        # a real tie, correctly split twelve ways, and a terrible demo: the
        # slate showed a pool nobody could win.
        #
        # So the COUNT comes first, from the kicker's own scoring day, and the
        # brackets are then filled from it. A quiet week is 0, a big one is 3,
        # and the field spreads out the way a real week does.
        made = max(0, min(3, int((points + tilt) // 3)))
        brackets = ("field_goals_made_20_29", "field_goals_made_30_39",
                    "field_goals_made_40_49")
        for offset, name in enumerate(brackets):
            values[name] = float(1.0 if offset < made else 0.0)
    return values


# ── the provider snapshot ────────────────────────────────────────────────────

def snapshot_for_week(league, teams: dict, week: int):
    """One `ProviderWeek` for the showcase, as the demo provider would emit it.

    THE SAME DTO EVERY PROVIDER EMITS, so `providers.demo.pool_source` reads it
    with no special case and `betting/` stays unaware that a demo exists. The
    keys are the showcase's own provider namespace, which is what the certified
    identity resolver maps back to team ids — never the team name.
    """
    from providers.base import (
        Finality, ProviderLeague, ProviderMatchup, ProviderPlayerStats,
        ProviderRosterEntry, ProviderTeam, ProviderWeek,
    )
    from providers.demo import DEMO_PROVIDER
    from demo.seed import team_key_for

    league_key = league.provider_league_key
    p_league = ProviderLeague(
        provider=DEMO_PROVIDER, league_key=league_key, name=league.name,
        season=int(league.season), current_week=week,
        season_final_week=showcase.SEASON_FINAL_WEEK,
        playoff_start_week=showcase.PLAYOFF_START_WEEK,
        start_week=showcase.START_WEEK)

    p_teams = []
    roster_entries = []
    player_stats = []
    for spec in showcase.TEAMS:
        team_key = team_key_for(league.id, spec.ordinal)
        p_teams.append(ProviderTeam(
            provider=DEMO_PROVIDER, team_key=team_key,
            team_id=str(spec.ordinal), name=spec.team_name,
            manager=spec.gm))

        points = actual_points_for_team(spec.ordinal, week)
        for index, slot in enumerate(rosters.SLOTS):
            player_key = rosters.player_key(league_key, spec.ordinal, index)
            roster_entries.append(ProviderRosterEntry(
                provider=DEMO_PROVIDER, team_key=team_key,
                player_key=player_key, player_id=f"{spec.ordinal}.{index}",
                week=week, slot=slot,
                name=rosters.player_name(spec.ordinal, index),
                nfl_team=rosters.CLUBS[(spec.ordinal + index) % len(rosters.CLUBS)]))

            if not points:
                # An unplayed week reports no stats at all. NOT ZEROS — a zero
                # is a measured fact and would make an unplayed week look
                # settleable; absence is what makes it unevaluable, which is
                # the state the finality gate and the pool engine both expect.
                continue
            pts = points[index]
            values = stat_line(spec.ordinal, index, week, pts)
            player_stats.append(ProviderPlayerStats(
                provider=DEMO_PROVIDER, player_key=player_key, week=week,
                values=values, stat_ids_present=frozenset(values),
                fantasy_points=pts))

    matchups = []
    for home, away, home_pts, away_pts in showcase.REGULAR_SCHEDULE.get(week, ()):
        final = home_pts is not None
        matchups.append(ProviderMatchup(
            provider=DEMO_PROVIDER, league_key=league_key,
            matchup_key=f"{league_key}.m.{week}.{home}.{away}", week=week,
            home_team_key=team_key_for(league.id, home),
            away_team_key=team_key_for(league.id, away),
            home_points=float(home_pts or 0.0),
            away_points=float(away_pts or 0.0),
            finality=Finality.FINAL if final else Finality.NOT_FINAL,
            winner_team_key=(
                None if not final or home_pts == away_pts
                else team_key_for(league.id,
                                  home if home_pts > away_pts else away))))

    return ProviderWeek(
        league=p_league, week=week, teams=tuple(p_teams),
        matchups=tuple(matchups), roster_entries=tuple(roster_entries),
        player_stats=tuple(player_stats),
        observed_at=showcase.OBSERVED_AT)
