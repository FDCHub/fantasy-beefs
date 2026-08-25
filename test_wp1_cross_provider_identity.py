#!/usr/bin/env python3
"""WP1 certification — canonical Yahoo <-> FantasyStakes <-> BALLDONTLIE identity.

WHAT THIS SUITE PROVES, AND WHY EACH GROUP EXISTS:

    A  name normalization folds SPELLING, never IDENTITY
    B  team and position dialects translate, and refuse what they do not know
    C  discovery is deterministic and fails closed on every ambiguity
    D  the persisted mapping is the identity — names stop being read
    E  the 58 historical week-17 records resolve, exactly and uniquely
    F  schema and manifest parity for a fresh database

GROUP D IS THE ONE THAT MATTERS MOST. If a persisted mapping ever stopped
winning, a trade or a renamed player would mint a second identity mid-season and
every projection already attached to the first would describe someone else.

GROUP E IS THE ACCEPTANCE GATE. Those 58 records are real Yahoo rows from two
completed 2025 week-17 matchups that Phase 0 reconciled against BALLDONTLIE. If
any one of them stops resolving to the identity recorded in the fixture, the
resolver has changed its mind about a real player and that is a regression,
whatever the reason.

OFFLINE AND DETERMINISTIC. No network, no Yahoo, no BALLDONTLIE key, no clock
dependency. The BALLDONTLIE side is a committed identity-only projection of the
Phase 0 live capture: names, ids, teams and position labels, and not one
statistic. SQLite in-memory for the persistence group; this package adds no
dialect-specific behaviour and the same table is certified on PostgreSQL through
the shared migration suite.
"""
from __future__ import annotations

