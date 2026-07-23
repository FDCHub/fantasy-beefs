# FantasyBeefs Mobile UI/UX Specification
## Revision 1 — Frozen V1 Draft

**Status:** Approved for design and implementation  
**Platform:** Mobile only  
**Orientation:** Portrait only  
**Role:** UI/UX appendix to the FantasyBeefs protocol documents

---

## 1. Purpose

This document defines the approved Version 1 mobile user experience for FantasyBeefs.

It governs:

- Product structure
- Global navigation
- Tab purpose and content
- User-visible rules and explanations
- Primary user flows
- Shared interface behavior
- Visual design standards
- Commissioner-specific UI
- Wrap Up structure
- Ledger and reconciliation presentation
- Ranking presentation and methodology
- Approved design prohibitions

The protocol documents remain authoritative for engine behavior, accounting, settlement, permissions, eligibility, pricing, and other system rules.

This appendix governs how those rules are presented and used in the mobile interface.

---

## 2. Product Experience

FantasyBeefs is a mobile-only wagering layer for an existing fantasy league.

It does not replace Yahoo, ESPN, Sleeper, or another host fantasy platform.

The product should feel like:

- A clean sports ledger
- A concise league newspaper
- A direct action tool
- A trustworthy accounting interface
- A private competition layer added to an existing league

The product should not feel like:

- A casino
- A traditional sportsbook
- A social media feed
- A dashboard
- A financial terminal
- A game filled with badges, avatars, and animations

---

## 3. Global Design Standard

### 3.1 Platform

The application shall be designed for mobile phones only.

V1 shall not include:

- Desktop layouts
- Tablet-specific layouts
- Responsive web breakpoints
- Landscape-specific layouts
- Sidebars
- Hover states
- Mouse-dependent interactions

The primary target is a standard portrait phone viewport.

Larger and smaller phones shall be handled through flexible spacing and vertical scrolling rather than alternate layouts.

### 3.2 Visual Style

The approved visual direction is Spartan, text-first, and editorial.

The interface shall use:

- One-column layouts
- Large, legible typography
- Strong whitespace
- A black header
- A white content area
- One accent color
- Thin dividers
- Simple text labels
- Full-width primary actions
- Minimal functional icons
- Clear numerical hierarchy

Typography and spacing shall create hierarchy.

Graphics shall not create hierarchy.

### 3.3 Images

V1 shall not use:

- Photos
- Avatars
- Profile pictures
- Illustrations
- Decorative imagery
- Team logos as required interface elements
- Background artwork

GM, team, wager, pool, and ranking views shall be text-first.

### 3.4 Design Principles

1. Content before chrome.
2. One screen, one purpose.
3. Numbers before graphics.
4. Scrolling beats unnecessary tapping.
5. The ledger must feel trustworthy.
6. The Wrap Up must feel enjoyable to read.
7. Every tap must earn its place.
8. Prefer removal over addition.
9. Typography should do most of the visual work.
10. The app should feel fast, calm, and obvious.

---

## 4. Global Navigation

The application shall use a persistent five-tab bottom navigation.

The tabs are:

1. My League
2. My Action
3. My Ledger
4. Wrap Up
5. Rules & Commish

The bottom navigation shall remain visible throughout the primary tab experience.

### 4.1 Navigation Behavior

- Vertical scrolling is the default within screens.
- Horizontal swiping is reserved for movement between Wrap Up editions.
- Rows may be tapped to expand or open detail.
- Back navigation shall return the user to the prior context.
- Deep links from notifications shall open the relevant item directly.
- Nested navigation shall remain shallow.
- Primary actions shall not be hidden behind ambiguous icons.

---

## 5. Shared Interface Standards

### 5.1 Headers

Each primary tab shall use a simple top header containing:

- Tab title
- Current league week or relevant status where useful
- Minimal secondary action only when necessary

Headers shall not contain decorative controls or dense utility menus.

