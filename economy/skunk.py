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
    EVENT_SKUNK_ASSESSMENT_CORRECTION,
    EVENT_SKUNK_ASSESSMENT_REVERSAL,
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

#: Every `economy_event` type whose posting moves a GM's Skunk obligation, and
#: therefore their FantasyStakes Score.
#:
#: ENUMERATED BY NAME, NEVER BY PREFIX — the same discipline
#: `reports/standings_read_model.py` applies to its door groupings, for the same
#: reason: a prefix test silently absorbs any event type added later, which is
#: how a non-Skunk movement ends up inside a Score without anybody editing this
#: file. WP-12's correction event types join this tuple deliberately when they
#: land, and the reversal nets against the assessment because both are here.
#: Every event family whose postings carry a GM's Skunk for FantasyStakes Score.
#:
#: ENUMERATED BY NAME, and all three are required for a corrected week to score
#: correctly (WP-12). The original assessment's negative `receivable:` leg, the
#: reversal's matching positive leg and the restatement's new negative leg all
#: belong to the same league-season Skunk family, so summing across the three
#: and negating once nets a correction to exactly the right per-GM figure —
#: with no special case, and with every posting preserved in full. Omitting the
#: reversal would leave a wrongly-skunked GM charged forever; omitting the
#: restatement would leave the correctly-skunked GM never charged at all.
SKUNK_SCORING_EVENT_TYPES: tuple[str, ...] = (
    EVENT_SKUNK_ASSESSMENT,
    EVENT_SKUNK_ASSESSMENT_REVERSAL,
    EVENT_SKUNK_ASSESSMENT_CORRECTION,
)


def skunk_pot_account(db, *, league_id: int, season: int) -> str:
    """Where this league-season's assessed Skunk accumulates (WP-5).

    ONE RESOLUTION, SHARED BY THE WRITER AND EVERY READER. Assessment,
    distribution and the Points Championship read model all call this, so the
    account a fee was posted into and the account a distribution debits cannot
    drift apart — which is the failure a second spelling would cause silently,
    leaving the fees stranded and the pot reading empty.

        RULESET_LEGACY     skunk:{league}
        RULESET_FINAL_POR  points_championship:{league}:{season}
    """
    from economy.economy_events import points_championship_account
    from ruleset import is_final_por

    if is_final_por(db, league_id=league_id, season=season):
        return points_championship_account(league_id, season)
    return skunk_account(league_id)


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
    # ── WP-5 — WHERE THE FEE LANDS IS SEASON-SCOPED UNDER THE FINAL POR ──────
    #
    # `skunk:{league}` has no season in it, so a league playing a second season
    # accumulates both seasons in one account and would distribute season one's
    # Skunk at the end of season two. `points_championship:{league}:{season}`
    # is the same pot, correctly scoped: §12 makes the Points Championship Pot
    # the Skunk ACTUALLY ASSESSED this season, which is exactly this balance.
    #
    # The GM-facing half of the posting is IDENTICAL in both eras — the same
    # `receivable:` legs, the same canonical split, the same amounts. Only the
    # pot the fee lands in changes, so no GM's obligation moves by a cent.
    legs.append((skunk_pot_account(db, league_id=league_id, season=season),
                 contribution_cents))
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


# ── Per-team season totals (FINAL POR · WP-3) ─────────────────────────────────

