# FantasyStakes UI/UX Rev 4.3 FINAL POR

**Governing Launch Ready UI/UX specification for FantasyStakes 1.0.**

---

## 1. Authority and precedence

FantasyStakes UI/UX Rev 4.3 FINAL POR is the governing Launch Ready UI/UX specification for FantasyStakes 1.0.

Precedence order:

1. FantasyStakes UI/UX Rev 4.3 FINAL POR
2. Later locked Launch Ready economy, postseason, provider, Yahoo, security and operational rulings
3. Rev 4.2 FINAL POR, for visual or interaction behavior not superseded by Rev 4.3
4. Older UI specifications, only where expressly preserved

Rev 4.3 governs presentation and interaction. It does **not** reopen certified Ledger, settlement, Pool, Versus, Skunk, Championship or Credits economics. Those remain governed by their own locked rulings.

Rev 4.2 FINAL POR remains the historical visual baseline for the product. Its typography scale, card grammar, dark palette, statement-style Ledger construction and sheet/overlay mechanics carry forward except where this document states otherwise.

---

## 2. Product identity

Product name:

**FantasyStakes**

Primary product tagline (locked, exact):

```
Real odds. Fantasy stakes. More ways to win.
```

Ledger / trust anchor (locked, exact):

```
Real odds. Fantasy stakes. Ledger keeps score.
```

Both strings are locked verbatim. They may be placed, sized and styled per surface, but the wording, punctuation and capitalization may not be altered, abbreviated, translated or paraphrased.

### 2.1 Removal of prototype and internal material

The production application presents no prototype, engineering or internal-authorship material to users. The following must not appear in any user-visible surface of the shipped product:

- "UI/UX Rev 4.2" or any UI revision designation
- "FINAL POR" or any point-of-record designation
- engineering revision dates
- engineering package or work-package names
- the Fraser D. Coleman masthead byline
- BAB references in any user-facing copy
- internal Python module, file or identifier citations
- FantasyBeefs product naming

The masthead carries product identity only. Legal notices belong in the secondary menu under Legal, not in a persistent masthead byline.

### 2.2 Scope limit on renaming

This is a user-visible language ruling only. Rev 4.3 does **not** authorize or require broad internal renames of compatibility identifiers, database fields, Python packages or existing API paths for branding reasons.

---

## 3. Primary navigation

The five primary game tabs are, in this exact order:

```
Standings · Play · Status · Wrap Up · Account
```

This ordering is mandatory.

Default landing tab: **Standings**

Rules & Settings is no longer a primary tab. It moves to a secondary gear/menu affordance.

### 3.1 Secondary gear/menu

The secondary menu may contain:

- Rules
- League Settings
- Commissioner controls
- Economy configuration
- Provider/admin information
- About
- Legal
- Yahoo attribution and supporting information

### 3.2 Bottom navigation

The bottom navigation must:

- remain visible across the five primary tabs;
- remain in document flow, not float destructively over content;
- respect device safe areas;
- provide a practical minimum 44 px touch target per item;
- use readable labels at the locked type sizes;
- accommodate all five labels — Standings, Play, Status, Wrap Up, Account — without crowding, truncation or forced two-line wrapping.

---

## 4. Game-purpose model

Each primary tab answers exactly one question.

| Tab | Question it answers |
| --- | --- |
| **Standings** | Who is winning FantasyStakes? |
| **Play** | What can I play? |
| **Status** | What is happening with my FantasyStakes action? |
| **Wrap Up** | What happened this week? |
| **Account** | Where do my Credits, obligations and season position stand? |

Product rhythm:

```
Standings → Play → Status → Wrap Up → Account
```

Content that answers a different tab's question belongs in that tab. Competitive ranking belongs in Standings, not Play and not Account.

---

## 5. Mobile readability POR

Governing principle (locked):

> Information needed to understand the current game state must be readable at normal phone viewing distance without zooming. Primary content must not rely on tiny metadata text, extremely low-contrast text or excessive letter spacing. Typography, card density, section hierarchy, monetary figures and navigation sizing must be consistent across all five primary tabs.

