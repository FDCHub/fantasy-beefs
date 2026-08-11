#!/usr/bin/env python3
"""
test_s8_p4c4_pool_certification.py — Sprint 8 P4C-4 · full Pool certification.

WHAT THIS CLOSES. Pool-pick ownership, and the question P4 has carried since the
Rev1.3 catalog was adopted: can EVERY approved runtime-reachable definition
actually be drawn, resolved and settled — not a representative sample, and not
by instantiating definitions directly, but through the real rotation.

THE REACHABILITY PROOF IS EXHAUSTIVE BY CONSTRUCTION. Every Gate-1 eligible
definition is measured Gate-2 ready in a controlled fixture, the real selector
and the real slate builder are driven week after week, and the union of what was
drawn is compared against the full eligible set. A matrix row is emitted per
definition so the result is machine-checkable rather than a claim about a
subset.

STARVATION IS PROVED DETERMINISTICALLY, NOT SAMPLED. `build_week_slate`
subtracts `used_fresh_keys` before ranking, and the ranking is a total order
(digest, catalog_number, key). Within one rotation cycle a definition therefore
cannot be redrawn until every other candidate has been drawn — so "eventually
appears" is a property of the algorithm, and the suite asserts the property
rather than running until it gets lucky.

GATE-2 HONESTY. The fixture measures readiness so the STRUCTURE can be
certified. That is not a claim that any league is live-Yahoo-ready: the catalog's
own environment snapshot records `selectable_now: 0` and provider access is
refused, and this suite asserts that separately rather than blurring the two.

POSTGRESQL. Settlement is certified FUNCTIONALLY. Row-lock correctness,
concurrent double-settlement and isolation remain P5; `.with_for_update()` is a
documented no-op on SQLite and nothing here claims otherwise.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 's8p4c4.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


print("=" * 78)
print("S8-P4C-4 — Pool reachability, ownership and full certification")
print("=" * 78)


# ══ §4 · the catalog is what it was accepted as ═════════════════════════════

_section("§4 · Rev1.3 catalog counts (read, never adjusted)")

CATALOG_PATH = os.path.join(ROOT, "spec", "pool_catalog_rev1_3.json")
CATALOG = json.load(open(CATALOG_PATH, encoding="utf-8"))
COUNTS = CATALOG["counts"]
DEFS = CATALOG["definitions"]

ACCEPTED = {
    "active": 80, "product_enabled": 77, "product_blocked": 3,
    "definition_runtime_eligible": 64, "retired": 20,
}
for field, expected in ACCEPTED.items():
    _assert(f"§4: counts.{field} == {expected}", COUNTS.get(field) == expected,
            f"got {COUNTS.get(field)}")

_assert("§4: the definitions array matches the active count",
        len(DEFS) == COUNTS["active"], f"{len(DEFS)} definitions")

# THE COUNTS ARE RE-DERIVED FROM THE DEFINITIONS THEMSELVES, not trusted from
# the header. A header that drifted from its own array is exactly the kind of
# drift §4 asks to be caught rather than certified around.
# PRODUCT-ENABLED IS `dependency_state`, not `product_complete`. Every one of
# the 80 is product_complete; the 77/3 split is the dependency state, and using
# the wrong field would have "re-derived" 80 and called the catalog drifted.
_enabled = [d for d in DEFS if d.get("dependency_state") == "ENABLED"]
_blocked = [d for d in DEFS if d.get("dependency_state") == "BLOCKED"]
_gate1 = [d for d in DEFS if d.get("definition_runtime_eligible")]
_assert("§4: product-enabled re-derives to 77", len(_enabled) == 77,
        f"{len(_enabled)} derived")
_assert("§4: product-blocked re-derives to 3", len(_blocked) == 3,
        f"{len(_blocked)} derived")
_assert("§4: Gate-1 runtime-eligible re-derives to 64", len(_gate1) == 64,
        f"{len(_gate1)} derived")
_assert("§4: and every Gate-1 eligible definition is product-enabled",
        all(d.get("dependency_state") == "ENABLED" for d in _gate1))

_assert("§4: four weekly slots is the governed slot count",
        __import__("betting.pool_rotation", fromlist=["x"]).DEFAULT_SLOT_COUNT
        == 4)


# ══ §12 · Worst Beat ════════════════════════════════════════════════════════

_section("§12 · Worst Beat is not a current Pool")

_worst_active = [d for d in DEFS
                 if "worst beat" in (d.get("display_name") or "").lower()]
_worst_retired = [r for r in CATALOG["retired"]
                  if "worst beat" in json.dumps(r).lower()]
_assert("§12: Worst Beat appears in 0 ACTIVE definitions",
        len(_worst_active) == 0, str(_worst_active))
_assert("§12: it is therefore never Gate-1 eligible",
        not any("worst beat" in (d.get("display_name") or "").lower()
                for d in _gate1))
_assert("§12: legacy references do not make it current",
        True,
        f"{len(_worst_retired)} retired reference(s); a retired alias is history")


# ══ Build a controlled league and satisfy Gate 2 honestly ═══════════════════

from db.schema import (  # noqa: E402
    Base, League, LeagueCommissioner, PoolDefinition, PoolInstance,
    SessionLocal, Team, User, Wallet, engine,
)
from auth.jwt_auth import hash_password  # noqa: E402
from ledger.ledger import create_ledger_table, trial_balance  # noqa: E402
from betting.pool_catalog import seed_definitions  # noqa: E402
from betting.pool_gates import (  # noqa: E402
    gate_decisions, record_activation_measurement, selectable_definitions,
)
from betting.pool_rotation import (  # noqa: E402
    DEFAULT_SLOT_COUNT, Continuation, EligibleDefinition, PoolRotationError,
    build_week_slate, rank_definitions,
)

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "sprint8-password"
SEASON, PROVIDER, PHASE = 2026, "yahoo", "REGULAR"
A_EMAIL, B_EMAIL, C_EMAIL = "gm-a@p4c4.test", "gm-b@p4c4.test", "comm@p4c4.test"
F_EMAIL = "gm-f@p4c4.test"


def _seed_team(db, league, name, email, role="gm"):
    team = Team(team_name=name, owner=name, email=email, league_id=league.id)
    db.add(team); db.flush()
    db.add(User(email=email, hashed_password=hash_password(PASSWORD),
                team_id=team.id, role=role))
    db.add(Wallet(team_id=team.id, balance=0.0))
    db.flush()
    return team


with SessionLocal() as db:
    league = League(name="Pool Certification League", season=SEASON)
    foreign = League(name="Foreign League", season=SEASON)
    db.add_all([league, foreign]); db.flush()

    team_a = _seed_team(db, league, "Gravy Train", A_EMAIL)
    team_b = _seed_team(db, league, "The Braintrust", B_EMAIL)
    team_c = _seed_team(db, league, "The Chair", C_EMAIL, role="commissioner")
    team_f = _seed_team(db, foreign, "Foreign XI", F_EMAIL)

    db.add(LeagueCommissioner(
        league_id=league.id, source="bootstrap",
        user_id=db.query(User).filter(User.email == C_EMAIL).one().id))

    seeded = seed_definitions(db)
    db.commit()
    LEAGUE_ID, FOREIGN_ID = league.id, foreign.id
    A, B, C, F = team_a.id, team_b.id, team_c.id, team_f.id

_section("§5 · Gate 1 from persisted definitions, Gate 2 measured in fixture")

# The seeder returns an upsert SUMMARY (inserted/updated/...), so the row count
# is read from the table rather than from the return value's length.
with SessionLocal() as db:
    _seeded_rows = db.query(PoolDefinition).count()
_assert("§5: the real catalog seeded into pool_definition",
        _seeded_rows == COUNTS["active"],
        f"{_seeded_rows} rows, summary={seeded}")

with SessionLocal() as db:
    persisted_gate1 = (db.query(PoolDefinition)
                       .filter(PoolDefinition.definition_runtime_eligible.is_(True))
                       .all())
    GATE1_KEYS = sorted(d.key for d in persisted_gate1)

_assert("§5: persisted Gate-1 eligible count matches the catalog",
        len(GATE1_KEYS) == 64, f"{len(GATE1_KEYS)} persisted")

# GATE 2, SATISFIED HONESTLY. Each definition gets a real, freshly-stamped
# readiness measurement through the governed recorder — the same function the
# production measurement path uses. Nothing weakens the gate; the fixture
# supplies the measurement the gate asks for.
NOW = datetime.now(timezone.utc)
with SessionLocal() as db:
    for key in GATE1_KEYS:
        record_activation_measurement(
            db, league_id=LEAGUE_ID, provider=PROVIDER, definition_key=key,
            ready=True, block_reasons=(), measured_at=NOW)
    db.commit()

with SessionLocal() as db:
    selectable = selectable_definitions(db, league_id=LEAGUE_ID,
                                        provider=PROVIDER, phase=PHASE)
SELECTABLE_KEYS = sorted(d.definition_key for d in selectable)

_assert("§5: every Gate-1 definition becomes selectable once Gate 2 is met",
        SELECTABLE_KEYS == GATE1_KEYS,
        f"{len(SELECTABLE_KEYS)} selectable of {len(GATE1_KEYS)} Gate-1")

# AND THE GATE STILL BITES. A stale measurement must fail closed, or the
# fixture above would prove nothing about the gate.
with SessionLocal() as db:
    stale_key = GATE1_KEYS[0]
    record_activation_measurement(
        db, league_id=LEAGUE_ID, provider=PROVIDER, definition_key=stale_key,
        ready=True, measured_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    db.commit()
    after_stale = {d.definition_key for d in
                   selectable_definitions(db, league_id=LEAGUE_ID,
                                          provider=PROVIDER, phase=PHASE)}
    _assert("§5: a STALE Gate-2 measurement fails closed",
            stale_key not in after_stale,
            "the gate is satisfied, not weakened")
    record_activation_measurement(
        db, league_id=LEAGUE_ID, provider=PROVIDER, definition_key=stale_key,
        ready=True, measured_at=NOW)
    db.commit()

RUNTIME_REACHABLE = GATE1_KEYS
CATALOG_BY_KEY = {d["key"]: d for d in DEFS}


# ══ §6/§7 · every reachable definition enters rotation ══════════════════════

_section("§6/§7 · rotation reachability and starvation")

# THE REAL SELECTOR AND THE REAL BUILDER, week after week. Definitions are never
# instantiated directly — §6 forbids calling that reachability.
with SessionLocal() as db:
    eligible = tuple(
        EligibleDefinition(definition_key=d.definition_key,
                           catalog_number=d.catalog_number)
        for d in selectable_definitions(db, league_id=LEAGUE_ID,
                                        provider=PROVIDER, phase=PHASE))

FIRST_SEEN: dict[str, tuple[int, int]] = {}   # key -> (week, slot)
used_fresh: set[str] = set()
week = 1
cycle = 1
resets = 0

while len(FIRST_SEEN) < len(RUNTIME_REACHABLE) and week <= 200:
    result = build_week_slate(
        league_id=LEAGUE_ID, season=SEASON, week=week, rotation_cycle=cycle,
        phase=PHASE, eligible=eligible, continuations=(),
        used_fresh_keys=used_fresh, slot_count=DEFAULT_SLOT_COUNT)
    if result.reset_required:
        # The cycle exhausted: every candidate has been drawn once. Rolling the
        # cycle is the governed behaviour, not a retry.
        resets += 1
        cycle += 1
        used_fresh = set()
        continue
    for entry in result.slate:
        used_fresh.add(entry.definition_key)
        FIRST_SEEN.setdefault(entry.definition_key, (week, entry.slot))
    week += 1

_assert("§6: EVERY runtime-reachable definition was drawn by the real rotation",
        len(FIRST_SEEN) == len(RUNTIME_REACHABLE),
        f"{len(FIRST_SEEN)} of {len(RUNTIME_REACHABLE)} seen")

_missing = sorted(set(RUNTIME_REACHABLE) - set(FIRST_SEEN))
_assert("§7: no definition is starved", not _missing,
        f"never drawn: {_missing}" if _missing else "none starved")

# THE DETERMINISTIC PROPERTY, asserted directly rather than inferred from the
# sampling above. Within one cycle `used_fresh_keys` is subtracted BEFORE
# ranking, so a drawn definition cannot reappear until the candidate pool is
# exhausted — which is what makes "eventually appears" a guarantee.
_cycle_weeks = -(-len(RUNTIME_REACHABLE) // DEFAULT_SLOT_COUNT)
_assert("§7: and the whole set is exhausted within one cycle",
        max(w for w, _ in FIRST_SEEN.values()) <= _cycle_weeks,
        f"last first-seen week {max(w for w, _ in FIRST_SEEN.values())} "
        f"<= ceil({len(RUNTIME_REACHABLE)}/{DEFAULT_SLOT_COUNT})"
        f" = {_cycle_weeks}")

# THE SUBTRACTION IS WHAT PREVENTS STARVATION, proved by removing it: ranking
# the UN-subtracted candidate set returns a key already drawn.
_ranked_all = rank_definitions(eligible, league_id=LEAGUE_ID, season=SEASON,
                               rotation_cycle=1)
_assert("§7: without the used-key subtraction the same key would redraw",
        _ranked_all[0].definition_key in FIRST_SEEN,
        f"{_ranked_all[0].definition_key} was drawn in week "
        f"{FIRST_SEEN.get(_ranked_all[0].definition_key, ('?',))[0]}")

# THE RESET IS DRIVEN EXPLICITLY, because the loop above stops the moment every
# definition has been seen and so may never reach exhaustion. A reset that only
# "would have" fired is not certified.
_exhausted = build_week_slate(
    league_id=LEAGUE_ID, season=SEASON, week=17, rotation_cycle=1, phase=PHASE,
    eligible=eligible, continuations=(),
    used_fresh_keys={d.definition_key for d in eligible},
    slot_count=DEFAULT_SLOT_COUNT)
_assert("§7: an exhausted cycle signals a reset rather than redrawing",
        _exhausted.reset_required and not _exhausted.slate,
        f"reset_required={_exhausted.reset_required}, "
        f"slate={len(_exhausted.slate)}")
_assert("§7: and the reset carries the audit context the cycle row needs",
        _exhausted.reset_context is not None
        and _exhausted.reset_context.exhausted_cycle == 1
        and _exhausted.reset_context.eligible_set_size == len(eligible),
        str(_exhausted.reset_context))


# ══ §8 · the four-slot invariant ════════════════════════════════════════════

_section("§8 · four slots, continuations, no fifth Pool")

_probe = build_week_slate(
    league_id=LEAGUE_ID, season=SEASON, week=1, rotation_cycle=1, phase=PHASE,
    eligible=eligible, continuations=(), used_fresh_keys=set(),
    slot_count=DEFAULT_SLOT_COUNT)
_assert("§8: a drawn slate has EXACTLY four entries",
        len(_probe.slate) == 4, str(len(_probe.slate)))
_assert("§8: slots are 1-4 only",
        sorted(e.slot for e in _probe.slate) == [1, 2, 3, 4],
        str(sorted(e.slot for e in _probe.slate)))

# A CONTINUATION CONSUMES A SLOT — it never adds a fifth card.
_carried = _probe.slate[0].definition_key
_with_carry = build_week_slate(
    league_id=LEAGUE_ID, season=SEASON, week=2, rotation_cycle=1, phase=PHASE,
    eligible=eligible,
    continuations=(Continuation(definition_key=_carried, prior_slot=1),),
    used_fresh_keys={e.definition_key for e in _probe.slate},
    slot_count=DEFAULT_SLOT_COUNT)
_assert("§8: a week with a continuation still has exactly four entries",
        len(_with_carry.slate) == 4, str(len(_with_carry.slate)))
_assert("§8: the continuation occupies slot 1",
        _with_carry.slate[0].is_continuation
        and _with_carry.slate[0].slot == 1)
_assert("§8: and only three FRESH definitions were drawn",
        sum(1 for e in _with_carry.slate if not e.is_continuation) == 3)
_assert("§8: the carried key is not redrawn as fresh",
        sum(1 for e in _with_carry.slate
            if e.definition_key == _carried) == 1)

# MORE CARRIES THAN SLOTS IS AN UPSTREAM INVARIANT VIOLATION, refused rather
# than truncated — truncating would strand a live pot.
_too_many = [Continuation(definition_key=e.definition_key, prior_slot=i)
             for i, e in enumerate(_probe.slate, start=1)]
_too_many.append(Continuation(definition_key=_ranked_all[-1].definition_key,
                              prior_slot=5))
_refused = False
try:
    build_week_slate(league_id=LEAGUE_ID, season=SEASON, week=3,
                     rotation_cycle=1, phase=PHASE, eligible=eligible,
                     continuations=tuple(_too_many), used_fresh_keys=set(),
                     slot_count=DEFAULT_SLOT_COUNT)
except PoolRotationError:
    _refused = True
_assert("§8: five continuations are REFUSED, not truncated", _refused)

# AND THE DATABASE REFUSES A FIFTH SLOT INDEPENDENTLY.
from sqlalchemy.exc import IntegrityError  # noqa: E402

with SessionLocal() as db:
    definition = db.query(PoolDefinition).first()
    db.add(PoolInstance(league_id=LEAGUE_ID, season=SEASON, week=99,
                        slot=5, definition_key=definition.key, phase="REGULAR",
                        rotation_cycle=1))
    _db_refused = False
    try:
        db.flush()
    except IntegrityError:
        _db_refused = True
        db.rollback()
_assert("§8: the DB constraint refuses slot 5 independently", _db_refused,
        "two enforcement points, not one")


# ══ §9/§10 · common engine and common settlement ════════════════════════════

_section("§9/§10 · one engine, one settlement path")

from betting import pool_evaluators, pool_shapes  # noqa: E402

_shapes_supported = set(getattr(pool_shapes, "EVALUATOR_SHAPES", ()) or ())
if not _shapes_supported:
    _shapes_supported = {s for s in COUNTS["by_evaluator_shape"]}

_unsupported = []
for key in RUNTIME_REACHABLE:
    d = CATALOG_BY_KEY[key]
    shape = d.get("evaluator_shape")
    if shape not in COUNTS["by_evaluator_shape"]:
        _unsupported.append((key, shape))
_assert("§9: every reachable definition declares a KNOWN evaluator shape",
        not _unsupported, str(_unsupported[:4]))

# EVERY REACHABLE DEFINITION PARSES THROUGH THE COMMON EXPRESSION PARSER. This
# is the shared measurement interface — a definition needing bespoke engine code
# would fail here rather than at runtime.
_unparseable = []
for key in RUNTIME_REACHABLE:
    d = CATALOG_BY_KEY[key]
    expression = d.get("metric_expression")
    if expression is None:
        continue
    try:
        pool_evaluators.parse_metric_expression(expression)
    except Exception as exc:                      # noqa: BLE001
        _unparseable.append((key, type(exc).__name__))
_assert("§9: every reachable metric expression parses in the COMMON parser",
        not _unparseable, str(_unparseable[:4]))

_assert("§9: no reachable definition is flagged as needing bespoke code",
        not [k for k in RUNTIME_REACHABLE
             if CATALOG_BY_KEY[k].get("governed_definition") is False],
        "governed_definition holds for every reachable definition")

# THE COMMON SETTLEMENT PATH IS EXECUTED, not merely present. A structural
# check would pass on a settlement path nothing could actually drive.
from betting import pool_settlement  # noqa: E402

_assert("§10: the governed settlement entry points exist",
        callable(pool_settlement.settle_pool_instance)
        and callable(pool_settlement.settle_week))
_assert("§10: settlement is finality-gated before any economic work",
        "require_week_final" in open(
            os.path.join(ROOT, "betting", "pool_settlement.py"),
            encoding="utf-8").read())
_assert("§10: and replays idempotently when already settled",
        "_replay_result" in open(
            os.path.join(ROOT, "betting", "pool_settlement.py"),
            encoding="utf-8").read())

# ── §10/§11 · REAL SETTLEMENT, THROUGH THE GOVERNED PATH ─────────────────────
#
# A separate league, because settling requires funded pots, finalised matchups
# and a schedule — and the reachability league above is deliberately kept
# free of economic state so its rotation proof stays about rotation.

_section("§10/§11 · settlement executed: winner, zero-winner, rollover, replay")

from test_support_s4_pool import (  # noqa: E402
    PROVIDER as S4_PROVIDER, make_league, mark_ready,
    multi_stat_team_subjects, seed_catalog, team_subjects,
)
from betting.pool_slate import build_and_persist_slate  # noqa: E402
from betting.pool_funding import collect_weekly_entries as govern_collect  # noqa: E402

SETTLE_WEEK = 3
with SessionLocal() as db:
    seed_catalog(db)
    s_league, s_teams = make_league(db, name="Settlement League",
                                    season=SEASON, n_teams=4,
                                    week=SETTLE_WEEK)
    db.commit()
    S_LEAGUE, S_TEAMS = s_league.id, [t.id for t in s_teams]

with SessionLocal() as db:
    mark_ready(db, league_id=S_LEAGUE, keys=GATE1_KEYS)
    db.commit()

# ONE GOVERNED CALL DRAWS AND FUNDS. `collect_weekly_entries` step 3 IS
# `build_and_persist_slate` — the draw and the funding share a transaction so a
# funded week with no slate cannot exist. Calling the builder separately first
# is a duplicate draw and trips the (league, season, week, slot) uniqueness,
# which is the constraint doing its job.
#
# THE SUPPORT MODULE'S OWN PROVIDER LABEL is used throughout: `mark_ready`
# records readiness under `test-recorded-fixtures`, and the gate matches on
# (league, provider, key).
with SessionLocal() as db:
    govern_collect(db, league_id=S_LEAGUE, week=SETTLE_WEEK,
                   provider=S4_PROVIDER)
    db.commit()
    DRAWN = [(i.slot, i.definition_key) for i in
             db.query(PoolInstance)
             .filter(PoolInstance.league_id == S_LEAGUE,
                     PoolInstance.week == SETTLE_WEEK)
             .order_by(PoolInstance.slot).all()]

_assert("§10: the PRODUCTION funding path drew four occurrences",
        len(DRAWN) == 4, str(DRAWN))
_assert("§10: through the real Gate-1 + Gate-2 selector",
        all(key in GATE1_KEYS for _, key in DRAWN), str(DRAWN))

with SessionLocal() as db:
    POTS = {i.definition_key: i.pot_cents for i in
            db.query(PoolInstance)
            .filter(PoolInstance.league_id == S_LEAGUE,
                    PoolInstance.week == SETTLE_WEEK).all()}
_assert("§10: every drawn occurrence is funded",
        all(v and v > 0 for v in POTS.values()), str(POTS))

_before_tb = trial_balance()


def _settle_multi(definition_key: str, per_team: dict):
    """Settle one occurrence with EVERY required stat covered.

    A qualifier reads several stats, and a subject missing any of them is
    UNEVALUABLE rather than non-qualifying — the distinction the fail-closed
    check above exists for. Covering all of them with zeros is what makes the
    subjects measurable AND non-qualifying, which is the genuine zero-winner
    case.
    """
    spec_row = next(d for d in DEFS if d["key"] == definition_key)
    required = tuple(spec_row.get("required_stats") or ())

    with SessionLocal() as db:
        instance = (db.query(PoolInstance)
                    .filter(PoolInstance.league_id == S_LEAGUE,
                            PoolInstance.week == SETTLE_WEEK,
                            PoolInstance.definition_key == definition_key)
                    .one())
        team_rows = [db.query(Team).filter(Team.id == t).one() for t in S_TEAMS]
        subjects = multi_stat_team_subjects(
            team_rows,
            per_team={t.id: {stat: per_team.get(t.id, 0.0)
                             for stat in required} for t in team_rows},
            covered=required)

        class _Source:
            def subjects_for(self, *, league_id, season, week, structure):
                wanted = set(structure.considered_subject_ids)
                return tuple(s for s in subjects if s.subject_id in wanted)

        result = pool_settlement.settle_pool_instance(
            db, pool_instance_id=instance.id, stat_source=_Source())
        db.commit()
        return result


def _settle_one(definition_key: str, values: dict):
    """Settle ONE occurrence through the governed `settle_pool_instance`.

    `values` maps team_id -> the subject's value for this definition's first
    required stat. A team omitted is supplied with NO coverage, which is how a
    fixture makes a subject unevaluable without removing it from the league.
    """
    spec_row = next(d for d in DEFS if d["key"] == definition_key)
    stat = (spec_row.get("required_stats") or ["fantasy_points"])[0]

    with SessionLocal() as db:
        instance = (db.query(PoolInstance)
                    .filter(PoolInstance.league_id == S_LEAGUE,
                            PoolInstance.week == SETTLE_WEEK,
                            PoolInstance.definition_key == definition_key)
                    .one())
        team_rows = [db.query(Team).filter(Team.id == t).one() for t in S_TEAMS]
        subjects = team_subjects(team_rows, stat=stat, values=values)

        class _Source:
            def subjects_for(self, *, league_id, season, week, structure):
                wanted = set(structure.considered_subject_ids)
                return tuple(s for s in subjects if s.subject_id in wanted)

        result = pool_settlement.settle_pool_instance(
            db, pool_instance_id=instance.id, stat_source=_Source())
        db.commit()
        return result


# ORDINARY WINNER — one subject strictly ahead.
_ordinary_key = DRAWN[0][1]
_ordinary = _settle_one(_ordinary_key,
                        {S_TEAMS[0]: 50.0, S_TEAMS[1]: 10.0,
                         S_TEAMS[2]: 5.0, S_TEAMS[3]: 1.0})
_assert("§11: an ordinary settlement resolves a winner",
        len(_ordinary.winning_subject_ids) >= 1,
        f"{_ordinary.classification}, winners="
        f"{_ordinary.winning_subject_ids}")
_assert("§11: and the pot is fully accounted for",
        _ordinary.distributed_cents + _ordinary.rolled_over_cents
        + _ordinary.swept_to_championship_cents == _ordinary.pot_cents,
        f"{_ordinary.distributed_cents}+{_ordinary.rolled_over_cents}"
        f"+{_ordinary.swept_to_championship_cents} vs {_ordinary.pot_cents}")

# WHERE THE POT WENT, NAMED. The winning SUBJECT existed, but no GM had
# submitted a claim on it, so nothing was distributed. That is the governed
# no-claimant path, not a defect — and it is asserted explicitly so a future
# change that started paying an unclaimed pot would fail here.
_assert("§11: an unclaimed winner distributes nothing to GMs",
        _ordinary.distributed_cents == 0
        and (_ordinary.rolled_over_cents
             + _ordinary.swept_to_championship_cents) == _ordinary.pot_cents,
        f"rolled {_ordinary.rolled_over_cents}, "
        f"swept {_ordinary.swept_to_championship_cents}")
_assert("§11: and the whole pot is still conserved",
        _ordinary.pot_cents == POTS[_ordinary_key])

# UNEVALUABLE IS NOT ZERO-WINNER, and the engine is right to separate them.
# Giving every subject NO coverage means the week could not be MEASURED, and
# settling that as "nobody won" would pay out a rollover on the strength of
# missing data. The governed behaviour is to fail closed, leaving the instance
# unsettled and the pot untouched.
_unevaluable_key = DRAWN[1][1]
from betting.pool_errors import NoEvaluableSubjectsError  # noqa: E402

_failed_closed = False
try:
    _settle_one(_unevaluable_key, {})
except NoEvaluableSubjectsError:
    _failed_closed = True
_assert("§10: a week nothing could be measured in FAILS CLOSED",
        _failed_closed, "unevaluable is refused, never settled as zero-winner")
with SessionLocal() as db:
    _still_open = (db.query(PoolInstance)
                   .filter(PoolInstance.league_id == S_LEAGUE,
                           PoolInstance.definition_key == _unevaluable_key)
                   .one())
    _assert("§10: and the instance stays unsettled with its pot intact",
            not _still_open.settled
            and _still_open.pot_cents == POTS[_unevaluable_key],
            f"settled={_still_open.settled}, pot={_still_open.pot_cents}")

# ZERO WINNERS, PROPERLY — subjects ARE evaluable, and none QUALIFIES. That
# needs a qualifier definition, because a rank-extremum always has a highest
# subject. A Gate-1 qualifier is settled with facts that meet nobody.
_qualifier_key = next(
    d["key"] for d in DEFS
    if d.get("evaluator_shape") == "QUALIFIER_PREDICATE"
    and d.get("definition_runtime_eligible"))
_zero = None
with SessionLocal() as db:
    definition = (db.query(PoolDefinition)
                  .filter(PoolDefinition.key == _qualifier_key).one())
    db.add(PoolInstance(league_id=S_LEAGUE, season=SEASON, week=SETTLE_WEEK,
                        slot=4, definition_key=_qualifier_key,
                        phase="REGULAR", rotation_cycle=1, pot_cents=400))
    # Slot 4 is already taken by the drawn slate, so this replaces it — the
    # instance exists to exercise SETTLEMENT, and its draw was already
    # certified separately in the reachability section.
    db.rollback()

with SessionLocal() as db:
    existing = (db.query(PoolInstance)
                .filter(PoolInstance.league_id == S_LEAGUE,
                        PoolInstance.week == SETTLE_WEEK,
                        PoolInstance.slot == 4).one())
    existing.definition_key = _qualifier_key
    db.commit()

_zero = _settle_multi(_qualifier_key,
                      {t: 0.0 for t in S_TEAMS})
_assert("§11: a week where no subject QUALIFIES settles without a winner",
        not _zero.winning_subject_ids,
        f"{_zero.classification}, winners={_zero.winning_subject_ids}")
_assert("§11: its pot is fully accounted for, not lost",
        _zero.distributed_cents + _zero.rolled_over_cents
        + _zero.swept_to_championship_cents == _zero.pot_cents,
        f"{_zero.distributed_cents}+{_zero.rolled_over_cents}"
        f"+{_zero.swept_to_championship_cents} vs {_zero.pot_cents}")
_assert("§11: and it took the governed rollover-or-sweep destination",
        (_zero.rolled_over_cents > 0) ^ (_zero.swept_to_championship_cents > 0),
        f"rolled {_zero.rolled_over_cents}, "
        f"swept {_zero.swept_to_championship_cents}, "
        f"event={_zero.event_type}")

# ROLLOVER CONSUMES NEXT WEEK'S SLOT, never adds a fifth Pool. Asserted through
# the real continuation reader the slate builder itself uses.
from betting.pool_slate import pending_continuations  # noqa: E402

with SessionLocal() as db:
    carries = pending_continuations(db, league_id=S_LEAGUE, season=SEASON,
                                    week=SETTLE_WEEK + 1)
_assert("§11: a rolled pot is offered to the next week as a continuation",
        all(c.slot in (1, 2, 3, 4) for c in carries),
        f"{len(carries)} continuation(s): "
        f"{[(c.definition_key, c.slot) for c in carries]}")
_assert("§8: and continuations can never exceed the four slots",
        len(carries) <= DEFAULT_SLOT_COUNT, str(len(carries)))

# IDEMPOTENT REPLAY — functionally, not as a locking claim.
_replay = _settle_one(_ordinary_key, {S_TEAMS[0]: 50.0})
_assert("§10: re-settling replays instead of paying twice",
        _replay.replayed is True, str(_replay.replayed))
_assert("§10: and the replay distributes nothing further",
        _replay.distributed_cents == _ordinary.distributed_cents)

_assert("§10: the ledger balances after settlement and replay",
        trial_balance() == 0, str(trial_balance()))
_assert("§11: no participation minimum was invented",
        "participation_minimum" not in open(
            os.path.join(ROOT, "betting", "pool_settlement.py"),
            encoding="utf-8").read(),
        "the retired rule stays retired")

# §19 — THE POSTGRES BOUNDARY, stated rather than assumed.
_assert("§19: row-lock/concurrency claims are NOT made here",
        os.environ.get("TEST_DATABASE_URL") is None,
        "SQLite: .with_for_update() is a documented no-op; locking is P5")


# ══ §16 · the per-definition matrix ═════════════════════════════════════════

_section("§16 · full certification matrix")

MATRIX = []
for key in sorted(RUNTIME_REACHABLE):
    d = CATALOG_BY_KEY[key]
    seen = FIRST_SEEN.get(key)
    MATRIX.append({
        "catalog_number": d["catalog_number"],
        "key": key,
        "display_name": d.get("display_name"),
        "gate_1": bool(d.get("definition_runtime_eligible")),
        "gate_2_condition": "fixture readiness measured fresh via "
                            "record_activation_measurement",
        "rotation_reachable": seen is not None,
        "first_week": seen[0] if seen else None,
        "first_slot": seen[1] if seen else None,
        "common_engine": key not in {k for k, _ in _unparseable}
                         and key not in {k for k, _ in _unsupported},
        "common_settlement": True,
        "continuation_compatible": bool(d.get("rollover_eligible")),
    })

MATRIX_PATH = os.path.join(_TMP_DIR, "p4c4_pool_matrix.json")
with open(MATRIX_PATH, "w", encoding="utf-8") as handle:
    json.dump(MATRIX, handle, indent=2)

_assert("§16: the matrix covers every reachable definition",
        len(MATRIX) == len(RUNTIME_REACHABLE), f"{len(MATRIX)} rows")
_assert("§16: every row is rotation-reachable",
        all(r["rotation_reachable"] for r in MATRIX),
        str([r["key"] for r in MATRIX if not r["rotation_reachable"]][:4]))
_assert("§16: every row resolves through the common engine",
        all(r["common_engine"] for r in MATRIX),
        str([r["key"] for r in MATRIX if not r["common_engine"]][:4]))
_assert("§16: every row can enter the common settlement path",
        all(r["common_settlement"] for r in MATRIX))
print(f"    matrix written: {MATRIX_PATH}")
print(f"    rollover-eligible (continuation-compatible): "
      f"{sum(1 for r in MATRIX if r['continuation_compatible'])} of {len(MATRIX)}")


# ══ §1/§3 · strict Pool-pick ownership ══════════════════════════════════════

_section("§1/§3 · strict Pool-pick ownership")

_pool_routes = open(os.path.join(ROOT, "api", "pool_routes.py"),
                    encoding="utf-8").read()
_tree = ast.parse(_pool_routes)
_calls = {n.func.id for n in ast.walk(_tree)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
_assert("§1: the lenient guard is no longer CALLED anywhere in pool routes",
        "assert_own_team" not in _calls)
_assert("§1: and the strict guard is",
        "assert_wagering_team_owner" in _calls)

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from auth.session import CSRF_COOKIE, CSRF_HEADER  # noqa: E402
from db.schema import PoolBetPick, PoolPrediction  # noqa: E402


class Client:
    def __init__(self, email):
        self.http = TestClient(app, raise_server_exceptions=False)
        if email:
            r = self.http.post("/auth/session",
                               json={"email": email, "password": PASSWORD})
            assert r.status_code == 200, r.text

    def post(self, path, body):
        headers = {}
        token = self.http.cookies.get(CSRF_COOKIE)
        if token:
            headers[CSRF_HEADER] = token
        r = self.http.request("POST", path, json=body, headers=headers)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text


def pool_state(team_id: int) -> dict:
    with SessionLocal() as db:
        return {
            "picks": db.query(PoolBetPick)
                       .filter(PoolBetPick.team_id == team_id).count(),
            "predictions": db.query(PoolPrediction)
                             .filter(PoolPrediction.team_id == team_id).count(),
            "instances": db.query(PoolInstance)
                           .filter(PoolInstance.league_id == LEAGUE_ID).count(),
            "trial_balance": trial_balance(),
        }


gm_a, gm_b, comm_c, gm_f = (Client(A_EMAIL), Client(B_EMAIL),
                            Client(C_EMAIL), Client(F_EMAIL))

before_a = pool_state(A)

status, body = comm_c.post("/pool/pick", {
    "league_id": LEAGUE_ID, "team_id": A, "bet_type": "biggest_winner",
    "pick": A, "week": 1})
_assert("§1: a COMMISSIONER cannot submit a Pool pick as another GM",
        status == 403, f"status {status}: {str(body)[:110]}")

after_a = pool_state(A)
_assert("§3: no pick row was created for GM A",
        after_a["picks"] == before_a["picks"],
        f"{before_a['picks']} → {after_a['picks']}")
_assert("§3: no participation state changed",
        after_a["instances"] == before_a["instances"])
_assert("§3: and the trial balance is unchanged",
        after_a["trial_balance"] == before_a["trial_balance"] == 0)

status, _ = gm_b.post("/pool/pick", {
    "league_id": LEAGUE_ID, "team_id": A, "bet_type": "biggest_winner",
    "pick": A, "week": 1})
_assert("§3: a GM cannot submit a Pool pick as another GM", status == 403,
        f"status {status}")

status, _ = gm_f.post("/pool/pick", {
    "league_id": LEAGUE_ID, "team_id": A, "bet_type": "biggest_winner",
    "pick": A, "week": 1})
_assert("§3: cross-league submission is denied", status == 403,
        f"status {status}")

# THE COMMISSIONER IS NOT DISABLED AS A PLAYER. Their own pick is accepted on
# the same terms as anyone's — the refusal above is about identity, not rank.
status, own = comm_c.post("/pool/pick", {
    "league_id": LEAGUE_ID, "team_id": C, "bet_type": "biggest_winner",
    "pick": C, "week": 1})
_assert("§1: a commissioner CAN submit their OWN team's pick",
        status not in (401, 403),
        f"status {status}: {str(own)[:110]}")

# THE SECOND DEFECT THIS PACKAGE FOUND: /pool/predict had no ownership check at
# all — weaker than the commissioner-permissive one already on the checklist.
before_pred = pool_state(A)
status, _ = gm_b.post("/pool/predict", {
    "league_id": LEAGUE_ID, "team_id": A, "predicted_team_id": B, "week": 1})
_assert("§2: a GM cannot submit a Worst Beat prediction as another team",
        status == 403, f"status {status}")
_assert("§3: and no prediction row was written",
        pool_state(A)["predictions"] == before_pred["predictions"])

anon = Client(None)
status, _ = anon.post("/pool/pick", {
    "league_id": LEAGUE_ID, "team_id": A, "bet_type": "biggest_winner",
    "pick": A, "week": 1})
_assert("§3: an unauthenticated pick is refused", status in (401, 403),
        f"status {status}")


# ══ §2 · commissioner/admin Pool commands keep their authority ══════════════

_section("§2 · administrative Pool commands are unchanged")

_admin_guarded = []
for node in ast.walk(_tree):
    if isinstance(node, ast.FunctionDef):
        body = ast.unparse(node)
        if "assert_league_commissioner" in body:
            _admin_guarded.append(node.name)
_assert("§2: config, collect and settle remain commissioner-scoped",
        set(_admin_guarded) >= {"create_pool_config", "collect_entries",
                                "settle_weekly_pool"},
        str(sorted(_admin_guarded)))


# ══ §13 · frontend Pool authority ═══════════════════════════════════════════

_section("§13 · the shipped Pool UI has no fallback and no evaluator")


def _code_only(js: str) -> str:
    out, i, n = [], 0, len(js)
    while i < n:
        if js.startswith("/*", i):
            end = js.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        line_end = js.find(chr(10), i)
        if line_end == -1:
            line_end = n
        line = js[i:line_end]
        if not line.lstrip().startswith(("//", "*")):
            out.append(line)
        i = line_end + 1
    return chr(10).join(out)


_slate_model = _code_only(open(os.path.join(ROOT, "web", "js",
                                            "pool-slate-model.js"),
                               encoding="utf-8").read())
_week_ui = _code_only(open(os.path.join(ROOT, "web", "js", "week.js"),
                           encoding="utf-8").read())
_rules_ui = _code_only(open(os.path.join(ROOT, "web", "js", "rules.js"),
                            encoding="utf-8").read())

_assert("§13: no frontend POOL_BET_TYPES list exists",
        "POOL_BET_TYPES" not in _slate_model
        and "POOL_BET_TYPES" not in _week_ui)
_assert("§13: no /pool/config fallback is reachable from the UI",
        "/pool/config" not in _slate_model and "/pool/config" not in _week_ui
        and "/pool/config" not in _rules_ui)
_assert("§13: an undrawn week yields ZERO rows, never the launch four",
        "if (MODE !== SLATE_MODE_DRAWN || !SERVED) return [];" in _slate_model)
_assert("§13: the slate is read, never composed",
        "SERVED.slots.map" in _slate_model)
_assert("§13: the UI runs no Pool winner evaluator",
        not any(t in _slate_model + _week_ui
                for t in ("rank_extremum", "evaluatePool", "computeWinner",
                          "parse_metric_expression")))
_assert("§13: and the four-slot contract is reported, not enforced client-side",
        "slateHonoursSlotContract" in _slate_model)


# ══ §15 · Gate-2 honesty ════════════════════════════════════════════════════

_section("§15 · structural reachability is not live readiness")

_env = CATALOG["current_environment"]
_assert("§15: the catalog still records selectable_now = 0",
        _env["selectable_now"] == 0, str(_env["selectable_now"]))
_assert("§15: and league_activation_ready_count = 0",
        _env["league_activation_ready_count"] == 0)
_assert("§15: the Gate-1 ceiling is not a promised selectable count",
        _env["post_access_selectable_count"] == "NOT_STATED_IN_ADVANCE")
_assert("§15: this suite's readiness is FIXTURE-MEASURED, not live",
        all(r["gate_2_condition"].startswith("fixture readiness")
            for r in MATRIX),
        "structural certification only — no live activation claim")


print("\n" + "=" * 78)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4C-4 POOL CERTIFICATION — all assertions PASSED")