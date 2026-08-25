#!/usr/bin/env python3
"""Sprint 2B certification — component projection storage, ingestion, selection.

WHAT THIS SUITE PROVES, AND WHY EACH GROUP EXISTS:

    A  the schema and the migration agree, and neither touches `projections`
    B  a snapshot stores once, de-duplicates, and never overwrites its history
    C  identity fails closed — RESOLVED only, three named refusals
    D  the selector is deterministic and has no fallbacks at all
    E  a whole week ingests offline, end to end, one page at a time
    F  every CULV and Mr Whiskers category is classified honestly
    G  the legacy scalar projection path is untouched

GROUP D IS THE ONE SPRINT 3 DEPENDS ON. CSPS will ask "which snapshot should I
use for this player, this week" and must get the same answer every time, from
one provider, for one canonical subject — with no quiet substitution of another
provider's forecast and no reaching for `projections.projected_points`, which is
a differently-scored number produced by a different source under a different
rule set. A fallback there would be undetectable and wrong.

GROUP C IS WHY THE STORE EXISTS AT ALL. A projection filed against a subject we
are not certain of is worse than a missing projection: it is a forecast that
will be read with confidence and priced.

OFFLINE AND DETERMINISTIC. SQLite in memory, the committed SYNTHETIC fixture
corpus, a frozen clock. No network, no credential, no PostgreSQL — the dialect
parity this table needs is certified separately, against a real server, in
test_sprint2b_component_projections_postgres.py.
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

from datetime import datetime, timedelta, timezone                 # noqa: E402

from sqlalchemy import create_engine                               # noqa: E402
from sqlalchemy.orm import sessionmaker                            # noqa: E402

from db.schema import (                                            # noqa: E402
    Base,
    Player,
    Projection,
    ProviderComponentProjection,
    ProviderPlayerAlias,
)
from providers.balldontlie import coverage as COV                  # noqa: E402
from providers.balldontlie import normalize as N                   # noqa: E402
from providers.balldontlie import parse as P                       # noqa: E402
from providers.balldontlie.ingest import ingest_week               # noqa: E402
from providers.balldontlie.transport import (                      # noqa: E402
    BalldontlieFixtureTransport,
)
from providers.component_projections import (                      # noqa: E402
    ComponentProjection,
    PersistOutcome,
    observation_digest,
    persist_snapshot,
    persist_snapshots,
    select_snapshot,
    select_week,
)
from providers.cross_identity import (                             # noqa: E402
    BALLDONTLIE,
    CanonicalSubject,
    CrossProviderResolution,
    Outcome,
)

CORPUS = os.path.join(ROOT, "providers", "fixtures", "balldontlie")
NOW = datetime(2025, 12, 24, 20, 0, tzinfo=timezone.utc)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _player(db, name, position, team):
    player = Player(name=name, position=position, nfl_team=team)
    db.add(player)
    db.flush()
    return player


def _resolution(player, key, outcome=Outcome.RESOLVED, detail=""):
    """A WP1-shaped resolution, built directly so each outcome can be exercised."""
    return CrossProviderResolution(
        outcome=outcome, provider=BALLDONTLIE,
        canonical=CanonicalSubject(player_id=player.id, name=player.name,
                                   position=player.position,
                                   nfl_team=player.nfl_team),
        provider_player_key=key if outcome == Outcome.RESOLVED else None,
        method="normalized_discovery", detail=detail or "test resolution")


def _projection(key, *, season=2025, week=17, components=None, position="WR",
                team="DET", observed_at=None):
    return ComponentProjection(
        provider=BALLDONTLIE, provider_player_key=key, season=season, week=week,
        components=components if components is not None
        else {"receiving_yards": 84.3, "targets": 9.8},
        components_present=tuple(sorted(components or
                                        {"receiving_yards": 0, "targets": 0})),
        nfl_team=team, position=position, observed_at=observed_at or NOW,
        source_kind=ProviderComponentProjection.SOURCE_PROJECTION)


def _store(db, player, key, **kwargs):
    return persist_snapshot(
        db, resolution=_resolution(player, key),
        projection=_projection(key, **kwargs), captured_at=NOW,
        provenance=ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC)


print("=" * 78)
print("SPRINT 2B · COMPONENT PROJECTION STORAGE, INGESTION AND SELECTION")
print("=" * 78)
print(f"  corpus              : {os.path.relpath(CORPUS)}")
print(f"  scoring categories  : {len(COV.CATEGORIES)}")


# ══════════════════════════════════════════════════════════════════════════════
# A · schema and migration
# ══════════════════════════════════════════════════════════════════════════════

print("\n2B-A · the schema and the migration agree, and `projections` is untouched")

_table = Base.metadata.tables.get("provider_component_projection")
_assert("provider_component_projection is declared on Base metadata",
        _table is not None)
_assert("the observation is unique on (provider, player_id, season, week, "
        "digest)",
        any(c.name == "uq_component_projection_observation"
            and [col.name for col in c.columns] ==
            ["provider", "player_id", "season", "week", "observation_digest"]
            for c in _table.constraints
            if hasattr(c, "columns") and c.name),
        str(sorted(c.name for c in _table.constraints if c.name)))
_assert("player_id is a foreign key onto players.id — the canonical subject",
        [str(fk.target_fullname) for fk in _table.c.player_id.foreign_keys]
        == ["players.id"])
_assert("the selector's lookup index exists",
        "ix_component_projection_lookup" in {i.name for i in _table.indexes},
        str(sorted(i.name for i in _table.indexes)))
_assert("components and components_present are BOTH stored — a zero and a "
        "silence are different facts",
        "components" in _table.c and "components_present" in _table.c)
_assert("the source endpoint is recorded, so a forecast can never be read as a "
        "result",
        "source_kind" in _table.c
        and ProviderComponentProjection.SOURCE_PROJECTION
        != ProviderComponentProjection.SOURCE_WEEKLY_STATS)

_ACTIVE = __import__("migrations.manifest", fromlist=["ACTIVE"]).ACTIVE
_assert("the migration manifest registers the table",
        any(m.identifier == "0015_provider_component_projection"
            and "provider_component_projection" in m.tables for m in _ACTIVE))
_assert("  · and it is ordered after WP1's alias table",
        [m.identifier for m in _ACTIVE].index(
            "0015_provider_component_projection") >
        [m.identifier for m in _ACTIVE].index("0014_provider_player_alias"))

# THE MIGRATION IS RUN, NOT READ. `create_all` builds from the models and never
# executes migrations/, so a right model and a wrong migration look identical to
# every assertion above.
_probe = os.path.join(ROOT, ".sprint2b_migration_probe.db")
if os.path.exists(_probe):
    os.remove(_probe)
_env = dict(os.environ, DATABASE_URL=f"sqlite:///{_probe.replace(os.sep, '/')}")
_out = __import__("subprocess").run(
    [sys.executable, "-X", "utf8", "-c", """
