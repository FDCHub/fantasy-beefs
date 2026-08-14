"""
test_wp1a_championship_track.py — WP1A certification gate.

No database. No Session. No network. No credentials. No clock.

WHAT THIS PROVES:

    Given a supported league configuration and normalized provider state,
    FantasyStakes deterministically identifies the current championship field
    and championship matchups — without league-size-specific or week-specific
    hardcoding — excluding consolation and placement teams, and failing closed
    when the provider state is insufficient.

WHY TWO UNALIKE LEAGUES. PS12 (12 teams, field 6, start 15, byes) and PS10
(10 teams, field 4, start 16, no byes) differ in every dimension that could have
been quietly hardcoded. A determination that only works for Fraser's league
passes W1A-1 and fails W1A-2.

Runs as: python test_wp1a_championship_track.py
"""

import ast
import io
import os
import sys
import tokenize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from providers.base import Finality, MatchupBracket  # noqa: E402
from providers.fixtures.postseason_synthetic import (  # noqa: E402
    matchup,
    ps10,
    ps12,
    ps12_declared_winner_contradicts_score,
    ps12_orphan_participant,
    ps12_partially_classified_week,
    ps12_round3_pending,
    ps12_unclassified_week,
    ps12_unresolved_result,
)
from season.championship_track import (  # noqa: E402
    REASON_BRACKET_CLASSIFICATION_ABSENT,
    REASON_BYE_TEAMS_UNIDENTIFIED,
    REASON_ORPHAN_PARTICIPANT,
    REASON_PARTIAL_BRACKET_CLASSIFICATION,
    REASON_PLAYOFF_START_WEEK_ABSENT,
    REASON_PLAYOFF_TEAM_COUNT_ABSENT,
    REASON_UNDECIDED_EARLIER_ROUND,
    REASON_UNRESOLVED_RESULT,
    ChampionshipTrackInput,
    ChampionshipWeekInput,
    TrackAuthority,
    derive_championship_track_state,
    first_round_bye_count,
    round_count_for_field,
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


def _input(league, *, through_week: int, declare_field: bool,
           with_team_count: bool = True, reverse: bool = False
           ) -> ChampionshipTrackInput:
    """Assemble the domain input from synthetic normalized provider material.

    `reverse` flips both the week order and the within-week matchup order. It is
    what makes the determinism case a real test rather than a restatement: the
    domain must not read either ordering.
    """
    from season.championship_track import ChampionshipFieldDeclaration

    items = sorted(league.weeks_through(through_week).items(),
                   reverse=reverse)
    weeks = tuple(
        ChampionshipWeekInput(
            week=w,
            matchups=tuple(reversed(ms)) if reverse else tuple(ms))
        for w, ms in items
    )
    declaration = (ChampionshipFieldDeclaration(
        team_keys=league.championship_field) if declare_field else None)
    return ChampionshipTrackInput(
        league_key=league.league_key,
        season=league.season,
        playoff_start_week=league.playoff_start_week,
        season_final_week=league.season_final_week,
        playoff_team_count=(league.playoff_team_count if with_team_count
                            else None),
        weeks=weeks,
        field_declaration=declaration,
    )


def _names(keys) -> list[str]:
    """Team keys reduced to their ordinal tails, for readable failure detail."""
    return sorted(k.rsplit(".", 1)[-1] for k in keys)


# ── W1A-1 · PS12 first round ─────────────────────────────────────────────────

def case_1_ps12_first_round() -> None:
    _section("W1A-1 · PS12 first round — six alive, two byes, derived structure")
    league = ps12()
    state = derive_championship_track_state(
        _input(league, through_week=15, declare_field=True), week=15)

    _assert("1a: authority is PROVIDER_CLASSIFIED",
            state.authority is TrackAuthority.PROVIDER_CLASSIFIED,
            detail=f"{state.authority} reasons={state.insufficiency_reasons}")
    _assert("1b: postseason has begun", state.postseason_started)
    _assert("1c: championship round ordinal is 1",
            state.championship_round_ordinal == 1,
            detail=str(state.championship_round_ordinal))
    _assert("1d: THREE rounds derived from a field of six (not stated)",
            state.round_count_expected == 3,
            detail=str(state.round_count_expected))
    _assert("1e: six teams contest the championship track this week",
            len(state.contesting_team_keys) == 6,
            detail=str(_names(state.contesting_team_keys)))
    _assert("1f: exactly two first-round byes",
            len(state.bye_team_keys) == 2,
            detail=str(_names(state.bye_team_keys)))
    _assert("1g: byes are the two teams with no matchup this round",
            _names(state.bye_team_keys) == ["1", "2"],
            detail=str(_names(state.bye_team_keys)))
    _assert("1h: exactly two championship matchups drawn from five reported",
            len(state.championship_matchups) == 2,
            detail=str(len(state.championship_matchups)))
    _assert("1i: the round-one losers are eliminated once the round is decided",
            _names(state.eliminated_team_keys) == ["5", "6"],
            detail=str(_names(state.eliminated_team_keys)))
    _assert("1j: subject accessor returns the six contesting teams",
            state.championship_subject_team_keys() == state.contesting_team_keys)


# ── W1A-2 · a different league and configuration, same code path ─────────────

def case_2_ps10_different_shape() -> None:
    _section("W1A-2 · PS10 — different size, field, start week and shape")
    league = ps10()
    # NO field declaration: round one's four participants ARE the whole field,
    # and playoff_team_count confirms it. This is the reconstruction path.
    state = derive_championship_track_state(
        _input(league, through_week=16, declare_field=False), week=16)

    _assert("2a: authority is DERIVED (field reconstructed from matchups)",
            state.authority is TrackAuthority.DERIVED,
            detail=f"{state.authority} reasons={state.insufficiency_reasons}")
    _assert("2b: postseason begins at week 16 for THIS league, not week 15",
            state.postseason_started and state.championship_round_ordinal == 1,
            detail=str(state.championship_round_ordinal))
    _assert("2c: TWO rounds derived from a field of four",
            state.round_count_expected == 2,
            detail=str(state.round_count_expected))
    _assert("2d: four teams contest, and there are NO byes",
            len(state.contesting_team_keys) == 4
            and not state.bye_team_keys,
            detail=f"contesting={_names(state.contesting_team_keys)} "
                   f"byes={_names(state.bye_team_keys)}")
    _assert("2e: two championship matchups drawn from five reported",
            len(state.championship_matchups) == 2)
    # The discriminating comparison: the SAME function produced a 6/2-bye/
    # 3-round answer for PS12 and a 4/0-bye/2-round answer here.
    ps12_state = derive_championship_track_state(
        _input(ps12(), through_week=15, declare_field=True), week=15)
    _assert("2f: one code path yields two different shapes",
            (ps12_state.round_count_expected,
             len(ps12_state.bye_team_keys)) == (3, 2)
            and (state.round_count_expected, len(state.bye_team_keys)) == (2, 0))


# ── W1A-3 · first-round byes ─────────────────────────────────────────────────

def case_3_byes() -> None:
    _section("W1A-3 · byes are alive and no matchup is fabricated for them")
    league = ps12()
    state = derive_championship_track_state(
        _input(league, through_week=15, declare_field=True), week=15)
    byes = state.bye_team_keys

    _assert("3a: bye teams are championship-alive this week",
            byes <= state.contesting_team_keys and len(byes) == 2,
            detail=str(_names(byes)))
    played = {k for m in state.championship_matchups for k in m.team_keys}
    _assert("3b: NO championship matchup was fabricated for a bye team",
            not (byes & played), detail=str(_names(byes & played)))
    _assert("3c: bye teams are not eliminated",
            not (byes & state.eliminated_team_keys))
    _assert("3d: byes advance to round two without playing",
            byes <= derive_championship_track_state(
                _input(league, through_week=16, declare_field=True),
                week=16).contesting_team_keys)


# ── W1A-4 · a later round after eliminations ─────────────────────────────────

def case_4_later_round() -> None:
    _section("W1A-4 · round two — winners and byes advance, losers eliminated")
    league = ps12()
    state = derive_championship_track_state(
        _input(league, through_week=16, declare_field=True), week=16)

    _assert("4a: round ordinal is 2", state.championship_round_ordinal == 2,
            detail=str(state.championship_round_ordinal))
    _assert("4b: the field contracted from six to four",
            _names(state.contesting_team_keys) == ["1", "2", "3", "4"],
            detail=str(_names(state.contesting_team_keys)))
    _assert("4c: round-one losers stayed eliminated",
            {"5", "6"} <= set(_names(state.eliminated_team_keys)),
            detail=str(_names(state.eliminated_team_keys)))
    _assert("4d: no byes remain in a full round",
            not state.bye_team_keys, detail=str(_names(state.bye_team_keys)))
    _assert("4e: after round two, two teams remain alive",
            _names(state.alive_team_keys) == ["1", "2"],
            detail=str(_names(state.alive_team_keys)))
    _assert("4f: finalists are NOT yet claimed at round two",
            state.finalist_team_keys == (),
            detail=str(state.finalist_team_keys))


# ── W1A-5 · championship week ────────────────────────────────────────────────

def case_5_championship_week() -> None:
    _section("W1A-5 · championship week — finalists identified")
    played = derive_championship_track_state(
        _input(ps12(), through_week=17, declare_field=True), week=17)
    pending = derive_championship_track_state(
        _input(ps12_round3_pending(), through_week=17, declare_field=True),
        week=17)

    _assert("5a: finalists identified once the deciding round is reached",
            _names(played.finalist_team_keys) == ["1", "2"],
            detail=str(played.finalist_team_keys))
    _assert("5b: finalists identified BEFORE the game is played",
            _names(pending.finalist_team_keys) == ["1", "2"],
            detail=str(pending.finalist_team_keys))
    _assert("5c: the contesting field for the week is identical before and "
            "after the result — settlement asks second",
            pending.contesting_team_keys == played.contesting_team_keys,
            detail=f"{_names(pending.contesting_team_keys)} vs "
                   f"{_names(played.contesting_team_keys)}")
    _assert("5d: subject accessor is stable across the result landing",
            pending.championship_subject_team_keys()
            == played.championship_subject_team_keys())
    _assert("5e: an unplayed final is not complete",
            not pending.complete and pending.champion_team_key is None)


# ── W1A-6 · completed championship ───────────────────────────────────────────

def case_6_complete() -> None:
    _section("W1A-6 · completed championship — champion identified")
    state = derive_championship_track_state(
        _input(ps12(), through_week=17, declare_field=True), week=17)

    _assert("6a: complete is True", state.complete)
    _assert("6b: champion is the declared winner of the final",
            _names([state.champion_team_key]) == ["1"],
            detail=str(state.champion_team_key))
    _assert("6c: exactly one team remains alive",
            len(state.alive_team_keys) == 1,
            detail=str(_names(state.alive_team_keys)))
    _assert("6d: the other five field teams are eliminated",
            len(state.eliminated_team_keys) == 5,
            detail=str(_names(state.eliminated_team_keys)))

    ten = derive_championship_track_state(
        _input(ps10(), through_week=17, declare_field=False), week=17)
    _assert("6e: PS10 completes in TWO rounds with its own champion",
            ten.complete and _names([ten.champion_team_key]) == ["2"]
            and ten.round_count_expected == 2,
            detail=f"{ten.champion_team_key} rounds={ten.round_count_expected}")


# ── W1A-7 · consolation matchups ─────────────────────────────────────────────

def case_7_consolation() -> None:
    _section("W1A-7 · consolation is never championship")
    league = ps12()
    consolation_teams = {league.team_key(n) for n in (7, 8, 9, 10, 11, 12)}

    for week in (15, 16, 17):
        state = derive_championship_track_state(
            _input(league, through_week=week, declare_field=True), week=week)
        drawn = {k for m in state.championship_matchups for k in m.team_keys}
        _assert(f"7a.w{week}: no consolation team appears in a championship "
                f"matchup", not (drawn & consolation_teams),
                detail=str(_names(drawn & consolation_teams)))
        _assert(f"7b.w{week}: no consolation team is championship-alive",
                not (state.contesting_team_keys & consolation_teams))
        _assert(f"7c.w{week}: no consolation team entered the field",
                not (state.championship_field_team_keys & consolation_teams))

    # The conflation this exists to defeat, stated as an assertion: every one of
    # those teams HAS a provider matchup in week 15 and scores real points.
    reported = {k for m in league.weeks[15]
                for k in (m.home_team_key, m.away_team_key)}
    _assert("7d: the excluded teams DO have provider matchups that week — "
            "'has a matchup' is not 'is on the championship track'",
            consolation_teams <= reported,
            detail=str(_names(consolation_teams - reported)))


# ── W1A-8 · placement / third-place game ─────────────────────────────────────

def case_8_placement() -> None:
    _section("W1A-8 · a third-place placement game is not championship")
    league = ps12()
    state = derive_championship_track_state(
        _input(league, through_week=17, declare_field=True), week=17)
    beaten_semifinalists = {league.team_key(3), league.team_key(4)}

    drawn = {k for m in state.championship_matchups for k in m.team_keys}
    _assert("8a: the third-place game is not a championship matchup",
            not (drawn & beaten_semifinalists),
            detail=str(_names(drawn & beaten_semifinalists)))
    _assert("8b: its participants are eliminated, not contesting",
            beaten_semifinalists <= state.eliminated_team_keys
            and not (beaten_semifinalists & state.contesting_team_keys))
    _assert("8c: exactly one championship matchup in the final week",
            len(state.championship_matchups) == 1,
            detail=str(len(state.championship_matchups)))
    _assert("8d: they were in the FIELD — eliminated is not 'never entered'",
            beaten_semifinalists <= state.championship_field_team_keys)


# ── W1A-9 · missing bracket authority ────────────────────────────────────────

def case_9_missing_bracket_authority() -> None:
    _section("W1A-9 · unclassified brackets fail closed")
    absent = derive_championship_track_state(
        _input(ps12_unclassified_week(), through_week=15, declare_field=True),
        week=15)

    _assert("9a: authority is UNKNOWN",
            absent.authority is TrackAuthority.UNKNOWN,
            detail=str(absent.authority))
    _assert("9b: the alive set is EMPTY — no fallback to 'all postseason teams'",
            not absent.alive_team_keys and not absent.contesting_team_keys,
            detail=str(_names(absent.contesting_team_keys)))
    _assert("9c: the reason names the missing input",
            REASON_BRACKET_CLASSIFICATION_ABSENT in absent.insufficiency_reasons,
            detail=str(absent.insufficiency_reasons))
    _assert("9d: the subject accessor returns None, not an empty set",
            absent.championship_subject_team_keys() is None)
    _assert("9e: no championship matchups leaked",
            absent.championship_matchups == ())

    partial = derive_championship_track_state(
        _input(ps12_partially_classified_week(), through_week=15,
               declare_field=True), week=15)
    _assert("9f: a PARTIALLY classified week also fails closed",
            partial.authority is TrackAuthority.UNKNOWN
            and REASON_PARTIAL_BRACKET_CLASSIFICATION
            in partial.insufficiency_reasons,
            detail=str(partial.insufficiency_reasons))

    no_boundary = derive_championship_track_state(
        ChampionshipTrackInput(league_key="SYN.l.x", season=2025,
                               playoff_start_week=None), week=15)
    _assert("9g: an absent playoff_start_week fails closed",
            no_boundary.authority is TrackAuthority.UNKNOWN
            and REASON_PLAYOFF_START_WEEK_ABSENT
            in no_boundary.insufficiency_reasons,
            detail=str(no_boundary.insufficiency_reasons))


# ── W1A-10 · missing playoff field size ──────────────────────────────────────

def case_10_missing_field_size() -> None:
    _section("W1A-10 · absent field size — refuse, never guess a round count")
    state = derive_championship_track_state(
        _input(ps12(), through_week=15, declare_field=False,
               with_team_count=False), week=15)

    _assert("10a: round count is NOT guessed",
            state.round_count_expected is None,
            detail=str(state.round_count_expected))
    _assert("10b: authority is UNKNOWN",
            state.authority is TrackAuthority.UNKNOWN)
    _assert("10c: both missing inputs are named",
            REASON_PLAYOFF_TEAM_COUNT_ABSENT in state.insufficiency_reasons
            and REASON_BYE_TEAMS_UNIDENTIFIED in state.insufficiency_reasons,
            detail=str(state.insufficiency_reasons))
    _assert("10d: the four teams that DID play round one were not mistaken "
            "for the whole field",
            not state.championship_field_team_keys)


# ── W1A-11 · malformed advancement ───────────────────────────────────────────

def case_11_malformed() -> None:
    _section("W1A-11 · malformed advancement fails closed")
    orphan = derive_championship_track_state(
        _input(ps12_orphan_participant(), through_week=16, declare_field=True),
        week=16)
    _assert("11a: a round-two team that won no round-one game is refused",
            orphan.authority is TrackAuthority.UNKNOWN
            and REASON_ORPHAN_PARTICIPANT in orphan.insufficiency_reasons,
            detail=str(orphan.insufficiency_reasons))

    unresolved = derive_championship_track_state(
        _input(ps12_unresolved_result(), through_week=15, declare_field=True),
        week=15)
    _assert("11b: FINAL with no declared winner is refused, not scored",
            unresolved.authority is TrackAuthority.UNKNOWN
            and REASON_UNRESOLVED_RESULT in unresolved.insufficiency_reasons,
            detail=str(unresolved.insufficiency_reasons))

    # An undecided round one, asked about round two.
    league = ps12()
    league.weeks[15] = tuple(
        matchup(league.league_key, 15, m.home_team_key, m.away_team_key,
                bracket=m.bracket, finality=Finality.NOT_FINAL)
        for m in league.weeks[15])
    stale = derive_championship_track_state(
        _input(league, through_week=16, declare_field=True), week=16)
    _assert("11c: an undecided EARLIER round is refused, not carried forward",
            stale.authority is TrackAuthority.UNKNOWN
            and REASON_UNDECIDED_EARLIER_ROUND in stale.insufficiency_reasons,
            detail=str(stale.insufficiency_reasons))

    # The negative that cannot be proved any other way.
    contradicted = derive_championship_track_state(
        _input(ps12_declared_winner_contradicts_score(), through_week=15,
               declare_field=True), week=15)
    _assert("11d: advancement follows the DECLARED winner, never the score",
            _names(contradicted.alive_team_keys) == ["1", "2", "3", "4"],
            detail=str(_names(contradicted.alive_team_keys)))


# ── W1A-12 · determinism ─────────────────────────────────────────────────────

def case_12_determinism() -> None:
    _section("W1A-12 · determinism under input reordering")
    for label, league, declare in (("PS12", ps12(), True),
                                   ("PS10", ps10(), False)):
        week = league.season_final_week
        forward = derive_championship_track_state(
            _input(league, through_week=week, declare_field=declare), week=week)
        reversed_ = derive_championship_track_state(
            _input(league, through_week=week, declare_field=declare,
                   reverse=True), week=week)
        _assert(f"12a.{label}: reordered weeks and matchups produce an EQUAL "
                f"state", forward == reversed_,
                detail="states differ" if forward != reversed_ else "")
        _assert(f"12b.{label}: repeated evaluation is stable",
                forward == derive_championship_track_state(
                    _input(league, through_week=week, declare_field=declare),
                    week=week))


# ── W1A-13 · structural protections ──────────────────────────────────────────

_DOMAIN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "season", "championship_track.py")
_FORBIDDEN_ROOTS = {"betting", "economy", "ledger", "beefs", "wallet", "db",
                    "sqlalchemy", "requests", "urllib", "yfpy"}
