"""
ops/safe_mode.py — the emergency write-disable.

WHAT IT IS FOR. There is one situation this product had no answer to: an
operator has reason to believe the authoritative state is wrong — a restore just
finished, a reconciliation failed, a settlement looks duplicated — and needs the
product to STOP taking new economic writes while they look, without taking the
product down.

Taking it down is not the same thing and is worse. GMs lose the ability to read
their own Ledger, the commissioner loses the diagnostics they need to decide
anything, and the operator loses the surfaces that would tell them what
happened. Reads are how you find out; writes are what you must not compound.

── HOW IT IS TURNED ON ─────────────────────────────────────────────────────

    FS_WRITES_DISABLED=1        environment-controlled, which means it is set
                                the way every other production setting is set
                                and takes effect on the next deploy or restart.

An environment variable, deliberately, and not a database flag. The situation
this exists for includes "the database is suspect", and a switch that has to be
read from the thing you are protecting against is a switch that may not work
when it matters. It also cannot be flipped by any request, by any user, or by
any commissioner — there is no route that sets it, by design.

    FS_WRITES_DISABLED_REASON   optional free text, shown to the operator and
                                logged. Never shown to a GM; product language
                                is what they get.

── WHAT IT REFUSES, AND WHAT IT MUST NOT ───────────────────────────────────

It refuses AUTHORITATIVE ECONOMIC WRITES: posting to the Ledger, settling,
issuing, claiming, sweeping. It does not refuse reads, it does not refuse
sign-in, and it does not refuse the commissioner diagnostics that exist to
answer the question the operator is asking.

THE REFUSAL IS EXPLICIT, not a 500. §24 is specific about this and it matters:
a generic error is indistinguishable from a bug, and an operator watching an
error rate cannot tell "I turned this off" from "something is broken". It
refuses with a named reason code and a 503, which says "not now" rather than
"something went wrong".
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = ["ENV_FLAG", "ENV_REASON", "REASON_CODE", "SafeMode",
           "assert_writes_allowed", "safe_mode_state", "writes_disabled"]

ENV_FLAG = "FS_WRITES_DISABLED"
ENV_REASON = "FS_WRITES_DISABLED_REASON"

#: The one reason code every refused write reports. Stable, so a caller can
#: branch on it and an operator can grep for it.
REASON_CODE = "writes_disabled"

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SafeMode:
    enabled: bool
    reason: str | None = None

    def as_dict(self) -> dict:
        return {"writes_disabled": self.enabled, "reason": self.reason}


def safe_mode_state(environ: dict | None = None) -> SafeMode:
    """Whether authoritative writes are currently permitted."""
    env = os.environ if environ is None else environ
    raw = (env.get(ENV_FLAG, "") or "").strip().lower()
    if raw not in _TRUTHY:
        return SafeMode(enabled=False)
    reason = (env.get(ENV_REASON, "") or "").strip() or None
    return SafeMode(enabled=True, reason=reason)


def writes_disabled(environ: dict | None = None) -> bool:
    return safe_mode_state(environ).enabled


class WritesDisabled(RuntimeError):
    """An authoritative economic write was attempted while writes are disabled.

    A DISTINCT TYPE so a route can map it to 503 with a named reason rather than
    letting it fall through to a 500 that looks like a defect.
    """

    reason_code = REASON_CODE

    def __init__(self, operation: str, reason: str | None = None):
        self.operation = operation
        self.reason = reason
        super().__init__(
            f"[{REASON_CODE}] {operation} refused: this deployment has "
            f"authoritative writes disabled"
            + (f" ({reason})" if reason else ""))


def assert_writes_allowed(operation: str, environ: dict | None = None) -> None:
    """Refuse an authoritative economic write while safe mode is on.

    CALLED AT THE ECONOMIC BOUNDARY, not at the route edge — the Ledger's own
    posting path — so a write cannot reach durable state through a route nobody
    remembered to guard.

    :param operation: what was being attempted, for the log and the refusal.
        A name, never a payload: it goes into a message.
    """
    state = safe_mode_state(environ)
    if state.enabled:
        raise WritesDisabled(operation, state.reason)
