"""The Demo provider — a runtime FantasyStakes provider, not a test fixture.

WP2 §10. Demo Mode is a launch FEATURE: a user must be able to experience the
whole product without connecting a Yahoo league, and what they experience must
be the product — the same Pool engine, the same Versus engine, the same Ledger,
the same Weekly Minimum, the same Skunk, the same postseason determination, the
same Championship podium, the same season close.

SO THIS PACKAGE PRODUCES FACTS AND NOTHING ELSE. It emits the same normalized
`providers.base` DTOs a Yahoo refresh emits, and every cent that moves as a
consequence moves through the certified engines afterwards. It imports nothing
from `ledger/` or `economy/` and it never posts — C-19 proves both, exactly as
C-15 proves them for Yahoo.

WHAT MAKES IT A PROVIDER RATHER THAN A SEED SCRIPT. A seed writes rows. This
answers questions: what is this league, who are its teams, what happened in
week N, which of those games were championship games. Those answers travel
through `providers/persist.py`, `providers/week_stat_source.py` and
`providers/postseason_bracket.py` — the same three seams Yahoo travels — so a
Demo league is not a parallel product, it is the product with a different feed.

IT IS DELIBERATELY NOT `test_support_*`. Those modules exist for suites and may
construct states production cannot reach; importing one from a shipping route
would invert the dependency and put fixture code on a money path.
"""

DEMO_PROVIDER = "demo"

#: Every Demo league key begins with this. It is the ONLY thing the Demo
#: postseason source claims on, so the source can never take over a Yahoo
#: league, and it is deliberately not Yahoo-shaped: a Yahoo key is
#: "{game_id}.l.{league_id}" with a numeric leading segment, and no Yahoo game
#: id is the string "demo".
DEMO_LEAGUE_KEY_PREFIX = "demo.l."
