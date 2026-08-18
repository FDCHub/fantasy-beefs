"""FantasyStakes 1.0 RC2 application entrypoint.

RC1's ``api.main`` remains untouched. RC2 registers only its additive SQLAlchemy
models before importing the certified RC1 application, then attaches the RC2
championship routes.

Run RC2 with:
    uvicorn api.main_rc2:app
"""
from __future__ import annotations

# Explicit model registration. Package __init__ modules are intentionally
# side-effect free so imports used by RC1 and RC2 cannot form package cycles.
from economy import fantasystakes_championship_allocation as _fs_allocation  # noqa: F401
from reports import championship_read_model as _fs_championship_read_model  # noqa: F401
from economy import fantasystakes_championship_settlement as _fs_settlement  # noqa: F401

from api.championship_routes import router as championship_router

# RC1 application construction, middleware, static UI and existing routes.
from api.main import app  # noqa: E402

# Additive RC2 surface. The underlying app object is otherwise unchanged.
app.include_router(championship_router)
