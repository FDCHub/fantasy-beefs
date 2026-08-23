"""The showcase league's fixture — every value fixed, nothing generated at runtime.

DETERMINISM IS THE POINT. A demo that looks different on Tuesday is a demo
nobody trusts. Every name, pairing, score and stake below is a literal, so the
same seed produces byte-identical standings, Championship Scores and Ledger
totals on every machine and every run.

── THE LEAGUE, AND WHY IT LOOKS LIKE THIS ───────────────────────────────────

Twelve GMs, a fourteen-week regular season, and a demo that opens in WEEK 11.
Week 11 is chosen deliberately: ten completed weeks give the Ledger real
history and the standings real separation, while three weeks still to play keep
the Championship Chase genuinely undecided. A week-1 league has nothing to show;
a finished one has nothing at stake.

THE SEASON TELLS A STORY, because a table of plausible noise is not a demo:

  · Gravy Seal Team Six (t1) and Third and Long Island (t4) are the two form
    teams, separated by a single result
  · Pain Sanders (t7) started 1-5 and has won four straight — the comeback
  · Cleat Fleetwood Mac (t2) and Kittle Big Town (t3) are a genuine rivalry:
    they have met twice, split, and sit adjacent in the table
  · the mid-table is close enough that three GMs can still reach the podium
  · nobody's wallet is absurd, and nobody is at zero

NO REAL PEOPLE. Team names are invented wordplay; GM names are invented; the
fictional players are invented. No NFL club is used as a fantasy team name, no
franchise character is referenced, and nothing here is crude.
"""
from __future__ import annotations

import datetime as _dt

from dataclasses import dataclass

# ── league shape ─────────────────────────────────────────────────────────────

#: THE ALLOCATION SEASON, and it has to be exactly this.
#:
#: `activate_season_allocation` records its SeasonAllocation rows under
#: `config.ALLOCATION_SEASON`, while `activate_fantasystakes_championship_stage`
#: looks for a completed base allocation under the LEAGUE'S season. A showcase
#: on any other season can never satisfy the RC2 stage — it refuses with "base
#: Season-Opening Allocation is not complete for the league season", which is
#: exactly what a made-up far-future season produced.
#:
#: The demo is NOT isolated by season and never was: it is isolated by its
#: provider binding, which is the only thing `assert_demo_league` and
#: `api.demo_routes.is_demo_league` consult.
import config as _config  # noqa: E402

SEASON = _config.ALLOCATION_SEASON
TEAM_COUNT = 12
START_WEEK = 1
#: Fourteen regular-season weeks, so the Weekly Play Reserve is 14 x the weekly
#: minimum — the derived figure the product actually shows.
REGULAR_SEASON_WEEKS = 14
PLAYOFF_START_WEEK = 15
SEASON_FINAL_WEEK = 17

#: Where the demo opens. Weeks 1..10 are complete; week 11 is live.
CURRENT_WEEK = 11
COMPLETED_THROUGH_WEEK = 10

# ── UIRECON Wave 3B · THE ONE DEMO-ONLY CHANGE IN THIS WAVE ──────────────────
#
# WHAT IT FIXES. The showcase claims a Prediction for EVERY GM on EVERY drawn
# occurrence, including the live week — see `gameplay.claim_week_pools` and the
# re-claim loop in `reset._restore`. That is right for the eleven GMs the
# visitor is playing against: it fills the pot, gives settlement a field, and
# makes `entered` a real number. It is wrong for the visitor themselves, because
# it means every Prop Pool they open is already answered, and the product's
# first-time experience — read the question, choose, submit — is unreachable in
# the demo that exists to show it.
#
# WHAT IT CHANGES, AND NOTHING MORE. One GM is skipped on ONE live-week slot.
# Every other GM still claims that slot, the visitor still claims the other
# three, and no completed week is touched at all.
#
# WHY THAT IS ECONOMICALLY INERT. A claim is a blind Prediction, not a stake:
# entry is collected per GM per WEEK by `collect_weekly_entries` regardless of
# how many occurrences they claim, so skipping one claim moves no Credits, does
# not change any pot, and does not change what any GM paid. It changes the
# CENSUS of claimants on one occurrence, which is what settlement evaluates —
# and settlement is unchanged: eleven claims still resolve there.
#
#: The showcase team the Try Demo visitor is seated on. Mirrors
#: `demo.seed.DEMO_SEAT_ORDINAL`, which owns the seating itself; the two are
#: asserted equal by `test_uirecon_wave3.py` so this copy cannot drift.
VISITOR_ORDINAL = 7

