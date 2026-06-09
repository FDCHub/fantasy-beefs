"""LineupOptimizer: picks the highest-projected legal starting lineup for a roster.

Slot fill order follows the canonical sequence: QB, RB, WR, TE, FLEX, K, DEF.
FLEX is eligible for RB/WR/TE. Players with injury_status "out" or "ir" are
excluded from the eligible pool before any selection.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.provider import LeagueConfig, PlayerProj, RosterState

_OUT_STATUSES = frozenset({"out", "ir"})

# Canonical slot order and which positions are eligible per slot.
# FLEX is the only multi-position slot; all others are single-position.
_CANONICAL_ORDER = ["QB", "RB", "WR", "TE", "FLEX", "K", "DEF"]

_SLOT_ELIGIBILITY: dict[str, frozenset[str]] = {
    "QB":   frozenset({"QB"}),
    "RB":   frozenset({"RB"}),
    "WR":   frozenset({"WR"}),
    "TE":   frozenset({"TE"}),
    "FLEX": frozenset({"RB", "WR", "TE"}),
    "K":    frozenset({"K"}),
    "DEF":  frozenset({"DEF"}),
}


class LineupOptimizer:

    def optimize(self, roster: RosterState, config: LeagueConfig) -> list[PlayerProj]:
        """Return the highest-projected legal starting lineup.

        Fills slots in canonical order (QB, RB, WR, TE, FLEX, K, DEF) using
        counts from config.roster_slots. A player can only fill one slot.
        Players with injury_status in ("out", "ir") are never selected.
        If a slot cannot be filled, it is skipped rather than raising.
        """
        eligible = [p for p in roster.players if p.injury_status not in _OUT_STATUSES]

        used_ids: set[int] = set()
        lineup: list[PlayerProj] = []

        for slot_name in _CANONICAL_ORDER:
            count = config.roster_slots.get(slot_name, 0)
            valid_positions = _SLOT_ELIGIBILITY[slot_name]

            for _ in range(count):
                candidates = [
                    p for p in eligible
                    if p.position in valid_positions and p.player_id not in used_ids
                ]
                if not candidates:
                    continue  # slot cannot be filled — skip rather than crash
                best = max(candidates, key=lambda p: p.projected_pts)
                lineup.append(best)
                used_ids.add(best.player_id)

        return lineup


# ---------------------------------------------------------------------------
# Acceptance test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.provider import LeagueConfig, PlayerProj, RosterState
    from odds.monte_carlo import HALF_PPR

    # Hand-built roster — no external data files needed.
    #
    # Slot-fill trace (RB3-OUT excluded from eligible pool):
    #   QB   -> QB Star      30.0
    #   RB   -> RB1          22.0
    #   RB   -> RB2          18.0
    #   WR   -> WR1          21.0
    #   WR   -> WR2          17.0
    #   TE   -> TE1          16.0
    #   FLEX -> RB4          14.0  (best remaining RB/WR/TE: RB4=14 > WR3=13 > TE2=10)
    #   K    -> Kicker        9.0
    #   DEF  -> Defense       8.0
    #   Expected total       = 155.0

    EXPECTED_SUM = 155.0

    players = [
        PlayerProj(player_id=1,  name="QB Star",   position="QB",  injury_status=None,  projected_pts=30.0),
        PlayerProj(player_id=2,  name="QB Backup", position="QB",  injury_status=None,  projected_pts=20.0),
        PlayerProj(player_id=3,  name="RB1",       position="RB",  injury_status=None,  projected_pts=22.0),
        PlayerProj(player_id=4,  name="RB2",       position="RB",  injury_status=None,  projected_pts=18.0),
        PlayerProj(player_id=5,  name="RB3 OUT",   position="RB",  injury_status="out", projected_pts=25.0),
        PlayerProj(player_id=6,  name="RB4",       position="RB",  injury_status=None,  projected_pts=14.0),
        PlayerProj(player_id=7,  name="WR1",       position="WR",  injury_status=None,  projected_pts=21.0),
        PlayerProj(player_id=8,  name="WR2",       position="WR",  injury_status=None,  projected_pts=17.0),
        PlayerProj(player_id=9,  name="WR3",       position="WR",  injury_status=None,  projected_pts=13.0),
        PlayerProj(player_id=10, name="TE1",       position="TE",  injury_status=None,  projected_pts=16.0),
        PlayerProj(player_id=11, name="TE2",       position="TE",  injury_status=None,  projected_pts=10.0),
        PlayerProj(player_id=12, name="Kicker",    position="K",   injury_status=None,  projected_pts=9.0),
        PlayerProj(player_id=13, name="Defense",   position="DEF", injury_status=None,  projected_pts=8.0),
    ]

    roster = RosterState(team_id=1, team_name="Test Team", week=1, players=players)

    config = LeagueConfig(
        league_id=1,
        season=2024,
        n_teams=10,
        playoff_start_week=15,
        n_playoff_teams=6,
        scoring=HALF_PPR,
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1},
    )

    optimizer = LineupOptimizer()
    lineup = optimizer.optimize(roster, config)

    print("Lineup:")
    for p in lineup:
        print(f"  pid={p.player_id:<3} {p.name:<12} {p.position:<5} {p.projected_pts:>5} pts")

    # --- no duplicates ---
    lineup_ids = [p.player_id for p in lineup]
    assert len(lineup_ids) == len(set(lineup_ids)), "Duplicate player in lineup"
    print("\n  [PASS] no duplicate players")

    # --- OUT player excluded ---
    out_player = next(p for p in players if p.injury_status == "out")
    assert out_player.player_id not in lineup_ids, (
        f"{out_player.name} (injury_status='out') must not appear in lineup"
    )
    print(f"  [PASS] OUT player '{out_player.name}' not in lineup")

    # --- total matches hand-computed expected ---
    total = sum(p.projected_pts for p in lineup)
    assert total == EXPECTED_SUM, f"Expected total {EXPECTED_SUM}, got {total}"
    print(f"  [PASS] total projected pts = {total} (matches expected {EXPECTED_SUM})")

    # --- 9 starters filled ---
    assert len(lineup) == 9, f"Expected 9 starters, got {len(lineup)}"
    print(f"  [PASS] {len(lineup)} starters filled\n")

    print("All acceptance tests passed.")
