"""
test_support_rev42_fixture.py — the authoritative Rev 4.2 accounting fixture.

INFRASTRUCTURE, NOT A TEST. No assertions live here; `test_s8_p4b1_fixture.py`
makes them and `test_support_app_server.py` seeds through this module.

WHY IT EXISTS AS ITS OWN MODULE. The app-server harness seeds inside a
subprocess, because `db.schema` binds its engine from DATABASE_URL at import
time. A fixture this size does not belong inline in a script string where no
editor can check it, so the subprocess imports this instead.

THE EXPECTATION MAP AT THE BOTTOM IS THE POINT OF THE PACKAGE. It records, cell
by cell, which Rev 4.2 figure has an authoritative backend source, what the
seeded season produces for it, and whether the browser expectation may stay
exact. P4B-2 changes assertions only where this map says REVISE EXACT or
UNRESOLVED.
"""

from __future__ import annotations

from economy.economy_events import min_account


# ── The authoritative Rev 4.2 accounting fixture (S8-P4B-1) ──────────────────
#
# WHAT THIS SEEDS, AND WHY IT IS NOT A SET OF NUMBERS. Sprint 7 certified the
# Rev 4.2 Ledger against illustrative JavaScript constants. P4 binds that tab to
# `economy/current_settle.py`, so those cells must come from POSTED LEDGER
# STATE — which means the fixture has to be a coherent season, not a table of
# desired balances. Every posting below is a thing that happened to this GM.
#
# THE SEASON THIS DESCRIBES, for one team over five weeks:
#
#   · the league activated its season allocation: $140 into the weekly-minimum
#     reserve and $80 into the championship reserve, advanced as $220;
#   · a $40 Top-Off was requested and approved;
#   · weeks 1-5 each released $10 of weekly minimum from the reserve;
#   · in week 1 the GM spent $2 and let $8 expire unused;
#   · weeks 2-4's $30 went into a wager that settled in the GM's favour,
#     returning $43 against a $32 stake;
#   · week 5's $10 is still live and unspent;
#   · a $28 wager is open right now and its stake sits in escrow.
#
# GOVERNING DOORS ARE USED VERBATIM. `season_allocation`,
# `approved_bab_topoff`, `weekly_minimum_release`, `weekly_minimum_expiry`,
# `wager_placed` and `wager_settled` are the same doors the production services
# post under, and `current_settle` reads two of them BY DOOR — so a fixture that
# invented a door name would produce a position the read model could not see.
#
# WHERE A SERVICE IS CALLED VS WHERE THE POSTING IS MADE DIRECTLY. The weekly
# minimum release and expiry go through the real services
# (`economy/weekly_minimum.py`), which take no row locks and run on SQLite.
# Season allocation and Top-Off approval do NOT: both take `FOR UPDATE` /
# `FOR NO KEY UPDATE` locks that SQLite cannot parse, which is why every suite
# exercising them is `_pg`. For those two the posting is made directly under
# the same door, in the same shape the service emits — verified against
# `economy/season_allocation.py` and `economy/top_off.py`. The lock behaviour
# they carry is a concurrency property, and concurrency is P5's.
#
# HELD IS ZERO, AND THAT IS THE AUTHORITATIVE ANSWER. The Rev 4.2 prototype
# showed $25 held against open offers. P4B-0 established that the reachable
# application path (`beefs/beef_engine.py`) uses a soft reservation and posts
# no challenge escrow, so no `ChallengeFundingLeg` row exists and
# `held_open_challenges_cents` is structurally 0. Fabricating those rows here
# would manufacture state no live path writes. See EXPECTATION_MAP.
#
# NOTHING BELOW INVENTS SEASON WINNINGS. The +$24 in the prototype's
# "Awards / Adj." cell has no authoritative accounting source (P3), and no door
# is opened here to create one. The GM's settled wager gain is ordinary wallet
# balance, which is where the accounting puts it.

#: Exact-cent expectations for the seeded position. These are the values
#: `economy/current_settle.py` must produce, and the P4B-1 suite asserts every
#: one of them against a real backend call.
FIXTURE_EXPECTED = {
    "wallet_cents":               5_500,
    "weekly_min_live_cents":      1_000,
    "available_cents":            6_500,
    "min_reserve_cents":          9_000,
    "expired_min_cents":            800,
    "in_play_cents":              2_800,
    "held_open_challenges_cents":     0,
    "receivable_cents":               0,
    "assets_cents":              19_100,
    "season_advance_cents":      22_000,
    "topoff_issued_cents":        4_000,
    "obligations_cents":         26_000,
    "current_settle_cents":      -6_900,
}