### 5.1 Target mobile type hierarchy

| Role | Size |
| --- | --- |
| Main page title | 22–24 px |
| Section heading | 18–20 px |
| Card primary text | 16–17 px |
| Card secondary text | 14–15 px |
| Metadata / tertiary | minimum 12–13 px |
| Summary-strip labels | 13–14 px |
| Summary-strip values | 22–24 px |
| Bottom-nav labels | 11–12 px |
| Touch targets | minimum 44 px |

### 5.2 Additional locked readability rules

- Increase secondary-text contrast against the dark surface.
- Reduce unnecessary uppercase treatment.
- Reduce excessive tracking / letter spacing.
- Favor fewer readable facts over more unreadable facts.
- Maintain typographic and density consistency across all five primary tabs.

Where the Rev 4.2 prototype used sub-12 px metadata, aggressive tracking or `--g2`-level contrast for content the user must read to understand game state, Rev 4.3 supersedes it.

---

## 6. Credits display contract

FantasyStakes uses `$` as the visual shorthand for virtual Credits.

Examples:

```
$10
$80
+$126
−$42
```

`$100` means 100 FantasyStakes Credits. It does not mean US dollars.

Credits:

- have no cash value;
- cannot be purchased;
- cannot be deposited;
- cannot be withdrawn;
- cannot be redeemed.

Whole-Credit display is the standard UI treatment. Internal accounting may remain cents-based. No UI change may weaken authoritative exact-cents accounting, and no rounding performed for display may be written back into an authoritative record.

A concise virtual-Credits disclosure remains present where monetary figures are prominent.

---

## 7. Standings

Standings is the first and default tab. It must look and read like familiar fantasy-football standings.

It contains **three complete standings tables, stacked vertically**.

There is no segmented selector, no carousel, and no extra tap required to reveal another standings category. All three tables are present on the page and reachable by ordinary vertical scrolling.

### 7.1 Table 1 — Overall Standings

```
RK | TEAM | VERSUS | POOLS | NET
```

Overall rank uses an authoritative server-derived net competitive FantasyStakes result.

Raw Wallet balance must **not** determine Overall ranking. Allocation, top-offs and other noncompetitive movements distort Wallet and would misrepresent competitive position.

### 7.2 Table 2 — Versus Standings

```
RK | TEAM | W-L | NET
```

### 7.3 Table 3 — Pool Standings

```
RK | TEAM | WINS | NET
```

### 7.4 Shared Standings rules

- The current user's team row is visually identifiable in all three tables, at any rank, without scrolling hunting.
- Table typography follows the locked hierarchy: table headings at section-heading scale, team rows at card-primary scale, numeric columns legible at a glance.
- Standings renders authoritative season-phase context.

### 7.5 Standings vs Account

- **Standings** is the competitive game ranking.
- **Account** is Credits, accounting and reconciliation.

Account is not the scoreboard. Wallet balance is not competitive rank.

---

## 8. Play

The former League tab becomes **Play**.

Purpose: find and enter available FantasyStakes competitions.

### 8.1 Retained

- League identity as the page heading
- Current week and season-phase context
- FantasyStakes Versus opportunities
- FantasyStakes Pools
- Four-cell summary strip

The page heading uses league identity alone. No "Fantasy Sportsbook" suffix is restored.

### 8.2 Removed

- The "FIRST KICKOFF IN" countdown and its running clock
- "1st", or any standings rank, from the first summary-strip cell
- Any standings information that now belongs in Standings

### 8.3 Four-cell summary strip

```
Net Winnings   |   Wallet   |   Weekly Min Left   |   Available
```

First cell renders as:

```
+$126
Net Winnings
```

and not as:

```
1st · +$126
```

Strip labels and values follow the locked summary-strip type sizes.

### 8.4 Versus discovery

Play keeps the compact vertical Versus discovery treatment established in the final Rev 4.2 design — one rich matchup card at a time in a vertically snapping rail — subject to the Rev 4.3 readability refinements and the card hierarchy in §9.

