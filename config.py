# Single source of truth for the current live season.
# TEMPORARY: pinned to 2025 because that's the only season with seeded
# projection data in production right now. Bump to 2026 once real 2026
# projections are seeded — must happen before Week 1 kickoff.
CURRENT_SEASON = 2025
LOCK_SEASON = 2026  # NFL schedule season for kickoff-lock checks; independent of CURRENT_SEASON (projection data year)

# Season stamped on SeasonAllocation rows and used by the allocation gate.
# Deliberately separate from CURRENT_SEASON, which is the projection-data
# year and remains pinned to 2025 until 2026 projections are seeded.
ALLOCATION_SEASON = 2026
