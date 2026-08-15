"""
economy/season_allocation.py — B2 season allocation (money path).

Replaces the Stripe-mediated buy-in with a commissioner-activated, whole-
league allocation. Activating a league writes one SeasonAllocation row and
one three-leg ledger posting per team, all inside ONE transaction with ONE
top-level commit.

SEASON AUTHORITY
    The allocation season is config.ALLOCATION_SEASON, referenced explicitly
    at every write, every query and every state-machine lookup — no alias, no
    local rebinding, so the authority is visible at each site. Never from a
    request body, never from the calendar year, never from an unqualified row
    lookup.

    It is deliberately NOT config.CURRENT_SEASON: that constant is the
    projection-data year, pinned to 2025 until 2026 projections are seeded,
    and is consumed by five engines that must keep reading 2025. Allocation
    season is a separate concept with its own setting.

TRANSACTION
    Every SeasonAllocation insert and every ledger.post() in one activation
    runs against THE SAME session inside ONE enclosing transaction.
    ledger.post() is always given session=db explicitly — omitting it would
    make post() open its own SessionLocal and commit internally, placing the
    postings outside this transaction and destroying the rollback guarantee.
    Any uniqueness, validation or posting error rolls back every allocation
    row AND every ledger entry from that activation; no partial state remains.

TRANSACTION OWNERSHIP (decided, not open)
    activate_season_allocation() TAKES OWNERSHIP of the supplied session's
    transaction. It commits on the create path and rolls back on every other
    terminal path — replay, every domain refusal, and every unexpected error.
    No caller may pass a session carrying uncommitted work it expects to
    survive this call or to control itself.

COMMIT COUNT (decided)
    At most one commit: exactly one on the create path, zero on the replay
    path, zero on every error path.

SERIALIZATION (B6 Group B)
    The FIRST statement of an activation takes the target League row with
    SELECT ... FOR NO KEY UPDATE, before any state is read and before any
    write. That row lock — not a unique-index violation — is what makes
    concurrent activations of one league deterministic. The choice of FOR NO
    KEY UPDATE over FOR UPDATE is deliberate and measured; see the lock site.

    Two overlapping activations resolve as: the winner holds the lock, reads
    empty state, writes the config row and every allocation row, and commits
    once; the loser BLOCKS on the League row, and when the winner commits and
    the lock is granted, the loser re-reads and takes the clean replay path.
    Nothing is written by the loser, nothing is posted, and no database
    exception is raised.

    This is also the lock B6 §6.4 requires of every League-authority writer and
    of the season-close writer, taken in the same position. Activation takes
    ONLY this lock and takes it FIRST, so it cannot participate in a lock
    cycle: the approval path's order is request row -> allocation row -> League
    row, and the one apparent inversion is not constructible, because approval
    can only lock an EXISTING allocation row for a league-season while
    activation only inserts when NO allocation row exists for that
    league-season. The two write sets are mutually exclusive on the same key.

ISOLATION (decided)
    The caller's isolation level is inherited deliberately. READ COMMITTED is
    RETAINED ON PURPOSE, and under the League row lock it is LOAD-BEARING, not
    merely acceptable: READ COMMITTED takes a FRESH SNAPSHOT PER STATEMENT, so
    the unblocked loser's subsequent reads see the winner's committed rows and
    it resolves to a clean replay. Elevating to REPEATABLE READ would make
    behavior strictly worse: the loser's snapshot would pin before the winner
    commits, so it would still see no rows, take the create path, and die on
    the unique index — converting a benign replay into an IntegrityError. It
    is also not reliably settable at that point, because
    resolve_allocation_terms() has already opened the transaction.

STATE MACHINE — FIVE states, evaluated inside the transaction before any write
    Evaluated over the PAIR (allocation rows, frozen config row). Both are read
    under the League lock, in one read phase, before any branch.

    neither exists     -> create BOTH atomically: one config row + N allocation
                          rows, one transaction, one commit
    complete + match   -> return the existing result; nothing posted, nothing
                          mutated. "Match" means the allocation tuple AND the
                          frozen multiplier both agree
    partial            -> PartialAllocationError; no mutation. THREE distinct
                          corruptions reach it: an incomplete allocation set;
                          allocation rows with no config row; a config row with
                          no allocation rows or an incomplete set
    conflicting        -> ConflictingAllocationError; no mutation. Allocation
                          tuple mismatch OR multiplier mismatch
    no teams           -> NoTeamsError; no mutation

    This state machine IS the idempotency mechanism.
    uq_season_allocation_league_team_season and uq_lstc_league_season are FINAL
    DEFENSE-IN-DEPTH GUARDS only — their violation is never used as the
    idempotency path.

    WHY THE MULTIPLIER MUST JOIN THE COMPARISON (B6 §2.5). Without it, a
    commissioner who edits League.topoff_cap_multiplier_bps and re-runs
    activation gets a FALSE REPLAY: the allocation rows still "match",
    activation reports success, and the stale frozen multiplier silently
    governs the whole season. That single omission would defeat the entire
    freeze model, so the multiplier is compared on every replay evaluation.

    MISSING FROZEN STATE IS NEVER SILENTLY REPAIRED. A config row without
    allocations, or allocations without a config row, is refused as partial —
    detected on the READ side, before the create branch, so it surfaces as a
    domain refusal rather than as a raw IntegrityError from the unique index.
    Completing half-written frozen state would paper over whatever produced it.

    OBSERVED RACE BEHAVIOR (evidence, not aspiration): the concurrent
    replay-loser path is now DETERMINISTIC under the League row lock — the
    loser blocks on the lock, re-reads committed state, and returns
    created=False. It is proven under genuine overlap by the Group B suite,
    which observes the block through pg_stat_activity/pg_locks rather than by
    timing. The UNIQUE-CONSTRAINT path remains reachable and remains proven by
    scenario (m1) of test_season_allocation_pg.py, whose holder writes an
    allocation row DIRECTLY and therefore never takes the League lock: a raw
    write that bypasses this seam is corruption, not a concurrent activation,
    and the unique index must stay live against it.

CONSERVATION
    Each posting is exactly three legs summing to zero in integer cents:
        ("season_issuance:{league_id}:{season}", -stop.buyin_cents)
        (f"min_reserve:{team_id}",                stop.min_reserve_cents)
        (f"reserve:{team_id}",                    stop.reserve_cents)
    Zero-sum is guaranteed upstream by payments/economy_config.py's
    ResolvedAllocationTerms, whose buyin_cents IS min_reserve_cents +
    reserve_cents by construction on BOTH paths — the legacy stop's import-time
    invariant, and the configured formula's own definition. It is never
    recomputed or rounded here. season_issuance:* is exempt from the ledger's
    non-negative balance guard UNDER THIS DOOR ONLY, so debiting it from zero is
    legal.

    ECONCFG-WP1D — WHERE THE THREE AMOUNTS COME FROM. A league-season with a
    FROZEN economy configuration is issued
        min_reserve = weekly_bet_minimum x regular_season_week_count
        reserve     = championship_contribution
    and an UNCONFIGURED one keeps the historical fixed stop, unchanged and
    un-backfilled. The posting shape, the ledger door, the account names and the
    SeasonAllocation snapshot are identical on both paths; only the numbers
    differ, and the row records whichever was actually issued.
    Wallet receives no leg: S5-R2 supersedes the model that put the Weekly
    Minimum allocation into Wallet.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from db.schema import League, LeagueSeasonTopoffConfig, SeasonAllocation, Team
# ECONCFG-F1 — the activation freeze. Imported for the audit row only; it
# supplies no number to any posting in this module.
from economy.league_economy_config import freeze_economy_config
from payments.economy_config import (
    ResolvedAllocationTerms, resolve_allocation_terms,
)
from economy.economy_events import (
    EVENT_OPENING_ALLOCATION,
    gm_season_key,
    season_issuance_account,
    min_reserve_account,
    record_event,
    reserve_account,
)
from ledger.ledger import SEASON_ALLOCATION_DOOR, post as ledger_post

#: Re-exported for callers/tests; the literal lives in ledger.ledger
#: beside the funded-balance exemption it activates.
DOOR = SEASON_ALLOCATION_DOOR


# ── Errors ────────────────────────────────────────────────────────────────────

class SeasonAllocationError(ValueError):
    """Base for every season-allocation domain refusal. Subclasses are
    distinct types so tests assert on type, never on message text."""


class PartialAllocationError(SeasonAllocationError):
    """The league already has SOME allocation rows for this season but not a
    complete set — some teams have a row and some do not, or a row exists for
    a team that is not in the league. Inconsistent: refused without mutation.
    Never repaired automatically; a partial set means something already went
    wrong and silently completing it would paper over that."""


class ConflictingAllocationError(SeasonAllocationError):
    """An existing row's stored snapshot disagrees with the league's current
    economy stop. Refused without mutation — reposting against a different
    stop would split one season's allocation across two stops."""


