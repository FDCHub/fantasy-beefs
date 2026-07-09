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
from betting.per_bet_lock import (
    LOCK_SEASON,
    LockCheck,
    is_bet_locked_for_gm as _real_is_bet_locked_for_gm,
    _is_real_kickoff,
    _is_placeholder_week,
)
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

    # ── Teams 7-10 — week 13 fixture for schedule_not_ready / data_gap tests ──
    # t7: TB (placeholder-only in week 13, 2026-12-20 06:00Z)
    # t8: DAL (real, confirmed kickoff in week 13 — keeps issue_challenge's own
    #     week-level check passing, since _nfl_lock_time finds DAL's real row
    #     as the week's overall earliest — see the week-13 NflSchedule setup)
    # t9: ZZZ (unmapped team code — appears nowhere in nfl_schedule at all)
    # t10: dummy opponent, only exists so t9 has its own week-10 matchup
    t7  = Team(league_id=league.id, team_name="Team TB",  owner="Gina",  email="gina@t.com")
    t8  = Team(league_id=league.id, team_name="Team DAL", owner="Hank",  email="hank@t.com")
    t9  = Team(league_id=league.id, team_name="Team ZZZ", owner="Ivy",   email="ivy@t.com")
    t10 = Team(league_id=league.id, team_name="Team Dummy", owner="Jack", email="jack@t.com")
    _db.add_all([t7, t8, t9, t10])
    _db.flush()

    for i in range(9):
        p = Player(name=f"T7-P{i}", position="WR", nfl_team="TB")
        _db.add(p); _db.flush()
        _db.add(Roster(team_id=t7.id, player_id=p.id))
    for i in range(9):
        p = Player(name=f"T8-P{i}", position="WR", nfl_team="DAL")
        _db.add(p); _db.flush()
        _db.add(Roster(team_id=t8.id, player_id=p.id))
    for i in range(9):
        p = Player(name=f"T9-P{i}", position="WR", nfl_team="ZZZ")
        _db.add(p); _db.flush()
        _db.add(Roster(team_id=t9.id, player_id=p.id))
    for i in range(9):
        p = Player(name=f"T10-P{i}", position="WR", nfl_team="SEA")
        _db.add(p); _db.flush()
        _db.add(Roster(team_id=t10.id, player_id=p.id))

    for team in (t1, t2, t3, t4, t5, t6, t7, t8, t9, t10):
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
    # Week 13 — t7/t8 share a matchup, t9/t10 share a matchup (each team needs
    # its own week-13 matchup for issue_challenge's _find_own_matchup lookup)
    _db.add(Matchup(league_id=league.id, week=13,
                    home_team_id=t7.id, away_team_id=t8.id,
                    home_score=0.0, away_score=0.0))
    _db.add(Matchup(league_id=league.id, week=13,
                    home_team_id=t9.id, away_team_id=t10.id,
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
    # Week 13 — used by Tests C/D (through issue_challenge/respond_to_challenge).
    # DAL's real row (Dec 18) sorts BEFORE TB's placeholder (Dec 20) overall,
    # so _nfl_lock_time's own whole-week MIN (fixed earlier this session, but
    # only band-filters the aggregate MIN, not per-team like is_bet_locked_
    # for_gm does) finds DAL's real row as week 13's earliest and does not
    # raise ScheduleNotReadyError — issue_challenge's week-level gate passes.
    # TB's per-bet lock is still independently placeholder-only when queried
    # for TB specifically, which is what Tests C/D exercise.
    PLACEHOLDER_KO   = datetime(2026, 12, 20, 6, 0, 0)
    REAL_KO_W13      = datetime(2026, 12, 18, 18, 0, 0)
    _db.add(NflSchedule(season=LOCK_SEASON, week=13,
                        home_team="DAL", away_team="NYG",
                        kickoff_utc=REAL_KO_W13))
    _db.add(NflSchedule(season=LOCK_SEASON, week=13,
                        home_team="TB", away_team="ATL",
                        kickoff_utc=PLACEHOLDER_KO))
    # Week 14 — used ONLY by Test E (direct is_bet_locked_for_gm call, never
    # through issue_challenge/respond_to_challenge, so _nfl_lock_time's own
    # week-level gate is never invoked for this data). Same calendar day:
    # TB's placeholder (06:00) sorts BEFORE DAL's real kickoff (18:00) under
    # a raw, unfiltered MIN() — the exact trap this whole fix closes.
    REAL_KO_W14 = datetime(2026, 12, 20, 18, 0, 0)
    _db.add(NflSchedule(season=LOCK_SEASON, week=14,
                        home_team="TB", away_team="ATL",
                        kickoff_utc=PLACEHOLDER_KO))
    _db.add(NflSchedule(season=LOCK_SEASON, week=14,
                        home_team="DAL", away_team="NYG",
                        kickoff_utc=REAL_KO_W14))
    # Week 11 — YYY's ONLY appearance all season is this placeholder row.
    # Used by the bye-detection-fix test: querying YYY for a DIFFERENT week
    # (12, zero rows) must return data_gap, not a true bye, since YYY has no
    # real (non-placeholder) row anywhere in the season.
    _db.add(NflSchedule(season=LOCK_SEASON, week=11,
                        home_team="YYY", away_team="XXX",
                        kickoff_utc=PLACEHOLDER_KO))
    # Week 15 — exactly ONE game row. Used by the one-game-week guard test
    # (_is_placeholder_week must return False here — a single loaded game
    # trivially has one distinct timestamp and must not be misread as a
    # whole-week placeholder).
    _db.add(NflSchedule(season=LOCK_SEASON, week=15,
                        home_team="SSS", away_team="RRR",
                        kickoff_utc=REAL_KO_W14))
    # Week 17 — THREE rows sharing one IDENTICAL timestamp whose HOUR happens
    # to fall INSIDE the band's accepted range (18:00, same hour as
    # REAL_KO_W14/W13) — a genuine whole-week placeholder week under CR-1's
    # revised threshold (MORE THAN TWO rows sharing one stamp, not more than
    # one — a real week can coincidentally have exactly two games at the
    # same kickoff slot, so >2 is required to still read as a placeholder
    # week) despite passing _is_real_kickoff() individually. WWW's only
    # season appearance is here. Used by the Fix 2 bye-path integration
    # test: querying WWW for a different week (18, zero rows) must still
    # return data_gap, not a false "true bye" — proving has_real_row now
    # requires BOTH _is_real_kickoff() AND not _is_placeholder_week(), not
    # _is_real_kickoff() alone.
    INBAND_PLACEHOLDER_KO = datetime(2026, 12, 21, 18, 0, 0)
    _db.add(NflSchedule(season=LOCK_SEASON, week=17,
                        home_team="WWW", away_team="VVV",
                        kickoff_utc=INBAND_PLACEHOLDER_KO))
    _db.add(NflSchedule(season=LOCK_SEASON, week=17,
                        home_team="UUU3", away_team="TTT3",
                        kickoff_utc=INBAND_PLACEHOLDER_KO))
    _db.add(NflSchedule(season=LOCK_SEASON, week=17,
                        home_team="UUU4", away_team="TTT4",
                        kickoff_utc=INBAND_PLACEHOLDER_KO))

    _db.commit()
    t1_id, t2_id, t3_id, t4_id   = t1.id, t2.id, t3.id, t4.id
    t5_id, t6_id                 = t5.id, t6.id
    t7_id, t8_id, t9_id, t10_id  = t7.id, t8.id, t9.id, t10.id
    lv_player_id                 = lv_player.id

# Session L3: _place_beef_side() now posts through the ledger (wager_placed,
# door-guarded by MS-L1-5.1) instead of mutating Wallet.balance directly. No
# code path anywhere in this repo funds a team's wallet:{team_id} ledger
# account yet — Wallet rows are still seeded directly, as above, exactly like
# production. Without a matching ledger credit, every accept below would now
# raise InsufficientFundsError for every team. This posting is a TEST-ONLY
# stand-in for funding that nothing in production actually performs yet —
# it makes this suite exercise the conversion correctly, but does not fix
# the real gap: a real accepted beef in production would still fail until
# something (deposit()/buy-in flow) credits wallet:{team_id} in the ledger.
from ledger.ledger import create_ledger_table, post as _ledger_seed_post
create_ledger_table()
for _tid in (t1_id, t2_id, t3_id, t4_id, t5_id, t6_id, t7_id, t8_id, t9_id, t10_id):
    _ledger_seed_post(
        [("world", -100_000_00), (f"wallet:{_tid}", 100_000_00)],
        door="buy_in_paid",
    )


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
    return LockCheck(locked=True, reason="in_progress")

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
    return LockCheck(locked=("LV" in teams), reason="in_progress" if "LV" in teams else None)

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
        locked.locked is True,
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
        locked.locked is False,
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


# ── TEST C: schedule_not_ready message via respond_to_challenge ───────────────
# t7 (TB, placeholder-only in week 13) vs t8 (DAL, real confirmed kickoff).
# issue_challenge's own week-level lock passes (DAL's real row, 2026-12-18,
# sorts before TB's placeholder, 2026-12-20, so _nfl_lock_time's whole-week
# MIN finds DAL's real row as week 13's earliest). The per-bet lock for TB
# specifically must independently come back schedule_not_ready, and respond_
# to_challenge must raise the split "hasn't posted an official kickoff time"
# message — not the generic "kicked off" message from Tests 2/5/A.

print("\nTest C: respond_to_challenge — schedule_not_ready message (real function, no mock)")
with SessionLocal() as db:
    out = issue_challenge(t7_id, t8_id, week=13, bet_type="straight", amount=10.0, db=db)
    cid_c = out.challenge_id

    raised    = False
    error_msg = ""
    try:
        respond_to_challenge(cid_c, accept=True, db=db)
    except ValueError as e:
        raised    = True
        error_msg = str(e)

    _assert("C: accept raises ValueError",                       raised, error_msg)
    _assert("C: message mentions 'hasn't posted an official kickoff time'",
            "hasn't posted an official kickoff time" in error_msg, error_msg)
    _assert("C: message does NOT use the generic 'kicked off' wording",
            "kicked off" not in error_msg, error_msg)
    # Fix 6 (MS-PBL-5): explicitly confirm this came from the PER-BET lock
    # layer, not respond_to_challenge's own week-level _nfl_lock_time gate —
    # that gate's own ScheduleNotReadyError message reads "this challenge
    # can't be accepted or declined until it is". Without this check, a
    # future change to the week-level gate could make this test pass for
    # the wrong reason (week-level firing first) without anyone noticing.
    _assert("C: message is NOT the week-level _nfl_lock_time gate's wording",
            "can't be accepted or declined until it is" not in error_msg, error_msg)

    bet_count = db.query(Bet).filter(Bet.beef_challenge_id == cid_c).count()
    _assert("C: no Bet rows created", bet_count == 0, f"got {bet_count}")


# ── TEST D: data_gap message via respond_to_challenge ─────────────────────────
# t9 (ZZZ, unmapped team code — zero rows anywhere in nfl_schedule) vs t8
# (DAL, real). Week-level lock still passes via DAL's real row. The per-bet
# lock for ZZZ must come back data_gap, and respond_to_challenge must raise
# the "missing schedule data ... contact the commissioner" message — distinct
# from Test C's schedule_not_ready wording.

print("\nTest D: respond_to_challenge — data_gap message via respond_to_challenge (real function, no mock)")
with SessionLocal() as db:
    out = issue_challenge(t9_id, t8_id, week=13, bet_type="straight", amount=10.0, db=db)
    cid_d = out.challenge_id

    raised    = False
    error_msg = ""
    try:
        respond_to_challenge(cid_d, accept=True, db=db)
    except ValueError as e:
        raised    = True
        error_msg = str(e)

    _assert("D: accept raises ValueError",                    raised, error_msg)
    _assert("D: message mentions 'missing schedule data'",    "missing schedule data" in error_msg, error_msg)
    _assert("D: message mentions 'contact the commissioner'", "contact the commissioner" in error_msg.lower(), error_msg)
    _assert("D: message distinct from Test C's schedule_not_ready wording",
            "hasn't posted an official kickoff time" not in error_msg, error_msg)

    bet_count = db.query(Bet).filter(Bet.beef_challenge_id == cid_d).count()
    _assert("D: no Bet rows created", bet_count == 0, f"got {bet_count}")


# ── TEST E: mixed real+placeholder week — real row wins MIN(), not placeholder ──
# Direct call to the real is_bet_locked_for_gm, spanning BOTH TB (placeholder,
# 06:00Z) and DAL (real, 18:00Z), same calendar day, in week 14 — the exact
# shape that would fool a raw, unfiltered MIN() into picking the earlier-
# sorting placeholder. This bypasses issue_challenge/respond_to_challenge
# entirely (direct call), so _nfl_lock_time's own week-level gate never
# comes into play — unlike week 13 (Tests C/D), which had to keep the real
# row sorting first overall for that gate to pass. now_utc sits after 06:00Z
# but before 18:00Z: the buggy (unfiltered) behavior would report locked=True
# (thinks TB's 06:00 stamp already passed); the fix must report locked=False
# (DAL's real 18:00 hasn't happened yet, and TB's placeholder is correctly
# excluded from the decision).

print("\nTest E: is_bet_locked_for_gm — mixed week, real row must win MIN() over placeholder")
with SessionLocal() as db:
    raw_conn = db.connection()
    # Fix 4 (MS-PBL-3): confirm the fixture's chosen hours actually sit on
    # the sides of the band they're meant to, before trusting the
    # sort-order assertions below.
    _assert(
        "E: fixture check — REAL_KO_W14's hour still passes the band",
        _is_real_kickoff(REAL_KO_W14) is True,
    )
    _assert(
        "E: fixture check — PLACEHOLDER_KO's hour still fails the band",
        _is_real_kickoff(PLACEHOLDER_KO) is False,
    )

    now_between = datetime(2026, 12, 20, 10, 0, 0, tzinfo=timezone.utc)
    result_e = _real_is_bet_locked_for_gm(raw_conn, ["TB", "DAL"], week=14, now_utc=now_between, season=LOCK_SEASON)
    _assert(
        "E: mixed week — real DAL kickoff (18:00Z) governs, not TB's placeholder (06:00Z)",
        result_e.locked is False and result_e.reason is None,
        f"got {result_e!r}",
    )

    # Companion — after the real 18:00Z kickoff, must correctly flip to locked.
    now_after = datetime(2026, 12, 20, 19, 0, 0, tzinfo=timezone.utc)
    result_e2 = _real_is_bet_locked_for_gm(raw_conn, ["TB", "DAL"], week=14, now_utc=now_after, season=LOCK_SEASON)
    _assert(
        "E: same mixed week, after real kickoff — locked=True, reason=in_progress",
        result_e2.locked is True and result_e2.reason == "in_progress",
        f"got {result_e2!r}",
    )


# ── TEST F: bye-detection fix — placeholder-only-elsewhere team is data_gap ────
# YYY's only appearance anywhere in the season is a week-11 placeholder row.
# Querying week 12 (zero rows for YYY) must NOT be read as a true bye, since
# no real (non-placeholder) row anywhere confirms YYY is genuinely tracked.

print("\nTest F: is_bet_locked_for_gm — placeholder-only-elsewhere team is data_gap, not a bye")
with SessionLocal() as db:
    raw_conn = db.connection()
    now_f = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)  # arbitrary, real wall-clock is before either fixture week
    result_f = _real_is_bet_locked_for_gm(raw_conn, ["YYY"], week=12, now_utc=now_f, season=LOCK_SEASON)
    _assert(
        "F: YYY (placeholder-only all season) queried for a bye week — data_gap, not a bye",
        result_f.locked is True and result_f.reason == "data_gap",
        f"got {result_f!r}",
    )


# ── TEST G (Verification 3): _is_placeholder_week's one-game-week guard ───────
# Week 15 has exactly ONE row. A single loaded game trivially has one
# distinct timestamp — _is_placeholder_week must return False, not True,
# or every mid-sync week with only one game loaded so far would be
# misread as a whole-week placeholder.

print("\nTest G: _is_placeholder_week — one-game week must be False, not True")
with SessionLocal() as db:
    raw_conn = db.connection()
    result_g = _is_placeholder_week(raw_conn, week=15, season=LOCK_SEASON)
    _assert(
        "G: week 15 (exactly one row) is NOT read as a placeholder week",
        result_g is False,
        f"got {result_g!r}",
    )


# ── TEST H (Verification 4): Fix 2 bye-path integration, in-band placeholder ──
# Week 17 is a genuine whole-week placeholder (three rows sharing one
# identical timestamp — CR-1 requires MORE THAN TWO, not more than one)
# whose shared hour (18:00) happens to fall INSIDE the band's
# accepted range — the exact case that would slip past a has_real_row check
# using _is_real_kickoff() alone. WWW's only season appearance is this row.
# Querying WWW for week 18 (zero rows) must still return data_gap, not a
# false "true bye", proving has_real_row now requires BOTH conditions.

print("\nTest H: is_bet_locked_for_gm — Fix 2 bye-path integration, in-band placeholder week")
with SessionLocal() as db:
    raw_conn = db.connection()
    # Confirm the fixture actually is a placeholder week despite the in-band hour.
    is_ph_week = _is_placeholder_week(raw_conn, week=17, season=LOCK_SEASON)
    _assert(
        "H: fixture check — week 17 (shared identical in-band timestamp) IS a placeholder week",
        is_ph_week is True,
        f"got {is_ph_week!r}",
    )
    _assert(
        "H: fixture check — that shared timestamp individually passes _is_real_kickoff (the trap)",
        _is_real_kickoff(INBAND_PLACEHOLDER_KO) is True,
    )

    result_h = _real_is_bet_locked_for_gm(raw_conn, ["WWW"], week=18, now_utc=now_f, season=LOCK_SEASON)
    _assert(
        "H: WWW (in-band placeholder-week-only all season) queried for a bye week — data_gap, not a bye",
        result_h.locked is True and result_h.reason == "data_gap",
        f"got {result_h!r}",
    )


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
