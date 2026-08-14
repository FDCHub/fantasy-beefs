"""WP1A — SYNTHETIC provider-NORMALIZED postseason material.

═══════════════════════════════════════════════════════════════════════════════
EVERYTHING IN THIS MODULE IS SYNTHETIC. NOTHING HERE WAS CAPTURED FROM YAHOO.
═══════════════════════════════════════════════════════════════════════════════

WHY THIS IS L2-NORMALIZED AND NOT A RAW PAYLOAD CORPUS, which is the whole
reason the module exists rather than a `build_postseason_corpus.py` beside the
other builders.

The rest of `providers/fixtures/corpus/` is L1 RAW: synthetic bytes shaped to
Yahoo's DOCUMENTED envelope, so that `providers/yahoo/parse.py` is exercised
against a real envelope even though the bytes are invented. That works because
Yahoo's envelope for leagues, teams, scoreboards and rosters IS documented and
IS already parsed.

It does NOT work for the postseason. This repository contains no evidence of how
— or whether — Yahoo distinguishes a championship matchup from a consolation
one. Writing a raw fixture carrying an invented `is_playoffs` or `is_consolation`
field would have manufactured exactly the evidence the WP1A recon reported as
missing, and a parser written against it would have been certified against a
fiction. So no raw postseason payload is written, no Yahoo field name is
invented, and `providers/yahoo/parse.py` is not touched.

WHAT IS CERTIFIED BY THIS MATERIAL, PRECISELY. The championship-track DOMAIN
logic: field determination, bye identification, round derivation, advancement,
elimination, completion, exclusion of consolation and placement games, and every
fail-closed refusal. That logic is provider-independent by construction, so
certifying it on normalized DTOs certifies the same code any provider will
drive. WHAT IS NOT CERTIFIED is that Yahoo can populate `MatchupBracket` at all —
only a CAPTURED Yahoo postseason payload can settle that, and none exists.

TWO LEAGUES, DELIBERATELY UNALIKE. PS12 and PS10 differ in team count, in
championship field size, in playoff start week, in round count and in whether
byes exist. Anything in the domain that quietly assumed Fraser's league passes
PS12 and fails PS10.
"""

from __future__ import annotations

from dataclasses import dataclass, field as _field

from providers.base import (
    Finality,
    MatchupBracket,
    ProviderMatchup,
    derive_matchup_key,
    orient,
)

#: Restated locally so a reader of this module cannot miss it. Identical in
#: meaning to `providers.fixtures.record.SYNTHETIC`.
PROVENANCE = "SYNTHETIC"

PROVIDER = "synthetic"


@dataclass(frozen=True)
class SyntheticPostseasonLeague:
    """One synthetic league's normalized postseason facts.

    Carries NO `ChampionshipTrackInput` and imports nothing from `season/`. The
    dependency runs domain -> providers, and this module stays on the provider
    side of it so the fixtures cannot quietly encode a domain assumption.
    """

    league_key: str
    season: int
    playoff_start_week: int
    season_final_week: int
    team_count: int
    playoff_team_count: int
    championship_field: frozenset[str]
    #: week -> every matchup the provider reported for it, both brackets mixed.
    weeks: dict[int, tuple[ProviderMatchup, ...]] = _field(default_factory=dict)

    def team_key(self, ordinal: int) -> str:
        return f"{self.league_key}.t.{ordinal}"

    def weeks_through(self, week: int) -> dict[int, tuple[ProviderMatchup, ...]]:
        return {w: ms for w, ms in self.weeks.items() if w <= week}


