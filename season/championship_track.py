"""WP1A — the authoritative championship-track primitive.

THE ONE QUESTION THIS MODULE ANSWERS:

    For league L, season S, week W, what is the championship-track state, and
    which teams are still alive on it?

FANTASYSTAKES SUPPORTS EXACTLY ONE POSTSEASON TRACK. Consolation, placement,
third-place and every other bracket a provider may run are out of scope — not
"handled later", but structurally absent: a matchup reaches this module's output
only by being affirmatively classified CHAMPIONSHIP, and every other
classification is dropped before any team enters the field.

── POSTSEASON PHASE IS NOT CHAMPIONSHIP TRACK ────────────────────────────────

This is the distinction the whole package exists to make, and the codebase did
not previously draw it. `betting/pool_season_boundary.phase_for_week` answers
"is week W at or past playoff_start_week", which is a correct and useful WEEK
classification — and it is the only postseason concept the certified baseline
has. It says nothing about who is playing for the title. In a twelve-team league
whose championship field is six, ten of those twelve teams are in the POSTSEASON
PHASE in week 15 and six of them are on the CHAMPIONSHIP TRACK. Reading the
first as the second admits four consolation teams into every downstream
eligibility decision.

That module is deliberately untouched by WP1A. This one sits beside it.

── THE FIVE INFERENCES THAT ARE FORBIDDEN (owner ruling, WP1A §2) ────────────

No path below infers championship membership from:

    1. a team having a matchup in a postseason week — consolation teams have
       matchups, and Yahoo publishes them on the same scoreboard;
    2. a team continuing to score real points — consolation teams score;
    3. a score comparison — the winner is the provider's or nobody's, exactly
       as `providers/yahoo/normalize.py` already rules for the regular season;
    4. the week number — no week is written down in this file;
    5. the league size or the field size — the round structure is ARITHMETIC
       over the field size, never a table of known shapes.

── WHAT THIS COSTS TODAY, STATED PLAINLY ─────────────────────────────────────

`providers/yahoo/` cannot classify a matchup's bracket. There is no evidenced
Yahoo discriminator anywhere in this repository, no captured postseason payload,
and WP1A deliberately did not invent one. So every `ProviderMatchup` a Yahoo
refresh produces today carries `MatchupBracket.UNKNOWN`, and this module
therefore returns `TrackAuthority.UNKNOWN` for every live Yahoo league.

THAT IS THE CORRECT PRODUCTION BEHAVIOUR, NOT A STUB. An UNKNOWN determination
yields NO championship-alive set, so a consumer that honours the contract
refuses rather than guessing. The alternative — shipping a plausible fallback
that admits every postseason team — would pay Pool money to consolation teams
and would do it silently. A refusal is visible; a wrong field is not.

── ALIVE VERSUS CONTESTING: READ THIS BEFORE CONSUMING ───────────────────────

Two team sets are exposed and they are NOT interchangeable:

    contesting_team_keys   alive ENTERING the requested week — the teams whose
                           championship-track season is live THAT WEEK, whether
                           they play or hold a bye. THIS is what a weekly
                           eligibility rule wants.

    alive_team_keys        alive AFTER applying whatever results the requested
                           week has already produced. Once week 17's final is
                           FINAL this is a single team; `contesting` for that
                           same week is still the two finalists.

Asking `alive_team_keys` for a weekly subject field would exclude the team that
lost this week's game AFTER it had already been a legitimate subject for it.
`championship_subject_team_keys()` returns the right one and is the accessor
downstream packages should call.
"""

from __future__ import annotations

from dataclasses import dataclass, field as _field
from datetime import datetime
from enum import Enum

from providers.base import Finality, MatchupBracket, ProviderMatchup

# ── Provenance vocabulary ─────────────────────────────────────────────────────
#
# Named constants rather than bare strings so a provenance value cannot be
# misspelled into silence at one of the assignment sites.

SOURCE_PROVIDER = "PROVIDER"
SOURCE_ABSENT = "ABSENT"
SOURCE_PROVIDER_DECLARED = "PROVIDER_DECLARED"
SOURCE_DERIVED_FROM_MATCHUPS = "DERIVED_FROM_MATCHUPS"
SOURCE_PROVIDER_CLASSIFIED = "PROVIDER_CLASSIFIED"

# ── Insufficiency vocabulary ──────────────────────────────────────────────────
#
# EVERY REFUSAL NAMES ITSELF. An operator asking "why did week 16 refuse?"
# gets the specific missing input, not a bare False — the same reason
# `betting/pool_gates.GateDecision` carries block reasons for every candidate
# including the ones that pass.

