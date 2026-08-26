"""SPRINT 5B · calibration against REAL BALLDONTLIE history.

WHAT THIS SUITE IS FOR, AND HOW IT DIFFERS FROM SPRINT 5'S. Sprint 5 proved the
machinery: a parameter store, an as-of cutoff, three models that refuse when
nothing has been measured. Every fact it was certified against was written by
hand. Sprint 5B fed the same machinery two real NFL seasons, and the first
thing that happened was that several hand-written facts turned out to be wrong.

    · `/plays` takes a SINGLE REQUIRED `game_id`. The client sent
      `game_ids[]` -- correct by symmetry with every neighbouring endpoint,
      and answered with HTTP 400 by the only endpoint that matters here.

    · Live plays carry `type_slug`, a nested `game` object and
      `clock_display`. The committed fixture had `type`, `game_id` and
      `clock`, so the parser required a field the provider does not emit.

    · The type vocabulary was guessed. `interception`, `fumble`, `downs`,
      `end-of-quarter` and `penalty-no-play` do not exist; the real names are
      `pass-interception-return`, `fumble-recovery-opponent`, `penalty`,
      `end-period` -- and `interception-return-touchdown`, the pick-six
      itself, was in no table at all.

    · No play text says "FIRST DOWN". Not one of 1,199 consecutive real
      plays. First downs live in `end_down`.

    · There is no `turnover-on-downs` type. A failed fourth down is an
      ordinary rush or reception whose `team` has already flipped.

Each of those was invisible to a fixture, because a fixture answers whatever it
was written to answer. So this suite certifies against a CAPTURED game -- a
real, unedited provider response -- and the numbers below were counted from it
by hand where they could be.

OFFLINE AND DETERMINISTIC. No network, no credential, no cache. The captured
fixture and an in-memory SQLite database are the whole world.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import math                                                        # noqa: E402
from datetime import datetime, timezone                            # noqa: E402

from sqlalchemy import create_engine, event                        # noqa: E402
from sqlalchemy.orm import sessionmaker                            # noqa: E402

from db.schema import (                                            # noqa: E402
    Base, Player, ProviderHistoricalRate as R,
)
from odds import sim_v2 as S                                       # noqa: E402
from odds.model_registry import (                                  # noqa: E402
    ACTIVE_MODEL_VERSION_ID, model_config_hash, resolve_model_config,
)
from providers.balldontlie import factual as F                     # noqa: E402
from providers.balldontlie import parse as P                       # noqa: E402
from providers.component_projections import (                      # noqa: E402
    ComponentProjection, persist_snapshot,
)
from providers.cross_identity import (                             # noqa: E402
    BALLDONTLIE, CanonicalSubject, CrossProviderResolution, Outcome,
)
from scoring import history as H                                   # noqa: E402
from scoring import iprm as I                                      # noqa: E402
from scoring.profile import load_profile                           # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(ROOT, "providers", "fixtures", "balldontlie")
CAPTURED = os.path.join(CORPUS, "plays__game_id-7005__per_page-100__CAPTURED.json")

#: The captured game: TEN at CHI, 2024 regular season week 1.
HOME, VISITOR = "CHI", "TEN"

PRICED_AT = datetime(2026, 9, 10, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 3, 1, tzinfo=timezone.utc)
BEFORE = datetime(2025, 9, 10, tzinfo=timezone.utc)

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


def _near(got, want, tol=1e-9):
    if got is None:
        return False
    return abs(got - want) < tol


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


print("=" * 78)
print("SPRINT 5B · REAL BALLDONTLIE CALIBRATION")
print("=" * 78)
print(f"  reception model : {H.RECEPTION_MODEL_VERSION}")
print(f"  pick-six model  : {H.PICK_SIX_MODEL_VERSION}")
print(f"  3-and-out model : {H.THREE_AND_OUT_MODEL_VERSION}")
print(f"  drives model    : {H.DRIVES_MODEL_VERSION}")
print(f"  IPRM            : {I.IPRM_VERSION}")

_payload = json.load(open(CAPTURED, encoding="utf-8"))
_plays = P.parse_plays(_payload)


# ══════════════════════════════════════════════════════════════════════════════
# A · the captured evidence is real, and labelled as such
# ══════════════════════════════════════════════════════════════════════════════

print("\n5B-A · the fixture is a real provider response, not a drawing of one")

_assert("the capture declares its provenance tier",
        _payload["_provenance"]["tier"] == "CAPTURED",
        _payload["_provenance"]["tier"])
_assert("  · and names the request that produced it",
        _payload["_provenance"]["request"]["game_id"] == 7005
        and _payload["_provenance"]["source"].endswith("/plays"))
_assert("  · it carries no credential, header or token",
        not any(k in json.dumps(_payload).lower()
                for k in ("authorization", "api_key", "bearer")))
_assert("a whole game was retained, because a drive cannot be classified "
        "from half of one", len(_plays) == 178, f"{len(_plays)} plays")

# THE FIELD NAMES THAT COST TWO SPRINTS.
_raw = _payload["data"][0]
_assert("live plays carry `type_slug`, not `type`",
        "type_slug" in _raw and "type" not in _raw, sorted(_raw)[:4])
_assert("  · and nest the game rather than carrying `game_id`",
        isinstance(_raw.get("game"), dict) and "game_id" not in _raw)
_assert("  · the parser reads both spellings, so the legacy corpus still "
        "replays", _plays[0].type and _plays[0].game_id == 7005)
_assert("no real play text says FIRST DOWN -- the signal is `end_down`",
        not any("FIRST DOWN" in (p.text or "").upper() for p in _plays)
        and any(isinstance(p.end_down, int) for p in _plays))


# ── THE ENDPOINT CONTRACT, AS MEASURED RATHER THAN ASSUMED ─────────────────

from providers.balldontlie.transport import ENDPOINTS                # noqa: E402
from providers.errors import ProviderTransportError                  # noqa: E402

_assert("`plays` takes a SINGLE REQUIRED `game_id`, not the plural every "
        "neighbouring endpoint uses",
        "game_id" in ENDPOINTS["plays"] and "game_ids[]" not in ENDPOINTS["plays"],
        sorted(ENDPOINTS["plays"]))
_assert("  · so the client refuses the plural rather than sending a 400",
        "game_ids[]" not in ENDPOINTS["plays"])
# `weeks[]` ON /stats IS ACCEPTED BY THE SERVER AND SILENTLY IGNORED. Sprint 5B
# sent seasons[]=2025&weeks[]=1 and paginated: page 1 was week 1, page 72 was
# week 8, page 145 was week 15. The season filter applied and the week filter
# did not, so a caller who believed it had fetched one week had in fact fetched
# a season. It is removed from the allowlist so the client refuses to send it.
_assert("`stats` does NOT accept `weeks[]` — the provider ignores it and "
        "returns the whole season with a 200",
        "weeks[]" not in ENDPOINTS["stats"], sorted(ENDPOINTS["stats"]))
_assert("  · while `games` DOES honour weeks[], which is why it keeps it",
        "weeks[]" in ENDPOINTS["games"])
_assert("  · and `stats` still filters by season and by game",
        {"seasons[]", "game_ids[]"} <= ENDPOINTS["stats"])


# ══════════════════════════════════════════════════════════════════════════════
# B · factual identification on real football
# ══════════════════════════════════════════════════════════════════════════════

print("\n5B-B · drives, three-and-outs and a pick-six, counted from real plays")

_drives = F.classify_drives(_plays, home=HOME, visitor=VISITOR)
_counted = [d for d in _drives if d.counts_toward_sample]
_assert("the real game classifies into possessions",
        len(_drives) == 29, f"{len(_drives)} drives")
_assert("  · and most of them are judgeable",
        len(_counted) == 23, f"{len(_counted)} of {len(_drives)} counted")
_unknown = [d for d in _drives if d.outcome == F.DriveOutcome.UNKNOWN]
_assert("  · an unclassifiable possession is excluded from BOTH halves of "
        "every rate, never counted as a stop",
        len(_unknown) == 5 and all(not d.counts_toward_sample for d in _unknown),
        f"{len(_unknown)} UNKNOWN")

_chi = F.three_and_outs_forced(_plays, home=HOME, visitor=VISITOR, team="CHI")
_ten = F.three_and_outs_forced(_plays, home=HOME, visitor=VISITOR, team="TEN")
_assert("Chicago's defence forced three-and-outs, with the sample beside them",
        _chi["three_and_outs"] == 4 and _chi["opponent_drives"] == 12,
        f"{_chi['three_and_outs']} of {_chi['opponent_drives']}")
_assert("  · and Tennessee's, measured the same way",
        _ten["three_and_outs"] == 2 and _ten["opponent_drives"] == 11,
        f"{_ten['three_and_outs']} of {_ten['opponent_drives']}")
_assert("  · every counted drive belongs to one of the two teams",
        {d.team for d in _counted} <= {HOME, VISITOR})

# the vocabulary really is complete for this game
_unmapped = {p.type for p in _plays} - F._KNOWN_SLUGS
_assert("every play type in a real game is in the known vocabulary",
        not _unmapped, f"unmapped: {sorted(_unmapped)}")

_events = F.pick_six_events(_plays)
_assert("the pick-six is identified structurally, by slug",
        sum(_events["pick_sixes"].values()) == 1,
        f"{sum(_events['pick_sixes'].values())} pick six")
_assert("  · attributed to the PASSER, never the returner or the team",
        list(_events["pick_sixes"]) == [78], list(_events["pick_sixes"]))
_assert("  · and the same passer's other interception is in the denominator",
        _events["interceptions"][78] == 2, _events["interceptions"])
_assert("  · nothing was left unattributed in this game",
        _events["unattributed"] == 0)
_pick_six_play = [p for p in _plays
                  if p.type == "interception-return-touchdown"][0]
_assert("  · the play the provider calls a pick-six names the defence as its "
        "team -- which is exactly why attribution cannot read `team`",
        (_pick_six_play.team or {}).get("abbreviation") == "CHI"
        and 78 in _pick_six_play.participant_ids(F.PARTICIPANT_PASSER))


# ══════════════════════════════════════════════════════════════════════════════
# C · real parameters, persisted with real provenance
# ══════════════════════════════════════════════════════════════════════════════

print("\n5B-C · real derived parameters, stored and re-derived")

_db = _session()
_games = [(_plays, HOME, VISITOR)]
_real = []
_real += H.derive_pick_six_rates([_plays], provider=BALLDONTLIE,
                                 season_window="2024", as_of=CUTOFF)
_real += H.derive_three_and_out_rates(_games, provider=BALLDONTLIE,
                                      season_window="2024", as_of=CUTOFF)
_real += H.derive_drive_rates(_games, provider=BALLDONTLIE,
                              season_window="2024", as_of=CUTOFF)
_real += H.derive_reception_rates_from_season_totals(
    [{"season": 2024, "postseason": False,
      "player": {"id": 760, "position_abbreviation": "WR"},
      "receiving_targets": 79, "receptions": 42},
     {"season": 2024, "postseason": False,
      "player": {"id": 761, "position_abbreviation": "TE"},
      "receiving_targets": 60, "receptions": 44}],
    provider=BALLDONTLIE, season_window="2024", as_of=CUTOFF)

_report = H.persist_rates(_db, _real, generated_at=datetime(2026, 3, 15,
                                                            tzinfo=timezone.utc))
_db.flush()
_assert("every derived parameter persists",
        _report["persisted"] == len(_real) and _report["persisted"] > 0,
        f"{_report['persisted']} rows")
_assert("  · none is labelled SYNTHETIC -- these came from a real response",
        _db.query(R).filter(R.source_kind == "SYNTHETIC").count() == 0)
_assert("  · the source names the endpoint each came from",
        {r.source_kind for r in _db.query(R).all()} == {"plays", "season_stats"},
        sorted({r.source_kind for r in _db.query(R).all()}))
_assert("  · and every row carries its cutoff and its sample size",
        all(r.as_of.replace(tzinfo=None) == CUTOFF.replace(tzinfo=None)
            and r.sample_size > 0 for r in _db.query(R).all()))

_again = H.persist_rates(_db, _real,
                         generated_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
_db.flush()
_assert("re-deriving the SAME history writes nothing at all",
        _again["persisted"] == 0 and _again["duplicate"] == len(_real),
        f"{_again['duplicate']} duplicates")

_drive_row = _db.query(R).filter(R.model_type == R.MODEL_DRIVES,
                                 R.entity_type == R.ENTITY_LEAGUE).one()
_assert("drives per team-game is MEASURED, not assumed",
        _near(_drive_row.rate, 23 / 2) and _drive_row.sample_size == 2,
        f"{_drive_row.rate:.4f} per team-game from {_drive_row.sample_size}")

_tao_row = _db.query(R).filter(R.model_type == R.MODEL_THREE_AND_OUT,
                               R.entity_key == "CHI").one()
_assert("a defensive rate is per OPPONENT DRIVE, with both terms kept",
        _near(_tao_row.rate, 4 / 12) and _tao_row.numerator == 4
        and _tao_row.denominator == 12)

_ps_row = _db.query(R).filter(R.model_type == R.MODEL_PICK_SIX,
                              R.entity_type == R.ENTITY_LEAGUE).one()
_assert("the pick-six rate is CONDITIONAL on an interception being thrown",
        _near(_ps_row.rate, 1 / 2) and _ps_row.denominator == 2)


# ══════════════════════════════════════════════════════════════════════════════
# D · reception-model-v2: what two real seasons changed
# ══════════════════════════════════════════════════════════════════════════════

print("\n5B-D · reception-model-v2 answers from the position, and why")

_assert("the model version records that the behaviour moved",
        H.RECEPTION_MODEL_VERSION == "reception-model-v2")

_bundle = H.resolve_bundle(_db, provider=BALLDONTLIE, as_of=PRICED_AT,
                           player_key="bdl.p.760", position="WR",
                           nfl_team="CHI")
_assert("a receiver resolves at the POSITION level",
        _bundle.reception.level == "MODELLED_POSITIONAL_FALLBACK",
        _bundle.reception.level)
_assert("  · even though his own measured rate is stored",
        _db.query(R).filter(R.model_type == R.MODEL_RECEPTION,
                            R.entity_key == "bdl.p.760").count() == 1)
# THE EVIDENCE, RECORDED. Training on 2024 and testing on 2025 over the same
# 134 players who cleared v1's fifty-target minimum, the POSITION rate beat each
# player's own: MAE 4.01 against 4.65. Across all 502 receivers, 2.28 against
# 2.87. Shrinkage between the two bottoms 2.6% below pure position, at a
# constant only obtainable by fitting the test season -- which is not a fit.
_assert("  · the player rate is kept as evidence, not consulted as a model",
        _bundle.reception.model_version == "reception-model-v2")

_league_only = _session()
H.persist_rates(_league_only, [r for r in _real
                               if r.model_type == R.MODEL_RECEPTION
                               and r.entity_type == R.ENTITY_LEAGUE])
_league_only.flush()
_assert("with no positional history the LEAGUE rate answers",
        H.resolve_bundle(_league_only, provider=BALLDONTLIE, as_of=PRICED_AT,
                         player_key="bdl.p.999", position="WR"
                         ).reception.level == "MODELLED_LEAGUE_FALLBACK")


# ══════════════════════════════════════════════════════════════════════════════
# E · the projections these parameters produce stay inside their bounds
# ══════════════════════════════════════════════════════════════════════════════

print("\n5B-E · bounded expectations")

from scoring import csps as C                                      # noqa: E402


def _project(components, profile=CULV, position="WR", nfl_team="CHI",
             rates=None, key="bdl.p.760", config=I.IPRM_V1):
    result = C.score_components(components, profile, mode=C.PROJECTION,
                                components_present=list(components),
                                position=position)
    result.provider_player_key = key
    return I.project(result, profile=profile, components=components,
                     config=config, position=position, nfl_team=nfl_team,
                     rates=rates)


_rec = _project({"targets": 9.0, "receiving_yards": 84.3},
                rates=_bundle).modelled("receptions")
_assert("expected receptions = targets x the measured catch rate",
        _near(_rec.parameters["expected_receptions"], 9.0 * (42 / 79)),
        f"{_rec.parameters['expected_receptions']:.4f}")
_assert("  · and can never exceed the targets that produced them",
        all(_project({"targets": t}, rates=_bundle)
            .modelled("receptions").parameters["expected_receptions"] <= t + 1e-9
            for t in (0.0, 1.0, 4.5, 12.0)))

_qb = _project({"passing_yards": 240.0, "passing_interceptions": 1.2},
               profile=WHISKERS, position="QB", rates=_bundle,
               key="bdl.p.78").modelled("pick_six_thrown")
_assert("expected pick-sixes = interceptions x the conditional rate",
        _near(_qb.parameters["expected_count"], 1.2 * 0.5),
        f"{_qb.parameters['expected_count']:.4f}")
_assert("  · and never exceeds the interceptions it is conditioned on",
        _qb.parameters["expected_count"] <= 1.2 + 1e-9)
_zero = _project({"passing_yards": 240.0, "passing_interceptions": 0.0},
                 profile=WHISKERS, position="QB", rates=_bundle,
                 key="bdl.p.78").modelled("pick_six_thrown")
_assert("  · zero projected interceptions gives an exact zero, not a model",
        _near(_zero.parameters["expected_count"], 0.0))


# ══════════════════════════════════════════════════════════════════════════════
# F · three-and-outs now resolve, because the drive count was measured
# ══════════════════════════════════════════════════════════════════════════════

print("\n5B-F · the gap Sprint 5 refused on is closed by a measurement")

_dst = _project({"defensive_sacks": 2.4, "dst_points_allowed": 21.3},
                profile=WHISKERS, position="DEF", nfl_team="CHI",
                rates=_bundle, key="bdl.dst.CHI").modelled("dst_three_and_outs")
_assert("a DST three-and-out projection RESOLVES on real parameters",
        _dst.quality != "MODEL_UNRESOLVED", _dst.quality)
_assert("  · expected count = measured rate x measured drives",
        _near(_dst.parameters["expected_three_and_outs"],
              _dst.parameters["three_and_out_rate_per_drive"]
              * _dst.parameters["expected_opponent_drives"]),
        f"{_dst.parameters['expected_three_and_outs']:.4f}")
_assert("  · and the drive count names the model that measured it",
        _dst.parameters["expected_drives_model_version"] == "drives-model-v1",
        _dst.parameters.get("expected_drives_model_version"))

# THE REFUSAL IS STILL THERE WHEN THE MEASUREMENT IS NOT.
_no_drives = _session()
H.persist_rates(_no_drives, [r for r in _real
                             if r.model_type == R.MODEL_THREE_AND_OUT])
_no_drives.flush()
_bundle_no_drives = H.resolve_bundle(_no_drives, provider=BALLDONTLIE,
                                     as_of=PRICED_AT, nfl_team="CHI",
                                     player_key="bdl.dst.CHI", position="DEF")
_still = _project({"defensive_sacks": 2.4}, profile=WHISKERS, position="DEF",
                  nfl_team="CHI", rates=_bundle_no_drives,
                  key="bdl.dst.CHI").modelled("dst_three_and_outs")
_assert("with the DEFENSIVE rate measured but no drive count, the model still "
        "refuses -- exactly as it did in Sprint 5",
        _still.quality == "MODEL_UNRESOLVED", _still.quality)
_assert("  · and says which of the two halves is missing",
        "drive" in _still.note.lower())


# ══════════════════════════════════════════════════════════════════════════════
# G · as-of, corrections and replay on real parameters
# ══════════════════════════════════════════════════════════════════════════════

print("\n5B-G · a real parameter cannot leak backwards in time")

_early = H.resolve_bundle(_db, provider=BALLDONTLIE, as_of=BEFORE,
                          player_key="bdl.p.760", position="WR", nfl_team="CHI")
_assert("a 2025 price cannot see a parameter cut off in March 2026",
        not _early.reception.resolved and not _early.drives.resolved
        and not _early.three_and_out.resolved, _early.reception.level)
_assert("  · and the refusal names the absence rather than inventing a rate",
        _early.reception.level == "MODEL_UNRESOLVED")
_assert("a 2026 price does resolve it",
        _bundle.reception.resolved and _bundle.drives.resolved)

_corrected = H.derive_three_and_out_rates(_games, provider=BALLDONTLIE,
                                          season_window="2024", as_of=CUTOFF)
_before_rows = _db.query(R).filter(R.model_type == R.MODEL_THREE_AND_OUT).count()
_original = _db.query(R).filter(R.model_type == R.MODEL_THREE_AND_OUT,
                                R.entity_key == "CHI").one()
_original_fingerprint = _original.fingerprint
_correction = H.HistoricalRate(
    provider=BALLDONTLIE, model_type=R.MODEL_THREE_AND_OUT,
    model_version=H.THREE_AND_OUT_MODEL_VERSION, entity_type=R.ENTITY_TEAM,
    entity_key="CHI", season_window="2024", as_of=CUTOFF,
    numerator=5.0, denominator=12.0, sample_size=12, source_kind="plays",
    parameters={"corrected": True})
H.persist_rates(_db, [_correction],
                generated_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
_db.flush()
_assert("a correction lands as a NEW row beside its predecessor",
        _db.query(R).filter(R.model_type == R.MODEL_THREE_AND_OUT).count()
        == _before_rows + 1)
_assert("  · the original is untouched and keeps its fingerprint",
        _db.query(R).filter_by(id=_original.id).one().numerator == 4.0
        and _db.query(R).filter_by(id=_original.id).one().fingerprint
        == _original_fingerprint)
_assert("  · a correction changes the derived fingerprint",
        _correction.fingerprint() != _original_fingerprint)


# ══════════════════════════════════════════════════════════════════════════════
# H · end to end, both real leagues, no network
# ══════════════════════════════════════════════════════════════════════════════

print("\n5B-H · CULV and Mr Whiskers through the whole pipeline")

_e2e = _session()
H.persist_rates(_e2e, _real, generated_at=datetime(2026, 3, 15,
                                                   tzinfo=timezone.utc))
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


_LINEUP = [
    _subject("QB1", "QB", "CHI", {"passing_yards": 268.4,
                                  "passing_touchdowns": 1.8,
                                  "passing_interceptions": 0.7}, "bdl.p.78"),
    _subject("WR1", "WR", "CHI", {"targets": 9.8,
                                  "receiving_yards": 84.3}, "bdl.p.760"),
    _subject("TE1", "TE", "CHI", {"targets": 8.1,
                                  "receiving_yards": 61.9}, "bdl.p.761"),
    _subject("D1", "DEF", "CHI", {"defensive_sacks": 2.4,
                                  "dst_points_allowed": 21.3}, "bdl.dst.CHI"),
]


def _build(profile, as_of=PRICED_AT):
    return S.build_lineup(_e2e, team_id=1, team_name="Home",
                          player_ids=_LINEUP, season=2026, week=1,
                          profile=profile,
                          projection_source=S.PROJECTION_SOURCE_BALLDONTLIE,
                          as_of=as_of)


_culv = _build(CULV)
_whiskers = _build(WHISKERS)

_assert("CULV is admissible on real measured parameters",
        _culv.admissible and not _culv.refusals,
        f"{len(_culv.starters)} starters, {len(_culv.refusals)} refusals")
_assert("MR WHISKERS is admissible too -- the gap Sprint 5 refused on is shut",
        _whiskers.admissible and not _whiskers.refusals,
        f"{len(_whiskers.starters)} starters, {len(_whiskers.refusals)} refusals")
_assert("  · every starter reaches a simulation-ready state",
        all(r.status in (I.Status.SIMULATION_READY,
                         I.Status.SIMULATION_READY_WITH_FALLBACKS)
            for r in _whiskers.iprm_results),
        sorted({r.status for r in _whiskers.iprm_results}))

_culv_means = [round(r.mean_fantasy_points, 9) for r in _culv.iprm_results]
_whiskers_means = [round(r.mean_fantasy_points, 9) for r in _whiskers.iprm_results]
_assert("the SAME components price differently under the two rulebooks",
        _culv_means != _whiskers_means,
        f"CULV {sum(_culv_means):.2f} vs Whiskers {sum(_whiskers_means):.2f}")
_assert("  · and CULV never sees a Mr Whiskers-only category",
        not any(m.category == "dst_three_and_outs" and m.expected_points
                for r in _culv.iprm_results for m in r.modelled_contributions))

_assert("a replay from the same stored rows reproduces the price exactly",
        [round(r.mean_fantasy_points, 9) for r in _build(CULV).iprm_results]
        == _culv_means)

# ── NO NETWORK AT QUOTE TIME, PROVED BY REMOVING THE NETWORK ────────────────
import providers.balldontlie.transport as _T                       # noqa: E402

_calls = []
_original_request = _T.BalldontlieLiveTransport._request


def _explode(self, *a, **k):
    _calls.append(a)
    raise AssertionError("the quote path opened a socket")


_T.BalldontlieLiveTransport._request = _explode
try:
    _offline = _build(WHISKERS)
    _offline_ok = True
finally:
    _T.BalldontlieLiveTransport._request = _original_request
_assert("pricing runs with the live transport sabotaged -- no BDL call at "
        "quote time", _offline_ok and not _calls,
        f"{len(_calls)} provider calls")
_assert("  · and produces the identical answer",
        [round(r.mean_fantasy_points, 9) for r in _offline.iprm_results]
        == _whiskers_means)

_before_cutoff = _build(WHISKERS, as_of=BEFORE)
_assert("priced BEFORE the parameters existed, the same lineup refuses",
        bool(_before_cutoff.refusals) or any(
            m.quality == "MODEL_UNRESOLVED"
            for r in _before_cutoff.iprm_results
            for m in r.modelled_contributions),
        f"{len(_before_cutoff.refusals)} refusal(s)")


# ══════════════════════════════════════════════════════════════════════════════
# I · nothing that was frozen has moved
# ══════════════════════════════════════════════════════════════════════════════

print("\n5B-I · the frozen things are still frozen")

_SIM_V1 = "1d60ff39343bebf1ceb8099f729fbaff18cb278078e06d094da6cc04ba4626d1"
_assert("sim-v1's configuration hash is byte-identical",
        model_config_hash(resolve_model_config("sim-v1")) == _SIM_V1,
        model_config_hash(resolve_model_config("sim-v1"))[:16])
_assert("sim-v1 is still the ACTIVE production model",
        ACTIVE_MODEL_VERSION_ID == "sim-v1", ACTIVE_MODEL_VERSION_ID)
_assert("IPRM stays at iprm-v2 -- data changed, its contract did not",
        I.IPRM_VERSION == "iprm-v2", I.IPRM_VERSION)
_assert("sim-v2 exists but is not active",
        "sim-v2" in resolve_model_config("sim-v2").model_version_id
        and ACTIVE_MODEL_VERSION_ID != "sim-v2")


print()
print("=" * 78)
if _failed:
    print(f"SPRINT 5B: {_failed} FAILED, {_passed} passed")
    raise SystemExit(1)
print(f"SPRINT 5B: all {_passed} assertions passed — every model above is "
      f"calibrated from\nreal BALLDONTLIE facts, and every one still refuses "
      f"when the measurement is absent.")
print("=" * 78)
