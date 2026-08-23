> # ⚠ PARTIALLY SUPERSEDED FOR FINAL POR SEASONS
>
> **Superseded by:** `spec/FANTASYSTAKES_FINAL_POR.md`
> **Scope:** league-seasons stamped `RULESET_FINAL_POR` (2) only. Every
> `RULESET_LEGACY` season — the state represented by the ABSENCE of a
> `league_season_ruleset` row — is governed by this document unchanged.
>
> **PARTIALLY, and the parts matter.** Most of this section is untouched: 4.2
> issuance, 4.3 availability, 4.4 escrow, 4.5's definition of what counts toward
> the Weekly Minimum and when it is evaluated, 4.6's non-negative Wallet law, and
> the whole of 4.9 season close except where named below. This document is
> **preserved as historical evidence and is not edited below this header.**
>
> **The rules the Final POR supersedes, by identifier:**
>
> | Rule | Said | Final POR |
> |---|---|---|
> | **BAB-401/402** Championship Pot funding | one League-season pot accumulating from Weekly Minimum shortfalls, Pool remainders, rollover sweeps, periodic contributions and season-end `reserve:{team_id}` sweeps | **three season-scoped pots**, each funded differently and none from a per-GM reserve. `reserve:{team}` is retired; `championship:{league}` is retired. FantasyStakes is **minted** at Weekly Minimum × Regular-Season Weeks and grows from sweeps, Top-Offs and terminal Pool remainders; Points is **never minted** and is the Skunk actually assessed; Fantasy Football is one commissioner-entered amount, may be 0, and **never accretes** (§5 there) |
> | **BAB-404/405** distribution rule and eligibility | League Configuration defines recipients and percentages; the Yahoo season result determines them | 60/30/10 is a **product rule, not a commissioner setting**, and it is one implementation for all three pillars. Only the Fantasy Football pillar is decided by the Yahoo result; FantasyStakes is decided by FantasyStakes Score and Points by regular-season Points For (§9, §10 there) |
> | **BAB-407** remainder in final Yahoo standing order | | remainder to the **first ordinal slot**, and an indivisible cent inside a dead heat by **ascending canonical team id** (§10 there) |
> | **BAB-506** Skunk Pot awarded whole to the highest Points For | | the Points Championship pays **60/30/10** with the dead-heat rule (§9a there) |
> | **BAB-508** distributed after regular-season finalization | | unchanged in timing, but the gate is now every regular-season week being **economically final** by `finalized_at`, since a provider correction lands as a re-finalised matchup (§9a there) |
> | **BAB-607** Top-Off posting sequence | balanced issuance to the Wallet | a **third leg**: `bab_issuance −2X`, `wallet +X`, `fantasystakes_championship +X`. The GM's obligation remains **X** (§6 there) |
> | **4.5 [HYBRID]** Weekly Minimum shortfall handling and the Reserve/Frozen mechanic | shortfall swept, remainder becomes a collected obligation; unspent Minimum out of circulation and returned at season end | the unspent Weekly Minimum is **forfeited to the FantasyStakes Championship Pot at WEEK close** and never returned. The shortfall sweep is **retired** for this era — it would charge the same GM twice for the same week (§4 there) |
>
> **BAB-503's tie rule is NOT superseded** and is in force verbatim: a tied
> weekly Skunk is divided equally, remainder one cent at a time in ascending GM
> identifier order. **BAB-501's optionality is likewise unchanged** and is what
> the Final POR builds on when it admits a Skunk Fee of 0.

# Fantasy Beefs — Merged Hybrid · Section 4 — BAB Economy

*Issuance, availability, escrow, minimum participation, pots, top-offs, and
season close.*

> **[HYBRID] Section-level note.** Adds the Reserve/Frozen mechanic (Row 6), the
> five-stop commissioner economy slider and $1 bet floor (Row 7), and the
> Weekly-Minimum auto-sourcing sequence (Row 5). All money-path items
> **[OPUS-GATED]**.

## 4.1 Purpose

The BAB Economy governs the creation, availability, reservation, transfer,
contribution, distribution, and retirement of BAB. All BAB balances SHALL be
derived from the Ledger and all BAB movement SHALL comply with Sections 3 and 4.