### 8.5 Pool cards

Play preserves the compact **2 × 2 Pool-card grid** from Rev 4.2.

Play Pools must **not** be converted into Status-style horizontal rails merely for cross-tab consistency.

Readability is improved by limiting each card to essential information:

- Pool type
- Pool name
- Entry amount
- Entries / pot / status, as applicable

Long descriptive microcopy moves out of the card and into the Pool detail surface.

---

## 9. Versus-card hierarchy

Locked hierarchy on the Versus card and its composer:

```
Matchup identity
→ VIEW MATCHUP PREVIEW
→ ML | SPR | O/U
→ supporting projection / read content where appropriate
```

**VIEW MATCHUP PREVIEW** is a clear full-width action row positioned directly **above** the odds markets.

The UX distinction is:

- **Preview** — why does this matchup look this way?
- **Markets** — what do I want to play?

This supersedes the Rev 4.2 composer order, in which the market tiles preceded the preview button.

---

## 10. Matchup Preview

The Matchup Preview is an **analysis surface**, not a second wagering surface.

Odds-market cells are removed from Matchup Preview. The Rev 4.2 "Sportsbook View" terms block, which restated moneyline, spread and total inside the preview, is superseded and removed.

Locked information order:

```
MATCHUP PREVIEW

matchup identity / records

WHY THE LINE LOOKS THIS WAY
analysis text

THE READ
short, stronger takeaway

LINEUPS
Team A lineup
Team B lineup
```

Analysis appears before dense lineup content. The Rev 4.2 ordering, which placed collapsed lineups above the analysis blocks, is superseded.

Closing the Preview returns the user to the Versus card, where the markets remain available and unchanged.

---

## 11. Carousel and rail headings

Remove the up/down arrow icon from swipe copy.

Superseded:

```
FANTASYSTAKES BETS · 11 OPPONENTS · SWIPE ↕
```

Governing:

```
FANTASYSTAKES BETS · 11 OPPONENTS · SWIPE
```

Apply consistently everywhere the redundant directional-arrow convention appears, including Yahoo matchup rails and Wrap Up section headings.

---

## 12. Status

The former Action tab becomes **Status**.

Purpose: track the lifecycle and status of the user's FantasyStakes activity.

### 12.1 Sections

Four sections are retained, in order:

```
ACTION REQUIRED
WAITING
LIVE
COMPLETED
```

All four section headings use the same typography hierarchy. Color and state treatment may differentiate them; type scale may not.

Each section retains one horizontally scrollable row of cards beneath it.

### 12.2 Page heading

The page-level contextual heading may continue to use language such as:

```
WEEK 5 · REGULAR SEASON ACTION
```

"Action" remains appropriate content terminology even though the navigation label is Status. The week and phase are authoritative values, not hard-coded strings.

### 12.3 Readability

Increase card readability and reduce unnecessary dead space. Card primary text, secondary text and status badges follow the locked hierarchy.

### 12.4 Interaction

Browser-native `window.prompt` interaction is not Launch Ready. Every prototype flow that relied on it must be replaced by product UI before certification.

---

## 13. Wrap Up

The former The Week tab becomes **Wrap Up**.

Purpose: weekly FantasyStakes scoreboard and recap.

### 13.1 Retained

- Yahoo matchup results
- FantasyStakes Versus activity and results
- Pools
- Skunk result where applicable
- ML / Spread / O-U recap where supported
- Weekly highlights
- Cumulative and season context
- Week navigation and state selection

### 13.2 Required by Rev 4.3

- Larger matchup text
- Stronger result prominence — the outcome is the loudest element in each row
- Greater vertical separation between Yahoo Matchups, FantasyStakes Bets and Pools
- Easier scanning of outcomes
- Less dense metadata

Wrap Up should feel like a weekly scoreboard, not a compressed report.

### 13.3 Explicit exclusion

Wrap Up does **not** gain a four-cell summary strip. Wrap Up carried no strip in the final Rev 4.2 design and gains none in Rev 4.3.

---

## 14. Account

