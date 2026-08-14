#!/usr/bin/env python3
"""
test_wp1b_postseason_pool_pg.py — WP1B · postseason Pool catalog & eligibility.

THE QUESTION THIS SUITE ANSWERS:

    IN THE POSTSEASON, CAN A POOL BE DRAWN, PICKED AND SETTLED AGAINST THE
    CHAMPIONSHIP FIELD ONLY — AND DOES THAT FIELD STAY PUT?

Two failures are in scope and they fail differently. The first is loud: a
postseason week that cannot be drawn at all, which is where the baseline stood
(every `postseason_eligible` was null). The second is silent and is the one the
freeze exists for: a Pool drawn over all twelve league teams, four of them
playing consolation, which does not raise anything — it settles, and it pays a
GM who picked an eliminated team.

WHAT IS PRODUCTION HERE. The catalog loader, the real seeder, the two gates, the
real selector and slate builder, the real claim validator, the real census and
the certified identity resolver. Championship FACTS come from the WP1A synthetic
normalized fixtures — there is no captured Yahoo postseason payload and WP1B
does not invent one (WP1B §13). Settlement subjects come from
`test_support_s4_pool.DefinitionStatSource`, the same recorded-fixture adaptor
the certified S4 suites use.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.

Runs as: python test_wp1b_postseason_pool_pg.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP1B suite cannot run:\n  {e}")
    sys.exit(2)

import json  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from betting.pool_catalog import (  # noqa: E402
    PoolCatalogError, load_catalog,
)
from betting.pool_claims import PoolClaimError, submit_claim  # noqa: E402
from betting.pool_claim_view import week_claim_view  # noqa: E402
from betting.pool_postseason import (  # noqa: E402
    CHAMPIONSHIP_PREFERRED_KEYS, PostseasonSubjectError, freeze_universe,
    frozen_subject_ids, is_championship_round, resolve_universe,
)
from betting.pool_season_boundary import (  # noqa: E402
    PHASE_POSTSEASON, PHASE_REGULAR, phase_for_week,
)
from betting.pool_slate import build_and_persist_slate  # noqa: E402
from betting.pool_subjects import (  # noqa: E402
    SCOPE_MATCHUP, SCOPE_TEAM, league_weekly_structure,
)
from providers.fixtures.postseason_synthetic import ps10, ps12  # noqa: E402
from providers.yahoo.identity import build_team_identity_resolver  # noqa: E402
from season.championship_track import (  # noqa: E402
    ChampionshipFieldDeclaration, ChampionshipTrackInput, ChampionshipWeekInput,
    derive_championship_track_state,
)
from test_support_s4_pool import (  # noqa: E402
    PROVIDER, mark_ready, seed_catalog,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


# ── Fixture construction ──────────────────────────────────────────────────────
#
# The DB league MIRRORS the WP1A synthetic championship league: twelve teams
# bound to `SYN.l.ps12.t.N` provider keys, and one Matchup row per synthetic
# matchup carrying that matchup's derived `provider_matchup_key`. Nothing is
# invented — the keys are the ones providers/base.derive_matchup_key produced.

FIXTURE_FINAL = datetime(2025, 12, 30, 12, 0, tzinfo=timezone.utc)


def namespaced(synthetic, suffix: str):
    """A copy of a synthetic league whose provider keys are unique to `suffix`.

    `teams.uq_teams_provider_key` is unique on (provider, provider_team_key)
    ACROSS leagues — the compound Yahoo key is globally unique in reality, so
    the constraint is right and it is the fixtures that must not collide. Each
    scenario below therefore gets its own synthetic league key, and every
    matchup key is RE-DERIVED through `providers.base.derive_matchup_key` rather
    than string-patched, so the keys stay the ones production would construct.
    """
    from dataclasses import replace

    from providers.fixtures.postseason_synthetic import matchup

    old = synthetic.league_key
    new = f"{old}-{suffix}"

    def rekey(key: str) -> str:
        return key.replace(old, new, 1)

    weeks = {}
    for week, matchups in synthetic.weeks.items():
        weeks[week] = tuple(
            matchup(new, week, rekey(m.home_team_key), rekey(m.away_team_key),
                    bracket=m.bracket, finality=m.finality,
                    winner=(rekey(m.winner_team_key) if m.winner_team_key
                            else None),
                    home_points=m.home_points, away_points=m.away_points,
                    is_tied=m.is_tied)
            for m in matchups)

    return replace(
        synthetic, league_key=new,
        championship_field=frozenset(rekey(k)
                                     for k in synthetic.championship_field),
        weeks=weeks)


def build_league(db, synthetic, *, name: str, wallet_cents: int = 100_000):
    """A DB league mirroring one synthetic postseason league."""
    from db.schema import League, Matchup, Team, Wallet
    from ledger.ledger import post as ledger_post

    league = League(season=synthetic.season, name=name,
                    projection_source="fantasypros",
                    season_final_week=synthetic.season_final_week,
                    playoff_start_week=synthetic.playoff_start_week)
    db.add(league)
    db.flush()

    teams: dict[str, object] = {}
    for ordinal in range(1, synthetic.team_count + 1):
        key = synthetic.team_key(ordinal)
        team = Team(league_id=league.id, team_name=f"{name}-t{ordinal}",
                    owner=f"owner-{ordinal}", email=f"{name}-{ordinal}@x.test",
                    provider="yahoo", provider_team_key=key,
                    provider_team_id=ordinal)
        db.add(team)
        db.flush()
        db.add(Wallet(team_id=team.id, balance=0.0))
        teams[key] = team
    db.flush()

    for team in teams.values():
        ledger_post([("world", -wallet_cents), (f"wallet:{team.id}", wallet_cents)],
                    door="buy_in_paid", session=db)

    for week, matchups in sorted(synthetic.weeks.items()):
        for m in matchups:
            db.add(Matchup(
                league_id=league.id, week=week,
                home_team_id=teams[m.home_team_key].id,
                away_team_id=teams[m.away_team_key].id,
                home_score=float(m.home_points or 0.0),
                away_score=float(m.away_points or 0.0),
                provider_matchup_key=m.matchup_key,
                finalized_at=FIXTURE_FINAL))
    db.flush()
    return league, teams


def track_state(synthetic, *, week: int, declare: bool = True,
                weeks_override: dict | None = None):
    """WP1A championship state for one synthetic league-week."""
    source = weeks_override if weeks_override is not None \
        else synthetic.weeks_through(week)
    return derive_championship_track_state(
        ChampionshipTrackInput(
            league_key=synthetic.league_key, season=synthetic.season,
            playoff_start_week=synthetic.playoff_start_week,
            season_final_week=synthetic.season_final_week,
            playoff_team_count=synthetic.playoff_team_count,
            weeks=tuple(ChampionshipWeekInput(week=w, matchups=tuple(ms))
                        for w, ms in sorted(source.items())),
            field_declaration=(ChampionshipFieldDeclaration(
                team_keys=synthetic.championship_field) if declare else None)),
        week=week)


def _ords(team_ids, teams_by_key) -> list[int]:
    """Internal team ids rendered as their synthetic ordinals, for readable
    failure detail."""
    by_id = {t.id: int(k.rsplit(".", 1)[-1]) for k, t in teams_by_key.items()}
    return sorted(by_id[i] for i in team_ids if i in by_id)


def ready_postseason(db, league_id: int) -> tuple[str, ...]:
    """Mark gate-2 ready for every postseason-eligible definition."""
    keys = tuple(d.key for d in load_catalog().definitions
                 if d.postseason_eligible)
    mark_ready(db, league_id=league_id, keys=keys)
    return keys


# ── 1 · Catalog data and the structural guard ────────────────────────────────

def case_catalog() -> None:
    _section("W1B-1 · postseason catalog resolved and structurally guarded")
    catalog = load_catalog()
    enabled = [d for d in catalog.definitions if d.postseason_eligible]
    disabled = [d for d in catalog.definitions if d.postseason_eligible is False]

    _assert("1a: every definition now carries an explicit boolean — no NULLs",
            all(d.postseason_eligible is not None for d in catalog.definitions),
            detail=str(sum(1 for d in catalog.definitions
                           if d.postseason_eligible is None)))
    _assert("1b: 44 postseason-eligible, 36 not",
            (len(enabled), len(disabled)) == (44, 36),
            detail=f"{len(enabled)}/{len(disabled)}")
    _assert("1c: no MATCHUP/RANK_EXTREMUM is postseason-eligible",
            not [d for d in enabled
                 if d.scope == SCOPE_MATCHUP
                 and d.evaluator_family == "RANK_EXTREMUM"])
    _assert("1d: MATCHUP/QUALIFIER IS permitted — the prohibition is on the "
            "competing-options structure, not on matchups",
            len([d for d in enabled if d.scope == SCOPE_MATCHUP]) == 9,
            detail=str(len([d for d in enabled if d.scope == SCOPE_MATCHUP])))
    _assert("1e: no gate-1-ineligible or BLOCKED definition was enabled",
            all(d.definition_runtime_eligible
                and d.dependency_state == "ENABLED" for d in enabled))
    _assert("1f: regular-season eligibility is untouched — all 80",
            all(d.regular_season_eligible for d in catalog.definitions))
    _assert("1g: every championship-preferred key is postseason-eligible",
            all(k in {d.key for d in enabled}
                for k in CHAMPIONSHIP_PREFERRED_KEYS),
            detail=str(CHAMPIONSHIP_PREFERRED_KEYS))


def case_guard() -> None:
    _section("W1B-2 · matchup-vs-matchup is refused at catalog load")
    raw = json.load(open("spec/pool_catalog_rev1_3.json", encoding="utf-8"))
    victim = next(r for r in raw["definitions"]
                  if r["scope"] == "MATCHUP"
                  and r["evaluator_family"] == "RANK_EXTREMUM")
    victim["postseason_eligible"] = True

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "_wp1b_prohibited_catalog.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(raw, fh)
    try:
        load_catalog(path)
        raised = None
    except PoolCatalogError as exc:
        raised = exc
    finally:
        os.remove(path)

    _assert("2a: a postseason-eligible MATCHUP/RANK_EXTREMUM row refuses to load",
            raised is not None, detail="catalog loaded without complaint")
    _assert("2b: the refusal names the prohibited structure",
            raised is not None
            and "PROHIBITED_POSTSEASON_STRUCTURE" in str(raised),
            detail=str(raised)[:90] if raised else "")
    _assert("2c: it is enforced at LOAD, so a bad edit cannot sit in the "
            "artifact looking approved",
            raised is not None and victim["key"] in str(raised))


# ── 2 · Subject-universe contraction ─────────────────────────────────────────

def case_contraction(db) -> None:
    _section("W1B-3 · postseason contracts the subject universe")
    syn = namespaced(ps12(), "contract")
    league, teams = build_league(db, syn, name="ps12-contract")
    seed_catalog(db)
    ready_postseason(db, league.id)
    resolver = build_team_identity_resolver(db, league_id=league.id)
    db.flush()

    # Regular-season structure BEFORE any freeze — the control.
    reg = league_weekly_structure(db, league_id=league.id, week=3,
                                  scope=SCOPE_TEAM)
    _assert("3a: regular-season TEAM universe is every league team (control)",
            len(reg.considered_subject_ids) == 12,
            detail=str(len(reg.considered_subject_ids)))

    state = track_state(syn, week=15)
    universe = resolve_universe(db, league_id=league.id, week=15, state=state,
                                resolver=resolver)
    freeze_universe(db, league_id=league.id, season=syn.season, week=15,
                    universe=universe, rotation_cycle=1)
    db.flush()

    team_struct = league_weekly_structure(db, league_id=league.id, week=15,
                                          scope=SCOPE_TEAM)
    match_struct = league_weekly_structure(db, league_id=league.id, week=15,
                                           scope=SCOPE_MATCHUP)

    _assert("3b: TEAM universe contracts to the six championship teams",
            _ords(team_struct.considered_subject_ids, teams) == [1, 2, 3, 4, 5, 6],
            detail=str(_ords(team_struct.considered_subject_ids, teams)))
    _assert("3c: the six consolation teams are excluded as SUBJECTS",
            not ({7, 8, 9, 10, 11, 12}
                 & set(_ords(team_struct.considered_subject_ids, teams))))
    _assert("3d: MATCHUP universe is the two championship games only, not the "
            "five the provider reported",
            len(match_struct.considered_subject_ids) == 2,
            detail=str(len(match_struct.considered_subject_ids)))

    # The conflation this defeats: every excluded team HAS a matchup and scores.
    from db.schema import Matchup
    all_w15 = db.query(Matchup).filter(Matchup.league_id == league.id,
                                       Matchup.week == 15).count()
    _assert("3e: the excluded teams DO have provider matchups that week — "
            "'has a matchup' is not 'is on the championship track'",
            all_w15 == 5, detail=f"{all_w15} matchup rows exist")

    _assert("3f: regular-season weeks stay UNMANIFESTED and unchanged",
            len(league_weekly_structure(db, league_id=league.id, week=3,
                                        scope=SCOPE_TEAM)
                .considered_subject_ids) == 12)
    return league, teams, syn, resolver


def case_byes(db) -> None:
    _section("W1B-4 · bye teams: alive, but not matchup subjects")
    syn = namespaced(ps12(), "byes")
    league, teams = build_league(db, syn, name="ps12-byes")
    resolver = build_team_identity_resolver(db, league_id=league.id)
    db.flush()

    state = track_state(syn, week=15)
    universe = resolve_universe(db, league_id=league.id, week=15, state=state,
                                resolver=resolver)

    bye_ords = sorted(int(k.rsplit(".", 1)[-1]) for k in state.bye_team_keys)
    _assert("4a: WP1A reports two bye teams for round one",
            bye_ords == [1, 2], detail=str(bye_ords))
    _assert("4b: bye teams ARE in the frozen TEAM universe — a bye is not "
            "elimination",
            set(bye_ords) <= set(_ords(universe.team_ids, teams)),
            detail=str(_ords(universe.team_ids, teams)))

    from db.schema import Matchup
    rows = db.query(Matchup).filter(Matchup.id.in_(universe.matchup_ids)).all()
    playing = set()
    by_id = {t.id: int(k.rsplit(".", 1)[-1]) for k, t in teams.items()}
    for m in rows:
        playing.add(by_id[m.home_team_id])
        playing.add(by_id[m.away_team_id])
    _assert("4c: a bye team contributes NO matchup subject — absence of a "
            "matchup, not absence from the track",
            not (set(bye_ords) & playing), detail=str(set(bye_ords) & playing))
    _assert("4d: no phantom matchup was fabricated to carry a bye",
            len(universe.matchup_ids) == 2)


def case_rounds(db) -> None:
    _section("W1B-5 · the field contracts round by round")
    syn = namespaced(ps12(), "rounds")
    league, teams = build_league(db, syn, name="ps12-rounds")
    resolver = build_team_identity_resolver(db, league_id=league.id)
    db.flush()

    shapes = {}
    for week in (15, 16, 17):
        state = track_state(syn, week=week)
        universe = resolve_universe(db, league_id=league.id, week=week,
                                    state=state, resolver=resolver)
        shapes[week] = (_ords(universe.team_ids, teams),
                        len(universe.matchup_ids),
                        is_championship_round(state))

    _assert("5a: round 1 -> six teams, two championship games",
            shapes[15][:2] == ([1, 2, 3, 4, 5, 6], 2), detail=str(shapes[15]))
    _assert("5b: round 2 -> four teams, two games",
            shapes[16][:2] == ([1, 2, 3, 4], 2), detail=str(shapes[16]))
    _assert("5c: championship week -> the two finalists, one game",
            shapes[17][:2] == ([1, 2], 1), detail=str(shapes[17]))
    _assert("5d: only the final round is identified as the championship round",
            [shapes[w][2] for w in (15, 16, 17)] == [False, False, True],
            detail=str([shapes[w][2] for w in (15, 16, 17)]))

    # A DIFFERENT LEAGUE SHAPE, so nothing above is tuned to twelve-and-six.
    ten = namespaced(ps10(), "rounds")
    l10, t10 = build_league(db, ten, name="ps10-rounds")
    r10 = build_team_identity_resolver(db, league_id=l10.id)
    db.flush()
    s16 = track_state(ten, week=16)
    u16 = resolve_universe(db, league_id=l10.id, week=16, state=s16,
                           resolver=r10)
    _assert("5e: PS10 round 1 -> four teams, no byes, and it is NOT the "
            "championship round",
            (_ords(u16.team_ids, t10), len(u16.matchup_ids),
             is_championship_round(s16)) == ([1, 2, 3, 4], 2, False),
            detail=str((_ords(u16.team_ids, t10), len(u16.matchup_ids))))
    s17 = track_state(ten, week=17)
    _assert("5f: PS10's championship round is round TWO — the themed week is "
            "found by arithmetic, not by week number",
            is_championship_round(s17) and s17.championship_round_ordinal == 2,
            detail=str(s17.championship_round_ordinal))


# ── 3 · Fail-closed refusals ─────────────────────────────────────────────────

def case_refusals(db) -> None:
    _section("W1B-6 · undeterminable or unresolvable state refuses")
    syn = namespaced(ps12(), "refuse")
    league, teams = build_league(db, syn, name="ps12-refuse")
    resolver = build_team_identity_resolver(db, league_id=league.id)
    seed_catalog(db)
    ready_postseason(db, league.id)
    db.flush()

    def _refusal(state, week=15):
        try:
            resolve_universe(db, league_id=league.id, week=week, state=state,
                             resolver=resolver)
            return None
        except PostseasonSubjectError as exc:
            return exc.reason

    _assert("6a: no championship state supplied -> refuse",
            _refusal(None) == "CHAMPIONSHIP_STATE_NOT_SUPPLIED")

    # The live-Yahoo shape: brackets unclassified, so the track is UNKNOWN.
    unclassified = track_state(
        syn, week=15,
        weeks_override={15: tuple(
            m.__class__(**{**m.__dict__, "bracket": m.bracket.__class__.UNKNOWN})
            for m in syn.weeks[15])})
    _assert("6b: an UNKNOWN championship track -> refuse, with no fallback to "
            "the league's twelve teams",
            _refusal(unclassified) == "CHAMPIONSHIP_STATE_UNKNOWN",
            detail=str(unclassified.authority))

    # Slate build must refuse BEFORE any occurrence exists.
    from db.schema import PoolInstance
    before = db.query(PoolInstance).filter(
        PoolInstance.league_id == league.id).count()
    refused = None
    try:
        build_and_persist_slate(db, league=league, season=syn.season, week=15,
                                phase=PHASE_POSTSEASON, provider=PROVIDER,
                                championship=unclassified, resolver=resolver)
    except PostseasonSubjectError as exc:
        refused = exc.reason
    db.flush()
    after = db.query(PoolInstance).filter(
        PoolInstance.league_id == league.id).count()
    _assert("6c: the postseason slate build refuses on UNKNOWN",
            refused == "CHAMPIONSHIP_STATE_UNKNOWN", detail=str(refused))
    _assert("6d: and NO occurrence was published by the refused draw",
            before == after == 0, detail=f"{before} -> {after}")
    _assert("6e: nor was any manifest row frozen by the refused draw",
            frozen_subject_ids(db, league_id=league.id, season=syn.season,
                               week=15, scope=SCOPE_TEAM) is None)

    # An unjoinable championship matchup key.
    from db.schema import Matchup
    row = (db.query(Matchup)
           .filter(Matchup.league_id == league.id, Matchup.week == 15)
           .order_by(Matchup.id).first())
    keep = row.provider_matchup_key
    row.provider_matchup_key = None
    db.flush()
    reason = _refusal(track_state(syn, week=15))
    row.provider_matchup_key = keep
    db.flush()
    _assert("6f: a championship matchup with no joinable provider key fails "
            "closed rather than being silently dropped",
            reason == "CHAMPIONSHIP_MATCHUP_UNRESOLVED", detail=str(reason))


# ── 4 · The freeze ───────────────────────────────────────────────────────────

def case_freeze(db) -> None:
    _section("W1B-7 · the frozen field does not move")
    syn = namespaced(ps12(), "freeze")
    league, teams = build_league(db, syn, name="ps12-freeze")
    resolver = build_team_identity_resolver(db, league_id=league.id)
    db.flush()

    state = track_state(syn, week=16)
    universe = resolve_universe(db, league_id=league.id, week=16, state=state,
                                resolver=resolver)
    freeze_universe(db, league_id=league.id, season=syn.season, week=16,
                    universe=universe, rotation_cycle=1)
    db.flush()
    published = league_weekly_structure(db, league_id=league.id, week=16,
                                        scope=SCOPE_TEAM).considered_subject_ids

    _assert("7a: the published field is the four semi-finalists",
            _ords(published, teams) == [1, 2, 3, 4],
            detail=str(_ords(published, teams)))

    # SIMULATED PROVIDER REFRESH producing a GENUINELY DIFFERENT answer for the
    # same week. Round one's field — six teams, two of them on byes — is what a
    # stale-or-corrected refresh could plausibly resolve week 16 to if anything
    # recomputed it. It is a real, larger, wrong-for-this-week universe, which
    # is exactly the shape of the drift the freeze exists to absorb.
    divergent = resolve_universe(db, league_id=league.id, week=15,
                                 state=track_state(syn, week=15),
                                 resolver=resolver)
    _assert("7b: the simulated refresh really does resolve a DIFFERENT field "
            "(control — otherwise 7c and 7d prove nothing)",
            _ords(divergent.team_ids, teams) != _ords(published, teams),
            detail=str(_ords(divergent.team_ids, teams)))

    after_refresh = league_weekly_structure(db, league_id=league.id, week=16,
                                            scope=SCOPE_TEAM).considered_subject_ids
    _assert("7c: the published field is unchanged by it — the read consults "
            "the manifest, never live provider state",
            after_refresh == published,
            detail=f"{_ords(after_refresh, teams)} vs {_ords(published, teams)}")

    # A SECOND FREEZE PROPOSING A DIFFERENT FIELD IS A CONFLICT, NOT AN UPDATE.
    # Taken on a SAVEPOINT so the refusal cannot damage the surrounding
    # transaction — which is how a production caller would take it too.
    conflict = None
    savepoint = db.begin_nested()
    try:
        freeze_universe(db, league_id=league.id, season=syn.season, week=16,
                        universe=divergent, rotation_cycle=1)
        savepoint.rollback()
    except PostseasonSubjectError as exc:
        conflict = exc.reason
        savepoint.rollback()
    _assert("7d: refreezing a DIFFERENT field is refused outright",
            conflict == "CHAMPIONSHIP_MANIFEST_CONFLICT", detail=str(conflict))

    # Re-freezing the SAME field is a no-op, so a retried build is safe.
    freeze_universe(db, league_id=league.id, season=syn.season, week=16,
                    universe=universe, rotation_cycle=1)
    db.flush()
    _assert("7e: refreezing the SAME field is idempotent",
            league_weekly_structure(db, league_id=league.id, week=16,
                                    scope=SCOPE_TEAM)
            .considered_subject_ids == published)

    # AN APPLICATION / CATALOG UPDATE MUST NOT REINTERPRET IT EITHER. Nothing
    # about the manifest is derived from the catalog, so re-seeding the whole
    # catalog — a deployment action — cannot move a published field.
    seed_catalog(db)
    db.flush()
    _assert("7f: re-seeding the catalog does not reinterpret a frozen field",
            league_weekly_structure(db, league_id=league.id, week=16,
                                    scope=SCOPE_TEAM)
            .considered_subject_ids == published)
    _assert("7g: no Yahoo field is stored — the manifest is internal ids only",
            _manifest_columns_are_internal())


def _manifest_columns_are_internal() -> bool:
    from db.schema import PoolWeekSubjectManifest as M

    allowed = {"id", "league_id", "season", "week", "scope", "subject_id",
               "rotation_cycle", "frozen_at"}
    return {c.name for c in M.__table__.columns} == allowed


# ── 5 · Claim/view anti-drift and participation ──────────────────────────────

def case_claims(db) -> None:
    _section("W1B-8 · offered set == accepted set, and eliminated GMs play")
    syn = namespaced(ps12(), "claims")
    league, teams = build_league(db, syn, name="ps12-claims")
    seed_catalog(db)
    ready_postseason(db, league.id)
    resolver = build_team_identity_resolver(db, league_id=league.id)
    _add_kickoff(db, season=syn.season, week=15, name="ps12-claims")
    db.flush()

    state = track_state(syn, week=15)
    slate = build_and_persist_slate(db, league=league, season=syn.season,
                                    week=15, phase=PHASE_POSTSEASON,
                                    provider=PROVIDER, championship=state,
                                    resolver=resolver)
    db.flush()
    _assert("8a: the postseason week drew FOUR cards",
            len(slate.instances) == 4, detail=str(len(slate.instances)))

    views = week_claim_view(db, league_id=league.id, season=syn.season,
                            week=15, viewer_team_id=None)
    _assert("8b: every card was offered a non-empty option set",
            all(v.subjects for v in views),
            detail=str([len(v.subjects) for v in views]))

    team_view = next(v for v in views if v.scope == SCOPE_TEAM)
    offered = {s.subject_id for s in team_view.subjects}
    _assert("8c: the offered TEAM options are the six championship teams",
            _ords(offered, teams) == [1, 2, 3, 4, 5, 6],
            detail=str(_ords(offered, teams)))

    instance = next(i for i in slate.instances
                    if i.definition_key == team_view.definition_key)
    eliminated = teams[syn.team_key(9)]          # a consolation team
    alive = teams[syn.team_key(3)]
    consolation_gm = teams[syn.team_key(11)]     # a GM whose own team is out

    refused = None
    try:
        submit_claim(db, pool_instance_id=instance.id,
                     team_id=consolation_gm.id, subject_id=eliminated.id)
    except PoolClaimError as exc:
        refused = exc.reason
    _assert("8d: a DIRECT claim on an eliminated team is rejected server-side "
            "— UI filtering is not the boundary",
            refused == "INVALID_SUBJECT", detail=str(refused))

    ok = submit_claim(db, pool_instance_id=instance.id,
                      team_id=consolation_gm.id, subject_id=alive.id)
    db.flush()
    _assert("8e: the SAME eliminated GM may still participate by picking a "
            "championship team",
            ok is not None and ok.selected_subject_id == alive.id)

    for tid in (teams[syn.team_key(7)].id, teams[syn.team_key(12)].id):
        submit_claim(db, pool_instance_id=instance.id, team_id=tid,
                     subject_id=alive.id)
    db.flush()
    _assert("8f: every league member is a participant regardless of bracket "
            "status — no 'your team must be alive' rule was introduced",
            _claim_count(db, instance.id) == 3,
            detail=str(_claim_count(db, instance.id)))

    # THE ANTI-DRIFT PROOF: the two sets are the same object, not two that agree.
    accepted = league_weekly_structure(db, league_id=league.id, week=15,
                                       scope=SCOPE_TEAM).considered_subject_ids
    _assert("8g: offered set and accepted set are identical",
            set(offered) == set(accepted),
            detail=f"offered={len(offered)} accepted={len(accepted)}")

    matchup_view = next((v for v in views if v.scope == SCOPE_MATCHUP), None)
    if matchup_view is not None:
        _assert("8h: MATCHUP options are championship games only",
                len(matchup_view.subjects) == 2,
                detail=str(len(matchup_view.subjects)))
    else:
        _assert("8h: MATCHUP options are championship games only",
                True, detail="no MATCHUP card in this draw")
    return league, teams, syn, resolver, slate


def _claim_count(db, instance_id: int) -> int:
    from db.schema import PoolClaim

    return (db.query(PoolClaim)
            .filter(PoolClaim.pool_instance_id == instance_id).count())


def _add_kickoff(db, *, season: int, week: int, name: str) -> None:
    from datetime import timedelta

    from db.schema import NflSchedule

    kickoff = datetime.now(timezone.utc) + timedelta(days=2)
    kickoff = kickoff.replace(hour=17, minute=0, second=0, microsecond=0,
                              tzinfo=None)
    db.add(NflSchedule(season=season, week=week,
                       home_team=f"H{week}-{name}", away_team=f"A{week}-{name}",
                       kickoff_utc=kickoff))
    # COMMITTED, NOT FLUSHED. `betting.pool_engine._nfl_lock_time` opens its own
    # SessionLocal, so an uncommitted schedule row is invisible to the lock
    # resolution the claim path performs — the fixture has to be durable, not
    # merely pending.
    db.commit()


# ── 6 · Rotation and the themed championship week ────────────────────────────

def case_rotation(db) -> None:
    _section("W1B-9 · postseason rotates, and the title week is themed")
    syn = namespaced(ps12(), "rotate")
    league, teams = build_league(db, syn, name="ps12-rotate")
    seed_catalog(db)
    ready_postseason(db, league.id)
    resolver = build_team_identity_resolver(db, league_id=league.id)
    db.flush()

    drawn: dict[int, tuple[str, ...]] = {}
    for week in (15, 16, 17):
        _add_kickoff(db, season=syn.season, week=week, name=f"rot{week}")
        state = track_state(syn, week=week)
        result = build_and_persist_slate(
            db, league=league, season=syn.season, week=week,
            phase=PHASE_POSTSEASON, provider=PROVIDER, championship=state,
            resolver=resolver)
        db.flush()
        drawn[week] = tuple(sorted(i.definition_key for i in result.instances))

    _assert("9a: every postseason week drew four cards",
            all(len(v) == 4 for v in drawn.values()),
            detail=str({w: len(v) for w, v in drawn.items()}))
    _assert("9b: rounds 1 and 2 drew DIFFERENT slates — the used-key filter is "
            "phase-aware now",
            drawn[15] != drawn[16],
            detail=f"{drawn[15]}\n            {drawn[16]}")
    _assert("9c: no definition repeats between round 1 and round 2",
            not (set(drawn[15]) & set(drawn[16])),
            detail=str(set(drawn[15]) & set(drawn[16])))

    preferred = set(CHAMPIONSHIP_PREFERRED_KEYS)
    _assert("9d: the championship week drew exactly the themed subset",
            set(drawn[17]) == preferred,
            detail=f"{sorted(drawn[17])}\n            {sorted(preferred)}")
    # THE DISCRIMINATING CASE for "themed, not rotated". A league whose ONLY
    # gate-2-ready postseason definitions are the four preferred ones must draw
    # them in round one; if the championship round then applied the used-key
    # subtraction, all four would be exhausted and the title week could not be
    # built at all. It draws them again, which is only possible because the
    # themed round deliberately does not subtract.
    syn2 = namespaced(ps12(), "themed")
    league2, _t2 = build_league(db, syn2, name="ps12-themed")
    r2 = build_team_identity_resolver(db, league_id=league2.id)
    mark_ready(db, league_id=league2.id, keys=CHAMPIONSHIP_PREFERRED_KEYS)
    _add_kickoff(db, season=syn2.season, week=15, name="themed15")
    db.flush()

    round1 = build_and_persist_slate(
        db, league=league2, season=syn2.season, week=15,
        phase=PHASE_POSTSEASON, provider=PROVIDER,
        championship=track_state(syn2, week=15), resolver=r2)
    db.flush()
    r1_keys = {i.definition_key for i in round1.instances}
    _assert("9e: round one consumed all four preferred definitions (setup)",
            r1_keys == preferred, detail=str(sorted(r1_keys)))

    final = build_and_persist_slate(
        db, league=league2, season=syn2.season, week=17,
        phase=PHASE_POSTSEASON, provider=PROVIDER,
        championship=track_state(syn2, week=17), resolver=r2)
    db.flush()
    _assert("9f: the title week draws the themed set AGAIN even though every "
            "one of them was already used — themed, not rotated",
            {i.definition_key for i in final.instances} == preferred,
            detail=str(sorted(i.definition_key for i in final.instances)))
    _assert("9g: the themed slate is league-independent — the same four "
            "regardless of which league's digest is ranking",
            {i.definition_key for i in final.instances} == set(drawn[17]),
            detail=str(sorted(drawn[17])))


def case_championship_fallback(db) -> None:
    _section("W1B-10 · themed week fills deterministically when short")
    syn = namespaced(ps12(), "fallback")
    league, teams = build_league(db, syn, name="ps12-fallback")
    seed_catalog(db)
    resolver = build_team_identity_resolver(db, league_id=league.id)

    # One preferred definition is NOT gate-2 ready — a partially supported week.
    keys = [d.key for d in load_catalog().definitions if d.postseason_eligible]
    withheld = CHAMPIONSHIP_PREFERRED_KEYS[1]
    mark_ready(db, league_id=league.id,
               keys=[k for k in keys if k != withheld])
    _add_kickoff(db, season=syn.season, week=17, name="fallback17")
    db.flush()

    state = track_state(syn, week=17)
    result = build_and_persist_slate(
        db, league=league, season=syn.season, week=17,
        phase=PHASE_POSTSEASON, provider=PROVIDER, championship=state,
        resolver=resolver)
    db.flush()
    keys_drawn = {i.definition_key for i in result.instances}

    _assert("10a: still four cards", len(result.instances) == 4,
            detail=str(len(result.instances)))
    _assert("10b: the unavailable preferred definition is absent",
            withheld not in keys_drawn, detail=withheld)
    _assert("10c: the three available preferred definitions all survived",
            {k for k in CHAMPIONSHIP_PREFERRED_KEYS if k != withheld}
            <= keys_drawn,
            detail=str(sorted(keys_drawn)))
    _assert("10d: the fourth slot was filled from the permitted postseason "
            "catalog, not left short",
            len(keys_drawn - set(CHAMPIONSHIP_PREFERRED_KEYS)) == 1,
            detail=str(sorted(keys_drawn - set(CHAMPIONSHIP_PREFERRED_KEYS))))
    _assert("10e: the filler is itself postseason-permitted",
            all(k in set(keys) for k in keys_drawn))


# ── 7 · Settlement over the frozen field ─────────────────────────────────────

def case_settlement(db) -> None:
    _section("W1B-11 · settlement censuses the field members picked from")
    from betting.pool_census import classify_pool
    from betting.pool_catalog import spec_from_row
    from db.schema import PoolDefinition
    from test_support_s4_pool import team_subjects

    syn = namespaced(ps12(), "settle")
    league, teams = build_league(db, syn, name="ps12-settle")
    seed_catalog(db)
    resolver = build_team_identity_resolver(db, league_id=league.id)
    db.flush()

    state = track_state(syn, week=15)
    universe = resolve_universe(db, league_id=league.id, week=15, state=state,
                                resolver=resolver)
    freeze_universe(db, league_id=league.id, season=syn.season, week=15,
                    universe=universe, rotation_cycle=1)
    db.flush()

    structure = league_weekly_structure(db, league_id=league.id, week=15,
                                        scope=SCOPE_TEAM)
    row = (db.query(PoolDefinition)
           .filter(PoolDefinition.key == "most_passing_yards").first())
    spec = spec_from_row(row)

    alive_teams = [t for k, t in sorted(teams.items())
                   if t.id in set(structure.considered_subject_ids)]
    values = {t.id: float(100 + i) for i, t in enumerate(alive_teams)}
    subjects = team_subjects(alive_teams, stat="passing_yards", values=values)
    outcome = classify_pool(spec, structure, subjects)

    _assert("11a: the census considered exactly the six frozen subjects",
            outcome.census.subjects_considered == 6,
            detail=str(outcome.census.subjects_considered))
    _assert("11b: a complete championship field settles",
            outcome.classification == "CLAIMS_PRESENT",
            detail=outcome.classification)
    _assert("11c: no eliminated team could win — none was ever a subject",
            all(sid in set(structure.considered_subject_ids)
                for sid in outcome.winning_subject_ids))

    # A BYE TEAM WITH NO DATA FAILS CLOSED — no fabricated zero (WP1B §5).
    bye_key = sorted(state.bye_team_keys)[0]
    partial = {tid: v for tid, v in values.items()
               if tid != teams[bye_key].id}
    short = team_subjects([t for t in alive_teams
                           if t.id != teams[bye_key].id],
                          stat="passing_yards", values=partial)
    outcome2 = classify_pool(spec, structure, short)
    _assert("11d: a bye team with no evaluable data makes the field INCOMPLETE "
            "— it is not scored as zero and not silently dropped",
            outcome2.classification == "INCOMPLETE_FIELD",
            detail=outcome2.classification)
    _assert("11e: and `considered` still names all six — the census did not "
            "shrink to match its own gap",
            outcome2.census.subjects_considered == 6
            and outcome2.census.subjects_evaluated == 5,
            detail=f"{outcome2.census.as_dict()}")
    _assert("11f: no claim count is computed over an incomplete field",
            outcome2.census.subjects_claiming is None)


# ── 8 · Backward compatibility ───────────────────────────────────────────────

def case_compatibility(db) -> None:
    _section("W1B-12 · unmanifested weeks keep the pre-WP1B behaviour")
    syn = namespaced(ps12(), "compat")
    league, teams = build_league(db, syn, name="ps12-compat")
    db.flush()

    _assert("12a: a REGULAR week is unmanifested",
            frozen_subject_ids(db, league_id=league.id, season=syn.season,
                               week=3, scope=SCOPE_TEAM) is None)
    _assert("12b: an unmanifested week resolves to the derived universe — the "
            "exact historical behaviour",
            len(league_weekly_structure(db, league_id=league.id, week=3,
                                        scope=SCOPE_TEAM)
                .considered_subject_ids) == 12)
    _assert("12c: an unmanifested POSTSEASON week (drawn on an older build) "
            "also resolves derived rather than empty",
            len(league_weekly_structure(db, league_id=league.id, week=15,
                                        scope=SCOPE_TEAM)
                .considered_subject_ids) == 12)
    _assert("12d: a claim on an unmanifested week validates as it always did",
            _validates(db, league.id, 3, SCOPE_TEAM,
                       teams[syn.team_key(9)].id))
    _assert("12e: phase derivation is unchanged",
            (phase_for_week(league, 3), phase_for_week(league, 15))
            == (PHASE_REGULAR, PHASE_POSTSEASON))

    # THE MIGRATION IS EXERCISED, NOT INSPECTED. The harness builds its schema
    # with create_all(), so asserting against THAT would prove only that the ORM
    # agrees with itself. The table is dropped and rebuilt by the REAL migration
    # so the production DDL is what gets checked — the same reason
    # migrate_pool_rotation_tables exposes `upgrade(engine)` at all.
    from sqlalchemy import inspect as sa_inspect, text as sa_text

    from db.migrations.migrate_wp1b_pool_subject_manifest import (
        TABLE, table_exists, upgrade,
    )
    from db.schema import PoolWeekSubjectManifest, engine

    db.commit()
    with engine.begin() as conn:
        conn.execute(sa_text(f"DROP TABLE IF EXISTS {TABLE}"))
    _assert("12f: the table is genuinely absent before the migration runs",
            not table_exists(engine))

    created = upgrade(engine)
    _assert("12g: the production migration creates it",
            table_exists(engine) and "created" in created, detail=created)
    _assert("12h: re-running the migration is a clean no-op",
            "nothing to do" in upgrade(engine))

    orm_cols = {c.name for c in PoolWeekSubjectManifest.__table__.columns}
    db_cols = {c["name"] for c in sa_inspect(engine).get_columns(TABLE)}
    _assert("12i: the migration's DDL and the ORM model agree on every column "
            "— two schema sources cannot drift",
            orm_cols == db_cols,
            detail=str(orm_cols.symmetric_difference(db_cols)))

    # ROLLBACK ORDER IS APPLICATION-FIRST, AND THE WRONG ORDER FAILS LOUDLY.
    #
    # The supported rollback is to revert the APPLICATION: pre-WP1B code never
    # queries this table, so leftover rows become inert and every league-week
    # resolves derived — no data is stranded and no balance is touched, because
    # the manifest carries no money.
    #
    # Dropping the TABLE while the new code is still deployed is the WRONG
    # order, and this asserts it fails rather than silently resolving to the
    # full twelve-team universe. A silent fallback there would be worse than an
    # error: it would quietly re-admit consolation teams to a live postseason.
    with engine.begin() as conn:
        conn.execute(sa_text(f"DROP TABLE IF EXISTS {TABLE}"))
    behaviour = None
    try:
        from db.schema import SessionLocal
        with SessionLocal() as fresh:
            behaviour = len(league_weekly_structure(
                fresh, league_id=league.id, week=15,
                scope=SCOPE_TEAM).considered_subject_ids)
    except Exception:                               # noqa: BLE001 - expected
        behaviour = "raised"
    upgrade(engine)
    _assert("12j: dropping the manifest table under a running WP1B build fails "
            "loudly rather than silently re-admitting eliminated teams",
            behaviour == "raised", detail=str(behaviour))
    _assert("12k: and the migration restores it", table_exists(engine))


def _validates(db, league_id: int, week: int, scope: str,
               subject_id: int) -> bool:
    from betting.pool_claims import _validate_subject

    try:
        _validate_subject(db, league_id=league_id, week=week, scope=scope,
                          subject_id=subject_id)
        return True
    except PoolClaimError:
        return False


# ── 9 · Weekly Minimum, ledger and regular-season control ────────────────────

def case_invariants(db) -> None:
    _section("W1B-13 · untouched baselines")
    from economy.weekly_minimum import is_release_week
    from ledger.ledger import trial_balance

    syn = namespaced(ps12(), "invariant")
    league, teams = build_league(db, syn, name="ps12-invariant")
    db.flush()

    _assert("13a: no Weekly Minimum releases in the postseason",
            is_release_week(league, 14) and not is_release_week(league, 15)
            and not is_release_week(league, 17))
    _assert("13b: the ledger trial balance is zero",
            trial_balance() == 0, detail=str(trial_balance()))

    # THE REGULAR SEASON IS THE CONTROL, and it is asserted end to end rather
    # than by inspection: a regular week still draws four cards from the
    # regular-season set with no championship state supplied at all.
    seed_catalog(db)
    from test_support_s4_pool import FOUR_TEAM_KEYS
    mark_ready(db, league_id=league.id, keys=FOUR_TEAM_KEYS)
    _add_kickoff(db, season=syn.season, week=3, name="ctrl3")
    db.flush()
    result = build_and_persist_slate(db, league=league, season=syn.season,
                                     week=3, phase=PHASE_REGULAR,
                                     provider=PROVIDER)
    db.flush()
    _assert("13c: a regular-season week draws four cards with NO championship "
            "state supplied",
            len(result.instances) == 4, detail=str(len(result.instances)))
    _assert("13d: and it drew from the regular-season set",
            {i.definition_key for i in result.instances} == set(FOUR_TEAM_KEYS),
            detail=str(sorted(i.definition_key for i in result.instances)))
    _assert("13e: the regular week is still unmanifested",
            frozen_subject_ids(db, league_id=league.id, season=syn.season,
                               week=3, scope=SCOPE_TEAM) is None)
    _assert("13f: the ledger is still balanced after a draw",
            trial_balance() == 0, detail=str(trial_balance()))

    # THE DEPLOYMENT DRIFT GATE. `scripts/bootstrap_pool_catalog.py --check`
    # used to compare only the set of KEYS, which would have reported OK on a
    # database seeded before WP1B — every row present, every postseason flag
    # still null, and an empty postseason candidate set at runtime.
    from db.schema import PoolDefinition
    from scripts.bootstrap_pool_catalog import _value_drift

    catalog = load_catalog()
    _assert("13g: a freshly seeded database reports no governed drift",
            _value_drift(db, catalog) == [],
            detail=str(_value_drift(db, catalog)[:3]))

    victim = (db.query(PoolDefinition)
              .filter(PoolDefinition.key == "most_passing_yards").first())
    victim.postseason_eligible = None
    db.flush()
    drift = _value_drift(db, catalog)
    _assert("13h: a stale postseason_eligible IS reported as drift — the gate "
            "now checks currency, not just presence",
            [(k, f) for k, f, _w, _g in drift]
            == [("most_passing_yards", "postseason_eligible")],
            detail=str(drift))
    victim.postseason_eligible = True
    db.flush()


def main() -> None:
    case_catalog()
    case_guard()

    with tdb.SessionLocal() as db:
        case_contraction(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_byes(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_rounds(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_refusals(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_freeze(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_claims(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_rotation(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_championship_fallback(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_settlement(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_compatibility(db)
        db.commit()
    with tdb.SessionLocal() as db:
        case_invariants(db)
        db.commit()


if __name__ == "__main__":
    print("  WP1B — POSTSEASON POOL CATALOG & ELIGIBILITY")
    tdb.reset()
    main()
    print()
    if _failures:
        print(f"RESULT: {len(_failures)} assertion(s) FAILED")
        for label in _failures:
            print(f"  - {label}")
        sys.exit(1)
    print("RESULT: all WP1B postseason Pool assertions PASSED")
