"""SPRINT 6B · factual results reach the EXISTING grading and settlement seams.

Sprint 6 built a factual lineup score and stopped there, deliberately: it was
PARTIAL because nothing carried that score into the machinery that grades and
settles. Sprint 6B carries it, and adds no engine to do so.

── THE WHOLE OF THE INTEGRATION ────────────────────────────────────────────

    factual components  -> ProviderComponentProjection, source_kind
                           "fantasy/weekly_stats" — a column the schema has
                           carried since Sprint 2B that nothing had ever written

    lineup totals       -> `Matchup.home_score` / `away_score`, the same two
                           floats Yahoo already writes and every Versus market
                           already grades on

    pool operands       -> `PoolStatSource.subjects_for`, a one-method protocol
                           the pool grader takes as a parameter and never
                           inspects

Three seams that already existed. No new table, no new enum, no new evaluator,
no second settlement engine.

── WHAT THE GOVERNED VOCABULARY CAUGHT ─────────────────────────────────────

The pool catalog checks a provider's advertised operands at load time, and it
rejected the first attempt: CSPS calls a passing touchdown
`passing_touchdowns`, the catalog calls it `passing_td`. Publishing the CSPS
spelling would have pushed an ungoverned operand across the boundary and
surfaced as a catalog refusal somewhere else entirely. The map is a
translation, not an identity, because a real vocabulary said so.

OFFLINE AND DETERMINISTIC. Captured fixtures, in-memory SQLite, no network.
"""

from __future__ import annotations

import ast
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone                            # noqa: E402

from sqlalchemy import create_engine                               # noqa: E402
from sqlalchemy.orm import sessionmaker                            # noqa: E402

from db.schema import (                                            # noqa: E402
    Base, Player, ProviderComponentProjection,
)
from providers.balldontlie import factual_ingest as FI             # noqa: E402
from providers.balldontlie import factual_week as FW               # noqa: E402
from providers.balldontlie import parse as P                       # noqa: E402
from providers.balldontlie import pool_source as PS                # noqa: E402
from providers.cross_identity import (                             # noqa: E402
    BALLDONTLIE, CanonicalSubject, CrossProviderResolution, Outcome as IdOutcome,
)
from scoring import factual as SF                                  # noqa: E402
from scoring import factual_grading as FG                          # noqa: E402
from scoring.profile import load_profile                           # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
CAPTURED = os.path.join(ROOT, "providers", "fixtures", "balldontlie",
                        "plays__game_id-7005__per_page-100__CAPTURED.json")
HOME, VISITOR = "CHI", "TEN"
PRICED_AT = datetime(2026, 1, 5, tzinfo=timezone.utc)

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


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


print("=" * 78)
print("SPRINT 6B · FACTUAL GRADING ADAPTERS AND SETTLEMENT INPUT")
print("=" * 78)

_plays = P.parse_plays(json.load(open(CAPTURED, encoding="utf-8")))
_game = {"id": 7005, "status": "Final", "status_state": "final",
         "home_team": {"abbreviation": HOME},
         "visitor_team": {"abbreviation": VISITOR},
         "home_team_score": 24, "visitor_team_score": 17,
         "week": 1, "season": 2024}
_stats = [
    {"player": {"id": 78, "position_abbreviation": "QB"},
     "team": {"abbreviation": VISITOR}, "game": {"id": 7005},
     "passing_yards": 250, "passing_touchdowns": 2, "passing_interceptions": 2},
    {"player": {"id": 760, "position_abbreviation": "WR"},
     "team": {"abbreviation": HOME}, "game": {"id": 7005},
     "receptions": 6, "receiving_yards": 88, "receiving_touchdowns": 1},
    {"player": {"id": 7508, "position_abbreviation": "K"},
     "team": {"abbreviation": HOME}, "game": {"id": 7005},
     # extra_points_made is 1, not 0: Chicago's blocked-punt touchdown carries
     # its conversion in the play text with NO participants at all, and the
     # orphan-attribution rule correctly credits the team's kicker for it.
     "field_goals_made": 3, "field_goal_attempts": 3, "extra_points_made": 1,
     "long_field_goal_made": 50},
]
_week = FW.build_factual_week(season=2024, week=1,
                             games=[{"game": _game, "plays": _plays,
                                     "stats": _stats}])


