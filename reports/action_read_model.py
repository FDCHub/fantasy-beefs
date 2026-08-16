"""
reports/action_read_model.py — the authoritative Action read model (S8-P4C-2).

READ-ONLY. Nothing here posts, locks, commits, prices or transitions anything.
It answers one question — "what does this GM's Action tab contain right now" —
from persisted proposal, wager and settlement state.

WHY CLASSIFICATION LIVES HERE AND NOT IN JAVASCRIPT. The Action tab is four
rails, and which rail a wager sits on is a statement about the PROTOCOL: whose
decision it is, whether the negotiation is still open, whether the wager is
live. Sprint 7's illustrative model derived that in the browser from
`protocolState` and a `role` string, which was correct for a fixture and is the
wrong place for it in production — the same rule would then exist twice, in two
languages, and the copy in JavaScript would be the one nobody notices drifting.
So the backend names the section and the frontend draws what it is told.

THE DECISION-OWNER IS THE WHOLE CLASSIFICATION. Section membership for an open
proposal is not "am I the issuer" — it is "is the decision mine". Those coincide
on a fresh offer and INVERT on a counter, which is exactly the case a
direction-based rule gets wrong. `decision_team_id` is therefore computed once,
from `response_status`, and both the section and the card's controls follow it.

USER-FACING LIFECYCLE LANGUAGE IS PRESERVED EXACTLY. `Incoming · Accepted ·
Countered · Declined · Expired` are the locked Rev 4.2 words. Internal states
that the product grammar does not name — `cancelled`, and the `revived` origin
of a challenge — are carried as protocol state but never presented as one of
those five, because inventing a sixth user-facing state is a product change and
this is a read model.

MONEY IS REPORTED, NEVER RECOMPUTED. Stakes come from the frozen proposal and
from posted escrow; nothing here re-derives a price, and no Dynamic formula is
reproduced. A Dynamic wager's Derived side is reported as the ceiling the
Handshake wrote, because that is the only authoritative bound that exists before
Final Lock.

AND AFTER FINAL LOCK, THE FROZEN RESULT IS THE AUTHORITY (WP6B). This is still
reporting rather than recomputing — `ChallengeFinalLock` is the immutable record
of what executed (Rev 9 §7.3), and it is read exactly as the proposal is. The
distinction matters because the proposal deliberately quotes NO Derived stake in
Dynamic mode: before WP6B wired the Final-Lock worker that gap was unreachable,
since a Dynamic wager could never be priced at all, and the card correctly showed
a ceiling and no stake. Now that the wager does get priced, reading the proposal
past that point would tell the opponent their stake is zero while real Credits of
theirs sit in Bet escrow. The ODDS move for the same reason and no other: Rev 9
§0 freezes the model and the ceilings at the Handshake but leaves the odds live
until Final Lock, so the Handshake quote is superseded the moment a frozen result
exists. American comes from that record and decimal from the Bet rows, which is
where each representation authoritatively lives (Rev 9 B-2); neither is converted
here.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import or_
from sqlalchemy.orm import Session

from beefs.proposal_lifecycle import (
    ACCEPTED, CANCELLED, COUNTERED, DECLINED, EXPIRED, MODE_DYNAMIC, OFFERED,
    OPEN_STATES,
)
from db.schema import (
    BeefChallenge, BeefProposal, Bet, ChallengeFinalLock, Team,
)
from economy.challenge_funding import challenge_escrow_balance

# ── The four rails, in Rev 4.2's order ────────────────────────────────────────

SECTION_ACTION_REQUIRED = "action"
SECTION_WAITING = "waiting"
SECTION_LIVE = "live"
SECTION_COMPLETED = "completed"

SECTIONS = (SECTION_ACTION_REQUIRED, SECTION_WAITING, SECTION_LIVE,
            SECTION_COMPLETED)

#: The locked user-facing lifecycle vocabulary. `cancelled` is deliberately
#: absent — see the module docstring.
STATUS_INCOMING = "Incoming"
STATUS_ACCEPTED = "Accepted"
STATUS_COUNTERED = "Countered"
STATUS_DECLINED = "Declined"
STATUS_EXPIRED = "Expired"

USER_FACING_STATUSES = (STATUS_INCOMING, STATUS_ACCEPTED, STATUS_COUNTERED,
                        STATUS_DECLINED, STATUS_EXPIRED)

#: Protocol state → the word a GM reads. `cancelled` maps to Declined because
#: that is what a withdrawn offer IS from the other side's view, and the locked
#: grammar has no sixth word; the protocol state travels separately for anyone
#: who needs the distinction.
_STATUS_WORD = {
    OFFERED: STATUS_INCOMING,
    COUNTERED: STATUS_COUNTERED,
    ACCEPTED: STATUS_ACCEPTED,
    DECLINED: STATUS_DECLINED,
    EXPIRED: STATUS_EXPIRED,
    CANCELLED: STATUS_DECLINED,
}


#: The two Versus subject phases, as this API contract spells them.
#:
#: DELIBERATELY LOWERCASE AND DELIBERATELY SEPARATE from
#: `betting/pool_season_boundary`'s `REGULAR`/`POSTSEASON`. That module's
#: constants are a governed internal vocabulary; these are a wire format. They
#: are the same DISTINCTION, decided by that module and reported by this one —
#: `_versus_subject_field` calls `is_postseason_week` and translates. Importing
#: the internal constants to serve them raw would tie the wire format to an
#: internal rename, and `reports/` keeps a narrow import surface besides.
PHASE_REGULAR = "regular"
PHASE_POSTSEASON = "postseason"


class ActionReadError(RuntimeError):
    """The Action state cannot be derived. Never a fallback to illustrative data."""


@dataclass(frozen=True)
class ActionCard:
    """One wager, as the Action tab needs it. Every field is sourced."""

    challenge_id: int
    section: str
    status: str                  # one of USER_FACING_STATUSES
    protocol_state: str          # the raw response_status, unrenamed
    mode: str                    # locked | dynamic
    week: int

    # Identity
    opponent_team_id: int
    opponent_name: str
    direction: str               # "sent" | "received"

    # WHOSE MOVE IT IS. None once the negotiation is closed — a settled
    # question has no owner, and reporting one would let a card offer controls.
    decision_team_id: Optional[int]
    viewer_decides: bool

    # Terms, as frozen on the active proposal
    wager_type: Optional[str]
    line: Optional[float]
    side: Optional[str]
    player_id: Optional[int]
    your_stake_cents: int
    their_stake_cents: Optional[int]
    pot_cents: Optional[int]
    your_odds: Optional[float]
    their_odds: Optional[float]
    your_moneyline: Optional[int]
    their_moneyline: Optional[int]

    # Real money currently held against THIS challenge's open escrow.
    escrow_cents: int

    # DYNAMIC ONLY. Absent on Locked, because a Locked wager has no ceiling.
    derived_ceiling_cents: Optional[int] = None
    derived_repriced: bool = False
    # WP6B — has the Final-Lock worker priced this wager yet? Read from the
    # existence of the immutable `ChallengeFinalLock` record, which is the one
    # fact separating "funded to a ceiling" from "priced and live". Always False
    # on a Locked card, which has no Final Lock to have occurred.
    final_locked: bool = False

    # Settlement, when it exists
    settled: bool = False
    net_cents: Optional[int] = None

    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    version_number: Optional[int] = None

    @property
    def controls(self) -> tuple[str, ...]:
        """Which commands this card may offer THIS viewer.

        Derived from the decision owner, never from direction. The server
        decides legality on the call regardless; this only keeps the UI from
        drawing a control that could not possibly work.
        """
        if not self.viewer_decides:
            return ()
        return ("accept", "counter", "decline")


@dataclass(frozen=True)
class ActionOpponent:
    """A team this GM may challenge.

    THE COMPOSER'S ONLY AUTHORITATIVE TARGET LIST. Issuing needs a real
    `challenged_team_id`, and the illustrative League fixture supplies display
    names with fixture ids — sending one of those would either fail or, worse,
    reach a real team that happened to share the number. League/provider binding
    is P4C-3's; this is the minimum the ACTION command needs to be real, which
    is why it lives in the Action contract rather than anticipating that work.
    """
    team_id: int
    team_name: str
    owner: str
    #: WP3C — whether this team may be a Versus subject RIGHT NOW.
    #:
    #: TRUE FOR EVERY MEMBER IN THE REGULAR SEASON, and in the postseason only
    #: for the championship-track field the governed authority names. It is
    #: REPORTED here, never decided: the caller supplies the eligible set, which
    #: it obtained from `beefs/postseason_versus`, and the funding gate refuses
    #: an ineligible pairing regardless of what this said.
    #:
    #: WHY THE LIST IS ANNOTATED RATHER THAN FILTERED. An eliminated opponent
    #: that simply vanished from the composer would leave a GM wondering where
    #: their league-mate went; a flagged one lets the surface say WHY. It also
    #: keeps this list usable by the Action cards, which must still name the
    #: opponent on a wager struck before elimination.
    versus_eligible: bool = True


@dataclass(frozen=True)
class ActionState:
    """The whole Action tab for one GM."""

    team_id: int
    league_id: int
    week: int
    cards: tuple[ActionCard, ...] = field(default_factory=tuple)
    opponents: tuple[ActionOpponent, ...] = field(default_factory=tuple)

    # -- WP3C: the Versus subject phase ---------------------------------------
    #
    #: `regular` or `postseason`, from the league's own governed boundary.
    versus_phase: str = PHASE_REGULAR
    #: Whether the eligible field could be determined at all. FALSE in a
    #: postseason week whose championship track the provider has not classified
    #: -- and then NO opponent is eligible, because the honest answer to "who
    #: may I challenge?" is "we cannot tell yet", not "everyone".
    versus_field_determinable: bool = True

    @property
    def eligible_opponents(self) -> tuple[ActionOpponent, ...]:
        """The subset a new wager may actually be offered against."""
        return tuple(o for o in self.opponents if o.versus_eligible)

    def section(self, name: str) -> tuple[ActionCard, ...]:
        return tuple(c for c in self.cards if c.section == name)

    @property
    def counts(self) -> dict[str, int]:
        """The four headings' counts, from bound state and nothing else."""
        return {name: len(self.section(name)) for name in SECTIONS}


