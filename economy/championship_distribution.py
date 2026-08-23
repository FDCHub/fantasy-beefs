"""
economy/championship_distribution.py — THE canonical championship split (WP-10).

ONE IMPLEMENTATION, THREE PILLARS. The Final POR §17 fixes 60/30/10 and the
dead-heat rule as PRODUCT rules, not commissioner settings, and requires one
implementation for the Regular-Season Points Championship, the FantasyStakes
Championship and the Fantasy Football Championship alike.

── WHAT THIS REPLACES, AND WHY IT MATTERED ─────────────────────────────────

Three implementations existed, and TWO OF THEM DISAGREED about ties:

    economy/championship.py::championship_distribution
        floors each place and gives the ENTIRE remainder to first place. It has
        no concept of a tie at all: it takes an already-ordered list of three
        team ids and pays them 60/30/10 in that order. A genuine two-way tie
        for first would be paid 60 and 30 by whatever order the caller happened
        to build — a competitive outcome decided by list construction.

    reports/championship_read_model.py::tied_championship_distribution
        pools the allocations of the ordinal places a tied group occupies and
        splits them equally. This IS the Final POR §17 rule, and it is the one
        preserved here — moved, not rewritten.

    reports/standings.py::DEFAULT_PAYOUT_SPLIT
        the bare `[60, 30, 10]` list, with no arithmetic attached.

Collapsing them was not tidying. Two pillars paying the same tie differently is
a real difference in who receives Credits, and nothing in the codebase forced
the two to agree.

── THE RULE, STATED ONCE ───────────────────────────────────────────────────

    1st 60%   2nd 30%   3rd 10%

ONE STRUCTURAL EXCEPTION, AND ONLY ONE. A Fantasy Football playoff format with
exactly two teams has no third-place game to win, so it pays 67/33 —
`TWO_TEAM_PLAYOFF_SPLIT` below. Everything else in this module is unchanged by
it: the same flooring, the same remainder-to-first rule and the same dead-heat
pooling apply to a two-place split, because `split` has always been a parameter
and none of the arithmetic below counts to three.

Percentage flooring leaves a remainder; it goes IN FULL to the first ordinal
slot, so the pot is conserved exactly. That is the accepted rule and is
unchanged from both predecessors.

DEAD HEAT. A tied group occupying ordinal places p..p+n-1 pools the allocations
of exactly those places and divides them equally. Every GM in the group is
recorded at the HIGHEST place the group occupies, and the next finisher takes
the place AFTER the group. §17's three worked examples:

    tie for 1st  (60 + 30) / 2 = 45 each; next finisher is 3rd
    tie for 2nd  (30 + 10) / 2 = 20 each; there is no separate 3rd award
    tie for 3rd  (10 +  0) / 2 =  5 each

A group extending past third shares only the paid slots it actually occupies —
which is why the third example is 10/2 and not 10.

── EXACT CENTS, AND WHERE THE ONE INDIVISIBLE CENT GOES ────────────────────

Integer cents throughout; no float participates. When an equal split does not
divide — three GMs sharing 100% of an odd pot — the remainder is assigned one
cent at a time by ASCENDING CANONICAL TEAM ID. That is the same remainder
convention `economy/skunk.py::split_by_canonical_id` and POR §6.3's pool payouts
already use, and it is ARITHMETIC DETERMINISM ONLY: it decides which GM holds an
extra cent, never who placed where. Rounding for display is a presentation
decision made elsewhere and never here.

── RANKING IS THE CALLER'S, AND EQUALITY IS A REAL TIE ─────────────────────

This module does not compute standings. It is given each GM's authoritative
rank VALUE — FantasyStakes Score, regular-season Points For, or a podium
ordinal — and equal values are a genuine dead heat. It never breaks one.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

#: The product's championship split. NOT a commissioner setting (Final POR §17).
CHAMPIONSHIP_SPLIT: tuple[int, int, int] = (60, 30, 10)

#: THE TWO-TEAM PLAYOFF SPLIT — owner ruling, Fantasy Football Championship.
#:
#: A playoff format containing EXACTLY TWO teams has one round, one game and
#: therefore no official third-place game to win. There is no third place to
#: pay, so the three-place split cannot apply: 60/30 of a pot leaves 10% with
#: nobody to give it to, and this module conserves the pot exactly rather than
#: stranding a tenth of it.
#:
#: 67/33 IS THE RULING, NOT A DERIVATION. It is close to 60/30 re-normalised
#: (66.67/33.33) but it is not that number, and nothing here computes it —
#: writing it as arithmetic would invite a future edit to "correct" the
#: rounding and quietly change a payout.
#:
#: THIS IS NOT A FALLBACK FOR MISSING DATA, and that distinction is the whole
#: of the ruling. It applies only when the official playoff STRUCTURE has no
#: third-place game. A three-or-more-team format whose third-place result is
#: missing, unavailable or ambiguous stays FAIL-CLOSED and must never be paid
#: as 67/33 — see `economy/ff_championship_settlement.py`, which is the only
#: caller and states the test in one place.
#:
#: NOT A COMMISSIONER SETTING, exactly as CHAMPIONSHIP_SPLIT is not.
TWO_TEAM_PLAYOFF_SPLIT: tuple[int, int] = (67, 33)


@dataclass(frozen=True)
class Placement:
    """One GM's finish and award in one championship.

    `place` is COMPETITION-STYLE and is the highest ordinal the GM's tied group
    occupies: a two-way tie for first produces two rows at place 1 and the next
    finisher at place 3. `tied` says whether the award was shared, so a surface
    can explain a halved figure without re-deriving the grouping.

    A GM outside the paid places still gets a Placement, with `amount_cents` 0.
    Reporting the whole field is what lets a standings surface show every
    finisher; omitting the unpaid rows would make "who came fourth" unanswerable
    from this result.
    """

    team_id: int
    place: int
    rank_value: int
    amount_cents: int
    tied: bool


def _reject_non_int(value: object, label: str) -> int:
    """bool is a subclass of int; True/False here is a caller mistake, not a
    number. Rejected explicitly rather than allowed to arithmetic as 1/0."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{label} must be an int, got {type(value).__name__}: {value!r}")
    return value