#: The live-week Pool slot left unclaimed for the visitor. Slot 1 of 4 — the
#: first Prop Pool they meet, so the openable one is the one they open.
VISITOR_OPEN_PICK_SLOT = 1


def visitor_skips_claim(week: int, slot: int, ordinal: int) -> bool:
    """Whether the showcase leaves this (week, slot, GM) unclaimed.

    ONE PREDICATE, TWO CALLERS. `gameplay.claim_week_pools` applies it while
    seeding and `reset._restore` applies it again while restoring, and they have
    to agree exactly — a skip in one and not the other would either hand the
    visitor a fully-claimed slate on reset or leave a slot permanently empty. It
    is a function rather than a repeated `if` so there is one place to read the
    rule and one place to test it.

    IT IS SCOPED THREE WAYS AND ALL THREE MATTER. The live week, so no completed
    week is ever touched; one slot, so three of the four Prop Pools still show
    the already-picked state; one GM, so the other eleven still claim and the
    settlement census is unchanged in size but one.
    """
    return (week == CURRENT_WEEK
            and slot == VISITOR_OPEN_PICK_SLOT
            and ordinal == VISITOR_ORDINAL)


# ── THE LIVE WEEK'S OPEN NEGOTIATIONS — UIRECON Wave 5 ───────────────────────
#
# WHY THE SHOWCASE NEEDS THEM. The demo played every contest to acceptance, so
# the visitor's Status tab could only ever show LIVE and COMPLETED: two of its
# four rails were structurally unreachable, and a GM meeting the product for the
# first time could not see what "something needs your decision" even looks like.
# The four rails are the FantasyStakes lifecycle, and a demo that can only
# demonstrate the back half of it is not demonstrating the lifecycle.
#
# A NEGOTIATION IS NOT A WAGER YET, WHICH IS WHAT MAKES THIS SAFE. An offered
# challenge has no Bet rows, posts nothing under `wager_placed`, and settles
# nothing. Its Anchor escrow is funded MIN-FIRST, so it is drawn from the
# issuer's weekly minimum — an allowance that is swept at week close in any case
# — and never from a wallet. Measured against a pristine showcase, adding these
# two moves no wallet balance, no standing, no championship score and no Pool
# figure, and leaves the trial balance at zero. `test_uirecon_wave5.py` asserts
# each of those rather than trusting this paragraph.
#
# THE TWO DIRECTIONS ARE THE POINT. One is issued TO the visitor, so it is
# genuinely theirs to answer and lands on ACTION REQUIRED with working
# controls; one is issued BY the visitor, so it is genuinely not theirs to
# answer and lands on WAITING with none. Seeding only one direction would
# demonstrate a rail rather than the distinction between two.

@dataclass(frozen=True)
class OpenNegotiation:
    """One live-week challenge the showcase deliberately leaves unanswered."""

    #: The GM who issues, and therefore funds the Anchor escrow.
    issuer_ordinal: int
    #: The GM whose decision it is.
    recipient_ordinal: int
    #: One of `VERSUS_PER_WEEK_MARKETS`.
    market: str


#: The showcase's unanswered live-week challenges, in issue order.
#:
#: THE OPPONENTS ARE ORDINARY LEAGUE MEMBERS, chosen so neither collides with
#: the accepted live-week contest the visitor already has (`versus_card` pairs
#: ordinal 3 with the visitor in week 11). The two markets differ so the two
#: cards show a line and a moneyline rather than the same shape twice.
VISITOR_OPEN_NEGOTIATIONS: tuple = (
    # Blitz and Pieces asks the visitor for a Spread Matchup — ACTION REQUIRED.
    OpenNegotiation(8, VISITOR_ORDINAL, "spread"),
    # The visitor asks Victorious Secret for a Moneyline Matchup — WAITING.
    OpenNegotiation(VISITOR_ORDINAL, 6, "straight"),
)