REASON_PLAYOFF_START_WEEK_ABSENT = "PLAYOFF_START_WEEK_ABSENT"
REASON_NO_PROVIDER_WEEKS = "NO_PROVIDER_WEEKS"
REASON_WEEK_NOT_SUPPLIED = "WEEK_NOT_SUPPLIED"
REASON_BRACKET_CLASSIFICATION_ABSENT = "BRACKET_CLASSIFICATION_ABSENT"
REASON_PARTIAL_BRACKET_CLASSIFICATION = "PARTIAL_BRACKET_CLASSIFICATION"
REASON_NO_CHAMPIONSHIP_MATCHUPS = "NO_CHAMPIONSHIP_MATCHUPS_CLASSIFIED"
REASON_PLAYOFF_TEAM_COUNT_ABSENT = "PLAYOFF_TEAM_COUNT_ABSENT"
REASON_FIELD_SIZE_NOT_POSITIVE = "FIELD_SIZE_NOT_POSITIVE"
REASON_FIELD_SIZE_CONTRADICTS_DECLARATION = "FIELD_SIZE_CONTRADICTS_DECLARATION"
REASON_BYE_TEAMS_UNIDENTIFIED = "CHAMPIONSHIP_BYE_TEAMS_UNIDENTIFIED"
REASON_ORPHAN_PARTICIPANT = "ORPHAN_CHAMPIONSHIP_PARTICIPANT"
REASON_DUPLICATE_PARTICIPANT = "DUPLICATE_CHAMPIONSHIP_PARTICIPANT"
REASON_UNDECIDED_EARLIER_ROUND = "UNDECIDED_ROUND_PRECEDES_REQUESTED_WEEK"
REASON_UNRESOLVED_RESULT = "CHAMPIONSHIP_RESULT_UNRESOLVED"
REASON_BYE_STRUCTURE_CONTRADICTS = "BYE_STRUCTURE_CONTRADICTS_FIELD_SIZE"
REASON_PREMATURE_COMPLETION = "PREMATURE_CHAMPIONSHIP_COMPLETION"
REASON_AMBIGUOUS_THIRD_PLACE = "AMBIGUOUS_THIRD_PLACE_MATCHUP"


class TrackAuthority(str, Enum):
    """How — and whether — the championship track was determined.

    PROVIDER_CLASSIFIED  the provider classified the brackets AND declared the
                         championship field; nothing was reconstructed
    DERIVED              the provider classified the brackets and the field was
                         reconstructed from them, with the field size
                         independently confirming that reconstruction complete
    UNKNOWN              the track could not be determined

    A TRISTATE, FOR THE THIRD TIME IN THIS CODEBASE AND FOR THE SAME REASON.
    `Finality` keeps "not final" apart from "we could not tell"; `MatchupBracket`
    keeps "consolation" apart from "unclassified"; this keeps "the field is
    reconstructed" apart from "there is no field". Collapsing any of the three
    would put a guess where a refusal belongs.
    """

    PROVIDER_CLASSIFIED = "PROVIDER_CLASSIFIED"
    DERIVED = "DERIVED"
    UNKNOWN = "UNKNOWN"

    @property
    def is_authoritative(self) -> bool:
        """The ONLY predicate a consumer may branch on.

        `authority != UNKNOWN` says the same thing; this reads as the rule, and
        a bare `if authority:` would pass for UNKNOWN because every member of a
        str-Enum is truthy.
        """
        return self is not TrackAuthority.UNKNOWN


# ── Inputs ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChampionshipFieldDeclaration:
    """A provider's statement of WHICH teams entered the championship track.

    WHY THIS CANNOT BE DERIVED FROM MATCHUPS ALONE, which is the single most
    load-bearing fact in this module. In a six-team field the first round has
    two matchups and four participants; the other two teams hold byes and appear
    in NO round-one matchup. Their identity is not recoverable from round one's
    matchups at round one — only from a seeding the provider states, or by
    waiting for round two, which is too late to answer round one's question.

    So a provider that can classify brackets but cannot name the field yields a
    determination that fails closed at round one and can never be rescued by a
    clever inference. `REASON_BYE_TEAMS_UNIDENTIFIED` is that refusal.

    A provider whose field has NO byes needs no declaration: round one's
    participants are the whole field, and `playoff_team_count` confirms it.
    """

    team_keys: frozenset[str]
    source: str = SOURCE_PROVIDER


@dataclass(frozen=True)
class ChampionshipWeekInput:
    """Every matchup a provider reported for one postseason week.

    ALL of them, championship and otherwise. Handing this module a pre-filtered
    championship-only list would move the exclusion decision to the caller and
    make it unauditable — and it would hide exactly the case that matters, where
    a consolation matchup sits beside a championship one on the same scoreboard.
    """

    week: int
    matchups: tuple[ProviderMatchup, ...] = ()