import json
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.schema import Base, Player, ProviderPlayerAlias
from providers.balldontlie_identity import (
    DEFAULT_FIXTURE,
    defense_key,
    directory_from_fixture,
    directory_from_rows,
    player_key,
)
from providers.cross_identity import (
    BALLDONTLIE,
    CanonicalSubject,
    Outcome,
    ProviderSubject,
    SubjectDirectory,
    bind_alias,
    discover,
    lookup_alias,
    normalize_person_name,
    resolve_player,
    retire_alias,
    set_manual_alias,
    suggest_candidates,
)
from providers.errors import ProviderIdentityError
from providers.nfl_teams import (
    CANONICAL_NFL_TEAMS,
    canonical_position,
    is_team_defense,
    to_canonical_team,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _refuses(label: str, call) -> None:
    """Assert a call fails closed with the repo's named identity refusal."""
    try:
        call()
    except ProviderIdentityError as exc:
        _assert(label, True, exc.reason)
    except Exception as exc:                                  # noqa: BLE001
        _assert(label, False, f"raised {type(exc).__name__}, not "
                              f"ProviderIdentityError: {exc}")
    else:
        _assert(label, False, "returned instead of refusing")


CORPUS_PATH = os.path.join("providers", "fixtures", "wp1_identity",
                           "yahoo_week17_identity_corpus.json")

DIRECTORY = directory_from_fixture()
CORPUS = json.load(open(CORPUS_PATH, encoding="utf-8"))


def _canonical(name, position, team, player_id=1):
    """A Yahoo-shaped record reduced to canonical identity terms."""
    return CanonicalSubject(
        player_id=player_id, name=name,
        position=canonical_position(position),
        nfl_team=to_canonical_team(team, dialect="yahoo") if team else None)


print("=" * 78)
print("WP1 · CANONICAL CROSS-PROVIDER PLAYER IDENTITY")
print("=" * 78)
print(f"  BALLDONTLIE directory : {DIRECTORY}")
print(f"  fixture               : {os.path.relpath(DEFAULT_FIXTURE)}")
print(f"  historical corpus     : {CORPUS['record_count']} Yahoo records "
      f"({CORPUS['season']} week {CORPUS['week']})")


# ── A · name normalization ────────────────────────────────────────────────────

print("\nWP1-A · name normalization folds spelling, never identity")

_assert("a trailing suffix separates from the core, not into it",
        normalize_person_name("Tyrone Tracy Jr.").core == "tyrone tracy"
        and normalize_person_name("Tyrone Tracy Jr.").suffix == "jr")
_assert("the suffixed and unsuffixed spellings share one core",
        normalize_person_name("James Cook III").core
        == normalize_person_name("James Cook").core == "james cook")
_assert("every generational suffix is recognised",
        [normalize_person_name(f"Ada Lovelace {s}").suffix
         for s in ("Jr.", "Sr.", "II", "III", "IV", "V")]
        == ["jr", "sr", "ii", "iii", "iv", "v"])
_assert("apostrophes join rather than separate",
        normalize_person_name("De'Von Achane").core == "devon achane"
        and normalize_person_name("Ka'imi Fairbairn").core == "kaimi fairbairn")
_assert("a typographic apostrophe folds the same as a typewriter one",
        normalize_person_name("De’Von Achane").core
        == normalize_person_name("De'Von Achane").core)
_assert("hyphens separate rather than join",
        normalize_person_name("Amon-Ra St. Brown").core == "amon ra st brown")
_assert("periods are removed, not turned into spaces",
        normalize_person_name("A.J. Brown").core == "aj brown")
_assert("case and repeated whitespace are folded",
        normalize_person_name("  jUSTIN   jEFFERSON ").core == "justin jefferson")
_assert("accents fold to their base letters",
        normalize_person_name("José Álvarez").core == "jose alvarez")
_assert("a two-token name is never stripped down to one",
        normalize_person_name("David V").core == "david v"
        and normalize_person_name("David V").suffix == "")
_assert("a three-token name does lose its trailing suffix",
        normalize_person_name("David Sills V").core == "david sills")
_refuses("an empty name refuses rather than matching everything",
         lambda: normalize_person_name("   "))
_refuses("a name that is only punctuation refuses",
         lambda: normalize_person_name("..."))

# The identity-preserving half: two different people never fold together.
_assert("two Wilsons with different first names keep different cores",
        len({normalize_person_name(n).core for n in
             ("Michael Wilson", "Garrett Wilson", "Russell Wilson",
              "Zach Wilson", "Roman Wilson", "Johnny Wilson",
              "Emanuel Wilson", "Jeff Wilson Jr.", "Cedrick Wilson Jr.")}) == 9)


# ── B · team and position dialects ───────────────────────────────────────────

print("\nWP1-B · provider dialects translate, and refuse what they do not know")

_assert("Yahoo WAS becomes canonical WSH",
        to_canonical_team("WAS", dialect="yahoo") == "WSH")
_assert("Yahoo JAC becomes canonical JAX",
        to_canonical_team("JAC", dialect="yahoo") == "JAX")
_assert("relocation spellings resolve to the current franchise",
        [to_canonical_team(a, dialect="yahoo") for a in ("SD", "OAK", "STL", "LA")]
        == ["LAC", "LV", "LAR", "LAR"])
_assert("lower-cased input is accepted",
        to_canonical_team("was", dialect="yahoo") == "WSH")
_assert("there are exactly thirty-two canonical teams",
        len(CANONICAL_NFL_TEAMS) == 32, str(len(CANONICAL_NFL_TEAMS)))

_bdl_teams = {s.nfl_team for s in DIRECTORY.subjects}
_assert("BALLDONTLIE names all thirty-two teams in the capture",
        len(_bdl_teams) == 32, str(len(_bdl_teams)))
_assert("every BALLDONTLIE abbreviation is ALREADY canonical (measured, "
        "not assumed)",
        _bdl_teams == set(CANONICAL_NFL_TEAMS),
        str(sorted(_bdl_teams ^ set(CANONICAL_NFL_TEAMS))))

_refuses("an unknown abbreviation refuses rather than passing through",
         lambda: to_canonical_team("XYZ", dialect="yahoo"))
_refuses("an empty abbreviation refuses",
         lambda: to_canonical_team("", dialect="yahoo"))
_refuses("an unknown dialect refuses",
         lambda: to_canonical_team("KC", dialect="sleeper"))

_assert("K and PK are one position",
        canonical_position("K") == canonical_position("PK") == "K")
_assert("DEF, DST and D/ST are one position",
        canonical_position("DEF") == canonical_position("DST")
        == canonical_position("D/ST") == "DEF")
_assert("is_team_defense recognises every spelling",
        all(is_team_defense(p) for p in ("DEF", "DST", "D/ST", "dst", "Defense"))
        and not is_team_defense("RB"))
_assert("a fullback is a running back",
        canonical_position("FB") == "RB")
_refuses("an unknown position refuses rather than matching everything",
         lambda: canonical_position("LS"))
_refuses("an empty position refuses",
         lambda: canonical_position(None))


# ── C · discovery is deterministic and fails closed ──────────────────────────

print("\nWP1-C · discovery is deterministic and fails closed")


def _subject(key, name, positions, team, defense=False):
    return ProviderSubject(
        provider=BALLDONTLIE, provider_player_key=key, name=name,
        positions=frozenset(positions), nfl_team=team,
        provider_positions=tuple(positions), is_team_defense=defense)


_res = discover(_canonical("Amon-Ra St. Brown", "WR", "DET"), DIRECTORY)
_assert("a real, unambiguous name resolves to exactly one subject",
        _res.outcome == Outcome.RESOLVED
        and _res.provider_player_key == "bdl.p.113",
        _res.provider_player_key or _res.outcome)
_assert("resolution records HOW it was made",
        _res.method == "normalized_discovery", str(_res.method))

# Duplicate names — the father/son case, both on one team at one position.
_dupes = SubjectDirectory(BALLDONTLIE, [
    _subject("bdl.p.9001", "Chris Doe", ["WR"], "KC"),
    _subject("bdl.p.9002", "Chris Doe", ["WR"], "KC"),
])
_res = discover(_canonical("Chris Doe", "WR", "KC"), _dupes)
_assert("two identical names on one team at one position are AMBIGUOUS",
        _res.outcome == Outcome.AMBIGUOUS, _res.outcome)
_assert("both candidates are reported, so an operator can choose",
        len(_res.candidates) == 2)
_assert("an AMBIGUOUS resolution binds nothing and names no key",
        _res.provider_player_key is None and _res.subject is None)

_sfx = SubjectDirectory(BALLDONTLIE, [
    _subject("bdl.p.9003", "Chris Doe", ["WR"], "KC"),
    _subject("bdl.p.9004", "Chris Doe Jr.", ["WR"], "KC"),
])
_res = discover(_canonical("Chris Doe Jr.", "WR", "KC"), _sfx)
_assert("a generational suffix separates a father from his son",
        _res.outcome == Outcome.RESOLVED
        and _res.provider_player_key == "bdl.p.9004", _res.outcome)
_res = discover(_canonical("Chris Doe", "WR", "KC"), _sfx)
_assert("and the unsuffixed spelling takes the unsuffixed subject",
        _res.outcome == Outcome.RESOLVED
        and _res.provider_player_key == "bdl.p.9003", _res.outcome)

_res = discover(_canonical("Nobody Atall", "WR", "KC"), DIRECTORY)
_assert("a subject the provider does not carry is UNRESOLVED, not a guess",
        _res.outcome == Outcome.UNRESOLVED, _res.outcome)
_assert("UNRESOLVED is a DIFFERENT outcome from AMBIGUOUS",
        Outcome.UNRESOLVED != Outcome.AMBIGUOUS != Outcome.CONFLICT)

# The traded player — our stored team is stale, the provider's is current.
_res = discover(_canonical("Amon-Ra St. Brown", "WR", "NYJ"), DIRECTORY)
_assert("a stale team falls back to name+position and still resolves",
        _res.outcome == Outcome.RESOLVED
        and _res.provider_player_key == "bdl.p.113", _res.outcome)
_assert("the fallback is recorded as the weaker method it is",
        _res.method == "normalized_discovery_team_relaxed", str(_res.method))

_relaxed_dupes = SubjectDirectory(BALLDONTLIE, [
    _subject("bdl.p.9005", "Chris Doe", ["WR"], "KC"),
    _subject("bdl.p.9006", "Chris Doe", ["WR"], "SF"),
])
_res = discover(_canonical("Chris Doe", "WR", "DEN"), _relaxed_dupes)
_assert("relaxing the team never resolves two same-named players",
        _res.outcome == Outcome.AMBIGUOUS, _res.outcome)

_precedence = SubjectDirectory(BALLDONTLIE, [
    _subject("bdl.p.9007", "Chris Doe", ["WR"], "KC"),
    _subject("bdl.p.9008", "Chris Doe", ["WR"], "SF"),
    _subject("bdl.p.9009", "Chris Doe", ["WR"], "DEN"),
])
_res = discover(_canonical("Chris Doe", "WR", "SF"), _precedence)
_assert("a team-confirmed match is never overridden by the relaxed pass",
        _res.outcome == Outcome.RESOLVED
        and _res.provider_player_key == "bdl.p.9008", _res.outcome)

_res = discover(_canonical("A Free Agent", "WR", None), DIRECTORY)
_assert("a player with no NFL team is still refused rather than guessed at",
        _res.outcome == Outcome.UNRESOLVED, _res.outcome)

# Team defenses — identity is the team, and the name is never read.
_res = discover(_canonical("Washington Commanders", "DEF", "WAS"), DIRECTORY)
_assert("Yahoo DEF resolves to the BALLDONTLIE DST for the same franchise",
        _res.outcome == Outcome.RESOLVED
        and _res.provider_player_key == defense_key("WSH"), _res.outcome)
_res = discover(_canonical("literally any string at all", "DEF", "KC"), DIRECTORY)
_assert("a team defense resolves on its TEAM, never on its name",
        _res.outcome == Outcome.RESOLVED
        and _res.provider_player_key == defense_key("KC"), _res.outcome)
_two_defenses = SubjectDirectory(BALLDONTLIE, [
    _subject("bdl.dst.KC", "Kansas City Chiefs", ["DEF"], "KC", defense=True),
    _subject("bdl.dst.KC2", "Kansas City Chiefs", ["DEF"], "KC", defense=True),
])
_res = discover(_canonical("Kansas City Chiefs", "DEF", "KC"), _two_defenses)
_assert("two defenses claiming one franchise are AMBIGUOUS",
        _res.outcome == Outcome.AMBIGUOUS, _res.outcome)

# The position contradiction inside one BALLDONTLIE payload.
_kicker = DIRECTORY.by_key("bdl.p.7544")
_assert("a kicker carries both provider labels and one canonical position",
        _kicker is not None and _kicker.positions == frozenset({"K"})
        and "PK" in _kicker.provider_positions,
        str(_kicker.provider_positions if _kicker else None))

_assert("suggest_candidates is available to an operator and binds nothing",
        len(suggest_candidates(_canonical("Michael Wilson", "WR", "NYJ"),
                               DIRECTORY)) > 0)


# ── D · the persisted mapping IS the identity ────────────────────────────────

print("\nWP1-D · the persisted mapping is the identity")


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _session_without_alias_uniques():
    """A session whose alias table has LOST its two unique constraints.

    The CONFLICT group has to reach a state the constraints exist to forbid,
    which is exactly why it cannot be built through them. A half-applied
    migration, a restored older dump or a hand-edited schema produces this
    database in the real world, and the resolver must refuse rather than pick —
    so the state is constructed deliberately here and the refusal asserted.
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE provider_player_alias")
        connection.exec_driver_sql("""
            CREATE TABLE provider_player_alias (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                provider            VARCHAR NOT NULL,
                provider_player_key VARCHAR NOT NULL,
                player_id           INTEGER NOT NULL REFERENCES players (id),
                provider_position   VARCHAR,
                provider_nfl_team   VARCHAR(4),
                status              VARCHAR NOT NULL,
                method              VARCHAR NOT NULL,
                manual_override     BOOLEAN NOT NULL DEFAULT 0,
                created_at          TIMESTAMP NOT NULL,
                updated_at          TIMESTAMP NOT NULL
            )
        """)
    return sessionmaker(bind=engine)()


def _player(db, name, position, team, provider="yahoo", key=None, pid=None):
    player = Player(id=pid, name=name, position=position, nfl_team=team,
                    provider=provider,
                    provider_player_key=key or f"461.p.{abs(hash(name)) % 99999}")
    db.add(player)
    db.flush()
    return player


db = _session()
_p = _player(db, "Amon-Ra St. Brown", "WR", "DET")
_res = resolve_player(db, _p, DIRECTORY)
_assert("a first resolution discovers and persists the mapping",
        _res.resolved and _res.provider_player_key == "bdl.p.113")
_rows = lookup_alias(db, provider=BALLDONTLIE, player_id=_p.id)
_assert("exactly one alias row is written",
        len(_rows) == 1 and _rows[0].method == "normalized_discovery")
_assert("the alias records the provider's observation of team and position",
        _rows[0].provider_nfl_team == "DET" and _rows[0].provider_position == "WR",
        f"{_rows[0].provider_nfl_team}/{_rows[0].provider_position}")

# The rename. Nothing about the name is read a second time.
_p.name = "Completely Different Person"
_p.position = "TE"
db.flush()
_res = resolve_player(db, _p, DIRECTORY)
_assert("a RENAMED player keeps the identity he already had",
        _res.resolved and _res.provider_player_key == "bdl.p.113", _res.outcome)
_assert("and the resolution says the name was never consulted",
        "persisted alias" in _res.detail)

# The trade. The observation moves; the identity does not.
db2 = _session()
_traded = _player(db2, "Amon-Ra St. Brown", "WR", "DET")
resolve_player(db2, _traded, DIRECTORY)
_traded.nfl_team = "NYJ"
db2.flush()
_res = resolve_player(db2, _traded, DIRECTORY)
_assert("a TRADED player does not mint a second identity",
        _res.resolved and _res.provider_player_key == "bdl.p.113", _res.outcome)
_assert("one alias row still, after the trade",
        len(lookup_alias(db2, provider=BALLDONTLIE, player_id=_traded.id)) == 1)
_assert("the provider's own team observation is refreshed, not the mapping",
        lookup_alias(db2, provider=BALLDONTLIE,
                     player_id=_traded.id)[0].provider_nfl_team == "DET")

# A mapping whose subject simply did not play this week.
db3 = _session()
_benched = _player(db3, "Bench Warmer", "WR", "KC")
bind_alias(db3, provider=BALLDONTLIE, player_id=_benched.id,
           provider_player_key="bdl.p.999999", method="manual")
_res = resolve_player(db3, _benched, DIRECTORY)
_assert("a mapped player absent from this week's slate is RESOLVED, not lost",
        _res.resolved, _res.outcome)
_assert("and the caller can tell 'mapped, no data' from 'unmapped'",
        _res.subject_in_directory is False and _res.subject is None)

# Provider ids are the durable key: a row already carrying the far provider's
# own identifier never touches a name.
db4 = _session()
_native = _player(db4, "Nobody Would Match This Name", "WR", "DET",
                  provider=BALLDONTLIE, key=player_key(113))
_res = resolve_player(db4, _native, DIRECTORY)
_assert("a row carrying the provider's own id resolves without any name",
        _res.resolved and _res.provider_player_key == "bdl.p.113"
        and _res.method == ProviderPlayerAlias.METHOD_PROVIDER_ID, _res.outcome)

# Rebinding refusals.
db5 = _session()
_a = _player(db5, "Amon-Ra St. Brown", "WR", "DET")
_b = _player(db5, "Jameson Williams", "WR", "DET")
resolve_player(db5, _a, DIRECTORY)
_refuses("rebinding a mapped player to a different key is a CONFLICT",
         lambda: bind_alias(db5, provider=BALLDONTLIE, player_id=_a.id,
                            provider_player_key="bdl.p.656", method="manual"))
_refuses("binding a key another player already holds is a CONFLICT",
         lambda: bind_alias(db5, provider=BALLDONTLIE, player_id=_b.id,
                            provider_player_key="bdl.p.113", method="manual"))
_assert("re-binding the SAME pair is idempotent, not an error",
        bind_alias(db5, provider=BALLDONTLIE, player_id=_a.id,
                   provider_player_key="bdl.p.113",
                   method="normalized_discovery").id
        == lookup_alias(db5, provider=BALLDONTLIE, player_id=_a.id)[0].id)

# Provider id reuse: a retired row keeps its key occupied.
db6 = _session()
_old = _player(db6, "Amon-Ra St. Brown", "WR", "DET")
_new = _player(db6, "Jameson Williams", "WR", "DET")
resolve_player(db6, _old, DIRECTORY)
retire_alias(db6, provider=BALLDONTLIE, player_id=_old.id)
_assert("a retired mapping stops resolving",
        lookup_alias(db6, provider=BALLDONTLIE, player_id=_old.id) == [])
_assert("but the row is kept, not deleted",
        len(lookup_alias(db6, provider=BALLDONTLIE, player_id=_old.id,
                         include_retired=True)) == 1)
_refuses("a retired row still blocks the key — the id-reuse guard",
         lambda: bind_alias(db6, provider=BALLDONTLIE, player_id=_new.id,
                            provider_player_key="bdl.p.113", method="manual"))

# Conflicting stored mappings surface as CONFLICT, not as an arbitrary pick.
db7 = _session_without_alias_uniques()
_c1 = _player(db7, "Chris Doe", "WR", "KC")
db7.add(ProviderPlayerAlias(provider=BALLDONTLIE, provider_player_key="bdl.p.7001",
                            player_id=_c1.id, status="active", method="manual"))
db7.add(ProviderPlayerAlias(provider=BALLDONTLIE, provider_player_key="bdl.p.7002",
                            player_id=_c1.id, status="active", method="manual"))
db7.flush()
_res = resolve_player(db7, _c1, DIRECTORY)
_assert("two ACTIVE aliases for one player is a CONFLICT, never a pick",
        _res.outcome == Outcome.CONFLICT, _res.outcome)
_assert("CONFLICT names both stored keys so an operator can act",
        "bdl.p.7001" in _res.detail and "bdl.p.7002" in _res.detail)

db8 = _session_without_alias_uniques()
_d1 = _player(db8, "Chris Doe", "WR", "KC")
_d2 = _player(db8, "Chris Roe", "WR", "SF")
db8.add(ProviderPlayerAlias(provider=BALLDONTLIE, provider_player_key="bdl.p.7003",
                            player_id=_d1.id, status="active", method="manual"))
db8.add(ProviderPlayerAlias(provider=BALLDONTLIE, provider_player_key="bdl.p.7003",
                            player_id=_d2.id, status="active", method="manual"))
db8.flush()
_res = resolve_player(db8, _d1, DIRECTORY)
_assert("one provider key claimed by two players is a CONFLICT",
        _res.outcome == Outcome.CONFLICT, _res.outcome)

# Manual override — the only path that may move a mapping.
db9 = _session()
_m = _player(db9, "Chris Doe", "WR", "KC")
_res = resolve_player(db9, _m, DIRECTORY)
_assert("an unmatched player is UNRESOLVED before any override",
        _res.outcome == Outcome.UNRESOLVED, _res.outcome)
set_manual_alias(db9, provider=BALLDONTLIE, player_id=_m.id,
                 provider_player_key="bdl.p.113")
_res = resolve_player(db9, _m, DIRECTORY)
_assert("a manual override resolves what discovery refused",
        _res.resolved and _res.provider_player_key == "bdl.p.113", _res.outcome)
_alias = lookup_alias(db9, provider=BALLDONTLIE, player_id=_m.id)[0]
_assert("and the override leaves its evidence on the row",
        _alias.manual_override is True and _alias.method == "manual")
set_manual_alias(db9, provider=BALLDONTLIE, player_id=_m.id,
                 provider_player_key="bdl.p.656")
_assert("a manual override MAY move a mapping the resolver may not",
        lookup_alias(db9, provider=BALLDONTLIE,
                     player_id=_m.id)[0].provider_player_key == "bdl.p.656")
_assert("and the superseded mapping is retired, not deleted",
        len(lookup_alias(db9, provider=BALLDONTLIE, player_id=_m.id,
                         include_retired=True)) == 2)
_other = _player(db9, "Someone Else", "WR", "KC")
_refuses("a manual override may not take a subject from another player",
         lambda: set_manual_alias(db9, provider=BALLDONTLIE, player_id=_other.id,
                                  provider_player_key="bdl.p.656"))

# Dry-run writes nothing.
db10 = _session()
_dry = _player(db10, "Amon-Ra St. Brown", "WR", "DET")
_res = resolve_player(db10, _dry, DIRECTORY, persist=False)
_assert("persist=False reaches the same decision and writes nothing",
        _res.resolved and lookup_alias(db10, provider=BALLDONTLIE,
                                       player_id=_dry.id) == [])

# .require() carries the right named refusal all the way out.
for _outcome, _reason, _subject_args in (
        (Outcome.UNRESOLVED, ProviderIdentityError.UNKNOWN,
         ("Nobody Atall", "WR", "KC")),
        (Outcome.AMBIGUOUS, ProviderIdentityError.AMBIGUOUS, None)):
    if _subject_args:
        _r = discover(_canonical(*_subject_args), DIRECTORY)
    else:
        _r = discover(_canonical("Chris Doe", "WR", "KC"), _dupes)
    try:
        _r.require()
        _assert(f"require() raises on {_outcome}", False, "returned")
    except ProviderIdentityError as exc:
        _assert(f"require() raises the repo's {_reason} on {_outcome}",
                exc.reason == _reason, exc.reason)

_assert("a RESOLVED require() returns the subject",
        discover(_canonical("Amon-Ra St. Brown", "WR", "DET"),
                 DIRECTORY).require().provider_player_key == "bdl.p.113")

# The database enforces the bijection even if the code above were bypassed.
db11 = _session()
_e1 = _player(db11, "One", "WR", "KC")
_e2 = _player(db11, "Two", "WR", "KC")
db11.add(ProviderPlayerAlias(provider=BALLDONTLIE, provider_player_key="bdl.p.8001",
                             player_id=_e1.id, status="active", method="manual"))
db11.add(ProviderPlayerAlias(provider=BALLDONTLIE, provider_player_key="bdl.p.8001",
                             player_id=_e2.id, status="active", method="manual"))
try:
    db11.commit()
    _assert("the database refuses one provider key on two players", False,
            "commit succeeded")
except Exception:
    db11.rollback()
    _assert("the database refuses one provider key on two players", True)

db12 = _session()
_f1 = _player(db12, "One", "WR", "KC")
db12.add(ProviderPlayerAlias(provider=BALLDONTLIE, provider_player_key="bdl.p.8002",
                             player_id=_f1.id, status="active", method="manual"))
db12.add(ProviderPlayerAlias(provider=BALLDONTLIE, provider_player_key="bdl.p.8003",
                             player_id=_f1.id, status="active", method="manual"))
try:
    db12.commit()
    _assert("the database refuses one player holding two ACTIVE subjects", False,
            "commit succeeded")
except Exception:
    db12.rollback()
    _assert("the database refuses one player holding two ACTIVE subjects", True)


# ── E · the historical acceptance corpus ─────────────────────────────────────

print("\nWP1-E · the 58 historical week-17 records")

_counts = {Outcome.RESOLVED: 0, Outcome.UNRESOLVED: 0,
           Outcome.AMBIGUOUS: 0, Outcome.CONFLICT: 0}
_wrong_identity: list[str] = []
_suffix_variants = 0
_suffix_mismatches: list[str] = []

# ONE `players` ROW PER REAL PLAYER, NOT PER RECORD. Six of the 58 records name
# a player who appears twice — Trevor Lawrence started for a team in each league,
# and the Titans defense was rostered in both. `players` is global and keyed on
# the Yahoo player key, so the second reference is the SAME row, and resolving it
# exercises the persisted path rather than discovery a second time. Building 58
# separate rows would have been a fiction, and the provider-key constraint says
# so out loud.
_dbE = _session()
_rows_by_subject: dict[tuple, object] = {}
_second_references = 0
_persisted_hits = 0
for _index, _record in enumerate(CORPUS["records"], start=1):
    _subject_key = (_record["yahoo_name"], _record["yahoo_display_position"],
                    _record["yahoo_editorial_team_abbr"])
    _row = _rows_by_subject.get(_subject_key)
    if _row is None:
        _row = _player(_dbE, _record["yahoo_name"],
                       _record["yahoo_display_position"],
                       _record["yahoo_editorial_team_abbr"],
                       key=f"461.p.corpus{len(_rows_by_subject) + 1}")
        _rows_by_subject[_subject_key] = _row
    else:
        _second_references += 1
    _res = resolve_player(_dbE, _row, DIRECTORY)
    if "persisted alias" in _res.detail:
        _persisted_hits += 1
    _counts[_res.outcome] += 1
    if _res.provider_player_key != _record["expected_balldontlie_key"]:
        _wrong_identity.append(
            f"{_record['yahoo_name']}: {_res.provider_player_key} != "
            f"{_record['expected_balldontlie_key']}")

    # Yahoo does not always print the generational suffix BALLDONTLIE carries.
    _alt = _record.get("yahoo_name_without_suffix")
    if _alt:
        _suffix_variants += 1
        _res_alt = discover(_canonical(_alt, _record["yahoo_display_position"],
                                       _record["yahoo_editorial_team_abbr"]),
                            DIRECTORY)
        if _res_alt.provider_player_key != _record["expected_balldontlie_key"]:
            _suffix_mismatches.append(_alt)

_assert(f"all {CORPUS['record_count']} records RESOLVE",
        _counts[Outcome.RESOLVED] == CORPUS["record_count"] == 58,
        f"resolved={_counts[Outcome.RESOLVED]}")
_assert("zero AMBIGUOUS", _counts[Outcome.AMBIGUOUS] == 0,
        str(_counts[Outcome.AMBIGUOUS]))
_assert("zero UNRESOLVED", _counts[Outcome.UNRESOLVED] == 0,
        str(_counts[Outcome.UNRESOLVED]))
_assert("zero CONFLICT", _counts[Outcome.CONFLICT] == 0,
        str(_counts[Outcome.CONFLICT]))
_assert("the 58 records name 52 distinct players, and one row serves each",
        len(_rows_by_subject) == 52 and _second_references == 6,
        f"{len(_rows_by_subject)} rows, {_second_references} second references")
_assert("a second reference to the same player reads the PERSISTED mapping",
        _persisted_hits == _second_references == 6, str(_persisted_hits))
_assert("52 alias rows exist afterwards — one per distinct player, no more",
        _dbE.query(ProviderPlayerAlias).count() == 52,
        str(_dbE.query(ProviderPlayerAlias).count()))
_assert("every record resolves to the identity Phase 0 reconciled",
        not _wrong_identity, "; ".join(_wrong_identity[:4]))
_assert(f"the {_suffix_variants} suffixed names also resolve WITHOUT the suffix",
        _suffix_variants == 6 and not _suffix_mismatches,
        "; ".join(_suffix_mismatches) or f"{_suffix_variants} variants")

_by_name = {r["yahoo_name"]: r["expected_balldontlie_key"]
            for r in CORPUS["records"]}
for _hard in ("Tyrone Tracy Jr.", "James Cook III", "Michael Wilson",
              "Amon-Ra St. Brown", "Ka'imi Fairbairn", "De'Von Achane",
              "Kyle Pitts Sr.", "Chris Godwin Jr.", "Travis Etienne Jr.",
              "Harold Fannin Jr."):
    _assert(f"the hard case {_hard!r} is in the corpus and resolved",
            _hard in _by_name, _by_name.get(_hard, "ABSENT"))

# The Wilson collision, stated directly rather than implied by a total.
_wilsons = [s for s in DIRECTORY.subjects
            if not s.is_team_defense and s.name.split(" ")[-1].startswith("Wilson")
            or (not s.is_team_defense and " Wilson" in s.name)]
_assert("the capture really does carry the Wilson collision cases",
        len(_wilsons) >= 8, f"{len(_wilsons)} Wilsons")
_assert("Michael Wilson resolves to ARI and to no other Wilson",
        _by_name["Michael Wilson"] == "bdl.p.882")
for _wrong_team, _label in (("NYJ", "Garrett Wilson's team"),
                            ("NYG", "Russell Wilson's team"),
                            ("PIT", "Roman Wilson's team")):
    _r = discover(_canonical("Michael Wilson", "WR", _wrong_team), DIRECTORY)
    _assert(f"'Michael Wilson' on {_label} does not become that Wilson",
            _r.provider_player_key == "bdl.p.882", str(_r.provider_player_key))

_defenses = [r for r in CORPUS["records"]
             if r["yahoo_display_position"] == "DEF"]
_assert(f"all {len(_defenses)} Yahoo DEF records map to a BALLDONTLIE DST",
        len(_defenses) == 7
        and all(r["expected_balldontlie_key"]
                == defense_key(to_canonical_team(r["yahoo_editorial_team_abbr"],
                                                 dialect="yahoo"))
                for r in _defenses),
        f"{len(_defenses)} defenses")

_assert("the corpus carries no scoring figure of any kind",
        not any(k for r in CORPUS["records"] for k in r
                if "point" in k or "score" in k or "stat" in k))


# ── F · schema and manifest parity ───────────────────────────────────────────

print("\nWP1-F · fresh-database and migration parity")

_assert("provider_player_alias is declared on Base metadata",
        "provider_player_alias" in Base.metadata.tables)
_table = Base.metadata.tables["provider_player_alias"]
_assert("the provider-key side is a PLAIN unique, spanning retired rows",
        "uq_provider_player_alias_key" in {c.name for c in _table.constraints})
_partial = {i.name: i for i in _table.indexes}.get(
    "uq_provider_player_alias_active_player")
_assert("the player side is a PARTIAL unique on status='active'",
        _partial is not None and _partial.unique
        and "status" in str(_partial.dialect_options["sqlite"]["where"])
        and "status" in str(_partial.dialect_options["postgresql"]["where"]))
_assert("player_id is a foreign key onto players.id — canonical identity is "
        "the existing row",
        [str(fk.target_fullname) for fk in _table.c.player_id.foreign_keys]
        == ["players.id"])

_ACTIVE = __import__("migrations.manifest", fromlist=["ACTIVE"]).ACTIVE
_assert("the migration manifest registers the alias table",
        any(m.identifier == "0014_provider_player_alias"
            and "provider_player_alias" in m.tables for m in _ACTIVE))

# THE RETENTION INVENTORY MUST ACCOUNT FOR THIS TABLE, AND MUST NOT CALL IT
# YAHOO'S. `ops/yahoo_retention.py` demands that every provider-named column in
# the schema be classified, and WP1 added four of them that Yahoo did not
# supply. C-1 fails the whole tree if they go unclassified; this asserts the
# other half — that the classification names BALLDONTLIE — because a green C-1
# is equally reachable by filing them as Yahoo facts, which would be a false
# statement about where the data came from in the one document a retention
# ruling would be read against.
_ret = __import__("ops.yahoo_retention",
                  fromlist=["FOREIGN_PROVIDER_FIELDS", "inventoried_columns",
                            "related_columns"])
_alias_named = {c for c in _table.c.keys()
                if c.startswith("provider_") or c == "provider"}
_classified = {f.column for f in _ret.FOREIGN_PROVIDER_FIELDS
               if f.table == "provider_player_alias"}
_assert("every provider-named alias column is in the retention inventory",
        _alias_named <= _classified,
        f"unclassified: {sorted(_alias_named - _classified)}"
        if _alias_named - _classified else f"{len(_alias_named)} columns")
_assert("  · and each is recorded as BALLDONTLIE's, never as Yahoo's",
        all(f.provider == BALLDONTLIE for f in _ret.FOREIGN_PROVIDER_FIELDS
            if f.table == "provider_player_alias"))
_assert("  · and no alias column is claimed by the Yahoo inventory",
        not {("provider_player_alias", c) for c in _alias_named}
        & (_ret.inventoried_columns() | _ret.related_columns()))

# THE MIGRATION IS RUN, NOT READ. `Base.metadata.create_all` builds a FRESH
# database from the models and never executes migrations/, so a model that is
# right and a migration that is wrong both look identical to every assertion
# above. This applies the real migration to a real pre-WP1 database — one built
# from every model EXCEPT this one — and applies it twice, in a subprocess
# because `db.schema.engine` binds to DATABASE_URL once at import.
_probe = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      ".wp1_migration_probe.db")
if os.path.exists(_probe):
    os.remove(_probe)
_env = dict(os.environ, DATABASE_URL=f"sqlite:///{_probe.replace(os.sep, '/')}")
_out = __import__("subprocess").run(
    [sys.executable, "-X", "utf8", "-c", """
from sqlalchemy import inspect
from db.schema import Base, engine
Base.metadata.create_all(engine, tables=[t for n, t in Base.metadata.tables.items()
                                         if n != "provider_player_alias"])
import migrations.add_provider_player_alias as m
first, second = m.upgrade(), m.upgrade()
i = inspect(engine)
print("FIRST", "created provider_player_alias" in first)
print("SECOND", second == ["provider_player_alias already exists"])
print("PARTIAL", any(x["name"] == "uq_provider_player_alias_active_player"
                     and x["unique"] for x in i.get_indexes("provider_player_alias")))
print("KEYUNIQUE", any(sorted(u["column_names"]) == ["provider", "provider_player_key"]
                       for u in i.get_unique_constraints("provider_player_alias")))
print("FK", [(f["referred_table"], f["constrained_columns"])
             for f in i.get_foreign_keys("provider_player_alias")]
      == [("players", ["player_id"])])
print("COLUMNS", sorted(c["name"] for c in i.get_columns("provider_player_alias")))
"""],
    capture_output=True, text=True, env=_env,
    cwd=os.path.dirname(os.path.abspath(__file__)))
if os.path.exists(_probe):
    os.remove(_probe)
_migration = dict(line.split(" ", 1) for line in _out.stdout.strip().splitlines()
                  if " " in line) if _out.returncode == 0 else {}
_assert("the migration applies to a real pre-WP1 database",
        _migration.get("FIRST") == "True",
        _out.stderr.strip().splitlines()[-1] if _out.stderr else "")
_assert("applying it a second time is a no-op",
        _migration.get("SECOND") == "True", _migration.get("SECOND", "?"))
_assert("the migration builds the PARTIAL unique the model declares",
        _migration.get("PARTIAL") == "True", _migration.get("PARTIAL", "?"))
_assert("the migration builds the plain unique on the provider key",
        _migration.get("KEYUNIQUE") == "True", _migration.get("KEYUNIQUE", "?"))
_assert("the migration builds the foreign key onto players.id",
        _migration.get("FK") == "True", _migration.get("FK", "?"))
_assert("migration and model agree on every column",
        _migration.get("COLUMNS", "") == str(sorted(_table.c.keys())),
        _migration.get("COLUMNS", "?"))

_fixture = json.load(open(DEFAULT_FIXTURE, encoding="utf-8"))
_assert("the BALLDONTLIE fixture is identity-only — no statistic is committed",
        not any(k for s in _fixture["subjects"] for k in s
                if k in ("stats", "points", "game", "fantasy_points")))
_assert("the fixture carries every subject the capture did",
        _fixture["subject_count"] == len(DIRECTORY) == 742,
        f"{_fixture['subject_count']}/{len(DIRECTORY)}")
_assert("directory_from_rows and directory_from_fixture agree",
        len(directory_from_rows(_fixture["subjects"])) == len(DIRECTORY))

# PROVENANCE IS STATED, AND IT IS NOT "CAPTURED". `providers/fixtures/record.py`
# reserves CAPTURED for verbatim payload bytes written by capture_live(), and
# C-25 treats that tier as the only evidence that can certify live parsing.
# Neither WP1 file is such a payload — one is a projection of a capture, the
# other is transcribed from screenshots because Yahoo answers this application
# with 403 — so both say so, in the file, where a reader of the file will see it.
_assert("the BALLDONTLIE fixture declares its provenance, and does not claim "
        "to be a captured payload",
        _fixture.get("provenance") == "DERIVED_FROM_CAPTURED",
        str(_fixture.get("provenance")))
_assert("the Yahoo acceptance corpus declares its provenance as transcribed",
        CORPUS.get("provenance") == "TRANSCRIBED", str(CORPUS.get("provenance")))
_assert("  · and neither WP1 file claims the CAPTURED tier",
        "CAPTURED" not in {_fixture.get("provenance"), CORPUS.get("provenance")})


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print(f"WP1 cross-provider identity: all assertions passed "
      f"({CORPUS['record_count']}/{CORPUS['record_count']} historical records "
      f"resolved, 0 ambiguous, 0 unresolved)")