def is_open_negotiation(week: int, issuer_ordinal: int,
                        recipient_ordinal: int) -> bool:
    """Whether this pairing is one the showcase leaves open.

    ONE PREDICATE, TWO CALLERS — the same discipline `visitor_skips_claim`
    keeps. `gameplay.open_live_negotiations` issues by it and
    `reset.restore_in_place` reconciles by it, so a visitor who answers one of
    these is returned to the state the seeder wrote rather than to a state one
    of the two modules happened to believe in.
    """
    return week == CURRENT_WEEK and any(
        spec.issuer_ordinal == issuer_ordinal
        and spec.recipient_ordinal == recipient_ordinal
        for spec in VISITOR_OPEN_NEGOTIATIONS)

#: The league's own economy, in exact cents.
#:
#: WHY 1000 AND NOT ANYTHING ELSE. `activate_season_allocation` resolves its
#: terms from the certified allocation config, which issues
#: `min_reserve = 14000` per team — 14 weeks of a 1000 weekly minimum. The
#: demo's weekly minimum therefore HAS to be 1000, or the reserve the ledger
#: actually funded and the reserve the surfaces describe disagree. A draft that
#: used 2000 looked fine until the season run-in tried to release week 12 and
#: the ledger refused with InsufficientFundsError, `min_reserve` already at
#: -8000. The ledger was right and the fixture was wrong.
#:
#:   Weekly Play Reserve       = 1000 x 14 = 14000   (issued at activation)
#:   Yahoo Championship        = 8000               (issued at activation)
#:   FantasyStakes Championship = 8000              (issued by the RC2 stage)
#:   Season-Opening Allocation = 30000
WEEKLY_BET_MINIMUM_CENTS = 1_000
YAHOO_CHAMPIONSHIP_CONTRIBUTION_CENTS = 8_000
FANTASYSTAKES_CHAMPIONSHIP_CONTRIBUTION_CENTS = 8_000
SKUNK_FEE_CENTS = 1_000

#: FINAL POR §14 / WP-17 — the Fantasy Football Championship Pot, as ONE
#: league-level amount the commissioner enters.
#:
#: WHY THE DEMO HAS TO SET IT. `set_draft` leaves this NULL when a caller does
#: not mention it, and that is right: 0 is a real commissioner choice and a
#: caller who never saw the setting must not be taken to have made it. But NULL
#: mints the pillar at zero, so a demo that omitted it showed a league with the
#: Fantasy Football Championship permanently unfunded -- and WP-17 requires the
#: demo to show that championship WHEN FUNDED.
#:
#: IT ALSO DECIDES WHETHER THE GRAND CHAMPIONSHIP EXISTS AT ALL. §20 needs at
#: least two FUNDED pillars, so with only the FantasyStakes pot funded the demo
#: could never leave PLACEHOLDER -- and WP-17 asks for placeholder, live AND
#: final.
#:
#: $80 matches the Yahoo Championship Contribution above, which is the figure
#: this league's GMs would recognise. It is a demo amount, not a product
#: constant: nothing derives it and every league sets its own.
FF_CHAMPIONSHIP_POT_CENTS = 8_000
POOL_ENTRY_CENTS = 500

#: How many FantasyStakes contests `demo.gameplay.versus_card` puts on the board
#: each week, and how many Pool occurrences a week's slate carries. Named here
#: because `demo.reset.expected_fingerprint` derives the canonical row counts
#: from them — a fixture change must move the expectation with it, never leave
#: every visitor looking like they mutated the league.
VERSUS_PER_WEEK_MARKETS: tuple = ("straight", "spread", "over_under")
POOL_SLOTS_PER_WEEK = 4


