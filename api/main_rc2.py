"""FantasyStakes 1.0 RC2 application entrypoint.

RC1's `api.main` remains untouched. Import the RC2 championship router first so
its SQLAlchemy models are registered on Base.metadata before `api.main` performs
fresh-database create_all, then reuse the certified RC1 application and attach
only the additive RC2 route surface.

Run RC2 with:
    uvicorn api.main_rc2:app
"""
from __future__ import annotations

# Importing this module registers the additive RC2 economy/distribution models.
import economy  # noqa: F401
import reports  # noqa: F401
from api.championship_routes import router as championship_router

# RC1 application construction, middleware, static UI and existing routes.
from api.main import app  # noqa: E402

# Additive RC2 surface. The underlying app object is otherwise unchanged.
app.include_router(championship_router)