The former Ledger tab becomes **Account**. The underlying Ledger remains authoritative.

Purpose: understand current Credits, committed positions, obligations and season accounting.

### 14.1 Retained

- Wallet / Available
- Weekly Minimum
- In Play
- Held
- Championship Reserve
- Out of circulation
- Skunk obligations
- Current Settle
- Completed activity and history

The trust anchor is used where appropriate on this surface:

```
Real odds. Fantasy stakes. Ledger keeps score.
```

### 14.2 Readability and disclosure

The top-level Account view must quickly answer, in this order:

1. What do I have?
2. What is in play?
3. How am I doing?
4. What is my Current Settle?

Detailed accounting moves toward collapsible disclosure sections, including as appropriate:

- Allocation / Advances
- Versus Activity
- Pools
- Skunk
- Championship
- Completed Activity
- Reconciliation / history

No authoritative detail is removed. Rev 4.3 reduces initial visual overload by disclosure, not by deletion. Every figure available in the Rev 4.2 Ledger statement remains reachable.

Account is accounting. It is not the competitive scoreboard.

---

## 15. Rules & Settings

Rules & Settings is no longer a primary tab; it lives in the secondary gear/menu.

This area may remain denser than the gameplay tabs, since it is reference material rather than in-game state.

Stale user-facing implementation terminology is removed. The current configurable league economy and later Launch Ready rulings govern any older static Rev 4.2 economic copy; where Rev 4.2 rules text states a fixed figure that is now configuration-derived, the configuration-derived value governs and the static text is superseded.

---

## 16. Commissioner economy setup

Before league activation, the commissioner can configure the league economy.

### 16.1 Editable inputs

| Setting | Range | Default |
| --- | --- | --- |
| Weekly Bet Minimum | $1 – $100 | $10 |
| Championship Pot Contribution | $1 – $1,000 | $80 |
| Skunk Fee | $1 – $100 | $10 |

### 16.2 Read-only / server-derived

- Regular-Season Weeks
- Weekly Minimum Reserve
- Championship Reserve
- Season-Opening Allocation
- League allocation total

The frontend renders authoritative values. The frontend must not reimplement the economic formula.

### 16.3 Season-Opening Allocation presentation

Primary presentation:

```
SEASON-OPENING ALLOCATION
$220 PER PLAYER
```

The amount is dynamic and supplied by the server. `$220` above is an illustrative rendering, not a fixed product constant.

Secondary presentation, beneath the primary figure:

```
League allocation total · 12 teams · $2,640
```

The league total is informational only. It must not imply that FantasyStakes collects money or operates a financial account.

Worked example under defaults: a 13-week league at the default Weekly Bet Minimum and Championship Pot Contribution yields **$210 per player**. The server supplies the value in all cases.

### 16.4 Activation and freeze

Before activation:

- inputs are editable;
- derived values are visible;
- the commissioner reviews the resulting allocation.

Activation requires deliberate confirmation.

After activation:

- settings are frozen;
- fields are noneditable;
- derived values remain visible;
- the UI clearly communicates that configuration is locked for the active season.

Provider or Yahoo setting changes after activation must not reinterpret Credits already issued.

---

## 17. Dynamic season phase

Season phase is never hard-coded.

Play, Status, Wrap Up and Account each render authoritative phase context, such as:

```
Regular Season
Postseason
Championship
```

Postseason eligibility remains server-authoritative. The frontend may not infer eligibility from week numbers or any other client-side heuristic.

---

## 18. Postseason UI

The UI supports the locked championship-track model.

Eligible Versus subjects in the postseason:

- teams still alive on the championship track;
- official third-place participants in championship week.

All league members may continue entering Pools after their own team is eliminated.

The postseason has:

- no Weekly Minimum;
- no Skunk;
- no ordinary consolation or placement Versus subjects.

Yahoo remains authoritative for live Yahoo postseason outcomes. There is no commissioner podium override.

---

## 19. Skunk UI

Current Skunk rules must display:

