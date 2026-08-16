"""
reports/standings_read_model.py — the Rev 4.3 competitive standings.

WP3B. An ADDITIVE READ MODEL (YELLOW). It posts nothing, settles nothing,
decides no eligibility and owns no lifecycle. Every figure it reports is a SUM
OF LEDGER LEGS THAT WERE ALREADY POSTED, grouped by the door that posted them.

WHY THIS EXISTS
---------------
Rev 4.3 §7 makes Standings the default tab and requires three tables — Overall,
Versus and Pool — each ranked by an authoritative server-derived COMPETITIVE
result. §7.1 is explicit that raw Wallet balance must not decide Overall rank,
because allocation, Top-Offs, Weekly Minimum release and expiry all move Wallet
without anybody winning or losing anything.

So the question this module answers is narrow: of everything that has moved a
GM's spendable Credits, HOW MUCH OF IT WAS COMPETITION? The ledger already
records the answer, because every posting names the door that made it.

THE DERIVATION, AND WHY IT IS A READ RATHER THAN A NEW RULE
-----------------------------------------------------------
`economy/current_settle.py` established this exact technique and is certified on
it: `season_advance_cents` and `topoff_issued_cents` are both
`SUM(amount_cents) WHERE door = :door AND account = :account`. Nothing here is a
new kind of derivation — it is the same one over a different door grouping, and
the grouping is enumerated by name below rather than inferred from a prefix.

A GM's SPENDABLE accounts are `wallet:{team}` and `min:{team}:{week}`, and both
must be summed. `economy/spend_sourcing.py::plan_spend_split` funds MIN FIRST
then wallet, so a Pool entry or a Versus stake paid out of a released Weekly
Minimum never touches `wallet:` at all. Summing only `wallet:` would report that
GM as having spent nothing.

    versus_net = Σ(spend-account legs under the Versus doors) + open Versus escrow
    pool_net   = Σ(spend-account legs under the Pool doors)
    net        = versus_net + pool_net

THE OPEN-ESCROW TERM IS WHY AN UNSETTLED WAGER IS NOT A LOSS. Placing a stake
debits the spend account immediately; the money sits in `escrow:` until the
wager resolves. Without the add-back, a GM who had just placed a wager would
appear to be losing by exactly their stake. `in_play_cents` — the same
authoritative attribution `current_settle` uses, read here through
`league_positions` rather than re-implemented — cancels the placement leg
exactly while the wager is open, and stops cancelling it the moment settlement
posts. Pools need no such term: a collected weekly contribution has LEFT the GM
(current_settle's own words) and is never refunded.

WHAT THIS MODULE DELIBERATELY DOES NOT REPORT
---------------------------------------------
Wallet, Available, Current Settle, obligations, advances, receivables. Standings
is read by every member about every other member, and Rev 4.3 §7.5 keeps the
competitive ranking and the accounting apart. Account is where a GM reads their
own money; nothing about anybody else's position leaves this module.

TIE ORDERING IS DISPLAY DETERMINISM, NOT A SETTLEMENT RULE (Rev 4.3 §7).
Equal NET is broken by ascending `team_id`, which is the canonical GM identifier
the Pool engine already orders payouts by (`betting/pool_settlement.py`, POR
§6.3). It decides who is printed first and nothing else — no money, no
entitlement and no eligibility depends on it.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from economy.economy_events import wallet_account
from reports.ledger_read_model import LedgerReadModelError, league_positions


# ── The door groupings ───────────────────────────────────────────────────────
#
# ENUMERATED BY NAME, NEVER BY PREFIX. A prefix test ("does the door start with
# 'challenge'?") silently absorbs any door added later, which is how a
# non-competitive movement ends up inside a competitive total without anybody
# editing this file. Adding a door here is a deliberate, reviewable edit.
#
# Each constant is imported from the module that OWNS the door, so a rename
# there is a NameError here rather than a silently empty sum.

from betting.pool_funding import (          # noqa: E402
    DOOR_DIVISION_REMAINDER, DOOR_WEEKLY_COLLECTION,
)
from betting.pool_settlement import (       # noqa: E402
    DOOR_CHAMPIONSHIP_SWEEP, DOOR_ROLLOVER_EXPIRY, DOOR_WINNER_DISTRIBUTION,
)
from economy.challenge_funding import (     # noqa: E402
    DOOR_DERIVED, DOOR_ISSUED, DOOR_MIGRATED, DOOR_REFUNDED, DOOR_RELEASED,
    DOOR_TOPUP,
)
from economy.dynamic_challenge import (     # noqa: E402
    DOOR_FL_MIGRATE, DOOR_FL_REFUND, DOOR_HS_DERIVED, DOOR_HS_RELEASE,
    DOOR_HS_SPLIT, DOOR_HS_TOPUP,
)

#: Every door through which Versus competition moves a GM's Credits.
#:
#: The escrow-to-escrow doors (MIGRATED, HS_SPLIT, FL_MIGRATE) are included even
#: though they touch no spend account. They contribute exactly zero, and listing
#: them makes the set demonstrably EXHAUSTIVE over the Versus machinery — a
#: reader checking this against `challenge_funding.py` and `dynamic_challenge.py`
#: can confirm nothing was left out, which is not possible against a partial list.
VERSUS_DOORS: tuple[str, ...] = (
    "wager_placed",
    "wager_settled",
    DOOR_ISSUED,
    DOOR_TOPUP,
    DOOR_RELEASED,
    DOOR_REFUNDED,
    DOOR_MIGRATED,
    DOOR_DERIVED,
    DOOR_HS_TOPUP,
    DOOR_HS_RELEASE,
    DOOR_HS_SPLIT,
    DOOR_HS_DERIVED,
    DOOR_FL_REFUND,
    DOOR_FL_MIGRATE,
)

#: Every door through which Pool competition moves a GM's Credits.
#:
#: SWEEP and ROLLOVER_EXPIRY move money between league-level accounts and reach
#: no GM; they are listed for the same exhaustiveness reason as above.
POOL_DOORS: tuple[str, ...] = (
    DOOR_WEEKLY_COLLECTION,
    DOOR_DIVISION_REMAINDER,
    DOOR_WINNER_DISTRIBUTION,
    DOOR_CHAMPIONSHIP_SWEEP,
    DOOR_ROLLOVER_EXPIRY,
)

#: The door that pays a Pool winner. A GM's Pool WINS is the number of distinct
#: postings under it that credited their wallet — one posting per settled
#: occurrence, one leg per winning GM (`betting/pool_settlement.py`).
POOL_WIN_DOOR = DOOR_WINNER_DISTRIBUTION


# ── Rows ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StandingsRow:
    """One team's competitive position. NO ACCOUNTING FIELDS — see module docs."""

    team_id: int
    team_name: str
    owner: str

    #: Settled Versus wagers. A push is neither, so it appears in neither count.
    versus_wins: int
    versus_losses: int
    versus_pushes: int

    #: Settled Pool occurrences this GM was paid from.
    pool_wins: int

    #: Exact integer cents. Negative is a real and ordinary answer.
    versus_net_cents: int
    pool_net_cents: int

    @property
    def net_cents(self) -> int:
        """The combined competitive result Overall ranks on."""
        return self.versus_net_cents + self.pool_net_cents

    @property
    def versus_record(self) -> str:
        """W-L for display. Pushes are excluded, as they are from the counts."""
        return f"{self.versus_wins}-{self.versus_losses}"

    def as_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "team_name": self.team_name,
            "owner": self.owner,
            "versus_wins": self.versus_wins,
            "versus_losses": self.versus_losses,
            "versus_pushes": self.versus_pushes,
            "versus_record": self.versus_record,
            "pool_wins": self.pool_wins,
            "versus_net_cents": self.versus_net_cents,
            "pool_net_cents": self.pool_net_cents,
            "net_cents": self.net_cents,
        }