#: League sizes, field sizes and week numbers that must never appear as a
#: literal in the domain. A structure that emerges from arithmetic contains none
#: of them; a structure that was written down contains at least one.
_BANNED_LITERALS = {"4", "6", "8", "10", "12", "14", "15", "16", "17"}


def case_13_structural() -> None:
    _section("W1A-13 · no hardcoding, no forbidden imports, no clock")
    with open(_DOMAIN, encoding="utf-8") as handle:
        raw = handle.read()

    numbers = [tok.string for tok in
               tokenize.generate_tokens(io.StringIO(raw).readline)
               if tok.type == tokenize.NUMBER]
    hits = sorted({n for n in numbers if n in _BANNED_LITERALS})
    _assert("13a: no league-size, field-size or week literal in the domain "
            "(comments and docstrings excluded by tokenize)",
            not hits, detail=f"literals present: {hits}" if hits else "none")

    offenders: list[str] = []
    for dirpath, _dirs, files in os.walk(os.path.dirname(_DOMAIN)):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    roots = [(node.module or "").split(".")[0]]
                else:
                    continue
                for root in roots:
                    if root in _FORBIDDEN_ROOTS:
                        offenders.append(f"{name}:{root}")
    _assert("13b: season/ imports no betting, economy, ledger, beefs, wallet, "
            "db, ORM or network module", not offenders,
            detail=str(offenders) if offenders else "none")

    code = " ".join(
        tok.string for tok in
        tokenize.generate_tokens(io.StringIO(raw).readline)
        if tok.type not in (tokenize.COMMENT, tokenize.STRING))
    banned = [w for w in ("random", "shuffle", "now", "utcnow", "time", "hash")
              if w in code.split()]
    _assert("13c: the determination consults no clock and no randomness",
            not banned, detail=str(banned) if banned else "none")

    # The arithmetic itself, exercised across shapes the fixtures do not use —
    # so the derivation is proved general rather than tuned to two leagues.
    shapes = {n: (round_count_for_field(n), first_round_bye_count(n))
              for n in (2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 16)}
    expected = {2: (1, 0), 3: (2, 1), 4: (2, 0), 5: (3, 3), 6: (3, 2),
                7: (3, 1), 8: (3, 0), 9: (4, 7), 10: (4, 6), 12: (4, 4),
                16: (4, 0)}
    _assert("13d: round and bye arithmetic is correct for every field size "
            "from 2 to 16", shapes == expected,
            detail=str({k: v for k, v in shapes.items()
                        if expected.get(k) != v}))
    raised = False
    try:
        round_count_for_field(1)
    except ValueError:
        raised = True
    _assert("13e: a field of one is refused rather than bracketed", raised)


