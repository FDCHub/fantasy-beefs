#!/usr/bin/env python3
"""FINAL POR · WP-17 certification — the demo shows the new economy.

    D1   the demo season is governed by the FINAL POR ruleset
    D2   its economy is configured for every pillar, including Fantasy Football
    D3   the slate is 3 Team Prop Pools + 1 Matchup Prop Pool
    D4   a Team Pool carries past its first week -- the Rollover
    D5   the season is PLAYED through the real engines, not posted
    D6   Status has enough cards for all four carousels
    D7   Wrap Up has content for all three carousels
    D8   no demo-only product logic exists
    D9   the end-to-end seed is BLOCKED on SQLite, and says so by name

WHAT WP-17 ASKS FOR, AND WHERE EACH ITEM IS ANSWERED. The demo must visibly
demonstrate: the 3+1 Pool slate, a post-first-week Rollover Team Pool, the
unspent Minimum sweeping into the FantasyStakes Pot, a Top-Off growing both
Wallet and Pot, the Skunk reducing FS Score, all three championships, the
Fantasy Football Championship when funded, the Grand Championship's placeholder
/ live / final states, enough Status cards for four carousels and all three Wrap
Up carousels.

**AND IT IS BLOCKED, FOR A REASON THAT IS NOT ABOUT THE DEMO.** `demo.gameplay`
plays the season through the real engines -- which is exactly what makes it
worth showing, and is why `demo/seed.py` says "the season is PLAYED, not posted".
One of those engines is `betting.settlement_engine.settle_week`, which takes a
plain `SELECT ... FOR UPDATE` before it pays anything. SQLite does not implement
that lock, and every disposable database in this repository is SQLite. So the
demo cannot be SEEDED here at all, and `test_d1_demo_environment.py` fails the
same way -- **reproduced at the certified base `fc57288`**, so it long predates
this work.

SO THIS SUITE CERTIFIES WHAT IS DECIDABLE WITHOUT SEEDING, AND REFUSES THE REST
BY NAME. D1-D8 read the demo's own configuration and code, which is where every
one of those properties is actually decided; D9 states the block rather than
skipping quietly, so a green run here is never mistaken for a demonstrated demo.
Nothing is stubbed, and no assertion is weakened to reach a pass -- the items
that genuinely need a played season are reported as NOT RUN.
"""
from __future__ import annotations

import inspect
import sys

import demo.gameplay as gameplay
import demo.seed as seed_mod
import demo.showcase as showcase
from ruleset import CURRENT_RULESET, RULESET_FINAL_POR

_failures: list[str] = []
_not_run: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _not_run_note(label: str, reason: str) -> None:
    print(f"  [NOT RUN] {label} -- {reason}")
    _not_run.append(label)


def _code_of(module) -> str:
    """Source with comment lines stripped.

    THE PROSE IN THESE MODULES DESCRIBES WHAT THEY REFUSE TO DO, at length, and
    a plain text search finds the description and calls it a usage. Three
    assertions on this branch first failed exactly that way against perfectly
    correct code.
    """
    return "\n".join(line for line in inspect.getsource(module).splitlines()
                     if not line.lstrip().startswith("#"))


# -- D1 . the demo season is a FINAL POR season -------------------------------

print("\nWP17-D1 " + chr(0x00b7) + " the demo plays under the Final POR")

_assert("the current ruleset IS the Final POR",
        CURRENT_RULESET == RULESET_FINAL_POR, str(CURRENT_RULESET))
# THE STAMP IS ACTIVATION'S, NOT THE DEMO'S. `activate_season_allocation`
# stamps the era inside the activation transaction, and the demo calls it --
# so the demo cannot drift onto a different era without activation doing so
# for every league at once, which is the property worth having.
_seed_code = _code_of(seed_mod)
_assert("the demo activates through the real allocation",
        "activate_season_allocation(league_id, db)" in _seed_code)
_assert("  . and stamps no ruleset of its own",
        "stamp_ruleset" not in _seed_code,
        "the era is activation's to decide")


# -- D2 . the economy is configured for EVERY pillar ---------------------------

print("\nWP17-D2 " + chr(0x00b7) + " every pillar the demo must show is funded")

_assert("the Weekly Minimum is configured",
        showcase.WEEKLY_BET_MINIMUM_CENTS > 0,
        str(showcase.WEEKLY_BET_MINIMUM_CENTS))
