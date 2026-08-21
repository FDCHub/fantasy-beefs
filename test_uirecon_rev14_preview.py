#!/usr/bin/env python3
"""
test_uirecon_rev14_preview.py — UIRECON Rev 1.4 Lane C · the Matchup Preview
becomes a comparison, and learns what the week has actually scored.

Run:  python test_uirecon_rev14_preview.py

WHAT LANE C DID.

  L1 · TWO LINEUPS ON ONE SCREEN IS NOT A COMPARISON. Wave 4A gave LINEUPS real
       data and drew it as two independent `lineupTable()` calls stacked one
       above the other. Every figure in them was true and the panel still made
       the one judgement it exists for the hardest thing on it: the quarterback
       a GM was weighing sat nine rows above the quarterback it was being
       weighed against, and at 320px the pair was never on screen together.

       The two teams are now COLUMNS of one matrix keyed by roster position, so
       row N is the same slot on both sides at every certified viewport from
       320px up. §1 and §2 below check that the surface BUILDS that pairing —
       one function draws both cells, and neither can carry a figure the other
       cannot — and the browser tier measures that the two columns really do
       sit on the same row at different x.

  L2 · A FORECAST WITH NO SCOREBOARD BESIDE IT. The preview could say what a
       starter was PROJECTED to score and nothing about what it HAD scored, so
       a GM deciding on Sunday afternoon was reading a Thursday number.

       The data was never missing — which is the same finding Wave 4A made one
       layer up. Every provider in this repository already publishes weekly
       fantasy points per player on `ProviderPlayerStats.fantasy_points`, the
       DTO `providers/week_stat_source.py` has settled Prop Pools from since
       WP2. `providers/live_scoring.py` is the reader that was missing between
       that field and the surface.

WHAT THIS SUITE WILL NOT LET PASS.

  A NUMBER NO PROVIDER STATED. §4 is the whole reason this file exists. A
  starter its provider has said nothing about must reach the pixel as an em
  dash and never as 0.0 — the two claims are "this game has not kicked off" and
  "this player took the field and scored nothing", and only one of them is true
  before Sunday. §4 proves the absence survives every hop: the DTO reader, the
  internal-id resolution, the read model, the response model and the renderer.

  A STALE PROJECTION WEARING A LIVE LABEL. §3 proves the two figures come from
  two different served fields and that neither is derived from the other.

  A DEMO THAT MOVES BETWEEN SHOWINGS. §5 reads the same Demo league-week twice
  and requires byte-equal figures, which is WP2 §12 restated for this surface.

  A READ PATH THAT WRITES. Lane C is read-only with respect to economics. §6
  reads the two modules it added or changed for any mutation at all.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")

from test_support_s7_harness import ensure_authenticated_app  # noqa: E402

# THE BROWSER TIER NEEDS A PRICED PAIRING, for the reason Wave 4's suite states:
# an unseeded league refuses every quote, and a preview measured against a
# refusal certifies the graceful-degradation path while claiming to certify the
# served one. The comparison matrix only exists in the SERVED branch.
ensure_authenticated_app(seed_pool_slate=True, action_shape="full",
                         seed_priceable_versus=True)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _without_comments(source: str) -> str:
    """The code, with its prose removed.

    The same trap Wave 1 documented: an absence check that scans raw source
    matches the comment explaining why the thing is absent, so the guard passes
    only for as long as nobody documents it. Both JS comment forms and the
    Python `#` form are stripped.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    source = re.sub(r"^\s*//.*$", "", source, flags=re.M)
    return re.sub(r"^\s*#.*$", "", source, flags=re.M)


def _code_only(source: str) -> str:
    """Python source with its comments AND its docstrings removed.

    A module docstring is not a comment, so a "this module never calls X" guard
    would otherwise be defeated by the paragraph explaining why it never calls
    X. Triple-quoted strings go first so the `#` pass cannot chew a `#` living
    inside prose.
    """
    source = re.sub(r'""".*?"""', "", source, flags=re.S)
    source = re.sub(r"'''.*?'''", "", source, flags=re.S)
    return re.sub(r"^\s*#.*$", "", source, flags=re.M)


# ── §1 · The surface builds a comparison, not two stacked lineups ────────────

_section("§1 · §L1 LINEUPS is a matrix keyed by roster position")

_prev_js = _without_comments(_read("web", "js", "preview.js"))