- the configured Skunk Fee;
- that the subject is the largest regular-season margin-of-defeat loser;
- that a margin tie splits one fee among the tied losers;
- that there is no postseason Skunk;
- that the Pot accumulates through the regular season;
- that the entire Pot is awarded to the highest cumulative Yahoo regular-season Points For;
- that Points For ties use the governed deterministic split;
- that Skunk is contingent;
- that Skunk is not included in the Season-Opening Allocation.

The following are removed from Skunk copy:

- universal `$10` assumptions where configuration applies;
- fixed `$140` cap language;
- fixed 14-week assumptions;
- BAB references.

---

## 20. Championship UI

The Championship surfaces reflect:

- the configured Championship Pot Contribution;
- the 60 / 30 / 10 payout split;
- champion;
- runner-up;
- official third place.

There is:

- no commissioner podium override;
- no standings-based fallback;
- no arbitrary outcome fallback.

If authoritative classification is unavailable, the UI fails closed — it presents an explicit unavailable state rather than inferring a podium.

---

## 21. Demo Mode

Demo is not a separate product UI.

Demo exercises the same surfaces and mechanics as live play:

```
Standings · Play · Status · Wrap Up · Account
commissioner setup · economy · Versus · Pools
Weekly Minimum · Skunk · postseason · Championship · season close
```

Only the source/provider data changes.

Demo must be unmistakably identified to the user. Demo synthetic data must never be presented as Yahoo-provided data, and Yahoo attribution must not appear in a way that implies Demo content originated from Yahoo.

---

## 22. Provider-state presentation

Permitted simple player-facing provider states:

```
DEMO
YAHOO · CONNECTED
YAHOO · SYNCING
YAHOO · NOT SYNCED YET
NOT CONNECTED
LEAGUE UNAVAILABLE
```

Raw provider diagnostics — status codes, token state, sync internals, exception detail — belong in commissioner and operator surfaces, not in ordinary player-facing UI.

---

## 23. Yahoo attribution

The executed Yahoo API Access and Use Agreement is authoritative.

Wherever Yahoo Fantasy Information is displayed, the product implements the required clear attribution:

```
Fantasy data provided by Yahoo Fantasy
```

For web pages, the attribution includes the required hyperlink to an official Yahoo Fantasy page as required by the executed agreement.

Requirements:

- attribution appears on every applicable Yahoo-data page;
- attribution must not impair the persistent bottom navigation;
- attribution uses normal panel or footer placement, not an intrusive fixed overlay;
- Demo must not imply its synthetic data came from Yahoo;
- no invented Yahoo logos or additional marks beyond permitted use.

Yahoo attribution is a Launch Ready contractual gate.

---

## 24. Yahoo storage boundary

The complete intended FantasyStakes product is built. The UI architecture is not crippled while the Section 2(c)(vii) clarification remains open.

Actual live Yahoo-derived information is handled under the executed agreement. Final Yahoo storage-boundary compliance remains a commercial-release gate.

This UI specification package does not alter persistence architecture.

---

## 25. Universal close behavior

The effective final Rev 4.2 treatment is preserved:

- a universal close control;
- positioned **upper-right**;
- visually associated with the active sheet or card;
- common across Versus, Pools, Account detail, Rules, commissioner surfaces and every other pop-out surface.

The close control is not moved to upper-left. Any earlier upper-left treatment is superseded.

---

## 26. Responsive and accessibility

FantasyStakes 1.0 remains a mobile-first web/PWA product.

Certification must eventually cover:

- small phone
- standard phone
- large phone
- landscape
- desktop

and must address:

- bottom-nav target sizing;
- pinch zoom and accessibility zoom;
- safe areas;
- horizontal scrolling behavior;
- sheets and overlays;
- input keyboards;
- content overflow;
- typography at all breakpoints.

---

## 27. Loading, error and empty states

Every primary surface requires intentional states for:

- loading
- no data
- no competitions
- no Status activity
- no Pools
- provider unavailable
- provider not connected
- league not activated
- incomplete economy
- frozen economy
- postseason unavailable
- season complete
- Demo

Raw Python identifiers, cents field names and internal exception strings are never exposed to ordinary users.

