#!/usr/bin/env python3
"""FINAL POR · WP-11 certification — the Fantasy Football Championship.

    F1  provider finality is three-valued, and UNKNOWN is BLOCKED
    F2  no bracket state at all is BLOCKED — never a silent zero
    F3  the podium comes from the bracket, never from a score
    F4  a tied final is an UNDECIDED game, not a dead heat
    F5  a bracket with no decided third place REFUSES rather than partly paying
    F6  a stated bracket pays 60/30/10 and conserves
    F7  the provider gate runs BEFORE the pot is read
    F8  an unresolvable provider team key refuses rather than paying a guess
    F9  exactly-once, and the legacy era is refused
    F10 nothing here reads a provider payload or classifies a matchup
    F11 the TWO-TEAM PLAYOFF exception pays 67/33 and conserves
    F12 a missing third place in a 3+ team format NEVER triggers 67/33

WHAT IS AND IS NOT CERTIFIED HERE. Everything downstream of the seam — the pot,
the podium arithmetic, exactly-once payment, conservation, the era gate and
every refusal — is exercised against a hand-stated bracket. What is NOT
certified is an end-to-end settlement against real Yahoo bracket data, because
no Yahoo postseason classification exists in this build. That is PROV-1/PROV-2
and is marked BLOCKED, not quietly assumed.

WHY F10 IS AN ASSERTION. The temptation in this module is to reach for a
payload and infer a winner from a score. F10 walks the source and requires that
nothing here imports a provider client, reads a Matchup score, or names a Yahoo
field — so "it does not invent bracket facts" is checked rather than promised.
"""
from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import ledger.ledger as ledger_module
from db.schema import Base, League, Team, Wallet
from economy.championship_pots import mint_fantasy_football_pot
from economy.economy_events import ff_championship_account
from economy.championship_distribution import (
    CHAMPIONSHIP_SPLIT, TWO_TEAM_PLAYOFF_SPLIT,
)
from economy.ff_championship_settlement import (
    FINALITY_AVAILABLE, FINALITY_BLOCKED, FINALITY_NOT_COMPLETE,
    STRUCTURE_STANDARD, STRUCTURE_TWO_TEAM, FFChampionshipError,
    is_two_team_playoff, official_field_size, podium, pot_cents,
    provider_finality, settle,
)
from ruleset import RULESET_FINAL_POR, stamp_ruleset

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
NAIVE = NOW.replace(tzinfo=None)

LEAGUE = 1
SEASON = 2026
POT = 10_000                      # $100, a commissioner-entered league amount
TEAMS = (1, 2, 3, 4)
KEYS = {t: f"k{t}" for t in TEAMS}
ACCOUNT = ff_championship_account(LEAGUE, SEASON)


# ── A hand-stated bracket ───────────────────────────────────────────────────
#
# STATED, NOT DERIVED, and that is the point of the fixture. The real
# `ChampionshipTrackState` is produced by `season.championship_track` from
# provider input this build does not have. What WP-11 owns begins where that
# object is handed over, so the suite hands one over — with exactly the fields
# the settlement is allowed to read, and no payload behind them.

@dataclass(frozen=True)
class _Game:
    winner_team_key: str | None
    is_decided: bool


@dataclass(frozen=True)
class _State:
    authority: str = "PROVIDER"
    insufficiency_reasons: tuple = ()
    complete: bool = True
    champion_team_key: str | None = KEYS[1]
    finalist_team_keys: tuple = (KEYS[1], KEYS[2])
    third_place_matchup: object = None
    # THE OFFICIAL PLAYOFF FIELD. Four teams by default, which is the format
    # that HAS a third-place game -- so every pre-existing case in this suite
    # still exercises the fail-closed path it was written for.
    championship_field_team_keys: frozenset = frozenset(
        {KEYS[1], KEYS[2], KEYS[3], KEYS[4]})


DECIDED_THIRD = _Game(winner_team_key=KEYS[3], is_decided=True)
TIED_THIRD = _Game(winner_team_key=None, is_decided=False)