def skunk_fees_by_team(db, *, league_id: int, season: int) -> dict[int, int]:
    """Skunk assessed against each GM this league-season, as POSITIVE cents.

    THE THIRD TERM OF FantasyStakes Score. Final POR §8 makes the identity
    `Matchup Net + Prop Pool Net - Skunk Fees`, and this is where the subtrahend
    comes from.

    ── WHY THIS GOES THROUGH `economy_event` AND NOT THE ACCOUNT BALANCE ──────

    Reading `receivable:{team}` directly would be shorter and is WRONG on two
    independent counts, either of which alone would be disqualifying:

      1. IT IS NOT SKUNK-ONLY. `betting/shortfall_sweep.py` also posts to
         `receivable:{team}`. That path has no production caller today, so the
         balance happens to be pure Skunk — a fact about current wiring, not a
         property of the account. A score identity may not rest on one.

      2. IT IS NOT SEASON-SCOPED. `receivable_account()` is `receivable:{team}`
         with no season in it, so a league playing a second season would find
         the first season's Skunk still subtracted from the new season's Score.

    `economy_event` carries `league_id`, `season` and `posting_id` and is
    indexed on `(league_id, season)`, so joining through it answers exactly the
    question asked: what did THIS league-season's Skunk machinery post against
    this GM.

    ── PER-TEAM ATTRIBUTION COMES FROM THE POSTING, NOT THE EVENT ────────────

    A Skunk assessment event is LEAGUE-WEEK scoped: `team_id` is NULL on it and
    `amount_cents` is the whole weekly fee. The per-GM split lives in the
    posting's `receivable:` legs, which is also what makes a tied week report
    2.5 and 2.5 rather than 5 against each — the split the engine actually made.

    ── SIGN, AND WHY A CORRECTION NETS FOR FREE ─────────────────────────────

    Legs are summed as posted and NEGATED once. An assessment posts a negative
    `receivable:` leg, so it contributes positively here. A WP-12 correction
    reversal posts the matching positive leg under its own door against the same
    league-season event family, so it contributes negatively and the two net —
    with no special case, and with both postings preserved in full.

    Returns a dict with an entry for every team that has any Skunk history this
    league-season. A GM never skunked is simply absent; callers read 0.
    """
    from sqlalchemy import text

    db.flush()
    # EXPLICIT PLACEHOLDERS, one per event type — the same shape
    # `reports/standings_read_model.py::_door_net_cents` uses for its door list,
    # and for the same reason: an `IN :tuple` bind is dialect-dependent and
    # expands differently under SQLite and PostgreSQL.
    placeholders = ", ".join(f":e{i}" for i in range(len(SKUNK_SCORING_EVENT_TYPES)))
    params: dict[str, object] = {
        f"e{i}": t for i, t in enumerate(SKUNK_SCORING_EVENT_TYPES)}
    params.update({"league_id": league_id, "season": season})
    # ── THE POSTING ID IS NORMALISED ON BOTH SIDES, AND IT HAS TO BE ─────────
    #
    # `economy_event.posting_id` and `ledger_entries.posting_id` are both
    # declared `Uuid`, and on PostgreSQL both are native `uuid` — a plain
    # equality join works there. ON SQLITE THEY DO NOT MATCH:
    #
    #   ledger_entries   'e4441c39d13144ea9d7ebb61c75ae271'   (ORM insert)
    #   economy_event    'e4441c39-d131-44ea-9d7e-bb61c75ae271'
    #
    # because `economy_events.record_event` inserts through RAW SQL with
    # `str(posting_id)`, which bypasses the `Uuid` type's own serialisation,
    # while `ledger.post` inserts through the ORM and gets the dashless form.
    #
    # MEASURED, NOT ASSUMED: a plain equality join over that pair returns zero
    # rows on SQLite and every row on PostgreSQL. Nothing had ever joined these
    # two tables before, so the divergence had never surfaced.
    #
    # THE WRITE FORMAT IS DELIBERATELY LEFT ALONE. "Fixing" `record_event` to
    # insert a normalised value would orphan every economy_event row already
    # written on a SQLite deployment, which is a far worse trade than
    # normalising at read time. Stripping dashes and lowercasing gives the same
    # answer on both dialects and on rows written by either path.
    norm = "REPLACE(LOWER(CAST({0}.posting_id AS TEXT)), '-', '')"
    rows = db.execute(text(
        "SELECT le.account, COALESCE(SUM(le.amount_cents), 0) "
        "FROM ledger_entries le "
        f"JOIN economy_event ev ON {norm.format('ev')} = {norm.format('le')} "
        "WHERE ev.league_id = :league_id "
        "  AND ev.season = :season "
        f"  AND ev.event_type IN ({placeholders}) "
        "  AND le.account LIKE 'receivable:%' "
        "GROUP BY le.account"), params).fetchall()

    totals: dict[int, int] = {}
    for account, amount in rows:
        try:
            team_id = int(str(account).split(":", 1)[1])
        except (IndexError, ValueError):
            # An account this module did not write cannot be attributed to a GM,
            # and guessing would put a number on a fact nobody recorded.
            continue
        total = -int(amount or 0)
        if total:
            totals[team_id] = total
    return totals


