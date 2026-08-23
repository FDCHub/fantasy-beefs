> # ⚠ SUPERSEDED FOR FINAL POR SEASONS
>
> **Superseded by:** `spec/FANTASYSTAKES_FINAL_POR.md`
> **Scope of supersession:** league-seasons stamped `RULESET_FINAL_POR` (2).
> **Still fully governing:** every `RULESET_LEGACY` season — which is every
> season activated before WP-1, and is the state represented by the ABSENCE of a
> `league_season_ruleset` row.
>
> This document is **preserved as historical evidence and is not edited below
> this header.** It remains the correct and complete description of the seasons
> it governed: their championships really were frozen at the playoff boundary,
> really were scored on the regular season alone, really were funded by per-GM
> contributions, and really were recognised on 3/2/1. Those seasons were played,
> settled and in some cases paid out on exactly these rules, and nothing in the
> Final POR is retroactive.
>
> **What the Final POR changes, section by section:**
>
> | Below | Final POR |
> |---|---|
> | §1 Score = matchup net + pool net | **three terms** — minus Skunk Fees (§2 there) |
> | §2 scoring window closes at `playoff_start_week`; postseason results excluded; standings must be frozen | **no boundary and no freeze** — scoring runs through the postseason; LIVE → FINAL → PAID (§8 there). `REASON_POSTSEASON_CONTAMINATED` becomes unreachable: a postseason result is not contamination, it is the competition |
> | §4 pot is per-GM contributions, fixed at activation, funded only by them | **league-level MINTED allocation**; Base = Weekly Minimum × Regular-Season Weeks, **not × GM count**; and it **grows** — sweeps, Top-Offs, terminal Pool remainders (§5 there) |
> | §4 "Weekly Minimum shortfalls … are returned to the originating GM at season end" | **forfeited to the FantasyStakes Championship Pot at WEEK close**; never returned, never re-entering `expired_min:` (§4 there) |
> | §6 Grand Champion on 3/2/1 points | **finalized championship VC across funded pillars**, at least two funded; PLACEHOLDER / LIVE / FINAL (§11 there) |
> | §6 Regular Season Points Champion excluded from Grand Champion | **the Points Championship is one of the three pillars** and counts when funded |
> | §7 "standings are final/frozen even though postseason play may continue" | the first tab stays **live through the postseason** |
>
> **What is NOT superseded and remains in force verbatim:**
>
> - §1's product principle — *Credits determine how much you can play;
>   competitive results determine whether you are winning.* Wallet balance is
>   still not Championship Score, and the list of noncompetitive movements that
>   never increase it is still correct.
> - §3's tie rule — exact equal scores are **real ties**, and no team-id,
>   wallet-balance, wager-count or win-count breaks one. Stable id ordering is
>   for display and for indivisible one-cent remainders only.
> - §5's distribution arithmetic — 60/30/10, pooled-and-split dead heats, integer
>   cents conserved, remainder by ascending canonical team id. The Final POR
>   makes this the **one** implementation for all three pillars.

# FantasyStakes 1.0 RC2 — Championship POR

Status: **LOCKED PRODUCT OWNER RULING — SUPERSEDED FOR FINAL POR SEASONS**
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

When either component championship contains a tie, the Grand Champion points for the ordinal places occupied by that tied group are pooled and divided equally among every GM in the tie. This preserves the total points available from the component championship and does not use display ordering as a competitive tiebreaker.

Examples:

- two-way tie for 1st: `(3 + 2) / 2 = 2.5` Grand Champion points each
- two-way tie for 2nd: `(2 + 1) / 2 = 1.5` points each
- three-way tie for 1st: `(3 + 2 + 1) / 3 = 2` points each
- a tie group extending beyond 3rd shares only the 1st/2nd/3rd points occupied by that group

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
