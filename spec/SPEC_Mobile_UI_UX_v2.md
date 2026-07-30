# FantasyBeefs Mobile UI/UX Specification
## Revision 2 — Bare-Bones V1

**Status:** Frozen V1 draft  
**Platform:** Mobile only  
**Orientation:** Portrait only  
**Role:** UI/UX appendix to the FantasyBeefs protocol

---

## 1. Authority

The protocol governs system behavior, accounting, pricing, settlement, eligibility, and permissions.

This document governs what users see and what actions the mobile interface exposes.

Specific locked screen rulings control over later summaries or generic descriptions unless expressly amended.

---

## 2. Design Standard

FantasyBeefs shall be:

- Mobile-only
- Portrait-only
- One column
- Text-first
- Spartan
- Fast and direct

The UI shall use:

- Strong typography
- White space
- Thin dividers
- One accent color
- Minimal functional icons
- Clear numbers and status labels

The UI shall not use:

- Photos
- Avatars
- Decorative imagery
- Casino styling
- Dashboard grids
- Charts used as decoration
- Multiple accent colors
- Deep menus
- Unnecessary animation

---

## 3. Global Navigation

The application shall use six persistent bottom tabs:

1. My League
2. My Team
3. My Action
4. My Ledger
5. Wrap Up
6. Rules & Commish

### 3.1 My Team

My Team shall remain a separate V1 tab.

It may initially function as a limited or placeholder screen, but it shall not be folded into My League.

---

## 4. Shared Interaction Rules

- Vertical scrolling is the default.
- Horizontal swiping is reserved for the My League carousel and Wrap Up editions.
- Primary actions shall use clear text labels.
- Important actions shall not be hidden behind icons.
- Status shall always be shown in text.
- Color may reinforce status but shall not be the only indicator.
- Accepted financial actions shall update balances and the Ledger immediately.
- Irreversible actions shall require confirmation.

Approved status words include:

- Incoming
- Pending
- Accepted
- Countered
- Declined
- Expired
- Active
- Locked
- Settled
- Won
- Lost
- Push
- Refunded
- Voided
- Published

---

## 5. My League

### 5.1 Purpose

My League is the primary betting surface.

Its main component is the **Beef, Open Contracts** carousel.

Standings, matchups, and rankings may appear as secondary league context, but they shall not replace the carousel.

### 5.2 Beef, Open Contracts Carousel

The carousel shall display one opposing GM per card.

Users shall swipe horizontally between GM cards.

Each card shall show:

- Opposing GM
- Opposing team
- Current matchup context
- Three betting cells
- Free to bet
- Relevant offer or lock status

### 5.3 Three Betting Cells

Each GM card shall contain three tappable cells:

1. Moneyline
2. Spread
3. O/U

Each cell shall show the current line and price or payout information required by the protocol.

Tapping a cell begins the challenge flow for that wager type.

### 5.4 Color Coding

The three-cell card shall use the locked green, red, and yellow treatment to distinguish the available sides or market states.

Color shall be supported by labels so the card remains understandable without color.

### 5.5 Bet-Your-Own-Side Rule

A GM may bet only the GM’s own side of the matchup.

The interface shall not offer the opposing side as a selectable wager.

### 5.6 Free to Bet

Every wagering surface shall show one consolidated number:

> **Free to bet**

This is the amount currently available for a new wager.

The UI shall not force the user to choose a funding source before acceptance.

The system determines the funding source under the economy protocol when the wager is accepted.

The detailed account breakdown belongs in My Ledger, not on the primary betting card.

### 5.7 Secondary League Context

Below or outside the primary carousel, My League may show:

- Fantasy Power Rankings
- Yahoo standings
- Weekly matchups
- Team and GM list

These elements are read-only league context.

---

## 6. My Team

### 6.1 Purpose

My Team is the GM’s own fantasy-team view.

V1 may be limited, but the tab shall remain reserved.

It may show:

- Team name
- GM name
- Yahoo record
- Current matchup
- Fantasy Power Rank
- Betting Standing
- Wagering Power Rank
- Current weekly activity

It shall not duplicate the full host fantasy platform.

---

## 7. My Action

### 7.1 Purpose

My Action contains the user’s offers, responses, active bets, pools, and settled activity.

### 7.2 Required Sections

My Action shall include:

1. Incoming
2. Pending or sent offers
3. Active Versus bets
4. Available pools
5. Joined pools
6. Settled activity