class NoTeamsError(SeasonAllocationError):
    """The league has no teams, so there is nothing to allocate. Refused
    rather than recorded as a vacuously 'complete' activation, which would
    permanently poison the state machine: every team added later would read
    as partial and could never be allocated."""


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SeasonAllocationResult:
    """What one activation (or one idempotent replay) produced.

    created distinguishes the two success paths: True means this call wrote
    the rows and postings; False means a complete, matching allocation already
    existed and this call wrote nothing at all. On the replay path posting_ids
    is empty — not because the postings are unknown, but because this call
    made none.
    """
    league_id:         int
    season:            int
    team_ids:          tuple[int, ...]
    buyin_cents:       int
    min_reserve_cents:      int
    reserve_cents:     int
    total_buyin_cents: int
    created:           bool
    posting_ids:       tuple[uuid.UUID, ...]


def _result(
    league_id: int,
    team_ids: tuple[int, ...],
    stop: ResolvedAllocationTerms,
    created: bool,
    posting_ids: tuple[uuid.UUID, ...],
) -> SeasonAllocationResult:
    return SeasonAllocationResult(
        league_id         = league_id,
        season            = config.ALLOCATION_SEASON,
        team_ids          = team_ids,
        buyin_cents       = stop.buyin_cents,
        min_reserve_cents      = stop.min_reserve_cents,
        reserve_cents     = stop.reserve_cents,
        total_buyin_cents = stop.buyin_cents * len(team_ids),
        created           = created,
        posting_ids       = posting_ids,
    )


