"""
betting/shortfall_sweep.py — B2, Section 6: weekly shortfall-to-championship sweep.

Trigger (already decided, not reopened here): each GM must wager at least
the league's Weekly Bet Minimum across pool + versus bets combined, each
REGULAR-SEASON week. Whatever portion goes unmet sweeps to championship, in
one atomic paired posting per team per week — covered by the team's own
wallet where funded, receivable for the rest.

── PG-CERT-1 · WHERE THE WEEKLY MINIMUM COMES FROM ────────────────────────

THE FROZEN COMMISSIONER CONFIGURATION, and the legacy stop only when there
isn't one. This module used to read `get_league_economy_stop` directly, which
resolves against the five-value Discrete-Stop table — and that was wrong in two
distinct ways once ECONCFG made the economy configurable:

  · a league configured with a Weekly Bet Minimum that is not one of the five
    certified stops made `get_league_economy_stop` RAISE, so the sweep crashed
    on exactly the leagues the configurable economy exists to serve; and

  · a league whose stop column still held a legacy value while its real,
    frozen configuration said something else was swept at the WRONG minimum —
    silently, against real wallets, into the championship pot.

`resolve_allocation_terms` is the one place that already knows the answer
("a FROZEN configuration wins; otherwise the legacy fixed stop applies"), so
this asks it rather than re-deciding. No new arithmetic is introduced here and
none is duplicated: the formula lives in `payments/economy_config.py`.

── AND NOT IN THE POSTSEASON ──────────────────────────────────────────────

There is no Weekly Bet Minimum after the regular season, so there is nothing
to fall short OF and nothing to sweep. This is a governed rule, not an
optimisation: sweeping a postseason week would move real money out of wallets
to satisfy an obligation the product says does not exist. The phase comes from
`betting/pool_season_boundary.phase_for_week`, which is the same authority the
Pool engine uses, rather than a second reading of `playoff_start_week`.

Framing (B2-6.7): no account in this system holds custody of *external*
real money — buy-ins and payouts confirm/settle outside the app, honor
system. That does NOT make reserve/receivable semantics advisory; it just
means the ledger's job here is producing an honest number, not solvency.

Cadence: weekly, not season-end — an internal transfer between two ledger
accounts already inside the system (wallet/receivable and championship).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import (
    Bet, League, Matchup, PoolConfig, PoolPot, ShortfallSweepRecord, Team,
    Wallet,
)
from betting.pool_season_boundary import PHASE_POSTSEASON, phase_for_week
from payments.economy_config import (
    get_league_economy_stop, resolve_allocation_terms,
)
from ledger.ledger import post as ledger_post, balance_of


def _to_cents(amount: float) -> int:
    """Dollars → integer cents. Rounds first — never truncates raw float
    multiplication — per the L1 spec's integer-cents-only requirement."""
    return round(amount * 100)


@dataclass
class SweepResult:
    team_id:          int
    week:             int
    weekly_min_cents: int
    wagered_cents:    int
    shortfall_cents:  int
    covered_cents:    int
    uncovered_cents:  int
    swept:            bool   # True if a ledger posting was made this call (shortfall_cents > 0)
    already_run:      bool   # True if this team/week was already swept before this call
    #: True when the week is postseason, where no Weekly Bet Minimum exists.
    #: Reported rather than silently returning a zero shortfall, so a caller —
    #: or a wrap-up line — can say WHY nothing was swept.
    postseason:       bool = False