@dataclass(frozen=True)
class DemoTeam:
    ordinal: int
    team_name: str
    gm: str
    #: Regular-season Yahoo record through COMPLETED_THROUGH_WEEK, as (W, L).
    record: tuple
    #: A one-line story hook, used by the walkthrough and nothing else.
    note: str


#: Twelve teams. The order IS the seeding order for provider keys; the standings
#: order is computed by the real read model, not asserted here.
TEAMS: tuple = (
    DemoTeam(1, "Gravy Seal Team Six", "Marcus Webb", (8, 2),
             "front-runner; lost only to Third and Long Island"),
    DemoTeam(2, "Cleat Fleetwood Mac", "Dana Whitfield", (6, 4),
             "one half of the league's rivalry"),
    DemoTeam(3, "Kittle Big Town", "Priya Raman", (6, 4),
             "the other half; split the season series"),
    DemoTeam(4, "Third and Long Island", "Eli Brandt", (8, 2),
             "co-leader, and holds the head-to-head"),
    DemoTeam(5, "The Punt Investors", "Sofia Delgado", (5, 5),
             "mid-table, still mathematically alive"),
    DemoTeam(6, "Victorious Secret", "Tom Achebe", (5, 5),
             "mid-table, best points-for of the chasing pack"),
    DemoTeam(7, "Pain Sanders", "Nadia Kowalski", (5, 5),
             "started 1-5, has won four straight — the comeback"),
    DemoTeam(8, "Blitz and Pieces", "Rory Sandoval", (5, 5),
             "streaky; the league's biggest single-week score"),
    DemoTeam(9, "Hurts So Good", "Aisha Bennett", (4, 6),
             "unlucky; three losses by under two points"),
    DemoTeam(10, "The Waiver Wire Wizards", "Chen Xiaoming", (4, 6),
             "most transactions in the league"),
    DemoTeam(11, "No Punt Intended", "Grace Ellery", (3, 7),
             "rebuilding, but dangerous in Pools"),
    DemoTeam(12, "Special Teams Only", "Bo Larkin", (1, 9),
             "the wooden spoon race is over"),
)

assert len(TEAMS) == TEAM_COUNT


# ── the Yahoo-style regular season, represented synthetically ────────────────
#
# Six pairings a week, every team playing once. `(home, away, home_pts, away_pts)`
# with points to one decimal, as fantasy scoring reads. These are INVENTED
# numbers; no Yahoo payload was consulted or copied.

def _w(*games):
    return tuple(games)


