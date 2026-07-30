# FantasyBeefs Mobile UI/UX Specification

## Revision 3

**Status:** Draft for approval
**Platform:** Mobile only
**Orientation:** Portrait only
**Role:** UI/UX appendix to the FantasyBeefs protocol
**Derived from:** Revision 2 — Bare-Bones V1, SHA-256 `33A95421…4DE7DD36`, 17,523 bytes, filed at commit `893b68e`

---

## 0. Revision Status

Revision 1 §28 requires every numbered revision to identify substantive changes across nine domains. Revision 2 carried no revision-status section and identified none of its changes. That omission is the reason the specification chain broke. This section exists so it does not happen again.

| Domain | Change from Revision 2 |
|---|---|
| **Navigation** | Six tabs reduced to five. `My Team` removed as a primary tab. `Rules & Commish` renamed `Rules & Settings`. Ruling C1, 2026-07-30 |
| **Screen purpose** | §6 repurposed from a `My Team` tab to Team Context, surfaced inside League. Section numbers otherwise preserved to keep the Revision 2 diff readable |
| **User flow** | Unchanged, except that response-card pricing and counter behavior are routed upstream rather than restated. §7, §8 |
| **User-visible content** | `Free to bet` superseded by `Available`. Ruling C3, 2026-07-30 |
| **Role behavior** | Commissioner Top-Off surface specified at field level, restoring the Revision 1 §19.2 field list that Revision 2 dropped. §15.4 |
| **Accounting presentation** | Ledger primary summary set to `Wallet · Available · In Play · Current Settle`. Account Breakdown retained separately. The Sheet remains the reconciliation surface. Rulings C2 and C3, 2026-07-30 |
| **Ranking presentation** | Unchanged |
| **Privacy behavior** | Unchanged |
| **Visual standard** | Unchanged |

**Also incorporated:** SKUNK-R4, 2026-07-30. See §15.3 and §17.5.

**Deliberately not locked in this revision:** response-card pricing behavior, counter semantics, offer/counter/accept escrow mechanics, and Was/Is behavior dependent on those mechanics. See §7.4.

---

## 1. Authority

The protocol governs system behavior, accounting, pricing, settlement, eligibility, and permissions.

This document governs what users see and what actions the mobile interface exposes.

Specific locked screen rulings control over later summaries or generic descriptions unless expressly amended.

### 1.1 Upstream Authority

Two documents sit above this one and are not restated here.

**`LOCKED_VS_DYNAMIC_WAGER_MODEL_RULING.md`** — the wager-freeze model of record. Sections 1–4 adopted 2026-07-19. Gate 5.3 cleared. Gates 5.1 and 5.2 remain open and block that document's own Section 6 cascade. This specification is step 6 of that cascade and is therefore scoped accordingly.

The adopted proposal-freeze model is authority now. A Locked proposal freezes when it is created. A counter creates a new frozen proposal. Acceptance selects a proposal and makes its frozen terms binding. This specification does not revert to acceptance-freeze semantics merely because downstream card copy is pending.

**`SPEC_Response_Card_v1.md`**, identifying as **Response Card Specification Rev 1.1 (Canonical)**, status LOCKED, SHA-256 `726FE9EA…41EC21F`. Canonical for response-card layout, badge colors, explanatory copy, and button behavior. It is scheduled for amendment by §6 step 5 of the wager-model ruling. Where it describes pricing or counter mechanics, that amendment governs the outcome, not this document.

### 1.2 Historical Authority

Revision 1 (`938d14b2`) and Revision 2 (`33A95421`) are retained as history.

Revision 2 remains historical fallback authority where this revision is silent, **except** where superseded by an identified upstream authority, a later product ruling, or an item explicitly marked pending in this revision.

---

## 2. Design Standard

FantasyBeefs shall be:

- Mobile-only
- Portrait-only
- One column
- Text-first
- Spartan
- Fast and direct

No photos, avatars, decorative imagery, casino chrome, or sportsbook styling.