### 5.2 Lists

Lists shall be the primary content structure.

List rows may contain:

- Primary label
- Secondary description
- Status
- Amount
- Result
- Movement indicator
- Simple action

Rows shall remain readable without opening detail.

### 5.3 Buttons

Primary buttons shall be:

- Full width where practical
- Text labeled
- Visually obvious
- Used sparingly

Secondary actions may appear as text buttons.

Destructive or irreversible actions shall require confirmation.

### 5.4 Dividers

Thin dividers may separate sections and rows.

Boxes, cards, and borders shall not be used merely to create visual grouping.

### 5.5 Status Labels

Status shall be communicated through concise text such as:

- Pending
- Active
- Locked
- Settled
- Won
- Lost
- Push
- Refunded
- Voided
- Closed
- Published

Color may reinforce status but shall not be the only indicator.

### 5.6 Empty States

Empty states shall use plain language.

Examples:

- No pending challenges.
- No active bets.
- No pools are open.
- No ledger activity yet.
- This week has not been published.
- No commissioner action is required.

### 5.7 Error States

Errors shall explain:

1. What happened
2. Why the action cannot continue
3. What the user must do next

Example:

> You do not have enough available BAB to accept this challenge.

### 5.8 Loading States

Loading states shall be brief and visually restrained.

The interface should avoid decorative skeleton dashboards.

### 5.9 Confirmation States

Accepted, joined, funded, settled, refunded, and published actions shall produce immediate, concise confirmation.

Any resulting balance or ledger change shall become visible without requiring the user to refresh.

---

## 6. My League

### 6.1 Purpose

My League is the league context tab.

It gives the GM a clear view of:

- Current league week
- Yahoo standings
- Current fantasy matchups
- Teams and GMs
- Fantasy Power Rankings
- Relevant league status

It is not a wagering dashboard.

### 6.2 Primary Content

The default My League screen should present, in a simple vertical sequence:

1. Current week
2. Fantasy Power Rankings
3. Yahoo standings
4. Weekly matchups
5. Team and GM list

The exact order may be refined by the designer, but the screen shall remain one column and text-first.

### 6.3 Team and GM Rows

Each team or GM row may show:

- Team name
- GM name
- Yahoo record
- Current rank
- Current matchup
- Relevant movement indicator

No profile photos or avatars shall be shown.

### 6.4 Team or GM Detail

Tapping a team or GM opens a detail view containing relevant information such as:

- Team name
- GM name
- Yahoo record
- Fantasy Power Rank
- Betting Standing
- Wagering Power Rank
- Current matchup
- Available challenge action
- Current or recent shared wager activity where privacy permits

The primary available action is:

> Challenge GM

### 6.5 Weekly Matchups

Weekly matchup rows shall show:

- Team A
- Team B
- Current or final score
- Matchup status
- Relevant Yahoo result

The UI shall not recreate the entire host fantasy platform.

It should show only the information needed for FantasyBeefs context and wagering.

---

## 7. Fantasy Power Rankings

### 7.1 Purpose

Fantasy Power Rankings measure fantasy-team strength.

They are separate from:

- Yahoo standings
- Betting Standings
- Wagering Power Rankings
- Luck Index

### 7.2 Ranking Formula

The approved formula is:

- 40% All-Play Record
- 25% Yahoo Record
- 25% Points-For Percentile
- 10% Recent Form

The calculation protocol governs the exact math.

### 7.3 Presentation

Each ranking row shall show:

- Rank
- Team or GM name
- Rank movement
- Optional concise record or score context

Example:

```text
1  Juggernauts
2  Walnut Creek   ▲2
3  Fraser         ▲1
4  Black Mambas   ▼2
```

The ranking shall not require a chart, gauge, or scorecard grid.

### 7.4 Methodology

A methodology explanation shall be available through a simple tap-to-expand or secondary detail view.

