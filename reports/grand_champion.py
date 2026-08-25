"""RC2 Grand Champion recognition.

Grand Champion is an unfunded season-ending recognition based only on the Yahoo
Championship podium and the FantasyStakes Championship podium. Regular-season
Points Champion / Skunk recognition is intentionally outside this calculation.

When a component championship contains a tie, the Grand Champion points for the
ordinal places occupied by that tied group are pooled and divided equally among
all GMs in the tie. This mirrors the locked FantasyStakes championship tied-podium
rule and preserves the total component points available.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

POINTS_BY_PLACE = {1: 3, 2: 2, 3: 1}


@dataclass(frozen=True)
class ChampionshipFinish:
    team_id: int
    place: int


@dataclass(frozen=True)
class GrandChampionRow:
    team_id: int
    yahoo_points: Fraction
    fantasystakes_points: Fraction
    #: This GM's authoritative FantasyStakes Championship Score in integer
    #: cents, carried only so a decided tiebreak can be explained. It is the
    #: frozen realized-net competitive figure — never a wallet balance — and it
    #: takes no part in the points arithmetic above.
    fantasystakes_score_cents: int | None = None

    @property
    def combined_points(self) -> Fraction:
        return self.yahoo_points + self.fantasystakes_points


@dataclass(frozen=True)
class GrandChampionResult:
    rows: tuple[GrandChampionRow, ...]
    champion_team_ids: tuple[int, ...]
    #: True when GMs tied on combined points and the FantasyStakes Championship
    #: Score actually separated them. False when no tie existed, and false when
    #: a tie survived the tiebreak — in both of those cases there is nothing for
    #: a surface to explain, so it must not show a tiebreak line.
    tiebreak_used: bool = False

    @property
    def co_champions(self) -> bool:
        return len(self.champion_team_ids) > 1


def _component_points(finishes: tuple[ChampionshipFinish, ...]) -> dict[int, Fraction]:
    """Return exact Grand Champion points for one component championship.

    Competition-style places are expected: a two-way tie for first is represented
    as places 1, 1 and the next finisher is place 3. A tied group beginning at
    place ``p`` occupies ordinal slots ``p .. p + group_size - 1``. Only the
    1st/2nd/3rd slots carry Grand Champion points; slots beyond third contribute
    zero. The occupied points are pooled and split equally across the tied group.
    """
    team_ids = [finish.team_id for finish in finishes]
    if len(team_ids) != len(set(team_ids)):
        raise ValueError("component championship contains duplicate team_id")
    if any(finish.place < 1 for finish in finishes):
        raise ValueError("component championship place must be >= 1")

    by_place: dict[int, list[int]] = {}
    for finish in finishes:
        by_place.setdefault(finish.place, []).append(finish.team_id)

    points: dict[int, Fraction] = {}
    occupied_until = 0
    for place in sorted(by_place):
        team_group = sorted(by_place[place])
        if place <= occupied_until:
            raise ValueError(
                "component championship places overlap a preceding tied group"
            )
        occupied_slots = range(place, place + len(team_group))
        pool = sum(POINTS_BY_PLACE.get(slot, 0) for slot in occupied_slots)
        share = Fraction(pool, len(team_group))
        for team_id in team_group:
            points[team_id] = share
        occupied_until = place + len(team_group) - 1

    return points


def calculate_grand_champion(
    *, yahoo_finishes: tuple[ChampionshipFinish, ...],
    fantasystakes_finishes: tuple[ChampionshipFinish, ...],
    fantasystakes_scores: dict | None = None,
) -> GrandChampionResult:
    """Combine both component championships and break a tie on realized net.

    THREE STEPS, IN ORDER, AND THE ORDER IS THE RULE.

      1. Component finishes score 3 / 2 / 1. A tied component finish pools the
         point values of the ordinal places the tied group occupies and splits
         them exactly, so a two-way tie for first is 5/2 each. This step is
         unchanged and still uses exact Fractions.
      2. If two or more GMs share the highest combined total, the higher
         FantasyStakes CHAMPIONSHIP SCORE wins — the authoritative frozen
         realized-net figure, never a wallet balance.
      3. If they are still level, they are co-Grand Champions.

    THE TIEBREAK IS A SECOND STEP, NOT A SECOND SCORE. It is applied only to
    candidates already level on points, and it never reorders anyone else or
    changes a single point value. `fantasystakes_scores` is optional: a caller
    that cannot supply authoritative scores gets the previous behaviour — every
    tied GM is a co-champion — rather than a tiebreak decided on absent data.
    """
    scores = dict(fantasystakes_scores or {})
    yahoo = _component_points(yahoo_finishes)
    fs = _component_points(fantasystakes_finishes)
    team_ids = sorted(set(yahoo) | set(fs))
    rows = tuple(
        sorted(
            (
                GrandChampionRow(
                    team_id=team_id,
                    yahoo_points=yahoo.get(team_id, Fraction(0, 1)),
                    fantasystakes_points=fs.get(team_id, Fraction(0, 1)),
                    fantasystakes_score_cents=(
                        int(scores[team_id]) if team_id in scores else None),
                )
                for team_id in team_ids
            ),
            key=lambda row: (-row.combined_points, row.team_id),
        )
    )
    if not rows:
        return GrandChampionResult(rows=(), champion_team_ids=())

    high = rows[0].combined_points
    level = [row for row in rows if row.combined_points == high]
    if len(level) == 1:
        return GrandChampionResult(rows=rows,
                                   champion_team_ids=(level[0].team_id,))

    # ── STEP 2 ───────────────────────────────────────────────────────────────
    # Only candidates already level on points are compared, and only on the
    # authoritative Championship Score. A candidate with no score cannot be
    # ranked against one that has one, so an incomplete set decides nothing and
    # falls through to co-champions rather than guessing.
    ranked = [row for row in level if row.fantasystakes_score_cents is not None]
    if len(ranked) == len(level) and ranked:
        best = max(row.fantasystakes_score_cents for row in ranked)
        winners = tuple(row.team_id for row in ranked
                        if row.fantasystakes_score_cents == best)
        # STEP 3 — still level on score is a real co-championship, and the
        # tiebreak did not decide it, so nothing may be presented as if it had.
        return GrandChampionResult(
            rows=rows, champion_team_ids=winners,
            tiebreak_used=len(winners) < len(level))

    return GrandChampionResult(
        rows=rows, champion_team_ids=tuple(row.team_id for row in level))