def matchup(league_key: str, week: int, a: str, b: str, *,
            bracket: MatchupBracket,
            finality: Finality = Finality.NOT_FINAL,
            winner: str | None = None,
            home_points: float | None = None,
            away_points: float | None = None,
            is_tied: bool = False) -> ProviderMatchup:
    """One normalized matchup, oriented by the certified canonical rule.

    Orientation and key derivation go through `providers/base.py` rather than
    being spelled out here, so a fixture cannot drift from the identity rule the
    rest of the provider layer uses — and so a test that shuffles the two team
    arguments produces a byte-identical matchup key, which is what makes the
    determinism case meaningful rather than tautological.
    """
    home, away = orient([a, b])
    return ProviderMatchup(
        provider=PROVIDER,
        league_key=league_key,
        matchup_key=derive_matchup_key(league_key, week, home, away),
        week=week,
        home_team_key=home,
        away_team_key=away,
        home_points=home_points,
        away_points=away_points,
        finality=finality,
        winner_team_key=winner,
        is_tied=is_tied,
        bracket=bracket,
    )


def _final(league_key: str, week: int, a: str, b: str, *,
           bracket: MatchupBracket, winner: str) -> ProviderMatchup:
    """A completed matchup whose winner the provider declared.

    Scores are supplied and are deliberately NOT the basis of anything: the
    winner is stated separately, and `season/championship_track.py` reads only
    the statement. `ps12_declared_winner_contradicts_score()` below turns that
    into an explicit proof rather than a claim.
    """
    home, _away = orient([a, b])
    winner_is_home = home == winner
    return matchup(
        league_key, week, a, b, bracket=bracket, finality=Finality.FINAL,
        winner=winner,
        home_points=118.5 if winner_is_home else 101.25,
        away_points=101.25 if winner_is_home else 118.5,
    )


# ── PS12 — twelve teams, six-team championship field, byes in round one ───────
#
# Field size six derives THREE rounds and TWO first-round byes. Neither number
# is written here: the fixture states the field and the matchups, and the domain
# derives the shape. If the arithmetic in `round_count_for_field` were wrong,
# the structural cross-check would refuse this fixture rather than pass it.

def ps12() -> SyntheticPostseasonLeague:
    """SYNTHETIC. 12 teams · championship field 6 · playoff start 15 · final 17.

    Seeds 1 and 2 hold first-round byes. Consolation matchups run alongside the
    championship track in every week, and the final week additionally carries a
    third-place placement game — the two cases that must never leak into the
    championship field.
    """
    key = "SYN.l.ps12"
    league = SyntheticPostseasonLeague(
        league_key=key, season=2025,
        playoff_start_week=15, season_final_week=17,
        team_count=12, playoff_team_count=6,
        championship_field=frozenset(f"{key}.t.{n}" for n in (1, 2, 3, 4, 5, 6)),
    )
    t = league.team_key

    # ── Round 1 (week 15). Seeds 3-6 play; seeds 1-2 hold byes and NO matchup
    # row is fabricated for them. Seeds 7-12 play consolation.
    league.weeks[15] = (
        _final(key, 15, t(3), t(6), bracket=MatchupBracket.CHAMPIONSHIP,
               winner=t(3)),
        _final(key, 15, t(4), t(5), bracket=MatchupBracket.CHAMPIONSHIP,
               winner=t(4)),
        _final(key, 15, t(7), t(8), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(7)),
        _final(key, 15, t(9), t(10), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(9)),
        _final(key, 15, t(11), t(12), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(11)),
    )

    # ── Round 2 (week 16). The byes enter; the round-1 winners join them.
    league.weeks[16] = (
        _final(key, 16, t(1), t(4), bracket=MatchupBracket.CHAMPIONSHIP,
               winner=t(1)),
        _final(key, 16, t(2), t(3), bracket=MatchupBracket.CHAMPIONSHIP,
               winner=t(2)),
        _final(key, 16, t(5), t(6), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(5)),
        _final(key, 16, t(7), t(9), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(7)),
        _final(key, 16, t(8), t(11), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(8)),
    )

    # ── Round 3 (week 17). One championship game, plus a THIRD-PLACE PLACEMENT
    # game between the two beaten semi-finalists — teams that are genuinely
    # eliminated from the championship track while still playing a real,
    # provider-reported, points-scoring game. That is the exact shape the
    # "has a matchup / still scoring" conflations get wrong.
    league.weeks[17] = (
        _final(key, 17, t(1), t(2), bracket=MatchupBracket.CHAMPIONSHIP,
               winner=t(1)),
        _final(key, 17, t(3), t(4), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(3)),
        _final(key, 17, t(5), t(7), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(5)),
        _final(key, 17, t(8), t(9), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(8)),
    )
    return league


