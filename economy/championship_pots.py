"""
economy/championship_pots.py — the Final POR league-level pot architecture (WP-5).

WHAT MODEL B ACTUALLY CHANGES. A championship pot is now a LEAGUE-LEVEL
virtual-credit allocation. It is not the sum of per-GM prepaid contributions,
and no GM owes anything because a pot exists. The retired architecture advanced
`reserve:{team}` to every GM at activation and swept it to `championship:{league}`
at season close, which made the pot's existence a per-GM obligation: every GM
carried their share as debt from day one whether or not they ever competed for
it. Minting the pot against a league-season issuance tally is the ledger shape
of the sentence "the league allocates the pot" — there is no GM leg, so no GM
liability can be derived from one. That is the property `no_gm_liability` below
asserts directly rather than by inspection.

── THE THREE POTS ───────────────────────────────────────────────────────────

    fantasystakes_championship:{L}:{S}   MINTED base, then GROWS during the season
    points_championship:{L}:{S}          NEVER minted; accrues actual Skunk only
    ff_championship:{L}:{S}              MINTED once at activation, then FROZEN

Each is season-scoped, and the scope is load-bearing rather than tidy: a league
playing a second season under `championship:{league}` or `skunk:{league}` would
distribute the previous season's money. A pot that outlives its season cannot be
distributed at the end of one.

── WHY THE THREE FUND DIFFERENTLY, AND MUST ─────────────────────────────────

FANTASYSTAKES is minted at a base and then grows, because §13 defines its
Current Pot as Base + sweeps + Top-Off additions + terminal Pool remainders. Its
size is not knowable at activation, which is exactly why WP-8 makes it LIVE
until finality instead of freezing it at the playoff boundary.

    Base = Weekly Minimum x Regular-Season Weeks

    NOT MULTIPLIED BY GM COUNT. This is the single most load-bearing arithmetic
    statement in WP-5 and the one the retired model got structurally wrong: it
    charged every GM a contribution, so the pot scaled with the field. §13 says
    the Base is one league-level allocation of one season's worth of Weekly
    Minimum. A ten-GM league and a four-GM league playing the same stops open
    the same Base Pot. `mint_fantasystakes_base_pot` never reads a team count,
    and there is no team count in scope for it to read by accident.

POINTS is never minted at all. §12: the pot IS the Skunk actually assessed. A
projection (fee x weeks) is a display figure and is computed by the read model,
never posted. A Points pot that could be minted could disagree with the fees the
league really paid, and there would be no way to tell which was right.

FANTASY FOOTBALL is minted once and then frozen absolutely. §14: one
commissioner-entered league amount, which MAY BE ZERO. It never accretes from
any source. A pot that grows from unrelated sources is a pot whose size no
commissioner agreed to, and this is the one pillar whose settlement is gated on
provider finality — a balance that moved after activation could not be
reconciled against the amount the league was told it was playing for.

── ZERO IS A REAL AMOUNT AND IS MINTED AS A NON-EVENT ───────────────────────

A league that sets the Fantasy Football pot to 0 has made a governed choice, not
a missing one. The mint records its event and posts NO ledger legs, exactly as
WP-4's zero-remainder week close does: the event is what makes a replay a no-op,
and a zero-amount posting would claim a movement that did not happen. §20's
"at least two FUNDED pillars" then reads the balance and correctly finds this
pillar unfunded — which is a different fact from "unminted", and WP-14 needs to
tell them apart.

── ERA ──────────────────────────────────────────────────────────────────────

Everything here is `RULESET_FINAL_POR` only. A legacy season mints nothing, and
`assert_final_por` refuses rather than quietly minting into a season whose pots
were funded by contributions that were really collected. Nothing here rewrites,
migrates or reinterprets a posting already made under the legacy architecture.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from economy.economy_events import (
    CHAMPIONSHIP_PILLARS,
    DOOR_CHAMPIONSHIP_POT_MINT,
    EVENT_CHAMPIONSHIP_POT_MINT,
    PILLAR_FANTASY_FOOTBALL,
    PILLAR_FANTASYSTAKES,
    PILLAR_POINTS,
    DuplicateEconomyEvent,
    championship_issuance_account,
    championship_pot_account,
    ff_championship_account,
    fantasystakes_championship_account,
    pillar_season_key,
    points_championship_account,
    record_event,
)
from ledger.ledger import _balance_of_in_session, post as ledger_post
from ruleset import is_final_por


class ChampionshipPotError(ValueError):
    """A pot operation was refused, carrying a stable reason code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_WRONG_ERA = "POT_WRONG_ERA"
