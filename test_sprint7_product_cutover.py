"""SPRINT 7 · per-league provider cutover, through the real app seams.

WHAT SPRINT 7 IS FOR. Six sprints built a BALLDONTLIE pipeline and certified
every piece of it. None of it was reachable from the running product: grep the
tree outside `test_*` and nothing imports `odds/sim_v2.py`, `scoring/csps.py`,
`scoring/factual.py` or `providers/balldontlie/*`. The live odds path is
`beefs/beef_engine.compute_market_board` reading scalar `Projection` rows under
`MODEL_V1`, exactly as before. This sprint makes the pipeline reachable — one
league at a time, by explicit configuration, with everything else untouched.

── THE SHAPE OF THE CUTOVER ────────────────────────────────────────────────

    league_provider_config     one row per league-season, three independent
                               axes, closed vocabularies, ABSENCE = today

    providers/selection.py     the single place that answers "who answers for
                               this league", and the only place that may

    _provider_stat_source      the one existing provider dispatch seam in
                               api/main.py, which now has a third branch

Nothing else in the app learned a provider name.

── WHAT "NO SILENT FALLBACK" COSTS, AND WHY IT IS WORTH IT ─────────────────

A league configured for BALLDONTLIE facts whose facts have not been ingested
does NOT get Yahoo's numbers. It raises. That is deliberately less convenient
than a fallback and deliberately safer: a Pool graded on evidence the operator
did not choose is wrong even when every subject resolves, and it is wrong
invisibly, with a confident number attached. The refusal is loud and names the
league, the season and the week.

OFFLINE AND DETERMINISTIC. In-memory SQLite, captured fixtures, no network.
"""

from __future__ import annotations

import ast
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone                            # noqa: E402

from sqlalchemy import create_engine, inspect                      # noqa: E402
from sqlalchemy.orm import sessionmaker                            # noqa: E402