# ── W1A-14 · the phase/track distinction, and the pre-postseason answer ──────

def case_14_phase_is_not_track() -> None:
    _section("W1A-14 · POSTSEASON phase is not CHAMPIONSHIP track")
    league = ps12()
    before = derive_championship_track_state(
        _input(league, through_week=15, declare_field=True), week=14)

    _assert("14a: a regular-season week reports the postseason as not begun",
            not before.postseason_started)
    _assert("14b: and returns None from the subject accessor — 'not started' "
            "is not 'nobody is eligible'",
            before.championship_subject_team_keys() is None)
    _assert("14c: it is an ANSWER, not a refusal",
            before.authority.is_authoritative
            and before.insufficiency_reasons == ())

    # Ten of twelve teams are in the postseason PHASE in week 15; six are on the
    # championship TRACK. That gap is the whole reason this package exists.
    week15 = derive_championship_track_state(
        _input(league, through_week=15, declare_field=True), week=15)
    in_phase = {k for m in league.weeks[15]
                for k in (m.home_team_key, m.away_team_key)}
    _assert("14d: postseason-phase participants strictly exceed the "
            "championship field",
            len(in_phase) == 10 and len(week15.contesting_team_keys) == 6,
            detail=f"phase={len(in_phase)} track="
                   f"{len(week15.contesting_team_keys)}")

    # A placement-only week after the track has finished.
    ten = ps10()
    ten.weeks[17] = tuple(m for m in ten.weeks[17]
                          if not m.bracket.is_affirmatively_championship)
    ten.weeks[16] = (
        matchup(ten.league_key, 16, ten.team_key(1), ten.team_key(2),
                bracket=MatchupBracket.CHAMPIONSHIP, finality=Finality.FINAL,
                winner=ten.team_key(1)),
    )
    tail = derive_championship_track_state(
        _input(ten, through_week=17, declare_field=True), week=17)
    _assert("14e: a placement-only week hosts no championship round",
            tail.championship_round_ordinal is None
            and tail.championship_matchups == (),
            detail=str(tail.championship_round_ordinal))
    _assert("14f: and yields no subject field for that week",
            tail.championship_subject_team_keys() is None)