The user-facing explanation shall clearly state the four weighted inputs.

### 7.5 Luck Index

Luck Index shall be separate commentary.

It shall compare:

- Expected Wins, based on all-play performance
- Actual Wins

Luck Index shall not be included in the Fantasy Power Ranking calculation.

---

## 8. My Action

### 8.1 Purpose

My Action is the operational wagering tab.

It contains the GM’s actionable and active betting activity.

### 8.2 Primary Sections

The tab shall include:

1. Pending Challenges
2. Active Versus Bets
3. Available Pools
4. Joined Pools
5. Settled Activity

The design shall remain a clean vertical list.

### 8.3 Pending Challenges

Each pending challenge shall show:

- Opponent
- Bet type
- Selection
- Line
- Odds or payout terms
- BAB amount
- Offer status
- Expiration or lock timing where relevant

Available actions may include:

- Accept
- Decline
- Counter

Where protocol permits, the issuer may also withdraw an unaccepted offer.

### 8.4 Counter Flow

A counter shall create a replacement offer according to the governing protocol.

The UI shall make clear that:

- The original offer is no longer the active offer
- The counter must be accepted before it becomes active
- The relevant terms have changed

### 8.5 Active Versus Bets

Each active wager shall show:

- Opponent
- Wager type
- Selection
- Line
- Stake
- Potential return or net result
- Current status
- Lock state
- Settlement state

Tapping opens full wager detail.

### 8.6 Available Pools

Each available pool shall show:

- Pool name
- Short description
- Entry amount
- Entry count where useful
- Lock time
- Rollover status where applicable
- Join action

Pools are voluntary.

### 8.7 Joined Pools

Joined pools shall show:

- User selection
- Entry amount
- Current status
- Lock status
- Result when settled
- Payout when applicable

### 8.8 Settled Activity

Settled wagers and pools shall show:

- Won
- Lost
- Push
- Refunded
- Voided
- Payout or return
- Settlement date

Settled items shall remain reviewable.

### 8.9 Wager Detail

Wager detail should include:

- Participants
- Bet terms
- Created time
- Accepted time
- Lock time
- Stake source
- Escrow movement
- Settlement result
- Ledger impact
- Protocol-based explanation where necessary

The screen shall remain text-first.

---

## 9. Versus Bets

### 9.1 Purpose

Versus bets are voluntary GM-versus-GM wagers.

The interface shall use “GM vs GM” language rather than “wallet vs wallet.”

### 9.2 Primary Flow

The standard flow is:

1. Select GM
2. Select bet type
3. Enter or confirm terms
4. Enter BAB amount
5. Review
6. Issue challenge
7. Opponent accepts, declines, counters, or leaves pending
8. Accepted wager funds escrow
9. Wager locks
10. Wager settles
11. Ledger updates

### 9.3 Finality

The UI shall communicate that accepted wagers are final except where the protocol requires a push, refund, or void.

### 9.4 Funding

The interface shall prevent acceptance or issuance when protocol funding requirements are not met.

The UI shall identify the relevant source account and any required top-off or available balance issue.

### 9.5 Active Limit

The UI shall enforce and explain the protocol-defined active Versus limit.

The approved limit is ten active Versus bets unless revised by the governing protocol.

### 9.6 Locking

The UI shall clearly distinguish:

- Pending
- Accepted
- Active
- Locked
- Settled

---

## 10. Pool Bets

### 10.1 Purpose

Pools allow voluntary league-wide participation in approved pool formats.

### 10.2 Pool Types

V1 contains four approved pool types.

The exact names and rules shall follow the governing pool protocol and approved user-facing rules.

### 10.3 Entry Flow

The standard pool flow is:

1. Open pool
2. Review description and entry
3. Select eligible entry
4. Confirm BAB
5. Join
6. Entry locks
7. Pool settles
8. Payout is credited

### 10.4 Ties

Pool ties split according to protocol.

