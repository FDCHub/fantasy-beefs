"""
FR-VAL10-af / af-1 — Engine Control Surface control tests  [RED]

Revision:  Rev 6
Rev date:  2026-07-22
Spec:      FR_VAL10_AF_ENGINE_CONTROL_SURFACE_MODULE_SPEC_Rev5.md
Baseline:  HEAD 19aa0bef26d3e9e684c9722e3d0b5e35290d40ec
Scope:     af-1 CONTROL-SURFACE tests only. Behavioral-suite triage is af-2.

REVISION HISTORY
  Rev 1  2026-07-22  Initial draft. Nine tests covering spec Section 9,
                     Tests 1-7. Standalone _assert convention, no pytest.
  Rev 2  2026-07-22  Two self-caught defects from the dry run.
                     (1) _assert_raises caught bare Exception, so ImportError
                         from the absent canonical module made T5b pass before
                         the feature existed. ImportError now never a pass.
                     (2) T6 walked dependency source (uv cache, site-packages)
                         and flagged pandas. Scoped to project source via
                         EXCLUDED_DIRS.
  Rev 3  2026-07-22  Three ruled corrections (Fraser, 2026-07-22).
                     (1) T6 regex could not see
                         `from sqlalchemy import create_engine as _create_engine`
                         — the exact form at per_bet_lock.py:456-458. Replaced
                         with AST-based detection resolving import aliases and
                         attribute calls. Added T6b: unparseable file is an
                         unproven file, must fail not skip. BLOCKING — T6 is
                         the persistent architectural control.
                     (2) T4 printed SKIP without TEST_DATABASE_URL while the
                         script could still exit "CONTROL-SURFACE GREEN". A
                         loud skip is still a skip. Replaced with a
                         deterministic non-live test asserting resolved dialect
                         and connect-listener registry; live check demoted to
                         optional T4c. No SKIP path remains.
                     (3) T7 asserted on a public normalize_url() the spec never
                         authorized. Rewritten to test behavior through the
                         authorized factory (eng.url.drivername).
  Rev 4  2026-07-22  Two ruled test-hardening corrections (Fraser, 2026-07-22).
                     (1) T4b false-green path closed. `connect` is a POOL
                         event: a listener attached via event.listen(engine,
                         "connect", hook) lands on engine.pool.dispatch.connect,
                         not reliably on engine.dispatch.connect. Rev 3
                         inspected engine.dispatch and guessed listener identity
                         from __name__/__doc__ substrings, so it could report
                         clean while the SQLite hook was attached to the
                         PostgreSQL engine. Replaced with exact-symbol
                         event.contains() against engine.pool, plus a positive
                         T4a (hook IS on the SQLite pool). Contract on af-1: the
                         hook must be a module-owned private callable named
                         _sqlite_foreign_keys_on_connect.
                     (2) T6 AST coverage extended to the sqlalchemy.engine
                         namespace: `from sqlalchemy.engine import create_engine`
                         and `sqlalchemy.engine.create_engine(...)`, plus
                         `from sqlalchemy import engine as eng`. The persistent
                         guard must not leave a bypass through SQLAlchemy's
                         secondary namespace. Attribute chains now flattened
                         rather than matched one level deep.
                     Also found while verifying (2): create_engine() on a
                     postgresql:// URL imports the DBAPI driver at CONSTRUCTION
                     time, not connect time. Without psycopg2 installed, T4
                     raised ModuleNotFoundError. Now reported as an explicitly
                     UNPROVEN gate rather than an unrelated crash.
  Rev 5  2026-07-22  No test-logic change. Parent spec pointer updated from
                     Rev 3 to Rev 5 (spec Rev 4 recorded the structural
                     contract these tests already assert; spec Rev 5 aligned
                     Section 5.4 to the AST guard). Header and runtime banner
                     now name the correct parent revision.
  Rev 6  2026-07-22  BOM-aware AST coverage. T6 and T6b now decode with
                     `utf-8-sig` and strict error handling so the walker can
                     inspect every Python source file accepted by Python's
                     normal tokenizer. The isolated BOM in
                     migrate_ledger_entries.py was separately removed as
                     repository hygiene.
                     Basis: the Rev 5 red baseline on ThinkPad reported T6b
                     failing on db/migrations/migrate_ledger_entries.py
                     (SyntaxError). Diagnosis: UTF-8 BOM at byte 0; py_compile
                     passes, so the file is valid — plain utf-8 decode left
                     U+FEFF in the string and ast.parse rejected it. Sole
                     offender across all 11 migrations. Fixing only the file
                     would have left the walker unable to read the NEXT BOM'd
                     file; fixing only the decode would have left a
                     non-idiomatic BOM in the repo. Both were required.
                     errors="ignore" (Rev 2) replaced with errors="strict":
                     ignoring undecodable bytes would hand ast.parse mangled
                     source that could parse clean, hiding a constructor.
                     UnicodeDecodeError added to the unproven-file catch.
                     Shipped under existing af-1 authorization (Fraser,
                     2026-07-22) — encoding detection is an implementation
                     detail making spec Rev 5 Section 5.4's total-coverage
                     requirement true, not a new requirement. No spec Rev
                     required.

RED BY DESIGN. The canonical engine module does not exist at HEAD. Every test
below fails on import or assertion until af-1 lands, then turns green. Do not
"fix" these by relaxing them.

Convention: standalone script, module-level _assert harness, sys.exit(1) on
failure. Matches the existing 23 test scripts. No pytest, no conftest.

Covers spec §9 Tests 1-7. Tests 8-10 are af-2 (full suite under enforcement).

Run:
    python test_af1_engine_control_surface_red.py            # SQLite path
    TEST_DATABASE_URL=postgresql://... python test_af1_...   # + Test 4 live
"""