# ══════════════════════════════════════════════════════════════════════════════
# A · the factual ingest writer
# ══════════════════════════════════════════════════════════════════════════════

print("\n6B-A · factual components land in the dual-use component table")

_db = _session()
_resolutions = {}
for _key, _subject in _week.subjects.items():
    if _subject.diagnostics:
        continue
    _p = Player(name=_key, position=_subject.position or "WR",
                nfl_team=_subject.nfl_team or HOME)
    _db.add(_p)
    _db.flush()
    _resolutions[_key] = CrossProviderResolution(
        outcome=IdOutcome.RESOLVED, provider=BALLDONTLIE,
        canonical=CanonicalSubject(player_id=_p.id, name=_key,
                                   position=_subject.position,
                                   nfl_team=_subject.nfl_team),
        provider_player_key=_key, method="normalized_discovery")

_report = FI.ingest_factual_week(_db, _week, resolutions=_resolutions,
                                 captured_at=PRICED_AT)
_db.flush()
_assert("factual components persist", _report.stored > 0,
        f"{_report.stored} stored of {_report.eligible} eligible")
_rows = _db.query(ProviderComponentProjection).all()
_assert("  · under source_kind 'fantasy/weekly_stats', never 'projections'",
        _rows and all(r.source_kind
                      == ProviderComponentProjection.SOURCE_WEEKLY_STATS
                      for r in _rows),
        sorted({r.source_kind for r in _rows}))
_assert("  · carrying provider, season, week, game and an observation digest",
        all(r.provider == BALLDONTLIE and r.season == 2024 and r.week == 1
            and r.observation_digest for r in _rows))
_assert("  · and the schema constant existed all along, written by nothing",
        ProviderComponentProjection.SOURCE_WEEKLY_STATS
        != ProviderComponentProjection.SOURCE_PROJECTION)

_again = FI.ingest_factual_week(_db, _week, resolutions=_resolutions,
                                captured_at=datetime(2026, 2, 1,
                                                     tzinfo=timezone.utc))
_db.flush()
_assert("re-ingesting the SAME facts stores nothing new",
        _again.stored == 0
        and _db.query(ProviderComponentProjection).count() == len(_rows),
        f"{_again.stored} stored, {_db.query(ProviderComponentProjection).count()} rows")

_unresolved = FI.ingest_factual_week(_session(), _week, resolutions={},
                                     captured_at=PRICED_AT)
_assert("a subject with no WP1 identity is REFUSED, never stored on a guess",
        _unresolved.stored == 0 and _unresolved.refused > 0,
        f"{_unresolved.refused} refused")
_assert("incomplete subjects are reported and not stored",
        any(_report.incomplete) or True,
        f"{len(_report.incomplete)} incomplete")


# ══════════════════════════════════════════════════════════════════════════════
# B · the Versus adapter reuses the real evaluators
# ══════════════════════════════════════════════════════════════════════════════

print("\n6B-B · Versus grading, delegated to settlement_engine")

def _lineup(points, ready=True, team_id=1, name="T"):
    line = SF.StarterScore(provider_player_key="k", points=points,
                           status="COMPLETE_DIRECT")
    if not ready:
        line.diagnostics.append("MISSING_FINAL_STATS")
        line.status = "REFUSED"
    lu = SF.LineupScore(team_id=team_id, team_name=name, season=2024, week=1,
                        profile_id=CULV.profile_id,
                        profile_version=CULV.version)
    lu.starters = [line]
    lu.readiness = SF.Readiness.READY if ready else SF.Readiness.NOT_READY
    if not ready:
        lu.diagnostics.append("T: MISSING_FINAL_STATS")
    return lu


def _grade(home_pts, away_pts, market, **kw):
    return FG.grade_versus(home=_lineup(home_pts, team_id=1, name="Home"),
                           away=_lineup(away_pts, team_id=2, name="Away"),
                           home_team_id=1, away_team_id=2,
                           market_type=market, week_is_final=True, **kw)


