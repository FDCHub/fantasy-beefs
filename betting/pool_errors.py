"""
Named Pool domain errors — POR Rev1.3 §6.2, Scope §C6/§C9.

"A bare ValueError is not acceptable" (§C6). Every fail-closed classification
raises a NAMED error carrying definition key, league, season, week,
classification and the census counts, so an operator reading a refusal knows
what happened without re-running anything.

THE CLASS HIERARCHY IS THE RULING, NOT DECORATION. POR §6.2 makes
INVARIANT_VIOLATION distinct in kind from the three data conditions:

    "INVARIANT_VIOLATION carries a distinct error type. Its cause is the
     evaluator, not the data. It is not resolved by waiting, and it must be
     distinguishable on the error surface from the three data conditions."

So there are two sibling branches under one root, never one flat family:

    PoolSettlementRefusedError            -- refuse; nothing posted, ever
      +- PoolDataConditionError           -- RETRY once the data arrives
      |    +- NoSubjectsError
      |    +- NoEvaluableSubjectsError
      |    +- IncompleteFieldError
      +- PoolInvariantViolationError      -- DO NOT retry; the evaluator is wrong

Collapsing the two branches would leave an operator waiting for data that
already arrived. A caller that wants "any refusal" catches the root; a caller
that wants "retry when the feed catches up" catches PoolDataConditionError and
gets exactly the three conditions retry can fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class SubjectCensus:
    """POR §6.2 — the census a settlement decision is made from.

    `subjects_claiming` is None until it is legitimately computable. §6.2,
    binding: "subjects_claiming is computed only once subjects_evaluated ==
    subjects_considered. A claim count over an incomplete field is not computed,
    not stored, and not logged." None is that state made unrepresentable-as-zero
    — a plain 0 would be indistinguishable from a real zero-claim result.
    """

    subjects_considered: int
    subjects_evaluated: int
    subjects_claiming: int | None = None

    def as_dict(self) -> dict:
        return {
            "subjects_considered": self.subjects_considered,
            "subjects_evaluated": self.subjects_evaluated,
            "subjects_claiming": self.subjects_claiming,
        }


class PoolSettlementRefusedError(Exception):
    """Root of every fail-closed settlement refusal.

    Catching this guarantees: no posting occurred, no rollover was written, no
    sweep happened, and the instance was NOT marked settled. The refusal is
    total — §6.2: "The settlement transaction is refused. Nothing partial
    survives."
    """

    #: Overridden by each subclass; mirrors the POR §6.2 classification name.
    classification: str = "REFUSED"

    def __init__(self, *, definition_key: str, league_id: int, season: int,
                 week: int, census: SubjectCensus,
                 unevaluable_subject_ids: Sequence[object] = (),
                 detail: str = "") -> None:
        self.definition_key = definition_key
        self.league_id = league_id
        self.season = season
        self.week = week
        self.census = census
        self.unevaluable_subject_ids = tuple(unevaluable_subject_ids)
        self.detail = detail
        super().__init__(
            f"[{self.classification}] definition={definition_key!r} "
            f"league={league_id} season={season} week={week} "
            f"considered={census.subjects_considered} "
            f"evaluated={census.subjects_evaluated} "
            f"claiming={census.subjects_claiming}"
            + (f" unevaluable={list(self.unevaluable_subject_ids)}"
               if self.unevaluable_subject_ids else "")
            + (f" -- {detail}" if detail else "")
        )

    def as_dict(self) -> dict:
        """Audit payload. Carries exactly what §6.2 requires a refusal to
        carry, so a caller logging this dict cannot omit a required field."""
        return {
            "classification": self.classification,
            "definition_key": self.definition_key,
            "league_id": self.league_id,
            "season": self.season,
            "week": self.week,
            "unevaluable_subject_ids": list(self.unevaluable_subject_ids),
            **self.census.as_dict(),
        }


class PoolDataConditionError(PoolSettlementRefusedError):
    """A refusal caused by absent structure or absent data.

    POR §6.2: "the remedy is retry once the missing structure or data is
    present." Every subclass here is transient in principle."""


class NoSubjectsError(PoolDataConditionError):
    classification = "NO_SUBJECTS"


class NoEvaluableSubjectsError(PoolDataConditionError):
    classification = "NO_EVALUABLE_SUBJECTS"


class IncompleteFieldError(PoolDataConditionError):
    """subjects_evaluated < subjects_considered.

    THERE IS NO COMPLETENESS THRESHOLD (POR §6.2, binding). One unevaluable
    subject out of a full field refuses the whole settlement, because that
    subject could have held the extremum or met the threshold and no
    completeness short of the full field excludes that possibility.

    This error additionally carries the identity of the unevaluable subjects —
    the only classification for which §6.2 requires it."""

    classification = "INCOMPLETE_FIELD"


class PoolInvariantViolationError(PoolSettlementRefusedError):
    """A complete RANK_EXTREMUM field produced zero claimants.

    NOT a data condition and NOT retryable. A RANK_EXTREMUM definition resolves
    to a winner or a tie for any valid non-empty subject set, so zero claimants
    over a fully evaluated non-empty field means the evaluator is wrong. POR
    §6.2 row 6 takes precedence over row 4 precisely so this never silently
    becomes a rollover."""

    classification = "INVARIANT_VIOLATION"


# Classification -> exception, so the census gate maps its own result table to
# an error without a chain of ifs that could drift from the table.
REFUSAL_ERRORS: dict[str, type[PoolSettlementRefusedError]] = {
    NoSubjectsError.classification: NoSubjectsError,
    NoEvaluableSubjectsError.classification: NoEvaluableSubjectsError,
    IncompleteFieldError.classification: IncompleteFieldError,
    PoolInvariantViolationError.classification: PoolInvariantViolationError,
}