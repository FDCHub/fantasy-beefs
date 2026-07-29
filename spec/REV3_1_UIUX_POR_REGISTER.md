# Rev3.1 UI/UX POR Register

**Date:** 2026-07-29
**Branch:** `remediation/foundation-phase-1` · **HEAD:** `ff70f56572411a134a6e2e84ae98a086bb01b8dc`
**Status:** POR RECORDED · NOT IMPLEMENTED
**Authorizes nothing.** No rebuild of Rev3.0 or the `_partial` candidate. Rev3.1 rebuild
authorization comes separately.

**Design objective:** minimalist, highly intuitive, exposing the deterministic FantasyStakes
mechanics without unnecessary screens, duplicate information, or hidden required workflows.

**Standing scope rule:** illustrative names, weeks, and demo amounts are not design priorities
except where they reveal a mechanics, calculation, ledger, or state-transition defect.

---

## UI-VS-1 — Unified Versus Workspace

**Status:** POR RECORDED · NOT IMPLEMENTED

**Superseded:** `opponent/market sheet → separate challenge composer → separate lineups sheet`.

**POR:** one Versus interaction = one persistent workspace.

### Challenge creation
Tapping a Versus opponent opens one workspace containing opponent name; record/rank/current-week
context; ML / Spread / O-U market row; collapsible **LINEUPS & PROJECTIONS**; collapsible
**CHALLENGE TERMS**; Cancel.

**Default collapsed state fits the mobile viewport with no vertical scroll.**

Selecting a market does not navigate. It keeps the workspace open, visibly highlights the
selection, and expands Challenge Terms.

### Challenge Terms
Selected market · LOCKED / DYNAMIC · concise mode-specific explanation · stake control ·
Available to bet / minimum · own stake · opponent stake · total Pot · win-net / lose-net ·
Send challenge.

### Stake default — $0
Default stake is **$0**. No prepopulated wager amount. The GM must actively establish the amount
before Send is a valid wager action.

**UI default only.** Does not create or imply a minimum-bet or validation mechanic beyond the
governing spec.

### Lineups & Projections
Standalone Versus lineup sheet eliminated. Its side-by-side content lives inside the workspace.
Expanded content may scroll; the no-scroll requirement binds the **default collapsed state only**.

### Accordion behavior
Mutually exclusive. Opening one collapses the other. Persisting across every toggle: selected
market, LOCKED/DYNAMIC selection, entered stake.

Required experience: `select market → configure wager → inspect lineups → return to wager`,
no lost state, no sense of having left the task.

### Incoming challenges
Same principle. One workspace holds opponent; market and wager terms; mode; economics;
expandable lineup/projection information; Accept / Counter / Pass; counter controls when invoked.
The GM never leaves the response workflow to inspect lineups.

### F7 — OPEN
Selected LOCKED/DYNAMIC mode must remain visibly identifiable on the outgoing offer and
applicable subsequent wager states. **Not bolted onto the old nested architecture.** Implemented
when UI-VS-1 is built.

**Current-artifact note.** `sendChallenge()` carries a truthful `PROTOTYPE LIMIT` comment stating
mode is selected but not propagated. That comment stays until UI-VS-1 makes it false.

---

## UI-COMMISH-TOPOFF-1 — Commissioner Top-Off Surface

**Status:** POR RECORDED · NOT IMPLEMENTED

**Defect, verified in the artifact.** `topOffSubmitted()` tells the GM the request *"appears in
the commissioner queue."* No such queue exists. The Commish surface renders 12 GM accounting
cards via `renderCommishGMs()` and nothing actionable. Missing MVP functional surface.

**Location:** Rules & Settings → Commish.

### Default Commish view
Minimal. A compact section exposing pending work immediately, e.g.
`TOP-OFF REQUESTS · 1 PENDING`.

Each pending request shows only what the decision needs: GM/team · requested amount ·
Remaining Top-Off Capacity · request time/status · **Approve** · **Decline**.

Further detail expands or opens only when needed.

### Governed workflow
The interface invokes the deterministic system workflow:
`REQUESTED → APPROVED → POSTING / POSTING PENDING → POSTED`
as required by the governing Top-Off specification.

**The commissioner does not manually manipulate accounting.** No UI for editing Wallet, editing
Credit balances, posting ledger transactions, changing a requested amount as an ad hoc
adjustment, or controlling wager settlement or outcomes.

Approval and decline are **governed actions**. Ledger, Wallet, obligation, capacity, posting,
idempotency, and failure handling remain system-owned.

Any authorization or self-approval rules in the authoritative Top-Off specification are preserved
exactly.