REASON_NEGATIVE_AMOUNT = "POT_NEGATIVE_AMOUNT"
REASON_UNKNOWN_PILLAR = "POT_UNKNOWN_PILLAR"
REASON_NOT_MINTABLE = "POT_NOT_MINTABLE"
REASON_NO_TERMS = "POT_NO_TERMS"


@dataclass(frozen=True)
class MintResult:
    league_id: int
    season: int
    pillar: str
    account: str
    amount_cents: int
    replayed: bool
    #: True when the amount was 0: the event was recorded and no leg was posted.
    posted: bool


@dataclass(frozen=True)
class PotBalances:
    """Every governed pot for one league-season, plus the minted tally.

    `minted_cents` is a POSITIVE magnitude. The issuance account runs negative
    as minting proceeds — its debit balance IS the tally — and reporting the raw
    balance would flip the sign of every mint in every reader."""

    league_id: int
    season: int
    fantasystakes_cents: int
    points_cents: int
    fantasy_football_cents: int
    minted_cents: int

    @property
    def by_pillar(self) -> dict[str, int]:
        return {
            PILLAR_FANTASYSTAKES: self.fantasystakes_cents,
            PILLAR_POINTS: self.points_cents,
            PILLAR_FANTASY_FOOTBALL: self.fantasy_football_cents,
        }

    @property
    def funded_pillars(self) -> tuple[str, ...]:
        """Pillars holding money. §20's Grand Championship requires two.

        FUNDED IS A BALANCE TEST, NOT A CONFIGURATION TEST. A pillar minted at
        zero is minted and unfunded; a pillar never minted is also unfunded.
        Both are correctly excluded, and neither is mistaken for the other."""
        return tuple(p for p in CHAMPIONSHIP_PILLARS if self.by_pillar[p] > 0)

    def as_dict(self) -> dict:
        return {
            "league_id": self.league_id,
            "season": self.season,
            "fantasystakes_cents": self.fantasystakes_cents,
            "points_cents": self.points_cents,
            "fantasy_football_cents": self.fantasy_football_cents,
            "minted_cents": self.minted_cents,
            "funded_pillars": list(self.funded_pillars),
        }


def assert_final_por(db, *, league_id: int, season: int) -> None:
    """Refuse any Final POR pot operation on a legacy season.

    REFUSES RATHER THAN NO-OPS. A legacy season's pots were funded by
    contributions that were really advanced to real GMs and are really owed;
    minting alongside them would double the pot and leave the contributions
    outstanding. There is no safe silent behaviour here, so there is none.
    """
    if not is_final_por(db, league_id=league_id, season=season):
        raise ChampionshipPotError(
            REASON_WRONG_ERA,
            f"league {league_id} season {season} is governed by the legacy "
            f"ruleset, whose championship pots are funded by per-GM "
            f"contributions. Refusing to mint a league-level pot into it.")


# ── Minting ───────────────────────────────────────────────────────────────────

#: The pillars a mint may target. POINTS is deliberately absent — see the module
#: docstring. Enumerated so the refusal is data, not a forgotten `if`.
MINTABLE_PILLARS: tuple[str, ...] = (PILLAR_FANTASYSTAKES,
                                     PILLAR_FANTASY_FOOTBALL)