## 4.2 BAB Principles

**BAB-001 — Exclusive Currency**
BAB is the only currency recognized inside Fantasy Beefs. No wager, Pool, Pot,
fee, or settlement may be denominated in another unit.

**BAB-002 — No Real-Money Custody**
Fantasy Beefs SHALL NOT receive, hold, transmit, convert, or settle real money.
Any offline reconciliation between league members occurs outside the platform and
has no effect on BAB protocol state.

**BAB-003 — Integer Precision**
BAB SHALL be stored and transferred in integer BAB cents. Fractional BAB cents
are prohibited.

**BAB-004 — Ledger Authority**
Every BAB balance SHALL equal the balance derived from posted Ledger entries.
Displayed balances SHALL NOT be authoritative when inconsistent with the Ledger.

**BAB-005 — No Negative Balances**
No Wallet, Escrow account, Championship Pot, Skunk Pot, rollover account, or
protocol account SHALL become negative.

**BAB-006 — No Unfunded Exposure**
A GM SHALL NOT accept or enter any wager whose maximum possible loss exceeds
available BAB.

**BAB-007 — Conservation**
BAB SHALL be created only through protocol-defined issuance and retired only
through protocol-defined retirement. Transfers, wagers, refunds, and Pot
movements SHALL conserve total BAB.

## 4.3 Wallets

**BAB-101 — GM Wallet**
Each GM SHALL have one Wallet for each League season. A Wallet contains BAB
currently available to that GM, excluding all BAB held in Escrow or protocol Pot
accounts.

**BAB-102 — Initial Allocation**
At season initialization, every eligible GM SHALL receive the League-configured
initial BAB allocation unless Section 7 expressly defines a permitted alternate
allocation rule.

**BAB-103 — Equal Initial Allocation**
Unless explicitly configured otherwise before the first accepted wager, all GMs
in the same League season SHALL receive the same initial BAB allocation.

**BAB-104 — Available BAB**
Available BAB equals the posted Wallet balance. Escrow SHALL be held in separate
Ledger accounts and SHALL NOT be subtracted a second time from the Wallet
display.

**BAB-105 — Wallet Changes**
A Wallet balance may change only through a posted Ledger transaction generated by
an accepted protocol event, including issuance, escrow reservation, escrow
release, settlement, Pot distribution, approved Top-Off, or correction by
compensating transaction.

**BAB-106 — No Manual Editing**
No GM, Commissioner, or administrator may directly edit a Wallet balance.

> **[HYBRID] BAB-107 — Reserve Split at Buy-In (Row 6).** When Reserve is
> enabled, the configured buy-in splits at initialization into a wagerable Wallet
> portion and a `reserve:{team_id}` portion (default 4/11 = 36.4% of buy-in). The
> Reserve portion is not wagerable. (Row 6.) **[OPUS-GATED]**
>
> **[HYBRID] BAB-108 — Weekly Reserve Release (Row 6).** Reserve releases to the
> Wallet weekly by the reserve-ceiling formula: released amount is governed so
> the remaining reserve never falls below (remaining weeks × weekly-minimum). The
> release makes previously-reserved BAB wagerable. **[OPUS-GATED]**
>
> **[HYBRID] BAB-109 — Weekly-Minimum Sourcing Sequence (Row 5).** A GM never
> chooses a funding source. Accepted-bet spend draws from `min:{team}:{week}`
> first (funded at weekly release, default $10 at the default stop), then from
> Wallet. Winnings always land in Wallet, never back into min (one-directional).
> Min debits at ACCEPTANCE for Versus bets (matched money only) and at PLACEMENT
> for Pool bets. **[OPUS-GATED]**

## 4.4 Escrow

**BAB-201 — Escrow Purpose**
Escrow reserves BAB that may be lost, paid, refunded, or redistributed when an
unresolved wager settles.

**BAB-202 — Full Funding**
Before a wager becomes Accepted or Pending, the maximum possible BAB loss of
every obligated participant SHALL be fully reserved in Escrow.

