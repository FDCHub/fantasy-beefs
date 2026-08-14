"""Season-structure domain — WP1A.

PROVIDER-NEUTRAL, AND MECHANICALLY SO. Nothing in this package may import
`betting`, `economy`, `ledger`, `beefs`, `wallet` or `db`. It consumes the
normalized DTOs in `providers/base.py` and returns domain answers; it moves no
money, reads no session and knows no provider's field names.

WHY A NEW PACKAGE RATHER THAN A MODULE IN `betting/`. The one postseason
primitive that existed before WP1A — `betting/pool_season_boundary.py` — lives
in the Pool package for historical reasons, and it answers a Pool question:
which rotation phase is this week in. The championship track is not a Pool
concept. It is consumed by Pool eligibility, by Versus eligibility, by the
Championship Pot basis, by Demo Mode and by the UI, and putting it under
`betting/` would have made four of those five importers reach into Pool code for
a fact that has nothing to do with Pools.

The import guard is asserted, not just documented: test_wp1a_championship_track
walks this package's AST and fails on any forbidden import.
"""
