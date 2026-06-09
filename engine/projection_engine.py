from __future__ import annotations
import os, sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from odds.monte_carlo import ScoringSettings, HALF_PPR
from connectors.fantasypros_connector import RawProj
from data.provider import PlayerProj

STD_PCT = 0.20
MIN_STD = 0.5

@dataclass
class ProjDist:
    mean: float
    std:  float

@dataclass
class ExtendedScoringSettings:
    base:           ScoringSettings
    pass_yd_points: float = 0.04
    rush_yd_points: float = 0.1
    rec_yd_points:  float = 0.1

CULV_SCORING = ExtendedScoringSettings(base=HALF_PPR)

def score_raw(raw: RawProj, scoring: ExtendedScoringSettings) -> float:
    points = (
        (raw.pass_yds * scoring.pass_yd_points)
      + (raw.pass_tds * scoring.base.pass_td_points)
      + (raw.pass_int * -2.0)
      + (raw.rush_yds * scoring.rush_yd_points)
      + (raw.rush_tds * scoring.base.rush_td_points)
      + (raw.rec_rec  * scoring.base.rec_points)
      + (raw.rec_yds  * scoring.rec_yd_points)
      + (raw.rec_tds  * scoring.base.rec_td_points)
      + (raw.fumbles  * -2.0)
      + (raw.ret_tds  * 6.0)
      + (raw.two_pt_tds * 2.0)
    )
    return max(0.0, round(points, 4))

class ProjectionEngine:
    def __init__(self, scoring: ExtendedScoringSettings) -> None:
        self.scoring = scoring

    def to_dist(self, raw: RawProj) -> ProjDist:
        mean = score_raw(raw, self.scoring)
        std  = max(MIN_STD, mean * STD_PCT)
        return ProjDist(mean=mean, std=std)

    def to_player_proj(self, raw: RawProj, player_id: int) -> PlayerProj:
        dist = self.to_dist(raw)
        return PlayerProj(
            player_id     = player_id,
            name          = raw.name,
            position      = raw.position,
            injury_status = None,
            projected_pts = dist.mean,
        )

    def score_roster(self, raws: list[RawProj], id_map: dict[str, int]) -> dict[int, ProjDist]:
        return {
            id_map[r.fpid]: self.to_dist(r)
            for r in raws
            if r.fpid in id_map
        }

if __name__ == "__main__":
    engine = ProjectionEngine(CULV_SCORING)

    hurts_raw = RawProj(
        fpid="19275",
        yahoo_player_id=None,
        name="Jalen Hurts",
        position="QB",
        team="PHI",
        bye_week=None,
        pass_att=27.61,
        pass_yds=218.44,
        pass_tds=1.57,
        pass_int=0.45,
        rush_att=8.87,
        rush_yds=40.93,
        rush_tds=0.83,
        rec_rec=0.0,
        rec_yds=0.0,
        rec_tds=0.0,
        fumbles=0.28,
        ret_tds=0,
        two_pt_tds=0,
    )

    # Test 1 — Jalen Hurts under CULV_SCORING
    result = score_raw(hurts_raw, CULV_SCORING)
    status = "PASS" if abs(result - 24.20) < 0.01 else "FAIL"
    print(f"Jalen Hurts: {result:.4f} pts (expected ~24.20) [{status}]")
    assert status == "PASS"

    # Test 2 — prove engine reads scoring, not hardcoded
    four_pt_base = ScoringSettings("half_ppr", 0.5, 4.0, 6.0, 6.0, 0.0, 0.0)
    four_pt_scoring = ExtendedScoringSettings(base=four_pt_base)
    result2 = score_raw(hurts_raw, four_pt_scoring)
    diff = result - result2
    status2 = "PASS" if abs(diff - 1.57) < 0.01 else "FAIL"
    print(f"4pt TD scoring: {result2:.4f} pts — diff={diff:.4f} (expected ~1.57) [{status2}]")
    assert status2 == "PASS"

    # Test 3 — to_player_proj round-trip
    pp = engine.to_player_proj(hurts_raw, 99)
    status3 = "PASS" if pp.player_id == 99 and pp.name == "Jalen Hurts" and abs(pp.projected_pts - 24.20) < 0.01 else "FAIL"
    print(f"to_player_proj: pid={pp.player_id} name={pp.name} pts={pp.projected_pts:.4f} [{status3}]")
    assert status3 == "PASS"

    print("\nAll acceptance tests passed.")
