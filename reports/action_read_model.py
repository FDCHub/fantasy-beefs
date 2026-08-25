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

from sqlalchemy import or_, text
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
    #: UIRECON Wave 4B — the persisted terminal status of THIS GM's bet, exactly
    #: as `bets.status` holds it: `won`, `lost`, `push`, `void`. None while the
    #: wager is still open.
    #:
    #: REPORTED, NOT DERIVED. A Wrap result card needs to say what happened, and
    #: inferring it from the sign of `net_cents` would call a push and a void the
    #: same thing and would invent an outcome for a zero-net win. The row already
    #: knows; this carries it.
    outcome: Optional[str] = None

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

#: The legacy `beef_challenges.status` vocabulary, in the governed one's terms.
#:
#: ONE-TO-ONE, AND A TRANSLATION RATHER THAN AN INTERPRETATION. Both columns
#: name the same five negotiation states; `status` is what
#: `beefs.beef_engine` writes and `response_status` is what
#: `beefs.proposal_lifecycle` writes. Nothing is inferred, widened or
#: guessed here — each legacy word has exactly one governed word and the
#: CHECK constraints on the two columns enumerate the same five outcomes.
_LEGACY_RESPONSE_STATUS = {
    "pending":   OFFERED,
    "countered": COUNTERED,
    "accepted":  ACCEPTED,
    "declined":  DECLINED,
    "expired":   EXPIRED,
}


def effective_response_status(challenge: BeefChallenge) -> Optional[str]:
    """The negotiation state, whichever column this row records it in.

    TWO WRITERS, ONE QUESTION. `economy.challenge_funding` records a matchup's
    state in `response_status`; `beefs.beef_engine` — which
    `betting.versus_legacy_guard` classifies as a GOVERNED FantasyStakes path,
    not the single-GM one it exists to refuse — records it in `status`. Both
    produce a real GM-versus-GM matchup that funds, settles and posts to the
    ledger, so both are wagers this read model has to be able to answer about.

    READING ONLY ONE OF THEM WAS THE DEFECT. A challenge written by the engine
    carries `response_status IS NULL`, so every state test below returned
    "not open, not accepted" and the wager fell through to COMPLETED whatever
    it was really doing — including while it was live.

    THE GOVERNED COLUMN ALWAYS WINS. A row that has a `response_status` is a
    proposal-lifecycle row and is answered from it; the legacy translation is
    consulted only when there is no governed value to read, so no governed
    wager's classification can change.
    """
    if challenge.response_status is not None:
        return challenge.response_status
    return _LEGACY_RESPONSE_STATUS.get(challenge.status)


def decision_team_id(challenge: BeefChallenge) -> Optional[int]:
    """Whose decision an open challenge is waiting on.

    THE ONE RULE, IN ONE PLACE. `offered` waits on the recipient; `countered`
    waits on the original issuer, because a counter hands the decision back.
    Anything closed has no decision owner at all.
    """
    state = effective_response_status(challenge)
    if state == OFFERED:
        return challenge.challenged_team_id
    if state == COUNTERED:
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
    state = effective_response_status(challenge)
    if state == ACCEPTED:
        return SECTION_LIVE
    if state in OPEN_STATES:
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


@dataclass
class _Terms:
    """The frozen terms of one matchup, from whichever record holds them."""

    anchor_stake_cents: int = 0
    derived_stake_cents: Optional[int] = None
    anchor_odds: Optional[float] = None
    derived_odds: Optional[float] = None
    anchor_moneyline: Optional[int] = None
    derived_moneyline: Optional[int] = None
    line: Optional[float] = None
    side: Optional[str] = None
    player_id: Optional[int] = None
    version_number: Optional[int] = None


