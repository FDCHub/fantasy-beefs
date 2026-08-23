"""
economy/wager_void.py — voiding an ACCEPTED wager (WP-13, Final POR §7).

WHAT A VOID IS, AND WHAT IT IS NOT. A void says NO CONTEST OCCURRED: the wager
was accepted, both sides funded it, and then something removed the contest —
a cancelled game, a governed commissioner action. It is not a push. A push is a
RESULT, reached by playing; §7 gives the two different consequences and this
module exists so they stay distinguishable forever.

── THE FOUR RULES, AND WHERE EACH ONE LIVES ────────────────────────────────

    1. the accepted action goes on satisfying that week's Weekly Minimum
    2. the refund goes to `wallet:{team}`
    3. `min:{team}:{week}` is NEVER restored
    4. the FantasyStakes Score effect is exactly 0

Rules 1 and 3 are the SAME RULE seen from two sides, and neither is a flag
anybody sets. The Minimum was consumed when the wager was funded; the refund
credits Wallet and touches no `min:` account, so the Minimum stays consumed and
the week stays satisfied. Both are properties of the POSTING and are derivable
from the ledger. A stored "minimum satisfied" flag could disagree with the
postings; this cannot.

WHY THE REFUND MUST NOT GO BACK TO `min:`. It would hand the GM a second chance
to spend a Weekly Minimum they had already committed — and, worse, at week close
WP-4 would sweep the restored balance to the FantasyStakes Championship Pot,
so a GM whose opponent's game was cancelled would silently forfeit Credits they
had never had the chance to re-wager. That is why §7 names the destination.

RULE 4 IS WHY `DOOR_WAGER_VOID` IS IN `VERSUS_DOORS`. FantasyStakes Score counts
spend-account legs under the Versus doors, plus open Versus escrow. The original
funding debited `min:` and/or `wallet:` for -X and the escrow held +X, netting 0
while open. A void drains the escrow and credits `wallet:` +X under a Versus
door, so the spend legs sum to 0 and no open escrow remains: exactly 0, with no
special case anywhere in the read model. Refunding under a door OUTSIDE that set
would leave the Score permanently -X — the GM charged for a contest that never
happened.

── PROVENANCE: REVERSE LEGS, BUT NOT SOURCE-FAITHFUL ONES ──────────────────

`economy.challenge_funding._reverse` returns money to its ORIGINAL SOURCES by
replaying the funding legs backwards, which is right for a decline, a cancel or
an expiry — none of those wagers was ever accepted, so the Minimum was never
committed. It is exactly wrong here: §7 says a void refunds to Wallet.

So this module writes the same `reverse` `ChallengeFundingLeg` rows, consuming
fund legs in the same strict reverse sequence order, and directs every refunded
cent to `wallet:{team}` instead of to `leg.source_account`. The reverse rows are
not decoration: `economy.current_settle.in_play_cents` sums those legs to decide
what a GM has committed to unresolved escrow, so a refund without them would
leave the GM's assets permanently overstating a stake they had been given back.

THE LEG ACCOUNT AND THE LEDGER ACCOUNT ARE SEPARATE PARAMETERS, and they have to
be. Acceptance migrates the Anchor's money out of `escrow:challenge:{id}` into
`escrow:{anchor_bet_id}` as a plain balanced posting — deliberately NOT as a
reverse leg, because the money did not go back to anyone. The Anchor's fund legs
therefore still name the challenge escrow as their destination while the Credits
themselves sit in the Bet escrow. The debit must name where the money IS; the
leg consumption must name where the provenance SAYS it went.

── EXACTLY-ONCE, AT THE STORAGE LAYER ──────────────────────────────────────

`voided_wagers.bet_id` is UNIQUE, so a second void of the same wager cannot be
recorded. The refund is claimed by that constraint rather than by a check this
module performs and a concurrent caller could race past.

── ERA ─────────────────────────────────────────────────────────────────────

`RULESET_FINAL_POR` only. §7 is a Final POR rule; a legacy season has no void
path and inventing one would move real Credits on an authority that does not
exist for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from economy.economy_events import (
    EVENT_WAGER_VOID,
    gm_week_key,
    record_event,
    wallet_account,
)
from ledger.ledger import _balance_of_in_session, post as ledger_post
from ruleset import is_final_por

#: The one door under which a voided accepted wager returns a stake.
#:
#: DISTINCT FROM `challenge_refunded`, which is the decline / cancel / expire
#: door and refunds SOURCE-FAITHFULLY to `min:` and `wallet:` alike. The two
#: refunds are economically different and must stay separable in the ledger
#: forever: one says "you never committed this", the other says "you committed
#: it, the contest vanished, here is your stake back — and your Weekly Minimum
#: stays satisfied".
#:
#: IT IS A MEMBER OF `VERSUS_DOORS`, and that membership is what makes the
#: FantasyStakes Score effect exactly 0. See the module docstring.
DOOR_WAGER_VOID = "wager_voided"


class WagerVoidError(ValueError):
    """A void was refused, carrying a stable reason code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_WRONG_ERA = "VOID_WRONG_ERA"
