"""
test_roster_slots_capture.py — FR-5.7 roster-slot capture + week-aware reads.

Fixtures are deliberately built so the BUG and the FIX diverge — a fixture
where Roster and RosterSlot agree would prove nothing.

Scenarios:
  1. Week-divergence   — RosterSlot for week N contradicts the current Roster.
                         _starters_for_team(week=N) must read week-N slots.
  2. Fallback          — no RosterSlot rows for a week → falls back to Roster,
                         settlement read still completes.
  3. Idempotency       — capture re-run for an already-captured week → no new
                         rows, no error, no mutation.
  4. 2c divergence     — a roster whose insertion order and true starter/bench
                         split DISAGREE. The old [:9] slice and the slot filter
                         return different answers; _player_actual must return the
                         slot-based one.
  5. Team-ID bridge    — Yahoo IDs → DB IDs via build_team_resolver(), with a
                         scrambled, non-affine mapping so +10 arithmetic would
                         route rosters to the WRONG team.
  6. Fail-safe capture — an unresolved player aborts the capture with nothing
                         written (settlement then falls back to Roster).

Uses a temp SQLite DB so prod is never touched. DATABASE_URL is set before any
project import so every engine/session points at the temp DB. The Yahoo API is
never called — _build_yahoo_query is monkey-patched to a fake.
"""

import os
import sys
import tempfile

# ── Must set DATABASE_URL before any project import touches db/schema.py ──────
_TMP_DIR  = tempfile.mkdtemp()
_DB_PATH  = os.path.join(_TMP_DIR, "test_roster_slots_capture.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.schema import (
    Base, engine, SessionLocal,
    League, Player, Projection, Roster, RosterSlot, Team,
)
from db.roster_read import _roster_for_week
from betting.settlement_engine import _starters_for_team
from betting.pool_engine import _special_teams_score
from reports.weekly_wrap import _player_actual
import notifications.tuesday_sync as tsync
from notifications.tuesday_sync import _step_capture_roster_slots
from config import CURRENT_SEASON as SEASON

# ── Assert harness ────────────────────────────────────────────────────────────

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


# ── Fake Yahoo layer (never hits the network) ─────────────────────────────────

class _FakeSelPos:
    def __init__(self, position: str) -> None:
        self.position = position


class _FakePlayer:
    def __init__(self, full_name: str, slot: str) -> None:
        self.full_name = full_name
        self.selected_position = _FakeSelPos(slot)


class _FakeRoster:
    def __init__(self, players: list[_FakePlayer]) -> None:
        self.players = players


class _FakeQuery:
    """Returns a canned roster per Yahoo team ID; records every call so the
    test can prove which Yahoo ID was fetched for each DB team."""
    def __init__(self, by_yahoo: dict[int, list[tuple[str, str]]]) -> None:
        self._by = by_yahoo
        self.calls: list[tuple[int, int]] = []

    def get_team_roster_by_week(self, team_id, chosen_week="current"):
        self.calls.append((team_id, chosen_week))
        entries = self._by.get(team_id, [])
        return _FakeRoster([_FakePlayer(n, s) for n, s in entries])


def _install_fake(by_yahoo: dict[int, list[tuple[str, str]]]) -> _FakeQuery:
    fake = _FakeQuery(by_yahoo)
    tsync._build_yahoo_query = lambda *_a, **_k: fake      # monkey-patch
    return fake


def _email(yahoo_id: int) -> str:
    return f"yahoo-team-{yahoo_id}@fantasy-beefs.local"


# ── DB bootstrap ──────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)

