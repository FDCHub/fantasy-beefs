"""
ops/demo_ledger_check.py — the post-restore integrity gate (WEBDEPLOY-1 sections 6 and 8).

    railway run python -m ops.demo_ledger_check
    railway run python -m ops.demo_ledger_check --json

WHAT IT IS FOR. Two operations end with the same unanswered question, and it is
the question that decides whether the deployment may take traffic again:

    a PostgreSQL restore just finished — is this database actually usable?
    the concurrent-entry probe just ran — did it leave the showcase intact?

`ops/smoke.py` runs from outside and cannot answer either: the trial balance and
the demo's canonical fingerprint are properties of the DATABASE, and no public
HTTP surface exposes them — correctly, because a route that reported the ledger's
internal integrity to an anonymous caller would be a route that reported the
ledger's internal integrity to anyone. So this runs INSIDE the deployment, from
an operator shell, against the deployment's own `DATABASE_URL`.

── WHAT IT ASSERTS, IN THE ORDER A RESTORE FAILS ────────────────────────────

    1. SCHEMA        migrations are current AND the recorded manifest is
                     corroborated by the live schema. A restore from a backup
                     taken before a release comes back with the OLD schema and a
                     record that may or may not admit it; `migrations.verify`
                     is the check that catches the record being wrong, which
                     `pending` alone cannot.

    2. TRIAL BALANCE Sum of every ledger entry across every account and door.
                     Exactly 0, always — the continuous integrity invariant. A
                     restore that lands mid-transaction, or a PITR target chosen
                     inside a settlement, shows up here as a non-zero integer
                     and nowhere else.

    3. SHOWCASE      the demo league exists and is CANONICAL by the same
                     fingerprint `POST /demo/enter` uses. Reported, and gating
                     only when `--require-demo` says this deployment is the
                     public demo. A Yahoo-connected deployment has no showcase
                     and must not fail for the absence of one.

── WHAT IT WILL NOT DO ─────────────────────────────────────────────────────

IT WRITES NOTHING. It does not restore, does not reseed, does not repair, and
takes no argument that would make it. A verification tool that could also fix
things is a tool an operator runs before they have finished reading the output.

IT PRINTS NO VALUE OF ANY SECRET, and no connection URL — only the dialect. The
one number it prints is the trial balance, which is an invariant rather than a
credential.

EXIT CODE IS THE RESULT: 0 pass, 1 failed checks.
"""

from __future__ import annotations

import argparse
import json

__all__ = ["run_integrity_check"]


def run_integrity_check(*, require_demo: bool = False) -> dict:
    """Every gate a restored or probed database must pass. Writes nothing."""
    checks: list = []
    failed = 0

    def record(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            failed += 1

    # ── 1 · the schema ───────────────────────────────────────────────────────
    from db.schema import engine

    dialect = engine.dialect.name
    record("the database is PostgreSQL", dialect == "postgresql", dialect)

    try:
        from migrations.run import pending, verify

        outstanding = [m.identifier for m in pending(engine)]
        record("migrations are current", not outstanding,
               ",".join(outstanding) or "none pending")
        unverified = verify(engine)
        record("the recorded manifest matches the live schema", not unverified,
               ";".join(unverified) or "verified")
    except Exception as exc:
        # FAIL CLOSED. An unanswerable schema question is the one condition
        # under which a restored database must NOT be declared usable — the
        # same rule `/ready` applies for the same reason.
        record("migrations are current", False, type(exc).__name__)
        record("the recorded manifest matches the live schema", False,
               type(exc).__name__)

    # ── 2 · the ledger ───────────────────────────────────────────────────────
    balance = None
    try:
        from ledger.ledger import trial_balance

        balance = trial_balance()
        record("trial balance is exactly 0", balance == 0, str(balance))
    except Exception as exc:
        record("trial balance is exactly 0", False, type(exc).__name__)

    # ── 3 · the showcase ─────────────────────────────────────────────────────
    #
    # REPORTED ALWAYS, GATING ONLY WHERE IT IS THE PRODUCT. `--require-demo` is
    # what the public demo deployment passes; a Yahoo-connected deployment runs
    # the same command without it and is not failed for having no demo league.
    showcase_state = {"present": False, "canonical": None, "league_id": None}
    try:
        from db.schema import SessionLocal
        from demo.reset import canonical_fingerprint, is_canonical
        from demo.seed import find_showcase

        with SessionLocal() as db:
            league = find_showcase(db)
            if league is None:
                showcase_state = {"present": False, "canonical": None,
                                  "league_id": None}
                if require_demo:
                    record("the showcase demo league exists", False,
                           "absent — run `python -m demo.seed`")
            else:
                canonical = is_canonical(db, league)
                showcase_state = {
                    "present": True,
                    "canonical": canonical,
                    "league_id": league.id,
                    "fingerprint": canonical_fingerprint(db, league),
                }
                record("the showcase demo league exists", True,
                       "league_id=%s" % league.id)
                record("the showcase is canonical", canonical,
                       "canonical" if canonical
                       else "DRIFTED — the next visitor restores it")
    except Exception as exc:
        if require_demo:
            record("the showcase demo league exists", False,
                   type(exc).__name__)

    return {"passed": failed == 0, "failed": failed, "checks": checks,
            "dialect": dialect, "trial_balance": balance,
            "showcase": showcase_state}


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-demo", action="store_true",
                        help="fail if the showcase demo league is absent "
                             "(the public demo deployment)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_integrity_check(require_demo=args.require_demo)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        for check in report["checks"]:
            mark = "PASS" if check["ok"] else "FAIL"
            suffix = (" — " + check["detail"]) if check["detail"] else ""
            print("  [%s] %s%s" % (mark, check["check"], suffix))
        print("  RESULT:", "PASS" if report["passed"]
              else "%d FAILED" % report["failed"])
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