REASON_NOT_ACCEPTED = "VOID_NOT_ACCEPTED"
REASON_ALREADY_VOIDED = "VOID_ALREADY_VOIDED"
REASON_ALREADY_SETTLED = "VOID_ALREADY_SETTLED"
REASON_NO_REASON = "VOID_NO_REASON"
REASON_CHALLENGE_NOT_FOUND = "VOID_CHALLENGE_NOT_FOUND"
REASON_UNATTRIBUTABLE = "VOID_UNATTRIBUTABLE_ESCROW"


@dataclass(frozen=True)
class VoidedSide:
    bet_id: int
    team_id: int
    escrow_account: str
    refunded_cents: int


@dataclass(frozen=True)
class VoidResult:
    challenge_id: int
    league_id: int
    season: int
    week: int | None
    reason: str
    sides: tuple[VoidedSide, ...]
    total_refunded_cents: int

    @property
    def bet_ids(self) -> tuple[int, ...]:
        return tuple(s.bet_id for s in self.sides)


def voided_bet_ids(db, *, league_id: int | None = None) -> tuple[int, ...]:
    """Every voided bet id, optionally for one league. READ-ONLY.

    The seam settlement uses to leave a voided wager alone. Returned as ids
    rather than as a predicate so the caller can express it as one SQL filter
    instead of a per-bet round trip.
    """
    from db.schema import VoidedWager

    query = db.query(VoidedWager.bet_id)
    if league_id is not None:
        query = query.filter(VoidedWager.league_id == league_id)
    return tuple(r[0] for r in query.all())


def is_voided(db, *, bet_id: int) -> bool:
    from db.schema import VoidedWager

    return (db.query(VoidedWager)
            .filter(VoidedWager.bet_id == bet_id).count()) > 0


def _bet_escrow_account(bet_id: int) -> str:
    return f"escrow:{bet_id}"