def cumulative_skunk_fees_cents(db, *, league_id: int, season: int,
                                team_id: int) -> int:
    """One GM's Skunk total for a league-season, as positive cents.

    A thin read over `skunk_fees_by_team` so a single-GM caller and the
    standings sweep cannot drift: there is one query shape and one sign
    convention, and both live in one place.
    """
    return skunk_fees_by_team(
        db, league_id=league_id, season=season).get(team_id, 0)


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
    """Pay the accumulated Skunk pot. LEGACY ARITHMETIC; delegates under the Final POR.

    LEGACY: the whole pot to the highest regular-season Points For, split evenly
    among a tied lead. FINAL POR (WP-9, §12): delegated to
    `economy.points_championship.distribute`, which pays it 60/30/10 with the
    dead-heat rule after the regular season is final. The return shape is the
    same either way, so every existing caller is unchanged.

    Does NOT commit, and is deliberately a STANDALONE callable rather than being
    wired into a close sequence — S5-P3 orchestrates it. Exposing it this way
    lets its idempotency be proven in isolation, before any ordering exists to
    confound the proof.

    After a successful distribution the season's Skunk pot is exactly zero: it
    is drained in one posting whose credit legs sum to the whole balance. WHICH
    account that is depends on the era — `skunk_pot_account` decides, and both
    the assessment above and this distribution ask it, so the account fees were
    posted into and the account this debits cannot drift apart.
    """
    from db.schema import League, Wallet

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise SkunkError(REASON_LEAGUE_NOT_FOUND, f"league {league_id} not found")
    season = league.season

    # ── FINAL POR · WP-9 — THIS IS NOT A SKUNK AWARD ANY MORE ───────────────
    #
    # §12 turns the Skunk pot into the Regular-Season Points Championship: a
    # real three-place championship paid 60/30/10 under the one canonical
    # split, with the dead-heat rule, settling when the regular season is
    # final. Everything about it that differs from the legacy award lives in
    # `economy.points_championship`; delegating rather than branching inline
    # keeps this function's legacy arithmetic byte-identical and keeps the
    # championship's own refusals (no championship, not final, empty pot)
    # readable as its own reason codes rather than as Skunk ones.
    #
    # BOTH ERAS CLAIM THE SAME LEAGUE-SEASON EVENT KEY, deliberately. A
    # league-season pays its Points pillar exactly once, whichever era's
    # arithmetic did it; two keys would let a season that somehow reached both
    # paths pay twice.
    from ruleset import is_final_por as _is_final_por

    if _is_final_por(db, league_id=league_id, season=season):
        from economy.points_championship import distribute as _distribute_points

        result = _distribute_points(db, league_id=league_id, season=season,
                                    now=now)
        return SkunkDistribution(
            league_id=league_id, season=season, pot_cents=result.pot_cents,
            winners=tuple((team_id, amount)
                          for team_id, _place, amount, _pf in result.placements
                          if amount > 0),
            top_points_for=max((pf for _t, _p, _a, pf in result.placements),
                               default=None))

    db.flush()
    pot_account = skunk_pot_account(db, league_id=league_id, season=season)
    pot = _balance_of_in_session(db, pot_account)
    if pot <= 0:
        raise SkunkError(
            REASON_EMPTY_POT,
            f"{pot_account} holds {pot} cents; nothing to distribute.")

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
    legs = [(pot_account, -pot)]
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