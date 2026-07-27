# FantasyStakes — UI/UX Continuation Package

**UI/UX Rev 2.0** · 2026-07-27 · Fraser D. Coleman
**Prototype artifact:** `FantasyStakes_UIUX_Prototype_Rev2_0.html` · `sha256 A00C882BFC7BBA0407E815A99EC92FE8500FAA745403F533AA2D38DB5014BEA7` · 923 lines · LF
**Repo destination:** `tools/prototype/` → `index.html`
**Scope:** UI/UX walkthrough only. This is not a program transition package. Backend remediation is untouched and unaddressed here.

---

## 0. How to use this package

The walkthrough is mid-flight. Open the prototype at a mobile viewport before proposing anything visual, resume at the component named in §6, and keep the two speeds from §3.

The prototype is **not committed**. It has never been placed in the working tree. Placement instruction is in §7.

---

## 1. The working model

| Party | Role |
|---|---|
| **Claude** | Proposes, analyses, recons against the record, records rulings |
| **ChatGPT** | Independently translates and reviews, recommends |
| **Fraser** | Rules. Sole decision-maker |

Two-class rule holds. Evidence products — greps, inventories, width measurements — may be produced freely and in parallel. Judgment products — orderings, taxonomies, design recommendations — are produced blind and independently, then diffed.

**Walkthrough speed rule, effective this thread.** Two speeds:

- **Mechanical** — rename, label, spacing, typography, icon, copy normalization, reversible static edits. No re-audit, no restating prior rulings, no re-deriving settled implications. Record, note the edit, move.
- **Structural / semantic** — money meaning, state transitions, wager lifecycle, permissions, data source, backend contract, protocol conflict, new interaction state. Full dependency check, surface conflicts, smallest question, record, move.

**Change rule, standing:** preserve the designed experience, reconcile the contract underneath, and **surface the conflict before changing anything.**

**Revision rule.** Minor bump per approved UI/UX iteration batch (`2.1`, `2.2`…). Major bump on substantial structural redesign or completion of a walkthrough phase. Displayed in the masthead as `UI/UX Rev X.Y · 2026 · Fraser D. Coleman`. Delivered artifacts carry the revision in the filename. Every continuation package states the current revision.

---

## 2. POR — rulings made this thread

### 2.1 Brand

| ID | Ruling |
|---|---|
| UI-033 | `OUR THING · YOUR LEAGUE` is the canonical tagline lockup wherever the tagline is a designed brand element. Prose may read *Our Thing. Your League.* No periods, middot separator, all caps. |
| UI-035 | Product rename is **presentation-layer only**. Out of scope and explicitly unchanged: repo names, Railway services, Pages URLs, backend identifiers, code symbols, deploy/restore procedures, internal infrastructure terminology. |
| UI-036 | Visible product name is **FantasyStakes**, closed up, no space, on all GM-facing surfaces: `<title>`, iOS display name, Front Door wordmark, masthead, visible product copy. iOS display name keeps the full string pending an on-device truncation test; shorten to `Stakes` only if it truncates badly. |
| UI-037 | `BAB` and existing product vocabulary unchanged absent separate ruling. **Superseded in part by UI-046** — `BEEF BETS` retired. `BAB` still stands. |

### 2.2 Front Door

| ID | Ruling |
|---|---|
| UI-034 | Gate mark (padlock disc) **deleted**. `Members only` carries the closed-league signal alone. `margin-top: 34px` replaces the disc's vertical separation. Reason: emoji are colour fonts and ignore `color`, so the disc could not take the gold and rendered OS-dependently. |
| UI-038 | Yahoo purple `#5f01d2` **kept** on the provider sign-in button. Not palette drift and not an exception — a provider OAuth button is a different class of element and carries provider colour. Open question closed. |
| UI-039 | Prototype commissioner bypass line **kept** until real OAuth is wired, then deleted. Ship-blocker, not a today problem. |
| UI-040 | `REV · 2026 · FRASER D. COLEMAN` door footer **kept**. |
| UI-041 | The automatic-seat-match sentence stays **exactly as written**. One shared no-match state after successful Yahoo auth when no seat resolves. Do **not** distinguish "wrong Yahoo account" from "not a member" unless the backend can actually distinguish them — an email lookup returns "no row" for both. |