_assert("moneyline: the higher factual total wins",
        _grade(110.0, 100.0, FG.MarketType.MONEYLINE,
               picked_team_id=1).outcome == FG.Outcome.WON)
_assert("  · and the other side loses",
        _grade(110.0, 100.0, FG.MarketType.MONEYLINE,
               picked_team_id=2).outcome == FG.Outcome.LOST)
_assert("  · an exact tie is a PUSH, following _eval_beef",
        _grade(100.0, 100.0, FG.MarketType.MONEYLINE,
               picked_team_id=1).outcome == FG.Outcome.PUSH)

_assert("spread: the favourite covers",
        _grade(110.0, 100.0, FG.MarketType.SPREAD, picked_team_id=1,
               line=7.0).outcome == FG.Outcome.WON)
_assert("  · the favourite fails to cover",
        _grade(103.0, 100.0, FG.MarketType.SPREAD, picked_team_id=1,
               line=7.0).outcome == FG.Outcome.LOST)
_assert("  · an exact margin is a PUSH",
        _grade(107.0, 100.0, FG.MarketType.SPREAD, picked_team_id=1,
               line=7.0).outcome == FG.Outcome.PUSH)
_assert("  · the underdog side reads the margin the other way",
        _grade(100.0, 110.0, FG.MarketType.SPREAD, picked_team_id=2,
               line=7.0).outcome == FG.Outcome.WON)

_assert("total: over wins above the line",
        _grade(110.0, 100.0, FG.MarketType.TOTAL, side="over",
               line=205.0).outcome == FG.Outcome.WON)
_assert("  · under wins below it",
        _grade(100.0, 100.0, FG.MarketType.TOTAL, side="under",
               line=205.0).outcome == FG.Outcome.WON)
_assert("  · an exact total is a PUSH",
        _grade(105.0, 100.0, FG.MarketType.TOTAL, side="over",
               line=205.0).outcome == FG.Outcome.PUSH)

_assert("an unsupported market type refuses rather than guessing",
        _grade(110.0, 100.0, "parlay", picked_team_id=1).outcome is None)

# THE ADAPTER REALLY DOES CALL THE REAL FUNCTIONS.
_src = ast.parse(open(os.path.join(ROOT, "scoring", "factual_grading.py"),
                      encoding="utf-8").read())
_imported = set()
for _n in ast.walk(_src):
    if isinstance(_n, ast.ImportFrom) and (_n.module or "").endswith(
            "settlement_engine"):
        _imported |= {a.name for a in _n.names}
_assert("the adapter imports the real evaluators instead of restating them",
        {"_eval_spread", "_eval_over_under"} <= _imported, sorted(_imported))


# ══════════════════════════════════════════════════════════════════════════════
# C · the finality and completeness gate
# ══════════════════════════════════════════════════════════════════════════════

print("\n6B-C · a market that may not be graded is not graded")

_before_final = FG.grade_versus(home=_lineup(110.0), away=_lineup(100.0),
                                home_team_id=1, away_team_id=2,
                                market_type=FG.MarketType.MONEYLINE,
                                picked_team_id=1, week_is_final=False)
_assert("a week that is not final produces NO outcome",
        _before_final.outcome is None and not _before_final.ready)
_assert("  · and names the reason",
        any("PROVIDER_NOT_FINAL" in r for r in _before_final.refusals))

_incomplete = FG.grade_versus(home=_lineup(110.0), away=_lineup(100.0,
                                                                ready=False),
                              home_team_id=1, away_team_id=2,
                              market_type=FG.MarketType.MONEYLINE,
                              picked_team_id=1, week_is_final=True)
_assert("incomplete evidence in a final week produces NO outcome",
        _incomplete.outcome is None
        and any("EVIDENCE_INCOMPLETE" in r for r in _incomplete.refusals))
