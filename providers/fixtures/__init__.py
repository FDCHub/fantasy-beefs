"""G — fixture capture and replay (§16).

TWO LAYERS, CERTIFYING DIFFERENT THINGS:

    L1 RAW         verbatim provider response bytes, after secret/PII scrubbing.
                   Certifies the PARSER.
    L2 NORMALIZED  the serialized normalized DTO set. Certifies identity,
                   finality and persistence INDEPENDENTLY of parser behavior, so
                   a parser bug cannot mask a persistence bug or vice versa.

PROVENANCE IS MANDATORY AND IS NEVER INFERRED. Every fixture manifest carries
`provenance` = CAPTURED or SYNTHETIC, explicitly. There is no default, no
"probably captured", and no path that upgrades one to the other. S6-R2 permits
Sprint 6 to certify architecture, normalization, identity, persistence, finality
safety, idempotency, concurrency and downstream integration on synthetic
fixtures — and forbids claiming live Yahoo payload parsing is certified without
CAPTURED ones. Keeping provenance a required, un-defaulted field is what makes
that claim checkable rather than aspirational.
"""

from providers.fixtures.record import (  # noqa: F401
    CAPTURED,
    SYNTHETIC,
    FixtureManifest,
    scrub,
    write_fixture,
)
from providers.fixtures.replay import (  # noqa: F401
    FixtureTransport,
    load_corpus,
)