_assert("a comparison matrix is constructed",
        "function comparisonMatrix(" in _prev_js)
_assert("the matrix is keyed by roster position",
        "function positionKey(" in _prev_js
        and 'class="fs-cmp__pos"' in _prev_js)
_assert("the served branch draws the matrix",
        "comparisonMatrix({" in _prev_js)

# THE STACKED PAIR IS GONE, not merely unused. A dead `lineupTable` left in the
# file is a second construction one edit away from being reachable again, and
# the whole of §L1 is that there is only one.
_assert("the Wave 4A stacked lineup table is gone",
        "lineupTable(" not in _prev_js)

# ONE FUNCTION DRAWS BOTH CELLS. This is §L1's parallel-construction rule and it
# is structural rather than cosmetic: the acting GM's cell and the opponent's
# are the same call with different data, so neither can acquire a figure, a
# class or an emphasis the other lacks.
_assert("one function draws both teams' cells",
        _prev_js.count("teamCell(") >= 3)      # one definition, two calls
_assert("one function draws both teams' footers",
        _prev_js.count("totalCell(") >= 3)
_assert("one function draws every labelled figure",
        _prev_js.count("figurePair(") >= 5)

# EVERY ROW IS ONE SLOT ON BOTH SIDES. The two lineups are indexed together and
# a side that is short draws an EMPTY cell rather than pulling its next player
# up — which would pair two starters the lineups do not pair.
_assert("the two lineups are indexed together, row by row",
        "left.rows[i]" in _prev_js and "right.rows[i]" in _prev_js)
_assert("a short lineup draws an empty cell, not a shifted row",
        "is-empty" in _prev_js)

# THE BINDER STILL REPORTS AND NEVER CALCULATES. Wave 4 §4's rule, restated for
# the fields Lane C added: a Math.*, a reduce() or a toFixed() here would mean a
# figure on screen that no server row states.
_model = _code_only(_without_comments(_read("web", "js", "preview-model.js")))
for _op, _why in (("toFixed", "rounds a figure"),
                  ("Math.", "calculates"),
                  ("reduce(", "aggregates"),
                  ("parseFloat", "reinterprets a served figure")):
    _assert(f"the preview binder never {_why} ({_op})", _op not in _model)


# ── §2 · Both figures are served, per starter and per team ───────────────────

_section("§2 · §L2 every starter and every team carries BOTH figures")

_api_src = _read("api", "main.py")

for _field, _label in (
    ("live_points:      Optional[float]", "a starter's live figure is served"),
    ("live_measured:    bool", "the affirmative measurement flag is served"),
    ("live_total:          Optional[float]", "a team's live total is served"),
    ("live_measured_count: int", "how much of the lineup it covers is served"),
    ("starter_count:       int", "how many starters there are is served"),
    ("live_available: bool", "whether the provider answered is served"),
):
    _assert(_label, _field in _api_src)

# THE PROJECTION NEVER LEAVES. §L2's standing rule: a live read that failed
# costs a GM the LIVE column and nothing else.
_assert("the projected total is still served",
        "projected_total: float" in _api_src)
_assert("every starter still carries a projection",
        "projected_points: float" in _api_src)

_prev_src = _code_only(_read("reports", "matchup_preview_read_model.py"))
_assert("the read model carries a live figure per starter",
        "live_points" in _prev_src and "live_measured" in _prev_src)
_assert("the read model carries a live total per side",
        "live_total" in _prev_src)

# THE TWO FIGURES ARE TWO FIELDS, and one is never computed from the other. A
# projection scaled by elapsed game time would be a fabricated live score with a
# plausible shape, which is the most dangerous version of the thing §L2 forbids.
_assert("the live figure is not derived from the projection",
        not re.search(r"live_points\s*=\s*[^\n]*projected", _prev_src))

# THE PREVIEW STILL DOES NOT PRICE. Wave 4 §3's rules, unchanged by Lane C.
_assert("the read model never calls the pricing engine itself",
        "compute_market_board" not in _prev_src)
_assert("the read model runs no simulation",
        "simulate" not in _prev_src and "monte" not in _prev_src.lower())
_assert("the live scoring is supplied by the caller, not fetched",
        "live=None" in _prev_src)


# ── §3 · The read model, against real bundles ────────────────────────────────

_section("§3 · the read model pairs projections with live figures")


class _FakeTeam:
    def __init__(self, team_id: int, name: str) -> None:
        self.id = team_id
        self.team_name = name