@dataclass(frozen=True)
class ChampionshipTrackInput:
    """Everything the determination reads. Nothing else is consulted.

    `playoff_start_week` is passed IN rather than read from a League row,
    because this package may not import `db` and because the governed fallback
    that `betting/pool_season_boundary.playoff_start_week` applies is an
    economic ruling this domain has no business restating. The caller resolves
    it; this module records in `TrackProvenance` whether it arrived at all.
    """

    league_key: str
    season: int
    playoff_start_week: int | None
    season_final_week: int | None = None
    playoff_team_count: int | None = None
    weeks: tuple[ChampionshipWeekInput, ...] = ()
    field_declaration: ChampionshipFieldDeclaration | None = None
    observed_at: datetime | None = None


# ── Outputs ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChampionshipMatchup:
    """One matchup on the championship track.

    Reached only via `MatchupBracket.is_affirmatively_championship`, so a
    consolation or placement game cannot become one of these by any path.
    """

    matchup_key: str
    home_team_key: str
    away_team_key: str
    round_ordinal: int
    finality: Finality
    winner_team_key: str | None
    is_tied: bool = False

    @property
    def team_keys(self) -> tuple[str, str]:
        return (self.home_team_key, self.away_team_key)

    @property
    def is_decided(self) -> bool:
        """Final AND carrying a provider-declared winner.

        BOTH CONDITIONS, and the second is not redundant. A final tie has no
        winner, and advancing on a score comparison is precisely the inference
        `providers/yahoo/normalize.py` refuses to make at the near end — this
        module must not make it at the far one.
        """
        return self.finality.is_affirmatively_final and bool(self.winner_team_key)


@dataclass(frozen=True)
class TrackProvenance:
    """Which inputs the determination actually consulted, and where each came
    from. Reported for successful determinations too, not only refusals — an
    answer whose field was reconstructed is a different claim from one the
    provider declared, and a reader must be able to tell them apart."""

    playoff_start_week_source: str = SOURCE_ABSENT
    season_final_week_source: str = SOURCE_ABSENT
    playoff_team_count_source: str = SOURCE_ABSENT
    field_source: str = SOURCE_ABSENT
    bracket_source: str = SOURCE_ABSENT
    weeks_consulted: tuple[int, ...] = ()
    observed_at: datetime | None = None


