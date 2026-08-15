"""Economic finality — the SOLE WRITER of Matchup.finalized_at (§7).

WP2 MOVED THE WRITER HERE FROM `providers/yahoo/finality.py`, AND SPLIT IT FROM
THE YAHOO STATUS MAPPING, which stays there. The split follows the one real
seam in the original module:

    finality_from_status()   YAHOO-SPECIFIC. "postevent" is a Yahoo word.
    apply_finality()         PROVIDER-NEUTRAL. It takes a `Finality` tristate
    assert_never_retracted() and a row, and knows nothing about any provider.

Every provider must reach `finalized_at` through the same writer or §7's
one-writer property is a claim rather than a fact — and C-7 proves it by
scanning the whole repository for a second assignment. Leaving the writer inside
the Yahoo package would have forced the Demo provider either to import Yahoo or
to write the column itself; the first is a fence violation and the second breaks
C-7 outright.

`Matchup.finalized_at` is the only economically authoritative internal finality
signal.

THE TRUTH TABLE (§7), implemented literally below:

    provider explicitly final          -> finalized_at set
    provider explicitly non-final      -> finalized_at NULL
    provider finality absent/unknown   -> finalized_at NULL
    final 0-0                          -> finalized_at set
    scores present, no final signal    -> finalized_at NULL

WHAT MAY NOT BE READ. Not the score, not whether the score is non-null, not a
0-0, not refreshed_at, not elapsed time, not the presence of the row, not the
presence of a payload, not the local clock, and not the number of times a
provider has been polled.

ONCE SET, NEVER RETURNED TO NULL. `apply_finality` refuses to clear a finalized
row. A provider that later reports a finalized matchup as non-final is not
retracting finality — it is CONTRADICTING it, which is S6-R3's case: the stored
value stands, a ProviderConflict is recorded by the caller, and the refresh
fails closed.

THE TIMESTAMP IS NOT THE SIGNAL. `finalized_at` records WHEN finality was
observed; the SIGNAL is the provider's affirmative status. A timestamp derived
from the ingest clock is fine precisely because nothing reads its VALUE to
decide finality — only its NULL-ness, which is set from the status.
"""

from __future__ import annotations

from datetime import datetime

from providers.base import Finality
from providers.errors import ProviderFinalityError


def apply_finality(matchup, finality: Finality, *, observed_at: datetime):
    """THE SOLE WRITER of Matchup.finalized_at. Returns (changed, retraction).

    `changed`     True when this call set finalized_at that was NULL.
    `retraction`  True when the provider reported non-final for a matchup that
                  is ALREADY final. Nothing is written in that case; the caller
                  records the S6-R3 conflict and fails closed. It is returned
                  rather than raised so the caller can record the conflict row
                  in the same transaction before refusing.

    Idempotent: a repeat FINAL on an already-final row is a no-op returning
    (False, False), which is what makes C-9's replay produce identical state.
    """
    already_final = matchup.finalized_at is not None

    if finality.is_affirmatively_final:
        if already_final:
            return (False, False)
        if observed_at is None:
            raise ProviderFinalityError(
                "apply_finality was asked to set finalized_at with no "
                "observed_at. The column must record WHEN finality was "
                "observed; substituting the local clock here would make the "
                "value depend on ingest timing rather than on the provider.")
        matchup.finalized_at = observed_at
        return (True, False)

    # Non-final or unknown. Both leave finalized_at exactly as it is — which
    # means NULL stays NULL, and a set value is NEVER cleared (§7, invariant).
    if already_final:
        return (False, True)
    return (False, False)


def assert_never_retracted(before, after) -> None:
    """Guard used by certification (C-7) and by the persistence tail.

    Reads two snapshots of the same row's finalized_at and refuses any
    transition out of non-NULL. Cheap enough to run on every persist, and it
    catches a regression introduced anywhere — including in code that never
    imported apply_finality.
    """
    if before is not None and after is None:
        raise ProviderFinalityError(
            "finalized_at was returned to NULL. §7 makes economic finality "
            "irreversible: once a result is final it may be CONTRADICTED — "
            "which is recorded as a ProviderConflict and fails closed — but it "
            "is never un-finalized.")