---

## 28. Frontend authority boundary

The frontend must **not** authoritatively calculate or decide:

- Season-Opening Allocation
- reserve amounts
- Weekly Minimum release
- Skunk charges
- Pool outcomes
- Versus settlement
- Championship payouts
- postseason eligibility
- authoritative Current Settle

The UI renders backend read models. Presentation-only formatting — whole-Credit display, sign and color treatment, ordering, grouping, truncation — is permitted.

No second economic engine may be created in JavaScript.

---

## 29. Implementation-risk boundary

| Band | Scope |
| --- | --- |
| **GREEN** | Presentation and UI |
| **YELLOW** | Additive read-model contracts where necessary |
| **RED** | Ledger / economic / settlement / postseason authority |

RED changes are prohibited in WP3 unless separately owner-ruled.

The completed WP3A reconciliation found no inherent need for RED changes to deliver Launch Ready UI.

---

## 30. Planned implementation sequence

| Package | Scope |
| --- | --- |
| **WP3B** | Shell + navigation + Standings + readability foundation + commissioner onboarding/economy |
| **WP3C** | Play + Status + Wrap Up + Account + Matchup Preview + Rules cleanup + postseason presentation |
| **WP3D** | Yahoo attribution + provider / Demo presentation |
| **WP3E** | Responsive + accessibility + PWA + error-state certification |

---

## 31. Relationship to Rev 4.2

Rev 4.3 supersedes Rev 4.2 where the two conflict. Rev 4.2 behavior not addressed here is preserved.

Superseded by Rev 4.3:

| Rev 4.2 behavior | Rev 4.3 ruling |
| --- | --- |
| Nav: League · Action · Ledger · The Week · Rules & Settings | Standings · Play · Status · Wrap Up · Account; Rules & Settings to secondary menu |
| League tab is the default landing surface | Standings is the default landing tab |
| No standings surface | Three stacked standings tables (Overall, Versus, Pool) |
| "FIRST KICKOFF IN" countdown clock on League | Removed from Play |
| First strip cell shows `+$126 · 1st` | Shows `+$126` / `Net Winnings`; rank lives in Standings |
| Composer order: market tiles → VIEW MATCHUP PREVIEW | Identity → VIEW MATCHUP PREVIEW → markets |
| Matchup Preview contains a Sportsbook View odds block | Odds-market cells removed from Preview |
| Preview order: lineups → why the line → the read | Why the line → the read → lineups |
| Rail headings end in `SWIPE ↕` | `SWIPE`, arrow removed |
| Fixed `$220` / `$140` / `$80` allocation figures in copy | Server-derived, configuration-dependent values |
| Fixed `$10` Skunk Fee and "10 BAB" rules copy | Configured Skunk Fee; no BAB language |
| 14-week / `$140` cap assumptions | Removed; Regular-Season Weeks is server-derived |
| Masthead byline and revision block | Removed from the production application |
| Sub-12 px metadata, heavy tracking, low-contrast content text | Locked readability hierarchy in §5 |

Preserved from Rev 4.2:

- universal close control, upper-right (final v17 treatment);
- league identity as the Play heading, with no "Fantasy Sportsbook" suffix;
- compact vertical Versus discovery rail and the 2 × 2 Pool grid, subject to Rev 4.3 readability refinements;
- Wrap Up with no four-cell summary strip;
- the authoritative Ledger statement content, now presented under Account with progressive disclosure;
- the dark palette, sheet/overlay mechanics and card grammar;
- LOCKED / DYNAMIC Versus mode presentation;
- commissioner Top-Off, GM ledger cards and League Reconciliation surfaces.

Rev 4.3 does not reintroduce retired UI concepts, including the segmented standings selector, the League-tab countdown, upper-left close placement or the "Fantasy Sportsbook" heading suffix.

Commissioner economy setup shows the League allocation total as a secondary informational figure beneath the primary per-player Season-Opening Allocation, per §16.3.

---

*End of FantasyStakes UI/UX Rev 4.3 FINAL POR.*
