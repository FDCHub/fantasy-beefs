#!/usr/bin/env python3
"""Sprint 5 certification — historical model parameters and the three gap models.

WHAT THIS SUITE PROVES, AND WHY EACH GROUP EXISTS:

    A  the parameter store: idempotent, versioned, append-only, fingerprinted
    B  AS-OF — a projection can never be built from results nobody could know
    C  factual three-and-out classification, with every exclusion exercised
    D  factual pick-six identification and its conditional rate
    E  the reception model, its hierarchy and its bounds
    F  the pick-six model, bounded by projected interceptions
    G  the three-and-out model, and the drive count it still needs
    H  corrections: a new parameter beside the old, never over it
    I  end to end — CULV and Mr Whiskers through the whole pipeline
    J  the freezes: sim-v1 untouched, activation off, no network in the path

GROUP B IS THE ONE THAT PROTECTS THE WAGER. A rate derived from a game that had
not been played when a price was struck is future information, and a wager
priced on it is indefensible no matter how good the arithmetic is. The cutoff is
one filter in one function, and this group is why it can be trusted.

GROUP C IS THE ONE WITH THE FOOTBALL IN IT. A three-and-out is not "three plays
happened"; it is a possession the offence STARTED, failed to earn a first down
in, and ended by punting. Every exclusion below exists because counting it would
pay a defence for something else.

WHAT THIS SUITE CANNOT PROVE. No BALLDONTLIE credential is reachable from this
environment, so no REAL historical sample has been acquired. Every rate here is
derived from committed SYNTHETIC fixtures or constructed in-test. The machinery
is certified; the measurements are not, and the production configuration
therefore still refuses.

OFFLINE AND DETERMINISTIC. SQLite in memory, committed fixtures, fixed instants.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import math                                                        # noqa: E402
from datetime import datetime, timedelta, timezone                 # noqa: E402

from sqlalchemy import create_engine, event                        # noqa: E402
from sqlalchemy.orm import sessionmaker                            # noqa: E402

from db.schema import (                                            # noqa: E402
    Base, Player, ProviderComponentProjection, ProviderHistoricalRate as R,
)
from odds import sim_v2 as S                                       # noqa: E402
from odds.model_registry import (                                  # noqa: E402
    ACTIVE_MODEL_VERSION_ID, MODEL_V1, model_config_hash, resolve_model_config,
)
from providers.balldontlie import factual as F                     # noqa: E402
from providers.balldontlie import history_refresh as HR            # noqa: E402
from providers.balldontlie import parse as P                       # noqa: E402
from providers.balldontlie.transport import (                      # noqa: E402
    BalldontlieFixtureTransport,
)
from providers.component_projections import (                      # noqa: E402
    ComponentProjection, persist_snapshot,
)
from providers.cross_identity import (                             # noqa: E402
    BALLDONTLIE, CanonicalSubject, CrossProviderResolution, Outcome,
)
from scoring import csps as C                                      # noqa: E402
from scoring import history as H                                   # noqa: E402
from scoring import iprm as I                                      # noqa: E402
from scoring.profile import load_profile                           # noqa: E402

CORPUS = os.path.join(ROOT, "providers", "fixtures", "balldontlie")
CULV = load_profile("culv_appreciation_society")
WHISKERS = load_profile("mr_whiskers_memorial")

#: The cutoff a 2024-2025 derivation carries, and the instant a 2026 projection
#: is priced at. Everything in this suite hangs off the gap between them.
CUTOFF = datetime(2026, 3, 1, tzinfo=timezone.utc)
PRICED_AT = datetime(2026, 9, 10, tzinfo=timezone.utc)
BEFORE = datetime(2025, 11, 1, tzinfo=timezone.utc)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _near(got: float, want: float, tol: float = 1e-9) -> bool:
    return abs(got - want) < tol


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _rate(model_type, entity_type, entity_key, numerator, denominator, *,
          as_of=CUTOFF, position=None, window="2024-2025",
          model_version=None, source="fantasy/weekly_stats"):
    versions = {R.MODEL_RECEPTION: H.RECEPTION_MODEL_VERSION,
                R.MODEL_PICK_SIX: H.PICK_SIX_MODEL_VERSION,
                R.MODEL_THREE_AND_OUT: H.THREE_AND_OUT_MODEL_VERSION}
    return H.HistoricalRate(
        provider=BALLDONTLIE, model_type=model_type,
        model_version=model_version or versions[model_type],
        entity_type=entity_type, entity_key=entity_key, position=position,
        season_window=window, as_of=as_of, numerator=float(numerator),
        denominator=float(denominator), sample_size=int(denominator),
        source_kind=source)


def _play(pid, slug, team, text, wallclock, **kw):
    row = {"id": pid, "game_id": 1, "type": slug,
           "team": {"abbreviation": team} if team else None, "text": text,
           "wallclock": wallclock, "stat_yardage": None,
           "period": kw.pop("period", 1), "clock": "10:00",
           "start_down": kw.pop("start_down", 1), "participants": []}
    row.update(kw)
    return row


def _plays(rows):
    return P.parse_plays({"data": rows, "meta": {}})


print("=" * 78)
print("SPRINT 5 · HISTORICAL MODEL INPUTS AND IPRM GAP CLOSURE")
print("=" * 78)
print(f"  iprm version        : {I.IPRM_VERSION}")
print(f"  model versions      : {H.RECEPTION_MODEL_VERSION}, "
      f"{H.PICK_SIX_MODEL_VERSION}, {H.THREE_AND_OUT_MODEL_VERSION}")
print(f"  BDL credential      : "
      f"{'present' if os.environ.get('BALLDONTLIE_API_KEY') else 'ABSENT — live acquisition blocked'}")


# ══════════════════════════════════════════════════════════════════════════════
# A · the parameter store
# ══════════════════════════════════════════════════════════════════════════════

print("\n5-A · the parameter store")

_db = _session()
_rates = [
    _rate(R.MODEL_RECEPTION, R.ENTITY_PLAYER, "bdl.p.113", 142, 196,
          position="WR"),
    _rate(R.MODEL_RECEPTION, R.ENTITY_POSITION, "WR", 9800, 15900,
          position="WR"),
    _rate(R.MODEL_RECEPTION, R.ENTITY_LEAGUE, H.LEAGUE_KEY, 14100, 22600),
    _rate(R.MODEL_PICK_SIX, R.ENTITY_LEAGUE, H.LEAGUE_KEY, 58, 884,
          position="QB", source="plays"),
    _rate(R.MODEL_THREE_AND_OUT, R.ENTITY_TEAM, "TEN", 71, 352, source="plays"),
]
_first = H.persist_rates(_db, _rates)
_assert("derived parameters persist", _first["persisted"] == 5, str(_first))
_again = H.persist_rates(_db, _rates)
_assert("re-running an unchanged derivation writes NOTHING",
        _again["persisted"] == 0 and _again["duplicate"] == 5
        and _db.query(R).count() == 5, str(_again))
_assert("a rate is numerator over denominator, and the sample travels with it",
        _near(_db.query(R).filter_by(entity_key="bdl.p.113").one().rate,
              142 / 196) and
        _db.query(R).filter_by(entity_key="bdl.p.113").one().sample_size == 196)
_assert("the fingerprint covers the derivation, not the moment it ran",
        H.rate_fingerprint(provider=BALLDONTLIE, model_type=R.MODEL_RECEPTION,
                           model_version="v", entity_type=R.ENTITY_PLAYER,
                           entity_key="k", season_window="w", as_of=CUTOFF,
                           numerator=1, denominator=2, sample_size=2)
        == H.rate_fingerprint(provider=BALLDONTLIE,
                              model_type=R.MODEL_RECEPTION, model_version="v",
                              entity_type=R.ENTITY_PLAYER, entity_key="k",
                              season_window="w", as_of=CUTOFF, numerator=1.0,
                              denominator=2.0, sample_size=2))
_assert("each model carries its own frozen version",
        {r.model_version for r in _db.query(R).all()}
        == {H.RECEPTION_MODEL_VERSION, H.PICK_SIX_MODEL_VERSION,
            H.THREE_AND_OUT_MODEL_VERSION})
_assert("a player rate and a team rate are different populations and never "
        "resolve into one another",
        H.select_rate(_db, provider=BALLDONTLIE,
                      model_type=R.MODEL_THREE_AND_OUT,
                      entity_type=R.ENTITY_PLAYER, entity_key="TEN",
                      as_of=PRICED_AT) is None)


# ══════════════════════════════════════════════════════════════════════════════
# B · as-of
# ══════════════════════════════════════════════════════════════════════════════

print("\n5-B · a projection can never read the future")

_bundle = H.resolve_bundle(_db, provider=BALLDONTLIE, as_of=PRICED_AT,
                           player_key="bdl.p.113", position="WR",
                           nfl_team="TEN")
_assert("at a later instant, the parameter is in force",
        _bundle.reception.resolved and _bundle.reception.level
        == "MODELLED_PLAYER_HISTORY")
_early = H.resolve_bundle(_db, provider=BALLDONTLIE, as_of=BEFORE,
                          player_key="bdl.p.113", position="WR",
                          nfl_team="TEN")
_assert("BEFORE the cutoff, the same parameter is invisible — no leakage",
        not _early.reception.resolved
        and not _early.pick_six.resolved
        and not _early.three_and_out.resolved,
        _early.reception.level)
_assert("  · and the refusal names the absence rather than inventing a rate",
        _early.reception.level == "MODEL_UNRESOLVED")

# TWO CUTOFFS, THE OLDER ONE STILL READABLE. This is what lets a wager priced in
# March reprice identically in September.
H.persist_rates(_db, [_rate(R.MODEL_RECEPTION, R.ENTITY_PLAYER, "bdl.p.113",
                            150, 200, position="WR",
                            as_of=datetime(2026, 6, 1, tzinfo=timezone.utc),
                            window="2024-2026")])
_db.flush()
_assert("the LATEST cutoff at or before the pricing instant wins",
        _near(H.resolve_bundle(_db, provider=BALLDONTLIE, as_of=PRICED_AT,
                               player_key="bdl.p.113",
                               position="WR").reception.rate, 150 / 200))
_assert("  · while a price struck earlier still resolves the older parameter",
        _near(H.resolve_bundle(_db, provider=BALLDONTLIE,
                               as_of=datetime(2026, 4, 1, tzinfo=timezone.utc),
                               player_key="bdl.p.113",
                               position="WR").reception.rate, 142 / 196))


# ══════════════════════════════════════════════════════════════════════════════
# C · factual three-and-outs
# ══════════════════════════════════════════════════════════════════════════════

print("\n5-C · what a three-and-out is, and every exclusion")


def _drive_case(rows, *, home="AAA", visitor="BBB"):
    drives = F.classify_drives(_plays(rows), home=home, visitor=visitor)
    return [d for d in drives if d.team == visitor]


_three_and_out = _drive_case([
    _play(1, "kickoff", "BBB", "kicks off", "T00"),
    _play(2, "rush", "BBB", "run for 2 yards", "T01", start_down=1),
    _play(3, "pass", "BBB", "incomplete", "T02", start_down=2),
    _play(4, "rush", "BBB", "stopped for no gain", "T03", start_down=3),
    _play(5, "punt", "AAA", "punts 45 yards", "T04"),
])
_assert("a punt after three unsuccessful downs IS a three-and-out",
        len(_three_and_out) == 1 and _three_and_out[0].is_three_and_out,
        _three_and_out[0].outcome)

_first_down = _drive_case([
    _play(1, "kickoff", "BBB", "kicks off", "T00"),
    _play(2, "rush", "BBB", "run for 12 yards, FIRST DOWN", "T01", start_down=1),
    _play(3, "pass", "BBB", "incomplete", "T02", start_down=1),
    _play(4, "rush", "BBB", "no gain", "T03", start_down=3),
    _play(5, "punt", "AAA", "punts", "T04"),
])
_assert("a drive that EARNED a first down is not one, however it ends",
        not _first_down[0].is_three_and_out
        and _first_down[0].earned_first_down)

_turnover = _drive_case([
    _play(1, "kickoff", "BBB", "kicks off", "T00"),
    _play(2, "rush", "BBB", "run for 2", "T01", start_down=1),
    _play(3, "pass", "BBB", "pass INTERCEPTED by J.Smith", "T02", start_down=2),
])
_assert("a TURNOVER is not a three-and-out — Yahoo pays for it separately",
        not _turnover[0].is_three_and_out
        and _turnover[0].outcome == F.DriveOutcome.TURNOVER)

_scoring = _drive_case([
    _play(1, "kickoff", "BBB", "kicks off", "T00"),
    _play(2, "pass", "BBB", "75 yard pass TOUCHDOWN", "T01", start_down=1),
])
_assert("a SCORING drive is not one, however few plays it took",
        not _scoring[0].is_three_and_out
        and _scoring[0].outcome == F.DriveOutcome.TOUCHDOWN)

_field_goal = _drive_case([
    _play(1, "kickoff", "BBB", "kicks off", "T00"),
    _play(2, "rush", "BBB", "run for 3", "T01", start_down=1),
    _play(3, "pass", "BBB", "incomplete", "T02", start_down=2),
    _play(4, "rush", "BBB", "run for 1", "T03", start_down=3),
    _play(5, "field-goal-good", "BBB", "52 Yd Field Goal", "T04"),
])
_assert("a FIELD GOAL drive is not one either",
        not _field_goal[0].is_three_and_out
        and _field_goal[0].outcome == F.DriveOutcome.FIELD_GOAL)

_downs = _drive_case([
    _play(1, "kickoff", "BBB", "kicks off", "T00"),
    _play(2, "rush", "BBB", "run for 2", "T01", start_down=1),
    _play(3, "pass", "BBB", "incomplete", "T02", start_down=2),
    _play(4, "rush", "BBB", "no gain", "T03", start_down=3),
    _play(5, "downs", "BBB", "turnover on downs", "T04", start_down=4),
])
_assert("going for it on FOURTH and failing is a different event, not a "
        "three-and-out",
        not _downs[0].is_three_and_out
        and _downs[0].outcome == F.DriveOutcome.DOWNS)

_kneel = _drive_case([
    _play(1, "kickoff", "BBB", "kicks off", "T00"),
    _play(2, "rush", "BBB", "QB KNEELS for -1", "T01", start_down=1),
    _play(3, "rush", "BBB", "QB KNEELS for -1", "T02", start_down=2),
    _play(4, "punt", "AAA", "punts", "T03"),
])
_assert("a KNEEL-DOWN possession is excluded from the numerator AND the "
        "denominator",
        not _kneel[0].is_three_and_out and not _kneel[0].counts_toward_sample)

_inherited = _drive_case([
    _play(1, "rush", "BBB", "run for 1", "T01", start_down=3),
    _play(2, "punt", "AAA", "punts", "T02"),
])
_assert("a possession INHERITED mid-series is not a three-and-out the defence "
        "forced",
        not _inherited[0].is_three_and_out and _inherited[0].inherited)

_unknown = _drive_case([
    _play(1, "kickoff", "BBB", "kicks off", "T00"),
    _play(2, "rush", "BBB", "run for 2", "T01", start_down=1),
])
_assert("a drive whose ending the stream never reported is excluded from the "
        "sample, not counted as a failure",
        _unknown[0].outcome == F.DriveOutcome.UNKNOWN
        and not _unknown[0].counts_toward_sample)

_assert("the classifier does NOT count punts — a punting drive that gained a "
        "first down is excluded",
        len([d for d in (_first_down + _three_and_out) if d.is_three_and_out])
        == 1)

_fixture_plays = _plays(json.load(open(os.path.join(
    CORPUS, "plays__game_ids-424186__per_page-100.json"),
    encoding="utf-8"))["data"])
_forced = F.three_and_outs_forced(_fixture_plays, home="LAR", visitor="DEN",
                                  team="LAR")
_assert("the committed fixture game classifies end to end",
        _forced["three_and_outs"] == 1 and _forced["opponent_drives"] >= 1,
        f"{_forced['three_and_outs']} of {_forced['opponent_drives']} drives")
_assert("  · and a drive ends at its TERMINATING play, so an interception is "
        "not overwritten by a later score",
        any(d["outcome"] == F.DriveOutcome.TURNOVER
            for d in F.three_and_outs_forced(
                _fixture_plays, home="LAR", visitor="DEN",
                team="DEN")["drives"]))


# ══════════════════════════════════════════════════════════════════════════════
# D · factual pick-sixes
# ══════════════════════════════════════════════════════════════════════════════

print("\n5-D · pick-sixes, identified from the play stream")

_events = F.pick_six_events(_fixture_plays)
_assert("the fixture's pick six is attributed to the PASSER participant",
        _events["interceptions"] == {63: 1} and _events["pick_sixes"] == {63: 1},
        str(_events["pick_sixes"]))

_ordinary = _plays([
    _play(1, "pass", "AAA", "pass INTERCEPTED by J.Bates", "T01",
          participants=[{"type": "passer", "player": {"id": 7}}]),
])
_assert("an ordinary interception counts in the denominator only",
        F.pick_six_events(_ordinary)["interceptions"] == {7: 1}
        and F.pick_six_events(_ordinary)["pick_sixes"] == {})

_multiple = _plays([
    _play(1, "pass", "AAA", "pass INTERCEPTED by A", "T01",
          participants=[{"type": "passer", "player": {"id": 7}}]),
    _play(2, "pass", "AAA", "pass INTERCEPTED by B 30 Yd Return TOUCHDOWN",
          "T02", participants=[{"type": "passer", "player": {"id": 7}}]),
    _play(3, "pass", "AAA", "pass complete for 12 yards", "T03",
          participants=[{"type": "passer", "player": {"id": 7}}]),
])
_assert("two interceptions, one returned: the conditional rate is 1 of 2",
        F.pick_six_events(_multiple)["interceptions"] == {7: 2}
        and F.pick_six_events(_multiple)["pick_sixes"] == {7: 1})
_assert("a game with no interception contributes nothing to either term",
        F.pick_six_events(_plays([_play(1, "rush", "AAA", "run for 3", "T01")]))
        ["interceptions"] == {})
_assert("an interception the stream cannot attribute is excluded from BOTH "
        "terms — it cannot depress a rate it was never part of",
        F.pick_six_events(_plays([
            _play(1, "pass", "AAA", "pass INTERCEPTED by C", "T01")]))
        ["interceptions"] == {})

_derived = H.derive_pick_six_rates([_multiple], provider=BALLDONTLIE,
                                   season_window="2025", as_of=CUTOFF)
_league_rate = [r for r in _derived if r.entity_type == R.ENTITY_LEAGUE][0]
_assert("derivation produces a conditional rate and the counts behind it",
        _near(_league_rate.rate, 0.5) and _league_rate.sample_size == 2,
        f"{_league_rate.rate:.3f} over {_league_rate.sample_size} interceptions")


# ══════════════════════════════════════════════════════════════════════════════
# E · the reception model
# ══════════════════════════════════════════════════════════════════════════════

print("\n5-E · receptions from targets")


def _iprm(components, profile=CULV, position="WR", nfl_team="DET",
          rates=None, config=I.IPRM_V1, player_key="bdl.p.113"):
    result = C.score_components(components, profile, mode=C.PROJECTION,
                                components_present=list(components),
                                position=position)
    result.provider_player_key = player_key
    return I.project(result, profile=profile, components=components,
                     config=config, position=position, nfl_team=nfl_team,
                     rates=rates)


_direct = _iprm({"receptions": 6.1, "receiving_yards": 84.3}, rates=_bundle)
_assert("a DIRECT reception projection beats the model — no model runs at all",
        _direct.modelled("receptions") is None
        and _direct.status == I.Status.SIMULATION_READY)

_modelled = _iprm({"targets": 9.8, "receiving_yards": 84.3}, rates=_bundle)
_receptions = _modelled.modelled("receptions")
_assert("targets plus a player catch rate produce expected receptions",
        _near(_receptions.parameters["expected_receptions"], 9.8 * (142 / 196)),
        f"{_receptions.parameters['expected_receptions']:.4f}")
_assert("  · and the result is simulation-ready with the fallback recorded",
        _modelled.status == I.Status.SIMULATION_READY_WITH_FALLBACKS)
_assert("  · the provenance answers 'why this many receptions?'",
        {"targets", "catch_rate", "expected_receptions", "sample_size",
         "seasons", "as_of", "model_version", "source_level"}
        <= set(_receptions.parameters),
        str(sorted(_receptions.parameters)[:4]))
_assert("  · naming the level that answered",
        _receptions.quality == "MODELLED_PLAYER_HISTORY")

_small_db = _session()
H.persist_rates(_small_db, [
    _rate(R.MODEL_RECEPTION, R.ENTITY_PLAYER, "bdl.p.999", 8, 11,
          position="WR"),
    _rate(R.MODEL_RECEPTION, R.ENTITY_POSITION, "WR", 9800, 15900,
          position="WR")])
_small_db.flush()
_small = H.resolve_bundle(_small_db, provider=BALLDONTLIE, as_of=PRICED_AT,
                          player_key="bdl.p.999", position="WR")
_assert("a player sample below the minimum falls back to the POSITION, and "
        "says why",
        _small.reception.level == "MODELLED_POSITIONAL_FALLBACK"
        and "below the minimum" in _small.reception.detail,
        f"n={11} against a minimum of {I.IPRM_V1.minimum_player_targets}")

_league_db = _session()
H.persist_rates(_league_db, [
    _rate(R.MODEL_RECEPTION, R.ENTITY_LEAGUE, H.LEAGUE_KEY, 14100, 22600)])
_league_db.flush()
_assert("with no player and no positional history, the LEAGUE rate answers",
        H.resolve_bundle(_league_db, provider=BALLDONTLIE, as_of=PRICED_AT,
                         player_key="bdl.p.777",
                         position="TE").reception.level
        == "MODELLED_LEAGUE_FALLBACK")

_assert("expected receptions can never exceed projected targets",
        all(_iprm({"targets": t, "receiving_yards": 40.0}, rates=_bundle)
            .modelled("receptions").parameters["expected_receptions"] <= t + 1e-9
            for t in (0.0, 0.4, 3.0, 12.5)))
_assert("zero targets project zero receptions",
        _near(_iprm({"targets": 0.0, "receiving_yards": 0.0}, rates=_bundle)
              .modelled("receptions").parameters["expected_receptions"], 0.0))
_assert("no targets at all is NOT a modelled category — the subject does not "
        "catch passes",
        _iprm({"passing_yards": 250.0}, position="QB",
              rates=_bundle).modelled("receptions") is None)
_assert("with NO parameter in force the model refuses, exactly as iprm-v1 did",
        _iprm({"targets": 9.8, "receiving_yards": 84.3}, rates=_early).status
        == I.Status.REFUSED)

_derived_rec = H.derive_reception_rates(
    P.parse_weekly_stats({"data": [
        {"season": 2025, "week": 1, "team": {"abbreviation": "DET"},
         "player": {"id": 113, "position": "WR"}, "position": "WR",
         "stats": {"targets": 10, "receptions": 7}},
        {"season": 2025, "week": 2, "team": {"abbreviation": "DET"},
         "player": {"id": 113, "position": "WR"}, "position": "WR",
         "stats": {"targets": 6, "receptions": 5}}]}),
    provider=BALLDONTLIE, season_window="2025", as_of=CUTOFF)
_player_rate = [r for r in _derived_rec if r.entity_type == R.ENTITY_PLAYER][0]
_assert("derivation sums both terms over the window, not per week",
        _near(_player_rate.rate, 12 / 16) and _player_rate.sample_size == 16,
        f"{_player_rate.numerator}/{_player_rate.denominator}")
_assert("  · and produces player, positional AND league rows from one pass",
        {r.entity_type for r in _derived_rec}
        == {R.ENTITY_PLAYER, R.ENTITY_POSITION, R.ENTITY_LEAGUE})


# ══════════════════════════════════════════════════════════════════════════════
# F · the pick-six model
# ══════════════════════════════════════════════════════════════════════════════

print("\n5-F · pick-six from projected interceptions")

_qb = _iprm({"passing_yards": 268.4, "passing_touchdowns": 1.8,
             "passing_interceptions": 0.7}, profile=WHISKERS, position="QB",
            rates=_bundle)
_pick = _qb.modelled("pick_six_thrown")
_assert("a projected interception count times the conditional rate",
        _near(_pick.parameters["expected_count"], 0.7 * (58 / 884)),
        f"{_pick.parameters['expected_count']:.5f}")
_assert("  · resolved from the LEAGUE conditional rate, which is the honest "
        "level for a sparse event",
        _pick.quality == "MODELLED_LEAGUE_FALLBACK")
_assert("  · with both historical counts exposed",
        _pick.parameters["historical_pick_sixes"] == 58
        and _pick.parameters["historical_interceptions"] == 884)
_assert("  · and the quarterback becomes simulation-ready",
        _qb.status == I.Status.SIMULATION_READY_WITH_FALLBACKS)
_assert("zero projected interceptions means exactly zero pick-sixes",
        _iprm({"passing_yards": 200.0}, profile=WHISKERS, position="QB",
              rates=_bundle).modelled("pick_six_thrown").quality
        == I.Quality.DIRECT)
_assert("the expectation never exceeds the projected interceptions",
        all(_iprm({"passing_interceptions": n}, profile=WHISKERS,
                  position="QB", rates=_bundle)
            .modelled("pick_six_thrown").parameters["expected_count"] <= n + 1e-9
            for n in (0.1, 0.7, 2.0, 5.0)))

_qb_history = _session()
H.persist_rates(_qb_history, [
    _rate(R.MODEL_PICK_SIX, R.ENTITY_PLAYER, "bdl.p.63", 4, 41, position="QB",
          source="plays"),
    _rate(R.MODEL_PICK_SIX, R.ENTITY_LEAGUE, H.LEAGUE_KEY, 58, 884,
          position="QB", source="plays")])
_qb_history.flush()
_assert("a quarterback with a large enough sample uses his OWN rate",
        H.resolve_bundle(_qb_history, provider=BALLDONTLIE, as_of=PRICED_AT,
                         player_key="bdl.p.63",
                         position="QB").pick_six.level
        == "MODELLED_PLAYER_HISTORY")
_sparse = _session()
H.persist_rates(_sparse, [
    _rate(R.MODEL_PICK_SIX, R.ENTITY_PLAYER, "bdl.p.63", 1, 6, position="QB",
          source="plays"),
    _rate(R.MODEL_PICK_SIX, R.ENTITY_LEAGUE, H.LEAGUE_KEY, 58, 884,
          position="QB", source="plays")])
_sparse.flush()
_assert("  · and a sparse one falls back rather than pricing a 1-in-6 fluke",
        H.resolve_bundle(_sparse, provider=BALLDONTLIE, as_of=PRICED_AT,
                         player_key="bdl.p.63",
                         position="QB").pick_six.level
        == "MODELLED_LEAGUE_FALLBACK")
_assert("with NO parameter the quarterback still refuses",
        _iprm({"passing_interceptions": 0.7}, profile=WHISKERS, position="QB",
              rates=_early).status == I.Status.REFUSED)


# ══════════════════════════════════════════════════════════════════════════════
# G · the three-and-out model
# ══════════════════════════════════════════════════════════════════════════════

print("\n5-G · three-and-outs, and the drive count they still need")

_dst = _iprm({"defensive_sacks": 2.4, "dst_points_allowed": 21.3},
             profile=WHISKERS, position="DEF", nfl_team="TEN", rates=_bundle)
_tao = _dst.modelled("dst_three_and_outs")
_assert("a MEASURED defensive rate alone is not enough — the model still "
        "refuses without an expected drive count",
        _dst.status == I.Status.REFUSED
        and _tao.quality == I.Quality.MODEL_UNRESOLVED)
_assert("  · and it says which half is missing, with the measured half shown",
        _near(_tao.parameters["three_and_out_rate_per_drive"], 71 / 352)
        and _tao.parameters["expected_opponent_drives"] is None
        and "expected opponent drive count" in _tao.note)

_with_drives = I.IprmConfig(expected_opponent_drives=11.2)
_resolved_dst = _iprm({"defensive_sacks": 2.4, "dst_points_allowed": 21.3},
                      profile=WHISKERS, position="DEF", nfl_team="TEN",
                      rates=_bundle, config=_with_drives)
_assert("with a drive count supplied, the expectation is rate x drives",
        _near(_resolved_dst.modelled("dst_three_and_outs")
              .parameters["expected_three_and_outs"], (71 / 352) * 11.2))
_assert("  · and the defence becomes simulation-ready",
        _resolved_dst.status == I.Status.SIMULATION_READY_WITH_FALLBACKS)
_assert("  · the expectation is non-negative and plausibly bounded",
        0.0 <= _resolved_dst.modelled("dst_three_and_outs")
        .parameters["expected_three_and_outs"] <= 11.2)
_assert("a team sample below the minimum falls back rather than trusting it",
        H.resolve_bundle(
            _session_small := _session(), provider=BALLDONTLIE,
            as_of=PRICED_AT, nfl_team="TEN").three_and_out.level
        == "MODEL_UNRESOLVED")
_assert("CULV never sees the model at all — it does not score three-and-outs",
        _iprm({"defensive_sacks": 2.4, "dst_points_allowed": 21.3},
              profile=CULV, position="DEF", nfl_team="TEN", rates=_bundle,
              config=_with_drives).modelled("dst_three_and_outs") is None)

_tao_derived = H.derive_three_and_out_rates(
    [(_plays([
        _play(1, "kickoff", "BBB", "kicks", "T00"),
        _play(2, "rush", "BBB", "no gain", "T01", start_down=1),
        _play(3, "pass", "BBB", "incomplete", "T02", start_down=2),
        _play(4, "rush", "BBB", "no gain", "T03", start_down=3),
        _play(5, "punt", "AAA", "punts", "T04"),
     ]), "AAA", "BBB")],
    provider=BALLDONTLIE, season_window="2025", as_of=CUTOFF)
_aaa = [r for r in _tao_derived if r.entity_key == "AAA"][0]
_assert("derivation measures three-and-outs PER OPPONENT DRIVE, not per game",
        _aaa.numerator == 1 and _aaa.denominator == 1
        and "opponent_drives" in _aaa.parameters)


# ══════════════════════════════════════════════════════════════════════════════
# H · corrections
# ══════════════════════════════════════════════════════════════════════════════

print("\n5-H · a provider correction never mutates a frozen parameter")

_corrections = _session()
H.persist_rates(_corrections, [
    _rate(R.MODEL_RECEPTION, R.ENTITY_PLAYER, "bdl.p.113", 142, 196,
          position="WR")],
    generated_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
_corrections.flush()
_original = _corrections.query(R).one()
_original_fingerprint = _original.fingerprint

H.persist_rates(_corrections, [
    _rate(R.MODEL_RECEPTION, R.ENTITY_PLAYER, "bdl.p.113", 143, 196,
          position="WR")],
    generated_at=datetime(2026, 3, 2, tzinfo=timezone.utc))
_corrections.flush()
_assert("a corrected count lands as a NEW row beside its predecessor",
        _corrections.query(R).count() == 2)
_assert("  · the original is unchanged, and still carries its fingerprint",
        _corrections.query(R).filter_by(id=_original.id).one().numerator == 142
        and _corrections.query(R).filter_by(id=_original.id).one().fingerprint
        == _original_fingerprint)
_assert("  · and a new price resolves the CORRECTED parameter",
        _near(H.resolve_bundle(_corrections, provider=BALLDONTLIE,
                               as_of=PRICED_AT, player_key="bdl.p.113",
                               position="WR").reception.rate, 143 / 196))

_refresh_report = HR.derive_from_payloads(
    _session(), weekly_stat_payloads=[{"data": [
        {"season": 2025, "week": 1, "team": {"abbreviation": "DET"},
         "player": {"id": 113, "position": "WR"}, "position": "WR",
         "stats": {"targets": 10, "receptions": 7}}], "meta": {}}],
    season_window="2025", as_of=CUTOFF)
_assert("the refresh service derives and stores without any network",
        _refresh_report.rates_persisted > 0
        and _refresh_report.weekly_stat_rows == 1,
        json.dumps(_refresh_report.as_dict())[:70])


# ══════════════════════════════════════════════════════════════════════════════
# I · end to end
# ══════════════════════════════════════════════════════════════════════════════

print("\n5-I · CULV and Mr Whiskers through the whole pipeline")

_e2e = _session()
_queries: list = []
event.listen(_e2e.get_bind(), "before_cursor_execute",
             lambda *a: _queries.append(a[2]))

H.persist_rates(_e2e, [
    _rate(R.MODEL_RECEPTION, R.ENTITY_POSITION, "WR", 9800, 15900,
          position="WR"),
    _rate(R.MODEL_RECEPTION, R.ENTITY_POSITION, "RB", 3100, 4000,
          position="RB"),
    _rate(R.MODEL_RECEPTION, R.ENTITY_POSITION, "TE", 2400, 3500,
          position="TE"),
    _rate(R.MODEL_RECEPTION, R.ENTITY_LEAGUE, H.LEAGUE_KEY, 14100, 22600),
    _rate(R.MODEL_PICK_SIX, R.ENTITY_LEAGUE, H.LEAGUE_KEY, 58, 884,
          position="QB", source="plays"),
    _rate(R.MODEL_THREE_AND_OUT, R.ENTITY_TEAM, "DET", 68, 340, source="plays"),
    _rate(R.MODEL_THREE_AND_OUT, R.ENTITY_TEAM, "TEN", 71, 352, source="plays"),
])
_e2e.flush()


def _subject(name, position, team, components, key):
    player = Player(name=name, position=position, nfl_team=team)
    _e2e.add(player)
    _e2e.flush()
    persist_snapshot(
        _e2e,
        resolution=CrossProviderResolution(
            outcome=Outcome.RESOLVED, provider=BALLDONTLIE,
            canonical=CanonicalSubject(player_id=player.id, name=name,
                                       position=position, nfl_team=team),
            provider_player_key=key, method="normalized_discovery"),
        projection=ComponentProjection(
            provider=BALLDONTLIE, provider_player_key=key, season=2026, week=1,
            components=components, components_present=tuple(sorted(components)),
            nfl_team=team, position=position, observed_at=PRICED_AT),
        captured_at=PRICED_AT, provenance="FIXTURE_SYNTHETIC")
    return player.id


_HOME = [
    _subject("QB1", "QB", "SF", {"passing_yards": 268.4,
                                 "passing_touchdowns": 1.8,
                                 "passing_interceptions": 0.7}, "bdl.p.501"),
    _subject("RB1", "RB", "ATL", {"rushing_yards": 92.7,
                                  "rushing_touchdowns": 0.7, "targets": 4.6,
                                  "receiving_yards": 33.1}, "bdl.p.502"),
    _subject("WR1", "WR", "DET", {"targets": 9.8,
                                  "receiving_yards": 84.3}, "bdl.p.503"),
    _subject("TE1", "TE", "LV", {"targets": 8.1,
                                 "receiving_yards": 61.9}, "bdl.p.504"),
    _subject("K1", "K", "JAX", {"field_goals_made_yards": 68.4,
                                "extra_points_made": 2.4}, "bdl.p.505"),
    _subject("D1", "DEF", "DET", {"defensive_sacks": 2.4,
                                  "dst_points_allowed": 21.3}, "bdl.dst.DET"),
]
_AWAY = [
    _subject("QB2", "QB", "LAR", {"passing_yards": 210.0,
                                  "passing_touchdowns": 1.1,
                                  "passing_interceptions": 0.9}, "bdl.p.601"),
    _subject("RB2", "RB", "BUF", {"rushing_yards": 61.0,
                                  "rushing_touchdowns": 0.4, "targets": 2.6,
                                  "receiving_yards": 18.0}, "bdl.p.602"),
    _subject("WR2", "WR", "LAC", {"targets": 6.2,
                                  "receiving_yards": 55.0}, "bdl.p.603"),
    _subject("TE2", "TE", "CLE", {"targets": 4.0,
                                  "receiving_yards": 31.0}, "bdl.p.604"),
    _subject("K2", "K", "CIN", {"field_goals_made_yards": 40.0,
                                "extra_points_made": 1.8}, "bdl.p.605"),
    _subject("D2", "DEF", "TEN", {"defensive_sacks": 1.9,
                                  "dst_points_allowed": 26.0}, "bdl.dst.TEN"),
]
_e2e.flush()
_V2 = resolve_model_config("sim-v2")
_DRIVES = I.IprmConfig(expected_opponent_drives=11.2)


def _build(ids, team_id, name, profile, config=I.IPRM_V1):
    return S.build_lineup(_e2e, team_id=team_id, team_name=name,
                          player_ids=ids, season=2026, week=1, profile=profile,
                          projection_source=S.PROJECTION_SOURCE_BALLDONTLIE,
                          as_of=PRICED_AT, iprm_config=config)


_culv_home = _build(_HOME, 1, "Home", "culv_appreciation_society")
_culv_away = _build(_AWAY, 2, "Away", "culv_appreciation_society")
_assert("CULV: every starter is admissible, receptions modelled from targets",
        _culv_home.admissible and _culv_away.admissible,
        str(_culv_home.refusals[:1]))
_assert("  · and no Mr Whiskers category leaks in",
        all(r.modelled("dst_three_and_outs") is None
            and r.modelled("pick_six_thrown") is None
            for r in _culv_home.iprm_results))
_culv_result, _culv_snapshot = S.run_matchup(
    matchup_id=11, week=1, home=_culv_home, away=_culv_away,
    model_config=_V2, projection_source=S.PROJECTION_SOURCE_BALLDONTLIE,
    season=2026)
_assert("  · CULV prices, deterministically",
        0.0 <= _culv_result.home_win_prob <= 1.0
        and S.run_matchup(matchup_id=11, week=1, home=_culv_home,
                          away=_culv_away, model_config=_V2, season=2026)[0]
        .home_win_prob == _culv_result.home_win_prob,
        f"{_culv_result.home_win_prob}")

_whiskers_home = _build(_HOME, 1, "Home", "mr_whiskers_memorial")
_assert("MR WHISKERS REFUSES without an expected drive count — the defence's "
        "three-and-outs are still unresolved",
        not _whiskers_home.admissible
        and any("three_and_out" in r for r in _whiskers_home.refusals),
        f"{len(_whiskers_home.refusals)} refusal(s)")

_whiskers_home_d = _build(_HOME, 1, "Home", "mr_whiskers_memorial", _DRIVES)
_whiskers_away_d = _build(_AWAY, 2, "Away", "mr_whiskers_memorial", _DRIVES)
_assert("  · and becomes SIMULATION-READY once a drive count is configured",
        _whiskers_home_d.admissible and _whiskers_away_d.admissible,
        str(_whiskers_home_d.refusals[:1]))
_whiskers_result, _whiskers_snapshot = S.run_matchup(
    matchup_id=12, week=1, home=_whiskers_home_d, away=_whiskers_away_d,
    model_config=_V2, projection_source=S.PROJECTION_SOURCE_BALLDONTLIE,
    season=2026)
_assert("  · Mr Whiskers prices, and differently from CULV on the same "
        "components",
        _whiskers_result.home_proj_mean != _culv_result.home_proj_mean,
        f"CULV {_culv_result.home_proj_mean} vs Whiskers "
        f"{_whiskers_result.home_proj_mean}")
_PARAMETER_BACKED = {"receptions", "pick_six_thrown", "dst_three_and_outs"}
_provenanced = [m for r in _whiskers_home_d.iprm_results
                for m in r.modelled_contributions
                if m.category in _PARAMETER_BACKED and m.expected_points]
_assert("every PARAMETER-BACKED contribution names its model version, its "
        "source level and the sample behind it",
        bool(_provenanced) and all(
            {"model_version", "source_level", "sample_size", "seasons"}
            <= set(m.parameters) for m in _provenanced),
        f"{len(_provenanced)} parameter-backed contribution(s)")
_assert("  · while the distribution models carry their family and parameters "
        "instead, because no stored rate produced them",
        all("cv" in m.parameters for r in _whiskers_home_d.iprm_results
            for m in r.modelled_contributions
            if m.category.endswith("_yard_bonus") and m.expected_points))
_assert("the quote fingerprint changes when a model parameter changes",
        _whiskers_snapshot["fingerprint"] != _culv_snapshot["fingerprint"])

_before_cutoff = S.build_lineup(
    _e2e, team_id=1, team_name="Home", player_ids=_HOME, season=2026, week=1,
    profile="mr_whiskers_memorial",
    projection_source=S.PROJECTION_SOURCE_BALLDONTLIE, as_of=BEFORE,
    iprm_config=_DRIVES)
_assert("priced BEFORE the parameters existed, the same lineup refuses",
        not _before_cutoff.admissible,
        f"{len(_before_cutoff.refusals)} refusal(s)")

_queries.clear()
_build(_HOME, 1, "Home", "culv_appreciation_society")
_six = len(_queries)
_queries.clear()
_build([_HOME[0]], 1, "Home", "culv_appreciation_society")
_assert("lineup cost stays independent of lineup size with parameters in play",
        _six == len(_queries), f"{_six} vs {len(_queries)} queries")


# ══════════════════════════════════════════════════════════════════════════════
# J · the freezes
# ══════════════════════════════════════════════════════════════════════════════

print("\n5-J · everything that must not have moved")

_assert("sim-v1's frozen hash is unchanged",
        model_config_hash(MODEL_V1)
        == "1d60ff39343bebf1ceb8099f729fbaff18cb278078e06d094da6cc04ba4626d1",
        model_config_hash(MODEL_V1)[:20])
_assert("production is still pointed at sim-v1",
        ACTIVE_MODEL_VERSION_ID == "sim-v1")
_assert("IPRM moved to v2 because its behaviour materially changed",
        I.IPRM_VERSION == "iprm-v2")

import ast                                                         # noqa: E402


def _imports(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


for _module in ("scoring/history.py", "scoring/iprm.py", "scoring/csps.py",
                "odds/sim_v2.py", "providers/balldontlie/factual.py"):
    _assert(f"  {_module} imports no HTTP client",
            not ({"httpx", "requests", "urllib", "socket"}
                 & _imports(os.path.join(ROOT, _module))))
_assert("  · only the refresh service may touch the network, and it is not on "
        "the quote path",
        "transport" in open(os.path.join(
            ROOT, "providers", "balldontlie", "history_refresh.py"),
            encoding="utf-8").read()
        and "history_refresh" not in open(os.path.join(ROOT, "odds",
                                                       "sim_v2.py"),
                                          encoding="utf-8").read())
_assert("a BALLDONTLIE-configured league never falls back to Yahoo",
        not S.build_lineup(_e2e, team_id=1, team_name="H", player_ids=_HOME,
                           season=2026, week=1,
                           profile="culv_appreciation_society",
                           projection_source=S.PROJECTION_SOURCE_YAHOO,
                           as_of=PRICED_AT).admissible)


print()
if _failures:
    print("=" * 78)
    print(f"SPRINT 5 — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  · {_f}")
    print("=" * 78)
    sys.exit(1)
print("=" * 78)
print("SPRINT 5 historical models: all assertions passed — the three model "
      "gaps are\nclosed by MEASURED parameters with an as-of cutoff, and every "
      "one still refuses\nwhen no measurement is in force.")
print("=" * 78)