**BAB-203 — Locked Challenge Escrow**
A Locked Challenge SHALL reserve the accepted maximum possible loss when the
challenge is accepted.

**BAB-204 — Dynamic Challenge Escrow**
A Dynamic Challenge SHALL reserve the Handshake maximum possible loss when
accepted. Final Lock MAY reduce the reservation but SHALL NOT increase it.

**BAB-205 — Pool Escrow**
A Prediction Pool entry fee SHALL move from the entrant Wallet to Pool Escrow when
the ticket is created. A Rank Pool contribution SHALL move to Pool Escrow at the
protocol-defined collection event.

**BAB-206 — Escrow Ownership**
Escrow SHALL retain the identity of its originating Wallet until settlement
transfers ownership or refunds the BAB.

**BAB-207 — Unavailable BAB**
BAB held in Escrow SHALL NOT be used for another wager, Top-Off offset, Pot
contribution, or withdrawal.

**BAB-208 — Permitted Releases**
Escrow may be released only by: final settlement; Push refund; Void refund;
protocol-defined cancellation refund; Dynamic Final Lock refund under The
Adjustment; Pool rollover or Pot transfer expressly required by protocol.

**BAB-209 — Zero Escrow at Completion**
A terminal wager SHALL have zero remaining Escrow after all settlement Ledger
entries post.

> **[HYBRID] BAB-210 — Escrow-at-Issue and Pending Bucket (money-model).** The
> issuer's Anchor Stake escrows at ISSUE, not only at accept. A pending-bucket
> value (Wallet + remaining min, minus all pending and locked commitments) gates
> every new bet so a GM can never commit more than he holds. Reversal on decline
> or expiry returns the issue-time escrow to Wallet/min. **[OPUS-GATED]**

## 4.5 Weekly Minimum

**BAB-301 — Optional Requirement**
A League MAY configure a Weekly Minimum BAB commitment that applies equally to all
active GMs for each applicable Fantasy Week.

**BAB-302 — Applicable Weeks**
League Configuration SHALL identify the first and last Fantasy Weeks to which the
Weekly Minimum applies. No assessment may occur outside that range.

> **[HYBRID]** No mandatory Weekly Minimum applies in playoff weeks (default
> 15–17); only the $1 structural bet floor applies there. New nullable config:
> `playoff_start_week` (fallback 15), `season_final_week` (fallback 17). (Postseason ruling.)

**BAB-303 — Qualifying Commitment**
BAB counts toward a GM's Weekly Minimum when it becomes committed through an
accepted Versus Bet, a funded Prediction Pool ticket, or a protocol-defined Rank
Pool contribution for that Fantasy Week.

**BAB-304 — Commitment Measurement**
The qualifying amount is the GM's maximum BAB at risk or nonrefundable Pool
contribution when the wager is accepted or entered. Potential winnings, refunded
excess Dynamic Escrow, and amounts merely offered SHALL NOT count.

**BAB-305 — No Double Counting**
The same BAB commitment SHALL count once toward the Weekly Minimum even if
referenced by multiple records or later redistributed through settlement.

**BAB-306 — Evaluation Time**
Weekly Minimum evaluation SHALL occur after wagering closes for the applicable
Fantasy Week and before season-end Pot distribution.

**BAB-307 — Shortfall Formula**
A GM's Weekly Minimum shortfall equals the configured Weekly Minimum minus that
GM's qualifying commitments for the week, but not less than zero.

**BAB-308 — Shortfall Contribution**
A positive shortfall SHALL be transferred from the GM Wallet to the Championship
Pot through the Ledger.

> **[HYBRID]** When the commissioner selects Frozen as the destination (locked at
> season kickoff), the shortfall/unspent-min credits `frozen:{team_id}` instead
> of Championship. (Row 6.)

**BAB-309 — Insufficient Wallet for Shortfall**
If a GM lacks sufficient Wallet BAB to pay a Weekly Minimum shortfall, the System
SHALL transfer the available Wallet balance and record the remaining unpaid
shortfall as a protocol obligation. The obligation SHALL be satisfied
automatically from the next BAB credited to that Wallet before the BAB becomes
available for wagering.