#: The season-opening split, fixed at activation and read from the Economy
#: Stop — NOT from the live `min_reserve` balance, which has fallen to $90 as
#: the weekly minimum released. Binding the split to the live balance was a
#: real defect caught in P4A.
FIXTURE_OPENING_SPLIT = {
    "min_reserve_leg_cents": 14_000,   # Weekly Minimum Reserve
    "reserve_leg_cents":      8_000,   # Championship Reserve
}


def _seed_accounting_fixture(db, league, gm_team, opponent_team) -> None:
    """Post the season described above. Does not commit — the caller owns that."""
    from economy.current_settle import DOOR_APPROVED_TOPOFF, DOOR_SEASON_ALLOCATION
    from economy.economy_events import min_reserve_account, wallet_account
    from economy.weekly_minimum import expire_weekly_minimum, release_weekly_minimum
    from db.schema import Bet, Matchup, Wallet
    from ledger.ledger import post as ledger_post

    gm, opp = gm_team.id, opponent_team.id

    def post(entries, door):
        """Post and FLUSH.

        The ledger's funded-balance guard reads through the session, and a
        posting that has only been `add()`ed is not yet visible to the next
        posting's check — so a two-step money movement (fund, then settle)
        fails on the second step with a phantom shortfall. Flushing after each
        posting is what makes the sequence below behave the way the production
        services do, where each posting owns its own transaction.
        """
        ledger_post(entries, door=door, session=db)
        db.flush()


    # 1 — Season allocation, both teams. min_reserve + reserve legs under the
    #     allocation door ARE the season advance: `season_advance_cents` sums
    #     exactly these two accounts under exactly this door.
    for team_id in (gm, opp):
        post([
            (min_reserve_account(team_id), FIXTURE_OPENING_SPLIT["min_reserve_leg_cents"]),
            (f"reserve:{team_id}",         FIXTURE_OPENING_SPLIT["reserve_leg_cents"]),
            ("world", -(FIXTURE_OPENING_SPLIT["min_reserve_leg_cents"]
                        + FIXTURE_OPENING_SPLIT["reserve_leg_cents"])),
        ], DOOR_SEASON_ALLOCATION)

    # 2 — An approved Top-Off for the GM ($40), and a smaller one for the
    #     opponent so they can fund their side of the wager below. Only the
    #     approved-issuance door counts as an obligation, which is why a
    #     pending request would move nothing.
    post([(wallet_account(gm), 4_000), ("world", -4_000)],
                DOOR_APPROVED_TOPOFF)
    post([(wallet_account(opp), 1_100), ("world", -1_100)],
                DOOR_APPROVED_TOPOFF)

    # 3 — Weeks 1-5 release the weekly minimum, through the REAL service.
    #     $50 leaves the reserve, so it lands at $140 - $50 = $90.
    for week in range(1, 6):
        release_weekly_minimum(db, league_id=league.id, team_id=gm, week=week)
    db.flush()

    # 4 — Week 1: $2 spent on the wager below, $8 left to expire. The expiry
    #     service sweeps whatever remains, so the spend has to happen first.
    #     Weeks 2-4 are spent in full.
    post([
        (min_account(gm, 1),  -200),
        (min_account(gm, 2), -1_000),
        (min_account(gm, 3), -1_000),
        (min_account(gm, 4), -1_000),
        ("escrow:SETTLED_A",  3_200),
    ], "wager_placed")

    expire_weekly_minimum(db, league_id=league.id, team_id=gm, week=1)
    db.flush()

    # 5 — The opponent funds their side, the wager settles for the GM, and the
    #     whole pot returns to the GM's wallet. The escrow account nets to zero,
    #     so it is settled and `in_play_cents` correctly ignores it.
    post([(wallet_account(opp), -1_100), ("escrow:SETTLED_A", 1_100)],
                "wager_placed")
    post([("escrow:SETTLED_A", -4_300), (wallet_account(gm), 4_300)],
                "wager_settled")

    # 6 — The open wager. Its escrow is what `in_play_cents` attributes, and it
    #     attributes it through the OWNING BET: the account must be
    #     `escrow:{bet_id}` and that bet's wallet must belong to the GM, or the
    #     read model raises UNATTRIBUTABLE_ESCROW rather than guessing.
    wallet = Wallet(team_id=gm, balance=0.0)
    db.add(wallet)
    db.flush()

    matchup = Matchup(league_id=league.id, week=5, home_team_id=gm,
                      away_team_id=opp, home_score=0.0, away_score=0.0)
    db.add(matchup)
    db.flush()

    open_bet = Bet(matchup_id=matchup.id, wallet_id=wallet.id,
                   bet_type="straight", amount=28.0, odds=1.9, status="pending")
    db.add(open_bet)
    db.flush()

    post([(wallet_account(gm), -2_800),
                 (f"escrow:{open_bet.id}", 2_800)],
                "wager_placed")

    # The settled escrow was parked under a non-numeric name so it could never
    # be mistaken for a bet escrow; now that it nets to zero it is invisible to
    # the scan either way. Left as-is deliberately: renaming it would imply a
    # bet row that never existed.