REGULAR_SCHEDULE: dict = {
    1:  _w((1, 12, 118.4, 82.1), (2, 11, 104.6, 96.3), (3, 10, 112.9, 99.8),
           (4, 9, 121.2, 88.7), (5, 8, 95.4, 108.2), (6, 7, 110.5, 71.9)),
    2:  _w((1, 11, 126.8, 90.2), (2, 10, 99.1, 101.7), (3, 9, 115.3, 106.4),
           (4, 8, 108.9, 97.5), (5, 7, 102.2, 84.6), (6, 12, 119.7, 78.3)),
    3:  _w((1, 10, 109.3, 103.8), (2, 9, 111.4, 105.9), (3, 8, 94.7, 116.2),
           (4, 7, 124.1, 92.8), (5, 12, 113.6, 80.4), (6, 11, 98.2, 100.1)),
    4:  _w((1, 9, 131.5, 97.2), (2, 8, 106.3, 104.8), (3, 12, 127.4, 85.6),
           (4, 11, 118.8, 93.1), (5, 6, 96.9, 114.7), (7, 10, 89.3, 107.5)),
    5:  _w((1, 8, 114.2, 110.6), (2, 12, 122.5, 79.8), (3, 11, 105.7, 99.4),
           (4, 10, 116.9, 102.3), (5, 9, 108.4, 107.1), (6, 7, 101.6, 95.8)),
    6:  _w((1, 7, 119.6, 101.3), (2, 3, 108.7, 112.4), (4, 12, 134.2, 76.9),
           (5, 11, 111.8, 94.5), (6, 10, 103.9, 105.2), (8, 9, 125.7, 98.6)),
    7:  _w((1, 6, 107.4, 112.9), (2, 5, 115.2, 103.6), (3, 4, 99.8, 120.5),
           (7, 12, 126.3, 81.7), (8, 11, 110.9, 96.2), (9, 10, 104.5, 100.8)),
    8:  _w((1, 5, 122.7, 98.4), (2, 4, 101.5, 117.8), (3, 6, 113.2, 109.7),
           (7, 11, 118.4, 92.6), (8, 10, 96.8, 114.3), (9, 12, 121.9, 83.5)),
    9:  _w((1, 4, 105.9, 109.2), (2, 6, 117.3, 102.8), (3, 5, 108.6, 111.4),
           (7, 10, 123.5, 99.7), (8, 12, 129.8, 87.2), (9, 11, 102.4, 106.9)),
    10: _w((1, 3, 128.6, 104.1), (2, 7, 97.5, 116.8), (4, 5, 119.4, 105.3),
           (6, 9, 113.7, 108.2), (8, 11, 107.9, 95.6), (10, 12, 111.2, 84.8)),
    # ── WEEKS 11-14 ARE SCHEDULED AND SCORED, BUT NOT YET PLAYED ────────────
    #
    # THE SCORES LIVE HERE, NOT IN A SECOND FIXTURE. An earlier build kept the
    # run-in results in `demo/states.py` and had the seeder create matchups only
    # through week 11, so the two halves of one season were described in two
    # places and week 12-14 rows had to be conjured at transition time.
    #
    # `COMPLETED_THROUGH_WEEK` — not the presence of a score — decides what the
    # seeder finalizes. So CURRENT seeds weeks 11-14 as real scheduled fixtures
    # with no result posted, and `demo.states` finalizes them one at a time as
    # it plays them. A week is unplayed because the clock has not reached it,
    # which is the same reason it is unplayed in a live league.
    11: _w((1, 2, 118.9, 111.4), (3, 7, 104.7, 121.3), (4, 6, 126.2, 99.8),
           (5, 10, 97.6, 113.5), (8, 9, 120.1, 108.7), (11, 12, 102.3, 94.9)),
    12: _w((1, 3, 121.7, 108.4), (2, 4, 99.6, 118.2), (5, 6, 107.3, 102.9),
           (7, 8, 115.4, 109.1), (9, 11, 111.8, 97.5), (10, 12, 104.2, 88.6)),
    13: _w((1, 4, 112.9, 116.5), (2, 5, 108.1, 103.7), (3, 6, 119.3, 105.8),
           (7, 9, 122.6, 101.4), (8, 12, 127.2, 91.3), (10, 11, 98.7, 100.5)),
    14: _w((1, 5, 125.3, 99.8), (2, 6, 110.4, 106.2), (3, 8, 102.6, 114.9),
           (4, 7, 117.1, 120.8), (9, 10, 109.5, 103.2), (11, 12, 95.4, 87.1)),
}


def team_score(team_ordinal: int, week: int):
    """This team's points in that week, or None if the fixture has no result.

    None IS A DISTINCT ANSWER FROM ZERO and the callers depend on it: a week
    with no result must report no stats at all, because a zero is a measured
    fact and would make an open week look settleable.

    NOTE the fixture carries results for all fourteen weeks. Whether a week has
    been PLAYED is a property of the league's clock, not of this table —
    `demo.states` finalizes a week immediately before settling it, and the
    finality gate is what actually stops an unplayed week from being settled.
    """
    for home, away, home_pts, away_pts in REGULAR_SCHEDULE.get(week, ()):
        if home == team_ordinal:
            return home_pts
        if away == team_ordinal:
            return away_pts
    return None


#: When the showcase's synthetic week was "observed". A FIXED instant, because
#: gate-2 readiness ages a measurement and a wall-clock stamp would make the
#: demo's pool activation go stale on its own between showings.
OBSERVED_AT = _dt.datetime(2026, 12, 30, 12, 0, 0, tzinfo=_dt.timezone.utc)