def _build(*, final_por: bool = True, mint: bool = True, bind: bool = True):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ledger_module.engine = engine
    ledger_module._LedgerBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    db.add(League(id=LEAGUE, name="L", season=SEASON, start_week=1,
                  playoff_start_week=15, provider="yahoo"))
    for t in TEAMS:
        db.add(Team(id=t, league_id=LEAGUE, team_name=f"T{t}", owner=f"O{t}",
                    email=f"t{t}@example.test", provider="yahoo",
                    provider_team_key=(KEYS[t] if bind else None)))
        db.add(Wallet(team_id=t, balance=0.0))
    db.commit()
    if final_por:
        stamp_ruleset(db, league_id=LEAGUE, season=SEASON,
                      version=RULESET_FINAL_POR)
        db.commit()
        if mint:
            mint_fantasy_football_pot(db, league_id=LEAGUE, season=SEASON,
                                      amount_cents=POT, now=NOW)
            db.commit()
    return db


def _bal(db, account: str) -> int:
    return ledger_module._balance_of_in_session(db, account)


# ── F1/F2 · provider finality ───────────────────────────────────────────────

print("\nWP11-F1/F2 · provider finality is three-valued; UNKNOWN is BLOCKED")
db = _build()

_assert("a complete, decided bracket is AVAILABLE",
        provider_finality(_State(third_place_matchup=DECIDED_THIRD)).status
        == FINALITY_AVAILABLE)
none_state = provider_finality(None)
_assert("  · NO bracket state at all is BLOCKED",
        none_state.status == FINALITY_BLOCKED, none_state.status)
_assert("  · and says why, naming UNKNOWN fails closed",
        any("UNKNOWN fails closed" in r for r in none_state.reasons),
        str(none_state.reasons))
unknown = provider_finality(_State(
    authority="UNKNOWN", insufficiency_reasons=("no postseason payload",)))
_assert("  · an UNKNOWN track authority is BLOCKED",
        unknown.status == FINALITY_BLOCKED, unknown.status)
_assert("  · carrying the track's own insufficiency reason",
        any("no postseason payload" in r for r in unknown.reasons),
        str(unknown.reasons))
incomplete = provider_finality(_State(complete=False))
_assert("  · a readable but incomplete bracket is NOT_COMPLETE, not BLOCKED",
        incomplete.status == FINALITY_NOT_COMPLETE, incomplete.status)
_assert("  · so 'nobody has won yet' is distinguishable from 'we cannot see'",
        incomplete.status != none_state.status)

for state, label in ((None, "no state"),
                     (_State(authority="UNKNOWN"), "UNKNOWN authority"),
                     (_State(complete=False), "incomplete bracket")):
    try:
        settle(db, league_id=LEAGUE, state=state, now=NOW)
        _assert(f"  · settling with {label} is refused", False, "accepted")
    except FFChampionshipError as exc:
        db.rollback()
        _assert(f"  · settling with {label} is refused",
                exc.reason == "FF_PROVIDER_FINALITY_BLOCKED", exc.reason)
_assert("  · and NOTHING was paid — never a silent zero",
        all(_bal(db, f"wallet:{t}") == 0 for t in TEAMS)
        and _bal(db, ACCOUNT) == POT,
        f"pot={_bal(db, ACCOUNT)}")


# ── F3/F4/F5 · the podium ───────────────────────────────────────────────────

print("\nWP11-F3 · the podium comes from the bracket, never from a score")
board = podium(_State(third_place_matchup=DECIDED_THIRD))
_assert("first is the provider's champion", board.champion_team_key == KEYS[1])
_assert("  · second is the finalist who is not the champion",
        board.runner_up_team_key == KEYS[2])
_assert("  · third is the winner of the official third-place game",
        board.third_team_key == KEYS[3])
_assert("  · and the podium is always exactly three names",
        len(board.ordered_keys) == 3, str(board.ordered_keys))

print("\nWP11-F4 · a tied final is an UNDECIDED game, not a dead heat")
tied_final = _State(complete=True, champion_team_key=None)
_assert("a complete bracket with no champion is NOT_COMPLETE",
        provider_finality(tied_final).status == FINALITY_NOT_COMPLETE)