The UI shall show:

- Number of tied winners
- Total pot
- Individual payout

### 10.5 Lock Timing

Pool lock timing shall be visible before entry.

Once locked, the user’s entry shall be read-only.

### 10.6 Rollover

Rollover shall be shown only for pool types where the protocol allows it.

---

## 11. My Ledger

### 11.1 Purpose

My Ledger is the GM’s BAB accounting tab.

It must feel formal, simple, and trustworthy.

### 11.2 Top Balance Strip

The top of the tab shall show:

- Wallet
- Weekly Min Escrow
- Active Bet Escrow
- Championship Reserve

The strip shall be concise and shall not become a dashboard grid.

### 11.3 Opening Allocation

The opening allocation shall reflect the approved economy model:

- Weekly Min Escrow
- Championship Reserve
- Wallet: 0 BAB

The opening ledger shall post:

- League Economy → Weekly Min Escrow
- League Economy → Championship Reserve

Wallet shall not begin with 140 BAB.

### 11.4 Account Model

The underlying economy includes:

- Weekly Reserve
- Weekly-Min Account
- Bet Wallet
- Championship Reserve
- Temporary Bet Escrow

The weekly funding sequence is:

```text
Weekly Reserve
    ↓
Weekly-Min Account
    ↓
Bet Escrow
    ↓
Wallet
```

Wallet contains unrestricted BAB.

### 11.5 Ledger Snapshot

Below the balance strip, the tab shall show:

> Ledger snapshot

Tapping shall expand to the full chronological ledger.

### 11.6 Ledger Format

Ledger rows shall use:

```text
Date | From → To | Debit | Credit
```

Example:

```text
Oct 24   Fraser → Versus Escrow   10.00   10.00
```

The ledger is chronological transaction history.

It shall not be styled as a card dashboard.

### 11.7 Sheet Snapshot

Below the Ledger snapshot, the tab shall show:

> Sheet snapshot

Tapping shall expand to the full season reconciliation.

### 11.8 Sheet

The Sheet is the consolidated season reconciliation.

It is not the same as the Ledger.

- Ledger = chronological transactions
- Sheet = season reconciliation

A GM sees the GM’s own Sheet.

A commissioner may access the league Sheet.

### 11.9 Ledger Integrity

The UI shall not provide a commissioner control to manually alter ledger entries.

Corrections shall occur only through protocol-authorized transactions.

---

## 12. Economy Stop

### 12.1 Authoritative Default

The approved default Economy Stop is:

| Item | BAB |
|---|---:|
| Bet Floor | 1 |
| Weekly Minimum | 10 |
| Weekly Min Escrow | 140 |
| Championship Reserve | 80 |
| Total Buy-In | 220 |
| Wallet | 0 |

This table is authoritative for the UI.

It overrides conflicting earlier UI wording.

### 12.2 Presentation

The Rules & Commish tab shall present the league’s active Economy Stop clearly.

The interface shall distinguish:

- Locked economy values
- Current balances
- Live enforcement mode
- User-specific wallet state

---

## 13. Wrap Up

### 13.1 Purpose

Wrap Up is the weekly league publication.

It should feel like a league newspaper or sports column.

It shall not feel like a dashboard.

### 13.2 Edition Model

Each completed week is a separate edition.

The latest completed week opens by default.

Each edition is:

- Vertically scrollable
- Horizontally navigable
- Read-only after publication

### 13.3 Navigation

Within the current edition:

- Swipe left to move to a newer edition
- Swipe right to move to an older edition
- Scroll vertically to read
- Tap the week header to open a week picker

Header concept:

```text
‹ WEEK 7      WEEK 8 WRAP UP      WEEK 9 ›
Final · Tuesday Oct 28
```

Horizontal swiping shall not be used elsewhere in the primary V1 product.

### 13.4 Publication State

A published edition is permanent and read-only.