### 2.3 Masthead

| ID | Ruling |
|---|---|
| UI-042 | Masthead becomes a **two-sided identity treatment**. Left: `FantasyStakes` wordmark, and beneath it the canonical lockup `OUR THING · YOUR LEAGUE`. Right, right-aligned: the revision line. Week context does **not** go in the masthead. |
| UI-043 | Revision line breaks onto **two right-aligned lines** — `UI/UX Rev 2.0 · 2026` / `Fraser D. Coleman`. Required, not cosmetic: measured single-line layout overflowed 288px of usable width by 71.5px, because the tagline (185.9px) is wider than the wordmark and sets the left column. Two lines measures 278.8px. Fits with 9px clear. |

### 2.4 Tab bar

| ID | Ruling |
|---|---|
| UI-044 | All five tab icons replaced with **inline SVG**, `stroke:currentColor`. Reason: the five emoji split into two presentation classes — crossed swords and scales default to text presentation and take the gold, clipboard/book/newspaper are emoji-presentation and render full colour regardless. The active-tab gold state therefore worked or failed depending on which tab you were on, decided by the OS. |

### 2.5 My League header

| ID | Ruling |
|---|---|
| UI-045 | Header is a two-line title. Line 1: the **Yahoo league name**, primary, wraps freely, **never truncated**. Line 2: `Fantasy Sportsbook · Week 8 · Regular Season` — fixed descriptor plus live context consolidated into one secondary line. Other tab headers unchanged. Measured 232.3px against 296px usable, 64px headroom for longer season phases. |
| UI-052 | **Kickoff countdown**, right side of the My League header, horizontally opposite the title. Before kickoff: digital countdown above the label `FIRST KICKOFF IN`. At and after the first kickoff: `LIVE` above `WEEK UNDERWAY`. Must be tied to the actual first kickoff of the current fantasy week, not a static clock. |

### 2.6 My League strip

| ID | Ruling |
|---|---|
| UI-047 | Four-cell structure **retained**. In Play is **not** added to the strip and does **not** displace the weekly minimum. |
| UI-048 | `League rec` is the **Yahoo fantasy-football record**, not the betting record. Betting record lives on My Action as `Bet record`. Standings place shows beside it — record at 16px, place at 10px grey. Rank must come from **Yahoo-authoritative standings data only**. Do not calculate or recreate standings rank client-side from W/L, PF, or any local tiebreak logic. |
| UI-049 | `Min left` → **`Weekly min left`**. Value and concept unchanged. Measured: two lines at 320px, one line at 360px+, never three. Passes the 22px label gate. |
| UI-050 | `Available to Bet` → **`Available to bet`**. Propagates to both strips. |
| UI-051 | Gold **text** treatment removed from the Available-to-bet cell; label and value colour match its siblings. The cell **keeps its border** and remains the strip anchor. UI-005 amends from "one gold anchor per strip" to **"one anchor cell per strip"** — the anchor is no longer colour-defined. Implemented as a new `.cell.anchor` class so no other gold cell was touched. |

### 2.7 Big Board (formerly Beef Bets)