### 7.3 Response Window

Every challenge shall have a 60-minute response window.

The card shall show the remaining time.

At the end of 60 minutes, an unanswered challenge becomes Expired.

An expired challenge cannot be accepted.

### 7.4 Five Response Cards

The interface shall include five distinct response-card states:

1. Incoming
2. Accepted
3. Countered
4. Declined
5. Expired

Each state shall use the previously approved badge color, layout, action set, and explanatory copy.

The detailed visual design, badge colors, explanatory copy, button behavior, and layout for each response card are governed by the **FantasyBeefs Response Card Specification**, which is authoritative. This section summarizes the required fields and states only.

The state name shall always appear as text.

### 7.5 Incoming Card

An Incoming card shall show:

- Challenger
- Wager type
- Side
- Line
- Price or payout
- BAB amount
- Free to bet
- Remaining response time

Actions:

- Accept
- Counter
- Decline

### 7.6 Accepted Card

An Accepted card shall show:

- Participants
- Final terms
- Stake
- Funding status
- Acceptance time
- Lock status

Accepted wagers are final except where the protocol requires a push, refund, or void.

### 7.7 Countered Card

A Countered card shall show:

- Original terms
- Replacement terms
- Countering GM
- Remaining response time
- Current required action

A counter replaces the prior active offer under the protocol.

### 7.8 Declined Card

A Declined card shall show:

- Final offered terms
- Declined status
- Decline time

No further action is available on the declined offer.

### 7.9 Expired Card

An Expired card shall show:

- Final offered terms
- Expired status
- Expiration time

No further action is available on the expired offer.

### 7.10 Card Perspective

Response cards are user-perspective aware.

The issuer and recipient may see different actions for the same underlying challenge.

The available actions, explanatory text, and resulting money movement shall reflect the governing protocol and the **FantasyBeefs Response Card Specification**.

This includes issuer-versus-recipient expiration behavior, reissue or new-challenge behavior, re-escrow, and any acceptance-time funding true-up.

This document intentionally does not duplicate those behavioral rules.

### 7.11 Sent Offers

A sent, unanswered offer shall show:

- Opponent
- Terms
- BAB amount
- Remaining response time
- Withdraw action where permitted

### 7.12 Active Versus Bets

Each active wager shall show:

- Opponent
- Wager type
- Side
- Line
- Stake
- Potential return
- Active or locked status

### 7.13 Pools

Available and joined pools shall show:

- Pool name
- Description
- Entry amount
- Selection
- Lock time
- Status
- Result and payout after settlement

Pools are voluntary.

---

## 8. Wager Flow

The standard Versus flow is:

1. Swipe to a GM card.
2. Tap Moneyline, Spread, or O/U.
3. Review the user’s own side.
4. Enter or confirm BAB.
5. Review Free to bet.
6. Send challenge.
7. Opponent has 60 minutes to accept, counter, or decline.
8. Accepted wager funds escrow.
9. Wager locks.
10. Wager settles.
11. Balances and Ledger update.

The UI shall enforce:

- Bet-your-own-side
- Funding requirements
- Active-bet limit
- Lock timing
- Accepted-wager finality
- Protocol-required pushes, refunds, and voids

---

## 9. My Ledger

### 9.1 Purpose

My Ledger is the user’s BAB accounting record.

It must be simple, formal, and trustworthy.

### 9.2 Account Breakdown

My Ledger shall show the detailed balance breakdown:

- Wallet
- Weekly Min Escrow
- Active Bet Escrow
- Championship Reserve

This detailed breakdown shall not replace the single Free to bet number on wagering screens.

### 9.3 Opening Allocation

The default opening allocation is:

| Account | BAB |
|---|---:|
| Wallet | 0 |
| Weekly Min Escrow | 140 |
| Championship Reserve | 80 |
| Total Buy-In | 220 |

Wallet shall not begin with 140 BAB.

### 9.4 Ledger

The Ledger is chronological transaction history.

Format:

```text
Date | From → To | Debit | Credit
```

The commissioner shall not have a control to manually rewrite ledger entries.

Corrections shall occur only through protocol-authorized transactions.

### 9.5 Sheet

The Sheet is the season reconciliation.

- Ledger = chronological transactions
- Sheet = season reconciliation

A GM sees the GM’s own Sheet.

A commissioner may access the league Sheet.

---

## 10. Settlement

Settlement shall follow the claim-first, two-phase settlement protocol.

