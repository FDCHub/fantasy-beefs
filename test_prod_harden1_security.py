#!/usr/bin/env python3
"""
test_prod_harden1_security.py — PROD-HARDEN-1 · secrets, logs and cookies.

WHAT THIS CERTIFIES. That production hardening did not open anything. This
package added a release endpoint, a readiness endpoint, a configuration report,
a write-disable, an audit and a smoke test — six new surfaces, every one of
which is a plausible place for a secret to escape, and several of which an
operator will run against production and paste into a ticket.

── THE THREE QUESTIONS ─────────────────────────────────────────────────────

    §37  is any real secret tracked by git?
    §27  can any of the new operational surfaces print one?
    §38  are the production browser-security assumptions still intact?

A failure of the first is a launch blocker and this suite says so.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_failures: list[str] = []
_blockers: list[str] = []


def _assert(label: str, condition: bool, detail: str = "",
            blocker: bool = False) -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)
        if blocker:
            _blockers.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _code_only(text_: str) -> str:
    for quote in ('"' * 3, "'" * 3):
        text_ = re.sub(quote + r"[\s\S]*?" + quote, " ", text_)
    return re.sub(r"^\s*#.*$", " ", text_, flags=re.M)


# ── 1 · §37 · nothing secret is tracked ──────────────────────────────────────

_section("1 · §37 · No real secret is tracked by git")

_tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                          text=True).stdout.split()

_SECRET_PATHS = ("secrets/", "private.json", "yahoo_oauth.json", ".env",
                 "id_rsa", ".pem", ".pfx", "credentials.json")
_offenders = [f for f in _tracked
              if any(part in f for part in _SECRET_PATHS)
              and not f.endswith(".example")]
_assert("no credential FILE is tracked", not _offenders,
        ", ".join(_offenders) or "none", blocker=True)

_assert("secrets/ is ignored", "secrets/" in _read(".gitignore"))
_assert("  · and .env with it", ".env" in _read(".gitignore"))

# THE CONTENT SCAN. Shaped values in tracked source, with the project's own
# obvious fakes excluded — a scan that flagged `FSFAKEACCESS-AAAA…` would be
# flagging the tests written to prove nothing real is there.
_FAKE_MARKERS = ("FAKE", "MUST-NEVER", "example", "placeholder", "dummy",
                 "test-", "PH1-", "at-", "rt-", "xxx", "your-", "<", "sample",
                 # VALUES THAT ANNOUNCE THEMSELVES. `RUNBOOK.md` carries
                 # `devpass` and `local-dev-only-change-me`; a scan that called
                 # those launch blockers would be crying wolf at documentation
                 # doing exactly the right thing.
                 "changeme", "change-me", "devpass", "local-dev", "dev-only",
                 # THIS SUITE'S OWN FIXTURES. The redaction checks below need
                 # values SHAPED like secrets to prove the config report never
                 # echoes one — and the moment this file became tracked, the
                 # scanner started reporting its own evidence as a finding.
                 # Naming them is honest; blinding the scan to this file would
                 # not be.
                 "SUPERSECRETPASSWORD", "JWTSECRETVALUE",
                 "YAHOOCLIENTSECRETVALUE", "dj0yCLIENTIDVALUE")
_PATTERNS = (
    (r"dj0y[A-Za-z0-9_-]{20,}", "a Yahoo client id"),
    (r"\bAKIA[0-9A-Z]{16}\b", "an AWS key id"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "a private key"),
    (r"postgres(?:ql)?://[^\s\"']*:[^\s\"'@]{6,}@[^\s\"']+", "a database URL "
                                                             "with a password"),
    (r"(?i)(client_secret|jwt_secret|secret_key)\s*[:=]\s*[\"'][A-Za-z0-9/+=_-]{20,}[\"']",
     "an inline secret assignment"),
)

def _is_local_test_dsn(fragment: str) -> bool:
    """A loopback DSN naming a `_test` database is the local disposable target.

    NOT A JUDGEMENT ABOUT THE PASSWORD — a judgement about REACH. The project's
    own harnesses refuse any database whose name lacks `_test` and refuse any
    non-local host, so a credential meeting both is one that opens a throwaway
    container on the developer's own machine. A real secret is one that reaches
    something somebody else can.
    """
    return (("@127.0.0.1" in fragment or "@localhost" in fragment)
            and "_test" in fragment)


_hits: list[str] = []
for path in _tracked:
    if not path.endswith((".py", ".js", ".mjs", ".json", ".toml", ".md",
                          ".yml", ".yaml", ".html", ".cfg", ".ini")):
        continue
    full = os.path.join(ROOT, path)
    if not os.path.isfile(full):
        continue
    try:
        body = open(full, encoding="utf-8", errors="replace").read()
    except Exception:                            # pragma: no cover - defensive
        continue
    for pattern, what in _PATTERNS:
        for match in re.finditer(pattern, body):
            fragment = match.group(0)
            if any(marker in fragment for marker in _FAKE_MARKERS):
                continue
            # THE LOCAL DISPOSABLE TEST TARGET IS NOT A SECRET, and calling it
            # one would make this scan cry wolf on the documented way to run the
            # PostgreSQL suites. `postgres:postgres` is a published default, on
            # loopback, against a database whose name must contain `_test` — the
            # project's own harnesses refuse anything else. A real secret is a
            # non-default credential on a host somebody else can reach.
            if _is_local_test_dsn(fragment):
                continue
            # The line, so an obvious fixture context is visible too.
            line_start = body.rfind("\n", 0, match.start()) + 1
            line = body[line_start:body.find("\n", match.start())]
            if any(marker.lower() in line.lower() for marker in _FAKE_MARKERS):
                continue
            _hits.append(f"{path}: {what}")

_assert("no secret-shaped value in tracked source", not _hits,
        "; ".join(sorted(set(_hits))) or "clean", blocker=True)

# THE PROJECT'S OWN DEPLOYMENT CONFIG carries no value either.
for config in ("railway.toml", "railway.final_lock.toml", "Procfile"):
    body = _read(config)
    _assert(f"{config} carries no secret value",
            not re.search(r"(SECRET|PASSWORD|TOKEN|KEY)\s*=\s*\S", body),
            "declares commands and builders only")


# ── 2 · §27 · the new operational surfaces cannot print a secret ─────────────

_section("2 · §27 · Operational surfaces redact by construction")

_OPS_MODULES = ("ops/release.py", "ops/config.py", "ops/safe_mode.py",
                "ops/audit.py", "ops/smoke.py", "migrations/run.py",
                "migrations/manifest.py")

for module in _OPS_MODULES:
    code = _code_only(_read(*module.split("/")))
    emitters = re.findall(
        r"(?:print|log(?:ger)?\.\w+)\s*\((.*?)\)\s*$", code, re.S | re.M)
    leaky = [call for call in emitters
             if re.search(r"\b(?:access_token|refresh_token|id_token|"
                          r"client_secret|password|_KEY|encryption_key)\b",
                          call)]
    _assert(f"{module} prints no credential", not leaky,
            "; ".join(leaky)[:110] or "none")

# THE CONFIG REPORT CARRIES NAMES, NOT VALUES — driven, not read.
from ops.config import evaluate_config                             # noqa: E402
from auth.token_crypto import generate_key                         # noqa: E402

_KEY = generate_key()
_SECRET_VALUES = {
    "FS_ENV": "production",
    "DATABASE_URL": "postgresql://u:SUPERSECRETPASSWORD@h/x",
    "FS_TOKEN_ENCRYPTION_KEY": _KEY,
    "JWT_SECRET_KEY": "JWTSECRETVALUE" + "z" * 30,
    "FS_YAHOO_CLIENT_ID": "dj0yCLIENTIDVALUE",
    "FS_YAHOO_CLIENT_SECRET": "YAHOOCLIENTSECRETVALUE",
    "FS_YAHOO_REDIRECT_URI": "https://x/cb",
}
_report = json.dumps(evaluate_config(_SECRET_VALUES).as_dict())
for value, what in ((_KEY, "the encryption key"),
                    ("SUPERSECRETPASSWORD", "the database password"),
                    ("JWTSECRETVALUE", "the session secret"),
                    ("YAHOOCLIENTSECRETVALUE", "the Yahoo client secret")):
    _assert(f"the configuration report never contains {what}",
            value not in _report, blocker=True)

from ops.release import release_identity                           # noqa: E402

_identity = json.dumps(release_identity(_SECRET_VALUES,
                                        use_cache=False).as_dict())
for value, what in ((_KEY, "the encryption key"),
                    ("SUPERSECRETPASSWORD", "the database password")):
    _assert(f"the release identity never contains {what}",
            value not in _identity, blocker=True)

# THE SMOKE TEST ACTIVELY LOOKS FOR LEAKS, and it must not be the leak.
_SMOKE = _read("ops", "smoke.py")
_assert("the smoke test sweeps responses for credential terms",
        "_FORBIDDEN_MARKERS" in _SMOKE and "no secret or credential term" in _SMOKE)
_assert("  · and every request it makes is a GET",
        "_get(" in _SMOKE
        and not re.search(r"method\s*=\s*[\"'](POST|PUT|DELETE|PATCH)",
                          _SMOKE))

# THE AUDIT REPORTS COUNTS, NOT CIPHERTEXT.
_AUDIT = _code_only(_read("ops", "audit.py"))
_assert("the audit never puts an envelope in a finding",
        not re.search(r"finding\([^)]*envelope", _AUDIT))
_assert("  · it reports how many failed, not which values",
        "unreadable} of {len(sealed)}" in _read("ops", "audit.py"))


# ── 3 · the write-disable refuses loudly, not generically ───────────────────

_section("3 · §24 · A disabled write is a named refusal, not a 500")

from ops.safe_mode import (                                        # noqa: E402
    REASON_CODE, WritesDisabled, assert_writes_allowed, safe_mode_state,
)

_assert("the reason code is stable", REASON_CODE == "writes_disabled")
try:
    assert_writes_allowed("probe", {"FS_WRITES_DISABLED": "1"})
    _assert("a disabled write raises", False, "it was allowed")
except WritesDisabled as exc:
    _assert("a disabled write raises", True)
    _assert("  · carrying the reason code", exc.reason_code == REASON_CODE)
    _assert("  · and naming the operation", "probe" in str(exc))

_assert("only explicit truthy values enable it",
        not safe_mode_state({"FS_WRITES_DISABLED": "0"}).enabled
        and not safe_mode_state({"FS_WRITES_DISABLED": ""}).enabled
        and safe_mode_state({"FS_WRITES_DISABLED": "true"}).enabled)

# NO ROUTE MAY TOGGLE IT. A user-reachable switch for this would be a denial of
# service with a commissioner's name on it.
_MAIN_CODE = _code_only(_read("api", "main.py"))
_assert("no route sets the write-disable flag",
        "FS_WRITES_DISABLED" not in _MAIN_CODE
        or "environ[" not in _MAIN_CODE.split("FS_WRITES_DISABLED")[0][-200:],
        "environment-controlled only")


# ── 4 · §38 · production browser security is unchanged ──────────────────────

_section("4 · §38 · Production auth and cookie assumptions hold")

_SESSION = _read("auth", "session.py")
_assert("session cookies are HttpOnly", "httponly=True" in _SESSION.lower()
        .replace(" ", "").replace("httponly=true", "httponly=True"))
_assert("cookies are Secure unless explicitly relaxed for development",
        "FS_COOKIE_INSECURE" in _SESSION)
_assert("  · and that relaxation is refused in production",
        "FS_COOKIE_INSECURE must not be set in production"
        in _read("auth", "environment.py"))
_assert("SameSite is set deliberately", "samesite" in _SESSION.lower())
_assert("CSRF protection is active",
        "CSRF_HEADER" in _SESSION and "csrf_failure_reason" in _SESSION)
_assert("  · and compares in constant time",
        "compare_digest" in _SESSION)

_ENVIRONMENT = _read("auth", "environment.py")
_assert("production offers no password login",
        "password=False" in _ENVIRONMENT)
_assert("  · and the readiness list still requires the Yahoo triple",
        "REQUIRED_YAHOO_VARS" in _ENVIRONMENT)

_assert("PKCE is still enforced",
        "no usable PKCE verifier" in _read("auth", "yahoo_oidc.py"))
_assert("  · with S256 only",
        'CHALLENGE_METHOD = "S256"' in _read("auth", "yahoo_oidc.py"))

# THE NEW ENDPOINTS ARE READ-ONLY AND UNAUTHENTICATED BY DESIGN — so they must
# expose nothing that is not already public.
for route in ("/version", "/ready"):
    body = _read("api", "main.py")
    section = body.split(f'@app.get("{route}")')[1][:2000]
    _assert(f"{route} performs no write",
            not re.search(r"\b(db\.add|db\.commit|db\.delete|ledger_post)\b",
                          section))


# ── 5 · the Yahoo isolation this package must not have weakened ─────────────

_section("5 · §56 · Provider isolation is untouched")

_CRED = _code_only(_read("providers", "yahoo", "user_credentials.py"))
_assert("the credential seam still refuses an operator fallback",
        "load_credentials" not in _CRED)
_assert("  · and still names no user but the league's own owner",
        not re.search(r"def bearer_for_league\([^)]*user_id", _CRED))

_TRANSPORT = _code_only(_read("providers", "yahoo", "transport.py"))
_assert("a bare transport still refuses to be constructed",
        "token_provider is None and not _operator_credentials" in _TRANSPORT)
_assert("  · and the operator path is still explicitly named",
        "for_operator_tooling" in _TRANSPORT)

_GRANT = _code_only(_read("auth", "provider_grant.py"))
_assert("the grant store still scopes every read by user",
        "ProviderGrant.user_id == user_id" in _GRANT)


print("\n" + "=" * 66)
if _blockers:
    print(f"PROD-HARDEN-1 SECURITY — {len(_blockers)} LAUNCH BLOCKER(S)")
    for f in _blockers:
        print(f"  · BLOCKER: {f}")
if _failures:
    print(f"PROD-HARDEN-1 SECURITY — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("PROD-HARDEN-1 SECURITY — all assertions PASSED")