def ps12_round3_pending() -> SyntheticPostseasonLeague:
    """SYNTHETIC PS12 whose championship game has not been played yet.

    Proves the finalists are identifiable BEFORE a result exists, and that the
    contesting field for the championship week is the same two teams before and
    after — which is the property `championship_subject_team_keys()` promises.
    """
    league = ps12()
    key = league.league_key
    t = league.team_key
    league.weeks[17] = (
        matchup(key, 17, t(1), t(2), bracket=MatchupBracket.CHAMPIONSHIP,
                finality=Finality.NOT_FINAL),
        matchup(key, 17, t(3), t(4), bracket=MatchupBracket.NON_CHAMPIONSHIP,
                finality=Finality.NOT_FINAL),
    )
    return league


def ps12_unclassified_week() -> SyntheticPostseasonLeague:
    """SYNTHETIC PS12 whose round-1 brackets are entirely UNKNOWN.

    THIS IS THE SHAPE OF EVERY LIVE YAHOO LEAGUE TODAY, and the reason it is a
    first-class fixture rather than an afterthought: `providers/yahoo/` cannot
    classify a bracket, so every real refresh produces exactly this. The
    determination must refuse, not fall back to the ten teams that have a
    postseason matchup.
    """
    league = ps12()
    key = league.league_key
    t = league.team_key
    league.weeks[15] = tuple(
        _final(key, 15, t(a), t(b), bracket=MatchupBracket.UNKNOWN,
               winner=t(a))
        for a, b in ((3, 6), (4, 5), (7, 8), (9, 10), (11, 12))
    )
    return league


def ps12_partially_classified_week() -> SyntheticPostseasonLeague:
    """SYNTHETIC PS12 with one round-1 matchup left UNKNOWN.

    The dangerous middle case: enough classification to look answerable, not
    enough to be answerable. The unclassified matchup could be the other
    semi-final, and dropping it would yield a field that is short by two teams
    and internally consistent.
    """
    league = ps12()
    key = league.league_key
    t = league.team_key
    first = list(league.weeks[15])
    first[1] = _final(key, 15, t(4), t(5), bracket=MatchupBracket.UNKNOWN,
                      winner=t(4))
    league.weeks[15] = tuple(first)
    return league


def ps12_orphan_participant() -> SyntheticPostseasonLeague:
    """SYNTHETIC PS12 where a round-2 championship game fields a team that never
    won a round-1 championship game — malformed advancement."""
    league = ps12()
    key = league.league_key
    t = league.team_key
    second = list(league.weeks[16])
    # t(9) was eliminated in the consolation bracket and cannot be here.
    second[1] = _final(key, 16, t(2), t(9), bracket=MatchupBracket.CHAMPIONSHIP,
                       winner=t(2))
    league.weeks[16] = tuple(second)
    return league


def ps12_unresolved_result() -> SyntheticPostseasonLeague:
    """SYNTHETIC PS12 whose round-1 championship game is FINAL with no declared
    winner — the provider says it is over and does not say who won."""
    league = ps12()
    key = league.league_key
    t = league.team_key
    first = list(league.weeks[15])
    first[0] = matchup(key, 15, t(3), t(6),
                       bracket=MatchupBracket.CHAMPIONSHIP,
                       finality=Finality.FINAL, winner=None,
                       home_points=104.4, away_points=104.4, is_tied=True)
    league.weeks[15] = tuple(first)
    return league


