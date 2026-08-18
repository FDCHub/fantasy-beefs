"""Economy package model registration.

RC2's independent FantasyStakes Championship contribution/allocation tables are
additive SQLAlchemy models. Importing them here registers the tables on
`db.schema.Base` before a fresh database runs `Base.metadata.create_all()`.
Existing databases receive the same schema through the explicit RC2 migration.
"""

from economy import fantasystakes_championship_economy as _fs_championship_economy  # noqa: F401,E402