@dataclass(frozen=True)
class LeagueStandings:
    """Three orderings over ONE set of rows.

    The three tables are three ORDERINGS, not three reads. Ordering the same
    rows three ways is what makes it impossible for Overall to disagree with
    Versus about what a team's Versus net was — a second query shaped for the
    second table is exactly how two tables come to state different facts.
    """

    league_id: int
    season: int
    #: The acting GM's team, so the UI can mark their row in all three tables
    #: without matching on a name. None when the reader owns no team here.
    acting_team_id: int | None
    rows: tuple[StandingsRow, ...]

    @property
    def overall(self) -> tuple[StandingsRow, ...]:
        return tuple(sorted(self.rows, key=lambda r: (-r.net_cents, r.team_id)))

    @property
    def versus(self) -> tuple[StandingsRow, ...]:
        return tuple(sorted(self.rows,
                            key=lambda r: (-r.versus_net_cents, r.team_id)))

    @property
    def pools(self) -> tuple[StandingsRow, ...]:
        return tuple(sorted(self.rows,
                            key=lambda r: (-r.pool_net_cents, r.team_id)))


# ── Components ───────────────────────────────────────────────────────────────

def _door_net_cents(db: Session, team_id: int, doors: tuple[str, ...]) -> int:
    """Sum this team's SPENDABLE-account legs under a named set of doors.

    Both spend accounts, for the reason in the module docstring: `min:` is spent
    before `wallet:`, so a stake funded from a released Weekly Minimum is
    invisible to a wallet-only sum.

    The `min:` pattern ends in a colon deliberately — `min:1:%` cannot match
    `min:10:5`, because the character after `min:1` there is `0` and not `:`.
    """
    if not doors:
        return 0
    db.flush()
    placeholders = ", ".join(f":d{i}" for i in range(len(doors)))
    params: dict[str, object] = {f"d{i}": d for i, d in enumerate(doors)}
    params["wallet"] = wallet_account(team_id)
    params["min_pattern"] = f"min:{team_id}:%"
    total = db.execute(text(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
        f"WHERE door IN ({placeholders}) "
        "AND (account = :wallet OR account LIKE :min_pattern)"),
        params).scalar()
    return int(total or 0)