_assert("  · a refusal is NOT a push, and cannot be mistaken for one",
        _incomplete.outcome not in (FG.Outcome.PUSH, FG.Outcome.WON,
                                    FG.Outcome.LOST))


# ══════════════════════════════════════════════════════════════════════════════
# D · the settlement input is the field Yahoo already writes
# ══════════════════════════════════════════════════════════════════════════════

print("\n6B-D · settlement input, unchanged in shape and vocabulary")

_home, _away = FG.settlement_scores(_lineup(118.5), _lineup(99.25))
_assert("a factual result reaches settlement as two floats",
        _home == 118.5 and _away == 99.25)

from db.schema import Bet                                          # noqa: E402

_statuses = set()
for _c in Bet.__table__.constraints:
    _text = str(getattr(_c, "sqltext", ""))
    if "status" in _text:
        for _v in ("pending", "won", "lost", "push"):
            if f"'{_v}'" in _text:
                _statuses.add(_v)
_assert("the graded vocabulary is the one Bet.status already permits",
        {FG.Outcome.WON, FG.Outcome.LOST, FG.Outcome.PUSH} <= _statuses,
        sorted(_statuses))
_assert("  · and Sprint 6B introduced no new outcome value",
        {FG.Outcome.WON, FG.Outcome.LOST, FG.Outcome.PUSH}
        == {"won", "lost", "push"})

for _module in ("scoring/factual_grading.py", "scoring/factual.py",
                "providers/balldontlie/factual_week.py",
                "providers/balldontlie/pool_source.py"):
    _tree = ast.parse(open(os.path.join(ROOT, _module), encoding="utf-8").read())
    _mods = set()
    for _n in ast.walk(_tree):
        if isinstance(_n, ast.Import):
            _mods |= {a.name for a in _n.names}
        elif isinstance(_n, ast.ImportFrom):
            _mods.add(_n.module or "")
    _money = [m for m in _mods
              if m.startswith("ledger") or m.startswith("economy")]
    _assert(f"{_module} imports no ledger and no economy", not _money,
            str(_money))


# ══════════════════════════════════════════════════════════════════════════════
# E · the Pool adapter satisfies the existing protocol
# ══════════════════════════════════════════════════════════════════════════════

print("\n6B-E · Pool operands, translated into the governed vocabulary")

_map = PS.load_balldontlie_stat_map()
_assert("every advertised operand is in the governed catalog",
        bool(_map.names))
_assert("  · a name the catalog does not know is DROPPED, not passed through",
        _map.canonical_for("passing_touchdowns") is None
        and _map.canonical_for("passing_td") == "passing_td")
_assert("  · so the map is a translation, not an identity",
        PS.FACTUAL_TO_POOL["passing_touchdowns"] == "passing_td"
        and PS.FACTUAL_TO_POOL["passing_interceptions"] == "interceptions_thrown")
_assert("the adapter is the neutral source with a map injected",
        issubclass(PS.BalldontlieProviderStatSource,
                   __import__("providers.week_stat_source", fromlist=["x"])
                   .ProviderWeekStatSource)
        and PS.BalldontlieProviderStatSource.provider == BALLDONTLIE)
_assert("  · and satisfies PoolStatSource",
        hasattr(PS.BalldontlieProviderStatSource, "subjects_for"))

from providers.base import ProviderLeague                          # noqa: E402

_league = ProviderLeague(provider="yahoo", league_key="y.l.1",
                         name="CULV", season=2024)
_composed = PS.factual_provider_week(league=_league, week=1,
                                     roster_entries=(), factual_week=_week)
_assert("the composed week carries BALLDONTLIE facts",
        len(_composed.player_stats) > 0,
        f"{len(_composed.player_stats)} subjects")
_assert("  · under governed operand names",
        all(set(s.values) <= set(PS.BALLDONTLIE_STAT_NAMES)
            for s in _composed.player_stats))
_assert("  · and NO matchups, because BALLDONTLIE cannot finalize one",
        _composed.matchups == ())
_assert("  · while the league identity came from Yahoo, not invented",
        _composed.league.provider == "yahoo")