def _compute_wagered_cents(team_id: int, league_id: int, week: int, db: Session) -> int:
    """
    Sum of versus-bet stakes (straight/spread/over_under/prop/the_lineup —
    including beef-originated bets, which write the same Bet rows) placed
    by this team in this week, plus the flat pool entry if the pool was
    collected league-wide for this week.

    Pool participation ruling (this session, confirmed via direct code
    read of betting/pool_engine.py's collect_weekly_entries()):
    collect_weekly_entries() charges every team in the league the same
    flat weekly_entry, once per week, gated only by PoolPot.entries_collected
    — NOT by PoolBetPick submission (a team can be charged without ever
    submitting a pick; the charge and the pick are independent). So pool
    credit here is keyed on PoolPot.entries_collected for that league+week,
    not on whether this specific team submitted a pick.
    """
    wallet = db.query(Wallet).filter(Wallet.team_id == team_id).first()
    versus_dollars = 0.0
    if wallet:
        versus_dollars = (
            db.query(func.sum(Bet.amount))
            .join(Matchup, Bet.matchup_id == Matchup.id)
            .filter(
                Bet.wallet_id    == wallet.id,
                Matchup.league_id == league_id,
                Matchup.week      == week,
            )
            .scalar()
        ) or 0.0

    pool_cents = 0
    pot = (
        db.query(PoolPot)
        .filter(PoolPot.league_id == league_id, PoolPot.week == week)
        .first()
    )
    if pot and pot.entries_collected:
        cfg = db.query(PoolConfig).filter(PoolConfig.league_id == league_id).first()
        if cfg:
            pool_cents = cfg.weekly_entry_cents

    return _to_cents(versus_dollars) + pool_cents


def weekly_minimum_cents(league_id: int, db: Session) -> int:
    """The league's Weekly Bet Minimum, from whichever authority governs it.

    ONE QUESTION, ONE ANSWER, AND IT IS NOT DECIDED HERE. A frozen commissioner
    configuration governs a configured league-season; an unconfigured one falls
    back to its legacy stop. `resolve_allocation_terms` already owns that
    precedence and this defers to it, so a change in the rule cannot leave the
    sweep charging against a basis nothing else uses.
    """
    league = db.query(League).filter(League.id == league_id).first()
    if league is not None:
        terms = resolve_allocation_terms(db, league_id=league_id,
                                         season=league.season)
        if terms.is_configured and terms.weekly_bet_minimum_cents is not None:
            return terms.weekly_bet_minimum_cents
    # LEGACY. `get_league_economy_stop` is still correct for a league that was
    # never configured, and still raises loudly for a stored value matching no
    # certified stop — which is the right behaviour for that path and is not
    # weakened here.
    return get_league_economy_stop(league_id, db).weekly_min_cents


