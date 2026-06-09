from __future__ import annotations
import os, sys
from dataclasses import dataclass, field
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from connectors.fantasypros_connector import RawProj
from data.provider import PlayerProj, RosterState
from engine.projection_engine import ProjectionEngine, CULV_SCORING


# ── Move types ───────────────────────────────────────────────────────────────

@dataclass
class WaiverAdd:
    add_player:     RawProj
    drop_player_id: int

@dataclass
class Trade:
    give_player_ids:  list[int]
    receive_players:  list[RawProj]

@dataclass
class Hold:
    pass

Move = WaiverAdd | Trade | Hold


# ── Engine ───────────────────────────────────────────────────────────────────

class RosterStateEngine:
    """Applies a candidate move to a RosterState and returns the new state.

    The returned RosterState is a shallow copy with players modified.
    The original roster is never mutated.
    ProjectionEngine converts incoming RawProj players to PlayerProj.
    """

    def __init__(self, projection_engine: ProjectionEngine | None = None) -> None:
        self.proj_engine = projection_engine or ProjectionEngine(CULV_SCORING)

    def apply_move(
        self,
        roster: RosterState,
        move:   Move,
        next_player_id: int = 9000,
    ) -> RosterState:
        """Return a new RosterState with the move applied.

        next_player_id: base ID for incoming players (RawProj have no player_id).
        Each incoming player gets next_player_id + index as their player_id.
        """
        players = list(roster.players)  # shallow copy — never mutate original

        if isinstance(move, Hold):
            pass  # no changes

        elif isinstance(move, WaiverAdd):
            # Drop player
            players = [p for p in players if p.player_id != move.drop_player_id]
            if len(players) == len(roster.players):
                raise ValueError(
                    f"drop_player_id {move.drop_player_id} not found in roster"
                )
            # Add player
            new_player = self.proj_engine.to_player_proj(
                move.add_player, player_id=next_player_id
            )
            players.append(new_player)

        elif isinstance(move, Trade):
            # Remove given players
            give_ids = set(move.give_player_ids)
            players = [p for p in players if p.player_id not in give_ids]
            missing = give_ids - {p.player_id for p in roster.players}
            if missing:
                raise ValueError(f"give_player_ids not found in roster: {missing}")
            # Add received players
            for i, raw in enumerate(move.receive_players):
                new_player = self.proj_engine.to_player_proj(
                    raw, player_id=next_player_id + i
                )
                players.append(new_player)

        return RosterState(
            team_id   = roster.team_id,
            team_name = roster.team_name,
            week      = roster.week,
            players   = players,
        )


# ── Acceptance test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    from data.provider import MockProvider

    provider = MockProvider()
    roster   = provider.get_roster(1, 1)
    engine   = RosterStateEngine()

    print(f"Original roster: {len(roster.players)} players")
    original_ids = {p.player_id for p in roster.players}

    # --- Test 1: Hold ---
    held = engine.apply_move(roster, Hold())
    assert len(held.players) == len(roster.players), "Hold must not change roster size"
    assert {p.player_id for p in held.players} == original_ids, "Hold must not change players"
    print("  [PASS] Hold — roster unchanged")

    # --- Test 2: WaiverAdd ---
    drop_id    = roster.players[0].player_id
    drop_name  = roster.players[0].name
    add_raw    = RawProj(
        fpid="test_001", yahoo_player_id=None,
        name="Free Agent WR", position="WR", team="KC", bye_week=6,
        pass_att=0, pass_yds=0, pass_tds=0, pass_int=0,
        rush_att=2, rush_yds=15, rush_tds=0,
        rec_rec=5, rec_yds=62, rec_tds=0.4,
        fumbles=0, ret_tds=0, two_pt_tds=0,
    )
    new_roster = engine.apply_move(roster, WaiverAdd(add_player=add_raw, drop_player_id=drop_id))
    assert len(new_roster.players) == len(roster.players), "WaiverAdd must keep roster size"
    assert drop_id not in {p.player_id for p in new_roster.players}, "Dropped player must be gone"
    assert any(p.name == "Free Agent WR" for p in new_roster.players), "Added player must appear"
    assert new_roster is not roster, "Must return new RosterState, not mutate original"
    assert len(roster.players) == len(original_ids), "Original roster must be unchanged"
    print(f"  [PASS] WaiverAdd — dropped '{drop_name}', added 'Free Agent WR'")

    # --- Test 3: Trade ---
    give_ids = [roster.players[1].player_id, roster.players[2].player_id]
    give_names = [p.name for p in roster.players if p.player_id in set(give_ids)]
    receive_raws = [
        RawProj(
            fpid="trade_001", yahoo_player_id=None,
            name="Trade Acquire RB", position="RB", team="SF", bye_week=9,
            pass_att=0, pass_yds=0, pass_tds=0, pass_int=0,
            rush_att=18, rush_yds=88, rush_tds=0.7,
            rec_rec=3, rec_yds=22, rec_tds=0.1,
            fumbles=0.1, ret_tds=0, two_pt_tds=0,
        ),
    ]
    trade_roster = engine.apply_move(
        roster,
        Trade(give_player_ids=give_ids, receive_players=receive_raws)
    )
    assert len(trade_roster.players) == len(roster.players) - 1, \
        f"Trade gave 2, received 1 — roster should shrink by 1"
    for gid in give_ids:
        assert gid not in {p.player_id for p in trade_roster.players}, \
            f"Given player {gid} must be gone"
    assert any(p.name == "Trade Acquire RB" for p in trade_roster.players), \
        "Received player must appear"
    print(f"  [PASS] Trade — gave {give_names}, received 'Trade Acquire RB'")

    # --- Test 4: invalid drop_player_id raises ---
    try:
        engine.apply_move(roster, WaiverAdd(add_player=add_raw, drop_player_id=99999))
        assert False, "Should have raised ValueError"
    except ValueError:
        print("  [PASS] Invalid drop_player_id raises ValueError")

    # --- Test 5: invalid give_player_ids raises ---
    try:
        engine.apply_move(roster, Trade(give_player_ids=[99999], receive_players=[]))
        assert False, "Should have raised ValueError"
    except ValueError:
        print("  [PASS] Invalid give_player_ids raises ValueError")

    print("\nAll acceptance tests passed.")
