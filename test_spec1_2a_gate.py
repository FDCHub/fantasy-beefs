"""
test_spec1_2a_gate.py — Sprint 2 Package 2A: the production gate.

WHAT THIS PROVES, and why it is the most important suite in the package. Spec 1
§1 requires the new lifecycle stay unreachable until Spec 2 supplies escrow, and
§12 requires that be "proven by unreachability, not throwing stubs". A throwing
stub is a path that exists and fails; unreachability is the absence of a path.
This suite asserts the absence.

    G1  no Proposal Lifecycle route is registered      [SUPERSEDED — WP5]
    G2  no module reachable from api.main imports beefs.proposal_lifecycle
                                                       [SUPERSEDED — WP5]
    G3  the service contains ZERO commit() calls — it cannot create committed
        lifecycle state on its own, so acceptance cannot become economically
        live without Package 2B owning the transaction (§10)
    G4  no wallet / ledger / escrow / Stripe mutation surface is reachable
    G5  the legacy beef path is untouched

G1 AND G2 EXPIRED ON THEIR OWN TERMS. §1 gated the lifecycle "until Spec 2
supplies escrow"; Spec 2 supplied it, and S8-P4C-1 cut the application over to
the funded path. Both are now inverted into SUPERSEDED-CHECKs that fail if the
application ever stops reaching it, and their original property is covered by
test_s8_p4c1_lifecycle_cutover.py and test_p1_l4_challenge_escrow_pg.py. See the
block above G2 in the body. G3, G4 and G5 are unaffected and still run — G3
especially, because the service owning no transaction of its own is what made
the cutover safe.

ORDER WAS LOAD-BEARING IN G2 while it asserted absence: api.main was imported
first and sys.modules asked whether the service came with it, and this suite
never imported beefs.proposal_lifecycle itself because doing so would have
destroyed the evidence. The inverted check reads the same signal, so the order
is preserved.

SCANS RUN ON EXECUTABLE TOKENS, not raw text. The service documents its own
prohibitions in prose — "no ledger posting", "IT NEVER COMMITS" — and a grep
cannot tell a written prohibition from a violation of it. This lesson was paid
for twice in B6; comments and string literals are stripped before any scan.

Runs under the PostgreSQL harness so importing db.schema binds to the disposable
test database rather than creating a stray SQLite file. It performs no database
work of its own.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] Package 2A gate suite cannot run:\n  {e}")
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

    REPO    = Path(os.path.dirname(os.path.abspath(__file__)))
    SERVICE = "beefs/proposal_lifecycle.py"
    MODULE  = "beefs.proposal_lifecycle"

    # ══════════════════════════════════════════════════════════════════════
    # G2 — SUPERSEDED AT WP5, ON THIS SUITE'S OWN TERMS
    # ══════════════════════════════════════════════════════════════════════
    #
    # THE REQUIREMENT WAS CONDITIONAL AND THE CONDITION HAS BEEN MET. This
    # file's own docstring states it: "Spec 1 §1 requires the new lifecycle stay
    # unreachable UNTIL SPEC 2 SUPPLIES ESCROW". Spec 2 supplied it —
    # `economy/challenge_funding.py` posts real escrow at issue (P1-L4), binds
    # accepted terms (P1-L4A), and S8-P4C-1 cut the application over to that
    # funded lifecycle deliberately. `api/main.py` therefore imports
    # `beefs.proposal_lifecycle` on purpose, at five call sites.
    #
    # SO G1 AND G2 NOW ASSERT THE OPPOSITE OF THE SHIPPED DESIGN. Leaving them
    # red would be exactly the "known failure" that hid four packages' worth of
    # drift until WP5; deleting them would erase the record of why the gate
    # existed. They are marked superseded HERE, with their replacement named.
    #
    # WHAT COVERS THE PROPERTY NOW — unreachability was a proxy for "acceptance
    # cannot become economically live without an owner for the money". That is
    # now asserted directly, against the live path rather than its absence:
    #
    #   test_s8_p4c1_lifecycle_cutover.py   the application's proposal path IS
    #                                       the funded lifecycle, end to end
    #   test_p1_l4_challenge_escrow_pg.py   issuing posts real escrow
    #   test_p1_l4a_accepted_terms_revive_pg.py  acceptance binds the terms
    #   test_s8_p4c1r_wagering_authority.py wagering authority on that path
    #
    # G3, G4 and G5 BELOW ARE NOT SUPERSEDED and still run. G3 in particular —
    # the service commits nothing of its own — is the invariant that made the
    # cutover safe, and it must keep holding now that the path is live.
    print("\nG2   SUPERSEDED — the lifecycle is deliberately reachable since "
          "S8-P4C-1")
    print("     Spec 1 §1 gated it 'until Spec 2 supplies escrow'; Spec 2 did.")
    print("     Replacement coverage: test_s8_p4c1_lifecycle_cutover.py, "
          "test_p1_l4_challenge_escrow_pg.py")

    import api.main                                   # noqa: F401 — imported for the graph
    # The supersession is asserted, not assumed: if the application ever STOPPED
    # reaching the funded lifecycle, that would be a real regression and this
    # must fail rather than quietly agreeing with a build that had lost it.
    _assert("G2 SUPERSEDED-CHECK: the application does reach the funded "
            "lifecycle, as S8-P4C-1 intended",
            MODULE in sys.modules,
            str([m for m in sys.modules if "proposal_lifecycle" in m]))
    # THE CONTROL, RE-ANCHORED AT WP5. It used to name `beefs.beef_engine`,
    # which api.main no longer pulls in at import time — another consequence of
    # the S8-P4C-1 cutover, since the legacy engine stopped being the reachable
    # path. Anchoring the control to a module that is no longer loaded made it
    # fail while proving nothing. It now names the settlement engine, which the
    # application does load, and asserts a breadth of app modules rather than
    # one name so a single future import change cannot silently hollow it out.
    _app_modules = [m for m in sys.modules
                    if m.startswith(("betting.", "economy.", "beefs."))]
    _assert("G2 CONTROL: importing api.main really did load the app's own "
            "modules, so the check above is not vacuous",
            "api.main" in sys.modules
            and "betting.settlement_engine" in sys.modules
            and len(_app_modules) >= 5,
            f"{len(_app_modules)} app module(s) loaded with api.main")

    from api.main import app

    # ══════════════════════════════════════════════════════════════════════
    # G1 — no route
    # ══════════════════════════════════════════════════════════════════════
    print("\nG1   no Proposal Lifecycle route is registered")
    # The four legacy beef paths are pre-existing and are pinned exactly below;
    # /beef/counter in particular is the LEGACY mutable counter, not the new
    # versioned one, so it is excluded here rather than flagged. The scan is for
    # a NEW-model route appearing.
    LEGACY_BEEF_PATHS = {
        "/beef/challenge", "/beef/counter", "/beef/pending/{team_id}",
        "/beef/respond",
    }
    paths = sorted({getattr(r, "path", "") for r in app.routes})
    suspicious = [p for p in paths
                  if p not in LEGACY_BEEF_PATHS
                  and re.search(r"proposal|counter|revive|negotiat", p, re.I)]
    _assert("G1 no route path outside the legacy four mentions proposals, "
            "counters, revive or negotiation", suspicious == [], str(suspicious))

    beef_routes = sorted(
        (r.path, tuple(sorted(getattr(r, "methods", None) or ())))
        for r in app.routes if "/beef" in getattr(r, "path", "")
    )
    _assert("G1 the ONLY beef routes are the four pre-existing legacy ones",
            beef_routes == [
                ("/beef/challenge",        ("POST",)),
                ("/beef/counter",          ("POST",)),
                ("/beef/pending/{team_id}", ("GET",)),
                ("/beef/respond",          ("POST",)),
            ], str(beef_routes))
    _assert("G1 CONTROL: the legacy four really are still registered, so the "
            "exclusion above hides nothing",
            LEGACY_BEEF_PATHS == {p for p, _ in beef_routes}, str(beef_routes))

    # SUPERSEDED AT WP5, with G2 above and for the same reason. `api/main.py`
    # names the lifecycle deliberately since S8-P4C-1; the other three route
    # modules still must not, because the cutover was to the Versus path only
    # and a Pool, war-room or health route reaching the negotiation service
    # would be a genuine scope breach. So the claim narrows rather than
    # disappears: exactly one route module may name it, and it is the one that
    # was authorised to.
    for rel in ("api/pool_routes.py", "api/war_room_routes.py",
                "api/health_routes.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        _assert(f"G1 {rel} never names proposal_lifecycle, even lazily",
                "proposal_lifecycle" not in src)

    _main_src = (REPO / "api/main.py").read_text(encoding="utf-8")
    _assert("G1 SUPERSEDED-CHECK: api/main.py names the lifecycle, as the "
            "S8-P4C-1 cutover requires",
            "proposal_lifecycle" in _main_src)

    # ══════════════════════════════════════════════════════════════════════
    # Source scans — executable tokens only
    # ══════════════════════════════════════════════════════════════════════
    def _code_only(src: str) -> str:
        skip = {tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE,
                tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
        for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
            tok = getattr(tokenize, name, None)
            if tok is not None:
                skip.add(tok)
        return " ".join(
            t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type not in skip)

    raw  = (REPO / SERVICE).read_text(encoding="utf-8")
    code = _code_only(raw)
    tree = ast.parse(raw)

    _assert("SCAN CONTROL: the code-only view is not empty and holds real code",
            "def issue_proposal_challenge" in re.sub(r"\s+", " ", code)
            or "issue_proposal_challenge" in code, code[:80])

    # ══════════════════════════════════════════════════════════════════════
    # G3 — zero commits
    # ══════════════════════════════════════════════════════════════════════
    print("\nG3   the service contains ZERO commit() calls (§10)")
    txn_calls = [f"{n.func.attr}:{n.lineno}" for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr in ("commit", "rollback", "begin",
                                     "begin_nested", "close")]
    _assert("G3 no commit(), rollback(), begin() or close() anywhere in the "
            "service — it owns no transaction", txn_calls == [], str(txn_calls))
    _assert("G3 CONTROL: it does use flush(), which writes inside the CALLER's "
            "transaction and is discarded by the caller's rollback",
            any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "flush" for n in ast.walk(tree)))
    _assert("G3 no SessionLocal is constructed — the session is always the "
            "caller's", "SessionLocal" not in code)
    _assert("G3 no engine is touched directly", "engine" not in code)

    # ══════════════════════════════════════════════════════════════════════
    # G4 — no economic surface
    # ══════════════════════════════════════════════════════════════════════
    print("\nG4   no wallet / ledger / escrow / Stripe surface is reachable")
    BANNED_NAMES = ("ledger_post", "wm_deposit", "deposit", "_place_beef_side",
                    "balance_of", "_balance_of_in_session", "trial_balance",
                    "_verify_wallet_available", "_challenge_reserved",
                    "APPROVED_BAB_TOPOFF_DOOR")
    for name in BANNED_NAMES:
        _assert(f"G4 the service never references {name}",
                re.search(rf"(?<![A-Za-z_]){re.escape(name)}(?![A-Za-z_])",
                          code) is None)

    BANNED_MODELS = ("Wallet", "Bet", "LedgerEntry", "FaabTransaction",
                     "Transaction", "BeefStarter")
    for model in BANNED_MODELS:
        _assert(f"G4 the service never imports or touches the {model} model",
                re.search(rf"(?<![A-Za-z_]){model}(?![A-Za-z_])", code) is None)

    _assert("G4 no Stripe symbol appears in executable code",
            re.search(r"stripe", code, re.I) is None)
    _assert("G4 the service assigns no balance attribute",
            re.search(r"\.\s*balance\s*=", code) is None)
    _assert("G4 the service never imports beef_engine — an import is the first "
            "step of a reachable path",
            "beef_engine" not in code)
    _assert("G4 the service never imports anything from api/",
            re.search(r"(?<![A-Za-z_])api\s*\.", code) is None)

    # What it MAY touch: only the three lifecycle models plus Roster.
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                imported.add(f"{n.module}.{a.name}")
        elif isinstance(n, ast.Import):
            for a in n.names:
                imported.add(a.name)
    schema_imports = {i.split(".")[-1] for i in imported if i.startswith("db.schema.")}
    _assert("G4 it imports exactly the four models the lifecycle needs",
            schema_imports == {"BeefChallenge", "BeefProposal",
                               "BeefProposalStarter", "Roster"},
            str(sorted(schema_imports)))
    _assert("G4 POSITIVE CONTROL: it really does import from db.schema, so the "
            "import scan is reading something",
            any(i.startswith("db.schema.") for i in imported))

    # ══════════════════════════════════════════════════════════════════════
    # G5 — the legacy path is untouched
    # ══════════════════════════════════════════════════════════════════════
    print("\nG5   the legacy beef path is unaffected")
    legacy = (REPO / "beefs" / "beef_engine.py").read_text(encoding="utf-8")
    _assert("G5 beef_engine.py does not reference the new lifecycle",
            "proposal_lifecycle" not in legacy)
    _assert("G5 beef_engine.py still owns the legacy economic path",
            "_place_beef_side" in legacy and "ledger_post" in legacy,
            "its behaviour is deliberately unchanged by Package 2A")
    _assert("G5 the legacy challenge-scoped starter capture is still present",
            "_capture_beef_starters" in legacy)
    _assert("G5 db/schema.py still declares all three Spec 1 models",
            all(f"class {m}(Base)" in
                (REPO / "db" / "schema.py").read_text(encoding="utf-8")
                for m in ("BeefChallenge", "BeefProposal", "BeefProposalStarter")))

    # Package 2B's surfaces must NOT have appeared early.
    print("\nG-2B  no Package 2B surface was implemented early")
    for banned, why in (
        (r"escrow:challenge:", "escrow-at-issue account"),
        (r"required_top_up",   "counter-time capacity validation"),
        (r"available_to_bet",  "shared Available to Bet"),
        (r"refund",            "refund posting"),
    ):
        _assert(f"G-2B the service implements no {why}",
                re.search(banned, code, re.I) is None)


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
