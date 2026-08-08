# FantasyStakes — Mobile UI/UX Specification, Revision 4.1

**Status:** Product of Record — current
**Date:** 2026-07-30
**Author of record:** Fraser D. Coleman
**Artifact:** `spec/FantasyStakes_UIUX_Prototype_Rev4_1.html` · SHA-256 `b2ab382f775086df469487fe5ad637757eb070e6794e8e1d8551264bd5129b88` · 147,401 bytes
**Hosted:** `tools/prototype/index.html` — byte-identical to the canonical artifact — https://fdchub.github.io/fantasy-beefs/tools/prototype/
**Supersedes:** Revision 4.0

---

## 0. Authority

> Revision 4.1 is the current UI/UX Product of Record. For UI presentation, navigation, screen purpose, user flow, user-visible terminology, layout, and visual behavior, Rev4.1 supersedes prior UI/UX specifications, POR registers, prototype candidates, transition packages, and concept mockups.
>
> Upstream game, wager, accounting, settlement, and economy protocols remain authoritative for underlying mechanics. Rev4.1 governs their approved UI presentation and must not silently redefine those mechanics.

This document is standalone. A reader needs nothing else to build the approved UI. It does not reference Rev1, Rev2, Rev3, Rev3.1, the Rev3.1 POR register, transition packages, partial prototypes, concept HTML files, or historical UI findings as sources of current intent.

Historical artifacts are retained but are no longer consulted for UI intent. Revision 4.0 is superseded and is history.

### 0.2 Change from Revision 4.0

One approved change: Head-to-Head cards on League gain a short sportsbook teaser and a `Tap for more ›` call to action, described in §2.5. Everything else in Rev4.0 carries forward unchanged.

The Rev4.1 build also corrected demo-data defects found during canonicalization. These are presentation fixes, not mechanic changes:

| Defect | Correction |
|---|---|
| Ledger `Versus wins` summary read `+$96 · 4 wagers`; the detail sheet held five rows totalling `+$186` | Summary and detail reconciled to `+$200 · 5 settled winning wagers` |
| Ledger `Pool net` summary read `+$13`; detail rows summed `+$20` | Summary corrected to `+$20` |
| Settled Versus row dated `Wk 7` at current Week 5 | Redated `Wk 4` |
| Pool rollover lineage read `Rolled from Wk 8 · rolls to Week 9` | Redated `Rolled from Wk 4 · rolls to Week 6` |
| Top-Off approval dated `Wk 8` | Redated `Wk 4` |
| Review documentation block rendered as scrollable app content below the phone experience | `.reviewdoc` set to `display:none`; source retained, never rendered |

Ledger history now reconciles to the League strip: `+$200 − $94 + $20 = +$126`.

### 0.1 What this document does not decide

Where an upstream mechanic is unresolved, the UI shows the unresolved state honestly and invents nothing. Two such cases exist and are marked in place. Rev4.1 does not resolve either:

- **Top-Off Cap** has no numeric anchor. The UI renders `cap pending`. No figure is invented.
- **Locked/Dynamic mode propagation** on outgoing offers is not yet implemented end to end. The prototype carries a truthful in-code limitation note.

---

## 1. Global frame

### 1.1 Masthead

Left, stacked:

```
FantasyStakes
OUR THING · YOUR LEAGUE
```

`Fantasy` in bone, `Stakes` in gold. The lockup is all caps, middot separator, letter-spaced, no periods. Right, right-aligned across two lines: the revision line and author.

The masthead is fixed and identical on every tab.

### 1.2 Navigation

Five primary tabs, in this order:

```
League · Action · Ledger · The Week · Rules & Settings
```

Inline SVG icons, `stroke:currentColor`, so the active-gold state renders identically across operating systems. No emoji.

There is no My Team primary tab.

