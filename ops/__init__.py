"""
ops — production operability.

WHAT LIVES HERE. The things an operator needs and a GM never sees: which
release is running, whether this process may serve traffic, whether writes are
permitted, and whether the database still satisfies the invariants the product
depends on.

WHAT DOES NOT LIVE HERE. Any product rule. Nothing in this package decides an
economic outcome, prices a market, settles a wager or interprets a provider. It
observes, it validates configuration, and — in exactly one case, the emergency
write-disable — it refuses. It never repairs.
"""