# ── Classification ────────────────────────────────────────────────────────────

def decision_team_id(challenge: BeefChallenge) -> Optional[int]:
    """Whose decision an open challenge is waiting on.

    THE ONE RULE, IN ONE PLACE. `offered` waits on the recipient; `countered`
    waits on the original issuer, because a counter hands the decision back.
    Anything closed has no decision owner at all.
    """
    if challenge.response_status == OFFERED:
        return challenge.challenged_team_id
    if challenge.response_status == COUNTERED:
        return challenge.challenger_team_id
    return None


def classify(challenge: BeefChallenge, viewer_team_id: int, *,
             settled: bool) -> str:
    """Which of the four rails this challenge sits on, for this viewer.

    SECTION IS VIEWER-RELATIVE, and only for open negotiations: the same
    challenge is ACTION REQUIRED for the GM who must decide and WAITING for the
    one who cannot. LIVE and COMPLETED are properties of the wager itself and
    read the same for both parties.
    """
    if settled:
        return SECTION_COMPLETED
    if challenge.response_status == ACCEPTED:
        return SECTION_LIVE
    if challenge.response_status in OPEN_STATES:
        return (SECTION_ACTION_REQUIRED
                if decision_team_id(challenge) == viewer_team_id
                else SECTION_WAITING)
    # declined / expired / cancelled — negotiation is over and nothing settled.
    return SECTION_COMPLETED