### 1.3 Palette

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0c0a07` | app background |
| `--mast` | `#12100c` | masthead |
| `--card` | `#161309` | cards |
| `--tile` | `#1b1811` | strip cells, inset tiles |
| `--line` / `--line2` / `--edge` | `#221d11` / `#2a2415` / `#3a3220` | dividers, borders |
| `--bone` | `#e8e2d2` | primary text |
| `--gold` | `#c9a24a` | accent, active state, anchor values |
| `--green` / `--green2` | `#97c459` / `#c0dd97` | positive money |
| `--red` | `#f09595` | negative money |
| `--amber` | `#ef9f27` | pending, unresolved |
| `--g1` / `--g2` | `#8a8573` / `#5a5546` | secondary, tertiary text |

Money is tabular-figure monospace everywhere. Positive green, negative red, anchor figures gold.

### 1.4 Strip grammar

Every tab that summarizes state uses the same four-cell strip: a four-column grid, equal widths, tile background, small grey label above a larger centered value. Icon-free. One cell per strip may carry an anchor or gold treatment to mark the figure that matters most on that screen.

### 1.5 Front door

Yahoo OAuth only. Provider purple `#5f01d2` is retained on the sign-in button as provider colour, not palette drift. One shared no-match state after successful auth when no seat resolves; the UI does not distinguish "wrong Yahoo account" from "not a member," because the backend cannot.

---

## 2. League

### 2.1 Purpose

League is the GM's league-specific fantasy sportsbook. It answers three questions in the first few seconds: how am I doing as a wagerer, how much do I have available, and where is the action.

### 2.2 League identity

```
CULV Appreciation Society · Fantasy Sportsbook
Week 5 · Regular Season
```

`Fantasy Sportsbook` takes the same font, weight, and colour as the league name. It is not a badge, pill, outlined button, or differently coloured label. Preferred on one line; the separator and phrase are held unbreakable so a narrow viewport wraps between the league name and the phrase, never mid-name.

The first-kickoff countdown sits right-aligned in the header block.

### 2.3 Four-cell strip

| Cell | Label | Value |
|---|---|---|
| 1 | Net Winnings | `+$126 · 1st` |
| 2 | Wallet | `$55` |
| 3 | Weekly Min Left | `$10` |
| 4 | Available | `$65` |

Cell 1 is season net wagering winnings and league rank by that figure. **The wager win/loss record does not appear in this cell.** The dot separator is rendered in secondary grey so rank reads as context rather than a second figure. Cell 4 carries the anchor treatment.

Icon-free, consistent with §1.4.

### 2.4 Your Fantasy Big Board

Section title: **YOUR FANTASY BIG BOARD**, with an optional light right-side helper label such as `this week's action`.

The Big Board contains exactly two zones:

1. **HEAD-TO-HEAD**
2. **LEAGUE POOLS**

**Equal billing is a layout requirement, not a judgment.** Both zones sit in the same flex parent at `flex:1 1 0`, so they receive equal height allocation and identical full-width footprint. Neither can grow at the other's expense. Neither is visually subordinate.

### 2.5 Head-to-Head

Horizontal card rail with scroll-snap. One card per opponent; a twelve-team league yields eleven. Each card carries opponent identity, record and rank context, and a three-cell market row: **ML**, **SPR**, **O/U**. Market cells take favourite, neutral, or underdog colour treatment.

Horizontal discovery is correct here because the opponent count is large and variable.

**Card teaser — Rev4.1.** Beneath the market row each card carries a short sportsbook-style teaser and a call to action. Full card contents, in order:

1. opponent identity
2. record and rank context
3. ML / SPR / O/U row
4. one short matchup teaser
5. CTA — exactly `Tap for more ›`

The teaser runs one to two short lines on mobile, roughly 25–50 characters. It is a hook, not analysis: it gives the GM a reason to open the card. Detailed information stays behind the opened card.

**The teaser is written against that card's actual line.** A card at `+165` with a low total reads *"Biggest dog on the board. Low total — live upset."* A card at `−7.5` reads *"Biggest spread you'll lay. Their ceiling is live."* Teaser and odds are coupled by intent; changing a card's odds requires rewriting its teaser.