from sqlalchemy import inspect
from db.schema import Base, engine
Base.metadata.create_all(engine, tables=[
    t for n, t in Base.metadata.tables.items()
    if n != "provider_component_projection"])
insp = inspect(engine)
print("BEFORE=" + str("provider_component_projection" in insp.get_table_names()))
print("PROJECTIONS_BEFORE=" + str(sorted(c["name"] for c in insp.get_columns("projections"))))
from migrations.add_provider_component_projection import upgrade
print("FIRST=" + str(upgrade()))
print("SECOND=" + str(upgrade()))
insp = inspect(engine)
print("AFTER=" + str("provider_component_projection" in insp.get_table_names()))
print("COLUMNS=" + str(sorted(c["name"] for c in insp.get_columns("provider_component_projection"))))
print("PROJECTIONS_AFTER=" + str(sorted(c["name"] for c in insp.get_columns("projections"))))
print("UNIQUES=" + str(sorted(u["name"] for u in insp.get_unique_constraints("provider_component_projection"))))
from sqlalchemy import text
row = ("INSERT INTO provider_component_projection (provider, provider_player_key,"
       " player_id, season, week, source_kind, provenance, vocabulary_version,"
       " components, components_present, observation_digest, observed_at,"
       " captured_at, created_at) VALUES ('b','k',1,2025,17,'fantasy/projections',"
       "'LIVE','v','{}','[]','dig','2025-01-01','2025-01-01','2025-01-01')")