with SessionLocal() as _db:
    # Three leagues: L0 fillers (consume ids 1-10 so capture ids land at 11+),
    # L1 capture teams (scrambled Yahoo mapping), L2 settlement/helper teams.
    l0 = League(season=SEASON, name="Filler",     projection_source="fantasypros")
    l1 = League(season=SEASON, name="Capture",    projection_source="fantasypros")
    l2 = League(season=SEASON, name="Settlement", projection_source="fantasypros")
    _db.add_all([l0, l1, l2]); _db.flush()

    # 10 filler teams in L0 → team ids 1..10
    for i in range(1, 11):
        _db.add(Team(league_id=l0.id, team_name=f"Filler {i}",
                     owner=f"F{i}", email=f"filler{i}@t.com"))
    _db.flush()

    # L1 capture teams inserted in SCRAMBLED Yahoo order so DB id != Yahoo+K.
    # Insertion order (Yahoo 3, 1, 2) → DB ids 11, 12, 13.
    #   Yahoo 3 -> DB 11 | Yahoo 1 -> DB 12 | Yahoo 2 -> DB 13
    # +10 arithmetic would say Yahoo 1 -> DB 11, which is WRONG here.
    cap_y3 = Team(league_id=l1.id, team_name="Cap Y3", owner="c3", email=_email(3))
    cap_y1 = Team(league_id=l1.id, team_name="Cap Y1", owner="c1", email=_email(1))
    cap_y2 = Team(league_id=l1.id, team_name="Cap Y2", owner="c2", email=_email(2))
    _db.add_all([cap_y3, cap_y1, cap_y2]); _db.flush()

    # Players the fake rosters reference (name-matched, lowercased).
    cap_player_names = [
        "Alpha One", "Alpha Bench",
        "Bravo One", "Bravo Bench",
        "Charlie One", "Charlie Flex",
    ]
    for nm in cap_player_names:
        _db.add(Player(name=nm, position="WR"))
    _db.flush()

    # L2 settlement/helper teams (Yahoo 4,5 — so the L1 resolver is unaffected).
    t_div = Team(league_id=l2.id, team_name="Divergence", owner="d", email=_email(4))
    t_pa  = Team(league_id=l2.id, team_name="PlayerActual", owner="p", email=_email(5))
    _db.add_all([t_div, t_pa]); _db.flush()

    # Players for test 1/2 (X, Y) and test 4 (A1..A10)
    px = Player(name="Div X", position="WR")
    py = Player(name="Div Y", position="WR")
    _db.add_all([px, py]); _db.flush()

    a_players = []
    for i in range(1, 11):
        p = Player(name=f"PA {i}", position="WR")
        _db.add(p); a_players.append(p)
    _db.flush()

    # ── Static Roster for the divergence team ────────────────────────────────
    # Current/static: X starts (WR), Y benched (BN).
    _db.add(Roster(team_id=t_div.id, player_id=px.id, slot="WR"))
    _db.add(Roster(team_id=t_div.id, player_id=py.id, slot="BN"))

    # ── Week-5 RosterSlot for the divergence team — CONTRADICTS the static ───
    # Week 5: X benched (BN), Y starts (WR). Opposite of the static Roster.
    DIV_WEEK = 5
    _db.add(RosterSlot(league_id=l2.id, team_id=t_div.id, player_id=px.id,
                       week=DIV_WEEK, slot="BN"))
    _db.add(RosterSlot(league_id=l2.id, team_id=t_div.id, player_id=py.id,
                       week=DIV_WEEK, slot="WR"))

    # ── Test 4 fixture: insertion order vs slot split DISAGREE ────────────────
    # RosterSlot ids ascend A1..A10. A9 is BN but sits within the first 9 (the
    # old [:9] slice would call it a starter). A10 is a starter slot but sits
    # 10th (the old slice would call it bench). Projections isolate the effect:
    #   A1..A8 = 0, A9 (BN) = 100, A10 (WR) = 1
    #   slot-based:   starter_pts = 1  bench_pts = 100
    #   positional:   starter_pts = 100 bench_pts = 1   (the bug)
    PA_WEEK = 7
    for i, p in enumerate(a_players, start=1):
        if i <= 8:
            slot, actual = "WR", 0.0
        elif i == 9:
            slot, actual = "BN", 100.0
        else:  # i == 10
            slot, actual = "WR", 1.0
        _db.add(RosterSlot(league_id=l2.id, team_id=t_pa.id, player_id=p.id,
                           week=PA_WEEK, slot=slot))
        _db.add(Projection(player_id=p.id, week=PA_WEEK, season=SEASON,
                           source="fantasypros", actual_points=actual))

    # ── Pool Special Teams divergence fixture ────────────────────────────────
    # Team whose CURRENT Roster kicker (K_old) differs from the WEEK-N RosterSlot
    # kicker (K_new). _special_teams_score(week=N) must score K_new, not K_old.
    # Projections (fantasypros, per pool_engine): K_old=50, K_new=9, DEF=7.
    #   week-N (slot-based):  K_new + DEF = 9 + 7 = 16
    #   current Roster (bug): K_old + DEF = 50 + 7 = 57
    t_st = Team(league_id=l2.id, team_name="SpecialTeams", owner="s", email=_email(6))
    _db.add(t_st); _db.flush()
    k_old = Player(name="Kicker Old", position="K")
    k_new = Player(name="Kicker New", position="K")
    st_def = Player(name="Defense ST", position="DEF")
    _db.add_all([k_old, k_new, st_def]); _db.flush()

    ST_WEEK = 6
    # Current/static Roster: K_old is the kicker, plus the DEF.
    _db.add(Roster(team_id=t_st.id, player_id=k_old.id,  slot="K"))
    _db.add(Roster(team_id=t_st.id, player_id=st_def.id, slot="DEF"))
    # Week-6 RosterSlot: K_new is the kicker instead — diverges from current.
    _db.add(RosterSlot(league_id=l2.id, team_id=t_st.id, player_id=k_new.id,
                       week=ST_WEEK, slot="K"))
    _db.add(RosterSlot(league_id=l2.id, team_id=t_st.id, player_id=st_def.id,
                       week=ST_WEEK, slot="DEF"))
    for pl, pts in ((k_old, 50.0), (k_new, 9.0), (st_def, 7.0)):
        _db.add(Projection(player_id=pl.id, week=ST_WEEK, season=SEASON,
                           source="fantasypros", actual_points=pts))
    # Fallback week 12: no RosterSlot rows → _special_teams_score must read the
    # static Roster (K_old + DEF). K_old=50, DEF=7 → 57. K_new isn't on the
    # static Roster, so a correct fallback can only score K_old.
    ST_FALLBACK_WEEK = 12
    for pl, pts in ((k_old, 50.0), (k_new, 9.0), (st_def, 7.0)):
        _db.add(Projection(player_id=pl.id, week=ST_FALLBACK_WEEK, season=SEASON,
                           source="fantasypros", actual_points=pts))

    _db.commit()

    # Capture ids for later assertions
    l1_id   = l1.id
    l2_id   = l2.id
    db_y1   = cap_y1.id     # 12
    db_y2   = cap_y2.id     # 13
    db_y3   = cap_y3.id     # 11
    tdiv_id = t_div.id
    tpa_id  = t_pa.id
    tst_id  = t_st.id
    px_id, py_id = px.id, py.id


