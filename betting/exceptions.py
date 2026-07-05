"""
Typed exceptions for the betting/wallet money path.

Both subclass ValueError deliberately — any existing `except ValueError`
handler anywhere in the codebase keeps catching these without modification.
That backward-compatibility guarantee is the one fact this whole fix depends on.
"""


class NotFoundError(ValueError):
    """Raised when a referenced entity (matchup, wallet) does not exist."""


class BetValidationError(ValueError):
    """Raised when a bet request is structurally or numerically invalid."""


assert issubclass(NotFoundError, ValueError)
assert issubclass(BetValidationError, ValueError)
