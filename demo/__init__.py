"""The FantasyStakes showcase demo — a deterministic, resettable sample league.

    python -m demo.seed      build (or rebuild) the showcase league
    python -m demo.reset     retire the showcase league and build a fresh one
    python -m demo.seed --status   report what exists, change nothing

WHAT THIS IS FOR. Showing the product to a prospective GM, a commissioner, a
Yahoo reviewer or a partner, with the same league every time. It is not a second
product and not a mockup: the standings, the Championship Score, the payouts and
the Ledger are produced by the SAME modules a real league uses.

── WHY THIS SITS BESIDE `providers/demo`, NOT INSIDE IT ─────────────────────

`providers/demo/scenario.py` is a CERTIFIED LIFECYCLE FIXTURE: six teams, six
weeks, a four-team bracket, built to exercise week open/finalize/postseason and
depended on by `test_wp2_demo_lifecycle_pg.py` and `test_wp2_provider_recovery_pg.py`.
It is exactly the wrong shape for a showcase — nobody is impressed by a six-team
league in week 2 — and changing it would break certified suites for a
presentation reason. So the showcase is its own fixture and touches none of it.

WHAT IT REUSES, WHICH IS EVERYTHING THAT MATTERS:

  · the Demo PROVIDER BINDING — `provider="demo"` plus the demo league-key
    prefix — so `api.demo_routes.is_demo_league` recognises it and every
    demo-only action is already scoped to it
  · the real ledger (`ledger.ledger.post`), including its door rules
  · the real economy: `set_draft`, `freeze_economy_config`,
    `activate_season_allocation`
  · the real standings, Championship Score and Grand Champion read models

THERE IS NO DEMO ECONOMY, NO DEMO LEDGER AND NO DEMO CHAMPIONSHIP ENGINE. If a
figure appears on a demo screen, the code that produced it is the code that
produces it in production.

── NO YAHOO, AT ALL ─────────────────────────────────────────────────────────

Nothing here calls Yahoo, holds a Yahoo token, or copies a Yahoo payload. Team
names, GM names, player names and every result are invented. The provider keys
are demo keys in a demo namespace. A demo league cannot be mistaken for a
connected one: its provider binding says `demo`, and the surfaces say so too.
"""
from __future__ import annotations

__all__ = ["showcase"]