@dataclass(frozen=True)
class ChampionshipTrackState:
    """The complete championship-track answer for one league-season-week."""

    league_key: str
    season: int
    week: int

    postseason_started: bool = False
    championship_round_ordinal: int | None = None
    round_count_expected: int | None = None

    championship_field_team_keys: frozenset[str] = frozenset()
    contesting_team_keys: frozenset[str] = frozenset()
    alive_team_keys: frozenset[str] = frozenset()
    eliminated_team_keys: frozenset[str] = frozenset()
    bye_team_keys: frozenset[str] = frozenset()

    championship_matchups: tuple[ChampionshipMatchup, ...] = ()

    complete: bool = False
    champion_team_key: str | None = None
    finalist_team_keys: tuple[str, ...] = ()

    # ── WP1BC — the official third-place exception ────────────────────────────
    #
    # ADDITIVE, AND EVERY FIELD ABOVE KEEPS ITS MEANING. The two teams playing
    # for third place are ELIMINATED from the championship track and stay in
    # `eliminated_team_keys`; they are not in `contesting_team_keys`, and their
    # game is not in `championship_matchups`. All of that remains true and is
    # still asserted. What WP1BC adds is a SECOND, BROADER concept beside it:
    #
    #     championship track   who can still win the title
    #     postseason eligible  who may be a FantasyStakes subject or wager this
    #                          week — the track, PLUS the official third-place
    #                          pair in championship week
    #
    # Collapsing the two would have been the smaller diff and the wrong model:
    # a third-place team must never read as a title contender, and a rule that
    # says "eliminated teams cannot play" must not silently acquire an
    # exception it cannot name.
    #: The official third-place game, when one is identified. `round_ordinal`
    #: carries the championship round ordinal of the WEEK it is played in — it
    #: is not itself a championship round.
    third_place_matchup: ChampionshipMatchup | None = None
    #: Its two participants: exactly the losers of the championship semifinal.
    third_place_team_keys: frozenset[str] = frozenset()

    authority: TrackAuthority = TrackAuthority.UNKNOWN
    provenance: TrackProvenance = _field(default_factory=TrackProvenance)
    insufficiency_reasons: tuple[str, ...] = ()

    def championship_subject_team_keys(self) -> frozenset[str] | None:
        """THE accessor an eligibility rule should call. WP1B's seam.

        Returns the teams whose championship-track season is live in this week —
        `contesting_team_keys` — or None when that cannot be stated.

        NONE MEANS REFUSE. It does not mean "nobody", and the distinction is the
        whole contract: an empty frozenset is a determined field that happens to
        be empty, while None is an undetermined one. A caller that treats them
        alike will build an empty subject field out of a provider outage and
        settle a Pool on it.

        None is returned in three situations, all of which a consumer must
        handle identically by refusing:

            · the postseason has not begun for this league-week;
            · the track could not be determined (`TrackAuthority.UNKNOWN`);
            · this week hosts no championship round at all — a placement-only
              final week, or a gap — so there is no championship field for it.

        IT IS DELIBERATELY NOT GATED ON `complete`. The answer for a given week
        must not change once that week's results arrive: the two finalists are
        the legitimate subject field for the championship week both before the
        game is played and after it is settled. Gating on `complete` would make
        this accessor return two different fields for one week depending on when
        it was asked, and settlement always asks second.
        """
        if not self.postseason_started:
            return None
        if not self.authority.is_authoritative:
            return None
        if self.championship_round_ordinal is None:
            return None
        return self.contesting_team_keys

    # ── WP1BC — THE SHARED POSTSEASON ELIGIBILITY RULE ───────────────────────
    #
    # ONE AUTHORITY, TWO CONSUMERS. `betting/pool_postseason.py` and
    # `beefs/postseason_versus.py` both call the two members below and neither
    # restates the rule. That is deliberate: "who may act this week" is a single
    # product question, and two implementations of it would drift the first time
    # one of them was amended. Each consumer translates the answer into internal
    # ids through the certified identity resolver; neither decides it.

    def postseason_subject_team_keys(self) -> frozenset[str] | None:
        """Every team eligible for FantasyStakes action this postseason week.

            ordinary playoff round   the championship-contesting field
            championship week        the finalists, PLUS the two teams in the
                                     OFFICIAL third-place game when one exists
            no third-place game      finalists only — a complete answer, not a
                                     refusal

        NOT THE SAME QUESTION AS `championship_subject_team_keys()`, and the two
        must not be used interchangeably. That one answers "who can still win
        the title" and is what a champion, finalist or advancement reader wants.
        This one answers "who may be a Pool subject or enter a Versus wager",
        which in championship week is a strictly larger set.

        NONE MEANS REFUSE, on exactly the same three conditions as the narrower
        accessor. An empty frozenset would be a determined-but-empty field; None
        is an undetermined one, and a caller that conflates them will build a
        subject universe out of a provider outage.

        THE THIRD-PLACE PAIR IS NEVER INFERRED FROM `NON_CHAMPIONSHIP`. It is
        identified by matching a classified non-championship matchup's
        participants against the semifinal losers derived from CHAMPIONSHIP
        results — see `_identify_third_place`. Every other placement game in the
        same week fails that match and stays excluded.
        """
        base = self.championship_subject_team_keys()
        if base is None:
            return None
        return base | self.third_place_team_keys

    @property
    def postseason_subject_matchups(self) -> tuple[ChampionshipMatchup, ...]:
        """Every matchup eligible to be a FantasyStakes subject this week.

        The championship matchups, plus the official third-place game when one
        is identified, in deterministic key order. Ordinary consolation and
        placement games are absent — including the other placement games played
        in the very same championship week.

        Empty whenever `postseason_subject_team_keys()` is None; a consumer that
        checks the accessor first, as both do, never reads a stale tuple.
        """
        combined = list(self.championship_matchups)
        if self.third_place_matchup is not None:
            combined.append(self.third_place_matchup)
        return tuple(sorted(combined, key=lambda m: m.matchup_key))


# ── Round arithmetic ──────────────────────────────────────────────────────────

def round_count_for_field(field_size: int) -> int:
    """How many single-elimination rounds a field of `field_size` requires.

    ceil(log2(n)), computed in integers. `(n - 1).bit_length()` is exact and
    avoids the float rounding that makes log2 unreliable at exact powers of two.

    A SIX-TEAM FIELD DERIVES THREE ROUNDS AND TWO FIRST-ROUND BYES, which is the
    familiar shape — but it is derived here, from the field size, and no shape
    is written down. A four-team field derives two rounds and no byes from the
    same two lines. That is the whole point: no league size, no round count and
    no progression appears as a constant anywhere in this module.
    """
    if field_size < 2:
        raise ValueError(
            f"a championship field of {field_size} cannot be bracketed; a track "
            f"needs at least two teams. Refusing to invent a round structure.")
    return (field_size - 1).bit_length()


def first_round_bye_count(field_size: int) -> int:
    """Byes required to lift `field_size` to the next power of two."""
    return (1 << round_count_for_field(field_size)) - field_size


# ── Determination ─────────────────────────────────────────────────────────────

def _unknown(track_input: ChampionshipTrackInput, *, week: int,
             reasons: tuple[str, ...], provenance: TrackProvenance,
             postseason_started: bool = False,
             round_count_expected: int | None = None,
             ) -> ChampionshipTrackState:
    """The fail-closed state. Every team set is empty, by construction.

    Built through one helper so no refusal path can accidentally leak a
    partially-populated alive set — which is the shape of bug that would let a
    consumer act on half a determination.
    """
    return ChampionshipTrackState(
        league_key=track_input.league_key, season=track_input.season, week=week,
        postseason_started=postseason_started,
        round_count_expected=round_count_expected,
        authority=TrackAuthority.UNKNOWN,
        provenance=provenance,
        insufficiency_reasons=tuple(sorted(set(reasons))),
    )