import os
import sys
import tempfile

# --- revision (keep in sync with the docstring history) ----------------------
REV = "Rev 6"
REV_DATE = "2026-07-22"
SPEC_REV = "FR_VAL10_AF_ENGINE_CONTROL_SURFACE_MODULE_SPEC_Rev5.md"
BASELINE = "19aa0bef26d3e9e684c9722e3d0b5e35290d40ec"

# --- DATABASE_URL discipline -------------------------------------------------
# Must be set before any project import touches db/schema.py, which resolves
# DB_URL at import time (db/schema.py:29-35). Same rule as every other test.
_TMP = os.path.join(tempfile.gettempdir(), "af1_control.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}"

# --- harness -----------------------------------------------------------------
_FAILURES = []
_PASSES = 0


def _assert(cond, label):
    global _PASSES
    if cond:
        _PASSES += 1
        print(f"  PASS  {label}")
    else:
        _FAILURES.append(label)
        print(f"  FAIL  {label}")


def _assert_raises(fn, label, exc=Exception):
    # ImportError is NEVER a pass. Without this guard, a missing canonical
    # module makes every _assert_raises test succeed for the wrong reason —
    # the test would go green before the feature exists.
    try:
        fn()
    except ImportError as e:
        _assert(False, f"{label}  (ImportError, not a real rejection: {e})")
        return
    except exc:
        _assert(True, label)
        return
    except BaseException as e:  # noqa: BLE001
        _assert(False, f"{label}  (raised {type(e).__name__}, expected {exc.__name__})")
        return
    _assert(False, f"{label}  (did not raise)")


# --- canonical module under test ---------------------------------------------
# Spec §5.1. Module path is the spec's contract; if af-1 chooses a different
# path, update HERE ONLY and record the variance in the spec.
CANONICAL_MODULE = "db.engine_factory"
CANONICAL_FACTORY = "get_engine"

_engine_mod = None
try:
    import importlib

    _engine_mod = importlib.import_module(CANONICAL_MODULE)
except ImportError as e:
    print(f"\n  RED: cannot import {CANONICAL_MODULE} — {e}")
    print("  Expected until af-1 lands. All tests below will fail.\n")


def _get_engine(*a, **kw):
    if _engine_mod is None:
        raise ImportError(f"{CANONICAL_MODULE} not present (af-1 not built)")
    return getattr(_engine_mod, CANONICAL_FACTORY)(*a, **kw)


SQLITE_URL = f"sqlite:///{_TMP}"
PG_URL = os.environ.get("TEST_DATABASE_URL", "")


# =============================================================================
# Test 1 — PRAGMA foreign_keys returns 1 on a governed SQLite connection
# Spec §5.2. Applying a pragma and verifying its effect are different acts.
# =============================================================================
def test_1_pragma_returns_one():
    from sqlalchemy import text

    eng = _get_engine(SQLITE_URL)
    with eng.connect() as conn:
        val = conn.execute(text("PRAGMA foreign_keys")).scalar()
    _assert(val == 1, "T1  PRAGMA foreign_keys returns 1 on governed SQLite connection")


# =============================================================================
# Test 2 — a dangling FK reference is rejected at insert on SQLite
# The behavioral proof that enforcement is live, not merely declared.
# =============================================================================
def test_2_dangling_fk_rejected():
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    eng = _get_engine("sqlite:///:memory:")
    with eng.connect() as conn:
        conn.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
        conn.execute(
            text(
                "CREATE TABLE child ("
                "  id INTEGER PRIMARY KEY, "
                "  parent_id INTEGER REFERENCES parent(id))"
            )
        )

        def _insert_orphan():
            conn.execute(text("INSERT INTO child (id, parent_id) VALUES (1, 999)"))

        _assert_raises(
            _insert_orphan,
            "T2  dangling FK reference rejected at insert on SQLite",
            IntegrityError,
        )


# =============================================================================
# Test 3 — the hook applies whenever an engine is constructed THROUGH the
# helper, independent of whether db.schema was imported first.
#
# Spec §9 note: this is the direct answer to the rejected global-listener
# approach (§4). It proves the helper's guarantee holds with no import-order
# precondition. It does NOT claim to govern constructors that bypass the
# helper — that is Test 6's job.
# =============================================================================
def test_3_hook_independent_of_import_order():
    import subprocess

    # Child process constructs an engine through the helper WITHOUT importing
    # db.schema at all. A global Engine listener registered inside db.schema
    # would not fire here; the canonical helper must.
    child = (
        "import os,sys\n"
        f"os.environ['DATABASE_URL']={SQLITE_URL!r}\n"
        f"sys.path.insert(0, {os.getcwd()!r})\n"
        "assert 'db.schema' not in sys.modules\n"
        f"import importlib; m=importlib.import_module({CANONICAL_MODULE!r})\n"
        "from sqlalchemy import text\n"
        f"eng=getattr(m,{CANONICAL_FACTORY!r})({SQLITE_URL!r})\n"
        "assert 'db.schema' not in sys.modules, 'helper pulled in db.schema'\n"
        "with eng.connect() as c:\n"
        "    v=c.execute(text('PRAGMA foreign_keys')).scalar()\n"
        "print('FK=%s' % v)\n"
        "sys.exit(0 if v==1 else 1)\n"
    )
    r = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True)
    _assert(
        r.returncode == 0,
        "T3  hook applies through helper with db.schema never imported"
        + ("" if r.returncode == 0 else f"  ({r.stderr.strip()[:160]})"),
    )


