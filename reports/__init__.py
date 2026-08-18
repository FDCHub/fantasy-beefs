"""Report package registration.

RC2 championship snapshot tables are declared on db.schema.Base from the report
module because they are a read-model lifecycle artifact, not mutable game state.
Importing the module here registers those tables before api/main.py's startup
`Base.metadata.create_all()` runs on a fresh database.

Existing production databases receive the same tables through the explicit
`0003_rc2_championship_snapshot` migration; this import is only the fresh-schema
half of that two-path contract.
"""

# Imported for SQLAlchemy model registration side effects. Keep the explicit
# alias private so `from reports import *` does not accidentally publish a new
# application API.
from reports import championship_read_model as _championship_read_model  # noqa: F401,E402
