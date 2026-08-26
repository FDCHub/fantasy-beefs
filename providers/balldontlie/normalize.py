"""WP2 · the Phase 0F rules — BALLDONTLIE's behaviour, made explicit and gated.

EVERY RULE BELOW WAS MEASURED, NOT ASSUMED. The Phase 0 acceptance test settled
58 real players across two league profiles from BALLDONTLIE facts and closed
every figure to 0.00 against Yahoo's own scoreboard. The rules that made that
work are recorded here as named functions, and `RULES` lists them so a
certification suite can assert that none has quietly disappeared.

── THE RULE THAT INVERTS AN EXISTING ONE, STATED FIRST ─────────────────────

`providers/week_stat_source.py` holds this product's standing rule about missing
statistics: A MISSING STAT IS UNEVALUABLE, NEVER 0.0. That rule is correct for
Yahoo, whose payload carries a stat id for every category it scores, so an
absent id really does mean "we were not told".

BALLDONTLIE OMITS EVERY ZERO. 25 of the 34 week-1 kickers carried no
`field_goals_missed` key, and all 25 had perfect days. Under the Yahoo rule
those 25 kickers would be UNEVALUABLE and no kicker Pool could ever settle.

Both rules are right about their own provider, and the difference is not a
detail to be smoothed over — it decides whether a wager settles or refuses. So
the distinction is drawn at the level BALLDONTLIE actually speaks at:

    A PRESENT ROW asserts its whole vocabulary. Every field the row's kind can
    carry is evaluable; the ones that are absent are zero, because that is what
    absence MEANS in this payload.

    AN ABSENT ROW asserts nothing. A subject with no row is UNEVALUABLE, exactly
    as before, and no default fills the hole.

    AN EMPTY `stats: {}` IS A PRESENT ROW. It is a real zero — a player who
    dressed and did not play — validated against Brock Bowers scoring 0.00. It
    is not a gap, and reading it as one would refuse a settlement that Yahoo
    settled.

COVERAGE IS THEREFORE ASSERTED AT ROW LEVEL, which is what `stat_ids_present`
carries out of this module. `providers/base.ProviderPlayerStats` keeps coverage
separate from values precisely so a provider can answer this question its own
way without the answer being inferred from a dict lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Iterator, Mapping, Sequence

from providers.balldontlie_identity import defense_key, player_key
from providers.balldontlie.parse import GameRow, PlayRow, WeeklyStatRow
from providers.base import ProviderLeague, ProviderPlayerStats, ProviderWeek
from providers.errors import ProviderParseError
from providers.nfl_teams import canonical_position, to_canonical_team

PROVIDER = "balldontlie"

__all__ = [
    "DST_FIELDS",
    "KICKER_FIELDS",
    "OFFENSE_FIELDS",
    "RULES",
    "DerivedValue",
    "build_week",
    "carry_possession",
    "extra_point_summary",
    "fantasy_position",
    "field_goal_distance",
    "field_goal_kicker_id",
    "final_score",
    "kicker_settlement_source",
    "normalize_projections",
    "normalize_weekly_stats",
    "ordered_plays",
    "pick_six_passer_id",
    "points_allowed",
    "refuse_play_aggregation",
    "refuse_quarter_sum",
    "regular_season_only",
    "subject_key",
    "supported_stats",
    "three_and_outs",
]


# ── the published vocabulary, per subject kind ───────────────────────────────
#
# WHY THESE LISTS EXIST AT ALL. Rule 0F-1 says a present row asserts its whole
# vocabulary — so the vocabulary has to be written down, or "whole" means
# "whichever keys happened to be non-zero", which is the bug the rule exists to
# prevent. Every name below was observed in the Phase 0 sweep across weeks 1, 4,
# 8, 12 and 17.
#
# A FIELD BALLDONTLIE SENDS THAT IS NOT LISTED HERE IS STILL CARRIED. See
# `normalize_weekly_stats`: unknown keys are passed through with their values
# and counted as present. Dropping them would hide a provider ADDING a category,
# which is how a scoring rule silently stops seeing its own input.

OFFENSE_FIELDS: frozenset[str] = frozenset({
    "passing_yards", "passing_touchdowns", "passing_interceptions",
    "passing_two_point_conversions",
    "rushing_yards", "rushing_touchdowns", "rushing_two_point_conversions",
    "receptions", "receiving_yards", "receiving_touchdowns",
    "receiving_two_point_conversions",
    "fumbles_lost", "offensive_fumble_recovery_touchdowns",
    "kick_return_touchdowns", "punt_return_touchdowns",
})

KICKER_FIELDS: frozenset[str] = frozenset({
    "field_goals_made", "field_goal_attempts", "field_goals_made_yards",
    "field_goals_made_0_to_39", "field_goals_made_40_to_49",
    "field_goals_made_50_plus", "field_goals_made_50_to_59",
    "field_goals_made_60_plus",
    "field_goals_missed", "field_goals_missed_yards",
    "field_goals_missed_0_to_39", "field_goals_missed_40_to_49",
    "field_goals_missed_50_plus",
    "extra_points_made", "extra_point_attempts", "extra_points_missed",
})

DST_FIELDS: frozenset[str] = frozenset({
    "defensive_sacks", "defensive_half_sacks", "defensive_interceptions",
    "opponent_fumble_recoveries", "fumbles_forced", "defensive_safeties",
    "kicks_blocked", "interception_return_touchdowns",
    "fumble_return_touchdowns", "turnover_return_touchdowns",
    "blocked_kick_return_touchdowns", "kick_return_touchdowns",
    "punt_return_touchdowns", "two_point_returns", "dst_points_allowed",
    "dst_yards_allowed",
})

PLAYER_FIELDS: frozenset[str] = OFFENSE_FIELDS | KICKER_FIELDS


# ── play slugs, and the two traps in them ────────────────────────────────────

#: `play.team` is the RECEIVING team on these. Possession must be carried
#: forward, never read from the play.
POSSESSION_INVERTED_SLUGS = frozenset({"punt", "kickoff", "field-goal-missed"})

#: `play.team` is the KICKING team here — the same field meaning the opposite
#: thing one slug apart, which is why nothing reads it directly.
POSSESSION_KICKING_SLUGS = frozenset({"field-goal-good"})

#: A THIRD MEANING OF THE SAME FIELD, measured in Sprint 5B. On a takeaway,
#: `play.team` is the team GAINING the ball — Kansas City threw the pass and
#: `team` reads BAL — so the play itself belongs to the possession that is
#: ENDING, and possession passes only afterwards. Reading `team` directly here
#: put the interception in the intercepting team's drive and left the drive it
#: actually ended with no ending at all, which is how 35% of real drives
#: classified UNKNOWN before this was understood.
POSSESSION_TAKEAWAY_SLUGS = frozenset({
    "pass-interception-return", "interception-return-touchdown",
    "fumble-recovery-opponent", "fumble-return-touchdown",
    "blocked-punt", "blocked-punt-touchdown", "punt-return-touchdown",
})

#: EVERY field-goal slug, listed rather than matched by prefix. `startswith
#: ("field-goal")` MISSES `blocked-field-goal` entirely — Phase 0 found a
#: blocked 37-yarder appearing only as "Jared Verse 76 Yd Return of Blocked
#: Field Goal" — and a missed field goal that is not counted as an attempt is a
#: kicker's score quietly improving.
FIELD_GOAL_SLUGS = frozenset({
    "field-goal-good", "field-goal-missed",
    "blocked-field-goal", "blocked-field-goal-touchdown",
})

#: Blocked kicks whose DISTANCE the play stream cannot give up.
#: `blocked-field-goal` carries `stat_yardage: null` — the distance exists only
#: in the English text — and `blocked-field-goal-touchdown` reports the RETURN
#: distance instead, which is a different number about a different event. Both
#: fall back to the summary endpoint, which carries the attempt exactly.
#:
#: ATTRIBUTION AND DISTANCE ARE SEPARATE LOSSES, AND ONLY ONE IS UNIVERSAL.
#: `blocked-field-goal` may still name its kicker; `blocked-field-goal-touchdown`
#: has no kicker participant at all. So `field_goal_kicker_id` answers from the
#: participants whatever the slug, and `field_goal_distance` is the one that
#: refuses — conflating them would throw away an attribution the payload made.
DISTANCE_UNRECOVERABLE_FG_SLUGS = frozenset({
    "blocked-field-goal", "blocked-field-goal-touchdown"})

PARTICIPANT_FIELD_GOAL_KICKER = "field_goal_kicker"
PARTICIPANT_PASSER = "passer"


@dataclass(frozen=True)
class DerivedValue:
    """A figure this layer computed rather than read, and how much to trust it.

    IT EXISTS FOR EXACTLY ONE CATEGORY TODAY. Three-and-outs forced is the only
    Yahoo category with no BALLDONTLIE field at all, and the derivation Phase 0
    built for it produced 1.19 per team-game against an NFL norm nearer 2.3. The
    punt counts underneath it cross-checked 47 of 48 against the box score, so
    the feed is right and the RULE is not yet calibrated — Yahoo's treatment of
    penalties, declined flags and drives ending a half is unknown.

    A number in that state must not be able to reach a settlement by being
    passed around as a float. So it is wrapped, `verified` is False, and
    `require_verified()` raises. WP10's verification gate is what flips it.
    """

    value: float
    verified: bool
    basis: str
    caveat: str = ""

    def require_verified(self) -> float:
        if not self.verified:
            raise ProviderParseError(
                f"refusing to hand out an UNVERIFIED derived figure "
                f"({self.basis}): {self.caveat} Settle this only behind the "
                f"verification gate, never from this value alone.")
        return self.value


# ── 0F-1 / 0F-2 / 0F-3 · the zero-omission family ────────────────────────────

def fantasy_position(row: WeeklyStatRow) -> str | None:
    """Canonical fantasy position for a row, or None when there is not one.

    NEVER ASSUME SIX VALUES. Phase 0's week-1 sweep returned one DT among 637
    rows, and `position_abbreviation` spells kickers PK and some backs FB. WP1's
    `canonical_position` already owns every spelling this product accepts, so
    this defers to it rather than keeping a second table — and returns None,
    rather than raising, for a position outside the fantasy vocabulary. A DT is
    a real row about a real player; it simply is not a fantasy subject, and
    dropping it silently or refusing the whole week are both worse answers.
    """
    for candidate in (row.position,
                      (row.player or {}).get("position_abbreviation"),
                      (row.player or {}).get("position")):
        if not candidate:
            continue
        try:
            return canonical_position(candidate)
        except Exception:                                     # noqa: BLE001
            continue
    return "DEF" if row.is_team_defense else None


def subject_key(row: WeeklyStatRow) -> str:
    """The BALLDONTLIE key WP1's resolver reads. One spelling, one source.

    A DST row carries `player: null` and is keyed by its team; everything else
    is keyed by player id. Both keys come from `providers/balldontlie_identity`,
    so a stat row and an identity mapping cannot drift apart by spelling a key
    two different ways in two different modules.
    """
    if row.is_team_defense:
        abbreviation = row.team_abbreviation
        try:
            return defense_key(to_canonical_team(abbreviation,
                                                 dialect=PROVIDER))
        except Exception as exc:                              # noqa: BLE001
            raise ProviderParseError(
                f"team defense row carries NFL team {abbreviation!r}, which is "
                f"not a team this product knows: {exc}") from exc
    identifier = row.player_id
    if identifier is None:
        raise ProviderParseError(
            "a non-defense fantasy row carries no player id. There is nothing "
            "durable to key it by, and falling back to the name is the one "
            "thing WP1 forbids.")
    return player_key(identifier)


def _vocabulary(row: WeeklyStatRow) -> frozenset[str]:
    return DST_FIELDS if row.is_team_defense else PLAYER_FIELDS


def normalize_weekly_stats(rows: Iterable[WeeklyStatRow], *,
                           week: int | None = None
                           ) -> tuple[ProviderPlayerStats, ...]:
    """Rows -> ProviderPlayerStats, applying rules 0F-1, 0F-2 and 0F-3.

    WHAT COMES OUT, PRECISELY:

        `values`            every field of the row's vocabulary, with an absent
                            field carried as 0.0 — because absence is how this
                            provider spells zero — plus every unknown field the
                            payload actually sent, at its reported value.

        `stat_ids_present`  the same key set. THE ROW IS THE COVERAGE. A subject
                            with no row produces no record at all and stays
                            UNEVALUABLE downstream, which is the distinction the
                            whole rule turns on.

    NOTHING IS INVENTED FOR A SUBJECT THAT HAS NO ROW. This function cannot even
    express that: it maps rows it was given, and a missing subject is missing.
    """
    out: list[ProviderPlayerStats] = []
    for row in rows:
        vocabulary = _vocabulary(row)
        values: dict[str, float] = {}
        for name in sorted(vocabulary):
            raw = row.stats.get(name)
            values[name] = 0.0 if raw is None else _as_float(raw, name)
        for name, raw in row.stats.items():
            if name in vocabulary or raw is None:
                continue
            try:
                values[name] = _as_float(raw, name)
            except ProviderParseError:
                # A non-numeric extra field is carried by the raw payload and is
                # not a statistic. Skipping it here loses nothing and refusing
                # the row would fail a whole week over a label.
                continue
        out.append(ProviderPlayerStats(
            provider=PROVIDER,
            player_key=subject_key(row),
            week=int(week if week is not None else row.week),
            values=values,
            stat_ids_present=frozenset(values),
            fantasy_points=_optional_points(row),
        ))
    return tuple(out)


def normalize_projections(rows: Iterable[WeeklyStatRow], *,
                         week: int | None = None
                         ) -> tuple[ProviderPlayerStats, ...]:
    """Projection rows -> components. 0F-1 IS DELIBERATELY NOT APPLIED.

    THE ZERO-OMISSION RULE IS ABOUT RESULTS, AND A FORECAST IS NOT A RESULT.
    On `/fantasy/weekly_stats` an absent `field_goals_missed` means the kicker
    missed none — the event did not happen, and zero is the true value. On
    `/fantasy/projections` an absent field means BALLDONTLIE DID NOT FORECAST
    IT, which is a different statement and usually a louder one.

    `receptions` proves it. Phase 0 found the projection block carries no
    reception count at all — a PPR league must derive one from `targets` and a
    catch rate — while `targets` is present. Zero-filling that field would hand
    CSPS a confident `receptions: 0.0` for every pass-catcher in the league, and
    a PPR projection built on it would be wrong for every one of them, silently,
    with no missing key anywhere to notice.

    So this carries exactly what the provider sent. A component that is absent
    stays absent, `stat_ids_present` says so, and a scorer that needs it must
    derive it or refuse — which is the same discipline `week_stat_source.py`
    applies to Yahoo, arrived at from the opposite direction.

    THE TWO ENDPOINTS THEREFORE NORMALIZE DIFFERENTLY, ON PURPOSE. That is the
    one place in this package where the shared vocabulary does not imply shared
    handling, and it is recorded as rule 0F-20 rather than left as a difference
    between two function bodies.
    """
    out: list[ProviderPlayerStats] = []
    for row in rows:
        values: dict[str, float] = {}
        for name, raw in row.stats.items():
            if raw is None:
                continue
            try:
                values[name] = _as_float(raw, name)
            except ProviderParseError:
                # A non-numeric field in a projection block is a label, not a
                # forecast. Carried in `components_present` by the caller and
                # not turned into a number here.
                continue
        out.append(ProviderPlayerStats(
            provider=PROVIDER,
            player_key=subject_key(row),
            week=int(week if week is not None else row.week),
            values=values,
            stat_ids_present=frozenset(values),
            fantasy_points=_optional_points(row),
        ))
    return tuple(out)


def _as_float(raw: Any, name: str) -> float:
    if isinstance(raw, bool):
        raise ProviderParseError(f"stat {name!r} is a boolean, not a number")
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ProviderParseError(
            f"stat {name!r} is {raw!r}, which is not a number") from exc


def _optional_points(row: WeeklyStatRow) -> float | None:
    """Fantasy points, ONLY where the provider stated them.

    Never computed here. BALLDONTLIE's own point total is scored under ITS
    default format, not under a FantasyStakes league's rule set, so it is
    carried as provider commentary and is not what anything settles on. WP4's
    evaluator produces the figure that matters, from the components above.
    """
    for name in ("fantasy_points", "points"):
        raw = row.stats.get(name)
        if raw is not None:
            try:
                return _as_float(raw, name)
            except ProviderParseError:
                return None
    return None


def supported_stats(rows: Iterable[WeeklyStatRow]) -> frozenset[str]:
    """What this PAYLOAD can measure — `ProviderStatCoverage`, answered honestly.

    Measured from the rows in hand, never from the documented vocabulary above.
    §13 is explicit: advertise what is available in the data, not what the
    provider's documentation claims it would send.
    """
    present: set[str] = set()
    for row in rows:
        present |= _vocabulary(row)
        present |= {k for k, v in row.stats.items() if v is not None}
    return frozenset(present)


# ── 0F-4 · quarters are not a score ──────────────────────────────────────────

def final_score(game: GameRow) -> tuple[float, float]:
    """(home, visitor) from the GAME object. The only supported reader.

    NEVER FROM QUARTERS, AND NEVER FROM THE LAST PLAY. BALLDONTLIE writes `null`
    for a scoreless quarter, so summing periods is wrong before it is even
    unsafe; and the play stream can carry a record AFTER `end-of-game`, so the
    last play is not the last word. Both wrong answers look plausible.
    """
    home, visitor = game.home_team_score, game.visitor_team_score
    if home is None or visitor is None:
        raise ProviderParseError(
            f"game {game.id} has no final score yet "
            f"(home={home!r}, visitor={visitor!r}). An unfinished game has no "
            f"score to read, and quarters must not be summed to invent one.")
    return home, visitor


def refuse_quarter_sum(game: GameRow) -> None:
    """A named refusal for the thing that must never happen. Always raises."""
    raise ProviderParseError(
        f"refusing to derive game {game.id}'s score from period_scores. "
        f"BALLDONTLIE writes null for a scoreless quarter, so the sum is either "
        f"a TypeError or a wrong total — and `final_score` already has the "
        f"authoritative figure.")


# ── 0F-5 / 0F-6 · plays: order, and the null team ────────────────────────────

def ordered_plays(plays: Sequence[PlayRow]) -> tuple[PlayRow, ...]:
    """Plays in real order. By WALLCLOCK, because ids are not monotonic.

    Phase 0F: play ids are non-monotonic and a record can follow
    `end-of-game`, so payload order and id order are both unreliable. Ties keep
    payload order (Python's sort is stable), and a play with no wallclock sorts
    after those that have one rather than being dropped — losing an event
    silently is how a three-and-out count drifts.
    """
    return tuple(sorted(
        plays, key=lambda p: (p.wallclock is None, str(p.wallclock or ""))))


def carry_possession(plays: Sequence[PlayRow], *, home: str, visitor: str
                     ) -> Iterator[tuple[PlayRow, str | None]]:
    """Yield (play, possessing team) with the kicking-play inversion undone.

    THE TRAP, IN ONE SENTENCE: `play.team` is the RECEIVING team on `punt`,
    `kickoff` and `field-goal-missed`, and the KICKING team on
    `field-goal-good`. One field, opposite meanings, one slug apart.

    So possession is CARRIED FORWARD from the last ordinary play and never read
    off a kicking play. A play with a null team — observed on a timeout — leaves
    possession untouched rather than clearing it or failing the game.
    """
    teams = {home, visitor}

    def other(side: str | None) -> str | None:
        rest = teams - {side} if side in teams else set()
        return next(iter(rest), None)

    possession: str | None = None
    for play in ordered_plays(plays):
        abbreviation = (play.team or {}).get("abbreviation")

        if play.type in POSSESSION_INVERTED_SLUGS:
            # `play.team` IS NOT READ HERE. It is the receiving team, and using
            # it as possession is the inversion this function exists to undo.
            # The one exception is seeding: with no carried possession yet —
            # the first play of a stream — the receiving team is the only
            # evidence available, and the kicking team is the other one.
            if possession is None and abbreviation in teams:
                possession = other(abbreviation)
            yield play, possession
            possession = other(possession)     # the ball changes hands
            continue

        if play.type in POSSESSION_TAKEAWAY_SLUGS:
            # The play belongs to whoever HAD the ball; `team` is who takes it.
            losing = other(abbreviation) if abbreviation in teams else possession
            if possession is None:
                possession = losing
            yield play, possession
            possession = abbreviation if abbreviation in teams else other(possession)
            continue

        if play.type in POSSESSION_KICKING_SLUGS:
            # The one slug where the team on the play IS the kicking team.
            if abbreviation in teams:
                possession = abbreviation
            yield play, possession
            possession = other(possession)
            continue

        # An ordinary play, or one with a null team (a timeout): a stated team
        # is possession, and a null one leaves possession exactly as it was.
        if abbreviation in teams:
            possession = abbreviation
        yield play, possession


# ── 0F-7 / 0F-8 / 0F-9 · kickers ─────────────────────────────────────────────

def field_goal_kicker_id(play: PlayRow) -> Any | None:
    """The kicker, by participant. None when the play cannot attribute one.

    ATTRIBUTION IS BY PARTICIPANT, NEVER BY TEAM. Phase 0 measured a team-keyed
    read misattributing 5 of 9 observed misses, for the reason
    `carry_possession` documents: the team on a kicking play is not reliably the
    kicking team.

    None means the payload named no kicker — which is exactly what
    `blocked-field-goal-touchdown` does. It is returned rather than raised
    because that is a real state with a real answer one endpoint over: the
    summary carries the attempt the play stream lost. See
    `field_goal_distance` and `kicker_settlement_source`.
    """
    ids = play.participant_ids(PARTICIPANT_FIELD_GOAL_KICKER)
    return ids[0] if ids else None


def field_goal_distance(play: PlayRow) -> float | None:
    """The attempt's distance, or None when the play stream does not hold it.

    None for both blocked slugs, and that is the whole point: `stat_yardage` is
    null on `blocked-field-goal`, and on `blocked-field-goal-touchdown` it is
    the RETURN distance — a plausible number about the wrong event, which is the
    more dangerous of the two failures. Phase 0 found Zane Gonzalez's blocked
    37-yarder appearing only as "Jared Verse 76 Yd Return of Blocked Field
    Goal"; reading 76 as his attempt would band it 60+ instead of 0–39.

    The summary endpoint carries both exactly — Gonzalez at 37 in the 0–39
    bucket — so a None here is an instruction to read it, not a dead end.
    """
    if play.type in DISTANCE_UNRECOVERABLE_FG_SLUGS:
        return None
    return play.stat_yardage


def kicker_settlement_source(stats: Mapping[str, float]) -> tuple[str, str]:
    """("summary" | "plays", why). The summary wins almost always.

    THE FINDING THAT SIMPLIFIED THIS ENTIRE PACKAGE: `/fantasy/weekly_stats` is
    COMPLETE WHERE `/plays` IS NOT. Both blocked kicks the play stream could not
    attribute are carried exactly by the summary, and all nine week-17 kickers
    with a miss settled correctly from the summary alone under both league
    profiles.

    `/plays` is needed only for the one ambiguity the summary cannot resolve: a
    kicker with TWO OR MORE misses of which at least one sits in the 0–39
    bucket, where `field_goals_missed_yards` is a total rather than a distance
    and the sub-20 band scores differently from 20–39. With a single miss that
    field IS the miss's exact distance, which is why one miss is not ambiguous.
    """
    missed = float(stats.get("field_goals_missed") or 0.0)
    short = float(stats.get("field_goals_missed_0_to_39") or 0.0)
    if missed >= 2 and short >= 1:
        return ("plays",
                f"{int(missed)} misses including {int(short)} in the 0–39 "
                f"bucket: field_goals_missed_yards is their TOTAL, so the "
                f"sub-20 band cannot be separated from 20–39 without the "
                f"individual attempts.")
    return ("summary",
            "the summary endpoint is complete for this kicker — it carries "
            "blocked kicks the play stream cannot attribute, and with at most "
            "one miss field_goals_missed_yards is that miss's exact distance.")


def extra_point_summary(stats: Mapping[str, float]) -> dict:
    """Extra points and two-point conversions, from STRUCTURED fields only.

    NEVER PARSE THE PLAY TEXT. Extra points and two-point conversions have no
    play record of their own — they are folded into the touchdown play's English
    — so deriving them from `/plays` means parsing prose about a scoring event.
    These five fields are structured and exact; the prose is neither.
    """
    return {
        "extra_points_made": float(stats.get("extra_points_made") or 0.0),
        "extra_point_attempts": float(stats.get("extra_point_attempts") or 0.0),
        "extra_points_missed": float(stats.get("extra_points_missed") or 0.0),
        "passing_two_point_conversions":
            float(stats.get("passing_two_point_conversions") or 0.0),
        "rushing_two_point_conversions":
            float(stats.get("rushing_two_point_conversions") or 0.0),
        "receiving_two_point_conversions":
            float(stats.get("receiving_two_point_conversions") or 0.0),
    }


def points_allowed(stats: Mapping[str, float]) -> float:
    """`dst_points_allowed`, and the two things a scorer must know about it.

    IT EXCLUDES OPPONENT DEFENSIVE TOUCHDOWNS, which is Yahoo's convention too —
    a defence is not charged for points its own offence gave up. That agreement
    is why settlement from this field was exact across the Phase 0 sweep, and it
    is worth stating here rather than leaving a scorer to assume either
    convention.

    THE EXTRA-POINT TREATMENT IS UNCONFIRMED. Phase 0 could not establish
    whether the conversion after an opponent defensive touchdown is included.
    The difference is one point, it only arises on a defensive score, and it has
    never been observed to change a band — but it is unconfirmed, and a band
    boundary is exactly where one point decides a payout. Recorded so the
    question is asked before a Pool settles on the boundary, not after.
    """
    return float(stats.get("dst_points_allowed") or 0.0)


# ── 0F-10 · pick six ─────────────────────────────────────────────────────────

def pick_six_passer_id(play: PlayRow) -> Any | None:
    """The passer charged with a pick six, or None.

    Both markers must be present in the play text, and the charge lands on the
    PASSER PARTICIPANT rather than on anyone named in the prose. Validated
    exactly on Matthew Stafford's week-17 interception returned for a touchdown,
    which is the difference between 12.76 and the 10.76 Yahoo paid.
    """
    text = play.text.upper()
    if "INTERCEPT" not in text or "TOUCHDOWN" not in text:
        return None
    ids = play.participant_ids(PARTICIPANT_PASSER)
    return ids[0] if ids else None


# ── 0F-11 · three-and-outs, and why they are fenced off ──────────────────────

def three_and_outs(plays: Sequence[PlayRow], *, home: str, visitor: str,
                   team: str) -> DerivedValue:
    """Three-and-outs forced by `team`. ALWAYS UNVERIFIED — see DerivedValue.

    The derivation: a possession that ends in a punt, earned no new first down,
    and ran no more than four plays. A possession's own series starts after any
    leading takeaway or any play entering with `start_down` ≥ 2, so a drive
    inherited mid-series is not counted as a three-and-out against the defence.

    IT IS RETURNED UNVERIFIED ON PURPOSE. Phase 0's sweep produced 1.19 per
    team-game against an NFL norm nearer 2.3. The punt counts underneath it
    matched the box score 47 times in 48, so the feed is sound and the RULE is
    uncalibrated: Yahoo's treatment of penalties, declined flags and drives that
    end a half is unknown, and `/plays` was additionally observed short by one
    event in 47 — immaterial to a field goal, material to this count.

    Nothing may settle on it until WP10's verification gate confirms it.
    """
    opponent = visitor if team == home else home
    possessions: list[list[PlayRow]] = []
    current: list[PlayRow] = []
    current_team: str | None = None

    for play, possession in carry_possession(plays, home=home, visitor=visitor):
        if possession != current_team:
            if current and current_team == opponent:
                possessions.append(current)
            current, current_team = [], possession
        current.append(play)
    if current and current_team == opponent:
        possessions.append(current)

    count = 0
    for possession in possessions:
        if not any(p.type == "punt" for p in possession):
            continue
        offensive = [p for p in possession if p.type not in ("punt", "kickoff")]
        if len(offensive) > 4:
            continue
        if any((p.start_down or 1) >= 2 for p in offensive[:1]):
            continue          # inherited mid-series; not a series this defence forced
        if any("FIRST DOWN" in p.text.upper() for p in offensive):
            continue
        count += 1

    return DerivedValue(
        value=float(count), verified=False,
        basis=f"three-and-outs forced by {team} derived from /plays sequencing",
        caveat="the threshold is PARTIAL: Phase 0 measured 1.19 per team-game "
               "against an NFL norm nearer 2.3, and /plays was short by one "
               "event in 47.")


# ── 0F-12 · the postseason week collision ────────────────────────────────────

def regular_season_only(games: Iterable[GameRow]) -> tuple[GameRow, ...]:
    """Drop postseason rows from a week-filtered `/games` result.

    WEEK NUMBERS ARE NOT UNIQUE. `weeks[]=1` returned 22 games — sixteen from
    September 2025 and six from January 2026 — because postseason numbering
    restarts at 1. Any week-filtered query against `/games`, `/stats` or
    `/team_stats` must say which half of the season it means. The `/fantasy/*`
    endpoints are clean: week 1 returned exactly 32 DST rows, all regular
    season, which is why nothing in the weekly-stats path calls this.
    """
    return tuple(game for game in games if not game.postseason)


# ── 0F-13 · plays never aggregate to a total ─────────────────────────────────

def refuse_play_aggregation(what: str = "player yardage") -> None:
    """A named refusal. Always raises.

    `stat_yardage` IS NOT THE PLAYER'S OFFICIAL YARDAGE. A Justin Herbert
    touchdown whose text read "for 23 yards" carried `stat_yardage: 15`, because
    a penalty was enforced between downs. Summing plays therefore produces a
    number that is close enough to look right and is not the figure Yahoo paid.
    `/stats` and `/fantasy/weekly_stats` carry the official totals.
    """
    raise ProviderParseError(
        f"refusing to derive {what} by summing plays. `stat_yardage` is not "
        f"official yardage — a penalty enforced between downs moves it — so "
        f"read /fantasy/weekly_stats or /stats instead.")


# ── the week ─────────────────────────────────────────────────────────────────

def build_week(*, league: ProviderLeague, week: int,
               player_stats: Sequence[ProviderPlayerStats] = (),
               observed_at: datetime | None = None) -> ProviderWeek:
    """A ProviderWeek carrying the parts BALLDONTLIE can actually speak to.

    THE LEAGUE IS SUPPLIED, NEVER INVENTED. BALLDONTLIE hosts no leagues, no
    fantasy teams and no rosters; it hosts facts about football. So `teams`,
    `matchups` and `roster_entries` stay EMPTY here rather than being filled
    with plausible-looking material, and the league identity is the one the
    caller is reading these facts FOR — a Yahoo league, in every case that
    matters. Composing the two sides is WP8's job at the composition boundary,
    and it is the right place for it: that is where the product already decides
    which feed answers for which league.

    An empty tuple is the true statement about what this provider knows of a
    fantasy matchup, and a ProviderWeek is the one aggregate persistence trusts
    to be internally consistent.
    """
    return ProviderWeek(
        league=league, week=int(week),
        teams=(), matchups=(), roster_entries=(),
        player_stats=tuple(player_stats),
        observed_at=observed_at,
    )


# ── the rule register ────────────────────────────────────────────────────────
#
# EVERY PHASE 0F ITEM, AND THE THING IN THIS MODULE THAT HONOURS IT. The
# certification suite asserts this table is complete and that each named
# callable exists — so a rule cannot be deleted, renamed or quietly stubbed
# without a gate going red.

RULES: tuple[tuple[str, str, str], ...] = (
    ("0F-1", "zero-valued fields are omitted entirely",
     "normalize_weekly_stats"),
    ("0F-2", "an empty stats block on a present row is a real zero",
     "normalize_weekly_stats"),
    ("0F-3", "an absent row is unevaluable; coverage is asserted at row level",
     "normalize_weekly_stats"),
    ("0F-4", "quarter scores use null for zero; never sum quarters",
     "final_score"),
    ("0F-5", "play ordering is not guaranteed; sort by wallclock",
     "ordered_plays"),
    ("0F-6", "a null team on a play is ordinary; skip rather than fail",
     "carry_possession"),
    ("0F-7", "possession is inverted on kicking plays; carry it forward",
     "carry_possession"),
    ("0F-8", "field goals are attributed by participant, never by team",
     "field_goal_kicker_id"),
    ("0F-9", "blocked-kick slugs lose the attempt distance; fall back to the "
             "summary endpoint", "field_goal_distance"),
    ("0F-10", "settle kickers from weekly_stats; /plays only for a multi-miss "
              "0–39 ambiguity", "kicker_settlement_source"),
    ("0F-11", "extra points and two-point conversions come from structured "
              "fields; never parse English", "extra_point_summary"),
    ("0F-12", "a pick six is INTERCEPT + TOUCHDOWN, charged to the passer "
              "participant", "pick_six_passer_id"),
    ("0F-13", "three-and-outs are PARTIAL and must stay behind the "
              "verification gate", "three_and_outs"),
    ("0F-14", "week numbers are not unique; filter postseason outside "
              "/fantasy/*", "regular_season_only"),
    ("0F-15", "stat_yardage is not official yardage; never aggregate plays",
     "refuse_play_aggregation"),
    ("0F-16", "the position vocabulary is not six values; normalise PK and FB",
     "fantasy_position"),
    ("0F-17", "a DST record carries player: null and is keyed by team",
     "subject_key"),
    ("0F-18", "coverage is measured from the payload, not from documentation",
     "supported_stats"),
    ("0F-19", "dst_points_allowed excludes opponent defensive touchdowns; the "
              "extra-point treatment is unconfirmed", "points_allowed"),
    ("0F-20", "zero-omission is a RESULT rule: an absent projection component "
              "was not forecast, and is never zero-filled",
     "normalize_projections"),
)