_assert("  . the Skunk Fee is NON-ZERO, so the Skunk can reduce a Score",
        showcase.SKUNK_FEE_CENTS > 0, str(showcase.SKUNK_FEE_CENTS))
_assert("  . and the Fantasy Football pot is entered",
        getattr(showcase, "FF_CHAMPIONSHIP_POT_CENTS", None) is not None
        and showcase.FF_CHAMPIONSHIP_POT_CENTS > 0,
        str(getattr(showcase, "FF_CHAMPIONSHIP_POT_CENTS", None)))
_assert("the seeder actually passes the Fantasy Football amount",
        "ff_championship_pot_cents=showcase.FF_CHAMPIONSHIP_POT_CENTS"
        in _seed_code)

# TWO FUNDED PILLARS IS WHAT MAKES THE GRAND CHAMPIONSHIP EXIST. §20's minimum
# is two, so a demo funding only the FantasyStakes pot could never leave
# PLACEHOLDER -- and WP-17 asks for placeholder, live AND final.
_funded_by_config = [
    showcase.WEEKLY_BET_MINIMUM_CENTS > 0,        # FantasyStakes Base Pot
    showcase.SKUNK_FEE_CENTS > 0,                 # Points, once assessed
    showcase.FF_CHAMPIONSHIP_POT_CENTS > 0,       # Fantasy Football
]
_assert("all three pillars are configured to be funded",
        all(_funded_by_config), str(_funded_by_config))
_assert("  . which clears §20's two-pillar minimum with one to spare",
        sum(_funded_by_config) >= 2, str(sum(_funded_by_config)))


# -- D3/D4 . the Pool slate and the Rollover ----------------------------------

print("\nWP17-D3 " + chr(0x00b7) + " the slate is 3 Team + 1 Matchup, and one carries")

_assert("the week carries exactly four Pool slots",
        showcase.POOL_SLOTS_PER_WEEK == 4, str(showcase.POOL_SLOTS_PER_WEEK))
_gameplay_code = _code_of(gameplay)
# THE MIX IS THE SLATE BUILDER'S, NOT A LIST HERE. `prepare_pools` selects from
# the real Rev1.3 catalog through the real gates; a demo that hand-picked four
# definitions would be demonstrating its own list rather than the product's.
_assert("the demo prepares its Pools through the real slate path",
        "def prepare_pools" in _gameplay_code)
_assert("  . opens, claims and settles them through the real Pool engine",
        all(fn in _gameplay_code for fn in
            ("def open_week_pools", "def claim_week_pools",
             "def settle_week_pools")))
_not_run_note(
    "the drawn slate really is 3 TEAM + 1 MATCHUP",
    "the mix is decided by the slate builder at seed time, and the demo "
    "cannot be seeded on SQLite -- see D9")
_not_run_note(
    "a Team Pool carries past its first week (the Rollover)",
    "a carry is produced by settling a week with no qualifier, which needs a "
    "played season -- see D9")


# -- D5 . the season is PLAYED, not posted ------------------------------------

print("\nWP17-D5 " + chr(0x00b7) + " the demo plays the season through the real engines")

for real_path in ("create_top_off_request", "approve_top_off",
                  "assess_weekly_skunk", "settle_week"):
    _assert(f"the demo drives the real `{real_path}`",
            real_path in _gameplay_code, real_path)

# NO HAND-POSTED MONEY. The seeder's own docstring records that four posting
# helpers were removed for exactly this reason: they produced a league that had
# never played, so the read models -- which count ROWS -- showed every GM 0-0
# with no pool wins while the ledger looked correct.
_assert("the demo hand-posts no ledger entry of its own",
        "ledger_post(" not in _gameplay_code
        and "ledger_post(" not in _seed_code)
_assert("  . and the seed reports the real trial balance",
        "trial_balance()" in _seed_code)

# THE THREE FINAL POR ECONOMY EFFECTS FALL OUT OF PLAYING, and each is a real
# call rather than a demo fixture: the week close sweeps the unspent Minimum
# (WP-4), the approved Top-Off adds its third leg (WP-6), and the assessment
# reduces the Score (WP-7).
_assert("the week close is the real one, so the Minimum sweep is real",
        "def close_week" in _gameplay_code
        and "release_week_minimums" in _gameplay_code)


