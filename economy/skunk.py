"""
Skunk — weekly assessment and season distribution (S5-P2, owner ruling S5-R1).

SKUNK IS LEDGER-ONLY. It NEVER debits `wallet:`, `min:` or `min_reserve:`. The
full assessment is recorded as an obligation on `receivable:{team}` and credited
to `skunk:{league_id}`:

    receivable:{team}   -assessed      (the obligation grows)
    skunk:{league_id}   +assessed      (the pot grows)

`receivable:*` is exempt from the ledger's non-negative guard, which is exactly
what lets an obligation be recorded without any wallet having to fund it. A GM's
current liquidity therefore has no effect on whether or how much Skunk is
assessed — there is no Wallet-first branch, no Weekly-Minimum-first branch and
no insufficient-funds failure, because there is nothing to be insufficient.

ONE CONTRIBUTION PER LEAGUE-WEEK, DIVIDED — NOT CHARGED N TIMES. When GMs tie
for the largest margin of defeat, the single configured contribution is split
across them by the same canonical-ID remainder rule POR §6.3 uses for pool
payouts: floor to everyone, one extra cent to the lowest ids until the remainder
is gone. Charging each tied GM a full contribution would multiply the league's
Skunk pot by the size of the tie.

TWO ZERO OUTCOMES THAT MUST NOT BE CONFLATED:

    NO_LOSER              every matchup tied. A legitimate competitive result.
                          Zero assessment, no obligation, no pot movement, and
                          an event row IS written so the week is closed and a
                          retry is a no-op.
    RESULTS_NOT_READY     a required matchup is not economically final
                          (finalized_at IS NULL). Fail closed, named error,
                          NOTHING posted and NO event row — so the week stays
                          open and can be assessed once the result is final.

Writing an event row in the second case would permanently mark the week
assessed and silently forfeit the league's Skunk for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from betting.pool_season_boundary import playoff_start_week
from economy.economy_events import (
    DOOR_SKUNK_ASSESSMENT,
    DOOR_SKUNK_DISTRIBUTION,
    EVENT_SKUNK_ASSESSMENT,
    EVENT_SKUNK_DISTRIBUTION,
    league_season_key,
    league_week_key,
    receivable_account,
    record_event,
    skunk_account,
    wallet_account,
)
from ledger.ledger import _balance_of_in_session, post as ledger_post

#: The historical weekly Skunk contribution, in integer cents.
#:
#: THE DEFAULT FOR AN UNCONFIGURED LEAGUE-SEASON ONLY (ECONCFG-WP1D). A season
#: with a frozen economy configuration assesses its own configured fee; see
#: `resolve_skunk_fee_cents`.
#:
#: AUTHORITY: BAB-504 (Weekly Contribution), Merged Section 4.7 Skunk Pot —
#: "Default weekly Skunk amount $10; regular season only (weeks 1-14), never
#: playoffs. ... Accumulates up to $140/season."
#:
#:     default weekly Skunk fee      1000 cents  ($10)
#:     default 14-week maximum      14000 cents  ($140)
#:
#: This was 2000, which was wrong: it doubled every assessed GM's obligation and
#: so understated their Current Settle by $10 per assessment.
#:
#: It is a DEFAULT, not a fixed rate — BAB-504 assesses "the League-configured
#: Skunk amount", so a league may supply another via
#: `assess_weekly_skunk(contribution_cents=...)`.
DEFAULT_SKUNK_CONTRIBUTION_CENTS = 1000

#: BAB-504's stated season ceiling, carried so a test can assert the governed
#: $140 accumulation without re-deriving it from the weekly figure.
DEFAULT_SKUNK_SEASON_MAXIMUM_CENTS = 14000


class SkunkError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_RESULTS_NOT_READY = "RESULTS_NOT_READY"
REASON_NOT_REGULAR_SEASON = "NOT_REGULAR_SEASON"
REASON_LEAGUE_NOT_FOUND = "LEAGUE_NOT_FOUND"
REASON_EMPTY_POT = "EMPTY_POT"
REASON_NO_STANDINGS = "NO_STANDINGS"

CLASSIFICATION_ASSESSED = "ASSESSED"
CLASSIFICATION_NO_LOSER = "NO_LOSER"


@dataclass(frozen=True)
class SkunkAssessment:
    league_id: int
    season: int
    week: int
    classification: str
    largest_margin: float | None
    assessed: tuple[tuple[int, int], ...]   # (team_id, cents), canonical order
    total_cents: int


@dataclass(frozen=True)
class SkunkDistribution:
    league_id: int
    season: int
    pot_cents: int
    winners: tuple[tuple[int, int], ...]    # (team_id, cents)
    top_points_for: float | None


# ── The canonical remainder split ─────────────────────────────────────────────

def split_by_canonical_id(total_cents: int,
                          team_ids) -> dict[int, int]:
    """Divide `total_cents` across `team_ids`, canonical id ascending.

        base      = total // n
        remainder = total %  n
        the first `remainder` ids by ASCENDING canonical id get one extra cent

    Identical in shape to POR §6.3's tied-payout rule, and deliberately so: one
    remainder convention across the whole product means a reader who has learned
    it once can predict every split. Conservation is exact —
    base * n + remainder == total — so no cent is invented or dropped.
    """
    ordered = sorted(team_ids)
    n = len(ordered)
    if n == 0:
        raise SkunkError("EMPTY_SPLIT", "cannot split across zero GMs")
    base, remainder = divmod(total_cents, n)
    out = {team_id: base for team_id in ordered}
    for team_id in ordered[:remainder]:
        out[team_id] += 1
    return out


# ── Weekly assessment ─────────────────────────────────────────────────────────

def determine_skunk_losers(db, *, league_id: int, week: int):
    """The GM(s) with the largest margin of defeat, from finalized matchups.

    Returns (loser_team_ids, largest_margin). An empty tuple with margin None
    means every matchup tied — a real result, not an error.

    A matchup whose `finalized_at` is NULL is not a final result and raises
    RESULTS_NOT_READY. Treating it as 0-0 would manufacture a tie and could
    assess the wrong GM, or silently close the week on a game still in play.
    """
    from db.schema import Matchup

    matchups = (db.query(Matchup)
                .filter(Matchup.league_id == league_id, Matchup.week == week)
                .order_by(Matchup.id).all())
    if not matchups:
        raise SkunkError(
            REASON_RESULTS_NOT_READY,
            f"league {league_id} week {week} has no matchups recorded; "
            f"refusing to assess Skunk against an absent field.")

    worst_margin = None
    losers: list[int] = []
    for m in matchups:
        # FINALITY IS `finalized_at`, AND NOTHING ELSE (owner ruling, S5-P2).
        # Not the score — home_score/away_score are NOT NULL, so an unplayed
        # game reads 0.0-0.0 and is indistinguishable from a genuine tie by
        # score alone, which would collapse RESULTS_NOT_READY into NO_LOSER and
        # silently forfeit the league's Skunk for the week. Not refreshed_at
        # either: that means data was ingested, which is a weaker claim than
        # "this result is final" and must not be load-bearing for money.
        if m.finalized_at is None:
            raise SkunkError(
                REASON_RESULTS_NOT_READY,
                f"matchup {m.id} (league {league_id} week {week}) is not "
                f"economically final (finalized_at IS NULL). Nothing posted; "
                f"the week remains assessable once the result is declared "
                f"final.")
        if m.home_score == m.away_score:
            continue
        margin = abs(m.home_score - m.away_score)
        loser = m.home_team_id if m.home_score < m.away_score else m.away_team_id
        if worst_margin is None or margin > worst_margin:
            worst_margin, losers = margin, [loser]
        elif margin == worst_margin:
            losers.append(loser)

    return tuple(sorted(set(losers))), worst_margin


def resolve_skunk_fee_cents(db, *, league_id: int, season: int) -> int:
    """The Skunk Fee this league-season assesses. ECONCFG-WP1D.

    A FROZEN economy configuration governs; an UNCONFIGURED league-season keeps
    the historical default. A DRAFT is never read — `read_frozen` returns only
    stamped rows — so a fee a commissioner may still edit can never charge a GM.

    FAILS CLOSED ON INCONSISTENT DURABLE STATE (§38). A season whose issuance
    matches no certified legacy stop was priced by a configuration; if that
    configuration is now missing, substituting the historical $10 would assess
    a fee on a basis the season was never configured under, and the mismatch
    would be invisible in the ledger afterwards.

    THIS IS THE ONLY THING ABOUT SKUNK THAT CHANGED. The widest-margin
    determination, the regular-season boundary, the margin-tie split, the
    receivable semantics, the pot account, the event key, the idempotency and
    the season distribution are all untouched — only where the AMOUNT comes
    from.
    """
    from economy.league_economy_config import read_frozen
    from payments.economy_config import assert_consistent_configured_state

    # Raises InconsistentEconomyStateError on a vanished configuration.
    assert_consistent_configured_state(db, league_id=league_id, season=season)

    frozen = read_frozen(db, league_id=league_id, season=season)
    if frozen is not None:
        return int(frozen.skunk_fee_cents)
    return DEFAULT_SKUNK_CONTRIBUTION_CENTS


def assess_weekly_skunk(db, *, league_id: int, week: int,
                        contribution_cents: int | None = None,
                        now: datetime | None = None) -> SkunkAssessment:
    """Assess one league-week's Skunk. Does NOT commit.

    Posting and event row share the caller's transaction, so a crash before its
    commit leaves neither, and a retry collides on the deterministic
    league-week key.

    `contribution_cents` defaults to the league-season's governing fee —
    the frozen configured amount, or the historical default for an
    unconfigured season. An explicit value still overrides it, which is what
    the existing suites use to pin an exact figure; production passes none.
    """
    from db.schema import League

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise SkunkError(REASON_LEAGUE_NOT_FOUND, f"league {league_id} not found")
    season = league.season

    if contribution_cents is None:
        contribution_cents = resolve_skunk_fee_cents(
            db, league_id=league_id, season=season)

    if week >= playoff_start_week(league):
        raise SkunkError(
            REASON_NOT_REGULAR_SEASON,
            f"week {week} is postseason for league {league_id}; Skunk is a "
            f"regular-season assessment.")

    # Raises RESULTS_NOT_READY before anything is written.
    losers, margin = determine_skunk_losers(db, league_id=league_id, week=week)
    key = league_week_key(EVENT_SKUNK_ASSESSMENT, league_id, season, week)

    if not losers:
        # NO_LOSER — every matchup tied. The week IS closed: the event row makes
        # a retry a no-op, and no money moves.
        record_event(db, event_key=key, league_id=league_id, season=season,
                     week=week, event_type=EVENT_SKUNK_ASSESSMENT,
                     amount_cents=0, posting_id=None, now=now)
        return SkunkAssessment(league_id=league_id, season=season, week=week,
                               classification=CLASSIFICATION_NO_LOSER,
                               largest_margin=None, assessed=(),
                               total_cents=0)

    allocation = split_by_canonical_id(contribution_cents, losers)

    # ONE posting: every GM's obligation leg plus the single pot credit. The
    # legs sum to zero by construction, and the pot receives exactly the one
    # configured contribution however many GMs tied.
    legs = [(receivable_account(team_id), -cents)
            for team_id, cents in sorted(allocation.items())]
    legs.append((skunk_account(league_id), contribution_cents))
    posting_id = ledger_post(legs, door=DOOR_SKUNK_ASSESSMENT, session=db)

    record_event(db, event_key=key, league_id=league_id, season=season,
                 week=week, event_type=EVENT_SKUNK_ASSESSMENT,
                 amount_cents=contribution_cents, posting_id=posting_id,
                 now=now)

    return SkunkAssessment(
        league_id=league_id, season=season, week=week,
        classification=CLASSIFICATION_ASSESSED, largest_margin=margin,
        assessed=tuple(sorted(allocation.items())),
        total_cents=contribution_cents)


# ── Season distribution ───────────────────────────────────────────────────────

def season_points_for(db, *, league_id: int, league) -> dict[int, float]:
    """Cumulative REGULAR-SEASON Points For per team, from finalized matchups.

    Postseason weeks are excluded: the Skunk award is a regular-season contest,
    and including playoff scores would advantage the teams that played more
    games rather than the one that scored most across the shared schedule."""
    from db.schema import Matchup, Team

    totals = {t.id: 0.0 for t in
              db.query(Team).filter(Team.league_id == league_id).all()}
    cutoff = playoff_start_week(league)
    for m in (db.query(Matchup)
              .filter(Matchup.league_id == league_id,
                      Matchup.week < cutoff).all()):
        if m.home_score is None or m.away_score is None:
            continue
        if m.home_team_id in totals:
            totals[m.home_team_id] += float(m.home_score)
        if m.away_team_id in totals:
            totals[m.away_team_id] += float(m.away_score)
    return totals


def distribute_season_skunk(db, *, league_id: int,
                            now: datetime | None = None) -> SkunkDistribution:
    """Pay the accumulated Skunk pot to the highest regular-season Points For.

    Does NOT commit, and is deliberately a STANDALONE callable rather than being
    wired into a close sequence — S5-P3 orchestrates it. Exposing it this way
    lets its idempotency be proven in isolation, before any ordering exists to
    confound the proof.

    After a successful distribution `skunk:{league_id}` is exactly zero: the pot
    is drained in one posting whose credit legs sum to the whole balance.
    """
    from db.schema import League, Wallet

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise SkunkError(REASON_LEAGUE_NOT_FOUND, f"league {league_id} not found")
    season = league.season

    db.flush()
    pot = _balance_of_in_session(db, skunk_account(league_id))
    if pot <= 0:
        raise SkunkError(
            REASON_EMPTY_POT,
            f"skunk:{league_id} holds {pot} cents; nothing to distribute.")

    totals = season_points_for(db, league_id=league_id, league=league)
    if not totals:
        raise SkunkError(REASON_NO_STANDINGS,
                         f"league {league_id} has no teams to rank")
    best = max(totals.values())
    winners = tuple(sorted(t for t, v in totals.items() if v == best))

    for team_id in winners:
        if db.query(Wallet).filter(Wallet.team_id == team_id).first() is None:
            raise SkunkError(
                "NO_WALLET",
                f"Skunk winner {team_id} has no wallet; refusing to pay a "
                f"subset of the winners.")

    allocation = split_by_canonical_id(pot, winners)
    legs = [(skunk_account(league_id), -pot)]
    legs.extend((wallet_account(team_id), cents)
                for team_id, cents in sorted(allocation.items()))
    posting_id = ledger_post(legs, door=DOOR_SKUNK_DISTRIBUTION, session=db)

    record_event(db, event_key=league_season_key(EVENT_SKUNK_DISTRIBUTION,
                                                 league_id, season),
                 league_id=league_id, season=season,
                 event_type=EVENT_SKUNK_DISTRIBUTION, amount_cents=pot,
                 posting_id=posting_id, now=now)

    return SkunkDistribution(league_id=league_id, season=season, pot_cents=pot,
                             winners=tuple(sorted(allocation.items())),
                             top_points_for=best)