| ID | Ruling |
|---|---|
| UI-046 | Section renamed **`BIG BOARD`**. `BEEF BETS` retired. Eyebrow: `BIG BOARD · 11 OPPONENTS · SWIPE →` — the count communicates completeness, so no `ALL`, and no `See all` card. This is the GM's complete weekly Versus board. |
| UI-053 | **All 11 opponent cards** in a 12-team league. Not a curated subset. |
| UI-054 | Ordering: **current Yahoo opponent first**, then the remaining 10 by **Yahoo standings rank**. Yahoo-authoritative rank only; do not recreate standings order or tiebreak logic locally. |
| UI-055 | Card heading is **`vs. [Yahoo team name]`** — the Yahoo fantasy team name, never the GM's personal name. **One line, always.** Long names use single-line CSS ellipsis; the card never wraps and never changes height. Full team name appears in the card interaction / pop-out. Measured budget: ~108px inner after `vs. `, roughly 17 characters at 12px. |
| UI-056 | Beneath the name: `[Yahoo record] · [Yahoo rank]`, e.g. `6–1 · 1st`. Both Yahoo-authoritative. |
| UI-057 | Each card keeps three Versus market cells — `ML` · `SPR` · `O/U` — each showing that market's current line for the **viewing GM** against that opponent. |
| UI-058 | **Market colour is always the viewing GM's perspective.** Green = viewing GM favoured. Amber = neutral / near even. Red = viewing GM underdog. Applies independently per market, so one card can carry green, amber and red at once. Colour never characterizes the opposing team. *Recon note: the prototype already behaved this way; this ruling is a documentation fix, not a code change.* |
| UI-059 | Amber **kept** as the neutral visual state. Its numerical band is **not defined in the UI thread** — routed to the odds/protocol ruling track. Current amber rendering preserved until that ruling exists. |
| UI-060 | The current Yahoo opponent is one of the same 11 cards and simply leads the rail. **No separate card type, no duplicate elsewhere in the Big Board.** |

### 2.8 My Action identity

| ID | Ruling |
|---|---|
| UI-061 | My Action tiles identify the opponent by **Yahoo team name**, matching the Big Board convention. Tile shape: team name / `Moneyline · LOCKED` / `incoming · 42m`. Full GM identity may appear elsewhere if needed; the primary wager identity in the UI is the Yahoo team. |

### 2.9 Challenge sheets