Any future correction method would require an explicit versioning decision and is outside the frozen V1 scope.

### 13.5 Approved Sections

A Wrap Up edition may contain:

1. Week in One Line
2. Bet of the Week
3. Fantasy Power Rankings
4. Yahoo Matchups
5. Pool Recap
6. Versus Recap
7. Betting Standings
8. Wagering Power Rankings
9. Weekly Minimum
10. Skunk
11. Pots
12. Next Week
13. Commentary

The presentation shall be one continuous article.

### 13.6 Bet of the Week

Bet of the Week is automatically selected using relevant criteria such as:

- Largest BAB
- Closest finish
- Biggest upset
- Late swing
- Other approved editorial significance

Under Quiet Ledger, participants shall be anonymized where required.

### 13.7 Editorial Style

The Wrap Up should use:

- Strong section headings
- Short paragraphs
- Simple ranking lists
- Plain matchup summaries
- Concise commentary
- Minimal separators
- No card grid
- No charts
- No gauges
- No profile imagery

---

## 14. Betting Standings

### 14.1 Purpose

Betting Standings show actual wagering results.

They are ranked strictly by net BAB.

### 14.2 Presentation

Each row shall show:

- Rank
- GM
- Net BAB
- Rank movement where useful

Example:

```text
1  Fraser          +31.4 BAB
2  Juggernauts     +18.2 BAB
3  Walnut Creek     +9.6 BAB
```

Betting Standings shall be clearly separated from Wagering Power Rankings.

---

## 15. Wagering Power Rankings

### 15.1 Purpose

Wagering Power Rankings measure wagering skill rather than raw net BAB alone.

### 15.2 Approved Formula

The approved formula is:

- 45% Risk-Adjusted ROI
- 30% Performance Versus Expected Odds
- 15% Weekly Consistency
- 10% Recent Form

The calculation protocol governs exact math.

### 15.3 Qualification

A minimum settled-wager or settled-BAB threshold shall be required before a GM is ranked.

The user-facing UI shall distinguish:

- Ranked
- Not yet qualified

### 15.4 Presentation

Each row shall show:

- Rank
- GM
- Rank movement
- Optional concise qualification or score context

The ranking shall not use gauges, radar charts, or dense analytics panels.

### 15.5 Methodology

A tap-to-expand methodology explanation shall identify the four weighted components and the minimum qualification rule.

---

## 16. Rules & Commish

### 16.1 Purpose

This tab contains:

- How to Play
- User-facing Rules
- Current league settings
- Economy Stop
- Privacy mode
- Weekly-minimum enforcement mode
- Commissioner controls
- Season publication and close controls

The tab shall show role-appropriate content.

### 16.2 GM View

A GM shall see:

- How to Play
- Rules
- Current Economy Stop
- Current privacy mode
- Current enforcement mode
- Locked league settings
- Relevant league timing
- Commissioner contact or explanatory text where appropriate

### 16.3 Commissioner View

A commissioner shall additionally see:

- Locked-at-kickoff settings
- Live settings
- Administrative settings
- Pause Betting
- Top-Off approvals
- Commissioner delegates
- Season publication and close
- League Sheet access

### 16.4 Settings Categories

The commissioner UI shall organize settings into:

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

### 16.5 Removed Feature Toggles

V1 shall not provide commissioner toggles to enable or disable:

- Wager types
- Pools
- Challenge modes
- Core approved product features

Those older concepts are removed from the approved UI model.

---

## 17. How to Play

### 17.1 Purpose

How to Play is the plain-language introduction to FantasyBeefs.

It should explain the product before the formal rules.

### 17.2 Required Topics

How to Play shall explain:

- FantasyBeefs sits on top of the existing fantasy league
- The host platform remains authoritative for fantasy results
- BAB is the league wagering currency
- GMs may make Versus bets
- GMs may join voluntary pools
- Weekly participation requirements may apply
- Accepted wagers fund escrow
- Results settle automatically under protocol
- Winnings return to Wallet
- Championship and Skunk structures operate separately
- The Ledger records all BAB movement
- The Wrap Up publishes the weekly league story

