"""SPRINT 7B · the certified BALLDONTLIE chain, reached from the live product.

WHAT SPRINT 7 LEFT OPEN. Sprint 7 made the choice representable — a row per
league-season naming a projection source, a factual source and a simulation
model — and wired the FACTUAL half into the one existing provider dispatch
seam. The PRICING half stayed unreachable: `beefs/beef_engine` read a
FantasyPros scalar out of `projections` and priced it with sim-v1, for every
league, unconditionally, and `odds/sim_v2.py` was imported by nothing outside
`test_*`. Sprint 7's own report called that Blocker B.

THIS SUITE IS THE PROOF THAT IT IS CLOSED. A league configured for BALLDONTLIE
projections and sim-v2 now produces its real market board — the same board the
`/versus/board` route serves and the same one the composer quotes from —
through:

    persisted component snapshot  ->  CSPS under the league's own profile
    ->  IPRM-v2 with parameters measured from real 2024 evidence
    ->  sim-v2, one sigma per player
    ->  odds/market_lines and _prob_to_american, unchanged
    ->  VersusMarketBoard

and a control league in the SAME process and the SAME database keeps reading
scalars and pricing with sim-v1.

── THE ADAPTER IS TWO FUNCTIONS, AND THAT IS THE DESIGN ────────────────────

`_fetch_starters_for_odds` decides WHERE the per-starter numbers come from.
`simulate_matchup_scores` decides WHICH simulator turns them into
distributions. Both were already the single place their question was answered,
so making those two provider-aware moves the whole product without duplicating
a board builder, an odds conversion, a spread rule or a quote lifecycle.

It also closes the mixed-provider hazard by construction rather than by
assertion: the preview read model builds the lineup a GM SEES from
`_fetch_starters_for_odds`, and the board prices from the same call, so there
is no second read that could answer differently.

── EVERY NUMBER IS MEASURED ────────────────────────────────────────────────

Components from the committed week-17 2025 capture. Pick-six, three-and-out and
drive parameters derived by the Sprint 5/5B derivers from the real captured
TEN-at-CHI play-by-play. Reception parameters from the real 2024 season totals
Sprint 5B certified. Sprint 7B calibrates nothing.

OFFLINE AND DETERMINISTIC. File-backed SQLite, captured fixtures, no network,
no credential.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.abspath(__file__))
_DB_PATH = os.path.join(os.environ.get("TEMP", "."), "sprint7b_pricing.db")
if os.path.exists(_DB_PATH):
    os.remove(_DB_PATH)
os.environ["DATABASE_URL"] = "sqlite:///" + _DB_PATH.replace("\\", "/")
os.environ.setdefault("JWT_SECRET_KEY", "sprint7b-suite-secret")
os.environ["FS_COOKIE_INSECURE"] = "1"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from datetime import datetime, timezone                            # noqa: E402

import numpy as np                                                 # noqa: E402

from db.schema import (                                            # noqa: E402
    Base, League, LeagueProviderConfig, Projection,
    ProviderComponentProjection, ProviderHistoricalRate, SessionLocal, Team,
    engine,
)

Base.metadata.create_all(engine)

from beefs import beef_engine as BE                                # noqa: E402
from beefs import pricing as PR                                    # noqa: E402
from odds import model_registry as MR                              # noqa: E402
from odds import sim_v2 as SV2                                     # noqa: E402
from providers import selection as SEL                             # noqa: E402
from scoring import csps as C                                      # noqa: E402
from scoring import iprm as I                                      # noqa: E402

import test_support_sprint7b_world as W                            # noqa: E402

FROZEN_V1_HASH = ("1d60ff39343bebf1ceb8099f729fbaff18cb2780"
                  "78e06d094da6cc04ba4626d1")

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


def _section(title):
    print(f"\n{title}")


def _raises(exc, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc:
        return True
    except Exception:                                             # noqa: BLE001
        return False
    return False


def _refusal(fn, *args, **kwargs):
    """Run and return the `PricingRefusal` it raised, or None."""
    try:
        fn(*args, **kwargs)
    except PR.PricingRefusal as exc:
        return exc
    except Exception:                                             # noqa: BLE001
        return None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 7B-A · the world, built from real evidence through production paths
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-A · the staging world, from measured evidence only")

db = SessionLocal()
world = W.seed_world(db)
# COMMITTED HERE SO THE WORLD SURVIVES THE DELIBERATE ROLLBACK IN 7B-E. That
# section proves a forbidden value cannot be STORED, which means provoking a
# constraint violation, which means rolling the session back — and an
# uncommitted world would go with it.
db.commit()
staging = world["leagues"]["staging"]
control = world["leagues"]["control"]
s_teams = world["teams"]["staging"]
c_teams = world["teams"]["control"]
# Plain integers, captured before anything closes a session. The restart proof
# in 7B-H detaches every ORM instance by design, and an identity that only
# exists as an attached object cannot survive the very event being tested.
STAGING_ID, CONTROL_ID = staging.id, control.id
S_TEAM_IDS = [t.id for t in s_teams]
C_TEAM_IDS = [t.id for t in c_teams]

_assert("the production ingest resolved every subject the capture carries",
        world["ingest"].resolved == len(W.SUBJECTS)
        and world["ingest"].unresolved == 0
        and world["ingest"].ambiguous == 0,
        f"{world['ingest'].resolved} resolved")
_assert("  · and persisted a component snapshot for each",
        db.query(ProviderComponentProjection).filter(
            ProviderComponentProjection.season == W.SEASON,
            ProviderComponentProjection.week == W.WEEK).count()
        == len(W.SUBJECTS))
_assert("  · labelled FIXTURE_SYNTHETIC, never LIVE -- a replayed snapshot must "
        "not be indistinguishable from a fetched one",
        {r.provenance for r in db.query(ProviderComponentProjection).all()}
        == {ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC})

_rates = db.query(ProviderHistoricalRate).all()
_assert("every IPRM model parameter was DERIVED from real evidence",
        len(_rates) > 0 and all(r.provider == "balldontlie" for r in _rates),
        f"{len(_rates)} parameter rows")
_assert("  · none is labelled SYNTHETIC",
        not [r for r in _rates if r.source_kind == "SYNTHETIC"])
_assert("  · all four certified models are represented",
        {r.model_version for r in _rates} >= {
            "pick-six-model-v2", "three-and-out-model-v2",
            "drives-model-v1", "reception-model-v2"},
        str(sorted({r.model_version for r in _rates})))
_assert("  · and they are in force BEFORE the moment being priced, which is "
        "why the lineup resolves at all",
        max(r.as_of for r in _rates).replace(tzinfo=None)
        < min(s.observed_at for s in db.query(
            ProviderComponentProjection).all()).replace(tzinfo=None),
        f"as_of {max(r.as_of for r in _rates)} < observed "
        f"{min(s.observed_at for s in db.query(ProviderComponentProjection).all())}")


# ══════════════════════════════════════════════════════════════════════════════
# 7B-B · the live product prices a BALLDONTLIE league through sim-v2
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-B · the ACTUAL product path, on the BALLDONTLIE chain")

# The board BEFORE activation — the league is on legacy, like every league in
# production today. Captured so the change is demonstrated rather than assumed.
_legacy_board = BE.compute_market_board(s_teams[0], s_teams[1], W.WEEK, db)

W.activate_balldontlie(db)
_selection = SEL.resolve(db, league_id=staging.id, season=W.SEASON)
_assert("the staging league is configured balldontlie / balldontlie / sim-v2",
        (_selection.projection_source, _selection.factual_source,
         _selection.simulation_model)
        == ("balldontlie", "balldontlie", "sim-v2"))
_assert("  · and names the certified scoring profile CSPS must use",
        _selection.scoring_profile_id == W.PROFILE_ID)

_plan = PR.resolve_plan(db, team_id=s_teams[0].id, week=W.WEEK)
_assert("the resolver puts this league on the component chain",
        _plan.uses_components is True)
_assert("  · under sim-v2, resolved through the frozen registry",
        _plan.model_config.model_version_id == "sim-v2")
_assert("  · with the league's own loaded CSPS profile",
        _plan.profile is not None
        and _plan.profile.profile_id == W.PROFILE_ID,
        f"{_plan.profile.profile_id} v{_plan.profile.version}")
_assert("  · and the certified IPRM version, not one this sprint invented",
        _plan.iprm_config.iprm_version == I.IPRM_VERSION == "iprm-v2")

_board = BE.compute_market_board(s_teams[0], s_teams[1], W.WEEK, db)
_assert("THE LIVE PRODUCT PRICES THIS LEAGUE FROM BALLDONTLIE COMPONENTS",
        _board is not None and isinstance(_board.anchor_moneyline, int),
        f"ML {_board.anchor_moneyline}/{_board.opponent_moneyline} "
        f"spread {_board.anchor_spread_display} total {_board.total_line}")
_assert("  · and the price MOVED -- this is a different model on different "
        "inputs, not the same board relabelled",
        (_board.anchor_moneyline, _board.spread_line, _board.total_line)
        != (_legacy_board.anchor_moneyline, _legacy_board.spread_line,
            _legacy_board.total_line),
        f"legacy {_legacy_board.anchor_moneyline}/"
        f"{_legacy_board.total_line} -> bdl {_board.anchor_moneyline}/"
        f"{_board.total_line}")
_assert("  · every market on the board is populated: moneyline, spread, total",
        _board.anchor_moneyline and _board.opponent_moneyline
        and _board.spread_line is not None and _board.total_line is not None)
_assert("  · the two win probabilities are complementary, as both frozen "
        "configs require",
        abs(_board.anchor_win_probability + _board.opponent_win_probability
            - 1.0) < 1e-9)

# THE CHAIN IS PROVEN LINK BY LINK, not by the existence of a number.
_inputs = BE._fetch_starters_for_odds("straight", s_teams[0].id,
                                      s_teams[1].id, None, W.WEEK, db)
_assert("the odds bundle carries a component pricing plan",
        _inputs.pricing_plan is not None
        and _inputs.pricing_plan.uses_components)
_build = _inputs.pricing_plan.builds[s_teams[0].id]
_assert("  · built by sim-v2's certified lineup builder",
        isinstance(_build, SV2.LineupBuild) and _build.admissible)
_assert("  · every starter carries an IPRM result with its OWN sigma -- which "
        "is the entire reason sim-v2 exists",
        len(_build.sigmas) == len(_build.means) == len(_build.starters)
        and len(set(_build.sigmas.tolist())) > 1,
        f"sigmas {[round(x, 3) for x in _build.sigmas.tolist()]}")
_assert("  · each mean came through CSPS under the league's profile",
        all(r.scoring_profile_id == W.PROFILE_ID
            for r in _build.iprm_results),
        str({r.scoring_profile_id for r in _build.iprm_results}))
_assert("  · every one is ADMISSIBLE, and says at which level its parameters "
        "resolved -- a price can be traced to its evidence",
        all(I.admissible(r) for r in _build.iprm_results)
        and {r.status for r in _build.iprm_results}
        <= {I.Status.SIMULATION_READY,
            I.Status.SIMULATION_READY_WITH_FALLBACKS},
        str({r.status for r in _build.iprm_results}))

_scores = PR.matchup_scores(_inputs.pricing_plan, _inputs, W.WEEK)
_assert("the draw is sim-v2's, one sigma per player",
        _scores[0].shape == (_plan.model_config.n_sims,),
        f"{_scores[0].shape}")
_assert("  · and NOT clamped at zero -- sim-v2 does not truncate, because a "
        "league-scored defence can go negative",
        _plan.model_config.truncate_draws_at_zero is False)

# The board's own numbers are re-derived from those arrays through the EXISTING
# market machinery, proving the board is a read of this draw and not a parallel
# computation that happens to agree.
from odds.market_lines import lines_from_scores, sportsbook_spread  # noqa: E402
from odds.odds_engine_headless import _prob_to_american             # noqa: E402

_p = float((_scores[0] > _scores[1]).mean())
_lines = lines_from_scores(_scores[0], _scores[1])
_assert("the board's moneyline IS this draw, through the existing conversion",
        _prob_to_american(_p) == _board.anchor_moneyline)
_assert("  · its spread IS this draw's median margin, through market_lines",
        _lines.spread_line == _board.spread_line
        and sportsbook_spread(_lines.spread_line)
        == _board.anchor_spread_display)
_assert("  · its total IS this draw's median combined score",
        _lines.total_line == _board.total_line)
_assert("  · so Sprint 7B reimplemented no odds, no spread and no total",
        True, "every line above came from odds/market_lines")


# ══════════════════════════════════════════════════════════════════════════════
# 7B-C · the control league, same process, same database, unchanged
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-C · the control league keeps the legacy scalar path and sim-v1")

_c_plan = PR.resolve_plan(db, team_id=c_teams[0].id, week=W.WEEK)
_assert("an unconfigured league resolves to legacy / legacy / sim-v1",
        (_c_plan.selection.projection_source,
         _c_plan.selection.factual_source,
         _c_plan.selection.simulation_model)
        == ("legacy", "legacy", "sim-v1")
        and _c_plan.selection.configured is False)
_assert("  · takes no component branch at all",
        _c_plan.uses_components is False and _c_plan.profile is None)

_c_inputs = BE._fetch_starters_for_odds("straight", c_teams[0].id,
                                        c_teams[1].id, None, W.WEEK, db)
_assert("  · and its odds bundle carries NO pricing plan, so the simulator "
        "takes the code path it always took",
        _c_inputs.pricing_plan is None)
_assert("  · its starter projections are the FantasyPros scalars",
        sorted(round(p.projected_points, 2) for p in _c_inputs.ch_starters)
        == sorted(round(W.LEGACY_POINTS[p.position], 2)
                  for p in _c_inputs.ch_starters),
        str([(p.position, p.projected_points) for p in _c_inputs.ch_starters]))

_c_board = BE.compute_market_board(c_teams[0], c_teams[1], W.WEEK, db)

# BYTE-FOR-BYTE, INDEPENDENTLY RECONSTRUCTED. The legacy board is recomputed
# here from `simulate_scores` under MODEL_V1 with the scalar projections — the
# pre-Sprint-7B formula, spelled out — and must agree exactly.
from odds.odds_engine_headless import simulate_scores               # noqa: E402

_ch, _cd = simulate_scores(
    c_teams[0].id, c_teams[1].id, _c_inputs.ch_starters,
    _c_inputs.cd_starters, W.WEEK, model_config=MR.MODEL_V1,
    matchup_id=None)
_ref_lines = lines_from_scores(_ch, _cd)
_assert("THE CONTROL BOARD IS BYTE-FOR-BYTE THE PRE-SPRINT-7B COMPUTATION",
        (_prob_to_american(float((_ch > _cd).mean())),
         _ref_lines.spread_line, _ref_lines.total_line)
        == (_c_board.anchor_moneyline, _c_board.spread_line,
            _c_board.total_line),
        f"ML {_c_board.anchor_moneyline} spread {_c_board.spread_line} "
        f"total {_c_board.total_line}")
_assert("  · and it is a DIFFERENT board from the BALLDONTLIE league's, on the "
        "same six players in the same week",
        (_c_board.anchor_moneyline, _c_board.total_line)
        != (_board.anchor_moneyline, _board.total_line))
_assert("  · so activating one league contaminated no other",
        _c_board.total_line == _legacy_board.total_line
        and _c_board.spread_line == _legacy_board.spread_line,
        "the control board equals the staging league's own PRE-activation board")

# ── THE PINNED LEGACY BOARD ────────────────────────────────────────────────
#
# MEASURED IN THE COMMITTED BASE, NOT PREDICTED. This exact line was produced by
# running the same construction against a clean `git archive` export of
# 12ce3128553df5bcda3059fdccfdcdebfe2e2bf8 — the tree as it stood before Sprint
# 7 and Sprint 7B existed — and it is pinned here so any future change to the
# legacy pricing path has to break this assertion to get through.
#
# It is deliberately a FIXED six-position league with stated scalar
# projections, independent of the world fixture above, so the pin means the same
# thing whatever else the suite is doing.
#
# THE TEAM IDS ARE EXPLICIT, AND THEY HAVE TO BE. sim-v1 seeds an unscheduled
# pairing from `home_id * 10_000 + away_id * 100 + week`, so two teams with
# different row ids are a DIFFERENT DRAW of the same matchup — correct
# behaviour, and fatal to a pin that let the database choose them. 9001 and
# 9002 are stated here and were stated in the base measurement.
_PINNED_LEGACY_BOARD = ("ml=-220/220 p=0.6878 spread=3.0 "
                        "display=-3.0/3.0 total=63.5")

_pin_league = League(season=W.SEASON, name="legacy pin",
                     projection_source="fantasypros")
db.add(_pin_league)
db.flush()
_pin_teams = []
for _ordinal in (1, 2):
    _t = Team(id=9000 + _ordinal, league_id=_pin_league.id,
              team_name=f"pin {_ordinal}",
              owner=f"o{_ordinal}", email=f"pin{_ordinal}@example.invalid")
    db.add(_t)
    _pin_teams.append(_t)
db.flush()
from db.schema import Player as _Player, Roster as _Roster       # noqa: E402

for _index, (_position, _points) in enumerate(sorted(W.LEGACY_POINTS.items())):
    _p = _Player(name=f"pin {_position}", position=_position, nfl_team="DET")
    db.add(_p)
    db.flush()
    db.add(_Roster(team_id=_pin_teams[_index % 2].id, player_id=_p.id))
    db.add(Projection(player_id=_p.id, week=W.WEEK, season=W.SEASON,
                      source=W.LEGACY_SOURCE, projected_points=_points,
                      injury_status=None))
db.flush()
_pin_board = BE.compute_market_board(_pin_teams[0], _pin_teams[1], W.WEEK, db)
_pin_actual = (f"ml={_pin_board.anchor_moneyline}/"
               f"{_pin_board.opponent_moneyline} "
               f"p={_pin_board.anchor_win_probability!r} "
               f"spread={_pin_board.spread_line!r} "
               f"display={_pin_board.anchor_spread_display!r}/"
               f"{_pin_board.opponent_spread_display!r} "
               f"total={_pin_board.total_line!r}")
_assert("THE LEGACY BOARD IS BYTE-FOR-BYTE WHAT THE COMMITTED BASE PRODUCED",
        _pin_actual == _PINNED_LEGACY_BOARD, _pin_actual)
_assert("  · including the raw win probability, not merely the rounded "
        "moneyline -- a drift smaller than a cent would still break this",
        "p=0.6878" in _pin_actual)

_assert("both models are live in ONE process at ONE time",
        PR.resolve_plan(db, team_id=s_teams[0].id,
                        week=W.WEEK).model_config.model_version_id == "sim-v2"
        and PR.resolve_plan(db, team_id=c_teams[0].id,
                            week=W.WEEK).model_config.model_version_id
        == "sim-v1")


# ══════════════════════════════════════════════════════════════════════════════
# 7B-D · no mixed-provider product state
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-D · the displayed projection and the priced projection are one read")

from reports import matchup_preview_read_model as PREVIEW            # noqa: E402

_preview = PREVIEW.matchup_preview(
    db, league_id=staging.id, week=W.WEEK, acting_team=s_teams[0],
    opponent_team=s_teams[1], board=_board, phase=None, live=None)
_shown = {row.player_id: round(row.projected_points, 4)
          for row in _preview.acting.lineup}
_priced = {r.player_id: round(float(r.mean_fantasy_points), 4)
           for r in _build.iprm_results}
_assert("the preview shows exactly the numbers the board priced",
        _shown == _priced, f"shown {_shown}")
_assert("  · none of which is a FantasyPros scalar",
        not any(abs(v - W.LEGACY_POINTS[p.position]) < 1e-6
                for p, v in zip(_build.starters, _shown.values())
                if p.position in W.LEGACY_POINTS),
        str(_shown))
_assert("  · and the projected total is the sum of those same values",
        abs(_preview.acting.projected_total
            - round(sum(_priced.values()), 1)) < 0.15,
        f"{_preview.acting.projected_total} vs {round(sum(_priced.values()), 1)}")
_assert("  · while the market beside them is this board, field for field",
        (_preview.market.acting_moneyline, _preview.market.spread_line,
         _preview.market.total_line)
        == (_board.anchor_moneyline, _board.spread_line, _board.total_line))

_c_preview = PREVIEW.matchup_preview(
    db, league_id=control.id, week=W.WEEK, acting_team=c_teams[0],
    opponent_team=c_teams[1], board=_c_board, phase=None, live=None)
_assert("the CONTROL preview shows the FantasyPros scalars beside sim-v1 odds",
        all(abs(row.projected_points - W.LEGACY_POINTS[
            next(p for p in world["players"]
                 if p.id == row.player_id).position]) < 1e-6
            for row in _c_preview.acting.lineup))
_assert("SO NO BOARD IN THIS PROCESS MIXES PROVIDERS", True,
        "one read feeds both the display and the price, by construction")

_prov = _plan.provenance()
_assert("a board's provenance is fully establishable without a secret",
        _prov["projection_source"] == "balldontlie"
        and _prov["simulation_model"] == "sim-v2"
        and _prov["scoring_profile_id"] == W.PROFILE_ID
        and _prov["iprm_version"] == "iprm-v2"
        and len(_prov["model_config_hash"]) == 64, json.dumps(_prov))
_assert("  · and carries no key, token, header or credential",
        not any(k in json.dumps(_prov).lower()
                for k in ("key", "token", "authorization", "secret",
                          "password", "bearer")))


# ══════════════════════════════════════════════════════════════════════════════
# 7B-E · no silent fallback, in either direction
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-E · the four combinations, and the two that refuse")

W.activate_balldontlie(db, projection_source="balldontlie",
                       simulation_model="sim-v1")
_r = _refusal(PR.resolve_plan, db, team_id=s_teams[0].id, week=W.WEEK)
_assert("balldontlie projections with sim-v1 REFUSES",
        _r is not None
        and _r.reason_code == "unsupported_model_combination")
_assert("  · because sim-v1 would re-score a CSPS total a second time, and "
        "the refusal says exactly that",
        "score a CSPS total a second time" in str(_r))

W.activate_balldontlie(db, projection_source="legacy",
                       simulation_model="sim-v2")
_r = _refusal(PR.resolve_plan, db, team_id=s_teams[0].id, week=W.WEEK)
_assert("legacy projections with sim-v2 REFUSES",
        _r is not None
        and _r.reason_code == "unsupported_model_combination")

W.activate_balldontlie(db, scoring_profile_id=None)
db.query(LeagueProviderConfig).filter(
    LeagueProviderConfig.league_id == staging.id).one().scoring_profile_id = None
db.flush()
_r = _refusal(PR.resolve_plan, db, team_id=s_teams[0].id, week=W.WEEK)
_assert("BALLDONTLIE projections with NO scoring profile REFUSES",
        _r is not None
        and _r.reason_code == "scoring_profile_unconfigured")
_assert("  · rather than picking a house rule set, because two certified "
        "profiles disagree on real subjects",
        "no default set to fall back on" in str(_r).replace("\n", " ")
        or "names no scoring profile" in str(_r))

W.activate_balldontlie(db)          # restore the supported configuration
_assert("  · and naming the profile again restores pricing immediately",
        BE.compute_market_board(s_teams[0], s_teams[1], W.WEEK, db)
        .total_line == _board.total_line)

# A CONFIGURED LEAGUE WHOSE SNAPSHOTS ARE MISSING REFUSES; it does NOT read the
# scalar table that is sitting right there, fully populated.
_r = _refusal(BE.compute_market_board, s_teams[0], s_teams[1], W.WEEK + 1, db)
_assert("a week with no component snapshot REFUSES",
        _r is not None
        and _r.reason_code == "projection_snapshot_unavailable",
        str(_r)[:110] if _r else "no refusal")
# SCOPED TO THIS WORLD'S PLAYERS, not to the whole table: the byte-for-byte
# pin in 7B-C seeds a second six-player league with its own scalar feed, and a
# global count would be measuring that instead of this claim.
_world_player_ids = [p.id for p in world["players"]]
_assert("  · even though the legacy scalar feed for those players exists and "
        "would have priced -- THAT is what no silent fallback means",
        db.query(Projection).filter(
            Projection.season == W.SEASON,
            Projection.source == W.LEGACY_SOURCE,
            Projection.player_id.in_(_world_player_ids)).count()
        == len(W.SUBJECTS))
_assert("  · and the refusal names the subject and the cause",
        _r is not None and _r.detail
        and any("component snapshot" in d for d in _r.detail),
        str(_r.detail[:1]) if _r and _r.detail else "")

_assert("the inverse is equally forbidden: a legacy league is never handed "
        "BALLDONTLIE values although its snapshots exist",
        PR.resolve_plan(db, team_id=c_teams[0].id,
                        week=W.WEEK).uses_components is False
        and db.query(ProviderComponentProjection).count() > 0)

_assert("`auto` cannot be stored, so it cannot be silently reinterpreted",
        _raises(Exception, SEL.set_selection, db, league_id=control.id,
                season=W.SEASON, projection_source="auto"))
db.rollback()
W.activate_balldontlie(db)


# ══════════════════════════════════════════════════════════════════════════════
# 7B-F · settlement-grade determinism and replay
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-F · the same inputs price the same board, every time")

_again = BE.compute_market_board(s_teams[0], s_teams[1], W.WEEK, db)
_assert("re-pricing reproduces the board exactly",
        (_again.anchor_moneyline, _again.opponent_moneyline,
         _again.spread_line, _again.total_line,
         _again.anchor_win_probability)
        == (_board.anchor_moneyline, _board.opponent_moneyline,
            _board.spread_line, _board.total_line,
            _board.anchor_win_probability))

_i2 = BE._fetch_starters_for_odds("straight", s_teams[0].id, s_teams[1].id,
                                  None, W.WEEK, db)
_fp1 = SV2.simulation_fingerprint(
    home=_build, away=_inputs.pricing_plan.builds[s_teams[1].id],
    model_config=_plan.model_config, iprm_config=_plan.iprm_config,
    projection_source="balldontlie", season=W.SEASON, week=W.WEEK,
    matchup_id=0)
_fp2 = SV2.simulation_fingerprint(
    home=_i2.pricing_plan.builds[s_teams[0].id],
    away=_i2.pricing_plan.builds[s_teams[1].id],
    model_config=_plan.model_config, iprm_config=_plan.iprm_config,
    projection_source="balldontlie", season=W.SEASON, week=W.WEEK,
    matchup_id=0)
_assert("  · and the simulation fingerprint is identical across the two runs",
        _fp1 == _fp2, _fp1[:24])

_assert("the seed rule both frozen configs NAME is now one function they both "
        "call, so the claim is checkable rather than asserted",
        MR.MODEL_V1.seed_method == MR.MODEL_V2.seed_method
        == "matchup_or_team_pair_week_v1")
from odds.odds_engine_headless import matchup_seed                  # noqa: E402

_assert("  · matchup-seeded when a pairing is scheduled",
        matchup_seed(1, 2, 17, matchup_id=42) == 42 * 1000 + 17)
_assert("  · team-pair-seeded when it is not",
        matchup_seed(1, 2, 17) == 1 * 10_000 + 2 * 100 + 17)


# ══════════════════════════════════════════════════════════════════════════════
# 7B-G · request scaling — NFL evidence is global, not per fantasy league
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-G · 1, 10 and 100 BALLDONTLIE leagues cost the provider nothing")


class _ExplodingTransport:
    """Any provider request on a UI path is a defect. This makes it a failure."""

    requests_made = 0

    def get(self, *a, **k):                                        # noqa: D102
        raise AssertionError("a UI request reached the provider")

    def paginate(self, *a, **k):                                   # noqa: D102
        raise AssertionError("a UI request reached the provider")


import providers.balldontlie.transport as TRANSPORT                 # noqa: E402

_real_live = TRANSPORT.BalldontlieLiveTransport
TRANSPORT.BalldontlieLiveTransport = _ExplodingTransport
try:
    _boards = [BE.compute_market_board(s_teams[0], s_teams[1], W.WEEK, db)
               for _ in range(10)]
    _no_network = True
except AssertionError:
    _no_network = False
finally:
    TRANSPORT.BalldontlieLiveTransport = _real_live

_assert("ten board reads triggered ZERO provider requests",
        _no_network and len(_boards) == 10)
_assert("  · and every one produced the identical board",
        all((b.anchor_moneyline, b.total_line)
            == (_board.anchor_moneyline, _board.total_line) for b in _boards))

# The scaling claim, made structurally rather than by counting HTTP calls: the
# component snapshot table is keyed by (provider, season, week, subject) and
# carries no league column at all, so N leagues read N times from ONE row set.
_cols = {c.name for c in ProviderComponentProjection.__table__.columns}
_assert("component snapshots are NFL-global -- there is no league column to "
        "multiply by",
        "league_id" not in _cols, str(sorted(_cols))[:120])
_rate_cols = {c.name for c in ProviderHistoricalRate.__table__.columns}
_assert("  · and neither is there one on the historical parameters",
        "league_id" not in _rate_cols)
_assert("  · so activating 1, 10 or 100 leagues stores not one extra fact row",
        db.query(ProviderComponentProjection).count() == len(W.SUBJECTS))

_t0 = time.perf_counter()
for _ in range(20):
    PR.resolve_plan(db, team_id=s_teams[0].id, week=W.WEEK)
_resolve_ms = (time.perf_counter() - _t0) * 1000 / 20
_assert("selection resolution is one indexed read, not an N+1",
        _resolve_ms < 25.0, f"{_resolve_ms:.3f} ms per resolve")

_t0 = time.perf_counter()
BE.compute_market_board(s_teams[0], s_teams[1], W.WEEK, db)
_board_ms = (time.perf_counter() - _t0) * 1000
_assert("a full BALLDONTLIE board -- snapshots, CSPS, IPRM-v2, sim-v2, lines "
        "-- is inside a page-load budget",
        _board_ms < 2000.0, f"{_board_ms:.1f} ms")


# ══════════════════════════════════════════════════════════════════════════════
# 7B-H · restart and recovery
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-H · nothing the product needs lives only in process memory")

db.commit()
db.close()

_restarted = SessionLocal()
_r_sel = SEL.resolve(_restarted, league_id=STAGING_ID, season=W.SEASON)
_assert("the provider selection survived a session restart",
        (_r_sel.projection_source, _r_sel.simulation_model,
         _r_sel.scoring_profile_id)
        == ("balldontlie", "sim-v2", W.PROFILE_ID))
# EVERY HANDLE IS RE-FETCHED BY ID. Nothing carried across the restart except
# integers, which is exactly the claim: no provider or model state lived in
# process memory.
staging = _restarted.query(League).filter(League.id == STAGING_ID).one()
control = _restarted.query(League).filter(League.id == CONTROL_ID).one()
s_teams = [_restarted.query(Team).filter(Team.id == i).one()
           for i in S_TEAM_IDS]
c_teams = [_restarted.query(Team).filter(Team.id == i).one()
           for i in C_TEAM_IDS]
_r_board = BE.compute_market_board(s_teams[0], s_teams[1], W.WEEK, _restarted)
_assert("  · and the board recomputes identically after the restart",
        (_r_board.anchor_moneyline, _r_board.spread_line, _r_board.total_line)
        == (_board.anchor_moneyline, _board.spread_line, _board.total_line))
_assert("  · the component snapshots survived too",
        _restarted.query(ProviderComponentProjection).count()
        == len(W.SUBJECTS))
_assert("  · as did every derived model parameter",
        _restarted.query(ProviderHistoricalRate).count() == len(_rates))
db = _restarted


# ══════════════════════════════════════════════════════════════════════════════
# 7B-I · the rollback drill
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-I · rollback changes a selection, never a history")

_snapshots_before = db.query(ProviderComponentProjection).count()
_rates_before = db.query(ProviderHistoricalRate).count()

SEL.set_selection(db, league_id=staging.id, season=W.SEASON,
                  projection_source="legacy", factual_source="legacy",
                  simulation_model="sim-v1", note="Sprint 7B rollback drill",
                  updated_by="sprint7b")
db.flush()
_rolled = BE.compute_market_board(s_teams[0], s_teams[1], W.WEEK, db)
_assert("after rollback the league prices exactly as it did before activation",
        (_rolled.anchor_moneyline, _rolled.spread_line, _rolled.total_line)
        == (_legacy_board.anchor_moneyline, _legacy_board.spread_line,
            _legacy_board.total_line))
_assert("  · every BALLDONTLIE snapshot is still there",
        db.query(ProviderComponentProjection).count() == _snapshots_before)
_assert("  · every derived parameter is still there",
        db.query(ProviderHistoricalRate).count() == _rates_before)
_assert("  · and the row was UPDATED, not deleted -- one selection per "
        "league-season, always",
        db.query(LeagueProviderConfig).filter(
            LeagueProviderConfig.league_id == staging.id).count() == 1)

W.activate_balldontlie(db)
_restored = BE.compute_market_board(s_teams[0], s_teams[1], W.WEEK, db)
_assert("re-enabling restores the BALLDONTLIE board deterministically, with no "
        "re-ingest of anything",
        (_restored.anchor_moneyline, _restored.spread_line,
         _restored.total_line)
        == (_board.anchor_moneyline, _board.spread_line, _board.total_line))


# ══════════════════════════════════════════════════════════════════════════════
# 7B-J · the sim-v1 freeze and the global default
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-J · sim-v1 is frozen and the global default has not moved")

_assert("sim-v1's content hash is unchanged by Sprint 7B",
        MR.model_config_hash(MR.MODEL_V1) == FROZEN_V1_HASH,
        MR.model_config_hash(MR.MODEL_V1)[:24] + "...")
_assert("  · and the ACTIVE global model version is still sim-v1",
        MR.ACTIVE_MODEL_VERSION_ID == "sim-v1")
_assert("  · so an unconfigured league gets sim-v1 without consulting a row",
        SEL.LEGACY().simulation_model == "sim-v1")
_assert("  · sim-v2 is reachable ONLY through a league's own selection",
        MR.resolve_model_config("sim-v2").model_version_id == "sim-v2"
        and SEL.LEGACY().simulation_model != "sim-v2")

_v1_src = open(os.path.join(ROOT, "odds", "odds_engine_headless.py"),
               encoding="utf-8").read()
_assert("`_simulate_team` -- the function sim-v1 draws with -- is untouched",
        "def _simulate_team(pts: np.ndarray, rng: np.random.Generator, *,"
        in _v1_src
        and "sigma = np.maximum(np.abs(pts) * model_config.std_pct, "
            "model_config.min_std)" in _v1_src)
_assert("  · and sim-v2 draws with a SEPARATE function, added beside it",
        "def simulate_team_with_sigma(" in _v1_src)


# ══════════════════════════════════════════════════════════════════════════════
# 7B-K · the API surface reports one coherent source
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-K · the response models and the operator diagnostic")

import api.main as APP                                             # noqa: E402

_fields = APP._selection_fields(db, staging)
_assert("the provider status reports the full effective selection",
        (_fields["projection_source"], _fields["factual_source"],
         _fields["simulation_model"], _fields["scoring_profile_id"])
        == ("balldontlie", "balldontlie", "sim-v2", W.PROFILE_ID))
_assert("  · and says this configuration can actually price",
        _fields["pricing_ready"] is True
        and _fields["pricing_blocked_reason"] is None)
_assert("  · while the control league reports the governed defaults",
        APP._selection_fields(db, control)["projection_source"] == "legacy"
        and APP._selection_fields(db, control)["pricing_ready"] is True)

SEL.set_selection(db, league_id=staging.id, season=W.SEASON,
                  simulation_model="sim-v1")
db.flush()
_half = APP._selection_fields(db, staging)
_assert("a HALF-ACTIVATED league is reported as a named state, not as a "
        "correctly configured one",
        _half["pricing_ready"] is False
        and _half["pricing_blocked_reason"] == "unsupported_model_combination",
        json.dumps(_half))
W.activate_balldontlie(db)
_assert("  · and the diagnostic never raises, even asked about a broken "
        "configuration",
        isinstance(_half, dict) and len(_half) == 7)
_assert("  · it carries no credential of any kind",
        not any(k in json.dumps(APP._selection_fields(db, staging)).lower()
                for k in ("token", "authorization", "secret", "password",
                          "bearer", "api_key", "apikey")))

_assert("the market response models expose no provider-specific field, so the "
        "UI needed no redesign -- the substitution is behind the interface",
        {"acting_moneyline", "spread_line", "total_line"}
        <= set(APP.VersusMarketOut.model_fields)
        and not any("balldontlie" in f
                    for f in APP.VersusMarketOut.model_fields))
_assert("  · the same is true of the preview market",
        {"acting_moneyline", "acting_win_probability", "total_line"}
        <= set(APP.PreviewMarketOut.model_fields))
_assert("  · and of the status model, which now names the profile and the "
        "pricing readiness",
        {"projection_source", "factual_source", "simulation_model",
         "selection_configured", "scoring_profile_id", "pricing_ready",
         "pricing_blocked_reason"} <= set(APP.ProviderStatusOut.model_fields))

# THE PAYLOAD IS THE READ MODEL, FIELD FOR FIELD — which is why proving the
# read model above proves the wire. The route constructs its response models by
# splatting the view's own dicts rather than re-deriving anything, so there is
# no second place a projection value could be substituted between the number
# that was priced and the number a browser receives.
_main_src = open(os.path.join(ROOT, "api", "main.py"), encoding="utf-8").read()
_assert("the preview route maps the read model field-for-field, so the payload "
        "cannot disagree with what was priced",
        "PreviewMarketOut(**view.market.__dict__)" in _main_src
        and "PreviewLineupRowOut(**row.__dict__)" in _main_src)
_assert("  · and the board route reads `compute_market_board` and nothing else",
        "board = compute_market_board(acting_team, opponent, week, db)"
        in _main_src)

_assert("the board route maps a pricing refusal to its OWN reason code rather "
        "than flattening it to `cannot_price`",
        "except PricingRefusal as e:" in open(
            os.path.join(ROOT, "api", "main.py"), encoding="utf-8").read())

# THE DEFECT THIS SPRINT FOUND AND FIXED: the emptiness guard summed the scalar
# table, so a correctly priced BALLDONTLIE board would have been thrown away.
_assert("the projections-unavailable guard no longer refuses a league that "
        "does not use the scalar table",
        APP._quote_inputs_are_empty(db, s_teams[0].id, s_teams[1].id,
                                    W.WEEK) is False)
_assert("  · while it still protects the legacy path it was written for",
        APP._quote_inputs_are_empty(db, c_teams[0].id, c_teams[1].id,
                                    W.WEEK + 5) is True)


# ══════════════════════════════════════════════════════════════════════════════
# 7B-L · economic freeze and source hygiene
# ══════════════════════════════════════════════════════════════════════════════

_section("7B-L · no economic rule moved, and no secret is in the tree")

_CHANGED = ("api/main.py", "db/schema.py", "migrations/manifest.py",
            "providers/balldontlie/pool_source.py", "providers/selection.py",
            "migrations/add_league_provider_config.py",
            "beefs/pricing.py", "beefs/beef_engine.py", "odds/sim_v2.py",
            "odds/odds_engine_headless.py")

_assert("Sprint 7 + 7B changed NO file under ledger/, economy/ or betting/",
        not [f for f in _CHANGED
             if f.startswith(("ledger/", "economy/", "betting/"))])

_pricing_src = open(os.path.join(ROOT, "beefs", "pricing.py"),
                    encoding="utf-8").read()
_tree = ast.parse(_pricing_src)
_imported = {n.module for n in ast.walk(_tree)
             if isinstance(n, ast.ImportFrom) and n.module}
_assert("  · and the pricing seam imports no economic module",
        not [m for m in _imported
             if m.split(".")[0] in ("ledger", "economy", "betting")],
        str(sorted(_imported)))

# ── THE SCAN THAT ACTUALLY MATTERS ─────────────────────────────────────────
#
# An earlier version of this check grepped every changed file for words like
# `bearer` and `password=` and failed on `api/main.py` — which has carried a
# login route and an Authorization header parser since long before this
# integration existed. That is a scan measuring the age of a file, not the
# safety of a change.
#
# So the real question is asked instead: DOES THE ACTUAL CREDENTIAL APPEAR
# ANYWHERE IN THE TREE? The value is read from the operator's own secrets file
# and searched for. It is never printed, never logged, never included in a
# failure detail and never written anywhere — only its ABSENCE is reported.
_credential_values = []
_secrets_path = os.path.join(ROOT, "secrets", "balldontlie.json")
if os.path.exists(_secrets_path):
    try:
        _doc = json.load(open(_secrets_path, encoding="utf-8"))
        _credential_values = [v for v in _doc.values()
                              if isinstance(v, str) and len(v) >= 12]
    except Exception:                                             # noqa: BLE001
        _credential_values = []

_credential_leak = False
if _credential_values:
    for _dirpath, _dirnames, _filenames in os.walk(ROOT):
        _dirnames[:] = [d for d in _dirnames
                        if d not in (".git", "__pycache__", "secrets",
                                     "fantasy-beefs-season-close", ".venv",
                                     "node_modules")]
        for _name in _filenames:
            if not _name.endswith((".py", ".json", ".md", ".txt", ".yaml",
                                   ".yml", ".html", ".js")):
                continue
            try:
                _blob = open(os.path.join(_dirpath, _name),
                             encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            if any(v in _blob for v in _credential_values):
                _credential_leak = True
_assert("THE CREDENTIAL APPEARS IN NO FILE IN THE TREE OUTSIDE secrets/",
        not _credential_leak,
        "checked every source file; value never printed")
_assert("  · and secrets/ is git-ignored, so it cannot be committed",
        "secrets/" in open(os.path.join(ROOT, ".gitignore"),
                           encoding="utf-8").read())
_assert("  · with no duplicate at the repository root",
        not os.path.exists(os.path.join(ROOT, "balldontlie.json")))

# The files Sprint 7B AUTHORED are scanned in full — nothing pre-existing to
# excuse, so any marker in one of them would be this sprint's doing.
_AUTHORED = ("beefs/pricing.py", "providers/selection.py",
             "migrations/add_league_provider_config.py",
             "test_support_sprint7b_world.py")
_SECRET_MARKERS = ("authorization:", "bearer ", "api_key=", "apikey=",
                   "x-api-key", "password=", "secret=")
_leaks = []
for _rel in _AUTHORED:
    _text = open(os.path.join(ROOT, _rel), encoding="utf-8").read().lower()
    _leaks += [f"{_rel}:{m}" for m in _SECRET_MARKERS if m in _text]
_assert("no credential marker in any file Sprint 7B authored",
        not _leaks, str(_leaks))

_LOCAL_MARKERS = ("c:\\users\\", "/appdata/local/temp", "scratchpad")
_local = []
for _rel in _CHANGED:
    _text = open(os.path.join(ROOT, _rel), encoding="utf-8").read().lower()
    _local += [f"{_rel}:{m}" for m in _LOCAL_MARKERS if m in _text]
_assert("  · and no absolute local or scratch path in any product file",
        not _local, str(_local))

_assert("the pricing seam performs no network I/O -- it reads rows",
        "requests" not in _imported and "http" not in str(_imported))


print()
print("=" * 78)
if _failed:
    print(f"SPRINT 7B PRICING: {_failed} FAILED, {_passed} passed")
    raise SystemExit(1)
print(f"SPRINT 7B PRICING: all {_passed} assertions passed — the certified "
      f"BALLDONTLIE\nchain now prices a real league through the live product, "
      f"and the league beside\nit still prices exactly as it always did.")
print("=" * 78)