def mint_pot(db, *, league_id: int, season: int, pillar: str,
             amount_cents: int, now: datetime | None = None) -> MintResult:
    """Mint one league-level championship pot allocation. Does NOT commit.

    TWO LEGS, NO GM ACCOUNT:

        championship_issuance:{league}:{season}   -amount
        <the pillar's pot account>                +amount

    The posting, the event row and the resulting balances are one transaction by
    construction — the caller's. A crash before its commit leaves nothing; a
    retry after it collides on the deterministic pillar-season key and is a
    no-op, which is what `DuplicateEconomyEvent` signals to the caller.
    """
    now = now or datetime.now(timezone.utc)
    assert_final_por(db, league_id=league_id, season=season)

    if pillar not in CHAMPIONSHIP_PILLARS:
        raise ChampionshipPotError(
            REASON_UNKNOWN_PILLAR,
            f"{pillar!r} is not a governed championship pillar "
            f"(known: {CHAMPIONSHIP_PILLARS}).")
    if pillar not in MINTABLE_PILLARS:
        raise ChampionshipPotError(
            REASON_NOT_MINTABLE,
            f"the {pillar} pot is never minted: its balance is the Skunk "
            f"actually assessed this season (Final POR §12). Minting one would "
            f"let the pot disagree with the fees the league really paid.")
    if int(amount_cents) < 0:
        raise ChampionshipPotError(
            REASON_NEGATIVE_AMOUNT,
            f"cannot mint {amount_cents} cents into the {pillar} pot; a "
            f"championship pot allocation is zero or positive.")

    amount = int(amount_cents)
    account = championship_pot_account(pillar, league_id, season)
    key = pillar_season_key(EVENT_CHAMPIONSHIP_POT_MINT, pillar, league_id,
                            season)

    # A ZERO MINT RECORDS ITS EVENT AND POSTS NOTHING. Same rule WP-4's week
    # close applies to a zero remainder: the event is what makes a replay a
    # no-op, and a zero-amount posting would claim a movement that never
    # happened. `posted` reports which of the two occurred.
    posting_id = None
    if amount > 0:
        posting_id = ledger_post(
            [(championship_issuance_account(league_id, season), -amount),
             (account, amount)],
            door=DOOR_CHAMPIONSHIP_POT_MINT, session=db,
        )
    record_event(db, event_key=key, league_id=league_id, season=season,
                 event_type=EVENT_CHAMPIONSHIP_POT_MINT,
                 amount_cents=amount, posting_id=posting_id, now=now)

    return MintResult(league_id=league_id, season=season, pillar=pillar,
                      account=account, amount_cents=amount, replayed=False,
                      posted=amount > 0)


def fantasystakes_base_pot_cents(db, *, league_id: int, season: int) -> int:
    """Weekly Minimum x Regular-Season Weeks. NOT multiplied by GM count.

    READ FROM THE SAME `resolve_allocation_terms` THAT PRICED THE SEASON, so the
    Base Pot and the Weekly Minimum actually released each week cannot disagree
    about what a Weekly Minimum is. `min_reserve_cents` is already exactly
    `weekly x weeks` on the configured path — it is the same product, and taking
    it rather than re-multiplying means there is no second multiplication site
    that could drift.

    NO TEAM COUNT IS READ HERE, and none is in scope to be read by accident.
    That is the arithmetic §13 turns on: a ten-GM league and a four-GM league on
    the same stops open the same Base Pot.
    """
    from payments.economy_config import resolve_allocation_terms

    terms = resolve_allocation_terms(db, league_id=league_id, season=season)
    if terms.min_reserve_cents is None:
        raise ChampionshipPotError(
            REASON_NO_TERMS,
            f"league {league_id} season {season} resolved no Weekly Minimum "
            f"reserve; the FantasyStakes Base Pot cannot be derived.")
    return int(terms.min_reserve_cents)


def mint_fantasystakes_base_pot(db, *, league_id: int, season: int,
                                now: datetime | None = None) -> MintResult:
    """Mint the FantasyStakes Championship Base Pot. Does NOT commit."""
    return mint_pot(db, league_id=league_id, season=season,
                    pillar=PILLAR_FANTASYSTAKES,
                    amount_cents=fantasystakes_base_pot_cents(
                        db, league_id=league_id, season=season),
                    now=now)


def mint_fantasy_football_pot(db, *, league_id: int, season: int,
                              amount_cents: int,
                              now: datetime | None = None) -> MintResult:
    """Mint the Fantasy Football Championship Pot. Does NOT commit.

    THE AMOUNT IS PASSED IN, NOT DERIVED. §14 makes it one commissioner-entered
    league amount; deriving it from anything would make it a formula the
    commissioner did not choose. Zero is accepted and is a governed choice.
    """
    return mint_pot(db, league_id=league_id, season=season,
                    pillar=PILLAR_FANTASY_FOOTBALL,
                    amount_cents=amount_cents, now=now)