# ── W1A-15 · provenance ──────────────────────────────────────────────────────

def case_15_provenance() -> None:
    _section("W1A-15 · provenance names every input consulted")
    declared = derive_championship_track_state(
        _input(ps12(), through_week=16, declare_field=True), week=16)
    reconstructed = derive_championship_track_state(
        _input(ps10(), through_week=16, declare_field=False), week=16)

    _assert("15a: a declared field is reported as declared",
            declared.provenance.field_source == "PROVIDER_DECLARED",
            detail=declared.provenance.field_source)
    _assert("15b: a reconstructed field is reported as reconstructed — the two "
            "claims are not interchangeable",
            reconstructed.provenance.field_source == "DERIVED_FROM_MATCHUPS",
            detail=reconstructed.provenance.field_source)
    _assert("15c: the weeks actually consulted are recorded",
            declared.provenance.weeks_consulted == (15, 16),
            detail=str(declared.provenance.weeks_consulted))
    _assert("15d: an absent input is reported ABSENT, never as a fallback value",
            derive_championship_track_state(
                _input(ps12(), through_week=15, declare_field=False,
                       with_team_count=False), week=15
            ).provenance.playoff_team_count_source == "ABSENT")


# ── W1A-16 · the live-Yahoo default ──────────────────────────────────────────