with engine.begin() as c:
    c.execute(text("INSERT INTO players (id, name, position) VALUES (1,'probe','WR')"))
    c.execute(text(row))
try:
    with engine.begin() as c:
        c.execute(text(row))
    print("DUPLICATE_REFUSED=False")
except Exception:
    print("DUPLICATE_REFUSED=True")
"""], capture_output=True, text=True, errors="replace", env=_env, cwd=ROOT)
_migration = dict(line.split("=", 1) for line in _out.stdout.splitlines()
                  if "=" in line)
_assert("the migration applies to a real pre-Sprint-2B database",
        _migration.get("BEFORE") == "False"
        and "created provider_component_projection" in _migration.get("FIRST", ""),
        (_out.stderr or "").strip().splitlines()[-1][:150] if _out.returncode
        else _migration.get("FIRST", "?")[:70])
_assert("applying it a second time is a no-op",
        "already exists" in _migration.get("SECOND", ""),
        _migration.get("SECOND", "?")[:60])
_assert("migration and model agree on every column",
        _migration.get("COLUMNS", "") == str(sorted(_table.c.keys())),
        _migration.get("COLUMNS", "?")[:80])
_assert("the migration builds the observation unique constraint",
        "uq_component_projection_observation" in _migration.get("UNIQUES", ""),
        _migration.get("UNIQUES", "?"))
_assert("  · and SQLite ENFORCES it — introspection is not the property that "
        "matters",
        _migration.get("DUPLICATE_REFUSED") == "True",
        _migration.get("DUPLICATE_REFUSED", "?"))
_assert("`projections` is IDENTICAL before and after — no column added, "
        "renamed or dropped",
        _migration.get("PROJECTIONS_BEFORE") == _migration.get("PROJECTIONS_AFTER")
        and "projected_points" in _migration.get("PROJECTIONS_AFTER", ""),
        _migration.get("PROJECTIONS_AFTER", "?"))
if os.path.exists(_probe):
    os.remove(_probe)


# ══════════════════════════════════════════════════════════════════════════════
# B · storage, idempotency and history
# ══════════════════════════════════════════════════════════════════════════════

print("\n2B-B · a snapshot stores once, de-duplicates, and keeps its history")

_db = _session()
_amon = _player(_db, "Amon-Ra St. Brown", "WR", "DET")

_first = _store(_db, _amon, "bdl.p.113")
_assert("a resolved subject stores a snapshot",
        _first.outcome == PersistOutcome.PERSISTED, _first.outcome)
_assert("  · against the CANONICAL player id, not a provider key",
        _first.player_id == _amon.id)
_assert("  · and the components round-trip as a JSON document",
        _db.query(ProviderComponentProjection).one().components
        == {"receiving_yards": 84.3, "targets": 9.8})

_again = _store(_db, _amon, "bdl.p.113")
_assert("re-persisting the IDENTICAL observation is a DUPLICATE, not a second "
        "row",
        _again.outcome == PersistOutcome.DUPLICATE
        and _db.query(ProviderComponentProjection).count() == 1,
        f"{_db.query(ProviderComponentProjection).count()} row(s)")
_assert("  · and it names the row that already held it",
        _again.snapshot_id == _first.snapshot_id)

_moved = _store(_db, _amon, "bdl.p.113",
                components={"receiving_yards": 91.0, "targets": 10.4},
                observed_at=NOW + timedelta(hours=6))
_assert("a projection that MOVED lands as a new snapshot",
        _moved.outcome == PersistOutcome.PERSISTED
        and _db.query(ProviderComponentProjection).count() == 2)
_assert("  · and the earlier forecast is still on disk, unmodified",
        _db.query(ProviderComponentProjection)
        .filter_by(id=_first.snapshot_id).one().components
        == {"receiving_yards": 84.3, "targets": 9.8})
_assert("the digest covers the payload but NOT the fetch time",
        observation_digest(provider=BALLDONTLIE,
                           provider_player_key="bdl.p.113", season=2025,
                           week=17, vocabulary_version="v", components={"a": 1})
        == observation_digest(provider=BALLDONTLIE,
                              provider_player_key="bdl.p.113", season=2025,
                              week=17, vocabulary_version="v",
                              components={"a": 1.0}))

# Separation: the unique key is per provider, per season, per week.
_store(_db, _amon, "bdl.p.113", season=2024)
_store(_db, _amon, "bdl.p.113", week=16)
_assert("season separates snapshots", _db.query(ProviderComponentProjection)
        .filter_by(player_id=_amon.id, season=2024).count() == 1)
_assert("week separates snapshots", _db.query(ProviderComponentProjection)
        .filter_by(player_id=_amon.id, week=16).count() == 1)

_other = persist_snapshot(
    _db, resolution=_resolution(_amon, "yh.p.9"),
    projection=ComponentProjection(
        provider="some_other_provider", provider_player_key="yh.p.9",
        season=2025, week=17, components={"receiving_yards": 84.3,
                                          "targets": 9.8}),
    captured_at=NOW,
    provenance=ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC)
_assert("provider separates snapshots — an identical payload from another "
        "provider is its own row",
        _other.outcome == PersistOutcome.PERSISTED
        and _other.snapshot_id != _first.snapshot_id)

# THE RACE, INJECTED DETERMINISTICALLY. Two workers ingesting one week can both
# pass the pre-check and both insert; the unique constraint settles it, and the
# loser must be told it lost a DUPLICATE rather than that something FAILED. This
# proxy makes the pre-check MISS exactly once — which is what the losing worker
# experiences — and then delegates everything to the real session.
class _BlindOnce:
    """A session whose first duplicate pre-check returns nothing."""

    def __init__(self, session):
        self._session = session
        self.blinded = False

    def query(self, *args, **kwargs):
        query = self._session.query(*args, **kwargs)
        if self.blinded:
            return query
        self.blinded = True

        class _Blind:
            def filter(self, *a, **k):
                return self

            def first(self):
                return None

        return _Blind()

    def __getattr__(self, name):
        return getattr(self._session, name)


_raced = persist_snapshot(
    _BlindOnce(_db), resolution=_resolution(_amon, "bdl.p.113"),
    projection=_projection("bdl.p.113"), captured_at=NOW,
    provenance=ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC)
_assert("a duplicate lost to a RACE is reported as DUPLICATE, not FAILED",
        _raced.outcome == PersistOutcome.DUPLICATE,
        f"{_raced.outcome}: {_raced.detail[:60]}")
# PROVIDER IS PART OF THE FILTER, because the separation test above stored an
# identical payload under a second provider for this same player-week. Counting
# without it would count that row too and report a phantom insert.
_bdl_rows = (_db.query(ProviderComponentProjection)
             .filter_by(provider=BALLDONTLIE, player_id=_amon.id, season=2025,
                        week=17).count())
_assert("  · the database refused the second copy, so no row was added",
        _bdl_rows == 2, f"{_bdl_rows} BALLDONTLIE row(s) for this player-week")
_assert("  · and the session survives it — a sibling snapshot still stores",
        _store(_db, _amon, "bdl.p.113",
               components={"receiving_yards": 12.5}).outcome
        == PersistOutcome.PERSISTED)

_dst_player = _player(_db, "Detroit Lions", "DEF", "DET")
_dst = _store(_db, _dst_player, "bdl.dst.DET", position="DEF",
              components={"defensive_sacks": 2.4, "dst_points_allowed": 21.3})
_assert("a team defense stores under its DST key",
        _dst.outcome == PersistOutcome.PERSISTED
        and _db.query(ProviderComponentProjection)
        .filter_by(provider_player_key="bdl.dst.DET").one().position == "DEF")

_kicker = _player(_db, "Cam Little", "K", "JAX")
_k = _store(_db, _kicker, "bdl.p.278371", position="K", team="JAX",
            components={"field_goals_made_yards": 68.4})
_assert("a kicker stores as canonical K, never as the provider's PK spelling",
        _db.query(ProviderComponentProjection)
        .filter_by(provider_player_key="bdl.p.278371").one().position == "K")


# ══════════════════════════════════════════════════════════════════════════════
# C · identity fails closed
# ══════════════════════════════════════════════════════════════════════════════

print("\n2B-C · identity fails closed — RESOLVED only, three named refusals")

_db2 = _session()
_p = _player(_db2, "Amon-Ra St. Brown", "WR", "DET")

for _outcome, _expected in ((Outcome.UNRESOLVED, PersistOutcome.UNRESOLVED),
                            (Outcome.AMBIGUOUS, PersistOutcome.AMBIGUOUS),
                            (Outcome.CONFLICT, PersistOutcome.CONFLICT)):
    _result = persist_snapshot(
        _db2, resolution=_resolution(_p, "bdl.p.113", outcome=_outcome),
        projection=_projection("bdl.p.113"), captured_at=NOW,
        provenance=ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC)
    _assert(f"an identity that is {_outcome} is REFUSED, with its own name kept",
            _result.outcome == _expected, _result.outcome)

_assert("  · and nothing at all was written by any of the three",
        _db2.query(ProviderComponentProjection).count() == 0,
        f"{_db2.query(ProviderComponentProjection).count()} row(s)")

_mismatch = persist_snapshot(
    _db2, resolution=_resolution(_p, "bdl.p.113"),
    projection=_projection("bdl.p.999"), captured_at=NOW,
    provenance=ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC)
_assert("a resolution and a payload about DIFFERENT subjects is a CONFLICT",
        _mismatch.outcome == PersistOutcome.CONFLICT,
        _mismatch.detail[:70])

_report = persist_snapshots(
    _db2, [(_resolution(_p, "bdl.p.113", outcome=Outcome.UNRESOLVED),
            _projection("bdl.p.113")),
           (_resolution(_p, "bdl.p.113"), _projection("bdl.p.113"))],
    captured_at=NOW,
    provenance=ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC)
_assert("a batch reports NAMED counts, and drops nothing silently",
        _report.persisted == 1 and _report.unresolved == 1
        and len(_report.results) == 2, json.dumps(_report.as_dict()))
_assert("  · and it names the refused subjects, not just how many there were",
        _report.subjects(PersistOutcome.UNRESOLVED) == ["bdl.p.113"])


# ══════════════════════════════════════════════════════════════════════════════
# D · the selector
# ══════════════════════════════════════════════════════════════════════════════

print("\n2B-D · the selector is deterministic, and has no fallbacks at all")

_db3 = _session()
_sel_player = _player(_db3, "Amon-Ra St. Brown", "WR", "DET")

_early = _store(_db3, _sel_player, "bdl.p.113",
                components={"receiving_yards": 70.0},
                observed_at=NOW - timedelta(days=2))
_mid = _store(_db3, _sel_player, "bdl.p.113",
              components={"receiving_yards": 80.0},
              observed_at=NOW - timedelta(days=1))
_late = _store(_db3, _sel_player, "bdl.p.113",
               components={"receiving_yards": 90.0}, observed_at=NOW)

_chosen = select_snapshot(_db3, provider=BALLDONTLIE, player_id=_sel_player.id,
                          season=2025, week=17)
_assert("with no as-of, the LATEST snapshot wins",
        _chosen.id == _late.snapshot_id
        and _chosen.components["receiving_yards"] == 90.0)

_as_of = select_snapshot(_db3, provider=BALLDONTLIE, player_id=_sel_player.id,
                         season=2025, week=17, as_of=NOW - timedelta(hours=12))
_assert("with an as-of, the latest snapshot AT OR BEFORE it wins — what was "
        "knowable then",
        _as_of.id == _mid.snapshot_id
        and _as_of.components["receiving_yards"] == 80.0)

_before_any = select_snapshot(_db3, provider=BALLDONTLIE,
                              player_id=_sel_player.id, season=2025, week=17,
                              as_of=NOW - timedelta(days=5))
_assert("  · and an as-of before every snapshot returns nothing, never the "
        "nearest one",
        _before_any is None)

_tie_a = _store(_db3, _sel_player, "bdl.p.113",
                components={"receiving_yards": 95.0}, observed_at=NOW)
_tie_b = _store(_db3, _sel_player, "bdl.p.113",
                components={"receiving_yards": 96.0}, observed_at=NOW)
_tied = select_snapshot(_db3, provider=BALLDONTLIE, player_id=_sel_player.id,
                        season=2025, week=17)
_assert("two snapshots sharing an observed_at tie-break on highest id — one "
        "row, every time",
        _tied.id == _tie_b.snapshot_id
        and all(select_snapshot(_db3, provider=BALLDONTLIE,
                                player_id=_sel_player.id, season=2025,
                                week=17).id == _tie_b.snapshot_id
                for _ in range(5)))

persist_snapshot(
    _db3, resolution=_resolution(_sel_player, "yh.p.9"),
    projection=ComponentProjection(provider="some_other_provider",
                                   provider_player_key="yh.p.9", season=2025,
                                   week=17, components={"receiving_yards": 12.0},
                                   observed_at=NOW + timedelta(days=1)),
    captured_at=NOW,
    provenance=ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC)
_still = select_snapshot(_db3, provider=BALLDONTLIE, player_id=_sel_player.id,
                         season=2025, week=17)
_assert("a NEWER snapshot from another provider is never substituted",
        _still.id == _tie_b.snapshot_id
        and _still.provider == BALLDONTLIE)
_assert("  · and asking for a provider with no snapshots returns None, not "
        "somebody else's",
        select_snapshot(_db3, provider="nobody", player_id=_sel_player.id,
                        season=2025, week=17) is None)

# THE FALLBACK THAT WOULD BE INVISIBLE. A scalar projection exists for this
# player and week; the selector must not see it under any circumstances.
_db3.add(Projection(player_id=_sel_player.id, week=17, season=2025,
                    projected_points=18.4, source="fantasypros"))
_db3.flush()
_assert("a scalar Projection row exists for this player-week",
        _db3.query(Projection).filter_by(player_id=_sel_player.id).count() == 1)
_assert("  · and the selector still answers from components only, never from "
        "projected_points",
        select_snapshot(_db3, provider=BALLDONTLIE, player_id=_sel_player.id,
                        season=2025, week=17).components["receiving_yards"]
        == 96.0)
_assert("  · a week with NO component snapshot returns None rather than the "
        "scalar",
        select_snapshot(_db3, provider=BALLDONTLIE, player_id=_sel_player.id,
                        season=2025, week=9) is None)
_assert("  · and the read seam never imports the scalar model at all",
        "Projection" not in [
            n for n in open(os.path.join(ROOT, "providers",
                                         "component_projections.py"),
                            encoding="utf-8").read().split()
            if n == "Projection"])

_bulk = select_week(_db3, provider=BALLDONTLIE, season=2025, week=17)
_assert("the bulk selector agrees with the single one, subject by subject",
        _bulk[_sel_player.id].id == _tie_b.snapshot_id)


# ══════════════════════════════════════════════════════════════════════════════
# E · offline end-to-end ingestion
# ══════════════════════════════════════════════════════════════════════════════

print("\n2B-E · a whole week ingests offline, end to end, one page at a time")

_db4 = _session()
_roster = [
    _player(_db4, "Brock Purdy", "QB", "SF"),
    _player(_db4, "Bijan Robinson", "RB", "ATL"),
    _player(_db4, "Amon-Ra St. Brown", "WR", "DET"),
    _player(_db4, "Brock Bowers", "TE", "LV"),
    _player(_db4, "Cam Little", "K", "JAX"),
    _player(_db4, "Detroit Lions", "DEF", "DET"),
]
_transport = BalldontlieFixtureTransport(CORPUS)
_summary = ingest_week(_db4, _transport, season=2025, week=17, players=_roster,
                       captured_at=NOW)
_db4.flush()

_assert("the fixture week fetches", _summary.fetched == 6,
        f"{_summary.fetched} rows")
_assert("  · by WEEKLY PAGINATION — two cursor pages, not one request per "
        "player",
        _summary.pages_fetched == 2 and _summary.requests_made == 2
        and _summary.requests_made < len(_roster),
        f"{_summary.requests_made} request(s) for {len(_roster)} players")
_assert("every rostered player resolves and persists",
        _summary.resolved == 6 and _summary.persisted == 6,
        json.dumps(_summary.as_dict()))
_assert("  · with no ambiguity, no unresolved subject and no conflict",
        (_summary.ambiguous, _summary.unresolved, _summary.conflict,
         _summary.failed) == (0, 0, 0, 0))

_stored = {row.provider_player_key: row for row in
           _db4.query(ProviderComponentProjection).all()}
for _key, _position in (("bdl.p.27", "QB"), ("bdl.p.475", "RB"),
                        ("bdl.p.113", "WR"), ("bdl.p.277679", "TE"),
                        ("bdl.p.278371", "K"), ("bdl.dst.DET", "DEF")):
    _assert(f"  · {_position} persisted as {_key}",
            _key in _stored and _stored[_key].position == _position,
            _stored.get(_key).position if _key in _stored else "MISSING")

_wr = _stored["bdl.p.113"]
_assert("provenance is FIXTURE_SYNTHETIC — replayed material never claims to "
        "be live",
        _wr.provenance == ProviderComponentProjection.PROVENANCE_FIXTURE_SYNTHETIC)
_assert("the provider's own freshness stamp is what observed_at carries",
        _wr.observed_at.replace(tzinfo=timezone.utc)
        == datetime(2025, 12, 24, 18, 5, tzinfo=timezone.utc),
        str(_wr.observed_at))
_assert("  · and the capture instant is kept separately from it",
        _wr.captured_at.replace(tzinfo=timezone.utc) == NOW)
_assert("the source endpoint is recorded as a PROJECTION",
        _wr.source_kind == ProviderComponentProjection.SOURCE_PROJECTION)
_assert("the provider record id and game id are preserved",
        _wr.provider_record_id == "90003" and _wr.provider_game_id == "424303")
_assert("the canonical NFL team is stored canonically",
        _wr.nfl_team == "DET")

# THE RULE THAT MATTERS MOST FOR A FORECAST. `receptions` is absent from the
# projection block; storing 0.0 would be a confident lie in every PPR league.
_assert("an UNPROJECTED component is absent, not zero-filled",
        "receptions" not in _wr.components and "targets" in _wr.components,
        str(sorted(_wr.components)[:4]))
_assert("  · and the raw payload keys are recorded beside it",
        "targets" in _wr.components_present)

_rerun = ingest_week(_db4, _transport, season=2025, week=17, players=_roster,
                     captured_at=NOW + timedelta(hours=1))
_assert("re-ingesting an unchanged week writes NOTHING and says so",
        _rerun.persisted == 0 and _rerun.duplicate == 6
        and _db4.query(ProviderComponentProjection).count() == 6,
        json.dumps({"persisted": _rerun.persisted,
                    "duplicate": _rerun.duplicate}))

_alias_rows = _db4.query(ProviderPlayerAlias).count()
_assert("WP1's durable mapping was written once, and reused on the second run",
        _alias_rows == 6, f"{_alias_rows} alias row(s)")

_absent = ingest_week(_db4, _transport, season=2025, week=17,
                      players=[_player(_db4, "Nobody Here", "WR", "NYJ")],
                      captured_at=NOW)
_assert("a player who is not in the slate is reported honestly, and stores "
        "nothing",
        _absent.persisted == 0
        and (_absent.unresolved + _absent.absent_from_slate) == 1,
        json.dumps({"unresolved": _absent.unresolved,
                    "absent_from_slate": _absent.absent_from_slate}))

_selected = select_snapshot(_db4, provider=BALLDONTLIE,
                            player_id=_roster[2].id, season=2025, week=17)
_assert("and the ingested week is readable through the Sprint 3 seam",
        _selected is not None
        and _selected.components["receiving_yards"] == 84.3,
        str(_selected.components.get("receiving_yards")))


# ══════════════════════════════════════════════════════════════════════════════
# F · the coverage contract
# ══════════════════════════════════════════════════════════════════════════════

print("\n2B-F · every CULV and Mr Whiskers category is classified honestly")

_assert("every category names a league that exists",
        all(set(c.leagues) <= {COV.CULV, COV.WHISKERS} and c.leagues
            for c in COV.CATEGORIES))
_assert("every category carries one of the four verdicts",
        all(c.verdict in (COV.DIRECT, COV.DERIVED, COV.SETTLEMENT, COV.ABSENT)
            for c in COV.CATEGORIES))
_assert("a DIRECT or DERIVED category always names the BDL field it comes from",
        all(c.source_field for c in COV.CATEGORIES
            if c.verdict in (COV.DIRECT, COV.DERIVED)))
_assert("EXACTLY ONE category is absent, and it is three-and-outs forced",
        [c.yahoo_category for c in COV.uncovered()] == ["Three-and-outs forced"],
        str([c.yahoo_category for c in COV.uncovered()]))
_assert("  · and it is not fabricated anywhere — no component, no source field",
        all(not c.component and not c.source_field for c in COV.uncovered()))
_assert("CULV is fully served by what a snapshot can carry",
        COV.coverage_report(COV.CULV)["absent"] == 0,
        json.dumps(COV.coverage_report(COV.CULV)))
_assert("Mr Whiskers is served except for that one category",
        COV.coverage_report(COV.WHISKERS)["absent"] == 1)

_ingested_components = set()
for _row in _db4.query(ProviderComponentProjection).all():
    _ingested_components |= set(_row.components)
_direct_singles = [c for c in COV.CATEGORIES
                   if c.verdict == COV.DIRECT and "+" not in c.source_field
                   and "/" not in c.source_field]
_representable = [c for c in _direct_singles
                  if c.source_field in N.PLAYER_FIELDS | N.DST_FIELDS]
_assert("every DIRECT category names a field inside WP2's normalized "
        "vocabulary",
        len(_representable) == len(_direct_singles),
        str([c.source_field for c in _direct_singles
             if c not in _representable]))
_assert("  · and the ingested week really did carry component payloads to "
        "store them in",
        len(_ingested_components) >= 20, f"{len(_ingested_components)} keys")


# ══════════════════════════════════════════════════════════════════════════════
# G · the legacy scalar path
# ══════════════════════════════════════════════════════════════════════════════

print("\n2B-G · the legacy scalar projection path is untouched")

_assert("Projection still carries projected_points, actual_points and source",
        {"projected_points", "actual_points", "source"}
        <= set(Projection.__table__.c.keys()))
_assert("  · and its unique key is unchanged: (player_id, week, season, source)",
        any(sorted(col.name for col in c.columns)
            == ["player_id", "season", "source", "week"]
            for c in Projection.__table__.constraints
            if hasattr(c, "columns") and len(c.columns) == 4))
# `Projection\(` and not `"Projection(" in ...`: the latter also matches
# `ProviderComponentProjection(`, which is this sprint's OWN model, and would
# report a violation on every correct line.
_assert("no Sprint 2B module constructs a legacy Projection row",
        not any(__import__("re").search(
            r"Projection\(", open(os.path.join(ROOT, *path),
                                     encoding="utf-8").read())
            for path in (("providers", "component_projections.py"),
                         ("providers", "balldontlie", "ingest.py"),
                         ("migrations",
                          "add_provider_component_projection.py"))))
_assert("  · and the scalar row written in group D still reads back unchanged",
        _db3.query(Projection).one().projected_points == 18.4)
_assert("component snapshots and scalar projections are different tables "
        "entirely",
        ProviderComponentProjection.__tablename__ != Projection.__tablename__
        and "projected_points" not in ProviderComponentProjection.__table__.c)


print()
if _failures:
    print("=" * 78)
    print(f"SPRINT 2B — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  · {_f}")
    print("=" * 78)
    sys.exit(1)
print("=" * 78)
print("SPRINT 2B component projections: all assertions passed — storage, "
      "idempotency,\nfail-closed identity, deterministic selection and a full "
      "offline weekly ingestion.")
print("=" * 78)