# ── The read ──────────────────────────────────────────────────────────────────

def _active_proposal(db: Session, challenge: BeefChallenge
                     ) -> Optional[BeefProposal]:
    """The version in force — the lifecycle's pointer, not the highest id.

    A challenge that has been accepted points at `accepted_proposal_id`; the
    terms a LIVE card shows must be the ones actually accepted, which after a
    counter is version 2 rather than the version the container was opened with.
    """
    proposal_id = challenge.accepted_proposal_id or challenge.active_proposal_id
    if proposal_id is None:
        return None
    return db.query(BeefProposal).filter(BeefProposal.id == proposal_id).first()


def _bets_for(db: Session, challenge_id: int) -> list[Bet]:
    return (db.query(Bet)
            .filter(Bet.beef_challenge_id == challenge_id)
            .order_by(Bet.id)
            .all())


def _final_lock(db: Session, challenge_id: int) -> Optional[ChallengeFinalLock]:
    """The frozen Final-Lock result, or None if the worker has not priced it.

    `UNIQUE(challenge_id)` makes "the" the right article: there is at most one,
    forever, so its presence is a complete answer rather than the first of
    several.
    """
    return (db.query(ChallengeFinalLock)
            .filter(ChallengeFinalLock.challenge_id == challenge_id).first())