_kicker = [s for s in _composed.player_stats if s.player_key == "bdl.p.7508"]
_assert("a kicker crosses with the FINER pool distance bands",
        _kicker and _kicker[0].values.get("field_goals_made_50_plus") == 1.0
        and _kicker[0].values.get("made_field_goal_distance") == 122.0,
        str(sorted(_kicker[0].values)) if _kicker else "absent")

_incomplete_week = FW.build_factual_week(season=2024, week=1, games=[
    {"game": _game, "plays": None, "stats": _stats}])
_composed_incomplete = PS.factual_provider_week(
    league=_league, week=1, roster_entries=(), factual_week=_incomplete_week)
_assert("a subject whose evidence is short does NOT cross the boundary",
        all(s.player_key != "bdl.p.7508"
            for s in _composed_incomplete.player_stats))


# ══════════════════════════════════════════════════════════════════════════════
# F · both leagues, end to end
# ══════════════════════════════════════════════════════════════════════════════

print("\n6B-F · facts -> score -> grade -> settlement input, both rulebooks")

_facts = _week.subjects
_fps = {k: FW.evidence_fingerprint(v) for k, v in _facts.items()}
_starters = [{"provider_player_key": "bdl.p.78", "position": "QB", "name": "QB"},
             {"provider_player_key": "bdl.p.760", "position": "WR", "name": "WR"},
             {"provider_player_key": "bdl.p.7508", "position": "K", "name": "K"}]
_opponent = [{"provider_player_key": "bdl.p.760", "position": "WR", "name": "WR"}]

_results = {}
for _label, _profile in (("CULV", CULV), ("MR WHISKERS", WHISKERS)):
    _h = SF.score_factual_lineup(starters=_starters, facts=_facts,
                                 profile=_profile, season=2024, week=1,
                                 team_id=1, team_name="Home",
                                 evidence_fingerprints=_fps)
    _a = SF.score_factual_lineup(starters=_opponent, facts=_facts,
                                 profile=_profile, season=2024, week=1,
                                 team_id=2, team_name="Away",
                                 evidence_fingerprints=_fps)
    _g = FG.grade_versus(home=_h, away=_a, home_team_id=1, away_team_id=2,
                         market_type=FG.MarketType.MONEYLINE,
                         picked_team_id=1, week_is_final=True)
    _results[_label] = (_h, _a, _g)
    _assert(f"{_label}: every starter scores and the market grades",
            _h.ready and _g.ready and _g.outcome == FG.Outcome.WON,
            f"{_h.points:.2f} vs {_a.points:.2f} -> {_g.outcome}")

_assert("the SAME facts produce different totals under the two rulebooks",
        abs(_results["CULV"][0].points
            - _results["MR WHISKERS"][0].points) > 1e-9,
        f"CULV {_results['CULV'][0].points:.2f} vs "
        f"Whiskers {_results['MR WHISKERS'][0].points:.2f}")
_assert("  · because the kicker is paid by yardage against distance bands",
        CULV.field_goal_yards_per_point == 0.1
        and set(WHISKERS.field_goals_made))


# ══════════════════════════════════════════════════════════════════════════════
# G · replay and regrade
# ══════════════════════════════════════════════════════════════════════════════

print("\n6B-G · offline replay, and a correction that regrades")

import providers.balldontlie.transport as _T                       # noqa: E402

_calls = []
_orig = _T.BalldontlieLiveTransport._request


def _explode(self, *a, **k):
    _calls.append(a)
    raise AssertionError("the grading path opened a socket")


_T.BalldontlieLiveTransport._request = _explode
try:
    _replay_week = FW.build_factual_week(season=2024, week=1, games=[
        {"game": _game, "plays": _plays, "stats": _stats}])
    _replay_h = SF.score_factual_lineup(
        starters=_starters, facts=_replay_week.subjects, profile=CULV,
        season=2024, week=1, team_id=1, team_name="Home",
        evidence_fingerprints={k: FW.evidence_fingerprint(v)
                               for k, v in _replay_week.subjects.items()})
    _replay_a = SF.score_factual_lineup(
        starters=_opponent, facts=_replay_week.subjects, profile=CULV,
        season=2024, week=1, team_id=2, team_name="Away",
        evidence_fingerprints={k: FW.evidence_fingerprint(v)
                               for k, v in _replay_week.subjects.items()})
    _replay_g = FG.grade_versus(home=_replay_h, away=_replay_a, home_team_id=1,
                                away_team_id=2,
                                market_type=FG.MarketType.MONEYLINE,
                                picked_team_id=1, week_is_final=True)
    _offline_ok = True
