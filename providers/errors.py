"""Named provider failures — Sprint 6.

EVERY REFUSAL HAS A NAME. S6-R1 and S6-R3 both turn on failing closed, and a
fail-closed path that raises a bare ValueError is indistinguishable at the call
site from a bug. Each class below names one refusal an operator can act on.

The hierarchy is deliberately shallow. `ProviderError` is the single catchable
root for "the gateway refused"; below it sit the four kinds of refusal that mean
genuinely different things:

    ProviderTransportError   the provider could not be reached or answered badly
    ProviderParseError       the payload arrived but is not the shape claimed
    ProviderIdentityError    a key is unknown, ambiguous or conflicting (S6-R1)
    ProviderConflictError    the provider contradicts final/frozen state (S6-R3)

ProviderConflictError CARRIES ITS PERSISTED ROW. A caller that catches it must
be able to tell the operator which conflict was recorded without re-querying,
and a caller that logs only the message would otherwise lose the link.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Root of every provider refusal. Never raised directly."""


class ProviderTransportError(ProviderError):
    """The provider could not be reached, refused, or returned a bad status."""


class ProviderParseError(ProviderError):
    """A payload arrived but does not carry the fields it must carry.

    Raised instead of returning a partial result: a parser that skips an
    unreadable matchup silently shrinks the slate, and a shrunken slate is
    exactly what the Sprint 1-5 freshness gates are built to notice — but only
    if it is ever allowed to reach them.
    """


class ProviderIdentityError(ProviderError):
    """S6-R1 — an identity is UNKNOWN, AMBIGUOUS or CONFLICTING.

    `reason` is one of the three constants below, so a caller can distinguish
    "this league has not been mapped yet" from "two rows claim the same provider
    key" without parsing the message.
    """

    UNKNOWN = "UNKNOWN_IDENTITY"
    AMBIGUOUS = "AMBIGUOUS_IDENTITY"
    CONFLICTING = "CONFLICTING_IDENTITY"
    NON_AUTHORITATIVE = "NON_AUTHORITATIVE_IDENTITY"

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


class ProviderFinalityError(ProviderError):
    """An attempt to move finality backwards, or to set it without a signal.

    Distinct from ProviderConflictError: this is a PROGRAMMING refusal at the
    finality writer's own boundary, raised before anything is recorded, whereas
    a conflict is a recorded disagreement about a fact.
    """


class ProviderConflictError(ProviderError):
    """S6-R3 — the provider contradicts economically final or frozen state.

    Raised AFTER the ProviderConflict row is written and the transaction that
    holds it is safe to commit, and always with the final state left unchanged.
    Callers get `conflict_key` so they can name the recorded row.
    """

    def __init__(self, message: str, *, conflict_key: str,
                 conflict_type: str, external_identity: str) -> None:
        super().__init__(f"[PROVIDER_CONFLICT:{conflict_type}] {message}")
        self.conflict_key = conflict_key
        self.conflict_type = conflict_type
        self.external_identity = external_identity


class ProviderCredentialError(ProviderError):
    """Live transport was asked for without usable credentials.

    Its own class because §3 requires offline certification to run with NO
    credentials at all: the certification harness asserts that constructing a
    LIVE transport in that environment raises THIS, which is a much stronger
    statement than "some exception happened".
    """