class _FakeStarter:
    """The `PlayerProj` shape `_fetch_starters_for_odds` hands the simulator."""

    def __init__(self, player_id: int, name: str, position: str,
                 points: float) -> None:
        self.player_id = player_id
        self.name = name
        self.position = position
        self.projected_points = points
        self.injury_status = None


_SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF")
_STARTERS = [_FakeStarter(100 + i, f"Player {i}", slot, 10.0 + i)
             for i, slot in enumerate(_SLOTS)]

try:
    from providers.live_scoring import LiveScores, REASON_NOT_REPORTED
    from reports.matchup_preview_read_model import _side

    # A FEED THAT HAS MEASURED FIVE OF NINE. Mid-week is the ordinary case and
    # it is the one that separates an honest partial total from a fabricated
    # full one.
    _partial = LiveScores(
        available=True, provider="demo", week=3,
        points_by_player_id={100: 12.4, 101: 0.0, 102: 8.8, 103: 21.1,
                             104: 3.5})
    _view = _side(_FakeTeam(1, "Pain Sanders"), _STARTERS, _partial)

    _assert("every starter carries a projection",
            all(isinstance(r.projected_points, float) for r in _view.lineup),
            f"{len(_view.lineup)} starters")
    _assert("every starter carries a live FIELD, measured or not",
            all(hasattr(r, "live_points") and hasattr(r, "live_measured")
                for r in _view.lineup))
    _assert("the measured starters are exactly the ones the feed named",
            [r.player_id for r in _view.lineup if r.live_measured]
            == [100, 101, 102, 103, 104])

    # A MEASURED ZERO IS A NUMBER. `player_id 101` scored 0.0 and must arrive as
    # 0.0 with `live_measured` True — the case a truthiness test would silently
    # turn into "no data" and the surface would then draw as an em dash.
    _zero = next(r for r in _view.lineup if r.player_id == 101)
    _assert("a measured zero survives as a measured zero",
            _zero.live_measured is True and _zero.live_points == 0.0,
            f"measured={_zero.live_measured} points={_zero.live_points!r}")

    # AN UNMEASURED STARTER IS NONE, NEVER ZERO.
    _unmeasured = [r for r in _view.lineup if not r.live_measured]
    _assert("an unmeasured starter carries no figure at all",
            all(r.live_points is None for r in _unmeasured),
            f"{len(_unmeasured)} unmeasured")

    _assert("the team projected total is the sum of the projections",
            _view.projected_total
            == round(sum(r.projected_points for r in _STARTERS), 1),
            str(_view.projected_total))
    _assert("the team live total covers only what was measured",
            _view.live_total == round(12.4 + 0.0 + 8.8 + 21.1 + 3.5, 1),
            str(_view.live_total))
    _assert("the live total says how much of the lineup it covers",
            (_view.live_measured_count, _view.starter_count) == (5, 9),
            f"{_view.live_measured_count}/{_view.starter_count}")

    # ── THE PRE-GAME SIDE ────────────────────────────────────────────────────
    #
    # Nothing measured. The projections are untouched, every live figure is
    # None, and the TEAM live total is None rather than 0.0 — a team whose
    # starters have not kicked off has not scored nothing.
    _pre = _side(_FakeTeam(2, "No Punt Intended"), _STARTERS,
                 LiveScores(available=True, reason=REASON_NOT_REPORTED,
                            provider="demo", week=3))
    _assert("a pre-game side still carries every projection",
            all(r.projected_points > 0 for r in _pre.lineup)
            and _pre.projected_total > 0, str(_pre.projected_total))
    _assert("a pre-game side reports NO live total, not a zero one",
            _pre.live_total is None, repr(_pre.live_total))
    _assert("a pre-game side measures nothing",
            _pre.live_measured_count == 0
            and all(r.live_points is None for r in _pre.lineup))

    # ── NO LIVE READ AT ALL ──────────────────────────────────────────────────
    _none = _side(_FakeTeam(3, "Third Team"), _STARTERS, None)
    _assert("a side built with no live read is identical to a pre-game one",
            _none.live_total is None and _none.live_measured_count == 0
            and _none.projected_total == _pre.projected_total)
except Exception as _exc:                                   # pragma: no cover
    _assert("the read-model checks could run", False, repr(_exc))


# ── §4 · The provider's absence is never a number ────────────────────────────

_section("§4 · §L2 a figure no provider stated is never drawn")