def _pool_wins(db: Session, team_id: int) -> int:
    """Settled Pool occurrences that paid this GM.

    COUNTED FROM THE POSTING, NOT FROM THE CLAIM. A claim records what a GM
    picked; it does not record that the pick won, and a pick that won a pot
    nobody could be paid from is not a win. One `pool_winner_distribution`
    posting exists per settled occurrence that distributed, and this GM has a
    leg in it exactly when they were one of its winners.
    """
    db.flush()
    total = db.execute(text(
        "SELECT COUNT(DISTINCT posting_id) FROM ledger_entries "
        "WHERE door = :door AND account = :wallet AND amount_cents > 0"),
        {"door": POOL_WIN_DOOR, "wallet": wallet_account(team_id)}).scalar()
    return int(total or 0)


def _versus_record(db: Session, team_id: int, league_id: int
                   ) -> tuple[int, int, int]:
    """Settled Versus wins, losses and pushes for one team in one league.

    READ FROM THE SETTLED BET ROWS, which is where the settlement engine records
    the outcome (`betting/settlement_engine.py` sets `status` and `settled_at`
    in the same transaction as the `wager_settled` posting). A record is a COUNT
    of decided wagers, so it cannot be derived from the money — two wagers that
    net to zero are 1-1, not 0-0.

    VERSUS ONLY: `beef_challenge_id IS NOT NULL` excludes any plain single-GM
    wager, which is not a Versus result and has no opponent.

    LEAGUE-SCOPED THROUGH THE MATCHUP, so a team that somehow held wagers under
    another league's matchups could not contribute them to this table.
    """
    from db.schema import Bet, Matchup, Wallet

    db.flush()
    rows = (db.query(Bet.status)
            .join(Wallet, Bet.wallet_id == Wallet.id)
            .join(Matchup, Bet.matchup_id == Matchup.id)
            .filter(Wallet.team_id == team_id,
                    Matchup.league_id == league_id,
                    Bet.beef_challenge_id.isnot(None),
                    Bet.status.in_(("won", "lost", "push")))
            .all())
    statuses = [r[0] for r in rows]
    return (statuses.count("won"), statuses.count("lost"),
            statuses.count("push"))


# ── Derivation ───────────────────────────────────────────────────────────────

def league_standings(db: Session, *, league_id: int,
                     acting_team_id: int | None = None) -> LeagueStandings:
    """The league's competitive standings, derived from posted state.

    MEMBERSHIP AND THE OPEN-ESCROW TERM BOTH COME FROM `league_positions`,
    which is the certified authority on both. Calling it rather than re-reading
    the roster and re-attributing escrow is what keeps a GM's In Play here equal
    to the In Play their own Account tab shows — a second attribution shaped for
    this response is exactly how the two come to disagree.

    It raises `LedgerReadModelError` for an absent league and
    `CurrentSettleError` for an escrow whose ownership posted state cannot
    determine. NEITHER IS CAUGHT. An unattributable escrow already refuses the
    Account tab rather than approximating, and a standings table that quietly
    substituted a guess for the same fact would be the worse of the two answers.
    """
    positions = league_positions(db, league_id=league_id)

    from db.schema import League
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:                          # pragma: no cover - guarded above
        raise LedgerReadModelError("LEAGUE_NOT_FOUND",
                                   f"League {league_id} not found")

    rows: list[StandingsRow] = []
    for position in positions:
        team_id = position.team_id
        wins, losses, pushes = _versus_record(db, team_id, league_id)
        rows.append(StandingsRow(
            team_id=team_id,
            team_name=position.team_name,
            owner=position.owner,
            versus_wins=wins,
            versus_losses=losses,
            versus_pushes=pushes,
            pool_wins=_pool_wins(db, team_id),
            # THE OPEN-ESCROW ADD-BACK, and why it is `in_play_cents` and not
            # `held_open_challenges_cents`. What has to be cancelled here is
            # EVERY Versus debit that has not yet resolved, and those sit in two
            # different places: an issued offer's money is in
            # `escrow:challenge:{id}`, an accepted wager's is in
            # `escrow:{bet_id}`. `in_play_cents` attributes both, because it
            # scans every escrow account still holding a balance.
            # `held_open_challenges_cents` covers only the first
            # (`economy/challenge_escrow_view.py` filters to OPEN_RESPONSE_STATES
            # by design), so using it would leave every accepted-but-unsettled
            # stake standing as a loss until the week settled.
            versus_net_cents=(_door_net_cents(db, team_id, VERSUS_DOORS)
                              + position.in_play_cents),
            pool_net_cents=_door_net_cents(db, team_id, POOL_DOORS),
        ))

    return LeagueStandings(
        league_id=league_id,
        season=league.season,
        acting_team_id=acting_team_id,
        rows=tuple(rows),
    )
