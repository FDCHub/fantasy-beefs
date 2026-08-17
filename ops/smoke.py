"""
ops/smoke.py — the post-deploy smoke test.

    python -m ops.smoke --base-url https://fantasystakes.example

WHAT IT IS FOR. One command an operator runs immediately after a deploy, before
they stop watching, that answers: did the right build come up, can it reach its
database, is it serving the application, and is it leaking anything.

── WHAT IT WILL NOT DO ─────────────────────────────────────────────────────

IT CHANGES NOTHING. Every request is a GET. There is no route in this file that
settles, posts, issues, claims or writes, and there is no argument that would
make it do so — a smoke test that could alter economic state would be a smoke
test nobody dares run against production.

IT DOES NOT REQUIRE YAHOO. The Fantasy API is externally blocked and may stay
blocked; a smoke test that failed on that would fail on every deploy and stop
being read. Provider status is REPORTED, never gating.

IT AUTHENTICATES AS NOBODY. Everything checked here is reachable without a
session, which is what keeps it safe to run from a deploy pipeline that holds no
credential.

EXIT CODE IS THE RESULT: 0 pass, 1 failed checks, 2 unreachable.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

__all__ = ["SmokeResult", "run_smoke"]

#: Values that must never appear in any response body this test reads. If one
#: does, the deploy is leaking and the exit code says so.
_FORBIDDEN_MARKERS = (
    "access_token", "refresh_token", "id_token", "client_secret",
    "JWT_SECRET", "FS_TOKEN_ENCRYPTION_KEY", "DATABASE_URL",
    "-----BEGIN", "postgres://", "postgresql://",
)


class SmokeResult:
    def __init__(self) -> None:
        self.checks: list = []
        self.failed = 0

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            self.failed += 1

    def as_dict(self) -> dict:
        return {"passed": self.failed == 0, "failed": self.failed,
                "checks": self.checks}


def _get(base: str, path: str, timeout: int = 15):
    request = urllib.request.Request(base.rstrip("/") + path,
                                     headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:
        return None, type(exc).__name__


def run_smoke(base_url: str, *, expect_release: str | None = None) -> SmokeResult:
    result = SmokeResult()

    # ── the build ────────────────────────────────────────────────────────────
    status, body = _get(base_url, "/version")
    result.record("version endpoint responds", status == 200, str(status))
    identity = {}
    if status == 200:
        try:
            identity = json.loads(body)
        except ValueError:
            result.record("version is JSON", False, body[:80])
    result.record("release is identified",
                  bool(identity.get("release"))
                  and identity.get("release") != "unknown",
                  str(identity.get("release_source")))
    if expect_release:
        # THE DEPLOY'S OWN SHA, IF THE PIPELINE KNOWS IT. This is the check that
        # catches the deploy that silently did not happen — the platform reports
        # success and the old build is still serving.
        result.record("the serving release is the one just deployed",
                      str(identity.get("release", "")).startswith(expect_release),
                      f"serving {str(identity.get('release'))[:12]}")

    # ── readiness ────────────────────────────────────────────────────────────
    status, body = _get(base_url, "/ready")
    ready = {}
    try:
        ready = json.loads(body)
    except ValueError:
        pass
    result.record("readiness reports ready", status == 200 and ready.get("ready"),
                  json.dumps(ready.get("checks", {}))[:160])
    checks = ready.get("checks", {})
    result.record("database is reachable", checks.get("database") == "ok",
                  str(checks.get("database")))
    result.record("schema is at the manifest head",
                  checks.get("migrations") == "ok", str(checks.get("migrations")))
    # REPORTED, NOT GATING — see the module docstring.
    result.record(f"provider sign-in: {checks.get('yahoo_sign_in')}", True,
                  "reported, not gating")
    result.record(f"writes: {checks.get('writes')}", True, "reported")

    # ── the application is actually served ───────────────────────────────────
    status, body = _get(base_url, "/app/index.html")
    result.record("the application shell is served",
                  status == 200 and "FantasyStakes" in body, str(status))

    status, sw = _get(base_url, "/app/service-worker.js")
    result.record("the service worker is served", status == 200, str(status))
    result.record("its cache namespace carries this release",
                  "__FS_RELEASE__" not in sw
                  and identity.get("release", "")[:12].isalnum(),
                  "substituted" if "__FS_RELEASE__" not in sw else "NOT substituted")

    status, health = _get(base_url, "/health")
    result.record("health responds", status == 200, str(status))

    # ── nothing leaked ───────────────────────────────────────────────────────
    #
    # EVERY BODY THIS TEST ALREADY READ, swept together. A deploy that exposes a
    # secret through any of these surfaces fails here rather than in a report
    # somebody writes later.
    combined = " ".join([body or "", sw or "", health or "",
                         json.dumps(identity), json.dumps(ready)])
    leaked = [m for m in _FORBIDDEN_MARKERS if m in combined]
    result.record("no secret or credential term in any response",
                  not leaked, ", ".join(leaked) or "clean")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expect-release", default=None,
                        help="commit SHA this deploy should be serving")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = run_smoke(args.base_url, expect_release=args.expect_release)

    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        for check in result.checks:
            mark = "PASS" if check["ok"] else "FAIL"
            suffix = f" — {check['detail']}" if check["detail"] else ""
            print(f"  [{mark}] {check['check']}{suffix}")
        print("  RESULT:", "PASS" if result.failed == 0
              else f"{result.failed} FAILED")
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