# =============================================================================
# Test 4 — PostgreSQL construction does NOT receive the SQLite hook
#
# DETERMINISTIC, NO LIVE DATABASE. Construction does not connect, so a
# PostgreSQL URL can be built with no server present.
#
# Rev 4: registration is tested by EXACT SYMBOL IDENTITY via event.contains()
# against engine.pool. `connect` is a pool event — a listener attached with
# event.listen(engine, "connect", hook) lands on engine.pool.dispatch.connect,
# not reliably on engine.dispatch.connect. Rev 3 inspected the wrong object and
# then guessed identity from __name__/__doc__ substrings, so it could report
# "no offending hook" while the SQLite hook was attached to the PostgreSQL
# engine — a false green in the test whose whole job is catching that.
#
# CONTRACT ON af-1: the SQLite connect hook must be a module-owned private
# callable named _sqlite_foreign_keys_on_connect. A private symbol is
# acceptable here because this is a structural control test, not a public API.
# =============================================================================
PG_DUMMY_URL = "postgresql://u:p@localhost:5432/nonexistent_db_af1"
SQLITE_HOOK_SYMBOL = "_sqlite_foreign_keys_on_connect"


def test_4_postgres_no_sqlite_hook():
    from sqlalchemy import event

    hook = getattr(_engine_mod, SQLITE_HOOK_SYMBOL, None) if _engine_mod else None
    if hook is None:
        _assert(
            False,
            f"T4  canonical module exposes {SQLITE_HOOK_SYMBOL} for exact-identity "
            f"registration testing (structural control contract)",
        )
        return

    sqlite_engine = _get_engine(SQLITE_URL)

    # NOTE: create_engine() on a postgresql:// URL imports the DBAPI driver at
    # CONSTRUCTION time, even though it does not connect. Without psycopg2
    # installed this raises ModuleNotFoundError. That is an unproven gate, not
    # a pass and not an unrelated crash — report it as such.
    try:
        postgres_engine = _get_engine(PG_DUMMY_URL)
    except ModuleNotFoundError as e:
        _assert(
            False,
            f"T4  PostgreSQL driver required for dialect-scoping proof "
            f"(pip install psycopg2-binary) — gate UNPROVEN, not passed: {e}",
        )
        return

    _assert(
        postgres_engine.dialect.name == "postgresql",
        f"T4  resolved dialect is postgresql (got {postgres_engine.dialect.name!r})",
    )

    # Positive: the hook IS registered on the SQLite pool.
    _assert(
        event.contains(sqlite_engine.pool, "connect", hook),
        "T4a SQLite engine pool has the FK connect hook registered",
    )

    # Negative: the SAME symbol is NOT registered on the PostgreSQL pool.
    _assert(
        not event.contains(postgres_engine.pool, "connect", hook),
        "T4b PostgreSQL engine pool does NOT have the SQLite FK connect hook",
    )

    # Live confirmation, when an instance happens to be available. ADDITIONAL
    # only — never the basis for T4 passing.
    if PG_URL:
        from sqlalchemy import text

        live = _get_engine(PG_URL)
        with live.connect() as conn:
            one = conn.execute(text("SELECT 1")).scalar()
        _assert(one == 1, "T4c live PostgreSQL connection succeeds (optional)")
    else:
        print("  note  T4c live PostgreSQL confirmation not run (no TEST_DATABASE_URL);")
        print("        T4/T4a/T4b are deterministic and DID run — af-1 gate unaffected.")



