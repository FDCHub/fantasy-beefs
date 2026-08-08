"""Shared FastAPI dependencies — keeps get_db in one place to avoid circular imports."""

from db.schema import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