# ── TEST 1: week-divergence — settlement reads week-N slots, not current Roster ─

print("\nTest 1: week-divergence — _starters_for_team reads week-N RosterSlot")
with SessionLocal() as db:
    starters = _starters_for_team(tdiv_id, DIV_WEEK, db)
    ids = {s.player_id for s in starters}
    _assert("week-5 starters = {Y} (slot-based), not {X} (static Roster)",
            ids == {py_id}, f"got {ids} (X={px_id}, Y={py_id})")
    _assert("benched X is excluded from week-5 starters", px_id not in ids)


# ── TEST 2: fallback — no slots for the week → static Roster ───────────────────

print("\nTest 2: fallback — a week with no RosterSlot rows falls back to Roster")
with SessionLocal() as db:
    NO_SLOT_WEEK = 9  # divergence team has no RosterSlot rows for week 9
    rows = _roster_for_week(tdiv_id, NO_SLOT_WEEK, db)
    ids  = {r.player_id for r in rows}
    _assert("fallback returns the static Roster (both X and Y present)",
            ids == {px_id, py_id}, f"got {ids}")

    starters = _starters_for_team(tdiv_id, NO_SLOT_WEEK, db)
    sids = {s.player_id for s in starters}
    _assert("fallback starters = {X} (static: X=WR, Y=BN)",
            sids == {px_id}, f"got {sids}")


# ── TEST 4: 2c divergence — _player_actual uses the slot split, not [:9] ───────

print("\nTest 4: 2c — _player_actual splits by slot, not by insertion order")
with SessionLocal() as db:
    starter_pts, bench_pts, best = _player_actual(tpa_id, PA_WEEK, db)
    _assert("starter_pts = 1.0 (slot-based; excludes the early BN=100)",
            starter_pts == 1.0, f"got {starter_pts}")
    _assert("bench_pts = 100.0 (the early-but-benched A9)",
            bench_pts == 100.0, f"got {bench_pts}")
    _assert("NOT the positional-slice answer (starter=100, bench=1)",
            not (starter_pts == 100.0 and bench_pts == 1.0),
            f"starter={starter_pts} bench={bench_pts}")
    _assert("best_possible unchanged = 101.0 (top-9 of all)",
            best == 101.0, f"got {best}")


# ── TEST 5: capture + team-ID bridge (scrambled, non-affine mapping) ──────────