Typography and whitespace create hierarchy. Dashboard grids are prohibited.

---

## 3. Global Navigation

The application shall use **five** persistent bottom tabs:

1. League
2. Action
3. Ledger
4. Wrap Up
5. Rules & Settings

### 3.1 My Team — superseded

Revision 2 §3.1 required `My Team` as a separate primary tab. **That requirement is expressly superseded.**

FantasyBeefs is an overlay on an existing host fantasy platform, not the primary roster-management product. Team and roster information may appear contextually. It does not own a primary navigation tab.

Team context is specified at §6.

---

## 4. Shared Interaction Rules

- Vertical scrolling is the default.
- Horizontal swiping is reserved for the League carousel and Wrap Up editions.
- Primary actions shall use clear text labels.
- Important actions shall not be hidden behind icons.
- Status shall always be shown in text.
- Color may reinforce status but shall never be the only indicator.
- Accepted financial actions shall update balances and the Ledger immediately.
- Irreversible actions shall require confirmation.

Approved status words: Incoming · Pending · Accepted · Countered · Declined · Expired · Active · Locked · Settled · Won · Lost · Push · Refunded · Voided · Published.

---

## 5. League

### 5.1 Purpose

League is the primary betting surface.

Its main component is the **Beef, Open Contracts** carousel.

Standings, matchups, and rankings may appear as secondary context. They shall not replace the carousel.

### 5.2 Beef, Open Contracts Carousel

One opposing GM per card. Users swipe horizontally between GM cards.

Each card shall show:

- Opposing GM
- Opposing team
- Current matchup context
- Three betting cells
- Available
- Relevant offer or lock status

### 5.3 Three Betting Cells

Each GM card shall contain three tappable cells: Moneyline, Spread, O/U.

Each cell shall show the current line and the price or payout information required by the protocol.

Tapping a cell begins the challenge flow for that wager type.

### 5.4 Color Coding

The three-cell card shall use the locked green, red, and yellow treatment to distinguish available sides or market states.

Color shall be supported by labels so the card remains understandable without color.

### 5.5 Bet-Your-Own-Side Rule

A GM may bet only the GM's own side of the matchup. The interface shall not offer the opposing side as a selectable wager.

### 5.6 Available

Every wagering surface shall show one consolidated number:

> **Available**

This is the amount currently available for a new wager.

**`Available` expressly supersedes Revision 2's `Free to bet`.** Ruling C3, 2026-07-30.

The UI shall not force the user to choose a funding source before acceptance. The system determines the funding source under the economy protocol when the wager is accepted.

The detailed account breakdown belongs in Ledger, not on the primary betting card.

### 5.7 Secondary League Context

Below or outside the primary carousel, League may show:

- Fantasy Power Rankings
- Yahoo standings
- Weekly matchups
- Team and GM list

These are read-only league context.

---

## 6. Team Context

Revision 2's `My Team` tab is superseded by §3.1. Its content survives as context, not as a destination.

Team and GM context may appear within League — on carousel cards, in the team and GM list, and in a team or GM detail view.

Available context:

- Team name
- GM name
- Yahoo record
- Current matchup
- Fantasy Power Rank
- Betting Standing
- Wagering Power Rank
- Current weekly activity

It shall not duplicate the host fantasy platform.

**Weekly historical lineup depiction is `PENDING — FR-5.7`.** The `roster_slots` table exists and is empty, with no writer. Until FR-5.7's capture job lands, any lineup surface reflects the current roster only, and shall not be presented as the lineup that was true in a past week.

---

## 7. Action

### 7.1 Purpose

Action is where a GM answers, tracks, and reviews wagers.

### 7.2 Required Sections

- Pending challenges
- Sent offers
- Active Versus bets
- Available pools
- Joined pools
- Settled activity

### 7.3 Response Window

Every challenge shall have a 60-minute response window. The card shall show remaining time. At the end of 60 minutes an unanswered challenge becomes Expired. An expired challenge cannot be accepted.

