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

    nfl_teams.py          canonical NFL team and fantasy position identity, and
                          the per-provider dialects that spell them differently
    cross_identity.py     one canonical `players` row <-> one subject at a
                          SECOND provider: normalization, fail-closed discovery,
                          and the durable `provider_player_alias` mapping
    balldontlie_identity.py
                          BALLDONTLIE subject rows -> the neutral records
                          cross_identity compares. No HTTP, no key: WP2 owns the
                          transport and hands its decoded payloads to this

    yahoo/                transport, parse, normalize, the Yahoo stat map, and
                          the Yahoo defaults over the neutral modules above
    balldontlie/          transport, parse, normalize for the FACTUAL provider:
                          a paced, cached client that never works around a rate
                          limit, and the Phase 0F rules its payload requires
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

WP1 ADDED CROSS-PROVIDER IDENTITY, AND IT IS NOT `identity.py`. `identity.py`
answers "which of OUR rows is this provider key", which every provider needs and
which is settled by a key we already stored. `cross_identity.py` answers a
question no single provider can: "which subject at ANOTHER provider is the same
human being as this one" — a question that starts from names because the two
providers share no identifier at all. It fails closed on every ambiguity and,
once it has answered, records the answer so the names are never read again.

ONE PROVIDER PACKAGE NEVER IMPORTS ANOTHER. `demo/` imports `providers.identity`
and `providers.persist`, never `providers.yahoo.*`. That fence is what keeps the
branch on provider identity confined to the composition layer, where the API
connects a league to its feed.

WP2 ADDED A PROVIDER THAT HOSTS NO LEAGUE, AND THE FENCE HOLDS DIFFERENTLY FOR
IT. Yahoo answers "who played whom, and who won"; BALLDONTLIE answers "what
happened on the field". It has no league, no fantasy team and no roster, so
`balldontlie/normalize.build_week` fills in the facts and leaves `teams`,
`matchups` and `roster_entries` EMPTY rather than inventing a league to put them
in. Which feed answers for which league stays where it already lives — the
composition layer — and joining a BALLDONTLIE fact to a Yahoo roster is what
`cross_identity.py` exists to make safe.
"""
