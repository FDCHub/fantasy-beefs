"""
ops/release.py — which build is running.

WHY THIS EXISTS. Every recovery question starts with "which version was up when
it happened", and until now this product could not answer it. A rollback needs
to name what it is rolling back to; a bad-release investigation needs to know
whether the process serving an error is the one that was just deployed; a
correlated log line is worth much less without the build it came from.

── WHERE THE IDENTIFIER COMES FROM, IN ORDER ────────────────────────────────

    FS_RELEASE                  an explicit release name an operator set. Wins,
                                because a human naming a release outranks a
                                platform inferring one.
    RAILWAY_GIT_COMMIT_SHA      what the platform actually deployed. This is the
                                normal production answer.
    git rev-parse HEAD          a developer machine or any checkout. Never
                                consulted in a deployed container, where there
                                is no git directory anyway.
    "unknown"                   said plainly rather than guessed at.

NOTHING HERE IS SECRET. A commit SHA identifies a build, not a credential, and
it is the one piece of deployment metadata that has to be visible for an
operator to act. The environment NAME is included for the same reason and the
same limit: `production`, not the values that make it one.

CACHED AFTER FIRST RESOLUTION, deliberately. The release cannot change inside a
running process — a new release is a new process — and shelling out to git on
every health check would be a needless subprocess on a hot path.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

__all__ = ["ReleaseIdentity", "SOURCE_ENV", "SOURCE_GIT", "SOURCE_PLATFORM",
           "SOURCE_UNKNOWN", "release_identity", "reset_cache"]

SOURCE_ENV = "explicit"
SOURCE_PLATFORM = "platform"
SOURCE_GIT = "git"
SOURCE_UNKNOWN = "unknown"

#: The product's own version, bumped by hand at a release boundary. Distinct
#: from the commit: a version says what this is, a commit says exactly which
#: build of it.
APPLICATION_VERSION = "1.0.0"

_CACHE: "ReleaseIdentity | None" = None


@dataclass(frozen=True)
class ReleaseIdentity:
    """What is running, in terms safe to log and safe to serve."""

    version: str
    #: A commit SHA, an operator-supplied name, or "unknown". Never a secret.
    release: str
    #: Where `release` came from, so an operator can tell a real deployment
    #: identifier from a developer checkout's HEAD.
    source: str
    environment: str

    @property
    def short(self) -> str:
        """The first twelve characters — enough to identify, short enough to log."""
        return self.release[:12] if self.release else SOURCE_UNKNOWN

    def as_dict(self) -> dict:
        return {"version": self.version, "release": self.release,
                "release_source": self.source, "environment": self.environment}


def _git_head(cwd: str | None = None) -> str | None:
    """HEAD, if this is a checkout and git is available. Never raises."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd or os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True, text=True, timeout=5)
    except Exception:                            # pragma: no cover - defensive
        return None
    value = (out.stdout or "").strip()
    return value if out.returncode == 0 and value else None


def release_identity(environ: dict | None = None, *,
                     use_cache: bool = True) -> ReleaseIdentity:
    """Identify this build.

    :param use_cache: tests pass False so one process can observe several
        environments; production never needs to.
    """
    global _CACHE
    if use_cache and _CACHE is not None and environ is None:
        return _CACHE

    env = os.environ if environ is None else environ
    from auth.environment import environment_name

    explicit = (env.get("FS_RELEASE", "") or "").strip()
    platform = (env.get("RAILWAY_GIT_COMMIT_SHA", "") or "").strip()

    if explicit:
        release, source = explicit, SOURCE_ENV
    elif platform:
        release, source = platform, SOURCE_PLATFORM
    else:
        head = _git_head()
        release, source = (head, SOURCE_GIT) if head else (SOURCE_UNKNOWN,
                                                           SOURCE_UNKNOWN)

    identity = ReleaseIdentity(
        version=APPLICATION_VERSION, release=release, source=source,
        environment=environment_name(env))
    if use_cache and environ is None:
        _CACHE = identity
    return identity


def reset_cache() -> None:
    """Forget the resolved identity. For tests only."""
    global _CACHE
    _CACHE = None
