# FantasyStakes 1.0 RC2 — Championship POR

Status: **LOCKED PRODUCT OWNER RULING**  
Release line: `release/fantasystakes-1.0.0-rc2`  
RC1 remains immutable at `fantasystakes-1.0.0-rc1`.

## 1. FantasyStakes Championship

The FantasyStakes Season Champion is the GM with the highest **total realized net winnings** from settled FantasyStakes matchups and FantasyStakes prop pools when the FantasyStakes championship scoring window becomes final.

### Championship Score

`FantasyStakes Championship Score = realized matchup net + realized prop-pool net`

Only competitive results count. Wallet balance is not Championship Score.

The following never increase Championship Score merely by moving Credits:

- Season-Opening Allocation
- top-offs
- Weekly Minimum releases, expiries, or end-of-season returns
- championship reserves or distributions
- refunds and administrative corrections
- any other noncompetitive Credit movement

Product principle:

> Credits determine how much you can play. Competitive results determine whether you are winning.

Bet volume is a legitimate strategy only because it creates additional opportunities to produce realized net winnings. Obtaining additional playable Credits does not itself improve Championship Score.

## 2. Championship scoring window

The FantasyStakes Championship race runs through the Yahoo regular season.

The scoring window closes at the boundary immediately before `playoff_start_week`. FantasyStakes Championship standings must be frozen before postseason FantasyStakes economic activity is allowed to affect the live competitive ledger.

During the Yahoo postseason:

- FantasyStakes play may continue.
- Wins and losses continue to move Credits.
- Ledger and wallet reconciliation continue normally.
- Postseason FantasyStakes results are excluded from FantasyStakes Championship Score.
- Postseason FantasyStakes results are excluded from the Grand Champion calculation.

A championship freeze must refuse while any regular-season FantasyStakes matchup or prop-pool result that can change Championship Score remains unsettled.

## 3. FantasyStakes Championship podium

Final FantasyStakes Championship placement is determined from the frozen Championship Score:

1. FantasyStakes Season Champion
2. FantasyStakes Runner-Up
3. FantasyStakes Third Place

Exact equal Championship Scores are real ties. No team-id, wallet-balance, wager-count, win-count, or other secondary performance tiebreaker decides championship entitlement.

A stable team-id ordering may be used only for deterministic display and for assigning indivisible one-cent arithmetic remainders. It is not a competitive tiebreaker.

## 4. FantasyStakes Championship Pot

Each league-season has two independently commissioner-editable championship contributions before activation:

- Yahoo Championship Contribution per GM
- FantasyStakes Championship Contribution per GM

The FantasyStakes contribution defaults to the same amount as the Yahoo contribution, but either may be edited independently before activation. Both freeze at season activation.

Default 14-week example:

- Weekly Play Reserve: $140
- Yahoo Championship Contribution: $80
- FantasyStakes Championship Contribution: $80
- Season-Opening Allocation: $300 per GM

These are defaults, not hardcoded league amounts.

The FantasyStakes Championship Pot is fixed at season activation and is funded only by the FantasyStakes Championship contributions. It does not grow from top-offs, Weekly Minimum shortfalls, wallet remnants, pool remainders, expired Credits, or other in-season movements.

Weekly Minimum shortfalls remain outside circulation under their existing rule and are returned to the originating GM at season end; they do not fund either championship.

## 5. FantasyStakes Championship distribution

The FantasyStakes Championship Pot is allocated 60% / 30% / 10% to the first three ordinal championship places.

When GMs tie, the prize shares for the ordinal places occupied by that tied group are combined and divided equally among every GM in the tie.

Examples:

- two-way tie for 1st: 60% + 30% is combined and split equally; the next place receives 10%
- two-way tie for 2nd: 30% + 10% is combined and split equally
- three-way tie for 1st: 60% + 30% + 10% is combined and split equally
- a tie group extending beyond 3rd shares only the top-three prize shares that the group occupies

Integer cents are conserved. Any indivisible cent remainder inside an equal tied split is assigned deterministically by ascending canonical team id solely as an arithmetic remainder rule.

## 6. Grand Champion

**Grand Champion** is the product name and POR.

The Grand Champion is the GM with the best combined finish across:

- the Yahoo Championship, and
- the FantasyStakes Championship.

There is no separate Grand Champion pot and no additional Season-Opening Allocation for it. It is a season-ending recognition.

Base scoring:

| Finish | Yahoo Championship | FantasyStakes Championship |
|---|---:|---:|
| 1st | 3 | 3 |
| 2nd | 2 | 2 |
| 3rd | 1 | 1 |

The highest combined score is Grand Champion. Equal highest combined scores produce co-Grand Champions; there is no Grand Champion tiebreaker.

**Open implementation detail:** how component points are assigned when the Yahoo or FantasyStakes championship itself contains a tie must be owner-ruled before Grand Champion settlement/final recognition is encoded. Do not infer a rule from display ordering.

The Regular Season Points Champion / Skunk award is not part of the Grand Champion calculation in RC2.

## 7. UI intent

During the Yahoo regular season, the first tab presents the FantasyStakes Championship Chase.

After the scoring cutoff, the FantasyStakes Championship standings are final/frozen even though postseason FantasyStakes play may continue for Credits.

After the Yahoo postseason becomes final, the first tab transitions to season results and prominently recognizes:

- Grand Champion
- Yahoo Championship podium
- FantasyStakes Championship podium
- Regular Season Points Champion

Grand Champion is not presented as a speculative live third championship race during the season.
