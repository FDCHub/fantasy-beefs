"""
test_support_s7_harness.py — an authenticated application for the Sprint 7 suites.

INFRASTRUCTURE, NOT A TEST. No assertions live here.

WHY IT EXISTS (WP5). The four Sprint 7 package suites each run a node browser
suite, and `web/tests/browser-harness.mjs` decides what to point Chrome at from
`FS_TEST_ORIGIN`. When `test_s7_full_ui_certification.py` runs them it has
already started an application and exported that variable, so they certify the
real product. Run DIRECTLY — which is how §4.1/§4.2 of the RUNBOOK tells a
developer to run them — there is no such variable, the harness falls back to its
own static file server, and since S8-P1 that server answers 404 to `/auth/me`.

The shell then draws the SIGN-IN GATE. Every selector the suite reaches for
belongs to an application that was never mounted, so the first `.click()`
dereferences null and the suite dies at "0 PASS / 0 FAIL, exit 1" — a result
that reads like a broken browser and is nothing of the kind. That is precisely
what the RUNBOOK recorded as "Chrome launch flakiness", and it was neither
Chrome nor flaky.

WHAT THIS DOES. `ensure_authenticated_app()` gives a suite an application to
certify against, and is a no-op when one is already provided. The two callers —
the full certification and a developer running one suite — therefore exercise
the same build through the same door, and neither has to know which case it is
in.

THE SEEDED SESSION IS A GM, not a commissioner, because the Sprint 7 suites
certify what an ordinary GM's five tabs look like. A suite needing commissioner
authority asks for it explicitly.
"""

from __future__ import annotations

import atexit
import os

#: The running server, when this module started one. Kept so a second call in
#: the same process reuses it rather than starting a second application.
_SERVER = None


def ensure_authenticated_app(*, seed_pool_slate: bool = False,
                             action_shape: str | None = None,
                             authenticate_as: str | None = None) -> str:
    """Guarantee `FS_TEST_ORIGIN` names a running, signed-in application.

    Returns the origin. Idempotent, and deliberately DEFERS to an origin that is
    already set: when the full certification is the caller it owns the
    application, and starting a second one here would certify a different
    database than the one the rest of that run is asserting against.
    """
    global _SERVER

    existing = os.environ.get("FS_TEST_ORIGIN")
    if existing:
        return existing

    if _SERVER is not None:
        return _SERVER.origin

    from test_support_app_server import GM_EMAIL, PASSWORD, AppServer

    _SERVER = AppServer(seed_pool_slate=seed_pool_slate,
                        action_shape=action_shape).start()
    atexit.register(_stop)

    os.environ["FS_TEST_ORIGIN"] = _SERVER.origin
    os.environ["FS_TEST_AUTH_EMAIL"] = authenticate_as or GM_EMAIL
    os.environ["FS_TEST_AUTH_PASSWORD"] = PASSWORD
    return _SERVER.origin


def _stop() -> None:
    global _SERVER
    if _SERVER is not None:
        _SERVER.stop()
        _SERVER = None