"""
auth/environment.py — which deployment this process is, and what that permits.

ONE PLACE DECIDES, AND EVERY GATE READS IT. Before WP3D.1 the codebase had no
concept of "this is production": `FS_COOKIE_INSECURE` and `JWT_SECRET_KEY` were
independent switches, each defaulting to the safe thing on its own. That worked
while there was one login. It does not work now, because the authentication
cutover turns on a question none of those switches answers — may this process
accept a password at all?

THE ANSWER IS NO IN PRODUCTION, AND NOTHING CAN TALK IT OUT OF THAT.

    FS_ENV=production   Sign in with Yahoo is the only login. The password
                        routes are not merely hidden — they refuse.
    anything else       development/test: the password routes work, so the
                        suites and a local Rev 4.3 review can run without an
                        interactive Yahoo round trip every time.

FAIL CLOSED, NOT FAIL BACK. A production process whose Yahoo configuration is
missing or incomplete does NOT quietly re-enable the password login it just
retired — that would turn a deployment mistake into a silent downgrade of the
entire authentication model. It refuses both, and says so. A broken login is a
visible incident; a secretly weaker one is not.

WHY THE DEFAULT IS NON-PRODUCTION. Twenty automated suites and the browser
harness sign in with an email and a password, and a default that broke them all
would be a default nobody could run. The cost is that a real deployment MUST set
`FS_ENV=production` explicitly, which is recorded in the WP3D.1 report as a
deployment requirement and asserted by `production_readiness()` below so an
operator can check it rather than assume it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = [
    "ENV_PRODUCTION",
    "AuthCapabilities",
    "auth_capabilities",
    "environment_name",
    "is_production",
    "production_readiness",
]

ENV_PRODUCTION = "production"

#: The three configuration values a Yahoo sign-in needs. Named here so the
#: readiness check, the OIDC module and the operator all use one list.
REQUIRED_YAHOO_VARS = (
    "FS_YAHOO_CLIENT_ID",
    "FS_YAHOO_CLIENT_SECRET",
    "FS_YAHOO_REDIRECT_URI",
)


def environment_name(environ: dict | None = None) -> str:
    """The deployment this process believes it is.

    Read at CALL time, never cached at import. A test sets the variable around
    one app instance and expects that instance to behave accordingly; a value
    captured at import would leak the first suite's setting into every later
    one in the same process.
    """
    env = (environ if environ is not None else os.environ)
    return (env.get("FS_ENV", "") or "development").strip().lower()


def is_production(environ: dict | None = None) -> bool:
    return environment_name(environ) == ENV_PRODUCTION


def yahoo_sign_in_configured(environ: dict | None = None) -> bool:
    """Whether this process holds a complete Yahoo sign-in configuration."""
    env = (environ if environ is not None else os.environ)
    return all((env.get(name, "") or "").strip() for name in REQUIRED_YAHOO_VARS)


@dataclass(frozen=True)
class AuthCapabilities:
    """What this process will accept as a login, and why.

    SERVED TO THE BROWSER so the sign-in surface can draw the right thing
    without guessing. It carries no secret and no diagnostic: whether a login
    method is available is not sensitive — a GM finds out by looking at the
    page — and the client id, the redirect and the secret are all absent by
    construction.
    """

    environment:      str
    yahoo:            bool
    password:         bool
    #: Set only when NEITHER method is available, which is a misconfigured
    #: production process. Product language; never an exception string.
    unavailable_reason: str | None = None


def auth_capabilities(environ: dict | None = None) -> AuthCapabilities:
    """The login methods this process offers."""
    env_name = environment_name(environ)
    production = env_name == ENV_PRODUCTION
    yahoo = yahoo_sign_in_configured(environ)

    if production:
        # THE CUTOVER, IN ONE LINE. In production the password is never a
        # login, configured Yahoo or not.
        return AuthCapabilities(
            environment=env_name,
            yahoo=yahoo,
            password=False,
            unavailable_reason=(
                None if yahoo else
                "Sign-in is temporarily unavailable. Please try again shortly."
            ),
        )

    return AuthCapabilities(environment=env_name, yahoo=yahoo, password=True)


def production_readiness(environ: dict | None = None) -> list[str]:
    """Everything a production process is missing, named for an operator.

    RETURNS A LIST RATHER THAN RAISING, and is read by `/health`, so a
    deployment can be inspected before it is trusted. Raising at import would
    make a misconfigured container crash-loop with the reason buried in a log
    nobody has tailed yet.
    """
    env = (environ if environ is not None else os.environ)
    missing: list[str] = []
    if not is_production(env):
        return missing
    for name in REQUIRED_YAHOO_VARS:
        if not (env.get(name, "") or "").strip():
            missing.append(name)
    if not (env.get("JWT_SECRET_KEY", "") or "").strip():
        missing.append("JWT_SECRET_KEY")
    if (env.get("FS_COOKIE_INSECURE", "") or "") == "1":
        missing.append("FS_COOKIE_INSECURE must not be set in production")
    return missing