Tone is sportsbook, not fantasy commentary. Acceptable register: *"Tight matchup — the spread may be a little too wide."* / *"Live dog spot if the projections hold."* / *"Records say mismatch. The line says otherwise."*

The CTA string is exactly `Tap for more ›`. Not "Tap for the read." Not any variant.

The teaser is visually subordinate to the market row — 9.5px, secondary grey. The CTA is 9px gold, semibold. Neither increases card height: the rail stretches cards to the zone height and centres their content, so the teaser occupies space already allocated. The entire card remains the tap target.

Tapping a card opens the existing challenge interaction. Wager mechanics are unchanged by Rev4.1.

Eyebrow: `HEAD-TO-HEAD · 11 OPPONENTS · SWIPE →`

### 2.6 League Pools

Exactly four weekly pool opportunities in the normal weekly slate, rendered as a **2 × 2 grid of rectangular pool cards**.

No horizontal scrolling. No vertical scrolling inside the zone. All four visible together.

Each card carries:

- type badge — `TEAM`, `MATCHUP`, or `ROLLOVER`
- pool title
- footer line: entry figure, participation count, chevron

Badge colours: TEAM green on green-tint, MATCHUP blue on blue-tint, ROLLOVER gold fill on dark text. The rollover card takes a lighter border and renders its carried pot in gold.

Cards stretch to fill their grid cell rather than sitting at a fixed width. The whole card is the tap target.

Full pool question text does not appear here; it lives in the opened pool detail. That omission is what lets four cards breathe in half the page.

Eyebrow: `LEAGUE POOLS · 4 THIS WEEK`. No swipe cue, because there is no swipe.

### 2.7 Removed from League

Yahoo Matchups sportsbook analysis is removed from League entirely. It lives in The Week. No banner explains the move and no module replaces it; the freed height is what gives the two Big Board zones equal billing.

---

## 3. Action

### 3.1 Purpose

Action is the GM's personal wager-management view. It is the only place a GM manages their own wagers. The Week never duplicates it.

### 3.2 Strip

`Season Bet Record` · `Bet this week` · `Upside left` · `Downside`.

### 3.3 Response cards

Five card states with per-side visibility rules, unchanged by Rev4.1:

| State | Issuer sees | Recipient sees |
|---|---|---|
| Incoming | no | yes |
| Countered | yes, actionable | yes, read-only |
| Accepted | yes | yes |
| Declined | yes | no |
| Expired | yes | no |

Every card answers four questions within a few seconds: what happened, what changed, why it changed, what can I do now.

### 3.4 Independent odds refresh

A responder must be able to refresh current odds as an **informational** action, independent of deciding.

**Refresh odds:**

- updates the displayed current market state
- does **not** accept
- does **not** decline
- does **not** create a counter
- does **not** mutate the frozen original offer

For a Locked offer, the card shows both figures distinctly:

```
Offer terms      +165 · frozen when sent
Current odds     +145 · updated now
```

Before refresh, the current-odds row reads `— not checked` in secondary grey. After refresh it takes bone text with the figure in gold, and the helper line changes to `updated just now · the offer above is unchanged`.

For a Dynamic offer the card shows a single `Live odds` row instead, because the terms are not frozen.

The three decision actions are **Take it**, **Counter**, **Decline**, in that order. Counter creation remains a separate action.

The former `Refresh & relock counter` control is retired. It conflated checking current information with beginning a counter, which meant a responder could not look without committing.

---

## 4. Ledger

### 4.1 Purpose

Ledger explains balances and records history. It does not prove the season position.

### 4.2 Primary summary

Exactly four cells, under the eyebrow `YOUR POSITION`:

```
Wallet · Available · In Play · Current Settle
```

`Current Settle` takes the gold cell and is tappable. Immediately below the strip, one line of secondary copy states that Current Settle is reconciled on the Sheet and that this Ledger records transaction history and account breakdown.

### 4.3 Ledger and Sheet