print("\nTest 5: capture writes rows and bridges Yahoo->DB via resolver (not +10)")
CAP_WEEK = 1
fake = _install_fake({
    1: [("Alpha One", "QB"),  ("Alpha Bench", "BN")],
    2: [("Bravo One", "RB"),  ("Bravo Bench", "IR")],
    3: [("Charlie One", "WR"), ("Charlie Flex", "W/R/T")],
})
with SessionLocal() as db:
    res = _step_capture_roster_slots(l1_id, CAP_WEEK, db)
    _assert("capture step succeeds", res.success, res.message)
    _assert("6 rows written", res.data.get("rows_written") == 6,
            f"got {res.data.get('rows_written')}")

    # Fetched by Yahoo ID (1,2,3), week 1 — never by DB id.
    fetched = {c[0] for c in fake.calls}
    _assert("fetched Yahoo IDs {1,2,3}", fetched == {1, 2, 3}, f"got {fetched}")
    _assert("every fetch used chosen_week=1",
            all(c[1] == 1 for c in fake.calls), f"got {fake.calls}")

    # Yahoo 1's roster must land under DB 12 (resolver), NOT DB 11 (+10).
    y1_rows = (db.query(RosterSlot)
                 .filter(RosterSlot.team_id == db_y1, RosterSlot.week == CAP_WEEK)
                 .all())
    y1_names = {db.get(Player, r.player_id).name: r.slot for r in y1_rows}
    _assert("Yahoo-1 roster routed to DB team 12 (resolver, not +10 -> 11)",
            y1_names == {"Alpha One": "QB", "Alpha Bench": "BN"},
            f"got {y1_names} on team {db_y1}")

    # Confirm +10 target (DB 11) holds Yahoo-3's roster, not Yahoo-1's.
    y3_rows = (db.query(RosterSlot)
                 .filter(RosterSlot.team_id == db_y3, RosterSlot.week == CAP_WEEK)
                 .all())
    y3_names = {db.get(Player, r.player_id).name for r in y3_rows}
    _assert("DB team 11 holds Yahoo-3's roster (proves no +10 reliance)",
            y3_names == {"Charlie One", "Charlie Flex"},
            f"got {y3_names} on team {db_y3}")

    # Slot label is selected_position.position verbatim (IR, W/R/T survive).
    y2_rows = (db.query(RosterSlot)
                 .filter(RosterSlot.team_id == db_y2, RosterSlot.week == CAP_WEEK)
                 .all())
    y2_slots = {db.get(Player, r.player_id).name: r.slot for r in y2_rows}
    _assert("slots captured verbatim from selected_position (IR preserved)",
            y2_slots == {"Bravo One": "RB", "Bravo Bench": "IR"}, f"got {y2_slots}")


# ── TEST 3: idempotency — re-run an already-captured week is a no-op ───────────

print("\nTest 3: idempotency — re-running capture for a captured week writes nothing")
with SessionLocal() as db:
    before = (db.query(RosterSlot)
                .filter(RosterSlot.league_id == l1_id, RosterSlot.week == CAP_WEEK)
                .count())
    res = _step_capture_roster_slots(l1_id, CAP_WEEK, db)
    after = (db.query(RosterSlot)
               .filter(RosterSlot.league_id == l1_id, RosterSlot.week == CAP_WEEK)
               .count())
    _assert("re-run succeeds (no error)", res.success, res.message)
    _assert("re-run reports idempotent no-op",
            res.data.get("idempotent_noop") is True, f"got {res.data}")
    _assert("row count unchanged (6 -> 6)", before == after == 6,
            f"before={before} after={after}")


# ── TEST 6: fail-safe — an unresolved player aborts with nothing written ──────

print("\nTest 6: fail-safe — unresolved player fails capture, writes nothing")
UNRES_WEEK = 2
_install_fake({
    1: [("Alpha One", "QB"), ("Ghost Player", "BN")],   # Ghost Player not in DB
    2: [("Bravo One", "RB")],
    3: [("Charlie One", "WR")],
})
with SessionLocal() as db:
    res = _step_capture_roster_slots(l1_id, UNRES_WEEK, db)
    _assert("capture fails on unresolved player", not res.success, res.message)
    _assert("failure names the unresolved player",
            "Ghost Player" in (res.error or ""), res.error or "")
    written = (db.query(RosterSlot)
                 .filter(RosterSlot.league_id == l1_id, RosterSlot.week == UNRES_WEEK)
                 .count())
    _assert("nothing written for the failed week (all-or-nothing)",
            written == 0, f"got {written}")


# ── TEST 7: pool Special Teams reads the week's kicker, not the current one ───

print("\nTest 7: pool _special_teams_score reads week-N RosterSlot kicker, not current Roster")
with SessionLocal() as db:
    st = _special_teams_score(tst_id, ST_WEEK, db)
    _assert("week-6 ST score = 16.0 (K_new 9 + DEF 7), slot-based",
            st == 16.0, f"got {st}")
    _assert("NOT the current-Roster answer 57.0 (K_old 50 + DEF 7)",
            st != 57.0, f"got {st}")

    # Week 12 has no RosterSlot rows → falls back to the static Roster, which
    # holds K_old (not K_new). Correct fallback scores K_old(50) + DEF(7) = 57.
    st_fb = _special_teams_score(tst_id, ST_FALLBACK_WEEK, db)
    _assert("fallback week (no slots) scores static-Roster K_old = 57.0",
            st_fb == 57.0, f"got {st_fb}")


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*54}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
