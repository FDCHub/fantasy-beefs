"""Sprint 5 · factual identification from play-by-play — drives and pick-sixes.

WHY THIS EXISTS SEPARATELY FROM WP2's normalize.py. WP2 answers "what did this
play say"; this module answers "what happened across a sequence of plays". A
drive is not a field in any payload — it is a classification over an ordered
possession, and getting it wrong is how a defence is paid for a three-and-out it
never forced.

── THE THREE-AND-OUT DEFINITION, STATED BEFORE IT IS IMPLEMENTED ───────────

A possession is a three-and-out when ALL of the following hold:

    1. the offence STARTS the possession — it is not inheriting a series
       already in progress after a turnover or a change of downs
    2. it earns NO first down
    3. it ends by PUNTING

Everything else is excluded, and each exclusion exists because counting it would
pay a defence for the wrong event:

    A TURNOVER is not a three-and-out. An interception on second down is a
    better defensive outcome, and Yahoo scores it separately — counting it here
    would pay twice for one play.

    A TOUCHDOWN or FIELD GOAL obviously is not one, however few plays it took.

    A POSSESSION ENDING A HALF OR GAME is not one. A team kneeling out the clock
    runs three plays and does not punt; a team taking over with nine seconds
    left never had a chance to earn a first down. Neither is a defensive
    achievement.

    A DOWNS TURNOVER is not one either — the offence went for it on fourth
    rather than punting, which is a different event with a different scoreline
    behind it.

    A PENALTY FIRST DOWN ends the series exactly as a earned one does. The
    stream marks it in the play text, and it counts.

── WHAT THIS MODULE REFUSES TO DO ──────────────────────────────────────────

IT DOES NOT COUNT PUNTS. Punts per game is a plausible-looking proxy that
differs from three-and-outs by every drive that punted after picking up a first
down — roughly half of them. Phase 0's own derivation was PARTIAL precisely
because its threshold was fitted rather than defined, and reproducing that with
a simpler rule would be worse, not better.

IT DOES NOT GUESS WHEN THE STREAM IS INCOMPLETE. `/plays` was measured short by
one event in 47. A possession whose terminating play is missing is classified
UNKNOWN and excluded from both the numerator and the denominator, so an
incomplete game lowers the sample size rather than corrupting the rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from providers.balldontlie.normalize import (
    PARTICIPANT_PASSER,
    carry_possession,
    ordered_plays,
)

__all__ = [
    "Drive",
    "DriveOutcome",
    "FIRST_DOWN_MARKERS",
    "classify_drives",
    "pick_six_events",
    "three_and_outs_forced",
]


class DriveOutcome:
    """How a possession ended. Only PUNT can be a three-and-out."""

    PUNT = "PUNT"
    TOUCHDOWN = "TOUCHDOWN"
    FIELD_GOAL = "FIELD_GOAL"
    MISSED_FIELD_GOAL = "MISSED_FIELD_GOAL"
    TURNOVER = "TURNOVER"
    DOWNS = "DOWNS"
    END_OF_PERIOD = "END_OF_PERIOD"
    #: The stream did not say. Excluded from numerator AND denominator.
    UNKNOWN = "UNKNOWN"


#: Legacy text markers for an awarded first down. RETAINED ONLY FOR OLDER
#: CAPTURED CORPORA — the live stream does not use them. Sprint 5B read 1,199
#: consecutive real plays and found the words "FIRST DOWN" in exactly none of
#: them; the live signal is `end_down == 1`, handled in `_earned_first_down`.
FIRST_DOWN_MARKERS = ("FIRST DOWN", "1ST DOWN")

# ── THE LIVE TYPE VOCABULARY, MEASURED RATHER THAN GUESSED ──────────────────
#
# Every slug below was observed in real `/plays` payloads during Sprint 5B.
# The names WP2 originally guessed — "interception", "fumble", "downs",
# "end-of-quarter", "penalty-no-play" — are NOT what the provider emits, and
# the two spellings that happened to coincide ("punt", "field-goal-good") hid
# that for two sprints. Legacy spellings are kept alongside the live ones so
# older captured corpora keep classifying.
#
# ANYTHING NOT LISTED HERE LEAVES THE DRIVE `UNKNOWN`, which excludes it from
# both halves of every rate. That is the fail-closed direction: an unrecognised
# ending must never be read as "the offence punted".

_TERMINATING = {
    # punts — the ordinary three-and-out ending
    "punt": DriveOutcome.PUNT,
    # a blocked punt is NOT a clean punt: possession changes by a route the
    # three-and-out definition does not describe, so it is excluded rather
    # than counted as a defensive stop.
    "blocked-punt": DriveOutcome.TURNOVER,
    "blocked-punt-touchdown": DriveOutcome.TURNOVER,
    "punt-return-touchdown": DriveOutcome.TURNOVER,
    # kicks
    "field-goal-good": DriveOutcome.FIELD_GOAL,
    "field-goal-missed": DriveOutcome.MISSED_FIELD_GOAL,
    "field-goal-blocked": DriveOutcome.MISSED_FIELD_GOAL,
    "blocked-field-goal": DriveOutcome.MISSED_FIELD_GOAL,
    "blocked-field-goal-touchdown": DriveOutcome.TURNOVER,
    # turnovers — LIVE spellings first
    "pass-interception-return": DriveOutcome.TURNOVER,
    "interception-return-touchdown": DriveOutcome.TURNOVER,
    "fumble-recovery-opponent": DriveOutcome.TURNOVER,
    "fumble-return-touchdown": DriveOutcome.TURNOVER,
    "safety": DriveOutcome.TURNOVER,
    # legacy fixture spellings
    "interception": DriveOutcome.TURNOVER,
    "fumble": DriveOutcome.TURNOVER,
    # scores by the offence
    "rushing-touchdown": DriveOutcome.TOUCHDOWN,
    "passing-touchdown": DriveOutcome.TOUCHDOWN,
    # downs
    "turnover-on-downs": DriveOutcome.DOWNS,
    "downs": DriveOutcome.DOWNS,
}

#: `fumble-recovery-own` deliberately absent: the offence keeps the ball and
#: the drive continues.

#: Endings that genuinely END a possession. `end-period` is NOT one of them:
#: it marks the quarter boundary, and a drive runs straight through the end of
#: the first and third quarters. Sprint 5B measured its `end_down` as 2, 3 or 4
#: as often as 1 — a drive in progress, not a drive finished. Treating it as an
#: ending closed roughly two live drives per game in the wrong place.
_PERIOD_END = {"end-of-half", "end-of-game", "end-of-regulation",
               "end-of-quarter"}

_NON_SNAP = {"kickoff", "kickoff-return-offense", "kickoff-return-touchdown",
             "timeout", "official-timeout", "penalty", "penalty-no-play",
             "two-minute-warning", "end-period", "coin-toss"}

#: Slugs that identify an interception THROWN, and the subset returned for six.
#: Structural, not textual: the live stream names the intercepting defender in
#: the prose and the quarterback only in `participants`.
INTERCEPTION_SLUGS = frozenset({"pass-interception-return",
                                "interception-return-touchdown"})
PICK_SIX_SLUGS = frozenset({"interception-return-touchdown"})

_TOUCHDOWN_MARKER = "TOUCHDOWN"
_KNEEL_MARKERS = ("KNEEL", "KNEELS", "VICTORY FORMATION")
_TURNOVER_MARKERS = ("INTERCEPT", "FUMBLE")



_KNOWN_SLUGS = (frozenset(_TERMINATING) | _PERIOD_END | _NON_SNAP
                | INTERCEPTION_SLUGS | PICK_SIX_SLUGS
                | {"rush", "pass-reception", "pass-incompletion", "sack",
                   "fumble-recovery-own", "extra-point-good",
                   "extra-point-missed", "two-point-conversion"})


def _earned_first_down(play, text: str) -> bool:
    """Did this play produce a first down?

    THE LIVE SIGNAL IS `end_down == 1`. A play that leaves the offence on first
    down converted; one that leaves them on second, third or fourth did not. A
    touchdown shows `end_down == -1` and is handled as a score, not a
    conversion. The text markers are checked only when the stream carries no
    `end_down` at all, which is how pre-Sprint-5B captured corpora look.
    """
    # A PLAY THAT HANDS THE BALL OVER NEVER CONVERTS FOR THE OFFENCE. On a
    # punt the stream reports `end_down == 1` because the RECEIVING team is
    # about to snap first-and-ten, and on an interception likewise. Reading
    # that as a conversion credited every punting drive with a first down and
    # made three-and-outs literally uncountable — 45 punts, zero found.
    if play.type in _TERMINATING:
        return False
    end_down = getattr(play, "end_down", None)
    if isinstance(end_down, int):
        return end_down == 1
    return any(marker in text for marker in FIRST_DOWN_MARKERS)


@dataclass
class Drive:
    """One possession, classified."""

    team: str | None
    plays: list = field(default_factory=list)
    outcome: str = DriveOutcome.UNKNOWN
    earned_first_down: bool = False
    inherited: bool = False
    kneel_down: bool = False
    offensive_play_count: int = 0
    #: Set once a terminating play is seen. A CLOSED drive never takes another
    #: play, even if possession has not changed hands in the stream yet — the
    #: interception that ends a drive must not be overwritten by the field goal
    #: the same team kicks two possessions later.
    closed: bool = False

    @property
    def is_three_and_out(self) -> bool:
        """The definition in the module docstring, and nothing looser."""
        return (self.outcome == DriveOutcome.PUNT
                and not self.earned_first_down
                and not self.inherited
                and not self.kneel_down
                and self.offensive_play_count <= 4)

    @property
    def counts_toward_sample(self) -> bool:
        """Whether this drive belongs in a rate's DENOMINATOR.

        A drive whose ending the stream never reported cannot be judged either
        way. Excluding it from both halves of the fraction lowers the sample
        size honestly; leaving it in the denominator alone would quietly bias
        every rate downward.
        """
        return (self.outcome not in (DriveOutcome.UNKNOWN,
                                     DriveOutcome.END_OF_PERIOD)
                and not self.kneel_down)

    def as_dict(self) -> dict:
        return {"team": self.team, "outcome": self.outcome,
                "earned_first_down": self.earned_first_down,
                "inherited": self.inherited, "kneel_down": self.kneel_down,
                "offensive_plays": self.offensive_play_count,
                "three_and_out": self.is_three_and_out,
                "counts": self.counts_toward_sample}


def classify_drives(plays: Sequence, *, home: str, visitor: str) -> list:
    """An ordered play stream -> classified possessions.

    Possession comes from WP2's `carry_possession`, which already undoes the
    kicking-play inversion (`play.team` is the RECEIVING team on a punt) and
    survives a null team. This module adds only the drive-level questions:
    where did a possession start, did it earn a first down, and how did it end.
    """
    drives: list[Drive] = []
    current: Drive | None = None

    for play, possession in carry_possession(plays, home=home, visitor=visitor):
        text = (play.text or "").upper()

        # ── A PERIOD ENDING CLOSES THE DRIVE IT INTERRUPTS ─────────────────
        if play.type in _PERIOD_END:
            if current is not None and current.outcome == DriveOutcome.UNKNOWN:
                current.outcome = DriveOutcome.END_OF_PERIOD
                current.closed = True
            continue

        # ── A NON-SNAP NEVER STARTS, JOINS OR SPLITS A POSSESSION ──────────
        # Kickoffs, timeouts, official timeouts and penalty records all carry a
        # `team`, and treating that as possession invented a one-play drive
        # every time one appeared: real games classified at 16.5 drives per
        # team-game against a true figure near 11, and a third of all drives
        # ended UNKNOWN holding nothing but a kickoff. They are skipped
        # entirely — the drive on either side of them is the same drive.
        if play.type in _NON_SNAP:
            continue

        # ── TURNOVER ON DOWNS HAS NO SLUG. IT IS A TEAM FLIP ON FOURTH ────
        # The provider emits no `turnover-on-downs` type at all: a failed
        # fourth-down conversion is an ordinary `rush` or `pass-reception`
        # whose `team` has already become the team taking over, with
        # `end_down == 1` for their new series. Sprint 5B measured all fifteen
        # fourth-down scrimmage plays in the sample reading `end_down == 1`
        # whether they converted or not — so the down cannot distinguish them
        # and only the team flip can. Missing this left the drive with no
        # ending, which is most of what remained UNKNOWN.
        if (current is not None and not current.closed
                and current.team is not None
                and play.start_down == 4
                and possession != current.team
                and play.type not in _TERMINATING
                and play.type not in _NON_SNAP):
            current.plays.append(play)
            current.offensive_play_count += 1
            current.outcome = DriveOutcome.DOWNS
            current.closed = True
            continue

        if current is None or possession != current.team or current.closed:
            current = Drive(team=possession)
            drives.append(current)
            # A POSSESSION THAT BEGINS MID-SERIES IS INHERITED. A takeaway hands
            # the ball over at whatever down the previous series reached, and a
            # defence has not "forced" a three-and-out against a series it did
            # not start. `start_down >= 2` on the first snap is how the stream
            # shows it.
            if (play.start_down or 1) >= 2:
                current.inherited = True

        current.plays.append(play)

        current.offensive_play_count += 1

        if _earned_first_down(play, text):
            current.earned_first_down = True
        if any(marker in text for marker in _KNEEL_MARKERS):
            current.kneel_down = True

        if _TOUCHDOWN_MARKER in text and not any(
                marker in text for marker in _TURNOVER_MARKERS):
            current.outcome = DriveOutcome.TOUCHDOWN
            current.closed = True
            continue

        outcome = _TERMINATING.get(play.type)
        if outcome is not None:
            current.outcome = outcome
            current.closed = True
            continue
        if any(marker in text for marker in _TURNOVER_MARKERS) and (
                "RECOVERED BY" in text or "INTERCEPTED" in text):
            current.outcome = DriveOutcome.TURNOVER
            current.closed = True

    return drives


def three_and_outs_forced(plays: Sequence, *, home: str, visitor: str,
                          team: str) -> dict:
    """Three-and-outs `team`'s DEFENCE forced, with the sample behind them.

    Returns the count AND the opponent drive count, because a rate needs both:
    three in a game where the opponent had nine drives is a very different
    defence from three in a game where they had fourteen.
    """
    opponent = visitor if team == home else home
    drives = classify_drives(plays, home=home, visitor=visitor)
    opponent_drives = [d for d in drives if d.team == opponent]
    counted = [d for d in opponent_drives if d.counts_toward_sample]
    forced = [d for d in counted if d.is_three_and_out]
    return {
        "team": team, "opponent": opponent,
        "three_and_outs": len(forced),
        "opponent_drives": len(counted),
        "excluded_drives": len(opponent_drives) - len(counted),
        "drives": [d.as_dict() for d in opponent_drives],
    }


def pick_six_events(plays: Sequence) -> dict:
    """Interceptions and pick-sixes, per passer, from the play stream.

    THE FACTUAL HALF OF THE PICK-SIX MODEL. A conditional rate needs both terms
    measured the same way — interceptions thrown and, of those, how many were
    returned for a touchdown — and both are read from the same ordered stream so
    they cannot disagree about which plays existed.

    ATTRIBUTION IS BY PASSER PARTICIPANT, never by team and never from the
    prose. WP2 validated exactly that on Matthew Stafford, where the play text
    names the intercepting defender and the participant names the quarterback
    who threw it.
    """
    interceptions: dict = {}
    pick_sixes: dict = {}
    unattributed = 0
    for play in ordered_plays(plays):
        text = (play.text or "").upper()
        kind = play.type

        # THE SLUG IS THE EVIDENCE, NOT THE PROSE. `pass-interception-return`
        # and `interception-return-touchdown` are the provider's own names for
        # these two events; the older text search for "INTERCEPT" also matched
        # a description mentioning an earlier interception, and could not tell
        # a returned touchdown from a two-point return without re-reading the
        # sentence. The legacy text path survives only for corpora captured
        # before the live slugs were known.
        is_interception = kind in INTERCEPTION_SLUGS or (
            kind not in _KNOWN_SLUGS and "INTERCEPT" in text)
        if not is_interception:
            continue

        passers = play.participant_ids(PARTICIPANT_PASSER)
        if not passers:
            # An interception the stream cannot attribute contributes to
            # NEITHER term. Counting it in the denominator alone would push
            # every quarterback's rate down.
            unattributed += 1
            continue
        passer = passers[0]
        interceptions[passer] = interceptions.get(passer, 0) + 1
        returned_for_six = (kind in PICK_SIX_SLUGS
                            or (kind not in _KNOWN_SLUGS
                                and _TOUCHDOWN_MARKER in text))
        if returned_for_six:
            pick_sixes[passer] = pick_sixes.get(passer, 0) + 1
    return {"interceptions": interceptions, "pick_sixes": pick_sixes,
            "unattributed": unattributed}