The UI shall not show settlement as complete until the authorized accounting transaction is complete.

After settlement, the user shall immediately see:

- Result
- Stake disposition
- Payout or refund
- Wallet change
- Escrow change
- Ledger transaction

The UI shall not mirror the completion-first anti-pattern.

---

## 11. Wrap Up

### 11.1 Purpose

Wrap Up is the weekly league publication.

It shall read like a concise league newspaper, not a dashboard.

### 11.2 Navigation

- Vertical scroll reads the current edition.
- Swipe left or right moves between weekly editions.
- Tapping the week header opens a week picker.
- The latest completed week opens by default.
- Published editions are read-only.

Header example:

```text
‹ WEEK 7      WEEK 8 WRAP UP      WEEK 9 ›
Final · Tuesday Oct 28
```

### 11.3 Content

A weekly edition may include:

- Week in One Line
- Bet of the Week
- Fantasy Power Rankings
- Yahoo matchup recap
- Pool recap
- Versus recap
- Betting Standings
- Wagering Power Rankings
- Weekly Minimum
- Skunk
- Pots
- Next Week
- Commissioner or editorial commentary

The edition shall be one continuous article.

---

## 12. Fantasy Power Rankings

Fantasy Power Rankings measure fantasy-team strength.

Approved formula:

- 40% All-Play Record
- 25% Yahoo Record
- 25% Points-For Percentile
- 10% Recent Form

The UI shall show:

- Rank
- Team or GM
- Rank movement

A brief methodology explanation shall be available.

### 12.1 Luck Index

Luck Index compares Expected Wins with Actual Wins.

It shall be shown separately.

Luck Index shall not be included in the Fantasy Power Ranking formula.

---

## 13. Betting Standings

Betting Standings shall be ranked strictly by net BAB.

The UI shall show:

- Rank
- GM
- Net BAB
- Rank movement where useful

Betting Standings are separate from Wagering Power Rankings.

---

## 14. Wagering Power Rankings

Wagering Power Rankings measure wagering skill.

Approved formula:

- 45% Risk-Adjusted ROI
- 30% Performance Versus Expected Odds
- 15% Weekly Consistency
- 10% Recent Form

The UI shall show:

- Rank
- GM
- Rank movement
- Ranked or not yet qualified status

A minimum qualification threshold shall apply under the calculation protocol.

A brief methodology explanation shall be available.

---

## 15. Rules & Commish

### 15.1 GM View

A GM shall see:

- How to Play
- User-facing Rules
- Economy Stop
- Privacy mode
- Weekly-minimum enforcement mode
- Locked league settings
- League timing and season status

### 15.2 Commissioner View

A commissioner shall additionally see:

- Locked-at-kickoff settings
- Live settings
- Administrative settings
- Pause Betting
- Top-Off approvals
- Commissioner delegates
- League Sheet
- Wrap Up publication
- Season close

### 15.3 Settings Groups

#### Locked at Kickoff

- Economy Stop
- Unspent-Minimum Destination
- Season Final Week
- Pool Rollover
- Championship Distribution
- Skunk Fee Amount

#### Live

- Weekly-Minimum Enforcement
  - Hard
  - Soft
- Bet Privacy
  - The Reveal
  - Quiet Ledger
- Pause Betting

#### Admin

- League Time Zone
- Commissioner Delegates
- Season Publication & Close

V1 shall not include commissioner toggles for individual wager types, pools, or core product features.

---

## 16. How to Play

How to Play shall explain:

- FantasyBeefs sits on top of the existing fantasy league.
- The host platform remains authoritative for fantasy results.
- BAB is the league wagering currency.
- GMs may issue and accept Versus challenges.
- GMs may join voluntary pools.
- GMs may bet only their own side.
- Every challenge has a 60-minute response window.
- Accepted wagers fund escrow.
- Accepted wagers settle automatically under protocol.
- Winnings return to Wallet.
- Weekly participation requirements may apply.
- The Ledger records every BAB movement.
- Wrap Up publishes the weekly league story.

The writing shall be short, direct, and non-legalistic.

---

## 17. User-Facing Rules

The Rules section shall contain the approved user-facing content for:

1. Season Economy
2. Weekly Minimum
3. Wallet & Top-Offs
4. Championship Reserve
5. Skunk Fee
6. Types of Bets
7. Versus Bets
8. Versus Pricing
9. Pool Bets
10. Privacy
11. Refunds & Pushes
12. Settlement
13. Postseason