### 7.4 Response Cards — scope of this section

Response cards are governed by **Response Card Specification Rev 1.1**, which is canonical for layout, badge colors, explanatory copy, and button behavior. **This section does not duplicate it.**

This section locks only mobile placement, taxonomy, perspective, navigation, and visual structure.

**The following behavioral areas are `PENDING GATES 5.1/5.2` — governed upstream by `LOCKED_VS_DYNAMIC_WAGER_MODEL_RULING.md` and the future Response Card specification amendment. This document does not lock them:**

- Anchor-Stake-only counter semantics
- Acceptance-time card repricing copy
- Offer, counter, and accept escrow mechanics
- Was/Is behavior dependent on those mechanics

Where Rev 1.1 currently states behavior in those areas, it is displayed as-is until amended. It is not restated here and gains no additional authority from this document.

### 7.5 Card Taxonomy — locked

Exactly five response-card states exist. No additional states may be introduced.

| Card | Terminal |
|---|---|
| Incoming | No |
| Accepted | Yes |
| Countered | No |
| Declined | Yes |
| Expired | Yes |

### 7.6 Perspective — locked

Response cards are perspective-aware. Issuer and recipient may see different actions for the same challenge.

- The **issuer** never sees Incoming.
- The **recipient** never sees the actionable issuer Countered view, never sees Declined, and never sees Expired.
- The **recipient** may see a read-only pending Countered view.

### 7.7 Revive — locked

Revive is available on Declined and Expired only.

**Revive is available to the original issuer only.** A recipient who wishes to play must create a new challenge from their own side.

**Revive creates an entirely new challenge. It does not reopen the original.** The original record remains permanently in its terminal state.

The escrow and pricing consequences of Revive are `PENDING GATES 5.1/5.2`.

### 7.8 Placement and Navigation — locked

Response cards live in Action, under Pending challenges and Sent offers, and move to Settled activity on reaching a terminal state.

Cards are reachable from a notification and from the relevant Action section. A card shall not require navigation away from Action to be understood or answered.

Terminal cards remain readable as history.

### 7.9 Visual Structure — locked

Text-first. The state name shall always appear as text, never as color alone. No avatars, no animations, no sportsbook styling, no casino graphics.

Badge treatment follows Rev 1.1.

### 7.10 Sent Offers

A sent, unanswered offer shall show opponent, terms, mode, and remaining response time.

A Withdraw action shall appear only where permitted by the governing wager and proposal lifecycle. **This specification does not independently create a withdrawal right.**

### 7.11 Active Versus Bets

Each active wager shall show opponent, wager type, terms, mode, stake, potential return, and Active or Locked status.

### 7.12 Pools

Available and joined pools shall show entry, lock timing, participation, and settlement state.

---

## 8. Wager Flow

The standard Versus flow is:

1. Swipe to a GM card.
2. Tap Moneyline, Spread, or O/U.
3. Review the GM's own side.
4. Enter or confirm BAB.
5. Review Available.
6. Send challenge.
7. Opponent has 60 minutes to accept, counter, or decline.
8. Accepted wager enters the protocol-defined committed/funding state.
9. Wager locks.
10. Wager settles.
11. Balances and Ledger update.

Exact offer/counter/accept escrow timing remains `PENDING GATES 5.1/5.2`. See §7.4.

The UI shall enforce bet-your-own-side, funding requirements, the active-bet limit, lock timing, accepted-wager finality, and protocol-required pushes, refunds, and voids.

### 8.1 Mode Visibility — locked

The Locked versus Dynamic distinction shall be visible before a GM accepts — in offer framing and status, not fine print. Wager-model ruling §4, ruled.

Every initial offer, both modes, shows lineups and odds. A Locked offer additionally explains in plain language that its terms are frozen inside FantasyBeefs, that host-platform lineup changes never touch them at any stage, and that the only way to put different terms on the table is Refresh & Relock in-app.

