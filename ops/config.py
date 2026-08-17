"""
ops/config.py — what a production process must have before it serves anyone.

WHY THE DISTINCTION IN THIS FILE IS THE WHOLE DESIGN.

Not every missing variable is equally bad, and treating them as if they were
produces one of two failures. Refuse to start without Yahoo configuration and a
deployment that is perfectly capable of serving a Demo league, showing a Ledger
and letting a GM read their season crash-loops instead. Start happily without an
encryption key and the first user who signs in has their Yahoo grant silently
dropped, with no error anyone will see until a league stops syncing weeks later.

So configuration is graded:

    CRITICAL      the process must not serve traffic without it. A missing
                  value here means requests would fail, or worse, would appear
                  to succeed while doing something unsafe.

    DEGRADED      a real capability is unavailable and the product says so in
                  its own language. The process runs; the feature does not.

`auth/environment.production_readiness()` already answered a narrower version of
this question for the sign-in surface, and it is REUSED rather than
reimplemented — its results feed the CRITICAL list here. One list of Yahoo
variables, in one place, still.

── WHAT IS NEVER DONE HERE ─────────────────────────────────────────────────

NO VALUE IS EVER READ INTO A RESULT. Every function in this module returns
variable NAMES and booleans. A configuration report that echoed a secret to
prove it was set would be a secret in a health response, a log and a screenshot.

NO DEVELOPMENT FALLBACK IN PRODUCTION. There is no branch here that substitutes
a default secret, a development key or a permissive origin when a production
value is absent. Absence is reported; it is never filled in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

__all__ = ["ConfigReport", "CRITICAL", "DEGRADED", "evaluate_config",
           "startup_guard"]

CRITICAL = "critical"
DEGRADED = "degraded"


@dataclass(frozen=True)
class ConfigReport:
    """What this process has, what it lacks, and how much that matters."""

    environment: str
    production: bool
    #: Names only. Never values.
    missing_critical: tuple = field(default_factory=tuple)
    missing_degraded: tuple = field(default_factory=tuple)
    #: The subset of `missing_critical` that a process cannot even START
    #: without. See `startup_guard` for why the two differ.
    fatal_at_startup: tuple = field(default_factory=tuple)
    #: Capabilities, as booleans an operator and a surface can both read.
    can_store_provider_tokens: bool = False
    can_sign_in_with_yahoo: bool = False
    database_configured: bool = False

    @property
    def serviceable(self) -> bool:
        """Whether this process may serve production traffic."""
        return not self.missing_critical

    def as_dict(self) -> dict:
        return {
            "environment": self.environment,
            "production": self.production,
            "serviceable": self.serviceable,
            "missing_critical": list(self.missing_critical),
            "fatal_at_startup": list(self.fatal_at_startup),
            "missing_degraded": list(self.missing_degraded),
            "can_store_provider_tokens": self.can_store_provider_tokens,
            "can_sign_in_with_yahoo": self.can_sign_in_with_yahoo,
            "database_configured": self.database_configured,
        }


def _set(env: dict, name: str) -> bool:
    return bool((env.get(name, "") or "").strip())


def evaluate_config(environ: dict | None = None) -> ConfigReport:
    """Grade this process's configuration. Reads only; never raises."""
    env = os.environ if environ is None else environ

    from auth.environment import (
        REQUIRED_YAHOO_VARS, environment_name, is_production,
        production_readiness,
    )
    from auth.token_crypto import available as crypto_available

    production = is_production(env)
    critical: list[str] = []
    degraded: list[str] = []

    database = _set(env, "DATABASE_URL")
    if production and not database:
        # WITHOUT THIS A PRODUCTION PROCESS SILENTLY USES THE LOCAL SQLITE FILE
        # in `db/schema.py`'s fallback — a file inside an ephemeral container,
        # which every deploy would discard along with every wager in it.
        critical.append("DATABASE_URL")

    tokens_storable = crypto_available(env)
    if production and not tokens_storable:
        # CRITICAL, AND THIS IS THE JUDGEMENT CALL WORTH STATING. A process
        # without it CAN serve every read and the whole Demo product. But it
        # accepts Yahoo sign-ins and drops the grant each one produces —
        # `record_grant` fails, the callback swallows it by design so the user
        # still gets in, and the league they came to connect never syncs.
        # Failing loudly at deploy is better than failing invisibly per user.
        critical.append("FS_TOKEN_ENCRYPTION_KEY")

    yahoo_ready = all(_set(env, name) for name in REQUIRED_YAHOO_VARS)

    # THE EXISTING READINESS LIST, REUSED. It already knows the Yahoo triple,
    # the session secret and the insecure-cookie rule, and duplicating any of
    # them here would create a second answer that could drift from the first.
    for item in production_readiness(env):
        if item.startswith("FS_YAHOO_"):
            # A DEPLOYMENT WITHOUT YAHOO IS A REAL DEPLOYMENT. It serves Demo,
            # reads and every non-provider surface; production auth is what is
            # unavailable, and the sign-in page already says so in product
            # language. Not a reason to refuse to start.
            degraded.append(item)
        else:
            critical.append(item)

    if production and not _set(env, "FS_PUBLIC_BASE_URL"):
        # DEGRADED, not critical: nothing in the request path needs it, but an
        # absolute URL in an email or a redirect has to come from somewhere
        # other than a client-supplied Host header.
        degraded.append("FS_PUBLIC_BASE_URL")

    from ops.release import release_identity

    if production and release_identity(env, use_cache=False).source == "unknown":
        degraded.append("FS_RELEASE or RAILWAY_GIT_COMMIT_SHA")

    # ── WHAT REFUSES TO START vs WHAT REFUSES TRAFFIC ────────────────────────
    #
    # THE DISTINCTION IS THE ONE `/ready` EXISTS FOR, and getting it wrong in
    # either direction is costly. A process that cannot function, or that would
    # function while silently doing harm, must not start — restarting it will
    # not help and it should crash loudly with the reason in the deploy log.
    # A process that functions but must not receive production traffic should
    # START and report NOT READY, so the platform withholds traffic while an
    # operator can still reach its diagnostics.
    #
    # `FS_COOKIE_INSECURE` is the case that taught the difference. It is a real
    # misconfiguration — cookies over plaintext — and it must gate traffic. But
    # the process is entirely functional, and making it fatal meant a
    # production-mode process could not even be brought up to be inspected.
    _CANNOT_FUNCTION = ("DATABASE_URL", "FS_TOKEN_ENCRYPTION_KEY",
                        "JWT_SECRET_KEY")
    fatal = tuple(name for name in dict.fromkeys(critical)
                  if name in _CANNOT_FUNCTION)

    return ConfigReport(
        environment=environment_name(env),
        production=production,
        missing_critical=tuple(dict.fromkeys(critical)),
        missing_degraded=tuple(dict.fromkeys(degraded)),
        fatal_at_startup=fatal,
        can_store_provider_tokens=tokens_storable,
        can_sign_in_with_yahoo=yahoo_ready,
        database_configured=database or not production,
    )


class ProductionConfigError(RuntimeError):
    """A production process is missing configuration it cannot serve without.

    CARRIES NAMES, NOT VALUES — it is raised at startup and will be the first
    thing in a deploy log.
    """


def startup_guard(environ: dict | None = None, *, raise_on_missing: bool = True
                  ) -> ConfigReport:
    """Evaluate configuration at startup and refuse if production cannot serve.

    FAIL CLOSED, AND FAIL LOUDLY — but only for what makes the process unable
    to function. Everything else that must gate production traffic gates it
    through `/ready`, which withholds traffic while leaving the process up and
    inspectable. See `evaluate_config` for why that split is not cosmetic.

    NON-PRODUCTION NEVER RAISES. A developer running the app with no Yahoo
    configuration and no encryption key is doing something ordinary, and this
    must not become a reason they cannot start the server.
    """
    report = evaluate_config(environ)
    if raise_on_missing and report.production and report.fatal_at_startup:
        raise ProductionConfigError(
            "This production process is missing configuration it cannot "
            "function without and will not start: "
            + ", ".join(report.fatal_at_startup)
            + ". Set them in the deployment environment. No value is shown "
              "here and none is substituted.")
    return report
