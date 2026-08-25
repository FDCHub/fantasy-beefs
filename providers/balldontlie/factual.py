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


#: Text markers for an awarded first down. BALLDONTLIE writes them into the play
#: text — "FIRST DOWN", and the penalty form — and there is no structured field
#: for it, so the text is read HERE and nowhere else in the codebase.
FIRST_DOWN_MARKERS = ("FIRST DOWN", "1ST DOWN")

_TERMINATING = {
    "punt": DriveOutcome.PUNT,
    "field-goal-good": DriveOutcome.FIELD_GOAL,
    "field-goal-missed": DriveOutcome.MISSED_FIELD_GOAL,
    "blocked-field-goal": DriveOutcome.MISSED_FIELD_GOAL,
    "blocked-field-goal-touchdown": DriveOutcome.TURNOVER,
    "interception": DriveOutcome.TURNOVER,
    "fumble": DriveOutcome.TURNOVER,
    "fumble-recovery-opponent": DriveOutcome.TURNOVER,
    "safety": DriveOutcome.TURNOVER,
    "downs": DriveOutcome.DOWNS,
    "turnover-on-downs": DriveOutcome.DOWNS,
}

_PERIOD_END = {"end-of-half", "end-of-game", "end-of-quarter",
               "end-of-regulation", "two-minute-warning"}

_NON_SNAP = {"kickoff", "timeout", "penalty-no-play", "two-minute-warning",
             "end-of-half", "end-of-game", "end-of-quarter",
             "end-of-regulation"}

_TOUCHDOWN_MARKER = "TOUCHDOWN"
_KNEEL_MARKERS = ("KNEEL", "KNEELS", "VICTORY FORMATION")
_TURNOVER_MARKERS = ("INTERCEPT", "FUMBLE")


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

        if play.type in _PERIOD_END:
            if current.outcome == DriveOutcome.UNKNOWN:
                current.outcome = DriveOutcome.END_OF_PERIOD
            continue

        if play.type not in _NON_SNAP:
            current.offensive_play_count += 1

        if any(marker in text for marker in FIRST_DOWN_MARKERS):
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
    for play in ordered_plays(plays):
        text = (play.text or "").upper()
        if "INTERCEPT" not in text:
            continue
        passers = play.participant_ids(PARTICIPANT_PASSER)
        if not passers:
            # An interception the stream cannot attribute contributes to
            # NEITHER term. Counting it in the denominator alone would push
            # every quarterback's rate down.
            continue
        passer = passers[0]
        interceptions[passer] = interceptions.get(passer, 0) + 1
        if _TOUCHDOWN_MARKER in text:
            pick_sixes[passer] = pick_sixes.get(passer, 0) + 1
    return {"interceptions": interceptions, "pick_sixes": pick_sixes,
            "unattributed": 0}