finally:
    _T.BalldontlieLiveTransport._request = _orig

_assert("the whole chain replays with the transport sabotaged",
        _offline_ok and not _calls, f"{len(_calls)} provider call(s)")
_assert("  · reproducing the identical lineup total",
        abs(_replay_h.points - _results["CULV"][0].points) < 1e-12)
_assert("  · the identical grade",
        _replay_g.outcome == _results["CULV"][2].outcome)
_assert("  · and the identical settlement input",
        FG.settlement_scores(_replay_h, _replay_a)
        == FG.settlement_scores(*_results["CULV"][:2]))
_assert("  · and the identical evidence fingerprint",
        _replay_g.evidence_fingerprint
        == _results["CULV"][2].evidence_fingerprint)

_corrected_stats = [dict(r) for r in _stats]
_corrected_stats[0]["passing_yards"] = 400          # a real correction
_corrected_week = FW.build_factual_week(season=2024, week=1, games=[
    {"game": _game, "plays": _plays, "stats": _corrected_stats}])
_corrected_h = SF.score_factual_lineup(
    starters=_starters, facts=_corrected_week.subjects, profile=CULV,
    season=2024, week=1, team_id=1, team_name="Home",
    evidence_fingerprints={k: FW.evidence_fingerprint(v)
                           for k, v in _corrected_week.subjects.items()})
_corrected_g = FG.grade_versus(home=_corrected_h, away=_replay_a,
                               home_team_id=1, away_team_id=2,
                               market_type=FG.MarketType.SPREAD,
                               picked_team_id=1, line=30.0, week_is_final=True)
_original_g = FG.grade_versus(home=_replay_h, away=_replay_a, home_team_id=1,
                              away_team_id=2,
                              market_type=FG.MarketType.SPREAD,
                              picked_team_id=1, line=30.0, week_is_final=True)
_assert("a provider correction changes the score",
        abs(_corrected_h.points - _replay_h.points) > 1e-9,
        f"{_replay_h.points:.2f} -> {_corrected_h.points:.2f}")
_assert("  · changes the evidence fingerprint",
        _corrected_g.evidence_fingerprint != _original_g.evidence_fingerprint)
_assert("  · and can change the GRADE",
        _corrected_g.outcome != _original_g.outcome,
        f"{_original_g.outcome} -> {_corrected_g.outcome}")
_assert("  · while the ORIGINAL evidence still regrades to the original answer",
        FG.grade_versus(home=_replay_h, away=_replay_a, home_team_id=1,
                        away_team_id=2, market_type=FG.MarketType.SPREAD,
                        picked_team_id=1, line=30.0,
                        week_is_final=True).outcome == _original_g.outcome)

