"""
test_b6_group_f_legacy_closure.py — B6 Package 3 Group F, §15 item 21: legacy
Top-Off closure (R1-R5).

WHAT THIS SUITE ESTABLISHES. After B6 there is EXACTLY ONE production Top-Off
issuance path — the five routes in api/main.py calling economy/top_off.py, which
calls the accepted ledger seam. Everything that used to mint wallet balance
another way is either unregistered or refuses structurally.

    R1  no Stripe module, import or symbol is reachable from any B6 path
    R2  apply_pending_topups() still refuses as its FIRST executable statement
    R3  the four legacy /faab/topup-* routes remain unregistered
    R4  confirm_topup, create_bet_topup and create_waiver_topup refuse as their
        FIRST executable statement
    R5  wm_deposit is not reachable from any B6 path

EVIDENCE IS STRUCTURAL WHERE THE REQUIREMENT IS STRUCTURAL. §11.5 requires a
"first-statement raise, AST-verified", so R2 and R4 parse the module and inspect
the function bodies rather than grepping for the word "raise" — a raise anywhere
in a function is not the same claim as a raise before anything else can run.
Each refusal is then also exercised, so the structure and the behaviour are
proved separately.

REACHABILITY IS ASKED OF THE RUNTIME, NOT OF TEXT, where that is possible. R1
imports the application and asks sys.modules whether any Stripe module was
loaded; R3 enumerates the routes the app actually registered. Both are evidence
about the app as assembled, which a source scan cannot give.

It runs under the PostgreSQL harness like every other B6 suite. It performs no
database work of its own — the harness is used so importing db.schema binds to
the disposable test database rather than creating a stray SQLite file in the
repository.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] B6 Group F legacy-closure suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    import ast
    import io
    import re
    import tokenize
    from pathlib import Path

    from api.main import app
    from wallet.faab_wallet import (
        TopUpsUnavailableError,
        apply_pending_topups, confirm_topup, create_bet_topup,
        create_waiver_topup,
    )

    REPO = Path(os.path.dirname(os.path.abspath(__file__)))

    def _code_only(src: str) -> str:
        """Executable tokens only — comments and string literals removed.

        Scanning raw source would be wrong here for the same reason it was in
        the Group E suite: these modules DOCUMENT their prohibitions in prose
        ("no Stripe path exists on it"), and a grep cannot tell a written
        prohibition from a violation of it.
        """
        skip = {tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE,
                tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
        for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
            tok = getattr(tokenize, name, None)
            if tok is not None:
                skip.add(tok)
        return " ".join(
            t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type not in skip)

    def _first_executable(fn_node):
        """The first statement that actually RUNS — the docstring, being an
        expression statement, is skipped exactly once."""
        body = fn_node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(getattr(body[0], "value", None), ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]
        return body[0] if body else None

    faab_src  = (REPO / "wallet" / "faab_wallet.py").read_text(encoding="utf-8")
    faab_tree = ast.parse(faab_src)
    faab_fns  = {n.name: n for n in ast.walk(faab_tree)
                 if isinstance(n, ast.FunctionDef)}

    # ══════════════════════════════════════════════════════════════════════
    # R2 / R4 — structural first-statement refusal
    # ══════════════════════════════════════════════════════════════════════
    print("\nR2/R4  the legacy top-up writers refuse as their FIRST executable "
          "statement (§11.5, AST-verified)")

    REFUSERS = {
        "apply_pending_topups": "R2",
        "confirm_topup":        "R4",
        "create_bet_topup":     "R4",
        "create_waiver_topup":  "R4",
    }
    for fn_name, tag in REFUSERS.items():
        node = faab_fns.get(fn_name)
        _assert(f"{tag} {fn_name} exists in wallet/faab_wallet.py", node is not None)
        if node is None:
            continue
        first = _first_executable(node)
        _assert(f"{tag} {fn_name}: the first executable statement is a raise",
                isinstance(first, ast.Raise),
                type(first).__name__ if first else "empty body")
        raised = None
        if isinstance(first, ast.Raise) and isinstance(first.exc, ast.Call):
            raised = getattr(first.exc.func, "id", None) or \
                     getattr(first.exc.func, "attr", None)
        _assert(f"{tag} {fn_name}: it raises TopUpsUnavailableError",
                raised == "TopUpsUnavailableError", str(raised))

    # The structural claim is that nothing runs BEFORE the raise. Prove it by
    # calling each writer with a session that would explode if it were touched:
    # None. A refusal that reached any query would raise AttributeError instead.
    print("\nR2/R4  each refusal is reached before any database work")
    for label, call in (
        ("apply_pending_topups", lambda: apply_pending_topups(None)),
        ("confirm_topup",        lambda: confirm_topup(1, None)),
        ("create_bet_topup",     lambda: create_bet_topup(1, 10.0, None)),
        ("create_waiver_topup",  lambda: create_waiver_topup(1, 10.0, None)),
    ):
        try:
            call()
            exc = None
        except Exception as e:                    # noqa: BLE001 — recording
            exc = e
        _assert(f"R2/R4 {label}() raises TopUpsUnavailableError even with db=None",
                isinstance(exc, TopUpsUnavailableError),
                f"got {type(exc).__name__}: {exc}")

    # Positive control: the retained bodies are still present but unreached, so
    # the assertions above are about ordering, not about deleted code.
    for fn_name in ("confirm_topup", "create_bet_topup", "create_waiver_topup"):
        node = faab_fns[fn_name]
        _assert(f"R4 {fn_name}: the historical body is retained UNREACHED",
                len(node.body) > 2, f"{len(node.body)} statements")

    # ══════════════════════════════════════════════════════════════════════
    # R3 — the legacy routes remain unregistered
    # ══════════════════════════════════════════════════════════════════════
    print("\nR3   the four legacy /faab/topup-* routes remain UNREGISTERED "
          "(§10.3)")
    registered = {getattr(r, "path", "") for r in app.routes}
    for legacy in ("/faab/topup-bet", "/faab/topup-waiver", "/faab/topup-confirm",
                   "/faab/apply-pending"):
        _assert(f"R3 {legacy} is not registered", legacy not in registered)

    topoff_routes = sorted(
        (r.path, tuple(sorted(getattr(r, "methods", None) or ())))
        for r in app.routes if "top-offs" in getattr(r, "path", "")
    )
    _assert("R3 EXACTLY FIVE Top-Off routes are registered, and no more",
            topoff_routes == [
                ("/league/{league_id}/top-offs",                      ("GET",)),
                ("/league/{league_id}/top-offs",                      ("POST",)),
                ("/league/{league_id}/top-offs/{request_id}/approve", ("POST",)),
                ("/league/{league_id}/top-offs/{request_id}/cancel",  ("POST",)),
                ("/league/{league_id}/top-offs/{request_id}/reject",  ("POST",)),
            ], str(topoff_routes))
    _assert("R3 no Top-Off route exposes DELETE or PUT",
            not any(m in ("DELETE", "PUT", "PATCH")
                    for _, ms in topoff_routes for m in ms), str(topoff_routes))

    # ══════════════════════════════════════════════════════════════════════
    # R1 — Stripe is unreachable
    # ══════════════════════════════════════════════════════════════════════
    print("\nR1   no Stripe module, import or symbol is reachable from any B6 "
          "path")
    # RUNTIME evidence: the whole application is imported by now, so anything a
    # B6 path could reach at import time is in sys.modules.
    stripe_modules = sorted(m for m in sys.modules
                            if "stripe" in m.lower())
    _assert("R1 NO Stripe module is loaded anywhere in the imported application",
            stripe_modules == [], str(stripe_modules))

    b6_sources = {
        "economy/top_off.py":                    None,
        "db/migrations/migrate_b6_top_off.py":   None,
    }
    for rel in list(b6_sources):
        b6_sources[rel] = _code_only((REPO / rel).read_text(encoding="utf-8"))
    for rel, code in b6_sources.items():
        _assert(f"R1 {rel} contains no stripe symbol in executable code",
                re.search(r"stripe", code, re.I) is None)

    api_code = _code_only((REPO / "api" / "main.py").read_text(encoding="utf-8"))
    _assert("R1 api/main.py imports no stripe module in executable code",
            re.search(r"stripe_connect|import\s+stripe", api_code, re.I) is None)
    # The FaabTransaction stripe_* columns are dormant legacy schema (§11.5) and
    # are deliberately NOT dropped; the claim is about reachable code paths, and
    # this is where the two are separated rather than conflated.
    _assert("R1 CONTROL: the dormant stripe_* columns are still declared in the "
            "model, so the scan above is about code paths, not schema",
            "stripe_link_id" in (REPO / "db" / "schema.py").read_text(encoding="utf-8"))

    # ══════════════════════════════════════════════════════════════════════
    # R5 — wm_deposit is unreachable from B6
    # ══════════════════════════════════════════════════════════════════════
    print("\nR5   wm_deposit is not reachable from any B6 path")
    topoff_code = b6_sources["economy/top_off.py"]
    _assert("R5 the issuance service never references wm_deposit or deposit()",
            re.search(r"(?<![A-Za-z_])(wm_deposit|deposit)\s*\(", topoff_code) is None)

    # The five route functions, by AST: collect every call they make and prove
    # wm_deposit is not among them. api/main.py DOES import wm_deposit for the
    # unrelated legacy wallet surface, so an import-level check would be
    # meaningless — the question is what the B6 handlers call.
    api_tree = ast.parse((REPO / "api" / "main.py").read_text(encoding="utf-8"))
    B6_HANDLERS = {"league_create_top_off", "league_approve_top_off",
                   "league_reject_top_off", "league_cancel_top_off",
                   "league_list_top_offs"}
    handlers = {n.name: n for n in ast.walk(api_tree)
                if isinstance(n, ast.FunctionDef) and n.name in B6_HANDLERS}
    _assert("R5 all five B6 route handlers were found for inspection",
            set(handlers) == B6_HANDLERS, str(sorted(handlers)))
    # BODY ONLY, and BARE NAMES only. decorator_list is deliberately excluded:
    # every one of these handlers is decorated with @app.post(...), and walking
    # the whole node would flag the router registration itself. Restricting to
    # bare-name calls keeps `app.post` (an attribute call) out of scope while
    # still catching a direct `post(...)` or `ledger_post(...)`, which is what a
    # second issuance implementation inside a route would actually look like.
    BANNED_DIRECT_CALLS = {"wm_deposit", "deposit", "post", "ledger_post",
                           "_balance_of_in_session"}
    banned_calls = []
    for name, node in handlers.items():
        for stmt in node.body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    if sub.func.id in BANNED_DIRECT_CALLS:
                        banned_calls.append(f"{name} -> {sub.func.id}")
    _assert("R5 no B6 route handler calls wm_deposit, deposit or the ledger "
            "directly — issuance goes through the service alone",
            banned_calls == [], str(banned_calls))

    # ══════════════════════════════════════════════════════════════════════
    # One issuance path
    # ══════════════════════════════════════════════════════════════════════
    print("\nR-one-path  exactly one production Top-Off issuance implementation")
    door_users = []
    for rel in ("api/main.py", "economy/top_off.py", "economy/season_allocation.py",
                "economy/season_close.py", "wallet/faab_wallet.py",
                "wallet/wallet_manager.py"):
        src = _code_only((REPO / rel).read_text(encoding="utf-8"))
        if "APPROVED_BAB_TOPOFF_DOOR" in src:
            door_users.append(rel)
    _assert("R-one-path only economy/top_off.py posts under the canonical "
            "top-off door", door_users == ["economy/top_off.py"], str(door_users))


try:
    main(tdb)
finally:
    tdb.teardown()

print("\n" + "=" * 60)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("All assertions PASSED")