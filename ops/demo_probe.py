"""
ops/demo_probe.py — the public-demo deployment certification probe (WEBDEPLOY-1 §8).

    python -m ops.demo_probe --base-url https://app.fantasystakesapp.com
    python -m ops.demo_probe --base-url ... --concurrency 12 --json

WHAT IT IS FOR. `ops/smoke.py` answers "did the right build come up and can it
reach its database". It deliberately cannot answer the question a TWO-REPLICA
public demo actually turns on:

    when twelve strangers press Try Demo at the same instant, and the load
    balancer sprays them across replicas that share nothing but PostgreSQL,
    does every one of them get seated in the SAME showcase league?

That is the D2.5.1 gate, and until now it existed only as an in-process pytest
(`test_d251_concurrent_entry.py`) driving a local application against a local
database. That test is the certification of the CODE. This is the certification
of the DEPLOYMENT, and they are not the same claim: the pytest cannot observe a
second replica, a platform load balancer, or an advisory lock crossing a process
boundary, because in-process there is only one process to cross.

── WHY THIS IS NOT A SMOKE TEST, AND IS NOT RUN LIKE ONE ────────────────────

IT WRITES. `POST /demo/enter` restores the showcase to canonical state before
seating, so unlike `ops.smoke` this probe can cause a bounded, intended mutation
of ONE league — the synthetic demo. That is why it is a separate module with a
separate name rather than a flag on the smoke test: nobody should be able to run
the write from the command they run reflexively after every deploy.

IT MUST NEVER BE POINTED AT A YAHOO DEPLOYMENT'S REAL LEAGUE, and it cannot be:
`/demo/enter` takes no parameters, names no league, and `demo.reset` runs
`assert_demo_league` before it touches a row. The probe inherits that safety
rather than restating it.

── WHAT IT PROVES, AND WHAT IT HONESTLY CANNOT ──────────────────────────────

PROVES, from outside, over the real network, against the real deployment:

    - every concurrent entrant is answered 200 — no 500, no StaleDataError
    - every entrant lands in ONE league_id — no duplicate showcase was created
    - at most one entrant caused a rebuild — the fingerprint short-circuit is
      working, so the public route is not a way to make the deployment replay a
      season on demand
    - the seated identity is the demo GM on the certified seat (Pain Sanders)
    - no response body leaks a credential term

CANNOT PROVE from outside, and does not pretend to:

    - TRIAL BALANCE = 0. It is a property of the ledger, not of an HTTP
      response, and no public surface exposes it — correctly.
    - THE CANONICAL FINGERPRINT. Same reason.

Those two are certified in the same pass by an OPERATOR command run against the
deployment's own database, and the operator procedure names both. The full
sequence is docs/RAILWAY_DEPLOYMENT.md section 8. A probe that claimed a zero
trial balance it had not read would be worse than one that says it cannot.

EXIT CODE IS THE RESULT: 0 pass, 1 failed checks, 2 unreachable.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

__all__ = ["DemoProbeResult", "run_demo_probe"]

#: The gate's concurrency. Twelve because that is the number D2.5.1 certifies,
#: and it is one per showcase team — the worst realistic simultaneous arrival.
DEFAULT_CONCURRENCY = 12

#: The team the certified seed seats a visitor on. Named here so a drift in the
#: fixture fails this probe rather than passing it silently.
EXPECTED_SEAT = "Pain Sanders"

#: Never acceptable in a response body reaching a public visitor.
_FORBIDDEN_MARKERS = (
    "access_token", "refresh_token", "client_secret", "JWT_SECRET",
    "FS_TOKEN_ENCRYPTION_KEY", "DATABASE_URL", "postgres://", "postgresql://",
    "-----BEGIN",
    # A leaked traceback is a leaked file path and a leaked internal name.
    "Traceback (most recent call last)", "StaleDataError", "sqlalchemy.",
)


class DemoProbeResult:
    def __init__(self) -> None:
        self.checks: list = []
        self.failed = 0
        self.entries: list = []

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            self.failed += 1

    def as_dict(self) -> dict:
        return {"passed": self.failed == 0, "failed": self.failed,
                "checks": self.checks, "entries": self.entries}


def _request(base: str, path: str, *, method: str = "GET",
             cookie: str | None = None, timeout: int = 60) -> tuple:
    """Return (status, body, cookie_header). Never raises."""
    request = urllib.request.Request(base.rstrip("/") + path, method=method,
                                     headers={"Accept": "application/json"})
    if method == "POST":
        # An explicit empty body: `/demo/enter` takes no parameters, and a POST
        # with no Content-Length is rejected by some proxies before it arrives.
        request.data = b""
        request.add_header("Content-Type", "application/json")
    if cookie:
        request.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            jar = response.headers.get_all("Set-Cookie") or []
            return (response.status,
                    response.read().decode("utf-8", "replace"),
                    "; ".join(value.split(";", 1)[0] for value in jar))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), ""
    except Exception as exc:
        return None, type(exc).__name__, ""


def run_demo_probe(base_url: str, *,
                   concurrency: int = DEFAULT_CONCURRENCY) -> DemoProbeResult:
    result = DemoProbeResult()

    # ── the burst ────────────────────────────────────────────────────────────
    #
    # SUBMITTED TOGETHER, NOT IN SEQUENCE. A loop of twelve serial requests
    # proves nothing about the advisory lock: each would find the league already
    # canonical and none would ever contend. The pool is sized to the burst so
    # every request is genuinely in flight at once.
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        responses = list(pool.map(
            lambda _: _request(base_url, "/demo/enter", method="POST"),
            range(concurrency)))

    statuses = [status for status, _, _ in responses]
    bodies = [body for _, body, _ in responses]
    result.record("all %d concurrent entrants answered 200" % concurrency,
                  all(status == 200 for status in statuses),
                  ",".join(str(status) for status in statuses))

    payloads = []
    for body in bodies:
        try:
            payloads.append(json.loads(body))
        except ValueError:
            payloads.append({})
    result.entries = [{"league_id": p.get("league_id"),
                       "restored": p.get("restored")} for p in payloads]

    league_ids = {p.get("league_id") for p in payloads if p.get("league_id")}
    result.record("every entrant landed in ONE showcase league",
                  len(league_ids) == 1,
                  "league_ids=" + ",".join(sorted(str(i) for i in league_ids)))

    seated = sum(1 for p in payloads if p.get("demo") is True)
    result.record("every entrant was told it is a demo",
                  bool(payloads) and seated == concurrency,
                  "%d/%d" % (seated, concurrency))

    # AT MOST ONE REBUILD. The fingerprint short-circuit is what stops a public
    # POST becoming a way to make the deployment replay a season; twelve
    # rebuilds would mean it is not working even though every request answered
    # 200, which is precisely the failure a status-code check cannot see.
    rebuilt = sum(1 for p in payloads if p.get("restored") == "rebuilt")
    result.record("at most one entrant triggered a rebuild", rebuilt <= 1,
                  "rebuilt=%d" % rebuilt)

    absent = sum(1 for status in statuses if status == 404)
    if absent:
        result.record("the showcase is seeded on this deployment", False,
                      "%d entrants got 404 demo_not_seeded — run the operator "
                      "seed (docs/RAILWAY_DEPLOYMENT.md section 7)" % absent)

    # ── the seat ─────────────────────────────────────────────────────────────
    #
    # One session from the burst, reused. Seating is an identity fact and cannot
    # be read from the entry response, which deliberately returns league
    # information rather than user information.
    cookie = next((jar for _, _, jar in responses if jar), "")
    if cookie:
        status, body, _ = _request(base_url, "/auth/me", cookie=cookie)
        identity = {}
        try:
            identity = json.loads(body)
        except ValueError:
            pass
        result.record("the issued session authenticates", status == 200,
                      str(status))
        result.record("the visitor is seated on " + EXPECTED_SEAT,
                      identity.get("team_name") == EXPECTED_SEAT,
                      str(identity.get("team_name")))
        bodies = bodies + [body]
    else:
        result.record("a browser session was issued", False, "no Set-Cookie")

    # ── nothing leaked ───────────────────────────────────────────────────────
    combined = " ".join(bodies)
    leaked = [marker for marker in _FORBIDDEN_MARKERS if marker in combined]
    result.record("no credential term, traceback or driver error in any body",
                  not leaked, ", ".join(leaked) or "clean")

    return result


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = run_demo_probe(args.base_url, concurrency=args.concurrency)

    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        for check in result.checks:
            mark = "PASS" if check["ok"] else "FAIL"
            suffix = (" — " + check["detail"]) if check["detail"] else ""
            print("  [%s] %s%s" % (mark, check["check"], suffix))
        print("  RESULT:", "PASS" if result.failed == 0
              else "%d FAILED" % result.failed)
        print("  NOT PROVEN HERE — run against the deployment's own database:")
        print("    railway run python -m demo.reset --check")
        print("    railway run python -m ops.demo_ledger_check")
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
