"""
db/engine_factory.py — FR-VAL10-af / af-1 canonical engine control surface.

Single governed construction point for every SQLAlchemy Engine in the project.
It owns URL normalization, dialect resolution, the dialect-scoped connect-arg
policy (spec Section 5.5), and — for SQLite only — a pool ``connect`` hook that
turns on foreign-key enforcement (``PRAGMA foreign_keys=ON``).

Spec: FR_VAL10_AF_ENGINE_CONTROL_SURFACE_MODULE_SPEC_Rev5.md

This module MUST NOT import ``db.schema``. ``db.schema`` imports this module,
never the reverse, so the governed point sits below the model layer and no
circular import can form.

``_sqlite_foreign_keys_on_connect`` is a module-owned PRIVATE symbol. It exists
solely so the af-1 control tests can assert exact-identity registration via
``event.contains(engine.pool, "connect", _sqlite_foreign_keys_on_connect)``. It
is NOT application API — no application code should import or call it, and it
carries no compatibility guarantee beyond the control tests.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url

# ── Recognized DBAPI connect_args, by dialect (spec Section 5.5) ──────────────
# Each connect_arg is classified as: kept (recognized for the resolved dialect),
# excluded (recognized for another dialect — dropped silently), or rejected
# (recognized for no supported dialect — raises at construction).

# pysqlite / sqlite3.connect(...) keyword arguments.
_SQLITE_CONNECT_ARGS = frozenset({
    "timeout", "detect_types", "isolation_level", "check_same_thread",
    "factory", "cached_statements", "uri",
})

# libpq / psycopg2.connect(...) keyword arguments — the recognized set we
# deliberately EXCLUDE under a non-PostgreSQL dialect rather than forward.
_POSTGRES_CONNECT_ARGS = frozenset({
    "connect_timeout", "sslmode", "sslcert", "sslkey", "sslrootcert", "sslcrl",
    "sslpassword", "application_name", "fallback_application_name", "options",
    "host", "hostaddr", "port", "dbname", "user", "password", "passfile",
    "service", "channel_binding", "gssencmode", "target_session_attrs",
    "client_encoding", "keepalives", "keepalives_idle", "keepalives_interval",
    "keepalives_count", "tcp_user_timeout", "requiressl",
})

_KNOWN_BY_DIALECT = {
    "sqlite": _SQLITE_CONNECT_ARGS,
    "postgresql": _POSTGRES_CONNECT_ARGS,
}


def _normalize_url(url: str) -> str:
    """Rewrite the legacy ``postgres://`` scheme to ``postgresql://``
    (spec Section 5.1.1) — the single point of truth, lifted from
    ``db/schema.py:32``. Idempotent: a URL that is already ``postgresql://``
    (or any other scheme) is returned unchanged. SQLAlchemy 2.0's ``make_url``
    does NOT normalize this itself, so it must happen before dialect
    resolution."""
    if isinstance(url, str) and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def _resolve_dialect(url: str) -> str:
    """Backend name of the NORMALIZED url (``'sqlite'`` | ``'postgresql'`` | …).
    Resolved from the URL alone — never from caller intent or the presence of a
    dialect-specific connect_arg (spec Section 5.1.2). Does not import the DBAPI
    driver."""
    return make_url(url).get_backend_name()


def _apply_option_policy(dialect: str, connect_args: dict) -> dict:
    """Dialect-scoped connect_args policy (spec Section 5.5). Returns the
    connect_args to actually forward to ``create_engine``.

      * recognized for the resolved dialect  -> kept
      * recognized for another dialect        -> EXCLUDED (dropped silently)
      * recognized for no supported dialect   -> REJECTED (raises here)

    Excluded and rejected are distinct dispositions: a legible other-dialect
    option (e.g. ``connect_timeout`` under SQLite) is dropped without noise; an
    unrecognized option raises at construction rather than being silently
    discarded or deferred to connect time.
    """
    if not connect_args:
        return {}

    own = _KNOWN_BY_DIALECT.get(dialect)
    if own is None:
        # Dialect outside af-1's two-dialect policy: forward unchanged rather
        # than guess. No such site exists among the eight; defensive only.
        return dict(connect_args)

    other_dialect_keys = frozenset().union(
        *(keys for name, keys in _KNOWN_BY_DIALECT.items() if name != dialect)
    )

    kept: dict = {}
    unknown: list = []
    for key, value in connect_args.items():
        if key in own:
            kept[key] = value
        elif key in other_dialect_keys:
            continue  # excluded silently — recognized for another dialect
        else:
            unknown.append(key)

    if unknown:
        raise ValueError(
            f"get_engine: connect_args {sorted(unknown)!r} are not recognized "
            f"for the resolved {dialect!r} dialect, nor for any other supported "
            f"dialect. Refusing to construct — the canonical option policy "
            f"(Section 5.5) rejects unknown options at construction rather than "
            f"forwarding them to connect time."
        )
    return kept


def _sqlite_foreign_keys_on_connect(dbapi_connection, connection_record):
    """Pool ``connect`` hook: enable SQLite foreign-key enforcement on every new
    DBAPI connection (``PRAGMA foreign_keys=ON``). Registered by ``get_engine``
    ONLY on SQLite engines, and only on the engine's own pool — never on a
    PostgreSQL pool.

    Module-owned private symbol — see the module docstring. Not application API.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def get_engine(url: str, *, connect_args: dict | None = None, **kwargs) -> Engine:
    """Canonical Engine factory — the one governed ``create_engine`` call site.

    Normalizes the URL, resolves the dialect from it, applies the dialect-scoped
    connect_args policy (Section 5.5), constructs the Engine, and — for SQLite
    only — registers the foreign-key connect hook on the engine's pool.

    Dialect-neutral engine options (``echo``, ``future``, ``pool_*``, …) pass
    through via ``**kwargs`` unchanged. ``connect_args`` are filtered per
    dialect: other-dialect options excluded, unknown options rejected at
    construction.
    """
    normalized = _normalize_url(url)
    dialect = _resolve_dialect(normalized)
    filtered_connect_args = _apply_option_policy(dialect, dict(connect_args or {}))

    # ── PROD-HARDEN-1 · POSTGRESQL POOL RESILIENCE ───────────────────────────
    #
    # A pooled connection outlives the network path it was opened over. A
    # database restart, a platform failover or an idle-timeout on a proxy all
    # leave a socket in the pool that looks fine and fails on first use — which
    # in production is a request, or worse, a settlement job.
    #
    #   pool_pre_ping   one round-trip before a checked-out connection is used;
    #                   a dead one is discarded and replaced transparently. This
    #                   is the setting that turns "the database restarted" from
    #                   an incident into a pause.
    #
    #   pool_recycle    connections older than this are retired. 300s sits well
    #                   under the idle timeouts platform proxies typically
    #                   impose, so a connection is replaced on our schedule
    #                   rather than dropped on theirs.
    #
    # NOT A RETRY LOOP, DELIBERATELY. §39 warns against retrying around
    # non-idempotent writes and it is right: pre-ping revalidates BEFORE the
    # transaction begins, so a statement that has already run is never
    # re-issued. A failed transaction still fails, and the job's own durable
    # idempotency decides what happens next.
    #
    # DEFAULTS ONLY — an explicit caller value always wins, which is what keeps
    # the af-1 control tests' constructed engines exactly as they ask for them.
    if dialect == "postgresql":
        kwargs.setdefault("pool_pre_ping", True)
        kwargs.setdefault("pool_recycle", 300)

    engine = create_engine(normalized, connect_args=filtered_connect_args, **kwargs)

    if dialect == "sqlite":
        # Attach to the engine's POOL (spec Section 5.1: "attach to the pool and
        # test against the pool"). 'connect' is a pool event; registering it on
        # engine.pool makes event.contains(engine.pool, "connect",
        # _sqlite_foreign_keys_on_connect) True by exact identity — while the
        # same symbol is never registered on any PostgreSQL pool. On SQLAlchemy
        # 2.0 an engine-level event.listen does NOT satisfy that pool-scoped
        # containment check, so attachment is pool-scoped and deterministic.
        event.listen(engine.pool, "connect", _sqlite_foreign_keys_on_connect)

    return engine
