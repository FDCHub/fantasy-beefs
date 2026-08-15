"""F — Yahoo finality. ONE mapping; the WRITER now lives in providers/finality.

WP2 SPLIT THIS MODULE ALONG ITS ONE REAL SEAM. `apply_finality` and
`assert_never_retracted` moved to `providers/finality.py` because they are
provider-neutral — they take a `Finality` tristate and a row, and no Yahoo word
appears in either. What stays here is the part that IS Yahoo: the mapping from
Yahoo's own status vocabulary onto the economic tristate.

BOTH ARE RE-EXPORTED so every existing importer — the certification harness, the
persistence tail, the Sprint 6 suites — keeps working unchanged, and so C-7's
sole-writer scan still finds this file in its permitted list alongside the new
one. There is exactly one implementation of the writer, in one file.

`finality_from_status` TAKES THE STATUS STRING AND NOTHING ELSE. It has no
`scores` parameter, no `refreshed_at` parameter and no clock, so none of those
inferences is even expressible here. That is the point of the signature.
"""

from __future__ import annotations

from providers.base import Finality
from providers.finality import (  # noqa: F401  (re-exported by design)
    apply_finality,
    assert_never_retracted,
)
from providers.yahoo.parse import (
    STATUS_MIDEVENT,
    STATUS_POSTEVENT,
    STATUS_PREEVENT,
)

#: Yahoo status -> the economic tristate. The ONLY affirmative-final value is
#: "postevent"; everything else is non-final, and anything unrecognized is
#: UNKNOWN rather than being optimistically bucketed.
_STATUS_TO_FINALITY = {
    STATUS_POSTEVENT: Finality.FINAL,
    STATUS_MIDEVENT: Finality.NOT_FINAL,
    STATUS_PREEVENT: Finality.NOT_FINAL,
}


def finality_from_status(status: str | None) -> Finality:
    """Map a raw Yahoo status string to the economic tristate.

    Takes the status and nothing else — deliberately. There is no `scores`
    parameter, no `refreshed_at` parameter and no clock, so no future edit can
    quietly start inferring finality from one of them without changing this
    signature and tripping every caller.

    An unrecognized, empty or absent status is UNKNOWN. Yahoo adding a fourth
    status value must not silently become "final"; it becomes "we could not
    tell", which keeps finalized_at NULL and money unmoved.
    """
    if status is None:
        return Finality.UNKNOWN
    return _STATUS_TO_FINALITY.get(str(status).strip().lower(),
                                   Finality.UNKNOWN)
