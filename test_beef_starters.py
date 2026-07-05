"""
test_beef_starters.py — Integration tests for beef_starters capture and
per-bet kickoff lock wiring.

Five scenarios:
  1. issue_challenge writes beef_starters rows with correct team_id for both teams.
  2. respond_to_challenge blocks the accept when the per-bet lock returns
     True — no Bet rows created. (Lock return value is mocked so we can test
     independently of NFL schedule timing.)
  3. respond_to_challenge allows the accept when the per-bet lock returns
     False — Bet rows created as before.
  4. A challenge with a short roster (fewer than 9) writes fewer than 9
     beef_starters rows for that team and still accepts successfully.
  5. Frozen-snapshot bypass proof: after a player moves teams between issue
     and accept, the lock still fires based on the frozen beef_starters.team_id,
     NOT the live roster.

Uses a temp SQLite DB so prod is never touched. DATABASE_URL is set before
any project imports to guarantee all engines and sessions point at the temp DB.
"""

import os
import sys
import tempfile

# ── Must set DATABASE_URL before any project import touches db/schema.py ──────
_TMP_DIR = tempfile.mkdtemp()
_DB_PATH  = os.path.join(_TMP_DIR, "test_beef_starters.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone

from db.schema import (
    Base, engine, SessionLocal,
    BeefChallenge, BeefStarter, Bet,
    League, Matchup, NflSchedule, Player, Roster, Team, Wallet,
)
from beefs.beef_engine import issue_challenge, respond_to_challenge
import beefs.beef_engine as _beef_engine          # for monkey-patching
from betting.per_bet_lock import LOCK_SEASON, is_bet_locked_for_gm as _real_is_bet_locked_for_gm
from config import CURRENT_SEASON as SEASON

# ── Helpers ───────────────────────────────────────────────────────────────────

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


# ── DB bootstrap ──────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)

# All games are far in the future so:
#   • _nfl_lock_time() returns a future datetime → issue_challenge never
#     blocks during tests (real wall-clock is July 2026)
#   • The week-level kickoff check in respond_to_challenge never fires
#   • Per-bet lock (is_bet_locked_for_gm) would also return False for
#     real wall-clock time — Tests 2 and 5 mock the function to test lock paths.
FUTURE_KO = datetime(2026, 9, 14, 18, 0, 0)   # future relative to July 2026
# PAST_KO is genuinely in the past (January 2026) — used by Tests A/B to verify
# that real datetime comparison in is_bet_locked_for_gm returns True.
# NflSchedule.kickoff_utc = Column(DateTime) — naive datetime, no timezone info.
# SQLite raw-text queries return this as a string; our isinstance(str) fix converts
# it before comparison. PostgreSQL returns a naive datetime directly. Both end up
# as naive → replaced with UTC tzinfo before comparing against now_utc (always aware).
PAST_KO   = datetime(2026, 1,  1,  0,  0, 0)   # past relative to July 2026

with SessionLocal() as _db:
    league = League(season=SEASON, name="Test League", projection_source="fantasypros")
    _db.add(league)
    _db.flush()

    # ── Six teams ─────────────────────────────────────────────────────────────
    t1 = Team(league_id=league.id, team_name="Team Alpha", owner="Alice", email="alice@t.com")
    t2 = Team(league_id=league.id, team_name="Team Beta",  owner="Bob",   email="bob@t.com")
    t3 = Team(league_id=league.id, team_name="Team Short", owner="Carol", email="carol@t.com")
    t4 = Team(league_id=league.id, team_name="Team Other", owner="Dave",  email="dave@t.com")
    # t5/t6 used only by Test 5 (roster-move bypass proof)
    t5 = Team(league_id=league.id, team_name="Team Solo",  owner="Eve",   email="eve@t.com")
    t6 = Team(league_id=league.id, team_name="Team Rival", owner="Frank", email="frank@t.com")
    _db.add_all([t1, t2, t3, t4, t5, t6])
    _db.flush()

    # t1: 9 players on KC
    for i in range(9):
        p = Player(name=f"T1-P{i}", position="WR", nfl_team="KC")
        _db.add(p); _db.flush()
        _db.add(Roster(team_id=t1.id, player_id=p.id))

    # t2: 9 players on PHI
    for i in range(9):
        p = Player(name=f"T2-P{i}", position="WR", nfl_team="PHI")
        _db.add(p); _db.flush()
        _db.add(Roster(team_id=t2.id, player_id=p.id))

    # t3: 3 players on KC (short roster)
    for i in range(3):
        p = Player(name=f"T3-P{i}", position="RB", nfl_team="KC")
        _db.add(p); _db.flush()
        _db.add(Roster(team_id=t3.id, player_id=p.id))

    # t4: 9 players on PHI
    for i in range(9):
        p = Player(name=f"T4-P{i}", position="TE", nfl_team="PHI")
        _db.add(p); _db.flush()
        _db.add(Roster(team_id=t4.id, player_id=p.id))

    # t5: 8 players on NO + 1 player on LV (the one to be moved in Test 5).
    # After the move t5's live roster has 8 NO players (non-empty → odds engine happy).
    # The frozen beef_starters for t5 still records 1 LV row, proving the bypass.
    lv_player = Player(name="LV-Solo", position="RB", nfl_team="LV")
    _db.add(lv_player); _db.flush()
    _db.add(Roster(team_id=t5.id, player_id=lv_player.id))
    for i in range(8):
        p = Player(name=f"T5-P{i}", position="WR", nfl_team="NO")
        _db.add(p); _db.flush()
        _db.add(Roster(team_id=t5.id, player_id=p.id))

    # t6: 9 players on SF
    for i in range(9):
        p = Player(name=f"T6-P{i}", position="WR", nfl_team="SF")
        _db.add(p); _db.flush()
        _db.add(Roster(team_id=t6.id, player_id=p.id))

    for team in (t1, t2, t3, t4, t5, t6):
        _db.add(Wallet(team_id=team.id, balance=1000.0))

    # ── Matchups ──────────────────────────────────────────────────────────────
    _db.add(Matchup(league_id=league.id, week=1,
                    home_team_id=t1.id, away_team_id=t2.id,
                    home_score=0.0, away_score=0.0))
    _db.add(Matchup(league_id=league.id, week=2,
                    home_team_id=t3.id, away_team_id=t4.id,
                    home_score=0.0, away_score=0.0))
    _db.add(Matchup(league_id=league.id, week=3,
                    home_team_id=t5.id, away_team_id=t6.id,
                    home_score=0.0, away_score=0.0))
    # Weeks 4 & 5 — t1 vs t2 — used by Tests A and B
    _db.add(Matchup(league_id=league.id, week=4,
                    home_team_id=t1.id, away_team_id=t2.id,
                    home_score=0.0, away_score=0.0))
    _db.add(Matchup(league_id=league.id, week=5,
                    home_team_id=t1.id, away_team_id=t2.id,
                    home_score=0.0, away_score=0.0))

    # ── NflSchedule — all future so week-level lock never fires ───────────────
    _db.add(NflSchedule(season=LOCK_SEASON, week=1,
                        home_team="KC", away_team="PHI",
                        kickoff_utc=FUTURE_KO))
    _db.add(NflSchedule(season=LOCK_SEASON, week=2,
                        home_team="KC", away_team="PHI",
                        kickoff_utc=FUTURE_KO))
    _db.add(NflSchedule(season=LOCK_SEASON, week=3,
                        home_team="LV", away_team="SF",
                        kickoff_utc=FUTURE_KO))
    # Week 4: seeded FUTURE at setup time; moved to PAST in Test A after issue
    _db.add(NflSchedule(season=LOCK_SEASON, week=4,
                        home_team="KC", away_team="PHI",
                        kickoff_utc=FUTURE_KO))
    # Week 5: stays FUTURE throughout (Test B)
    _db.add(NflSchedule(season=LOCK_SEASON, week=5,
                        home_team="KC", away_team="PHI",
                        kickoff_utc=FUTURE_KO))

    _db.commit()
    t1_id, t2_id, t3_id, t4_id = t1.id, t2.id, t3.id, t4.id
    t5_id, t6_id                = t5.id, t6.id
    lv_player_id                = lv_player.id


# ── TEST 1: issue_challenge writes beef_starters with correct team_id ──────────

print("\nTest 1: issue_challenge writes beef_starters for both teams (with team_id)")
with SessionLocal() as db:
    out = issue_challenge(t1_id, t2_id, week=1, bet_type="straight", amount=10.0, db=db)
    cid1 = out.challenge_id

    rows = db.query(BeefStarter).filter(BeefStarter.beef_challenge_id == cid1).all()
    _assert("18 total beef_starters rows (9 per team)", len(rows) == 18, f"got {len(rows)}")

    t1_rows = [r for r in rows if r.team_id == t1_id]
    t2_rows = [r for r in rows if r.team_id == t2_id]
    _assert("9 rows with team_id=t1 (KC)",  len(t1_rows) == 9, f"got {len(t1_rows)}")
    _assert("9 rows with team_id=t2 (PHI)", len(t2_rows) == 9, f"got {len(t2_rows)}")
    _assert("all t1 rows have nfl_team=KC",  all(r.nfl_team == "KC"  for r in t1_rows))
    _assert("all t2 rows have nfl_team=PHI", all(r.nfl_team == "PHI" for r in t2_rows))
    _assert("all nfl_team values non-null",  all(r.nfl_team for r in rows))


# ── TEST 2: block accept when per-bet lock returns True ───────────────────────
# is_bet_locked_for_gm is mocked so the test is independent of schedule timing.

print("\nTest 2: respond_to_challenge blocks accept when per-bet lock returns True")

def _mock_always_locked(conn, teams, week, now_utc=None, *, season=LOCK_SEASON):
    return True

_original_lock_fn = _beef_engine.is_bet_locked_for_gm
_beef_engine.is_bet_locked_for_gm = _mock_always_locked

try:
    with SessionLocal() as db:
        out = issue_challenge(t1_id, t2_id, week=1, bet_type="straight", amount=10.0, db=db)
        cid2 = out.challenge_id

        raised    = False
        error_msg = ""
        try:
            respond_to_challenge(cid2, accept=True, db=db)
        except ValueError as e:
            raised    = True
            error_msg = str(e)

        _assert("accept raises ValueError",    raised,                    error_msg)
        _assert("error mentions 'kicked off'", "kicked off" in error_msg, error_msg)

        bet_count = db.query(Bet).filter(Bet.beef_challenge_id == cid2).count()
        _assert("no Bet rows created",         bet_count == 0,            f"got {bet_count}")
finally:
    _beef_engine.is_bet_locked_for_gm = _original_lock_fn


# ── TEST 3: allow accept when per-bet lock returns False ──────────────────────
# Real is_bet_locked_for_gm: wall-clock is July 2026, game is Sep 2026 → False.

print("\nTest 3: respond_to_challenge allows accept when per-bet lock returns False")
with SessionLocal() as db:
    out = issue_challenge(t1_id, t2_id, week=1, bet_type="straight", amount=10.0, db=db)
    cid3 = out.challenge_id

    raised = False
    result = None
    try:
        result = respond_to_challenge(cid3, accept=True, db=db)
    except Exception as e:
        raised = True
        print(f"    unexpected exception: {e}")

    _assert("accept does not raise", not raised)
    if not raised:
        bet_count = db.query(Bet).filter(Bet.beef_challenge_id == cid3).count()
        _assert("2 Bet rows created (one per side)", bet_count == 2,                   f"got {bet_count}")
        _assert("challenger_bet_id populated",       result.challenger_bet_id is not None)
        _assert("challenged_bet_id populated",       result.challenged_bet_id is not None)


# ── TEST 4: short roster → fewer beef_starters, accept still succeeds ─────────

print("\nTest 4: short roster (t3=3 players) → 3+9=12 beef_starters, accept succeeds")
with SessionLocal() as db:
    out = issue_challenge(t3_id, t4_id, week=2, bet_type="straight", amount=10.0, db=db)
    cid4 = out.challenge_id

    rows     = db.query(BeefStarter).filter(BeefStarter.beef_challenge_id == cid4).all()
    t3_rows  = [r for r in rows if r.team_id == t3_id]
    t4_rows  = [r for r in rows if r.team_id == t4_id]
    _assert("3 beef_starters for t3 (short roster, team_id)", len(t3_rows) == 3,  f"got {len(t3_rows)}")
    _assert("9 beef_starters for t4 (full roster, team_id)",  len(t4_rows) == 9,  f"got {len(t4_rows)}")
    _assert("total is 12 (3+9)",                              len(rows)    == 12, f"got {len(rows)}")

    raised = False
    result = None
    try:
        result = respond_to_challenge(cid4, accept=True, db=db)
    except Exception as e:
        raised = True
        print(f"    unexpected exception: {e}")

    _assert("short-roster accept does not raise",               not raised)
    if not raised:
        bet_count = db.query(Bet).filter(Bet.beef_challenge_id == cid4).count()
        _assert("2 Bet rows created for short-roster challenge", bet_count == 2, f"got {bet_count}")


# ── TEST 5: frozen-snapshot bypass proof ──────────────────────────────────────
# After issue, move the LV player from t5's roster to t6.
# The frozen beef_starters.team_id still points "LV" → t5.
# Mock returns True only when called with "LV".
# Proves the lock fires from the FROZEN snapshot, not the live roster.
# (Old code: ch_player_ids queries live roster → empty → ch_nfl_teams=[] → no lock.)
# (New code: team_id filter on frozen rows → ch_nfl_teams=["LV"] → locked.)

print("\nTest 5: frozen-snapshot bypass proof (roster move between issue and accept)")

with SessionLocal() as db:
    # Issue while LV player is still on t5's live roster
    out = issue_challenge(t5_id, t6_id, week=3, bet_type="straight", amount=10.0, db=db)
    cid5 = out.challenge_id

    # Verify beef_starters captured correctly at issue time
    rows    = db.query(BeefStarter).filter(BeefStarter.beef_challenge_id == cid5).all()
    t5_rows = [r for r in rows if r.team_id == t5_id]
    _assert("9 beef_starters rows for t5 (1 LV + 8 NO)", len(t5_rows) == 9, f"got {len(t5_rows)}")
    _assert("t5 frozen rows include nfl_team=LV",
            any(r.nfl_team == "LV" for r in t5_rows))

# Simulate a roster move: transfer LV player from t5 to t6 AFTER issue
with SessionLocal() as db:
    roster_row = (
        db.query(Roster)
        .filter(Roster.team_id == t5_id, Roster.player_id == lv_player_id)
        .one()
    )
    roster_row.team_id = t6_id
    db.commit()

# Mock: locked only when "LV" is in the teams list
def _mock_lv_locked(conn, teams, week, now_utc=None, *, season=LOCK_SEASON):
    return "LV" in teams

_beef_engine.is_bet_locked_for_gm = _mock_lv_locked
try:
    with SessionLocal() as db:
        raised    = False
        error_msg = ""
        try:
            respond_to_challenge(cid5, accept=True, db=db)
        except ValueError as e:
            raised    = True
            error_msg = str(e)

        _assert(
            "accept blocked via frozen snapshot after roster move",
            raised,
            error_msg or "no exception raised — live roster was used (bypass!)",
        )
        _assert("error mentions 'kicked off'", "kicked off" in error_msg, error_msg)

        bet_count = db.query(Bet).filter(Bet.beef_challenge_id == cid5).count()
        _assert("no Bet rows created",         bet_count == 0, f"got {bet_count}")
finally:
    _beef_engine.is_bet_locked_for_gm = _original_lock_fn


# ── TEST A: real is_bet_locked_for_gm decision — past kickoff ─────────────────
#
# Issue while kickoff is future, then move it to the past. No mock — the REAL
# function runs against real seeded data.
#
# SQLite / PostgreSQL datetime note
# ----------------------------------
# NflSchedule.kickoff_utc = Column(DateTime) — naive, no timezone.
# SQLite raw text() queries return it as a string (e.g. "2026-01-01 00:00:00").
# PostgreSQL returns a naive datetime object.
# is_bet_locked_for_gm handles both via: isinstance(str) → fromisoformat
# then tzinfo=None → replace(tzinfo=UTC) before comparing with now_utc (aware).
# The PAST_KO naive datetime inserted here exercises this exact code path in SQLite.
#
# Why the direct call + separate respond_to_challenge call
# ---------------------------------------------------------
# is_bet_locked_for_gm is tested directly to prove its DECISION from a real
# kickoff timestamp. When respond_to_challenge is called with the same past
# kickoff seeded, the WEEK-LEVEL lock in respond_to_challenge fires first
# (it calls _nfl_lock_time which returns MIN kickoff for the week = PAST_KO,
# then checks now >= PAST_KO → True). The per-bet lock is never reached through
# respond_to_challenge for a past kickoff because the week-level lock always fires
# first when MIN(kickoff for week) is in the past. The direct call below is the
# only way to exercise is_bet_locked_for_gm's datetime decision in this test suite.

print("\nTest A: real is_bet_locked_for_gm — past kickoff blocks accept")

with SessionLocal() as db:
    out = issue_challenge(t1_id, t2_id, week=4, bet_type="straight", amount=10.0, db=db)
    cid_a = out.challenge_id

# Move the week-4 kickoff into the past AFTER issue succeeds
with SessionLocal() as db:
    sched = (
        db.query(NflSchedule)
        .filter(NflSchedule.season == LOCK_SEASON, NflSchedule.week == 4)
        .one()
    )
    sched.kickoff_utc = PAST_KO
    db.commit()

# Step 1 — direct call: prove is_bet_locked_for_gm decides True from real data.
# Uses db.connection() matching what respond_to_challenge itself uses.
with SessionLocal() as db:
    raw_conn = db.connection()
    locked = _real_is_bet_locked_for_gm(raw_conn, ["KC"], week=4, season=LOCK_SEASON)
    _assert(
        "A1: is_bet_locked_for_gm(real fn) returns True for past kickoff",
        locked is True,
        f"got {locked!r}",
    )

# Step 2 — respond_to_challenge: system must block (week-level lock fires here,
# per-bet lock unreachable — see note above). Asserts "kickoff" (one word) which
# appears in the week-level message: "Week 4 locked at kickoff — …".
with SessionLocal() as db:
    raised    = False
    error_msg = ""
    try:
        respond_to_challenge(cid_a, accept=True, db=db)
    except ValueError as e:
        raised    = True
        error_msg = str(e)

    _assert("A2: respond_to_challenge raises when kickoff is past", raised)
    _assert("A2: error mentions 'kickoff'", "kickoff" in error_msg, error_msg)
    bet_count = db.query(Bet).filter(Bet.beef_challenge_id == cid_a).count()
    _assert("A2: no Bet rows created",      bet_count == 0, f"got {bet_count}")


# ── TEST B: real is_bet_locked_for_gm decision — future kickoff ───────────────
# Kickoff stays future throughout. Real function (no mock) returns False,
# respond_to_challenge allows the accept, 2 Bet rows created.

print("\nTest B: real is_bet_locked_for_gm — future kickoff allows accept")

with SessionLocal() as db:
    out = issue_challenge(t1_id, t2_id, week=5, bet_type="straight", amount=10.0, db=db)
    cid_b = out.challenge_id

# Step 1 — direct call: prove is_bet_locked_for_gm decides False for future game.
with SessionLocal() as db:
    raw_conn = db.connection()
    locked = _real_is_bet_locked_for_gm(raw_conn, ["KC"], week=5, season=LOCK_SEASON)
    _assert(
        "B1: is_bet_locked_for_gm(real fn) returns False for future kickoff",
        locked is False,
        f"got {locked!r}",
    )

# Step 2 — respond_to_challenge: no lock fires, accept succeeds.
with SessionLocal() as db:
    raised = False
    result = None
    try:
        result = respond_to_challenge(cid_b, accept=True, db=db)
    except Exception as e:
        raised = True
        print(f"    unexpected exception: {e}")

    _assert("B2: accept does not raise",         not raised)
    if not raised:
        bet_count = db.query(Bet).filter(Bet.beef_challenge_id == cid_b).count()
        _assert("B2: 2 Bet rows created",        bet_count == 2, f"got {bet_count}")
        _assert("B2: challenger_bet_id set",     result.challenger_bet_id is not None)
        _assert("B2: challenged_bet_id set",     result.challenged_bet_id is not None)


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
