"""E — Yahoo persistence. The implementation now lives in providers/persist.py.

WP2 MOVED IT AND LEFT THIS RE-EXPORT BEHIND ON PURPOSE. Every rule the module
enforced — the ingestion horizon, the pre-final update allowance, the post-final
freeze with its recorded ProviderConflict, the frozen season boundaries, the
two-layer serialization — was provider-neutral already. The single Yahoo-shaped
thing about it was `PROVIDER = "yahoo"`, and `providers/persist.py` now reads
that name off the snapshot's own `ProviderLeague.provider` instead.

NOTHING BELOW IS A SECOND IMPLEMENTATION. These are the same objects, imported.
The module survives because a dozen certified suites and the production Tuesday
job import `providers.yahoo.persist.refresh_league_week` by name, and rewriting
those imports would have made a package move look like a change to persistence
behaviour.

A DEMO CALLER MUST NOT COME THROUGH HERE — `providers/demo/` imports
`providers.persist` directly. One provider adapter importing another is the
fence WP2 draws.

`PROVIDER` is kept as the Yahoo name for the handful of callers that read it as
a constant.
"""

from __future__ import annotations

from providers.persist import (  # noqa: F401  (re-exported by design)
    CONFLICT_FINALITY_RETRACTION,
    CONFLICT_FROZEN_BOUNDARY,
    CONFLICT_POST_FINAL_SCORE,
    CONFLICT_POST_FINAL_WINNER,
    RefreshResult,
    acknowledge_conflict,
    conflict_key,
    open_conflicts,
    record_conflict,
    refresh_league_week,
    refresh_season,
    snapshot_digest,
)

# THE PRIVATE HELPERS ARE RE-EXPORTED TOO, and deliberately. The ECONCFG-F1
# certification exercises `_reconcile_boundary` DIRECTLY — populate once,
# no-op on a repeat, conflict on a contradiction — because that discipline is
# the reason `start_week` can be frozen at all, and testing it through a whole
# refresh would prove it only incidentally. A package move must not force a
# certified suite to be rewritten to keep asserting the same property.
from providers.persist import (  # noqa: F401,E402  (re-exported by design)
    _find_matchup,
    _persist_matchup,
    _persist_roster,
    _reconcile_boundary,
)

PROVIDER = "yahoo"