_assert("  · and says a tied final is an undecided game",
        any("not a dead heat" in r
            for r in provider_finality(tied_final).reasons),
        str(provider_finality(tied_final).reasons))
try:
    podium(_State(third_place_matchup=TIED_THIRD))
    _assert("  · an undecided third-place game refuses", False, "accepted")
except FFChampionshipError as exc:
    _assert("  · an undecided third-place game refuses",
            exc.reason == "FF_PROVIDER_FINALITY_BLOCKED", exc.reason)

print("\nWP11-F5 · no decided third place REFUSES rather than partly paying")
try:
    podium(_State(third_place_matchup=None))
    _assert("a bracket naming no third-place game refuses", False, "accepted")
except FFChampionshipError as exc:
    _assert("a bracket naming no third-place game refuses",
            exc.reason == "FF_PROVIDER_FINALITY_BLOCKED", exc.reason)
    # THE REFUSAL'S REASON CHANGED UNDER THE OWNER RULING, and the change is
    # the point. It used to say "a two-name podium cannot be paid because §17
    # must conserve the pot"; a two-name podium CAN now be paid, at 67/33, but
    # only when the FORMAT has no third-place game. A four-team format that
    # cannot show one is a provider gap, and the message now says exactly that
    # -- naming the field size, so an operator can tell the two apart.
    _assert("  · and explains that this FORMAT has a third place to pay",
            "HAS an official third-place game" in str(exc), str(exc)[:140])

# The reason this refuses rather than paying 60/30: the canonical splitter
# itself will not conserve a two-name podium. Demonstrated directly.
from economy.championship_distribution import (  # noqa: E402
    distribute_championship, podium_standings,
)

try:
    distribute_championship(POT, podium_standings([1, 2]))
    _assert("  · the canonical split would not have conserved it anyway",
            False, "it conserved")
except AssertionError as exc:
    _assert("  · the canonical split would not have conserved it anyway",
            "must conserve the pot exactly" in str(exc), str(exc)[:70])


# ── F6/F7 · the payment ─────────────────────────────────────────────────────

print("\nWP11-F6 · a stated bracket pays 60/30/10 and conserves")
result = settle(db, league_id=LEAGUE, state=_State(
    third_place_matchup=DECIDED_THIRD), now=NOW)
db.commit()
by_team = {t: (place, amount) for t, place, amount in result.placements}

_assert("the pot paid is the whole minted pot", result.pot_cents == POT,
        str(result.pot_cents))
_assert("  · first place takes 60%", by_team[1][1] == 6_000,
        str(by_team[1][1]))
_assert("  · second takes 30%", by_team[2][1] == 3_000, str(by_team[2][1]))
_assert("  · third takes 10%", by_team[3][1] == 1_000, str(by_team[3][1]))
_assert("  · the places are 1, 2, 3",
        [by_team[t][0] for t in (1, 2, 3)] == [1, 2, 3],
        str([by_team[t][0] for t in (1, 2, 3)]))
_assert("  · the awards total exactly the pot", result.paid_cents == POT,
        str(result.paid_cents))
_assert("  · no dead heat is reported — a knockout has no tie",
        len({p for _t, p, _a in result.placements}) == 3,
        str([p for _t, p, _a in result.placements]))
_assert("  · every award reached a Wallet",
        all(_bal(db, f"wallet:{t}") == by_team[t][1] for t in (1, 2, 3)),
        str({t: _bal(db, f"wallet:{t}") for t in TEAMS}))
_assert("  · the fourth GM was paid nothing", _bal(db, "wallet:4") == 0)
_assert("  · the pot account is drained", _bal(db, ACCOUNT) == 0,
        str(_bal(db, ACCOUNT)))
_assert("  · and the global trial balance is zero",
        ledger_module.trial_balance() == 0,
        str(ledger_module.trial_balance()))

print("\nWP11-F7 · the provider gate runs BEFORE the pot is read")
unfunded = _build(mint=False)
_assert("the pot really is empty",
        pot_cents(unfunded, league_id=LEAGUE, season=SEASON) == 0)
try:
    settle(unfunded, league_id=LEAGUE, state=None, now=NOW)
    _assert("  · a blocked bracket on an EMPTY pot reports BLOCKED", False,
            "accepted")