def _classify_week(week_input: ChampionshipWeekInput) -> str | None:
    """A postseason week's bracket-classification health, or None when healthy.

    A PARTIALLY CLASSIFIED WEEK FAILS CLOSED, and it is worth saying why rather
    than dropping the unclassified matchups quietly. An UNKNOWN matchup sitting
    beside a CHAMPIONSHIP one might be the other semi-final. Dropping it would
    produce a field that looks complete, passes every downstream count and is
    missing half the bracket — an error no later check could catch, because
    nothing downstream knows how big the round should have been.
    """
    if not week_input.matchups:
        return REASON_BRACKET_CLASSIFICATION_ABSENT
    unknown = sum(1 for m in week_input.matchups
                  if m.bracket is MatchupBracket.UNKNOWN)
    if unknown == len(week_input.matchups):
        return REASON_BRACKET_CLASSIFICATION_ABSENT
    if unknown:
        return REASON_PARTIAL_BRACKET_CLASSIFICATION
    return None


def _championship_matchups(week_input: ChampionshipWeekInput, *, ordinal: int
                           ) -> tuple[ChampionshipMatchup, ...]:
    """This week's championship matchups, in deterministic key order.

    The filter is `is_affirmatively_championship` and nothing else. UNKNOWN does
    not pass it, NON_CHAMPIONSHIP does not pass it, and neither is given a
    second chance further down.
    """
    return tuple(sorted(
        (ChampionshipMatchup(
            matchup_key=m.matchup_key,
            home_team_key=m.home_team_key,
            away_team_key=m.away_team_key,
            round_ordinal=ordinal,
            finality=m.finality,
            winner_team_key=m.winner_team_key,
            is_tied=m.is_tied,
        )
         for m in week_input.matchups
         if m.bracket.is_affirmatively_championship),
        key=lambda m: m.matchup_key,
    ))


def _identify_third_place(week_input: ChampionshipWeekInput,
                          semifinal_losers: frozenset[str],
                          *, ordinal: int
                          ) -> tuple[ChampionshipMatchup | None, str | None]:
    """The OFFICIAL third-place game for a championship week — WP1BC §2.

    Returns (matchup, refusal_reason); exactly one is ever non-None, and both
    being None means "this season has no third-place game", which is a complete
    answer rather than a gap.

    THE DISCRIMINATOR IS THE PARTICIPANT SET, NOT THE BRACKET VALUE. A
    championship week can carry several classified non-championship games —
    PS12's carries three. Treating any of them as eligible because it is "the
    placement game in the final week" is the exact rule the POR prohibits. What
    identifies the OFFICIAL one is that its two participants are precisely the
    teams that lost the championship semifinal, and those come from CHAMPIONSHIP
    results the track already derived. So the third-place game is recognised by
    championship evidence, not by consolation evidence.

    UNKNOWN CANNOT QUALIFY, on two independent grounds. The filter demands
    `MatchupBracket.NON_CHAMPIONSHIP` affirmatively rather than "not
    championship", and a week containing any UNKNOWN matchup has already been
    refused by `_classify_week` before this is reached. Either alone would be
    sufficient; both are present because this is the branch where an eliminated
    team becomes able to take money.

    MORE THAN ONE MATCH IS A REFUSAL, NOT A CHOICE. Two rows claiming the same
    pair means the bracket cannot be read deterministically, and picking either
    would make eligibility depend on row order.
    """
    if not semifinal_losers:
        return None, None

    candidates = [
        m for m in week_input.matchups
        if m.bracket is MatchupBracket.NON_CHAMPIONSHIP
        and frozenset((m.home_team_key, m.away_team_key)) == semifinal_losers
    ]
    if not candidates:
        # A season that simply does not play a third-place game. Finalists-only
        # eligibility is the correct answer and nothing is wrong.
        return None, None
    if len(candidates) > 1:
        return None, REASON_AMBIGUOUS_THIRD_PLACE

    found = candidates[0]
    return ChampionshipMatchup(
        matchup_key=found.matchup_key,
        home_team_key=found.home_team_key,
        away_team_key=found.away_team_key,
        round_ordinal=ordinal,
        finality=found.finality,
        winner_team_key=found.winner_team_key,
        is_tied=found.is_tied,
    ), None