def _settlement(db: Session, challenge_id: int, team_id: int
                ) -> tuple[bool, Optional[int]]:
    """Whether this GM's side has settled, and their net in cents.

    SETTLED MEANS THE GM'S OWN BET SETTLED. A challenge is not "completed"
    because the other side's row happens to carry a status — the card belongs to
    this GM and reports their outcome.
    """
    from db.schema import Wallet

    wallet_ids = {w.id for w in db.query(Wallet)
                  .filter(Wallet.team_id == team_id).all()}
    mine = [b for b in _bets_for(db, challenge_id) if b.wallet_id in wallet_ids]
    if not mine:
        return False, None
    bet = mine[0]
    if bet.status in ("pending", None):
        return False, None

    stake_cents = int(round(float(bet.amount) * 100))
    if bet.status == "won":
        # The payout net of the stake — what the GM is up on the wager.
        return True, int(round(stake_cents * float(bet.odds))) - stake_cents
    if bet.status == "lost":
        return True, -stake_cents
    # push / void and anything else terminal: no gain, no loss.
    return True, 0


def gm_action_state(db: Session, *, team_id: int, league_id: int,
                    week: Optional[int] = None,
                    eligible_team_ids: Optional[frozenset] = None,
                    versus_phase: str = PHASE_REGULAR,
                    versus_field_determinable: bool = True) -> ActionState:
    """Every Action card for one GM, already classified.

    LEAGUE-SCOPED. A challenge is only this GM's Action if it belongs to the
    league being read — the acting league comes from the session, and reading
    across leagues would be the boundary violation P2 closed.

    WP3C — `eligible_team_ids` IS SUPPLIED, NOT COMPUTED. Postseason Versus
    eligibility belongs to `beefs/postseason_versus`, is derived from the
    championship track, and reaching it needs the provider layer `reports/` is
    not allowed to import. The composition layer assembles it and hands it in;
    this module marks the list and invents nothing. `None` means "no restriction
    applies", which is the regular season and every pre-WP3C caller.
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if team is None:
        raise ActionReadError(f"Team {team_id} does not exist.")
    if team.league_id != league_id:
        raise ActionReadError(
            f"Team {team_id} is not in league {league_id}; refusing to report "
            f"Action state across a league boundary.")

    rows = (db.query(BeefChallenge)
            .filter(BeefChallenge.league_id == league_id,
                    or_(BeefChallenge.challenger_team_id == team_id,
                        BeefChallenge.challenged_team_id == team_id))
            .order_by(BeefChallenge.id)
            .all())

    cards: list[ActionCard] = []
    for challenge in rows:
        opponent_id = (challenge.challenged_team_id
                       if challenge.challenger_team_id == team_id
                       else challenge.challenger_team_id)
        opponent = db.query(Team).filter(Team.id == opponent_id).first()
        proposal = _active_proposal(db, challenge)
        settled, net_cents = _settlement(db, challenge.id, team_id)
        owner = decision_team_id(challenge)
        is_anchor = challenge.challenger_team_id == team_id

        anchor_stake = getattr(proposal, "anchor_stake_cents", None) or 0
        derived_stake = getattr(proposal, "quoted_derived_stake_cents", None)
        dynamic = challenge.challenge_mode == MODE_DYNAMIC

        # WHOSE STAKE IS WHOSE. The Anchor is always the original issuer, even
        # after a counter — reading it off `direction` would swap both sides'
        # money on every countered card.
        your_stake = anchor_stake if is_anchor else (derived_stake or 0)
        their_stake = derived_stake if is_anchor else anchor_stake

        # THE DYNAMIC CEILING IS THE ONLY AUTHORITATIVE DERIVED BOUND that
        # exists before Final Lock. It is reported, never used to guess a price.
        #
        # THE SAME NUMBER FOR BOTH VIEWERS, deliberately. The Derived side is
        # the ORIGINAL RECIPIENT's, so its ceiling is a property of the wager
        # rather than of who is looking at it — the issuer needs it to see how
        # far their opponent's stake may move, and the opponent needs it to see
        # their own exposure. Only the Derived side floats, so there is one
        # ceiling to report and `dynamic_issuer_ceiling_cents` is not it.
        ceiling = challenge.dynamic_opponent_ceiling_cents if dynamic else None

        # THE PRICE, FROM WHICHEVER RECORD IS AUTHORITATIVE NOW. Before Final
        # Lock that is the accepted proposal; after it, the frozen result and the
        # Bet rows it created. See the module docstring — the switch is reporting
        # a later fact, not recomputing an earlier one.
        final_lock = _final_lock(db, challenge.id) if dynamic else None
        if final_lock is not None:
            anchor_stake = final_lock.anchor_cents
            derived_stake = final_lock.derived_final_cents
            your_stake = anchor_stake if is_anchor else derived_stake
            their_stake = derived_stake if is_anchor else anchor_stake
            anchor_ml = final_lock.issuer_moneyline
            derived_ml = final_lock.opponent_moneyline
            _by_id = {b.id: b for b in _bets_for(db, challenge.id)}
            _anchor_bet = _by_id.get(final_lock.anchor_bet_id)
            _derived_bet = _by_id.get(final_lock.derived_bet_id)
            anchor_odds = _anchor_bet.odds if _anchor_bet else None
            derived_odds = _derived_bet.odds if _derived_bet else None
        else:
            anchor_ml = getattr(proposal, "anchor_moneyline", None)
            derived_ml = getattr(proposal, "derived_moneyline", None)
            anchor_odds = getattr(proposal, "anchor_odds", None)
            derived_odds = getattr(proposal, "derived_odds", None)

        pot = None
        if anchor_stake and derived_stake:
            pot = anchor_stake + derived_stake

        cards.append(ActionCard(
            challenge_id=challenge.id,
            section=classify(challenge, team_id, settled=settled),
            status=_STATUS_WORD.get(challenge.response_status,
                                    STATUS_INCOMING),
            protocol_state=challenge.response_status,
            mode=challenge.challenge_mode or "locked",
            week=challenge.week,
            opponent_team_id=opponent_id,
            opponent_name=(opponent.team_name if opponent else "Unknown"),
            direction="sent" if is_anchor else "received",
            decision_team_id=owner,
            viewer_decides=(owner == team_id),
            wager_type=challenge.wager_type or challenge.bet_type,
            line=getattr(proposal, "line", None),
            side=getattr(proposal, "side", None),
            player_id=getattr(proposal, "player_id", None),
            your_stake_cents=your_stake,
            their_stake_cents=their_stake,
            pot_cents=pot,
            your_odds=(anchor_odds if is_anchor else derived_odds),
            their_odds=(derived_odds if is_anchor else anchor_odds),
            your_moneyline=(anchor_ml if is_anchor else derived_ml),
            their_moneyline=(derived_ml if is_anchor else anchor_ml),
            escrow_cents=challenge_escrow_balance(db, challenge.id),
            derived_ceiling_cents=ceiling,
            derived_repriced=bool(dynamic
                                  and challenge.dynamic_handshake_at is not None),
            final_locked=final_lock is not None,
            settled=settled,
            net_cents=net_cents,
            created_at=(challenge.created_at.isoformat()
                        if challenge.created_at else None),
            expires_at=(challenge.active_response_expires_at.isoformat()
                        if challenge.active_response_expires_at
                        else (challenge.expires_at.isoformat()
                              if challenge.expires_at else None)),
            version_number=getattr(proposal, "version_number", None),
        ))

    # EVERY OTHER TEAM IN THIS LEAGUE, and no team outside it. The cross-league
    # refusal exists on the route too; excluding them here means the UI never
    # offers a target that is going to be refused.
    #
    # WP3C EXTENDS THAT SAME REASONING INTO THE POSTSEASON. Before this, every
    # league member was offered as a Versus target in every week -- including,
    # in week 16, two consolation teams whose wager `beefs/postseason_versus`
    # refuses at the funding gate. The list is now MARKED with the governed
    # answer, so the surface can decline to offer what the engine will decline
    # to accept.
    opponents = tuple(
        ActionOpponent(
            team_id=t.id, team_name=t.team_name, owner=t.owner,
            versus_eligible=(eligible_team_ids is None
                             or t.id in eligible_team_ids),
        )
        for t in db.query(Team)
        .filter(Team.league_id == league_id, Team.id != team_id)
        .order_by(Team.team_name).all()
    )

    return ActionState(team_id=team_id, league_id=league_id,
                       week=week or 0, cards=tuple(cards),
                       opponents=opponents,
                       versus_phase=versus_phase,
                       versus_field_determinable=versus_field_determinable)