**BAB-310 — Shortfall Priority**
Outstanding Weekly Minimum obligations SHALL be collected before discretionary
Top-Off-funded wagering, Pot distributions, or new wager commitments.

**BAB-311 — Outcome Independence**
A wager counts toward the Weekly Minimum regardless of whether it later wins,
loses, Pushes, or Voids, except that a wager voided because it was never valid
SHALL NOT count.

## 4.6 Championship Pot

**BAB-401 — Championship Pot Purpose**
The Championship Pot is a League-season BAB account accumulated for season-end
distribution under League Configuration.

**BAB-402 — Permitted Funding Sources**
The Championship Pot MAY receive BAB only from: Weekly Minimum shortfalls; Pool
payout remainders; season-end Pool rollover sweeps; League-configured periodic
contributions; other sources expressly defined by this Specification.

> **[HYBRID]** Add funding sources (Row 6): season-end Reserve sweeps
> (`reserve:{team_id}` remaining balances); Versus/Pool indivisible remainders
> per the applicable remainder rule. Note the two distinct remainder rules: Pool
> splits route remainders here (GE-1045); Versus derivation does NOT (floor-both,
> Row 3, residue uncollected).

**BAB-403 — No Midseason Distribution**
Championship Pot BAB SHALL remain unavailable to GMs until the protocol-defined
season-end distribution event.

**BAB-404 — Distribution Rule**
League Configuration SHALL define the eligible recipient or recipients and the
distribution percentages or ranking formula before the first accepted wager.

> **[HYBRID]** Default distribution is 60/30/10 (1st/2nd/3rd) by final Yahoo
> regular-season result. Leftover cents from floor-division go to 1st place so
> payouts sum exactly. (Row 6.)

**BAB-405 — Distribution Eligibility**
Only the official Yahoo season result identified by League Configuration SHALL
determine Championship Pot recipients.

**BAB-406 — Distribution Timing**
The Championship Pot SHALL be distributed only after all season wagers and Pools
are terminal, all outstanding rollovers have been swept or otherwise resolved,
and the Ledger has passed reconciliation.

**BAB-407 — Equal-Split Remainder**
Any indivisible BAB-cent remainder created by Championship Pot distribution SHALL
be assigned according to the League-configured remainder rule. If no separate
rule is configured, the remainder SHALL be awarded one BAB cent at a time in
final Yahoo standing order, beginning with the highest-ranked recipient.

**BAB-408 — No Commissioner Discretion**
The Commissioner SHALL NOT alter Championship Pot recipients, percentages, or
payout order after the first accepted wager.

## 4.7 Skunk Pot

**BAB-501 — Optional Pot**
A League MAY enable one Skunk Pot for the season.

**BAB-502 — Weekly Skunk Definition**
Unless League Configuration expressly adopts another deterministic definition
before the first accepted wager, the Weekly Skunk is the GM with the largest
margin of defeat in the official Yahoo weekly matchups.

**BAB-503 — Skunk Tie**
If multiple GMs tie for the largest margin of defeat, the configured weekly Skunk
contribution SHALL be divided equally among the tied GMs. Any indivisible BAB-cent
remainder SHALL be assessed one cent at a time in ascending GM identifier order.

**BAB-504 — Weekly Contribution**
Each Weekly Skunk SHALL contribute the League-configured Skunk amount to the Skunk
Pot after Yahoo finalization for that week.

> **[HYBRID]** Default weekly Skunk amount $10; regular season only (weeks 1–14),
> never playoffs. The contribution is an off-wallet obligation (added to dues
> owed, not spendable-balance math). Accumulates up to $140/season. (Skunk Fee
> ruling.) The obligation's pre-settlement home (`receivable:{team_id}` candidate)
> is **[OPUS-GATED]** open.

**BAB-505 — Insufficient Wallet**
If a Weekly Skunk lacks sufficient Wallet BAB, the available balance SHALL
transfer immediately and the unpaid remainder SHALL become a protocol obligation
collected from future Wallet credits before new wagering is allowed.

**BAB-506 — Default Season Winner**
Unless League Configuration defines another deterministic recipient before the
first accepted wager, the Skunk Pot SHALL be awarded to the GM with the highest
cumulative Yahoo regular-season Points For.