def _legacy_terms(db: Session, challenge: BeefChallenge) -> _Terms:
    """The terms of an engine-written matchup, off its own columns and Bets.

    WHY THIS IS REPORTING AND NOT ACCOMMODATION. `beef_challenges` carries the
    legacy engine's frozen terms in its OWN columns — `amount`, `line`, `side`,
    `challenger_odds`, `challenged_odds`, `challenger_moneyline`,
    `challenged_moneyline` — and the module already reads one of that family,
    `bet_type`, as the fallback for `wager_type`. This reads the rest of the
    same family for the same reason: it is where this record shape
    authoritatively states what was agreed.

    AND THE BET ROWS OUTRANK THE CONTAINER once they exist, on exactly the rule
    the module docstring already states for Final Lock: an executed record
    supersedes the quote that preceded it. A countered legacy challenge settles
    at `countered_amount`, and the Bet rows are what actually carry that — so
    reading `amount` past acceptance would report a stake the GM did not place.

    NO PRICE IS COMPUTED. Every value below is copied off a persisted row.
    """
    anchor_bet = derived_bet = None
    if challenge.challenger_bet_id or challenge.challenged_bet_id:
        by_id = {b.id: b for b in _bets_for(db, challenge.id)}
        anchor_bet = by_id.get(challenge.challenger_bet_id)
        derived_bet = by_id.get(challenge.challenged_bet_id)

    def _cents(bet, fallback):
        if bet is not None and bet.amount is not None:
            return int(round(float(bet.amount) * 100))
        return int(round(float(fallback) * 100)) if fallback is not None else 0

    return _Terms(
        anchor_stake_cents=_cents(anchor_bet, challenge.amount),
        derived_stake_cents=_cents(derived_bet, challenge.amount),
        anchor_odds=(anchor_bet.odds if anchor_bet is not None
                     else challenge.challenger_odds),
        derived_odds=(derived_bet.odds if derived_bet is not None
                      else challenge.challenged_odds),
        anchor_moneyline=challenge.challenger_moneyline,
        derived_moneyline=challenge.challenged_moneyline,
        line=challenge.line,
        side=challenge.side,
        player_id=challenge.player_id,
    )


def _proposal_terms(proposal: BeefProposal) -> _Terms:
    """The frozen terms of a proposal-lifecycle matchup, unchanged."""
    return _Terms(
        anchor_stake_cents=getattr(proposal, "anchor_stake_cents", None) or 0,
        derived_stake_cents=getattr(proposal, "quoted_derived_stake_cents", None),
        anchor_odds=getattr(proposal, "anchor_odds", None),
        derived_odds=getattr(proposal, "derived_odds", None),
        anchor_moneyline=getattr(proposal, "anchor_moneyline", None),
        derived_moneyline=getattr(proposal, "derived_moneyline", None),
        line=getattr(proposal, "line", None),
        side=getattr(proposal, "side", None),
        player_id=getattr(proposal, "player_id", None),
        version_number=getattr(proposal, "version_number", None),
    )


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


def _settled_credit_cents(db: Session, *, bet_id: int, team_id: int) -> int:
    """What settlement actually moved into this GM's wallet closing this bet.

    THE POSTING IS THE AUTHORITY, exactly as it is in
    `betting/pool_result_view`. A beef settles in ONE posting that debits both
    sides' escrow and credits the winner, so the posting is found by this bet's
    own escrow account and the answer is this GM's leg of it — zero when they
    were not credited, which is the honest figure for a loss.
    """
    total = db.execute(
        text("SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
             "WHERE account = :wallet AND posting_id IN ("
             "  SELECT posting_id FROM ledger_entries "
             "  WHERE account = :escrow AND door = 'wager_settled')"),
        {"wallet": f"wallet:{team_id}", "escrow": f"escrow:{bet_id}"},
    ).scalar()
    return int(total or 0)


def _settlement(db: Session, challenge_id: int, team_id: int
                ) -> tuple[bool, Optional[int], Optional[str]]:
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
        return False, None, None
    bet = mine[0]

    # A no-fault void is terminal reporting state even though it is deliberately
    # NOT a settlement and therefore leaves Bet.status pending.  The append-only
    # VoidedWager row is the authority; response_status remains accepted so the
    # acceptance audit trail and Weekly Minimum satisfaction are preserved.
    from economy.wager_void import is_voided
    if is_voided(db, bet_id=bet.id):
        return True, 0, "void"

    if bet.status in ("pending", None):
        return False, None, None

    # THE STATUS IS CARRIED THROUGH VERBATIM. It is the row's own terminal word
    # and the only authority on what happened.
    #
    # AND THE NET IS THE LEDGER'S, NOT A FORMULA'S. What stood here was
    # `stake x odds - stake`, which is a payout rule this product retired:
    # `betting/settlement_engine` credits the winner BOTH escrow balances —
    # the pot — and its own comment names that as "the fix itself, not the
    # 2x-amount shortcut it replaces ... never a recomputed bet.amount".
    # Reproducing an odds payout here therefore reported a number no posting
    # ever made, and it disagreed with `reports/standings_read_model`, which
    # reads the same wagers off the ledger doors. One GM's week could read
    # -1,687 on their Action cards and -1,500 in the Standings.
    #
    # So the credit is read from the posting that made it: the `wager_settled`
    # posting that closed THIS bet's escrow, and the amount it moved into this
    # GM's wallet. A loss credits nothing and nets the stake; a push returns the
    # escrow and nets zero; a win nets the pot less the stake. No branch on the
    # status word is needed for the money, because the ledger already
    # distinguishes them — which is what "money is reported, never recomputed"
    # asks of this module.
    stake_cents = int(round(float(bet.amount) * 100))
    credited = _settled_credit_cents(db, bet_id=bet.id, team_id=team_id)
    return True, credited - stake_cents, bet.status