**Ledger = transaction and account history. Sheet = authoritative season reconciliation.**

Current Settle may be summarized in the Ledger. **The Ledger does not prove it.** The Sheet proves it.

The Ledger carries a compact Current Settle card near the foot: label, figure, direction, and a plain statement that the Ledger does not prove this number, with a gold `Open the Sheet ›` action. Tapping either the summary cell or the card opens the Sheet.

### 4.4 The Sheet

An overlay. Current Settle in a gold-bordered block at the top, then the full reconciliation:

- settlement-relevant assets, itemized, with subtotal
- GM obligations, itemized, with subtotal
- the arithmetic line `Current Settle (assets − obligations)`

Closing note: settlement-relevant assets minus GM obligations from posted accounting state; season-opening and Top-Off advances are owed back; the Championship contribution is excluded once contributed; Earned Season Awards are final entitlements not yet posted elsewhere; Skunk Fees are obligations, never assets.

### 4.5 Account Breakdown

Kept separate from the summary and from the Sheet. Labelled `Account Breakdown & History`. Collapsible groups: opening wallet, top-offs received, versus wins, versus losses, pool net, in-play versus wagers, pending offer holds, weekly min left, out of circulation, Skunk Fees, earned season awards, advance obligations.

Pending offer holds are shown separately and are **not** In Play.

### 4.6 Top-Off request

`Request Top-Off` sits in the Ledger header. The GM-side request flow is unchanged. Remaining capacity renders as `cap pending` until the cap anchor is ruled.

---

## 5. The Week

### 5.1 Purpose

The Week is the persistent weekly editorial and sportsbook-analysis destination for the league. It is league-level coverage. It is not a second Action tab.

The tab label is permanently **The Week**. No `Wrap Up` label survives anywhere in the primary navigation.

### 5.2 Two independent controls

Week selection and week state are separate controls, stacked.

**Week navigator** — previous, current, next-available:

```
‹   Week 4   Week 5   Week 6   ›
```

- the selected week is gold-highlighted
- previous weeks remain navigable
- **the next week is shown only after its Preview has been published. No empty or unpublished future week is displayed.**
- the navigator shows a window of up to three real weeks. When the selected week is the newest available, the window holds at that week and extends backwards, so the highlighted week sits at the right edge rather than the centre. Centring is a preference, not a rule; never display a week that does not exist in order to centre.
- arrows dim at their limits and do not move past week 1 or past the newest available week
- horizontal swipe on the tab body supplements the arrows

**Week state selector** — three views for the selected week:

```
Preview | View Results | Review
```

States unavailable for the selected week render dimmed and, when tapped, show a short panel explaining the gate.

### 5.3 Preview

The pregame fantasy-football and sportsbook analysis experience.

From publication through the week's first kickoff, the following refresh: odds, lines, Yahoo starting lineups, projections, and relevant analysis inputs. A freshness indicator reads `Updated 18 min ago` with a green status dot and a gold `Refresh` action.

**At the week's first kickoff, Preview freezes permanently.** Frozen means odds no longer refresh, lineup data no longer refreshes, projections no longer refresh, and analysis no longer refreshes. The frozen Preview remains historically accessible as the exact final pregame snapshot, marked with a grey dot and the line `Frozen at Week N first kickoff · final pre-kickoff snapshot`.

There is no editorial intro block. The slate begins immediately.

**Slate card contents:**

- matchup identity, both teams
- record and standing context for each side
- ML, SPR, O/U in the standard three-cell market row
- projected score
- two to three short sentences of matchup commentary

The teaser's job is to help the GM decide whether to open the matchup. It does not contain the complete analysis.

Below the slate, the week's open pools are listed compactly with entry and participation, and a note that all pools lock at the week's first kickoff.

### 5.4 Opened matchup — section order

Fixed order. This ordering is load-bearing: numbers first, then the data behind them, then the market interpretation, then the fantasy interpretation.

**1. Sportsbook View — open by default, not collapsible.**
Favorite, moneyline both sides, spread, total, projected score, status, outlook.

