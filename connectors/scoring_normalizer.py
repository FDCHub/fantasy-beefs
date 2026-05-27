import sys
import os

# Allow running from any cwd by resolving the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mock_league import TEAMS, SCHEDULE
from connectors.models import (
    NormalizedLeague,
    NormalizedMatchup,
    NormalizedPlayer,
    NormalizedRoster,
)


def _build_roster(team: dict, week: int) -> NormalizedRoster:
    return NormalizedRoster(
        team_id=team["id"],
        team_name=team["name"],
        owner=team["owner"],
        email=team["email"],
        players=[
            NormalizedPlayer(name=p["name"], position=p["pos"])
            for p in team["roster"]
        ],
        week_score=team["scores"][week - 1],
    )


def normalize_week(week: int) -> NormalizedLeague:
    if not 1 <= week <= len(SCHEDULE):
        raise ValueError(f"week must be 1–{len(SCHEDULE)}, got {week}")

    matchups = []
    for home_idx, away_idx in SCHEDULE[week - 1]:
        home = _build_roster(TEAMS[home_idx], week)
        away = _build_roster(TEAMS[away_idx], week)
        matchups.append(NormalizedMatchup(week=week, home=home, away=away))

    return NormalizedLeague(season=2024, week=week, matchups=matchups)


# ── Test / demo ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    league = normalize_week(1)

    print(f"NormalizedLeague  season={league.season}  week={league.week}\n")

    print("┌────┬────────────────────────────┬────────────────────────────┬────────┬────────┬────────┐")
    print("│ #  │ Home                       │ Away                       │  Home  │  Away  │ Margin │")
    print("├────┼────────────────────────────┼────────────────────────────┼────────┼────────┼────────┤")
    for i, m in enumerate(league.matchups, 1):
        w = "←" if m.winner is m.home else "→"
        print(
            f"│ {i:<2} │ {m.home.team_name:<26} │ {m.away.team_name:<26} │"
            f" {m.home.week_score:>6.1f} │ {m.away.week_score:>6.1f} │ {w}{m.margin:>5.1f} │"
        )
    print("└────┴────────────────────────────┴────────────────────────────┴────────┴────────┴────────┘")

    hi = league.highest_scorer
    lo = league.lowest_scorer
    print(f"\nHighest scorer : {hi.team_name} ({hi.owner})  {hi.week_score} pts")
    print(f"Lowest scorer  : {lo.team_name} ({lo.owner})  {lo.week_score} pts")

    print(f"\nNormalizedRoster sample — {league.matchups[0].home.team_name}")
    print(f"  owner : {league.matchups[0].home.owner}")
    print(f"  email : {league.matchups[0].home.email}")
    print(f"  score : {league.matchups[0].home.week_score}")
    print(f"  roster ({len(league.matchups[0].home.players)} players):")
    for p in league.matchups[0].home.players:
        print(f"    [{p.position:<4}] {p.name}")