except FFChampionshipError as exc:
    unfunded.rollback()
    _assert("  · a blocked bracket on an EMPTY pot reports BLOCKED",
            exc.reason == "FF_PROVIDER_FINALITY_BLOCKED", exc.reason)
try:
    settle(unfunded, league_id=LEAGUE,
           state=_State(third_place_matchup=DECIDED_THIRD), now=NOW)
    _assert("  · while a STATED bracket on an empty pot reports EMPTY_POT",
            False, "accepted")
except FFChampionshipError as exc:
    unfunded.rollback()
    _assert("  · while a STATED bracket on an empty pot reports EMPTY_POT",
            exc.reason == "FF_EMPTY_POT", exc.reason)
_assert("  · so an operator is never shown EMPTY_POT for a provider problem",
        True)


# ── F8/F9 · identity, exactly-once, era ────────────────────────────────────

print("\nWP11-F8 · an unresolvable provider key refuses rather than guessing")
unbound = _build(bind=False)
try:
    settle(unbound, league_id=LEAGUE,
           state=_State(third_place_matchup=DECIDED_THIRD), now=NOW)
    _assert("an unbound league refuses", False, "accepted")
except Exception as exc:
    unbound.rollback()
    _assert("an unbound league refuses",
            "provider identity" in str(exc) or "FF_UNRESOLVED_TEAM" in str(exc),
            str(exc)[:90])
_assert("  · and paid nobody",
        all(_bal(unbound, f"wallet:{t}") == 0 for t in TEAMS))

print("\nWP11-F9 · exactly-once, and the legacy era is refused")
wallets = {t: _bal(db, f"wallet:{t}") for t in TEAMS}
try:
    settle(db, league_id=LEAGUE,
           state=_State(third_place_matchup=DECIDED_THIRD), now=NOW)
    _assert("a replay is refused rather than paying twice", False, "accepted")
except Exception as exc:
    db.rollback()
    _assert("a replay is refused rather than paying twice", True,
            type(exc).__name__)
_assert("  · and no Wallet moved",
        {t: _bal(db, f"wallet:{t}") for t in TEAMS} == wallets,
        str({t: _bal(db, f"wallet:{t}") for t in TEAMS}))
_assert("  · exactly one distribution event exists for this pillar",
        db.execute(text(
            "SELECT COUNT(*) FROM economy_event WHERE event_key LIKE :k"),
            {"k": "CHAMPIONSHIP_DISTRIBUTION:fantasy_football:%"}).scalar()
        == 1)

old = _build(final_por=False)
try:
    settle(old, league_id=LEAGUE,
           state=_State(third_place_matchup=DECIDED_THIRD), now=NOW)
    _assert("  · a LEGACY season is refused", False, "accepted")
except FFChampionshipError as exc:
    old.rollback()
    _assert("  · a LEGACY season is refused", exc.reason == "FF_WRONG_ERA",
            exc.reason)


# ── F10 · nothing here invents a bracket fact ──────────────────────────────

print("\nWP11-F10 · nothing here reads a payload or classifies a matchup")
import economy.ff_championship_settlement as ffs  # noqa: E402

src = inspect.getsource(ffs)
_assert("no provider client is imported",
        not any(token in src for token in
                ("yfpy", "providers.yahoo", "import requests", "httpx")))
_assert("  · no Matchup score is read",
        "home_score" not in src and "away_score" not in src)
# WALKED AS AN AST, NOT GREPPED. The module's own prose explains §19's
# classification rule and names it, so a text search finds the explanation
# rather than a call — which is how this assertion first failed while the code
# was correct. Attribute and name nodes are code and only code.
import ast  # noqa: E402

_tree = ast.parse(src)
_referenced = {n.attr for n in ast.walk(_tree) if isinstance(n, ast.Attribute)}
_referenced |= {n.id for n in ast.walk(_tree) if isinstance(n, ast.Name)}
_CLASSIFIERS = {"is_affirmatively_championship", "MatchupBracket",
                "_classify_week", "_championship_matchups",
                "_identify_third_place"}
