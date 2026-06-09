"""ProjectionEngine: converts PPR-scored projections to league-adjusted fantasy points.

MVP path: wraps _adjust_for_scoring() from odds/monte_carlo.py, which uses
position-average stat proxies to convert stored FantasyPros PPR points to the
target scoring system.

Post-MVP upgrade: when the FantasyPros API key lands, swap the provider to store
raw production stats; this engine will do exact per-player scoring conversion.
The engine interface is unchanged — only the provider changes.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from odds.monte_carlo import ScoringSettings, _adjust_for_scoring
from data.provider import PlayerProj

STD_PCT  = 0.20  # 20 % of projected mean as σ — matches monte_carlo.py convention
MIN_STD  = 0.5   # floor so zero-projection players still have variance


@dataclass
class ProjDist:
    mean: float  # league-adjusted projected points
    std: float   # standard deviation for Monte Carlo draws


class ProjectionEngine:
    """Applies league scoring rules to a PlayerProj, producing a ProjDist."""

    def __init__(self, scoring: ScoringSettings) -> None:
        self.scoring = scoring

    def adjust(self, player: PlayerProj) -> ProjDist:
        """Convert one player's PPR projection to this league's scoring."""
        mean = _adjust_for_scoring(player.projected_pts, player.position, self.scoring)
        std  = max(MIN_STD, mean * STD_PCT)
        return ProjDist(mean=mean, std=std)

    def adjust_roster(self, players: list[PlayerProj]) -> dict[int, ProjDist]:
        """Adjust all players, keyed by player_id."""
        return {p.player_id: self.adjust(p) for p in players}


# ---------------------------------------------------------------------------
# Acceptance test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from odds.monte_carlo import HALF_PPR, PPR
    from data.provider import PlayerProj

    player = PlayerProj(
        player_id=1,
        name="Test Player",
        position="WR",
        injury_status=None,
        projected_pts=20.0,
    )

    half_ppr_engine = ProjectionEngine(HALF_PPR)
    ppr_engine      = ProjectionEngine(PPR)

    dist_half = half_ppr_engine.adjust(player)
    dist_ppr  = ppr_engine.adjust(player)

    print(f"Player: {player.name} ({player.position}), raw PPR proj = {player.projected_pts}")
    print(f"  HALF_PPR -> mean={dist_half.mean:.4f}, std={dist_half.std:.4f}")
    print(f"  PPR      -> mean={dist_ppr.mean:.4f},  std={dist_ppr.std:.4f}")

    assert isinstance(dist_half, ProjDist), "adjust() must return ProjDist"
    assert dist_half.mean > 0, "HALF_PPR mean must be positive"
    assert dist_ppr.mean > dist_half.mean, (
        f"PPR ({dist_ppr.mean}) must score higher than HALF_PPR ({dist_half.mean}) "
        "for a WR — proves engine reads league settings, not hardcoded points"
    )
    assert dist_half.std >= MIN_STD, "std must respect MIN_STD floor"
    print("  [PASS] HALF_PPR < PPR (engine reads scoring settings)\n")

    # adjust_roster round-trip
    from data.provider import MockProvider
    provider = MockProvider()
    roster   = provider.get_roster(1, 7)
    dists    = half_ppr_engine.adjust_roster(roster.players)

    assert len(dists) == len(roster.players), "adjust_roster must cover every player"
    assert all(isinstance(d, ProjDist) for d in dists.values()), "all values must be ProjDist"
    sample = next(iter(dists.values()))
    print(f"adjust_roster: {len(dists)} players adjusted")
    print(f"  first player -> mean={sample.mean:.4f}, std={sample.std:.4f}")
    print("  [PASS] adjust_roster\n")

    print("All acceptance tests passed.")