def _challenge_wager_escrow_cents(db: Session,
                                  challenge: BeefChallenge) -> int:
    """Actual escrow held for this challenge at its current lifecycle stage.

    Before acceptance the Anchor is held in ``escrow:challenge:{id}``.  On
    acceptance that balance migrates to the two immutable Bet escrows, so an
    accepted Status card must read those accounts rather than report a false
    zero from the now-empty challenge account.  A void drains both and the same
    read naturally returns zero without inferring terminal state from balance.

    AND IT DOES NOT FLUSH TO GET THERE. An explicit session flush stood before
    this SELECT and was removed: it was a no-op on every read path measured —
    nothing is ever pending when this module runs — and it was redundant, because
    ``Session.execute`` autoflushes and ``sessionmaker(bind=engine)`` leaves
    autoflush at its default. ``ledger._balance_of_in_session`` issues this exact
    query against this exact table without one and states the rule: "no caller
    precondition beyond ordinary autoflush, which is the codebase-wide default".

    IT WAS NOT MERELY REDUNDANT, which is why its absence is worth stating. A
    read model that flushes writes whatever a CALLER left pending — so the one
    module contractually forbidden to mutate would have been the module that
    forced somebody else's mutation to disk. That is the hazard
    `test_uirecon_wave4_demo_visibility` guards, and the guard was right.
    """
    bets = _bets_for(db, challenge.id)
    if bets:
        return sum(max(0, int(db.execute(
            text("SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
                 "WHERE account = :account"),
            {"account": f"escrow:{bet.id}"},
        ).scalar() or 0)) for bet in bets)
    return challenge_escrow_balance(db, challenge.id)


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
        settled, net_cents, outcome = _settlement(db, challenge.id, team_id)
        owner = decision_team_id(challenge)
        is_anchor = challenge.challenger_team_id == team_id

        # THE TERMS COME FROM WHICHEVER RECORD THIS MATCHUP KEEPS THEM IN.
        # A proposal-lifecycle wager keeps them on the accepted proposal; an
        # engine-written one keeps them on the challenge row and its Bets. Both
        # are governed GM-versus-GM matchups that fund and settle, so both have
        # terms to report — and reading only the first told a GM their stake was
        # zero while their Credits sat in a settled Bet.
        terms = _proposal_terms(proposal) if proposal is not None \
            else _legacy_terms(db, challenge)

        anchor_stake = terms.anchor_stake_cents
        derived_stake = terms.derived_stake_cents
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
            anchor_ml = terms.anchor_moneyline
            derived_ml = terms.derived_moneyline
            anchor_odds = terms.anchor_odds
            derived_odds = terms.derived_odds

        pot = None
        if anchor_stake and derived_stake:
            pot = anchor_stake + derived_stake

        cards.append(ActionCard(
            challenge_id=challenge.id,
            section=classify(challenge, team_id, settled=settled),
            status=_STATUS_WORD.get(effective_response_status(challenge),
                                    STATUS_INCOMING),
            protocol_state=effective_response_status(challenge),
            mode=challenge.challenge_mode or "locked",
            week=challenge.week,
            opponent_team_id=opponent_id,
            opponent_name=(opponent.team_name if opponent else "Unknown"),
            direction="sent" if is_anchor else "received",
            decision_team_id=owner,
            viewer_decides=(owner == team_id),
            wager_type=challenge.wager_type or challenge.bet_type,
            line=terms.line,
            side=terms.side,
            player_id=terms.player_id,
            your_stake_cents=your_stake,
            their_stake_cents=their_stake,
            pot_cents=pot,
            your_odds=(anchor_odds if is_anchor else derived_odds),
            their_odds=(derived_odds if is_anchor else anchor_odds),
            your_moneyline=(anchor_ml if is_anchor else derived_ml),
            their_moneyline=(derived_ml if is_anchor else anchor_ml),
            escrow_cents=_challenge_wager_escrow_cents(db, challenge),
            derived_ceiling_cents=ceiling,
            derived_repriced=bool(dynamic
                                  and challenge.dynamic_handshake_at is not None),
            final_locked=final_lock is not None,
            settled=settled,
            net_cents=net_cents,
            outcome=outcome,
            created_at=(challenge.created_at.isoformat()
                        if challenge.created_at else None),
            expires_at=(challenge.active_response_expires_at.isoformat()
                        if challenge.active_response_expires_at
                        else (challenge.expires_at.isoformat()
                              if challenge.expires_at else None)),
            version_number=terms.version_number,
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