### 8.2 Dynamic Stake Copy — locked

Gate 5.3 is cleared. The approved copy is authoritative:

> Both lineups and the odds stay live and lock in at kickoff. Your stake stays put — but if the odds shift, your opponent's stake can come down (never up, never past the max set now). That ceiling never grows.

The issuer's Anchor Stake is fixed and never moves on odds. Only the opponent's Derived Stake reprices, capped at its Handshake ceiling.

---

## 9. Ledger

### 9.1 Purpose

Ledger is the GM's BAB accounting record. It must be simple, formal, and trustworthy.

### 9.2 Primary Summary

The top of the tab shall show four user-facing summary metrics:

> **Wallet · Available · In Play · Current Settle**

These are summary metrics. **They are not four ledger accounts.** Ruling C3, 2026-07-30.

The strip shall be concise and shall not become a dashboard grid.

- **Wallet** — current posted Wallet balance.
- **Available** — the amount currently available for a new wager. Same figure shown on wagering surfaces per §5.6.
- **In Play** — the GM's own funded stake in committed, unresolved wagers, across Versus and Pools. Pending offer holds are excluded until acceptance.
- **Current Settle** — what the GM would owe or be owed if the season ended now.

### 9.3 Account Breakdown

Below the summary, Ledger shall show the underlying accounting components:

- Wallet
- Weekly Min Escrow
- Active Bet Escrow
- Championship Reserve

**Summary metrics and account structure shall not be collapsed into one vocabulary.** The summary answers "where do I stand." The breakdown answers "how is it held."

### 9.4 Opening Allocation

| Account | BAB |
|---|---:|
| Wallet | 0 |
| Weekly Min Escrow | 140 |
| Championship Reserve | 80 |
| Total Buy-In | 220 |

Wallet shall not begin with 140 BAB.

### 9.5 Ledger

The Ledger is chronological transaction history.

Format:

```text
Date | From → To | Debit | Credit
```

It shall not be styled as a card dashboard.

The commissioner shall not have a control to manually rewrite ledger entries. Corrections occur only through protocol-authorized transactions.

### 9.6 Sheet

The Sheet is the season reconciliation. Ledger and Sheet remain separate concepts.

- Ledger = chronological transactions
- Sheet = season reconciliation

A GM sees the GM's own Sheet. A commissioner may access the league Sheet.

### 9.7 Current Settle — placement

**Current Settle may appear in Ledger as a summary metric. Ledger does not provide the authoritative reconciliation proof. The Sheet remains the reconciliation surface.** Ruling C2, 2026-07-30.

Ledger explains balances. The Sheet proves them.

Where Current Settle is shown with composition, it is `settlement-relevant assets − obligations`. The full proof lives in the Sheet.

---

## 10. Settlement

Settlement shall follow the claim-first, two-phase settlement protocol.

The UI shall not show settlement as complete until the authorized accounting transaction is complete. The completion-first anti-pattern shall not be mirrored.

After settlement the user shall immediately see result, stake disposition, payout or refund, Wallet change, escrow change, and the Ledger transaction.

---

## 11. Wrap Up

First-class tab. One vertically scrolling article. Horizontal swipe moves between editions. Tapping the week header opens a week picker. Published editions are read-only. Editorial newspaper style. Bet of the Week included.

---

## 12. Fantasy Power Rankings

Approved 40/25/25/10 formula. Methodology shall be viewable.

### 12.1 Luck Index

Separate from Fantasy Power Rankings.

---

## 13. Betting Standings

Ranked by net BAB. Separate from Wagering Power Rankings.

---

## 14. Wagering Power Rankings

Approved 45/30/15/10 formula. Qualification rules and methodology shall be viewable.

---

## 15. Rules & Settings

Renamed from Revision 2's `Rules & Commish`. Ruling C1, 2026-07-30.

### 15.1 GM View

Rules, How to Play, the league's active Economy Stop, and current settings, read-only.