# =============================================================================
# Tests 5 / 5a / 5b — canonical option policy (spec §5.5)
#
# Two DISTINCT dispositions, per the Rev 3 ruling:
#   excluded  — recognized for another dialect; dropped silently
#   rejected  — recognized for no dialect; raises at construction
# =============================================================================
def test_5_dialect_neutral_options_survive():
    eng = _get_engine(SQLITE_URL, echo=False)
    _assert(eng is not None, "T5  dialect-neutral option (echo) survives routing")


def test_5a_other_dialect_option_excluded():
    # connect_timeout is a recognized libpq/psycopg option. Under a resolved
    # SQLite dialect it must be EXCLUDED — dropped without raising.
    # This is the exact combination sites 2, 5, 6, 7, 8 pass whenever
    # DATABASE_URL is unset, i.e. every test run.
    try:
        eng = _get_engine(SQLITE_URL, connect_args={"connect_timeout": 10})
        from sqlalchemy import text

        with eng.connect() as conn:
            v = conn.execute(text("PRAGMA foreign_keys")).scalar()
        _assert(
            v == 1,
            "T5a connect_timeout excluded under SQLite without raising; hook still applied",
        )
    except Exception as e:  # noqa: BLE001
        _assert(False, f"T5a connect_timeout should be excluded, not raised ({type(e).__name__})")


def test_5b_unknown_option_rejected():
    # Recognized for no dialect -> must RAISE, not be silently dropped.
    _assert_raises(
        lambda: _get_engine(SQLITE_URL, connect_args={"not_a_real_dbapi_option": 1}),
        "T5b unknown option raises at construction (not silently dropped)",
    )


