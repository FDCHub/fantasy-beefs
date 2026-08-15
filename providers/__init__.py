"""Provider gateway — the provider-neutral layer, and one package per provider.

THE PROVIDER LAYER TOUCHES NO MONEY. Nothing under providers/ may import from
`ledger/` or `economy/`, and no path in it posts a ledger entry. The gateway
supplies FACTS — identities, scores, finality, roster slots, stats, brackets —
and the accepted engines remain the only things that move a cent.

That separation is asserted mechanically, not just documented: C-15 replays a
full recorded Yahoo season through this package and proves the ledger is
untouched, C-19 does the same for a full Demo season, and providers/certify/run.py
additionally walks every module here for a forbidden import.

── THE SHAPE, AFTER WP2 ─────────────────────────────────────────────────────

    base.py               the DTOs and the transport protocol
    errors.py             every named refusal
    identity.py           provider key -> internal row, for ANY provider
    finality.py           THE sole writer of Matchup.finalized_at
    persist.py            THE guarded score/winner writer, horizon, conflicts
    week_stat_source.py   the PoolStatSource over a ProviderWeek
    postseason_bracket.py the bracket-classification capability registry
    incident.py           the named refusal taxonomy and its emitter
    diagnosis.py          "why is this week stuck?", as a pure read

    yahoo/                transport, parse, normalize, the Yahoo stat map, and
                          the Yahoo defaults over the neutral modules above
    demo/                 a deterministic runtime provider: scenario, source,
                          stat map, bracket source
    fixtures/             the recorded corpus, its scrubber and its replay
    certify/              the offline certification gate

WP2 MOVED IDENTITY, FINALITY AND PERSISTENCE OUT OF `yahoo/` AND CHANGED NOTHING
ABOUT WHAT THEY DO. None of the three was ever Yahoo-specific — each read a
provider name it was handed and applied the same rule — and living inside the
Yahoo package meant a second provider could only reuse them by importing Yahoo.
`yahoo/identity.py`, `yahoo/finality.py` and `yahoo/persist.py` remain as the
Yahoo-defaulting face of the same objects, so every existing importer is
unaffected and there is exactly one implementation of each.

ONE PROVIDER PACKAGE NEVER IMPORTS ANOTHER. `demo/` imports `providers.identity`
and `providers.persist`, never `providers.yahoo.*`. That fence is what keeps the
branch on provider identity confined to the composition layer, where the API
connects a league to its feed.
"""