_assert("  · no matchup classifier is called here",
        not (_referenced & _CLASSIFIERS), str(sorted(_referenced & _CLASSIFIERS)))
_assert("  · and no season.championship_track internal is imported",
        not any(isinstance(n, (ast.Import, ast.ImportFrom))
                and "championship_track" in (getattr(n, "module", "") or "")
                for n in ast.walk(_tree)))
_assert("  · the winner is taken from the provider's own declaration",
        "winner_team_key" in src)
_assert("  · and the decided predicate is the track's, not a local one",
        "is_decided" in src and "def is_decided" not in src)
_assert("  · finality is derived from the supplied state alone",
        "def provider_finality(state)" in src)


# -- F11 . the two-team playoff exception ------------------------------------

print("\nWP11-F11 " + chr(0x00b7) + " a TWO-TEAM playoff pays 67/33")

TWO_TEAM = _State(
    championship_field_team_keys=frozenset({KEYS[1], KEYS[2]}),
    third_place_matchup=None)

_assert("the official field size is read from the provider's declaration",
        official_field_size(TWO_TEAM) == 2,
        str(official_field_size(TWO_TEAM)))
_assert("  . and a two-team format is recognised as one",
        is_two_team_playoff(TWO_TEAM) is True)
_assert("  . while a four-team format is not",
        is_two_team_playoff(_State()) is False)

two = podium(TWO_TEAM)
_assert("a two-team podium names exactly two finishers",
        two.ordered_keys == (KEYS[1], KEYS[2]), str(two.ordered_keys))
_assert("  . with no third place at all", two.third_team_key is None)
_assert("  . declared as the two-team structure",
        two.structure == STRUCTURE_TWO_TEAM, two.structure)
_assert("  . and it takes the 67/33 split",
        two.split == TWO_TEAM_PLAYOFF_SPLIT, str(two.split))
_assert("  . which is a governed constant summing to 100",
        sum(TWO_TEAM_PLAYOFF_SPLIT) == 100
        and TWO_TEAM_PLAYOFF_SPLIT == (67, 33), str(TWO_TEAM_PLAYOFF_SPLIT))

two_db = _build()
two_result = settle(two_db, league_id=LEAGUE, state=TWO_TEAM, now=NOW)
two_db.commit()
two_by = {t: (place, amount) for t, place, amount in two_result.placements}

_assert("the champion takes 67% of a 10000 pot",
        two_by[1][1] == 6_700, str(two_by[1][1]))
_assert("  . the runner-up takes 33%", two_by[2][1] == 3_300,
        str(two_by[2][1]))
_assert("  . nobody else is paid",
        all(t not in two_by for t in (3, 4)), str(sorted(two_by)))
_assert("  . the whole pot is conserved", two_result.paid_cents == POT,
        f"{two_result.paid_cents} of {POT}")
_assert("  . the pot account is drained",
        _bal(two_db, ACCOUNT) == 0, str(_bal(two_db, ACCOUNT)))
_assert("  . the trial balance is zero",
        ledger_module.trial_balance() == 0)
_assert("  . and the result SAYS which structure paid, so nobody infers it",
        two_result.structure == STRUCTURE_TWO_TEAM
        and tuple(two_result.split) == TWO_TEAM_PLAYOFF_SPLIT
        and two_result.field_size == 2,
        f"{two_result.structure} {two_result.split} field={two_result.field_size}")

# An indivisible pot still conserves, and the remainder goes to first.
from economy.championship_distribution import (  # noqa: E402
    distribute_championship as _dist, podium_standings as _pods,
)

for odd_pot in (999, 1, 3, 12_345):
    parts = _dist(odd_pot, _pods([1, 2]), split=TWO_TEAM_PLAYOFF_SPLIT)
    _assert(f"  . a pot of {odd_pot} conserves exactly under 67/33",
            sum(p.amount_cents for p in parts) == odd_pot,
            str([p.amount_cents for p in parts]))
_assert("  . and an exact two-way dead heat pools 67+33 and splits it",
        [p.amount_cents for p in _dist(1_000, ((7, 5), (8, 5)),
                                       split=TWO_TEAM_PLAYOFF_SPLIT)]
        == [500, 500])