try:
    from providers import live_scoring
    from providers.demo.scenario import DemoScenario, week_snapshot

    _scenario = DemoScenario(league_key="demo.l.rev14probe")

    # AN OPEN WEEK IS A HEALTHY SNAPSHOT WITH NO STATS IN IT. The Demo provider
    # publishes lineups for any week and numbers only for a FINAL one, because
    # that is what a real feed does — see providers/demo/scenario.py. The
    # pre-game state therefore arrives here as a provider that ANSWERED.
    _open = week_snapshot(_scenario, week=2, current_week=2, final=False,
                          with_rosters=True)
    _open_live = live_scoring.live_week_from_snapshot(_open)
    _assert("an open week carries no player scoring at all",
            not _open_live.measured_any,
            f"{len(_open_live.points_by_player_key)} measured")

    _resolved = live_scoring.resolve_live_scores(None, _open_live,
                                                 player_ids=[1, 2, 3])
    _assert("an open week is AVAILABLE — the provider answered",
            _resolved.available is True)
    _assert("and names why it has no figures",
            _resolved.reason == live_scoring.REASON_NOT_REPORTED,
            repr(_resolved.reason))
    _assert("no starter is given a fabricated figure",
            all(_resolved.points_for(pid) is None for pid in (1, 2, 3)))
    _assert("and none is reported as measured",
            not any(_resolved.measured(pid) for pid in (1, 2, 3)))

    # A PROVIDER WE COULD NOT READ IS A DIFFERENT STATE, and it is kept
    # different for the same reason `providers.base.Finality` keeps UNKNOWN
    # apart from NOT_FINAL: the two look identical to a GM and mean entirely
    # different things to an operator.
    _out = live_scoring.no_live_scores(reason=live_scoring.REASON_UNREADABLE,
                                       week=2, provider="yahoo")
    _assert("an unreadable provider is NOT available",
            _out.available is False and _out.reason == "live_provider_unreadable",
            repr(_out.reason))
    _assert("an unreadable provider still yields no number",
            _out.points_for(1) is None and not _out.measured(1))

    # A STAT RECORD WITH NO SCORING TOTAL ON IT IS NOT A ZERO EITHER. The DTO
    # allows `fantasy_points=None` beside a full raw stat line, and this module
    # must not sum that line into a score of its own — that would be
    # FantasyStakes scoring a league whose settings it does not own.
    from providers.base import (ProviderLeague, ProviderPlayerStats,
                                ProviderWeek)
    _bare = ProviderWeek(
        league=ProviderLeague(provider="demo", league_key="demo.l.x",
                              name="x", season=2025),
        week=1,
        player_stats=(ProviderPlayerStats(
            provider="demo", player_key="demo.l.x.p.1", week=1,
            values={"receiving_yards": 88.0},
            stat_ids_present=frozenset({"receiving_yards"}),
            fantasy_points=None),))
    _assert("a stat line with no reported points yields no live figure",
            not live_scoring.live_week_from_snapshot(_bare).measured_any)

    # THE RENDERER'S HALF OF THE SAME RULE. `liveFigure` consults the
    # affirmative flag, so a measured 0.0 prints and an unmeasured starter
    # cannot.
    _assert("the renderer draws the em dash for an unmeasured starter",
            "row.liveMeasured && typeof row.live === 'number'" in _prev_js)
    _assert("the renderer never coerces a missing live figure to zero",
            not re.search(r"live\s*\|\|\s*0", _prev_js))
    _assert("a team with no measured starter draws the em dash too",
            "typeof spec.liveTotal === 'number'" in _prev_js)

    # THE SURFACE SAYS A DIFFERENT THING FOR EACH ABSENCE.
    _assert("the note distinguishes 'not scored yet' from 'could not read'",
            "served.live_available" in _prev_js
            and "not available from this" in _prev_js)
except Exception as _exc:                                   # pragma: no cover
    _assert("the missing-data checks could run", False, repr(_exc))


# ── §4b · A figure is resolved onto a player by IDENTITY, never by name ──────

_section("§4b · S6-R1 the live figure reaches the right player, or nobody")