def sweep_shortfall_for_team(team_id: int, league_id: int, week: int, db: Session) -> SweepResult:
    """
    Computes, and if needed posts, one team's shortfall sweep for one week.

    Idempotent per (league_id, team_id, week) via ShortfallSweepRecord —
    calling this again for the same team/week returns the existing record
    (already_run=True) without posting again, whether or not the original
    call found a shortfall.
    """
    # THE POSTSEASON GUARD COMES FIRST, before the idempotency read and before
    # any economy lookup. There is no Weekly Bet Minimum here, so there is no
    # record to write, no posting to make and nothing to be idempotent about —
    # a postseason call is a pure no-op however many times it is made.
    league = db.query(League).filter(League.id == league_id).first()
    if league is not None and phase_for_week(league, week) == PHASE_POSTSEASON:
        return SweepResult(
            team_id=team_id, week=week, weekly_min_cents=0, wagered_cents=0,
            shortfall_cents=0, covered_cents=0, uncovered_cents=0,
            swept=False, already_run=False, postseason=True)

    existing = (
        db.query(ShortfallSweepRecord)
        .filter(
            ShortfallSweepRecord.league_id == league_id,
            ShortfallSweepRecord.team_id   == team_id,
            ShortfallSweepRecord.week      == week,
        )
        .first()
    )
    if existing:
        return SweepResult(
            team_id=team_id, week=week,
            weekly_min_cents=existing.weekly_min_cents,
            wagered_cents=existing.wagered_cents,
            shortfall_cents=existing.shortfall_cents,
            covered_cents=existing.covered_cents,
            uncovered_cents=existing.uncovered_cents,
            swept=False,
            already_run=True,
        )

    weekly_min_cents = weekly_minimum_cents(league_id, db)
    wagered_cents    = _compute_wagered_cents(team_id, league_id, week, db)
    shortfall_cents  = max(0, weekly_min_cents - wagered_cents)

    covered_cents   = 0
    uncovered_cents = 0
    posting_id_str  = None

    if shortfall_cents > 0:
        # B2-6.2 — compute the pre-split, always-valid posting BEFORE calling
        # ledger.post(): the ledger's own funded-balance guard (MS-L1-5.1)
        # would reject a raw shortfall_cents debit against a wallet that
        # can't cover it. covered_cents is bounded by the wallet's CURRENT
        # funded balance (read inside this same session/transaction, so it
        # can't go stale between this read and the write below).
        wallet_balance_cents = balance_of(f"wallet:{team_id}")
        covered_cents   = min(shortfall_cents, max(0, wallet_balance_cents))
        uncovered_cents = shortfall_cents - covered_cents

        # B2-6.3 (Option A) — one atomic posting, full shortfall credited to
        # championship immediately, not split into "collected now" / "owed
        # later" postings. No zero-value rows (Door 4's remainder discipline):
        # the receivable leg is omitted entirely when the wallet fully covers.
        entries: list[tuple[str, int]] = []
        if covered_cents > 0:
            entries.append((f"wallet:{team_id}", -covered_cents))
            entries.append(("championship", covered_cents))
        if uncovered_cents > 0:
            entries.append((f"receivable:{team_id}", -uncovered_cents))
            entries.append(("championship", uncovered_cents))

        posting_id = ledger_post(entries, door="shortfall_sweep", session=db)
        posting_id_str = str(posting_id)

    db.add(ShortfallSweepRecord(
        league_id        = league_id,
        team_id          = team_id,
        week             = week,
        weekly_min_cents = weekly_min_cents,
        wagered_cents    = wagered_cents,
        shortfall_cents  = shortfall_cents,
        covered_cents    = covered_cents,
        uncovered_cents  = uncovered_cents,
        posting_id       = posting_id_str,
    ))
    db.commit()

    return SweepResult(
        team_id=team_id, week=week,
        weekly_min_cents=weekly_min_cents,
        wagered_cents=wagered_cents,
        shortfall_cents=shortfall_cents,
        covered_cents=covered_cents,
        uncovered_cents=uncovered_cents,
        swept=shortfall_cents > 0,
        already_run=False,
    )


def sweep_shortfall_for_week(league_id: int, week: int, db: Session) -> list[SweepResult]:
    """Runs sweep_shortfall_for_team() for every team in the league."""
    teams = db.query(Team).filter(Team.league_id == league_id).order_by(Team.id).all()
    return [sweep_shortfall_for_team(team.id, league_id, week, db) for team in teams]


def sweep_explanation_text(result: SweepResult) -> str:
    """Plain-language, template-fallback-safe summary of one team's sweep
    result for a given week — used by the weekly wrap (Section 6, 'Also
    required')."""
    if result.postseason:
        # NOT "wagered $0.00 against a $0.00 minimum", which is arithmetically
        # true and reads as a bug. The postseason has no Weekly Bet Minimum and
        # the sentence should say so.
        return (f"Week {result.week}: postseason — no Weekly Bet Minimum "
                f"applies, so nothing was swept.")
    if not result.swept:
        return (
            f"Week {result.week}: wagered ${result.wagered_cents / 100:,.2f} against a "
            f"${result.weekly_min_cents / 100:,.2f} minimum — no shortfall swept."
        )
    parts = [
        f"Week {result.week}: wagered ${result.wagered_cents / 100:,.2f} against a "
        f"${result.weekly_min_cents / 100:,.2f} minimum — "
        f"${result.shortfall_cents / 100:,.2f} short."
    ]
    if result.covered_cents > 0:
        parts.append(f"${result.covered_cents / 100:,.2f} swept from your wallet to the championship pot.")
    if result.uncovered_cents > 0:
        parts.append(
            f"${result.uncovered_cents / 100:,.2f} couldn't be covered by your wallet — "
            f"added to your outstanding balance (receivable) instead."
        )
    return " ".join(parts)