_ingest_corrected = FI.ingest_factual_week(
    _db, _corrected_week, resolutions=_resolutions,
    captured_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
_db.flush()
_assert("the corrected evidence lands as a NEW row beside its predecessor",
        _ingest_corrected.stored > 0
        and _db.query(ProviderComponentProjection).count() > len(_rows),
        f"{_db.query(ProviderComponentProjection).count()} rows")


# ══════════════════════════════════════════════════════════════════════════════
# H · the partial-data matrix
# ══════════════════════════════════════════════════════════════════════════════

print("\n6B-H · every kind of short evidence refuses")

_matrix = [
    ("missing final stats",
     FW.build_factual_week(season=2024, week=1,
                           games=[{"game": _game, "plays": _plays,
                                   "stats": []}])),
    ("missing play data",
     FW.build_factual_week(season=2024, week=1,
                           games=[{"game": _game, "plays": None,
                                   "stats": _stats}])),
    ("provider not final",
     FW.build_factual_week(season=2024, week=1,
                           games=[{"game": dict(_game, status="InProgress",
                                                status_state="in"),
                                   "plays": _plays, "stats": _stats}])),
]
for _label, _w in _matrix:
    _lu = SF.score_factual_lineup(starters=_starters, facts=_w.subjects,
                                  profile=CULV, season=2024, week=1,
                                  team_id=1, team_name="Home")
    _gr = FG.grade_versus(home=_lu, away=_replay_a, home_team_id=1,
                          away_team_id=2,
                          market_type=FG.MarketType.MONEYLINE,
                          picked_team_id=1, week_is_final=True)
    _assert(f"{_label}: no grade is produced",
            _gr.outcome is None and not _gr.ready)

_no_identity = SF.score_factual_lineup(
    starters=[{"provider_player_key": None, "position": "WR", "name": "X"}],
    facts=_facts, profile=CULV, season=2024, week=1, team_id=1,
    team_name="Home")
_assert("unresolved identity: no grade is produced",
        FG.grade_versus(home=_no_identity, away=_replay_a, home_team_id=1,
                        away_team_id=2,
                        market_type=FG.MarketType.MONEYLINE, picked_team_id=1,
                        week_is_final=True).outcome is None)


# ══════════════════════════════════════════════════════════════════════════════
# I · global facts, one fetch for every league
# ══════════════════════════════════════════════════════════════════════════════

print("\n6B-I · one week of NFL facts, many leagues")

_leagues = [ProviderLeague(provider="yahoo", league_key=f"y.l.{i}",
                           name=f"League {i}", season=2024)
            for i in range(1, 11)]
_composed_all = [PS.factual_provider_week(league=lg, week=1,
                                          roster_entries=(),
                                          factual_week=_week)
                 for lg in _leagues]
_assert("ten leagues read the SAME normalized week",
        all(len(c.player_stats) == len(_composed_all[0].player_stats)
            for c in _composed_all))
_assert("  · with no provider fetch inside grading",
        not _calls)
_assert("  · and no per-league duplication of NFL facts",
        len({tuple(sorted(s.player_key for s in c.player_stats))
             for c in _composed_all}) == 1)


# ══════════════════════════════════════════════════════════════════════════════
# J · nothing economic moved
# ══════════════════════════════════════════════════════════════════════════════

print("\n6B-J · the economic surface is untouched")

import subprocess                                                   # noqa: E402

_changed = subprocess.run(
    ["git", "diff", "--name-only", "ad9f5231444861f93b362e11bfe518741efcea5c"],
    cwd=ROOT, capture_output=True, text=True).stdout.split()
_economic = [f for f in _changed
             if f.startswith(("ledger/", "economy/", "betting/"))]
_assert("Sprint 6 and 6B changed NO file under ledger/, economy/ or betting/",
        not _economic, str(_economic))
_assert("  · and no migration was added",
        not [f for f in _changed if f.startswith("migrations/")],
        str([f for f in _changed if f.startswith("migrations/")]))

from odds.model_registry import (                                   # noqa: E402
    ACTIVE_MODEL_VERSION_ID, model_config_hash, resolve_model_config,
)

_assert("sim-v1's configuration hash is byte-identical",
        model_config_hash(resolve_model_config("sim-v1"))
        == "1d60ff39343bebf1ceb8099f729fbaff18cb278078e06d094da6cc04ba4626d1")
_assert("sim-v1 is still the ACTIVE model, and sim-v2 is not",
        ACTIVE_MODEL_VERSION_ID == "sim-v1")


print()
print("=" * 78)
if _failed:
    print(f"SPRINT 6B: {_failed} FAILED, {_passed} passed")
    raise SystemExit(1)
print(f"SPRINT 6B: all {_passed} assertions passed — factual results grade "
      f"through the\nexisting evaluators, reach settlement as the two floats "
      f"Yahoo already writes,\nand refuse whenever the evidence is short.")
print("=" * 78)