def derive_championship_track_state(track_input: ChampionshipTrackInput, *,
                                    week: int) -> ChampionshipTrackState:
    """The championship-track state for `week`. Pure; reads only its argument.

    Deterministic in the strong sense the certification requires: the same
    normalized facts supplied in any ORDER produce an equal state, because every
    team collection is a frozenset and every sequence is sorted on a stable key.
    """
    reasons: list[str] = []

    supplied_weeks = tuple(sorted({w.week for w in track_input.weeks}))
    provenance = TrackProvenance(
        playoff_start_week_source=(
            SOURCE_ABSENT if track_input.playoff_start_week is None
            else SOURCE_PROVIDER),
        season_final_week_source=(
            SOURCE_ABSENT if track_input.season_final_week is None
            else SOURCE_PROVIDER),
        playoff_team_count_source=(
            SOURCE_ABSENT if track_input.playoff_team_count is None
            else SOURCE_PROVIDER),
        weeks_consulted=supplied_weeks,
        observed_at=track_input.observed_at,
    )

    # ── The boundary. Without it, "has the postseason begun" is unanswerable,
    # and answering it wrongly is the one mistake that mislabels an entire
    # regular-season week as a championship round.
    start = track_input.playoff_start_week
    if start is None:
        return _unknown(track_input, week=week,
                        reasons=(REASON_PLAYOFF_START_WEEK_ABSENT,),
                        provenance=provenance)

    if week < start:
        # NOT A REFUSAL. The postseason has not begun, which is a complete and
        # authoritative answer. `championship_subject_team_keys()` still returns
        # None, because there is no championship field to be a subject of.
        return ChampionshipTrackState(
            league_key=track_input.league_key, season=track_input.season,
            week=week, postseason_started=False,
            authority=TrackAuthority.DERIVED, provenance=provenance)

    # ── Field size, from the strongest available source ──────────────────────
    declaration = track_input.field_declaration
    declared_size = len(declaration.team_keys) if declaration is not None else None
    counted_size = track_input.playoff_team_count

    if (declared_size is not None and counted_size is not None
            and declared_size != counted_size):
        # Two authoritative sources disagreeing about the field is not a value
        # to pick between. It is a provider state no determination can rest on.
        reasons.append(REASON_FIELD_SIZE_CONTRADICTS_DECLARATION)

    field_size = declared_size if declared_size is not None else counted_size
    round_count_expected: int | None = None
    if field_size is not None:
        if field_size < 2:
            reasons.append(REASON_FIELD_SIZE_NOT_POSITIVE)
        else:
            round_count_expected = round_count_for_field(field_size)

    if reasons:
        return _unknown(track_input, week=week, reasons=tuple(reasons),
                        provenance=provenance, postseason_started=True,
                        round_count_expected=round_count_expected)

    # ── Postseason weeks in scope: at or after the boundary, up to `week` ─────
    in_scope = tuple(sorted(
        (w for w in track_input.weeks if start <= w.week <= week),
        key=lambda w: w.week))
    provenance = TrackProvenance(
        playoff_start_week_source=provenance.playoff_start_week_source,
        season_final_week_source=provenance.season_final_week_source,
        playoff_team_count_source=provenance.playoff_team_count_source,
        weeks_consulted=tuple(w.week for w in in_scope),
        observed_at=provenance.observed_at,
    )

    if not in_scope:
        return _unknown(track_input, week=week,
                        reasons=(REASON_NO_PROVIDER_WEEKS,),
                        provenance=provenance, postseason_started=True,
                        round_count_expected=round_count_expected)
    if week not in {w.week for w in in_scope}:
        # The requested week itself was not supplied. Answering from the weeks
        # around it would be interpolation, and a bracket does not interpolate.
        return _unknown(track_input, week=week,
                        reasons=(REASON_WEEK_NOT_SUPPLIED,),
                        provenance=provenance, postseason_started=True,
                        round_count_expected=round_count_expected)

    for week_input in in_scope:
        problem = _classify_week(week_input)
        if problem:
            reasons.append(problem)
    if reasons:
        return _unknown(track_input, week=week, reasons=tuple(reasons),
                        provenance=provenance, postseason_started=True,
                        round_count_expected=round_count_expected)

    # ── The championship rounds are the weeks that HAVE championship matchups,
    # in week order. The round ordinal is read off actual bracket state — never
    # computed as `week - playoff_start_week`, which would mislabel a
    # placement-only week as a championship round and would break the moment a
    # league's championship track is shorter than its postseason phase.
    rounds: list[tuple[ChampionshipWeekInput, tuple[ChampionshipMatchup, ...]]] = []
    for week_input in in_scope:
        ordinal = len(rounds) + 1
        matchups = _championship_matchups(week_input, ordinal=ordinal)
        if matchups:
            rounds.append((week_input, matchups))

    if not rounds:
        return _unknown(track_input, week=week,
                        reasons=(REASON_NO_CHAMPIONSHIP_MATCHUPS,),
                        provenance=provenance, postseason_started=True,
                        round_count_expected=round_count_expected)

    provenance = TrackProvenance(
        playoff_start_week_source=provenance.playoff_start_week_source,
        season_final_week_source=provenance.season_final_week_source,
        playoff_team_count_source=provenance.playoff_team_count_source,
        bracket_source=SOURCE_PROVIDER_CLASSIFIED,
        weeks_consulted=provenance.weeks_consulted,
        observed_at=provenance.observed_at,
    )

    # ── The round-one field ──────────────────────────────────────────────────
    first_week, first_matchups = rounds[0]
    first_participants: list[str] = []
    for matchup in first_matchups:
        first_participants.extend(matchup.team_keys)
    if len(set(first_participants)) != len(first_participants):
        return _unknown(track_input, week=week,
                        reasons=(REASON_DUPLICATE_PARTICIPANT,),
                        provenance=provenance, postseason_started=True,
                        round_count_expected=round_count_expected)
    round_one = frozenset(first_participants)

    if declaration is not None:
        championship_field = frozenset(declaration.team_keys)
        if not round_one <= championship_field:
            return _unknown(track_input, week=week,
                            reasons=(REASON_ORPHAN_PARTICIPANT,),
                            provenance=provenance, postseason_started=True,
                            round_count_expected=round_count_expected)
        field_source = SOURCE_PROVIDER_DECLARED
    elif field_size is None:
        # No declaration and no field size: round one's participants might be
        # the whole field or might be missing every bye team, and nothing
        # available distinguishes those. See ChampionshipFieldDeclaration.
        return _unknown(track_input, week=week,
                        reasons=(REASON_PLAYOFF_TEAM_COUNT_ABSENT,
                                 REASON_BYE_TEAMS_UNIDENTIFIED),
                        provenance=provenance, postseason_started=True,
                        round_count_expected=round_count_expected)
    elif len(round_one) == field_size:
        championship_field = round_one
        field_source = SOURCE_DERIVED_FROM_MATCHUPS
    else:
        return _unknown(track_input, week=week,
                        reasons=(REASON_BYE_TEAMS_UNIDENTIFIED,),
                        provenance=provenance, postseason_started=True,
                        round_count_expected=round_count_expected)

    provenance = TrackProvenance(
        playoff_start_week_source=provenance.playoff_start_week_source,
        season_final_week_source=provenance.season_final_week_source,
        playoff_team_count_source=provenance.playoff_team_count_source,
        field_source=field_source,
        bracket_source=provenance.bracket_source,
        weeks_consulted=provenance.weeks_consulted,
        observed_at=provenance.observed_at,
    )

    # STRUCTURAL CROSS-CHECK. When the field size is authoritative the bye count
    # is arithmetic, so a round one whose byes disagree with it describes a
    # bracket this model does not understand. Refusing is the right direction:
    # a mis-modelled bracket produces a wrong alive set every subsequent round.
    if field_size is not None:
        expected_byes = first_round_bye_count(field_size)
        if len(championship_field - round_one) != expected_byes:
            return _unknown(track_input, week=week,
                            reasons=(REASON_BYE_STRUCTURE_CONTRADICTS,),
                            provenance=provenance, postseason_started=True,
                            round_count_expected=round_count_expected)

    # ── Walk the rounds ──────────────────────────────────────────────────────
    alive = championship_field
    contesting = championship_field
    byes: frozenset[str] = frozenset()
    week_matchups: tuple[ChampionshipMatchup, ...] = ()
    requested_ordinal: int | None = None
    finalists: tuple[str, ...] = ()
    rounds_decided = 0
    # WP1BC — losers per championship round ordinal. Recorded as the walk goes
    # because the semifinal's losers are computed here and were previously
    # discarded; nothing downstream could reconstruct them, since
    # `eliminated_team_keys` is the WHOLE eliminated field rather than one
    # round's casualties.
    losers_by_round: dict[int, frozenset[str]] = {}

    for index, (week_input, matchups) in enumerate(rounds):
        ordinal = index + 1
        is_requested = week_input.week == week

        participants: list[str] = []
        for matchup in matchups:
            participants.extend(matchup.team_keys)
        if len(set(participants)) != len(participants):
            return _unknown(track_input, week=week,
                            reasons=(REASON_DUPLICATE_PARTICIPANT,),
                            provenance=provenance, postseason_started=True,
                            round_count_expected=round_count_expected)
        playing = frozenset(participants)
        if not playing <= alive:
            # A team contesting this round that did not survive the last one.
            # There is no reading of that which is safe to continue from.
            return _unknown(track_input, week=week,
                            reasons=(REASON_ORPHAN_PARTICIPANT,),
                            provenance=provenance, postseason_started=True,
                            round_count_expected=round_count_expected)

        entering = alive
        round_byes = entering - playing

        # FINALISTS ARE THE TWO TEAMS CONTESTING A SINGLE DECIDING GAME, and
        # they are identified from that structure rather than from a round
        # number — a track whose final round is round two identifies them just
        # as well as one whose final round is round three.
        if len(entering) == 2 and len(matchups) == 1:
            finalists = tuple(sorted(matchups[0].team_keys))

        # A FINAL BUT WINNERLESS CHAMPIONSHIP GAME cannot advance anybody, and
        # it is a DIFFERENT state from a game still in progress. Reported as
        # unresolved rather than resolved by score: a provider that declares a
        # result without declaring a winner has said something no downstream
        # reader may paper over, and comparing the two scores here would be the
        # inference `providers/yahoo/normalize.py` already refuses to make.
        if any(m.finality.is_affirmatively_final and not m.winner_team_key
               for m in matchups):
            return _unknown(track_input, week=week,
                            reasons=(REASON_UNRESOLVED_RESULT,),
                            provenance=provenance, postseason_started=True,
                            round_count_expected=round_count_expected)

        decided = all(m.is_decided for m in matchups)
        if decided:
            winners = frozenset(m.winner_team_key for m in matchups
                                if m.winner_team_key)
            advancing = winners | round_byes
            rounds_decided += 1
            # PLAYING minus WINNERS, not ENTERING minus ADVANCING. The two agree
            # today, but the first says what it means — a bye team did not lose
            # a game it never played, and if bye handling ever changes the
            # second would quietly start counting them.
            losers_by_round[ordinal] = playing - winners
        else:
            if not is_requested:
                # An undecided round before the one being asked about makes
                # every later alive set a guess. This is the case a naive
                # implementation gets wrong by carrying the previous field
                # forward as though nothing had happened.
                return _unknown(track_input, week=week,
                                reasons=(REASON_UNDECIDED_EARLIER_ROUND,),
                                provenance=provenance, postseason_started=True,
                                round_count_expected=round_count_expected)
            advancing = entering

        if is_requested:
            contesting = entering
            byes = round_byes
            week_matchups = matchups
            requested_ordinal = ordinal

        alive = advancing

    if requested_ordinal is None:
        # The requested week is a postseason week with no championship game —
        # a placement-only final week, or a gap. The track's state still stands;
        # this week simply contributes nothing to it.
        contesting = alive
        byes = frozenset()
        week_matchups = ()

    complete = len(alive) == 1 and rounds_decided == len(rounds)
    champion = next(iter(alive)) if complete else None

    if (complete and round_count_expected is not None
            and rounds_decided < round_count_expected):
        # One team left before the bracket could have produced one. Whatever
        # this state is, it is not a completed championship.
        return _unknown(track_input, week=week,
                        reasons=(REASON_PREMATURE_COMPLETION,),
                        provenance=provenance, postseason_started=True,
                        round_count_expected=round_count_expected)

    # ── WP1BC — the official third-place game ────────────────────────────────
    #
    # CHAMPIONSHIP WEEK ONLY, AND ONLY WHEN A SEMIFINAL EXISTS. The exception is
    # scoped to the round that decides the title (§1); an ordinary playoff round
    # has no third-place concept, and a one-round track (a two-team field) has
    # no semifinal to lose. Both yield finalists-only eligibility, which is an
    # answer rather than a refusal.
    third_place: ChampionshipMatchup | None = None
    third_place_keys: frozenset[str] = frozenset()
    if (requested_ordinal is not None
            and round_count_expected is not None
            and requested_ordinal == round_count_expected
            and round_count_expected >= 2):
        semifinal_losers = losers_by_round.get(round_count_expected - 1,
                                               frozenset())
        requested_input = next(w for w in in_scope if w.week == week)
        third_place, third_place_problem = _identify_third_place(
            requested_input, semifinal_losers, ordinal=requested_ordinal)
        if third_place_problem:
            return _unknown(track_input, week=week,
                            reasons=(third_place_problem,),
                            provenance=provenance, postseason_started=True,
                            round_count_expected=round_count_expected)
        if third_place is not None:
            third_place_keys = frozenset(third_place.team_keys)

    authority = (TrackAuthority.PROVIDER_CLASSIFIED
                 if field_source == SOURCE_PROVIDER_DECLARED
                 else TrackAuthority.DERIVED)

    return ChampionshipTrackState(
        league_key=track_input.league_key,
        season=track_input.season,
        week=week,
        postseason_started=True,
        championship_round_ordinal=requested_ordinal,
        round_count_expected=round_count_expected,
        championship_field_team_keys=championship_field,
        contesting_team_keys=contesting,
        alive_team_keys=alive,
        eliminated_team_keys=championship_field - alive,
        bye_team_keys=byes,
        championship_matchups=week_matchups,
        complete=complete,
        champion_team_key=champion,
        finalist_team_keys=finalists,
        third_place_matchup=third_place,
        third_place_team_keys=third_place_keys,
        authority=authority,
        provenance=provenance,
        insufficiency_reasons=(),
    )
