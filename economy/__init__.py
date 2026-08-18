"""Economy package.

RC2 model registration is explicit in ``api.main_rc2``. Package import must stay
side-effect free so report modules can depend on economy helpers without creating
an economy <-> reports initialization cycle.
"""