def slot_amounts(total_cents: int,
                 split: tuple[int, ...] = CHAMPIONSHIP_SPLIT) -> list[int]:
    """The three ordinal allocations in exact cents, conserving the pot.

    Separated from the placement logic so a commissioner surface can show what
    each place is worth BEFORE anyone has finished, without going near the tie
    rule or inventing a second copy of the percentages.
    """
    _reject_non_int(total_cents, "total_cents")
    if total_cents < 0:
        raise ValueError(f"total_cents must be non-negative, got {total_cents}")
    if sum(split) != 100:
        raise ValueError(f"split must sum to 100, got {sum(split)} from {split!r}")

    amounts = [total_cents * pct // 100 for pct in split]
    # RULE 2 — the entire flooring remainder goes to first place. Not spread,
    # not rounded to nearest, not dropped.
    amounts[0] += total_cents - sum(amounts)
    return amounts


def distribute_championship(
    total_cents: int,
    standings,
    split: tuple[int, ...] = CHAMPIONSHIP_SPLIT,
) -> tuple[Placement, ...]:
    """Award `total_cents` over `standings` by 60/30/10 with the dead-heat rule.

    `standings` is any iterable of `(team_id, rank_value)` where a HIGHER
    `rank_value` is a better finish and EQUAL values are a real tie. Every
    pillar can supply one:

        FantasyStakes   the GM's FantasyStakes Score in cents
        Points          cumulative regular-season Points For, scaled to an int
        Fantasy Football a podium ordinal (3, 2, 1) from the provider bracket

    Returns one `Placement` per GM, ordered by place then canonical team id.

    CONSERVATION IS ASSERTED, NOT ASSUMED. The awards must total exactly
    `total_cents`; a mismatch raises rather than paying a pot that does not add
    up. An EMPTY field returns no placements and is only legal for an empty pot
    — a funded championship with nobody in it is a caller bug, not a rounding
    question.
    """
    rows = [(int(_reject_non_int(t, "team_id")),
             int(_reject_non_int(v, "rank_value"))) for t, v in standings]
    if len({t for t, _ in rows}) != len(rows):
        dupes = sorted({t for t, _ in rows if [x for x, _ in rows].count(t) > 1})
        raise ValueError(f"standings contain duplicate team ids: {dupes}")

    amounts = slot_amounts(total_cents, split)

    if not rows:
        if total_cents:
            raise ValueError(
                f"cannot distribute {total_cents} cents over an empty field")
        return ()

    ordered = sorted(rows, key=lambda pair: (-pair[1], pair[0]))

    placements: list[Placement] = []
    cursor = 0
    for rank_value, grouped in groupby(ordered, key=lambda pair: pair[1]):
        group = sorted(t for t, _ in grouped)
        place = cursor + 1

        # THE SLOTS THIS GROUP OCCUPIES, clamped to the paid places. A group
        # starting at or past the fourth ordinal occupies no paid slot and its
        # pooled prize is legitimately zero.
        first_slot = cursor
        last_slot = min(cursor + len(group), len(amounts))
        pooled = sum(amounts[first_slot:last_slot]) if first_slot < len(amounts) else 0

        base, remainder = divmod(pooled, len(group))
        for index, team_id in enumerate(group):
            placements.append(Placement(
                team_id=team_id,
                place=place,
                rank_value=rank_value,
                # ASCENDING CANONICAL TEAM ID takes the indivisible cent —
                # arithmetic determinism, never a competitive tiebreak.
                amount_cents=base + (1 if index < remainder else 0),
                tied=len(group) > 1,
            ))
        cursor += len(group)

    paid = sum(p.amount_cents for p in placements)
    if paid != total_cents:
        raise AssertionError(
            f"championship distribution paid {paid} of a {total_cents} pot; "
            f"the split must conserve the pot exactly")

    return tuple(sorted(placements, key=lambda p: (p.place, p.team_id)))


def podium_standings(team_ids) -> tuple[tuple[int, int], ...]:
    """Turn an ORDERED podium into `standings` pairs, best first.

    For a pillar whose result is a bracket rather than a score — the Fantasy
    Football Championship — the provider states an order and there is no rank
    value to compare. Descending ordinals give every finisher a distinct value,
    so `distribute_championship` reports no tie, which is correct: a knockout
    bracket produces one champion, one runner-up and one third.

    A CALLER THAT CANNOT ORDER ITS PODIUM MUST NOT CALL THIS. Passing a guessed
    order silently pays the wrong GMs, and no validation here can detect it —
    the same contract the predecessor arithmetic carried.
    """
    ordered = list(team_ids)
    if len(set(ordered)) != len(ordered):
        raise ValueError(f"podium names a team twice: {ordered!r}")
    return tuple((int(t), len(ordered) - i) for i, t in enumerate(ordered))
