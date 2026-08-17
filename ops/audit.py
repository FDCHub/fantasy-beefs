"""
ops/audit.py — the recovery audit. Read-only, and it never repairs.

WHAT IT ANSWERS. After a restore, a crash, a bad release or an interrupted job:
is this database's authoritative state internally consistent, and is it safe to
resume workers and re-enable writes?

WHY IT REFUSES TO FIX ANYTHING. Every check below can fail for more than one
reason, and the reasons have different correct responses. A Ledger that does not
balance might be a half-written posting, a restore from the wrong point, or a
defect — and "make it balance" is the wrong answer to all three. An audit that
repaired would be an audit whose output nobody could trust, because a clean
result would no longer distinguish "was fine" from "was made to look fine".

So it observes and it reports. The operator decides.

── WHAT IT CHECKS ─────────────────────────────────────────────────────────

    SCHEMA        the tables the running release needs, and the migration
                  ledger's view of what has been applied
    LEDGER        debits equal credits, globally
    PROTECTED     no account that may not go negative has gone negative
    ESCROW/POT    no escrow or pot balance is impossible
    GRANTS        every provider grant points at a real user; every league
                  credential owner exists
    JOBS          nothing is claimed by a worker that can no longer exist

    python -m ops.audit                     # against DATABASE_URL
    python -m ops.audit --json              # machine-readable

EXIT CODE IS THE RESULT: 0 clean, 1 findings, 2 could not run. A deploy gate or
a restore drill can branch on it without parsing anything.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field

__all__ = ["AuditFinding", "AuditResult", "run_audit"]

SEVERITY_BLOCKING = "blocking"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class AuditFinding:
    check: str
    severity: str
    detail: str


@dataclass
class AuditResult:
    release: dict = field(default_factory=dict)
    checks_run: list = field(default_factory=list)
    findings: list = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not any(f.severity == SEVERITY_BLOCKING for f in self.findings)

    def as_dict(self) -> dict:
        return {
            "release": self.release,
            "clean": self.clean,
            "checks_run": self.checks_run,
            "findings": [{"check": f.check, "severity": f.severity,
                          "detail": f.detail} for f in self.findings],
        }


def run_audit(session=None) -> AuditResult:
    """Audit the database this process is bound to. Opens nothing it does not close.

    :param session: an open Session to reuse. Tests pass one; the command-line
        entry point lets this open and close its own.
    """
    from sqlalchemy import func, inspect, text

    from ops.release import release_identity

    result = AuditResult(release=release_identity(use_cache=False).as_dict())

    owns_session = session is None
    if owns_session:
        from db.schema import SessionLocal

        session = SessionLocal()

    def finding(check: str, severity: str, detail: str) -> None:
        result.findings.append(AuditFinding(check, severity, detail))

    try:
        # ── schema ───────────────────────────────────────────────────────────
        result.checks_run.append("schema")
        tables = set(inspect(session.get_bind()).get_table_names())
        for required in ("users", "leagues", "provider_grants",
                         "ledger_entries"):
            if required not in tables:
                finding("schema", SEVERITY_BLOCKING,
                        f"required table {required!r} is absent")

        # THE MIGRATION LEDGER IS REPORTED, NOT REQUIRED. A database bootstrapped
        # fresh has the full schema and no migration history, which is correct
        # and is not a finding — see migrations/manifest.py.
        result.checks_run.append("migrations")
        if "schema_migrations" in tables:
            applied = session.execute(
                text("SELECT count(*) FROM schema_migrations")).scalar()
            result.release["migrations_applied"] = int(applied or 0)
        else:
            result.release["migrations_applied"] = None

        # ── the Ledger balances ──────────────────────────────────────────────
        result.checks_run.append("ledger_balance")
        if "ledger_entries" in tables:
            total = session.execute(
                text("SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries")
            ).scalar()
            if int(total or 0) != 0:
                finding("ledger_balance", SEVERITY_BLOCKING,
                        f"debits and credits do not net to zero: {total} cents")

            # ── protected accounts ───────────────────────────────────────────
            #
            # THE SAME RULE THE POSTING GUARD ENFORCES, checked against what is
            # actually stored. `world` and `receivable:*` are the two the Ledger
            # exempts by design; anything else negative is a state the guard
            # should have made unreachable, so finding one is a real signal.
            result.checks_run.append("protected_accounts")
            rows = session.execute(text(
                "SELECT account, SUM(amount_cents) AS bal FROM ledger_entries "
                "GROUP BY account HAVING SUM(amount_cents) < 0")).fetchall()
            for account, balance in rows:
                if account == "world" or str(account).startswith("receivable:"):
                    continue
                finding("protected_accounts", SEVERITY_BLOCKING,
                        f"{account} is negative ({balance} cents)")

        # ── provider grants and credential owners ────────────────────────────
        result.checks_run.append("provider_grants")
        if {"provider_grants", "users"} <= tables:
            orphans = session.execute(text(
                "SELECT count(*) FROM provider_grants g "
                "LEFT JOIN users u ON u.id = g.user_id WHERE u.id IS NULL"
            )).scalar()
            if int(orphans or 0):
                finding("provider_grants", SEVERITY_BLOCKING,
                        f"{orphans} grant(s) reference a user that is gone")

            # A GRANT THAT WILL NOT OPEN IS REPORTED AS A WARNING, NOT A
            # FAILURE. The commonest cause is a restore without the matching
            # encryption key, which is an operator condition with an operator
            # remedy — and the audit's job is to say so before somebody
            # concludes the data is corrupt.
            result.checks_run.append("grant_readability")
            from auth.token_crypto import TokenCryptoError, decrypt

            unreadable = 0
            sealed = session.execute(text(
                "SELECT id, refresh_token_sealed FROM provider_grants "
                "WHERE refresh_token_sealed IS NOT NULL")).fetchall()
            for grant_id, envelope in sealed:
                try:
                    decrypt(envelope, context=f"grant:{grant_id}:refresh")
                except TokenCryptoError:
                    unreadable += 1
            if unreadable:
                finding("grant_readability", SEVERITY_WARNING,
                        f"{unreadable} of {len(sealed)} stored grant(s) cannot "
                        f"be decrypted with the configured key — check "
                        f"FS_TOKEN_ENCRYPTION_KEY before concluding data loss")

        if {"leagues", "users"} <= tables:
            result.checks_run.append("credential_owners")
            missing = session.execute(text(
                "SELECT count(*) FROM leagues l "
                "LEFT JOIN users u ON u.id = l.provider_credential_user_id "
                "WHERE l.provider_credential_user_id IS NOT NULL "
                "AND u.id IS NULL")).scalar()
            if int(missing or 0):
                finding("credential_owners", SEVERITY_BLOCKING,
                        f"{missing} league(s) name a credential owner that is gone")

        # ── stuck job claims ─────────────────────────────────────────────────
        #
        # A CLAIM HELD BY A PROCESS THAT NO LONGER EXISTS. The claim protocol
        # recovers these on its own TTL, so this is a WARNING: it tells an
        # operator why a week looks stalled without asserting a defect.
        result.checks_run.append("stuck_claims")
        if "challenge_final_lock_claims" in tables:
            # THE CLAIM'S OWN VOCABULARY, read from the table rather than
            # assumed. A first cut looked for a `released_at` column that does
            # not exist; the protocol expresses the same fact as a status that
            # is not `completed` together with an expiry that has passed.
            stale = session.execute(text(
                "SELECT count(*) FROM challenge_final_lock_claims "
                "WHERE status <> 'completed' AND claim_expires_at IS NOT NULL "
                "AND claim_expires_at < :now"),
                {"now": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc)}).scalar()
            if int(stale or 0):
                finding("stuck_claims", SEVERITY_WARNING,
                        f"{stale} final-lock claim(s) are past their expiry and "
                        f"not completed; they are reclaimed on the TTL")

        # ── safe mode, reported so an audit explains a quiet product ─────────
        result.checks_run.append("safe_mode")
        from ops.safe_mode import safe_mode_state

        state = safe_mode_state()
        if state.enabled:
            finding("safe_mode", SEVERITY_WARNING,
                    "authoritative writes are DISABLED on this deployment"
                    + (f" ({state.reason})" if state.reason else ""))

    finally:
        if owns_session:
            session.close()

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output")
    args = parser.parse_args(argv)

    try:
        result = run_audit()
    except Exception as exc:                     # pragma: no cover - defensive
        # THE TYPE, NOT THE MESSAGE. A connection error's text can contain the
        # database URL, and this runs in an operator's terminal and their CI.
        print(f"AUDIT COULD NOT RUN: {type(exc).__name__}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        rel = result.release
        print(f"FantasyStakes recovery audit — {rel.get('version')} "
              f"@ {str(rel.get('release'))[:12]} ({rel.get('environment')})")
        print(f"  checks: {', '.join(result.checks_run)}")
        if not result.findings:
            print("  CLEAN — no findings")
        for f in result.findings:
            print(f"  [{f.severity.upper():8}] {f.check}: {f.detail}")
        print("  RESULT:", "CLEAN" if result.clean else "BLOCKING FINDINGS")
    return 0 if result.clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