**Top-Off Cap numeric anchor remains unresolved. Do not invent one.**

---

## UI-LEDGER-1 — Ledger Hierarchy Simplification

**Status:** POR RECORDED · NOT IMPLEMENTED
**Not an accounting-model change.** Preserve the accounting proof; make the normal Ledger
understandable at a glance.

### Reference example — arithmetic verified
| | |
|---|---|
| Wallet | $55 |
| Weekly Min Reserve | $90 |
| Weekly Min Left | $10 |
| In Play | $28 |
| Out of circulation | $8 |
| Earned Season Awards | $24 |
| **Assets** | **$215** |
| Opening advance | $220 |
| Top-Off advances | $40 |
| **Obligations** | **$260** |
| **Current Settle** | **−$45** |

Checked by direct arithmetic: `55+90+10+28+8+24 = 215`; `220+40 = 260`; `215−260 = −45`.
Matches the `COMMISH_GMS` row for `Sam O. (you)` — `[55,90,10,28,8,24,40,0]`. Consistent.
**These mechanics are unchanged by this ruling.**

### Layer 1 — live summary
Retain both compact strips.
`Wallet · Weekly Min Left · In Play · Available`
`Net winnings · Skunks · Top-Off Remaining · Current Settle`
The GM gets the important answers before reading any accounting detail.

### Layer 2 — explain current balances
Replace repetitive *"How we got here / What is still committed"* presentation with compact
balance explanations. Rows may expand to detail. **The default screen does not enumerate every
historical transaction to prove a subtotal.**

**`IN PLAY · $28`** shows contributing categories rather than implying Versus only:
`Versus — $X` · `Pools — $Y` · `Total In Play — $28`.

Pending offer holds are separate and excluded. If shown, as secondary information below:
`Pending offer holds · $25` with `Held · not In Play`.

**Sample component amounts are not POR.** Categories and the accounting definition matter; the
demo amounts do not.

### Layer 3 — Current Settle
One compact proof replacing the overlapping settlement sections:

`CURRENT SETTLE · −$45` — *You would owe $45 if the season ended now.*
`Assets · $215` — Wallet, Weekly Min Reserve, Weekly Min Left, In Play, Out of circulation,
Earned Season Awards.
`Obligations · $260` — season-opening advance, Top-Off advances, Skunk fines when nonzero.
`Current Settle = settlement-relevant assets − obligations`.

Do not repeat Current Settle through separate *"settle later"*, *"owe back"*, and then another
complete calculation unless a distinct piece of information requires it.

### Skunk presentation
A Skunk fine is an **obligation**. Never presented so it reads as both an asset awaiting
settlement and an obligation. When zero, no repeated `$0` rows. When nonzero, under obligations
and any appropriate summary metric.

**Verified in the artifact:** Skunk currently appears in five Ledger locations — the season strip
(598), a collapsible section (671/674), an obligations flat row (698), and the settle summary
(717) — four of them showing `$0`. This is the redundancy the ruling targets.

### Progressive disclosure
Minimalist default: current position · major composition · Current Settle proof. Transaction
history stays available by drill-down and does not dominate the default experience.

---

## UIL1-M1 — RULED 2026-07-29

**Ruling.** Layer 2 must **not** imply that displayed activity rows mathematically reconstruct
the Wallet balance. Season wager P&L and Wallet movement are different concepts, because wager
funding draws from Weekly Min as well as Wallet.

**Do not** add a mandatory `Funded into wagers −$Z` line to the minimalist default view. My
recommendation of reading 1 is **overruled**.

`WALLET · $55` is the **current posted Wallet balance**. Explanatory copy, not arithmetic:

> **Wallet · $55**
> *Current posted balance after wager funding and settled activity.*

Top-Off, Versus, and Pool rows, where shown, are **activity summaries and drill-down entry
points** — not an additive proof of `$55`. Their visible subtotals are not required to sum to
the balance.

Full transaction reconstruction belongs in drill-down history, not the default hierarchy.

**Current Settle remains the one place with explicit arithmetic proof:**
`settlement-relevant assets − obligations = Current Settle`.

**Design principle established:** one proof, not two. The Ledger proves Current Settle. It
explains Wallet.

### Finding as originally raised — retained for the record

**The Layer 2 Wallet composition did not reconcile as written.**

Proposed shape: `Opening $0 · Top-Offs +$40 · Versus +$X net · Pools +$Y net` explaining
`WALLET · $55`.

From the artifact's own `openLgDetail()` totals: Versus wins `+$186`, Versus losses `−$94`
→ Versus net `+$92`. Pool net `+$20`. Together `+$112`, which matches the Net winnings strip.