def _reverse_to_wallet(db, *, challenge_id: int, team_id: int,
                       leg_account: str, amount_cents: int, posting_id,
                       batch_id=None):
    """Write `reverse` funding legs for a refund that went to Wallet.

    Same strict reverse-sequence consumption `challenge_funding._reverse` uses —
    each `fund` leg for at most its remaining reversible cents, each reverse row
    naming the exact fund row it draws from. The ONE difference is
    `source_account`: it records `wallet:{team}`, because that is where the
    money actually went, and a leg claiming it returned to `min:` would be a
    false statement about a posting anyone can read.

    Returns the cents this could account for. A shortfall is NOT raised here:
    the ledger refund is driven by the escrow BALANCE, which is authoritative,
    and the caller decides what an unaccounted remainder means.
    """
    from db.schema import ChallengeFundingLeg
    from economy.challenge_funding import _next_sequence, _remaining_reversible

    fund_legs = (
        db.query(ChallengeFundingLeg)
        .filter(ChallengeFundingLeg.challenge_id == challenge_id,
                ChallengeFundingLeg.team_id == team_id,
                ChallengeFundingLeg.destination_account == leg_account,
                ChallengeFundingLeg.leg_kind == "fund")
        .order_by(ChallengeFundingLeg.sequence_number.desc())
        .all())

    outstanding = amount_cents
    sequence = _next_sequence(db, challenge_id)
    accounted = 0
    for leg in fund_legs:
        if outstanding <= 0:
            break
        take = min(_remaining_reversible(db, leg), outstanding)
        if take <= 0:
            continue
        db.add(ChallengeFundingLeg(
            challenge_id=challenge_id,
            team_id=leg.team_id,
            sequence_number=sequence,
            source_account=wallet_account(team_id),
            destination_account=leg_account,
            amount_cents=-take,
            leg_kind="reverse",
            reverses_funding_leg_id=leg.id,
            posting_id=posting_id,
            posting_batch_id=batch_id,
            protocol_event_id=leg.protocol_event_id,
        ))
        sequence += 1
        outstanding -= take
        accounted += take
    db.flush()
    return accounted