# ── WHY THERE IS NO VERSUS OR POOL FIXTURE HERE ──────────────────────────────
#
# There used to be one: `DEMO_VERSUS` and `DEMO_POOLS` listed every contest, its
# stake and its winner, and the seeder posted those outcomes straight to the
# ledger. The totals were right and the league had never played — no
# `BeefChallenge`, no `Bet`, no `PoolInstance`, no `PoolClaim` — so the standings
# read model, which counts ROWS, showed twelve GMs at 0-0 with no pool wins.
#
# The contests are now GENERATED by `demo.gameplay` from this schedule and
# settled by the real engines, so a fixture describing their results would be a
# second, competing account of the same season. Whatever the season produces is
# the answer; `expected_story()` below records what that turned out to be.


# ── the championship demo input ──────────────────────────────────────────────
#
# THE CHAMPIONSHIP SCORE IS NOT DECLARED HERE, AND THAT IS DELIBERATE. An
# earlier draft of this fixture listed the scores it expected each GM to finish
# on. That was wrong in principle and wrong in fact: the Championship Score is
# realized net from settled FantasyStakes contests, so it is whatever the REAL
# read model derives from the postings above — and the hand-written numbers did
# not match what the engine produced. A demo that asserts its own scores has
# stopped demonstrating the product.
#
# So the only championship input the fixture supplies is the one the demo
# genuinely has to invent: Yahoo's postseason podium.

#: What the bracket below RESOLVES TO — champion, runner-up, official third.
#:
#: NOT AN INPUT TO THE PODIUM. `economy.championship_podium` derives the podium
#: from the bracket by certified code, and a caller that could simply name three
#: teams would be a bypass of exactly the control WP1D added. This constant is
#: the documented expectation, asserted against the derived podium by the D2.4
#: suite; if the bracket below changes, the assertion fails rather than this
#: quietly disagreeing with reality.
YAHOO_PODIUM_ORDINALS: tuple = (4, 1, 7)

#: The synthetic postseason bracket — SIX teams, two byes, three rounds over the
#: demo's postseason weeks.
#:
#: WHY A BRACKET AND NOT A DECLARED PODIUM. `close_season_economy` distributes
#: the Championship Pot through `economy.championship_podium`, which refuses any
#: recipient order that is not derivable from a complete championship track:
#: "The Championship Pot recipient order is not derivable from standings, seed
#: or regular-season scoring." That refusal is the product protecting a payout,
#: and the demo answers it the way a provider does — by reporting a bracket and
#: letting the certified deriver read it.
#:
#: EVERY ROW IS INVENTED. No Yahoo payload, no Yahoo key, no Yahoo read.
#:
#: `(week, home_ordinal, away_ordinal, home_points, away_points, is_championship)`
POSTSEASON_FIELD_ORDINALS: tuple = (4, 1, 7, 9, 2, 3)
POSTSEASON_BRACKET: tuple = (
    # Round 1 — the four unseeded teams; ordinals 4 and 1 hold byes.
    (15, 7, 3, 118.2, 104.6, True),
    (15, 2, 9, 121.5, 110.3, True),
    # Round 2 — semifinals. The byes enter; 2 and 7 lose and go to the
    # third-place game, which is what makes that game identifiable at all.
    (16, 4, 2, 126.4, 112.8, True),
    (16, 1, 7, 119.7, 115.1, True),
    # Round 3 — the final, and beside it the official third-place game. The
    # third-place row is NON_CHAMPIONSHIP: an eliminated team is not a title
    # contender, and `_identify_third_place` recognises it by its participants
    # being exactly the semifinal losers.
    (17, 4, 1, 131.0, 122.5, True),
    (17, 7, 2, 113.9, 108.4, False),
)