from db.schema import (                                            # noqa: E402
    Base, League, LeagueProviderConfig, Player,
    ProviderComponentProjection,
)
from providers import selection as SEL                             # noqa: E402
from providers.balldontlie import factual_ingest as FI             # noqa: E402
from providers.balldontlie import factual_week as FW               # noqa: E402
from providers.balldontlie import parse as P                       # noqa: E402
from providers.balldontlie import pool_source as PS                # noqa: E402
from providers.cross_identity import (                             # noqa: E402
    BALLDONTLIE, CanonicalSubject, CrossProviderResolution, Outcome as IdOut,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
CAPTURED = os.path.join(ROOT, "providers", "fixtures", "balldontlie",
                        "plays__game_id-7005__per_page-100__CAPTURED.json")
SEASON, WEEK = 2024, 1

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
print("SPRINT 7 · PRODUCT WIRING AND CONTROLLED CUTOVER")
print("=" * 78)

_db = _session()
_control = League(name="Control League", provider="yahoo", season=SEASON,
                  provider_league_key="y.l.control")
_staging = League(name="Staging League", provider="yahoo", season=SEASON,
                  provider_league_key="y.l.staging")
_db.add_all([_control, _staging])
_db.flush()


# ══════════════════════════════════════════════════════════════════════════════
# A · absence is the default, and the default is today
# ══════════════════════════════════════════════════════════════════════════════

print("\n7-A · a league nobody configured behaves exactly as it did")

_c = SEL.resolve(_db, league_id=_control.id, season=SEASON)
_assert("an unconfigured league resolves to legacy on every axis",
        (_c.projection_source, _c.factual_source, _c.simulation_model)
        == ("legacy", "legacy", "sim-v1"),
        f"{_c.projection_source}/{_c.factual_source}/{_c.simulation_model}")
_assert("  · and knows it was never configured", not _c.configured)
_assert("  · resolving it does not CREATE a row",
        _db.query(LeagueProviderConfig).count() == 0)
_assert("  · nothing auto-detects from a credential or a snapshot existing",
        SEL.resolve(_db, league_id=_control.id,
                    season=SEASON).projection_source == "legacy")

_assert("the legacy scalar selector is untouched and still chooses the feed",
        _control.projection_source == "fantasypros",
        _control.projection_source)


# ══════════════════════════════════════════════════════════════════════════════
# B · activation is one explicit row
# ══════════════════════════════════════════════════════════════════════════════

print("\n7-B · one league moves, and only that league")

_s = SEL.set_selection(_db, league_id=_staging.id, season=SEASON,
                       projection_source="balldontlie",
                       factual_source="balldontlie",
                       simulation_model="sim-v2",
                       note="Sprint 7 staging cutover", updated_by="operator")
_db.flush()
_assert("the staging league takes BALLDONTLIE and sim-v2",
        (_s.projection_source, _s.factual_source, _s.simulation_model)
        == ("balldontlie", "balldontlie", "sim-v2"))
_assert("  · and the control league is completely unaffected",
        SEL.resolve(_db, league_id=_control.id,
                    season=SEASON).simulation_model == "sim-v1")
_assert("BOTH remain Yahoo leagues — League.provider never moves",
        _control.provider == "yahoo" and _staging.provider == "yahoo")
_assert("  · because who HOSTS a league and who supplies the FOOTBALL are "
        "different questions",
        _staging.provider == "yahoo" and _s.factual_source == "balldontlie")

_assert("the two leagues resolve different frozen models in one process",
        SEL.resolve_model_version(_s).model_version_id == "sim-v2"
        and SEL.resolve_model_version(_c).model_version_id == "sim-v1")

# THE VOCABULARY IS CLOSED AT THE ENGINE, NOT IN PYTHON.
_bad = _session()
_bl = League(name="X", provider="yahoo", season=SEASON)
_bad.add(_bl)
_bad.flush()
try:
    _bad.add(LeagueProviderConfig(league_id=_bl.id, season=SEASON,
                                  projection_source="auto",
                                  factual_source="legacy",
                                  simulation_model="sim-v1"))
    _bad.flush()
    _rejected = False
except Exception:
    _bad.rollback()
    _rejected = True
_assert("an ambiguous source like 'auto' cannot be STORED at all", _rejected)
_assert("  · so a misconfiguration fails at write, where an operator is "
        "watching, not at read time in a settlement run", _rejected)


# ══════════════════════════════════════════════════════════════════════════════
# C · no silent fallback, in either direction
# ══════════════════════════════════════════════════════════════════════════════

print("\n7-C · a provider the operator did not choose is refused")

for _sel, _offered, _what in ((_s, "legacy", "projection"),
                              (_c, "balldontlie", "projection")):
    try:
        SEL.require_projection_source(_sel, _offered)
        _ok = False
    except SEL.ProviderSelectionError:
        _ok = True
    _assert(f"a {_sel.projection_source!r} league refuses {_offered!r} "
            f"{_what}s", _ok)

for _sel, _offered in ((_s, "legacy"), (_c, "balldontlie")):
    try:
        SEL.require_factual_source(_sel, _offered)
        _ok = False
    except SEL.ProviderSelectionError:
        _ok = True
    _assert(f"a {_sel.factual_source!r} league refuses {_offered!r} facts", _ok)

try:
    SEL.require_factual_source(_s, "legacy")
    _message = ""
except SEL.ProviderSelectionError as _exc:
    _message = str(_exc)
_assert("the refusal names the league, the season and BOTH providers",
        str(_staging.id) in _message and "balldontlie" in _message
        and "legacy" in _message, _message[:78])
_assert("  · and says why a substitute is not acceptable",
        "not interchangeable" in _message or "cannot be" in _message)


# ══════════════════════════════════════════════════════════════════════════════
# D · the real app seam dispatches on the row
# ══════════════════════════════════════════════════════════════════════════════

print("\n7-D · api.main._provider_stat_source takes the third branch")

import api.main as APP                                             # noqa: E402

_src = ast.parse(open(os.path.join(ROOT, "api", "main.py"),
                      encoding="utf-8").read())
_fn = next(n for n in ast.walk(_src)
           if isinstance(n, ast.FunctionDef) and n.name == "_provider_stat_source")
_body = ast.dump(_fn)
_assert("the seam consults the Sprint 7 selection",
        "resolve_selection" in _body or "selection" in _body)
_assert("  · and still has its Demo branch",
        "DEMO_PROVIDER" in _body)
_assert("  · and still has its Yahoo branch",
        "bind_pool_stat_source" in _body)
_assert("there is exactly ONE provider dispatch seam for pool stats",
        sum(1 for n in ast.walk(_src)
            if isinstance(n, ast.FunctionDef)
            and n.name == "_provider_stat_source") == 1)

# THE SEAM'S REFUSAL, EXERCISED THROUGH THE REAL HELPER.
_empty = _session()
_el = League(name="Empty", provider="yahoo", season=SEASON,
             provider_league_key="y.l.empty")
_empty.add(_el)
_empty.flush()
SEL.set_selection(_empty, league_id=_el.id, season=SEASON,
                  factual_source="balldontlie")
_empty.flush()


class _Snap:
    """The parts of a ProviderWeek the composer reads."""

    def __init__(self):
        from providers.base import ProviderLeague
        self.league = ProviderLeague(provider="yahoo", league_key="y.l.empty",
                                     name="Empty", season=SEASON)
        self.week = WEEK
        self.roster_entries = ()
        self.observed_at = None


try:
    PS.factual_week_from_components(
        _empty, league=_Snap().league, week=WEEK, season=SEASON,
        roster_entries=(), observed_at=None)
    _refused_empty = False
    _empty_msg = ""
except LookupError as _exc:
    _refused_empty = True
    _empty_msg = str(_exc)
_assert("a BALLDONTLIE league with NO persisted facts REFUSES rather than "
        "falling back", _refused_empty)
_assert("  · and the refusal says no other provider's numbers substitute",
        "fallback" in _empty_msg or "did not choose" in _empty_msg,
        _empty_msg[:78])


# ══════════════════════════════════════════════════════════════════════════════
# E · facts ingested once serve every league
# ══════════════════════════════════════════════════════════════════════════════

print("\n7-E · NFL facts are global; leagues read, they do not fetch")

_plays = P.parse_plays(json.load(open(CAPTURED, encoding="utf-8")))
_game = {"id": 7005, "status": "Final", "status_state": "final",
         "home_team": {"abbreviation": "CHI"},
         "visitor_team": {"abbreviation": "TEN"},
         "home_team_score": 24, "visitor_team_score": 17,
         "week": WEEK, "season": SEASON}
_stats = [
    {"player": {"id": 78, "position_abbreviation": "QB"},
     "team": {"abbreviation": "TEN"}, "game": {"id": 7005},
     "passing_yards": 250, "passing_touchdowns": 2, "passing_interceptions": 2},
    {"player": {"id": 760, "position_abbreviation": "WR"},
     "team": {"abbreviation": "CHI"}, "game": {"id": 7005},
     "receptions": 6, "receiving_yards": 88, "receiving_touchdowns": 1},
]
_week = FW.build_factual_week(season=SEASON, week=WEEK,
                             games=[{"game": _game, "plays": _plays,
                                     "stats": _stats}])

_resolutions = {}
for _key, _subject in _week.subjects.items():
    if _subject.diagnostics:
        continue
    _p = Player(name=_key, position=_subject.position or "WR",
                nfl_team=_subject.nfl_team or "CHI")
    _db.add(_p)
    _db.flush()
    _resolutions[_key] = CrossProviderResolution(
        outcome=IdOut.RESOLVED, provider=BALLDONTLIE,
        canonical=CanonicalSubject(player_id=_p.id, name=_key,
                                   position=_subject.position,
                                   nfl_team=_subject.nfl_team),
        provider_player_key=_key, method="normalized_discovery")

_report = FI.ingest_factual_week(_db, _week, resolutions=_resolutions,
                                 captured_at=datetime(2026, 1, 5,
                                                      tzinfo=timezone.utc))
_db.flush()
_assert("one ingest persists the week's facts once",
        _report.stored > 0, f"{_report.stored} subjects")
_rows_after_one = _db.query(ProviderComponentProjection).count()

_extra = [League(name=f"League {i}", provider="yahoo", season=SEASON,
                 provider_league_key=f"y.l.{i}") for i in range(3, 13)]
_db.add_all(_extra)
_db.flush()
for _lg in _extra:
    SEL.set_selection(_db, league_id=_lg.id, season=SEASON,
                      factual_source="balldontlie")
_db.flush()
_assert("ten more leagues activate and store NOT ONE extra fact row",
        _db.query(ProviderComponentProjection).count() == _rows_after_one,
        f"{_rows_after_one} rows before, "
        f"{_db.query(ProviderComponentProjection).count()} after")
_assert("  · because NFL facts are a property of the NFL, not of a league",
        _db.query(LeagueProviderConfig).count() == 11)


# ══════════════════════════════════════════════════════════════════════════════
# F · rollback changes a selection, never a history
# ══════════════════════════════════════════════════════════════════════════════

print("\n7-F · rollback")

_before = _db.query(ProviderComponentProjection).count()
_rolled = SEL.set_selection(_db, league_id=_staging.id, season=SEASON,
                            projection_source="legacy",
                            factual_source="legacy",
                            simulation_model="sim-v1",
                            note="rolled back", updated_by="operator")
_db.flush()
_assert("a rolled-back league is on legacy behaviour again",
        (_rolled.projection_source, _rolled.factual_source,
         _rolled.simulation_model) == ("legacy", "legacy", "sim-v1"))
_assert("  · and every BALLDONTLIE fact it produced is still there",
        _db.query(ProviderComponentProjection).count() == _before,
        f"{_before} rows")
_assert("  · so the league can be moved forward again without re-ingesting",
        SEL.set_selection(_db, league_id=_staging.id, season=SEASON,
                          factual_source="balldontlie").factual_source
        == "balldontlie")
_assert("rollback is an UPDATE of one row, not a deletion of anything",
        _db.query(LeagueProviderConfig).filter_by(
            league_id=_staging.id).count() == 1)


# ══════════════════════════════════════════════════════════════════════════════
# G · restart safety
# ══════════════════════════════════════════════════════════════════════════════

print("\n7-G · the selection survives a restart because it is a row")

_db.commit()
_reopened = sessionmaker(bind=_db.get_bind())()
_after_restart = SEL.resolve(_reopened, league_id=_staging.id, season=SEASON)
_assert("a fresh session reads the same selection",
        _after_restart.factual_source == "balldontlie"
        and _after_restart.configured)
_assert("  · and the control league is still legacy",
        SEL.resolve(_reopened, league_id=_control.id,
                    season=SEASON).simulation_model == "sim-v1")
_assert("  · with no in-memory provider state anywhere in the resolver",
        not any(isinstance(v, dict) and "cache" in n.lower()
                for n, v in vars(SEL).items()))


# ══════════════════════════════════════════════════════════════════════════════
# G2 · the settlement INPUT path, through the real functions
# ══════════════════════════════════════════════════════════════════════════════

print("\n7-G2 · what settlement reads is what BALLDONTLIE produced")

from betting.settlement_engine import (                             # noqa: E402
    _eval_over_under, _eval_spread, _team_score_for_week,
)
from db.schema import Matchup, Team                                 # noqa: E402
from scoring import factual_grading as FG                           # noqa: E402

_sdb = _session()
_sl = League(name="Settle", provider="yahoo", season=SEASON,
             provider_league_key="y.l.settle")
_sdb.add(_sl)
_sdb.flush()
_home = Team(team_name="Home", owner="A", email="a@example.test",
             league_id=_sl.id)
_away = Team(team_name="Away", owner="B", email="b@example.test",
             league_id=_sl.id)
_sdb.add_all([_home, _away])
_sdb.flush()

# The FantasyStakes factual totals a BALLDONTLIE week produced.
_HOME_TOTAL, _AWAY_TOTAL = 118.5, 99.25
_m = Matchup(league_id=_sl.id, week=WEEK, home_team_id=_home.id,
             away_team_id=_away.id,
             home_score=_HOME_TOTAL, away_score=_AWAY_TOTAL,
             winner_team_id=_home.id)
_sdb.add(_m)
_sdb.flush()

_assert("the function every Versus market grades through reads the factual "
        "total", _team_score_for_week(_home.id, WEEK, _sdb) == _HOME_TOTAL,
        str(_team_score_for_week(_home.id, WEEK, _sdb)))
_assert("  · for both sides",
        _team_score_for_week(_away.id, WEEK, _sdb) == _AWAY_TOTAL)
_assert("  · so settlement needs no new field, table or enum to see them",
        _m.home_score == _HOME_TOTAL and _m.away_score == _AWAY_TOTAL)


class _BetShim:
    def __init__(self, picked, line=None, side=None):
        self.picked_team_id = picked
        self.line = line
        self.side = side


_assert("the REAL spread evaluator grades the factual margin",
        _eval_spread(_BetShim(_home.id, line=7.0), _m) is True
        and _eval_spread(_BetShim(_home.id, line=25.0), _m) is False)
_assert("the REAL total evaluator grades the factual combined score",
        _eval_over_under(_BetShim(None, line=200.0, side="over"), _m) is True
        and _eval_over_under(_BetShim(None, line=250.0, side="over"), _m)
        is False)

_adapter = FG.settlement_scores(
    type("L", (), {"points": _HOME_TOTAL})(),
    type("L", (), {"points": _AWAY_TOTAL})())
_assert("the Sprint 6B adapter emits exactly those two numbers",
        _adapter == (_HOME_TOTAL, _AWAY_TOTAL), str(_adapter))
_assert("  · so the provider changed and settlement cannot tell",
        _team_score_for_week(_home.id, WEEK, _sdb) == _adapter[0])

# THE SOLE WRITER IS STILL THE SOLE WRITER.
import re                                                           # noqa: E402

#: `<holder>.home_score = value` — an assignment, with `==` excluded.
_ASSIGN = re.compile(r"(\w+)\.(?:home|away)_score\s*=(?!=)")
#: Holders that are demonstrably not a `Matchup` row.
_NON_MATCHUP_HOLDERS = {"grade"}
_writers = []
for _dirpath, _dirnames, _files in os.walk(ROOT):
    if any(skip in _dirpath for skip in
           ("fantasy-beefs-season-close", ".git", "__pycache__", "migrations")):
        continue
    for _f in _files:
        if not _f.endswith(".py") or _f.startswith("test_"):
            continue
        _path = os.path.join(_dirpath, _f)
        try:
            _src_text = open(_path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        # A REAL ASSIGNMENT, NOT A COMPARISON. `m.home_score == m.away_score`
        # contains the same characters and is a read; and an assignment onto a
        # local dataclass (`grade.home_score = ...`) is not a Matchup write.
        for _match in _ASSIGN.finditer(_src_text):
            if _match.group(1) not in _NON_MATCHUP_HOLDERS:
                _writers.append(os.path.relpath(_path, ROOT))
                break
_ALLOWED = {os.path.join("providers", "persist.py"),
            os.path.join("demo", "states.py")}
_assert("Sprint 7 added NO new writer of Matchup.home_score",
        not (set(_writers) - _ALLOWED), str(sorted(set(_writers) - _ALLOWED)))


# ══════════════════════════════════════════════════════════════════════════════
# H · the frozen things, and the economic surface
# ══════════════════════════════════════════════════════════════════════════════

print("\n7-H · nothing frozen moved and no economics were touched")

from odds.model_registry import (                                   # noqa: E402
    ACTIVE_MODEL_VERSION_ID, model_config_hash, resolve_model_config,
)

_SIM_V1 = "1d60ff39343bebf1ceb8099f729fbaff18cb278078e06d094da6cc04ba4626d1"
_assert("sim-v1's configuration hash is byte-identical",
        model_config_hash(resolve_model_config("sim-v1")) == _SIM_V1)
_assert("the GLOBAL default is still sim-v1 — activation is per league",
        ACTIVE_MODEL_VERSION_ID == "sim-v1", ACTIVE_MODEL_VERSION_ID)
_assert("  · so an unconfigured league prices exactly as it did yesterday",
        SEL.resolve_model_version(
            SEL.LEGACY()).model_version_id == "sim-v1")

_tree = ast.parse(open(os.path.join(ROOT, "providers", "selection.py"),
                       encoding="utf-8").read())
_mods = set()
for _n in ast.walk(_tree):
    if isinstance(_n, ast.Import):
        _mods |= {a.name for a in _n.names}
    elif isinstance(_n, ast.ImportFrom):
        _mods.add(_n.module or "")
_assert("the selector imports no ledger, economy or betting module",
        not [m for m in _mods
             if m.startswith(("ledger", "economy", "betting"))], str(_mods))

import subprocess                                                   # noqa: E402

_changed = subprocess.run(
    ["git", "diff", "--name-only",
     "12ce3128553df5bcda3059fdccfdcdebfe2e2bf8"],
    cwd=ROOT, capture_output=True, text=True).stdout.split()
_economic = [f for f in _changed
             if f.startswith(("ledger/", "economy/", "betting/"))]
_assert("Sprint 7 changed NO file under ledger/, economy/ or betting/",
        not _economic, str(_economic))


# ══════════════════════════════════════════════════════════════════════════════
# H2 · an operator can see which provider answered
# ══════════════════════════════════════════════════════════════════════════════

print("\n7-H2 · diagnostics report the effective selection, never a secret")

# Section F left this league mid-rollback on purpose; restate the selection so
# this section describes a known state rather than inheriting one.
SEL.set_selection(_db, league_id=_staging.id, season=SEASON,
                  projection_source="balldontlie",
                  factual_source="balldontlie",
                  simulation_model="sim-v2")
_db.flush()
_fields = APP._selection_fields(_db, _staging)
_assert("the provider status reports the effective selection",
        _fields["factual_source"] == "balldontlie"
        and _fields["simulation_model"] == "sim-v2", str(_fields))
_assert("  · and says the selection was explicitly configured",
        _fields["selection_configured"] is True)
_ctrl_fields = APP._selection_fields(_db, _control)
_assert("  · while an unconfigured league reports legacy AND says so",
        _ctrl_fields["factual_source"] == "legacy"
        and _ctrl_fields["selection_configured"] is False)
# SPRINT 7B WIDENED THIS SET, AND THE ASSERTION WIDENED WITH IT RATHER THAN
# LOOSENING. The claim was never "there are exactly four keys" — it was that an
# unconfigured league answers EVERY question the diagnostic can be asked, so an
# absent row reads as a governed default instead of a missing answer. Sprint 7B
# added three more questions (which scoring profile, can this configuration
# price, and if not why), so the set is stated in full again.
_assert("  · so an absent row reads as a governed default, not a missing answer",
        set(_ctrl_fields) == {"projection_source", "factual_source",
                              "simulation_model", "selection_configured",
                              "scoring_profile_id", "pricing_ready",
                              "pricing_blocked_reason"})

_assert("the model exposes the selection to operators",
        {"projection_source", "factual_source", "simulation_model",
         "selection_configured"} <= set(APP.ProviderStatusOut.model_fields))
_assert("NO credential, key or header is in the diagnostic",
        not any(k in json.dumps(_fields).lower()
                for k in ("key", "token", "authorization", "secret",
                          "password")), json.dumps(_fields))

# THE DIAGNOSTIC MUST SURVIVE A DATABASE THAT HAS NOT MIGRATED YET.
class _Unmigrated:
    id = 999
    season = SEASON

    def __getattr__(self, name):
        raise RuntimeError("no such table: league_provider_config")


_unmigrated_db = _session()
from db.schema import LeagueProviderConfig as _LPC                  # noqa: E402

_LPC.__table__.drop(_unmigrated_db.get_bind())
_fallback = APP._selection_fields(_unmigrated_db, _control)
_assert("a database without the table still answers, with the defaults",
        _fallback["selection_configured"] is False
        and _fallback["simulation_model"] == "sim-v1", str(_fallback))
_assert("  · because a diagnostic that 500s is useless exactly when needed",
        _fallback["factual_source"] == "legacy")


# ══════════════════════════════════════════════════════════════════════════════
# I · the migration is additive and inert
# ══════════════════════════════════════════════════════════════════════════════

print("\n7-I · creating the table changes nothing by itself")

from migrations import add_league_provider_config as MIG            # noqa: E402
from migrations.manifest import identifiers                         # noqa: E402

# THE RUNNER'S INTERFACE, EXERCISED THE WAY THE RUNNER USES IT: it sets
# `module.engine` and calls `upgrade()`. A migration that exposes some other
# shape is registered, reported as pending, and then fails the release — which
# is exactly what happened the first time this one was written.
_fresh = create_engine("sqlite:///:memory:")
Base.metadata.create_all(_fresh)
_original_engine = MIG.engine
try:
    MIG.engine = _fresh
    _first = MIG.upgrade()
    _second = MIG.upgrade()
finally:
    MIG.engine = _original_engine
_cols = [c["name"] for c in inspect(_fresh).get_columns("league_provider_config")]
_assert("the migration exposes the interface the runner calls",
        callable(getattr(MIG, "upgrade", None)) and hasattr(MIG, "engine"))
_assert("  · applying it twice is a no-op",
        "already exists" in " ".join(_second), str(_second))
_assert("  · and it is registered as the manifest head",
        identifiers()[-1] == "0017_league_provider_config", identifiers()[-1])
_assert("  · it writes NO row, so no league's behaviour changes by migrating",
        "projection_source" in _cols
        and sessionmaker(bind=_fresh)().query(LeagueProviderConfig).count() == 0)


print()
print("=" * 78)
if _failed:
    print(f"SPRINT 7: {_failed} FAILED, {_passed} passed")
    raise SystemExit(1)
print(f"SPRINT 7: all {_passed} assertions passed — one league moved, every "
      f"other league\nuntouched, and no provider substitutes for another in "
      f"either direction.")
print("=" * 78)