# =============================================================================
# Test 6 — bypass guard
# Keeps §5.3 true over time. Without it, migration is a one-time cleanup
# rather than an enforced boundary.
# =============================================================================
def test_6_bypass_guard():
    """AST-based. A regex on r'\\bcreate_engine\\s*\\(' cannot see
    `from sqlalchemy import create_engine as _create_engine` — which is exactly
    what per_bet_lock.py:456-458 does. Since T6 is the persistent architectural
    control, it must resolve aliases and attribute calls, not match text."""
    import ast
    import pathlib

    root = pathlib.Path(os.getcwd())
    canonical_rel = CANONICAL_MODULE.replace(".", os.sep) + ".py"

    EXCLUDED_DIRS = {
        ".venv", "venv", "env", ".git", "__pycache__", ".cache",
        "site-packages", "node_modules", ".idea", ".pytest_cache", "build", "dist",
    }

    class _Finder(ast.NodeVisitor):
        """Tracks every local name bound to create_engine (from either the
        `sqlalchemy` or `sqlalchemy.engine` namespace), plus every module alias
        of those namespaces, then flags calls through any of them.

        Rev 4 adds the `sqlalchemy.engine` forms:
            from sqlalchemy.engine import create_engine
            import sqlalchemy.engine; sqlalchemy.engine.create_engine(...)
        A persistent architectural guard must not leave an easy bypass through
        SQLAlchemy's secondary namespace."""

        SOURCE_MODULES = {"sqlalchemy", "sqlalchemy.engine"}

        def __init__(self):
            self.direct_names = set()    # create_engine, _create_engine, ce, ...
            self.module_aliases = set()  # sqlalchemy, sa, sqlalchemy.engine, eng, ...
            self.hits = []

        def visit_ImportFrom(self, node):
            if node.module in self.SOURCE_MODULES:
                for a in node.names:
                    if a.name == "create_engine":
                        self.direct_names.add(a.asname or a.name)
                    # `from sqlalchemy import engine as eng` -> eng.create_engine(...)
                    elif a.name == "engine" and node.module == "sqlalchemy":
                        self.module_aliases.add(a.asname or a.name)
            self.generic_visit(node)

        def visit_Import(self, node):
            for a in node.names:
                if a.name in self.SOURCE_MODULES:
                    # `import sqlalchemy.engine` binds the root name `sqlalchemy`
                    self.module_aliases.add(a.asname or a.name.split(".")[0])
                    if a.asname:
                        self.module_aliases.add(a.asname)
            self.generic_visit(node)

        def _attr_chain(self, node):
            """Flatten a.b.c -> ['a','b','c']; None if not a pure name chain."""
            parts = []
            cur = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if not isinstance(cur, ast.Name):
                return None
            parts.append(cur.id)
            return list(reversed(parts))

        def visit_Call(self, node):
            f = node.func
            # bare call: create_engine(...) / _create_engine(...)
            if isinstance(f, ast.Name) and f.id in self.direct_names:
                self.hits.append(node.lineno)
            elif isinstance(f, ast.Attribute) and f.attr == "create_engine":
                chain = self._attr_chain(f)
                if chain:
                    root = chain[0]
                    # sqlalchemy.create_engine / sa.create_engine
                    # sqlalchemy.engine.create_engine / eng.create_engine
                    if root in self.module_aliases or root == "sqlalchemy":
                        self.hits.append(node.lineno)
            self.generic_visit(node)

    offenders = []
    unparseable = []
    for py in root.rglob("*.py"):
        rel_parts = py.relative_to(root).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue
        rel = str(py.relative_to(root))
        if rel.endswith(canonical_rel):
            continue
        if os.path.basename(rel) == os.path.basename(__file__):
            continue
        try:
            # utf-8-sig strips a leading BOM, matching what Python's own
            # tokenizer accepts. Plain utf-8 leaves U+FEFF in the string and
            # ast.parse rejects it as a non-printable character — so the walker
            # could not read a BOM'd file at all, and T6 would silently skip it.
            #
            # errors="strict" is deliberate: errors="ignore" would discard
            # undecodable bytes and hand ast.parse a mangled source that might
            # parse clean, hiding a constructor. An undecodable file must be
            # UNPROVEN, not quietly accepted.
            src = py.read_text(encoding="utf-8-sig", errors="strict")
            tree = ast.parse(src)
        except (OSError, SyntaxError, UnicodeDecodeError) as e:
            # Never swallow: an unparseable or undecodable file is an unproven file.
            unparseable.append(f"{rel} ({type(e).__name__})")
            continue
        fnd = _Finder()
        fnd.visit(tree)
        for ln in sorted(set(fnd.hits)):
            offenders.append(f"{rel}:{ln}")

    _assert(
        not offenders,
        "T6  no aliased or direct create_engine in project source outside canonical module"
        + ("" if not offenders else f"  ({len(offenders)} found: {offenders[:8]})"),
    )
    # An unparseable file could hide a constructor. Coverage must be total.
    _assert(
        not unparseable,
        "T6b every project source file parsed (no unproven files)"
        + ("" if not unparseable else f"  ({unparseable[:4]})"),
    )