# -- F12 . the exception is NOT a fallback for missing data ------------------

print("\nWP11-F12 " + chr(0x00b7) + " missing third-place data NEVER triggers 67/33")

for label, state in (
    ("a four-team format with NO third-place game",
     _State(third_place_matchup=None)),
    ("a four-team format whose third-place game is UNDECIDED",
     _State(third_place_matchup=TIED_THIRD)),
    ("a six-team format with no third-place game",
     _State(championship_field_team_keys=frozenset(
         {KEYS[1], KEYS[2], KEYS[3], KEYS[4], "k5", "k6"}),
        third_place_matchup=None)),
    ("a THREE-team format with no third-place game",
     _State(championship_field_team_keys=frozenset(
         {KEYS[1], KEYS[2], KEYS[3]}), third_place_matchup=None)),
):
    guard = _build()
    try:
        settle(guard, league_id=LEAGUE, state=state, now=NOW)
        _assert(f"{label} is refused", False, "accepted -- it paid something")
    except FFChampionshipError as exc:
        guard.rollback()
        _assert(f"{label} is refused",
                exc.reason == "FF_PROVIDER_FINALITY_BLOCKED", exc.reason)
    _assert("  . and paid nobody",
            all(_bal(guard, f"wallet:{t}") == 0 for t in TEAMS)
            and _bal(guard, ACCOUNT) == POT,
            f"pot={_bal(guard, ACCOUNT)}")

# THE REFUSAL SAYS WHY, naming the field size, so an operator can tell a
# structural exception apart from a provider gap without reading the code.
gap = _build()
try:
    settle(gap, league_id=LEAGUE, state=_State(third_place_matchup=None),
           now=NOW)
except FFChampionshipError as exc:
    gap.rollback()
    _assert("the refusal names the field size that requires a third place",
            "4 teams" in str(exc), str(exc)[:120])
    _assert("  . and says paying 67/33 would be a permanent raise",
            "permanent raise" in str(exc), str(exc)[:200])

# An UNKNOWN field size is BLOCKED, and is a DIFFERENT refusal from a gap.
unknown_field = _build()
try:
    settle(unknown_field, league_id=LEAGUE,
           state=_State(championship_field_team_keys=frozenset()), now=NOW)
    _assert("an unknown field size is refused", False, "accepted")
except FFChampionshipError as exc:
    unknown_field.rollback()
    _assert("an unknown field size is refused",
            exc.reason == "FF_FIELD_SIZE_UNKNOWN", exc.reason)
    _assert("  . by its own reason code, not the third-place one",
            exc.reason != "FF_PROVIDER_FINALITY_BLOCKED")

_assert("the standard split is untouched at 60/30/10",
        CHAMPIONSHIP_SPLIT == (60, 30, 10), str(CHAMPIONSHIP_SPLIT))
_assert("  . and a four-team settlement still reports it",
        settle(_build(), league_id=LEAGUE,
               state=_State(third_place_matchup=DECIDED_THIRD),
               now=NOW).structure == STRUCTURE_STANDARD)

import economy.ff_championship_settlement as _ffs  # noqa: E402

_src = inspect.getsource(_ffs)
_assert("the structure is decided BEFORE any third-place game is read",
        _src.index("field_size = official_field_size(state)")
        < _src.index('game = getattr(state, "third_place_matchup"'),
        "the third-place question is asked first")
# WALKED AS AN AST, NOT GREPPED. The module's own docstring explains that the
# split is chosen from `structure` RATHER than from `len(ordered_keys)`, so a
# text search finds the explanation and not a call -- which is how this first
# failed while the code was correct.
_ff_tree = ast.parse(_src)
_len_args = [
    getattr(n.args[0], "attr", getattr(n.args[0], "id", ""))
    for n in ast.walk(_ff_tree)
    if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "len" and n.args
]
_assert("  . neither split is derived from a count of podium names",
        not any(a in ("ordered_keys", "team_ids") for a in _len_args),
        str(_len_args))


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-11 Fantasy Football Championship: all assertions passed "
      "(provider bracket finality remains BLOCKED — see the module docstring)")