def _identity_checks() -> None:
    """Resolve a provider's figures onto internal player ids, against real rows.

    A DISPOSABLE IN-MEMORY DATABASE, because the claim is about a JOIN and there
    is no way to assert a join without one. Nothing is read from or written to
    any database this product uses; the three rows below exist for the length of
    this function.

    THE THIRD ROW IS THE WHOLE POINT. It carries a Demo-SHAPED provider key
    under the `yahoo` provider — the collision that would let one provider's
    figures be painted onto another provider's players if the lookup keyed on
    the string alone. WP2 keeps the two providers apart at composition; this is
    the assertion that they stay apart at identity.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.schema import Base, Player
    from providers.live_scoring import ProviderLiveWeek, resolve_live_scores

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        db.add_all([
            Player(name="Measured", position="QB", provider="demo",
                   provider_player_key="demo.l.probe.p.100"),
            # SCORED ZERO, AND IT PLAYED. The row that separates a measured
            # nothing from an absent something.
            Player(name="Blanked", position="RB", provider="demo",
                   provider_player_key="demo.l.probe.p.101"),
            # A DIFFERENT PROVIDER'S PLAYER wearing a colliding key.
            Player(name="Elsewhere", position="WR", provider="yahoo",
                   provider_player_key="demo.l.probe.p.102"),
            # NO PROVIDER IDENTITY AT ALL — the certification fixture's own
            # synthetic roster, and every locally-seeded league's.
            Player(name="Unbound", position="TE"),
        ])
        db.commit()
        ids = [row.id for row in db.query(Player).order_by(Player.id).all()]

        week = ProviderLiveWeek(
            provider="demo", week=1, observed_at=None,
            points_by_player_key={"demo.l.probe.p.100": 18.4,
                                  "demo.l.probe.p.101": 0.0,
                                  "demo.l.probe.p.102": 99.9})
        got = resolve_live_scores(db, week, player_ids=ids)

        _assert("the provider's figure lands on the right player",
                got.points_for(ids[0]) == 18.4 and got.measured(ids[0]),
                repr(got.points_for(ids[0])))
        _assert("a measured zero lands as a measured zero",
                got.points_for(ids[1]) == 0.0 and got.measured(ids[1]),
                repr(got.points_for(ids[1])))
        _assert("another provider's player is never given this feed's figure",
                got.points_for(ids[2]) is None and not got.measured(ids[2]),
                repr(got.points_for(ids[2])))
        _assert("a player with no provider identity gets no figure, not a guess",
                got.points_for(ids[3]) is None and not got.measured(ids[3]),
                repr(got.points_for(ids[3])))

        # NOTHING WAS WRITTEN BY READING. A dirty session after the resolution
        # would mean the read path mutated state.
        _assert("resolving live figures leaves the session clean",
                not db.new and not db.dirty and not db.deleted,
                f"new={len(db.new)} dirty={len(db.dirty)} del={len(db.deleted)}")
    finally:
        db.close()
        engine.dispose()


try:
    _identity_checks()
except Exception as _exc:                                   # pragma: no cover
    _assert("the identity checks could run", False, repr(_exc))


# ── §5 · The Demo feed is deterministic ──────────────────────────────────────

_section("§5 · WP2 §12 two reads of one Demo week are identical")

try:
    from providers.demo.scenario import DemoScenario as _DS, week_snapshot as _ws
    from providers.live_scoring import live_week_from_snapshot as _lwfs

    _sc = _DS(league_key="demo.l.rev14determinism")
    _first = _lwfs(_ws(_sc, week=1, current_week=1, final=True,
                       with_rosters=True))
    _second = _lwfs(_ws(_sc, week=1, current_week=1, final=True,
                        with_rosters=True))

    _assert("the Demo week reports figures at all",
            _first.measured_any,
            f"{len(_first.points_by_player_key)} starters measured")
    _assert("two reads of the same Demo week agree exactly",
            _first.points_by_player_key == _second.points_by_player_key)

    # A DIFFERENT WEEK IS A DIFFERENT WEEK. A "deterministic" feed that returned
    # the same numbers for every week would pass the check above and be useless,
    # so the negative is asserted alongside it.
    _other = _lwfs(_ws(_sc, week=3, current_week=3, final=True,
                       with_rosters=True))
    _assert("a different Demo week reports different figures",
            _other.points_by_player_key != _first.points_by_player_key)

    # TWO DEMO LEAGUES NEVER COLLIDE — the scenario derives every key from the
    # league key, so the figures are namespaced as well as stable.
    _elsewhere = _lwfs(_ws(_DS(league_key="demo.l.rev14other"), week=1,
                           current_week=1, final=True, with_rosters=True))
    _assert("another Demo league's figures are keyed to itself",
            not (set(_elsewhere.points_by_player_key)
                 & set(_first.points_by_player_key)))

    # THE SHOWCASE FEED IS THE OTHER DEMO WORLD, and it is deterministic by the
    # same construction — pure functions of (team ordinal, roster slot, week).
    # It is checked here because `demo/stats.py` is what a showcase league's
    # live figures come from, and a determinism claim that covered only
    # `providers/demo/scenario.py` would leave half the demo uncertified.
    from demo import stats as _demo_stats
    _s1 = _demo_stats.actual_points_for_team(1, 1)
    _s2 = _demo_stats.actual_points_for_team(1, 1)
    _assert("the showcase feed's week is deterministic too",
            _s1 == _s2 and len(_s1) > 0, f"{len(_s1)} starters")
    _assert("an unplayed showcase week reports nothing, not zeros",
            _demo_stats.actual_points_for_team(1, 99) == ())
except Exception as _exc:                                   # pragma: no cover
    _assert("the determinism checks could run", False, repr(_exc))


# ── §6 · Lane C wrote nothing ────────────────────────────────────────────────

_section("§6 · the live-scoring path is read-only and caches nothing")

_MUTATIONS = ("db.add(", "db.add_all(", "db.commit()", "db.delete(", "db.flush()",
              "db.merge(", "INSERT ", "UPDATE ", "DELETE ", "session.add(")

for _mod in ("providers/live_scoring.py",
             "reports/matchup_preview_read_model.py"):
    _src = _code_only(_read(*_mod.split("/")))
    _hits = [m for m in _MUTATIONS if m in _src]
    _assert(f"{_mod} performs no mutation", not _hits, ", ".join(_hits))
    _assert(f"{_mod} issues no write SQL",
            not re.search(r"text\(\s*[\"'](?!\s*SELECT)", _src, re.I))

# NO NEW STORE OF PROVIDER DATA. `ops/yahoo_retention.py` inventories every
# persisted field of Yahoo origin against `db/schema.py`, so a cache here would
# be a retention question before it was a feature. The guard is on the module
# doing the reading rather than on the schema, because the schema check already
# exists and this is the file that would tempt someone to add one.
_live_src = _code_only(_read("providers", "live_scoring.py"))
for _forbidden in ("lru_cache", "cache", "_CACHE", "global "):
    _assert(f"the live reader holds nothing between calls ({_forbidden})",
            _forbidden not in _live_src)

# ONE COMPOSITION BOUNDARY. WP2 puts the only provider-name branch in
# `api.main._provider_week_snapshot`; a second one here would be a second place
# to keep in step with every provider that is ever added.
_assert("the live reader does not branch on a provider name",
        "yahoo" not in _live_src.lower() and "DEMO_PROVIDER" not in _live_src)
_assert("the route reaches the provider through the WP2 boundary",
        "_provider_week_snapshot(db, league, week, with_rosters=True)"
        in _api_src)

# ECONOMICS ARE UNTOUCHED. Lane C is read-only with respect to every money path.
for _frozen in ("betting/pool_claims.py", "betting/pool_settlement.py",
                "betting/settlement_engine.py", "economy/challenge_funding.py",
                "ledger/ledger.py", "odds/market_lines.py"):
    _assert(f"{_frozen} is not named by the live-scoring path",
            os.path.basename(_frozen).replace(".py", "") not in _live_src)


# ── Node tier ────────────────────────────────────────────────────────────────

def _run_node(script: str, label: str) -> None:
    node = shutil.which("node")
    if node is None:
        _assert(f"{label} — node is available", False, "node not on PATH")
        return
    print(f"\n{label}")
    proc = subprocess.run([node, os.path.join(WEB, "tests", script)],
                          cwd=ROOT, capture_output=True, text=True)
    print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print(proc.stderr.rstrip())
    passes = proc.stdout.count("[PASS]")
    fails = proc.stdout.count("[FAIL]")
    _assert(f"{label} is green", proc.returncode == 0,
            f"{passes} PASS / {fails} FAIL, exit {proc.returncode}")


_run_node("uirecon_rev14_preview_browser.mjs",
          "UIRECON Rev 1.4 Lane C browser suite (headless Chrome)")


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
if _failures:
    print(f"UIRECON REV 1.4 LANE C — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
print("UIRECON REV 1.4 LANE C — ALL PASSED")