**BAB-507 — Skunk Pot Winner Tie**
If multiple GMs tie for the Skunk Pot winning metric, the Pot SHALL be divided
equally. Any indivisible remainder SHALL be awarded one BAB cent at a time in
ascending GM identifier order.

**BAB-508 — Distribution Timing**
The Skunk Pot SHALL be distributed after Yahoo regular-season finalization and
after all weekly Skunk assessments have posted.

**BAB-509 — No Self-Exemption**
A GM may not decline, waive, redirect, or replace a protocol-defined Skunk
contribution or award.

## 4.8 BAB Top-Offs

**BAB-601 — Top-Off Purpose**
A BAB Top-Off is protocol-defined issuance that increases one GM Wallet during an
active League season.

**BAB-602 — GM Request**
A Top-Off request SHALL identify the requesting GM, League season, amount, request
timestamp, and any League-configured external reference.

**BAB-603 — Positive Amount**
A Top-Off amount SHALL be a positive integer number of BAB cents and SHALL satisfy
any League-configured minimum, maximum, or increment.

**BAB-604 — Commissioner Approval**
A Top-Off SHALL require approval by an authorized Commissioner. The Commissioner
may approve or reject the request but may not change the requested amount; a
different amount requires a new request.

**BAB-605 — No Self-Approval**
A Commissioner SHALL NOT approve their own Top-Off request. If all Commissioners
are request participants, the League-configured alternate approver SHALL act. If
no alternate exists, the request SHALL remain pending and no BAB shall issue.

**BAB-606 — Single Execution**
An approved Top-Off SHALL post exactly once. Repeated approval requests SHALL
return the original result without additional issuance.

**BAB-607 — Posting Sequence**
1. Validate the pending request and approver authority.
2. Verify the request remains within all League-configured Top-Off limits.
3. Create the balanced issuance Ledger transaction.
4. Apply any outstanding protocol obligations before releasing residual BAB to
   the Wallet.
5. Record the approval and posting audit entries.
6. Mark the Top-Off request Approved and Final.

**BAB-608 — Rejected or Withdrawn Request**
A rejected or withdrawn Top-Off request SHALL issue no BAB and SHALL create no
Wallet or Pot movement.

**BAB-609 — Top-Off Audit**
Every approved or rejected Top-Off SHALL permanently record the requester, amount,
timestamps, approver, decision, Specification version, and resulting Ledger
transaction ID when applicable.

**BAB-610 — No Retroactive Top-Off**
A Top-Off SHALL NOT be backdated to fund a wager that previously failed, expired,
or was rejected for insufficient BAB.

> **[HYBRID]** Topped-off BAB is "above-and-beyond" — pure free-to-spend Wallet
> money, not subject to the reserve ceiling. Every top-off is a real obligation,
> reconciled at season end. **[PENDING CODE-VERIFY]** — the deposit path
> currently writes off-ledger; must route through LED postings.

## 4.9 Protocol Obligations

**BAB-701 — Obligation Scope**
A protocol obligation is BAB owed by a GM because a mandatory Weekly Minimum or
Skunk contribution could not be fully collected from the Wallet.

**BAB-702 — Collection Priority**
When BAB is later credited to a GM with an outstanding obligation, the System
SHALL collect obligations before any remaining BAB becomes available in the
Wallet.

**BAB-703 — Collection Order**
Obligations SHALL be collected in chronological order by creation timestamp. Ties
SHALL be resolved by obligation ID.

**BAB-704 — No Interest or Penalty**
Protocol obligations SHALL NOT accrue interest, fees, or additional penalties
unless a future Specification version expressly provides otherwise.

**BAB-705 — Season-End Obligation**
An unpaid obligation remaining at season close SHALL remain in the archived season
Ledger and SHALL be handled by the League-configured season-close rule. It SHALL
NOT be silently forgiven or transferred to a new season.

## 4.10 Pool Balances and Rollovers

**BAB-801 — Pool Balance**
A Pool balance equals all funded entry fees, automatic contributions, and valid
rollover BAB assigned to that Pool occurrence, less any refunds made before
settlement.