### 17.3 Tone

How to Play should be:

- Direct
- Short
- Friendly
- Non-legalistic
- Consistent with the approved rules
- Free of unnecessary gambling jargon

---

## 18. User-Facing Rules

The Rules section shall contain the approved categories below.

### 18.1 Season Economy

Explain:

- Total season buy-in
- Opening allocation
- Wallet opening balance
- Weekly Min Escrow
- Championship Reserve
- Economy Stop
- BAB as the league currency

### 18.2 Weekly Minimum

Explain:

- Weekly minimum amount
- Weekly-Min Account
- Hard versus Soft enforcement
- Required timing
- Consequences of noncompliance
- Unspent-minimum destination

### 18.3 Wallet & Top-Offs

Explain:

- Wallet contains unrestricted BAB
- Winnings flow to Wallet
- Wallet funds eligible activity
- Top-Off approval requirements
- Top-Offs are recorded in the Ledger

### 18.4 Championship Reserve

Explain:

- Reserve purpose
- Opening funding
- Locked nature
- Distribution timing
- Commissioner inability to repurpose it outside protocol

### 18.5 Skunk Fee

Explain:

- Trigger
- Fee amount
- Tie handling
- Pot destination
- Settlement timing

### 18.6 Types of Bets

Explain the approved V1 wagering categories:

- Versus bets
- Pool bets
- Approved lines and formats

The user-facing copy shall distinguish fantasy wagering from host-platform standings.

### 18.7 Versus Bets

Explain:

- Voluntary GM-versus-GM format
- Offer, accept, decline, counter, and withdraw states
- Funding
- Escrow
- Locking
- Active limit
- Accepted-wager finality
- Settlement

### 18.8 Versus Pricing

Explain:

- Dynamic odds or pricing
- Stake
- Potential return
- Push behavior
- No hidden pricing

The exact pricing engine remains governed by protocol.

### 18.9 Pool Bets

Explain:

- Pools are voluntary
- Four approved V1 pool types
- Entry amount
- Lock timing
- Highest-score-wins structure where applicable
- Tie splitting
- Rollover only where permitted

### 18.10 Privacy

Explain the league’s selected mode:

#### The Reveal

League wagering activity is visible according to protocol.

#### Quiet Ledger

Private wager details are restricted according to protocol.

Wrap Up content shall anonymize participants where required.

### 18.11 Refunds & Pushes

Explain:

- Push
- Refund
- Void
- Returned stake
- Ledger treatment

### 18.12 Settlement

Explain:

- Yahoo is authoritative
- Results are settled under the approved protocol
- Ledger updates follow settlement
- Commissioners do not manually rewrite outcomes
- Accepted wagers remain final except for protocol-required push, refund, or void

### 18.13 Postseason

Explain:

- Postseason availability
- Season-final-week setting
- Championship settlement
- Remaining balances
- Season close
- New season reset

---

## 19. Commissioner Actions

### 19.1 Pause Betting

Pause Betting is the approved live control.

It shall replace “Emergency Pause” wording.

The UI shall explain:

- What activity is paused
- What remains viewable
- Whether existing accepted bets remain active
- When betting resumes

The protocol governs exact effects.

### 19.2 Top-Off Approval

A commissioner may review eligible Top-Off requests.

The interface shall show:

- GM
- Amount
- Request time
- Reason or note where applicable
- Approve
- Decline
- Resulting ledger transaction

### 19.3 Delegates

Commissioner Delegates may be added or removed according to protocol.

The UI shall make delegated authority visible.

### 19.4 Publication and Close

The commissioner shall have controls for:

- Publishing a weekly Wrap Up
- Closing the season
- Reviewing required close conditions
- Confirming season close