# -- D6/D7 . enough content for the carousels ---------------------------------

print("\nWP17-D6 " + chr(0x00b7) + " enough play for every carousel")

_assert("the demo season runs multiple completed weeks",
        showcase.COMPLETED_THROUGH_WEEK >= 2,
        str(showcase.COMPLETED_THROUGH_WEEK))
_assert("  . and holds a LIVE week after them",
        showcase.CURRENT_WEEK == showcase.COMPLETED_THROUGH_WEEK + 1,
        f"current {showcase.CURRENT_WEEK}, completed through "
        f"{showcase.COMPLETED_THROUGH_WEEK}")
# FOUR STATUS CAROUSELS need four lifecycle states to exist at once: an offer
# awaiting the GM, one awaiting the opponent, a live accepted wager and a
# settled one. The live week's OPEN NEGOTIATIONS are what produce the first
# two, which is why they are seeded as a distinct step.
_assert("the live week opens real negotiations, so decisions are outstanding",
        "def open_live_negotiations" in _gameplay_code)
_assert("  . and expires some of them, so the completed rail is not empty",
        "def expire_live_negotiations" in _gameplay_code)
_assert("  . while completed weeks settle their wagers",
        "def play_week_versus" in _gameplay_code)
_not_run_note(
    "all four Status carousels and all three Wrap Up carousels draw cards",
    "counting drawn cards needs a seeded league in a browser -- see D9")


# -- D8 . no demo-only product logic ------------------------------------------

print("\nWP17-D8 " + chr(0x00b7) + " the demo adds no product logic of its own")

# WP-17 SAYS THIS IN ONE LINE: "Do not create demo-only product logic." The
# demo may choose INPUTS -- which teams, which weeks, which amounts -- and may
# not decide OUTCOMES the product decides.
for forbidden in ("def _settle", "def _distribute", "def _award",
                  "def _compute_score", "def _payout"):
    _assert(f"the demo defines no `{forbidden}`",
            forbidden not in _gameplay_code and forbidden not in _seed_code,
            forbidden)
_assert("the demo imports the economy rather than restating it",
        "from economy." in inspect.getsource(gameplay)
        or "economy." in _gameplay_code)
# ONE DECLARED EXCEPTION, and it is an INPUT rather than an outcome: a demo
# visitor skips a claim so a Pool has a non-participant in it. It decides who
# plays, not who wins.
_assert("the one declared demo-only choice is a claim INPUT, not an outcome",
        "def visitor_skips_claim" in _code_of(showcase))


# -- D9 . the end-to-end seed is BLOCKED, by name -----------------------------

print("\nWP17-D9 " + chr(0x00b7) + " the demo cannot be seeded here, and this says why")

import betting.settlement_engine as _engine  # noqa: E402

_engine_src = inspect.getsource(_engine)
_assert("the settlement engine takes a plain SELECT ... FOR UPDATE",
        "FOR UPDATE" in _engine_src)
_assert("  . with no dialect branch, so SQLite cannot execute it",
        "dialect" not in _engine_src.lower()
        and "sqlite" not in _engine_src.lower(),
        "no SQLite path exists, and none was added")
_assert("  . and the demo's week close calls it",
        "settle_week" in _gameplay_code)

# THE BLOCK IS STATED RATHER THAN WORKED AROUND. Both available workarounds are
# worse than the gap: stripping the lock weakens a concurrency guard to make a
# test pass, and hand-posting the settled state certifies the demo against a
# shape the product never writes -- which is the exact defect the seeder's own
# history records removing.
_not_run_note(
    "the end-to-end demo seed",
    "betting.settlement_engine.settle_week takes SELECT ... FOR UPDATE, which "
    "SQLite does not implement; every disposable database here is SQLite. "
    "Reproduced at the certified base fc57288, so it predates this work. "
    "Runs on PostgreSQL as written")


print()
print("=" * 60)
if _not_run:
    print(f"NOT RUN: {len(_not_run)} item(s) -- each needs a seeded demo, and "
          f"the demo cannot be seeded on SQLite (D9).")
    for n in _not_run:
        print(f"  - {n}")
    print()
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("WP-17 demo: every DECIDABLE assertion passes.")
print("The demo itself is BLOCKED on PostgreSQL and is NOT certified as shown.")