`0 + 40 + 92 + 20 = $152` — **not $55.** The shortfall is $97.

`$152` is exactly the superseded Model A Wallet figure removed earlier in the correction pass.
So the breakdown as written reconstructs the retired number.

**Cause:** the shape has inflows only. Wagers fund from Weekly Min first, then Wallet — so
Wallet-funded stakes are an outflow the explanation omits.

**Two readings, and they are not equivalent:**
1. `Versus +$X net` means season P&L. Then a `Funded into wagers −$Z` row is **required**, or the
   subtotal cannot close.
2. `Versus +$X net` means net *Wallet effect* — winnings minus Wallet-funded stakes. Then it
   closes at $55, but the row no longer means what "Versus net" reads as, and it will not match
   the `Net winnings +$112` strip directly above it.

**Disposition:** neither reading is adopted. The ruling above removes the premise — Layer 2 makes
no additive claim about Wallet, so there is no subtotal to close. The `$152` coincidence is
recorded as evidence of why the additive framing was hazardous, not as a defect to repair.

**Downstream effect:** the `+$92 / +$20 / +$112` figures rest on settled-result rows dated
**Wk 6 and Wk 7** at a current week of 5. Because Layer 2 no longer needs those figures to
reconcile anything, the future-week rows are decoupled from UI-LEDGER-1 and handled as
illustrative data — see below.

---

## Resolved by this ruling

**F3 component amounts — CLOSED as a blocker.** *"Do not turn arbitrary Rev3.0 sample component
amounts into POR"* removes the requirement to preserve `$16` and `$12`. The rebuild sets Versus
components to sum to `$24` against Pool `$4`, totalling the `$28` In Play aggregate, which keeps
the commish row and Current Settle intact. No further ruling needed.

**F3 residual — ABSORBED into UI-LEDGER-1 Layer 2.** The Ledger In Play block labelled
`Versus wagers` becomes `Versus / Pools / Total`.

---

## Not changing

These UI rulings authorize no change to deterministic game or economic mechanics. Mechanics are
not inferred from prototype data.

Governing concepts remain spec/POR-sourced: Wallet · Weekly Min Reserve · Weekly Min Left ·
Available to bet · pending holds · In Play · Out of circulation · Top-Off advances ·
season-opening advance · Championship contribution · Earned Season Awards · Skunk obligations ·
Current Settle.

**In Play** = the GM's own funded stake in committed/accepted, unresolved wagers. Includes Versus
and Pool wagers. Pending Versus offer holds excluded until acceptance/commitment.

**Navigation:** `League · Action · Ledger · Wrap Up · Rules & Settings`.

**Canonical Rules POR** stays separate from these visual simplifications and replaces stale
Rev3.0 Rules copy during the correction/rebuild. *(Already applied in the `_partial` candidate.)*

---

## Scope boundary

Agreed change list is these three items. Do not broaden without first identifying a genuine
missing workflow or usability problem.

**Do not collapse** Pool entry, Top-Off lifecycle states, Live vs Settled wager states, or other
distinct lifecycle moments merely to reduce card count.

---

## Future-week illustrative rows — RECORDED, DEFERRED

`openLgDetail()` renders settled Versus results dated **Wk 6** (`+$45`, `−$40`) and **Wk 7**
(`+$40`), plus a Wk 6 Pool row, in a prototype whose current week is 5. Settled outcomes of weeks
that have not occurred.

**Ruling:** invalid illustrative data. **Must not survive the Rev3.1 rebuild.**

- No further repair or rebasing pass now.
- **Do not derive POR or mechanics from these rows.**
- Replaced or simplified when Rev3.1 is built from coherent deterministic state.

## Open items carried

| Ref | Item | Status |
|---|---|---|
| **UIL1-M1** | Layer 2 Wallet framing | **RULED** — explain, don't prove |
| Future-week settled rows | Wk 6/Wk 7 results at Week 5 | **RECORDED · DEFERRED to rebuild** |
| **F3** | In Play components | **CLOSED** — amounts illustrative, not POR |
| **F7** | Mode propagation | OPEN · built inside UI-VS-1 |
| Top-Off Cap anchor | Numeric anchor | UNRESOLVED · standing |

---

## Artifact state

- `FantasyStakes_UIUX_Prototype_Rev3_0.html` — `f8b3edac…de5c6cea`, 130,349 bytes.
  **Immutable.** Committed at `ff70f56`.
- `FantasyStakes_UIUX_Prototype_Rev3_1_partial.html` — `087ba445…f236f5f`, 126,691 bytes.
  **Intermediate.** Not Rev3.1. Not committed.