# ── The Rev 4.2 expectation map (S8-P4B-1) ───────────────────────────────────
#
# Rev 4.2 cell → authoritative backend source → seeded expected value → status.
#
#   KEEP EXACT      a backend source exists and the existing display
#                   expectation is already what it produces;
#   REVISE EXACT    a backend source exists, but the illustrative number was
#                   not authoritative — replace it with the exact seeded value;
#   UNRESOLVED      no authoritative source exists; the UI must not manufacture
#                   a number, and the approved unresolved treatment applies.
#
# NOTHING HERE IS LOOSENED. Every sourced cell keeps an exact expectation; only
# two rows change status, and both changed for reasons proven in P3 and P4B-0
# rather than because a number was inconvenient.

EXPECTATION_MAP = (
    # (cell, source, illustrative, seeded, status, note)
    ("Wallet", "wallet:{team} balance", 5_500, 5_500, "KEEP EXACT",
     "Top-Off $40 + settled return $43 - open stake $28."),

    ("Weekly Min Left", "min:{team}:{week} live balance", 1_000, 1_000,
     "KEEP EXACT", "Week 5 released and unspent."),

    ("Available", "wallet + live weekly minimum", 6_500, 6_500, "KEEP EXACT",
     "Grouping of two authoritative terms."),

    ("In Play", "in_play_cents — escrow:{bet_id}, attributed via Bet.wallet",
     2_800, 2_800, "KEEP EXACT",
     "One open wager. Equals the whole of in_play because Held is 0."),

    ("Held", "held_open_challenges_cents — ChallengeFundingLeg, open states",
     2_500, 0, "REVISE EXACT",
     "P4B-0: the reachable path (beefs/beef_engine.py) uses a soft "
     "reservation and posts no challenge escrow, so no ChallengeFundingLeg "
     "exists and this is structurally 0. Fabricating rows would manufacture "
     "state no live path writes. P4C owns Spec-2 activation, after which this "
     "becomes a non-zero SUBSET of In Play."),

    ("Weekly Reserve Not Released", "min_reserve:{team} balance", 9_000, 9_000,
     "KEEP EXACT", "$140 opening less $50 released over five weeks."),

    ("Weekly Min Out of Circulation", "expired_min:{team} balance", 800, 800,
     "KEEP EXACT", "Week 1's unspent $8, swept by the real expiry service."),

    ("Skunk Fees", "-receivable:{team} balance", 0, 0, "KEEP EXACT",
     "No assessment seeded; the sign convention is still exercised by P3."),

    ("Season Opening", "season_advance_cents — allocation door, both legs",
     22_000, 22_000, "KEEP EXACT", "Posted advance, not a config lookup."),

    ("Weekly Minimum Reserve opening leg", "Economy Stop min_reserve_cents",
     14_000, 14_000, "KEEP EXACT",
     "From the STOP, not the live $90 balance. Reading the live balance was a "
     "real P4A defect: it falls every week while the advance it describes "
     "does not move."),

    ("Championship Reserve", "Economy Stop reserve_cents", 8_000, 8_000,
     "KEEP EXACT", "Same reconciliation rule as the leg above."),

    ("Added Stakes / Top-Off", "topoff_issued_cents — approved issuance door",
     4_000, 4_000, "KEEP EXACT",
     "Approved issuance only; a pending or rejected request posts nothing."),

    ("Awards / Adj.", "no authoritative source", 3_200, None, "UNRESOLVED",
     "The illustrative +$32 is expired_min $8 + skunk $0 + seasonWinnings $24. "
     "P3 proved seasonWinnings has no source: award credits sit inside wallet "
     "and no posted door attributes them. Showing $8 would be arithmetically "
     "right but would present a partial figure under a total's label, and "
     "showing $0 would falsely assert an authoritative zero. The approved "
     "unresolved treatment applies to the winnings component."),

    ("Current Settle", "current_settle_cents — assets - obligations",
     -4_500, -6_900, "REVISE EXACT",
     "Moves by exactly the unsourced +$24 that is no longer invented. This is "
     "the authoritative figure for the seeded position and P4B-2 must assert "
     "it exactly."),
)

#: Rev 4.2 cells that stay illustrative in P4B because they belong to a
#: DIFFERENT domain — none of them is accounting, and none is sourced by the
#: read models P3 built. P4C owns them; P4B must not revise them.
DEFERRED_TO_P4C = (
    ("Bet Record (14-7)", "proposal/wager history — Action domain"),
    ("Net Winnings / rank", "settled wager activity — Action/Week domain"),
    ("Net Versus / Net Pools", "explanatory activity totals; P3 proved no "
                               "posted door groups them"),
    ("Season awards / championships", "award lifecycle, not accounting state"),
)