# ── Activation ────────────────────────────────────────────────────────────────

def activate_season_allocation(league_id: int, db: Session) -> SeasonAllocationResult:
    """
    Activate the season allocation for every team in `league_id`, for
    config.ALLOCATION_SEASON. Whole-league operation: all teams or none.

    Season is NOT a parameter — it is read from config so no caller can
    activate a season other than the live one.

    Activation writes TWO kinds of frozen state in one transaction (B6 §2.4):
    exactly one league_season_topoff_config row carrying the cap multiplier
    copied from League.topoff_cap_multiplier_bps, and one SeasonAllocation row
    per team. All or none — a failure discards both.

    Returns a SeasonAllocationResult. The frozen multiplier is deliberately NOT
    on that result: league_season_topoff_config is its single authoritative
    source, and approval reads it from that row and nowhere else (§2.6,
    invariant 29). Callers needing the frozen value query the table.

    Raises PartialAllocationError, ConflictingAllocationError or NoTeamsError
    on an inconsistent league, having mutated nothing. On any error — domain,
    uniqueness or posting — the transaction is rolled back, so no config row,
    no allocation row and no ledger entry from this call survives.

    The caller supplies the session; this function owns the transaction on it
    and issues the single commit. The target League row is locked FOR NO KEY
    UPDATE for the whole call, so concurrent activations of one league
    serialize and the loser returns a clean replay rather than a database error.
    """
    try:
        # THE SERIALIZATION POINT (B6 §6.4). Taken FIRST, before any state read
        # and before any write, so two concurrent activations of one league can
        # never both read empty state. The loser blocks here; when the winner
        # commits, the loser's later statements take fresh READ COMMITTED
        # snapshots, see the committed rows, and resolve to a clean replay
        # instead of colliding on a unique index. See SERIALIZATION above.
        #
        # A league_id that does not exist locks nothing and is NOT an error
        # here: the teams query below returns empty and NoTeamsError is raised,
        # exactly as before this lock existed. Because teams.league_id is a
        # foreign key to leagues.id, locked_league is necessarily non-None on
        # every path that survives that check.
        #
        # key_share=True emits FOR NO KEY UPDATE, NOT FOR UPDATE, and the
        # distinction is LOAD-BEARING (measured, see below). Inserting any row
        # whose foreign key references this league — a SeasonAllocation row, a
        # Team, anything — makes PostgreSQL take FOR KEY SHARE on the leagues
        # tuple to hold the referenced key stable. FOR UPDATE conflicts with
        # FOR KEY SHARE; FOR NO KEY UPDATE does not. Measured on PostgreSQL 16:
        #
        #   holder                     contender FOR UPDATE   contender FOR NO KEY UPDATE
        #   FK child INSERT            BLOCKS                 proceeds
        #   FOR NO KEY UPDATE          BLOCKS                 BLOCKS
        #   FOR UPDATE                 BLOCKS                 BLOCKS
        #
        # So FOR NO KEY UPDATE serializes precisely what must serialize —
        # activation against activation, and activation against the FOR UPDATE
        # taken by B6 §6.4's authority and season-close writers — while NOT
        # blocking on an unrelated in-flight insert that merely references this
        # league. FOR UPDATE here would additionally make the allocation unique
        # index unreachable, and with it untestable: scenario (m1) of
        # test_season_allocation_pg.py proves that final race guard fires by
        # holding an uncommitted raw allocation INSERT, and under FOR UPDATE the
        # contender would block on this lock instead and never reach the index.
        # A defense-in-depth guard nothing can demonstrate is not a guard.
        locked_league = (
            db.query(League)
            .filter(League.id == league_id)
            .with_for_update(key_share=True)
            .first()
        )

        # order_by(Team.id) is LOAD-BEARING, not tidiness (R-8). It fixes the
        # order in which concurrent activations of the same league insert
        # rows, so they acquire the unique index's locks in the SAME order and
        # QUEUE behind one another instead of deadlocking. Remove it and two
        # overlapping activations can each hold the lock the other needs, and
        # Postgres will abort one with a deadlock rather than the clean
        # IntegrityError the race guard is designed to produce. Do not drop
        # or reorder this clause. The League row lock above does not supersede
        # it: a raw allocation INSERT that bypasses this seam never takes that
        # lock, so the unique index — and therefore this ordering — is still
        # the guard that runs. Scenario (m1) of test_season_allocation_pg.py
        # exercises exactly that arrangement.
        teams = (
            db.query(Team)
            .filter(Team.league_id == league_id)
            .order_by(Team.id)
            .all()
        )
        team_ids = tuple(t.id for t in teams)
        if not team_ids:
            raise NoTeamsError(
                f"League {league_id} has no teams — nothing to allocate for "
                f"season {config.ALLOCATION_SEASON}. Refusing to record an "
                f"empty activation."
            )

        # ── ECONCFG-WP1D — FREEZE FIRST, THEN RESOLVE, THEN ISSUE ───────────
        #
        # THE ORDER IS THE SAFETY PROPERTY. No Credit may post from an editable
        # draft, so the configuration is stamped immutable BEFORE anything reads
        # it as an issuance basis. `freeze_economy_config` is a no-op returning
        # None for an UNCONFIGURED league-season — which is every pre-ECONCFG-F1
        # season — and those fall through to the legacy fixed stop unchanged.
        #
        # Both calls sit under the League row lock taken above, so a concurrent
        # activation cannot freeze one configuration and issue against another.
        freeze_economy_config(db, league_id=league_id,
                              season=config.ALLOCATION_SEASON)

        # ONE RESOLUTION, ONE FORMULA. `stop` keeps its name because every
        # reader below consumes exactly the three amounts it always did —
        # buyin_cents, min_reserve_cents, reserve_cents — and the posting shape,
        # the ledger door and the SeasonAllocation snapshot are untouched. What
        # changed is only WHERE those three numbers come from.
        stop = resolve_allocation_terms(db, league_id=league_id,
                                        season=config.ALLOCATION_SEASON)

        # THE STATE READ. Both halves of the frozen state are read here, in one
        # phase, before any branch — so every corruption is detected on the READ
        # side and surfaces as a domain refusal, never as a raw IntegrityError
        # from a unique index discovered mid-write.
        existing = (
            db.query(SeasonAllocation)
            .filter(
                SeasonAllocation.league_id == league_id,
                SeasonAllocation.season    == config.ALLOCATION_SEASON,
            )
            .all()
        )
        frozen = (
            db.query(LeagueSeasonTopoffConfig)
            .filter(
                LeagueSeasonTopoffConfig.league_id == league_id,
                LeagueSeasonTopoffConfig.season    == config.ALLOCATION_SEASON,
            )
            .one_or_none()
        )
        # one_or_none() rather than first(): uq_lstc_league_season makes a second
        # row impossible, so if one ever appears it is corruption of exactly the
        # kind this module refuses to paper over, and MultipleResultsFound must
        # propagate rather than be silently narrowed to the first row.

        # The multiplier to freeze, and the value a replay is compared against,
        # read from the LOCKED League row so it cannot change under us between
        # the comparison and the write.
        league_multiplier_bps = locked_league.topoff_cap_multiplier_bps

        if existing or frozen is not None:
            # ── Already-activated paths. None of these writes anything. ──
            by_team = {row.team_id: row for row in existing}
            present = set(by_team)
            expected = set(team_ids)

            # Covers BOTH an incomplete allocation set AND a config row standing
            # alone with no allocation rows at all (present == empty set). The
            # latter must be caught HERE, on the read side: letting it fall
            # through to the create branch would insert a duplicate config row
            # and die on uq_lstc_league_season, turning a diagnosable corruption
            # into a raw database exception.
            if present != expected:
                missing = sorted(expected - present)
                extra   = sorted(present - expected)
                raise PartialAllocationError(
                    f"League {league_id} has an INCOMPLETE season allocation for "
                    f"season {config.ALLOCATION_SEASON}: {len(present)} of "
                    f"{len(expected)} league "
                    f"teams have rows. Teams present: {sorted(present)}. "
                    f"Teams absent: {missing}. "
                    f"Rows for teams not in this league: {extra}. "
                    f"Frozen top-off config row present: {frozen is not None}. "
                    f"Refusing to mutate — a partial allocation means something "
                    f"already went wrong and must be investigated, not completed."
                )

            # A complete allocation set with NO frozen multiplier. The season is
            # half-activated: caps cannot be computed, so approval would abort on
            # every request (§7.3 outcome 4). Refused as partial rather than
            # repaired — writing the config row now would freeze TODAY's
            # League.topoff_cap_multiplier_bps onto a season that was activated
            # under an unknown one, silently inventing the very fact the freeze
            # exists to preserve.
            if frozen is None:
                raise PartialAllocationError(
                    f"League {league_id} has a COMPLETE season-"
                    f"{config.ALLOCATION_SEASON} allocation "
                    f"({len(present)} teams) but NO frozen top-off multiplier "
                    f"row in league_season_topoff_config. The season is "
                    f"half-activated and no cap can be computed. Refusing to "
                    f"mutate — writing the snapshot now would freeze the "
                    f"CURRENT League.topoff_cap_multiplier_bps "
                    f"({league_multiplier_bps}) onto a season activated under "
                    f"an unknown one. Investigate, do not complete."
                )

            conflicts = [
                (
                    row.team_id,
                    (row.buyin_cents, row.min_reserve_cents, row.reserve_cents),
                )
                for row in existing
                if (row.buyin_cents, row.min_reserve_cents, row.reserve_cents)
                != (stop.buyin_cents, stop.min_reserve_cents, stop.reserve_cents)
            ]
            if conflicts:
                raise ConflictingAllocationError(
                    f"League {league_id}'s stored "
                    f"season-{config.ALLOCATION_SEASON} allocation "
                    f"disagrees with its current economy stop. Current stop "
                    f"(buyin, wallet, reserve) = "
                    f"({stop.buyin_cents}, {stop.min_reserve_cents}, {stop.reserve_cents}). "
                    f"Stored, by team: {conflicts}. Refusing to mutate — "
                    f"reposting would split one season across two stops."
                )

            # THE MULTIPLIER IS PART OF THE COMPARISON TUPLE (B6 §2.5). Without
            # this check a commissioner could edit League.topoff_cap_multiplier_bps,
            # re-run activation, receive a successful "replay", and have the
            # STALE frozen multiplier govern the season silently. That is the
            # single omission that would defeat the whole freeze model.
            if frozen.topoff_cap_multiplier_bps != league_multiplier_bps:
                raise ConflictingAllocationError(
                    f"League {league_id}'s FROZEN season-"
                    f"{config.ALLOCATION_SEASON} top-off multiplier "
                    f"({frozen.topoff_cap_multiplier_bps} bps) disagrees with the "
                    f"league's current League.topoff_cap_multiplier_bps "
                    f"({league_multiplier_bps} bps). The frozen value is "
                    f"authoritative for this season and is never updated in "
                    f"place. Refusing to mutate — treating this as a replay "
                    f"would report success while the stale multiplier silently "
                    f"governed the season."
                )

            # Complete and matching, in BOTH the allocation tuple and the frozen
            # multiplier — the idempotent replay. Nothing posted, nothing
            # mutated. Roll back so this branch leaves the session in the SAME
            # terminal posture as every other non-create path (R-2): without it
            # the function would have three postures on one session — commit,
            # rollback, and neither — and a caller could not write correct code
            # against that. Only the read transaction opened by the checks above
            # is discarded; there is nothing else to lose.
            db.rollback()
            return _result(league_id, team_ids, stop, created=False, posting_ids=())

        # ── Neither exists: create BOTH atomically. ──
        # The config row goes first, following §2.4's enumeration. Ordering is no
        # longer load-bearing for concurrency — the League lock above is the
        # serialization point — so uq_lstc_league_season, like the allocation
        # unique index, is defense in depth that no activation reaches.
        db.add(LeagueSeasonTopoffConfig(
            league_id                 = league_id,
            season                    = config.ALLOCATION_SEASON,
            topoff_cap_multiplier_bps = league_multiplier_bps,
        ))

        posting_ids: list[uuid.UUID] = []
        for team_id in team_ids:
            db.add(SeasonAllocation(
                league_id     = league_id,
                team_id       = team_id,
                season        = config.ALLOCATION_SEASON,
                buyin_cents   = stop.buyin_cents,
                min_reserve_cents  = stop.min_reserve_cents,
                reserve_cents = stop.reserve_cents,
            ))
            # Three legs, integer cents, summing to zero by economy_config's
            # import-time invariant. session=db keeps these entries inside THIS
            # transaction; post() does not commit on the session-provided path.
            # S5-R2 / S5-P1 owner ruling — THE OPENING ALLOCATION SHAPE.
            #
            #   season_issuance:{league}:{season}  -22000
            #   min_reserve:{team}                 +14000
            #   reserve:{team}                      +8000
            #   wallet:{team}                           0   (NO leg at all)
            #
            # WALLET GETS NO LEG, not a zero-amount one. A zero leg would be a
            # posting that moved nothing while claiming the Wallet participated,
            # and the obsolete model — 140 straight into Wallet — is superseded,
            # not merely reduced. There is nothing to grandfather.
            #
            # THE SOURCE IS season_issuance, NEVER bab_issuance. That namespace
            # is reserved to the canonical approved Top-Off door by an accepted
            # B6 invariant which names this very door as one that must NOT be
            # exempt on it. The two obligations stay separately derivable from
            # posted state, which is what S5-P2/P3 Current Settle needs.
            #
            # Zero-sum holds by economy_config's import-time invariant
            # min_reserve_cents + reserve_cents == buyin_cents; it is never
            # recomputed or rounded here.
            posting_ids.append(ledger_post(
                [
                    (season_issuance_account(league_id, config.ALLOCATION_SEASON),
                     -stop.buyin_cents),
                    (min_reserve_account(team_id), stop.min_reserve_cents),
                    (reserve_account(team_id),     stop.reserve_cents),
                ],
                door    = SEASON_ALLOCATION_DOOR,
                session = db,
            ))

            # The per-GM season obligation, recorded in THIS transaction. Its
            # deterministic key makes a replay collide rather than double-issue;
            # the state machine above is the primary idempotency mechanism and
            # this is the structural backstop that also covers a caller reaching
            # the create branch by some path the state read did not cover.
            record_event(
                db,
                event_key = gm_season_key(EVENT_OPENING_ALLOCATION, league_id,
                                          config.ALLOCATION_SEASON, team_id),
                league_id = league_id,
                season    = config.ALLOCATION_SEASON,
                team_id   = team_id,
                event_type= EVENT_OPENING_ALLOCATION,
                amount_cents = stop.buyin_cents,
                posting_id   = posting_ids[-1],
            )

        # Force the INSERTs (and therefore both final race guards,
        # uq_lstc_league_season and uq_season_allocation_league_team_season) to
        # be evaluated inside this transaction rather than at commit time.
        db.flush()

        # THE single top-level commit — reached only after every row and every
        # posting for every team has succeeded.
        db.commit()

        return _result(league_id, team_ids, stop, created=True, posting_ids=tuple(posting_ids))

    except Exception:
        # Covers domain refusals (which wrote nothing anyway), IntegrityError
        # from either race guard, and any ledger posting error. The config row,
        # every allocation row and every ledger entry from this call are
        # discarded together, and the League lock releases with them.
        db.rollback()
        raise
