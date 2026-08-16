"""
beefs/versus_quote.py — the Versus proposal economics, in ONE place.

WP3C.1. What a GM is told before they send, and what the write path freezes into
the proposal, are now produced by the same function.

THE DEFECT THIS CLOSES, AND WHY IT WAS STRUCTURAL RATHER THAN A BUG.

Before this module, the Locked economics of a Versus proposal were computed
INLINE inside `api/main.py`, in two places — `/beef/challenge` and
`/beef/counter` — as four expressions repeated verbatim:

    quoted_derived_stake_cents  = None if dynamic else stake_cents
    quoted_funded_pot_cents     = None if dynamic else stake_cents * 2
    quoted_anchor_payout_cents  = round(stake_cents * anchor_dec)
    quoted_derived_payout_cents = None if dynamic else round(stake_cents * derived_dec)

Two copies of a formula is one copy too many, and adding a third for a quote
endpoint would have made the pre-send figures and the written figures
independently maintained — which is precisely how a product comes to show a GM
one pot and record another. WP3C.1 §4 permits a minimal extraction for exactly
this reason, on the condition that the outputs are unchanged. They are: the
expressions below are the originals, moved rather than rewritten, and the
parity suite asserts the quote and the persisted proposal agree to the cent.

THIS MODULE COMPUTES NO ODDS. It is handed the priced decimal odds and the
frozen win probabilities that `beefs/beef_engine._compute_odds` produced, and it
turns a stake into the four money figures a proposal carries. The pricing model
is not touched, imported or reimplemented here.

DYNAMIC IS NOT LOCKED WITH DIFFERENT NUMBERS — it is a different shape, and the
difference is load-bearing:

  LOCKED    both sides stake the same amount. The Derived stake, the pot and
            both payouts are quoted at proposal time and frozen there.

  DYNAMIC   the opponent's side is priced at the HANDSHAKE, from the frozen
            probabilities, by `odds/dynamic_pricing.derive_stakes` — and it may
            come DOWN again at Final Lock, never up. The proposal therefore
            quotes NO Derived stake: `quoted_derived_stake_cents` is None, and
            that None is protocol, not omission.

            A quote may still tell the GM what the opponent's CEILING would be,
            because that is knowable now and is the number the Handshake will
            use. It is reported as a ceiling and labelled as one — never as a
            settled stake. WP3C.1 §10.

NO DATABASE, NO SESSION, NO I/O. Everything here is arithmetic over arguments,
which is what lets the quote route and the two write routes share it without
either inheriting the other's transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# THE DYNAMIC CEILING IS THE CERTIFIED DERIVATION, imported rather than
# restated. `odds/dynamic_pricing.derive_stakes` is the P3-D1 pricing law and is
# fenced by `test_p3_d1_dynamic_pricing.py` against ever acquiring a database
# type; the Handshake calls the same function on the same frozen probabilities,
# so a quote produced here cannot disagree with the ceiling the Handshake sets.
from odds.dynamic_pricing import derive_stakes


@dataclass(frozen=True)
class ProposalEconomics:
    """The four money figures a Versus proposal carries, in exact cents.

    The field names are the `ProposalTerms` names verbatim. Nothing is renamed
    for presentation — a rename is where a mapping error hides, and this type
    exists specifically so the quote and the write cannot map differently.
    """

    anchor_stake_cents: int
    #: None in Dynamic, where the opponent's side is priced at the Handshake.
    quoted_derived_stake_cents: Optional[int]
    #: None in Dynamic, for the same reason: there is no second stake to add.
    quoted_funded_pot_cents: Optional[int]
    quoted_anchor_payout_cents: int
    quoted_derived_payout_cents: Optional[int]


def proposal_economics(*, stake_cents: int, anchor_odds: float,
                       derived_odds: float, dynamic: bool) -> ProposalEconomics:
    """The economics of one proposal at one stake.

    MOVED, NOT REWRITTEN. Each expression is the one that stood inline in
    `api/main.py`, including its rounding. `round()` is Python's
    banker's rounding and is retained deliberately: changing it to
    half-away-from-zero would reprice every wager whose payout lands on a
    half-cent, which is a change to certified economics and is prohibited.

    :param stake_cents: the issuer's Anchor stake, exact integer cents
    :param anchor_odds: decimal odds for the issuer, from the pricing model
    :param derived_odds: decimal odds for the opponent, from the pricing model
    :param dynamic: whether this is a Dynamic proposal
    """
    return ProposalEconomics(
        anchor_stake_cents=stake_cents,
        # BOTH SIDES STAKE THE SAME AMOUNT in locked mode — the single `amount`
        # on the request is each side's stake, exactly as the legacy path placed
        # both sides at `effective_amount`.
        quoted_derived_stake_cents=None if dynamic else stake_cents,
        quoted_funded_pot_cents=None if dynamic else stake_cents * 2,
        quoted_anchor_payout_cents=round(stake_cents * anchor_odds),
        quoted_derived_payout_cents=(None if dynamic
                                     else round(stake_cents * derived_odds)),
    )


@dataclass(frozen=True)
class VersusQuote:
    """What a composer needs to show before a GM sends.

    A PROJECTION OF `ProposalEconomics`, plus the odds it was priced at and, in
    Dynamic, the ceiling the Handshake would set. It carries no identity fields
    — the route adds those, because the route is what resolved them.
    """

    your_stake_cents: int
    #: The opponent's stake. In Dynamic this is the CEILING — see `is_ceiling`.
    opponent_stake_cents: int
    pot_cents: int
    #: WHAT THE GM GAINS ON A WIN — the opponent's stake, not the whole pot.
    #:
    #: This is the PROFIT, and it is deliberately the same quantity the composer
    #: has always drawn under `You win`, beside `You lose` = their own stake.
    #: The two rows are a symmetric pair: one is what is gained, the other what
    #: is lost, and the pot is reported separately as the third figure.
    #:
    #: The settlement engine credits the winner `winner_escrow + loser_escrow`,
    #: which is `pot_cents` — the same money, described from the other side.
    #: Reporting the pot HERE would silently redefine an existing certified UI
    #: row, which WP3C.1 forbids.
    win_cents: int
    #: What the GM loses on a loss: their own stake, and never more.
    lose_cents: int

    anchor_odds: float
    derived_odds: float
    anchor_moneyline: int
    derived_moneyline: int

    #: TRUE in Dynamic. The opponent's figure is a maximum that may come down at
    #: Final Lock and can never rise; the surface must say so rather than
    #: presenting it as settled. WP3C.1 §10.
    is_ceiling: bool

    def as_dict(self) -> dict:
        return {
            "your_stake_cents": self.your_stake_cents,
            "opponent_stake_cents": self.opponent_stake_cents,
            "pot_cents": self.pot_cents,
            "win_cents": self.win_cents,
            "lose_cents": self.lose_cents,
            "anchor_odds": self.anchor_odds,
            "derived_odds": self.derived_odds,
            "anchor_moneyline": self.anchor_moneyline,
            "derived_moneyline": self.derived_moneyline,
            "is_ceiling": self.is_ceiling,
        }


def build_quote(*, stake_cents: int, anchor_odds: float, derived_odds: float,
                anchor_moneyline: int, derived_moneyline: int,
                anchor_probability: float, derived_probability: float,
                dynamic: bool) -> VersusQuote:
    """The pre-send quote, from the same economics the write path freezes.

    LOCKED reads `proposal_economics` directly, so the quoted opponent stake and
    pot ARE the values the proposal will carry — not a parallel calculation that
    happens to agree.

    DYNAMIC has no quoted Derived stake to read, because the protocol does not
    fix one at proposal time. What it does have is the ceiling, and the ceiling
    is derivable NOW from the frozen probabilities by the same function the
    Handshake uses. Reporting it is honest and useful; reporting it as a settled
    stake would not be, which is what `is_ceiling` exists to prevent.

    THE ANCHOR STAKE IS THE SAME IN BOTH MODES and is never derived — it is what
    the GM typed. Only the opponent's side differs.
    """
    economics = proposal_economics(
        stake_cents=stake_cents, anchor_odds=anchor_odds,
        derived_odds=derived_odds, dynamic=dynamic)

    if dynamic:
        # THE HANDSHAKE'S OWN DERIVATION, on the probabilities this proposal
        # would freeze. `economy/dynamic_challenge` calls
        # `derive_stakes(anchor_target, p_iss, p_opp)` and takes
        # `.opponent_cents` as the ceiling; this is that call, with that
        # argument order, on the same inputs.
        pair = derive_stakes(stake_cents, anchor_probability,
                             derived_probability)
        opponent_cents = pair.opponent_cents
        pot_cents = pair.funded_pot_cents
    else:
        # NOT RECOMPUTED. Read straight off the economics the proposal carries,
        # so a change to that function moves the quote with it.
        opponent_cents = economics.quoted_derived_stake_cents
        pot_cents = economics.quoted_funded_pot_cents

    return VersusQuote(
        your_stake_cents=economics.anchor_stake_cents,
        opponent_stake_cents=opponent_cents,
        pot_cents=pot_cents,
        # WIN IS THE OPPONENT'S STAKE — the profit. See the field note: this is
        # the quantity the composer's `You win` row has always carried, and
        # WP3C.1 replaces where the number COMES FROM without redefining what
        # the row means.
        win_cents=opponent_cents,
        lose_cents=economics.anchor_stake_cents,
        anchor_odds=anchor_odds,
        derived_odds=derived_odds,
        anchor_moneyline=anchor_moneyline,
        derived_moneyline=derived_moneyline,
        is_ceiling=dynamic,
    )