def ps12_declared_winner_contradicts_score() -> SyntheticPostseasonLeague:
    """SYNTHETIC PS12 whose round-1 winner scored FEWER points than the loser.

    Nonsense as a fantasy result, and that is the point: the only way to advance
    the correct team is to read `winner_team_key`. Any implementation that
    compares scores advances the wrong team and fails the assertion. There is no
    subtler way to prove a negative.
    """
    league = ps12()
    key = league.league_key
    t = league.team_key
    first = list(league.weeks[15])
    home, _away = orient([t(3), t(6)])
    winner = t(3)
    first[0] = matchup(
        key, 15, t(3), t(6), bracket=MatchupBracket.CHAMPIONSHIP,
        finality=Finality.FINAL, winner=winner,
        # The DECLARED winner is given the LOWER score.
        home_points=1.0 if home == winner else 999.0,
        away_points=999.0 if home == winner else 1.0,
    )
    league.weeks[15] = tuple(first)
    return league


def ps12_ambiguous_third_place() -> SyntheticPostseasonLeague:
    """SYNTHETIC PS12 whose championship week carries TWO games between the
    beaten semi-finalists.

    Nonsense as a bracket, and that is the point: two rows claiming the same
    pair means "the official third-place game" has no deterministic answer, and
    picking either would make eligibility depend on row order. The
    determination must refuse rather than choose.
    """
    league = ps12()
    key = league.league_key
    t = league.team_key
    final = list(league.weeks[17])
    # A second t3-vs-t4 game, distinguished only by being a separate row.
    final.append(matchup(key, 17, t(4), t(3),
                         bracket=MatchupBracket.NON_CHAMPIONSHIP,
                         finality=Finality.NOT_FINAL))
    league.weeks[17] = tuple(final)
    return league


def ps12_no_third_place() -> SyntheticPostseasonLeague:
    """SYNTHETIC PS12 whose championship week plays NO third-place game.

    The two other placement games remain, so this also proves they are not
    promoted in its absence: a week with placement games but no semifinal-loser
    pairing yields finalists-only eligibility, never "whatever placement game
    happens to be there".
    """
    league = ps12()
    losers = {league.team_key(3), league.team_key(4)}
    league.weeks[17] = tuple(
        m for m in league.weeks[17]
        if frozenset((m.home_team_key, m.away_team_key)) != losers)
    return league


# ── PS10 — ten teams, four-team championship field, no byes, later start ──────

def ps10() -> SyntheticPostseasonLeague:
    """SYNTHETIC. 10 teams · championship field 4 · playoff start 16 · final 17.

    DIFFERENT IN EVERY DIMENSION THAT COULD HAVE BEEN HARDCODED: a different
    league size, a different field size, a different playoff start week, a
    different round count, and no byes at all. Field size four derives two
    rounds and zero byes — again, derived, not stated.

    It also exercises the path where no field DECLARATION is needed: round one's
    four participants are the entire field, and `playoff_team_count` confirms
    it, so the field is reconstructed from matchups alone.
    """
    key = "SYN.l.ps10"
    league = SyntheticPostseasonLeague(
        league_key=key, season=2025,
        playoff_start_week=16, season_final_week=17,
        team_count=10, playoff_team_count=4,
        championship_field=frozenset(f"{key}.t.{n}" for n in (1, 2, 3, 4)),
    )
    t = league.team_key

    league.weeks[16] = (
        _final(key, 16, t(1), t(4), bracket=MatchupBracket.CHAMPIONSHIP,
               winner=t(1)),
        _final(key, 16, t(2), t(3), bracket=MatchupBracket.CHAMPIONSHIP,
               winner=t(2)),
        _final(key, 16, t(5), t(6), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(5)),
        _final(key, 16, t(7), t(8), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(7)),
        _final(key, 16, t(9), t(10), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(9)),
    )
    league.weeks[17] = (
        _final(key, 17, t(1), t(2), bracket=MatchupBracket.CHAMPIONSHIP,
               winner=t(2)),
        _final(key, 17, t(3), t(4), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(4)),
        _final(key, 17, t(5), t(7), bracket=MatchupBracket.NON_CHAMPIONSHIP,
               winner=t(5)),
    )
    return league