### 15.2 Commissioner View

A commissioner shall additionally see locked-at-kickoff settings, live settings, administrative settings, Pause Betting, Top-Off approvals, commissioner delegates, the league Sheet, Wrap Up publication, and season close.

### 15.3 Settings Groups

**Locked at Kickoff**

- Economy Stop
- **Skunk Fee** — default 10 BAB, commissioner-configurable before the season
- Unspent-Minimum Destination
- Season Final Week
- Pool Rollover
- Championship Distribution

Skunk Fee is a **separate** Locked-at-Kickoff setting and shall not be placed inside the Economy Stop table. SKUNK-R4, 2026-07-30.

The interface shall visually distinguish Skunk Fee from Weekly Minimum. Both default to 10 BAB and are unrelated.

**Live**

- Weekly-Minimum Enforcement — Hard or Soft
- Bet Privacy — The Reveal or Quiet Ledger
- Pause Betting

**Admin**

- League Time Zone
- Commissioner Delegates
- Season Publication & Close

V1 shall not include commissioner toggles for individual wager types, pools, or core product features.

### 15.4 Top-Off Approval Surface

The default commissioner view shall expose pending work immediately, for example `TOP-OFF REQUESTS · 1 PENDING`.

Each pending request shows only what the decision needs:

- GM or team
- Requested amount
- Remaining Top-Off Capacity
- Request time and status
- Reason or note where applicable
- **Approve**
- **Decline**
- **Resulting ledger transaction**

Further detail expands only when needed.

The interface invokes the deterministic system workflow `REQUESTED → APPROVED → POSTING / POSTING PENDING → POSTED`.

**The commissioner does not manually manipulate accounting.** No UI for editing Wallet, editing balances, posting ledger transactions, changing a requested amount as an ad hoc adjustment, or controlling settlement or outcomes. Approval and decline are governed actions.

**The Top-Off Cap numeric anchor remains unresolved. Do not invent one.**

---

## 16. How to Play

Rules & Settings shall contain the actual How to Play content, not a link to it. Plain language, no marketing tone.

---

## 17. User-Facing Rules

### 17.1 Season Economy

Explain buy-in, opening allocation, and what each account is for.

### 17.2 Weekly Minimum

Explain the weekly minimum, enforcement modes, and shortfall consequences.

### 17.3 Wallet & Top-Offs

Explain:

- Wallet contains unrestricted BAB.
- Winnings flow to Wallet.
- `Available` is the consolidated amount available for a new wager.
- Top-Offs require the approved process.
- Top-Offs are recorded in the Ledger.

### 17.4 Championship Reserve

Explain purpose, opening funding, locked status, distribution timing, and that a commissioner cannot repurpose it outside protocol.

### 17.5 Skunk Fee

Per SKUNK-R4, 2026-07-30. Explain:

- **Trigger** — the weekly condition that assesses the fee.
- **Amount** — commissioner-configured, locked at kickoff, default 10 BAB. Not universally fixed.
- **Tie handling** — GMs tied for the weekly Skunk divide **one** configured fee. A tie never creates multiple fees.
- **Obligation, not a debit** — Skunk assessments are off-Wallet obligations. They do not debit Wallet, Weekly Min, wager escrow, or Available.
- **Accrual** — there is **no funded in-season Skunk pot**. An off-Wallet Skunk liability accrues through the regular season, tracked at both the individual and league level.
- **Award** — the season Skunk award belongs to the **regular-season Points For champion**.
- **Settlement timing** — obligations settle at season settlement.

The interface shall explain the individual obligation and the league accrual as concepts. **It shall not expose raw internal ledger account names.**

Skunk is distinct from the Championship Pot. Skunk goes to the regular-season Points For champion. The Championship Pot goes by postseason bracket placement.

### 17.6 Types of Bets

Explain the approved V1 formats.

### 17.7 Versus Bets

Explain voluntary GM-versus-GM wagering, the active-bet limit, finality, and locking. The interface shall use "GM vs GM," never "wallet vs wallet."