The UI shall prevent close when protocol requirements are not satisfied.

---

## 20. Notifications

Notifications should be concise and deep-link to the relevant screen.

V1 notification events may include:

- New challenge
- Challenge accepted
- Challenge declined
- Counter received
- Challenge withdrawn
- Wager locked
- Pool joined
- Pool locking soon
- Wager settled
- Pool settled
- Weekly minimum issue
- Top-Off approved or declined
- Wrap Up published
- Betting paused or resumed
- Season close action required

Notifications shall not reveal private wager details when Quiet Ledger prohibits them.

---

## 21. Privacy Behavior

The UI shall obey the active league privacy mode.

### 21.1 The Reveal

The interface may show league wagering activity according to protocol.

### 21.2 Quiet Ledger

The interface shall restrict private wager detail.

Where editorial content references private activity, the Wrap Up shall anonymize participants or omit restricted detail.

The user shall always retain access to the user’s own wager and ledger details.

---

## 22. Settlement and Accounting Visibility

When a wager settles, the user shall immediately see:

- Result
- Stake disposition
- Payout
- Wallet change
- Escrow change
- Ledger transaction

The UI shall not present settlement as complete before the protocol-authorized accounting transaction is complete.

The settlement interface must follow the final claim-first, two-phase settlement protocol and must not mirror the known completion-first anti-pattern.

---

## 23. Season Close

The commissioner close flow shall show whether all required conditions are satisfied.

Examples may include:

- All wagers settled
- All pools settled
- Championship distribution complete
- Skunk distribution complete
- No unresolved escrow
- Final Sheet reconciled
- Final Wrap Up published where required

A new season shall begin with a fresh economy and new opening allocations.

---

## 24. Visual Prohibitions

The following are prohibited in V1 unless separately approved:

- Dashboard grids
- KPI tile walls
- Multi-column mobile layouts
- Charts used as decoration
- Gauges
- Pie charts
- Radar charts
- Dense sportsbook boards
- Profile pictures
- Avatars
- Decorative team art
- Background photography
- Illustrations
- Multiple accent colors
- Excessive borders
- Floating widgets
- Large icon systems
- Gamified badges
- Achievement systems
- Confetti-heavy settlement
- Unnecessary animations
- Horizontal scrolling outside Wrap Up editions
- Deep nested menus
- Hidden primary actions
- Decorative cards around every item

---

## 25. Motion and Feedback

Animation shall be:

- Minimal
- Fast
- Functional
- Secondary to content

Permitted examples:

- Row expansion
- Tab transition
- Brief confirmation
- Subtle settled-state change
- Horizontal edition transition in Wrap Up

Animation shall not delay an action or obscure accounting.

---

## 26. Accessibility

The mobile UI shall support:

- Strong contrast
- Legible default text
- Dynamic font scaling where practical
- Clear touch targets
- One-handed use
- Text labels for important actions
- Status communication independent of color
- Logical reading order
- Simple language

---

## 27. Reserved for Future Versions

The following are outside the frozen V1 scope unless separately approved:

- Desktop or tablet layouts
- Multi-league management
- Social feed
- Messaging
- GM avatars
- Team imagery
- Badges
- Achievements
- Rich animation
- AI-generated personalized coaching
- Advanced charting
- Historical season archive beyond approved Wrap Up editions
- Public profiles
- Wager-type enable/disable toggles
- Manual ledger editing
- Expanded responsive web experience

---

## Appendix A — Locked Design Decisions

The following decisions are frozen for V1:

1. FantasyBeefs is mobile-only.
2. V1 is portrait-only.
3. The interface uses a persistent five-tab bottom navigation.
4. The tabs are My League, My Action, My Ledger, Wrap Up, and Rules & Commish.
5. The design is Spartan and text-first.
6. The app uses one-column layouts.
7. The app uses a black header, white content area, and one accent color.
8. The UI contains no photos, avatars, or decorative imagery.
9. Dashboard grids are prohibited.
10. Typography and whitespace create hierarchy.
11. My Ledger contains a balance strip, Ledger snapshot, and Sheet snapshot.
12. Ledger and Sheet are separate concepts.
13. Ledger is chronological transaction history.
14. Sheet is season reconciliation.
15. GM sees own Sheet.
16. Commissioner may see league Sheet.
17. Wallet opens at 0 BAB.
18. Weekly Min Escrow opens at 140 BAB under the default Economy Stop.
19. Championship Reserve opens at 80 BAB under the default Economy Stop.
20. Wrap Up is a first-class tab.
21. Wrap Up is one vertically scrolling article.
22. Horizontal swipe moves between Wrap Up editions.
23. Tapping the week header opens a week picker.
24. Published Wrap Ups are read-only.
25. Wrap Up uses an editorial newspaper style.
26. Bet of the Week is included.
27. Fantasy Power Rankings use the approved 40/25/25/10 formula.
28. Luck Index is separate from Fantasy Power Rankings.
29. Betting Standings are ranked by net BAB.
30. Wagering Power Rankings are separate from Betting Standings.
31. Wagering Power Rankings use the approved 45/30/15/10 formula.
32. Rules & Commish is role-aware.
33. Commissioner settings are grouped into Locked at Kickoff, Live, and Admin.
34. Pause Betting replaces Emergency Pause wording.
35. Commissioner feature toggles for wager types and pools are removed.
36. Pools are voluntary.
37. Versus bets are voluntary.
38. The UI uses “GM vs GM,” not “wallet vs wallet.”
39. Four pool types exist in V1.
40. Pool ties split.
41. Settlement and ledger updates are immediately visible.
42. The UI shall not expose manual ledger editing.
43. The Rules & Commish tab includes the actual How to Play and user-facing Rules content.
44. The UI/UX appendix does not replace protocol authority.

---

## Appendix B — Screen Map

```text
My League
 ├── Fantasy Power Rankings
 ├── Yahoo Standings
 ├── Weekly Matchups
 ├── Team / GM List
 └── Team / GM Detail
      └── Challenge GM

My Action
 ├── Pending Challenges
 │    ├── Accept
 │    ├── Decline
 │    └── Counter
 ├── Active Versus Bets
 ├── Available Pools
 ├── Joined Pools
 └── Settled Activity

My Ledger
 ├── Balance Strip
 ├── Ledger Snapshot
 │    └── Full Ledger
 └── Sheet Snapshot
      └── Full Sheet

Wrap Up
 ├── Current Edition
 ├── Previous Edition
 ├── Next Edition
 └── Week Picker

Rules & Commish
 ├── How to Play
 ├── Rules
 ├── Economy Stop
 ├── Current Settings
 └── Commissioner Controls
      ├── Locked at Kickoff
      ├── Live
      └── Admin
```

---

## Appendix C — Designer Handoff Standard

The designer may refine:

- Exact typography
- Font family
- Font sizes
- Spacing scale
- Divider treatment
- Accent color selection
- Button corner treatment
- Minimal icon selection
- Micro-animation timing
- Final information order within an approved tab

The designer may not change without product approval:

- Five-tab structure
- Tab names
- Mobile-only requirement
- One-column structure
- Wrap Up navigation model
- Ledger versus Sheet distinction
- Role permissions
- User-visible rules structure
- Economy presentation
- Ranking methodology
- Privacy behavior
- Primary flows
- Visual prohibitions
- No-image standard

---

## 28. Revision Status

This document freezes the approved Version 1 UI/UX direction.

Future revisions shall be numbered and shall identify any substantive change to:

- Navigation
- Screen purpose
- User flow
- User-visible content
- Role behavior
- Accounting presentation
- Ranking presentation
- Privacy behavior
- Visual standard