| ID | Ruling |
|---|---|
| UI-062 | Win and loss figures must be the **same kind of number**. Both net. Was `If you win +$44` (gross, includes the GM's own returned stake) against `If you lose −$20` (net) — overstating the upside by 83%. Now `+$24` / `−$20`, with `Total pot $44` retained above as context. |
| UI-063 | The challenge sheet carries a **stake input**. Was hardcoded `$20`. FR-7.50 validation had no field to validate. |
| UI-064 | The sheet must **disclose that the issuer's funds are held when the challenge is sent**, and `Available to bet` must visibly drop on send. |
| UI-065 | **Mode must be visible before acceptance** — a `LOCKED` or `DYNAMIC` badge beside the market name, plus the ruled one-line explainer below. Badge is scannable in the My Action tile list before the sheet is opened. Required by Section 4 of the adopted Locked-vs-Dynamic ruling: the distinction lives in the offer framing and status, not in fine print. |
| UI-066 | The incoming-challenge sheet **shows both starting lineups**. Same section: every initial offer, both modes, shows lineups and odds. Under proposal-freeze the lineup snapshot *is* the offer. |

---

## 3. Economy POR — amended this thread

**Authoritative source:** the economy model settled 2026-07-26. Supersedes walkthrough §2, VAL-10 Rev 23's cap anchor, and the Top-Off UI spec's examples.

### 3.1 Wallet — corrected definition

The earlier phrasing "Wallet = net winnings + top-offs" described the **credit set**, not the balance. Corrected:

```
Wallet sources (credits) — two, nothing else
  · settled net winnings credited to Wallet
  · approved BAB top-offs

Current Wallet balance
  Wallet = cumulative Wallet credits − cumulative Wallet-funded debits
```

Starts at **$0**.

**Cannot enter Wallet:** the Championship Reserve ($80 at the default stop, never bettable, held to the season-end pot); the Weekly Min Reserve ($140, which is not Wallet money — it releases weekly into Available to bet, and the old table calling that column "Wallet" was the named defect). Skunk fees never debit Wallet — a skunk fee is a receivable added to dues owed, not a Wallet transaction.

**Debit set is currently a set of one:** Wallet-funded wager stakes. "Any other valid Wallet debits" has no members yet. Nothing is to be added to that set by accident.

**Escrow is never subtracted from a balance that is already "remaining."** Funding the wager is what removes the Wallet-funded portion in the first place. Do not compute `$20 − $20 escrow`.

### 3.2 Available to bet — verified

```
Available to bet = Wallet + Weekly min left
```

Verified against the POR on five points, all holding:

1. The formula is **exact and always governs** — stated as an identity, not an approximation.
2. When `Weekly min left` reaches `$0`, **Available to bet equals Wallet**. This is the ordinary mid-week state for any active GM, not an edge case.
3. **In Play is not subtracted.**
4. **Escrow is not separately subtracted.** (3 and 4 are the same statement — In Play *is* escrow. One rule: escrow is never subtracted. This is why `_challenge_reserved` was retired.)
5. The value is **derived from canonical ledger state**, never maintained as an independent balance — Governing Invariant 10, recompute never increment.

Available to bet is a **hard ceiling on any single wager**, not merely a display.

### 3.3 Funding order — made explicit

**Funding is tranche-first.** The Weekly Min tranche is consumed before Wallet on every wager. This was implicit in the POR's depletion table and stated nowhere as a rule. It is not cosmetic — it decides weekly-minimum compliance and therefore whether a shortfall sweeps.

Worked example, verified consistent with the POR's own table:

| | Wallet | Weekly min left | Available to bet | In Play |
|---|---|---|---|---|
| Before | $30 | $10 | **$40** | $0 |
| $20 stake — $10 tranche, then $10 Wallet | $20 | $0 | **$20** | $20 |

### 3.4 Known display consequence

Once the week's tranche is spent, **Wallet and Available to bet display the identical number for the rest of the week.** Two of four cells read the same most of the time. Not wrong. It was the strongest argument for putting In Play in the strip; that was declined under UI-047 and is not reopened.

---

## 4. Wager lifecycle POR — recorded this thread

**Governing source:** `LOCKED_VS_DYNAMIC_WAGER_MODEL_RULING.md`, Sections 1–4 **ADOPTED 2026-07-19**, plus `SIMULATION_ENGINE_MODULE_SPEC_Rev7.md`.

> A Locked proposal freezes when it is created. A counter creates a new frozen proposal. Acceptance selects one proposal and makes its frozen lineup, odds, stakes, and settlement terms mutually binding. Later Yahoo lineup changes do not alter the accepted Locked Bet.

### 4.1 Locked Versus — proposal-freeze

- A Locked **initial proposal freezes when it is created**.
- At proposal creation, snapshot and freeze: covered Yahoo lineups, projections, odds/line, both stakes, payout, settlement terms.
- Later Yahoo lineup changes do **not** modify that proposal.
- A **counter creates a new immutable frozen proposal** using then-current Yahoo lineups and recalculated terms. It replaces the proposal on the table; the original record stays immutable for history.
- **Acceptance does not freeze or reprice anything.** It selects the frozen proposal currently on the table and makes that exact snapshot mutually binding.
- **No re-counter.** Once a counter is on the table, the original issuer may only accept or decline.
- Settlement reads the accepted FantasyStakes lineup snapshot, not either GM's later Yahoo lineup. Yahoo remains the source of player *statistics*; FantasyStakes is the source of *which player IDs are covered*.

**Corrected mid-thread.** Acceptance-freeze wording surfaced earlier in this thread and was ruled **stale phrasing returning by mistake, not a new ruling.** The adopted proposal-freeze model stands.

**UI copy:** *"Lineups and odds freeze the moment you send this. Later Yahoo lineup changes — yours or theirs — do not touch these terms."*

### 4.2 Dynamic Versus

At Handshake, three things freeze: the **model version**, each side's **maximum exposure**, and the **escrow ceiling**. Odds do not freeze. Between Handshake and Final Lock, informational refreshes are **nonbinding and move no money**.

- The issuer's **Anchor Stake is fixed** and never moves on odds.
- Only the opponent's **Derived Stake reprices** — it may hold or decrease, **never increase** above the Handshake ceiling.
- **The ceiling never grows.** It is the load-bearing no-increase guard, not merely an exposure limit.

**UI copy must carry timing *and* stake direction.** Timing alone reintroduces the defect that gate 5.3 was written to fix — draft copy once said stakes could "flex up or down," contradicting Rev 7.

### 4.3 Dynamic Final Lock

**Verified against Rev 7 line 225** — *"earliest covered kickoff (`_nfl_lock_time` / per-challenge kickoff already computed in `beef_engine`)."* The mechanism already exists.

Final Lock occurs immediately before the **earliest scheduled NFL kickoff involving any player in either final starting lineup covered by the wager**. At that one event:

- the official final simulation runs under the Handshake-frozen model version;
- final lineup, odds and terms freeze;
- the Dynamic Adjustment applies **once**;
- settlement later reads those frozen Final Lock terms.

**Wager-specific.** Not the first NFL game of the week, and **not** a sequence of per-player partial locks. Separate from the My League `FIRST KICKOFF IN` clock.

### 4.4 `per_bet_lock.py` — reconciled, not conflicting

Two mechanisms, two jobs, no collision. `per_bet_lock` is called by the accept flow to block **accepting** a bet on an already-kicked-off game. Final Lock governs **Dynamic repricing**. The earlier concern that its per-row tripwire logic contradicted a single wager-wide Final Lock is closed.

### 4.5 Escrow timing — confirmed from the record

- Issuer **Anchor Stake escrows at initial-offer issue** (`escrow:challenge:{id}`, drawn min-first-then-wallet).
- **Counter creation moves no money.**
- **True-up occurs at acceptance / Handshake.**

The challenge sheet must therefore disclose that the issuer's funds are held when the challenge is sent. Confirmed by evidence, not recommendation — `LOCKED_VS_DYNAMIC` §5.1 reference behaviour plus Spec 2's documented scope.

---

## 5. Unresolved — UI/UX and protocol items that affect visible behaviour

Only items that change what a GM sees. Backend remediation is out of scope.

| # | Item                                                                                                                                             | Class | Blocking |
|---|--------------------------------------------------------------------------------------------------------------------------------------------------|---|---|
| U-01 | **Gold-cell scope.** UI-051 removed gold from Available to bet. Never answered: does this apply **only** to that cell, or to **every gold cell in the app**? `Settled wk`, `Proj settle`, `Biggest winner` are still gold. Implemented conservatively — a new `.cell.anchor` class, no other gold cell touched. | LAYOUT | Nothing today. Decide before Ledger and Wrap Up walkthrough. |
| U-02 | **Amber threshold band.** The odds engine defines only two states: `isFav = p > 0.5` (line 958), `isFavY = yourProb >= 0.5` (1341), `favIsA = margin >= 0` (1116). **No neutral band exists anywhere in the engine.** Amber has no source. Routed to the odds/protocol track. | PENDING RULING | Amber renders as-is meanwhile. |
| U-03 | **Predicate disagreement at exactly 50%.** Those three predicates use `>` in one place and `>=` in two. Immaterial for a colour chip, material for the money path. Routed out of the UI thread. | PENDING RULING | Not UI-blocking. |
| U-04 | **Unspent Weekly Min destination.** Commissioner setting *Sweep to pot / Withhold and return* is **unruled**. The *return* branch breaks the Wallet definition — returned tranche money would be a third credit source, and Wallet has exactly two. Sweep-to-pot has no such problem. | PENDING RULING | Decides whether Wallet's definition survives contact with the setting. |
| U-05 | **Yahoo standings rank field.** UI-048 and UI-054 both require Yahoo-authoritative rank. `/league/standings` is **not verified** to return a rank field. Cells are **BACKEND CONTRACT NEEDED**, not SUPPORTED NOW. Client-side derivation is explicitly forbidden. | BACKEND DEPENDENCY | Rank displays static until verified. |
| U-06 | **Yahoo league name source.** UI-045 needs it. No confirmed endpoint field.                                                                      | BACKEND CONTRACT NEEDED | Static string in prototype. |
| U-07 | **First-kickoff timestamp source.** UI-052 needs it. `per_bet_lock.py` contains `_is_real_kickoff()` band logic and `beef_engine` computes a per-challenge kickoff, so timestamps exist somewhere — that is a **lead to grep**, not a confirmed contract. | BACKEND CONTRACT NEEDED | Countdown is a JS demo clock. |
| U-08 | **iOS home-screen truncation.** `FantasyStakes` is 13 characters against a ~11–12 ceiling. On-device test outstanding. Shorten to `Stakes` only if it truncates badly. `apple-mobile-web-app-title` is independent of `<title>`. | COPY | Needs a phone, not a decision. |
| U-09 | **Front Door 320px render.** Wordmark measured 238px against 256px usable — arithmetic, not a render. Container had no usable browser; DejaVu fonts would have been a wide bracket, not Fraser's renderer. **The rendered mobile viewport is the visual authority.** Screenshot outstanding. | LAYOUT | Confirm before the door is called closed. |
| U-10 | **Tab-bar icon appearance.** Requested observation never returned. Now moot for colour — SVG takes the gold — but the new glyph set has never been seen on a real screen. | LAYOUT | Confirm in the next screenshot. |
| U-11 | **Pull / cancel window.** The State Lab mocks a *pulled* state. Whether an issuer may withdraw an unaccepted offer, and until when, is **unruled**. Mocked as `PENDING`. | PENDING RULING | Blocks that state's design. |
| U-12 | **Pool mechanics — four unruled surfaces.** Rank pool scoring, prediction pool mechanics, rollover conditions, tie handling, negative-pool self-pick block. All mocked as `PENDING` rather than inventing behaviour. | PENDING RULING | Blocks pool walkthrough depth. |
| U-13 | **"Weekly min left" reads as obligation, not balance.** The formula uses it as a spendable tranche balance. The two numbers are always identical so nothing displays wrong — but a GM reading it as an obligation and one reading it as a balance take opposite feelings from the same `$0`. | COPY | Revisit if Rules copy has to explain it. |

---

## 6. Resume point

**My Action → incoming challenge state, remaining sub-components.**

UI-061 through UI-066 settled identity, mode visibility, lineups, and net figures. Still open on that surface, in order:

1. **Expiry semantics** — the outgoing sheet never tells the sender the offer expires or when; the incoming sheet says `42m`. Asymmetric. Where does the sender see their own clock?
2. **Counter flow** — the button now reads `Refresh & relock counter`. The recipient changes their Yahoo lineup first, then FantasyStakes pulls it and creates a new frozen proposal. That two-step needs a designed path, and the no-re-counter rule needs to be visible to the issuer.
3. **Accepted Locked card.**
4. **Accepted Dynamic card**, plus refresh and Final Lock states.

Then Pools, using the State Lab as the review surface.

**Use the State Lab.** Tap `STATE LAB` in the masthead. 13 Versus states and 10 Pool states render as a gallery, each with a status tag. It exists so the remaining lifecycle can be reviewed visually rather than discussed abstractly.

---

## 7. Prototype changes in this pass

Applied in one edit pass from `2f3cce36…` (the rename-only build, never placed) to `A00C882BFC7BBA0407E815A99EC92FE8500FAA745403F533AA2D38DB5014BEA7`. 562 → 923 lines. LF throughout, zero CR bytes. JS syntax-checked clean with `node --check`.

| Area | Change |
|---|---|
| Rename | Six surfaces → `FantasyStakes`. Line 529's `Fantasy Beefs` space defect absorbed. Zero residue. |
| Front Door | `.disc` div and CSS rule deleted. `Members only` given `margin:34px 0 8px`. |
| Masthead | Rebuilt as flex two-column. Left `.mastL`: wordmark + `OUR THING · YOUR LEAGUE`. Right `.mastR`: two-line `UI/UX Rev 2.0 · 2026` / `Fraser D. Coleman`, plus a `STATE LAB` entry. |
| Tab bar | All five emoji → inline SVG, `stroke:currentColor`, 18×18. |
| My League header | Two-column `.thead`. Left: league name + consolidated secondary line. Right: live countdown + `FIRST KICKOFF IN`, flipping to `LIVE` / `WEEK UNDERWAY` at zero. |
| League strip | `5–2` + `3rd`; `Weekly min left`; `Available to bet`; `.cell.anchor` replaces `.cell.gold` on that cell only. |
| Ledger strip | Same two label changes, same anchor swap. |
| Big Board | Eyebrow → `BIG BOARD · 11 OPPONENTS · SWIPE →`. Four cards → **11**, headed `vs. [team]`, Yahoo opponent first then by rank, `record · rank` beneath, viewer-perspective market colours. `.bcard .nm` given single-line ellipsis. |
| My Action | Tiles carry Yahoo team names and mode badges — `Moneyline · LOCKED`, `Spread · DYNAMIC`. |
| Challenge sheet | Rebuilt: mode badge, ruled explainer, live stake input with reprice, net win/loss, `Total pot` retained, hold disclosure, `Send challenge · hold $N`. |
| Incoming sheet | Rebuilt: mode badge, mode-specific ruled explainer, both starting lineups, net figures, `Refresh & relock counter`. |
| State Lab | New overlay. 13 Versus states, 10 Pool states, status tag per card, `PENDING` where unruled. |

**Not applied:** nothing approved was held back. Placement of the file was deliberately deferred so one placement covers the whole thread rather than five.

**Placement — ThinkPad X13, PyCharm terminal (PowerShell)**

Folder: `C:\Users\frase\OneDrive\PycharmProjects\fantasy-beefs\`

```powershell
Copy-Item "$env:USERPROFILE\Downloads\FantasyStakes_UIUX_Prototype_Rev2_0.html" .\tools\prototype\index.html -Force
(Get-FileHash .\tools\prototype\index.html -Algorithm SHA256).Hash | Out-String
```

Expect `A00C882BFC7BBA0407E815A99EC92FE8500FAA745403F533AA2D38DB5014BEA7`. Use `Copy-Item`, never `Get-Content`/`Set-Content` — the latter re-encodes and flips LF to CRLF, changing the hash and inflating the diff.

**Also outstanding:** the stray repo-root `index.html` holding `d35b6710…` is superseded and untracked. Harmless today. At commit, a root `index.html` becomes the Pages front door at `fdchub.github.io/fantasy-beefs/`. Not touched.

---

## 8. Next-thread opener

> Resuming the FantasyStakes UI/UX walkthrough at **UI/UX Rev 2.0**.
>
> Prototype is `tools/prototype/index.html`, `sha256 A00C882BFC7BBA0407E815A99EC92FE8500FAA745403F533AA2D38DB5014BEA7`, 923 lines. Open it at a mobile viewport and confirm you have before proposing anything visual.
>
> Operate in **live prototype walkthrough mode**: one component at a time, `Look at / Current / Meaning / Backend / Question`, actual on-screen labels not internal spec names, wait for my ruling before moving on. Two speeds per §1 — mechanical decisions get recorded and skipped past; structural ones get the full dependency check. Surface conflicts before changing anything. The rendered mobile viewport is the visual authority; HTML behaving correctly is not evidence that it looks correct.
>
> Read §2 through §4 of this package as governing POR. Do not re-derive settled rulings. Do not reopen backend remediation.
>
> Resume at **My Action → incoming challenge, expiry semantics** (§6, item 1). Use the State Lab for the lifecycle states.
>
> Deliverable at thread end: another UI/UX Continuation Package at **Rev 2.1**, plus the consolidated prototype as `FantasyStakes_UIUX_Prototype_Rev2_1.html`.