def expected_story() -> dict:
    """What the season ACTUALLY produces, recorded so a regression is visible.

    NOT A SOURCE OF TRUTH FOR ANY SURFACE, and no longer a wish. Nothing in the
    application reads this.

    ── WHY THESE NUMBERS CHANGED ────────────────────────────────────────────

    An earlier version of this function stated the story the fixture was DESIGNED
    to tell — a named front-runner, a named comeback reaching the podium — and
    the seeder hand-posted results that made it come true. Once the season began
    genuinely playing through the real Versus and Pool engines, the outcome
    became whatever those engines produce from the schedule, the rosters and the
    projections. It is deterministic, but it is theirs, not the fixture's.

    So this now records the VERIFIED result and the D1/D2.4 suites assert the
    league against it. If a fixture edit moves the champion, the assertion fails
    and the story is updated deliberately — rather than the demo quietly telling
    one story on screen and another in the docs.
    """
    # ── WHY THE CURRENT LEADER MOVED AT REV 1.4 ──────────────────────────
    #
    # POR Rev 1.4 §4.2 rules the weekly slate at 3 TEAM + 1 MATCHUP. A
    # different set of Prop Pool definitions is therefore drawn every week,
    # different subjects win them, and every GM's pool net moves. MEASURED
    # across the two builds on the same seeded showcase: all twelve teams'
    # `versus_net_cents` and Versus records are BYTE-IDENTICAL, and all twelve
    # `pool_net_cents` differ. The Championship Chase is the sum of the two, so
    # its CURRENT order moved and its Matchup half did not.
    #
    # That is the rotation ruling arriving, not a settlement defect — which is
    # exactly the case this function was written to absorb: "If a fixture edit
    # moves the champion, the assertion fails and the story is updated
    # deliberately."
    #
    # WHAT DID NOT MOVE: the FINAL podium is still ordinals (1, 2, 11) and the
    # Grand Champion is still ordinal 1. Only the CURRENT standing changed.
    #
    # AND WHAT THAT COSTS THE DEMO, STATED PLAINLY. Ordinal 1 now leads at
    # CURRENT *and* wins at FINAL, so the lead no longer changes hands over the
    # run-in and `leader_changes_between_states` is False below. The comment on
    # that field is right that a table which never moves is a weaker
    # demonstration; restoring a lead change is a FIXTURE question — which weeks
    # the showcase plays and how it claims — and is deliberately NOT answered by
    # bending a governed rotation rule into a nicer story.
    return {
        # ── CURRENT (week 11 live) ───────────────────────────────────────────
        #: Gravy Seal Team Six leads the Championship Chase at CURRENT.
        #: Was ordinal 2 (Cleat Fleetwood Mac) before POR Rev 1.4 §4.2.
        "current_leader_ordinal": 1,
        #: Gravy Seal Team Six is unbeaten in FantasyStakes matchups at CURRENT.
        "current_unbeaten_ordinal": 1,

        # ── FINAL (season closed) ────────────────────────────────────────────
        #: The FantasyStakes Championship podium, in order.
        #: WAS (1, 2, 11) — Gravy Seal Team Six, Cleat Fleetwood Mac, No Punt
        #: Intended. POR Rev 1.4 §4.2's governed 3 TEAM + 1 MATCHUP slate draws a
        #: different set of Prop Pools every week, so the prop-pool half of every
        #: GM's Championship Score moved and second and third place changed
        #: hands. The CHAMPION did not: ordinal 1 still wins, and still wins as
        #: Yahoo runner-up, which is the case the Grand Champion rule exists to
        #: decide.
        "final_podium_ordinals": (1, 12, 4),
        #: The Grand Champion — FantasyStakes champion AND Yahoo runner-up,
        #: which is precisely the case the Grand Champion rule exists to decide.
        "grand_champion_ordinal": 1,
        #: WAS True. Under POR Rev 1.4 §4.2's governed slate the CURRENT
        #: leader and the FINAL champion are the same GM, so the lead does
        #: not change hands. Recorded as MEASURED rather than as wished
        #: for — see the note above `return`. A demo-narrative consequence
        #: of the rotation ruling, and a candidate for a later fixture
        #: pass.
        "leader_changes_between_states": False,

        # ── invariants, not outcomes ─────────────────────────────────────────
        #: Nobody may be left with nothing to show on every column.
        "min_absolute_net_cents": 0,
    }