def void_accepted_wager(db, *, challenge_id: int, reason: str,
                        now: datetime | None = None) -> VoidResult:
    """Void one ACCEPTED wager, both sides. Does NOT commit.

    Each side's Bet escrow is returned in full to that side's own Wallet, the
    void is recorded once per bet, and one auditable economy event names the
    whole act.
    """
    import beefs.proposal_lifecycle as spec1
    from db.schema import BeefChallenge, Bet, League, VoidedWager, Wallet
    from economy.challenge_funding import _batch_id_for, challenge_escrow_account

    now = now or datetime.now(timezone.utc)

    if not (reason or "").strip():
        raise WagerVoidError(
            REASON_NO_REASON,
            "a void must carry a stated reason. It removes a contest two GMs "
            "had already funded; an unexplained one is not auditable.")

    challenge = (db.query(BeefChallenge)
                 .filter(BeefChallenge.id == challenge_id).first())
    if challenge is None:
        raise WagerVoidError(REASON_CHALLENGE_NOT_FOUND,
                             f"challenge {challenge_id} not found")

    if challenge.response_status != spec1.ACCEPTED:
        raise WagerVoidError(
            REASON_NOT_ACCEPTED,
            f"challenge {challenge_id} is {challenge.response_status!r}, not "
            f"{spec1.ACCEPTED!r}. §7's void applies to an ACCEPTED wager; a "
            f"challenge that was never accepted is declined, cancelled or "
            f"expired, and those refund source-faithfully to `min:` and "
            f"`wallet:` through `economy.challenge_funding`.")

    league = (db.query(League)
              .filter(League.id == challenge.league_id).first())
    if league is None:
        raise WagerVoidError(
            REASON_CHALLENGE_NOT_FOUND,
            f"challenge {challenge_id} names league {challenge.league_id}, "
            f"which does not exist.")
    season = league.season

    if not is_final_por(db, league_id=league.id, season=season):
        raise WagerVoidError(
            REASON_WRONG_ERA,
            f"league {league.id} season {season} is governed by the legacy "
            f"ruleset, which has no accepted-wager void. Refusing to invent "
            f"one for a season already played under different rules.")

    bet_ids = [b for b in (challenge.challenger_bet_id,
                           challenge.challenged_bet_id) if b is not None]
    bets = (db.query(Bet).filter(Bet.id.in_(bet_ids)).order_by(Bet.id).all()
            if bet_ids else [])
    if not bets:
        raise WagerVoidError(
            REASON_NOT_ACCEPTED,
            f"challenge {challenge_id} is ACCEPTED but names no Bet rows; "
            f"there is no accepted wager to void.")

    for bet in bets:
        if is_voided(db, bet_id=bet.id):
            raise WagerVoidError(
                REASON_ALREADY_VOIDED,
                f"bet {bet.id} of challenge {challenge_id} is already voided. "
                f"A void refunds a stake once; refusing to refund it again.")
        if bet.status != "pending":
            raise WagerVoidError(
                REASON_ALREADY_SETTLED,
                f"bet {bet.id} of challenge {challenge_id} is {bet.status!r}. "
                f"The contest produced a result and the escrow has been paid "
                f"out; those Credits are in GM Wallets and are not this "
                f"module's to reclaim.")

    week = getattr(bets[0], "week", None)
    if week is None:
        matchup_ids = {b.matchup_id for b in bets if b.matchup_id}
        if matchup_ids:
            from db.schema import Matchup

            matchup = (db.query(Matchup)
                       .filter(Matchup.id == min(matchup_ids)).first())
            week = matchup.week if matchup is not None else None

    sides: list[VoidedSide] = []
    total = 0
    for bet in bets:
        wallet = db.query(Wallet).filter(Wallet.id == bet.wallet_id).first()
        if wallet is None or wallet.team_id is None:
            raise WagerVoidError(
                REASON_UNATTRIBUTABLE,
                f"bet {bet.id} names wallet {bet.wallet_id}, which resolves to "
                f"no team. A refund cannot be directed from posted state, and "
                f"guessing an owner would credit the wrong GM.")
        team_id = wallet.team_id
        escrow = _bet_escrow_account(bet.id)
        db.flush()
        held = max(0, _balance_of_in_session(db, escrow))

        posting_id = None
        if held > 0:
            posting_id = ledger_post(
                [(escrow, -held), (wallet_account(team_id), held)],
                door=DOOR_WAGER_VOID, session=db)
            db.flush()

            # PROVENANCE. The Anchor's fund legs still name the challenge
            # escrow because acceptance migrated the money onward as a plain
            # posting rather than as a reverse leg; the Derived side's name its
            # own Bet escrow. Try the Bet escrow first, then the challenge
            # escrow, so both sides clear their in-play interest.
            batch_id = _batch_id_for(db, posting_id)
            accounted = _reverse_to_wallet(
                db, challenge_id=challenge_id, team_id=team_id,
                leg_account=escrow, amount_cents=held,
                posting_id=posting_id, batch_id=batch_id)
            if accounted < held:
                _reverse_to_wallet(
                    db, challenge_id=challenge_id, team_id=team_id,
                    leg_account=challenge_escrow_account(challenge_id),
                    amount_cents=held - accounted,
                    posting_id=posting_id, batch_id=batch_id)

        db.add(VoidedWager(
            bet_id=bet.id, challenge_id=challenge_id, team_id=team_id,
            league_id=league.id, season=season, week=week,
            refunded_cents=held, reason=reason.strip(),
            posting_id=posting_id, created_at=now))
        sides.append(VoidedSide(bet_id=bet.id, team_id=team_id,
                                escrow_account=escrow, refunded_cents=held))
        total += held

    # ONE AUDITABLE EVENT FOR THE WHOLE ACT, independent of the per-bet rows.
    # Keyed on the challenge so a second void of the same wager collides here as
    # well as on `uq_voided_wager_bet` — belt and braces over two different
    # storage mechanisms, because a refund is not a thing to be careless about.
    record_event(db, event_key=gm_week_key(
                     EVENT_WAGER_VOID, league.id, season, week or 0,
                     challenge_id),
                 league_id=league.id, season=season, week=week,
                 event_type=EVENT_WAGER_VOID, amount_cents=total,
                 posting_id=None, now=now)
    db.flush()

    return VoidResult(challenge_id=challenge_id, league_id=league.id,
                      season=season, week=week, reason=reason.strip(),
                      sides=tuple(sides), total_refunded_cents=total)
