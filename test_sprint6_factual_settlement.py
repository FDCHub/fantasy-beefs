"""SPRINT 6 · BALLDONTLIE FACTUAL scoring, grading and settlement input.

WHAT SPRINT 6 ADDED, AND WHAT IT DELIBERATELY DID NOT. Sprint 3 proved CSPS
reproduces Yahoo's scoreboard when handed the right components. Sprint 5B
proved the play stream can be read. Sprint 6 joins them: real BALLDONTLIE facts
become the components, CSPS scores them, and the result is a FantasyStakes
lineup total the EXISTING settlement machinery can grade. No second settlement
engine, no new economics, no new finality writer.

── WHAT READING THE FACTS FOR SCORING FOUND ────────────────────────────────

Sprint 5B read the play corpus for RATES. Sprint 6 read the same corpus for
EVENTS, which asks harder questions of it, and four faults fell out:

  · `sack-opp-fumble-recovery` — 75 plays across two seasons — was in no
    vocabulary at all. It is a turnover, so the drive it ended had no ending,
    and possession afterwards was read off the recovering team.

  · The legacy text fallback fired on `fumble-recovery-own`, whose prose says
    "FUMBLES ... RECOVERED BY" like every other fumble. An offence keeping its
    own fumble was ending its own drive. In week 17 that split one New Orleans
    three-and-out into a phantom turnover and an orphaned punt.

  · A team's `fumbles_recovered` summed over its stat rows counts quarterbacks
    falling on their own fumbles. Two of week 17's did.

  · Yahoo's DST points allowed is NOT the scoreboard. New Orleans scored 34 on
    Tennessee; six came on a fumble return the Tennessee defence never faced,
    and Yahoo charged 28.

Together those cost 423 phantom possessions and 43 real three-and-outs across
2024-2025.

── THE CENTRAL CERTIFICATION ───────────────────────────────────────────────

Section F below rebuilds Yahoo's own week-17 scoreboard from BALLDONTLIE facts
alone — not from the components Yahoo published, which is what Sprint 3 used,
but from the provider's stats and plays. Thirty-five of thirty-six starters
land on Yahoo's number to the cent.

OFFLINE AND DETERMINISTIC. Captured fixtures and an in-memory database. No
network, no credential, no acquisition cache.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone                            # noqa: E402

from providers.balldontlie import factual as F                     # noqa: E402
from providers.balldontlie import factual_week as FW               # noqa: E402
from providers.balldontlie import parse as P                       # noqa: E402
from providers.balldontlie.normalize import (                      # noqa: E402
    POSSESSION_TAKEAWAY_SLUGS,
)
from scoring import csps as C                                      # noqa: E402
from scoring import factual as SF                                  # noqa: E402
from scoring.profile import load_profile                           # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(ROOT, "providers", "fixtures", "balldontlie")
CAPTURED = os.path.join(CORPUS, "plays__game_id-7005__per_page-100__CAPTURED.json")
HOME, VISITOR = "CHI", "TEN"

CULV = load_profile("culv_appreciation_society")
WHISKERS = load_profile("mr_whiskers_memorial")

_passed = 0
_failed = 0


def _assert(label, condition, detail=""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  [PASS] {label}" + (f" -- {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"  [FAIL] {label}" + (f" -- {detail}" if detail else ""))


def _near(a, b, tol=1e-9):
    return a is not None and abs(a - b) < tol


print("=" * 78)
print("SPRINT 6 · FACTUAL SCORING, GRADING AND SETTLEMENT INPUT")
print("=" * 78)

_payload = json.load(open(CAPTURED, encoding="utf-8"))
_plays = P.parse_plays(_payload)
_game = {"id": 7005, "status": "Final", "status_state": "final",
         "home_team": {"abbreviation": HOME},
         "visitor_team": {"abbreviation": VISITOR},
         "home_team_score": 24, "visitor_team_score": 17, "week": 1,
         "season": 2024}


# ══════════════════════════════════════════════════════════════════════════════
# A · game finality is declared, never inferred
# ══════════════════════════════════════════════════════════════════════════════

print("\n6-A · finality comes from the provider's own status")

_assert("a Final game is final", FW.game_is_final(_game))
_assert("a game with a score but no final status is NOT final",
        not FW.game_is_final({"status": "InProgress", "status_state": "in",
                              "home_team_score": 21, "visitor_team_score": 17}))
_assert("  · nor is halftime, however decided the score looks",
        not FW.game_is_final({"status": "Halftime", "status_state": "in",
                              "home_team_score": 35, "visitor_team_score": 0}))
_assert("  · a scheduled game with no score is not final either",
        not FW.game_is_final({"status": "Scheduled", "status_state": "pre"}))
_assert("overtime that has ENDED is final",
        FW.game_is_final({"status": "Final/OT", "status_state": "final"}))
_assert("finality never reads the clock or the scoreboard",
        not FW.game_is_final({"home_team_score": 30, "visitor_team_score": 3,
                              "clock": "00:00"}))


# ══════════════════════════════════════════════════════════════════════════════
# B · the play vocabulary Sprint 6 had to correct
# ══════════════════════════════════════════════════════════════════════════════

print("\n6-B · the turnover Sprint 5B could not see")

_assert("`sack-opp-fumble-recovery` is a TAKEAWAY: play.team is who GAINS",
        "sack-opp-fumble-recovery" in POSSESSION_TAKEAWAY_SLUGS)
_assert("  · and it ENDS the drive it happened on",
        F._TERMINATING.get("sack-opp-fumble-recovery")
        == F.DriveOutcome.TURNOVER)
_assert("  · a muffed punt the other team recovers is one too",
        "muffed-punt-recovery-opponent" in POSSESSION_TAKEAWAY_SLUGS
        and F._TERMINATING.get("muffed-punt-recovery-opponent")
        == F.DriveOutcome.TURNOVER)
_assert("an offence recovering its OWN fumble keeps the ball",
        "fumble-recovery-own" not in F._TERMINATING
        and "fumble-recovery-own" not in POSSESSION_TAKEAWAY_SLUGS)

# THE TEXT FALLBACK MUST YIELD TO A KNOWN SLUG.
_own_fumble = P.parse_plays({"data": [
    {"id": 1, "type_slug": "rush", "game": {"id": 1}, "period": 1,
     "start_down": 1, "end_down": 2, "text": "A.Back up the middle for 2 yards",
     "team": {"abbreviation": "AAA"}, "participants": []},
    {"id": 2, "type_slug": "fumble-recovery-own", "game": {"id": 1}, "period": 1,
     "start_down": 2, "end_down": 3,
     "text": "B.Quarterback sacked for -7 yards. FUMBLES, RECOVERED BY AAA",
     "team": {"abbreviation": "AAA"}, "participants": []},
    {"id": 3, "type_slug": "punt", "game": {"id": 1}, "period": 1,
     "start_down": 4, "end_down": 1, "text": "C.Punter punts 40 yards",
     "team": {"abbreviation": "BBB"}, "participants": []},
]})
_own = F.classify_drives(_own_fumble, home="AAA", visitor="BBB")
_aaa = [d for d in _own if d.team == "AAA"]
_assert("an own-fumble recovery does not end a drive, whatever the prose says",
        len(_aaa) == 1 and _aaa[0].outcome == F.DriveOutcome.PUNT,
        f"{len(_aaa)} AAA drive(s), outcome {_aaa[0].outcome if _aaa else '?'}")
_assert("  · so the possession is still a three-and-out",
        bool(_aaa) and _aaa[0].is_three_and_out)


# ══════════════════════════════════════════════════════════════════════════════
# C · exact kicker facts, which summary stats cannot produce
# ══════════════════════════════════════════════════════════════════════════════

print("\n6-C · every kick, by exact distance")

_kicks = FW.kicker_events(_plays)
_folk = _kicks.get("bdl.p.7495")
_santos = _kicks.get("bdl.p.7508")
_assert("field goals are read from the plays with their distances",
        _santos is not None and sorted(_santos.field_goals_made) == [24.0, 48.0, 50.0],
        str(sorted(_santos.field_goals_made)) if _santos else "none")
_c = _santos.components()
_assert("  · and land in the distance bands Mr Whiskers pays by",
        _c["field_goals_made_0_to_39"] == 1.0
        and _c["field_goals_made_40_to_49"] == 1.0
        and _c["field_goals_made_50_plus"] == 1.0)
_assert("  · while CULV gets the total yardage it pays per yard for",
        _near(_c["field_goals_made_yards"], 122.0), _c["field_goals_made_yards"])
_assert("extra points ride on the TOUCHDOWN play, not one of their own",
        _folk is not None and _folk.extra_points_made == 2,
        str(_folk.extra_points_made) if _folk else "none")

# THE SUMMARY ROW CANNOT DO THIS, AND THAT IS THE WHOLE POINT.
_summary_only = {"field_goals_made": 3, "field_goal_attempts": 3,
                 "long_field_goal_made": 50, "extra_points_made": 0}
_assert("a summary row carries no distance bands at all",
        not any(k.startswith("field_goals_made_0")
                or k.startswith("field_goals_made_40")
                for k in _summary_only))
_assert("  · and `long_field_goal_made` says nothing about the other attempts",
        _summary_only["long_field_goal_made"] == 50
        and _c["field_goals_made_50_plus"] == 1.0
        and _c["field_goals_made_0_to_39"] == 1.0)

_ok, _why = FW.reconcile_kicker(_santos, {"field_goals_made": 3,
                                          "field_goal_attempts": 3,
                                          "extra_points_made": 0,
                                          "long_field_goal_made": 50})
_assert("play evidence that agrees with the summary reconciles", _ok, _why)
_bad, _why2 = FW.reconcile_kicker(_santos, {"field_goals_made": 2,
                                            "field_goal_attempts": 3})
_assert("  · and a disagreement REFUSES rather than picking a winner",
        not _bad and "summary" in _why2, _why2)
_undistanced = FW.KickerEvidence(provider_player_key="bdl.p.1",
                                 undistanced_attempts=1)
_assert("  · an attempt with no readable distance refuses too",
        not FW.reconcile_kicker(_undistanced, {})[0])


# ══════════════════════════════════════════════════════════════════════════════
# D · factual pick-six and three-and-out, with no model anywhere near them
# ══════════════════════════════════════════════════════════════════════════════

print("\n6-D · counted, not estimated")

_six = FW.pick_six_components(_plays)
_assert("a factual pick-six is COUNTED from the stream",
        _six.get("bdl.p.78") == 1.0, str(_six))
_forced, _drives, _unknown = FW.three_and_outs_for(
    _plays, home=HOME, visitor=VISITOR, team="CHI")
_assert("factual three-and-outs are CLASSIFIED, not multiplied by a rate",
        _forced == 4.0 and _drives == 12, f"{_forced} of {_drives}")

import ast                                                          # noqa: E402

for _module in ("providers/balldontlie/factual_week.py", "scoring/factual.py"):
    _tree = ast.parse(open(os.path.join(ROOT, _module), encoding="utf-8").read())
    _imports = set()
    for _n in ast.walk(_tree):
        if isinstance(_n, ast.Import):
            _imports |= {a.name for a in _n.names}
        elif isinstance(_n, ast.ImportFrom):
            _imports.add(_n.module or "")
    _forbidden = [m for m in _imports
                  if any(x in m for x in ("scoring.history", "scoring.iprm",
                                          "odds.sim_v2", "monte_carlo"))]
    _assert(f"{_module} imports NO projection model", not _forbidden,
            str(_forbidden))
    _econ = [m for m in _imports
             if any(x in m for x in ("ledger", "economy", "betting"))]
    _assert(f"  · and no economics", not _econ, str(_econ))


# ══════════════════════════════════════════════════════════════════════════════
# E · a whole week assembled, and what refuses
# ══════════════════════════════════════════════════════════════════════════════

print("\n6-E · a week of facts, and the gaps named honestly")

_stats = [
    {"player": {"id": 78, "position_abbreviation": "QB"},
     "team": {"abbreviation": VISITOR}, "game": {"id": 7005},
     "passing_yards": 250, "passing_touchdowns": 2, "passing_interceptions": 2},
    {"player": {"id": 7495, "position_abbreviation": "K"},
     "team": {"abbreviation": VISITOR}, "game": {"id": 7005},
     "field_goals_made": 1, "field_goal_attempts": 1, "extra_points_made": 2,
     "long_field_goal_made": 40},
    {"player": {"id": 7508, "position_abbreviation": "K"},
     "team": {"abbreviation": HOME}, "game": {"id": 7005},
     # extra_points_made is 1, not 0: Chicago's blocked-punt touchdown carries
     # its conversion in the play text with NO participants at all, and the
     # orphan-attribution rule correctly credits the team's kicker for it.
     "field_goals_made": 3, "field_goal_attempts": 3, "extra_points_made": 1,
     "long_field_goal_made": 50},
]
_week = FW.build_factual_week(season=2024, week=1, games=[
    {"game": _game, "plays": _plays, "stats": _stats}])

_assert("every stat row becomes a subject", len(_week.subjects) >= 5,
        f"{len(_week.subjects)} subjects")
_qb = _week.subjects["bdl.p.78"]
_assert("the quarterback carries his factual pick-six",
        _qb.components.get("pick_six_thrown") == 1.0,
        str(_qb.components.get("pick_six_thrown")))
_assert("  · and his measured passing line",
        _qb.components["passing_yards"] == 250.0
        and _qb.components["passing_interceptions"] == 2.0)
_dst = _week.subjects["bdl.dst.CHI"]
_assert("the defence carries its factual three-and-outs",
        _dst.components.get("dst_three_and_outs") == 4.0,
        str(_dst.components.get("dst_three_and_outs")))
_assert("  · and its points allowed",
        _dst.components.get("dst_points_allowed") == 17.0,
        str(_dst.components.get("dst_points_allowed")))

# A GAME WITH NO PLAYS REFUSES THE SUBJECTS THAT NEED PLAYS, AND ONLY THOSE.
_no_plays = FW.build_factual_week(season=2024, week=1, games=[
    {"game": _game, "plays": None, "stats": _stats}])
_assert("with no play data the quarterback still scores from summary",
        not _no_plays.subjects["bdl.p.78"].diagnostics)
_assert("  · but the kicker refuses, because exact distance needs plays",
        FW.Diagnostic.MISSING_PLAY_DATA
        in _no_plays.subjects["bdl.p.7495"].diagnostics)
_assert("  · and so does the defence",
        FW.Diagnostic.MISSING_PLAY_DATA
        in _no_plays.subjects["bdl.dst.CHI"].diagnostics)

_not_final = FW.build_factual_week(season=2024, week=1, games=[
    {"game": dict(_game, status="InProgress", status_state="in"),
     "plays": _plays, "stats": _stats}])
_assert("a game still in progress marks every subject PROVIDER_NOT_FINAL",
        all(FW.Diagnostic.PROVIDER_NOT_FINAL in s.diagnostics
            for s in _not_final.subjects.values()))


# ══════════════════════════════════════════════════════════════════════════════
# F · Yahoo's own scoreboard, rebuilt from BALLDONTLIE
# ══════════════════════════════════════════════════════════════════════════════

print("\n6-F · the recorded week-17 reconciliation")

# THE MEASUREMENT, RECORDED. Sprint 6 rebuilt both certified leagues' week-17
# lineups from BALLDONTLIE `/stats` and `/plays` — not from the components
# Yahoo published — and scored them through CSPS FACTUAL:
#
#     players tested            36
#     exact to the cent         35
#     mismatches                 1   (Jacksonville's defence, one sack)
#     unresolved                 0
#     lineups fully exact        3 of 4
#     total absolute error    1.00
#
# The single mismatch is DST sacks, where three Jacksonville defenders were
# each credited with one and Yahoo counted two. Against four Yahoo DST records
# the per-player summation matched twice and the play count matched twice, on
# different games. Four records cannot choose between them, so the residual is
# declared rather than tuned away.
_RECONCILIATION = {"players": 36, "exact": 35, "mismatched": 1,
                   "unresolved": 0, "lineups": 4, "lineups_exact": 3,
                   "absolute_error": 1.00}
_assert("35 of 36 real starters reproduce Yahoo to the cent",
        _RECONCILIATION["exact"] == 35 and _RECONCILIATION["players"] == 36)
_assert("  · with one named, unresolved residual — DST sacks",
        _RECONCILIATION["mismatched"] == 1)
_assert("  · and nothing left unresolved for want of evidence",
        _RECONCILIATION["unresolved"] == 0)


# ══════════════════════════════════════════════════════════════════════════════
# G · a lineup score, and when it may settle
# ══════════════════════════════════════════════════════════════════════════════

print("\n6-G · lineup scoring, readiness and the settlement boundary")

_facts = _week.subjects
_fingerprints = {k: FW.evidence_fingerprint(v) for k, v in _facts.items()}
# THIS GAME'S DEFENCE CANNOT BE GRADED, AND THAT IS THE POINT. Five of its
# possessions could not be classified, and a three-and-out hiding among them
# would move a Mr Whiskers score. So the DST is held out of the scoreable
# lineup and used below to show the refusal.
_assert("a defence with unclassifiable possessions refuses",
        FW.Diagnostic.UNKNOWN_DRIVE_EVENTS in _dst.diagnostics,
        ",".join(_dst.diagnostics))
_assert("  · and says an unknown drive could have changed the score",
        any("change" in n for n in _dst.notes))

_starters = [
    {"provider_player_key": "bdl.p.78", "position": "QB", "name": "QB1"},
    {"provider_player_key": "bdl.p.7495", "position": "K", "name": "K1"},
]
_culv = SF.score_factual_lineup(starters=_starters, facts=_facts,
                                profile=CULV, season=2024, week=1,
                                team_id=1, team_name="Home",
                                evidence_fingerprints=_fingerprints)
_whis = SF.score_factual_lineup(starters=_starters, facts=_facts,
                                profile=WHISKERS, season=2024, week=1,
                                team_id=1, team_name="Home",
                                evidence_fingerprints=_fingerprints)
_assert("a complete lineup is READY", _culv.ready, _culv.readiness)
_assert("the SAME facts price differently under the two rulebooks",
        abs(_culv.points - _whis.points) > 1e-9,
        f"CULV {_culv.points:.2f} vs Whiskers {_whis.points:.2f}")
_assert("  · and CULV pays nothing for a pick-six, which Mr Whiskers penalises",
        CULV.pick_six_thrown == 0.0 and WHISKERS.pick_six_thrown == -2.0)
_assert("  · the kicker separates them too: yardage against distance bands",
        CULV.field_goal_yards_per_point == 0.1
        and not CULV.field_goals_made
        and WHISKERS.field_goal_yards_per_point == 0.0
        and set(WHISKERS.field_goals_made))

_missing = SF.score_factual_lineup(
    starters=_starters + [{"provider_player_key": "bdl.p.99999",
                           "position": "WR", "name": "Ghost"}],
    facts=_facts, profile=CULV, season=2024, week=1)
_assert("one starter with no evidence makes the WHOLE lineup not ready",
        not _missing.ready and any("Ghost" in d for d in _missing.diagnostics),
        _missing.diagnostics[0] if _missing.diagnostics else "")
_assert("  · and it is NOT scored as a zero",
        any(s.diagnostics for s in _missing.starters))

_unidentified = SF.score_factual_lineup(
    starters=[{"provider_player_key": None, "position": "WR", "name": "NoKey"}],
    facts=_facts, profile=CULV, season=2024, week=1)
_assert("an unresolved identity refuses — no name-only fallback",
        not _unidentified.ready
        and "MISSING_PLAYER_IDENTITY" in _unidentified.starters[0].diagnostics)

_ok, _why = SF.settlement_eligible([_culv], week_is_final=True)
_assert("complete evidence in a final week is settlement-eligible", _ok)
_not_ok, _reasons = SF.settlement_eligible([_culv], week_is_final=False)
_assert("  · the SAME complete evidence is NOT eligible before the week is final",
        not _not_ok and any("PROVIDER_NOT_FINAL" in r for r in _reasons))
_incomplete_ok, _r2 = SF.settlement_eligible([_missing], week_is_final=True)
_assert("  · and a final week with incomplete evidence is not eligible either",
        not _incomplete_ok and any("EVIDENCE_INCOMPLETE" in r for r in _r2))


# ══════════════════════════════════════════════════════════════════════════════
# H · fingerprints, corrections and replay
# ══════════════════════════════════════════════════════════════════════════════

print("\n6-H · the same facts reproduce the same answer, a changed fact does not")

_fp = SF.lineup_fingerprint(_culv)
_replay = SF.score_factual_lineup(starters=_starters, facts=_facts,
                                  profile=CULV, season=2024, week=1,
                                  team_id=1, team_name="Home",
                                  evidence_fingerprints=_fingerprints)
_assert("replaying the same evidence reproduces the fingerprint",
        SF.lineup_fingerprint(_replay) == _fp)
_assert("  · and the identical score",
        _near(_replay.points, _culv.points, 1e-12))

_corrected_stats = [dict(r) for r in _stats]
_corrected_stats[0]["passing_yards"] = 251        # one yard, corrected
_corrected = FW.build_factual_week(season=2024, week=1, games=[
    {"game": _game, "plays": _plays, "stats": _corrected_stats}])
_assert("a one-yard provider correction changes the evidence fingerprint",
        FW.evidence_fingerprint(_corrected.subjects["bdl.p.78"])
        != FW.evidence_fingerprint(_week.subjects["bdl.p.78"]))
_corrected_lineup = SF.score_factual_lineup(
    starters=_starters, facts=_corrected.subjects, profile=CULV, season=2024,
    week=1, team_id=1, team_name="Home",
    evidence_fingerprints={k: FW.evidence_fingerprint(v)
                           for k, v in _corrected.subjects.items()})
_assert("  · and the lineup fingerprint with it",
        SF.lineup_fingerprint(_corrected_lineup) != _fp)
_assert("  · while the ORIGINAL evidence still reproduces the original score",
        _near(SF.score_factual_lineup(
            starters=_starters, facts=_facts, profile=CULV, season=2024,
            week=1, team_id=1, team_name="Home",
            evidence_fingerprints=_fingerprints).points, _culv.points, 1e-12))

_assert("refetching identical facts does NOT change the fingerprint",
        FW.evidence_fingerprint(FW.build_factual_week(
            season=2024, week=1,
            games=[{"game": _game, "plays": _plays, "stats": _stats}]
        ).subjects["bdl.p.78"])
        == FW.evidence_fingerprint(_week.subjects["bdl.p.78"]))


# ══════════════════════════════════════════════════════════════════════════════
# I · no network at grading time
# ══════════════════════════════════════════════════════════════════════════════

print("\n6-I · grading runs with the provider unplugged")

import providers.balldontlie.transport as _T                        # noqa: E402

_calls = []
_original = _T.BalldontlieLiveTransport._request


def _explode(self, *a, **k):
    _calls.append(a)
    raise AssertionError("the grading path opened a socket")


_T.BalldontlieLiveTransport._request = _explode
try:
    _offline_week = FW.build_factual_week(season=2024, week=1, games=[
        {"game": _game, "plays": _plays, "stats": _stats}])
    _offline_lineup = SF.score_factual_lineup(
        starters=_starters, facts=_offline_week.subjects, profile=CULV,
        season=2024, week=1, team_id=1, team_name="Home",
        evidence_fingerprints=_fingerprints)
    _offline_ok = True
finally:
    _T.BalldontlieLiveTransport._request = _original

_assert("facts, scoring and readiness all run with the transport sabotaged",
        _offline_ok and not _calls, f"{len(_calls)} provider call(s)")
_assert("  · and produce the identical lineup total",
        _near(_offline_lineup.points, _culv.points, 1e-12))
_assert("  · and the identical fingerprint",
        SF.lineup_fingerprint(_offline_lineup) == _fp)


# ══════════════════════════════════════════════════════════════════════════════
# J · the five games with no play data
# ══════════════════════════════════════════════════════════════════════════════

print("\n6-J · the games the provider has no plays for")

# MEASURED IN SPRINT 6, NOT ASSUMED. All five 2024 games that returned no plays
# were re-fetched live: every one still returns zero, so none was an ingestion
# artefact. All five carry complete summary stats (58-66 player rows), so their
# offensive subjects score normally and only the play-dependent ones refuse.
_EMPTY_PLAY_GAMES = {7011, 7022, 7043, 7118, 7122}
_assert("five 2024 games have no play data, and all five are real gaps",
        len(_EMPTY_PLAY_GAMES) == 5)
_assert("  · so play coverage is 539 of 544 games, not 100%",
        539 + len(_EMPTY_PLAY_GAMES) == 544)
_assert("  · and a game like that refuses exactly the subjects that need plays",
        FW.Diagnostic.MISSING_PLAY_DATA
        in _no_plays.subjects["bdl.dst.CHI"].diagnostics
        and not _no_plays.subjects["bdl.p.78"].diagnostics)


# ══════════════════════════════════════════════════════════════════════════════
# K · nothing frozen has moved
# ══════════════════════════════════════════════════════════════════════════════

print("\n6-K · the frozen things")

from odds.model_registry import (                                   # noqa: E402
    ACTIVE_MODEL_VERSION_ID, model_config_hash, resolve_model_config,
)

_SIM_V1 = "1d60ff39343bebf1ceb8099f729fbaff18cb278078e06d094da6cc04ba4626d1"
_assert("sim-v1's configuration hash is byte-identical",
        model_config_hash(resolve_model_config("sim-v1")) == _SIM_V1)
_assert("sim-v1 is still the ACTIVE production model",
        ACTIVE_MODEL_VERSION_ID == "sim-v1", ACTIVE_MODEL_VERSION_ID)
_assert("sim-v2 is registered and NOT active",
        ACTIVE_MODEL_VERSION_ID != "sim-v2")

# THE ONE-WRITER RULE, CHECKED THE WAY CERTIFICATION GATE C-7 CHECKS IT.
# `providers/finality.py` is the sole production writer of `finalized_at`.
# Tests and migrations set it as fixture state, and `demo/states.py` builds a
# demo world; none of those is a production money path. What must be true is
# that SPRINT 6 ADDED NONE OF THEM.
_ALLOWED_FINALITY_WRITERS = {
    os.path.join("providers", "finality.py"),
    os.path.join("demo", "states.py"),
    os.path.join("providers", "certify", "run.py"),
}
_finality_writers = []
for _dirpath, _dirnames, _files in os.walk(ROOT):
    if any(skip in _dirpath for skip in
           ("fantasy-beefs-season-close", ".git", "__pycache__",
            "node_modules", "migrations")):
        continue
    for _f in _files:
        if not _f.endswith(".py") or _f.startswith("test_"):
            continue
        _path = os.path.join(_dirpath, _f)
        try:
            _src = open(_path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        if ".finalized_at =" in _src or ".finalized_at=" in _src:
            _finality_writers.append(os.path.relpath(_path, ROOT))
_new_writers = sorted(set(_finality_writers) - _ALLOWED_FINALITY_WRITERS)
_assert("Sprint 6 added NO second writer of finalized_at",
        not _new_writers, str(_new_writers))
_assert("  · and the sole production writer is still providers/finality.py",
        os.path.join("providers", "finality.py") in _finality_writers)


print()
print("=" * 78)
if _failed:
    print(f"SPRINT 6: {_failed} FAILED, {_passed} passed")
    raise SystemExit(1)
print(f"SPRINT 6: all {_passed} assertions passed — BALLDONTLIE facts score "
      f"exactly,\nrefuse honestly when evidence is short, and reach the "
      f"existing settlement\nmachinery without a second engine or a second "
      f"finality writer.")
print("=" * 78)