def case_16_live_yahoo_default() -> None:
    _section("W1A-16 · the default a real Yahoo refresh produces today")
    from providers.base import ProviderMatchup

    plain = ProviderMatchup(
        provider="yahoo", league_key="461.l.488800",
        matchup_key="461.l.488800.w.15.m.a~b", week=15,
        home_team_key="461.l.488800.t.1", away_team_key="461.l.488800.t.2",
        home_points=None, away_points=None, finality=Finality.NOT_FINAL)

    _assert("16a: a matchup constructed without a bracket states UNKNOWN",
            plain.bracket is MatchupBracket.UNKNOWN, detail=str(plain.bracket))
    _assert("16b: UNKNOWN is not affirmatively championship",
            not plain.bracket.is_affirmatively_championship)
    _assert("16c: NON_CHAMPIONSHIP is not affirmatively championship either",
            not MatchupBracket.NON_CHAMPIONSHIP.is_affirmatively_championship)
    _assert("16d: only CHAMPIONSHIP is",
            MatchupBracket.CHAMPIONSHIP.is_affirmatively_championship)

    # End to end: the shape every live league is in right now.
    from providers.yahoo import normalize, parse
    corpus = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "providers", "fixtures", "corpus",
                          "yahoo_scoreboard_w1.json")
    with open(corpus, encoding="utf-8") as handle:
        produced = normalize.normalize_scoreboard(
            parse.parse_scoreboard(handle.read()), week=1)
    _assert("16e: the REAL Yahoo pipeline emits UNKNOWN for every matchup — "
            "no bracket was invented in providers/yahoo/",
            produced and all(m.bracket is MatchupBracket.UNKNOWN
                             for m in produced),
            detail=str([m.bracket for m in produced]))
    _assert("16f: a league of such matchups therefore refuses",
            derive_championship_track_state(
                ChampionshipTrackInput(
                    league_key="461.l.488800", season=2025,
                    playoff_start_week=15, playoff_team_count=6,
                    weeks=(ChampionshipWeekInput(week=15, matchups=produced),)),
                week=15).authority is TrackAuthority.UNKNOWN)


def main() -> None:
    case_1_ps12_first_round()
    case_2_ps10_different_shape()
    case_3_byes()
    case_4_later_round()
    case_5_championship_week()
    case_6_complete()
    case_7_consolation()
    case_8_placement()
    case_9_missing_bracket_authority()
    case_10_missing_field_size()
    case_11_malformed()
    case_12_determinism()
    case_13_structural()
    case_14_phase_is_not_track()
    case_15_provenance()
    case_16_live_yahoo_default()


if __name__ == "__main__":
    print("  WP1A — CHAMPIONSHIP-TRACK CERTIFICATION")
    main()
    print()
    if _failures:
        print(f"RESULT: {len(_failures)} assertion(s) FAILED")
        for label in _failures:
            print(f"  - {label}")
        sys.exit(1)
    print("RESULT: all WP1A championship-track assertions PASSED")
