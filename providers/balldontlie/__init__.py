"""BALLDONTLIE — the second provider package (WP2).

WHAT THIS PACKAGE IS. A client for BALLDONTLIE's NFL v1 API and the two layers
that turn its payloads into this repository's neutral records: a paced, cached
transport that returns raw payload material, a parser that reads BALLDONTLIE's
envelope and nothing else, and a normalizer that applies the Phase 0F rules and
emits `providers.base` DTOs.

    transport.py   HTTP, credentials, pacing, caching, pagination, rate limits
    parse.py       BALLDONTLIE's envelope -> plain typed rows. No rules.
    normalize.py   the Phase 0F rules -> ProviderPlayerStats / ProviderWeek

── WHAT THIS PACKAGE IS NOT, AND WHY EACH LINE MATTERS ──────────────────────

IT IS NOT A LEAGUE. Yahoo hosts leagues; BALLDONTLIE hosts FACTS. There is no
BALLDONTLIE league, no BALLDONTLIE fantasy team, and no BALLDONTLIE roster, so
nothing here manufactures one. `normalize.build_week` takes the
`ProviderLeague` it is given — the Yahoo league the facts are being read FOR —
and fills in only the parts BALLDONTLIE can actually speak to. A `ProviderWeek`
carrying an invented league would be a lie told in the one aggregate persistence
trusts.

IT DOES NOT SETTLE ANYTHING. No scoring rule, no league profile, no points. The
component -> points evaluator is WP4 and the settlement seam is WP9; this layer
stops at "here is what BALLDONTLIE reported". The one place that boundary is
tempting to cross is the kicker, whose Yahoo category depends on distance bands
— and even there this package reports the bands BALLDONTLIE published and
refuses to convert them.

IT TOUCHES NO MONEY. The rule the whole provider layer lives under (see
`providers/__init__.py`): nothing here imports `ledger/` or `economy/`, and
C-15 replays a full season to prove the ledger is untouched.

IT NEVER WORKS AROUND A RATE LIMIT. BALLDONTLIE's terms §7c forbid it, and the
transport is built so that circumventing one would take deliberate effort: a 429
raises, carrying the server's own `Retry-After`, and no automatic retry exists
to be tuned into a workaround.

── THE IDENTITY SEAM IS WP1'S, NOT THIS PACKAGE'S ──────────────────────────

`providers/cross_identity.py` already answers "which FantasyStakes player is
this BALLDONTLIE subject". This package produces subjects keyed by
BALLDONTLIE's own identifiers — `bdl.p.882`, `bdl.dst.WSH` — using the same two
key functions WP1's resolver reads, so a stat row and an identity mapping cannot
drift apart by spelling a key two ways.

── PROVENANCE OF WHAT IS CERTIFIED HERE ────────────────────────────────────

The fixtures under `providers/fixtures/balldontlie/` are SYNTHETIC, built to the
shapes and behaviours the Phase 0 acceptance test MEASURED across 117 live
requests. They certify this package's rules — every Phase 0F item — and they do
not certify that BALLDONTLIE's live payload still matches what Phase 0 saw. Only
a CAPTURED fixture settles that, and capturing one needs an API key this
environment does not hold. §16/§17's discipline applies unchanged: the gap is
reported, never papered over.
"""

from providers.balldontlie.transport import (  # noqa: F401
    BASE_URL,
    BalldontlieFixtureTransport,
    BalldontlieLiveTransport,
    BalldontlieRateLimited,
    RateLimit,
    load_credentials,
)