**BAB-802 — Restricted Use**
Pool BAB SHALL remain restricted to payout, refund, rollover, or Championship Pot
transfer as defined by the Pool Wager Definition.

**BAB-803 — Rollover Ownership**
Rolled BAB belongs to the Pool Wager Definition, not to the original entrants, and
SHALL NOT be refunded merely because the participant field changes in a later
occurrence.

**BAB-804 — Rollover Accounting**
Every rollover SHALL transfer the undistributed Pool balance from the settled
occurrence account to the next occurrence account through balanced Ledger entries.

**BAB-805 — Final Occurrence**
If no later eligible occurrence exists, remaining rollover BAB SHALL transfer to
the Championship Pot unless League Configuration identifies another
protocol-defined destination.

> **[HYBRID]** Only qualifier/threshold-style Pool bets (where "zero qualifiers"
> is a real outcome) are rollover-eligible; rank-based bets always resolve. The
> terminal sweep fires at `season_final_week`, not a hardcoded week. (Rollover
> ruling.)

## 4.11 Season Close

**BAB-901 — Season-Close Order**
Season-end BAB processing SHALL occur in this order:
1. Finalize or Void all unresolved Versus Bets.
2. Finalize or Void all unresolved Pool Bets.
3. Release or transfer all remaining Escrow.
4. Complete all Weekly Minimum and Skunk assessments.
5. Resolve all Pool rollovers and season-end sweeps.
6. Distribute the Skunk Pot.
7. Distribute the Championship Pot.
8. Apply remaining protocol obligations under League Configuration.
9. Reconcile every Wallet, Escrow account, Pot, rollover account, and protocol
   issuance account.
10. Archive the season.

> **[HYBRID]** Insert before step 7: sweep remaining `reserve:{team_id}` balances
> to Championship; return `frozen:{team_id}` balances to Wallet at final
> reconciliation. Zero all `min:{team}:{week}` accounts. (Rows 5, 6.)

**BAB-902 — Zero Escrow**
Every Escrow account SHALL equal zero before the season may be archived.

**BAB-903 — Zero Rollover**
Every Pool rollover account SHALL equal zero before season archive, following
payout or transfer to its season-end destination.

**BAB-904 — Pot Completion**
The Championship Pot and Skunk Pot SHALL equal zero after their final
distributions, unless League Configuration expressly carries a Pot into a future
season.

**BAB-905 — Reconciliation**
The final sum of Wallets, Escrow, Pots, rollover accounts, and protocol accounts
SHALL equal the total BAB issued minus total BAB retired for the season.

**BAB-906 — Season Separation**
A new season SHALL create new Wallet, Pot, Escrow, rollover, and configuration
records. Historical balances and transactions SHALL remain immutable.

## 4.12 BAB Economy Invariants

**BAB-INV-001** — Only posted Ledger entries change BAB balances.
**BAB-INV-002** — No wager creates unfunded risk.
**BAB-INV-003** — No participant may use Escrowed BAB twice.
**BAB-INV-004** — No Dynamic Challenge increases exposure after Handshake.
**BAB-INV-005** — Weekly Minimum and Skunk obligations are deterministic and
collect before discretionary use of later credits.
**BAB-INV-006** — Pool remainders and rollovers follow a predefined destination.
**BAB-INV-007** — Commissioners approve Top-Offs but cannot manually alter
balances.
**BAB-INV-008** — All Escrow and rollover accounts resolve before season archive.
**BAB-INV-009** — The BAB Economy conserves total BAB except for explicit
issuance and retirement.

> **[HYBRID] BAB-INV-010** — Reserve and Frozen accounts resolve before season
> archive (Reserve swept to Championship; Frozen returned to Wallet). (Row 6.)

### End of Section 4

Section 4 defines the complete economic behavior of BAB. The merged-hybrid
additions — Reserve/Frozen (BAB-107/108, BAB-INV-010), Weekly-Minimum sourcing
(BAB-109), escrow-at-issue (BAB-210), and the postseason/rollover notes — are
money-path and Opus-gated. The five-stop commissioner economy slider values are
specified in Section 7 (Configuration). Section 5 governs fair pricing.
