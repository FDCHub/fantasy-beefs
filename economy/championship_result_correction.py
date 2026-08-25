"""RC2 — governed authoritative restatement of an eligible FantasyStakes contest.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT
---------------------------------------------
A correction is a DISTINCT governed operation, not a second ordinary settlement.
Ordinary settlement stays exactly-once: `week_settlements` still refuses a
completed week, `PoolInstance.settled` still short-circuits to a replay, and the
ledger's once-only guard still refuses a `wager_settled` posting against a
drained escrow. None of that is reopened here, and this module never calls those
engines' settle paths.

Instead it computes the DIFFERENCE between the result that was settled and the
result that is authoritative, and posts exactly that difference under its own
door. Stakes are never re-funded and pots are never re-paid: escrow is not
touched at all, because escrow was already drained by the original settlement.

    delta(team) = payout_under_corrected_result − payout_actually_received

The deltas sum to zero by construction — both results distribute the same pot —
so the correction is one balanced double-entry posting.

THE CALLER SUPPLIES A RESULT, NEVER AN AMOUNT
---------------------------------------------
`CorrectedVersusResult` names a winner or a push. `CorrectedPoolResult` names the
winning GM set. The Credits are derived here from posted ledger state and, for
pools, from `betting.pool_settlement.allocate_even_split` — the same certified
§6.3 allocator ordinary settlement uses, so a corrected split is cent-for-cent
what settlement would have produced had the corrected result been known.

ORDER OF OPERATIONS IS LOAD-BEARING
-----------------------------------
Eligibility, the funded field and the ALREADY-PAID refusal are all checked
BEFORE any economics are derived or posted. A championship whose pot has been
distributed refuses here with nothing written, rather than moving wallets first
and discovering the problem afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.schema import Bet, Wallet
from ledger.ledger import post as ledger_post

#: The one door under which an authoritative championship result correction
#: moves Credits. Deliberately NOT `wager_settled` or `pool_winner_distribution`:
#: a correction is not an ordinary settlement, and conflating them would make the
#: two indistinguishable in the ledger forever.
#:
#: It is equally deliberately NOT a member of `VERSUS_DOORS` / `POOL_DOORS`. The
#: championship consequence of a correction is carried by its append-only
#: correction row, which is counted exactly once by the corrected-score overlay.
#: Adding this door to those tuples as well would count the same restatement
#: twice — once from the ledger sum and once from the correction row.
DOOR_RESULT_CORRECTION = "fantasystakes_result_correction"

#: A prop pool whose original economics were NOT a governed winner distribution
#: (rollover, championship sweep, or any non-distributing resolution). RC2
#: corrects the winner-distribution class only; everything else fails closed.
REASON_POOL_NOT_CORRECTABLE = "FS_CORRECTION_POOL_CLASS_NOT_CORRECTABLE"

OUTCOME_WINNER = "winner"
OUTCOME_PUSH = "push"


@dataclass(frozen=True)
class CorrectedVersusResult:
    """The authoritative outcome of a governed GM-vs-GM matchup."""

    outcome: str                      # 'winner' | 'push'
    winner_team_id: int | None = None


@dataclass(frozen=True)
class CorrectedPoolResult:
    """The authoritative winning GM set of a governed prop-pool occurrence."""

    winner_team_ids: tuple[int, ...]


def _versus_stakes_and_payouts(db: Session, contest) -> tuple[dict, dict]:
    """(stake per team, payout already received per team) from posted state.

    STAKE is every credit ever made into that GM's `escrow:{bet_id}` — what they
    actually put at risk, however it was funded. PAYOUT is every wallet leg they
    received in the `wager_settled` postings that drained this contest's escrow,
    which is precisely what ordinary settlement paid them and nothing else.
    """
    from sqlalchemy import text

    db.flush()
    stakes: dict[int, int] = {}
    payouts: dict[int, int] = {}
    for account in contest.escrow_accounts:
        bet_id = int(account.split(":", 1)[1])
        row = (db.query(Wallet.team_id)
               .join(Bet, Bet.wallet_id == Wallet.id)
               .filter(Bet.id == bet_id).first())
        if row is None:
            continue
        team_id = int(row[0])
        staked = db.execute(text(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
            "WHERE account = :a AND amount_cents > 0"), {"a": account}).scalar()
        stakes[team_id] = stakes.get(team_id, 0) + int(staked or 0)
        payouts.setdefault(team_id, 0)

    if contest.escrow_accounts:
        acct_ph = ", ".join(f":a{i}" for i in range(len(contest.escrow_accounts)))
        params = {f"a{i}": a for i, a in enumerate(contest.escrow_accounts)}
        for team_id in list(payouts):
            params_t = dict(params, wallet=f"wallet:{team_id}")
            paid = db.execute(text(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
                "WHERE door = 'wager_settled' AND account = :wallet "
                "AND posting_id IN (SELECT posting_id FROM ledger_entries "
                f"                  WHERE account IN ({acct_ph}))"),
                params_t).scalar()
            payouts[team_id] = int(paid or 0)
    return stakes, payouts


def _versus_target(result: CorrectedVersusResult, stakes: dict) -> dict:
    """What each GM should hold from this contest under the corrected result."""
    pot = sum(stakes.values())
    if result.outcome == OUTCOME_PUSH:
        # A push returns each GM their own stake — never cross-credited, the
        # same rule `settlement_engine` applies with two independent postings.
        return dict(stakes)
    if result.outcome != OUTCOME_WINNER or result.winner_team_id is None:
        raise ValueError("corrected Versus result must name a winner or be a push")
    if int(result.winner_team_id) not in stakes:
        raise ValueError(
            f"team {result.winner_team_id} did not stake in this matchup")
    return {team_id: (pot if team_id == int(result.winner_team_id) else 0)
            for team_id in stakes}


def assert_pool_correctable(db: Session, contest) -> None:
    """Prove this occurrence's original economics were a NORMAL winner distribution.

    WHY CLASSIFICATION ALONE IS NOT ENOUGH — measured, not assumed.
    `settlement_classification` records the CENSUS outcome, not the economic
    class. `betting/pool_settlement.py:369` shows a `CLAIMS_PRESENT` occurrence
    whose winning tickets were zero being resolved through `_resolve_zero_claim`
    into a rollover or a championship sweep. Keying only on the classification
    would therefore let a swept pot be "corrected" with
    `allocate_even_split`, redistributing Credits that are no longer in
    `pool:{league}` at all.

    THE AUTHORITY IS THE DURABLE ECONOMIC-EVENT HISTORY, which is the same
    source `_replay_result` trusts for exactly this reason: it reports "what
    actually happened rather than what should have happened". An occurrence is
    correctable only when its posted economics are one `WINNER_DISTRIBUTION` and
    nothing else, and its own durable counters agree.

    RC2 SUPPORTS ONE ECONOMIC CLASS. Rollover, championship sweep and any
    non-distributing resolution FAIL CLOSED here — before any derivation, any
    posting and any audit row — rather than being silently reinterpreted.
    Extending correction to those classes is deliberately not RC2 scope.
    """
    from db.schema import PoolEconomicEvent, PoolInstance
    from betting.pool_census import CLASSIFICATION_CLAIMS_PRESENT
    from betting.pool_settlement import (
        EVENT_ROLLOVER_EXPIRY_SWEEP, EVENT_SUBJECT_ZERO_CLAIM_CHAMPIONSHIP_SWEEP,
        EVENT_SUBJECT_ZERO_CLAIM_ROLLOVER, EVENT_TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP,
        EVENT_TICKET_ZERO_WINNER_ROLLOVER, EVENT_WINNER_DISTRIBUTION,
    )
    from reports.championship_corrections import ChampionshipCorrectionError

    non_distribution = {
        EVENT_SUBJECT_ZERO_CLAIM_ROLLOVER,
        EVENT_SUBJECT_ZERO_CLAIM_CHAMPIONSHIP_SWEEP,
        EVENT_TICKET_ZERO_WINNER_ROLLOVER,
        EVENT_TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP,
        EVENT_ROLLOVER_EXPIRY_SWEEP,
    }

    instance = (db.query(PoolInstance)
                .filter(PoolInstance.id == contest.contest_ref).first())
    if instance is None:  # pragma: no cover - resolve_contest already refuses
        raise ChampionshipCorrectionError(
            REASON_POOL_NOT_CORRECTABLE,
            f"prop-pool occurrence {contest.contest_ref} not found")

    if not bool(instance.settled):
        raise ChampionshipCorrectionError(
            REASON_POOL_NOT_CORRECTABLE,
            f"prop-pool occurrence {contest.contest_ref} is not settled. There "
            f"is no authoritative result to restate; settle it first.")

    events = [e.event_type for e in
              db.query(PoolEconomicEvent)
              .filter(PoolEconomicEvent.pool_instance_id == instance.id)
              .order_by(PoolEconomicEvent.id.asc()).all()]
    blocking = sorted({e for e in events if e in non_distribution})
    if blocking:
        raise ChampionshipCorrectionError(
            REASON_POOL_NOT_CORRECTABLE,
            f"prop-pool occurrence {contest.contest_ref} resolved through "
            f"{', '.join(blocking)}, not a winner distribution. Its Credits left "
            f"through rollover or a championship sweep, so an even-split "
            f"restatement would redistribute money the pot no longer holds. RC2 "
            f"corrects winner-distribution pools only. Nothing was posted.")

    if EVENT_WINNER_DISTRIBUTION not in events:
        raise ChampionshipCorrectionError(
            REASON_POOL_NOT_CORRECTABLE,
            f"prop-pool occurrence {contest.contest_ref} has no "
            f"{EVENT_WINNER_DISTRIBUTION} economic event; it never distributed a "
            f"pot to winners and has no winner set to restate.")

    classification = instance.settlement_classification or ""
    if classification != CLASSIFICATION_CLAIMS_PRESENT:
        raise ChampionshipCorrectionError(
            REASON_POOL_NOT_CORRECTABLE,
            f"prop-pool occurrence {contest.contest_ref} carries settlement "
            f"classification {classification!r}; only "
            f"{CLASSIFICATION_CLAIMS_PRESENT!r} resolves through the governed "
            f"winner distribution that `allocate_even_split` is the correct "
            f"allocator for.")

    distributed = int(instance.distributed_cents or 0)
    pot = int(instance.pot_cents or 0)
    rolled = int(instance.rollover_cents or 0)
    if distributed <= 0 or distributed != pot or rolled:
        raise ChampionshipCorrectionError(
            REASON_POOL_NOT_CORRECTABLE,
            f"prop-pool occurrence {contest.contest_ref} reports pot={pot}, "
            f"distributed={distributed}, rollover={rolled}. A correctable "
            f"occurrence distributed its whole pot to winners and carried no "
            f"rollover.")


def _pool_payouts(db: Session, contest, league_id: int) -> tuple[int, dict]:
    """(pot distributed, cents already received per GM) for a prop-pool occurrence."""
    from sqlalchemy import text

    db.flush()
    if not contest.posting_ids:
        return 0, {}
    ph = ", ".join(f":p{i}" for i in range(len(contest.posting_ids)))
    params = {f"p{i}": p for i, p in enumerate(contest.posting_ids)}
    rows = db.execute(text(
        "SELECT account, SUM(amount_cents) FROM ledger_entries "
        "WHERE door = 'pool_winner_distribution' AND account LIKE 'wallet:%' "
        f"AND posting_id IN ({ph}) GROUP BY account"), params).fetchall()
    payouts = {int(a.split(":", 1)[1]): int(c) for a, c in rows}
    return sum(payouts.values()), payouts


def apply_result_correction(
    db: Session, *, league_id: int, competition_type: str, contest_ref: int,
    corrected_result, reason: str, source: str, correction_key: str,
    now: datetime | None = None,
):
    """Restate one eligible contest economically and record the correction.

    ONE TRANSACTION. The corrective posting and the append-only correction rows
    are written into the caller's session and committed together by the caller,
    so a failure anywhere leaves neither corrected wallets without provenance nor
    provenance claiming economics that never happened.
    """
    from reports.championship_corrections import (
        COMPETITION_PROP_POOL, COMPETITION_VERSUS,
        FantasyStakesChampionshipCorrection, CorrectionResult, CorrectionRow,
        ChampionshipCorrectionError, REASON_ALREADY_PAID, REASON_NOT_ELIGIBLE,
        REASON_TEAM_NOT_IN_FIELD, corrections_for, resolve_contest,
    )
    from economy.fantasystakes_championship_settlement import (
        FantasyStakesChampionshipDistributionRun,
    )
    from reports.championship_read_model import (
        FantasyStakesChampionshipFreeze, funded_championship_field,
    )
    from db.schema import League

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise ChampionshipCorrectionError(
            "FS_CORRECTION_CONTEST_NOT_FOUND", f"league {league_id} not found")
    season = int(league.season)

    marker = (db.query(FantasyStakesChampionshipFreeze)
              .filter(FantasyStakesChampionshipFreeze.league_id == league_id,
                      FantasyStakesChampionshipFreeze.season == season).first())
    if marker is None:
        raise ChampionshipCorrectionError(
            "FS_CORRECTION_CHAMPIONSHIP_NOT_FROZEN",
            f"league {league_id} season {season} has no frozen FantasyStakes "
            f"Championship; an eligible result needs no correction before the "
            f"freeze.")

    # ── REFUSE BEFORE ANY ECONOMICS ──────────────────────────────────────────
    # Checked first, deliberately: discovering the pot was already distributed
    # AFTER moving wallets would leave real Credits moved against a championship
    # that can never account for them, and RC2 performs no clawback.
    paid = (db.query(FantasyStakesChampionshipDistributionRun)
            .filter(FantasyStakesChampionshipDistributionRun.league_id == league_id,
                    FantasyStakesChampionshipDistributionRun.season == season)
            .one_or_none())
    if paid is not None:
        raise ChampionshipCorrectionError(
            REASON_ALREADY_PAID,
            f"league {league_id} season {season} distributed its FantasyStakes "
            f"Championship Pot at {paid.distributed_at}. No corrective economics "
            f"were derived and none were posted; this requires governed "
            f"administrative recovery.")

    # Replay: the same key returns the recorded result and posts nothing.
    already = [r for r in corrections_for(db, league_id=league_id, season=season)
               if r.correction_key == correction_key]
    if already:
        contest = resolve_contest(db, league_id=league_id,
                                  competition_type=competition_type,
                                  contest_ref=contest_ref)
        return CorrectionResult(
            league_id=league_id, season=season,
            competition_type=contest.competition_type,
            contest_ref=contest.contest_ref, scoring_week=contest.scoring_week,
            rows=tuple(already), replayed=True)

    contest = resolve_contest(db, league_id=league_id,
                              competition_type=competition_type,
                              contest_ref=contest_ref)
    if contest.scoring_week >= int(marker.playoff_start_week):
        raise ChampionshipCorrectionError(
            REASON_NOT_ELIGIBLE,
            f"{contest.competition_type} contest {contest.contest_ref} has "
            f"scoring week {contest.scoring_week}, on or after "
            f"playoff_start_week={marker.playoff_start_week}. Postseason play is "
            f"permanently outside the Championship scoring window; no economics "
            f"were posted.")

    field = funded_championship_field(db, league_id=league_id, season=season)
    if not field:
        raise ChampionshipCorrectionError(
            "FS_CORRECTION_CHAMPIONSHIP_NOT_FROZEN",
            f"league {league_id} season {season} has no funded championship field.")

    # ── DERIVE THE DIFFERENCE ────────────────────────────────────────────────
    if contest.competition_type == COMPETITION_VERSUS:
        stakes, current = _versus_stakes_and_payouts(db, contest)
        if not stakes:
            raise ChampionshipCorrectionError(
                "FS_CORRECTION_CONTEST_NOT_FOUND",
                f"matchup {contest.contest_ref} has no funded stake to restate.")
        target = _versus_target(corrected_result, stakes)
    elif contest.competition_type == COMPETITION_PROP_POOL:
        from betting.pool_settlement import allocate_even_split

        # PROVE THE ECONOMIC CLASS BEFORE DERIVING ANYTHING. This raises before
        # any target is computed, any posting is made and any audit row exists.
        assert_pool_correctable(db, contest)
        pot, current = _pool_payouts(db, contest, league_id)
        if pot <= 0:
            raise ChampionshipCorrectionError(
                "FS_CORRECTION_CONTEST_NOT_FOUND",
                f"prop-pool occurrence {contest.contest_ref} distributed nothing; "
                f"there is no settled result to restate.")
        winners = tuple(sorted(int(t) for t in corrected_result.winner_team_ids))
        if not winners:
            raise ValueError("corrected prop-pool result must name at least one winner")
        # The certified §6.3 allocator, so a corrected split is cent-for-cent
        # what settlement itself would have produced.
        target = allocate_even_split(pot, winners)
        for team_id in current:
            target.setdefault(team_id, 0)
    else:  # pragma: no cover - resolve_contest already refuses
        raise ChampionshipCorrectionError(
            "FS_CORRECTION_UNKNOWN_COMPETITION_TYPE", competition_type)

    touched = sorted(set(target) | set(current))
    outside = sorted(t for t in touched if t not in field)
    if outside:
        raise ChampionshipCorrectionError(
            REASON_TEAM_NOT_IN_FIELD,
            f"{contest.competition_type} contest {contest.contest_ref} would move "
            f"Credits for team(s) {outside} outside the funded FantasyStakes "
            f"Championship field. Nothing was posted.")

    deltas = {t: int(target.get(t, 0)) - int(current.get(t, 0)) for t in touched}
    deltas = {t: d for t, d in deltas.items() if d}
    if sum(deltas.values()) != 0:
        raise ChampionshipCorrectionError(
            "FS_CORRECTION_NOT_CONSERVATIVE",
            f"corrected result would move {sum(deltas.values())} net cents; a "
            f"restatement redistributes the same pot and must sum to zero.")

    posting_id = None
    if deltas:
        posting_id = ledger_post(
            [(f"wallet:{t}", d) for t, d in sorted(deltas.items())],
            door=DOOR_RESULT_CORRECTION, session=db)
        db.flush()

    written: list = []
    for team_id in sorted(deltas):
        prior = (db.query(FantasyStakesChampionshipCorrection)
                 .filter(FantasyStakesChampionshipCorrection.league_id == league_id,
                         FantasyStakesChampionshipCorrection.season == season,
                         FantasyStakesChampionshipCorrection.competition_type
                         == contest.competition_type,
                         FantasyStakesChampionshipCorrection.contest_ref
                         == contest.contest_ref,
                         FantasyStakesChampionshipCorrection.team_id == team_id)
                 .order_by(FantasyStakesChampionshipCorrection.revision.desc())
                 .first())
        previous = int(prior.corrected_net_cents) if prior is not None else 0
        revision = (int(prior.revision) + 1) if prior is not None else 1
        delta = int(deltas[team_id])
        db.add(FantasyStakesChampionshipCorrection(
            freeze_id=marker.id, league_id=league_id, season=season,
            team_id=team_id, competition_type=contest.competition_type,
            contest_ref=contest.contest_ref, scoring_week=contest.scoring_week,
            revision=revision, previous_net_cents=previous,
            corrected_net_cents=previous + delta, delta_cents=delta,
            reason=reason, source=source, correction_key=correction_key,
            posting_id=posting_id, created_at=now))
        written.append(CorrectionRow(
            team_id=team_id, competition_type=contest.competition_type,
            contest_ref=contest.contest_ref, scoring_week=contest.scoring_week,
            revision=revision, previous_net_cents=previous,
            corrected_net_cents=previous + delta, delta_cents=delta,
            reason=reason, source=source, correction_key=correction_key))

    # Reflect the corrected outcome on the governed rows themselves, so the
    # contest's own state agrees with the economics. Ordinary settlement is not
    # re-entered; only the terminal status is restated.
    if contest.competition_type == COMPETITION_VERSUS:
        _restate_versus_bets(db, contest, corrected_result, now)

    db.flush()
    return CorrectionResult(
        league_id=league_id, season=season,
        competition_type=contest.competition_type,
        contest_ref=contest.contest_ref, scoring_week=contest.scoring_week,
        rows=tuple(written), replayed=False)


def _restate_versus_bets(db: Session, contest, result, now: datetime) -> None:
    for account in contest.escrow_accounts:
        bet_id = int(account.split(":", 1)[1])
        bet = db.query(Bet).filter(Bet.id == bet_id).first()
        if bet is None:
            continue
        wallet = db.query(Wallet).filter(Wallet.id == bet.wallet_id).first()
        if result.outcome == OUTCOME_PUSH:
            status = "push"
        elif wallet is not None and int(wallet.team_id) == int(result.winner_team_id):
            status = "won"
        else:
            status = "lost"
        bet.status = status
        bet.settled_at = now