### 17.8 Versus Pricing

Explain line, price or odds, stake, potential return, and push behavior.

Exact pricing math remains governed by protocol. The Locked versus Dynamic distinction is governed by `LOCKED_VS_DYNAMIC_WAGER_MODEL_RULING.md`. See §8.1 and §8.2.

Counter and acceptance repricing copy is `PENDING GATES 5.1/5.2`.

### 17.9 Pool Bets

Explain voluntary entry, approved V1 pool types, entry amount, selection, lock timing, tie splitting, and rollover where permitted.

### 17.10 Privacy

**The Reveal** and **Quiet Ledger**, both explained in plain language.

### 17.11 Refunds & Pushes

Explain protocol-required pushes, refunds, and voids.

### 17.12 Settlement

Explain claim-first, two-phase settlement and when a result becomes final.

### 17.13 Postseason

Explain Championship Reserve distribution and season close.

---

## 18. Privacy

The interface shall obey the active privacy mode.

A user shall always retain access to their own wagers and ledger detail.

Notifications and Wrap Up content shall not reveal information prohibited by Quiet Ledger.

---

## 19. Notifications

V1 notifications may include new challenge, challenge accepted, counter received, challenge declined, challenge expired, wager locked, pool locking, wager settled, pool settled, weekly-minimum issue, Top-Off decision, Wrap Up published, betting paused or resumed, and season-close action.

Notifications shall open the relevant screen.

---

## 20. Locked V1 Decisions

1. **Five** bottom tabs: League · Action · Ledger · Wrap Up · Rules & Settings.
2. **My Team does not own a primary tab.** Team context appears within League.
3. League is centered on the Beef, Open Contracts carousel.
4. The carousel shows one GM per card.
5. Each card has Moneyline, Spread, and O/U cells.
6. A GM may bet only the GM's own side.
7. Green, red, and yellow coding is retained.
8. Betting surfaces show one **Available** number.
9. Detailed account balances remain in Ledger.
10. Challenges have a 60-minute response window.
11. Incoming, Accepted, Countered, Declined, and Expired are distinct card states, and no others exist.
12. Response-card perspective differs by issuer and recipient.
13. Revive is issuer-only and creates a new challenge.
14. The app is mobile-only and portrait-only.
15. The app is one-column and text-first.
16. Photos, avatars, decorative imagery, casino chrome, and sportsbook styling are prohibited.
17. Ledger and Sheet remain separate. **The Sheet is the reconciliation surface.**
18. Ledger primary summary is Wallet · Available · In Play · Current Settle. Account Breakdown is separate.
19. Wallet opens at 0 BAB.
20. Weekly Min Escrow opens at 140 BAB.
21. Championship Reserve opens at 80 BAB.
22. **Skunk Fee is a separate Locked-at-Kickoff setting, default 10 BAB, not part of the Economy Stop table.**
23. Wrap Up is a first-class tab, scrolls vertically, swipes horizontally by week, and is read-only once published.
24. Rules & Settings contains the actual How to Play and user-facing Rules content.
25. Fantasy Power Rankings, Betting Standings, and Wagering Power Rankings remain separate.
26. Settlement follows claim-first, two-phase accounting.
27. The UI shall not expose manual ledger editing.
28. The Locked versus Dynamic distinction is visible before acceptance.

---

## 21. Open Items Carried

| Item | Status |
|---|---|
| Response-card pricing, counter semantics, escrow, dependent Was/Is | `PENDING GATES 5.1/5.2` |
| Top-Off Cap numeric anchor | UNRESOLVED. Do not invent |
| Weekly historical lineup depiction | `PENDING — FR-5.7`. Capture job not built |
| Response Card Specification amendment | Scheduled, wager-model ruling §6 step 5 |
| Prototype reconciliation | Rev3.0 and Rev3.1 remain prototype and POR. Neither is authority. No prototype edits authorized by this revision |
