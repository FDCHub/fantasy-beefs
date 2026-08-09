"""
The ONE min-first spend-sourcing implementation (S5-P1 §3).

    1. min:{team}:{week}
    2. wallet:{team}

WHY THIS MODULE EXISTS RATHER THAN A SECOND COPY. Versus funding and the Pool
weekly contribution both spend a GM's money and both must drain the released
Weekly Minimum before touching Wallet. Two implementations of that order would
agree on the day they were written and drift the first time either changed —
and the drift would be invisible, because both would still produce balanced
postings for the right total. Only the ACCOUNTS would differ, and only in weeks
where the split actually bites.

THE CANONICAL IMPLEMENTATION MOVED HERE; IT WAS NOT REWRITTEN. The behaviour is
`economy.challenge_funding.plan_source_split`, which was already conformant.
That name still exists and still works — it now delegates here — so every P1-L4
assertion about ordered funding provenance holds unchanged.

ORDER IS THE PRODUCT, NOT JUST THE AMOUNTS. Refunds replay the sequence
backwards, so "min first" is recorded as position. A caller that returns the
same two amounts in the other order has produced a different, wrong result.

DESTINATION RULES ARE NOT THIS MODULE'S BUSINESS. Winnings, refunds, pushes and
voids credit Wallet only, and nothing here changes that: this function decides
where money is TAKEN FROM, never where it goes back to.
"""

from __future__ import annotations

from economy.economy_events import min_account, wallet_account


def plan_spend_split(db, team_id: int, week: int,
                     required_cents: int) -> list[tuple[str, int]]:
    """Split `required_cents` across this team's sources, MIN FIRST then wallet.

    Returns legs IN FUNDING ORDER as (account, positive amount). Min-only,
    wallet-only and mixed are all valid shapes; a zero-amount leg is never
    returned, because a leg that moved nothing is not history.

    A NEGATIVE min balance is clamped to zero rather than allowed to increase
    the wallet leg. `min:` should never go negative — the ledger guard prevents
    it — but if one ever did, treating it as spendable capacity would silently
    fund from a deficit.
    """
    from ledger.ledger import _balance_of_in_session

    if required_cents <= 0:
        return []

    min_available = max(0, _balance_of_in_session(db, min_account(team_id, week)))
    min_leg = min(min_available, required_cents)
    wallet_leg = required_cents - min_leg

    legs: list[tuple[str, int]] = []
    if min_leg > 0:
        legs.append((min_account(team_id, week), min_leg))
    if wallet_leg > 0:
        legs.append((wallet_account(team_id), wallet_leg))
    return legs


def available_spend_cents(db, team_id: int, week: int) -> int:
    """Total spendable capacity for one team-week, in authoritative cents.

    min + wallet and nothing else. Reserve is excluded on purpose: `reserve:` is
    economically committed to the Championship pot from activation and is never
    spendable. `min_reserve:` is excluded too — it is this season's UNRELEASED
    Weekly Minimum, and only the released week's `min:` may be spent."""
    from ledger.ledger import _balance_of_in_session

    db.flush()
    return (max(0, _balance_of_in_session(db, min_account(team_id, week)))
            + _balance_of_in_session(db, wallet_account(team_id)))