def mint_season_pots(db, *, league_id: int, season: int,
                     fantasy_football_cents: int,
                     now: datetime | None = None) -> tuple[MintResult, ...]:
    """Mint every mintable pot for one league-season. Does NOT commit.

    Called once, by activation, inside the activation transaction — so a season
    that fails to activate has no pots, and a season with pots really was
    activated. Each pillar is independently exactly-once on its own key, so a
    partially completed earlier run converges without re-minting what stands.
    """
    results: list[MintResult] = []
    for pillar, amount in (
        (PILLAR_FANTASYSTAKES,
         fantasystakes_base_pot_cents(db, league_id=league_id, season=season)),
        (PILLAR_FANTASY_FOOTBALL, int(fantasy_football_cents)),
    ):
        savepoint = db.begin_nested()
        try:
            results.append(mint_pot(db, league_id=league_id, season=season,
                                    pillar=pillar, amount_cents=amount,
                                    now=now))
            savepoint.commit()
        except DuplicateEconomyEvent:
            # Already minted by an earlier partially-completed run. Discard only
            # this pillar's savepoint; the pillars already minted stand.
            savepoint.rollback()
            results.append(MintResult(
                league_id=league_id, season=season, pillar=pillar,
                account=championship_pot_account(pillar, league_id, season),
                amount_cents=0, replayed=True, posted=False))
    db.flush()
    return tuple(results)


# ── The one destination for terminal Pool money ───────────────────────────────

def terminal_pool_destination(db, *, league_id: int, season: int) -> str:
    """Where a terminal Prop Pool remainder goes. ONE RESOLUTION, EVERY SITE.

    Four sites move Pool money that no GM won — the weekly division remainder,
    a definition that can never carry, the final-week rollover expiry, and a
    week with no predictors. All four asked for `championship:{league}` by
    literal. §13 makes a terminal remainder a FantasyStakes Championship Pot
    addition under the Final POR, and four literals would have been four places
    to forget.

        RULESET_LEGACY     championship:{league}
        RULESET_FINAL_POR  fantasystakes_championship:{league}:{season}

    WHY THE FANTASYSTAKES POT AND NOT THE POINTS OR FANTASY FOOTBALL ONE.
    Terminal Pool money is FantasyStakes money that was played for and not won.
    The Points pot is the Skunk actually assessed and nothing else; the Fantasy
    Football pot never accretes at all. Only the FantasyStakes pot is defined
    as growing during the season, and §13 names this as one of the three things
    it grows from.
    """
    if is_final_por(db, league_id=league_id, season=season):
        return fantasystakes_championship_account(league_id, season)
    from economy.economy_events import championship_account

    return championship_account(league_id)


# ── Reading ───────────────────────────────────────────────────────────────────

def pot_balances(db, *, league_id: int, season: int) -> PotBalances:
    """Every governed pot for one league-season, derived from the ledger."""
    db.flush()
    return PotBalances(
        league_id=league_id, season=season,
        fantasystakes_cents=_balance_of_in_session(
            db, fantasystakes_championship_account(league_id, season)),
        points_cents=_balance_of_in_session(
            db, points_championship_account(league_id, season)),
        fantasy_football_cents=_balance_of_in_session(
            db, ff_championship_account(league_id, season)),
        minted_cents=-_balance_of_in_session(
            db, championship_issuance_account(league_id, season)),
    )


def no_gm_liability(db, *, league_id: int, season: int) -> bool:
    """Whether minting created any GM-keyed leg. Must always be True.

    THE DIRECT TEST OF MODEL B, asserted rather than argued. Every leg ever
    posted under the mint door is read back and required to be either the
    league-season issuance tally or a governed pot account. A GM-keyed leg
    appearing here would mean a pot was funded by somebody, which is precisely
    the architecture WP-5 retires.
    """
    from sqlalchemy import text

    db.flush()
    rows = db.execute(text(
        "SELECT DISTINCT account FROM ledger_entries WHERE door = :d"),
        {"d": DOOR_CHAMPIONSHIP_POT_MINT}).fetchall()
    permitted = {championship_issuance_account(league_id, season)} | {
        championship_pot_account(p, league_id, season)
        for p in CHAMPIONSHIP_PILLARS}
    return all(r[0] in permitted for r in rows)