### 17.1 Season Economy

Explain:

- Total buy-in
- Wallet opening balance
- Weekly Min Escrow
- Championship Reserve
- Economy Stop
- BAB as league currency

### 17.2 Weekly Minimum

Explain:

- Weekly minimum
- Funding and timing
- Hard versus Soft enforcement
- Consequences of noncompliance
- Unspent-minimum destination

### 17.3 Wallet & Top-Offs

Explain:

- Wallet contains unrestricted BAB.
- Winnings flow to Wallet.
- Free to bet is the consolidated amount available for a new wager.
- Top-Offs require the approved process.
- Top-Offs are recorded in the Ledger.

### 17.4 Championship Reserve

Explain:

- Purpose
- Opening funding
- Locked status
- Distribution timing

### 17.5 Skunk Fee

Explain:

- Trigger
- Amount
- Tie handling
- Pot destination
- Settlement timing

### 17.6 Types of Bets

Explain the approved V1 formats:

- Moneyline
- Spread
- O/U
- Approved Versus bets
- Approved pool bets

### 17.7 Versus Bets

Explain:

- Voluntary GM-versus-GM format
- Bet-your-own-side rule
- Offer
- 60-minute response window
- Accept
- Counter
- Decline
- Expire
- Withdraw where permitted
- Funding
- Escrow
- Locking
- Active limit
- Finality
- Settlement

### 17.8 Versus Pricing

Explain:

- Line
- Price or odds
- Stake
- Potential return
- Push behavior

Exact pricing math remains governed by protocol.

### 17.9 Pool Bets

Explain:

- Voluntary entry
- Approved V1 pool types
- Entry amount
- Selection
- Lock timing
- Tie splitting
- Rollover where permitted

### 17.10 Privacy

#### The Reveal

League wagering activity is visible according to protocol.

#### Quiet Ledger

Private wager details are restricted according to protocol.

Wrap Up shall anonymize or omit restricted information.

### 17.11 Refunds & Pushes

Explain:

- Push
- Refund
- Void
- Returned stake
- Ledger treatment

### 17.12 Settlement

Explain:

- The host platform is authoritative for fantasy results.
- Settlement follows the protocol.
- Ledger updates follow settlement.
- Commissioners do not manually rewrite outcomes.
- Accepted wagers remain final except for protocol-required push, refund, or void.

### 17.13 Postseason

Explain:

- Postseason availability
- Season-final-week setting
- Championship settlement
- Remaining balances
- Season close
- New-season reset

---

## 18. Privacy

The interface shall obey the active privacy mode.

The user shall always retain access to the user’s own wagers and ledger details.

Notifications and Wrap Up content shall not reveal information prohibited by Quiet Ledger.

---

## 19. Notifications

V1 notifications may include:

- New challenge
- Challenge accepted
- Counter received
- Challenge declined
- Challenge expired
- Wager locked
- Pool locking
- Wager settled
- Pool settled
- Weekly-minimum issue
- Top-Off decision
- Wrap Up published
- Betting paused or resumed
- Season-close action

Notifications shall open the relevant screen.

---

## 20. Locked V1 Decisions

1. Six bottom tabs.
2. My Team remains a separate tab.
3. My League is centered on the Beef, Open Contracts carousel.
4. The carousel shows one GM per card.
5. Each card has Moneyline, Spread, and O/U cells.
6. A GM may bet only the GM’s own side.
7. Green, red, and yellow coding is retained.
8. Betting surfaces show one Free to bet number.
9. Detailed account balances remain in My Ledger.
10. Challenges have a 60-minute response window.
11. Incoming, Accepted, Countered, Declined, and Expired are distinct card states.
12. The app is mobile-only and portrait-only.
13. The app is one-column and text-first.
14. Photos, avatars, decorative imagery, and casino chrome are prohibited.
15. Ledger and Sheet remain separate.
16. Wallet opens at 0 BAB.
17. Weekly Min Escrow opens at 140 BAB.
18. Championship Reserve opens at 80 BAB.
19. Wrap Up is a first-class tab.
20. Wrap Up scrolls vertically and swipes horizontally by week.
21. Published Wrap Ups are read-only.
22. Rules & Commish contains the actual How to Play and user-facing Rules content.
23. Fantasy Power Rankings, Betting Standings, and Wagering Power Rankings remain separate.
24. Settlement follows claim-first, two-phase accounting.
25. The UI shall not expose manual ledger editing.