**2. Starting Lineups & Projections — collapsible.**
Immediately below Sportsbook View. Side-by-side starters, per-player projections, team projection totals, and a note that projections are pregame and refresh until kickoff.

**3. Why The Line Looks This Way — collapsible.**
Gambling and market analysis only. Why one side is favoured, how the spread is constructed, why the total sits where it does, odds and line movement, market edge or risk, and how lineup and projection inputs translate into the line. This section does not carry general fantasy storytelling.

**4. The Read — collapsible, last.**
Fantasy-football analysis. Important players, positional matchups, lineup strengths and weaknesses, recent form, head-to-head history, matchup tendencies, and fantasy storylines. Expands on the slate teaser.

Closing note: analysis only, no wager runs through this card; to bet, use Head-to-Head on the Big Board.

### 5.5 View Results

Becomes the active state at the week's first kickoff.

League-wide current and developing results. Close matchups first, then the full slate, then developing storylines: Skunk watch, pool outcomes, standings implications.

**Does not duplicate Action.** A closing note directs the GM to Action for their own wagers.

For a past week, View Results remains available as the historical in-progress view and is labelled as such rather than presenting as live.

### 5.6 Review

Review becomes active **only when both** of the following are true:

1. the necessary Yahoo results are final, **and**
2. FantasyStakes settlement for that week has completed

Until both are satisfied the active state remains View Results. **Review must never present unsettled outcomes as final.** Where the gate is unmet, Review shows a short panel naming both conditions.

Review contains the completed weekly story: Yahoo matchup results, matchup narratives, Versus results, Pool results, Skunk of the Week, High Score, biggest wagering winners and losers, standings movement, and notable league storylines.

### 5.7 Historical access

Past weeks retain all three views. Preview stays the frozen pre-kickoff snapshot. View Results stays available as the historical in-progress view. Review is the final completed state.

Historical content is **not** collapsed into Review only.

On a past week the header countdown block swaps to `FINAL / WEEK N` rather than showing a stale kickoff timer, and the subtitle reads `Completed`.

---

## 6. Rules & Settings

### 6.1 Structure

Segmented zones: Rules sheets, League settings, and Commish.

### 6.2 Rules sheets

Five canonical sheets: **The Money**, **Weekly Grind**, **Big Money**, **The Bets**, **The Fine Print**.

All five are canonical content. Per-section provenance tagging is retired — mixed `authoritative / draft / pending` badges no longer appear, because every sheet is now canonical and the distinction has no referent.

**Locked copy points that must survive rewording:**

- Wagers fund from **Weekly Min first, then Wallet**. Stated in the funding sheet and repeated in the offer-hold copy.
- **All pools for the week lock at the week's first kickoff.**
- Held stake on a failed offer is released according to its original funding and the governing weekly-account rules. Never "returns to your wallet" unconditionally.
- No payment-processing language on any GM-facing surface. Settlement reads `Final · settled · Credits posted to Wallet`.

### 6.3 League settings

Read-only for GMs. Commissioner-set before the season, locking at kickoff: Economy Stop, Standard Pool Bet, and the Skunk Fee. Championship split is a fixed league rule.

### 6.4 Skunk Fee

Presented as **Skunk Fee** throughout. Never "Skunk fine."

| Property | Presentation |
|---|---|
| Default | 10 BAB |
| Configurability | commissioner-configurable before the season |
| Lock | locks at kickoff |
| Relationship to Weekly Minimum | separate from it |
| Assessment | off-Wallet obligation |
| In-season pot | none — no funded holding account |
| Accrual | accrues as a season obligation on the GM who takes it |
| Award | season total owed at season end to the regular-season Points For champion |

The UI must state plainly that a Skunk Fee never reduces what a GM has Available.

### 6.5 Commish

Three sections, in order:

**A · Top-Off requests.** The request queue. Each row carries GM and team, requested amount, Remaining Top-Off Capacity, request time, status, and a **Resulting ledger transaction** block showing the advance as an obligation, the amount posted to Wallet, and the net effect on Current Settle. Approve and Decline actions. Workflow `REQUESTED → APPROVED → POSTING → POSTED` is system-owned; the commissioner never edits balances directly.

Remaining capacity renders `cap pending`. No cap figure is invented.

**B · League reconciliation.** The advances-outstanding identity: GM-attributable holdings plus league-level holding accounts against total advances outstanding, with an explicit balance or variance state. Skunk Fees are excluded from this identity as obligations rather than credit-holding locations.

**C · GM ledger cards.** Twelve expandable cards from the illustrative dataset.

---

## 7. Interaction conventions

- Overlays open as a bottom sheet with a single close action.
- Collapsible sections use a chevron that rotates on open.
- Horizontal rails use scroll-snap.
- Money figures are tabular monospace and never reflow on update.
- Illustrative demo data is unified to a single coherent league state at Week 5. Names, weeks, and amounts are not design priorities except where they reveal a mechanics, calculation, ledger, or state-transition defect.
- No GM appears as their own opponent in any demo state.
- No settled result may be dated in a future week relative to the current week.

---

## 8. Conformance checklist

A build conforms to Rev4.1 when all of the following hold:

1. Five primary tabs: League · Action · Ledger · The Week · Rules & Settings
2. No `Wrap Up` label in primary navigation
3. League header reads `CULV Appreciation Society · Fantasy Sportsbook` in one type treatment
4. League cell 1 reads `Net Winnings` / `+$126 · 1st` with no W/L record
5. Strip is icon-free and uses the common four-cell grammar
6. `YOUR FANTASY BIG BOARD` contains exactly two zones
7. Head-to-Head and League Pools receive equal zone height and full width
8. League Pools renders four cards in a 2 × 2 grid with no scrolling in the zone
9. Yahoo Matchups does not appear on League
10. The Week has independent week navigation and a three-state selector, and never displays an unpublished future week
11. Preview shows a freshness indicator and freezes at first kickoff
12. Frozen Preview remains historically accessible
13. No editorial intro block precedes the slate
14. Slate cards carry a two-to-three-sentence teaser, not full analysis
15. Opened matchup order is Sportsbook View → Lineups → Why The Line → The Read
16. Sportsbook View is open by default; the other three are collapsible
17. Review is gated on Yahoo final **and** settlement complete
18. Past weeks retain all three views
19. Response cards carry an independent Refresh odds action
20. Refresh odds does not accept, decline, counter, or mutate the offer
21. Locked offers show frozen terms and current odds distinctly
22. Ledger summary is Wallet · Available · In Play · Current Settle
23. Account Breakdown is separate from the summary
24. The Sheet proves Current Settle; the Ledger does not
25. Commish carries the Top-Off queue with Resulting ledger transaction
26. Top-Off Cap renders `cap pending`, never an invented figure
27. Skunk Fee follows §6.4 in full
28. No payment-processing language on GM-facing surfaces
29. No GM opposes themselves in demo data
30. No settled result is dated in a future week
31. Head-to-Head cards carry a teaser and the CTA `Tap for more ›`, exact string
32. Teasers are matchup-specific, not generic filler
33. Card height is not increased by the teaser
34. Review documentation never renders as scrollable app content
35. Ledger summary figures equal their detail-sheet totals
36. Ledger history reconciles to the League Net Winnings figure
37. The hosted prototype at `tools/prototype/index.html` is byte-identical to the canonical artifact
38. The hosted prototype identifies itself as `UI/UX Rev 4.1`

---

## 9. Open items carried, not resolved

| Item | State |
|---|---|
| Top-Off Cap numeric anchor | unresolved · do not invent |
| Locked/Dynamic mode propagation on outgoing offers | not implemented · truthful limitation note in code |
| Weekly historical lineup depiction | pending upstream |
| Weekly Pool Bet rotation | scoped as the next task, not built |

Rev4.1 governs the presentation of these. It does not resolve them.