# =============================================================================
# Test 7 — postgres:// -> postgresql:// normalization preserved
# Lifted from db/schema.py:32 into the canonical point (spec §5.1.1).
# URL-level assertion only; no connection attempted.
# =============================================================================
def test_7_scheme_normalization():
    """Tested through the authorized factory. The spec requires normalization
    BEHAVIOR; it does not require the module to expose normalize_url() publicly.
    Asserting on a helper function would dictate an interface the spec never
    authorized. Construction does not connect, so no server is needed."""
    eng = _get_engine("postgres://u:p@h:5432/d")
    _assert(
        eng.url.drivername.startswith("postgresql"),
        f"T7  postgres:// normalized to postgresql:// (drivername={eng.url.drivername!r})",
    )

    sqlite_eng = _get_engine(SQLITE_URL)
    _assert(
        sqlite_eng.url.drivername.startswith("sqlite"),
        f"T7b sqlite:// URL passes through unmodified (drivername={sqlite_eng.url.drivername!r})",
    )


# =============================================================================
def main():
    print(f"\nFR-VAL10-af / af-1 — Engine Control Surface control tests [RED]  {REV} ({REV_DATE})")
    print(f"  spec             : {SPEC_REV}")
    print(f"  baseline         : {BASELINE[:12]}")
    print(f"  canonical module : {CANONICAL_MODULE}.{CANONICAL_FACTORY}")
    print(f"  sqlite url       : {SQLITE_URL}")
    print(f"  postgres url     : {'set (T4c live confirm on)' if PG_URL else 'not set (T4/T4b still run)'}")
    print()

    for fn in (
        test_1_pragma_returns_one,
        test_2_dangling_fk_rejected,
        test_3_hook_independent_of_import_order,
        test_4_postgres_no_sqlite_hook,
        test_5_dialect_neutral_options_survive,
        test_5a_other_dialect_option_excluded,
        test_5b_unknown_option_rejected,
        test_6_bypass_guard,
        test_7_scheme_normalization,
    ):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            _assert(False, f"{fn.__name__} raised {type(e).__name__}: {e}")

    print(f"\n  {_PASSES} passed, {len(_FAILURES)} failed")
    if _FAILURES:
        print("\n  FAILURES:")
        for f in _FAILURES:
            print(f"    - {f}")
        print(
            "\n  RED is expected until af-1 lands. af-1 control-surface green "
            "= all of the above passing.\n"
            "  NOTE: af-1 green does NOT mean FR-VAL10-af satisfied. af-2 "
            "(full suite under FK enforcement) is a separate gate.\n"
        )
        sys.exit(1)

    print(f"\n  af-1 CONTROL-SURFACE GREEN.  (tests {REV}, spec {SPEC_REV})")
    print("  FR-VAL10-af is NOT yet satisfied — af-2 behavioral triage remains.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()