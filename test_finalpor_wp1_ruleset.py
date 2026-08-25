#!/usr/bin/env python3
"""FINAL POR · WP-1 certification — the season-level ruleset era gate.

WHAT THIS SUITE PROVES, AND WHY EACH CASE EXISTS:

    R1  absence resolves to the LEGACY ruleset          historical safety
    R2  a stamped season resolves to what was stamped   the gate actually gates
    R3  `is_final_por` is the predicate call sites use  one spelling, one place
    R4  a replay stamping the SAME version is a no-op   idempotency
    R5  a restamp naming a DIFFERENT version REFUSES    no silent era change
    R6  an unknown version REFUSES rather than downgrading
    R7  one row per league-season, enforced by the database
    R8  the table is registered on `Base` metadata      fresh-DB parity

R1 IS THE ONE THAT PROTECTS EVERY HISTORICAL SEASON. If it ever fails, every
pre-WP-1 league-season silently becomes governed by the Final POR — which would
rescore frozen championships and reclassify settled obligations. It is asserted
first and deliberately.

Runs on SQLite in-memory: this package adds no dialect-specific behaviour, and
the same assertions run against PostgreSQL through the shared migration suite.
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.schema import Base, League, LeagueSeasonRuleset
from ruleset import (
    CURRENT_RULESET,
    KNOWN_RULESETS,
    REASON_ALREADY_STAMPED,
    REASON_UNKNOWN_VERSION,
    RULESET_FINAL_POR,
    RULESET_LEGACY,
    RulesetError,
    is_final_por,
    resolve_ruleset_version,
    stamp_ruleset,
)

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
    db = sessionmaker(bind=engine)()
    db.add(League(id=1, name="Test League", season=2026))
    db.add(League(id=2, name="Other League", season=2026))
    db.commit()
    return db


print("\nWP1-R1 · absence is the LEGACY ruleset — historical safety")
db = _session()
_assert("an unstamped league-season resolves to RULESET_LEGACY",
        resolve_ruleset_version(db, league_id=1, season=2026) == RULESET_LEGACY,
        str(resolve_ruleset_version(db, league_id=1, season=2026)))
_assert("an unstamped league-season is NOT governed by the Final POR",
        is_final_por(db, league_id=1, season=2026) is False)
_assert("absence writes nothing — resolving is a pure read",
        db.query(LeagueSeasonRuleset).count() == 0)


print("\nWP1-R2 · a stamped season resolves to what was stamped")
stamp_ruleset(db, league_id=1, season=2026)
db.flush()
_assert("stamping records exactly one row",
        db.query(LeagueSeasonRuleset).count() == 1)
_assert("the stamped season resolves to CURRENT_RULESET",
        resolve_ruleset_version(db, league_id=1, season=2026) == CURRENT_RULESET)
_assert("CURRENT_RULESET is the Final POR in this build",
        CURRENT_RULESET == RULESET_FINAL_POR)


print("\nWP1-R3 · the era predicate")
_assert("a stamped season IS governed by the Final POR",
        is_final_por(db, league_id=1, season=2026) is True)
_assert("a DIFFERENT league is unaffected by league 1's stamp",
        is_final_por(db, league_id=2, season=2026) is False)
_assert("a DIFFERENT season of the SAME league is unaffected",
        is_final_por(db, league_id=1, season=2025) is False)


print("\nWP1-R4 · replay stamping the same version is a no-op")
before = db.query(LeagueSeasonRuleset).count()
row_a = stamp_ruleset(db, league_id=1, season=2026)
row_b = stamp_ruleset(db, league_id=1, season=2026, version=CURRENT_RULESET)
db.flush()
_assert("a replay adds no row",
        db.query(LeagueSeasonRuleset).count() == before,
        f"{before} -> {db.query(LeagueSeasonRuleset).count()}")
_assert("a replay returns the existing row", row_a.id == row_b.id)


print("\nWP1-R5 · a restamp naming a DIFFERENT version refuses")
try:
    stamp_ruleset(db, league_id=1, season=2026, version=RULESET_LEGACY)
    _assert("restamping a different version raises", False, "no exception")
except RulesetError as exc:
    _assert("restamping a different version raises RulesetError", True)
    _assert("the refusal carries REASON_ALREADY_STAMPED",
            exc.reason == REASON_ALREADY_STAMPED, exc.reason)
    _assert("the stored version is unchanged by the refused restamp",
            resolve_ruleset_version(db, league_id=1, season=2026)
            == RULESET_FINAL_POR)


print("\nWP1-R6 · an unknown version refuses rather than silently downgrading")
try:
    stamp_ruleset(db, league_id=2, season=2026, version=999)
    _assert("stamping an unknown version raises", False, "no exception")
except RulesetError as exc:
    _assert("stamping an unknown version raises RulesetError", True)
    _assert("the refusal carries REASON_UNKNOWN_VERSION",
            exc.reason == REASON_UNKNOWN_VERSION, exc.reason)

# A row written by a NEWER build must refuse on READ too, not just on write —
# that is the direction the danger actually comes from.
db.add(LeagueSeasonRuleset(league_id=2, season=2026, ruleset_version=999))
db.flush()
try:
    resolve_ruleset_version(db, league_id=2, season=2026)
    _assert("reading an unknown stamped version raises", False, "no exception")
except RulesetError as exc:
    _assert("reading an unknown stamped version raises RulesetError", True)
    _assert("the read refusal carries REASON_UNKNOWN_VERSION",
            exc.reason == REASON_UNKNOWN_VERSION, exc.reason)
db.rollback()


print("\nWP1-R7 · one row per league-season, enforced by the database")
db2 = _session()
db2.add(LeagueSeasonRuleset(league_id=1, season=2026,
                            ruleset_version=RULESET_FINAL_POR))
db2.add(LeagueSeasonRuleset(league_id=1, season=2026,
                            ruleset_version=RULESET_FINAL_POR))
try:
    db2.commit()
    _assert("a duplicate (league, season) is rejected by the database", False,
            "commit succeeded")
except Exception:
    db2.rollback()
    _assert("a duplicate (league, season) is rejected by the database", True)


print("\nWP1-R8 · fresh-database parity")
_assert("league_season_ruleset is declared on Base metadata",
        "league_season_ruleset" in Base.metadata.tables,
        str(sorted(t for t in Base.metadata.tables if "ruleset" in t)))
_assert("KNOWN_RULESETS covers both eras this build implements",
        KNOWN_RULESETS == {RULESET_LEGACY, RULESET_FINAL_POR},
        str(sorted(KNOWN_RULESETS)))
_assert("the migration manifest registers the ruleset table",
        any(m.identifier == "0010_season_ruleset"
            and "league_season_ruleset" in m.tables
            for m in __import__("migrations.manifest",
                                fromlist=["ACTIVE"]).ACTIVE))


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-1 ruleset era gate: all assertions passed")
